"""Illegal transitions, actions and payloads are rejected without mutation."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase


class IllegalTransitionTests(V5TestCase):
    def test_wrong_action_at_node(self) -> None:
        task_id = self.start_lite()
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id, "evidence.test.record", {"passed": True}
            )
        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id).revision, 0)

    def test_apply_after_done(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        self.controller.apply(task_id, "task.implementation.complete", {"summary": "x"})
        self.controller.apply(
            task_id, "evidence.test.record", {"passed": True, "command": "c"}
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(task_id, "task.preflight", {})
        self.assertEqual(context.exception.code, "NO_ACTION_AVAILABLE")

    def test_cancel_after_done(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        self.controller.apply(task_id, "task.implementation.complete", {"summary": "x"})
        self.controller.apply(
            task_id, "evidence.test.record", {"passed": True, "command": "c"}
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="too late")
        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")

    def test_unknown_payload_field(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                "task.implementation.complete",
                {"summary": "x", "extra": 1},
            )
        self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
        self.assertIn("extra", str(context.exception.details))

    def test_missing_required_field(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(task_id, "task.implementation.complete", {})
        self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
        self.assertIn("summary", context.exception.details["missing_fields"])

    def test_wrong_payload_type(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id, "task.implementation.complete", {"summary": 42}
            )
        self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")

    def test_test_not_passing(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        self.controller.apply(task_id, "task.implementation.complete", {"summary": "x"})
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id, "evidence.test.record", {"passed": False, "command": "c"}
            )
        self.assertEqual(context.exception.code, "TEST_NOT_PASSING")
        self.assertEqual(self.controller.show(task_id).revision, 2)

    def test_apply_missing_task(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.apply("task-nope", "task.preflight", {})
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_start_with_empty_requirement(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="   ",
                workflow="lite",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "REQUIREMENT_INVALID")

    def test_start_unknown_workflow(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="x",
                workflow="full",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
