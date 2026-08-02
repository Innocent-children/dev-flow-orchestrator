"""Generation-current controller boundary contracts."""

from __future__ import annotations

import stat
import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from support import RepositoryTestCase, make_repository


class ControllerContractTests(RepositoryTestCase):
    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def test_data_directory_must_be_disjoint_from_repository(self) -> None:
        cases = []

        inside = self.repository / "data"
        cases.append((Controller(str(inside)), self.repository, inside / "tasks"))

        cases.append(
            (Controller(str(self.repository)), self.repository, self.repository / "tasks")
        )

        data_root = self.root / "containing-data"
        data_root.mkdir()
        nested_repository = make_repository(data_root, "nested-repository")
        cases.append((Controller(str(data_root)), nested_repository, data_root / "tasks"))

        for controller, repository, state_root in cases:
            with self.subTest(data_dir=str(controller.store.root), repository=str(repository)):
                with self.assertRaises(DevFlowError) as context:
                    controller.start(
                        requirement="Keep state outside the repository",
                        workflow="lite",
                        repository=str(repository),
                    )
                self.assertEqual(
                    context.exception.code, "DATA_DIR_INSIDE_REPOSITORY"
                )
                self.assertFalse(state_root.exists())

    def test_state_paths_are_private(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"

        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(state_path.parent.stat().st_mode), 0o700)

    def test_explicit_task_id_is_persisted(self) -> None:
        state = self.controller.start(
            requirement="Named task",
            workflow="lite",
            repository=str(self.repository),
            task_id="task-custom",
        )

        self.assertEqual(state.task_id, "task-custom")
        self.assertEqual(self.controller.show("task-custom").task_id, "task-custom")

    def test_wrong_action_is_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                "verification.record",
                {},
                binding=projection["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id), before)

    def test_invalid_payloads_are_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        cases = (
            ({"summary": "x", "extra": 1}, "extra"),
            ({}, "summary"),
            ({"summary": 42}, None),
        )

        for payload, detail in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.apply(
                        task_id,
                        projection["action"]["action_id"],
                        payload,
                        binding=projection["action"]["binding"],
                    )
                self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
                if detail is not None:
                    self.assertIn(detail, str(context.exception.details))
                self.assertEqual(self.controller.show(task_id), before)

    def test_stale_apply_after_terminal_returns_fresh_conflict(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        pending = self.controller.next(task_id)
        self.controller.cancel(task_id, reason="Stop before implementation")
        terminal = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                pending["action"]["action_id"],
                {"summary": "too late"},
                binding=pending["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        fresh = context.exception.details["projection"]
        self.assertEqual(fresh["revision"], terminal.revision)
        self.assertEqual(fresh["status"], "CANCELLED")
        self.assertTrue(fresh["done"])
        self.assertIsNone(fresh["action"])
        self.assertEqual(self.controller.show(task_id), terminal)

    def test_cancel_after_terminal_state_is_rejected(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        self.controller.cancel(task_id, reason="Stop once")

        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="Stop twice")

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")

    def test_missing_task_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.next("task-nope")
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_empty_requirement_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="   ",
                workflow="lite",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "REQUIREMENT_INVALID")

    def test_truly_unknown_workflow_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="Unknown workflow",
                workflow="workflow-that-does-not-exist",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_apply_returns_current_receipt_and_projection(self) -> None:
        task_id = self.start_lite()
        projected = self.controller.next(task_id)
        result = self.controller.apply(
            task_id,
            projected["action"]["action_id"],
            {},
            binding=projected["action"]["binding"],
        )

        self.assertEqual(
            result["receipt"],
            {
                "schema": "dev-flow-v6-receipt/v1",
                "task_id": task_id,
                "action_id": "task.preflight",
                "committed_revision": 1,
                "status": "IMPLEMENTING",
                "current_node": "implement",
            },
        )
        self.assertEqual(result["projection"]["revision"], 1)
        self.assertEqual(
            result["projection"]["action"]["action_id"], "implementation.record"
        )


if __name__ == "__main__":
    unittest.main()
