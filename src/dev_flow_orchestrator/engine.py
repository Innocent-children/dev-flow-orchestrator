"""Pure V6 ledger replay, action binding, assurance routing, and projections."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from .delivery import (
    artifact_by_record_id,
    artifact_freshness,
    assurance_waiver,
    contract_digest,
    contract_summary,
    coverage_view,
    effective_contract,
    generate_dossier,
    governing_resource_requests,
    make_action_binding,
    resolve_inputs,
    resource_requests,
    seal_artifact,
    seal_record,
    validate_action_binding,
    validate_artifact,
    validate_contract,
    validate_decision,
    validate_record_seal,
)
from .model import (
    DevFlowError,
    MutationPlan,
    TaskState,
    canonical_json_bytes,
    freeze_json,
    json_value,
)
from .product import AGENT_PROTOCOL_SCHEMA
from .snapshot import validate_snapshot
from .workflow import (
    ArtifactContract,
    InputContract,
    NodeContract,
    WorkflowDefinition,
)


NODE_OUTPUT_INVALID = "NODE_OUTPUT_INVALID"
MAX_NODE_OUTPUT_BYTES = 64 * 1024
RECORD_FIELDS = {
    "schema",
    "kind",
    "record_id",
    "digest",
    "task_revision",
    "timestamp",
    "producer",
    "payload",
    "contract",
    "transition",
    "snapshot",
    "artifact",
    "binding",
}
ARTIFACT_FIELDS = {
    "schema",
    "digest",
    "type",
    "contract_revision",
    "contract_digest",
    "producer",
    "workspace_role",
    "snapshot",
    "inputs",
    "resources",
    "body",
}


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def is_terminal_state(state: TaskState, definition: WorkflowDefinition) -> bool:
    return state.current_node in definition.terminal_nodes


def current_node_contract(
    state: TaskState, definition: WorkflowDefinition
) -> NodeContract:
    if is_terminal_state(state, definition):
        raise _error(
            "NO_ACTION_AVAILABLE",
            "current node has no workflow action",
            current_node=state.current_node,
            status=state.status,
        )
    contract = definition.nodes.get(state.current_node)
    if contract is None or not contract.action_id:
        raise _error(
            "NO_ACTION_AVAILABLE",
            "current node has no workflow action",
            current_node=state.current_node,
            status=state.status,
        )
    return contract


def plan_current_action(
    state: TaskState,
    definition: WorkflowDefinition,
    action_id: str,
    expected_revision: int,
) -> tuple:
    """Bind one declared action to the currently loaded task revision."""
    if state.revision != expected_revision:
        raise _error(
            "REVISION_CONFLICT",
            "task revision is stale",
            task_id=state.task_id,
            expected_revision=expected_revision,
            actual_revision=state.revision,
        )
    if is_terminal_state(state, definition):
        raise _error(
            "ACTION_NOT_AVAILABLE",
            "task is already finished",
            current_node=state.current_node,
            status=state.status,
        )
    contract = current_node_contract(state, definition)
    cancel = definition.cancel_contract
    is_cancel = cancel is not None and cancel.action_id == action_id
    if contract.action_id != action_id:
        if is_cancel:
            contract = cancel
        else:
            raise _error(
                "ACTION_NOT_AVAILABLE",
                "action is not available at the current node",
                action_id=action_id,
                current_node=state.current_node,
                expected_action_id=contract.action_id,
            )
    if state.revision == 0 and contract.handler_id != "preflight":
        raise _error(
            "PREFLIGHT_REQUIRED",
            "repository preflight must be the first task mutation",
        )
    return contract, MutationPlan(
        action_id=contract.action_id,
        task_id=state.task_id,
        expected_revision=expected_revision,
        source_node=state.current_node,
        target_node=contract.target_node or state.current_node,
        effect_kind=contract.effect_port,
        allowed_writes=contract.allowed_state_writes,
    )


def validate_action_payload(
    contract: NodeContract,
    payload: Optional[Mapping[str, object]],
) -> Mapping[str, object]:
    """Validate one exact, bounded JSON output against its node declaration."""
    if payload is None:
        value = {}
    elif not isinstance(payload, Mapping):
        raise _error(NODE_OUTPUT_INVALID, "node output must be an object")
    else:
        value = json_value(payload)
    if not isinstance(value, dict):
        raise _error(NODE_OUTPUT_INVALID, "node output must be an object")
    missing = sorted(set(contract.payload_types) - set(value))
    unknown = sorted(set(value) - set(contract.payload_types))
    if missing:
        raise _error(
            NODE_OUTPUT_INVALID,
            "node output is incomplete",
            missing_fields=missing,
        )
    if unknown:
        raise _error(
            NODE_OUTPUT_INVALID,
            "node output contains undeclared fields",
            unknown_fields=unknown,
        )
    try:
        encoded = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise _error(NODE_OUTPUT_INVALID, "node output is not strict JSON") from exc
    if len(encoded) > MAX_NODE_OUTPUT_BYTES:
        raise _error(NODE_OUTPUT_INVALID, "node output exceeds the payload budget")
    for field, expected_type in contract.payload_types.items():
        item = value[field]
        valid = (
            expected_type == "string"
            and isinstance(item, str)
            and bool(item.strip())
            and len(item.encode("utf-8")) <= 8192
        ) or (
            expected_type == "boolean" and isinstance(item, bool)
        ) or (
            expected_type == "integer"
            and isinstance(item, int)
            and not isinstance(item, bool)
        ) or (
            expected_type == "object" and isinstance(item, dict)
        ) or (
            expected_type == "sha256"
            and isinstance(item, str)
            and len(item) == 64
            and all(character in "0123456789abcdef" for character in item)
        )
        if not valid:
            raise _error(
                NODE_OUTPUT_INVALID,
                "node output field has the wrong type or size",
                field=field,
                expected_type=expected_type,
            )
    return freeze_json(value)


def _validated_snapshot(value: object) -> Mapping[str, object]:
    try:
        return freeze_json(validate_snapshot(value))
    except DevFlowError:
        raise
    except (TypeError, ValueError) as exc:
        raise _error("WORKSPACE_SNAPSHOT_INVALID", "workspace snapshot is invalid") from exc


def _current_contract(state: TaskState) -> Mapping[str, object]:
    return effective_contract(state.original_contract, state.records)


def assurance_attempts(
    records: Sequence[object], node_id: str, contract_value: Mapping[str, object]
) -> int:
    digest = contract_digest(contract_value)
    return sum(
        1
        for record in records
        if isinstance(record, Mapping)
        and isinstance(record.get("producer"), Mapping)
        and record["producer"].get("node_id") == node_id
        and isinstance(record.get("contract"), Mapping)
        and record["contract"].get("digest") == digest
        and record.get("kind") in ("verification", "review")
    )


def _action_attempt(
    records: Sequence[object], node_id: str, contract_value: Mapping[str, object]
) -> int:
    digest = contract_digest(contract_value)
    return 1 + sum(
        1
        for record in records
        if isinstance(record, Mapping)
        and isinstance(record.get("producer"), Mapping)
        and record["producer"].get("node_id") == node_id
        and isinstance(record.get("contract"), Mapping)
        and record["contract"].get("digest") == digest
    )


def _coverage_payload(
    output: Mapping[str, object], contract_value: Mapping[str, object]
) -> Mapping[str, str]:
    coverage = output.get("coverage")
    criterion_ids = tuple(
        item["id"] for item in contract_value["acceptance_criteria"]
    )
    if not isinstance(coverage, Mapping) or set(coverage) != set(criterion_ids):
        raise _error(
            NODE_OUTPUT_INVALID,
            "verification coverage must report every acceptance criterion",
            expected_criterion_ids=list(criterion_ids),
        )
    normalized = {}
    for criterion_id in criterion_ids:
        status = coverage.get(criterion_id)
        if status not in ("proven", "unverified"):
            raise _error(
                NODE_OUTPUT_INVALID,
                "verification coverage values must be proven or unverified",
                criterion_id=criterion_id,
            )
        normalized[criterion_id] = status
    return MappingProxyType(normalized)


def _assurance_success(
    contract: NodeContract,
    output: Mapping[str, object],
    contract_value: Mapping[str, object],
    records: Sequence[object],
) -> bool:
    if contract.handler_id == "test.record":
        if output.get("passed") is not True:
            raise _error("TEST_NOT_PASSING", "workflow-v1 test evidence is not passing")
        return True
    if contract.handler_id == "verification.record":
        coverage = _coverage_payload(output, contract_value)
        if output.get("passed") is not True:
            return False
        view = coverage_view(contract_value, records, {"coverage": coverage})
        if any(item["status"] not in ("proven", "waived") for item in view.values()):
            raise _error(
                NODE_OUTPUT_INVALID,
                "passing verification requires proven or waived current coverage",
            )
        return True
    if contract.handler_id == "review.record":
        outcome = output.get("outcome")
        assurance = output.get("assurance")
        if outcome not in ("approved", "changes-requested", "unavailable"):
            raise _error(NODE_OUTPUT_INVALID, "review outcome is invalid")
        if assurance not in ("independent", "self"):
            raise _error(NODE_OUTPUT_INVALID, "review assurance is invalid")
        if outcome == "approved" and assurance == "independent":
            return True
        return (
            outcome == "unavailable"
            and assurance_waiver(records, contract_value, contract.node_id) is not None
        )
    return True


def _transition_for_action(
    state: TaskState,
    contract: NodeContract,
    output: Mapping[str, object],
    contract_value: Mapping[str, object],
) -> Tuple[dict, int]:
    attempt = _action_attempt(state.records, contract.node_id, contract_value)
    route = "cancel" if contract is not None and contract.node_id == "cancel" else "success"
    target_node = contract.target_node
    target_status = contract.target_status
    if contract.handler_id in ("verification.record", "review.record", "test.record"):
        succeeded = _assurance_success(contract, output, contract_value, state.records)
        if not succeeded:
            if contract.rework is None:
                raise _error(
                    NODE_OUTPUT_INVALID,
                    "failed assurance has no declared rework route",
                )
            if attempt < contract.rework.max_attempts:
                route = "failure"
                target_node = contract.rework.failure_node
                target_status = contract.rework.failure_status
            else:
                route = "exhausted"
                target_node = contract.rework.exhausted_node
                target_status = contract.rework.exhausted_status
    if not isinstance(target_node, str) or not isinstance(target_status, str):
        raise _error("NODE_BINDING_INVALID", "node target is unavailable")
    return {
        "from": state.current_node,
        "to": target_node,
        "status": target_status,
        "route": route,
    }, attempt


def _effective_artifact_contract(
    contract: NodeContract, definition: WorkflowDefinition
) -> Optional[ArtifactContract]:
    if contract.artifact is not None:
        return contract.artifact
    if contract.node_id == "cancel":
        return None
    if contract.handler_id == "preflight":
        return ArtifactContract("repository-baseline", "produces-source", ())
    if definition.schema == "dev-flow-workflow/v1":
        if contract.handler_id == "test.record":
            return ArtifactContract("legacy-verification", "verifies-source", ())
        # Workflow-v1 had no workspace-role language and historically allowed
        # evidence actions to accompany source edits.  The adapter therefore
        # gives each such action a conservative source-successor boundary.
        return ArtifactContract(
            "legacy-evidence",
            "produces-source",
            (InputContract("*", "source-predecessor"),),
        )
    return None


def _producer(
    contract: NodeContract,
    attempt: int,
    output: Mapping[str, object],
) -> dict:
    driver = None
    if contract.driver is not None:
        driver = {
            "capability": json_value(contract.driver),
            "result": json_value(output.get("driver_result")),
        }
    return {
        "kind": "workflow-action",
        "action_id": contract.action_id,
        "node_id": contract.node_id,
        "attempt": attempt,
        "driver": driver,
    }


def _canonical_inputs(binding: Mapping[str, object]) -> list:
    inputs = binding.get("inputs")
    if not isinstance(inputs, (list, tuple)):
        raise _error("ACTION_BINDING_INVALID", "action inputs are invalid")
    result = []
    for item in inputs:
        if not isinstance(item, Mapping):
            raise _error("ACTION_BINDING_INVALID", "action input is invalid")
        expected = {
            "type",
            "edge",
            "record_id",
            "record_digest",
            "artifact_digest",
            "snapshot_digest",
            "summary",
        }
        if set(item) != expected:
            raise _error("ACTION_BINDING_INVALID", "action input fields are invalid")
        result.append(
            {
                "type": item.get("type"),
                "edge": item.get("edge"),
                "record_id": item.get("record_id"),
                "record_digest": item.get("record_digest"),
                "artifact_digest": item.get("artifact_digest"),
                "snapshot_digest": item.get("snapshot_digest"),
            }
        )
    return result


def _bound_resources(
    output: Mapping[str, object], snapshot: Mapping[str, object]
) -> list:
    requested = resource_requests(output)
    snapshot_items = snapshot.get("resources")
    if not isinstance(snapshot_items, (list, tuple)):
        snapshot_items = ()
    result = []
    for request in requested:
        match = next(
            (
                item
                for item in snapshot_items
                if isinstance(item, Mapping)
                and item.get("path") == request["path"]
                and item.get("role") == request["role"]
                and item.get("normalizer") == request["normalizer"]
            ),
            None,
        )
        if match is None:
            raise _error(
                "RESOURCE_BINDING_MISSING",
                "declared repository resource was not captured by the snapshot",
                path=request["path"],
            )
        result.append(json_value(match))
    return result


def _dossier_body(
    state: TaskState,
    contract: NodeContract,
    output: Mapping[str, object],
    snapshot: Mapping[str, object],
    contract_value: Mapping[str, object],
    inputs: Sequence[Mapping[str, object]],
) -> dict:
    artifacts = artifact_by_record_id(state.records)
    input_artifacts = [artifacts.get(item.get("record_id")) for item in inputs]
    if contract.finalize_outcome == "success":
        verification = next(
            (
                artifact
                for artifact in input_artifacts
                if isinstance(artifact, Mapping)
                and artifact.get("type") == "verification-result"
            ),
            None,
        )
        if not isinstance(verification, Mapping):
            raise _error("DELIVERY_NOT_READY", "successful delivery requires verification")
        verification_body = verification.get("body")
        if not isinstance(verification_body, Mapping) or verification_body.get("passed") is not True:
            raise _error("DELIVERY_NOT_READY", "successful delivery requires passing verification")
        coverage = coverage_view(contract_value, state.records, verification_body)
        if any(item["status"] not in ("proven", "waived") for item in coverage.values()):
            raise _error("DELIVERY_NOT_READY", "acceptance coverage is incomplete")
        review = next(
            (
                artifact
                for artifact in input_artifacts
                if isinstance(artifact, Mapping) and artifact.get("type") == "review-result"
            ),
            None,
        )
        if isinstance(review, Mapping):
            body = review.get("body")
            review_ok = (
                isinstance(body, Mapping)
                and body.get("outcome") == "approved"
                and body.get("assurance") == "independent"
            )
            waived = (
                isinstance(body, Mapping)
                and body.get("outcome") == "unavailable"
                and assurance_waiver(
                    state.records,
                    contract_value,
                    str(review.get("producer", {}).get("node_id", "")),
                )
                is not None
            )
            if not review_ok and not waived:
                raise _error(
                    "DELIVERY_NOT_READY",
                    "successful delivery requires independent approval or an exact waiver",
                )
    supplied = {
        "change_summary": output.get("summary", ""),
        "remaining_risks": output.get("remaining_risks", {}),
        "handoff_recommendation": output.get("handoff", ""),
    }
    return generate_dossier(
        contract=contract_value,
        records=state.records,
        current_snapshot=snapshot,
        outcome=contract.finalize_outcome or "incomplete",
        supplied=supplied,
    )


def _artifact_for_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    output: Mapping[str, object],
    binding: Mapping[str, object],
    snapshot: Mapping[str, object],
    contract_value: Mapping[str, object],
    producer: Mapping[str, object],
) -> Optional[Mapping[str, object]]:
    declared = _effective_artifact_contract(contract, definition)
    if declared is None:
        return None
    inputs = _canonical_inputs(binding)
    body = {
        key: json_value(value)
        for key, value in output.items()
        if key != "resources"
    }
    if contract.handler_id == "delivery.finalize":
        body = _dossier_body(
            state,
            contract,
            output,
            snapshot,
            contract_value,
            inputs,
        )
    return seal_artifact(
        {
            "type": declared.artifact_type,
            "contract_revision": contract_value["revision"],
            "contract_digest": contract_digest(contract_value),
            "producer": json_value(producer),
            "workspace_role": declared.workspace_role,
            "snapshot": json_value(snapshot),
            "inputs": inputs,
            "resources": _bound_resources(output, snapshot),
            "body": body,
        }
    )


def _binding_snapshot(
    state: TaskState,
    binding: Mapping[str, object],
    current_snapshot: Mapping[str, object],
) -> Mapping[str, object]:
    starting_digest = binding.get("starting_snapshot_digest")
    if current_snapshot.get("digest") == starting_digest:
        return current_snapshot
    predecessor = binding.get("source_predecessor")
    if isinstance(predecessor, Mapping):
        artifact = artifact_by_record_id(state.records).get(predecessor.get("record_id"))
        snapshot = artifact.get("snapshot") if isinstance(artifact, Mapping) else None
        if isinstance(snapshot, Mapping) and snapshot.get("digest") == starting_digest:
            return snapshot
    for artifact in reversed(tuple(artifact_by_record_id(state.records).values())):
        snapshot = artifact.get("snapshot") if isinstance(artifact, Mapping) else None
        if isinstance(snapshot, Mapping) and snapshot.get("digest") == starting_digest:
            return snapshot
    raise _error(
        "ACTION_BINDING_STALE",
        "the action starting snapshot is not a current recorded source",
    )


def _validate_binding_for_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    binding_value: object,
    current_snapshot: Mapping[str, object],
) -> Mapping[str, object]:
    binding = validate_action_binding(binding_value)
    contract_value = _current_contract(state)
    expected_scalars = {
        "task_id": state.task_id,
        "task_revision": state.revision,
        "action_id": contract.action_id,
        "node_id": contract.node_id,
        "contract_revision": contract_value["revision"],
        "contract_digest": contract_digest(contract_value),
    }
    mismatched = [
        field for field, expected in expected_scalars.items() if binding.get(field) != expected
    ]
    if mismatched:
        raise _error(
            "ACTION_BINDING_STALE",
            "action binding no longer matches the task",
            fields=mismatched,
        )
    starting_snapshot = _binding_snapshot(state, binding, current_snapshot)
    declared = _effective_artifact_contract(contract, definition)
    input_contracts: Iterable[object] = () if declared is None else declared.inputs
    resolved = resolve_inputs(
        state.records,
        contract_value,
        input_contracts,
        starting_snapshot,
        allow_revision_source=int(contract_value["revision"]) > 1,
    )
    if json_value(binding.get("inputs")) != [json_value(item) for item in resolved]:
        raise _error(
            "ACTION_BINDING_STALE",
            "action binding inputs are no longer authoritative",
        )
    predecessor = next(
        (item for item in resolved if item.get("edge") == "source-predecessor"),
        None,
    )
    if json_value(binding.get("source_predecessor")) != (
        None if predecessor is None else json_value(predecessor)
    ):
        raise _error("ACTION_BINDING_STALE", "source predecessor binding is invalid")
    role = None if declared is None else declared.workspace_role
    if contract.handler_id == "preflight" or role in (None, "context", "verifies-source"):
        if current_snapshot.get("digest") != binding.get("starting_snapshot_digest"):
            raise _error(
                "WORKSPACE_CHANGED",
                "this action does not authorize a workspace change",
            )
    elif role == "produces-source":
        if predecessor is None:
            raise _error(
                "ACTION_BINDING_INVALID",
                "a source-producing action requires a source predecessor",
            )
        if predecessor.get("snapshot_digest") != binding.get("starting_snapshot_digest"):
            raise _error(
                "ACTION_BINDING_STALE",
                "source predecessor and starting snapshot differ",
            )
    return binding


def _record_kind(contract: NodeContract) -> str:
    return {
        "preflight": "preflight",
        "verification.record": "verification",
        "review.record": "review",
        "delivery.finalize": "delivery-dossier",
    }.get(contract.handler_id, "action")


def _record_for_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    output: Mapping[str, object],
    binding_value: object,
    snapshot_value: object,
    timestamp: str,
) -> Tuple[Mapping[str, object], dict]:
    snapshot = _validated_snapshot(snapshot_value)
    binding = _validate_binding_for_action(
        state, definition, contract, binding_value, snapshot
    )
    contract_value = _current_contract(state)
    transition, attempt = _transition_for_action(
        state, contract, output, contract_value
    )
    producer = _producer(contract, attempt, output)
    artifact = _artifact_for_action(
        state,
        definition,
        contract,
        output,
        binding,
        snapshot,
        contract_value,
        producer,
    )
    record = seal_record(
        {
            "kind": _record_kind(contract),
            "task_revision": state.revision + 1,
            "timestamp": timestamp,
            "producer": producer,
            "payload": json_value(output),
            "contract": {
                "revision": contract_value["revision"],
                "digest": contract_digest(contract_value),
            },
            "transition": transition,
            "snapshot": json_value(snapshot),
            "artifact": None if artifact is None else json_value(artifact),
            "binding": json_value(binding),
        }
    )
    return record, transition


def apply_current_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    plan: MutationPlan,
    *,
    payload: Optional[Mapping[str, object]],
    binding: object,
    snapshot: object,
    timestamp: str,
) -> TaskState:
    """Append one action record after exact plan, binding, and snapshot checks."""
    current_contract, current_plan = plan_current_action(
        state, definition, plan.action_id, plan.expected_revision
    )
    if current_contract != contract or current_plan != plan:
        raise _error("PLAN_BINDING_MISMATCH", "node action plan is no longer current")
    output = validate_action_payload(contract, payload)
    record, transition = _record_for_action(
        state,
        definition,
        contract,
        output,
        binding,
        snapshot,
        timestamp,
    )
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        status=transition["status"],
        current_node=transition["to"],
        records=(*state.records, record),
    )


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > 8192
    ):
        raise _error("MUTATION_INVALID", "mutation text is invalid", field=field)
    return value


def _status_for_node(definition: WorkflowDefinition, node_id: str) -> str:
    if node_id == definition.entry_node:
        return "INTAKE"
    statuses = []
    contracts = list(definition.nodes.values())
    if definition.cancel_contract is not None:
        contracts.append(definition.cancel_contract)
    for contract in contracts:
        if contract.target_node == node_id and contract.target_status:
            statuses.append(contract.target_status)
        if contract.rework is not None:
            if contract.rework.failure_node == node_id:
                statuses.append(contract.rework.failure_status)
            if contract.rework.exhausted_node == node_id:
                statuses.append(contract.rework.exhausted_status)
    unique = tuple(dict.fromkeys(statuses))
    if len(unique) != 1:
        raise _error(
            "WORKFLOW_INVALID",
            "contract revision target does not have one deterministic status",
            node_id=node_id,
            statuses=list(unique),
        )
    return unique[0]


def revise_contract(
    state: TaskState,
    definition: WorkflowDefinition,
    *,
    new_contract: Mapping[str, object],
    reason: str,
    actor_label: str,
    snapshot: object,
    timestamp: str,
) -> TaskState:
    if state.revision == 0 or not state.records or state.records[0].get("kind") != "preflight":
        raise _error(
            "PREFLIGHT_REQUIRED",
            "contract revision is available only after repository preflight",
        )
    if is_terminal_state(state, definition):
        raise _error("ACTION_NOT_AVAILABLE", "terminal task cannot revise its contract")
    current = _current_contract(state)
    validated = validate_contract(
        new_contract, expected_revision=int(current["revision"]) + 1
    )
    previous_contract_digest = contract_digest(current)
    new_contract_digest = contract_digest(validated)
    clean_reason = _text(reason, "reason")
    clean_actor = _text(actor_label, "actor_label")
    current_snapshot = _validated_snapshot(snapshot)
    target = definition.revision_target
    transition = {
        "from": state.current_node,
        "to": target,
        "status": _status_for_node(definition, target),
        "route": "contract-revision",
    }
    producer = {
        "kind": "contract-revision",
        "action_id": "contract.revise",
        "node_id": state.current_node,
        "attempt": 1,
        "driver": None,
    }
    artifact = seal_artifact(
        {
            "type": "revision-source",
            "contract_revision": validated["revision"],
            "contract_digest": new_contract_digest,
            "producer": producer,
            "workspace_role": "produces-source",
            "snapshot": json_value(current_snapshot),
            "inputs": [],
            "resources": [],
            "body": {"reason": clean_reason, "actor_label": clean_actor},
        }
    )
    payload = {
        "new_contract": json_value(validated),
        "previous_contract_digest": previous_contract_digest,
        "new_contract_digest": new_contract_digest,
        "reason": clean_reason,
        "actor_label": clean_actor,
    }
    record = seal_record(
        {
            "kind": "contract-revision",
            "task_revision": state.revision + 1,
            "timestamp": timestamp,
            "producer": producer,
            "payload": payload,
            "contract": {
                "revision": validated["revision"],
                "digest": new_contract_digest,
            },
            "transition": transition,
            "snapshot": json_value(current_snapshot),
            "artifact": json_value(artifact),
            "binding": None,
        }
    )
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        status=transition["status"],
        current_node=target,
        records=(*state.records, record),
    )


def record_decision(
    state: TaskState,
    definition: WorkflowDefinition,
    *,
    decision: Mapping[str, object],
    timestamp: str,
) -> TaskState:
    if state.revision == 0 or not state.records or state.records[0].get("kind") != "preflight":
        raise _error(
            "PREFLIGHT_REQUIRED",
            "decisions are available only after repository preflight",
        )
    if is_terminal_state(state, definition):
        raise _error("ACTION_NOT_AVAILABLE", "terminal task cannot record a decision")
    contract_value = _current_contract(state)
    validated = validate_decision(
        decision, contract=contract_value, records=state.records
    )
    if validated["kind"] == "assurance-waiver":
        review = definition.nodes.get(validated["subject"])
        if review is None or review.handler_id != "review.record":
            raise _error(
                "DECISION_INVALID",
                "assurance waiver subject must be an exact review node id",
            )
    producer = {
        "kind": "decision",
        "actor_label": validated["actor_label"],
    }
    record = seal_record(
        {
            "kind": "decision",
            "task_revision": state.revision + 1,
            "timestamp": timestamp,
            "producer": producer,
            "payload": json_value(validated),
            "contract": {
                "revision": contract_value["revision"],
                "digest": contract_digest(contract_value),
            },
            "transition": None,
            "snapshot": None,
            "artifact": None,
            "binding": None,
        }
    )
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        records=(*state.records, record),
    )


def _state_invalid(reason: str, **details: object) -> DevFlowError:
    return _error(
        "STATE_INVALID",
        "task state is inconsistent with its workflow",
        reason=reason,
        **details,
    )


def _replay_action_record(
    replay_state: TaskState,
    definition: WorkflowDefinition,
    record: Mapping[str, object],
) -> TaskState:
    producer = record.get("producer")
    if not isinstance(producer, Mapping):
        raise _state_invalid("record_producer_invalid")
    action_id = producer.get("action_id")
    try:
        contract, plan = plan_current_action(
            replay_state,
            definition,
            str(action_id),
            replay_state.revision,
        )
        output = validate_action_payload(contract, record.get("payload"))
        expected = apply_current_action(
            replay_state,
            definition,
            contract,
            plan,
            payload=output,
            binding=record.get("binding"),
            snapshot=record.get("snapshot"),
            timestamp=str(record.get("timestamp")),
        )
    except DevFlowError as exc:
        raise _state_invalid(
            "action_replay_failed", cause=exc.code, cause_details=exc.details
        ) from exc
    if json_value(expected.records[-1]) != json_value(record):
        raise _state_invalid("action_record_not_deterministic")
    return expected


def validate_persisted_state(
    state: TaskState, definition: WorkflowDefinition
) -> None:
    """Replay every immutable record and fail closed on any divergence."""
    try:
        reconstructed = TaskState.from_dict(state.as_dict(), definition=definition)
    except DevFlowError as exc:
        raise _state_invalid(
            "state_shape_invalid", cause=exc.code, cause_details=exc.details
        ) from exc
    if reconstructed != state:
        raise _state_invalid("state_shape_invalid")
    if state.current_node not in definition.nodes:
        raise _state_invalid("current_node_unknown", current_node=state.current_node)
    replay = replace(
        state,
        revision=0,
        updated_at=state.created_at,
        status="INTAKE",
        current_node=definition.entry_node,
        records=(),
    )
    for index, raw_record in enumerate(state.records, start=1):
        try:
            record = validate_record_seal(raw_record)
        except DevFlowError as exc:
            raise _state_invalid(
                "record_seal_invalid", record_index=index, cause=exc.code
            ) from exc
        if set(record) != RECORD_FIELDS:
            raise _state_invalid(
                "record_fields_invalid",
                record_index=index,
                fields=sorted(str(field) for field in record),
            )
        if record.get("task_revision") != index:
            raise _state_invalid("record_revision_invalid", record_index=index)
        if not isinstance(record.get("timestamp"), str) or not record["timestamp"]:
            raise _state_invalid("record_timestamp_invalid", record_index=index)
        kind = record.get("kind")
        if index == 1 and kind != "preflight":
            raise _state_invalid("preflight_not_first")
        if kind == "decision":
            if index == 1:
                raise _state_invalid("decision_before_preflight")
            try:
                candidate = record_decision(
                    replay,
                    definition,
                    decision=record.get("payload"),
                    timestamp=record["timestamp"],
                )
            except DevFlowError as exc:
                raise _state_invalid(
                    "decision_replay_failed", cause=exc.code, cause_details=exc.details
                ) from exc
        elif kind == "contract-revision":
            payload = record.get("payload")
            if not isinstance(payload, Mapping) or set(payload) != {
                "new_contract",
                "previous_contract_digest",
                "new_contract_digest",
                "reason",
                "actor_label",
            }:
                raise _state_invalid("contract_revision_payload_invalid")
            try:
                replay_contract = _current_contract(replay)
                if payload["previous_contract_digest"] != contract_digest(
                    replay_contract
                ):
                    raise _state_invalid(
                        "contract_revision_previous_digest_invalid",
                        record_index=index,
                    )
                replay_replacement = validate_contract(
                    payload["new_contract"],
                    expected_revision=int(replay_contract["revision"]) + 1,
                )
                if payload["new_contract_digest"] != contract_digest(
                    replay_replacement
                ):
                    raise _state_invalid(
                        "contract_revision_new_digest_invalid",
                        record_index=index,
                    )
                candidate = revise_contract(
                    replay,
                    definition,
                    new_contract=payload["new_contract"],
                    reason=payload["reason"],
                    actor_label=payload["actor_label"],
                    snapshot=record.get("snapshot"),
                    timestamp=record["timestamp"],
                )
            except DevFlowError as exc:
                raise _state_invalid(
                    "contract_revision_replay_failed",
                    cause=exc.code,
                    cause_details=exc.details,
                ) from exc
        elif kind in ("preflight", "action", "verification", "review", "delivery-dossier"):
            candidate = _replay_action_record(replay, definition, record)
        else:
            raise _state_invalid("record_kind_invalid", record_index=index, kind=kind)
        if json_value(candidate.records[-1]) != json_value(record):
            raise _state_invalid("record_replay_mismatch", record_index=index)
        replay = candidate
    if (
        replay.revision != state.revision
        or replay.status != state.status
        or replay.current_node != state.current_node
        or replay.updated_at != state.updated_at
        or json_value(replay.records) != json_value(state.records)
    ):
        raise _state_invalid("state_replay_result_mismatch")


def validate_state_transition(
    previous: TaskState,
    candidate: TaskState,
    definition: WorkflowDefinition,
) -> None:
    """Require an exact one-record append and immutable initialization fields."""
    immutable_fields = (
        "task_id",
        "requirement",
        "created_at",
        "workflow_id",
        "workflow_version",
        "workflow_schema",
        "workflow_adapter_identity",
        "workflow_identity",
        "repositories",
        "original_contract",
        "schema_version",
        "product_identity",
    )
    changed = [
        field
        for field in immutable_fields
        if getattr(previous, field) != getattr(candidate, field)
    ]
    if changed:
        raise _error(
            "STATE_WRITE_INVALID",
            "task mutation changed immutable initialization state",
            fields=changed,
        )
    if candidate.revision != previous.revision + 1:
        raise _error(
            "STATE_WRITE_INVALID",
            "task mutation must advance exactly one revision",
        )
    if (
        len(candidate.records) != len(previous.records) + 1
        or candidate.records[:-1] != previous.records
    ):
        raise _error(
            "STATE_WRITE_INVALID",
            "task mutation must append exactly one record without rewriting history",
        )
    validate_persisted_state(candidate, definition)


def _dossier_summary(
    state: TaskState,
    contract_value: Mapping[str, object],
    freshness: Mapping[str, object],
) -> Optional[dict]:
    current_digest = contract_digest(contract_value)
    for record in reversed(state.records):
        if not isinstance(record, Mapping):
            continue
        artifact = record.get("artifact")
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("type") != "delivery-dossier"
            or artifact.get("contract_digest") != current_digest
        ):
            continue
        body = artifact.get("body")
        coverage = body.get("coverage", {}) if isinstance(body, Mapping) else {}
        counts = {"proven": 0, "waived": 0, "unverified": 0}
        if isinstance(coverage, Mapping):
            for item in coverage.values():
                status = item.get("status") if isinstance(item, Mapping) else "unverified"
                counts[status if status in counts else "unverified"] += 1
        current = freshness.get(str(record.get("record_id")), {})
        return {
            "record_id": record.get("record_id"),
            "digest": artifact.get("digest"),
            "outcome": body.get("outcome") if isinstance(body, Mapping) else None,
            "coverage": counts,
            "current": current.get("current", False),
            "stale_reasons": current.get("reasons", []),
        }
    return None


def agent_projection(
    state: TaskState,
    definition: WorkflowDefinition,
    current_snapshot: Mapping[str, object],
) -> dict:
    """Return one compact action plus its canonical provenance binding."""
    snapshot = _validated_snapshot(current_snapshot)
    contract_value = _current_contract(state)
    freshness = artifact_freshness(state.records, contract_value, snapshot)
    terminal = is_terminal_state(state, definition)
    action = None
    if not terminal:
        node = current_node_contract(state, definition)
        declared = _effective_artifact_contract(node, definition)
        blocked = None
        try:
            inputs = resolve_inputs(
                state.records,
                contract_value,
                () if declared is None else declared.inputs,
                snapshot,
                allow_revision_source=int(contract_value["revision"]) > 1,
            )
            binding = make_action_binding(
                task_id=state.task_id,
                revision=state.revision,
                action_id=node.action_id,
                node_id=node.node_id,
                contract=contract_value,
                inputs=inputs,
                current_snapshot=snapshot,
            )
        except DevFlowError as exc:
            if exc.code != "ARTIFACT_INPUT_MISSING":
                raise
            inputs = ()
            binding = None
            blocked = {
                "code": exc.code,
                "message": exc.message,
                "details": dict(exc.details),
            }
        retry = None
        if node.rework is not None:
            used = assurance_attempts(state.records, node.node_id, contract_value)
            retry = {
                "attempts_used": used,
                "max_attempts": node.rework.max_attempts,
                "remaining": max(0, node.rework.max_attempts - used),
            }
        action = {
            **node.as_dict(),
            "inputs": [json_value(item) for item in inputs],
            "binding": None if binding is None else json_value(binding),
            "blocked": blocked,
            "retry_budget": retry,
        }
    repository = state.repositories[0]
    return {
        "schema": AGENT_PROTOCOL_SCHEMA,
        "task_id": state.task_id,
        "revision": state.revision,
        "workflow": {
            "id": state.workflow_id,
            "version": state.workflow_version,
            "schema": state.workflow_schema,
            "adapter_identity": state.workflow_adapter_identity,
            "identity": state.workflow_identity,
        },
        "status": state.status,
        "current_node": state.current_node,
        "contract": contract_summary(contract_value),
        "repository": {
            "id": repository.repository_id,
            "path": repository.path,
            "snapshot": {
                key: json_value(snapshot.get(key))
                for key in (
                    "digest",
                    "head",
                    "branch",
                    "clean",
                    "status_sha256",
                    "status_bytes",
                )
            },
        },
        "freshness": freshness,
        "action": action,
        "dossier": _dossier_summary(state, contract_value, freshness),
        "done": terminal,
    }


def task_view(
    state: TaskState,
    definition: WorkflowDefinition,
    current_snapshot: Mapping[str, object],
) -> dict:
    """Full read-only state and derived delivery view for explicit inspection."""
    snapshot = _validated_snapshot(current_snapshot)
    contract_value = _current_contract(state)
    freshness = artifact_freshness(state.records, contract_value, snapshot)
    return {
        **state.as_dict(),
        "effective_contract": json_value(contract_value),
        "effective_contract_digest": contract_digest(contract_value),
        "current_snapshot": json_value(snapshot),
        "artifact_freshness": freshness,
        "dossier": _dossier_summary(state, contract_value, freshness),
        "terminal": is_terminal_state(state, definition),
    }


def current_resource_requests(state: TaskState) -> tuple:
    """Resources required for a current snapshot without mutating state."""
    return governing_resource_requests(state.records, _current_contract(state))
