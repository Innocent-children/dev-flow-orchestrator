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
catalog = support.catalog
identity = support.identity

AUTHORITATIVE_OPERATIONS = (
    "manager.capability.authorize/v1",
    "manager.capability.revoke/v1",
    "orchestration.artifact.record/v1",
    "orchestration.assignment.issue/v1",
    "orchestration.attempt.abandon/v1",
    "orchestration.barrier.close/v1",
    "orchestration.barrier.reopen/v1",
    "orchestration.cancellation.request/v1",
    "orchestration.dispatch.handoff/v1",
    "orchestration.finalization.commit/v1",
    "orchestration.frontier.advance/v1",
    "orchestration.integration.capture/v1",
    "orchestration.integration.verify/v1",
    "orchestration.lease.expire/v1",
    "orchestration.lease.issue/v1",
    "orchestration.lease.revoke/v1",
    "orchestration.map.expand/v1",
    "orchestration.map.invalidate/v1",
    "orchestration.plan.approve/v1",
    "orchestration.plan.record/v1",
    "orchestration.reconciliation.begin/v1",
    "orchestration.reconciliation.complete/v1",
    "orchestration.result.accept/v1",
    "orchestration.result.invalidate/v1",
    "orchestration.retry.request/v1",
    "orchestration.review.record/v1",
    "orchestration.runtime-stop.record/v1",
    "orchestration.runtime.recovery.observe/v1",
    "orchestration.timeout.record/v1",
)
LEGACY_ALIASES = {
    "orchestration.barrier.evaluate/v1": (
        "orchestration.barrier.close/v1",
    ),
    "orchestration.plan.expand/v1": (
        "orchestration.map.expand/v1",
    ),
    "orchestration.runtime.recover/v1": (
        "orchestration.attempt.abandon/v1",
        "orchestration.runtime.recovery.observe/v1",
    ),
    "orchestration.worker.assign/v1": (
        "orchestration.assignment.issue/v1",
        "orchestration.dispatch.handoff/v1",
        "orchestration.frontier.advance/v1",
        "orchestration.lease.issue/v1",
    ),
    "worker-result.submit/v1": (
        "orchestration.result.accept/v1",
    ),
}
LIVE_NODES = frozenset(
    {
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
        "BLOCKED",
    }
)


class OrchestrationActionCatalogTests(unittest.TestCase):
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
            profile_value["bundle_sha256"] = digests[
                (
                    str(profile_value["workflow_id"]),
                    int(profile_value["workflow_version"]),
                )
            ]
        self._write(activation_path, activation)

    def _load(self, root: Path) -> object:
        return catalog.load_workflow_catalog(
            root,
            contract_resolver=self.resolver,
            identity_api=identity,
        )

    def _mutated_graph(self, mutation: object) -> Path:
        root = self._copy_workflows()
        path = root / "bundles/full-v3/workflow.json"
        graph = self._read(path)
        assert callable(mutation)
        mutation(graph)
        self._write(path, graph)
        self._refresh(root)
        return root

    def _assert_error(self, code: str, root: Path) -> None:
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._load(root)
        self.assertEqual(raised.exception.code, code)

    @staticmethod
    def _matrix_item(
        graph: dict[str, object], operation_id: str
    ) -> dict[str, object]:
        metadata = graph["repository_orchestration"]
        assert isinstance(metadata, dict)
        return next(
            item
            for item in metadata["operation_matrix"]
            if item["operation_id"] == operation_id
        )

    @staticmethod
    def _shared_action(
        graph: dict[str, object], action_id: str
    ) -> dict[str, object]:
        return next(
            item
            for item in graph["shared_actions"]
            if item["action"]["id"] == action_id
        )

    def test_exhaustive_matrix_compiles_one_semantic_action_per_live_node(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh(root)
        loaded = self._load(root)
        full = loaded.resolve("full", 3)
        metadata = full.repository_orchestration
        self.assertEqual(
            tuple(metadata["operation_ids"]), AUTHORITATIVE_OPERATIONS
        )
        self.assertEqual(
            {
                item["alias_id"]: tuple(item["operation_ids"])
                for item in metadata["legacy_aliases"]
            },
            LEGACY_ALIASES,
        )
        self.assertTrue(
            all(
                profile["active"] is False
                for profile in loaded.activations
            )
        )

        semantic_ids: set[str] = set()
        for item in metadata["operation_matrix"]:
            operation_id = str(item["operation_id"])
            action_id = str(item["action_id"])
            role_ids = (
                action_id,
                str(item["validator_id"]),
                str(item["event_id"]),
                str(item["write_set_id"]),
                *(str(value) for value in item["effect_ids"]),
            )
            self.assertTrue(all(value.endswith(".v1") for value in role_ids))
            self.assertFalse(semantic_ids.intersection(role_ids))
            semantic_ids.update(role_ids)
            edges = tuple(
                edge
                for edge in full.action_edges
                if edge["trigger"]["id"] == action_id
            )
            self.assertEqual(len(edges), len(LIVE_NODES))
            self.assertEqual(
                {str(edge["source"]) for edge in edges}, LIVE_NODES
            )
            self.assertTrue(
                all(edge["source"] == edge["target"] for edge in edges)
            )
            self.assertTrue(
                all(
                    tuple(effect["id"] for effect in edge["effects"])
                    == tuple(item["effect_ids"])
                    for edge in edges
                )
            )
            self.assertTrue(
                all(
                    "orchestration-action-matrix"
                    in edge["required_suites"]
                    for edge in edges
                )
            )
            if not operation_id.startswith("manager."):
                self.assertTrue(
                    all(
                        edge["public_command"]
                        == {
                            "id": "orchestration",
                            "selector": "operation",
                            "values": (operation_id,),
                        }
                        for edge in edges
                    )
                )

        lite = loaded.resolve("lite", 3)
        self.assertIsNone(lite.repository_orchestration)
        self.assertFalse(
            any(
                edge["public_command"]["id"] == "orchestration"
                for edge in lite.action_edges
            )
        )

    def test_overloaded_frontier_assignment_and_recovery_abandon_split(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh(root)
        full = self._load(root).resolve("full", 3)
        matrix = {
            item["operation_id"]: item
            for item in full.repository_orchestration["operation_matrix"]
        }
        split_pairs = (
            (
                "orchestration.frontier.advance/v1",
                "orchestration.assignment.issue/v1",
            ),
            (
                "orchestration.runtime.recovery.observe/v1",
                "orchestration.attempt.abandon/v1",
            ),
            (
                "orchestration.assignment.issue/v1",
                "orchestration.lease.issue/v1",
            ),
            (
                "orchestration.lease.issue/v1",
                "orchestration.dispatch.handoff/v1",
            ),
            (
                "orchestration.barrier.close/v1",
                "orchestration.barrier.reopen/v1",
            ),
            (
                "orchestration.finalization.commit/v1",
                "orchestration.result.accept/v1",
            ),
        )
        for left, right in split_pairs:
            with self.subTest(left=left, right=right):
                for field in (
                    "action_id",
                    "validator_id",
                    "event_id",
                    "write_set_id",
                    "effect_ids",
                ):
                    self.assertNotEqual(
                        matrix[left][field], matrix[right][field]
                    )

    def test_controller_artifact_writes_are_claimed_single_dispatch_effects(
        self,
    ) -> None:
        root = self._copy_workflows()
        self._refresh(root)
        full = self._load(root).resolve("full", 3)
        expected = {
            "orchestration.artifact.record/v1",
            "orchestration.attempt.abandon/v1",
            "orchestration.integration.capture/v1",
            "orchestration.plan.record/v1",
            "orchestration.result.accept/v1",
        }
        observed: set[str] = set()
        for operation_id in expected:
            matrix = next(
                item
                for item in full.repository_orchestration[
                    "operation_matrix"
                ]
                if item["operation_id"] == operation_id
            )
            edges = tuple(
                edge
                for edge in full.action_edges
                if edge["trigger"]["id"] == matrix["action_id"]
            )
            self.assertEqual(len(edges), len(LIVE_NODES))
            for edge in edges:
                self.assertEqual(len(edge["effects"]), 1)
                effect = edge["effects"][0]
                self.assertEqual(
                    effect["dispatch"], "single-dispatch"
                )
                self.assertEqual(
                    effect["idempotency"], "execution-effect-key/v1"
                )
                self.assertEqual(
                    effect["recovery"]["mode"],
                    "observe-or-quarantine/v1",
                )
                self.assertEqual(
                    effect["recovery"]["redispatch"], "forbidden"
                )
            observed.add(operation_id)
        self.assertEqual(observed, expected)

    def test_matrix_rejects_missing_overloaded_or_legacy_authority(
        self,
    ) -> None:
        def overload_action(graph: dict[str, object]) -> None:
            frontier = self._matrix_item(
                graph, "orchestration.frontier.advance/v1"
            )
            assignment = self._matrix_item(
                graph, "orchestration.assignment.issue/v1"
            )
            frontier["action_id"] = assignment["action_id"]

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_SEMANTIC_OVERLOAD",
            self._mutated_graph(overload_action),
        )

        def incomplete_alias(graph: dict[str, object]) -> None:
            metadata = graph["repository_orchestration"]
            alias = next(
                item
                for item in metadata["legacy_aliases"]
                if item["alias_id"]
                == "orchestration.runtime.recover/v1"
            )
            alias["operation_ids"].remove(
                "orchestration.attempt.abandon/v1"
            )

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_LEGACY_ALIAS_INVALID",
            self._mutated_graph(incomplete_alias),
        )

        def legacy_authoritative_edge(
            graph: dict[str, object]
        ) -> None:
            matrix = self._matrix_item(
                graph, "orchestration.barrier.close/v1"
            )
            family = self._shared_action(
                graph, str(matrix["action_id"])
            )
            family["action"]["public_command"]["values"] = [
                "orchestration.barrier.evaluate/v1"
            ]

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_ACTION_BINDING_INVALID",
            self._mutated_graph(legacy_authoritative_edge),
        )

    def test_matrix_rejects_missing_placement_or_role_binding(self) -> None:
        def missing_placement(graph: dict[str, object]) -> None:
            matrix = self._matrix_item(
                graph, "orchestration.lease.issue/v1"
            )
            family = self._shared_action(
                graph, str(matrix["action_id"])
            )
            family["placements"].pop()

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_ACTION_PLACEMENT_INVALID",
            self._mutated_graph(missing_placement),
        )

        def wrong_write_set(graph: dict[str, object]) -> None:
            matrix = self._matrix_item(
                graph, "orchestration.assignment.issue/v1"
            )
            family = self._shared_action(
                graph, str(matrix["action_id"])
            )
            family["action"]["kernel_state_writes"] = [
                "/orchestration/frontier",
                "/orchestration/manager_capabilities",
            ]

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_ACTION_BINDING_INVALID",
            self._mutated_graph(wrong_write_set),
        )

        def wrong_effect_identity(graph: dict[str, object]) -> None:
            matrix = self._matrix_item(
                graph, "orchestration.runtime.recovery.observe/v1"
            )
            family = self._shared_action(
                graph, str(matrix["action_id"])
            )
            family["action"]["effects"][0]["id"] = (
                "orchestration.attempt.abandon.effect.v1"
            )

        self._assert_error(
            "WORKFLOW_ORCHESTRATION_ACTION_BINDING_INVALID",
            self._mutated_graph(wrong_effect_identity),
        )


if __name__ == "__main__":
    unittest.main()
