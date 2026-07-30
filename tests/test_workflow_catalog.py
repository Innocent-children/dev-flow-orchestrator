from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


identity = _source_module(
    "dev_flow_catalog_test_identity",
    ROOT / "scripts" / "workflow_bundle_identity.py",
)
catalog = _source_module(
    "dev_flow_catalog_test_catalog",
    ROOT / "scripts" / "dev_flow_parts" / "workflow_catalog.py",
)
WORKFLOWS = ROOT / "workflows"
LEGACY_EDGES = (
    ROOT / "tests" / "fixtures" / "workflow_legacy" / "edges.jsonl"
)
FULL_ORDER = (
    "INTAKE",
    "PREFLIGHTED",
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
)
LITE_ORDER = (
    "INTAKE",
    "PREFLIGHTED",
    "IMPLEMENTING",
    "VERIFYING",
    "DONE",
)


def _load_runtime_module(name: str) -> types.ModuleType:
    path = ROOT / "scripts" / "dev_flow.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


class WorkflowCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        references = set()
        for graph_path in sorted(
            (WORKFLOWS / "bundles").glob("*/workflow.json")
        ):
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            references.update(
                (
                    item["registry"],
                    item["id"],
                    item["version"],
                )
                for item in graph["contracts"]
            )
        cls.references = frozenset(references)
        cls.resolver = catalog.StaticContractResolver(cls.references)

    def _copy_workflows(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "workflows"
        shutil.copytree(WORKFLOWS, target)
        return target

    def _refresh_static_test_digests(self, root: Path) -> None:
        catalog_path = root / "catalog.json"
        document = self._read_json(catalog_path)
        digests: dict[tuple[str, int], str] = {}
        for entry in document["bundles"]:
            bundle_root = root / entry["root"]
            graph_source = (bundle_root / entry["graph"]).read_bytes()
            files = tuple(
                identity.BundleFile(
                    item["path"],
                    item["kind"],
                    (bundle_root / item["path"]).read_bytes(),
                )
                for item in entry["files"]
            )
            result = identity.compute_workflow_bundle_identity(
                graph_source,
                files,
                (),
            )
            entry["graph_sha256"] = result.graph_sha256
            entry["bundle_sha256"] = result.bundle_sha256
            digests[
                (entry["workflow_id"], entry["workflow_version"])
            ] = result.bundle_sha256
        self._write_json(catalog_path, document)

        activation_path = root / "activation.json"
        activation = self._read_json(activation_path)
        for profile in activation["profiles"]:
            profile["bundle_sha256"] = digests[
                (profile["workflow_id"], profile["workflow_version"])
            ]
        self._write_json(activation_path, activation)

    def _load(
        self,
        root: Path = WORKFLOWS,
        *,
        resolver: object | None = None,
    ) -> catalog.WorkflowCatalog:
        return catalog.load_workflow_catalog(
            root,
            contract_resolver=resolver or self.resolver,
            identity_api=identity,
        )

    def _assert_load_error(
        self,
        code: str,
        root: Path,
        *,
        resolver: object | None = None,
    ) -> catalog.WorkflowCatalogError:
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._load(root, resolver=resolver)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.as_dict()["code"], code)
        return raised.exception

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        return value

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_packaged_catalog_loads_six_sealed_immutable_bundles(self) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)

        self.assertTrue(loaded.sealed)
        self.assertEqual(
            tuple(loaded.bundles),
            (
                ("full", 3),
                ("full", 4),
                ("lite", 3),
                ("lite", 4),
                ("full-legacy", 2),
                ("lite-legacy", 2),
            ),
        )
        self.assertEqual(len(loaded.bundles_by_identity), 6)
        self.assertEqual(
            {
                (
                    item["workflow_id"],
                    item["workflow_version"],
                    item["execution_profile"],
                )
                for item in loaded.activations
            },
            {
                ("full", 3, "single-repository"),
                ("full", 3, "multi-repository"),
                ("lite", 3, "single-repository"),
            },
        )
        self.assertTrue(
            all(not item["active"] for item in loaded.activations)
        )
        self.assertEqual(
            loaded.resolve("full", 3).active_profiles,
            (),
        )
        self.assertEqual(
            loaded.resolve("lite", 3).active_profiles,
            (),
        )
        self.assertEqual(
            loaded.resolve("full", 4).active_profiles,
            (),
        )
        self.assertEqual(
            loaded.resolve("lite", 4).active_profiles,
            (),
        )
        self.assertTrue(
            all(
                not loaded.resolve(workflow_id, 2).active_profiles
                for workflow_id in ("full-legacy", "lite-legacy")
            )
        )
        self.assertEqual(
            loaded.resolve("full-legacy", 2).graph["task_schema_versions"],
            (1, 2),
        )
        self.assertEqual(
            loaded.resolve("full", 3).graph["task_schema_versions"],
            (3,),
        )
        self.assertEqual(
            loaded.resolve("full", 4).graph["task_schema_versions"],
            (3,),
        )
        with self.assertRaises(TypeError):
            loaded.bundles[("other", 1)] = loaded.resolve("full", 3)
        with self.assertRaises(TypeError):
            loaded.resolve("full", 3).graph["flow"] = "lite"
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            loaded.resolve("missing", 1)
        self.assertEqual(raised.exception.code, "WORKFLOW_BUNDLE_UNKNOWN")

    def test_repository_orchestration_metadata_is_static_and_strict(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        full = loaded.resolve("full", 3)
        metadata = full.repository_orchestration
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(
            metadata["map"]["child_template"]["template_id"],
            "map.repositories/v1",
        )
        self.assertEqual(
            metadata["map"]["child_template"]["node_id"],
            "IMPLEMENTING",
        )
        self.assertEqual(metadata["join"]["node_id"], "VERIFYING")
        self.assertIsNone(
            loaded.resolve("lite", 3).repository_orchestration
        )
        with self.assertRaises(TypeError):
            metadata["schema"] = "replacement"

        cases = (
            (
                lambda graph: graph.pop("repository_orchestration"),
                "WORKFLOW_ORCHESTRATION_REQUIRED",
            ),
            (
                lambda graph: graph["repository_orchestration"].update(
                    {"unexpected": True}
                ),
                "WORKFLOW_UNKNOWN_FIELD",
            ),
            (
                lambda graph: graph["repository_orchestration"]["map"].update(
                    {"parent_node_id": "UNKNOWN"}
                ),
                "WORKFLOW_REFERENCE_DANGLING",
            ),
            (
                lambda graph: graph["repository_orchestration"]["map"].update(
                    {"parent_node_id": "INTAKE"}
                ),
                "WORKFLOW_ORCHESTRATION_NODE_MISMATCH",
            ),
            (
                lambda graph: graph["repository_orchestration"]["join"].update(
                    {"node_id": "IMPLEMENTING"}
                ),
                "WORKFLOW_ORCHESTRATION_INVALID",
            ),
            (
                lambda graph: graph["repository_orchestration"]["join"].update(
                    {"node_id": "REVIEWING"}
                ),
                "WORKFLOW_ORCHESTRATION_NODE_MISMATCH",
            ),
            (
                lambda graph: graph["repository_orchestration"]["map"][
                    "child_template"
                ].update({"template_id": "map.other/v1"}),
                "WORKFLOW_ORCHESTRATION_INVALID",
            ),
            (
                lambda graph: graph["repository_orchestration"][
                    "operation_ids"
                ].append("orchestration.artifact.record/v1"),
                "WORKFLOW_DUPLICATE_ID",
            ),
            (
                lambda graph: graph["repository_orchestration"][
                    "operation_ids"
                ].reverse(),
                "WORKFLOW_ORCHESTRATION_INVALID",
            ),
            (
                lambda graph: graph["repository_orchestration"][
                    "operation_ids"
                ].__setitem__(0, "not-versioned"),
                "WORKFLOW_ORCHESTRATION_INVALID",
            ),
            (
                lambda graph: graph["repository_orchestration"]["map"].update(
                    {"command": ["unsafe"]}
                ),
                "WORKFLOW_EXECUTABLE_CONTENT_FORBIDDEN",
            ),
        )
        for mutation, code in cases:
            with self.subTest(code=code):
                root = self._copy_workflows()
                graph_path = (
                    root / "bundles" / "full-v3" / "workflow.json"
                )
                graph = self._read_json(graph_path)
                mutation(graph)
                self._write_json(graph_path, graph)
                self._assert_load_error(code, root)

        root = self._copy_workflows()
        full_path = root / "bundles" / "full-v3" / "workflow.json"
        lite_path = root / "bundles" / "lite-v3" / "workflow.json"
        full_graph = self._read_json(full_path)
        lite_graph = self._read_json(lite_path)
        lite_graph["repository_orchestration"] = full_graph[
            "repository_orchestration"
        ]
        self._write_json(lite_path, lite_graph)
        self._refresh_static_test_digests(root)
        self._assert_load_error(
            "WORKFLOW_ORCHESTRATION_FORBIDDEN", root
        )

        root = self._copy_workflows()
        lite_path = root / "bundles" / "lite-v3" / "workflow.json"
        lite_graph = self._read_json(lite_path)
        lite_graph["execution_profiles"].append("multi-repository")
        self._write_json(lite_path, lite_graph)
        self._refresh_static_test_digests(root)
        self._assert_load_error(
            "WORKFLOW_ORCHESTRATION_FORBIDDEN", root
        )

    def test_builtin_graphs_preserve_order_edges_and_automatic_movement(self) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        expected_automatic = {
            ("full", 3): {
                ("BASELINED", "INDEXED", "action", "record-index"),
                ("WORKSPACE_READY", "PLANNING", "transition", "transition"),
                ("IMPLEMENTING", "VERIFYING", "transition", "transition"),
                ("VERIFYING", "REVIEWING", "action", "review-snapshot"),
            },
            ("lite", 3): {
                ("IMPLEMENTING", "VERIFYING", "transition", "transition"),
            },
        }
        for key, bundle in loaded.bundles.items():
            with self.subTest(bundle=key):
                expected_order = (
                    FULL_ORDER
                    if bundle.graph["flow"] == "full"
                    else LITE_ORDER
                )
                self.assertEqual(bundle.graph["ordered_nodes"], expected_order)
                automatic = {
                    (
                        edge["source"],
                        edge["target"],
                        edge["trigger"]["kind"],
                        edge["trigger"]["id"],
                    )
                    for edge in bundle.edges
                    if edge["automatic"]
                }
                canonical_key = (
                    ("full", 3)
                    if bundle.graph["flow"] == "full"
                    else ("lite", 3)
                )
                self.assertEqual(automatic, expected_automatic[canonical_key])
                self.assertEqual(
                    len(bundle.edges),
                    79 if bundle.graph["flow"] == "full" else 30,
                )
                self.assertFalse(
                    any(
                        edge["automatic"]
                        and edge["target"] in {"DONE", "CANCELLED"}
                        for edge in bundle.edges
                    )
                )
                for node_id in expected_order[:-1]:
                    targets = {
                        edge["target"] for edge in bundle.legal_edges(node_id)
                    }
                    self.assertIn("BLOCKED", targets)
                    self.assertIn("CANCELLED", targets)
                self.assertEqual(bundle.legal_edges("DONE"), ())
                blocked_targets = {
                    edge["target"] for edge in bundle.legal_edges("BLOCKED")
                }
                expected_blocked_targets = (
                    set(expected_order[:-1]) | {"CANCELLED"}
                )
                if bundle.workflow_version == 3:
                    expected_blocked_targets.add("BLOCKED")
                self.assertEqual(
                    blocked_targets,
                    expected_blocked_targets,
                )
                for source in (*expected_order[:-1], "BLOCKED"):
                    cancellation_triggers = {
                        edge["trigger"]["id"]
                        for edge in bundle.legal_edges(source)
                        if edge["target"] == "CANCELLED"
                    }
                    self.assertEqual(
                        cancellation_triggers,
                        {"cancel", "transition-cancel"},
                    )
                self.assertTrue(
                    any(edge["class"] == "rework" for edge in bundle.edges)
                )

    def test_bundle_metadata_is_localized_bounded_and_role_complete(self) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        for key, bundle in loaded.bundles.items():
            with self.subTest(bundle=key):
                self.assertEqual(set(bundle.graph["labels"]), {"en", "zh-CN"})
                playbook_limit = bundle.graph["projection"]["playbook_max_bytes"]
                for node in bundle.nodes.values():
                    self.assertEqual(set(node["labels"]), {"en", "zh-CN"})
                    self.assertTrue(all(node["labels"].values()))
                    self.assertTrue(node["required_sections"])
                    playbook = bundle.root / node["playbook"]["path"]
                    self.assertLessEqual(playbook.stat().st_size, playbook_limit)
                roles = {
                    node["index_role"]
                    for node in bundle.nodes.values()
                    if node["index_role"] is not None
                }
                if bundle.graph["flow"] == "full":
                    self.assertEqual(roles, {"baseline", "origin", "workspace"})
                else:
                    self.assertEqual(roles, set())

    def test_every_node_has_a_complete_versioned_execution_contract(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        contract_fields = {
            "contract_version",
            "input_schema",
            "output_schema",
            "required_evidence",
            "produced_evidence",
            "context_projection",
            "approval_policy",
            "effect_policy",
            "retry_policy",
            "recovery_policy",
            "allowed_state_writes",
        }
        kernel_owned_reducers = {
            "reducer.status/v1",
            "reducer.cancel/v1",
            "reducer.invalidate-review/v1",
            "reducer.invalidate-plan/v1",
            "reducer.impact-reassess/v1",
        }
        for key, bundle in loaded.bundles.items():
            expected_kind = (
                "state" if bundle.graph["legacy_adapter"] else "generic"
            )
            expected_context = (
                "legacy-v1"
                if bundle.graph["legacy_adapter"]
                else "node-v1"
            )
            for node_id, node in bundle.nodes.items():
                with self.subTest(bundle=key, node=node_id):
                    self.assertTrue(contract_fields.issubset(node))
                    self.assertEqual(node["kind"], expected_kind)
                    self.assertEqual(node["contract_version"], "v1")
                    self.assertEqual(
                        node["context_projection"]["profile"],
                        expected_context,
                    )
                    self.assertEqual(
                        node["input_schema"], "dev-flow-node-input/v1"
                    )
                    self.assertEqual(
                        node["output_schema"], "dev-flow-node-result/v1"
                    )
                    expected_action_writes = {
                        path
                        for edge in bundle.legal_action_edges(node_id)
                        for path in edge["allowed_state_writes"]
                    }
                    self.assertEqual(
                        set(node["allowed_state_writes"]),
                        expected_action_writes,
                    )
            for edge in bundle.edges:
                self.assertNotIn("invalidates", edge)
                self.assertIn("set-task-status", edge["kernel_effects"])
                self.assertTrue(
                    kernel_owned_reducers.isdisjoint(
                        reference["id"] for reference in edge["reducers"]
                    )
                )
                self.assertFalse(
                    {
                        "/approvals",
                        "/artifacts",
                        "/repositories",
                        "/review_snapshots",
                        "/workspace",
                    }.intersection(edge["allowed_state_writes"])
                )
        self.assertEqual(
            {
                node["executor"]["id"]
                for node in loaded.resolve("full", 3).nodes.values()
            },
            {
                "executor.barrier/v1",
                "executor.codex-exec/v1",
                "executor.codex-thread/v1",
                "executor.deterministic/v1",
                "executor.external-tool/v1",
                "executor.human-gate/v1",
                "executor.native-subagents/v1",
            },
        )

    def test_tool_capabilities_are_identity_covered_and_edge_exact(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        full = loaded.resolve("full", 3)
        lite = loaded.resolve("lite", 3)
        self.assertEqual(
            tuple(
                item["capability_id"]
                for item in full.tool_capabilities
            ),
            ("tool.codebase-memory.read/v1",),
        )
        self.assertEqual(lite.tool_capabilities, ())
        for edge in full.action_edges:
            policy = edge["tool_policy"]
            expected = (
                ()
                if policy is None
                else tuple(policy["capabilities"])
            )
            self.assertEqual(edge["tool_capabilities"], expected)

        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        action = next(
            action
            for node in graph["nodes"]
            for action in node["actions"]
            if action.get("tool_policy") is not None
        )
        action["tool_policy"]["capabilities"] = [
            "tool.undeclared.read/v1"
        ]
        self._write_json(graph_path, graph)
        self._refresh_static_test_digests(root)
        self._assert_load_error(
            "WORKFLOW_ACTION_TOOL_POLICY_INVALID", root
        )

    def test_node_contract_validation_fails_closed_with_stable_codes(
        self,
    ) -> None:
        graph_cases = (
            (
                lambda graph: graph["nodes"][0].pop("contract_version"),
                "WORKFLOW_REQUIRED_FIELD",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"kind": "unknown-node-kind"}
                ),
                "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"contract_version": "v2"}
                ),
                "WORKFLOW_NODE_CONTRACT_UNSUPPORTED",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"input_schema": "dev-flow-unknown-input/v1"}
                ),
                "WORKFLOW_SCHEMA_UNKNOWN",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"input_schema": "dev-flow-node-result/v1"}
                ),
                "WORKFLOW_SCHEMA_ROLE_MISMATCH",
            ),
            (
                lambda graph: graph["nodes"][0]["effect_policy"].update(
                    {"classification": "arbitrary"}
                ),
                "WORKFLOW_NODE_EFFECT_INVALID",
            ),
            (
                lambda graph: graph["nodes"][0]["effect_policy"].update(
                    {"effects": ["arbitrary-effect"]}
                ),
                "WORKFLOW_NODE_EFFECT_INVALID",
            ),
            (
                lambda graph: graph["nodes"][0]["retry_policy"].update(
                    {"mode": "forever"}
                ),
                "WORKFLOW_NODE_RETRY_INVALID",
            ),
            (
                lambda graph: graph["nodes"][0]["recovery_policy"].update(
                    {"mode": "blind-replay"}
                ),
                "WORKFLOW_NODE_RECOVERY_INVALID",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"allowed_state_writes": ["/approvals/review"]}
                ),
                "WORKFLOW_PROTECTED_STATE_WRITE",
            ),
            (
                lambda graph: graph["edge_policies"][0].update(
                    {"allowed_state_writes": ["/status", "/workspace/owner"]}
                ),
                "WORKFLOW_PROTECTED_STATE_WRITE",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"module_path": "package.behavior"}
                ),
                "WORKFLOW_EXECUTABLE_CONTENT_FORBIDDEN",
            ),
            (
                lambda graph: graph["nodes"][0].update(
                    {"shell": "git status"}
                ),
                "WORKFLOW_EXECUTABLE_CONTENT_FORBIDDEN",
            ),
        )
        for mutation, code in graph_cases:
            with self.subTest(code=code):
                root = self._copy_workflows()
                graph_path = (
                    root / "bundles" / "full-v3" / "workflow.json"
                )
                graph = self._read_json(graph_path)
                mutation(graph)
                self._write_json(graph_path, graph)
                self._assert_load_error(code, root)

        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        graph["schemas"]["documents"][1]["path"] = "../node-input.json"
        self._write_json(graph_path, graph)
        self._assert_load_error("WORKFLOW_PATH_INVALID", root)

        schema_cases = (
            (
                lambda schema: schema.update(
                    {"$id": "dev-flow-node-input/v2"}
                ),
                "WORKFLOW_SCHEMA_ID_MISMATCH",
            ),
            (
                lambda schema: schema.update(
                    {"$schema": "http://json-schema.org/draft-07/schema#"}
                ),
                "WORKFLOW_SCHEMA_VERSION_UNSUPPORTED",
            ),
            (
                lambda schema: schema.update(
                    {"additionalProperties": True}
                ),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema["required"].pop(),
                "WORKFLOW_SCHEMA_INVALID",
            ),
        )
        for mutation, code in schema_cases:
            with self.subTest(code=code):
                root = self._copy_workflows()
                schema_path = (
                    root
                    / "bundles"
                    / "full-v3"
                    / "schemas"
                    / "node-input.json"
                )
                schema = self._read_json(schema_path)
                mutation(schema)
                self._write_json(schema_path, schema)
                self._assert_load_error(code, root)

    def test_authoritative_node_result_schema_extensions_fail_closed(
        self,
    ) -> None:
        mutations = (
            (
                lambda schema: schema["properties"][
                    "assignment_id"
                ].update(
                    {"$ref": "https://example.invalid/schema"}
                ),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema["$defs"].pop("stableId"),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema["properties"]["blockers"].update(
                    {"x-canonicalUtf8Order": False}
                ),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema.update(
                    {"x-contentAddressedIdentity": "missing"}
                ),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema["allOf"][0]["oneOf"].pop(),
                "WORKFLOW_SCHEMA_INVALID",
            ),
            (
                lambda schema: schema.update(
                    {"x-unreviewedKeyword": True}
                ),
                "WORKFLOW_UNKNOWN_FIELD",
            ),
        )
        for mutation, code in mutations:
            with self.subTest(code=code):
                root = self._copy_workflows()
                schema_path = (
                    root
                    / "bundles"
                    / "full-v3"
                    / "schemas"
                    / "node-result.json"
                )
                schema = self._read_json(schema_path)
                mutation(schema)
                self._write_json(schema_path, schema)
                self._assert_load_error(code, root)

    def test_generic_node_composes_existing_contracts_without_python_branch(
        self,
    ) -> None:
        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        finalizing_index = next(
            index
            for index, node in enumerate(graph["nodes"])
            if node["id"] == "FINALIZING"
        )
        node = dict(graph["nodes"][finalizing_index])
        node.update(
            {
                "id": "QUALITY_BARRIER",
                "labels": {
                    "en": "Quality barrier",
                    "zh-CN": "质量屏障",
                },
                "phase": "quality-barrier",
                "effect_policy": {
                    "classification": "controller",
                    "effects": ["controller-transition"],
                },
                "executor": {
                    "registry": "executors",
                    "id": "executor.deterministic/v1",
                    "version": "v1",
                },
                "approval_policy": {"mode": "edge-policy", "gate": None},
            }
        )
        graph["nodes"].insert(finalizing_index, node)
        ordered_index = graph["ordered_nodes"].index("FINALIZING")
        graph["ordered_nodes"].insert(ordered_index, "QUALITY_BARRIER")
        existing = next(
            edge
            for edge in graph["edges"]
            if edge["id"] == "full.reviewing.finalizing"
        )
        existing["id"] = "full.reviewing.quality-barrier"
        existing["target"] = "QUALITY_BARRIER"
        graph["edges"].append(
            {
                "id": "full.quality-barrier.finalizing",
                "source": "QUALITY_BARRIER",
                "target": "FINALIZING",
                "policy": "finalizing-forward",
            }
        )
        self._write_json(graph_path, graph)
        self._refresh_static_test_digests(root)

        loaded = self._load(root)

        added = loaded.resolve("full", 3).node("QUALITY_BARRIER")
        self.assertEqual(added["kind"], "generic")
        self.assertEqual(added["contract_version"], "v1")
        self.assertEqual(added["allowed_state_writes"], ())
        self.assertNotIn(
            "QUALITY_BARRIER",
            (
                ROOT
                / "scripts"
                / "dev_flow_parts"
                / "workflow_catalog.py"
            ).read_text(encoding="utf-8"),
        )

    def test_frozen_legacy_graphs_match_every_golden_edge_and_invalidation(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        loaded = self._load(root)
        fields = (
            "id",
            "flow",
            "kind",
            "from",
            "to",
            "trigger",
            "invalidation",
            "v1",
            "v2",
        )
        pointer_by_golden_name = {
            "baseline-fetch-approval": "/approvals/baseline-fetch",
            "impact-generation": "/impact_generation",
            "lite-approval": "/approvals/lite",
            "plan-approval": "/approvals/plan",
            "planning-generation": "/planning_generation",
            "repository-workspace-indexes": "/repositories",
            "repository-workspaces": "/repositories",
            "review-approval": "/approvals/review",
            "review-snapshots": "/review_snapshots",
            "route": "/route",
            "route-approval": "/approvals/route",
            "task-workspace-generation": "/workspace",
            "workspace-approval": "/approvals/workspace",
        }
        expected = {}
        for line in LEGACY_EDGES.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            edge = dict(zip(fields, json.loads(line)))
            key = (
                edge["flow"],
                edge["kind"],
                edge["from"],
                edge["to"],
                edge["trigger"],
            )
            expected[key] = {
                pointer_by_golden_name[item]
                for item in edge["invalidation"]
            }

        actual = {}
        kind_name = {
            "block": "blocking",
            "cancel": "cancellation",
        }
        trigger_name = {
            "lite-risk-verifying": "lite-risk:VERIFYING",
            "lite-risk-done": "lite-risk:DONE",
        }
        for workflow_id in ("full-legacy", "lite-legacy"):
            bundle = loaded.resolve(workflow_id, 2)
            for edge in bundle.edges:
                trigger = edge["trigger"]["id"]
                key = (
                    bundle.graph["flow"],
                    kind_name.get(edge["class"], edge["class"]),
                    edge["source"],
                    edge["target"],
                    trigger_name.get(trigger, trigger),
                )
                self.assertNotIn(key, actual)
                actual[key] = set(edge["kernel_invalidates"])

        self.assertEqual(set(actual), set(expected))
        for key, expected_invalidations in expected.items():
            with self.subTest(edge=key):
                self.assertEqual(actual[key], expected_invalidations)

    def test_rejects_malformed_and_ambiguous_catalog_json(self) -> None:
        cases = (
            (b'{"schema":"a","schema":"b"}', "WORKFLOW_JSON_DUPLICATE_KEY"),
            (b'{"schema":1.0}', "WORKFLOW_JSON_FLOAT_FORBIDDEN"),
            (b'{"schema":NaN}', "WORKFLOW_JSON_NONFINITE_FORBIDDEN"),
            (
                b'{"schema":9223372036854775808}',
                "WORKFLOW_JSON_INTEGER_OUT_OF_RANGE",
            ),
            (
                b'{"schema":' + (b"9" * 5000) + b"}",
                "WORKFLOW_JSON_INTEGER_OUT_OF_RANGE",
            ),
            (
                '{"schema":"e\u0301"}'.encode("utf-8"),
                "WORKFLOW_JSON_NOT_NFC",
            ),
            (
                b'{"schema":"\\ud800"}',
                "WORKFLOW_JSON_UNICODE_INVALID",
            ),
            (b"\xef\xbb\xbf{}", "WORKFLOW_JSON_BOM_FORBIDDEN"),
            (b'{"schema":"\xff"}', "WORKFLOW_JSON_UTF8_INVALID"),
            (b'{"schema":', "WORKFLOW_JSON_MALFORMED"),
        )
        for payload, code in cases:
            with self.subTest(code=code):
                root = self._copy_workflows()
                (root / "catalog.json").write_bytes(payload)
                self._assert_load_error(code, root)

    def test_activation_inventory_is_exact_and_active_requires_suites(self) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        activation_path = root / "activation.json"
        activation = self._read_json(activation_path)
        activation["profiles"] = [
            item
            for item in activation["profiles"]
            if not (
                item["workflow_id"] == "full"
                and item["workflow_version"] == 3
                and item["execution_profile"] == "single-repository"
            )
        ]
        self._write_json(activation_path, activation)
        self._assert_load_error("WORKFLOW_ACTIVATION_INCOMPLETE", root)

        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        activation_path = root / "activation.json"
        activation = self._read_json(activation_path)
        activation["profiles"][0]["active"] = True
        activation["profiles"][0]["required_suites"] = []
        self._write_json(activation_path, activation)
        self._assert_load_error("WORKFLOW_ACTIVATION_INCOMPLETE", root)

    def test_rejects_unknown_fields_and_duplicate_graph_ids(self) -> None:
        for mutation, code in (
            (
                lambda graph: graph["nodes"][0].update({"unexpected": True}),
                "WORKFLOW_UNKNOWN_FIELD",
            ),
            (
                lambda graph: graph["nodes"].append(dict(graph["nodes"][0])),
                "WORKFLOW_DUPLICATE_ID",
            ),
            (
                lambda graph: graph["contracts"][0].update(
                    {"version": "v2"}
                ),
                "WORKFLOW_INVALID_CONTRACT",
            ),
            (
                lambda graph: graph["nodes"][0]["playbook"].update(
                    {"anchor": "missing-anchor"}
                ),
                "WORKFLOW_PLAYBOOK_ANCHOR_INVALID",
            ),
        ):
            with self.subTest(code=code):
                root = self._copy_workflows()
                graph_path = root / "bundles" / "full-v3" / "workflow.json"
                graph = self._read_json(graph_path)
                mutation(graph)
                self._write_json(graph_path, graph)
                self._assert_load_error(code, root)

        root = self._copy_workflows()
        schema_path = (
            root
            / "bundles"
            / "full-v3"
            / "schemas"
            / "contracts.json"
        )
        schema = self._read_json(schema_path)
        schema["unexpected"] = True
        self._write_json(schema_path, schema)
        self._assert_load_error("WORKFLOW_UNKNOWN_FIELD", root)

    def test_rejects_unknown_executable_contract_after_registry_sealing(self) -> None:
        missing = ("guards", "guard.preflight-current/v1", "v1")
        delegate = self.resolver

        class MissingResolver:
            sealed = True

            def resolve(
                self, registry: str, identifier: str, version: str
            ) -> object:
                if (registry, identifier, version) == missing:
                    raise KeyError(missing)
                return delegate.resolve(registry, identifier, version)

            def identity_handlers(self, references: object) -> object:
                return delegate.identity_handlers(references)

        self._assert_load_error(
            "WORKFLOW_CONTRACT_UNKNOWN",
            WORKFLOWS,
            resolver=MissingResolver(),
        )

    def test_rejects_duplicate_catalog_identity_and_portable_path_collision(
        self,
    ) -> None:
        root = self._copy_workflows()
        catalog_path = root / "catalog.json"
        document = self._read_json(catalog_path)
        document["bundles"].append(dict(document["bundles"][0]))
        self._write_json(catalog_path, document)
        self._assert_load_error("WORKFLOW_DUPLICATE_IDENTITY", root)

        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        catalog_path = root / "catalog.json"
        document = self._read_json(catalog_path)
        document["bundles"][0]["files"].append(
            {"path": "Workflow.json", "kind": "J"}
        )
        self._write_json(catalog_path, document)
        self._assert_load_error("WORKFLOW_PATH_COLLISION", root)

    def test_rejects_path_traversal_symlink_escape_and_unlisted_files(self) -> None:
        root = self._copy_workflows()
        catalog_path = root / "catalog.json"
        document = self._read_json(catalog_path)
        document["bundles"][0]["graph"] = "../workflow.json"
        self._write_json(catalog_path, document)
        self._assert_load_error("WORKFLOW_PATH_INVALID", root)

        root = self._copy_workflows()
        bundle_root = root / "bundles" / "full-v3"
        escape = bundle_root / "escape.json"
        try:
            os.symlink(root / "activation.json", escape)
        except (OSError, NotImplementedError):
            pass
        else:
            catalog_path = root / "catalog.json"
            document = self._read_json(catalog_path)
            document["bundles"][0]["files"].append(
                {"path": "escape.json", "kind": "J"}
            )
            self._write_json(catalog_path, document)
            self._assert_load_error("WORKFLOW_SYMLINK_FORBIDDEN", root)

        root = self._copy_workflows()
        (root / "bundles" / "full-v3" / "unlisted.txt").write_text(
            "not in the static inventory\n",
            encoding="utf-8",
        )
        self._assert_load_error("WORKFLOW_INVENTORY_MISMATCH", root)

        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        shutil.copytree(
            root / "bundles" / "lite-v3",
            root / "bundles" / "unlisted-v1",
        )
        self._assert_load_error(
            "WORKFLOW_STATIC_INVENTORY_INVALID",
            root,
        )

    def test_rejects_implicit_cycle_unreachable_node_and_terminal_automatic(
        self,
    ) -> None:
        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        graph["edges"].append(
            {
                "id": "full.finalizing.intake",
                "source": "FINALIZING",
                "target": "INTAKE",
                "policy": "done-forward",
            }
        )
        self._write_json(graph_path, graph)
        self._assert_load_error("WORKFLOW_IMPLICIT_CYCLE", root)

        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        orphan = dict(graph["nodes"][0])
        orphan["id"] = "ORPHAN"
        orphan["labels"] = {"en": "Orphan", "zh-CN": "孤立"}
        orphan["actions"] = []
        graph["nodes"].append(orphan)
        graph["ordered_nodes"].append("ORPHAN")
        self._write_json(graph_path, graph)
        self._assert_load_error("WORKFLOW_NODE_UNREACHABLE", root)

        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read_json(graph_path)
        policy = next(
            item
            for item in graph["edge_policies"]
            if item["id"] == "done-forward"
        )
        policy["automatic"] = True
        policy["confirmation"] = "automatic"
        self._write_json(graph_path, graph)
        self._assert_load_error("WORKFLOW_TERMINAL_AUTOMATIC", root)

    def test_detects_identity_covered_playbook_tampering(self) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        playbook = root / "bundles" / "lite-v3" / "playbooks" / "workflow.md"
        playbook.write_text(
            playbook.read_text(encoding="utf-8") + "\nTampered.\n",
            encoding="utf-8",
        )
        self._assert_load_error("WORKFLOW_DIGEST_MISMATCH", root)

    def test_expected_identity_helper_is_read_only_and_ignores_stored_digests(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        catalog_path = root / "catalog.json"
        activation_path = root / "activation.json"
        document = self._read_json(catalog_path)
        for entry in document["bundles"]:
            entry["graph_sha256"] = "f" * 64
            entry["bundle_sha256"] = "f" * 64
        self._write_json(catalog_path, document)
        activation = self._read_json(activation_path)
        for profile in activation["profiles"]:
            profile["bundle_sha256"] = "f" * 64
        self._write_json(activation_path, activation)
        before = {
            path: path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

        expected = catalog.expected_workflow_catalog_identities(
            root,
            contract_resolver=self.resolver,
            identity_api=identity,
        )

        self.assertEqual(len(expected), 4)
        self.assertEqual(
            {
                (item["workflow_id"], item["workflow_version"])
                for item in expected
            },
            {
                ("full", 3),
                ("lite", 3),
                ("full-legacy", 2),
                ("lite-legacy", 2),
            },
        )
        self.assertTrue(
            all(item["graph_sha256"] != "f" * 64 for item in expected)
        )
        self.assertTrue(
            all(item["bundle_sha256"] != "f" * 64 for item in expected)
        )
        self.assertEqual(
            before,
            {
                path: path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            },
        )
        self._assert_load_error("WORKFLOW_DIGEST_MISMATCH", root)

        document["bundles"][0]["graph"] = "../workflow.json"
        self._write_json(catalog_path, document)
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            catalog.expected_workflow_catalog_identities(
                root,
                contract_resolver=self.resolver,
                identity_api=identity,
            )
        self.assertEqual(raised.exception.code, "WORKFLOW_PATH_INVALID")

    def test_shared_namespace_fragments_cannot_clobber_catalog_internals(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh_static_test_digests(root)
        module_name = "dev_flow_catalog_shared_namespace_test"
        module = types.ModuleType(module_name)
        module.__file__ = str(ROOT / "scripts" / "dev_flow.py")
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        sources = (
            ROOT / "scripts" / "workflow_bundle_identity.py",
            *(
                ROOT / "scripts" / "dev_flow_parts" / name
                for name in (
                    "workflow_registry.py",
                    "workflow_handlers.py",
                    "workflow_builtin_handlers.py",
                    "workflow_v3_handlers.py",
                    "workflow_catalog.py",
                    "workflow_state.py",
                    "transition_engine.py",
                    "agent_protocol.py",
                    "node_telemetry.py",
                    "repository_plan.py",
                    "core.py",
                    "mutation.py",
                    "scope.py",
                    "process.py",
                    "git.py",
                    "commands.py",
                    "baseline.py",
                    "workspace.py",
                    "review.py",
                    "cli.py",
                    "workflow_runtime.py",
                )
            ),
        )
        for path in sources:
            exec(
                compile(path.read_bytes(), str(path), "exec"),
                module.__dict__,
                module.__dict__,
            )

        # These were historically generic fragment-private names. A later
        # fragment may own them without changing catalog behavior.
        exec(
            "\n".join(
                (
                    "_CONTRACT_ID_RE = object()",
                    "_SHA256_RE = object()",
                    "_reject_float = lambda literal: literal",
                    "_reject_constant = lambda literal: literal",
                    "_parse_integer = lambda literal: literal",
                    "_freeze = lambda value: value",
                )
            ),
            module.__dict__,
            module.__dict__,
        )
        resolver = module.StaticContractResolver(self.references)
        loaded = module.load_workflow_catalog(
            root,
            contract_resolver=resolver,
            identity_api=module,
        )
        self.assertEqual(
            tuple(loaded.bundles),
            (
                ("full", 3),
                ("lite", 3),
                ("full-legacy", 2),
                ("lite-legacy", 2),
            ),
        )


if __name__ == "__main__":
    unittest.main()
