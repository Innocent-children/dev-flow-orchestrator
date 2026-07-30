from __future__ import annotations

import dataclasses
import json
import socket
import time
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


class _InjectedPreflightFailure(RuntimeError):
    pass


class V3PreflightActionTransactionTests(DevFlowTestCase):
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
                bundle = services.catalog.resolve("lite", 3)
                action_suites = {
                    str(suite)
                    for edge in bundle.action_edges
                    for suite in edge["required_suites"]
                }
                activation["required_suites"] = sorted(
                    {
                        *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            "single-repository"
                        ],
                        *action_suites,
                    }
                )
            else:
                activation["active"] = False
                activation["required_suites"] = []
            activations.append(MappingProxyType(activation))
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=tuple(activations),
            ),
        )

    def _start(self, task_id: str) -> dict:
        repository, _ = self.make_repo(f"{task_id}-repository")
        with mock.patch.object(
            dev_flow,
            "_workflow_runtime_services",
            self._active_lite_services(),
        ):
            return self.cli(
                "start",
                "exercise transactional preflight",
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

    def _authorize(
        self, started: dict
    ) -> tuple[object, bytearray]:
        state = dev_flow.load_state(started["task_id"], self.data)
        secret = bytearray(b"P" * 32)
        verifier = dev_flow.issue_manager_capability(
            task_id=started["task_id"],
            issued_for_task_revision=started["revision"],
            manager_session_id="preflight-manager",
            allowed_actions=dev_flow._manager_default_actions(state),
            ttl_ns=60_000_000_000,
            wall_time_ns=time.time_ns(),
            monotonic_time_ns=dev_flow._manager_system_monotonic_ns(),
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="mcp-secret-channel",
            operator_confirmation_sha256="6" * 64,
            issuance_audit_sha256="7" * 64,
            manager_secret=secret,
        )
        state["orchestration"] = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {
                verifier.capability_id: verifier.as_persistent_dict()
            },
        }
        self._state_path(started["task_id"]).write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.addCleanup(dev_flow._manager_zeroize, secret)
        return verifier, secret

    def _state_path(self, task_id: str) -> Path:
        return self.data / "tasks" / task_id / "state.json"

    def _task_dir(self, task_id: str) -> Path:
        return self._state_path(task_id).parent

    @staticmethod
    def _request(
        started: dict,
        verifier: object,
        *,
        action_id: str,
        revision: int,
        nonce: str,
    ) -> dict:
        return {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": verifier.capability_id,
            "task_id": started["task_id"],
            "manager_session_id": "preflight-manager",
            "action_id": action_id,
            "expected_revision": revision,
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

    def _preflight_preview(self, started: dict) -> dict:
        return self.cli(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--preview",
        )

    def _apply_preflight(
        self,
        started: dict,
        preview: dict,
        verifier: object,
        secret: bytearray,
        *,
        nonce: str,
        expected_code: int = 0,
    ) -> dict:
        request = self._request(
            started,
            verifier,
            action_id="task.preflight",
            revision=started["revision"],
            nonce=nonce,
        )
        return self._with_secret(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--confirm-preview",
            preview["transition_preview"]["token"],
            request=request,
            secret=secret,
            expected_code=expected_code,
        )

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

    def _used_nonces(
        self, state: dict, capability_id: str
    ) -> list[str]:
        verifier = state["orchestration"]["manager_capabilities"][
            capability_id
        ]
        return list(verifier["used_request_nonce_sha256s"])

    def test_normal_commit_binds_both_edges_and_consumes_nonce_atomically(
        self,
    ) -> None:
        started = self._start("preflight-tx-normal")
        verifier, secret = self._authorize(started)
        preview = self._preflight_preview(started)
        observations: list[str] = []
        original_observe = (
            dev_flow._v3_preflight_reobserve_complete_evidence
        )

        def observe(*args: object, **kwargs: object) -> str:
            observations.append("claimed")
            return original_observe(*args, **kwargs)

        with mock.patch.object(
            dev_flow,
            "_v3_preflight_reobserve_complete_evidence",
            side_effect=observe,
        ):
            applied = self._apply_preflight(
                started,
                preview,
                verifier,
                secret,
                nonce="1" * 64,
            )

        self.assertEqual(applied["status"], "PREFLIGHTED")
        self.assertEqual(
            applied["revision"], started["revision"] + 1
        )
        self.assertEqual(observations, ["claimed"])
        task_dir = self._task_dir(started["task_id"])
        archives = self._archives(task_dir)
        self.assertEqual(len(archives), 1)
        journal = json.loads(archives[0].read_text(encoding="utf-8"))
        bindings = journal["bindings"]
        receipt = journal["receipt"]
        self.assertNotEqual(
            bindings["authorization_action_edge_id"],
            bindings["completion_edge_id"],
        )
        self.assertEqual(
            bindings["action_edge_id"],
            bindings["completion_edge_id"],
        )
        self.assertEqual(
            receipt["authorization_action_edge_id"],
            bindings["authorization_action_edge_id"],
        )
        self.assertEqual(
            receipt["completion_edge_id"],
            bindings["completion_edge_id"],
        )
        self.assertEqual(journal["phase"], "COMMITTED")
        self.assertTrue(journal["finalization"]["nonce_consumed"])
        persisted = dev_flow.load_state(started["task_id"], self.data)
        nonce_sha256 = dev_flow.manager_request_nonce_digest(
            dev_flow.validate_manager_capability_request(
                self._request(
                    started,
                    verifier,
                    action_id="task.preflight",
                    revision=started["revision"],
                    nonce="1" * 64,
                )
            )
        )
        self.assertEqual(
            self._used_nonces(persisted, verifier.capability_id),
            [nonce_sha256],
        )
        revision_events = [
            event
            for event in self._events(task_dir)
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

    def test_wrong_node_and_preview_mismatch_write_nothing(
        self,
    ) -> None:
        started = self._start("preflight-tx-zero-write")
        verifier, secret = self._authorize(started)
        preview = self._preflight_preview(started)
        state_path = self._state_path(started["task_id"])
        task_dir = state_path.parent
        before_state = state_path.read_bytes()
        before_events = (task_dir / "events.jsonl").read_bytes()
        with (
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
            ) as execute,
            mock.patch.object(
                dev_flow,
                "_v3_preflight_reobserve_complete_evidence",
            ) as observe,
        ):
            request = self._request(
                started,
                verifier,
                action_id="task.preflight",
                revision=started["revision"],
                nonce="2" * 64,
            )
            mismatch = self._with_secret(
                "preflight",
                started["task_id"],
                "--expected-revision",
                str(started["revision"]),
                "--confirm-preview",
                preview["transition_preview"]["token"] + "-wrong",
                request=request,
                secret=secret,
                expected_code=2,
            )
        self.assertEqual(mismatch["error"]["code"], "PREFLIGHT_PREVIEW_STALE")
        execute.assert_not_called()
        observe.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), before_events
        )
        self.assertFalse((task_dir / "action-executions").exists())

        transition_preview = self.cli(
            "transition",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--to",
            "BLOCKED",
            "--note",
            "exercise wrong-node rejection",
            "--preview",
        )
        transition_request = self._request(
            started,
            verifier,
            action_id="task.transition",
            revision=started["revision"],
            nonce="3" * 64,
        )
        blocked = self._with_secret(
            "transition",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--to",
            "BLOCKED",
            "--note",
            "exercise wrong-node rejection",
            "--confirm-intent",
            transition_preview["preview"]["intent_id"],
            request=transition_request,
            secret=secret,
        )
        blocked_state = json.loads(state_path.read_text(encoding="utf-8"))
        blocked_state["blocked"]["phase"] = "preflight"
        state_path.write_text(
            json.dumps(
                blocked_state,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        before_state = state_path.read_bytes()
        before_events = (task_dir / "events.jsonl").read_bytes()
        with (
            mock.patch.object(dev_flow, "_preflight_repo") as git_effect,
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
            ) as execute,
        ):
            rejected = self.cli(
                "preflight",
                started["task_id"],
                "--expected-revision",
                str(blocked["revision"]),
                "--preview",
                expected_code=2,
            )
        self.assertEqual(
            rejected["error"]["code"],
            "WORKFLOW_ACTION_PLACEMENT_INVALID",
        )
        git_effect.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before_state)
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), before_events
        )

    def test_wrong_target_cross_trigger_missing_and_ambiguous_are_zero_write(
        self,
    ) -> None:
        started = self._start("preflight-tx-edge-rejection")
        current = dev_flow.load_state(started["task_id"], self.data)
        task_dir = self._task_dir(started["task_id"])
        before_state = self._state_path(started["task_id"]).read_bytes()
        before_events = (task_dir / "events.jsonl").read_bytes()
        authorization_edge = dev_flow.resolve_v3_node_action_edge(
            current, "preflight", selector="initial"
        )
        completion_edge = (
            dev_flow.resolve_v3_workflow_action_completion_edge(
                current,
                authorization_edge,
                public_command="preflight",
                target="PREFLIGHTED",
            )
        )

        def invocation(
            proposed_edge: object,
            *,
            action_id: str,
            status: str,
        ) -> object:
            return dev_flow.WorkflowActionInvocation(
                kind="node",
                public_command="preflight",
                selector="initial",
                action_outcome=dev_flow.ActionOutcome(
                    action_id,
                    str(proposed_edge),
                    proposed_state_delta={
                        "set": {"/status": status},
                        "remove": [],
                        "operations": [],
                    },
                ),
                action_parameters={"mode": "initial"},
            )

        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "lite", 3
        )
        cross_edge = next(
            edge
            for edge in bundle.legal_movement_edges("INTAKE")
            if edge["trigger"]["id"] != "preflight"
        )
        cases = (
            (
                "wrong-target",
                invocation(
                    completion_edge["id"],
                    action_id="preflight",
                    status="BLOCKED",
                ),
            ),
            (
                "cross-trigger",
                invocation(
                    cross_edge["id"],
                    action_id=str(cross_edge["trigger"]["id"]),
                    status=str(cross_edge["target"]),
                ),
            ),
            (
                "missing",
                invocation(
                    "missing.preflight.edge.v1",
                    action_id="preflight",
                    status="PREFLIGHTED",
                ),
            ),
        )
        task_lock = dev_flow._task_lock(task_dir)
        registry_lock = dev_flow._workspace_registry_lock(
            dev_flow.resolve_data_dir(self.data)
        )
        with task_lock, registry_lock:
            for label, request in cases:
                with (
                    self.subTest(label=label),
                    self.assertRaises(
                        dev_flow.WorkflowActionTransactionError
                    ) as raised,
                ):
                    dev_flow.preview_v3_workflow_action_transaction(
                        current, request
                    )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
                )

            class AmbiguousBundle:
                def legal_action_edges(
                    self, source: str
                ) -> tuple[object, ...]:
                    return bundle.legal_action_edges(source)

                def legal_movement_edges(
                    self, source: str
                ) -> tuple[object, ...]:
                    edges = bundle.legal_movement_edges(source)
                    return (*edges, completion_edge)

            with (
                mock.patch.object(
                    dev_flow,
                    "_workflow_action_bundle",
                    return_value=AmbiguousBundle(),
                ),
                self.assertRaises(
                    dev_flow.WorkflowActionTransactionError
                ) as ambiguous,
            ):
                dev_flow.resolve_v3_workflow_action_completion_edge(
                    current,
                    authorization_edge,
                    public_command="preflight",
                    target="PREFLIGHTED",
                )
        self.assertEqual(
            ambiguous.exception.code,
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
        )
        self.assertEqual(
            self._state_path(started["task_id"]).read_bytes(),
            before_state,
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), before_events
        )
        self.assertFalse((task_dir / "action-executions").exists())

    def test_lost_dispatch_response_never_redispatches_or_consumes_nonce(
        self,
    ) -> None:
        started = self._start("preflight-tx-lost-dispatch")
        verifier, secret = self._authorize(started)
        preview = self._preflight_preview(started)
        original_execute = (
            dev_flow.execute_v3_workflow_action_transaction
        )
        original_observe = (
            dev_flow._v3_preflight_reobserve_complete_evidence
        )
        observations: list[str] = []

        def observe(*args: object, **kwargs: object) -> str:
            observations.append("claimed")
            return original_observe(*args, **kwargs)

        def fail(stage: str) -> None:
            if stage == "after-dispatch":
                raise _InjectedPreflightFailure(stage)

        def execute(*args: object, **kwargs: object) -> object:
            kwargs["failure_hook"] = fail
            return original_execute(*args, **kwargs)

        with (
            mock.patch.object(
                dev_flow,
                "_v3_preflight_reobserve_complete_evidence",
                side_effect=observe,
            ),
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute,
            ),
        ):
            failed = self._apply_preflight(
                started,
                preview,
                verifier,
                secret,
                nonce="4" * 64,
                expected_code=1,
            )
        self.assertEqual(failed["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(
            failed["error"]["details"]["type"],
            "_InjectedPreflightFailure",
        )
        task_dir = self._task_dir(started["task_id"])
        active = sorted(
            (task_dir / "action-executions" / "active").glob(
                "*.json"
            )
        )
        self.assertEqual(len(active), 1)
        active_name = active[0].name
        recovered = self._apply_preflight(
            started,
            preview,
            verifier,
            secret,
            nonce="4" * 64,
            expected_code=2,
        )
        self.assertEqual(
            recovered["error"]["code"],
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_REQUIRED",
        )
        self.assertEqual(
            recovered["error"]["details"]["status"],
            "QUARANTINE_REQUIRED",
        )
        self.assertEqual(observations, ["claimed"])
        self.assertEqual(
            [path.name for path in sorted(active[0].parent.glob("*.json"))],
            [active_name],
        )
        persisted = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(persisted["revision"], started["revision"])
        self.assertEqual(
            self._used_nonces(persisted, verifier.capability_id), []
        )

    def test_complete_receipt_restart_commits_same_journal_without_dispatch(
        self,
    ) -> None:
        started = self._start("preflight-tx-receipt-restart")
        verifier, secret = self._authorize(started)
        preview = self._preflight_preview(started)
        original_execute = (
            dev_flow.execute_v3_workflow_action_transaction
        )
        original_observe = (
            dev_flow._v3_preflight_reobserve_complete_evidence
        )
        observations: list[str] = []

        def observe(*args: object, **kwargs: object) -> str:
            observations.append("claimed")
            return original_observe(*args, **kwargs)

        def fail(stage: str) -> None:
            if stage == "after-receipt-verified":
                raise _InjectedPreflightFailure(stage)

        def execute(*args: object, **kwargs: object) -> object:
            kwargs["failure_hook"] = fail
            return original_execute(*args, **kwargs)

        with (
            mock.patch.object(
                dev_flow,
                "_v3_preflight_reobserve_complete_evidence",
                side_effect=observe,
            ),
            mock.patch.object(
                dev_flow,
                "execute_v3_workflow_action_transaction",
                side_effect=execute,
            ),
        ):
            failed = self._apply_preflight(
                started,
                preview,
                verifier,
                secret,
                nonce="5" * 64,
                expected_code=1,
            )
        self.assertEqual(failed["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(
            failed["error"]["details"]["type"],
            "_InjectedPreflightFailure",
        )
        task_dir = self._task_dir(started["task_id"])
        active = sorted(
            (task_dir / "action-executions" / "active").glob(
                "*.json"
            )
        )
        self.assertEqual(len(active), 1)
        active_name = active[0].name
        pending = json.loads(active[0].read_text(encoding="utf-8"))
        self.assertEqual(pending["phase"], "RECEIPT_VERIFIED")
        before = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(before["revision"], started["revision"])
        self.assertEqual(
            self._used_nonces(before, verifier.capability_id), []
        )

        applied = self._apply_preflight(
            started,
            preview,
            verifier,
            secret,
            nonce="5" * 64,
        )
        self.assertEqual(applied["status"], "PREFLIGHTED")
        self.assertEqual(observations, ["claimed"])
        self.assertFalse(active[0].exists())
        archives = self._archives(task_dir)
        self.assertEqual([path.name for path in archives], [active_name])
        persisted = dev_flow.load_state(started["task_id"], self.data)
        request = dev_flow.validate_manager_capability_request(
            self._request(
                started,
                verifier,
                action_id="task.preflight",
                revision=started["revision"],
                nonce="5" * 64,
            )
        )
        self.assertEqual(
            self._used_nonces(persisted, verifier.capability_id),
            [dev_flow.manager_request_nonce_digest(request)],
        )
        manager_events = [
            event
            for event in self._events(task_dir)
            if event["revision"] == applied["revision"]
            and event["type"]
            == dev_flow.MANAGER_CAPABILITY_AUTHORIZED_EVENT
        ]
        self.assertEqual(len(manager_events), 1)
