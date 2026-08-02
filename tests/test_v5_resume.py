"""Task state survives process restarts; tampering and old schemas fail closed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase


class ResumeTests(V5TestCase):
    def test_new_controller_resumes_at_same_node(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        fresh = Controller(self.data_dir)
        projection = fresh.next(task_id)
        self.assertEqual(projection["requirement"], "A test requirement")
        self.assertEqual(projection["action"]["action_id"],
                         "task.implementation.complete")
        self.assertEqual(projection["revision"], 1)
        result = fresh.apply(
            task_id, "task.implementation.complete", {"summary": "resumed"}
        )
        self.assertEqual(result["receipt"]["current_node"], "verify")

    def test_tampered_workflow_identity_fails(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["workflow"]["identity"] = "0" * 64
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "WORKFLOW_IDENTITY_MISMATCH")

    def test_corrupt_state_json_fails(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        state_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_v4_schema_state_fails(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["schema_version"] = 4
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_missing_task_state_file(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.show("task-ghost")
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_inventory_omits_orphan_but_direct_load_remains_strict(self) -> None:
        healthy = self.start_lite("healthy")
        orphan = "task-orphan"
        (Path(self.data_dir) / "tasks" / orphan).mkdir()

        self.assertEqual(
            tuple(state.task_id for state in self.controller.list_tasks()),
            (healthy,),
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(orphan)
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_inventory_omits_invalid_state_but_direct_load_is_strict(self) -> None:
        healthy = self.start_lite("healthy")
        invalid = self.start_lite("invalid")
        state_path = Path(self.data_dir) / "tasks" / invalid / "state.json"
        state_path.write_text("{not json", encoding="utf-8")

        self.assertEqual(
            tuple(state.task_id for state in self.controller.list_tasks()),
            (healthy,),
        )
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(invalid)
        self.assertEqual(context.exception.code, "STATE_INVALID")

    def test_inventory_root_error_remains_strict(self) -> None:
        data_root = self.root / "strict-inventory"
        target = self.root / "inventory-target"
        data_root.mkdir()
        target.mkdir()
        (data_root / "tasks").symlink_to(target, target_is_directory=True)
        controller = Controller(str(data_root))

        with self.assertRaises(DevFlowError) as context:
            controller.list_tasks()
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_inventory_locks_root_error_remains_strict(self) -> None:
        self.start_lite("healthy")
        locks_root = Path(self.data_dir) / "locks"
        target = self.root / "locks-target"
        locks_root.rename(target)
        locks_root.symlink_to(target, target_is_directory=True)

        with self.assertRaises(DevFlowError) as context:
            self.controller.list_tasks()
        self.assertEqual(context.exception.code, "DATA_PATH_UNSAFE")

    def test_impossible_node_revision_and_status_fail_closed(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["current_node"] = "done"
        value["status"] = "DONE"
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "STATE_INVALID")
        self.assertEqual(
            context.exception.details["reason"], "current_node_path_mismatch"
        )

    def test_state_path_and_embedded_task_id_must_match(self) -> None:
        first = self.start_lite("first")
        second = self.start_lite("second")
        first_path = Path(self.data_dir) / "tasks" / first / "state.json"
        second_path = Path(self.data_dir) / "tasks" / second / "state.json"
        first_path.write_bytes(second_path.read_bytes())
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(first)
        self.assertEqual(context.exception.code, "STATE_INVALID")
        self.assertEqual(context.exception.details["expected_task_id"], first)
        self.assertEqual(context.exception.details["stored_task_id"], second)

    def test_preflight_cannot_be_forged_as_evidence(self) -> None:
        task_id = self.start_lite()
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        timestamp = "2026-08-01T00:00:00Z"
        value.update({
            "revision": 1,
            "updated_at": timestamp,
            "status": "IMPLEMENTING",
            "current_node": "implement",
            "evidence": [{
                "schema": "dev-flow-v5-node-output/v1",
                "action_id": "task.preflight",
                "node_id": "preflight",
                "recorded_at": timestamp,
                "payload": {},
            }],
        })
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.show(task_id)
        self.assertEqual(context.exception.code, "STATE_INVALID")
        self.assertEqual(context.exception.details["reason"], "preflight_state_invalid")


if __name__ == "__main__":
    unittest.main()
