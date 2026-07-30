from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "orchestration_authority.py"
)
EXTERNAL_TOOLS_PATH = (
    ROOT / "scripts" / "dev_flow_parts" / "external_tools.py"
)
SPEC = importlib.util.spec_from_loader(
    "dev_flow_orchestration_authority_tests", loader=None
)
assert SPEC is not None
authority = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = authority
for source_path in (EXTERNAL_TOOLS_PATH, MODULE_PATH):
    source = source_path.read_bytes()
    exec(compile(source, str(source_path), "exec"), authority.__dict__)


def digest(character: str) -> str:
    return character * 64


def lease_spec(
    *,
    task_id: str = "task-7",
    node_instance_id: str = "map.impl:api:3",
    repository_id: str = "api",
    repository_identity_sha256: str = digest("2"),
    worktree_identity_sha256: str = digest("3"),
    attempt: int = 1,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_revision": 41,
        "workflow_bundle_sha256": digest("1"),
        "map_epoch": 3,
        "node_instance_id": node_instance_id,
        "repository_id": repository_id,
        "repository_identity_sha256": repository_identity_sha256,
        "worktree_identity_sha256": worktree_identity_sha256,
        "attempt": attempt,
        "input_evidence_sha256": digest("4"),
        "plan_dag_sha256": digest("5"),
        "semantic_input_sha256": digest("6"),
        "interface_contract_sha256s": [digest("7"), digest("8")],
        "approved_paths": ["src", "tests"],
        "allowed_actions": [
            "artifact.read/v1",
            "playbook.read/v1",
            "process.run-approved/v1",
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ],
        "write_policy": "scoped-write",
    }


def issue_lease(
    spec: Optional[dict[str, object]] = None,
    *,
    nonce: bytes = b"L" * 32,
    wall: int = 1_000_000,
    monotonic: int = 50_000,
    ttl: int = 10_000,
    existing: tuple[object, ...] = (),
) -> object:
    return authority.issue_worker_lease(
        spec or lease_spec(),
        lease_nonce_bytes=nonce,
        wall_time_ns=wall,
        monotonic_time_ns=monotonic,
        ttl_ns=ttl,
        clock_id="boot-7",
        existing_leases=existing,
    )


def create_assignment(
    lease: Optional[object] = None,
    *,
    external_tool_grants: tuple[object, ...] = (),
    external_tool_role_profile: object = None,
) -> object:
    return authority.create_worker_assignment(
        lease or issue_lease(),
        node_id="repository.implement/v1",
        worktree_path="/controller/worktrees/task-7/api",
        controller_claim_sha256=digest("9"),
        plan_id="repository-plan:task-7:3",
        plan_artifact_sha256=digest("a"),
        playbook_locator="playbooks/repository-implement.md",
        playbook_sha256=digest("b"),
        required_evidence_contract_sha256s=[
            digest("c"),
            digest("d"),
        ],
        external_tool_grants=external_tool_grants,
        external_tool_role_profile=external_tool_role_profile,
    )


def external_grant(
    *,
    task_id: str = "task-7",
    repository_id: str = "api",
    revision: int = 41,
    role_profile: object = None,
) -> tuple[object, object | None]:
    capability = authority.ExternalToolCapability(
        capability_id="tool.codebase-memory.read/v1",
        tool_id="codebase-memory",
        operations=("external-read",),
        result_schema=authority.CODEBASE_MEMORY_RESULT_SCHEMA,
        scopes=("files",),
    )
    baseline = authority.CodebaseMemoryBinding(
        phase="baseline",
        generation="generation-3",
        repository_id=repository_id,
        source_snapshot_sha256=digest("e"),
        project_id="baseline-project-3",
    )
    current = authority.CodebaseMemoryBinding(
        phase="current-generation-workspace",
        generation="generation-3",
        repository_id=repository_id,
        source_snapshot_sha256=digest("f"),
        project_id="current-project-3",
    )
    assignment = authority.build_codebase_memory_assignment(
        capability,
        current,
        controller_revision=revision,
        scopes=("files",),
    )
    request = authority.build_codebase_memory_request(
        assignment, query="find files"
    )
    profile = role_profile
    if profile is True:
        profile = authority.build_external_tool_role_profile(
            role_id="worker.read-only",
            declarations=(capability,),
            exposed_capability_ids=(capability.capability_id,),
        )
    grant = authority.build_external_tool_execution_grant(
        task_id=task_id,
        workflow_bundle_sha256=digest("1"),
        node_instance_id="map.impl:api:3",
        action_id="full.implementing.workspace-index.v1",
        execution_id="execution-41",
        effect_id="workspace-index.effect",
        attempt=1,
        declarations=(capability,),
        edge_capability_ids=(capability.capability_id,),
        capability_id=capability.capability_id,
        assignment=assignment,
        request=request,
        controller_project_bindings=(baseline, current),
        role_profile=profile,
    )
    return grant, profile


def issue_capability(
    *,
    secret: bytes = b"M" * 32,
    wall: int = 2_000_000,
    monotonic: int = 80_000,
    ttl: int = 20_000,
) -> object:
    return authority.issue_manager_capability(
        task_id="task-7",
        issued_for_task_revision=41,
        manager_session_id="manager-session-7",
        allowed_actions=[
            "action.apply/v1",
            "worker-result.submit/v1",
        ],
        ttl_ns=ttl,
        wall_time_ns=wall,
        monotonic_time_ns=monotonic,
        clock_id="boot-7",
        secret_transport="local-secret-channel",
        operator_confirmation_sha256=digest("e"),
        issuance_audit_sha256=digest("f"),
        manager_secret=secret,
    )


def manager_request(
    capability: object,
    *,
    task_id: str = "task-7",
    session_id: str = "manager-session-7",
    action_id: str = "worker-result.submit/v1",
    nonce: str = digest("a"),
) -> dict[str, object]:
    return {
        "schema": authority.MANAGER_CAPABILITY_REQUEST_SCHEMA,
        "capability_id": capability.capability_id,
        "task_id": task_id,
        "manager_session_id": session_id,
        "action_id": action_id,
        "expected_revision": 43,
        "request_nonce": nonce,
    }


def principal(
    *,
    role: str = "manager",
    session_id: str = "manager-session-7",
    os_user_identity_sha256: str = digest("1"),
) -> dict[str, object]:
    return {
        "schema": authority.AGENT_PRINCIPAL_SCHEMA,
        "role": role,
        "session_id": session_id,
        "os_user_identity_sha256": os_user_identity_sha256,
        "host_identity_sha256": digest("2"),
    }


def host_report(assignment: object) -> dict[str, object]:
    return {
        "schema": authority.HOST_CAPABILITY_REPORT_SCHEMA,
        "adapter_id": "native-subagent/v1",
        "assignment_id": assignment.assignment_id,
        "worker_session_id": "worker-session-api-1",
        "worker_identity_sha256": digest("3"),
        "attestation_sha256": digest("4"),
        "host_enforced": True,
        "allowed_write_identity_sha256s": [
            assignment.worktree_identity_sha256
        ],
        "denied_read_identity_sha256s": [
            digest("5"),
            digest("6"),
            digest("7"),
        ],
        "denied_tool_ids": [
            "action.apply/v1",
            "evidence.accept/v1",
            "worker-result.submit/v1",
        ],
        "all_other_writes_denied": True,
        "manager_secret_channel_excluded": True,
        "controller_state_excluded": True,
        "mutation_tools_excluded": True,
    }


class CanonicalAuthorityContractTests(unittest.TestCase):
    def test_canonical_json_is_deterministic_and_rejects_value_drift(
        self,
    ) -> None:
        self.assertEqual(
            authority.canonical_orchestration_bytes(
                {"z": [2, 1], "a": "value"}
            ),
            b'{"a":"value","z":[2,1]}',
        )
        for value, code in (
            ({"value": 1.5}, "ORCHESTRATION_JSON_FLOAT_FORBIDDEN"),
            (
                {"value": "e\u0301"},
                "ORCHESTRATION_JSON_STRING_NOT_NFC",
            ),
        ):
            with self.subTest(code=code):
                with self.assertRaises(
                    authority.OrchestrationAuthorityError
                ) as raised:
                    authority.canonical_orchestration_bytes(value)
                self.assertEqual(raised.exception.code, code)


class WorkerAssignmentContractTests(unittest.TestCase):
    def test_external_tool_grant_is_separate_from_worker_capabilities(
        self,
    ) -> None:
        grant, profile = external_grant(role_profile=True)
        assignment = create_assignment(
            external_tool_grants=(grant,),
            external_tool_role_profile=profile,
        )

        self.assertNotIn(
            grant.capability.capability_id, assignment.capabilities
        )
        self.assertEqual(
            assignment.external_tool_grant_sha256s,
            (grant.sha256,),
        )
        self.assertEqual(
            assignment.external_tool_role_profile_sha256,
            profile.sha256,
        )
        self.assertIs(
            authority.validate_worker_external_tool_grant(
                assignment, grant, role_profile=profile
            ),
            grant,
        )

    def test_undeclared_or_mismatched_worker_tool_fails_closed(
        self,
    ) -> None:
        grant, _ = external_grant()
        unexposed = create_assignment()
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_external_tool_grant(
                unexposed, grant
            )
        self.assertEqual(
            raised.exception.code,
            "WORKER_EXTERNAL_TOOL_GRANT_UNASSIGNED",
        )

        wrong_grant, _ = external_grant(revision=42)
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            create_assignment(external_tool_grants=(wrong_grant,))
        self.assertEqual(
            raised.exception.code,
            "WORKER_EXTERNAL_TOOL_BINDING_MISMATCH",
        )

    def test_cancellation_requested_blocks_new_lease_authority(
        self,
    ) -> None:
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.issue_worker_lease(
                lease_spec(),
                lease_nonce_bytes=b"L" * 32,
                wall_time_ns=1_000_000,
                monotonic_time_ns=50_000,
                ttl_ns=10_000,
                clock_id="boot-7",
                cancellation_requested=True,
            )
        self.assertEqual(
            raised.exception.code,
            "WORKER_LEASE_CANCELLATION_REQUESTED",
        )

    def test_assignment_binds_exact_scope_and_is_content_addressed(
        self,
    ) -> None:
        lease = issue_lease()
        assignment = create_assignment(lease)
        again = create_assignment(lease)

        self.assertEqual(assignment, again)
        self.assertEqual(
            assignment.assignment_id, again.assignment_id
        )
        self.assertEqual(
            assignment.expected_revision, lease.task_revision
        )
        self.assertEqual(
            assignment.lease_credential.mutation_authority, "none"
        )
        self.assertEqual(
            assignment.capabilities,
            assignment.lease_credential.allowed_actions,
        )
        self.assertIsInstance(assignment.approved_paths, tuple)
        self.assertIsInstance(
            assignment.interface_contract_sha256s, tuple
        )

        exported = assignment.as_dict()
        exported["approved_paths"].append("unexpected")
        self.assertEqual(assignment.approved_paths, ("src", "tests"))

        tampered = assignment.as_dict()
        tampered["expected_revision"] = 42
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_assignment(tampered)
        self.assertEqual(
            raised.exception.code,
            "WORKER_ASSIGNMENT_IDENTITY_MISMATCH",
        )

    def test_assignment_rejects_unknown_fields_paths_and_mutation_power(
        self,
    ) -> None:
        assignment = create_assignment()
        value = assignment.as_dict()
        value["manager_secret"] = "forbidden"
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_assignment(value)
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_UNKNOWN_FIELD"
        )

        bad_scope = lease_spec()
        bad_scope["allowed_actions"] = [
            *bad_scope["allowed_actions"],
            "task.transition/v1",
        ]
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(bad_scope)
        self.assertEqual(
            raised.exception.code, "WORKER_CAPABILITY_FORBIDDEN"
        )

        bad_path = lease_spec()
        bad_path["approved_paths"] = ["../outside"]
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(bad_path)
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_PATH_INVALID"
        )

    def test_lease_credential_is_explicitly_non_mutating(
        self,
    ) -> None:
        credential = authority.worker_lease_credential(issue_lease())
        self.assertEqual(credential.mutation_authority, "none")
        self.assertNotIn(
            "manager", json.dumps(credential.as_dict(), sort_keys=True)
        )

        forged = credential.as_dict()
        forged["mutation_authority"] = "controller"
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_lease_credential(forged)
        self.assertEqual(
            raised.exception.code,
            "WORKER_MUTATION_AUTHORITY_FORBIDDEN",
        )


class ManagerCapabilityTests(unittest.TestCase):
    def test_issuance_persists_only_verifier_material(
        self,
    ) -> None:
        secret = b"this-is-a-32-byte-manager-secret!!"
        self.assertGreaterEqual(len(secret), 32)
        capability = issue_capability(secret=secret)
        persistent = capability.as_persistent_dict()
        serialized = json.dumps(persistent, sort_keys=True)

        self.assertNotIn(secret.hex(), serialized)
        self.assertNotIn(secret.decode("ascii"), serialized)
        self.assertNotIn("manager_secret", persistent)
        self.assertNotIn(secret.hex(), repr(capability))
        self.assertRegex(
            persistent["verifier_hmac_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            authority.validate_manager_capability_verifier(
                persistent
            ),
            capability,
        )

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_capability(secret=b"short")
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_SECRET_TOO_SHORT",
        )

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.issue_manager_capability(
                task_id="task-7",
                issued_for_task_revision=41,
                manager_session_id="manager-session-7",
                allowed_actions=["action.apply/v1"],
                ttl_ns=20_000,
                wall_time_ns=2_000_000,
                monotonic_time_ns=80_000,
                clock_id="boot-7",
                secret_transport="argv",
                operator_confirmation_sha256=digest("e"),
                issuance_audit_sha256=digest("f"),
                manager_secret=b"M" * 32,
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_SECRET_TRANSPORT_FORBIDDEN",
        )

    def test_valid_request_consumes_nonce_and_replay_fails_closed(
        self,
    ) -> None:
        secret = b"M" * 32
        capability = issue_capability(secret=secret)
        request = manager_request(capability)
        authorization = authority.consume_manager_capability_request(
            capability,
            request,
            principal(),
            manager_secret=secret,
            wall_time_ns=2_005_000,
            monotonic_time_ns=85_000,
            clock_id="boot-7",
        )

        self.assertEqual(authorization.action_id, request["action_id"])
        self.assertEqual(
            len(
                authorization.verifier_state
                .used_request_nonce_sha256s
            ),
            1,
        )
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.consume_manager_capability_request(
                authorization.verifier_state,
                request,
                principal(),
                manager_secret=secret,
                wall_time_ns=2_005_001,
                monotonic_time_ns=85_001,
                clock_id="boot-7",
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_REQUEST_REPLAYED",
        )

    def test_committed_request_receipt_recovery_reauthenticates_without_mutation(
        self,
    ) -> None:
        secret = bytearray(b"M" * 32)
        capability = issue_capability(secret=secret)
        request = manager_request(capability)
        consumed = authority.consume_manager_capability_request(
            capability,
            request,
            principal(),
            manager_secret=secret,
            wall_time_ns=2_005_000,
            monotonic_time_ns=85_000,
            clock_id="boot-7",
        )
        revoked = authority.revoke_manager_capability(
            consumed.verifier_state,
            revoked_at_wall_ns=2_006_000,
            reason="operator-revoked",
            revocation_audit_sha256=digest("e"),
        )

        recovered = (
            authority.verify_manager_capability_replay_request(
                revoked,
                request,
                principal(),
                manager_secret=secret,
            )
        )

        self.assertEqual(
            recovered.authorization_id,
            consumed.authorization_id,
        )
        self.assertEqual(recovered.verifier_state, revoked)
        self.assertEqual(
            recovered.verifier_state.used_request_nonce_sha256s,
            consumed.verifier_state.used_request_nonce_sha256s,
        )

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.verify_manager_capability_replay_request(
                revoked,
                request,
                principal(),
                manager_secret=bytearray(b"X" * 32),
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_PROOF_INVALID",
        )

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.verify_manager_capability_replay_request(
                revoked,
                manager_request(
                    capability, nonce=digest("c")
                ),
                principal(),
                manager_secret=secret,
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_REQUEST_NOT_COMMITTED",
        )

        distinct = manager_request(capability, nonce=digest("b"))
        second = authority.consume_manager_capability_request(
            consumed.verifier_state,
            distinct,
            principal(),
            manager_secret=secret,
            wall_time_ns=2_005_002,
            monotonic_time_ns=85_002,
            clock_id="boot-7",
        )
        self.assertEqual(
            len(second.verifier_state.used_request_nonce_sha256s),
            2,
        )

        reused_nonce = manager_request(
            capability,
            action_id="action.apply/v1",
            nonce=distinct["request_nonce"],
        )
        reused_nonce["expected_revision"] = 99
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.consume_manager_capability_request(
                second.verifier_state,
                reused_nonce,
                principal(),
                manager_secret=secret,
                wall_time_ns=2_005_003,
                monotonic_time_ns=85_003,
                clock_id="boot-7",
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_REQUEST_REPLAYED",
        )

    def test_capability_scope_expiry_revocation_and_proof_are_exact(
        self,
    ) -> None:
        secret = b"M" * 32
        capability = issue_capability(secret=secret)
        cases = (
            (
                manager_request(
                    capability, task_id="another-task"
                ),
                secret,
                2_001_000,
                81_000,
                "MANAGER_CAPABILITY_TASK_MISMATCH",
            ),
            (
                manager_request(
                    capability, action_id="task.cancel/v1"
                ),
                secret,
                2_001_000,
                81_000,
                "MANAGER_CAPABILITY_ACTION_DENIED",
            ),
            (
                manager_request(capability),
                b"X" * 32,
                2_001_000,
                81_000,
                "MANAGER_CAPABILITY_PROOF_INVALID",
            ),
            (
                manager_request(capability),
                secret,
                capability.expires_at_wall_ns,
                100_000,
                "MANAGER_CAPABILITY_EXPIRED",
            ),
            (
                manager_request(capability),
                secret,
                capability.issued_at_wall_ns - 1,
                capability.issued_at_monotonic_ns,
                "MANAGER_CAPABILITY_CLOCK_ROLLBACK",
            ),
        )
        for request, proof, wall, monotonic, code in cases:
            with self.subTest(code=code):
                with self.assertRaises(
                    authority.OrchestrationAuthorityError
                ) as raised:
                    authority.consume_manager_capability_request(
                        capability,
                        request,
                        principal(),
                        manager_secret=proof,
                        wall_time_ns=wall,
                        monotonic_time_ns=monotonic,
                        clock_id="boot-7",
                    )
                self.assertEqual(raised.exception.code, code)

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.consume_manager_capability_request(
                capability,
                manager_request(capability),
                principal(),
                manager_secret=secret,
                wall_time_ns=2_001_000,
                monotonic_time_ns=81_000,
                clock_id="different-boot",
            )
        self.assertEqual(
            raised.exception.code,
            "MANAGER_CAPABILITY_CLOCK_CONTEXT_MISMATCH",
        )

        revoked = authority.revoke_manager_capability(
            capability,
            revoked_at_wall_ns=2_002_000,
            reason="operator-revoked/v1",
            revocation_audit_sha256=digest("d"),
        )
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.consume_manager_capability_request(
                revoked,
                manager_request(revoked),
                principal(),
                manager_secret=secret,
                wall_time_ns=2_003_000,
                monotonic_time_ns=83_000,
                clock_id="boot-7",
            )
        self.assertEqual(
            raised.exception.code, "MANAGER_CAPABILITY_REVOKED"
        )

    def test_same_os_user_worker_is_denied_before_proof_use(self) -> None:
        secret = b"M" * 32
        capability = issue_capability(secret=secret)
        same_user = principal(
            role="worker",
            session_id="worker-session-api-1",
            os_user_identity_sha256=digest("1"),
        )
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.consume_manager_capability_request(
                capability,
                manager_request(capability),
                same_user,
                manager_secret=secret,
                wall_time_ns=2_001_000,
                monotonic_time_ns=81_000,
                clock_id="boot-7",
            )
        self.assertEqual(
            raised.exception.code,
            "ORCHESTRATION_WORKER_MUTATION_DENIED",
        )
        self.assertEqual(
            capability.used_request_nonce_sha256s, ()
        )


class HostIsolationTests(unittest.TestCase):
    def test_host_attestation_enables_only_exact_parallel_scope(
        self,
    ) -> None:
        assignment = create_assignment()
        report = host_report(assignment)
        decision = authority.evaluate_host_isolation(
            report,
            assignment,
            trusted_adapter_ids=["native-subagent/v1"],
            protected_read_identity_sha256s=[
                digest("5"),
                digest("6"),
            ],
            mutating_tool_ids=[
                "action.apply/v1",
                "worker-result.submit/v1",
            ],
        )
        self.assertTrue(decision.parallel_dispatch_allowed)
        self.assertEqual(
            decision.dispatch_mode, "parallel-writable-worker"
        )
        self.assertEqual(decision.blocker_codes, ())

    def test_unproven_boundaries_fall_back_to_manager_serial(
        self,
    ) -> None:
        assignment = create_assignment()
        cases = (
            (
                {"manager_secret_channel_excluded": False},
                "HOST_MANAGER_SECRET_NOT_EXCLUDED",
            ),
            (
                {"controller_state_excluded": False},
                "HOST_CONTROLLER_STATE_NOT_EXCLUDED",
            ),
            (
                {"mutation_tools_excluded": False},
                "HOST_MUTATION_TOOLS_NOT_EXCLUDED",
            ),
            (
                {"host_enforced": False},
                "HOST_BOUNDARY_NOT_ENFORCED",
            ),
            (
                {"allowed_write_identity_sha256s": [digest("9")]},
                "HOST_WRITE_SCOPE_NOT_EXACT",
            ),
        )
        for updates, code in cases:
            with self.subTest(code=code):
                report = host_report(assignment)
                report.update(updates)
                decision = authority.evaluate_host_isolation(
                    report,
                    assignment,
                    trusted_adapter_ids=["native-subagent/v1"],
                    protected_read_identity_sha256s=[
                        digest("5"),
                        digest("6"),
                    ],
                    mutating_tool_ids=[
                        "action.apply/v1",
                        "worker-result.submit/v1",
                    ],
                )
                self.assertFalse(
                    decision.parallel_dispatch_allowed
                )
                self.assertEqual(
                    decision.dispatch_mode, "manager-serial"
                )
                self.assertIn(code, decision.blocker_codes)

        decision = authority.evaluate_host_isolation(
            host_report(assignment),
            assignment,
            trusted_adapter_ids=["different-adapter/v1"],
            protected_read_identity_sha256s=[
                digest("5"),
                digest("6"),
            ],
            mutating_tool_ids=[
                "action.apply/v1",
                "worker-result.submit/v1",
            ],
        )
        self.assertIn(
            "HOST_ADAPTER_UNTRUSTED", decision.blocker_codes
        )


class WorkerLeaseTests(unittest.TestCase):
    def test_lease_exclusivity_blocks_node_or_worktree_until_quiesced(
        self,
    ) -> None:
        first = issue_lease()
        same_node = lease_spec(worktree_identity_sha256=digest("8"))
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(same_node, nonce=b"N" * 32, existing=(first,))
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_EXCLUSIVE_CONFLICT"
        )

        same_worktree = lease_spec(
            node_instance_id="map.impl:web:3",
            repository_id="web",
            repository_identity_sha256=digest("7"),
        )
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(
                same_worktree, nonce=b"O" * 32, existing=(first,)
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_EXCLUSIVE_CONFLICT"
        )

        distinct = lease_spec(
            node_instance_id="map.impl:web:3",
            repository_id="web",
            repository_identity_sha256=digest("7"),
            worktree_identity_sha256=digest("8"),
        )
        second = issue_lease(
            distinct, nonce=b"P" * 32, existing=(first,)
        )
        self.assertNotEqual(first.lease_id, second.lease_id)

    def test_expiry_and_revocation_never_imply_quiescence(
        self,
    ) -> None:
        lease = issue_lease()
        status = authority.worker_lease_status(
            lease,
            wall_time_ns=lease.expires_at_wall_ns,
            monotonic_time_ns=lease.issued_at_monotonic_ns
            + lease.ttl_ns,
            clock_id=lease.clock_id,
        )
        self.assertEqual(status.effective_state, "EXPIRED")
        self.assertFalse(status.authorized)
        self.assertFalse(status.quiesced)

        expired = authority.expire_worker_lease(
            lease,
            wall_time_ns=lease.expires_at_wall_ns,
            monotonic_time_ns=lease.issued_at_monotonic_ns
            + lease.ttl_ns,
            clock_id=lease.clock_id,
        )
        self.assertEqual(expired.state, "EXPIRED")
        self.assertIsNone(expired.quiesced_at_wall_ns)

        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(
                lease_spec(),
                nonce=b"Q" * 32,
                wall=lease.expires_at_wall_ns + 1,
                monotonic=lease.issued_at_monotonic_ns
                + lease.ttl_ns
                + 1,
                existing=(expired,),
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_EXCLUSIVE_CONFLICT"
        )

        revoked = authority.revoke_worker_lease(
            lease,
            revoked_at_wall_ns=lease.issued_at_wall_ns + 1,
            reason="cancel-requested/v1",
        )
        self.assertEqual(revoked.state, "REVOKED")
        self.assertIsNone(revoked.quiesced_at_wall_ns)
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            issue_lease(
                lease_spec(),
                nonce=b"R" * 32,
                wall=lease.issued_at_wall_ns + 2,
                monotonic=lease.issued_at_monotonic_ns + 2,
                existing=(revoked,),
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_EXCLUSIVE_CONFLICT"
        )

    def test_candidate_validation_rejects_stale_or_inactive_attempt(
        self,
    ) -> None:
        lease = issue_lease()
        valid = {
            "task_id": lease.task_id,
            "node_instance_id": lease.node_instance_id,
            "repository_id": lease.repository_id,
            "worktree_identity_sha256": (
                lease.worktree_identity_sha256
            ),
            "attempt": lease.attempt,
            "lease_nonce": lease.lease_nonce,
            "current_attempt": lease.attempt,
            "wall_time_ns": lease.issued_at_wall_ns + 1,
            "monotonic_time_ns": (
                lease.issued_at_monotonic_ns + 1
            ),
            "clock_id": lease.clock_id,
        }
        self.assertEqual(
            authority.validate_worker_lease_candidate(
                lease, **valid
            ),
            lease,
        )

        stale = dict(valid)
        stale["current_attempt"] = 2
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_lease_candidate(
                lease, **stale
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_STALE_ATTEMPT"
        )

        revoked = authority.revoke_worker_lease(
            lease,
            revoked_at_wall_ns=lease.issued_at_wall_ns + 1,
            reason="superseded/v1",
        )
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_lease_candidate(
                revoked, **valid
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_REVOKED"
        )

    def test_records_are_frozen_and_strictly_versioned(self) -> None:
        lease = issue_lease()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            lease.state = "REVOKED"

        unknown = lease.as_dict()
        unknown["surprise"] = True
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_lease(unknown)
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_UNKNOWN_FIELD"
        )

        wrong_version = lease.as_dict()
        wrong_version["schema"] = "dev-flow-worker-lease/v2"
        with self.assertRaises(
            authority.OrchestrationAuthorityError
        ) as raised:
            authority.validate_worker_lease(wrong_version)
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_SCHEMA_UNSUPPORTED"
        )

        for invalid_nonce in (b"N" * 31, b"N" * 33):
            with self.subTest(nonce_bytes=len(invalid_nonce)):
                with self.assertRaises(
                    authority.OrchestrationAuthorityError
                ) as raised:
                    issue_lease(nonce=invalid_nonce)
                self.assertEqual(
                    raised.exception.code,
                    "WORKER_LEASE_NONCE_INVALID",
                )


if __name__ == "__main__":
    unittest.main()
