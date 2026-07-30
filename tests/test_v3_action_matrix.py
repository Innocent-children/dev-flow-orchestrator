from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

if __package__:
    from . import test_workflow_catalog as support
else:
    import test_workflow_catalog as support


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
PLACEMENT = (
    ROOT / "tests" / "fixtures" / "workflow_v3" / "action_placement.json"
)
catalog = support.catalog
identity = support.identity


class V3ActionMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        references = set()
        for graph_path in sorted(
            (WORKFLOWS / "bundles").glob("*/workflow.json")
        ):
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            references.update(
                (item["registry"], item["id"], item["version"])
                for item in graph["contracts"]
            )
        cls.resolver = catalog.StaticContractResolver(references)

    def _copy_workflows(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        target = Path(temporary.name) / "workflows"
        shutil.copytree(WORKFLOWS, target)
        return target

    @staticmethod
    def _read(path: Path) -> dict[str, object]:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(value, dict)
        return value

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _refresh(self, root: Path) -> None:
        catalog_path = root / "catalog.json"
        document = self._read(catalog_path)
        digests: dict[tuple[str, int], str] = {}
        for entry_value in document["bundles"]:
            assert isinstance(entry_value, dict)
            entry = entry_value
            bundle_root = root / str(entry["root"])
            graph_source = (bundle_root / str(entry["graph"])).read_bytes()
            files = tuple(
                identity.BundleFile(
                    str(item["path"]),
                    str(item["kind"]),
                    (bundle_root / str(item["path"])).read_bytes(),
                )
                for item in entry["files"]
            )
            result = identity.compute_workflow_bundle_identity(
                graph_source, files, ()
            )
            entry["graph_sha256"] = result.graph_sha256
            entry["bundle_sha256"] = result.bundle_sha256
            digests[
                (str(entry["workflow_id"]), int(entry["workflow_version"]))
            ] = result.bundle_sha256
        self._write(catalog_path, document)
        activation_path = root / "activation.json"
        activation = self._read(activation_path)
        for profile_value in activation["profiles"]:
            assert isinstance(profile_value, dict)
            profile = profile_value
            profile["bundle_sha256"] = digests[
                (
                    str(profile["workflow_id"]),
                    int(profile["workflow_version"]),
                )
            ]
        self._write(activation_path, activation)

    def _load(self, root: Path) -> catalog.WorkflowCatalog:
        return catalog.load_workflow_catalog(
            root,
            contract_resolver=self.resolver,
            identity_api=identity,
        )

    def _assert_error(
        self, code: str, root: Path
    ) -> catalog.WorkflowCatalogError:
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._load(root)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def _mutated_graph(
        self, mutation: object, *, flow: str = "full"
    ) -> Path:
        root = self._copy_workflows()
        path = root / "bundles" / f"{flow}-v3" / "workflow.json"
        graph = self._read(path)
        assert callable(mutation)
        mutation(graph)
        self._write(path, graph)
        self._refresh(root)
        return root

    def test_compiled_action_edges_match_exact_placement_fixture(self) -> None:
        root = self._copy_workflows()
        self._refresh(root)
        loaded = self._load(root)
        fixture = self._read(PLACEMENT)
        self.assertEqual(
            fixture["schema"], "dev-flow-v3-action-placement/v1"
        )
        expected_counts = {"full": 53, "lite": 15}
        total_counts = {"full": 404, "lite": 15}
        for flow, expected_nodes_value in fixture["flows"].items():
            expected_nodes = expected_nodes_value
            bundle = loaded.resolve(str(flow), 3)
            self.assertIs(bundle.movement_edges, bundle.edges)
            self.assertEqual(len(bundle.action_edges), total_counts[flow])
            fixture_edges = tuple(
                edge
                for edge in bundle.action_edges
                if edge["public_command"]["id"] != "orchestration"
            )
            self.assertEqual(len(fixture_edges), expected_counts[flow])
            observed: dict[str, list[list[object]]] = {}
            for node_id in bundle.nodes:
                observed[node_id] = sorted(
                    [
                        [
                            edge["trigger"]["id"],
                            edge["id"],
                            edge["public_command"]["id"],
                            edge["public_command"]["selector"],
                            list(edge["public_command"]["values"]),
                            list(edge["allowed_artifact_kinds"]),
                        ]
                        for edge in bundle.legal_action_edges(node_id)
                        if edge["public_command"]["id"]
                        != "orchestration"
                    ],
                    key=lambda item: str(item[0]).encode("utf-8"),
                )
            canonical_expected = {
                node_id: sorted(
                    actions,
                    key=lambda item: str(item[0]).encode("utf-8"),
                )
                for node_id, actions in expected_nodes.items()
            }
            self.assertEqual(observed, canonical_expected)
            for edge in bundle.action_edges:
                self.assertEqual(edge["source"], edge["target"])
                self.assertEqual(edge["class"], "action")
                self.assertFalse(edge["automatic"])
                self.assertNotIn(edge, bundle.movement_edges)
                with self.assertRaises(TypeError):
                    edge["canonical_event"] = "forged"
            for node_id in bundle.nodes:
                self.assertEqual(
                    {
                        str(edge["id"])
                        for edge in bundle.legal_edges(node_id)
                    },
                    {
                        *(
                            str(edge["id"])
                            for edge in bundle.legal_movement_edges(node_id)
                        ),
                        *(
                            str(edge["id"])
                            for edge in bundle.legal_action_edges(node_id)
                        ),
                    },
                )

    def test_wrong_node_repeat_and_artifact_kind_fail_at_policy_lookup(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh(root)
        loaded = self._load(root)
        fixture = self._read(PLACEMENT)
        for (
            flow,
            source,
            command,
            selector,
            expected_code,
        ) in fixture["rejections"]:
            with self.subTest(
                flow=flow,
                source=source,
                command=command,
                selector=selector,
            ):
                bundle = loaded.resolve(flow, 3)
                with self.assertRaises(
                    catalog.WorkflowCatalogError
                ) as raised:
                    bundle.resolve_public_action(
                        source, command, selector=selector
                    )
                self.assertEqual(raised.exception.code, expected_code)
        full = loaded.resolve("full", 3)
        impact = full.resolve_public_action(
            "INDEXED", "record-artifact", selector="impact"
        )
        self.assertEqual(
            impact["id"], "full.action.indexed.record-impact.v1"
        )
        self.assertEqual(impact["allowed_artifact_kinds"], ("impact",))

    def test_shared_action_templates_are_exact_placed_and_identity_covered(
        self,
    ) -> None:
        root = self._copy_workflows()
        graph_path = root / "bundles" / "full-v3" / "workflow.json"
        graph = self._read(graph_path)
        graph["shared_actions"][0]["action"][
            "canonical_event"
        ] = "manager_capability_authorized_forged"
        self._write(graph_path, graph)
        self._assert_error(
            "WORKFLOW_ORCHESTRATION_ACTION_BINDING_INVALID", root
        )

        unknown_node = self._mutated_graph(
            lambda candidate: candidate["shared_actions"][0][
                "placements"
            ][0].update({"node": "UNKNOWN"})
        )
        self._assert_error(
            "WORKFLOW_REFERENCE_DANGLING", unknown_node
        )

        duplicate_placement = self._mutated_graph(
            lambda candidate: candidate["shared_actions"][0][
                "placements"
            ].append(
                dict(
                    candidate["shared_actions"][0]["placements"][0]
                )
            )
        )
        self._assert_error(
            "WORKFLOW_DUPLICATE_ID", duplicate_placement
        )

    def test_v3_action_policy_is_exact_closed_and_non_overloaded(self) -> None:
        cases = (
            (
                lambda graph: graph["nodes"][0]["actions"][0].pop(
                    "canonical_event"
                ),
                "WORKFLOW_REQUIRED_FIELD",
            ),
            (
                lambda graph: graph["nodes"][0]["actions"][0]["effects"][
                    0
                ].update({"dispatch": "replay-safe"}),
                "WORKFLOW_ACTION_POLICY_INVALID",
            ),
            (
                lambda graph: graph["nodes"][0]["actions"][0].update(
                    {"requires_note": True}
                ),
                "WORKFLOW_ACTION_NOTE_POLICY_MISMATCH",
            ),
            (
                lambda graph: graph["nodes"][3]["actions"][0][
                    "allowed_artifact_kinds"
                ].append("free-form"),
                "WORKFLOW_ACTION_POLICY_INVALID",
            ),
            (
                lambda graph: graph["nodes"][2]["actions"][1][
                    "tool_policy"
                ].update(
                    {
                        "project_identity": (
                            "current-generation-workspace-project"
                        )
                    }
                ),
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            ),
            (
                lambda graph: (
                    graph["nodes"][2]["actions"][1].update(
                        {"effect_classification": "external-write"}
                    )
                ),
                "WORKFLOW_ACTION_TOOL_POLICY_INVALID",
            ),
            (
                lambda graph: (
                    graph["nodes"][0]["actions"][0].update(
                        {"id": "unversioned-action"}
                    ),
                    graph["nodes"][0]["actions"][0]["trigger"].update(
                        {"id": "unversioned-action"}
                    ),
                ),
                "WORKFLOW_ACTION_POLICY_INVALID",
            ),
        )
        for mutation, code in cases:
            with self.subTest(code=code):
                self._assert_error(code, self._mutated_graph(mutation))

        def overload(graph: dict[str, object]) -> None:
            nodes = graph["nodes"]
            implementing = next(
                node for node in nodes if node["id"] == "IMPLEMENTING"
            )
            verifying = next(
                node for node in nodes if node["id"] == "VERIFYING"
            )
            source = implementing["actions"][0]["id"]
            verifying["actions"][0]["id"] = source
            verifying["actions"][0]["trigger"]["id"] = source

        self._assert_error(
            "WORKFLOW_ACTION_SEMANTIC_OVERLOAD",
            self._mutated_graph(overload),
        )

        def duplicate_public_selection(graph: dict[str, object]) -> None:
            action = json.loads(
                json.dumps(graph["nodes"][0]["actions"][0])
            )
            action["id"] = "full.intake.preflight-duplicate.v1"
            action["edge_id"] = (
                "full.action.intake.preflight-duplicate.v1"
            )
            action["trigger"]["id"] = action["id"]
            graph["nodes"][0]["actions"].append(action)

        self._assert_error(
            "WORKFLOW_ACTION_SELECTION_AMBIGUOUS",
            self._mutated_graph(duplicate_public_selection),
        )

    def test_note_resume_and_activation_action_closure_fail_closed(
        self,
    ) -> None:
        self._assert_error(
            "WORKFLOW_ACTION_NOTE_POLICY_MISMATCH",
            self._mutated_graph(
                lambda graph: next(
                    policy
                    for policy in graph["edge_policies"]
                    if policy["id"] == "manual-block"
                ).update({"requires_note": False})
            ),
        )

        def remove_lite_safety(graph: dict[str, object]) -> None:
            resume = next(
                policy
                for policy in graph["edge_policies"]
                if policy["id"] == "resume"
            )
            resume["guards"] = [
                guard
                for guard in resume["guards"]
                if guard["id"] != "guard.lite-risk-safe/v1"
            ]

        self._assert_error(
            "WORKFLOW_ACTION_RESUME_POLICY_INVALID",
            self._mutated_graph(remove_lite_safety, flow="lite"),
        )

        root = self._copy_workflows()
        self._refresh(root)
        activation_path = root / "activation.json"
        activation = self._read(activation_path)
        profile = activation["profiles"][0]
        profile["active"] = True
        profile["required_suites"].remove("action-policy")
        self._write(activation_path, activation)
        self._assert_error("WORKFLOW_ACTIVATION_INCOMPLETE", root)

    def test_legacy_five_field_actions_remain_accepted_without_compilation(
        self,
    ) -> None:
        root = self._copy_workflows()
        path = (
            root / "bundles" / "full-legacy-v2" / "workflow.json"
        )
        graph = self._read(path)
        graph["nodes"][0]["actions"] = [
            {
                "id": "legacy-repeat",
                "handler": {
                    "registry": "executors",
                    "id": "executor.deterministic/v1",
                    "version": "v1",
                },
                "guards": [],
                "reducers": [
                    {
                        "registry": "reducers",
                        "id": "reducer.action-outcome/v1",
                        "version": "v1",
                    }
                ],
                "gate": None,
            }
        ]
        self._write(path, graph)
        self._refresh(root)
        loaded = self._load(root)
        legacy = loaded.resolve("full-legacy", 2)
        self.assertEqual(
            set(legacy.nodes["INTAKE"]["actions"][0]),
            {"gate", "guards", "handler", "id", "reducers"},
        )
        self.assertEqual(legacy.action_edges, ())


if __name__ == "__main__":
    unittest.main()
