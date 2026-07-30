from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts/dev_flow.py"


def load_controller() -> dict[str, object]:
    return runpy.run_path(str(CONTROLLER), run_name="v4_focused_test")


def runtime_services():
    return load_controller()["_WORKFLOW_RUNTIME_SERVICES"]


class V4TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="dev-flow-v4-")
        self.temp = Path(self._temporary.name)
        self.data_dir = self.temp / "data"
        self.repo = self.temp / "repo 空格"
        self.repo.mkdir()
        self.git_config_global = self.temp / "empty-global.gitconfig"
        self.git_config_system = self.temp / "empty-system.gitconfig"
        self.git_config_global.write_text("", encoding="utf-8")
        self.git_config_system.write_text("", encoding="utf-8")
        self.environment = os.environ.copy()
        for key in list(self.environment):
            if key.startswith("GIT_") or key in {
                "SSH_ASKPASS",
                "SSH_ASKPASS_REQUIRE",
            }:
                self.environment.pop(key, None)
        self.environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(self.git_config_global),
                "GIT_CONFIG_SYSTEM": str(self.git_config_system),
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "/usr/bin/false",
                "PYTHONPYCACHEPREFIX": str(self.temp / "pycache"),
            }
        )
        self._git("init", "-b", "feature")
        self._git("config", "user.email", "v4@example.invalid")
        self._git("config", "user.name", "V4 Test")
        (self.repo / "README.md").write_text("V4\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-m", "initial")

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment,
        )

    def controller_process(
        self, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--data-dir",
                str(self.data_dir),
            ],
            cwd=ROOT,
            env=self.environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _controller_with_inherited_fd(
        self, args: list[str], inherited_fd: int
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--data-dir",
                str(self.data_dir),
            ],
            cwd=ROOT,
            env=self.environment,
            pass_fds=(inherited_fd,),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def authorize_manager(
        self, task_id: str, expected_revision: int
    ) -> tuple[dict[str, object], bytes]:
        preview = self.controller(
            "manager-authorize",
            task_id,
            "--expected-revision",
            str(expected_revision),
            "--manager-session-id",
            "focused-manager",
            "--ttl-seconds",
            "900",
            "--preview",
        )
        read_fd, write_fd = os.pipe()
        try:
            completed = self._controller_with_inherited_fd(
                [
                    "manager-authorize",
                    task_id,
                    "--expected-revision",
                    str(expected_revision),
                    "--manager-session-id",
                    "focused-manager",
                    "--ttl-seconds",
                    "900",
                    "--confirm-intent",
                    preview["preview"]["intent_id"],
                    "--manager-secret-fd",
                    str(write_fd),
                ],
                write_fd,
            )
        finally:
            os.close(write_fd)
        try:
            frame = b""
            while True:
                chunk = os.read(read_fd, 4096)
                if not chunk:
                    break
                frame += chunk
        finally:
            os.close(read_fd)
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result.get("ok"), result)
        self.assertGreaterEqual(len(frame), 4)
        (length,) = struct.unpack(">I", frame[:4])
        self.assertEqual(len(frame), length + 4)
        return result, frame[4:]

    def manager_controller_process(
        self,
        request: dict[str, object],
        secret: bytes,
        *args: str,
    ) -> subprocess.CompletedProcess[str]:
        read_fd, write_fd = os.pipe()
        frame = struct.pack(">I", len(secret)) + secret
        try:
            os.write(write_fd, frame)
        finally:
            os.close(write_fd)
        try:
            return self._controller_with_inherited_fd(
                [
                    *args,
                    "--manager-request-json",
                    json.dumps(
                        request,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "--manager-secret-fd",
                    str(read_fd),
                ],
                read_fd,
            )
        finally:
            os.close(read_fd)

    def controller(self, *args: str) -> dict[str, object]:
        completed = self.controller_process(*args)
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result.get("ok"), result)
        return result

    def start(self, task_id: str, strategy: str) -> dict[str, object]:
        args = [
            "start",
            "focused V4 task",
            "--repo",
            str(self.repo),
            "--task-id",
            task_id,
            "--workspace-strategy",
            strategy,
            "--change-category",
            "docs",
        ]
        if strategy != "worktree":
            args.extend(["--target-path", "README.md"])
        return self.controller(*args)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class V4OrchestrationTestCase(V4TestCase):
    """Focused real-controller fixture for the current multi-repository path."""

    orchestration_task_id = "focused-orchestration-v4"
    manager_session_id = "focused-orchestration-manager"

    def setUp(self) -> None:
        super().setUp()
        self.namespace = load_controller()
        bundle = self.namespace["_WORKFLOW_RUNTIME_SERVICES"].catalog.bundles[
            ("full", 4)
        ]
        creation_fields = json.loads(
            json.dumps(
                self.namespace["build_v4_task_creation_fields"](
                    self.orchestration_task_id,
                    bundle,
                    execution_profile="multi-repository",
                )
            )
        )
        self.orchestration_task_dir = (
            self.data_dir / "tasks" / self.orchestration_task_id
        )
        self.namespace["_ensure_private_dir"](self.orchestration_task_dir)
        self.namespace["_atomic_write_json"](
            self.orchestration_task_dir / "state.json",
            {
                "schema_version": 4,
                "task_id": self.orchestration_task_id,
                "revision": 0,
                "status": "INTAKE",
                "flow": "full",
                "repositories": [],
                "route": None,
                **creation_fields,
            },
        )
        self.secrets: dict[str, bytearray] = {}
        self.random_counter = 0
        self.wall_ns = 1_000_000_000_000
        self.monotonic_ns = 1_000_000_000
        self.protected_identity = digest("controller-data-directory")
        self.service = self.namespace["OrchestrationControllerService"](
            secret_resolver=lambda capability_id: bytearray(
                self.secrets[capability_id]
            ),
            secret_publisher=lambda capability_id, secret: (
                self.secrets.__setitem__(
                    capability_id, bytearray(secret)
                )
            ),
            random_bytes=self._random_bytes,
            wall_time_ns=lambda: self.wall_ns,
            monotonic_ns=lambda: self.monotonic_ns,
            clock_id="focused-orchestration-clock",
            runtime_stop_observer=self._trusted_stop_observer,
            runtime_stop_authenticator=lambda _lease, _observation: True,
            integration_verifier=self._trusted_integration_verifier,
            host_capability_observer=self._trusted_host_observer,
            trusted_host_adapter_ids=("focused-host-adapter",),
            protected_read_identity_sha256s=(self.protected_identity,),
        )
        receipt = self.service.authorize_manager(
            self.orchestration_task_id,
            expected_revision=0,
            manager_session_id=self.manager_session_id,
            ttl_ns=100_000_000_000,
            operator_confirmed=True,
            operator_confirmation_sha256=digest("operator-confirmation"),
            issuance_audit_sha256=digest("issuance-audit"),
            data_dir=self.data_dir,
        )
        self.capability_id = str(receipt.payload["capability_id"])
        self.nonce_counter = 0

    def _random_bytes(self, size: int) -> bytearray:
        self.random_counter += 1
        seed = hashlib.sha256(
            f"random-{self.random_counter}".encode("utf-8")
        ).digest()
        return bytearray(
            (seed * ((size + len(seed) - 1) // len(seed)))[:size]
        )

    def orchestration_state(self) -> dict[str, object]:
        return json.loads(
            (self.orchestration_task_dir / "state.json").read_text(
                encoding="utf-8"
            )
        )

    def orchestration_principal(self) -> dict[str, object]:
        return {
            "schema": self.namespace["AGENT_PRINCIPAL_SCHEMA"],
            "role": "manager",
            "session_id": self.manager_session_id,
            "os_user_identity_sha256": digest("os-user"),
            "host_identity_sha256": digest("host"),
        }

    def orchestration_request(
        self,
        action_id: str,
        *,
        expected_revision: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, object]:
        self.nonce_counter += 1
        return {
            "schema": self.namespace["MANAGER_CAPABILITY_REQUEST_SCHEMA"],
            "capability_id": self.capability_id,
            "task_id": self.orchestration_task_id,
            "manager_session_id": self.manager_session_id,
            "action_id": action_id,
            "expected_revision": (
                int(self.orchestration_state()["revision"])
                if expected_revision is None
                else expected_revision
            ),
            "request_nonce": nonce
            or digest(f"request-nonce-{self.nonce_counter}"),
        }

    def _trusted_host_observer(
        self, assignment: dict[str, object]
    ) -> dict[str, object]:
        return {
            "schema": self.namespace["HOST_CAPABILITY_REPORT_SCHEMA"],
            "adapter_id": "focused-host-adapter",
            "assignment_id": assignment["assignment_id"],
            "worker_session_id": "focused-worker-session",
            "worker_identity_sha256": digest("focused-worker"),
            "attestation_sha256": digest("focused-host-attestation"),
            "host_enforced": True,
            "allowed_write_identity_sha256s": [
                assignment["worktree_identity_sha256"]
            ],
            "denied_read_identity_sha256s": [
                self.protected_identity
            ],
            "denied_tool_ids": sorted(
                self.namespace["_osc_mutating_tool_ids"]
            ),
            "all_other_writes_denied": True,
            "manager_secret_channel_excluded": True,
            "controller_state_excluded": True,
            "mutation_tools_excluded": True,
        }

    def _trusted_stop_observer(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        return {
            "schema": self.namespace["RUNTIME_STOP_OBSERVATION_SCHEMA"],
            "task_id": projection["task_id"],
            "node_instance_id": projection["node_instance_id"],
            "attempt": projection["attempt"],
            "assignment_id": projection["assignment_id"],
            "lease_id": projection["lease_id"],
            "runtime_handle_id": projection["runtime_handle_id"],
            "host_assignment_id": projection["host_assignment_id"],
            "authentication_sha256": projection[
                "runtime_authentication_sha256"
            ],
            "stopped": True,
        }

    def _trusted_integration_verifier(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        observation = {
            "schema": self.namespace[
                "ORCHESTRATION_TRUSTED_INTEGRATION_OBSERVATION_SCHEMA"
            ],
            "snapshot_id": projection["snapshot_id"],
            "snapshot_sha256": projection["snapshot_sha256"],
            "outcome": "SUCCEEDED",
            "evidence_sha256": digest("focused-integration-evidence"),
            "verifier_id": "focused-integration-verifier",
        }
        return {
            **observation,
            "attestation_sha256": self.namespace["_osc_digest"](
                observation
            ),
        }

    def record_and_expand_plan(self) -> dict[str, object]:
        contract_content = b'{"schema":"contract.integration/v1"}\n'
        contract_sha256 = hashlib.sha256(contract_content).hexdigest()
        self.service.record_artifact(
            self.orchestration_task_id,
            artifact_id="focused-integration-contract",
            content=contract_content,
            kind="application/vnd.dev-flow.contract+json",
            semantic_sha256=contract_sha256,
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_ACTION_ARTIFACT_RECORD"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        plan_value = {
            "schema": self.namespace["REPOSITORY_PLAN_SCHEMA"],
            "task_id": self.orchestration_task_id,
            "workflow_bundle_sha256": self.orchestration_state()[
                "workflow_ref"
            ]["bundle_sha256"],
            "plan_id": "focused-plan-v4",
            "map_node_id": "map.repositories/v1",
            "map_epoch": 1,
            "plan_input_revision": self.orchestration_state()["revision"],
            "semantic_input_sha256": "0" * 64,
            "repository_set": ["api"],
            "repositories": [
                {
                    "repository_id": "api",
                    "identity_sha256": digest("repository-api"),
                    "repository_path": "repositories/api",
                    "approved_paths": ["src", "tests"],
                    "write_policy": "scoped-write",
                    "required_approval_ids": [],
                    "required_evidence_contract_sha256": [
                        contract_sha256
                    ],
                }
            ],
            "interface_contracts": [
                {
                    "contract_id": "contract.integration/v1",
                    "artifact_id": "focused-integration-contract",
                    "sha256": contract_sha256,
                }
            ],
            "dependencies": [],
            "worktree_policy": {
                "mode": "controller-owned",
                "require_clean": True,
                "distinct": True,
            },
            "concurrency_policy": {
                "max_workers": 1,
                "max_writable_workers": 1,
            },
            "retry_policy": {
                "max_attempts": 2,
                "retryable_states": ["BLOCKED", "FAILED"],
                "requires_approval": True,
            },
            "integration_policy": {
                "commands": [["python3", "-m", "unittest"]],
                "evidence_contract_sha256": [contract_sha256],
            },
        }
        bound = self.namespace["bind_repository_plan_semantic_input"](
            plan_value
        )
        plan = json.loads(
            self.namespace["canonical_repository_plan_bytes"](bound)
        )
        self.service.record_plan(
            self.orchestration_task_id,
            plan,
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_ACTION_PLAN_RECORD"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        self.service.approve_plan(
            self.orchestration_task_id,
            approval_intent="approve-repository-map/v1",
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_ACTION_PLAN_APPROVE"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        self.service.expand_plan(
            self.orchestration_task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_OPERATION_MAP_EXPAND"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        self.service.advance_ready_frontier(
            self.orchestration_task_id,
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_OPERATION_FRONTIER_ADVANCE"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        return plan

    def start_orchestration_assignment(
        self,
    ) -> tuple[dict[str, object], dict[str, object]]:
        plan = self.record_and_expand_plan()
        child = self.orchestration_state()["orchestration"]["expansion"][
            "children"
        ][0]
        allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        input_sha256 = digest("focused-assignment-input")
        lease = self.service.issue_lease(
            self.orchestration_task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(self.repo.resolve()),
            input_evidence_sha256=input_sha256,
            allowed_actions=allowed_actions,
            lease_ttl_ns=10_000_000_000,
            request=self.orchestration_request(
                self.namespace["ORCHESTRATION_OPERATION_LEASE_ISSUE"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        issued = self.service.issue_assignment(
            self.orchestration_task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(self.repo.resolve()),
            input_evidence_sha256=input_sha256,
            allowed_actions=allowed_actions,
            playbook_locator="playbooks/workflow.md",
            playbook_sha256=digest("playbook"),
            required_evidence_contract_sha256s=plan["repositories"][0][
                "required_evidence_contract_sha256"
            ],
            runtime_handle_id="runtime-api",
            host_assignment_id="host-assignment-api",
            runtime_authentication_sha256=digest("runtime-auth"),
            actor_id="worker-api",
            lease_ttl_ns=10_000_000_000,
            lease_id=str(lease.payload["lease_id"]),
            request=self.orchestration_request(
                self.namespace[
                    "ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE"
                ]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        self.service.handoff_dispatch(
            self.orchestration_task_id,
            assignment_id=str(issued.payload["assignment_id"]),
            runtime_handle_id="runtime-api",
            host_assignment_id="host-assignment-api",
            runtime_authentication_sha256=digest("runtime-auth"),
            actor_id="worker-api",
            request=self.orchestration_request(
                self.namespace[
                    "ORCHESTRATION_OPERATION_DISPATCH_HANDOFF"
                ]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        assignment = self.orchestration_state()["orchestration"][
            "assignments"
        ][issued.payload["assignment_id"]]
        return plan, assignment

    def successful_orchestration_result(
        self, assignment: dict[str, object]
    ) -> dict[str, object]:
        state = self.orchestration_state()
        dispatch = state["orchestration"]["dispatch"][
            assignment["assignment_id"]
        ]
        worktree_sha256, _paths, changed_paths_sha256 = self.namespace[
            "_osc_worktree_observation"
        ](
            str(self.repo.resolve()),
            baseline_head=dispatch["worktree_baseline_head"],
        )
        output_observation = {
            "schema": self.namespace[
                "ORCHESTRATION_CONTROLLER_OUTPUT_OBSERVATION_SCHEMA"
            ],
            "task_id": self.orchestration_task_id,
            "assignment_id": assignment["assignment_id"],
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "worktree_sha256": worktree_sha256,
            "changed_paths_sha256": changed_paths_sha256,
            "artifacts": {},
            "evidence": {},
        }
        output_sha256 = hashlib.sha256(
            b"dev-flow-controller-output-observation-v1\x00"
            + self.namespace["_osc_canonical_bytes"](output_observation)
        ).hexdigest()
        verification_sha256 = hashlib.sha256(
            b"dev-flow-controller-verification-observation-v1\x00"
            + self.namespace["_osc_canonical_bytes"](
                {
                    "assignment_id": assignment["assignment_id"],
                    "outcome": "SUCCEEDED",
                    "evidence": {},
                }
            )
        ).hexdigest()
        lease = assignment["lease_credential"]
        candidate = {
            "schema": self.namespace[
                "ORCHESTRATION_NODE_RESULT_SCHEMA"
            ],
            "task_id": self.orchestration_task_id,
            "workflow_bundle_sha256": assignment[
                "workflow_bundle_sha256"
            ],
            "map_epoch": assignment["map_epoch"],
            "repository_id": assignment["repository_id"],
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "assignment_id": assignment["assignment_id"],
            "lease_id": lease["lease_id"],
            "lease_nonce": lease["lease_nonce"],
            "input_sha256": assignment["input_evidence_sha256"],
            "output_sha256": output_sha256,
            "worktree_sha256": worktree_sha256,
            "changed_paths_sha256": changed_paths_sha256,
            "verification_sha256": verification_sha256,
            "outcome": "SUCCEEDED",
            "summary": "focused controller-observed result",
            "blockers": [],
            "plan_drift": {"detected": False, "reasons": []},
            "artifact_refs": [],
            "evidence_refs": [],
            "runtime_handle": dispatch["runtime_handle_id"],
        }
        bound = self.namespace["bind_node_result_identity"](candidate)
        return json.loads(
            self.namespace["canonical_node_result_bytes"](bound)
        )
