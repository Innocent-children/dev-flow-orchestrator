from __future__ import annotations

import copy
import dataclasses
import json
import socket
import time
import unittest
from types import MappingProxyType
from unittest import mock

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class V3ActivationTests(DevFlowTestCase):
    def _authorize_manager_action(
        self,
        task_id: str,
        revision: int,
        action_id: str,
    ) -> tuple[dict, bytearray]:
        state = dev_flow.load_state(task_id, self.data)
        self.assertEqual(state["revision"], revision)
        secret = bytearray(b"V" * 32)
        wall_time_ns = time.time_ns()
        verifier = dev_flow.issue_manager_capability(
            task_id=task_id,
            issued_for_task_revision=revision,
            manager_session_id="v3-activation-manager",
            allowed_actions=dev_flow._manager_default_actions(state),
            ttl_ns=60_000_000_000,
            wall_time_ns=wall_time_ns,
            monotonic_time_ns=(
                dev_flow._manager_system_monotonic_ns()
            ),
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="mcp-secret-channel",
            operator_confirmation_sha256="8" * 64,
            issuance_audit_sha256="9" * 64,
            manager_secret=secret,
        )
        state["orchestration"] = {
            "schema": "dev-flow-orchestration-state/v1",
            "manager_capabilities": {},
        }
        state["orchestration"]["manager_capabilities"][
            verifier.capability_id
        ] = verifier.as_persistent_dict()
        state_path = (
            self.data / "tasks" / task_id / "state.json"
        )
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        authorized = {
            "revision": revision,
            "capability": verifier.as_persistent_dict(),
        }
        self.assertIn(
            action_id,
            authorized["capability"]["allowed_actions"],
        )
        return authorized, secret

    def _apply_with_manager_secret(
        self,
        *arguments: str,
        request: dict,
        secret: bytearray,
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
            )
        finally:
            publisher.close()
            consumer.close()

    def _services_with_active(
        self, flow: str, execution_profile: str
    ) -> object:
        services = dev_flow.workflow_runtime_services()
        activations = []
        selected_found = False
        for frozen in services.catalog.activations:
            item = dict(frozen)
            selected = (
                item["workflow_id"] == flow
                and item["workflow_version"] == 4
                and item["execution_profile"] == execution_profile
            )
            selected_found = selected_found or selected
            if selected:
                item["active"] = True
                bundle = services.catalog.resolve(flow, 4)
                action_suites = {
                    str(suite)
                    for edge in bundle.action_edges
                    for suite in edge["required_suites"]
                }
                item["required_suites"] = sorted(
                    {
                        *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            execution_profile
                        ],
                        *action_suites,
                    }
                )
            else:
                item["active"] = False
                item["required_suites"] = []
            activations.append(MappingProxyType(item))
        bundle = services.catalog.resolve(flow, 4)
        action_suites = {
            str(suite)
            for edge in bundle.action_edges
            for suite in edge["required_suites"]
        }
        if not selected_found:
            activations.append(
                MappingProxyType(
                    {
                        "workflow_id": flow,
                        "workflow_version": 4,
                        "bundle_sha256": bundle.bundle_sha256,
                        "execution_profile": execution_profile,
                        "active": True,
                        "required_suites": sorted(
                            {
                                *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                                    execution_profile
                                ],
                                *action_suites,
                            }
                        ),
                    }
                )
            )
        catalog = dataclasses.replace(
            services.catalog, activations=tuple(activations)
        )
        return dataclasses.replace(services, catalog=catalog)

    def _services_with_all_inactive(self) -> object:
        services = dev_flow.workflow_runtime_services()
        activations = tuple(
            MappingProxyType(
                {
                    **dict(item),
                    "active": False,
                    "required_suites": [],
                }
            )
            for item in services.catalog.activations
        )
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog,
                activations=activations,
            ),
        )

    def _start_active_lite(self, task_id: str) -> dict:
        repository, _ = self.make_repo(f"{task_id}-repository")
        services = self._services_with_active(
            "lite", "single-repository"
        )
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            return self.cli(
                "start",
                "exercise the authoritative v3 path",
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

    def _services_with_bundle(
        self, services: object, bundle: object
    ) -> object:
        bundles = dict(services.catalog.bundles)
        bundles[bundle.key] = bundle
        by_identity = dict(services.catalog.bundles_by_identity)
        by_identity[bundle.bundle_sha256] = bundle
        catalog = dataclasses.replace(
            services.catalog,
            bundles=MappingProxyType(bundles),
            bundles_by_identity=MappingProxyType(by_identity),
        )
        return dataclasses.replace(services, catalog=catalog)

    def test_inactive_profile_falls_back_or_fails_closed_explicitly(
        self,
    ) -> None:
        services = self._services_with_all_inactive()
        fallback = dev_flow.select_task_creation_workflow(
            "full", 1, services=services
        )
        self.assertEqual(
            fallback["schema_version"], dev_flow.TASK_SCHEMA_VERSION
        )
        self.assertEqual(fallback["kind"], "legacy")

        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow.select_task_creation_workflow(
                "full",
                1,
                require_schema_v3=True,
                services=services,
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_CREATION_INACTIVE"
        )

    def test_single_and_multi_repository_activation_are_independent(
        self,
    ) -> None:
        services = self._services_with_active(
            "full", "single-repository"
        )

        single = dev_flow.select_task_creation_workflow(
            "full",
            1,
            require_schema_v3=True,
            services=services,
        )
        self.assertEqual(single["schema_version"], 3)
        self.assertEqual(
            single["execution_profile"], "single-repository"
        )
        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow.select_task_creation_workflow(
                "full",
                2,
                require_schema_v3=True,
                services=services,
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_CREATION_INACTIVE"
        )

    def test_active_but_incomplete_profile_never_falls_back(
        self,
    ) -> None:
        services = self._services_with_active(
            "lite", "single-repository"
        )
        activations = []
        for frozen in services.catalog.activations:
            item = dict(frozen)
            if (
                item["workflow_id"] == "lite"
                and item["execution_profile"] == "single-repository"
            ):
                item["required_suites"] = ["compatibility"]
            activations.append(MappingProxyType(item))
        services = dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog, activations=tuple(activations)
            ),
        )

        with self.assertRaises(dev_flow.WorkflowCatalogError) as raised:
            dev_flow.select_task_creation_workflow(
                "lite", 1, services=services
            )
        self.assertEqual(
            raised.exception.code, "WORKFLOW_ACTIVATION_INCOMPLETE"
        )
        self.assertIn(
            "rollback-rehearsal",
            raised.exception.details["missing_suites"],
        )

    def test_active_profile_negative_matrix_fails_before_first_commit(
        self,
    ) -> None:
        services = self._services_with_active(
            "lite", "single-repository"
        )
        bundle = services.catalog.resolve("lite", 4)

        first_edge = dict(bundle.edges[0])
        first_edge["target"] = "UNKNOWN-NODE"
        broken_edge = dataclasses.replace(
            bundle,
            edges=(
                MappingProxyType(first_edge),
                *bundle.edges[1:],
            ),
        )

        unknown_handler = dataclasses.replace(
            bundle,
            contracts=(
                *bundle.contracts,
                dev_flow.ContractReference(
                    "executors",
                    "executor.unknown/v1",
                    "v1",
                ),
            ),
        )

        first_node_id = next(iter(bundle.nodes))
        unsupported_recovery_nodes = dict(bundle.nodes)
        unsupported_recovery_node = dict(
            unsupported_recovery_nodes[first_node_id]
        )
        recovery = dict(
            unsupported_recovery_node["recovery_policy"]
        )
        recovery["mode"] = "unsupported"
        unsupported_recovery_node["recovery_policy"] = (
            MappingProxyType(recovery)
        )
        unsupported_recovery_nodes[first_node_id] = (
            MappingProxyType(unsupported_recovery_node)
        )
        unsupported_recovery = dataclasses.replace(
            bundle,
            nodes=MappingProxyType(unsupported_recovery_nodes),
        )

        unsupported_contract_nodes = dict(bundle.nodes)
        unsupported_contract_node = dict(
            unsupported_contract_nodes[first_node_id]
        )
        unsupported_contract_node["contract_version"] = "v999"
        unsupported_contract_nodes[first_node_id] = MappingProxyType(
            unsupported_contract_node
        )
        unsupported_contract = dataclasses.replace(
            bundle,
            nodes=MappingProxyType(unsupported_contract_nodes),
        )

        cases = {
            "broken-edge": broken_edge,
            "unknown-handler": unknown_handler,
            "unsupported-recovery": unsupported_recovery,
            "unsupported-node-contract": unsupported_contract,
        }
        for label, candidate_bundle in cases.items():
            with self.subTest(label=label):
                repository, _ = self.make_repo(
                    f"activation-negative-{label}"
                )
                task_id = f"activation-negative-{label}"
                args = dev_flow.build_parser().parse_args(
                    [
                        "start",
                        "must fail before revision one",
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
                        "--data-dir",
                        str(self.data),
                    ]
                )
                candidate_services = self._services_with_bundle(
                    services, candidate_bundle
                )
                with (
                    mock.patch.object(
                        dev_flow,
                        "_workflow_runtime_services",
                        candidate_services,
                    ),
                    self.assertRaises(dev_flow.FlowError) as raised,
                ):
                    args.handler(args)
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_ACTIVATION_INCOMPLETE",
                )
                self.assertFalse(
                    (
                        self.data / "tasks" / task_id / "state.json"
                    ).exists()
                )

    def test_active_start_pins_exact_bundle_and_deterministic_nodes(
        self,
    ) -> None:
        repository, _ = self.make_repo("active-v3-repository")
        services = self._services_with_active(
            "lite", "single-repository"
        )
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            response = self.cli(
                "start",
                "create a pinned v3 task",
                "--repo",
                str(repository),
                "--task-id",
                "active-v3",
                "--workspace-strategy",
                "in-place",
                "--change-category",
                "docs",
                "--target-path",
                "tracked.txt",
            )

        state = response["task"]
        bundle = services.catalog.resolve("lite", 4)
        self.assertEqual(state["schema_version"], 3)
        self.assertEqual(
            state["execution_profile"], "single-repository"
        )
        self.assertNotIn("orchestration", state)
        self.assertEqual(
            state["workflow_ref"],
            {
                "id": bundle.workflow_id,
                "version": bundle.workflow_version,
                "schema": bundle.graph["schema"],
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            },
        )
        first = dev_flow.build_v3_task_creation_fields(
            "active-v3",
            bundle,
            execution_profile="single-repository",
        )
        second = dev_flow.build_v3_task_creation_fields(
            "active-v3",
            bundle,
            execution_profile="single-repository",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            state["node_instances"], first["node_instances"]
        )
        self.assertEqual(
            [
                item["node_id"]
                for item in state["node_instances"]
                if item["state"] == "READY"
            ],
            ["INTAKE"],
        )
        dev_flow.validate_v3_task_state(state)

    def test_production_v4_profiles_create_exact_pinned_tasks(
        self,
    ) -> None:
        lite_repository, _ = self.make_repo("production-lite-v4")
        full_repository, _ = self.make_repo("production-full-v4")
        multi_repository_a, _ = self.make_repo(
            "production-full-v4-multi-a"
        )
        multi_repository_b, _ = self.make_repo(
            "production-full-v4-multi-b"
        )
        cases = (
            (
                "production-lite-v4",
                "lite",
                "single-repository",
                [
                    "--repo",
                    str(lite_repository),
                    "--workspace-strategy",
                    "in-place",
                    "--change-category",
                    "docs",
                    "--target-path",
                    "tracked.txt",
                ],
            ),
            (
                "production-full-v4",
                "full",
                "single-repository",
                [
                    "--repo",
                    str(full_repository),
                    "--workspace-strategy",
                    "worktree",
                ],
            ),
            (
                "production-full-v4-multi",
                "full",
                "multi-repository",
                [
                    "--repo",
                    str(multi_repository_a),
                    "--repo",
                    str(multi_repository_b),
                    "--workspace-strategy",
                    "worktree",
                ],
            ),
        )
        services = dev_flow._WORKFLOW_RUNTIME_SERVICES
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            for task_id, flow, execution_profile, arguments in cases:
                with self.subTest(task_id=task_id):
                    response = self.cli(
                        "start",
                        f"start {flow}@4 production profile",
                        "--task-id",
                        task_id,
                        *arguments,
                    )
                    task = response["task"]
                    bundle = services.catalog.resolve(flow, 4)
                    self.assertEqual(task["schema_version"], 3)
                    self.assertEqual(
                        task["execution_profile"],
                        execution_profile,
                    )
                    self.assertEqual(
                        task["workflow_ref"],
                        {
                            "id": flow,
                            "version": 4,
                            "schema": bundle.graph["schema"],
                            "graph_sha256": bundle.graph_sha256,
                            "bundle_sha256": bundle.bundle_sha256,
                        },
                    )

    def test_production_manifest_keeps_full_v3_multi_repository_inactive(
        self,
    ) -> None:
        services = dev_flow._WORKFLOW_RUNTIME_SERVICES
        activation = next(
            item
            for item in services.catalog.activations
            if item["workflow_id"] == "full"
            and item["workflow_version"] == 3
            and item["execution_profile"] == "multi-repository"
        )
        self.assertFalse(activation["active"])
        self.assertEqual(
            set(activation["required_suites"]),
            {
                *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                    "multi-repository"
                ],
                "action-policy",
                "action-recovery",
                "external-tool-capability-evidence",
            },
        )
        self.assertTrue(
            all(
                not profile["active"]
                for profile in services.catalog.activations
                if profile["workflow_version"] == 3
            )
        )

    def test_v3_gate_and_invalidation_contracts_cover_reachable_policies(
        self,
    ) -> None:
        services = dev_flow.workflow_runtime_services()
        expected_reducers = {
            "full": {
                "planning-forward": "reducer.v3-invalidate-plan/v1",
                "rework-plan": "reducer.v3-invalidate-plan/v1",
                "rework-implementation": (
                    "reducer.v3-invalidate-review/v1"
                ),
                "impact-reassess": (
                    "reducer.v3-impact-reassess/v1"
                ),
                "cancel": "reducer.v3-cancel/v1",
                "transition-cancel": "reducer.v3-cancel/v1",
            },
            "lite": {
                "rework-implementation": (
                    "reducer.v3-invalidate-review/v1"
                ),
                "cancel": "reducer.v3-cancel/v1",
                "transition-cancel": "reducer.v3-cancel/v1",
            },
        }
        required_repeat_actions = {
            "BASELINED": (
                "full.baselined.approve-baseline-fetch.v1"
            ),
            "INDEXED": (
                "full.indexed.approve-impact-degraded.v1"
            ),
            "WORKSPACE_READY": (
                "full.workspace-ready.approve-workspace.v1"
            ),
        }
        for flow, policies in expected_reducers.items():
            bundle = services.catalog.resolve(flow, 3)
            by_policy = {
                item["id"]: item
                for item in bundle.graph["edge_policies"]
            }
            for policy_id, reducer_id in policies.items():
                with self.subTest(
                    flow=flow, policy=policy_id
                ):
                    self.assertIn(
                        reducer_id,
                        {
                            reference["id"]
                            for reference in by_policy[
                                policy_id
                            ]["reducers"]
                        },
                    )
            gate_ids = {
                reference.identifier
                for reference in bundle.contracts
                if reference.registry == "gates"
            }
            self.assertTrue(gate_ids)
            self.assertTrue(
                all(
                    gate_id.endswith("-outcome/v1")
                    for gate_id in gate_ids
                )
            )
            for gate_id in gate_ids:
                callable_builder = (
                    services.handler_resolver.resolve_callable(
                        "gates", gate_id, "v1", "builder"
                    )
                )
                self.assertTrue(callable(callable_builder))
        full = services.catalog.resolve("full", 3)
        for node_id, action_id in required_repeat_actions.items():
            self.assertIn(
                action_id,
                {
                    item["id"]
                    for item in full.nodes[node_id]["actions"]
                },
            )

    def test_inactive_explicit_start_fails_before_first_commit(
        self,
    ) -> None:
        repository, _ = self.make_repo("inactive-v3-repository")
        args = dev_flow.build_parser().parse_args(
            [
                "start",
                "must not commit",
                "--repo",
                str(repository),
                "--task-id",
                "inactive-v3",
                "--workspace-strategy",
                "worktree",
                "--data-dir",
                str(self.data),
            ]
        )
        args.require_schema_v3 = True

        services = self._services_with_all_inactive()
        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                args.handler(args)

        self.assertEqual(
            raised.exception.code, "WORKFLOW_CREATION_INACTIVE"
        )
        self.assertFalse(
            (
                self.data
                / "tasks"
                / "inactive-v3"
                / "state.json"
            ).exists()
        )

    def test_v4_deactivation_does_not_strand_existing_pinned_task(
        self,
    ) -> None:
        services = self._services_with_all_inactive()
        bundle = services.catalog.resolve("full", 4)
        fields = dev_flow.build_v3_task_creation_fields(
            "already-pinned",
            bundle,
            execution_profile="multi-repository",
        )
        state = {
            "schema_version": 3,
            "task_id": "already-pinned",
            "revision": 1,
            "status": "INTAKE",
            "flow": "full",
            **copy.deepcopy(fields),
        }

        with mock.patch.object(
            dev_flow, "_workflow_runtime_services", services
        ):
            resolution = dev_flow.resolve_loaded_task_workflow(
                state, purpose="mutation"
            )

        self.assertEqual(
            resolution["bundle_sha256"], bundle.bundle_sha256
        )
        self.assertEqual(
            state["execution_profile"], "multi-repository"
        )
        self.assertEqual(
            state["orchestration"]["schema"],
            "dev-flow-orchestration-state/v1",
        )
        self.assertFalse(
            any(
                item["active"]
                for item in (
                    services.catalog.activations
                )
            )
        )

    def test_pure_transition_uses_engine_node_lifecycle_and_outbox(
        self,
    ) -> None:
        started = self._start_active_lite("v3-pure-transition")
        authorized, secret = self._authorize_manager_action(
            started["task_id"],
            started["revision"],
            "task.transition",
        )
        preview = self.cli(
            "transition",
            "v3-pure-transition",
            "--expected-revision",
            str(authorized["revision"]),
            "--to",
            "BLOCKED",
            "--note",
            "waiting for a decision",
            "--preview",
        )
        request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": authorized["capability"][
                "capability_id"
            ],
            "task_id": started["task_id"],
            "manager_session_id": "v3-activation-manager",
            "action_id": "task.transition",
            "expected_revision": authorized["revision"],
            "request_nonce": "1" * 64,
        }
        try:
            applied = self._apply_with_manager_secret(
                "transition",
                "v3-pure-transition",
                "--expected-revision",
                str(authorized["revision"]),
                "--to",
                "BLOCKED",
                "--note",
                "waiting for a decision",
                "--confirm-intent",
                preview["preview"]["intent_id"],
                request=request,
                secret=secret,
            )
        finally:
            dev_flow._manager_zeroize(secret)

        self.assertEqual(applied["status"], "BLOCKED")
        states = {
            (item["node_id"], item["state"])
            for item in applied["node_instances"]
        }
        self.assertIn(("INTAKE", "SUCCEEDED"), states)
        self.assertIn(("BLOCKED", "BLOCKED"), states)
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / "v3-pure-transition"
                / "events.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        revision_events = [
            item
            for item in events
            if item["revision"] == applied["revision"]
        ]
        self.assertEqual(
            {item["type"] for item in revision_events},
            {
                "state_transitioned",
                "workflow_audit_fact",
                dev_flow.MANAGER_CAPABILITY_AUTHORIZED_EVENT,
            },
        )
        self.assertEqual(
            len(
                {
                    item["transaction_id"]
                    for item in revision_events
                }
            ),
            1,
        )

    def test_v3_handler_cannot_bypass_engine_write_scope(self) -> None:
        started = self._start_active_lite("v3-bypass")
        current = dev_flow.load_state("v3-bypass", self.data)
        candidate = copy.deepcopy(current)
        candidate["status"] = "BLOCKED"
        candidate["blocked"] = {
            "phase": "manual",
            "from_status": "INTAKE",
            "reason": "blocked",
            "details": [],
            "at": dev_flow.utc_now(),
        }
        candidate["requirement"] = "unauthorized replacement"

        with (
            dev_flow._task_lock(
                dev_flow._task_dir("v3-bypass", self.data)
            ),
            dev_flow._workspace_registry_lock(
                dev_flow.resolve_data_dir(self.data)
            ),
            self.assertRaises(dev_flow.FlowError) as raised,
        ):
            dev_flow._commit_state(
                current,
                candidate,
                dev_flow._task_dir("v3-bypass", self.data),
                "state_transitioned",
                {
                    "from": "INTAKE",
                    "to": "BLOCKED",
                    "note": "blocked",
                    "intent_id": "confirmed-by-command-boundary",
                },
            )

        self.assertEqual(
            raised.exception.code, "V3_ENGINE_COMMIT_PROOF_REQUIRED"
        )
        unchanged = dev_flow.load_state("v3-bypass", self.data)
        self.assertEqual(unchanged["revision"], started["revision"])
        self.assertNotEqual(
            unchanged["requirement"], "unauthorized replacement"
        )

    def test_cancel_action_is_engine_owned_after_activation_turns_off(
        self,
    ) -> None:
        started = self._start_active_lite("v3-cancel")
        authorized, secret = self._authorize_manager_action(
            started["task_id"],
            started["revision"],
            "task.cancel",
        )
        preview = self.cli(
            "cancel",
            "v3-cancel",
            "--expected-revision",
            str(authorized["revision"]),
            "--reason",
            "superseded",
            "--preview",
        )
        request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": authorized["capability"][
                "capability_id"
            ],
            "task_id": started["task_id"],
            "manager_session_id": "v3-activation-manager",
            "action_id": "task.cancel",
            "expected_revision": authorized["revision"],
            "request_nonce": "2" * 64,
        }
        try:
            applied = self._apply_with_manager_secret(
                "cancel",
                "v3-cancel",
                "--expected-revision",
                str(authorized["revision"]),
                "--reason",
                "superseded",
                "--confirm-intent",
                preview["preview"]["intent_id"],
                request=request,
                secret=secret,
            )
        finally:
            dev_flow._manager_zeroize(secret)

        self.assertEqual(applied["status"], "CANCELLED")
        self.assertTrue(
            any(
                item["node_id"] == "CANCELLED"
                and item["state"] == "SUCCEEDED"
                for item in applied["node_instances"]
            )
        )
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / started["task_id"]
                / "events.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        reducer_facts = [
            item
            for item in events
            if item["revision"] == applied["revision"]
            and item["type"] == "workflow_audit_fact"
            and item["payload"]["fact_type"]
            == "registered-reducer-applied"
        ]
        self.assertTrue(reducer_facts)
        self.assertEqual(
            reducer_facts[-1]["payload"]["fact"]["handler"]["id"],
            "reducer.v3-cancel/v1",
        )

    def test_same_node_gate_uses_registered_outcome_and_reducer(
        self,
    ) -> None:
        started = self._start_active_lite("v3-lite-gate")
        authorized, secret = self._authorize_manager_action(
            started["task_id"],
            started["revision"],
            "task.preflight",
        )
        preview = self.cli(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(authorized["revision"]),
            "--preview",
        )
        capability = authorized["capability"]
        preflight_request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": capability["capability_id"],
            "task_id": started["task_id"],
            "manager_session_id": "v3-activation-manager",
            "action_id": "task.preflight",
            "expected_revision": authorized["revision"],
            "request_nonce": "3" * 64,
        }
        try:
            preflighted = self._apply_with_manager_secret(
                "preflight",
                started["task_id"],
                "--expected-revision",
                str(authorized["revision"]),
                "--confirm-preview",
                preview["transition_preview"]["token"],
                request=preflight_request,
                secret=secret,
            )
            gate_request = {
                "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
                "capability_id": capability["capability_id"],
                "task_id": started["task_id"],
                "manager_session_id": "v3-activation-manager",
                "action_id": "gate.approve",
                "expected_revision": preflighted["revision"],
                "request_nonce": "4" * 64,
            }
            approved = self._apply_with_manager_secret(
                "approve",
                started["task_id"],
                "--expected-revision",
                str(preflighted["revision"]),
                "--gate",
                "lite",
                "--note",
                "approve the current lite evidence",
                request=gate_request,
                secret=secret,
            )
        finally:
            dev_flow._manager_zeroize(secret)

        persisted = dev_flow.load_state(started["task_id"], self.data)
        self.assertEqual(persisted["status"], "PREFLIGHTED")
        self.assertIn("lite", persisted["approvals"])
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / started["task_id"]
                / "events.jsonl"
            )
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        facts = {
            item["payload"]["fact_type"]
            for item in events
            if item["revision"] == approved["revision"]
            and item["type"] == "workflow_audit_fact"
        }
        self.assertIn("pure-command-approval-built", facts)
        self.assertIn("registered-reducer-applied", facts)
        self.assertIn("pinned-action-gate-resolved", facts)
