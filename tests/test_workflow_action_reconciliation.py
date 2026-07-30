from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
import time

from scripts.dev_flow_parts import action_execution_journal as journal
from tests.dev_flow_test_case import dev_flow
from tests.test_action_execution_journal import MANAGER_SECRET, _sha
from tests.test_action_execution_journal import _compensation_plan
from tests.test_action_execution_journal import _effect
from tests.test_action_execution_journal import _journal_core
from tests.test_action_execution_store import ActionExecutionStoreCase

reconcile = dev_flow


class _InjectedReconciliationFailure(RuntimeError):
    pass


def _crash_at(stage_to_fail: str):
    def fail(stage: str) -> None:
        if stage == stage_to_fail:
            raise _InjectedReconciliationFailure(stage)

    return fail


class WorkflowActionReconciliationTests(ActionExecutionStoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.task_dir = (
            Path(self.temporary.name) / "task-vector"
        ).resolve()
        self.task_dir.mkdir(mode=0o700)
        self.store = dev_flow.ActionExecutionStore(self.task_dir)
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": "task-vector",
            "revision": 7,
            "status": "INTAKE",
            "flow": "full",
            "repositories": [],
            "route": None,
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    "task-vector",
                    bundle,
                    execution_profile="single-repository",
                )
            ),
        }
        self.manager_secret = bytearray(b"R" * 32)
        self.manager_verifier = dev_flow.issue_manager_capability(
            task_id="task-vector",
            issued_for_task_revision=7,
            manager_session_id="reconciliation-manager",
            allowed_actions=dev_flow._manager_default_actions(state),
            ttl_ns=60_000_000_000,
            wall_time_ns=time.time_ns(),
            monotonic_time_ns=(
                dev_flow._manager_system_monotonic_ns()
            ),
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="mcp-secret-channel",
            operator_confirmation_sha256="6" * 64,
            issuance_audit_sha256="7" * 64,
            manager_secret=self.manager_secret,
        )
        orchestration = copy.deepcopy(
            state.get("orchestration", {})
        )
        assert isinstance(orchestration, dict)
        orchestration.update(
            {
                "schema": "dev-flow-orchestration-state/v1",
                "manager_capabilities": {
                    self.manager_verifier.capability_id: (
                        self.manager_verifier.as_persistent_dict()
                    )
                },
            }
        )
        state["orchestration"] = orchestration
        dev_flow._atomic_write_json(
            self.task_dir / "state.json", state
        )
        self.state = state
        self.action_outcome = dev_flow.ActionOutcome(
            "full.intake.preflight.v1",
            "full.action.intake.preflight.v1",
            evidence_records=(
                {"validator": "reconciliation-test/v1"},
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
                dev_flow.AuditFact(
                    "reconciliation-test-evidence",
                    {"validator": "reconciliation-test/v1"},
                ),
            ),
        )
        self.action_parameters = {"mode": "initial"}
        self.evidence = {"validator": "reconciliation-test/v1"}
        with dev_flow._task_lock(self.task_dir):
            self.preview = dev_flow.evaluate_v3_node_action(
                state,
                public_command="preflight",
                selector="initial",
                action_outcome=self.action_outcome,
                action_parameters=self.action_parameters,
                evidence=self.evidence,
                preview=True,
            )
        self.assertEqual(
            self.preview.edge_id, "full.action.intake.preflight.v1"
        )
        self.live_evaluation = None
        self.manager_requests: dict[str, dict[str, object]] = {}
        self.manager_operation_fingerprints: dict[str, str] = {}
        self.effect_id = "full.intake.preflight.v1.effect"

    def _target_journal(self) -> dict[str, object]:
        core = _journal_core(
            effects=[_effect(self.effect_id)]
        )
        bindings = core["bindings"]
        assert isinstance(bindings, dict)
        workflow_ref = self.state["workflow_ref"]
        assert isinstance(workflow_ref, dict)
        bindings.update(
            {
                "workflow_id": workflow_ref["id"],
                "workflow_version": str(workflow_ref["version"]),
                "workflow_bundle_sha256": workflow_ref[
                    "bundle_sha256"
                ],
                "action_edge_id": self.preview.edge_id,
                "authorization_action_edge_id": self.preview.edge_id,
                "completion_edge_id": self.preview.edge_id,
                "handler_id": "executor.deterministic/v1",
                "candidate_after_sha256": (
                    dev_flow._workflow_action_candidate_binding_sha256(
                        self.preview, "exact-revision"
                    )
                ),
                "pre_effect_state_sha256": dev_flow._sha256_contract(
                    self.state
                ),
            }
        )
        return journal.seal_journal(
            core, manager_secret=MANAGER_SECRET
        )

    def _live_evaluator(
        self,
        context: reconcile.WorkflowActionReconciliationCommitContext,
    ) -> reconcile.WorkflowActionReconciliationCommitPlan:
        self.assertEqual(
            context.pre_effect_state["revision"],
            self.state["revision"],
        )
        evaluation = dev_flow.evaluate_v3_node_action(
            context.current_state,
            public_command="preflight",
            selector="initial",
            action_outcome=self.action_outcome,
            action_parameters=self.action_parameters,
            evidence=self.evidence,
            confirm_intent=self.preview.intent["intent_id"],
            preview=False,
            receipt_context=dev_flow.WorkflowActionReceiptContext(
                index=self.receipt_verified_index,
                journal=self.receipt_verified_journal,
                expected_index=dev_flow.cas_token(
                    self.receipt_verified_index
                ),
                reauthenticate=lambda: MANAGER_SECRET,
                pre_effect_state=context.pre_effect_state,
                neutralize_manager_nonce=True,
            ),
        )
        return reconcile.WorkflowActionReconciliationCommitPlan(
            evaluation
        )

    def _commit_authorizer(
        self,
        context: reconcile.WorkflowActionReconciliationCommitContext,
    ) -> object:
        request = self.manager_requests[
            context.request.attempt_id
        ]
        return dev_flow._manager_authority_context(
            request=request,
            action_id="task.preflight",
            secret_resolver=lambda: bytearray(self.manager_secret),
            operation_fingerprint_sha256=(
                self.manager_operation_fingerprints[
                    context.request.attempt_id
                ]
            ),
        )

    def _prepare_manager_evaluation(
        self,
        attempt_id: str,
        manager_request: dict[str, object],
        index: dict[str, object],
        current: dict[str, object],
    ) -> object:
        operation_fingerprint = _sha(
            "reconciliation-operation:" + attempt_id
        )
        self.manager_requests[attempt_id] = manager_request
        self.manager_operation_fingerprints[attempt_id] = (
            operation_fingerprint
        )
        claims = dev_flow.action_execution_required_lock_claims(
            current
        )
        with dev_flow._manager_authority_context(
            request=manager_request,
            action_id="task.preflight",
            secret_resolver=lambda: bytearray(self.manager_secret),
            operation_fingerprint_sha256=operation_fingerprint,
        ):
            with dev_flow._task_lock(self.task_dir):
                with dev_flow._workflow_tx_ordered_locks(
                    self.task_dir, claims
                ):
                    invocation = (
                        dev_flow._manager_authority_context_var.get()
                    )
                    dev_flow.manager_process_commit_gate_v1(
                        self.state,
                        self.state,
                        "manager_effect_preauthorized",
                        _effect_lifecycle=(
                            "preauthorize",
                            "generic",
                        ),
                        _effect_package_action_id=(
                            invocation.package_action_id
                        ),
                    )
                    authorization = (
                        dev_flow
                        ._manager_workflow_action_authorization_v1(
                            self.state,
                            event_type="preflight_recorded",
                        )
                    )
                    evaluation_state = (
                        dev_flow._manager_engine_evaluation_state_v1(
                            self.state,
                            event_type="preflight_recorded",
                        )
                    )
                    if hasattr(
                        self, "receipt_verified_journal"
                    ):
                        self.live_evaluation = (
                            dev_flow.evaluate_v3_node_action(
                            evaluation_state,
                            public_command="preflight",
                            selector="initial",
                            action_outcome=self.action_outcome,
                            action_parameters=self.action_parameters,
                            evidence=self.evidence,
                            confirm_intent=self.preview.intent[
                                "intent_id"
                            ],
                            preview=True,
                            receipt_context=(
                                dev_flow.WorkflowActionReceiptContext(
                                    index=index,
                                    journal=current,
                                    expected_index=(
                                        dev_flow.cas_token(index)
                                    ),
                                    reauthenticate=(
                                        lambda: MANAGER_SECRET
                                    ),
                                    pre_effect_state=self.state,
                                    neutralize_manager_nonce=True,
                                )
                            ),
                            )
                        )
        return authorization

    def _assert_compensation_adapter_unlocked(self) -> None:
        forbidden = [
            capability
            for capability in (
                dev_flow._workflow_tx_live_lock_capabilities()
            )
            if capability.get("lock_name")
            in {
                "state.lock",
                "workspace-registry.lock",
                "action-execution-index.lock",
            }
        ]
        self.assertEqual(forbidden, [])

    def _authoritative_task_bytes(
        self,
    ) -> dict[str, bytes | None]:
        return {
            name: (
                (self.task_dir / name).read_bytes()
                if (self.task_dir / name).exists()
                else None
            )
            for name in (
                "state.json",
                "events.jsonl",
                "pending-events.json",
            )
        }

    def _quarantined(
        self,
        *,
        with_complete_receipt: bool,
    ) -> tuple[dict[str, object], dict[str, object]]:
        index, current = self.persist_initial(
            self._target_journal()
        )
        self.store.claim_for_dispatch(
            str(current["execution_id"]),
            self.effect_id,
            "claim-store",
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        index = self.store.read_index(
            expected_task_id=str(current["task_id"])
        )
        current = self.store.read_active_journal(
            str(current["execution_id"]),
            manager_secret=MANAGER_SECRET,
        )
        containment = journal.new_containment(
            current,
            self.effect_id,
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        running = journal.advance_effect_phase(
            current,
            self.effect_id,
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                containment["record_sha256"]
            ),
        )
        index, current = self.persist_update(
            index, current, running
        )
        quiesced_containment = journal.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=_sha("quiescence"),
        )
        quiesced_containment = self.persist_containment(
            index,
            current,
            quiesced_containment,
            before=containment,
        )
        quiesced = journal.advance_effect_phase(
            current,
            self.effect_id,
            "QUIESCED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                quiesced_containment["record_sha256"]
            ),
            receipt_sha256=_sha("effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, quiesced
        )
        closed = journal.advance_containment(
            quiesced_containment, "CLOSED"
        )
        closed = self.persist_containment(
            index,
            current,
            closed,
            before=quiesced_containment,
        )
        verified = journal.advance_effect_phase(
            current,
            self.effect_id,
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(closed["record_sha256"]),
            receipt_sha256=_sha("effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, verified
        )
        settled = journal.advance_global_settlement(
            current, manager_secret=MANAGER_SECRET
        )
        index, current = self.persist_update(
            index, current, settled
        )
        if with_complete_receipt:
            receipt = dev_flow.build_v3_workflow_action_receipt(
                self.state,
                self.preview,
                self.task_dir,
                execution_id=str(current["execution_id"]),
                effect_receipt_sha256=_sha(
                    "complete-action-receipt"
                ),
            )
            receipt_verified = journal.verify_receipt_intent(
                current,
                receipt,
                manager_secret=MANAGER_SECRET,
            )
            index, current = self.persist_update(
                index, current, receipt_verified
            )
            self.receipt_verified_index = index
            self.receipt_verified_journal = current
        quarantined = journal.quarantine_journal(
            current,
            reason_code="reconciliation-test",
            details_sha256=_sha("quarantine-details"),
            effect_id=self.effect_id,
            receipt_sha256=_sha("effect-receipt"),
            manager_secret=MANAGER_SECRET,
        )
        return self.persist_update(index, current, quarantined)

    def _request(
        self,
        index: dict[str, object],
        current: dict[str, object],
        *,
        attempt_id: str = "reconcile-1",
        nonce: str = "fresh-reconciliation-nonce",
        replaces_attempt_id: str | None = None,
        live_authority: bool = False,
    ) -> reconcile.WorkflowActionReconciliationRequest:
        bindings = current["bindings"]
        assert isinstance(bindings, dict)
        manager_request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": self.manager_verifier.capability_id,
            "task_id": str(current["task_id"]),
            "manager_session_id": "reconciliation-manager",
            "action_id": "task.preflight",
            "expected_revision": int(bindings["task_revision"]),
            "request_nonce": _sha(nonce),
        }
        authorization = None
        if live_authority:
            authorization = self._prepare_manager_evaluation(
                attempt_id,
                manager_request,
                (
                    self.receipt_verified_index
                    if hasattr(self, "receipt_verified_index")
                    else index
                ),
                (
                    self.receipt_verified_journal
                    if hasattr(
                        self, "receipt_verified_journal"
                    )
                    else current
                ),
            )
        else:
            self.manager_requests[attempt_id] = manager_request
            self.manager_operation_fingerprints[attempt_id] = _sha(
                "reconciliation-operation:" + attempt_id
            )
        provisional = reconcile.WorkflowActionReconciliationRequest(
            task_id=str(current["task_id"]),
            workflow_id=str(bindings["workflow_id"]),
            workflow_version=str(bindings["workflow_version"]),
            workflow_bundle_sha256=str(
                bindings["workflow_bundle_sha256"]
            ),
            action_edge_id=str(bindings["action_edge_id"]),
            target_execution_id=str(current["execution_id"]),
            effect_id=self.effect_id,
            scopes=copy.deepcopy(bindings["scopes"]),
            current_task_revision=int(bindings["task_revision"]),
            attempt_id=attempt_id,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=(
                authorization.authorization_sha256
                if authorization is not None
                else _sha(
                    "fresh-reconciliation-auth:" + attempt_id
                )
            ),
            capability_sha256=(
                authorization.capability_sha256
                if authorization is not None
                else _sha(
                    "fresh-reconciliation-capability:"
                    + attempt_id
                )
            ),
            gate_sha256=_sha(
                "fresh-reconciliation-gate:" + attempt_id
            ),
            request_nonce_sha256=(
                authorization.request_nonce_sha256
                if authorization is not None
                else dev_flow.manager_request_nonce_digest(
                    manager_request
                )
            ),
            engine_proof_sha256="0" * 64,
            principal=(
                authorization.principal
                if authorization is not None
                else "manager:reconciliation:" + attempt_id
            ),
            expected_index=reconcile.cas_token(index),
            expected_journal=reconcile.cas_token(current),
            replaces_attempt_id=replaces_attempt_id,
        )
        if (
            live_authority
            and not hasattr(self, "receipt_verified_journal")
        ):
            operation_fingerprint = (
                self.manager_operation_fingerprints[attempt_id]
            )
            claims = dev_flow.action_execution_required_lock_claims(
                current
            )
            with dev_flow._manager_authority_context(
                request=manager_request,
                action_id="task.preflight",
                secret_resolver=lambda: bytearray(
                    self.manager_secret
                ),
                operation_fingerprint_sha256=operation_fingerprint,
            ):
                with dev_flow._task_lock(self.task_dir):
                    with dev_flow._workflow_tx_ordered_locks(
                        self.task_dir, claims
                    ):
                        invocation = (
                            dev_flow
                            ._manager_authority_context_var.get()
                        )
                        dev_flow.manager_process_commit_gate_v1(
                            self.state,
                            self.state,
                            "manager_effect_preauthorized",
                            _effect_lifecycle=(
                                "preauthorize",
                                "generic",
                            ),
                            _effect_package_action_id=(
                                invocation.package_action_id
                            ),
                        )
                        evaluation_state = (
                            dev_flow
                            ._manager_engine_evaluation_state_v1(
                                self.state,
                                event_type="preflight_recorded",
                            )
                        )
                        self.live_evaluation = (
                            reconcile
                            .preview_v3_workflow_action_abandonment(
                                provisional,
                                evaluation_state,
                                current,
                            )
                        )
        return dataclasses.replace(
            provisional,
            engine_proof_sha256=(
                reconcile
                .workflow_action_reconciliation_engine_proof_sha256(
                    provisional,
                    (
                        self.live_evaluation
                        if self.live_evaluation is not None
                        else self.preview
                    ),
                )
            ),
        )

    def _compensation_plan(
        self,
    ) -> reconcile.WorkflowActionCompensationPlan:
        raw = _compensation_plan()
        return reconcile.WorkflowActionCompensationPlan(
            action_id=str(raw["action_id"]),
            effect_id=self.effect_id,
            safe_inputs=raw["safe_inputs"],
            postcondition_contract_sha256=str(
                raw["postcondition_contract_sha256"]
            ),
        )

    @staticmethod
    def _compensation_approvals(
        plan: reconcile.WorkflowActionCompensationPlan,
        target: dict[str, object],
        *,
        same_principal: bool = False,
        wrong_plan_binding: bool = False,
        wrong_target_binding: bool = False,
    ) -> tuple[
        reconcile.WorkflowActionCompensationApproval,
        reconcile.WorkflowActionCompensationApproval,
    ]:
        plan_sha256 = (
            _sha("wrong-compensation-plan")
            if wrong_plan_binding
            else plan.plan_sha256
        )
        target_sha256 = (
            _sha("wrong-compensation-target")
            if wrong_target_binding
            else str(target["record_sha256"])
        )
        host_principal = "host:approver"
        return (
            reconcile.WorkflowActionCompensationApproval(
                authority="host",
                principal=host_principal,
                approval_sha256=_sha("host-approval"),
                compensation_plan_sha256=plan_sha256,
                target_journal_sha256=target_sha256,
            ),
            reconcile.WorkflowActionCompensationApproval(
                authority="workflow",
                principal=(
                    host_principal
                    if same_principal
                    else "workflow:approver"
                ),
                approval_sha256=_sha("workflow-approval"),
                compensation_plan_sha256=plan_sha256,
                target_journal_sha256=target_sha256,
            ),
        )

    def _compensated(
        self,
        challenge: object,
        *,
        compensation_execution_id: str = "compensation-control",
        approvals: tuple[
            reconcile.WorkflowActionCompensationApproval, ...
        ]
        | None = None,
        plan: reconcile.WorkflowActionCompensationPlan | None = None,
    ) -> object:
        selected_plan = plan or self._compensation_plan()
        selected_approvals = approvals or self._compensation_approvals(
            selected_plan, challenge.target
        )
        return challenge.compensated(
            compensation_execution_id=compensation_execution_id,
            compensation_plan=selected_plan,
            approvals=selected_approvals,
        )

    @staticmethod
    def _accepted(challenge: object) -> object:
        target = challenge.target
        return challenge.accepted(
            complete_receipt=target["receipt"],
            postcondition_evidence_sha256=_sha(
                "accepted-postconditions"
            ),
        )

    @staticmethod
    def _abandoned(challenge: object) -> object:
        return challenge.abandoned(
            quiescence_evidence_sha256=_sha(
                "authenticated-quiescence"
            ),
            no_business_outcome_evidence_sha256=_sha(
                "no-business-outcome"
            ),
        )

    def test_accepted_reuses_complete_receipt_and_never_dispatches(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(
            index, current, live_authority=True
        )
        invocations: list[str] = []

        def verify(challenge: object) -> object:
            invocations.append(challenge.request.attempt_id)
            return self._accepted(challenge)

        result = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            request,
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=verify,
            commit_evaluator=self._live_evaluator,
            commit_authorizer=self._commit_authorizer,
        )

        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(result.dispatcher_invocations, 0)
        self.assertEqual(invocations, ["reconcile-1"])
        self.assertFalse(result.blocked)
        self.assertEqual(result.index["entries"], [])
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertEqual(
            result.attempt["bindings"]["target_receipt_sha256"],
            current["receipt"]["receipt_sha256"],
        )

    def test_missing_live_evaluator_is_zero_claim_and_zero_write(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        before = self.store.read_index()

        with self.assertRaises(
            reconcile.WorkflowActionReconciliationError
        ) as raised:
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                self._request(index, current),
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
            )

        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_EVALUATOR_REQUIRED",
        )
        self.assertEqual(self.store.read_index(), before)
        with self.assertRaises(Exception):
            self.store.read_reconciliation("reconcile-1")

    def test_engine_proof_must_bind_the_live_evaluation(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = dataclasses.replace(
            self._request(
                index, current, live_authority=True
            ),
            engine_proof_sha256=_sha("wrong-live-engine-proof"),
        )

        with self.assertRaises(
            reconcile.WorkflowActionReconciliationError
        ) as raised:
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
            )

        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_ENGINE_PROOF_MISMATCH",
        )
        self.assertEqual(
            self.store.read_reconciliation("reconcile-1")["phase"],
            "CLAIMED",
        )
        self.assertEqual(
            dev_flow.load_state(self.task_dir / "state.json")[
                "revision"
            ],
            7,
        )

    def test_abandoned_requires_closed_quiescence_and_no_receipt(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=False
        )
        result = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            self._request(
                index, current, live_authority=True
            ),
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=self._abandoned,
            commit_evaluator=(
                reconcile
                .evaluate_v3_workflow_action_abandonment
            ),
            commit_authorizer=self._commit_authorizer,
        )

        self.assertEqual(result.status, "ABANDONED")
        self.assertEqual(result.index["entries"], [])
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertEqual(
            result.attempt["outcome"]["proof_kind"],
            "no-outcome-quiescence",
        )

    def test_unresolved_attempt_remains_indexed_and_blocks_fresh_retry(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=False
        )
        request = self._request(index, current)
        captured: list[object] = []
        authoritative_before = self._authoritative_task_bytes()

        def unresolved(challenge: object) -> object:
            proof = challenge.unresolved(
                diagnostic_evidence_sha256=_sha(
                    "still-indeterminate"
                )
            )
            captured.append(proof)
            return proof

        result = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            request,
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=unresolved,
        )
        self.assertEqual(result.status, "UNRESOLVED")
        self.assertEqual(
            self._authoritative_task_bytes(),
            authoritative_before,
        )
        self.assertTrue(result.blocked)
        self.assertIsNone(result.archive_path)
        self.assertEqual(
            {
                item["execution_id"]
                for item in result.index["entries"]
            },
            {"execution-vector", "reconcile-1"},
        )
        with self.assertRaises(Exception):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=lambda challenge: captured[0],
            )
        target = self.store.read_active_journal(
            "execution-vector", manager_secret=MANAGER_SECRET
        )
        fresh = self._request(
            result.index,
            target,
            attempt_id="reconcile-2",
            nonce="second-fresh-reconciliation-nonce",
            replaces_attempt_id="reconcile-1",
        )
        rotated = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            fresh,
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=lambda challenge: challenge.unresolved(
                diagnostic_evidence_sha256=_sha("still-blocked")
            ),
        )
        self.assertEqual(
            {
                item["execution_id"]
                for item in rotated.index["entries"]
            },
            {"execution-vector", "reconcile-2"},
        )
        self.assertEqual(rotated.status, "UNRESOLVED")
        self.assertTrue(rotated.blocked)
        self.assertEqual(
            self.store.read_reconciliation_archive("reconcile-1"),
            result.attempt,
        )
        self.assertEqual(self.store.read_index(), rotated.index)

    def test_compensation_requires_exact_distinct_dual_approval_bindings(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(index, current)
        before = self.store.read_index()
        plan = self._compensation_plan()
        complete = self._compensation_approvals(plan, current)
        for approvals in (
            complete[:1],
            self._compensation_approvals(
                plan, current, same_principal=True
            ),
        ):
            with self.subTest(approvals=approvals):
                with self.assertRaises(
                    reconcile.WorkflowActionReconciliationError
                ) as raised:
                    reconcile.reconcile_v3_workflow_action_quarantine(
                        self.task_dir,
                        request,
                        reauthenticate=lambda: MANAGER_SECRET,
                        verifier=lambda challenge, approvals=approvals: (
                            self._compensated(
                                challenge,
                                approvals=approvals,
                                plan=plan,
                            )
                        ),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_ACTION_RECONCILIATION_"
                    "DUAL_APPROVAL_REQUIRED",
                )
                self.assertEqual(self.store.read_index(), before)

        for approvals in (
            self._compensation_approvals(
                plan, current, wrong_plan_binding=True
            ),
            self._compensation_approvals(
                plan, current, wrong_target_binding=True
            ),
        ):
            with self.subTest(approvals=approvals):
                with self.assertRaises(
                    reconcile.WorkflowActionReconciliationError
                ) as raised:
                    reconcile.reconcile_v3_workflow_action_quarantine(
                        self.task_dir,
                        request,
                        reauthenticate=lambda: MANAGER_SECRET,
                        verifier=lambda challenge, approvals=approvals: (
                            self._compensated(
                                challenge,
                                approvals=approvals,
                                plan=plan,
                            )
                        ),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_ACTION_RECONCILIATION_"
                    "COMPENSATION_APPROVAL_MISMATCH",
                )
                self.assertEqual(self.store.read_index(), before)

    def test_compensation_dispatches_once_and_unblocks_only_after_receipt(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        invocations: list[str] = []

        def dispatch(
            permit: object,
        ) -> reconcile.WorkflowActionCompensationObservation:
            self._assert_compensation_adapter_unlocked()
            invocations.append(permit.claim_id)
            return reconcile.WorkflowActionCompensationObservation(
                effect_receipt_sha256=_sha(
                    "compensation-effect-receipt"
                ),
                postcondition_proof_sha256=_sha(
                    "compensation-postcondition"
                ),
            )

        result = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            self._request(
                index, current, live_authority=True
            ),
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=self._compensated,
            commit_evaluator=self._live_evaluator,
            commit_authorizer=self._commit_authorizer,
            compensation_dispatcher=dispatch,
        )

        self.assertEqual(result.status, "COMPENSATED")
        self.assertEqual(result.dispatcher_invocations, 1)
        self.assertEqual(invocations, ["compensation-control-claim"])
        self.assertFalse(result.blocked)
        self.assertEqual(result.index["entries"], [])
        self.assertEqual(
            result.compensation_execution_id,
            "compensation-control",
        )
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertEqual(
            self.store.read_reconciliation_archive("reconcile-1"),
            result.attempt,
        )
        self.assertEqual(
            self.store.read_compensation_archive(
                "compensation-control"
            )["phase"],
            "COMMITTED",
        )

    def test_lost_compensation_response_remains_claimed_and_never_replays(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(index, current)
        invocations: list[str] = []

        def lost(permit: object) -> object:
            self._assert_compensation_adapter_unlocked()
            invocations.append(permit.claim_id)
            raise _InjectedReconciliationFailure("lost response")

        with self.assertRaises(
            reconcile.WorkflowActionReconciliationError
        ) as raised:
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._compensated,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                compensation_dispatcher=lost,
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_"
            "COMPENSATION_RESPONSE_UNKNOWN",
        )
        self.assertEqual(invocations, ["compensation-control-claim"])
        claimed = self.store.read_compensation(
            "compensation-control"
        )
        self.assertEqual(claimed["phase"], "CLAIMED")
        self.assertEqual(
            {
                item["execution_id"]
                for item in self.store.read_index()["entries"]
            },
            {"execution-vector", "compensation-control"},
        )
        with self.assertRaises(Exception):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._compensated,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                compensation_dispatcher=lost,
            )
        self.assertEqual(invocations, ["compensation-control-claim"])
        with self.assertRaises(Exception):
            reconcile.recover_v3_workflow_action_reconciliation(
                self.task_dir,
                "reconcile-1",
                reauthenticate=lambda: MANAGER_SECRET,
            )
        self.assertEqual(invocations, ["compensation-control-claim"])

    def test_invalid_compensation_receipt_keeps_claimed_scope_blocked(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        invocations: list[str] = []

        def invalid(permit: object) -> object:
            self._assert_compensation_adapter_unlocked()
            invocations.append(permit.claim_id)
            return {
                "effect_receipt_sha256": _sha("untyped-receipt"),
                "postcondition_proof_sha256": _sha("untyped-proof"),
            }

        with self.assertRaises(
            reconcile.WorkflowActionReconciliationError
        ) as raised:
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                self._request(index, current),
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._compensated,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                compensation_dispatcher=invalid,
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_"
            "COMPENSATION_RECEIPT_INVALID",
        )
        self.assertEqual(invocations, ["compensation-control-claim"])
        self.assertEqual(
            self.store.read_compensation(
                "compensation-control"
            )["phase"],
            "CLAIMED",
        )
        self.assertEqual(
            {
                item["execution_id"]
                for item in self.store.read_index()["entries"]
            },
            {"execution-vector", "compensation-control"},
        )

    def test_expiry_revocation_and_wrong_receipt_are_zero_write(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(index, current)
        before = self.store.read_index()
        for reason in (
            "AUTHORIZATION_EXPIRED",
            "AUTHORIZATION_REVOKED",
        ):
            with self.subTest(reason=reason):
                with self.assertRaises(
                    reconcile.WorkflowActionReconciliationError
                ) as raised:
                    reconcile.reconcile_v3_workflow_action_quarantine(
                        self.task_dir,
                        request,
                        reauthenticate=lambda: MANAGER_SECRET,
                        verifier=lambda challenge, reason=reason: (
                            self._reject(reason)
                        ),
                    )
                self.assertIn(reason, raised.exception.code)
                self.assertEqual(self.store.read_index(), before)

        def wrong_receipt(challenge: object) -> object:
            receipt = dict(challenge.target["receipt"])
            receipt["receipt_sha256"] = _sha("forged-receipt")
            return challenge.accepted(
                complete_receipt=receipt,
                postcondition_evidence_sha256=_sha("evidence"),
            )

        with self.assertRaises(
            reconcile.WorkflowActionReconciliationError
        ) as raised:
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=wrong_receipt,
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_RECONCILIATION_RECEIPT_MISMATCH",
        )
        self.assertEqual(self.store.read_index(), before)

    @staticmethod
    def _reject(reason: str) -> object:
        raise reconcile.WorkflowActionReconciliationAuthorityRejected(
            reason
        )

    def test_archive_failure_keeps_terminal_attempt_and_target_blocked(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(
            index, current, live_authority=True
        )

        with self.assertRaises(_InjectedReconciliationFailure):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                failure_hook=_crash_at("terminal-archive:before"),
            )
        after = self.store.read_index()
        self.assertEqual(
            {
                item["execution_id"] for item in after["entries"]
            },
            {"execution-vector", "reconcile-1"},
        )
        self.assertTrue(
            (
                self.task_dir
                / journal.action_execution_active_path(
                    "execution-vector"
                )
            ).is_file()
        )
        self.assertEqual(
            self.store.read_reconciliation("reconcile-1")["phase"],
            "ACCEPTED",
        )
        recovered = (
            reconcile.recover_v3_workflow_action_reconciliation(
                self.task_dir,
                "reconcile-1",
                reauthenticate=lambda: MANAGER_SECRET,
            )
        )
        self.assertEqual(recovered.status, "ACCEPTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.index["entries"], [])
        self.assertTrue(Path(recovered.archive_path).is_file())

    def test_after_archive_restart_is_idempotent_and_zero_dispatch(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        with self.assertRaises(_InjectedReconciliationFailure):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                self._request(
                    index, current, live_authority=True
                ),
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                failure_hook=_crash_at("after-archive"),
            )

        self.assertEqual(self.store.read_index()["entries"], [])
        archived_attempt = self.store.read_reconciliation_archive(
            "reconcile-1"
        )
        self.assertEqual(archived_attempt["phase"], "ACCEPTED")
        with self.assertRaises(Exception):
            self.store.read_reconciliation("reconcile-1")

        recovered = (
            reconcile.recover_v3_workflow_action_reconciliation(
                self.task_dir,
                "reconcile-1",
                reauthenticate=lambda: MANAGER_SECRET,
            )
        )
        self.assertEqual(recovered.status, "ACCEPTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.index["entries"], [])
        self.assertTrue(Path(recovered.archive_path).is_file())

    def test_after_task_commit_recovers_from_event_without_redispatch(
        self,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        with self.assertRaises(Exception):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                self._request(
                    index, current, live_authority=True
                ),
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                failure_hook=_crash_at("after-task-commit"),
            )

        self.assertEqual(
            self.store.read_reconciliation("reconcile-1")["phase"],
            "CLAIMED",
        )
        self.assertEqual(
            dev_flow.load_state(self.task_dir / "state.json")[
                "revision"
            ],
            8,
        )
        recovered = (
            reconcile.recover_v3_workflow_action_reconciliation(
                self.task_dir,
                "reconcile-1",
                reauthenticate=lambda: MANAGER_SECRET,
            )
        )
        self.assertEqual(recovered.status, "ACCEPTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.index["entries"], [])
        self.assertTrue(Path(recovered.archive_path).is_file())

    def _assert_precommit_attempt_recovery(
        self,
        stage: str,
        expected_phase: str,
    ) -> None:
        index, current = self._quarantined(
            with_complete_receipt=True
        )
        request = self._request(index, current)
        authoritative_before = self._authoritative_task_bytes()
        with self.assertRaises(_InjectedReconciliationFailure):
            reconcile.reconcile_v3_workflow_action_quarantine(
                self.task_dir,
                request,
                reauthenticate=lambda: MANAGER_SECRET,
                verifier=self._accepted,
                commit_evaluator=self._live_evaluator,
                commit_authorizer=self._commit_authorizer,
                failure_hook=_crash_at(stage),
            )
        self.assertEqual(
            self.store.read_reconciliation("reconcile-1")["phase"],
            expected_phase,
        )
        self.assertEqual(
            dev_flow.load_state(self.task_dir / "state.json")[
                "revision"
            ],
            7,
        )
        self.assertEqual(
            self._authoritative_task_bytes(),
            authoritative_before,
        )

        recovered = reconcile.reconcile_v3_workflow_action_quarantine(
            self.task_dir,
            request,
            reauthenticate=lambda: MANAGER_SECRET,
            verifier=self._accepted,
            commit_evaluator=self._live_evaluator,
            commit_authorizer=self._commit_authorizer,
        )
        self.assertEqual(recovered.status, "UNRESOLVED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertTrue(recovered.blocked)
        self.assertEqual(
            self.store.read_reconciliation("reconcile-1")["phase"],
            "UNRESOLVED",
        )
        self.assertEqual(
            dev_flow.load_state(self.task_dir / "state.json")[
                "revision"
            ],
            7,
        )

    def test_after_attempt_restart_resumes_without_new_attempt(
        self,
    ) -> None:
        self._assert_precommit_attempt_recovery(
            "after-attempt", "PREPARED"
        )

    def test_after_claim_restart_resumes_without_new_claim(
        self,
    ) -> None:
        self._assert_precommit_attempt_recovery(
            "after-claim", "CLAIMED"
        )
