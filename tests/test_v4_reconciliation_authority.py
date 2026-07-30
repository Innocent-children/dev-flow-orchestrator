from __future__ import annotations

import copy
import hashlib
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import dev_flow


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scopes() -> dict[str, list[str]]:
    return {
        "repository_ids": ["repo-1"],
        "node_ids": [],
        "worktree_ids": [],
        "lease_ids": [],
        "paths": [],
        "external_resources": [],
    }


def _request() -> object:
    return dev_flow.WorkflowActionReconciliationRequest(
        task_id="task-v4",
        workflow_id="full",
        workflow_version="4",
        workflow_bundle_sha256=_digest("bundle"),
        action_edge_id="full.action.v4",
        target_execution_id="target-v4",
        effect_id="effect-v4",
        scopes=_scopes(),
        current_task_revision=12,
        attempt_id="reconcile-v4",
        recovery_action_id="control.reconcile/v1",
        authorization_kind="manager",
        authorization_sha256=_digest("authorization"),
        capability_sha256=_digest("capability"),
        gate_sha256=_digest("gate"),
        request_nonce_sha256=_digest("nonce"),
        engine_proof_sha256=_digest("engine"),
        principal="manager:v4",
        expected_index=dev_flow.CASToken(8, _digest("index")),
        expected_journal=dev_flow.CASToken(
            6, _digest("target-journal")
        ),
    )


def _target() -> dict[str, object]:
    return {
        "task_id": "task-v4",
        "execution_id": "target-v4",
        "record_sha256": _digest("target-journal"),
        "receipt": None,
    }


def _containments() -> tuple[dict[str, object], ...]:
    return (
        {
            "task_id": "task-v4",
            "execution_id": "target-v4",
            "effect_id": "effect-v4",
            "phase": "CLOSED",
            "record_sha256": _digest("containment"),
        },
    )


class V4LiveAbandonmentAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = _request()
        self.target = _target()
        self.containments = _containments()

    def _decision(self, proof: object, challenge: object) -> str:
        payload = dev_flow._workflow_reconcile_consume_proof(
            proof, challenge._challenge_id
        )
        return str(payload["decision"])

    def test_caller_digests_cannot_authorize_v4_abandonment(self) -> None:
        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request, self.target, self.containments
        )
        with self.assertRaises(
            dev_flow.WorkflowActionReconciliationError
        ) as raised:
            challenge.abandoned(
                quiescence_evidence_sha256=_digest("quiet"),
                no_business_outcome_evidence_sha256=_digest("absent"),
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_CALLER_AUTHORITY_FORBIDDEN",
        )
        evidence = {
            "schema": dev_flow._ACTION_RECOVERY_EVIDENCE_SCHEMA,
            "outcome": "ABANDONED",
            "quiescence_evidence_sha256": _digest("quiet"),
            "no_business_outcome_evidence_sha256": _digest("absent"),
        }
        cli_challenge = (
            dev_flow.WorkflowActionReconciliationChallenge(
                self.request,
                self.target,
                self.containments,
                live_abandonment_observer=lambda _challenge: True,
            )
        )
        with self.assertRaises(dev_flow.FlowError) as cli_raised:
            dev_flow._action_recovery_verifier(
                evidence, "effect-v4"
            )(cli_challenge)
        self.assertEqual(
            cli_raised.exception.code,
            "ACTION_RECOVERY_CALLER_AUTHORITY_FORBIDDEN",
        )

    def test_missing_live_observer_fails_closed(self) -> None:
        evidence = {
            "schema": dev_flow._ACTION_RECOVERY_EVIDENCE_SCHEMA,
            "outcome": "ABANDONED",
        }
        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request, self.target, self.containments
        )
        proof = dev_flow._action_recovery_verifier(
            evidence, "effect-v4"
        )(challenge)
        self.assertEqual(
            self._decision(proof, challenge), "UNRESOLVED"
        )

    def test_exact_live_observation_is_opaque_and_one_shot(self) -> None:
        issued: list[object] = []

        def observer(observation_challenge: object) -> object:
            observation = observation_challenge.confirm(
                request=observation_challenge.request,
                target=observation_challenge.target,
                containments=observation_challenge.containments,
                observed_quiescence="QUIESCENT",
                observed_business_outcome="ABSENT",
                observation_evidence_sha256=_digest(
                    "live-controller-observation"
                ),
            )
            issued.append(observation)
            return observation

        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request,
            self.target,
            self.containments,
            live_abandonment_observer=observer,
        )
        proof = challenge.abandoned()
        self.assertEqual(self._decision(proof, challenge), "ABANDONED")
        with self.assertRaises(TypeError):
            copy.copy(issued[0])
        with self.assertRaises(TypeError):
            pickle.dumps(issued[0])
        with self.assertRaises(
            dev_flow.WorkflowActionReconciliationError
        ):
            dev_flow._workflow_reconcile_consume_live_observation(
                issued[0]
            )

    def test_observer_cannot_substitute_target(self) -> None:
        def observer(observation_challenge: object) -> object:
            changed = observation_challenge.target
            changed["record_sha256"] = _digest("another-target")
            return observation_challenge.confirm(
                request=observation_challenge.request,
                target=changed,
                containments=observation_challenge.containments,
                observed_quiescence="QUIESCENT",
                observed_business_outcome="ABSENT",
                observation_evidence_sha256=_digest(
                    "live-controller-observation"
                ),
            )

        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request,
            self.target,
            self.containments,
            live_abandonment_observer=observer,
        )
        with self.assertRaises(
            dev_flow.WorkflowActionReconciliationError
        ) as raised:
            challenge.abandoned()
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_MISMATCH",
        )

    def test_boolean_or_mapping_observation_cannot_authorize(self) -> None:
        for fake in (
            True,
            {
                "quiescent": True,
                "business_outcome_absent": True,
                "sha256": _digest("caller"),
            },
        ):
            with self.subTest(fake=type(fake).__name__):
                challenge = (
                    dev_flow.WorkflowActionReconciliationChallenge(
                        self.request,
                        self.target,
                        self.containments,
                        live_abandonment_observer=lambda _challenge: fake,
                    )
                )
                with self.assertRaises(
                    dev_flow.WorkflowActionReconciliationError
                ) as raised:
                    challenge.abandoned()
                self.assertEqual(
                    raised.exception.code,
                    (
                        "WORKFLOW_ACTION_RECONCILIATION_"
                        "LIVE_OBSERVATION_REQUIRED"
                    ),
                )

    def test_live_observer_must_affirm_absent_outcome(self) -> None:
        def observer(observation_challenge: object) -> object:
            return observation_challenge.confirm(
                request=observation_challenge.request,
                target=observation_challenge.target,
                containments=observation_challenge.containments,
                observed_quiescence="QUIESCENT",
                observed_business_outcome="UNKNOWN",
                observation_evidence_sha256=_digest("live-unknown"),
            )

        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request,
            self.target,
            self.containments,
            live_abandonment_observer=observer,
        )
        with self.assertRaises(
            dev_flow.WorkflowActionReconciliationError
        ) as raised:
            challenge.abandoned()
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_INCOMPLETE",
        )


class V4OperatorInterventionResponseTests(unittest.TestCase):
    def _response(
        self,
        workflow_version: str,
        *,
        effect_records: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        result = dev_flow.WorkflowActionReconciliationResult(
            status="UNRESOLVED",
            target_execution_id="target-v4",
            attempt_id="reconcile-v4",
            attempt={
                "outcome": {
                    "recovery_event_sha256": None,
                    "outbox_sha256": None,
                    "task_commit_revision": None,
                }
            },
            index={},
            archive_path=None,
            dispatcher_invocations=0,
            blocked=True,
        )
        target = {
            "execution_id": "target-v4",
            "bindings": {
                "workflow_version": workflow_version,
                "scopes": _scopes(),
            },
            "effects": (
                effect_records
                if effect_records is not None
                else [
                    {
                        "effect_id": "effect-b",
                        "claim_id": "claim-b",
                    },
                    {
                        "effect_id": "effect-a",
                        "claim_id": "claim-a",
                    },
                ]
            ),
        }
        store = mock.Mock()
        store.read_active_journal.return_value = target
        with (
            mock.patch.object(
                dev_flow, "ActionExecutionStore", return_value=store
            ),
            mock.patch.object(
                dev_flow,
                "load_state",
                return_value={"task_id": "task-v4", "revision": 12},
            ),
        ):
            return dev_flow._action_recovery_response(
                Path("/unused/task-v4"),
                result,
                manager_secret="not-output",
            )

    def test_v4_unresolved_returns_bounded_intervention_packet(
        self,
    ) -> None:
        response = self._response("4")
        self.assertEqual(
            response["schema"],
            "dev-flow-v4-action-reconciliation-cli-result/v1",
        )
        self.assertEqual(
            response["operator_intervention"],
            {
                "schema": "dev-flow-v4-operator-intervention/v1",
                "required": True,
                "reason": "TRUSTED_HOST_AUTHORITY_UNAVAILABLE",
                "target_execution_id": "target-v4",
                "effect_ids": ["effect-a", "effect-b"],
                "affected_scopes": _scopes(),
                "allowed_resume_conditions": [
                    "authenticated_original_runtime",
                    "verifiable_stored_receipt",
                    "trusted_host_recovery_authority",
                ],
                "automatic_redispatch": False,
                "automatic_compensation": False,
                "automatic_unblock": False,
                "caller_assertion_can_unblock": False,
            },
        )
        self.assertLessEqual(
            len(
                dev_flow.semantic_json_bytes(
                    response["operator_intervention"]
                )
            ),
            dev_flow._ACTION_RECOVERY_MAX_OPERATOR_INTERVENTION_BYTES,
        )
        self.assertNotIn("not-output", repr(response))

    def test_v4_intervention_overflow_fails_closed_with_inspect_locator(
        self,
    ) -> None:
        base_effect_id = "effect-boundary"
        response = self._response(
            "4",
            effect_records=[
                {
                    "effect_id": base_effect_id,
                    "claim_id": "claim-boundary",
                }
            ],
        )
        base_size = len(
            dev_flow.semantic_json_bytes(
                response["operator_intervention"]
            )
        )
        limit = (
            dev_flow._ACTION_RECOVERY_MAX_OPERATOR_INTERVENTION_BYTES
        )
        boundary_effect_id = (
            base_effect_id + "x" * (limit - base_size)
        )
        boundary = self._response(
            "4",
            effect_records=[
                {
                    "effect_id": boundary_effect_id,
                    "claim_id": "claim-boundary",
                }
            ],
        )
        self.assertEqual(
            len(
                dev_flow.semantic_json_bytes(
                    boundary["operator_intervention"]
                )
            ),
            limit,
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            self._response(
                "4",
                effect_records=[
                    {
                        "effect_id": boundary_effect_id + "x",
                        "claim_id": "claim-boundary",
                    }
                ],
            )
        self.assertEqual(
            raised.exception.code,
            "ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE",
        )
        self.assertEqual(
            raised.exception.details["target_execution_id"],
            "target-v4",
        )
        self.assertEqual(
            raised.exception.details["inspect_command"],
            "action-recovery-inspect",
        )
        self.assertEqual(
            raised.exception.details["actual_bytes"],
            limit + 1,
        )
        self.assertEqual(
            raised.exception.details["limit_bytes"],
            limit,
        )

    def test_v4_intervention_rejects_corrupt_durable_effect_graph(
        self,
    ) -> None:
        with self.assertRaises(dev_flow.FlowError) as raised:
            self._response("4", effect_records=[])
        self.assertEqual(
            raised.exception.code,
            "ACTION_RECOVERY_RESULT_INVALID",
        )
        self.assertEqual(
            raised.exception.details,
            {
                "target_execution_id": "target-v4",
                "inspect_command": "action-recovery-inspect",
            },
        )

    def test_v3_result_schema_and_shape_remain_compatible(
        self,
    ) -> None:
        response = self._response("3")
        self.assertEqual(
            response["schema"],
            "dev-flow-v3-action-reconciliation-cli-result/v1",
        )
        self.assertEqual(
            set(response),
            {
                "schema",
                "task_id",
                "target_execution_id",
                "attempt_id",
                "status",
                "blocked",
                "target_dispatcher_invocations",
                "original_dispatch_count",
                "compensation_dispatch_count",
                "event_sha256",
                "outbox_sha256",
                "revision",
                "archive_path",
                "compensation_execution_id",
            },
        )


class V4CompensationBridgeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temporary.name).resolve()
        (self.task_dir / "compensation-targets").mkdir()
        self.candidate = (
            self.task_dir / "compensation-targets" / "candidate.bin"
        )
        self.candidate.write_bytes(b"controller-owned")
        self.request = _request()
        expected = hashlib.sha256(b"controller-owned").hexdigest()
        self.plan = dev_flow.WorkflowActionCompensationPlan(
            action_id=(
                dev_flow._ACTION_RECOVERY_COMPENSATION_FILE_ACTION
            ),
            effect_id="effect-v4",
            safe_inputs={
                "task_relative_path": (
                    "compensation-targets/candidate.bin"
                ),
                "expected_sha256": expected,
            },
            postcondition_contract_sha256=(
                dev_flow.action_recovery_controller_file_contract_sha256()
            ),
        )
        self.permit = dev_flow.CompensationDispatchPlan(
            task_id="task-v4",
            execution_id="compensation-v4",
            target_execution_id="target-v4",
            authorization_attempt_id="reconcile-v4",
            claim_id="compensation-v4-claim",
            journal_revision=3,
            journal_record_sha256=_digest("compensation-journal"),
            index_revision=9,
            index_record_sha256=_digest("compensation-index"),
            compensation_plan=self.plan.as_dict(),
            required_lock_claims=(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _approve(
        challenge: object, request: object, target: object
    ) -> object:
        return challenge.approve(request=request, target=target)

    def test_missing_host_bridge_becomes_unresolved(self) -> None:
        evidence = {
            "schema": dev_flow._ACTION_RECOVERY_EVIDENCE_SCHEMA,
            "outcome": "COMPENSATED",
            "compensation_execution_id": "compensation-v4",
            "compensation_plan": self.plan.as_dict(),
        }
        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request, _target(), _containments()
        )
        proof = dev_flow._action_recovery_verifier(
            evidence, "effect-v4"
        )(challenge)
        payload = dev_flow._workflow_reconcile_consume_proof(
            proof, challenge._challenge_id
        )
        self.assertEqual(payload["decision"], "UNRESOLVED")

    def test_caller_approval_objects_cannot_authorize_v4(self) -> None:
        target = _target()
        approval = dev_flow.WorkflowActionCompensationApproval(
            authority="host",
            principal="host:caller",
            approval_sha256=_digest("caller-host"),
            compensation_plan_sha256=self.plan.plan_sha256,
            target_journal_sha256=str(target["record_sha256"]),
        )
        workflow = dev_flow.WorkflowActionCompensationApproval(
            authority="workflow",
            principal="workflow:caller",
            approval_sha256=_digest("caller-workflow"),
            compensation_plan_sha256=self.plan.plan_sha256,
            target_journal_sha256=str(target["record_sha256"]),
        )
        challenge = dev_flow.WorkflowActionReconciliationChallenge(
            self.request, target, _containments()
        )
        with self.assertRaises(
            dev_flow.WorkflowActionReconciliationError
        ) as raised:
            challenge.compensated(
                compensation_execution_id="compensation-v4",
                compensation_plan=self.plan,
                approvals=(approval, workflow),
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_CALLER_AUTHORITY_FORBIDDEN",
        )

    def test_live_host_grant_is_consumed_immediately_before_remove(
        self,
    ) -> None:
        observation = dev_flow._action_recovery_dispatch_compensation(
            self.task_dir,
            self.permit,
            workflow_request=self.request,
            host_approval_callback=self._approve,
        )
        self.assertIsInstance(
            observation,
            dev_flow.WorkflowActionCompensationObservation,
        )
        self.assertFalse(self.candidate.exists())

    def test_host_denial_does_not_invoke_provider(self) -> None:
        with self.assertRaises(dev_flow.ExternalWriteError) as raised:
            dev_flow._action_recovery_dispatch_compensation(
                self.task_dir,
                self.permit,
                workflow_request=self.request,
                host_approval_callback=lambda *_args: True,
            )
        self.assertEqual(
            raised.exception.code, "CURRENT_HOST_APPROVAL_DENIED"
        )
        self.assertTrue(self.candidate.exists())

    def test_v4_dispatcher_wrapper_is_opaque(self) -> None:
        dispatcher = (
            dev_flow._workflow_reconcile_wrap_compensation_dispatcher(
                lambda permit: permit
            )
        )
        self.assertIs(
            type(dispatcher),
            dev_flow.WorkflowActionCompensationDispatcher,
        )
        with self.assertRaises(TypeError):
            copy.copy(dispatcher)
        with self.assertRaises(TypeError):
            pickle.dumps(dispatcher)

if __name__ == "__main__":
    unittest.main()
