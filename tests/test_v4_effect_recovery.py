from __future__ import annotations

import dataclasses
import inspect
import unittest

from tests.support import V4OrchestrationTestCase, runtime_services


VALID_REQUESTS = {
    "dispatch": {
        "claim_phase": "CLAIMED",
        "containment_phase": "SPAWN_PENDING",
        "single_dispatch": True,
    },
    "observation": {"redispatch": False, "target_bound": True},
    "settlement": {"receipt_verified": True, "fresh_authority": True},
    "reattachment": {
        "authenticated_live_handle": True,
        "redispatch": False,
    },
    "control": {"target_bound": True, "fresh_authority": True},
    "accepted": {
        "stored_receipt_verified": True,
        "fresh_authority": True,
    },
    "abandoned": {
        "controller_owned_live_evidence": True,
        "target_bound": True,
        "no_business_outcome": True,
    },
    "unresolved": {"scope_blocked": True, "redispatch": False},
    "compensation": {
        "workflow_gate_verified": True,
        "opaque_host_grant_consumed": True,
        "new_execution": True,
    },
    "containment": {"durable_crosslink": True, "target_bound": True},
    "archive": {"terminal": True, "index_closed": True},
    "unblock": {
        "terminal_reconciliation": True,
        "archive_verified": True,
    },
}


class _InjectedEffectFailure(RuntimeError):
    pass


class V4EffectRecoveryTests(V4OrchestrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.services = runtime_services()

    def _call(self, role: str) -> dict[str, object]:
        executor = self.services.registries.executors.resolve_callable(
            f"executor.v4-{role}/v2", "v2", "dispatcher"
        )
        request = {
            "schema": "dev-flow-v4-handler-request/v1",
            "role": role,
            **VALID_REQUESTS[role],
        }
        result = executor(request, ())
        self.assertEqual(
            result,
            {
                "schema": "dev-flow-v4-handler-result/v1",
                "role": role,
                "authorized": True,
            },
        )
        rejected = dict(request)
        rejected.pop(next(iter(VALID_REQUESTS[role])))
        with self.assertRaises(ValueError):
            executor(rejected, ())
        with self.assertRaises(ValueError):
            executor(request, ("ambient-capability",))
        return result

    def test_every_direct_v4_handler_executes_and_fails_closed(self) -> None:
        for role in VALID_REQUESTS:
            with self.subTest(role=role):
                self._call(role)

    def test_each_retained_settlement_recovery_class_executes_closure(self) -> None:
        representatives = {}
        for bundle in self.services.catalog.bundles.values():
            for edge in bundle.action_edges:
                for effect in edge["effects"]:
                    key = (
                        effect["settlement"],
                        effect["recovery"]["mode"],
                    )
                    representatives.setdefault(key, (edge, effect))
        self.assertEqual(
            set(representatives),
            {
                ("synchronous-quiescence", "re-evaluate/v1"),
                (
                    "synchronous-quiescence",
                    "observe-or-quarantine/v1",
                ),
                (
                    "asynchronous-handoff",
                    "observe-or-quarantine/v1",
                ),
            },
        )
        for classification, (edge, effect) in representatives.items():
            with self.subTest(classification=classification, edge=edge["id"]):
                self.assertEqual(
                    effect["receipt"], "dev-flow-action-receipt/v1"
                )
                self.assertEqual(
                    effect["recovery"]["redispatch"], "forbidden"
                )
                for role in (
                    "dispatch",
                    "observation",
                    "settlement",
                    "unresolved",
                ):
                    self._call(role)

        _plan, assignment = self.start_orchestration_assignment()
        self.assertIn(
            assignment["assignment_id"],
            self.orchestration_state()["orchestration"]["dispatch"],
        )
        revoked = self.service.revoke_manager(
            self.orchestration_task_id,
            expected_revision=int(
                self.orchestration_state()["revision"]
            ),
            capability_id=self.capability_id,
            reason="focused-recovery-class-coverage",
            revocation_audit_sha256=(
                "9" * 64
            ),
            operator_confirmed=True,
            data_dir=self.data_dir,
        )
        self.assertEqual(
            revoked.event_type,
            "manager_capability_revoked",
        )
        self.assertIsNotNone(
            self.orchestration_state()["orchestration"][
                "manager_capabilities"
            ][self.capability_id]["revoked_at_wall_ns"]
        )
        archives = list(
            (
                self.orchestration_task_dir
                / "action-executions"
                / "archive"
            ).rglob("*.json")
        )
        self.assertTrue(archives)
        archived_text = "\n".join(
            path.read_text(encoding="utf-8") for path in archives
        )
        for operation_id in (
            "manager.capability.authorize",
            "orchestration.dispatch.handoff",
        ):
            self.assertIn(operation_id, archived_text)

    def test_real_transaction_recovery_never_redispatches(self) -> None:
        n = self.namespace
        with n["_task_lock"](self.orchestration_task_dir):
            state = n["_finish_loaded_state"](
                self.orchestration_task_dir / "state.json",
                n["_read_task_state_structural_snapshot"](
                    self.orchestration_task_dir / "state.json"
                ),
            )
            edge = n["resolve_v4_node_action_edge"](
                state, "preflight", selector="initial"
            )
            outcome = n["ActionOutcome"](
                edge["trigger"]["id"],
                edge["id"],
                evidence_records=(
                    {"validator": "focused-transaction/v1"},
                ),
                proposed_state_delta={
                    "set": {
                        "/preflight": {"status": "ready"},
                        "/repositories": [],
                        "/risk_assessment": {"level": "low"},
                    },
                    "remove": [],
                    "operations": [],
                },
                audit_facts=(
                    n["AuditFact"](
                        "focused-transaction-validator-accepted",
                        {"validator": "focused-transaction/v1"},
                    ),
                ),
            )
            provisional = n["WorkflowActionInvocation"](
                kind="node",
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "focused-transaction/v1"},
            )
            preview = n["evaluate_v4_node_action"](
                state,
                public_command=provisional.public_command,
                selector=provisional.selector,
                action_outcome=provisional.action_outcome,
                action_parameters=provisional.action_parameters,
                evidence=provisional.evidence,
                preview=True,
            )
        invocation = dataclasses.replace(
            provisional,
            confirm_intent=preview.intent["intent_id"],
        )
        authorization = n["WorkflowActionAuthorization"](
            kind="operator",
            authorization_sha256="a" * 64,
            capability_sha256=None,
            request_nonce_sha256="b" * 64,
            principal="operator:focused",
            ownership_sha256="c" * 64,
            registry_state_sha256="d" * 64,
            reauthenticate=lambda: None,
        )
        effect = n["WorkflowActionEffectBinding"](
            effect_id="full.intake.preflight.v1.effect",
            kind="filesystem",
            scope_kinds=("repository", "task"),
            scopes={
                "repository_ids": ["repo-a"],
                "node_ids": [],
                "worktree_ids": [],
                "lease_ids": [],
                "paths": [],
                "external_resources": [],
            },
            safe_inputs={"mode": "focused-transaction"},
            attempt_id="attempt-1",
        )
        dispatches = []

        def dispatcher(context):
            dispatches.append(context.plan.claim_id)
            return n["WorkflowActionEffectObservation"](
                task_id=context.plan.task_id,
                execution_id=context.plan.execution_id,
                effect_id=context.plan.effect_id,
                claim_id=context.plan.claim_id,
                attempt_id=context.plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256="e" * 64,
            )

        def fail_after_dispatch(stage: str) -> None:
            if stage == "after-dispatch":
                raise _InjectedEffectFailure(stage)

        with self.assertRaises(_InjectedEffectFailure):
            n["execute_v4_workflow_action_transaction"](
                state,
                self.orchestration_task_dir,
                invocation,
                authorization=authorization,
                effect_binding=effect,
                execution_id="focused-lost-dispatch",
                dispatcher=dispatcher,
                failure_hook=fail_after_dispatch,
            )
        recovered = n["recover_v4_workflow_action_transaction"](
            self.orchestration_task_dir,
            "focused-lost-dispatch",
            authorization=authorization,
        )
        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(len(dispatches), 1)
        self.assertNotIn(
            "dispatcher",
            inspect.signature(
                n["recover_v4_workflow_action_transaction"]
            ).parameters,
        )
        self.assertEqual(
            self.orchestration_state()["revision"],
            state["revision"],
        )

    def test_bounded_hostless_unresolved_path_never_redispatches(self) -> None:
        result = self._call("unresolved")
        self.assertTrue(result["authorized"])
        executor = self.services.registries.executors.resolve_callable(
            "executor.v4-unresolved/v2", "v2", "dispatcher"
        )
        with self.assertRaisesRegex(ValueError, "remain blocked"):
            executor(
                {
                    "schema": "dev-flow-v4-handler-request/v1",
                    "role": "unresolved",
                    "scope_blocked": True,
                    "redispatch": True,
                },
                (),
            )


if __name__ == "__main__":
    unittest.main()
