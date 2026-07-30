from __future__ import annotations

import copy
import contextlib
import dataclasses
import inspect
from pathlib import Path

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow
from tests.test_action_execution_journal import MANAGER_SECRET
from tests.test_action_execution_journal import _effect as _journal_effect
from tests.test_action_execution_journal import _sealed_journal
from tests.test_action_execution_journal import _sha
from tests.test_action_execution_store import ActionExecutionStoreCase


class _InjectedTransactionFailure(RuntimeError):
    pass


class WorkflowActionTransactionTests(DevFlowTestCase):
    def _persist_v4(
        self,
        task_id: str,
    ) -> tuple[Path, dict[str, object]]:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 4
        )
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            "repositories": [],
            "route": None,
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            ),
        }
        task_dir = dev_flow._task_dir(task_id, self.data)
        dev_flow._ensure_private_dir(task_dir)
        dev_flow._persist_state_transaction(
            None,
            state,
            task_dir,
            "task_started",
            {"status": "INTAKE"},
        )
        return task_dir, dev_flow.load_state(task_id, self.data)

    def _locks(self, task_dir: Path) -> tuple[object, object]:
        del task_dir
        # The transaction kernel now owns short lock acquisition and releases
        # task/index authority before entering the effect adapter.
        return (contextlib.nullcontext(), contextlib.nullcontext())

    def _invocation(
        self,
        state: dict[str, object],
    ) -> dev_flow.WorkflowActionInvocation:
        task_dir = dev_flow._task_dir(
            str(state["task_id"]), self.data
        )
        with dev_flow._task_lock(task_dir):
            edge = dev_flow.resolve_v3_node_action_edge(
                state, "preflight", selector="initial"
            )
            outcome = dev_flow.ActionOutcome(
                edge["trigger"]["id"],
                edge["id"],
                evidence_records=(
                    {"validator": "transaction-test/v1"},
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
                        "transaction-validator-accepted",
                        {"validator": "transaction-test/v1"},
                    ),
                ),
            )
            request = dev_flow.WorkflowActionInvocation(
                kind="node",
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters={"mode": "initial"},
                evidence={"validator": "transaction-test/v1"},
            )
            preview = dev_flow.evaluate_v3_node_action(
                state,
                public_command=request.public_command,
                selector=request.selector,
                action_outcome=request.action_outcome,
                action_parameters=request.action_parameters,
                evidence=request.evidence,
                preview=True,
            )
        return dataclasses.replace(
            request, confirm_intent=preview.intent["intent_id"]
        )

    @staticmethod
    def _authorization() -> dev_flow.WorkflowActionAuthorization:
        return dev_flow.WorkflowActionAuthorization(
            kind="operator",
            authorization_sha256="a" * 64,
            capability_sha256=None,
            request_nonce_sha256="b" * 64,
            principal="operator:test",
            ownership_sha256="c" * 64,
            registry_state_sha256="d" * 64,
            reauthenticate=lambda: None,
        )

    @staticmethod
    def _effect() -> dev_flow.WorkflowActionEffectBinding:
        return dev_flow.WorkflowActionEffectBinding(
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
            safe_inputs={"mode": "transaction-test"},
            attempt_id="attempt-1",
        )

    @staticmethod
    def _observation(
        context: dev_flow.WorkflowActionDispatchContext,
        *,
        claim_id: str | None = None,
    ) -> dev_flow.WorkflowActionEffectObservation:
        plan = context.plan
        return dev_flow.WorkflowActionEffectObservation(
            task_id=plan.task_id,
            execution_id=plan.execution_id,
            effect_id=plan.effect_id,
            claim_id=plan.claim_id if claim_id is None else claim_id,
            attempt_id=plan.attempt_id,
            settlement="QUIESCED",
            receipt_sha256="e" * 64,
        )

    def test_single_effect_commits_and_dispatches_exactly_once(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-happy")
        calls: list[str] = []

        def dispatch(context: object) -> object:
            calls.append(context.plan.claim_id)
            return self._observation(context)

        claim_limits: list[int | None] = []
        original_claim = (
            dev_flow.claim_ready_v3_workflow_action_effects
        )

        def claim_one_frontier(
            *args: object, **kwargs: object
        ) -> object:
            claim_limits.append(kwargs.get("limit"))
            return original_claim(*args, **kwargs)

        dev_flow.claim_ready_v3_workflow_action_effects = (
            claim_one_frontier
        )
        task_lock, registry_lock = self._locks(task_dir)
        try:
            with task_lock, registry_lock:
                result = dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-happy",
                    dispatcher=dispatch,
                )
        finally:
            dev_flow.claim_ready_v3_workflow_action_effects = (
                original_claim
            )

        self.assertEqual(result.status, "COMMITTED")
        self.assertTrue(claim_limits)
        self.assertEqual(set(claim_limits), {1})
        self.assertEqual(result.dispatcher_invocations, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.state["preflight"]["status"], "ready")
        self.assertEqual(result.journal["phase"], "COMMITTED")
        self.assertTrue(Path(result.archive_path).is_file())
        self.assertFalse(
            (
                task_dir
                / dev_flow.action_execution_active_path(
                    "execution-happy"
                )
            ).exists()
        )

    def test_semantic_operation_excludes_only_revision_confirmation(
        self,
    ) -> None:
        _, state = self._persist_v4("tx-semantic-operation")
        invocation = self._invocation(state)
        edge_roles = dev_flow._workflow_tx_edge_roles(
            state, invocation
        )

        def digest(
            selected: dev_flow.WorkflowActionInvocation,
        ) -> str:
            return dev_flow.semantic_sha256(
                dev_flow._WORKFLOW_TX_SEMANTIC_OPERATION_DOMAIN,
                dev_flow._workflow_tx_semantic_invocation_binding(
                    selected, edge_roles
                ),
            )

        expected = digest(invocation)
        self.assertEqual(
            digest(
                dataclasses.replace(
                    invocation,
                    confirm_intent=_sha("new-revision-intent"),
                )
            ),
            expected,
        )
        changed_parameters = dataclasses.replace(
            invocation,
            action_parameters={"mode": "changed"},
        )
        changed_selector = dataclasses.replace(
            invocation, selector="full"
        )
        changed_outcome = dataclasses.replace(
            invocation,
            action_outcome=dataclasses.replace(
                invocation.action_outcome,
                audit_facts=(
                    dev_flow.AuditFact(
                        "transaction-validator-changed",
                        {"validator": "changed/v1"},
                    ),
                ),
            ),
        )
        for changed in (
            changed_parameters,
            changed_selector,
            changed_outcome,
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(digest(changed), expected)

    def test_failure_before_claim_never_invokes_dispatcher(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-unstarted")
        calls: list[object] = []

        def fail(stage: str) -> None:
            if stage == "after-prepare":
                raise _InjectedTransactionFailure(stage)

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            with self.assertRaises(_InjectedTransactionFailure):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-unstarted",
                    dispatcher=lambda context: calls.append(context),
                    failure_hook=fail,
                )
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-unstarted",
                    authorization=self._authorization(),
                )
            )

        self.assertEqual(recovered.status, "UNSTARTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(calls, [])

    def test_lost_dispatch_response_is_never_redispatched(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-lost-dispatch")
        calls: list[str] = []

        def dispatch(context: object) -> object:
            calls.append(context.plan.claim_id)
            return self._observation(context)

        def fail(stage: str) -> None:
            if stage == "after-dispatch":
                raise _InjectedTransactionFailure(stage)

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            with self.assertRaises(_InjectedTransactionFailure):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-lost-dispatch",
                    dispatcher=dispatch,
                    failure_hook=fail,
                )
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-lost-dispatch",
                    authorization=self._authorization(),
                )
            )
            with self.assertRaises(Exception):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-lost-dispatch",
                    dispatcher=dispatch,
                )

        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(len(calls), 1)

    def test_forged_observation_is_zero_task_commit(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-forged-observation")
        calls: list[str] = []

        def dispatch(context: object) -> object:
            calls.append(context.plan.claim_id)
            return self._observation(
                context, claim_id="claim-forged"
            )

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            with self.assertRaisesRegex(
                dev_flow.WorkflowActionTransactionError,
                "durable claim",
            ):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-forged-observation",
                    dispatcher=dispatch,
                )
            current = dev_flow.load_state(state["task_id"], self.data)
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-forged-observation",
                    authorization=self._authorization(),
                )
            )

        self.assertEqual(current["revision"], state["revision"])
        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(len(calls), 1)

    def test_lost_commit_response_recovers_without_dispatch(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-lost-commit")
        calls: list[str] = []

        def dispatch(context: object) -> object:
            calls.append(context.plan.claim_id)
            return self._observation(context)

        def fail(stage: str) -> None:
            if stage == "after-task-commit":
                raise _InjectedTransactionFailure(stage)

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            with self.assertRaises(_InjectedTransactionFailure):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    self._invocation(state),
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-lost-commit",
                    dispatcher=dispatch,
                    failure_hook=fail,
                )
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-lost-commit",
                    authorization=self._authorization(),
                )
            )

        self.assertEqual(recovered.status, "RECOVERED_COMMITTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.state["preflight"]["status"], "ready")
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(recovered.archive_path).is_file())

    def test_complete_receipt_recovers_task_commit_without_dispatch(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-complete-receipt")
        calls: list[str] = []

        def dispatch(context: object) -> object:
            calls.append(context.plan.claim_id)
            return self._observation(context)

        def fail(stage: str) -> None:
            if stage == "after-receipt-verified":
                raise _InjectedTransactionFailure(stage)

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            invocation = self._invocation(state)
            with self.assertRaises(_InjectedTransactionFailure):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    invocation,
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-complete-receipt",
                    dispatcher=dispatch,
                    failure_hook=fail,
                )
            awaiting = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-complete-receipt",
                    authorization=self._authorization(),
                )
            )
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-complete-receipt",
                    authorization=self._authorization(),
                    invocation=invocation,
                )
            )

        self.assertEqual(awaiting.status, "AWAITING_TASK_COMMIT")
        self.assertEqual(recovered.status, "RECOVERED_COMMITTED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(
            recovered.state["preflight"]["status"], "ready"
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(Path(recovered.archive_path).is_file())

    def test_complete_receipt_rejects_changed_recovery_invocation(
        self,
    ) -> None:
        task_dir, state = self._persist_v4("tx-recovery-binding")

        def fail(stage: str) -> None:
            if stage == "after-receipt-verified":
                raise _InjectedTransactionFailure(stage)

        task_lock, registry_lock = self._locks(task_dir)
        with task_lock, registry_lock:
            invocation = self._invocation(state)
            with self.assertRaises(_InjectedTransactionFailure):
                dev_flow.execute_v3_workflow_action_transaction(
                    state,
                    task_dir,
                    invocation,
                    authorization=self._authorization(),
                    effect_binding=self._effect(),
                    execution_id="execution-recovery-binding",
                    dispatcher=self._observation,
                    failure_hook=fail,
                )
            forged = dataclasses.replace(
                invocation,
                evidence={"validator": "forged/v1"},
            )
            recovered = (
                dev_flow.recover_v3_workflow_action_transaction(
                    task_dir,
                    "execution-recovery-binding",
                    authorization=self._authorization(),
                    invocation=forged,
                )
            )
            current = dev_flow.load_state(
                state["task_id"], self.data
            )

        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.journal["phase"], "QUARANTINED")
        self.assertEqual(current["revision"], state["revision"])

    def test_claimed_failure_matrix_is_observe_only_and_never_redispatches(
        self,
    ) -> None:
        cases = {
            "after-claim": 0,
            "after-containment": 0,
            "after-dispatch": 1,
            "after-running": 1,
            "after-observation": 1,
            "after-effect-verified": 1,
        }
        for ordinal, (stage, expected_calls) in enumerate(
            cases.items(), start=1
        ):
            with self.subTest(stage=stage):
                task_id = f"tx-claimed-matrix-{ordinal}"
                execution_id = f"execution-claimed-matrix-{ordinal}"
                task_dir, state = self._persist_v4(task_id)
                calls: list[str] = []

                def dispatch(context: object) -> object:
                    calls.append(context.plan.claim_id)
                    return self._observation(context)

                def fail(observed_stage: str) -> None:
                    if observed_stage == stage:
                        raise _InjectedTransactionFailure(stage)

                task_lock, registry_lock = self._locks(task_dir)
                with task_lock, registry_lock:
                    invocation = self._invocation(state)
                    with self.assertRaises(
                        _InjectedTransactionFailure
                    ):
                        dev_flow.execute_v3_workflow_action_transaction(
                            state,
                            task_dir,
                            invocation,
                            authorization=self._authorization(),
                            effect_binding=self._effect(),
                            execution_id=execution_id,
                            dispatcher=dispatch,
                            failure_hook=fail,
                        )
                    recovered = (
                        dev_flow.recover_v3_workflow_action_transaction(
                            task_dir,
                            execution_id,
                            authorization=self._authorization(),
                            invocation=invocation,
                        )
                    )
                    with self.assertRaises(Exception):
                        dev_flow.execute_v3_workflow_action_transaction(
                            state,
                            task_dir,
                            invocation,
                            authorization=self._authorization(),
                            effect_binding=self._effect(),
                            execution_id=execution_id,
                            dispatcher=dispatch,
                        )

                self.assertEqual(
                    recovered.status, "QUARANTINE_REQUIRED"
                )
                self.assertEqual(
                    recovered.dispatcher_invocations, 0
                )
                self.assertEqual(len(calls), expected_calls)

    def test_finalization_failure_matrix_recovers_without_dispatch(
        self,
    ) -> None:
        cases = {
            "after-task-commit": "RECOVERED_COMMITTED",
            "after-journal-commit": "RECOVERED_COMMITTED",
            "after-archive": "ALREADY_CLOSED",
        }
        for ordinal, (stage, expected_status) in enumerate(
            cases.items(), start=1
        ):
            with self.subTest(stage=stage):
                task_id = f"tx-final-matrix-{ordinal}"
                execution_id = f"execution-final-matrix-{ordinal}"
                task_dir, state = self._persist_v4(task_id)
                calls: list[str] = []

                def dispatch(context: object) -> object:
                    calls.append(context.plan.claim_id)
                    return self._observation(context)

                def fail(observed_stage: str) -> None:
                    if observed_stage == stage:
                        raise _InjectedTransactionFailure(stage)

                task_lock, registry_lock = self._locks(task_dir)
                with task_lock, registry_lock:
                    invocation = self._invocation(state)
                    with self.assertRaises(
                        _InjectedTransactionFailure
                    ):
                        dev_flow.execute_v3_workflow_action_transaction(
                            state,
                            task_dir,
                            invocation,
                            authorization=self._authorization(),
                            effect_binding=self._effect(),
                            execution_id=execution_id,
                            dispatcher=dispatch,
                            failure_hook=fail,
                        )
                    recovered = (
                        dev_flow.recover_v3_workflow_action_transaction(
                            task_dir,
                            execution_id,
                            authorization=self._authorization(),
                            invocation=invocation,
                        )
                    )

                self.assertEqual(recovered.status, expected_status)
                self.assertEqual(
                    recovered.dispatcher_invocations, 0
                )
                self.assertEqual(len(calls), 1)

    def test_transaction_entry_rejects_inherited_controller_locks_before_journal(
        self,
    ) -> None:
        for suffix, inherited_lock in (
            (
                "task",
                lambda task_dir: dev_flow._task_lock(task_dir),
            ),
            (
                "registry",
                lambda _task_dir: dev_flow._workspace_registry_lock(
                    dev_flow.resolve_data_dir(self.data)
                ),
            ),
        ):
            with self.subTest(lock=suffix):
                task_dir, state = self._persist_v4(
                    f"tx-entry-lock-{suffix}"
                )
                invocation = self._invocation(state)
                dispatcher_calls = 0

                def dispatch(_context: object) -> object:
                    nonlocal dispatcher_calls
                    dispatcher_calls += 1
                    raise AssertionError("dispatcher must not run")

                with inherited_lock(task_dir):
                    with self.assertRaises(
                        dev_flow.WorkflowActionTransactionError
                    ) as raised:
                        dev_flow.execute_v3_workflow_action_transaction(
                            state,
                            task_dir,
                            invocation,
                            authorization=self._authorization(),
                            effect_binding=self._effect(),
                            execution_id=(
                                f"execution-entry-lock-{suffix}"
                            ),
                            dispatcher=dispatch,
                        )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_ACTION_TRANSACTION_LOCK_ORDER_INVALID",
                )
                self.assertEqual(dispatcher_calls, 0)
                self.assertFalse(
                    (task_dir / "action-executions").exists()
                )


class WorkflowActionExecutionKernelTests(ActionExecutionStoreCase):
    def persist_initial(
        self,
        record: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        current = copy.deepcopy(record or _sealed_journal())
        bindings = current["bindings"]
        state = {
            "schema_version": 2,
            "task_id": current["task_id"],
            "revision": bindings["task_revision"],
            "workflow_ref": {
                "bundle_sha256": bindings[
                    "workflow_bundle_sha256"
                ],
            },
        }
        dev_flow._atomic_write_json(
            self.task_dir / "state.json",
            state,
        )
        bindings["pre_effect_state_sha256"] = (
            dev_flow._sha256_contract(state)
        )
        core = {
            key: value
            for key, value in current.items()
            if key not in {"record_sha256", "seal"}
        }
        current = dev_flow.seal_journal(
            core,
            manager_secret=MANAGER_SECRET,
        )
        return super().persist_initial(current)

    @staticmethod
    def _authorization() -> dev_flow.WorkflowActionAuthorization:
        return dev_flow.WorkflowActionAuthorization(
            kind="manager",
            authorization_sha256=_sha("authorization"),
            capability_sha256=_sha("capability"),
            request_nonce_sha256=_sha("request-nonce"),
            principal="manager:test",
            ownership_sha256=_sha("ownership"),
            registry_state_sha256=_sha("registry-state"),
            reauthenticate=lambda: MANAGER_SECRET,
            nonce_consumed_verifier=lambda state, events: True,
        )

    @staticmethod
    def _observation(
        context: object,
        *,
        settlement: str = "QUIESCED",
        runtime_handle_sha256: str | None = None,
    ) -> dev_flow.WorkflowActionEffectObservation:
        plan = (
            context.plan
            if type(context)
            is dev_flow.WorkflowActionDispatchContext
            else context
        )
        return dev_flow.WorkflowActionEffectObservation(
            task_id=plan.task_id,
            execution_id=plan.execution_id,
            effect_id=plan.effect_id,
            claim_id=plan.claim_id,
            attempt_id=plan.attempt_id,
            settlement=settlement,
            receipt_sha256=_sha("receipt:" + plan.effect_id),
            runtime_handle_sha256=runtime_handle_sha256,
        )

    def _observe_callback(
        self,
        *,
        settlement: str = "QUIESCED",
        runtime_handle_sha256: str | None = None,
    ) -> object:
        def observe(active: object) -> object:
            dev_flow.verify_active_v3_workflow_action_observe_context(
                active
            )
            return self._observation(
                active,
                settlement=settlement,
                runtime_handle_sha256=runtime_handle_sha256,
            )

        return observe

    def test_parallel_claim_batch_and_dependency_frontier_are_durable(
        self,
    ) -> None:
        effects = [
            _journal_effect(
                "effect-a",
                repository_id="repo-a",
                path="/work/repo-a",
                parallel_group="fanout",
            ),
            _journal_effect(
                "effect-b",
                repository_id="repo-b",
                path="/work/repo-b",
                parallel_group="fanout",
            ),
            _journal_effect(
                "effect-c",
                repository_id="repo-c",
                path="/work/repo-c",
                predecessors=["effect-a", "effect-b"],
            ),
        ]
        self.persist_initial(
            _sealed_journal(effects=effects)
        )

        first = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        self.assertEqual(
            {context.plan.effect_id for context in first.contexts},
            {"effect-a", "effect-b"},
        )
        self.assertEqual(first.dispatcher_invocations, 0)
        self.assertEqual(
            {
                effect["effect_id"]: effect["phase"]
                for effect in first.journal["effects"]
            },
            {
                "effect-a": "CLAIMED",
                "effect-b": "CLAIMED",
                "effect-c": "PLANNED",
            },
        )
        for context in first.contexts:
            dev_flow.observe_v3_workflow_action_effect(
                self.task_dir,
                context.plan.execution_id,
                context.plan.effect_id,
                authorization=self._authorization(),
                observer=self._observe_callback(),
            )
        second = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        self.assertEqual(
            [context.plan.effect_id for context in second.contexts],
            ["effect-c"],
        )

    def test_limit_one_async_frontier_never_orphans_mixed_or_async_sibling(
        self,
    ) -> None:
        for ordinal, (sibling_kind, sibling_settlement) in enumerate(
            (
                ("filesystem", "synchronous-quiescence"),
                ("runtime-dispatch", "asynchronous-handoff"),
            ),
            start=1,
        ):
            with self.subTest(sibling_kind=sibling_kind):
                task_dir = (
                    Path(self.temporary.name)
                    / f"async-frontier-{ordinal}"
                )
                task_dir.mkdir(mode=0o700)
                store = dev_flow.ActionExecutionStore(task_dir)
                execution_id = f"execution-frontier-{ordinal}"
                first_effect = _journal_effect(
                    "effect-a",
                    kind="runtime-dispatch",
                    settlement="asynchronous-handoff",
                    repository_id="repo-a",
                    path="/work/repo-a",
                    parallel_group="fanout",
                )
                first_effect["scopes"]["lease_ids"] = [
                    "lease-a"
                ]
                sibling = _journal_effect(
                    "effect-b",
                    kind=sibling_kind,
                    settlement=sibling_settlement,
                    repository_id="repo-b",
                    path="/work/repo-b",
                    parallel_group="fanout",
                )
                if sibling_kind == "runtime-dispatch":
                    sibling["scopes"]["lease_ids"] = [
                        "lease-b"
                    ]
                index = store.initialize_index(
                    "task-vector"
                ).index
                store.persist_initial(
                    _sealed_journal(
                        execution_id=execution_id,
                        effects=[first_effect, sibling],
                    ),
                    expected_index=dev_flow.cas_token(index),
                    manager_secret=MANAGER_SECRET,
                )

                claimed = (
                    dev_flow.claim_ready_v3_workflow_action_effects(
                        task_dir,
                        execution_id,
                        authorization=self._authorization(),
                        claim_id_factory=(
                            lambda effect_id: "claim-" + effect_id
                        ),
                        limit=1,
                    )
                )
                self.assertEqual(
                    [
                        context.plan.effect_id
                        for context in claimed.contexts
                    ],
                    ["effect-a"],
                )
                self.assertEqual(
                    {
                        effect["effect_id"]: effect["phase"]
                        for effect in claimed.journal["effects"]
                    },
                    {
                        "effect-a": "CLAIMED",
                        "effect-b": "PLANNED",
                    },
                )

                recovered = (
                    dev_flow.recover_v3_workflow_action_transaction(
                        task_dir,
                        execution_id,
                        authorization=self._authorization(),
                    )
                )
                self.assertEqual(
                    recovered.status, "QUARANTINE_REQUIRED"
                )
                self.assertEqual(
                    recovered.dispatcher_invocations, 0
                )
                self.assertNotIn(
                    "CLAIMED",
                    [
                        effect["phase"]
                        for effect in recovered.journal["effects"][1:]
                    ],
                )

    def test_claimed_recovery_persists_quarantine_without_new_permit(
        self,
    ) -> None:
        index, current = self.persist_initial()
        self.store.claim_for_dispatch(
            "execution-vector",
            "effect-a",
            "claim-lost",
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )

        recovered = dev_flow.recover_v3_workflow_action_transaction(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
        )

        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(recovered.journal["phase"], "QUARANTINED")
        self.assertEqual(
            recovered.journal["effects"][0]["phase"],
            "QUARANTINED",
        )
        self.assertEqual(
            self.store.read_index()["entries"][0]["execution_id"],
            "execution-vector",
        )

    def test_claimed_async_recovery_never_invents_quiescence(
        self,
    ) -> None:
        effect = _journal_effect(
            "effect-runtime",
            kind="runtime-dispatch",
            settlement="asynchronous-handoff",
            repository_id="repo-a",
            path="/work/repo-a",
        )
        effect["scopes"]["lease_ids"] = ["lease-a"]
        self.persist_initial(_sealed_journal(effects=[effect]))
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda _effect_id: "claim-runtime",
        )
        self.assertEqual(len(claimed.contexts), 1)
        before = self.store.read_containment(
            "execution-vector", "effect-runtime"
        )
        self.assertEqual(before["phase"], "SPAWN_PENDING")

        recovered = dev_flow.recover_v3_workflow_action_transaction(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
        )

        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        after = self.store.read_containment(
            "execution-vector", "effect-runtime"
        )
        self.assertEqual(after["phase"], "QUARANTINED")
        self.assertEqual(
            recovered.journal["effects"][0][
                "containment_record_sha256"
            ],
            after["record_sha256"],
        )
        with self.assertRaises(
            dev_flow.ActionExecutionJournalError
        ):
            dev_flow.advance_containment(
                after,
                "CLOSED",
            )

    def test_runtime_binding_release_handoff_and_reservation_crosslink(
        self,
    ) -> None:
        effect = _journal_effect(
            "effect-runtime",
            kind="runtime-dispatch",
            settlement="asynchronous-handoff",
            repository_id="repo-a",
            path="/work/repo-a",
        )
        effect["scopes"]["lease_ids"] = ["lease-a"]
        record = _sealed_journal(effects=[effect])
        self.persist_initial(record)
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        context = claimed.contexts[0]
        binding = dev_flow.WorkflowActionRuntimeBinding(
            task_id="task-vector",
            execution_id="execution-vector",
            effect_id="effect-runtime",
            claim_id=context.plan.claim_id,
            attempt_id=context.plan.attempt_id,
            lease_id="lease-a",
            runtime_handle_sha256=_sha("runtime-handle"),
            stop_action_id="runtime.stop/v1",
            reconcile_action_id="runtime.reconcile/v1",
        )
        bound = dev_flow.bind_v3_workflow_action_runtime(
            self.task_dir,
            binding,
            authorization=self._authorization(),
        )
        self.assertEqual(bound.containment["phase"], "RUNTIME_BOUND")
        release_calls: list[str] = []
        release_contexts: list[
            dev_flow.WorkflowActionRuntimeReleaseContext
        ] = []

        def release_adapter(
            active: dev_flow.WorkflowActionRuntimeReleaseContext,
        ) -> dev_flow.WorkflowActionRuntimeReleaseAck:
            for forged in (
                dataclasses.replace(active),
                copy.deepcopy(active),
            ):
                with self.assertRaises(
                    dev_flow.WorkflowActionTransactionError
                ):
                    dev_flow.verify_active_v3_workflow_action_runtime_release(
                        forged
                    )
            facts = (
                dev_flow.verify_active_v3_workflow_action_runtime_release(
                    active
                )
            )
            release_calls.append(
                str(facts["runtime_handle_sha256"])
            )
            release_contexts.append(active)
            return dev_flow.WorkflowActionRuntimeReleaseAck(
                task_id=active.binding.task_id,
                execution_id=active.binding.execution_id,
                effect_id=active.binding.effect_id,
                claim_id=active.binding.claim_id,
                attempt_id=active.binding.attempt_id,
                lease_id=active.binding.lease_id,
                runtime_handle_sha256=(
                    active.binding.runtime_handle_sha256
                ),
                runtime_binding_sha256=(
                    active.binding.binding_sha256
                ),
                release_context_sha256=(
                    active.release_context_sha256
                ),
                protocol="suspended-release/v1",
                released=True,
            )

        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.release_v3_workflow_action_runtime(
                self.task_dir,
                dataclasses.replace(
                    binding,
                    runtime_handle_sha256=_sha(
                        "wrong-runtime-handle"
                    ),
                ),
                authorization=self._authorization(),
                release_adapter=release_adapter,
            )
        self.assertEqual(release_calls, [])
        released = dev_flow.release_v3_workflow_action_runtime(
            self.task_dir,
            binding,
            authorization=self._authorization(),
            release_adapter=release_adapter,
        )
        self.assertEqual(released.containment["phase"], "RELEASED")
        self.assertEqual(
            release_calls, [_sha("runtime-handle")]
        )
        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.verify_active_v3_workflow_action_runtime_release(
                release_contexts[0]
            )
        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.release_v3_workflow_action_runtime(
                self.task_dir,
                binding,
                authorization=self._authorization(),
                release_adapter=release_adapter,
            )
        self.assertEqual(len(release_calls), 1)
        observed = dev_flow.observe_v3_workflow_action_effect(
            self.task_dir,
            context.plan.execution_id,
            context.plan.effect_id,
            authorization=self._authorization(),
            observer=self._observe_callback(
                settlement="HANDOFF_VERIFIED",
                runtime_handle_sha256=_sha("runtime-handle"),
            ),
            runtime_binding=binding,
        )
        self.assertEqual(
            observed.containment["phase"], "HANDOFF_VERIFIED"
        )
        self.assertEqual(
            observed.journal["effects"][0]["phase"], "VERIFIED"
        )
        receipt_verified = dev_flow.verify_receipt_intent(
            observed.journal,
            {
                "receipt_sha256": _sha("action-receipt"),
                "candidate_state_sha256": _sha("candidate-state"),
                "event_batch_sha256": _sha("event-batch"),
                "engine_proof_sha256": _sha("engine-proof"),
                "authorization_action_edge_id": (
                    "baseline.materialize/v3"
                ),
                "completion_edge_id": "baseline.materialize/v3",
            },
            manager_secret=MANAGER_SECRET,
        )
        persisted = self.store.persist_update(
            receipt_verified,
            expected_index=dev_flow.cas_token(observed.index),
            expected_journal=dev_flow.cas_token(observed.journal),
            manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        committed = dev_flow.commit_journal(
            persisted.record,
            {
                "task_commit_revision": 8,
                "task_state_sha256": _sha("task-state"),
                "event_sha256": _sha("handoff-event"),
                "outbox_sha256": _sha("handoff-outbox"),
                "nonce_consumed": True,
            },
            manager_secret=MANAGER_SECRET,
        )
        persisted = self.store.persist_update(
            committed,
            expected_index=dev_flow.cas_token(persisted.index),
            expected_journal=dev_flow.cas_token(persisted.record),
            manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        reservation = dev_flow.new_runtime_reservation(
            persisted.record,
            "effect-runtime",
            observed.containment,
            lease_id="lease-a",
            runtime_handle_sha256=_sha("runtime-handle"),
            stop_action_id="runtime.stop/v1",
            reconcile_action_id="runtime.reconcile/v1",
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(reservation["phase"], "ACTIVE")
        self.assertEqual(
            reservation["containment_record_sha256"],
            observed.containment["record_sha256"],
        )
        stored_reservation = self.store.persist_runtime_reservation(
            reservation,
            expected_index=dev_flow.cas_token(persisted.index),
            expected_journal=dev_flow.cas_token(persisted.record),
            manager_secret=MANAGER_SECRET,
        )
        closure = self.store.archive_and_close(
            "execution-vector",
            expected_index=dev_flow.cas_token(
                stored_reservation.index
            ),
            expected_journal=dev_flow.cas_token(persisted.record),
            authoritative_event_sha256=_sha("handoff-event"),
            promote_runtime_reservation=True,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            closure.index["entries"][0]["entry_kind"],
            "runtime-reservation",
        )

    def test_dispatch_entry_has_released_task_and_index_locks(
        self,
    ) -> None:
        self.persist_initial()
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        context = claimed.contexts[0]
        calls: list[tuple[str, ...]] = []

        def dispatch(
            observed: dev_flow.WorkflowActionDispatchContext,
        ) -> dev_flow.WorkflowActionEffectObservation:
            held = tuple(dev_flow._HELD_LOCK_DIRECTORIES.get())
            calls.append(held)
            self.assertNotIn(str(self.task_dir), held)
            self.assertNotIn(str(self.task_dir.parent.parent), held)
            return self._observation(observed)

        with dev_flow._task_lock(self.task_dir):
            with self.assertRaises(
                dev_flow.WorkflowActionTransactionError
            ) as raised:
                dev_flow.dispatch_claimed_v3_workflow_action_effect(
                    self.task_dir,
                    context,
                    authorization=self._authorization(),
                    dispatcher=dispatch,
                )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_TRANSACTION_DISPATCH_LOCK_HELD",
        )
        self.assertEqual(calls, [])

        dispatch_result = (
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                self.task_dir,
                context,
                authorization=self._authorization(),
                dispatcher=dispatch,
            )
        )
        self.assertIsInstance(
            dispatch_result, dev_flow.WorkflowActionDispatchResult
        )
        self.assertIsInstance(
            dispatch_result.observation,
            dev_flow.WorkflowActionEffectObservation,
        )
        self.assertIsInstance(
            dispatch_result.observe_context,
            dev_flow.WorkflowActionObserveContext,
        )
        self.assertEqual(len(calls), 1)

    def test_restart_observe_only_reconstructs_exact_cas_without_redispatch(
        self,
    ) -> None:
        self.persist_initial()
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        dispatch_context = claimed.contexts[0]
        dispatcher_count = 0

        def lost_response(
            _active: dev_flow.WorkflowActionDispatchContext,
        ) -> object:
            nonlocal dispatcher_count
            dispatcher_count += 1
            raise ConnectionError("effect completed; response lost")

        with self.assertRaises(ConnectionError):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                self.task_dir,
                dispatch_context,
                authorization=self._authorization(),
                dispatcher=lost_response,
            )
        captured: list[object] = []
        observer_count = 0

        def observe(active: object) -> object:
            nonlocal observer_count
            observer_count += 1
            captured.append(active)
            for forged in (
                dataclasses.replace(active, claim_id="wrong-claim"),
                dataclasses.replace(
                    active, attempt_id="wrong-attempt"
                ),
                dataclasses.replace(
                    active, journal_record_sha256="0" * 64
                ),
                dataclasses.replace(
                    active,
                    containment_revision=(
                        active.containment_revision + 1
                    ),
                ),
            ):
                with self.assertRaises(
                    dev_flow.WorkflowActionTransactionError
                ):
                    dev_flow.verify_active_v3_workflow_action_observe_context(
                        forged
                    )
            facts = (
                dev_flow.verify_active_v3_workflow_action_observe_context(
                    active
                )
            )
            self.assertEqual(
                facts["observe_context_sha256"],
                active.observe_context_sha256,
            )
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.task_id,
                execution_id=active.execution_id,
                effect_id=active.effect_id,
                claim_id=active.claim_id,
                attempt_id=active.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=_sha("recovered-receipt"),
            )

        first = dev_flow.observe_v3_workflow_action_effect(
            self.task_dir,
            dispatch_context.plan.execution_id,
            dispatch_context.plan.effect_id,
            authorization=self._authorization(),
            observer=observe,
        )
        self.assertEqual(first.status, "OBSERVED_QUARANTINED")
        self.assertEqual(first.dispatcher_invocations, 0)
        self.assertEqual(dispatcher_count, 1)
        self.assertEqual(observer_count, 1)
        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.verify_active_v3_workflow_action_observe_context(
                captured[0]
            )

        second = dev_flow.observe_v3_workflow_action_effect(
            self.task_dir,
            dispatch_context.plan.execution_id,
            dispatch_context.plan.effect_id,
            authorization=self._authorization(),
            observer=observe,
        )
        self.assertEqual(second.status, "OBSERVED_QUARANTINED")
        self.assertEqual(second.dispatcher_invocations, 0)
        self.assertEqual(dispatcher_count, 1)
        self.assertEqual(observer_count, 2)
        assert first.observation is not None
        assert second.observation is not None
        self.assertEqual(
            first.observation.receipt_sha256,
            second.observation.receipt_sha256,
        )

    def test_async_launch_is_suspended_until_exact_binding_is_durable(
        self,
    ) -> None:
        effect = _journal_effect(
            "effect-runtime",
            kind="runtime-dispatch",
            settlement="asynchronous-handoff",
            repository_id="repo-a",
            path="/work/repo-a",
        )
        effect["scopes"]["lease_ids"] = ["lease-a"]
        self.persist_initial(_sealed_journal(effects=[effect]))
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        context = claimed.contexts[0]
        business_effect_count = 0

        def launch(
            observed: dev_flow.WorkflowActionDispatchContext,
        ) -> dev_flow.WorkflowActionRuntimeLaunch:
            self.assertEqual(
                observed.launch_protocol,
                "suspended-handshake/v1",
            )
            binding = dev_flow.WorkflowActionRuntimeBinding(
                task_id=observed.plan.task_id,
                execution_id=observed.plan.execution_id,
                effect_id=observed.plan.effect_id,
                claim_id=observed.plan.claim_id,
                attempt_id=observed.plan.attempt_id,
                lease_id="lease-a",
                runtime_handle_sha256=_sha("suspended-runtime"),
                stop_action_id="runtime.stop/v1",
                reconcile_action_id="runtime.reconcile/v1",
            )
            return dev_flow.WorkflowActionRuntimeLaunch(
                binding=binding,
                protocol="suspended-handshake/v1",
                suspended=True,
                business_effect_count=business_effect_count,
            )

        launched = dev_flow.dispatch_claimed_v3_workflow_action_effect(
            self.task_dir,
            context,
            authorization=self._authorization(),
            dispatcher=launch,
        )
        self.assertIsInstance(
            launched, dev_flow.WorkflowActionRuntimeLaunch
        )
        self.assertEqual(business_effect_count, 0)
        before_bind = self.store.read_active_journal(
            "execution-vector", manager_secret=MANAGER_SECRET
        )
        self.assertEqual(
            before_bind["effects"][0]["phase"], "CLAIMED"
        )
        self.assertIsNone(
            before_bind["effects"][0]["runtime_binding_sha256"]
        )

        bound = dev_flow.bind_v3_workflow_action_runtime(
            self.task_dir,
            launched.binding,
            authorization=self._authorization(),
        )
        self.assertEqual(bound.containment["phase"], "RUNTIME_BOUND")
        self.assertEqual(
            bound.journal["effects"][0]["runtime_binding_sha256"],
            launched.binding.binding_sha256,
        )

    def test_runtime_release_lost_response_is_observe_only_and_never_replayed(
        self,
    ) -> None:
        effect = _journal_effect(
            "effect-runtime",
            kind="runtime-dispatch",
            settlement="asynchronous-handoff",
            repository_id="repo-a",
            path="/work/repo-a",
        )
        effect["scopes"]["lease_ids"] = ["lease-a"]
        self.persist_initial(_sealed_journal(effects=[effect]))
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        dispatch_context = claimed.contexts[0]
        binding = dev_flow.WorkflowActionRuntimeBinding(
            task_id=dispatch_context.plan.task_id,
            execution_id=dispatch_context.plan.execution_id,
            effect_id=dispatch_context.plan.effect_id,
            claim_id=dispatch_context.plan.claim_id,
            attempt_id=dispatch_context.plan.attempt_id,
            lease_id="lease-a",
            runtime_handle_sha256=_sha("lost-release-runtime"),
            stop_action_id="runtime.stop/v1",
            reconcile_action_id="runtime.reconcile/v1",
        )
        dev_flow.bind_v3_workflow_action_runtime(
            self.task_dir,
            binding,
            authorization=self._authorization(),
        )
        release_calls = 0

        def lost_response(
            active: dev_flow.WorkflowActionRuntimeReleaseContext,
        ) -> dev_flow.WorkflowActionRuntimeReleaseAck:
            nonlocal release_calls
            dev_flow.verify_active_v3_workflow_action_runtime_release(
                active
            )
            release_calls += 1
            raise RuntimeError(
                "lost response from https://secret.invalid/runtime"
            )

        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ) as raised:
            dev_flow.release_v3_workflow_action_runtime(
                self.task_dir,
                binding,
                authorization=self._authorization(),
                release_adapter=lost_response,
            )
        self.assertEqual(
            raised.exception.code,
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_UNCERTAIN",
        )
        self.assertNotIn("secret.invalid", str(raised.exception))
        self.assertEqual(release_calls, 1)
        containment = self.store.read_containment(
            "execution-vector", "effect-runtime"
        )
        self.assertEqual(containment["phase"], "RELEASED")

        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.release_v3_workflow_action_runtime(
                self.task_dir,
                binding,
                authorization=self._authorization(),
                release_adapter=lost_response,
            )
        self.assertEqual(release_calls, 1)

        recovered = dev_flow.recover_v3_workflow_action_transaction(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            runtime_bindings={"effect-runtime": binding},
            live_runtime_authenticator=(
                lambda journal, observed, exact: (
                    observed["phase"] == "RELEASED"
                    and exact is binding
                )
            ),
        )
        self.assertEqual(recovered.status, "REATTACH_OBSERVE_ONLY")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(release_calls, 1)

    def test_dispatch_capability_rejects_forgery_copy_outside_and_replay(
        self,
    ) -> None:
        self.persist_initial()
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            self.task_dir,
            "execution-vector",
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: "claim-" + effect_id,
        )
        context = claimed.contexts[0]
        calls = 0

        def dispatch(
            active: dev_flow.WorkflowActionDispatchContext,
        ) -> dev_flow.WorkflowActionEffectObservation:
            nonlocal calls
            calls += 1
            facts = (
                dev_flow.verify_active_v3_workflow_action_dispatch(
                    active
                )
            )
            self.assertEqual(facts["claim_id"], active.plan.claim_id)
            return self._observation(active)

        for forged in (
            dataclasses.replace(context),
            copy.deepcopy(context),
        ):
            with self.subTest(kind=type(forged).__name__):
                with self.assertRaises(
                    dev_flow.WorkflowActionTransactionError
                ):
                    dev_flow.dispatch_claimed_v3_workflow_action_effect(
                        self.task_dir,
                        forged,
                        authorization=self._authorization(),
                        dispatcher=dispatch,
                    )
                self.assertEqual(calls, 0)

        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.verify_active_v3_workflow_action_dispatch(
                context
            )
        self.assertEqual(calls, 0)
        self.assertFalse(
            hasattr(
                dev_flow,
                "_WORKFLOW_TX_ISSUE_DISPATCH_PERMIT",
            )
        )
        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            with dev_flow._workflow_tx_active_dispatch(context):
                dispatch(context)
        self.assertEqual(calls, 0)

        dev_flow.dispatch_claimed_v3_workflow_action_effect(
            self.task_dir,
            context,
            authorization=self._authorization(),
            dispatcher=dispatch,
        )
        self.assertEqual(calls, 1)

        with self.assertRaises(
            dev_flow.WorkflowActionTransactionError
        ):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                self.task_dir,
                context,
                authorization=self._authorization(),
                dispatcher=dispatch,
            )
        self.assertEqual(calls, 1)

    def test_public_dispatch_surface_exposes_no_mint_or_invoke_primitive(
        self,
    ) -> None:
        claim_signature = inspect.signature(
            dev_flow.claim_ready_v3_workflow_action_effects
        )
        dispatch_signature = inspect.signature(
            dev_flow.dispatch_claimed_v3_workflow_action_effect
        )
        release_signature = inspect.signature(
            dev_flow.release_v3_workflow_action_runtime
        )
        self.assertNotIn("_permit_issuer", claim_signature.parameters)
        self.assertNotIn("permit_issuer", claim_signature.parameters)
        self.assertNotIn(
            "callback_invoker", dispatch_signature.parameters
        )
        self.assertNotIn(
            "permit_issuer", release_signature.parameters
        )
        self.assertNotIn(
            "callback_invoker", release_signature.parameters
        )
        for name in (
            "_WORKFLOW_TX_ISSUE_DISPATCH_PERMIT",
            "_WORKFLOW_TX_INVOKE_DISPATCH_CALLBACK",
            "_WORKFLOW_TX_VERIFY_ACTIVE_DISPATCH",
            "_workflow_tx_build_dispatch_callback_authority",
            "_workflow_tx_build_public_dispatch_api",
            "_WORKFLOW_TX_ISSUE_RUNTIME_RELEASE_PERMIT",
            "_WORKFLOW_TX_INVOKE_RUNTIME_RELEASE_CALLBACK",
            "_WORKFLOW_TX_VERIFY_ACTIVE_RUNTIME_RELEASE",
            "_workflow_tx_build_runtime_release_callback_authority",
            "_workflow_tx_build_public_runtime_release_api",
        ):
            self.assertFalse(hasattr(dev_flow, name), name)
