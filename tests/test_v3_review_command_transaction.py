from __future__ import annotations

import copy
import json
import socket
import time
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


class _InjectedReviewFailure(RuntimeError):
    pass


class V3ReviewCommandTransactionTests(DevFlowTestCase):
    def _state_path(self, task_id: str) -> Path:
        return self.data / "tasks" / task_id / "state.json"

    def _task_dir(self, task_id: str) -> Path:
        return self._state_path(task_id).parent

    @staticmethod
    def _events(task_dir: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in (task_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    @staticmethod
    def _archives(task_dir: Path) -> list[Path]:
        return sorted(
            (task_dir / "action-executions" / "archive").glob(
                "*.json"
            )
        )

    @staticmethod
    def _active_journals(task_dir: Path) -> list[Path]:
        return sorted(
            (task_dir / "action-executions" / "active").glob(
                "*.json"
            )
        )

    def _persist_state(self, state: dict) -> None:
        dev_flow._atomic_write_json(
            self._state_path(state["task_id"]), state
        )

    def _prepared_v3_state(
        self,
        *,
        task_id: str,
        status: str,
    ) -> dict:
        repository, _remote = self.make_repo(
            f"{task_id}-repository"
        )
        state = self.ready_workspace_task(
            repository, task_id=task_id
        )
        state = self.record_workspace_indexes(state)
        self.mutate("transition", state, "PLANNING")
        state = dev_flow.load_state(task_id, self.data)
        contract = self.root / f"{task_id}-contract.md"
        contract.write_text(
            "# Contract\n\nReview transaction fixture.\n",
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
            "review transaction fixture approved",
            "--artifact-sha256",
            recorded["artifact"]["sha256"],
        )
        state = dev_flow.load_state(task_id, self.data)
        self.mutate("transition", state, "IMPLEMENTING")
        state = dev_flow.load_state(task_id, self.data)
        state["status"] = status
        state["schema_version"] = dev_flow.V3_TASK_SCHEMA_VERSION
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state.update(
            copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            )
        )
        for node in state["node_instances"]:
            node["state"] = (
                "READY" if node["node_id"] == status else "PENDING"
            )
        self._persist_state(state)
        return dev_flow.load_state(task_id, self.data)

    def _authorize(
        self,
        state: dict,
        *,
        secret_byte: bytes,
    ) -> tuple[object, bytearray]:
        secret = bytearray(secret_byte * 32)
        verifier = dev_flow.issue_manager_capability(
            task_id=state["task_id"],
            issued_for_task_revision=state["revision"],
            manager_session_id="review-command-manager",
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
            manager_secret=secret,
        )
        state = copy.deepcopy(state)
        state["orchestration"] = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {
                verifier.capability_id: (
                    verifier.as_persistent_dict()
                )
            },
        }
        self._persist_state(state)
        self.addCleanup(dev_flow._manager_zeroize, secret)
        return verifier, secret

    @staticmethod
    def _request(
        state: dict,
        verifier: object,
        *,
        action_id: str,
        nonce: str,
    ) -> dict:
        return {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": verifier.capability_id,
            "task_id": state["task_id"],
            "manager_session_id": "review-command-manager",
            "action_id": action_id,
            "expected_revision": state["revision"],
            "request_nonce": nonce,
        }

    def _with_secret(
        self,
        *arguments: str,
        request: dict,
        secret: bytearray,
        expected_code: int = 0,
    ) -> dict:
        publisher, consumer = socket.socketpair()
        try:
            dev_flow.publish_manager_secret(
                dev_flow.ManagerSecretChannelConfig(
                    publisher.fileno()
                ),
                secret,
            )
            return self.cli(
                *arguments,
                "--manager-request-json",
                json.dumps(
                    request,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "--manager-secret-fd",
                str(consumer.fileno()),
                expected_code=expected_code,
            )
        finally:
            publisher.close()
            consumer.close()

    def _apply(
        self,
        state: dict,
        verifier: object,
        secret: bytearray,
        *,
        action: str,
        nonce: str,
        expected_code: int = 0,
    ) -> dict:
        if action == "record-test":
            arguments = (
                "record-test",
                state["task_id"],
                "--expected-revision",
                str(state["revision"]),
                "--name",
                "unit",
                "--command",
                "python3 -m unittest",
                "--exit-code",
                "0",
            )
            action_id = "evidence.test.record"
        else:
            self.assertEqual(action, "review-snapshot")
            arguments = (
                "review-snapshot",
                state["task_id"],
                "--expected-revision",
                str(state["revision"]),
            )
            action_id = "evidence.review-snapshot.record"
        return self._with_secret(
            *arguments,
            request=self._request(
                state,
                verifier,
                action_id=action_id,
                nonce=nonce,
            ),
            secret=secret,
            expected_code=expected_code,
        )

    def _snapshot_ready_state(self, task_id: str) -> dict:
        state = self._prepared_v3_state(
            task_id=task_id, status="VERIFYING"
        )
        verifier, secret = self._authorize(
            state, secret_byte=b"T"
        )
        recorded = self._apply(
            state,
            verifier,
            secret,
            action="record-test",
            nonce="0" * 64,
        )
        self.assertEqual(recorded["status"], "VERIFYING")
        return dev_flow.load_state(task_id, self.data)

    @staticmethod
    def _used_nonces(
        state: dict, capability_id: str
    ) -> list[str]:
        return list(
            state["orchestration"]["manager_capabilities"][
                capability_id
            ]["used_request_nonce_sha256s"]
        )

    def _assert_nonce(
        self,
        state: dict,
        verifier: object,
        *,
        action_id: str,
        nonce: str,
        consumed: bool,
    ) -> None:
        request = dev_flow.validate_manager_capability_request(
            self._request(
                state,
                verifier,
                action_id=action_id,
                nonce=nonce,
            )
        )
        expected = (
            [dev_flow.manager_request_nonce_digest(request)]
            if consumed
            else []
        )
        persisted = dev_flow.load_state(
            state["task_id"], self.data
        )
        self.assertEqual(
            self._used_nonces(
                persisted, verifier.capability_id
            ),
            expected,
        )

    def _assert_clean_effect_boundary(self) -> None:
        forbidden = [
            capability
            for capability in (
                dev_flow._workflow_tx_live_lock_capabilities()
            )
            if capability.get("lock_name")
            in {"state.lock", "workspace-registry.lock"}
        ]
        self.assertEqual(forbidden, [])

    def _assert_atomic_commit(
        self,
        *,
        before: dict,
        applied: dict,
        verifier: object,
        action_id: str,
        nonce: str,
        expected_status: str,
        archive: Path,
    ) -> None:
        self.assertEqual(applied["status"], expected_status)
        self.assertEqual(
            applied["revision"], before["revision"] + 1
        )
        journal = json.loads(archive.read_text(encoding="utf-8"))
        self.assertEqual(journal["phase"], "COMMITTED")
        self.assertTrue(journal["finalization"]["nonce_consumed"])
        self._assert_nonce(
            before,
            verifier,
            action_id=action_id,
            nonce=nonce,
            consumed=True,
        )
        revision_events = [
            event
            for event in self._events(
                self._task_dir(before["task_id"])
            )
            if event["revision"] == applied["revision"]
        ]
        manager_events = [
            event
            for event in revision_events
            if event["type"]
            == dev_flow.MANAGER_CAPABILITY_AUTHORIZED_EVENT
        ]
        self.assertEqual(len(manager_events), 1)
        self.assertEqual(
            len(
                {
                    event["transaction_id"]
                    for event in revision_events
                }
            ),
            1,
        )

    def test_normal_record_and_snapshot_commit_with_clean_lock_boundaries(
        self,
    ) -> None:
        state = self._prepared_v3_state(
            task_id="review-command-normal",
            status="VERIFYING",
        )
        task_dir = self._task_dir(state["task_id"])
        original_execute = (
            dev_flow.execute_v3_workflow_action_transaction
        )
        original_dispatch = dev_flow.dispatch_v3_review_effect
        entries: list[str] = []
        dispatches: list[str] = []

        def execute(*args: object, **kwargs: object) -> object:
            self._assert_clean_effect_boundary()
            entries.append("clean")
            return original_execute(*args, **kwargs)

        def dispatch(*args: object, **kwargs: object) -> object:
            self._assert_clean_effect_boundary()
            dispatches.append(args[0].action)
            return original_dispatch(*args, **kwargs)

        verifier, secret = self._authorize(
            state, secret_byte=b"N"
        )
        before_archives = {
            path.name for path in self._archives(task_dir)
        }
        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute,
            ),
            mock.patch.object(
                dev_flow,
                "dispatch_v3_review_effect",
                side_effect=dispatch,
            ),
        ):
            recorded = self._apply(
                state,
                verifier,
                secret,
                action="record-test",
                nonce="1" * 64,
            )
        archives = self._archives(task_dir)
        new_archives = [
            path
            for path in archives
            if path.name not in before_archives
        ]
        self.assertEqual(len(new_archives), 1)
        self._assert_atomic_commit(
            before=state,
            applied=recorded,
            verifier=verifier,
            action_id="evidence.test.record",
            nonce="1" * 64,
            expected_status="VERIFYING",
            archive=new_archives[0],
        )

        state = dev_flow.load_state(state["task_id"], self.data)
        verifier, secret = self._authorize(
            state, secret_byte=b"S"
        )
        before_archives = {path.name for path in archives}
        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute,
            ),
            mock.patch.object(
                dev_flow,
                "dispatch_v3_review_effect",
                side_effect=dispatch,
            ),
        ):
            reviewed = self._apply(
                state,
                verifier,
                secret,
                action="review-snapshot",
                nonce="2" * 64,
            )
        archives = self._archives(task_dir)
        new_archives = [
            path
            for path in archives
            if path.name not in before_archives
        ]
        self.assertEqual(len(new_archives), 1)
        self._assert_atomic_commit(
            before=state,
            applied=reviewed,
            verifier=verifier,
            action_id="evidence.review-snapshot.record",
            nonce="2" * 64,
            expected_status="REVIEWING",
            archive=new_archives[0],
        )
        self.assertEqual(entries, ["clean", "clean"])
        self.assertEqual(
            dispatches, ["record-test", "review-snapshot"]
        )

    def test_manager_effect_authorization_is_cleared_exactly_once(
        self,
    ) -> None:
        state = self._prepared_v3_state(
            task_id="review-command-manager-clear",
            status="VERIFYING",
        )
        verifier, secret = self._authorize(
            state, secret_byte=b"C"
        )
        clear_calls: list[object] = []
        original_clear = (
            dev_flow._ManagerAuthorityInvocation
            .clear_effect_authorization
        )

        def tracked_clear(invocation: object) -> None:
            clear_calls.append(invocation)
            original_clear(invocation)

        with mock.patch.object(
            dev_flow._ManagerAuthorityInvocation,
            "clear_effect_authorization",
            new=tracked_clear,
        ):
            self._apply(
                state,
                verifier,
                secret,
                action="record-test",
                nonce="c" * 64,
            )
        self.assertEqual(len(clear_calls), 1)

    def _exercise_restart(
        self,
        *,
        action: str,
        stage: str,
        task_id: str,
        nonce: str,
    ) -> None:
        state = (
            self._prepared_v3_state(
                task_id=task_id, status="VERIFYING"
            )
            if action == "record-test"
            else self._snapshot_ready_state(task_id)
        )
        verifier, secret = self._authorize(
            state,
            secret_byte=(
                b"L" if stage == "after-dispatch" else b"R"
            ),
        )
        original_execute = (
            dev_flow.execute_v3_workflow_action_transaction
        )
        original_dispatch = dev_flow.dispatch_v3_review_effect
        original_observe = dev_flow.observe_v3_review_effect
        dispatches = 0
        observations = 0

        def fail(observed_stage: str) -> None:
            if observed_stage == stage:
                raise _InjectedReviewFailure(observed_stage)

        def execute(*args: object, **kwargs: object) -> object:
            self._assert_clean_effect_boundary()
            kwargs["failure_hook"] = fail
            return original_execute(*args, **kwargs)

        def dispatch(*args: object, **kwargs: object) -> object:
            nonlocal dispatches
            self._assert_clean_effect_boundary()
            dispatches += 1
            return original_dispatch(*args, **kwargs)

        def observe(*args: object, **kwargs: object) -> object:
            nonlocal observations
            observations += 1
            return original_observe(*args, **kwargs)

        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute,
            ),
            mock.patch.object(
                dev_flow,
                "dispatch_v3_review_effect",
                side_effect=dispatch,
            ),
            mock.patch.object(
                dev_flow,
                "observe_v3_review_effect",
                side_effect=observe,
            ),
        ):
            failed = self._apply(
                state,
                verifier,
                secret,
                action=action,
                nonce=nonce,
                expected_code=1,
            )
        self.assertEqual(failed["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(
            failed["error"]["details"]["type"],
            "_InjectedReviewFailure",
        )
        task_dir = self._task_dir(state["task_id"])
        active = self._active_journals(task_dir)
        self.assertEqual(len(active), 1)
        active_name = active[0].name
        pending = json.loads(active[0].read_text(encoding="utf-8"))
        expected_phase = (
            "RECEIPT_VERIFIED"
            if stage == "after-receipt-verified"
            else "QUARANTINED"
        )
        self.assertEqual(pending["phase"], expected_phase)
        action_id = (
            "evidence.test.record"
            if action == "record-test"
            else "evidence.review-snapshot.record"
        )
        self._assert_nonce(
            state,
            verifier,
            action_id=action_id,
            nonce=nonce,
            consumed=False,
        )

        with (
            mock.patch.object(
                dev_flow,
                "dispatch_v3_review_effect",
                side_effect=dispatch,
            ),
            mock.patch.object(
                dev_flow,
                "observe_v3_review_effect",
                side_effect=observe,
            ),
        ):
            recovered = self._apply(
                state,
                verifier,
                secret,
                action=action,
                nonce=nonce,
                expected_code=(
                    2 if stage == "after-dispatch" else 0
                ),
            )
        self.assertEqual(dispatches, 1)
        self.assertGreaterEqual(observations, 1)
        if stage == "after-dispatch":
            self.assertEqual(
                recovered["error"]["code"],
                "WORKFLOW_ACTION_TRANSACTION_RECOVERY_REQUIRED",
            )
            self.assertEqual(
                recovered["error"]["details"]["status"],
                "QUARANTINE_REQUIRED",
            )
            self.assertTrue(active[0].exists())
            self._assert_nonce(
                state,
                verifier,
                action_id=action_id,
                nonce=nonce,
                consumed=False,
            )
            return
        self.assertFalse(active[0].exists())
        archives = self._archives(task_dir)
        self.assertIn(active_name, [path.name for path in archives])
        self._assert_atomic_commit(
            before=state,
            applied=recovered,
            verifier=verifier,
            action_id=action_id,
            nonce=nonce,
            expected_status=(
                "VERIFYING"
                if action == "record-test"
                else "REVIEWING"
            ),
            archive=next(
                path for path in archives if path.name == active_name
            ),
        )

    def test_lost_record_dispatch_response_observes_without_redispatch(
        self,
    ) -> None:
        self._exercise_restart(
            action="record-test",
            stage="after-dispatch",
            task_id="record-command-lost-response",
            nonce="3" * 64,
        )

    def test_lost_snapshot_dispatch_response_observes_without_redispatch(
        self,
    ) -> None:
        self._exercise_restart(
            action="review-snapshot",
            stage="after-dispatch",
            task_id="snapshot-command-lost-response",
            nonce="4" * 64,
        )

    def test_record_complete_receipt_restart_commits_same_journal(
        self,
    ) -> None:
        self._exercise_restart(
            action="record-test",
            stage="after-receipt-verified",
            task_id="record-command-receipt-restart",
            nonce="5" * 64,
        )

    def test_snapshot_complete_receipt_restart_commits_same_journal(
        self,
    ) -> None:
        self._exercise_restart(
            action="review-snapshot",
            stage="after-receipt-verified",
            task_id="snapshot-command-receipt-restart",
            nonce="6" * 64,
        )

    def test_wrong_node_and_authoritative_drift_are_zero_effect(
        self,
    ) -> None:
        wrong = self._prepared_v3_state(
            task_id="snapshot-command-wrong-node",
            status="IMPLEMENTING",
        )
        verifier, secret = self._authorize(
            wrong, secret_byte=b"W"
        )
        task_dir = self._task_dir(wrong["task_id"])
        before_state = self._state_path(wrong["task_id"]).read_bytes()
        before_events = (task_dir / "events.jsonl").read_bytes()
        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
            ) as execute,
            mock.patch.object(
                dev_flow, "dispatch_v3_review_effect"
            ) as dispatch,
        ):
            rejected = self._apply(
                wrong,
                verifier,
                secret,
                action="review-snapshot",
                nonce="7" * 64,
                expected_code=2,
            )
        self.assertEqual(rejected["error"]["code"], "INVALID_STATE")
        execute.assert_not_called()
        dispatch.assert_not_called()
        self.assertEqual(
            self._state_path(wrong["task_id"]).read_bytes(),
            before_state,
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), before_events
        )
        self.assertFalse((task_dir / "action-executions").exists())

        drifted = self._prepared_v3_state(
            task_id="record-command-authoritative-drift",
            status="VERIFYING",
        )
        verifier, secret = self._authorize(
            drifted, secret_byte=b"D"
        )
        task_dir = self._task_dir(drifted["task_id"])
        before_events = (task_dir / "events.jsonl").read_bytes()
        original_execute = (
            dev_flow.execute_v3_workflow_action_transaction
        )
        injected_state: bytes | None = None

        def execute_with_drift(
            *args: object, **kwargs: object
        ) -> object:
            nonlocal injected_state
            self._assert_clean_effect_boundary()
            changed = dev_flow.load_state(
                drifted["task_id"], self.data
            )
            changed["revision"] = int(changed["revision"]) + 1
            changed["updated_at"] = dev_flow.utc_now()
            self._persist_state(changed)
            injected_state = self._state_path(
                drifted["task_id"]
            ).read_bytes()
            return original_execute(*args, **kwargs)

        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute_with_drift,
            ),
            mock.patch.object(
                dev_flow, "dispatch_v3_review_effect"
            ) as dispatch,
        ):
            rejected = self._apply(
                drifted,
                verifier,
                secret,
                action="record-test",
                nonce="8" * 64,
                expected_code=2,
            )
        self.assertEqual(
            rejected["error"]["code"],
            "WORKFLOW_ACTION_TRANSACTION_STALE_STATE",
        )
        dispatch.assert_not_called()
        self.assertIsNotNone(injected_state)
        self.assertEqual(
            self._state_path(drifted["task_id"]).read_bytes(),
            injected_state,
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), before_events
        )
        self.assertFalse((task_dir / "action-executions").exists())
