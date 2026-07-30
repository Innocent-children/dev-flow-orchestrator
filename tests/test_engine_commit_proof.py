from __future__ import annotations

import copy
import contextvars
import dataclasses
import json
import pickle
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow

from tests.test_transition_kernel_invariants import (
    WORKFLOW_REF,
    canonical_graph,
    engine,
    passing_guard,
    status_reducer,
    task_state,
)


class EngineCommitProofUnitTests(unittest.TestCase):
    def _evaluation(self) -> object:
        graph = canonical_graph()
        evidence = {"fingerprint": "c" * 64}
        workflow = engine.TransitionEngine(
            graph,
            guard_resolver=lambda identifier, _version: {
                "guard.current/v1": passing_guard
            }[identifier],
            reducer_resolver=lambda identifier, _version: {
                "reducer.status/v1": status_reducer
            }[identifier],
        )
        context = engine.KernelTransitionContext(
            task_id="task-v3",
            workflow_ref=WORKFLOW_REF,
            task_lock_held=True,
            workspace_lock_held=False,
            ownership_lock_held=False,
            evidence_sha256=engine._sha256_contract(evidence),
            evidence_authentic=True,
            evidence_current=True,
            supported_node_contracts={"state": ("v1",)},
            supported_contract_versions={
                "guards:guard.current/v1": ("v1",),
                "reducers:reducer.status/v1": ("v1",),
                "executors:executor.deterministic/v1": ("v1",),
            },
            authorized_effects=("task-state",),
        )
        preview = workflow.evaluate(
            task_state(),
            expected_revision=4,
            action_id="transition",
            action_parameters={},
            evidence=evidence,
            preview=True,
            kernel_context=context,
        )
        return workflow.evaluate(
            task_state(),
            expected_revision=4,
            action_id="transition",
            action_parameters={},
            evidence=evidence,
            confirm_intent=preview.intent["intent_id"],
            preview=False,
            kernel_context=context,
        )

    def test_only_exact_kernel_evaluation_has_one_shot_issuance(
        self,
    ) -> None:
        evaluation = self._evaluation()
        constructed = engine.TransitionEvaluation(
            edge_id=evaluation.edge_id,
            source=evaluation.source,
            target=evaluation.target,
            intent=evaluation.intent,
            candidate_state=evaluation.candidate_state,
            changed_paths=evaluation.changed_paths,
            guard_results=evaluation.guard_results,
            audit_facts=evaluation.audit_facts,
        )
        replaced = dataclasses.replace(evaluation)
        copied = copy.copy(evaluation)
        with self.assertRaises(TypeError):
            copy.deepcopy(evaluation)

        for forged in (constructed, replaced, copied):
            with self.assertRaises(
                engine.TransitionEngineError
            ) as raised:
                engine._transition_engine_consume_evaluation_issuance(
                    forged
                )
            self.assertEqual(
                raised.exception.code,
                "V3_ENGINE_EVALUATION_UNREGISTERED",
            )

        issuance = (
            engine._transition_engine_consume_evaluation_issuance(
                evaluation
            )
        )
        self.assertEqual(issuance["task_id"], "task-v3")
        self.assertEqual(
            issuance["evaluation"]["edge_id"],
            "full.intake.ready",
        )
        with self.assertRaises(engine.TransitionEngineError) as replay:
            engine._transition_engine_consume_evaluation_issuance(
                evaluation
            )
        self.assertEqual(
            replay.exception.code,
            "V3_ENGINE_EVALUATION_UNREGISTERED",
        )

    def test_proof_is_opaque_nonserializable_and_one_shot(
        self,
    ) -> None:
        with self.assertRaises(TypeError):
            engine.EngineCommitProof()
        proof = engine._engine_commit_proof_issue(
            {"contract": "test/v1", "payload": {"value": 1}}
        )
        self.assertEqual(repr(proof), "<EngineCommitProof opaque>")
        for operation in (
            lambda: copy.copy(proof),
            lambda: copy.deepcopy(proof),
            lambda: pickle.dumps(proof),
            lambda: json.dumps(proof),
            lambda: dataclasses.replace(proof),
        ):
            with self.assertRaises(TypeError):
                operation()

        consumed = engine._engine_commit_proof_consume(
            proof, {"payload": {"value": 1}}
        )
        self.assertEqual(consumed["payload"], {"value": 1})
        with self.assertRaises(engine.TransitionEngineError) as replay:
            engine._engine_commit_proof_consume(
                proof, {"payload": {"value": 1}}
            )
        self.assertEqual(
            replay.exception.code,
            "V3_ENGINE_COMMIT_PROOF_REPLAYED",
        )

    def test_digest_copy_cannot_steal_registered_proof(
        self,
    ) -> None:
        proof = engine._engine_commit_proof_issue(
            {"contract": "test/v1", "payload": {"value": 2}}
        )
        forged = object.__new__(engine.EngineCommitProof)
        object.__setattr__(
            forged,
            "_EngineCommitProof__issuance_id",
            object.__getattribute__(
                proof, "_EngineCommitProof__issuance_id"
            ),
        )
        object.__setattr__(
            forged,
            "_EngineCommitProof__mac",
            object.__getattribute__(proof, "_EngineCommitProof__mac"),
        )
        with self.assertRaises(engine.TransitionEngineError) as raised:
            engine._engine_commit_proof_consume(
                forged, {"payload": {"value": 2}}
            )
        self.assertEqual(
            raised.exception.code, "V3_ENGINE_COMMIT_PROOF_INVALID"
        )
        engine._engine_commit_proof_consume(
            proof, {"payload": {"value": 2}}
        )

    def test_wrong_binding_and_cross_thread_failure_burn_proof(
        self,
    ) -> None:
        wrong = engine._engine_commit_proof_issue(
            {"contract": "test/v1", "payload": {"value": 3}}
        )
        with self.assertRaises(engine.TransitionEngineError) as mismatch:
            engine._engine_commit_proof_consume(
                wrong, {"payload": {"value": 4}}
            )
        self.assertEqual(
            mismatch.exception.code,
            "V3_ENGINE_COMMIT_PROOF_MISMATCH",
        )
        with self.assertRaises(engine.TransitionEngineError) as replay:
            engine._engine_commit_proof_consume(
                wrong, {"payload": {"value": 3}}
            )
        self.assertEqual(
            replay.exception.code,
            "V3_ENGINE_COMMIT_PROOF_REPLAYED",
        )

        main_thread = threading.get_ident()
        cross_thread = engine._engine_commit_proof_issue(
            {
                "contract": "test/v1",
                "controller_thread_id": main_thread,
            }
        )
        failures: list[str] = []

        def consume_elsewhere() -> None:
            try:
                engine._engine_commit_proof_consume(
                    cross_thread,
                    {"controller_thread_id": threading.get_ident()},
                )
            except engine.TransitionEngineError as exc:
                failures.append(exc.code)

        worker = threading.Thread(target=consume_elsewhere)
        worker.start()
        worker.join()
        self.assertEqual(
            failures, ["V3_ENGINE_COMMIT_PROOF_MISMATCH"]
        )
        with self.assertRaises(engine.TransitionEngineError) as replay:
            engine._engine_commit_proof_consume(
                cross_thread,
                {"controller_thread_id": main_thread},
            )
        self.assertEqual(
            replay.exception.code,
            "V3_ENGINE_COMMIT_PROOF_REPLAYED",
        )

    def test_process_restart_has_new_key_and_empty_registry(
        self,
    ) -> None:
        proof = engine._engine_commit_proof_issue(
            {"contract": "test/v1", "payload": {"value": 5}}
        )
        issuance_id = object.__getattribute__(
            proof, "_EngineCommitProof__issuance_id"
        )
        mac = object.__getattribute__(
            proof, "_EngineCommitProof__mac"
        )
        module_path = Path(str(engine.__file__)).resolve()
        child = """
import importlib.util
import sys
path, issuance_id, supplied_mac = sys.argv[1:]
spec = importlib.util.spec_from_file_location("restart_engine", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
forged = object.__new__(module.EngineCommitProof)
object.__setattr__(
    forged, "_EngineCommitProof__issuance_id", issuance_id
)
object.__setattr__(forged, "_EngineCommitProof__mac", supplied_mac)
try:
    module._engine_commit_proof_consume(
        forged, {"payload": {"value": 5}}
    )
except module.TransitionEngineError as error:
    print(error.code)
else:
    print("UNEXPECTED_ACCEPT")
"""
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-I",
                "-S",
                "-c",
                child,
                str(module_path),
                str(issuance_id),
                str(mac),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "V3_ENGINE_COMMIT_PROOF_REPLAYED",
        )
        # The failed restarted-process replay cannot consume the authority
        # that remains registered only in this original controller process.
        engine._engine_commit_proof_consume(
            proof, {"payload": {"value": 5}}
        )


class EngineCommitProofBoundaryTests(DevFlowTestCase):
    def _active_lite_services(self) -> object:
        services = dev_flow.workflow_runtime_services()
        activations = []
        for frozen in services.catalog.activations:
            item = dict(frozen)
            active = (
                item["workflow_id"] == "lite"
                and item["workflow_version"] == 3
                and item["execution_profile"]
                == "single-repository"
            )
            item["active"] = active
            item["required_suites"] = (
                sorted(
                    {
                        *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            "single-repository"
                        ],
                        *{
                            str(suite)
                            for edge in services.catalog.resolve(
                                "lite", 3
                            ).action_edges
                            for suite in edge["required_suites"]
                        },
                    }
                )
                if active
                else []
            )
            activations.append(MappingProxyType(item))
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=tuple(activations),
            ),
        )

    def _start_v3(self, task_id: str) -> dict:
        repository, _remote = self.make_repo(f"{task_id}-repository")
        with mock.patch.object(
            dev_flow,
            "_workflow_runtime_services",
            self._active_lite_services(),
        ):
            started = self.cli(
                "start",
                "exercise durable engine proof",
                "--repo",
                str(repository),
                "--task-id",
                task_id,
                "--workspace-strategy",
                "in-place",
                "--change-category",
                "docs",
                "--target-path",
                "tracked.txt",
            )
        persisted = dev_flow.load_state(task_id, self.data)
        self.assertEqual(persisted["schema_version"], 3)
        return started

    def _blocked_evaluation(
        self, current: dict
    ) -> tuple[object, dict, dict, tuple]:
        note = "wait for a current decision"
        parameters = {
            "from": current["status"],
            "to": "BLOCKED",
            "note": note,
        }
        records = {
            "blocked": {
                "phase": "manual",
                "from_status": current["status"],
                "reason": note,
                "details": [],
                "at": current["updated_at"],
            }
        }
        preview = dev_flow.evaluate_v3_command_movement(
            current,
            target="BLOCKED",
            event_type="state_transitioned",
            action_id="transition",
            action_parameters=parameters,
            state_records=records,
            preview=True,
        )
        evaluation = dev_flow.evaluate_v3_command_movement(
            current,
            target="BLOCKED",
            event_type="state_transitioned",
            action_id="transition",
            action_parameters=parameters,
            state_records=records,
            confirm_intent=preview.intent["intent_id"],
            preview=False,
        )
        candidate = copy.deepcopy(
            dev_flow._workflow_transition_public(
                evaluation.candidate_state
            )
        )
        payload = {
            **parameters,
            "action": "transition",
            "intent_id": evaluation.intent["intent_id"],
            "confirmation_mode": evaluation.intent[
                "confirmation_mode"
            ],
            "evidence_sha256": evaluation.intent[
                "evidence_sha256"
            ],
        }
        linked = dev_flow.workflow_transition_audit_events(
            evaluation
        )
        return evaluation, candidate, payload, linked

    def _locks(self, task_id: str) -> object:
        task_dir = dev_flow._task_dir(task_id, self.data)
        return (
            task_dir,
            dev_flow._task_lock(task_dir),
            dev_flow._workspace_registry_lock(
                dev_flow.resolve_data_dir(self.data)
            ),
        )

    def test_raw_and_commit_boundaries_reject_unproved_v3_diff(
        self,
    ) -> None:
        started = self._start_v3("proof-required")
        current = dev_flow.load_state(started["task_id"], self.data)
        candidate = copy.deepcopy(current)
        candidate["requirement"] = "forged replacement"
        task_dir, task_lock, workspace_lock = self._locks(
            started["task_id"]
        )
        with task_lock, workspace_lock:
            with self.assertRaises(dev_flow.FlowError) as raw:
                dev_flow._persist_state_transaction(
                    current,
                    copy.deepcopy(candidate),
                    task_dir,
                    "forged_state",
                    {"value": "forged"},
                )
            self.assertEqual(
                raw.exception.code,
                "V3_ENGINE_COMMIT_PROOF_INVALID",
            )
            with self.assertRaises(dev_flow.FlowError) as commit:
                dev_flow._commit_state(
                    current,
                    copy.deepcopy(candidate),
                    task_dir,
                    "forged_state",
                    {"value": "forged"},
                )
            self.assertEqual(
                commit.exception.code,
                "V3_ENGINE_COMMIT_PROOF_REQUIRED",
            )
        unchanged = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(unchanged["revision"], current["revision"])
        self.assertNotEqual(
            unchanged["requirement"], "forged replacement"
        )

    def test_public_evaluation_copy_cannot_mint_but_original_can(
        self,
    ) -> None:
        started = self._start_v3("proof-public-evaluation")
        task_dir, task_lock, workspace_lock = self._locks(
            started["task_id"]
        )
        with task_lock, workspace_lock:
            current = dev_flow.load_state(
                started["task_id"], self.data
            )
            evaluation, candidate, payload, linked = (
                self._blocked_evaluation(current)
            )
            copied = dataclasses.replace(evaluation)
            with self.assertRaises(
                dev_flow.TransitionEngineError
            ) as forged:
                dev_flow._workflow_transition_mint_engine_commit_proof(
                    current,
                    copied,
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                )
            self.assertEqual(
                forged.exception.code,
                "V3_ENGINE_EVALUATION_UNREGISTERED",
            )
            proof = (
                dev_flow._workflow_transition_mint_engine_commit_proof(
                    current,
                    evaluation,
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                )
            )
            event = dev_flow._persist_state_transaction(
                current,
                candidate,
                task_dir,
                "state_transitioned",
                payload,
                additional_events=linked,
                _engine_commit_proof=proof,
            )
        self.assertEqual(event["revision"], current["revision"] + 1)
        persisted = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(persisted["status"], "BLOCKED")

    def test_wrong_payload_burns_proof_and_replay_is_zero_write(
        self,
    ) -> None:
        started = self._start_v3("proof-wrong-payload")
        task_dir, task_lock, workspace_lock = self._locks(
            started["task_id"]
        )
        with task_lock, workspace_lock:
            current = dev_flow.load_state(
                started["task_id"], self.data
            )
            evaluation, candidate, payload, linked = (
                self._blocked_evaluation(current)
            )
            proof = (
                dev_flow._workflow_transition_mint_engine_commit_proof(
                    current,
                    evaluation,
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                )
            )
            wrong_payload = {**payload, "note": "changed after proof"}
            with self.assertRaises(dev_flow.FlowError) as mismatch:
                dev_flow._persist_state_transaction(
                    current,
                    copy.deepcopy(candidate),
                    task_dir,
                    "state_transitioned",
                    wrong_payload,
                    additional_events=linked,
                    _engine_commit_proof=proof,
                )
            self.assertEqual(
                mismatch.exception.code,
                "V3_ENGINE_COMMIT_PROOF_MISMATCH",
            )
            with self.assertRaises(dev_flow.FlowError) as replay:
                dev_flow._persist_state_transaction(
                    current,
                    copy.deepcopy(candidate),
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                    _engine_commit_proof=proof,
                )
            self.assertEqual(
                replay.exception.code,
                "V3_ENGINE_COMMIT_PROOF_REPLAYED",
            )
        unchanged = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(unchanged["revision"], current["revision"])
        self.assertEqual(unchanged["status"], current["status"])

    def test_copied_lock_context_cannot_move_proof_to_thread(
        self,
    ) -> None:
        started = self._start_v3("proof-cross-thread")
        task_dir, task_lock, workspace_lock = self._locks(
            started["task_id"]
        )
        failures: list[str] = []
        with task_lock, workspace_lock:
            current = dev_flow.load_state(
                started["task_id"], self.data
            )
            evaluation, candidate, payload, linked = (
                self._blocked_evaluation(current)
            )
            proof = (
                dev_flow._workflow_transition_mint_engine_commit_proof(
                    current,
                    evaluation,
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                )
            )
            copied_context = contextvars.copy_context()

            def consume() -> None:
                try:
                    dev_flow._persist_state_transaction(
                        current,
                        copy.deepcopy(candidate),
                        task_dir,
                        "state_transitioned",
                        payload,
                        additional_events=linked,
                        _engine_commit_proof=proof,
                    )
                except dev_flow.FlowError as exc:
                    failures.append(exc.code)

            worker = threading.Thread(
                target=lambda: copied_context.run(consume)
            )
            worker.start()
            worker.join()
            with self.assertRaises(dev_flow.FlowError) as replay:
                dev_flow._persist_state_transaction(
                    current,
                    copy.deepcopy(candidate),
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                    _engine_commit_proof=proof,
                )
            self.assertEqual(
                replay.exception.code,
                "V3_ENGINE_COMMIT_PROOF_REPLAYED",
            )
        self.assertEqual(
            failures,
            ["V3_ENGINE_COMMIT_LOCK_CAPABILITY_INVALID"],
        )
        unchanged = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(unchanged["revision"], current["revision"])


    def test_copied_lock_context_cannot_issue_evaluation(
        self,
    ) -> None:
        started = self._start_v3("proof-evaluation-cross-thread")
        task_dir, task_lock, workspace_lock = self._locks(
            started["task_id"]
        )
        failures: list[str] = []
        with task_lock, workspace_lock:
            current = dev_flow.load_state(
                started["task_id"], self.data
            )
            copied_context = contextvars.copy_context()

            def evaluate_elsewhere() -> None:
                try:
                    self._blocked_evaluation(current)
                except dev_flow.TransitionEngineError as exc:
                    failures.append(exc.code)

            worker = threading.Thread(
                target=lambda: copied_context.run(evaluate_elsewhere)
            )
            worker.start()
            worker.join()
            # A fresh evaluation on the actual lock-owning thread remains
            # usable; the copied context never received an issuance.
            evaluation, candidate, payload, linked = (
                self._blocked_evaluation(current)
            )
            proof = (
                dev_flow._workflow_transition_mint_engine_commit_proof(
                    current,
                    evaluation,
                    task_dir,
                    "state_transitioned",
                    payload,
                    additional_events=linked,
                )
            )
            dev_flow._persist_state_transaction(
                current,
                candidate,
                task_dir,
                "state_transitioned",
                payload,
                additional_events=linked,
                _engine_commit_proof=proof,
            )
        self.assertEqual(
            failures,
            ["V3_ENGINE_COMMIT_LOCK_CAPABILITY_INVALID"],
        )
        persisted = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(persisted["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
