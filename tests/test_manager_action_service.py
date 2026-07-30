from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import socket
import struct
import time
from types import MappingProxyType
from unittest import mock

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class ManagerActionServiceTests(DevFlowTestCase):
    def _active_lite_services(self) -> object:
        services = dev_flow.workflow_runtime_services()
        activations = []
        for frozen in services.catalog.activations:
            activation = dict(frozen)
            if (
                activation["workflow_id"] == "lite"
                and activation["workflow_version"] == 3
                and activation["execution_profile"]
                == "single-repository"
            ):
                activation["active"] = True
                activation["required_suites"] = sorted(
                    set(
                        dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            "single-repository"
                        ]
                    )
                    | {"action-policy", "action-recovery"}
                )
            activations.append(MappingProxyType(activation))
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=tuple(activations),
            ),
        )

    def _start_authorized_task(
        self,
        *,
        allowed_actions: list[str] | None = None,
    ) -> tuple[dict, bytearray, object]:
        repository, _ = self.make_repo("manager-action-repository")
        services = self._active_lite_services()
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            started = self.cli(
                "start",
                "exercise replay-safe manager actions",
                "--repo",
                str(repository),
                "--task-id",
                "manager-action",
                "--workspace-strategy",
                "in-place",
                "--change-category",
                "docs",
                "--target-path",
                "tracked.txt",
            )
        secret = bytearray(b"M" * 32)
        wall_time_ns = time.time_ns()
        monotonic_time_ns = (
            dev_flow._manager_system_monotonic_ns()
        )
        verifier = dev_flow.issue_manager_capability(
            task_id=started["task_id"],
            issued_for_task_revision=started["revision"],
            manager_session_id="manager-session-1",
            allowed_actions=allowed_actions or ["transition"],
            ttl_ns=60_000_000_000,
            wall_time_ns=wall_time_ns,
            monotonic_time_ns=monotonic_time_ns,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="mcp-secret-channel",
            operator_confirmation_sha256="1" * 64,
            issuance_audit_sha256="2" * 64,
            manager_secret=secret,
        )
        state_path = (
            self.data / "tasks" / started["task_id"] / "state.json"
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["orchestration"] = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {
                verifier.capability_id: (
                    verifier.as_persistent_dict()
                )
            },
        }
        state_path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return started, secret, verifier

    @staticmethod
    def _request(
        started: dict,
        verifier: object,
        *,
        nonce: str = "5" * 64,
        action_id: str = "transition",
    ) -> dict:
        return {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": verifier.capability_id,
            "task_id": started["task_id"],
            "manager_session_id": "manager-session-1",
            "action_id": action_id,
            "expected_revision": started["revision"],
            "request_nonce": nonce,
        }

    @staticmethod
    def _principal(*, role: str = "manager") -> dict:
        return {
            "schema": "dev-flow-agent-principal/v1",
            "role": role,
            "session_id": "manager-session-1",
            "os_user_identity_sha256": "3" * 64,
            "host_identity_sha256": "4" * 64,
        }

    def test_common_locked_boundary_precedes_all_protected_effect_classes(
        self,
    ) -> None:
        started, _secret, _verifier = self._start_authorized_task()
        artifact = self.root / "candidate-artifact.txt"
        artifact.write_text("candidate\n", encoding="utf-8")
        common = {
            "task_id": None,
            "task_option": started["task_id"],
            "data_dir": self.data,
            "expected_revision": started["revision"],
        }
        invocations = (
            (
                dev_flow.command_baseline,
                argparse.Namespace(**common),
            ),
            (
                dev_flow.command_prepare_workspace,
                argparse.Namespace(**common),
            ),
            (
                dev_flow.command_review_snapshot,
                argparse.Namespace(**common),
            ),
            (
                dev_flow.command_record_artifact,
                argparse.Namespace(
                    **common,
                    path=str(artifact),
                    metadata_json=None,
                ),
            ),
        )
        protected_names = (
            "_git",
            "_atomic_write_json",
            "_atomic_write_bytes",
            "_claim_workspace_plan",
            "_execute_worktree",
            "_write_review_repo",
            "_hash_artifact",
        )
        patches = {
            name: mock.patch.object(dev_flow, name)
            for name in protected_names
        }
        mocks = {
            name: patcher.start()
            for name, patcher in patches.items()
        }
        self.addCleanup(
            lambda: [patcher.stop() for patcher in patches.values()]
        )

        for handler, namespace in invocations:
            with self.subTest(handler=handler.__name__):
                with self.assertRaises(dev_flow.FlowError) as raised:
                    handler(namespace)
                self.assertEqual(
                    raised.exception.code,
                    "MANAGER_CAPABILITY_REQUIRED",
                )

        for name, effect in mocks.items():
            with self.subTest(effect=name):
                effect.assert_not_called()

    def test_direct_handler_cannot_borrow_another_action_context(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task()
        artifact = self.root / "cross-action-artifact.txt"
        artifact.write_text("candidate\n", encoding="utf-8")
        request = self._request(
            started, verifier, nonce="9" * 64
        )
        state_path = (
            self.data / "tasks" / started["task_id"] / "state.json"
        )
        event_path = state_path.with_name("events.jsonl")
        before_state = state_path.read_bytes()
        before_events = (
            event_path.read_bytes() if event_path.exists() else None
        )
        proof = bytearray(secret)
        reads = 0

        def resolve() -> bytearray:
            nonlocal reads
            reads += 1
            return proof

        namespace = argparse.Namespace(
            task_id=None,
            task_option=started["task_id"],
            data_dir=self.data,
            expected_revision=started["revision"],
            path=str(artifact),
            metadata_json=None,
        )
        with (
            mock.patch.object(dev_flow, "_hash_artifact") as artifact_hash,
            mock.patch.object(
                dev_flow, "_atomic_write_json"
            ) as state_write,
            self.assertRaises(dev_flow.FlowError) as raised,
        ):
            with dev_flow._manager_authority_context(
                request=request,
                action_id="transition",
                secret_resolver=resolve,
                principal=self._principal(),
                operation_fingerprint_sha256="a" * 64,
            ):
                dev_flow.command_record_artifact(namespace)

        self.assertEqual(
            raised.exception.code,
            "MANAGER_HANDLER_ACTION_MISMATCH",
        )
        self.assertEqual(reads, 0)
        self.assertEqual(proof, bytearray(secret))
        artifact_hash.assert_not_called()
        state_write.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(
            event_path.read_bytes() if event_path.exists() else None,
            before_events,
        )

    def test_quarantine_recovery_requires_exact_action_before_any_retry_effect(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task(
            allowed_actions=[
                "recovery.quarantine",
                "transition",
            ]
        )
        state_path = (
            self.data / "tasks" / started["task_id"] / "state.json"
        )
        event_path = state_path.with_name("events.jsonl")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        recovery_id = "recovery-already-committed"
        state["mutation_recoveries"] = [
            {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "recovery_id": recovery_id,
                "recovered_at": dev_flow.utc_now(),
                "quarantined_pid": None,
                "quarantined_command": ["git", "status"],
                "state_revision": state["revision"],
                "validation": {},
            }
        ]
        state_path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        quarantine_path = state_path.with_name(
            "mutation-quarantine.json"
        )
        quarantine = {
            "schema_version": 1,
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "ready": False,
            "recovery_id": recovery_id,
            "recovery_validated_revision": state["revision"],
            "state_revision": state["revision"],
            "phase": "spawn_pending",
            "pid": None,
            "process_group": None,
            "gate_protocol_version": 1,
            "target_release_authorized": False,
            "containment_established": False,
            "command": ["git", "status"],
        }
        quarantine_path.write_text(
            json.dumps(quarantine, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before_state = state_path.read_bytes()
        before_quarantine = quarantine_path.read_bytes()
        before_events = (
            event_path.read_bytes() if event_path.exists() else None
        )
        namespace = argparse.Namespace(
            task_id=None,
            task_option=started["task_id"],
            data_dir=self.data,
            expected_revision=started["revision"],
        )
        recovery_request = self._request(
            started,
            verifier,
            nonce="b" * 64,
            action_id="recovery.quarantine",
        )
        transition_request = self._request(
            started,
            verifier,
            nonce="c" * 64,
            action_id="transition",
        )
        invalid_proof = bytearray(b"X" * 32)
        cross_action_proof = bytearray(secret)
        cross_reads = 0

        def cross_resolve() -> bytearray:
            nonlocal cross_reads
            cross_reads += 1
            return cross_action_proof

        attempts = (
            (
                "missing",
                contextlib.nullcontext(),
                "MANAGER_CAPABILITY_REQUIRED",
            ),
            (
                "invalid",
                dev_flow._manager_authority_context(
                    request=recovery_request,
                    action_id="recovery.quarantine",
                    secret_resolver=lambda: invalid_proof,
                    principal=self._principal(),
                    operation_fingerprint_sha256="d" * 64,
                ),
                "MANAGER_CAPABILITY_PROOF_INVALID",
            ),
            (
                "cross-action",
                dev_flow._manager_authority_context(
                    request=transition_request,
                    action_id="transition",
                    secret_resolver=cross_resolve,
                    principal=self._principal(),
                    operation_fingerprint_sha256="e" * 64,
                ),
                "MANAGER_HANDLER_ACTION_MISMATCH",
            ),
        )
        for label, authority, expected_code in attempts:
            with self.subTest(label=label):
                with (
                    mock.patch.object(
                        dev_flow, "_atomic_write_json"
                    ) as write,
                    mock.patch.object(
                        dev_flow, "_archive_quarantine"
                    ) as archive,
                    mock.patch.object(
                        dev_flow, "_commit_state"
                    ) as commit,
                    self.assertRaises(dev_flow.FlowError) as raised,
                    authority,
                ):
                    dev_flow.command_recover_quarantine(namespace)
                self.assertEqual(
                    raised.exception.code, expected_code
                )
                write.assert_not_called()
                archive.assert_not_called()
                commit.assert_not_called()
                self.assertEqual(
                    state_path.read_bytes(), before_state
                )
                self.assertEqual(
                    quarantine_path.read_bytes(),
                    before_quarantine,
                )
                self.assertEqual(
                    (
                        event_path.read_bytes()
                        if event_path.exists()
                        else None
                    ),
                    before_events,
                )

        self.assertEqual(
            invalid_proof, bytearray(b"\x00" * 32)
        )
        self.assertEqual(cross_reads, 0)
        self.assertEqual(cross_action_proof, bytearray(secret))

    def test_invalid_and_worker_proofs_fail_before_effect_and_zero_secret(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task()
        request = self._request(started, verifier)
        for role, proof, expected_code in (
            (
                "manager",
                bytearray(b"X" * 32),
                "MANAGER_CAPABILITY_PROOF_INVALID",
            ),
            (
                "worker",
                bytearray(secret),
                "ORCHESTRATION_WORKER_MUTATION_DENIED",
            ),
        ):
            with self.subTest(role=role):
                effects: list[str] = []
                with self.assertRaises(dev_flow.FlowError) as raised:
                    with dev_flow._manager_authority_context(
                        request=request,
                        action_id="transition",
                        secret_resolver=lambda proof=proof: proof,
                        principal=self._principal(role=role),
                        operation_fingerprint_sha256="6" * 64,
                    ):
                        with dev_flow._locked_state(
                            started["task_id"],
                            self.data,
                            started["revision"],
                            manager_action_id="task.transition",
                        ):
                            effects.append("protected")
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(effects, [])
                self.assertEqual(proof, bytearray(b"\x00" * 32))

    def test_effect_failure_does_not_consume_nonce_and_zeroizes_exact_buffer(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task()
        request = self._request(
            started, verifier, nonce="7" * 64
        )
        state_path = (
            self.data / "tasks" / started["task_id"] / "state.json"
        )
        event_path = state_path.with_name("events.jsonl")
        before_state = state_path.read_bytes()
        before_events = (
            event_path.read_bytes() if event_path.exists() else None
        )
        proof = bytearray(secret)
        reads = 0

        def resolve() -> bytearray:
            nonlocal reads
            reads += 1
            return proof

        with self.assertRaisesRegex(RuntimeError, "effect failed"):
            with dev_flow._manager_authority_context(
                request=request,
                action_id="transition",
                secret_resolver=resolve,
                principal=self._principal(),
                operation_fingerprint_sha256="8" * 64,
            ):
                with dev_flow._locked_state(
                    started["task_id"],
                    self.data,
                    started["revision"],
                    manager_action_id="task.transition",
                ):
                    raise RuntimeError("effect failed")

        self.assertEqual(reads, 1)
        self.assertEqual(proof, bytearray(b"\x00" * 32))
        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(
            event_path.read_bytes() if event_path.exists() else None,
            before_events,
        )

    def test_secret_descriptor_reads_exactly_one_bounded_frame(
        self,
    ) -> None:
        read_fd, write_fd = os.pipe()
        first = b"A" * 32
        second = b"B" * 32
        frame = (
            struct.pack(">I", len(first))
            + first
            + struct.pack(">I", len(second))
            + second
        )
        try:
            os.write(write_fd, frame)
            os.close(write_fd)
            write_fd = -1
            resolved = dev_flow.resolve_manager_secret(
                dev_flow.ManagerSecretChannelConfig(read_fd)
            )
            self.assertIsInstance(resolved, bytearray)
            self.assertEqual(resolved, bytearray(first))
            self.assertEqual(
                os.read(read_fd, len(frame)),
                struct.pack(">I", len(second)) + second,
            )
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)
            if "resolved" in locals():
                dev_flow._manager_zeroize(resolved)

    def test_posix_secret_channel_accepts_only_connected_unix_sockets(
        self,
    ) -> None:
        if os.name == "nt":
            self.skipTest("POSIX socket-family contract")
        left, right = socket.socketpair()
        try:
            duplicate = dev_flow._manager_channel_descriptor(
                dev_flow.ManagerSecretChannelConfig(left.fileno())
            )
            os.fstat(duplicate)
            os.close(duplicate)
        finally:
            left.close()
            right.close()

        network_socket = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        try:
            real_dup = os.dup
            leaked_duplicate = real_dup(network_socket.fileno())
            with mock.patch.object(
                dev_flow.os,
                "dup",
                return_value=leaked_duplicate,
            ):
                with self.assertRaises(dev_flow.FlowError) as raised:
                    dev_flow._manager_channel_descriptor(
                        dev_flow.ManagerSecretChannelConfig(
                            network_socket.fileno()
                        )
                    )
            self.assertEqual(
                raised.exception.code,
                "MANAGER_SECRET_CHANNEL_FORBIDDEN",
            )
            with self.assertRaises(OSError):
                os.fstat(leaked_duplicate)
        finally:
            network_socket.close()

        if socket.has_ipv6:
            network_socket6 = socket.socket(
                socket.AF_INET6, socket.SOCK_STREAM
            )
            try:
                with self.assertRaises(dev_flow.FlowError) as raised6:
                    dev_flow._manager_channel_descriptor(
                        dev_flow.ManagerSecretChannelConfig(
                            network_socket6.fileno()
                        )
                    )
                self.assertEqual(
                    raised6.exception.code,
                    "MANAGER_SECRET_CHANNEL_FORBIDDEN",
                )
            finally:
                network_socket6.close()

    def test_lost_apply_response_recovers_exact_receipt_without_second_write(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task()
        issued_buffers: list[bytearray] = []
        principal = {
            "schema": "dev-flow-agent-principal/v1",
            "role": "manager",
            "session_id": "manager-session-1",
            "os_user_identity_sha256": "3" * 64,
            "host_identity_sha256": "4" * 64,
        }

        class Channel:
            def principal_for(self, _request_identity):
                return principal

            def resolve_secret(self, capability_id):
                if capability_id != verifier.capability_id:
                    raise AssertionError("unexpected capability")
                owned = bytearray(secret)
                issued_buffers.append(owned)
                return owned

        channel = Channel()
        input_value = {
            "contract": "dev-flow-action-transition-input/v1",
            "to": "BLOCKED",
            "note": "waiting for operator evidence",
        }
        preview = dev_flow.controller_action_preview(
            started["task_id"],
            expected_revision=started["revision"],
            action_id="transition",
            input_value=input_value,
            data_dir=self.data,
        )
        request = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": verifier.capability_id,
            "task_id": started["task_id"],
            "manager_session_id": "manager-session-1",
            "action_id": "transition",
            "expected_revision": started["revision"],
            "request_nonce": "5" * 64,
        }
        original_receipt = (
            dev_flow._controller_action_committed_receipt
        )
        committed_receipts: list[dict] = []

        def lose_response(*args, **kwargs):
            receipt = original_receipt(*args, **kwargs)
            committed_receipts.append(receipt)
            raise RuntimeError("simulated response loss")

        with (
            mock.patch.object(
                dev_flow,
                "_controller_action_committed_receipt",
                lose_response,
            ),
            self.assertRaisesRegex(
                RuntimeError, "simulated response loss"
            ),
        ):
            dev_flow.controller_action_apply(
                started["task_id"],
                expected_revision=started["revision"],
                action_id="transition",
                input_value=input_value,
                preview_intent=preview["preview_intent"],
                request=request,
                principal=principal,
                manager_channel=channel,
                data_dir=self.data,
            )

        self.assertEqual(len(issued_buffers), 1)
        state_after_commit = dev_flow.load_state(
            started["task_id"], self.data
        )
        event_path = (
            self.data / "tasks" / started["task_id"] / "events.jsonl"
        )
        events_after_commit = event_path.read_bytes()
        committed_events = [
            json.loads(line)
            for line in events_after_commit.splitlines()
            if line
        ]
        revision_events = [
            event
            for event in committed_events
            if event.get("revision") == started["revision"] + 1
        ]
        primary_events = [
            event
            for event in revision_events
            if event.get("type") == "state_transitioned"
        ]
        manager_events = [
            event
            for event in revision_events
            if event.get("type")
            == dev_flow.MANAGER_CAPABILITY_AUTHORIZED_EVENT
        ]
        self.assertEqual(len(primary_events), 1)
        self.assertEqual(len(manager_events), 1)
        self.assertEqual(
            primary_events[0].get("transaction_id"),
            manager_events[0].get("transaction_id"),
        )
        self.assertEqual(
            len(
                {
                    event.get("transaction_id")
                    for event in revision_events
                }
            ),
            1,
        )
        persisted_verifier = state_after_commit["orchestration"][
            "manager_capabilities"
        ][verifier.capability_id]
        self.assertEqual(
            persisted_verifier["used_request_nonce_sha256s"],
            [dev_flow.manager_request_nonce_digest(request)],
        )
        recovered = dev_flow.controller_action_apply(
            started["task_id"],
            expected_revision=started["revision"],
            action_id="transition",
            input_value=input_value,
            preview_intent=preview["preview_intent"],
            request=request,
            principal=principal,
            manager_channel=channel,
            data_dir=self.data,
        )

        self.assertEqual(recovered, committed_receipts[0])
        self.assertEqual(
            dev_flow.load_state(
                started["task_id"], self.data
            )["revision"],
            state_after_commit["revision"],
        )
        self.assertEqual(event_path.read_bytes(), events_after_commit)
        self.assertEqual(
            issued_buffers,
            [
                bytearray(b"\x00" * 32),
                bytearray(b"\x00" * 32),
            ],
        )

        before_conflict = event_path.read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow.controller_action_apply(
                started["task_id"],
                expected_revision=started["revision"],
                action_id="transition",
                input_value={
                    **input_value,
                    "note": "different canonical input",
                },
                preview_intent=preview["preview_intent"],
                request=request,
                principal=principal,
                manager_channel=channel,
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_REQUEST_REPLAY_CONFLICT",
        )
        self.assertEqual(event_path.read_bytes(), before_conflict)
        self.assertEqual(
            issued_buffers[-1], bytearray(b"\x00" * 32)
        )

    def test_forged_engine_proof_leaves_business_nonce_and_events_unchanged(
        self,
    ) -> None:
        started, secret, verifier = self._start_authorized_task()
        principal = self._principal()
        issued_buffers: list[bytearray] = []

        class Channel:
            def principal_for(self, _request_identity):
                return principal

            def resolve_secret(self, capability_id):
                if capability_id != verifier.capability_id:
                    raise AssertionError("unexpected capability")
                owned = bytearray(secret)
                issued_buffers.append(owned)
                return owned

        input_value = {
            "contract": "dev-flow-action-transition-input/v1",
            "to": "BLOCKED",
            "note": "proof must bind manager nonce and transition",
        }
        preview = dev_flow.controller_action_preview(
            started["task_id"],
            expected_revision=started["revision"],
            action_id="transition",
            input_value=input_value,
            data_dir=self.data,
        )
        request = self._request(
            started,
            verifier,
            nonce="d" * 64,
        )
        state_path = (
            self.data / "tasks" / started["task_id"] / "state.json"
        )
        event_path = state_path.with_name("events.jsonl")
        before_state = state_path.read_bytes()
        before_events = event_path.read_bytes()

        with (
            mock.patch.object(
                dev_flow,
                "_workflow_transition_mint_engine_commit_proof",
                return_value=object(),
            ),
            self.assertRaises(dev_flow.FlowError) as raised,
        ):
            dev_flow.controller_action_apply(
                started["task_id"],
                expected_revision=started["revision"],
                action_id="transition",
                input_value=input_value,
                preview_intent=preview["preview_intent"],
                request=request,
                principal=principal,
                manager_channel=Channel(),
                data_dir=self.data,
            )

        self.assertEqual(
            raised.exception.code,
            "V3_ENGINE_COMMIT_PROOF_INVALID",
        )
        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(event_path.read_bytes(), before_events)
        persisted = dev_flow.load_state(
            started["task_id"], self.data
        )
        persisted_verifier = persisted["orchestration"][
            "manager_capabilities"
        ][verifier.capability_id]
        self.assertEqual(
            persisted_verifier["used_request_nonce_sha256s"],
            [],
        )
        self.assertEqual(
            issued_buffers,
            [bytearray(b"\x00" * len(secret))],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
