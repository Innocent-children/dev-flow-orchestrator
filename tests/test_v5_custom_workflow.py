"""Custom workflow YAML files run end-to-end with zero code difference."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase

MINIMAL_FLOW = """\
schema: dev-flow-workflow/v1
id: minimal
version: 5
description: "Three-node flow without a verify gate."
entry: preflight
nodes:
  preflight:
    action_id: task.preflight
    handler: preflight
    target: {node: implement, status: IMPLEMENTING}
    effect: git.inspect-repository
  implement:
    action_id: task.implementation.complete
    handler: evidence.record
    target: {node: done, status: DONE}
    payload: {summary: string}
  done: {terminal: true}
"""

OPENSPEC_FLOW = """\
schema: dev-flow-workflow/v1
id: openspec-lite
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
    target: {node: done, status: DONE}
    payload: {change_id: string}
    driver: {tool: openspec}
  done: {terminal: true}
"""

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


class CustomWorkflowTests(V5TestCase):
    def write_flow(self, text: str, name: str = "flow.yaml") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_custom_workflow_runs_end_to_end(self) -> None:
        flow_path = self.write_flow(MINIMAL_FLOW)
        state = self.controller.start(
            requirement="custom flow",
            workflow=str(flow_path),
            repository=str(self.repository),
        )
        self.assertEqual(state.workflow_id, str(flow_path))
        self.controller.apply(state.task_id, "task.preflight", {})
        result = self.controller.apply(
            state.task_id, "task.implementation.complete", {"summary": "done"}
        )
        self.assertEqual(result["receipt"]["status"], "DONE")
        self.assertTrue(result["projection"]["done"])

    def test_editing_workflow_after_start_fails(self) -> None:
        flow_path = self.write_flow(MINIMAL_FLOW)
        task_id = self.start_task(str(flow_path))
        flow_path.write_text(MINIMAL_FLOW.replace("Three-node", "Changed"), encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            self.controller.next(task_id)
        self.assertEqual(context.exception.code, "WORKFLOW_IDENTITY_MISMATCH")

    def test_driver_is_opaque_passthrough(self) -> None:
        flow_path = self.write_flow(OPENSPEC_FLOW, "openspec.yaml")
        state = self.controller.start(
            requirement="spec-first flow",
            workflow=str(flow_path),
            repository=str(self.repository),
        )
        self.controller.apply(state.task_id, "task.preflight", {})
        projection = self.controller.next(state.task_id)
        self.assertEqual(projection["action"]["action_id"], "record.spec")
        self.assertEqual(projection["action"]["driver"], {"tool": "openspec"})
        result = self.controller.apply(
            state.task_id, "record.spec", {"change_id": "changes/abc-1"}
        )
        self.assertEqual(result["receipt"]["status"], "DONE")

    def test_json_workflow_documents_are_supported(self) -> None:
        flow_path = self.root / "flow.json"
        flow_path.write_text(json.dumps({
            "schema": "dev-flow-workflow/v1",
            "id": "json-flow",
            "version": 5,
            "entry": "preflight",
            "nodes": {
                "preflight": {
                    "action_id": "task.preflight",
                    "handler": "preflight",
                    "target": {"node": "implement", "status": "IMPLEMENTING"},
                    "effect": "git.inspect-repository",
                },
                "implement": {
                    "action_id": "task.implementation.complete",
                    "handler": "evidence.record",
                    "target": {"node": "done", "status": "DONE"},
                },
                "done": {"terminal": True},
            },
        }), encoding="utf-8")
        task_id = self.start_task(str(flow_path))
        result = self.controller.apply(task_id, "task.preflight", {})
        self.assertEqual(result["receipt"]["status"], "IMPLEMENTING")

    def test_relative_custom_path_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="relative",
                workflow="relative/flow.yaml",
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_terminal_node_not_status_controls_activity(self) -> None:
        flow_path = self.write_flow(CUSTOM_STATUS_FLOW, "custom-status.yaml")
        task_id = self.start_task(str(flow_path))
        self.controller.apply(task_id, "task.preflight", {})
        state = self.controller.show(task_id)
        self.assertEqual(state.status, "DONE")
        self.assertEqual(
            [item.task_id for item in self.controller.tasks_for_path(str(self.repository))],
            [task_id],
        )
        result = self.controller.apply(
            task_id,
            "task.implementation.complete",
            {"summary": "complete"},
        )
        self.assertEqual(result["projection"]["status"], "COMPLETE")
        self.assertTrue(result["projection"]["done"])
        self.assertEqual(
            self.controller.tasks_for_path(str(self.repository)),
            (),
        )

    def test_object_payload_persists_and_replays_after_restart(self) -> None:
        flow_path = self.write_flow(OBJECT_PAYLOAD_FLOW, "object-payload.yaml")
        task_id = self.start_task(str(flow_path))
        self.controller.apply(task_id, "task.preflight", {})
        payload = {
            "metadata": {
                "source": "custom-workflow",
                "flags": {"verified": True},
                "items": [1, "two"],
            }
        }

        result = self.controller.apply(task_id, "task.record", payload)

        self.assertEqual(result["receipt"]["status"], "DONE")
        restarted = type(self.controller)(self.data_dir)
        persisted = restarted.show(task_id)
        self.assertEqual(persisted.as_dict()["evidence"][-1]["payload"], payload)
        self.assertTrue(restarted.next(task_id)["done"])

    def test_object_payload_rejects_non_mapping_without_advancing(self) -> None:
        flow_path = self.write_flow(OBJECT_PAYLOAD_FLOW, "object-invalid.yaml")
        task_id = self.start_task(str(flow_path))
        self.controller.apply(task_id, "task.preflight", {})
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(task_id, "task.record", {"metadata": []})

        self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
        after = self.controller.show(task_id)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.current_node, before.current_node)
        self.assertEqual(after.evidence, before.evidence)

    def test_missing_workflow_file_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="missing",
                workflow=str(self.root / "nope.yaml"),
                repository=str(self.repository),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def start_task(self, workflow: str) -> str:
        state = self.controller.start(
            requirement="custom",
            workflow=workflow,
            repository=str(self.repository),
        )
        return state.task_id


if __name__ == "__main__":
    unittest.main()
