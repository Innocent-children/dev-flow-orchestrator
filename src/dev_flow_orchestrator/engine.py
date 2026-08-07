"""Pure ledger replay, action binding, assurance routing, and projections."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from .delivery import (
    artifact_by_record_id,
    artifact_freshness,
    assurance_waiver,
    contract_digest,
    contract_summary,
    coverage_view,
    decisions_for_contract,
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
from .capsule import (
    ambient_drift,
    derive_manifest,
    make_preflight_baseline,
    snapshot_has_unmerged_entries,
)
from .assurance import (
    budget_view,
    derive_assurance_plan,
    next_obligation,
    normalize_impact_report,
    obligation_states,
    validate_assurance_execution,
)
from .review import derive_review_result, validate_disposition, validate_finding
from .model import (
    DevFlowError,
    MutationPlan,
    TaskState,
    canonical_json_bytes,
    freeze_json,
    json_value,
)
from .product import (
    AGENT_PROTOCOL_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    MAX_ACTION_PAYLOAD_BYTES,
    MAX_TEXT_FIELD_BYTES,
    TASK_CHANGE_CLAIMS_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
)
from .snapshot import repository_snapshot, validate_task_snapshot
from .workflow import (
    ArtifactContract,
    InputContract,
    NodeContract,
    WorkflowDefinition,
)


NODE_OUTPUT_INVALID = "NODE_OUTPUT_INVALID"
MAX_NODE_OUTPUT_BYTES = MAX_ACTION_PAYLOAD_BYTES
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
    if (
        contract.handler_id == "assurance.dispatch"
        or ".rework." in contract.action_id
    ) and contract.action_id != action_id:
        adaptive = _adaptive_context(state, definition)
        finalizer = _adaptive_dispatch_finalizer(definition, adaptive)
        if (
            finalizer is not None
            and finalizer.action_id == action_id
            and (
                contract.handler_id == "assurance.dispatch"
                or finalizer.finalize_outcome == "success"
            )
        ):
            contract = finalizer
    cancel = definition.cancel_for(state.current_node)
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
    if state.revision == 0 and contract.handler_id != "preflight" and not is_cancel:
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
    optional_fields = (
        {"ownership_claims": "object"}
        if contract.artifact is not None
        and contract.artifact.workspace_role == "produces-source"
        and contract.handler_id != "preflight"
        else {}
    )
    if contract.artifact is not None and contract.artifact.artifact_type == "impact-report":
        optional_fields["impact_manifest"] = "object"
    if contract.handler_id == "assurance.dispatch":
        optional_fields["assurance_result"] = "object"
    accepted_types = {**dict(contract.payload_types), **optional_fields}
    missing = sorted(set(contract.payload_types) - set(value))
    unknown = sorted(set(value) - set(accepted_types))
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
    for field, expected_type in accepted_types.items():
        if field not in value:
            continue
        item = value[field]
        valid = (
            expected_type == "string"
            and isinstance(item, str)
            and bool(item.strip())
            and len(item.encode("utf-8")) <= MAX_TEXT_FIELD_BYTES
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
    driver_result = value.get("driver_result")
    if driver_result is not None and (
        not isinstance(driver_result, dict)
        or driver_result.get("schema") != DRIVER_RESULT_SCHEMA
    ):
        raise _error(
            NODE_OUTPUT_INVALID,
            "driver result must use the current product schema",
            expected_schema=DRIVER_RESULT_SCHEMA,
        )
    return freeze_json(value)


def _validated_snapshot(
    value: object, repositories: Sequence[object]
) -> Mapping[str, object]:
    try:
        return freeze_json(validate_task_snapshot(value, repositories))
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
    records: Sequence[object], contract: NodeContract, contract_value: Mapping[str, object]
) -> int:
    digest = contract_digest(contract_value)
    return 1 + sum(
        1
        for record in records
        if isinstance(record, Mapping)
        and isinstance(record.get("producer"), Mapping)
        and record["producer"].get("kind") == "workflow-action"
        and record["producer"].get("node_id") == contract.node_id
        and record["producer"].get("action_id") == contract.action_id
        and isinstance(record.get("contract"), Mapping)
        and record["contract"].get("digest") == digest
    )


def _coverage_payload(
    output: Mapping[str, object],
    contract_value: Mapping[str, object],
    repositories: Sequence[object],
) -> Mapping[str, object]:
    coverage = output.get("coverage")
    criterion_ids = tuple(
        item["id"] for item in contract_value["acceptance_criteria"]
    )
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "schema",
        "criteria",
        "repositories",
        "integration",
    }:
        raise _error(
            NODE_OUTPUT_INVALID,
            "verification coverage must contain schema, criteria, repositories, and integration",
        )
    if coverage.get("schema") != VERIFICATION_COVERAGE_SCHEMA:
        raise _error(
            NODE_OUTPUT_INVALID,
            "verification coverage must use the current product schema",
            expected_schema=VERIFICATION_COVERAGE_SCHEMA,
        )
    criteria = coverage.get("criteria")
    if not isinstance(criteria, Mapping) or set(criteria) != set(criterion_ids):
        raise _error(
            NODE_OUTPUT_INVALID,
            "verification coverage must report every acceptance criterion",
            expected_criterion_ids=list(criterion_ids),
        )
    normalized_criteria = {}
    for criterion_id in criterion_ids:
        status = criteria.get(criterion_id)
        if status not in ("proven", "unverified"):
            raise _error(
                NODE_OUTPUT_INVALID,
                "verification coverage values must be proven or unverified",
                criterion_id=criterion_id,
            )
        normalized_criteria[criterion_id] = status

    def result(value: object, field: str) -> dict:
        if not isinstance(value, Mapping) or set(value) != {"command", "passed"}:
            raise _error(
                NODE_OUTPUT_INVALID,
                "verification result fields are invalid",
                field=field,
            )
        command = value.get("command")
        passed = value.get("passed")
        if (
            not isinstance(command, str)
            or not command.strip()
            or len(command.encode("utf-8")) > 8192
            or not isinstance(passed, bool)
        ):
            raise _error(
                NODE_OUTPUT_INVALID,
                "verification result value is invalid",
                field=field,
            )
        return {"command": command, "passed": passed}

    repository_ids = tuple(item.repository_id for item in repositories)
    repository_results = coverage.get("repositories")
    if not isinstance(repository_results, Mapping) or set(repository_results) != set(
        repository_ids
    ):
        raise _error(
            NODE_OUTPUT_INVALID,
            "verification must report every repository exactly once",
            expected_repository_ids=list(repository_ids),
        )
    normalized_repositories = {
        repository_id: result(
            repository_results.get(repository_id),
            "repositories." + repository_id,
        )
        for repository_id in repository_ids
    }
    integration = result(coverage.get("integration"), "integration")
    if output.get("command") != integration["command"]:
        raise _error(
            NODE_OUTPUT_INVALID,
            "top-level verification command must equal the integration command",
        )
    aggregate_passed = integration["passed"] and all(
        item["passed"] for item in normalized_repositories.values()
    )
    if output.get("passed") is not aggregate_passed:
        raise _error(
            NODE_OUTPUT_INVALID,
            "top-level passed must equal the repository and integration command aggregate",
        )
    return freeze_json(
        {
            "schema": VERIFICATION_COVERAGE_SCHEMA,
            "criteria": normalized_criteria,
            "repositories": normalized_repositories,
            "integration": integration,
        }
    )


def _assurance_success(
    state: TaskState,
    contract: NodeContract,
    output: Mapping[str, object],
    contract_value: Mapping[str, object],
    records: Sequence[object],
) -> bool:
    if contract.handler_id == "verification.record":
        coverage = _coverage_payload(output, contract_value, state.repositories)
        if output.get("passed") is not True:
            return False
        view = coverage_view(contract_value, records, {"coverage": coverage})
        incomplete = any(
            item["status"] not in ("proven", "waived")
            for item in view.values()
        )
        if incomplete:
            return False
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
    attempt = _action_attempt(state.records, contract, contract_value)
    route = "cancel" if contract is not None and contract.node_id == "cancel" else "success"
    target_node = contract.target_node
    target_status = contract.target_status
    if contract.handler_id in ("verification.record", "review.record"):
        succeeded = _assurance_success(
            state, contract, output, contract_value, state.records
        )
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
    contract: NodeContract,
) -> Optional[ArtifactContract]:
    if contract.handler_id == "delivery.finalize" and contract.artifact is not None:
        return ArtifactContract(
            contract.artifact.artifact_type,
            contract.artifact.workspace_role,
            (),
        )
    if contract.artifact is not None:
        return contract.artifact
    if contract.node_id == "cancel":
        return None
    if contract.handler_id == "preflight":
        return ArtifactContract("repository-baseline", "produces-source", ())
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
    state: TaskState,
    output: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> list:
    repository_ids = tuple(item.repository_id for item in state.repositories)
    requested = resource_requests(output, repository_ids)
    result = []
    for request in requested:
        repository_id = request.get("repository_id")
        member_snapshot = repository_snapshot(
            snapshot,
            state.repositories,
            str(repository_id),
        )
        snapshot_items = member_snapshot.get("resources")
        if not isinstance(snapshot_items, (list, tuple)):
            snapshot_items = ()
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
                repository_id=repository_id,
            )
        result.append({"repository_id": repository_id, **json_value(match)})
    return result


def _dossier_body(
    state: TaskState,
    contract: NodeContract,
    output: Mapping[str, object],
    snapshot: Mapping[str, object],
    contract_value: Mapping[str, object],
    inputs: Sequence[Mapping[str, object]],
) -> dict:
    assurance_body = _latest_artifact_body(state, body_field="assurance_plan")
    if assurance_body is not None:
        plan = assurance_body["assurance_plan"]
        manifest_body = _latest_artifact_body(state, body_field="task_change_manifest")
        impact_body = _latest_artifact_body(state, artifact_type="impact-report")
        history = _assurance_history(state, plan)
        executions = history["state_executions"]
        waived_subjects = {
            item["subject"]
            for item in decisions_for_contract(state.records, contract_value)
            if item.get("kind") == "assurance-waiver"
        }
        dispositioned_obligation_ids = _dispositioned_review_obligation_ids(state, plan)
        waived_obligation_ids = tuple(sorted(set(
            obligation["obligation_id"]
            for obligation in plan["obligations"]
            if obligation["obligation_id"] in waived_subjects
            or obligation["fingerprint"] in waived_subjects
        ) | set(dispositioned_obligation_ids)))
        states = obligation_states(
            plan,
            executions,
            waived_obligation_ids=waived_obligation_ids,
            reused_obligation_ids=history["reused_obligation_ids"],
        )
        state_by_id = {item["obligation_id"]: item for item in states}
        decisions = decisions_for_contract(state.records, contract_value)
        criterion_waiver_by_id = {
            item["subject"]: item
            for item in decisions
            if item.get("kind") == "criterion-waiver"
        }
        executions_by_fingerprint = {}
        for execution in history["all_executions"]:
            executions_by_fingerprint.setdefault(
                execution["obligation_fingerprint"], []
            ).append(execution["digest"])
        reused_execution_digests = {}
        for decision in history["reuse_decisions"]:
            if decision["status"] == "reused":
                reused_execution_digests.setdefault(
                    decision["current_obligation_id"], []
                ).append(decision["execution_digest"])
        adaptive_coverage = {}
        for criterion in contract_value["acceptance_criteria"]:
            criterion_id = criterion["id"]
            related = [
                obligation
                for obligation in plan["obligations"]
                if criterion_id in obligation["criterion_ids"]
            ]
            proofs = [
                {
                    "obligation_id": obligation["obligation_id"],
                    "obligation_fingerprint": obligation["fingerprint"],
                    "state": state_by_id[obligation["obligation_id"]]["state"],
                    "execution_digests": sorted(
                        executions_by_fingerprint.get(obligation["fingerprint"], [])
                        + reused_execution_digests.get(obligation["obligation_id"], [])
                    ),
                    "task_change_slice": json_value(obligation["task_change_slice"]),
                    "impact_closure": json_value(obligation["impact_closure"]),
                    "repository_ids": json_value(obligation["repository_ids"]),
                }
                for obligation in related
            ]
            waiver = criterion_waiver_by_id.get(criterion_id)
            if waiver is not None:
                adaptive_coverage[criterion_id] = {
                    "status": "waived",
                    "decision": json_value(waiver),
                    "proofs": proofs,
                }
            else:
                discharged = bool(related) and all(
                    item["state"] in ("satisfied", "reused", "waived")
                    for item in proofs
                )
                adaptive_coverage[criterion_id] = {
                    "status": "proven" if discharged else "unverified",
                    "proofs": proofs,
                }
        unresolved = [
            item for item in states
            if item["state"] not in ("satisfied", "reused", "waived", "not-required")
        ]
        if contract.finalize_outcome == "success" and unresolved:
            raise _error(
                "DELIVERY_NOT_READY",
                "successful delivery requires every current assurance obligation",
                unmet_obligations=[item["obligation_id"] for item in unresolved],
            )
        if contract.finalize_outcome == "success" and any(
            item["status"] not in ("proven", "waived")
            for item in adaptive_coverage.values()
        ):
            raise _error(
                "DELIVERY_NOT_READY",
                "successful delivery requires current criterion coverage",
            )
        supplied = {
            "change_summary": output.get("summary", ""),
            "remaining_risks": output.get("remaining_risks", {}),
            "handoff_recommendation": output.get("handoff", ""),
        }
        dossier = generate_dossier(
            contract=contract_value,
            records=state.records,
            current_snapshot=snapshot,
            outcome=contract.finalize_outcome or "incomplete",
            supplied=supplied,
            repositories=state.repositories,
        )
        current_proof_record_ids = {
            str(item["execution_record_id"])
            for item in history["reuse_decisions"]
            if item["status"] == "reused"
        }
        reusable_fingerprints = {
            obligation["fingerprint"]
            for obligation in plan["obligations"]
            if state_by_id[obligation["obligation_id"]]["state"]
            in ("satisfied", "reused")
        }
        manifest_history = []
        revision_intervals = []
        assurance_history = []
        review_history = []
        for record in state.records:
            if not isinstance(record, Mapping):
                continue
            artifact = record.get("artifact")
            if not isinstance(artifact, Mapping):
                continue
            body = artifact.get("body")
            if not isinstance(body, Mapping):
                continue
            recorded_manifest = body.get("task_change_manifest")
            if isinstance(recorded_manifest, Mapping):
                manifest_history.append({
                    "record_id": record.get("record_id"),
                    "artifact_type": artifact.get("type"),
                    "artifact_digest": artifact.get("digest"),
                    "snapshot_digest": (
                        artifact["snapshot"].get("digest")
                        if isinstance(artifact.get("snapshot"), Mapping)
                        else None
                    ),
                    "producer": json_value(artifact.get("producer")),
                    "manifest": json_value(recorded_manifest),
                })
            if artifact.get("type") == "revision-source":
                revision_intervals.append({
                    "record_id": record.get("record_id"),
                    "contract_digest": artifact.get("contract_digest"),
                    "revision_interval": json_value(body.get("revision_interval")),
                    "adoption_claims": json_value(body.get("adoption_claims")),
                    "manifest_digest": (
                        recorded_manifest.get("digest")
                        if isinstance(recorded_manifest, Mapping)
                        else None
                    ),
                })
            execution = body.get("assurance_execution")
            if isinstance(execution, Mapping):
                current = (
                    execution.get("obligation_fingerprint") in reusable_fingerprints
                    or str(record.get("record_id")) in current_proof_record_ids
                )
                if current and execution.get("passed") is True:
                    current_proof_record_ids.add(str(record.get("record_id")))
                entry = {
                    "record_id": record.get("record_id"),
                    "artifact_digest": artifact.get("digest"),
                    "current": current,
                    "execution": json_value(execution),
                    "obligation": json_value(body.get("obligation")),
                    "review_result": json_value(body.get("review_result")),
                    "review_binding": json_value(body.get("review_binding")),
                    "reuse_basis": next(
                        (
                            json_value(item)
                            for item in history["reuse_decisions"]
                            if str(item["execution_record_id"])
                            == str(record.get("record_id"))
                        ),
                        None,
                    ),
                }
                assurance_history.append(entry)
                if isinstance(body.get("review_result"), Mapping):
                    review_history.append(entry)
        for item in dossier.get("artifacts", ()):
            if str(item.get("record_id")) not in current_proof_record_ids:
                continue
            item["stale_reasons"] = [
                reason
                for reason in item.get("stale_reasons", ())
                if reason != "superseded"
                and not str(reason).startswith(("source_replaced", "workspace_changed"))
            ]
            item["current"] = not item["stale_reasons"]
        for key in ("verification_attempts", "review_attempts"):
            for item in dossier.get(key, ()):
                if str(item.get("record_id")) in current_proof_record_ids:
                    item["stale_reasons"] = [
                        reason
                        for reason in item.get("stale_reasons", ())
                        if reason != "superseded"
                        and not str(reason).startswith(("source_replaced", "workspace_changed"))
                    ]
                    item["current"] = not item["stale_reasons"]
        accepted_snapshot = _latest_manifest_snapshot(state)
        drift = (
            None
            if accepted_snapshot is None
            else ambient_drift(accepted_snapshot, snapshot, state.repositories)
        )
        structured_findings = []
        for record in state.records:
            if not isinstance(record, Mapping):
                continue
            record_contract = record.get("contract")
            if (
                not isinstance(record_contract, Mapping)
                or record_contract.get("digest") != contract_digest(contract_value)
            ):
                continue
            payload = record.get("payload")
            assurance_result = (
                payload.get("assurance_result") if isinstance(payload, Mapping) else None
            )
            review = (
                assurance_result.get("review")
                if isinstance(assurance_result, Mapping)
                else None
            )
            findings = review.get("findings") if isinstance(review, Mapping) else None
            if isinstance(findings, (list, tuple)):
                structured_findings.extend(json_value(item) for item in findings)
        return {
            **dossier,
            "coverage": adaptive_coverage,
            "preflight_origin": json_value(
                next(
                    (
                        artifact.get("body", {}).get("preflight_baseline")
                        for artifact in artifact_by_record_id(state.records).values()
                        if isinstance(artifact, Mapping)
                        and artifact.get("type") == "repository-baseline"
                        and isinstance(artifact.get("body"), Mapping)
                    ),
                    None,
                )
            ),
            "task_change_manifest": None if manifest_body is None else json_value(manifest_body["task_change_manifest"]),
            "impact_manifest": None if impact_body is None else json_value(impact_body.get("impact_manifest")),
            "assurance_plan": json_value(plan),
            "obligation_states": json_value(states),
            "assurance_budget": budget_view(
                plan,
                history["all_executions"],
                execution_classes=history["execution_classes"],
                rework_executions=history["rework_executions"],
                governance_mutations=history["governance_mutations"],
                fixed_mutations=history["fixed_mutations"] + 1,
            ),
            "review_findings": structured_findings,
            "finding_dispositions": json_value(
                _finding_dispositions(state, contract_value, current_only=False)
            ),
            "manifest_history": manifest_history,
            "revision_intervals": revision_intervals,
            "ambient_drift": json_value(drift),
            "assurance_history": assurance_history,
            "assurance_reuse_history": json_value(history["reuse_decisions"]),
            "review_history": review_history,
            "governance_history": json_value([
                {
                    "record_id": record.get("record_id"),
                    "kind": record.get("kind"),
                    "contract": record.get("contract"),
                    "payload": record.get("payload"),
                }
                for record in state.records
                if isinstance(record, Mapping)
                and record.get("kind") in ("decision", "finding-disposition", "contract-revision")
            ]),
            "repository_results": json_value([
                state_by_id[item["obligation_id"]]
                for item in plan["obligations"]
                if item["kind"] == "repository-check"
            ]),
            "integration_results": json_value([
                state_by_id[item["obligation_id"]]
                for item in plan["obligations"]
                if item["kind"] == "integration-check"
            ]),
            "decision": {
                "outcome": "DONE" if contract.finalize_outcome == "success" else "INCOMPLETE",
                "unmet_obligation_ids": [item["obligation_id"] for item in unresolved],
                "reason": "all current obligations are discharged" if not unresolved else "required assurance remains unresolved or exhausted",
            },
        }
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
        repositories=state.repositories,
    )


def _artifact_for_action(
    state: TaskState,
    contract: NodeContract,
    output: Mapping[str, object],
    binding: Mapping[str, object],
    snapshot: Mapping[str, object],
    contract_value: Mapping[str, object],
    producer: Mapping[str, object],
    adaptive: Optional[Mapping[str, object]] = None,
) -> Optional[Mapping[str, object]]:
    declared = _effective_artifact_contract(contract)
    if declared is None:
        return None
    inputs = _canonical_inputs(binding)
    body = {
        key: json_value(value)
        for key, value in output.items()
        if key != "resources"
    }
    if contract.handler_id == "preflight":
        baseline = make_preflight_baseline(
            task_id=state.task_id,
            contract_digest=contract_digest(contract_value),
            snapshot=snapshot,
            repositories=state.repositories,
        )
        empty_manifest = derive_manifest(
            task_id=state.task_id,
            contract=contract_value,
            contract_digest=contract_digest(contract_value),
            repositories=state.repositories,
            preflight=baseline,
            predecessor=None,
            before_snapshot=snapshot,
            after_snapshot=snapshot,
            claims={"schema": TASK_CHANGE_CLAIMS_SCHEMA, "claims": []},
            producer={
                "action_id": contract.action_id,
                "task_revision": state.revision + 1,
                "contract_revision": contract_value["revision"],
                "binding_digest": hashlib.sha256(canonical_json_bytes(binding)).hexdigest(),
            },
        )
        body = {
            "preflight_baseline": baseline,
            "task_change_manifest": empty_manifest,
        }
    elif declared.artifact_type == "impact-report":
        submitted_impact = output.get("impact_manifest")
        if submitted_impact is None:
            submitted_impact = {
                "confidence": "unknown",
                "entries": [],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": False,
                "overflow": False,
                "limitations": ["impact closure was not supplied; conservative assurance is required"],
            }
        body = {
            **body,
            "impact_manifest": normalize_impact_report(
                submitted_impact,
                repositories=state.repositories,
                contract=contract_value,
            ),
        }
    elif declared.workspace_role == "produces-source":
        baseline = next(
            (
                artifact.get("body", {}).get("preflight_baseline")
                for artifact in artifact_by_record_id(state.records).values()
                if isinstance(artifact, Mapping)
                and artifact.get("type") == "repository-baseline"
                and isinstance(artifact.get("body"), Mapping)
            ),
            None,
        )
        if baseline is None:
            raise _error("CAPSULE_INVALID", "source action has no immutable preflight baseline")
        predecessor = next(
            (
                artifact.get("body", {}).get("task_change_manifest")
                for artifact in reversed(tuple(artifact_by_record_id(state.records).values()))
                if isinstance(artifact, Mapping)
                and isinstance(artifact.get("body"), Mapping)
                and isinstance(artifact.get("body", {}).get("task_change_manifest"), Mapping)
            ),
            None,
        )
        claims = output.get(
            "ownership_claims",
            {"schema": TASK_CHANGE_CLAIMS_SCHEMA, "claims": []},
        )
        if not isinstance(claims, Mapping) or claims.get("schema") != TASK_CHANGE_CLAIMS_SCHEMA:
            raise _error("OWNERSHIP_CLAIMS_INVALID", "source action requires current exact ownership claims")
        starting_snapshot = _binding_snapshot(state, binding, snapshot)
        manifest = derive_manifest(
            task_id=state.task_id,
            contract=contract_value,
            contract_digest=contract_digest(contract_value),
            repositories=state.repositories,
            preflight=baseline,
            predecessor=predecessor,
            before_snapshot=starting_snapshot,
            after_snapshot=snapshot,
            claims=claims,
            producer={
                "action_id": contract.action_id,
                "task_revision": state.revision + 1,
                "contract_revision": contract_value["revision"],
                "binding_digest": hashlib.sha256(canonical_json_bytes(binding)).hexdigest(),
            },
        )
        body = {**body, "task_change_manifest": manifest}
    elif contract.handler_id == "assurance.dispatch":
        if adaptive is None:
            raise _error("ASSURANCE_INVALID", "adaptive assurance context is unavailable")
        body = {
            "summary": output.get("summary", ""),
            "assurance_plan": json_value(adaptive["plan"]),
            "assurance_execution": json_value(adaptive["execution"]),
            "obligation": json_value(adaptive["obligation"]),
            "budget": json_value(adaptive["budget"]),
            "review_result": json_value(adaptive.get("review_result")),
            "review_binding": json_value(adaptive.get("review_binding")),
        }
    elif contract.handler_id == "delivery.finalize":
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
            "resources": _bound_resources(state, output, snapshot),
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
    declared = _effective_artifact_contract(contract)
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
            drift = ambient_drift(starting_snapshot, current_snapshot, state.repositories)
            raise _error(
                "WORKSPACE_CHANGED",
                "unclaimed ambient drift blocks this repository-dependent action",
                ambient_drift=drift,
                recovery=("restore", "revise-contract", "cancel-with-authority"),
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
        "assurance.dispatch": "assurance-execution",
        "delivery.finalize": "delivery-dossier",
    }.get(contract.handler_id, "action")


def _latest_artifact_body(
    state: TaskState,
    *,
    artifact_type: Optional[str] = None,
    body_field: Optional[str] = None,
) -> Optional[Mapping[str, object]]:
    for artifact in reversed(tuple(artifact_by_record_id(state.records).values())):
        if not isinstance(artifact, Mapping):
            continue
        if artifact_type is not None and artifact.get("type") != artifact_type:
            continue
        body = artifact.get("body")
        if not isinstance(body, Mapping):
            continue
        if body_field is None or isinstance(body.get(body_field), Mapping):
            return body
    return None


def _latest_manifest_snapshot(state: TaskState) -> Optional[Mapping[str, object]]:
    for artifact in reversed(tuple(artifact_by_record_id(state.records).values())):
        if not isinstance(artifact, Mapping):
            continue
        body = artifact.get("body")
        snapshot = artifact.get("snapshot")
        if (
            isinstance(body, Mapping)
            and isinstance(body.get("task_change_manifest"), Mapping)
            and isinstance(snapshot, Mapping)
        ):
            return snapshot
    return None


def _assurance_history(
    state: TaskState,
    plan: Mapping[str, object],
) -> dict:
    """Project same-contract executions and slice-equivalent read-only reuse."""
    def governing_digest(obligation: Mapping[str, object]) -> str:
        ignored = {"schema", "obligation_id", "fingerprint", "task_change_slice"}
        return hashlib.sha256(canonical_json_bytes({
            key: value for key, value in obligation.items() if key not in ignored
        })).hexdigest()

    def slice_map(obligation: Mapping[str, object]) -> dict:
        return {
            (str(item.get("repository_id")), str(item.get("path"))): json_value(item)
            for item in obligation.get("task_change_slice", ())
            if isinstance(item, Mapping)
        }

    def closure_keys(value: object) -> set:
        result = set()
        if isinstance(value, Mapping):
            repository_id = value.get("repository_id")
            path = value.get("path")
            if isinstance(repository_id, str) and isinstance(path, str):
                result.add((repository_id, path))
            for nested in value.values():
                result.update(closure_keys(nested))
        elif isinstance(value, (list, tuple)):
            for nested in value:
                result.update(closure_keys(nested))
        return result

    def resource_binding(snapshot: object) -> Optional[str]:
        if not isinstance(snapshot, Mapping):
            return None
        resources = []
        for member in snapshot.get("repositories", ()):
            member_snapshot = member.get("snapshot") if isinstance(member, Mapping) else None
            if not isinstance(member_snapshot, Mapping):
                return None
            for resource in member_snapshot.get("resources", ()):
                if isinstance(resource, Mapping) and resource.get("role") == "governing":
                    resources.append({
                        "repository_id": member.get("repository_id"),
                        "path": resource.get("path"),
                        "normalizer": resource.get("normalizer"),
                        "kind": resource.get("kind"),
                        "semantic_sha256": resource.get("semantic_sha256"),
                    })
        return hashlib.sha256(canonical_json_bytes(resources)).hexdigest()

    current_by_governing = {
        governing_digest(item): item for item in plan["obligations"]
    }
    current_plan_digest = plan["digest"]
    all_executions = []
    state_executions = []
    reused_obligation_ids = set()
    reuse_decisions = []
    execution_classes = {}
    rework_executions = 0
    governance_mutations = 0
    fixed_mutations = 0
    current_contract_digest = plan["contract_digest"]
    for record in state.records:
        if not isinstance(record, Mapping):
            continue
        record_contract = record.get("contract")
        if (
            not isinstance(record_contract, Mapping)
            or record_contract.get("digest") != current_contract_digest
        ):
            continue
        kind = record.get("kind")
        producer = record.get("producer")
        action_id = (
            producer.get("action_id")
            if isinstance(producer, Mapping)
            else None
        )
        if kind in ("decision", "finding-disposition"):
            governance_mutations += 1
        elif kind == "assurance-execution":
            pass
        elif isinstance(action_id, str) and ".rework." in action_id:
            rework_executions += 1
        elif not (
            isinstance(action_id, str) and action_id.startswith("delivery.finalize.")
        ):
            fixed_mutations += 1
    artifacts = artifact_by_record_id(state.records)
    current_source_artifact = next(
        (
            artifact
            for artifact in reversed(tuple(artifacts.values()))
            if isinstance(artifact, Mapping)
            and isinstance(artifact.get("body"), Mapping)
            and isinstance(artifact["body"].get("task_change_manifest"), Mapping)
            and artifact["body"]["task_change_manifest"].get("digest")
            == plan.get("manifest_digest")
        ),
        None,
    )
    current_resource_binding = resource_binding(
        current_source_artifact.get("snapshot")
        if isinstance(current_source_artifact, Mapping)
        else None
    )
    for record_id, artifact in artifacts.items():
        if not isinstance(artifact, Mapping):
            continue
        body = artifact.get("body")
        if not isinstance(body, Mapping):
            continue
        execution = body.get("assurance_execution")
        recorded_plan = body.get("assurance_plan")
        if (
            not isinstance(execution, Mapping)
            or not isinstance(recorded_plan, Mapping)
            or execution.get("contract_digest") != plan["contract_digest"]
        ):
            continue
        old_obligation = next(
            (
                item
                for item in recorded_plan.get("obligations", ())
                if isinstance(item, Mapping)
                and item.get("obligation_id") == execution.get("obligation_id")
            ),
            None,
        )
        if old_obligation is None:
            raise _error(
                "ASSURANCE_INVALID",
                "recorded execution has no governing obligation",
            )
        all_executions.append(execution)
        execution_classes[str(execution.get("digest", ""))] = old_obligation[
            "budget_class"
        ]
        if execution.get("plan_digest") == current_plan_digest:
            state_executions.append(execution)
            continue
        current = current_by_governing.get(governing_digest(old_obligation))
        reasons = []
        changed_keys = set()
        closure = closure_keys(old_obligation.get("impact_closure"))
        if execution.get("passed") is not True:
            reasons.append("execution-did-not-pass")
        if current is None:
            reasons.append("governing-obligation-changed")
        else:
            old_slice = slice_map(old_obligation)
            new_slice = slice_map(current)
            changed_keys = {
                key for key in set(old_slice) | set(new_slice)
                if old_slice.get(key) != new_slice.get(key)
            }
            if changed_keys:
                if old_obligation.get("kind") in (
                    "integration-check", "independent-review"
                ):
                    reasons.append("reviewed-member-or-edge-slice-changed")
                elif not closure:
                    reasons.append("impact-closure-ambiguous")
                elif changed_keys & closure:
                    reasons.append("task-change-slice-intersects-impact-closure")
                elif old_obligation.get("kind") == "documentation-check" and any(
                    (old_slice.get(key) or new_slice.get(key) or {}).get("classification")
                    == "documentation"
                    for key in changed_keys
                ):
                    reasons.append("documentation-slice-changed")
            old_resource_binding = resource_binding(artifact.get("snapshot"))
            if (
                old_resource_binding is None
                or current_resource_binding is None
                or old_resource_binding != current_resource_binding
            ):
                reasons.append("governing-resources-changed-or-unavailable")
        decision = {
            "execution_record_id": record_id,
            "execution_digest": execution.get("digest"),
            "prior_plan_digest": execution.get("plan_digest"),
            "current_plan_digest": current_plan_digest,
            "prior_obligation_id": old_obligation.get("obligation_id"),
            "current_obligation_id": (
                None if current is None else current.get("obligation_id")
            ),
            "status": "reused" if not reasons else "invalidated",
            "reasons": reasons or ["same-governing-inputs-and-disjoint-slice-delta"],
            "changed_slice": [
                {"repository_id": key[0], "path": key[1]}
                for key in sorted(changed_keys)
            ],
            "impact_closure": [
                {"repository_id": key[0], "path": key[1]}
                for key in sorted(closure)
            ],
            "governing_resource_binding": current_resource_binding,
        }
        reuse_decisions.append(decision)
        if not reasons and current is not None:
            reused_obligation_ids.add(current["obligation_id"])
    return {
        "all_executions": tuple(all_executions),
        "state_executions": tuple(state_executions),
        "reused_obligation_ids": tuple(sorted(reused_obligation_ids)),
        "reuse_decisions": tuple(reuse_decisions),
        "execution_classes": execution_classes,
        "rework_executions": rework_executions,
        "governance_mutations": governance_mutations,
        "fixed_mutations": fixed_mutations,
    }


def _review_finding_context(
    state: TaskState,
    *,
    finding_fingerprint: str,
    plan_digest: Optional[str] = None,
) -> tuple:
    """Locate one immutable structured finding and its governing review."""
    for record in reversed(state.records):
        if not isinstance(record, Mapping):
            continue
        artifact = record.get("artifact")
        body = artifact.get("body") if isinstance(artifact, Mapping) else None
        review_result = body.get("review_result") if isinstance(body, Mapping) else None
        assurance_plan = body.get("assurance_plan") if isinstance(body, Mapping) else None
        if (
            not isinstance(review_result, Mapping)
            or not isinstance(assurance_plan, Mapping)
            or finding_fingerprint not in review_result.get("finding_fingerprints", ())
            or (plan_digest is not None and assurance_plan.get("digest") != plan_digest)
        ):
            continue
        payload = record.get("payload")
        assurance_result = (
            payload.get("assurance_result") if isinstance(payload, Mapping) else None
        )
        review = (
            assurance_result.get("review")
            if isinstance(assurance_result, Mapping)
            else None
        )
        findings = review.get("findings") if isinstance(review, Mapping) else None
        finding = next(
            (
                item
                for item in findings
                if isinstance(item, Mapping)
                and item.get("fingerprint") == finding_fingerprint
            ),
            None,
        ) if isinstance(findings, (list, tuple)) else None
        if finding is None:
            raise _error(
                "REVIEW_INVALID",
                "review result cannot locate its immutable finding content",
            )
        return finding, review_result, assurance_plan
    raise _error(
        "FINDING_DISPOSITION_INVALID",
        "finding is not current in the requested assurance plan",
    )


def _finding_dispositions(
    state: TaskState,
    contract_value: Mapping[str, object],
    *,
    current_only: bool = True,
) -> tuple:
    current_digest = contract_digest(contract_value)
    values = []
    for record in state.records:
        if not isinstance(record, Mapping):
            continue
        payload = record.get("payload")
        disposition = None
        if record.get("kind") == "finding-disposition" and isinstance(payload, Mapping):
            disposition = payload
        elif record.get("kind") == "contract-revision" and isinstance(payload, Mapping):
            disposition = payload.get("finding_disposition")
        if isinstance(disposition, Mapping) and (
            not current_only
            or disposition.get("contract_digest") == current_digest
        ):
            values.append(disposition)
    return tuple(values)


def _dispositioned_review_obligation_ids(
    state: TaskState,
    plan: Mapping[str, object],
) -> tuple:
    dispositions = _finding_dispositions(state, _current_contract(state))
    fingerprints = {
        item["finding_fingerprint"]
        for item in dispositions
        if item.get("plan_digest") == plan.get("digest")
        and item.get("kind") in ("accepted-risk", "confirmed-out-of-scope")
    }
    if not fingerprints:
        return ()
    resolved = []
    for artifact in artifact_by_record_id(state.records).values():
        body = artifact.get("body") if isinstance(artifact, Mapping) else None
        review_result = body.get("review_result") if isinstance(body, Mapping) else None
        recorded_plan = body.get("assurance_plan") if isinstance(body, Mapping) else None
        if (
            not isinstance(review_result, Mapping)
            or not isinstance(recorded_plan, Mapping)
            or recorded_plan.get("digest") != plan.get("digest")
        ):
            continue
        blocking = set(review_result.get("rework_fingerprints", ()))
        blocking.update(review_result.get("triage_fingerprints", ()))
        blocking.update(review_result.get("impact_gap_fingerprints", ()))
        if blocking and blocking.issubset(fingerprints):
            resolved.append(review_result["obligation_id"])
    return tuple(sorted(set(resolved)))


def _adaptive_context(
    state: TaskState,
    definition: WorkflowDefinition,
) -> dict:
    contract_value = _current_contract(state)
    manifest_body = _latest_artifact_body(state, body_field="task_change_manifest")
    impact_body = _latest_artifact_body(state, artifact_type="impact-report")
    if manifest_body is None:
        raise _error("ASSURANCE_BLOCKED", "adaptive assurance requires a current task-change manifest")
    manifest = manifest_body["task_change_manifest"]
    if impact_body is None or not isinstance(impact_body.get("impact_manifest"), Mapping):
        impact = normalize_impact_report(
            {
                "confidence": "unknown",
                "entries": [],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": False,
                "overflow": False,
                "limitations": ["no current bounded impact artifact is available"],
            },
            repositories=state.repositories,
            contract=contract_value,
        )
    else:
        impact = impact_body["impact_manifest"]
    previous_body = _latest_artifact_body(state, body_field="assurance_plan")
    previous_plan = None if previous_body is None else previous_body["assurance_plan"]
    plan = derive_assurance_plan(
        task_id=state.task_id,
        profile=definition.assurance_profile,
        contract=contract_value,
        contract_digest=contract_digest(contract_value),
        repositories=state.repositories,
        manifest=manifest,
        impact=impact,
        previous_plan=previous_plan,
    )
    history = _assurance_history(state, plan)
    waived_subjects = {
        item["subject"]
        for item in decisions_for_contract(state.records, contract_value)
        if item.get("kind") == "assurance-waiver"
    }
    dispositioned_obligation_ids = _dispositioned_review_obligation_ids(state, plan)
    waived_obligation_ids = tuple(sorted(set(
        obligation["obligation_id"]
        for obligation in plan["obligations"]
        if obligation["obligation_id"] in waived_subjects
        or obligation["fingerprint"] in waived_subjects
    ) | set(dispositioned_obligation_ids)))
    selected = next_obligation(
        plan,
        history["state_executions"],
        waived_obligation_ids=waived_obligation_ids,
        reused_obligation_ids=history["reused_obligation_ids"],
    )
    return {
        "plan": plan,
        "manifest": manifest,
        "impact": impact,
        "executions": history["state_executions"],
        "all_executions": history["all_executions"],
        "reused_obligation_ids": history["reused_obligation_ids"],
        "reuse_decisions": history["reuse_decisions"],
        "waived_obligation_ids": waived_obligation_ids,
        "execution_classes": history["execution_classes"],
        "rework_executions": history["rework_executions"],
        "governance_mutations": history["governance_mutations"],
        "fixed_mutations": history["fixed_mutations"],
        "selected": selected,
        "budget": budget_view(
            plan,
            history["all_executions"],
            execution_classes=history["execution_classes"],
            rework_executions=history["rework_executions"],
            governance_mutations=history["governance_mutations"],
            fixed_mutations=history["fixed_mutations"],
        ),
        "states": obligation_states(
            plan,
            history["state_executions"],
            waived_obligation_ids=waived_obligation_ids,
            reused_obligation_ids=history["reused_obligation_ids"],
        ),
    }


def _adaptive_dispatch_finalizer(
    definition: WorkflowDefinition,
    adaptive: Mapping[str, object],
) -> Optional[NodeContract]:
    selected = adaptive["selected"]
    outcome = None
    if selected is None:
        outcome = "success"
    else:
        budget_class = selected["obligation"]["budget_class"]
        class_key = "review" if budget_class == "review" else "verification"
        remaining = adaptive["budget"]["remaining"]
        if remaining[class_key] <= 0 or remaining["total_action"] <= 1:
            outcome = "incomplete"
    if outcome is None:
        return None
    finalizers = [
        item
        for item in definition.nodes.values()
        if item.handler_id == "delivery.finalize"
        and item.finalize_outcome == outcome
    ]
    if len(finalizers) != 1:
        raise _error(
            "WORKFLOW_INVALID",
            "adaptive workflow requires one {} finalizer".format(outcome),
        )
    return finalizers[0]


def _adaptive_execution(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    output: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict:
    context = _adaptive_context(state, definition)
    selected = context["selected"]
    if selected is None:
        raise _error("ASSURANCE_NOT_AVAILABLE", "all current obligations are already discharged")
    obligation = selected["obligation"]
    submitted = output.get("assurance_result")
    if submitted is None:
        evidence = []
        command = output.get("command")
        if isinstance(command, str) and command.strip():
            evidence.append({
                "kind": "command",
                "reference": command,
                "summary": str(output.get("summary", "recorded assurance result")),
            })
        submitted = {
            "obligation_id": obligation["obligation_id"],
            "passed": output.get("passed"),
            "evidence": evidence,
            "limitations": [],
        }
    expected_fields = {"obligation_id", "passed", "evidence", "limitations"}
    if obligation["kind"] == "independent-review":
        expected_fields.add("review")
    if not isinstance(submitted, Mapping) or set(submitted) != expected_fields:
        raise _error("ASSURANCE_EXECUTION_INVALID", "assurance result fields are invalid")
    if submitted.get("obligation_id") != obligation["obligation_id"]:
        raise _error("ASSURANCE_EXECUTION_INVALID", "assurance result names a non-current obligation")
    review_result = None
    review_binding = None
    passed = submitted.get("passed")
    if obligation["kind"] == "independent-review":
        review = submitted.get("review")
        review_fields = {
            "reviewer_available", "independent", "reviewer_digest",
            "review_scope_digest", "guidance_digest", "workspace_digest",
            "findings", "claimed_outcome",
        }
        if not isinstance(review, Mapping) or set(review) != review_fields:
            raise _error("REVIEW_INVALID", "independent review result fields are invalid")
        scope_digest = hashlib.sha256(canonical_json_bytes({
            "plan_digest": context["plan"]["digest"],
            "obligation_fingerprint": obligation["fingerprint"],
            "task_change_slice": obligation["task_change_slice"],
        })).hexdigest()
        guidance_digest = hashlib.sha256(
            canonical_json_bytes(
                {} if contract.driver is None else contract.driver
            )
        ).hexdigest()
        expected_review_bindings = {
            "review_scope_digest": scope_digest,
            "guidance_digest": guidance_digest,
            "workspace_digest": snapshot["digest"],
        }
        if any(review.get(key) != value for key, value in expected_review_bindings.items()):
            raise _error("REVIEW_INVALID", "independent review bindings are stale")
        reviewer_digest = review.get("reviewer_digest")
        if not isinstance(reviewer_digest, str) or len(reviewer_digest) != 64:
            raise _error("REVIEW_INVALID", "reviewer identity digest is invalid")
        review_binding_body = {
            "task_id": state.task_id,
            "contract_digest": context["plan"]["contract_digest"],
            "plan_digest": context["plan"]["digest"],
            "obligation_id": obligation["obligation_id"],
            "obligation_fingerprint": obligation["fingerprint"],
            "manifest_digest": context["manifest"]["digest"],
            "review_scope_digest": scope_digest,
            "guidance_digest": guidance_digest,
            "reviewer_digest": reviewer_digest,
            "workspace_digest": snapshot["digest"],
            "reviewer_available": review.get("reviewer_available") is True,
            "independent": review.get("independent") is True,
        }
        review_binding = {
            **review_binding_body,
            "digest": hashlib.sha256(
                canonical_json_bytes(review_binding_body)
            ).hexdigest(),
        }
        raw_findings = review.get("findings")
        if not isinstance(raw_findings, (list, tuple)):
            raise _error("REVIEW_INVALID", "review findings are invalid")
        findings = [
            validate_finding(
                item,
                task_id=state.task_id,
                contract=_current_contract(state),
                contract_digest=context["plan"]["contract_digest"],
                plan=context["plan"],
                manifest=context["manifest"],
                repository_ids=tuple(item.repository_id for item in state.repositories),
                review_scope_digest=scope_digest,
                guidance_digest=guidance_digest,
                reviewer_digest=reviewer_digest,
                workspace_digest=snapshot["digest"],
            )
            for item in raw_findings
        ]
        review_result = derive_review_result(
            plan=context["plan"],
            review_obligation=obligation,
            findings=findings,
            reviewer_available=review.get("reviewer_available") is True,
            independent=review.get("independent") is True,
            claimed_outcome=review.get("claimed_outcome"),
        )
        passed = review_result["outcome"] == "approved"
        if submitted.get("passed") != passed:
            raise _error(
                "REVIEW_OUTCOME_CONTRADICTORY",
                "submitted pass flag contradicts the controller-derived review outcome",
            )
    execution = validate_assurance_execution(
        {
            "schema": "dev-flow-assurance-execution/0.4.0",
            "plan_digest": context["plan"]["digest"],
            "obligation_id": obligation["obligation_id"],
            "obligation_fingerprint": obligation["fingerprint"],
            "contract_digest": context["plan"]["contract_digest"],
            "manifest_digest": context["plan"]["manifest_digest"],
            "passed": passed,
            "evidence": submitted.get("evidence"),
            "limitations": submitted.get("limitations"),
        },
        plan=context["plan"],
        obligation=obligation,
    )
    executions = (*context["executions"], execution)
    all_executions = (*context["all_executions"], execution)
    execution_classes = {
        **context["execution_classes"],
        execution["digest"]: obligation["budget_class"],
    }
    return {
        **context,
        "obligation": obligation,
        "execution": execution,
        "budget": budget_view(
            context["plan"],
            all_executions,
            execution_classes=execution_classes,
            rework_executions=context["rework_executions"],
            governance_mutations=context["governance_mutations"],
            fixed_mutations=context["fixed_mutations"],
        ),
        "next": next_obligation(
            context["plan"],
            executions,
            waived_obligation_ids=context["waived_obligation_ids"],
            reused_obligation_ids=context["reused_obligation_ids"],
        ),
        "review_result": review_result,
        "review_binding": review_binding,
    }


def _record_for_action(
    state: TaskState,
    definition: WorkflowDefinition,
    contract: NodeContract,
    output: Mapping[str, object],
    binding_value: object,
    snapshot_value: object,
    timestamp: str,
) -> Tuple[Mapping[str, object], dict]:
    snapshot = _validated_snapshot(snapshot_value, state.repositories)
    if contract.handler_id != "preflight" and snapshot_has_unmerged_entries(
        snapshot, state.repositories
    ):
        raise _error(
            "UNMERGED_INDEX_BLOCKED",
            "unmerged index stages block source, assurance, and finalization",
        )
    binding = _validate_binding_for_action(state, contract, binding_value, snapshot)
    contract_value = _current_contract(state)
    adaptive = (
        _adaptive_execution(state, definition, contract, output, snapshot)
        if contract.handler_id == "assurance.dispatch"
        else None
    )
    transition, attempt = _transition_for_action(
        state, contract, output, contract_value
    )
    if adaptive is not None:
        incomplete_finalizers = [
            item
            for item in definition.nodes.values()
            if item.handler_id == "delivery.finalize"
            and item.finalize_outcome == "incomplete"
        ]
        if len(incomplete_finalizers) != 1:
            raise _error(
                "WORKFLOW_INVALID",
                "adaptive workflow requires one incomplete finalizer",
            )
        incomplete_finalizer = incomplete_finalizers[0]
        if adaptive["execution"]["passed"] is True:
            if adaptive["next"] is None:
                finalizers = [
                    item
                    for item in definition.nodes.values()
                    if item.handler_id == "delivery.finalize"
                    and item.finalize_outcome == "success"
                ]
                if len(finalizers) != 1:
                    raise _error("WORKFLOW_INVALID", "adaptive workflow requires one success finalizer")
                transition = {
                    "from": state.current_node,
                    "to": finalizers[0].node_id,
                    "status": "FINALIZING",
                    "route": "assurance-complete",
                }
            else:
                next_class = adaptive["next"]["obligation"]["budget_class"]
                remaining = adaptive["budget"]["remaining"]
                class_key = "review" if next_class == "review" else "verification"
                if remaining[class_key] <= 0 or remaining["total_action"] <= 1:
                    transition = {
                        "from": state.current_node,
                        "to": incomplete_finalizer.node_id,
                        "status": "FINALIZING",
                        "route": "assurance-exhausted",
                    }
                else:
                    transition = {
                        "from": state.current_node,
                        "to": state.current_node,
                        "status": "VERIFYING",
                        "route": "next-obligation",
                    }
        else:
            if (
                adaptive.get("review_result") is not None
                and adaptive["review_result"]["outcome"] == "triage-required"
            ):
                transition = {
                    "from": state.current_node,
                    "to": definition.revision_target,
                    "status": "ANALYZING",
                    "route": (
                        "impact-gap"
                        if adaptive["review_result"]["impact_gap_fingerprints"]
                        else "causal-triage"
                    ),
                }
            else:
                state_after = next(
                    item for item in obligation_states(
                        adaptive["plan"],
                        (*adaptive["executions"], adaptive["execution"]),
                        waived_obligation_ids=adaptive["waived_obligation_ids"],
                        reused_obligation_ids=adaptive["reused_obligation_ids"],
                    )
                    if item["obligation_id"] == adaptive["obligation"]["obligation_id"]
                )
                if (
                    state_after["state"] == "outstanding"
                    and contract.rework is not None
                    and adaptive["budget"]["remaining"]["rework"] > 0
                    and adaptive["budget"]["remaining"]["total_action"] > 1
                ):
                    transition = {
                        "from": state.current_node,
                        "to": contract.rework.failure_node,
                        "status": contract.rework.failure_status,
                        "route": "finding-bound-rework" if adaptive["obligation"]["kind"] == "independent-review" else "assurance-rework",
                    }
                elif contract.rework is not None:
                    transition = {
                        "from": state.current_node,
                        "to": contract.rework.exhausted_node,
                        "status": contract.rework.exhausted_status,
                        "route": "assurance-exhausted",
                    }
    producer = _producer(contract, attempt, output)
    artifact = _artifact_for_action(
        state,
        contract,
        output,
        binding,
        snapshot,
        contract_value,
        producer,
        adaptive,
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
    for contract in definition.nodes.values():
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
    ownership_claims: Optional[Mapping[str, object]],
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
    current_snapshot = _validated_snapshot(snapshot, state.repositories)
    accepted_snapshot = _latest_manifest_snapshot(state)
    if accepted_snapshot is None:
        raise _error(
            "CAPSULE_INVALID",
            "contract revision cannot locate the accepted source snapshot",
        )
    reconciliation_claims = (
        {"schema": TASK_CHANGE_CLAIMS_SCHEMA, "claims": []}
        if ownership_claims is None
        else ownership_claims
    )
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
    baseline_body = next(
        (
            artifact.get("body")
            for artifact in artifact_by_record_id(state.records).values()
            if isinstance(artifact, Mapping)
            and artifact.get("type") == "repository-baseline"
            and isinstance(artifact.get("body"), Mapping)
        ),
        None,
    )
    manifest_body = _latest_artifact_body(state, body_field="task_change_manifest")
    if baseline_body is None or manifest_body is None:
        raise _error("CAPSULE_INVALID", "contract revision cannot locate the current capsule")
    rolled_manifest = derive_manifest(
        task_id=state.task_id,
        contract=validated,
        contract_digest=new_contract_digest,
        repositories=state.repositories,
        preflight=baseline_body["preflight_baseline"],
        predecessor=manifest_body["task_change_manifest"],
        before_snapshot=accepted_snapshot,
        after_snapshot=current_snapshot,
        claims=reconciliation_claims,
        producer={
            "action_id": "contract.revise",
            "task_revision": state.revision + 1,
            "contract_revision": validated["revision"],
            "binding_digest": hashlib.sha256(canonical_json_bytes({
                "previous_contract_digest": previous_contract_digest,
                "new_contract_digest": new_contract_digest,
                "snapshot_digest": current_snapshot["digest"],
            })).hexdigest(),
        },
        reconcile_existing=True,
    )
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
            "body": {
                "reason": clean_reason,
                "actor_label": clean_actor,
                "revision_interval": {
                    "accepted_snapshot_digest": accepted_snapshot["digest"],
                    "revision_snapshot_digest": current_snapshot["digest"],
                },
                "adoption_claims": json_value(reconciliation_claims),
                "task_change_manifest": rolled_manifest,
            },
        }
    )
    payload = {
        "new_contract": json_value(validated),
        "previous_contract_digest": previous_contract_digest,
        "new_contract_digest": new_contract_digest,
        "reason": clean_reason,
        "actor_label": clean_actor,
        "ownership_claims": json_value(reconciliation_claims),
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
        adaptive = _adaptive_context(state, definition)
        review_obligation = next(
            (
                obligation
                for obligation in adaptive["plan"]["obligations"]
                if obligation["kind"] == "independent-review"
                and validated["subject"]
                in (obligation["obligation_id"], obligation["fingerprint"])
            ),
            None,
        )
        if review_obligation is None:
            raise _error(
                "DECISION_INVALID",
                "assurance waiver subject must be the current independent-review obligation",
            )
        unavailable_recorded = any(
            isinstance(artifact, Mapping)
            and isinstance(artifact.get("body"), Mapping)
            and isinstance(artifact["body"].get("assurance_execution"), Mapping)
            and artifact["body"]["assurance_execution"].get("plan_digest")
            == adaptive["plan"]["digest"]
            and artifact["body"]["assurance_execution"].get("obligation_id")
            == review_obligation["obligation_id"]
            and isinstance(artifact["body"].get("review_result"), Mapping)
            and artifact["body"]["review_result"].get("outcome") == "unavailable"
            for artifact in artifact_by_record_id(state.records).values()
        )
        if not unavailable_recorded:
            raise _error(
                "DECISION_INVALID",
                "independent-review waiver requires a current unavailable review execution",
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


def record_finding_disposition(
    state: TaskState,
    definition: WorkflowDefinition,
    *,
    disposition: Mapping[str, object],
    actor_authorized: bool,
    snapshot: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    """Record one CAS-bound finding disposition, optionally expanding scope."""
    if state.revision == 0 or not state.records or state.records[0].get("kind") != "preflight":
        raise _error(
            "PREFLIGHT_REQUIRED",
            "finding dispositions are available only after repository preflight",
        )
    if is_terminal_state(state, definition):
        raise _error("ACTION_NOT_AVAILABLE", "terminal task cannot dispose a finding")
    submitted = dict(disposition)
    submitted.pop("digest", None)
    fingerprint = submitted.get("finding_fingerprint")
    if not isinstance(fingerprint, str):
        raise _error("FINDING_DISPOSITION_INVALID", "finding fingerprint is invalid")
    contract_value = _current_contract(state)
    if any(
        item.get("finding_fingerprint") == fingerprint
        for item in _finding_dispositions(state, contract_value, current_only=True)
    ):
        raise _error(
            "FINDING_DISPOSITION_INVALID",
            "finding already has a current-contract disposition",
            finding_fingerprint=fingerprint,
        )
    plan_digest = submitted.get("plan_digest")
    finding, review_result, plan = _review_finding_context(
        state,
        finding_fingerprint=fingerprint,
        plan_digest=plan_digest if isinstance(plan_digest, str) else None,
    )
    validated = validate_disposition(
        submitted,
        task_id=state.task_id,
        contract_digest=contract_digest(contract_value),
        plan_digest=plan["digest"],
        review_digest=review_result["digest"],
        finding_fingerprint_value=fingerprint,
        expected_revision=state.revision,
        current_revision=state.revision,
        actor_authorized=actor_authorized,
    )
    relation = finding.get("causal_relation")
    if validated["kind"] == "accepted-risk" and not (
        finding.get("blocking") is True
        and relation in ("introduced", "affected", "unknown")
    ):
        raise _error(
            "FINDING_DISPOSITION_INVALID",
            "accepted risk requires one blocking causal or unresolved finding",
        )
    if validated["kind"] == "confirmed-out-of-scope" and relation not in (
        "out-of-scope", "unknown"
    ):
        raise _error(
            "FINDING_DISPOSITION_INVALID",
            "out-of-scope confirmation requires an out-of-scope or unknown finding",
        )
    if validated["kind"] == "expand-contract":
        if snapshot is None:
            raise _error(
                "FINDING_DISPOSITION_INVALID",
                "contract expansion requires a current repository snapshot",
            )
        revised = revise_contract(
            state,
            definition,
            new_contract=validated["next_contract"],
            ownership_claims=None,
            reason=validated["rationale"],
            actor_label=validated["actor"],
            snapshot=snapshot,
            timestamp=timestamp,
        )
        revision_record = dict(revised.records[-1])
        revision_record["payload"] = {
            **dict(revision_record["payload"]),
            "finding_disposition": json_value(validated),
        }
        revision_record.pop("digest", None)
        revision_record.pop("record_id", None)
        sealed = seal_record(revision_record)
        return replace(revised, records=(*state.records, sealed))
    producer = {
        "kind": "finding-disposition",
        "actor_label": validated["actor"],
    }
    dispatch_nodes = [
        item
        for item in definition.nodes.values()
        if item.handler_id == "assurance.dispatch"
    ]
    if len(dispatch_nodes) != 1:
        raise _error(
            "WORKFLOW_INVALID",
            "finding dispositions require one adaptive assurance dispatch node",
        )
    transition = {
        "from": state.current_node,
        "to": dispatch_nodes[0].node_id,
        "status": "VERIFYING",
        "route": "finding-disposition",
    }
    record = seal_record(
        {
            "kind": "finding-disposition",
            "task_revision": state.revision + 1,
            "timestamp": timestamp,
            "producer": producer,
            "payload": json_value(validated),
            "contract": {
                "revision": contract_value["revision"],
                "digest": contract_digest(contract_value),
            },
            "transition": transition,
            "snapshot": None,
            "artifact": None,
            "binding": None,
        }
    )
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        status=transition["status"],
        current_node=transition["to"],
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
        producer = record.get("producer")
        entry_cancel = definition.cancel_for(definition.entry_node)
        is_entry_cancel = (
            kind == "action"
            and entry_cancel is not None
            and isinstance(producer, Mapping)
            and producer.get("action_id") == entry_cancel.action_id
            and producer.get("node_id") == entry_cancel.node_id
        )
        if index == 1 and kind != "preflight" and not is_entry_cancel:
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
        elif kind == "finding-disposition":
            if index == 1:
                raise _state_invalid("finding_disposition_before_preflight")
            try:
                candidate = record_finding_disposition(
                    replay,
                    definition,
                    disposition=record.get("payload"),
                    actor_authorized=True,
                    snapshot=None,
                    timestamp=record["timestamp"],
                )
            except DevFlowError as exc:
                raise _state_invalid(
                    "finding_disposition_replay_failed",
                    cause=exc.code,
                    cause_details=exc.details,
                ) from exc
        elif kind == "contract-revision":
            payload = record.get("payload")
            base_revision_fields = {
                "new_contract",
                "previous_contract_digest",
                "new_contract_digest",
                "reason",
                "actor_label",
                "ownership_claims",
            }
            if not isinstance(payload, Mapping) or set(payload) not in (
                base_revision_fields,
                base_revision_fields | {"finding_disposition"},
            ):
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
                if "finding_disposition" in payload:
                    candidate = record_finding_disposition(
                        replay,
                        definition,
                        disposition=payload["finding_disposition"],
                        actor_authorized=True,
                        snapshot=record.get("snapshot"),
                        timestamp=record["timestamp"],
                    )
                else:
                    candidate = revise_contract(
                        replay,
                        definition,
                        new_contract=payload["new_contract"],
                        ownership_claims=payload["ownership_claims"],
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
        elif kind in (
            "preflight", "action", "verification", "review",
            "assurance-execution", "delivery-dossier",
        ):
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
        "workflow_identity",
        "repositories",
        "original_contract",
        "version",
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
    freshness: Optional[Mapping[str, object]],
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
        current = (
            None
            if freshness is None
            else freshness.get(str(record.get("record_id")), {})
        )
        summary = {
            "record_id": record.get("record_id"),
            "digest": artifact.get("digest"),
            "outcome": body.get("outcome") if isinstance(body, Mapping) else None,
            "coverage": counts,
            "current": None if current is None else current.get("current", False),
            "stale_reasons": [] if current is None else current.get("reasons", []),
        }
        if isinstance(body, Mapping):
            repository_set = body.get("repository_set")
            summary["schema"] = body.get("schema")
            summary["repository_set_id"] = (
                repository_set.get("id")
                if isinstance(repository_set, Mapping)
                else None
            )
        return summary
    return None


def _latest_review_projection(
    state: TaskState,
    contract_value: Mapping[str, object],
) -> Optional[dict]:
    current_digest = contract_digest(contract_value)
    for record in reversed(state.records):
        if not isinstance(record, Mapping):
            continue
        record_contract = record.get("contract")
        artifact = record.get("artifact")
        body = artifact.get("body") if isinstance(artifact, Mapping) else None
        review_result = body.get("review_result") if isinstance(body, Mapping) else None
        if (
            isinstance(record_contract, Mapping)
            and record_contract.get("digest") == current_digest
            and isinstance(review_result, Mapping)
        ):
            return {
                "digest": review_result.get("digest"),
                "outcome": review_result.get("outcome"),
                "binding": json_value(body.get("review_binding")),
                "finding_fingerprints": json_value(
                    review_result.get("finding_fingerprints", [])
                ),
                "rework_fingerprints": json_value(
                    review_result.get("rework_fingerprints", [])
                ),
                "triage_fingerprints": json_value(
                    review_result.get("triage_fingerprints", [])
                ),
                "impact_gap_fingerprints": json_value(
                    review_result.get("impact_gap_fingerprints", [])
                ),
            }
    return None


def agent_projection(
    state: TaskState,
    definition: WorkflowDefinition,
    current_snapshot: Mapping[str, object],
) -> dict:
    """Return one compact action plus its canonical provenance binding."""
    snapshot = _validated_snapshot(current_snapshot, state.repositories)
    contract_value = _current_contract(state)
    freshness = artifact_freshness(state.records, contract_value, snapshot)
    review_projection = _latest_review_projection(state, contract_value)
    terminal = is_terminal_state(state, definition)
    action = None
    if not terminal:
        node = current_node_contract(state, definition)
        adaptive_projection = None
        if node.handler_id == "assurance.dispatch" or ".rework." in node.action_id:
            adaptive_projection = _adaptive_context(state, definition)
            finalizer = _adaptive_dispatch_finalizer(
                definition,
                adaptive_projection,
            )
            if finalizer is not None and (
                node.handler_id == "assurance.dispatch"
                or finalizer.finalize_outcome == "success"
            ):
                node = finalizer
        declared = _effective_artifact_contract(node)
        blocked = None
        try:
            inputs = resolve_inputs(
                state.records,
                contract_value,
                () if declared is None else declared.inputs,
                snapshot,
                allow_revision_source=int(contract_value["revision"]) > 1,
            )
            binding_snapshot = snapshot
            if (
                declared is not None
                and declared.workspace_role == "produces-source"
                and node.handler_id != "preflight"
            ):
                predecessor = next(
                    (item for item in inputs if item.get("edge") == "source-predecessor"),
                    None,
                )
                artifacts = artifact_by_record_id(state.records)
                predecessor_artifact = (
                    None
                    if predecessor is None
                    else artifacts.get(predecessor.get("record_id"))
                )
                predecessor_snapshot = (
                    predecessor_artifact.get("snapshot")
                    if isinstance(predecessor_artifact, Mapping)
                    else None
                )
                if not isinstance(predecessor_snapshot, Mapping):
                    raise _error(
                        "ARTIFACT_INPUT_MISSING",
                        "source predecessor snapshot is unavailable",
                    )
                drift = ambient_drift(
                    predecessor_snapshot,
                    snapshot,
                    state.repositories,
                )
                if drift["present"]:
                    raise _error(
                        "AMBIENT_DRIFT",
                        "unclaimed ambient drift blocks source production",
                        ambient_drift=drift,
                        recovery=("restore", "revise-contract", "cancel-with-authority"),
                    )
                binding_snapshot = predecessor_snapshot
            binding = make_action_binding(
                task_id=state.task_id,
                revision=state.revision,
                action_id=node.action_id,
                node_id=node.node_id,
                contract=contract_value,
                inputs=inputs,
                current_snapshot=binding_snapshot,
            )
        except DevFlowError as exc:
            if exc.code not in ("ARTIFACT_INPUT_MISSING", "AMBIENT_DRIFT"):
                raise
            inputs = ()
            binding = None
            blocked = {
                "code": exc.code,
                "message": exc.message,
                "details": dict(exc.details),
            }
        if (
            node.handler_id == "delivery.finalize"
            and node.finalize_outcome == "success"
        ):
            accepted_snapshot = _latest_manifest_snapshot(state)
            if accepted_snapshot is None:
                raise _error(
                    "ASSURANCE_BLOCKED",
                    "completed assurance has no accepted task-change snapshot",
                )
            drift = ambient_drift(accepted_snapshot, snapshot, state.repositories)
            if drift["present"]:
                inputs = ()
                binding = None
                blocked = {
                    "code": "AMBIENT_DRIFT",
                    "message": "unclaimed ambient drift blocks successful finalization",
                    "details": {
                        "ambient_drift": drift,
                        "recovery": [
                            "restore",
                            "revise-contract",
                            "cancel-with-authority",
                        ],
                    },
                }
        retry = None
        retry_owner = node if node.rework is not None else None
        if retry_owner is None:
            rework_sources = [
                candidate
                for candidate in definition.nodes.values()
                if candidate.rework is not None
                and candidate.rework.failure_node == state.current_node
            ]
            if len(rework_sources) == 1:
                retry_owner = rework_sources[0]
        if retry_owner is not None and retry_owner.rework is not None:
            used = assurance_attempts(
                state.records,
                retry_owner.node_id,
                contract_value,
            )
            retry = {
                "attempts_used": used,
                "max_attempts": retry_owner.rework.max_attempts,
                "remaining": max(0, retry_owner.rework.max_attempts - used),
            }
        action = {
            **node.as_dict(),
            "inputs": [json_value(item) for item in inputs],
            "binding": None if binding is None else json_value(binding),
            "blocked": blocked,
            "retry_budget": retry,
        }
        if review_projection is not None:
            action["review_state"] = json_value(review_projection)
        if node.handler_id == "assurance.dispatch":
            adaptive = adaptive_projection
            selected = adaptive["selected"]
            action["current_obligation"] = json_value(selected["obligation"])
            action["task_change_slice"] = json_value(
                selected["obligation"]["task_change_slice"]
            )
            action["assurance"] = {
                "policy": adaptive["plan"]["policy"],
                "profile": adaptive["plan"]["profile"],
                "plan_id": adaptive["plan"]["plan_id"],
                "plan_digest": adaptive["plan"]["digest"],
                "confidence": adaptive["plan"]["confidence"],
                "obligation_states": json_value(adaptive["states"]),
                "budget": json_value(adaptive["budget"]),
                "maximum_remaining_actions": adaptive["budget"]["maximum_remaining_actions"],
                "not_required": json_value(adaptive["plan"]["not_required"]),
                "reuse_decisions": json_value(adaptive["reuse_decisions"]),
            }
            action["retry_budget"] = selected["state"]
            if selected["obligation"]["kind"] == "independent-review":
                action["review_contract"] = {
                    "review_scope_digest": hashlib.sha256(canonical_json_bytes({
                        "plan_digest": adaptive["plan"]["digest"],
                        "obligation_fingerprint": selected["obligation"]["fingerprint"],
                        "task_change_slice": selected["obligation"]["task_change_slice"],
                    })).hexdigest(),
                    "guidance_digest": hashlib.sha256(canonical_json_bytes(
                        {} if node.driver is None else node.driver
                    )).hexdigest(),
                    "workspace_digest": snapshot["digest"],
                    "manifest_digest": adaptive["manifest"]["digest"],
                    "contract_digest": adaptive["plan"]["contract_digest"],
                    "finding_schema": "dev-flow-review-finding/0.4.0",
                    "causal_relations": [
                        "introduced", "affected", "pre-existing",
                        "out-of-scope", "unknown",
                    ],
                    "agent_verdict_is_authority": False,
                }
    base = {
        "schema": AGENT_PROTOCOL_SCHEMA,
        "task_id": state.task_id,
        "revision": state.revision,
        "workflow": {
            "id": state.workflow_id,
            "version": state.workflow_version,
            "schema": state.workflow_schema,
            "identity": state.workflow_identity,
        },
        "status": state.status,
        "current_node": state.current_node,
        "contract": contract_summary(contract_value),
        "repository_set": {
            "id": state.repository_set_id,
            "digest": snapshot.get("digest"),
            "repositories": [
                {
                    "id": repository.repository_id,
                    "path": repository.path,
                    "snapshot": {
                        key: json_value(
                            repository_snapshot(
                                snapshot,
                                state.repositories,
                                repository.repository_id,
                            ).get(key)
                        )
                        for key in (
                            "digest",
                            "head",
                            "branch",
                            "clean",
                            "status_sha256",
                            "status_bytes",
                            "object_format",
                            "index_entry_count",
                            "index_output_bytes",
                            "has_unmerged_entries",
                            "git_worktree_dir",
                            "git_common_dir",
                        )
                    },
                }
                for repository in state.repositories
            ],
        },
        "freshness": freshness,
        "review": review_projection,
        "action": action,
        "dossier": _dossier_summary(state, contract_value, freshness),
        "done": terminal,
    }
    if action is not None and current_node_contract(
        state, definition
    ).handler_id == "verification.record":
        action["verification_coverage"] = {
            "schema": VERIFICATION_COVERAGE_SCHEMA,
            "fields": ["schema", "criteria", "repositories", "integration"],
            "criterion_ids": sorted(
                item["id"] for item in contract_value["acceptance_criteria"]
            ),
            "repository_ids": [
                repository.repository_id for repository in state.repositories
            ],
            "result_fields": ["command", "passed"],
            "command_rule": "top-level command equals integration command",
            "passed_rule": "top-level passed equals all repository and integration results",
        }
    return base


def task_view(
    state: TaskState,
    definition: WorkflowDefinition,
    current_snapshot: Optional[Mapping[str, object]],
    *,
    snapshot_error: Optional[Mapping[str, object]] = None,
) -> dict:
    """Full read-only state and derived delivery view for explicit inspection."""
    snapshot = (
        None
        if current_snapshot is None
        else _validated_snapshot(current_snapshot, state.repositories)
    )
    contract_value = _current_contract(state)
    freshness = (
        None
        if snapshot is None
        else artifact_freshness(state.records, contract_value, snapshot)
    )
    return {
        **state.as_dict(),
        "effective_contract": json_value(contract_value),
        "effective_contract_digest": contract_digest(contract_value),
        "current_snapshot": None if snapshot is None else json_value(snapshot),
        "snapshot_error": json_value(snapshot_error),
        "artifact_freshness": freshness,
        "dossier": _dossier_summary(state, contract_value, freshness),
        "terminal": is_terminal_state(state, definition),
    }


def current_resource_requests(state: TaskState) -> tuple:
    """Resources required for a current snapshot without mutating state."""
    return governing_resource_requests(state.records, _current_contract(state))
