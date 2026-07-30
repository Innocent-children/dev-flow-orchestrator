from __future__ import annotations

import unittest

if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


dev_flow = test_case.dev_flow


class V4RuntimeHandlerTests(unittest.TestCase):
    def test_activation_readiness_rejects_v4_descriptor_placeholder(
        self,
    ) -> None:
        class DisabledResolver:
            def resolve_callable(
                self,
                _registry: str,
                _identifier: str,
                _version: str,
                _role: str,
            ) -> object:
                return dev_flow._disabled_executor_dispatch

        class DisabledServices:
            handler_resolver = DisabledResolver()

        with self.assertRaises(
            dev_flow.WorkflowCatalogError
        ) as raised:
            dev_flow._workflow_runtime_validate_action_reference(
                DisabledServices(),
                {
                    "registry": "executors",
                    "id": "executor.v4-dispatch/v2",
                    "version": "v2",
                },
                registry="executors",
                edge_id="edge-test",
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTIVATION_INCOMPLETE",
        )

    def test_exact_full_v4_bundle_resolves_executable_role_closure(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()
        bundle = services.catalog.resolve("full", 4)
        action_id = str(bundle.action_edges[0]["trigger"]["id"])
        expected_symbols = {
            "abandoned": "_v4_abandoned_executor",
            "accepted": "_v4_accepted_executor",
            "archive": "_v4_archive_executor",
            "compensation": "_v4_compensation_executor",
            "containment": "_v4_containment_executor",
            "control": "_v4_control_executor",
            "dispatch": "_v4_dispatch_executor",
            "observation": "_v4_observation_executor",
            "reattachment": "_v4_reattachment_executor",
            "settlement": "_v4_settlement_executor",
            "unblock": "_v4_unblock_executor",
            "unresolved": "_v4_unresolved_executor",
        }

        for role, symbol in expected_symbols.items():
            with self.subTest(role=role):
                reference = bundle.resolve_action_handler(
                    action_id, role
                )
                implementation = (
                    services.handler_resolver.resolve_callable(
                        reference.registry,
                        reference.identifier,
                        reference.version,
                        "dispatcher",
                    )
                )
                self.assertEqual(implementation.__name__, symbol)
                self.assertIsNot(
                    implementation,
                    dev_flow._disabled_executor_dispatch,
                )

    def test_v4_role_handlers_fail_closed_and_accept_bound_requests(
        self,
    ) -> None:
        requests = {
            "dispatch": {
                "claim_phase": "CLAIMED",
                "containment_phase": "SPAWN_PENDING",
                "single_dispatch": True,
            },
            "observation": {
                "redispatch": False,
                "target_bound": True,
            },
            "settlement": {
                "receipt_verified": True,
                "fresh_authority": True,
            },
            "reattachment": {
                "authenticated_live_handle": True,
                "redispatch": False,
            },
            "control": {
                "target_bound": True,
                "fresh_authority": True,
            },
            "accepted": {
                "stored_receipt_verified": True,
                "fresh_authority": True,
            },
            "abandoned": {
                "controller_owned_live_evidence": True,
                "target_bound": True,
                "no_business_outcome": True,
            },
            "unresolved": {
                "scope_blocked": True,
                "redispatch": False,
            },
            "compensation": {
                "workflow_gate_verified": True,
                "opaque_host_grant_consumed": True,
                "new_execution": True,
            },
            "containment": {
                "durable_crosslink": True,
                "target_bound": True,
            },
            "archive": {
                "terminal": True,
                "index_closed": True,
            },
            "unblock": {
                "terminal_reconciliation": True,
                "archive_verified": True,
            },
        }
        services = dev_flow.workflow_runtime_services()
        bundle = services.catalog.resolve("full", 4)
        action_id = str(bundle.action_edges[0]["trigger"]["id"])

        for role, fields in requests.items():
            with self.subTest(role=role):
                reference = bundle.resolve_action_handler(
                    action_id, role
                )
                implementation = (
                    services.handler_resolver.resolve_callable(
                        reference.registry,
                        reference.identifier,
                        reference.version,
                        "dispatcher",
                    )
                )
                with self.assertRaises(ValueError):
                    implementation(
                        {
                            "schema": "dev-flow-v4-handler-request/v1",
                            "role": role,
                        },
                        (),
                    )
                result = implementation(
                    {
                        "schema": "dev-flow-v4-handler-request/v1",
                        "role": role,
                        **fields,
                    },
                    (),
                )
                self.assertEqual(
                    result,
                    {
                        "schema": "dev-flow-v4-handler-result/v1",
                        "role": role,
                        "authorized": True,
                    },
                )


if __name__ == "__main__":
    unittest.main()
