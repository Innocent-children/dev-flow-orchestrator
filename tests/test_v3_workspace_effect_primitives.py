from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow, git
from tests.test_action_execution_journal import (
    MANAGER_SECRET,
    _effect as _journal_effect,
    _sealed_journal,
    _sha,
)


class _LostWorkspaceResponse(RuntimeError):
    pass


class V3WorkspaceEffectPrimitiveTests(DevFlowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.first, _ = self.make_repo("workspace-typed-first")
        self.second, _ = self.make_repo("workspace-typed-second")
        self.task_id = "workspace-typed-task"
        self.state = self.route_approved_task(
            self.first,
            self.second,
            task_id=self.task_id,
        )
        self.state["schema_version"] = (
            dev_flow.V3_TASK_SCHEMA_VERSION
        )
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        self.state.update(
            copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    self.task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            )
        )
        self.repository_ids = tuple(
            sorted(
                (repo["id"] for repo in self.state["repositories"]),
                key=lambda item: item.encode("utf-8"),
            )
        )
        self.task_dir = self.data / "tasks" / self.task_id
        self._persist_state(self.state)
        self._dispatch_counter = 0

    def _persist_state(self, state: dict) -> None:
        dev_flow._atomic_write_json(
            self.task_dir / "state.json", state
        )

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

    def _claimed_context(
        self,
        plan: object,
        *,
        effect_id: str | None = None,
    ) -> tuple[Path, object]:
        self._dispatch_counter += 1
        token = str(self._dispatch_counter)
        transaction_dir = (
            self.root / "transaction-kernel" / token
        )
        transaction_dir.mkdir(parents=True)
        safe_inputs = dev_flow.v3_workspace_effect_safe_inputs(plan)
        scopes = dev_flow.v3_workspace_effect_scopes(plan)
        effect = _journal_effect(
            effect_id=effect_id or plan.expected_effect_id,
            repository_id=plan.repository_ids[0],
            path=str(self.root / ("effect-scope-" + token)),
        )
        effect["scopes"] = scopes
        effect["safe_inputs"] = safe_inputs
        effect["safe_input_sha256"] = dev_flow.semantic_sha256(
            dev_flow.SAFE_INPUT_DOMAIN, safe_inputs
        )
        effect["attempt_id"] = "attempt-workspace-" + token
        execution_id = "execution-workspace-" + token
        record = _sealed_journal(
            task_id=plan.task_id,
            execution_id=execution_id,
            effects=[effect],
        )
        authoritative_state = copy.deepcopy(self.state)
        authoritative_state["task_id"] = plan.task_id
        authoritative_state["revision"] = 7
        dev_flow._atomic_write_json(
            transaction_dir / "state.json",
            authoritative_state,
        )
        journal_core = {
            key: copy.deepcopy(value)
            for key, value in record.items()
            if key not in {"record_sha256", "seal"}
        }
        journal_core["bindings"]["pre_effect_state_sha256"] = (
            dev_flow._sha256_contract(authoritative_state)
        )
        journal_core["bindings"]["workflow_bundle_sha256"] = (
            authoritative_state["workflow_ref"]["bundle_sha256"]
        )
        record = dev_flow.seal_journal(
            journal_core, manager_secret=MANAGER_SECRET
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
            execution_id,
            authorization=self._authorization(),
            claim_id_factory=lambda effect_id: (
                "claim-" + effect_id
            ),
        )
        self.assertEqual(len(batch.contexts), 1)
        return transaction_dir, batch.contexts[0]

    def _dispatch_public(
        self,
        plan: object,
        effect_helper: object,
        *,
        lose_response: bool = False,
    ) -> tuple[Path, object, list[object]]:
        transaction_dir, context = self._claimed_context(plan)
        captured = []

        def adapter(active: object) -> object:
            typed = effect_helper(plan, active)
            captured.append(typed)
            if lose_response:
                raise _LostWorkspaceResponse("response lost")
            return dev_flow.WorkflowActionEffectObservation(
                task_id=active.plan.task_id,
                execution_id=active.plan.execution_id,
                effect_id=active.plan.effect_id,
                claim_id=active.plan.claim_id,
                attempt_id=active.plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=typed.semantic_sha256,
            )

        if lose_response:
            with self.assertRaises(_LostWorkspaceResponse):
                dev_flow.dispatch_claimed_v3_workflow_action_effect(
                    transaction_dir,
                    context,
                    authorization=self._authorization(),
                    dispatcher=adapter,
                )
        else:
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                transaction_dir,
                context,
                authorization=self._authorization(),
                dispatcher=adapter,
            )
        return transaction_dir, context, captured

    def _observe_public(
        self,
        plan: object,
        transaction_dir: Path,
        dispatch_context: object,
        *,
        observation: object | None = None,
        verify_workspace_read_only: bool = False,
    ) -> tuple[object, object, list[object]]:
        captured_receipts = []
        captured_contexts = []
        effect_observer = (
            dev_flow.observe_v3_workspace_plan_effect
            if plan.action == "plan"
            else dev_flow.observe_v3_workspace_execute_effect
        )

        def adapter(active: object) -> object:
            captured_contexts.append(active)
            before_observe = (
                self._tree_snapshot()
                if verify_workspace_read_only
                else None
            )
            receipt = effect_observer(
                plan, active, observation
            )
            if before_observe is not None:
                self.assertEqual(
                    self._tree_snapshot(), before_observe
                )
            captured_receipts.append(receipt)
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
            dispatch_context.plan.execution_id,
            dispatch_context.plan.effect_id,
            authorization=self._authorization(),
            observer=adapter,
        )
        self.assertEqual(step.dispatcher_invocations, 0)
        self.assertEqual(len(captured_receipts), 1)
        return captured_receipts[0], step, captured_contexts

    def _plan(self) -> object:
        return dev_flow.plan_v3_workspace_plan_effect(
            state_value=self.state,
            data_root=self.data,
            task_dir=self.task_dir,
        )

    def _approve_workspace_plan(self, receipt: object) -> None:
        observation = receipt.observation
        artifact_path = Path(str(observation["artifact_path"]))
        artifact_sha = str(observation["evidence_sha256"])
        evidence = json.loads(artifact_path.read_text(encoding="utf-8"))
        repository_ids = [
            item["repository_id"]
            for item in evidence["repositories"]
        ]
        artifact = {
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "artifact_id": "workspace-plan-1",
            "kind": "workspace-plan",
            "path": str(artifact_path),
            "path_identity": dev_flow._serializable_path_identity(
                artifact_path
            ),
            "sha256": artifact_sha,
            "artifact_type": "file",
            "size": artifact_path.stat().st_size,
            "file_count": 1,
            "total_size": artifact_path.stat().st_size,
            "metadata": {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "repository_ids": repository_ids,
                "workspace_generation": 0,
            },
        }
        self.state["revision"] = int(self.state["revision"]) + 1
        self.state["artifacts"].append(artifact)
        self.state["workspace"]["plan"] = {
            "artifact_id": artifact["artifact_id"],
            "sha256": artifact_sha,
            "path": str(artifact_path),
            "repository_ids": repository_ids,
            "workspace_generation": 0,
        }
        self.state["approvals"]["workspace"] = {
            "approval_id": "workspace-approval-1",
            "artifact_id": artifact["artifact_id"],
            "artifact_sha256": artifact_sha,
            "workspace_generation": 0,
        }
        self._persist_state(self.state)

    def _planned_and_approved(self) -> tuple[object, object]:
        plan = self._plan()
        transaction_dir, context, observations = (
            self._dispatch_public(
                plan, dev_flow.dispatch_v3_workspace_plan_effect
            )
        )
        receipt, _step, _contexts = self._observe_public(
            plan,
            transaction_dir,
            context,
            observation=observations[0],
        )
        self._approve_workspace_plan(receipt)
        execute_plan = dev_flow.plan_v3_workspace_execute_effect(
            state_value=self.state,
            data_root=self.data,
            task_dir=self.task_dir,
        )
        return plan, execute_plan

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

    def test_plan_and_observer_are_read_only_and_plan_is_frozen(
        self,
    ) -> None:
        before = self._tree_snapshot()
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("planning probed by writing"),
            ),
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError("planning mutated Git"),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("planning wrote a file"),
            ),
        ):
            plan = self._plan()
        self.assertEqual(self._tree_snapshot(), before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.action = "execute"
        with self.assertRaises(TypeError):
            plan.bindings["changed"] = True
        self.assertEqual(
            set(dev_flow.v3_workspace_effect_safe_inputs(plan)),
            {
                "workspace_plan_schema",
                "workspace_action",
                "workspace_mode",
                "workspace_expected_effect_id",
                "workspace_effect_plan_sha256",
                "workspace_repository_ids",
                "approved_binding_sha256",
            },
        )

        transaction_dir, context, observations = (
            self._dispatch_public(
                plan, dev_flow.dispatch_v3_workspace_plan_effect
            )
        )
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("observer probed by writing"),
            ),
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError("observer mutated Git"),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("observer wrote a file"),
            ),
        ):
            receipt, step, observe_contexts = self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
                verify_workspace_read_only=True,
            )
        self.assertFalse(receipt.recovered_lost_response)
        self.assertEqual(step.dispatcher_invocations, 0)
        self.assertIs(
            type(observe_contexts[0]),
            dev_flow.WorkflowActionObserveContext,
        )
        self.assertEqual(
            receipt.attempt_id, observe_contexts[0].attempt_id
        )
        self.assertEqual(
            receipt.observe_context_sha256,
            observe_contexts[0].observe_context_sha256,
        )

    def test_forged_context_is_rejected_before_first_effect(self) -> None:
        plan = self._plan()
        _transaction_dir, context = self._claimed_context(plan)
        with self.assertRaises(dev_flow.FlowError) as observe_error:
            dev_flow.observe_v3_workspace_plan_effect(
                plan, context.plan
            )
        self.assertEqual(
            observe_error.exception.code,
            "WORKSPACE_EFFECT_OBSERVE_CONTEXT_REQUIRED",
        )
        forged = dataclasses.replace(
            context, catalog_contract_sha256="f" * 64
        )
        with mock.patch.object(
            dev_flow, "_workspace_plan", wraps=dev_flow._workspace_plan
        ) as planning:
            with self.assertRaises(dev_flow.FlowError) as raised:
                dev_flow.dispatch_v3_workspace_plan_effect(
                    plan, forged
                )
        self.assertEqual(
            raised.exception.code,
            "WORKSPACE_EFFECT_TRANSACTION_PERMIT_INACTIVE",
        )
        self.assertEqual(planning.call_count, 0)

        borrowed_dir, borrowed = self._claimed_context(
            plan,
            effect_id="full.intake.preflight.v1.effect",
        )

        def borrowed_adapter(active: object) -> object:
            return dev_flow.dispatch_v3_workspace_plan_effect(
                plan, active
            )

        with mock.patch.object(
            dev_flow, "_workspace_plan", wraps=dev_flow._workspace_plan
        ) as planning:
            with self.assertRaises(dev_flow.FlowError) as borrowed_error:
                dev_flow.dispatch_claimed_v3_workflow_action_effect(
                    borrowed_dir,
                    borrowed,
                    authorization=self._authorization(),
                    dispatcher=borrowed_adapter,
                )
        self.assertEqual(
            borrowed_error.exception.code,
            "WORKSPACE_EFFECT_TRANSACTION_PERMIT_MISMATCH",
        )
        self.assertEqual(planning.call_count, 0)

    def test_public_callback_dispatches_exactly_once(self) -> None:
        plan = self._plan()
        with (
            mock.patch.object(
                dev_flow,
                "_workspace_plan",
                wraps=dev_flow._workspace_plan,
            ) as planning,
            mock.patch.object(
                dev_flow,
                "_claim_workspace_plan",
                wraps=dev_flow._claim_workspace_plan,
            ) as claiming,
        ):
            _transaction_dir, _context, observations = (
                self._dispatch_public(
                    plan,
                    dev_flow.dispatch_v3_workspace_plan_effect,
                )
            )
        self.assertEqual(len(observations), 1)
        self.assertEqual(planning.call_count, 1)
        self.assertEqual(claiming.call_count, 1)

    def test_lost_response_observes_durably_and_never_redispatches(
        self,
    ) -> None:
        plan = self._plan()
        effect_count = 0

        def effect(current_plan: object, context: object) -> object:
            nonlocal effect_count
            effect_count += 1
            return dev_flow.dispatch_v3_workspace_plan_effect(
                current_plan, context
            )

        transaction_dir, context, observations = (
            self._dispatch_public(
                plan, effect, lose_response=True
            )
        )
        self.assertEqual(effect_count, 1)
        self.assertEqual(len(observations), 1)
        receipt, observe_step, _observe_contexts = (
            self._observe_public(
                plan,
                transaction_dir,
                context,
            )
        )
        self.assertTrue(receipt.recovered_lost_response)
        self.assertEqual(
            observe_step.status, "OBSERVED_QUARANTINED"
        )
        self.assertEqual(observe_step.dispatcher_invocations, 0)

        def retry(active: object) -> object:
            nonlocal effect_count
            effect_count += 1
            raise AssertionError("already-claimed effect was redispatched")

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
            context.plan.execution_id,
            authorization=self._authorization(),
        )
        self.assertEqual(second.contexts, ())
        self.assertEqual(effect_count, 1)

    def test_plan_observer_rejects_artifact_and_registry_tamper(
        self,
    ) -> None:
        plan = self._plan()
        transaction_dir, context, observations = (
            self._dispatch_public(
                plan, dev_flow.dispatch_v3_workspace_plan_effect
            )
        )
        receipt, _step, _observe_contexts = self._observe_public(
            plan,
            transaction_dir,
            context,
            observation=observations[0],
        )
        registry_path = self.data / "workspace-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["claims"][0]["branch"] = "codex/tampered"
        dev_flow._atomic_write_json(registry_path, registry)
        with self.assertRaises(dev_flow.FlowError):
            self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
            )

        # Restore the claim, then prove digest-addressed bytes are authoritative.
        registry["claims"][0]["branch"] = (
            json.loads(
                Path(str(receipt.observation["artifact_path"])).read_text(
                    encoding="utf-8"
                )
            )["repositories"][0]["branch"]
        )
        dev_flow._atomic_write_json(registry_path, registry)
        artifact_path = Path(str(receipt.observation["artifact_path"]))
        artifact_path.write_bytes(artifact_path.read_bytes() + b" ")
        with self.assertRaises(dev_flow.FlowError):
            self._observe_public(
                plan,
                transaction_dir,
                context,
                observation=observations[0],
            )

    def test_execute_materializes_and_observes_every_repo_read_only(
        self,
    ) -> None:
        _plan, execute_plan = self._planned_and_approved()
        self.assertEqual(
            execute_plan.repository_ids, self.repository_ids
        )
        with mock.patch.object(
            dev_flow,
            "_execute_worktree",
            wraps=dev_flow._execute_worktree,
        ) as execute:
            transaction_dir, context, observations = (
                self._dispatch_public(
                    execute_plan,
                    dev_flow.dispatch_v3_workspace_execute_effect,
                )
            )
        self.assertEqual(execute.call_count, 2)
        with (
            mock.patch.object(
                dev_flow,
                "_probe_worktree_capabilities",
                side_effect=AssertionError("observer probed by writing"),
            ),
            mock.patch.object(
                dev_flow,
                "_git_mutating",
                side_effect=AssertionError("observer mutated Git"),
            ),
            mock.patch.object(
                dev_flow,
                "_atomic_write_bytes",
                side_effect=AssertionError("observer wrote a file"),
            ),
        ):
            receipt, step, _observe_contexts = self._observe_public(
                execute_plan,
                transaction_dir,
                context,
                observation=observations[0],
                verify_workspace_read_only=True,
            )
        self.assertEqual(step.dispatcher_invocations, 0)
        self.assertEqual(
            [
                item["repository_id"]
                for item in receipt.observation["workspaces"]
            ],
            list(self.repository_ids),
        )

    def test_execute_partial_failure_has_no_receipt_or_redispatch(
        self,
    ) -> None:
        _plan, execute_plan = self._planned_and_approved()
        original = dev_flow._execute_worktree
        effect_count = 0

        def partial(item: dict) -> dict:
            nonlocal effect_count
            effect_count += 1
            if effect_count == 2:
                raise dev_flow.FlowError(
                    "INJECTED_PARTIAL_FAILURE",
                    "second repository failed",
                )
            return original(item)

        transaction_dir, context = self._claimed_context(execute_plan)

        def adapter(active: object) -> object:
            typed = dev_flow.dispatch_v3_workspace_execute_effect(
                execute_plan, active
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

        with (
            mock.patch.object(
                dev_flow, "_execute_worktree", side_effect=partial
            ),
            self.assertRaises(dev_flow.FlowError),
        ):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                transaction_dir,
                context,
                authorization=self._authorization(),
                dispatcher=adapter,
            )
        self.assertEqual(effect_count, 2)
        with self.assertRaises(dev_flow.FlowError):
            self._observe_public(
                execute_plan,
                transaction_dir,
                context,
            )
        replay_count = 0

        def retry(active: object) -> object:
            nonlocal replay_count
            replay_count += 1
            raise AssertionError("partial execution was redispatched")

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
        self.assertEqual(replay_count, 0)

    def test_execute_observer_rejects_branch_and_source_drift(
        self,
    ) -> None:
        _plan, execute_plan = self._planned_and_approved()
        transaction_dir, context, observations = (
            self._dispatch_public(
                execute_plan,
                dev_flow.dispatch_v3_workspace_execute_effect,
            )
        )
        first_workspace = Path(
            str(
                execute_plan.bindings["repository_plans"][0][
                    "path"
                ]
            )
        )
        git(first_workspace, "switch", "--detach", "-q")
        with self.assertRaises(dev_flow.FlowError):
            self._observe_public(
                execute_plan,
                transaction_dir,
                context,
                observation=observations[0],
            )

        # Restore the branch, then drift an independent source checkout.
        branch = str(
            execute_plan.bindings["repository_plans"][0]["branch"]
        )
        git(first_workspace, "switch", "-q", branch)
        (self.second / "tracked.txt").write_text(
            "source drift\n", encoding="utf-8"
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            self._observe_public(
                execute_plan,
                transaction_dir,
                context,
                observation=observations[0],
            )
        self.assertEqual(raised.exception.code, "SOURCE_WORKTREE_CHANGED")


if __name__ == "__main__":
    import unittest

    unittest.main()
