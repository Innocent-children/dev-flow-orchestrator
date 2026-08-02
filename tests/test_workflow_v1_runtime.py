"""Runtime compatibility contracts for absolute-path workflow-v1 documents."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError, json_value
from support import RepositoryTestCase


CUSTOM_STATUS_FLOW = """\
schema: dev-flow-workflow/v1
id: custom-status
version: 5
entry: preflight
nodes:
  preflight:
    action_id: task.preflight
    handler: preflight
    target: {node: implement, status: DONE}
    effect: git.inspect-repository
  implement:
    action_id: task.implementation.complete
    handler: evidence.record
    target: {node: complete, status: COMPLETE}
    payload: {summary: string}
  complete: {terminal: true}
"""

OBJECT_PAYLOAD_FLOW = """\
schema: dev-flow-workflow/v1
id: object-payload
version: 5
entry: preflight
nodes:
  preflight:
    action_id: task.preflight
    handler: preflight
    target: {node: record, status: IMPLEMENTING}
    effect: git.inspect-repository
  record:
    action_id: task.record
    handler: evidence.record
    target: {node: done, status: DONE}
    payload: {metadata: object}
  done: {terminal: true}
"""

OPAQUE_DRIVER_FLOW = """\
schema: dev-flow-workflow/v1
id: opaque-driver
version: 5
entry: preflight
nodes:
  preflight:
    action_id: task.preflight
    handler: preflight
    target: {node: spec, status: SPECING}
    effect: git.inspect-repository
  spec:
    action_id: record.spec
    handler: evidence.record
    target: {node: summarize, status: SUMMARIZING}
    payload: {change_id: string}
    driver:
      tool: openspec
      nested:
        mode: opaque
  summarize:
    action_id: record.summary
    handler: evidence.record
    target: {node: done, status: DONE}
    payload: {summary: string}
  done: {terminal: true}
"""


class WorkflowV1RuntimeTests(RepositoryTestCase):
    def write_flow(self, text: str, name: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def start_flow(self, path: Path) -> str:
        return self.controller.start(
            requirement="Workflow-v1 compatibility",
            workflow=str(path),
            repository=str(self.repository),
        ).task_id

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def test_relative_custom_path_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="Relative workflow path",
                workflow="relative/flow.yaml",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_missing_absolute_custom_path_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="Missing workflow path",
                workflow=str(self.root / "missing.yaml"),
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_driver_configuration_is_opaque_through_apply_and_next(self) -> None:
        task_id = self.start_flow(
            self.write_flow(OPAQUE_DRIVER_FLOW, "opaque-driver.yaml")
        )
        self.apply_current(task_id, {})
        expected_driver = {
            "tool": "openspec",
            "nested": {"mode": "opaque"},
        }

        driver_projection = self.controller.next(task_id)
        self.assertEqual(driver_projection["action"]["action_id"], "record.spec")
        self.assertEqual(driver_projection["action"]["driver"], expected_driver)
        self.assertIsNotNone(driver_projection["action"]["binding"])

        result = self.controller.apply(
            task_id,
            driver_projection["action"]["action_id"],
            {"change_id": "changes/abc-1"},
            binding=driver_projection["action"]["binding"],
        )
        driver_record = self.controller.show(task_id).records[-1]
        self.assertEqual(
            json_value(driver_record["producer"]["driver"]),
            {"capability": expected_driver, "result": None},
        )

        followup = result["projection"]
        refreshed = self.controller.next(task_id)
        self.assertEqual(followup["action"], refreshed["action"])
        self.assertEqual(refreshed["action"]["action_id"], "record.summary")
        self.assertIsNone(refreshed["action"]["driver"])
        self.assertIsNotNone(refreshed["action"]["binding"])
        self.assertEqual(
            refreshed["action"]["inputs"][0]["record_id"],
            driver_record["record_id"],
        )

        terminal = self.controller.apply(
            task_id,
            refreshed["action"]["action_id"],
            {"summary": "Driver result recorded"},
            binding=refreshed["action"]["binding"],
        )
        self.assertTrue(terminal["projection"]["done"])
        self.assertIsNone(terminal["projection"]["action"])

    def test_terminal_node_not_status_controls_activity(self) -> None:
        task_id = self.start_flow(
            self.write_flow(CUSTOM_STATUS_FLOW, "custom-status.yaml")
        )
        self.apply_current(task_id, {})

        intermediate = self.controller.show(task_id)
        self.assertEqual(intermediate.status, "DONE")
        self.assertEqual(intermediate.current_node, "implement")
        self.assertEqual(
            [item.task_id for item in self.controller.tasks_for_path(str(self.repository))],
            [task_id],
        )

        result = self.apply_current(task_id, {"summary": "complete"})
        self.assertEqual(result["projection"]["status"], "COMPLETE")
        self.assertTrue(result["projection"]["done"])
        self.assertEqual(self.controller.tasks_for_path(str(self.repository)), ())

    def test_object_payload_persists_and_replays_after_restart(self) -> None:
        task_id = self.start_flow(
            self.write_flow(OBJECT_PAYLOAD_FLOW, "object-payload.yaml")
        )
        self.apply_current(task_id, {})
        payload = {
            "metadata": {
                "source": "custom-workflow",
                "flags": {"verified": True},
                "items": [1, "two"],
            }
        }

        result = self.apply_current(task_id, payload)

        self.assertEqual(result["receipt"]["status"], "DONE")
        restarted = Controller(self.data_dir)
        persisted = restarted.show(task_id)
        self.assertEqual(json_value(persisted.records[-1]["payload"]), payload)
        self.assertTrue(restarted.next(task_id)["done"])

    def test_invalid_object_payload_is_rejected_atomically(self) -> None:
        task_id = self.start_flow(
            self.write_flow(OBJECT_PAYLOAD_FLOW, "object-invalid.yaml")
        )
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                {"metadata": []},
                binding=projection["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
        self.assertEqual(self.controller.show(task_id), before)


if __name__ == "__main__":
    unittest.main()
