from __future__ import annotations

import ast
import concurrent.futures
import hashlib
import inspect
import json
import textwrap
import threading
import time
from pathlib import Path

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


AUTHORITATIVE_OPERATIONS = (
    "manager.capability.authorize/v1",
    "manager.capability.revoke/v1",
    "orchestration.artifact.record/v1",
    "orchestration.assignment.issue/v1",
    "orchestration.attempt.abandon/v1",
    "orchestration.barrier.close/v1",
    "orchestration.barrier.reopen/v1",
    "orchestration.cancellation.request/v1",
    "orchestration.dispatch.handoff/v1",
    "orchestration.finalization.commit/v1",
    "orchestration.frontier.advance/v1",
    "orchestration.integration.capture/v1",
    "orchestration.integration.verify/v1",
    "orchestration.lease.expire/v1",
    "orchestration.lease.issue/v1",
    "orchestration.lease.revoke/v1",
    "orchestration.map.expand/v1",
    "orchestration.map.invalidate/v1",
    "orchestration.plan.approve/v1",
    "orchestration.plan.record/v1",
    "orchestration.reconciliation.begin/v1",
    "orchestration.reconciliation.complete/v1",
    "orchestration.result.accept/v1",
    "orchestration.result.invalidate/v1",
    "orchestration.retry.request/v1",
    "orchestration.review.record/v1",
    "orchestration.runtime-stop.record/v1",
    "orchestration.runtime.recovery.observe/v1",
    "orchestration.timeout.record/v1",
)


SERVICE_ROUTES = {
    "manager.capability.authorize/v1": (
        "authorize_manager",
        "ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE",
    ),
    "manager.capability.revoke/v1": (
        "revoke_manager",
        "ORCHESTRATION_OPERATION_MANAGER_REVOKE",
    ),
    "orchestration.artifact.record/v1": (
        "record_artifact",
        "ORCHESTRATION_OPERATION_ARTIFACT_RECORD",
    ),
    "orchestration.assignment.issue/v1": (
        "issue_assignment",
        "ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE",
    ),
    "orchestration.attempt.abandon/v1": (
        "abandon_attempt",
        "ORCHESTRATION_OPERATION_ATTEMPT_ABANDON",
    ),
    "orchestration.barrier.close/v1": (
        "evaluate_barrier",
        "ORCHESTRATION_OPERATION_BARRIER_CLOSE",
    ),
    "orchestration.barrier.reopen/v1": (
        "reopen_barrier",
        "ORCHESTRATION_OPERATION_BARRIER_REOPEN",
    ),
    "orchestration.cancellation.request/v1": (
        "request_cancellation",
        "ORCHESTRATION_OPERATION_CANCELLATION_REQUEST",
    ),
    "orchestration.dispatch.handoff/v1": (
        "handoff_dispatch",
        "ORCHESTRATION_OPERATION_DISPATCH_HANDOFF",
    ),
    "orchestration.finalization.commit/v1": (
        "commit_finalization",
        "ORCHESTRATION_OPERATION_FINALIZATION_COMMIT",
    ),
    "orchestration.frontier.advance/v1": (
        "advance_ready_frontier",
        "ORCHESTRATION_OPERATION_FRONTIER_ADVANCE",
    ),
    "orchestration.integration.capture/v1": (
        "capture_integration_snapshot",
        "ORCHESTRATION_ACTION_INTEGRATION_CAPTURE",
    ),
    "orchestration.integration.verify/v1": (
        "record_integration_verification",
        "ORCHESTRATION_OPERATION_INTEGRATION_VERIFY",
    ),
    "orchestration.lease.expire/v1": (
        "expire_lease",
        "ORCHESTRATION_OPERATION_LEASE_EXPIRE",
    ),
    "orchestration.lease.issue/v1": (
        "issue_lease",
        "ORCHESTRATION_OPERATION_LEASE_ISSUE",
    ),
    "orchestration.lease.revoke/v1": (
        "revoke_lease",
        "ORCHESTRATION_OPERATION_LEASE_REVOKE",
    ),
    "orchestration.map.expand/v1": (
        "expand_plan",
        "ORCHESTRATION_OPERATION_MAP_EXPAND",
    ),
    "orchestration.map.invalidate/v1": (
        "invalidate_map",
        "ORCHESTRATION_OPERATION_MAP_INVALIDATE",
    ),
    "orchestration.plan.approve/v1": (
        "approve_plan",
        "ORCHESTRATION_OPERATION_PLAN_APPROVE",
    ),
    "orchestration.plan.record/v1": (
        "record_plan",
        "ORCHESTRATION_ACTION_PLAN_RECORD",
    ),
    "orchestration.reconciliation.begin/v1": (
        "begin_reconciliation",
        "ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN",
    ),
    "orchestration.reconciliation.complete/v1": (
        "complete_reconciliation",
        "ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE",
    ),
    "orchestration.result.accept/v1": (
        "accept_result",
        "ORCHESTRATION_OPERATION_RESULT_ACCEPT",
    ),
    "orchestration.result.invalidate/v1": (
        "invalidate_result",
        "ORCHESTRATION_OPERATION_RESULT_INVALIDATE",
    ),
    "orchestration.retry.request/v1": (
        "request_retry",
        "ORCHESTRATION_OPERATION_RETRY_REQUEST",
    ),
    "orchestration.review.record/v1": (
        "record_independent_review",
        "ORCHESTRATION_OPERATION_REVIEW_RECORD",
    ),
    "orchestration.runtime-stop.record/v1": (
        "record_authenticated_stop",
        "ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD",
    ),
    "orchestration.runtime.recovery.observe/v1": (
        "recover_runtime",
        "ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE",
    ),
    "orchestration.timeout.record/v1": (
        "record_timeout",
        "ORCHESTRATION_OPERATION_TIMEOUT_RECORD",
    ),
}


class OrchestrationActionTransactionCatalogTests(DevFlowTestCase):
    def _state(self) -> dict[str, object]:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        return {
            "schema_version": 3,
            "task_id": "orchestration-routing-task",
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            **json.loads(
                json.dumps(
                    dev_flow.build_v3_task_creation_fields(
                        "orchestration-routing-task",
                        bundle,
                        execution_profile="multi-repository",
                    )
                )
            ),
        }

    def test_exact_29_operation_set_is_catalog_sealed_and_typed(self) -> None:
        state = self._state()
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        metadata = bundle.repository_orchestration
        self.assertEqual(
            tuple(metadata["operation_ids"]), AUTHORITATIVE_OPERATIONS
        )
        self.assertEqual(
            tuple(dev_flow.ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS),
            AUTHORITATIVE_OPERATIONS,
        )
        self.assertEqual(
            tuple(
                sorted(
                    dev_flow._OSC_AUTHORITATIVE_VALIDATORS,
                    key=lambda value: value.encode("utf-8"),
                )
            ),
            AUTHORITATIVE_OPERATIONS,
        )
        self.assertEqual(
            len(set(dev_flow._OSC_AUTHORITATIVE_VALIDATORS.values())),
            29,
        )

        semantic_roles: set[str] = set()
        for operation_id in AUTHORITATIVE_OPERATIONS:
            with self.subTest(operation_id=operation_id):
                selection = (
                    dev_flow.resolve_catalog_orchestration_action(
                        state, operation_id
                    )
                )
                self.assertIsInstance(
                    selection,
                    dev_flow.OrchestrationActionSelection,
                )
                self.assertEqual(selection.operation_id, operation_id)
                roles = {
                    selection.action_id,
                    selection.validator_id,
                    selection.event_id,
                    selection.write_set_id,
                    *selection.effect_ids,
                }
                self.assertFalse(semantic_roles.intersection(roles))
                semantic_roles.update(roles)
                edge = next(
                    item
                    for item in bundle.action_edges
                    if item["id"] == selection.edge_id
                )
                self.assertEqual(edge["id"], selection.edge_id)
                self.assertEqual(
                    edge["trigger"]["id"], selection.action_id
                )
                self.assertEqual(
                    edge["canonical_event"],
                    selection.canonical_event,
                )

    def test_every_service_route_names_its_exact_authoritative_operation(
        self,
    ) -> None:
        self.assertEqual(set(SERVICE_ROUTES), set(AUTHORITATIVE_OPERATIONS))
        for operation_id, (method_name, constant_name) in (
            SERVICE_ROUTES.items()
        ):
            with self.subTest(operation_id=operation_id):
                method = getattr(
                    dev_flow.OrchestrationControllerService, method_name
                )
                tree = ast.parse(
                    textwrap.dedent(inspect.getsource(method))
                )
                referenced_names = {
                    node.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                }
                referenced_names.update(
                    node.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute)
                )
                self.assertIn(constant_name, referenced_names)
                self.assertEqual(
                    getattr(dev_flow, constant_name), operation_id
                )
                gateway = (
                    "_osc_execute_authoritative_transaction"
                    if operation_id.startswith("manager.capability.")
                    else "_simple_authorized_mutation"
                )
                self.assertIn(gateway, referenced_names)
                self.assertNotIn(
                    "_persist_state_transaction", referenced_names
                )

        coordinator_source = inspect.getsource(
            dev_flow._osc_execute_authoritative_transaction
        )
        self.assertIn(
            "_osc_build_authoritative_action_result",
            coordinator_source,
        )
        self.assertIn(
            "preview_v3_workflow_action_transaction",
            coordinator_source,
        )
        self.assertIn(
            "execute_v3_workflow_action_transaction",
            coordinator_source,
        )
        self.assertIn(
            "current_invocation_factory", coordinator_source
        )
        self.assertNotIn("_persist_state_transaction", coordinator_source)
        mutation_source = inspect.getsource(
            dev_flow.OrchestrationControllerService
            ._simple_authorized_mutation
        )
        self.assertIn(
            "_osc_execute_authoritative_transaction", mutation_source
        )
        self.assertNotIn("_persist_state_transaction", mutation_source)


class OrchestrationActionTransactionRuntimeTests(DevFlowTestCase):
    task_id = "orchestration-action-transaction-task"
    manager_session_id = "orchestration-action-transaction-manager"

    def setUp(self) -> None:
        super().setUp()
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": self.task_id,
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            **json.loads(
                json.dumps(
                    dev_flow.build_v3_task_creation_fields(
                        self.task_id,
                        bundle,
                        execution_profile="multi-repository",
                    )
                )
            ),
        }
        self.task_dir = self.data / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True)
        (self.task_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.secrets: dict[str, bytearray] = {}
        self.secret_publications = 0
        self.random_counter = 0
        self.wall_ns = time.time_ns()
        self.monotonic_ns = dev_flow._manager_system_monotonic_ns()
        self.protected_identity = _sha("controller-data-directory")
        self.service = dev_flow.OrchestrationControllerService(
            secret_resolver=lambda capability_id: bytearray(
                self.secrets[capability_id]
            ),
            secret_publisher=self._publish_secret,
            random_bytes=self._random_bytes,
            wall_time_ns=lambda: self.wall_ns,
            monotonic_ns=lambda: self.monotonic_ns,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            host_capability_observer=self._trusted_host_observer,
            trusted_host_adapter_ids=("transaction-host-adapter",),
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
            operator_confirmation_sha256=_sha("operator-confirmation"),
            issuance_audit_sha256=_sha("issuance-audit"),
            data_dir=self.data,
        )
        self.capability_id = str(receipt.payload["capability_id"])
        self.nonce_counter = 0

    def _publish_secret(
        self, capability_id: str, secret: bytearray
    ) -> None:
        self.secret_publications += 1
        self.secrets[capability_id] = bytearray(secret)

    def _random_bytes(self, size: int) -> bytearray:
        self.random_counter += 1
        seed = hashlib.sha256(
            f"orchestration-random-{self.random_counter}".encode("utf-8")
        ).digest()
        return bytearray(
            (seed * ((size + len(seed) - 1) // len(seed)))[:size]
        )

    def _trusted_host_observer(
        self, assignment: dict[str, object]
    ) -> dict[str, object]:
        return {
            "schema": dev_flow.HOST_CAPABILITY_REPORT_SCHEMA,
            "adapter_id": "transaction-host-adapter",
            "assignment_id": assignment["assignment_id"],
            "worker_session_id": "transaction-worker-session",
            "worker_identity_sha256": _sha("transaction-worker"),
            "attestation_sha256": _sha("transaction-host-attestation"),
            "host_enforced": True,
            "allowed_write_identity_sha256s": [
                assignment["worktree_identity_sha256"]
            ],
            "denied_read_identity_sha256s": [
                self.protected_identity
            ],
            "denied_tool_ids": sorted(dev_flow._osc_mutating_tool_ids),
            "all_other_writes_denied": True,
            "manager_secret_channel_excluded": True,
            "controller_state_excluded": True,
            "mutation_tools_excluded": True,
        }

    def _state(self) -> dict[str, object]:
        return json.loads(
            (self.task_dir / "state.json").read_text(encoding="utf-8")
        )

    def _task_snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.task_dir)): path.read_bytes()
            for path in sorted(self.task_dir.rglob("*"))
            if path.is_file()
        }

    def _principal(self) -> dict[str, object]:
        return {
            "schema": dev_flow.AGENT_PRINCIPAL_SCHEMA,
            "role": "manager",
            "session_id": self.manager_session_id,
            "os_user_identity_sha256": _sha("os-user"),
            "host_identity_sha256": _sha("host"),
        }

    def _request(
        self,
        action_id: str,
        *,
        expected_revision: int | None = None,
        nonce: str | None = None,
    ) -> dict[str, object]:
        self.nonce_counter += 1
        return {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "manager_session_id": self.manager_session_id,
            "action_id": action_id,
            "expected_revision": (
                int(self._state()["revision"])
                if expected_revision is None
                else expected_revision
            ),
            "request_nonce": (
                nonce or _sha(f"request-{self.nonce_counter}")
            ),
        }

    def _record_two_repository_plan(
        self, repositories: dict[str, Path]
    ) -> dict[str, object]:
        contract_content = b'{"schema":"contract.integration/v1"}\n'
        contract_sha256 = hashlib.sha256(
            contract_content
        ).hexdigest()
        self.service.record_artifact(
            self.task_id,
            artifact_id="transaction-integration-contract",
            content=contract_content,
            kind="application/vnd.dev-flow.contract+json",
            semantic_sha256=contract_sha256,
            request=self._request(
                "orchestration.artifact.record/v1"
            ),
            principal=self._principal(),
            data_dir=self.data,
        )
        repository_rows = []
        for repository_id, path in repositories.items():
            binding = dev_flow._osc_stable_worktree_binding(
                str(path)
            )
            repository_rows.append(
                {
                    "repository_id": repository_id,
                    "identity_sha256": binding[
                        "repository_common_dir_sha256"
                    ],
                    "repository_path": (
                        f"repositories/{repository_id}"
                    ),
                    "approved_paths": ["src", "tests"],
                    "write_policy": "scoped-write",
                    "required_approval_ids": [],
                    "required_evidence_contract_sha256": [
                        contract_sha256
                    ],
                }
            )
        repository_rows.sort(
            key=lambda value: str(
                value["repository_id"]
            ).encode("utf-8")
        )
        plan_value = {
            "schema": dev_flow.REPOSITORY_PLAN_SCHEMA,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self._state()[
                "workflow_ref"
            ]["bundle_sha256"],
            "plan_id": "transaction-two-repository-plan",
            "map_node_id": "map.repositories/v1",
            "map_epoch": 1,
            "plan_input_revision": self._state()["revision"],
            "semantic_input_sha256": "0" * 64,
            "repository_set": sorted(repositories),
            "repositories": repository_rows,
            "interface_contracts": [
                {
                    "contract_id": "contract.integration/v1",
                    "artifact_id": (
                        "transaction-integration-contract"
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
                "max_workers": 2,
                "max_writable_workers": 2,
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
        plan = json.loads(
            dev_flow.canonical_repository_plan_bytes(
                dev_flow.bind_repository_plan_semantic_input(
                    plan_value
                )
            )
        )
        self.service.record_plan(
            self.task_id,
            plan,
            request=self._request(
                "orchestration.plan.record/v1"
            ),
            principal=self._principal(),
            data_dir=self.data,
        )
        self.service.approve_plan(
            self.task_id,
            approval_intent="approve-repository-map/v1",
            request=self._request(
                "orchestration.plan.approve/v1"
            ),
            principal=self._principal(),
            data_dir=self.data,
        )
        self.service.expand_plan(
            self.task_id,
            current_semantic_input_sha256=plan[
                "semantic_input_sha256"
            ],
            request=self._request(
                "orchestration.map.expand/v1"
            ),
            principal=self._principal(),
            data_dir=self.data,
        )
        child_ids = sorted(
            (
                str(child["node_instance_id"])
                for child in self._state()["orchestration"][
                    "expansion"
                ]["children"]
            ),
            key=lambda value: value.encode("utf-8"),
        )
        for child_id in child_ids:
            self.service.advance_ready_frontier(
                self.task_id,
                node_instance_id=child_id,
                request=self._request(
                    "orchestration.frontier.advance/v1"
                ),
                principal=self._principal(),
                data_dir=self.data,
            )
        return plan

    def _issue_two_assignments(
        self,
        plan: dict[str, object],
        repositories: dict[str, Path],
    ) -> dict[str, dict[str, object]]:
        children = {
            str(child["repository_id"]): child
            for child in self._state()["orchestration"][
                "expansion"
            ]["children"]
        }
        allowed_actions = [
            "repository.read/v1",
            "repository.write-approved/v1",
            "result.emit-candidate/v1",
        ]
        result: dict[str, dict[str, object]] = {}
        for repository_id, worktree in repositories.items():
            child = children[repository_id]
            input_sha256 = _sha(
                f"transaction-input-{repository_id}"
            )
            lease_receipt = self.service.issue_lease(
                self.task_id,
                node_instance_id=str(child["node_instance_id"]),
                worktree_path=str(worktree),
                input_evidence_sha256=input_sha256,
                allowed_actions=allowed_actions,
                lease_ttl_ns=100_000_000_000,
                request=self._request(
                    "orchestration.lease.issue/v1"
                ),
                principal=self._principal(),
                data_dir=self.data,
            )
            lease_id = str(lease_receipt.payload["lease_id"])
            repository = next(
                row
                for row in plan["repositories"]
                if row["repository_id"] == repository_id
            )
            assignment_receipt = self.service.issue_assignment(
                self.task_id,
                node_instance_id=str(child["node_instance_id"]),
                worktree_path=str(worktree),
                input_evidence_sha256=input_sha256,
                allowed_actions=allowed_actions,
                playbook_locator="playbooks/workflow.md",
                playbook_sha256=_sha("transaction-playbook"),
                required_evidence_contract_sha256s=repository[
                    "required_evidence_contract_sha256"
                ],
                runtime_handle_id=None,
                host_assignment_id=(
                    f"transaction-host-{repository_id}"
                ),
                runtime_authentication_sha256=_sha(
                    f"transaction-runtime-auth-{repository_id}"
                ),
                actor_id=f"transaction-actor-{repository_id}",
                lease_ttl_ns=100_000_000_000,
                lease_id=lease_id,
                request=self._request(
                    "orchestration.assignment.issue/v1"
                ),
                principal=self._principal(),
                data_dir=self.data,
            )
            assignment_id = str(
                assignment_receipt.payload["assignment_id"]
            )
            result[repository_id] = self._state()[
                "orchestration"
            ]["assignments"][assignment_id]
        return result

    def test_single_dispatch_operation_commits_through_generic_journal(
        self,
    ) -> None:
        content = b"catalog-sealed orchestration artifact\n"
        content_sha256 = hashlib.sha256(content).hexdigest()
        receipt = self.service.record_artifact(
            self.task_id,
            artifact_id="transaction-artifact",
            content=content,
            kind="text/plain",
            semantic_sha256=content_sha256,
            request=self._request(
                "orchestration.artifact.record/v1"
            ),
            principal=self._principal(),
            data_dir=self.data,
        )
        self.assertEqual(receipt.revision, 2)
        self.assertEqual(
            self._state()["orchestration"]["artifacts"][
                "transaction-artifact"
            ]["sha256"],
            content_sha256,
        )
        archive = self.task_dir / "action-executions" / "archive"
        archived = list(archive.glob("*.json"))
        self.assertGreaterEqual(len(archived), 2)
        artifact_journals = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in archived
            if "orchestration-artifact-" in path.name
        ]
        self.assertEqual(len(artifact_journals), 1)
        self.assertEqual(artifact_journals[0]["phase"], "COMMITTED")
        self.assertEqual(
            artifact_journals[0]["bindings"]["action_edge_id"],
            dev_flow.resolve_catalog_orchestration_action(
                self._state(),
                "orchestration.artifact.record/v1",
            ).edge_id,
        )

    def test_wrong_binding_and_replay_are_zero_write(self) -> None:
        before = self._task_snapshot()
        request = self._request(
            "orchestration.assignment.issue/v1"
        )
        with self.assertRaises(Exception):
            self.service.record_artifact(
                self.task_id,
                artifact_id="wrong-binding-artifact",
                content=b"wrong binding\n",
                kind="text/plain",
                semantic_sha256=hashlib.sha256(
                    b"wrong binding\n"
                ).hexdigest(),
                request=request,
                principal=self._principal(),
                data_dir=self.data,
            )
        self.assertEqual(self._task_snapshot(), before)
        self.assertFalse(
            (
                self.task_dir
                / "artifacts"
                / "wrong-binding-artifact"
            ).exists()
        )

        content = b"replay-bound artifact\n"
        digest = hashlib.sha256(content).hexdigest()
        replay_request = self._request(
            "orchestration.artifact.record/v1",
            nonce=_sha("one-shot-replay-nonce"),
        )
        self.service.record_artifact(
            self.task_id,
            artifact_id="replay-artifact",
            content=content,
            kind="text/plain",
            semantic_sha256=digest,
            request=replay_request,
            principal=self._principal(),
            data_dir=self.data,
        )
        committed = self._task_snapshot()
        with self.assertRaises(Exception):
            self.service.record_artifact(
                self.task_id,
                artifact_id="replay-artifact",
                content=content,
                kind="text/plain",
                semantic_sha256=digest,
                request=replay_request,
                principal=self._principal(),
                data_dir=self.data,
            )
        self.assertEqual(self._task_snapshot(), committed)

    def test_overlapping_scopes_serialize_and_loser_never_dispatches(
        self,
    ) -> None:
        first_entered = threading.Event()
        release_first = threading.Event()
        dispatcher_calls: list[str] = []
        original_publish = dev_flow._osc_publish_artifact

        def blocking_publish(
            task_dir: Path,
            reference: object,
            content: bytes,
        ) -> None:
            original_publish(task_dir, reference, content)
            dispatcher_calls.append(str(reference["id"]))
            first_entered.set()
            if not release_first.wait(timeout=10):
                raise AssertionError("timed out awaiting overlap assertion")

        dev_flow._osc_publish_artifact = blocking_publish
        first_content = b"first overlapping artifact\n"
        second_content = b"second overlapping artifact\n"
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2
            ) as executor:
                first = executor.submit(
                    self.service.record_artifact,
                    self.task_id,
                    artifact_id="overlap-first",
                    content=first_content,
                    kind="text/plain",
                    semantic_sha256=hashlib.sha256(
                        first_content
                    ).hexdigest(),
                    request=self._request(
                        "orchestration.artifact.record/v1"
                    ),
                    principal=self._principal(),
                    data_dir=self.data,
                )
                self.assertTrue(first_entered.wait(timeout=5))
                second = executor.submit(
                    self.service.record_artifact,
                    self.task_id,
                    artifact_id="overlap-second",
                    content=second_content,
                    kind="text/plain",
                    semantic_sha256=hashlib.sha256(
                        second_content
                    ).hexdigest(),
                    request=self._request(
                        "orchestration.artifact.record/v1"
                    ),
                    principal=self._principal(),
                    data_dir=self.data,
                )
                with self.assertRaises(Exception) as raised:
                    second.result(timeout=5)
                release_first.set()
                self.assertEqual(
                    getattr(raised.exception, "code", None),
                    "ACTION_JOURNAL_SCOPE_CONFLICT",
                )
                self.assertEqual(dispatcher_calls, ["overlap-first"])
                first_receipt = first.result(timeout=10)
        finally:
            release_first.set()
            dev_flow._osc_publish_artifact = original_publish

        self.assertEqual(first_receipt.revision, 2)
        current = self._state()
        self.assertIn(
            "overlap-first", current["orchestration"]["artifacts"]
        )
        self.assertNotIn(
            "overlap-second", current["orchestration"]["artifacts"]
        )
        self.assertFalse(
            (
                self.task_dir
                / "artifacts"
                / "overlap-second"
            ).exists()
        )

    def test_disjoint_repository_handoffs_dispatch_concurrently_and_commit(
        self,
    ) -> None:
        repositories = {
            repository_id: self.make_repo(
                f"transaction-{repository_id}"
            )[0]
            for repository_id in ("api", "web")
        }
        plan = self._record_two_repository_plan(repositories)
        assignments = self._issue_two_assignments(
            plan, repositories
        )
        shared_revision = int(self._state()["revision"])
        requests = {
            repository_id: self._request(
                "orchestration.dispatch.handoff/v1",
                expected_revision=shared_revision,
            )
            for repository_id in repositories
        }
        dispatch_barrier = threading.Barrier(2)
        dispatch_entries: list[str] = []
        original_dispatch = (
            dev_flow.dispatch_claimed_v3_workflow_action_effect
        )

        def synchronized_dispatch(
            *args: object, **kwargs: object
        ) -> object:
            dispatch_entries.append(str(args[1].plan.execution_id))
            dispatch_barrier.wait(timeout=10)
            return original_dispatch(*args, **kwargs)

        def handoff(repository_id: str) -> object:
            assignment = assignments[repository_id]
            return self.service.handoff_dispatch(
                self.task_id,
                assignment_id=str(assignment["assignment_id"]),
                runtime_handle_id=f"runtime-{repository_id}",
                host_assignment_id=f"host-{repository_id}",
                runtime_authentication_sha256=_sha(
                    f"runtime-auth-{repository_id}"
                ),
                actor_id=f"actor-{repository_id}",
                request=requests[repository_id],
                principal=self._principal(),
                data_dir=self.data,
            )

        dev_flow.dispatch_claimed_v3_workflow_action_effect = (
            synchronized_dispatch
        )
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2
            ) as executor:
                futures = {
                    repository_id: executor.submit(
                        handoff, repository_id
                    )
                    for repository_id in repositories
                }
                receipts = {
                    repository_id: future.result(timeout=20)
                    for repository_id, future in futures.items()
                }
        finally:
            dev_flow.dispatch_claimed_v3_workflow_action_effect = (
                original_dispatch
            )

        self.assertEqual(len(dispatch_entries), 2)
        self.assertEqual(len(set(dispatch_entries)), 2)
        self.assertEqual(
            sorted(
                receipt.revision for receipt in receipts.values()
            ),
            [shared_revision + 1, shared_revision + 2],
        )
        dispatch = self._state()["orchestration"]["dispatch"]
        self.assertEqual(
            {
                str(value["assignment_id"])
                for value in assignments.values()
            },
            set(dispatch),
        )


class OrchestrationActionLostResponseTests(DevFlowTestCase):
    def test_manager_authorize_lost_response_never_republishes_secret(
        self,
    ) -> None:
        task_id = "orchestration-manager-lost-response"
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 0,
            "status": "INTAKE",
            "flow": "full",
            **json.loads(
                json.dumps(
                    dev_flow.build_v3_task_creation_fields(
                        task_id,
                        bundle,
                        execution_profile="multi-repository",
                    )
                )
            ),
        }
        task_dir = self.data / "tasks" / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        publications: list[str] = []
        random_counter = 0

        def random_bytes(size: int) -> bytearray:
            nonlocal random_counter
            random_counter += 1
            seed = hashlib.sha256(
                f"lost-random-{random_counter}".encode("utf-8")
            ).digest()
            return bytearray(
                (seed * ((size + len(seed) - 1) // len(seed)))[:size]
            )

        service = dev_flow.OrchestrationControllerService(
            secret_resolver=lambda _capability_id: bytearray(b"x" * 32),
            secret_publisher=lambda capability_id, _secret: (
                publications.append(capability_id)
            ),
            random_bytes=random_bytes,
            wall_time_ns=time.time_ns,
            monotonic_ns=dev_flow._manager_system_monotonic_ns,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
        )

        def fail(stage: str) -> None:
            if stage == "after-dispatch":
                raise RuntimeError("injected lost dispatch response")

        kwargs = {
            "expected_revision": 0,
            "manager_session_id": "lost-response-manager",
            "ttl_ns": 100_000_000_000,
            "operator_confirmed": True,
            "operator_confirmation_sha256": _sha(
                "lost-operator-confirmation"
            ),
            "issuance_audit_sha256": _sha("lost-issuance-audit"),
            "data_dir": self.data,
        }
        with self.assertRaises(Exception):
            service.authorize_manager(
                task_id, **kwargs, failure_hook=fail
            )
        self.assertEqual(len(publications), 1)
        restarted = dev_flow.OrchestrationControllerService(
            secret_resolver=lambda _capability_id: bytearray(b"x" * 32),
            secret_publisher=lambda capability_id, _secret: (
                publications.append(capability_id)
            ),
            random_bytes=random_bytes,
            wall_time_ns=time.time_ns,
            monotonic_ns=dev_flow._manager_system_monotonic_ns,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
        )
        with self.assertRaises(Exception):
            restarted.authorize_manager(task_id, **kwargs)
        self.assertEqual(len(publications), 1)
        current = json.loads(
            (task_dir / "state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(current["revision"], 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
