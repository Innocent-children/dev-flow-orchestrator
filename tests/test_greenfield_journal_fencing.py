from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.journal import EffectJournal
from dev_flow_orchestrator.model import DevFlowError, MutationPlan


class GreenfieldJournalFencingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.journal = EffectJournal(self.root / "data")
        self.task_id = "journal-fencing"
        self.plan = MutationPlan(
            action_id="workspace.prepare",
            task_id=self.task_id,
            expected_revision=4,
            source_node="workspace",
            target_node="implement",
            effect_kind="workspace.prepare",
            allowed_writes=("/revision", "/effects"),
            authority_id="confirm-" + ("a" * 64),
            actor_id="session-journal-fencing",
        )
        self.binding = self.plan.binding

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _claim(self) -> dict:
        return self.journal.claim(
            task_id=self.task_id,
            plan=self.plan,
            payload={},
            requests={"destination": str(self.root / "workspace")},
            authority_binding_digest="b" * 64,
            expected_attempt=1,
            timestamp="2026-07-31T00:00:00Z",
        )

    def test_execution_fence_serializes_same_task_and_binding(self) -> None:
        attempted = threading.Event()
        entered = threading.Event()
        released = threading.Event()

        def contender() -> None:
            attempted.set()
            with self.journal.execution_fence(self.task_id, self.binding):
                entered.set()
            released.set()

        with self.journal.execution_fence(self.task_id, self.binding):
            claimed = self._claim()
            self.assertEqual(claimed["phase"], "CLAIMED")
            self.assertEqual(
                self.journal.get(self.task_id, self.binding)["phase"],
                "CLAIMED",
            )
            thread = threading.Thread(target=contender)
            thread.start()
            self.assertTrue(attempted.wait(1.0))
            self.assertFalse(entered.wait(0.1))

        self.assertTrue(entered.wait(1.0))
        self.assertTrue(released.wait(1.0))
        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())

    def test_execution_fence_is_keyed_by_binding(self) -> None:
        other_plan = MutationPlan(
            action_id="workspace.prepare",
            task_id=self.task_id,
            expected_revision=5,
            source_node="workspace",
            target_node="implement",
            effect_kind="workspace.prepare",
            allowed_writes=("/revision", "/effects"),
        )
        entered = threading.Event()

        def contender() -> None:
            with self.journal.execution_fence(
                self.task_id,
                other_plan.binding,
            ):
                entered.set()

        with self.journal.execution_fence(self.task_id, self.binding):
            thread = threading.Thread(target=contender)
            thread.start()
            self.assertTrue(entered.wait(1.0))

        thread.join(timeout=1.0)
        self.assertFalse(thread.is_alive())

    def test_receipt_and_commit_replays_are_idempotent(self) -> None:
        self._claim()
        receipt = {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "path": str(self.root / "workspace"),
        }
        stored_receipt = self.journal.mark_receipt(
            self.task_id,
            self.binding,
            receipt,
            "2026-07-31T00:01:00Z",
        )
        replayed_receipt = self.journal.mark_receipt(
            self.task_id,
            self.binding,
            receipt,
            "2026-07-31T00:02:00Z",
        )
        self.assertEqual(replayed_receipt, stored_receipt)
        self.assertEqual(
            replayed_receipt["updated_at"],
            "2026-07-31T00:01:00Z",
        )

        committed = self.journal.mark_committed(
            self.task_id,
            self.binding,
            5,
            "2026-07-31T00:03:00Z",
        )
        replayed_after_commit = self.journal.mark_receipt(
            self.task_id,
            self.binding,
            receipt,
            "2026-07-31T00:04:00Z",
        )
        self.assertEqual(replayed_after_commit, committed)

        replayed_commit = self.journal.mark_committed(
            self.task_id,
            self.binding,
            5,
            "2026-07-31T00:05:00Z",
        )
        self.assertEqual(replayed_commit, committed)
        self.assertEqual(
            replayed_commit["updated_at"],
            "2026-07-31T00:03:00Z",
        )

    def test_receipt_and_commit_replays_reject_conflicts(self) -> None:
        self._claim()
        receipt = {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "path": str(self.root / "workspace"),
        }
        self.journal.mark_receipt(
            self.task_id,
            self.binding,
            receipt,
            "2026-07-31T00:01:00Z",
        )
        with self.assertRaises(DevFlowError) as receipt_error:
            self.journal.mark_receipt(
                self.task_id,
                self.binding,
                dict(receipt, path=str(self.root / "other")),
                "2026-07-31T00:02:00Z",
            )
        self.assertEqual(
            receipt_error.exception.code,
            "EFFECT_RECEIPT_CONFLICT",
        )

        self.journal.mark_committed(
            self.task_id,
            self.binding,
            5,
            "2026-07-31T00:03:00Z",
        )
        with self.assertRaises(DevFlowError) as committed_receipt_error:
            self.journal.mark_receipt(
                self.task_id,
                self.binding,
                dict(receipt, path=str(self.root / "other")),
                "2026-07-31T00:04:00Z",
            )
        self.assertEqual(
            committed_receipt_error.exception.code,
            "EFFECT_RECEIPT_CONFLICT",
        )

        with self.assertRaises(DevFlowError) as commit_error:
            self.journal.mark_committed(
                self.task_id,
                self.binding,
                6,
                "2026-07-31T00:05:00Z",
            )
        self.assertEqual(
            commit_error.exception.code,
            "EFFECT_COMMIT_CONFLICT",
        )


if __name__ == "__main__":
    unittest.main()
