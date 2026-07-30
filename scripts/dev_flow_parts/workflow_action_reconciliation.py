# Loaded by scripts/dev_flow.py after the action-execution store and
# transaction coordinator.  This module is the controller-owned quarantine
# reconciliation boundary.  It never redispatches the quarantined business
# effect: a verifier may accept its complete durable receipt, prove that no
# business outcome occurred after quiescence, or leave the target unresolved.
from __future__ import annotations

import copy as _workflow_reconcile_copy
import contextlib as _workflow_reconcile_contextlib
import hmac as _workflow_reconcile_hmac
import json as _workflow_reconcile_json
import re as _workflow_reconcile_re
import secrets as _workflow_reconcile_secrets
from dataclasses import dataclass as _workflow_reconcile_dataclass
from pathlib import Path as _WorkflowReconcilePath
from typing import Callable as _WorkflowReconcileCallable
from typing import Mapping as _WorkflowReconcileMapping
from typing import Sequence as _WorkflowReconcileSequence


if "ActionExecutionStore" not in globals():
    from .action_execution_journal import (
        CASToken,
        action_execution_archive_path,
        advance_compensation_execution,
        advance_reconciliation_attempt,
        authorize_reconciliation_compensation,
        cas_token,
        compensation_plan_sha256,
        finalize_reconciliation_compensation,
        new_compensation_execution,
        new_reconciliation_attempt,
        normalize_compensation_plan,
        normalize_scopes,
        plan_compensation_control_rotation,
        plan_reconciliation_control_rotation,
        seal_compensation_receipt,
        semantic_json_bytes,
        semantic_sha256,
    )
    from .action_execution_store import (
        ActionExecutionStore,
        CompensationDispatchPlan,
        action_execution_required_lock_claims,
    )
    from .transition_engine import TransitionEvaluation


WORKFLOW_ACTION_RECONCILIATION_SCHEMA = (
    "dev-flow-v3-workflow-action-reconciliation/v1"
)
WORKFLOW_ACTION_RECONCILIATION_FAILURE_POINTS = (
    "before-attempt",
    "after-attempt",
    "after-claim",
    "before-task-commit",
    "after-task-commit",
    "after-decision",
    "after-archive",
)

_WORKFLOW_RECONCILE_SHA256_RE = _workflow_reconcile_re.compile(
    r"^[0-9a-f]{64}$"
)
_WORKFLOW_RECONCILE_ABANDONMENT_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-abandonment-v1\x00"
)
_WORKFLOW_RECONCILE_LIVE_ABANDONMENT_DOMAIN = (
    b"dev-flow-v4-workflow-action-live-abandonment-v1\x00"
)
_WORKFLOW_RECONCILE_PROOF_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-proof-v1\x00"
)
_WORKFLOW_RECONCILE_ENGINE_PROOF_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-engine-proof-v1\x00"
)
_WORKFLOW_RECONCILE_RESTART_UNRESOLVED_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-restart-unresolved-v1\x00"
)
_WORKFLOW_RECONCILE_DUAL_APPROVAL_DOMAIN = (
    b"dev-flow-v3-workflow-action-compensation-dual-approval-v1\x00"
)
_WORKFLOW_RECONCILE_EVENT_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-event-v1\x00"
)
_WORKFLOW_RECONCILE_OUTBOX_DOMAIN = (
    b"dev-flow-v3-workflow-action-reconciliation-outbox-v1\x00"
)
_WORKFLOW_RECONCILE_EVENT_SCHEMA = (
    "dev-flow-v3-workflow-action-reconciliation-event/v1"
)
_WORKFLOW_RECONCILE_ACTION_ID = "control.reconcile/v1"
_WORKFLOW_RECONCILE_SCOPE_FIELDS = (
    "repository_ids",
    "node_ids",
    "worktree_ids",
    "lease_ids",
    "paths",
    "external_resources",
)


class WorkflowActionReconciliationError(RuntimeError):
    """Stable fail-closed rejection from the reconciliation coordinator."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _WorkflowReconcileMapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class WorkflowActionReconciliationAuthorityRejected(RuntimeError):
    """A current-authority verifier rejected an expiring/revoked fact."""

    _REASONS = frozenset(
        {
            "AUTHORIZATION_EXPIRED",
            "AUTHORIZATION_REVOKED",
            "GATE_NOT_CURRENT",
            "REQUEST_NONCE_REPLAY",
            "ENGINE_PROOF_NOT_CURRENT",
        }
    )

    def __init__(self, reason: str) -> None:
        if reason not in self._REASONS:
            raise ValueError("unsupported reconciliation rejection reason")
        super().__init__(reason)
        self.reason = reason


def _workflow_reconcile_error(
    code: str,
    message: str,
    *,
    details: _WorkflowReconcileMapping[str, object] | None = None,
) -> WorkflowActionReconciliationError:
    return WorkflowActionReconciliationError(
        code, message, details=details
    )


def _workflow_reconcile_sha256(value: object, role: str) -> str:
    if (
        not isinstance(value, str)
        or not _WORKFLOW_RECONCILE_SHA256_RE.fullmatch(value)
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
            f"{role} must be lowercase SHA-256",
        )
    return value


def _workflow_reconcile_text(value: object, role: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
            f"{role} must be non-empty text",
        )
    return value


def _workflow_reconcile_fail(
    failure_hook: _WorkflowReconcileCallable[[str], None] | None,
    stage: str,
) -> None:
    if failure_hook is not None:
        failure_hook(stage)


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionReconciliationRequest:
    """One exact, fresh request bound to a quarantined catalog effect."""

    task_id: str
    workflow_id: str
    workflow_version: str
    workflow_bundle_sha256: str
    action_edge_id: str
    target_execution_id: str
    effect_id: str
    scopes: _WorkflowReconcileMapping[str, object]
    current_task_revision: int
    attempt_id: str
    recovery_action_id: str
    authorization_kind: str
    authorization_sha256: str
    capability_sha256: str | None
    gate_sha256: str
    request_nonce_sha256: str
    engine_proof_sha256: str
    principal: str
    expected_index: CASToken
    expected_journal: CASToken
    replaces_attempt_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "workflow_id",
            "workflow_version",
            "action_edge_id",
            "target_execution_id",
            "effect_id",
            "attempt_id",
            "recovery_action_id",
            "principal",
        ):
            _workflow_reconcile_text(
                getattr(self, field_name), field_name
            )
        for field_name in (
            "workflow_bundle_sha256",
            "authorization_sha256",
            "gate_sha256",
            "request_nonce_sha256",
            "engine_proof_sha256",
        ):
            _workflow_reconcile_sha256(
                getattr(self, field_name), field_name
            )
        if (
            isinstance(self.current_task_revision, bool)
            or not isinstance(self.current_task_revision, int)
            or self.current_task_revision < 0
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
                "current task revision must be a non-negative integer",
            )
        if self.authorization_kind not in {"manager", "operator"}:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
                "authorization kind must be manager or operator",
            )
        if self.recovery_action_id != _WORKFLOW_RECONCILE_ACTION_ID:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_ACTION_INVALID",
                "generic quarantine recovery requires control.reconcile/v1",
            )
        if self.authorization_kind == "manager":
            _workflow_reconcile_sha256(
                self.capability_sha256, "capability_sha256"
            )
        elif self.capability_sha256 is not None:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
                "operator reconciliation cannot carry manager capability",
            )
        if (
            type(self.expected_index) is not CASToken
            or type(self.expected_journal) is not CASToken
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CAS_REQUIRED",
                "request requires exact index and journal CAS tokens",
            )
        if self.replaces_attempt_id is not None:
            _workflow_reconcile_text(
                self.replaces_attempt_id, "replaces_attempt_id"
            )
        try:
            normalized = normalize_scopes(dict(self.scopes))
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_SCOPE_INVALID",
                "request scopes must use the canonical action scope schema",
            ) from exc
        object.__setattr__(
            self,
            "scopes",
            _workflow_reconcile_copy.deepcopy(normalized),
        )


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionReconciliationResult:
    status: str
    target_execution_id: str
    attempt_id: str
    attempt: dict[str, object]
    index: dict[str, object]
    archive_path: str | None
    dispatcher_invocations: int
    blocked: bool
    compensation_execution_id: str | None = None


class _WorkflowReconcileCompensationDispatchRequired(RuntimeError):
    """Internal control transfer that releases controller locks before I/O."""

    def __init__(
        self,
        request: WorkflowActionReconciliationRequest,
        permit: CompensationDispatchPlan,
    ) -> None:
        super().__init__("compensation dispatch requires released locks")
        self.request = request
        self.permit = permit


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionReconciliationCommitContext:
    """Exact live facts from which a caller must issue one evaluation."""

    request: WorkflowActionReconciliationRequest
    decision: str
    evidence_sha256: str
    receipt_sha256: str | None
    current_state: _WorkflowReconcileMapping[str, object]
    pre_effect_state: _WorkflowReconcileMapping[str, object]
    target_journal: _WorkflowReconcileMapping[str, object]
    attempt: _WorkflowReconcileMapping[str, object]
    compensation_execution: (
        _WorkflowReconcileMapping[str, object] | None
    ) = None

    def __post_init__(self) -> None:
        if self.decision not in {
            "ACCEPTED",
            "ABANDONED",
            "COMPENSATED",
        }:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMMIT_CONTEXT_INVALID",
                "commit context requires one closing decision",
            )
        _workflow_reconcile_sha256(
            self.evidence_sha256, "evidence_sha256"
        )
        if self.receipt_sha256 is not None:
            _workflow_reconcile_sha256(
                self.receipt_sha256, "receipt_sha256"
            )
        for field_name in (
            "current_state",
            "pre_effect_state",
            "target_journal",
            "attempt",
        ):
            object.__setattr__(
                self,
                field_name,
                _workflow_reconcile_copy.deepcopy(
                    dict(getattr(self, field_name))
                ),
            )
        if self.compensation_execution is not None:
            object.__setattr__(
                self,
                "compensation_execution",
                _workflow_reconcile_copy.deepcopy(
                    dict(self.compensation_execution)
                ),
            )


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionReconciliationCommitPlan:
    """One live, unconsumed kernel evaluation; event facts are derived."""

    evaluation: TransitionEvaluation

    def __post_init__(self) -> None:
        if type(self.evaluation) is not TransitionEvaluation:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_EVALUATION_INVALID",
                "commit plan requires the exact live TransitionEvaluation type",
            )


def _workflow_reconcile_catalog_event_type(
    state: _WorkflowReconcileMapping[str, object],
    request: WorkflowActionReconciliationRequest,
    target: _WorkflowReconcileMapping[str, object],
) -> str:
    """Resolve the target edge and prove its declared reconciliation control."""

    try:
        bundle = _workflow_action_bundle(state)
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CATALOG_INVALID",
            "pinned workflow bundle could not be resolved",
        ) from exc
    edges = (
        *tuple(getattr(bundle, "movement_edges", ())),
        *tuple(getattr(bundle, "action_edges", ())),
    )
    matches = [
        edge
        for edge in edges
        if edge.get("id") == request.action_edge_id
    ]
    if len(matches) != 1:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EDGE_MISMATCH",
            "target action edge is not unique in the pinned bundle",
        )
    completion_edge = matches[0]
    bindings = target.get("bindings")
    authorization_edge_id = (
        bindings.get("authorization_action_edge_id")
        if isinstance(bindings, _WorkflowReconcileMapping)
        else None
    )
    action_matches = [
        edge
        for edge in tuple(getattr(bundle, "action_edges", ()))
        if edge.get("id")
        == (
            authorization_edge_id
            if isinstance(authorization_edge_id, str)
            else request.action_edge_id
        )
    ]
    if len(action_matches) != 1:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EDGE_MISMATCH",
            "target authorization action edge is not unique",
        )
    action_edge = action_matches[0]
    completion_trigger = completion_edge.get("trigger")
    public_command = action_edge.get("public_command")
    if (
        action_edge.get("id") != completion_edge.get("id")
        and (
            not isinstance(
                completion_trigger, _WorkflowReconcileMapping
            )
            or not isinstance(
                public_command, _WorkflowReconcileMapping
            )
            or completion_trigger.get("id")
            != public_command.get("id")
        )
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EDGE_MISMATCH",
            "target authorization and completion edges are not linked",
        )
    effects = action_edge.get("effects")
    target_effect = next(
        (
            effect
            for effect in effects
            if isinstance(effect, _WorkflowReconcileMapping)
            and effect.get("id") == request.effect_id
        ),
        None,
    ) if isinstance(effects, (list, tuple)) else None
    controls = (
        target_effect.get("target_controls")
        if isinstance(target_effect, _WorkflowReconcileMapping)
        else None
    )
    event_type = action_edge.get("canonical_event")
    if (
        target_effect is None
        or not isinstance(controls, (list, tuple))
        or request.recovery_action_id not in controls
        or not isinstance(event_type, str)
        or not event_type
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_ACTION_INVALID",
            "pinned target effect does not declare this recovery control",
            details={
                "edge_id": request.action_edge_id,
                "effect_id": request.effect_id,
                "recovery_action_id": request.recovery_action_id,
            },
        )
    return event_type


def workflow_action_reconciliation_engine_proof_sha256(
    request: WorkflowActionReconciliationRequest,
    evaluation: TransitionEvaluation,
) -> str:
    """Bind a request to the exact semantic live engine evaluation.

    The request digest excludes its own proof field. Commit still consumes
    the process-private one-shot issuance, so matching public bytes alone
    cannot mint authority.
    """

    if (
        type(request) is not WorkflowActionReconciliationRequest
        or type(evaluation) is not TransitionEvaluation
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVALUATION_INVALID",
            "engine proof binding requires exact request and evaluation types",
        )
    evaluation_binding = globals().get(
        "_workflow_action_evaluation_binding"
    )
    if not callable(evaluation_binding):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_RUNTIME_INVALID",
            "engine evaluation binding is unavailable",
        )
    request_binding = {
        field_name: _workflow_reconcile_copy.deepcopy(
            getattr(request, field_name)
        )
        for field_name in request.__dataclass_fields__
        if field_name not in {
            "engine_proof_sha256",
            "expected_index",
            "expected_journal",
        }
    }
    request_binding["expected_index"] = {
        "revision": request.expected_index.revision,
        "record_sha256": request.expected_index.record_sha256,
    }
    request_binding["expected_journal"] = {
        "revision": request.expected_journal.revision,
        "record_sha256": request.expected_journal.record_sha256,
    }
    return semantic_sha256(
        _WORKFLOW_RECONCILE_ENGINE_PROOF_DOMAIN,
        {
            "request": request_binding,
            "evaluation": evaluation_binding(evaluation),
        },
    )


def _workflow_reconcile_control_evaluation(
    request: WorkflowActionReconciliationRequest,
    state: _WorkflowReconcileMapping[str, object],
    target: _WorkflowReconcileMapping[str, object],
    *,
    decision: str,
    preview: bool,
) -> TransitionEvaluation:
    if decision not in {"ABANDONED", "COMPENSATED"}:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_CONTEXT_INVALID",
            "control evaluation requires abandonment or compensation",
        )
    if decision == "ABANDONED" and target.get("receipt") is not None:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_ABANDONMENT_RECEIPT_FORBIDDEN",
            "proven-no-outcome abandonment cannot carry a business receipt",
        )
    bundle = _workflow_action_bundle(state)
    bindings = target.get("bindings")
    authorization_edge_id = (
        bindings.get("authorization_action_edge_id")
        if isinstance(bindings, _WorkflowReconcileMapping)
        else None
    )
    edges = tuple(getattr(bundle, "action_edges", ()))
    matches = [
        edge
        for edge in edges
        if edge.get("id")
        == (
            authorization_edge_id
            if isinstance(authorization_edge_id, str)
            else request.action_edge_id
        )
    ]
    if len(matches) != 1:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EDGE_MISMATCH",
            "abandonment requires one exact same-node target edge",
        )
    edge = matches[0]
    trigger = edge.get("trigger")
    public_command = edge.get("public_command")
    values = (
        public_command.get("values")
        if isinstance(public_command, _WorkflowReconcileMapping)
        else None
    )
    if (
        not isinstance(trigger, _WorkflowReconcileMapping)
        or not isinstance(trigger.get("id"), str)
        or not isinstance(public_command, _WorkflowReconcileMapping)
        or not isinstance(public_command.get("id"), str)
        or not isinstance(values, (list, tuple))
        or len(values) != 1
        or not isinstance(values[0], str)
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CATALOG_INVALID",
            "abandonment target has no exact public action selection",
        )
    decision_name = decision.lower()
    decision_contract = (
        "abandonment"
        if decision == "ABANDONED"
        else "compensated"
    )
    evidence = {
        "contract": (
            "dev-flow-v3-workflow-action-"
            + decision_contract
            + "-evaluation/v1"
        ),
        "decision": decision,
        "attempt_id": request.attempt_id,
        "target_execution_id": request.target_execution_id,
        "target_record_sha256": target.get("record_sha256"),
        "effect_id": request.effect_id,
        "recovery_action_id": request.recovery_action_id,
        "gate_sha256": request.gate_sha256,
    }
    outcome = ActionOutcome(
        str(trigger["id"]),
        str(edge["id"]),
        evidence_records=(evidence,),
        proposed_state_delta={
            "set": {},
            "remove": [],
            "operations": [],
        },
        audit_facts=(
            AuditFact(
                "workflow-action-"
                + decision_name
                + "-noop-evaluated",
                evidence,
            ),
        ),
    )
    preview_evaluation = _workflow_action_evaluate_selected(
        state,
        bundle,
        edge,
        node_action=True,
        public_command=str(public_command["id"]),
        selector=str(values[0]),
        edge_selector=None,
        action_outcome=outcome,
        approval_outcome=None,
        action_parameters={
            "recovery_action_id": request.recovery_action_id,
            "effect_id": request.effect_id,
        },
        evidence=evidence,
        confirm_intent=None,
        preview=True,
        receipt_context=None,
        allow_unreceipted_reconciliation_noop=True,
    )
    if preview:
        return preview_evaluation
    evaluation = _workflow_action_evaluate_selected(
        state,
        bundle,
        edge,
        node_action=True,
        public_command=str(public_command["id"]),
        selector=str(values[0]),
        edge_selector=None,
        action_outcome=outcome,
        approval_outcome=None,
        action_parameters={
            "recovery_action_id": request.recovery_action_id,
            "effect_id": request.effect_id,
        },
        evidence=evidence,
        confirm_intent=str(
            preview_evaluation.intent["intent_id"]
        ),
        preview=False,
        receipt_context=None,
        allow_unreceipted_reconciliation_noop=True,
    )
    if evaluation.changed_paths:
        raise _workflow_reconcile_error(
            (
                "WORKFLOW_ACTION_RECONCILIATION_"
                + decision
                + "_MUTATION_FORBIDDEN"
            ),
            decision_name
            + " control evaluation changed business state",
            details={"changed_paths": list(evaluation.changed_paths)},
        )
    return evaluation


def preview_v3_workflow_action_abandonment(
    request: WorkflowActionReconciliationRequest,
    state: _WorkflowReconcileMapping[str, object],
    target: _WorkflowReconcileMapping[str, object],
) -> TransitionEvaluation:
    """Preview the exact no-business-outcome control evaluation."""

    return _workflow_reconcile_control_evaluation(
        request,
        state,
        target,
        decision="ABANDONED",
        preview=True,
    )


def evaluate_v3_workflow_action_abandonment(
    context: WorkflowActionReconciliationCommitContext,
) -> WorkflowActionReconciliationCommitPlan:
    """Mint one live no-op evaluation after fresh authority is installed."""

    if (
        type(context) is not WorkflowActionReconciliationCommitContext
        or context.decision != "ABANDONED"
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_CONTEXT_INVALID",
            "abandonment evaluation requires its exact live commit context",
        )
    evaluation = _workflow_reconcile_control_evaluation(
        context.request,
        context.current_state,
        context.target_journal,
        decision="ABANDONED",
        preview=False,
    )
    return WorkflowActionReconciliationCommitPlan(evaluation)


def preview_v3_workflow_action_compensation(
    request: WorkflowActionReconciliationRequest,
    state: _WorkflowReconcileMapping[str, object],
    target: _WorkflowReconcileMapping[str, object],
) -> TransitionEvaluation:
    """Preview the exact no-stale-candidate compensation commit."""

    return _workflow_reconcile_control_evaluation(
        request,
        state,
        target,
        decision="COMPENSATED",
        preview=True,
    )


def evaluate_v3_workflow_action_compensation(
    context: WorkflowActionReconciliationCommitContext,
) -> WorkflowActionReconciliationCommitPlan:
    """Mint a live no-op business evaluation after compensation settles."""

    if (
        type(context) is not WorkflowActionReconciliationCommitContext
        or context.decision != "COMPENSATED"
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_CONTEXT_INVALID",
            "compensation evaluation requires its exact live commit context",
        )
    evaluation = _workflow_reconcile_control_evaluation(
        context.request,
        context.current_state,
        context.target_journal,
        decision="COMPENSATED",
        preview=False,
    )
    return WorkflowActionReconciliationCommitPlan(evaluation)


@_workflow_reconcile_dataclass(frozen=True)
class _WorkflowActionReconciliationAuthorityFacts:
    state: dict[str, object]
    events: tuple[dict[str, object], ...]
    event_sha256: str
    outbox_sha256: str
    nonce_consumed: bool


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionCompensationPlan:
    """Typed versioned safe-input plan authorized before dispatch."""

    action_id: str
    effect_id: str
    safe_inputs: _WorkflowReconcileMapping[str, object]
    postcondition_contract_sha256: str
    schema: str = "dev-flow-v3-action-compensation-plan/v1"

    def __post_init__(self) -> None:
        try:
            normalized = normalize_compensation_plan(self.as_dict())
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_PLAN_INVALID",
                "compensation plan must satisfy the strict versioned schema",
            ) from exc
        object.__setattr__(
            self,
            "safe_inputs",
            _workflow_reconcile_copy.deepcopy(
                normalized["safe_inputs"]
            ),
        )

    def as_dict(self) -> dict[str, object]:
        safe_inputs = _workflow_reconcile_copy.deepcopy(
            dict(self.safe_inputs)
        )
        return {
            "schema": self.schema,
            "action_id": self.action_id,
            "effect_id": self.effect_id,
            "safe_inputs": safe_inputs,
            "safe_inputs_sha256": semantic_sha256(
                b"dev-flow-v3-action-effect-safe-input-v1\x00",
                safe_inputs,
            ),
            "postcondition_contract_sha256": (
                self.postcondition_contract_sha256
            ),
        }

    @property
    def plan_sha256(self) -> str:
        return compensation_plan_sha256(self.as_dict())


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionCompensationObservation:
    """The only accepted synchronous dispatcher response."""

    effect_receipt_sha256: str
    postcondition_proof_sha256: str

    def __post_init__(self) -> None:
        _workflow_reconcile_sha256(
            self.effect_receipt_sha256,
            "effect_receipt_sha256",
        )
        _workflow_reconcile_sha256(
            self.postcondition_proof_sha256,
            "postcondition_proof_sha256",
        )


@_workflow_reconcile_dataclass(frozen=True)
class WorkflowActionCompensationApproval:
    """One digest-only half of a future host/workflow dual approval."""

    authority: str
    principal: str
    approval_sha256: str
    compensation_plan_sha256: str | None = None
    target_journal_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.authority not in {"host", "workflow"}:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_DUAL_APPROVAL_REQUIRED",
                "compensation approval authority must be host or workflow",
            )
        _workflow_reconcile_text(self.principal, "approval principal")
        _workflow_reconcile_sha256(
            self.approval_sha256, "approval_sha256"
        )
        if self.compensation_plan_sha256 is not None:
            _workflow_reconcile_sha256(
                self.compensation_plan_sha256,
                "compensation_plan_sha256",
            )
        if self.target_journal_sha256 is not None:
            _workflow_reconcile_sha256(
                self.target_journal_sha256,
                "target_journal_sha256",
            )


def _workflow_reconcile_make_proof_boundary():
    marker = object()
    live: dict[str, tuple[str, dict[str, object], bytes]] = {}
    key = _workflow_reconcile_secrets.token_bytes(32)

    class WorkflowActionReconciliationProof:
        """Opaque, process-local, one-shot reconciliation authority."""

        __slots__ = ("__issuance_id", "__mac")

        def __init__(
            self,
            issuance_id: str,
            mac: bytes,
            *,
            _marker: object,
        ) -> None:
            if _marker is not marker:
                raise TypeError(
                    "reconciliation proofs are issued by a live challenge"
                )
            object.__setattr__(
                self,
                "_WorkflowActionReconciliationProof__issuance_id",
                issuance_id,
            )
            object.__setattr__(
                self,
                "_WorkflowActionReconciliationProof__mac",
                mac,
            )

        def __repr__(self) -> str:
            return "<WorkflowActionReconciliationProof opaque>"

        def __copy__(self) -> object:
            raise TypeError("reconciliation proof cannot be copied")

        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise TypeError("reconciliation proof cannot be deep-copied")

        def __reduce__(self) -> object:
            raise TypeError("reconciliation proof cannot be serialized")

        def __reduce_ex__(self, protocol: int) -> object:
            del protocol
            raise TypeError("reconciliation proof cannot be serialized")

    def issue(
        challenge_id: str,
        payload: dict[str, object],
    ) -> WorkflowActionReconciliationProof:
        issuance_id = _workflow_reconcile_secrets.token_hex(24)
        payload_bytes = semantic_json_bytes(payload)
        mac = _workflow_reconcile_hmac.digest(
            key,
            (
                _WORKFLOW_RECONCILE_PROOF_DOMAIN
                + challenge_id.encode("ascii")
                + b"\x00"
                + issuance_id.encode("ascii")
                + b"\x00"
                + payload_bytes
            ),
            "sha256",
        )
        live[issuance_id] = (challenge_id, payload, mac)
        return WorkflowActionReconciliationProof(
            issuance_id, mac, _marker=marker
        )

    def consume(
        proof: object,
        challenge_id: str,
    ) -> dict[str, object]:
        if type(proof) is not WorkflowActionReconciliationProof:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_PROOF_INVALID",
                "verifier must return the exact opaque proof type",
            )
        issuance_id = object.__getattribute__(
            proof,
            "_WorkflowActionReconciliationProof__issuance_id",
        )
        supplied_mac = object.__getattribute__(
            proof,
            "_WorkflowActionReconciliationProof__mac",
        )
        record = live.pop(issuance_id, None)
        if (
            record is None
            or record[0] != challenge_id
            or not _workflow_reconcile_hmac.compare_digest(
                supplied_mac, record[2]
            )
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_PROOF_REPLAY",
                "proof is stale, replayed, or bound to another challenge",
            )
        return _workflow_reconcile_copy.deepcopy(record[1])

    return WorkflowActionReconciliationProof, issue, consume


(
    WorkflowActionReconciliationProof,
    _workflow_reconcile_issue_proof,
    _workflow_reconcile_consume_proof,
) = _workflow_reconcile_make_proof_boundary()


def _workflow_reconcile_make_live_observation_boundary():
    """Create one process-local, one-shot observation authority."""

    marker = object()
    live: dict[object, str] = {}

    class WorkflowActionAbandonmentObservation:
        """Opaque proof of one target-bound live V4 observation."""

        __slots__ = ("_marker", "_record")

        def __init__(self, record: object, *, _marker: object) -> None:
            if _marker is not marker:
                raise TypeError(
                    "abandonment observations are issued by a live challenge"
                )
            self._marker = marker
            self._record = record

        def __repr__(self) -> str:
            return "<WorkflowActionAbandonmentObservation opaque>"

        def __copy__(self) -> object:
            raise TypeError("abandonment observation cannot be copied")

        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise TypeError(
                "abandonment observation cannot be deep-copied"
            )

        def __reduce__(self) -> object:
            raise TypeError(
                "abandonment observation cannot be serialized"
            )

        def __reduce_ex__(self, protocol: int) -> object:
            del protocol
            raise TypeError(
                "abandonment observation cannot be serialized"
            )

    def issue(observation_evidence_sha256: str) -> object:
        record = object()
        live[record] = _workflow_reconcile_sha256(
            observation_evidence_sha256,
            "observation_evidence_sha256",
        )
        return WorkflowActionAbandonmentObservation(
            record, _marker=marker
        )

    def consume(value: object) -> str:
        if type(value) is not WorkflowActionAbandonmentObservation:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_REQUIRED",
                "V4 abandonment requires package-owned live observation authority",
            )
        record = object.__getattribute__(value, "_record")
        observation_evidence_sha256 = live.pop(record, None)
        if observation_evidence_sha256 is None:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_REPLAY",
                "live abandonment observation is stale or already consumed",
            )
        return observation_evidence_sha256

    return WorkflowActionAbandonmentObservation, issue, consume


(
    WorkflowActionAbandonmentObservation,
    _workflow_reconcile_issue_live_observation,
    _workflow_reconcile_consume_live_observation,
) = _workflow_reconcile_make_live_observation_boundary()


def _workflow_reconcile_make_compensation_dispatch_boundary():
    """Wrap the sole V4 bridge-backed compensation invocation path."""

    marker = object()

    class WorkflowActionCompensationDispatcher:
        """Opaque package-owned dispatcher; never a durable authority."""

        __slots__ = ("_callback", "_marker")

        def __init__(self, callback: object, *, _marker: object) -> None:
            if _marker is not marker or not callable(callback):
                raise TypeError(
                    "compensation dispatchers are package-issued"
                )
            self._callback = callback
            self._marker = marker

        def __call__(self, permit: object) -> object:
            return self._callback(permit)

        def __repr__(self) -> str:
            return "<WorkflowActionCompensationDispatcher opaque>"

        def __copy__(self) -> object:
            raise TypeError("compensation dispatcher cannot be copied")

        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise TypeError(
                "compensation dispatcher cannot be deep-copied"
            )

        def __reduce__(self) -> object:
            raise TypeError(
                "compensation dispatcher cannot be serialized"
            )

        def __reduce_ex__(self, protocol: int) -> object:
            del protocol
            raise TypeError(
                "compensation dispatcher cannot be serialized"
            )

    def wrap(callback: object) -> object:
        return WorkflowActionCompensationDispatcher(
            callback, _marker=marker
        )

    return WorkflowActionCompensationDispatcher, wrap


(
    WorkflowActionCompensationDispatcher,
    _workflow_reconcile_wrap_compensation_dispatcher,
) = _workflow_reconcile_make_compensation_dispatch_boundary()


class WorkflowActionAbandonmentObservationChallenge:
    """Exact live V4 target material exposed to the controller observer."""

    __slots__ = ("_containments", "_issued", "_request", "_target")

    def __init__(
        self,
        request: WorkflowActionReconciliationRequest,
        target: _WorkflowReconcileMapping[str, object],
        containments: _WorkflowReconcileSequence[
            _WorkflowReconcileMapping[str, object]
        ],
    ) -> None:
        self._request = request
        self._target = _workflow_reconcile_copy.deepcopy(dict(target))
        self._containments = tuple(
            _workflow_reconcile_copy.deepcopy(dict(item))
            for item in containments
        )
        self._issued = False

    @property
    def request(self) -> WorkflowActionReconciliationRequest:
        return self._request

    @property
    def target(self) -> dict[str, object]:
        return _workflow_reconcile_copy.deepcopy(self._target)

    @property
    def containments(self) -> tuple[dict[str, object], ...]:
        return tuple(
            _workflow_reconcile_copy.deepcopy(item)
            for item in self._containments
        )

    def confirm(
        self,
        *,
        request: WorkflowActionReconciliationRequest,
        target: _WorkflowReconcileMapping[str, object],
        containments: _WorkflowReconcileSequence[
            _WorkflowReconcileMapping[str, object]
        ],
        observed_quiescence: str,
        observed_business_outcome: str,
        observation_evidence_sha256: str,
    ) -> object:
        if self._issued:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_REPLAY",
                "one live observation challenge can be confirmed only once",
            )
        if request is not self._request:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_MISMATCH",
                "live observer named another reconciliation request",
            )
        try:
            exact_target = _workflow_reconcile_hmac.compare_digest(
                semantic_json_bytes(dict(target)),
                semantic_json_bytes(self._target),
            )
            exact_containments = _workflow_reconcile_hmac.compare_digest(
                semantic_json_bytes(
                    [dict(item) for item in containments]
                ),
                semantic_json_bytes(list(self._containments)),
            )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_MISMATCH",
                "live observer returned non-canonical target material",
            ) from exc
        if not exact_target or not exact_containments:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_MISMATCH",
                "live observer did not bind the exact target and containments",
            )
        if self._target.get("receipt") is not None:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_OUTCOME_EXISTS",
                "a complete stored receipt forbids abandonment",
            )
        if (
            observed_quiescence != "QUIESCENT"
            or observed_business_outcome != "ABSENT"
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_INCOMPLETE",
                "live observer must affirm quiescence and absent business outcome",
            )
        if not self._containments or any(
            item.get("phase") != "CLOSED"
            for item in self._containments
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_QUIESCENCE_REQUIRED",
                "live abandonment requires every containment to be closed",
            )
        self._issued = True
        return _workflow_reconcile_issue_live_observation(
            observation_evidence_sha256
        )


class WorkflowActionReconciliationChallenge:
    """Current, exact facts exposed only to the process-local verifier."""

    __slots__ = (
        "_challenge_id",
        "_containments",
        "_issued",
        "_live_abandonment_observer",
        "_request",
        "_target",
    )

    def __init__(
        self,
        request: WorkflowActionReconciliationRequest,
        target: _WorkflowReconcileMapping[str, object],
        containments: _WorkflowReconcileSequence[
            _WorkflowReconcileMapping[str, object]
        ],
        live_abandonment_observer: _WorkflowReconcileCallable[
            [WorkflowActionAbandonmentObservationChallenge], object
        ]
        | None = None,
    ) -> None:
        self._challenge_id = _workflow_reconcile_secrets.token_hex(24)
        self._request = request
        self._target = _workflow_reconcile_copy.deepcopy(dict(target))
        self._containments = tuple(
            _workflow_reconcile_copy.deepcopy(dict(item))
            for item in containments
        )
        self._live_abandonment_observer = live_abandonment_observer
        self._issued = False

    @property
    def request(self) -> WorkflowActionReconciliationRequest:
        return self._request

    @property
    def target(self) -> dict[str, object]:
        return _workflow_reconcile_copy.deepcopy(self._target)

    @property
    def containments(self) -> tuple[dict[str, object], ...]:
        return tuple(
            _workflow_reconcile_copy.deepcopy(item)
            for item in self._containments
        )

    def _issue(self, payload: dict[str, object]) -> object:
        if self._issued:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_PROOF_REPLAY",
                "one challenge can issue only one decision proof",
            )
        self._issued = True
        return _workflow_reconcile_issue_proof(
            self._challenge_id, payload
        )

    def accepted(
        self,
        *,
        complete_receipt: _WorkflowReconcileMapping[str, object],
        postcondition_evidence_sha256: str,
    ) -> object:
        target_receipt = self._target.get("receipt")
        try:
            same_receipt = _workflow_reconcile_hmac.compare_digest(
                semantic_json_bytes(dict(complete_receipt)),
                semantic_json_bytes(target_receipt),
            )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_RECEIPT_INVALID",
                "accepted proof must carry the complete stored receipt",
            ) from exc
        if not isinstance(target_receipt, dict) or not same_receipt:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_RECEIPT_MISMATCH",
                "accepted proof differs from the complete stored receipt",
            )
        return self._closing(
            "ACCEPTED",
            evidence_sha256=postcondition_evidence_sha256,
            complete_receipt=target_receipt,
        )

    def abandoned(
        self,
        *,
        quiescence_evidence_sha256: str | None = None,
        no_business_outcome_evidence_sha256: str | None = None,
    ) -> object:
        if self._target.get("receipt") is not None:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_OUTCOME_EXISTS",
                "a complete stored receipt forbids abandonment",
            )
        if not self._containments or any(
            item.get("phase") != "CLOSED"
            for item in self._containments
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_QUIESCENCE_REQUIRED",
                "abandonment requires every containment to be durably closed",
            )
        if self._request.workflow_version == "4":
            if (
                quiescence_evidence_sha256 is not None
                or no_business_outcome_evidence_sha256 is not None
            ):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_CALLER_AUTHORITY_FORBIDDEN",
                    "caller digests cannot authorize V4 abandonment",
                )
            observer = self._live_abandonment_observer
            if not callable(observer):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_LIVE_OBSERVATION_REQUIRED",
                    "V4 abandonment requires a package-owned live observer",
                )
            observation_challenge = (
                WorkflowActionAbandonmentObservationChallenge(
                    self._request,
                    self._target,
                    self._containments,
                )
            )
            observation = observer(observation_challenge)
            observation_evidence_sha256 = (
                _workflow_reconcile_consume_live_observation(
                    observation
                )
            )
            evidence = semantic_sha256(
                _WORKFLOW_RECONCILE_LIVE_ABANDONMENT_DOMAIN,
                {
                    "task_id": self._request.task_id,
                    "workflow_id": self._request.workflow_id,
                    "workflow_version": self._request.workflow_version,
                    "workflow_bundle_sha256": (
                        self._request.workflow_bundle_sha256
                    ),
                    "action_edge_id": self._request.action_edge_id,
                    "target_execution_id": (
                        self._request.target_execution_id
                    ),
                    "effect_id": self._request.effect_id,
                    "attempt_id": self._request.attempt_id,
                    "current_task_revision": (
                        self._request.current_task_revision
                    ),
                    "target_journal_sha256": self._target.get(
                        "record_sha256"
                    ),
                    "containment_sha256s": [
                        item.get("record_sha256")
                        for item in self._containments
                    ],
                    "live_observation_evidence_sha256": (
                        observation_evidence_sha256
                    ),
                },
            )
            return self._closing(
                "ABANDONED",
                evidence_sha256=evidence,
                complete_receipt=None,
            )
        evidence = semantic_sha256(
            _WORKFLOW_RECONCILE_ABANDONMENT_DOMAIN,
            {
                "quiescence_evidence_sha256": _workflow_reconcile_sha256(
                    quiescence_evidence_sha256,
                    "quiescence_evidence_sha256",
                ),
                "no_business_outcome_evidence_sha256": (
                    _workflow_reconcile_sha256(
                        no_business_outcome_evidence_sha256,
                        "no_business_outcome_evidence_sha256",
                    )
                ),
            },
        )
        return self._closing(
            "ABANDONED",
            evidence_sha256=evidence,
            complete_receipt=None,
        )

    def unresolved(
        self,
        *,
        diagnostic_evidence_sha256: str,
    ) -> object:
        return self._issue(
            {
                "decision": "UNRESOLVED",
                "evidence_sha256": _workflow_reconcile_sha256(
                    diagnostic_evidence_sha256,
                    "diagnostic_evidence_sha256",
                ),
                "complete_receipt": None,
            }
        )

    def compensated(
        self,
        *,
        compensation_execution_id: str,
        compensation_plan: WorkflowActionCompensationPlan,
        approvals: _WorkflowReconcileSequence[
            WorkflowActionCompensationApproval
        ]
        | None = None,
    ) -> object:
        if (
            self._request.workflow_version == "4"
            and approvals is not None
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CALLER_AUTHORITY_FORBIDDEN",
                "caller approval objects and digests cannot authorize V4 compensation",
            )
        if (
            self._request.workflow_version == "4"
            and type(compensation_plan)
            is WorkflowActionCompensationPlan
            and approvals is None
        ):
            plan = compensation_plan.as_dict()
            plan_sha256 = compensation_plan.plan_sha256
            target_sha256 = str(self._target["record_sha256"])
            workflow_binding_sha256 = semantic_sha256(
                _WORKFLOW_RECONCILE_DUAL_APPROVAL_DOMAIN,
                {
                    "authority_kind": "controller-gate-binding",
                    "task_id": self._request.task_id,
                    "workflow_id": self._request.workflow_id,
                    "workflow_version": self._request.workflow_version,
                    "workflow_bundle_sha256": (
                        self._request.workflow_bundle_sha256
                    ),
                    "action_edge_id": self._request.action_edge_id,
                    "target_execution_id": (
                        self._request.target_execution_id
                    ),
                    "compensation_execution_id": (
                        compensation_execution_id
                    ),
                    "effect_id": self._request.effect_id,
                    "gate_sha256": self._request.gate_sha256,
                    "request_nonce_sha256": (
                        self._request.request_nonce_sha256
                    ),
                    "compensation_plan_sha256": plan_sha256,
                    "target_journal_sha256": target_sha256,
                },
            )
            host_binding_sha256 = semantic_sha256(
                _WORKFLOW_RECONCILE_DUAL_APPROVAL_DOMAIN,
                {
                    "authority_kind": "host-bridge-required",
                    "workflow_binding_sha256": (
                        workflow_binding_sha256
                    ),
                    "compensation_plan_sha256": plan_sha256,
                    "target_journal_sha256": target_sha256,
                },
            )
            dual_binding_sha256 = semantic_sha256(
                _WORKFLOW_RECONCILE_DUAL_APPROVAL_DOMAIN,
                {
                    "compensation_plan_sha256": plan_sha256,
                    "target_journal_sha256": target_sha256,
                    "host_bridge_required_sha256": (
                        host_binding_sha256
                    ),
                    "controller_gate_binding_sha256": (
                        workflow_binding_sha256
                    ),
                },
            )
            return self._issue(
                {
                    "decision": "COMPENSATE",
                    "evidence_sha256": (
                        compensation_plan.postcondition_contract_sha256
                    ),
                    "complete_receipt": None,
                    "compensation_execution_id": (
                        _workflow_reconcile_text(
                            compensation_execution_id,
                            "compensation_execution_id",
                        )
                    ),
                    "compensation_plan": plan,
                    "compensation_plan_sha256": plan_sha256,
                    # These persisted values are exact audit bindings.  The
                    # only live host authority is the one-shot grant consumed
                    # by HostOwnedExternalWriteBridge at provider invocation.
                    "dual_approval_sha256": dual_binding_sha256,
                    "host_principal": "host:live-external-write-bridge",
                    "host_approval_sha256": host_binding_sha256,
                    "workflow_principal": self._request.principal,
                    "workflow_approval_sha256": (
                        workflow_binding_sha256
                    ),
                }
            )
        if (
            type(compensation_plan)
            is not WorkflowActionCompensationPlan
            or
            not isinstance(approvals, (tuple, list))
            or len(approvals) != 2
            or any(
                type(item) is not WorkflowActionCompensationApproval
                for item in approvals
            )
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_DUAL_APPROVAL_REQUIRED",
                "compensation requires exact host and workflow approvals",
            )
        plan = compensation_plan.as_dict()
        plan_sha256 = compensation_plan.plan_sha256
        target_sha256 = str(self._target["record_sha256"])
        by_authority = {item.authority: item for item in approvals}
        if (
            set(by_authority) != {"host", "workflow"}
            or len(
                {item.principal for item in by_authority.values()}
            )
            != 2
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_DUAL_APPROVAL_REQUIRED",
                "host and workflow approvals require distinct principals",
            )
        wrong_bindings = sorted(
            item.authority
            for item in by_authority.values()
            if (
                item.compensation_plan_sha256 != plan_sha256
                or item.target_journal_sha256 != target_sha256
            )
        )
        if wrong_bindings:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_APPROVAL_MISMATCH",
                "each approval must bind the exact plan and target journal",
                details={"authorities": wrong_bindings},
            )
        dual_approval_sha256 = semantic_sha256(
            _WORKFLOW_RECONCILE_DUAL_APPROVAL_DOMAIN,
            {
                "compensation_plan_sha256": plan_sha256,
                "target_journal_sha256": target_sha256,
                "approvals": [
                    {
                        "authority": authority,
                        "principal": by_authority[
                            authority
                        ].principal,
                        "approval_sha256": by_authority[
                            authority
                        ].approval_sha256,
                    }
                    for authority in ("host", "workflow")
                ],
            },
        )
        return self._issue(
            {
                "decision": "COMPENSATE",
                "evidence_sha256": compensation_plan.postcondition_contract_sha256,
                "complete_receipt": None,
                "compensation_execution_id": _workflow_reconcile_text(
                    compensation_execution_id,
                    "compensation_execution_id",
                ),
                "compensation_plan": plan,
                "compensation_plan_sha256": plan_sha256,
                "dual_approval_sha256": dual_approval_sha256,
                "host_principal": by_authority["host"].principal,
                "host_approval_sha256": by_authority[
                    "host"
                ].approval_sha256,
                "workflow_principal": by_authority[
                    "workflow"
                ].principal,
                "workflow_approval_sha256": by_authority[
                    "workflow"
                ].approval_sha256,
            }
        )

    def _closing(
        self,
        decision: str,
        *,
        evidence_sha256: str,
        complete_receipt: dict[str, object] | None,
    ) -> object:
        return self._issue(
            {
                "decision": decision,
                "evidence_sha256": _workflow_reconcile_sha256(
                    evidence_sha256, "evidence_sha256"
                ),
                "complete_receipt": _workflow_reconcile_copy.deepcopy(
                    complete_receipt
                ),
            }
        )


def _workflow_reconcile_reauthenticate(
    target: _WorkflowReconcileMapping[str, object],
    reauthenticate: _WorkflowReconcileCallable[
        [], str | bytes | None
    ],
) -> str | bytes | None:
    if not callable(reauthenticate):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_REQUIRED",
            "reconciliation requires a process-local reauthentication callback",
        )
    try:
        secret = reauthenticate()
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
            "target journal authorization could not be reauthenticated",
        ) from exc
    bindings = target.get("bindings")
    kind = (
        bindings.get("authorization_kind")
        if isinstance(bindings, _WorkflowReconcileMapping)
        else None
    )
    if kind == "manager":
        if not isinstance(secret, (str, bytes)) or not secret:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
                "manager target requires its live authentication secret",
            )
    elif secret is not None:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
            "operator target cannot accept a manager secret",
        )
    return secret


def _workflow_reconcile_validate_target(
    request: WorkflowActionReconciliationRequest,
    target: _WorkflowReconcileMapping[str, object],
    index: _WorkflowReconcileMapping[str, object],
) -> None:
    bindings = target.get("bindings")
    effects = target.get("effects")
    quarantine = target.get("quarantine")
    if (
        target.get("phase") != "QUARANTINED"
        or not isinstance(bindings, _WorkflowReconcileMapping)
        or not isinstance(effects, list)
        or not isinstance(quarantine, _WorkflowReconcileMapping)
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TARGET_INVALID",
            "target must be one exact active quarantined action journal",
        )
    expected = {
        "task_id": request.task_id,
        "workflow_id": request.workflow_id,
        "workflow_version": request.workflow_version,
        "workflow_bundle_sha256": request.workflow_bundle_sha256,
        "action_edge_id": request.action_edge_id,
        "execution_id": request.target_execution_id,
    }
    actual = {
        "task_id": target.get("task_id"),
        "workflow_id": bindings.get("workflow_id"),
        "workflow_version": bindings.get("workflow_version"),
        "workflow_bundle_sha256": bindings.get(
            "workflow_bundle_sha256"
        ),
        "action_edge_id": bindings.get("action_edge_id"),
        "execution_id": target.get("execution_id"),
    }
    mismatches = sorted(
        key for key, value in expected.items() if actual.get(key) != value
    )
    target_effect = next(
        (
            item
            for item in effects
            if isinstance(item, _WorkflowReconcileMapping)
            and item.get("effect_id") == request.effect_id
        ),
        None,
    )
    if target_effect is None:
        mismatches.append("effect_id")
    if quarantine.get("effect_id") not in {None, request.effect_id}:
        mismatches.append("quarantine.effect_id")
    if semantic_json_bytes(bindings.get("scopes")) != semantic_json_bytes(
        request.scopes
    ):
        mismatches.append("scopes")
    if index.get("task_id") != request.task_id:
        mismatches.append("index.task_id")
    if mismatches:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_BINDING_MISMATCH",
            "request differs from the quarantined execution",
            details={"fields": sorted(set(mismatches))},
        )
    if request.attempt_id == request.target_execution_id:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_ATTEMPT_INVALID",
            "reconciliation attempt requires a distinct fresh identity",
        )
    stale_values = {
        "authorization_sha256": bindings.get("authorization_sha256"),
        "gate_sha256": bindings.get("guard_projection_sha256"),
        "request_nonce_sha256": bindings.get("request_nonce_sha256"),
        "engine_proof_sha256": bindings.get(
            "verifier_before_sha256"
        ),
    }
    receipt = target.get("receipt")
    if isinstance(receipt, _WorkflowReconcileMapping):
        stale_values["engine_proof_sha256"] = receipt.get(
            "engine_proof_sha256"
        )
    reused = sorted(
        key
        for key, stale in stale_values.items()
        if getattr(request, key) == stale
    )
    if reused:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_FRESH_AUTHORITY_REQUIRED",
            "reconciliation must use fresh authorization, gate, nonce, and proof",
            details={"fields": reused},
        )


def _workflow_reconcile_containments(
    store: ActionExecutionStore,
    target: _WorkflowReconcileMapping[str, object],
) -> tuple[dict[str, object], ...]:
    effects = target.get("effects")
    assert isinstance(effects, list)
    records = []
    for effect in effects:
        assert isinstance(effect, _WorkflowReconcileMapping)
        try:
            record = store.read_containment(
                str(target["execution_id"]),
                str(effect["effect_id"]),
            )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CONTAINMENT_MISSING",
                "every quarantined effect requires its durable containment",
                details={"effect_id": effect.get("effect_id")},
            ) from exc
        if (
            record.get("task_id") != target.get("task_id")
            or record.get("execution_id") != target.get("execution_id")
            or record.get("record_sha256")
            != effect.get("containment_record_sha256")
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CONTAINMENT_MISMATCH",
                "containment is not the exact journal cross-link",
                details={"effect_id": effect.get("effect_id")},
            )
        records.append(record)
    return tuple(records)


def _workflow_reconcile_existing_control(
    store: ActionExecutionStore,
    request: WorkflowActionReconciliationRequest,
    index: _WorkflowReconcileMapping[str, object],
) -> dict[str, object] | None:
    entries = index.get("entries")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if (
            not isinstance(entry, _WorkflowReconcileMapping)
            or entry.get("entry_kind") != "control"
            or entry.get("target_execution_id")
            != request.target_execution_id
        ):
            continue
        attempt_id = entry.get("execution_id")
        try:
            attempt = store.read_reconciliation(str(attempt_id))
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CONTROL_BLOCKED",
                "an existing target control cannot be safely classified",
                details={"attempt_id": attempt_id},
            ) from exc
        if attempt.get("phase") == "UNRESOLVED":
            if (
                request.replaces_attempt_id is not None
                and request.replaces_attempt_id != attempt_id
            ):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_REPLACEMENT_MISMATCH",
                    "fresh request names another unresolved predecessor",
                )
            return attempt
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CONTROL_BLOCKED",
            "another reconciliation control remains active for the target",
            details={
                "attempt_id": attempt_id,
                "phase": attempt.get("phase"),
            },
        )
    return None


def _workflow_reconcile_event_payload(
    request: WorkflowActionReconciliationRequest,
    *,
    decision: str,
    evidence_sha256: str,
    receipt_sha256: str | None,
) -> dict[str, object]:
    terminal_decision = (
        "COMPENSATED" if decision == "COMPENSATE" else decision
    )
    if terminal_decision not in {
        "ACCEPTED",
        "ABANDONED",
        "COMPENSATED",
    }:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_DECISION_INVALID",
            "only a closing decision may produce a task event",
        )
    if terminal_decision in {"ACCEPTED", "COMPENSATED"}:
        receipt_sha256 = _workflow_reconcile_sha256(
            receipt_sha256, "receipt_sha256"
        )
    elif receipt_sha256 is not None:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_RECEIPT_INVALID",
            "abandonment cannot claim a business or compensation receipt",
        )
    return {
        "schema": _WORKFLOW_RECONCILE_EVENT_SCHEMA,
        "recovery_action_id": request.recovery_action_id,
        "action_edge_id": request.action_edge_id,
        "attempt_id": request.attempt_id,
        "target_execution_id": request.target_execution_id,
        "effect_id": request.effect_id,
        "decision": terminal_decision,
        "evidence_sha256": _workflow_reconcile_sha256(
            evidence_sha256, "evidence_sha256"
        ),
        "receipt_sha256": receipt_sha256,
        "authorization_kind": request.authorization_kind,
        "authorization_sha256": request.authorization_sha256,
        "capability_sha256": request.capability_sha256,
        "gate_sha256": request.gate_sha256,
        "request_nonce_sha256": request.request_nonce_sha256,
        "engine_proof_sha256": request.engine_proof_sha256,
    }


def _workflow_reconcile_read_events(
    path: _WorkflowReconcilePath,
) -> tuple[dict[str, object], ...]:
    try:
        values = tuple(
            _workflow_reconcile_json.loads(line)
            for line in path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        )
    except (
        OSError,
        UnicodeError,
        _workflow_reconcile_json.JSONDecodeError,
    ) as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_OUTBOX_INVALID",
            "authoritative task event log could not be read",
        ) from exc
    if any(not isinstance(item, dict) for item in values):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_OUTBOX_INVALID",
            "authoritative task event log contains a non-object record",
        )
    return values


def _workflow_reconcile_authority_facts(
    task_path: _WorkflowReconcilePath,
    request: WorkflowActionReconciliationRequest,
    *,
    event_type: str,
    event_payload: _WorkflowReconcileMapping[str, object],
) -> _WorkflowActionReconciliationAuthorityFacts | None:
    state_path = task_path / "state.json"
    try:
        raw_state = _read_task_state_json(state_path)
        if not isinstance(raw_state, dict):
            raise TypeError("task state is not an object")
        _validate_task_state_snapshot(state_path, raw_state)
        pending = raw_state.get("pending_events")
        if pending is None and raw_state.get("pending_event") is not None:
            pending = [raw_state["pending_event"]]
        pending_events = (
            tuple(_workflow_reconcile_copy.deepcopy(pending))
            if isinstance(pending, list)
            else ()
        )
        state = load_state(state_path)
    except WorkflowActionReconciliationError:
        raise
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_STATE_INVALID",
            "authoritative task state could not be validated",
        ) from exc
    expected_revision = request.current_task_revision + 1
    actual_revision = state.get("revision")
    if (
        isinstance(actual_revision, int)
        and not isinstance(actual_revision, bool)
        and actual_revision < expected_revision
    ):
        return None
    if (
        state.get("task_id") != request.task_id
        or actual_revision != expected_revision
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_AUTHORITY_DRIFT",
            "task state does not remain at the exact recovery revision",
            details={
                "expected_revision": expected_revision,
                "actual_revision": actual_revision,
            },
        )
    events = (
        pending_events
        if pending_events
        else _workflow_reconcile_read_events(
            task_path / "events.jsonl"
        )
    )
    primary = [
        event
        for event in events
        if (
            event.get("task_id") == request.task_id
            and event.get("previous_revision")
            == request.current_task_revision
            and event.get("revision") == expected_revision
            and event.get("type") == event_type
            and isinstance(
                event.get("payload"),
                _WorkflowReconcileMapping,
            )
            and _workflow_reconcile_hmac.compare_digest(
                semantic_json_bytes(event["payload"]),
                semantic_json_bytes(dict(event_payload)),
            )
        )
    ]
    if not primary:
        return None
    if len(primary) != 1:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_OUTBOX_INVALID",
            "authoritative outbox contains duplicate recovery events",
        )
    event = primary[0]
    transaction_id = event.get("transaction_id")
    if transaction_id is None:
        batch = (event,)
    else:
        batch = tuple(
            candidate
            for candidate in events
            if candidate.get("transaction_id") == transaction_id
        )
    if (
        not batch
        or any(
            candidate.get("task_id") != request.task_id
            or candidate.get("previous_revision")
            != request.current_task_revision
            or candidate.get("revision") != expected_revision
            for candidate in batch
        )
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_OUTBOX_INVALID",
            "recovery event batch is not one exact task transaction",
        )
    manager_event_type = globals().get(
        "MANAGER_CAPABILITY_AUTHORIZED_EVENT",
        "manager_capability_request_consumed",
    )
    manager_events = [
        candidate
        for candidate in batch
        if candidate.get("type") == manager_event_type
    ]
    if request.authorization_kind == "manager":
        if (
            len(manager_events) != 1
            or not isinstance(
                manager_events[0].get("payload"),
                _WorkflowReconcileMapping,
            )
            or manager_events[0]["payload"].get(
                "request_nonce_sha256"
            )
            != request.request_nonce_sha256
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_NONCE_NOT_CONSUMED",
                "manager recovery lacks one exact same-transaction nonce event",
            )
        nonce_consumed = True
    else:
        if manager_events:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_NONCE_INVALID",
                "operator recovery cannot claim a manager nonce event",
            )
        nonce_consumed = False
    return _WorkflowActionReconciliationAuthorityFacts(
        state=_workflow_reconcile_copy.deepcopy(state),
        events=tuple(
            _workflow_reconcile_copy.deepcopy(item) for item in batch
        ),
        event_sha256=semantic_sha256(
            _WORKFLOW_RECONCILE_EVENT_DOMAIN, event
        ),
        outbox_sha256=semantic_sha256(
            _WORKFLOW_RECONCILE_OUTBOX_DOMAIN, list(batch)
        ),
        nonce_consumed=nonce_consumed,
    )


def _workflow_reconcile_validate_accepted_candidate(
    request: WorkflowActionReconciliationRequest,
    evaluation: TransitionEvaluation,
    target: _WorkflowReconcileMapping[str, object],
    pre_effect_state: _WorkflowReconcileMapping[str, object],
) -> None:
    receipt = target.get("receipt")
    bindings = target.get("bindings")
    if not isinstance(receipt, _WorkflowReconcileMapping) or not isinstance(
        bindings, _WorkflowReconcileMapping
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_RECEIPT_INVALID",
            "acceptance requires the complete stored target receipt",
        )
    if request.authorization_kind == "operator":
        try:
            _workflow_action_validate_receipt_candidate(
                evaluation, receipt, target
            )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CANDIDATE_MISMATCH",
                "fresh recovery evaluation differs from the stored receipt candidate",
            ) from exc
        return
    try:
        revision_policy = str(bindings["revision_policy"])
        neutral_candidate = (
            _workflow_action_manager_neutral_candidate(
                evaluation, pre_effect_state
            )
        )
        if revision_policy == "exact-revision":
            candidate_sha256 = _sha256_contract(neutral_candidate)
        elif revision_policy == "disjoint-scope-revalidate":
            projection = []
            for pointer in sorted(
                set(evaluation.changed_paths),
                key=lambda item: item.encode("utf-8"),
            ):
                before_present, before_value = (
                    _transition_engine_pointer_get(
                        pre_effect_state, pointer
                    )
                )
                present, value = _transition_engine_pointer_get(
                    neutral_candidate, pointer
                )
                if (
                    before_present == present
                    and (
                        not present
                        or semantic_json_bytes(before_value)
                        == semantic_json_bytes(value)
                    )
                ):
                    continue
                projection.append(
                    {
                        "path": pointer,
                        "present": present,
                        "value": (
                            _workflow_transition_public(value)
                            if present
                            else None
                        ),
                    }
                )
            candidate_sha256 = semantic_sha256(
                _workflow_action_scoped_candidate_domain,
                {
                    "edge_id": evaluation.edge_id,
                    "changed_paths": projection,
                },
            )
        else:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_CANDIDATE_MISMATCH",
                "target uses an unsupported revision policy",
            )
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CANDIDATE_MISMATCH",
            "manager recovery candidate projection could not be verified",
        ) from exc
    if (
        candidate_sha256 != bindings.get("candidate_after_sha256")
        or receipt.get("completion_edge_id") != evaluation.edge_id
        or bindings.get("completion_edge_id") != evaluation.edge_id
        or receipt.get("authorization_action_edge_id")
        != bindings.get("authorization_action_edge_id")
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CANDIDATE_MISMATCH",
            "fresh manager recovery candidate differs outside nonce state",
        )


def _workflow_reconcile_commit(
    task_path: _WorkflowReconcilePath,
    request: WorkflowActionReconciliationRequest,
    *,
    decision: str,
    evidence_sha256: str,
    receipt_sha256: str | None,
    target: _WorkflowReconcileMapping[str, object],
    attempt: _WorkflowReconcileMapping[str, object],
    commit_evaluator: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext],
        WorkflowActionReconciliationCommitPlan,
    ],
    commit_authorizer: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext], object
    ]
    | None = None,
    compensation_execution: (
        _WorkflowReconcileMapping[str, object] | None
    ) = None,
    failure_hook: _WorkflowReconcileCallable[[str], None] | None = None,
) -> _WorkflowActionReconciliationAuthorityFacts:
    if not callable(commit_evaluator):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVALUATOR_REQUIRED",
            "closing reconciliation requires a live commit evaluator",
        )
    state_path = task_path / "state.json"
    try:
        state = load_state(state_path)
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_STATE_INVALID",
            "live task state could not be loaded",
        ) from exc
    if (
        state.get("task_id") != request.task_id
        or state.get("revision") != request.current_task_revision
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REVISION_INVALID",
            "commit evaluator requires the exact current task revision",
            details={
                "expected_revision": request.current_task_revision,
                "actual_revision": state.get("revision"),
            },
        )
    public_decision = (
        "COMPENSATED" if decision == "COMPENSATE" else decision
    )
    context = WorkflowActionReconciliationCommitContext(
        request=request,
        decision=public_decision,
        evidence_sha256=evidence_sha256,
        receipt_sha256=receipt_sha256,
        current_state=state,
        pre_effect_state=state,
        target_journal=target,
        attempt=attempt,
        compensation_execution=compensation_execution,
    )
    try:
        if request.authorization_kind == "manager":
            if not callable(commit_authorizer):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_COMMIT_AUTHORITY_REQUIRED",
                    "manager reconciliation requires one process-local "
                    "fresh capability authority context",
                )
            authority_context = commit_authorizer(context)
        else:
            authority_context = _workflow_reconcile_contextlib.nullcontext()
        with authority_context:  # type: ignore[attr-defined]
            evaluation_context = context
            if request.authorization_kind == "manager":
                invocation = _manager_authority_context_var.get()
                package_action_id = getattr(
                    invocation, "package_action_id", None
                )
                event_type = _workflow_reconcile_catalog_event_type(
                    state, request, target
                )
                manager_process_commit_gate_v1(
                    state,
                    state,
                    "manager_effect_preauthorized",
                    _effect_lifecycle=("preauthorize", "generic"),
                    _effect_package_action_id=package_action_id,
                )
                manager_authorization = (
                    _manager_workflow_action_authorization_v1(
                        state, event_type=event_type
                    )
                )
                expected_manager_binding = {
                    "authorization_sha256": (
                        request.authorization_sha256
                    ),
                    "capability_sha256": request.capability_sha256,
                    "request_nonce_sha256": (
                        request.request_nonce_sha256
                    ),
                    "principal": request.principal,
                }
                actual_manager_binding = {
                    field_name: getattr(
                        manager_authorization, field_name
                    )
                    for field_name in expected_manager_binding
                }
                mismatches = sorted(
                    field_name
                    for field_name, expected_value
                    in expected_manager_binding.items()
                    if actual_manager_binding[field_name]
                    != expected_value
                )
                if mismatches:
                    raise _workflow_reconcile_error(
                        "WORKFLOW_ACTION_RECONCILIATION_COMMIT_AUTHORITY_MISMATCH",
                        "live manager authority differs from the durable "
                        "reconciliation request",
                        details={"fields": mismatches},
                    )
                prepared = _manager_engine_evaluation_state_v1(
                    state, event_type=event_type
                )
                if not isinstance(prepared, dict):
                    raise _workflow_reconcile_error(
                        "WORKFLOW_ACTION_RECONCILIATION_COMMIT_AUTHORITY_INVALID",
                        "manager authority produced no nonce-prepared engine state",
                    )
                evaluation_context = (
                    WorkflowActionReconciliationCommitContext(
                        request=request,
                        decision=public_decision,
                        evidence_sha256=evidence_sha256,
                        receipt_sha256=receipt_sha256,
                        current_state=prepared,
                        pre_effect_state=state,
                        target_journal=target,
                        attempt=attempt,
                        compensation_execution=(
                            compensation_execution
                        ),
                    )
                )
            plan = commit_evaluator(evaluation_context)
            if type(plan) is not WorkflowActionReconciliationCommitPlan:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_EVALUATION_INVALID",
                    "commit evaluator must return the exact typed commit plan",
                )
            evaluation = plan.evaluation
            actual_engine_proof_sha256 = (
                workflow_action_reconciliation_engine_proof_sha256(
                    request, evaluation
                )
            )
            if not _workflow_reconcile_hmac.compare_digest(
                request.engine_proof_sha256,
                actual_engine_proof_sha256,
            ):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_ENGINE_PROOF_MISMATCH",
                    "request proof digest does not bind the live engine evaluation",
                )
            target_bindings = target.get("bindings")
            expected_evaluation_edge_id = (
                target_bindings.get(
                    "authorization_action_edge_id"
                )
                if (
                    context.decision
                    in {"ABANDONED", "COMPENSATED"}
                    and isinstance(
                        target_bindings,
                        _WorkflowReconcileMapping,
                    )
                )
                else request.action_edge_id
            )
            if evaluation.edge_id != expected_evaluation_edge_id:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_EDGE_MISMATCH",
                    "live recovery evaluation is bound to another action edge",
                    details={
                        "expected_edge_id": (
                            expected_evaluation_edge_id
                        ),
                        "actual_edge_id": evaluation.edge_id,
                    },
                )
            return _workflow_reconcile_commit_evaluated(
                task_path,
                request,
                evaluation_context,
                evaluation,
                target=target,
                attempt=attempt,
                compensation_execution=compensation_execution,
                failure_hook=failure_hook,
            )
    except WorkflowActionReconciliationError:
        raise
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVALUATION_FAILED",
            "live recovery evaluation failed",
            details={
                "error_type": type(exc).__name__,
                **(
                    {"error_code": str(exc.code)}
                    if isinstance(
                        getattr(exc, "code", None), str
                    )
                    else {}
                ),
            },
        ) from exc


def _workflow_reconcile_commit_evaluated(
    task_path: _WorkflowReconcilePath,
    request: WorkflowActionReconciliationRequest,
    context: WorkflowActionReconciliationCommitContext,
    evaluation: TransitionEvaluation,
    *,
    target: _WorkflowReconcileMapping[str, object],
    attempt: _WorkflowReconcileMapping[str, object],
    compensation_execution: (
        _WorkflowReconcileMapping[str, object] | None
    ),
    failure_hook: _WorkflowReconcileCallable[[str], None] | None,
) -> _WorkflowActionReconciliationAuthorityFacts:
    """Commit one already-authorized live reconciliation evaluation."""

    state = _workflow_reconcile_copy.deepcopy(
        dict(context.pre_effect_state)
    )
    public_decision = context.decision
    evidence_sha256 = context.evidence_sha256
    receipt_sha256 = context.receipt_sha256
    try:
        (
            _bundle,
            edge,
            _selection,
            event_type,
            _ordinary_payload,
            additional_events,
        ) = _workflow_action_commit_components(state, evaluation)
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVALUATION_INVALID",
            "live evaluation does not resolve through the pinned catalog",
        ) from exc
    target_bindings = target.get("bindings")
    expected_event_edge_id = (
        target_bindings.get("authorization_action_edge_id")
        if (
            public_decision in {"ABANDONED", "COMPENSATED"}
            and isinstance(
                target_bindings, _WorkflowReconcileMapping
            )
        )
        else request.action_edge_id
    )
    if (
        edge.get("id") != expected_event_edge_id
        or edge.get("canonical_event") != event_type
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVENT_MISMATCH",
            "recovery event must be the evaluation edge canonical event",
        )
    if public_decision == "ACCEPTED":
        _workflow_reconcile_validate_accepted_candidate(
            request,
            evaluation,
            target,
            context.pre_effect_state,
        )
    elif public_decision == "ABANDONED" and evaluation.changed_paths:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_ABANDONMENT_MUTATION_FORBIDDEN",
            "abandonment evaluation cannot accept the stale business candidate",
            details={"changed_paths": list(evaluation.changed_paths)},
        )
    event_payload = _workflow_reconcile_event_payload(
        request,
        decision=public_decision,
        evidence_sha256=evidence_sha256,
        receipt_sha256=receipt_sha256,
    )
    candidate = _workflow_reconcile_copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CANDIDATE_INVALID",
            "live recovery evaluation produced no task candidate",
        )
    _workflow_reconcile_fail(failure_hook, "before-task-commit")
    try:
        if request.authorization_kind == "manager":
            _commit_state(
                state,
                candidate,
                task_path,
                event_type,
                event_payload,
                additional_events=additional_events,
                _engine_commit_evaluation=evaluation,
                _verified_receipt=(
                    target.get("receipt")
                    if public_decision == "ACCEPTED"
                    else (
                        compensation_execution.get("receipt")
                        if isinstance(
                            compensation_execution,
                            _WorkflowReconcileMapping,
                        )
                        else None
                    )
                ),
            )
        else:
            proof = _workflow_transition_mint_engine_commit_proof(
                state,
                evaluation,
                task_path,
                event_type,
                event_payload,
                additional_events=additional_events,
                verified_receipt=(
                    target.get("receipt")
                    if public_decision == "ACCEPTED"
                    else (
                        compensation_execution.get("receipt")
                        if isinstance(
                            compensation_execution,
                            _WorkflowReconcileMapping,
                        )
                        else None
                    )
                ),
            )
            _persist_state_transaction(
                state,
                candidate,
                task_path,
                event_type,
                event_payload,
                additional_events=additional_events,
                _engine_commit_proof=proof,
                _verified_receipt=(
                    target.get("receipt")
                    if public_decision == "ACCEPTED"
                    else (
                        compensation_execution.get("receipt")
                        if isinstance(
                            compensation_execution,
                            _WorkflowReconcileMapping,
                        )
                        else None
                    )
                ),
            )
    except WorkflowActionReconciliationError:
        raise
    except Exception as exc:
        raise _workflow_reconcile_error(
            getattr(
                exc,
                "code",
                "WORKFLOW_ACTION_RECONCILIATION_COMMIT_FAILED",
            ),
            str(
                getattr(
                    exc,
                    "message",
                    "authoritative recovery transaction failed",
                )
            ),
            details=getattr(exc, "details", {}),
        ) from exc
    _workflow_reconcile_fail(failure_hook, "after-task-commit")
    facts = _workflow_reconcile_authority_facts(
        task_path,
        request,
        event_type=event_type,
        event_payload=event_payload,
    )
    if facts is None:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_UNVERIFIED",
            "task transaction committed no exact authoritative recovery event",
        )
    return facts


def _workflow_reconcile_finish_compensation_locked(
    task_path: _WorkflowReconcilePath,
    request: WorkflowActionReconciliationRequest,
    permit: CompensationDispatchPlan,
    observation: WorkflowActionCompensationObservation,
    *,
    manager_secret: str | bytes | None,
    commit_evaluator: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext],
        WorkflowActionReconciliationCommitPlan,
    ],
    commit_authorizer: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext], object
    ]
    | None,
    failure_hook: _WorkflowReconcileCallable[[str], None] | None,
) -> WorkflowActionReconciliationResult:
    """Persist a compensation observation after authoritative locked rereads."""

    store = ActionExecutionStore(task_path)
    claimed_index = store.read_index(
        expected_task_id=request.task_id
    )
    if (
        claimed_index.get("revision") != permit.index_revision
        or claimed_index.get("record_sha256")
        != permit.index_record_sha256
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CAS_CONFLICT",
            "compensation control changed after its one dispatch claim",
        )
    target = store.read_active_journal(
        request.target_execution_id,
        manager_secret=manager_secret,
    )
    if (
        target.get("revision") != request.expected_journal.revision
        or target.get("record_sha256")
        != request.expected_journal.record_sha256
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_CAS_CONFLICT",
            "compensation target changed after authorization",
        )
    attempt = store.read_rotated_reconciliation(
        request.attempt_id
    )
    claimed_compensation = store.read_compensation(
        permit.execution_id
    )
    if (
        claimed_compensation.get("phase") != "CLAIMED"
        or claimed_compensation.get("claim_id") != permit.claim_id
        or claimed_compensation.get("revision")
        != permit.journal_revision
        or claimed_compensation.get("record_sha256")
        != permit.journal_record_sha256
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_CLAIM_INVALID",
            "compensation observation differs from its exact durable claim",
        )
    bindings = claimed_compensation["bindings"]
    assert isinstance(bindings, dict)
    receipt = seal_compensation_receipt(
        {
            "execution_id": permit.execution_id,
            "claim_id": permit.claim_id,
            "target_journal_record_sha256": bindings[
                "target_journal_record_sha256"
            ],
            "authorization_record_sha256": bindings[
                "authorization_record_sha256"
            ],
            "compensation_plan_sha256": bindings[
                "compensation_plan_sha256"
            ],
            "effect_receipt_sha256": (
                observation.effect_receipt_sha256
            ),
            "postcondition_proof_sha256": (
                observation.postcondition_proof_sha256
            ),
        }
    )
    verified = advance_compensation_execution(
        claimed_compensation,
        "RECEIPT_VERIFIED",
        receipt=receipt,
    )
    compensation_context = store.persist_compensation_update(
        verified,
        expected_index=cas_token(claimed_index),
        expected_execution=cas_token(claimed_compensation),
        target_manager_secret=manager_secret,
        failure_hook=failure_hook,
    )
    assert compensation_context.record is not None
    facts = _workflow_reconcile_commit(
        task_path,
        request,
        decision="COMPENSATE",
        evidence_sha256=observation.postcondition_proof_sha256,
        receipt_sha256=str(receipt["receipt_sha256"]),
        target=target,
        attempt=attempt,
        commit_evaluator=commit_evaluator,
        commit_authorizer=commit_authorizer,
        compensation_execution=compensation_context.record,
        failure_hook=failure_hook,
    )
    committed = advance_compensation_execution(
        compensation_context.record,
        "COMMITTED",
        recovery_event_sha256=facts.event_sha256,
        task_commit_revision=int(facts.state["revision"]),
        task_state_sha256=_sha256_contract(facts.state),
        outbox_sha256=facts.outbox_sha256,
        nonce_consumed=facts.nonce_consumed,
    )
    compensation_context = store.persist_compensation_update(
        committed,
        expected_index=cas_token(compensation_context.index),
        expected_execution=cas_token(compensation_context.record),
        target_manager_secret=manager_secret,
        failure_hook=failure_hook,
    )
    assert compensation_context.record is not None
    terminal_attempt = finalize_reconciliation_compensation(
        attempt,
        compensation_context.record,
    )
    closure = store.finalize_compensation_and_close(
        terminal_attempt,
        compensation_context.record,
        expected_index=cas_token(compensation_context.index),
        expected_journal=request.expected_journal,
        manager_secret=manager_secret,
        failure_hook=failure_hook,
    )
    return WorkflowActionReconciliationResult(
        status="COMPENSATED",
        target_execution_id=request.target_execution_id,
        attempt_id=request.attempt_id,
        attempt=_workflow_reconcile_copy.deepcopy(
            terminal_attempt
        ),
        index=_workflow_reconcile_copy.deepcopy(closure.index),
        archive_path=closure.archive_path,
        dispatcher_invocations=1,
        blocked=False,
        compensation_execution_id=permit.execution_id,
    )


def _workflow_reconcile_locked(
    task_dir: str | object,
    request: WorkflowActionReconciliationRequest,
    *,
    reauthenticate: _WorkflowReconcileCallable[
        [], str | bytes | None
    ],
    verifier: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationChallenge], object
    ],
    live_abandonment_observer: _WorkflowReconcileCallable[
        [WorkflowActionAbandonmentObservationChallenge], object
    ]
    | None = None,
    commit_evaluator: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext],
        WorkflowActionReconciliationCommitPlan,
    ]
    | None = None,
    commit_authorizer: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext], object
    ]
    | None = None,
    compensation_dispatcher: _WorkflowReconcileCallable[
        [CompensationDispatchPlan],
        WorkflowActionCompensationObservation,
    ]
    | None = None,
    failure_hook: _WorkflowReconcileCallable[[str], None] | None = None,
) -> WorkflowActionReconciliationResult:
    """Reconcile one quarantine without ever reopening business dispatch.

    The caller retains the task/repository/worktree/lease/registry locks
    declared by the returned store context.  A terminal ``UNRESOLVED`` attempt
    deliberately remains indexed as a target-control child and therefore
    blocks every overlapping future action indefinitely.
    """

    if type(request) is not WorkflowActionReconciliationRequest:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REQUEST_INVALID",
            "coordinator requires the exact typed request",
        )
    if not callable(verifier):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_VERIFIER_REQUIRED",
            "coordinator requires a process-local current-fact verifier",
        )
    task_path = _WorkflowReconcilePath(task_dir)
    if not task_path.is_absolute():
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must be an explicit absolute path",
        )
    try:
        task_path = task_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must resolve to an existing directory",
        ) from exc
    store = ActionExecutionStore(task_path)
    manager_secret: str | bytes | None = None
    try:
        # Read once without a secret only to learn the sealed authorization
        # kind; manager journals are authenticated by the exact second read.
        try:
            raw_target = store.read_active_journal(
                request.target_execution_id,
                manager_secret=None,
            )
        except Exception:
            raw_target = None
        if raw_target is None:
            # A manager journal cannot be read unauthenticated.  Obtain the
            # process-local secret before reading its exact promoted pair.
            try:
                manager_secret = reauthenticate()
            except Exception as exc:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
                    "target journal could not be reauthenticated",
                ) from exc
        else:
            manager_secret = _workflow_reconcile_reauthenticate(
                raw_target, reauthenticate
            )
        context = store.read_promoted_context(
            request.target_execution_id,
            expected_index=request.expected_index,
            expected_journal=request.expected_journal,
            manager_secret=manager_secret,
        )
        assert context.record is not None
        target = context.record
        # If the first manager read required a secret, validate the callback
        # result against the now-authenticated target contract as well.
        if raw_target is None:
            bindings = target.get("bindings")
            if (
                not isinstance(bindings, _WorkflowReconcileMapping)
                or bindings.get("authorization_kind") != "manager"
                or not isinstance(manager_secret, (str, bytes))
                or not manager_secret
            ):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
                    "reauthentication did not match target authorization",
                )
        _workflow_reconcile_validate_target(
            request, target, context.index
        )
        try:
            catalog_state = load_state(task_path / "state.json")
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_STATE_INVALID",
                "current task state could not validate recovery control",
            ) from exc
        _workflow_reconcile_catalog_event_type(
            catalog_state, request, target
        )
        predecessor = _workflow_reconcile_existing_control(
            store, request, context.index
        )
        containments = _workflow_reconcile_containments(store, target)
        challenge = WorkflowActionReconciliationChallenge(
            request,
            target,
            containments,
            live_abandonment_observer=live_abandonment_observer,
        )
        try:
            proof = verifier(challenge)
        except WorkflowActionReconciliationAuthorityRejected as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_" + exc.reason,
                "current reconciliation authority rejected the request",
            ) from exc
        except WorkflowActionReconciliationError:
            raise
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_VERIFICATION_FAILED",
                "current reconciliation facts could not be verified",
            ) from exc
        payload = _workflow_reconcile_consume_proof(
            proof, challenge._challenge_id
        )
        decision = str(payload["decision"])
        if decision in {
            "ACCEPTED",
            "ABANDONED",
            "COMPENSATE",
        } and any(
            item.get("phase") != "CLOSED" for item in containments
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_QUIESCENCE_REQUIRED",
                "closing reconciliation requires closed containment",
            )
        if decision == "COMPENSATE" and not callable(
            compensation_dispatcher
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_DISPATCHER_REQUIRED",
                "authorized compensation requires an explicit dispatcher",
            )
        if (
            decision == "COMPENSATE"
            and request.workflow_version == "4"
            and type(compensation_dispatcher)
            is not WorkflowActionCompensationDispatcher
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_LIVE_BRIDGE_REQUIRED",
                "V4 compensation requires the package-owned live host bridge",
            )
        if decision in {
            "ACCEPTED",
            "ABANDONED",
            "COMPENSATE",
        } and not callable(commit_evaluator):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_EVALUATOR_REQUIRED",
                "closing reconciliation requires a live commit evaluator",
            )
        if (
            decision
            in {"ACCEPTED", "ABANDONED", "COMPENSATE"}
            and request.authorization_kind == "manager"
            and not callable(commit_authorizer)
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMMIT_AUTHORITY_REQUIRED",
                "manager reconciliation requires one process-local "
                "fresh capability authority context",
            )

        _workflow_reconcile_fail(failure_hook, "before-attempt")
        attempt = new_reconciliation_attempt(
            target,
            context.index,
            attempt_id=request.attempt_id,
            effect_id=request.effect_id,
            expected_task_revision=request.current_task_revision,
            recovery_action_id=request.recovery_action_id,
            authorization_kind=request.authorization_kind,
            authorization_sha256=request.authorization_sha256,
            capability_sha256=request.capability_sha256,
            gate_sha256=request.gate_sha256,
            request_nonce_sha256=request.request_nonce_sha256,
            engine_proof_sha256=request.engine_proof_sha256,
            principal=request.principal,
            manager_secret=manager_secret,
        )
        if predecessor is None:
            persisted = store.persist_reconciliation_initial(
                attempt,
                target_execution_id=request.target_execution_id,
                expected_index=cas_token(context.index),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
        else:
            rotation_plan = plan_reconciliation_control_rotation(
                context.index,
                predecessor,
                attempt,
                target_journal=target,
                expected_index=cas_token(context.index),
                manager_secret=manager_secret,
            )
            persisted = store.rotate_reconciliation_control(
                predecessor,
                attempt,
                target_execution_id=request.target_execution_id,
                expected_index=cas_token(context.index),
                manager_secret=manager_secret,
                rotation_plan=rotation_plan,
                failure_hook=failure_hook,
            )
        assert persisted.record is not None
        _workflow_reconcile_fail(failure_hook, "after-attempt")
        claimed = advance_reconciliation_attempt(
            persisted.record, "CLAIMED"
        )
        persisted = store.persist_reconciliation_update(
            claimed,
            expected_index=cas_token(persisted.index),
            expected_attempt=cas_token(persisted.record),
            target_manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        assert persisted.record is not None
        _workflow_reconcile_fail(failure_hook, "after-claim")
        if decision == "COMPENSATE":
            authorized = authorize_reconciliation_compensation(
                persisted.record,
                compensation_execution_id=str(
                    payload["compensation_execution_id"]
                ),
                compensation_plan=payload["compensation_plan"],
                dual_approval_sha256=str(
                    payload["dual_approval_sha256"]
                ),
                host_principal=str(payload["host_principal"]),
                host_approval_sha256=str(
                    payload["host_approval_sha256"]
                ),
                workflow_principal=str(
                    payload["workflow_principal"]
                ),
                workflow_approval_sha256=str(
                    payload["workflow_approval_sha256"]
                ),
            )
            persisted = store.persist_reconciliation_update(
                authorized,
                expected_index=cas_token(persisted.index),
                expected_attempt=cas_token(persisted.record),
                target_manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted.record is not None
            compensation = new_compensation_execution(
                persisted.record,
                target,
                manager_secret=manager_secret,
            )
            compensation_rotation = (
                plan_compensation_control_rotation(
                    persisted.index,
                    persisted.record,
                    compensation,
                    target_journal=target,
                    expected_index=cas_token(persisted.index),
                    manager_secret=manager_secret,
                )
            )
            rotated = store.rotate_to_compensation_control(
                persisted.record,
                compensation,
                target_execution_id=request.target_execution_id,
                expected_index=cas_token(persisted.index),
                manager_secret=manager_secret,
                rotation_plan=compensation_rotation,
                failure_hook=failure_hook,
            )
            assert rotated.record is not None
            claim_id = (
                str(payload["compensation_execution_id"])
                + "-claim"
            )
            permit = store.claim_compensation_for_dispatch(
                str(payload["compensation_execution_id"]),
                claim_id,
                expected_index=cas_token(rotated.index),
                expected_execution=cas_token(rotated.record),
                target_manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            raise _WorkflowReconcileCompensationDispatchRequired(
                request, permit
            )
        facts = None
        if decision != "UNRESOLVED":
            complete_receipt = payload.get("complete_receipt")
            receipt_sha256 = (
                complete_receipt.get("receipt_sha256")
                if isinstance(
                    complete_receipt,
                    _WorkflowReconcileMapping,
                )
                else None
            )
            facts = _workflow_reconcile_commit(
                task_path,
                request,
                decision=decision,
                evidence_sha256=str(payload["evidence_sha256"]),
                receipt_sha256=(
                    str(receipt_sha256)
                    if receipt_sha256 is not None
                    else None
                ),
                target=target,
                attempt=persisted.record,
                commit_evaluator=commit_evaluator,  # type: ignore[arg-type]
                commit_authorizer=commit_authorizer,
                failure_hook=failure_hook,
            )
        terminal = advance_reconciliation_attempt(
            persisted.record,
            decision,
            evidence_sha256=str(payload["evidence_sha256"]),
            recovery_event_sha256=(
                facts.event_sha256 if facts is not None else None
            ),
            task_commit_revision=(
                int(facts.state["revision"])
                if facts is not None
                else None
            ),
            task_state_sha256=(
                _sha256_contract(facts.state)
                if facts is not None
                else None
            ),
            outbox_sha256=(
                facts.outbox_sha256 if facts is not None else None
            ),
            nonce_consumed=(
                facts.nonce_consumed if facts is not None else False
            ),
        )
        persisted = store.persist_reconciliation_update(
            terminal,
            expected_index=cas_token(persisted.index),
            expected_attempt=cas_token(persisted.record),
            target_manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        assert persisted.record is not None
        _workflow_reconcile_fail(failure_hook, "after-decision")
        if decision == "UNRESOLVED":
            return WorkflowActionReconciliationResult(
                status=decision,
                target_execution_id=request.target_execution_id,
                attempt_id=request.attempt_id,
                attempt=_workflow_reconcile_copy.deepcopy(
                    persisted.record
                ),
                index=_workflow_reconcile_copy.deepcopy(persisted.index),
                archive_path=None,
                dispatcher_invocations=0,
                blocked=True,
            )
        closure = store.archive_and_close(
            request.target_execution_id,
            expected_index=cas_token(persisted.index),
            expected_journal=request.expected_journal,
            authoritative_event_sha256=str(
                facts.event_sha256
            ),
            reconciliation_attempt_id=request.attempt_id,
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        _workflow_reconcile_fail(failure_hook, "after-archive")
        return WorkflowActionReconciliationResult(
            status=decision,
            target_execution_id=request.target_execution_id,
            attempt_id=request.attempt_id,
            attempt=_workflow_reconcile_copy.deepcopy(persisted.record),
            index=_workflow_reconcile_copy.deepcopy(closure.index),
            archive_path=closure.archive_path,
            dispatcher_invocations=0,
            blocked=False,
        )
    finally:
        manager_secret = None


def reconcile_v3_workflow_action_quarantine(
    task_dir: str | object,
    request: WorkflowActionReconciliationRequest,
    *,
    reauthenticate: _WorkflowReconcileCallable[
        [], str | bytes | None
    ],
    verifier: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationChallenge], object
    ],
    live_abandonment_observer: _WorkflowReconcileCallable[
        [WorkflowActionAbandonmentObservationChallenge], object
    ]
    | None = None,
    commit_evaluator: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext],
        WorkflowActionReconciliationCommitPlan,
    ]
    | None = None,
    commit_authorizer: _WorkflowReconcileCallable[
        [WorkflowActionReconciliationCommitContext], object
    ]
    | None = None,
    compensation_dispatcher: _WorkflowReconcileCallable[
        [CompensationDispatchPlan],
        WorkflowActionCompensationObservation,
    ]
    | None = None,
    failure_hook: _WorkflowReconcileCallable[[str], None] | None = None,
) -> WorkflowActionReconciliationResult:
    """Own the exact task/scope/control locks for one reconciliation."""

    if type(request) is not WorkflowActionReconciliationRequest:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_REQUEST_INVALID",
            "coordinator requires the exact typed request",
        )
    task_path = _WorkflowReconcilePath(task_dir)
    if not task_path.is_absolute():
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must be an explicit absolute path",
        )
    try:
        task_path = task_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must resolve to an existing directory",
        ) from exc
    if "_task_lock" not in globals() or (
        "_workflow_tx_ordered_locks" not in globals()
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_RUNTIME_INVALID",
            "reconciliation must run through the composed controller runtime",
        )
    retry_attempt = None
    retry_store = ActionExecutionStore(task_path)
    for reader in (
        retry_store.read_reconciliation,
        retry_store.read_rotated_reconciliation,
        retry_store.read_reconciliation_archive,
    ):
        try:
            retry_attempt = reader(request.attempt_id)
            break
        except Exception as exc:
            if getattr(exc, "code", None) not in {
                "ACTION_STORE_RECORD_MISSING",
                "ACTION_STORE_DIRECTORY_MISSING",
            }:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_ATTEMPT_INVALID",
                    "existing retry attempt could not be authenticated",
                    details={"attempt_id": request.attempt_id},
                ) from exc
    if retry_attempt is not None:
        if (
            retry_attempt.get("task_id") != request.task_id
            or retry_attempt.get("target_execution_id")
            != request.target_execution_id
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_REPLAY",
                "attempt identity is already bound to another request",
            )
        return recover_v3_workflow_action_reconciliation(
            task_path,
            request.attempt_id,
            reauthenticate=reauthenticate,
            failure_hook=failure_hook,
        )
    manager_secret: str | bytes | None = None
    store = ActionExecutionStore(task_path)
    try:
        pending: (
            _WorkflowReconcileCompensationDispatchRequired | None
        ) = None
        with _task_lock(task_path):
            try:
                live_state = _read_task_state_snapshot(
                    task_path / "state.json"
                )
            except Exception as exc:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_STATE_INVALID",
                    "current task state could not be validated",
                ) from exc
            if (
                live_state.get("schema_version") != 3
                or live_state.get("task_id") != request.task_id
                or live_state.get("revision")
                != request.current_task_revision
                or live_state.get("pending_event") is not None
                or live_state.get("pending_events") is not None
            ):
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_REVISION_INVALID",
                    "request does not bind one settled current schema-v3 task revision",
                    details={
                        "expected_revision": (
                            request.current_task_revision
                        ),
                        "actual_revision": live_state.get("revision"),
                    },
                )
            try:
                raw_target = store.read_active_journal(
                    request.target_execution_id,
                    manager_secret=None,
                )
            except Exception:
                raw_target = None
            if raw_target is None:
                try:
                    manager_secret = reauthenticate()
                except Exception as exc:
                    raise _workflow_reconcile_error(
                        "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
                        "target journal could not be reauthenticated",
                    ) from exc
            else:
                manager_secret = _workflow_reconcile_reauthenticate(
                    raw_target, reauthenticate
                )
            context = store.read_promoted_context(
                request.target_execution_id,
                expected_index=request.expected_index,
                expected_journal=request.expected_journal,
                manager_secret=manager_secret,
            )
            if context.record is None:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_TARGET_INVALID",
                    "quarantined target journal is unavailable",
                )
            claims = action_execution_required_lock_claims(
                context.record
            )
            try:
                with _workflow_tx_ordered_locks(task_path, claims):
                    return _workflow_reconcile_locked(
                        task_path,
                        request,
                        reauthenticate=lambda: manager_secret,
                        verifier=verifier,
                        live_abandonment_observer=(
                            live_abandonment_observer
                        ),
                        commit_evaluator=commit_evaluator,
                        commit_authorizer=commit_authorizer,
                        compensation_dispatcher=compensation_dispatcher,
                        failure_hook=failure_hook,
                    )
            except (
                _WorkflowReconcileCompensationDispatchRequired
            ) as required:
                pending = required
        assert pending is not None
        if not callable(compensation_dispatcher) or not callable(
            commit_evaluator
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_RUNTIME_INVALID",
                "claimed compensation lost its required live callbacks",
            )
        try:
            with _workflow_tx_scope_locks(
                task_path, pending.permit.required_lock_claims
            ):
                _workflow_tx_assert_effect_lock_boundary(
                    task_path,
                    pending.permit.required_lock_claims,
                    operation="compensation dispatch",
                    lock_error_code=(
                        "WORKFLOW_ACTION_RECONCILIATION_LOCK_ORDER_INVALID"
                    ),
                    scope_error_code=(
                        "WORKFLOW_ACTION_RECONCILIATION_SCOPE_LOCK_REQUIRED"
                    ),
                )
                observation = compensation_dispatcher(
                    pending.permit
                )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_RESPONSE_UNKNOWN",
                "compensation was claimed; dispatcher response is "
                "unavailable and redispatch is forbidden",
                details={
                    "compensation_execution_id": (
                        pending.permit.execution_id
                    ),
                    "claim_id": pending.permit.claim_id,
                },
            ) from exc
        if type(observation) is not WorkflowActionCompensationObservation:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_RECEIPT_INVALID",
                "dispatcher must return the exact typed compensation observation",
            )
        with _workflow_tx_ordered_locks(
            task_path, pending.permit.required_lock_claims
        ):
            return _workflow_reconcile_finish_compensation_locked(
                task_path,
                pending.request,
                pending.permit,
                observation,
                manager_secret=manager_secret,
                commit_evaluator=commit_evaluator,
                commit_authorizer=commit_authorizer,
                failure_hook=failure_hook,
            )
    finally:
        manager_secret = None


def _workflow_reconcile_request_from_attempt(
    target: _WorkflowReconcileMapping[str, object],
    attempt: _WorkflowReconcileMapping[str, object],
) -> WorkflowActionReconciliationRequest:
    target_bindings = target.get("bindings")
    bindings = attempt.get("bindings")
    if not isinstance(
        target_bindings, _WorkflowReconcileMapping
    ) or not isinstance(bindings, _WorkflowReconcileMapping):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_BINDING_INVALID",
            "durable recovery records have no immutable bindings",
        )
    return WorkflowActionReconciliationRequest(
        task_id=str(target["task_id"]),
        workflow_id=str(target_bindings["workflow_id"]),
        workflow_version=str(target_bindings["workflow_version"]),
        workflow_bundle_sha256=str(
            target_bindings["workflow_bundle_sha256"]
        ),
        action_edge_id=str(target_bindings["action_edge_id"]),
        target_execution_id=str(target["execution_id"]),
        effect_id=str(bindings["effect_id"]),
        scopes=_workflow_reconcile_copy.deepcopy(
            target_bindings["scopes"]
        ),
        current_task_revision=int(
            bindings["expected_task_revision"]
        ),
        attempt_id=str(attempt["attempt_id"]),
        recovery_action_id=str(bindings["recovery_action_id"]),
        authorization_kind=str(bindings["authorization_kind"]),
        authorization_sha256=str(
            bindings["authorization_sha256"]
        ),
        capability_sha256=(
            str(bindings["capability_sha256"])
            if bindings["capability_sha256"] is not None
            else None
        ),
        gate_sha256=str(bindings["gate_sha256"]),
        request_nonce_sha256=str(
            bindings["request_nonce_sha256"]
        ),
        engine_proof_sha256=str(
            bindings["engine_proof_sha256"]
        ),
        principal=str(bindings["principal"]),
        expected_index=CASToken(
            int(bindings["expected_index_revision"]),
            str(bindings["expected_index_sha256"]),
        ),
        expected_journal=CASToken(
            int(bindings["expected_journal_revision"]),
            str(bindings["expected_journal_sha256"]),
        ),
    )


def _workflow_reconcile_read_attempt(
    store: ActionExecutionStore,
    attempt_id: str,
) -> dict[str, object]:
    try:
        return store.read_reconciliation(attempt_id)
    except Exception:
        try:
            return store.read_rotated_reconciliation(attempt_id)
        except Exception:
            try:
                return store.read_reconciliation_archive(attempt_id)
            except Exception as exc:
                raise _workflow_reconcile_error(
                    "WORKFLOW_ACTION_RECONCILIATION_ATTEMPT_INVALID",
                    "reconciliation attempt is neither active, rotated, nor archived",
                    details={"attempt_id": attempt_id},
                ) from exc


def _workflow_reconcile_read_target(
    store: ActionExecutionStore,
    execution_id: str,
    *,
    manager_secret: str | bytes | None,
) -> dict[str, object]:
    try:
        return store.read_active_journal(
            execution_id, manager_secret=manager_secret
        )
    except Exception:
        try:
            return store.read_archive_journal(
                execution_id, manager_secret=manager_secret
            )
        except Exception as exc:
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_TARGET_INVALID",
                "reconciliation target is neither active nor archived",
                details={"execution_id": execution_id},
            ) from exc


def _workflow_reconcile_recovery_event(
    task_path: _WorkflowReconcilePath,
    request: WorkflowActionReconciliationRequest,
    target: _WorkflowReconcileMapping[str, object],
) -> tuple[
    str,
    dict[str, object],
    _WorkflowActionReconciliationAuthorityFacts,
]:
    try:
        state = load_state(task_path / "state.json")
        bundle = _workflow_action_bundle(state)
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_STATE_INVALID",
            "recovery could not resolve the authoritative pinned task",
        ) from exc
    edges = (
        *tuple(getattr(bundle, "movement_edges", ())),
        *tuple(getattr(bundle, "action_edges", ())),
    )
    target_bindings = target.get("bindings")
    authorization_edge_id = (
        target_bindings.get("authorization_action_edge_id")
        if isinstance(
            target_bindings, _WorkflowReconcileMapping
        )
        else None
    )
    matching_edges = [
        edge
        for edge in edges
        if edge.get("id")
        == (
            authorization_edge_id
            if isinstance(authorization_edge_id, str)
            else request.action_edge_id
        )
    ]
    if (
        len(matching_edges) != 1
        or not isinstance(
            matching_edges[0].get("canonical_event"), str
        )
        or not matching_edges[0]["canonical_event"]
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_EVENT_MISMATCH",
            "recovery action edge has no unique canonical event",
        )
    event_type = str(matching_edges[0]["canonical_event"])
    expected_revision = request.current_task_revision + 1
    events = _workflow_reconcile_read_events(
        task_path / "events.jsonl"
    )
    immutable = {
        "schema": _WORKFLOW_RECONCILE_EVENT_SCHEMA,
        "recovery_action_id": request.recovery_action_id,
        "action_edge_id": request.action_edge_id,
        "attempt_id": request.attempt_id,
        "target_execution_id": request.target_execution_id,
        "effect_id": request.effect_id,
        "authorization_kind": request.authorization_kind,
        "authorization_sha256": request.authorization_sha256,
        "capability_sha256": request.capability_sha256,
        "gate_sha256": request.gate_sha256,
        "request_nonce_sha256": request.request_nonce_sha256,
        "engine_proof_sha256": request.engine_proof_sha256,
    }
    candidates = []
    for event in events:
        payload = event.get("payload")
        if (
            event.get("task_id") == request.task_id
            and event.get("previous_revision")
            == request.current_task_revision
            and event.get("revision") == expected_revision
            and event.get("type") == event_type
            and isinstance(payload, _WorkflowReconcileMapping)
            and all(payload.get(key) == value for key, value in immutable.items())
        ):
            candidates.append(event)
    if len(candidates) != 1:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_UNVERIFIED",
            "recovery found no unique authoritative task event",
            details={"matches": len(candidates)},
        )
    payload = candidates[0]["payload"]
    assert isinstance(payload, _WorkflowReconcileMapping)
    decision = payload.get("decision")
    evidence_sha256 = payload.get("evidence_sha256")
    receipt_sha256 = payload.get("receipt_sha256")
    expected_payload = _workflow_reconcile_event_payload(
        request,
        decision=str(decision),
        evidence_sha256=str(evidence_sha256),
        receipt_sha256=(
            str(receipt_sha256)
            if receipt_sha256 is not None
            else None
        ),
    )
    facts = _workflow_reconcile_authority_facts(
        task_path,
        request,
        event_type=event_type,
        event_payload=expected_payload,
    )
    if facts is None:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_COMMIT_UNVERIFIED",
            "authoritative recovery transaction is incomplete",
        )
    return event_type, expected_payload, facts


def _workflow_reconcile_unresolved_replay(
    task_path: _WorkflowReconcilePath,
    store: ActionExecutionStore,
    attempt_id: str,
    attempt: _WorkflowReconcileMapping[str, object],
    target: _WorkflowReconcileMapping[str, object],
    request: WorkflowActionReconciliationRequest,
    *,
    manager_secret: str | bytes | None,
) -> WorkflowActionReconciliationResult | None:
    if attempt.get("phase") != "UNRESOLVED":
        return None
    target_id = request.target_execution_id
    try:
        active_attempt = store.read_reconciliation(attempt_id)
        active_target = store.read_active_journal(
            target_id, manager_secret=manager_secret
        )
        index = store.read_index(expected_task_id=request.task_id)
        live_state = load_state(task_path / "state.json")
    except Exception as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay requires its exact active durable control",
        ) from exc
    if (
        semantic_json_bytes(active_attempt)
        != semantic_json_bytes(attempt)
        or semantic_json_bytes(active_target)
        != semantic_json_bytes(target)
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay records changed during lock acquisition",
        )
    active_request = _workflow_reconcile_request_from_attempt(
        active_target, active_attempt
    )
    if active_request != request:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay request differs from its active records",
        )
    _workflow_reconcile_validate_target(
        active_request, active_target, index
    )
    bindings = active_attempt.get("bindings")
    target_bindings = active_target.get("bindings")
    outcome = active_attempt.get("outcome")
    receipt = active_target.get("receipt")
    quarantine = active_target.get("quarantine")
    if isinstance(receipt, _WorkflowReconcileMapping):
        target_receipt_sha256 = receipt.get("receipt_sha256")
    elif isinstance(quarantine, _WorkflowReconcileMapping):
        target_receipt_sha256 = quarantine.get("receipt_sha256")
    else:
        target_receipt_sha256 = None
    if (
        not isinstance(bindings, _WorkflowReconcileMapping)
        or not isinstance(
            target_bindings, _WorkflowReconcileMapping
        )
        or not isinstance(outcome, _WorkflowReconcileMapping)
        or active_attempt.get("attempt_id") != attempt_id
        or active_attempt.get("task_id") != request.task_id
        or active_attempt.get("target_execution_id") != target_id
        or active_attempt.get("revision") != 2
        or outcome.get("decision") != "UNRESOLVED"
        or outcome.get("recovery_event_sha256") is not None
        or active_target.get("task_id") != request.task_id
        or active_target.get("execution_id") != target_id
        or active_target.get("phase") != "QUARANTINED"
        or active_target.get("revision")
        != request.expected_journal.revision
        or not _workflow_reconcile_hmac.compare_digest(
            str(active_target.get("record_sha256")),
            request.expected_journal.record_sha256,
        )
        or not _workflow_reconcile_hmac.compare_digest(
            str(bindings.get("target_journal_record_sha256")),
            request.expected_journal.record_sha256,
        )
        or bindings.get("target_receipt_sha256")
        != target_receipt_sha256
        or live_state.get("task_id") != request.task_id
        or live_state.get("revision")
        != request.current_task_revision
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay identity, target, or task revision changed",
        )
    workflow_ref = live_state.get("workflow_ref")
    if (
        not isinstance(workflow_ref, _WorkflowReconcileMapping)
        or workflow_ref.get("id") != request.workflow_id
        or str(workflow_ref.get("version"))
        != request.workflow_version
        or workflow_ref.get("bundle_sha256")
        != request.workflow_bundle_sha256
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay differs from the pinned workflow",
        )
    minimum_index_revision = (
        int(bindings["expected_index_revision"])
        + 2 * (int(active_attempt["revision"]) + 1)
    )
    entries = index.get("entries")
    if (
        not isinstance(entries, list)
        or not isinstance(index.get("revision"), int)
        or int(index["revision"]) < minimum_index_revision
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay index predates its durable control",
        )
    by_execution_id = {
        str(entry.get("execution_id")): entry
        for entry in entries
        if isinstance(entry, _WorkflowReconcileMapping)
    }
    target_entry = by_execution_id.get(target_id)
    control_entry = by_execution_id.get(attempt_id)
    target_controls = [
        entry
        for entry in entries
        if isinstance(entry, _WorkflowReconcileMapping)
        and entry.get("entry_kind") == "control"
        and entry.get("target_execution_id") == target_id
    ]
    expected_target_entry = {
        "execution_id": target_id,
        "entry_kind": "ordinary",
        "target_execution_id": None,
        "control_action_id": None,
        "concurrency_class": target_bindings.get(
            "concurrency_class"
        ),
        "scopes": _workflow_reconcile_copy.deepcopy(
            target_bindings.get("scopes")
        ),
        "pending_record_sha256": None,
        "record_sha256": active_target.get("record_sha256"),
        "runtime_reservation": None,
    }
    expected_control_entry = {
        "execution_id": attempt_id,
        "entry_kind": "control",
        "target_execution_id": target_id,
        "control_action_id": bindings.get("recovery_action_id"),
        "concurrency_class": "target-control",
        "scopes": _workflow_reconcile_copy.deepcopy(
            target_bindings.get("scopes")
        ),
        "pending_record_sha256": None,
        "record_sha256": active_attempt.get("record_sha256"),
        "runtime_reservation": None,
    }
    if (
        len(target_controls) != 1
        or target_controls[0] is not control_entry
        or not isinstance(
            target_entry, _WorkflowReconcileMapping
        )
        or not isinstance(
            control_entry, _WorkflowReconcileMapping
        )
        or semantic_json_bytes(target_entry)
        != semantic_json_bytes(expected_target_entry)
        or semantic_json_bytes(control_entry)
        != semantic_json_bytes(expected_control_entry)
    ):
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_UNRESOLVED_REPLAY_INVALID",
            "unresolved replay control entry bindings are not exact",
        )
    return WorkflowActionReconciliationResult(
        status="UNRESOLVED",
        target_execution_id=target_id,
        attempt_id=attempt_id,
        attempt=_workflow_reconcile_copy.deepcopy(active_attempt),
        index=_workflow_reconcile_copy.deepcopy(index),
        archive_path=None,
        dispatcher_invocations=0,
        blocked=True,
    )


def _recover_workflow_reconciliation_locked(
    task_path: _WorkflowReconcilePath,
    attempt_id: str,
    *,
    manager_secret: str | bytes | None,
    failure_hook: _WorkflowReconcileCallable[[str], None] | None,
) -> WorkflowActionReconciliationResult:
    store = ActionExecutionStore(task_path)
    attempt = _workflow_reconcile_read_attempt(store, attempt_id)
    target_id = str(attempt["target_execution_id"])
    target = _workflow_reconcile_read_target(
        store,
        target_id,
        manager_secret=manager_secret,
    )
    request = _workflow_reconcile_request_from_attempt(
        target, attempt
    )
    try:
        _event_type, event_payload, facts = (
            _workflow_reconcile_recovery_event(
                task_path, request, target
            )
        )
    except WorkflowActionReconciliationError as exc:
        if attempt.get("phase") == "UNRESOLVED":
            if (
                exc.code
                != "WORKFLOW_ACTION_RECONCILIATION_COMMIT_UNVERIFIED"
                or exc.details.get("matches") != 0
            ):
                raise
            unresolved_replay = (
                _workflow_reconcile_unresolved_replay(
                    task_path,
                    store,
                    attempt_id,
                    attempt,
                    target,
                    request,
                    manager_secret=manager_secret,
                )
            )
            assert unresolved_replay is not None
            return unresolved_replay
        try:
            live_state = load_state(task_path / "state.json")
        except Exception:
            raise
        if (
            live_state.get("task_id") != request.task_id
            or live_state.get("revision")
            != request.current_task_revision
            or attempt.get("phase") not in {"PREPARED", "CLAIMED"}
        ):
            raise
        index = store.read_index(expected_task_id=request.task_id)
        if attempt.get("phase") == "PREPARED":
            claimed = advance_reconciliation_attempt(
                attempt, "CLAIMED"
            )
            persisted = store.persist_reconciliation_update(
                claimed,
                expected_index=cas_token(index),
                expected_attempt=cas_token(attempt),
                target_manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted.record is not None
            attempt = persisted.record
            index = persisted.index
        evidence_sha256 = semantic_sha256(
            _WORKFLOW_RECONCILE_RESTART_UNRESOLVED_DOMAIN,
            {
                "task_id": request.task_id,
                "attempt_id": attempt_id,
                "attempt_record_sha256": attempt[
                    "record_sha256"
                ],
                "task_revision": request.current_task_revision,
                "task_state_sha256": _sha256_contract(live_state),
                "classification": (
                    "restart-before-authoritative-event"
                ),
            },
        )
        unresolved = advance_reconciliation_attempt(
            attempt,
            "UNRESOLVED",
            evidence_sha256=evidence_sha256,
        )
        persisted = store.persist_reconciliation_update(
            unresolved,
            expected_index=cas_token(index),
            expected_attempt=cas_token(attempt),
            target_manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        assert persisted.record is not None
        return WorkflowActionReconciliationResult(
            status="UNRESOLVED",
            target_execution_id=target_id,
            attempt_id=attempt_id,
            attempt=_workflow_reconcile_copy.deepcopy(
                persisted.record
            ),
            index=_workflow_reconcile_copy.deepcopy(
                persisted.index
            ),
            archive_path=None,
            dispatcher_invocations=0,
            blocked=True,
        )
    decision = str(event_payload["decision"])
    index = store.read_index(expected_task_id=request.task_id)
    dispatcher_invocations = 0
    if decision == "COMPENSATED":
        authorization = attempt.get("compensation_authorization")
        if (
            attempt.get("phase")
            not in {"COMPENSATION_AUTHORIZED", "COMPENSATED"}
            or not isinstance(
                authorization, _WorkflowReconcileMapping
            )
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_INVALID",
                "authoritative compensation event has no durable authorization",
            )
        compensation_id = str(
            authorization["compensation_execution_id"]
        )
        try:
            compensation = store.read_compensation(
                compensation_id
            )
        except Exception:
            compensation = store.read_compensation_archive(
                compensation_id
            )
        receipt = compensation.get("receipt")
        if (
            not isinstance(receipt, _WorkflowReconcileMapping)
            or receipt.get("receipt_sha256")
            != event_payload["receipt_sha256"]
        ):
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_RECEIPT_INVALID",
                "authoritative event differs from the verified compensation receipt",
            )
        if compensation.get("phase") == "RECEIPT_VERIFIED":
            committed = advance_compensation_execution(
                compensation,
                "COMMITTED",
                recovery_event_sha256=facts.event_sha256,
                task_commit_revision=int(facts.state["revision"]),
                task_state_sha256=_sha256_contract(facts.state),
                outbox_sha256=facts.outbox_sha256,
                nonce_consumed=facts.nonce_consumed,
            )
            persisted = store.persist_compensation_update(
                committed,
                expected_index=cas_token(index),
                expected_execution=cas_token(compensation),
                target_manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted.record is not None
            compensation = persisted.record
            index = persisted.index
        if compensation.get("phase") != "COMMITTED":
            raise _workflow_reconcile_error(
                "WORKFLOW_ACTION_RECONCILIATION_COMPENSATION_INVALID",
                "compensation is not durably committed",
            )
        terminal = (
            attempt
            if attempt.get("phase") == "COMPENSATED"
            else finalize_reconciliation_compensation(
                attempt, compensation
            )
        )
        closure = store.finalize_compensation_and_close(
            terminal,
            compensation,
            expected_index=cas_token(index),
            expected_journal=cas_token(target),
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        return WorkflowActionReconciliationResult(
            status="COMPENSATED",
            target_execution_id=target_id,
            attempt_id=attempt_id,
            attempt=_workflow_reconcile_copy.deepcopy(terminal),
            index=_workflow_reconcile_copy.deepcopy(closure.index),
            archive_path=closure.archive_path,
            dispatcher_invocations=dispatcher_invocations,
            blocked=False,
            compensation_execution_id=compensation_id,
        )
    if decision not in {"ACCEPTED", "ABANDONED"}:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_DECISION_INVALID",
            "authoritative event does not carry a recoverable decision",
        )
    if attempt.get("phase") == "CLAIMED":
        terminal = advance_reconciliation_attempt(
            attempt,
            decision,
            evidence_sha256=str(event_payload["evidence_sha256"]),
            recovery_event_sha256=facts.event_sha256,
            task_commit_revision=int(facts.state["revision"]),
            task_state_sha256=_sha256_contract(facts.state),
            outbox_sha256=facts.outbox_sha256,
            nonce_consumed=facts.nonce_consumed,
        )
        persisted = store.persist_reconciliation_update(
            terminal,
            expected_index=cas_token(index),
            expected_attempt=cas_token(attempt),
            target_manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        assert persisted.record is not None
        attempt = persisted.record
        index = persisted.index
    if attempt.get("phase") != decision:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_ATTEMPT_INVALID",
            "durable attempt differs from its authoritative event",
        )
    entries = index.get("entries")
    if isinstance(entries, list) and not any(
        isinstance(entry, _WorkflowReconcileMapping)
        and entry.get("execution_id") in {target_id, attempt_id}
        for entry in entries
    ):
        return WorkflowActionReconciliationResult(
            status=decision,
            target_execution_id=target_id,
            attempt_id=attempt_id,
            attempt=_workflow_reconcile_copy.deepcopy(attempt),
            index=_workflow_reconcile_copy.deepcopy(index),
            archive_path=str(
                task_path / action_execution_archive_path(target_id)
            ),
            dispatcher_invocations=dispatcher_invocations,
            blocked=False,
        )
    closure = store.archive_and_close(
        target_id,
        expected_index=cas_token(index),
        expected_journal=cas_token(target),
        authoritative_event_sha256=facts.event_sha256,
        reconciliation_attempt_id=attempt_id,
        manager_secret=manager_secret,
        failure_hook=failure_hook,
    )
    return WorkflowActionReconciliationResult(
        status=decision,
        target_execution_id=target_id,
        attempt_id=attempt_id,
        attempt=_workflow_reconcile_copy.deepcopy(attempt),
        index=_workflow_reconcile_copy.deepcopy(closure.index),
        archive_path=closure.archive_path,
        dispatcher_invocations=dispatcher_invocations,
        blocked=False,
    )


def recover_v3_workflow_action_reconciliation(
    task_dir: str | object,
    attempt_id: str,
    *,
    reauthenticate: _WorkflowReconcileCallable[
        [], str | bytes | None
    ],
    failure_hook: _WorkflowReconcileCallable[[str], None] | None = None,
) -> WorkflowActionReconciliationResult:
    """Finish a committed recovery from task event plus exact journal CAS."""

    _workflow_reconcile_text(attempt_id, "attempt_id")
    task_path = _WorkflowReconcilePath(task_dir)
    if not task_path.is_absolute():
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must be an explicit absolute path",
        )
    try:
        task_path = task_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _workflow_reconcile_error(
            "WORKFLOW_ACTION_RECONCILIATION_TASK_DIR_INVALID",
            "task directory must resolve to an existing directory",
        ) from exc
    store = ActionExecutionStore(task_path)
    manager_secret: str | bytes | None = None
    try:
        with _task_lock(task_path):
            attempt = _workflow_reconcile_read_attempt(
                store, attempt_id
            )
            target_id = str(attempt["target_execution_id"])
            try:
                raw_target = store.read_active_journal(
                    target_id, manager_secret=None
                )
            except Exception:
                raw_target = None
            if raw_target is None:
                try:
                    manager_secret = reauthenticate()
                except Exception as exc:
                    raise _workflow_reconcile_error(
                        "WORKFLOW_ACTION_RECONCILIATION_REAUTHENTICATION_FAILED",
                        "target journal could not be reauthenticated",
                    ) from exc
            else:
                manager_secret = _workflow_reconcile_reauthenticate(
                    raw_target, reauthenticate
                )
            target = _workflow_reconcile_read_target(
                store,
                target_id,
                manager_secret=manager_secret,
            )
            claims = action_execution_required_lock_claims(target)
            with _workflow_tx_ordered_locks(task_path, claims):
                return _recover_workflow_reconciliation_locked(
                    task_path,
                    attempt_id,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
    finally:
        manager_secret = None


__all__ = [
    "WORKFLOW_ACTION_RECONCILIATION_FAILURE_POINTS",
    "WORKFLOW_ACTION_RECONCILIATION_SCHEMA",
    "WorkflowActionReconciliationAuthorityRejected",
    "WorkflowActionAbandonmentObservation",
    "WorkflowActionAbandonmentObservationChallenge",
    "WorkflowActionReconciliationChallenge",
    "WorkflowActionReconciliationCommitContext",
    "WorkflowActionReconciliationCommitPlan",
    "WorkflowActionCompensationApproval",
    "WorkflowActionCompensationDispatcher",
    "WorkflowActionCompensationObservation",
    "WorkflowActionCompensationPlan",
    "WorkflowActionReconciliationError",
    "WorkflowActionReconciliationProof",
    "WorkflowActionReconciliationRequest",
    "WorkflowActionReconciliationResult",
    "evaluate_v3_workflow_action_abandonment",
    "evaluate_v3_workflow_action_compensation",
    "preview_v3_workflow_action_abandonment",
    "preview_v3_workflow_action_compensation",
    "recover_v3_workflow_action_reconciliation",
    "reconcile_v3_workflow_action_quarantine",
    "workflow_action_reconciliation_engine_proof_sha256",
]
