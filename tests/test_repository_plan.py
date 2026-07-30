from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "repository_plan.py"
)
FIXTURE_PATH = (
    Path(__file__).with_name("fixtures")
    / "repository_plan"
    / "valid_v1.json"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_repository_plan_tests", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
repository_plan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repository_plan
SPEC.loader.exec_module(repository_plan)


def load_plan() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def bind(plan: dict[str, object]) -> dict[str, object]:
    value = repository_plan.bind_repository_plan_semantic_input(plan)
    return json.loads(
        repository_plan.canonical_repository_plan_bytes(value)
    )


def approve(
    plan: dict[str, object],
    *,
    revision: int = 12,
) -> object:
    return repository_plan.create_repository_plan_approval(
        plan,
        approval_intent="approve-repository-map/v1",
        approval_commit_revision=revision,
    )


def workflow_bundle(
    *,
    bundle_sha256: str = "d" * 64,
) -> dict[str, object]:
    metadata = {
        "schema": "dev-flow-repository-orchestration/v1",
        "execution_profile": "multi-repository",
        "map": {
            "operation_id": "map.repositories/v1",
            "parent_node_id": "IMPLEMENTING",
            "child_template": {
                "template_id": "map.repositories/v1",
                "node_id": "IMPLEMENTING",
            },
        },
        "join": {
            "operation_id": "join.repositories/v1",
            "node_id": "VERIFYING",
            "barrier_policy": {
                "id": "barrier.all-current-succeeded/v1",
                "required_outcomes": ["SUCCEEDED"],
            },
        },
        "operation_ids": [],
    }
    nodes = {
        "IMPLEMENTING": {"id": "IMPLEMENTING"},
        "VERIFYING": {"id": "VERIFYING"},
    }
    return {
        "bundle_sha256": bundle_sha256,
        "execution_profiles": (
            "single-repository",
            "multi-repository",
        ),
        "repository_orchestration": metadata,
        "nodes": nodes,
        "graph": {
            "flow": "full",
            "execution_profiles": [
                "single-repository",
                "multi-repository",
            ],
            "repository_orchestration": metadata,
            "nodes": list(nodes.values()),
        },
    }


def current_fact(
    *,
    repository_id: str | None = None,
    result_id: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "accepted": True,
        "current": True,
    }
    if repository_id is not None:
        value["repository_id"] = repository_id
    if result_id is not None:
        value["result_id"] = result_id
    return value


class RepositoryPlanSchemaTests(unittest.TestCase):
    def test_fixture_has_normative_canonical_identity_vectors(self) -> None:
        plan = repository_plan.load_repository_plan(
            FIXTURE_PATH.read_bytes()
        )
        identity = repository_plan.repository_plan_identity(plan)

        self.assertEqual(
            identity.semantic_input_sha256,
            "e2d5f93fe37437fb36b88151eae7ae2ef1155e84fde3b680d3a2dbb0755685b8",
        )
        self.assertEqual(
            identity.artifact_sha256,
            "3b4dce32ac1da9340cf2c9e734cd88f69b36249cbac07d1bf6f5a981029afe12",
        )
        self.assertEqual(
            identity.dag_sha256,
            "2d5a19a176c950d2fe98b154ee4ae4d9f92e973493f179be753d5193660939ec",
        )
        expected_preimage = (
            b"dev-flow-repository-plan-v1\x00"
            + struct.pack(">Q", len(identity.canonical_bytes))
            + identity.canonical_bytes
        )
        self.assertEqual(
            repository_plan.repository_plan_preimage(plan),
            expected_preimage,
        )
        self.assertEqual(
            identity.dag_sha256,
            hashlib.sha256(expected_preimage).hexdigest(),
        )
        with self.assertRaises(TypeError):
            plan["map_epoch"] = 4
        with self.assertRaises(TypeError):
            plan["repositories"][0]["repository_id"] = "changed"

    def test_strict_json_rejects_duplicate_float_nonfinite_range_and_bom(
        self,
    ) -> None:
        cases = (
            (
                b'{"schema":"x","schema":"y"}',
                "REPOSITORY_PLAN_JSON_DUPLICATE_KEY",
            ),
            (
                b'{"value":1.5}',
                "REPOSITORY_PLAN_JSON_FLOAT_FORBIDDEN",
            ),
            (
                b'{"value":NaN}',
                "REPOSITORY_PLAN_JSON_NONFINITE_FORBIDDEN",
            ),
            (
                b'{"value":9223372036854775808}',
                "REPOSITORY_PLAN_JSON_INTEGER_OUT_OF_RANGE",
            ),
            (
                b"\xef\xbb\xbf{}",
                "REPOSITORY_PLAN_JSON_BOM_FORBIDDEN",
            ),
        )
        for source, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(
                    repository_plan.RepositoryPlanError
                ) as raised:
                    repository_plan.parse_repository_plan_json(source)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(
                    raised.exception.as_dict()["code"], code
                )

    def test_schema_is_closed_and_all_canonical_arrays_are_ordered(
        self,
    ) -> None:
        plan = load_plan()
        plan["surprise"] = True
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_UNKNOWN_FIELD"
        )

        plan = load_plan()
        plan["repository_set"] = ["web", "docs", "api"]
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_ORDER_INVALID"
        )

        plan = load_plan()
        plan["repository_set"] = ["api", "docs"]
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_REPOSITORY_SET_MISMATCH",
        )

    def test_portable_repository_and_path_collisions_are_rejected(
        self,
    ) -> None:
        plan = load_plan()
        plan["repositories"][1]["repository_id"] = "API"
        plan["repository_set"] = ["API", "api", "web"]
        plan["repositories"] = sorted(
            plan["repositories"],
            key=lambda item: item["repository_id"].encode("utf-8"),
        )
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_PORTABLE_COLLISION",
        )

        plan = load_plan()
        plan["repositories"][1]["repository_path"] = "Repositories/API"
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_PATH_COLLISION"
        )

        plan = load_plan()
        plan["repositories"][1]["identity_sha256"] = "1" * 64
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_DUPLICATE_IDENTITY",
        )

        plan = load_plan()
        plan["repositories"][0]["approved_paths"] = ["src", "src/api"]
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_PATH_COLLISION"
        )

    def test_graph_rejects_self_unknown_duplicate_identity_and_cycle(
        self,
    ) -> None:
        plan = load_plan()
        plan["dependencies"][0]["to_repository_id"] = "api"
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_DEPENDENCY_SELF"
        )

        plan = load_plan()
        plan["dependencies"][0]["to_repository_id"] = "ghost"
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_DEPENDENCY_UNKNOWN"
        )

        plan = load_plan()
        duplicate_id = copy.deepcopy(plan["dependencies"][0])
        duplicate_id["from_repository_id"] = "docs"
        plan["dependencies"].append(duplicate_id)
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_PORTABLE_COLLISION",
        )

        plan = load_plan()
        reverse = copy.deepcopy(plan["dependencies"][0])
        reverse.update(
            {
                "edge_id": "edge.web-api/v1",
                "from_repository_id": "web",
                "to_repository_id": "api",
            }
        )
        plan["dependencies"].append(reverse)
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_DEPENDENCY_CYCLE",
        )
        self.assertEqual(
            raised.exception.details["repository_ids"], ["api", "web"]
        )

    def test_unknown_contract_and_non_monotonic_map_epoch_are_rejected(
        self,
    ) -> None:
        plan = load_plan()
        plan["dependencies"][0]["output_contract_sha256"] = "f" * 64
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.bind_repository_plan_semantic_input(plan)
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_CONTRACT_UNKNOWN"
        )

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan(
                load_plan(), previous_map_epoch=3
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_MAP_EPOCH_NOT_MONOTONIC",
        )

    def test_semantic_input_binds_plan_inputs_but_not_approval_revision(
        self,
    ) -> None:
        plan = load_plan()
        approval_12 = approve(plan, revision=12)
        approval_50 = approve(plan, revision=50)

        self.assertEqual(
            approval_12["plan_input_revision"], 11
        )
        self.assertEqual(
            approval_12["approval_commit_revision"], 12
        )
        self.assertEqual(
            approval_50["semantic_input_sha256"],
            approval_12["semantic_input_sha256"],
        )
        repository_plan.validate_repository_plan_approval(
            plan, approval_50
        )

        drifted = copy.deepcopy(plan)
        drifted["repositories"][0]["approved_paths"] = [
            "src",
            "tests",
            "tools",
        ]
        drifted = bind(drifted)
        self.assertNotEqual(
            drifted["semantic_input_sha256"],
            plan["semantic_input_sha256"],
        )
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_approval(
                drifted, approval_12
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_APPROVAL_BINDING_MISMATCH",
        )

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_approval(
                plan,
                approval_12,
                current_semantic_input_sha256="f" * 64,
            )
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_APPROVAL_STALE"
        )

    def test_task_local_artifact_content_is_pure_and_content_addressed(
        self,
    ) -> None:
        plan = load_plan()
        original = copy.deepcopy(plan)

        artifact = repository_plan.build_repository_plan_artifact(plan)

        self.assertEqual(artifact.task_id, "task-multi-1")
        self.assertEqual(
            artifact.sha256, hashlib.sha256(artifact.content).hexdigest()
        )
        self.assertEqual(artifact.size, len(artifact.content))
        self.assertEqual(plan, original)
        self.assertFalse(
            hasattr(repository_plan, "persist_repository_plan")
        )
        self.assertFalse(
            hasattr(repository_plan, "dispatch_repository_worker")
        )

    def test_contracts_must_exist_in_injected_task_local_artifact_set(
        self,
    ) -> None:
        plan = load_plan()
        artifacts = {
            contract["artifact_id"]: contract["sha256"]
            for contract in plan["interface_contracts"]
        }
        validated = (
            repository_plan.validate_repository_plan_contract_artifacts(
                plan, artifacts
            )
        )
        self.assertEqual(validated["plan_id"], "plan-multi-1")

        missing = dict(artifacts)
        missing.pop("artifact-api-output-v1")
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_contract_artifacts(
                plan, missing
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_CONTRACT_ARTIFACT_MISSING",
        )

        mismatched = dict(artifacts)
        mismatched["artifact-api-output-v1"] = "f" * 64
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_contract_artifacts(
                plan, mismatched
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_CONTRACT_ARTIFACT_MISMATCH",
        )

    def test_approval_commit_revision_is_a_distinct_later_audit_fact(
        self,
    ) -> None:
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            approve(load_plan(), revision=11)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_APPROVAL_REVISION_INVALID",
        )
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.create_repository_plan_approval(
                load_plan(),
                plan_artifact_id="some-other-artifact",
                approval_intent="approve-repository-map/v1",
                approval_commit_revision=12,
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_ARTIFACT_IDENTITY_MISMATCH",
        )


class RepositoryMapExpansionTests(unittest.TestCase):
    def test_expansion_is_stable_ordered_dependent_and_deeply_immutable(
        self,
    ) -> None:
        plan = load_plan()
        approval = approve(plan)

        first = repository_plan.expand_repository_map(plan, approval)
        second = repository_plan.expand_repository_map(
            plan, approval, existing_expansion=first
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [child["repository_id"] for child in first["children"]],
            ["api", "docs", "web"],
        )
        self.assertEqual(
            first["children"][2]["dependencies"],
            (first["children"][0]["node_instance_id"],),
        )
        self.assertEqual(
            first["children"][0]["node_instance_id"],
            "repository-node-"
            "218def7bf28fe10703434f3c4c97f327f2f162fc91157e82bb0c3a4bf4f47818",
        )
        self.assertEqual(
            repository_plan.repository_map_expansion_sha256(first),
            "ef3c0a00f3fe2a769d3b541c626543296b39486e5dafddf488c20314cbcf9922",
        )
        with self.assertRaises(TypeError):
            first["map_epoch"] = 4
        with self.assertRaises(TypeError):
            first["children"][0]["repository_id"] = "other"

    def test_replay_reuses_children_and_conflicting_expansion_fails(
        self,
    ) -> None:
        plan = load_plan()
        approval = approve(plan)
        expansion = repository_plan.expand_repository_map(plan, approval)
        tampered = json.loads(
            json.dumps(
                {
                    key: (
                        [
                            {
                                child_key: (
                                    list(child_value)
                                    if isinstance(child_value, tuple)
                                    else child_value
                                )
                                for child_key, child_value in child.items()
                            }
                            for child in value
                        ]
                        if key == "children"
                        else (
                            list(value)
                            if isinstance(value, tuple)
                            else value
                        )
                    )
                    for key, value in expansion.items()
                }
            )
        )
        tampered["children"][0]["node_instance_id"] = (
            "repository-node-" + "f" * 64
        )

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.expand_repository_map(
                plan, approval, existing_expansion=tampered
            )
        self.assertEqual(
            raised.exception.code, "REPOSITORY_MAP_EXPANSION_CONFLICT"
        )

    def test_bundle_binding_separates_template_and_persisted_child_node(
        self,
    ) -> None:
        plan = load_plan()
        approval = approve(plan)
        bundle = workflow_bundle()

        validated = (
            repository_plan.validate_repository_plan_against_workflow_bundle(
                plan, bundle
            )
        )
        expansion = (
            repository_plan.expand_repository_map_for_workflow_bundle(
                plan, approval, bundle
            )
        )
        replay = (
            repository_plan.expand_repository_map_for_workflow_bundle(
                plan,
                approval,
                bundle,
                existing_expansion=expansion,
            )
        )

        self.assertEqual(validated["map_node_id"], "map.repositories/v1")
        self.assertEqual(expansion["map_node_id"], "map.repositories/v1")
        self.assertEqual(
            {child["node_id"] for child in expansion["children"]},
            {"IMPLEMENTING"},
        )
        self.assertEqual(expansion, replay)

        caller_join = json.loads(
            json.dumps(
                repository_plan._repository_plan_thaw(expansion)
            )
        )
        caller_join["children"][0]["node_id"] = "VERIFYING"
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.expand_repository_map_for_workflow_bundle(
                plan,
                approval,
                bundle,
                existing_expansion=caller_join,
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_MAP_EXPANSION_CONFLICT",
        )

    def test_bundle_binding_rejects_map_or_bundle_substitution(
        self,
    ) -> None:
        plan = load_plan()
        wrong_map = copy.deepcopy(plan)
        wrong_map["map_node_id"] = "map.other/v1"
        wrong_map = bind(wrong_map)
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_against_workflow_bundle(
                wrong_map, workflow_bundle()
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_MAP_BINDING_MISMATCH",
        )

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.validate_repository_plan_against_workflow_bundle(
                plan, workflow_bundle(bundle_sha256="e" * 64)
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_WORKFLOW_MISMATCH",
        )

    def test_node_identity_binds_every_approved_map_dimension(self) -> None:
        plan = load_plan()
        identity = repository_plan.repository_plan_identity(plan)
        base = {
            "task_id": plan["task_id"],
            "workflow_bundle_sha256": plan[
                "workflow_bundle_sha256"
            ],
            "plan_id": plan["plan_id"],
            "dag_sha256": identity.dag_sha256,
            "map_epoch": plan["map_epoch"],
            "repository_id": "api",
            "map_node_id": plan["map_node_id"],
        }
        baseline = repository_plan.repository_node_instance_id(**base)
        mutations = (
            ("task_id", "task-multi-2"),
            ("workflow_bundle_sha256", "e" * 64),
            ("plan_id", "plan-multi-2"),
            ("dag_sha256", "f" * 64),
            ("map_epoch", 4),
            ("repository_id", "docs"),
            ("map_node_id", "map.other/v1"),
        )
        for field, replacement in mutations:
            with self.subTest(field=field):
                changed = dict(base)
                changed[field] = replacement
                self.assertNotEqual(
                    repository_plan.repository_node_instance_id(
                        **changed
                    ),
                    baseline,
                )

    def test_repository_set_drift_stales_approval_before_expansion(
        self,
    ) -> None:
        plan = load_plan()
        approval = approve(plan)
        drifted = copy.deepcopy(plan)
        drifted["repositories"] = drifted["repositories"][:2]
        drifted["repository_set"] = ["api", "docs"]
        drifted["dependencies"] = []
        drifted = bind(drifted)

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.expand_repository_map(drifted, approval)
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_PLAN_APPROVAL_BINDING_MISMATCH",
        )


class RepositoryReadyFrontierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = load_plan()
        self.approval = approve(self.plan)

    def test_roots_need_current_approvals_but_not_dependency_order(
        self,
    ) -> None:
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval
        )

        self.assertEqual(
            [item.repository_id for item in frontier.ready], ["docs"]
        )
        blockers = {
            item.repository_id: item.codes for item in frontier.blocked
        }
        self.assertIn(
            "REQUIRED_APPROVAL_NOT_CURRENT", blockers["api"]
        )
        self.assertIn("DEPENDENCY_RESULT_MISSING", blockers["web"])

        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan,
            self.approval,
            approval_facts={"architecture/v1": current_fact()},
        )
        self.assertEqual(
            [item.repository_id for item in frontier.ready],
            ["api", "docs"],
        )

    def test_downstream_requires_accepted_current_success_contracts(
        self,
    ) -> None:
        result = {
            "result_id": "result-api-1",
            "outcome": "SUCCEEDED",
            "accepted": True,
            "current": True,
            "output_contract_sha256": ["a" * 64],
        }
        common = {
            "approval_facts": {
                "architecture/v1": current_fact()
            },
            "accepted_results": {"api": result},
            "evidence_facts": {
                "a" * 64: current_fact(
                    repository_id="api", result_id="result-api-1"
                ),
                "c" * 64: current_fact(),
            },
        }
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **common
        )
        self.assertEqual(
            [item.repository_id for item in frontier.ready],
            ["api", "docs", "web"],
        )

        for field, replacement, expected in (
            ("accepted", False, "DEPENDENCY_RESULT_NOT_ACCEPTED"),
            ("current", False, "DEPENDENCY_RESULT_STALE"),
            (
                "outcome",
                "FAILED",
                "DEPENDENCY_RESULT_NOT_SUCCESSFUL",
            ),
            (
                "output_contract_sha256",
                ["b" * 64],
                "DEPENDENCY_OUTPUT_CONTRACT_MISMATCH",
            ),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(common)
                changed["accepted_results"]["api"][field] = replacement
                frontier = (
                    repository_plan.calculate_repository_ready_frontier(
                        self.plan, self.approval, **changed
                    )
                )
                blockers = {
                    item.repository_id: item.codes
                    for item in frontier.blocked
                }
                self.assertIn(expected, blockers["web"])

        changed = copy.deepcopy(common)
        changed["evidence_facts"]["a" * 64]["current"] = False
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **changed
        )
        blockers = {
            item.repository_id: item.codes for item in frontier.blocked
        }
        self.assertIn(
            "DEPENDENCY_OUTPUT_EVIDENCE_NOT_CURRENT",
            blockers["web"],
        )

        changed = copy.deepcopy(common)
        changed["evidence_facts"]["a" * 64][
            "repository_id"
        ] = "docs"
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **changed
        )
        blockers = {
            item.repository_id: item.codes for item in frontier.blocked
        }
        self.assertIn(
            "DEPENDENCY_OUTPUT_EVIDENCE_NOT_CURRENT",
            blockers["web"],
        )

    def test_result_insertion_order_cannot_change_the_frontier(self) -> None:
        facts = {
            "approval_facts": {
                "architecture/v1": current_fact()
            },
            "accepted_results": {
                "docs": {
                    "result_id": "result-docs",
                    "outcome": "SUCCEEDED",
                    "accepted": True,
                    "current": True,
                    "output_contract_sha256": [],
                },
                "api": {
                    "result_id": "result-api",
                    "outcome": "SUCCEEDED",
                    "accepted": True,
                    "current": True,
                    "output_contract_sha256": ["a" * 64],
                },
            },
            "evidence_facts": {
                "a" * 64: current_fact(),
                "c" * 64: current_fact(),
            },
        }
        first = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **facts
        )
        reversed_results = dict(
            reversed(list(facts["accepted_results"].items()))
        )
        second = repository_plan.calculate_repository_ready_frontier(
            self.plan,
            self.approval,
            accepted_results=reversed_results,
            approval_facts=facts["approval_facts"],
            evidence_facts=facts["evidence_facts"],
        )
        self.assertEqual(first, second)

    def test_concurrency_limits_dispatch_only_not_semantic_readiness(
        self,
    ) -> None:
        plan = copy.deepcopy(self.plan)
        plan["dependencies"] = []
        plan["repositories"][2][
            "required_evidence_contract_sha256"
        ] = []
        plan["concurrency_policy"] = {
            "max_workers": 2,
            "max_writable_workers": 1,
        }
        plan = bind(plan)
        approval = approve(plan)

        frontier = repository_plan.calculate_repository_ready_frontier(
            plan,
            approval,
            approval_facts={"architecture/v1": current_fact()},
        )

        self.assertEqual(
            [item.repository_id for item in frontier.ready],
            ["api", "docs", "web"],
        )
        self.assertEqual(
            [item.repository_id for item in frontier.dispatchable],
            ["api", "docs"],
        )
        self.assertEqual(frontier.available_workers, 2)
        self.assertEqual(frontier.available_writable_workers, 1)

    def test_running_workers_reduce_capacity_without_changing_dag(
        self,
    ) -> None:
        plan = copy.deepcopy(self.plan)
        plan["dependencies"] = []
        plan["repositories"][2][
            "required_evidence_contract_sha256"
        ] = []
        plan = bind(plan)
        approval = approve(plan)
        frontier = repository_plan.calculate_repository_ready_frontier(
            plan,
            approval,
            node_facts={
                "api": {"state": "RUNNING", "attempts_started": 1}
            },
        )

        self.assertEqual(frontier.active_workers, 1)
        self.assertEqual(frontier.active_writable_workers, 1)
        self.assertEqual(
            [item.repository_id for item in frontier.ready], ["docs", "web"]
        )
        self.assertEqual(
            [item.repository_id for item in frontier.dispatchable],
            ["docs", "web"],
        )

    def test_retry_requires_policy_capacity_and_current_approval(
        self,
    ) -> None:
        nodes = {
            "api": {"state": "FAILED", "attempts_started": 1}
        }
        common = {
            "node_facts": nodes,
            "approval_facts": {"architecture/v1": current_fact()},
        }
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **common
        )
        blockers = {
            item.repository_id: item.codes for item in frontier.blocked
        }
        self.assertIn("RETRY_APPROVAL_NOT_CURRENT", blockers["api"])

        retry_id = repository_plan.repository_retry_approval_id("api", 2)
        common["approval_facts"][retry_id] = current_fact()
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **common
        )
        api = next(
            item for item in frontier.ready
            if item.repository_id == "api"
        )
        self.assertEqual(api.attempt, 2)

        nodes["api"]["attempts_started"] = 2
        frontier = repository_plan.calculate_repository_ready_frontier(
            self.plan, self.approval, **common
        )
        blockers = {
            item.repository_id: item.codes for item in frontier.blocked
        }
        self.assertIn("RETRY_EXHAUSTED", blockers["api"])

    def test_stale_plan_approval_and_unknown_repository_facts_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.calculate_repository_ready_frontier(
                self.plan,
                self.approval,
                current_semantic_input_sha256="f" * 64,
            )
        self.assertEqual(
            raised.exception.code, "REPOSITORY_PLAN_APPROVAL_STALE"
        )

        with self.assertRaises(
            repository_plan.RepositoryPlanError
        ) as raised:
            repository_plan.calculate_repository_ready_frontier(
                self.plan,
                self.approval,
                node_facts={
                    "ghost": {
                        "state": "PENDING",
                        "attempts_started": 0,
                    }
                },
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_READY_FACT_UNKNOWN_REPOSITORY",
        )

    def test_ready_calculation_is_pure_and_results_are_immutable(
        self,
    ) -> None:
        plan = load_plan()
        approval = approve(plan)
        original_plan = copy.deepcopy(plan)

        frontier = repository_plan.calculate_repository_ready_frontier(
            plan, approval
        )

        self.assertEqual(plan, original_plan)
        self.assertIsInstance(frontier.ready, tuple)
        with self.assertRaises(
            (AttributeError, TypeError)
        ):
            frontier.ready += ()


if __name__ == "__main__":
    unittest.main()
