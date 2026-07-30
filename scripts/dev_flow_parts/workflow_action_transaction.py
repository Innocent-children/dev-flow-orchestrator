# Loaded by scripts/dev_flow.py after workflow_action_service.py.
# Responsibility: coordinate one catalog action across the durable action
# journal, an injected effect dispatcher, and the authoritative task outbox.
from __future__ import annotations

import copy as _workflow_tx_copy
import contextlib as _workflow_tx_contextlib
import contextvars as _workflow_tx_contextvars
import json as _workflow_tx_json
import re as _workflow_tx_re
import secrets as _workflow_tx_secrets
import threading as _workflow_tx_threading
from dataclasses import dataclass as _workflow_tx_dataclass
from pathlib import Path as _WorkflowTxPath
from typing import Callable as _WorkflowTxCallable
from typing import Mapping as _WorkflowTxMapping


_WORKFLOW_TX_SHA256_RE = _workflow_tx_re.compile(r"^[0-9a-f]{64}$")
_WORKFLOW_TX_EFFECT_PLAN_DOMAIN = (
    b"dev-flow-v4-workflow-action-effect-plan-v1\x00"
)
_WORKFLOW_TX_OPERATION_DOMAIN = (
    b"dev-flow-v4-workflow-action-operation-v1\x00"
)
_WORKFLOW_TX_SEMANTIC_OPERATION_DOMAIN = (
    b"dev-flow-v4-workflow-action-semantic-operation-v1\x00"
)
_WORKFLOW_TX_REQUEST_DOMAIN = b"dev-flow-v4-workflow-action-request-v1\x00"
_WORKFLOW_TX_CONFIRMATION_DOMAIN = (
    b"dev-flow-v4-workflow-action-confirmation-v1\x00"
)
_WORKFLOW_TX_GUARD_DOMAIN = (
    b"dev-flow-v4-workflow-action-guard-projection-v1\x00"
)
_WORKFLOW_TX_EVIDENCE_DOMAIN = (
    b"dev-flow-v4-workflow-action-evidence-v1\x00"
)
_WORKFLOW_TX_APPROVAL_DOMAIN = (
    b"dev-flow-v4-workflow-action-approval-v1\x00"
)
_WORKFLOW_TX_POSTCONDITION_DOMAIN = (
    b"dev-flow-v4-workflow-action-postcondition-v1\x00"
)
_WORKFLOW_TX_VERIFIER_DOMAIN = (
    b"dev-flow-v4-workflow-action-verifier-before-v1\x00"
)
_WORKFLOW_TX_IDEMPOTENCY_DOMAIN = (
    b"dev-flow-v4-workflow-action-effect-idempotency-v1\x00"
)
_WORKFLOW_TX_EFFECT_RECEIPT_DOMAIN = (
    b"dev-flow-v4-workflow-action-effect-receipt-set-v1\x00"
)
_WORKFLOW_TX_EVENT_DOMAIN = (
    b"dev-flow-v4-workflow-action-authoritative-event-v1\x00"
)
_WORKFLOW_TX_OUTBOX_DOMAIN = (
    b"dev-flow-v4-workflow-action-authoritative-outbox-v1\x00"
)
_WORKFLOW_TX_SCOPE_LOCK_DOMAIN = (
    b"dev-flow-v4-workflow-action-scope-lock-v1\x00"
)
_WORKFLOW_TX_DISPATCH_PERMIT_DOMAIN = (
    b"dev-flow-v4-workflow-action-dispatch-permit-v1\x00"
)
_WORKFLOW_TX_OBSERVE_CONTEXT_DOMAIN = (
    b"dev-flow-v4-workflow-action-observe-context-v1\x00"
)
_WORKFLOW_TX_RUNTIME_RELEASE_PERMIT_DOMAIN = (
    b"dev-flow-v4-workflow-action-runtime-release-permit-v1\x00"
)
_WORKFLOW_TX_RUNTIME_LAUNCH_PROTOCOL = "suspended-handshake/v1"
_WORKFLOW_TX_RUNTIME_RELEASE_PROTOCOL = "suspended-release/v1"
_WORKFLOW_TX_SYNC_DISPATCH_PROTOCOL = "direct-observe/v1"
_WORKFLOW_TX_OBSERVE_PROTOCOL = "durable-observe-only/v1"

WORKFLOW_ACTION_TRANSACTION_FAILURE_POINTS = (
    "before-prepare",
    "after-prepare",
    "after-claim",
    "after-containment",
    "after-dispatch",
    "after-running",
    "after-runtime-release-authorized",
    "after-runtime-release",
    "after-observation",
    "after-effect-verified",
    "after-receipt-verified",
    "after-task-commit",
    "after-journal-commit",
    "after-archive",
)


class WorkflowActionTransactionError(RuntimeError):
    """Stable fail-closed rejection from the action transaction boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _WorkflowTxMapping[str, object] | None = None,
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


def _workflow_tx_error(
    code: str,
    message: str,
    *,
    details: _WorkflowTxMapping[str, object] | None = None,
) -> WorkflowActionTransactionError:
    return WorkflowActionTransactionError(
        code, message, details=details
    )


def _workflow_tx_sha256(value: object, role: str) -> str:
    if (
        not isinstance(value, str)
        or not _WORKFLOW_TX_SHA256_RE.fullmatch(value)
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            f"{role} must be lowercase SHA-256",
        )
    return value


def _workflow_tx_public_mapping(
    value: _WorkflowTxMapping[str, object] | None,
    role: str,
) -> dict[str, object]:
    try:
        public = _workflow_transition_public(dict(value or {}))
        copied = _workflow_tx_copy.deepcopy(public)
        semantic_json_bytes(copied)
    except Exception as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            f"{role} must be a strict public semantic JSON object",
        ) from exc
    if not isinstance(copied, dict):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            f"{role} must be an object",
        )
    return copied


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionInvocation:
    """One typed request for the generic catalog Action Service."""

    kind: str
    public_command: str
    action_outcome: ActionOutcome
    selector: str | None = None
    target: str | None = None
    edge_selector: str | None = None
    approval_outcome: ApprovalOutcome | None = None
    action_parameters: _WorkflowTxMapping[str, object] | None = None
    evidence: _WorkflowTxMapping[str, object] | None = None
    confirm_intent: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"node", "movement"}:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                "action invocation kind must be node or movement",
            )
        if (
            not isinstance(self.public_command, str)
            or not self.public_command
            or type(self.action_outcome) is not ActionOutcome
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                "action invocation requires a command and exact ActionOutcome",
            )
        if (
            self.approval_outcome is not None
            and type(self.approval_outcome) is not ApprovalOutcome
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                "approval must use the exact ApprovalOutcome type",
            )
        if self.kind == "node":
            if self.target is not None or self.edge_selector is not None:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                    "node action cannot carry movement selectors",
                )
        elif (
            not isinstance(self.target, str)
            or not self.target
            or self.selector is not None
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                "movement action requires target and forbids node selector",
            )
        if self.confirm_intent is not None and (
            not isinstance(self.confirm_intent, str)
            or not self.confirm_intent
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
                "confirmation intent must be non-empty text",
            )
        object.__setattr__(
            self,
            "action_parameters",
            _workflow_tx_public_mapping(
                self.action_parameters, "action parameters"
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            _workflow_tx_public_mapping(self.evidence, "evidence"),
        )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionAuthorization:
    """Digest-only authorization plus transient reauthentication seams.

    The callbacks are process-local authorities. Their secret values and
    manager nonce evidence are never copied into the journal, dispatcher
    input, event payload, or exception details.
    """

    kind: str
    authorization_sha256: str
    capability_sha256: str | None
    request_nonce_sha256: str
    principal: str
    ownership_sha256: str
    registry_state_sha256: str
    reauthenticate: _WorkflowTxCallable[[], str | bytes | None]
    nonce_consumed_verifier: (
        _WorkflowTxCallable[
            [
                _WorkflowTxMapping[str, object],
                tuple[_WorkflowTxMapping[str, object], ...],
            ],
            bool,
        ]
        | None
    ) = None

    def __post_init__(self) -> None:
        if self.kind not in {"operator", "manager"}:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_AUTHORIZATION_INVALID",
                "authorization kind must be operator or manager",
            )
        for field_name in (
            "authorization_sha256",
            "request_nonce_sha256",
            "ownership_sha256",
            "registry_state_sha256",
        ):
            _workflow_tx_sha256(
                getattr(self, field_name), field_name
            )
        if (
            not isinstance(self.principal, str)
            or not self.principal
            or not callable(self.reauthenticate)
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_AUTHORIZATION_INVALID",
                "authorization requires principal and reauthentication",
            )
        if self.kind == "manager":
            _workflow_tx_sha256(
                self.capability_sha256, "capability_sha256"
            )
            if not callable(self.nonce_consumed_verifier):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_NONCE_VERIFIER_REQUIRED",
                    "manager authorization requires authoritative nonce "
                    "consumption verification",
                )
        elif (
            self.capability_sha256 is not None
            or self.nonce_consumed_verifier is not None
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_AUTHORIZATION_INVALID",
                "operator authorization cannot carry manager augmentation",
            )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionEffectBinding:
    """Safe, typed augmentation for the one dispatching catalog effect."""

    effect_id: str
    kind: str
    scope_kinds: tuple[str, ...]
    scopes: _WorkflowTxMapping[str, object]
    safe_inputs: _WorkflowTxMapping[str, object]
    attempt_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.effect_id, str)
            or not self.effect_id
            or not isinstance(self.kind, str)
            or not self.kind
            or not isinstance(self.attempt_id, str)
            or not self.attempt_id
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
                "effect binding identities and kind are required",
            )
        if (
            not isinstance(self.scope_kinds, tuple)
            or any(
                not isinstance(item, str) or not item
                for item in self.scope_kinds
            )
            or tuple(
                sorted(
                    set(self.scope_kinds),
                    key=lambda item: item.encode("utf-8"),
                )
            )
            != self.scope_kinds
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
                "catalog scope kinds must be sorted and unique",
            )
        scopes = _workflow_tx_public_mapping(self.scopes, "effect scopes")
        safe_inputs = _workflow_tx_public_mapping(
            self.safe_inputs, "effect safe inputs"
        )
        try:
            normalized_scopes = normalize_scopes(scopes)
            _reject_secret_fields(safe_inputs, "/safe_inputs")
        except Exception as exc:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
                "effect scope or safe input contract is invalid",
            ) from exc
        object.__setattr__(self, "scopes", normalized_scopes)
        object.__setattr__(self, "safe_inputs", safe_inputs)


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionEffectObservation:
    """Typed observation returned exactly once by the injected dispatcher."""

    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    settlement: str
    receipt_sha256: str
    runtime_handle_sha256: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
                    f"{field_name} is required",
                )
        if self.settlement not in {"QUIESCED", "HANDOFF_VERIFIED"}:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
                "observation settlement branch is invalid",
            )
        _workflow_tx_sha256(self.receipt_sha256, "receipt_sha256")
        if self.runtime_handle_sha256 is not None:
            _workflow_tx_sha256(
                self.runtime_handle_sha256,
                "runtime_handle_sha256",
            )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionDispatchContext:
    plan: ActionDispatchPlan
    effect_kind: str
    settlement: str
    scopes: dict[str, object]
    catalog_contract_sha256: str
    launch_protocol: str


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionObserveContext:
    """A read-only callback context reconstructed from durable authority."""

    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    journal_revision: int
    journal_record_sha256: str
    index_revision: int
    index_record_sha256: str
    containment_revision: int
    containment_record_sha256: str
    containment_phase: str
    effect_kind: str
    settlement: str
    safe_inputs: dict[str, object]
    required_lock_claims: tuple[tuple[str, str], ...]
    scopes: dict[str, object]
    catalog_contract_sha256: str
    runtime_binding_sha256: str | None
    runtime_handle_sha256: str | None
    protocol: str

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
            "containment_phase",
            "effect_kind",
            "settlement",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
                    f"{field_name} is required",
                )
        if self.protocol != _WORKFLOW_TX_OBSERVE_PROTOCOL:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
                "observe context protocol is invalid",
            )
        if self.settlement not in {
            "synchronous-quiescence",
            "asynchronous-handoff",
        }:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
                "observe context settlement is invalid",
            )
        for field_name in (
            "journal_revision",
            "index_revision",
            "containment_revision",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
                    f"{field_name} must be a non-negative integer",
                )
        for field_name in (
            "journal_record_sha256",
            "index_record_sha256",
            "containment_record_sha256",
            "catalog_contract_sha256",
        ):
            _workflow_tx_sha256(
                getattr(self, field_name), field_name
            )
        if self.runtime_binding_sha256 is not None:
            _workflow_tx_sha256(
                self.runtime_binding_sha256,
                "runtime_binding_sha256",
            )
        if self.runtime_handle_sha256 is not None:
            _workflow_tx_sha256(
                self.runtime_handle_sha256,
                "runtime_handle_sha256",
            )
        safe_inputs = _workflow_tx_public_mapping(
            self.safe_inputs, "observe safe inputs"
        )
        scopes = _workflow_tx_public_mapping(
            self.scopes, "observe scopes"
        )
        try:
            _reject_secret_fields(safe_inputs, "/safe_inputs")
            normalized_scopes = normalize_scopes(scopes)
        except Exception as exc:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
                "observe safe inputs or scopes are invalid",
            ) from exc
        object.__setattr__(self, "safe_inputs", safe_inputs)
        object.__setattr__(self, "scopes", normalized_scopes)
        _workflow_tx_scope_claims(self.required_lock_claims)

    @property
    def observe_context_sha256(self) -> str:
        return _workflow_tx_observe_context_sha256(self)


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionDispatchResult:
    """Observed callback output bound to the exact pre-dispatch CAS."""

    observation: WorkflowActionEffectObservation
    observe_context: WorkflowActionObserveContext
    dispatcher_invocations: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.observation)
            is not WorkflowActionEffectObservation
            or type(self.observe_context)
            is not WorkflowActionObserveContext
            or self.dispatcher_invocations != 1
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_DISPATCH_RESULT_INVALID",
                "dispatch result requires one exact observed callback",
            )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionRuntimeBinding:
    """Authenticated identity persisted before an async runtime is released."""

    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    lease_id: str
    runtime_handle_sha256: str
    stop_action_id: str
    reconcile_action_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
            "lease_id",
            "stop_action_id",
            "reconcile_action_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_INVALID",
                    f"{field_name} is required",
                )
        _workflow_tx_sha256(
            self.runtime_handle_sha256,
            "runtime_handle_sha256",
        )

    @property
    def binding_sha256(self) -> str:
        return runtime_binding_sha256(
            task_id=self.task_id,
            execution_id=self.execution_id,
            effect_id=self.effect_id,
            claim_id=self.claim_id,
            attempt_id=self.attempt_id,
            lease_id=self.lease_id,
            runtime_handle_sha256=self.runtime_handle_sha256,
            stop_action_id=self.stop_action_id,
            reconcile_action_id=self.reconcile_action_id,
        )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionRuntimeLaunch:
    """A contained runtime that cannot execute business work yet."""

    binding: WorkflowActionRuntimeBinding
    protocol: str
    suspended: bool
    business_effect_count: int

    def __post_init__(self) -> None:
        if (
            type(self.binding) is not WorkflowActionRuntimeBinding
            or self.protocol != _WORKFLOW_TX_RUNTIME_LAUNCH_PROTOCOL
            or self.suspended is not True
            or isinstance(self.business_effect_count, bool)
            or not isinstance(self.business_effect_count, int)
            or self.business_effect_count != 0
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_LAUNCH_INVALID",
                "runtime launch must be an exact zero-effect suspended handshake",
            )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionRuntimeReleaseContext:
    """One durable, target-bound authorization to release a runtime."""

    binding: WorkflowActionRuntimeBinding
    containment_revision: int
    containment_record_sha256: str
    journal_revision: int
    journal_record_sha256: str
    index_revision: int
    index_record_sha256: str
    required_lock_claims: tuple[tuple[str, str], ...]
    protocol: str

    def __post_init__(self) -> None:
        if (
            type(self.binding) is not WorkflowActionRuntimeBinding
            or self.protocol != _WORKFLOW_TX_RUNTIME_RELEASE_PROTOCOL
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_INVALID",
                "runtime release context requires the exact bound protocol",
            )
        for field_name in (
            "containment_revision",
            "journal_revision",
            "index_revision",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_INVALID",
                    f"{field_name} must be a non-negative integer",
                )
        for field_name in (
            "containment_record_sha256",
            "journal_record_sha256",
            "index_record_sha256",
        ):
            _workflow_tx_sha256(
                getattr(self, field_name), field_name
            )
        _workflow_tx_scope_claims(self.required_lock_claims)

    @property
    def release_context_sha256(self) -> str:
        return _workflow_tx_runtime_release_permit_sha256(self)


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionRuntimeReleaseAck:
    """Exact acknowledgment returned by the authorized release adapter."""

    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    lease_id: str
    runtime_handle_sha256: str
    runtime_binding_sha256: str
    release_context_sha256: str
    protocol: str
    released: bool

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
            "lease_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_ACK_INVALID",
                    f"{field_name} is required",
                )
        for field_name in (
            "runtime_handle_sha256",
            "runtime_binding_sha256",
            "release_context_sha256",
        ):
            _workflow_tx_sha256(
                getattr(self, field_name), field_name
            )
        if (
            self.protocol != _WORKFLOW_TX_RUNTIME_RELEASE_PROTOCOL
            or self.released is not True
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_ACK_INVALID",
                "release acknowledgment must confirm the exact protocol",
            )


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionEffectStep:
    status: str
    execution_id: str
    effect_id: str
    journal: dict[str, object]
    index: dict[str, object]
    containment: dict[str, object]
    dispatcher_invocations: int = 0
    observation: WorkflowActionEffectObservation | None = None
    observe_context_sha256: str | None = None


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionClaimBatch:
    execution_id: str
    contexts: tuple[WorkflowActionDispatchContext, ...]
    journal: dict[str, object]
    index: dict[str, object]
    dispatcher_invocations: int = 0


@_workflow_tx_dataclass(frozen=True)
class WorkflowActionTransactionResult:
    status: str
    execution_id: str | None
    state: dict[str, object] | None
    journal: dict[str, object] | None
    index: dict[str, object] | None
    archive_path: str | None
    dispatcher_invocations: int


@_workflow_tx_dataclass(frozen=True)
class _WorkflowActionAuthorityFacts:
    state: dict[str, object]
    events: tuple[dict[str, object], ...]
    event_sha256: str
    outbox_sha256: str


@_workflow_tx_dataclass(frozen=True)
class _WorkflowActionEdgeRoles:
    authorization_action_edge: _WorkflowTxMapping[str, object]
    completion_edge: _WorkflowTxMapping[str, object]

    @property
    def authorization_action_edge_id(self) -> str:
        return str(self.authorization_action_edge["id"])

    @property
    def completion_edge_id(self) -> str:
        return str(self.completion_edge["id"])

    @property
    def completes_movement(self) -> bool:
        return (
            self.authorization_action_edge_id
            != self.completion_edge_id
        )

    def binding(self) -> dict[str, str]:
        return {
            "authorization_action_edge_id": (
                self.authorization_action_edge_id
            ),
            "completion_edge_id": self.completion_edge_id,
        }


@_workflow_tx_dataclass(frozen=True)
class _WorkflowActionFreshEvaluation:
    state: dict[str, object]
    invocation: WorkflowActionInvocation
    edge_roles: _WorkflowActionEdgeRoles
    evaluation_state: dict[str, object]
    manager_intent_state: dict[str, object] | None
    preview: TransitionEvaluation
    bindings: tuple[WorkflowActionEffectBinding, ...]


def _workflow_tx_fail(
    failure_hook: _WorkflowTxCallable[[str], None] | None,
    stage: str,
) -> None:
    if failure_hook is not None:
        failure_hook(stage)


def _workflow_tx_data_root(task_path: _WorkflowTxPath) -> _WorkflowTxPath:
    parent = task_path.parent
    return parent.parent if parent.name == "tasks" else parent


def _workflow_tx_scope_lock_directory(
    task_path: _WorkflowTxPath,
    kind: str,
    identity: str,
) -> _WorkflowTxPath:
    digest = semantic_sha256(
        _WORKFLOW_TX_SCOPE_LOCK_DOMAIN,
        {"kind": kind, "identity": identity},
    )
    return (
        _workflow_tx_data_root(task_path)
        / "action-execution-scope-locks"
        / kind
        / digest
    )


def _workflow_tx_live_lock_capabilities(
) -> tuple[dict[str, object], ...]:
    """Return only broker-authenticated locks held by this exact thread."""

    try:
        held = tuple(
            workflow_runtime_services().locks.held_directories()
        )
        observed = _engine_lock_capability_snapshot(held)
    except Exception as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_OBSERVER_INVALID",
            "live controller locks could not be authenticated",
        ) from exc
    if not isinstance(observed, list) or any(
        not isinstance(item, dict) for item in observed
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_OBSERVER_INVALID",
            "live lock observer returned an invalid capability set",
        )
    return tuple(
        _workflow_tx_copy.deepcopy(item) for item in observed
    )


def _workflow_tx_assert_clean_transaction_entry(
    task_path: _WorkflowTxPath,
) -> None:
    """Reject inherited controller locks before any journal/index write."""

    task_directory = str(task_path.resolve(strict=False))
    data_root = str(
        _workflow_tx_data_root(task_path).resolve(strict=False)
    )
    forbidden = []
    for capability in _workflow_tx_live_lock_capabilities():
        lock_name = capability.get("lock_name")
        path = capability.get("path")
        if (
            lock_name == "state.lock"
            and path == task_directory
        ) or (
            lock_name == "workspace-registry.lock"
            and path == data_root
        ) or lock_name == "action-execution-index.lock":
            forbidden.append(capability)
    if forbidden:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_ORDER_INVALID",
            "generic transaction must begin without inherited task, "
            "index, or workspace-registry locks",
            details={
                "lock_names": sorted(
                    {
                        str(item.get("lock_name"))
                        for item in forbidden
                    }
                )
            },
        )


def _workflow_tx_scope_claims(
    claims: object,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(claims, tuple):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_CLAIMS_INVALID",
            "controller lock claims must use the exact ordered tuple",
        )
    result: list[tuple[str, str]] = []
    previous: tuple[int, bytes] | None = None
    order = {"task": 0, "repository": 1, "worktree": 2, "lease": 3, "registry": 4}
    for claim in claims:
        if (
            not isinstance(claim, tuple)
            or len(claim) != 2
            or claim[0] not in order
            or not isinstance(claim[1], str)
            or not claim[1]
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_LOCK_CLAIMS_INVALID",
                "controller lock claim is malformed",
            )
        key = (order[claim[0]], claim[1].encode("utf-8"))
        if previous is not None and key <= previous:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_LOCK_CLAIMS_INVALID",
                "controller lock claims are duplicated or out of order",
            )
        previous = key
        if claim[0] in {"repository", "worktree", "lease"}:
            result.append((claim[0], claim[1]))
    return tuple(result)


@_workflow_tx_contextlib.contextmanager
def _workflow_tx_scope_locks(
    task_path: _WorkflowTxPath,
    claims: tuple[tuple[str, str], ...],
):
    """Acquire deterministic non-task effect locks in normative order."""

    scope_claims = _workflow_tx_scope_claims(claims)
    with _workflow_tx_contextlib.ExitStack() as stack:
        for kind, identity in scope_claims:
            stack.enter_context(
                _file_lock(
                    _workflow_tx_scope_lock_directory(
                        task_path, kind, identity
                    ),
                    "scope.lock",
                )
            )
        yield


def _workflow_tx_capability_key(
    capability: _WorkflowTxMapping[str, object],
) -> tuple[str, str]:
    return (
        str(capability.get("path")),
        str(capability.get("lock_name")),
    )


@_workflow_tx_contextlib.contextmanager
def _workflow_tx_ordered_locks(
    task_path: _WorkflowTxPath,
    claims: tuple[tuple[str, str], ...],
):
    """Hold task→scope→registry locks only around controller storage work."""

    scope_claims = _workflow_tx_scope_claims(claims)
    task_directory = str(task_path.resolve(strict=False))
    data_root = _workflow_tx_data_root(task_path)
    data_root_text = str(data_root.resolve(strict=False))
    capabilities = _workflow_tx_live_lock_capabilities()
    held_keys = {
        _workflow_tx_capability_key(item) for item in capabilities
    }
    task_key = (task_directory, "state.lock")
    registry_key = (data_root_text, "workspace-registry.lock")
    required_scope_keys = {
        (
            str(
                _workflow_tx_scope_lock_directory(
                    task_path, kind, identity
                ).resolve(strict=False)
            ),
            "scope.lock",
        )
        for kind, identity in scope_claims
    }
    task_held = task_key in held_keys
    registry_held = registry_key in held_keys
    held_scope_keys = {
        key for key in held_keys if key[1] == "scope.lock"
    }
    if not task_held and (registry_held or held_scope_keys):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_ORDER_INVALID",
            "task lock must precede scope and registry locks",
        )
    if registry_held and not required_scope_keys.issubset(
        held_scope_keys
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_ORDER_INVALID",
            "scope locks cannot be inserted after the registry lock",
        )
    with _workflow_tx_contextlib.ExitStack() as stack:
        if not task_held:
            stack.enter_context(_task_lock(task_path))
        for kind, identity in scope_claims:
            key = (
                str(
                    _workflow_tx_scope_lock_directory(
                        task_path, kind, identity
                    ).resolve(strict=False)
                ),
                "scope.lock",
            )
            if key not in held_scope_keys:
                stack.enter_context(
                    _file_lock(
                        _workflow_tx_scope_lock_directory(
                            task_path, kind, identity
                        ),
                        "scope.lock",
                    )
                )
        if not registry_held:
            stack.enter_context(_workspace_registry_lock(data_root))
        yield


def _workflow_tx_dispatch_permit_sha256(
    context: WorkflowActionDispatchContext,
) -> str:
    plan = context.plan
    return semantic_sha256(
        _WORKFLOW_TX_DISPATCH_PERMIT_DOMAIN,
        {
            "task_id": plan.task_id,
            "execution_id": plan.execution_id,
            "effect_id": plan.effect_id,
            "claim_id": plan.claim_id,
            "attempt_id": plan.attempt_id,
            "journal_revision": plan.journal_revision,
            "journal_record_sha256": plan.journal_record_sha256,
            "index_revision": plan.index_revision,
            "index_record_sha256": plan.index_record_sha256,
            "safe_inputs": plan.safe_inputs,
            "required_lock_claims": [
                {"kind": kind, "identity": identity}
                for kind, identity in plan.required_lock_claims
            ],
            "effect_kind": context.effect_kind,
            "settlement": context.settlement,
            "scopes": context.scopes,
            "catalog_contract_sha256": (
                context.catalog_contract_sha256
            ),
            "launch_protocol": context.launch_protocol,
        },
    )


def _workflow_tx_observe_context_sha256(
    context: WorkflowActionObserveContext,
) -> str:
    return semantic_sha256(
        _WORKFLOW_TX_OBSERVE_CONTEXT_DOMAIN,
        {
            "task_id": context.task_id,
            "execution_id": context.execution_id,
            "effect_id": context.effect_id,
            "claim_id": context.claim_id,
            "attempt_id": context.attempt_id,
            "journal_revision": context.journal_revision,
            "journal_record_sha256": (
                context.journal_record_sha256
            ),
            "index_revision": context.index_revision,
            "index_record_sha256": context.index_record_sha256,
            "containment_revision": context.containment_revision,
            "containment_record_sha256": (
                context.containment_record_sha256
            ),
            "containment_phase": context.containment_phase,
            "effect_kind": context.effect_kind,
            "settlement": context.settlement,
            "safe_inputs": context.safe_inputs,
            "required_lock_claims": [
                {"kind": kind, "identity": identity}
                for kind, identity in context.required_lock_claims
            ],
            "scopes": context.scopes,
            "catalog_contract_sha256": (
                context.catalog_contract_sha256
            ),
            "runtime_binding_sha256": (
                context.runtime_binding_sha256
            ),
            "runtime_handle_sha256": (
                context.runtime_handle_sha256
            ),
            "protocol": context.protocol,
        },
    )


def _workflow_tx_active_observe_facts(
    context: WorkflowActionObserveContext,
) -> dict[str, object]:
    return {
        "task_id": context.task_id,
        "execution_id": context.execution_id,
        "effect_id": context.effect_id,
        "claim_id": context.claim_id,
        "attempt_id": context.attempt_id,
        "journal_revision": context.journal_revision,
        "journal_record_sha256": context.journal_record_sha256,
        "index_revision": context.index_revision,
        "index_record_sha256": context.index_record_sha256,
        "containment_revision": context.containment_revision,
        "containment_record_sha256": (
            context.containment_record_sha256
        ),
        "containment_phase": context.containment_phase,
        "effect_kind": context.effect_kind,
        "settlement": context.settlement,
        "safe_inputs": _workflow_tx_copy.deepcopy(
            context.safe_inputs
        ),
        "safe_input_sha256": semantic_sha256(
            SAFE_INPUT_DOMAIN, context.safe_inputs
        ),
        "required_lock_claims": [
            {"kind": kind, "identity": identity}
            for kind, identity in context.required_lock_claims
        ],
        "scope_lock_claims": [
            {"kind": kind, "identity": identity}
            for kind, identity in _workflow_tx_scope_claims(
                context.required_lock_claims
            )
        ],
        "scopes": _workflow_tx_copy.deepcopy(context.scopes),
        "catalog_contract_sha256": (
            context.catalog_contract_sha256
        ),
        "runtime_binding_sha256": (
            context.runtime_binding_sha256
        ),
        "runtime_handle_sha256": (
            context.runtime_handle_sha256
        ),
        "protocol": context.protocol,
        "observe_context_sha256": (
            context.observe_context_sha256
        ),
    }


def _workflow_tx_build_observe_callback_authority():
    """Keep observe-only callbacks process-local and target-bound."""

    lock = _workflow_tx_threading.Lock()
    active: dict[int, dict[str, object]] = {}
    active_stack = _workflow_tx_contextvars.ContextVar(
        "dev_flow_v4_active_action_observers", default=()
    )

    def invoke(
        task_path: _WorkflowTxPath,
        context: WorkflowActionObserveContext,
        callback: _WorkflowTxCallable[
            [WorkflowActionObserveContext], object
        ],
    ) -> object:
        if (
            type(context) is not WorkflowActionObserveContext
            or not callable(callback)
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVER_INVALID",
                "observe-only callback requires an exact durable context",
            )
        _workflow_tx_assert_observe_lock_boundary(
            task_path, context
        )
        capability = object()
        thread_id = _workflow_tx_threading.get_ident()
        digest = context.observe_context_sha256
        record = {
            "capability": capability,
            "context": context,
            "digest": digest,
            "thread_id": thread_id,
            "verified": False,
        }
        with lock:
            active[id(capability)] = record
        token = active_stack.set(
            (*active_stack.get(), capability)
        )
        try:
            result = callback(context)
            with lock:
                registered = active.get(id(capability))
                if (
                    registered is not record
                    or registered.get("verified") is not True
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_OBSERVE_VERIFIER_REQUIRED",
                        "package observer did not verify its exact active context",
                    )
            return result
        finally:
            active_stack.reset(token)
            with lock:
                if active.get(id(capability)) is record:
                    del active[id(capability)]

    def verify(
        context: WorkflowActionObserveContext,
    ) -> dict[str, object]:
        stack = active_stack.get()
        capability = stack[-1] if stack else None
        digest = (
            context.observe_context_sha256
            if type(context) is WorkflowActionObserveContext
            else None
        )
        thread_id = _workflow_tx_threading.get_ident()
        with lock:
            registered = (
                active.get(id(capability))
                if capability is not None
                else None
            )
            if (
                registered is None
                or registered.get("capability") is not capability
                or registered.get("context") is not context
                or registered.get("digest") != digest
                or registered.get("thread_id") != thread_id
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_ACTIVE_OBSERVE_REQUIRED",
                    "package observer is outside its exact observe-only callback",
                )
            registered["verified"] = True
        return _workflow_tx_active_observe_facts(context)

    return invoke, verify


def _workflow_tx_build_dispatch_callback_authority():
    """Keep permit issuance and active callback records in closure state."""

    lock = _workflow_tx_threading.Lock()
    permits: dict[int, tuple[object, str]] = {}
    active: dict[int, tuple[object, object, str, int]] = {}
    active_stack = _workflow_tx_contextvars.ContextVar(
        "dev_flow_v4_active_action_dispatches", default=()
    )

    def issue(context: WorkflowActionDispatchContext) -> None:
        if type(context) is not WorkflowActionDispatchContext:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_DISPATCH_PERMIT_INVALID",
                "only an exact first-claim context can receive a permit",
            )
        digest = _workflow_tx_dispatch_permit_sha256(context)
        with lock:
            if id(context) in permits:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_DISPATCH_PERMIT_INVALID",
                    "first-claim context already has a live permit",
                )
            permits[id(context)] = (context, digest)

    def invoke(
        task_path: _WorkflowTxPath,
        context: WorkflowActionDispatchContext,
        callback: _WorkflowTxCallable[
            [WorkflowActionDispatchContext], object
        ],
    ) -> object:
        if not callable(callback):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_DISPATCH_INVALID",
                "effect adapter must be callable",
            )
        _workflow_tx_assert_dispatch_lock_boundary(
            task_path, context
        )
        digest = _workflow_tx_dispatch_permit_sha256(context)
        capability = object()
        thread_id = _workflow_tx_threading.get_ident()
        with lock:
            registered = permits.get(id(context))
            if (
                registered is None
                or registered[0] is not context
                or registered[1] != digest
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_DISPATCH_PERMIT_INVALID",
                    "dispatch requires the exact unconsumed first-claim permit",
                )
            del permits[id(context)]
            active[id(capability)] = (
                capability,
                context,
                digest,
                thread_id,
            )
        token = active_stack.set(
            (*active_stack.get(), capability)
        )
        try:
            return callback(context)
        finally:
            active_stack.reset(token)
            with lock:
                registered_active = active.get(id(capability))
                if (
                    registered_active is not None
                    and registered_active[0] is capability
                ):
                    del active[id(capability)]

    def verify(context: WorkflowActionDispatchContext) -> None:
        stack = active_stack.get()
        capability = stack[-1] if stack else None
        digest = _workflow_tx_dispatch_permit_sha256(context)
        thread_id = _workflow_tx_threading.get_ident()
        with lock:
            registered = (
                active.get(id(capability))
                if capability is not None
                else None
            )
            if (
                registered is None
                or registered[0] is not capability
                or registered[1] is not context
                or registered[2] != digest
                or registered[3] != thread_id
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_ACTIVE_DISPATCH_REQUIRED",
                    "effect helper is outside its exact authorized callback",
                )

    return issue, invoke, verify


(
    _WORKFLOW_TX_ISSUE_DISPATCH_PERMIT,
    _WORKFLOW_TX_INVOKE_DISPATCH_CALLBACK,
    _WORKFLOW_TX_VERIFY_ACTIVE_DISPATCH,
) = _workflow_tx_build_dispatch_callback_authority()


@_workflow_tx_contextlib.contextmanager
def _workflow_tx_active_dispatch(
    context: WorkflowActionDispatchContext,
):
    """Fail closed: active capabilities can only be minted by invoke()."""

    del context
    raise _workflow_tx_error(
        "WORKFLOW_ACTION_TRANSACTION_ACTIVE_DISPATCH_REQUIRED",
        "active dispatch cannot be entered independently",
    )
    yield  # pragma: no cover


def _workflow_tx_active_dispatch_facts(
    context: WorkflowActionDispatchContext,
    verifier: _WorkflowTxCallable[
        [WorkflowActionDispatchContext], None
    ],
) -> dict[str, object]:
    if type(context) is not WorkflowActionDispatchContext:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_ACTIVE_DISPATCH_REQUIRED",
            "effect helper requires the exact active dispatch context",
        )
    if (
        context.settlement != "synchronous-quiescence"
        or context.launch_protocol != _WORKFLOW_TX_SYNC_DISPATCH_PROTOCOL
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_RELEASE_REQUIRED",
            "suspended runtime launch cannot execute business effects",
        )
    verifier(context)
    plan = context.plan
    return {
        "task_id": plan.task_id,
        "execution_id": plan.execution_id,
        "effect_id": plan.effect_id,
        "claim_id": plan.claim_id,
        "attempt_id": plan.attempt_id,
        "safe_input_sha256": semantic_sha256(
            SAFE_INPUT_DOMAIN, plan.safe_inputs
        ),
        "scope_lock_claims": [
            {"kind": kind, "identity": identity}
            for kind, identity in _workflow_tx_scope_claims(
                plan.required_lock_claims
            )
        ],
    }


def _workflow_tx_assert_effect_lock_boundary(
    task_path: _WorkflowTxPath,
    required_lock_claims: tuple[tuple[str, str], ...],
    *,
    operation: str,
    lock_error_code: str,
    scope_error_code: str,
) -> None:
    """Prove controller locks are absent and exact scope locks are live."""

    capabilities = _workflow_tx_live_lock_capabilities()
    forbidden = [
        item
        for item in capabilities
        if item.get("lock_name")
        in {
            "state.lock",
            "action-execution-index.lock",
            "workspace-registry.lock",
        }
    ]
    if forbidden:
        raise _workflow_tx_error(
            lock_error_code,
            f"{operation} adapter cannot run under task, index, or "
            "registry locks",
            details={
                "lock_names": sorted(
                    {
                        str(item.get("lock_name"))
                        for item in forbidden
                    }
                )
            },
        )
    held = {
        _workflow_tx_capability_key(item) for item in capabilities
    }
    required = {
        (
            str(
                _workflow_tx_scope_lock_directory(
                    task_path, kind, identity
                ).resolve(strict=False)
            ),
            "scope.lock",
        )
        for kind, identity in _workflow_tx_scope_claims(
            required_lock_claims
        )
    }
    if not required.issubset(held):
        raise _workflow_tx_error(
            scope_error_code,
            f"{operation} adapter requires every live deterministic "
            "scope lock",
        )


def _workflow_tx_assert_dispatch_lock_boundary(
    task_path: _WorkflowTxPath,
    context: WorkflowActionDispatchContext,
) -> None:
    _workflow_tx_assert_effect_lock_boundary(
        task_path,
        context.plan.required_lock_claims,
        operation="dispatch",
        lock_error_code=(
            "WORKFLOW_ACTION_TRANSACTION_DISPATCH_LOCK_HELD"
        ),
        scope_error_code=(
            "WORKFLOW_ACTION_TRANSACTION_DISPATCH_SCOPE_LOCK_MISSING"
        ),
    )


def _workflow_tx_assert_observe_lock_boundary(
    task_path: _WorkflowTxPath,
    context: WorkflowActionObserveContext,
) -> None:
    _workflow_tx_assert_effect_lock_boundary(
        task_path,
        context.required_lock_claims,
        operation="observe",
        lock_error_code=(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_LOCK_HELD"
        ),
        scope_error_code=(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_SCOPE_LOCK_MISSING"
        ),
    )


def _workflow_tx_runtime_release_permit_sha256(
    context: WorkflowActionRuntimeReleaseContext,
) -> str:
    binding = context.binding
    return semantic_sha256(
        _WORKFLOW_TX_RUNTIME_RELEASE_PERMIT_DOMAIN,
        {
            "binding": {
                "task_id": binding.task_id,
                "execution_id": binding.execution_id,
                "effect_id": binding.effect_id,
                "claim_id": binding.claim_id,
                "attempt_id": binding.attempt_id,
                "lease_id": binding.lease_id,
                "runtime_handle_sha256": (
                    binding.runtime_handle_sha256
                ),
                "runtime_binding_sha256": binding.binding_sha256,
                "stop_action_id": binding.stop_action_id,
                "reconcile_action_id": (
                    binding.reconcile_action_id
                ),
            },
            "containment_revision": context.containment_revision,
            "containment_record_sha256": (
                context.containment_record_sha256
            ),
            "journal_revision": context.journal_revision,
            "journal_record_sha256": (
                context.journal_record_sha256
            ),
            "index_revision": context.index_revision,
            "index_record_sha256": context.index_record_sha256,
            "required_lock_claims": [
                {"kind": kind, "identity": identity}
                for kind, identity in context.required_lock_claims
            ],
            "protocol": context.protocol,
        },
    )


def _workflow_tx_build_runtime_release_callback_authority():
    """Keep runtime-release permits and active callbacks in closure state."""

    lock = _workflow_tx_threading.Lock()
    permits: dict[int, tuple[object, str]] = {}
    active: dict[int, tuple[object, object, str, int]] = {}
    active_stack = _workflow_tx_contextvars.ContextVar(
        "dev_flow_v4_active_runtime_releases", default=()
    )

    def issue(
        context: WorkflowActionRuntimeReleaseContext,
    ) -> None:
        if type(context) is not WorkflowActionRuntimeReleaseContext:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_PERMIT_INVALID",
                "only an exact durable release context may receive a permit",
            )
        digest = _workflow_tx_runtime_release_permit_sha256(
            context
        )
        with lock:
            if id(context) in permits:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_PERMIT_INVALID",
                    "runtime release context already has a live permit",
                )
            permits[id(context)] = (context, digest)

    def invoke(
        task_path: _WorkflowTxPath,
        context: WorkflowActionRuntimeReleaseContext,
        callback: _WorkflowTxCallable[
            [WorkflowActionRuntimeReleaseContext], object
        ],
    ) -> object:
        if not callable(callback):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_INVALID",
                "runtime release adapter must be callable",
            )
        _workflow_tx_assert_effect_lock_boundary(
            task_path,
            context.required_lock_claims,
            operation="runtime release",
            lock_error_code=(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_LOCK_HELD"
            ),
            scope_error_code=(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_SCOPE_LOCK_MISSING"
            ),
        )
        digest = _workflow_tx_runtime_release_permit_sha256(
            context
        )
        capability = object()
        thread_id = _workflow_tx_threading.get_ident()
        with lock:
            registered = permits.get(id(context))
            if (
                registered is None
                or registered[0] is not context
                or registered[1] != digest
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_PERMIT_INVALID",
                    "runtime release requires the exact unconsumed durable permit",
                )
            del permits[id(context)]
            active[id(capability)] = (
                capability,
                context,
                digest,
                thread_id,
            )
        token = active_stack.set(
            (*active_stack.get(), capability)
        )
        try:
            return callback(context)
        finally:
            active_stack.reset(token)
            with lock:
                registered_active = active.get(id(capability))
                if (
                    registered_active is not None
                    and registered_active[0] is capability
                ):
                    del active[id(capability)]

    def verify(
        context: WorkflowActionRuntimeReleaseContext,
    ) -> None:
        stack = active_stack.get()
        capability = stack[-1] if stack else None
        digest = _workflow_tx_runtime_release_permit_sha256(
            context
        )
        thread_id = _workflow_tx_threading.get_ident()
        with lock:
            registered = (
                active.get(id(capability))
                if capability is not None
                else None
            )
            if (
                registered is None
                or registered[0] is not capability
                or registered[1] is not context
                or registered[2] != digest
                or registered[3] != thread_id
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_ACTIVE_RUNTIME_RELEASE_REQUIRED",
                    "runtime helper is outside its exact authorized release callback",
                )

    return issue, invoke, verify


(
    _WORKFLOW_TX_ISSUE_RUNTIME_RELEASE_PERMIT,
    _WORKFLOW_TX_INVOKE_RUNTIME_RELEASE_CALLBACK,
    _WORKFLOW_TX_VERIFY_ACTIVE_RUNTIME_RELEASE,
) = _workflow_tx_build_runtime_release_callback_authority()


def _workflow_tx_active_runtime_release_facts(
    context: WorkflowActionRuntimeReleaseContext,
    verifier: _WorkflowTxCallable[
        [WorkflowActionRuntimeReleaseContext], None
    ],
) -> dict[str, object]:
    if (
        type(context) is not WorkflowActionRuntimeReleaseContext
        or context.protocol
        != _WORKFLOW_TX_RUNTIME_RELEASE_PROTOCOL
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_ACTIVE_RUNTIME_RELEASE_REQUIRED",
            "runtime helper requires the exact active release context",
        )
    verifier(context)
    binding = context.binding
    return {
        "task_id": binding.task_id,
        "execution_id": binding.execution_id,
        "effect_id": binding.effect_id,
        "claim_id": binding.claim_id,
        "attempt_id": binding.attempt_id,
        "lease_id": binding.lease_id,
        "runtime_handle_sha256": binding.runtime_handle_sha256,
        "runtime_binding_sha256": binding.binding_sha256,
        "release_context_sha256": (
            context.release_context_sha256
        ),
        "stop_action_id": binding.stop_action_id,
        "reconcile_action_id": binding.reconcile_action_id,
        "scope_lock_claims": [
            {"kind": kind, "identity": identity}
            for kind, identity in _workflow_tx_scope_claims(
                context.required_lock_claims
            )
        ],
    }


def _workflow_tx_invocation_binding(
    invocation: WorkflowActionInvocation,
    edge_roles: _WorkflowActionEdgeRoles,
) -> dict[str, object]:
    outcome = invocation.action_outcome
    approval = invocation.approval_outcome
    return {
        "kind": invocation.kind,
        "public_command": invocation.public_command,
        "selector": invocation.selector,
        "target": invocation.target,
        "edge_selector": invocation.edge_selector,
        "edge_roles": edge_roles.binding(),
        "action_parameters": _workflow_transition_public(
            invocation.action_parameters
        ),
        "evidence": _workflow_transition_public(invocation.evidence),
        "confirm_intent": invocation.confirm_intent,
        "action_outcome": {
            "action_id": outcome.action_id,
            "proposed_edge_id": outcome.proposed_edge_id,
            "evidence_records": _workflow_transition_public(
                outcome.evidence_records
            ),
            "proposed_state_delta": _workflow_transition_public(
                outcome.proposed_state_delta
            ),
            "audit_facts": [
                {
                    "fact_type": fact.fact_type,
                    "payload": _workflow_transition_public(fact.payload),
                }
                for fact in outcome.audit_facts
            ],
            "external_postconditions": _workflow_transition_public(
                outcome.external_postconditions
            ),
        },
        "approval_outcome": (
            None
            if approval is None
            else {
                "gate_id": approval.gate_id,
                "proposed_edge_id": approval.proposed_edge_id,
                "approval": _workflow_transition_public(
                    approval.approval
                ),
                "evidence_records": _workflow_transition_public(
                    approval.evidence_records
                ),
                "audit_facts": [
                    {
                        "fact_type": fact.fact_type,
                        "payload": _workflow_transition_public(
                            fact.payload
                        ),
                    }
                    for fact in approval.audit_facts
                ],
            }
        ),
    }


def _workflow_tx_semantic_invocation_binding(
    invocation: WorkflowActionInvocation,
    edge_roles: _WorkflowActionEdgeRoles,
) -> dict[str, object]:
    """Bind the requested operation while excluding revision confirmation.

    A scoped transaction may be re-previewed at a newer unrelated revision,
    which necessarily changes the confirmation intent. Every caller-selected
    operation field and every action/approval/audit outcome remains bound.
    """

    binding = _workflow_tx_invocation_binding(
        invocation, edge_roles
    )
    binding.pop("confirm_intent")
    return binding


def _workflow_tx_edge(
    state: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
) -> _WorkflowTxMapping[str, object]:
    if invocation.kind == "node":
        return resolve_v4_node_action_edge(
            state,
            invocation.public_command,
            selector=invocation.selector,
        )
    assert invocation.target is not None
    return resolve_v4_movement_action_edge(
        state,
        invocation.public_command,
        target=invocation.target,
        edge_selector=invocation.edge_selector,
    )


def _workflow_tx_edge_roles(
    state: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
) -> _WorkflowActionEdgeRoles:
    """Resolve both roles from the pinned action and the typed outcome.

    Callers cannot inject a completion target. A different proposed edge is
    accepted only when it is the unique legal movement edge from the current
    node with the exact same public action trigger.
    """

    authorization_edge = _workflow_tx_edge(state, invocation)
    authorization_edge_id = authorization_edge.get("id")
    proposed_edge_id = invocation.action_outcome.proposed_edge_id
    if proposed_edge_id == authorization_edge_id:
        return _WorkflowActionEdgeRoles(
            authorization_action_edge=authorization_edge,
            completion_edge=authorization_edge,
        )
    if invocation.kind != "node":
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_MISMATCH",
            "action outcome does not bind its authorization action edge",
            details={
                "authorization_action_edge_id": authorization_edge_id,
                "proposed_edge_id": proposed_edge_id,
            },
        )
    authorization_trigger = authorization_edge.get("trigger")
    public_command = authorization_edge.get("public_command")
    if (
        not isinstance(authorization_trigger, _WorkflowTxMapping)
        or authorization_trigger.get("kind") != "action"
        or not isinstance(public_command, _WorkflowTxMapping)
        or public_command.get("id") != invocation.public_command
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "authorization action has no pinned public command",
            details={"edge_id": authorization_edge_id},
        )
    selector_name = public_command.get("selector")
    selector_values = public_command.get("values")
    selector_valid = (
        isinstance(selector_name, str)
        and isinstance(selector_values, (list, tuple))
        and invocation.selector in selector_values
    ) or (
        selector_name is None
        and isinstance(selector_values, (list, tuple))
        and not selector_values
        and invocation.selector is None
    )
    if not selector_valid:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "authorization selector is not pinned to this action",
            details={
                "authorization_action_edge_id": authorization_edge_id,
                "selector": invocation.selector,
            },
        )
    bundle = _workflow_action_bundle(state)
    candidates = [
        edge
        for edge in bundle.legal_movement_edges(str(state.get("status")))
        if edge.get("id") == proposed_edge_id
        and isinstance(edge.get("trigger"), _WorkflowTxMapping)
        and edge["trigger"].get("kind") == "action"
        and edge["trigger"].get("id") == invocation.public_command
    ]
    if len(candidates) != 1:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "action outcome does not resolve one same-trigger movement",
            details={
                "source": state.get("status"),
                "authorization_action_edge_id": authorization_edge_id,
                "proposed_edge_id": proposed_edge_id,
                "edge_ids": [edge.get("id") for edge in candidates],
            },
        )
    completion_edge = candidates[0]
    if (
        completion_edge.get("source") != state.get("status")
        or completion_edge.get("target") == state.get("status")
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "action completion must be a legal movement from the current node",
            details={
                "authorization_action_edge_id": authorization_edge_id,
                "completion_edge_id": completion_edge.get("id"),
            },
        )
    return _WorkflowActionEdgeRoles(
        authorization_action_edge=authorization_edge,
        completion_edge=completion_edge,
    )


def resolve_v4_workflow_action_completion_edge(
    state: _WorkflowTxMapping[str, object],
    authorization_action_edge: _WorkflowTxMapping[str, object],
    *,
    public_command: str,
    target: str,
) -> _WorkflowTxMapping[str, object]:
    """Resolve a result status to one catalog-pinned action completion."""

    bundle = _workflow_action_bundle(state)
    authorization_edge_id = authorization_action_edge.get("id")
    authorization_matches = [
        edge
        for edge in bundle.legal_action_edges(str(state.get("status")))
        if edge.get("id") == authorization_edge_id
        and edge == authorization_action_edge
        and isinstance(edge.get("public_command"), _WorkflowTxMapping)
        and edge["public_command"].get("id") == public_command
    ]
    if len(authorization_matches) != 1:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "completion resolver requires one pinned authorization action",
            details={
                "authorization_action_edge_id": authorization_edge_id
            },
        )
    if target == state.get("status"):
        return authorization_matches[0]
    candidates = [
        edge
        for edge in bundle.legal_movement_edges(str(state.get("status")))
        if edge.get("target") == target
        and isinstance(edge.get("trigger"), _WorkflowTxMapping)
        and edge["trigger"].get("kind") == "action"
        and edge["trigger"].get("id") == public_command
    ]
    if len(candidates) != 1:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "result status does not resolve one same-command completion edge",
            details={
                "source": state.get("status"),
                "target": target,
                "authorization_action_edge_id": authorization_edge_id,
                "completion_edge_ids": [
                    edge.get("id") for edge in candidates
                ],
            },
        )
    return candidates[0]


def _workflow_tx_evaluate(
    state: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
    *,
    preview: bool,
    receipt_context: WorkflowActionReceiptContext | None = None,
    manager_intent_state: _WorkflowTxMapping[str, object] | None = None,
    edge_roles: _WorkflowActionEdgeRoles | None = None,
) -> TransitionEvaluation:
    roles = edge_roles or _workflow_tx_edge_roles(state, invocation)
    if roles.completes_movement:
        completion_edge = roles.completion_edge
        completion_target = completion_edge.get("target")
        if not isinstance(completion_target, str) or not completion_target:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
                "action completion edge has no exact target",
                details={"edge_id": completion_edge.get("id")},
            )
        canonical_event = roles.authorization_action_edge.get(
            "canonical_event"
        )
        if not isinstance(canonical_event, str) or not canonical_event:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
                "action completion has no canonical audit event",
                details={
                    "authorization_action_edge_id": (
                        roles.authorization_action_edge_id
                    )
                },
            )
        try:
            proposed_set = (
                invocation.action_outcome.proposed_state_delta.get(
                    "set"
                )
            )
            proposed_status = (
                proposed_set.get("/status")
                if isinstance(proposed_set, _WorkflowTxMapping)
                else None
            )
            if proposed_status != completion_target:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
                    "action outcome status differs from its pinned completion edge",
                    details={
                        "completion_edge_id": completion_edge.get("id"),
                        "expected_target": completion_target,
                        "actual_target": proposed_status,
                    },
                )
            desired = _transition_engine_apply_kernel_delta(
                state,
                invocation.action_outcome.proposed_state_delta,
                completion_edge,
                invocation.action_parameters,
            )
            desired["status"] = completion_target
            parameters = dict(invocation.action_parameters)
            parameters[_workflow_action_selection_parameter] = {
                "kind": "node-action-completion",
                "public_command": invocation.public_command,
                "selector": invocation.selector,
                "target": completion_target,
                "canonical_event": canonical_event,
                **roles.binding(),
            }
            if not preview:
                parameters["intent_id"] = invocation.confirm_intent
            return evaluate_v4_workflow_movement(
                state,
                desired,
                event_type=canonical_event,
                payload=parameters,
                preview_only=preview,
                compare_desired=True,
                manager_intent_state=manager_intent_state,
            )
        except TransitionEngineError:
            raise
    common = {
        "public_command": invocation.public_command,
        "action_outcome": invocation.action_outcome,
        "approval_outcome": invocation.approval_outcome,
        "action_parameters": invocation.action_parameters,
        "evidence": invocation.evidence,
        "confirm_intent": invocation.confirm_intent,
        "preview": preview,
        "receipt_context": receipt_context,
    }
    if invocation.kind == "node":
        return evaluate_v4_node_action(
            state,
            selector=invocation.selector,
            **common,
        )
    assert invocation.target is not None
    return evaluate_v4_movement_action(
        state,
        target=invocation.target,
        edge_selector=invocation.edge_selector,
        **common,
    )


def _workflow_tx_evaluation_state(
    state: _WorkflowTxMapping[str, object],
    edge: _WorkflowTxMapping[str, object],
    authorization: WorkflowActionAuthorization | None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Prepare the manager nonce before every receipt-bound evaluation."""

    durable = _workflow_tx_copy.deepcopy(
        _workflow_transition_public(state)
    )
    if not isinstance(durable, dict):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_STATE_INVALID",
            "action transaction requires an object task state",
        )
    if (
        type(authorization) is not WorkflowActionAuthorization
        or authorization.kind != "manager"
    ):
        return durable, None
    event_type = edge.get("canonical_event")
    if not isinstance(event_type, str) or not event_type:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "manager action edge has no canonical event",
            details={"edge_id": edge.get("id")},
        )
    try:
        prepared = _manager_engine_evaluation_state_v1(
            durable, event_type=event_type
        )
    except FlowError as exc:
        raise _workflow_tx_error(
            exc.code, exc.message, details=exc.details
        ) from exc
    if not isinstance(prepared, dict):
        raise _workflow_tx_error(
            "MANAGER_PREAUTHORIZATION_REQUIRED",
            "manager action transaction has no nonce-prepared state",
        )
    if (
        prepared.get("task_id") != durable.get("task_id")
        or prepared.get("revision") != durable.get("revision")
        or prepared.get("status") != durable.get("status")
        or prepared.get("workflow_ref") != durable.get("workflow_ref")
    ):
        raise _workflow_tx_error(
            "MANAGER_AUTHORIZATION_DELTA_INVALID",
            "manager action preparation changed the task binding",
        )
    return prepared, durable


def _workflow_tx_reauthenticate(
    authorization: WorkflowActionAuthorization,
) -> str | bytes | None:
    try:
        secret = authorization.reauthenticate()
    except Exception as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_REAUTHENTICATION_FAILED",
            "authorization could not be reauthenticated",
        ) from exc
    if authorization.kind == "manager":
        if not isinstance(secret, (str, bytes)) or not secret:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_REAUTHENTICATION_FAILED",
                "manager reauthentication returned no secret",
            )
    elif secret is not None:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_REAUTHENTICATION_FAILED",
            "operator reauthentication must not return a manager secret",
        )
    return secret


def _workflow_tx_assert_journal_authorization(
    journal: _WorkflowTxMapping[str, object],
    authorization: WorkflowActionAuthorization,
) -> None:
    bindings = journal.get("bindings")
    if not isinstance(bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            "execution journal has no immutable authorization bindings",
        )
    expected = {
        "authorization_kind": authorization.kind,
        "authorization_sha256": authorization.authorization_sha256,
        "capability_sha256": authorization.capability_sha256,
        "request_nonce_sha256": authorization.request_nonce_sha256,
        "principal": authorization.principal,
        "ownership_sha256": authorization.ownership_sha256,
        "registry_state_sha256": authorization.registry_state_sha256,
    }
    mismatches = sorted(
        field
        for field, value in expected.items()
        if bindings.get(field) != value
    )
    if mismatches:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_AUTHORIZATION_MISMATCH",
            "current authorization differs from the durable execution",
            details={"fields": mismatches},
        )


def _workflow_tx_effect(
    journal: _WorkflowTxMapping[str, object],
    effect_id: str,
) -> dict[str, object]:
    effects = journal.get("effects")
    if isinstance(effects, list):
        for effect in effects:
            if (
                isinstance(effect, _WorkflowTxMapping)
                and effect.get("effect_id") == effect_id
            ):
                return _workflow_tx_copy.deepcopy(dict(effect))
    raise _workflow_tx_error(
        "WORKFLOW_ACTION_TRANSACTION_EFFECT_MISSING",
        "execution journal does not declare the requested effect",
        details={"effect_id": effect_id},
    )


def _workflow_tx_dispatch_effects(
    edge: _WorkflowTxMapping[str, object],
) -> tuple[_WorkflowTxMapping[str, object], ...]:
    effects = edge.get("effects")
    if not isinstance(effects, (list, tuple)):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "selected catalog edge has no typed effects",
        )
    if any(not isinstance(effect, _WorkflowTxMapping) for effect in effects):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "selected catalog edge contains an untyped effect",
        )
    dispatching = tuple(
        effect
        for effect in effects
        if effect.get("dispatch") == "single-dispatch"
    )
    unsupported = [
        effect.get("id")
        for effect in effects
        if effect.get("dispatch") not in {"none", "single-dispatch"}
    ]
    if unsupported:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "catalog effect has an unsupported dispatch policy",
            details={"effect_ids": unsupported},
        )
    return tuple(
        sorted(
            dispatching,
            key=lambda effect: str(effect.get("id")).encode("utf-8"),
        )
    )


def _workflow_tx_dispatch_effect(
    edge: _WorkflowTxMapping[str, object],
) -> _WorkflowTxMapping[str, object] | None:
    """Compatibility projection for callers not yet migrated to a DAG."""

    dispatching = _workflow_tx_dispatch_effects(edge)
    if not dispatching:
        return None
    if len(dispatching) != 1:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_MULTI_EFFECT_REQUIRED",
            "catalog edge requires the multi-effect transaction path",
            details={"edge_id": edge.get("id")},
        )
    return dispatching[0]


def _workflow_tx_bound_scopes(
    state: _WorkflowTxMapping[str, object],
    catalog_effect: _WorkflowTxMapping[str, object],
    binding: WorkflowActionEffectBinding,
) -> dict[str, object]:
    declared = tuple(catalog_effect.get("scopes", ()))
    if binding.scope_kinds != declared:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_MISMATCH",
            "typed effect scope kinds differ from the pinned catalog edge",
        )
    scopes = {
        key: list(value)
        for key, value in dict(binding.scopes).items()
    }
    if "task" in declared:
        node_ids = set(scopes["node_ids"])
        node_ids.add(str(state["status"]))
        scopes["node_ids"] = sorted(
            node_ids, key=lambda item: item.encode("utf-8")
        )
    requirements = {
        "repository": bool(scopes["repository_ids"]),
        "worktree": bool(scopes["worktree_ids"] or scopes["paths"]),
        "external-index": bool(scopes["external_resources"]),
        "secret-channel": bool(scopes["external_resources"]),
    }
    missing = [
        kind
        for kind, satisfied in requirements.items()
        if kind in declared and not satisfied
    ]
    if missing:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_SCOPE_MISSING",
            "typed effect binding does not realize every catalog scope",
            details={"scope_kinds": missing},
        )
    return normalize_scopes(scopes)


def compile_v4_workflow_action_journal(
    state: _WorkflowTxMapping[str, object],
    edge: _WorkflowTxMapping[str, object],
    preview: TransitionEvaluation,
    invocation: WorkflowActionInvocation,
    authorization: WorkflowActionAuthorization,
    effect_binding: WorkflowActionEffectBinding | None = None,
    *,
    execution_id: str,
    effect_bindings: tuple[WorkflowActionEffectBinding, ...] | None = None,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    """Compile a PREPARED journal from exact authorization/completion roles."""

    if not isinstance(execution_id, str) or not execution_id:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EXECUTION_INVALID",
            "execution identity is required",
        )
    catalog_effects = _workflow_tx_dispatch_effects(edge)
    if not catalog_effects:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_JOURNAL_FORBIDDEN",
            "effect-free actions must use the generic engine proof directly",
        )
    if effect_bindings is None:
        supplied_bindings = (
            (effect_binding,)
            if type(effect_binding) is WorkflowActionEffectBinding
            else ()
        )
    elif (
        effect_binding is None
        and isinstance(effect_bindings, tuple)
        and all(
            type(item) is WorkflowActionEffectBinding
            for item in effect_bindings
        )
    ):
        supplied_bindings = effect_bindings
    else:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
            "effect bindings must use exactly one typed input form",
        )
    bindings_by_id = {
        binding.effect_id: binding for binding in supplied_bindings
    }
    catalog_ids = tuple(
        str(effect.get("id")) for effect in catalog_effects
    )
    if (
        len(bindings_by_id) != len(supplied_bindings)
        or set(bindings_by_id) != set(catalog_ids)
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_MISMATCH",
            "typed effects must exactly cover every dispatching catalog effect",
            details={
                "catalog_effect_ids": list(catalog_ids),
                "binding_effect_ids": sorted(bindings_by_id),
            },
        )
    effect_rows: list[
        tuple[
            _WorkflowTxMapping[str, object],
            WorkflowActionEffectBinding,
            dict[str, object],
        ]
    ] = []
    merged_scopes = {
        "repository_ids": set(),
        "node_ids": set(),
        "worktree_ids": set(),
        "lease_ids": set(),
        "paths": set(),
        "external_resources": set(),
    }
    for catalog_effect in catalog_effects:
        binding = bindings_by_id[str(catalog_effect["id"])]
        scopes = _workflow_tx_bound_scopes(
            state, catalog_effect, binding
        )
        for field, values in scopes.items():
            merged_scopes[field].update(values)
        effect_rows.append((catalog_effect, binding, scopes))
    scopes = normalize_scopes(
        {
            field: sorted(
                values, key=lambda item: item.encode("utf-8")
            )
            for field, values in merged_scopes.items()
        }
    )
    concurrency_values = {
        str(catalog_effect.get("concurrency"))
        for catalog_effect in catalog_effects
    }
    if not concurrency_values.issubset(
        {"exclusive-task", "scoped"}
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "catalog effect declares an invalid concurrency class",
        )
    concurrency_class = (
        "exclusive-task"
        if "exclusive-task" in concurrency_values
        else "scoped"
    )
    revision_policy = (
        "exact-revision"
        if concurrency_class == "exclusive-task"
        else "disjoint-scope-revalidate"
    )
    bundle = _workflow_action_bundle(state)
    edge_roles = _workflow_tx_edge_roles(state, invocation)
    if (
        edge.get("id")
        != edge_roles.authorization_action_edge_id
        or preview.edge_id != edge_roles.completion_edge_id
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_COMPLETION_INVALID",
            "journal preview does not bind both pinned edge roles",
            details={
                **edge_roles.binding(),
                "authorization_argument_edge_id": edge.get("id"),
                "preview_edge_id": preview.edge_id,
            },
        )
    handler = edge_roles.completion_edge.get("handler")
    if not isinstance(handler, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CATALOG_INVALID",
            "selected edge has no pinned handler",
        )
    invocation_binding = _workflow_tx_invocation_binding(
        invocation, edge_roles
    )
    semantic_invocation_binding = (
        _workflow_tx_semantic_invocation_binding(
            invocation, edge_roles
        )
    )
    guard_projection = [
        {
            "guard_id": guard_id,
            "passed": result.passed,
            "evidence": _workflow_transition_public(result.evidence),
            "blockers": _workflow_transition_public(result.blockers),
        }
        for guard_id, result in preview.guard_results
    ]
    effect_plan = {
        "edge_roles": edge_roles.binding(),
        "effects": [
            {
                "catalog": _workflow_transition_public(catalog_effect),
                "binding": {
                    "effect_id": binding.effect_id,
                    "kind": binding.kind,
                    "scope_kinds": list(binding.scope_kinds),
                    "scopes": effect_scopes,
                    "safe_input_sha256": semantic_sha256(
                        SAFE_INPUT_DOMAIN,
                        dict(binding.safe_inputs),
                    ),
                    "attempt_id": binding.attempt_id,
                },
            }
            for catalog_effect, binding, effect_scopes in effect_rows
        ],
    }
    effect_plan_sha256 = semantic_sha256(
        _WORKFLOW_TX_EFFECT_PLAN_DOMAIN, effect_plan
    )
    workflow_version = getattr(bundle, "workflow_version", None)
    if not isinstance(workflow_version, str):
        workflow_version = str(workflow_version)
    journal_core = {
        "schema": ACTION_EXECUTION_JOURNAL_SCHEMA,
        "task_id": state["task_id"],
        "execution_id": execution_id,
        "revision": 0,
        "phase": "PREPARED",
        "bindings": {
            "task_revision": state["revision"],
            "pre_effect_state_sha256": _sha256_contract(state),
            "workflow_id": getattr(bundle, "workflow_id"),
            "workflow_version": workflow_version,
            "workflow_bundle_sha256": getattr(
                bundle, "bundle_sha256"
            ),
            "authorization_action_edge_id": (
                edge_roles.authorization_action_edge_id
            ),
            "completion_edge_id": edge_roles.completion_edge_id,
            "action_edge_id": edge_roles.completion_edge_id,
            "handler_id": handler["id"],
            "effect_plan_sha256": effect_plan_sha256,
            "concurrency_class": concurrency_class,
            "scopes": scopes,
            "authorized_paths": list(scopes["paths"]),
            "confirmation_sha256": semantic_sha256(
                _WORKFLOW_TX_CONFIRMATION_DOMAIN,
                {"intent_id": invocation.confirm_intent},
            ),
            "operation_sha256": semantic_sha256(
                _WORKFLOW_TX_OPERATION_DOMAIN, invocation_binding
            ),
            "semantic_operation_sha256": semantic_sha256(
                _WORKFLOW_TX_SEMANTIC_OPERATION_DOMAIN,
                semantic_invocation_binding,
            ),
            "authorization_kind": authorization.kind,
            "authorization_sha256": (
                authorization.authorization_sha256
            ),
            "capability_sha256": authorization.capability_sha256,
            "request_sha256": semantic_sha256(
                _WORKFLOW_TX_REQUEST_DOMAIN, invocation_binding
            ),
            "request_nonce_sha256": (
                authorization.request_nonce_sha256
            ),
            "principal": authorization.principal,
            "guard_projection_sha256": semantic_sha256(
                _WORKFLOW_TX_GUARD_DOMAIN, guard_projection
            ),
            "evidence_sha256": semantic_sha256(
                _WORKFLOW_TX_EVIDENCE_DOMAIN,
                _workflow_transition_public(invocation.evidence),
            ),
            "approval_sha256": semantic_sha256(
                _WORKFLOW_TX_APPROVAL_DOMAIN,
                invocation_binding["approval_outcome"],
            ),
            "ownership_sha256": authorization.ownership_sha256,
            "registry_state_sha256": (
                authorization.registry_state_sha256
            ),
            "postcondition_contract_sha256": semantic_sha256(
                _WORKFLOW_TX_POSTCONDITION_DOMAIN,
                {
                    "receipts": [
                        catalog_effect.get("receipt")
                        for catalog_effect in catalog_effects
                    ],
                    "external_postconditions": (
                        invocation_binding["action_outcome"][
                            "external_postconditions"
                        ]
                    ),
                },
            ),
            "verifier_before_sha256": semantic_sha256(
                _WORKFLOW_TX_VERIFIER_DOMAIN,
                {
                    "evaluation": _workflow_action_evaluation_binding(
                        preview
                    ),
                    "edge_roles": edge_roles.binding(),
                    "effect_plan_sha256": effect_plan_sha256,
                },
            ),
            "candidate_after_sha256": (
                _workflow_action_candidate_binding_sha256(
                    preview, revision_policy
                )
            ),
            "revision_policy": revision_policy,
        },
        "effects": [
            {
                "effect_id": binding.effect_id,
                "kind": binding.kind,
                "settlement": catalog_effect["settlement"],
                "scopes": effect_scopes,
                "safe_inputs": dict(binding.safe_inputs),
                "safe_input_sha256": semantic_sha256(
                    SAFE_INPUT_DOMAIN, dict(binding.safe_inputs)
                ),
                "idempotency_key_sha256": semantic_sha256(
                    _WORKFLOW_TX_IDEMPOTENCY_DOMAIN,
                    {
                        "execution_id": execution_id,
                        "effect_id": binding.effect_id,
                        "attempt_id": binding.attempt_id,
                        "catalog_policy": catalog_effect.get(
                            "idempotency"
                        ),
                        "edge_roles": edge_roles.binding(),
                    },
                ),
                "predecessors": list(catalog_effect["dependencies"]),
                "parallel_group": catalog_effect["parallel_group"],
                "attempt_id": binding.attempt_id,
                "phase": "PLANNED",
                "settled_as": None,
                "claim_id": None,
                "containment_record_sha256": None,
                "runtime_binding_sha256": None,
                "receipt_sha256": None,
            }
            for catalog_effect, binding, effect_scopes in effect_rows
        ],
        "receipt": None,
        "quarantine": None,
        "reconciliation_attempt_ids": [],
        "finalization": None,
    }
    return seal_journal(
        journal_core, manager_secret=manager_secret
    )


def _workflow_tx_persist_update(
    store: ActionExecutionStore,
    context: StoredActionExecution,
    updated: dict[str, object],
    *,
    manager_secret: str | bytes | None,
    failure_hook: _WorkflowTxCallable[[str], None] | None,
) -> StoredActionExecution:
    assert context.record is not None
    return store.persist_update(
        updated,
        expected_index=cas_token(context.index),
        expected_journal=cas_token(context.record),
        manager_secret=manager_secret,
        failure_hook=failure_hook,
    )


def _workflow_tx_validate_observation(
    observation: object,
    plan: ActionDispatchPlan,
) -> WorkflowActionEffectObservation:
    if type(observation) is not WorkflowActionEffectObservation:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
            "dispatcher must return the exact typed observation",
        )
    expected = {
        "task_id": plan.task_id,
        "execution_id": plan.execution_id,
        "effect_id": plan.effect_id,
        "claim_id": plan.claim_id,
        "attempt_id": plan.attempt_id,
    }
    mismatches = {
        field: getattr(observation, field)
        for field, value in expected.items()
        if getattr(observation, field) != value
    }
    if (
        mismatches
        or observation.settlement != "QUIESCED"
        or observation.runtime_handle_sha256 is not None
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
            "dispatcher observation does not bind the durable claim",
            details={"fields": sorted(mismatches)},
        )
    return observation


def _workflow_tx_read_events(
    path: _WorkflowTxPath,
) -> tuple[dict[str, object], ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        values = tuple(
            _workflow_tx_json.loads(line)
            for line in lines
            if line.strip()
        )
    except (OSError, UnicodeError, _workflow_tx_json.JSONDecodeError) as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OUTBOX_INVALID",
            "authoritative event log could not be read",
        ) from exc
    if not all(isinstance(item, dict) for item in values):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OUTBOX_INVALID",
            "authoritative event log contains a non-object record",
        )
    return values


def _workflow_tx_authority_facts(
    task_dir: _WorkflowTxPath,
    journal: _WorkflowTxMapping[str, object],
) -> _WorkflowActionAuthorityFacts | None:
    bindings = journal.get("bindings")
    receipt = journal.get("receipt")
    if not isinstance(bindings, _WorkflowTxMapping) or not isinstance(
        receipt, _WorkflowTxMapping
    ):
        return None
    prepared_revision = int(bindings["task_revision"])
    revision_policy = bindings.get("revision_policy")
    state_path = task_dir / "state.json"
    raw_state = _read_task_state_json(state_path)
    if not isinstance(raw_state, dict):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_STATE_INVALID",
            "authoritative task state is not an object",
        )
    _validate_task_state_snapshot(state_path, raw_state)
    pending = raw_state.get("pending_events")
    if pending is None and raw_state.get("pending_event") is not None:
        pending = [raw_state["pending_event"]]
    pending_events = (
        tuple(_workflow_tx_copy.deepcopy(pending))
        if isinstance(pending, list)
        else ()
    )
    state = load_state(state_path)
    if state.get("revision") <= prepared_revision:
        return None
    if state.get("task_id") != journal.get("task_id"):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_AUTHORITY_DRIFT",
            "task state identity differs from the journal transaction",
            details={
                "actual_revision": state.get("revision"),
            },
        )
    event_sources = (
        pending_events,
        _workflow_tx_read_events(task_dir / "events.jsonl"),
    )
    events: tuple[dict[str, object], ...] = ()
    matches: list[dict[str, object]] = []
    for event_source in event_sources:
        source_matches = []
        for event in event_source:
            payload = event.get("payload")
            execution = (
                payload.get("execution")
                if isinstance(payload, _WorkflowTxMapping)
                else None
            )
            previous_revision = event.get("previous_revision")
            event_revision = event.get("revision")
            revision_chain_valid = (
                isinstance(previous_revision, int)
                and not isinstance(previous_revision, bool)
                and isinstance(event_revision, int)
                and not isinstance(event_revision, bool)
                and event_revision == previous_revision + 1
            )
            policy_revision_valid = (
                revision_chain_valid
                and (
                    (
                        revision_policy == "exact-revision"
                        and previous_revision == prepared_revision
                    )
                    or (
                        revision_policy
                        == "disjoint-scope-revalidate"
                        and previous_revision >= prepared_revision
                    )
                )
            )
            if (
                event.get("task_id") == journal.get("task_id")
                and policy_revision_valid
                and isinstance(execution, _WorkflowTxMapping)
                and execution.get("execution_id")
                == journal.get("execution_id")
                and execution.get("receipt_sha256")
                == receipt.get("receipt_sha256")
                and payload.get("edge_id") == bindings["action_edge_id"]
            ):
                source_matches.append(event)
        if source_matches:
            events = event_source
            matches = source_matches
            break
    if not matches:
        return None
    if len(matches) != 1:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OUTBOX_INVALID",
            "authoritative outbox contains duplicate execution events",
        )
    primary = matches[0]
    expected_revision = primary["revision"]
    previous_revision = primary["previous_revision"]
    if state.get("revision") != expected_revision:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_AUTHORITY_DRIFT",
            "task state advanced beyond the journal transaction",
            details={
                "expected_revision": expected_revision,
                "actual_revision": state.get("revision"),
            },
        )
    transaction_id = primary.get("transaction_id")
    if transaction_id is None:
        batch = (primary,)
    else:
        batch = tuple(
            event
            for event in events
            if event.get("transaction_id") == transaction_id
        )
    if (
        not batch
        or any(
            event.get("task_id") != journal.get("task_id")
            or event.get("revision") != expected_revision
            or event.get("previous_revision")
            != previous_revision
            for event in batch
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OUTBOX_INVALID",
            "authoritative event batch is not one exact task transaction",
        )
    return _WorkflowActionAuthorityFacts(
        state=_workflow_tx_copy.deepcopy(state),
        events=tuple(
            _workflow_tx_copy.deepcopy(event) for event in batch
        ),
        event_sha256=semantic_sha256(
            _WORKFLOW_TX_EVENT_DOMAIN, primary
        ),
        outbox_sha256=semantic_sha256(
            _WORKFLOW_TX_OUTBOX_DOMAIN, list(batch)
        ),
    )


def _workflow_tx_nonce_consumed(
    authorization: WorkflowActionAuthorization,
    facts: _WorkflowActionAuthorityFacts,
) -> bool:
    if authorization.kind == "operator":
        return False
    verifier = authorization.nonce_consumed_verifier
    assert verifier is not None
    try:
        consumed = verifier(facts.state, facts.events)
    except Exception as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_NONCE_VERIFICATION_FAILED",
            "manager nonce consumption could not be verified",
        ) from exc
    if type(consumed) is not bool or not consumed:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_NONCE_NOT_CONSUMED",
            "manager transaction cannot finalize without authoritative "
            "nonce consumption",
        )
    return True


def _workflow_tx_validate_recovery_invocation(
    journal: _WorkflowTxMapping[str, object],
    state: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
    authorization: WorkflowActionAuthorization,
) -> None:
    """Rebind a typed restart request to the immutable prepared journal."""

    if type(invocation) is not WorkflowActionInvocation:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_INVOCATION_INVALID",
            "receipt recovery requires the exact typed invocation",
        )
    bindings = journal.get("bindings")
    if not isinstance(bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_BINDING_INVALID",
            "promoted journal has no exact immutable bindings",
        )
    edge_roles = _workflow_tx_edge_roles(state, invocation)
    invocation_binding = _workflow_tx_invocation_binding(
        invocation, edge_roles
    )
    expected = {
        "task_id": state.get("task_id"),
        "task_revision": state.get("revision"),
        "pre_effect_state_sha256": _sha256_contract(state),
        "operation_sha256": semantic_sha256(
            _WORKFLOW_TX_OPERATION_DOMAIN, invocation_binding
        ),
        "request_sha256": semantic_sha256(
            _WORKFLOW_TX_REQUEST_DOMAIN, invocation_binding
        ),
        "confirmation_sha256": semantic_sha256(
            _WORKFLOW_TX_CONFIRMATION_DOMAIN,
            {"intent_id": invocation.confirm_intent},
        ),
        "authorization_kind": authorization.kind,
        "authorization_sha256": authorization.authorization_sha256,
        "capability_sha256": authorization.capability_sha256,
        "request_nonce_sha256": authorization.request_nonce_sha256,
        "principal": authorization.principal,
        "ownership_sha256": authorization.ownership_sha256,
        "registry_state_sha256": authorization.registry_state_sha256,
    }
    actual = {
        "task_id": journal.get("task_id"),
        **{
            key: bindings.get(key)
            for key in expected
            if key != "task_id"
        },
    }
    mismatches = sorted(
        key
        for key, value in expected.items()
        if actual.get(key) != value
    )
    if mismatches:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_BINDING_MISMATCH",
            "typed recovery request differs from the prepared transaction",
            details={"fields": mismatches},
        )
    bundle = _workflow_action_bundle(state)
    if (
        edge_roles.authorization_action_edge_id
        != bindings.get("authorization_action_edge_id")
        or edge_roles.completion_edge_id
        != bindings.get("completion_edge_id")
        or edge_roles.completion_edge_id
        != bindings.get("action_edge_id")
        or getattr(bundle, "workflow_id", None)
        != bindings.get("workflow_id")
        or str(getattr(bundle, "workflow_version", ""))
        != bindings.get("workflow_version")
        or getattr(bundle, "bundle_sha256", None)
        != bindings.get("workflow_bundle_sha256")
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_BINDING_MISMATCH",
            "typed recovery request does not resolve the prepared bundle edge",
        )


def _workflow_tx_commit_evaluation(
    old_state: dict[str, object],
    evaluation: TransitionEvaluation,
    task_path: _WorkflowTxPath,
    authorization: WorkflowActionAuthorization,
    receipt_context: WorkflowActionReceiptContext,
) -> dict[str, object]:
    """Commit through the typed action boundary and live manager gate."""

    if authorization.kind != "manager":
        return commit_v4_workflow_action(
            old_state,
            evaluation,
            task_path,
            receipt_context=receipt_context,
        )
    (
        bundle,
        edge,
        selection,
        event_type,
        payload,
        additional_events,
    ) = _workflow_action_commit_components(old_state, evaluation)
    verified_receipt, verified_journal = (
        _workflow_action_verified_journal_receipt(
            old_state,
            bundle,
            edge,
            receipt_context,
        )
    )
    if (
        not isinstance(verified_receipt, _WorkflowTxMapping)
        or not isinstance(verified_journal, _WorkflowTxMapping)
        or not isinstance(
            verified_journal.get("execution_id"), str
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECEIPT_REQUIRED",
            "manager action commit requires one verified journal receipt",
        )
    (
        _bundle,
        _edge,
        _selection,
        event_type,
        payload,
        additional_events,
    ) = _workflow_action_commit_components(
        old_state,
        evaluation,
        execution_binding={
            "execution_id": verified_journal["execution_id"],
            "receipt_sha256": verified_receipt["receipt_sha256"],
        },
    )
    _workflow_action_validate_receipt_candidate(
        evaluation, verified_receipt, verified_journal
    )
    candidate = _workflow_tx_copy.deepcopy(
        _workflow_transition_public(evaluation.candidate_state)
    )
    if not isinstance(candidate, dict):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_STATE_INVALID",
            "manager action evaluation produced no object candidate",
        )
    event_batch = _workflow_transition_event_batch_binding(
        event_type,
        payload,
        additional_events,
        event_ids=None,
        transaction_id=None,
    )
    if verified_receipt.get(
        "event_batch_sha256"
    ) != _sha256_contract(event_batch):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECEIPT_MISMATCH",
            "verified receipt does not bind the action event batch",
        )
    expected_engine_binding = (
        workflow_action_engine_proof_binding_sha256(
            old_state,
            evaluation,
            task_path,
            verified_receipt,
            execution_id=str(verified_journal["execution_id"]),
        )
    )
    if verified_receipt.get(
        "engine_proof_sha256"
    ) != expected_engine_binding:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECEIPT_MISMATCH",
            "verified receipt does not bind the action proof core",
        )
    _commit_state(
        old_state,
        candidate,
        task_path,
        event_type,
        payload,
        additional_events=additional_events,
        _engine_commit_evaluation=evaluation,
        _verified_receipt=verified_receipt,
    )
    return candidate


def _workflow_tx_dispatch_context(
    plan: ActionDispatchPlan,
    effect: _WorkflowTxMapping[str, object],
    journal: _WorkflowTxMapping[str, object],
) -> WorkflowActionDispatchContext:
    bindings = journal.get("bindings")
    if not isinstance(bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            "execution journal has no immutable bindings",
        )
    settlement = effect.get("settlement")
    if settlement == "synchronous-quiescence":
        public_settlement = "synchronous-quiescence"
    elif settlement == "asynchronous-handoff":
        public_settlement = "asynchronous-handoff"
    else:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
            "effect has no supported settlement contract",
        )
    return WorkflowActionDispatchContext(
        plan=plan,
        effect_kind=str(effect["kind"]),
        settlement=public_settlement,
        scopes=_workflow_tx_copy.deepcopy(dict(effect["scopes"])),
        catalog_contract_sha256=str(
            bindings["effect_plan_sha256"]
        ),
        launch_protocol=(
            _WORKFLOW_TX_RUNTIME_LAUNCH_PROTOCOL
            if public_settlement == "asynchronous-handoff"
            else _WORKFLOW_TX_SYNC_DISPATCH_PROTOCOL
        ),
    )


def _workflow_tx_observe_context(
    stored: StoredActionExecution,
    effect: _WorkflowTxMapping[str, object],
    containment: _WorkflowTxMapping[str, object],
) -> WorkflowActionObserveContext:
    """Reconstruct an observe-only context from one exact promoted CAS."""

    record = stored.record
    if record is None:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
            "observe context requires the promoted execution journal",
        )
    bindings = record.get("bindings")
    if not isinstance(bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
            "execution journal has no immutable effect-plan binding",
        )
    expected_identity = {
        "task_id": record.get("task_id"),
        "execution_id": record.get("execution_id"),
        "effect_id": effect.get("effect_id"),
        "claim_id": effect.get("claim_id"),
        "attempt_id": effect.get("attempt_id"),
    }
    mismatches = sorted(
        field
        for field, expected in expected_identity.items()
        if containment.get(field) != expected
    )
    linked_containment = effect.get(
        "containment_record_sha256"
    )
    released_async_successor = (
        effect.get("settlement") == "asynchronous-handoff"
        and effect.get("phase") == "RUNNING"
        and containment.get("phase") == "RELEASED"
    )
    if (
        mismatches
        or effect.get("claim_id") is None
        or (
            linked_containment is not None
            and linked_containment
            != containment.get("record_sha256")
            and not released_async_successor
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_MISMATCH",
            "durable containment differs from the promoted effect claim",
            details={"fields": mismatches},
        )
    settlement = effect.get("settlement")
    if settlement not in {
        "synchronous-quiescence",
        "asynchronous-handoff",
    }:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
            "durable effect has no supported observation settlement",
        )
    if (
        settlement == "asynchronous-handoff"
        and (
            effect.get("runtime_binding_sha256") is None
            or containment.get("runtime_handle_sha256") is None
            or containment.get("phase")
            not in {
                "RELEASED",
                "HANDOFF_VERIFIED",
                "CLOSED",
                "QUARANTINED",
            }
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_REQUIRED",
            "async observe-only context requires a released runtime binding",
        )
    safe_inputs = effect.get("safe_inputs")
    scopes = effect.get("scopes")
    if (
        not isinstance(safe_inputs, _WorkflowTxMapping)
        or not isinstance(scopes, _WorkflowTxMapping)
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_INVALID",
            "durable effect lost safe-input or scope bindings",
        )
    return WorkflowActionObserveContext(
        task_id=str(record["task_id"]),
        execution_id=str(record["execution_id"]),
        effect_id=str(effect["effect_id"]),
        claim_id=str(effect["claim_id"]),
        attempt_id=str(effect["attempt_id"]),
        journal_revision=int(record["revision"]),
        journal_record_sha256=str(record["record_sha256"]),
        index_revision=int(stored.index["revision"]),
        index_record_sha256=str(stored.index["record_sha256"]),
        containment_revision=int(containment["revision"]),
        containment_record_sha256=str(
            containment["record_sha256"]
        ),
        containment_phase=str(containment["phase"]),
        effect_kind=str(effect["kind"]),
        settlement=str(settlement),
        safe_inputs=_workflow_tx_copy.deepcopy(dict(safe_inputs)),
        required_lock_claims=stored.required_lock_claims,
        scopes=_workflow_tx_copy.deepcopy(dict(scopes)),
        catalog_contract_sha256=str(
            bindings["effect_plan_sha256"]
        ),
        runtime_binding_sha256=(
            str(effect["runtime_binding_sha256"])
            if effect.get("runtime_binding_sha256") is not None
            else None
        ),
        runtime_handle_sha256=(
            str(containment["runtime_handle_sha256"])
            if containment.get("runtime_handle_sha256")
            is not None
            else None
        ),
        protocol=_WORKFLOW_TX_OBSERVE_PROTOCOL,
    )


def _workflow_tx_claim_ready_impl(
    task_dir: str | object,
    execution_id: str,
    *,
    permit_issuer: _WorkflowTxCallable[
        [WorkflowActionDispatchContext], None
    ],
    authorization: WorkflowActionAuthorization,
    claim_id_factory: _WorkflowTxCallable[[str], str] | None = None,
    limit: int | None = None,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionClaimBatch:
    """Durably claim the current DAG frontier without invoking a dispatcher.

    Returned contexts are process-local first-claim permits. They are never
    reconstructed for an already claimed effect, including during recovery.
    The caller releases its short task/index lock before consuming them.
    """

    if (
        not isinstance(execution_id, str)
        or not execution_id
        or type(authorization) is not WorkflowActionAuthorization
        or (
            limit is not None
            and (
                isinstance(limit, bool)
                or not isinstance(limit, int)
                or limit <= 0
            )
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CLAIM_INVALID",
            "claim frontier requires exact execution and authorization",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    contexts: list[WorkflowActionDispatchContext] = []
    ordered_locks = None
    ordered_locks_entered = False
    try:
        preliminary = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        ordered_locks = _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        )
        ordered_locks.__enter__()
        ordered_locks_entered = True
        current = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        assert current.record is not None
        _workflow_tx_assert_journal_authorization(
            current.record, authorization
        )
        declared = [
            str(effect["effect_id"])
            for effect in current.record["effects"]
            if isinstance(effect, _WorkflowTxMapping)
            and effect.get("phase") == "PLANNED"
        ]
        for effect_id in declared:
            if limit is not None and len(contexts) >= limit:
                break
            current = store.read_promoted_context(
                execution_id, manager_secret=manager_secret
            )
            assert current.record is not None
            effect = _workflow_tx_effect(
                current.record, effect_id
            )
            if effect["phase"] != "PLANNED":
                continue
            claim_id = (
                claim_id_factory(effect_id)
                if claim_id_factory is not None
                else "claim-" + _workflow_tx_secrets.token_hex(16)
            )
            if not isinstance(claim_id, str) or not claim_id:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_CLAIM_INVALID",
                    "claim identity factory returned invalid text",
                    details={"effect_id": effect_id},
                )
            try:
                plan = store.claim_for_dispatch(
                    execution_id,
                    effect_id,
                    claim_id,
                    expected_index=cas_token(current.index),
                    expected_journal=cas_token(current.record),
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
            except ActionExecutionJournalError as exc:
                if exc.code in {
                    "ACTION_JOURNAL_EFFECT_DEPENDENCY_BLOCKED",
                    "ACTION_JOURNAL_EFFECT_PARALLEL_CONFLICT",
                }:
                    continue
                raise
            claimed = store.read_promoted_context(
                execution_id,
                expected_index=CASToken(
                    plan.index_revision,
                    plan.index_record_sha256,
                ),
                expected_journal=CASToken(
                    plan.journal_revision,
                    plan.journal_record_sha256,
                ),
                manager_secret=manager_secret,
            )
            assert claimed.record is not None
            containment = new_containment(
                claimed.record,
                effect_id,
                index=claimed.index,
                expected_index=cas_token(claimed.index),
                manager_secret=manager_secret,
            )
            store.persist_containment(
                containment,
                expected_index=cas_token(claimed.index),
                expected_journal=cas_token(claimed.record),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            dispatch_context = _workflow_tx_dispatch_context(
                plan,
                _workflow_tx_effect(claimed.record, effect_id),
                claimed.record,
            )
            permit_issuer(dispatch_context)
            contexts.append(dispatch_context)
        final = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        assert final.record is not None
        return WorkflowActionClaimBatch(
            execution_id=execution_id,
            contexts=tuple(contexts),
            journal=_workflow_tx_copy.deepcopy(final.record),
            index=_workflow_tx_copy.deepcopy(final.index),
        )
    finally:
        if ordered_locks_entered and ordered_locks is not None:
            ordered_locks.__exit__(None, None, None)
        manager_secret = None


def _workflow_tx_validate_runtime_launch(
    launch: object,
    context: WorkflowActionDispatchContext,
) -> WorkflowActionRuntimeLaunch:
    if type(launch) is not WorkflowActionRuntimeLaunch:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_LAUNCH_INVALID",
            "async adapter must return the exact suspended launch type",
        )
    binding = launch.binding
    plan = context.plan
    mismatches = sorted(
        field
        for field, expected in (
            ("task_id", plan.task_id),
            ("execution_id", plan.execution_id),
            ("effect_id", plan.effect_id),
            ("claim_id", plan.claim_id),
            ("attempt_id", plan.attempt_id),
        )
        if getattr(binding, field) != expected
    )
    scopes = context.scopes
    lease_ids = scopes.get("lease_ids")
    if (
        context.settlement != "asynchronous-handoff"
        or context.launch_protocol
        != _WORKFLOW_TX_RUNTIME_LAUNCH_PROTOCOL
        or context.effect_kind != "runtime-dispatch"
        or not isinstance(lease_ids, list)
        or binding.lease_id not in lease_ids
        or mismatches
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_LAUNCH_MISMATCH",
            "suspended runtime differs from the durable first claim",
            details={"fields": mismatches},
        )
    return launch


def _workflow_tx_quarantine_dispatch_uncertainty(
    task_path: _WorkflowTxPath,
    context: WorkflowActionDispatchContext,
    authorization: WorkflowActionAuthorization,
    *,
    manager_secret: str | bytes | None,
    failure_hook: _WorkflowTxCallable[[str], None] | None,
) -> None:
    store = ActionExecutionStore(task_path)
    preliminary = store.read_promoted_context(
        context.plan.execution_id,
        manager_secret=manager_secret,
    )
    with _workflow_tx_ordered_locks(
        task_path, preliminary.required_lock_claims
    ):
        current = store.read_promoted_context(
            context.plan.execution_id,
            manager_secret=manager_secret,
        )
        assert current.record is not None
        _workflow_tx_assert_journal_authorization(
            current.record, authorization
        )
        _workflow_tx_persist_uncertain_quarantine(
            store,
            current,
            effect_id=context.plan.effect_id,
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )


def _workflow_tx_dispatch_claimed_impl(
    task_dir: str | object,
    context: WorkflowActionDispatchContext,
    *,
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionDispatchContext,
            _WorkflowTxCallable[
                [WorkflowActionDispatchContext], object
            ],
        ],
        object,
    ],
    authorization: WorkflowActionAuthorization,
    dispatcher: _WorkflowTxCallable[
        [WorkflowActionDispatchContext],
        WorkflowActionEffectObservation | WorkflowActionRuntimeLaunch,
    ],
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionDispatchResult | WorkflowActionRuntimeLaunch:
    """Consume one process-local first-claim permit outside task/index locks.

    Synchronous adapters return an exact quiescence observation. Async
    adapters may only create a contained, suspended runtime handshake; the
    controller must persist its exact runtime binding before release.
    """

    if (
        type(context) is not WorkflowActionDispatchContext
        or type(authorization) is not WorkflowActionAuthorization
        or not callable(dispatcher)
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_DISPATCH_INVALID",
            "dispatch requires exact context, authorization, and adapter",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    invoked = False
    expected_observe_context: (
        WorkflowActionObserveContext | None
    ) = None
    try:
        preliminary = store.read_promoted_context(
            context.plan.execution_id,
            manager_secret=manager_secret,
        )
        with _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        ):
            current = store.read_promoted_context(
                context.plan.execution_id,
                expected_journal=CASToken(
                    context.plan.journal_revision,
                    context.plan.journal_record_sha256,
                ),
                manager_secret=manager_secret,
            )
            assert current.record is not None
            _workflow_tx_assert_journal_authorization(
                current.record, authorization
            )
            bindings = current.record.get("bindings")
            authoritative_state = (
                _read_task_state_structural_snapshot(
                    task_path / "state.json"
                )
            )
            if (
                not isinstance(bindings, _WorkflowTxMapping)
                or bindings.get("task_revision")
                != authoritative_state.get("revision")
                or bindings.get("pre_effect_state_sha256")
                != _sha256_contract(authoritative_state)
                or bindings.get("workflow_bundle_sha256")
                != (
                    authoritative_state.get("workflow_ref") or {}
                ).get("bundle_sha256")
            ):
                _workflow_tx_persist_uncertain_quarantine(
                    store,
                    current,
                    effect_id=context.plan.effect_id,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_PREIMAGE_DRIFT",
                    "authoritative task preimage changed before dispatch",
                    details={
                        "execution_id": (
                            context.plan.execution_id
                        ),
                        "effect_id": context.plan.effect_id,
                        "dispatcher_invocations": 0,
                    },
                )
            effect = _workflow_tx_effect(
                current.record, context.plan.effect_id
            )
            containment = store.read_containment(
                context.plan.execution_id,
                context.plan.effect_id,
            )
            if (
                effect["phase"] != "CLAIMED"
                or effect["claim_id"] != context.plan.claim_id
                or effect["attempt_id"] != context.plan.attempt_id
                or containment["phase"] != "SPAWN_PENDING"
                or containment["claim_id"] != context.plan.claim_id
                or containment["attempt_id"]
                != context.plan.attempt_id
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_DISPATCH_CLAIM_MISMATCH",
                    "dispatch context differs from durable claim/containment",
                )
            if context.settlement == "synchronous-quiescence":
                expected_observe_context = (
                    _workflow_tx_observe_context(
                        current, effect, containment
                    )
                )
        try:
            with _workflow_tx_scope_locks(
                task_path, context.plan.required_lock_claims
            ):
                def invoke_adapter(
                    active: WorkflowActionDispatchContext,
                ) -> object:
                    nonlocal invoked
                    invoked = True
                    return dispatcher(active)

                result = callback_invoker(
                    task_path, context, invoke_adapter
                )
                _workflow_tx_fail(failure_hook, "after-dispatch")
                if (
                    context.settlement
                    == "synchronous-quiescence"
                ):
                    observation = _workflow_tx_validate_observation(
                        result, context.plan
                    )
                    assert expected_observe_context is not None
                    return WorkflowActionDispatchResult(
                        observation=observation,
                        observe_context=expected_observe_context,
                    )
                return _workflow_tx_validate_runtime_launch(
                    result, context
                )
        except Exception:
            if invoked:
                _workflow_tx_quarantine_dispatch_uncertainty(
                    task_path,
                    context,
                    authorization,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
            raise
    finally:
        manager_secret = None


def _workflow_tx_build_public_dispatch_api(
    permit_issuer: _WorkflowTxCallable[
        [WorkflowActionDispatchContext], None
    ],
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionDispatchContext,
            _WorkflowTxCallable[
                [WorkflowActionDispatchContext], object
            ],
        ],
        object,
    ],
    active_verifier: _WorkflowTxCallable[
        [WorkflowActionDispatchContext], None
    ],
):
    def claim_ready(
        task_dir: str | object,
        execution_id: str,
        *,
        authorization: WorkflowActionAuthorization,
        claim_id_factory: (
            _WorkflowTxCallable[[str], str] | None
        ) = None,
        limit: int | None = None,
        failure_hook: (
            _WorkflowTxCallable[[str], None] | None
        ) = None,
    ) -> WorkflowActionClaimBatch:
        return _workflow_tx_claim_ready_impl(
            task_dir,
            execution_id,
            permit_issuer=permit_issuer,
            authorization=authorization,
            claim_id_factory=claim_id_factory,
            limit=limit,
            failure_hook=failure_hook,
        )

    def dispatch_claimed(
        task_dir: str | object,
        context: WorkflowActionDispatchContext,
        *,
        authorization: WorkflowActionAuthorization,
        dispatcher: _WorkflowTxCallable[
            [WorkflowActionDispatchContext],
            WorkflowActionEffectObservation
            | WorkflowActionRuntimeLaunch,
        ],
        failure_hook: (
            _WorkflowTxCallable[[str], None] | None
        ) = None,
    ) -> WorkflowActionDispatchResult | WorkflowActionRuntimeLaunch:
        return _workflow_tx_dispatch_claimed_impl(
            task_dir,
            context,
            callback_invoker=callback_invoker,
            authorization=authorization,
            dispatcher=dispatcher,
            failure_hook=failure_hook,
        )

    def verify_active(
        context: WorkflowActionDispatchContext,
    ) -> dict[str, object]:
        return _workflow_tx_active_dispatch_facts(
            context, active_verifier
        )

    claim_ready.__name__ = (
        "claim_ready_v4_workflow_action_effects"
    )
    dispatch_claimed.__name__ = (
        "dispatch_claimed_v4_workflow_action_effect"
    )
    verify_active.__name__ = (
        "verify_active_v4_workflow_action_dispatch_context"
    )
    return claim_ready, dispatch_claimed, verify_active


(
    claim_ready_v4_workflow_action_effects,
    dispatch_claimed_v4_workflow_action_effect,
    verify_active_v4_workflow_action_dispatch_context,
) = _workflow_tx_build_public_dispatch_api(
    _WORKFLOW_TX_ISSUE_DISPATCH_PERMIT,
    _WORKFLOW_TX_INVOKE_DISPATCH_CALLBACK,
    _WORKFLOW_TX_VERIFY_ACTIVE_DISPATCH,
)

del _WORKFLOW_TX_ISSUE_DISPATCH_PERMIT
del _WORKFLOW_TX_INVOKE_DISPATCH_CALLBACK
del _WORKFLOW_TX_VERIFY_ACTIVE_DISPATCH
del _workflow_tx_build_public_dispatch_api
del _workflow_tx_build_dispatch_callback_authority


(
    _WORKFLOW_TX_INVOKE_OBSERVE_CALLBACK,
    verify_active_v4_workflow_action_observe_context,
) = _workflow_tx_build_observe_callback_authority()

del _workflow_tx_build_observe_callback_authority


def verify_active_v4_workflow_action_dispatch(
    context: WorkflowActionDispatchContext,
) -> dict[str, object]:
    """Compatibility alias for the canonical active-context verifier."""

    return verify_active_v4_workflow_action_dispatch_context(context)


def _workflow_tx_validate_runtime_binding(
    journal: _WorkflowTxMapping[str, object],
    binding: WorkflowActionRuntimeBinding,
) -> dict[str, object]:
    effect = _workflow_tx_effect(journal, binding.effect_id)
    expected = {
        "task_id": journal.get("task_id"),
        "execution_id": journal.get("execution_id"),
        "effect_id": effect["effect_id"],
        "claim_id": effect["claim_id"],
        "attempt_id": effect["attempt_id"],
    }
    mismatches = sorted(
        field
        for field, value in expected.items()
        if getattr(binding, field) != value
    )
    scopes = effect["scopes"]
    assert isinstance(scopes, dict)
    if (
        mismatches
        or effect["kind"] != "runtime-dispatch"
        or effect["settlement"] != "asynchronous-handoff"
        or binding.lease_id not in scopes["lease_ids"]
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_MISMATCH",
            "runtime binding differs from the durable async claim",
            details={"fields": mismatches},
        )
    return effect


def bind_v4_workflow_action_runtime(
    task_dir: str | object,
    binding: WorkflowActionRuntimeBinding,
    *,
    authorization: WorkflowActionAuthorization,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionEffectStep:
    """Persist runtime identity after contained launch and before release."""

    if (
        type(binding) is not WorkflowActionRuntimeBinding
        or type(authorization) is not WorkflowActionAuthorization
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_INVALID",
            "runtime binding requires exact typed inputs",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    ordered_locks = None
    ordered_locks_entered = False
    try:
        preliminary = store.read_promoted_context(
            binding.execution_id, manager_secret=manager_secret
        )
        ordered_locks = _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        )
        ordered_locks.__enter__()
        ordered_locks_entered = True
        context = store.read_promoted_context(
            binding.execution_id, manager_secret=manager_secret
        )
        assert context.record is not None
        _workflow_tx_assert_journal_authorization(
            context.record, authorization
        )
        effect = _workflow_tx_validate_runtime_binding(
            context.record, binding
        )
        containment = store.read_containment(
            binding.execution_id, binding.effect_id
        )
        if containment["phase"] == "SPAWN_PENDING":
            runtime_bound = advance_containment(
                containment,
                "RUNTIME_BOUND",
                runtime_handle_sha256=(
                    binding.runtime_handle_sha256
                ),
            )
            persisted_containment = store.persist_containment(
                runtime_bound,
                expected_index=cas_token(context.index),
                expected_journal=cas_token(context.record),
                expected_containment=cas_token(containment),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted_containment.record is not None
            containment = persisted_containment.record
        elif (
            containment["phase"]
            not in {"RUNTIME_BOUND", "RELEASED", "HANDOFF_VERIFIED"}
            or containment["runtime_handle_sha256"]
            != binding.runtime_handle_sha256
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_MISMATCH",
                "containment has another runtime identity",
            )
        context = store.read_promoted_context(
            binding.execution_id, manager_secret=manager_secret
        )
        assert context.record is not None
        effect = _workflow_tx_effect(
            context.record, binding.effect_id
        )
        if effect["phase"] == "CLAIMED":
            running = advance_effect_phase(
                context.record,
                binding.effect_id,
                "RUNNING",
                manager_secret=manager_secret,
                containment_record_sha256=str(
                    containment["record_sha256"]
                ),
                runtime_binding_sha256=binding.binding_sha256,
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                running,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert context.record is not None
            _workflow_tx_fail(failure_hook, "after-running")
        else:
            effect = _workflow_tx_effect(
                context.record, binding.effect_id
            )
            if (
                effect["phase"]
                not in {"RUNNING", "HANDOFF_VERIFIED", "VERIFIED"}
                or effect["runtime_binding_sha256"]
                != binding.binding_sha256
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_MISMATCH",
                    "journal has another runtime binding",
                )
        return WorkflowActionEffectStep(
            status="RUNTIME_BOUND",
            execution_id=binding.execution_id,
            effect_id=binding.effect_id,
            journal=_workflow_tx_copy.deepcopy(context.record),
            index=_workflow_tx_copy.deepcopy(context.index),
            containment=_workflow_tx_copy.deepcopy(containment),
        )
    finally:
        if ordered_locks_entered and ordered_locks is not None:
            ordered_locks.__exit__(None, None, None)
        manager_secret = None


def _workflow_tx_validate_runtime_release_ack(
    value: object,
    context: WorkflowActionRuntimeReleaseContext,
) -> WorkflowActionRuntimeReleaseAck:
    if type(value) is not WorkflowActionRuntimeReleaseAck:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_ACK_INVALID",
            "runtime release adapter must return the exact acknowledgment type",
        )
    binding = context.binding
    expected = {
        "task_id": binding.task_id,
        "execution_id": binding.execution_id,
        "effect_id": binding.effect_id,
        "claim_id": binding.claim_id,
        "attempt_id": binding.attempt_id,
        "lease_id": binding.lease_id,
        "runtime_handle_sha256": binding.runtime_handle_sha256,
        "runtime_binding_sha256": binding.binding_sha256,
        "release_context_sha256": (
            context.release_context_sha256
        ),
        "protocol": context.protocol,
        "released": True,
    }
    mismatches = sorted(
        field
        for field, expected_value in expected.items()
        if getattr(value, field) != expected_value
    )
    if mismatches:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_ACK_MISMATCH",
            "runtime release acknowledgment differs from its durable target",
            details={"fields": mismatches},
        )
    return value


def _workflow_tx_release_runtime_impl(
    task_dir: str | object,
    binding: WorkflowActionRuntimeBinding,
    *,
    permit_issuer: _WorkflowTxCallable[
        [WorkflowActionRuntimeReleaseContext], None
    ],
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionRuntimeReleaseContext,
            _WorkflowTxCallable[
                [WorkflowActionRuntimeReleaseContext], object
            ],
        ],
        object,
    ],
    authorization: WorkflowActionAuthorization,
    release_adapter: _WorkflowTxCallable[
        [WorkflowActionRuntimeReleaseContext],
        WorkflowActionRuntimeReleaseAck,
    ],
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionEffectStep:
    """Persist then consume one exact target-bound runtime release permit."""

    if (
        type(binding) is not WorkflowActionRuntimeBinding
        or type(authorization) is not WorkflowActionAuthorization
        or not callable(release_adapter)
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_INVALID",
            "runtime release requires exact typed inputs and adapter",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    ordered_locks = None
    ordered_locks_entered = False
    release_context: WorkflowActionRuntimeReleaseContext | None = None
    durable_journal: dict[str, object] | None = None
    durable_index: dict[str, object] | None = None
    durable_containment: dict[str, object] | None = None
    try:
        preliminary = store.read_promoted_context(
            binding.execution_id, manager_secret=manager_secret
        )
        ordered_locks = _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        )
        ordered_locks.__enter__()
        ordered_locks_entered = True
        context = store.read_promoted_context(
            binding.execution_id, manager_secret=manager_secret
        )
        assert context.record is not None
        _workflow_tx_assert_journal_authorization(
            context.record, authorization
        )
        effect = _workflow_tx_validate_runtime_binding(
            context.record, binding
        )
        if (
            effect["phase"] not in {
                "RUNNING",
                "HANDOFF_VERIFIED",
                "VERIFIED",
            }
            or effect["runtime_binding_sha256"]
            != binding.binding_sha256
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_INVALID",
                "runtime must be durably bound before release",
            )
        containment = store.read_containment(
            binding.execution_id, binding.effect_id
        )
        if containment["phase"] != "RUNTIME_BOUND":
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_ALREADY_AUTHORIZED",
                "runtime release is not replayable after durable authorization",
            )
        released = advance_containment(
            containment, "RELEASED"
        )
        persisted = store.persist_containment(
            released,
            expected_index=cas_token(context.index),
            expected_journal=cas_token(context.record),
            expected_containment=cas_token(containment),
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        assert persisted.record is not None
        containment = persisted.record
        release_context = WorkflowActionRuntimeReleaseContext(
            binding=binding,
            containment_revision=int(containment["revision"]),
            containment_record_sha256=str(
                containment["record_sha256"]
            ),
            journal_revision=int(context.record["revision"]),
            journal_record_sha256=str(
                context.record["record_sha256"]
            ),
            index_revision=int(context.index["revision"]),
            index_record_sha256=str(
                context.index["record_sha256"]
            ),
            required_lock_claims=context.required_lock_claims,
            protocol=_WORKFLOW_TX_RUNTIME_RELEASE_PROTOCOL,
        )
        permit_issuer(release_context)
        durable_journal = _workflow_tx_copy.deepcopy(
            context.record
        )
        durable_index = _workflow_tx_copy.deepcopy(context.index)
        durable_containment = _workflow_tx_copy.deepcopy(
            containment
        )
        _workflow_tx_fail(
            failure_hook, "after-runtime-release-authorized"
        )
    finally:
        if ordered_locks_entered and ordered_locks is not None:
            ordered_locks.__exit__(None, None, None)
        manager_secret = None
    assert release_context is not None
    assert durable_journal is not None
    assert durable_index is not None
    assert durable_containment is not None
    try:
        with _workflow_tx_scope_locks(
            task_path, release_context.required_lock_claims
        ):
            raw_ack = callback_invoker(
                task_path, release_context, release_adapter
            )
        _workflow_tx_validate_runtime_release_ack(
            raw_ack, release_context
        )
        _workflow_tx_fail(failure_hook, "after-runtime-release")
    except Exception as exc:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RUNTIME_RELEASE_UNCERTAIN",
            "runtime release response is uncertain; recovery must "
            "authenticate and observe the durable runtime handle",
        ) from exc
    return WorkflowActionEffectStep(
        status="RELEASED",
        execution_id=binding.execution_id,
        effect_id=binding.effect_id,
        journal=durable_journal,
        index=durable_index,
        containment=durable_containment,
    )


def _workflow_tx_build_public_runtime_release_api(
    permit_issuer: _WorkflowTxCallable[
        [WorkflowActionRuntimeReleaseContext], None
    ],
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionRuntimeReleaseContext,
            _WorkflowTxCallable[
                [WorkflowActionRuntimeReleaseContext], object
            ],
        ],
        object,
    ],
    active_verifier: _WorkflowTxCallable[
        [WorkflowActionRuntimeReleaseContext], None
    ],
):
    def release_runtime(
        task_dir: str | object,
        binding: WorkflowActionRuntimeBinding,
        *,
        authorization: WorkflowActionAuthorization,
        release_adapter: _WorkflowTxCallable[
            [WorkflowActionRuntimeReleaseContext],
            WorkflowActionRuntimeReleaseAck,
        ],
        failure_hook: (
            _WorkflowTxCallable[[str], None] | None
        ) = None,
    ) -> WorkflowActionEffectStep:
        return _workflow_tx_release_runtime_impl(
            task_dir,
            binding,
            permit_issuer=permit_issuer,
            callback_invoker=callback_invoker,
            authorization=authorization,
            release_adapter=release_adapter,
            failure_hook=failure_hook,
        )

    def verify_active_release(
        context: WorkflowActionRuntimeReleaseContext,
    ) -> dict[str, object]:
        return _workflow_tx_active_runtime_release_facts(
            context, active_verifier
        )

    release_runtime.__name__ = (
        "release_v4_workflow_action_runtime"
    )
    verify_active_release.__name__ = (
        "verify_active_v4_workflow_action_runtime_release"
    )
    return release_runtime, verify_active_release


(
    release_v4_workflow_action_runtime,
    verify_active_v4_workflow_action_runtime_release,
) = _workflow_tx_build_public_runtime_release_api(
    _WORKFLOW_TX_ISSUE_RUNTIME_RELEASE_PERMIT,
    _WORKFLOW_TX_INVOKE_RUNTIME_RELEASE_CALLBACK,
    _WORKFLOW_TX_VERIFY_ACTIVE_RUNTIME_RELEASE,
)

del _WORKFLOW_TX_ISSUE_RUNTIME_RELEASE_PERMIT
del _WORKFLOW_TX_INVOKE_RUNTIME_RELEASE_CALLBACK
del _WORKFLOW_TX_VERIFY_ACTIVE_RUNTIME_RELEASE
del _workflow_tx_build_public_runtime_release_api
del _workflow_tx_build_runtime_release_callback_authority


def _workflow_tx_persist_observation_impl(
    task_dir: str | object,
    observation: WorkflowActionEffectObservation,
    *,
    authorization: WorkflowActionAuthorization,
    expected_context: WorkflowActionObserveContext | None = None,
    runtime_binding: WorkflowActionRuntimeBinding | None = None,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionEffectStep:
    """Persist an observation already authenticated by a live callback."""

    if (
        type(observation) is not WorkflowActionEffectObservation
        or type(authorization) is not WorkflowActionAuthorization
        or (
            expected_context is not None
            and type(expected_context)
            is not WorkflowActionObserveContext
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
            "effect observation requires exact authenticated inputs",
        )
    if expected_context is not None:
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
        ):
            if (
                getattr(observation, field_name)
                != getattr(expected_context, field_name)
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                    "observation differs from its authenticated context",
                    details={"fields": [field_name]},
                )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    ordered_locks = None
    ordered_locks_entered = False
    try:
        preliminary = store.read_promoted_context(
            observation.execution_id,
            manager_secret=manager_secret,
        )
        ordered_locks = _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        )
        ordered_locks.__enter__()
        ordered_locks_entered = True
        context = store.read_promoted_context(
            observation.execution_id,
            expected_journal=(
                CASToken(
                    expected_context.journal_revision,
                    expected_context.journal_record_sha256,
                )
                if expected_context is not None
                else None
            ),
            manager_secret=manager_secret,
        )
        assert context.record is not None
        _workflow_tx_assert_journal_authorization(
            context.record, authorization
        )
        effect = _workflow_tx_effect(
            context.record, observation.effect_id
        )
        mismatches = sorted(
            field
            for field, expected in (
                ("task_id", context.record["task_id"]),
                ("execution_id", context.record["execution_id"]),
                ("effect_id", effect["effect_id"]),
                ("claim_id", effect["claim_id"]),
                ("attempt_id", effect["attempt_id"]),
            )
            if getattr(observation, field) != expected
        )
        expected_settlement = (
            "HANDOFF_VERIFIED"
            if effect["settlement"] == "asynchronous-handoff"
            else "QUIESCED"
        )
        if mismatches or observation.settlement != expected_settlement:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                "observation differs from the durable effect claim",
                details={"fields": mismatches},
            )
        containment = store.read_containment(
            observation.execution_id, observation.effect_id
        )
        if expected_context is not None:
            if (
                containment.get("revision")
                != expected_context.containment_revision
                or containment.get("record_sha256")
                != expected_context.containment_record_sha256
                or containment.get("phase")
                != expected_context.containment_phase
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CAS_MISMATCH",
                    "containment changed during observe-only callback",
                )
        if expected_settlement == "HANDOFF_VERIFIED":
            if type(runtime_binding) is not WorkflowActionRuntimeBinding:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_REQUIRED",
                    "async observation requires its exact runtime binding",
                )
            _workflow_tx_validate_runtime_binding(
                context.record, runtime_binding
            )
            if (
                observation.runtime_handle_sha256
                != runtime_binding.runtime_handle_sha256
                or effect["runtime_binding_sha256"]
                != runtime_binding.binding_sha256
                or containment["phase"]
                not in {"RELEASED", "HANDOFF_VERIFIED"}
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                    "handoff observation differs from the released runtime",
                )
            if containment["phase"] == "RELEASED":
                handed_off = advance_containment(
                    containment,
                    "HANDOFF_VERIFIED",
                    receipt_sha256=observation.receipt_sha256,
                )
                persisted = store.persist_containment(
                    handed_off,
                    expected_index=cas_token(context.index),
                    expected_journal=cas_token(context.record),
                    expected_containment=cas_token(containment),
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert persisted.record is not None
                containment = persisted.record
            context = store.read_promoted_context(
                observation.execution_id,
                manager_secret=manager_secret,
            )
            assert context.record is not None
            effect = _workflow_tx_effect(
                context.record, observation.effect_id
            )
            if effect["phase"] == "RUNNING":
                handed_off_journal = advance_effect_phase(
                    context.record,
                    observation.effect_id,
                    "HANDOFF_VERIFIED",
                    manager_secret=manager_secret,
                    containment_record_sha256=str(
                        containment["record_sha256"]
                    ),
                    runtime_binding_sha256=(
                        runtime_binding.binding_sha256
                    ),
                    receipt_sha256=observation.receipt_sha256,
                )
                context = _workflow_tx_persist_update(
                    store,
                    context,
                    handed_off_journal,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert context.record is not None
                _workflow_tx_fail(
                    failure_hook, "after-observation"
                )
        else:
            if (
                runtime_binding is not None
                or observation.runtime_handle_sha256 is not None
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                    "synchronous observation cannot bind a live runtime",
                )
            if effect["phase"] == "CLAIMED":
                running = advance_effect_phase(
                    context.record,
                    observation.effect_id,
                    "RUNNING",
                    manager_secret=manager_secret,
                    containment_record_sha256=str(
                        containment["record_sha256"]
                    ),
                )
                context = _workflow_tx_persist_update(
                    store,
                    context,
                    running,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert context.record is not None
                _workflow_tx_fail(
                    failure_hook, "after-running"
                )
            if containment["phase"] == "SPAWN_PENDING":
                quiesced = advance_containment(
                    containment,
                    "QUIESCED",
                    receipt_sha256=observation.receipt_sha256,
                )
                persisted = store.persist_containment(
                    quiesced,
                    expected_index=cas_token(context.index),
                    expected_journal=cas_token(context.record),
                    expected_containment=cas_token(containment),
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert persisted.record is not None
                containment = persisted.record
            context = store.read_promoted_context(
                observation.execution_id,
                manager_secret=manager_secret,
            )
            assert context.record is not None
            effect = _workflow_tx_effect(
                context.record, observation.effect_id
            )
            if effect["phase"] == "RUNNING":
                quiesced_journal = advance_effect_phase(
                    context.record,
                    observation.effect_id,
                    "QUIESCED",
                    manager_secret=manager_secret,
                    containment_record_sha256=str(
                        containment["record_sha256"]
                    ),
                    receipt_sha256=observation.receipt_sha256,
                )
                context = _workflow_tx_persist_update(
                    store,
                    context,
                    quiesced_journal,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert context.record is not None
                _workflow_tx_fail(
                    failure_hook, "after-observation"
                )
            if containment["phase"] == "QUIESCED":
                closed = advance_containment(
                    containment,
                    "CLOSED",
                    receipt_sha256=observation.receipt_sha256,
                )
                persisted = store.persist_containment(
                    closed,
                    expected_index=cas_token(context.index),
                    expected_journal=cas_token(context.record),
                    expected_containment=cas_token(containment),
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert persisted.record is not None
                containment = persisted.record
        context = store.read_promoted_context(
            observation.execution_id,
            manager_secret=manager_secret,
        )
        assert context.record is not None
        effect = _workflow_tx_effect(
            context.record, observation.effect_id
        )
        if effect["phase"] in {"QUIESCED", "HANDOFF_VERIFIED"}:
            verified = advance_effect_phase(
                context.record,
                observation.effect_id,
                "VERIFIED",
                manager_secret=manager_secret,
                containment_record_sha256=str(
                    containment["record_sha256"]
                ),
                runtime_binding_sha256=(
                    runtime_binding.binding_sha256
                    if runtime_binding is not None
                    else None
                ),
                receipt_sha256=observation.receipt_sha256,
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                verified,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert context.record is not None
            _workflow_tx_fail(
                failure_hook, "after-effect-verified"
            )
        effect = _workflow_tx_effect(
            context.record, observation.effect_id
        )
        if (
            effect["phase"] != "VERIFIED"
            or effect["receipt_sha256"]
            != observation.receipt_sha256
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                "durable effect differs from the supplied observation",
            )
        effects = context.record["effects"]
        assert isinstance(effects, list)
        if (
            context.record["phase"] == "RUNNING"
            and all(
                item.get("phase") == "VERIFIED"
                for item in effects
                if isinstance(item, _WorkflowTxMapping)
            )
        ):
            settled = advance_global_settlement(
                context.record, manager_secret=manager_secret
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                settled,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert context.record is not None
        return WorkflowActionEffectStep(
            status="VERIFIED",
            execution_id=observation.execution_id,
            effect_id=observation.effect_id,
            journal=_workflow_tx_copy.deepcopy(context.record),
            index=_workflow_tx_copy.deepcopy(context.index),
            containment=_workflow_tx_copy.deepcopy(containment),
            observation=observation,
            observe_context_sha256=(
                expected_context.observe_context_sha256
                if expected_context is not None
                else None
            ),
        )
    finally:
        if ordered_locks_entered and ordered_locks is not None:
            ordered_locks.__exit__(None, None, None)
        manager_secret = None


def _workflow_tx_validate_observe_callback_result(
    result: object,
    context: WorkflowActionObserveContext,
) -> WorkflowActionEffectObservation:
    if type(result) is not WorkflowActionEffectObservation:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
            "observe-only callback must return the exact outer observation",
        )
    mismatches = sorted(
        field_name
        for field_name in (
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
        )
        if getattr(result, field_name)
        != getattr(context, field_name)
    )
    expected_settlement = (
        "HANDOFF_VERIFIED"
        if context.settlement == "asynchronous-handoff"
        else "QUIESCED"
    )
    if (
        result.settlement != expected_settlement
        or (
            expected_settlement == "QUIESCED"
            and result.runtime_handle_sha256 is not None
        )
        or (
            expected_settlement == "HANDOFF_VERIFIED"
            and result.runtime_handle_sha256
            != context.runtime_handle_sha256
        )
    ):
        mismatches.append("settlement")
    if mismatches:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
            "observe-only result differs from its durable context",
            details={"fields": sorted(set(mismatches))},
        )
    return result


def _workflow_tx_observe_effect_impl(
    task_dir: str | object,
    execution_id: str,
    effect_id: str,
    *,
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionObserveContext,
            _WorkflowTxCallable[
                [WorkflowActionObserveContext], object
            ],
        ],
        object,
    ],
    authorization: WorkflowActionAuthorization,
    observer: _WorkflowTxCallable[
        [WorkflowActionObserveContext],
        WorkflowActionEffectObservation,
    ],
    runtime_binding: WorkflowActionRuntimeBinding | None = None,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionEffectStep:
    """Run one authenticated read-only observer without dispatch authority."""

    if (
        not isinstance(execution_id, str)
        or not execution_id
        or not isinstance(effect_id, str)
        or not effect_id
        or type(authorization) is not WorkflowActionAuthorization
        or not callable(observer)
        or (
            runtime_binding is not None
            and type(runtime_binding)
            is not WorkflowActionRuntimeBinding
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_OBSERVER_INVALID",
            "observe-only execution requires exact identities and adapter",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    observe_context: WorkflowActionObserveContext | None = None
    durable_journal: dict[str, object] | None = None
    durable_index: dict[str, object] | None = None
    durable_containment: dict[str, object] | None = None
    quarantined = False
    verified_terminal = False
    try:
        preliminary = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        with _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        ):
            current = store.read_promoted_context(
                execution_id, manager_secret=manager_secret
            )
            assert current.record is not None
            _workflow_tx_assert_journal_authorization(
                current.record, authorization
            )
            effect = _workflow_tx_effect(
                current.record, effect_id
            )
            containment = store.read_containment(
                execution_id, effect_id
            )
            observe_context = _workflow_tx_observe_context(
                current, effect, containment
            )
            if observe_context.settlement == "asynchronous-handoff":
                if (
                    type(runtime_binding)
                    is not WorkflowActionRuntimeBinding
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_REQUIRED",
                        "async observe-only callback requires the exact runtime binding",
                    )
                _workflow_tx_validate_runtime_binding(
                    current.record, runtime_binding
                )
                if (
                    runtime_binding.binding_sha256
                    != observe_context.runtime_binding_sha256
                    or runtime_binding.runtime_handle_sha256
                    != observe_context.runtime_handle_sha256
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_MISMATCH",
                        "runtime binding differs from the observe-only context",
                    )
            elif runtime_binding is not None:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_MISMATCH",
                    "synchronous observe-only callback cannot bind a runtime",
                )
            quarantined = (
                current.record.get("phase") == "QUARANTINED"
                or effect.get("phase") == "QUARANTINED"
                or containment.get("phase") == "QUARANTINED"
            )
            if quarantined and not (
                current.record.get("phase") == "QUARANTINED"
                and effect.get("phase") == "QUARANTINED"
                and containment.get("phase")
                in {"QUARANTINED", "CLOSED"}
                and effect.get("containment_record_sha256")
                == containment.get("record_sha256")
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_MISMATCH",
                    "quarantine observation requires coherent durable containment",
                )
            verified_terminal = effect.get("phase") == "VERIFIED"
            if verified_terminal and containment.get("phase") not in {
                "CLOSED",
                "HANDOFF_VERIFIED",
            }:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CONTEXT_MISMATCH",
                    "verified observation requires terminal containment",
                )
            durable_journal = _workflow_tx_copy.deepcopy(
                current.record
            )
            durable_index = _workflow_tx_copy.deepcopy(
                current.index
            )
            durable_containment = _workflow_tx_copy.deepcopy(
                containment
            )
    finally:
        manager_secret = None
    assert observe_context is not None
    assert durable_journal is not None
    assert durable_index is not None
    assert durable_containment is not None
    with _workflow_tx_scope_locks(
        task_path, observe_context.required_lock_claims
    ):
        raw_result = callback_invoker(
            task_path, observe_context, observer
        )
    observation = _workflow_tx_validate_observe_callback_result(
        raw_result, observe_context
    )
    if quarantined or verified_terminal:
        manager_secret = _workflow_tx_reauthenticate(authorization)
        try:
            with _workflow_tx_ordered_locks(
                task_path, observe_context.required_lock_claims
            ):
                current = store.read_promoted_context(
                    execution_id,
                    expected_journal=CASToken(
                        observe_context.journal_revision,
                        observe_context.journal_record_sha256,
                    ),
                    manager_secret=manager_secret,
                )
                current_containment = store.read_containment(
                    execution_id, effect_id
                )
                if (
                    current_containment.get("revision")
                    != observe_context.containment_revision
                    or current_containment.get("record_sha256")
                    != observe_context.containment_record_sha256
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_OBSERVE_CAS_MISMATCH",
                        "quarantined target changed during observation",
                    )
                assert current.record is not None
                _workflow_tx_assert_journal_authorization(
                    current.record, authorization
                )
        finally:
            manager_secret = None
        return WorkflowActionEffectStep(
            status=(
                "OBSERVED_QUARANTINED"
                if quarantined
                else "OBSERVED_VERIFIED"
            ),
            execution_id=execution_id,
            effect_id=effect_id,
            journal=durable_journal,
            index=durable_index,
            containment=durable_containment,
            dispatcher_invocations=0,
            observation=observation,
            observe_context_sha256=(
                observe_context.observe_context_sha256
            ),
        )
    return _workflow_tx_persist_observation_impl(
        task_path,
        observation,
        authorization=authorization,
        expected_context=observe_context,
        runtime_binding=runtime_binding,
        failure_hook=failure_hook,
    )


def _workflow_tx_build_public_observe_api(
    callback_invoker: _WorkflowTxCallable[
        [
            _WorkflowTxPath,
            WorkflowActionObserveContext,
            _WorkflowTxCallable[
                [WorkflowActionObserveContext], object
            ],
        ],
        object,
    ],
):
    def observe_effect(
        task_dir: str | object,
        execution_id: str,
        effect_id: str,
        *,
        authorization: WorkflowActionAuthorization,
        observer: _WorkflowTxCallable[
            [WorkflowActionObserveContext],
            WorkflowActionEffectObservation,
        ],
        runtime_binding: (
            WorkflowActionRuntimeBinding | None
        ) = None,
        failure_hook: (
            _WorkflowTxCallable[[str], None] | None
        ) = None,
    ) -> WorkflowActionEffectStep:
        return _workflow_tx_observe_effect_impl(
            task_dir,
            execution_id,
            effect_id,
            callback_invoker=callback_invoker,
            authorization=authorization,
            observer=observer,
            runtime_binding=runtime_binding,
            failure_hook=failure_hook,
        )

    observe_effect.__name__ = "observe_v4_workflow_action_effect"
    return observe_effect


observe_v4_workflow_action_effect = (
    _workflow_tx_build_public_observe_api(
        _WORKFLOW_TX_INVOKE_OBSERVE_CALLBACK
    )
)

del _WORKFLOW_TX_INVOKE_OBSERVE_CALLBACK
del _workflow_tx_build_public_observe_api


def _workflow_tx_normalize_effect_bindings(
    effect_binding: WorkflowActionEffectBinding | None,
    effect_bindings: tuple[WorkflowActionEffectBinding, ...] | None,
) -> tuple[WorkflowActionEffectBinding, ...]:
    if effect_bindings is None:
        if effect_binding is None:
            return ()
        if type(effect_binding) is not WorkflowActionEffectBinding:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
                "effect binding must use the exact typed value",
            )
        return (effect_binding,)
    if (
        effect_binding is not None
        or not isinstance(effect_bindings, tuple)
        or not effect_bindings
        or any(
            type(item) is not WorkflowActionEffectBinding
            for item in effect_bindings
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
            "multi-effect bindings require one non-empty exact tuple",
        )
    ids = [item.effect_id for item in effect_bindings]
    if len(set(ids)) != len(ids):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
            "multi-effect bindings contain a duplicate identity",
        )
    return tuple(
        sorted(
            effect_bindings,
            key=lambda item: item.effect_id.encode("utf-8"),
        )
    )


def _workflow_tx_initial_lock_claims(
    state: _WorkflowTxMapping[str, object],
) -> tuple[tuple[str, str], ...]:
    """Claim only controller state locks while publishing the journal.

    Effect scopes are conflict-checked atomically by the execution index.
    Acquiring their runtime locks here would wait behind an already
    dispatched callback and prevent the index from rejecting an overlapping
    plan with zero dispatch.
    """

    task_id = state.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_STATE_INVALID",
            "task state has no exact identity",
        )
    return (("task", task_id),)


def _workflow_tx_index_entry_lock_claims(
    task_id: object,
    entry: _WorkflowTxMapping[str, object],
) -> tuple[tuple[str, str], ...]:
    scopes = entry.get("scopes")
    if not isinstance(task_id, str) or not isinstance(
        scopes, _WorkflowTxMapping
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_LOCK_CLAIMS_INVALID",
            "active index entry has no canonical lock scope",
        )
    claims: list[dict[str, str]] = [
        {"kind": "task", "identity": task_id}
    ]
    for kind, field in (
        ("repository", "repository_ids"),
        ("worktree", "worktree_ids"),
        ("lease", "lease_ids"),
    ):
        values = scopes.get(field)
        if not isinstance(values, list):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_LOCK_CLAIMS_INVALID",
                "active index scope is malformed",
                details={"field": field},
            )
        for identity in values:
            claims.append(
                {"kind": kind, "identity": str(identity)}
            )
    return tuple(
        (str(claim["kind"]), str(claim["identity"]))
        for claim in normalize_lock_claims(claims)
    )


def _workflow_tx_bindings_from_journal(
    journal: _WorkflowTxMapping[str, object],
    edge: _WorkflowTxMapping[str, object],
) -> tuple[WorkflowActionEffectBinding, ...]:
    catalog_by_id = {
        str(effect["id"]): effect
        for effect in _workflow_tx_dispatch_effects(edge)
    }
    effects = journal.get("effects")
    if not isinstance(effects, list):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
            "journal has no immutable effect graph",
        )
    result: list[WorkflowActionEffectBinding] = []
    for effect in effects:
        if not isinstance(effect, _WorkflowTxMapping):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_INVALID",
                "journal effect graph contains an invalid node",
            )
        effect_id = str(effect["effect_id"])
        catalog_effect = catalog_by_id.get(effect_id)
        if catalog_effect is None:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_EFFECT_MISMATCH",
                "latest catalog no longer declares a journal effect",
                details={"effect_id": effect_id},
            )
        scope_kinds = tuple(catalog_effect.get("scopes", ()))
        result.append(
            WorkflowActionEffectBinding(
                effect_id=effect_id,
                kind=str(effect["kind"]),
                scope_kinds=scope_kinds,
                scopes=_workflow_tx_copy.deepcopy(
                    dict(effect["scopes"])
                ),
                safe_inputs=_workflow_tx_copy.deepcopy(
                    dict(effect["safe_inputs"])
                ),
                attempt_id=str(effect["attempt_id"]),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: item.effect_id.encode("utf-8"),
        )
    )


def _workflow_tx_revalidation_facts(
    journal: _WorkflowTxMapping[str, object],
) -> dict[str, object]:
    bindings = journal.get("bindings")
    if not isinstance(bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            "journal has no immutable revalidation facts",
        )
    fields = (
        "workflow_bundle_sha256",
        "effect_plan_sha256",
        "semantic_operation_sha256",
        "scopes",
        "guard_projection_sha256",
        "evidence_sha256",
        "approval_sha256",
        "ownership_sha256",
        "registry_state_sha256",
        "postcondition_contract_sha256",
    )
    return {
        field: _workflow_tx_copy.deepcopy(bindings[field])
        for field in fields
    }


def _workflow_tx_fresh_evaluation(
    current: dict[str, object],
    journal: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
    authorization: WorkflowActionAuthorization,
    *,
    manager_secret: str | bytes | None,
    current_invocation_factory: (
        _WorkflowTxCallable[
            [dict[str, object]], WorkflowActionInvocation
        ]
        | None
    ),
) -> _WorkflowActionFreshEvaluation:
    durable_bindings = journal.get("bindings")
    if not isinstance(durable_bindings, _WorkflowTxMapping):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BINDING_INVALID",
            "journal has no immutable revision policy",
        )
    drifted = (
        current.get("revision")
        != durable_bindings.get("task_revision")
    )
    revision_policy = durable_bindings.get("revision_policy")
    if drifted and revision_policy == "exact-revision":
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EXACT_REVISION_DRIFT",
            "exclusive transaction cannot accept a changed task revision",
        )
    selected_invocation = invocation
    if drifted:
        if not callable(current_invocation_factory):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_FRESH_INVOCATION_REQUIRED",
                "scoped revision drift requires a latest-state invocation factory",
            )
        try:
            selected_invocation = current_invocation_factory(
                _workflow_tx_copy.deepcopy(current)
            )
        except WorkflowActionTransactionError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", None)
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_FRESH_INVOCATION_INVALID",
                "latest-state invocation factory failed closed",
                details={
                    "error_type": type(exc).__name__,
                    **(
                        {"error_code": error_code}
                        if isinstance(error_code, str)
                        else {}
                    ),
                },
            ) from exc
        if type(selected_invocation) is not WorkflowActionInvocation:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_FRESH_INVOCATION_INVALID",
                "latest-state invocation factory returned an invalid value",
            )
    edge_roles = _workflow_tx_edge_roles(
        current, selected_invocation
    )
    if (
        edge_roles.authorization_action_edge_id
        != durable_bindings.get("authorization_action_edge_id")
        or edge_roles.completion_edge_id
        != durable_bindings.get("completion_edge_id")
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BOUND_FACT_DRIFT",
            "latest catalog resolves different action edge roles",
        )
    evaluation_state, manager_intent_state = (
        _workflow_tx_evaluation_state(
            current,
            edge_roles.authorization_action_edge,
            authorization,
        )
    )
    preview = _workflow_tx_evaluate(
        evaluation_state,
        selected_invocation,
        preview=True,
        manager_intent_state=manager_intent_state,
        edge_roles=edge_roles,
    )
    reconstructed = _workflow_tx_bindings_from_journal(
        journal, edge_roles.authorization_action_edge
    )
    fresh_journal = compile_v4_workflow_action_journal(
        current,
        edge_roles.authorization_action_edge,
        preview,
        selected_invocation,
        authorization,
        execution_id=str(journal["execution_id"]),
        effect_bindings=reconstructed,
        manager_secret=manager_secret,
    )
    disposition = revision_revalidation_disposition(
        journal,
        int(current["revision"]),
        current_facts=_workflow_tx_revalidation_facts(
            fresh_journal
        ),
        manager_secret=manager_secret,
    )
    expected_disposition = (
        "REEVALUATE_CURRENT_STATE" if drifted else "CURRENT_REVISION"
    )
    if disposition != expected_disposition:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BOUND_FACT_DRIFT",
            "latest bundle, guard, evidence, authority, scope, or postcondition changed",
            details={"disposition": disposition},
        )
    fresh_bindings = fresh_journal["bindings"]
    assert isinstance(fresh_bindings, dict)
    stable_fields = {
        "workflow_id",
        "workflow_version",
        "workflow_bundle_sha256",
        "authorization_action_edge_id",
        "completion_edge_id",
        "action_edge_id",
        "handler_id",
        "effect_plan_sha256",
        "concurrency_class",
        "scopes",
        "guard_projection_sha256",
        "evidence_sha256",
        "approval_sha256",
        "ownership_sha256",
        "registry_state_sha256",
        "postcondition_contract_sha256",
        "candidate_after_sha256",
        "revision_policy",
        "semantic_operation_sha256",
    }
    if not drifted:
        stable_fields.update(
            {
                "pre_effect_state_sha256",
                "confirmation_sha256",
                "operation_sha256",
                "request_sha256",
                "verifier_before_sha256",
            }
        )
    mismatches = sorted(
        field
        for field in stable_fields
        if semantic_json_bytes(fresh_bindings[field])
        != semantic_json_bytes(durable_bindings[field])
    )
    if mismatches:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_BOUND_FACT_DRIFT",
            "fresh engine candidate differs from the durable scoped plan",
            details={"fields": mismatches},
        )
    return _WorkflowActionFreshEvaluation(
        state=_workflow_tx_copy.deepcopy(current),
        invocation=selected_invocation,
        edge_roles=edge_roles,
        evaluation_state=_workflow_tx_copy.deepcopy(
            dict(evaluation_state)
        ),
        manager_intent_state=(
            None
            if manager_intent_state is None
            else _workflow_tx_copy.deepcopy(
                dict(manager_intent_state)
            )
        ),
        preview=preview,
        bindings=reconstructed,
    )


def _workflow_tx_effect_receipt_sha256(
    journal: _WorkflowTxMapping[str, object],
    edge_roles: _WorkflowActionEdgeRoles,
) -> str:
    effects = journal.get("effects")
    if not isinstance(effects, list) or any(
        not isinstance(effect, _WorkflowTxMapping)
        or effect.get("phase") != "VERIFIED"
        for effect in effects
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_EFFECTS_UNVERIFIED",
            "final receipt requires every durable effect observation",
        )
    return semantic_sha256(
        _WORKFLOW_TX_EFFECT_RECEIPT_DOMAIN,
        {
            "edge_roles": edge_roles.binding(),
            "observations": [
                {
                    "effect_id": effect["effect_id"],
                    "claim_id": effect["claim_id"],
                    "attempt_id": effect["attempt_id"],
                    "settlement": effect["settled_as"],
                    "receipt_sha256": effect["receipt_sha256"],
                }
                for effect in sorted(
                    effects,
                    key=lambda item: str(
                        item["effect_id"]
                    ).encode("utf-8"),
                )
            ],
        },
    )


def _workflow_tx_quarantine_bound_drift(
    store: ActionExecutionStore,
    context: StoredActionExecution,
    error: WorkflowActionTransactionError,
    *,
    manager_secret: str | bytes | None,
    failure_hook: _WorkflowTxCallable[[str], None] | None,
) -> StoredActionExecution:
    assert context.record is not None
    details_sha256 = semantic_sha256(
        _WORKFLOW_TX_VERIFIER_DOMAIN,
        {
            "code": error.code,
            "details": _workflow_tx_public_mapping(
                error.details, "revalidation error"
            ),
        },
    )
    effects = context.record.get("effects")
    effect_ids = [
        str(effect["effect_id"])
        for effect in effects
        if isinstance(effect, _WorkflowTxMapping)
        and isinstance(effect.get("effect_id"), str)
    ] if isinstance(effects, list) else []
    receipt = context.record.get("receipt")
    receipt_sha256 = (
        str(receipt["receipt_sha256"])
        if isinstance(receipt, _WorkflowTxMapping)
        and isinstance(receipt.get("receipt_sha256"), str)
        else None
    )
    quarantined = quarantine_journal(
        context.record,
        reason_code="revision-revalidation-failed",
        details_sha256=details_sha256,
        effect_id=effect_ids[0] if len(effect_ids) == 1 else None,
        receipt_sha256=receipt_sha256,
        manager_secret=manager_secret,
    )
    return _workflow_tx_persist_update(
        store,
        context,
        quarantined,
        manager_secret=manager_secret,
        failure_hook=failure_hook,
    )


def _workflow_tx_finalize_verified(
    task_path: _WorkflowTxPath,
    execution_id: str,
    invocation: WorkflowActionInvocation,
    authorization: WorkflowActionAuthorization,
    *,
    current_invocation_factory: (
        _WorkflowTxCallable[
            [dict[str, object]], WorkflowActionInvocation
        ]
        | None
    ),
    runtime_bindings: _WorkflowTxMapping[
        str, WorkflowActionRuntimeBinding
    ]
    | None,
    dispatcher_invocations: int,
    failure_hook: _WorkflowTxCallable[[str], None] | None,
) -> WorkflowActionTransactionResult:
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    try:
        preliminary = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        with _workflow_tx_ordered_locks(
            task_path, preliminary.required_lock_claims
        ):
            context = store.read_promoted_context(
                execution_id, manager_secret=manager_secret
            )
            assert context.record is not None
            _workflow_tx_assert_journal_authorization(
                context.record, authorization
            )
            if context.record["phase"] not in {
                "QUIESCED",
                "HANDOFF_VERIFIED",
            }:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_EFFECTS_UNSETTLED",
                    "final commit requires a settled effect graph",
                )
            current = load_state(task_path / "state.json")
            try:
                fresh = _workflow_tx_fresh_evaluation(
                    current,
                    context.record,
                    invocation,
                    authorization,
                    manager_secret=manager_secret,
                    current_invocation_factory=(
                        current_invocation_factory
                    ),
                )
            except WorkflowActionTransactionError as exc:
                quarantined = _workflow_tx_quarantine_bound_drift(
                    store,
                    context,
                    exc,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert quarantined.record is not None
                return WorkflowActionTransactionResult(
                    status="QUARANTINE_REQUIRED",
                    execution_id=execution_id,
                    state=None,
                    journal=_workflow_tx_copy.deepcopy(
                        quarantined.record
                    ),
                    index=_workflow_tx_copy.deepcopy(
                        quarantined.index
                    ),
                    archive_path=None,
                    dispatcher_invocations=dispatcher_invocations,
                )
            effect_receipt_sha256 = (
                _workflow_tx_effect_receipt_sha256(
                    context.record, fresh.edge_roles
                )
            )
            receipt = build_v4_workflow_action_receipt(
                fresh.state,
                fresh.preview,
                task_path,
                execution_id=execution_id,
                effect_receipt_sha256=effect_receipt_sha256,
                authorization_action_edge_id=(
                    fresh.edge_roles.authorization_action_edge_id
                ),
                completion_edge_id=(
                    fresh.edge_roles.completion_edge_id
                ),
            )
            receipt_verified = verify_receipt_intent(
                context.record,
                receipt,
                manager_secret=manager_secret,
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                receipt_verified,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            _workflow_tx_fail(
                failure_hook, "after-receipt-verified"
            )
            assert context.record is not None
            receipt_context = WorkflowActionReceiptContext(
                index=context.index,
                journal=context.record,
                expected_index=cas_token(context.index),
                reauthenticate=authorization.reauthenticate,
                pre_effect_state=fresh.state,
            )
            evaluation = _workflow_tx_evaluate(
                fresh.evaluation_state,
                fresh.invocation,
                preview=False,
                receipt_context=receipt_context,
                manager_intent_state=fresh.manager_intent_state,
                edge_roles=fresh.edge_roles,
            )
            committed = _workflow_tx_commit_evaluation(
                fresh.state,
                evaluation,
                task_path,
                authorization,
                receipt_context,
            )
            _workflow_tx_fail(failure_hook, "after-task-commit")
            facts = _workflow_tx_authority_facts(
                task_path, context.record
            )
            if facts is None:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_COMMIT_UNOBSERVED",
                    "task commit returned without authoritative outbox bytes",
                )
            nonce_consumed = _workflow_tx_nonce_consumed(
                authorization, facts
            )
            final_journal = commit_journal(
                context.record,
                {
                    "task_commit_revision": facts.state["revision"],
                    "task_state_sha256": _sha256_contract(
                        facts.state
                    ),
                    "event_sha256": facts.event_sha256,
                    "outbox_sha256": facts.outbox_sha256,
                    "nonce_consumed": nonce_consumed,
                },
                manager_secret=manager_secret,
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                final_journal,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            _workflow_tx_fail(failure_hook, "after-journal-commit")
            assert context.record is not None
            async_effects = [
                effect
                for effect in context.record["effects"]
                if isinstance(effect, _WorkflowTxMapping)
                and effect.get("settled_as") == "HANDOFF_VERIFIED"
            ]
            promote_runtime_reservation = bool(async_effects)
            closure_index = context.index
            if async_effects:
                if (
                    len(async_effects) != 1
                    or not isinstance(runtime_bindings, _WorkflowTxMapping)
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_REQUIRED",
                        "handoff closure requires one exact runtime binding",
                    )
                effect = async_effects[0]
                binding = runtime_bindings.get(
                    str(effect["effect_id"])
                )
                if type(binding) is not WorkflowActionRuntimeBinding:
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_RUNTIME_BINDING_REQUIRED",
                        "handoff closure lost its exact runtime binding",
                    )
                _workflow_tx_validate_runtime_binding(
                    context.record, binding
                )
                containment = store.read_containment(
                    execution_id, binding.effect_id
                )
                reservation = new_runtime_reservation(
                    context.record,
                    binding.effect_id,
                    containment,
                    lease_id=binding.lease_id,
                    runtime_handle_sha256=(
                        binding.runtime_handle_sha256
                    ),
                    stop_action_id=binding.stop_action_id,
                    reconcile_action_id=binding.reconcile_action_id,
                    manager_secret=manager_secret,
                )
                stored_reservation = (
                    store.persist_runtime_reservation(
                        reservation,
                        expected_index=cas_token(context.index),
                        expected_journal=cas_token(context.record),
                        manager_secret=manager_secret,
                        failure_hook=failure_hook,
                    )
                )
                closure_index = stored_reservation.index
            closure = store.archive_and_close(
                execution_id,
                expected_index=cas_token(closure_index),
                expected_journal=cas_token(context.record),
                authoritative_event_sha256=facts.event_sha256,
                promote_runtime_reservation=(
                    promote_runtime_reservation
                ),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            _workflow_tx_fail(failure_hook, "after-archive")
            return WorkflowActionTransactionResult(
                status="COMMITTED",
                execution_id=execution_id,
                state=_workflow_tx_copy.deepcopy(committed),
                journal=_workflow_tx_copy.deepcopy(context.record),
                index=_workflow_tx_copy.deepcopy(closure.index),
                archive_path=closure.archive_path,
                dispatcher_invocations=dispatcher_invocations,
            )
    finally:
        manager_secret = None


def preview_v4_workflow_action_transaction(
    state: _WorkflowTxMapping[str, object],
    invocation: WorkflowActionInvocation,
    *,
    authorization: WorkflowActionAuthorization | None = None,
    task_dir: str | object | None = None,
) -> TransitionEvaluation:
    """Preview the exact edge roles used by execution without writing."""

    if type(invocation) is not WorkflowActionInvocation:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
            "transaction preview requires the exact invocation type",
        )

    def evaluate(
        current: _WorkflowTxMapping[str, object],
    ) -> TransitionEvaluation:
        edge_roles = _workflow_tx_edge_roles(current, invocation)
        evaluation_state, manager_intent_state = (
            _workflow_tx_evaluation_state(
                current,
                edge_roles.authorization_action_edge,
                authorization,
            )
        )
        return _workflow_tx_evaluate(
            evaluation_state,
            invocation,
            preview=True,
            manager_intent_state=manager_intent_state,
            edge_roles=edge_roles,
        )

    if task_dir is None:
        return evaluate(state)
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    _workflow_tx_assert_clean_transaction_entry(task_path)
    task_id = state.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
            "transaction preview requires a task identity",
        )
    with _workflow_tx_ordered_locks(
        task_path,
        (
            ("task", task_id),
            ("registry", "workspace-registry"),
        ),
    ):
        authoritative = load_state(task_path / "state.json")
        if _sha256_contract(authoritative) != _sha256_contract(
            state
        ):
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_STALE_STATE",
                "supplied task state is not the current authoritative snapshot",
            )
        return evaluate(authoritative)


def _execute_v4_workflow_action_transaction_core(
    state: dict[str, object],
    task_dir: str | object,
    invocation: WorkflowActionInvocation,
    *,
    authorization: WorkflowActionAuthorization | None = None,
    effect_binding: WorkflowActionEffectBinding | None = None,
    effect_bindings: tuple[WorkflowActionEffectBinding, ...] | None = None,
    execution_id: str | None = None,
    dispatcher: (
        _WorkflowTxCallable[
            [WorkflowActionDispatchContext],
            WorkflowActionEffectObservation
            | WorkflowActionRuntimeLaunch,
        ]
        | None
    ) = None,
    observer: (
        _WorkflowTxCallable[
            [WorkflowActionObserveContext],
            WorkflowActionEffectObservation,
        ]
        | None
    ) = None,
    current_invocation_factory: (
        _WorkflowTxCallable[
            [dict[str, object]], WorkflowActionInvocation
        ]
        | None
    ) = None,
    target_execution_id: str | None = None,
    control_action_id: str | None = None,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionTransactionResult:
    """Run the v4 Action Transaction with a short-lock effect boundary."""

    if type(invocation) is not WorkflowActionInvocation:
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_REQUEST_INVALID",
            "transaction requires the exact invocation type",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    _workflow_tx_assert_clean_transaction_entry(task_path)
    supplied_bindings = _workflow_tx_normalize_effect_bindings(
        effect_binding, effect_bindings
    )
    if (
        (target_execution_id is None)
        != (control_action_id is None)
        or (
            target_execution_id is not None
            and (
                not target_execution_id
                or not isinstance(control_action_id, str)
                or not control_action_id
            )
        )
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_CONTROL_INVALID",
            "target control requires exact target execution and action identities",
        )
    initial_claims = _workflow_tx_initial_lock_claims(
        state
    )
    manager_secret: str | bytes | None = None
    store = ActionExecutionStore(task_path)
    try:
        with _workflow_tx_ordered_locks(
            task_path, initial_claims
        ):
            authoritative_before = load_state(
                task_path / "state.json"
            )
            if (
                _sha256_contract(authoritative_before)
                != _sha256_contract(state)
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_STALE_STATE",
                    "supplied task state is not the current authoritative snapshot",
                )
            edge_roles = _workflow_tx_edge_roles(
                authoritative_before, invocation
            )
            edge = edge_roles.authorization_action_edge
            catalog_effects = _workflow_tx_dispatch_effects(edge)
            evaluation_state, manager_intent_state = (
                _workflow_tx_evaluation_state(
                    authoritative_before, edge, authorization
                )
            )
            preview = _workflow_tx_evaluate(
                evaluation_state,
                invocation,
                preview=True,
                manager_intent_state=manager_intent_state,
                edge_roles=edge_roles,
            )
            if not catalog_effects:
                if (
                    supplied_bindings
                    or execution_id is not None
                    or dispatcher is not None
                    or observer is not None
                    or current_invocation_factory is not None
                    or target_execution_id is not None
                    or control_action_id is not None
                ):
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_JOURNAL_FORBIDDEN",
                        "effect-free action cannot carry execution journal inputs",
                    )
                evaluation = _workflow_tx_evaluate(
                    evaluation_state,
                    invocation,
                    preview=False,
                    manager_intent_state=manager_intent_state,
                    edge_roles=edge_roles,
                )
                committed = commit_v4_workflow_action(
                    authoritative_before, evaluation, task_path
                )
                return WorkflowActionTransactionResult(
                    status="COMMITTED_EFFECT_FREE",
                    execution_id=None,
                    state=committed,
                    journal=None,
                    index=None,
                    archive_path=None,
                    dispatcher_invocations=0,
                )
            if (
                type(authorization)
                is not WorkflowActionAuthorization
                or not supplied_bindings
                or not isinstance(execution_id, str)
                or not execution_id
                or not callable(dispatcher)
                or (
                    observer is not None
                    and not callable(observer)
                )
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_INPUT_REQUIRED",
                    "side-effect action requires authorization, exact effect "
                    "bindings, execution identity, and dispatcher",
                )
            if (
                invocation.confirm_intent
                != preview.intent.get("intent_id")
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_CONFIRMATION_MISMATCH",
                    "side-effect transaction must bind the current preview intent",
                )
            manager_secret = _workflow_tx_reauthenticate(
                authorization
            )
            _workflow_tx_fail(failure_hook, "before-prepare")
            initialized = store.initialize_index(
                str(authoritative_before["task_id"]),
                failure_hook=failure_hook,
            )
            journal = compile_v4_workflow_action_journal(
                authoritative_before,
                edge,
                preview,
                invocation,
                authorization,
                execution_id=execution_id,
                effect_bindings=supplied_bindings,
                manager_secret=manager_secret,
            )
            prepared = store.persist_initial(
                journal,
                expected_index=cas_token(initialized.index),
                entry_kind=(
                    "control"
                    if target_execution_id is not None
                    else "ordinary"
                ),
                target_execution_id=target_execution_id,
                control_action_id=control_action_id,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            del prepared
            _workflow_tx_fail(failure_hook, "after-prepare")
    finally:
        manager_secret = None

    assert isinstance(authorization, WorkflowActionAuthorization)
    assert isinstance(execution_id, str)
    assert callable(dispatcher)
    dispatcher_invocations = 0
    runtime_bindings: dict[
        str, WorkflowActionRuntimeBinding
    ] = {}
    while True:
        batch = claim_ready_v4_workflow_action_effects(
            task_path,
            execution_id,
            authorization=authorization,
            limit=1,
            failure_hook=failure_hook,
        )
        if batch.contexts:
            _workflow_tx_fail(failure_hook, "after-claim")
            _workflow_tx_fail(failure_hook, "after-containment")
            for context in batch.contexts:
                dispatched = (
                    dispatch_claimed_v4_workflow_action_effect(
                        task_path,
                        context,
                        authorization=authorization,
                        dispatcher=dispatcher,
                        failure_hook=failure_hook,
                    )
                )
                dispatcher_invocations += 1
                if type(dispatched) is WorkflowActionRuntimeLaunch:
                    bound = bind_v4_workflow_action_runtime(
                        task_path,
                        dispatched.binding,
                        authorization=authorization,
                        failure_hook=failure_hook,
                    )
                    runtime_bindings[
                        dispatched.binding.effect_id
                    ] = dispatched.binding
                    return WorkflowActionTransactionResult(
                        status="RUNTIME_BOUND_AWAITING_RELEASE",
                        execution_id=execution_id,
                        state=None,
                        journal=_workflow_tx_copy.deepcopy(
                            bound.journal
                        ),
                        index=_workflow_tx_copy.deepcopy(bound.index),
                        archive_path=None,
                        dispatcher_invocations=dispatcher_invocations,
                    )
                if type(dispatched) is not WorkflowActionDispatchResult:
                    raise _workflow_tx_error(
                        "WORKFLOW_ACTION_TRANSACTION_OBSERVATION_INVALID",
                        "synchronous dispatch returned no authenticated observation",
                    )
                if observer is None:
                    _workflow_tx_persist_observation_impl(
                        task_path,
                        dispatched.observation,
                        authorization=authorization,
                        expected_context=dispatched.observe_context,
                        failure_hook=failure_hook,
                    )
                else:
                    observe_v4_workflow_action_effect(
                        task_path,
                        execution_id,
                        context.plan.effect_id,
                        authorization=authorization,
                        observer=observer,
                        failure_hook=failure_hook,
                    )
            continue
        if batch.journal["phase"] in {
            "QUIESCED",
            "HANDOFF_VERIFIED",
        }:
            return _workflow_tx_finalize_verified(
                task_path,
                execution_id,
                invocation,
                authorization,
                current_invocation_factory=(
                    current_invocation_factory
                ),
                runtime_bindings=runtime_bindings,
                dispatcher_invocations=dispatcher_invocations,
                failure_hook=failure_hook,
            )
        return WorkflowActionTransactionResult(
            status="AWAITING_EFFECT_OBSERVATION",
            execution_id=execution_id,
            state=None,
            journal=_workflow_tx_copy.deepcopy(batch.journal),
            index=_workflow_tx_copy.deepcopy(batch.index),
            archive_path=None,
            dispatcher_invocations=dispatcher_invocations,
        )


def _workflow_tx_persist_uncertain_quarantine(
    store: ActionExecutionStore,
    context: StoredActionExecution,
    *,
    effect_id: str | None = None,
    manager_secret: str | bytes | None,
    failure_hook: _WorkflowTxCallable[[str], None] | None,
) -> StoredActionExecution:
    """Turn a claimed uncertain effect into durable fail-closed truth."""

    assert context.record is not None
    if context.record["phase"] == "QUARANTINED":
        return context
    effects = context.record.get("effects")
    uncertain = next(
        (
            effect
            for effect in effects
            if isinstance(effect, _WorkflowTxMapping)
            and (
                effect_id is None
                or effect.get("effect_id") == effect_id
            )
            and effect.get("phase")
            in {
                "CLAIMED",
                "RUNNING",
                "QUIESCED",
                "HANDOFF_VERIFIED",
            }
        ),
        None,
    ) if isinstance(effects, list) else None
    if uncertain is None:
        receipt_set_sha256 = semantic_sha256(
            _WORKFLOW_TX_EFFECT_RECEIPT_DOMAIN,
            {
                "execution_id": context.record["execution_id"],
                "effects": [
                    {
                        "effect_id": effect["effect_id"],
                        "receipt_sha256": effect[
                            "receipt_sha256"
                        ],
                    }
                    for effect in effects
                    if isinstance(effect, _WorkflowTxMapping)
                ],
            },
        )
        receipt = context.record.get("receipt")
        action_receipt_sha256 = (
            str(receipt["receipt_sha256"])
            if isinstance(receipt, _WorkflowTxMapping)
            and isinstance(receipt.get("receipt_sha256"), str)
            else receipt_set_sha256
        )
        verified_effect_ids = [
            str(effect["effect_id"])
            for effect in effects
            if isinstance(effect, _WorkflowTxMapping)
            and effect.get("phase") == "VERIFIED"
            and isinstance(effect.get("effect_id"), str)
        ]
        selected_effect_id = (
            effect_id
            if effect_id in verified_effect_ids
            else (
                verified_effect_ids[0]
                if len(verified_effect_ids) == 1
                else None
            )
        )
        quarantined = quarantine_journal(
            context.record,
            reason_code="recovery-commit-intent-missing",
            details_sha256=receipt_set_sha256,
            effect_id=selected_effect_id,
            receipt_sha256=action_receipt_sha256,
            manager_secret=manager_secret,
        )
        return _workflow_tx_persist_update(
            store,
            context,
            quarantined,
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
    effect_id = str(uncertain["effect_id"])
    containment_digest = uncertain.get(
        "containment_record_sha256"
    )
    try:
        containment = store.read_containment(
            str(context.record["execution_id"]), effect_id
        )
    except Exception:
        containment = None
    if isinstance(containment, dict):
        containment_phase = containment.get("phase")
        if (
            uncertain.get("settlement")
            == "synchronous-quiescence"
            and containment_phase
            in {"SPAWN_PENDING", "RELEASED", "QUIESCED"}
        ):
            if containment_phase != "QUIESCED":
                quiescence_sha256 = semantic_sha256(
                    _WORKFLOW_TX_VERIFIER_DOMAIN,
                    {
                        "execution_id": context.record[
                            "execution_id"
                        ],
                        "effect_id": effect_id,
                        "claim_id": uncertain["claim_id"],
                        "attempt_id": uncertain["attempt_id"],
                        "observation": (
                            "recovery-acquired-effect-locks"
                        ),
                    },
                )
                quiesced_containment = advance_containment(
                    containment,
                    "QUIESCED",
                    receipt_sha256=quiescence_sha256,
                )
                persisted_containment = (
                    store.persist_containment(
                        quiesced_containment,
                        expected_index=cas_token(context.index),
                        expected_journal=cas_token(context.record),
                        expected_containment=cas_token(containment),
                        manager_secret=manager_secret,
                        failure_hook=failure_hook,
                    )
                )
                assert persisted_containment.record is not None
                containment = persisted_containment.record
            closed_containment = advance_containment(
                containment, "CLOSED"
            )
            persisted_containment = store.persist_containment(
                closed_containment,
                expected_index=cas_token(context.index),
                expected_journal=cas_token(context.record),
                expected_containment=cas_token(containment),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted_containment.record is not None
            containment_digest = persisted_containment.record[
                "record_sha256"
            ]
        elif containment_phase not in {
            "CLOSED",
            "QUARANTINED",
        }:
            quarantined_containment = advance_containment(
                containment, "QUARANTINED"
            )
            persisted_containment = store.persist_containment(
                quarantined_containment,
                expected_index=cas_token(context.index),
                expected_journal=cas_token(context.record),
                expected_containment=cas_token(containment),
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert persisted_containment.record is not None
            containment_digest = persisted_containment.record[
                "record_sha256"
            ]
    quarantined = advance_effect_phase(
        context.record,
        effect_id,
        "QUARANTINED",
        manager_secret=manager_secret,
        containment_record_sha256=(
            str(containment_digest)
            if containment_digest is not None
            else None
        ),
        receipt_sha256=(
            str(uncertain["receipt_sha256"])
            if uncertain.get("receipt_sha256") is not None
            else None
        ),
    )
    return _workflow_tx_persist_update(
        store,
        context,
        quarantined,
        manager_secret=manager_secret,
        failure_hook=failure_hook,
    )


def _workflow_tx_authenticated_live_runtime(
    store: ActionExecutionStore,
    journal: _WorkflowTxMapping[str, object],
    runtime_bindings: _WorkflowTxMapping[
        str, WorkflowActionRuntimeBinding
    ]
    | None,
    authenticator: (
        _WorkflowTxCallable[
            [
                _WorkflowTxMapping[str, object],
                _WorkflowTxMapping[str, object],
                WorkflowActionRuntimeBinding,
            ],
            bool,
        ]
        | None
    ),
) -> WorkflowActionRuntimeBinding | None:
    """Authenticate only a previously persisted exact runtime handle."""

    if not isinstance(runtime_bindings, _WorkflowTxMapping) or not callable(
        authenticator
    ):
        return None
    effects = journal.get("effects")
    if not isinstance(effects, list):
        return None
    for effect in effects:
        if (
            not isinstance(effect, _WorkflowTxMapping)
            or effect.get("kind") != "runtime-dispatch"
            or effect.get("settlement")
            != "asynchronous-handoff"
            or effect.get("phase")
            not in {"RUNNING", "HANDOFF_VERIFIED"}
            or effect.get("runtime_binding_sha256") is None
        ):
            continue
        binding = runtime_bindings.get(str(effect["effect_id"]))
        if type(binding) is not WorkflowActionRuntimeBinding:
            continue
        try:
            _workflow_tx_validate_runtime_binding(
                journal, binding
            )
            containment = store.read_containment(
                str(journal["execution_id"]),
                binding.effect_id,
            )
            if (
                containment["phase"]
                not in {
                    "RUNTIME_BOUND",
                    "RELEASED",
                    "HANDOFF_VERIFIED",
                }
                or containment["runtime_handle_sha256"]
                != binding.runtime_handle_sha256
                or authenticator(
                    _workflow_tx_copy.deepcopy(dict(journal)),
                    _workflow_tx_copy.deepcopy(
                        dict(containment)
                    ),
                    binding,
                )
                is not True
            ):
                continue
        except Exception:
            continue
        return binding
    return None


def _recover_v4_workflow_action_transaction_core(
    task_dir: str | object,
    execution_id: str,
    *,
    authorization: WorkflowActionAuthorization,
    invocation: WorkflowActionInvocation | None = None,
    current_invocation_factory: (
        _WorkflowTxCallable[
            [dict[str, object]], WorkflowActionInvocation
        ]
        | None
    ) = None,
    runtime_bindings: _WorkflowTxMapping[
        str, WorkflowActionRuntimeBinding
    ]
    | None = None,
    live_runtime_authenticator: (
        _WorkflowTxCallable[
            [
                _WorkflowTxMapping[str, object],
                _WorkflowTxMapping[str, object],
                WorkflowActionRuntimeBinding,
            ],
            bool,
        ]
        | None
    ) = None,
    failure_hook: _WorkflowTxCallable[[str], None] | None = None,
) -> WorkflowActionTransactionResult:
    """Recover only from promoted journal context and task/outbox authority.

    This entry point deliberately has no dispatcher argument. A claimed effect
    can therefore never be redispatched during restart recovery. When a
    complete verified receipt exists but the task commit did not return, the
    caller may supply the original typed invocation; its complete immutable
    binding is revalidated before the task/outbox commit is retried.
    """

    if (
        not isinstance(execution_id, str)
        or not execution_id
        or type(authorization) is not WorkflowActionAuthorization
    ):
        raise _workflow_tx_error(
            "WORKFLOW_ACTION_TRANSACTION_RECOVERY_INVALID",
            "recovery requires execution identity and exact authorization",
        )
    task_path = _WorkflowTxPath(task_dir).resolve(strict=True)
    manager_secret = _workflow_tx_reauthenticate(authorization)
    store = ActionExecutionStore(task_path)
    ordered_locks = None
    ordered_locks_entered = False
    try:
        index = store.read_index()
        entries = index.get("entries")
        entry = next(
            (
                candidate
                for candidate in entries
                if isinstance(candidate, dict)
                and candidate.get("execution_id") == execution_id
            ),
            None,
        ) if isinstance(entries, list) else None
        if entry is None:
            try:
                archived = store.read_archive_journal(
                    execution_id, manager_secret=manager_secret
                )
            except Exception as exc:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_RECOVERY_MISSING",
                    "execution is neither active nor durably archived",
                ) from exc
            return WorkflowActionTransactionResult(
                status="ALREADY_CLOSED",
                execution_id=execution_id,
                state=None,
                journal=archived,
                index=index,
                archive_path=str(
                    task_path
                    / action_execution_archive_path(execution_id)
                ),
                dispatcher_invocations=0,
            )
        ordered_locks = _workflow_tx_ordered_locks(
            task_path,
            _workflow_tx_index_entry_lock_claims(
                index.get("task_id"), entry
            ),
        )
        ordered_locks.__enter__()
        ordered_locks_entered = True
        index = store.read_index()
        entries = index.get("entries")
        entry = next(
            (
                candidate
                for candidate in entries
                if isinstance(candidate, dict)
                and candidate.get("execution_id")
                == execution_id
            ),
            None,
        ) if isinstance(entries, list) else None
        if entry is None:
            raise _workflow_tx_error(
                "WORKFLOW_ACTION_TRANSACTION_RECOVERY_CONFLICT",
                "active execution changed while recovery acquired locks",
            )
        if entry.get("pending_record_sha256") is not None:
            recovered = store.recover_pending(
                execution_id,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            if recovered.status != "PROMOTED":
                return WorkflowActionTransactionResult(
                    status=recovered.status,
                    execution_id=execution_id,
                    state=None,
                    journal=recovered.record,
                    index=recovered.index,
                    archive_path=None,
                    dispatcher_invocations=0,
                )
        context = store.read_promoted_context(
            execution_id, manager_secret=manager_secret
        )
        assert context.record is not None
        phase = str(context.record["phase"])
        if phase == "PREPARED":
            return WorkflowActionTransactionResult(
                status="UNSTARTED",
                execution_id=execution_id,
                state=None,
                journal=context.record,
                index=context.index,
                archive_path=None,
                dispatcher_invocations=0,
            )
        if phase not in {"RECEIPT_VERIFIED", "COMMITTED"}:
            live_binding = _workflow_tx_authenticated_live_runtime(
                store,
                context.record,
                runtime_bindings,
                live_runtime_authenticator,
            )
            if live_binding is not None:
                return WorkflowActionTransactionResult(
                    status="REATTACH_OBSERVE_ONLY",
                    execution_id=execution_id,
                    state=None,
                    journal=context.record,
                    index=context.index,
                    archive_path=None,
                    dispatcher_invocations=0,
                )
            context = _workflow_tx_persist_uncertain_quarantine(
                store,
                context,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert context.record is not None
            return WorkflowActionTransactionResult(
                status="QUARANTINE_REQUIRED",
                execution_id=execution_id,
                state=None,
                journal=context.record,
                index=context.index,
                archive_path=None,
                dispatcher_invocations=0,
            )
        facts = _workflow_tx_authority_facts(
            task_path, context.record
        )
        if facts is None:
            if phase != "RECEIPT_VERIFIED" or invocation is None:
                return WorkflowActionTransactionResult(
                    status="AWAITING_TASK_COMMIT",
                    execution_id=execution_id,
                    state=None,
                    journal=context.record,
                    index=context.index,
                    archive_path=None,
                    dispatcher_invocations=0,
                )
            current = load_state(task_path / "state.json")
            try:
                fresh = _workflow_tx_fresh_evaluation(
                    current,
                    context.record,
                    invocation,
                    authorization,
                    manager_secret=manager_secret,
                    current_invocation_factory=(
                        current_invocation_factory
                    ),
                )
            except WorkflowActionTransactionError as exc:
                context = _workflow_tx_quarantine_bound_drift(
                    store,
                    context,
                    exc,
                    manager_secret=manager_secret,
                    failure_hook=failure_hook,
                )
                assert context.record is not None
                return WorkflowActionTransactionResult(
                    status="QUARANTINE_REQUIRED",
                    execution_id=execution_id,
                    state=None,
                    journal=context.record,
                    index=context.index,
                    archive_path=None,
                    dispatcher_invocations=0,
                )
            receipt_context = WorkflowActionReceiptContext(
                index=context.index,
                journal=context.record,
                expected_index=cas_token(context.index),
                reauthenticate=authorization.reauthenticate,
                pre_effect_state=fresh.state,
            )
            evaluation = _workflow_tx_evaluate(
                fresh.evaluation_state,
                fresh.invocation,
                preview=False,
                receipt_context=receipt_context,
                manager_intent_state=fresh.manager_intent_state,
                edge_roles=fresh.edge_roles,
            )
            _workflow_tx_commit_evaluation(
                fresh.state,
                evaluation,
                task_path,
                authorization,
                receipt_context,
            )
            facts = _workflow_tx_authority_facts(
                task_path, context.record
            )
            if facts is None:
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_COMMIT_UNOBSERVED",
                    "receipt recovery committed no authoritative task outbox",
                )
        if phase == "RECEIPT_VERIFIED":
            nonce_consumed = _workflow_tx_nonce_consumed(
                authorization, facts
            )
            committed_journal = commit_journal(
                context.record,
                {
                    "task_commit_revision": facts.state["revision"],
                    "task_state_sha256": _sha256_contract(facts.state),
                    "event_sha256": facts.event_sha256,
                    "outbox_sha256": facts.outbox_sha256,
                    "nonce_consumed": nonce_consumed,
                },
                manager_secret=manager_secret,
            )
            context = _workflow_tx_persist_update(
                store,
                context,
                committed_journal,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
        else:
            finalization = context.record.get("finalization")
            if (
                not isinstance(finalization, dict)
                or finalization.get("event_sha256")
                != facts.event_sha256
                or finalization.get("outbox_sha256")
                != facts.outbox_sha256
                or finalization.get("task_state_sha256")
                != _sha256_contract(facts.state)
            ):
                raise _workflow_tx_error(
                    "WORKFLOW_ACTION_TRANSACTION_FINALIZATION_MISMATCH",
                    "committed journal differs from task/outbox authority",
                )
        assert context.record is not None
        closure = store.archive_and_close(
            execution_id,
            expected_index=cas_token(context.index),
            expected_journal=cas_token(context.record),
            authoritative_event_sha256=facts.event_sha256,
            manager_secret=manager_secret,
            failure_hook=failure_hook,
        )
        return WorkflowActionTransactionResult(
            status="RECOVERED_COMMITTED",
            execution_id=execution_id,
            state=facts.state,
            journal=context.record,
            index=closure.index,
            archive_path=closure.archive_path,
            dispatcher_invocations=0,
        )
    finally:
        if ordered_locks_entered and ordered_locks is not None:
            ordered_locks.__exit__(None, None, None)
        manager_secret = None


__all__ = [
    "WORKFLOW_ACTION_TRANSACTION_FAILURE_POINTS",
    "WorkflowActionAuthorization",
    "WorkflowActionClaimBatch",
    "WorkflowActionDispatchContext",
    "WorkflowActionDispatchResult",
    "WorkflowActionEffectBinding",
    "WorkflowActionEffectObservation",
    "WorkflowActionEffectStep",
    "WorkflowActionInvocation",
    "WorkflowActionObserveContext",
    "WorkflowActionRuntimeBinding",
    "WorkflowActionRuntimeLaunch",
    "WorkflowActionRuntimeReleaseAck",
    "WorkflowActionRuntimeReleaseContext",
    "WorkflowActionTransactionError",
    "WorkflowActionTransactionResult",
    "bind_v4_workflow_action_runtime",
    "claim_ready_v4_workflow_action_effects",
    "compile_v4_workflow_action_journal",
    "dispatch_claimed_v4_workflow_action_effect",
    "observe_v4_workflow_action_effect",
    "preview_v4_workflow_action_transaction",
    "release_v4_workflow_action_runtime",
    "resolve_v4_workflow_action_completion_edge",
    "verify_active_v4_workflow_action_dispatch",
    "verify_active_v4_workflow_action_dispatch_context",
    "verify_active_v4_workflow_action_observe_context",
    "verify_active_v4_workflow_action_runtime_release",
]
