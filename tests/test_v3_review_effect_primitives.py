from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow
from tests.test_action_execution_journal import (
    MANAGER_SECRET,
    _effect as _journal_effect,
    _sealed_journal,
    _sha,
)


class _LostReviewResponse(RuntimeError):
    pass


class V3ReviewEffectPrimitiveTests(DevFlowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._transaction_counter = 0

    @staticmethod
    def _authorization() -> object:
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

    def _persist_state(self, state: dict) -> None:
        task_dir = self.data / "tasks" / state["task_id"]
        dev_flow._atomic_write_json(task_dir / "state.json", state)

    def _prepared_state(
        self,
        *,
        repository_count: int = 1,
        status: str = "IMPLEMENTING",
        task_id: str,
    ) -> tuple[dict, tuple[Path, ...]]:
        repositories = tuple(
            self.make_repo(f"{task_id}-repo-{index}")[0]
            for index in range(repository_count)
        )
        state = self.ready_workspace_task(
            *repositories, task_id=task_id
        )
        state = self.record_workspace_indexes(state)
        self.mutate("transition", state, "PLANNING")
        state = dev_flow.load_state(task_id, self.data)
        contract = self.root / f"{task_id}-contract.md"
        contract.write_text(
            "# Contract\n\nTyped review effect fixture.\n",
            encoding="utf-8",
        )
        recorded = self.mutate(
            "record-artifact",
            state,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        state = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            state,
            "--gate",
            "plan",
            "--note",
            "typed review fixture plan approved",
            "--artifact-sha256",
            recorded["artifact"]["sha256"],
        )
        state = dev_flow.load_state(task_id, self.data)
        self.mutate("transition", state, "IMPLEMENTING")
        state = dev_flow.load_state(task_id, self.data)
        if status != "IMPLEMENTING":
            state["status"] = status
        state["schema_version"] = dev_flow.V3_TASK_SCHEMA_VERSION
        self._persist_state(state)
        return state, repositories

    def _record_plan(
        self,
        state: dict,
        *,
        execution_id: str,
        output: Path | None = None,
    ) -> object:
        return dev_flow.plan_v3_record_test_effect(
            state_value=state,
            data_root=self.data,
            task_dir=self.data / "tasks" / state["task_id"],
            execution_id=execution_id,
            name="unit",
            test_command="python -m unittest",
            exit_code=0,
            output=output,
        )

    def _snapshot_plan(
        self,
        state: dict,
        *,
        execution_id: str,
        repository_ids: tuple[str, ...] | None = None,
    ) -> object:
        return dev_flow.plan_v3_review_snapshot_effect(
            state_value=state,
            data_root=self.data,
            task_dir=self.data / "tasks" / state["task_id"],
            execution_id=execution_id,
            repository_ids=repository_ids,
        )

    def _claimed_context(
        self,
        plan: object,
        *,
        effect_id: str | None = None,
    ) -> tuple[Path, object]:
        self._transaction_counter += 1
        token = str(self._transaction_counter)
        transaction_dir = self.root / "review-transactions" / token
        transaction_dir.mkdir(parents=True)
        safe_inputs = dev_flow.v3_review_effect_safe_inputs(plan)
        scopes = dev_flow.v3_review_effect_scopes(plan)
        effect = _journal_effect(
            effect_id=effect_id or plan.expected_effect_id,
            repository_id=plan.repository_ids[0],
            path=str(self.root / ("review-scope-" + token)),
        )
        effect["scopes"] = scopes
        effect["safe_inputs"] = safe_inputs
        effect["safe_input_sha256"] = dev_flow.semantic_sha256(
            dev_flow.SAFE_INPUT_DOMAIN, safe_inputs
        )
        effect["attempt_id"] = "attempt-review-" + token
        record = _sealed_journal(
            task_id=plan.task_id,
            execution_id=plan.execution_id,
            effects=[effect],
        )
        authoritative_state = (
            dev_flow._read_task_state_structural_snapshot(
                Path(str(plan.bindings["state_path"]))
            )
        )
        authoritative_state["workflow_ref"] = {
            "bundle_sha256": record["bindings"][
                "workflow_bundle_sha256"
            ]
        }
        dev_flow._atomic_write_json(
            transaction_dir / "state.json",
            authoritative_state,
        )
        core = {
            key: value
            for key, value in record.items()
            if key not in {"record_sha256", "seal"}
        }
        core["bindings"]["task_revision"] = authoritative_state[
            "revision"
        ]
        core["bindings"]["pre_effect_state_sha256"] = (
            dev_flow._sha256_contract(authoritative_state)
        )
        core["bindings"]["workflow_bundle_sha256"] = (
            record["bindings"]["workflow_bundle_sha256"]
        )
        record = dev_flow.seal_journal(
            core,
            manager_secret=MANAGER_SECRET,
        )
        store = dev_flow.ActionExecutionStore(transaction_dir)
        initialized = store.initialize_index(plan.task_id)
        store.persist_initial(
            record,
            expected_index=dev_flow.cas_token(initialized.index),
            manager_secret=MANAGER_SECRET,
        )
        batch = dev_flow.claim_ready_v3_workflow_action_effects(
            transaction_dir,
            plan.execution_id,
            authorization=self._authorization(),
            claim_id_factory=lambda current: "claim-" + current,
        )
        self.assertEqual(len(batch.contexts), 1)
        return transaction_dir, batch.contexts[0]

    def _dispatch_public(
        self,
        plan: object,
        *,
        lose_response: bool = False,
    ) -> tuple[Path, object, list[object], object | None]:
        transaction_dir, context = self._claimed_context(plan)
        captured = []

        def adapter(active: object) -> object:
            observation = dev_flow.dispatch_v3_review_effect(
                plan, active
            )
            captured.append(observation)
            if lose_response:
                raise _LostReviewResponse("review response lost")
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.plan.task_id,
                execution_id=active.plan.execution_id,
                effect_id=active.plan.effect_id,
                claim_id=active.plan.claim_id,
                attempt_id=active.plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=observation.semantic_sha256,
            )

        dispatch_result = None
        if lose_response:
            with self.assertRaises(_LostReviewResponse):
                dev_flow.dispatch_claimed_v3_workflow_action_effect(
                    transaction_dir,
                    context,
                    authorization=self._authorization(),
                    dispatcher=adapter,
                )
        else:
            dispatch_result = (
                dev_flow.dispatch_claimed_v3_workflow_action_effect(
                    transaction_dir,
                    context,
                    authorization=self._authorization(),
                    dispatcher=adapter,
                )
            )
            self.assertEqual(dispatch_result.dispatcher_invocations, 1)
        return transaction_dir, context, captured, dispatch_result

    def _observe_public(
        self,
        plan: object,
        transaction_dir: Path,
        dispatch_context: object,
        *,
        observation: object | None = None,
        verify_review_read_only: bool = False,
    ) -> tuple[object, object, list[object]]:
        receipts = []
        contexts = []

        def adapter(active: object) -> object:
            contexts.append(active)
            before = (
                self._tree_snapshot()
                if verify_review_read_only
                else None
            )
            receipt = dev_flow.observe_v3_review_effect(
                plan, active, observation
            )
            if before is not None:
                self.assertEqual(self._tree_snapshot(), before)
            receipts.append(receipt)
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.task_id,
                execution_id=active.execution_id,
                effect_id=active.effect_id,
                claim_id=active.claim_id,
                attempt_id=active.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=receipt.semantic_sha256,
            )

        step = dev_flow.observe_v3_workflow_action_effect(
            transaction_dir,
            plan.execution_id,
            plan.expected_effect_id,
            authorization=self._authorization(),
            observer=adapter,
        )
        self.assertEqual(step.dispatcher_invocations, 0)
        self.assertEqual(len(receipts), 1)
        return receipts[0], step, contexts

    def _tree_snapshot(self) -> list[tuple[str, int, int]]:
        return sorted(
            (
                str(path.relative_to(self.root)),
                path.stat().st_size,
                path.stat().st_mtime_ns,
            )
            for path in self.root.rglob("*")
            if path.is_file()
        )

    def _snapshot_ready_state(
        self,
        *,
        task_id: str,
    ) -> tuple[dict, tuple[Path, ...]]:
        state, repositories = self._prepared_state(
            repository_count=2,
            status="VERIFYING",
            task_id=task_id,
        )
        record_plan = self._record_plan(
            state,
            execution_id="record-for-" + task_id,
        )
        transaction_dir, context, observations, _result = (
            self._dispatch_public(record_plan)
        )
        receipt, _step, _contexts = self._observe_public(
            record_plan,
            transaction_dir,
            context,
            observation=observations[0],
        )
        state["tests"].append(
            receipt.as_dict()["result"]["test_record"]
        )
        state["revision"] = int(state["revision"]) + 1
        self._persist_state(state)
        return state, repositories

    def test_planners_are_read_only_frozen_and_bind_exact_contracts(
        self,
    ) -> None:
        state, _repositories = self._prepared_state(
            status="IMPLEMENTING",
            task_id="review-plan-contracts",
        )
        before = self._tree_snapshot()
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("planner probed filesystem"),
            ) as probe,
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError("planner mutated Git"),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("planner wrote bytes"),
            ),
        ):
            implementing = self._record_plan(
                state,
                execution_id="record-review-contracts",
            )
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(self._tree_snapshot(), before)
        self.assertEqual(
            implementing.expected_effect_id,
            "full.implementing.record-test.v1.effect",
        )
        self.assertEqual(
            set(dev_flow.v3_review_effect_safe_inputs(implementing)),
            {
                "schema",
                "action",
                "expected_effect_id",
                "plan_sha256",
                "task_revision",
                "execution_id",
                "repository_ids",
                "state_sha256",
                "payloads_sha256",
            },
        )
        scopes = dev_flow.v3_review_effect_scopes(implementing)
        self.assertEqual(
            scopes["repository_ids"],
            list(implementing.repository_ids),
        )
        self.assertEqual(
            scopes["worktree_ids"],
            [
                "review:"
                + implementing.task_id
                + ":"
                + repository_id
                for repository_id in implementing.repository_ids
            ],
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            implementing.action = "review-snapshot"
        with self.assertRaises(TypeError):
            implementing.bindings["changed"] = True
        with self.assertRaises(TypeError):
            implementing.payloads["/tmp/forged"] = b"forged"

        state["status"] = "VERIFYING"
        state["revision"] = int(state["revision"]) + 1
        self._persist_state(state)
        verifying = self._record_plan(
            state,
            execution_id="record-review-verifying",
        )
        self.assertEqual(
            verifying.expected_effect_id,
            "full.verifying.record-test.v1.effect",
        )

    def test_dispatch_and_observe_require_exact_active_contexts(
        self,
    ) -> None:
        state, _repositories = self._prepared_state(
            task_id="review-context-authority",
        )
        plan = self._record_plan(
            state, execution_id="review-context-execution"
        )
        transaction_dir, context = self._claimed_context(plan)
        payload_paths = [
            Path(str(item["path"]))
            for item in plan.bindings["payloads"]
        ]
        with self.assertRaises(dev_flow.FlowError) as plain:
            dev_flow.dispatch_v3_review_effect(plan, context.plan)
        self.assertEqual(
            plain.exception.code,
            "REVIEW_EFFECT_TRANSACTION_PERMIT_REQUIRED",
        )
        copied = dataclasses.replace(context)
        forged = dataclasses.replace(
            context, catalog_contract_sha256="f" * 64
        )
        for invalid in (copied, forged):
            with self.assertRaises(dev_flow.FlowError) as rejected:
                dev_flow.dispatch_v3_review_effect(plan, invalid)
            self.assertEqual(
                rejected.exception.code,
                "REVIEW_EFFECT_TRANSACTION_PERMIT_INACTIVE",
            )
        self.assertTrue(all(not path.exists() for path in payload_paths))

        borrowed_dir, borrowed = self._claimed_context(
            plan,
            effect_id="full.intake.preflight.v1.effect",
        )

        def borrowed_adapter(active: object) -> object:
            return dev_flow.dispatch_v3_review_effect(plan, active)

        with self.assertRaises(dev_flow.FlowError) as wrong_effect:
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                borrowed_dir,
                borrowed,
                authorization=self._authorization(),
                dispatcher=borrowed_adapter,
            )
        self.assertEqual(
            wrong_effect.exception.code,
            "REVIEW_EFFECT_TRANSACTION_PERMIT_MISMATCH",
        )
        self.assertTrue(all(not path.exists() for path in payload_paths))

        def borrowed_observer(active: object) -> object:
            receipt = dev_flow.observe_v3_review_effect(
                plan, active
            )
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.task_id,
                execution_id=active.execution_id,
                effect_id=active.effect_id,
                claim_id=active.claim_id,
                attempt_id=active.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=receipt.semantic_sha256,
            )

        with self.assertRaises(dev_flow.FlowError) as wrong_observer:
            dev_flow.observe_v3_workflow_action_effect(
                borrowed_dir,
                plan.execution_id,
                borrowed.plan.effect_id,
                authorization=self._authorization(),
                observer=borrowed_observer,
            )
        self.assertEqual(
            wrong_observer.exception.code,
            "REVIEW_EFFECT_OBSERVE_CONTEXT_MISMATCH",
        )

        observed_dispatches = []

        def dispatch_adapter(active: object) -> object:
            typed = dev_flow.dispatch_v3_review_effect(plan, active)
            observed_dispatches.append(typed)
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.plan.task_id,
                execution_id=active.plan.execution_id,
                effect_id=active.plan.effect_id,
                claim_id=active.plan.claim_id,
                attempt_id=active.plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=typed.semantic_sha256,
            )

        dev_flow.dispatch_claimed_v3_workflow_action_effect(
            transaction_dir,
            context,
            authorization=self._authorization(),
            dispatcher=dispatch_adapter,
        )
        self.assertEqual(len(observed_dispatches), 1)
        with self.assertRaises(dev_flow.FlowError) as replay:
            dev_flow.dispatch_v3_review_effect(plan, context)
        self.assertEqual(
            replay.exception.code,
            "REVIEW_EFFECT_TRANSACTION_PERMIT_INACTIVE",
        )
        with self.assertRaises(dev_flow.FlowError) as plain_observe:
            dev_flow.observe_v3_review_effect(plan, context.plan)
        self.assertEqual(
            plain_observe.exception.code,
            "REVIEW_EFFECT_OBSERVE_CONTEXT_REQUIRED",
        )
        _receipt, _step, observe_contexts = self._observe_public(
            plan,
            transaction_dir,
            context,
            observation=observed_dispatches[0],
        )
        replay_context = observe_contexts[0]
        for invalid in (
            replay_context,
            dataclasses.replace(replay_context),
        ):
            with self.assertRaises(dev_flow.FlowError) as rejected:
                dev_flow.observe_v3_review_effect(
                    plan, invalid, observed_dispatches[0]
                )
            self.assertEqual(
                rejected.exception.code,
                "REVIEW_EFFECT_OBSERVE_CONTEXT_INACTIVE",
            )

    def test_record_test_claimed_blob_and_read_only_observer(
        self,
    ) -> None:
        state, _repositories = self._prepared_state(
            task_id="review-record-blob",
        )
        plan = self._record_plan(
            state, execution_id="review-record-blob-execution"
        )
        payload_paths = [
            Path(str(item["path"]))
            for item in plan.bindings["payloads"]
        ]
        self.assertTrue(all(not path.exists() for path in payload_paths))
        transaction_dir, context, observations, result = (
            self._dispatch_public(plan)
        )
        self.assertIs(
            type(result), dev_flow.WorkflowActionDispatchResult
        )
        self.assertTrue(all(path.is_file() for path in payload_paths))
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("observer probed filesystem"),
            ) as probe,
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError("observer mutated Git"),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("review observer wrote bytes"),
            ),
        ):
            receipt, step, contexts = self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
                verify_review_read_only=True,
            )
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(step.status, "VERIFIED")
        self.assertFalse(receipt.recovered_lost_response)
        self.assertEqual(receipt.attempt_id, contexts[0].attempt_id)
        self.assertEqual(
            receipt.journal_record_sha256,
            contexts[0].journal_record_sha256,
        )
        self.assertEqual(
            receipt.index_record_sha256,
            contexts[0].index_record_sha256,
        )
        self.assertEqual(
            receipt.containment_record_sha256,
            contexts[0].containment_record_sha256,
        )
        self.assertEqual(
            receipt.observe_context_sha256,
            contexts[0].observe_context_sha256,
        )
        self.assertEqual(
            receipt.result["test_record"]["repository_ids"],
            plan.repository_ids,
        )

    def test_record_test_lost_response_observes_without_redispatch(
        self,
    ) -> None:
        state, _repositories = self._prepared_state(
            task_id="review-record-lost-response",
        )
        plan = self._record_plan(
            state, execution_id="review-record-lost-execution"
        )
        transaction_dir, context, observations, _result = (
            self._dispatch_public(plan, lose_response=True)
        )
        self.assertEqual(len(observations), 1)
        receipt, step, _contexts = self._observe_public(
            plan, transaction_dir, context
        )
        self.assertTrue(receipt.recovered_lost_response)
        self.assertEqual(step.status, "OBSERVED_QUARANTINED")
        self.assertEqual(step.dispatcher_invocations, 0)

        redispatches = 0

        def retry(_active: object) -> object:
            nonlocal redispatches
            redispatches += 1
            raise AssertionError("claimed review effect was redispatched")

        with self.assertRaises(
            (
                dev_flow.WorkflowActionTransactionError,
                dev_flow.ActionExecutionJournalError,
            )
        ):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                transaction_dir,
                context,
                authorization=self._authorization(),
                dispatcher=retry,
            )
        second = dev_flow.claim_ready_v3_workflow_action_effects(
            transaction_dir,
            plan.execution_id,
            authorization=self._authorization(),
        )
        self.assertEqual(second.contexts, ())
        self.assertEqual(redispatches, 0)

    def test_snapshot_target_is_execution_bound_and_covers_all_repos(
        self,
    ) -> None:
        state, _repositories = self._snapshot_ready_state(
            task_id="review-snapshot-all-repos"
        )
        before = self._tree_snapshot()
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("snapshot planner probed"),
            ) as probe,
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("snapshot planner wrote"),
            ),
        ):
            first = self._snapshot_plan(
                state, execution_id="snapshot-execution-a"
            )
            second = self._snapshot_plan(
                state, execution_id="snapshot-execution-b"
            )
        self.assertEqual(probe.call_count, 0)
        self.assertEqual(self._tree_snapshot(), before)
        self.assertEqual(
            first.expected_effect_id,
            "full.verifying.review-snapshot.v1.effect",
        )
        self.assertEqual(
            set(dev_flow.v3_review_effect_safe_inputs(first)),
            {
                "schema",
                "action",
                "expected_effect_id",
                "plan_sha256",
                "task_revision",
                "execution_id",
                "repository_ids",
                "state_sha256",
                "payloads_sha256",
            },
        )
        snapshot_scopes = dev_flow.v3_review_effect_scopes(first)
        self.assertEqual(
            snapshot_scopes["repository_ids"],
            list(first.repository_ids),
        )
        self.assertEqual(
            snapshot_scopes["worktree_ids"],
            [
                "review:"
                + first.task_id
                + ":"
                + repository_id
                for repository_id in first.repository_ids
            ],
        )
        self.assertEqual(
            first.repository_ids,
            tuple(
                sorted(
                    (
                        repository["id"]
                        for repository in state["repositories"]
                    ),
                    key=lambda item: item.encode("utf-8"),
                )
            ),
        )
        self.assertNotEqual(
            first.bindings["snapshot_root"],
            second.bindings["snapshot_root"],
        )
        self.assertNotEqual(
            first.bindings["snapshot"]["snapshot_id"],
            second.bindings["snapshot"]["snapshot_id"],
        )
        self.assertEqual(
            Path(str(first.bindings["snapshot_root"])).name,
            first.bindings["snapshot"]["snapshot_id"],
        )
        with self.assertRaises(dev_flow.FlowError) as incomplete:
            self._snapshot_plan(
                state,
                execution_id="snapshot-incomplete",
                repository_ids=(first.repository_ids[0],),
            )
        self.assertEqual(incomplete.exception.code, "INCOMPLETE_REVIEW")

        transaction_dir, context, observations, _result = (
            self._dispatch_public(first)
        )
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("snapshot observer probed"),
            ) as observer_probe,
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError(
                    "snapshot observer mutated Git"
                ),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError(
                    "snapshot observer wrote bytes"
                ),
            ),
        ):
            receipt, step, _contexts = self._observe_public(
                first,
                transaction_dir,
                context,
                observation=observations[0],
                verify_review_read_only=True,
            )
        self.assertEqual(observer_probe.call_count, 0)
        self.assertEqual(step.status, "VERIFIED")
        self.assertEqual(
            receipt.result["snapshot"]["repository_ids"],
            first.repository_ids,
        )
        self.assertTrue(
            all(
                Path(str(descriptor["path"])).is_file()
                for descriptor in first.bindings["payloads"]
            )
        )

    def test_snapshot_partial_failure_preserves_bytes_and_has_no_receipt(
        self,
    ) -> None:
        state, _repositories = self._snapshot_ready_state(
            task_id="review-snapshot-partial"
        )
        plan = self._snapshot_plan(
            state, execution_id="snapshot-partial-execution"
        )
        transaction_dir, context = self._claimed_context(plan)
        original_write = dev_flow._atomic_write_bytes
        written: list[Path] = []

        def partial_write(path: Path, content: bytes) -> None:
            target = Path(path)
            if len(written) == 1:
                raise dev_flow.FlowError(
                    "INJECTED_REVIEW_PARTIAL_FAILURE",
                    "second snapshot payload failed",
                )
            original_write(target, content)
            written.append(target)

        def adapter(active: object) -> object:
            with mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=partial_write,
            ):
                typed = dev_flow.dispatch_v3_review_effect(
                    plan, active
                )
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.plan.task_id,
                execution_id=active.plan.execution_id,
                effect_id=active.plan.effect_id,
                claim_id=active.plan.claim_id,
                attempt_id=active.plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=typed.semantic_sha256,
            )

        with self.assertRaises(dev_flow.FlowError) as failed:
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                transaction_dir,
                context,
                authorization=self._authorization(),
                dispatcher=adapter,
            )
        self.assertEqual(
            failed.exception.code,
            "INJECTED_REVIEW_PARTIAL_FAILURE",
        )
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].is_file())
        with self.assertRaises(dev_flow.FlowError) as no_receipt:
            self._observe_public(
                plan, transaction_dir, context
            )
        self.assertEqual(
            no_receipt.exception.code,
            "REVIEW_EFFECT_RECEIPT_MISSING",
        )
        self.assertTrue(written[0].is_file())

        redispatches = 0

        def retry(_active: object) -> object:
            nonlocal redispatches
            redispatches += 1
            raise AssertionError("partial snapshot was redispatched")

        with self.assertRaises(
            (
                dev_flow.WorkflowActionTransactionError,
                dev_flow.ActionExecutionJournalError,
            )
        ):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                transaction_dir,
                context,
                authorization=self._authorization(),
                dispatcher=retry,
            )
        self.assertEqual(redispatches, 0)

    def test_observer_rejects_payload_repository_and_output_drift(
        self,
    ) -> None:
        state, _repositories = self._prepared_state(
            status="VERIFYING",
            task_id="review-observer-drift",
        )
        output = self.root / "review-test-output.txt"
        output.write_text("all tests passed\n", encoding="utf-8")
        plan = self._record_plan(
            state,
            execution_id="review-drift-execution",
            output=output,
        )
        transaction_dir, context, observations, _result = (
            self._dispatch_public(plan)
        )
        self._observe_public(
            plan,
            transaction_dir,
            context,
            observation=observations[0],
        )

        descriptor = plan.bindings["payloads"][0]
        payload_path = Path(str(descriptor["path"]))
        original_payload = plan.payloads[str(payload_path)]
        payload_path.write_bytes(original_payload + b" ")
        with self.assertRaises(dev_flow.FlowError) as tampered:
            self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
            )
        self.assertEqual(
            tampered.exception.code,
            "REVIEW_EFFECT_RECEIPT_MISMATCH",
        )
        payload_path.write_bytes(original_payload)

        working = Path(
            str(plan.bindings["repositories"][0]["working_path"])
        )
        tracked = working / "tracked.txt"
        original_tracked = tracked.read_bytes()
        tracked.write_bytes(original_tracked + b"drift\n")
        with self.assertRaises(dev_flow.FlowError) as repo_drift:
            self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
            )
        self.assertEqual(
            repo_drift.exception.code,
            "REVIEW_EFFECT_REPOSITORY_CHANGED",
        )
        tracked.write_bytes(original_tracked)

        output.write_text("tampered output\n", encoding="utf-8")
        with self.assertRaises(dev_flow.FlowError) as output_drift:
            self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
            )
        self.assertEqual(
            output_drift.exception.code,
            "REVIEW_EFFECT_OUTPUT_CHANGED",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
