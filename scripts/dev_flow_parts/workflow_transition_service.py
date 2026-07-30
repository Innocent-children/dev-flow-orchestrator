# Loaded by scripts/dev_flow.py before the controller transaction fragment.
# This service makes every committed workflow movement prove itself against
# the task-pinned V4 graph and bounded kernel writes.
from __future__ import annotations

import copy
import contextlib
import contextvars
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Sequence


def _build_engine_lock_capability_broker(
) -> tuple[
    contextvars.ContextVar[tuple[object, ...]],
    Callable[[object, str], object],
    Callable[[object], None],
    Callable[[Sequence[str]], list[dict[str, object]]],
]:
    """Track real package lock contexts with opaque process-local objects."""

    held_capabilities: contextvars.ContextVar[tuple[object, ...]] = (
        contextvars.ContextVar(
            "dev_flow_engine_held_lock_capabilities", default=()
        )
    )
    registry_lock = threading.Lock()
    registry: dict[
        int, tuple[object, str, str, int, str]
    ] = {}

    def issue(directory: object, lock_name: str) -> object:
        path = str(Path(directory).resolve(strict=False))
        capability = object()
        record = (
            capability,
            path,
            lock_name,
            threading.get_ident(),
            secrets.token_hex(32),
        )
        with registry_lock:
            registry[id(capability)] = record
        return capability

    def revoke(capability: object) -> None:
        with registry_lock:
            registered = registry.get(id(capability))
            if (
                registered is not None
                and registered[0] is capability
            ):
                del registry[id(capability)]

    def snapshot(
        held_directories: Sequence[str],
    ) -> list[dict[str, object]]:
        capabilities = held_capabilities.get()
        if len(capabilities) != len(held_directories):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_LOCK_CAPABILITY_INVALID",
                "held lock paths lack exact opaque lock capabilities",
            )
        result: list[dict[str, object]] = []
        thread_id = threading.get_ident()
        with registry_lock:
            for index, (capability, directory) in enumerate(
                zip(capabilities, held_directories)
            ):
                registered = registry.get(id(capability))
                canonical_directory = str(
                    Path(directory).resolve(strict=False)
                )
                if (
                    registered is None
                    or registered[0] is not capability
                    or registered[1] != canonical_directory
                    or registered[3] != thread_id
                ):
                    raise TransitionEngineError(
                        "V4_ENGINE_COMMIT_LOCK_CAPABILITY_INVALID",
                        "held lock capability is absent, copied, or stale",
                        details={"lock_index": index},
                    )
                result.append(
                    {
                        "capability_id": registered[4],
                        "path": registered[1],
                        "lock_name": registered[2],
                        "controller_thread_id": registered[3],
                    }
                )
        return result

    return held_capabilities, issue, revoke, snapshot


(
    _engine_held_lock_capabilities,
    _engine_lock_capability_issue,
    _engine_lock_capability_revoke,
    _engine_lock_capability_snapshot,
) = _build_engine_lock_capability_broker()


_workflow_transition_event_actions = {
    "baseline_recorded": "baseline",
    "gate_approved": "approve-route",
    "index_recorded": "record-index",
    "preflight_recorded": "preflight",
    "review_snapshot_recorded": "review-snapshot",
    "route_set": "set-route",
    "task_cancelled": "cancel",
    "workspace_prepared": "prepare-workspace",
}


def _workflow_transition_public(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _workflow_transition_public(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_workflow_transition_public(item) for item in value]
    return value


def _workflow_transition_bundle(
    state: Mapping[str, object],
) -> object:
    resolution = resolve_loaded_task_workflow(
        state, purpose="mutation"
    )
    digest = resolution.get("bundle_sha256")
    if not isinstance(digest, str):
        raise TransitionEngineError(
            "WORKFLOW_RESOLUTION_FAILED",
            "task-pinned workflow has no exact bundle identity",
        )
    return workflow_runtime_services().catalog.resolve_identity(digest)


def _workflow_transition_graph(bundle: object) -> dict[str, object]:
    graph = getattr(bundle, "graph", None)
    edges = getattr(bundle, "edges", None)
    if not isinstance(graph, Mapping) or not isinstance(edges, tuple):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "resolved workflow bundle lacks a validated expanded graph",
        )
    result = copy.deepcopy(_workflow_transition_public(graph))
    if not isinstance(result, dict):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID", "workflow graph is not an object"
        )
    result["edges"] = copy.deepcopy(_workflow_transition_public(edges))
    result["graph_sha256"] = getattr(bundle, "graph_sha256", None)
    result["bundle_sha256"] = getattr(bundle, "bundle_sha256", None)
    return result


def _workflow_transition_v4_graph(
    bundle: object,
) -> dict[str, object]:
    """Grant the non-extensible kernel its node-lifecycle write path."""

    graph = _workflow_transition_graph(bundle)
    edges = graph.get("edges")
    if not isinstance(edges, list):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "schema-v4 workflow graph has no expanded edge array",
        )
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        invalidates = [
            item
            for item in edge.get("kernel_invalidates", ())
            if isinstance(item, str)
        ]
        if "/node_instances" not in invalidates:
            invalidates.append("/node_instances")
        edge["kernel_invalidates"] = sorted(set(invalidates))
    return graph


def _workflow_transition_action(
    event_type: str,
    payload: Mapping[str, object],
    *,
    target: str,
    candidates: Sequence[Mapping[str, object]],
) -> str:
    if event_type == "state_transitioned":
        action = payload.get("action")
        if isinstance(action, str) and action:
            return action
        return "transition-cancel" if target == "CANCELLED" else "transition"
    if event_type == "lite_risk_escalation_required":
        attempted = payload.get("attempted_target")
        if isinstance(attempted, str) and attempted:
            return f"lite-risk-{attempted.lower()}"
    declared = _workflow_transition_event_actions.get(event_type)
    if declared is not None:
        return declared
    actions = {
        trigger.get("id")
        for edge in candidates
        for trigger in (edge.get("trigger"),)
        if isinstance(trigger, Mapping)
        and isinstance(trigger.get("id"), str)
    }
    if len(actions) == 1:
        return next(iter(actions))
    raise TransitionEngineError(
        "WORKFLOW_MOVEMENT_ACTION_UNKNOWN",
        "state movement cannot be bound to one declared action",
        details={
            "event_type": event_type,
            "target": target,
            "actions": sorted(actions),
        },
    )


def v4_workflow_confirmation_mode(
    state: Mapping[str, object],
    source: str,
    target: str,
    *,
    action: str = "transition",
) -> str:
    """Return confirmation only from the task-pinned schema-v4 edge."""

    if state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise TransitionEngineError(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "pinned confirmation lookup requires task schema v4",
        )
    bundle = _workflow_transition_bundle(state)
    action_id = (
        "transition-cancel"
        if action == "transition" and target == "CANCELLED"
        else action
    )
    matches = tuple(
        edge
        for edge in bundle.legal_edges(source)
        if edge.get("target") == target
        and isinstance(edge.get("trigger"), Mapping)
        and edge["trigger"].get("id") == action_id
    )
    if len(matches) != 1:
        raise TransitionEngineError(
            "EDGE_SELECTION_AMBIGUOUS"
            if len(matches) > 1
            else "EDGE_NOT_AVAILABLE",
            "confirmation lookup did not resolve one pinned edge",
            details={
                "source": source,
                "target": target,
                "action_id": action_id,
                "edge_ids": sorted(
                    str(edge.get("id")) for edge in matches
                ),
            },
        )
    confirmation = matches[0].get("confirmation")
    if not isinstance(confirmation, str) or not confirmation:
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "pinned edge does not declare a confirmation mode",
            details={"edge_id": matches[0].get("id")},
        )
    return confirmation


def _workflow_transition_instance_input_sha256(
    state: Mapping[str, object],
    edge: Mapping[str, object],
    node_instance_id: str,
    attempt: int,
) -> str:
    return _sha256_contract(
        {
            "contract": "dev-flow-node-attempt-input/v1",
            "task_id": state.get("task_id"),
            "bundle_sha256": (
                state.get("workflow_ref", {}).get("bundle_sha256")
                if isinstance(state.get("workflow_ref"), Mapping)
                else None
            ),
            "base_revision": state.get("revision"),
            "edge_id": edge.get("id"),
            "node_instance_id": node_instance_id,
            "attempt": attempt,
        }
    )


def _workflow_transition_advance_nodes(
    candidate: Mapping[str, object],
    edge: Mapping[str, object],
) -> dict[str, object]:
    result = copy.deepcopy(_workflow_transition_public(candidate))
    if not isinstance(result, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID", "transition candidate must be an object"
        )
    instances = result.get("node_instances")
    if not isinstance(instances, list):
        raise TransitionEngineError(
            "NODE_INSTANCE_INVALID",
            "schema-v4 transition requires node instances",
        )
    source = edge.get("source")
    target = edge.get("target")
    if not isinstance(source, str) or not isinstance(target, str):
        raise TransitionEngineError(
            "WORKFLOW_GRAPH_INVALID",
            "selected edge must identify source and target nodes",
        )
    active_states = {
        "READY",
        "RUNNING",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
        "BLOCKED",
    }
    source_instances = [
        item
        for item in instances
        if isinstance(item, dict)
        and item.get("node_id") == source
        and item.get("state") in active_states
    ]
    if len(source_instances) != 1:
        raise TransitionEngineError(
            "NODE_INSTANCE_CURRENT_MISMATCH",
            "task status must resolve to one current node instance",
            details={
                "source": source,
                "active_instances": [
                    item.get("node_instance_id")
                    for item in source_instances
                ],
            },
        )
    source_instance = source_instances[0]
    source_attempts = source_instance.get("attempts")
    if not isinstance(source_attempts, list):
        raise TransitionEngineError(
            "NODE_ATTEMPT_INVALID",
            "current node instance has no attempt history",
        )
    if source_attempts:
        latest = source_attempts[-1]
        if (
            not isinstance(latest, dict)
            or latest.get("state")
            in {"SUCCEEDED", "FAILED", "SKIPPED"}
        ):
            raise TransitionEngineError(
                "NODE_ATTEMPT_TERMINAL",
                "terminal node attempts cannot be changed in place",
                details={
                    "node_instance_id": source_instance.get(
                        "node_instance_id"
                    )
                },
            )
        latest["state"] = "SUCCEEDED"
    else:
        source_attempts.append(
            {
                "attempt": 1,
                "state": "SUCCEEDED",
                "input_sha256": (
                    _workflow_transition_instance_input_sha256(
                        result,
                        edge,
                        str(source_instance["node_instance_id"]),
                        1,
                    )
                ),
                "result_refs": [],
            }
        )
    source_instance["state"] = "SUCCEEDED"

    pending_targets = [
        item
        for item in instances
        if isinstance(item, dict)
        and item.get("node_id") == target
        and item.get("state") == "PENDING"
    ]
    if len(pending_targets) > 1:
        raise TransitionEngineError(
            "NODE_INSTANCE_TARGET_AMBIGUOUS",
            "more than one pending target node instance is present",
            details={"target": target},
        )
    if pending_targets:
        target_instance = pending_targets[0]
    else:
        workflow_ref = result.get("workflow_ref")
        if not isinstance(workflow_ref, Mapping):
            raise TransitionEngineError(
                "WORKFLOW_REF_INVALID",
                "schema-v4 task has no pinned workflow identity",
            )
        occurrence = (
            sum(
                1
                for item in instances
                if isinstance(item, Mapping)
                and item.get("node_id") == target
            )
            + 1
        )
        target_instance = {
            "node_instance_id": _workflow_runtime_node_instance_id(
                str(result.get("task_id")),
                str(workflow_ref.get("bundle_sha256")),
                target,
                occurrence,
            ),
            "node_id": target,
            "state": "PENDING",
            "dependencies": [],
            "attempts": [],
        }
        instances.append(target_instance)
    target_instance["dependencies"] = [
        str(source_instance["node_instance_id"])
    ]
    target_state = (
        "BLOCKED"
        if target == "BLOCKED"
        else (
            "SUCCEEDED"
            if target in {"DONE", "CANCELLED"}
            else "READY"
        )
    )
    target_instance["state"] = target_state
    if target_state in {"BLOCKED", "SUCCEEDED"}:
        target_attempts = target_instance.get("attempts")
        if not isinstance(target_attempts, list):
            raise TransitionEngineError(
                "NODE_ATTEMPT_INVALID",
                "target node instance has no attempt history",
            )
        target_attempts.append(
            {
                "attempt": len(target_attempts) + 1,
                "state": target_state,
                "input_sha256": (
                    _workflow_transition_instance_input_sha256(
                        result,
                        edge,
                        str(target_instance["node_instance_id"]),
                        len(target_attempts) + 1,
                    )
                ),
                "result_refs": [],
                **(
                    {"previous_attempt": len(target_attempts)}
                    if target_attempts
                    else {}
                ),
            }
        )
    instances.sort(
        key=lambda item: str(item.get("node_instance_id", "")).encode(
            "utf-8"
        )
    )
    return result


def _workflow_transition_supported_contracts(
    bundle: object,
) -> Mapping[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for reference in getattr(bundle, "contracts", ()):
        key = f"{reference.registry}:{reference.identifier}"
        result.setdefault(key, set()).add(reference.version)
    return {
        key: tuple(sorted(versions))
        for key, versions in result.items()
    }


def _workflow_transition_authorized_paths(
    state: Mapping[str, object],
) -> tuple[str, ...]:
    paths: set[str] = set()
    for repository in state.get("repositories", ()):
        if not isinstance(repository, Mapping):
            continue
        for field in (
            "path",
            "canonical_path",
        ):
            value = repository.get(field)
            if isinstance(value, str) and value:
                paths.add(value)
        for field in (
            "analysis_workspace",
            "workspace",
        ):
            workspace = repository.get(field)
            if not isinstance(workspace, Mapping):
                continue
            for path_field in ("path", "worktree", "workspace"):
                value = workspace.get(path_field)
                if isinstance(value, str) and value:
                    paths.add(value)
    return tuple(sorted(paths))


def _workflow_transition_locks(
    state: Mapping[str, object],
) -> tuple[bool, bool, bool]:
    held = tuple(_HELD_LOCK_DIRECTORIES.get())
    task_directory = _held_task_directory()
    task_held = (
        task_directory is not None
        and task_directory.name == state.get("task_id")
    )
    workspace_held = any(
        task_directory is None
        or value != str(task_directory.resolve(strict=False))
        for value in held
    )
    return task_held, workspace_held, workspace_held


def _workflow_transition_exact_state_delta(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    excluded_paths: Sequence[str] = (),
) -> dict[str, object]:
    """Encode one exact, deterministic state candidate as a bounded delta."""

    excluded = tuple(excluded_paths)
    set_values: dict[str, object] = {}
    remove_paths: list[str] = []
    for pointer in json_pointer_diff(before, after):
        if any(_path_is_within(pointer, root) for root in excluded):
            continue
        present, value = _transition_engine_pointer_get(after, pointer)
        if present:
            set_values[pointer] = copy.deepcopy(
                _workflow_transition_public(value)
            )
        else:
            remove_paths.append(pointer)
    return {
        "set": set_values,
        "remove": remove_paths,
        "operations": [],
    }


def _workflow_transition_require_handler_version(
    registry: str,
    identifier: str,
    version: str | None,
) -> str:
    if not isinstance(version, str) or not version:
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_REFERENCE_INVALID",
            "schema-v4 handler references require an exact contract version",
            details={"registry": registry, "id": identifier},
        )
    return version


def _workflow_transition_handler_fact(
    registry: str,
    identifier: str,
    version: str,
    registration: object,
) -> dict[str, object]:
    return {
        "registry": registry,
        "id": identifier,
        "version": version,
        "implementation_sha256": getattr(
            registration, "implementation_sha256", None
        ),
    }


def _workflow_transition_guard_projection(
    candidate_state: Mapping[str, object],
    *,
    source: str,
    target: str,
    parameters: Mapping[str, object],
    multi_repository_authority_current: bool,
) -> dict[str, object]:
    result = copy.deepcopy(
        _workflow_transition_public(candidate_state)
    )
    if not isinstance(result, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "guard projection requires an object candidate",
        )
    result.update(
        {
            "source_status": source,
            "target_status": target,
            "action_parameters": copy.deepcopy(dict(parameters)),
            "note": parameters.get("note", parameters.get("reason")),
            "requires_note": parameters.get("requires_note"),
            "multi_repository_authority_current": (
                multi_repository_authority_current
            ),
        }
    )
    return result


def _workflow_transition_registered_guard_resolver(
    candidate_state: Mapping[str, object],
    *,
    source: str,
    target: str,
    parameters: Mapping[str, object],
    multi_repository_authority_current: bool,
) -> Callable[[str, str | None], Callable[..., GuardResult]]:
    package_resolver = workflow_runtime_services().handler_resolver

    def resolve(
        identifier: str, version_value: str | None
    ) -> Callable[..., GuardResult]:
        version = _workflow_transition_require_handler_version(
            "guards", identifier, version_value
        )
        registration = package_resolver.resolve(
            "guards", identifier, version
        )
        evaluator = package_resolver.resolve_callable(
            "guards", identifier, version, "evaluator"
        )
        declared_capabilities = tuple(
            getattr(registration, "capabilities", ())
        )
        queries = {
            capability: (
                lambda projection: copy.deepcopy(
                    _workflow_transition_public(projection)
                )
            )
            for capability in declared_capabilities
        }
        membrane = package_resolver.capability_membrane(
            "guards",
            identifier,
            version,
            queries=queries,
        )
        handler_fact = _workflow_transition_handler_fact(
            "guards", identifier, version, registration
        )

        def evaluate(
            _immutable_state: object,
            _immutable_evidence: object,
            _kernel_capability: object,
        ) -> GuardResult:
            state_value = copy.deepcopy(
                _workflow_transition_public(candidate_state)
            )
            if not isinstance(state_value, dict):
                raise TransitionEngineError(
                    "TASK_STATE_INVALID",
                    "registered guard requires an object state projection",
                )
            before_sha256 = _sha256_contract(state_value)
            projection = _workflow_transition_guard_projection(
                state_value,
                source=source,
                target=target,
                parameters=parameters,
                multi_repository_authority_current=(
                    multi_repository_authority_current
                ),
            )
            try:
                if identifier == "guard.baseline-current/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.blocked-resume/v1":
                    if not _guard_blocked_resume_target(
                        _freeze_contract_value(
                            projection,
                            "$registered_guard/resume_projection",
                        ),
                        membrane,
                    ):
                        blocked = state_value.get("blocked")
                        expected = (
                            blocked.get("from_status")
                            if isinstance(blocked, Mapping)
                            else None
                        )
                        raise FlowError(
                            "INVALID_TRANSITION",
                            (
                                "blocked task can only resume to its "
                                "recorded from_status"
                            ),
                            details={
                                "from": source,
                                "to": target,
                                "allowed": (
                                    [expected]
                                    if isinstance(expected, str)
                                    else []
                                ),
                            },
                        )
                    raw_result = evaluator(state_value, target)
                elif identifier == "guard.index-current/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.lite-approved/v1":
                    raw_result = evaluator(
                        state_value,
                        verify_worktree=(
                            source == "PREFLIGHTED"
                            and target == "IMPLEMENTING"
                        ),
                    )
                elif identifier == "guard.lite-risk-safe/v1":
                    data_dir = parameters.get("data_dir")
                    if data_dir is None:
                        task_directory = _held_task_directory()
                        if task_directory is not None:
                            data_dir = str(task_directory.parent.parent)
                    raw_result = evaluator(state_value, data_dir)
                elif identifier == "guard.plan-current/v1":
                    route_value = (
                        state_value.get("route") or {}
                    ).get("value")
                    artifact_kind = (
                        "direct-contract"
                        if route_value == "direct"
                        else "openspec-plan"
                    )
                    raw_result = evaluator(state_value, artifact_kind)
                elif identifier == "guard.preflight-current/v1":
                    records = []
                    for repository in state_value.get(
                        "repositories", ()
                    ):
                        if not isinstance(repository, dict):
                            raise FlowError(
                                "TASK_STATE_INVALID",
                                "repository projection is invalid",
                            )
                        records.append(
                            evaluator(
                                repository.get("preflight"),
                                f"preflight:{repository.get('id')}",
                            )
                        )
                    raw_result = records
                elif identifier == "guard.review-approved/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.review-current/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.route-approved/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.test-current/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.workspace-indexes-current/v1":
                    raw_result = evaluator(state_value)
                elif identifier == "guard.workspace-ready/v1":
                    raw_result = evaluator(state_value)
                elif identifier in {
                    "guard.note-required/v1",
                    "guard.multi-repository-barrier-current/v1",
                    "guard.multi-repository-cancellation-quiesced/v1",
                    "guard.multi-repository-integration-current/v1",
                    "guard.multi-repository-review-current/v1",
                }:
                    raw_result = evaluator(
                        _freeze_contract_value(
                            projection, "$registered_guard/projection"
                        ),
                        membrane,
                    )
                elif not declared_capabilities:
                    # New audited pure guards use the common immutable
                    # projection/capability contract and need no engine branch.
                    raw_result = evaluator(
                        _freeze_contract_value(
                            projection, "$registered_guard/projection"
                        ),
                        membrane,
                    )
                else:
                    raise TransitionEngineError(
                        "WORKFLOW_GUARD_ADAPTER_UNAVAILABLE",
                        "guard has no registered runtime implementation",
                        details=handler_fact,
                    )
            except FlowError as exc:
                return GuardResult(
                    False,
                    {"handler": handler_fact},
                    (
                        {
                            "code": exc.code,
                            "message": exc.message,
                            "details": exc.details,
                        },
                    ),
                )
            if _sha256_contract(state_value) != before_sha256:
                raise TransitionEngineError(
                    "GUARD_STATE_MUTATION",
                    "registered guard mutated its candidate projection",
                    details=handler_fact,
                )
            blocker_reason = None
            if isinstance(raw_result, bool):
                passed = raw_result
            elif (
                isinstance(raw_result, (list, tuple))
                and raw_result
                and isinstance(raw_result[0], bool)
            ):
                passed = raw_result[0]
                if len(raw_result) > 1 and isinstance(
                    raw_result[1], str
                ):
                    blocker_reason = raw_result[1]
            elif (
                identifier == "guard.lite-risk-safe/v1"
                and isinstance(raw_result, Mapping)
            ):
                passed = raw_result.get("decision") == "safe"
                if not passed:
                    blocker_reason = "live lite risk requires the full flow"
            else:
                passed = True
            declared_result_sha256 = (
                raw_result.get("sha256")
                if isinstance(raw_result, Mapping)
                else None
            )
            if (
                isinstance(declared_result_sha256, str)
                and len(declared_result_sha256) == 64
            ):
                # Evidence producers may include observation timestamps while
                # also returning their own stable semantic digest.  Bind that
                # digest so immediate preview/apply reevaluation is stable.
                result_sha256 = declared_result_sha256
            else:
                try:
                    result_sha256 = _sha256_contract(
                        _workflow_transition_public(raw_result)
                    )
                except TransitionEngineError:
                    result_sha256 = _sha256_contract(
                        {"result_type": type(raw_result).__name__}
                    )
            return GuardResult(
                passed,
                {
                    "handler": handler_fact,
                    "projection_sha256": before_sha256,
                    "result_sha256": result_sha256,
                },
                (
                    ()
                    if passed
                    else (
                        {
                            "code": "CURRENT_EVIDENCE_REQUIRED",
                            "message": (
                                blocker_reason
                                or "registered guard rejected current evidence"
                            ),
                        },
                    )
                ),
            )

        return evaluate

    return resolve


def _workflow_transition_registered_reducer_resolver(
    *,
    parameters: Mapping[str, object],
) -> Callable[[str, str | None], Callable[..., ReducerResult]]:
    package_resolver = workflow_runtime_services().handler_resolver

    def resolve(
        identifier: str, version_value: str | None
    ) -> Callable[..., ReducerResult]:
        version = _workflow_transition_require_handler_version(
            "reducers", identifier, version_value
        )
        registration = package_resolver.resolve(
            "reducers", identifier, version
        )
        reducer = package_resolver.resolve_callable(
            "reducers", identifier, version, "reducer"
        )
        membrane = package_resolver.capability_membrane(
            "reducers", identifier, version
        )
        handler_fact = _workflow_transition_handler_fact(
            "reducers", identifier, version, registration
        )

        def apply(
            projected: Mapping[str, object],
            edge: Mapping[str, object],
            action_outcome: ActionOutcome | None,
            _approval_outcome: ApprovalOutcome | None,
            _kernel_capability: object,
        ) -> ReducerResult:
            candidate_delta = (
                _workflow_transition_public(
                    action_outcome.proposed_state_delta
                )
                if action_outcome is not None
                else {"set": {}, "remove": [], "operations": []}
            )
            projection = {
                "source_status": edge.get("source", edge.get("from")),
                "target_status": edge.get("target", edge.get("to")),
                "candidate_delta": candidate_delta,
                "blocked": parameters.get("blocked"),
                "cancelled": parameters.get("cancelled"),
                "action_parameters": copy.deepcopy(dict(parameters)),
            }
            raw_delta = reducer(
                _freeze_contract_value(
                    projection, "$registered_reducer/projection"
                ),
                membrane,
            )
            if not isinstance(raw_delta, Mapping):
                raise TransitionEngineError(
                    "REDUCER_RESULT_INVALID",
                    "registered reducer must return a state delta object",
                    details=handler_fact,
                )
            normalized = _transition_engine_normalize_kernel_delta(
                raw_delta
            )
            candidate = copy.deepcopy(
                _workflow_transition_public(projected)
            )
            if not isinstance(candidate, dict):
                raise TransitionEngineError(
                    "REDUCER_RESULT_INVALID",
                    "registered reducer received a non-object state",
                    details=handler_fact,
                )
            kernel_paths = _transition_engine_kernel_write_paths(edge)
            kernel_set: dict[str, object] = {}
            kernel_remove: list[str] = []
            for pointer, item in normalized["set"].items():
                if pointer == "/status":
                    target_status = edge.get(
                        "target", edge.get("to")
                    )
                    if item != target_status:
                        raise TransitionEngineError(
                            "KERNEL_STATUS_WRITE_FORBIDDEN",
                            "registered reducer proposed a different edge target",
                            details={
                                **handler_fact,
                                "proposed": item,
                                "target": target_status,
                            },
                        )
                    continue
                if any(
                    _path_is_within(pointer, path)
                    for path in kernel_paths
                ):
                    kernel_set[pointer] = item
                else:
                    _transition_engine_pointer_set(
                        candidate, pointer, item
                    )
            for pointer in normalized["remove"]:
                if pointer == "/status":
                    raise TransitionEngineError(
                        "KERNEL_STATUS_WRITE_FORBIDDEN",
                        "a registered reducer cannot remove task status",
                        details=handler_fact,
                    )
                if any(
                    _path_is_within(pointer, path)
                    for path in kernel_paths
                ):
                    kernel_remove.append(pointer)
                else:
                    _transition_engine_pointer_remove(
                        candidate, pointer
                    )
            accepted_delta = {
                "set": kernel_set,
                "remove": kernel_remove,
                "operations": normalized["operations"],
            }
            return ReducerResult(
                candidate,
                (
                    AuditFact(
                        "registered-reducer-applied",
                        {
                            "handler": handler_fact,
                            "delta_sha256": _sha256_contract(
                                normalized
                            ),
                        },
                    ),
                ),
                accepted_delta,
            )

        return apply

    return resolve


_workflow_transition_gate_names = MappingProxyType(
    {
        "gate.baseline-fetch-outcome/v1": "baseline-fetch",
        "gate.baseline-fetch/v1": "baseline-fetch",
        "gate.impact-degraded-outcome/v1": "impact-degraded",
        "gate.impact-degraded/v1": "impact-degraded",
        "gate.lite-outcome/v1": "lite",
        "gate.lite/v1": "lite",
        "gate.plan-outcome/v1": "plan",
        "gate.plan/v1": "plan",
        "gate.review-outcome/v1": "review",
        "gate.review/v1": "review",
        "gate.route-outcome/v1": "route",
        "gate.route/v1": "route",
        "gate.workspace-outcome/v1": "workspace",
        "gate.workspace/v1": "workspace",
    }
)


def _workflow_transition_current_approval(
    state: Mapping[str, object],
    *,
    gate_id: str,
    action_id: str,
) -> dict[str, object]:
    state_value = copy.deepcopy(_workflow_transition_public(state))
    if not isinstance(state_value, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "approval currentness requires an object state",
        )
    gate_name = _workflow_transition_gate_names.get(gate_id)
    if gate_name is None:
        raise TransitionEngineError(
            "WORKFLOW_GATE_ADAPTER_UNAVAILABLE",
            "registered gate has no currentness adapter",
            details={"gate_id": gate_id},
        )
    try:
        if gate_name == "baseline-fetch":
            if action_id == "approve-baseline-fetch":
                approval = _require_gate(
                    state_value, "baseline-fetch"
                )
                expected = _preflight_remote_evidence_sha256(
                    state_value
                )
                if approval.get("preflight_remote_sha256") != expected:
                    raise FlowError(
                        "STALE_APPROVAL",
                        "baseline-fetch approval is not current",
                    )
                dirty = [
                    repository.get("id")
                    for repository in state_value.get(
                        "repositories", ()
                    )
                    if (
                        repository.get("preflight") or {}
                    ).get("dirty")
                ]
                if dirty and approval.get("dirty_allowed") is not True:
                    raise FlowError(
                        "DIRTY_NOT_APPROVED",
                        "dirty preflight snapshots require explicit approval",
                        details={"repository_ids": dirty},
                    )
            else:
                approval = _require_baseline_fetch_approval(
                    state_value
                )
        elif gate_name == "impact-degraded":
            approval = _require_gate(
                state_value, "impact-degraded"
            )
        elif gate_name == "lite":
            approval = _require_lite_gate(
                state_value,
                verify_worktree=action_id == "approve-lite",
            )
        elif gate_name == "plan":
            route_value = (
                state_value.get("route") or {}
            ).get("value")
            artifact_kind = (
                "direct-contract"
                if route_value == "direct"
                else "openspec-plan"
            )
            approval, _artifact = _require_current_plan_gate(
                state_value, artifact_kind
            )
        elif gate_name == "review":
            approval, _report = _require_review_gate(state_value)
        elif gate_name == "route":
            approval, _impact = _require_route_gate(state_value)
        elif gate_name == "workspace":
            if action_id == "approve-workspace":
                approval, artifact = (
                    _require_gate_for_latest_artifact(
                        state_value,
                        "workspace",
                        "workspace-plan",
                    )
                )
                generation = int(
                    (state_value.get("workspace") or {}).get(
                        "generation", 0
                    )
                )
                if (
                    approval.get("artifact_id")
                    != artifact.get("artifact_id")
                    or approval.get("workspace_generation")
                    != generation
                ):
                    raise FlowError(
                        "STALE_APPROVAL",
                        "workspace approval is not current",
                    )
            else:
                approval = _require_workspace_ready(state_value)
        else:
            raise TransitionEngineError(
                "WORKFLOW_GATE_ADAPTER_UNAVAILABLE",
                "registered gate has no currentness adapter",
                details={"gate_id": gate_id},
            )
    except FlowError as exc:
        raise TransitionEngineError(
            exc.code, exc.message, details=exc.details
        ) from exc
    return copy.deepcopy(approval)


def _workflow_transition_registered_approval_outcome(
    state: Mapping[str, object],
    *,
    gate_reference: Mapping[str, object],
    edge_id: str,
    action_id: str,
    intent_id: str | None = None,
) -> ApprovalOutcome:
    gate_id = gate_reference.get("id")
    gate_version = gate_reference.get("version")
    if not isinstance(gate_id, str):
        raise TransitionEngineError(
            "WORKFLOW_CONTRACT_REFERENCE_INVALID",
            "selected gate has no stable identity",
        )
    version = _workflow_transition_require_handler_version(
        "gates",
        gate_id,
        gate_version if isinstance(gate_version, str) else None,
    )
    package_resolver = workflow_runtime_services().handler_resolver
    registration = package_resolver.resolve(
        "gates", gate_id, version
    )
    builder = package_resolver.resolve_callable(
        "gates", gate_id, version, "builder"
    )
    membrane = package_resolver.capability_membrane(
        "gates", gate_id, version
    )
    approval = _workflow_transition_current_approval(
        state, gate_id=gate_id, action_id=action_id
    )
    if intent_id is not None:
        approval["intent_id"] = intent_id
    built = builder(
        _freeze_contract_value(
            {
                "gate_id": gate_id,
                "proposed_edge_id": edge_id,
                "approval": approval,
            },
            "$registered_gate/projection",
        ),
        membrane,
    )
    if not isinstance(built, Mapping):
        raise TransitionEngineError(
            "APPROVAL_OUTCOME_INVALID",
            "registered gate builder must return an outcome object",
            details={"gate_id": gate_id, "version": version},
        )
    if (
        built.get("gate_id") != gate_id
        or built.get("proposed_edge_id") != edge_id
        or not isinstance(built.get("approval"), Mapping)
    ):
        raise TransitionEngineError(
            "APPROVAL_OUTCOME_INVALID",
            "registered gate builder changed the pinned outcome identity",
            details={"gate_id": gate_id, "version": version},
        )
    handler_fact = _workflow_transition_handler_fact(
        "gates", gate_id, version, registration
    )
    built_approval = copy.deepcopy(
        _workflow_transition_public(built["approval"])
    )
    if not isinstance(built_approval, dict):
        raise TransitionEngineError(
            "APPROVAL_OUTCOME_INVALID",
            "registered gate builder returned an invalid approval",
            details=handler_fact,
        )
    return ApprovalOutcome(
        gate_id,
        edge_id,
        built_approval,
        audit_facts=(
            AuditFact(
                "registered-approval-outcome-current",
                {
                    "handler": handler_fact,
                    "approval_id": built_approval.get("approval_id"),
                },
            ),
        ),
    )


def _workflow_transition_manager_evaluation_input_v1(
    old_state: Mapping[str, object],
    *,
    event_type: str,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Prepare one immutable manager nonce base before engine evaluation."""

    durable = copy.deepcopy(_workflow_transition_public(old_state))
    if not isinstance(durable, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "manager engine input requires an object task state",
        )
    try:
        prepared = _manager_engine_evaluation_state_v1(
            durable, event_type=event_type
        )
    except FlowError as exc:
        raise TransitionEngineError(
            exc.code, exc.message, details=exc.details
        ) from exc
    if prepared is None:
        return durable, None
    if (
        prepared.get("task_id") != durable.get("task_id")
        or prepared.get("revision") != durable.get("revision")
        or prepared.get("status") != durable.get("status")
        or prepared.get("workflow_ref") != durable.get("workflow_ref")
    ):
        raise TransitionEngineError(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "manager pre-evaluation input changed the task binding",
        )
    return prepared, durable


def _workflow_transition_manager_neutral_candidate_v1(
    desired_state: Mapping[str, object],
    intent_state: Mapping[str, object] | None,
) -> dict[str, object]:
    """Remove only the pre-evaluated nonce delta from preview identity."""

    desired = copy.deepcopy(_workflow_transition_public(desired_state))
    if not isinstance(desired, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "manager-neutral candidate must be an object",
        )
    if intent_state is None:
        return desired
    if "orchestration" in intent_state:
        desired["orchestration"] = copy.deepcopy(
            _workflow_transition_public(intent_state["orchestration"])
        )
    else:
        desired.pop("orchestration", None)
    return desired


def evaluate_v4_workflow_movement(
    old_state: Mapping[str, object],
    desired_state: Mapping[str, object],
    *,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    preview_only: bool = False,
    compare_desired: bool = True,
    reducer_parameters: Mapping[str, object] | None = None,
    manager_intent_state: Mapping[str, object] | None = None,
) -> TransitionEvaluation:
    """Authoritatively evaluate one v4 movement against its pinned bundle."""

    if old_state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise TransitionEngineError(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "authoritative v4 transition service requires schema version 4",
        )
    source = old_state.get("status")
    target = desired_state.get("status")
    if not isinstance(source, str) or not isinstance(target, str):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "workflow movement requires string source and target states",
        )
    if source == target:
        raise TransitionEngineError(
            "WORKFLOW_MOVEMENT_REQUIRED",
            "v4 transition service requires a task-status movement",
        )
    controlled_targets = {
        "VERIFYING",
        "REVIEWING",
        "FINALIZING",
        "DONE",
        "CANCELLED",
    }
    multi_repository_authority_current = (
        old_state.get("execution_profile") != "multi-repository"
    )
    if (
        old_state.get("execution_profile") == "multi-repository"
        and target in controlled_targets
    ):
        task_directory = _held_task_directory()
        if task_directory is None:
            raise TransitionEngineError(
                "MULTI_REPOSITORY_AUTHORITY_LOCK_REQUIRED",
                "multi-repository controlled movement requires the held task and workspace authority path",
            )
        try:
            orchestration_status = (
                _osc_fresh_terminal_orchestration_status(
                    task_directory,
                    old_state,
                    target_status=target,
                )
            )
        except FlowError as exc:
            raise TransitionEngineError(
                exc.code,
                exc.message,
                details=exc.details,
            ) from exc
        if orchestration_status.get("ready") is not True:
            raise TransitionEngineError(
                "MULTI_REPOSITORY_MOVEMENT_BLOCKED",
                "multi-repository movement lacks current controller-owned orchestration authority",
                details={
                    "source": source,
                    "target": target,
                    "blockers": orchestration_status.get(
                        "blockers", []
                    ),
                    "snapshot_id": orchestration_status.get(
                        "snapshot_id"
                    ),
                },
            )
        multi_repository_authority_current = True
    bundle = _workflow_transition_bundle(old_state)
    candidates = tuple(
        edge
        for edge in bundle.legal_edges(source)
        if edge.get("target") == target
    )
    parameters = dict(payload or {})
    supplied_intent = parameters.pop("intent_id", None)
    # Confirmation is transport metadata, not semantic action input.  Binding
    # it into the engine intent would make preview and apply identities differ
    # merely because apply carries the preview token it is meant to verify.
    parameters.pop("confirmation_mode", None)
    parameters.pop("evidence_sha256", None)
    handler_parameters = {
        **parameters,
        **dict(reducer_parameters or {}),
    }
    action_id = _workflow_transition_action(
        event_type,
        parameters,
        target=target,
        candidates=candidates,
    )
    eligible = tuple(
        edge
        for edge in candidates
        if isinstance(edge.get("trigger"), Mapping)
        and edge["trigger"].get("id") == action_id
    )
    if len(eligible) != 1:
        raise TransitionEngineError(
            "EDGE_SELECTION_AMBIGUOUS"
            if len(eligible) > 1
            else "EDGE_NOT_AVAILABLE",
            "v4 movement does not identify one pinned edge",
            details={
                "source": source,
                "target": target,
                "action_id": action_id,
                "edge_ids": sorted(
                    str(edge.get("id")) for edge in eligible
                ),
            },
        )
    selected = eligible[0]
    edge_id = str(selected.get("id"))
    desired = copy.deepcopy(_workflow_transition_public(desired_state))
    if not isinstance(desired, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID", "desired task state must be an object"
        )
    intent_desired = (
        _workflow_transition_manager_neutral_candidate_v1(
            desired, manager_intent_state
        )
    )
    handler_parameters.setdefault("blocked", desired.get("blocked"))
    handler_parameters.setdefault("cancelled", desired.get("cancelled"))
    desired_workspace = desired.get("workspace")
    if isinstance(desired_workspace, Mapping):
        reassessed_at = desired_workspace.get("reassessed_at")
        if reassessed_at is not None:
            handler_parameters.setdefault("reassessed_at", reassessed_at)
    candidate_delta = _workflow_transition_exact_state_delta(
        old_state,
        desired,
        excluded_paths=(
            "/status",
            "/node_instances",
            "/revision",
            "/updated_at",
        ),
    )
    if compare_desired:
        declared_paths = tuple(
            path
            for path in selected.get("allowed_state_writes", ())
            if isinstance(path, str)
        ) + _transition_engine_kernel_write_paths(selected)
        proposed_paths = tuple(
            sorted(
                {
                    *candidate_delta["set"],
                    *candidate_delta["remove"],
                }
            )
        )
        unexpected = tuple(
            path
            for path in proposed_paths
            if not any(
                _path_is_within(path, allowed)
                for allowed in declared_paths
            )
        )
        if unexpected:
            raise TransitionEngineError(
                "TRANSITION_HANDLER_OUT_OF_SCOPE",
                "handler candidate contains changes outside the pinned edge",
                details={
                    "edge_id": edge_id,
                    "unexpected_paths": list(unexpected),
                },
            )

    def apply_kernel_effects(
        candidate: Mapping[str, object],
        edge: Mapping[str, object],
        _action: object,
        _approval: object,
        _action_parameters: Mapping[str, object],
    ) -> KernelEffectResult:
        advanced = _workflow_transition_advance_nodes(candidate, edge)
        return KernelEffectResult(
            advanced,
            (
                AuditFact(
                    "node-lifecycle-advanced",
                    {
                        "edge_id": edge.get("id"),
                        "source": edge.get("source"),
                        "target": edge.get("target"),
                    },
                ),
            ),
        )

    graph = _workflow_transition_v4_graph(bundle)
    guard_parameters = {
        **parameters,
        "requires_note": selected.get("requires_note") is True,
    }
    engine = TransitionEngine(
        graph,
        guard_resolver=_workflow_transition_registered_guard_resolver(
            intent_desired,
            source=source,
            target=target,
            parameters=guard_parameters,
            multi_repository_authority_current=(
                multi_repository_authority_current
            ),
        ),
        reducer_resolver=_workflow_transition_registered_reducer_resolver(
            parameters=handler_parameters
        ),
        kernel_effect_applier=apply_kernel_effects,
    )
    requested_paths = _workflow_transition_authorized_paths(old_state)
    side_effects = tuple(
        item
        for item in selected.get("side_effects", ())
        if isinstance(item, str)
    )
    evidence = {
        "event_type": event_type,
        "payload": parameters,
        "desired_state_sha256": _sha256_contract(intent_desired),
        "candidate_delta_sha256": _sha256_contract(candidate_delta),
    }
    task_lock, workspace_lock, ownership_lock = (
        workflow_runtime_services().locks.workflow_transition_locks(
            old_state
        )
    )
    context_values = {
        "task_id": str(old_state.get("task_id")),
        "workflow_ref": old_state.get("workflow_ref", {}),
        "task_lock_held": task_lock,
        "workspace_lock_held": workspace_lock,
        "ownership_lock_held": ownership_lock,
        "evidence_sha256": _sha256_contract(evidence),
        "evidence_authentic": True,
        "evidence_current": True,
        "supported_node_contracts": {
            str(kind): tuple(versions)
            for kind, versions in (
                _workflow_catalog_supported_node_contracts.items()
            )
        },
        "supported_contract_versions": (
            _workflow_transition_supported_contracts(bundle)
        ),
        "authorized_effects": side_effects,
        "requested_effect_paths": requested_paths,
        "authorized_paths": requested_paths,
    }
    action_outcome = ActionOutcome(
        action_id,
        edge_id,
        evidence_records=(
            {
                "event_type": event_type,
                "candidate_sha256": _sha256_contract(intent_desired),
                "candidate_delta_sha256": _sha256_contract(
                    candidate_delta
                ),
            },
        ),
        proposed_state_delta=candidate_delta,
        audit_facts=(
            AuditFact(
                "action-outcome-accepted",
                {
                    "action_id": action_id,
                    "edge_id": edge_id,
                    "candidate_delta_sha256": _sha256_contract(
                        candidate_delta
                    ),
                },
            ),
        ),
        external_postconditions=(
            ({"paths": list(requested_paths)},)
            if requested_paths
            else ()
        ),
    )
    gate = selected.get("gate")
    approval_seed = (
        _workflow_transition_registered_approval_outcome(
            old_state,
            gate_reference=gate,
            edge_id=edge_id,
            action_id=action_id,
        )
        if isinstance(gate, Mapping)
        else None
    )
    preview = engine.evaluate(
        old_state,
        expected_revision=int(old_state.get("revision", -1)),
        action_id=action_id,
        action_parameters=parameters,
        evidence=evidence,
        edge_id=edge_id,
        action_outcome=action_outcome,
        approval_outcome=approval_seed,
        preview=True,
        kernel_context=KernelTransitionContext(**context_values),
    )
    if preview_only:
        return preview
    confirmation = selected.get("confirmation")
    if confirmation == "explicit" and not isinstance(
        supplied_intent, str
    ):
        raise TransitionEngineError(
            "TRANSITION_INTENT_REQUIRED",
            "explicit v4 movement requires a confirmed controller preview",
            details={"preview": _workflow_transition_public(preview.intent)},
        )
    approval_intent = (
        supplied_intent
        if confirmation == "explicit"
        else preview.intent["intent_id"]
    )
    approval_outcome = (
        _workflow_transition_registered_approval_outcome(
            old_state,
            gate_reference=gate,
            edge_id=edge_id,
            action_id=action_id,
            intent_id=(
                str(approval_intent)
                if isinstance(approval_intent, str)
                else None
            ),
        )
        if isinstance(gate, Mapping)
        else None
    )
    if approval_outcome is not None:
        context_values.update(
            {
                "approval_current": True,
                "approval_intent_id": approval_intent,
            }
        )
    evaluation = engine.evaluate(
        old_state,
        expected_revision=int(old_state.get("revision", -1)),
        action_id=action_id,
        action_parameters=parameters,
        evidence=evidence,
        edge_id=edge_id,
        action_outcome=action_outcome,
        approval_outcome=approval_outcome,
        confirm_intent=(
            supplied_intent
            if isinstance(supplied_intent, str)
            else None
        ),
        preview=False,
        kernel_context=KernelTransitionContext(**context_values),
    )
    engine_candidate = copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(engine_candidate, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "engine transition candidate must be an object",
        )
    if compare_desired:
        comparison_candidate = copy.deepcopy(engine_candidate)
        comparison_candidate["node_instances"] = copy.deepcopy(
            desired.get("node_instances")
        )
        differences = json_pointer_diff(desired, comparison_candidate)
        if differences:
            raise TransitionEngineError(
                "TRANSITION_HANDLER_OUT_OF_SCOPE",
                "handler candidate contains changes outside the pinned edge",
                details={
                    "edge_id": edge_id,
                    "unexpected_paths": list(differences),
                },
            )
    try:
        validate_v4_task_state(engine_candidate)
    except WorkflowStateError as exc:
        raise TransitionEngineError(
            exc.code, exc.message, details=exc.details
        ) from exc
    return evaluation


def evaluate_v4_command_movement(
    old_state: Mapping[str, object],
    *,
    target: str,
    event_type: str,
    action_id: str,
    action_parameters: Mapping[str, object] | None = None,
    state_records: Mapping[str, object] | None = None,
    confirm_intent: str | None = None,
    preview: bool = False,
    manager_intent_state: Mapping[str, object] | None = None,
) -> TransitionEvaluation:
    """Run a schema-v4 command directly against one pinned engine edge.

    This entry point accepts no caller-owned edge table or guard result,
    transition intent, or hand-written invalidation candidate.  Commands may
    supply action output records (for example ``blocked`` or ``cancelled``),
    while the pinned registered reducers remain the only source of movement
    invalidation semantics.
    """

    if old_state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise TransitionEngineError(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "engine-owned command movement requires schema version 4",
        )
    source = old_state.get("status")
    if not isinstance(source, str) or not isinstance(target, str):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "engine-owned command movement requires string node identities",
        )
    desired = copy.deepcopy(_workflow_transition_public(old_state))
    if not isinstance(desired, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "engine-owned command movement requires an object task state",
        )
    desired["status"] = target
    parameters = copy.deepcopy(
        _workflow_transition_public(dict(action_parameters or {}))
    )
    if not isinstance(parameters, dict):
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "command action parameters must be an object",
        )
    records = copy.deepcopy(
        _workflow_transition_public(dict(state_records or {}))
    )
    if not isinstance(records, dict):
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "command state records must be an object",
        )
    unknown_records = sorted(set(records) - {"blocked", "cancelled"})
    if unknown_records:
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "command state records contain unsupported fields",
            details={"fields": unknown_records},
        )
    for field, value in records.items():
        desired[field] = copy.deepcopy(value)
    parameters["action"] = action_id
    if confirm_intent is not None:
        parameters["intent_id"] = confirm_intent
    return evaluate_v4_workflow_movement(
        old_state,
        desired,
        event_type=event_type,
        payload=parameters,
        preview_only=preview,
        compare_desired=False,
        reducer_parameters=records,
        manager_intent_state=manager_intent_state,
    )


def v4_transition_preview(
    evaluation: TransitionEvaluation,
) -> dict[str, object]:
    """Project an engine intent using the long-standing CLI preview shape."""

    preview = copy.deepcopy(
        _workflow_transition_public(evaluation.intent)
    )
    if not isinstance(preview, dict):
        raise TransitionEngineError(
            "TRANSITION_INTENT_INVALID",
            "engine transition preview must be an object",
        )
    preview["requires_confirmation"] = (
        preview.get("confirmation_mode") == "explicit"
    )
    return preview


def _workflow_transition_event_batch_binding(
    event_type: str,
    payload: Mapping[str, object] | None,
    additional_events: Sequence[
        tuple[str, Mapping[str, object]]
    ],
    *,
    event_ids: Sequence[str] | None,
    transaction_id: str | None,
) -> dict[str, object]:
    if not isinstance(event_type, str) or not event_type:
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_EVENT_INVALID",
            "engine-authorized event type must be non-empty",
        )
    linked: list[dict[str, object]] = []
    for linked_type, linked_payload in additional_events:
        if (
            not isinstance(linked_type, str)
            or not linked_type
            or not isinstance(linked_payload, Mapping)
        ):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_EVENT_INVALID",
                "linked engine-authorized events must be typed objects",
            )
        linked.append(
            {
                "type": linked_type,
                "payload": copy.deepcopy(
                    _workflow_transition_public(linked_payload)
                ),
            }
        )
    if event_ids is not None and (
        any(not isinstance(item, str) or not item for item in event_ids)
        or len(tuple(event_ids)) != len(linked) + 1
        or len(set(event_ids)) != len(tuple(event_ids))
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_EVENT_INVALID",
            "preallocated event identities do not match the sealed batch",
        )
    if transaction_id is not None and (
        not isinstance(transaction_id, str) or not transaction_id
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_EVENT_INVALID",
            "preallocated transaction identity is invalid",
        )
    public_payload = copy.deepcopy(
        _workflow_transition_public(dict(payload or {}))
    )
    if not isinstance(public_payload, dict):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_EVENT_INVALID",
            "engine-authorized event payload must be an object",
        )
    return {
        "primary": {
            "type": event_type,
            "payload": public_payload,
        },
        "linked": linked,
        "event_ids": (
            list(event_ids) if event_ids is not None else None
        ),
        "transaction_id": transaction_id,
    }


def _workflow_transition_lock_capability_binding(
    task_dir: object,
    state: Mapping[str, object],
) -> dict[str, object]:
    try:
        task_directory = Path(task_dir).resolve(strict=False)
    except (OSError, TypeError, ValueError) as exc:
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_TASK_DIRECTORY_INVALID",
            "engine commit requires a canonical task directory",
        ) from exc
    task_id = state.get("task_id")
    if (
        not isinstance(task_id, str)
        or not task_id
        or task_directory.name != task_id
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_TASK_DIRECTORY_MISMATCH",
            "canonical task directory does not bind the task identity",
            details={
                "task_id": task_id,
                "task_directory": str(task_directory),
            },
        )
    services = workflow_runtime_services()
    held_task = services.locks.held_task_directory()
    if not isinstance(held_task, Path):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_LOCK_REQUIRED",
            "engine commit requires the live task-lock capability",
        )
    task_identity = _serializable_path_identity(task_directory)
    held_task_identity = _serializable_path_identity(
        held_task.resolve(strict=False)
    )
    if not _path_identity_equal(task_identity, held_task_identity):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_LOCK_MISMATCH",
            "held task lock does not bind the committed task directory",
        )
    held_directories = services.locks.held_directories()
    opaque_capabilities = _engine_lock_capability_snapshot(
        held_directories
    )
    held_records = [
        {
            "path": str(Path(value).resolve(strict=False)),
            "identity": _serializable_path_identity(
                Path(value).resolve(strict=False)
            ),
        }
        for value in held_directories
    ]
    held_records.sort(
        key=lambda item: str(item["path"]).encode("utf-8")
    )
    task_lock, workspace_lock, ownership_lock = (
        services.locks.workflow_transition_locks(state)
    )
    if not task_lock:
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_LOCK_REQUIRED",
            "engine commit requires the live task-lock capability",
        )
    return {
        "task_directory": {
            "path": str(task_directory),
            "identity": task_identity,
        },
        "held_task_directory": {
            "path": str(held_task.resolve(strict=False)),
            "identity": held_task_identity,
        },
        "held_lock_directories": held_records,
        "opaque_lock_capabilities": opaque_capabilities,
        "task_lock_held": task_lock,
        "workspace_lock_held": workspace_lock,
        "ownership_lock_held": ownership_lock,
        # ContextVar values can be copied to another thread.  The OS lock and
        # proof must remain on the exact controller thread that evaluated the
        # candidate.
        "controller_thread_id": threading.get_ident(),
    }


def _workflow_transition_evaluation_lock_binding(
    state: Mapping[str, object],
) -> dict[str, object]:
    """Observe the exact task-lock capability set during engine evaluation."""

    held_task = workflow_runtime_services().locks.held_task_directory()
    if not isinstance(held_task, Path):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_LOCK_REQUIRED",
            "schema-v4 evaluation requires the live task-lock capability",
        )
    return _workflow_transition_lock_capability_binding(
        held_task, state
    )


def _workflow_transition_receipt_binding(
    verified_receipt: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if verified_receipt is None:
        return None
    public = copy.deepcopy(
        _workflow_transition_public(dict(verified_receipt))
    )
    if not isinstance(public, dict):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_RECEIPT_INVALID",
            "verified engine receipt must be an object",
        )
    return public


def _workflow_transition_observed_engine_commit_binding(
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    task_dir: object,
    *,
    event_type: str,
    payload: Mapping[str, object] | None,
    additional_events: Sequence[
        tuple[str, Mapping[str, object]]
    ],
    event_ids: Sequence[str] | None,
    transaction_id: str | None,
    verified_receipt: Mapping[str, object] | None,
) -> dict[str, object]:
    lock_binding = _workflow_transition_lock_capability_binding(
        task_dir, old_state
    )
    workflow_ref = copy.deepcopy(
        _workflow_transition_public(
            old_state.get("workflow_ref", {})
        )
    )
    if not isinstance(workflow_ref, dict):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_WORKFLOW_INVALID",
            "engine commit requires a pinned workflow identity",
        )
    resolution = resolve_loaded_task_workflow(
        old_state, purpose="mutation"
    )
    if not isinstance(resolution, Mapping) or not isinstance(
        resolution.get("bundle_sha256"), str
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_WORKFLOW_INVALID",
            "engine commit could not resolve the pinned workflow bundle",
        )
    return {
        "task_directory": lock_binding["task_directory"],
        "held_lock_capabilities": lock_binding,
        "task": {
            "task_id": old_state.get("task_id"),
            "schema_version": old_state.get("schema_version"),
            "expected_revision": old_state.get("revision"),
        },
        "workflow": {
            "workflow_ref": workflow_ref,
            "resolved_bundle_sha256": resolution["bundle_sha256"],
        },
        "old_state_sha256": _sha256_contract(old_state),
        "candidate_state_sha256": _sha256_contract(candidate_state),
        "event_batch": _workflow_transition_event_batch_binding(
            event_type,
            payload,
            additional_events,
            event_ids=event_ids,
            transaction_id=transaction_id,
        ),
        "verified_receipt": _workflow_transition_receipt_binding(
            verified_receipt
        ),
    }


def _workflow_transition_mint_engine_commit_proof(
    old_state: Mapping[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    *,
    additional_events: Sequence[
        tuple[str, Mapping[str, object]]
    ] = (),
    event_ids: Sequence[str] | None = None,
    transaction_id: str | None = None,
    verified_receipt: Mapping[str, object] | None = None,
    manager_evaluation_state: Mapping[str, object] | None = None,
    manager_authorization: Mapping[str, object] | None = None,
) -> EngineCommitProof:
    """Mint one proof from an exact, still-live kernel evaluation issuance."""

    issuance = _transition_engine_consume_evaluation_issuance(
        evaluation
    )
    candidate = copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "kernel evaluation candidate must be an object",
        )
    if (manager_evaluation_state is None) != (
        manager_authorization is None
    ):
        raise TransitionEngineError(
            "V4_ENGINE_MANAGER_BINDING_INVALID",
            "manager evaluation state and authorization must be supplied together",
        )
    issuance_state = (
        old_state
        if manager_evaluation_state is None
        else manager_evaluation_state
    )
    if manager_evaluation_state is not None:
        candidate_orchestration = candidate.get("orchestration")
        manager_orchestration = manager_evaluation_state.get(
            "orchestration"
        )
        if (
            not isinstance(candidate_orchestration, Mapping)
            or not isinstance(manager_orchestration, Mapping)
            or candidate_orchestration.get("manager_capabilities")
            != manager_orchestration.get("manager_capabilities")
        ):
            raise TransitionEngineError(
                "V4_ENGINE_MANAGER_BINDING_INVALID",
                "engine candidate does not retain its pre-evaluated manager nonce",
            )
    observed = _workflow_transition_observed_engine_commit_binding(
        old_state,
        candidate,
        task_dir,
        event_type=event_type,
        payload=payload,
        additional_events=additional_events,
        event_ids=event_ids,
        transaction_id=transaction_id,
        verified_receipt=verified_receipt,
    )
    if (
        issuance.get("old_state_sha256")
        != _sha256_contract(issuance_state)
        or issuance.get("task_id") != old_state.get("task_id")
        or issuance.get("expected_revision")
        != old_state.get("revision")
        or not isinstance(observed.get("workflow"), Mapping)
        or issuance.get("workflow_ref")
        != observed["workflow"].get("workflow_ref")
    ):
        raise TransitionEngineError(
            "V4_ENGINE_EVALUATION_MISMATCH",
            "kernel evaluation does not bind the committed task snapshot",
        )
    kernel_context = issuance.get("kernel_context")
    evaluation_lock_binding = issuance.get(
        "evaluation_lock_capabilities"
    )
    lock_binding = observed["held_lock_capabilities"]
    if not isinstance(kernel_context, Mapping) or not isinstance(
        lock_binding, Mapping
    ):
        raise TransitionEngineError(
            "V4_ENGINE_EVALUATION_MISMATCH",
            "kernel evaluation lacks its lock-capability binding",
        )
    if not isinstance(evaluation_lock_binding, Mapping):
        raise TransitionEngineError(
            "V4_ENGINE_EVALUATION_LOCK_REQUIRED",
            (
                "durable commit requires a kernel evaluation observed by "
                "the composed controller lock broker"
            ),
        )
    if not hmac.compare_digest(
        _canonical_json_bytes(evaluation_lock_binding),
        _canonical_json_bytes(lock_binding),
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_LOCK_MISMATCH",
            "held lock capabilities changed after kernel evaluation",
        )
    for field in (
        "task_lock_held",
        "workspace_lock_held",
        "ownership_lock_held",
    ):
        if kernel_context.get(field) != lock_binding.get(field):
            raise TransitionEngineError(
                "V4_ENGINE_COMMIT_LOCK_MISMATCH",
                "held locks changed after kernel evaluation",
                details={"capability": field},
            )
    state_path = Path(task_dir) / "state.json"
    persisted = _read_task_state_structural_snapshot(state_path)
    if not hmac.compare_digest(
        _sha256_contract(persisted),
        str(observed["old_state_sha256"]),
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_STALE_STATE",
            "kernel evaluation is not based on the durable task snapshot",
            details={
                "expected_revision": old_state.get("revision"),
                "persisted_revision": persisted.get("revision"),
            },
        )
    core = {
        "contract": "dev-flow-v4-engine-commit-proof/v1",
        **observed,
        "edge_id": evaluation.edge_id,
        "action": issuance.get("action"),
        "evaluation": issuance.get("evaluation"),
    }
    if manager_authorization is not None:
        core["manager_authorization"] = {
            **copy.deepcopy(
                _workflow_transition_public(manager_authorization)
            ),
            "evaluation_state_sha256": _sha256_contract(
                manager_evaluation_state
            ),
        }
    proof = _engine_commit_proof_issue(core)
    if type(proof) is not EngineCommitProof:
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_PROOF_INVALID",
            "kernel proof broker returned an invalid capability",
        )
    return proof


def _workflow_transition_consume_engine_commit(
    proof: object,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    task_dir: object,
    *,
    event_type: str,
    payload: Mapping[str, object] | None,
    additional_events: Sequence[
        tuple[str, Mapping[str, object]]
    ] = (),
    event_ids: Sequence[str] | None = None,
    transaction_id: str | None = None,
    verified_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Atomically consume one exact process-private commit proof.

    The observed binding is deliberately built *after* the broker atomically
    pops a genuine proof.  Wrong payloads, lost locks, cross-thread use, and
    exceptions therefore burn the proof and require a fresh reevaluation.
    """

    return _engine_commit_proof_consume(
        proof,
        lambda: _workflow_transition_observed_engine_commit_binding(
            old_state,
            candidate_state,
            task_dir,
            event_type=event_type,
            payload=payload,
            additional_events=additional_events,
            event_ids=event_ids,
            transaction_id=transaction_id,
            verified_receipt=verified_receipt,
        ),
    )


def commit_v4_command_movement(
    old_state: dict[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    *,
    additional_events: Sequence[
        tuple[str, dict[str, object]]
    ] = (),
) -> dict[str, object]:
    """Commit exactly one prior engine evaluation through the normal outbox."""

    candidate = copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise TransitionEngineError(
            "TASK_STATE_INVALID",
            "engine-authorized movement candidate must be an object",
        )
    if (
        old_state.get("status") != evaluation.source
        or candidate.get("status") != evaluation.target
    ):
        raise TransitionEngineError(
            "V4_ENGINE_COMMIT_PROOF_MISMATCH",
            "transition evaluation does not match the committed source/target",
        )
    public_payload = copy.deepcopy(
        _workflow_transition_public(dict(payload or {}))
    )
    if not isinstance(public_payload, dict):
        raise TransitionEngineError(
            "TRANSITION_CONTRACT_INVALID",
            "movement event payload must be an object",
        )
    linked_events = [
        *additional_events,
        *workflow_transition_audit_events(evaluation),
    ]
    _commit_state(
        old_state,
        candidate,
        task_dir,
        event_type,
        public_payload,
        additional_events=linked_events,
        _engine_commit_evaluation=evaluation,
    )
    return candidate


def v4_command_movement_evaluate_v1(
    old_state: Mapping[str, object],
    **arguments: object,
) -> TransitionEvaluation:
    """Versioned command boundary that projects kernel errors as FlowError."""

    try:
        event_type = arguments.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise TransitionEngineError(
                "TRANSITION_CONTRACT_INVALID",
                "command movement requires one canonical event type",
            )
        (
            evaluation_state,
            manager_intent_state,
        ) = _workflow_transition_manager_evaluation_input_v1(
            old_state, event_type=event_type
        )
        return evaluate_v4_command_movement(
            evaluation_state,
            **arguments,
            manager_intent_state=manager_intent_state,
        )
    except TransitionEngineError as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc


def v4_command_movement_preview_v1(
    evaluation: TransitionEvaluation,
) -> dict[str, object]:
    try:
        return v4_transition_preview(evaluation)
    except TransitionEngineError as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc


def v4_command_movement_commit_v1(
    old_state: dict[str, object],
    evaluation: TransitionEvaluation,
    task_dir: object,
    event_type: str,
    payload: Mapping[str, object] | None = None,
    *,
    additional_events: Sequence[
        tuple[str, dict[str, object]]
    ] = (),
) -> dict[str, object]:
    try:
        return commit_v4_command_movement(
            old_state,
            evaluation,
            task_dir,
            event_type,
            payload,
            additional_events=additional_events,
        )
    except TransitionEngineError as exc:
        details = _workflow_transition_public(exc.details)
        raise FlowError(
            exc.code,
            exc.message,
            details=details if isinstance(details, dict) else {},
        ) from exc


def evaluate_v4_gate_approval_candidate(
    old_state: Mapping[str, object],
    desired_state: Mapping[str, object],
    *,
    payload: Mapping[str, object] | None = None,
    manager_intent_state: Mapping[str, object] | None = None,
) -> TransitionEvaluation:
    """Evaluate a same-node gate action through the authoritative engine."""

    if old_state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise TransitionEngineError(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "formal gate actions require schema version 4",
        )
    raise TransitionEngineError(
        "V4_GATE_CANDIDATE_FORBIDDEN",
        (
            "schema-v4 gate approval requires the compiled action edge, "
            "typed ApprovalOutcome, and generic one-shot engine proof"
        ),
        details={
            "status": old_state.get("status"),
            "replacement": "evaluate_v4_node_action",
        },
    )


def workflow_transition_audit_events(
    evaluation: TransitionEvaluation,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Project typed audit facts into the existing durable event batch."""

    linked = {
        "edge_id": evaluation.edge_id,
        "intent_id": evaluation.intent.get("intent_id"),
    }
    return tuple(
        (
            "workflow_audit_fact",
            {
                **linked,
                "fact_type": fact.fact_type,
                "fact": copy.deepcopy(
                    _workflow_transition_public(fact.payload)
                ),
            },
        )
        for fact in evaluation.audit_facts
    )


V4_NODE_MUTATION_MAP_EXPAND = "MAP_EXPAND"
V4_NODE_MUTATION_MAP_INVALIDATE = "MAP_INVALIDATE"
V4_NODE_MUTATION_FRONTIER_READY = "FRONTIER_READY"
V4_NODE_MUTATION_ATTEMPT_START = "ATTEMPT_START"
V4_NODE_MUTATION_ATTEMPT_ABANDON = "ATTEMPT_ABANDON"
V4_NODE_MUTATION_RESULT_ACCEPT = "RESULT_ACCEPT"
V4_NODE_MUTATION_RETRY_READY = "RETRY_READY"
V4_NODE_MUTATION_OPERATIONS = frozenset(
    {
        V4_NODE_MUTATION_MAP_EXPAND,
        V4_NODE_MUTATION_MAP_INVALIDATE,
        V4_NODE_MUTATION_FRONTIER_READY,
        V4_NODE_MUTATION_ATTEMPT_START,
        V4_NODE_MUTATION_ATTEMPT_ABANDON,
        V4_NODE_MUTATION_RESULT_ACCEPT,
        V4_NODE_MUTATION_RETRY_READY,
    }
)
V4_NODE_MUTATION_EVENT_TYPES = MappingProxyType(
    {
        V4_NODE_MUTATION_MAP_EXPAND: "orchestration_plan_expanded",
        V4_NODE_MUTATION_MAP_INVALIDATE: (
            "orchestration_map_invalidated"
        ),
        V4_NODE_MUTATION_FRONTIER_READY: (
            "orchestration_frontier_ready"
        ),
        V4_NODE_MUTATION_ATTEMPT_START: (
            "orchestration_worker_assigned"
        ),
        V4_NODE_MUTATION_ATTEMPT_ABANDON: (
            "orchestration_attempt_abandoned"
        ),
        V4_NODE_MUTATION_RESULT_ACCEPT: (
            "orchestration_result_accepted"
        ),
        V4_NODE_MUTATION_RETRY_READY: (
            "orchestration_retry_authorized"
        ),
    }
)
V4_NODE_MUTATION_MANAGER_ACTIONS = MappingProxyType(
    {
        V4_NODE_MUTATION_MAP_EXPAND: (
            "orchestration.plan.expand/v1"
        ),
        V4_NODE_MUTATION_MAP_INVALIDATE: (
            "orchestration.map.invalidate/v1"
        ),
        V4_NODE_MUTATION_FRONTIER_READY: (
            "orchestration.worker.assign/v1"
        ),
        V4_NODE_MUTATION_ATTEMPT_START: (
            "orchestration.worker.assign/v1"
        ),
        V4_NODE_MUTATION_ATTEMPT_ABANDON: (
            "orchestration.runtime.recover/v1"
        ),
        V4_NODE_MUTATION_RESULT_ACCEPT: (
            "worker-result.submit/v1"
        ),
        V4_NODE_MUTATION_RETRY_READY: (
            "orchestration.retry.request/v1"
        ),
    }
)
V4_NODE_MUTATION_ORCHESTRATION_POLICY = MappingProxyType(
    {
        V4_NODE_MUTATION_MAP_EXPAND: (
            "/orchestration/expansion",
            "/orchestration/manager_capabilities",
        ),
        V4_NODE_MUTATION_MAP_INVALIDATE: (
            "/orchestration/approval",
            "/orchestration/barriers",
            "/orchestration/current_results",
            "/orchestration/expansion",
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        V4_NODE_MUTATION_FRONTIER_READY: (
            "/orchestration/manager_capabilities",
        ),
        V4_NODE_MUTATION_ATTEMPT_START: (
            "/orchestration/assignments",
            "/orchestration/dispatch",
            "/orchestration/leases",
            "/orchestration/manager_capabilities",
            "/orchestration/pending_retries",
        ),
        V4_NODE_MUTATION_ATTEMPT_ABANDON: (
            "/orchestration/accepted_results",
            "/orchestration/artifacts",
            "/orchestration/current_results",
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        V4_NODE_MUTATION_RESULT_ACCEPT: (
            "/orchestration/accepted_results",
            "/orchestration/artifacts",
            "/orchestration/current_results",
            "/orchestration/integration",
            "/orchestration/integration_verification",
            "/orchestration/manager_capabilities",
            "/orchestration/review",
        ),
        V4_NODE_MUTATION_RETRY_READY: (
            "/orchestration/manager_capabilities",
            "/orchestration/pending_retries",
        ),
    }
)
_v4_node_mutation_required_orchestration_roots = MappingProxyType(
    {
        V4_NODE_MUTATION_MAP_EXPAND: (
            "/orchestration/expansion",
        ),
        V4_NODE_MUTATION_MAP_INVALIDATE: (
            "/orchestration/expansion",
        ),
        V4_NODE_MUTATION_FRONTIER_READY: (),
        V4_NODE_MUTATION_ATTEMPT_START: (
            "/orchestration/assignments",
            "/orchestration/dispatch",
            "/orchestration/leases",
        ),
        V4_NODE_MUTATION_ATTEMPT_ABANDON: (
            "/orchestration/accepted_results",
            "/orchestration/artifacts",
            "/orchestration/current_results",
        ),
        V4_NODE_MUTATION_RESULT_ACCEPT: (
            "/orchestration/accepted_results",
            "/orchestration/artifacts",
            "/orchestration/current_results",
        ),
        V4_NODE_MUTATION_RETRY_READY: (
            "/orchestration/pending_retries",
        ),
    }
)
_v4_node_mutation_contract = "dev-flow-v4-node-mutation/v1"
V4_ATTEMPT_ABANDONMENT_SCHEMA = (
    "dev-flow-attempt-abandonment/v1"
)
V4_ATTEMPT_ABANDONMENT_RECORD_SCHEMA = (
    "dev-flow-attempt-abandonment-record/v1"
)
V4_CONTROLLER_RESULT_OBSERVATION_SCHEMA = (
    "dev-flow-controller-result-observation/v1"
)
_v4_node_mutation_authorization_key = secrets.token_bytes(32)
_v4_node_manager_authorization_key = secrets.token_bytes(32)
_v4_controller_result_observation_key = secrets.token_bytes(32)
_v4_node_mutation_result_states = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
    }
)
_v4_node_mutation_active_attempt_states = frozenset(
    {"RUNNING", "WAITING_APPROVAL", "WAITING_EXTERNAL"}
)


def _v4_node_mutation_error(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> "TransitionEngineError":
    return TransitionEngineError(code, message, details=details)


def _v4_node_mutation_utf8(value: str) -> bytes:
    return value.encode("utf-8")


def _v4_node_mutation_path_is_within(
    pointer: str, root: str
) -> bool:
    return pointer == root or pointer.startswith(
        root.rstrip("/") + "/"
    )


def seal_v4_controller_result_observation(
    *,
    result: Mapping[str, object],
    verified_output: Mapping[str, object],
    observed_at_revision: int,
) -> dict[str, object]:
    core = {
        "schema": V4_CONTROLLER_RESULT_OBSERVATION_SCHEMA,
        "result_id": result.get("result_id"),
        "assignment_id": result.get("assignment_id"),
        "node_instance_id": result.get("node_instance_id"),
        "attempt": result.get("attempt"),
        "output_sha256": verified_output.get("output_sha256"),
        "worktree_sha256": verified_output.get("worktree_sha256"),
        "changed_paths_sha256": verified_output.get(
            "changed_paths_sha256"
        ),
        "verification_sha256": verified_output.get(
            "verification_sha256"
        ),
        "observed_at_revision": observed_at_revision,
    }
    return {
        **core,
        "seal_hmac_sha256": hmac.new(
            _v4_controller_result_observation_key,
            _canonical_json_bytes(core),
            hashlib.sha256,
        ).hexdigest(),
    }


def _validate_v4_controller_result_observation(
    value: object,
    *,
    result: Mapping[str, object],
) -> None:
    if not isinstance(value, Mapping):
        raise _v4_node_mutation_error(
            "V4_RESULT_CONTROLLER_OBSERVATION_REQUIRED",
            "result acceptance requires a controller-sealed output observation",
        )
    fields = {
        "schema",
        "result_id",
        "assignment_id",
        "node_instance_id",
        "attempt",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
        "observed_at_revision",
        "seal_hmac_sha256",
    }
    core = {
        key: value.get(key)
        for key in fields
        if key != "seal_hmac_sha256"
    }
    expected = hmac.new(
        _v4_controller_result_observation_key,
        _canonical_json_bytes(core),
        hashlib.sha256,
    ).hexdigest()
    bindings = {
        "result_id": result.get("result_id"),
        "assignment_id": result.get("assignment_id"),
        "node_instance_id": result.get("node_instance_id"),
        "attempt": result.get("attempt"),
        "output_sha256": result.get("output_sha256"),
        "worktree_sha256": result.get("worktree_sha256"),
        "changed_paths_sha256": result.get(
            "changed_paths_sha256"
        ),
        "verification_sha256": result.get(
            "verification_sha256"
        ),
    }
    if (
        set(value) != fields
        or value.get("schema")
        != V4_CONTROLLER_RESULT_OBSERVATION_SCHEMA
        or isinstance(value.get("observed_at_revision"), bool)
        or not isinstance(value.get("observed_at_revision"), int)
        or any(value.get(key) != item for key, item in bindings.items())
        or not hmac.compare_digest(
            str(value.get("seal_hmac_sha256")), expected
        )
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_CONTROLLER_OBSERVATION_INVALID",
            "controller result observation is forged, stale, or belongs to another result",
        )


def _v4_node_mutation_orchestration_pointers(
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    *,
    operation: str,
    affected: Sequence[str],
    before_nodes: Mapping[str, Mapping[str, object]],
    after_nodes: Mapping[str, Mapping[str, object]],
    expected_revision: int,
    event_id: str,
    event_payload: Mapping[str, object],
) -> tuple[str, ...]:
    old_orchestration = old_state.get("orchestration")
    new_orchestration = candidate_state.get("orchestration")
    if not isinstance(old_orchestration, Mapping) or not isinstance(
        new_orchestration, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_ORCHESTRATION_STATE_REQUIRED",
            "node mutation requires an existing orchestration state object",
        )
    pointers = tuple(
        pointer
        for pointer in json_pointer_diff(
            old_orchestration,
            new_orchestration,
            "/orchestration",
        )
    )
    policy = V4_NODE_MUTATION_ORCHESTRATION_POLICY[operation]
    unexpected = [
        pointer
        for pointer in pointers
        if not any(
            _v4_node_mutation_path_is_within(pointer, root)
            for root in policy
        )
    ]
    if unexpected:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_OUT_OF_SCOPE",
            "orchestration mutation exceeds package-owned operation policy",
            details={
                "operation": operation,
                "unexpected_paths": unexpected,
                "allowed_roots": list(policy),
            },
        )
    required = _v4_node_mutation_required_orchestration_roots[
        operation
    ]
    missing = [
        root
        for root in required
        if not any(
            _v4_node_mutation_path_is_within(pointer, root)
            for pointer in pointers
        )
    ]
    if missing:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_ORCHESTRATION_INCOMPLETE",
            "node mutation lacks its required orchestration facts",
            details={"operation": operation, "missing_roots": missing},
        )
    _v4_node_mutation_validate_orchestration_semantics(
        old_orchestration,
        new_orchestration,
        operation=operation,
        affected=tuple(affected),
        before_nodes=before_nodes,
        after_nodes=after_nodes,
        expected_revision=expected_revision,
        event_id=event_id,
        event_payload=event_payload,
        old_state=old_state,
    )
    return tuple(
        sorted(set(pointers), key=_v4_node_mutation_utf8)
    )


def _v4_node_mutation_mapping(
    value: object,
    *,
    operation: str,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _v4_node_mutation_error(
            f"V4_{operation}_ORCHESTRATION_INVALID",
            "operation orchestration ledger must be an object",
            details={"field": field},
        )
    if any(not isinstance(key, str) for key in value):
        raise _v4_node_mutation_error(
            f"V4_{operation}_ORCHESTRATION_INVALID",
            "operation orchestration ledger keys must be strings",
            details={"field": field},
        )
    return value


def _v4_node_mutation_mapping_delta(
    before: object,
    after: object,
    *,
    operation: str,
    field: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    old_values = _v4_node_mutation_mapping(
        before, operation=operation, field=field
    )
    new_values = _v4_node_mutation_mapping(
        after, operation=operation, field=field
    )
    added = tuple(
        sorted(
            set(new_values) - set(old_values),
            key=_v4_node_mutation_utf8,
        )
    )
    removed = tuple(
        sorted(
            set(old_values) - set(new_values),
            key=_v4_node_mutation_utf8,
        )
    )
    modified = tuple(
        sorted(
            (
                key
                for key in set(old_values) & set(new_values)
                if old_values[key] != new_values[key]
            ),
            key=_v4_node_mutation_utf8,
        )
    )
    return added, removed, modified


def _v4_node_mutation_bound_node_attempt(
    value: object,
) -> tuple[object, object]:
    if not isinstance(value, Mapping):
        return None, None
    node_instance_id = value.get("node_instance_id")
    attempt = value.get("attempt")
    nested = value.get("result")
    if isinstance(nested, Mapping):
        node_instance_id = nested.get(
            "node_instance_id", node_instance_id
        )
        attempt = nested.get("attempt", attempt)
    return node_instance_id, attempt


def _v4_node_mutation_validate_map_orchestration(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    affected: tuple[str, ...],
    after_nodes: Mapping[str, Mapping[str, object]],
) -> None:
    prior_expansion = before.get("expansion")
    replacing_retired = (
        isinstance(prior_expansion, Mapping)
        and prior_expansion.get("current") is False
        and isinstance(
            prior_expansion.get("retired_at_revision"), int
        )
    )
    if prior_expansion is not None and not replacing_retired:
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
            "map expansion can replace only a formally retired generation",
        )
    expansion = after.get("expansion")
    if not isinstance(expansion, Mapping):
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
            "map expansion must persist a canonical expansion object",
        )
    if expansion.get("current", True) is not True:
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
            "successor map expansion must be current",
        )
    if replacing_retired:
        assert isinstance(prior_expansion, Mapping)
        minimum_epoch = prior_expansion.get(
            "minimum_successor_map_epoch"
        )
        if (
            isinstance(minimum_epoch, bool)
            or not isinstance(minimum_epoch, int)
            or isinstance(expansion.get("map_epoch"), bool)
            or not isinstance(expansion.get("map_epoch"), int)
            or int(expansion["map_epoch"]) < minimum_epoch
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_SUCCESSOR_EPOCH_INVALID",
                "successor map epoch is below the retired generation bound",
                details={"minimum_successor_map_epoch": minimum_epoch},
            )
    children = expansion.get("children")
    if not isinstance(children, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in children
    ):
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
            "persisted expansion children must be objects",
        )
    child_by_id = {
        str(item.get("node_instance_id")): item
        for item in children
        if isinstance(item, Mapping)
        and isinstance(item.get("node_instance_id"), str)
    }
    if (
        len(child_by_id) != len(children)
        or tuple(
            sorted(child_by_id, key=_v4_node_mutation_utf8)
        )
        != affected
    ):
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
            "persisted expansion membership must equal affected children",
            details={
                "affected": list(affected),
                "children": sorted(child_by_id),
            },
        )
    for identifier, child in child_by_id.items():
        node = after_nodes[identifier]
        expected = {
            "node_id": node.get("node_id"),
            "repository_id": node.get("repository_id"),
            "dependencies": list(node.get("dependencies", ())),
        }
        mismatched = [
            field
            for field, value in expected.items()
            if child.get(field) != value
        ]
        if mismatched:
            raise _v4_node_mutation_error(
                "V4_MAP_EXPANSION_ORCHESTRATION_INVALID",
                "expansion child differs from its node instance",
                details={
                    "node_instance_id": identifier,
                    "fields": mismatched,
                },
            )


def _v4_node_mutation_validate_attempt_orchestration(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    affected: tuple[str, ...],
    after_nodes: Mapping[str, Mapping[str, object]],
) -> None:
    cancellation = before.get("cancellation")
    if (
        isinstance(cancellation, Mapping)
        and cancellation.get("requested") is True
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_CANCELLATION_REQUESTED",
            "attempt start is forbidden after persisted cancellation intent",
        )
    identifier = affected[0]
    attempt = len(after_nodes[identifier].get("attempts", ()))
    additions: dict[str, tuple[str, ...]] = {}
    for field in ("assignments", "dispatch", "leases"):
        added, removed, modified = _v4_node_mutation_mapping_delta(
            before.get(field),
            after.get(field),
            operation=V4_NODE_MUTATION_ATTEMPT_START,
            field=field,
        )
        if len(added) != 1 or removed or modified:
            raise _v4_node_mutation_error(
                "V4_ATTEMPT_START_ORCHESTRATION_INVALID",
                "attempt start must append one immutable assignment, dispatch, and lease",
                details={
                    "field": field,
                    "added": list(added),
                    "removed": list(removed),
                    "modified": list(modified),
                },
            )
        additions[field] = added
    assignment_id = additions["assignments"][0]
    if additions["dispatch"] != (assignment_id,):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_ORCHESTRATION_INVALID",
            "dispatch identity must equal its new assignment identity",
        )
    assignments = _v4_node_mutation_mapping(
        after.get("assignments"),
        operation=V4_NODE_MUTATION_ATTEMPT_START,
        field="assignments",
    )
    leases = _v4_node_mutation_mapping(
        after.get("leases"),
        operation=V4_NODE_MUTATION_ATTEMPT_START,
        field="leases",
    )
    for field, value in (
        ("assignment", assignments[assignment_id]),
        ("lease", leases[additions["leases"][0]]),
    ):
        bound_node, bound_attempt = (
            _v4_node_mutation_bound_node_attempt(value)
        )
        if bound_node != identifier or bound_attempt != attempt:
            raise _v4_node_mutation_error(
                "V4_ATTEMPT_START_ORCHESTRATION_INVALID",
                "new orchestration record does not bind the affected attempt",
                details={
                    "field": field,
                    "node_instance_id": bound_node,
                    "attempt": bound_attempt,
                    "expected_node_instance_id": identifier,
                    "expected_attempt": attempt,
                },
            )
    pending_added, pending_removed, pending_modified = (
        _v4_node_mutation_mapping_delta(
            before.get("pending_retries"),
            after.get("pending_retries"),
            operation=V4_NODE_MUTATION_ATTEMPT_START,
            field="pending_retries",
        )
    )
    if pending_added or pending_modified or (
        pending_removed not in ((), (identifier,))
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_ORCHESTRATION_INVALID",
            "attempt start may only consume its own pending retry",
            details={
                "added": list(pending_added),
                "removed": list(pending_removed),
                "modified": list(pending_modified),
            },
        )
    if attempt > 1 and pending_removed != (identifier,):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_ORCHESTRATION_INVALID",
            "replacement attempt must consume its exact pending retry",
            details={"node_instance_id": identifier},
        )


def _v4_node_mutation_validate_result_orchestration(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    affected: tuple[str, ...],
    after_nodes: Mapping[str, Mapping[str, object]],
) -> None:
    identifier = affected[0]
    attempt = len(after_nodes[identifier].get("attempts", ()))
    additions: dict[str, tuple[str, ...]] = {}
    for field in ("accepted_results", "artifacts"):
        added, removed, modified = _v4_node_mutation_mapping_delta(
            before.get(field),
            after.get(field),
            operation=V4_NODE_MUTATION_RESULT_ACCEPT,
            field=field,
        )
        if len(added) != 1 or removed or modified:
            raise _v4_node_mutation_error(
                "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
                "result acceptance must append one immutable result and artifact",
                details={
                    "field": field,
                    "added": list(added),
                    "removed": list(removed),
                    "modified": list(modified),
                },
            )
        additions[field] = added
    result_id = additions["accepted_results"][0]
    if additions["artifacts"] != (result_id,):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
            "accepted result and artifact identities must match",
        )
    accepted = _v4_node_mutation_mapping(
        after.get("accepted_results"),
        operation=V4_NODE_MUTATION_RESULT_ACCEPT,
        field="accepted_results",
    )
    accepted_record = accepted[result_id]
    accepted_result = (
        accepted_record.get("result")
        if isinstance(accepted_record, Mapping)
        else None
    )
    if not isinstance(accepted_result, Mapping):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
            "accepted result record lacks its immutable result",
        )
    _validate_v4_controller_result_observation(
        accepted_record.get("controller_observation"),
        result=accepted_result,
    )
    bound_node, bound_attempt = _v4_node_mutation_bound_node_attempt(
        accepted_record
    )
    if bound_node != identifier or bound_attempt not in (
        None,
        attempt,
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
            "accepted result does not bind the affected current attempt",
            details={
                "result_id": result_id,
                "node_instance_id": bound_node,
                "attempt": bound_attempt,
            },
        )
    old_current = _v4_node_mutation_mapping(
        before.get("current_results"),
        operation=V4_NODE_MUTATION_RESULT_ACCEPT,
        field="current_results",
    )
    new_current = _v4_node_mutation_mapping(
        after.get("current_results"),
        operation=V4_NODE_MUTATION_RESULT_ACCEPT,
        field="current_results",
    )
    expected_current = dict(old_current)
    expected_current[identifier] = result_id
    if dict(new_current) != expected_current:
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
            "current-result index may change only for the affected node",
            details={"node_instance_id": identifier},
        )
    for field in ("integration", "integration_verification", "review"):
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value == new_value:
            continue
        if field in {"integration_verification", "review"}:
            valid = isinstance(old_value, Mapping) and new_value is None
        else:
            valid = (
                isinstance(old_value, Mapping)
                and isinstance(new_value, Mapping)
                and old_value.get("current") is True
                and new_value.get("current") is False
                and all(
                    old_value.get(key) == value
                    for key, value in new_value.items()
                    if key != "current"
                )
                and set(old_value) == set(new_value)
            )
        if not valid:
            raise _v4_node_mutation_error(
                "V4_RESULT_ACCEPT_ORCHESTRATION_INVALID",
                "downstream invalidation exceeds result-accept policy",
                details={"field": field},
            )


def _v4_node_mutation_validate_abandon_orchestration(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    affected: tuple[str, ...],
    after_nodes: Mapping[str, Mapping[str, object]],
    expected_revision: int,
    event_id: str,
    event_payload: Mapping[str, object],
) -> None:
    identifier = affected[0]
    result_id = event_payload.get("result_id")
    if not isinstance(result_id, str):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "attempt abandonment event has no recovery result identity",
        )
    additions: dict[str, tuple[str, ...]] = {}
    for field in ("accepted_results", "artifacts"):
        added, removed, modified = _v4_node_mutation_mapping_delta(
            before.get(field),
            after.get(field),
            operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
            field=field,
        )
        if added != (result_id,) or removed or modified:
            raise _v4_node_mutation_error(
                "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
                "attempt abandonment must append one immutable recovery result and artifact",
                details={
                    "field": field,
                    "added": list(added),
                    "removed": list(removed),
                    "modified": list(modified),
                },
            )
        additions[field] = added
    accepted = _v4_node_mutation_mapping(
        after.get("accepted_results"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="accepted_results",
    )
    record = accepted[result_id]
    if not isinstance(record, Mapping):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "recovery result record must be an object",
        )
    result = record.get("result")
    receipt = record.get("receipt")
    expected_record_fields = {
        "schema",
        "result",
        "receipt",
        "accepted",
        "current",
        "controller_owned",
        "lease_quiesced",
        "runtime_live",
    }
    if (
        set(record) != expected_record_fields
        or record.get("schema")
        != V4_ATTEMPT_ABANDONMENT_RECORD_SCHEMA
        or not isinstance(result, Mapping)
        or result.get("schema") != V4_ATTEMPT_ABANDONMENT_SCHEMA
        or result.get("result_id") != result_id
        or result.get("node_instance_id") != identifier
        or result.get("attempt")
        != len(after_nodes[identifier].get("attempts", ()))
        or result.get("assignment_id")
        != event_payload.get("assignment_id")
        or result.get("lease_id") != event_payload.get("lease_id")
        or result.get("quiescence_proof_sha256")
        != event_payload.get("quiescence_proof_sha256")
        or result.get("reason") != event_payload.get("reason")
        or result.get("outcome") != "BLOCKED"
        or result.get("controller_owned") is not True
        or record.get("accepted") is not True
        or record.get("current") is not True
        or record.get("controller_owned") is not True
        or record.get("lease_quiesced") is not True
        or record.get("runtime_live") is not False
        or not isinstance(receipt, Mapping)
        or set(receipt)
        != {
            "accepted_revision",
            "event_id",
            "authorization_id",
            "payload",
        }
        or receipt.get("accepted_revision") != expected_revision + 1
        or receipt.get("event_id") != event_id
        or receipt.get("authorization_id")
        != event_payload.get("manager_authorization_id")
        or receipt.get("payload") != dict(event_payload)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "recovery result record differs from its controller-derived event",
            details={"result_id": result_id},
        )
    content = _v4_attempt_abandonment_canonical_bytes(result)
    artifact_sha256 = hashlib.sha256(content).hexdigest()
    artifacts = _v4_node_mutation_mapping(
        after.get("artifacts"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="artifacts",
    )
    if artifacts[result_id] != {
        "id": result_id,
        "semantic_sha256": artifact_sha256,
        "sha256": artifact_sha256,
        "size": len(content),
        "kind": V4_ATTEMPT_ABANDONMENT_SCHEMA,
        "locator": event_payload.get("locator"),
    }:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "recovery artifact reference is not content addressed",
            details={"result_id": result_id},
        )
    old_current = _v4_node_mutation_mapping(
        before.get("current_results"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="current_results",
    )
    new_current = _v4_node_mutation_mapping(
        after.get("current_results"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="current_results",
    )
    expected_current = dict(old_current)
    expected_current[identifier] = result_id
    if dict(new_current) != expected_current:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "recovery result must become the affected node's exact current result",
        )
    for field in ("integration", "integration_verification", "review"):
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value == new_value:
            continue
        if field in {"integration_verification", "review"}:
            valid = isinstance(old_value, Mapping) and new_value is None
        else:
            valid = (
                isinstance(old_value, Mapping)
                and isinstance(new_value, Mapping)
                and old_value.get("current") is True
                and new_value.get("current") is False
                and all(
                    old_value.get(key) == value
                    for key, value in new_value.items()
                    if key != "current"
                )
                and set(old_value) == set(new_value)
            )
        if not valid:
            raise _v4_node_mutation_error(
                "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
                "attempt abandonment exceeded downstream invalidation policy",
                details={"field": field},
            )


def _v4_node_mutation_validate_retry_orchestration(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    affected: tuple[str, ...],
    before_nodes: Mapping[str, Mapping[str, object]],
) -> None:
    identifier = affected[0]
    added, removed, modified = _v4_node_mutation_mapping_delta(
        before.get("pending_retries"),
        after.get("pending_retries"),
        operation=V4_NODE_MUTATION_RETRY_READY,
        field="pending_retries",
    )
    if added != (identifier,) or removed or modified:
        raise _v4_node_mutation_error(
            "V4_RETRY_READY_ORCHESTRATION_INVALID",
            "retry readiness must append only its affected pending retry",
            details={
                "added": list(added),
                "removed": list(removed),
                "modified": list(modified),
            },
        )
    pending = _v4_node_mutation_mapping(
        after.get("pending_retries"),
        operation=V4_NODE_MUTATION_RETRY_READY,
        field="pending_retries",
    )
    record = pending[identifier]
    previous_attempt = len(
        before_nodes[identifier].get("attempts", ())
    )
    if (
        not isinstance(record, Mapping)
        or record.get("previous_attempt") != previous_attempt
        or record.get("next_attempt") != previous_attempt + 1
    ):
        raise _v4_node_mutation_error(
            "V4_RETRY_READY_ORCHESTRATION_INVALID",
            "pending retry does not bind the preserved attempt generation",
            details={"node_instance_id": identifier},
        )


def _v4_node_mutation_validate_orchestration_semantics(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    operation: str,
    affected: tuple[str, ...],
    before_nodes: Mapping[str, Mapping[str, object]],
    after_nodes: Mapping[str, Mapping[str, object]],
    expected_revision: int,
    event_id: str,
    event_payload: Mapping[str, object],
    old_state: Mapping[str, object],
) -> None:
    _v4_node_mutation_validate_manager_nonce(
        before,
        after,
        required=True,
    )
    if operation == V4_NODE_MUTATION_MAP_EXPAND:
        _v4_node_mutation_validate_map_orchestration(
            before,
            after,
            affected=affected,
            after_nodes=after_nodes,
        )
    elif operation == V4_NODE_MUTATION_MAP_INVALIDATE:
        facts = v4_map_invalidation_facts(
            old_state,
            phase=str(event_payload.get("phase")),
            reason=(
                str(event_payload.get("reason"))
                if event_payload.get("phase") == "STALE"
                else None
            ),
            minimum_successor_map_epoch=(
                event_payload.get("minimum_successor_map_epoch")
                if event_payload.get("phase") == "STALE"
                else None
            ),
            manager_authorization_id=str(
                event_payload.get(
                    "manager_authorization_id", ""
                )
            ),
        )
        projection = facts["orchestration_projection"]
        assert isinstance(projection, Mapping)
        mismatched = sorted(
            field
            for field, value in projection.items()
            if after.get(field)
            != _workflow_transition_public(value)
        )
        if mismatched:
            raise _v4_node_mutation_error(
                "V4_MAP_INVALIDATION_ORCHESTRATION_INVALID",
                "map invalidation candidate differs from its exact stale projection",
                details={"fields": mismatched},
            )
    elif operation == V4_NODE_MUTATION_FRONTIER_READY:
        # Readiness is a node projection of the package-recomputed frontier.
        # The only orchestration write it may share is the manager nonce
        # consumption already checked above.
        return
    elif operation == V4_NODE_MUTATION_ATTEMPT_START:
        _v4_node_mutation_validate_attempt_orchestration(
            before,
            after,
            affected=affected,
            after_nodes=after_nodes,
        )
    elif operation == V4_NODE_MUTATION_ATTEMPT_ABANDON:
        _v4_node_mutation_validate_abandon_orchestration(
            before,
            after,
            affected=affected,
            after_nodes=after_nodes,
            expected_revision=expected_revision,
            event_id=event_id,
            event_payload=event_payload,
        )
    elif operation == V4_NODE_MUTATION_RESULT_ACCEPT:
        _v4_node_mutation_validate_result_orchestration(
            before,
            after,
            affected=affected,
            after_nodes=after_nodes,
        )
    else:
        _v4_node_mutation_validate_retry_orchestration(
            before,
            after,
            affected=affected,
            before_nodes=before_nodes,
        )


def _v4_node_mutation_validate_manager_nonce(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    required: bool = False,
) -> None:
    old_capabilities = _v4_node_mutation_mapping(
        before.get("manager_capabilities"),
        operation="NODE_MUTATION",
        field="manager_capabilities",
    )
    new_capabilities = _v4_node_mutation_mapping(
        after.get("manager_capabilities"),
        operation="NODE_MUTATION",
        field="manager_capabilities",
    )
    added, removed, modified = _v4_node_mutation_mapping_delta(
        old_capabilities,
        new_capabilities,
        operation="NODE_MUTATION",
        field="manager_capabilities",
    )
    if not added and not removed and not modified:
        if required:
            raise _v4_node_mutation_error(
                "V4_NODE_MUTATION_MANAGER_NONCE_REQUIRED",
                "controller node mutation must consume one exact manager nonce",
            )
        return
    if added or removed or len(modified) != 1:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_NONCE_INVALID",
            "node mutation may update only one existing manager nonce ledger",
            details={
                "added": list(added),
                "removed": list(removed),
                "modified": list(modified),
            },
        )
    capability_id = modified[0]
    old_record = old_capabilities[capability_id]
    new_record = new_capabilities[capability_id]
    if not isinstance(old_record, Mapping) or not isinstance(
        new_record, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_NONCE_INVALID",
            "manager capability verifier must remain an object",
        )
    if any(
        old_record.get(key) != value
        for key, value in new_record.items()
        if key != "used_request_nonce_sha256s"
    ) or (
        set(old_record) != set(new_record)
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_NONCE_INVALID",
            "node mutation cannot rewrite manager capability scope",
            details={"capability_id": capability_id},
        )
    old_nonces = old_record.get("used_request_nonce_sha256s")
    new_nonces = new_record.get("used_request_nonce_sha256s")
    if (
        not isinstance(old_nonces, (list, tuple))
        or not isinstance(new_nonces, (list, tuple))
        or any(not isinstance(item, str) for item in old_nonces)
        or any(not isinstance(item, str) for item in new_nonces)
        or len(new_nonces) != len(old_nonces) + 1
        or not set(old_nonces).issubset(new_nonces)
        or len(set(new_nonces)) != len(new_nonces)
        or list(new_nonces)
        != sorted(new_nonces, key=_v4_node_mutation_utf8)
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_NONCE_INVALID",
            "manager nonce ledger must append one unique canonical digest",
            details={"capability_id": capability_id},
        )


def _v4_node_mutation_node_map(
    state: Mapping[str, object],
) -> dict[str, Mapping[str, object]]:
    values = state.get("node_instances")
    if not isinstance(values, (list, tuple)):
        raise _v4_node_mutation_error(
            "NODE_INSTANCE_INVALID",
            "schema-v4 node mutation requires node instances",
        )
    result: dict[str, Mapping[str, object]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            raise _v4_node_mutation_error(
                "NODE_INSTANCE_INVALID",
                "schema-v4 node instance must be an object",
            )
        identifier = value.get("node_instance_id")
        if not isinstance(identifier, str) or not identifier:
            raise _v4_node_mutation_error(
                "NODE_INSTANCE_INVALID",
                "schema-v4 node instance has no stable identity",
            )
        if identifier in result:
            raise _v4_node_mutation_error(
                "NODE_INSTANCE_INVALID",
                "schema-v4 node instance identities must be unique",
                details={"node_instance_id": identifier},
            )
        result[identifier] = value
    return result


def _v4_node_mutation_index(
    state: Mapping[str, object], node_instance_id: str
) -> int:
    values = state.get("node_instances")
    assert isinstance(values, (list, tuple))
    for index, value in enumerate(values):
        if (
            isinstance(value, Mapping)
            and value.get("node_instance_id") == node_instance_id
        ):
            return index
    raise _v4_node_mutation_error(
        "NODE_INSTANCE_UNKNOWN",
        "authorized node instance is absent from the candidate",
        details={"node_instance_id": node_instance_id},
    )


def _v4_node_mutation_same_except(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    allowed_fields: Sequence[str],
    code: str,
) -> None:
    allowed = set(allowed_fields)
    changed = sorted(
        key
        for key in set(before) | set(after)
        if key not in allowed and before.get(key) != after.get(key)
    )
    if changed:
        raise _v4_node_mutation_error(
            code,
            "node mutation changed fields outside its operation policy",
            details={
                "node_instance_id": before.get("node_instance_id"),
                "fields": changed,
            },
        )


def _v4_node_mutation_validate_map_expand(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    bundle: object,
    candidate_state: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    removed = sorted(set(before) - set(after), key=_v4_node_mutation_utf8)
    added = tuple(
        sorted(set(after) - set(before), key=_v4_node_mutation_utf8)
    )
    modified = sorted(
        (
            identifier
            for identifier in set(before) & set(after)
            if before[identifier] != after[identifier]
        ),
        key=_v4_node_mutation_utf8,
    )
    if removed or modified or not added:
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_INVALID",
            "map expansion may only append one or more immutable children",
            details={
                "added": list(added),
                "removed": removed,
                "modified": modified,
            },
        )
    graph_nodes = getattr(bundle, "nodes", None)
    if not isinstance(graph_nodes, Mapping):
        raise _v4_node_mutation_error(
            "WORKFLOW_GRAPH_INVALID",
            "pinned workflow has no validated node registry",
        )
    repository_ids: list[str] = []
    added_set = set(added)
    for identifier in added:
        node = after[identifier]
        repository_id = node.get("repository_id")
        if not isinstance(repository_id, str) or not repository_id:
            raise _v4_node_mutation_error(
                "V4_MAP_EXPANSION_INVALID",
                "map child must bind one repository identity",
                details={"node_instance_id": identifier},
            )
        repository_ids.append(repository_id)
        if (
            node.get("state") != "PENDING"
            or node.get("attempts") not in ([], ())
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_EXPANSION_INVALID",
                "map child must begin PENDING with empty attempt history",
                details={"node_instance_id": identifier},
            )
        if node.get("node_id") not in graph_nodes:
            raise _v4_node_mutation_error(
                "V4_MAP_EXPANSION_INVALID",
                "map child node contract is absent from the pinned bundle",
                details={
                    "node_instance_id": identifier,
                    "node_id": node.get("node_id"),
                },
            )
        dependencies = node.get("dependencies")
        if not isinstance(dependencies, (list, tuple)) or any(
            dependency not in added_set for dependency in dependencies
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_EXPANSION_INVALID",
                "map child dependencies must resolve within this expansion",
                details={"node_instance_id": identifier},
            )
    if len(repository_ids) != len(set(repository_ids)):
        raise _v4_node_mutation_error(
            "V4_MAP_EXPANSION_INVALID",
            "map expansion may create only one child per repository",
            details={"repository_ids": repository_ids},
        )
    pointers = tuple(
        sorted(
            (
                f"/node_instances/{_v4_node_mutation_index(candidate_state, identifier)}"
                for identifier in added
            ),
            key=_v4_node_mutation_utf8,
        )
    )
    return added, pointers


def v4_frontier_ready_facts(
    state: Mapping[str, object],
) -> Mapping[str, object]:
    """Return the package-recomputed deterministic dependency frontier."""

    orchestration = state.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise _v4_node_mutation_error(
            "V4_FRONTIER_ORCHESTRATION_INVALID",
            "frontier readiness requires persisted orchestration state",
        )
    expansion = orchestration.get("expansion")
    if not isinstance(expansion, Mapping):
        raise _v4_node_mutation_error(
            "V4_FRONTIER_EXPANSION_REQUIRED",
            "frontier readiness requires a persisted map expansion",
        )
    if expansion.get("current", True) is not True:
        raise _v4_node_mutation_error(
            "V4_FRONTIER_EXPANSION_STALE",
            "a stale map expansion cannot produce a dispatch frontier",
        )
    children_value = expansion.get("children")
    if not isinstance(children_value, (list, tuple)):
        raise _v4_node_mutation_error(
            "V4_FRONTIER_EXPANSION_INVALID",
            "persisted map children must be an ordered array",
        )
    child_ids = tuple(
        str(child.get("node_instance_id"))
        for child in children_value
        if isinstance(child, Mapping)
        and isinstance(child.get("node_instance_id"), str)
    )
    if len(child_ids) != len(children_value) or len(
        set(child_ids)
    ) != len(child_ids):
        raise _v4_node_mutation_error(
            "V4_FRONTIER_EXPANSION_INVALID",
            "persisted map children must have unique stable identities",
        )
    nodes = _v4_node_mutation_node_map(state)
    current_results = _v4_node_mutation_mapping(
        orchestration.get("current_results"),
        operation=V4_NODE_MUTATION_FRONTIER_READY,
        field="current_results",
    )
    frontier: list[str] = []
    dependency_result_ids: dict[str, dict[str, object]] = {}
    for identifier in sorted(child_ids, key=_v4_node_mutation_utf8):
        node = nodes.get(identifier)
        if not isinstance(node, Mapping):
            raise _v4_node_mutation_error(
                "V4_FRONTIER_EXPANSION_INVALID",
                "persisted map child has no matching node instance",
                details={"node_instance_id": identifier},
            )
        if node.get("state") != "PENDING":
            continue
        dependencies = node.get("dependencies")
        if not isinstance(dependencies, (list, tuple)):
            raise _v4_node_mutation_error(
                "V4_FRONTIER_EXPANSION_INVALID",
                "map child dependencies must be an ordered array",
                details={"node_instance_id": identifier},
            )
        dependency_facts: dict[str, object] = {}
        ready = True
        for dependency in dependencies:
            dependency_node = nodes.get(str(dependency))
            if (
                not isinstance(dependency_node, Mapping)
                or dependency_node.get("state") != "SUCCEEDED"
                or dependency not in current_results
            ):
                ready = False
                break
            dependency_facts[str(dependency)] = current_results[
                dependency
            ]
        if ready:
            frontier.append(identifier)
            dependency_result_ids[identifier] = dependency_facts
    core = {
        "schema": "dev-flow-frontier-ready/v1",
        "task_id": state.get("task_id"),
        "bundle_sha256": (
            state.get("workflow_ref", {}).get("bundle_sha256")
            if isinstance(state.get("workflow_ref"), Mapping)
            else None
        ),
        "plan_id": expansion.get("plan_id"),
        "dag_sha256": expansion.get("dag_sha256"),
        "map_epoch": expansion.get("map_epoch"),
        "node_instance_ids": frontier,
        "dependency_result_ids": dependency_result_ids,
    }
    return MappingProxyType(
        {
            **core,
            "frontier_sha256": _sha256_contract(core),
        }
    )


def _v4_node_mutation_validate_frontier_ready(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    event_payload: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    facts = v4_frontier_ready_facts(old_state)
    affected = tuple(facts["node_instance_ids"])
    if not affected:
        raise _v4_node_mutation_error(
            "V4_FRONTIER_EMPTY",
            "the current dependency frontier contains no pending children",
        )
    required_payload = {
        "operation": V4_NODE_MUTATION_FRONTIER_READY,
        "plan_id": facts["plan_id"],
        "dag_sha256": facts["dag_sha256"],
        "map_epoch": facts["map_epoch"],
        "node_instance_ids": list(affected),
        "dependency_result_ids": _workflow_transition_public(
            facts["dependency_result_ids"]
        ),
        "frontier_sha256": facts["frontier_sha256"],
    }
    mismatched = sorted(
        key
        for key, value in required_payload.items()
        if event_payload.get(key) != value
    )
    if mismatched:
        raise _v4_node_mutation_error(
            "V4_FRONTIER_FACTS_MISMATCH",
            "caller frontier facts differ from the package-recomputed frontier",
            details={
                "fields": mismatched,
                "expected": required_payload,
            },
        )
    added = sorted(set(after) - set(before), key=_v4_node_mutation_utf8)
    removed = sorted(set(before) - set(after), key=_v4_node_mutation_utf8)
    changed = tuple(
        sorted(
            (
                identifier
                for identifier in set(before) & set(after)
                if before[identifier] != after[identifier]
            ),
            key=_v4_node_mutation_utf8,
        )
    )
    if added or removed or changed != affected:
        raise _v4_node_mutation_error(
            "V4_FRONTIER_SELECTION_INVALID",
            "frontier readiness must advance the complete deterministic frontier",
            details={
                "expected": list(affected),
                "changed": list(changed),
                "added": added,
                "removed": removed,
            },
        )
    pointers: list[str] = []
    for identifier in affected:
        old_node = before[identifier]
        new_node = after[identifier]
        _v4_node_mutation_same_except(
            old_node,
            new_node,
            allowed_fields=("state",),
            code="V4_FRONTIER_SELECTION_INVALID",
        )
        if (
            old_node.get("state") != "PENDING"
            or new_node.get("state") != "READY"
            or new_node.get("attempts") != old_node.get("attempts")
        ):
            raise _v4_node_mutation_error(
                "V4_FRONTIER_SELECTION_INVALID",
                "frontier children may only advance PENDING to READY",
                details={"node_instance_id": identifier},
            )
        pointers.append(
            f"/node_instances/"
            f"{_v4_node_mutation_index(candidate_state, identifier)}"
            "/state"
        )
    return affected, tuple(
        sorted(pointers, key=_v4_node_mutation_utf8)
    )


def _v4_attempt_abandonment_canonical_bytes(
    value: Mapping[str, object],
) -> bytes:
    return json.dumps(
        _workflow_transition_public(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _v4_map_stale_projection(
    value: object,
    *,
    field: str,
    reason: str,
) -> object:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_ORCHESTRATION_INVALID",
            "downstream orchestration projection must be an object",
            details={"field": field},
        )
    projected = copy.deepcopy(_workflow_transition_public(value))
    assert isinstance(projected, dict)
    if field == "barriers":
        for record in projected.values():
            if not isinstance(record, dict):
                raise _v4_node_mutation_error(
                    "V4_MAP_INVALIDATION_ORCHESTRATION_INVALID",
                    "barrier projection contains a non-object record",
                )
            record["status"] = "REOPENED"
            record["aggregate"] = None
            record["current"] = False
            record["stale_reason"] = reason
        return projected
    projected["current"] = False
    projected["stale_reason"] = reason
    return projected


def v4_map_invalidation_facts(
    state: Mapping[str, object],
    *,
    phase: str,
    manager_authorization_id: str,
    reason: str | None = None,
    minimum_successor_map_epoch: int | None = None,
) -> Mapping[str, object]:
    """Derive the exact two-phase stale/retired map projection."""

    if phase not in {"STALE", "RETIRED"}:
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_PHASE_INVALID",
            "map invalidation phase must be STALE or RETIRED",
        )
    if (
        not isinstance(manager_authorization_id, str)
        or not manager_authorization_id
    ):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_AUTHORIZATION_REQUIRED",
            "map invalidation requires manager authorization identity",
        )
    orchestration = state.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_ORCHESTRATION_INVALID",
            "map invalidation requires persisted orchestration state",
        )
    expansion_value = orchestration.get("expansion")
    if not isinstance(expansion_value, Mapping):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_EXPANSION_REQUIRED",
            "map invalidation requires a persisted expansion",
        )
    expansion = copy.deepcopy(
        _workflow_transition_public(expansion_value)
    )
    assert isinstance(expansion, dict)
    children = expansion.get("children")
    child_ids = tuple(
        sorted(
            (
                str(child["node_instance_id"])
                for child in children
                if isinstance(child, Mapping)
                and isinstance(child.get("node_instance_id"), str)
            ),
            key=_v4_node_mutation_utf8,
        )
    ) if isinstance(children, (list, tuple)) else ()
    if not child_ids or len(child_ids) != len(children):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_EXPANSION_INVALID",
            "map invalidation requires canonical persisted children",
        )
    next_revision = int(state.get("revision", -1)) + 1
    if phase == "STALE":
        if expansion.get("current", True) is not True:
            raise _v4_node_mutation_error(
                "V4_MAP_INVALIDATION_ALREADY_STALE",
                "only a current expansion can enter the stale phase",
            )
        if not isinstance(reason, str) or not reason.strip():
            raise _v4_node_mutation_error(
                "V4_MAP_INVALIDATION_REASON_REQUIRED",
                "map invalidation requires a non-empty drift reason",
            )
        if len(reason.encode("utf-8")) > 1024:
            raise _v4_node_mutation_error(
                "V4_MAP_INVALIDATION_REASON_INVALID",
                "map invalidation reason exceeds its fixed byte bound",
            )
        map_epoch = expansion.get("map_epoch")
        if (
            isinstance(map_epoch, bool)
            or not isinstance(map_epoch, int)
            or isinstance(minimum_successor_map_epoch, bool)
            or not isinstance(minimum_successor_map_epoch, int)
            or minimum_successor_map_epoch <= map_epoch
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_SUCCESSOR_EPOCH_INVALID",
                "successor epoch lower bound must exceed the stale map epoch",
                details={"map_epoch": map_epoch},
            )
        stale_core = {
            "schema": "dev-flow-map-invalidation-facts/v1",
            "task_id": state.get("task_id"),
            "workflow_bundle_sha256": expansion.get(
                "workflow_bundle_sha256"
            ),
            "plan_id": expansion.get("plan_id"),
            "dag_sha256": expansion.get("dag_sha256"),
            "semantic_input_sha256": expansion.get(
                "semantic_input_sha256"
            ),
            "map_epoch": map_epoch,
            "node_instance_ids": list(child_ids),
            "reason": reason,
            "stale_at_revision": next_revision,
            "minimum_successor_map_epoch": (
                minimum_successor_map_epoch
            ),
        }
        stale_digest = _sha256_contract(stale_core)
        expansion.update(
            {
                "current": False,
                "stale_reason": reason,
                "stale_at_revision": next_revision,
                "stale_facts_sha256": stale_digest,
                "minimum_successor_map_epoch": (
                    minimum_successor_map_epoch
                ),
            }
        )
        current_results = _v4_node_mutation_mapping(
            orchestration.get("current_results"),
            operation=V4_NODE_MUTATION_MAP_INVALIDATE,
            field="current_results",
        )
        projected_current = {
            key: copy.deepcopy(
                _workflow_transition_public(value)
            )
            for key, value in current_results.items()
            if key not in child_ids
        }
        projected = {
            "approval": None,
            "barriers": _v4_map_stale_projection(
                orchestration.get("barriers"),
                field="barriers",
                reason=reason,
            ),
            "current_results": projected_current,
            "expansion": expansion,
            "integration": _v4_map_stale_projection(
                orchestration.get("integration"),
                field="integration",
                reason=reason,
            ),
            "integration_verification": _v4_map_stale_projection(
                orchestration.get("integration_verification"),
                field="integration_verification",
                reason=reason,
            ),
            "review": _v4_map_stale_projection(
                orchestration.get("review"),
                field="review",
                reason=reason,
            ),
        }
        event_payload = {
            "operation": V4_NODE_MUTATION_MAP_INVALIDATE,
            "phase": phase,
            "plan_id": expansion.get("plan_id"),
            "dag_sha256": expansion.get("dag_sha256"),
            "map_epoch": map_epoch,
            "node_instance_ids": list(child_ids),
            "reason": reason,
            "stale_at_revision": next_revision,
            "stale_facts_sha256": stale_digest,
            "minimum_successor_map_epoch": (
                minimum_successor_map_epoch
            ),
            "manager_authorization_id": manager_authorization_id,
        }
    else:
        if (
            expansion.get("current") is not False
            or "retired_at_revision" in expansion
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_RETIREMENT_STATE_INVALID",
                "only a stale non-retired expansion can be retired",
            )
        _v4_map_invalidation_assert_quiesced(
            state, child_ids=child_ids
        )
        expansion["retired_at_revision"] = next_revision
        projected = {
            "approval": orchestration.get("approval"),
            "barriers": orchestration.get("barriers"),
            "current_results": orchestration.get("current_results"),
            "expansion": expansion,
            "integration": orchestration.get("integration"),
            "integration_verification": orchestration.get(
                "integration_verification"
            ),
            "review": orchestration.get("review"),
        }
        event_payload = {
            "operation": V4_NODE_MUTATION_MAP_INVALIDATE,
            "phase": phase,
            "plan_id": expansion.get("plan_id"),
            "dag_sha256": expansion.get("dag_sha256"),
            "map_epoch": expansion.get("map_epoch"),
            "node_instance_ids": list(child_ids),
            "stale_facts_sha256": expansion.get(
                "stale_facts_sha256"
            ),
            "retired_at_revision": next_revision,
            "minimum_successor_map_epoch": expansion.get(
                "minimum_successor_map_epoch"
            ),
            "manager_authorization_id": manager_authorization_id,
        }
    return MappingProxyType(
        {
            "phase": phase,
            "node_instance_ids": child_ids,
            "orchestration_projection": MappingProxyType(
                {
                    key: _workflow_state_freeze(value)
                    for key, value in projected.items()
                }
            ),
            "event_payload": MappingProxyType(event_payload),
        }
    )


def _v4_map_invalidation_assert_quiesced(
    state: Mapping[str, object],
    *,
    child_ids: Sequence[str],
) -> None:
    orchestration = state.get("orchestration")
    assert isinstance(orchestration, Mapping)
    leases = _v4_node_mutation_mapping(
        orchestration.get("leases"),
        operation=V4_NODE_MUTATION_MAP_INVALIDATE,
        field="leases",
    )
    proofs = _v4_node_mutation_mapping(
        orchestration.get("quiescence_proofs"),
        operation=V4_NODE_MUTATION_MAP_INVALIDATE,
        field="quiescence_proofs",
    )
    dispatch = _v4_node_mutation_mapping(
        orchestration.get("dispatch"),
        operation=V4_NODE_MUTATION_MAP_INVALIDATE,
        field="dispatch",
    )
    assignments = _v4_node_mutation_mapping(
        orchestration.get("assignments"),
        operation=V4_NODE_MUTATION_MAP_INVALIDATE,
        field="assignments",
    )
    child_set = set(child_ids)
    bound_running: set[tuple[str, int]] = set()
    for lease_id, lease_value in leases.items():
        try:
            lease = validate_worker_lease(lease_value)
        except Exception as exc:
            raise _v4_node_mutation_error(
                "V4_MAP_RETIREMENT_LEASE_INVALID",
                "map retirement encountered an invalid child lease",
                details={"lease_id": lease_id},
            ) from exc
        if lease.node_instance_id not in child_set:
            continue
        proof = proofs.get(lease_id)
        assignment_id = (
            proof.get("assignment_id")
            if isinstance(proof, Mapping)
            else None
        )
        assignment = assignments.get(assignment_id)
        runtime = dispatch.get(assignment_id)
        if (
            lease.state not in {"REVOKED", "EXPIRED"}
            or lease.quiesced_at_wall_ns is None
            or lease.quiescence_evidence_sha256 is None
            or not isinstance(proof, Mapping)
            or proof.get("quiesced") is not True
            or proof.get("proof_sha256")
            != lease.quiescence_evidence_sha256
            or not isinstance(assignment, Mapping)
            or assignment.get("node_instance_id")
            != lease.node_instance_id
            or assignment.get("attempt") != lease.attempt
            or not isinstance(runtime, Mapping)
            or runtime.get("runtime_status") != "QUIESCED"
            or runtime.get("runtime_live") is not False
        ):
            raise _v4_node_mutation_error(
                "V4_MAP_RETIREMENT_NOT_QUIESCED",
                "map retirement requires every child lease to be quiesced",
                details={"lease_id": lease_id},
            )
        bound_running.add((lease.node_instance_id, lease.attempt))
    nodes = _v4_node_mutation_node_map(state)
    stranded = []
    for identifier in child_ids:
        node = nodes[identifier]
        if node.get("state") != "RUNNING":
            continue
        attempts = node.get("attempts")
        attempt = len(attempts) if isinstance(
            attempts, (list, tuple)
        ) else 0
        if (identifier, attempt) not in bound_running:
            stranded.append(identifier)
    if stranded:
        raise _v4_node_mutation_error(
            "V4_MAP_RETIREMENT_NOT_QUIESCED",
            "running map children lack quiesced lease evidence",
            details={"node_instance_ids": stranded},
        )


def _v4_node_mutation_validate_map_invalidate(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    event_payload: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    phase = event_payload.get("phase")
    facts = v4_map_invalidation_facts(
        old_state,
        phase=str(phase),
        reason=(
            str(event_payload.get("reason"))
            if phase == "STALE"
            else None
        ),
        minimum_successor_map_epoch=(
            event_payload.get("minimum_successor_map_epoch")
            if phase == "STALE"
            else None
        ),
        manager_authorization_id=str(
            event_payload.get("manager_authorization_id", "")
        ),
    )
    expected_payload = dict(facts["event_payload"])
    mismatched = sorted(
        key
        for key, value in expected_payload.items()
        if event_payload.get(key) != value
    )
    if mismatched:
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_FACTS_MISMATCH",
            "map invalidation event differs from package-derived facts",
            details={"fields": mismatched},
        )
    affected = tuple(facts["node_instance_ids"])
    if set(before) != set(after):
        raise _v4_node_mutation_error(
            "V4_MAP_INVALIDATION_NODE_INVALID",
            "map invalidation cannot add or remove node history",
        )
    changed = tuple(
        sorted(
            (
                identifier
                for identifier in before
                if before[identifier] != after[identifier]
            ),
            key=_v4_node_mutation_utf8,
        )
    )
    pointers: list[str] = []
    if phase == "STALE":
        if changed:
            raise _v4_node_mutation_error(
                "V4_MAP_INVALIDATION_NODE_INVALID",
                "stale phase cannot change active child lifecycle",
                details={"changed": list(changed)},
            )
    else:
        expected_changed = tuple(
            identifier
            for identifier in affected
            if before[identifier].get("state") != "SKIPPED"
        )
        if changed != expected_changed:
            raise _v4_node_mutation_error(
                "V4_MAP_RETIREMENT_NODE_INVALID",
                "retirement must skip every old-generation child exactly",
                details={
                    "expected": list(expected_changed),
                    "changed": list(changed),
                },
            )
        for identifier in affected:
            old_node = before[identifier]
            new_node = after[identifier]
            _v4_node_mutation_same_except(
                old_node,
                new_node,
                allowed_fields=("state",),
                code="V4_MAP_RETIREMENT_NODE_INVALID",
            )
            if (
                new_node.get("state") != "SKIPPED"
                or new_node.get("attempts") != old_node.get("attempts")
            ):
                raise _v4_node_mutation_error(
                    "V4_MAP_RETIREMENT_NODE_INVALID",
                    "retirement must preserve child attempts while marking history skipped",
                    details={"node_instance_id": identifier},
                )
            if old_node.get("state") != "SKIPPED":
                pointers.append(
                    f"/node_instances/"
                    f"{_v4_node_mutation_index(candidate_state, identifier)}"
                    "/state"
                )
    return affected, tuple(
        sorted(pointers, key=_v4_node_mutation_utf8)
    )


def v4_attempt_abandonment_facts(
    state: Mapping[str, object],
    *,
    lease_id: str,
    reason: str,
    manager_authorization_id: str,
) -> Mapping[str, object]:
    """Derive one controller-owned blocked-result from quiesced truth."""

    if not isinstance(reason, str) or not reason.strip():
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_REASON_REQUIRED",
            "attempt abandonment requires a non-empty controller reason",
        )
    if len(reason.encode("utf-8")) > 1024:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_REASON_INVALID",
            "attempt abandonment reason exceeds its fixed byte bound",
        )
    if (
        not isinstance(manager_authorization_id, str)
        or not manager_authorization_id
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_AUTHORIZATION_REQUIRED",
            "attempt abandonment requires manager authorization identity",
        )
    orchestration = state.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ORCHESTRATION_INVALID",
            "attempt abandonment requires persisted orchestration state",
        )
    leases = _v4_node_mutation_mapping(
        orchestration.get("leases"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="leases",
    )
    lease_value = leases.get(lease_id)
    try:
        lease = validate_worker_lease(lease_value)
    except Exception as exc:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_LEASE_INVALID",
            "attempt abandonment requires a valid persisted worker lease",
            details={"lease_id": lease_id},
        ) from exc
    if (
        lease.state not in {"REVOKED", "EXPIRED"}
        or lease.quiesced_at_wall_ns is None
        or lease.quiescence_evidence_sha256 is None
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_NOT_QUIESCED",
            "attempt abandonment requires a revoked or expired quiesced lease",
            details={"lease_id": lease_id, "lease_state": lease.state},
        )
    proofs = _v4_node_mutation_mapping(
        orchestration.get("quiescence_proofs"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="quiescence_proofs",
    )
    proof = proofs.get(lease_id)
    if (
        not isinstance(proof, Mapping)
        or proof.get("lease_id") != lease_id
        or proof.get("quiesced") is not True
        or proof.get("proof_sha256")
        != lease.quiescence_evidence_sha256
        or not isinstance(proof.get("assignment_id"), str)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_NOT_QUIESCED",
            "attempt abandonment requires the exact persisted quiescence proof",
            details={"lease_id": lease_id},
        )
    assignment_id = str(proof["assignment_id"])
    assignments = _v4_node_mutation_mapping(
        orchestration.get("assignments"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="assignments",
    )
    assignment = assignments.get(assignment_id)
    if (
        not isinstance(assignment, Mapping)
        or assignment.get("node_instance_id")
        != lease.node_instance_id
        or assignment.get("attempt") != lease.attempt
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_ASSIGNMENT_INVALID",
            "quiesced lease does not bind its persisted assignment",
            details={"lease_id": lease_id},
        )
    dispatch = _v4_node_mutation_mapping(
        orchestration.get("dispatch"),
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
        field="dispatch",
    )
    dispatch_record = dispatch.get(assignment_id)
    if (
        not isinstance(dispatch_record, Mapping)
        or dispatch_record.get("runtime_status") != "QUIESCED"
        or dispatch_record.get("runtime_live") is not False
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_RUNTIME_LIVE",
            "attempt abandonment requires controller-observed runtime quiescence",
            details={"lease_id": lease_id},
        )
    nodes = _v4_node_mutation_node_map(state)
    node = nodes.get(lease.node_instance_id)
    attempts = node.get("attempts") if isinstance(node, Mapping) else None
    if (
        not isinstance(node, Mapping)
        or node.get("state") != "RUNNING"
        or not isinstance(attempts, (list, tuple))
        or len(attempts) != lease.attempt
        or not isinstance(attempts[-1], Mapping)
        or attempts[-1].get("state") != "RUNNING"
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_NODE_INVALID",
            "quiesced lease does not own the current running attempt",
            details={
                "node_instance_id": lease.node_instance_id,
                "attempt": lease.attempt,
            },
        )
    core = {
        "schema": V4_ATTEMPT_ABANDONMENT_SCHEMA,
        "task_id": state.get("task_id"),
        "workflow_bundle_sha256": lease.workflow_bundle_sha256,
        "node_instance_id": lease.node_instance_id,
        "repository_id": lease.repository_id,
        "attempt": lease.attempt,
        "assignment_id": assignment_id,
        "lease_id": lease_id,
        "quiescence_proof_sha256": (
            lease.quiescence_evidence_sha256
        ),
        "input_sha256": attempts[-1].get("input_sha256"),
        "outcome": "BLOCKED",
        "reason": reason,
        "controller_owned": True,
    }
    result_id = "attempt-abandonment-" + _sha256_contract(core)
    document = {**core, "result_id": result_id}
    content = _v4_attempt_abandonment_canonical_bytes(document)
    artifact_sha256 = hashlib.sha256(content).hexdigest()
    locator = (
        f"artifacts/orchestration/{artifact_sha256}.json"
    )
    event_payload = {
        "operation": V4_NODE_MUTATION_ATTEMPT_ABANDON,
        "result_id": result_id,
        "node_instance_id": lease.node_instance_id,
        "repository_id": lease.repository_id,
        "attempt": lease.attempt,
        "assignment_id": assignment_id,
        "lease_id": lease_id,
        "reason": reason,
        "quiescence_proof_sha256": (
            lease.quiescence_evidence_sha256
        ),
        "artifact_sha256": artifact_sha256,
        "locator": locator,
        "manager_authorization_id": manager_authorization_id,
    }
    return MappingProxyType(
        {
            "result_id": result_id,
            "node_instance_id": lease.node_instance_id,
            "attempt": lease.attempt,
            "input_sha256": attempts[-1].get("input_sha256"),
            "document": MappingProxyType(document),
            "content": content,
            "artifact_sha256": artifact_sha256,
            "artifact_size": len(content),
            "locator": locator,
            "event_payload": MappingProxyType(event_payload),
        }
    )


def build_v4_attempt_abandonment_retry_candidate(
    prior_result_value: object,
    prior_lease_value: object,
    quiescence_proof: object,
    retry_policy_value: object,
    *,
    expected_revision: int,
    current_revision: int,
    retry_approval_current: bool,
    worktree_strategy: str,
    worktree_fingerprint_sha256: str,
) -> object:
    """Authorize retry from a controller-owned abandonment result."""

    if not isinstance(prior_result_value, Mapping):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_RETRY_INVALID",
            "abandonment retry requires its persisted result record",
        )
    record = prior_result_value
    result = record.get("result")
    if (
        set(record)
        != {
            "schema",
            "result",
            "receipt",
            "accepted",
            "current",
            "controller_owned",
            "lease_quiesced",
            "runtime_live",
        }
        or record.get("schema")
        != V4_ATTEMPT_ABANDONMENT_RECORD_SCHEMA
        or record.get("accepted") is not True
        or record.get("current") is not True
        or record.get("controller_owned") is not True
        or record.get("lease_quiesced") is not True
        or record.get("runtime_live") is not False
        or not isinstance(result, Mapping)
        or result.get("schema") != V4_ATTEMPT_ABANDONMENT_SCHEMA
        or result.get("controller_owned") is not True
        or result.get("outcome") != "BLOCKED"
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_RETRY_INVALID",
            "retry source is not a current controller-owned abandonment",
        )
    lease = validate_runtime_lease_state(prior_lease_value)
    if (
        result.get("node_instance_id")
        != lease["node_instance_id"]
        or result.get("attempt") != lease["attempt"]
        or result.get("lease_id") != lease["lease_id"]
        or result.get("quiescence_proof_sha256")
        != getattr(quiescence_proof, "proof_sha256", None)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_RETRY_INVALID",
            "abandonment result, lease, and quiescence proof do not bind one attempt",
        )
    if not isinstance(retry_policy_value, Mapping):
        raise _v4_node_mutation_error(
            "RETRY_POLICY_INVALID",
            "retry policy must be an object",
        )
    policy = retry_policy_value
    if set(policy) != {
        "max_attempts",
        "retryable_outcomes",
        "requires_approval",
    }:
        raise _v4_node_mutation_error(
            "RETRY_POLICY_INVALID",
            "retry policy field set is invalid",
        )
    max_attempts = policy.get("max_attempts")
    retryable = policy.get("retryable_outcomes")
    requires_approval = policy.get("requires_approval")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts < 1
        or not isinstance(retryable, (list, tuple))
        or any(
            item not in {"FAILED", "BLOCKED"}
            for item in retryable
        )
        or list(retryable)
        != sorted(set(retryable), key=_v4_node_mutation_utf8)
        or not isinstance(requires_approval, bool)
        or not isinstance(retry_approval_current, bool)
    ):
        raise _v4_node_mutation_error(
            "RETRY_POLICY_INVALID",
            "retry policy values are invalid",
        )
    if "BLOCKED" not in retryable:
        raise _v4_node_mutation_error(
            "RETRY_OUTCOME_NOT_ALLOWED",
            "retry policy does not permit a blocked abandonment",
        )
    next_attempt = int(result["attempt"]) + 1
    if next_attempt > max_attempts:
        raise _v4_node_mutation_error(
            "RETRY_ATTEMPTS_EXHAUSTED",
            "retry policy has no remaining attempt",
            details={
                "max_attempts": max_attempts,
                "next_attempt": next_attempt,
            },
        )
    if requires_approval and not retry_approval_current:
        raise _v4_node_mutation_error(
            "RETRY_APPROVAL_REQUIRED",
            "retry requires a current explicit approval",
        )
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or isinstance(current_revision, bool)
        or not isinstance(current_revision, int)
        or expected_revision != current_revision
    ):
        raise _v4_node_mutation_error(
            "RETRY_REVISION_CONFLICT",
            "retry expected revision is stale",
            details={
                "expected": expected_revision,
                "current": current_revision,
            },
        )
    replacement = authorize_replacement_lease(
        lease,
        quiescence_proof,
        next_attempt=next_attempt,
        worktree_strategy=worktree_strategy,
        worktree_fingerprint_sha256=(
            worktree_fingerprint_sha256
        ),
    )
    return RetryCandidate(
        node_instance_id=str(result["node_instance_id"]),
        previous_attempt=int(result["attempt"]),
        next_attempt=replacement.next_attempt,
        expected_revision=expected_revision,
        candidate_revision=current_revision + 1,
        worktree_strategy=replacement.worktree_strategy,
        worktree_fingerprint_sha256=(
            replacement.worktree_fingerprint_sha256
        ),
    )


def _v4_node_mutation_validate_attempt_abandon(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    event_id: str,
    event_payload: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    facts = v4_attempt_abandonment_facts(
        old_state,
        lease_id=str(event_payload.get("lease_id", "")),
        reason=str(event_payload.get("reason", "")),
        manager_authorization_id=str(
            event_payload.get("manager_authorization_id", "")
        ),
    )
    expected_payload = dict(facts["event_payload"])
    mismatched = sorted(
        key
        for key, value in expected_payload.items()
        if event_payload.get(key) != value
    )
    if mismatched:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_FACTS_MISMATCH",
            "attempt abandonment event differs from controller-derived facts",
            details={"fields": mismatched},
        )
    identifier = _v4_node_mutation_changed_existing(
        before,
        after,
        operation=V4_NODE_MUTATION_ATTEMPT_ABANDON,
    )
    if identifier != facts["node_instance_id"]:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_NODE_INVALID",
            "attempt abandonment changed a node outside its quiesced lease",
        )
    old_node = before[identifier]
    new_node = after[identifier]
    _v4_node_mutation_same_except(
        old_node,
        new_node,
        allowed_fields=("state", "attempts"),
        code="V4_ATTEMPT_ABANDON_NODE_INVALID",
    )
    old_attempts = old_node.get("attempts")
    new_attempts = new_node.get("attempts")
    if (
        old_node.get("state") != "RUNNING"
        or new_node.get("state") != "BLOCKED"
        or not isinstance(old_attempts, (list, tuple))
        or not isinstance(new_attempts, (list, tuple))
        or not old_attempts
        or len(old_attempts) != len(new_attempts)
        or list(old_attempts[:-1]) != list(new_attempts[:-1])
        or not isinstance(old_attempts[-1], Mapping)
        or not isinstance(new_attempts[-1], Mapping)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_NODE_INVALID",
            "attempt abandonment must move the current RUNNING attempt to BLOCKED",
            details={"node_instance_id": identifier},
        )
    old_attempt = old_attempts[-1]
    new_attempt = new_attempts[-1]
    _v4_node_mutation_same_except(
        old_attempt,
        new_attempt,
        allowed_fields=("state", "result_refs"),
        code="V4_ATTEMPT_HISTORY_REWRITE",
    )
    old_refs = old_attempt.get("result_refs")
    new_refs = new_attempt.get("result_refs")
    if (
        old_attempt.get("state") != "RUNNING"
        or new_attempt.get("state") != "BLOCKED"
        or not isinstance(old_refs, (list, tuple))
        or not isinstance(new_refs, (list, tuple))
        or len(new_refs) != len(old_refs) + 1
        or list(new_refs[:-1]) != list(old_refs)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_HISTORY_REWRITE",
            "attempt abandonment must preserve history and append one recovery reference",
            details={"node_instance_id": identifier},
        )
    expected_reference = {
        "schema": _workflow_state_result_reference_schema,
        "result_id": facts["result_id"],
        "task_id": old_state.get("task_id"),
        "bundle_sha256": old_state.get("workflow_ref", {}).get(
            "bundle_sha256"
        ),
        "node_instance_id": identifier,
        "attempt": facts["attempt"],
        "input_sha256": facts["input_sha256"],
        "output_sha256": facts["artifact_sha256"],
        "locator": facts["locator"],
    }
    if new_refs[-1] != expected_reference:
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_ABANDON_REFERENCE_INVALID",
            "attempt abandonment recovery reference is not controller-derived",
        )
    node_index = _v4_node_mutation_index(
        candidate_state, identifier
    )
    attempt_index = len(new_attempts) - 1
    pointers = (
        f"/node_instances/{node_index}/state",
        f"/node_instances/{node_index}/attempts/{attempt_index}/state",
        f"/node_instances/{node_index}/attempts/{attempt_index}/result_refs/{len(old_refs)}",
    )
    return (identifier,), tuple(
        sorted(pointers, key=_v4_node_mutation_utf8)
    )


def _v4_node_mutation_changed_existing(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    operation: str,
) -> str:
    added = sorted(set(after) - set(before), key=_v4_node_mutation_utf8)
    removed = sorted(set(before) - set(after), key=_v4_node_mutation_utf8)
    changed = sorted(
        (
            identifier
            for identifier in set(before) & set(after)
            if before[identifier] != after[identifier]
        ),
        key=_v4_node_mutation_utf8,
    )
    if added or removed or len(changed) != 1:
        raise _v4_node_mutation_error(
            f"V4_{operation}_INVALID",
            "node mutation operation must change exactly one existing node",
            details={
                "added": added,
                "removed": removed,
                "changed": changed,
            },
        )
    return changed[0]


def _v4_node_mutation_validate_attempt_start(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    candidate_state: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identifier = _v4_node_mutation_changed_existing(
        before, after, operation=V4_NODE_MUTATION_ATTEMPT_START
    )
    old_node = before[identifier]
    new_node = after[identifier]
    _v4_node_mutation_same_except(
        old_node,
        new_node,
        allowed_fields=("state", "attempts"),
        code="V4_ATTEMPT_START_INVALID",
    )
    if old_node.get("state") != "READY" or new_node.get("state") != "RUNNING":
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_INVALID",
            "attempt start requires READY to RUNNING node lifecycle",
            details={
                "node_instance_id": identifier,
                "before": old_node.get("state"),
                "after": new_node.get("state"),
            },
        )
    old_attempts = old_node.get("attempts")
    new_attempts = new_node.get("attempts")
    if not isinstance(old_attempts, (list, tuple)) or not isinstance(
        new_attempts, (list, tuple)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_INVALID",
            "attempt start requires ordered attempt history",
        )
    if (
        len(new_attempts) != len(old_attempts) + 1
        or list(new_attempts[:-1]) != list(old_attempts)
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_HISTORY_REWRITE",
            "attempt start must preserve history and append exactly one attempt",
            details={"node_instance_id": identifier},
        )
    if old_attempts:
        latest_old = old_attempts[-1]
        if (
            not isinstance(latest_old, Mapping)
            or latest_old.get("state") not in {"FAILED", "BLOCKED"}
        ):
            raise _v4_node_mutation_error(
                "V4_ATTEMPT_START_INVALID",
                "a later attempt requires a preserved failed or blocked predecessor",
                details={"node_instance_id": identifier},
            )
    latest = new_attempts[-1]
    if (
        not isinstance(latest, Mapping)
        or latest.get("state") != "RUNNING"
        or latest.get("result_refs") not in ([], ())
        or "runtime_handle" not in latest
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_START_INVALID",
            "new attempt must be RUNNING, empty, and runtime-bound",
            details={"node_instance_id": identifier},
        )
    node_index = _v4_node_mutation_index(candidate_state, identifier)
    pointers = (
        f"/node_instances/{node_index}/attempts/{len(old_attempts)}",
        f"/node_instances/{node_index}/state",
    )
    return (identifier,), tuple(
        sorted(pointers, key=_v4_node_mutation_utf8)
    )


def _v4_node_mutation_validate_result_accept(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    candidate_state: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identifier = _v4_node_mutation_changed_existing(
        before, after, operation=V4_NODE_MUTATION_RESULT_ACCEPT
    )
    old_node = before[identifier]
    new_node = after[identifier]
    _v4_node_mutation_same_except(
        old_node,
        new_node,
        allowed_fields=("state", "attempts"),
        code="V4_RESULT_ACCEPT_INVALID",
    )
    if (
        old_node.get("state")
        not in _v4_node_mutation_active_attempt_states
        or new_node.get("state") not in _v4_node_mutation_result_states
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_INVALID",
            "result acceptance requires one active current attempt",
            details={
                "node_instance_id": identifier,
                "before": old_node.get("state"),
                "after": new_node.get("state"),
            },
        )
    old_attempts = old_node.get("attempts")
    new_attempts = new_node.get("attempts")
    if (
        not isinstance(old_attempts, (list, tuple))
        or not isinstance(new_attempts, (list, tuple))
        or not old_attempts
        or len(old_attempts) != len(new_attempts)
        or list(old_attempts[:-1]) != list(new_attempts[:-1])
    ):
        raise _v4_node_mutation_error(
            "V4_ATTEMPT_HISTORY_REWRITE",
            "result acceptance must preserve every prior attempt",
            details={"node_instance_id": identifier},
        )
    old_attempt = old_attempts[-1]
    new_attempt = new_attempts[-1]
    if not isinstance(old_attempt, Mapping) or not isinstance(
        new_attempt, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_INVALID",
            "current result attempt must be an object",
        )
    _v4_node_mutation_same_except(
        old_attempt,
        new_attempt,
        allowed_fields=("state", "result_refs"),
        code="V4_ATTEMPT_HISTORY_REWRITE",
    )
    if (
        old_attempt.get("state") != old_node.get("state")
        or new_attempt.get("state") != new_node.get("state")
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_INVALID",
            "node and current attempt lifecycle must advance together",
            details={"node_instance_id": identifier},
        )
    old_refs = old_attempt.get("result_refs")
    new_refs = new_attempt.get("result_refs")
    if not isinstance(old_refs, (list, tuple)) or not isinstance(
        new_refs, (list, tuple)
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_ACCEPT_INVALID",
            "result acceptance requires ordered result references",
        )
    old_by_id = {
        item.get("result_id"): item
        for item in old_refs
        if isinstance(item, Mapping)
    }
    new_by_id = {
        item.get("result_id"): item
        for item in new_refs
        if isinstance(item, Mapping)
    }
    added_ids = sorted(
        set(new_by_id) - set(old_by_id),
        key=lambda value: _v4_node_mutation_utf8(str(value)),
    )
    if (
        len(old_by_id) != len(old_refs)
        or len(new_by_id) != len(new_refs)
        or len(added_ids) != 1
        or set(old_by_id) - set(new_by_id)
        or any(new_by_id[key] != value for key, value in old_by_id.items())
    ):
        raise _v4_node_mutation_error(
            "V4_RESULT_REFERENCE_REWRITE",
            "result acceptance must preserve references and add exactly one",
            details={"node_instance_id": identifier},
        )
    new_result_id = added_ids[0]
    new_ref_index = next(
        index
        for index, value in enumerate(new_refs)
        if isinstance(value, Mapping)
        and value.get("result_id") == new_result_id
    )
    node_index = _v4_node_mutation_index(candidate_state, identifier)
    attempt_index = len(new_attempts) - 1
    pointers = (
        f"/node_instances/{node_index}/attempts/{attempt_index}/result_refs/{new_ref_index}",
        f"/node_instances/{node_index}/attempts/{attempt_index}/state",
        f"/node_instances/{node_index}/state",
    )
    return (identifier,), tuple(
        sorted(pointers, key=_v4_node_mutation_utf8)
    )


def _v4_node_mutation_validate_retry_ready(
    before: Mapping[str, Mapping[str, object]],
    after: Mapping[str, Mapping[str, object]],
    *,
    candidate_state: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identifier = _v4_node_mutation_changed_existing(
        before, after, operation=V4_NODE_MUTATION_RETRY_READY
    )
    old_node = before[identifier]
    new_node = after[identifier]
    _v4_node_mutation_same_except(
        old_node,
        new_node,
        allowed_fields=("state",),
        code="V4_RETRY_READY_INVALID",
    )
    attempts = old_node.get("attempts")
    if (
        old_node.get("state") not in {"FAILED", "BLOCKED"}
        or new_node.get("state") != "READY"
        or new_node.get("attempts") != attempts
        or not isinstance(attempts, (list, tuple))
        or not attempts
        or not isinstance(attempts[-1], Mapping)
        or attempts[-1].get("state") != old_node.get("state")
        or not attempts[-1].get("result_refs")
    ):
        raise _v4_node_mutation_error(
            "V4_RETRY_READY_INVALID",
            "retry readiness requires a preserved accepted failed or blocked attempt",
            details={"node_instance_id": identifier},
        )
    node_index = _v4_node_mutation_index(candidate_state, identifier)
    return (identifier,), (f"/node_instances/{node_index}/state",)


def _v4_node_mutation_binding_payload(
    authorization: "AuthorizedV4NodeMutation",
) -> dict[str, object]:
    return {
        "schema": authorization.schema,
        "authorization_id": authorization.authorization_id,
        "task_id": authorization.task_id,
        "expected_revision": authorization.expected_revision,
        "workflow_id": authorization.workflow_id,
        "workflow_version": authorization.workflow_version,
        "graph_sha256": authorization.graph_sha256,
        "bundle_sha256": authorization.bundle_sha256,
        "operation": authorization.operation,
        "event_id": authorization.event_id,
        "event_type": authorization.event_type,
        "event_payload_sha256": authorization.event_payload_sha256,
        "affected_node_instance_ids": list(
            authorization.affected_node_instance_ids
        ),
        "before_node_instances_sha256": (
            authorization.before_node_instances_sha256
        ),
        "after_node_instances_sha256": (
            authorization.after_node_instances_sha256
        ),
        "candidate_sha256": authorization.candidate_sha256,
        "allowed_pointers": list(authorization.allowed_pointers),
        "audit_facts": [
            {
                "fact_type": fact.fact_type,
                "payload": _workflow_transition_public(fact.payload),
            }
            for fact in authorization.audit_facts
        ],
    }


def _v4_node_mutation_authorization_tag(
    payload: Mapping[str, object],
) -> str:
    return hmac.new(
        _v4_node_mutation_authorization_key,
        _canonical_json_bytes(payload),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class SealedV4ManagerAuthorization:
    authorization: ManagerAuthorization
    seal: str = field(repr=False, compare=False)


@dataclass(frozen=True)
class SealedV4NodeManagerOperation:
    authorization: SealedV4ManagerAuthorization
    operation: str
    event_id: str
    event_type: str
    event_payload_sha256: str
    old_state_sha256: str
    candidate_state_sha256: str
    seal: str = field(repr=False, compare=False)

    def seal_payload(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.authorization.as_dict(),
            "authorization_seal": self.authorization.seal,
            "operation": self.operation,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_payload_sha256": self.event_payload_sha256,
            "old_state_sha256": self.old_state_sha256,
            "candidate_state_sha256": self.candidate_state_sha256,
        }


def seal_v4_manager_authorization(
    authorization: object,
) -> SealedV4ManagerAuthorization:
    if type(authorization) is not ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_REQUIRED",
            "formal node mutation requires one typed ManagerAuthorization",
        )
    payload = authorization.as_dict()
    return SealedV4ManagerAuthorization(
        authorization=authorization,
        seal=hmac.new(
            _v4_node_manager_authorization_key,
            b"manager-authorization\x00"
            + _canonical_json_bytes(payload),
            hashlib.sha256,
        ).hexdigest(),
    )


def validate_v4_manager_authorization_pre_effect(
    value: object,
    old_state: Mapping[str, object],
    candidate_orchestration: Mapping[str, object],
    *,
    action_id: str,
) -> SealedV4ManagerAuthorization:
    """Authenticate the exact nonce consumption before protected effects.

    This deliberately does not consume or persist the nonce.  The later
    formal operation still binds the completed candidate and event and is the
    only path that commits the verifier delta.
    """

    if type(value) is not SealedV4ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_REQUIRED",
            "protected formal work requires a sealed manager authorization",
        )
    sealed = value
    authorization = sealed.authorization
    if type(authorization) is not ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "sealed manager authorization has an invalid receipt type",
        )
    expected_seal = hmac.new(
        _v4_node_manager_authorization_key,
        b"manager-authorization\x00"
        + _canonical_json_bytes(authorization.as_dict()),
        hashlib.sha256,
    ).hexdigest()
    receipt_payload = {
        "schema": MANAGER_AUTHORIZATION_SCHEMA,
        "capability_id": authorization.capability_id,
        "task_id": authorization.task_id,
        "manager_session_id": authorization.manager_session_id,
        "action_id": authorization.action_id,
        "expected_revision": authorization.expected_revision,
        "request_fingerprint_sha256": (
            authorization.request_fingerprint_sha256
        ),
    }
    expected_authorization_id = (
        "manager-authorization:"
        + _authority_digest(
            _authority_authorization_domain,
            receipt_payload,
        )
    )
    if (
        not hmac.compare_digest(sealed.seal, expected_seal)
        or authorization.authorization_id
        != expected_authorization_id
        or authorization.task_id != old_state.get("task_id")
        or authorization.expected_revision
        != old_state.get("revision")
        or authorization.action_id != action_id
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_STALE",
            "sealed manager authorization does not bind the locked action and revision",
        )
    old_orchestration = old_state.get("orchestration")
    if not isinstance(old_orchestration, Mapping):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "protected formal work requires orchestration ledgers",
        )
    _v4_node_mutation_validate_manager_nonce(
        old_orchestration,
        candidate_orchestration,
        required=True,
    )
    old_capabilities = old_orchestration.get(
        "manager_capabilities"
    )
    new_capabilities = candidate_orchestration.get(
        "manager_capabilities"
    )
    if not isinstance(old_capabilities, Mapping) or not isinstance(
        new_capabilities, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "manager capability ledger is invalid",
        )
    modified = [
        capability_id
        for capability_id in sorted(
            old_capabilities, key=_v4_node_mutation_utf8
        )
        if old_capabilities[capability_id]
        != new_capabilities.get(capability_id)
    ]
    if (
        modified != [authorization.capability_id]
        or new_capabilities.get(authorization.capability_id)
        != authorization.verifier_state.as_persistent_dict()
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "protected work did not consume the exact sealed manager verifier",
        )
    return sealed


def _v4_node_manager_operation(
    authorization: object,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    *,
    operation: str,
    event_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> SealedV4NodeManagerOperation:
    if type(authorization) is not SealedV4ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_REQUIRED",
            "formal node mutation requires a package-sealed ManagerAuthorization",
        )
    values = {
        "authorization": authorization,
        "operation": operation,
        "event_id": event_id,
        "event_type": event_type,
        "event_payload_sha256": _sha256_contract(payload),
        "old_state_sha256": _sha256_contract(old_state),
        "candidate_state_sha256": _sha256_contract(candidate_state),
    }
    provisional = SealedV4NodeManagerOperation(
        **values, seal=""
    )
    return SealedV4NodeManagerOperation(
        **values,
        seal=hmac.new(
            _v4_node_manager_authorization_key,
            b"formal-node-operation\x00"
            + _canonical_json_bytes(provisional.seal_payload()),
            hashlib.sha256,
        ).hexdigest(),
    )


@dataclass(frozen=True)
class AuthorizedV4NodeMutation:
    """Process-local, immutable proof for one exact node-state candidate."""

    schema: str
    authorization_id: str
    task_id: str
    expected_revision: int
    workflow_id: str
    workflow_version: int
    graph_sha256: str
    bundle_sha256: str
    operation: str
    event_id: str
    event_type: str
    event_payload_sha256: str
    affected_node_instance_ids: tuple[str, ...]
    before_node_instances_sha256: str
    after_node_instances_sha256: str
    candidate_sha256: str
    allowed_pointers: tuple[str, ...]
    audit_facts: tuple[AuditFact, ...]
    _authorization_tag: str = field(repr=False, compare=False)


def _v4_node_mutation_validate_state_pair(
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
) -> tuple[object, dict[str, Mapping[str, object]], dict[str, Mapping[str, object]]]:
    if (
        old_state.get("schema_version") != V4_TASK_SCHEMA_VERSION
        or candidate_state.get("schema_version")
        != V4_TASK_SCHEMA_VERSION
    ):
        raise _v4_node_mutation_error(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "node mutation service requires schema-v4 task state",
        )
    if old_state.get("task_id") != candidate_state.get("task_id"):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_TASK_MISMATCH",
            "node mutation candidate changed task identity",
        )
    if old_state.get("revision") != candidate_state.get("revision"):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_REVISION_STALE",
            "node mutation candidate must bind the current revision",
            details={
                "expected_revision": old_state.get("revision"),
                "candidate_revision": candidate_state.get("revision"),
            },
        )
    if old_state.get("status") != candidate_state.get("status"):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_STATUS_CHANGE",
            "node mutation service cannot move task lifecycle",
        )
    if old_state.get("workflow_ref") != candidate_state.get(
        "workflow_ref"
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_BUNDLE_MISMATCH",
            "node mutation candidate changed its pinned workflow identity",
        )
    try:
        validate_v4_task_state(old_state)
        validate_v4_task_state(candidate_state)
        old_bundle = _workflow_transition_bundle(old_state)
        new_bundle = _workflow_transition_bundle(candidate_state)
    except (WorkflowCatalogError, WorkflowStateError) as exc:
        raise _v4_node_mutation_error(
            getattr(exc, "code", "WORKFLOW_RESOLUTION_FAILED"),
            getattr(
                exc,
                "message",
                "schema-v4 node mutation could not resolve its bundle",
            ),
            details=getattr(exc, "details", {}),
        ) from exc
    if (
        getattr(old_bundle, "bundle_sha256", None)
        != getattr(new_bundle, "bundle_sha256", None)
        or getattr(old_bundle, "graph_sha256", None)
        != getattr(new_bundle, "graph_sha256", None)
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_BUNDLE_MISMATCH",
            "node mutation did not resolve one exact pinned bundle",
        )
    differences = json_pointer_diff(old_state, candidate_state)
    unexpected = [
        pointer
        for pointer in differences
        if pointer != "/node_instances"
        and not (
            pointer == "/orchestration"
            or pointer.startswith("/orchestration/")
        )
    ]
    if unexpected:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_OUT_OF_SCOPE",
            "node mutation candidate changed non-orchestration task fields",
            details={"unexpected_paths": unexpected},
        )
    return (
        old_bundle,
        _v4_node_mutation_node_map(old_state),
        _v4_node_mutation_node_map(candidate_state),
    )


def evaluate_v4_node_mutation(
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    *,
    operation: str,
    event_id: str,
    event_type: str,
    payload: Mapping[str, object] | None = None,
) -> AuthorizedV4NodeMutation:
    """Validate and bind one package-owned node lifecycle operation."""

    if operation not in V4_NODE_MUTATION_OPERATIONS:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_OPERATION_UNSUPPORTED",
            "node mutation operation is outside the package-owned closed set",
            details={
                "operation": operation,
                "supported": sorted(V4_NODE_MUTATION_OPERATIONS),
            },
        )
    if not isinstance(event_id, str) or not event_id:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_EVENT_INVALID",
            "node mutation authorization requires a preallocated event ID",
        )
    expected_event = V4_NODE_MUTATION_EVENT_TYPES[operation]
    if event_type != expected_event:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_EVENT_MISMATCH",
            "node mutation event does not match its operation policy",
            details={
                "operation": operation,
                "expected_event_type": expected_event,
                "event_type": event_type,
            },
        )
    event_payload = dict(payload or {})
    bundle, before, after = _v4_node_mutation_validate_state_pair(
        old_state, candidate_state
    )
    if operation == V4_NODE_MUTATION_MAP_EXPAND:
        affected, node_pointers = (
            _v4_node_mutation_validate_map_expand(
                before,
                after,
                bundle=bundle,
                candidate_state=candidate_state,
            )
        )
    elif operation == V4_NODE_MUTATION_MAP_INVALIDATE:
        affected, node_pointers = (
            _v4_node_mutation_validate_map_invalidate(
                before,
                after,
                old_state=old_state,
                candidate_state=candidate_state,
                event_payload=event_payload,
            )
        )
    elif operation == V4_NODE_MUTATION_FRONTIER_READY:
        affected, node_pointers = (
            _v4_node_mutation_validate_frontier_ready(
                before,
                after,
                old_state=old_state,
                candidate_state=candidate_state,
                event_payload=event_payload,
            )
        )
    elif operation == V4_NODE_MUTATION_ATTEMPT_START:
        affected, node_pointers = (
            _v4_node_mutation_validate_attempt_start(
                before, after, candidate_state=candidate_state
            )
        )
    elif operation == V4_NODE_MUTATION_ATTEMPT_ABANDON:
        affected, node_pointers = (
            _v4_node_mutation_validate_attempt_abandon(
                before,
                after,
                old_state=old_state,
                candidate_state=candidate_state,
                event_id=event_id,
                event_payload=event_payload,
            )
        )
    elif operation == V4_NODE_MUTATION_RESULT_ACCEPT:
        affected, node_pointers = (
            _v4_node_mutation_validate_result_accept(
                before, after, candidate_state=candidate_state
            )
        )
    else:
        affected, node_pointers = (
            _v4_node_mutation_validate_retry_ready(
                before, after, candidate_state=candidate_state
            )
        )
    orchestration_pointers = (
        _v4_node_mutation_orchestration_pointers(
            old_state,
            candidate_state,
            operation=operation,
            affected=affected,
            before_nodes=before,
            after_nodes=after,
            expected_revision=int(old_state.get("revision", -1)),
            event_id=event_id,
            event_payload=event_payload,
        )
    )
    allowed_pointers = tuple(
        sorted(
            {*node_pointers, *orchestration_pointers},
            key=_v4_node_mutation_utf8,
        )
    )
    workflow_ref = old_state.get("workflow_ref")
    assert isinstance(workflow_ref, Mapping)
    before_sha256 = _sha256_contract(
        old_state.get("node_instances")
    )
    after_sha256 = _sha256_contract(
        candidate_state.get("node_instances")
    )
    candidate_sha256 = _sha256_contract(candidate_state)
    event_payload_sha256 = _sha256_contract(
        {"type": event_type, "payload": event_payload}
    )
    authorization_core = {
        "schema": _v4_node_mutation_contract,
        "task_id": old_state.get("task_id"),
        "expected_revision": old_state.get("revision"),
        "workflow_id": workflow_ref.get("id"),
        "workflow_version": workflow_ref.get("version"),
        "graph_sha256": workflow_ref.get("graph_sha256"),
        "bundle_sha256": workflow_ref.get("bundle_sha256"),
        "operation": operation,
        "event_id": event_id,
        "event_type": event_type,
        "event_payload_sha256": event_payload_sha256,
        "affected_node_instance_ids": list(affected),
        "before_node_instances_sha256": before_sha256,
        "after_node_instances_sha256": after_sha256,
        "candidate_sha256": candidate_sha256,
        "allowed_pointers": list(allowed_pointers),
    }
    authorization_id = (
        "v4-node-mutation-" + _sha256_contract(authorization_core)
    )
    audit_facts = (
        AuditFact(
            "v4-node-mutation-authorized",
            {
                "authorization_id": authorization_id,
                "operation": operation,
                "affected_node_instance_ids": list(affected),
                "allowed_pointers": list(allowed_pointers),
                "candidate_sha256": candidate_sha256,
            },
        ),
        AuditFact(
            "v4-node-lifecycle-validated",
            {
                "authorization_id": authorization_id,
                "before_node_instances_sha256": before_sha256,
                "after_node_instances_sha256": after_sha256,
                "bundle_sha256": workflow_ref.get("bundle_sha256"),
            },
        ),
    )
    provisional = AuthorizedV4NodeMutation(
        schema=_v4_node_mutation_contract,
        authorization_id=authorization_id,
        task_id=str(old_state.get("task_id")),
        expected_revision=int(old_state.get("revision", -1)),
        workflow_id=str(workflow_ref.get("id")),
        workflow_version=int(workflow_ref.get("version", -1)),
        graph_sha256=str(workflow_ref.get("graph_sha256")),
        bundle_sha256=str(workflow_ref.get("bundle_sha256")),
        operation=operation,
        event_id=event_id,
        event_type=event_type,
        event_payload_sha256=event_payload_sha256,
        affected_node_instance_ids=affected,
        before_node_instances_sha256=before_sha256,
        after_node_instances_sha256=after_sha256,
        candidate_sha256=candidate_sha256,
        allowed_pointers=allowed_pointers,
        audit_facts=audit_facts,
        _authorization_tag="",
    )
    return AuthorizedV4NodeMutation(
        **{
            **provisional.__dict__,
            "_authorization_tag": _v4_node_mutation_authorization_tag(
                _v4_node_mutation_binding_payload(provisional)
            ),
        }
    )


def validate_v4_node_mutation_authorization(
    authorization: object,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    *,
    operation: str,
    event_id: str,
    event_type: str,
    payload: Mapping[str, object] | None = None,
) -> AuthorizedV4NodeMutation:
    """Reevaluate current truth and reject forged, stale, or altered proofs."""

    if type(authorization) is not AuthorizedV4NodeMutation:
        raise _v4_node_mutation_error(
            "V4_TRANSITION_SERVICE_REQUIRED",
            "schema-v4 node changes require typed controller authorization",
        )
    typed = authorization
    binding = _v4_node_mutation_binding_payload(typed)
    expected_tag = _v4_node_mutation_authorization_tag(binding)
    if not hmac.compare_digest(
        typed._authorization_tag, expected_tag
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_AUTHORIZATION_INVALID",
            "node mutation authorization seal is invalid",
            details={"authorization_id": typed.authorization_id},
        )
    if typed.operation != operation:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_OPERATION_MISMATCH",
            "node mutation authorization is scoped to another operation",
            details={
                "authorized": typed.operation,
                "requested": operation,
            },
        )
    if typed.event_id != event_id:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_EVENT_MISMATCH",
            "node mutation authorization is scoped to another event ID",
            details={
                "authorized": typed.event_id,
                "requested": event_id,
            },
        )
    if typed.event_type != event_type:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_EVENT_MISMATCH",
            "node mutation authorization is scoped to another event",
            details={
                "authorized": typed.event_type,
                "requested": event_type,
            },
        )
    if typed.expected_revision != old_state.get("revision"):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_REVISION_STALE",
            "node mutation authorization was evaluated at another revision",
            details={
                "authorized": typed.expected_revision,
                "current": old_state.get("revision"),
            },
        )
    if typed.candidate_sha256 != _sha256_contract(candidate_state):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_CANDIDATE_MISMATCH",
            "node mutation candidate changed after authorization",
            details={"authorization_id": typed.authorization_id},
        )
    current = evaluate_v4_node_mutation(
        old_state,
        candidate_state,
        operation=operation,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if _v4_node_mutation_binding_payload(typed) != (
        _v4_node_mutation_binding_payload(current)
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_AUTHORIZATION_STALE",
            "node mutation authorization no longer matches current truth",
            details={"authorization_id": typed.authorization_id},
        )
    return typed


def validate_v4_formal_manager_operation(
    value: object,
    old_state: Mapping[str, object],
    candidate_state: Mapping[str, object],
    *,
    event_type: str,
    event_payload: Mapping[str, object],
) -> tuple[str, dict[str, object]]:
    if type(value) is not SealedV4NodeManagerOperation:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_REQUIRED",
            "formal node mutation requires one sealed manager operation",
        )
    operation = value
    expected_operation_seal = hmac.new(
        _v4_node_manager_authorization_key,
        b"formal-node-operation\x00"
        + _canonical_json_bytes(operation.seal_payload()),
        hashlib.sha256,
    ).hexdigest()
    sealed = operation.authorization
    if type(sealed) is not SealedV4ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "formal node manager authorization has an invalid type",
        )
    authorization = sealed.authorization
    if type(authorization) is not ManagerAuthorization:
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "formal node manager authorization has an invalid receipt type",
        )
    expected_authorization_seal = hmac.new(
        _v4_node_manager_authorization_key,
        b"manager-authorization\x00"
        + _canonical_json_bytes(authorization.as_dict()),
        hashlib.sha256,
    ).hexdigest()
    expected_action = V4_NODE_MUTATION_MANAGER_ACTIONS.get(
        operation.operation
    )
    receipt_payload = {
        "schema": MANAGER_AUTHORIZATION_SCHEMA,
        "capability_id": authorization.capability_id,
        "task_id": authorization.task_id,
        "manager_session_id": authorization.manager_session_id,
        "action_id": authorization.action_id,
        "expected_revision": authorization.expected_revision,
        "request_fingerprint_sha256": (
            authorization.request_fingerprint_sha256
        ),
    }
    expected_authorization_id = (
        "manager-authorization:"
        + _authority_digest(
            _authority_authorization_domain,
            receipt_payload,
        )
    )
    if (
        not hmac.compare_digest(
            operation.seal, expected_operation_seal
        )
        or not hmac.compare_digest(
            sealed.seal, expected_authorization_seal
        )
        or operation.event_type != event_type
        or operation.event_payload_sha256
        != _sha256_contract(event_payload)
        or operation.old_state_sha256
        != _sha256_contract(old_state)
        or operation.candidate_state_sha256
        != _sha256_contract(candidate_state)
        or authorization.task_id != old_state.get("task_id")
        or authorization.expected_revision
        != old_state.get("revision")
        or authorization.action_id != expected_action
        or authorization.authorization_id
        != expected_authorization_id
        or event_payload.get("manager_authorization_id")
        != authorization.authorization_id
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_STALE",
            "sealed manager authorization does not bind the exact action, revision, candidate, and event",
        )
    old_orchestration = old_state.get("orchestration")
    new_orchestration = candidate_state.get("orchestration")
    if not isinstance(old_orchestration, Mapping) or not isinstance(
        new_orchestration, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "formal manager authorization requires orchestration ledgers",
        )
    _v4_node_mutation_validate_manager_nonce(
        old_orchestration,
        new_orchestration,
        required=True,
    )
    old_capabilities = old_orchestration.get(
        "manager_capabilities"
    )
    new_capabilities = new_orchestration.get(
        "manager_capabilities"
    )
    if not isinstance(old_capabilities, Mapping) or not isinstance(
        new_capabilities, Mapping
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "manager capability ledger is invalid",
        )
    modified = [
        capability_id
        for capability_id in sorted(
            old_capabilities, key=_v4_node_mutation_utf8
        )
        if old_capabilities[capability_id]
        != new_capabilities.get(capability_id)
    ]
    if (
        modified != [authorization.capability_id]
        or new_capabilities.get(authorization.capability_id)
        != authorization.verifier_state.as_persistent_dict()
    ):
        raise _v4_node_mutation_error(
            "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
            "candidate did not consume the exact sealed manager verifier",
        )
    return (
        "manager_authorization_consumed",
        {
            "schema": "dev-flow-manager-consumption/v1",
            "authorization_id": authorization.authorization_id,
            "capability_id": authorization.capability_id,
            "manager_session_id": authorization.manager_session_id,
            "action_id": authorization.action_id,
            "expected_revision": authorization.expected_revision,
            "request_fingerprint_sha256": (
                authorization.request_fingerprint_sha256
            ),
            "operation": operation.operation,
            "event_id": operation.event_id,
            "event_type": operation.event_type,
            "candidate_sha256": operation.candidate_state_sha256,
        },
    )


def workflow_v4_node_mutation_audit_events(
    authorization: AuthorizedV4NodeMutation,
) -> tuple[tuple[str, dict[str, object]], ...]:
    linked = {
        "authorization_id": authorization.authorization_id,
        "operation": authorization.operation,
    }
    return tuple(
        (
            "workflow_audit_fact",
            {
                **linked,
                "fact_type": fact.fact_type,
                "fact": copy.deepcopy(
                    _workflow_transition_public(fact.payload)
                ),
            },
        )
        for fact in authorization.audit_facts
    )


def commit_v4_node_event(
    old_state: dict[str, object],
    candidate_state: dict[str, object],
    task_dir: "Path",
    event_type: str,
    payload: dict[str, object] | None = None,
    *,
    operation: str,
    manager_authorization: SealedV4ManagerAuthorization,
    finalize_event_binding: Callable[
        [dict[str, object], str], None
    ]
    | None = None,
) -> dict[str, object]:
    """Commit one node mutation only after fresh formal authorization."""

    try:
        task_lock, workspace_lock, _ownership_lock = (
            workflow_runtime_services().locks.workflow_transition_locks(
                old_state
            )
        )
        if not task_lock or not workspace_lock:
            raise _v4_node_mutation_error(
                "V4_NODE_MUTATION_LOCK_REQUIRED",
                "node mutation commit requires task and workspace locks",
                details={
                    "task_lock_held": task_lock,
                    "workspace_lock_held": workspace_lock,
                },
            )
        state_path = task_dir / "state.json"
        persisted = _read_task_state_structural_snapshot(state_path)
        if _sha256_contract(persisted) != _sha256_contract(old_state):
            raise _v4_node_mutation_error(
                "V4_NODE_MUTATION_STALE_STATE",
                "node mutation old state is not the committed snapshot",
                details={
                    "task_id": old_state.get("task_id"),
                    "expected_revision": old_state.get("revision"),
                    "persisted_revision": persisted.get("revision"),
                },
            )
        primary_event_id = str(uuid.uuid4())
        if finalize_event_binding is not None:
            finalize_event_binding(
                candidate_state, primary_event_id
            )
        event_payload = dict(payload or {})
        formal_manager_operation = _v4_node_manager_operation(
            manager_authorization,
            old_state,
            candidate_state,
            operation=operation,
            event_id=primary_event_id,
            event_type=event_type,
            payload=event_payload,
        )
        manager_event = manager_process_commit_gate_v1(
            old_state,
            candidate_state,
            event_type,
            formal_operation=formal_manager_operation,
            formal_event_payload=event_payload,
        )
        if not isinstance(manager_event, tuple):
            raise _v4_node_mutation_error(
                "V4_NODE_MUTATION_MANAGER_AUTHORIZATION_INVALID",
                "formal manager membrane produced no consumption event",
            )
        authorization = evaluate_v4_node_mutation(
            old_state,
            candidate_state,
            operation=operation,
            event_id=primary_event_id,
            event_type=event_type,
            payload=event_payload,
        )
        validate_v4_node_mutation_authorization(
            authorization,
            old_state,
            candidate_state,
            operation=operation,
            event_id=primary_event_id,
            event_type=event_type,
            payload=event_payload,
        )
        linked_events = list(
            workflow_v4_node_mutation_audit_events(authorization)
        )
        linked_events.insert(0, manager_event)
        event_ids = [
            primary_event_id,
            *(
                str(uuid.uuid4())
                for _item in linked_events
            ),
        ]
        return _persist_state_transaction(
            old_state,
            candidate_state,
            task_dir,
            event_type,
            event_payload,
            additional_events=linked_events,
            _event_ids=event_ids,
            _transaction_id=(
                str(uuid.uuid4()) if linked_events else None
            ),
        )
    except TransitionEngineError as exc:
        raise FlowError(
            exc.code,
            exc.message,
            details=exc.details,
        ) from exc
