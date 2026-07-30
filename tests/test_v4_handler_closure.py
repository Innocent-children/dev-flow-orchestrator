from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"


def _source_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


catalog = _source_module(
    "dev_flow_v4_handler_closure_test_catalog",
    ROOT / "scripts" / "dev_flow_parts" / "workflow_catalog.py",
)

ROLES = (
    "abandoned",
    "accepted",
    "archive",
    "compensation",
    "containment",
    "control",
    "dispatch",
    "observation",
    "reattachment",
    "settlement",
    "unblock",
    "unresolved",
)


def _handler(role: str) -> dict[str, str]:
    return {
        "registry": "executors",
        "id": f"executor.v4-{role}/v2",
        "version": "v2",
    }


def _closure() -> list[dict[str, object]]:
    return [{"role": role, "handler": _handler(role)} for role in ROLES]


def _reference(value: dict[str, str]) -> object:
    return catalog.ContractReference(
        value["registry"], value["id"], value["version"]
    )


class V4HandlerClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle_root = WORKFLOWS / "bundles" / "full-v3"
        cls.graph = json.loads(
            (cls.bundle_root / "workflow.json").read_text(encoding="utf-8")
        )
        catalog_document = json.loads(
            (WORKFLOWS / "catalog.json").read_text(encoding="utf-8")
        )
        cls.entry = next(
            item
            for item in catalog_document["bundles"]
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
        )
        cls.inventory = {
            cls.entry["graph"]: "J",
            **{
                item["path"]: item["kind"]
                for item in cls.entry["files"]
            },
        }
        cls.base_references = frozenset(
            _reference(item) for item in cls.graph["contracts"]
        )
        cls.closure_references = frozenset(
            _reference(item["handler"]) for item in _closure()
        )
        cls.declared_references = (
            cls.base_references | cls.closure_references
        )
        cls.base_action = cls.graph["nodes"][0]["actions"][0]
        cls.node_allowed_writes = tuple(
            cls.graph["nodes"][0]["allowed_state_writes"]
        )

    def _v4_action(self) -> dict[str, object]:
        action = copy.deepcopy(self.base_action)
        action["handler_closure"] = _closure()
        return action

    def _validate_action(
        self,
        action: dict[str, object],
        *,
        workflow_version: int = 4,
        declared_references: frozenset[object] | None = None,
    ) -> tuple[object, ...]:
        return catalog._workflow_catalog_validate_action(
            action,
            "/action",
            node_id="INTAKE",
            node_allowed_state_writes=self.node_allowed_writes,
            declared_contracts=(
                self.declared_references
                if declared_references is None
                else declared_references
            ),
            flow="full",
            legacy_adapter=False,
            workflow_version=workflow_version,
        )

    def _assert_action_error(
        self,
        code: str,
        action: dict[str, object],
        *,
        declared_references: frozenset[object] | None = None,
    ) -> object:
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._validate_action(
                action, declared_references=declared_references
            )
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def _v4_graph(self) -> dict[str, object]:
        graph = copy.deepcopy(self.graph)
        graph["workflow_version"] = 4
        graph["contracts"].extend(
            item["handler"] for item in _closure()
        )
        for node in graph["nodes"]:
            for action in node["actions"]:
                action["handler_closure"] = _closure()
        for family in graph.get("shared_actions", []):
            family["action"]["handler_closure"] = _closure()
        return graph

    def _validate_graph(
        self,
        graph: dict[str, object],
        *,
        resolver: object | None = None,
    ) -> tuple[object, ...]:
        return catalog._workflow_catalog_validate_workflow_graph(
            graph,
            expected_entry={
                **self.entry,
                "workflow_version": 4,
            },
            inventory=self.inventory,
            bundle_root=self.bundle_root,
            contract_resolver=(
                resolver
                if resolver is not None
                else catalog.StaticContractResolver(
                    self.declared_references
                )
            ),
        )

    def test_full_v4_graph_identity_covers_each_action_closure(self) -> None:
        (
            frozen_graph,
            nodes,
            edges,
            contracts,
            profiles,
            action_edges,
        ) = self._validate_graph(self._v4_graph())

        self.assertEqual(frozen_graph["workflow_version"], 4)
        self.assertTrue(nodes)
        self.assertTrue(edges)
        self.assertTrue(profiles)
        self.assertEqual(
            self.closure_references,
            self.closure_references & set(contracts),
        )
        self.assertTrue(action_edges)
        for edge in action_edges:
            closure = edge["handler_closure"]
            self.assertEqual(tuple(item["role"] for item in closure), ROLES)
            self.assertEqual(
                tuple(item["handler"]["registry"] for item in closure),
                ("executors",) * len(ROLES),
            )
            self.assertEqual(
                tuple(item["handler"]["version"] for item in closure),
                ("v2",) * len(ROLES),
            )

    def test_v4_action_closure_is_compiled_into_semantic_identity(self) -> None:
        (
            action_id,
            normalized,
            references,
            action_edge,
            semantic_fingerprint,
        ) = self._validate_action(self._v4_action())

        self.assertEqual(action_id, self.base_action["id"])
        self.assertEqual(
            tuple(item["role"] for item in normalized["handler_closure"]),
            ROLES,
        )
        self.assertEqual(
            tuple(item["role"] for item in action_edge["handler_closure"]),
            ROLES,
        )
        self.assertTrue(self.closure_references.issubset(references))
        for role in ROLES:
            self.assertIn(f"executor.v4-{role}/v2", semantic_fingerprint)

    def test_v3_action_shape_and_semantics_remain_unchanged(self) -> None:
        original = copy.deepcopy(self.base_action)
        (
            _action_id,
            normalized,
            _references,
            action_edge,
            semantic_fingerprint,
        ) = self._validate_action(original, workflow_version=3)

        self.assertNotIn("handler_closure", normalized)
        self.assertNotIn("handler_closure", action_edge)
        self.assertNotIn("executor.v4-", semantic_fingerprint)
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._validate_action(self._v4_action(), workflow_version=3)
        self.assertEqual(raised.exception.code, "WORKFLOW_UNKNOWN_FIELD")

    def test_v4_action_requires_complete_canonical_role_inventory(self) -> None:
        missing = self._v4_action()
        missing["handler_closure"].pop()
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", missing
        )

        duplicate = self._v4_action()
        duplicate["handler_closure"][-1] = copy.deepcopy(
            duplicate["handler_closure"][0]
        )
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", duplicate
        )

        reordered = self._v4_action()
        reordered["handler_closure"][0], reordered["handler_closure"][1] = (
            reordered["handler_closure"][1],
            reordered["handler_closure"][0],
        )
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", reordered
        )

        extra = self._v4_action()
        extra["handler_closure"].append(copy.deepcopy(_closure()[0]))
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", extra
        )

    def test_v4_action_requires_exact_v2_executor_for_each_role(self) -> None:
        wrong_registry = self._v4_action()
        wrong_registry["handler_closure"][0]["handler"]["registry"] = "guards"
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", wrong_registry
        )

        wrong_identity = self._v4_action()
        wrong_identity["handler_closure"][0]["handler"]["id"] = (
            "executor.v4-accepted/v2"
        )
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", wrong_identity
        )

        old_version = self._v4_action()
        old_version["handler_closure"][0]["handler"] = {
            "registry": "executors",
            "id": "executor.v4-abandoned/v1",
            "version": "v1",
        }
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", old_version
        )

        unknown_role = self._v4_action()
        unknown_role["handler_closure"][0] = {
            "role": "supersession",
            "handler": {
                "registry": "executors",
                "id": "executor.v4-supersession/v2",
                "version": "v2",
            },
        }
        self._assert_action_error(
            "WORKFLOW_HANDLER_CLOSURE_INVALID", unknown_role
        )

    def test_v4_action_rejects_undeclared_or_unresolved_closure_handler(
        self,
    ) -> None:
        declared_without_unresolved = frozenset(
            reference
            for reference in self.declared_references
            if reference.identifier != "executor.v4-unresolved/v2"
        )
        self._assert_action_error(
            "WORKFLOW_CONTRACT_UNDECLARED",
            self._v4_action(),
            declared_references=declared_without_unresolved,
        )

        resolver_without_unresolved = catalog.StaticContractResolver(
            declared_without_unresolved
        )
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._validate_graph(
                self._v4_graph(), resolver=resolver_without_unresolved
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_CONTRACT_UNKNOWN"
        )

    def test_v4_action_requires_handler_closure_field(self) -> None:
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            self._validate_action(copy.deepcopy(self.base_action))
        self.assertEqual(raised.exception.code, "WORKFLOW_REQUIRED_FIELD")
        self.assertEqual(
            raised.exception.details["fields"], ["handler_closure"]
        )

    def test_bundle_resolver_returns_only_pinned_handler_target(self) -> None:
        (
            frozen_graph,
            nodes,
            edges,
            contracts,
            profiles,
            action_edges,
        ) = self._validate_graph(self._v4_graph())
        bundle = catalog.WorkflowBundle(
            workflow_id="full",
            workflow_version=4,
            bundle_schema_version=1,
            graph_sha256="0" * 64,
            bundle_sha256="1" * 64,
            root=self.bundle_root,
            graph=frozen_graph,
            resources={},
            nodes=nodes,
            edges=edges,
            action_edges=action_edges,
            contracts=contracts,
            execution_profiles=profiles,
            repository_orchestration=frozen_graph.get(
                "repository_orchestration"
            ),
            active_profiles=(),
        )
        action_id = self.base_action["id"]
        expected = catalog.ContractReference(
            "executors", "executor.v4-observation/v2", "v2"
        )

        self.assertEqual(
            bundle.resolve_action_handler(action_id, "observation"),
            expected,
        )
        self.assertEqual(
            bundle.resolve_action_handler(
                action_id, "observation", call_target=expected
            ),
            expected,
        )
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            bundle.resolve_action_handler(
                action_id,
                "observation",
                call_target=catalog.ContractReference(
                    "executors", "executor.v4-dispatch/v2", "v2"
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_HANDLER_CALL_TARGET_UNPINNED",
        )
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            bundle.resolve_action_handler(
                action_id,
                "observation",
                call_target={
                    "registry": "executors",
                    "id": "executor.v4-observation/v2",
                    "version": "v2",
                },
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_HANDLER_CALL_TARGET_UNPINNED",
        )

    def test_bundle_resolver_rejects_unknown_action_or_role(self) -> None:
        action = self._v4_action()
        (
            _action_id,
            _normalized,
            _references,
            action_edge,
            _semantic_fingerprint,
        ) = self._validate_action(action)
        bundle = catalog.WorkflowBundle(
            workflow_id="full",
            workflow_version=4,
            bundle_schema_version=1,
            graph_sha256="0" * 64,
            bundle_sha256="1" * 64,
            root=self.bundle_root,
            graph={},
            resources={},
            nodes={},
            edges=(),
            action_edges=(action_edge,),
            contracts=tuple(sorted(self.declared_references)),
            execution_profiles=("single-repository",),
            repository_orchestration=None,
            active_profiles=(),
        )
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            bundle.resolve_action_handler("missing.action.v1", "dispatch")
        self.assertEqual(
            raised.exception.code, "WORKFLOW_HANDLER_CLOSURE_UNKNOWN"
        )
        with self.assertRaises(catalog.WorkflowCatalogError) as raised:
            bundle.resolve_action_handler(
                self.base_action["id"], "supersession"
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_HANDLER_CLOSURE_INVALID"
        )


if __name__ == "__main__":
    unittest.main()
