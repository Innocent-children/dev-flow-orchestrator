"""Focused pure validation tests for workflow-v1 adaptation and workflow-v2."""

from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    WORKFLOW_IDS,
    WORKFLOW_V1_ADAPTER_IDENTITY,
    WORKFLOW_V2_ADAPTER_IDENTITY,
)
from dev_flow_orchestrator.workflow import (
    SCHEMA_V1,
    SCHEMA_V2,
    validate_definition_document,
    workflow_identity,
)
from dev_flow_orchestrator.workflows import load_definition


def v1_document() -> dict:
    return {
        "schema": SCHEMA_V1,
        "id": "custom-linear",
        "version": 5,
        "entry": "preflight",
        "nodes": {
            "preflight": {
                "action_id": "task.preflight",
                "handler": "preflight",
                "target": {"node": "work", "status": "WORKING"},
                "effect": "git.inspect-repository",
            },
            "work": {
                "action_id": "work.record",
                "handler": "evidence.record",
                "target": {"node": "verify", "status": "VERIFYING"},
                "payload": {"summary": "string", "details": "object"},
                "driver": {
                    "tool": "project-specific-tool",
                    "nested": {"mode": "opaque"},
                },
            },
            "verify": {
                "action_id": "test.record",
                "handler": "test.record",
                "target": {"node": "done", "status": "COMPLETE"},
                "payload": {"passed": "boolean", "command": "string"},
            },
            "done": {"terminal": True},
        },
    }


def v2_document() -> dict:
    return {
        "schema": SCHEMA_V2,
        "id": "bounded-delivery",
        "version": 6,
        "entry": "preflight",
        "revision_target": "implement",
        "nodes": {
            "preflight": {
                "action_id": "task.preflight",
                "handler": "preflight",
                "target": {"node": "implement", "status": "IMPLEMENTING"},
                "effect": "git.inspect-repository",
                "artifact": {
                    "type": "repository-baseline",
                    "workspace": "produces-source",
                    "inputs": [],
                },
            },
            "implement": {
                "action_id": "implementation.record",
                "handler": "artifact.record",
                "target": {"node": "verify", "status": "VERIFYING"},
                "payload": {"summary": "string"},
                "artifact": {
                    "type": "implementation",
                    "workspace": "produces-source",
                    "inputs": [
                        {
                            "type": "repository-baseline",
                            "edge": "source-predecessor",
                        }
                    ],
                },
            },
            "verify": {
                "action_id": "verification.record",
                "handler": "verification.record",
                "target": {"node": "finalize_success", "status": "FINALIZING"},
                "payload": {
                    "passed": "boolean",
                    "command": "string",
                    "coverage": "object",
                },
                "artifact": {
                    "type": "verification-result",
                    "workspace": "verifies-source",
                    "inputs": [
                        {"type": "implementation", "edge": "governing"}
                    ],
                },
                "rework": {
                    "failure": {"node": "repair", "status": "IMPLEMENTING"},
                    "max_attempts": 2,
                    "exhausted": {
                        "node": "finalize_incomplete",
                        "status": "FINALIZING",
                    },
                },
            },
            "repair": {
                "action_id": "repair.record",
                "handler": "artifact.record",
                "target": {"node": "verify", "status": "VERIFYING"},
                "payload": {"summary": "string"},
                "artifact": {
                    "type": "implementation",
                    "workspace": "produces-source",
                    "inputs": [
                        {
                            "type": "implementation",
                            "edge": "source-predecessor",
                        },
                        {"type": "verification-result", "edge": "causal"},
                    ],
                },
            },
            "finalize_success": {
                "action_id": "delivery.finalize.success",
                "handler": "delivery.finalize",
                "target": {"node": "done", "status": "DONE"},
                "payload": {"summary": "string"},
                "artifact": {
                    "type": "delivery-dossier",
                    "workspace": "verifies-source",
                    "inputs": [
                        {"type": "verification-result", "edge": "governing"}
                    ],
                },
                "finalize": "success",
            },
            "finalize_incomplete": {
                "action_id": "delivery.finalize.incomplete",
                "handler": "delivery.finalize",
                "target": {"node": "incomplete", "status": "INCOMPLETE"},
                "payload": {"summary": "string"},
                "artifact": {
                    "type": "delivery-dossier",
                    "workspace": "verifies-source",
                    "inputs": [
                        {"type": "verification-result", "edge": "governing"}
                    ],
                },
                "finalize": "incomplete",
            },
            "done": {"terminal": True},
            "incomplete": {"terminal": True},
            "cancelled": {"terminal": True},
        },
        "cancel": {
            "action_id": "task.cancel",
            "handler": "artifact.record",
            "target": {"node": "cancelled", "status": "CANCELLED"},
            "payload": {"reason": "string"},
        },
    }


def assert_invalid(
    testcase: unittest.TestCase, document: object, message_part: str
) -> None:
    with testcase.assertRaises(DevFlowError) as context:
        validate_definition_document(
            document, workflow_id="/tmp/custom-workflow.yaml", source="test"
        )
    testcase.assertEqual(context.exception.code, "WORKFLOW_INVALID")
    testcase.assertIn(message_part, context.exception.message)


class WorkflowV1AdapterTests(unittest.TestCase):
    def test_version_five_document_is_adapted_without_rewriting_original(self) -> None:
        document = v1_document()
        definition = validate_definition_document(
            document,
            workflow_id="/tmp/custom-workflow.yaml",
            source="test",
        )

        self.assertEqual(definition.schema, SCHEMA_V1)
        self.assertEqual(definition.version, 5)
        self.assertEqual(
            definition.adapter_identity, WORKFLOW_V1_ADAPTER_IDENTITY
        )
        self.assertEqual(definition.revision_target, "preflight")
        self.assertEqual(dict(definition.document), document)
        self.assertEqual(
            definition.nodes["work"].driver["nested"]["mode"], "opaque"
        )
        self.assertEqual(
            definition.nodes["work"].allowed_state_writes[-1], "/records"
        )
        self.assertIsNone(definition.nodes["work"].artifact)

    def test_selected_identity_binds_selector_schema_document_and_adapter(self) -> None:
        document = v1_document()
        first = workflow_identity("/tmp/a.yaml", document)
        second = workflow_identity("/tmp/b.yaml", document)
        changed = deepcopy(document)
        changed["nodes"]["work"]["description"] = "changed"

        self.assertNotEqual(first, second)
        self.assertNotEqual(first, workflow_identity("/tmp/a.yaml", changed))
        self.assertNotEqual(
            first,
            workflow_identity(
                "/tmp/a.yaml", document, "dev-flow-workflow-v1-adapter/test"
            ),
        )

    def test_v1_stays_version_five(self) -> None:
        document = v1_document()
        document["version"] = 6
        assert_invalid(self, document, "workflow-v1 compatibility")


class WorkflowV2ContractTests(unittest.TestCase):
    def test_typed_artifacts_and_finite_failure_cycle_load(self) -> None:
        definition = validate_definition_document(
            v2_document(),
            workflow_id="bounded-delivery",
            source="test",
        )

        self.assertEqual(definition.schema, SCHEMA_V2)
        self.assertEqual(definition.version, 6)
        self.assertEqual(
            definition.adapter_identity, WORKFLOW_V2_ADAPTER_IDENTITY
        )
        self.assertEqual(definition.revision_target, "implement")
        self.assertEqual(
            definition.nodes["implement"].artifact.inputs[0].edge_kind,
            "source-predecessor",
        )
        self.assertEqual(definition.nodes["verify"].rework.max_attempts, 2)
        self.assertEqual(definition.nodes["verify"].rework.failure_node, "repair")
        self.assertEqual(
            definition.nodes["verify"].rework.exhausted_node,
            "finalize_incomplete",
        )
        self.assertEqual(definition.terminals, definition.terminal_nodes)
        self.assertIs(definition.cancel, definition.cancel_contract)

    def test_source_producer_requires_exactly_one_predecessor(self) -> None:
        document = v2_document()
        document["nodes"]["implement"]["artifact"]["inputs"] = []
        assert_invalid(self, document, "exactly one source-predecessor")

        document = v2_document()
        document["nodes"]["implement"]["artifact"]["inputs"].append(
            {"type": "older-baseline", "edge": "source-predecessor"}
        )
        assert_invalid(self, document, "exactly one source-predecessor")

    def test_preflight_and_revision_source_establish_source_without_predecessor(self) -> None:
        document = v2_document()
        definition = validate_definition_document(
            document, workflow_id="bounded-delivery", source="test"
        )
        self.assertEqual(
            definition.nodes["preflight"].artifact.artifact_type,
            "repository-baseline",
        )

        document["nodes"]["implement"]["artifact"] = {
            "type": "revision-source",
            "workspace": "produces-source",
            "inputs": [],
        }
        definition = validate_definition_document(
            document, workflow_id="bounded-delivery", source="test"
        )
        self.assertEqual(
            definition.nodes["implement"].artifact.artifact_type,
            "revision-source",
        )

    def test_revision_target_must_be_reachable_and_nonterminal(self) -> None:
        document = v2_document()
        document["revision_target"] = "done"
        assert_invalid(self, document, "reachable nonterminal")

        document = v2_document()
        document["revision_target"] = "missing"
        assert_invalid(self, document, "reachable nonterminal")

    def test_rework_is_assurance_only_and_budget_is_positive(self) -> None:
        document = v2_document()
        document["nodes"]["implement"]["rework"] = deepcopy(
            document["nodes"]["verify"]["rework"]
        )
        assert_invalid(self, document, "supported only")

        document = v2_document()
        document["nodes"]["verify"]["rework"]["max_attempts"] = 0
        assert_invalid(self, document, "positive integer")

    def test_exhaustion_must_enter_incomplete_finalization(self) -> None:
        document = v2_document()
        document["nodes"]["verify"]["rework"]["exhausted"] = {
            "node": "finalize_success",
            "status": "FINALIZING",
        }
        assert_invalid(self, document, "incomplete delivery.finalize")

    def test_cycle_without_a_finite_failure_edge_is_rejected(self) -> None:
        document = v2_document()
        document["nodes"]["verify"]["target"] = {
            "node": "repair",
            "status": "IMPLEMENTING",
        }
        assert_invalid(self, document, "finite failure edges are removed")

    def test_failure_only_node_is_reachable_but_unrelated_node_is_not(self) -> None:
        definition = validate_definition_document(
            v2_document(), workflow_id="bounded-delivery", source="test"
        )
        self.assertIn("repair", definition.nodes)

        document = v2_document()
        document["nodes"]["orphan"] = {
            "action_id": "orphan.record",
            "handler": "artifact.record",
            "target": {"node": "finalize_success", "status": "FINALIZING"},
            "artifact": {
                "type": "orphan-report",
                "workspace": "context",
                "inputs": [],
            },
        }
        assert_invalid(self, document, "not reachable")

    def test_verification_review_and_finalize_must_verify_source(self) -> None:
        document = v2_document()
        document["nodes"]["verify"]["artifact"]["workspace"] = "context"
        assert_invalid(self, document, "must use workspace: verifies-source")

        document = v2_document()
        document["nodes"]["finalize_success"]["artifact"]["workspace"] = (
            "context"
        )
        assert_invalid(self, document, "must use workspace: verifies-source")

    def test_non_cancelled_terminal_requires_delivery_finalizer(self) -> None:
        document = v2_document()
        document["nodes"]["verify"]["target"] = {
            "node": "done",
            "status": "DONE",
        }
        assert_invalid(self, document, "must enter a terminal through")


class OfficialWorkflowPortfolioTests(unittest.TestCase):
    def test_all_official_workflows_are_v2_and_finalize_both_outcomes(self) -> None:
        self.assertEqual(
            set(WORKFLOW_IDS),
            {"lite", "feature", "bugfix", "investigation", "refactor", "full"},
        )
        for workflow_id in WORKFLOW_IDS:
            with self.subTest(workflow=workflow_id):
                definition = load_definition(workflow_id)
                self.assertEqual(definition.schema, SCHEMA_V2)
                self.assertEqual(definition.version, 6)
                outcomes = {
                    node.finalize_outcome
                    for node in definition.nodes.values()
                    if node.finalize_outcome is not None
                }
                self.assertEqual(outcomes, {"success", "incomplete"})
                self.assertEqual(
                    definition.nodes["preflight"].artifact.artifact_type,
                    "repository-baseline",
                )
                self.assertIsNotNone(definition.cancel_contract)

    def test_official_revision_targets_match_product_reentry(self) -> None:
        self.assertEqual(load_definition("lite").revision_target, "implement")
        for workflow_id in ("feature", "bugfix", "refactor", "full", "investigation"):
            with self.subTest(workflow=workflow_id):
                self.assertEqual(load_definition(workflow_id).revision_target, "impact")

    def test_optional_drivers_declare_fallback_and_produced_type(self) -> None:
        for workflow_id in WORKFLOW_IDS:
            definition = load_definition(workflow_id)
            for node in definition.nodes.values():
                if node.driver is None:
                    continue
                with self.subTest(workflow=workflow_id, node=node.node_id):
                    self.assertIs(node.driver["optional"], True)
                    self.assertTrue(node.driver["fallback"])
                    self.assertEqual(
                        node.driver["produces"], node.artifact.artifact_type
                    )

    def test_openspec_plans_are_repository_backed_source_producers(self) -> None:
        for workflow_id in ("feature", "bugfix", "refactor", "full"):
            definition = load_definition(workflow_id)
            planning = definition.nodes["planning"]
            with self.subTest(workflow=workflow_id):
                self.assertEqual(planning.driver["tool"], "openspec")
                self.assertEqual(planning.payload_types["resources"], "object")
                self.assertEqual(planning.artifact.workspace_role, "produces-source")
                predecessors = [
                    item
                    for item in planning.artifact.inputs
                    if item.edge_kind == "source-predecessor"
                ]
                self.assertEqual(len(predecessors), 1)
                self.assertEqual(
                    predecessors[0].artifact_type, "repository-baseline"
                )

    def test_review_rework_returns_through_docs_verification_and_review(self) -> None:
        for workflow_id in ("feature", "bugfix", "refactor", "full"):
            definition = load_definition(workflow_id)
            with self.subTest(workflow=workflow_id):
                review = definition.nodes["review"]
                review_rework = definition.nodes[review.rework.failure_node]
                documentation = definition.nodes[review_rework.target_node]
                verification = definition.nodes[documentation.target_node]
                self.assertEqual(review_rework.artifact.workspace_role, "produces-source")
                self.assertIn(
                    "causal", {item.edge_kind for item in review_rework.artifact.inputs}
                )
                self.assertEqual(documentation.node_id, "documentation")
                self.assertEqual(verification.node_id, "verify")
                self.assertEqual(verification.target_node, "review")

    def test_investigation_does_not_declare_implementation(self) -> None:
        definition = load_definition("investigation")
        artifact_types = {
            node.artifact.artifact_type
            for node in definition.nodes.values()
            if node.artifact is not None
        }
        self.assertNotIn("implementation", artifact_types)
        self.assertIn("investigation-report", artifact_types)


if __name__ == "__main__":
    unittest.main()
