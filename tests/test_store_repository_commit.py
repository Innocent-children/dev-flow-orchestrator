"""Store-side repository mutation commit authority."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.delivery import resource_requests, validate_action_binding
from dev_flow_orchestrator.engine import (
    apply_current_action,
    plan_current_action,
    validate_action_payload,
)
from dev_flow_orchestrator.model import DevFlowError, RepositoryRecord
from dev_flow_orchestrator.product import PLUGIN_DATA_NAMESPACE
from dev_flow_orchestrator.store import RepositoryMutationPlan
from support import RepositoryTestCase, make_repository


class StoreRepositoryCommitTests(RepositoryTestCase):
    def state_path(self, task_id: str) -> Path:
        return (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

    def apply_prepare(self, task_id: str):
        projection = self.controller.next(task_id)
        action_id = projection["action"]["action_id"]
        binding = validate_action_binding(projection["action"]["binding"])
        expected_revision = binding["task_revision"]

        def prepare(current, definition):
            contract, action_plan = plan_current_action(
                current,
                definition,
                action_id,
                expected_revision,
            )
            payload = validate_action_payload(contract, {})
            requested = resource_requests(
                payload,
                repository_ids=tuple(
                    repository.repository_id
                    for repository in current.repositories
                ),
            )

            def capture():
                return self.controller._snapshot(
                    current,
                    additional_resources=requested,
                )

            def derive(snapshot):
                return apply_current_action(
                    current,
                    definition,
                    contract,
                    action_plan,
                    payload=payload,
                    binding=binding,
                    snapshot=snapshot,
                    timestamp="2026-08-09T00:00:00Z",
                )

            return RepositoryMutationPlan(action_id, capture, derive)

        return expected_revision, prepare

    def test_commit_uses_fixed_lock_and_phase_order_through_observation(self) -> None:
        task_id = self.start_lite("fixed commit authority")
        expected_revision, base_prepare = self.apply_prepare(task_id)
        events = []
        capture_count = 0

        @contextmanager
        def recording_lock(path):
            events.append(("enter", path.name))
            try:
                yield
            finally:
                events.append(("exit", path.name))

        def prepare(current, definition):
            plan = base_prepare(current, definition)

            def capture():
                nonlocal capture_count
                capture_count += 1
                events.append(("capture", capture_count))
                return plan.capture()

            return RepositoryMutationPlan(plan.action_id, capture, plan.derive)

        def phase_hook(phase):
            events.append(("phase", phase))

        with patch(
            "dev_flow_orchestrator.store.exclusive_file_lock",
            side_effect=recording_lock,
        ):
            committed = self.controller.store.commit_repository_mutation(
                task_id,
                expected_revision,
                prepare,
                phase_hook=phase_hook,
            )

        entered = [value for kind, value in events if kind == "enter"]
        exited = [value for kind, value in events if kind == "exit"]
        self.assertEqual(entered[0], "membership.lock")
        self.assertTrue(entered[1].startswith("repository-"))
        self.assertEqual(entered[-1], task_id + ".lock")
        self.assertEqual(exited, list(reversed(entered)))
        self.assertEqual(
            [event for event in events if event[0] in {"capture", "phase"}],
            [
                ("capture", 1),
                ("phase", "before-revalidation"),
                ("capture", 2),
                ("phase", "after-revalidation"),
                ("phase", "before-observation"),
                ("capture", 3),
            ],
        )
        self.assertEqual(
            committed.action_id,
            committed.state.records[0]["producer"]["action_id"],
        )
        self.assertEqual(committed.state.revision, 1)
        self.assertEqual(committed.observation, committed.committed_snapshot)
        self.assertIsNone(committed.observation_error_code)
        self.assertTrue(committed.observed_at.endswith("Z"))
        self.assertEqual(self.controller.store.load(task_id).revision, 1)

    def test_revalidation_mismatch_is_bounded_and_does_not_write(self) -> None:
        task_id = self.start_lite("reject prewrite drift")
        expected_revision, prepare = self.apply_prepare(task_id)
        before = self.state_path(task_id).read_bytes()

        def phase_hook(phase):
            if phase == "before-revalidation":
                (self.repository / "a.txt").write_text(
                    "changed before revalidation\n",
                    encoding="utf-8",
                )

        with self.assertRaises(DevFlowError) as context:
            self.controller.store.commit_repository_mutation(
                task_id,
                expected_revision,
                prepare,
                phase_hook=phase_hook,
            )

        self.assertEqual(context.exception.code, "SNAPSHOT_UNSTABLE")
        self.assertEqual(context.exception.details["phase"], "revalidation")
        self.assertEqual(
            context.exception.details["repository_ids"],
            [self.controller.show(task_id).repositories[0].repository_id],
        )
        self.assertEqual(self.state_path(task_id).read_bytes(), before)
        self.assertEqual(self.controller.show(task_id).revision, 0)

    def test_postwrite_observation_failure_does_not_reclassify_commit(self) -> None:
        task_id = self.start_lite("committed despite observation failure")
        expected_revision, prepare = self.apply_prepare(task_id)

        def phase_hook(phase):
            if phase == "before-observation":
                raise DevFlowError(
                    "SNAPSHOT_UNSTABLE",
                    "secret-observation-message-7b9139",
                    details={"secret": "secret-observation-detail-7b9139"},
                )

        committed = self.controller.store.commit_repository_mutation(
            task_id,
            expected_revision,
            prepare,
            phase_hook=phase_hook,
        )

        self.assertEqual(committed.state.revision, 1)
        self.assertIsNone(committed.observation)
        self.assertIsNone(committed.observed_at)
        self.assertEqual(committed.observation_error_code, "SNAPSHOT_UNSTABLE")
        self.assertNotIn("secret-observation", repr(committed))
        self.assertEqual(self.controller.store.load(task_id).revision, 1)

    def test_residual_drift_commits_and_returns_new_live_observation(self) -> None:
        task_id = self.start_lite("observe residual drift")
        expected_revision, prepare = self.apply_prepare(task_id)

        def phase_hook(phase):
            if phase == "after-revalidation":
                (self.repository / "a.txt").write_text(
                    "changed after revalidation\n",
                    encoding="utf-8",
                )

        committed = self.controller.store.commit_repository_mutation(
            task_id,
            expected_revision,
            prepare,
            phase_hook=phase_hook,
        )

        self.assertEqual(committed.state.revision, 1)
        self.assertIsNotNone(committed.observation)
        self.assertNotEqual(committed.observation, committed.committed_snapshot)
        self.assertIsNone(committed.observation_error_code)
        self.assertTrue(committed.observed_at.endswith("Z"))
        self.assertEqual(self.controller.store.load(task_id).revision, 1)

    def test_cancellation_checkpoint_precedes_derivation_and_write(self) -> None:
        task_id = self.start_lite("cancel at commit checkpoint")
        expected_revision, base_prepare = self.apply_prepare(task_id)
        before = self.state_path(task_id).read_bytes()
        derived = []

        def prepare(current, definition):
            plan = base_prepare(current, definition)

            def derive(snapshot):
                derived.append(True)
                return plan.derive(snapshot)

            return RepositoryMutationPlan(plan.action_id, plan.capture, derive)

        def cancel():
            raise DevFlowError("OPERATION_CANCELLED", "cancelled")

        with self.assertRaises(DevFlowError) as context:
            self.controller.store.commit_repository_mutation(
                task_id,
                expected_revision,
                prepare,
                cancellation_check=cancel,
            )

        self.assertEqual(context.exception.code, "OPERATION_CANCELLED")
        self.assertEqual(derived, [])
        self.assertEqual(self.state_path(task_id).read_bytes(), before)

    def test_authority_identity_order_is_canonical_and_duplicate_fails(self) -> None:
        other = make_repository(self.root, "other")
        records = (
            RepositoryRecord(
                "caller-z",
                str(other),
                str(other / ".git"),
                str(other / ".git"),
            ),
            RepositoryRecord(
                "caller-a",
                str(self.repository),
                str(self.repository / ".git"),
                str(self.repository / ".git"),
            ),
        )

        forward = self.controller.store._repository_authorities(records)
        reverse = self.controller.store._repository_authorities(tuple(reversed(records)))

        self.assertEqual(forward, reverse)
        self.assertEqual(
            [authority.identity for authority in forward],
            sorted(authority.identity for authority in forward),
        )
        self.assertTrue(all(
            authority.lock_path.parent == self.controller.store.locks_root
            and authority.lock_path.name.startswith("repository-")
            and authority.lock_path.suffix == ".lock"
            for authority in forward
        ))
        with self.assertRaises(DevFlowError) as context:
            self.controller.store._repository_authorities(
                (
                    records[0],
                    RepositoryRecord(
                        "different-caller-id",
                        records[0].path,
                        records[0].git_worktree_dir,
                        records[0].git_common_dir,
                    ),
                )
            )
        self.assertEqual(context.exception.code, "REPOSITORY_DUPLICATE")

    def test_observation_error_code_does_not_expose_arbitrary_exception(self) -> None:
        self.assertEqual(
            self.controller.store._observation_error_code(
                RuntimeError("secret path: {}".format(self.repository))
            ),
            "OBSERVATION_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
