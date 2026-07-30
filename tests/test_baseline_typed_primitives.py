from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path
from unittest import mock

from dev_flow_test_case import DevFlowTestCase, dev_flow, git
from test_action_execution_journal import _effect as _journal_effect
from test_action_execution_journal import _sealed_journal
from test_action_execution_journal import _sha


class BaselineTypedPrimitiveTests(DevFlowTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo, self.remote = self.make_repo("typed baseline")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self._identity = 0

    def _artifact_plan(
        self, path: Path | None = None
    ) -> object:
        artifact = path or (self.repo / "artifact.md")
        if not artifact.exists():
            artifact.write_text("evidence\n", encoding="utf-8")
        return dev_flow.plan_v3_record_artifact(
            task_id="task-typed",
            task_revision=4,
            repository_id="repo-a",
            artifact_path=artifact,
            artifact_kind="impact",
        )

    def _context(self, plan: object, **changes: object) -> object:
        self._identity += 1
        token = str(self._identity)
        transaction_plan = dev_flow.ActionDispatchPlan(
            task_id=plan.task_id,
            execution_id="execution-" + token,
            effect_id="effect-" + token,
            claim_id="claim-" + token,
            attempt_id="attempt-" + token,
            journal_revision=1,
            journal_record_sha256="a" * 64,
            index_revision=1,
            index_record_sha256="b" * 64,
            safe_inputs=dev_flow.v3_baseline_effect_safe_inputs(plan),
            required_lock_claims=(),
        )
        context = dev_flow.WorkflowActionDispatchContext(
            plan=transaction_plan,
            effect_kind="filesystem",
            settlement="synchronous-quiescence",
            scopes=dev_flow.v3_baseline_effect_scopes(plan),
            catalog_contract_sha256="c" * 64,
            launch_protocol=dev_flow._WORKFLOW_TX_SYNC_DISPATCH_PROTOCOL,
        )
        return dataclasses.replace(context, **changes)

    def _authorized_dispatch(
        self, plan: object, dispatcher: object
    ) -> tuple[Path, object, object, object]:
        task_dir, context, authorization = self._claimed_context(plan)
        observed: list[object] = []

        def adapter(active: object) -> object:
            receipt = dev_flow.dispatch_v3_baseline_effect(
                plan, active, dispatcher
            )
            observed.append(receipt)
            transaction_plan = active.plan
            return dev_flow.WorkflowActionEffectObservation(
                task_id=transaction_plan.task_id,
                execution_id=transaction_plan.execution_id,
                effect_id=transaction_plan.effect_id,
                claim_id=transaction_plan.claim_id,
                attempt_id=transaction_plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=receipt.semantic_sha256,
            )
        dev_flow.dispatch_claimed_v3_workflow_action_effect(
            task_dir,
            context,
            authorization=authorization,
            dispatcher=adapter,
        )
        self.assertEqual(len(observed), 1)
        return task_dir, context, authorization, observed[0]

    def _authorized_observe(
        self,
        plan: object,
        dispatched: tuple[Path, object, object, object],
        observer: object,
    ) -> tuple[object, object]:
        task_dir, context, authorization, dispatch_observation = (
            dispatched
        )
        receipts: list[object] = []

        def adapter(active: object) -> object:
            before = self._tree_snapshot()
            receipt = observer(
                plan, active, dispatch_observation
            )
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
            task_dir,
            context.plan.execution_id,
            context.plan.effect_id,
            authorization=authorization,
            observer=adapter,
        )
        self.assertEqual(len(receipts), 1)
        return receipts[0], step

    @staticmethod
    def _authorization() -> object:
        return dev_flow.WorkflowActionAuthorization(
            kind="operator",
            authorization_sha256=_sha("authorization"),
            capability_sha256=None,
            request_nonce_sha256=_sha("request-nonce"),
            principal="manager:test",
            ownership_sha256=_sha("ownership"),
            registry_state_sha256=_sha("registry-state"),
            reauthenticate=lambda: None,
        )

    def _claimed_context(
        self, plan: object
    ) -> tuple[Path, object, object]:
        self._identity += 1
        execution_id = "baseline-primitive-" + str(self._identity)
        task_dir = self.root / "action-transactions" / execution_id
        task_dir.mkdir(mode=0o700, parents=True)
        effect = _journal_effect(
            "effect-a",
            repository_id=plan.repository_id,
            path=next(iter(dev_flow.v3_baseline_effect_scopes(plan)["paths"])),
        )
        effect["scopes"] = dev_flow.v3_baseline_effect_scopes(plan)
        effect["safe_inputs"] = dev_flow.v3_baseline_effect_safe_inputs(
            plan
        )
        effect["safe_input_sha256"] = dev_flow.semantic_sha256(
            dev_flow.SAFE_INPUT_DOMAIN, effect["safe_inputs"]
        )
        record = _sealed_journal(
            task_id=plan.task_id,
            execution_id=execution_id,
            effects=[effect],
            authorization_kind="operator",
        )
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        authoritative_state = {
            "schema_version": 3,
            "task_id": plan.task_id,
            "revision": 7,
            "status": "INTAKE",
            "flow": "full",
            "repositories": [],
            "route": None,
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    plan.task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            ),
        }
        dev_flow._atomic_write_json(
            task_dir / "state.json", authoritative_state
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
            journal_core, manager_secret=None
        )
        store = dev_flow.ActionExecutionStore(task_dir)
        initialized = store.initialize_index(plan.task_id)
        store.persist_initial(
            record,
            expected_index=dev_flow.cas_token(initialized.index),
        )
        authorization = self._authorization()
        claimed = dev_flow.claim_ready_v3_workflow_action_effects(
            task_dir,
            execution_id,
            authorization=authorization,
            claim_id_factory=lambda _effect_id: "claim-" + execution_id,
        )
        self.assertEqual(len(claimed.contexts), 1)
        return task_dir, claimed.contexts[0], authorization

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

    def test_plan_and_observe_are_zero_write_and_plans_are_frozen(
        self,
    ) -> None:
        artifact = self.root / "impact.json"
        artifact.write_text('{"coverage":"complete"}\n', encoding="utf-8")
        destination = self.root / "analysis" / "repo-a"
        redacted_url = dev_flow._redact_sensitive_text(str(self.remote))
        remote_sha = dev_flow._sensitive_value_sha256(str(self.remote))
        assert remote_sha is not None
        pre_ref = git(
            self.repo, "rev-parse", "refs/remotes/origin/main"
        )
        external_receipt = {
            "schema": "codebase-memory-index-receipt/v1",
            "phase": "baseline",
            "source_role": "baseline",
            "generation": 0,
            "repository_id": "repo-a",
            "project_id": "baseline-project-a",
            "source_snapshot_sha": self.head,
            "receipt_sha256": "d" * 64,
        }
        git(self.repo, "switch", "-q", "--detach", self.head)
        before = self._tree_snapshot()
        with mock.patch.object(
            dev_flow,
            "_git_mutating",
            side_effect=AssertionError("plan attempted a Git write"),
        ):
            fetch_plan = dev_flow.plan_v3_baseline_fetch(
                task_id="task-typed",
                task_revision=4,
                repository_id="repo-a",
                repository_path=self.repo,
                remote="origin",
                remote_url=redacted_url,
                remote_url_sha256=remote_sha,
                refspec="+refs/heads/main:refs/remotes/origin/main",
                source_ref="refs/remotes/origin/main",
                pre_head_sha=self.head,
                pre_ref_sha=pre_ref,
            )
            material_plan = dev_flow.plan_v3_baseline_materialization(
                task_id="task-typed",
                task_revision=4,
                repository_id="repo-a",
                source_path=self.repo,
                destination_path=destination,
                base_sha=self.head,
            )
            index_plan = dev_flow.plan_v3_record_index(
                task_id="task-typed",
                task_revision=4,
                repository_id="repo-a",
                phase="baseline",
                source_role="baseline",
                generation=0,
                project_id="baseline-project-a",
                source_path=self.repo,
                source_snapshot_sha=self.head,
                external_receipt=external_receipt,
            )
            artifact_plan = dev_flow.plan_v3_record_artifact(
                task_id="task-typed",
                task_revision=4,
                repository_id="repo-a",
                artifact_path=artifact,
                artifact_kind="impact",
            )
            repeated_artifact_plan = dev_flow.plan_v3_record_artifact(
                task_id="task-typed",
                task_revision=4,
                repository_id="repo-a",
                artifact_path=artifact,
                artifact_kind="impact",
            )
        self.assertEqual(self._tree_snapshot(), before)
        self.assertEqual(
            artifact_plan.semantic_sha256,
            repeated_artifact_plan.semantic_sha256,
        )
        for plan in (
            fetch_plan,
            material_plan,
            index_plan,
            artifact_plan,
        ):
            with self.assertRaises(dataclasses.FrozenInstanceError):
                plan.action = "changed"
            with self.assertRaises(TypeError):
                plan.bindings["changed"] = True

        git(
            self.repo,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            "--detach",
            str(destination),
            self.head,
        )
        material_dispatched = self._authorized_dispatch(
            material_plan, lambda _plan: {"created": True}
        )
        with mock.patch.object(
            dev_flow,
            "_git_mutating",
            side_effect=AssertionError("observe attempted a Git write"),
        ):
            receipt, observed_step = self._authorized_observe(
                material_plan,
                material_dispatched,
                dev_flow.observe_v3_baseline_materialization,
            )
        self.assertEqual(observed_step.status, "VERIFIED")
        self.assertTrue(receipt.observation["detached"])
        self.assertTrue(receipt.observation["clean"])
        git(destination, "switch", "-q", "-c", "drift")

        task_dir, context, authorization, material_observation = (
            material_dispatched
        )

        def drift_observer(active: object) -> object:
            receipt = dev_flow.observe_v3_baseline_materialization(
                material_plan, active, material_observation
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

        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow.observe_v3_workflow_action_effect(
                task_dir,
                context.plan.execution_id,
                context.plan.effect_id,
                authorization=authorization,
                observer=drift_observer,
            )
        self.assertEqual(
            raised.exception.code,
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
        )

    def test_semantic_json_unicode_and_int64_match_journal_contract(
        self,
    ) -> None:
        valid = {"é": (1 << 63) - 1, "minimum": -(1 << 63)}
        self.assertEqual(
            dev_flow._v3_baseline_semantic_bytes(valid),
            dev_flow.semantic_json_bytes(valid),
        )
        for invalid in (
            {"too_large": 1 << 63},
            {"not_nfc": "e\u0301"},
        ):
            with self.assertRaises(
                dev_flow.ActionExecutionJournalError
            ) as journal_error:
                dev_flow.semantic_json_bytes(invalid)
            with self.assertRaises(dev_flow.FlowError) as baseline_error:
                dev_flow._v3_baseline_semantic_bytes(invalid)
            self.assertEqual(
                baseline_error.exception.details["cause_code"],
                journal_error.exception.code,
            )

    def test_transaction_authority_rejects_forgery_copy_replay_and_drift(
        self,
    ) -> None:
        plan = self._artifact_plan()
        invocation_count = 0

        def effect(_plan: object) -> dict[str, object]:
            nonlocal invocation_count
            invocation_count += 1
            return {}

        forged = self._context(plan)
        for candidate in (
            forged,
            copy.copy(forged),
            dataclasses.replace(forged),
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                dev_flow.dispatch_v3_baseline_effect(
                    plan, candidate, effect
                )
            self.assertEqual(
                raised.exception.code,
                "BASELINE_EFFECT_TRANSACTION_PERMIT_INACTIVE",
            )
        with self.assertRaises(dev_flow.FlowError):
            dev_flow.dispatch_v3_baseline_effect(plan, None, effect)
        self.assertEqual(invocation_count, 0)

        private_enter = self._context(plan)
        with self.assertRaises(dev_flow.WorkflowActionTransactionError):
            with dev_flow._workflow_tx_active_dispatch(private_enter):
                pass

        task_dir, valid, authorization = self._claimed_context(plan)

        def valid_adapter(active: object) -> object:
            receipt = dev_flow.dispatch_v3_baseline_effect(
                plan, active, effect
            )
            transaction_plan = active.plan
            return dev_flow.WorkflowActionEffectObservation(
                task_id=transaction_plan.task_id,
                execution_id=transaction_plan.execution_id,
                effect_id=transaction_plan.effect_id,
                claim_id=transaction_plan.claim_id,
                attempt_id=transaction_plan.attempt_id,
                settlement="QUIESCED",
                receipt_sha256=receipt.semantic_sha256,
            )

        dev_flow.dispatch_claimed_v3_workflow_action_effect(
            task_dir,
            valid,
            authorization=authorization,
            dispatcher=valid_adapter,
        )
        with self.assertRaises(dev_flow.FlowError):
            dev_flow.dispatch_v3_baseline_effect(plan, valid, effect)
        self.assertEqual(invocation_count, 1)

        transforms = (
            lambda active: dataclasses.replace(
                active,
                plan=dataclasses.replace(
                    active.plan,
                    safe_inputs={"baseline_plan_sha256": "e" * 64},
                ),
            ),
            lambda active: dataclasses.replace(
                active,
                scopes=dev_flow.normalize_scopes(
                    {
                        "repository_ids": ["repo-b"],
                        "node_ids": [],
                        "worktree_ids": [],
                        "lease_ids": [],
                        "paths": [],
                        "external_resources": [],
                    }
                ),
            ),
            lambda active: dataclasses.replace(
                active,
                plan=dataclasses.replace(
                    active.plan,
                    journal_record_sha256="not-a-digest",
                ),
            ),
            lambda active: dataclasses.replace(
                active, catalog_contract_sha256="not-a-digest"
            ),
            lambda active: dataclasses.replace(
                active,
                settlement="asynchronous-handoff",
                launch_protocol=(
                    dev_flow._WORKFLOW_TX_RUNTIME_LAUNCH_PROTOCOL
                ),
            ),
        )
        for transform in transforms:
            drift_dir, drift, drift_authorization = (
                self._claimed_context(plan)
            )

            def reject_drift(active: object) -> object:
                candidate = transform(active)
                with self.assertRaises(dev_flow.FlowError):
                    dev_flow.dispatch_v3_baseline_effect(
                        plan, candidate, effect
                    )
                transaction_plan = active.plan
                return dev_flow.WorkflowActionEffectObservation(
                    task_id=transaction_plan.task_id,
                    execution_id=transaction_plan.execution_id,
                    effect_id=transaction_plan.effect_id,
                    claim_id=transaction_plan.claim_id,
                    attempt_id=transaction_plan.attempt_id,
                    settlement="QUIESCED",
                    receipt_sha256="f" * 64,
                )
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                drift_dir,
                drift,
                authorization=drift_authorization,
                dispatcher=reject_drift,
            )
        self.assertEqual(invocation_count, 1)

    def test_lost_response_cannot_open_a_second_effect_invocation(
        self,
    ) -> None:
        plan = self._artifact_plan()
        task_dir, context, authorization = self._claimed_context(plan)
        invocation_count = 0

        def effect(_plan: object) -> None:
            nonlocal invocation_count
            invocation_count += 1
            raise ConnectionError("response lost after effect")

        with self.assertRaises(ConnectionError):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                task_dir,
                context,
                authorization=authorization,
                dispatcher=lambda active: (
                    dev_flow.dispatch_v3_baseline_effect(
                        plan, active, effect
                    )
                ),
            )
        with self.assertRaises(
            (
                dev_flow.WorkflowActionTransactionError,
                dev_flow.ActionExecutionJournalError,
            )
        ):
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                task_dir,
                context,
                authorization=authorization,
                dispatcher=lambda active: (
                    dev_flow.dispatch_v3_baseline_effect(
                        plan, active, effect
                    )
                ),
            )
        self.assertEqual(invocation_count, 1)
        receipts: list[object] = []

        def observe_after_restart(active: object) -> object:
            receipt = dev_flow.observe_v3_record_artifact(
                plan, active
            )
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

        recovered = dev_flow.observe_v3_workflow_action_effect(
            task_dir,
            context.plan.execution_id,
            context.plan.effect_id,
            authorization=authorization,
            observer=observe_after_restart,
        )
        self.assertEqual(recovered.status, "OBSERVED_QUARANTINED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        self.assertEqual(invocation_count, 1)
        self.assertEqual(len(receipts), 1)

    def test_observer_requires_active_exact_transaction_context(
        self,
    ) -> None:
        plan = self._artifact_plan()
        dispatched = self._authorized_dispatch(
            plan, lambda _plan: {}
        )
        task_dir, context, authorization, dispatch_observation = (
            dispatched
        )
        captured: list[object] = []
        receipt_count = 0

        def adapter(active: object) -> object:
            nonlocal receipt_count
            captured.append(active)
            for forged in (
                dataclasses.replace(
                    active, claim_id="forged-claim"
                ),
                dataclasses.replace(
                    active, attempt_id="forged-attempt"
                ),
                dataclasses.replace(
                    active, index_record_sha256="0" * 64
                ),
                dataclasses.replace(
                    active,
                    containment_revision=(
                        active.containment_revision + 1
                    ),
                ),
            ):
                with self.assertRaises(dev_flow.FlowError) as raised:
                    dev_flow.observe_v3_record_artifact(
                        plan, forged, dispatch_observation
                    )
                self.assertEqual(
                    raised.exception.code,
                    "BASELINE_EFFECT_OBSERVE_CONTEXT_INACTIVE",
                )
            receipt = dev_flow.observe_v3_record_artifact(
                plan, active, dispatch_observation
            )
            receipt_count += 1
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
            task_dir,
            context.plan.execution_id,
            context.plan.effect_id,
            authorization=authorization,
            observer=adapter,
        )
        self.assertEqual(step.status, "VERIFIED")
        self.assertEqual(receipt_count, 1)
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow.observe_v3_record_artifact(
                plan, captured[0], dispatch_observation
            )
        self.assertEqual(
            raised.exception.code,
            "BASELINE_EFFECT_OBSERVE_CONTEXT_INACTIVE",
        )

    def test_credential_url_never_enters_serialized_or_error_surfaces(
        self,
    ) -> None:
        secret_values = (
            "credential-user",
            "password-value",
            "top-secret-token",
        )
        raw_url = (
            "https://credential-user:password-value@example.invalid/"
            "repository.git?token=top-secret-token"
        )
        git(self.repo, "remote", "set-url", "origin", raw_url)
        redacted_url = dev_flow._redact_sensitive_text(raw_url)
        remote_sha = dev_flow._sensitive_value_sha256(raw_url)
        assert remote_sha is not None
        pre_ref = git(
            self.repo, "rev-parse", "refs/remotes/origin/main"
        )
        plan = dev_flow.plan_v3_baseline_fetch(
            task_id="task-secret",
            task_revision=7,
            repository_id="repo-a",
            repository_path=self.repo,
            remote="origin",
            remote_url=redacted_url,
            remote_url_sha256=remote_sha,
            refspec="+refs/heads/main:refs/remotes/origin/main",
            source_ref="refs/remotes/origin/main",
            pre_head_sha=self.head,
            pre_ref_sha=pre_ref,
        )
        dispatched = self._authorized_dispatch(
            plan,
            lambda _plan: {
                "remote_url": redacted_url,
                "remote_url_sha256": remote_sha,
            },
        )
        receipt, _step = self._authorized_observe(
            plan, dispatched, dev_flow.observe_v3_baseline_fetch
        )
        observation = dispatched[3]
        serializable = json.dumps(
            {
                "plan": plan.as_dict(),
                "journal_safe_inputs": (
                    dev_flow.v3_baseline_effect_safe_inputs(plan)
                ),
                "observation": dict(observation.result),
                "receipt": receipt.as_dict(),
            },
            sort_keys=True,
        )
        surfaces = [
            serializable,
            repr(plan),
            repr(observation),
            repr(receipt),
        ]

        changed_url = (
            "https://other-user:other-password@example.invalid/"
            "repository.git?token=other-token"
        )
        git(self.repo, "remote", "set-url", "origin", changed_url)
        task_dir, context, authorization = self._claimed_context(plan)
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow.dispatch_claimed_v3_workflow_action_effect(
                task_dir,
                context,
                authorization=authorization,
                dispatcher=lambda active: (
                    dev_flow.dispatch_v3_baseline_fetch(plan, active)
                ),
            )
        surfaces.extend(
            [
                repr(raised.exception),
                str(raised.exception),
                json.dumps(
                    {
                        "code": raised.exception.code,
                        "message": raised.exception.message,
                        "details": raised.exception.details,
                    },
                    sort_keys=True,
                ),
            ]
        )
        combined = "\n".join(surfaces)
        for secret in (*secret_values, "other-user", "other-password", "other-token"):
            self.assertNotIn(secret, combined)

    def test_wrong_index_binding_and_changed_artifact_fail_observation(
        self,
    ) -> None:
        external_receipt = {
            "schema": "codebase-memory-index-receipt/v1",
            "phase": "baseline",
            "source_role": "baseline",
            "generation": 0,
            "repository_id": "repo-a",
            "project_id": "baseline-project-a",
            "source_snapshot_sha": self.head,
            "receipt_sha256": "d" * 64,
        }
        git(self.repo, "switch", "-q", "--detach", self.head)
        index_plan = dev_flow.plan_v3_record_index(
            task_id="task-index",
            task_revision=2,
            repository_id="repo-a",
            phase="baseline",
            source_role="baseline",
            generation=0,
            project_id="baseline-project-a",
            source_path=self.repo,
            source_snapshot_sha=self.head,
            external_receipt=external_receipt,
        )
        accepted = self._authorized_dispatch(
            index_plan,
            lambda _plan: {
                "phase": "baseline",
                "source_role": "baseline",
                "generation": 0,
                "project_id": "baseline-project-a",
            },
        )
        index_receipt, _step = self._authorized_observe(
            index_plan, accepted, dev_flow.observe_v3_record_index
        )
        self.assertEqual(
            index_receipt.observation["evidence_classification"],
            "discovery-evidence",
        )
        self.assertFalse(index_receipt.observation["coverage_proof"])
        wrong = self._authorized_dispatch(
            index_plan,
            lambda _plan: {
                "phase": "baseline",
                "source_role": "baseline",
                "generation": 0,
                "project_id": "wrong-project",
            },
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            self._authorized_observe(
                index_plan, wrong, dev_flow.observe_v3_record_index
            )
        self.assertEqual(
            raised.exception.code, "INDEX_OBSERVATION_MISMATCH"
        )

        artifact = self.repo / "bound-artifact.txt"
        artifact.write_text("before\n", encoding="utf-8")
        artifact_plan = self._artifact_plan(artifact)
        artifact_observation = self._authorized_dispatch(
            artifact_plan, lambda _plan: {}
        )
        artifact.write_text("after\n", encoding="utf-8")
        with self.assertRaises(dev_flow.FlowError) as raised:
            self._authorized_observe(
                artifact_plan,
                artifact_observation,
                dev_flow.observe_v3_record_artifact,
            )
        self.assertEqual(raised.exception.code, "ARTIFACT_CHANGED")


if __name__ == "__main__":
    import unittest

    unittest.main()
