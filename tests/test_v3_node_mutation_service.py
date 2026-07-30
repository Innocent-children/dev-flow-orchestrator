from __future__ import annotations

import copy
import dataclasses
import json

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class V3NodeMutationServiceTests(DevFlowTestCase):
    def _orchestration(self) -> dict:
        return {
            "schema": "dev-flow-orchestration-state/v1",
            "accepted_results": {},
            "artifacts": {},
            "assignments": {},
            "barriers": {},
            "current_results": {},
            "dispatch": {},
            "expansion": None,
            "integration": None,
            "integration_verification": None,
            "leases": {},
            "manager_capabilities": {},
            "pending_retries": {},
            "quiescence_proofs": {},
            "review": None,
        }

    def _base_state(self, task_id: str = "v3-node-mutation") -> dict:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        return {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 7,
            "status": "IMPLEMENTING",
            "flow": "full",
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="multi-repository",
                )
            ),
            "orchestration": self._orchestration(),
        }

    def _map_candidate(self, state: dict) -> tuple[dict, str]:
        candidate = copy.deepcopy(state)
        node_instance_id = "repository-node-a"
        candidate["node_instances"].append(
            {
                "node_instance_id": node_instance_id,
                "node_id": "IMPLEMENTING",
                "state": "PENDING",
                "dependencies": [],
                "attempts": [],
                "repository_id": "repository-a",
            }
        )
        candidate["node_instances"].sort(
            key=lambda item: item["node_instance_id"].encode("utf-8")
        )
        candidate["orchestration"]["expansion"] = {
            "schema": "dev-flow-repository-map-expansion/v1",
            "task_id": state["task_id"],
            "workflow_bundle_sha256": state["workflow_ref"][
                "bundle_sha256"
            ],
            "plan_id": "plan-1",
            "dag_sha256": "3" * 64,
            "semantic_input_sha256": "4" * 64,
            "map_node_id": "map.repositories/v1",
            "map_epoch": 1,
            "repository_set": ["repository-a"],
            "children": [
                {
                    "node_instance_id": node_instance_id,
                    "node_id": "IMPLEMENTING",
                    "repository_id": "repository-a",
                    "repository_identity_sha256": "5" * 64,
                    "map_epoch": 1,
                    "dependencies": [],
                }
            ],
        }
        return candidate, node_instance_id

    def _ready_state(self) -> tuple[dict, str]:
        state, node_instance_id = self._map_candidate(
            self._base_state()
        )
        node = self._node(state, node_instance_id)
        node["state"] = "READY"
        return state, node_instance_id

    def _dependent_map_state(self) -> tuple[dict, str, str]:
        state = self._base_state("v3-frontier")
        first_id = "repository-node-a"
        second_id = "repository-node-b"
        children = (
            (first_id, "repository-a", []),
            (second_id, "repository-b", [first_id]),
        )
        for identifier, repository_id, dependencies in children:
            state["node_instances"].append(
                {
                    "node_instance_id": identifier,
                    "node_id": "IMPLEMENTING",
                    "state": "PENDING",
                    "dependencies": list(dependencies),
                    "attempts": [],
                    "repository_id": repository_id,
                }
            )
        state["node_instances"].sort(
            key=lambda item: item["node_instance_id"].encode("utf-8")
        )
        state["orchestration"]["expansion"] = {
            "schema": "dev-flow-repository-map-expansion/v1",
            "task_id": state["task_id"],
            "workflow_bundle_sha256": state["workflow_ref"][
                "bundle_sha256"
            ],
            "plan_id": "plan-frontier",
            "dag_sha256": "3" * 64,
            "semantic_input_sha256": "4" * 64,
            "map_node_id": "map.repositories/v1",
            "map_epoch": 1,
            "repository_set": ["repository-a", "repository-b"],
            "children": [
                {
                    "node_instance_id": identifier,
                    "node_id": "IMPLEMENTING",
                    "repository_id": repository_id,
                    "repository_identity_sha256": (
                        "5" * 64
                        if repository_id == "repository-a"
                        else "6" * 64
                    ),
                    "map_epoch": 1,
                    "dependencies": list(dependencies),
                }
                for identifier, repository_id, dependencies in children
            ],
        }
        state["orchestration"]["manager_capabilities"][
            "capability-frontier"
        ] = {
            "scope": "manager",
            "used_request_nonce_sha256s": [],
        }
        return state, first_id, second_id

    def _frontier_payload(self, state: dict) -> dict:
        facts = dict(dev_flow.v3_frontier_ready_facts(state))
        return {
            "operation": dev_flow.V3_NODE_MUTATION_FRONTIER_READY,
            "plan_id": facts["plan_id"],
            "dag_sha256": facts["dag_sha256"],
            "map_epoch": facts["map_epoch"],
            "node_instance_ids": list(facts["node_instance_ids"]),
            "dependency_result_ids": copy.deepcopy(
                facts["dependency_result_ids"]
            ),
            "frontier_sha256": facts["frontier_sha256"],
        }

    def _apply_map_invalidation_projection(
        self, candidate: dict, facts: object
    ) -> None:
        projection = dev_flow._workflow_transition_public(
            facts["orchestration_projection"]
        )
        candidate["orchestration"].update(projection)

    def _attempt_candidate(
        self, state: dict, node_instance_id: str
    ) -> dict:
        candidate = copy.deepcopy(state)
        node = self._node(candidate, node_instance_id)
        attempt = len(node["attempts"]) + 1
        input_sha256 = f"{attempt:x}".rjust(64, "0")
        node["state"] = "RUNNING"
        node["attempts"].append(
            {
                "attempt": attempt,
                "state": "RUNNING",
                "input_sha256": input_sha256,
                "result_refs": [],
                **(
                    {"previous_attempt": attempt - 1}
                    if attempt > 1
                    else {}
                ),
                "runtime_handle": {
                    "schema": "dev-flow-runtime-handle/v1",
                    "handle_id": f"runtime-{attempt}",
                    "kind": "controller-runtime",
                    "task_id": state["task_id"],
                    "node_instance_id": node_instance_id,
                    "attempt": attempt,
                    "repository_id": "repository-a",
                },
            }
        )
        orchestration = candidate["orchestration"]
        orchestration["assignments"][f"assignment-{attempt}"] = {
            "node_instance_id": node_instance_id,
            "attempt": attempt,
        }
        orchestration["dispatch"][f"assignment-{attempt}"] = {
            "runtime_handle_id": f"runtime-{attempt}"
        }
        orchestration["leases"][f"lease-{attempt}"] = {
            "node_instance_id": node_instance_id,
            "attempt": attempt,
        }
        return candidate

    def _result_candidate(
        self,
        state: dict,
        node_instance_id: str,
        *,
        outcome: str = "FAILED",
    ) -> dict:
        candidate = copy.deepcopy(state)
        node = self._node(candidate, node_instance_id)
        attempt = node["attempts"][-1]
        attempt_number = attempt["attempt"]
        result_id = f"result-{attempt_number}"
        node["state"] = outcome
        attempt["state"] = outcome
        attempt["result_refs"].append(
            {
                "schema": "dev-flow-node-result-reference/v1",
                "result_id": result_id,
                "task_id": state["task_id"],
                "bundle_sha256": state["workflow_ref"][
                    "bundle_sha256"
                ],
                "node_instance_id": node_instance_id,
                "attempt": attempt_number,
                "input_sha256": attempt["input_sha256"],
                "output_sha256": "2" * 64,
                "locator": f"artifacts/{result_id}.json",
            }
        )
        orchestration = candidate["orchestration"]
        orchestration["artifacts"][result_id] = {
            "locator": f"artifacts/{result_id}.json"
        }
        accepted_result = {
            "result_id": result_id,
            "assignment_id": f"assignment-{attempt_number}",
            "node_instance_id": node_instance_id,
            "attempt": attempt_number,
            "output_sha256": "2" * 64,
            "worktree_sha256": "3" * 64,
            "changed_paths_sha256": "4" * 64,
            "verification_sha256": "5" * 64,
            "outcome": outcome,
        }
        orchestration["accepted_results"][result_id] = {
            "result": accepted_result,
            "controller_observation": (
                dev_flow.seal_v3_controller_result_observation(
                    result=accepted_result,
                    verified_output=accepted_result,
                    observed_at_revision=state["revision"],
                )
            ),
        }
        orchestration["current_results"][
            node_instance_id
        ] = result_id
        return candidate

    def _retry_candidate(
        self, state: dict, node_instance_id: str
    ) -> dict:
        candidate = copy.deepcopy(state)
        self._node(candidate, node_instance_id)["state"] = "READY"
        candidate["orchestration"]["pending_retries"][
            node_instance_id
        ] = {
            "previous_attempt": 1,
            "next_attempt": 2,
        }
        return candidate

    @staticmethod
    def _node(state: dict, node_instance_id: str) -> dict:
        return next(
            item
            for item in state["node_instances"]
            if item["node_instance_id"] == node_instance_id
        )

    def _evaluate(
        self,
        old_state: dict,
        candidate: dict,
        operation: str,
        *,
        event_id: str = "event-node-mutation",
    ) -> object:
        authorized_old = copy.deepcopy(old_state)
        authorized_candidate = copy.deepcopy(candidate)
        self._manager_authorization(
            authorized_old,
            authorized_candidate,
            operation=operation,
        )
        return dev_flow.evaluate_v3_node_mutation(
            authorized_old,
            authorized_candidate,
            operation=operation,
            event_id=event_id,
            event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                operation
            ],
            payload={"operation": operation},
        )

    def _manager_authorization(
        self,
        old_state: dict,
        candidate: dict,
        *,
        operation: str,
    ) -> object:
        sequence = getattr(self, "_manager_authorization_sequence", 0) + 1
        self._manager_authorization_sequence = sequence
        action_id = dev_flow.V3_NODE_MUTATION_MANAGER_ACTIONS[
            operation
        ]
        manager_session_id = f"manager-session-{sequence}"
        secret = bytearray(b"M" * 32)
        verifier = dev_flow.issue_manager_capability(
            task_id=old_state["task_id"],
            issued_for_task_revision=old_state["revision"],
            manager_session_id=manager_session_id,
            allowed_actions=[action_id],
            ttl_ns=1_000_000_000,
            wall_time_ns=1_000_000,
            monotonic_time_ns=500_000,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
            secret_transport="local-secret-channel",
            operator_confirmation_sha256=f"{sequence:064x}",
            issuance_audit_sha256=f"{sequence + 1:064x}",
            manager_secret=secret,
        )
        old_state["orchestration"]["manager_capabilities"][
            verifier.capability_id
        ] = verifier.as_persistent_dict()
        candidate["orchestration"]["manager_capabilities"][
            verifier.capability_id
        ] = verifier.as_persistent_dict()
        authorization = dev_flow.consume_manager_capability_request(
            verifier,
            {
                "schema": (
                    dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA
                ),
                "capability_id": verifier.capability_id,
                "task_id": old_state["task_id"],
                "manager_session_id": manager_session_id,
                "action_id": action_id,
                "expected_revision": old_state["revision"],
                "request_nonce": f"{sequence + 2:064x}",
            },
            {
                "schema": dev_flow.AGENT_PRINCIPAL_SCHEMA,
                "role": "manager",
                "session_id": manager_session_id,
                "os_user_identity_sha256": "d" * 64,
                "host_identity_sha256": "e" * 64,
            },
            manager_secret=secret,
            wall_time_ns=1_000_001,
            monotonic_time_ns=500_001,
            clock_id=dev_flow.MANAGER_CAPABILITY_CLOCK_ID,
        )
        candidate["orchestration"]["manager_capabilities"][
            verifier.capability_id
        ] = authorization.verifier_state.as_persistent_dict()
        return dev_flow.seal_v3_manager_authorization(authorization)

    def test_closed_operations_produce_exact_frozen_authorizations(
        self,
    ) -> None:
        base = self._base_state()
        expanded, node_instance_id = self._map_candidate(base)
        map_authorization = self._evaluate(
            base,
            expanded,
            dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
        )
        self.assertEqual(
            map_authorization.affected_node_instance_ids,
            (node_instance_id,),
        )
        self.assertIn(
            "/orchestration/expansion",
            map_authorization.allowed_pointers,
        )
        self.assertTrue(
            any(
                pointer.startswith("/node_instances/")
                for pointer in map_authorization.allowed_pointers
            )
        )
        self.assertNotEqual(
            map_authorization.before_node_instances_sha256,
            map_authorization.after_node_instances_sha256,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            map_authorization.operation = "FORGED"

        ready, node_instance_id = self._ready_state()
        started = self._attempt_candidate(ready, node_instance_id)
        attempt_authorization = self._evaluate(
            ready,
            started,
            dev_flow.V3_NODE_MUTATION_ATTEMPT_START,
        )
        self.assertEqual(
            attempt_authorization.affected_node_instance_ids,
            (node_instance_id,),
        )
        self.assertIn(
            "/orchestration/leases/lease-1",
            attempt_authorization.allowed_pointers,
        )

        accepted = self._result_candidate(
            started, node_instance_id
        )
        result_authorization = self._evaluate(
            started,
            accepted,
            dev_flow.V3_NODE_MUTATION_RESULT_ACCEPT,
        )
        self.assertIn(
            "/orchestration/accepted_results/result-1",
            result_authorization.allowed_pointers,
        )

        retry = self._retry_candidate(
            accepted, node_instance_id
        )
        retry_authorization = self._evaluate(
            accepted,
            retry,
            dev_flow.V3_NODE_MUTATION_RETRY_READY,
        )
        self.assertEqual(
            retry_authorization.allowed_pointers[0],
            f"/node_instances/"
            f"{dev_flow._v3_node_mutation_index(retry, node_instance_id)}"
            "/state",
        )
        self.assertTrue(
            retry_authorization.allowed_pointers[1].startswith(
                "/orchestration/manager_capabilities/"
            )
        )
        self.assertEqual(
            retry_authorization.allowed_pointers[2],
            f"/orchestration/pending_retries/{node_instance_id}",
        )

    def test_frontier_ready_is_complete_recomputed_and_dependency_safe(
        self,
    ) -> None:
        state, first_id, second_id = self._dependent_map_state()
        candidate = copy.deepcopy(state)
        self._node(candidate, first_id)["state"] = "READY"
        candidate["orchestration"]["manager_capabilities"][
            "capability-frontier"
        ]["used_request_nonce_sha256s"] = ["a" * 64]
        authorization = dev_flow.evaluate_v3_node_mutation(
            state,
            candidate,
            operation=dev_flow.V3_NODE_MUTATION_FRONTIER_READY,
            event_id="event-frontier",
            event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                dev_flow.V3_NODE_MUTATION_FRONTIER_READY
            ],
            payload=self._frontier_payload(state),
        )
        self.assertEqual(
            authorization.affected_node_instance_ids, (first_id,)
        )

        invalid_candidates = []
        dependency_unsatisfied = copy.deepcopy(state)
        self._node(dependency_unsatisfied, second_id)[
            "state"
        ] = "READY"
        invalid_candidates.append(dependency_unsatisfied)

        arbitrary_superset = copy.deepcopy(state)
        self._node(arbitrary_superset, first_id)["state"] = "READY"
        self._node(arbitrary_superset, second_id)["state"] = "READY"
        invalid_candidates.append(arbitrary_superset)

        rogue_coarse = copy.deepcopy(state)
        self._node(rogue_coarse, first_id)["state"] = "READY"
        coarse = next(
            node
            for node in rogue_coarse["node_instances"]
            if node.get("repository_id") is None
            and node["state"] == "PENDING"
        )
        coarse["state"] = "READY"
        invalid_candidates.append(rogue_coarse)

        for invalid in invalid_candidates:
            invalid["orchestration"]["manager_capabilities"][
                "capability-frontier"
            ]["used_request_nonce_sha256s"] = ["a" * 64]
            with self.subTest(
                changed=[
                    node["node_instance_id"]
                    for node in invalid["node_instances"]
                    if node["state"] == "READY"
                ]
            ):
                with self.assertRaises(
                    dev_flow.TransitionEngineError
                ) as raised:
                    dev_flow.evaluate_v3_node_mutation(
                        state,
                        invalid,
                        operation=(
                            dev_flow.V3_NODE_MUTATION_FRONTIER_READY
                        ),
                        event_id="event-frontier-invalid",
                        event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                            dev_flow.V3_NODE_MUTATION_FRONTIER_READY
                        ],
                        payload=self._frontier_payload(state),
                    )
                self.assertEqual(
                    raised.exception.code,
                    "V3_FRONTIER_SELECTION_INVALID",
                )

        forged_payload = self._frontier_payload(state)
        forged_payload["node_instance_ids"] = [second_id]
        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.evaluate_v3_node_mutation(
                state,
                candidate,
                operation=dev_flow.V3_NODE_MUTATION_FRONTIER_READY,
                event_id="event-frontier-forged-facts",
                event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                    dev_flow.V3_NODE_MUTATION_FRONTIER_READY
                ],
                payload=forged_payload,
            )
        self.assertEqual(
            raised.exception.code, "V3_FRONTIER_FACTS_MISMATCH"
        )

    def test_map_invalidation_is_two_phase_and_allows_newer_epoch(
        self,
    ) -> None:
        old_state, old_node_id = self._map_candidate(
            self._base_state("v3-map-invalidate")
        )
        old_state["orchestration"]["manager_capabilities"][
            "capability-map"
        ] = {
            "scope": "manager",
            "used_request_nonce_sha256s": [],
        }
        stale_facts = dev_flow.v3_map_invalidation_facts(
            old_state,
            phase="STALE",
            reason="repository-set-drift",
            minimum_successor_map_epoch=4,
            manager_authorization_id="authorization-stale",
        )
        stale_candidate = copy.deepcopy(old_state)
        self._apply_map_invalidation_projection(
            stale_candidate, stale_facts
        )
        stale_candidate["orchestration"]["manager_capabilities"][
            "capability-map"
        ]["used_request_nonce_sha256s"] = ["a" * 64]
        stale_authorization = dev_flow.evaluate_v3_node_mutation(
            old_state,
            stale_candidate,
            operation=dev_flow.V3_NODE_MUTATION_MAP_INVALIDATE,
            event_id="event-map-stale",
            event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                dev_flow.V3_NODE_MUTATION_MAP_INVALIDATE
            ],
            payload=dict(stale_facts["event_payload"]),
        )
        self.assertEqual(
            stale_authorization.affected_node_instance_ids,
            (old_node_id,),
        )
        self.assertEqual(
            self._node(stale_candidate, old_node_id)["state"],
            "PENDING",
        )
        self.assertFalse(
            stale_candidate["orchestration"]["expansion"]["current"]
        )

        retired_state = copy.deepcopy(stale_candidate)
        retired_state["revision"] = 8
        retired_facts = dev_flow.v3_map_invalidation_facts(
            retired_state,
            phase="RETIRED",
            manager_authorization_id="authorization-retired",
        )
        retired_candidate = copy.deepcopy(retired_state)
        self._apply_map_invalidation_projection(
            retired_candidate, retired_facts
        )
        self._node(retired_candidate, old_node_id)[
            "state"
        ] = "SKIPPED"
        retired_candidate["orchestration"]["manager_capabilities"][
            "capability-map"
        ]["used_request_nonce_sha256s"] = ["a" * 64, "b" * 64]
        dev_flow.evaluate_v3_node_mutation(
            retired_state,
            retired_candidate,
            operation=dev_flow.V3_NODE_MUTATION_MAP_INVALIDATE,
            event_id="event-map-retired",
            event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                dev_flow.V3_NODE_MUTATION_MAP_INVALIDATE
            ],
            payload=dict(retired_facts["event_payload"]),
        )
        self.assertEqual(
            retired_candidate["orchestration"]["expansion"][
                "retired_at_revision"
            ],
            9,
        )

        successor = copy.deepcopy(retired_candidate)
        successor_id = "repository-node-c"
        successor["node_instances"].append(
            {
                "node_instance_id": successor_id,
                "node_id": "IMPLEMENTING",
                "state": "PENDING",
                "dependencies": [],
                "attempts": [],
                "repository_id": "repository-c",
            }
        )
        successor["node_instances"].sort(
            key=lambda item: item["node_instance_id"].encode("utf-8")
        )
        successor["orchestration"]["expansion"] = {
            "schema": "dev-flow-repository-map-expansion/v1",
            "task_id": retired_state["task_id"],
            "workflow_bundle_sha256": retired_state["workflow_ref"][
                "bundle_sha256"
            ],
            "plan_id": "plan-successor",
            "dag_sha256": "7" * 64,
            "semantic_input_sha256": "8" * 64,
            "map_node_id": "map.repositories/v1",
            "map_epoch": 7,
            "repository_set": ["repository-c"],
            "children": [
                {
                    "node_instance_id": successor_id,
                    "node_id": "IMPLEMENTING",
                    "repository_id": "repository-c",
                    "repository_identity_sha256": "9" * 64,
                    "map_epoch": 7,
                    "dependencies": [],
                }
            ],
        }
        successor["orchestration"]["manager_capabilities"][
            "capability-map"
        ]["used_request_nonce_sha256s"] = [
            "a" * 64,
            "b" * 64,
            "c" * 64,
        ]
        dev_flow.evaluate_v3_node_mutation(
            retired_candidate,
            successor,
            operation=dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
            event_id="event-map-successor",
            event_type=dev_flow.V3_NODE_MUTATION_EVENT_TYPES[
                dev_flow.V3_NODE_MUTATION_MAP_EXPAND
            ],
            payload={
                "operation": dev_flow.V3_NODE_MUTATION_MAP_EXPAND
            },
        )
        self.assertEqual(
            self._node(successor, old_node_id)["state"], "SKIPPED"
        )

    def test_failure_matrix_rejects_wrong_operation_event_and_history(
        self,
    ) -> None:
        base = self._base_state()
        expanded, node_instance_id = self._map_candidate(base)

        cases = []
        cases.append(
            (
                "unknown-operation",
                lambda: dev_flow.evaluate_v3_node_mutation(
                    base,
                    expanded,
                    operation="DELETE_NODE",
                    event_id="event-1",
                    event_type="orchestration_plan_expanded",
                ),
                "V3_NODE_MUTATION_OPERATION_UNSUPPORTED",
            )
        )
        cases.append(
            (
                "wrong-event",
                lambda: dev_flow.evaluate_v3_node_mutation(
                    base,
                    expanded,
                    operation=dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                    event_id="event-1",
                    event_type="orchestration_worker_assigned",
                ),
                "V3_NODE_MUTATION_EVENT_MISMATCH",
            )
        )
        changed_status = copy.deepcopy(expanded)
        changed_status["status"] = "VERIFYING"
        cases.append(
            (
                "task-status",
                lambda: self._evaluate(
                    base,
                    changed_status,
                    dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                ),
                "V3_NODE_MUTATION_STATUS_CHANGE",
            )
        )
        modified_old = copy.deepcopy(expanded)
        original_id = next(
            item["node_instance_id"]
            for item in modified_old["node_instances"]
            if item["node_instance_id"] != node_instance_id
        )
        self._node(modified_old, original_id)["state"] = "FAILED"
        cases.append(
            (
                "map-rewrites-old-node",
                lambda: self._evaluate(
                    base,
                    modified_old,
                    dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                ),
                "V3_MAP_EXPANSION_INVALID",
            )
        )
        out_of_scope = copy.deepcopy(expanded)
        out_of_scope["orchestration"]["reconciliation_probes"] = {}
        cases.append(
            (
                "caller-invented-write-scope",
                lambda: self._evaluate(
                    base,
                    out_of_scope,
                    dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                ),
                "V3_NODE_MUTATION_OUT_OF_SCOPE",
            )
        )
        rogue_child = copy.deepcopy(expanded)
        rogue_child["orchestration"]["expansion"][
            "children"
        ].append(
            {
                "node_instance_id": "repository-node-rogue",
                "node_id": "IMPLEMENTING",
                "repository_id": "repository-rogue",
                "dependencies": [],
            }
        )
        cases.append(
            (
                "map-extra-child-in-allowed-root",
                lambda: self._evaluate(
                    base,
                    rogue_child,
                    dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                ),
                # Exact bundle/state validation is deliberately earlier than
                # the operation policy and rejects the malformed child first.
                "ORCHESTRATION_EXPANSION_INVALID",
            )
        )
        manager_old = copy.deepcopy(base)
        manager_old["orchestration"]["manager_capabilities"][
            "capability-1"
        ] = {
            "scope": "manager",
            "used_request_nonce_sha256s": [],
        }
        manager_candidate, _manager_node = self._map_candidate(
            manager_old
        )
        manager_candidate["orchestration"]["manager_capabilities"][
            "capability-1"
        ] = {
            "scope": "worker",
            "used_request_nonce_sha256s": ["6" * 64],
        }
        cases.append(
            (
                "manager-scope-rewrite-in-allowed-root",
                lambda: self._evaluate(
                    manager_old,
                    manager_candidate,
                    dev_flow.V3_NODE_MUTATION_MAP_EXPAND,
                ),
                "V3_NODE_MUTATION_MANAGER_NONCE_INVALID",
            )
        )
        ready, node_instance_id = self._ready_state()
        started = self._attempt_candidate(ready, node_instance_id)
        extra_assignment = copy.deepcopy(started)
        extra_assignment["orchestration"]["assignments"][
            "assignment-rogue"
        ] = {
            "node_instance_id": "another-node",
            "attempt": 1,
        }
        cases.append(
            (
                "attempt-extra-assignment-in-allowed-root",
                lambda: self._evaluate(
                    ready,
                    extra_assignment,
                    dev_flow.V3_NODE_MUTATION_ATTEMPT_START,
                ),
                "V3_ATTEMPT_START_ORCHESTRATION_INVALID",
            )
        )
        invalid_attempt = copy.deepcopy(started)
        self._node(invalid_attempt, node_instance_id)["attempts"][
            0
        ]["result_refs"] = [
            {
                "schema": "dev-flow-node-result-reference/v1",
                "result_id": "forged",
                "task_id": ready["task_id"],
                "bundle_sha256": ready["workflow_ref"][
                    "bundle_sha256"
                ],
                "node_instance_id": node_instance_id,
                "attempt": 1,
                "input_sha256": "1".rjust(64, "0"),
                "output_sha256": "3" * 64,
                "locator": "forged",
            }
        ]
        cases.append(
            (
                "attempt-start-with-output",
                lambda: self._evaluate(
                    ready,
                    invalid_attempt,
                    dev_flow.V3_NODE_MUTATION_ATTEMPT_START,
                ),
                "V3_ATTEMPT_START_INVALID",
            )
        )
        accepted = self._result_candidate(
            started, node_instance_id
        )
        extra_result = copy.deepcopy(accepted)
        extra_result["orchestration"]["accepted_results"][
            "result-rogue"
        ] = {
            "node_instance_id": "another-node",
            "outcome": "FAILED",
        }
        extra_result["orchestration"]["artifacts"][
            "result-rogue"
        ] = {"locator": "artifacts/result-rogue.json"}
        cases.append(
            (
                "result-extra-ledger-entry-in-allowed-root",
                lambda: self._evaluate(
                    started,
                    extra_result,
                    dev_flow.V3_NODE_MUTATION_RESULT_ACCEPT,
                ),
                "V3_RESULT_ACCEPT_ORCHESTRATION_INVALID",
            )
        )
        rewritten = copy.deepcopy(accepted)
        self._node(rewritten, node_instance_id)["attempts"][0][
            "input_sha256"
        ] = "4" * 64
        self._node(rewritten, node_instance_id)["attempts"][0][
            "result_refs"
        ][0]["input_sha256"] = "4" * 64
        cases.append(
            (
                "result-rewrites-input",
                lambda: self._evaluate(
                    started,
                    rewritten,
                    dev_flow.V3_NODE_MUTATION_RESULT_ACCEPT,
                ),
                "V3_ATTEMPT_HISTORY_REWRITE",
            )
        )
        successful = self._result_candidate(
            started, node_instance_id, outcome="SUCCEEDED"
        )
        invalid_retry = self._retry_candidate(
            successful, node_instance_id
        )
        cases.append(
            (
                "retry-success",
                lambda: self._evaluate(
                    successful,
                    invalid_retry,
                    dev_flow.V3_NODE_MUTATION_RETRY_READY,
                ),
                "V3_RETRY_READY_INVALID",
            )
        )

        for label, action, code in cases:
            with self.subTest(label=label):
                with self.assertRaises(
                    dev_flow.TransitionEngineError
                ) as raised:
                    action()
                self.assertEqual(raised.exception.code, code)

    def test_authorization_revalidation_rejects_forged_stale_and_changed(
        self,
    ) -> None:
        old_state = self._base_state()
        candidate, _node_instance_id = self._map_candidate(old_state)
        event_id = "event-auth"
        operation = dev_flow.V3_NODE_MUTATION_MAP_EXPAND
        event_type = dev_flow.V3_NODE_MUTATION_EVENT_TYPES[operation]
        payload = {"operation": operation}
        self._manager_authorization(
            old_state,
            candidate,
            operation=operation,
        )
        authorization = dev_flow.evaluate_v3_node_mutation(
            old_state,
            candidate,
            operation=operation,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        validated = dev_flow.validate_v3_node_mutation_authorization(
            authorization,
            old_state,
            candidate,
            operation=operation,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
        self.assertIs(validated, authorization)

        forged = dataclasses.replace(
            authorization, candidate_sha256="f" * 64
        )
        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_v3_node_mutation_authorization(
                forged,
                old_state,
                candidate,
                operation=operation,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_NODE_MUTATION_AUTHORIZATION_INVALID",
        )

        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_v3_node_mutation_authorization(
                authorization,
                old_state,
                candidate,
                operation=operation,
                event_id="another-event",
                event_type=event_type,
                payload=payload,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_NODE_MUTATION_EVENT_MISMATCH",
        )

        stale_old = copy.deepcopy(old_state)
        stale_candidate = copy.deepcopy(candidate)
        stale_old["revision"] += 1
        stale_candidate["revision"] += 1
        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_v3_node_mutation_authorization(
                authorization,
                stale_old,
                stale_candidate,
                operation=operation,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_NODE_MUTATION_REVISION_STALE",
        )

        altered = copy.deepcopy(candidate)
        altered["orchestration"]["expansion"]["extra"] = "changed"
        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_v3_node_mutation_authorization(
                authorization,
                old_state,
                altered,
                operation=operation,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_NODE_MUTATION_CANDIDATE_MISMATCH",
        )

        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_v3_node_mutation_authorization(
                object(),
                old_state,
                candidate,
                operation=operation,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
        self.assertEqual(
            raised.exception.code,
            "V3_TRANSITION_SERVICE_REQUIRED",
        )

    def test_generic_commit_rejects_node_and_orchestration_changes(
        self,
    ) -> None:
        old_state = self._base_state()
        node_candidate, _node_instance_id = self._map_candidate(
            old_state
        )
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._commit_state(
                old_state,
                node_candidate,
                self.root,
                "orchestration_plan_expanded",
            )
        self.assertEqual(
            raised.exception.code, "V3_ENGINE_COMMIT_PROOF_REQUIRED"
        )

        orchestration_candidate = copy.deepcopy(old_state)
        orchestration_candidate["orchestration"]["expansion"] = {}
        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._commit_state(
                old_state,
                orchestration_candidate,
                self.root,
                "orchestration_plan_expanded",
            )
        self.assertEqual(
            raised.exception.code, "V3_ENGINE_COMMIT_PROOF_REQUIRED"
        )

    def test_superseded_formal_commit_cannot_bypass_engine_proof(
        self,
    ) -> None:
        base = self._base_state("v3-node-commit")
        expanded, node_instance_id = self._map_candidate(base)
        self._node(expanded, node_instance_id)["state"] = "READY"
        old_state = self._attempt_candidate(
            expanded, node_instance_id
        )
        candidate = self._result_candidate(
            old_state, node_instance_id
        )
        manager_authorization = self._manager_authorization(
            old_state,
            candidate,
            operation=dev_flow.V3_NODE_MUTATION_RESULT_ACCEPT,
        )
        task_dir = dev_flow._task_dir(
            old_state["task_id"], self.data
        )
        task_dir.mkdir(parents=True)
        dev_flow._atomic_write_json(
            task_dir / "state.json", old_state
        )

        def bind_event_id(value: dict, event_id: str) -> None:
            value["orchestration"]["accepted_results"][
                "result-1"
            ]["receipt"] = {"event_id": event_id}

        data_root = dev_flow.resolve_data_dir(self.data)
        before_state = (task_dir / "state.json").read_bytes()
        with (
            dev_flow._task_lock(task_dir),
            dev_flow._workspace_registry_lock(data_root),
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                dev_flow.commit_v3_node_event(
                    old_state,
                    candidate,
                    task_dir,
                    "orchestration_result_accepted",
                    {
                        "operation": "RESULT_ACCEPT",
                        "manager_authorization_id": (
                            manager_authorization.authorization
                            .authorization_id
                        ),
                    },
                    operation=(
                        dev_flow.V3_NODE_MUTATION_RESULT_ACCEPT
                    ),
                    manager_authorization=manager_authorization,
                    finalize_event_binding=bind_event_id,
                )
        self.assertEqual(
            raised.exception.code,
            "V3_ENGINE_COMMIT_PROOF_INVALID",
        )
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), before_state
        )
        self.assertFalse((task_dir / "events.jsonl").exists())
