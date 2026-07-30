from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "protocol_sizes" / "current.json"


def _load_module(name: str, relative_path: str) -> object:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


protocol = _load_module(
    "dev_flow_agent_protocol_size_measurement",
    "scripts/dev_flow_parts/agent_protocol.py",
)
orchestration = _load_module(
    "dev_flow_orchestration_result_size_measurement",
    "scripts/dev_flow_parts/orchestration_results.py",
)
projection = _load_module(
    "dev_flow_workflow_projection_size_measurement",
    "scripts/dev_flow_parts/workflow_projection.py",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_id(kind: str, value: str) -> str:
    return f"{kind}:{_digest(value)}"


def _authoritative_node_result() -> object:
    return orchestration.bind_node_result_identity(
        {
            "schema": orchestration.ORCHESTRATION_NODE_RESULT_SCHEMA,
            "task_id": "task-1",
            "workflow_bundle_sha256": _digest("b"),
            "map_epoch": 3,
            "repository_id": "api",
            "node_instance_id": "node-api",
            "attempt": 1,
            "assignment_id": _content_id(
                "worker-assignment", "assignment-api"
            ),
            "lease_id": _content_id("worker-lease", "lease-api"),
            "lease_nonce": _digest("nonce-api"),
            "input_sha256": _digest("i"),
            "output_sha256": _digest("o"),
            "worktree_sha256": _digest("g"),
            "changed_paths_sha256": _digest("h"),
            "verification_sha256": _digest("v"),
            "outcome": "SUCCEEDED",
            "summary": "api result",
            "blockers": [],
            "plan_drift": {"detected": False, "reasons": []},
            "artifact_refs": [
                {
                    "id": "artifact-api",
                    "semantic_sha256": _digest("artifact-contract"),
                    "sha256": _digest("r"),
                    "size": 321,
                    "kind": "application/json",
                    "locator": "artifact-api",
                }
            ],
            "evidence_refs": [
                {
                    "id": "evidence-api",
                    "semantic_sha256": _digest("e"),
                    "sha256": _digest("r"),
                    "size": 321,
                    "kind": "test.report.v1",
                    "locator": "evidence-api",
                }
            ],
            "runtime_handle": "runtime-api",
        }
    )


def _measured_payloads() -> dict[str, bytes]:
    workflow_ref = {
        "id": "full",
        "version": 4,
        "schema": "dev-flow-workflow/v1",
        "graph_sha256": (
            "8aa863efb740dc979c862919012c1073de"
            "3a00ab130d8ce62d851e80bc422078"
        ),
        "bundle_sha256": (
            "bc5082c941a839490506c8f403038dbe"
            "e93c49d07ab6e6529557bc41e707760d"
        ),
    }
    task_next = protocol.build_task_next(
        {"task_id": "task-1", "revision": 7},
        workflow_ref=workflow_ref,
        frontier=[
            {
                "node_instance_id": "node-1",
                "repository_id": "repo-a",
                "node_id": "IMPLEMENTING",
                "label": "实现中",
            }
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
    checkpoint = protocol.build_hook_checkpoint(
        task_next,
        controller_locator="scripts/dev_flow.py show --next task-1",
    )
    receipt = protocol.build_mutation_receipt(
        task_id="task-1",
        revision=8,
        node_id="VERIFYING",
        changed_sections=["tests", "status", "tests"],
        action_id="record-test",
        summary={"passed": True, "test_id": "test-1"},
        next_locator={"action_id": "review-snapshot"},
    )
    playbook_source = (
        ROOT
        / "workflows"
        / "bundles"
        / "full-v4"
        / "playbooks"
        / "workflow.md"
    ).read_text(encoding="utf-8")
    playbook_section = projection._workflow_projection_playbook_section(
        playbook_source, "implementing"
    ).encode("utf-8")
    node_result = _authoritative_node_result()
    operator_intervention = {
        "schema": "dev-flow-v4-operator-intervention/v1",
        "required": True,
        "reason": "TRUSTED_HOST_AUTHORITY_UNAVAILABLE",
        "target_execution_id": "target-v4",
        "effect_ids": ["effect-a", "effect-b"],
        "affected_scopes": {
            "external_resources": [],
            "lease_ids": ["lease-a"],
            "node_ids": ["node-a"],
            "paths": ["/work/repo-a"],
            "repository_ids": ["repo-a"],
            "worktree_ids": ["worktree-a"],
        },
        "allowed_resume_conditions": [
            "authenticated_original_runtime",
            "verifiable_stored_receipt",
            "trusted_host_recovery_authority",
        ],
        "automatic_redispatch": False,
        "automatic_compensation": False,
        "automatic_unblock": False,
        "caller_assertion_can_unblock": False,
    }
    return {
        "authoritative_node_result": (
            orchestration.canonical_node_result_bytes(
                node_result
            )
        ),
        "hook_checkpoint": protocol.canonical_protocol_bytes(checkpoint),
        "implementing_playbook_section": playbook_section,
        "inline_node_result_summary": str(
            node_result["summary"]
        ).encode("utf-8"),
        "mutation_receipt": protocol.canonical_protocol_bytes(receipt),
        "operator_intervention": protocol.canonical_protocol_bytes(
            operator_intervention
        ),
        "task_next": protocol.canonical_protocol_bytes(task_next),
    }


class CurrentProtocolSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_current_measurements_are_reproducible_and_within_budget(
        self,
    ) -> None:
        payloads = _measured_payloads()
        self.assertEqual(
            set(payloads),
            set(self.report["payloads"]),
        )
        for name, payload in payloads.items():
            with self.subTest(payload=name):
                expected = self.report["payloads"][name]
                self.assertEqual(len(payload), expected["bytes"])
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(),
                    expected["sha256"],
                )
                self.assertEqual(
                    (len(payload) + 3) // 4,
                    expected["observational_token_estimate"],
                )
                self.assertLessEqual(
                    len(payload), expected["budget_bytes"]
                )

    def test_baseline_comparisons_are_integer_and_reproducible(self) -> None:
        current = self.report["payloads"]
        baseline = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "protocol_sizes"
                / "baseline.json"
            ).read_text(encoding="utf-8")
        )["payloads"]
        comparisons = {
            "legacy_hook_compact_to_hook_checkpoint": (
                baseline["hook_compact"]["bytes"],
                current["hook_checkpoint"]["bytes"],
            ),
            "legacy_compact_task_read_to_task_next": (
                baseline["compact_task_read"]["bytes"],
                current["task_next"]["bytes"],
            ),
            "legacy_common_mutation_receipt_to_v4_receipt": (
                baseline["common_mutation_receipt"]["bytes"],
                current["mutation_receipt"]["bytes"],
            ),
            "full_playbook_to_selected_section": (
                (
                    ROOT
                    / "workflows"
                    / "bundles"
                    / "full-v4"
                    / "playbooks"
                    / "workflow.md"
                ).stat().st_size,
                current["implementing_playbook_section"]["bytes"],
            ),
        }
        self.assertEqual(
            set(comparisons),
            set(self.report["comparisons"]),
        )
        for name, (before, after) in comparisons.items():
            with self.subTest(comparison=name):
                expected = self.report["comparisons"][name]
                self.assertEqual(before, expected["baseline_bytes"])
                self.assertEqual(after, expected["current_bytes"])
                self.assertEqual(
                    round((before - after) * 1000 / before),
                    expected["reduction_millis"],
                )


if __name__ == "__main__":
    unittest.main()
