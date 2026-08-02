"""End-to-end golden path and basic controller contracts."""

from __future__ import annotations

import stat
import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.controller import Controller
from v5_support import V5TestCase, make_repository


class GoldenPathTests(V5TestCase):
    def test_golden_path_lite(self) -> None:
        task_id = self.start_lite("Add a bounded feature")
        state = self.controller.show(task_id)
        self.assertEqual(state.status, "INTAKE")
        self.assertEqual(state.current_node, "preflight")
        self.assertEqual(state.revision, 0)
        self.assertEqual(state.workflow_id, "lite")
        self.assertEqual(len(state.repositories), 1)
        self.assertEqual(
            state.repositories[0].path,
            str(self.repository.resolve()),
        )

        projection = self.controller.next(task_id)
        self.assertEqual(projection["requirement"], "Add a bounded feature")
        self.assertEqual(projection["action"]["action_id"], "task.preflight")
        self.assertFalse(projection["done"])
        self.assertEqual(
            projection["repo_context"]["path"],
            str(self.repository.resolve()),
        )

        result = self.controller.apply(task_id, "task.preflight", {})
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], "IMPLEMENTING")
        self.assertEqual(receipt["current_node"], "implement")
        self.assertEqual(receipt["committed_revision"], 1)
        self.assertIn("projection", result)
        preflight = self.controller.show(task_id).repositories[0].preflight
        self.assertIsNotNone(preflight)
        self.assertEqual(preflight["schema"], "dev-flow-v5-git-preflight/v1")
        self.assertTrue(preflight["clean"])

        result = self.controller.apply(
            task_id, "task.implementation.complete", {"summary": "implemented"}
        )
        self.assertEqual(result["receipt"]["status"], "VERIFYING")

        result = self.controller.apply(
            task_id,
            "evidence.test.record",
            {"passed": True, "command": "python3 -m unittest"},
        )
        self.assertEqual(result["receipt"]["status"], "DONE")
        self.assertEqual(result["receipt"]["current_node"], "done")

        projection = self.controller.next(task_id)
        self.assertTrue(projection["done"])
        self.assertIsNone(projection["action"])
        self.assertEqual(projection["status"], "DONE")
        self.assertEqual(len(self.controller.show(task_id).evidence), 2)

    def test_data_dir_inside_repository_rejected(self) -> None:
        controller = Controller(str(self.repository / "data"))
        with self.assertRaises(DevFlowError) as context:
            controller.start(
                requirement="bad data dir",
                workflow="lite",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "DATA_DIR_INSIDE_REPOSITORY")
        self.assertFalse((self.repository / "data" / "tasks").exists())

    def test_data_dir_equal_to_repository_rejected(self) -> None:
        controller = Controller(str(self.repository))
        with self.assertRaises(DevFlowError) as context:
            controller.start(
                requirement="equal paths",
                workflow="lite",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "DATA_DIR_INSIDE_REPOSITORY")
        self.assertFalse((self.repository / "tasks").exists())

    def test_repository_inside_data_dir_rejected(self) -> None:
        data_root = self.root / "containing-data"
        data_root.mkdir()
        repository = make_repository(data_root, "nested-repository")
        controller = Controller(str(data_root))

        with self.assertRaises(DevFlowError) as context:
            controller.start(
                requirement="nested repository",
                workflow="lite",
                repository=str(repository),
            )
        self.assertEqual(context.exception.code, "DATA_DIR_INSIDE_REPOSITORY")
        self.assertFalse((data_root / "tasks").exists())

    def test_state_file_permissions(self) -> None:
        task_id = self.start_lite()
        state_path = (
            Path(self.data_dir) / "tasks" / task_id / "state.json"
        )
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        task_dir = state_path.parent
        self.assertEqual(stat.S_IMODE(task_dir.stat().st_mode), 0o700)

    def test_cancel_end_to_end(self) -> None:
        task_id = self.start_lite("Cancel this")
        result = self.controller.cancel(task_id, reason="changed my mind")
        self.assertEqual(result["receipt"]["status"], "CANCELLED")
        self.assertTrue(result["projection"]["done"])
        self.assertIsNone(result["projection"]["action"])
        state = self.controller.show(task_id)
        self.assertEqual(state.current_node, "cancelled")
        self.assertEqual(len(state.evidence), 1)
        self.assertEqual(state.evidence[0]["payload"], {"reason": "changed my mind"})

    def test_apply_returns_receipt_and_projection(self) -> None:
        task_id = self.start_lite()
        result = self.controller.apply(task_id, "task.preflight", {})
        self.assertIn("receipt", result)
        self.assertIn("projection", result)
        self.assertEqual(result["projection"]["action"]["action_id"],
                         "task.implementation.complete")

    def test_explicit_task_id(self) -> None:
        state = self.controller.start(
            requirement="named task",
            workflow="lite",
            repository=str(self.repository),
            task_id="task-custom",
        )
        self.assertEqual(state.task_id, "task-custom")
        self.assertEqual(self.controller.show("task-custom").task_id, "task-custom")


if __name__ == "__main__":
    unittest.main()
