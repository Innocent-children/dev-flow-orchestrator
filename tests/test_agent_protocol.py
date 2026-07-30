from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "agent_protocol.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_agent_protocol", PROTOCOL_PATH
)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = protocol
SPEC.loader.exec_module(protocol)


def workflow_ref() -> dict:
    return {
        "id": "full",
        "version": 3,
        "schema": "dev-flow-workflow/v1",
        "graph_sha256": "a" * 64,
        "bundle_sha256": "b" * 64,
    }


def artifact_reference(
    task_id: str, payload: bytes, *, artifact_id: str = "artifact-1"
) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema": "dev-flow-artifact-reference/v1",
        "artifact_id": artifact_id,
        "task_id": task_id,
        "semantic_sha256": digest,
        "sha256": digest,
        "size": len(payload),
        "media_type": "application/json",
        "kind": "protocol-overflow",
        "locator": f"artifacts/{artifact_id}",
    }


class AgentProtocolTests(unittest.TestCase):
    def test_agent_projection_does_not_claim_authoritative_v1(self) -> None:
        self.assertEqual(
            protocol.AGENT_NODE_RESULT_CANDIDATE_SCHEMA,
            "dev-flow-agent-node-result-candidate/v1",
        )
        self.assertFalse(hasattr(protocol, "NODE_RESULT_SCHEMA"))
        self.assertFalse(hasattr(protocol, "validate_node_result"))

    def test_common_task_next_is_deterministic_and_under_budget(self) -> None:
        first = protocol.build_task_next(
            {"task_id": "task-1", "revision": 7},
            workflow_ref=workflow_ref(),
            frontier=[
                {
                    "node_instance_id": "node-2",
                    "repository_id": "repo-b",
                    "node_id": "IMPLEMENTING",
                    "label": "实现中",
                },
                {
                    "node_instance_id": "node-1",
                    "repository_id": "repo-a",
                    "node_id": "IMPLEMENTING",
                    "label": "实现中",
                },
            ],
            actions=[
                {
                    "action_id": "implementation.execute",
                    "edge_id": "full.implement.verify/v1",
                    "confirmation": "automatic",
                    "required_sections": ["repositories", "workspace"],
                    "playbook": "playbooks/implement.md",
                }
            ],
        )
        second = protocol.build_task_next(
            {"revision": 7, "task_id": "task-1"},
            workflow_ref=workflow_ref(),
            frontier=list(reversed(first["frontier"])),
            actions=first["actions"],
        )

        self.assertEqual(
            first["frontier"][0]["node_instance_id"], "node-1"
        )
        self.assertEqual(
            first["frontier_sha256"], second["frontier_sha256"]
        )
        self.assertLessEqual(
            protocol.protocol_size(first), protocol.TASK_NEXT_BUDGET
        )
        serialized = protocol.canonical_protocol_bytes(first)
        self.assertNotIn(b"index", serialized)
        self.assertNotIn(b"history", serialized)

    def test_hook_checkpoint_is_revision_and_frontier_bound(self) -> None:
        task_next = protocol.build_task_next(
            {"task_id": "task-1", "revision": 7},
            workflow_ref=workflow_ref(),
            frontier=[{"node_id": "IMPLEMENTING"}],
            actions=[
                {
                    "action_id": "implementation.execute",
                    "edge_id": "full.implement.verify/v1",
                    "playbook": "playbooks/implement.md",
                }
            ],
        )

        checkpoint = protocol.build_hook_checkpoint(
            task_next,
            controller_locator="scripts/dev_flow.py show --next task-1",
        )

        self.assertEqual(checkpoint["revision"], 7)
        self.assertEqual(
            checkpoint["frontier_sha256"],
            task_next["frontier_sha256"],
        )
        self.assertLessEqual(
            protocol.protocol_size(checkpoint),
            protocol.HOOK_CHECKPOINT_BUDGET,
        )

    def test_task_next_overflow_is_stored_without_silent_truncation(
        self,
    ) -> None:
        stored: list[bytes] = []

        def writer(task_id: str, _kind: str, content: bytes) -> dict:
            stored.append(content)
            return artifact_reference(task_id, content)

        result = protocol.build_task_next(
            {"task_id": "task-1", "revision": 7},
            workflow_ref=workflow_ref(),
            frontier=[
                {
                    "node_instance_id": f"node-{index:03}",
                    "repository_id": f"repository-{index:03}",
                    "node_id": "IMPLEMENTING",
                }
                for index in range(80)
            ],
            actions=[
                {
                    "action_id": "implementation.execute",
                    "edge_id": "full.implement.verify/v1",
                    "playbook": "playbooks/implement.md",
                }
            ],
            artifact_writer=writer,
        )

        self.assertEqual(len(stored), 1)
        full = json.loads(stored[0].decode("utf-8"))
        self.assertEqual(len(full["frontier"]), 80)
        self.assertIn("artifact", result)
        self.assertLessEqual(
            protocol.protocol_size(result), protocol.TASK_NEXT_BUDGET
        )

    def test_revision_delta_participates_in_task_next_budget(
        self,
    ) -> None:
        stored: list[bytes] = []

        def writer(task_id: str, _kind: str, content: bytes) -> dict:
            stored.append(content)
            return artifact_reference(task_id, content)

        delta = {
            "contract": "dev-flow-task-next-delta/v1",
            "from_revision": 0,
            "to_revision": 2,
            "revision_count": 2,
            "delta_sha256": "d" * 64,
            "reset_required": False,
        }
        result = protocol.build_task_next(
            {"task_id": "task-1", "revision": 2},
            workflow_ref=workflow_ref(),
            frontier=[
                {
                    "node_instance_id": f"node-{index:03}",
                    "repository_id": f"repository-{index:03}",
                    "node_id": "IMPLEMENTING",
                }
                for index in range(20)
            ],
            actions=[
                {
                    "action_id": "implementation.execute",
                    "edge_id": "full.implement.verify/v1",
                }
            ],
            revision_delta=delta,
            artifact_writer=writer,
        )

        self.assertEqual(result["revision_delta"], delta)
        self.assertNotIn(
            "revision_delta",
            json.loads(stored[0].decode("utf-8")),
        )
        self.assertLessEqual(
            protocol.protocol_size(result), protocol.TASK_NEXT_BUDGET
        )

    def test_overflow_storage_failure_is_structured(self) -> None:
        with self.assertRaises(protocol.AgentProtocolError) as raised:
            protocol.build_task_next(
                {"task_id": "task-1", "revision": 7},
                workflow_ref=workflow_ref(),
                frontier=[
                    {
                        "node_instance_id": f"node-{index:03}",
                        "node_id": "IMPLEMENTING",
                    }
                    for index in range(80)
                ],
                actions=[],
            )
        self.assertEqual(
            raised.exception.code,
            "PROTOCOL_OVERFLOW_STORAGE_REQUIRED",
        )

    def test_common_mutation_receipt_is_action_scoped(self) -> None:
        receipt = protocol.build_mutation_receipt(
            task_id="task-1",
            revision=8,
            node_id="VERIFYING",
            changed_sections=["tests", "status", "tests"],
            action_id="record-test",
            summary={"passed": True, "test_id": "test-1"},
            next_locator={"action_id": "review-snapshot"},
            required_fields={"artifact_sha256": "c" * 64},
        )

        self.assertEqual(receipt["changed"], ["status", "tests"])
        self.assertIn("required", receipt)
        common = dict(receipt)
        common.pop("required")
        self.assertLessEqual(
            protocol.protocol_size(common),
            protocol.MUTATION_RECEIPT_BUDGET,
        )
        self.assertNotIn("workflow", receipt)
        self.assertNotIn("indexes", receipt)

    def test_artifact_reference_is_task_scoped_and_integrity_bound(
        self,
    ) -> None:
        value = artifact_reference("task-1", b"payload")
        self.assertEqual(
            protocol.validate_artifact_reference(
                value, expected_task_id="task-1"
            )["sha256"],
            hashlib.sha256(b"payload").hexdigest(),
        )
        with self.assertRaises(protocol.AgentProtocolError) as raised:
            protocol.validate_artifact_reference(
                value, expected_task_id="other"
            )
        self.assertEqual(
            raised.exception.code, "ARTIFACT_TASK_SCOPE_MISMATCH"
        )

    def test_node_result_is_schema_input_and_budget_bound(self) -> None:
        value = {
            "schema": "dev-flow-agent-node-result-candidate/v1",
            "result_id": "result-1",
            "task_id": "task-1",
            "bundle_sha256": "b" * 64,
            "node_instance_id": "node-1",
            "repository_id": "repo-a",
            "attempt": 1,
            "input_sha256": "c" * 64,
            "status": "succeeded",
            "summary": "Implemented and verified.",
            "artifacts": [],
            "evidence": [],
            "changed_files": ["src/example.py"],
            "blockers": [],
            "plan_drift": {"detected": False},
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "reasoning_output_tokens": 1,
            },
        }

        result = protocol.validate_agent_node_result_candidate(
            value,
            expected_task_id="task-1",
            expected_input_sha256="c" * 64,
        )

        self.assertLessEqual(
            protocol.protocol_size(result), protocol.NODE_RESULT_BUDGET
        )
        self.assertLessEqual(
            len(result["summary"].encode("utf-8")),
            protocol.NODE_RESULT_SUMMARY_BUDGET,
        )
        with self.assertRaises(protocol.AgentProtocolError) as raised:
            protocol.validate_agent_node_result_candidate(
                {**value, "input_sha256": "d" * 64},
                expected_input_sha256="c" * 64,
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_INPUT_MISMATCH"
        )

    def test_node_result_rejects_free_form_or_oversized_content(self) -> None:
        with self.assertRaises(protocol.AgentProtocolError) as raised:
            protocol.validate_agent_node_result_candidate({"text": "done"})
        self.assertEqual(raised.exception.code, "NODE_RESULT_UNKNOWN_FIELD")

        oversized = {
            "schema": "dev-flow-agent-node-result-candidate/v1",
            "result_id": "result-1",
            "task_id": "task-1",
            "bundle_sha256": "b" * 64,
            "node_instance_id": "node-1",
            "attempt": 1,
            "input_sha256": "c" * 64,
            "status": "succeeded",
            "summary": "x" * 513,
        }
        with self.assertRaises(protocol.AgentProtocolError) as raised:
            protocol.validate_agent_node_result_candidate(oversized)
        self.assertEqual(
            raised.exception.code, "PROTOCOL_FIELD_TOO_LARGE"
        )


if __name__ == "__main__":
    unittest.main()
