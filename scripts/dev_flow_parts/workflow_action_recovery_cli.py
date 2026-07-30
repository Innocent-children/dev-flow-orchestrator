# Loaded by scripts/dev_flow.py into its shared module namespace.
# Responsibility: isolated CLI projection for schema-v4 action quarantine
# inspection, preview, reconciliation, and lost-response recovery.
from __future__ import annotations

import contextlib as _action_recovery_contextlib
import copy as _action_recovery_copy
import hashlib as _action_recovery_hashlib
import hmac as _action_recovery_hmac
import json as _action_recovery_json
import os as _action_recovery_os
import stat as _action_recovery_stat
import time as _action_recovery_time
from dataclasses import replace as _action_recovery_replace
from pathlib import Path as _ActionRecoveryPath
from pathlib import PurePosixPath as _ActionRecoveryPurePosixPath
from typing import Mapping as _ActionRecoveryMapping


_ACTION_RECOVERY_EVIDENCE_SCHEMA = (
    "dev-flow-v4-action-reconciliation-evidence/v1"
)
_ACTION_RECOVERY_RESULT_SCHEMA = (
    "dev-flow-v4-action-reconciliation-cli-result/v1"
)
_ACTION_RECOVERY_RESULT_SCHEMA_V4 = (
    "dev-flow-v4-action-reconciliation-cli-result/v1"
)
_ACTION_RECOVERY_OPERATOR_INTERVENTION_SCHEMA = (
    "dev-flow-v4-operator-intervention/v1"
)
_ACTION_RECOVERY_OPERATOR_INTERVENTION_REASON = (
    "TRUSTED_HOST_AUTHORITY_UNAVAILABLE"
)
_ACTION_RECOVERY_INSPECT_SCHEMA = (
    "dev-flow-v4-action-reconciliation-inspect/v1"
)
_ACTION_RECOVERY_PREVIEW_SCHEMA = (
    "dev-flow-v4-action-reconciliation-preview/v1"
)
_ACTION_RECOVERY_PREVIEW_DOMAIN = (
    b"dev-flow-v4-action-reconciliation-cli-preview-v1\x00"
)
_ACTION_RECOVERY_GATE_DOMAIN = (
    b"dev-flow-v4-action-reconciliation-cli-gate-v1\x00"
)
_ACTION_RECOVERY_COMPENSATION_FILE_ACTION = (
    "recovery.compensate.controller-file-remove/v1"
)
_ACTION_RECOVERY_COMPENSATION_CONTRACT_DOMAIN = (
    b"dev-flow-v4-controller-file-compensation-contract-v1\x00"
)
_ACTION_RECOVERY_COMPENSATION_RECEIPT_DOMAIN = (
    b"dev-flow-v4-controller-file-compensation-receipt-v1\x00"
)
_ACTION_RECOVERY_COMPENSATION_POSTCONDITION_DOMAIN = (
    b"dev-flow-v4-controller-file-compensation-postcondition-v1\x00"
)
_ACTION_RECOVERY_UNRESOLVED_AUTHORITY_DOMAIN = (
    b"dev-flow-v4-action-recovery-authority-unavailable-v1\x00"
)
_ACTION_RECOVERY_EXTERNAL_GATE_DOMAIN = (
    b"dev-flow-v4-action-recovery-external-write-gate-v1\x00"
)
_ACTION_RECOVERY_MAX_RECORD_BYTES = 16 * 1024 * 1024
_ACTION_RECOVERY_MAX_OPERATOR_INTERVENTION_BYTES = 4 * 1024

# These callbacks are installed only by the package/controller composition.
# CLI JSON cannot name, enable, or synthesize either authority.
_ACTION_RECOVERY_LIVE_ABANDONMENT_OBSERVER_V4 = None
_ACTION_RECOVERY_HOST_APPROVAL_CALLBACK_V4 = None


def _action_recovery_error(
    code: str,
    message: str,
    *,
    details: _ActionRecoveryMapping[str, object] | None = None,
) -> FlowError:
    return FlowError(code, message, details=dict(details or {}))


def _action_recovery_json_object(
    value: object,
    *,
    role: str,
    exact_fields: frozenset[str] | None = None,
) -> dict[str, object]:
    if not isinstance(value, _ActionRecoveryMapping):
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            f"{role} must be a JSON object",
        )
    result = _action_recovery_copy.deepcopy(dict(value))
    try:
        semantic_json_bytes(result)
    except Exception as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            f"{role} must be strict semantic JSON",
        ) from exc
    if exact_fields is not None and set(result) != set(exact_fields):
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            f"{role} has unknown or missing fields",
            details={
                "expected": sorted(exact_fields),
                "actual": sorted(result),
            },
        )
    return result


def _action_recovery_digest(value: object, role: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            f"{role} must be lowercase SHA-256",
        )
    return value


def _action_recovery_evidence(args: object) -> dict[str, object]:
    try:
        parsed = _action_recovery_json.loads(args.evidence_json)
    except (
        TypeError,
        ValueError,
        UnicodeError,
        _action_recovery_json.JSONDecodeError,
    ) as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            "--evidence-json is not valid JSON",
        ) from exc
    evidence = _action_recovery_json_object(
        parsed, role="reconciliation evidence"
    )
    if evidence.get("schema") != _ACTION_RECOVERY_EVIDENCE_SCHEMA:
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            "reconciliation evidence uses an unsupported schema",
        )
    outcome = str(args.outcome).upper()
    common = {"schema", "outcome"}
    if evidence.get("outcome") != outcome:
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            "evidence outcome does not match --outcome",
        )
    expected = {
        "ACCEPTED": common
        | {"postcondition_evidence_sha256", "invocation"},
        "ABANDONED": common,
        "COMPENSATED": common
        | {
            "compensation_execution_id",
            "compensation_plan",
        },
    }[outcome]
    if set(evidence) != expected:
        raise _action_recovery_error(
            "ACTION_RECOVERY_EVIDENCE_INVALID",
            "reconciliation evidence has unknown or missing fields",
            details={
                "expected": sorted(expected),
                "actual": sorted(evidence),
            },
        )
    for field_name in (
        "postcondition_evidence_sha256",
        "quiescence_evidence_sha256",
        "no_business_outcome_evidence_sha256",
    ):
        if field_name in evidence:
            _action_recovery_digest(
                evidence[field_name], field_name
            )
    return evidence


def _action_recovery_record(path: _ActionRecoveryPath) -> dict[str, object]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(_ACTION_RECOVERY_MAX_RECORD_BYTES + 1)
    except OSError as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_MISSING",
            "action recovery record is unavailable",
            details={"path": str(path)},
        ) from exc
    if len(raw) > _ACTION_RECOVERY_MAX_RECORD_BYTES:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RECORD_BOUNDED",
            "action recovery record exceeds the inspection bound",
        )
    try:
        value = _action_recovery_json.loads(raw)
    except (
        ValueError,
        UnicodeError,
        _action_recovery_json.JSONDecodeError,
    ) as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RECORD_INVALID",
            "action recovery record is not canonical JSON",
        ) from exc
    if not isinstance(value, dict):
        raise _action_recovery_error(
            "ACTION_RECOVERY_RECORD_INVALID",
            "action recovery record must be an object",
        )
    return value


def _action_recovery_untrusted_target(
    task_dir: _ActionRecoveryPath,
    execution_id: str,
) -> tuple[dict[str, object], dict[str, object], str]:
    active = task_dir / action_execution_active_path(execution_id)
    archived = task_dir / action_execution_archive_path(execution_id)
    path = active if active.is_file() else archived
    journal = _action_recovery_record(path)
    try:
        normalized = normalize_journal(journal)
    except Exception as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RECORD_INVALID",
            "action recovery journal does not satisfy its strict schema",
        ) from exc
    index_path = task_dir / ACTION_EXECUTION_INDEX_PATH
    if index_path.is_file():
        try:
            index = normalize_index(
                _action_recovery_record(index_path)
            )
        except Exception as exc:
            raise _action_recovery_error(
                "ACTION_RECOVERY_RECORD_INVALID",
                "action execution index does not satisfy its strict schema",
            ) from exc
    else:
        index = seal_index(
            {
                "schema": ACTION_EXECUTION_INDEX_SCHEMA,
                "task_id": str(normalized["task_id"]),
                "revision": 0,
                "entries": [],
            }
        )
    return index, normalized, str(path)


def _action_recovery_preview_document(
    *,
    task_id: str,
    execution_id: str,
    attempt_id: str,
    outcome: str,
    expected_revision: int,
    evidence: dict[str, object],
    index: dict[str, object],
    target: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": _ACTION_RECOVERY_PREVIEW_SCHEMA,
        "task_id": task_id,
        "target_execution_id": execution_id,
        "attempt_id": attempt_id,
        "outcome": outcome,
        "expected_revision": expected_revision,
        "evidence_sha256": _action_recovery_hashlib.sha256(
            semantic_json_bytes(evidence)
        ).hexdigest(),
        "expected_index_revision": index["revision"],
        "expected_index_sha256": index["record_sha256"],
        "expected_journal_revision": target["revision"],
        "expected_journal_sha256": target["record_sha256"],
    }


def _action_recovery_preview_token(document: object) -> str:
    return "action-recovery-preview:" + _action_recovery_hashlib.sha256(
        _ACTION_RECOVERY_PREVIEW_DOMAIN + semantic_json_bytes(document)
    ).hexdigest()


def _action_recovery_gate_sha256(preview_token: str) -> str:
    return _action_recovery_hashlib.sha256(
        _ACTION_RECOVERY_GATE_DOMAIN + preview_token.encode("utf-8")
    ).hexdigest()


def workflow_action_recovery_inspect_v1(
    args: object,
) -> dict[str, object]:
    task_id = _task_arg(args)
    task_dir = _task_dir(task_id, args.data_dir)
    index, target, path = _action_recovery_untrusted_target(
        task_dir, args.execution_id
    )
    bindings = target.get("bindings")
    return {
        "schema": _ACTION_RECOVERY_INSPECT_SCHEMA,
        "task_id": task_id,
        "target_execution_id": target.get("execution_id"),
        "phase": target.get("phase"),
        "journal_revision": target.get("revision"),
        "journal_record_sha256": target.get("record_sha256"),
        "index_revision": index.get("revision"),
        "index_record_sha256": index.get("record_sha256"),
        "receipt_available": isinstance(target.get("receipt"), dict),
        "quarantine": _workflow_transition_public(
            target.get("quarantine")
        ),
        "effect_ids": [
            effect.get("effect_id")
            for effect in target.get("effects", ())
            if isinstance(effect, _ActionRecoveryMapping)
        ],
        "workflow_bundle_sha256": (
            bindings.get("workflow_bundle_sha256")
            if isinstance(bindings, _ActionRecoveryMapping)
            else None
        ),
        "record_path": path,
        "authenticated": False,
        "authority": "discovery-only",
    }


def workflow_action_recovery_preview_v1(
    args: object,
) -> dict[str, object]:
    task_id = _task_arg(args)
    state = load_state(task_id, args.data_dir)
    _check_revision(state, args.expected_revision)
    evidence = _action_recovery_evidence(args)
    task_dir = _task_dir(task_id, args.data_dir)
    index, target, _path = _action_recovery_untrusted_target(
        task_dir, args.execution_id
    )
    if target.get("task_id") != task_id:
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_MISMATCH",
            "target journal belongs to another task",
        )
    if target.get("phase") != "QUARANTINED":
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_NOT_QUARANTINED",
            "action recovery preview requires a quarantined execution",
            details={"phase": target.get("phase")},
        )
    document = _action_recovery_preview_document(
        task_id=task_id,
        execution_id=args.execution_id,
        attempt_id=args.attempt_id,
        outcome=str(args.outcome).upper(),
        expected_revision=args.expected_revision,
        evidence=evidence,
        index=index,
        target=target,
    )
    return {
        **document,
        "confirm_preview": _action_recovery_preview_token(document),
        "authenticated": False,
        "authority": "discovery-only",
        "target_dispatcher_invocations": 0,
    }


def _action_recovery_audit_facts(
    values: object,
    *,
    role: str,
) -> tuple[AuditFact, ...]:
    if not isinstance(values, list):
        raise _action_recovery_error(
            "ACTION_RECOVERY_INVOCATION_INVALID",
            f"{role} must be a list",
        )
    result = []
    for index, value in enumerate(values):
        item = _action_recovery_json_object(
            value,
            role=f"{role}[{index}]",
            exact_fields=frozenset({"fact_type", "payload"}),
        )
        result.append(
            AuditFact(
                str(item["fact_type"]),
                _action_recovery_json_object(
                    item["payload"],
                    role=f"{role}[{index}].payload",
                ),
            )
        )
    return tuple(result)


def _action_recovery_action_outcome(
    value: object,
) -> ActionOutcome:
    item = _action_recovery_json_object(
        value,
        role="invocation.action_outcome",
        exact_fields=frozenset(
            {
                "action_id",
                "proposed_edge_id",
                "evidence_records",
                "proposed_state_delta",
                "audit_facts",
                "external_postconditions",
            }
        ),
    )
    if not isinstance(item["evidence_records"], list) or not isinstance(
        item["external_postconditions"], list
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_INVOCATION_INVALID",
            "action outcome evidence and postconditions must be lists",
        )
    return ActionOutcome(
        str(item["action_id"]),
        str(item["proposed_edge_id"]),
        evidence_records=tuple(
            _action_recovery_json_object(
                record, role="action outcome evidence"
            )
            for record in item["evidence_records"]
        ),
        proposed_state_delta=_action_recovery_json_object(
            item["proposed_state_delta"],
            role="action outcome state delta",
        ),
        audit_facts=_action_recovery_audit_facts(
            item["audit_facts"], role="action outcome audit facts"
        ),
        external_postconditions=tuple(
            _action_recovery_json_object(
                record, role="action outcome postcondition"
            )
            for record in item["external_postconditions"]
        ),
    )


def _action_recovery_approval_outcome(
    value: object,
) -> ApprovalOutcome | None:
    if value is None:
        return None
    item = _action_recovery_json_object(
        value,
        role="invocation.approval_outcome",
        exact_fields=frozenset(
            {
                "gate_id",
                "proposed_edge_id",
                "approval",
                "evidence_records",
                "audit_facts",
            }
        ),
    )
    if not isinstance(item["evidence_records"], list):
        raise _action_recovery_error(
            "ACTION_RECOVERY_INVOCATION_INVALID",
            "approval evidence must be a list",
        )
    return ApprovalOutcome(
        str(item["gate_id"]),
        str(item["proposed_edge_id"]),
        _action_recovery_json_object(
            item["approval"], role="approval record"
        ),
        evidence_records=tuple(
            _action_recovery_json_object(
                record, role="approval evidence"
            )
            for record in item["evidence_records"]
        ),
        audit_facts=_action_recovery_audit_facts(
            item["audit_facts"], role="approval audit facts"
        ),
    )


def _action_recovery_invocation(
    value: object,
    state: dict[str, object],
    target: dict[str, object],
) -> WorkflowActionInvocation:
    item = _action_recovery_json_object(
        value,
        role="accepted invocation",
        exact_fields=frozenset(
            {
                "kind",
                "public_command",
                "selector",
                "target",
                "edge_selector",
                "action_outcome",
                "approval_outcome",
                "action_parameters",
                "evidence",
                "confirm_intent",
            }
        ),
    )
    invocation = WorkflowActionInvocation(
        kind=str(item["kind"]),
        public_command=str(item["public_command"]),
        selector=(
            str(item["selector"])
            if item["selector"] is not None
            else None
        ),
        target=(
            str(item["target"])
            if item["target"] is not None
            else None
        ),
        edge_selector=(
            str(item["edge_selector"])
            if item["edge_selector"] is not None
            else None
        ),
        action_outcome=_action_recovery_action_outcome(
            item["action_outcome"]
        ),
        approval_outcome=_action_recovery_approval_outcome(
            item["approval_outcome"]
        ),
        action_parameters=_action_recovery_json_object(
            item["action_parameters"], role="action parameters"
        ),
        evidence=_action_recovery_json_object(
            item["evidence"], role="action evidence"
        ),
        confirm_intent=(
            str(item["confirm_intent"])
            if item["confirm_intent"] is not None
            else None
        ),
    )
    bindings = target.get("bindings")
    if not isinstance(bindings, _ActionRecoveryMapping):
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_INVALID",
            "target journal has no immutable invocation bindings",
        )
    try:
        roles = _workflow_tx_edge_roles(state, invocation)
        invocation_binding = _workflow_tx_invocation_binding(
            invocation, roles
        )
        actual = {
            "operation_sha256": semantic_sha256(
                _WORKFLOW_TX_OPERATION_DOMAIN, invocation_binding
            ),
            "semantic_operation_sha256": semantic_sha256(
                _WORKFLOW_TX_SEMANTIC_OPERATION_DOMAIN,
                _workflow_tx_semantic_invocation_binding(
                    invocation, roles
                ),
            ),
            "request_sha256": semantic_sha256(
                _WORKFLOW_TX_REQUEST_DOMAIN, invocation_binding
            ),
            "confirmation_sha256": semantic_sha256(
                _WORKFLOW_TX_CONFIRMATION_DOMAIN,
                {"intent_id": invocation.confirm_intent},
            ),
        }
    except Exception as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_INVOCATION_INVALID",
            "accepted invocation does not resolve through the pinned catalog",
        ) from exc
    mismatches = sorted(
        field_name
        for field_name, value in actual.items()
        if bindings.get(field_name) != value
    )
    if mismatches:
        raise _action_recovery_error(
            "ACTION_RECOVERY_INVOCATION_MISMATCH",
            "accepted invocation differs from the quarantined operation",
            details={"fields": mismatches},
        )
    return invocation


def _action_recovery_compensation_plan(
    value: object,
    *,
    effect_id: str,
) -> WorkflowActionCompensationPlan:
    item = _action_recovery_json_object(
        value,
        role="compensation plan",
        exact_fields=frozenset(
            {
                "schema",
                "action_id",
                "effect_id",
                "safe_inputs",
                "safe_inputs_sha256",
                "postcondition_contract_sha256",
            }
        ),
    )
    if item.get("effect_id") != effect_id:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation plan does not bind the target effect",
        )
    plan = WorkflowActionCompensationPlan(
        action_id=str(item["action_id"]),
        effect_id=str(item["effect_id"]),
        safe_inputs=_action_recovery_json_object(
            item["safe_inputs"], role="compensation safe inputs"
        ),
        postcondition_contract_sha256=str(
            item["postcondition_contract_sha256"]
        ),
    )
    if plan.as_dict() != item:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation plan digest fields are not canonical",
        )
    return plan


def action_recovery_controller_file_contract_sha256() -> str:
    return semantic_sha256(
        _ACTION_RECOVERY_COMPENSATION_CONTRACT_DOMAIN,
        {
            "action_id": _ACTION_RECOVERY_COMPENSATION_FILE_ACTION,
            "postcondition": "controller-owned-file-absent",
        },
    )


def _action_recovery_compensation_approvals(
    value: object,
    plan: WorkflowActionCompensationPlan,
    target: dict[str, object],
) -> tuple[
    WorkflowActionCompensationApproval,
    WorkflowActionCompensationApproval,
]:
    if not isinstance(value, list) or len(value) != 2:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation requires exactly two approvals",
        )
    approvals = []
    for index, raw in enumerate(value):
        item = _action_recovery_json_object(
            raw,
            role=f"compensation approval[{index}]",
            exact_fields=frozenset(
                {
                    "authority",
                    "principal",
                    "approval_sha256",
                    "compensation_plan_sha256",
                    "target_journal_sha256",
                }
            ),
        )
        approvals.append(
            WorkflowActionCompensationApproval(
                authority=str(item["authority"]),
                principal=str(item["principal"]),
                approval_sha256=str(item["approval_sha256"]),
                compensation_plan_sha256=str(
                    item["compensation_plan_sha256"]
                ),
                target_journal_sha256=str(
                    item["target_journal_sha256"]
                ),
            )
        )
    return approvals[0], approvals[1]


def _action_recovery_compensation_path(
    task_dir: _ActionRecoveryPath,
    safe_inputs: dict[str, object],
) -> tuple[_ActionRecoveryPath, str]:
    if set(safe_inputs) != {"task_relative_path", "expected_sha256"}:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "controller file compensation has unknown or missing inputs",
        )
    expected_sha256 = _action_recovery_digest(
        safe_inputs["expected_sha256"], "expected_sha256"
    )
    relative_value = safe_inputs["task_relative_path"]
    if (
        not isinstance(relative_value, str)
        or not relative_value
        or "\\" in relative_value
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation path must be a portable task-relative path",
        )
    relative = _ActionRecoveryPurePosixPath(relative_value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not relative.parts
        or relative.parts[0] != "compensation-targets"
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation path must remain under compensation-targets",
        )
    candidate = task_dir.joinpath(*relative.parts)
    try:
        parent = candidate.parent.resolve(strict=True)
        root = task_dir.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation parent directory is unavailable",
        ) from exc
    if parent != root and root not in parent.parents:
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_INVALID",
            "compensation path escapes the task data directory",
        )
    return candidate, expected_sha256


def _action_recovery_dispatch_compensation(
    task_dir: _ActionRecoveryPath,
    permit: CompensationDispatchPlan,
    *,
    workflow_request: WorkflowActionReconciliationRequest,
    host_approval_callback: object,
) -> WorkflowActionCompensationObservation:
    if (
        workflow_request.workflow_version != "4"
        or not callable(host_approval_callback)
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_ADAPTER_UNAVAILABLE",
            "V4 compensation requires the package-owned host approval bridge",
        )
    plan = _action_recovery_json_object(
        permit.compensation_plan, role="claimed compensation plan"
    )
    if (
        plan.get("action_id")
        != _ACTION_RECOVERY_COMPENSATION_FILE_ACTION
        or plan.get("postcondition_contract_sha256")
        != action_recovery_controller_file_contract_sha256()
    ):
        raise _action_recovery_error(
            "ACTION_RECOVERY_COMPENSATION_ADAPTER_UNAVAILABLE",
            "compensation action has no package-owned CLI adapter",
        )
    safe_inputs = _action_recovery_json_object(
        plan.get("safe_inputs"), role="claimed compensation inputs"
    )
    candidate, expected_sha256 = _action_recovery_compensation_path(
        task_dir, safe_inputs
    )
    external_request = {
        "schema": "dev-flow-v4-action-compensation-write-request/v1",
        "task_id": permit.task_id,
        "workflow_id": workflow_request.workflow_id,
        "workflow_version": workflow_request.workflow_version,
        "workflow_bundle_sha256": (
            workflow_request.workflow_bundle_sha256
        ),
        "recovery_action_id": workflow_request.recovery_action_id,
        "workflow_gate_sha256": workflow_request.gate_sha256,
        "workflow_authorization_sha256": (
            workflow_request.authorization_sha256
        ),
        "request_nonce_sha256": (
            workflow_request.request_nonce_sha256
        ),
        "engine_proof_sha256": (
            workflow_request.engine_proof_sha256
        ),
        "compensation_action_id": plan["action_id"],
        "compensation_execution_id": permit.execution_id,
        "authorization_attempt_id": permit.authorization_attempt_id,
        "claim_id": permit.claim_id,
        "effect_id": workflow_request.effect_id,
        "compensation_plan_sha256": (
            compensation_plan_sha256(plan)
        ),
    }
    external_target = {
        "schema": "dev-flow-v4-action-compensation-write-target/v1",
        "task_id": permit.task_id,
        "target_execution_id": permit.target_execution_id,
        "target_journal_sha256": (
            workflow_request.expected_journal.record_sha256
        ),
        "compensation_journal_sha256": (
            permit.journal_record_sha256
        ),
        "task_relative_path": safe_inputs["task_relative_path"],
        "expected_sha256": expected_sha256,
    }
    gate_decision_sha256 = semantic_sha256(
        _ACTION_RECOVERY_EXTERNAL_GATE_DOMAIN,
        {
            "decision": "approved",
            "task_revision": workflow_request.current_task_revision,
            "workflow_gate_sha256": workflow_request.gate_sha256,
            "workflow_authorization_sha256": (
                workflow_request.authorization_sha256
            ),
            "engine_proof_sha256": (
                workflow_request.engine_proof_sha256
            ),
            "request": external_request,
            "target": external_target,
        },
    )
    gate = WorkflowWriteGateDecision(
        gate_id="control.reconcile.compensation/v4",
        decision="approved",
        controller_revision=workflow_request.current_task_revision,
        decision_sha256=gate_decision_sha256,
    )
    binding = WorkflowWriteBinding(
        bundle_sha256=workflow_request.workflow_bundle_sha256,
        action_id=str(plan["action_id"]),
        execution_id=permit.execution_id,
        effect_id=workflow_request.effect_id,
        gate_sha256=gate.sha256,
        nonce=workflow_request.request_nonce_sha256,
    )
    issuer = WorkflowWriteAuthorizationIssuer()

    def provider(
        exact_request: object,
        exact_target: object,
    ) -> dict[str, object]:
        if exact_request != external_request or exact_target != external_target:
            raise _action_recovery_error(
                "ACTION_RECOVERY_COMPENSATION_TARGET_DRIFT",
                "external-write provider received another request or target",
            )
        try:
            before = _action_recovery_os.lstat(candidate)
            if not _action_recovery_stat.S_ISREG(before.st_mode):
                raise _action_recovery_error(
                    "ACTION_RECOVERY_COMPENSATION_TARGET_INVALID",
                    "compensation target must be a regular controller file",
                )
            digest = _action_recovery_hashlib.sha256()
            with candidate.open("rb") as stream:
                opened = _action_recovery_os.fstat(stream.fileno())
                if (
                    opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino
                ):
                    raise _action_recovery_error(
                        "ACTION_RECOVERY_COMPENSATION_TARGET_DRIFT",
                        "compensation target changed before observation",
                    )
                for block in iter(
                    lambda: stream.read(1024 * 1024), b""
                ):
                    digest.update(block)
            observed_sha256 = digest.hexdigest()
            current = _action_recovery_os.lstat(candidate)
            if (
                current.st_dev != before.st_dev
                or current.st_ino != before.st_ino
                or observed_sha256 != expected_sha256
            ):
                raise _action_recovery_error(
                    "ACTION_RECOVERY_COMPENSATION_TARGET_DRIFT",
                    "compensation target differs from its approved identity",
                )
            candidate.unlink()
            try:
                _action_recovery_os.lstat(candidate)
            except FileNotFoundError:
                pass
            else:
                raise _action_recovery_error(
                    "ACTION_RECOVERY_COMPENSATION_POSTCONDITION_FAILED",
                    "compensation target still exists",
                )
        except FlowError:
            raise
        except OSError as exc:
            raise _action_recovery_error(
                "ACTION_RECOVERY_COMPENSATION_FAILED",
                "controller-owned compensation could not complete",
            ) from exc
        return {
            "schema": (
                "dev-flow-v4-action-compensation-provider-result/v1"
            ),
            "removed_sha256": observed_sha256,
            "postcondition_proof_sha256": semantic_sha256(
                _ACTION_RECOVERY_COMPENSATION_POSTCONDITION_DOMAIN,
                {
                    "task_id": permit.task_id,
                    "execution_id": permit.execution_id,
                    "task_relative_path": (
                        safe_inputs["task_relative_path"]
                    ),
                    "absent": True,
                },
            ),
        }

    bridge = HostOwnedExternalWriteBridge(
        issuer=issuer,
        approval_callback=host_approval_callback,
        provider=provider,
    )
    authorization = issuer.issue(
        binding=binding,
        request=external_request,
        target=external_target,
        gate=gate,
        ttl_seconds=30,
    )
    outcome = bridge.invoke(
        authorization=authorization,
        binding=binding,
        request=external_request,
        target=external_target,
    )
    provider_result = dict(outcome.provider_result)
    return WorkflowActionCompensationObservation(
        effect_receipt_sha256=outcome.receipt.sha256,
        postcondition_proof_sha256=str(
            provider_result["postcondition_proof_sha256"]
        ),
    )


def _action_recovery_verifier(
    evidence: dict[str, object],
    effect_id: str,
    *,
    live_abandonment_authority: bool = False,
    host_compensation_authority: bool = False,
):
    def verify(
        challenge: WorkflowActionReconciliationChallenge,
    ) -> object:
        outcome = str(evidence["outcome"])
        if (
            challenge.request.workflow_version == "4"
            and {
                "approvals",
                "quiescence_evidence_sha256",
                "no_business_outcome_evidence_sha256",
            }
            & set(evidence)
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_CALLER_AUTHORITY_FORBIDDEN",
                "caller approvals, booleans, and digests cannot authorize V4 recovery",
            )
        if outcome == "ACCEPTED":
            receipt = challenge.target.get("receipt")
            if not isinstance(receipt, dict):
                raise _action_recovery_error(
                    "ACTION_RECOVERY_RECEIPT_REQUIRED",
                    "accepted reconciliation requires a stored receipt",
                )
            return challenge.accepted(
                complete_receipt=receipt,
                postcondition_evidence_sha256=str(
                    evidence["postcondition_evidence_sha256"]
                ),
            )
        if outcome == "ABANDONED":
            if challenge.request.workflow_version == "4":
                if not live_abandonment_authority:
                    return challenge.unresolved(
                        diagnostic_evidence_sha256=semantic_sha256(
                            _ACTION_RECOVERY_UNRESOLVED_AUTHORITY_DOMAIN,
                            {
                                "authority": "live-abandonment-observer",
                                "task_id": challenge.request.task_id,
                                "workflow_bundle_sha256": (
                                    challenge.request.workflow_bundle_sha256
                                ),
                                "action_edge_id": (
                                    challenge.request.action_edge_id
                                ),
                                "target_execution_id": (
                                    challenge.request.target_execution_id
                                ),
                                "target_journal_sha256": (
                                    challenge.target.get("record_sha256")
                                ),
                            },
                        )
                    )
                return challenge.abandoned()
            return challenge.abandoned(
                quiescence_evidence_sha256=str(
                    evidence["quiescence_evidence_sha256"]
                ),
                no_business_outcome_evidence_sha256=str(
                    evidence[
                        "no_business_outcome_evidence_sha256"
                    ]
                ),
            )
        plan = _action_recovery_compensation_plan(
            evidence["compensation_plan"], effect_id=effect_id
        )
        if challenge.request.workflow_version == "4":
            if not host_compensation_authority:
                return challenge.unresolved(
                    diagnostic_evidence_sha256=semantic_sha256(
                        _ACTION_RECOVERY_UNRESOLVED_AUTHORITY_DOMAIN,
                        {
                            "authority": "host-external-write-bridge",
                            "task_id": challenge.request.task_id,
                            "workflow_bundle_sha256": (
                                challenge.request.workflow_bundle_sha256
                            ),
                            "action_edge_id": (
                                challenge.request.action_edge_id
                            ),
                            "target_execution_id": (
                                challenge.request.target_execution_id
                            ),
                            "compensation_execution_id": evidence[
                                "compensation_execution_id"
                            ],
                            "compensation_plan_sha256": (
                                plan.plan_sha256
                            ),
                        },
                    )
                )
            return challenge.compensated(
                compensation_execution_id=str(
                    evidence["compensation_execution_id"]
                ),
                compensation_plan=plan,
            )
        approvals = _action_recovery_compensation_approvals(
            evidence["approvals"], plan, dict(challenge.target)
        )
        return challenge.compensated(
            compensation_execution_id=str(
                evidence["compensation_execution_id"]
            ),
            compensation_plan=plan,
            approvals=approvals,
        )

    return verify


@_action_recovery_contextlib.contextmanager
def _action_recovery_commit_authority(
    outer: object,
):
    if not isinstance(outer, _ManagerAuthorityInvocation):
        raise _action_recovery_error(
            "MANAGER_CAPABILITY_REQUIRED",
            "action recovery has no live manager authority",
        )
    token = _manager_authority_context_var.set(None)
    try:
        with _manager_authority_context(
            request=outer.request,
            action_id=outer.action_id,
            secret_resolver=lambda: bytearray(
                outer.current_secret()
            ),
            principal=outer.principal,
            operation_fingerprint_sha256=(
                outer.operation_fingerprint_sha256
            ),
        ):
            yield
    finally:
        _manager_authority_context_var.reset(token)


def _action_recovery_operator_intervention(
    target: _ActionRecoveryMapping[str, object],
    result: WorkflowActionReconciliationResult,
) -> dict[str, object] | None:
    bindings = target.get("bindings")
    if (
        result.status != "UNRESOLVED"
        or not isinstance(bindings, _ActionRecoveryMapping)
        or bindings.get("workflow_version") != "4"
    ):
        return None
    inspect_details = {
        "target_execution_id": result.target_execution_id,
        "inspect_command": "action-recovery-inspect",
    }
    if target.get("execution_id") != result.target_execution_id:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RESULT_INVALID",
            "V4 intervention target differs from the recovery result",
            details=inspect_details,
        )
    effects = target.get("effects")
    if not isinstance(effects, list):
        raise _action_recovery_error(
            "ACTION_RECOVERY_RESULT_INVALID",
            "V4 intervention target has no durable effect graph",
            details=inspect_details,
        )
    effect_ids = sorted(
        {
            str(effect["effect_id"])
            for effect in effects
            if isinstance(effect, _ActionRecoveryMapping)
            and isinstance(effect.get("effect_id"), str)
            and effect["effect_id"]
        }
    )
    if not effect_ids:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RESULT_INVALID",
            "V4 intervention target has no effect identity",
            details=inspect_details,
        )
    try:
        affected_scopes = normalize_scopes(
            bindings.get("scopes"),
            "/operator_intervention/affected_scopes",
        )
    except Exception as exc:
        raise _action_recovery_error(
            "ACTION_RECOVERY_RESULT_INVALID",
            "V4 intervention target has no canonical affected scopes",
            details=inspect_details,
        ) from exc
    intervention = {
        "schema": _ACTION_RECOVERY_OPERATOR_INTERVENTION_SCHEMA,
        "required": True,
        "reason": _ACTION_RECOVERY_OPERATOR_INTERVENTION_REASON,
        "target_execution_id": result.target_execution_id,
        "effect_ids": effect_ids,
        "affected_scopes": affected_scopes,
        "allowed_resume_conditions": [
            "authenticated_original_runtime",
            "verifiable_stored_receipt",
            "trusted_host_recovery_authority",
        ],
        "automatic_redispatch": False,
        "automatic_compensation": False,
        "automatic_unblock": False,
        "caller_assertion_can_unblock": False,
    }
    encoded_size = len(semantic_json_bytes(intervention))
    if encoded_size > _ACTION_RECOVERY_MAX_OPERATOR_INTERVENTION_BYTES:
        raise _action_recovery_error(
            "ACTION_RECOVERY_OPERATOR_INTERVENTION_TOO_LARGE",
            "V4 operator intervention exceeds its serialized byte limit",
            details={
                "target_execution_id": result.target_execution_id,
                "actual_bytes": encoded_size,
                "limit_bytes": (
                    _ACTION_RECOVERY_MAX_OPERATOR_INTERVENTION_BYTES
                ),
                "inspect_command": "action-recovery-inspect",
            },
        )
    return intervention


def _action_recovery_response(
    task_dir: _ActionRecoveryPath,
    result: WorkflowActionReconciliationResult,
    *,
    manager_secret: str,
) -> dict[str, object]:
    attempt = result.attempt
    outcome = attempt.get("outcome")
    if not isinstance(outcome, _ActionRecoveryMapping):
        raise _action_recovery_error(
            "ACTION_RECOVERY_RESULT_INVALID",
            "terminal reconciliation has no durable outcome",
        )
    store = ActionExecutionStore(task_dir)
    target = (
        store.read_active_journal(
            result.target_execution_id,
            manager_secret=manager_secret,
        )
        if result.blocked
        else store.read_archive_journal(
            result.target_execution_id,
            manager_secret=manager_secret,
        )
    )
    original_dispatch_count = sum(
        1
        for effect in target.get("effects", ())
        if isinstance(effect, _ActionRecoveryMapping)
        and effect.get("claim_id") is not None
    )
    compensation_dispatch_count = 0
    if result.status == "COMPENSATED":
        if result.compensation_execution_id is None:
            raise _action_recovery_error(
                "ACTION_RECOVERY_RESULT_INVALID",
                "compensated recovery has no execution identity",
            )
        compensation = store.read_compensation_archive(
            result.compensation_execution_id
        )
        if compensation.get("phase") != "COMMITTED":
            raise _action_recovery_error(
                "ACTION_RECOVERY_RESULT_INVALID",
                "compensation execution is not durably committed",
            )
        compensation_dispatch_count = 1
    state = load_state(task_dir / "state.json")
    bindings = target.get("bindings")
    workflow_version = (
        bindings.get("workflow_version")
        if isinstance(bindings, _ActionRecoveryMapping)
        else None
    )
    response = {
        "schema": (
            _ACTION_RECOVERY_RESULT_SCHEMA_V4
            if workflow_version == "4"
            else _ACTION_RECOVERY_RESULT_SCHEMA
        ),
        "task_id": state["task_id"],
        "target_execution_id": result.target_execution_id,
        "attempt_id": result.attempt_id,
        "status": result.status,
        "blocked": result.blocked,
        "target_dispatcher_invocations": 0,
        "original_dispatch_count": original_dispatch_count,
        "compensation_dispatch_count": (
            compensation_dispatch_count
        ),
        "event_sha256": outcome.get("recovery_event_sha256"),
        "outbox_sha256": outcome.get("outbox_sha256"),
        "revision": (
            outcome.get("task_commit_revision")
            if outcome.get("task_commit_revision") is not None
            else state["revision"]
        ),
        "archive_path": result.archive_path,
        "compensation_execution_id": (
            result.compensation_execution_id
        ),
    }
    intervention = _action_recovery_operator_intervention(
        target, result
    )
    if intervention is not None:
        response["operator_intervention"] = intervention
    return response


def _action_recovery_existing_attempt(
    store: ActionExecutionStore,
    attempt_id: str,
) -> dict[str, object] | None:
    for reader in (
        store.read_reconciliation,
        store.read_rotated_reconciliation,
        store.read_reconciliation_archive,
    ):
        try:
            return reader(attempt_id)
        except Exception as exc:
            if getattr(exc, "code", None) not in {
                "ACTION_STORE_RECORD_MISSING",
                "ACTION_STORE_DIRECTORY_MISSING",
            }:
                raise
    return None


def _action_recovery_target_effect_id(
    target: _ActionRecoveryMapping[str, object],
    outcome: str,
) -> str:
    effects = target.get("effects")
    if not isinstance(effects, list):
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_INVALID",
            "action recovery target has no effect graph",
        )
    if outcome == "ACCEPTED":
        quarantine = target.get("quarantine")
        receipt = target.get("receipt")
        if not isinstance(
            quarantine, _ActionRecoveryMapping
        ) or not isinstance(receipt, _ActionRecoveryMapping):
            raise _action_recovery_error(
                "ACTION_RECOVERY_RECEIPT_REQUIRED",
                "accepted recovery requires an exact stored receipt",
            )
        effect_id = quarantine.get("effect_id")
        receipt_sha256 = receipt.get("receipt_sha256")
        accepted = [
            effect
            for effect in effects
            if isinstance(effect, _ActionRecoveryMapping)
            and effect.get("effect_id") == effect_id
            and effect.get("phase") == "QUARANTINED"
            and isinstance(effect.get("receipt_sha256"), str)
            and quarantine.get("receipt_sha256") == receipt_sha256
        ]
        if len(accepted) != 1:
            raise _action_recovery_error(
                "ACTION_RECOVERY_TARGET_AMBIGUOUS",
                "accepted recovery requires one receipt-bound "
                "quarantined effect",
                details={"accepted_effects": len(accepted)},
            )
        return str(effect_id)
    quarantined = [
        effect
        for effect in effects
        if isinstance(effect, _ActionRecoveryMapping)
        and effect.get("phase") == "QUARANTINED"
        and isinstance(effect.get("effect_id"), str)
        and effect["effect_id"]
    ]
    if len(quarantined) != 1:
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_AMBIGUOUS",
            "action recovery requires exactly one quarantined effect",
            details={"quarantined_effects": len(quarantined)},
        )
    return str(quarantined[0]["effect_id"])


def _action_recovery_validate_closed_containments(
    store: ActionExecutionStore,
    index: dict[str, object],
    target: dict[str, object],
    evidence: dict[str, object],
    *,
    manager_secret: str,
) -> tuple[dict[str, object], dict[str, object]]:
    del manager_secret
    if evidence["outcome"] == "ACCEPTED":
        receipt = target.get("receipt")
        if not isinstance(receipt, _ActionRecoveryMapping):
            raise _action_recovery_error(
                "ACTION_RECOVERY_RECEIPT_REQUIRED",
                "accepted reconciliation requires a stored receipt",
            )
        _action_recovery_digest(
            receipt.get("receipt_sha256"),
            "receipt.receipt_sha256",
        )
    elif (
        not isinstance(target.get("bindings"), _ActionRecoveryMapping)
        or target["bindings"].get("workflow_version") != "4"
    ):
        _action_recovery_digest(
            evidence.get("quiescence_evidence_sha256"),
            "quiescence_evidence_sha256",
        )
    effects = target.get("effects")
    if not isinstance(effects, list):
        raise _action_recovery_error(
            "ACTION_RECOVERY_TARGET_INVALID",
            "action recovery target has no effect graph",
        )
    for effect in effects:
        if not isinstance(effect, _ActionRecoveryMapping):
            raise _action_recovery_error(
                "ACTION_RECOVERY_TARGET_INVALID",
                "action recovery target has an invalid effect",
            )
        containment = store.read_containment(
            str(target["execution_id"]),
            str(effect["effect_id"]),
        )
        if (
            containment["phase"] != "CLOSED"
            or effect.get("containment_record_sha256")
            != containment["record_sha256"]
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_QUIESCENCE_REQUIRED",
                "every target containment must be durably closed and cross-linked",
                details={
                    "effect_id": effect["effect_id"],
                    "phase": containment["phase"],
                },
            )
    return index, target


def workflow_action_recovery_apply_v1(
    args: object,
) -> dict[str, object]:
    task_id = _task_arg(args)
    evidence = _action_recovery_evidence(args)
    task_dir = _task_dir(task_id, args.data_dir)
    store = ActionExecutionStore(task_dir)
    existing = _action_recovery_existing_attempt(
        store, args.attempt_id
    )
    if existing is not None:
        expected_preview = str(args.confirm_preview)
        bindings = existing.get("bindings")
        if not isinstance(bindings, _ActionRecoveryMapping):
            raise _action_recovery_error(
                "ACTION_RECOVERY_ATTEMPT_INVALID",
                "existing reconciliation has no immutable bindings",
            )
        if (
            existing.get("target_execution_id")
            != args.execution_id
            or bindings.get("expected_task_revision")
            != args.expected_revision
            or bindings.get("gate_sha256")
            != _action_recovery_gate_sha256(expected_preview)
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_REPLAY_CONFLICT",
                "attempt identity is bound to another recovery request",
            )
    else:
        index_untrusted, target_untrusted, _path = (
            _action_recovery_untrusted_target(
                task_dir, args.execution_id
            )
        )
        preview_document = _action_recovery_preview_document(
            task_id=task_id,
            execution_id=args.execution_id,
            attempt_id=args.attempt_id,
            outcome=str(args.outcome).upper(),
            expected_revision=args.expected_revision,
            evidence=evidence,
            index=index_untrusted,
            target=target_untrusted,
        )
        expected_preview = _action_recovery_preview_token(
            preview_document
        )
        if (
            not isinstance(args.confirm_preview, str)
            or not _action_recovery_hmac.compare_digest(
                args.confirm_preview, expected_preview
            )
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_PREVIEW_STALE",
                "action recovery apply requires the exact live preview",
            )
        provisional_untrusted = WorkflowActionReconciliationRequest(
            task_id=task_id,
            workflow_id=str(
                target_untrusted["bindings"]["workflow_id"]
            ),
            workflow_version=str(
                target_untrusted["bindings"]["workflow_version"]
            ),
            workflow_bundle_sha256=str(
                target_untrusted["bindings"][
                    "workflow_bundle_sha256"
                ]
            ),
            action_edge_id=str(
                target_untrusted["bindings"]["action_edge_id"]
            ),
            target_execution_id=args.execution_id,
            effect_id=_action_recovery_target_effect_id(
                target_untrusted, str(evidence["outcome"])
            ),
            scopes=_action_recovery_copy.deepcopy(
                target_untrusted["bindings"]["scopes"]
            ),
            current_task_revision=args.expected_revision,
            attempt_id=args.attempt_id,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256="0" * 64,
            capability_sha256="0" * 64,
            gate_sha256=_action_recovery_gate_sha256(
                expected_preview
            ),
            request_nonce_sha256="0" * 64,
            engine_proof_sha256="0" * 64,
            principal="manager:pending",
            expected_index=cas_token(index_untrusted),
            expected_journal=cas_token(target_untrusted),
        )
    outer = _manager_authority_context_var.get()
    if not isinstance(outer, _ManagerAuthorityInvocation):
        raise _action_recovery_error(
            "MANAGER_CAPABILITY_REQUIRED",
            "schema-v4 action recovery requires local manager proof",
        )
    request = outer.request
    if (
        request.task_id != task_id
        or request.action_id != "control.reconcile/v1"
        or request.expected_revision != args.expected_revision
    ):
        raise _action_recovery_error(
            "MANAGER_CAPABILITY_ACTION_MISMATCH",
            "manager request does not bind this recovery apply",
    )
    if existing is not None:
        try:
            outer.current_secret()
        except FlowError as exc:
            if exc.code != "MANAGER_CAPABILITY_PROOF_UNAVAILABLE":
                raise
            outer.take_secret()
        manager_secret = _manager_workflow_action_journal_secret_v1()
        state = load_state(task_id, args.data_dir)
        orchestration = _manager_orchestration_mapping(state)
        verifier_value = orchestration[
            "manager_capabilities"
        ].get(request.capability_id)
        if verifier_value is None:
            raise _action_recovery_error(
                "MANAGER_CAPABILITY_UNKNOWN",
                "replayed recovery capability is unavailable",
            )
        verifier = validate_manager_capability_verifier(
            verifier_value
        )
        nonce_sha256 = manager_request_nonce_digest(request)
        try:
            if nonce_sha256 in verifier.used_request_nonce_sha256s:
                verify_manager_capability_replay_request(
                    verifier,
                    request,
                    outer.principal,
                    manager_secret=outer.current_secret(),
                )
            else:
                _check_revision(state, args.expected_revision)
                consume_manager_capability_request(
                    verifier,
                    request,
                    outer.principal,
                    manager_secret=outer.current_secret(),
                    wall_time_ns=_action_recovery_time.time_ns(),
                    monotonic_time_ns=(
                        _manager_system_monotonic_ns()
                    ),
                    clock_id=MANAGER_CAPABILITY_CLOCK_ID,
                )
        except OrchestrationAuthorityError as exc:
            raise FlowError(
                exc.code, exc.message, details=exc.details
            ) from exc
        result = recover_v4_workflow_action_reconciliation(
            task_dir,
            args.attempt_id,
            reauthenticate=lambda: manager_secret,
        )
        return _action_recovery_response(
            task_dir, result, manager_secret=manager_secret
        )

    with _task_lock(task_dir):
        state = load_state(task_id, args.data_dir)
        _check_revision(state, args.expected_revision)
        event_type = _workflow_reconcile_catalog_event_type(
            state, provisional_untrusted, target_untrusted
        )
        manager_process_commit_gate_v1(
            state,
            state,
            "manager_effect_preauthorized",
            _effect_lifecycle=("preauthorize", "generic"),
            _effect_package_action_id=outer.package_action_id,
        )
        manager_secret = (
            _manager_workflow_action_journal_secret_v1()
        )
        index = store.read_index(expected_task_id=task_id)
        target = store.read_active_journal(
            args.execution_id,
            manager_secret=manager_secret,
        )
        if target.get("phase") != "QUARANTINED":
            raise _action_recovery_error(
                "ACTION_RECOVERY_TARGET_NOT_QUARANTINED",
                "action recovery apply requires a quarantined execution",
                details={"phase": target.get("phase")},
            )
        if (
            index["revision"] != index_untrusted["revision"]
            or index["record_sha256"]
            != index_untrusted["record_sha256"]
            or target["revision"] != target_untrusted["revision"]
            or target["record_sha256"]
            != target_untrusted["record_sha256"]
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_PREVIEW_STALE",
                "action index or journal changed after preview",
            )
        provisional = _action_recovery_replace(
            provisional_untrusted,
            expected_index=cas_token(index),
            expected_journal=cas_token(target),
        )
        authorization = _manager_workflow_action_authorization_v1(
            state, event_type=event_type
        )
        prepared = _manager_engine_evaluation_state_v1(
            state, event_type=event_type
        )
        if not isinstance(prepared, dict):
            raise _action_recovery_error(
                "MANAGER_PREAUTHORIZATION_REQUIRED",
                "action recovery produced no nonce-prepared state",
            )
        provisional = _action_recovery_replace(
            provisional,
            authorization_sha256=(
                authorization.authorization_sha256
            ),
            capability_sha256=authorization.capability_sha256,
            request_nonce_sha256=(
                authorization.request_nonce_sha256
            ),
            principal=authorization.principal,
        )
        invocation = (
            _action_recovery_invocation(
                evidence["invocation"], state, target
            )
            if evidence["outcome"] == "ACCEPTED"
            else None
        )
        if evidence["outcome"] == "ABANDONED":
            preview_evaluation = (
                preview_v4_workflow_action_abandonment(
                    provisional, prepared, target
                )
            )
        elif evidence["outcome"] == "COMPENSATED":
            preview_evaluation = (
                preview_v4_workflow_action_compensation(
                    provisional, prepared, target
                )
            )
        else:
            assert invocation is not None
            receipt_context = WorkflowActionReceiptContext(
                index=index,
                journal=target,
                expected_index=cas_token(index),
                reauthenticate=lambda: manager_secret,
                pre_effect_state=state,
                neutralize_manager_nonce=True,
                reconciliation_authority=(
                    _workflow_action_quarantined_receipt_authority
                ),
            )
            roles = _workflow_tx_edge_roles(state, invocation)
            preview_evaluation = _workflow_tx_evaluate(
                prepared,
                invocation,
                preview=True,
                receipt_context=receipt_context,
                manager_intent_state=state,
                edge_roles=roles,
            )
        request_value = _action_recovery_replace(
            provisional,
            engine_proof_sha256=(
                workflow_action_reconciliation_engine_proof_sha256(
                    provisional, preview_evaluation
                )
            ),
        )

    recovery_lock_claims = action_execution_required_lock_claims(
        target
    )
    with _workflow_tx_ordered_locks(
        task_dir, recovery_lock_claims
    ):
        current_index = store.read_index(
            expected_task_id=task_id
        )
        current_target = store.read_active_journal(
            args.execution_id,
            manager_secret=manager_secret,
        )
        if (
            cas_token(current_index) != request_value.expected_index
            or cas_token(current_target)
            != request_value.expected_journal
        ):
            raise _action_recovery_error(
                "ACTION_RECOVERY_PREVIEW_STALE",
                "action recovery target changed before quiescence commit",
            )
        closed_index, closed_target = (
            _action_recovery_validate_closed_containments(
            store,
            current_index,
            current_target,
            evidence,
            manager_secret=manager_secret,
        )
        )
        request_without_proof = _action_recovery_replace(
            request_value,
            expected_index=cas_token(closed_index),
            expected_journal=cas_token(closed_target),
            engine_proof_sha256="0" * 64,
        )
        if evidence["outcome"] == "ABANDONED":
            preview_evaluation = (
                preview_v4_workflow_action_abandonment(
                    request_without_proof,
                    prepared,
                    closed_target,
                )
            )
        elif evidence["outcome"] == "COMPENSATED":
            preview_evaluation = (
                preview_v4_workflow_action_compensation(
                    request_without_proof,
                    prepared,
                    closed_target,
                )
            )
        else:
            assert invocation is not None
            closed_receipt_context = WorkflowActionReceiptContext(
                index=closed_index,
                journal=closed_target,
                expected_index=cas_token(closed_index),
                reauthenticate=lambda: manager_secret,
                pre_effect_state=state,
                neutralize_manager_nonce=True,
                reconciliation_authority=(
                    _workflow_action_quarantined_receipt_authority
                ),
            )
            roles = _workflow_tx_edge_roles(state, invocation)
            preview_evaluation = _workflow_tx_evaluate(
                prepared,
                invocation,
                preview=True,
                receipt_context=closed_receipt_context,
                manager_intent_state=state,
                edge_roles=roles,
            )
        request_value = _action_recovery_replace(
            request_without_proof,
            engine_proof_sha256=(
                workflow_action_reconciliation_engine_proof_sha256(
                    request_without_proof, preview_evaluation
                )
            ),
        )

    def commit_evaluator(
        context: WorkflowActionReconciliationCommitContext,
    ) -> WorkflowActionReconciliationCommitPlan:
        if context.decision == "ABANDONED":
            return evaluate_v4_workflow_action_abandonment(context)
        if context.decision == "COMPENSATED":
            return evaluate_v4_workflow_action_compensation(context)
        assert invocation is not None
        current_store = ActionExecutionStore(task_dir)
        current_index = current_store.read_index(
            expected_task_id=task_id
        )
        receipt_context = WorkflowActionReceiptContext(
            index=current_index,
            journal=context.target_journal,
            expected_index=cas_token(current_index),
            reauthenticate=lambda: manager_secret,
            pre_effect_state=context.pre_effect_state,
            neutralize_manager_nonce=True,
            reconciliation_authority=(
                _workflow_action_quarantined_receipt_authority
            ),
        )
        roles = _workflow_tx_edge_roles(
            context.pre_effect_state, invocation
        )
        evaluation = _workflow_tx_evaluate(
            context.current_state,
            invocation,
            preview=False,
            receipt_context=receipt_context,
            manager_intent_state=context.pre_effect_state,
            edge_roles=roles,
        )
        return WorkflowActionReconciliationCommitPlan(evaluation)

    live_observer_v4 = (
        _ACTION_RECOVERY_LIVE_ABANDONMENT_OBSERVER_V4
        if callable(_ACTION_RECOVERY_LIVE_ABANDONMENT_OBSERVER_V4)
        else None
    )
    host_approval_v4 = (
        _ACTION_RECOVERY_HOST_APPROVAL_CALLBACK_V4
        if callable(_ACTION_RECOVERY_HOST_APPROVAL_CALLBACK_V4)
        else None
    )
    try:
        result = reconcile_v4_workflow_action_quarantine(
            task_dir,
            request_value,
            reauthenticate=lambda: manager_secret,
            verifier=_action_recovery_verifier(
                evidence,
                request_value.effect_id,
                live_abandonment_authority=callable(
                    live_observer_v4
                ),
                host_compensation_authority=callable(
                    host_approval_v4
                ),
            ),
            live_abandonment_observer=(
                live_observer_v4
                if request_value.workflow_version == "4"
                else None
            ),
            commit_evaluator=commit_evaluator,
            commit_authorizer=lambda _context: (
                _action_recovery_commit_authority(outer)
            ),
            compensation_dispatcher=(
                _workflow_reconcile_wrap_compensation_dispatcher(
                    lambda permit: (
                        _action_recovery_dispatch_compensation(
                            task_dir,
                            permit,
                            workflow_request=request_value,
                            host_approval_callback=(
                                host_approval_v4
                            ),
                        )
                    )
                )
                if (
                    evidence["outcome"] == "COMPENSATED"
                    and request_value.workflow_version == "4"
                    and callable(host_approval_v4)
                )
                else None
            ),
        )
    except WorkflowActionReconciliationError as exc:
        raise FlowError(
            exc.code, exc.message, details=exc.details
        ) from exc
    return _action_recovery_response(
        task_dir, result, manager_secret=manager_secret
    )
