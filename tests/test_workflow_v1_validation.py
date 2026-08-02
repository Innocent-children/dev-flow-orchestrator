"""One rejection case per workflow validation rule."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.workflow import validate_definition_document


def base_document() -> dict:
    return {
        "schema": "dev-flow-workflow/v1",
        "id": "test-flow",
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
                "payload": {"summary": "string"},
            },
            "done": {"terminal": True},
        },
    }


def assert_invalid(testcase: unittest.TestCase, document: object,
                   message_part: str) -> None:
    with testcase.assertRaises(DevFlowError) as context:
        validate_definition_document(
            document, workflow_id="test-flow", source="test"
        )
    testcase.assertEqual(context.exception.code, "WORKFLOW_INVALID")
    testcase.assertIn(message_part, context.exception.message)


class WorkflowValidationTests(unittest.TestCase):
    def test_valid_document_loads(self) -> None:
        definition = validate_definition_document(
            base_document(), workflow_id="test-flow", source="test"
        )
        self.assertEqual(definition.workflow_id, "test-flow")
        self.assertEqual(definition.entry_node, "preflight")
        self.assertEqual(definition.terminal_nodes, ("done",))
        self.assertEqual(definition.cancel_contract, None)

    def test_unknown_top_level_key(self) -> None:
        document = base_document()
        document["extra"] = 1
        assert_invalid(self, document, "unknown workflow field")

    def test_unknown_node_field(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["mystery"] = 1
        assert_invalid(self, document, "unknown node field")

    def test_dangling_target(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["target"] = {"node": "ghost", "status": "X"}
        assert_invalid(self, document, "target.node must be a declared node")

    def test_unreachable_node(self) -> None:
        document = base_document()
        document["nodes"]["extra"] = {
            "action_id": "x.extra",
            "handler": "evidence.record",
            "target": {"node": "done", "status": "DONE"},
        }
        assert_invalid(self, document, "not reachable")

    def test_duplicate_action_id(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["action_id"] = "task.preflight"
        assert_invalid(self, document, "action_id values must be unique")

    def test_self_loop(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["target"] = {
            "node": "implement", "status": "IMPLEMENTING"
        }
        assert_invalid(self, document, "must not target itself")

    def test_bad_payload_type(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["payload"] = {"summary": "wat"}
        assert_invalid(self, document, "unknown type")

    def test_authority_not_supported(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["authority"] = "task-revision+human-approval"
        assert_invalid(self, document, "not supported by this runtime yet")

    def test_unsupported_effect(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["effect"] = "git.prepare-workspace"
        assert_invalid(self, document, "supports only effect")

    def test_unknown_handler(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["handler"] = "review.record"
        assert_invalid(self, document, "handler must be one of")

    def test_entry_not_preflight(self) -> None:
        document = base_document()
        document["entry"] = "implement"
        assert_invalid(self, document, "entry node must use the preflight handler")

    def test_preflight_not_entry(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["handler"] = "preflight"
        document["nodes"]["implement"]["effect"] = "git.inspect-repository"
        del document["nodes"]["implement"]["payload"]
        assert_invalid(self, document, "exactly one preflight node")

    def test_payload_on_preflight(self) -> None:
        document = base_document()
        document["nodes"]["preflight"]["payload"] = {"summary": "string"}
        assert_invalid(self, document, "takes no payload")

    def test_writes_outside_vocabulary(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["writes"] = ["/approvals"]
        assert_invalid(self, document, "declared writes must be exactly")

    def test_no_terminal_node(self) -> None:
        document = base_document()
        del document["nodes"]["done"]
        document["nodes"]["implement"]["target"] = {"node": "verify", "status": "V"}
        document["nodes"]["verify"] = {
            "action_id": "x.verify",
            "handler": "evidence.record",
            "target": {"node": "implement", "status": "I"},
        }
        assert_invalid(self, document, "at least one terminal node")

    def test_cancel_without_target(self) -> None:
        document = base_document()
        document["cancel"] = {
            "action_id": "task.cancel",
            "handler": "evidence.record",
        }
        assert_invalid(self, document, "target is required")

    def test_cancel_duplicate_action_id(self) -> None:
        document = base_document()
        document["cancel"] = {
            "action_id": "task.preflight",
            "handler": "evidence.record",
            "target": {"node": "done", "status": "CANCELLED"},
        }
        assert_invalid(self, document, "cancel action_id must differ")

    def test_two_node_cycle_is_rejected_even_with_cancel_terminal(self) -> None:
        document = base_document()
        document["nodes"]["implement"]["target"] = {
            "node": "verify", "status": "VERIFYING"
        }
        document["nodes"]["verify"] = {
            "action_id": "evidence.verify",
            "handler": "evidence.record",
            "target": {"node": "implement", "status": "IMPLEMENTING"},
        }
        document["cancel"] = {
            "action_id": "task.cancel",
            "handler": "evidence.record",
            "target": {"node": "done", "status": "CANCELLED"},
            "payload": {"reason": "string"},
        }
        assert_invalid(self, document, "must not contain a cycle")

    def test_cancel_target_must_be_terminal(self) -> None:
        document = base_document()
        document["cancel"] = {
            "action_id": "task.cancel",
            "handler": "evidence.record",
            "target": {"node": "implement", "status": "CANCELLED"},
            "payload": {"reason": "string"},
        }
        assert_invalid(self, document, "must be a terminal node")

    def test_cancel_status_must_be_cancelled(self) -> None:
        document = base_document()
        document["cancel"] = {
            "action_id": "task.cancel",
            "handler": "evidence.record",
            "target": {"node": "done", "status": "DONE"},
            "payload": {"reason": "string"},
        }
        assert_invalid(self, document, "must be exactly 'CANCELLED'")

    def test_cancel_payload_must_be_exact(self) -> None:
        document = base_document()
        document["cancel"] = {
            "action_id": "task.cancel",
            "handler": "evidence.record",
            "target": {"node": "done", "status": "CANCELLED"},
            "payload": {"reason": "string", "extra": "string"},
        }
        assert_invalid(self, document, "must be exactly reason: string")

    def test_wrong_version(self) -> None:
        document = base_document()
        document["version"] = 4
        assert_invalid(self, document, "version must be current schema")

    def test_terminal_node_with_action(self) -> None:
        document = base_document()
        document["nodes"]["done"] = {
            "terminal": True,
            "action_id": "x.done",
        }
        assert_invalid(self, document, "terminal node must not declare")


if __name__ == "__main__":
    unittest.main()
