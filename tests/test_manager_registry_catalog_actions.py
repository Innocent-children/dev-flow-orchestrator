from __future__ import annotations

import copy
import json
import time
import unittest
from unittest import mock

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class ManagerRegistryCatalogActionTests(DevFlowTestCase):
    _FULL_PLACEMENTS = {
        "BASELINED",
        "BLOCKED",
        "FINALIZING",
        "IMPACT_REVIEW",
        "IMPLEMENTING",
        "INDEXED",
        "INTAKE",
        "PLANNING",
        "PREFLIGHTED",
        "REVIEWING",
        "ROUTE_APPROVED",
        "VERIFYING",
        "WORKSPACE_READY",
    }
    _LITE_PLACEMENTS = {
        "BLOCKED",
        "IMPLEMENTING",
        "INTAKE",
        "PREFLIGHTED",
        "VERIFYING",
    }
    _RAW_PATH_NAMES = (
        "_commit_manager_registry_operation",
        "_commit_state",
        "_manager_registry_candidate",
        "_persist_state_transaction",
        "publish_manager_secret",
    )

    def test_manager_orchestration_allowlist_is_exact_and_excludes_registry_actions(
        self,
    ) -> None:
        registry_actions = {
            dev_flow.ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
            dev_flow.ORCHESTRATION_OPERATION_MANAGER_REVOKE,
        }
        manager_operations = (
            set(dev_flow.ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS)
            - registry_actions
        )
        declared = dev_flow._MANAGER_PACKAGE_ACTION_EVENT_TYPES
        self.assertTrue(registry_actions.isdisjoint(declared))
        self.assertEqual(len(manager_operations), 27)
        for operation_id in manager_operations:
            identities = (
                dev_flow._workflow_catalog_repository_semantic_identities(
                    operation_id
                )
            )
            self.assertEqual(
                declared.get(operation_id),
                frozenset({str(identities["event_id"])}),
                operation_id,
            )

    @staticmethod
    def _plain(value: object) -> object:
        if hasattr(value, "items"):
            return {
                str(key): ManagerRegistryCatalogActionTests._plain(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                ManagerRegistryCatalogActionTests._plain(item)
                for item in value
            ]
        return value

    @staticmethod
    def _principal(*, role: str = "operator") -> dict[str, object]:
        return {
            "schema": dev_flow.AGENT_PRINCIPAL_SCHEMA,
            "role": role,
            "session_id": "manager-session-catalog-action",
            "os_user_identity_sha256": "3" * 64,
            "host_identity_sha256": "4" * 64,
        }

    @staticmethod
    def _state(
        *,
        revision: int = 7,
        orchestration: dict[str, object] | None = None,
    ) -> dict[str, object]:
        state: dict[str, object] = {
            "schema_version": dev_flow.V3_TASK_SCHEMA_VERSION,
            "task_id": "manager-registry-catalog-action",
            "revision": revision,
            "status": "INTAKE",
        }
        if orchestration is not None:
            state["orchestration"] = orchestration
        return state

    @staticmethod
    def _issue_verifier(
        *,
        revision: int = 7,
    ) -> tuple[bytearray, object, int]:
        secret = bytearray(b"S" * 32)
        wall_time_ns = time.time_ns()
        verifier = dev_flow.issue_manager_capability(
            task_id="manager-registry-catalog-action",
            issued_for_task_revision=revision,
            manager_session_id="manager-session-catalog-action",
            allowed_actions=["task.transition"],
            ttl_ns=60_000_000_000,
            wall_time_ns=wall_time_ns,
            monotonic_time_ns=dev_flow._manager_system_monotonic_ns(),
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="mcp-secret-channel",
            operator_confirmation_sha256="1" * 64,
            issuance_audit_sha256="2" * 64,
            manager_secret=secret,
        )
        return secret, verifier, wall_time_ns

    @staticmethod
    def _publication() -> dict[str, object]:
        return {
            "schema": dev_flow.MANAGER_SECRET_PUBLICATION_PLAN_SCHEMA,
            "effect": "secret-publication",
            "publication_required": True,
            "transport": "mcp-secret-channel",
            "channel_binding_sha256": "5" * 64,
        }

    def _raw_path_patches(self) -> tuple[list[object], list[object]]:
        patchers = [
            mock.patch.object(dev_flow, name)
            for name in self._RAW_PATH_NAMES
        ]
        effects = [patcher.start() for patcher in patchers]
        self.addCleanup(
            lambda: [patcher.stop() for patcher in reversed(patchers)]
        )
        return patchers, effects

    def test_manager_actions_are_exact_catalog_sealed_nonterminal_actions(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()
        expected_by_flow = {
            "full": self._FULL_PLACEMENTS,
            "lite": self._LITE_PLACEMENTS,
        }
        for flow, expected_nodes in expected_by_flow.items():
            with self.subTest(flow=flow):
                bundle = services.catalog.resolve(flow, 3)
                for action_id, command in (
                    (
                        dev_flow.MANAGER_REGISTRY_AUTHORIZE_ACTION_ID,
                        "manager-authorize",
                    ),
                    (
                        dev_flow.MANAGER_REGISTRY_REVOKE_ACTION_ID,
                        "manager-revoke",
                    ),
                ):
                    observed_nodes = {
                        str(edge["source"])
                        for edge in bundle.action_edges
                        if edge["trigger"]["id"] == action_id
                    }
                    self.assertEqual(observed_nodes, expected_nodes)
                    for node_id in expected_nodes:
                        edge = bundle.resolve_public_action(
                            node_id,
                            command,
                            selector="operator",
                        )
                        self.assertEqual(edge["source"], edge["target"])
                        self.assertEqual(edge["class"], "action")
                        self.assertEqual(
                            edge["public_command"]["selector"],
                            "authority",
                        )
                with self.assertRaises(
                    dev_flow.WorkflowCatalogError
                ) as terminal:
                    bundle.resolve_public_action(
                        "DONE",
                        "manager-authorize",
                        selector="operator",
                    )
                self.assertEqual(
                    terminal.exception.code,
                    "WORKFLOW_ACTION_PLACEMENT_INVALID",
                )

        full = services.catalog.resolve("full", 3)
        authorize = full.resolve_public_action(
            "INTAKE", "manager-authorize", selector="operator"
        )
        revoke = full.resolve_public_action(
            "INTAKE", "manager-revoke", selector="operator"
        )
        self.assertEqual(
            set(authorize["side_effects"]),
            {"secret-publication", "task-state"},
        )
        self.assertEqual(
            {effect["dispatch"] for effect in authorize["effects"]},
            {"single-dispatch"},
        )
        self.assertEqual(set(revoke["side_effects"]), {"task-state"})
        self.assertEqual(
            {effect["dispatch"] for effect in revoke["effects"]},
            {"none"},
        )
        self.assertIs(
            services.handler_resolver.resolve_callable(
                "guards",
                "guard.manager-registry-action/v1",
                "v1",
                "evaluator",
            ),
            dev_flow._manager_registry_action_guard_v1,
        )
        self.assertIs(
            services.handler_resolver.resolve_callable(
                "reducers",
                "reducer.manager-registry-action/v1",
                "v1",
                "reducer",
            ),
            dev_flow._manager_registry_action_reducer_v1,
        )

    def test_authorize_adapter_returns_strict_secret_free_outcome_without_writes(
        self,
    ) -> None:
        state = self._state()
        original_state = copy.deepcopy(state)
        secret, verifier, _wall_time_ns = self._issue_verifier()
        publication = self._publication()
        edge = (
            dev_flow.workflow_runtime_services()
            .catalog.resolve("full", 3)
            .resolve_public_action(
                "INTAKE",
                "manager-authorize",
                selector="operator",
            )
        )
        _patchers, raw_effects = self._raw_path_patches()

        outcome = dev_flow.build_manager_registry_action_outcome_v1(
            state,
            edge,
            operation="authorize",
            verifier=verifier,
            principal=self._principal(),
            secret_publication=publication,
        )

        self.assertIs(type(outcome), dev_flow.ActionOutcome)
        self.assertEqual(
            outcome.action_id,
            dev_flow.MANAGER_REGISTRY_AUTHORIZE_ACTION_ID,
        )
        self.assertEqual(outcome.proposed_edge_id, edge["id"])
        delta = self._plain(outcome.proposed_state_delta)
        self.assertEqual(set(delta), {"operations", "remove", "set"})
        self.assertEqual(delta["operations"], [])
        self.assertEqual(delta["remove"], [])
        self.assertEqual(set(delta["set"]), {"/orchestration"})
        registry = delta["set"]["/orchestration"][
            "manager_capabilities"
        ]
        self.assertEqual(
            set(registry),
            {verifier.capability_id},
        )
        self.assertEqual(
            self._plain(outcome.external_postconditions),
            [publication],
        )
        serialized_outcome = json.dumps(
            {
                "delta": delta,
                "evidence": self._plain(outcome.evidence_records),
                "postconditions": self._plain(
                    outcome.external_postconditions
                ),
            },
            sort_keys=True,
        )
        self.assertNotIn(secret.decode("ascii"), serialized_outcome)
        self.assertEqual(state, original_state)
        for effect in raw_effects:
            effect.assert_not_called()

    def test_revoke_adapter_accepts_older_issuance_revision_and_has_no_external_effect(
        self,
    ) -> None:
        _secret, verifier, wall_time_ns = self._issue_verifier(
            revision=7
        )
        revoked = dev_flow.revoke_manager_capability(
            verifier,
            revoked_at_wall_ns=wall_time_ns + 1,
            reason="operator-request",
            revocation_audit_sha256="6" * 64,
        )
        state = self._state(
            revision=8,
            orchestration={
                "schema": "dev-flow-orchestration-state/v1",
                "manager_capabilities": {
                    verifier.capability_id: (
                        verifier.as_persistent_dict()
                    )
                },
            },
        )
        original_state = copy.deepcopy(state)
        edge = (
            dev_flow.workflow_runtime_services()
            .catalog.resolve("full", 3)
            .resolve_public_action(
                "INTAKE",
                "manager-revoke",
                selector="operator",
            )
        )
        _patchers, raw_effects = self._raw_path_patches()

        outcome = dev_flow.build_manager_registry_action_outcome_v1(
            state,
            edge,
            operation="revoke",
            verifier=revoked,
            principal=self._principal(),
        )

        self.assertIs(type(outcome), dev_flow.ActionOutcome)
        self.assertEqual(
            outcome.action_id,
            dev_flow.MANAGER_REGISTRY_REVOKE_ACTION_ID,
        )
        self.assertEqual(tuple(outcome.external_postconditions), ())
        delta = self._plain(outcome.proposed_state_delta)
        record = delta["set"]["/orchestration"][
            "manager_capabilities"
        ][verifier.capability_id]
        self.assertEqual(
            record["issued_for_task_revision"],
            7,
        )
        self.assertEqual(
            record["revoked_at_wall_ns"],
            wall_time_ns + 1,
        )
        self.assertEqual(state, original_state)
        for effect in raw_effects:
            effect.assert_not_called()

    def test_action_identity_selector_and_permission_fail_before_any_write(
        self,
    ) -> None:
        state = self._state()
        _secret, verifier, _wall_time_ns = self._issue_verifier()
        publication = self._publication()
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        edge = bundle.resolve_public_action(
            "INTAKE", "manager-authorize", selector="operator"
        )
        state_path = self.root / "state.json"
        event_path = self.root / "events.jsonl"
        state_path.write_bytes(b'{"sentinel":"state"}\n')
        event_path.write_bytes(b'{"sentinel":"event"}\n')
        before_state = state_path.read_bytes()
        before_events = event_path.read_bytes()
        _patchers, raw_effects = self._raw_path_patches()

        forged_edge = self._plain(edge)
        forged_edge["trigger"]["id"] = "manager.capability.forged.v1"
        with self.assertRaises(dev_flow.FlowError) as action_error:
            dev_flow.build_manager_registry_action_outcome_v1(
                state,
                forged_edge,
                operation="authorize",
                verifier=verifier,
                principal=self._principal(),
                secret_publication=publication,
            )
        self.assertEqual(
            action_error.exception.code,
            "MANAGER_REGISTRY_ACTION_EDGE_MISMATCH",
        )

        with self.assertRaises(
            dev_flow.WorkflowCatalogError
        ) as selector_error:
            bundle.resolve_public_action(
                "INTAKE",
                "manager-authorize",
                selector="manager",
            )
        self.assertEqual(
            selector_error.exception.code,
            "WORKFLOW_ACTION_SELECTOR_UNDECLARED",
        )

        with self.assertRaises(dev_flow.FlowError) as permission_error:
            dev_flow.build_manager_registry_action_outcome_v1(
                state,
                edge,
                operation="authorize",
                verifier=verifier,
                principal=self._principal(role="manager"),
                secret_publication=publication,
            )
        self.assertEqual(
            permission_error.exception.code,
            "MANAGER_REGISTRY_OPERATOR_REQUIRED",
        )

        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(event_path.read_bytes(), before_events)
        for effect in raw_effects:
            effect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
