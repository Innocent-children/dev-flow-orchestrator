from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


dev_flow = test_case.dev_flow
ROOT = Path(__file__).resolve().parents[1]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OrchestrationServiceTests(test_case.DevFlowTestCase):
    task_id = "orchestration-service-task"
    manager_session_id = "manager-session-test"

    def setUp(self) -> None:
        super().setUp()
        bundle = dev_flow._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
            ("full", 4)
        ]
        creation_fields = json.loads(
            json.dumps(
                dev_flow.build_v3_task_creation_fields(
                    self.task_id,
                    bundle,
                    execution_profile="multi-repository",
                )
            )
        )
        task_dir = self.data / "tasks" / self.task_id
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "task_id": self.task_id,
                    "revision": 0,
                    "status": "INTAKE",
                    "flow": "full",
                    **creation_fields,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.secrets: dict[str, bytearray] = {}
        self.random_counter = 0
        self.wall_ns = 1_000_000_000_000
        self.monotonic_ns = 1_000_000_000
        self.recovery_observation = (False, False, False)
        self.host_observations: list[dict[str, object]] = []
        self.protected_identity = digest("controller-data-directory")
        self.service = dev_flow.OrchestrationControllerService(
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
            clock_id="orchestration-test-clock",
            runtime_stop_observer=self._trusted_stop_observer,
            runtime_stop_authenticator=lambda _lease, _observation: True,
            runtime_isolation_observer=(
                self._trusted_isolation_observer
            ),
            runtime_recovery_observer=(
                self._trusted_recovery_observer
            ),
            integration_verifier=(
                self._trusted_integration_verifier
            ),
            independent_reviewer=(
                self._trusted_independent_reviewer
            ),
            host_capability_observer=self._trusted_host_observer,
            trusted_host_adapter_ids=("test-host-adapter",),
            protected_read_identity_sha256s=(
                self.protected_identity,
            ),
        )
        receipt = self.service.authorize_manager(
            self.task_id,
            expected_revision=0,
            manager_session_id=self.manager_session_id,
            ttl_ns=100_000_000_000,
            operator_confirmed=True,
            operator_confirmation_sha256=digest("operator-confirmation"),
            issuance_audit_sha256=digest("issuance-audit"),
            data_dir=self.data,
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

    def _trusted_host_observer(
        self, assignment: dict[str, object]
    ) -> dict[str, object]:
        self.host_observations.append(
            json.loads(json.dumps(assignment))
        )
        return {
            "schema": dev_flow.HOST_CAPABILITY_REPORT_SCHEMA,
            "adapter_id": "test-host-adapter",
            "assignment_id": assignment["assignment_id"],
            "worker_session_id": "test-worker-session",
            "worker_identity_sha256": digest("test-worker"),
            "attestation_sha256": digest("test-host-attestation"),
            "host_enforced": True,
            "allowed_write_identity_sha256s": [
                assignment["worktree_identity_sha256"]
            ],
            "denied_read_identity_sha256s": [
                self.protected_identity
            ],
            "denied_tool_ids": sorted(
                dev_flow._osc_mutating_tool_ids
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
            "schema": dev_flow.RUNTIME_STOP_OBSERVATION_SCHEMA,
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

    def _trusted_isolation_observer(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        return {
            "schema": (
                dev_flow.ORCHESTRATION_RUNTIME_ISOLATION_ATTESTATION_SCHEMA
            ),
            "lease_id": projection["lease_id"],
            "assignment_id": projection["assignment_id"],
            "termination_confirmed": True,
            "termination_evidence_sha256": digest(
                "termination-evidence"
            ),
            "operator_isolation_confirmed": False,
            "operator_isolation_evidence_sha256": None,
        }

    def _trusted_recovery_observer(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        found, authenticated, live = self.recovery_observation
        return {
            "schema": dev_flow.RUNTIME_RECOVERY_OBSERVATION_SCHEMA,
            "task_id": projection["task_id"],
            "node_instance_id": projection["node_instance_id"],
            "attempt": projection["attempt"],
            "assignment_id": projection["assignment_id"],
            "lease_id": projection["lease_id"],
            "runtime_handle_id": projection["runtime_handle_id"],
            "host_assignment_id": projection["host_assignment_id"],
            "found": found,
            "authenticated": authenticated,
            "live": live,
            "worktree_fingerprint_sha256": projection[
                "worktree_fingerprint_sha256"
            ],
        }

    def _trusted_integration_verifier(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        observation = {
            "schema": (
                dev_flow.ORCHESTRATION_TRUSTED_INTEGRATION_OBSERVATION_SCHEMA
            ),
            "snapshot_id": projection["snapshot_id"],
            "snapshot_sha256": projection["snapshot_sha256"],
            "outcome": "SUCCEEDED",
            "evidence_sha256": digest(
                "trusted-integration-evidence"
            ),
            "verifier_id": "trusted-integration-verifier",
        }
        return {
            **observation,
            "attestation_sha256": dev_flow._osc_digest(
                observation
            ),
        }

    def _trusted_independent_reviewer(
        self, projection: dict[str, object]
    ) -> dict[str, object]:
        observation = {
            "schema": (
                dev_flow.ORCHESTRATION_TRUSTED_REVIEW_OBSERVATION_SCHEMA
            ),
            "reviewer_id": "independent-reviewer",
            "integration_verification_id": projection[
                "integration_verification_id"
            ],
            "snapshot_id": projection["snapshot_id"],
            "reviewed_surface_sha256s": projection[
                "reviewed_surface_sha256s"
            ],
            "outcome": "SUCCEEDED",
            "evidence_sha256": digest(
                "trusted-independent-review-evidence"
            ),
        }
        return {
            **observation,
            "attestation_sha256": dev_flow._osc_digest(
                observation
            ),
        }

    @property
    def task_dir(self) -> Path:
        return self.data / "tasks" / self.task_id

    def state(self) -> dict[str, object]:
        return json.loads(
            (self.task_dir / "state.json").read_text(encoding="utf-8")
        )

    def event_lines(self) -> list[str]:
        path = self.task_dir / "events.jsonl"
        return (
            path.read_text(encoding="utf-8").splitlines()
            if path.exists()
            else []
        )

    def principal(self, *, role: str = "manager") -> dict[str, object]:
        return {
            "schema": dev_flow.AGENT_PRINCIPAL_SCHEMA,
            "role": role,
            "session_id": (
                self.manager_session_id
                if role == "manager"
                else "worker-session-test"
            ),
            "os_user_identity_sha256": digest("os-user"),
            "host_identity_sha256": digest("host"),
        }

    def request(
        self,
        action_id: str,
        *,
        nonce: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        self.nonce_counter += 1
        return {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "manager_session_id": self.manager_session_id,
            "action_id": action_id,
            "expected_revision": (
                int(self.state()["revision"])
                if expected_revision is None
                else expected_revision
            ),
            "request_nonce": nonce
            or digest(f"request-nonce-{self.nonce_counter}"),
        }

    def _record_plan(
        self,
        *,
        map_epoch: int = 1,
        repositories: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        contract_content = b'{"schema":"contract.integration/v1"}\n'
        contract_sha256 = hashlib.sha256(contract_content).hexdigest()
        if (
            "artifact-integration-contract"
            not in self.state().get("orchestration", {}).get(
                "artifacts", {}
            )
        ):
            self.service.record_artifact(
                self.task_id,
                artifact_id="artifact-integration-contract",
                content=contract_content,
                kind="application/vnd.dev-flow.contract+json",
                semantic_sha256=contract_sha256,
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        bundle_sha256 = self.state()["workflow_ref"]["bundle_sha256"]
        repository_values = repositories or [
            {
                "repository_id": "api",
                "identity_sha256": digest("repository-api"),
                "repository_path": "repositories/api",
            }
        ]
        normalized_repositories = [
            {
                "approved_paths": ["src", "tests"],
                "write_policy": "scoped-write",
                "required_approval_ids": [],
                "required_evidence_contract_sha256": [
                    contract_sha256
                ],
                **value,
            }
            for value in repository_values
        ]
        repository_set = sorted(
            (
                str(value["repository_id"])
                for value in normalized_repositories
            ),
            key=lambda value: value.encode("utf-8"),
        )
        plan_value = {
            "schema": dev_flow.REPOSITORY_PLAN_SCHEMA,
            "task_id": self.task_id,
            "workflow_bundle_sha256": bundle_sha256,
            "plan_id": (
                f"plan-orchestration-service-{map_epoch}"
            ),
            "map_node_id": "map.repositories/v1",
            "map_epoch": map_epoch,
            "plan_input_revision": self.state()["revision"],
            "semantic_input_sha256": "0" * 64,
            "repository_set": repository_set,
            "repositories": normalized_repositories,
            "interface_contracts": [
                {
                    "contract_id": "contract.integration/v1",
                    "artifact_id": "artifact-integration-contract",
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
                "max_workers": len(normalized_repositories),
                "max_writable_workers": len(
                    normalized_repositories
                ),
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
        bound = dev_flow.bind_repository_plan_semantic_input(plan_value)
        plan = json.loads(
            dev_flow.canonical_repository_plan_bytes(bound)
        )
        self.service.record_plan(
            self.task_id,
            plan,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_PLAN_RECORD
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.approve_plan(
            self.task_id,
            approval_intent="approve-repository-map/v1",
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_PLAN_APPROVE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        return plan

    def _make_linked_worktree(
        self, name: str
    ) -> tuple[Path, Path]:
        source, _remote = self.make_repo(f"{name}-source")
        worktree = self.root / f"{name}-worktree"
        test_case.git(
            source,
            "worktree",
            "add",
            "-q",
            "-b",
            f"codex/{name}",
            str(worktree),
            "HEAD",
        )
        self.assertTrue((worktree / ".git").is_file())
        return source, worktree

    def _issue_repository_assignment(
        self,
        plan: dict[str, object],
        child: dict[str, object],
        worktree: Path,
    ) -> dict[str, object]:
        repository_id = str(child["repository_id"])
        repository = next(
            value
            for value in plan["repositories"]
            if value["repository_id"] == repository_id
        )
        allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        input_evidence_sha256 = digest(
            f"assignment-input-{repository_id}"
        )
        lease = self.service.issue_lease(
            self.task_id,
            node_instance_id=str(child["node_instance_id"]),
            worktree_path=str(worktree),
            input_evidence_sha256=input_evidence_sha256,
            allowed_actions=allowed_actions,
            lease_ttl_ns=10_000_000_000,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_LEASE_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        receipt = self.service.issue_assignment(
            self.task_id,
            node_instance_id=str(child["node_instance_id"]),
            worktree_path=str(worktree),
            input_evidence_sha256=input_evidence_sha256,
            allowed_actions=allowed_actions,
            playbook_locator="playbooks/workflow.md",
            playbook_sha256=digest("playbook"),
            required_evidence_contract_sha256s=repository[
                "required_evidence_contract_sha256"
            ],
            runtime_handle_id=f"runtime-{repository_id}",
            host_assignment_id=(
                f"host-assignment-{repository_id}"
            ),
            runtime_authentication_sha256=digest(
                f"runtime-auth-{repository_id}"
            ),
            actor_id=f"worker-actor-{repository_id}",
            lease_ttl_ns=10_000_000_000,
            lease_id=str(lease.payload["lease_id"]),
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.handoff_dispatch(
            self.task_id,
            assignment_id=str(receipt.payload["assignment_id"]),
            runtime_handle_id=f"runtime-{repository_id}",
            host_assignment_id=(
                f"host-assignment-{repository_id}"
            ),
            runtime_authentication_sha256=digest(
                f"runtime-auth-{repository_id}"
            ),
            actor_id=f"worker-actor-{repository_id}",
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_DISPATCH_HANDOFF
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        return self.state()["orchestration"]["assignments"][
            receipt.payload["assignment_id"]
        ]

    def _start_assignment(
        self,
        *,
        runtime_handle_id: str | None = "runtime-api",
        lease_ttl_ns: int = 10_000_000_000,
    ) -> tuple[dict[str, object], Path, dict[str, object]]:
        plan = self._record_plan()
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.advance_ready_frontier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        state = self.state()
        child = state["orchestration"]["expansion"]["children"][0]
        repo, _remote = self.make_repo("worker-api")
        allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        input_evidence_sha256 = digest("assignment-input")
        lease = self.service.issue_lease(
            self.task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(repo),
            input_evidence_sha256=input_evidence_sha256,
            allowed_actions=allowed_actions,
            lease_ttl_ns=lease_ttl_ns,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_LEASE_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        receipt = self.service.issue_assignment(
            self.task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(repo),
            input_evidence_sha256=input_evidence_sha256,
            allowed_actions=allowed_actions,
            playbook_locator="playbooks/workflow.md",
            playbook_sha256=digest("playbook"),
            required_evidence_contract_sha256s=plan[
                "repositories"
            ][0]["required_evidence_contract_sha256"],
            runtime_handle_id=runtime_handle_id,
            host_assignment_id="host-assignment-api",
            runtime_authentication_sha256=digest("runtime-auth"),
            actor_id="worker-actor-api",
            lease_ttl_ns=lease_ttl_ns,
            lease_id=str(lease.payload["lease_id"]),
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        if runtime_handle_id is not None:
            self.service.handoff_dispatch(
                self.task_id,
                assignment_id=str(
                    receipt.payload["assignment_id"]
                ),
                runtime_handle_id=runtime_handle_id,
                host_assignment_id="host-assignment-api",
                runtime_authentication_sha256=digest(
                    "runtime-auth"
                ),
                actor_id="worker-actor-api",
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_DISPATCH_HANDOFF
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        assignment = self.state()["orchestration"]["assignments"][
            receipt.payload["assignment_id"]
        ]
        return plan, repo, assignment

    def _successful_result(
        self,
        repo: Path,
        assignment: dict[str, object],
        *,
        outcome: str = "SUCCEEDED",
    ) -> dict[str, object]:
        state = self.state()
        dispatch = state["orchestration"]["dispatch"][
            assignment["assignment_id"]
        ]
        worktree_sha256, _paths, changed_paths_sha256 = (
            dev_flow._osc_worktree_observation(
                str(repo),
                baseline_head=dispatch["worktree_baseline_head"],
            )
        )
        output_observation = {
            "schema": (
                dev_flow.ORCHESTRATION_CONTROLLER_OUTPUT_OBSERVATION_SCHEMA
            ),
            "task_id": self.task_id,
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
            + dev_flow._osc_canonical_bytes(output_observation)
        ).hexdigest()
        verification_sha256 = hashlib.sha256(
            b"dev-flow-controller-verification-observation-v1\x00"
            + dev_flow._osc_canonical_bytes(
                {
                    "assignment_id": assignment["assignment_id"],
                    "outcome": outcome,
                    "evidence": {},
                }
            )
        ).hexdigest()
        lease = assignment["lease_credential"]
        candidate = {
            "schema": dev_flow.ORCHESTRATION_NODE_RESULT_SCHEMA,
            "task_id": self.task_id,
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
            "outcome": outcome,
            "summary": "controller-observed implementation",
            "blockers": [],
            "plan_drift": {"detected": False, "reasons": []},
            "artifact_refs": [],
            "evidence_refs": [],
            "runtime_handle": dispatch["runtime_handle_id"],
        }
        bound = dev_flow.bind_node_result_identity(candidate)
        return json.loads(dev_flow.canonical_node_result_bytes(bound))

    def _runtime_stop_observation(
        self, assignment: dict[str, object]
    ) -> dict[str, object]:
        dispatch = self.state()["orchestration"]["dispatch"][
            assignment["assignment_id"]
        ]
        lease = assignment["lease_credential"]
        return {
            "schema": dev_flow.RUNTIME_STOP_OBSERVATION_SCHEMA,
            "task_id": self.task_id,
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "assignment_id": assignment["assignment_id"],
            "lease_id": lease["lease_id"],
            "runtime_handle_id": dispatch["runtime_handle_id"],
            "host_assignment_id": dispatch["host_assignment_id"],
            "authentication_sha256": dispatch[
                "runtime_authentication_sha256"
            ],
            "stopped": True,
        }

    def _safe_worktree_snapshot(
        self,
        assignment: dict[str, object],
        *,
        worktree_fingerprint_sha256: str | None = None,
    ) -> dict[str, object]:
        return {
            "schema": dev_flow.WORKTREE_POSTCONDITION_SCHEMA,
            "repository_id": assignment["repository_id"],
            "repository_identity_sha256": assignment[
                "repository_identity_sha256"
            ],
            "worktree_fingerprint_sha256": (
                worktree_fingerprint_sha256
                or assignment["worktree_identity_sha256"]
            ),
            "repository_common_dir_sha256": digest("common-dir"),
            "ownership_claim_sha256": digest("ownership-claim"),
            "git_state_sha256": digest("git-state"),
            "changed_paths_sha256": digest("changed-paths"),
            "complete": True,
            "active_writer": False,
            "mutation_quarantine": False,
        }

    def _runtime_recovery_observation(
        self,
        assignment: dict[str, object],
        *,
        found: bool,
        authenticated: bool,
        live: bool,
    ) -> dict[str, object]:
        dispatch = self.state()["orchestration"]["dispatch"][
            assignment["assignment_id"]
        ]
        lease = assignment["lease_credential"]
        return {
            "schema": (
                dev_flow.RUNTIME_RECOVERY_OBSERVATION_SCHEMA
            ),
            "task_id": self.task_id,
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "assignment_id": assignment["assignment_id"],
            "lease_id": lease["lease_id"],
            "runtime_handle_id": dispatch["runtime_handle_id"],
            "host_assignment_id": dispatch["host_assignment_id"],
            "found": found,
            "authenticated": authenticated,
            "live": live,
            "worktree_fingerprint_sha256": assignment[
                "worktree_identity_sha256"
            ],
        }

    def _ready_integration_member(
        self,
    ) -> tuple[Path, dict[str, object], dict[str, object], str]:
        _plan, repo, assignment = self._start_assignment()
        result = self._successful_result(repo, assignment)
        self.service.accept_result(
            self.task_id,
            result,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        lease_id = str(
            assignment["lease_credential"]["lease_id"]
        )
        self.service.record_authenticated_stop(
            self.task_id,
            lease_id=lease_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_RUNTIME_STOP
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        barrier = self.service.evaluate_barrier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_BARRIER_CLOSE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(barrier.payload["status"], "CLOSED")
        return (
            repo,
            assignment,
            result,
            str(barrier.payload["barrier_id"]),
        )

    def _capture_and_verify_integration(
        self, barrier_id: str
    ) -> tuple[str, str]:
        snapshot = self.service.capture_integration_snapshot(
            self.task_id,
            barrier_id=barrier_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_INTEGRATION_CAPTURE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        snapshot_id = str(snapshot.payload["snapshot_id"])
        verification = (
            self.service.record_integration_verification(
                self.task_id,
                snapshot_id=snapshot_id,
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_INTEGRATION_VERIFY
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        )
        return (
            snapshot_id,
            str(verification.payload["verification_id"]),
        )

    def test_authorization_persists_only_verifier_and_nonce_replay_is_atomic(
        self,
    ) -> None:
        secret = self.secrets[self.capability_id]
        state_text = (self.task_dir / "state.json").read_text(
            encoding="utf-8"
        )
        events_text = (self.task_dir / "events.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(secret.hex(), state_text)
        self.assertNotIn(secret.hex(), events_text)
        verifier = self.state()["orchestration"][
            "manager_capabilities"
        ][self.capability_id]
        self.assertIn("verifier_hmac_sha256", verifier)
        self.assertNotIn("secret", verifier)

        nonce = digest("one-shot-nonce")
        self.service.record_artifact(
            self.task_id,
            artifact_id="nonce-artifact",
            content=b"nonce-artifact",
            kind="application/octet-stream",
            semantic_sha256=digest("nonce-artifact"),
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD,
                nonce=nonce,
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        reference = self.state()["orchestration"]["artifacts"][
            "nonce-artifact"
        ]
        self.assertEqual(
            reference["locator"],
            "artifacts/orchestration/"
            + digest("nonce-artifact")
            + ".json",
        )
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        replay = self.request(
            dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD,
            nonce=nonce,
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.record_artifact(
                self.task_id,
                artifact_id="must-not-exist",
                content=b"replayed",
                kind="application/octet-stream",
                semantic_sha256=digest("replayed"),
                request=replay,
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code, "MANAGER_CAPABILITY_REQUEST_REPLAYED"
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(), before_events
        )
    def test_manager_revocation_is_durable_and_blocks_new_mutation(
        self,
    ) -> None:
        receipt = self.service.revoke_manager(
            self.task_id,
            expected_revision=int(self.state()["revision"]),
            capability_id=self.capability_id,
            reason="operator-ended-session",
            revocation_audit_sha256=digest("revocation-audit"),
            operator_confirmed=True,
            data_dir=self.data,
        )
        self.assertEqual(
            receipt.event_type, "manager_capability_revoked"
        )
        verifier = self.state()["orchestration"][
            "manager_capabilities"
        ][self.capability_id]
        self.assertEqual(
            verifier["revocation_reason"], "operator-ended-session"
        )
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.record_artifact(
                self.task_id,
                artifact_id="revoked-artifact",
                content=b"revoked-artifact",
                kind="application/octet-stream",
                semantic_sha256=digest("revoked-artifact"),
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code, "MANAGER_CAPABILITY_REVOKED"
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(), before_events
        )

    def test_manager_secret_is_zeroized_on_all_consumer_paths(
        self,
    ) -> None:
        captured: list[bytearray] = []

        def correct_resolver(capability_id: str) -> bytearray:
            owned = bytearray(self.secrets[capability_id])
            captured.append(owned)
            return owned

        self.service._secret_resolver = correct_resolver
        content = b"zeroize-success"
        self.service.record_artifact(
            self.task_id,
            artifact_id="zeroize-success",
            content=content,
            kind="application/octet-stream",
            semantic_sha256=hashlib.sha256(content).hexdigest(),
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertTrue(captured)
        self.assertEqual(captured[-1], bytearray(len(captured[-1])))

        def wrong_resolver(_capability_id: str) -> bytearray:
            owned = bytearray(b"x" * 32)
            captured.append(owned)
            return owned

        self.service._secret_resolver = wrong_resolver
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.record_artifact(
                self.task_id,
                artifact_id="zeroize-proof-failure",
                content=b"proof-failure",
                kind="application/octet-stream",
                semantic_sha256=digest("proof-failure"),
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code, "MANAGER_CAPABILITY_PROOF_INVALID"
        )
        self.assertEqual(captured[-1], bytearray(len(captured[-1])))

        self.service._secret_resolver = correct_resolver
        with mock.patch.object(
            dev_flow,
            "consume_manager_capability_request",
            side_effect=RuntimeError("injected consumer failure"),
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                self.service.record_artifact(
                    self.task_id,
                    artifact_id="zeroize-internal-failure",
                    content=b"internal-failure",
                    kind="application/octet-stream",
                    semantic_sha256=digest("internal-failure"),
                    request=self.request(
                        dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                    ),
                    principal=self.principal(),
                    data_dir=self.data,
                )
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_SERVICE_FAILED"
        )
        self.assertEqual(captured[-1], bytearray(len(captured[-1])))

    def test_map_expansion_commits_formally_and_exact_replay_is_zero_write(
        self,
    ) -> None:
        plan = self._record_plan()
        request = self.request(
            dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
        )
        receipt = self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=request,
            principal=self.principal(),
            data_dir=self.data,
        )
        state = self.state()
        expansion = state["orchestration"]["expansion"]
        self.assertEqual(
            receipt.event_type,
            "orchestration.map.expand.event.v1",
        )
        self.assertIsNotNone(expansion)
        for child in expansion["children"]:
            node = next(
                item
                for item in state["node_instances"]
                if item["node_instance_id"]
                == child["node_instance_id"]
            )
            self.assertEqual(node["state"], "PENDING")
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.expand_plan(
                self.task_id,
                current_semantic_input_sha256=plan[
                    "semantic_input_sha256"
                ],
                request=request,
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertIn(
            raised.exception.code,
            {
                "REVISION_CONFLICT",
                "MANAGER_CAPABILITY_REQUEST_REPLAYED",
            },
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(), before_events
        )

        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.expand_plan(
                self.task_id,
                current_semantic_input_sha256=plan[
                    "semantic_input_sha256"
                ],
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_MAP_EXPANSION_ALREADY_CURRENT",
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(), before_events
        )
        ready = self.service.advance_ready_frontier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(
            ready.event_type,
            "orchestration.frontier.advance.event.v1",
        )
        ready_state = self.state()
        self.assertTrue(
            all(
                next(
                    node
                    for node in ready_state["node_instances"]
                    if node["node_instance_id"]
                    == child["node_instance_id"]
                )["state"]
                == "READY"
                for child in expansion["children"]
            )
        )

    def test_wrong_profile_is_rejected_without_state_or_event(self) -> None:
        task_id = "orchestration-unsupported-profile"
        bundle = dev_flow._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
            ("full", 3)
        ]
        fields = json.loads(
            json.dumps(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            )
        )
        fields["execution_profile"] = "unsupported-profile"
        task_dir = self.data / "tasks" / task_id
        task_dir.mkdir(parents=True)
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            **fields,
        }
        state_path = task_dir / "state.json"
        state_path.write_text(
            json.dumps(state, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before = state_path.read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.authorize_manager(
                task_id,
                expected_revision=0,
                manager_session_id="unsupported-manager",
                ttl_ns=100_000_000,
                operator_confirmed=True,
                operator_confirmation_sha256=digest("single-confirm"),
                issuance_audit_sha256=digest("single-audit"),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "TASK_EXECUTION_PROFILE_INVALID",
        )
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((task_dir / "events.jsonl").exists())

    def test_control_evaluator_rejects_rogue_sibling_in_allowed_root(
        self,
    ) -> None:
        old_state = self.state()
        receipt = self.service.record_artifact(
            self.task_id,
            artifact_id="formal-artifact",
            content=b"formal-artifact",
            kind="application/octet-stream",
            semantic_sha256=digest("formal-artifact"),
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        candidate = self.state()
        candidate["revision"] = old_state["revision"]
        candidate["updated_at"] = old_state["updated_at"]
        dev_flow._osc_evaluate_control_mutation(
            old_state,
            candidate,
            operation_id=(
                dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
            ),
            event_type="orchestration_artifact_recorded",
            payload=receipt.payload,
        )
        rogue = json.loads(json.dumps(candidate))
        rogue_reference = dict(
            rogue["orchestration"]["artifacts"]["formal-artifact"]
        )
        rogue_reference["id"] = "rogue-sibling"
        rogue["orchestration"]["artifacts"][
            "rogue-sibling"
        ] = rogue_reference
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._osc_evaluate_control_mutation(
                old_state,
                rogue,
                operation_id=(
                    dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                ),
                event_type="orchestration_artifact_recorded",
                payload=receipt.payload,
            )
        self.assertEqual(
            raised.exception.code,
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
        )
        rogue_field = json.loads(json.dumps(candidate))
        rogue_field["orchestration"]["artifacts"][
            "formal-artifact"
        ]["caller_allowed_write"] = True
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._osc_evaluate_control_mutation(
                old_state,
                rogue_field,
                operation_id=(
                    dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
                ),
                event_type="orchestration_artifact_recorded",
                payload=receipt.payload,
            )
        self.assertEqual(
            raised.exception.code,
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
        )

    def test_result_acceptance_replay_conflict_and_api_boundary(
        self,
    ) -> None:
        _plan, repo, assignment = self._start_assignment()
        result = self._successful_result(repo, assignment)
        request = self.request(
            dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
        )
        receipt = self.service.accept_result(
            self.task_id,
            result,
            request=request,
            principal=self.principal(),
            data_dir=self.data,
        )
        record = self.state()["orchestration"][
            "accepted_results"
        ][result["result_id"]]
        self.assertEqual(
            receipt.event_type,
            "orchestration.result.accept.event.v1",
        )
        self.assertEqual(
            record["receipt"]["accepted_revision"],
            receipt.revision,
        )
        self.assertNotIn("event_id", record["receipt"])
        self.assertNotIn(
            "verified_output",
            inspect.signature(self.service.accept_result).parameters,
        )

        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                result,
                request=request,
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertIn(
            raised.exception.code,
            {
                "REVISION_CONFLICT",
                "MANAGER_CAPABILITY_REQUEST_REPLAYED",
            },
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

        conflict = json.loads(json.dumps(result))
        conflict["summary"] = "different bytes under the same identity"
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                conflict,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_IDENTITY_MISMATCH",
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                result,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_REPLAY",
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

    def test_result_reverification_rejects_in_lock_worktree_drift(
        self,
    ) -> None:
        _plan, repo, assignment = self._start_assignment()
        result = self._successful_result(repo, assignment)
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        original = dev_flow._osc_verify_worker_result
        calls = 0

        def verify_with_race(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                (repo / "src").mkdir()
                (repo / "src" / "late-race.txt").write_text(
                    "late mutation\n", encoding="utf-8"
                )
            return original(*args, **kwargs)

        with mock.patch.object(
            dev_flow,
            "_osc_verify_worker_result",
            side_effect=verify_with_race,
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                self.service.accept_result(
                    self.task_id,
                    result,
                    request=self.request(
                        dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                    ),
                    principal=self.principal(),
                    data_dir=self.data,
                )
        self.assertEqual(calls, 2)
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_WORKTREE_DRIFT"
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

    def test_result_observer_rejects_skip_worktree_hidden_byte_drift(
        self,
    ) -> None:
        _plan, repo, assignment = self._start_assignment()
        result = self._successful_result(repo, assignment)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "update-index",
                "--skip-worktree",
                "tracked.txt",
            ],
            check=True,
        )
        (repo / "tracked.txt").write_bytes(
            b"hidden bytes differ from the accepted candidate\n"
        )
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()

        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                result,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                ),
                principal=self.principal(),
                data_dir=self.data,
            )

        self.assertEqual(raised.exception.code, "HIDDEN_INDEX_FLAGS")
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

    def test_result_observer_ignores_hostile_git_directory_environment(
        self,
    ) -> None:
        _plan, repo, assignment = self._start_assignment()
        result = self._successful_result(repo, assignment)
        decoy, _remote = self.make_repo("hostile-git-env-decoy")
        hostile = {
            "GIT_DIR": str(decoy / ".git"),
            "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(
                decoy / ".git" / "objects"
            ),
        }

        with mock.patch.dict(os.environ, hostile, clear=False):
            receipt = self.service.accept_result(
                self.task_id,
                result,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                ),
                principal=self.principal(),
                data_dir=self.data,
            )

        self.assertEqual(
            receipt.payload["result_id"], result["result_id"]
        )
        self.assertEqual(
            self.state()["orchestration"]["accepted_results"][
                result["result_id"]
            ]["result"]["assignment_id"],
            assignment["assignment_id"],
        )

    def test_complete_integration_review_and_finalization_chain(
        self,
    ) -> None:
        _repo, _assignment, result, barrier_id = (
            self._ready_integration_member()
        )
        snapshot_id, verification_id = (
            self._capture_and_verify_integration(barrier_id)
        )
        review = self.service.record_independent_review(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_REVIEW
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        status = self.service.finalization_status(
            self.task_id, data_dir=self.data
        )

        self.assertEqual(
            self.state()["orchestration"]["current_results"][
                result["node_instance_id"]
            ],
            result["result_id"],
        )
        self.assertEqual(
            self.state()["orchestration"][
                "integration_verification"
            ]["verification_id"],
            verification_id,
        )
        self.assertEqual(
            review.payload["snapshot_id"], snapshot_id
        )
        self.assertTrue(status["ready"], status)
        self.assertEqual(status["blockers"], [])

    def test_two_repository_worktrees_complete_serialized_cas_chain(
        self,
    ) -> None:
        _api_source, api_worktree = self._make_linked_worktree(
            "multi-api"
        )
        _web_source, web_worktree = self._make_linked_worktree(
            "multi-web"
        )
        worktrees = {
            "api": api_worktree,
            "web": web_worktree,
        }
        bindings = {
            repository_id: dev_flow._osc_stable_worktree_binding(
                str(worktree)
            )
            for repository_id, worktree in worktrees.items()
        }
        self.assertEqual(
            len(
                {
                    value["repository_common_dir_sha256"]
                    for value in bindings.values()
                }
            ),
            2,
        )
        plan = self._record_plan(
            repositories=[
                {
                    "repository_id": repository_id,
                    "identity_sha256": bindings[repository_id][
                        "repository_common_dir_sha256"
                    ],
                    "repository_path": (
                        f"repositories/{repository_id}"
                    ),
                }
                for repository_id in ("api", "web")
            ]
        )
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        children = {
            child["repository_id"]: child
            for child in self.state()["orchestration"][
                "expansion"
            ]["children"]
        }
        for repository_id in ("api", "web"):
            self.service.advance_ready_frontier(
                self.task_id,
                node_instance_id=str(
                    children[repository_id]["node_instance_id"]
                ),
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        assignments = {
            repository_id: self._issue_repository_assignment(
                plan,
                children[repository_id],
                worktrees[repository_id],
            )
            for repository_id in ("api", "web")
        }

        running = self.state()
        lease_ids = {
            repository_id: str(
                assignment["lease_credential"]["lease_id"]
            )
            for repository_id, assignment in assignments.items()
        }
        self.assertEqual(len(set(lease_ids.values())), 2)
        self.assertEqual(
            {
                node["repository_id"]
                for node in running["node_instances"]
                if node.get("repository_id") in worktrees
                and node["state"] == "RUNNING"
            },
            {"api", "web"},
        )
        for lease_id in lease_ids.values():
            lease = dev_flow.validate_worker_lease(
                running["orchestration"]["leases"][lease_id]
            )
            status = dev_flow.worker_lease_status(
                lease,
                wall_time_ns=self.wall_ns,
                monotonic_time_ns=self.monotonic_ns,
                clock_id="orchestration-test-clock",
            )
            self.assertTrue(status.authorized)
            self.assertFalse(status.quiesced)
        self.assertNotEqual(
            assignments["api"]["worktree_identity_sha256"],
            assignments["web"]["worktree_identity_sha256"],
        )

        for repository_id, worktree in worktrees.items():
            source_dir = worktree / "src"
            source_dir.mkdir()
            (source_dir / f"{repository_id}.txt").write_text(
                f"implemented {repository_id}\n",
                encoding="utf-8",
            )
        candidates = sorted(
            (
                self._successful_result(
                    worktrees[repository_id],
                    assignments[repository_id],
                )
                for repository_id in ("api", "web")
            ),
            key=lambda result: str(
                result["node_instance_id"]
            ).encode("utf-8"),
        )
        shared_revision = int(self.state()["revision"])
        first_request = self.request(
            dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT,
            expected_revision=shared_revision,
        )
        stale_second_request = self.request(
            dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT,
            expected_revision=shared_revision,
        )
        first_receipt = self.service.accept_result(
            self.task_id,
            candidates[0],
            request=first_request,
            principal=self.principal(),
            data_dir=self.data,
        )
        before_stale_state = (
            self.task_dir / "state.json"
        ).read_bytes()
        before_stale_events = (
            self.task_dir / "events.jsonl"
        ).read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                candidates[1],
                request=stale_second_request,
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(),
            before_stale_state,
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_stale_events,
        )

        reloaded = self.state()
        self.assertEqual(
            reloaded["orchestration"]["current_results"][
                candidates[0]["node_instance_id"]
            ],
            candidates[0]["result_id"],
        )
        self.assertNotIn(
            candidates[1]["node_instance_id"],
            reloaded["orchestration"]["current_results"],
        )
        revalidated = dev_flow._osc_verify_worker_result(
            self.task_id,
            candidates[1],
            data_dir=self.data,
            wall_time_ns=lambda: self.wall_ns,
            monotonic_time_ns=lambda: self.monotonic_ns,
            clock_id="orchestration-test-clock",
        )
        self.assertEqual(
            revalidated["worktree_sha256"],
            candidates[1]["worktree_sha256"],
        )
        second_receipt = self.service.accept_result(
            self.task_id,
            candidates[1],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT,
                expected_revision=int(reloaded["revision"]),
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(
            second_receipt.revision, first_receipt.revision + 1
        )

        for candidate in candidates:
            assignment = assignments[candidate["repository_id"]]
            self.service.record_authenticated_stop(
                self.task_id,
                lease_id=str(
                    assignment["lease_credential"]["lease_id"]
                ),
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_RUNTIME_STOP
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        barrier = self.service.evaluate_barrier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_BARRIER_CLOSE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(barrier.payload["status"], "CLOSED")
        snapshot_id, verification_id = (
            self._capture_and_verify_integration(
                str(barrier.payload["barrier_id"])
            )
        )
        review = self.service.record_independent_review(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_REVIEW
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        final = self.state()["orchestration"]
        snapshot = final["integration"]["payload"]
        status = self.service.finalization_status(
            self.task_id, data_dir=self.data
        )
        self.assertEqual(snapshot["repository_set"], ["api", "web"])
        self.assertEqual(
            {
                member["repository_id"]
                for member in snapshot["members"]
            },
            {"api", "web"},
        )
        self.assertEqual(
            final["integration_verification"][
                "verification_id"
            ],
            verification_id,
        )
        self.assertEqual(review.payload["snapshot_id"], snapshot_id)
        self.assertTrue(status["ready"], status)
        self.assertEqual(status["blockers"], [])

    def test_integration_capture_rejects_late_worktree_race_atomically(
        self,
    ) -> None:
        repo, _assignment, _result, barrier_id = (
            self._ready_integration_member()
        )
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        original = dev_flow._osc_controller_worktree_snapshot
        calls = 0

        def observe_with_late_write(*args, **kwargs):
            nonlocal calls
            observed = original(*args, **kwargs)
            calls += 1
            if calls == 1:
                (repo / "late-after-quiescence.txt").write_text(
                    "late write\n", encoding="utf-8"
                )
            return observed

        with mock.patch.object(
            dev_flow,
            "_osc_controller_worktree_snapshot",
            side_effect=observe_with_late_write,
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                self.service.capture_integration_snapshot(
                    self.task_id,
                    barrier_id=barrier_id,
                    request=self.request(
                        dev_flow.ORCHESTRATION_ACTION_INTEGRATION_CAPTURE
                    ),
                    principal=self.principal(),
                    data_dir=self.data,
                )

        self.assertEqual(
            raised.exception.code, "INTEGRATION_WORKTREE_DRIFT"
        )
        self.assertGreaterEqual(calls, 2)
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

    def test_finalization_status_reobserves_drift_after_verification(
        self,
    ) -> None:
        repo, _assignment, _result, barrier_id = (
            self._ready_integration_member()
        )
        self._capture_and_verify_integration(barrier_id)
        self.service.record_independent_review(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_REVIEW
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        (repo / "tracked.txt").write_text(
            "drift after integration verification\n",
            encoding="utf-8",
        )

        status = self.service.finalization_status(
            self.task_id, data_dir=self.data
        )

        self.assertFalse(status["ready"])
        self.assertIn(
            "INTEGRATION_WORKTREE_DRIFT", status["blockers"]
        )

    def test_result_invalidation_reopens_complete_integration_chain(
        self,
    ) -> None:
        _repo, _assignment, result, barrier_id = (
            self._ready_integration_member()
        )
        self._capture_and_verify_integration(barrier_id)
        self.service.record_independent_review(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_REVIEW
            ),
            principal=self.principal(),
            data_dir=self.data,
        )

        self.service.invalidate_result(
            self.task_id,
            result_id=str(result["result_id"]),
            reason="dependency-contract-changed",
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_INVALIDATE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.reopen_barrier(
            self.task_id,
            barrier_id=barrier_id,
            reason="dependency-contract-changed",
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_BARRIER_REOPEN
            ),
            principal=self.principal(),
            data_dir=self.data,
        )

        orchestration = self.state()["orchestration"]
        status = self.service.finalization_status(
            self.task_id, data_dir=self.data
        )
        self.assertEqual(
            orchestration["barriers"][barrier_id]["status"],
            "REOPENED",
        )
        self.assertFalse(orchestration["integration"]["current"])
        self.assertFalse(
            orchestration["integration_verification"]["current"]
        )
        self.assertFalse(orchestration["review"]["current"])
        self.assertFalse(status["ready"])
        self.assertIn(
            "INTEGRATION_SNAPSHOT_NOT_CURRENT",
            status["blockers"],
        )

    @test_case.unittest.skipUnless(
        hasattr(os, "symlink"), "symbolic links are unavailable"
    )
    def test_worktree_observation_rejects_untracked_symlink(
        self,
    ) -> None:
        repo, _remote = self.make_repo("symlink-observation")
        (repo / "src").mkdir()
        outside = self.root / "outside-secret.txt"
        outside.write_text("must not be read\n", encoding="utf-8")
        (repo / "src" / "external-link").symlink_to(outside)
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._osc_worktree_observation(str(repo))
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_WORKTREE_TYPE_UNSUPPORTED",
        )

    @test_case.unittest.skipIf(
        os.name == "nt", "POSIX O_NOFOLLOW race is exercised here"
    )
    def test_worktree_observation_rejects_file_to_symlink_race(
        self,
    ) -> None:
        repo, _remote = self.make_repo("nofollow-observation")
        (repo / "src").mkdir()
        target = repo / "src" / "candidate.txt"
        target.write_text("candidate\n", encoding="utf-8")
        outside = self.root / "outside-race-secret.txt"
        outside.write_text("must not be read\n", encoding="utf-8")
        real_open = dev_flow._osc_os.open
        replaced = False

        def replace_before_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if not replaced and Path(path) == target:
                replaced = True
                target.unlink()
                target.symlink_to(outside)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(
            dev_flow._osc_os,
            "open",
            side_effect=replace_before_open,
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                dev_flow._osc_worktree_observation(str(repo))
        self.assertTrue(replaced)
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_WORKTREE_CHANGED"
        )

    def test_host_observation_runs_before_formal_assignment_commit(
        self,
    ) -> None:
        observations: list[tuple[int, str]] = []
        trusted = self._trusted_host_observer

        def observer(assignment: dict[str, object]) -> dict[str, object]:
            state = self.state()
            event = json.loads(self.event_lines()[-1])
            observations.append(
                (int(state["revision"]), str(event["type"]))
            )
            return trusted(assignment)

        self.service._host_capability_observer = observer
        self._start_assignment()
        self.assertEqual(len(observations), 1)
        self.assertNotEqual(
            observations[0][1], "orchestration_worker_assigned"
        )
        self.assertLess(
            observations[0][0], int(self.state()["revision"])
        )

    def test_assignment_without_handoff_has_no_runtime_attempt(
        self,
    ) -> None:
        _plan, _repo, assignment = self._start_assignment(
            runtime_handle_id=None
        )
        orchestration = self.state()["orchestration"]
        self.assertNotIn(
            assignment["assignment_id"],
            orchestration["dispatch"],
        )
        self.assertEqual(
            next(
                node
                for node in self.state()["node_instances"]
                if node["node_instance_id"]
                == assignment["node_instance_id"]
            )["state"],
            "READY",
        )

    def test_absent_runtime_handle_rejects_stop_and_allows_recovery(
        self,
    ) -> None:
        _plan, _repo, assignment = self._start_assignment(
            runtime_handle_id=None
        )
        lease_id = assignment["lease_credential"]["lease_id"]
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.record_authenticated_stop(
                self.task_id,
                lease_id=lease_id,
                request=self.request(
                    dev_flow.ORCHESTRATION_ACTION_RUNTIME_STOP
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_STOP_HANDLE_REQUIRED"
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(),
            before_state,
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

        self.recovery_observation = (False, False, False)
        receipt = self.service.recover_runtime(
            self.task_id,
            lease_id=lease_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(
            receipt.payload["status"], "ORPHANED_UNCERTAIN"
        )

    def test_failed_assignment_commit_precedes_worktree_claim(
        self,
    ) -> None:
        plan = self._record_plan()
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.advance_ready_frontier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        state = self.state()
        child = state["orchestration"]["expansion"]["children"][0]
        repo, _remote = self.make_repo("failed-assignment-api")
        allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        input_evidence_sha256 = digest(
            "failed-assignment-input"
        )
        lease = self.service.issue_lease(
            self.task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(repo),
            input_evidence_sha256=input_evidence_sha256,
            allowed_actions=allowed_actions,
            lease_ttl_ns=10_000_000_000,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_LEASE_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()

        with mock.patch.object(
            dev_flow,
            "commit_v3_workflow_action",
            side_effect=dev_flow.FlowError(
                "INJECTED_ASSIGNMENT_COMMIT_FAILURE",
                "injected formal assignment commit failure",
            ),
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                self.service.issue_assignment(
                    self.task_id,
                    node_instance_id=child["node_instance_id"],
                    worktree_path=str(repo),
                    input_evidence_sha256=input_evidence_sha256,
                    allowed_actions=allowed_actions,
                    playbook_locator="playbooks/workflow.md",
                    playbook_sha256=digest("playbook"),
                    required_evidence_contract_sha256s=plan[
                        "repositories"
                    ][0]["required_evidence_contract_sha256"],
                    runtime_handle_id="runtime-failed-api",
                    host_assignment_id="host-assignment-failed-api",
                    runtime_authentication_sha256=digest(
                        "runtime-auth-failed"
                    ),
                    actor_id="worker-actor-failed-api",
                    lease_ttl_ns=10_000_000_000,
                    lease_id=str(lease.payload["lease_id"]),
                    request=self.request(
                        dev_flow.ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE
                    ),
                    principal=self.principal(),
                    data_dir=self.data,
                )
        self.assertEqual(
            raised.exception.code,
            "INJECTED_ASSIGNMENT_COMMIT_FAILURE",
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(),
            before_state,
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )
        registry_path = self.data / "worktree-claims.json"
        if registry_path.exists():
            registry = json.loads(
                registry_path.read_text(encoding="utf-8")
            )
            self.assertEqual(registry["claims"], {})

    def test_durable_worktree_writer_claim_blocks_second_task_commit(
        self,
    ) -> None:
        _source, shared_worktree = self._make_linked_worktree(
            "shared-writer"
        )
        binding = dev_flow._osc_stable_worktree_binding(
            str(shared_worktree)
        )
        owner_plan = self._record_plan(
            repositories=[
                {
                    "repository_id": "owner",
                    "identity_sha256": binding[
                        "repository_common_dir_sha256"
                    ],
                    "repository_path": "repositories/owner",
                }
            ]
        )
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=owner_plan[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.advance_ready_frontier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        owner_child = self.state()["orchestration"][
            "expansion"
        ]["children"][0]
        owner_assignment = self._issue_repository_assignment(
            owner_plan, owner_child, shared_worktree
        )
        owner_lease_id = str(
            owner_assignment["lease_credential"]["lease_id"]
        )

        contender_task_id = "orchestration-claim-contender"
        contender_session_id = "manager-session-contender"
        bundle = dev_flow._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
            ("full", 3)
        ]
        creation_fields = json.loads(
            json.dumps(
                dev_flow.build_v3_task_creation_fields(
                    contender_task_id,
                    bundle,
                    execution_profile="multi-repository",
                )
            )
        )
        contender_dir = (
            self.data / "tasks" / contender_task_id
        )
        contender_dir.mkdir(parents=True)
        (contender_dir / "state.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "task_id": contender_task_id,
                    "revision": 0,
                    "status": "INTAKE",
                    "flow": "full",
                    **creation_fields,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        authorized = self.service.authorize_manager(
            contender_task_id,
            expected_revision=0,
            manager_session_id=contender_session_id,
            ttl_ns=100_000_000_000,
            operator_confirmed=True,
            operator_confirmation_sha256=digest(
                "contender-operator-confirmation"
            ),
            issuance_audit_sha256=digest(
                "contender-issuance-audit"
            ),
            data_dir=self.data,
        )
        contender_capability_id = str(
            authorized.payload["capability_id"]
        )
        contender_nonce = 0

        def contender_state() -> dict[str, object]:
            return json.loads(
                (contender_dir / "state.json").read_text(
                    encoding="utf-8"
                )
            )

        def contender_request(
            action_id: str,
        ) -> dict[str, object]:
            nonlocal contender_nonce
            contender_nonce += 1
            return {
                "schema": (
                    dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA
                ),
                "capability_id": contender_capability_id,
                "task_id": contender_task_id,
                "manager_session_id": contender_session_id,
                "action_id": action_id,
                "expected_revision": int(
                    contender_state()["revision"]
                ),
                "request_nonce": digest(
                    f"contender-request-{contender_nonce}"
                ),
            }

        contender_principal = {
            "schema": dev_flow.AGENT_PRINCIPAL_SCHEMA,
            "role": "manager",
            "session_id": contender_session_id,
            "os_user_identity_sha256": digest("os-user"),
            "host_identity_sha256": digest("host"),
        }
        contract_content = (
            b'{"schema":"contract.integration/v1"}\n'
        )
        contract_sha256 = hashlib.sha256(
            contract_content
        ).hexdigest()
        self.service.record_artifact(
            contender_task_id,
            artifact_id="artifact-integration-contract",
            content=contract_content,
            kind="application/vnd.dev-flow.contract+json",
            semantic_sha256=contract_sha256,
            request=contender_request(
                dev_flow.ORCHESTRATION_ACTION_ARTIFACT_RECORD
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        contender_plan_value = {
            "schema": dev_flow.REPOSITORY_PLAN_SCHEMA,
            "task_id": contender_task_id,
            "workflow_bundle_sha256": bundle.bundle_sha256,
            "plan_id": "plan-worktree-claim-contender",
            "map_node_id": "map.repositories/v1",
            "map_epoch": 1,
            "plan_input_revision": contender_state()["revision"],
            "semantic_input_sha256": "0" * 64,
            "repository_set": ["contender"],
            "repositories": [
                {
                    "repository_id": "contender",
                    "identity_sha256": binding[
                        "repository_common_dir_sha256"
                    ],
                    "repository_path": "repositories/contender",
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
                    "artifact_id": (
                        "artifact-integration-contract"
                    ),
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
        contender_plan = json.loads(
            dev_flow.canonical_repository_plan_bytes(
                dev_flow.bind_repository_plan_semantic_input(
                    contender_plan_value
                )
            )
        )
        self.service.record_plan(
            contender_task_id,
            contender_plan,
            request=contender_request(
                dev_flow.ORCHESTRATION_ACTION_PLAN_RECORD
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        self.service.approve_plan(
            contender_task_id,
            approval_intent="approve-repository-map/v1",
            request=contender_request(
                dev_flow.ORCHESTRATION_ACTION_PLAN_APPROVE
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        self.service.expand_plan(
            contender_task_id,
            current_semantic_input_sha256=contender_plan[
                "semantic_input_sha256"
            ],
            request=contender_request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        self.service.advance_ready_frontier(
            contender_task_id,
            request=contender_request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        contender_child = contender_state()["orchestration"][
            "expansion"
        ]["children"][0]
        contender_allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        contender_input_sha256 = digest(
            "contender-assignment-input"
        )
        contender_lease = self.service.issue_lease(
            contender_task_id,
            node_instance_id=str(
                contender_child["node_instance_id"]
            ),
            worktree_path=str(shared_worktree),
            input_evidence_sha256=contender_input_sha256,
            allowed_actions=contender_allowed_actions,
            lease_ttl_ns=10_000_000_000,
            request=contender_request(
                dev_flow.ORCHESTRATION_OPERATION_LEASE_ISSUE
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        contender_assignment = self.service.issue_assignment(
            contender_task_id,
            node_instance_id=str(
                contender_child["node_instance_id"]
            ),
            worktree_path=str(shared_worktree),
            input_evidence_sha256=contender_input_sha256,
            allowed_actions=contender_allowed_actions,
            playbook_locator="playbooks/workflow.md",
            playbook_sha256=digest("playbook"),
            required_evidence_contract_sha256s=[
                contract_sha256
            ],
            runtime_handle_id="runtime-contender",
            host_assignment_id="host-assignment-contender",
            runtime_authentication_sha256=digest(
                "runtime-auth-contender"
            ),
            actor_id="worker-actor-contender",
            lease_ttl_ns=10_000_000_000,
            lease_id=str(contender_lease.payload["lease_id"]),
            request=contender_request(
                dev_flow.ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE
            ),
            principal=contender_principal,
            data_dir=self.data,
        )
        before_state = (
            contender_dir / "state.json"
        ).read_bytes()
        before_events = (
            contender_dir / "events.jsonl"
        ).read_bytes()
        registry_path = self.data / "worktree-claims.json"
        before_registry = registry_path.read_bytes()
        before_head = test_case.git(
            shared_worktree, "rev-parse", "HEAD"
        )
        before_status = test_case.git(
            shared_worktree,
            "status",
            "--porcelain=v2",
            "--untracked-files=all",
        )

        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.handoff_dispatch(
                contender_task_id,
                assignment_id=str(
                    contender_assignment.payload[
                        "assignment_id"
                    ]
                ),
                runtime_handle_id="runtime-contender",
                host_assignment_id=(
                    "host-assignment-contender"
                ),
                runtime_authentication_sha256=digest(
                    "runtime-auth-contender"
                ),
                actor_id="worker-actor-contender",
                request=contender_request(
                    dev_flow.ORCHESTRATION_OPERATION_DISPATCH_HANDOFF
                ),
                principal=contender_principal,
                data_dir=self.data,
            )

        self.assertEqual(
            raised.exception.code,
            "WORKTREE_WRITER_CLAIM_CONFLICT",
        )
        self.assertEqual(
            (contender_dir / "state.json").read_bytes(),
            before_state,
        )
        self.assertEqual(
            (contender_dir / "events.jsonl").read_bytes(),
            before_events,
        )
        self.assertEqual(registry_path.read_bytes(), before_registry)
        self.assertEqual(
            test_case.git(shared_worktree, "rev-parse", "HEAD"),
            before_head,
        )
        self.assertEqual(
            test_case.git(
                shared_worktree,
                "status",
                "--porcelain=v2",
                "--untracked-files=all",
            ),
            before_status,
        )
        contender_orchestration = contender_state()[
            "orchestration"
        ]
        self.assertEqual(len(contender_orchestration["leases"]), 1)
        self.assertEqual(
            len(contender_orchestration["assignments"]), 1
        )
        self.assertEqual(contender_orchestration["dispatch"], {})
        owner_lease = self.state()["orchestration"]["leases"][
            owner_lease_id
        ]
        self.assertIsNone(owner_lease["revoked_at_wall_ns"])
        self.assertIsNone(owner_lease["quiesced_at_wall_ns"])

    def test_expired_lease_result_is_rejected_without_commit(
        self,
    ) -> None:
        _plan, repo, assignment = self._start_assignment(
            lease_ttl_ns=10
        )
        result = self._successful_result(repo, assignment)
        self.monotonic_ns += 11
        before_state = (self.task_dir / "state.json").read_bytes()
        before_events = (self.task_dir / "events.jsonl").read_bytes()
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.accept_result(
                self.task_id,
                result,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_RESULT_ACCEPT
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_LATE_OR_ORPHANED"
        )
        self.assertEqual(
            (self.task_dir / "state.json").read_bytes(), before_state
        )
        self.assertEqual(
            (self.task_dir / "events.jsonl").read_bytes(),
            before_events,
        )

    def test_orphan_recovery_abandons_attempt_then_retries_safely(
        self,
    ) -> None:
        plan, repo, assignment = self._start_assignment()
        lease_id = assignment["lease_credential"]["lease_id"]
        self.recovery_observation = (False, False, False)
        recovered = self.service.recover_runtime(
            self.task_id,
            lease_id=lease_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(recovered.payload["status"], "ORPHANED_UNCERTAIN")
        orphaned = self.state()["orchestration"]
        self.assertEqual(orphaned["leases"][lease_id]["state"], "REVOKED")
        self.assertFalse(
            orphaned["leases"][lease_id]["quiesced_at_wall_ns"]
            is not None
        )

        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.abandon_attempt(
                self.task_id,
                lease_id=lease_id,
                reason="runtime-handle-lost",
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_ATTEMPT_ABANDON
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_ATTEMPT_ABANDON_QUIESCENCE_REQUIRED",
        )

        self.service.begin_reconciliation(
            self.task_id,
            lease_id=lease_id,
            reason="runtime-handle-unavailable",
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_RECONCILE_BEGIN
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.monotonic_ns += dev_flow.KERNEL_MINIMUM_STABILITY_NS
        self.service.complete_reconciliation(
            self.task_id,
            lease_id=lease_id,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_RECONCILE_COMPLETE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        abandonment = self.service.abandon_attempt(
            self.task_id,
            lease_id=lease_id,
            reason="runtime-handle-lost",
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_ATTEMPT_ABANDON
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(
            abandonment.event_type,
            "orchestration.attempt.abandon.event.v1",
        )
        result_id = abandonment.payload["result_id"]
        blocked = self.state()["orchestration"]
        self.assertTrue(
            blocked["attempts"][result_id]["controller_owned"]
        )
        self.assertEqual(
            next(
                node
                for node in self.state()["node_instances"]
                if node["node_instance_id"]
                == assignment["node_instance_id"]
            )["state"],
            "BLOCKED",
        )

        self.service.request_retry(
            self.task_id,
            result_id=result_id,
            worktree_strategy="resume-verified",
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_RETRY
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        current = self.state()
        child = current["orchestration"]["expansion"][
            "children"
        ][0]
        replacement_input_sha256 = digest("replacement-input")
        replacement_lease = self.service.issue_lease(
            self.task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(repo),
            input_evidence_sha256=replacement_input_sha256,
            allowed_actions=[
                "repository.read/v1",
                "repository.write-approved/v1",
                "result.emit-candidate/v1",
            ],
            lease_ttl_ns=10_000_000_000,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_LEASE_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        replacement = self.service.issue_assignment(
            self.task_id,
            node_instance_id=child["node_instance_id"],
            worktree_path=str(repo),
            input_evidence_sha256=replacement_input_sha256,
            allowed_actions=[
                "repository.read/v1",
                "repository.write-approved/v1",
                "result.emit-candidate/v1",
            ],
            playbook_locator="playbooks/workflow.md",
            playbook_sha256=digest("playbook"),
            required_evidence_contract_sha256s=plan[
                "repositories"
            ][0]["required_evidence_contract_sha256"],
            runtime_handle_id="runtime-api-2",
            host_assignment_id="host-assignment-api-2",
            runtime_authentication_sha256=digest(
                "runtime-auth-2"
            ),
            actor_id="worker-actor-api-2",
            lease_ttl_ns=10_000_000_000,
            lease_id=str(replacement_lease.payload["lease_id"]),
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.handoff_dispatch(
            self.task_id,
            assignment_id=str(
                replacement.payload["assignment_id"]
            ),
            runtime_handle_id="runtime-api-2",
            host_assignment_id="host-assignment-api-2",
            runtime_authentication_sha256=digest(
                "runtime-auth-2"
            ),
            actor_id="worker-actor-api-2",
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_DISPATCH_HANDOFF
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(replacement.payload["attempt"], 2)
        final = self.state()
        final_node = next(
            node
            for node in final["node_instances"]
            if node["node_instance_id"]
            == assignment["node_instance_id"]
        )
        self.assertEqual(final_node["state"], "RUNNING")
        self.assertEqual(len(final_node["attempts"]), 2)
        self.assertIn(
            result_id,
            final["orchestration"]["attempts"],
        )
        self.assertNotEqual(
            replacement.payload["lease_id"], lease_id
        )

    def test_committed_stop_recovers_target_release_after_lost_response(
        self,
    ) -> None:
        _plan, _repo, assignment = self._start_assignment()
        lease_id = str(
            assignment["lease_credential"]["lease_id"]
        )
        store = dev_flow.ActionExecutionStore(self.task_dir)
        index = store.read_index(expected_task_id=self.task_id)
        targets = [
            str(entry["execution_id"])
            for entry in index["entries"]
            if entry["entry_kind"] == "runtime-reservation"
            and entry["runtime_reservation"]["phase"] == "ACTIVE"
            and entry["runtime_reservation"]["lease_id"] == lease_id
        ]
        self.assertEqual(len(targets), 1)
        target_execution_id = targets[0]
        stop_observations = 0
        original_stop_observer = (
            self.service._runtime_stop_observer
        )

        def counting_stop_observer(
            projection: dict[str, object],
        ) -> dict[str, object]:
            nonlocal stop_observations
            stop_observations += 1
            return original_stop_observer(projection)

        self.service._runtime_stop_observer = (
            counting_stop_observer
        )
        with mock.patch.object(
            dev_flow,
            "_osc_release_runtime_reservation_target",
            side_effect=dev_flow.FlowError(
                "INJECTED_TARGET_RELEASE_RESPONSE_LOSS",
                "task commit completed before target release response",
            ),
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                self.service.record_authenticated_stop(
                    self.task_id,
                    lease_id=lease_id,
                    request=self.request(
                        dev_flow.ORCHESTRATION_ACTION_RUNTIME_STOP
                    ),
                    principal=self.principal(),
                    data_dir=self.data,
                )
        self.assertEqual(
            raised.exception.code,
            "INJECTED_TARGET_RELEASE_RESPONSE_LOSS",
        )
        self.assertEqual(stop_observations, 1)
        self.assertEqual(
            store.read_runtime_reservation(
                target_execution_id
            )["phase"],
            "ACTIVE",
        )
        stop_events = [
            event
            for event in dev_flow._osc_read_bounded_events(
                self.task_dir
            )
            if event["type"]
            == "orchestration.runtime-stop.record.event.v1"
        ]
        self.assertEqual(len(stop_events), 1)
        self.assertEqual(
            stop_events[0]["payload"]["target_execution_id"],
            target_execution_id,
        )

        restarted = dev_flow.OrchestrationControllerService(
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
            clock_id="orchestration-test-clock",
            runtime_stop_observer=counting_stop_observer,
            runtime_stop_authenticator=(
                lambda _lease, _observation: True
            ),
            runtime_isolation_observer=(
                self._trusted_isolation_observer
            ),
            runtime_recovery_observer=(
                self._trusted_recovery_observer
            ),
            integration_verifier=(
                self._trusted_integration_verifier
            ),
            independent_reviewer=(
                self._trusted_independent_reviewer
            ),
            host_capability_observer=(
                self._trusted_host_observer
            ),
            trusted_host_adapter_ids=("test-host-adapter",),
            protected_read_identity_sha256s=(
                self.protected_identity,
            ),
        )
        restarted.abandon_attempt(
            self.task_id,
            lease_id=lease_id,
            reason="runtime-stopped-before-response",
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_ATTEMPT_ABANDON
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(stop_observations, 1)
        self.assertEqual(
            store.read_runtime_reservation(
                target_execution_id
            )["phase"],
            "QUIESCED",
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in dev_flow._osc_read_bounded_events(
                        self.task_dir
                    )
                    if event["type"]
                    == "orchestration.runtime-stop.record.event.v1"
                ]
            ),
            1,
        )

    def test_two_phase_map_invalidation_preserves_history_and_replans(
        self,
    ) -> None:
        plan = self._record_plan()
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.service.advance_ready_frontier(
            self.task_id,
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        old_child = self.state()["orchestration"]["expansion"][
            "children"
        ][0]["node_instance_id"]
        stale = self.service.invalidate_map(
            self.task_id,
            phase="STALE",
            reason="repository-membership-drift",
            minimum_successor_map_epoch=2,
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_MAP_INVALIDATE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(stale.payload["phase"], "STALE")
        stale_state = self.state()
        self.assertFalse(
            stale_state["orchestration"]["expansion"]["current"]
        )
        self.assertIsNone(stale_state["orchestration"]["approval"])
        with self.assertRaises(dev_flow.FlowError) as raised:
            self.service.advance_ready_frontier(
                self.task_id,
                request=self.request(
                    dev_flow.ORCHESTRATION_OPERATION_FRONTIER_ADVANCE
                ),
                principal=self.principal(),
                data_dir=self.data,
            )
        self.assertEqual(
            raised.exception.code,
            "REPOSITORY_MAP_EXPANSION_STALE",
        )

        retired = self.service.invalidate_map(
            self.task_id,
            phase="RETIRED",
            request=self.request(
                dev_flow.ORCHESTRATION_ACTION_MAP_INVALIDATE
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        self.assertEqual(retired.payload["phase"], "RETIRED")
        retired_node = next(
            node
            for node in self.state()["node_instances"]
            if node["node_instance_id"] == old_child
        )
        self.assertEqual(retired_node["state"], "SKIPPED")

        successor = self._record_plan(map_epoch=2)
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=successor[
                "semantic_input_sha256"
            ],
            request=self.request(
                dev_flow.ORCHESTRATION_OPERATION_MAP_EXPAND
            ),
            principal=self.principal(),
            data_dir=self.data,
        )
        final = self.state()
        new_child = final["orchestration"]["expansion"][
            "children"
        ][0]["node_instance_id"]
        self.assertNotEqual(new_child, old_child)
        self.assertEqual(
            next(
                node
                for node in final["node_instances"]
                if node["node_instance_id"] == old_child
            )["state"],
            "SKIPPED",
        )
        self.assertEqual(
            next(
                node
                for node in final["node_instances"]
                if node["node_instance_id"] == new_child
            )["state"],
            "PENDING",
        )
        self.assertEqual(
            len(final["orchestration"]["plan_history"]), 1
        )

    def test_service_is_available_under_isolated_stdlib_startup(
        self,
    ) -> None:
        script = (
            "import runpy;"
            f"ns=runpy.run_path({str(ROOT / 'scripts' / 'dev_flow.py')!r});"
            "print(ns['OrchestrationControllerService'].__name__)"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.strip(),
            "OrchestrationControllerService",
        )


if __name__ == "__main__":
    raise SystemExit(test_case.unittest.main())
