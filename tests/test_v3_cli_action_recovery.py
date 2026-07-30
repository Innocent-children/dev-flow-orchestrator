from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow
from tests.test_action_execution_journal import _effect, _journal_core


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"

# OpenSpec 8.8 requires reconciliation to remain usable through the exact
# standard-library CLI when every optional host integration is absent.  These
# names intentionally distinguish action-execution quarantine from the legacy
# mutation-quarantine command.
ACTION_RECOVERY_CLI_GRAMMAR = {
    "action-recovery-inspect": frozenset(
        {"task_id", "execution_id", "data_dir"}
    ),
    "action-recovery-preview": frozenset(
        {
            "task_id",
            "execution_id",
            "attempt_id",
            "outcome",
            "expected_revision",
            "evidence_json",
            "data_dir",
        }
    ),
    "action-recovery-apply": frozenset(
        {
            "task_id",
            "execution_id",
            "attempt_id",
            "outcome",
            "expected_revision",
            "confirm_preview",
            "evidence_json",
            "data_dir",
        }
    ),
}


class V3CliActionRecoveryTests(DevFlowTestCase):
    def _registered_cli_parsers(self) -> dict[str, object]:
        parser = dev_flow.build_parser()
        choices: dict[str, object] = {}
        for action in parser._actions:
            candidate = getattr(action, "choices", None)
            if isinstance(candidate, dict):
                choices.update(candidate)
        return choices

    def _assert_terminal_reconciliation_response(
        self,
        response: dict,
        *,
        task_id: str,
        execution_id: str,
        attempt_id: str,
        outcome: str,
        original_dispatch_count: int = 1,
        compensation_dispatch_count: int = 0,
    ) -> None:
        """Assert the bounded CLI result needed by the future 8.8 E2E.

        The response must expose enough durable identities to verify a lost
        response by repeating ``action-recovery-apply`` in a new process.  It
        deliberately has no field authorizing redispatch of the target.
        """

        self.assertEqual(
            response.get("schema"),
            "dev-flow-v4-action-reconciliation-cli-result/v1",
        )
        self.assertEqual(response.get("task_id"), task_id)
        self.assertEqual(
            response.get("target_execution_id"), execution_id
        )
        self.assertEqual(response.get("attempt_id"), attempt_id)
        self.assertEqual(response.get("status"), outcome)
        self.assertEqual(response.get("blocked"), False)
        self.assertEqual(
            response.get("target_dispatcher_invocations"), 0
        )
        self.assertEqual(
            response.get("original_dispatch_count"),
            original_dispatch_count,
        )
        self.assertEqual(
            response.get("compensation_dispatch_count"),
            compensation_dispatch_count,
        )
        self.assertIsInstance(response.get("event_sha256"), str)
        self.assertEqual(len(response["event_sha256"]), 64)
        self.assertIsInstance(response.get("outbox_sha256"), str)
        self.assertEqual(len(response["outbox_sha256"]), 64)
        self.assertIsInstance(response.get("revision"), int)
        self.assertIsInstance(response.get("archive_path"), str)
        self.assertNotIn("operator_intervention", response)

    def _assert_operator_intervention_response(
        self,
        response: dict,
        *,
        task_id: str,
        execution_id: str,
        attempt_id: str,
        effect_ids: list[str],
        affected_scopes: dict,
        original_dispatch_count: int = 1,
    ) -> None:
        self.assertEqual(
            response.get("schema"),
            "dev-flow-v4-action-reconciliation-cli-result/v1",
        )
        self.assertEqual(response.get("task_id"), task_id)
        self.assertEqual(
            response.get("target_execution_id"), execution_id
        )
        self.assertEqual(response.get("attempt_id"), attempt_id)
        self.assertEqual(response.get("status"), "UNRESOLVED")
        self.assertEqual(response.get("blocked"), True)
        self.assertEqual(
            response.get("target_dispatcher_invocations"), 0
        )
        self.assertEqual(
            response.get("original_dispatch_count"),
            original_dispatch_count,
        )
        self.assertEqual(
            response.get("compensation_dispatch_count"), 0
        )
        self.assertIsNone(response.get("event_sha256"))
        self.assertIsNone(response.get("outbox_sha256"))
        self.assertIsNone(response.get("archive_path"))
        self.assertIsNone(response.get("compensation_execution_id"))
        self.assertEqual(
            response.get("operator_intervention"),
            {
                "schema": "dev-flow-v4-operator-intervention/v1",
                "required": True,
                "reason": "TRUSTED_HOST_AUTHORITY_UNAVAILABLE",
                "target_execution_id": execution_id,
                "effect_ids": sorted(effect_ids),
                "affected_scopes": affected_scopes,
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

    def test_8_8_registers_cli_only_action_recovery_grammar(
        self,
    ) -> None:
        """Fail until action reconciliation is reachable without MCP/SDKs."""

        parsers = self._registered_cli_parsers()
        missing = sorted(set(ACTION_RECOVERY_CLI_GRAMMAR) - set(parsers))
        self.assertEqual(
            missing,
            [],
            (
                "OpenSpec 8.8 is blocked: the isolated CLI has no "
                "action-execution reconciliation inspect/preview/apply "
                f"surface; missing={missing}"
            ),
        )
        for command, required_destinations in (
            ACTION_RECOVERY_CLI_GRAMMAR.items()
        ):
            configured = parsers[command]
            destinations = {
                str(action.dest)
                for action in configured._actions
                if getattr(action, "dest", None) not in {None, "help"}
            }
            self.assertEqual(
                sorted(required_destinations - destinations),
                [],
                (
                    f"{command} does not bind the exact recovery "
                    "identity/CAS/evidence grammar"
                ),
            )

    def _active_services(self, workflow_id: str = "full") -> object:
        services = dev_flow.workflow_runtime_services()
        activations = []
        selected_found = False
        for frozen in services.catalog.activations:
            activation = dict(frozen)
            selected = (
                activation["workflow_id"] == workflow_id
                and activation["workflow_version"] == 4
                and activation["execution_profile"]
                == "single-repository"
            )
            selected_found = selected_found or selected
            activation["active"] = selected
            if selected:
                bundle = services.catalog.resolve(workflow_id, 4)
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
                activation["required_suites"] = []
            activations.append(MappingProxyType(activation))
        bundle = services.catalog.resolve(workflow_id, 4)
        action_suites = {
            str(suite)
            for edge in bundle.action_edges
            for suite in edge["required_suites"]
        }
        if not selected_found:
            activations.append(
                MappingProxyType(
                    {
                        "workflow_id": workflow_id,
                        "workflow_version": 4,
                        "bundle_sha256": bundle.bundle_sha256,
                        "execution_profile": "single-repository",
                        "active": True,
                        "required_suites": sorted(
                            {
                                *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                                    "single-repository"
                                ],
                                *action_suites,
                            }
                        ),
                    }
                )
            )
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=tuple(activations),
            ),
        )

    def _start(
        self,
        task_id: str = "cli-action-recovery-task",
        *,
        workflow_id: str = "full",
    ) -> tuple[dict, Path]:
        repository, _ = self.make_repo(f"{task_id}-repository")
        slow = repository / "slow-untracked.bin"
        with slow.open("wb") as stream:
            stream.truncate(128 * 1024 * 1024)
        with mock.patch.object(
            dev_flow,
            "_workflow_runtime_services",
            self._active_services(workflow_id),
        ):
            lite_arguments = (
                (
                    "--change-category",
                    "docs",
                    "--target-path",
                    "README.md",
                )
                if workflow_id == "lite"
                else ()
            )
            started = self.cli(
                "start",
                "exercise isolated CLI action recovery",
                "--repo",
                str(repository),
                "--task-id",
                task_id,
                "--flow",
                workflow_id,
                "--workspace-strategy",
                (
                    "worktree"
                    if workflow_id == "full"
                    else "in-place"
                ),
                *lite_arguments,
            )
        return started, repository

    def _authorize(
        self, started: dict
    ) -> tuple[dict, bytearray]:
        preview_code, preview = self._run_cli(
            "manager-authorize",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--manager-session-id",
            "cli-recovery-manager",
            "--ttl-seconds",
            "900",
            "--preview",
        )
        self.assertEqual(preview_code, 0, preview)
        reader, writer = os.pipe()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(SCRIPT),
                    "manager-authorize",
                    started["task_id"],
                    "--expected-revision",
                    str(started["revision"]),
                    "--manager-session-id",
                    "cli-recovery-manager",
                    "--ttl-seconds",
                    "900",
                    "--confirm-intent",
                    preview["preview"]["intent_id"],
                    "--manager-secret-fd",
                    str(writer),
                    "--data-dir",
                    str(self.data),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(writer,),
                env=self._environment(),
            )
            os.close(writer)
            writer = -1
            stdout, stderr = process.communicate(timeout=30)
            frame = bytearray()
            while True:
                chunk = os.read(reader, 4096)
                if not chunk:
                    break
                frame.extend(chunk)
        finally:
            os.close(reader)
            if writer >= 0:
                os.close(writer)
        self.assertEqual(
            process.returncode,
            0,
            f"stdout={stdout!r} stderr={stderr!r}",
        )
        self.assertEqual(stderr, b"")
        lines = stdout.splitlines()
        self.assertEqual(len(lines), 1, stdout)
        authorized = json.loads(lines[0].decode("utf-8"))
        verifier = dev_flow.load_state(
            started["task_id"], self.data
        )["orchestration"]["manager_capabilities"][
            authorized["capability"]["capability_id"]
        ]
        self.assertLess(
            time.time_ns(),
            verifier["expires_at_wall_ns"],
            verifier,
        )
        self.assertLess(
            (
                dev_flow._manager_system_monotonic_ns()
                - verifier["issued_at_monotonic_ns"]
            ),
            verifier["ttl_ns"],
            verifier,
        )
        self.assertGreaterEqual(len(frame), 4)
        (size,) = struct.unpack(">I", bytes(frame[:4]))
        self.assertEqual(size, len(frame[4:]))
        secret = bytearray(frame[4:])
        dev_flow._manager_zeroize(frame)
        self.addCleanup(dev_flow._manager_zeroize, secret)
        return authorized, secret

    def _environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }

    def _run_cli(self, *arguments: str) -> tuple[int, dict]:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(SCRIPT),
                *arguments,
                "--data-dir",
                str(self.data),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=self._environment(),
        )
        self.assertEqual(completed.stderr, b"")
        lines = completed.stdout.splitlines()
        self.assertEqual(len(lines), 1, completed.stdout)
        return (
            completed.returncode,
            json.loads(lines[0].decode("utf-8")),
        )

    def _manager_process(
        self,
        arguments: tuple[str, ...],
        *,
        request: dict,
        secret: bytearray,
        failure_point: str | None = None,
    ) -> tuple[subprocess.Popen[bytes], socket.socket]:
        publisher, consumer = socket.socketpair()
        try:
            dev_flow.publish_manager_secret(
                dev_flow.ManagerSecretChannelConfig(
                    publisher.fileno()
                ),
                secret,
            )
            cli_arguments = [
                *arguments,
                "--manager-request-json",
                json.dumps(
                    request,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "--manager-secret-fd",
                str(consumer.fileno()),
                "--data-dir",
                str(self.data),
            ]
            command = [
                sys.executable,
                "-I",
                "-S",
                str(SCRIPT),
                *cli_arguments,
            ]
            if failure_point is not None:
                harness = "\n".join(
                    (
                        "import importlib.util, os, sys",
                        "path, point = sys.argv[1:3]",
                        "spec = importlib.util.spec_from_file_location(",
                        "    'isolated_recovery_cli', path",
                        ")",
                        "module = importlib.util.module_from_spec(spec)",
                        "sys.modules[spec.name] = module",
                        "spec.loader.exec_module(module)",
                        "original = module."
                        "reconcile_v3_workflow_action_quarantine",
                        "def wrapped(*args, **kwargs):",
                        "    def fail(stage):",
                        "        if stage == point:",
                        "            os._exit(91)",
                        "    kwargs['failure_hook'] = fail",
                        "    return original(*args, **kwargs)",
                        "module.reconcile_v3_workflow_action_quarantine = "
                        "wrapped",
                        "raise SystemExit(module.main(sys.argv[3:]))",
                    )
                )
                command = [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    harness,
                    str(SCRIPT),
                    failure_point,
                    *cli_arguments,
                ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(consumer.fileno(),),
                env=self._environment(),
            )
        except Exception:
            publisher.close()
            raise
        finally:
            consumer.close()
        return process, publisher

    def _manager_cli(
        self,
        arguments: tuple[str, ...],
        *,
        request: dict,
        secret: bytearray,
    ) -> tuple[int, dict]:
        process, publisher = self._manager_process(
            arguments,
            request=request,
            secret=secret,
        )
        try:
            stdout, stderr = process.communicate(timeout=30)
        finally:
            publisher.close()
        self.assertEqual(stderr, b"")
        lines = stdout.splitlines()
        self.assertEqual(len(lines), 1, stdout)
        return process.returncode, json.loads(
            lines[0].decode("utf-8")
        )

    def _journal_secret(
        self, task_id: str, capability: dict, secret: bytearray
    ) -> str:
        payload = dev_flow._json_bytes(
            {
                "contract": (
                    "dev-flow-manager-workflow-action-"
                    "journal-secret/v1"
                ),
                "task_id": task_id,
                "capability_id": capability["capability_id"],
                "manager_session_id": capability[
                    "manager_session_id"
                ],
            }
        )
        return hmac.new(
            secret,
            dev_flow._manager_workflow_action_secret_domain
            + len(payload).to_bytes(8, "big")
            + payload,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _invocation_json(invocation: object) -> dict:
        outcome = invocation.action_outcome
        value = {
            "kind": invocation.kind,
            "public_command": invocation.public_command,
            "selector": invocation.selector,
            "target": invocation.target,
            "edge_selector": invocation.edge_selector,
            "action_outcome": {
                "action_id": outcome.action_id,
                "proposed_edge_id": outcome.proposed_edge_id,
                "evidence_records": [
                    dict(value)
                    for value in outcome.evidence_records
                ],
                "proposed_state_delta": dict(
                    outcome.proposed_state_delta
                ),
                "audit_facts": [
                    {
                        "fact_type": fact.fact_type,
                        "payload": dict(fact.payload),
                    }
                    for fact in outcome.audit_facts
                ],
                "external_postconditions": [
                    dict(value)
                    for value in outcome.external_postconditions
                ],
            },
            "approval_outcome": None,
            "action_parameters": dict(
                invocation.action_parameters
            ),
            "evidence": dict(invocation.evidence),
            "confirm_intent": invocation.confirm_intent,
        }
        return json.loads(
            dev_flow.semantic_json_bytes(
                dev_flow._workflow_transition_public(value)
            ).decode("utf-8")
        )

    def _accepted_quarantine_fixture(
        self,
        started: dict,
        authorized: dict,
        secret: bytearray,
    ) -> tuple[dict, dict]:
        task_id = started["task_id"]
        task_dir = self.data / "tasks" / task_id
        state = dev_flow.load_state(task_id, self.data)
        outcome = dev_flow.ActionOutcome(
            "full.intake.preflight.v1",
            "full.action.intake.preflight.v1",
            evidence_records=(
                {"validator": "cli-accepted-recovery/v1"},
            ),
            proposed_state_delta={
                "set": {
                    "/preflight": {"status": "ready"},
                    "/repositories": state["repositories"],
                    "/risk_assessment": {"level": "low"},
                },
                "remove": [],
                "operations": [],
            },
            audit_facts=(
                dev_flow.AuditFact(
                    "cli-accepted-recovery",
                    {"validator": "cli-accepted-recovery/v1"},
                ),
            ),
        )
        parameters = {"mode": "initial"}
        evidence = {"validator": "cli-accepted-recovery/v1"}
        with dev_flow._task_lock(task_dir):
            preview = dev_flow.evaluate_v3_node_action(
                state,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters=parameters,
                evidence=evidence,
                preview=True,
            )
        invocation = dev_flow.WorkflowActionInvocation(
            kind="node",
            public_command="preflight",
            selector="initial",
            action_outcome=outcome,
            action_parameters=parameters,
            evidence=evidence,
            confirm_intent=preview.intent["intent_id"],
        )
        roles = dev_flow._workflow_tx_edge_roles(
            state, invocation
        )
        journal_secret = self._journal_secret(
            task_id, authorized["capability"], secret
        )
        execution_id = "cli-accepted-recovery-execution"
        repository_ids = [
            str(repository["id"])
            for repository in state["repositories"]
        ]
        authorization = dev_flow.WorkflowActionAuthorization(
            kind="manager",
            authorization_sha256="7" * 64,
            capability_sha256=hashlib.sha256(
                dev_flow.semantic_json_bytes(
                    authorized["capability"]
                )
            ).hexdigest(),
            request_nonce_sha256="8" * 64,
            principal="manager:cli-recovery-manager",
            ownership_sha256="9" * 64,
            registry_state_sha256="a" * 64,
            reauthenticate=lambda: journal_secret,
            nonce_consumed_verifier=(
                lambda _state, _events: True
            ),
        )
        effect_binding = dev_flow.WorkflowActionEffectBinding(
            effect_id="full.intake.preflight.v1.effect",
            kind="filesystem",
            scope_kinds=("repository", "task"),
            scopes={
                "repository_ids": repository_ids,
                "node_ids": [],
                "worktree_ids": [],
                "lease_ids": [],
                "paths": [],
                "external_resources": [],
            },
            safe_inputs={"mode": "cli-accepted-recovery"},
            attempt_id="cli-accepted-effect-attempt",
        )
        sealed = dev_flow.compile_v3_workflow_action_journal(
            state,
            roles.authorization_action_edge,
            preview,
            invocation,
            authorization,
            effect_binding,
            execution_id=execution_id,
            manager_secret=journal_secret,
        )
        store = dev_flow.ActionExecutionStore(task_dir)
        index = store.initialize_index(task_id).index
        persisted = store.persist_initial(
            sealed,
            expected_index=dev_flow.cas_token(index),
            manager_secret=journal_secret,
        )
        assert persisted.record is not None
        index, current = persisted.index, persisted.record
        store.claim_for_dispatch(
            execution_id,
            "full.intake.preflight.v1.effect",
            "cli-accepted-claim",
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            manager_secret=journal_secret,
        )
        index = store.read_index(expected_task_id=task_id)
        current = store.read_active_journal(
            execution_id, manager_secret=journal_secret
        )
        containment = dev_flow.new_containment(
            current,
            "full.intake.preflight.v1.effect",
            index=index,
            expected_index=dev_flow.cas_token(index),
            manager_secret=journal_secret,
        )
        containment_result = store.persist_containment(
            containment,
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            manager_secret=journal_secret,
        )
        assert containment_result.record is not None
        containment = containment_result.record

        def update(value: dict) -> None:
            nonlocal index, current
            result = store.persist_update(
                value,
                expected_index=dev_flow.cas_token(index),
                expected_journal=dev_flow.cas_token(current),
                manager_secret=journal_secret,
            )
            assert result.record is not None
            index, current = result.index, result.record

        update(
            dev_flow.advance_effect_phase(
                current,
                "full.intake.preflight.v1.effect",
                "RUNNING",
                manager_secret=journal_secret,
                containment_record_sha256=containment[
                    "record_sha256"
                ],
            )
        )
        quiesced = dev_flow.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256="5" * 64,
        )
        contained = store.persist_containment(
            quiesced,
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            expected_containment=dev_flow.cas_token(containment),
            manager_secret=journal_secret,
        )
        assert contained.record is not None
        quiesced = contained.record
        update(
            dev_flow.advance_effect_phase(
                current,
                "full.intake.preflight.v1.effect",
                "QUIESCED",
                manager_secret=journal_secret,
                containment_record_sha256=quiesced[
                    "record_sha256"
                ],
                receipt_sha256="5" * 64,
            )
        )
        closed = dev_flow.advance_containment(
            quiesced, "CLOSED"
        )
        contained = store.persist_containment(
            closed,
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            expected_containment=dev_flow.cas_token(quiesced),
            manager_secret=journal_secret,
        )
        assert contained.record is not None
        closed = contained.record
        update(
            dev_flow.advance_effect_phase(
                current,
                "full.intake.preflight.v1.effect",
                "VERIFIED",
                manager_secret=journal_secret,
                containment_record_sha256=closed[
                    "record_sha256"
                ],
                receipt_sha256="5" * 64,
            )
        )
        update(
            dev_flow.advance_global_settlement(
                current, manager_secret=journal_secret
            )
        )
        receipt = dev_flow.build_v3_workflow_action_receipt(
            state,
            preview,
            task_dir,
            execution_id=execution_id,
            effect_receipt_sha256="5" * 64,
            authorization_action_edge_id=(
                roles.authorization_action_edge_id
            ),
            completion_edge_id=roles.completion_edge_id,
        )
        update(
            dev_flow.verify_receipt_intent(
                current,
                receipt,
                manager_secret=journal_secret,
            )
        )
        update(
            dev_flow.quarantine_journal(
                current,
                reason_code="cli-accepted-recovery",
                details_sha256="6" * 64,
                effect_id="full.intake.preflight.v1.effect",
                receipt_sha256=receipt["receipt_sha256"],
                manager_secret=journal_secret,
            )
        )
        return current, self._invocation_json(invocation)

    def _claimed_quarantine_fixture(
        self,
        started: dict,
        authorized: dict,
        secret: bytearray,
        *,
        execution_id: str,
    ) -> dict:
        task_id = started["task_id"]
        task_dir = self.data / "tasks" / task_id
        state = dev_flow.load_state(task_id, self.data)
        workflow_id = str(state["workflow_ref"]["id"])
        effect_id = f"{workflow_id}.intake.preflight.v1.effect"
        outcome = dev_flow.ActionOutcome(
            f"{workflow_id}.intake.preflight.v1",
            f"{workflow_id}.action.intake.preflight.v1",
            evidence_records=(
                {"validator": "cli-boundary-recovery/v1"},
            ),
            proposed_state_delta={
                "set": {
                    "/preflight": {"status": "ready"},
                    "/repositories": state["repositories"],
                    "/risk_assessment": {"level": "low"},
                },
                "remove": [],
                "operations": [],
            },
            audit_facts=(
                dev_flow.AuditFact(
                    "cli-boundary-recovery",
                    {"validator": "cli-boundary-recovery/v1"},
                ),
            ),
        )
        parameters = {"mode": "initial"}
        evidence = {"validator": "cli-boundary-recovery/v1"}
        with dev_flow._task_lock(task_dir):
            preview = dev_flow.evaluate_v3_node_action(
                state,
                public_command="preflight",
                selector="initial",
                action_outcome=outcome,
                action_parameters=parameters,
                evidence=evidence,
                preview=True,
            )
        invocation = dev_flow.WorkflowActionInvocation(
            kind="node",
            public_command="preflight",
            selector="initial",
            action_outcome=outcome,
            action_parameters=parameters,
            evidence=evidence,
            confirm_intent=preview.intent["intent_id"],
        )
        roles = dev_flow._workflow_tx_edge_roles(
            state, invocation
        )
        journal_secret = self._journal_secret(
            task_id, authorized["capability"], secret
        )
        capability_sha256 = hashlib.sha256(
            dev_flow.semantic_json_bytes(authorized["capability"])
        ).hexdigest()
        authorization = dev_flow.WorkflowActionAuthorization(
            kind="manager",
            authorization_sha256="7" * 64,
            capability_sha256=capability_sha256,
            request_nonce_sha256="8" * 64,
            principal="manager:cli-recovery-manager",
            ownership_sha256="9" * 64,
            registry_state_sha256="a" * 64,
            reauthenticate=lambda: journal_secret,
            nonce_consumed_verifier=(
                lambda _state, _events: True
            ),
        )
        repository = state["repositories"][0]
        core = _journal_core(
            task_id=task_id,
            execution_id=execution_id,
            effects=[
                _effect(
                    effect_id,
                    repository_id=str(repository["id"]),
                    path=str(repository["path"]),
                )
            ],
        )
        handler = roles.completion_edge["handler"]
        core["bindings"].update(
            {
                "task_revision": state["revision"],
                "pre_effect_state_sha256": (
                    dev_flow._sha256_contract(state)
                ),
                "workflow_id": state["workflow_ref"]["id"],
                "workflow_version": str(
                    state["workflow_ref"]["version"]
                ),
                "workflow_bundle_sha256": state[
                    "workflow_ref"
                ]["bundle_sha256"],
                "authorization_action_edge_id": (
                    roles.authorization_action_edge_id
                ),
                "completion_edge_id": roles.completion_edge_id,
                "action_edge_id": roles.completion_edge_id,
                "handler_id": handler["id"],
                "authorization_sha256": (
                    authorization.authorization_sha256
                ),
                "capability_sha256": capability_sha256,
                "request_nonce_sha256": (
                    authorization.request_nonce_sha256
                ),
                "principal": authorization.principal,
                "ownership_sha256": (
                    authorization.ownership_sha256
                ),
                "registry_state_sha256": (
                    authorization.registry_state_sha256
                ),
            }
        )
        sealed = dev_flow.seal_journal(
            core, manager_secret=journal_secret
        )
        store = dev_flow.ActionExecutionStore(task_dir)
        index = store.initialize_index(task_id).index
        persisted = store.persist_initial(
            sealed,
            expected_index=dev_flow.cas_token(index),
            manager_secret=journal_secret,
        )
        assert persisted.record is not None
        store.claim_for_dispatch(
            execution_id,
            effect_id,
            f"{execution_id}-claim",
            expected_index=dev_flow.cas_token(persisted.index),
            expected_journal=dev_flow.cas_token(persisted.record),
            manager_secret=journal_secret,
        )
        index = store.read_index(expected_task_id=task_id)
        current = store.read_active_journal(
            execution_id, manager_secret=journal_secret
        )
        containment = dev_flow.new_containment(
            current,
            effect_id,
            index=index,
            expected_index=dev_flow.cas_token(index),
            manager_secret=journal_secret,
        )
        stored = store.persist_containment(
            containment,
            expected_index=dev_flow.cas_token(index),
            expected_journal=dev_flow.cas_token(current),
            manager_secret=journal_secret,
        )
        assert stored.record is not None
        recovered = dev_flow.recover_v3_workflow_action_transaction(
            task_dir,
            execution_id,
            authorization=authorization,
        )
        self.assertEqual(recovered.status, "QUARANTINE_REQUIRED")
        self.assertEqual(recovered.dispatcher_invocations, 0)
        assert recovered.journal is not None
        self.assertEqual(
            recovered.journal["effects"][0]["phase"],
            "QUARANTINED",
        )
        closed = store.read_containment(
            execution_id, effect_id
        )
        self.assertEqual(closed["phase"], "CLOSED")
        return recovered.journal

    def _exercise_claimed_restart_reconciliation(
        self,
        outcome: str,
        *,
        workflow_id: str = "full",
    ) -> None:
        self.assertIn(outcome, {"ABANDONED", "COMPENSATED"})
        started, _repository = self._start(
            workflow_id=workflow_id
        )
        authorized, secret = self._authorize(started)
        capability = authorized["capability"]
        authorized_revision = authorized["revision"]
        show_code, shown = self._run_cli(
            "show", started["task_id"], "--compact"
        )
        self.assertEqual(show_code, 0)
        self.assertEqual(shown["task_id"], started["task_id"])
        preview_code, preview = self._run_cli(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(authorized_revision),
            "--preview",
        )
        self.assertEqual(preview_code, 0)
        request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": capability["capability_id"],
            "task_id": started["task_id"],
            "manager_session_id": "cli-recovery-manager",
            "action_id": "task.preflight",
            "expected_revision": authorized_revision,
            "request_nonce": "a" * 64,
        }
        arguments = (
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(authorized_revision),
            "--confirm-preview",
            preview["transition_preview"]["token"],
        )
        process, publisher = self._manager_process(
            arguments, request=request, secret=secret
        )
        task_dir = self.data / "tasks" / started["task_id"]
        active_dir = task_dir / "action-executions" / "active"
        deadline = time.monotonic() + 20
        claimed_path = None
        claimed = None
        while time.monotonic() < deadline:
            active = sorted(active_dir.glob("*.json"))
            if active:
                try:
                    observed = json.loads(
                        active[0].read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    observed = None
                if (
                    isinstance(observed, dict)
                    and observed.get("phase")
                    in {"CLAIMED", "RUNNING"}
                ):
                    claimed_path = active[0]
                    claimed = observed
                    process.terminate()
                    break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                publisher.close()
                self.fail(
                    "isolated apply exited before a claimed journal "
                    f"could be interrupted: stdout={stdout!r}, "
                    f"stderr={stderr!r}"
                )
            time.sleep(0.001)
        else:
            process.kill()
            publisher.close()
            self.fail("timed out waiting for a claimed action journal")
        try:
            process.communicate(timeout=10)
        finally:
            publisher.close()
        assert claimed_path is not None
        assert isinstance(claimed, dict)
        effect = claimed["effects"][0]
        claim_id = effect["claim_id"]
        attempt_id = effect["attempt_id"]
        state_before = (task_dir / "state.json").read_bytes()
        events_before = (task_dir / "events.jsonl").read_bytes()

        recovery_code, recovery = self._manager_cli(
            arguments, request=request, secret=secret
        )
        self.assertEqual(recovery_code, 2)
        self.assertEqual(
            recovery["error"]["code"],
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_REQUIRED",
        )
        self.assertEqual(
            recovery["error"]["details"]["status"],
            "QUARANTINE_REQUIRED",
        )
        quarantined_bytes = claimed_path.read_bytes()
        quarantined = json.loads(
            quarantined_bytes.decode("utf-8")
        )
        self.assertEqual(quarantined["phase"], "QUARANTINED")
        self.assertEqual(
            quarantined["effects"][0]["claim_id"], claim_id
        )
        self.assertEqual(
            quarantined["effects"][0]["attempt_id"], attempt_id
        )
        self.assertEqual(
            (
                quarantined["bindings"]["authorization_action_edge_id"],
                quarantined["bindings"]["completion_edge_id"],
                quarantined["bindings"]["action_edge_id"],
                quarantined["effects"][0]["effect_id"],
            ),
            (
                f"{workflow_id}.action.intake.preflight.v1",
                f"{workflow_id}.intake.preflighted",
                f"{workflow_id}.intake.preflighted",
                f"{workflow_id}.intake.preflight.v1.effect",
            ),
        )
        self.assertEqual(
            recovery["error"]["details"]["dispatcher_invocations"],
            0,
        )
        index_path = task_dir / "action-executions" / "index.json"
        quarantined_index_bytes = index_path.read_bytes()
        quarantined_index = json.loads(
            quarantined_index_bytes.decode("utf-8")
        )
        indexed = [
            entry
            for entry in quarantined_index["entries"]
            if entry["execution_id"] == quarantined["execution_id"]
        ]
        self.assertEqual(len(indexed), 1)
        self.assertEqual(
            indexed[0]["record_sha256"],
            quarantined["record_sha256"],
        )

        repeated_code, repeated = self._manager_cli(
            arguments, request=request, secret=secret
        )
        self.assertEqual(repeated_code, 2)
        self.assertEqual(
            repeated["error"]["details"]["status"],
            "QUARANTINE_REQUIRED",
        )
        self.assertEqual(
            repeated["error"]["details"]["dispatcher_invocations"],
            0,
        )
        self.assertEqual(claimed_path.read_bytes(), quarantined_bytes)
        self.assertEqual(index_path.read_bytes(), quarantined_index_bytes)
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), state_before
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), events_before
        )
        current = dev_flow.load_state(started["task_id"], self.data)
        used = current["orchestration"]["manager_capabilities"][
            capability["capability_id"]
        ]["used_request_nonce_sha256s"]
        self.assertEqual(used, [])

        inspect_code, inspected = self._run_cli(
            "action-recovery-inspect",
            started["task_id"],
            "--execution-id",
            quarantined["execution_id"],
        )
        self.assertEqual(inspect_code, 0)
        self.assertEqual(inspected["phase"], "QUARANTINED")
        self.assertEqual(inspected["authenticated"], False)
        self.assertEqual(inspected["authority"], "discovery-only")

        reconciliation_attempt_id = (
            "cli-action-recovery-"
            + outcome.lower()
            + "-attempt"
        )
        compensation_target = None
        if outcome == "COMPENSATED":
            compensation_target = (
                task_dir
                / "compensation-targets"
                / "preflight-claim.bin"
            )
            compensation_target.parent.mkdir()
            compensation_payload = (
                b"controller-owned-recovery-target"
            )
            compensation_target.write_bytes(
                compensation_payload
            )
            compensation_plan_value = (
                dev_flow.WorkflowActionCompensationPlan(
                    action_id=(
                        "recovery.compensate."
                        "controller-file-remove/v1"
                    ),
                    effect_id=quarantined["effects"][0][
                        "effect_id"
                    ],
                    safe_inputs={
                        "task_relative_path": (
                            "compensation-targets/"
                            "preflight-claim.bin"
                        ),
                        "expected_sha256": hashlib.sha256(
                            compensation_payload
                        ).hexdigest(),
                    },
                    postcondition_contract_sha256=(
                        dev_flow
                        .action_recovery_controller_file_contract_sha256()
                    ),
                )
            )
            compensation_plan = (
                compensation_plan_value.as_dict()
            )
            evidence = {
                "schema": (
                    "dev-flow-v3-action-reconciliation-"
                    "evidence/v1"
                ),
                "outcome": outcome,
                "compensation_execution_id": (
                    "cli-action-recovery-"
                    "compensation-execution"
                ),
                "compensation_plan": compensation_plan,
            }
        else:
            evidence = {
                "schema": (
                    "dev-flow-v3-action-reconciliation-"
                    "evidence/v1"
                ),
                "outcome": outcome,
            }
        evidence_json = json.dumps(
            evidence, sort_keys=True, separators=(",", ":")
        )
        recovery_preview_code, recovery_preview = self._run_cli(
            "action-recovery-preview",
            started["task_id"],
            "--execution-id",
            quarantined["execution_id"],
            "--attempt-id",
            reconciliation_attempt_id,
            "--outcome",
            outcome,
            "--expected-revision",
            str(authorized_revision),
            "--evidence-json",
            evidence_json,
        )
        self.assertEqual(recovery_preview_code, 0)
        self.assertEqual(
            recovery_preview["target_dispatcher_invocations"], 0
        )
        reconcile_request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": capability["capability_id"],
            "task_id": started["task_id"],
            "manager_session_id": "cli-recovery-manager",
            "action_id": "control.reconcile/v1",
            "expected_revision": authorized_revision,
            "request_nonce": "d" * 64,
        }
        recovery_arguments = (
            "action-recovery-apply",
            started["task_id"],
            "--execution-id",
            quarantined["execution_id"],
            "--attempt-id",
            reconciliation_attempt_id,
            "--outcome",
            outcome,
            "--expected-revision",
            str(authorized_revision),
            "--confirm-preview",
            recovery_preview["confirm_preview"],
            "--evidence-json",
            evidence_json,
        )
        terminal_code, terminal = self._manager_cli(
            recovery_arguments,
            request=reconcile_request,
            secret=secret,
        )
        self.assertEqual(terminal_code, 0, terminal)
        effect_ids = [
            str(effect["effect_id"])
            for effect in quarantined["effects"]
        ]
        self._assert_operator_intervention_response(
            terminal,
            task_id=started["task_id"],
            execution_id=quarantined["execution_id"],
            attempt_id=reconciliation_attempt_id,
            effect_ids=effect_ids,
            affected_scopes=quarantined["bindings"]["scopes"],
        )
        self.assertEqual(
            terminal["revision"], authorized_revision
        )
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), state_before
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), events_before
        )
        blocked_index = json.loads(index_path.read_text("utf-8"))
        self.assertEqual(
            {
                entry["execution_id"]
                for entry in blocked_index["entries"]
            },
            {
                quarantined["execution_id"],
                reconciliation_attempt_id,
            },
        )
        if compensation_target is not None:
            self.assertTrue(compensation_target.exists())
        stable_paths = [
            task_dir / "state.json",
            task_dir / "events.jsonl",
            task_dir / "action-executions" / "index.json",
            task_dir
            / dev_flow.action_reconciliation_attempt_path(
                reconciliation_attempt_id
            ),
            task_dir
            / "action-executions"
            / "active"
            / f"{quarantined['execution_id']}.json",
        ]
        stable_bytes = {
            path: path.read_bytes() for path in stable_paths
        }
        repeated_terminal_code, repeated_terminal = (
            self._manager_cli(
                recovery_arguments,
                request=reconcile_request,
                secret=secret,
            )
        )
        self.assertEqual(repeated_terminal_code, 0, repeated_terminal)
        self.assertEqual(repeated_terminal, terminal)
        self.assertEqual(
            {path: path.read_bytes() for path in stable_paths},
            stable_bytes,
        )

    def test_full_abandonment_requires_operator_intervention(
        self,
    ) -> None:
        self._exercise_claimed_restart_reconciliation("ABANDONED")

    def test_full_compensation_requires_operator_intervention(
        self,
    ) -> None:
        self._exercise_claimed_restart_reconciliation("COMPENSATED")

    def test_lite_abandonment_requires_operator_intervention(
        self,
    ) -> None:
        self._exercise_claimed_restart_reconciliation(
            "ABANDONED", workflow_id="lite"
        )

    def test_lite_compensation_requires_operator_intervention(
        self,
    ) -> None:
        self._exercise_claimed_restart_reconciliation(
            "COMPENSATED", workflow_id="lite"
        )

    def test_receipt_verified_restart_accepts_once_and_never_redispatches(
        self,
    ) -> None:
        started, _repository = self._start()
        authorized, secret = self._authorize(started)
        capability = authorized["capability"]
        quarantined, invocation = (
            self._accepted_quarantine_fixture(
                started, authorized, secret
            )
        )
        task_id = started["task_id"]
        task_dir = self.data / "tasks" / task_id
        execution_id = quarantined["execution_id"]
        attempt_id = "cli-action-recovery-accepted-attempt"
        inspect_code, inspected = self._run_cli(
            "action-recovery-inspect",
            task_id,
            "--execution-id",
            execution_id,
        )
        self.assertEqual(inspect_code, 0, inspected)
        self.assertEqual(inspected["phase"], "QUARANTINED")
        self.assertEqual(inspected["authenticated"], False)
        self.assertEqual(inspected["authority"], "discovery-only")
        evidence = {
            "schema": (
                "dev-flow-v3-action-reconciliation-evidence/v1"
            ),
            "outcome": "ACCEPTED",
            "postcondition_evidence_sha256": "b" * 64,
            "invocation": invocation,
        }
        evidence_json = json.dumps(
            evidence, sort_keys=True, separators=(",", ":")
        )
        preview_code, preview = self._run_cli(
            "action-recovery-preview",
            task_id,
            "--execution-id",
            execution_id,
            "--attempt-id",
            attempt_id,
            "--outcome",
            "ACCEPTED",
            "--expected-revision",
            str(authorized["revision"]),
            "--evidence-json",
            evidence_json,
        )
        self.assertEqual(preview_code, 0, preview)
        self.assertEqual(
            preview["target_dispatcher_invocations"], 0
        )
        request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": capability["capability_id"],
            "task_id": task_id,
            "manager_session_id": "cli-recovery-manager",
            "action_id": "control.reconcile/v1",
            "expected_revision": authorized["revision"],
            "request_nonce": "c" * 64,
        }
        arguments = (
            "action-recovery-apply",
            task_id,
            "--execution-id",
            execution_id,
            "--attempt-id",
            attempt_id,
            "--outcome",
            "ACCEPTED",
            "--expected-revision",
            str(authorized["revision"]),
            "--confirm-preview",
            preview["confirm_preview"],
            "--evidence-json",
            evidence_json,
        )
        terminal_code, terminal = self._manager_cli(
            arguments, request=request, secret=secret
        )
        self.assertEqual(terminal_code, 0, terminal)
        self._assert_terminal_reconciliation_response(
            terminal,
            task_id=task_id,
            execution_id=execution_id,
            attempt_id=attempt_id,
            outcome="ACCEPTED",
        )
        terminal_state = dev_flow.load_state(task_id, self.data)
        self.assertEqual(
            terminal_state["revision"], terminal["revision"]
        )
        self.assertEqual(
            terminal_state["preflight"]["status"], "ready"
        )
        self.assertIsNone(terminal_state.get("pending_event"))
        self.assertFalse(terminal_state.get("pending_events", []))
        stable_paths = [
            task_dir / "state.json",
            task_dir / "events.jsonl",
            task_dir / "action-executions" / "index.json",
            task_dir
            / dev_flow.action_reconciliation_archive_path(
                attempt_id
            ),
            task_dir
            / "action-executions"
            / "archive"
            / f"{execution_id}.json",
        ]
        stable_bytes = {
            path: path.read_bytes() for path in stable_paths
        }
        repeated_code, repeated = self._manager_cli(
            arguments, request=request, secret=secret
        )
        self.assertEqual(repeated_code, 0, repeated)
        self.assertEqual(repeated, terminal)
        self.assertEqual(
            {path: path.read_bytes() for path in stable_paths},
            stable_bytes,
        )
        revoke_preview_code, revoke_preview = self._run_cli(
            "manager-revoke",
            task_id,
            "--expected-revision",
            str(terminal["revision"]),
            "--capability-id",
            capability["capability_id"],
            "--reason",
            "cli-action-recovery-complete",
            "--preview",
        )
        self.assertEqual(revoke_preview_code, 0, revoke_preview)
        revoke_code, revoked = self._run_cli(
            "manager-revoke",
            task_id,
            "--expected-revision",
            str(terminal["revision"]),
            "--capability-id",
            capability["capability_id"],
            "--reason",
            "cli-action-recovery-complete",
            "--confirm-intent",
            revoke_preview["preview"]["intent_id"],
        )
        self.assertEqual(revoke_code, 0, revoked)
        self.assertEqual(
            revoked["revision"], terminal["revision"] + 1
        )
