"""Pure current-node eligibility and bounded mutation planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from types import MappingProxyType
from typing import Callable, Mapping, Optional

from .model import (
    DevFlowError,
    MutationPlan,
    RepositoryRecord,
    TaskState,
    canonical_json_bytes,
)
from .workflow import (
    NodeContract,
    WorkflowDefinition,
    current_contract,
)


NODE_OUTPUT_INVALID = "NODE_OUTPUT_INVALID"


def plan_current_action(
    state: TaskState,
    definition: WorkflowDefinition,
    action_id: str,
    expected_revision: int,
) -> tuple:
    """Plan the exact action for the current node at the given revision.

    The revision is read from the controller's load, never from the agent
    protocol; the store revalidates it under the task lock before any
    write. ``apply`` re-plans under the lock and rejects drift, so a
    raced or stale call fails before the state is touched.
    """
    if state.revision != expected_revision:
        raise DevFlowError(
            "REVISION_CONFLICT",
            "task revision is stale",
            details={
                "task_id": state.task_id,
                "expected_revision": expected_revision,
                "actual_revision": state.revision,
            },
        )
    contract = current_contract(state, definition)
    if contract.action_id != action_id:
        cancel = definition.cancel_contract
        if cancel is not None and cancel.action_id == action_id:
            contract = cancel
        else:
            raise DevFlowError(
                "ACTION_NOT_AVAILABLE",
                "action is not available at the current node",
                details={
                    "action_id": action_id,
                    "current_node": state.current_node,
                    "expected_action_id": contract.action_id,
                },
            )
    plan = MutationPlan(
        action_id=contract.action_id,
        task_id=state.task_id,
        expected_revision=expected_revision,
        source_node=contract.node_id,
        target_node=contract.target_node,
        effect_kind=contract.effect_port,
        allowed_writes=contract.allowed_state_writes,
    )
    return contract, plan


def validate_action_payload(
    contract: NodeContract,
    payload: Optional[Mapping[str, object]],
) -> Mapping[str, object]:
    value = dict(payload or {})
    missing = [
        field
        for field in contract.payload_types
        if field not in value
    ]
    if missing:
        raise DevFlowError(
            NODE_OUTPUT_INVALID,
            "node output is incomplete",
            details={"missing_fields": missing},
        )
    unknown = sorted(set(value) - set(contract.payload_types))
    if unknown:
        raise DevFlowError(
            NODE_OUTPUT_INVALID,
            "node output contains undeclared fields",
            details={"unknown_fields": unknown},
        )
    if len(canonical_json_bytes(value)) > 16 * 1024:
        raise DevFlowError(
            NODE_OUTPUT_INVALID,
            "node output exceeds the bounded payload budget",
        )
    for field, expected_type in contract.payload_types.items():
        if field not in value:
            continue
        item = value[field]
        valid = (
            expected_type == "string"
            and isinstance(item, str)
            and 0 < len(item.encode("utf-8")) <= 8192
        ) or (
            expected_type == "boolean"
            and isinstance(item, bool)
        ) or (
            expected_type == "integer"
            and isinstance(item, int)
            and not isinstance(item, bool)
        ) or (
            expected_type == "object"
            and isinstance(item, Mapping)
        ) or (
            expected_type == "sha256"
            and isinstance(item, str)
            and re.fullmatch(r"[0-9a-f]{64}", item) is not None
        )
        if not valid:
            raise DevFlowError(
                NODE_OUTPUT_INVALID,
                "node output field has the wrong type or size",
                details={"field": field, "expected_type": expected_type},
            )
    return MappingProxyType(value)


NodeHandler = Callable[
    [
        TaskState,
        NodeContract,
        MutationPlan,
        Mapping[str, object],
        Optional[Mapping[str, object]],
        str,
    ],
    TaskState,
]


@dataclass(frozen=True)
class NodeFamily:
    """Direct pure handler and declared external effect port for one node family."""

    handler: NodeHandler
    effect_port: str


def _record(
    contract: NodeContract,
    output: Mapping[str, object],
    timestamp: str,
) -> dict:
    return {
        "schema": "dev-flow-v5-node-output/v1",
        "action_id": contract.action_id,
        "node_id": contract.node_id,
        "recorded_at": timestamp,
        "payload": dict(output),
    }


def _advance(
    state: TaskState,
    contract: NodeContract,
    timestamp: str,
    **changes: object,
) -> TaskState:
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        status=contract.target_status,
        current_node=contract.target_node,
        **changes,
    )


def _record_evidence(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del plan, effect_result
    return _advance(
        state,
        contract,
        timestamp,
        evidence=(*state.evidence, _record(contract, output, timestamp)),
    )


def _record_test(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    if output.get("passed") is not True:
        raise DevFlowError(
            "TEST_NOT_PASSING",
            "current test evidence is not passing",
        )
    return _record_evidence(state, contract, plan, output, None, timestamp)


def apply_preflight(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del plan, output
    if not isinstance(effect_result, Mapping):
        raise DevFlowError(
            "PREFLIGHT_EVIDENCE_INVALID",
            "preflight requires Git inspection evidence",
        )
    expected_ids = {
        repository.repository_id
        for repository in state.repositories
    }
    if set(effect_result) != expected_ids:
        raise DevFlowError(
            "PREFLIGHT_EVIDENCE_INVALID",
            "preflight evidence does not cover the exact repository set",
        )
    repositories = tuple(
        RepositoryRecord(
            repository.repository_id,
            repository.path,
            effect_result[repository.repository_id],
        )
        for repository in state.repositories
    )
    return _advance(state, contract, timestamp, repositories=repositories)


NODE_FAMILY_CATALOG = MappingProxyType(
    {
        "preflight": NodeFamily(apply_preflight, "git.inspect-repository"),
        "evidence.record": NodeFamily(_record_evidence, "none"),
        "test.record": NodeFamily(_record_test, "none"),
    }
)


def apply_current_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    plan: MutationPlan,
    *,
    payload: Optional[Mapping[str, object]],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    current_contract_value, current_plan = plan_current_action(
        state,
        definition,
        plan.action_id,
        plan.expected_revision,
    )
    if current_contract_value != contract or current_plan != plan:
        raise DevFlowError(
            "PLAN_BINDING_MISMATCH",
            "node action plan is no longer current",
        )
    output = validate_action_payload(contract, payload)
    family = NODE_FAMILY_CATALOG.get(contract.handler_id)
    if family is None or family.effect_port != contract.effect_port:
        raise DevFlowError(
            "NODE_BINDING_INVALID",
            "node handler or effect port is not installed",
            details={
                "handler_id": contract.handler_id,
                "effect_port": contract.effect_port,
            },
        )
    return family.handler(
        state,
        contract,
        plan,
        output,
        effect_result,
        timestamp,
    )


def _state_invalid(reason: str, **details: object) -> DevFlowError:
    return DevFlowError(
        "STATE_INVALID",
        "task state is inconsistent with its workflow",
        details={"reason": reason, **details},
    )


def _write_invalid(reason: str, **details: object) -> DevFlowError:
    return DevFlowError(
        "STATE_WRITE_INVALID",
        "task mutation produced an inconsistent state",
        details={"reason": reason, **details},
    )


def _validate_state_shape(
    state: TaskState,
    definition: WorkflowDefinition,
) -> None:
    try:
        reconstructed = TaskState.from_dict(
            state.as_dict(),
            definition=definition,
        )
    except DevFlowError as exc:
        raise _state_invalid(
            "state_shape_invalid",
            cause=exc.code,
            cause_details=exc.details,
        ) from exc
    except (AttributeError, TypeError, ValueError) as exc:
        raise _state_invalid(
            "state_shape_invalid",
            cause=type(exc).__name__,
        ) from exc
    if reconstructed != state:
        raise _state_invalid("state_shape_invalid")
    if state.current_node not in definition.nodes:
        raise _state_invalid(
            "current_node_unknown",
            current_node=state.current_node,
        )
    if len(state.repositories) != 1:
        raise _state_invalid(
            "repository_set_invalid",
            repository_count=len(state.repositories),
        )


def _replay_evidence_record(
    record: object,
    index: int,
    cursor_node: str,
    definition: WorkflowDefinition,
) -> tuple:
    if not isinstance(record, Mapping):
        raise _state_invalid("evidence_record_invalid", evidence_index=index)
    expected_fields = {
        "schema",
        "action_id",
        "node_id",
        "recorded_at",
        "payload",
    }
    if set(record) != expected_fields:
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            fields=sorted(str(field) for field in record),
        )
    if record.get("schema") != "dev-flow-v5-node-output/v1":
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            field="schema",
        )
    recorded_at = record.get("recorded_at")
    payload = record.get("payload")
    if not isinstance(recorded_at, str) or not recorded_at:
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            field="recorded_at",
        )
    if not isinstance(payload, Mapping):
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            field="payload",
        )
    if cursor_node in definition.terminal_nodes:
        raise _state_invalid(
            "evidence_action_mismatch",
            evidence_index=index,
            current_node=cursor_node,
        )

    current = definition.nodes[cursor_node]
    contract = current
    action_id = record.get("action_id")
    if current.handler_id == "preflight" and action_id == current.action_id:
        raise _state_invalid(
            "preflight_state_invalid",
            evidence_index=index,
        )
    if action_id != current.action_id:
        cancel = definition.cancel_contract
        if cancel is None or action_id != cancel.action_id:
            raise _state_invalid(
                "evidence_action_mismatch",
                evidence_index=index,
                action_id=action_id,
                current_node=cursor_node,
                expected_action_id=current.action_id,
            )
        contract = cancel
    if record.get("node_id") != contract.node_id:
        raise _state_invalid(
            "evidence_action_mismatch",
            evidence_index=index,
            node_id=record.get("node_id"),
            expected_node_id=contract.node_id,
        )
    try:
        validated = validate_action_payload(contract, payload)
    except DevFlowError as exc:
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            cause=exc.code,
            cause_details=exc.details,
        ) from exc
    if contract.handler_id == "test.record" and validated.get("passed") is not True:
        raise _state_invalid(
            "evidence_record_invalid",
            evidence_index=index,
            cause="TEST_NOT_PASSING",
        )
    return contract.target_node, contract.target_status, recorded_at


def validate_persisted_state(
    state: TaskState,
    definition: WorkflowDefinition,
) -> None:
    """Fail closed unless a state can be replayed from its workflow entry."""
    _validate_state_shape(state, definition)

    cursor_node = definition.entry_node
    cursor_status = "INTAKE"
    cursor_revision = 0
    last_evidence_timestamp = None

    repository = state.repositories[0]
    if repository.preflight is not None:
        entry_contract = definition.nodes[definition.entry_node]
        if entry_contract.handler_id != "preflight":
            raise _state_invalid("preflight_state_invalid")
        cursor_node = entry_contract.target_node
        cursor_status = entry_contract.target_status
        cursor_revision += 1

    for index, record in enumerate(state.evidence):
        cursor_node, cursor_status, recorded_at = _replay_evidence_record(
            record,
            index,
            cursor_node,
            definition,
        )
        cursor_revision += 1
        last_evidence_timestamp = recorded_at

    if state.revision != cursor_revision:
        raise _state_invalid(
            "revision_path_mismatch",
            expected_revision=cursor_revision,
            stored_revision=state.revision,
        )
    if state.current_node != cursor_node:
        raise _state_invalid(
            "current_node_path_mismatch",
            expected_node=cursor_node,
            stored_node=state.current_node,
        )
    if state.status != cursor_status:
        raise _state_invalid(
            "status_path_mismatch",
            expected_status=cursor_status,
            stored_status=state.status,
        )
    if state.revision == 0:
        if repository.preflight is not None or state.evidence:
            raise _state_invalid("preflight_state_invalid")
        if state.created_at != state.updated_at:
            raise _state_invalid(
                "revision_path_mismatch",
                expected_updated_at=state.created_at,
                stored_updated_at=state.updated_at,
            )
    if last_evidence_timestamp is not None and state.updated_at != last_evidence_timestamp:
        raise _state_invalid(
            "evidence_record_invalid",
            expected_updated_at=last_evidence_timestamp,
            stored_updated_at=state.updated_at,
        )


def validate_state_transition(
    current: TaskState,
    candidate: TaskState,
    definition: WorkflowDefinition,
) -> None:
    """Validate one append-only, revision-gated state transition."""
    immutable_fields = (
        "task_id",
        "requirement",
        "created_at",
        "workflow_id",
        "workflow_version",
        "workflow_identity",
        "schema_version",
        "product_identity",
    )
    for field in immutable_fields:
        if getattr(candidate, field) != getattr(current, field):
            raise _write_invalid("immutable_field_changed", field=field)
    if candidate.revision != current.revision + 1:
        raise _write_invalid(
            "revision_path_mismatch",
            expected_revision=current.revision + 1,
            candidate_revision=candidate.revision,
        )
    current_repository_identity = tuple(
        (repository.repository_id, repository.path)
        for repository in current.repositories
    )
    candidate_repository_identity = tuple(
        (repository.repository_id, repository.path)
        for repository in candidate.repositories
    )
    if candidate_repository_identity != current_repository_identity:
        raise _write_invalid("immutable_field_changed", field="repositories")
    if len(current.repositories) != 1 or len(candidate.repositories) != 1:
        raise _write_invalid(
            "repository_set_invalid",
            repository_count=len(candidate.repositories),
        )

    preflight_transition = (
        not current.evidence
        and candidate.evidence == current.evidence
        and current.repositories[0].preflight is None
        and candidate.repositories[0].preflight is not None
    )
    evidence_transition = (
        candidate.repositories == current.repositories
        and len(candidate.evidence) == len(current.evidence) + 1
        and candidate.evidence[:-1] == current.evidence
    )
    if not preflight_transition and not evidence_transition:
        raise _write_invalid("transition_shape_invalid")
    try:
        validate_persisted_state(candidate, definition)
    except DevFlowError as exc:
        raise _write_invalid(
            exc.details.get("reason", "candidate_state_invalid"),
            cause=exc.code,
            cause_details=exc.details,
        ) from exc
