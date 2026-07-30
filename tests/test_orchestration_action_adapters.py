from __future__ import annotations

import copy
import dataclasses
import sys
import unittest
from collections.abc import Mapping
from types import MappingProxyType

if __package__:
    from . import test_workflow_catalog as support
else:
    import test_workflow_catalog as support


MODULE_NAME = "dev_flow_orchestration_action_adapter_tests"
dev_flow = support._load_runtime_module(MODULE_NAME)


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class _Catalog:
    def __init__(self, bundle: object, *, sealed: bool = True) -> None:
        self.bundle = bundle
        self.resolve_calls = 0
        self.sealed = sealed

    def resolve_identity(self, _bundle_sha256: str) -> object:
        self.resolve_calls += 1
        return self.bundle


class OrchestrationActionAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = dev_flow.workflow_runtime_services().catalog
        cls.bundle = cls.catalog.resolve("full", 4)
        cls.lite_bundle = cls.catalog.resolve("lite", 4)
        cls.legacy_bundle = cls.catalog.resolve("full-legacy", 2)
        metadata = cls.bundle.repository_orchestration
        assert isinstance(metadata, Mapping)
        cls.metadata = metadata
        cls.operation_ids = tuple(metadata["operation_ids"])
        cls.matrix = {
            str(item["operation_id"]): item
            for item in metadata["operation_matrix"]
        }
        cls.alias_ids = tuple(
            str(item["alias_id"]) for item in metadata["legacy_aliases"]
        )

    def tearDown(self) -> None:
        sys.modules.setdefault(MODULE_NAME, dev_flow)

    def _state(
        self,
        *,
        bundle: object | None = None,
        task_id: str = "adapter-task",
        revision: int = 17,
        status: str = "INTAKE",
    ) -> dict[str, object]:
        selected = bundle or self.bundle
        return {
            "schema_version": 3,
            "execution_profile": "multi-repository",
            "task_id": task_id,
            "revision": revision,
            "status": status,
            "workflow_ref": {
                "id": getattr(selected, "workflow_id"),
                "version": getattr(selected, "workflow_version"),
                "schema": getattr(selected, "graph")["schema"],
                "graph_sha256": getattr(selected, "graph_sha256"),
                "bundle_sha256": getattr(selected, "bundle_sha256"),
            },
        }

    def _assert_error(
        self,
        code: str,
        callback: object,
    ) -> dev_flow.OrchestrationActionAdapterError:
        assert callable(callback)
        with self.assertRaises(
            dev_flow.OrchestrationActionAdapterError
        ) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(raised.exception.as_dict()["code"], code)
        return raised.exception

    def _tampered_metadata_bundle(
        self,
        mutation: object,
    ) -> object:
        metadata = _thaw(self.metadata)
        assert isinstance(metadata, dict)
        assert callable(mutation)
        mutation(metadata)
        return dataclasses.replace(
            self.bundle,
            repository_orchestration=_freeze(metadata),
        )

    def _tampered_edge_bundle(
        self,
        operation_id: str,
        mutation: object,
        *,
        duplicate: bool = False,
    ) -> object:
        selection = dev_flow.resolve_catalog_orchestration_action(
            self._state(), operation_id, catalog=self.catalog
        )
        replacement: object | None = None
        edges: list[object] = []
        for edge in self.bundle.action_edges:
            if edge["id"] != selection.edge_id:
                edges.append(edge)
                continue
            value = _thaw(edge)
            assert isinstance(value, dict)
            assert callable(mutation)
            mutation(value)
            replacement = _freeze(value)
            edges.append(replacement)
        self.assertIsNotNone(replacement)
        if duplicate:
            edges.append(replacement)
        return dataclasses.replace(
            self.bundle,
            action_edges=tuple(edges),
        )

    def test_all_29_operations_select_one_exact_catalog_edge(self) -> None:
        self.assertEqual(len(self.operation_ids), 29)
        self.assertEqual(set(self.operation_ids), set(self.matrix))
        state = self._state()
        before = copy.deepcopy(state)
        identities: dict[str, set[str]] = {
            "action": set(),
            "validator": set(),
            "event": set(),
            "write_set": set(),
            "effect": set(),
            "edge": set(),
        }
        manager = {
            "manager.capability.authorize/v1": (
                "manager-authorize",
                "manager_capability_authorized",
            ),
            "manager.capability.revoke/v1": (
                "manager-revoke",
                "manager_capability_revoked",
            ),
        }
        for operation_id in self.operation_ids:
            with self.subTest(operation_id=operation_id):
                contract = self.matrix[operation_id]
                selection = (
                    dev_flow.resolve_catalog_orchestration_action(
                        state, operation_id, catalog=self.catalog
                    )
                )
                self.assertEqual(selection.task_id, state["task_id"])
                self.assertEqual(
                    selection.expected_revision, state["revision"]
                )
                self.assertEqual(selection.node_id, state["status"])
                self.assertEqual(selection.operation_id, operation_id)
                self.assertEqual(
                    selection.action_id, contract["action_id"]
                )
                self.assertEqual(
                    selection.validator_id, contract["validator_id"]
                )
                self.assertEqual(
                    selection.event_id, contract["event_id"]
                )
                self.assertEqual(
                    selection.write_set_id, contract["write_set_id"]
                )
                self.assertEqual(
                    selection.effect_ids, tuple(contract["effect_ids"])
                )
                if operation_id in manager:
                    command, event = manager[operation_id]
                    self.assertEqual(
                        (
                            selection.public_command_id,
                            selection.public_selector,
                            selection.public_selector_value,
                            selection.canonical_event,
                        ),
                        (command, "authority", "operator", event),
                    )
                else:
                    self.assertEqual(
                        (
                            selection.public_command_id,
                            selection.public_selector,
                            selection.public_selector_value,
                            selection.canonical_event,
                        ),
                        (
                            "orchestration",
                            "operation",
                            operation_id,
                            contract["event_id"],
                        ),
                    )
                identities["action"].add(selection.action_id)
                identities["validator"].add(selection.validator_id)
                identities["event"].add(selection.event_id)
                identities["write_set"].add(selection.write_set_id)
                identities["effect"].update(selection.effect_ids)
                identities["edge"].add(selection.edge_id)
                with self.assertRaises(
                    dataclasses.FrozenInstanceError
                ):
                    selection.operation_id = "changed"
                intent = dev_flow.OrchestrationActionSemanticIntent(
                    operation_id, {"request": {"id": "probe"}}
                )
                with self.assertRaises(TypeError):
                    intent.payload["request"]["id"] = "changed"
                self._assert_error(
                    "ORCHESTRATION_ACTION_SEMANTIC_VALIDATOR_REJECTED",
                    lambda selected=operation_id, typed=intent: (
                        dev_flow.build_catalog_orchestration_action_outcome(
                            state,
                            selected,
                            typed,
                            catalog=self.catalog,
                        )
                    ),
                )
        for role, values in identities.items():
            with self.subTest(identity_role=role):
                self.assertEqual(len(values), 29)
        self.assertEqual(state, before)

    def test_typed_intent_is_required_and_cross_operation_closed(
        self,
    ) -> None:
        first, second = self.operation_ids[:2]
        state = self._state()
        self._assert_error(
            "ORCHESTRATION_ACTION_INTENT_INVALID",
            lambda: dev_flow.build_catalog_orchestration_action_outcome(
                state,
                first,
                {"operation_id": first, "payload": {}},
                catalog=self.catalog,
            ),
        )
        intent = dev_flow.OrchestrationActionSemanticIntent(second, {})
        self._assert_error(
            "ORCHESTRATION_ACTION_INTENT_CROSS_BINDING",
            lambda: dev_flow.build_catalog_orchestration_action_outcome(
                state, first, intent, catalog=self.catalog
            ),
        )

    def test_validator_registry_is_static_exact_and_closed(self) -> None:
        operation_id = self.operation_ids[0]
        validator_id = str(self.matrix[operation_id]["validator_id"])
        self._assert_error(
            "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_FROZEN",
            lambda: (
                dev_flow._register_orchestration_action_semantic_validator(
                    operation_id, validator_id, lambda *_args: None
                )
            ),
        )
        register, freeze, _validate = (
            dev_flow._build_orchestration_action_semantic_authority()
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_VALIDATOR_REGISTRATION_UNKNOWN",
            lambda: register(
                "orchestration.unknown/v1",
                "orchestration.unknown.validator.v1",
                lambda *_args: None,
            ),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_VALIDATOR_IMPLEMENTATION_FORBIDDEN",
            lambda: register(
                operation_id,
                validator_id,
                lambda *_args: None,
            ),
        )
        freeze()
        self._assert_error(
            "ORCHESTRATION_ACTION_VALIDATOR_REGISTRY_FROZEN",
            lambda: register(
                operation_id,
                validator_id,
                lambda *_args: None,
            ),
        )
        self.assertNotIn(
            "_register_orchestration_action_semantic_validator",
            dev_flow.__all__,
        )
        self.assertNotIn(
            "freeze_orchestration_action_semantic_validators",
            dev_flow.__all__,
        )

    def test_alias_unknown_profile_pin_and_node_reject(self) -> None:
        state = self._state()
        for alias_id in self.alias_ids:
            with self.subTest(alias_id=alias_id):
                self._assert_error(
                    "ORCHESTRATION_ACTION_LEGACY_ALIAS_FORBIDDEN",
                    lambda value=alias_id: (
                        dev_flow.resolve_catalog_orchestration_action(
                            state, value, catalog=self.catalog
                        )
                    ),
                )
        self._assert_error(
            "ORCHESTRATION_ACTION_UNDECLARED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                state,
                "orchestration.unknown/v1",
                catalog=self.catalog,
            ),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_FULL_V3_REQUIRED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(bundle=self.lite_bundle),
                self.operation_ids[0],
                catalog=self.catalog,
            ),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_FULL_V3_REQUIRED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(bundle=self.legacy_bundle),
                self.operation_ids[0],
                catalog=self.catalog,
            ),
        )
        unpinned = self._state()
        unpinned["workflow_ref"]["bundle_sha256"] = "0" * 64
        self._assert_error(
            "ORCHESTRATION_ACTION_BUNDLE_UNPINNED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                unpinned, self.operation_ids[0], catalog=self.catalog
            ),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_NODE_INVALID",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(status="DONE"),
                self.operation_ids[0],
                catalog=self.catalog,
            ),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_CATALOG_UNSEALED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                state,
                self.operation_ids[0],
                catalog=_Catalog(self.bundle, sealed=False),
            ),
        )

    def test_state_and_workflow_reference_are_exact(self) -> None:
        operation_id = self.operation_ids[0]
        cases: tuple[tuple[str, str, object], ...] = (
            (
                "schema",
                "ORCHESTRATION_ACTION_V3_REQUIRED",
                lambda state: state.__setitem__("schema_version", 2),
            ),
            (
                "missing-ref",
                "ORCHESTRATION_ACTION_WORKFLOW_REF_INVALID",
                lambda state: state["workflow_ref"].pop("graph_sha256"),
            ),
            (
                "extra-ref",
                "ORCHESTRATION_ACTION_WORKFLOW_REF_INVALID",
                lambda state: state["workflow_ref"].update({"extra": True}),
            ),
            (
                "wrong-graph",
                "ORCHESTRATION_ACTION_BUNDLE_BINDING_INVALID",
                lambda state: state["workflow_ref"].update(
                    {"graph_sha256": "0" * 64}
                ),
            ),
            (
                "negative-revision",
                "ORCHESTRATION_ACTION_STATE_INVALID",
                lambda state: state.__setitem__("revision", -1),
            ),
        )
        for name, code, mutation in cases:
            with self.subTest(name=name):
                state = self._state()
                mutation(state)
                self._assert_error(
                    code,
                    lambda value=state: (
                        dev_flow.resolve_catalog_orchestration_action(
                            value,
                            operation_id,
                            catalog=self.catalog,
                        )
                    ),
                )
        single_repository = self._state()
        single_repository["execution_profile"] = "single-repository"
        manager_selection = (
            dev_flow.resolve_catalog_orchestration_action(
                single_repository,
                "manager.capability.authorize/v1",
                catalog=self.catalog,
            )
        )
        self.assertEqual(
            manager_selection.operation_id,
            "manager.capability.authorize/v1",
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MULTI_PROFILE_REQUIRED",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                single_repository,
                "orchestration.assignment.issue/v1",
                catalog=self.catalog,
            ),
        )

    def test_delta_is_exact_canonical_and_scoped(self) -> None:
        selection = dev_flow.resolve_catalog_orchestration_action(
            self._state(),
            "orchestration.assignment.issue/v1",
            catalog=self.catalog,
        )
        root = selection.allowed_write_roots[0]
        normalized = (
            dev_flow._orchestration_action_adapter_normalize_delta(
                {
                    "set": {f"{root}/probe": {"ok": True}},
                    "remove": [],
                    "operations": [],
                },
                allowed_roots=selection.allowed_write_roots,
            )
        )
        self.assertEqual(
            normalized["set"][f"{root}/probe"]["ok"], True
        )
        with self.assertRaises(TypeError):
            normalized["set"][f"{root}/probe"]["ok"] = False

        cases: tuple[tuple[str, str, Mapping[str, object]], ...] = (
            (
                "out-of-scope",
                "ORCHESTRATION_ACTION_WRITE_OUT_OF_SCOPE",
                {
                    "set": {"/status": "DONE"},
                    "remove": [],
                    "operations": [],
                },
            ),
            (
                "missing-field",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {"set": {"/status": "DONE"}, "remove": []},
            ),
            (
                "unknown-field",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {
                    "set": {"/status": "DONE"},
                    "remove": [],
                    "operations": [],
                    "unknown": True,
                },
            ),
            (
                "implicit-operation",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {
                    "set": {},
                    "remove": [],
                    "operations": [{"op": "set"}],
                },
            ),
            (
                "empty",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {"set": {}, "remove": [], "operations": []},
            ),
            (
                "overlap",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {
                    "set": {
                        root: {},
                        f"{root}/child": True,
                    },
                    "remove": [],
                    "operations": [],
                },
            ),
            (
                "bad-pointer",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {
                    "set": {f"{root}/bad~2pointer": True},
                    "remove": [],
                    "operations": [],
                },
            ),
            (
                "unordered-remove",
                "ORCHESTRATION_ACTION_DELTA_INVALID",
                {
                    "set": {},
                    "remove": [f"{root}/z", f"{root}/a"],
                    "operations": [],
                },
            ),
        )
        for name, code, delta in cases:
            with self.subTest(name=name):
                self._assert_error(
                    code,
                    lambda candidate=delta: (
                        dev_flow._orchestration_action_adapter_normalize_delta(
                            candidate,
                            allowed_roots=selection.allowed_write_roots,
                        )
                    ),
                )

    def test_semantic_json_is_strict_and_intents_are_immutable(
        self,
    ) -> None:
        operation_id = "orchestration.assignment.issue/v1"
        cases: tuple[tuple[str, Mapping[str, object]], ...] = (
            ("non-nfc-value", {"probe": "e\u0301"}),
            ("non-nfc-key", {"e\u0301": True}),
            ("invalid-surrogate", {"probe": "\ud800"}),
            ("wide-integer", {"probe": 2**63}),
        )
        for name, payload in cases:
            with self.subTest(name=name):
                self._assert_error(
                    "ORCHESTRATION_ACTION_JSON_INVALID",
                    lambda candidate=payload: (
                        dev_flow.OrchestrationActionSemanticIntent(
                            operation_id, candidate
                        )
                    ),
                )
        intent = dev_flow.OrchestrationActionSemanticIntent(
            operation_id, {"nested": [1, {"ok": True}]}
        )
        self.assertIsInstance(intent.payload, MappingProxyType)
        self.assertIsInstance(intent.payload["nested"], tuple)
        with self.assertRaises(TypeError):
            intent.payload["nested"][1]["ok"] = False

    def test_manager_nonce_partition_matches_operator_registry_authority(
        self,
    ) -> None:
        registry = dev_flow.resolve_catalog_orchestration_action(
            self._state(),
            "manager.capability.authorize/v1",
            catalog=self.catalog,
        )
        registry_delta = MappingProxyType(
            {
                "set": MappingProxyType(
                    {
                        (
                            "/orchestration/manager_capabilities/"
                            "new-capability"
                        ): {"used_request_nonce_sha256s": []}
                    }
                ),
                "remove": (),
                "operations": (),
            }
        )
        self.assertFalse(
            dev_flow._orchestration_action_adapter_manager_nonce_declared(
                registry_delta, registry
            )
        )
        nonce_pointer = (
            "/orchestration/manager_capabilities/"
            "capability/used_request_nonce_sha256s/probe"
        )
        forbidden_registry_nonce = MappingProxyType(
            {
                "set": MappingProxyType({nonce_pointer: True}),
                "remove": (),
                "operations": (),
            }
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_FORBIDDEN",
            lambda: (
                dev_flow._orchestration_action_adapter_manager_nonce_declared(
                    forbidden_registry_nonce, registry
                )
            ),
        )
        empty = MappingProxyType(
            {
                "set": MappingProxyType({}),
                "remove": (),
                "operations": (),
            }
        )
        self.assertFalse(
            dev_flow._orchestration_action_adapter_manager_nonce_declared(
                empty, registry
            )
        )
        manager_action = dev_flow.resolve_catalog_orchestration_action(
            self._state(),
            "orchestration.assignment.issue/v1",
            catalog=self.catalog,
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_REQUIRED",
            lambda: (
                dev_flow._orchestration_action_adapter_manager_nonce_declared(
                    empty, manager_action
                )
            ),
        )
        manager_nonce_delta = MappingProxyType(
            {
                "set": MappingProxyType({nonce_pointer: True}),
                "remove": (),
                "operations": (),
            }
        )
        self.assertTrue(
            dev_flow._orchestration_action_adapter_manager_nonce_declared(
                manager_nonce_delta, manager_action
            )
        )
        wrong_nonce = MappingProxyType(
            {
                "set": MappingProxyType(
                    {
                        (
                            "/orchestration/manager_capabilities/"
                            "capability/revoked_at_wall_ns"
                        ): 1
                    }
                ),
                "remove": (),
                "operations": (),
            }
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_REQUIRED",
            lambda: (
                dev_flow._orchestration_action_adapter_manager_nonce_declared(
                    wrong_nonce, manager_action
                )
            ),
        )
        narrowed = dataclasses.replace(
            manager_action,
            allowed_write_roots=("/orchestration/assignments",),
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MANAGER_NONCE_UNDECLARED",
            lambda: (
                dev_flow._orchestration_action_adapter_manager_nonce_declared(
                    manager_nonce_delta, narrowed
                )
            ),
        )

    def test_matrix_and_edge_cross_binding_fail_closed(self) -> None:
        first = self.operation_ids[2]
        second = self.operation_ids[3]

        def overload(metadata: dict[str, object]) -> None:
            matrix = metadata["operation_matrix"]
            matrix[1]["validator_id"] = matrix[0]["validator_id"]

        overloaded = self._tampered_metadata_bundle(overload)
        self._assert_error(
            "ORCHESTRATION_ACTION_SEMANTIC_OVERLOAD",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(), first, catalog=_Catalog(overloaded)
            ),
        )

        def unknown_field(metadata: dict[str, object]) -> None:
            metadata["operation_matrix"][0]["unknown"] = True

        unknown = self._tampered_metadata_bundle(unknown_field)
        self._assert_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(), first, catalog=_Catalog(unknown)
            ),
        )

        def wrong_exact_identity(
            metadata: dict[str, object],
        ) -> None:
            metadata["operation_matrix"][0][
                "validator_id"
            ] = "manager.capability.authorize.other-validator.v1"

        wrong_identity = self._tampered_metadata_bundle(
            wrong_exact_identity
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(), first, catalog=_Catalog(wrong_identity)
            ),
        )

        def missing_operation(metadata: dict[str, object]) -> None:
            metadata["operation_ids"].pop()
            metadata["operation_matrix"].pop()

        incomplete = self._tampered_metadata_bundle(missing_operation)
        self._assert_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(), first, catalog=_Catalog(incomplete)
            ),
        )

        def wrong_alias_target(metadata: dict[str, object]) -> None:
            metadata["legacy_aliases"][0]["operation_ids"] = [
                self.operation_ids[2]
            ]

        wrong_alias = self._tampered_metadata_bundle(
            wrong_alias_target
        )
        self._assert_error(
            "ORCHESTRATION_ACTION_MATRIX_INVALID",
            lambda: dev_flow.resolve_catalog_orchestration_action(
                self._state(), first, catalog=_Catalog(wrong_alias)
            ),
        )

        edge_cases: tuple[tuple[str, object, bool, str], ...] = (
            (
                "wrong-target",
                lambda edge: edge.__setitem__("target", "PREFLIGHTED"),
                False,
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            ),
            (
                "wrong-action",
                lambda edge: edge["trigger"].__setitem__(
                    "id", self.matrix[second]["action_id"]
                ),
                False,
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            ),
            (
                "wrong-event",
                lambda edge: edge.__setitem__(
                    "canonical_event", self.matrix[second]["event_id"]
                ),
                False,
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            ),
            (
                "wrong-effect",
                lambda edge: edge["effects"][0].__setitem__(
                    "id", self.matrix[second]["effect_ids"][0]
                ),
                False,
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            ),
            (
                "wrong-write-set",
                lambda edge: edge.__setitem__(
                    "kernel_state_writes",
                    ["/orchestration/manager_capabilities"],
                ),
                False,
                "ORCHESTRATION_ACTION_EDGE_BINDING_INVALID",
            ),
            (
                "wrong-public-selector",
                lambda edge: edge["public_command"].__setitem__(
                    "selector", "alias"
                ),
                False,
                "ORCHESTRATION_ACTION_EDGE_INVALID",
            ),
            (
                "ambiguous-public-selector",
                lambda _edge: None,
                True,
                "ORCHESTRATION_ACTION_EDGE_INVALID",
            ),
        )
        for name, mutation, duplicate, code in edge_cases:
            with self.subTest(name=name):
                tampered = self._tampered_edge_bundle(
                    first, mutation, duplicate=duplicate
                )
                self._assert_error(
                    code,
                    lambda candidate=tampered: (
                        dev_flow.resolve_catalog_orchestration_action(
                            self._state(),
                            first,
                            catalog=_Catalog(candidate),
                        )
                    ),
                )

    def test_no_raw_delta_or_persistence_dispatch_surface(self) -> None:
        retired = {
            "OrchestrationActionRequest",
            "OrchestrationActionValidatedDelta",
            "OrchestrationActionValidatorBindingIndex",
            "build_catalog_orchestration_action_request",
            "_issue_catalog_orchestration_action_validated_delta",
        }
        for name in retired:
            with self.subTest(name=name):
                self.assertFalse(hasattr(dev_flow, name))
                self.assertNotIn(name, dev_flow.__all__)
        exported = {
            name
            for name in dev_flow.__all__
            if "orchestration_action" in name.lower()
        }
        self.assertFalse(
            any(
                token in name.lower()
                for name in exported
                for token in ("persist", "dispatch", "delta_seal")
            )
        )


if __name__ == "__main__":
    unittest.main()
