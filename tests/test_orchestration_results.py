from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "orchestration_results.py"
)
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_orchestration_results_tests", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
orchestration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestration
SPEC.loader.exec_module(orchestration)


def digest(character: str) -> str:
    return hashlib.sha256(character.encode("utf-8")).hexdigest()


def content_id(kind: str, value: str) -> str:
    return f"{kind}:{digest(value)}"


def result_payload(
    *,
    node_instance_id: str = "node-api",
    repository_id: str = "api",
    outcome: str = "SUCCEEDED",
    blockers: list[str] | None = None,
    drift: bool = False,
) -> dict[str, object]:
    return {
        "schema": orchestration.ORCHESTRATION_NODE_RESULT_SCHEMA,
        "task_id": "task-1",
        "workflow_bundle_sha256": digest("b"),
        "map_epoch": 3,
        "repository_id": repository_id,
        "node_instance_id": node_instance_id,
        "attempt": 1,
        "assignment_id": content_id(
            "worker-assignment", f"assignment-{repository_id}"
        ),
        "lease_id": content_id(
            "worker-lease", f"lease-{repository_id}"
        ),
        "lease_nonce": digest(f"nonce-{repository_id}"),
        "input_sha256": digest("i"),
        "output_sha256": digest("o"),
        "worktree_sha256": digest("g"),
        "changed_paths_sha256": digest("h"),
        "verification_sha256": digest("v"),
        "outcome": outcome,
        "summary": f"{repository_id} result",
        "blockers": blockers or [],
        "plan_drift": {
            "detected": drift,
            "reasons": ["plan/path-out-of-scope"] if drift else [],
        },
        "artifact_refs": [
            {
                "id": f"artifact-{repository_id}",
                "semantic_sha256": digest("artifact-contract"),
                "sha256": digest("r"),
                "size": 321,
                "kind": "application.json",
                "locator": f"artifact-{repository_id}",
            }
        ],
        "evidence_refs": [
            {
                "id": f"evidence-{repository_id}",
                "semantic_sha256": digest("e"),
                "sha256": digest("r"),
                "size": 321,
                "kind": "test.report.v1",
                "locator": f"evidence-{repository_id}",
            }
        ],
        "runtime_handle": f"runtime-{repository_id}",
    }


def bound_result(**kwargs: object) -> dict[str, object]:
    return dict(
        orchestration._orchestration_thaw(
            orchestration.bind_node_result_identity(
                result_payload(**kwargs)
            )
        )
    )


def expectation(
    *,
    repository_id: str = "api",
    node_instance_id: str = "node-api",
    lease_active: bool = True,
) -> dict[str, object]:
    return {
        "schema": orchestration.NODE_RESULT_EXPECTATION_SCHEMA,
        "task_id": "task-1",
        "workflow_bundle_sha256": digest("b"),
        "plan_id": "plan-1",
        "plan_artifact_sha256": digest("p"),
        "dag_sha256": digest("d"),
        "semantic_input_sha256": digest("s"),
        "map_epoch": 3,
        "repository_id": repository_id,
        "repository_identity_sha256": (
            digest("a") if repository_id == "api" else digest("w")
        ),
        "node_instance_id": node_instance_id,
        "attempt": 1,
        "assignment_revision": 7,
        "assignment_id": content_id(
            "worker-assignment", f"assignment-{repository_id}"
        ),
        "assignment_sha256": digest("n"),
        "lease_id": content_id(
            "worker-lease", f"lease-{repository_id}"
        ),
        "lease_nonce": digest(f"nonce-{repository_id}"),
        "input_sha256": digest("i"),
        "interface_contract_sha256": [digest("c")],
        "input_worktree_fingerprint_sha256": digest("f"),
        "actor_id": f"worker-{repository_id}",
        "host_assignment_id": f"host-{repository_id}",
        "runtime_handle_id": f"runtime-{repository_id}",
        "lease_active": lease_active,
    }


def verified_output(
    *,
    repository_id: str = "api",
) -> dict[str, object]:
    return {
        "schema": orchestration.NODE_RESULT_VERIFIED_OUTPUT_SCHEMA,
        "output_sha256": digest("o"),
        "worktree_sha256": digest("g"),
        "changed_paths_sha256": digest("h"),
        "verification_sha256": digest("v"),
        "artifacts": {
            f"artifact-{repository_id}": digest("r")
        },
        "evidence": {
            f"evidence-{repository_id}": {
                "sha256": digest("r"),
                "semantic_sha256": digest("e"),
                "size": 321,
                "kind": "test.report.v1",
                "locator": f"evidence-{repository_id}",
                "current": True,
            }
        },
    }


def accepted_result(
    result: dict[str, object],
    *,
    current: bool = True,
    accepted: bool = True,
    lease_quiesced: bool = True,
    runtime_live: bool = False,
) -> dict[str, object]:
    return {
        "schema": orchestration.ACCEPTED_NODE_RESULT_SCHEMA,
        "accepted": accepted,
        "current": current,
        "repository_evidence_sha256": digest("z"),
        "lease_quiesced": lease_quiesced,
        "runtime_live": runtime_live,
        "result": result,
    }


def barrier() -> dict[str, object]:
    return {
        "schema": orchestration.RESULT_BARRIER_SCHEMA,
        "barrier_id": "barrier-1",
        "task_id": "task-1",
        "workflow_bundle_sha256": digest("b"),
        "plan_id": "plan-1",
        "dag_sha256": digest("d"),
        "map_epoch": 3,
        "node_instance_id": "join-1",
        "members": [
            {
                "node_instance_id": "node-api",
                "repository_id": "api",
                "required": True,
                "allowed_outcomes": ["SUCCEEDED"],
            },
            {
                "node_instance_id": "node-web",
                "repository_id": "web",
                "required": True,
                "allowed_outcomes": ["SUCCEEDED"],
            },
        ],
    }


def lease(
    *,
    status: str = "ACTIVE",
    attempt: int = 1,
    expires: int = 2_000_000_000,
) -> dict[str, object]:
    return {
        "schema": orchestration.RUNTIME_LEASE_STATE_SCHEMA,
        "lease_id": content_id("worker-lease", "lease-api"),
        "task_id": "task-1",
        "workflow_bundle_sha256": digest("b"),
        "plan_id": "plan-1",
        "dag_sha256": digest("d"),
        "map_epoch": 3,
        "repository_id": "api",
        "repository_identity_sha256": digest("a"),
        "node_instance_id": "node-api",
        "attempt": attempt,
        "assignment_id": "assignment-api",
        "assignment_sha256": digest("n"),
        "input_sha256": digest("i"),
        "worktree_identity_sha256": digest("stable-worktree"),
        "worktree_fingerprint_sha256": digest("f"),
        "repository_common_dir_sha256": digest("m"),
        "ownership_claim_sha256": digest("q"),
        "runtime_handle_id": "runtime-api",
        "host_assignment_id": "host-api",
        "runtime_authentication_sha256": digest("9"),
        "status": status,
        "writable": True,
        "issued_monotonic_ns": 100,
        "expires_monotonic_ns": expires,
        "clock_id": "clock-1",
    }


def stop_observation(
    *,
    authentication_sha256: str | None = None,
    stopped: bool = True,
) -> dict[str, object]:
    return {
        "schema": orchestration.RUNTIME_STOP_OBSERVATION_SCHEMA,
        "task_id": "task-1",
        "node_instance_id": "node-api",
        "attempt": 1,
        "assignment_id": "assignment-api",
        "lease_id": content_id("worker-lease", "lease-api"),
        "runtime_handle_id": "runtime-api",
        "host_assignment_id": "host-api",
        "authentication_sha256": (
            authentication_sha256 or digest("9")
        ),
        "stopped": stopped,
    }


def snapshot(
    *,
    fingerprint: str | None = None,
    active_writer: bool = False,
    mutation_quarantine: bool = False,
) -> dict[str, object]:
    return {
        "schema": orchestration.WORKTREE_POSTCONDITION_SCHEMA,
        "repository_id": "api",
        "repository_identity_sha256": digest("a"),
        "initial_worktree_fingerprint_sha256": digest("f"),
        "worktree_fingerprint_sha256": (
            fingerprint or digest("g")
        ),
        "repository_common_dir_sha256": digest("m"),
        "ownership_claim_sha256": digest("q"),
        "git_state_sha256": digest("j"),
        "changed_paths_sha256": digest("h"),
        "complete": True,
        "active_writer": active_writer,
        "mutation_quarantine": mutation_quarantine,
    }


def recovery_observation(
    *,
    found: bool,
    authenticated: bool,
    live: bool,
    fingerprint: str | None = None,
) -> dict[str, object]:
    return {
        "schema": (
            orchestration.RUNTIME_RECOVERY_OBSERVATION_SCHEMA
        ),
        "task_id": "task-1",
        "node_instance_id": "node-api",
        "attempt": 1,
        "assignment_id": "assignment-api",
        "lease_id": content_id("worker-lease", "lease-api"),
        "runtime_handle_id": "runtime-api",
        "host_assignment_id": "host-api",
        "found": found,
        "authenticated": authenticated,
        "live": live,
        "worktree_fingerprint_sha256": (
            fingerprint or digest("f")
        ),
    }


class NodeResultContractTests(unittest.TestCase):
    def test_result_identity_is_content_addressed_and_deeply_immutable(
        self,
    ) -> None:
        first = orchestration.bind_node_result_identity(
            result_payload()
        )
        second = orchestration.bind_node_result_identity(
            result_payload()
        )

        self.assertEqual(first["result_id"], second["result_id"])
        self.assertEqual(
            first["result_id"],
            "node-result-"
            + orchestration.node_result_content_sha256(first),
        )
        self.assertEqual(
            orchestration.canonical_node_result_bytes(first),
            orchestration.canonical_node_result_bytes(second),
        )
        with self.assertRaises(TypeError):
            first["outcome"] = "FAILED"
        with self.assertRaises(TypeError):
            first["plan_drift"]["detected"] = True
        self.assertLessEqual(
            len(orchestration.canonical_node_result_bytes(first)),
            orchestration.NODE_RESULT_BUDGET,
        )

    def test_result_budget_rejects_without_truncating_required_detail(
        self,
    ) -> None:
        payload = result_payload()
        payload["summary"] = "x" * 500
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.bind_node_result_identity(payload)
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_BUDGET_EXCEEDED"
        )
        self.assertEqual(payload["summary"], "x" * 500)

    def test_all_bundles_publish_the_same_authoritative_schema(
        self,
    ) -> None:
        schemas = []
        for bundle in (
            "full-v3",
            "lite-v3",
            "full-legacy-v2",
            "lite-legacy-v2",
        ):
            schemas.append(
                json.loads(
                    (
                        ROOT
                        / "workflows"
                        / "bundles"
                        / bundle
                        / "schemas"
                        / "node-result.json"
                    ).read_text(encoding="utf-8")
                )
            )
        self.assertTrue(
            all(schema == schemas[0] for schema in schemas[1:])
        )
        self.assertEqual(schemas[0]["$id"], "dev-flow-node-result/v1")
        self.assertEqual(
            schemas[0]["x-canonicalUtf8MaxBytes"], 2048
        )
        self.assertEqual(
            set(schemas[0]["required"]),
            set(orchestration._orchestration_node_result_fields),
        )

    def test_result_schema_artifact_evidence_and_plan_drift_are_strict(
        self,
    ) -> None:
        payload = result_payload()
        payload["future"] = True
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.bind_node_result_identity(payload)
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_UNKNOWN_FIELD"
        )

        payload = result_payload()
        payload["evidence_refs"][0]["future"] = True
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.bind_node_result_identity(payload)
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_REFERENCE_INVALID",
        )

        payload = result_payload(drift=True)
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.bind_node_result_identity(payload)
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_PLAN_DRIFT_OUTCOME_INVALID",
        )

        payload = result_payload()
        payload["schema"] = "dev-flow-node-result/v2"
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.bind_node_result_identity(payload)
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_SCHEMA_UNSUPPORTED"
        )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.parse_node_result_json(
                b'{"schema":"x","schema":"y"}'
            )
        self.assertEqual(
            raised.exception.code, "ORCHESTRATION_DUPLICATE_KEY"
        )

    def test_acceptance_binds_all_context_and_verified_outputs(
        self,
    ) -> None:
        result = bound_result()

        candidate = orchestration.evaluate_node_result_acceptance(
            result,
            expected_revision=8,
            current_revision=8,
            expected_bindings=expectation(),
            verified_output=verified_output(),
        )

        self.assertEqual(candidate.disposition, "ACCEPT")
        self.assertEqual(candidate.expected_revision, 8)
        self.assertEqual(candidate.candidate_revision, 9)

        drifted = expectation()
        drifted["map_epoch"] = 4
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                result,
                expected_revision=8,
                current_revision=8,
                expected_bindings=drifted,
                verified_output=verified_output(),
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_PLAN_DRIFT"
        )

        contract_drift = expectation()
        contract_drift["assignment_id"] = content_id(
            "worker-assignment", "changed-contract-assignment"
        )
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                result,
                expected_revision=8,
                current_revision=8,
                expected_bindings=contract_drift,
                verified_output=verified_output(),
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_BINDING_MISMATCH"
        )

        output_drift = verified_output()
        output_drift["worktree_sha256"] = digest("x")
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                result,
                expected_revision=8,
                current_revision=8,
                expected_bindings=expectation(),
                verified_output=output_drift,
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_WORKTREE_DRIFT"
        )

    def test_acceptance_supports_assignment_without_runtime_handle(
        self,
    ) -> None:
        result_value = result_payload()
        result_value["runtime_handle"] = None
        expected = expectation()
        expected["runtime_handle_id"] = None

        candidate = orchestration.evaluate_node_result_acceptance(
            orchestration.bind_node_result_identity(result_value),
            expected_revision=8,
            current_revision=8,
            expected_bindings=expected,
            verified_output=verified_output(),
        )

        self.assertEqual(candidate.disposition, "ACCEPT")
        self.assertIsNone(candidate.result["runtime_handle"])

    def test_idempotency_precedes_cas_and_conflicting_id_fails_closed(
        self,
    ) -> None:
        result = bound_result()
        history = {
            result["result_id"]: {
                "result": result,
                "receipt": {
                    "accepted_revision": 9,
                    "event_id": "event-1",
                },
            }
        }

        replay = orchestration.evaluate_node_result_acceptance(
            result,
            expected_revision=8,
            current_revision=9,
            expected_bindings=expectation(lease_active=False),
            verified_output=verified_output(),
            observed_results=history,
        )

        self.assertEqual(replay.disposition, "IDEMPOTENT")
        self.assertEqual(replay.candidate_revision, 9)
        self.assertEqual(
            replay.prior_receipt["accepted_revision"], 9
        )

        conflict = copy.deepcopy(result)
        conflict["summary"] = "different canonical content"
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                conflict,
                expected_revision=9,
                current_revision=9,
                expected_bindings=expectation(),
                verified_output=verified_output(),
                observed_results=history,
            )
        self.assertEqual(
            raised.exception.code,
            "NODE_RESULT_IDEMPOTENCY_CONFLICT",
        )

    def test_revision_late_output_and_reported_plan_drift_are_separate(
        self,
    ) -> None:
        result = bound_result()
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                result,
                expected_revision=7,
                current_revision=8,
                expected_bindings=expectation(),
                verified_output=verified_output(),
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_REVISION_CONFLICT"
        )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_node_result_acceptance(
                result,
                expected_revision=8,
                current_revision=8,
                expected_bindings=expectation(
                    lease_active=False
                ),
                verified_output=verified_output(),
            )
        self.assertEqual(
            raised.exception.code, "NODE_RESULT_LATE_OR_ORPHANED"
        )

        drift_result = bound_result(
            outcome="BLOCKED",
            blockers=["plan/reapproval-required"],
            drift=True,
        )
        candidate = orchestration.evaluate_node_result_acceptance(
            drift_result,
            expected_revision=8,
            current_revision=8,
            expected_bindings=expectation(),
            verified_output=verified_output(),
        )
        self.assertEqual(candidate.disposition, "REPLAN_REQUIRED")


class BarrierContractTests(unittest.TestCase):
    def test_fan_in_is_complete_current_and_utf8_deterministic(
        self,
    ) -> None:
        api = bound_result()
        web = bound_result(
            node_instance_id="node-web",
            repository_id="web",
        )
        reverse_completion = {
            "node-web": accepted_result(web),
            "node-api": accepted_result(api),
        }
        forward_completion = {
            "node-api": accepted_result(api),
            "node-web": accepted_result(web),
        }

        reverse = orchestration.evaluate_result_barrier(
            barrier(), reverse_completion
        )
        forward = orchestration.evaluate_result_barrier(
            barrier(), forward_completion
        )

        self.assertEqual(reverse.status, "CLOSED")
        self.assertEqual(
            reverse.aggregate["barrier_sha256"],
            forward.aggregate["barrier_sha256"],
        )
        self.assertEqual(
            [
                item["node_instance_id"]
                for item in reverse.aggregate["members"]
            ],
            ["node-api", "node-web"],
        )
        self.assertEqual(len(reverse.current_results), 2)
        with self.assertRaises(TypeError):
            reverse.aggregate["members"][0]["result_id"] = "other"

    def test_failed_or_nonquiesced_member_keeps_barrier_open(
        self,
    ) -> None:
        api = bound_result()
        web = bound_result(
            node_instance_id="node-web",
            repository_id="web",
            outcome="FAILED",
            blockers=["tests/failed"],
        )
        evaluation = orchestration.evaluate_result_barrier(
            barrier(),
            {
                "node-api": accepted_result(api),
                "node-web": accepted_result(
                    web,
                    lease_quiesced=False,
                    runtime_live=True,
                ),
            },
        )

        self.assertEqual(evaluation.status, "OPEN")
        self.assertEqual(evaluation.aggregate, None)
        self.assertEqual(len(evaluation.current_results), 2)
        self.assertEqual(
            evaluation.current_results[1]["node_instance_id"],
            "node-web",
        )
        self.assertIn(
            "RUNTIME_STILL_LIVE",
            evaluation.current_results[1]["blocker_codes"],
        )
        self.assertEqual(
            evaluation.blockers[0].codes,
            (
                "LEASE_NOT_QUIESCED",
                "RESULT_OUTCOME_NOT_ALLOWED",
                "RUNTIME_STILL_LIVE",
            ),
        )

    def test_invalidation_reopens_closed_barrier_and_names_member(
        self,
    ) -> None:
        api = bound_result()
        web = bound_result(
            node_instance_id="node-web",
            repository_id="web",
        )
        records = {
            "node-api": accepted_result(api),
            "node-web": accepted_result(web),
        }
        closed = orchestration.evaluate_result_barrier(
            barrier(), records
        )
        records["node-api"] = accepted_result(
            api, current=False
        )

        reopened = orchestration.evaluate_result_barrier(
            barrier(),
            records,
            previous_aggregate=closed.aggregate,
            dependent_result_ids=[
                "integration-result",
                "review-result",
            ],
        )

        self.assertEqual(reopened.status, "REOPENED")
        self.assertEqual(
            reopened.invalidated_node_instance_ids, ("node-api",)
        )
        self.assertEqual(
            reopened.dependent_result_ids_to_invalidate,
            ("integration-result", "review-result"),
        )
        self.assertIn(
            "RESULT_STALE", reopened.blockers[0].codes
        )


class LeaseAndRecoveryKernelTests(unittest.TestCase):
    def test_timeout_and_cancellation_requested_do_not_claim_quiescence(
        self,
    ) -> None:
        timeout = orchestration.evaluate_lease_timeout(
            lease(),
            monotonic_ns=lambda: 3_000_000_000,
            clock_id="clock-1",
        )
        self.assertTrue(timeout.expired)
        self.assertFalse(timeout.authorization_active)
        self.assertTrue(timeout.cancellation_requested)
        self.assertFalse(timeout.quiesced)
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.evaluate_lease_timeout(
                lease(),
                monotonic_ns=lambda: 3_000_000_000,
                clock_id="after-reboot",
            )
        self.assertEqual(
            raised.exception.code, "MONOTONIC_CLOCK_ID_MISMATCH"
        )

        cancellation = orchestration.build_cancellation_candidate(
            [lease()],
            expected_revision=10,
            current_revision=10,
            approval_current=True,
        )
        self.assertTrue(cancellation.requested)
        self.assertFalse(cancellation.quiesced)
        self.assertEqual(
            cancellation.lease_ids_to_revoke,
            (content_id("worker-lease", "lease-api"),),
        )
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.build_cancellation_candidate(
                [lease()],
                expected_revision=9,
                current_revision=10,
                approval_current=True,
            )
        self.assertEqual(
            raised.exception.code,
            "CANCELLATION_REVISION_CONFLICT",
        )

    def test_runtime_stop_requires_exact_authentication_and_postcondition(
        self,
    ) -> None:
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.authenticate_runtime_stop(
                lease(),
                stop_observation(
                    authentication_sha256=digest("8")
                ),
                authentication_verifier=(
                    lambda _lease, _observation: True
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_STOP_AUTHENTICATION_FAILED",
        )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.authenticate_runtime_stop(
                lease(),
                stop_observation(),
                authentication_verifier=(
                    lambda _lease, _observation: False
                ),
            )
        self.assertEqual(
            raised.exception.code,
            "RUNTIME_STOP_AUTHENTICATION_FAILED",
        )

        authenticated = orchestration.authenticate_runtime_stop(
            lease(),
            stop_observation(),
            authentication_verifier=(
                lambda _lease, _observation: True
            ),
        )
        proof = orchestration.prove_quiescence_from_runtime_stop(
            lease(status="REVOKED"),
            authenticated,
            snapshot(),
        )
        self.assertTrue(proof.quiesced)
        self.assertEqual(
            proof.method, "authenticated-runtime-stop"
        )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.prove_quiescence_from_runtime_stop(
                lease(status="REVOKED"),
                authenticated,
                snapshot(active_writer=True),
            )
        self.assertEqual(
            raised.exception.code, "WORKTREE_ACTIVE_WRITER"
        )

    def test_absent_runtime_handle_uses_recovery_not_authenticated_stop(
        self,
    ) -> None:
        no_handle = lease()
        no_handle["runtime_handle_id"] = None
        stop = stop_observation()
        stop["runtime_handle_id"] = None
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.authenticate_runtime_stop(
                no_handle,
                stop,
                authentication_verifier=(
                    lambda _lease, _observation: True
                ),
            )
        self.assertEqual(
            raised.exception.code, "RUNTIME_STOP_HANDLE_REQUIRED"
        )

        recovery = recovery_observation(
            found=False,
            authenticated=False,
            live=False,
        )
        recovery["runtime_handle_id"] = None
        decision = orchestration.evaluate_runtime_recovery(
            no_handle,
            recovery,
            monotonic_ns=lambda: 1_000,
            clock_id="clock-1",
        )
        self.assertEqual(decision.status, "ORPHANED_UNCERTAIN")
        self.assertFalse(decision.reattach)

    def test_stable_reconciliation_rejects_zero_reduced_and_uncertain_stop(
        self,
    ) -> None:
        revoked = lease(status="REVOKED")
        for interval in (
            0,
            orchestration.KERNEL_MINIMUM_STABILITY_NS - 1,
        ):
            with self.subTest(interval=interval):
                with self.assertRaises(
                    orchestration.OrchestrationResultError
                ) as raised:
                    orchestration.begin_stable_reconciliation(
                        revoked,
                        snapshot(),
                        monotonic_ns=lambda: 100,
                        clock_id="reconciliation-clock",
                        required_stability_ns=interval,
                        reason="runtime-unobservable",
                        termination_confirmed=True,
                        operator_isolation_confirmed=False,
                        termination_evidence_sha256=digest("t"),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "STABILITY_INTERVAL_BELOW_KERNEL_MINIMUM",
                )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.begin_stable_reconciliation(
                revoked,
                snapshot(),
                monotonic_ns=lambda: 100,
                clock_id="reconciliation-clock",
                reason="termination-failed",
                termination_confirmed=False,
                operator_isolation_confirmed=False,
            )
        self.assertEqual(
            raised.exception.code,
            "TERMINATION_OR_ISOLATION_NOT_CONFIRMED",
        )

        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.begin_stable_reconciliation(
                revoked,
                snapshot(),
                monotonic_ns=lambda: 100,
                clock_id="reconciliation-clock",
                reason="unverified-termination",
                termination_confirmed=True,
                operator_isolation_confirmed=False,
            )
        self.assertEqual(
            raised.exception.code, "TERMINATION_EVIDENCE_INVALID"
        )

    def test_stable_reconciliation_needs_two_equal_complete_snapshots(
        self,
    ) -> None:
        revoked = lease(status="REVOKED")
        start = 10
        probe = orchestration.begin_stable_reconciliation(
            revoked,
            snapshot(),
            monotonic_ns=lambda: start,
            clock_id="reconciliation-clock",
            reason="runtime-handle-unavailable",
            termination_confirmed=True,
            operator_isolation_confirmed=False,
            termination_evidence_sha256=digest("t"),
        )
        too_soon = (
            start
            + orchestration.KERNEL_MINIMUM_STABILITY_NS
            - 1
        )
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.complete_stable_reconciliation(
                revoked,
                probe,
                snapshot(),
                monotonic_ns=lambda: too_soon,
                clock_id="reconciliation-clock",
            )
        self.assertEqual(
            raised.exception.code,
            "STABLE_RECONCILIATION_INTERVAL_INCOMPLETE",
        )

        finished = (
            start + orchestration.KERNEL_MINIMUM_STABILITY_NS
        )
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.complete_stable_reconciliation(
                revoked,
                probe,
                snapshot(fingerprint=digest("x")),
                monotonic_ns=lambda: finished,
                clock_id="reconciliation-clock",
            )
        self.assertEqual(
            raised.exception.code,
            "STABLE_RECONCILIATION_SNAPSHOT_CHANGED",
        )

        proof = orchestration.complete_stable_reconciliation(
            revoked,
            probe,
            snapshot(),
            monotonic_ns=lambda: finished,
            clock_id="reconciliation-clock",
        )
        self.assertTrue(proof.quiesced)
        self.assertEqual(
            proof.method, "stable-postcondition-reconciliation"
        )

    def test_recovery_reattaches_exact_runtime_but_orphans_uncertainty(
        self,
    ) -> None:
        reattach = orchestration.evaluate_runtime_recovery(
            lease(),
            recovery_observation(
                found=True, authenticated=True, live=True
            ),
            monotonic_ns=lambda: 1_000,
            clock_id="clock-1",
        )
        self.assertEqual(reattach.status, "REATTACH")
        self.assertTrue(reattach.reattach)
        self.assertFalse(reattach.replacement_allowed)

        orphan = orchestration.evaluate_runtime_recovery(
            lease(),
            recovery_observation(
                found=False, authenticated=False, live=False
            ),
            monotonic_ns=lambda: 1_000,
            clock_id="clock-1",
        )
        self.assertEqual(orphan.status, "ORPHANED_UNCERTAIN")
        self.assertIn("TERMINATION_UNCERTAIN", orphan.blockers)

        expired_live = orchestration.evaluate_runtime_recovery(
            lease(),
            recovery_observation(
                found=True, authenticated=True, live=True
            ),
            monotonic_ns=lambda: 3_000_000_000,
            clock_id="clock-1",
        )
        self.assertEqual(
            expired_live.status, "REVOKED_OR_EXPIRED_LIVE"
        )
        self.assertIn(
            "REVOKED_OR_EXPIRED_RUNTIME_LIVE",
            expired_live.blockers,
        )
        self.assertFalse(expired_live.replacement_allowed)

    def test_revocation_alone_denies_replacement_then_proof_allows_retry(
        self,
    ) -> None:
        revoked = lease(status="REVOKED")
        with self.assertRaises(
            orchestration.OrchestrationResultError
        ) as raised:
            orchestration.authorize_replacement_lease(
                revoked,
                None,
                next_attempt=2,
                worktree_strategy="resume-verified",
                worktree_fingerprint_sha256=digest("g"),
            )
        self.assertEqual(
            raised.exception.code,
            "REPLACEMENT_LEASE_QUIESCENCE_REQUIRED",
        )

        authenticated = orchestration.authenticate_runtime_stop(
            revoked,
            stop_observation(),
            authentication_verifier=(
                lambda _lease, _observation: True
            ),
        )
        proof = orchestration.prove_quiescence_from_runtime_stop(
            revoked, authenticated, snapshot()
        )
        replacement = orchestration.authorize_replacement_lease(
            revoked,
            proof,
            next_attempt=2,
            worktree_strategy="resume-verified",
            worktree_fingerprint_sha256=digest("g"),
        )
        self.assertTrue(replacement.authorized)

        failed = bound_result(
            outcome="FAILED", blockers=["tests/failed"]
        )
        retry = orchestration.build_retry_candidate(
            accepted_result(failed),
            revoked,
            proof,
            {
                "max_attempts": 3,
                "retryable_outcomes": ["BLOCKED", "FAILED"],
                "requires_approval": True,
            },
            expected_revision=11,
            current_revision=11,
            retry_approval_current=True,
            worktree_strategy="resume-verified",
            worktree_fingerprint_sha256=digest("g"),
        )
        self.assertEqual(retry.previous_attempt, 1)
        self.assertEqual(retry.next_attempt, 2)
        self.assertEqual(retry.candidate_revision, 12)

        cancellation = (
            orchestration.evaluate_cancellation_quiescence(
                [revoked],
                {content_id("worker-lease", "lease-api"): proof},
            )
        )
        self.assertTrue(cancellation.quiesced)

        status_only = lease(status="QUIESCED")
        status_only.update(
            {
                "lease_id": content_id("worker-lease", "lease-web"),
                "repository_id": "web",
                "repository_identity_sha256": digest("w"),
                "node_instance_id": "node-web",
                "assignment_id": "assignment-web",
                "worktree_identity_sha256": digest(
                    "stable-worktree-web"
                ),
                "repository_common_dir_sha256": digest("m-web"),
                "ownership_claim_sha256": digest("q-web"),
                "runtime_handle_id": "runtime-web",
                "host_assignment_id": "host-web",
            }
        )
        incomplete = orchestration.evaluate_cancellation_quiescence(
            [revoked, status_only],
            {content_id("worker-lease", "lease-api"): proof},
        )
        self.assertFalse(incomplete.quiesced)
        self.assertEqual(
            incomplete.uncertain_lease_ids,
            (content_id("worker-lease", "lease-web"),),
        )


if __name__ == "__main__":
    unittest.main()
