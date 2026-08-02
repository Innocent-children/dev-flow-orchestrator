"""TaskStore binds state identity, paths and append-only transitions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase


class StoreIntegrityTests(V5TestCase):
    def test_state_symlink_is_rejected(self) -> None:
        first = self.start_lite("first")
        second = self.start_lite("second")
        first_path = Path(self.data_dir) / "tasks" / first / "state.json"
        second_path = Path(self.data_dir) / "tasks" / second / "state.json"
        first_path.unlink()
        first_path.symlink_to(second_path)
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(first)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_dangling_state_symlink_is_rejected(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        state_path.unlink()
        state_path.symlink_to(self.root / "missing-state.json")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_task_directory_symlink_is_rejected(self) -> None:
        existing = self.start_lite()
        tasks = Path(self.data_dir) / "tasks"
        alias = tasks / "task-alias"
        alias.symlink_to(tasks / existing, target_is_directory=True)
        with self.assertRaises(DevFlowError) as context:
            self.controller.show("task-alias")
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_lock_symlink_is_rejected(self) -> None:
        task_id = self.start_lite()
        lock = Path(self.data_dir) / "locks" / (task_id + ".lock")
        lock.unlink()
        lock.symlink_to(self.root / "lock-target")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_mutation_cannot_change_requirement(self) -> None:
        task_id = self.start_lite()
        before = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                0,
                lambda state: replace(
                    state,
                    requirement="rewritten",
                    revision=1,
                    updated_at="2026-08-01T00:00:00Z",
                    status="IMPLEMENTING",
                    current_node="implement",
                    repositories=(
                        replace(state.repositories[0], preflight={"clean": True}),
                    ),
                ),
            )
        self.assertEqual(context.exception.code, "STATE_WRITE_INVALID")
        self.assertEqual(self.controller.show(task_id), before)

    def test_mutation_with_invalid_shape_fails_before_write(self) -> None:
        task_id = self.start_lite()
        before = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                0,
                lambda state: replace(
                    state,
                    revision=1,
                    updated_at="2026-08-01T00:00:00Z",
                    status="",
                    current_node="implement",
                    repositories=(
                        replace(state.repositories[0], preflight={"clean": True}),
                    ),
                ),
            )
        self.assertEqual(context.exception.code, "STATE_WRITE_INVALID")
        self.assertEqual(
            context.exception.details["reason"],
            "state_shape_invalid",
        )
        self.assertEqual(self.controller.show(task_id), before)

    def test_mutation_cannot_rewrite_existing_evidence(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        self.controller.apply(
            task_id,
            "task.implementation.complete",
            {"summary": "original"},
        )
        before = self.controller.show(task_id)
        timestamp = "2026-08-01T00:00:00Z"
        rewritten = dict(before.evidence[0])
        rewritten["payload"] = {"summary": "rewritten"}
        test_record = {
            "schema": "dev-flow-v5-node-output/v1",
            "action_id": "evidence.test.record",
            "node_id": "verify",
            "recorded_at": timestamp,
            "payload": {"passed": True, "command": "focused tests"},
        }
        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                before.revision,
                lambda state: replace(
                    state,
                    revision=state.revision + 1,
                    updated_at=timestamp,
                    status="DONE",
                    current_node="done",
                    evidence=(rewritten, test_record),
                ),
            )
        self.assertEqual(context.exception.code, "STATE_WRITE_INVALID")
        self.assertEqual(self.controller.show(task_id), before)


if __name__ == "__main__":
    unittest.main()
