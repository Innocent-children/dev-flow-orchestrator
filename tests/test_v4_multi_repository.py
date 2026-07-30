from __future__ import annotations

import concurrent.futures
import copy
import hashlib
import json
import unittest

from tests.support import V4OrchestrationTestCase, runtime_services


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def content_id(kind: str, value: str) -> str:
    return f"{kind}:{digest(value)}"


def repository_plan() -> dict[str, object]:
    return {
        "schema": "dev-flow-repository-plan/v1",
        "task_id": "task-multi-1",
        "workflow_bundle_sha256": "d" * 64,
        "plan_id": "plan-multi-1",
        "map_node_id": "map.repositories/v1",
        "map_epoch": 3,
        "plan_input_revision": 11,
        "semantic_input_sha256": (
            "e2d5f93fe37437fb36b88151eae7ae2ef1155e84fde3b680d3a2dbb0755685b8"
        ),
        "repository_set": ["api", "docs", "web"],
        "repositories": [
            {
                "repository_id": "api",
                "identity_sha256": "1" * 64,
                "repository_path": "repositories/api",
                "approved_paths": ["src", "tests"],
                "write_policy": "scoped-write",
                "required_approval_ids": ["architecture/v1"],
                "required_evidence_contract_sha256": [],
            },
            {
                "repository_id": "docs",
                "identity_sha256": "2" * 64,
                "repository_path": "repositories/docs",
                "approved_paths": ["guides"],
                "write_policy": "read-only",
                "required_approval_ids": [],
                "required_evidence_contract_sha256": [],
            },
            {
                "repository_id": "web",
                "identity_sha256": "3" * 64,
                "repository_path": "repositories/web",
                "approved_paths": ["src", "tests"],
                "write_policy": "scoped-write",
                "required_approval_ids": [],
                "required_evidence_contract_sha256": ["c" * 64],
            },
        ],
        "interface_contracts": [
            {
                "contract_id": "contract.api-output/v1",
                "artifact_id": "artifact-api-output-v1",
                "sha256": "a" * 64,
            },
            {
                "contract_id": "contract.integration/v1",
                "artifact_id": "artifact-integration-v1",
                "sha256": "b" * 64,
            },
            {
                "contract_id": "contract.web-input/v1",
                "artifact_id": "artifact-web-input-v1",
                "sha256": "c" * 64,
            },
        ],
        "dependencies": [
            {
                "edge_id": "edge.api-web/v1",
                "from_repository_id": "api",
                "to_repository_id": "web",
                "input_contract_sha256": "c" * 64,
                "output_contract_sha256": "a" * 64,
                "required_evidence_contract_sha256": ["a" * 64],
            }
        ],
        "worktree_policy": {
            "mode": "controller-owned",
            "require_clean": True,
            "distinct": True,
        },
        "concurrency_policy": {
            "max_workers": 3,
            "max_writable_workers": 2,
        },
        "retry_policy": {
            "max_attempts": 2,
            "retryable_states": ["BLOCKED", "FAILED"],
            "requires_approval": True,
        },
        "integration_policy": {
            "commands": [["python3", "-m", "unittest"]],
            "evidence_contract_sha256": ["b" * 64],
        },
    }


def lease_spec() -> dict[str, object]:
    return {
        "task_id": "task-multi-1",
        "task_revision": 41,
        "workflow_bundle_sha256": digest("bundle"),
        "map_epoch": 3,
        "node_instance_id": "map.impl:api:3",
        "repository_id": "api",
        "repository_identity_sha256": digest("repository"),
        "worktree_identity_sha256": digest("worktree"),
        "attempt": 1,
        "input_evidence_sha256": digest("input"),
        "plan_dag_sha256": digest("dag"),
        "semantic_input_sha256": digest("semantic"),
        "interface_contract_sha256s": [digest("contract-a")],
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


def result_payload(
    namespace,
    *,
    repository_id: str = "api",
    node_instance_id: str = "node-api",
) -> dict[str, object]:
    return {
        "schema": namespace["ORCHESTRATION_NODE_RESULT_SCHEMA"],
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
        "outcome": "SUCCEEDED",
        "summary": f"{repository_id} result",
        "blockers": [],
        "plan_drift": {"detected": False, "reasons": []},
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


def expectation(namespace) -> dict[str, object]:
    return {
        "schema": namespace["NODE_RESULT_EXPECTATION_SCHEMA"],
        "task_id": "task-1",
        "workflow_bundle_sha256": digest("b"),
        "plan_id": "plan-1",
        "plan_artifact_sha256": digest("p"),
        "dag_sha256": digest("d"),
        "semantic_input_sha256": digest("s"),
        "map_epoch": 3,
        "repository_id": "api",
        "repository_identity_sha256": digest("a"),
        "node_instance_id": "node-api",
        "attempt": 1,
        "assignment_revision": 7,
        "assignment_id": content_id(
            "worker-assignment", "assignment-api"
        ),
        "assignment_sha256": digest("n"),
        "lease_id": content_id("worker-lease", "lease-api"),
        "lease_nonce": digest("nonce-api"),
        "input_sha256": digest("i"),
        "interface_contract_sha256": [digest("c")],
        "input_worktree_fingerprint_sha256": digest("f"),
        "actor_id": "worker-api",
        "host_assignment_id": "host-api",
        "runtime_handle_id": "runtime-api",
        "lease_active": True,
    }


def verified_output(namespace) -> dict[str, object]:
    return {
        "schema": namespace["NODE_RESULT_VERIFIED_OUTPUT_SCHEMA"],
        "output_sha256": digest("o"),
        "worktree_sha256": digest("g"),
        "changed_paths_sha256": digest("h"),
        "verification_sha256": digest("v"),
        "artifacts": {"artifact-api": digest("r")},
        "evidence": {
            "evidence-api": {
                "sha256": digest("r"),
                "semantic_sha256": digest("e"),
                "size": 321,
                "kind": "test.report.v1",
                "locator": "evidence-api",
                "current": True,
            }
        },
    }


def accepted_result(namespace, result) -> dict[str, object]:
    return {
        "schema": namespace["ACCEPTED_NODE_RESULT_SCHEMA"],
        "accepted": True,
        "current": True,
        "repository_evidence_sha256": digest("z"),
        "lease_quiesced": True,
        "runtime_live": False,
        "result": result,
    }


def barrier(namespace) -> dict[str, object]:
    return {
        "schema": namespace["RESULT_BARRIER_SCHEMA"],
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


class V4MultiRepositoryTests(V4OrchestrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.full = runtime_services().catalog.bundles[("full", 4)]

    def test_plan_expansion_and_exclusive_lease_execute(self) -> None:
        n = self.namespace
        plan = n["bind_repository_plan_semantic_input"](
            repository_plan()
        )
        validated = n["validate_repository_plan"](plan)
        approval = n["create_repository_plan_approval"](
            validated,
            approval_intent="approve-repository-map/v1",
            approval_commit_revision=12,
        )
        expansion = n["expand_repository_map"](validated, approval)
        self.assertEqual(
            [child["repository_id"] for child in expansion["children"]],
            ["api", "docs", "web"],
        )
        self.assertEqual(
            expansion,
            n["expand_repository_map"](
                validated, approval, existing_expansion=expansion
            ),
        )

        lease = n["issue_worker_lease"](
            lease_spec(),
            lease_nonce_bytes=b"L" * 32,
            wall_time_ns=1_000_000,
            monotonic_time_ns=50_000,
            ttl_ns=10_000,
            clock_id="boot-4",
        )
        status = n["worker_lease_status"](
            lease,
            wall_time_ns=1_000_001,
            monotonic_time_ns=50_001,
            clock_id="boot-4",
        )
        self.assertTrue(status.authorized)
        with self.assertRaises(
            n["OrchestrationAuthorityError"]
        ) as raised:
            n["issue_worker_lease"](
                lease_spec(),
                lease_nonce_bytes=b"M" * 32,
                wall_time_ns=1_000_002,
                monotonic_time_ns=50_002,
                ttl_ns=10_000,
                clock_id="boot-4",
                existing_leases=(lease,),
            )
        self.assertEqual(
            raised.exception.code, "WORKER_LEASE_EXCLUSIVE_CONFLICT"
        )

    def test_result_barrier_integration_and_serialized_cas_execute(self) -> None:
        n = self.namespace
        _plan, assignment = self.start_orchestration_assignment()
        result = self.successful_orchestration_result(assignment)
        expected_revision = int(self.orchestration_state()["revision"])
        requests = [
            self.orchestration_request(
                n["ORCHESTRATION_OPERATION_RESULT_ACCEPT"],
                expected_revision=expected_revision,
                nonce=digest(f"competing-result-{index}"),
            )
            for index in range(2)
        ]

        def accept(request):
            try:
                receipt = self.service.accept_result(
                    self.orchestration_task_id,
                    result,
                    request=request,
                    principal=self.orchestration_principal(),
                    data_dir=self.data_dir,
                )
                return ("accepted", receipt.revision)
            except n["FlowError"] as exc:
                return ("rejected", exc.code)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(accept, requests))
        self.assertEqual(
            sorted(item[0] for item in outcomes),
            ["accepted", "rejected"],
        )
        rejected_code = next(
            item[1] for item in outcomes if item[0] == "rejected"
        )
        self.assertIn(
            rejected_code,
            {
                "ACTION_JOURNAL_SCOPE_CONFLICT",
                "REVISION_CONFLICT",
                "MANAGER_REQUEST_REVISION_MISMATCH",
                "ORCHESTRATION_REVISION_CONFLICT",
            },
        )
        state = self.orchestration_state()
        self.assertEqual(state["revision"], expected_revision + 1)
        self.assertIn(
            result["result_id"],
            state["orchestration"]["accepted_results"],
        )
        with self.assertRaises(n["FlowError"]) as stale:
            self.service.accept_result(
                self.orchestration_task_id,
                result,
                request=self.orchestration_request(
                    n["ORCHESTRATION_OPERATION_RESULT_ACCEPT"],
                    expected_revision=expected_revision,
                    nonce=digest("stale-result-cas"),
                ),
                principal=self.orchestration_principal(),
                data_dir=self.data_dir,
            )
        self.assertIn(
            stale.exception.code,
            {
                "REVISION_CONFLICT",
                "MANAGER_REQUEST_REVISION_MISMATCH",
                "ORCHESTRATION_REVISION_CONFLICT",
            },
        )

        self.service.record_authenticated_stop(
            self.orchestration_task_id,
            lease_id=str(
                assignment["lease_credential"]["lease_id"]
            ),
            request=self.orchestration_request(
                n["ORCHESTRATION_ACTION_RUNTIME_STOP"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        closed = self.service.evaluate_barrier(
            self.orchestration_task_id,
            request=self.orchestration_request(
                n["ORCHESTRATION_OPERATION_BARRIER_CLOSE"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        self.assertEqual(closed.payload["status"], "CLOSED")

        snapshot = self.service.capture_integration_snapshot(
            self.orchestration_task_id,
            barrier_id=str(closed.payload["barrier_id"]),
            request=self.orchestration_request(
                n["ORCHESTRATION_ACTION_INTEGRATION_CAPTURE"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        verified = self.service.record_integration_verification(
            self.orchestration_task_id,
            snapshot_id=str(snapshot.payload["snapshot_id"]),
            request=self.orchestration_request(
                n["ORCHESTRATION_ACTION_INTEGRATION_VERIFY"]
            ),
            principal=self.orchestration_principal(),
            data_dir=self.data_dir,
        )
        final_state = self.orchestration_state()
        self.assertTrue(snapshot.payload["snapshot_id"])
        self.assertTrue(verified.payload["verification_id"])
        self.assertEqual(final_state["revision"], verified.revision)
        events = [
            json.loads(line)
            for line in (
                self.orchestration_task_dir / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            [event["revision"] for event in events],
            sorted(event["revision"] for event in events),
        )
        self.assertTrue(
            list(
                (
                    self.orchestration_task_dir
                    / "action-executions"
                    / "archive"
                ).rglob("*.json")
            )
        )

    def test_full_profile_places_multi_repository_operations(self) -> None:
        orchestration = self.full.repository_orchestration
        self.assertIsNotNone(orchestration)
        matrix = orchestration["operation_matrix"]
        self.assertEqual(
            len({item["write_set_id"] for item in matrix}), len(matrix)
        )
        placements = [
            edge
            for edge in self.full.action_edges
            if "v4-multi-repository" in edge["required_suites"]
        ]
        self.assertTrue(placements)
        self.assertTrue(all(edge["kernel_state_writes"] for edge in placements))


if __name__ == "__main__":
    unittest.main()
