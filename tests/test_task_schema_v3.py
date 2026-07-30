from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "scripts" / "dev_flow_parts" / "workflow_state.py"
FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "task_state"
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_workflow_state_v3_tests", STATE_PATH
)
assert SPEC is not None and SPEC.loader is not None
workflow_state = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow_state
SPEC.loader.exec_module(workflow_state)


def load_fixture(name: str) -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def bundle_descriptor(
    *,
    bundle_sha256: str = "b" * 64,
) -> dict[str, object]:
    return {
        "workflow_id": "full",
        "workflow_version": 3,
        "graph_sha256": "a" * 64,
        "bundle_sha256": bundle_sha256,
        "execution_profiles": ("single-repository",),
        "nodes": {
            "IMPLEMENTING": {"id": "IMPLEMENTING"},
            "VERIFYING": {"id": "VERIFYING"},
        },
        "graph": {
            "schema": "dev-flow-workflow/v1",
            "flow": "full",
            "execution_profiles": ["single-repository"],
            "nodes": [
                {"id": "IMPLEMENTING"},
                {"id": "VERIFYING"},
            ],
        },
    }


def resolver_for(
    *,
    bundle: dict[str, object] | None = None,
):
    legacy = {
        (1, "full"): {
            "id": "full-legacy",
            "version": 2,
            "adapter": "full@legacy-v2",
        },
        (2, "lite"): {
            "id": "lite-legacy",
            "version": 2,
            "adapter": "lite@legacy-v2",
        },
    }
    bundle_value = bundle or bundle_descriptor()
    bundles = {
        ("full", 3, "b" * 64): bundle_value,
    }

    def resolve(state: object, *, purpose: str):
        return workflow_state.resolve_task_workflow(
            state,
            legacy_resolver=legacy,
            bundle_resolver=bundles,
            purpose=purpose,
        )

    return resolve


def multi_bundle_descriptor() -> dict[str, object]:
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
        "workflow_id": "full",
        "workflow_version": 3,
        "graph_sha256": "a" * 64,
        "bundle_sha256": "b" * 64,
        "execution_profiles": (
            "single-repository",
            "multi-repository",
        ),
        "repository_orchestration": metadata,
        "nodes": nodes,
        "graph": {
            "schema": "dev-flow-workflow/v1",
            "flow": "full",
            "execution_profiles": [
                "single-repository",
                "multi-repository",
            ],
            "repository_orchestration": metadata,
            "nodes": list(nodes.values()),
        },
    }


def multi_task_state() -> dict[str, object]:
    return {
        "schema_version": 3,
        "task_id": "multi-state",
        "flow": "full",
        "execution_profile": "multi-repository",
        "status": "IMPLEMENTING",
        "revision": 4,
        "workflow_ref": {
            "id": "full",
            "version": 3,
            "schema": "dev-flow-workflow/v1",
            "graph_sha256": "a" * 64,
            "bundle_sha256": "b" * 64,
        },
        "node_instances": [
            {
                "node_instance_id": "coarse-implementing",
                "node_id": "IMPLEMENTING",
                "state": "RUNNING",
                "dependencies": [],
                "attempts": [],
            },
            {
                "node_instance_id": "coarse-verifying",
                "node_id": "VERIFYING",
                "state": "PENDING",
                "dependencies": [],
                "attempts": [],
            },
            {
                "node_instance_id": "repo-api",
                "node_id": "IMPLEMENTING",
                "repository_id": "api",
                "state": "READY",
                "dependencies": [],
                "attempts": [],
            },
            {
                "node_instance_id": "repo-web",
                "node_id": "IMPLEMENTING",
                "repository_id": "web",
                "state": "PENDING",
                "dependencies": ["repo-api"],
                "attempts": [],
            },
        ],
        "orchestration": {
            "schema": "dev-flow-orchestration-state/v1",
            "expansion": {
                "schema": "dev-flow-repository-map-expansion/v1",
                "task_id": "multi-state",
                "workflow_bundle_sha256": "b" * 64,
                "plan_id": "plan-multi",
                "dag_sha256": "c" * 64,
                "semantic_input_sha256": "d" * 64,
                "map_node_id": "map.repositories/v1",
                "map_epoch": 1,
                "repository_set": ["api", "web"],
                "children": [
                    {
                        "node_instance_id": "repo-api",
                        "node_id": "IMPLEMENTING",
                        "repository_id": "api",
                        "repository_identity_sha256": "1" * 64,
                        "map_epoch": 1,
                        "dependencies": [],
                    },
                    {
                        "node_instance_id": "repo-web",
                        "node_id": "IMPLEMENTING",
                        "repository_id": "web",
                        "repository_identity_sha256": "2" * 64,
                        "map_epoch": 1,
                        "dependencies": ["repo-api"],
                    },
                ],
            },
        },
    }


class TaskSchemaV3Tests(unittest.TestCase):
    def test_schema_constants_extend_without_redefining_v2(self) -> None:
        self.assertEqual(workflow_state.V3_TASK_SCHEMA_VERSION, 3)
        self.assertEqual(
            workflow_state.LEGACY_TASK_SCHEMA_VERSIONS,
            frozenset({1, 2}),
        )
        self.assertEqual(
            workflow_state.SUPPORTED_TASK_SCHEMA_VERSIONS,
            frozenset({1, 2, 3}),
        )

    def test_valid_v3_structure_is_deeply_read_only(self) -> None:
        state = load_fixture("schema_v3_full.json")

        validated = workflow_state.validate_v3_task_state(state)

        self.assertEqual(validated["schema_version"], 3)
        self.assertEqual(
            validated["workflow_ref"]["bundle_sha256"], "b" * 64
        )
        self.assertEqual(
            validated["execution_profile"], "single-repository"
        )
        self.assertEqual(
            validated["node_instances"][0]["attempts"][0][
                "result_refs"
            ][0]["result_id"],
            "result-1",
        )
        self.assertEqual(
            validated["node_instances"][0]["attempts"][0][
                "runtime_handle"
            ]["handle_id"],
            "thread-1",
        )
        with self.assertRaises(TypeError):
            validated["workflow_ref"]["id"] = "replacement"
        with self.assertRaises(TypeError):
            validated["node_instances"][0]["state"] = "FAILED"

    def test_mutation_validation_resolves_exact_pinned_bundle(self) -> None:
        state = load_fixture("schema_v3_full.json")

        resolution = workflow_state.validate_task_state_for_mutation(
            state, resolver=resolver_for()
        )

        self.assertEqual(resolution["kind"], "bundle")
        self.assertEqual(resolution["id"], "full")
        self.assertEqual(resolution["version"], 3)
        self.assertEqual(resolution["bundle_sha256"], "b" * 64)
        with self.assertRaises(TypeError):
            resolution["bundle_sha256"] = "c" * 64

    def test_bundle_resolver_callable_receives_immutable_exact_reference(
        self,
    ) -> None:
        state = load_fixture("schema_v3_full.json")
        received = None

        def bundle_resolver(reference: object) -> dict[str, object]:
            nonlocal received
            received = reference
            return bundle_descriptor()

        resolution = workflow_state.resolve_task_workflow(
            state,
            legacy_resolver={},
            bundle_resolver=bundle_resolver,
            purpose="inspection",
        )

        self.assertEqual(received["bundle_sha256"], "b" * 64)
        with self.assertRaises(TypeError):
            received["id"] = "other"
        self.assertEqual(resolution["kind"], "bundle")

    def test_mutation_rejects_unsupported_or_substituted_bundle(self) -> None:
        future = load_fixture("schema_v4_future.json")
        with self.assertRaises(workflow_state.WorkflowStateError) as raised:
            workflow_state.validate_task_state_for_mutation(
                future, resolver=resolver_for()
            )
        self.assertEqual(raised.exception.code, "TASK_SCHEMA_UNSUPPORTED")

        current = load_fixture("schema_v3_full.json")
        with self.assertRaises(workflow_state.WorkflowStateError) as raised:
            workflow_state.validate_task_state_for_mutation(
                current,
                resolver=resolver_for(
                    bundle=bundle_descriptor(bundle_sha256="c" * 64)
                ),
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_RESOLUTION_MISMATCH"
        )

    def test_inspection_is_tolerant_for_future_schema_and_does_not_resolve(
        self,
    ) -> None:
        state = load_fixture("schema_v4_future.json")
        original = copy.deepcopy(state)
        resolver_called = False

        def forbidden_resolver(_state: object, *, purpose: str):
            nonlocal resolver_called
            resolver_called = True
            raise AssertionError(purpose)

        inspection = workflow_state.inspect_task_state(
            state, resolver=forbidden_resolver
        )

        self.assertFalse(inspection["supported"])
        self.assertFalse(inspection["valid"])
        self.assertFalse(inspection["mutation_ready"])
        self.assertEqual(
            inspection["errors"][0]["code"], "TASK_SCHEMA_UNSUPPORTED"
        )
        self.assertEqual(
            inspection["workflow_ref"]["future_identity_field"],
            "retained-for-inspection",
        )
        self.assertFalse(resolver_called)
        self.assertEqual(state, original)

    def test_inspection_distinguishes_supported_but_malformed_state(
        self,
    ) -> None:
        state = load_fixture("schema_v3_full.json")
        state["workflow_ref"]["unexpected"] = True

        inspection = workflow_state.inspect_task_state(
            state, resolver=resolver_for()
        )

        self.assertTrue(inspection["supported"])
        self.assertFalse(inspection["valid"])
        self.assertEqual(
            inspection["errors"][0]["code"], "WORKFLOW_REF_INVALID"
        )

    def test_strict_workflow_ref_rejects_version_digest_and_contract_drift(
        self,
    ) -> None:
        state = load_fixture("schema_v3_full.json")
        mutations = (
            ("version", True, "WORKFLOW_REF_INVALID"),
            ("graph_sha256", "ABC", "WORKFLOW_REF_INVALID"),
            ("schema", "dev-flow-workflow/v2", "WORKFLOW_REF_UNSUPPORTED"),
        )
        for field, value, code in mutations:
            with self.subTest(field=field):
                damaged = copy.deepcopy(state)
                damaged["workflow_ref"][field] = value
                with self.assertRaises(
                    workflow_state.WorkflowStateError
                ) as raised:
                    workflow_state.validate_v3_task_state(damaged)
                self.assertEqual(raised.exception.code, code)

    def test_node_attempt_result_and_runtime_bindings_are_strict(self) -> None:
        state = load_fixture("schema_v3_full.json")
        attempt = state["node_instances"][0]["attempts"][0]
        mutations = (
            (
                lambda item: item.update({"attempt": 2}),
                "NODE_ATTEMPT_INVALID",
            ),
            (
                lambda item: item["result_refs"][0].update(
                    {"node_instance_id": "node-2"}
                ),
                "RESULT_REFERENCE_MISMATCH",
            ),
            (
                lambda item: item["runtime_handle"].update(
                    {"task_id": "another-task"}
                ),
                "RUNTIME_HANDLE_MISMATCH",
            ),
        )
        for mutate, code in mutations:
            with self.subTest(code=code):
                damaged = copy.deepcopy(state)
                damaged_attempt = damaged["node_instances"][0][
                    "attempts"
                ][0]
                mutate(damaged_attempt)
                with self.assertRaises(
                    workflow_state.WorkflowStateError
                ) as raised:
                    workflow_state.validate_v3_task_state(damaged)
                self.assertEqual(raised.exception.code, code)
        self.assertEqual(attempt["attempt"], 1)

    def test_node_identity_order_uniqueness_and_dependencies_are_validated(
        self,
    ) -> None:
        state = load_fixture("schema_v3_full.json")
        cases = []
        reversed_nodes = copy.deepcopy(state)
        reversed_nodes["node_instances"].reverse()
        cases.append(reversed_nodes)
        duplicate = copy.deepcopy(state)
        duplicate["node_instances"][1]["node_instance_id"] = "node-1"
        cases.append(duplicate)
        dangling = copy.deepcopy(state)
        dangling["node_instances"][1]["dependencies"] = ["node-missing"]
        cases.append(dangling)

        for damaged in cases:
            with self.subTest(task=damaged["task_id"]):
                with self.assertRaises(
                    workflow_state.WorkflowStateError
                ) as raised:
                    workflow_state.validate_v3_task_state(damaged)
                self.assertEqual(
                    raised.exception.code, "NODE_INSTANCE_INVALID"
                )

    def test_execution_profile_is_required_without_changing_legacy(
        self,
    ) -> None:
        missing = load_fixture("schema_v3_full.json")
        missing.pop("execution_profile")
        with self.assertRaises(
            workflow_state.WorkflowStateError
        ) as raised:
            workflow_state.validate_v3_task_state(missing)
        self.assertEqual(
            raised.exception.code, "TASK_EXECUTION_PROFILE_INVALID"
        )

        legacy = {
            "schema_version": 2,
            "flow": "lite",
        }
        resolution = workflow_state.resolve_task_workflow(
            legacy,
            legacy_resolver={
                (2, "lite"): {
                    "id": "lite-legacy",
                    "version": 2,
                }
            },
            bundle_resolver={},
            purpose="inspection",
        )
        self.assertEqual(resolution["kind"], "legacy")

    def test_bundle_aware_multi_state_binds_expansion_and_dynamic_nodes(
        self,
    ) -> None:
        state = multi_task_state()
        validated = (
            workflow_state.validate_v3_task_state_against_bundle(
                state, multi_bundle_descriptor()
            )
        )
        self.assertEqual(
            validated["execution_profile"], "multi-repository"
        )
        self.assertEqual(
            validated["orchestration"]["expansion"]["map_node_id"],
            "map.repositories/v1",
        )

        cases = (
            (
                lambda item: item["node_instances"][0].update(
                    {"node_id": "CALLER_JOIN"}
                ),
                "NODE_INSTANCE_BUNDLE_MISMATCH",
            ),
            (
                lambda item: item["orchestration"].update(
                    {"expansion": None}
                ),
                "ORCHESTRATION_EXPANSION_REQUIRED",
            ),
            (
                lambda item: item["orchestration"]["expansion"].update(
                    {"map_node_id": "map.other/v1"}
                ),
                "ORCHESTRATION_EXPANSION_MISMATCH",
            ),
            (
                lambda item: item["orchestration"]["expansion"][
                    "children"
                ][0].update({"node_id": "VERIFYING"}),
                "ORCHESTRATION_EXPANSION_INVALID",
            ),
            (
                lambda item: item["node_instances"][2].update(
                    {"node_id": "VERIFYING"}
                ),
                "ORCHESTRATION_EXPANSION_MISMATCH",
            ),
            (
                lambda item: item["orchestration"].update(
                    {"schema": "dev-flow-orchestration-state/v2"}
                ),
                "ORCHESTRATION_STATE_INVALID",
            ),
        )
        for mutate, code in cases:
            with self.subTest(code=code):
                damaged = copy.deepcopy(state)
                mutate(damaged)
                with self.assertRaises(
                    workflow_state.WorkflowStateError
                ) as raised:
                    workflow_state.validate_v3_task_state_against_bundle(
                        damaged, multi_bundle_descriptor()
                    )
                self.assertEqual(raised.exception.code, code)

    def test_single_profile_rejects_orchestration_and_repository_children(
        self,
    ) -> None:
        state = load_fixture("schema_v3_full.json")
        state["orchestration"] = {
            "schema": "dev-flow-orchestration-state/v1",
            "expansion": None,
        }
        with self.assertRaises(
            workflow_state.WorkflowStateError
        ) as raised:
            workflow_state.validate_v3_task_state_against_bundle(
                state, bundle_descriptor()
            )
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_STATE_FORBIDDEN"
        )

        state = multi_task_state()
        state.pop("orchestration")
        with self.assertRaises(
            workflow_state.WorkflowStateError
        ) as raised:
            workflow_state.validate_v3_task_state_against_bundle(
                state, multi_bundle_descriptor()
            )
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_STATE_REQUIRED"
        )


if __name__ == "__main__":
    unittest.main()
