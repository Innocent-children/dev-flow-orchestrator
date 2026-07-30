# Loaded by scripts/dev_flow.py after core/process persistence primitives.
# Responsibility: the only production composition layer for schema-v3
# multi-repository orchestration.  Pure contracts remain in repository_plan,
# orchestration_authority, orchestration_results, and runtime_adapters.
from __future__ import annotations

import contextlib as _osc_contextlib
import copy as _osc_copy
import hashlib as _osc_hashlib
import json as _osc_json
import os as _osc_os
import secrets as _osc_secrets
import stat as _osc_stat
import time as _osc_time
from dataclasses import dataclass as _osc_dataclass
from pathlib import Path as _OscPath
from typing import (
    Callable as _OscCallable,
    Iterator as _OscIterator,
    Mapping as _OscMapping,
    Optional as _OscOptional,
    Sequence as _OscSequence,
)


ORCHESTRATION_SERVICE_STATE_SCHEMA = "dev-flow-orchestration-state/v1"
ORCHESTRATION_INTEGRATION_SNAPSHOT_SCHEMA = (
    "dev-flow-integration-snapshot/v1"
)
ORCHESTRATION_INTEGRATION_VERIFICATION_SCHEMA = (
    "dev-flow-integration-verification/v1"
)
ORCHESTRATION_INDEPENDENT_REVIEW_SCHEMA = (
    "dev-flow-independent-review/v1"
)
ORCHESTRATION_TRUSTED_INTEGRATION_OBSERVATION_SCHEMA = (
    "dev-flow-trusted-integration-observation/v1"
)
ORCHESTRATION_TRUSTED_REVIEW_OBSERVATION_SCHEMA = (
    "dev-flow-trusted-review-observation/v1"
)
ORCHESTRATION_CONTROLLER_OUTPUT_OBSERVATION_SCHEMA = (
    "dev-flow-controller-output-observation/v1"
)
ORCHESTRATION_RUNTIME_ISOLATION_ATTESTATION_SCHEMA = (
    "dev-flow-runtime-isolation-attestation/v1"
)
ORCHESTRATION_WORKTREE_CLAIM_REGISTRY_SCHEMA = (
    "dev-flow-worktree-claim-registry/v1"
)
_OSC_EVENT_LOG_MAX_BYTES = 64 * 1024 * 1024
_OSC_EVENT_LINE_MAX_BYTES = 1024 * 1024
_OSC_EVENT_LOG_MAX_RECORDS = 100_000
_OSC_WORKTREE_CLAIM_REGISTRY_MAX_BYTES = 4 * 1024 * 1024


def _osc_utf8_sort_key(value: object) -> bytes:
    return str(value).encode("utf-8")


def _osc_random_secret(size: int) -> bytearray:
    return bytearray(_osc_secrets.token_bytes(size))


def _osc_system_monotonic_ns() -> int:
    """Return a monotonic epoch suitable for persisted cross-process leases."""

    clock_gettime_ns = getattr(_osc_time, "clock_gettime_ns", None)
    clock_monotonic = getattr(_osc_time, "CLOCK_MONOTONIC", None)
    if callable(clock_gettime_ns) and clock_monotonic is not None:
        return int(clock_gettime_ns(clock_monotonic))
    return int(_osc_time.monotonic_ns())


ORCHESTRATION_ACTION_ARTIFACT_RECORD = "orchestration.artifact.record/v1"
ORCHESTRATION_ACTION_PLAN_RECORD = "orchestration.plan.record/v1"
ORCHESTRATION_ACTION_PLAN_APPROVE = "orchestration.plan.approve/v1"
ORCHESTRATION_ACTION_PLAN_EXPAND = "orchestration.plan.expand/v1"
ORCHESTRATION_ACTION_MAP_INVALIDATE = "orchestration.map.invalidate/v1"
ORCHESTRATION_ACTION_ASSIGN = "orchestration.worker.assign/v1"
ORCHESTRATION_ACTION_RESULT_ACCEPT = "worker-result.submit/v1"
ORCHESTRATION_ACTION_BARRIER = "orchestration.barrier.evaluate/v1"
ORCHESTRATION_ACTION_INVALIDATE = "orchestration.result.invalidate/v1"
ORCHESTRATION_ACTION_RETRY = "orchestration.retry.request/v1"
ORCHESTRATION_ACTION_TIMEOUT = "orchestration.timeout.record/v1"
ORCHESTRATION_ACTION_CANCEL = "orchestration.cancellation.request/v1"
ORCHESTRATION_ACTION_RUNTIME_STOP = "orchestration.runtime-stop.record/v1"
ORCHESTRATION_ACTION_RECONCILE_BEGIN = (
    "orchestration.reconciliation.begin/v1"
)
ORCHESTRATION_ACTION_RECONCILE_COMPLETE = (
    "orchestration.reconciliation.complete/v1"
)
ORCHESTRATION_ACTION_RECOVER = "orchestration.runtime.recover/v1"
ORCHESTRATION_ACTION_INTEGRATION_CAPTURE = (
    "orchestration.integration.capture/v1"
)
ORCHESTRATION_ACTION_INTEGRATION_VERIFY = (
    "orchestration.integration.verify/v1"
)
ORCHESTRATION_ACTION_REVIEW = "orchestration.review.record/v1"
ORCHESTRATION_OPERATOR_AUTHORIZE = (
    "orchestration.manager.authorize/v1"
)
ORCHESTRATION_OPERATOR_REVOKE = "orchestration.manager.revoke/v1"

# Schema-v3 catalog identities.  The older constants above are retained only
# for their frozen service adapters; no schema-v3 action is selected through
# one of the overloaded aliases.
ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE = (
    "manager.capability.authorize/v1"
)
ORCHESTRATION_OPERATION_MANAGER_REVOKE = "manager.capability.revoke/v1"
ORCHESTRATION_OPERATION_ARTIFACT_RECORD = (
    "orchestration.artifact.record/v1"
)
ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE = (
    "orchestration.assignment.issue/v1"
)
ORCHESTRATION_OPERATION_ATTEMPT_ABANDON = (
    "orchestration.attempt.abandon/v1"
)
ORCHESTRATION_OPERATION_BARRIER_CLOSE = (
    "orchestration.barrier.close/v1"
)
ORCHESTRATION_OPERATION_BARRIER_REOPEN = (
    "orchestration.barrier.reopen/v1"
)
ORCHESTRATION_OPERATION_CANCELLATION_REQUEST = (
    "orchestration.cancellation.request/v1"
)
ORCHESTRATION_OPERATION_DISPATCH_HANDOFF = (
    "orchestration.dispatch.handoff/v1"
)
ORCHESTRATION_OPERATION_FINALIZATION_COMMIT = (
    "orchestration.finalization.commit/v1"
)
ORCHESTRATION_OPERATION_FRONTIER_ADVANCE = (
    "orchestration.frontier.advance/v1"
)
ORCHESTRATION_OPERATION_INTEGRATION_CAPTURE = (
    "orchestration.integration.capture/v1"
)
ORCHESTRATION_OPERATION_INTEGRATION_VERIFY = (
    "orchestration.integration.verify/v1"
)
ORCHESTRATION_OPERATION_LEASE_EXPIRE = (
    "orchestration.lease.expire/v1"
)
ORCHESTRATION_OPERATION_LEASE_ISSUE = "orchestration.lease.issue/v1"
ORCHESTRATION_OPERATION_LEASE_REVOKE = (
    "orchestration.lease.revoke/v1"
)
ORCHESTRATION_OPERATION_MAP_EXPAND = "orchestration.map.expand/v1"
ORCHESTRATION_OPERATION_MAP_INVALIDATE = (
    "orchestration.map.invalidate/v1"
)
ORCHESTRATION_OPERATION_PLAN_APPROVE = (
    "orchestration.plan.approve/v1"
)
ORCHESTRATION_OPERATION_PLAN_RECORD = "orchestration.plan.record/v1"
ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN = (
    "orchestration.reconciliation.begin/v1"
)
ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE = (
    "orchestration.reconciliation.complete/v1"
)
ORCHESTRATION_OPERATION_RESULT_ACCEPT = (
    "orchestration.result.accept/v1"
)
ORCHESTRATION_OPERATION_RESULT_INVALIDATE = (
    "orchestration.result.invalidate/v1"
)
ORCHESTRATION_OPERATION_RETRY_REQUEST = (
    "orchestration.retry.request/v1"
)
ORCHESTRATION_OPERATION_REVIEW_RECORD = (
    "orchestration.review.record/v1"
)
ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD = (
    "orchestration.runtime-stop.record/v1"
)
ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE = (
    "orchestration.runtime.recovery.observe/v1"
)
ORCHESTRATION_OPERATION_TIMEOUT_RECORD = (
    "orchestration.timeout.record/v1"
)

ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS = tuple(
    sorted(
        {
            ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
            ORCHESTRATION_OPERATION_MANAGER_REVOKE,
            ORCHESTRATION_OPERATION_ARTIFACT_RECORD,
            ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE,
            ORCHESTRATION_OPERATION_ATTEMPT_ABANDON,
            ORCHESTRATION_OPERATION_BARRIER_CLOSE,
            ORCHESTRATION_OPERATION_BARRIER_REOPEN,
            ORCHESTRATION_OPERATION_CANCELLATION_REQUEST,
            ORCHESTRATION_OPERATION_DISPATCH_HANDOFF,
            ORCHESTRATION_OPERATION_FINALIZATION_COMMIT,
            ORCHESTRATION_OPERATION_FRONTIER_ADVANCE,
            ORCHESTRATION_OPERATION_INTEGRATION_CAPTURE,
            ORCHESTRATION_OPERATION_INTEGRATION_VERIFY,
            ORCHESTRATION_OPERATION_LEASE_EXPIRE,
            ORCHESTRATION_OPERATION_LEASE_ISSUE,
            ORCHESTRATION_OPERATION_LEASE_REVOKE,
            ORCHESTRATION_OPERATION_MAP_EXPAND,
            ORCHESTRATION_OPERATION_MAP_INVALIDATE,
            ORCHESTRATION_OPERATION_PLAN_APPROVE,
            ORCHESTRATION_OPERATION_PLAN_RECORD,
            ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN,
            ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE,
            ORCHESTRATION_OPERATION_RESULT_ACCEPT,
            ORCHESTRATION_OPERATION_RESULT_INVALIDATE,
            ORCHESTRATION_OPERATION_RETRY_REQUEST,
            ORCHESTRATION_OPERATION_REVIEW_RECORD,
            ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
            ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE,
            ORCHESTRATION_OPERATION_TIMEOUT_RECORD,
        },
        key=_osc_utf8_sort_key,
    )
)

ORCHESTRATION_MANAGER_ACTIONS = tuple(
    operation_id
    for operation_id in ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS
    if operation_id
    not in {
        ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
        ORCHESTRATION_OPERATION_MANAGER_REVOKE,
    }
)

_osc_mutating_tool_ids = (
    "action.apply/v1",
    "evidence.accept/v1",
    "worker-result.submit/v1",
)

_osc_control_event_types = {
    ORCHESTRATION_OPERATOR_AUTHORIZE: "orchestration_manager_authorized",
    ORCHESTRATION_OPERATOR_REVOKE: "orchestration_manager_revoked",
    ORCHESTRATION_ACTION_ARTIFACT_RECORD: (
        "orchestration_artifact_recorded"
    ),
    ORCHESTRATION_ACTION_PLAN_RECORD: "orchestration_plan_recorded",
    ORCHESTRATION_ACTION_PLAN_APPROVE: "orchestration_plan_approved",
    ORCHESTRATION_ACTION_BARRIER: "orchestration_barrier_evaluated",
    ORCHESTRATION_ACTION_INVALIDATE: (
        "orchestration_result_invalidated"
    ),
    ORCHESTRATION_ACTION_TIMEOUT: (
        "orchestration_lease_timeout_recorded"
    ),
    ORCHESTRATION_ACTION_CANCEL: "orchestration_cancellation_requested",
    ORCHESTRATION_ACTION_RUNTIME_STOP: (
        "orchestration_runtime_stop_authenticated"
    ),
    ORCHESTRATION_ACTION_RECONCILE_BEGIN: (
        "orchestration_reconciliation_started"
    ),
    ORCHESTRATION_ACTION_RECONCILE_COMPLETE: (
        "orchestration_reconciliation_completed"
    ),
    ORCHESTRATION_ACTION_RECOVER: "orchestration_runtime_recovered",
    ORCHESTRATION_ACTION_INTEGRATION_CAPTURE: (
        "orchestration_integration_captured"
    ),
    ORCHESTRATION_ACTION_INTEGRATION_VERIFY: (
        "orchestration_integration_verified"
    ),
    ORCHESTRATION_ACTION_REVIEW: (
        "orchestration_independent_review_recorded"
    ),
}

_osc_control_write_policy = {
    ORCHESTRATION_OPERATOR_AUTHORIZE: (
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_OPERATOR_REVOKE: (
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_ARTIFACT_RECORD: (
        "/orchestration/artifacts",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_PLAN_RECORD: (
        "/orchestration/approval",
        "/orchestration/artifacts",
        "/orchestration/manager_capabilities",
        "/orchestration/plan",
        "/orchestration/plan_history",
    ),
    ORCHESTRATION_ACTION_PLAN_APPROVE: (
        "/orchestration/approval",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_BARRIER: (
        "/orchestration/barriers",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_INVALIDATE: (
        "/orchestration/accepted_results",
        "/orchestration/barriers",
        "/orchestration/current_results",
        "/orchestration/integration",
        "/orchestration/integration_verification",
        "/orchestration/manager_capabilities",
        "/orchestration/review",
    ),
    ORCHESTRATION_ACTION_TIMEOUT: (
        "/orchestration/dispatch",
        "/orchestration/leases",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_CANCEL: (
        "/orchestration/cancellation",
        "/orchestration/dispatch",
        "/orchestration/leases",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_RUNTIME_STOP: (
        "/orchestration/accepted_results",
        "/orchestration/cancellation",
        "/orchestration/dispatch",
        "/orchestration/leases",
        "/orchestration/manager_capabilities",
        "/orchestration/quiescence_proofs",
    ),
    ORCHESTRATION_ACTION_RECONCILE_BEGIN: (
        "/orchestration/manager_capabilities",
        "/orchestration/reconciliation_probes",
    ),
    ORCHESTRATION_ACTION_RECONCILE_COMPLETE: (
        "/orchestration/accepted_results",
        "/orchestration/cancellation",
        "/orchestration/dispatch",
        "/orchestration/leases",
        "/orchestration/manager_capabilities",
        "/orchestration/quiescence_proofs",
        "/orchestration/reconciliation_probes",
    ),
    ORCHESTRATION_ACTION_RECOVER: (
        "/orchestration/dispatch",
        "/orchestration/leases",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_INTEGRATION_CAPTURE: (
        "/orchestration/artifacts",
        "/orchestration/integration",
        "/orchestration/integration_verification",
        "/orchestration/manager_capabilities",
        "/orchestration/review",
    ),
    ORCHESTRATION_ACTION_INTEGRATION_VERIFY: (
        "/orchestration/integration_verification",
        "/orchestration/manager_capabilities",
    ),
    ORCHESTRATION_ACTION_REVIEW: (
        "/orchestration/manager_capabilities",
        "/orchestration/review",
    ),
}


@_osc_dataclass(frozen=True)
class OrchestrationCommitReceipt:
    task_id: str
    revision: int
    event_id: str
    event_type: str
    authorization_id: _OscOptional[str]
    payload: _OscMapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "revision": self.revision,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "authorization_id": self.authorization_id,
            "payload": _osc_thaw(self.payload),
        }


@_osc_dataclass(frozen=True)
class WorkerAssignmentView:
    """A data-only projection; it deliberately carries no mutation method."""

    assignment: _OscMapping[str, object]
    dispatch_mode: str
    blocker_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment": _osc_thaw(self.assignment),
            "dispatch_mode": self.dispatch_mode,
            "blocker_codes": list(self.blocker_codes),
        }


@_osc_dataclass(frozen=True)
class _OscAuthorizedControlMutation:
    operation_id: str
    event_type: str
    task_id: str
    expected_revision: int
    candidate_sha256: str
    changed_pointers: tuple[str, ...]


def _osc_error(
    code: str,
    message: str,
    *,
    details: _OscOptional[_OscMapping[str, object]] = None,
) -> Exception:
    return FlowError(code, message, details=dict(details or {}))


def _osc_translate(exc: Exception) -> Exception:
    if isinstance(exc, FlowError):
        return exc
    code = getattr(exc, "code", "ORCHESTRATION_SERVICE_FAILED")
    message = getattr(exc, "message", str(exc))
    details = getattr(exc, "details", {})
    if not isinstance(details, _OscMapping):
        details = {}
    return _osc_error(str(code), str(message), details=details)


def _osc_thaw(value: object) -> object:
    if isinstance(value, _OscMapping):
        return {str(key): _osc_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_osc_thaw(item) for item in value]
    if isinstance(value, list):
        return [_osc_thaw(item) for item in value]
    return value


def _osc_canonical_bytes(value: object) -> bytes:
    return _osc_json.dumps(
        _osc_thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _osc_digest(value: object) -> str:
    return _osc_hashlib.sha256(_osc_canonical_bytes(value)).hexdigest()


def _osc_require_v3(state: _OscMapping[str, object]) -> None:
    if state.get("schema_version") != V3_TASK_SCHEMA_VERSION:
        raise _osc_error(
            "ORCHESTRATION_V3_REQUIRED",
            "multi-repository orchestration is available only for schema-v3 tasks",
            details={"schema_version": state.get("schema_version")},
        )


def _osc_empty_state() -> dict[str, object]:
    return {
        "schema": ORCHESTRATION_SERVICE_STATE_SCHEMA,
        "artifacts": {},
        "plan": None,
        "plan_history": [],
        "approval": None,
        "expansion": None,
        "manager_capabilities": {},
        "frontier": {},
        "leases": {},
        "assignments": {},
        "dispatch": {},
        "attempts": {},
        "accepted_results": {},
        "current_results": {},
        "barriers": {},
        "quiescence_proofs": {},
        "reconciliation_probes": {},
        "retries": {},
        "timeouts": {},
        "pending_retries": {},
        "cancellation": {
            "requested": False,
            "quiesced": False,
            "affected_lease_ids": [],
            "uncertain_lease_ids": [],
        },
        "integration": None,
        "integration_verification": None,
        "review": None,
        "finalization": None,
    }


def _osc_state_copy(state: _OscMapping[str, object]) -> dict[str, object]:
    _osc_require_v3(state)
    raw = state.get("orchestration")
    if raw is None:
        return _osc_empty_state()
    if not isinstance(raw, _OscMapping):
        raise _osc_error(
            "ORCHESTRATION_STATE_INVALID",
            "persisted orchestration state must be an object",
        )
    if raw.get("schema") != ORCHESTRATION_SERVICE_STATE_SCHEMA:
        raise _osc_error(
            "ORCHESTRATION_STATE_SCHEMA_UNSUPPORTED",
            "persisted orchestration state schema is unsupported",
            details={"schema": raw.get("schema")},
        )
    result = _osc_copy.deepcopy(_osc_thaw(raw))
    expected = _osc_empty_state()
    unknown = sorted(set(result) - set(expected))
    if unknown:
        raise _osc_error(
            "ORCHESTRATION_STATE_INVALID",
            "persisted orchestration state has unknown fields",
            details={"fields": unknown},
        )
    for key, default in expected.items():
        result.setdefault(key, _osc_copy.deepcopy(default))
    for key in (
        "artifacts",
        "manager_capabilities",
        "frontier",
        "leases",
        "assignments",
        "dispatch",
        "attempts",
        "accepted_results",
        "current_results",
        "barriers",
        "quiescence_proofs",
        "reconciliation_probes",
        "retries",
        "timeouts",
        "pending_retries",
    ):
        if not isinstance(result[key], dict):
            raise _osc_error(
                "ORCHESTRATION_STATE_INVALID",
                "persisted orchestration collection is invalid",
                details={"field": key},
            )
    if not isinstance(result["plan_history"], list):
        raise _osc_error(
            "ORCHESTRATION_STATE_INVALID",
            "persisted plan history must be an array",
            details={"field": "plan_history"},
        )
    return result


def _osc_artifact_locator(content_sha256: str) -> str:
    if (
        not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in content_sha256
        )
    ):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INVALID",
            "artifact locator requires a lowercase content SHA-256",
        )
    return f"artifacts/orchestration/{content_sha256}.json"


def _osc_store_artifact(
    task_dir: _OscPath,
    orchestration: dict[str, object],
    *,
    artifact_id: str,
    content: bytes,
    kind: str,
    semantic_sha256: str,
) -> dict[str, object]:
    reference = _osc_artifact_reference(
        artifact_id=artifact_id,
        content=content,
        kind=kind,
        semantic_sha256=semantic_sha256,
    )
    _osc_publish_artifact(task_dir, reference, content)
    artifacts = orchestration["artifacts"]
    assert isinstance(artifacts, dict)
    prior = artifacts.get(artifact_id)
    if prior is not None and prior != reference:
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_IDENTITY_CONFLICT",
            "artifact identity already has different persisted facts",
            details={"artifact_id": artifact_id},
        )
    artifacts[artifact_id] = reference
    return reference


def _osc_artifact_reference(
    *,
    artifact_id: str,
    content: bytes,
    kind: str,
    semantic_sha256: str,
) -> dict[str, object]:
    """Derive one immutable artifact reference without writing bytes."""

    if not isinstance(content, bytes):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INVALID",
            "artifact content must be bytes",
        )
    if (
        not isinstance(artifact_id, str)
        or not artifact_id
        or not isinstance(kind, str)
        or not kind
        or not isinstance(semantic_sha256, str)
        or len(semantic_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in semantic_sha256
        )
    ):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INVALID",
            "artifact reference requires exact identity, kind, and semantic SHA-256",
        )
    sha256 = _osc_hashlib.sha256(content).hexdigest()
    locator = _osc_artifact_locator(sha256)
    return {
        "id": artifact_id,
        "semantic_sha256": semantic_sha256,
        "sha256": sha256,
        "size": len(content),
        "kind": kind,
        "locator": locator,
    }


def _osc_publish_artifact(
    task_dir: _OscPath,
    reference: _OscMapping[str, object],
    content: bytes,
) -> None:
    """Idempotently publish bytes only from a claimed dispatcher."""

    if (
        not isinstance(content, bytes)
        or reference
        != _osc_artifact_reference(
            artifact_id=str(reference.get("id", "")),
            content=content,
            kind=str(reference.get("kind", "")),
            semantic_sha256=str(
                reference.get("semantic_sha256", "")
            ),
        )
    ):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INVALID",
            "published bytes do not match their prepared artifact reference",
        )
    locator = str(reference["locator"])
    path = task_dir / locator
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise _osc_error(
                "ORCHESTRATION_ARTIFACT_READ_FAILED",
                "could not read an existing task artifact",
                details={"artifact_id": reference["id"]},
            ) from exc
        if existing != content:
            raise _osc_error(
                "ORCHESTRATION_ARTIFACT_IDENTITY_CONFLICT",
                "artifact identity already names different bytes",
                details={"artifact_id": reference["id"]},
            )
    else:
        _atomic_write_bytes(path, content)


def _osc_read_artifact(
    task_dir: _OscPath,
    orchestration: _OscMapping[str, object],
    artifact_id: str,
) -> bytes:
    artifacts = orchestration.get("artifacts")
    if not isinstance(artifacts, _OscMapping):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_MISSING",
            "task has no orchestration artifact index",
        )
    reference = artifacts.get(artifact_id)
    if not isinstance(reference, _OscMapping):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_MISSING",
            "task-scoped artifact is absent",
            details={"artifact_id": artifact_id},
        )
    locator = reference.get("locator")
    if not isinstance(locator, str) or locator != _osc_artifact_locator(
        str(reference.get("sha256"))
    ):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INVALID",
            "task artifact locator is not controller-owned",
            details={"artifact_id": artifact_id},
        )
    try:
        content = (task_dir / locator).read_bytes()
    except OSError as exc:
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_READ_FAILED",
            "could not read task-scoped artifact",
            details={"artifact_id": artifact_id},
        ) from exc
    if (
        _osc_hashlib.sha256(content).hexdigest() != reference.get("sha256")
        or len(content) != reference.get("size")
    ):
        raise _osc_error(
            "ORCHESTRATION_ARTIFACT_INTEGRITY_MISMATCH",
            "task artifact bytes differ from persisted integrity facts",
            details={"artifact_id": artifact_id},
        )
    return content


def _osc_path_is_within(pointer: str, root: str) -> bool:
    return pointer == root or pointer.startswith(root.rstrip("/") + "/")


def _osc_mapping_delta(
    before: object,
    after: object,
    *,
    field: str,
) -> tuple[set[str], set[str], set[str]]:
    if not isinstance(before, _OscMapping) or not isinstance(
        after, _OscMapping
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
            "a package-owned orchestration ledger is not an object",
            details={"field": field},
        )
    old_keys = set(before)
    new_keys = set(after)
    return (
        new_keys - old_keys,
        old_keys - new_keys,
        {
            key
            for key in old_keys & new_keys
            if before[key] != after[key]
        },
    )


def _osc_require_mapping_delta(
    before: object,
    after: object,
    *,
    field: str,
    added: set[str] = frozenset(),
    removed: set[str] = frozenset(),
    modified: set[str] = frozenset(),
) -> None:
    actual = _osc_mapping_delta(before, after, field=field)
    expected = (set(added), set(removed), set(modified))
    if actual != expected:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
            "orchestration ledger delta exceeds its fixed operation shape",
            details={
                "field": field,
                "expected": [sorted(value) for value in expected],
                "actual": [sorted(value) for value in actual],
            },
        )


def _osc_validate_manager_nonce_delta(
    before: _OscMapping[str, object],
    after: _OscMapping[str, object],
    payload: _OscMapping[str, object],
) -> None:
    capability_id = payload.get("manager_capability_id")
    authorization_id = payload.get("manager_authorization_id")
    if (
        not isinstance(capability_id, str)
        or not isinstance(authorization_id, str)
        or not authorization_id
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "authorized control payload lacks its manager binding",
        )
    old_caps = before.get("manager_capabilities")
    new_caps = after.get("manager_capabilities")
    _osc_require_mapping_delta(
        old_caps,
        new_caps,
        field="manager_capabilities",
        modified={capability_id},
    )
    assert isinstance(old_caps, _OscMapping)
    assert isinstance(new_caps, _OscMapping)
    old_record = old_caps[capability_id]
    new_record = new_caps[capability_id]
    if not isinstance(old_record, _OscMapping) or not isinstance(
        new_record, _OscMapping
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "manager verifier delta is invalid",
        )
    old_nonces = old_record.get("used_request_nonce_sha256s")
    new_nonces = new_record.get("used_request_nonce_sha256s")
    if (
        not isinstance(old_nonces, (list, tuple))
        or not isinstance(new_nonces, (list, tuple))
        or len(new_nonces) != len(old_nonces) + 1
        or len(set(new_nonces)) != len(new_nonces)
        or not set(old_nonces).issubset(set(new_nonces))
        or list(new_nonces)
        != sorted(new_nonces, key=lambda item: str(item).encode("utf-8"))
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_NONCE_INVALID",
            "authorized control mutation must append exactly one manager nonce",
            details={"capability_id": capability_id},
        )
    old_without_nonce = dict(old_record)
    new_without_nonce = dict(new_record)
    old_without_nonce.pop("used_request_nonce_sha256s", None)
    new_without_nonce.pop("used_request_nonce_sha256s", None)
    if old_without_nonce != new_without_nonce:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_NONCE_INVALID",
            "manager authorization may not rewrite verifier scope",
            details={"capability_id": capability_id},
        )


def _osc_dispatch_ids_for_leases(
    orchestration: _OscMapping[str, object],
    lease_ids: set[str],
) -> set[str]:
    assignments = orchestration.get("assignments")
    if not isinstance(assignments, _OscMapping):
        return set()
    return {
        str(assignment_id)
        for assignment_id, value in assignments.items()
        if isinstance(value, _OscMapping)
        and isinstance(value.get("lease_credential"), _OscMapping)
        and value["lease_credential"].get("lease_id") in lease_ids
    }


def _osc_derive_barrier_definition(
    state: _OscMapping[str, object],
    orchestration: _OscMapping[str, object],
    bundle: object,
) -> dict[str, object]:
    expansion = _osc_current_expansion(orchestration)
    plan = orchestration.get("plan")
    approval = orchestration.get("approval")
    metadata = getattr(bundle, "repository_orchestration", None)
    join = (
        metadata.get("join")
        if isinstance(metadata, _OscMapping)
        else None
    )
    policy = (
        join.get("barrier_policy")
        if isinstance(join, _OscMapping)
        else None
    )
    if (
        not isinstance(plan, _OscMapping)
        or not isinstance(approval, _OscMapping)
        or not isinstance(join, _OscMapping)
        or not isinstance(policy, _OscMapping)
    ):
        raise _osc_error(
            "RESULT_BARRIER_INPUT_INCOMPLETE",
            "canonical barrier requires expansion, plan approval, and pinned join policy",
    )
    join_node_id = join.get("node_id")
    nodes = state.get("node_instances")
    if not isinstance(nodes, list):
        raise _osc_error(
            "RESULT_BARRIER_JOIN_INVALID",
            "task node instance ledger is invalid",
        )
    join_instances = [
        node
        for node in nodes
        if isinstance(node, _OscMapping)
        and node.get("node_id") == join_node_id
        and node.get("repository_id") is None
    ]
    if len(join_instances) != 1:
        raise _osc_error(
            "RESULT_BARRIER_JOIN_INVALID",
            "pinned join node does not resolve to one static instance",
        )
    allowed_outcomes = list(policy.get("required_outcomes", ()))
    members = [
        {
            "node_instance_id": child["node_instance_id"],
            "repository_id": child["repository_id"],
            "required": True,
            "allowed_outcomes": allowed_outcomes,
        }
        for child in expansion.get("children", ())
        if isinstance(child, _OscMapping)
    ]
    members.sort(
        key=lambda item: str(item["node_instance_id"]).encode("utf-8")
    )
    identity = {
        "task_id": state.get("task_id"),
        "workflow_bundle_sha256": state.get(
            "workflow_ref", {}
        ).get("bundle_sha256"),
        "plan_id": plan.get("plan_id"),
        "map_epoch": plan.get("map_epoch"),
        "node_instance_id": join_instances[0].get(
            "node_instance_id"
        ),
        "policy_id": policy.get("id"),
        "members": members,
    }
    return {
        "schema": RESULT_BARRIER_SCHEMA,
        "barrier_id": "repository-barrier:" + _osc_digest(identity),
        "task_id": state["task_id"],
        "workflow_bundle_sha256": state["workflow_ref"][
            "bundle_sha256"
        ],
        "plan_id": plan["plan_id"],
        "dag_sha256": approval["dag_sha256"],
        "map_epoch": plan["map_epoch"],
        "node_instance_id": join_instances[0]["node_instance_id"],
        "members": members,
    }


def _osc_validate_control_semantics(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    *,
    operation_id: str,
    payload: _OscMapping[str, object],
) -> None:
    before = _osc_state_copy(old_state)
    after = _osc_state_copy(candidate_state)
    old_caps = before["manager_capabilities"]
    new_caps = after["manager_capabilities"]
    if operation_id == ORCHESTRATION_OPERATOR_AUTHORIZE:
        capability_id = payload.get("capability_id")
        if not isinstance(capability_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "manager authorization payload lacks capability identity",
            )
        _osc_require_mapping_delta(
            old_caps,
            new_caps,
            field="manager_capabilities",
            added={capability_id},
        )
        assert isinstance(new_caps, _OscMapping)
        record = new_caps[capability_id]
        try:
            validate_manager_capability_verifier(record)
        except Exception as exc:
            raise _osc_translate(exc) from exc
        if (
            not isinstance(record, _OscMapping)
            or record.get("capability_id") != capability_id
            or record.get("task_id") != old_state.get("task_id")
            or record.get("manager_session_id")
            != payload.get("manager_session_id")
            or list(record.get("allowed_actions", ()))
            != payload.get("allowed_actions")
            or record.get("secret_transport")
            != payload.get("secret_transport")
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "manager verifier does not match its authorization payload",
            )
        return
    if operation_id == ORCHESTRATION_OPERATOR_REVOKE:
        capability_id = payload.get("capability_id")
        if not isinstance(capability_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "manager revocation payload lacks capability identity",
            )
        _osc_require_mapping_delta(
            old_caps,
            new_caps,
            field="manager_capabilities",
            modified={capability_id},
        )
        assert isinstance(old_caps, _OscMapping)
        assert isinstance(new_caps, _OscMapping)
        old_record = old_caps[capability_id]
        new_record = new_caps[capability_id]
        try:
            validate_manager_capability_verifier(new_record)
        except Exception as exc:
            raise _osc_translate(exc) from exc
        if not isinstance(old_record, _OscMapping) or not isinstance(
            new_record, _OscMapping
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "manager revocation verifier is invalid",
            )
        allowed = {
            "revoked_at_wall_ns",
            "revocation_reason",
            "revocation_audit_sha256",
        }
        if (
            any(
                old_record.get(key) != value
                for key, value in new_record.items()
                if key not in allowed
            )
            or set(old_record) != set(new_record)
            or new_record.get("revoked_at_wall_ns") is None
            or new_record.get("revocation_reason")
            != payload.get("reason")
            or new_record.get("revocation_audit_sha256")
            != payload.get("revocation_audit_sha256")
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "manager revocation changed facts outside its exact verifier",
            )
        return

    _osc_validate_manager_nonce_delta(before, after, payload)

    if operation_id == ORCHESTRATION_ACTION_ARTIFACT_RECORD:
        artifact_id = payload.get("id")
        if not isinstance(artifact_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "artifact event lacks its content identity",
            )
        _osc_require_mapping_delta(
            before["artifacts"],
            after["artifacts"],
            field="artifacts",
            added={artifact_id},
        )
        assert isinstance(after["artifacts"], _OscMapping)
        reference = after["artifacts"][artifact_id]
        if (
            not isinstance(reference, _OscMapping)
            or set(reference)
            != {"id", "semantic_sha256", "sha256", "size", "kind", "locator"}
            or reference
            != {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "event_id",
                "manager_authorization_id",
                "manager_capability_id",
                "operation_id",
            }
            }
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "artifact ledger entry differs from the event payload",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_PLAN_RECORD:
        artifact_id = payload.get("artifact_id")
        plan_id = payload.get("plan_id")
        if not isinstance(artifact_id, str) or not isinstance(
            plan_id, str
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "plan event lacks its plan and artifact identities",
            )
        added, removed, modified = _osc_mapping_delta(
            before["artifacts"], after["artifacts"], field="artifacts"
        )
        if removed or modified or added not in (set(), {artifact_id}):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "plan recording may only add its content-addressed plan artifact",
            )
        expected_record = {
            key: payload[key]
            for key in (
                "artifact_id",
                "artifact_sha256",
                "dag_sha256",
                "semantic_input_sha256",
                "plan_id",
                "map_epoch",
                "plan_input_revision",
            )
        }
        if after.get("plan") != expected_record:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "persisted plan record differs from its event payload",
            )
        if added:
            assert isinstance(after["artifacts"], _OscMapping)
            reference = after["artifacts"][artifact_id]
            if (
                not isinstance(reference, _OscMapping)
                or set(reference)
                != {
                    "id",
                    "semantic_sha256",
                    "sha256",
                    "size",
                    "kind",
                    "locator",
                }
                or reference.get("id") != artifact_id
                or reference.get("sha256")
                != payload.get("artifact_sha256")
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_BINDING_INVALID",
                    "plan artifact reference is not its fixed controller schema",
                )
        old_history = before["plan_history"]
        new_history = after["plan_history"]
        if (
            not isinstance(old_history, list)
            or not isinstance(new_history, list)
            or new_history[: len(old_history)] != old_history
            or len(new_history) not in {
                len(old_history),
                len(old_history) + 1,
            }
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "plan history must be append-only",
            )
        if len(new_history) == len(old_history) + 1:
            prior = before.get("plan")
            appended = dict(new_history[-1])
            superseded = appended.pop(
                "superseded_at_revision", None
            )
            if (
                appended != prior
                or superseded
                != int(old_state.get("revision", -1)) + 1
                or after.get("approval") is not None
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_BINDING_INVALID",
                    "replacement plan history does not bind the superseded plan",
                )
        elif after.get("approval") != before.get("approval"):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "initial or idempotent plan recording may not change approval",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_PLAN_APPROVE:
        approval = after.get("approval")
        plan = after.get("plan")
        if not isinstance(approval, _OscMapping) or not isinstance(
            plan, _OscMapping
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "plan approval must bind the persisted plan",
            )
        try:
            _repository_plan_validate_approval_shape(approval)
        except Exception as exc:
            raise _osc_translate(exc) from exc
        if (
            approval.get("plan_id") != plan.get("plan_id")
            or approval.get("dag_sha256") != payload.get("dag_sha256")
            or approval.get("approval_commit_revision")
            != payload.get("approval_commit_revision")
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "plan approval differs from its event and plan",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_BARRIER:
        barrier_id = payload.get("barrier_id")
        if not isinstance(barrier_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "barrier event lacks its identity",
            )
        added, removed, modified = _osc_mapping_delta(
            before["barriers"], after["barriers"], field="barriers"
        )
        if removed or (added | modified) != {barrier_id}:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "barrier evaluation may change only its derived barrier",
            )
        assert isinstance(after["barriers"], _OscMapping)
        barrier_record = after["barriers"][barrier_id]
        expected_definition = _osc_derive_barrier_definition(
            candidate_state,
            after,
            _osc_resolve_multi_bundle(candidate_state),
        )
        if (
            not isinstance(barrier_record, _OscMapping)
            or barrier_record.get("definition")
            != expected_definition
            or barrier_record.get("status") != payload.get("status")
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "barrier status differs from its event payload",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_INVALIDATE:
        result_id = payload.get("result_id")
        if not isinstance(result_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "invalidation event lacks its result identity",
            )
        _osc_require_mapping_delta(
            before["accepted_results"],
            after["accepted_results"],
            field="accepted_results",
            modified={result_id},
        )
        assert isinstance(before["accepted_results"], _OscMapping)
        assert isinstance(after["accepted_results"], _OscMapping)
        old_record = before["accepted_results"][result_id]
        new_record = after["accepted_results"][result_id]
        if not isinstance(old_record, _OscMapping) or not isinstance(
            new_record, _OscMapping
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "invalidated result record is invalid",
            )
        expected = dict(old_record)
        expected["current"] = False
        if new_record != expected:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "invalidation may only clear the affected result current flag",
            )
        result_value = old_record.get("result")
        node_id = (
            result_value.get("node_instance_id")
            if isinstance(result_value, _OscMapping)
            else None
        )
        if not isinstance(node_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "invalidated result has no node identity",
            )
        old_current = before["current_results"]
        new_current = after["current_results"]
        if (
            isinstance(old_current, _OscMapping)
            and old_current.get(node_id) == result_id
        ):
            _osc_require_mapping_delta(
                old_current,
                new_current,
                field="current_results",
                removed={node_id},
            )
        else:
            _osc_require_mapping_delta(
                old_current,
                new_current,
                field="current_results",
            )
        old_barriers = before["barriers"]
        new_barriers = after["barriers"]
        assert isinstance(old_barriers, _OscMapping)
        assert isinstance(new_barriers, _OscMapping)
        expected_barriers = _osc_copy.deepcopy(
            _osc_thaw(old_barriers)
        )
        for value in expected_barriers.values():
            if (
                isinstance(value, dict)
                and value.get("aggregate") is not None
            ):
                value["status"] = "REOPENED"
                value["aggregate"] = None
        if new_barriers != expected_barriers:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "result invalidation changed a barrier outside its affected closure",
            )
        reason = payload.get("reason")
        for field in (
            "integration",
            "integration_verification",
            "review",
        ):
            old_value = before.get(field)
            new_value = after.get(field)
            if isinstance(old_value, _OscMapping):
                expected_value = dict(_osc_thaw(old_value))
                expected_value["current"] = False
                if field == "integration":
                    expected_value["stale_reason"] = reason
                if new_value != expected_value:
                    raise _osc_error(
                        "ORCHESTRATION_CONTROL_DELTA_INVALID",
                        "result invalidation changed downstream state outside currentness",
                        details={"field": field},
                    )
            elif new_value is not None:
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "result invalidation created downstream state",
                    details={"field": field},
                )
        return

    if operation_id == ORCHESTRATION_ACTION_RECONCILE_BEGIN:
        lease_id = payload.get("lease_id")
        if not isinstance(lease_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "reconciliation event lacks lease identity",
            )
        _osc_require_mapping_delta(
            before["reconciliation_probes"],
            after["reconciliation_probes"],
            field="reconciliation_probes",
            added={lease_id},
        )
        return

    if operation_id in {
        ORCHESTRATION_ACTION_TIMEOUT,
        ORCHESTRATION_ACTION_RUNTIME_STOP,
        ORCHESTRATION_ACTION_RECONCILE_COMPLETE,
        ORCHESTRATION_ACTION_RECOVER,
    }:
        lease_id = payload.get("lease_id")
        if not isinstance(lease_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "lease operation event lacks lease identity",
            )
        lease_delta = _osc_mapping_delta(
            before["leases"], after["leases"], field="leases"
        )
        if lease_delta[0] or lease_delta[1] or not lease_delta[
            2
        ].issubset({lease_id}):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "lease operation changed an unrelated lease",
            )
        allowed_dispatch = _osc_dispatch_ids_for_leases(
            before, {lease_id}
        )
        dispatch_delta = _osc_mapping_delta(
            before["dispatch"], after["dispatch"], field="dispatch"
        )
        if (
            dispatch_delta[0]
            or dispatch_delta[1]
            or not dispatch_delta[2].issubset(allowed_dispatch)
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "lease operation changed unrelated dispatch state",
            )
        assert isinstance(before["dispatch"], _OscMapping)
        assert isinstance(after["dispatch"], _OscMapping)
        for assignment_id in dispatch_delta[2]:
            old_dispatch = before["dispatch"][assignment_id]
            new_dispatch = after["dispatch"][assignment_id]
            if not isinstance(old_dispatch, _OscMapping) or not isinstance(
                new_dispatch, _OscMapping
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "lease dispatch record is invalid",
                )
            expected_dispatch = dict(old_dispatch)
            if operation_id == ORCHESTRATION_ACTION_TIMEOUT:
                expected_dispatch["runtime_status"] = "EXPIRED"
            elif operation_id in {
                ORCHESTRATION_ACTION_RUNTIME_STOP,
                ORCHESTRATION_ACTION_RECONCILE_COMPLETE,
            }:
                expected_dispatch["runtime_status"] = "QUIESCED"
                expected_dispatch["runtime_live"] = False
            elif payload.get("reattach") is True:
                expected_dispatch["runtime_status"] = "ACTIVE"
                expected_dispatch["runtime_live"] = True
            else:
                expected_dispatch["runtime_status"] = "ORPHANED"
            if new_dispatch != expected_dispatch:
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "lease operation rewrote dispatch fields outside its exact transition",
                    details={"assignment_id": assignment_id},
                )
        if lease_delta[2]:
            assert isinstance(before["leases"], _OscMapping)
            assert isinstance(after["leases"], _OscMapping)
            old_lease = before["leases"][lease_id]
            new_lease = after["leases"][lease_id]
            if not isinstance(old_lease, _OscMapping) or not isinstance(
                new_lease, _OscMapping
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "lease record is invalid",
                )
            allowed_lease_fields = {
                "state",
                "revoked_at_wall_ns",
                "revocation_reason",
            }
            if operation_id in {
                ORCHESTRATION_ACTION_RUNTIME_STOP,
                ORCHESTRATION_ACTION_RECONCILE_COMPLETE,
            }:
                allowed_lease_fields.update(
                    {
                        "quiesced_at_wall_ns",
                        "quiescence_evidence_sha256",
                    }
                )
            if (
                set(old_lease) != set(new_lease)
                or any(
                    old_lease.get(key) != value
                    for key, value in new_lease.items()
                    if key not in allowed_lease_fields
                )
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "lease operation rewrote immutable lease scope",
                    details={"lease_id": lease_id},
                )
        if operation_id == ORCHESTRATION_ACTION_RECONCILE_COMPLETE:
            _osc_require_mapping_delta(
                before["reconciliation_probes"],
                after["reconciliation_probes"],
                field="reconciliation_probes",
                removed={lease_id},
            )
        if operation_id in {
            ORCHESTRATION_ACTION_RUNTIME_STOP,
            ORCHESTRATION_ACTION_RECONCILE_COMPLETE,
        }:
            old_proofs = before["quiescence_proofs"]
            new_proofs = after["quiescence_proofs"]
            added_proofs, removed_proofs, modified_proofs = (
                _osc_mapping_delta(
                    old_proofs,
                    new_proofs,
                    field="quiescence_proofs",
                )
            )
            if (
                removed_proofs
                or modified_proofs
                or added_proofs != {lease_id}
                or not isinstance(new_proofs, _OscMapping)
                or new_proofs[lease_id].get("proof_sha256")
                != payload.get("proof_sha256")
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "quiescence operation did not append its exact lease proof",
                )
            old_results = before["accepted_results"]
            new_results = after["accepted_results"]
            assert isinstance(old_results, _OscMapping)
            assert isinstance(new_results, _OscMapping)
            expected_results = _osc_copy.deepcopy(
                _osc_thaw(old_results)
            )
            for record in expected_results.values():
                result = (
                    record.get("result")
                    if isinstance(record, dict)
                    else None
                )
                if (
                    isinstance(result, dict)
                    and result.get("lease_id") == lease_id
                ):
                    record["lease_quiesced"] = True
                    record["runtime_live"] = False
            if new_results != expected_results:
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "quiescence operation changed unrelated accepted results",
                )
            old_cancellation = before.get("cancellation")
            expected_cancellation = _osc_copy.deepcopy(
                _osc_thaw(old_cancellation)
            )
            if (
                isinstance(expected_cancellation, dict)
                and expected_cancellation.get("requested") is True
            ):
                affected = expected_cancellation.get(
                    "affected_lease_ids"
                )
                if not isinstance(affected, list) or any(
                    not isinstance(value, str) for value in affected
                ):
                    raise _osc_error(
                        "ORCHESTRATION_CONTROL_BINDING_INVALID",
                        "requested cancellation lacks its immutable affected lease set",
                    )
                uncertain = sorted(
                    (
                        value
                        for value in affected
                        if value not in new_proofs
                    ),
                    key=_osc_utf8_sort_key,
                )
                expected_cancellation[
                    "uncertain_lease_ids"
                ] = uncertain
                expected_cancellation["quiesced"] = not uncertain
            if after.get("cancellation") != expected_cancellation:
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "quiescence operation changed cancellation outside its lease closure",
                )
        return

    if operation_id == ORCHESTRATION_ACTION_CANCEL:
        lease_ids = set(payload.get("lease_ids_to_revoke", ()))
        affected = set(payload.get("affected_lease_ids", ()))
        uncertain = set(
            payload.get(
                "lease_ids_requiring_reconciliation", ()
            )
        )
        if affected != set(before["leases"]):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "cancellation affected lease set does not bind every current lease",
            )
        if after.get("cancellation") != {
            "requested": True,
            "quiesced": False,
            "affected_lease_ids": sorted(
                affected, key=_osc_utf8_sort_key
            ),
            "uncertain_lease_ids": sorted(
                uncertain, key=_osc_utf8_sort_key
            ),
        }:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "cancellation ledger differs from its derived candidate",
            )
        lease_delta = _osc_mapping_delta(
            before["leases"], after["leases"], field="leases"
        )
        if lease_delta[0] or lease_delta[1] or lease_delta[2] != lease_ids:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "cancellation changed leases outside its derived set",
            )
        allowed_dispatch = _osc_dispatch_ids_for_leases(
            before, lease_ids
        )
        dispatch_delta = _osc_mapping_delta(
            before["dispatch"], after["dispatch"], field="dispatch"
        )
        if (
            dispatch_delta[0]
            or dispatch_delta[1]
            or dispatch_delta[2] != allowed_dispatch
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "cancellation changed dispatch outside its derived set",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_INTEGRATION_CAPTURE:
        snapshot_id = payload.get("snapshot_id")
        if not isinstance(snapshot_id, str):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "integration event lacks snapshot identity",
            )
        _osc_require_mapping_delta(
            before["artifacts"],
            after["artifacts"],
            field="artifacts",
            added={snapshot_id},
        )
        integration = after.get("integration")
        if (
            not isinstance(integration, _OscMapping)
            or set(integration)
            != {
                "snapshot_id",
                "snapshot_sha256",
                "locator",
                "current",
                "stale_reason",
                "payload",
            }
            or integration.get("snapshot_id") != snapshot_id
            or integration.get("snapshot_sha256")
            != payload.get("snapshot_sha256")
            or integration.get("current") is not True
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "integration ledger differs from its snapshot event",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_INTEGRATION_VERIFY:
        verification = after.get("integration_verification")
        integration = after.get("integration")
        if payload.get("outcome") == "STALE":
            if (
                verification is not None
                or not isinstance(integration, _OscMapping)
                or integration.get("current") is not False
            ):
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_BINDING_INVALID",
                    "stale integration verification did not invalidate its snapshot",
                )
        elif (
            not isinstance(verification, _OscMapping)
            or set(verification)
            != {"verification_id", "current", "payload"}
            or verification.get("verification_id")
            != payload.get("verification_id")
            or verification.get("current") is not True
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "integration verification differs from its event",
            )
        return

    if operation_id == ORCHESTRATION_ACTION_REVIEW:
        review = after.get("review")
        if (
            not isinstance(review, _OscMapping)
            or set(review) != {"review_id", "current", "payload"}
            or review.get("review_id") != payload.get("review_id")
            or review.get("current") is not True
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_BINDING_INVALID",
                "independent review differs from its event",
            )
        return

    raise _osc_error(
        "ORCHESTRATION_OPERATION_UNSUPPORTED",
        "control operation lacks a package-owned semantic delta validator",
        details={"operation_id": operation_id},
    )


_OSC_AUTHORITATIVE_INTENT_SCHEMA = (
    "dev-flow-orchestration-authoritative-intent/v1"
)
_OSC_AUTHORITATIVE_OPERATION_FINGERPRINT_DOMAIN = (
    b"dev-flow-orchestration-authoritative-operation-v1\0"
)
_OSC_AUTHORITATIVE_INTENT_FIELDS = frozenset(
    {"candidate_state", "event_payload", "schema"}
)
_OSC_AUTHORITATIVE_IMMUTABLE_STATE_FIELDS = (
    "execution_profile",
    "flow",
    "revision",
    "schema_version",
    "status",
    "task_id",
    "workflow_ref",
)


def _osc_authoritative_intent_parts(
    state: _OscMapping[str, object],
    intent: object,
    selection: object,
    *,
    operation_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    if (
        type(intent) is not OrchestrationActionSemanticIntent
        or intent.operation_id != operation_id
        or getattr(selection, "operation_id", None) != operation_id
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_INTENT_CROSS_BINDING",
            "orchestration semantic validator received another operation",
            details={"operation_id": operation_id},
        )
    payload = intent.payload
    if (
        not isinstance(payload, _OscMapping)
        or set(payload) != _OSC_AUTHORITATIVE_INTENT_FIELDS
        or payload.get("schema") != _OSC_AUTHORITATIVE_INTENT_SCHEMA
        or not isinstance(payload.get("candidate_state"), _OscMapping)
        or not isinstance(payload.get("event_payload"), _OscMapping)
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_INTENT_INVALID",
            "orchestration semantic intent has no exact typed candidate envelope",
            details={"operation_id": operation_id},
        )
    candidate = _osc_copy.deepcopy(
        _osc_thaw(payload["candidate_state"])
    )
    event_payload = _osc_copy.deepcopy(
        _osc_thaw(payload["event_payload"])
    )
    if not isinstance(candidate, dict) or not isinstance(
        event_payload, dict
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_INTENT_INVALID",
            "orchestration semantic intent candidate is not an object",
            details={"operation_id": operation_id},
        )
    for field in _OSC_AUTHORITATIVE_IMMUTABLE_STATE_FIELDS:
        if candidate.get(field) != state.get(field):
            raise _osc_error(
                "ORCHESTRATION_ACTION_BINDING_INVALID",
                "orchestration candidate changed an immutable task binding",
                details={"operation_id": operation_id, "field": field},
            )
    if event_payload.get("operation_id") != operation_id:
        raise _osc_error(
            "ORCHESTRATION_ACTION_EVENT_BINDING_INVALID",
            "orchestration event payload belongs to another operation",
            details={"operation_id": operation_id},
        )
    expected_event_id = getattr(selection, "event_id", None)
    if event_payload.get("event_id") != expected_event_id:
        raise _osc_error(
            "ORCHESTRATION_ACTION_EVENT_BINDING_INVALID",
            "orchestration event payload differs from the selected event identity",
            details={
                "operation_id": operation_id,
                "expected_event_id": expected_event_id,
                "actual_event_id": event_payload.get("event_id"),
            },
        )
    _osc_state_copy(state)
    _osc_state_copy(candidate)
    return candidate, event_payload


def _osc_authoritative_candidate(
    candidate: dict[str, object],
    event_payload: dict[str, object],
    *,
    operation_id: str,
    semantic_contract: str,
) -> OrchestrationActionSemanticCandidate:
    return OrchestrationActionSemanticCandidate(
        candidate,
        {
            "schema": (
                "dev-flow-orchestration-semantic-validation-evidence/v1"
            ),
            "operation_id": operation_id,
            "semantic_contract": semantic_contract,
            "event_payload_sha256": _osc_digest(event_payload),
            "candidate_state_sha256": _osc_digest(candidate),
        },
    )


def _osc_authoritative_orchestration_pair(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    before = _osc_state_copy(old_state)
    after = _osc_state_copy(candidate_state)
    _osc_validate_manager_nonce_delta(before, after, event_payload)
    return before, after


def _osc_authoritative_mapping_change(
    before: _OscMapping[str, object],
    after: _OscMapping[str, object],
    *,
    field: str,
    key: str,
    mode: str,
) -> tuple[object, object]:
    old_value = before.get(field)
    new_value = after.get(field)
    if mode == "add":
        _osc_require_mapping_delta(
            old_value, new_value, field=field, added={key}
        )
    elif mode == "modify":
        _osc_require_mapping_delta(
            old_value, new_value, field=field, modified={key}
        )
    elif mode == "upsert":
        added, removed, modified = _osc_mapping_delta(
            old_value, new_value, field=field
        )
        if removed or (added, modified) not in (
            ({key}, set()),
            (set(), {key}),
        ):
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "orchestration ledger changed outside its exact entry",
                details={"field": field, "key": key},
            )
    else:  # pragma: no cover - package programming error
        raise AssertionError(mode)
    assert isinstance(new_value, _OscMapping)
    return (
        (
            old_value.get(key)
            if isinstance(old_value, _OscMapping)
            else None
        ),
        new_value[key],
    )


def _osc_semantic_manager_authorize(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_OPERATOR_AUTHORIZE,
        payload=event_payload,
    )


def _osc_semantic_manager_revoke(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_OPERATOR_REVOKE,
        payload=event_payload,
    )


def _osc_semantic_artifact_record(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_ARTIFACT_RECORD,
        payload=event_payload,
    )


def _osc_semantic_assignment_issue(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    assignment_id = event_payload.get("assignment_id")
    if not isinstance(assignment_id, str) or not assignment_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "assignment issue requires one assignment identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="assignments",
        key=assignment_id,
        mode="add",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("assignment_id") != assignment_id
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "assignment ledger differs from its issued identity",
        )


def _osc_semantic_attempt_abandon(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    attempt_id = event_payload.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment requires one attempt identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="attempts",
        key=attempt_id,
        mode="add",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("state") != "ABANDONED"
        or record.get("node_instance_id")
        != event_payload.get("node_instance_id")
        or record.get("lease_id") != event_payload.get("lease_id")
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment did not record ABANDONED",
        )
    node_instance_id = event_payload.get("node_instance_id")
    old_nodes = old_state.get("node_instances")
    new_nodes = candidate_state.get("node_instances")
    if (
        not isinstance(node_instance_id, str)
        or not isinstance(old_nodes, list)
        or not isinstance(new_nodes, list)
        or len(old_nodes) != len(new_nodes)
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment has no exact node lifecycle binding",
        )
    expected_nodes = _osc_copy.deepcopy(old_nodes)
    expected_node = next(
        (
            node
            for node in expected_nodes
            if isinstance(node, dict)
            and node.get("node_instance_id") == node_instance_id
        ),
        None,
    )
    expected_attempts = (
        expected_node.get("attempts")
        if isinstance(expected_node, dict)
        else None
    )
    if (
        not isinstance(expected_node, dict)
        or expected_node.get("state") != "RUNNING"
        or not isinstance(expected_attempts, list)
        or not expected_attempts
        or not isinstance(expected_attempts[-1], dict)
        or expected_attempts[-1].get("state") != "RUNNING"
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment does not target the current running attempt",
        )
    result_refs = expected_attempts[-1].get("result_refs")
    reference = record.get("reference")
    if (
        not isinstance(result_refs, list)
        or not isinstance(reference, _OscMapping)
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment has no exact diagnostic reference",
        )
    expected_node["state"] = "BLOCKED"
    expected_attempts[-1]["state"] = "BLOCKED"
    result_refs.append(
        {
            "schema": _workflow_state_result_reference_schema,
            "result_id": attempt_id,
            "task_id": old_state.get("task_id"),
            "bundle_sha256": old_state.get("workflow_ref", {}).get(
                "bundle_sha256"
            ),
            "node_instance_id": node_instance_id,
            "attempt": record.get("attempt"),
            "input_sha256": record.get("input_sha256"),
            "output_sha256": reference.get("sha256"),
            "locator": reference.get("locator"),
        }
    )
    if expected_nodes != new_nodes:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "attempt abandonment changed the node lifecycle outside its exact blocked diagnostic",
        )


def _osc_semantic_barrier_close(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_BARRIER,
        payload=event_payload,
    )


def _osc_semantic_barrier_reopen(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    barrier_id = event_payload.get("barrier_id")
    if not isinstance(barrier_id, str) or not barrier_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "barrier reopen requires one barrier identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="barriers",
        key=barrier_id,
        mode="modify",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("status") != "REOPENED"
        or record.get("aggregate") is not None
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "barrier reopen did not clear the exact closed aggregate",
        )


def _osc_semantic_cancellation_request(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    cancellation = after.get("cancellation")
    if (
        not isinstance(cancellation, _OscMapping)
        or cancellation == before.get("cancellation")
        or cancellation.get("requested") is not True
        or tuple(cancellation.get("affected_lease_ids", ()))
        != tuple(event_payload.get("affected_lease_ids", ()))
        or tuple(cancellation.get("uncertain_lease_ids", ()))
        != tuple(
            event_payload.get(
                "lease_ids_requiring_reconciliation", ()
            )
        )
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "cancellation request differs from its exact affected lease set",
        )


def _osc_semantic_dispatch_handoff(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    assignment_id = event_payload.get("assignment_id")
    if not isinstance(assignment_id, str) or not assignment_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "dispatch handoff requires one assignment identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="dispatch",
        key=assignment_id,
        mode="upsert",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("assignment_id") not in {None, assignment_id}
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "dispatch handoff differs from its assignment",
        )


def _osc_semantic_finalization_commit(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    finalization_id = event_payload.get("finalization_id")
    record = after.get("finalization")
    if (
        not isinstance(finalization_id, str)
        or not finalization_id
        or before.get("finalization") is not None
        or not isinstance(record, _OscMapping)
        or record.get("finalization_id") != finalization_id
        or record.get("current") is not True
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "finalization commit is not one current immutable record",
        )


def _osc_semantic_frontier_advance(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    node_instance_id = event_payload.get("node_instance_id")
    if not isinstance(node_instance_id, str) or not node_instance_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "frontier advancement requires one node-instance identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="frontier",
        key=node_instance_id,
        mode="upsert",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("state") != "READY"
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "frontier advancement did not record READY",
        )


def _osc_semantic_integration_capture(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_INTEGRATION_CAPTURE,
        payload=event_payload,
    )


def _osc_semantic_integration_verify(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_INTEGRATION_VERIFY,
        payload=event_payload,
    )


def _osc_semantic_lease_expire(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    lease_id = event_payload.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease expiry requires one lease identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before, after, field="leases", key=lease_id, mode="modify"
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("state") != "EXPIRED"
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease expiry did not record EXPIRED",
        )
    assignments = before.get("assignments")
    affected = {
        str(assignment_id)
        for assignment_id, assignment in (
            assignments.items()
            if isinstance(assignments, _OscMapping)
            else ()
        )
        if isinstance(assignment, _OscMapping)
        and isinstance(
            assignment.get("lease_credential"), _OscMapping
        )
        and assignment["lease_credential"].get("lease_id")
        == lease_id
    }
    old_dispatch = before.get("dispatch")
    new_dispatch = after.get("dispatch")
    _added, _removed, modified = _osc_mapping_delta(
        old_dispatch, new_dispatch, field="dispatch"
    )
    if _added or _removed or not modified.issubset(affected):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
            "lease expiry changed unrelated dispatch records",
        )
    assert isinstance(new_dispatch, _OscMapping)
    if any(
        not isinstance(new_dispatch[key], _OscMapping)
        or new_dispatch[key].get("runtime_status") != "EXPIRED"
        for key in modified
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease expiry dispatch records are not EXPIRED",
        )


def _osc_semantic_lease_issue(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    lease_id = event_payload.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease issue requires one lease identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before, after, field="leases", key=lease_id, mode="add"
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("lease_id") != lease_id
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease ledger differs from its issued identity",
        )


def _osc_semantic_lease_revoke(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    lease_id = event_payload.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease revocation requires one lease identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before, after, field="leases", key=lease_id, mode="modify"
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("state") != "REVOKED"
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "lease revocation did not record REVOKED",
        )


def _osc_semantic_map_expand(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    expansion = after.get("expansion")
    if (
        expansion == before.get("expansion")
        or not isinstance(expansion, _OscMapping)
        or expansion.get("current") is not True
        or not isinstance(event_payload.get("expansion_sha256"), str)
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "map expansion did not bind one current expansion",
        )


def _osc_semantic_map_invalidate(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    old_expansion = before.get("expansion")
    new_expansion = after.get("expansion")
    if (
        not isinstance(old_expansion, _OscMapping)
        or not isinstance(new_expansion, _OscMapping)
        or old_expansion == new_expansion
        or new_expansion.get("current") is not False
        or event_payload.get("phase") not in {"STALE", "RETIRED"}
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "map invalidation did not preserve one stale/retired expansion",
        )


def _osc_semantic_plan_approve(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_PLAN_APPROVE,
        payload=event_payload,
    )


def _osc_semantic_plan_record(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_PLAN_RECORD,
        payload=event_payload,
    )


def _osc_semantic_reconciliation_begin(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_RECONCILE_BEGIN,
        payload=event_payload,
    )


def _osc_semantic_reconciliation_complete(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_RECONCILE_COMPLETE,
        payload=event_payload,
    )


def _osc_semantic_result_accept(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    result_id = event_payload.get("result_id")
    node_instance_id = event_payload.get("node_instance_id")
    if (
        not isinstance(result_id, str)
        or not result_id
        or not isinstance(node_instance_id, str)
        or not node_instance_id
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "result acceptance requires result and node identities",
        )
    _old, record = _osc_authoritative_mapping_change(
        before,
        after,
        field="accepted_results",
        key=result_id,
        mode="add",
    )
    if (
        not isinstance(record, _OscMapping)
        or record.get("current") is not True
        or not isinstance(after.get("current_results"), _OscMapping)
        or after["current_results"].get(node_instance_id) != result_id
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "accepted result does not own the current node result",
        )


def _osc_semantic_result_invalidate(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    result_id = event_payload.get("result_id")
    if not isinstance(result_id, str) or not result_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "result invalidation requires one result identity",
        )
    old_record, new_record = _osc_authoritative_mapping_change(
        before,
        after,
        field="accepted_results",
        key=result_id,
        mode="modify",
    )
    if not isinstance(old_record, _OscMapping) or not isinstance(
        new_record, _OscMapping
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "result invalidation record is malformed",
        )
    expected = _osc_copy.deepcopy(_osc_thaw(old_record))
    assert isinstance(expected, dict)
    expected["current"] = False
    if new_record != expected:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
            "result invalidation may only clear currentness",
        )
    result = old_record.get("result")
    node_instance_id = (
        result.get("node_instance_id")
        if isinstance(result, _OscMapping)
        else None
    )
    old_current = before.get("current_results")
    new_current = after.get("current_results")
    if (
        isinstance(node_instance_id, str)
        and isinstance(old_current, _OscMapping)
        and old_current.get(node_instance_id) == result_id
    ):
        _osc_require_mapping_delta(
            old_current,
            new_current,
            field="current_results",
            removed={node_instance_id},
        )
    else:
        _osc_require_mapping_delta(
            old_current, new_current, field="current_results"
        )
    if after.get("barriers") != before.get("barriers"):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_DELTA_INVALID",
            "result invalidation cannot overload barrier reopening",
        )
    reason = event_payload.get("reason")
    for field in ("integration", "integration_verification", "review"):
        previous = before.get(field)
        current = after.get(field)
        if isinstance(previous, _OscMapping):
            wanted = _osc_copy.deepcopy(_osc_thaw(previous))
            assert isinstance(wanted, dict)
            wanted["current"] = False
            if field == "integration":
                wanted["stale_reason"] = reason
            if current != wanted:
                raise _osc_error(
                    "ORCHESTRATION_CONTROL_DELTA_INVALID",
                    "result invalidation changed downstream evidence outside currentness",
                    details={"field": field},
                )
        elif current is not None:
            raise _osc_error(
                "ORCHESTRATION_CONTROL_DELTA_INVALID",
                "result invalidation created downstream evidence",
                details={"field": field},
            )


def _osc_semantic_retry_request(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    retry_id = event_payload.get("retry_id")
    if not isinstance(retry_id, str) or not retry_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "retry request requires one retry identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before, after, field="retries", key=retry_id, mode="add"
    )
    if not isinstance(record, _OscMapping):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "retry request did not append its exact record",
        )
    node_instance_id = record.get("node_instance_id")
    old_nodes = old_state.get("node_instances")
    new_nodes = candidate_state.get("node_instances")
    if (
        not isinstance(node_instance_id, str)
        or not isinstance(old_nodes, list)
        or not isinstance(new_nodes, list)
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "retry request has no exact node lifecycle binding",
        )
    expected_nodes = _osc_copy.deepcopy(old_nodes)
    expected_node = next(
        (
            node
            for node in expected_nodes
            if isinstance(node, dict)
            and node.get("node_instance_id") == node_instance_id
        ),
        None,
    )
    if (
        not isinstance(expected_node, dict)
        or expected_node.get("state") not in {"BLOCKED", "FAILED"}
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "retry request does not target one blocked or failed node",
        )
    expected_node["state"] = "READY"
    if expected_nodes != new_nodes:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "retry request changed node lifecycle outside its exact ready transition",
        )


def _osc_semantic_review_record(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_REVIEW,
        payload=event_payload,
    )


def _osc_semantic_runtime_stop_record(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_RUNTIME_STOP,
        payload=event_payload,
    )


def _osc_semantic_runtime_recovery_observe(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=ORCHESTRATION_ACTION_RECOVER,
        payload=event_payload,
    )


def _osc_semantic_timeout_record(
    old_state: _OscMapping[str, object],
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> None:
    before, after = _osc_authoritative_orchestration_pair(
        old_state, candidate_state, event_payload
    )
    timeout_id = event_payload.get("timeout_id")
    if not isinstance(timeout_id, str) or not timeout_id:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "timeout recording requires one timeout identity",
        )
    _old, record = _osc_authoritative_mapping_change(
        before, after, field="timeouts", key=timeout_id, mode="add"
    )
    if not isinstance(record, _OscMapping):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_BINDING_INVALID",
            "timeout ledger did not append its exact record",
        )


def _osc_validate_authoritative_operation(
    state: _OscMapping[str, object],
    intent: object,
    selection: object,
    *,
    operation_id: str,
    semantic_contract: str,
    validator: _OscCallable[
        [
            _OscMapping[str, object],
            _OscMapping[str, object],
            _OscMapping[str, object],
        ],
        None,
    ],
) -> OrchestrationActionSemanticCandidate:
    candidate, event_payload = _osc_authoritative_intent_parts(
        state, intent, selection, operation_id=operation_id
    )
    validator(state, candidate, event_payload)
    return _osc_authoritative_candidate(
        candidate,
        event_payload,
        operation_id=operation_id,
        semantic_contract=semantic_contract,
    )


def _osc_validator_manager_authorize(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
        semantic_contract="manager-authorize/v1",
        validator=_osc_semantic_manager_authorize,
    )


def _osc_validator_manager_revoke(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_MANAGER_REVOKE,
        semantic_contract="manager-revoke/v1",
        validator=_osc_semantic_manager_revoke,
    )


def _osc_validator_artifact_record(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_ARTIFACT_RECORD,
        semantic_contract="artifact-record/v1",
        validator=_osc_semantic_artifact_record,
    )


def _osc_validator_assignment_issue(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE,
        semantic_contract="assignment-issue/v1",
        validator=_osc_semantic_assignment_issue,
    )


def _osc_validator_attempt_abandon(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_ATTEMPT_ABANDON,
        semantic_contract="attempt-abandon/v1",
        validator=_osc_semantic_attempt_abandon,
    )


def _osc_validator_barrier_close(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_BARRIER_CLOSE,
        semantic_contract="barrier-close/v1",
        validator=_osc_semantic_barrier_close,
    )


def _osc_validator_barrier_reopen(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_BARRIER_REOPEN,
        semantic_contract="barrier-reopen/v1",
        validator=_osc_semantic_barrier_reopen,
    )


def _osc_validator_cancellation_request(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_CANCELLATION_REQUEST,
        semantic_contract="cancellation-request/v1",
        validator=_osc_semantic_cancellation_request,
    )


def _osc_validator_dispatch_handoff(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_DISPATCH_HANDOFF,
        semantic_contract="dispatch-handoff/v1",
        validator=_osc_semantic_dispatch_handoff,
    )


def _osc_validator_finalization_commit(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_FINALIZATION_COMMIT,
        semantic_contract="finalization-commit/v1",
        validator=_osc_semantic_finalization_commit,
    )


def _osc_validator_frontier_advance(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_FRONTIER_ADVANCE,
        semantic_contract="frontier-advance/v1",
        validator=_osc_semantic_frontier_advance,
    )


def _osc_validator_integration_capture(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_INTEGRATION_CAPTURE,
        semantic_contract="integration-capture/v1",
        validator=_osc_semantic_integration_capture,
    )


def _osc_validator_integration_verify(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_INTEGRATION_VERIFY,
        semantic_contract="integration-verify/v1",
        validator=_osc_semantic_integration_verify,
    )


def _osc_validator_lease_expire(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_LEASE_EXPIRE,
        semantic_contract="lease-expire/v1",
        validator=_osc_semantic_lease_expire,
    )


def _osc_validator_lease_issue(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_LEASE_ISSUE,
        semantic_contract="lease-issue/v1",
        validator=_osc_semantic_lease_issue,
    )


def _osc_validator_lease_revoke(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_LEASE_REVOKE,
        semantic_contract="lease-revoke/v1",
        validator=_osc_semantic_lease_revoke,
    )


def _osc_validator_map_expand(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_MAP_EXPAND,
        semantic_contract="map-expand/v1",
        validator=_osc_semantic_map_expand,
    )


def _osc_validator_map_invalidate(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_MAP_INVALIDATE,
        semantic_contract="map-invalidate/v1",
        validator=_osc_semantic_map_invalidate,
    )


def _osc_validator_plan_approve(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_PLAN_APPROVE,
        semantic_contract="plan-approve/v1",
        validator=_osc_semantic_plan_approve,
    )


def _osc_validator_plan_record(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_PLAN_RECORD,
        semantic_contract="plan-record/v1",
        validator=_osc_semantic_plan_record,
    )


def _osc_validator_reconciliation_begin(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN,
        semantic_contract="reconciliation-begin/v1",
        validator=_osc_semantic_reconciliation_begin,
    )


def _osc_validator_reconciliation_complete(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE,
        semantic_contract="reconciliation-complete/v1",
        validator=_osc_semantic_reconciliation_complete,
    )


def _osc_validator_result_accept(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RESULT_ACCEPT,
        semantic_contract="result-accept/v1",
        validator=_osc_semantic_result_accept,
    )


def _osc_validator_result_invalidate(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RESULT_INVALIDATE,
        semantic_contract="result-invalidate/v1",
        validator=_osc_semantic_result_invalidate,
    )


def _osc_validator_retry_request(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RETRY_REQUEST,
        semantic_contract="retry-request/v1",
        validator=_osc_semantic_retry_request,
    )


def _osc_validator_review_record(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_REVIEW_RECORD,
        semantic_contract="review-record/v1",
        validator=_osc_semantic_review_record,
    )


def _osc_validator_runtime_stop_record(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
        semantic_contract="runtime-stop-record/v1",
        validator=_osc_semantic_runtime_stop_record,
    )


def _osc_validator_runtime_recovery_observe(
    state, intent, selection
):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=(
            ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE
        ),
        semantic_contract="runtime-recovery-observe/v1",
        validator=_osc_semantic_runtime_recovery_observe,
    )


def _osc_validator_timeout_record(state, intent, selection):
    return _osc_validate_authoritative_operation(
        state,
        intent,
        selection,
        operation_id=ORCHESTRATION_OPERATION_TIMEOUT_RECORD,
        semantic_contract="timeout-record/v1",
        validator=_osc_semantic_timeout_record,
    )


_OSC_AUTHORITATIVE_VALIDATORS = {
    ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE: (
        _osc_validator_manager_authorize
    ),
    ORCHESTRATION_OPERATION_MANAGER_REVOKE: (
        _osc_validator_manager_revoke
    ),
    ORCHESTRATION_OPERATION_ARTIFACT_RECORD: (
        _osc_validator_artifact_record
    ),
    ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE: (
        _osc_validator_assignment_issue
    ),
    ORCHESTRATION_OPERATION_ATTEMPT_ABANDON: (
        _osc_validator_attempt_abandon
    ),
    ORCHESTRATION_OPERATION_BARRIER_CLOSE: (
        _osc_validator_barrier_close
    ),
    ORCHESTRATION_OPERATION_BARRIER_REOPEN: (
        _osc_validator_barrier_reopen
    ),
    ORCHESTRATION_OPERATION_CANCELLATION_REQUEST: (
        _osc_validator_cancellation_request
    ),
    ORCHESTRATION_OPERATION_DISPATCH_HANDOFF: (
        _osc_validator_dispatch_handoff
    ),
    ORCHESTRATION_OPERATION_FINALIZATION_COMMIT: (
        _osc_validator_finalization_commit
    ),
    ORCHESTRATION_OPERATION_FRONTIER_ADVANCE: (
        _osc_validator_frontier_advance
    ),
    ORCHESTRATION_OPERATION_INTEGRATION_CAPTURE: (
        _osc_validator_integration_capture
    ),
    ORCHESTRATION_OPERATION_INTEGRATION_VERIFY: (
        _osc_validator_integration_verify
    ),
    ORCHESTRATION_OPERATION_LEASE_EXPIRE: _osc_validator_lease_expire,
    ORCHESTRATION_OPERATION_LEASE_ISSUE: _osc_validator_lease_issue,
    ORCHESTRATION_OPERATION_LEASE_REVOKE: _osc_validator_lease_revoke,
    ORCHESTRATION_OPERATION_MAP_EXPAND: _osc_validator_map_expand,
    ORCHESTRATION_OPERATION_MAP_INVALIDATE: (
        _osc_validator_map_invalidate
    ),
    ORCHESTRATION_OPERATION_PLAN_APPROVE: (
        _osc_validator_plan_approve
    ),
    ORCHESTRATION_OPERATION_PLAN_RECORD: _osc_validator_plan_record,
    ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN: (
        _osc_validator_reconciliation_begin
    ),
    ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE: (
        _osc_validator_reconciliation_complete
    ),
    ORCHESTRATION_OPERATION_RESULT_ACCEPT: _osc_validator_result_accept,
    ORCHESTRATION_OPERATION_RESULT_INVALIDATE: (
        _osc_validator_result_invalidate
    ),
    ORCHESTRATION_OPERATION_RETRY_REQUEST: (
        _osc_validator_retry_request
    ),
    ORCHESTRATION_OPERATION_REVIEW_RECORD: _osc_validator_review_record,
    ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD: (
        _osc_validator_runtime_stop_record
    ),
    ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE: (
        _osc_validator_runtime_recovery_observe
    ),
    ORCHESTRATION_OPERATION_TIMEOUT_RECORD: (
        _osc_validator_timeout_record
    ),
}

if (
    tuple(
        sorted(_OSC_AUTHORITATIVE_VALIDATORS, key=_osc_utf8_sort_key)
    )
    != ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS
    or len(set(_OSC_AUTHORITATIVE_VALIDATORS.values())) != 29
):
    raise RuntimeError(
        "orchestration semantic validator inventory is not exact"
    )

for _osc_operation_id in ORCHESTRATION_AUTHORITATIVE_OPERATION_IDS:
    _osc_identities = _workflow_catalog_repository_semantic_identities(
        _osc_operation_id
    )
    _register_orchestration_action_semantic_validator(
        _osc_operation_id,
        str(_osc_identities["validator_id"]),
        _OSC_AUTHORITATIVE_VALIDATORS[_osc_operation_id],
    )
del _osc_identities, _osc_operation_id


def _osc_build_authoritative_action_result(
    state: _OscMapping[str, object],
    *,
    operation_id: str,
    candidate_state: _OscMapping[str, object],
    event_payload: _OscMapping[str, object],
) -> tuple[OrchestrationActionAdapterResult, dict[str, object]]:
    selection = resolve_catalog_orchestration_action(
        state, operation_id
    )
    bound_payload = {
        **_osc_copy.deepcopy(_osc_thaw(event_payload)),
        "operation_id": operation_id,
        "event_id": selection.event_id,
    }
    intent = OrchestrationActionSemanticIntent(
        operation_id,
        {
            "schema": _OSC_AUTHORITATIVE_INTENT_SCHEMA,
            "candidate_state": _osc_copy.deepcopy(
                _osc_thaw(candidate_state)
            ),
            "event_payload": bound_payload,
        },
    )
    result = build_catalog_orchestration_action_outcome(
        state, operation_id, intent
    )
    if result.selection != selection:
        raise _osc_error(
            "ORCHESTRATION_ACTION_SELECTION_CHANGED",
            "orchestration action selection changed during semantic validation",
            details={"operation_id": operation_id},
        )
    return result, bound_payload


def _osc_authoritative_invocation(
    result: OrchestrationActionAdapterResult,
    event_payload: _OscMapping[str, object],
    *,
    action_parameters: _OscOptional[_OscMapping[str, object]] = None,
    confirm_intent: _OscOptional[str] = None,
) -> WorkflowActionInvocation:
    selection = result.selection
    parameters = (
        _osc_copy.deepcopy(_osc_thaw(action_parameters))
        if action_parameters is not None
        else _osc_copy.deepcopy(_osc_thaw(event_payload))
    )
    catalog_bindings = {
        "operation_id": selection.operation_id,
        "event_id": selection.event_id,
    }
    for key, expected in catalog_bindings.items():
        supplied = parameters.get(key)
        if supplied is not None and supplied != expected:
            raise _osc_error(
                "ORCHESTRATION_ACTION_CATALOG_BINDING_INVALID",
                "action parameters conflict with the sealed orchestration catalog",
                details={
                    "operation_id": selection.operation_id,
                    "field": key,
                    "expected": expected,
                    "actual": supplied,
                },
            )
        parameters[key] = expected
    return WorkflowActionInvocation(
        kind="node",
        public_command=selection.public_command_id,
        selector=selection.public_selector_value,
        action_outcome=result.action_outcome,
        action_parameters=parameters,
        evidence={
            "schema": (
                "dev-flow-orchestration-action-invocation-evidence/v1"
            ),
            "operation_id": selection.operation_id,
            "action_id": selection.action_id,
            "validator_id": selection.validator_id,
            "event_id": selection.event_id,
            "write_set_id": selection.write_set_id,
            "effect_ids": list(selection.effect_ids),
            "binding_sha256": result.binding_sha256,
            "delta_sha256": result.delta_sha256,
        },
        confirm_intent=confirm_intent,
    )


def _osc_authoritative_effect_bindings(
    state: _OscMapping[str, object],
    invocation: WorkflowActionInvocation,
    result: OrchestrationActionAdapterResult,
    effect_inputs: _OscOptional[_OscMapping[str, object]],
) -> tuple[WorkflowActionEffectBinding, ...]:
    edge = resolve_v3_node_action_edge(
        state,
        invocation.public_command,
        selector=invocation.selector,
    )
    effects = edge.get("effects")
    if not isinstance(effects, (tuple, list)):
        raise _osc_error(
            "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
            "selected orchestration edge has no typed effects",
        )
    dispatch_effects = tuple(
        effect
        for effect in effects
        if isinstance(effect, _OscMapping)
        and effect.get("dispatch") == "single-dispatch"
    )
    expected_ids = tuple(
        str(effect.get("id")) for effect in dispatch_effects
    )
    supplied = effect_inputs or {}
    if (
        not isinstance(supplied, _OscMapping)
        or set(supplied) != set(expected_ids)
        or any(
            effect_id not in result.selection.effect_ids
            for effect_id in expected_ids
        )
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
            "effect inputs must exactly cover selected dispatch effects",
            details={
                "operation_id": result.selection.operation_id,
                "expected_effect_ids": list(expected_ids),
                "actual_effect_ids": sorted(
                    (str(key) for key in supplied),
                    key=_osc_utf8_sort_key,
                ),
            },
        )
    bindings: list[WorkflowActionEffectBinding] = []
    for effect_id in expected_ids:
        value = supplied[effect_id]
        if (
            not isinstance(value, _OscMapping)
            or set(value)
            != {"attempt_id", "kind", "safe_inputs", "scopes"}
            or not isinstance(value.get("scopes"), _OscMapping)
            or not isinstance(value.get("safe_inputs"), _OscMapping)
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                "dispatch effect input has no exact typed shape",
                details={"effect_id": effect_id},
            )
        bindings.append(
            WorkflowActionEffectBinding(
                effect_id=effect_id,
                kind=str(value["kind"]),
                scope_kinds=tuple(
                    str(item)
                    for item in next(
                        effect
                        for effect in dispatch_effects
                        if effect.get("id") == effect_id
                    ).get("scopes", ())
                ),
                scopes=_osc_copy.deepcopy(
                    _osc_thaw(value["scopes"])
                ),
                safe_inputs=_osc_copy.deepcopy(
                    _osc_thaw(value["safe_inputs"])
                ),
                attempt_id=str(value["attempt_id"]),
            )
        )
    return tuple(bindings)


def _osc_effect_authorized_parameters(
    parameters: _OscMapping[str, object],
    bindings: _OscSequence[WorkflowActionEffectBinding],
) -> dict[str, object]:
    """Bind exact typed effect scopes into the kernel path request."""

    key = "_catalog_effect_authorization"
    result = _osc_copy.deepcopy(_osc_thaw(parameters))
    if key in result:
        raise _osc_error(
            "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
            "catalog effect authorization is controller-owned",
        )
    if bindings:
        result[key] = [
            {
                "effect_id": binding.effect_id,
                "scope_kinds": list(binding.scope_kinds),
                "scopes": _osc_copy.deepcopy(
                    _osc_thaw(binding.scopes)
                ),
                "safe_input_sha256": _osc_digest(
                    binding.safe_inputs
                ),
                "attempt_id": binding.attempt_id,
            }
            for binding in bindings
        ]
    return result


def _osc_apply_catalog_orchestration_delta(
    state: _OscMapping[str, object],
    delta: _OscMapping[str, object],
    selection: OrchestrationActionSelection,
) -> dict[str, object]:
    """Apply one business delta under the catalog's explicit write set."""

    normalized = _orchestration_action_adapter_normalize_delta(
        delta,
        allowed_roots=selection.allowed_write_roots,
    )
    candidate = _osc_copy.deepcopy(_osc_thaw(state))
    for pointer, value in normalized["set"].items():
        _transition_engine_pointer_set(
            candidate,
            str(pointer),
            _osc_copy.deepcopy(_osc_thaw(value)),
        )
    for pointer in sorted(
        normalized["remove"],
        key=lambda value: (str(value).count("/"), str(value)),
        reverse=True,
    ):
        _transition_engine_pointer_remove(candidate, str(pointer))
    observed = _workflow_transition_exact_state_delta(
        state, candidate
    )
    if observed != _osc_thaw(normalized):
        raise _osc_error(
            "ORCHESTRATION_ACTION_SEMANTIC_DRIFT",
            "catalog business delta no longer has its exact pointer effect",
            details={"operation_id": selection.operation_id},
        )
    return candidate


def _osc_execute_authoritative_transaction(
    old_state: dict[str, object],
    candidate_state: _OscMapping[str, object],
    task_dir: _OscPath,
    *,
    operation_id: str,
    event_payload: _OscMapping[str, object],
    authorization: WorkflowActionAuthorization,
    action_parameters: _OscOptional[
        _OscMapping[str, object]
    ] = None,
    effect_inputs: _OscOptional[_OscMapping[str, object]] = None,
    execution_id: _OscOptional[str] = None,
    dispatcher: _OscOptional[_OscCallable[[object], object]] = None,
    runtime_release_adapter: _OscOptional[
        _OscCallable[[object], object]
    ] = None,
    runtime_observer: _OscOptional[
        _OscCallable[[object], object]
    ] = None,
    target_execution_id: _OscOptional[str] = None,
    control_action_id: _OscOptional[str] = None,
    failure_hook: _OscOptional[_OscCallable[[str], None]] = None,
) -> WorkflowActionTransactionResult:
    """Compose one catalog operation without minting a second authority."""

    result, bound_payload = _osc_build_authoritative_action_result(
        old_state,
        operation_id=operation_id,
        candidate_state=candidate_state,
        event_payload=event_payload,
    )
    unbound_seed = _osc_authoritative_invocation(
        result,
        bound_payload,
        action_parameters=action_parameters,
    )
    effect_bindings = _osc_authoritative_effect_bindings(
        old_state, unbound_seed, result, effect_inputs
    )
    if effect_bindings:
        if (
            not isinstance(execution_id, str)
            or not execution_id
            or not callable(dispatcher)
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_EFFECT_INPUT_REQUIRED",
                "dispatching orchestration action requires execution identity and adapter",
                details={"operation_id": operation_id},
            )
    elif (
        effect_inputs
        or execution_id is not None
        or dispatcher is not None
        or runtime_release_adapter is not None
        or runtime_observer is not None
        or target_execution_id is not None
        or control_action_id is not None
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_EFFECT_INPUT_FORBIDDEN",
            "effect-free orchestration action cannot carry dispatch inputs",
            details={"operation_id": operation_id},
        )
    seed = _osc_authoritative_invocation(
        result,
        bound_payload,
        action_parameters=_osc_effect_authorized_parameters(
            unbound_seed.action_parameters, effect_bindings
        ),
    )
    preview = preview_v3_workflow_action_transaction(
        old_state,
        seed,
        authorization=authorization,
        task_dir=task_dir,
    )
    intent_id = preview.intent.get("intent_id")
    if not isinstance(intent_id, str) or not intent_id:
        raise _osc_error(
            "ORCHESTRATION_ACTION_PREVIEW_INVALID",
            "orchestration action preview returned no confirmation identity",
            details={"operation_id": operation_id},
        )
    invocation = _osc_authoritative_invocation(
        result,
        bound_payload,
        action_parameters=seed.action_parameters,
        confirm_intent=intent_id,
    )

    def current_invocation_factory(
        current: dict[str, object],
    ) -> WorkflowActionInvocation:
        def stable_selection(value: object) -> dict[str, object]:
            fields = getattr(value, "__dataclass_fields__", {})
            return {
                str(field): _osc_copy.deepcopy(
                    getattr(value, str(field))
                )
                for field in fields
                if field != "expected_revision"
            }

        current_selection = resolve_catalog_orchestration_action(
            current, operation_id
        )
        if stable_selection(current_selection) != stable_selection(
            result.selection
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_CATALOG_DRIFT",
                "orchestration action selection changed during scoped revalidation",
                details={"operation_id": operation_id},
            )
        manager_rebase_preauthorization_v1(
            current,
            event_type=current_selection.canonical_event,
        )
        current_prepared = _manager_engine_evaluation_state_v1(
            current,
            event_type=current_selection.canonical_event,
        )
        if not isinstance(current_prepared, dict):
            raise _osc_error(
                "MANAGER_PREAUTHORIZATION_REQUIRED",
                "scoped orchestration revalidation has no nonce-prepared current state",
                details={"operation_id": operation_id},
            )
        current_candidate = _osc_apply_catalog_orchestration_delta(
            current_prepared,
            result.action_outcome.proposed_state_delta,
            current_selection,
        )
        current_result, current_payload = (
            _osc_build_authoritative_action_result(
                current,
                operation_id=operation_id,
                candidate_state=current_candidate,
                event_payload=bound_payload,
            )
        )
        if (
            stable_selection(current_result.selection)
            != stable_selection(result.selection)
            or current_result.delta_sha256 != result.delta_sha256
            or (
                current_result.action_outcome.proposed_state_delta
                != result.action_outcome.proposed_state_delta
            )
            or current_payload != bound_payload
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_SEMANTIC_DRIFT",
                "fresh orchestration validation differs from the durable semantic operation",
                details={"operation_id": operation_id},
            )
        current_seed = _osc_authoritative_invocation(
            result,
            bound_payload,
            action_parameters=seed.action_parameters,
        )
        current_preview = preview_v3_workflow_action_transaction(
            current,
            current_seed,
            authorization=authorization,
        )
        current_intent_id = current_preview.intent.get("intent_id")
        if (
            not isinstance(current_intent_id, str)
            or not current_intent_id
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_PREVIEW_INVALID",
                "latest-state orchestration preview returned no confirmation identity",
                details={"operation_id": operation_id},
            )
        return _osc_authoritative_invocation(
            result,
            bound_payload,
            action_parameters=seed.action_parameters,
            confirm_intent=current_intent_id,
        )

    launched: list[WorkflowActionRuntimeBinding] = []

    def dispatch_and_capture(context: object) -> object:
        assert dispatcher is not None
        held = {
            str(_OscPath(item).resolve(strict=False))
            for item in _HELD_LOCK_DIRECTORIES.get()
        }
        forbidden = {
            str(task_dir.resolve(strict=False)),
            str(task_dir.parent.parent.resolve(strict=False)),
        }
        if held.intersection(forbidden):
            raise _osc_error(
                "ORCHESTRATION_ACTION_DISPATCH_LOCK_HELD",
                "orchestration dispatcher cannot run under task or workspace-registry lock",
                details={
                    "operation_id": operation_id,
                    "forbidden_lock_directories": sorted(
                        held.intersection(forbidden),
                        key=_osc_utf8_sort_key,
                    ),
                },
            )
        dispatched = dispatcher(context)
        if type(dispatched) is WorkflowActionRuntimeLaunch:
            launched.append(dispatched.binding)
        return dispatched

    transaction = execute_v3_workflow_action_transaction(
        old_state,
        task_dir,
        invocation,
        authorization=authorization,
        effect_bindings=(
            effect_bindings if effect_bindings else None
        ),
        execution_id=execution_id,
        dispatcher=(
            dispatch_and_capture if dispatcher is not None else None
        ),
        current_invocation_factory=(
            current_invocation_factory
            if effect_bindings
            else None
        ),
        target_execution_id=target_execution_id,
        control_action_id=control_action_id,
        failure_hook=failure_hook,
    )
    if transaction.status != "RUNTIME_BOUND_AWAITING_RELEASE":
        if (
            runtime_release_adapter is not None
            or runtime_observer is not None
        ):
            raise _osc_error(
                "ORCHESTRATION_ACTION_RUNTIME_LIFECYCLE_FORBIDDEN",
                "non-handoff operation cannot carry runtime lifecycle adapters",
                details={"operation_id": operation_id},
            )
        return transaction
    if (
        len(launched) != 1
        or not callable(runtime_release_adapter)
        or not callable(runtime_observer)
        or not isinstance(execution_id, str)
    ):
        raise _osc_error(
            "ORCHESTRATION_ACTION_RUNTIME_LIFECYCLE_REQUIRED",
            "handoff operation requires exact release and observation adapters",
            details={"operation_id": operation_id},
        )
    binding = launched[0]
    release_v3_workflow_action_runtime(
        task_dir,
        binding,
        authorization=authorization,
        release_adapter=runtime_release_adapter,
        failure_hook=failure_hook,
    )
    observe_v3_workflow_action_effect(
        task_dir,
        binding.execution_id,
        binding.effect_id,
        authorization=authorization,
        observer=runtime_observer,
        runtime_binding=binding,
        failure_hook=failure_hook,
    )
    return _workflow_tx_finalize_verified(
        task_dir,
        execution_id,
        invocation,
        authorization,
        current_invocation_factory=current_invocation_factory,
        runtime_bindings={binding.effect_id: binding},
        dispatcher_invocations=transaction.dispatcher_invocations,
        failure_hook=failure_hook,
    )


def _osc_single_dispatch_effect_inputs(
    selection: object,
    *,
    kind: str,
    scopes: _OscMapping[str, object],
    safe_inputs: _OscMapping[str, object],
    attempt_id: str,
) -> dict[str, object]:
    effect_ids = tuple(getattr(selection, "effect_ids", ()))
    if len(effect_ids) != 1:
        raise _osc_error(
            "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
            "controller operation requires exactly one catalog effect",
            details={
                "operation_id": getattr(
                    selection, "operation_id", None
                ),
                "effect_ids": list(effect_ids),
            },
        )
    return {
        str(effect_ids[0]): {
            "attempt_id": attempt_id,
            "kind": kind,
            "safe_inputs": _osc_copy.deepcopy(
                _osc_thaw(safe_inputs)
            ),
            "scopes": _osc_copy.deepcopy(_osc_thaw(scopes)),
        }
    }


def _osc_effect_scopes(
    *,
    repository_ids: _OscSequence[str] = (),
    node_ids: _OscSequence[str] = (),
    worktree_ids: _OscSequence[str] = (),
    lease_ids: _OscSequence[str] = (),
    paths: _OscSequence[str] = (),
    external_resources: _OscSequence[str] = (),
) -> dict[str, object]:
    def normalized(values: _OscSequence[str]) -> list[str]:
        return sorted(set(values), key=_osc_utf8_sort_key)

    return {
        "repository_ids": normalized(repository_ids),
        "node_ids": normalized(node_ids),
        "worktree_ids": normalized(worktree_ids),
        "lease_ids": normalized(lease_ids),
        "paths": normalized(paths),
        "external_resources": normalized(external_resources),
    }


def _osc_quiesced_effect_observation(
    context: object,
    *,
    receipt_facts: _OscMapping[str, object],
) -> WorkflowActionEffectObservation:
    if type(context) is not WorkflowActionDispatchContext:
        raise _osc_error(
            "ORCHESTRATION_ACTION_DISPATCH_CONTEXT_INVALID",
            "controller effect requires the exact claimed dispatch context",
        )
    plan = context.plan
    receipt_sha256 = semantic_sha256(
        b"dev-flow-orchestration-effect-observation-v1\0",
        {
            "task_id": plan.task_id,
            "execution_id": plan.execution_id,
            "effect_id": plan.effect_id,
            "claim_id": plan.claim_id,
            "attempt_id": plan.attempt_id,
            "facts": _osc_copy.deepcopy(
                _osc_thaw(receipt_facts)
            ),
        },
    )
    return WorkflowActionEffectObservation(
        task_id=plan.task_id,
        execution_id=plan.execution_id,
        effect_id=plan.effect_id,
        claim_id=plan.claim_id,
        attempt_id=plan.attempt_id,
        settlement="QUIESCED",
        receipt_sha256=receipt_sha256,
    )


def _osc_operator_workflow_authorization(
    state: _OscMapping[str, object],
    *,
    operation_id: str,
    principal: object,
    request_nonce_sha256: str,
    authorization_facts: _OscMapping[str, object],
) -> WorkflowActionAuthorization:
    parsed = validate_agent_principal(principal)
    if parsed.role != "operator":
        raise _osc_error(
            "MANAGER_REGISTRY_OPERATOR_REQUIRED",
            "manager registry action requires the local operator principal",
        )
    orchestration = _osc_state_copy(state)
    capabilities = orchestration["manager_capabilities"]
    principal_payload = parsed.as_dict()
    return WorkflowActionAuthorization(
        kind="operator",
        authorization_sha256=semantic_sha256(
            b"dev-flow-orchestration-operator-authorization-v1\0",
            {
                "operation_id": operation_id,
                "task_id": state.get("task_id"),
                "revision": state.get("revision"),
                "principal": principal_payload,
                "facts": _osc_copy.deepcopy(
                    _osc_thaw(authorization_facts)
                ),
            },
        ),
        capability_sha256=None,
        request_nonce_sha256=request_nonce_sha256,
        principal=(
            "operator:"
            + str(parsed.session_id)
            + ":"
            + _osc_digest(principal_payload)
        ),
        ownership_sha256=semantic_sha256(
            b"dev-flow-orchestration-operator-ownership-v1\0",
            {
                "task_id": state.get("task_id"),
                "principal": principal_payload,
            },
        ),
        registry_state_sha256=semantic_sha256(
            b"dev-flow-orchestration-manager-registry-state-v1\0",
            capabilities,
        ),
        reauthenticate=lambda: None,
    )


def _osc_resolve_v3_bundle(
    state: _OscMapping[str, object],
) -> object:
    _osc_require_v3(state)
    try:
        resolve_loaded_task_workflow(state, purpose="mutation")
        workflow_ref = state.get("workflow_ref")
        if not isinstance(workflow_ref, _OscMapping):
            raise _osc_error(
                "WORKFLOW_REF_REQUIRED",
                "schema-v3 task has no pinned workflow reference",
            )
        bundle = workflow_runtime_services().catalog.resolve_identity(
            str(workflow_ref.get("bundle_sha256"))
        )
        validate_v3_task_state_against_bundle(state, bundle)
        return bundle
    except Exception as exc:
        if isinstance(exc, FlowError):
            raise
        raise _osc_translate(exc) from exc


def _osc_resolve_multi_bundle(
    state: _OscMapping[str, object],
) -> object:
    bundle = _osc_resolve_v3_bundle(state)
    if state.get("execution_profile") != "multi-repository":
        raise _osc_error(
            "ORCHESTRATION_MULTI_PROFILE_REQUIRED",
            "orchestration service accepts only pinned multi-repository tasks",
            details={"execution_profile": state.get("execution_profile")},
        )
    return bundle


def _osc_evaluate_control_mutation(
    old_state: dict[str, object],
    candidate_state: dict[str, object],
    *,
    operation_id: str,
    event_type: str,
    payload: _OscMapping[str, object],
) -> _OscAuthorizedControlMutation:
    policy = _osc_control_write_policy.get(operation_id)
    expected_event_type = _osc_control_event_types.get(operation_id)
    if policy is None or expected_event_type is None:
        raise _osc_error(
            "ORCHESTRATION_OPERATION_UNSUPPORTED",
            "orchestration operation is outside the package-owned control set",
            details={"operation_id": operation_id},
        )
    if event_type != expected_event_type:
        raise _osc_error(
            "ORCHESTRATION_EVENT_MISMATCH",
            "orchestration event does not match its fixed operation policy",
            details={
                "operation_id": operation_id,
                "expected": expected_event_type,
                "actual": event_type,
            },
        )
    bundle_resolver = (
        _osc_resolve_v3_bundle
        if operation_id
        in {
            ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
            ORCHESTRATION_OPERATION_MANAGER_REVOKE,
        }
        else _osc_resolve_multi_bundle
    )
    bundle = bundle_resolver(old_state)
    bundle_resolver(candidate_state)
    if (
        old_state.get("task_id") != candidate_state.get("task_id")
        or old_state.get("revision") != candidate_state.get("revision")
        or old_state.get("status") != candidate_state.get("status")
        or old_state.get("workflow_ref")
        != candidate_state.get("workflow_ref")
        or old_state.get("node_instances")
        != candidate_state.get("node_instances")
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_OUT_OF_SCOPE",
            "control mutation changed task, revision, workflow, status, or node lifecycle",
            details={"operation_id": operation_id},
        )
    metadata = getattr(bundle, "repository_orchestration", None)
    operation_ids = (
        metadata.get("operation_ids")
        if isinstance(metadata, _OscMapping)
        else ()
    )
    if (
        operation_id
        not in {ORCHESTRATION_OPERATOR_AUTHORIZE, ORCHESTRATION_OPERATOR_REVOKE}
        and operation_id not in operation_ids
    ):
        raise _osc_error(
            "ORCHESTRATION_OPERATION_NOT_DECLARED",
            "operation is absent from the pinned bundle controller surface",
            details={"operation_id": operation_id},
        )
    normalized_old = _osc_copy.deepcopy(old_state)
    normalized_old["orchestration"] = _osc_state_copy(normalized_old)
    differences = tuple(
        sorted(
            json_pointer_diff(normalized_old, candidate_state),
            key=lambda item: item.encode("utf-8"),
        )
    )
    unexpected = [
        pointer
        for pointer in differences
        if not any(_osc_path_is_within(pointer, root) for root in policy)
    ]
    if unexpected:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_OUT_OF_SCOPE",
            "control mutation exceeded its package-owned write policy",
            details={
                "operation_id": operation_id,
                "unexpected_paths": unexpected,
                "allowed_roots": list(policy),
            },
        )
    if not differences:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_NO_CHANGE",
            "control mutation produced no durable state change",
            details={"operation_id": operation_id},
        )
    _osc_validate_control_semantics(
        old_state,
        candidate_state,
        operation_id=operation_id,
        payload=payload,
    )
    return _OscAuthorizedControlMutation(
        operation_id=operation_id,
        event_type=event_type,
        task_id=str(old_state["task_id"]),
        expected_revision=int(old_state["revision"]),
        candidate_sha256=_sha256_contract(candidate_state),
        changed_pointers=differences,
    )


def _osc_commit_control_event(
    old_state: dict[str, object],
    candidate_state: dict[str, object],
    task_dir: _OscPath,
    event_type: str,
    payload: dict[str, object],
    *,
    operation_id: str,
) -> dict[str, object]:
    task_lock, workspace_lock, _ownership_lock = (
        workflow_runtime_services().locks.workflow_transition_locks(
            old_state
        )
    )
    if not task_lock or not workspace_lock:
        raise _osc_error(
            "ORCHESTRATION_CONTROL_LOCK_REQUIRED",
            "control mutation requires task and workspace locks",
            details={
                "task_lock_held": task_lock,
                "workspace_lock_held": workspace_lock,
            },
        )
    persisted = _read_task_state_structural_snapshot(
        task_dir / "state.json"
    )
    if _sha256_contract(persisted) != _sha256_contract(old_state):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_STALE_STATE",
            "control mutation old state is not the committed snapshot",
            details={
                "expected_revision": old_state.get("revision"),
                "persisted_revision": persisted.get("revision"),
            },
        )
    authorization = _osc_evaluate_control_mutation(
        old_state,
        candidate_state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    if authorization.candidate_sha256 != _sha256_contract(
        candidate_state
    ):
        raise _osc_error(
            "ORCHESTRATION_CONTROL_CANDIDATE_CHANGED",
            "control mutation changed after authorization",
        )
    return _persist_state_transaction(
        old_state,
        candidate_state,
        task_dir,
        event_type,
        payload,
    )


@_osc_contextlib.contextmanager
def _osc_locked_current_state(
    task_id: str,
    data_dir: object,
    *,
    require_multi: bool = True,
) -> _OscIterator[tuple[_OscPath, dict[str, object]]]:
    task_dir = _task_dir(task_id, data_dir)
    with _task_lock(task_dir):
        state_path = task_dir / "state.json"
        state = _read_task_state_structural_snapshot(state_path)
        _validate_loaded_state_for_mutation(state_path, state)
        state = _finish_loaded_state(state_path, state)
        if require_multi:
            _osc_resolve_multi_bundle(state)
        else:
            _osc_resolve_v3_bundle(state)
        with _workspace_registry_lock(resolve_data_dir(data_dir)):
            yield task_dir, state


def _osc_receipt(
    event: _OscMapping[str, object],
    *,
    authorization_id: _OscOptional[str],
    payload: _OscMapping[str, object],
) -> OrchestrationCommitReceipt:
    return OrchestrationCommitReceipt(
        task_id=str(event["task_id"]),
        revision=int(event["revision"]),
        event_id=str(event["event_id"]),
        event_type=str(event["type"]),
        authorization_id=authorization_id,
        payload=_osc_copy.deepcopy(_osc_thaw(payload)),
    )


def _osc_result_event_id(
    task_dir: _OscPath,
    result_id: str,
    fallback: str,
) -> str:
    try:
        events = _osc_read_bounded_events(task_dir)
    except FlowError:
        return fallback
    matches = []
    for event in events:
        if (
            event.get("type") == "orchestration_result_accepted"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("result_id") == result_id
            and isinstance(event.get("event_id"), str)
        ):
            matches.append(str(event["event_id"]))
    if len(matches) == 1:
        return matches[0]
    return fallback


def _osc_read_bounded_events(
    task_dir: _OscPath,
) -> tuple[dict[str, object], ...]:
    path = task_dir / "events.jsonl"
    try:
        metadata = path.lstat()
        if (
            not _osc_stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > _OSC_EVENT_LOG_MAX_BYTES
        ):
            raise _osc_error(
                "ORCHESTRATION_EVENT_LOG_INVALID",
                "event log is not one bounded regular file",
            )
        flags = _osc_os.O_RDONLY
        if hasattr(_osc_os, "O_NOFOLLOW"):
            flags |= _osc_os.O_NOFOLLOW
        descriptor = _osc_os.open(path, flags)
    except FlowError:
        raise
    except OSError as exc:
        raise _osc_error(
            "ORCHESTRATION_EVENT_RECEIPT_MISSING",
            "the committed orchestration event could not be read",
        ) from exc
    events: list[dict[str, object]] = []
    try:
        opened = _osc_os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or not _osc_stat.S_ISREG(opened.st_mode)
            or opened.st_size > _OSC_EVENT_LOG_MAX_BYTES
        ):
            raise _osc_error(
                "ORCHESTRATION_EVENT_LOG_INVALID",
                "event log identity changed before it was read",
            )
        with _osc_os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            observed = 0
            while True:
                line = stream.readline(_OSC_EVENT_LINE_MAX_BYTES + 1)
                if not line:
                    break
                observed += len(line)
                if (
                    len(line) > _OSC_EVENT_LINE_MAX_BYTES
                    or observed > _OSC_EVENT_LOG_MAX_BYTES
                    or len(events) >= _OSC_EVENT_LOG_MAX_RECORDS
                    or not line.endswith(b"\n")
                ):
                    raise _osc_error(
                        "ORCHESTRATION_EVENT_LOG_OVERSIZED",
                        "event log exceeds its bounded streaming contract",
                    )
                try:
                    event = _osc_json.loads(
                        line[:-1].decode("utf-8", "strict")
                    )
                except (UnicodeDecodeError, ValueError) as exc:
                    raise _osc_error(
                        "ORCHESTRATION_EVENT_LOG_INVALID",
                        "event log contains a malformed record",
                    ) from exc
                if not isinstance(event, dict):
                    raise _osc_error(
                        "ORCHESTRATION_EVENT_LOG_INVALID",
                        "event log record must be an object",
                    )
                events.append(event)
        final = path.lstat()
        if (
            final.st_dev != metadata.st_dev
            or final.st_ino != metadata.st_ino
            or final.st_size != observed
        ):
            raise _osc_error(
                "ORCHESTRATION_EVENT_LOG_CHANGED",
                "event log changed while it was read",
            )
    finally:
        if descriptor >= 0:
            _osc_os.close(descriptor)
    return tuple(events)


def _osc_committed_event(
    task_dir: _OscPath,
    *,
    task_id: str,
    event_type: str,
    payload_key: str,
    payload_value: object,
    expected_event_id: object = None,
    expected_revision: object = None,
    expected_authorization_id: object = None,
    expected_transaction_id: object = None,
    expected_execution_id: object = None,
    expected_receipt_sha256: object = None,
) -> _OscMapping[str, object]:
    matches = []
    for event in _osc_read_bounded_events(task_dir):
        payload = event.get("payload")
        execution = (
            payload.get("execution")
            if isinstance(payload, dict)
            else None
        )
        if (
            event.get("task_id") == task_id
            and event.get("type") == event_type
            and isinstance(payload, dict)
            and payload.get(payload_key) == payload_value
            and isinstance(event.get("event_id"), str)
            and isinstance(event.get("revision"), int)
            and isinstance(event.get("previous_revision"), int)
            and (
                expected_event_id is None
                or event.get("event_id") == expected_event_id
            )
            and (
                expected_revision is None
                or event.get("revision") == expected_revision
            )
            and (
                expected_authorization_id is None
                or payload.get("manager_authorization_id")
                == expected_authorization_id
            )
            and (
                expected_transaction_id is None
                or event.get("transaction_id")
                == expected_transaction_id
            )
            and (
                expected_execution_id is None
                or (
                    isinstance(execution, dict)
                    and execution.get("execution_id")
                    == expected_execution_id
                )
            )
            and (
                expected_receipt_sha256 is None
                or (
                    isinstance(execution, dict)
                    and execution.get("receipt_sha256")
                    == expected_receipt_sha256
                )
            )
        ):
            matches.append(event)
    if len(matches) != 1:
        raise _osc_error(
            (
                "ORCHESTRATION_EVENT_RECEIPT_AMBIGUOUS"
                if len(matches) > 1
                else "ORCHESTRATION_EVENT_RECEIPT_MISSING"
            ),
            "the committed orchestration event is not uniquely and exactly bound",
            details={
                "event_type": event_type,
                "payload_key": payload_key,
                "payload_value": payload_value,
                "match_count": len(matches),
            },
        )
    return matches[0]


def _osc_validate_replay_caller(
    *,
    task_id: str,
    request: object,
    principal: object,
    action_id: str,
    orchestration: _OscMapping[str, object],
    authorization_id: object,
) -> tuple[object, object]:
    parsed_request = validate_manager_capability_request(request)
    caller = validate_agent_principal(principal)
    if (
        caller.role != "manager"
        or caller.session_id != parsed_request.manager_session_id
        or parsed_request.task_id != task_id
        or parsed_request.action_id != action_id
    ):
        raise _osc_error(
            "ORCHESTRATION_RECEIPT_RECOVERY_DENIED",
            "only the bound manager may recover an orchestration receipt",
        )
    capabilities = orchestration.get("manager_capabilities")
    verifier = (
        capabilities.get(parsed_request.capability_id)
        if isinstance(capabilities, _OscMapping)
        else None
    )
    if (
        not isinstance(verifier, _OscMapping)
        or verifier.get("manager_session_id")
        != parsed_request.manager_session_id
        or verifier.get("task_id") != task_id
    ):
        raise _osc_error(
            "MANAGER_CAPABILITY_UNKNOWN",
            "manager capability verifier is absent or revoked",
            details={"capability_id": parsed_request.capability_id},
        )
    fingerprint = manager_request_fingerprint(parsed_request)
    expected_authorization_id = (
        "manager-authorization:"
        + _authority_digest(
            _authority_authorization_domain,
            {
                "schema": MANAGER_AUTHORIZATION_SCHEMA,
                "capability_id": parsed_request.capability_id,
                "task_id": parsed_request.task_id,
                "manager_session_id": (
                    parsed_request.manager_session_id
                ),
                "action_id": parsed_request.action_id,
                "expected_revision": (
                    parsed_request.expected_revision
                ),
                "request_fingerprint_sha256": fingerprint,
            },
        )
    )
    used_nonces = verifier.get("used_request_nonce_sha256s")
    nonce_digest = manager_request_nonce_digest(parsed_request)
    if (
        authorization_id != expected_authorization_id
        or not isinstance(used_nonces, (list, tuple))
        or nonce_digest not in used_nonces
    ):
        raise _osc_error(
            "ORCHESTRATION_RECEIPT_RECOVERY_DENIED",
            "receipt recovery request does not match the committed request identity",
        )
    return parsed_request, caller


def _osc_runtime_reservation_target(
    task_dir: _OscPath,
    *,
    task_id: str,
    lease_id: str,
    control_action_id: str,
) -> str:
    if control_action_id == ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD:
        control_field = "stop_action_id"
    elif (
        control_action_id
        == ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE
    ):
        control_field = "reconcile_action_id"
    else:
        raise _osc_error(
            "ORCHESTRATION_RUNTIME_RESERVATION_CONTROL_INVALID",
            "runtime reservation target accepts only a declared stop or reconciliation-complete action",
            details={"control_action_id": control_action_id},
        )
    index = ActionExecutionStore(task_dir).read_index(
        expected_task_id=task_id
    )
    matches: list[str] = []
    for entry in index["entries"]:
        reservation = entry.get("runtime_reservation")
        if (
            entry.get("entry_kind") == "runtime-reservation"
            and isinstance(reservation, _OscMapping)
            and reservation.get("phase") == "ACTIVE"
            and reservation.get("lease_id") == lease_id
            and reservation.get(control_field)
            == control_action_id
            and isinstance(entry.get("execution_id"), str)
        ):
            matches.append(str(entry["execution_id"]))
    if len(matches) != 1:
        raise _osc_error(
            "ORCHESTRATION_RUNTIME_RESERVATION_TARGET_INVALID",
            "target control requires one exact active runtime reservation",
            details={
                "lease_id": lease_id,
                "control_action_id": control_action_id,
                "match_count": len(matches),
            },
        )
    return matches[0]


def _osc_release_runtime_reservation_target(
    task_dir: _OscPath,
    *,
    task_id: str,
    target_execution_id: str,
    control_action_id: str,
    quiescence_sha256: str,
    event_sha256: str,
    authoritative_event: object,
) -> None:
    store = ActionExecutionStore(task_dir)
    reservation = store.read_runtime_reservation(
        target_execution_id
    )
    if (
        reservation.get("task_id") != task_id
        or reservation.get("phase") != "ACTIVE"
        or (
            control_action_id
            == ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD
            and reservation.get("stop_action_id")
            != control_action_id
        )
        or (
            control_action_id
            == ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE
            and reservation.get("reconcile_action_id")
            != control_action_id
        )
        or control_action_id
        not in {
            ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
            ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE,
        }
    ):
        raise _osc_error(
            "ORCHESTRATION_RUNTIME_RESERVATION_RELEASE_INVALID",
            "runtime reservation is not the exact active task target",
        )
    state = load_state(task_id, task_dir.parent.parent)
    workflow_ref = state.get("workflow_ref")
    v4_runtime = (
        isinstance(workflow_ref, _OscMapping)
        and workflow_ref.get("version") == 4
    )
    result_event_sha256 = (
        v4_runtime_result_event_sha256(authoritative_event)
        if v4_runtime
        else event_sha256
    )
    settled = seal_runtime_reservation(
        {
            key: value
            for key, value in reservation.items()
            if key != "record_sha256"
        }
        | {
            "phase": "QUIESCED",
            "result_event_sha256": result_event_sha256,
        }
    )
    claims = action_runtime_reservation_required_lock_claims(
        reservation
    )
    with _workflow_tx_ordered_locks(task_dir, claims):
        current_index = store.read_index(
            expected_task_id=task_id
        )
        current_reservation = store.read_runtime_reservation(
            target_execution_id
        )
        if current_reservation != reservation:
            raise _osc_error(
                "ORCHESTRATION_RUNTIME_RESERVATION_RELEASE_CONFLICT",
                "runtime reservation changed before exact release",
            )
        if v4_runtime:
            orchestration = state.get("orchestration")
            assignments = (
                orchestration.get("assignments")
                if isinstance(orchestration, _OscMapping)
                else None
            )
            assignment_matches = [
                item
                for item in (
                    assignments.values()
                    if isinstance(assignments, _OscMapping)
                    else ()
                )
                if isinstance(item, _OscMapping)
                and isinstance(
                    item.get("lease_credential"), _OscMapping
                )
                and item["lease_credential"].get("lease_id")
                == reservation.get("lease_id")
            ]
            containment = store.read_containment(
                target_execution_id,
                str(reservation["effect_id"]),
            )
            if len(assignment_matches) != 1:
                raise _osc_error(
                    "ORCHESTRATION_RUNTIME_RESERVATION_RELEASE_INVALID",
                    "V4 runtime reservation lacks one exact assignment binding",
                )
            assignment = assignment_matches[0]
            evidence_authority = V4RuntimeEvidenceAuthority()
            evidence = evidence_authority.issue_settlement(
                task_id=task_id,
                execution_id=target_execution_id,
                effect_id=str(reservation["effect_id"]),
                claim_id=str(containment["claim_id"]),
                attempt_id=str(containment["attempt_id"]),
                runtime_attempt=int(assignment["attempt"]),
                executor_id="executor.codex-thread/v1",
                request_id=str(assignment["assignment_id"]),
                node_instance_id=str(
                    assignment["node_instance_id"]
                ),
                repository_id=str(assignment["repository_id"]),
                runtime_handle_sha256=str(
                    reservation["runtime_handle_sha256"]
                ),
                containment_record_sha256=str(
                    reservation["containment_record_sha256"]
                ),
                runtime_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                settlement="QUIESCED",
                runtime_exit_or_quiescence_sha256=(
                    quiescence_sha256
                ),
                authoritative_event=authoritative_event,
            )
            store.release_v4_runtime_reservation(
                settled,
                expected_index=cas_token(current_index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                evidence_authority=evidence_authority,
                settlement_evidence=evidence,
                authoritative_event=authoritative_event,
            )
        else:
            store.release_runtime_reservation(
                settled,
                expected_index=cas_token(current_index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                authenticated_exit_or_quiescence_sha256=(
                    quiescence_sha256
                ),
                result_or_cancellation_event_sha256=event_sha256,
            )


def _osc_recover_committed_runtime_reservation_releases(
    task_dir: _OscPath,
    *,
    task_id: str,
) -> int:
    """Close target reservations from already committed control events."""

    index_path = task_dir / ACTION_EXECUTION_INDEX_PATH
    if not index_path.exists():
        return 0
    store = ActionExecutionStore(task_dir)
    index = store.read_index(expected_task_id=task_id)
    active_targets = [
        str(entry["execution_id"])
        for entry in index["entries"]
        if (
            entry.get("entry_kind") == "runtime-reservation"
            and isinstance(
                entry.get("runtime_reservation"), _OscMapping
            )
            and entry["runtime_reservation"].get("phase") == "ACTIVE"
            and isinstance(entry.get("execution_id"), str)
        )
    ]
    if not active_targets:
        return 0
    state = load_state(task_id, task_dir.parent.parent)
    events = _osc_read_bounded_events(task_dir)
    recovered = 0
    for target_execution_id in active_targets:
        matches: list[
            tuple[str, str, _OscMapping[str, object]]
        ] = []
        for event in events:
            payload = event.get("payload")
            if not isinstance(payload, _OscMapping):
                continue
            control_action_id = payload.get("control_action_id")
            proof_sha256 = payload.get("proof_sha256")
            if (
                payload.get("target_execution_id")
                != target_execution_id
                or control_action_id
                not in {
                    ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
                    ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE,
                }
                or payload.get("operation_id") != control_action_id
                or not isinstance(proof_sha256, str)
            ):
                continue
            selection = resolve_catalog_orchestration_action(
                state, str(control_action_id)
            )
            execution = payload.get("execution")
            if (
                event.get("task_id") != task_id
                or event.get("type") != selection.canonical_event
                or not isinstance(execution, _OscMapping)
                or not isinstance(
                    execution.get("execution_id"), str
                )
                or not isinstance(
                    execution.get("receipt_sha256"), str
                )
            ):
                continue
            matches.append(
                (
                    str(control_action_id),
                    proof_sha256,
                    event,
                )
            )
        if len(matches) > 1:
            raise _osc_error(
                "ORCHESTRATION_RUNTIME_RESERVATION_RELEASE_AMBIGUOUS",
                "multiple committed control events target one active runtime reservation",
                details={
                    "target_execution_id": target_execution_id,
                    "match_count": len(matches),
                },
            )
        if not matches:
            continue
        control_action_id, proof_sha256, event = matches[0]
        _osc_release_runtime_reservation_target(
            task_dir,
            task_id=task_id,
            target_execution_id=target_execution_id,
            control_action_id=control_action_id,
            quiescence_sha256=proof_sha256,
            event_sha256=semantic_sha256(
                _WORKFLOW_TX_EVENT_DOMAIN, event
            ),
            authoritative_event=event,
        )
        recovered += 1
    return recovered


def _osc_find_node(
    state: dict[str, object], node_instance_id: str
) -> dict[str, object]:
    nodes = state.get("node_instances")
    if not isinstance(nodes, list):
        raise _osc_error(
            "NODE_INSTANCE_INVALID",
            "v3 task has no node instance collection",
        )
    for node in nodes:
        if (
            isinstance(node, dict)
            and node.get("node_instance_id") == node_instance_id
        ):
            return node
    raise _osc_error(
        "NODE_INSTANCE_UNKNOWN",
        "node instance is not part of the current task",
        details={"node_instance_id": node_instance_id},
    )


def _osc_plan_from_state(
    task_dir: _OscPath, orchestration: _OscMapping[str, object]
) -> _OscMapping[str, object]:
    record = orchestration.get("plan")
    if not isinstance(record, _OscMapping):
        raise _osc_error(
            "REPOSITORY_PLAN_REQUIRED",
            "task has no persisted repository plan",
        )
    artifact_id = record.get("artifact_id")
    if not isinstance(artifact_id, str):
        raise _osc_error(
            "REPOSITORY_PLAN_STATE_INVALID",
            "persisted repository plan reference is invalid",
        )
    return load_repository_plan(
        _osc_read_artifact(task_dir, orchestration, artifact_id)
    )


def _osc_approval_from_state(
    orchestration: _OscMapping[str, object],
) -> _OscMapping[str, object]:
    approval = orchestration.get("approval")
    if not isinstance(approval, _OscMapping):
        raise _osc_error(
            "REPOSITORY_PLAN_APPROVAL_REQUIRED",
            "repository plan has not been approved",
        )
    return approval


def _osc_current_expansion(
    orchestration: _OscMapping[str, object],
) -> _OscMapping[str, object]:
    expansion = orchestration.get("expansion")
    if not isinstance(expansion, _OscMapping):
        raise _osc_error(
            "REPOSITORY_MAP_EXPANSION_REQUIRED",
            "operation requires the current canonical map expansion",
        )
    if expansion.get("current", True) is not True:
        raise _osc_error(
            "REPOSITORY_MAP_EXPANSION_STALE",
            "operation is blocked while the repository map generation is stale",
            details={
                "map_epoch": expansion.get("map_epoch"),
                "stale_reason": expansion.get("stale_reason"),
            },
        )
    return expansion


def _osc_repository_frontier(
    plan: _OscMapping[str, object],
    approval: _OscMapping[str, object],
    state: _OscMapping[str, object],
    orchestration: _OscMapping[str, object],
) -> object:
    expansion = _osc_current_expansion(orchestration)
    children = {
        str(child["repository_id"]): child
        for child in expansion.get("children", ())
        if isinstance(child, _OscMapping)
    }
    node_facts: dict[str, object] = {}
    for repository_id, child in children.items():
        node = _osc_find_node(
            dict(state), str(child["node_instance_id"])
        )
        node_facts[repository_id] = {
            "state": node["state"],
            "attempts_started": len(node.get("attempts", ())),
        }
    accepted_results = orchestration.get("accepted_results")
    current_results = orchestration.get("current_results")
    artifacts = orchestration.get("artifacts")
    if (
        not isinstance(accepted_results, _OscMapping)
        or not isinstance(current_results, _OscMapping)
        or not isinstance(artifacts, _OscMapping)
    ):
        raise _osc_error(
            "ORCHESTRATION_STATE_INVALID",
            "repository frontier ledgers are invalid",
        )
    result_facts: dict[str, object] = {}
    evidence_facts: dict[str, object] = {}
    approval_facts: dict[str, object] = {}
    for reference in artifacts.values():
        if not isinstance(reference, _OscMapping):
            continue
        for digest in {
            reference.get("sha256"),
            reference.get("semantic_sha256"),
        }:
            if isinstance(digest, str):
                evidence_facts[digest] = {
                    "accepted": True,
                    "current": True,
                    "repository_id": None,
                    "result_id": None,
                }
    for repository_id, child in children.items():
        node_instance_id = str(child["node_instance_id"])
        result_id = current_results.get(node_instance_id)
        record = accepted_results.get(result_id)
        if not isinstance(result_id, str) or not isinstance(
            record, _OscMapping
        ):
            continue
        result = record.get("result")
        if not isinstance(result, _OscMapping):
            continue
        output_contracts = sorted(
            {
                str(reference["sha256"])
                for field in ("artifact_refs", "evidence_refs")
                for reference in result.get(field, ())
                if isinstance(reference, _OscMapping)
                and isinstance(reference.get("sha256"), str)
            },
            key=lambda item: item.encode("utf-8"),
        )
        result_facts[repository_id] = {
            "result_id": result_id,
            "outcome": result["outcome"],
            "accepted": record.get("accepted") is True,
            "current": (
                current_results.get(node_instance_id) == result_id
            ),
            "output_contract_sha256": output_contracts,
        }
        for reference in result.get("evidence_refs", ()):
            if not isinstance(reference, _OscMapping):
                continue
            for digest in {
                reference.get("sha256"),
                reference.get("semantic_sha256"),
            }:
                if isinstance(digest, str):
                    evidence_facts[digest] = {
                        "accepted": True,
                        "current": True,
                        "repository_id": repository_id,
                        "result_id": result_id,
                    }
    pending = orchestration.get("pending_retries")
    if isinstance(pending, _OscMapping):
        for repository_id, child in children.items():
            retry = pending.get(child["node_instance_id"])
            if isinstance(retry, _OscMapping):
                approval_facts[
                    repository_retry_approval_id(
                        repository_id, int(retry["next_attempt"])
                    )
                ] = {
                    "accepted": True,
                    "current": True,
                    "repository_id": repository_id,
                    "result_id": current_results.get(
                        child["node_instance_id"]
                    ),
                }
    return calculate_repository_ready_frontier(
        plan,
        approval,
        node_facts=node_facts,
        accepted_results=result_facts,
        approval_facts=approval_facts,
        evidence_facts=evidence_facts,
        current_semantic_input_sha256=plan[
            "semantic_input_sha256"
        ],
    )


def _osc_assignment_sha256(assignment_id: str) -> str:
    _, separator, digest = assignment_id.rpartition(":")
    if not separator or len(digest) != 64:
        raise _osc_error(
            "WORKER_ASSIGNMENT_IDENTITY_INVALID",
            "worker assignment identity is not content addressed",
        )
    return digest


def _osc_proof_to_state(proof: object) -> dict[str, object]:
    if not isinstance(proof, LeaseQuiescenceProof):
        raise _osc_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "quiescence proof object is required",
        )
    payload = _osc_json.loads(proof.canonical_bytes.decode("utf-8"))
    return {
        "lease_id": proof.lease_id,
        "assignment_id": proof.assignment_id,
        "method": proof.method,
        "worktree_fingerprint_sha256": (
            proof.worktree_fingerprint_sha256
        ),
        "proof_sha256": proof.proof_sha256,
        "quiesced": proof.quiesced,
        "payload": payload,
    }


def _osc_proof_from_state(value: object) -> LeaseQuiescenceProof:
    if not isinstance(value, _OscMapping):
        raise _osc_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "persisted quiescence proof is invalid",
        )
    return LeaseQuiescenceProof(
        lease_id=str(value["lease_id"]),
        assignment_id=str(value["assignment_id"]),
        method=str(value["method"]),
        worktree_fingerprint_sha256=str(
            value["worktree_fingerprint_sha256"]
        ),
        proof_sha256=str(value["proof_sha256"]),
        quiesced=value.get("quiesced") is True,
        canonical_bytes=_osc_canonical_bytes(value["payload"]),
    )


def _osc_proof_snapshot(
    projection: _OscMapping[str, object],
    value: object,
) -> tuple[LeaseQuiescenceProof, dict[str, object]]:
    proof = _osc_proof_from_state(value)
    validate_lease_quiescence_proof(projection, proof)
    if not isinstance(value, _OscMapping):
        raise _osc_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "persisted quiescence proof is invalid",
        )
    payload = value.get("payload")
    snapshot = (
        payload.get("snapshot")
        if isinstance(payload, _OscMapping)
        else None
    )
    if not isinstance(snapshot, _OscMapping):
        raise _osc_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "persisted quiescence proof lacks its post-stop snapshot",
        )
    return proof, _osc_copy.deepcopy(_osc_thaw(snapshot))


def _osc_git_paths(raw: bytes, *, source: str) -> list[str]:
    paths: list[str] = []
    for value in raw.split(b"\0"):
        if not value:
            continue
        try:
            path = value.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise _osc_error(
                "NODE_RESULT_CHANGED_PATH_INVALID",
                "controller observed a non-UTF-8 changed path",
                details={
                    "source": source,
                    "path_bytes_hex": value.hex(),
                },
            ) from exc
        if (
            path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise _osc_error(
                "NODE_RESULT_CHANGED_PATH_INVALID",
                "controller observed a non-canonical changed path",
                details={"source": source, "path": path},
            )
        paths.append(path)
    return paths


def _osc_stable_worktree_binding(
    worktree_path: str,
) -> dict[str, str]:
    worktree = _OscPath(worktree_path)
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise _osc_error(
            "WORKER_ASSIGNMENT_WORKTREE_MISSING",
            "controller-owned worktree is absent",
            details={"worktree_path": worktree_path},
        ) from exc
    if not resolved.is_dir() or str(resolved) != worktree_path:
        raise _osc_error(
            "WORKER_ASSIGNMENT_WORKTREE_IDENTITY_MISMATCH",
            "worktree path must be its canonical resolved directory",
            details={
                "assigned": worktree_path,
                "resolved": str(resolved),
            },
        )
    runtime_git = workflow_runtime_services().git
    root = runtime_git.observe(
        resolved, "rev-parse", "--show-toplevel"
    )
    if _OscPath(root).resolve(strict=True) != resolved:
        raise _osc_error(
            "WORKER_ASSIGNMENT_WORKTREE_IDENTITY_MISMATCH",
            "assigned path is not the root of its Git worktree",
            details={"assigned": worktree_path, "git_root": root},
        )
    common_raw = runtime_git.observe(
        resolved, "rev-parse", "--git-common-dir"
    )
    common_path = _OscPath(common_raw)
    if not common_path.is_absolute():
        common_path = resolved / common_path
    try:
        common = common_path.resolve(strict=True)
        root_stat = resolved.stat()
        common_stat = common.stat()
    except OSError as exc:
        raise _osc_error(
            "WORKER_ASSIGNMENT_WORKTREE_IDENTITY_MISMATCH",
            "Git common directory identity could not be observed",
            details={"worktree_path": worktree_path},
        ) from exc
    if not common.is_dir():
        raise _osc_error(
            "WORKER_ASSIGNMENT_WORKTREE_IDENTITY_MISMATCH",
            "Git common directory is not a directory",
            details={"common_dir": str(common)},
        )
    common_identity = {
        "schema": "dev-flow-git-common-dir-identity/v1",
        "path": str(common),
        "device": int(common_stat.st_dev),
        "inode": int(common_stat.st_ino),
    }
    repository_common_dir_sha256 = _osc_digest(common_identity)
    ownership = {
        "schema": "dev-flow-worktree-ownership-claim/v1",
        "worktree_path": str(resolved),
        "worktree_device": int(root_stat.st_dev),
        "worktree_inode": int(root_stat.st_ino),
        "worktree_uid": int(getattr(root_stat, "st_uid", 0)),
        "worktree_gid": int(getattr(root_stat, "st_gid", 0)),
        "repository_common_dir_sha256": (
            repository_common_dir_sha256
        ),
        "common_dir_uid": int(
            getattr(common_stat, "st_uid", 0)
        ),
        "common_dir_gid": int(
            getattr(common_stat, "st_gid", 0)
        ),
    }
    ownership_claim_sha256 = _osc_digest(ownership)
    stable = {
        "schema": "dev-flow-stable-worktree-identity/v1",
        "worktree_path": str(resolved),
        "repository_common_dir_sha256": (
            repository_common_dir_sha256
        ),
        "ownership_claim_sha256": ownership_claim_sha256,
    }
    return {
        "worktree_path": str(resolved),
        "worktree_identity_sha256": _osc_digest(stable),
        "repository_common_dir_sha256": (
            repository_common_dir_sha256
        ),
        "ownership_claim_sha256": ownership_claim_sha256,
    }


def _osc_bound_worktree_observation(
    worktree_path: str,
    *,
    baseline_head: _OscOptional[str] = None,
) -> tuple[
    dict[str, str],
    str,
    str,
    str,
    tuple[str, ...],
    str,
]:
    before = _osc_stable_worktree_binding(worktree_path)
    worktree = _OscPath(worktree_path)
    runtime_git = workflow_runtime_services().git
    before_head = runtime_git.observe(
        worktree, "rev-parse", "HEAD"
    )
    branch_ref = (
        runtime_git.observe_optional(
            worktree,
            "symbolic-ref",
            "-q",
            "HEAD",
        )
        or "DETACHED"
    )
    first = _osc_worktree_observation(
        worktree_path, baseline_head=baseline_head
    )
    second = _osc_worktree_observation(
        worktree_path, baseline_head=baseline_head
    )
    after_head = runtime_git.observe(
        worktree, "rev-parse", "HEAD"
    )
    after = _osc_stable_worktree_binding(worktree_path)
    after_branch = (
        runtime_git.observe_optional(
            worktree,
            "symbolic-ref",
            "-q",
            "HEAD",
        )
        or "DETACHED"
    )
    if (
        before != after
        or before_head != after_head
        or branch_ref != after_branch
        or first != second
    ):
        raise _osc_error(
            "WORKTREE_OBSERVATION_CHANGED",
            "worktree binding, branch, HEAD, or content changed during controller observation",
        )
    return (
        before,
        branch_ref,
        before_head,
        first[0],
        first[1],
        first[2],
    )


def _osc_worktree_claim_registry_path(
    task_dir: _OscPath,
) -> _OscPath:
    return task_dir.parent.parent / "worktree-claims.json"


def _osc_read_worktree_claim_registry(
    task_dir: _OscPath,
) -> dict[str, object]:
    path = _osc_worktree_claim_registry_path(task_dir)
    if not path.exists():
        return {
            "schema": ORCHESTRATION_WORKTREE_CLAIM_REGISTRY_SCHEMA,
            "generation": 0,
            "claims": {},
        }
    try:
        metadata = path.lstat()
        if (
            not _osc_stat.S_ISREG(metadata.st_mode)
            or metadata.st_size
            > _OSC_WORKTREE_CLAIM_REGISTRY_MAX_BYTES
        ):
            raise _osc_error(
                "WORKTREE_CLAIM_REGISTRY_INVALID",
                "worktree claim registry is not one bounded regular file",
            )
        content = path.read_bytes()
        value = _osc_json.loads(
            content.decode("utf-8", "strict")
        )
    except FlowError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise _osc_error(
            "WORKTREE_CLAIM_REGISTRY_INVALID",
            "worktree claim registry cannot be read",
        ) from exc
    if (
        len(content) > _OSC_WORKTREE_CLAIM_REGISTRY_MAX_BYTES
        or not isinstance(value, dict)
        or set(value) != {"schema", "generation", "claims"}
        or value.get("schema")
        != ORCHESTRATION_WORKTREE_CLAIM_REGISTRY_SCHEMA
        or not isinstance(value.get("generation"), int)
        or value["generation"] < 0
        or not isinstance(value.get("claims"), dict)
    ):
        raise _osc_error(
            "WORKTREE_CLAIM_REGISTRY_INVALID",
            "worktree claim registry has an invalid schema",
        )
    return value


def _osc_write_worktree_claim_registry(
    task_dir: _OscPath, registry: dict[str, object]
) -> None:
    _atomic_write_json(
        _osc_worktree_claim_registry_path(task_dir), registry
    )


def _osc_worktree_claim_slot_sha256(
    registry: _OscMapping[str, object],
    claim_key_sha256: str,
) -> str:
    claims = registry.get("claims")
    if (
        not isinstance(claims, _OscMapping)
        or not isinstance(claim_key_sha256, str)
        or len(claim_key_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in claim_key_sha256
        )
    ):
        raise _osc_error(
            "WORKTREE_CLAIM_REGISTRY_INVALID",
            "worktree claim slot binding is invalid",
        )
    return _osc_digest(
        {
            "schema": "dev-flow-worktree-claim-slot/v1",
            "claim_key_sha256": claim_key_sha256,
            "claim": _osc_copy.deepcopy(
                _osc_thaw(claims.get(claim_key_sha256))
            ),
        }
    )


def _osc_prepare_worktree_claim(
    task_dir: _OscPath,
    *,
    task_id: str,
    node_instance_id: str,
    lease_id: str,
    assignment_id: str,
    binding: _OscMapping[str, str],
    branch_ref: str,
    initial_head: str,
) -> dict[str, object]:
    """Derive an idempotent claim without publishing the registry write."""

    registry = _osc_read_worktree_claim_registry(task_dir)
    claims = registry["claims"]
    assert isinstance(claims, dict)
    key = binding["repository_common_dir_sha256"]
    prior = claims.get(key)
    if (
        isinstance(prior, dict)
        and prior.get("status") == "ACTIVE"
    ):
        if (
            prior.get("task_id") == task_id
            and prior.get("node_instance_id") == node_instance_id
            and prior.get("lease_id") == lease_id
            and prior.get("assignment_id") == assignment_id
        ):
            return _osc_copy.deepcopy(prior)
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_CONFLICT",
            "another task or lease already owns this Git common directory",
            details={
                "claim_task_id": prior.get("task_id"),
                "claim_node_instance_id": prior.get(
                    "node_instance_id"
                ),
                "claim_lease_id": prior.get("lease_id"),
            },
        )
    prior_generation = (
        prior.get("claim_generation")
        if isinstance(prior, dict)
        else 0
    )
    if (
        isinstance(prior_generation, bool)
        or not isinstance(prior_generation, int)
        or prior_generation < 0
    ):
        raise _osc_error(
            "WORKTREE_CLAIM_REGISTRY_INVALID",
            "worktree claim slot has an invalid generation",
        )
    generation = prior_generation + 1
    claim = {
        "schema": "dev-flow-worktree-claim/v1",
        "claim_generation": generation,
        "claim_key_sha256": key,
        "task_id": task_id,
        "node_instance_id": node_instance_id,
        "lease_id": lease_id,
        "assignment_id": assignment_id,
        "worktree_path": binding["worktree_path"],
        "worktree_identity_sha256": binding[
            "worktree_identity_sha256"
        ],
        "repository_common_dir_sha256": key,
        "ownership_claim_sha256": binding[
            "ownership_claim_sha256"
        ],
        "branch_ref": branch_ref,
        "initial_head": initial_head,
        "status": "ACTIVE",
        "released_at_revision": None,
    }
    return claim


def _osc_acquire_worktree_claim(
    task_dir: _OscPath,
    *,
    task_id: str,
    node_instance_id: str,
    lease_id: str,
    assignment_id: str,
    binding: _OscMapping[str, str],
    branch_ref: str,
    initial_head: str,
) -> dict[str, object]:
    expected = _osc_prepare_worktree_claim(
        task_dir,
        task_id=task_id,
        node_instance_id=node_instance_id,
        lease_id=lease_id,
        assignment_id=assignment_id,
        binding=binding,
        branch_ref=branch_ref,
        initial_head=initial_head,
    )
    registry = _osc_read_worktree_claim_registry(task_dir)
    claims = registry["claims"]
    assert isinstance(claims, dict)
    key = binding["repository_common_dir_sha256"]
    prior = claims.get(key)
    if isinstance(prior, dict) and prior == expected:
        return _osc_copy.deepcopy(prior)
    generation = expected["claim_generation"]
    prior_generation = (
        prior.get("claim_generation")
        if isinstance(prior, dict)
        else 0
    )
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or isinstance(prior_generation, bool)
        or not isinstance(prior_generation, int)
        or generation != prior_generation + 1
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_STALE",
            "prepared worktree claim no longer binds its claim slot generation",
        )
    claim = _osc_copy.deepcopy(expected)
    claims[key] = claim
    registry["generation"] = int(registry["generation"]) + 1
    _osc_write_worktree_claim_registry(task_dir, registry)
    return claim


def _osc_release_worktree_claim(
    task_dir: _OscPath,
    *,
    task_id: str,
    lease_id: str,
    assignment_id: str,
    claim_key_sha256: str,
    claim_generation: int,
    released_at_revision: int,
) -> None:
    registry = _osc_read_worktree_claim_registry(task_dir)
    claims = registry["claims"]
    assert isinstance(claims, dict)
    claim = claims.get(claim_key_sha256)
    if not isinstance(claim, dict):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISSING",
            "durable worktree claim is absent",
        )
    if (
        claim.get("task_id") != task_id
        or claim.get("lease_id") != lease_id
        or claim.get("assignment_id") != assignment_id
        or claim.get("claim_generation") != claim_generation
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "durable worktree claim belongs to another authority",
        )
    if claim.get("status") == "RELEASED":
        if claim.get("released_at_revision") != released_at_revision:
            raise _osc_error(
                "WORKTREE_WRITER_CLAIM_RELEASE_MISMATCH",
                "durable worktree claim was released by another task revision",
                details={
                    "expected_revision": released_at_revision,
                    "actual_revision": claim.get(
                        "released_at_revision"
                    ),
                },
            )
        return
    if claim.get("status") != "ACTIVE":
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_INVALID",
            "durable worktree claim status is invalid",
        )
    claim["status"] = "RELEASED"
    claim["released_at_revision"] = released_at_revision
    _osc_write_worktree_claim_registry(task_dir, registry)


def _osc_lease_worktree_claim_binding(
    task_dir: _OscPath,
    orchestration: _OscMapping[str, object],
    *,
    task_id: str,
    lease_id: str,
) -> dict[str, object]:
    """Read one exact claim binding without changing registry bytes."""

    assignments = orchestration.get("assignments")
    dispatch = orchestration.get("dispatch")
    if not isinstance(assignments, _OscMapping) or not isinstance(
        dispatch, _OscMapping
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "orchestration assignment ledgers are invalid",
        )
    assignment = next(
        (
            value
            for value in assignments.values()
            if isinstance(value, _OscMapping)
            and isinstance(
                value.get("lease_credential"), _OscMapping
            )
            and value["lease_credential"].get("lease_id")
            == lease_id
        ),
        None,
    )
    if not isinstance(assignment, _OscMapping):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "lease has no assignment for durable claim release",
        )
    assignment_id = str(assignment["assignment_id"])
    record = dispatch.get(assignment_id)
    if not isinstance(record, _OscMapping):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "assignment has no durable claim binding",
        )
    claim_key_sha256 = str(
        record["worktree_claim_key_sha256"]
    )
    claim_generation = int(
        record["worktree_claim_generation"]
    )
    registry = _osc_read_worktree_claim_registry(task_dir)
    claims = registry["claims"]
    assert isinstance(claims, dict)
    claim = claims.get(claim_key_sha256)
    if (
        not isinstance(claim, dict)
        or claim.get("task_id") != task_id
        or claim.get("lease_id") != lease_id
        or claim.get("assignment_id") != assignment_id
        or claim.get("claim_key_sha256") != claim_key_sha256
        or claim.get("claim_generation") != claim_generation
        or claim.get("status") not in {"ACTIVE", "RELEASED"}
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "durable claim registry does not contain the exact lease binding",
            details={
                "lease_id": lease_id,
                "assignment_id": assignment_id,
                "claim_key_sha256": claim_key_sha256,
            },
        )
    return {
        "assignment": _osc_copy.deepcopy(
            _osc_thaw(assignment)
        ),
        "dispatch": _osc_copy.deepcopy(_osc_thaw(record)),
        "claim": _osc_copy.deepcopy(claim),
        "registry_sha256": _osc_digest(registry),
    }


def _osc_release_lease_worktree_claim(
    task_dir: _OscPath,
    orchestration: _OscMapping[str, object],
    *,
    task_id: str,
    lease_id: str,
    released_at_revision: int,
) -> None:
    assignments = orchestration.get("assignments")
    dispatch = orchestration.get("dispatch")
    if not isinstance(assignments, _OscMapping) or not isinstance(
        dispatch, _OscMapping
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "orchestration assignment ledgers are invalid",
        )
    assignment = next(
        (
            value
            for value in assignments.values()
            if isinstance(value, _OscMapping)
            and isinstance(
                value.get("lease_credential"), _OscMapping
            )
            and value["lease_credential"].get("lease_id")
            == lease_id
        ),
        None,
    )
    if not isinstance(assignment, _OscMapping):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "lease has no assignment for durable claim release",
        )
    record = dispatch.get(assignment["assignment_id"])
    if not isinstance(record, _OscMapping):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "assignment has no durable claim binding",
        )
    _osc_release_worktree_claim(
        task_dir,
        task_id=task_id,
        lease_id=lease_id,
        assignment_id=str(assignment["assignment_id"]),
        claim_key_sha256=str(
            record["worktree_claim_key_sha256"]
        ),
        claim_generation=int(
            record["worktree_claim_generation"]
        ),
        released_at_revision=released_at_revision,
    )


def _osc_worktree_observation(
    worktree_path: str,
    *,
    baseline_head: _OscOptional[str] = None,
) -> tuple[str, tuple[str, ...], str]:
    worktree = _OscPath(worktree_path)
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise _osc_error(
            "NODE_RESULT_WORKTREE_MISSING",
            "assigned controller-owned worktree is absent",
            details={"worktree_path": worktree_path},
        ) from exc
    if not resolved.is_dir() or str(resolved) != worktree_path:
        raise _osc_error(
            "NODE_RESULT_WORKTREE_IDENTITY_MISMATCH",
            "assigned worktree path is not its canonical resolved directory",
            details={
                "assigned": worktree_path,
                "resolved": str(resolved),
            },
        )
    runtime = workflow_runtime_services()
    root = runtime.git.observe(
        resolved, "rev-parse", "--show-toplevel"
    )
    if _OscPath(root).resolve(strict=True) != resolved:
        raise _osc_error(
            "NODE_RESULT_WORKTREE_IDENTITY_MISMATCH",
            "assigned path is not the root of its Git worktree",
            details={"assigned": worktree_path, "git_root": root},
        )
    # Result, quiescence, integration, and finalization decisions require the
    # same complete hostile-Git evidence contract as preflight and review.
    # Ordinary ``git diff`` output is not sufficient: skip-worktree,
    # assume-unchanged, filters, dirty initialized submodules, replacement
    # objects, or caller-selected Git metadata can hide different worktree
    # bytes behind an unchanged diff. The frozen evidence capability clears
    # hostile Git redirection, rejects every incomplete-evidence condition,
    # recursively
    # binds tracked raw filesystem bytes/types/modes and initialized
    # submodules, and accepts only two identical observations.
    try:
        complete = runtime.evidence.fingerprint_repository(resolved)
    except FlowError as exc:
        code = (
            "NODE_RESULT_WORKTREE_CHANGED"
            if exc.code == "WORKTREE_CHANGED"
            else exc.code
        )
        raise _osc_error(
            code,
            exc.message,
            details={
                **dict(exc.details),
                "worktree_path": worktree_path,
                "observation": (
                    "controller-complete-worktree-evidence"
                ),
            },
        ) from exc
    unsupported_untracked = [
        item
        for item in complete.get("untracked", ())
        if (
            not isinstance(item, _OscMapping)
            or item.get("type") != "file"
        )
    ]
    if unsupported_untracked:
        raise _osc_error(
            "NODE_RESULT_WORKTREE_TYPE_UNSUPPORTED",
            "worker result evidence accepts only regular untracked files",
            details={
                "worktree_path": worktree_path,
                "paths": [
                    item.get("path")
                    if isinstance(item, _OscMapping)
                    else None
                    for item in unsupported_untracked
                ],
            },
        )
    head = str(complete["head_sha"])
    staged_paths = _osc_git_paths(
        runtime.git.diff(
            resolved,
            "--cached",
            "--name-only",
            "-z",
            "--",
            text=False,
        ),
        source="staged",
    )
    unstaged_paths = _osc_git_paths(
        runtime.git.diff(
            resolved,
            "--name-only",
            "-z",
            "--",
            text=False,
        ),
        source="unstaged",
    )
    committed_paths = (
        _osc_git_paths(
            runtime.git.diff(
                resolved,
                "--name-only",
                "-z",
                baseline_head,
                "HEAD",
                "--",
                text=False,
            ),
            source="committed",
        )
        if baseline_head is not None
        else []
    )
    untracked_raw = runtime.git.observe(
        resolved,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    untracked_paths = _osc_git_paths(
        untracked_raw, source="untracked"
    )
    changed_paths = tuple(
        sorted(
            {
                *committed_paths,
                *staged_paths,
                *unstaged_paths,
                *untracked_paths,
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    changed_sha256 = _osc_hashlib.sha256(
        b"dev-flow-controller-changed-paths-v1\x00"
        + _osc_canonical_bytes(list(changed_paths))
    ).hexdigest()
    fingerprint = {
        "schema": "dev-flow-controller-worktree-observation/v1",
        "path": str(resolved),
        "head": head,
        "complete_repository_fingerprint_sha256": complete["sha256"],
        "tracked_worktree_manifest_sha256": complete[
            "tracked_worktree_manifest_sha256"
        ],
        "capability_profile_sha256": complete[
            "capability_profile_sha256"
        ],
        "cached_sha256": complete["cached_sha256"],
        "unstaged_sha256": complete["unstaged_sha256"],
        "untracked": complete["untracked"],
    }
    worktree_sha256 = _osc_hashlib.sha256(
        b"dev-flow-controller-worktree-observation-v1\x00"
        + _osc_canonical_bytes(fingerprint)
    ).hexdigest()
    return worktree_sha256, changed_paths, changed_sha256


def _osc_controller_worktree_snapshot(
    task_dir: _OscPath,
    assignment: _OscMapping[str, object],
    dispatch: _OscMapping[str, object],
    *,
    runtime_inactive: bool,
) -> dict[str, object]:
    worktree_path = str(assignment["worktree_path"])
    baseline_head = dispatch.get("worktree_baseline_head")
    if not isinstance(baseline_head, str):
        raise _osc_error(
            "NODE_RESULT_WORKTREE_BASELINE_MISSING",
            "assignment lacks its controller-observed Git baseline",
        )
    (
        binding,
        branch_ref,
        _current_head,
        fingerprint,
        _changed_paths,
        changed_paths_sha256,
    ) = _osc_bound_worktree_observation(
        worktree_path,
        baseline_head=baseline_head,
    )
    expected_binding = {
        "worktree_identity_sha256": assignment.get(
            "worktree_identity_sha256"
        ),
        "repository_common_dir_sha256": dispatch.get(
            "repository_common_dir_sha256"
        ),
        "ownership_claim_sha256": dispatch.get(
            "ownership_claim_sha256"
        ),
        "worktree_branch_ref": dispatch.get(
            "worktree_branch_ref"
        ),
    }
    mismatched = sorted(
        key
        for key, value in expected_binding.items()
        if (
            branch_ref
            if key == "worktree_branch_ref"
            else binding.get(key)
        )
        != value
    )
    if mismatched:
        raise _osc_error(
            "WORKTREE_POSTCONDITION_BINDING_MISMATCH",
            "controller-observed worktree identity changed",
            details={"fields": mismatched},
        )
    registry = _osc_read_worktree_claim_registry(task_dir)
    claims = registry["claims"]
    assert isinstance(claims, dict)
    claim_key = dispatch.get("worktree_claim_key_sha256")
    claim_generation = dispatch.get(
        "worktree_claim_generation"
    )
    durable_claim = claims.get(claim_key)
    lease_credential = assignment.get("lease_credential")
    lease_id = (
        lease_credential.get("lease_id")
        if isinstance(lease_credential, _OscMapping)
        else None
    )
    expected_claim = {
        "task_id": assignment.get("task_id"),
        "node_instance_id": assignment.get("node_instance_id"),
        "lease_id": lease_id,
        "assignment_id": assignment.get("assignment_id"),
        "worktree_path": binding["worktree_path"],
        "worktree_identity_sha256": binding[
            "worktree_identity_sha256"
        ],
        "repository_common_dir_sha256": binding[
            "repository_common_dir_sha256"
        ],
        "ownership_claim_sha256": binding[
            "ownership_claim_sha256"
        ],
        "branch_ref": branch_ref,
        "initial_head": baseline_head,
        "claim_generation": claim_generation,
    }
    if (
        not isinstance(claim_key, str)
        or not isinstance(claim_generation, int)
        or not isinstance(durable_claim, _OscMapping)
        or durable_claim.get("claim_key_sha256") != claim_key
        or durable_claim.get("status")
        not in {"ACTIVE", "RELEASED"}
        or any(
            durable_claim.get(key) != value
            for key, value in expected_claim.items()
        )
    ):
        raise _osc_error(
            "WORKTREE_WRITER_CLAIM_MISMATCH",
            "worktree observation does not bind the controller durable ownership registry",
        )
    initial = dispatch.get(
        "worktree_initial_fingerprint_sha256"
    )
    if not isinstance(initial, str):
        raise _osc_error(
            "WORKTREE_POSTCONDITION_BINDING_MISMATCH",
            "assignment lacks its initial worktree fingerprint",
        )
    return {
        "schema": WORKTREE_POSTCONDITION_SCHEMA,
        "repository_id": assignment["repository_id"],
        "repository_identity_sha256": assignment[
            "repository_identity_sha256"
        ],
        "initial_worktree_fingerprint_sha256": initial,
        "worktree_fingerprint_sha256": fingerprint,
        "repository_common_dir_sha256": binding[
            "repository_common_dir_sha256"
        ],
        "ownership_claim_sha256": binding[
            "ownership_claim_sha256"
        ],
        "git_state_sha256": fingerprint,
        "changed_paths_sha256": changed_paths_sha256,
        "complete": True,
        "active_writer": not runtime_inactive,
        "mutation_quarantine": False,
    }


def _osc_validate_runtime_isolation_attestation(
    value: object,
    projection: _OscMapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, _OscMapping):
        raise _osc_error(
            "RUNTIME_ISOLATION_ATTESTATION_INVALID",
            "trusted runtime isolation attestation must be an object",
        )
    attestation = dict(value)
    expected_fields = {
        "schema",
        "lease_id",
        "assignment_id",
        "termination_confirmed",
        "termination_evidence_sha256",
        "operator_isolation_confirmed",
        "operator_isolation_evidence_sha256",
    }
    termination = attestation.get("termination_confirmed")
    isolation = attestation.get(
        "operator_isolation_confirmed"
    )
    termination_evidence = attestation.get(
        "termination_evidence_sha256"
    )
    isolation_evidence = attestation.get(
        "operator_isolation_evidence_sha256"
    )

    def valid_optional_digest(
        present: object, digest_value: object
    ) -> bool:
        return (
            isinstance(present, bool)
            and present
            == (
                isinstance(digest_value, str)
                and len(digest_value) == 64
                and all(
                    character in "0123456789abcdef"
                    for character in digest_value
                )
            )
        )

    if (
        set(attestation) != expected_fields
        or attestation.get("schema")
        != ORCHESTRATION_RUNTIME_ISOLATION_ATTESTATION_SCHEMA
        or attestation.get("lease_id") != projection["lease_id"]
        or attestation.get("assignment_id")
        != projection["assignment_id"]
        or not valid_optional_digest(
            termination, termination_evidence
        )
        or not valid_optional_digest(isolation, isolation_evidence)
        or not (termination or isolation)
    ):
        raise _osc_error(
            "RUNTIME_ISOLATION_ATTESTATION_INVALID",
            "trusted runtime isolation attestation is not exact",
        )
    return attestation


def _osc_changed_path_allowed(
    path: str, approved_paths: _OscSequence[str]
) -> bool:
    return any(
        path == approved or path.startswith(approved.rstrip("/") + "/")
        for approved in approved_paths
    )


def _osc_verify_worker_result(
    task_id: str,
    result_value: object,
    *,
    data_dir: object = None,
    locked_context: _OscOptional[
        tuple[_OscPath, dict[str, object]]
    ] = None,
    wall_time_ns: _OscCallable[[], int] = _osc_time.time_ns,
    monotonic_time_ns: _OscCallable[[], int] = (
        _osc_system_monotonic_ns
    ),
    clock_id: _OscOptional[str] = None,
) -> dict[str, object]:
    """Re-observe a worker result from controller-owned durable facts."""

    try:
        result = validate_orchestration_node_result(result_value)
        context = (
            _osc_locked_current_state(task_id, data_dir)
            if locked_context is None
            else _osc_contextlib.nullcontext(locked_context)
        )
        with context as (task_dir, state):
            orchestration = _osc_state_copy(state)
            _osc_current_expansion(orchestration)
            assignments = orchestration["assignments"]
            leases = orchestration["leases"]
            assert isinstance(assignments, dict)
            assert isinstance(leases, dict)
            assignment = assignments.get(result["assignment_id"])
            if not isinstance(assignment, _OscMapping):
                raise _osc_error(
                    "WORKER_ASSIGNMENT_UNKNOWN",
                    "result assignment is not controller-persisted",
                )
            lease_value = leases.get(result["lease_id"])
            if lease_value is None:
                raise _osc_error(
                    "WORKER_LEASE_UNKNOWN",
                    "result lease is not controller-persisted",
                )
            lease = validate_worker_lease(lease_value)
            credential = assignment.get("lease_credential")
            expected = {
                "task_id": assignment.get("task_id"),
                "workflow_bundle_sha256": assignment.get(
                    "workflow_bundle_sha256"
                ),
                "map_epoch": assignment.get("map_epoch"),
                "repository_id": assignment.get("repository_id"),
                "node_instance_id": assignment.get(
                    "node_instance_id"
                ),
                "attempt": assignment.get("attempt"),
                "assignment_id": assignment.get("assignment_id"),
                "input_sha256": assignment.get(
                    "input_evidence_sha256"
                ),
            }
            mismatched = [
                field
                for field, value in expected.items()
                if result.get(field) != value
            ]
            if (
                result.get("lease_id") != lease.lease_id
                or not isinstance(credential, _OscMapping)
                or credential.get("lease_id") != lease.lease_id
                or result.get("lease_nonce") != lease.lease_nonce
                or credential.get("lease_nonce") != lease.lease_nonce
            ):
                mismatched.append("lease")
            if mismatched:
                raise _osc_error(
                    "NODE_RESULT_BINDING_MISMATCH",
                    "worker result differs from its persisted assignment or lease",
                    details={"fields": sorted(set(mismatched))},
                )
            node = _osc_find_node(state, str(result["node_instance_id"]))
            attempts = node.get("attempts")
            latest_attempt = (
                attempts[-1]
                if isinstance(attempts, list) and attempts
                else None
            )
            runtime_handle = (
                latest_attempt.get("runtime_handle")
                if isinstance(latest_attempt, _OscMapping)
                else None
            )
            expected_runtime_handle = (
                None
                if runtime_handle is None
                else runtime_handle.get("handle_id")
                if isinstance(runtime_handle, _OscMapping)
                else object()
            )
            if (
                node.get("state")
                not in {"RUNNING", "WAITING_APPROVAL", "WAITING_EXTERNAL"}
                or not isinstance(attempts, list)
                or len(attempts) != int(result["attempt"])
                or expected_runtime_handle != result.get("runtime_handle")
            ):
                raise _osc_error(
                    "NODE_RESULT_ATTEMPT_STALE",
                    "worker result does not bind the active attempt generation",
                )
            dispatch_record = orchestration["dispatch"].get(
                assignment["assignment_id"]
            )
            baseline_head = (
                dispatch_record.get("worktree_baseline_head")
                if isinstance(dispatch_record, _OscMapping)
                else None
            )
            if not isinstance(baseline_head, str):
                raise _osc_error(
                    "NODE_RESULT_WORKTREE_BASELINE_MISSING",
                    "persisted assignment lacks its controller-observed Git baseline",
                )
            worktree_sha256, changed_paths, changed_sha256 = (
                _osc_worktree_observation(
                    str(assignment["worktree_path"]),
                    baseline_head=baseline_head,
                )
            )
            approved_paths = tuple(
                str(value)
                for value in assignment.get("approved_paths", ())
            )
            disallowed = [
                path
                for path in changed_paths
                if not _osc_changed_path_allowed(
                    path, approved_paths
                )
            ]
            if disallowed or (
                assignment.get("write_policy") == "read-only"
                and changed_paths
            ):
                raise _osc_error(
                    "NODE_RESULT_CHANGED_PATH_OUT_OF_SCOPE",
                    "controller observed changes outside the assignment write scope",
                    details={"paths": disallowed or list(changed_paths)},
                )
            artifacts: dict[str, str] = {}
            evidence: dict[str, object] = {}
            for field, destination in (
                ("artifact_refs", artifacts),
                ("evidence_refs", evidence),
            ):
                for reference in result[field]:
                    identifier = str(reference["id"])
                    content = _osc_read_artifact(
                        task_dir, orchestration, identifier
                    )
                    persisted = orchestration["artifacts"].get(
                        identifier
                    )
                    if (
                        not isinstance(persisted, _OscMapping)
                        or any(
                            persisted.get(key) != reference[key]
                            for key in (
                                "id",
                                "semantic_sha256",
                                "sha256",
                                "size",
                                "kind",
                                "locator",
                            )
                        )
                        or _osc_hashlib.sha256(content).hexdigest()
                        != reference["sha256"]
                    ):
                        raise _osc_error(
                            "NODE_RESULT_ARTIFACT_UNVERIFIED",
                            "result reference differs from task-scoped controller bytes",
                            details={"artifact_id": identifier},
                        )
                    if field == "artifact_refs":
                        artifacts[identifier] = str(
                            reference["sha256"]
                        )
                    else:
                        evidence[identifier] = {
                            "sha256": reference["sha256"],
                            "semantic_sha256": reference[
                                "semantic_sha256"
                            ],
                            "size": reference["size"],
                            "kind": reference["kind"],
                            "locator": reference["locator"],
                            "current": True,
                        }
            output_observation = {
                "schema": (
                    ORCHESTRATION_CONTROLLER_OUTPUT_OBSERVATION_SCHEMA
                ),
                "task_id": task_id,
                "assignment_id": result["assignment_id"],
                "node_instance_id": result["node_instance_id"],
                "attempt": result["attempt"],
                "worktree_sha256": worktree_sha256,
                "changed_paths_sha256": changed_sha256,
                "artifacts": artifacts,
                "evidence": {
                    key: {
                        "sha256": value["sha256"],
                        "semantic_sha256": value[
                            "semantic_sha256"
                        ],
                    }
                    for key, value in evidence.items()
                },
            }
            output_sha256 = _osc_hashlib.sha256(
                b"dev-flow-controller-output-observation-v1\x00"
                + _osc_canonical_bytes(output_observation)
            ).hexdigest()
            verification_sha256 = _osc_hashlib.sha256(
                b"dev-flow-controller-verification-observation-v1\x00"
                + _osc_canonical_bytes(
                    {
                        "assignment_id": result["assignment_id"],
                        "outcome": result["outcome"],
                        "evidence": output_observation["evidence"],
                    }
                )
            ).hexdigest()
            verified = {
                "schema": NODE_RESULT_VERIFIED_OUTPUT_SCHEMA,
                "output_sha256": output_sha256,
                "worktree_sha256": worktree_sha256,
                "changed_paths_sha256": changed_sha256,
                "verification_sha256": verification_sha256,
                "artifacts": artifacts,
                "evidence": evidence,
            }
            lease_status = worker_lease_status(
                lease,
                wall_time_ns=wall_time_ns(),
                monotonic_time_ns=monotonic_time_ns(),
                clock_id=clock_id or lease.clock_id,
            )
            evaluate_node_result_acceptance(
                result,
                expected_revision=int(state["revision"]),
                current_revision=int(state["revision"]),
                expected_bindings={
                    "schema": NODE_RESULT_EXPECTATION_SCHEMA,
                    "task_id": assignment["task_id"],
                    "workflow_bundle_sha256": assignment[
                        "workflow_bundle_sha256"
                    ],
                    "plan_id": assignment["plan_id"],
                    "plan_artifact_sha256": assignment[
                        "plan_artifact_sha256"
                    ],
                    "dag_sha256": assignment[
                        "plan_dag_sha256"
                    ],
                    "semantic_input_sha256": assignment[
                        "semantic_input_sha256"
                    ],
                    "map_epoch": assignment["map_epoch"],
                    "repository_id": assignment["repository_id"],
                    "repository_identity_sha256": assignment[
                        "repository_identity_sha256"
                    ],
                    "node_instance_id": assignment[
                        "node_instance_id"
                    ],
                    "attempt": assignment["attempt"],
                    "assignment_revision": assignment[
                        "expected_revision"
                    ],
                    "assignment_id": assignment["assignment_id"],
                    "assignment_sha256": _osc_assignment_sha256(
                        str(assignment["assignment_id"])
                    ),
                    "lease_id": lease.lease_id,
                    "lease_nonce": lease.lease_nonce,
                    "input_sha256": assignment[
                        "input_evidence_sha256"
                    ],
                    "interface_contract_sha256": list(
                        assignment[
                            "interface_contract_sha256s"
                        ]
                    ),
                    "input_worktree_fingerprint_sha256": (
                        orchestration["dispatch"][
                            assignment["assignment_id"]
                        ][
                            "worktree_initial_fingerprint_sha256"
                        ]
                    ),
                    "actor_id": orchestration["dispatch"][
                        assignment["assignment_id"]
                    ]["actor_id"],
                    "host_assignment_id": orchestration["dispatch"][
                        assignment["assignment_id"]
                    ]["host_assignment_id"],
                    "runtime_handle_id": orchestration["dispatch"][
                        assignment["assignment_id"]
                    ]["runtime_handle_id"],
                    "lease_active": lease_status.authorized,
                },
                verified_output=verified,
                observed_results={},
            )
            return verified
    except Exception as exc:
        raise _osc_translate(exc) from exc


def controller_verify_worker_result(
    task_id: str,
    result_value: object,
    *,
    data_dir: object = None,
) -> dict[str, object]:
    """Return a diagnostic preview; acceptance always re-verifies in-lock."""

    return _osc_verify_worker_result(
        task_id, result_value, data_dir=data_dir
    )


def _osc_terminal_orchestration_status(
    state: _OscMapping[str, object],
    *,
    target_status: str,
) -> dict[str, object]:
    if state.get("execution_profile") != "multi-repository":
        return {
            "ready": True,
            "blockers": [],
            "snapshot_id": None,
        }
    orchestration = _osc_state_copy(state)
    blockers: set[str] = set()
    cancellation = orchestration.get("cancellation")
    leases = orchestration.get("leases")
    proofs = orchestration.get("quiescence_proofs")
    dispatch = orchestration.get("dispatch")
    assignments = orchestration.get("assignments")
    if not isinstance(leases, _OscMapping):
        blockers.add("ORCHESTRATION_LEASE_LEDGER_INVALID")
        leases = {}
    if not isinstance(proofs, _OscMapping):
        blockers.add("ORCHESTRATION_PROOF_LEDGER_INVALID")
        proofs = {}
    if not isinstance(dispatch, _OscMapping):
        blockers.add("ORCHESTRATION_DISPATCH_LEDGER_INVALID")
        dispatch = {}
    if not isinstance(assignments, _OscMapping):
        blockers.add("ORCHESTRATION_ASSIGNMENT_LEDGER_INVALID")
        assignments = {}
    non_quiesced = []
    for lease_id, lease in leases.items():
        if not isinstance(lease, _OscMapping):
            non_quiesced.append(str(lease_id))
            continue
        assignment = next(
            (
                value
                for value in assignments.values()
                if isinstance(value, _OscMapping)
                and isinstance(
                    value.get("lease_credential"), _OscMapping
                )
                and value["lease_credential"].get("lease_id")
                == lease_id
            ),
            None,
        )
        record = (
            dispatch.get(assignment.get("assignment_id"))
            if isinstance(assignment, _OscMapping)
            else None
        )
        if (
            lease.get("quiesced_at_wall_ns") is None
            or lease_id not in proofs
            or not isinstance(record, _OscMapping)
            or record.get("runtime_live") is not False
            or record.get("runtime_status") != "QUIESCED"
        ):
            non_quiesced.append(str(lease_id))
    if non_quiesced:
        blockers.add("ORCHESTRATION_LEASE_NOT_QUIESCED")

    if target_status == "CANCELLED":
        if (
            not isinstance(cancellation, _OscMapping)
            or set(cancellation)
            != {
                "requested",
                "quiesced",
                "affected_lease_ids",
                "uncertain_lease_ids",
            }
            or cancellation.get("requested") is not True
        ):
            blockers.add("CANCELLATION_INTENT_NOT_CURRENT")
        else:
            affected = cancellation.get("affected_lease_ids")
            uncertain = cancellation.get("uncertain_lease_ids")
            canonical_affected = (
                isinstance(affected, list)
                and all(isinstance(value, str) for value in affected)
                and affected
                == sorted(set(affected), key=_osc_utf8_sort_key)
            )
            if (
                not canonical_affected
                or set(affected) != set(leases)
                or not isinstance(uncertain, list)
                or uncertain
                != sorted(set(uncertain), key=_osc_utf8_sort_key)
                or uncertain
                or cancellation.get("quiesced") is not True
                or any(value not in proofs for value in affected)
            ):
                blockers.add("CANCELLATION_QUIESCENCE_NOT_PROVEN")
        return {
            "ready": not blockers,
            "blockers": sorted(blockers, key=_osc_utf8_sort_key),
            "snapshot_id": None,
        }

    if target_status != "DONE":
        return {
            "ready": True,
            "blockers": [],
            "snapshot_id": None,
        }
    if (
        isinstance(cancellation, _OscMapping)
        and cancellation.get("requested") is True
    ):
        blockers.add("CANCELLATION_PENDING")
    plan = orchestration.get("plan")
    expansion = orchestration.get("expansion")
    if (
        not isinstance(plan, _OscMapping)
        or not isinstance(expansion, _OscMapping)
        or expansion.get("current", True) is not True
        or expansion.get("map_epoch") != plan.get("map_epoch")
        or expansion.get("plan_id") != plan.get("plan_id")
    ):
        blockers.add("MAP_GENERATION_NOT_CURRENT")
    integration = orchestration.get("integration")
    verification = orchestration.get("integration_verification")
    review = orchestration.get("review")
    snapshot_id = (
        integration.get("snapshot_id")
        if isinstance(integration, _OscMapping)
        else None
    )
    integration_payload = (
        integration.get("payload")
        if isinstance(integration, _OscMapping)
        else None
    )
    barrier = (
        orchestration.get("barriers", {}).get(
            integration_payload.get("barrier_id")
        )
        if isinstance(integration_payload, _OscMapping)
        and isinstance(orchestration.get("barriers"), _OscMapping)
        else None
    )
    if (
        not isinstance(integration, _OscMapping)
        or integration.get("current") is not True
        or not isinstance(integration_payload, _OscMapping)
        or integration_payload.get("snapshot_id")
        not in {None, snapshot_id}
        or not isinstance(barrier, _OscMapping)
        or barrier.get("status") != "CLOSED"
        or not isinstance(barrier.get("aggregate"), _OscMapping)
        or barrier["aggregate"].get("barrier_sha256")
        != integration_payload.get("barrier_sha256")
    ):
        blockers.add("INTEGRATION_SNAPSHOT_NOT_CURRENT")
        blockers.add("INTEGRATION_BARRIER_NOT_CURRENT")
    else:
        current_results = orchestration.get("current_results")
        accepted_results = orchestration.get("accepted_results")
        members = integration_payload.get("members")
        repository_set = integration_payload.get("repository_set")
        if (
            not isinstance(current_results, _OscMapping)
            or not isinstance(accepted_results, _OscMapping)
            or not isinstance(members, list)
            or not isinstance(repository_set, list)
            or [member.get("repository_id") for member in members]
            != sorted(repository_set, key=_osc_utf8_sort_key)
        ):
            blockers.add("INTEGRATION_SNAPSHOT_BINDING_INVALID")
        else:
            for member in members:
                if not isinstance(member, _OscMapping):
                    blockers.add(
                        "INTEGRATION_SNAPSHOT_BINDING_INVALID"
                    )
                    break
                result_id = current_results.get(
                    member.get("node_instance_id")
                )
                accepted = accepted_results.get(result_id)
                member_proof = proofs.get(member.get("lease_id"))
                if (
                    result_id != member.get("result_id")
                    or not isinstance(accepted, _OscMapping)
                    or accepted.get("current") is not True
                    or accepted.get("lease_quiesced") is not True
                    or accepted.get("runtime_live") is not False
                    or member.get("lease_id") not in proofs
                    or not isinstance(member_proof, _OscMapping)
                    or not isinstance(
                        member.get("quiescence_proof_sha256"), str
                    )
                    or member_proof.get("proof_sha256")
                    != member["quiescence_proof_sha256"]
                ):
                    blockers.add(
                        "INTEGRATION_SNAPSHOT_BINDING_INVALID"
                    )
                    break
    verification_payload = (
        verification.get("payload")
        if isinstance(verification, _OscMapping)
        else None
    )
    if (
        not isinstance(verification, _OscMapping)
        or verification.get("current") is not True
        or not isinstance(verification_payload, _OscMapping)
        or verification_payload.get("snapshot_id") != snapshot_id
        or verification_payload.get("snapshot_sha256")
        != (
            integration.get("snapshot_sha256")
            if isinstance(integration, _OscMapping)
            else None
        )
        or verification_payload.get("outcome") != "SUCCEEDED"
        or not isinstance(
            verification_payload.get("attestation_sha256"), str
        )
        or not isinstance(
            verification_payload.get("verifier_id"), str
        )
    ):
        blockers.add("INTEGRATION_VERIFICATION_NOT_CURRENT")
    review_payload = (
        review.get("payload")
        if isinstance(review, _OscMapping)
        else None
    )
    implementation_actors = {
        value.get("actor_id")
        for value in dispatch.values()
        if isinstance(value, _OscMapping)
    }
    if (
        not isinstance(review, _OscMapping)
        or review.get("current") is not True
        or not isinstance(review_payload, _OscMapping)
        or review_payload.get("integration_verification_id")
        != (
            verification.get("verification_id")
            if isinstance(verification, _OscMapping)
            else None
        )
        or review_payload.get("snapshot_id") != snapshot_id
        or review_payload.get("outcome") != "SUCCEEDED"
        or review_payload.get("reviewer_id")
        in implementation_actors
        or not isinstance(
            review_payload.get("attestation_sha256"), str
        )
    ):
        blockers.add("INDEPENDENT_REVIEW_NOT_CURRENT")
    return {
        "ready": not blockers,
        "blockers": sorted(blockers, key=_osc_utf8_sort_key),
        "snapshot_id": snapshot_id,
    }


def _osc_fresh_terminal_orchestration_status(
    task_dir: _OscPath,
    state: _OscMapping[str, object],
    *,
    target_status: str,
) -> dict[str, object]:
    staged_targets = {
        "VERIFYING",
        "REVIEWING",
        "FINALIZING",
        "DONE",
    }
    status = _osc_terminal_orchestration_status(
        state,
        target_status=(
            "DONE" if target_status in staged_targets else target_status
        ),
    )
    blockers = set(status["blockers"])
    ignored = {
        "VERIFYING": {
            "INTEGRATION_VERIFICATION_NOT_CURRENT",
            "INDEPENDENT_REVIEW_NOT_CURRENT",
        },
        "REVIEWING": {"INDEPENDENT_REVIEW_NOT_CURRENT"},
    }.get(target_status, set())
    blockers.difference_update(ignored)
    if state.get("execution_profile") != "multi-repository":
        return status
    orchestration = _osc_state_copy(state)
    if target_status in staged_targets and not blockers:
        integration = orchestration["integration"]
        assert isinstance(integration, _OscMapping)
        for member in integration["payload"]["members"]:
            assignment_id = member["assignment_id"]
            lease_id = member["lease_id"]
            assignment = orchestration["assignments"].get(
                assignment_id
            )
            dispatch = orchestration["dispatch"].get(
                assignment_id
            )
            if not isinstance(
                assignment, _OscMapping
            ) or not isinstance(dispatch, _OscMapping):
                blockers.add("INTEGRATION_SNAPSHOT_BINDING_INVALID")
                break
            projection = (
                OrchestrationControllerService._runtime_lease_projection(
                    object.__new__(OrchestrationControllerService),
                    orchestration,
                    lease_id,
                )
            )
            proof, proof_snapshot = _osc_proof_snapshot(
                projection,
                orchestration["quiescence_proofs"].get(lease_id),
            )
            first = _osc_controller_worktree_snapshot(
                task_dir,
                assignment,
                dispatch,
                runtime_inactive=True,
            )
            second = _osc_controller_worktree_snapshot(
                task_dir,
                assignment,
                dispatch,
                runtime_inactive=True,
            )
            if (
                first != second
                or first != proof_snapshot
                or proof.proof_sha256
                != member["quiescence_proof_sha256"]
                or first["worktree_fingerprint_sha256"]
                != member["worktree_sha256"]
                or first["changed_paths_sha256"]
                != member["changed_paths_sha256"]
            ):
                blockers.add("INTEGRATION_WORKTREE_DRIFT")
                break
    if target_status == "CANCELLED" and not blockers:
        registry = _osc_read_worktree_claim_registry(task_dir)
        claims = registry["claims"]
        assert isinstance(claims, dict)
        for assignment in orchestration["assignments"].values():
            if not isinstance(assignment, _OscMapping):
                blockers.add("WORKTREE_WRITER_CLAIM_MISMATCH")
                break
            record = orchestration["dispatch"].get(
                assignment.get("assignment_id")
            )
            claim = (
                claims.get(record.get("worktree_claim_key_sha256"))
                if isinstance(record, _OscMapping)
                else None
            )
            if (
                not isinstance(claim, _OscMapping)
                or claim.get("task_id") != state.get("task_id")
                or claim.get("assignment_id")
                != assignment.get("assignment_id")
                or claim.get("claim_generation")
                != record.get("worktree_claim_generation")
                or claim.get("status") != "RELEASED"
            ):
                blockers.add("WORKTREE_WRITER_CLAIM_NOT_RELEASED")
                break
    return {
        "ready": not blockers,
        "blockers": sorted(blockers, key=_osc_utf8_sort_key),
        "snapshot_id": status["snapshot_id"],
    }


def _osc_preauthorize_manager_effect(
    old_state: _OscMapping[str, object],
    candidate_orchestration: _OscMapping[str, object],
    authorization: object,
    *,
    action_id: str,
) -> SealedV3ManagerAuthorization:
    sealed = seal_v3_manager_authorization(authorization)
    try:
        return validate_v3_manager_authorization_pre_effect(
            sealed,
            old_state,
            candidate_orchestration,
            action_id=action_id,
        )
    except TransitionEngineError as exc:
        raise _osc_error(
            exc.code, exc.message, details=exc.details
        ) from exc


class OrchestrationControllerService:
    """Controller-only schema-v3 orchestration facade for CLI and MCP."""

    __slots__ = (
        "_secret_resolver",
        "_secret_publisher",
        "_random_bytes",
        "_wall_time_ns",
        "_monotonic_ns",
        "_clock_id",
        "_runtime_stop_observer",
        "_runtime_stop_authenticator",
        "_runtime_isolation_observer",
        "_runtime_recovery_observer",
        "_integration_verifier",
        "_independent_reviewer",
        "_host_capability_observer",
        "_trusted_host_adapter_ids",
        "_protected_read_identity_sha256s",
        "_mutating_tool_ids",
    )

    def __init__(
        self,
        *,
        secret_resolver: _OscCallable[[str], bytearray],
        secret_publisher: _OscOptional[
            _OscCallable[[str, bytes], None]
        ] = None,
        random_bytes: _OscCallable[[int], bytearray] = _osc_random_secret,
        wall_time_ns: _OscCallable[[], int] = _osc_time.time_ns,
        monotonic_ns: _OscCallable[[], int] = (
            _osc_system_monotonic_ns
        ),
        clock_id: str = "process-monotonic",
        runtime_stop_observer: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        runtime_stop_authenticator: _OscOptional[
            _OscCallable[
                [
                    _OscMapping[str, object],
                    _OscMapping[str, object],
                ],
                bool,
            ]
        ] = None,
        runtime_isolation_observer: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        runtime_recovery_observer: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        integration_verifier: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        independent_reviewer: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        host_capability_observer: _OscOptional[
            _OscCallable[[_OscMapping[str, object]], object]
        ] = None,
        trusted_host_adapter_ids: _OscSequence[str] = (),
        protected_read_identity_sha256s: _OscSequence[str] = (),
        mutating_tool_ids: _OscSequence[str] = _osc_mutating_tool_ids,
    ) -> None:
        if not callable(secret_resolver):
            raise TypeError("secret_resolver must be callable")
        if secret_publisher is not None and not callable(secret_publisher):
            raise TypeError("secret_publisher must be callable")
        for name, callback in (
            ("runtime_stop_observer", runtime_stop_observer),
            (
                "runtime_stop_authenticator",
                runtime_stop_authenticator,
            ),
            (
                "runtime_isolation_observer",
                runtime_isolation_observer,
            ),
            (
                "runtime_recovery_observer",
                runtime_recovery_observer,
            ),
            ("integration_verifier", integration_verifier),
            ("independent_reviewer", independent_reviewer),
            (
                "host_capability_observer",
                host_capability_observer,
            ),
        ):
            if callback is not None and not callable(callback):
                raise TypeError(f"{name} must be callable")
        self._secret_resolver = secret_resolver
        self._secret_publisher = secret_publisher
        self._random_bytes = random_bytes
        self._wall_time_ns = wall_time_ns
        self._monotonic_ns = monotonic_ns
        self._clock_id = clock_id
        self._runtime_stop_observer = runtime_stop_observer
        self._runtime_stop_authenticator = (
            runtime_stop_authenticator
        )
        self._runtime_isolation_observer = (
            runtime_isolation_observer
        )
        self._runtime_recovery_observer = (
            runtime_recovery_observer
        )
        self._integration_verifier = integration_verifier
        self._independent_reviewer = independent_reviewer
        self._host_capability_observer = (
            host_capability_observer
        )
        self._trusted_host_adapter_ids = tuple(
            trusted_host_adapter_ids
        )
        self._protected_read_identity_sha256s = tuple(
            protected_read_identity_sha256s
        )
        self._mutating_tool_ids = tuple(mutating_tool_ids)

    def __repr__(self) -> str:
        return "OrchestrationControllerService(secret_channel=<hidden>)"

    def _authorize(
        self,
        orchestration: dict[str, object],
        request_value: object,
        principal_value: object,
        *,
        action_id: str,
    ) -> object:
        request = validate_manager_capability_request(request_value)
        principal = validate_agent_principal(principal_value)
        if request.action_id != action_id:
            raise _osc_error(
                "MANAGER_CAPABILITY_ACTION_MISMATCH",
                "request action does not match the controller operation",
                details={
                    "expected": action_id,
                    "actual": request.action_id,
                },
            )
        capabilities = orchestration["manager_capabilities"]
        assert isinstance(capabilities, dict)
        verifier = capabilities.get(request.capability_id)
        if not isinstance(verifier, _OscMapping):
            raise _osc_error(
                "MANAGER_CAPABILITY_UNKNOWN",
                "manager capability verifier is absent",
                details={"capability_id": request.capability_id},
            )
        try:
            resolved_secret = self._secret_resolver(
                request.capability_id
            )
        except Exception as exc:
            raise _osc_error(
                "MANAGER_CAPABILITY_SECRET_UNAVAILABLE",
                "manager-scoped secret could not be resolved",
            ) from exc
        if not isinstance(resolved_secret, bytearray):
            raise _osc_error(
                "MANAGER_CAPABILITY_SECRET_UNAVAILABLE",
                "manager-scoped secret resolver must transfer one mutable owned buffer",
            )
        secret = resolved_secret
        try:
            authorization = consume_manager_capability_request(
                verifier,
                request,
                principal,
                manager_secret=secret,
                wall_time_ns=self._wall_time_ns(),
                monotonic_time_ns=self._monotonic_ns(),
                clock_id=self._clock_id,
            )
        finally:
            _manager_zeroize(secret)
        capabilities[request.capability_id] = (
            authorization.verifier_state.as_persistent_dict()
        )
        return authorization

    def _frozen_legacy_authorize_manager_direct(
        self,
        task_id: str,
        *,
        expected_revision: int,
        manager_session_id: str,
        allowed_actions: _OscSequence[str] = ORCHESTRATION_MANAGER_ACTIONS,
        ttl_ns: int,
        operator_confirmed: bool,
        operator_confirmation_sha256: str,
        issuance_audit_sha256: str,
        secret_transport: str = "local-secret-channel",
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        inspected = load_state(task_id, data_dir)
        if inspected.get("schema_version") == 3:
            raise _osc_error(
                "ORCHESTRATION_LEGACY_MANAGER_PATH_FORBIDDEN",
                "schema-v3 manager issuance must use its catalog action transaction",
            )
        if operator_confirmed is not True:
            raise _osc_error(
                "MANAGER_CAPABILITY_OPERATOR_CONFIRMATION_REQUIRED",
                "manager authorization requires explicit operator confirmation",
            )
        requested_actions = tuple(allowed_actions)
        if (
            not requested_actions
            or any(
                not isinstance(action, str) or not action
                for action in requested_actions
            )
            or len(requested_actions) != len(set(requested_actions))
            or tuple(
                sorted(
                    requested_actions,
                    key=lambda item: str(item).encode("utf-8"),
                )
            )
            != requested_actions
        ):
            raise _osc_error(
                "MANAGER_CAPABILITY_ACTION_SCOPE_INVALID",
                "manager actions must be a canonical package-owned action set",
            )
        secret = self._random_bytes(32)
        if not isinstance(secret, bytearray) or len(secret) != 32:
            raise _osc_error(
                "MANAGER_CAPABILITY_SECRET_GENERATION_FAILED",
                "secret source must transfer exactly one mutable 256-bit buffer",
            )
        try:
            with _locked_state(
                task_id,
                data_dir,
                expected_revision,
                manager_effect_policy="formal",
            ) as (task_dir, state):
                old_state = _osc_copy.deepcopy(state)
                new_state = _osc_copy.deepcopy(state)
                orchestration = _osc_state_copy(new_state)
                package_actions = set(_manager_default_actions(state))
                if not set(requested_actions).issubset(
                    package_actions
                ):
                    raise _osc_error(
                        "MANAGER_CAPABILITY_ACTION_SCOPE_INVALID",
                        "manager actions must be declared by the pinned bundle and sealed command registries",
                        details={
                            "unknown_actions": sorted(
                                set(requested_actions)
                                - package_actions
                            )
                        },
                    )
                verifier = issue_manager_capability(
                    task_id=task_id,
                    issued_for_task_revision=expected_revision,
                    manager_session_id=manager_session_id,
                    allowed_actions=requested_actions,
                    ttl_ns=ttl_ns,
                    wall_time_ns=self._wall_time_ns(),
                    monotonic_time_ns=self._monotonic_ns(),
                    clock_id=self._clock_id,
                    secret_transport=secret_transport,
                    operator_confirmation_sha256=(
                        operator_confirmation_sha256
                    ),
                    issuance_audit_sha256=issuance_audit_sha256,
                    manager_secret=secret,
                )
                if self._secret_publisher is None:
                    raise _osc_error(
                        "MANAGER_CAPABILITY_SECRET_CHANNEL_UNAVAILABLE",
                        "manager authorization requires an injected secret publisher",
                    )
                capabilities = orchestration["manager_capabilities"]
                assert isinstance(capabilities, dict)
                capabilities[verifier.capability_id] = (
                    verifier.as_persistent_dict()
                )
                new_state["orchestration"] = orchestration
                payload = {
                    "capability_id": verifier.capability_id,
                    "manager_session_id": manager_session_id,
                    "allowed_actions": list(verifier.allowed_actions),
                    "secret_transport": secret_transport,
                }
                event = _osc_commit_control_event(
                    old_state,
                    new_state,
                    task_dir,
                    "orchestration_manager_authorized",
                    payload,
                    operation_id=ORCHESTRATION_OPERATOR_AUTHORIZE,
                )
                try:
                    self._secret_publisher(
                        verifier.capability_id, secret
                    )
                except Exception as publication_exc:
                    raise _osc_error(
                        "MANAGER_CAPABILITY_SECRET_PUBLICATION_PENDING",
                        "manager verifier committed but its local secret publication did not complete; revoke and reissue through the operator path",
                        details={
                            "capability_id": verifier.capability_id,
                            "revision": event.get("revision"),
                        },
                    ) from publication_exc
                return _osc_receipt(
                    event, authorization_id=None, payload=payload
                )
        except Exception as exc:
            raise _osc_translate(exc) from exc
        finally:
            if isinstance(secret, bytearray):
                _manager_zeroize(secret)

    def authorize_manager(
        self,
        task_id: str,
        *,
        expected_revision: int,
        manager_session_id: str,
        allowed_actions: _OscSequence[str] = ORCHESTRATION_MANAGER_ACTIONS,
        ttl_ns: int,
        operator_confirmed: bool,
        operator_confirmation_sha256: str,
        issuance_audit_sha256: str,
        secret_transport: str = "local-secret-channel",
        data_dir: object = None,
        failure_hook: _OscOptional[
            _OscCallable[[str], None]
        ] = None,
    ) -> OrchestrationCommitReceipt:
        if operator_confirmed is not True:
            raise _osc_error(
                "MANAGER_CAPABILITY_OPERATOR_CONFIRMATION_REQUIRED",
                "manager authorization requires explicit operator confirmation",
            )
        requested_actions = tuple(allowed_actions)
        if (
            not requested_actions
            or tuple(
                sorted(
                    set(requested_actions), key=_osc_utf8_sort_key
                )
            )
            != requested_actions
        ):
            raise _osc_error(
                "MANAGER_CAPABILITY_ACTION_SCOPE_INVALID",
                "manager actions must be a canonical exact-operation set",
            )
        if self._secret_publisher is None:
            raise _osc_error(
                "MANAGER_CAPABILITY_SECRET_CHANNEL_UNAVAILABLE",
                "manager authorization requires an injected secret publisher",
            )
        secret = self._random_bytes(32)
        if not isinstance(secret, bytearray) or len(secret) != 32:
            raise _osc_error(
                "MANAGER_CAPABILITY_SECRET_GENERATION_FAILED",
                "secret source must transfer exactly one mutable 256-bit buffer",
            )
        try:
            operator = _manager_local_principal(
                "orchestration-operator", role="operator"
            )
            with _osc_locked_current_state(
                task_id, data_dir, require_multi=False
            ) as (task_dir, state):
                _check_revision(state, expected_revision)
                old_state = _osc_copy.deepcopy(state)
                package_actions = set(
                    _manager_default_actions(old_state)
                )
                if not set(requested_actions).issubset(
                    package_actions
                ):
                    raise _osc_error(
                        "MANAGER_CAPABILITY_ACTION_SCOPE_INVALID",
                        "manager actions are absent from the pinned bundle",
                        details={
                            "unknown_actions": sorted(
                                set(requested_actions)
                                - package_actions,
                                key=_osc_utf8_sort_key,
                            )
                        },
                    )
                verifier = issue_manager_capability(
                    task_id=task_id,
                    issued_for_task_revision=expected_revision,
                    manager_session_id=manager_session_id,
                    allowed_actions=requested_actions,
                    ttl_ns=ttl_ns,
                    wall_time_ns=self._wall_time_ns(),
                    monotonic_time_ns=self._monotonic_ns(),
                    clock_id=self._clock_id,
                    secret_transport=secret_transport,
                    operator_confirmation_sha256=(
                        operator_confirmation_sha256
                    ),
                    issuance_audit_sha256=issuance_audit_sha256,
                    manager_secret=secret,
                )
                candidate, _registry_operation = (
                    _manager_registry_candidate(
                        old_state,
                        operation="authorize",
                        verifier=verifier,
                    )
                )
                channel_binding_sha256 = semantic_sha256(
                    b"dev-flow-manager-secret-channel-binding-v1\0",
                    {
                        "task_id": task_id,
                        "capability_id": verifier.capability_id,
                        "transport": secret_transport,
                    },
                )
                publication_plan = {
                    "schema": (
                        MANAGER_SECRET_PUBLICATION_PLAN_SCHEMA
                    ),
                    "effect": "secret-publication",
                    "publication_required": True,
                    "transport": secret_transport,
                    "channel_binding_sha256": (
                        channel_binding_sha256
                    ),
                }
                action_parameters = (
                    manager_registry_action_parameters_v1(
                        old_state,
                        operation="authorize",
                        verifier=verifier,
                        principal=operator,
                        secret_publication=publication_plan,
                    )
                )
                payload = {
                    "capability_id": verifier.capability_id,
                    "manager_session_id": manager_session_id,
                    "allowed_actions": list(
                        verifier.allowed_actions
                    ),
                    "expires_at_wall_ns": (
                        verifier.expires_at_wall_ns
                    ),
                    "secret_transport": secret_transport,
                    "operator_confirmation_sha256": (
                        operator_confirmation_sha256
                    ),
                    "issuance_audit_sha256": (
                        issuance_audit_sha256
                    ),
                }
                authorization = (
                    _osc_operator_workflow_authorization(
                        old_state,
                        operation_id=(
                            ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE
                        ),
                        principal=operator,
                        request_nonce_sha256=semantic_sha256(
                            b"dev-flow-manager-issuance-nonce-v1\0",
                            {
                                "task_id": task_id,
                                "revision": expected_revision,
                                "capability_id": (
                                    verifier.capability_id
                                ),
                                "issuance_audit_sha256": (
                                    issuance_audit_sha256
                                ),
                            },
                        ),
                        authorization_facts=payload,
                    )
                )
                selection = resolve_catalog_orchestration_action(
                    old_state,
                    ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE,
                )
                verifier_sha256 = _osc_digest(
                    verifier.as_persistent_dict()
                )
                effect_inputs = (
                    _osc_single_dispatch_effect_inputs(
                        selection,
                        kind="external",
                        scopes=_osc_effect_scopes(
                            node_ids=("manager-registry",),
                            external_resources=(
                                "manager-secret-channel-"
                                + channel_binding_sha256,
                            ),
                        ),
                        safe_inputs={
                            "registry_record_id": (
                                verifier.capability_id
                            ),
                            "verifier_sha256": verifier_sha256,
                            "channel_binding_sha256": (
                                channel_binding_sha256
                            ),
                        },
                        attempt_id=(
                            "manager-authorize-"
                            + _osc_digest(
                                {
                                    "capability_id": (
                                        verifier.capability_id
                                    ),
                                    "verifier_sha256": (
                                        verifier_sha256
                                    ),
                                }
                            )[:32]
                        ),
                    )
                )
                execution_id = (
                    "manager-authorize-"
                    + _osc_digest(
                        {
                            "task_id": task_id,
                            "revision": expected_revision,
                            "capability_id": (
                                verifier.capability_id
                            ),
                            "verifier_sha256": verifier_sha256,
                        }
                    )
                )

                def publish(context: object) -> object:
                    self._secret_publisher(
                        verifier.capability_id, secret
                    )
                    return _osc_quiesced_effect_observation(
                        context,
                        receipt_facts={
                            "capability_id": (
                                verifier.capability_id
                            ),
                            "verifier_sha256": verifier_sha256,
                            "publication_plan_sha256": (
                                _osc_digest(publication_plan)
                            ),
                        },
                    )

            result = _osc_execute_authoritative_transaction(
                old_state,
                candidate,
                task_dir,
                operation_id=(
                    ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE
                ),
                event_payload=payload,
                authorization=authorization,
                action_parameters=action_parameters,
                effect_inputs=effect_inputs,
                execution_id=execution_id,
                dispatcher=publish,
                failure_hook=failure_hook,
            )
            if result.status != "COMMITTED":
                raise _osc_error(
                    "ORCHESTRATION_ACTION_TRANSACTION_INCOMPLETE",
                    "manager authorization did not reach an atomic commit",
                    details={
                        "status": result.status,
                        "execution_id": execution_id,
                    },
                )
            event = _osc_committed_event(
                task_dir,
                task_id=task_id,
                event_type=selection.canonical_event,
                payload_key="operation_id",
                payload_value=(
                    ORCHESTRATION_OPERATION_MANAGER_AUTHORIZE
                ),
                expected_revision=expected_revision + 1,
            )
            return _osc_receipt(
                event,
                authorization_id=None,
                payload=payload,
            )
        except Exception as exc:
            raise _osc_translate(exc) from exc
        finally:
            _manager_zeroize(secret)

    def revoke_manager(
        self,
        task_id: str,
        *,
        expected_revision: int,
        capability_id: str,
        reason: str,
        revocation_audit_sha256: str,
        operator_confirmed: bool,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        if operator_confirmed is not True:
            raise _osc_error(
                "MANAGER_CAPABILITY_OPERATOR_CONFIRMATION_REQUIRED",
                "manager revocation requires explicit operator confirmation",
            )
        try:
            operator = _manager_local_principal(
                "orchestration-operator", role="operator"
            )
            with _osc_locked_current_state(
                task_id, data_dir, require_multi=False
            ) as (task_dir, state):
                _check_revision(state, expected_revision)
                old_state = _osc_copy.deepcopy(state)
                orchestration = _osc_state_copy(old_state)
                capabilities = orchestration["manager_capabilities"]
                assert isinstance(capabilities, dict)
                verifier = capabilities.get(capability_id)
                if not isinstance(verifier, _OscMapping):
                    raise _osc_error(
                        "MANAGER_CAPABILITY_UNKNOWN",
                        "manager capability verifier is absent",
                        details={"capability_id": capability_id},
                    )
                revoked = revoke_manager_capability(
                    verifier,
                    revoked_at_wall_ns=self._wall_time_ns(),
                    reason=reason,
                    revocation_audit_sha256=revocation_audit_sha256,
                )
                candidate, _registry_operation = (
                    _manager_registry_candidate(
                        old_state,
                        operation="revoke",
                        verifier=revoked,
                    )
                )
                payload = {
                    "capability_id": capability_id,
                    "manager_session_id": (
                        revoked.manager_session_id
                    ),
                    "reason": reason,
                    "revoked_at_wall_ns": (
                        revoked.revoked_at_wall_ns
                    ),
                    "revocation_audit_sha256": (
                        revocation_audit_sha256
                    ),
                }
                action_parameters = (
                    manager_registry_action_parameters_v1(
                        old_state,
                        operation="revoke",
                        verifier=revoked,
                        principal=operator,
                    )
                )
                authorization = (
                    _osc_operator_workflow_authorization(
                        old_state,
                        operation_id=(
                            ORCHESTRATION_OPERATION_MANAGER_REVOKE
                        ),
                        principal=operator,
                        request_nonce_sha256=semantic_sha256(
                            b"dev-flow-manager-revocation-nonce-v1\0",
                            {
                                "task_id": task_id,
                                "revision": expected_revision,
                                "capability_id": capability_id,
                                "revocation_audit_sha256": (
                                    revocation_audit_sha256
                                ),
                            },
                        ),
                        authorization_facts=payload,
                    )
                )
            result = _osc_execute_authoritative_transaction(
                old_state,
                candidate,
                task_dir,
                operation_id=(
                    ORCHESTRATION_OPERATION_MANAGER_REVOKE
                ),
                event_payload=payload,
                authorization=authorization,
                action_parameters=action_parameters,
            )
            if result.status != "COMMITTED_EFFECT_FREE":
                raise _osc_error(
                    "ORCHESTRATION_ACTION_TRANSACTION_INCOMPLETE",
                    "manager revocation did not commit atomically",
                    details={"status": result.status},
                )
            selection = resolve_catalog_orchestration_action(
                old_state,
                ORCHESTRATION_OPERATION_MANAGER_REVOKE,
            )
            event = _osc_committed_event(
                task_dir,
                task_id=task_id,
                event_type=selection.canonical_event,
                payload_key="operation_id",
                payload_value=(
                    ORCHESTRATION_OPERATION_MANAGER_REVOKE
                ),
                expected_revision=expected_revision + 1,
            )
            return _osc_receipt(
                event, authorization_id=None, payload=payload
            )
        except Exception as exc:
            raise _osc_translate(exc) from exc

    def record_artifact(
        self,
        task_id: str,
        *,
        artifact_id: str,
        content: bytes,
        kind: str,
        semantic_sha256: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        content_sha256 = (
            _osc_hashlib.sha256(content).hexdigest()
            if isinstance(content, bytes)
            else None
        )
        if semantic_sha256 != content_sha256:
            raise _osc_error(
                "ORCHESTRATION_ARTIFACT_SEMANTIC_DIGEST_MISMATCH",
                "external artifact semantic digest must equal controller-computed content SHA-256",
                details={
                    "expected": content_sha256,
                    "actual": semantic_sha256,
                },
            )

        reference = _osc_artifact_reference(
            artifact_id=artifact_id,
            content=content,
            kind=kind,
            semantic_sha256=str(content_sha256),
        )

        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            artifacts = orchestration["artifacts"]
            assert isinstance(artifacts, dict)
            prior = artifacts.get(artifact_id)
            if prior is not None and prior != reference:
                raise _osc_error(
                    "ORCHESTRATION_ARTIFACT_IDENTITY_CONFLICT",
                    "artifact identity already has different persisted facts",
                    details={"artifact_id": artifact_id},
                )
            artifacts[artifact_id] = _osc_copy.deepcopy(reference)
            return _osc_copy.deepcopy(reference)

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            _payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> tuple[
            _OscMapping[str, object],
            str,
            _OscCallable[[object], object],
        ]:
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-artifact-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "artifact_id": artifact_id,
                        "sha256": reference["sha256"],
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="filesystem",
                scopes=_osc_effect_scopes(
                    repository_ids=("controller",),
                    node_ids=("controller-artifacts",),
                    worktree_ids=("controller-artifacts",),
                    paths=(
                        str(
                            (
                                task_dir / str(reference["locator"])
                            ).resolve()
                        ),
                    ),
                ),
                safe_inputs={
                    "artifact_id": artifact_id,
                    "content_sha256": reference["sha256"],
                    "locator": reference["locator"],
                },
                attempt_id=(
                    "artifact-"
                    + _osc_digest(reference)[:32]
                ),
            )

            def dispatch(context: object) -> object:
                _osc_publish_artifact(
                    task_dir, reference, content
                )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "artifact_id": artifact_id,
                        "content_sha256": reference["sha256"],
                        "locator": reference["locator"],
                    },
                )

            return effect_inputs, execution_id, dispatch

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_ARTIFACT_RECORD,
            event_type="orchestration_artifact_recorded",
            operation_facts={
                "artifact_id": artifact_id,
                "kind": kind,
                "content_sha256": content_sha256,
            },
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def _simple_authorized_mutation(
        self,
        *,
        task_id: str,
        data_dir: object,
        request: object,
        principal: object,
        action_id: str,
        event_type: str,
        operation_facts: _OscOptional[
            _OscMapping[str, object]
        ] = None,
        mutate: _OscCallable[
            [_OscPath, dict[str, object], dict[str, object]],
            _OscMapping[str, object],
        ],
        effect_builder: _OscOptional[
            _OscCallable[
                [
                    _OscPath,
                    _OscMapping[str, object],
                    _OscMapping[str, object],
                    _OscMapping[str, object],
                    object,
                    object,
                ],
                _OscSequence[object],
            ]
        ] = None,
    ) -> OrchestrationCommitReceipt:
        try:
            task_dir_for_recovery = _task_dir(
                task_id, data_dir
            )
            _osc_recover_committed_runtime_reservation_releases(
                task_dir_for_recovery,
                task_id=task_id,
            )
            parsed_request = validate_manager_capability_request(request)
            if parsed_request.action_id != action_id:
                raise _osc_error(
                    "MANAGER_CAPABILITY_ACTION_MISMATCH",
                    "manager request does not bind the exact authoritative operation",
                    details={
                        "expected": action_id,
                        "actual": parsed_request.action_id,
                    },
                )
            with _osc_locked_current_state(
                task_id, data_dir
            ) as (_inspected_task_dir, inspected):
                _check_revision(
                    inspected, parsed_request.expected_revision
                )
                selection = resolve_catalog_orchestration_action(
                    inspected, action_id
                )
            operation_fingerprint_sha256 = semantic_sha256(
                _OSC_AUTHORITATIVE_OPERATION_FINGERPRINT_DOMAIN,
                {
                    "task_id": task_id,
                    "expected_revision": (
                        parsed_request.expected_revision
                    ),
                    "operation_id": action_id,
                    "event_id": selection.event_id,
                    "facts": _osc_copy.deepcopy(
                        _osc_thaw(operation_facts or {})
                    ),
                },
            )
            with _manager_authority_context(
                request=parsed_request,
                action_id=action_id,
                secret_resolver=lambda: self._secret_resolver(
                    parsed_request.capability_id
                ),
                principal=principal,
                operation_fingerprint_sha256=(
                    operation_fingerprint_sha256
                ),
                wall_time_ns=self._wall_time_ns,
                monotonic_time_ns=self._monotonic_ns,
                clock_id=self._clock_id,
            ):
                with _osc_locked_current_state(
                    task_id, data_dir
                ) as (task_dir, state):
                    _check_revision(
                        state, parsed_request.expected_revision
                    )
                    locked_selection = (
                        resolve_catalog_orchestration_action(
                            state, action_id
                        )
                    )
                    if locked_selection != selection:
                        raise _osc_error(
                            "ORCHESTRATION_ACTION_CATALOG_DRIFT",
                            "orchestration action selection changed before preauthorization",
                            details={"operation_id": action_id},
                        )
                    old_state = _osc_copy.deepcopy(state)
                    manager_process_commit_gate_v1(
                        old_state,
                        old_state,
                        "manager_effect_preauthorized",
                        _effect_lifecycle=(
                            "preauthorize",
                            "generic",
                        ),
                        _effect_package_action_id=action_id,
                    )
                    prepared = _manager_engine_evaluation_state_v1(
                        old_state,
                        event_type=selection.canonical_event,
                    )
                    if not isinstance(prepared, dict):
                        raise _osc_error(
                            "MANAGER_PREAUTHORIZATION_REQUIRED",
                            "authoritative orchestration action has no nonce-prepared engine state",
                        )
                    new_state = _osc_copy.deepcopy(prepared)
                    orchestration = _osc_state_copy(new_state)
                    (
                        _invocation,
                        _validated_request,
                        preauthorization,
                    ) = _manager_validated_preauthorization_v1(
                        old_state,
                        event_type=selection.canonical_event,
                    )
                    authorization = (
                        _manager_workflow_action_authorization_v1(
                            old_state,
                            event_type=selection.canonical_event,
                        )
                    )
                    payload = dict(
                        _osc_thaw(
                            mutate(
                                task_dir,
                                new_state,
                                orchestration,
                            )
                        )
                    )
                    payload["manager_authorization_id"] = (
                        preauthorization.authorization.authorization_id
                    )
                    payload["manager_capability_id"] = (
                        preauthorization.authorization.capability_id
                    )
                    new_state["orchestration"] = orchestration
                    effect_inputs = None
                    execution_id = None
                    dispatcher = None
                    runtime_release_adapter = None
                    runtime_observer = None
                    target_execution_id = None
                    control_action_id = None
                    if effect_builder is not None:
                        built_effect = effect_builder(
                            task_dir,
                            old_state,
                            new_state,
                            payload,
                            selection,
                            preauthorization,
                        )
                        if len(built_effect) == 3:
                            (
                                effect_inputs,
                                execution_id,
                                dispatcher,
                            ) = built_effect
                        elif len(built_effect) == 5:
                            (
                                effect_inputs,
                                execution_id,
                                dispatcher,
                                runtime_release_adapter,
                                runtime_observer,
                            ) = built_effect
                        elif len(built_effect) == 7:
                            (
                                effect_inputs,
                                execution_id,
                                dispatcher,
                                runtime_release_adapter,
                                runtime_observer,
                                target_execution_id,
                                control_action_id,
                            ) = built_effect
                            if (
                                not isinstance(
                                    target_execution_id, str
                                )
                                or not target_execution_id
                                or not isinstance(
                                    control_action_id, str
                                )
                                or not control_action_id
                            ):
                                raise _osc_error(
                                    "ORCHESTRATION_ACTION_CONTROL_BINDING_INVALID",
                                    "target control effect lacks exact target and action identities",
                                )
                            payload["target_execution_id"] = (
                                target_execution_id
                            )
                            payload["control_action_id"] = (
                                control_action_id
                            )
                        else:
                            raise _osc_error(
                                "ORCHESTRATION_ACTION_EFFECT_BINDING_INVALID",
                                "effect builder returned an unsupported lifecycle shape",
                            )
                result = _osc_execute_authoritative_transaction(
                    old_state,
                    new_state,
                    task_dir,
                    operation_id=action_id,
                    event_payload=payload,
                    authorization=authorization,
                    effect_inputs=effect_inputs,
                    execution_id=execution_id,
                    dispatcher=dispatcher,
                    runtime_release_adapter=(
                        runtime_release_adapter
                    ),
                    runtime_observer=runtime_observer,
                    target_execution_id=target_execution_id,
                    control_action_id=control_action_id,
                )
                expected_status = (
                    "COMMITTED"
                    if effect_builder is not None
                    else "COMMITTED_EFFECT_FREE"
                )
                if result.status != expected_status:
                    raise _osc_error(
                        "ORCHESTRATION_ACTION_TRANSACTION_INCOMPLETE",
                        "orchestration action did not close atomically",
                        details={
                            "operation_id": action_id,
                            "status": result.status,
                            "expected_status": expected_status,
                        },
                    )
                committed_revision = (
                    parsed_request.expected_revision + 1
                )
                committed_execution_id = None
                committed_receipt_sha256 = None
                if effect_builder is not None:
                    finalization = (
                        result.journal.get("finalization")
                        if isinstance(
                            result.journal, _OscMapping
                        )
                        else None
                    )
                    verified_receipt = (
                        result.journal.get("receipt")
                        if isinstance(
                            result.journal, _OscMapping
                        )
                        else None
                    )
                    if (
                        not isinstance(
                            finalization, _OscMapping
                        )
                        or isinstance(
                            finalization.get(
                                "task_commit_revision"
                            ),
                            bool,
                        )
                        or not isinstance(
                            finalization.get(
                                "task_commit_revision"
                            ),
                            int,
                        )
                        or not isinstance(
                            verified_receipt, _OscMapping
                        )
                        or not isinstance(
                            verified_receipt.get(
                                "receipt_sha256"
                            ),
                            str,
                        )
                        or not isinstance(
                            result.execution_id, str
                        )
                    ):
                        raise _osc_error(
                            "ORCHESTRATION_ACTION_FINALIZATION_INVALID",
                            "orchestration transaction returned no exact finalization binding",
                            details={"operation_id": action_id},
                        )
                    committed_revision = finalization[
                        "task_commit_revision"
                    ]
                    committed_execution_id = result.execution_id
                    committed_receipt_sha256 = verified_receipt[
                        "receipt_sha256"
                    ]
                event = _osc_committed_event(
                    task_dir,
                    task_id=task_id,
                    event_type=selection.canonical_event,
                    payload_key="operation_id",
                    payload_value=action_id,
                    expected_revision=committed_revision,
                    expected_authorization_id=(
                        preauthorization.authorization.authorization_id
                    ),
                    expected_execution_id=committed_execution_id,
                    expected_receipt_sha256=(
                        committed_receipt_sha256
                    ),
                )
                if target_execution_id is not None:
                    finalization = (
                        result.journal.get("finalization")
                        if isinstance(result.journal, _OscMapping)
                        else None
                    )
                    proof_sha256 = payload.get("proof_sha256")
                    event_sha256 = (
                        finalization.get("event_sha256")
                        if isinstance(
                            finalization, _OscMapping
                        )
                        else None
                    )
                    if (
                        not isinstance(proof_sha256, str)
                        or not isinstance(event_sha256, str)
                    ):
                        raise _osc_error(
                            "ORCHESTRATION_RUNTIME_RESERVATION_RELEASE_INVALID",
                            "target control commit lacks exact quiescence and event bindings",
                        )
                    _osc_release_runtime_reservation_target(
                        task_dir,
                        task_id=task_id,
                        target_execution_id=(
                            target_execution_id
                        ),
                        control_action_id=str(
                            control_action_id
                        ),
                        quiescence_sha256=proof_sha256,
                        event_sha256=event_sha256,
                        authoritative_event=event,
                    )
                return _osc_receipt(
                    event,
                    authorization_id=(
                        preauthorization.authorization.authorization_id
                    ),
                    payload=payload,
                )
        except Exception as exc:
            raise _osc_translate(exc) from exc

    def record_plan(
        self,
        task_id: str,
        plan_value: object,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        prepared_artifact: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            bundle = _osc_resolve_multi_bundle(state)
            plan = validate_repository_plan_against_workflow_bundle(
                plan_value, bundle
            )
            workflow_ref = state.get("workflow_ref")
            if not isinstance(workflow_ref, _OscMapping):
                raise _osc_error(
                    "WORKFLOW_REF_REQUIRED",
                    "v3 task has no pinned workflow reference",
                )
            if (
                plan["task_id"] != task_id
                or plan["workflow_bundle_sha256"]
                != workflow_ref.get("bundle_sha256")
                or int(plan["plan_input_revision"])
                != int(state["revision"])
            ):
                raise _osc_error(
                    "REPOSITORY_PLAN_TASK_BINDING_MISMATCH",
                    "repository plan does not bind the current task input",
                )
            artifact_index = orchestration["artifacts"]
            assert isinstance(artifact_index, dict)
            available = {
                key: value["sha256"]
                for key, value in artifact_index.items()
                if isinstance(value, dict)
                and isinstance(value.get("sha256"), str)
            }
            validate_repository_plan_contract_artifacts(plan, available)
            artifact = build_repository_plan_artifact(plan)
            reference = _osc_artifact_reference(
                artifact_id=artifact.artifact_id,
                content=artifact.content,
                kind=REPOSITORY_PLAN_SCHEMA,
                semantic_sha256=artifact.semantic_input_sha256,
            )
            prior_reference = artifact_index.get(
                artifact.artifact_id
            )
            if (
                prior_reference is not None
                and prior_reference != reference
            ):
                raise _osc_error(
                    "ORCHESTRATION_ARTIFACT_IDENTITY_CONFLICT",
                    "plan artifact identity already has different persisted facts",
                    details={
                        "artifact_id": artifact.artifact_id
                    },
                )
            artifact_index[artifact.artifact_id] = reference
            prepared_artifact.clear()
            prepared_artifact.update(
                {
                    "content": artifact.content,
                    "reference": reference,
                }
            )
            record = {
                "artifact_id": artifact.artifact_id,
                "artifact_sha256": artifact.sha256,
                "dag_sha256": artifact.dag_sha256,
                "semantic_input_sha256": (
                    artifact.semantic_input_sha256
                ),
                "plan_id": plan["plan_id"],
                "map_epoch": plan["map_epoch"],
                "plan_input_revision": plan["plan_input_revision"],
            }
            existing = orchestration.get("plan")
            if existing is not None and existing != record:
                if not isinstance(existing, dict):
                    raise _osc_error(
                        "REPOSITORY_PLAN_STATE_INVALID",
                        "persisted plan record is invalid",
                    )
                expansion = orchestration.get("expansion")
                if expansion is not None:
                    if (
                        not isinstance(expansion, _OscMapping)
                        or expansion.get("current") is not False
                        or not isinstance(
                            expansion.get("retired_at_revision"),
                            int,
                        )
                    ):
                        raise _osc_error(
                            "REPOSITORY_REPLAN_NODE_API_REQUIRED",
                            "expanded repository map must be formally stale and retired before replanning",
                        )
                    minimum_epoch = expansion.get(
                        "minimum_successor_map_epoch"
                    )
                    if (
                        isinstance(minimum_epoch, bool)
                        or not isinstance(minimum_epoch, int)
                        or int(plan["map_epoch"]) < minimum_epoch
                    ):
                        raise _osc_error(
                            "REPOSITORY_PLAN_MAP_EPOCH_NOT_MONOTONIC",
                            "replacement plan is below the formally retired map epoch bound",
                            details={
                                "minimum_successor_map_epoch": (
                                    minimum_epoch
                                ),
                                "map_epoch": plan["map_epoch"],
                            },
                        )
                if int(plan["map_epoch"]) <= int(
                    existing.get("map_epoch", 0)
                ):
                    raise _osc_error(
                        "REPOSITORY_PLAN_MAP_EPOCH_NOT_MONOTONIC",
                        "replacement plan must advance the map epoch",
                    )
                history = orchestration["plan_history"]
                assert isinstance(history, list)
                history.append(
                    {
                        **_osc_copy.deepcopy(existing),
                        "superseded_at_revision": int(
                            state["revision"]
                        )
                        + 1,
                    }
                )
                orchestration["approval"] = None
            orchestration["plan"] = record
            return record

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> tuple[
            _OscMapping[str, object],
            str,
            _OscCallable[[object], object],
        ]:
            reference = prepared_artifact.get("reference")
            content = prepared_artifact.get("content")
            if not isinstance(reference, _OscMapping) or not isinstance(
                content, bytes
            ):
                raise _osc_error(
                    "ORCHESTRATION_ARTIFACT_INVALID",
                    "plan action has no prepared artifact publication",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-plan-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "plan_id": payload.get("plan_id"),
                        "artifact_sha256": reference["sha256"],
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="filesystem",
                scopes=_osc_effect_scopes(
                    node_ids=("controller-plan",),
                    paths=(
                        str(
                            (
                                task_dir / str(reference["locator"])
                            ).resolve()
                        ),
                    ),
                ),
                safe_inputs={
                    "artifact_id": reference["id"],
                    "content_sha256": reference["sha256"],
                    "plan_id": payload.get("plan_id"),
                },
                attempt_id=(
                    "plan-" + _osc_digest(reference)[:32]
                ),
            )

            def dispatch(context: object) -> object:
                _osc_publish_artifact(
                    task_dir, reference, content
                )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "artifact_id": reference["id"],
                        "content_sha256": reference["sha256"],
                        "plan_id": payload.get("plan_id"),
                    },
                )

            return effect_inputs, execution_id, dispatch

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_ACTION_PLAN_RECORD,
            event_type="orchestration_plan_recorded",
            operation_facts={
                "plan_sha256": _osc_digest(plan_value)
            },
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def approve_plan(
        self,
        task_id: str,
        *,
        approval_intent: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        if approval_intent != "approve-repository-map/v1":
            raise _osc_error(
                "REPOSITORY_PLAN_APPROVAL_INTENT_INVALID",
                "repository plan approval intent is package-owned",
            )

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            plan = _osc_plan_from_state(task_dir, orchestration)
            approval = create_repository_plan_approval(
                plan,
                approval_intent=approval_intent,
                approval_commit_revision=int(state["revision"]) + 1,
            )
            prior = orchestration.get("approval")
            normalized = _osc_thaw(approval)
            if prior is not None and prior != normalized:
                raise _osc_error(
                    "REPOSITORY_PLAN_APPROVAL_CONFLICT",
                    "repository plan already has a different approval",
                )
            orchestration["approval"] = normalized
            return {
                "plan_id": plan["plan_id"],
                "approval_commit_revision": approval[
                    "approval_commit_revision"
                ],
                "dag_sha256": approval["dag_sha256"],
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_PLAN_APPROVE,
            event_type="orchestration_plan_approved",
            operation_facts={
                "approval_intent": approval_intent,
            },
            mutate=mutate,
        )

    def invalidate_map(
        self,
        task_id: str,
        *,
        phase: str,
        reason: _OscOptional[str] = None,
        minimum_successor_map_epoch: _OscOptional[int] = None,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Persist package-derived STALE or RETIRED map lifecycle facts."""

        if phase == "RETIRED" and (
            reason is not None
            or minimum_successor_map_epoch is not None
        ):
            raise _osc_error(
                "V3_MAP_INVALIDATION_INPUT_INVALID",
                "retirement reuses the persisted stale facts and accepts no replacement inputs",
            )

        def mutate(
            _task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            expansion_value = orchestration.get("expansion")
            if not isinstance(expansion_value, dict):
                raise _osc_error(
                    "V3_MAP_INVALIDATION_EXPANSION_REQUIRED",
                    "map invalidation requires a persisted expansion",
                )
            expansion = _osc_copy.deepcopy(expansion_value)
            children = expansion.get("children")
            if not isinstance(children, list) or not children:
                raise _osc_error(
                    "V3_MAP_INVALIDATION_EXPANSION_INVALID",
                    "map invalidation requires canonical persisted children",
                )
            node_ids = sorted(
                (
                    str(child["node_instance_id"])
                    for child in children
                    if isinstance(child, dict)
                    and isinstance(
                        child.get("node_instance_id"), str
                    )
                ),
                key=_osc_utf8_sort_key,
            )
            if len(node_ids) != len(children):
                raise _osc_error(
                    "V3_MAP_INVALIDATION_EXPANSION_INVALID",
                    "map invalidation child identities are invalid",
                )
            next_revision = int(state["revision"]) + 1
            if phase == "STALE":
                if expansion.get("current", True) is not True:
                    raise _osc_error(
                        "V3_MAP_INVALIDATION_ALREADY_STALE",
                        "only a current map can enter the stale phase",
                    )
                if not isinstance(reason, str) or not reason.strip():
                    raise _osc_error(
                        "V3_MAP_INVALIDATION_REASON_REQUIRED",
                        "map invalidation requires one stable reason",
                    )
                map_epoch = expansion.get("map_epoch")
                if (
                    isinstance(map_epoch, bool)
                    or not isinstance(map_epoch, int)
                    or isinstance(
                        minimum_successor_map_epoch, bool
                    )
                    or not isinstance(
                        minimum_successor_map_epoch, int
                    )
                    or minimum_successor_map_epoch <= map_epoch
                ):
                    raise _osc_error(
                        "V3_MAP_SUCCESSOR_EPOCH_INVALID",
                        "successor map epoch must exceed the stale epoch",
                    )
                core = {
                    "task_id": task_id,
                    "plan_id": expansion.get("plan_id"),
                    "map_epoch": map_epoch,
                    "node_instance_ids": node_ids,
                    "reason": reason,
                    "stale_at_revision": next_revision,
                    "minimum_successor_map_epoch": (
                        minimum_successor_map_epoch
                    ),
                }
                expansion.update(
                    {
                        "current": False,
                        "stale_reason": reason,
                        "stale_at_revision": next_revision,
                        "stale_facts_sha256": _osc_digest(core),
                        "minimum_successor_map_epoch": (
                            minimum_successor_map_epoch
                        ),
                    }
                )
                orchestration["approval"] = None
            else:
                if (
                    expansion.get("current") is not False
                    or "retired_at_revision" in expansion
                ):
                    raise _osc_error(
                        "V3_MAP_RETIREMENT_STATE_INVALID",
                        "only a stale map can enter the retired phase",
                    )
                expansion["retired_at_revision"] = next_revision
                for node_id in node_ids:
                    _osc_find_node(state, node_id)[
                        "state"
                    ] = "SKIPPED"
            orchestration["expansion"] = expansion
            return {
                "phase": phase,
                "plan_id": expansion.get("plan_id"),
                "map_epoch": expansion.get("map_epoch"),
                "node_instance_ids": node_ids,
                "stale_facts_sha256": expansion.get(
                    "stale_facts_sha256"
                ),
                "minimum_successor_map_epoch": expansion.get(
                    "minimum_successor_map_epoch"
                ),
                **(
                    {
                        "reason": reason,
                        "stale_at_revision": expansion.get(
                            "stale_at_revision"
                        ),
                    }
                    if phase == "STALE"
                    else {
                        "retired_at_revision": expansion.get(
                            "retired_at_revision"
                        )
                    }
                ),
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_MAP_INVALIDATE,
            event_type="orchestration_map_invalidated",
            operation_facts={
                "phase": phase,
                "reason": reason,
                "minimum_successor_map_epoch": (
                    minimum_successor_map_epoch
                ),
            },
            mutate=mutate,
        )

    def expand_plan(
        self,
        task_id: str,
        *,
        current_semantic_input_sha256: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            bundle = _osc_resolve_multi_bundle(state)
            plan = _osc_plan_from_state(task_dir, orchestration)
            approval = _osc_approval_from_state(orchestration)
            persisted_semantic = str(
                plan["semantic_input_sha256"]
            )
            if current_semantic_input_sha256 != persisted_semantic:
                raise _osc_error(
                    "REPOSITORY_PLAN_SEMANTIC_INPUT_STALE",
                    "map expansion semantic input differs from the persisted plan",
                )
            prior = orchestration.get("expansion")
            replacing_retired = (
                isinstance(prior, _OscMapping)
                and prior.get("current") is False
                and isinstance(
                    prior.get("retired_at_revision"), int
                )
            )
            if prior is not None and not replacing_retired:
                raise _osc_error(
                    "REPOSITORY_MAP_EXPANSION_ALREADY_CURRENT",
                    "the current map expansion cannot be replayed as a new mutation",
                )
            expansion = expand_repository_map_for_workflow_bundle(
                plan,
                approval,
                bundle,
                current_semantic_input_sha256=persisted_semantic,
                existing_expansion=None,
            )
            normalized = _osc_thaw(expansion)
            if isinstance(normalized, dict):
                normalized["current"] = True
            orchestration["expansion"] = normalized
            nodes = state.get("node_instances")
            if not isinstance(nodes, list):
                raise _osc_error(
                    "NODE_INSTANCE_INVALID",
                    "v3 task node instances are invalid",
                )
            existing = {
                node.get("node_instance_id")
                for node in nodes
                if isinstance(node, dict)
            }
            node_ids: list[str] = []
            for child in expansion["children"]:
                identifier = str(child["node_instance_id"])
                if identifier in existing:
                    raise _osc_error(
                        "REPOSITORY_MAP_EXPANSION_CONFLICT",
                        "a map child identity is already present",
                        details={
                            "node_instance_id": identifier
                        },
                    )
                node_ids.append(identifier)
                nodes.append(
                    {
                        "node_instance_id": identifier,
                        "node_id": child["node_id"],
                        "state": "PENDING",
                        "dependencies": list(
                            child["dependencies"]
                        ),
                        "attempts": [],
                        "repository_id": child["repository_id"],
                    }
                )
            nodes.sort(
                key=lambda item: str(
                    item["node_instance_id"]
                ).encode("utf-8")
            )
            return {
                "plan_id": expansion["plan_id"],
                "map_epoch": expansion["map_epoch"],
                "expansion_sha256": (
                    repository_map_expansion_sha256(expansion)
                ),
                "node_instance_ids": node_ids,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_MAP_EXPAND,
            event_type="orchestration_map_expanded",
            operation_facts={
                "semantic_input_sha256": (
                    current_semantic_input_sha256
                )
            },
            mutate=mutate,
        )

    def advance_ready_frontier(
        self,
        task_id: str,
        *,
        node_instance_id: _OscOptional[str] = None,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Advance the complete package-recomputed PENDING frontier."""

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            plan = _osc_plan_from_state(task_dir, orchestration)
            _osc_current_expansion(orchestration)
            approval = _osc_approval_from_state(orchestration)
            repository_frontier = _osc_repository_frontier(
                plan, approval, state, orchestration
            )
            formal_facts = dict(v3_frontier_ready_facts(state))
            formal_ids = tuple(
                str(value)
                for value in formal_facts["node_instance_ids"]
            )
            repository_ids = tuple(
                item.node_instance_id
                for item in repository_frontier.ready
            )
            if not set(formal_ids).issubset(
                set(repository_ids)
            ):
                raise _osc_error(
                    "REPOSITORY_FRONTIER_POLICY_BLOCKED",
                    "the formal ready frontier exceeds the approved repository frontier",
                    details={
                        "dependency_frontier": list(formal_ids),
                        "repository_frontier": list(repository_ids),
                    },
                )
            selected = (
                node_instance_id
                if node_instance_id is not None
                else (
                    sorted(
                        formal_ids, key=_osc_utf8_sort_key
                    )[0]
                    if formal_ids
                    else None
                )
            )
            if selected not in formal_ids:
                raise _osc_error(
                    "REPOSITORY_FRONTIER_POLICY_BLOCKED",
                    "selected node is absent from the current ready frontier",
                    details={
                        "node_instance_id": selected,
                        "ready": list(formal_ids),
                    },
                )
            frontier = orchestration["frontier"]
            assert isinstance(frontier, dict)
            if selected in frontier:
                raise _osc_error(
                    "ORCHESTRATION_FRONTIER_ALREADY_ADVANCED",
                    "frontier advancement is single-use per node",
                    details={"node_instance_id": selected},
                )
            dependency_results = _osc_thaw(
                formal_facts["dependency_result_ids"]
            )
            record = {
                "state": "READY",
                "node_instance_id": selected,
                "plan_id": formal_facts["plan_id"],
                "dag_sha256": formal_facts["dag_sha256"],
                "map_epoch": formal_facts["map_epoch"],
                "dependency_result_ids": (
                    dependency_results.get(selected, {})
                    if isinstance(dependency_results, dict)
                    else {}
                ),
                "frontier_sha256": formal_facts[
                    "frontier_sha256"
                ],
            }
            frontier[str(selected)] = record
            _osc_find_node(state, str(selected))["state"] = "READY"
            return _osc_copy.deepcopy(record)

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_FRONTIER_ADVANCE,
            event_type="orchestration_frontier_advanced",
            operation_facts={
                "node_instance_id": node_instance_id
            },
            mutate=mutate,
        )

    def issue_lease(
        self,
        task_id: str,
        *,
        node_instance_id: str,
        worktree_path: str,
        input_evidence_sha256: str,
        allowed_actions: _OscSequence[str],
        lease_ttl_ns: int,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Issue only the lease credential for one advanced frontier node."""

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            cancellation = orchestration.get("cancellation")
            cancellation_requested = (
                isinstance(cancellation, _OscMapping)
                and cancellation.get("requested") is True
            )
            if cancellation_requested:
                raise _osc_error(
                    "WORKER_LEASE_CANCELLATION_REQUESTED",
                    "lease issue is blocked after cancellation",
                )
            frontier = orchestration["frontier"]
            assert isinstance(frontier, dict)
            frontier_record = frontier.get(node_instance_id)
            if (
                not isinstance(frontier_record, dict)
                or frontier_record.get("state") != "READY"
            ):
                raise _osc_error(
                    "REPOSITORY_NODE_NOT_READY",
                    "lease issue requires an independently advanced frontier node",
                    details={
                        "node_instance_id": node_instance_id
                    },
                )
            plan = _osc_plan_from_state(task_dir, orchestration)
            expansion = _osc_current_expansion(orchestration)
            approval = _osc_approval_from_state(orchestration)
            validate_repository_plan_approval(
                plan,
                approval,
                current_semantic_input_sha256=plan[
                    "semantic_input_sha256"
                ],
            )
            child = next(
                (
                    item
                    for item in expansion["children"]
                    if item["node_instance_id"]
                    == node_instance_id
                ),
                None,
            )
            if not isinstance(child, _OscMapping):
                raise _osc_error(
                    "NODE_INSTANCE_UNKNOWN",
                    "lease node is outside the current map expansion",
                )
            repository = next(
                item
                for item in plan["repositories"]
                if item["repository_id"]
                == child["repository_id"]
            )
            (
                worktree_binding,
                _branch,
                _head,
                _fingerprint,
                _paths,
                _paths_sha256,
            ) = _osc_bound_worktree_observation(worktree_path)
            retries = orchestration["retries"]
            assert isinstance(retries, dict)
            retry_attempts = [
                int(value.get("next_attempt", 0))
                for value in retries.values()
                if isinstance(value, dict)
                and value.get("node_instance_id")
                == node_instance_id
                and isinstance(value.get("next_attempt"), int)
            ]
            attempts = orchestration["attempts"]
            assert isinstance(attempts, dict)
            existing_attempts = [
                int(value.get("attempt", 0))
                for value in attempts.values()
                if isinstance(value, dict)
                and value.get("node_instance_id")
                == node_instance_id
                and isinstance(value.get("attempt"), int)
            ]
            attempt = max(
                [1, *retry_attempts, *existing_attempts]
            )
            if existing_attempts and attempt in existing_attempts:
                attempt += 1
            leases = orchestration["leases"]
            assert isinstance(leases, dict)
            lease = issue_worker_lease(
                {
                    "task_id": task_id,
                    "task_revision": int(state["revision"]),
                    "workflow_bundle_sha256": plan[
                        "workflow_bundle_sha256"
                    ],
                    "map_epoch": plan["map_epoch"],
                    "node_instance_id": node_instance_id,
                    "repository_id": repository["repository_id"],
                    "repository_identity_sha256": repository[
                        "identity_sha256"
                    ],
                    "worktree_identity_sha256": (
                        worktree_binding[
                            "worktree_identity_sha256"
                        ]
                    ),
                    "attempt": attempt,
                    "input_evidence_sha256": (
                        input_evidence_sha256
                    ),
                    "plan_dag_sha256": approval["dag_sha256"],
                    "semantic_input_sha256": plan[
                        "semantic_input_sha256"
                    ],
                    "interface_contract_sha256s": [
                        item["sha256"]
                        for item in plan["interface_contracts"]
                    ],
                    "approved_paths": list(
                        repository["approved_paths"]
                    ),
                    "allowed_actions": list(allowed_actions),
                    "write_policy": repository["write_policy"],
                },
                lease_nonce_bytes=bytes(self._random_bytes(32)),
                wall_time_ns=self._wall_time_ns(),
                monotonic_time_ns=self._monotonic_ns(),
                ttl_ns=lease_ttl_ns,
                clock_id=self._clock_id,
                existing_leases=list(leases.values()),
                cancellation_requested=False,
            )
            leases[lease.lease_id] = lease.as_dict()
            return {
                "lease_id": lease.lease_id,
                "node_instance_id": node_instance_id,
                "repository_id": repository["repository_id"],
                "attempt": attempt,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_LEASE_ISSUE,
            event_type="orchestration_lease_issued",
            operation_facts={
                "node_instance_id": node_instance_id,
                "worktree_path_sha256": _osc_hashlib.sha256(
                    worktree_path.encode("utf-8")
                ).hexdigest(),
                "input_evidence_sha256": input_evidence_sha256,
                "allowed_actions": list(allowed_actions),
                "lease_ttl_ns": lease_ttl_ns,
            },
            mutate=mutate,
        )

    def _frozen_legacy_issue_assignment_alias(
        self,
        task_id: str,
        *,
        node_instance_id: str,
        worktree_path: str,
        input_evidence_sha256: str,
        allowed_actions: _OscSequence[str],
        playbook_locator: str,
        playbook_sha256: str,
        required_evidence_contract_sha256s: _OscSequence[str],
        runtime_handle_id: _OscOptional[str],
        host_assignment_id: str,
        runtime_authentication_sha256: str,
        actor_id: str,
        lease_ttl_ns: int,
        lease_id: _OscOptional[str] = None,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Frozen overloaded adapter retained for non-v3 compatibility only."""

        inspected = load_state(task_id, data_dir)
        if inspected.get("schema_version") == 3:
            raise _osc_error(
                "ORCHESTRATION_LEGACY_ALIAS_FORBIDDEN",
                "schema-v3 callers must issue lease, assignment, and dispatch as separate authoritative operations",
                details={"alias_id": ORCHESTRATION_ACTION_ASSIGN},
            )
        try:
            parsed_request = validate_manager_capability_request(request)
            committed_receipt: _OscOptional[
                OrchestrationCommitReceipt
            ] = None
            committed_assignment: _OscOptional[dict[str, object]] = None
            with _locked_state(
                task_id,
                data_dir,
                parsed_request.expected_revision,
                manager_effect_policy="formal",
            ) as (task_dir, state):
                old_state = _osc_copy.deepcopy(state)
                new_state = _osc_copy.deepcopy(state)
                orchestration = _osc_state_copy(new_state)
                authorization = self._authorize(
                    orchestration,
                    parsed_request,
                    principal,
                    action_id=ORCHESTRATION_ACTION_ASSIGN,
                )
                sealed_authorization = (
                    _osc_preauthorize_manager_effect(
                        old_state,
                        orchestration,
                        authorization,
                        action_id=ORCHESTRATION_ACTION_ASSIGN,
                    )
                )
                cancellation = orchestration.get("cancellation")
                cancellation_requested = (
                    isinstance(cancellation, _OscMapping)
                    and cancellation.get("requested") is True
                )
                if cancellation_requested:
                    raise _osc_error(
                        "WORKER_LEASE_CANCELLATION_REQUESTED",
                        "worker assignment is blocked after cancellation is requested",
                    )
                plan = _osc_plan_from_state(task_dir, orchestration)
                expansion = _osc_current_expansion(orchestration)
                approval = _osc_approval_from_state(orchestration)
                validate_repository_plan_approval(
                    plan,
                    approval,
                    current_semantic_input_sha256=plan[
                        "semantic_input_sha256"
                    ],
                )
                child = next(
                    (
                        item
                        for item in expansion["children"]
                        if item["node_instance_id"]
                        == node_instance_id
                    ),
                    None,
                )
                if not isinstance(child, _OscMapping):
                    raise _osc_error(
                        "NODE_INSTANCE_UNKNOWN",
                        "assignment node is outside the current map expansion",
                    )
                node = _osc_find_node(new_state, node_instance_id)
                if node.get("state") != "READY":
                    raise _osc_error(
                        "REPOSITORY_NODE_NOT_READY",
                        "assignment is legal only for a formally READY node",
                        details={
                            "node_instance_id": node_instance_id,
                            "state": node.get("state"),
                        },
                    )
                frontier = _osc_repository_frontier(
                    plan, approval, state, orchestration
                )
                dispatchable = {
                    item.node_instance_id
                    for item in frontier.dispatchable
                }
                if node_instance_id not in dispatchable:
                    blockers = next(
                        (
                            list(item.codes)
                            for item in frontier.blocked
                            if item.repository_id
                            == child["repository_id"]
                        ),
                        ["REPOSITORY_NOT_DISPATCHABLE"],
                    )
                    raise _osc_error(
                        "REPOSITORY_NODE_NOT_DISPATCHABLE",
                        "repository is outside the current dependency-ready frontier",
                        details={
                            "node_instance_id": node_instance_id,
                            "blockers": blockers,
                        },
                    )
                repository = next(
                    item
                    for item in plan["repositories"]
                    if item["repository_id"]
                    == child["repository_id"]
                )
                (
                    worktree_binding,
                    worktree_branch_ref,
                    worktree_baseline_head,
                    initial_worktree_sha256,
                    _paths,
                    _paths_sha256,
                ) = _osc_bound_worktree_observation(
                    worktree_path
                )
                worktree_identity_sha256 = worktree_binding[
                    "worktree_identity_sha256"
                ]
                controller_claim_sha256 = _osc_digest(
                    {
                        "schema": (
                            "dev-flow-controller-worktree-claim/v1"
                        ),
                        "task_id": task_id,
                        "workflow_bundle_sha256": plan[
                            "workflow_bundle_sha256"
                        ],
                        "repository_id": repository[
                            "repository_id"
                        ],
                        "repository_identity_sha256": repository[
                            "identity_sha256"
                        ],
                        "node_instance_id": node_instance_id,
                        **worktree_binding,
                    }
                )
                attempts = node.get("attempts")
                if not isinstance(attempts, list):
                    raise _osc_error(
                        "NODE_INSTANCE_INVALID",
                        "node attempt history is invalid",
                    )
                pending = orchestration["pending_retries"]
                assert isinstance(pending, dict)
                retry = pending.get(node_instance_id)
                attempt = (
                    int(retry["next_attempt"])
                    if isinstance(retry, dict)
                    else len(attempts) + 1
                )
                leases = orchestration["leases"]
                assert isinstance(leases, dict)
                lease = issue_worker_lease(
                    {
                        "task_id": task_id,
                        "task_revision": int(state["revision"]),
                        "workflow_bundle_sha256": plan[
                            "workflow_bundle_sha256"
                        ],
                        "map_epoch": plan["map_epoch"],
                        "node_instance_id": node_instance_id,
                        "repository_id": repository["repository_id"],
                        "repository_identity_sha256": repository[
                            "identity_sha256"
                        ],
                        "worktree_identity_sha256": (
                            worktree_identity_sha256
                        ),
                        "attempt": attempt,
                        "input_evidence_sha256": (
                            input_evidence_sha256
                        ),
                        "plan_dag_sha256": approval["dag_sha256"],
                        "semantic_input_sha256": plan[
                            "semantic_input_sha256"
                        ],
                        "interface_contract_sha256s": [
                            item["sha256"]
                            for item in plan["interface_contracts"]
                        ],
                        "approved_paths": list(
                            repository["approved_paths"]
                        ),
                        "allowed_actions": list(allowed_actions),
                        "write_policy": repository["write_policy"],
                    },
                    lease_nonce_bytes=bytes(
                        self._random_bytes(32)
                    ),
                    wall_time_ns=self._wall_time_ns(),
                    monotonic_time_ns=self._monotonic_ns(),
                    ttl_ns=lease_ttl_ns,
                    clock_id=self._clock_id,
                    existing_leases=list(leases.values()),
                    cancellation_requested=cancellation_requested,
                )
                assignment = create_worker_assignment(
                    lease,
                    node_id=str(child["node_id"]),
                    worktree_path=worktree_path,
                    controller_claim_sha256=controller_claim_sha256,
                    plan_id=str(plan["plan_id"]),
                    plan_artifact_sha256=str(
                        approval["plan_artifact_sha256"]
                    ),
                    playbook_locator=playbook_locator,
                    playbook_sha256=playbook_sha256,
                    required_evidence_contract_sha256s=(
                        required_evidence_contract_sha256s
                    ),
                )
                if self._host_capability_observer is None:
                    decision = {
                        "schema": HOST_ISOLATION_DECISION_SCHEMA,
                        "assignment_id": assignment.assignment_id,
                        "parallel_dispatch_allowed": False,
                        "dispatch_mode": "manager-serial",
                        "blocker_codes": [
                            "HOST_CAPABILITY_REPORT_MISSING"
                        ],
                    }
                else:
                    try:
                        host_report = (
                            self._host_capability_observer(
                                assignment.as_dict()
                            )
                        )
                    except Exception as exc:
                        raise _osc_error(
                            "HOST_CAPABILITY_OBSERVATION_FAILED",
                            "trusted host capability observation failed before assignment commit",
                            details={
                                "type": type(exc).__name__
                            },
                        ) from exc
                    decision = evaluate_host_isolation(
                        host_report,
                        assignment,
                        trusted_adapter_ids=(
                            self._trusted_host_adapter_ids
                        ),
                        protected_read_identity_sha256s=(
                            self._protected_read_identity_sha256s
                        ),
                        mutating_tool_ids=self._mutating_tool_ids,
                    ).as_dict()
                durable_claim = _osc_acquire_worktree_claim(
                    task_dir,
                    task_id=task_id,
                    node_instance_id=node_instance_id,
                    lease_id=lease.lease_id,
                    assignment_id=assignment.assignment_id,
                    binding=worktree_binding,
                    branch_ref=worktree_branch_ref,
                    initial_head=worktree_baseline_head,
                )
                leases[lease.lease_id] = lease.as_dict()
                assignments = orchestration["assignments"]
                dispatch = orchestration["dispatch"]
                assert isinstance(assignments, dict)
                assert isinstance(dispatch, dict)
                assignments[assignment.assignment_id] = (
                    assignment.as_dict()
                )
                dispatch[assignment.assignment_id] = {
                    "decision": decision,
                    "runtime_handle_id": runtime_handle_id,
                    "host_assignment_id": host_assignment_id,
                    "runtime_authentication_sha256": (
                        runtime_authentication_sha256
                    ),
                    "actor_id": actor_id,
                    "worktree_baseline_head": (
                        worktree_baseline_head
                    ),
                    "worktree_initial_fingerprint_sha256": (
                        initial_worktree_sha256
                    ),
                    "repository_common_dir_sha256": worktree_binding[
                        "repository_common_dir_sha256"
                    ],
                    "ownership_claim_sha256": worktree_binding[
                        "ownership_claim_sha256"
                    ],
                    "worktree_claim_key_sha256": durable_claim[
                        "claim_key_sha256"
                    ],
                    "worktree_claim_generation": durable_claim[
                        "claim_generation"
                    ],
                    "worktree_branch_ref": worktree_branch_ref,
                    "runtime_live": decision[
                        "parallel_dispatch_allowed"
                    ]
                    is True,
                    "runtime_status": (
                        "ACTIVE"
                        if decision[
                            "parallel_dispatch_allowed"
                        ]
                        is True
                        else "ACTIVE"
                    ),
                }
                attempts.append(
                    {
                        "attempt": attempt,
                        "state": "RUNNING",
                        "input_sha256": input_evidence_sha256,
                        "result_refs": [],
                        **(
                            {"previous_attempt": attempt - 1}
                            if attempt > 1
                            else {}
                        ),
                        "runtime_handle": (
                            None
                            if runtime_handle_id is None
                            else {
                                "schema": (
                                    _workflow_state_runtime_handle_schema
                                ),
                                "handle_id": runtime_handle_id,
                                "kind": "controller-runtime",
                                "task_id": task_id,
                                "node_instance_id": (
                                    node_instance_id
                                ),
                                "attempt": attempt,
                                "repository_id": repository[
                                    "repository_id"
                                ],
                            }
                        ),
                    }
                )
                node["state"] = "RUNNING"
                pending.pop(node_instance_id, None)
                new_state["orchestration"] = orchestration
                payload = {
                    "assignment_id": assignment.assignment_id,
                    "lease_id": lease.lease_id,
                    "node_instance_id": node_instance_id,
                    "attempt": attempt,
                    "dispatch_mode": decision["dispatch_mode"],
                    "parallel_dispatch_allowed": decision[
                        "parallel_dispatch_allowed"
                    ],
                    "blocker_codes": decision["blocker_codes"],
                    "manager_authorization_id": (
                        authorization.authorization_id
                    ),
                }
                event_type = V3_NODE_MUTATION_EVENT_TYPES[
                    V3_NODE_MUTATION_ATTEMPT_START
                ]
                try:
                    event = commit_v3_node_event(
                        old_state,
                        new_state,
                        task_dir,
                        event_type,
                        payload,
                        operation=V3_NODE_MUTATION_ATTEMPT_START,
                        manager_authorization=sealed_authorization,
                    )
                except Exception as commit_exc:
                    try:
                        _osc_release_worktree_claim(
                            task_dir,
                            task_id=task_id,
                            lease_id=lease.lease_id,
                            assignment_id=assignment.assignment_id,
                            claim_key_sha256=str(
                                durable_claim[
                                    "claim_key_sha256"
                                ]
                            ),
                            claim_generation=int(
                                durable_claim["claim_generation"]
                            ),
                            released_at_revision=int(
                                state["revision"]
                            ),
                        )
                    except Exception as rollback_exc:
                        raise _osc_error(
                            "WORKTREE_CLAIM_ROLLBACK_FAILED",
                            "failed formal assignment left a conservative active worktree quarantine",
                            details={
                                "commit_failure_type": type(
                                    commit_exc
                                ).__name__,
                                "rollback_failure_type": type(
                                    rollback_exc
                                ).__name__,
                                "claim_key_sha256": durable_claim[
                                    "claim_key_sha256"
                                ],
                            },
                        ) from rollback_exc
                    raise
                committed_receipt = _osc_receipt(
                    event,
                    authorization_id=authorization.authorization_id,
                    payload=payload,
                )
                committed_assignment = assignment.as_dict()
            assert committed_receipt is not None
            return committed_receipt
        except Exception as exc:
            raise _osc_translate(exc) from exc

    def issue_assignment(
        self,
        task_id: str,
        *,
        node_instance_id: str,
        worktree_path: str,
        input_evidence_sha256: str,
        allowed_actions: _OscSequence[str],
        playbook_locator: str,
        playbook_sha256: str,
        required_evidence_contract_sha256s: _OscSequence[str],
        runtime_handle_id: _OscOptional[str],
        host_assignment_id: str,
        runtime_authentication_sha256: str,
        actor_id: str,
        lease_ttl_ns: int,
        lease_id: _OscOptional[str] = None,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Issue only an assignment from a separately persisted lease."""

        del (
            runtime_handle_id,
            host_assignment_id,
            runtime_authentication_sha256,
            actor_id,
            lease_ttl_ns,
        )

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            plan = _osc_plan_from_state(task_dir, orchestration)
            expansion = _osc_current_expansion(orchestration)
            approval = _osc_approval_from_state(orchestration)
            frontier = orchestration["frontier"]
            assert isinstance(frontier, dict)
            ready = frontier.get(node_instance_id)
            if (
                not isinstance(ready, dict)
                or ready.get("state") != "READY"
            ):
                raise _osc_error(
                    "REPOSITORY_NODE_NOT_READY",
                    "assignment issue requires a separately advanced frontier",
                )
            child = next(
                (
                    item
                    for item in expansion["children"]
                    if item["node_instance_id"]
                    == node_instance_id
                ),
                None,
            )
            if not isinstance(child, _OscMapping):
                raise _osc_error(
                    "NODE_INSTANCE_UNKNOWN",
                    "assignment node is outside the current map",
                )
            leases = orchestration["leases"]
            assert isinstance(leases, dict)
            matches = [
                validate_worker_lease(value)
                for identifier, value in leases.items()
                if (
                    lease_id is None
                    or identifier == lease_id
                )
                and isinstance(value, _OscMapping)
                and value.get("node_instance_id")
                == node_instance_id
                and value.get("state") == "ACTIVE"
            ]
            if len(matches) != 1:
                raise _osc_error(
                    "WORKER_LEASE_SELECTION_INVALID",
                    "assignment issue requires one exact active lease",
                    details={
                        "node_instance_id": node_instance_id,
                        "lease_id": lease_id,
                        "match_count": len(matches),
                    },
                )
            lease = matches[0]
            (
                worktree_binding,
                _branch,
                _head,
                _fingerprint,
                _paths,
                _paths_sha256,
            ) = _osc_bound_worktree_observation(worktree_path)
            if (
                lease.worktree_identity_sha256
                != worktree_binding[
                    "worktree_identity_sha256"
                ]
                or lease.input_evidence_sha256
                != input_evidence_sha256
                or tuple(lease.allowed_actions)
                != tuple(allowed_actions)
            ):
                raise _osc_error(
                    "WORKER_LEASE_BINDING_MISMATCH",
                    "assignment inputs differ from the separately issued lease",
                )
            controller_claim_sha256 = _osc_digest(
                {
                    "schema": (
                        "dev-flow-controller-worktree-claim/v1"
                    ),
                    "task_id": task_id,
                    "workflow_bundle_sha256": (
                        lease.workflow_bundle_sha256
                    ),
                    "repository_id": lease.repository_id,
                    "repository_identity_sha256": (
                        lease.repository_identity_sha256
                    ),
                    "node_instance_id": node_instance_id,
                    **worktree_binding,
                }
            )
            assignment = create_worker_assignment(
                lease,
                node_id=str(child["node_id"]),
                worktree_path=worktree_path,
                controller_claim_sha256=controller_claim_sha256,
                plan_id=str(plan["plan_id"]),
                plan_artifact_sha256=str(
                    approval["plan_artifact_sha256"]
                ),
                playbook_locator=playbook_locator,
                playbook_sha256=playbook_sha256,
                required_evidence_contract_sha256s=(
                    required_evidence_contract_sha256s
                ),
            )
            assignments = orchestration["assignments"]
            assert isinstance(assignments, dict)
            if assignment.assignment_id in assignments:
                raise _osc_error(
                    "WORKER_ASSIGNMENT_EXISTS",
                    "assignment identity has already been issued",
                    details={
                        "assignment_id": assignment.assignment_id
                    },
                )
            assignments[assignment.assignment_id] = (
                assignment.as_dict()
            )
            return {
                "assignment_id": assignment.assignment_id,
                "lease_id": lease.lease_id,
                "node_instance_id": node_instance_id,
                "repository_id": lease.repository_id,
                "attempt": lease.attempt,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_ASSIGNMENT_ISSUE,
            event_type="orchestration_assignment_issued",
            operation_facts={
                "node_instance_id": node_instance_id,
                "lease_id": lease_id,
                "worktree_path_sha256": _osc_hashlib.sha256(
                    worktree_path.encode("utf-8")
                ).hexdigest(),
                "input_evidence_sha256": input_evidence_sha256,
                "playbook_sha256": playbook_sha256,
            },
            mutate=mutate,
        )

    def handoff_dispatch(
        self,
        task_id: str,
        *,
        assignment_id: str,
        runtime_handle_id: str,
        host_assignment_id: str,
        runtime_authentication_sha256: str,
        actor_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Claim and hand off one separately issued assignment."""

        prepared_dispatch: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            assignments = orchestration["assignments"]
            leases = orchestration["leases"]
            dispatch = orchestration["dispatch"]
            assert isinstance(assignments, dict)
            assert isinstance(leases, dict)
            assert isinstance(dispatch, dict)
            assignment = assignments.get(assignment_id)
            if not isinstance(assignment, dict):
                raise _osc_error(
                    "WORKER_ASSIGNMENT_UNKNOWN",
                    "dispatch handoff requires a persisted assignment",
                )
            credential = assignment.get("lease_credential")
            lease_id = (
                credential.get("lease_id")
                if isinstance(credential, dict)
                else None
            )
            if not isinstance(lease_id, str):
                raise _osc_error(
                    "WORKER_LEASE_UNKNOWN",
                    "assignment has no persisted lease binding",
                )
            lease = validate_worker_lease(leases[lease_id])
            (
                worktree_binding,
                branch_ref,
                baseline_head,
                initial_fingerprint,
                _paths,
                _paths_sha256,
            ) = _osc_bound_worktree_observation(
                str(assignment["worktree_path"])
            )
            if (
                worktree_binding["worktree_identity_sha256"]
                != lease.worktree_identity_sha256
            ):
                raise _osc_error(
                    "WORKER_LEASE_BINDING_MISMATCH",
                    "dispatch worktree differs from its lease",
                )
            if self._host_capability_observer is None:
                raise _osc_error(
                    "HOST_CAPABILITY_REPORT_MISSING",
                    "dispatch handoff requires a trusted host isolation observer",
                )
            try:
                host_report = self._host_capability_observer(
                    _osc_copy.deepcopy(assignment)
                )
            except Exception as exc:
                raise _osc_error(
                    "HOST_CAPABILITY_OBSERVATION_FAILED",
                    "trusted host capability observation failed",
                ) from exc
            decision = evaluate_host_isolation(
                host_report,
                assignment,
                trusted_adapter_ids=self._trusted_host_adapter_ids,
                protected_read_identity_sha256s=(
                    self._protected_read_identity_sha256s
                ),
                mutating_tool_ids=self._mutating_tool_ids,
            ).as_dict()
            if decision["parallel_dispatch_allowed"] is not True:
                raise _osc_error(
                    "WORKER_PARALLEL_DISPATCH_DENIED",
                    "host isolation does not authorize worker handoff",
                    details={
                        "blocker_codes": decision["blocker_codes"]
                    },
                )
            claim = _osc_prepare_worktree_claim(
                task_dir,
                task_id=task_id,
                node_instance_id=str(
                    assignment["node_instance_id"]
                ),
                lease_id=lease_id,
                assignment_id=assignment_id,
                binding=worktree_binding,
                branch_ref=branch_ref,
                initial_head=baseline_head,
            )
            claim_slot_sha256 = _osc_worktree_claim_slot_sha256(
                _osc_read_worktree_claim_registry(task_dir),
                str(claim["claim_key_sha256"]),
            )
            record = {
                "assignment_id": assignment_id,
                "decision": decision,
                "runtime_handle_id": runtime_handle_id,
                "host_assignment_id": host_assignment_id,
                "runtime_authentication_sha256": (
                    runtime_authentication_sha256
                ),
                "actor_id": actor_id,
                "worktree_baseline_head": baseline_head,
                "worktree_initial_fingerprint_sha256": (
                    initial_fingerprint
                ),
                "repository_common_dir_sha256": (
                    worktree_binding[
                        "repository_common_dir_sha256"
                    ]
                ),
                "ownership_claim_sha256": (
                    worktree_binding[
                        "ownership_claim_sha256"
                    ]
                ),
                "worktree_claim_key_sha256": claim[
                    "claim_key_sha256"
                ],
                "worktree_claim_generation": claim[
                    "claim_generation"
                ],
                "worktree_branch_ref": branch_ref,
                "runtime_live": True,
                "runtime_status": "ACTIVE",
            }
            if assignment_id in dispatch:
                raise _osc_error(
                    "WORKER_DISPATCH_EXISTS",
                    "assignment already has a dispatch record",
                )
            dispatch[assignment_id] = record
            node = _osc_find_node(
                _state, str(assignment["node_instance_id"])
            )
            node_attempts = node.get("attempts")
            attempt = assignment.get("attempt")
            if (
                not isinstance(node_attempts, list)
                or isinstance(attempt, bool)
                or not isinstance(attempt, int)
                or attempt != len(node_attempts) + 1
                or node.get("state") != "READY"
            ):
                raise _osc_error(
                    "WORKER_DISPATCH_ATTEMPT_INVALID",
                    "dispatch handoff does not bind the next ready attempt",
                    details={
                        "assignment_id": assignment_id,
                        "attempt": attempt,
                        "prior_attempt_count": (
                            len(node_attempts)
                            if isinstance(node_attempts, list)
                            else None
                        ),
                        "node_state": node.get("state"),
                    },
                )
            node_attempts.append(
                {
                    "attempt": attempt,
                    "state": "RUNNING",
                    "input_sha256": assignment[
                        "input_evidence_sha256"
                    ],
                    "result_refs": [],
                    **(
                        {"previous_attempt": attempt - 1}
                        if attempt > 1
                        else {}
                    ),
                    "runtime_handle": {
                        "schema": _workflow_state_runtime_handle_schema,
                        "handle_id": runtime_handle_id,
                        "kind": "controller-runtime",
                        "task_id": task_id,
                        "node_instance_id": assignment[
                            "node_instance_id"
                        ],
                        "attempt": attempt,
                        "repository_id": assignment[
                            "repository_id"
                        ],
                    },
                }
            )
            node["state"] = "RUNNING"
            prepared_dispatch.clear()
            prepared_dispatch.update(
                {
                    "assignment": _osc_copy.deepcopy(
                        assignment
                    ),
                    "binding": worktree_binding,
                    "branch_ref": branch_ref,
                    "baseline_head": baseline_head,
                    "claim": claim,
                    "claim_slot_sha256": (
                        claim_slot_sha256
                    ),
                    "lease_id": lease_id,
                    "record": record,
                }
            )
            return {
                "assignment_id": assignment_id,
                "lease_id": lease_id,
                "node_instance_id": assignment[
                    "node_instance_id"
                ],
                "repository_id": assignment["repository_id"],
                "runtime_handle_id": runtime_handle_id,
                "host_assignment_id": host_assignment_id,
                "dispatch_mode": decision["dispatch_mode"],
            }

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            _candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> _OscSequence[object]:
            assignment = prepared_dispatch.get("assignment")
            binding_value = prepared_dispatch.get("binding")
            claim = prepared_dispatch.get("claim")
            lease_id = prepared_dispatch.get("lease_id")
            if (
                not isinstance(assignment, _OscMapping)
                or not isinstance(binding_value, _OscMapping)
                or not isinstance(claim, _OscMapping)
                or not isinstance(lease_id, str)
            ):
                raise _osc_error(
                    "WORKER_DISPATCH_PREPARATION_INVALID",
                    "dispatch handoff has no exact prepared claim",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-dispatch-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "assignment_id": assignment_id,
                        "lease_id": lease_id,
                        "runtime_handle_id": runtime_handle_id,
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="runtime-dispatch",
                scopes=_osc_effect_scopes(
                    repository_ids=(
                        str(assignment["repository_id"]),
                    ),
                    node_ids=(
                        str(assignment["node_instance_id"]),
                    ),
                    worktree_ids=(
                        str(
                            assignment[
                                "worktree_identity_sha256"
                            ]
                        ),
                    ),
                    lease_ids=(lease_id,),
                    paths=(
                        str(assignment["worktree_path"]),
                    ),
                ),
                safe_inputs={
                    "assignment_id": assignment_id,
                    "lease_id": lease_id,
                    "worktree_claim_id": claim[
                        "claim_key_sha256"
                    ],
                    "worktree_claim_generation": claim[
                        "claim_generation"
                    ],
                    "claim_slot_sha256": prepared_dispatch[
                        "claim_slot_sha256"
                    ],
                    "runtime_handle_sha256": _osc_hashlib.sha256(
                        runtime_handle_id.encode("utf-8")
                    ).hexdigest(),
                },
                attempt_id=(
                    "dispatch-"
                    + _osc_digest(
                        {
                            "assignment_id": assignment_id,
                            "lease_id": lease_id,
                        }
                    )[:32]
                ),
            )
            runtime_handle_sha256 = _osc_hashlib.sha256(
                runtime_handle_id.encode("utf-8")
            ).hexdigest()
            launched: dict[str, object] = {}

            def dispatch(context: object) -> object:
                if type(context) is not WorkflowActionDispatchContext:
                    raise _osc_error(
                        "ORCHESTRATION_ACTION_DISPATCH_CONTEXT_INVALID",
                        "runtime handoff requires a claimed context",
                    )
                with _workspace_registry_lock(
                    resolve_data_dir(data_dir)
                ):
                    current_registry = (
                        _osc_read_worktree_claim_registry(
                            task_dir
                        )
                    )
                    if _osc_worktree_claim_slot_sha256(
                        current_registry,
                        str(claim["claim_key_sha256"]),
                    ) != str(
                        prepared_dispatch[
                            "claim_slot_sha256"
                        ]
                    ):
                        raise _osc_error(
                            "WORKTREE_WRITER_CLAIM_STALE",
                            "worktree claim slot changed after dispatch was claimed",
                        )
                    actual = _osc_acquire_worktree_claim(
                        task_dir,
                        task_id=task_id,
                        node_instance_id=str(
                            assignment["node_instance_id"]
                        ),
                        lease_id=lease_id,
                        assignment_id=assignment_id,
                        binding=binding_value,
                        branch_ref=str(
                            prepared_dispatch["branch_ref"]
                        ),
                        initial_head=str(
                            prepared_dispatch["baseline_head"]
                        ),
                    )
                if actual != claim:
                    raise _osc_error(
                        "WORKTREE_WRITER_CLAIM_STALE",
                        "claimed worktree facts differ from the candidate",
                    )
                plan = context.plan
                runtime_binding = WorkflowActionRuntimeBinding(
                    task_id=plan.task_id,
                    execution_id=plan.execution_id,
                    effect_id=plan.effect_id,
                    claim_id=plan.claim_id,
                    attempt_id=plan.attempt_id,
                    lease_id=lease_id,
                    runtime_handle_sha256=(
                        runtime_handle_sha256
                    ),
                    stop_action_id=(
                        ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD
                    ),
                    reconcile_action_id=(
                        ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE
                    ),
                )
                launched["binding"] = runtime_binding
                return WorkflowActionRuntimeLaunch(
                    binding=runtime_binding,
                    protocol="suspended-handshake/v1",
                    suspended=True,
                    business_effect_count=0,
                )

            def release(context: object) -> object:
                if type(context) is not WorkflowActionRuntimeReleaseContext:
                    raise _osc_error(
                        "ORCHESTRATION_ACTION_RUNTIME_RELEASE_INVALID",
                        "dispatch release requires the exact permit",
                    )
                runtime_binding = context.binding
                return WorkflowActionRuntimeReleaseAck(
                    task_id=runtime_binding.task_id,
                    execution_id=runtime_binding.execution_id,
                    effect_id=runtime_binding.effect_id,
                    claim_id=runtime_binding.claim_id,
                    attempt_id=runtime_binding.attempt_id,
                    lease_id=runtime_binding.lease_id,
                    runtime_handle_sha256=(
                        runtime_binding.runtime_handle_sha256
                    ),
                    runtime_binding_sha256=(
                        runtime_binding.binding_sha256
                    ),
                    release_context_sha256=(
                        context.release_context_sha256
                    ),
                    protocol=context.protocol,
                    released=True,
                )

            def observe(context: object) -> object:
                if type(context) is not WorkflowActionObserveContext:
                    raise _osc_error(
                        "ORCHESTRATION_ACTION_OBSERVATION_INVALID",
                        "dispatch observation requires exact durable context",
                    )
                active_facts = (
                    verify_active_v3_workflow_action_observe_context(
                        context
                    )
                )
                safe_inputs = active_facts.get("safe_inputs")
                if (
                    not isinstance(safe_inputs, _OscMapping)
                    or safe_inputs.get("assignment_id")
                    != assignment_id
                    or safe_inputs.get("lease_id") != lease_id
                    or safe_inputs.get("worktree_claim_id")
                    != claim.get("claim_key_sha256")
                    or safe_inputs.get(
                        "worktree_claim_generation"
                    )
                    != claim.get("claim_generation")
                ):
                    raise _osc_error(
                        "ORCHESTRATION_ACTION_OBSERVATION_INVALID",
                        "dispatch observation differs from its active durable binding",
                    )
                return WorkflowActionEffectObservation(
                    task_id=context.task_id,
                    execution_id=context.execution_id,
                    effect_id=context.effect_id,
                    claim_id=context.claim_id,
                    attempt_id=context.attempt_id,
                    settlement="HANDOFF_VERIFIED",
                    receipt_sha256=semantic_sha256(
                        b"dev-flow-orchestration-dispatch-handoff-v1\0",
                        {
                            "assignment_id": assignment_id,
                            "lease_id": lease_id,
                            "claim": _osc_thaw(claim),
                        },
                    ),
                    runtime_handle_sha256=(
                        runtime_handle_sha256
                    ),
                )

            return (
                effect_inputs,
                execution_id,
                dispatch,
                release,
                observe,
            )

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_DISPATCH_HANDOFF,
            event_type="orchestration_dispatch_handed_off",
            operation_facts={
                "assignment_id": assignment_id,
                "runtime_handle_sha256": _osc_hashlib.sha256(
                    runtime_handle_id.encode("utf-8")
                ).hexdigest(),
                "host_assignment_id": host_assignment_id,
                "runtime_authentication_sha256": (
                    runtime_authentication_sha256
                ),
                "actor_id": actor_id,
            },
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def worker_assignment_view(
        self,
        task_id: str,
        assignment_id: str,
        *,
        data_dir: object = None,
    ) -> WorkerAssignmentView:
        state = load_state(task_id, data_dir)
        orchestration = _osc_state_copy(state)
        assignments = orchestration["assignments"]
        dispatch = orchestration["dispatch"]
        assert isinstance(assignments, dict)
        assert isinstance(dispatch, dict)
        assignment = assignments.get(assignment_id)
        record = dispatch.get(assignment_id)
        if not isinstance(assignment, dict) or not isinstance(record, dict):
            raise _osc_error(
                "WORKER_ASSIGNMENT_UNKNOWN",
                "worker assignment is absent",
            )
        decision = record["decision"]
        if not isinstance(decision, dict):
            raise _osc_error(
                "HOST_ISOLATION_DECISION_INVALID",
                "assignment dispatch decision is invalid",
            )
        if decision.get("parallel_dispatch_allowed") is not True:
            raise _osc_error(
                "WORKER_PARALLEL_DISPATCH_DENIED",
                "manager-serial fallback assignments are not exposed to workers",
                details={
                    "dispatch_mode": decision.get("dispatch_mode"),
                    "blocker_codes": decision.get("blocker_codes", []),
                },
            )
        return WorkerAssignmentView(
            assignment=_osc_copy.deepcopy(assignment),
            dispatch_mode=str(decision["dispatch_mode"]),
            blocker_codes=tuple(decision["blocker_codes"]),
        )

    def _runtime_lease_projection(
        self,
        orchestration: _OscMapping[str, object],
        lease_id: str,
    ) -> dict[str, object]:
        leases = orchestration["leases"]
        assignments = orchestration["assignments"]
        dispatch = orchestration["dispatch"]
        assert isinstance(leases, _OscMapping)
        assert isinstance(assignments, _OscMapping)
        assert isinstance(dispatch, _OscMapping)
        lease = validate_worker_lease(leases[lease_id])
        assignment = next(
            (
                value
                for value in assignments.values()
                if isinstance(value, _OscMapping)
                and value.get("lease_credential", {}).get("lease_id")
                == lease_id
            ),
            None,
        )
        if not isinstance(assignment, _OscMapping):
            raise _osc_error(
                "WORKER_ASSIGNMENT_UNKNOWN",
                "lease has no persisted assignment",
            )
        dispatch_record = dispatch.get(assignment["assignment_id"])
        if dispatch_record is None:
            (
                worktree_binding,
                _branch,
                _head,
                initial_fingerprint,
                _paths,
                _paths_sha256,
            ) = _osc_bound_worktree_observation(
                str(assignment["worktree_path"])
            )
            if (
                worktree_binding["worktree_identity_sha256"]
                != lease.worktree_identity_sha256
            ):
                raise _osc_error(
                    "WORKER_LEASE_BINDING_MISMATCH",
                    "pre-dispatch recovery worktree differs from its lease",
                )
            dispatch_record = {
                "runtime_status": lease.state,
                "worktree_initial_fingerprint_sha256": (
                    initial_fingerprint
                ),
                "repository_common_dir_sha256": (
                    worktree_binding[
                        "repository_common_dir_sha256"
                    ]
                ),
                "ownership_claim_sha256": (
                    worktree_binding["ownership_claim_sha256"]
                ),
                "runtime_handle_id": None,
                "host_assignment_id": (
                    "unassigned:"
                    + _osc_assignment_sha256(
                        str(assignment["assignment_id"])
                    )
                ),
                "runtime_authentication_sha256": _osc_digest(
                    {
                        "schema": (
                            "dev-flow-undispatched-runtime/v1"
                        ),
                        "assignment_id": assignment[
                            "assignment_id"
                        ],
                        "lease_id": lease_id,
                    }
                ),
            }
        elif not isinstance(dispatch_record, _OscMapping):
            raise _osc_error(
                "RUNTIME_HANDLE_UNAVAILABLE",
                "assignment runtime binding is malformed",
            )
        runtime_status = str(
            dispatch_record.get("runtime_status", lease.state)
        )
        status = (
            "QUIESCED"
            if lease.quiesced_at_wall_ns is not None
            else runtime_status
        )
        return {
            "schema": RUNTIME_LEASE_STATE_SCHEMA,
            "lease_id": lease.lease_id,
            "task_id": lease.task_id,
            "workflow_bundle_sha256": lease.workflow_bundle_sha256,
            "plan_id": assignment["plan_id"],
            "dag_sha256": lease.plan_dag_sha256,
            "map_epoch": lease.map_epoch,
            "repository_id": lease.repository_id,
            "repository_identity_sha256": (
                lease.repository_identity_sha256
            ),
            "node_instance_id": lease.node_instance_id,
            "attempt": lease.attempt,
            "assignment_id": assignment["assignment_id"],
            "assignment_sha256": _osc_assignment_sha256(
                str(assignment["assignment_id"])
            ),
            "input_sha256": lease.input_evidence_sha256,
            "worktree_identity_sha256": (
                lease.worktree_identity_sha256
            ),
            "worktree_fingerprint_sha256": (
                dispatch_record[
                    "worktree_initial_fingerprint_sha256"
                ]
            ),
            "repository_common_dir_sha256": (
                dispatch_record["repository_common_dir_sha256"]
            ),
            "ownership_claim_sha256": (
                dispatch_record["ownership_claim_sha256"]
            ),
            "runtime_handle_id": dispatch_record[
                "runtime_handle_id"
            ],
            "host_assignment_id": dispatch_record[
                "host_assignment_id"
            ],
            "runtime_authentication_sha256": dispatch_record[
                "runtime_authentication_sha256"
            ],
            "status": status,
            "writable": lease.write_policy == "scoped-write",
            "issued_monotonic_ns": lease.issued_at_monotonic_ns,
            "expires_monotonic_ns": (
                lease.issued_at_monotonic_ns + lease.ttl_ns
            ),
            "clock_id": lease.clock_id,
        }

    def _result_expectation(
        self,
        task_dir: _OscPath,
        orchestration: _OscMapping[str, object],
        assignment: _OscMapping[str, object],
        lease: object,
    ) -> dict[str, object]:
        plan = _osc_plan_from_state(task_dir, orchestration)
        approval = _osc_approval_from_state(orchestration)
        dispatch = orchestration["dispatch"]
        assert isinstance(dispatch, _OscMapping)
        runtime = dispatch[assignment["assignment_id"]]
        status = worker_lease_status(
            lease,
            wall_time_ns=self._wall_time_ns(),
            monotonic_time_ns=self._monotonic_ns(),
            clock_id=self._clock_id,
        )
        return {
            "schema": NODE_RESULT_EXPECTATION_SCHEMA,
            "task_id": assignment["task_id"],
            "workflow_bundle_sha256": assignment[
                "workflow_bundle_sha256"
            ],
            "plan_id": assignment["plan_id"],
            "plan_artifact_sha256": assignment[
                "plan_artifact_sha256"
            ],
            "dag_sha256": assignment["plan_dag_sha256"],
            "semantic_input_sha256": assignment[
                "semantic_input_sha256"
            ],
            "map_epoch": assignment["map_epoch"],
            "repository_id": assignment["repository_id"],
            "repository_identity_sha256": assignment[
                "repository_identity_sha256"
            ],
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "assignment_revision": assignment["expected_revision"],
            "assignment_id": assignment["assignment_id"],
            "assignment_sha256": _osc_assignment_sha256(
                str(assignment["assignment_id"])
            ),
            "lease_id": lease.lease_id,
            "lease_nonce": lease.lease_nonce,
            "input_sha256": assignment["input_evidence_sha256"],
            "interface_contract_sha256": list(
                assignment["interface_contract_sha256s"]
            ),
            "input_worktree_fingerprint_sha256": runtime[
                "worktree_initial_fingerprint_sha256"
            ],
            "actor_id": runtime["actor_id"],
            "host_assignment_id": runtime["host_assignment_id"],
            "runtime_handle_id": runtime["runtime_handle_id"],
            "lease_active": status.authorized,
        }

    def _frozen_legacy_accept_result_alias(
        self,
        task_id: str,
        result_value: object,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        inspected = load_state(task_id, data_dir)
        if inspected.get("schema_version") == 3:
            raise _osc_error(
                "ORCHESTRATION_LEGACY_ALIAS_FORBIDDEN",
                "schema-v3 result acceptance requires orchestration.result.accept/v1",
                details={
                    "alias_id": ORCHESTRATION_ACTION_RESULT_ACCEPT
                },
            )
        try:
            parsed_request = validate_manager_capability_request(request)
            raw = dict(result_value) if isinstance(
                result_value, _OscMapping
            ) else {}
            result_id = raw.get("result_id")
            with _osc_locked_current_state(
                task_id, data_dir
            ) as (task_dir, state):
                old_state = _osc_copy.deepcopy(state)
                new_state = _osc_copy.deepcopy(state)
                orchestration = _osc_state_copy(new_state)
                observed = orchestration["accepted_results"]
                assert isinstance(observed, dict)
                existing = (
                    observed.get(result_id)
                    if isinstance(result_id, str)
                    else None
                )
                if existing is not None:
                    candidate = evaluate_node_result_acceptance(
                        result_value,
                        expected_revision=parsed_request.expected_revision,
                        current_revision=int(state["revision"]),
                        expected_bindings={},
                        verified_output={},
                        observed_results={
                            key: {
                                "result": value["result"],
                                "receipt": value["receipt"],
                            }
                            for key, value in observed.items()
                            if isinstance(value, dict)
                        },
                    )
                    receipt = candidate.prior_receipt
                    if not isinstance(receipt, _OscMapping):
                        raise _osc_error(
                            "NODE_RESULT_RECEIPT_INVALID",
                            "persisted result receipt is invalid",
                        )
                    _osc_validate_replay_caller(
                        task_id=task_id,
                        request=parsed_request,
                        principal=principal,
                        action_id=ORCHESTRATION_ACTION_RESULT_ACCEPT,
                        orchestration=orchestration,
                        authorization_id=receipt.get(
                            "authorization_id"
                        ),
                    )
                    event = _osc_committed_event(
                        task_dir,
                        task_id=task_id,
                        event_type=V3_NODE_MUTATION_EVENT_TYPES[
                            V3_NODE_MUTATION_RESULT_ACCEPT
                        ],
                        payload_key="result_id",
                        payload_value=result_id,
                        expected_event_id=receipt.get("event_id"),
                        expected_revision=receipt.get(
                            "accepted_revision"
                        ),
                        expected_authorization_id=receipt.get(
                            "authorization_id"
                        ),
                    )
                    if (
                        event.get("event_id") != receipt.get("event_id")
                        or event.get("revision")
                        != receipt.get("accepted_revision")
                    ):
                        raise _osc_error(
                            "NODE_RESULT_RECEIPT_INVALID",
                            "persisted result receipt does not bind its committed event",
                        )
                    return _osc_receipt(
                        event,
                        authorization_id=receipt.get(
                            "authorization_id"
                        ),
                        payload=receipt["payload"],
                    )
                result = validate_orchestration_node_result(
                    result_value
                )
                expansion = _osc_current_expansion(orchestration)
                child_ids = tuple(
                    sorted(
                        (
                            str(child["node_instance_id"])
                            for child in expansion.get(
                                "children", ()
                            )
                            if isinstance(child, _OscMapping)
                            and isinstance(
                                child.get("node_instance_id"),
                                str,
                            )
                        ),
                        key=_osc_utf8_sort_key,
                    )
                )
                current_index = orchestration["current_results"]
                assert isinstance(current_index, dict)
                pending_first_results = tuple(
                    identifier
                    for identifier in child_ids
                    if identifier not in current_index
                )
                if (
                    result["node_instance_id"] in child_ids
                    and pending_first_results
                    and result["node_instance_id"]
                    != pending_first_results[0]
                ):
                    raise _osc_error(
                        "NODE_RESULT_ACCEPTANCE_ORDER_BLOCKED",
                        "fan-out results are accepted only in canonical node-instance order",
                        details={
                            "expected_node_instance_id": (
                                pending_first_results[0]
                            ),
                            "actual_node_instance_id": result[
                                "node_instance_id"
                            ],
                            "map_epoch": expansion.get(
                                "map_epoch"
                            ),
                        },
                    )
                _check_revision(state, parsed_request.expected_revision)
                authorization = self._authorize(
                    orchestration,
                    parsed_request,
                    principal,
                    action_id=ORCHESTRATION_ACTION_RESULT_ACCEPT,
                )
                sealed_authorization = (
                    _osc_preauthorize_manager_effect(
                        old_state,
                        orchestration,
                        authorization,
                        action_id=(
                            ORCHESTRATION_ACTION_RESULT_ACCEPT
                        ),
                    )
                )
                trusted_verified_output = _osc_verify_worker_result(
                    task_id,
                    result,
                    data_dir=data_dir,
                    locked_context=(task_dir, state),
                    wall_time_ns=self._wall_time_ns,
                    monotonic_time_ns=self._monotonic_ns,
                    clock_id=self._clock_id,
                )
                assignments = orchestration["assignments"]
                leases = orchestration["leases"]
                assert isinstance(assignments, dict)
                assert isinstance(leases, dict)
                assignment = assignments.get(result["assignment_id"])
                if not isinstance(assignment, dict):
                    raise _osc_error(
                        "WORKER_ASSIGNMENT_UNKNOWN",
                        "result assignment is not persisted",
                    )
                lease = validate_worker_lease(
                    leases[result["lease_id"]]
                )
                expectation = self._result_expectation(
                    task_dir, orchestration, assignment, lease
                )
                candidate = evaluate_node_result_acceptance(
                    result,
                    expected_revision=parsed_request.expected_revision,
                    current_revision=int(state["revision"]),
                    expected_bindings=expectation,
                    verified_output=trusted_verified_output,
                    observed_results={
                        key: {
                            "result": value["result"],
                            "receipt": value["receipt"],
                        }
                        for key, value in observed.items()
                        if isinstance(value, dict)
                    },
                )
                artifacts = orchestration["artifacts"]
                assert isinstance(artifacts, dict)
                if candidate.result_id in artifacts:
                    raise _osc_error(
                        "NODE_RESULT_ARTIFACT_IDENTITY_CONFLICT",
                        "result identity is already occupied by another artifact",
                        details={"result_id": candidate.result_id},
                    )
                content = canonical_node_result_bytes(candidate.result)
                reference = _osc_store_artifact(
                    task_dir,
                    orchestration,
                    artifact_id=candidate.result_id,
                    content=content,
                    kind=ORCHESTRATION_NODE_RESULT_SCHEMA,
                    semantic_sha256=candidate.content_sha256,
                )
                payload = {
                    "result_id": candidate.result_id,
                    "node_instance_id": result["node_instance_id"],
                    "repository_id": result["repository_id"],
                    "attempt": result["attempt"],
                    "outcome": result["outcome"],
                    "disposition": candidate.disposition,
                    "locator": reference["locator"],
                    "manager_authorization_id": (
                        authorization.authorization_id
                    ),
                }
                receipt_record = {
                    "accepted_revision": int(state["revision"]) + 1,
                    "event_id": "",
                    "authorization_id": authorization.authorization_id,
                    "payload": _osc_copy.deepcopy(payload),
                }
                observed[candidate.result_id] = {
                    "result": _osc_thaw(candidate.result),
                    "receipt": receipt_record,
                    "controller_observation": (
                        seal_v3_controller_result_observation(
                            result=candidate.result,
                            verified_output=trusted_verified_output,
                            observed_at_revision=int(
                                state["revision"]
                            ),
                        )
                    ),
                }
                current_results = orchestration["current_results"]
                assert isinstance(current_results, dict)
                current_results[result["node_instance_id"]] = (
                    candidate.result_id
                )
                observed[candidate.result_id]["accepted"] = True
                observed[candidate.result_id]["current"] = True
                observed[candidate.result_id][
                    "repository_evidence_sha256"
                ] = result["verification_sha256"]
                observed[candidate.result_id]["lease_quiesced"] = (
                    lease.quiesced_at_wall_ns is not None
                )
                dispatch = orchestration["dispatch"][
                    assignment["assignment_id"]
                ]
                observed[candidate.result_id]["runtime_live"] = bool(
                    dispatch.get("runtime_live", True)
                )
                node = _osc_find_node(
                    new_state, str(result["node_instance_id"])
                )
                node["state"] = str(result["outcome"])
                attempt = node["attempts"][int(result["attempt"]) - 1]
                attempt["state"] = str(result["outcome"])
                attempt["result_refs"].append(
                    {
                        "schema": (
                            _workflow_state_result_reference_schema
                        ),
                        "result_id": candidate.result_id,
                        "task_id": task_id,
                        "bundle_sha256": result[
                            "workflow_bundle_sha256"
                        ],
                        "node_instance_id": result[
                            "node_instance_id"
                        ],
                        "attempt": result["attempt"],
                        "input_sha256": result["input_sha256"],
                        "output_sha256": result["output_sha256"],
                        "locator": reference["locator"],
                    }
                )
                if orchestration.get("integration") is not None:
                    orchestration["integration"]["current"] = False
                    orchestration["integration_verification"] = None
                    orchestration["review"] = None
                new_state["orchestration"] = orchestration
                event_type = V3_NODE_MUTATION_EVENT_TYPES[
                    V3_NODE_MUTATION_RESULT_ACCEPT
                ]

                def finalize_event_binding(
                    candidate_state: dict[str, object],
                    event_id: str,
                ) -> None:
                    candidate_orchestration = candidate_state.get(
                        "orchestration"
                    )
                    if not isinstance(candidate_orchestration, dict):
                        raise _osc_error(
                            "NODE_RESULT_RECEIPT_INVALID",
                            "candidate orchestration ledger is absent",
                        )
                    candidate_results = candidate_orchestration.get(
                        "accepted_results"
                    )
                    if not isinstance(candidate_results, dict):
                        raise _osc_error(
                            "NODE_RESULT_RECEIPT_INVALID",
                            "candidate result ledger is absent",
                        )
                    candidate_record = candidate_results.get(
                        candidate.result_id
                    )
                    candidate_receipt = (
                        candidate_record.get("receipt")
                        if isinstance(candidate_record, dict)
                        else None
                    )
                    if not isinstance(candidate_receipt, dict):
                        raise _osc_error(
                            "NODE_RESULT_RECEIPT_INVALID",
                            "candidate result receipt is absent",
                        )
                    candidate_receipt["event_id"] = event_id

                final_verified_output = _osc_verify_worker_result(
                    task_id,
                    result,
                    data_dir=data_dir,
                    locked_context=(task_dir, state),
                    wall_time_ns=self._wall_time_ns,
                    monotonic_time_ns=self._monotonic_ns,
                    clock_id=self._clock_id,
                )
                if final_verified_output != trusted_verified_output:
                    raise _osc_error(
                        "NODE_RESULT_WORKTREE_DRIFT",
                        "controller observation changed before result commit",
                    )
                event = commit_v3_node_event(
                    old_state,
                    new_state,
                    task_dir,
                    event_type,
                    payload,
                    operation=V3_NODE_MUTATION_RESULT_ACCEPT,
                    manager_authorization=sealed_authorization,
                    finalize_event_binding=finalize_event_binding,
                )
                return _osc_receipt(
                    event,
                    authorization_id=authorization.authorization_id,
                    payload=payload,
                )
        except Exception as exc:
            raise _osc_translate(exc) from exc

    def accept_result(
        self,
        task_id: str,
        result_value: object,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Accept one verified result without overloading artifact state."""

        prepared_result: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            result = validate_orchestration_node_result(
                result_value
            )
            observed = orchestration["accepted_results"]
            current_results = orchestration["current_results"]
            assignments = orchestration["assignments"]
            leases = orchestration["leases"]
            dispatch = orchestration["dispatch"]
            assert isinstance(observed, dict)
            assert isinstance(current_results, dict)
            assert isinstance(assignments, dict)
            assert isinstance(leases, dict)
            assert isinstance(dispatch, dict)
            if result["result_id"] in observed:
                raise _osc_error(
                    "NODE_RESULT_REPLAY",
                    "accepted result identities are single-use",
                    details={"result_id": result["result_id"]},
                )
            assignment = assignments.get(
                result["assignment_id"]
            )
            if not isinstance(assignment, dict):
                raise _osc_error(
                    "WORKER_ASSIGNMENT_UNKNOWN",
                    "result assignment is not persisted",
                )
            lease = validate_worker_lease(
                leases[result["lease_id"]]
            )
            trusted_verified_output = _osc_verify_worker_result(
                task_id,
                result,
                data_dir=data_dir,
                locked_context=(task_dir, state),
                wall_time_ns=self._wall_time_ns,
                monotonic_time_ns=self._monotonic_ns,
                clock_id=self._clock_id,
            )
            expectation = self._result_expectation(
                task_dir, orchestration, assignment, lease
            )
            candidate = evaluate_node_result_acceptance(
                result,
                expected_revision=int(state["revision"]),
                current_revision=int(state["revision"]),
                expected_bindings=expectation,
                verified_output=trusted_verified_output,
                observed_results={
                    key: {
                        "result": value["result"],
                        "receipt": value.get("receipt", {}),
                    }
                    for key, value in observed.items()
                    if isinstance(value, dict)
                },
            )
            content = canonical_node_result_bytes(
                candidate.result
            )
            reference = _osc_artifact_reference(
                artifact_id=candidate.result_id,
                content=content,
                kind=ORCHESTRATION_NODE_RESULT_SCHEMA,
                semantic_sha256=candidate.content_sha256,
            )
            dispatch_record = dispatch.get(
                assignment["assignment_id"]
            )
            accepted_record = {
                "result": _osc_thaw(candidate.result),
                "controller_observation": (
                    seal_v3_controller_result_observation(
                        result=candidate.result,
                        verified_output=trusted_verified_output,
                        observed_at_revision=int(
                            state["revision"]
                        ),
                    )
                ),
                "reference": reference,
                "accepted": True,
                "current": True,
                "repository_evidence_sha256": result[
                    "verification_sha256"
                ],
                "lease_quiesced": (
                    lease.quiesced_at_wall_ns is not None
                ),
                "runtime_live": (
                    bool(
                        dispatch_record.get(
                            "runtime_live", True
                        )
                    )
                    if isinstance(dispatch_record, dict)
                    else False
                ),
                "receipt": {
                    "accepted_revision": (
                        int(state["revision"]) + 1
                    ),
                    "result_id": candidate.result_id,
                },
            }
            observed[candidate.result_id] = accepted_record
            current_results[result["node_instance_id"]] = (
                candidate.result_id
            )
            prepared_result.clear()
            prepared_result.update(
                {
                    "content": content,
                    "reference": reference,
                    "result": _osc_thaw(candidate.result),
                    "verified_output": _osc_thaw(
                        trusted_verified_output
                    ),
                }
            )
            return {
                "result_id": candidate.result_id,
                "node_instance_id": result["node_instance_id"],
                "repository_id": result["repository_id"],
                "assignment_id": result["assignment_id"],
                "lease_id": result["lease_id"],
                "attempt": result["attempt"],
                "outcome": result["outcome"],
                "disposition": candidate.disposition,
                "locator": reference["locator"],
            }

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> _OscSequence[object]:
            reference = prepared_result.get("reference")
            content = prepared_result.get("content")
            result = prepared_result.get("result")
            prior_verified = prepared_result.get(
                "verified_output"
            )
            if (
                not isinstance(reference, _OscMapping)
                or not isinstance(content, bytes)
                or not isinstance(result, _OscMapping)
            ):
                raise _osc_error(
                    "NODE_RESULT_ARTIFACT_INVALID",
                    "result action has no prepared controller output",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-result-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "result_id": payload.get("result_id"),
                        "content_sha256": reference["sha256"],
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="filesystem",
                scopes=_osc_effect_scopes(
                    repository_ids=("controller",),
                    node_ids=("controller-result",),
                    worktree_ids=("controller-results",),
                    paths=(
                        str(
                            (
                                task_dir / str(reference["locator"])
                            ).resolve()
                        ),
                    ),
                ),
                safe_inputs={
                    "result_id": payload.get("result_id"),
                    "content_sha256": reference["sha256"],
                    "locator": reference["locator"],
                },
                attempt_id=(
                    "result-" + _osc_digest(reference)[:32]
                ),
            )

            def dispatch(context: object) -> object:
                current_verified = _osc_verify_worker_result(
                    task_id,
                    result,
                    data_dir=data_dir,
                    locked_context=(task_dir, candidate_state),
                    wall_time_ns=self._wall_time_ns,
                    monotonic_time_ns=self._monotonic_ns,
                    clock_id=self._clock_id,
                )
                if _osc_thaw(current_verified) != prior_verified:
                    raise _osc_error(
                        "NODE_RESULT_WORKTREE_DRIFT",
                        "controller result observation changed before publication",
                    )
                _osc_publish_artifact(
                    task_dir, reference, content
                )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "result_id": payload.get("result_id"),
                        "content_sha256": reference["sha256"],
                        "locator": reference["locator"],
                    },
                )

            return effect_inputs, execution_id, dispatch

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_RESULT_ACCEPT,
            event_type="orchestration_result_accepted",
            operation_facts={
                "result_sha256": _osc_digest(result_value)
            },
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def evaluate_barrier(
        self,
        task_id: str,
        barrier_value: object = None,
        *,
        dependent_result_ids: _OscSequence[str] = (),
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        if barrier_value is not None or dependent_result_ids:
            raise _osc_error(
                "ORCHESTRATION_BARRIER_CALLER_DEFINITION_FORBIDDEN",
                "barrier membership, policy, join, and invalidation closure are package-owned",
            )

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            barrier = _osc_derive_barrier_definition(
                state,
                orchestration,
                _osc_resolve_multi_bundle(state),
            )
            barrier_id = str(barrier["barrier_id"])
            barriers = orchestration["barriers"]
            accepted = orchestration["accepted_results"]
            current = orchestration["current_results"]
            assert isinstance(barriers, dict)
            assert isinstance(accepted, dict)
            assert isinstance(current, dict)
            prior = barriers.get(barrier_id)
            values = {
                node_id: {
                    "schema": ACCEPTED_NODE_RESULT_SCHEMA,
                    "accepted": accepted[result_id]["accepted"],
                    "current": (
                        current.get(node_id) == result_id
                    ),
                    "repository_evidence_sha256": accepted[result_id][
                        "repository_evidence_sha256"
                    ],
                    "lease_quiesced": accepted[result_id][
                        "lease_quiesced"
                    ],
                    "runtime_live": accepted[result_id][
                        "runtime_live"
                    ],
                    "result": accepted[result_id]["result"],
                }
                for node_id, result_id in current.items()
                if result_id in accepted
            }
            evaluation = evaluate_result_barrier(
                barrier,
                values,
                previous_aggregate=(
                    prior.get("aggregate")
                    if isinstance(prior, dict)
                    else None
                ),
                dependent_result_ids=(),
            )
            barriers[barrier_id] = {
                "definition": _osc_thaw(barrier),
                "status": evaluation.status,
                "aggregate": _osc_thaw(evaluation.aggregate),
                "current_results": _osc_thaw(
                    evaluation.current_results
                ),
                "invalidated_node_instance_ids": list(
                    evaluation.invalidated_node_instance_ids
                ),
                "dependent_result_ids_to_invalidate": list(
                    evaluation.dependent_result_ids_to_invalidate
                ),
            }
            return {
                "barrier_id": barrier_id,
                "status": evaluation.status,
                "barrier_sha256": (
                    evaluation.aggregate["barrier_sha256"]
                    if evaluation.aggregate is not None
                    else None
                ),
                "blockers": [
                    {
                        "node_instance_id": blocker.node_instance_id,
                        "codes": list(blocker.codes),
                    }
                    for blocker in evaluation.blockers
                ],
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_BARRIER_CLOSE,
            event_type="orchestration_barrier_evaluated",
            operation_facts={"semantic": "derived-current-barrier"},
            mutate=mutate,
        )

    def reopen_barrier(
        self,
        task_id: str,
        *,
        barrier_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            barriers = orchestration["barriers"]
            assert isinstance(barriers, dict)
            record = barriers.get(barrier_id)
            if (
                not isinstance(record, dict)
                or record.get("status") != "CLOSED"
                or record.get("aggregate") is None
            ):
                raise _osc_error(
                    "ORCHESTRATION_BARRIER_NOT_CLOSED",
                    "barrier reopening requires one currently closed aggregate",
                    details={"barrier_id": barrier_id},
                )
            record["status"] = "REOPENED"
            record["aggregate"] = None
            return {
                "barrier_id": barrier_id,
                "reason": reason,
                "status": "REOPENED",
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_BARRIER_REOPEN,
            event_type="orchestration_barrier_reopened",
            operation_facts={
                "barrier_id": barrier_id,
                "reason": reason,
            },
            mutate=mutate,
        )

    def invalidate_result(
        self,
        task_id: str,
        *,
        result_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            accepted = orchestration["accepted_results"]
            current = orchestration["current_results"]
            assert isinstance(accepted, dict)
            assert isinstance(current, dict)
            record = accepted.get(result_id)
            if not isinstance(record, dict):
                raise _osc_error(
                    "NODE_RESULT_UNKNOWN",
                    "result cannot be invalidated because it is absent",
                )
            record["current"] = False
            node_id = record["result"]["node_instance_id"]
            if current.get(node_id) == result_id:
                current.pop(node_id)
            integration = orchestration.get("integration")
            if isinstance(integration, dict):
                integration["current"] = False
                integration["stale_reason"] = reason
            verification = orchestration.get(
                "integration_verification"
            )
            if isinstance(verification, dict):
                verification["current"] = False
            review = orchestration.get("review")
            if isinstance(review, dict):
                review["current"] = False
            return {"result_id": result_id, "reason": reason}

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_RESULT_INVALIDATE,
            event_type="orchestration_result_invalidated",
            operation_facts={
                "result_id": result_id,
                "reason": reason,
            },
            mutate=mutate,
        )

    def request_cancellation(
        self,
        task_id: str,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            projections = [
                self._runtime_lease_projection(orchestration, lease_id)
                for lease_id in sorted(orchestration["leases"])
            ]
            candidate = build_cancellation_candidate(
                projections,
                expected_revision=int(state["revision"]),
                current_revision=int(state["revision"]),
                approval_current=True,
            )
            orchestration["cancellation"] = {
                "requested": True,
                "quiesced": False,
                "affected_lease_ids": sorted(
                    (
                        str(projection["lease_id"])
                        for projection in projections
                    ),
                    key=_osc_utf8_sort_key,
                ),
                "uncertain_lease_ids": list(
                    candidate.lease_ids_requiring_reconciliation
                ),
            }
            return {
                "requested": True,
                "quiesced": False,
                "affected_lease_ids": sorted(
                    (
                        str(projection["lease_id"])
                        for projection in projections
                    ),
                    key=_osc_utf8_sort_key,
                ),
                "lease_ids_to_revoke": list(
                    candidate.lease_ids_to_revoke
                ),
                "lease_ids_requiring_reconciliation": list(
                    candidate.lease_ids_requiring_reconciliation
                ),
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_CANCELLATION_REQUEST,
            event_type="orchestration_cancellation_requested",
            operation_facts={
                "semantic": "all-current-leases",
            },
            mutate=mutate,
        )

    def record_timeout(
        self,
        task_id: str,
        *,
        lease_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            projection = self._runtime_lease_projection(
                orchestration, lease_id
            )
            decision = evaluate_lease_timeout(
                projection,
                monotonic_ns=self._monotonic_ns,
                clock_id=self._clock_id,
            )
            observation = {
                "lease_id": lease_id,
                "expired": decision.expired,
                "cancellation_requested": (
                    decision.cancellation_requested
                ),
                "quiesced": decision.quiesced,
                "blockers": list(decision.blockers),
                "clock_id": self._clock_id,
            }
            timeout_id = "timeout:" + _osc_digest(observation)
            timeouts = orchestration["timeouts"]
            assert isinstance(timeouts, dict)
            if timeout_id in timeouts:
                raise _osc_error(
                    "ORCHESTRATION_TIMEOUT_DUPLICATE",
                    "timeout observation already has a durable identity",
                    details={"timeout_id": timeout_id},
                )
            timeouts[timeout_id] = {
                "timeout_id": timeout_id,
                **observation,
            }
            return {"timeout_id": timeout_id, **observation}

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_TIMEOUT_RECORD,
            event_type="orchestration_lease_timeout_recorded",
            operation_facts={"lease_id": lease_id},
            mutate=mutate,
        )

    def expire_lease(
        self,
        task_id: str,
        *,
        lease_id: str,
        timeout_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            timeouts = orchestration["timeouts"]
            leases = orchestration["leases"]
            dispatch = orchestration["dispatch"]
            assignments = orchestration["assignments"]
            assert isinstance(timeouts, dict)
            assert isinstance(leases, dict)
            assert isinstance(dispatch, dict)
            assert isinstance(assignments, dict)
            observation = timeouts.get(timeout_id)
            if (
                not isinstance(observation, dict)
                or observation.get("lease_id") != lease_id
                or observation.get("expired") is not True
            ):
                raise _osc_error(
                    "ORCHESTRATION_TIMEOUT_NOT_EXPIRING",
                    "lease expiry requires one current expired timeout observation",
                    details={
                        "lease_id": lease_id,
                        "timeout_id": timeout_id,
                    },
                )
            lease = validate_worker_lease(leases[lease_id])
            leases[lease_id] = expire_worker_lease(
                lease,
                wall_time_ns=self._wall_time_ns(),
                monotonic_time_ns=self._monotonic_ns(),
                clock_id=self._clock_id,
            ).as_dict()
            for assignment_id, assignment in assignments.items():
                credential = (
                    assignment.get("lease_credential")
                    if isinstance(assignment, dict)
                    else None
                )
                if (
                    isinstance(credential, dict)
                    and credential.get("lease_id") == lease_id
                    and isinstance(dispatch.get(assignment_id), dict)
                ):
                    dispatch[assignment_id][
                        "runtime_status"
                    ] = "EXPIRED"
            return {
                "lease_id": lease_id,
                "timeout_id": timeout_id,
                "state": "EXPIRED",
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_LEASE_EXPIRE,
            event_type="orchestration_lease_expired",
            operation_facts={
                "lease_id": lease_id,
                "timeout_id": timeout_id,
            },
            mutate=mutate,
        )

    def revoke_lease(
        self,
        task_id: str,
        *,
        lease_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            leases = orchestration["leases"]
            assert isinstance(leases, dict)
            lease = validate_worker_lease(leases[lease_id])
            leases[lease_id] = revoke_worker_lease(
                lease,
                revoked_at_wall_ns=self._wall_time_ns(),
                reason=reason,
            ).as_dict()
            return {
                "lease_id": lease_id,
                "reason": reason,
                "state": "REVOKED",
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_LEASE_REVOKE,
            event_type="orchestration_lease_revoked",
            operation_facts={
                "lease_id": lease_id,
                "reason": reason,
            },
            mutate=mutate,
        )

    def record_authenticated_stop(
        self,
        task_id: str,
        *,
        lease_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        prepared_stop: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            projection = self._runtime_lease_projection(
                orchestration, lease_id
            )
            if (
                self._runtime_stop_observer is None
                or self._runtime_stop_authenticator is None
            ):
                raise _osc_error(
                    "TRUSTED_RUNTIME_ADAPTER_REQUIRED",
                    "authenticated stop requires controller-configured runtime observation and authentication",
                )
            try:
                stop_observation = self._runtime_stop_observer(
                    projection
                )
            except Exception as exc:
                raise _osc_error(
                    "TRUSTED_RUNTIME_OBSERVATION_FAILED",
                    "trusted runtime stop observation failed",
                    details={"type": type(exc).__name__},
                ) from exc
            authenticated = authenticate_runtime_stop(
                projection,
                stop_observation,
                authentication_verifier=(
                    self._runtime_stop_authenticator
                ),
            )
            assignment = orchestration["assignments"][
                projection["assignment_id"]
            ]
            dispatch = orchestration["dispatch"][
                projection["assignment_id"]
            ]
            post_stop_snapshot = _osc_controller_worktree_snapshot(
                task_dir,
                assignment,
                dispatch,
                runtime_inactive=True,
            )
            proof = prove_quiescence_from_runtime_stop(
                projection, authenticated, post_stop_snapshot
            )
            self._persist_quiescence(orchestration, lease_id, proof)
            prepared_stop.clear()
            prepared_stop.update(
                {
                    "projection": projection,
                    "stop_observation": _osc_thaw(
                        stop_observation
                    ),
                    "proof_sha256": proof.proof_sha256,
                    "orchestration": _osc_copy.deepcopy(
                        orchestration
                    ),
                }
            )
            return {
                "lease_id": lease_id,
                "proof_sha256": proof.proof_sha256,
                "method": proof.method,
                "quiesced": True,
            }

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> _OscSequence[object]:
            projection = prepared_stop.get("projection")
            prepared_orchestration = prepared_stop.get(
                "orchestration"
            )
            if not isinstance(projection, _OscMapping) or not isinstance(
                prepared_orchestration, _OscMapping
            ):
                raise _osc_error(
                    "RUNTIME_STOP_PREPARATION_INVALID",
                    "runtime stop has no prepared authenticated proof",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-runtime-stop-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "lease_id": lease_id,
                        "proof_sha256": payload.get(
                            "proof_sha256"
                        ),
                    }
                )
            )
            assignment_id = str(
                projection["assignment_id"]
            )
            assignment = prepared_orchestration[
                "assignments"
            ][assignment_id]
            claim_binding = _osc_lease_worktree_claim_binding(
                task_dir,
                prepared_orchestration,
                task_id=task_id,
                lease_id=lease_id,
            )
            claim = claim_binding["claim"]
            if not isinstance(claim, _OscMapping):
                raise _osc_error(
                    "WORKTREE_WRITER_CLAIM_MISMATCH",
                    "runtime stop has no exact worktree claim",
                )
            target_execution_id = _osc_runtime_reservation_target(
                task_dir,
                task_id=task_id,
                lease_id=lease_id,
                control_action_id=(
                    ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD
                ),
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="control",
                scopes=_osc_effect_scopes(
                    repository_ids=(
                        str(projection["repository_id"]),
                    ),
                    node_ids=(
                        str(projection["node_instance_id"]),
                    ),
                    worktree_ids=(
                        str(
                            assignment[
                                "worktree_identity_sha256"
                            ]
                        ),
                    ),
                    lease_ids=(lease_id,),
                    paths=(str(assignment["worktree_path"]),),
                ),
                safe_inputs={
                    "lease_id": lease_id,
                    "assignment_id": assignment_id,
                    "proof_sha256": payload.get(
                        "proof_sha256"
                    ),
                    "worktree_claim_id": claim[
                        "claim_key_sha256"
                    ],
                    "worktree_claim_generation": claim[
                        "claim_generation"
                    ],
                    "registry_sha256": claim_binding[
                        "registry_sha256"
                    ],
                },
                attempt_id=(
                    "runtime-stop-"
                    + _osc_digest(
                        {
                            "lease_id": lease_id,
                            "assignment_id": assignment_id,
                        }
                    )[:32]
                ),
            )

            def dispatch(context: object) -> object:
                with _workspace_registry_lock(
                    resolve_data_dir(data_dir)
                ):
                    current_registry = (
                        _osc_read_worktree_claim_registry(
                            task_dir
                        )
                    )
                    if _osc_digest(current_registry) != str(
                        claim_binding["registry_sha256"]
                    ):
                        raise _osc_error(
                            "WORKTREE_WRITER_CLAIM_STALE",
                            "worktree claim registry changed after runtime stop was claimed",
                        )
                    _osc_release_lease_worktree_claim(
                        task_dir,
                        prepared_orchestration,
                        task_id=task_id,
                        lease_id=lease_id,
                        released_at_revision=(
                            int(candidate_state["revision"]) + 1
                        ),
                    )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "lease_id": lease_id,
                        "assignment_id": assignment_id,
                        "proof_sha256": payload.get(
                            "proof_sha256"
                        ),
                    },
                )

            return (
                effect_inputs,
                execution_id,
                dispatch,
                None,
                None,
                target_execution_id,
                ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
            )

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_RUNTIME_STOP_RECORD,
            event_type="orchestration_runtime_stop_authenticated",
            operation_facts={"lease_id": lease_id},
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def _persist_quiescence(
        self,
        orchestration: dict[str, object],
        lease_id: str,
        proof: LeaseQuiescenceProof,
    ) -> None:
        projection = self._runtime_lease_projection(
            orchestration, lease_id
        )
        validate_lease_quiescence_proof(projection, proof)
        proofs = orchestration["quiescence_proofs"]
        leases = orchestration["leases"]
        assert isinstance(proofs, dict)
        assert isinstance(leases, dict)
        proofs[lease_id] = _osc_proof_to_state(proof)
        lease = validate_worker_lease(leases[lease_id])
        if lease.state == "ACTIVE":
            lease = revoke_worker_lease(
                lease,
                revoked_at_wall_ns=self._wall_time_ns(),
                reason="runtime-stopped",
            )
        leases[lease_id] = validate_worker_lease(
            {
                **lease.as_dict(),
                "quiesced_at_wall_ns": self._wall_time_ns(),
                "quiescence_evidence_sha256": proof.proof_sha256,
            }
        ).as_dict()
        assignment = next(
            value
            for value in orchestration["assignments"].values()
            if value["lease_credential"]["lease_id"] == lease_id
        )
        dispatch = orchestration["dispatch"][
            assignment["assignment_id"]
        ]
        dispatch["runtime_status"] = "QUIESCED"
        dispatch["runtime_live"] = False
        for record in orchestration["accepted_results"].values():
            if (
                isinstance(record, dict)
                and record.get("result", {}).get("lease_id") == lease_id
            ):
                record["lease_quiesced"] = True
                record["runtime_live"] = False
        cancellation = orchestration["cancellation"]
        if (
            isinstance(cancellation, dict)
            and cancellation.get("requested") is True
        ):
            affected = cancellation.get("affected_lease_ids")
            if not isinstance(affected, list):
                raise _osc_error(
                    "CANCELLATION_STATE_INVALID",
                    "requested cancellation lacks its immutable affected lease set",
                )
            persisted_proofs = orchestration[
                "quiescence_proofs"
            ]
            evaluation = evaluate_cancellation_quiescence(
                [
                    self._runtime_lease_projection(
                        orchestration, affected_lease_id
                    )
                    for affected_lease_id in affected
                ],
                {
                    affected_lease_id: _osc_proof_from_state(
                        persisted_proofs[affected_lease_id]
                    )
                    for affected_lease_id in affected
                    if affected_lease_id in persisted_proofs
                },
            )
            cancellation["uncertain_lease_ids"] = list(
                evaluation.uncertain_lease_ids
            )
            cancellation["quiesced"] = evaluation.quiesced

    def begin_reconciliation(
        self,
        task_id: str,
        *,
        lease_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            projection = self._runtime_lease_projection(
                orchestration, lease_id
            )
            if self._runtime_isolation_observer is None:
                raise _osc_error(
                    "TRUSTED_RUNTIME_ADAPTER_REQUIRED",
                    "stable reconciliation requires a controller-configured isolation observer",
                )
            try:
                attestation = (
                    _osc_validate_runtime_isolation_attestation(
                        self._runtime_isolation_observer(
                            projection
                        ),
                        projection,
                    )
                )
            except FlowError:
                raise
            except Exception as exc:
                raise _osc_error(
                    "TRUSTED_RUNTIME_OBSERVATION_FAILED",
                    "trusted runtime isolation observation failed",
                    details={"type": type(exc).__name__},
                ) from exc
            assignment = orchestration["assignments"][
                projection["assignment_id"]
            ]
            dispatch = orchestration["dispatch"][
                projection["assignment_id"]
            ]
            first_snapshot = _osc_controller_worktree_snapshot(
                _task_dir,
                assignment,
                dispatch,
                runtime_inactive=True,
            )
            probe = begin_stable_reconciliation(
                projection,
                first_snapshot,
                monotonic_ns=self._monotonic_ns,
                clock_id=self._clock_id,
                required_stability_ns=(
                    KERNEL_MINIMUM_STABILITY_NS
                ),
                reason=reason,
                termination_confirmed=attestation[
                    "termination_confirmed"
                ],
                operator_isolation_confirmed=(
                    attestation[
                        "operator_isolation_confirmed"
                    ]
                ),
                termination_evidence_sha256=(
                    attestation[
                        "termination_evidence_sha256"
                    ]
                ),
                operator_isolation_evidence_sha256=(
                    attestation[
                        "operator_isolation_evidence_sha256"
                    ]
                ),
            )
            orchestration["reconciliation_probes"][lease_id] = {
                "lease_id": probe.lease_id,
                "assignment_id": probe.assignment_id,
                "lease_binding_sha256": probe.lease_binding_sha256,
                "clock_id": probe.clock_id,
                "started_monotonic_ns": probe.started_monotonic_ns,
                "required_stability_ns": probe.required_stability_ns,
                "snapshot_sha256": probe.snapshot_sha256,
                "snapshot": _osc_thaw(probe.snapshot),
                "reason": probe.reason,
                "termination_confirmed": probe.termination_confirmed,
                "termination_evidence_sha256": (
                    probe.termination_evidence_sha256
                ),
                "operator_isolation_confirmed": (
                    probe.operator_isolation_confirmed
                ),
                "operator_isolation_evidence_sha256": (
                    probe.operator_isolation_evidence_sha256
                ),
            }
            return {
                "lease_id": lease_id,
                "snapshot_sha256": probe.snapshot_sha256,
                "required_stability_ns": probe.required_stability_ns,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_RECONCILIATION_BEGIN,
            event_type="orchestration_reconciliation_started",
            operation_facts={
                "lease_id": lease_id,
                "reason": reason,
            },
            mutate=mutate,
        )

    def complete_reconciliation(
        self,
        task_id: str,
        *,
        lease_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        prepared_release: dict[str, object] = {}

        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            value = orchestration["reconciliation_probes"].get(
                lease_id
            )
            if not isinstance(value, dict):
                raise _osc_error(
                    "STABLE_RECONCILIATION_PROBE_REQUIRED",
                    "no persisted reconciliation probe exists",
                )
            probe = StableReconciliationProbe(**value)
            projection = self._runtime_lease_projection(
                orchestration, lease_id
            )
            assignment = orchestration["assignments"][
                projection["assignment_id"]
            ]
            dispatch = orchestration["dispatch"][
                projection["assignment_id"]
            ]
            second_snapshot = _osc_controller_worktree_snapshot(
                _task_dir,
                assignment,
                dispatch,
                runtime_inactive=True,
            )
            proof = complete_stable_reconciliation(
                projection,
                probe,
                second_snapshot,
                monotonic_ns=self._monotonic_ns,
                clock_id=self._clock_id,
            )
            self._persist_quiescence(orchestration, lease_id, proof)
            orchestration["reconciliation_probes"].pop(lease_id)
            return {
                "lease_id": lease_id,
                "proof_sha256": proof.proof_sha256,
                "method": proof.method,
                "quiesced": True,
            }

        def effect_builder(
            task_dir: _OscPath,
            old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> tuple[object, object, object]:
            del old_state
            candidate_orchestration = candidate_state.get(
                "orchestration"
            )
            if not isinstance(
                candidate_orchestration, _OscMapping
            ):
                raise _osc_error(
                    "WORKTREE_WRITER_CLAIM_MISMATCH",
                    "reconciliation candidate has no orchestration ledger",
                )
            binding = _osc_lease_worktree_claim_binding(
                task_dir,
                candidate_orchestration,
                task_id=task_id,
                lease_id=lease_id,
            )
            assignment = binding["assignment"]
            claim = binding["claim"]
            if not isinstance(
                assignment, _OscMapping
            ) or not isinstance(claim, _OscMapping):
                raise _osc_error(
                    "WORKTREE_WRITER_CLAIM_MISMATCH",
                    "reconciliation claim binding is malformed",
                )
            target_execution_id = _osc_runtime_reservation_target(
                task_dir,
                task_id=task_id,
                lease_id=lease_id,
                control_action_id=(
                    ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE
                ),
            )
            proof_sha256 = payload.get("proof_sha256")
            if not isinstance(proof_sha256, str):
                raise _osc_error(
                    "LEASE_QUIESCENCE_PROOF_INVALID",
                    "reconciliation effect lacks its exact proof digest",
                )
            authorization = preauthorization.authorization
            released_at_revision = (
                int(candidate_state["revision"]) + 1
            )
            prepared_release.clear()
            prepared_release.update(
                {
                    "assignment_id": str(
                        assignment["assignment_id"]
                    ),
                    "claim_key_sha256": str(
                        claim["claim_key_sha256"]
                    ),
                    "claim_generation": int(
                        claim["claim_generation"]
                    ),
                    "registry_sha256": str(
                        binding["registry_sha256"]
                    ),
                    "proof_sha256": proof_sha256,
                    "released_at_revision": (
                        released_at_revision
                    ),
                }
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="registry",
                scopes=_osc_effect_scopes(
                    repository_ids=(
                        str(assignment["repository_id"]),
                    ),
                    node_ids=(
                        str(assignment["node_instance_id"]),
                    ),
                    worktree_ids=(
                        str(
                            assignment[
                                "worktree_identity_sha256"
                            ]
                        ),
                    ),
                    lease_ids=(lease_id,),
                    paths=(str(assignment["worktree_path"]),),
                ),
                safe_inputs={
                    "worktree_claim_id": prepared_release[
                        "claim_key_sha256"
                    ],
                    "worktree_claim_generation": (
                        prepared_release["claim_generation"]
                    ),
                    "lease_id": lease_id,
                    "reconciliation_proof_sha256": (
                        proof_sha256
                    ),
                    "registry_sha256": prepared_release[
                        "registry_sha256"
                    ],
                },
                attempt_id=(
                    "reconciliation-release-"
                    + _osc_digest(
                        {
                            "lease_id": lease_id,
                            "claim_key_sha256": (
                                prepared_release[
                                    "claim_key_sha256"
                                ]
                            ),
                            "claim_generation": (
                                prepared_release[
                                    "claim_generation"
                                ]
                            ),
                            "proof_sha256": proof_sha256,
                        }
                    )[:32]
                ),
            )
            execution_id = (
                "orchestration-reconciliation-release-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "lease_id": lease_id,
                        "claim_key_sha256": (
                            prepared_release[
                                "claim_key_sha256"
                            ]
                        ),
                        "claim_generation": (
                            prepared_release[
                                "claim_generation"
                            ]
                        ),
                        "proof_sha256": proof_sha256,
                    }
                )
            )

            def dispatch(context: object) -> object:
                with _workspace_registry_lock(
                    resolve_data_dir(data_dir)
                ):
                    before = _osc_read_worktree_claim_registry(
                        task_dir
                    )
                    before_sha256 = _osc_digest(before)
                    if (
                        before_sha256
                        != prepared_release["registry_sha256"]
                    ):
                        raise _osc_error(
                            "WORKTREE_WRITER_CLAIM_STALE",
                            "worktree claim registry changed after effect claim",
                            details={
                                "expected_registry_sha256": (
                                    prepared_release[
                                        "registry_sha256"
                                    ]
                                ),
                                "actual_registry_sha256": (
                                    before_sha256
                                ),
                            },
                        )
                    _osc_release_worktree_claim(
                        task_dir,
                        task_id=task_id,
                        lease_id=lease_id,
                        assignment_id=str(
                            prepared_release["assignment_id"]
                        ),
                        claim_key_sha256=str(
                            prepared_release[
                                "claim_key_sha256"
                            ]
                        ),
                        claim_generation=int(
                            prepared_release[
                                "claim_generation"
                            ]
                        ),
                        released_at_revision=int(
                            prepared_release[
                                "released_at_revision"
                            ]
                        ),
                    )
                    observed = (
                        _osc_lease_worktree_claim_binding(
                            task_dir,
                            candidate_orchestration,
                            task_id=task_id,
                            lease_id=lease_id,
                        )
                    )
                    observed_claim = observed["claim"]
                    if (
                        not isinstance(
                            observed_claim, _OscMapping
                        )
                        or observed_claim.get("status")
                        != "RELEASED"
                        or observed_claim.get(
                            "released_at_revision"
                        )
                        != prepared_release[
                            "released_at_revision"
                        ]
                    ):
                        raise _osc_error(
                            "WORKTREE_WRITER_CLAIM_RELEASE_UNOBSERVED",
                            "claimed reconciliation did not reach the exact released terminal record",
                        )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "lease_id": lease_id,
                        "worktree_claim_id": (
                            prepared_release[
                                "claim_key_sha256"
                            ]
                        ),
                        "worktree_claim_generation": (
                            prepared_release[
                                "claim_generation"
                            ]
                        ),
                        "reconciliation_proof_sha256": (
                            proof_sha256
                        ),
                        "registry_before_sha256": (
                            prepared_release[
                                "registry_sha256"
                            ]
                        ),
                        "registry_after_sha256": (
                            observed["registry_sha256"]
                        ),
                    },
                )

            return (
                effect_inputs,
                execution_id,
                dispatch,
                None,
                None,
                target_execution_id,
                ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE,
            )

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=(
                ORCHESTRATION_OPERATION_RECONCILIATION_COMPLETE
            ),
            event_type="orchestration_reconciliation_completed",
            operation_facts={"lease_id": lease_id},
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def recover_runtime(
        self,
        task_id: str,
        *,
        lease_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            projection = self._runtime_lease_projection(
                orchestration, lease_id
            )
            if self._runtime_recovery_observer is None:
                raise _osc_error(
                    "TRUSTED_RUNTIME_ADAPTER_REQUIRED",
                    "runtime recovery requires a controller-configured observer",
                )
            try:
                observation = self._runtime_recovery_observer(
                    projection
                )
            except Exception as exc:
                raise _osc_error(
                    "TRUSTED_RUNTIME_OBSERVATION_FAILED",
                    "trusted runtime recovery observation failed",
                    details={"type": type(exc).__name__},
                ) from exc
            decision = evaluate_runtime_recovery(
                projection,
                observation,
                monotonic_ns=self._monotonic_ns,
                clock_id=self._clock_id,
            )
            assignment = next(
                value
                for value in orchestration["assignments"].values()
                if value["lease_credential"]["lease_id"] == lease_id
            )
            dispatch = orchestration["dispatch"].get(
                assignment["assignment_id"]
            )
            if decision.reattach:
                if not isinstance(dispatch, dict):
                    raise _osc_error(
                        "RUNTIME_HANDLE_UNAVAILABLE",
                        "an undispatched assignment cannot be reattached",
                    )
                dispatch["runtime_live"] = True
                dispatch["runtime_status"] = "ACTIVE"
            else:
                if isinstance(dispatch, dict):
                    dispatch["runtime_status"] = "ORPHANED"
                lease = validate_worker_lease(
                    orchestration["leases"][lease_id]
                )
                if lease.state == "ACTIVE":
                    orchestration["leases"][lease_id] = (
                        revoke_worker_lease(
                            lease,
                            revoked_at_wall_ns=self._wall_time_ns(),
                            reason="runtime-orphaned",
                        ).as_dict()
                    )
            return {
                "lease_id": lease_id,
                "status": decision.status,
                "reattach": decision.reattach,
                "replacement_allowed": decision.replacement_allowed,
                "blockers": list(decision.blockers),
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=(
                ORCHESTRATION_OPERATION_RUNTIME_RECOVERY_OBSERVE
            ),
            event_type="orchestration_runtime_recovered",
            operation_facts={"lease_id": lease_id},
            mutate=mutate,
        )

    def _frozen_legacy_abandon_attempt_alias(
        self,
        task_id: str,
        *,
        lease_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Close one proven-quiesced lost attempt with a formal result."""

        inspected = load_state(task_id, data_dir)
        if inspected.get("schema_version") == 3:
            raise _osc_error(
                "ORCHESTRATION_LEGACY_ALIAS_FORBIDDEN",
                "schema-v3 recovery observation and attempt abandonment are separate operations",
                details={"alias_id": ORCHESTRATION_ACTION_RECOVER},
            )
        try:
            parsed_request = validate_manager_capability_request(request)
            with _locked_state(
                task_id,
                data_dir,
                parsed_request.expected_revision,
                manager_effect_policy="formal",
            ) as (task_dir, state):
                old_state = _osc_copy.deepcopy(state)
                new_state = _osc_copy.deepcopy(state)
                orchestration = _osc_state_copy(new_state)
                authorization = self._authorize(
                    orchestration,
                    parsed_request,
                    principal,
                    action_id=ORCHESTRATION_ACTION_RECOVER,
                )
                sealed_authorization = (
                    _osc_preauthorize_manager_effect(
                        old_state,
                        orchestration,
                        authorization,
                        action_id=ORCHESTRATION_ACTION_RECOVER,
                    )
                )
                facts = v3_attempt_abandonment_facts(
                    old_state,
                    lease_id=lease_id,
                    reason=reason,
                    manager_authorization_id=(
                        authorization.authorization_id
                    ),
                )
                result_id = str(facts["result_id"])
                node_instance_id = str(
                    facts["node_instance_id"]
                )
                reference = _osc_store_artifact(
                    task_dir,
                    orchestration,
                    artifact_id=result_id,
                    content=facts["content"],
                    kind=V3_ATTEMPT_ABANDONMENT_SCHEMA,
                    semantic_sha256=str(facts["artifact_sha256"]),
                )
                if (
                    reference["locator"] != facts["locator"]
                    or reference["sha256"]
                    != facts["artifact_sha256"]
                    or reference["size"] != facts["artifact_size"]
                ):
                    raise _osc_error(
                        "V3_ATTEMPT_ABANDON_ARTIFACT_INVALID",
                        "controller artifact storage differs from formal abandonment facts",
                    )

                node = _osc_find_node(
                    new_state, node_instance_id
                )
                attempts = node.get("attempts")
                attempt_number = int(facts["attempt"])
                if (
                    not isinstance(attempts, list)
                    or len(attempts) != attempt_number
                    or not isinstance(attempts[-1], dict)
                ):
                    raise _osc_error(
                        "V3_ATTEMPT_ABANDON_NODE_INVALID",
                        "formal abandonment facts do not identify the current attempt",
                    )
                node["state"] = "BLOCKED"
                attempts[-1]["state"] = "BLOCKED"
                result_refs = attempts[-1].get("result_refs")
                if not isinstance(result_refs, list):
                    raise _osc_error(
                        "V3_ATTEMPT_HISTORY_REWRITE",
                        "current attempt result history is invalid",
                    )
                result_refs.append(
                    {
                        "schema": (
                            _workflow_state_result_reference_schema
                        ),
                        "result_id": result_id,
                        "task_id": task_id,
                        "bundle_sha256": state["workflow_ref"][
                            "bundle_sha256"
                        ],
                        "node_instance_id": node_instance_id,
                        "attempt": attempt_number,
                        "input_sha256": facts["input_sha256"],
                        "output_sha256": facts[
                            "artifact_sha256"
                        ],
                        "locator": facts["locator"],
                    }
                )

                payload = _osc_thaw(facts["event_payload"])
                accepted = orchestration["accepted_results"]
                current = orchestration["current_results"]
                assert isinstance(accepted, dict)
                assert isinstance(current, dict)
                accepted[result_id] = {
                    "schema": (
                        V3_ATTEMPT_ABANDONMENT_RECORD_SCHEMA
                    ),
                    "result": _osc_thaw(facts["document"]),
                    "receipt": {
                        "accepted_revision": int(state["revision"])
                        + 1,
                        "event_id": "",
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "payload": _osc_copy.deepcopy(payload),
                    },
                    "accepted": True,
                    "current": True,
                    "controller_owned": True,
                    "lease_quiesced": True,
                    "runtime_live": False,
                }
                current[node_instance_id] = result_id
                integration = orchestration.get("integration")
                if (
                    isinstance(integration, dict)
                    and integration.get("current") is True
                ):
                    integration["current"] = False
                    orchestration["integration_verification"] = None
                    orchestration["review"] = None
                new_state["orchestration"] = orchestration

                def finalize_event_binding(
                    candidate_state: dict[str, object],
                    event_id: str,
                ) -> None:
                    candidate_orchestration = candidate_state.get(
                        "orchestration"
                    )
                    candidate_results = (
                        candidate_orchestration.get(
                            "accepted_results"
                        )
                        if isinstance(
                            candidate_orchestration, dict
                        )
                        else None
                    )
                    candidate_record = (
                        candidate_results.get(result_id)
                        if isinstance(candidate_results, dict)
                        else None
                    )
                    candidate_receipt = (
                        candidate_record.get("receipt")
                        if isinstance(candidate_record, dict)
                        else None
                    )
                    if not isinstance(candidate_receipt, dict):
                        raise _osc_error(
                            "V3_ATTEMPT_ABANDON_RECEIPT_INVALID",
                            "candidate abandonment receipt is absent",
                        )
                    candidate_receipt["event_id"] = event_id

                event_type = V3_NODE_MUTATION_EVENT_TYPES[
                    V3_NODE_MUTATION_ATTEMPT_ABANDON
                ]
                event = commit_v3_node_event(
                    old_state,
                    new_state,
                    task_dir,
                    event_type,
                    payload,
                    operation=V3_NODE_MUTATION_ATTEMPT_ABANDON,
                    manager_authorization=sealed_authorization,
                    finalize_event_binding=finalize_event_binding,
                )
                return _osc_receipt(
                    event,
                    authorization_id=authorization.authorization_id,
                    payload=payload,
                )
        except Exception as exc:
            raise _osc_translate(exc) from exc

    def abandon_attempt(
        self,
        task_id: str,
        *,
        lease_id: str,
        reason: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        """Record one quiesced attempt abandonment as its own operation."""

        prepared_attempt: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            leases = orchestration["leases"]
            proofs = orchestration["quiescence_proofs"]
            attempts = orchestration["attempts"]
            assignments = orchestration["assignments"]
            dispatch_records = orchestration["dispatch"]
            assert isinstance(leases, dict)
            assert isinstance(proofs, dict)
            assert isinstance(attempts, dict)
            assert isinstance(assignments, dict)
            assert isinstance(dispatch_records, dict)
            lease = validate_worker_lease(leases[lease_id])
            proof = proofs.get(lease_id)
            if (
                lease.state not in {"REVOKED", "EXPIRED"}
                or lease.quiesced_at_wall_ns is None
                or lease.quiescence_evidence_sha256 is None
                or not isinstance(proof, dict)
                or proof.get("lease_id") != lease_id
                or proof.get("quiesced") is not True
                or proof.get("proof_sha256")
                != lease.quiescence_evidence_sha256
                or not isinstance(reason, str)
                or not reason.strip()
            ):
                raise _osc_error(
                    "V3_ATTEMPT_ABANDON_QUIESCENCE_REQUIRED",
                    "attempt abandonment requires a quiescence proof and reason",
                )
            assignment_id = proof.get("assignment_id")
            assignment = assignments.get(assignment_id)
            dispatch_record = dispatch_records.get(assignment_id)
            if (
                not isinstance(assignment_id, str)
                or not isinstance(assignment, dict)
                or assignment.get("node_instance_id")
                != lease.node_instance_id
                or assignment.get("attempt") != lease.attempt
                or not isinstance(dispatch_record, dict)
                or dispatch_record.get("runtime_status") != "QUIESCED"
                or dispatch_record.get("runtime_live") is not False
            ):
                raise _osc_error(
                    "V3_ATTEMPT_ABANDON_QUIESCENCE_REQUIRED",
                    "attempt abandonment requires the exact quiesced assignment",
                )
            node = _osc_find_node(state, lease.node_instance_id)
            node_attempts = node.get("attempts")
            if (
                node.get("state") != "RUNNING"
                or not isinstance(node_attempts, list)
                or len(node_attempts) != lease.attempt
                or not isinstance(node_attempts[-1], dict)
                or node_attempts[-1].get("state") != "RUNNING"
            ):
                raise _osc_error(
                    "V3_ATTEMPT_ABANDON_NODE_INVALID",
                    "attempt abandonment must target the current running attempt",
                )
            attempt_id = (
                "attempt-abandonment:"
                + _osc_digest(
                    {
                        "task_id": task_id,
                        "lease_id": lease_id,
                        "node_instance_id": (
                            lease.node_instance_id
                        ),
                        "attempt": lease.attempt,
                    }
                )
            )
            if attempt_id in attempts:
                raise _osc_error(
                    "V3_ATTEMPT_ABANDON_REPLAY",
                    "attempt abandonment is single-use",
                    details={"attempt_id": attempt_id},
                )
            document = {
                "schema": V3_ATTEMPT_ABANDONMENT_SCHEMA,
                "attempt_id": attempt_id,
                "task_id": task_id,
                "workflow_bundle_sha256": (
                    state["workflow_ref"]["bundle_sha256"]
                ),
                "lease_id": lease_id,
                "node_instance_id": lease.node_instance_id,
                "repository_id": lease.repository_id,
                "attempt": lease.attempt,
                "assignment_id": assignment_id,
                "state": "ABANDONED",
                "reason": reason,
                "quiescence_proof_sha256": proof.get(
                    "proof_sha256"
                ),
                "input_sha256": node_attempts[-1].get(
                    "input_sha256"
                ),
                "controller_owned": True,
            }
            content = _osc_canonical_bytes(document)
            content_sha256 = _osc_hashlib.sha256(
                content
            ).hexdigest()
            reference = _osc_artifact_reference(
                artifact_id=attempt_id,
                content=content,
                kind=V3_ATTEMPT_ABANDONMENT_SCHEMA,
                semantic_sha256=content_sha256,
            )
            attempts[attempt_id] = {
                **document,
                "reference": reference,
                "abandoned_at_revision": (
                    int(state["revision"]) + 1
                ),
            }
            node["state"] = "BLOCKED"
            node_attempts[-1]["state"] = "BLOCKED"
            result_refs = node_attempts[-1].get("result_refs")
            if not isinstance(result_refs, list):
                raise _osc_error(
                    "V3_ATTEMPT_HISTORY_REWRITE",
                    "current attempt result history is invalid",
                )
            result_refs.append(
                {
                    "schema": _workflow_state_result_reference_schema,
                    "result_id": attempt_id,
                    "task_id": task_id,
                    "bundle_sha256": state["workflow_ref"][
                        "bundle_sha256"
                    ],
                    "node_instance_id": lease.node_instance_id,
                    "attempt": lease.attempt,
                    "input_sha256": node_attempts[-1].get(
                        "input_sha256"
                    ),
                    "output_sha256": reference["sha256"],
                    "locator": reference["locator"],
                }
            )
            prepared_attempt.clear()
            prepared_attempt.update(
                {
                    "content": content,
                    "reference": reference,
                }
            )
            return {
                "attempt_id": attempt_id,
                "result_id": attempt_id,
                "lease_id": lease_id,
                "node_instance_id": lease.node_instance_id,
                "repository_id": lease.repository_id,
                "attempt": lease.attempt,
                "reason": reason,
                "locator": reference["locator"],
            }

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            _candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> _OscSequence[object]:
            reference = prepared_attempt.get("reference")
            content = prepared_attempt.get("content")
            if not isinstance(reference, _OscMapping) or not isinstance(
                content, bytes
            ):
                raise _osc_error(
                    "V3_ATTEMPT_ABANDON_ARTIFACT_INVALID",
                    "attempt abandonment has no prepared evidence",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-attempt-abandon-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "attempt_id": payload.get("attempt_id"),
                        "content_sha256": reference["sha256"],
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="filesystem",
                scopes=_osc_effect_scopes(
                    repository_ids=(
                        str(payload["repository_id"]),
                    ),
                    node_ids=(
                        str(payload["node_instance_id"]),
                    ),
                    worktree_ids=(
                        "attempt-" + _osc_digest(reference)[:32],
                    ),
                    lease_ids=(lease_id,),
                    paths=(
                        str(
                            (
                                task_dir / str(reference["locator"])
                            ).resolve()
                        ),
                    ),
                ),
                safe_inputs={
                    "attempt_id": payload.get("attempt_id"),
                    "content_sha256": reference["sha256"],
                    "locator": reference["locator"],
                },
                attempt_id=(
                    "abandon-" + _osc_digest(reference)[:32]
                ),
            )

            def dispatch(context: object) -> object:
                _osc_publish_artifact(
                    task_dir, reference, content
                )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "attempt_id": payload.get("attempt_id"),
                        "content_sha256": reference["sha256"],
                        "locator": reference["locator"],
                    },
                )

            return effect_inputs, execution_id, dispatch

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_ATTEMPT_ABANDON,
            event_type="orchestration_attempt_abandoned",
            operation_facts={
                "lease_id": lease_id,
                "reason": reason,
            },
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def request_retry(
        self,
        task_id: str,
        *,
        result_id: str,
        worktree_strategy: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            accepted = orchestration["accepted_results"]
            retries = orchestration["retries"]
            assert isinstance(accepted, dict)
            assert isinstance(retries, dict)
            record = accepted.get(result_id)
            result = (
                record.get("result")
                if isinstance(record, dict)
                else None
            )
            source_kind = "accepted-result"
            if isinstance(result, dict):
                node_instance_id = str(
                    result["node_instance_id"]
                )
                if (
                    orchestration["current_results"].get(
                        node_instance_id
                    )
                    != result_id
                ):
                    raise _osc_error(
                        "NODE_RESULT_NOT_CURRENT",
                        "retry requires the current accepted result",
                    )
                previous_attempt = int(result["attempt"])
            else:
                diagnostic = orchestration["attempts"].get(
                    result_id
                )
                if (
                    not isinstance(diagnostic, dict)
                    or diagnostic.get("state") != "ABANDONED"
                    or diagnostic.get("controller_owned") is not True
                    or not isinstance(
                        diagnostic.get("node_instance_id"), str
                    )
                    or isinstance(diagnostic.get("attempt"), bool)
                    or not isinstance(
                        diagnostic.get("attempt"), int
                    )
                ):
                    raise _osc_error(
                        "NODE_RESULT_UNKNOWN",
                        "retry source is neither a current result nor a controller abandonment diagnostic",
                    )
                source_kind = "attempt-abandonment"
                node_instance_id = str(
                    diagnostic["node_instance_id"]
                )
                previous_attempt = int(diagnostic["attempt"])
                node = _osc_find_node(
                    _state, node_instance_id
                )
                node_attempts = node.get("attempts")
                result_refs = (
                    node_attempts[-1].get("result_refs")
                    if (
                        isinstance(node_attempts, list)
                        and node_attempts
                        and isinstance(node_attempts[-1], dict)
                    )
                    else None
                )
                if (
                    node.get("state") != "BLOCKED"
                    or not isinstance(node_attempts, list)
                    or len(node_attempts) != previous_attempt
                    or not isinstance(node_attempts[-1], dict)
                    or node_attempts[-1].get("state") != "BLOCKED"
                    or not isinstance(result_refs, list)
                    or not any(
                        isinstance(reference, dict)
                        and reference.get("result_id") == result_id
                        for reference in result_refs
                    )
                ):
                    raise _osc_error(
                        "V3_ATTEMPT_ABANDON_RETRY_INVALID",
                        "retry source is not the current blocked abandonment diagnostic",
                    )
            retry_id = (
                "retry:"
                + _osc_digest(
                    {
                        "task_id": task_id,
                        "result_id": result_id,
                        "previous_attempt": previous_attempt,
                        "next_attempt": previous_attempt + 1,
                        "worktree_strategy": worktree_strategy,
                    }
                )
            )
            if retry_id in retries:
                raise _osc_error(
                    "RETRY_ALREADY_PENDING",
                    "retry identity has already been requested",
                )
            retry = {
                "retry_id": retry_id,
                "result_id": result_id,
                "node_instance_id": node_instance_id,
                "previous_attempt": previous_attempt,
                "next_attempt": previous_attempt + 1,
                "worktree_strategy": worktree_strategy,
                "source_kind": source_kind,
            }
            retries[retry_id] = retry
            node = _osc_find_node(_state, node_instance_id)
            if node.get("state") not in {"BLOCKED", "FAILED"}:
                raise _osc_error(
                    "RETRY_NODE_NOT_BLOCKED",
                    "retry requires a blocked or failed current node",
                )
            node["state"] = "READY"
            return _osc_copy.deepcopy(retry)

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_RETRY_REQUEST,
            event_type="orchestration_retry_requested",
            operation_facts={
                "result_id": result_id,
                "worktree_strategy": worktree_strategy,
            },
            mutate=mutate,
        )

    def capture_integration_snapshot(
        self,
        task_id: str,
        *,
        barrier_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        prepared_snapshot: dict[str, object] = {}

        def mutate(
            task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            plan = _osc_plan_from_state(task_dir, orchestration)
            barrier = orchestration["barriers"].get(barrier_id)
            if (
                not isinstance(barrier, dict)
                or barrier.get("status") != "CLOSED"
                or not isinstance(barrier.get("aggregate"), dict)
            ):
                raise _osc_error(
                    "INTEGRATION_BARRIER_NOT_CLOSED",
                    "integration requires a closed current barrier",
                )
            aggregate = barrier["aggregate"]
            members = aggregate["members"]
            member_repositories = sorted(
                (member["repository_id"] for member in members),
                key=_osc_utf8_sort_key,
            )
            expected_repositories = sorted(
                plan["repository_set"],
                key=_osc_utf8_sort_key,
            )
            if member_repositories != expected_repositories:
                raise _osc_error(
                    "INTEGRATION_REPOSITORY_SET_INCOMPLETE",
                    "integration snapshot must bind the complete repository set",
                    details={
                        "expected": expected_repositories,
                        "actual": member_repositories,
                    },
                )
            for lease_id, lease_value in orchestration[
                "leases"
            ].items():
                lease = validate_worker_lease(lease_value)
                if (
                    lease.repository_id in member_repositories
                    and lease.write_policy == "scoped-write"
                    and lease.quiesced_at_wall_ns is None
                ):
                    raise _osc_error(
                        "INTEGRATION_ACTIVE_WRITER",
                        "integration cannot capture while a writable lease is uncertain",
                        details={"lease_id": lease_id},
                    )
            accepted = orchestration["accepted_results"]
            current = orchestration["current_results"]
            snapshot_members = []
            for member in members:
                result_id = current.get(member["node_instance_id"])
                record = accepted.get(result_id)
                if (
                    not isinstance(record, dict)
                    or record.get("current") is not True
                    or record.get("lease_quiesced") is not True
                    or record.get("runtime_live") is not False
                ):
                    raise _osc_error(
                        "INTEGRATION_RESULT_NOT_CURRENT",
                        "integration member result is stale or non-quiesced",
                        details={
                            "node_instance_id": member[
                                "node_instance_id"
                            ]
                        },
                    )
                result = record["result"]
                lease_id = result["lease_id"]
                projection = self._runtime_lease_projection(
                    orchestration, lease_id
                )
                persisted_proof = orchestration[
                    "quiescence_proofs"
                ].get(lease_id)
                proof, post_stop_snapshot = _osc_proof_snapshot(
                    projection, persisted_proof
                )
                assignment = orchestration["assignments"].get(
                    projection["assignment_id"]
                )
                dispatch = orchestration["dispatch"].get(
                    projection["assignment_id"]
                )
                if not isinstance(
                    assignment, _OscMapping
                ) or not isinstance(dispatch, _OscMapping):
                    raise _osc_error(
                        "INTEGRATION_ASSIGNMENT_BINDING_INVALID",
                        "integration member lacks its persisted assignment binding",
                    )
                first_current = _osc_controller_worktree_snapshot(
                    task_dir,
                    assignment,
                    dispatch,
                    runtime_inactive=True,
                )
                second_current = _osc_controller_worktree_snapshot(
                    task_dir,
                    assignment,
                    dispatch,
                    runtime_inactive=True,
                )
                if (
                    _osc_canonical_bytes(first_current)
                    != _osc_canonical_bytes(second_current)
                    or first_current != post_stop_snapshot
                    or proof.worktree_fingerprint_sha256
                    != result["worktree_sha256"]
                    or first_current["worktree_fingerprint_sha256"]
                    != result["worktree_sha256"]
                    or first_current["changed_paths_sha256"]
                    != result["changed_paths_sha256"]
                ):
                    raise _osc_error(
                        "INTEGRATION_WORKTREE_DRIFT",
                        "current worktree no longer equals the exact accepted post-stop result",
                        details={
                            "repository_id": result[
                                "repository_id"
                            ],
                            "lease_id": lease_id,
                        },
                    )
                snapshot_members.append(
                    {
                        "repository_id": result["repository_id"],
                        "node_instance_id": result[
                            "node_instance_id"
                        ],
                        "assignment_id": projection[
                            "assignment_id"
                        ],
                        "lease_id": lease_id,
                        "result_id": result["result_id"],
                        "output_sha256": result["output_sha256"],
                        "worktree_sha256": result["worktree_sha256"],
                        "changed_paths_sha256": result[
                            "changed_paths_sha256"
                        ],
                        "verification_sha256": result[
                            "verification_sha256"
                        ],
                        "quiescence_proof_sha256": (
                            proof.proof_sha256
                        ),
                        "post_stop_snapshot_sha256": _osc_digest(
                            post_stop_snapshot
                        ),
                        "repository_common_dir_sha256": (
                            first_current[
                                "repository_common_dir_sha256"
                            ]
                        ),
                        "ownership_claim_sha256": first_current[
                            "ownership_claim_sha256"
                        ],
                    }
                )
            snapshot_members.sort(
                key=lambda item: _osc_utf8_sort_key(
                    item["repository_id"]
                )
            )
            payload = {
                "schema": ORCHESTRATION_INTEGRATION_SNAPSHOT_SCHEMA,
                "task_id": task_id,
                "workflow_bundle_sha256": plan[
                    "workflow_bundle_sha256"
                ],
                "plan_id": plan["plan_id"],
                "dag_sha256": aggregate["dag_sha256"],
                "map_epoch": plan["map_epoch"],
                "barrier_id": barrier_id,
                "barrier_sha256": aggregate["barrier_sha256"],
                "repository_set": list(plan["repository_set"]),
                "members": snapshot_members,
            }
            snapshot_sha256 = _osc_digest(payload)
            snapshot_id = "integration-snapshot:" + snapshot_sha256
            content = _osc_canonical_bytes(payload)
            reference = _osc_artifact_reference(
                artifact_id=snapshot_id,
                content=content,
                kind=ORCHESTRATION_INTEGRATION_SNAPSHOT_SCHEMA,
                semantic_sha256=snapshot_sha256,
            )
            artifacts = orchestration["artifacts"]
            assert isinstance(artifacts, dict)
            if snapshot_id in artifacts:
                raise _osc_error(
                    "INTEGRATION_SNAPSHOT_REPLAY",
                    "integration snapshot identity is single-use",
                    details={"snapshot_id": snapshot_id},
                )
            artifacts[snapshot_id] = reference
            orchestration["integration"] = {
                "snapshot_id": snapshot_id,
                "snapshot_sha256": snapshot_sha256,
                "locator": reference["locator"],
                "current": True,
                "stale_reason": None,
                "payload": payload,
            }
            orchestration["integration_verification"] = None
            orchestration["review"] = None
            prepared_snapshot.clear()
            prepared_snapshot.update(
                {
                    "content": content,
                    "reference": reference,
                    "payload": payload,
                }
            )
            return {
                "snapshot_id": snapshot_id,
                "snapshot_sha256": snapshot_sha256,
                "barrier_sha256": aggregate["barrier_sha256"],
                "repository_set": list(plan["repository_set"]),
            }

        def effect_builder(
            task_dir: _OscPath,
            _old_state: _OscMapping[str, object],
            candidate_state: _OscMapping[str, object],
            payload: _OscMapping[str, object],
            selection: object,
            preauthorization: object,
        ) -> _OscSequence[object]:
            reference = prepared_snapshot.get("reference")
            content = prepared_snapshot.get("content")
            snapshot_payload = prepared_snapshot.get("payload")
            if (
                not isinstance(reference, _OscMapping)
                or not isinstance(content, bytes)
                or not isinstance(snapshot_payload, _OscMapping)
            ):
                raise _osc_error(
                    "INTEGRATION_SNAPSHOT_INVALID",
                    "integration action has no prepared snapshot",
                )
            authorization = preauthorization.authorization
            execution_id = (
                "orchestration-integration-"
                + _osc_digest(
                    {
                        "authorization_id": (
                            authorization.authorization_id
                        ),
                        "snapshot_id": payload.get("snapshot_id"),
                        "content_sha256": reference["sha256"],
                    }
                )
            )
            effect_inputs = _osc_single_dispatch_effect_inputs(
                selection,
                kind="filesystem",
                scopes=_osc_effect_scopes(
                    node_ids=("controller-integration",),
                    paths=(
                        str(
                            (
                                task_dir / str(reference["locator"])
                            ).resolve()
                        ),
                    ),
                ),
                safe_inputs={
                    "snapshot_id": payload.get("snapshot_id"),
                    "content_sha256": reference["sha256"],
                    "locator": reference["locator"],
                },
                attempt_id=(
                    "integration-"
                    + _osc_digest(reference)[:32]
                ),
            )

            def dispatch(context: object) -> object:
                current_orchestration = _osc_state_copy(
                    candidate_state
                )
                members = snapshot_payload.get("members")
                if not isinstance(members, (list, tuple)):
                    raise _osc_error(
                        "INTEGRATION_SNAPSHOT_INVALID",
                        "prepared snapshot members are invalid",
                    )
                for member in members:
                    if not isinstance(member, _OscMapping):
                        raise _osc_error(
                            "INTEGRATION_SNAPSHOT_INVALID",
                            "prepared snapshot member is invalid",
                        )
                    assignment = current_orchestration[
                        "assignments"
                    ].get(member.get("assignment_id"))
                    record = current_orchestration[
                        "dispatch"
                    ].get(member.get("assignment_id"))
                    if not isinstance(
                        assignment, _OscMapping
                    ) or not isinstance(record, _OscMapping):
                        raise _osc_error(
                            "INTEGRATION_ASSIGNMENT_BINDING_INVALID",
                            "integration member lost its assignment",
                        )
                    first = _osc_controller_worktree_snapshot(
                        task_dir,
                        assignment,
                        record,
                        runtime_inactive=True,
                    )
                    second = _osc_controller_worktree_snapshot(
                        task_dir,
                        assignment,
                        record,
                        runtime_inactive=True,
                    )
                    if (
                        first != second
                        or first[
                            "worktree_fingerprint_sha256"
                        ]
                        != member.get("worktree_sha256")
                        or first["changed_paths_sha256"]
                        != member.get("changed_paths_sha256")
                    ):
                        raise _osc_error(
                            "INTEGRATION_WORKTREE_DRIFT",
                            "integration worktree changed before publication",
                        )
                _osc_publish_artifact(
                    task_dir, reference, content
                )
                return _osc_quiesced_effect_observation(
                    context,
                    receipt_facts={
                        "snapshot_id": payload.get("snapshot_id"),
                        "content_sha256": reference["sha256"],
                        "locator": reference["locator"],
                    },
                )

            return effect_inputs, execution_id, dispatch

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_ACTION_INTEGRATION_CAPTURE,
            event_type="orchestration_integration_captured",
            operation_facts={"barrier_id": barrier_id},
            mutate=mutate,
            effect_builder=effect_builder,
        )

    def record_integration_verification(
        self,
        task_id: str,
        *,
        snapshot_id: str,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            integration = orchestration.get("integration")
            if (
                not isinstance(integration, dict)
                or integration.get("snapshot_id") != snapshot_id
                or integration.get("current") is not True
            ):
                raise _osc_error(
                    "INTEGRATION_SNAPSHOT_STALE",
                    "integration verification does not bind the current snapshot",
                )
            expected = {
                member["repository_id"]: member["worktree_sha256"]
                for member in integration["payload"]["members"]
            }
            observed: dict[str, str] = {}
            drifted = False
            for member in integration["payload"]["members"]:
                assignment_id = member.get("assignment_id")
                lease_id = member.get("lease_id")
                assignment = orchestration["assignments"].get(
                    assignment_id
                )
                dispatch = orchestration["dispatch"].get(
                    assignment_id
                )
                if (
                    not isinstance(assignment_id, str)
                    or not isinstance(lease_id, str)
                    or not isinstance(assignment, _OscMapping)
                    or not isinstance(dispatch, _OscMapping)
                ):
                    drifted = True
                    break
                projection = self._runtime_lease_projection(
                    orchestration, lease_id
                )
                proof, proof_snapshot = _osc_proof_snapshot(
                    projection,
                    orchestration["quiescence_proofs"].get(
                        lease_id
                    ),
                )
                first = _osc_controller_worktree_snapshot(
                    task_dir,
                    assignment,
                    dispatch,
                    runtime_inactive=True,
                )
                second = _osc_controller_worktree_snapshot(
                    task_dir,
                    assignment,
                    dispatch,
                    runtime_inactive=True,
                )
                repository_id = member["repository_id"]
                observed[repository_id] = first[
                    "worktree_fingerprint_sha256"
                ]
                if (
                    first != second
                    or first != proof_snapshot
                    or proof.proof_sha256
                    != member.get("quiescence_proof_sha256")
                    or _osc_digest(proof_snapshot)
                    != member.get("post_stop_snapshot_sha256")
                    or first["worktree_fingerprint_sha256"]
                    != member["worktree_sha256"]
                    or first["changed_paths_sha256"]
                    != member["changed_paths_sha256"]
                ):
                    drifted = True
                    break
            if drifted or observed != expected:
                integration["current"] = False
                integration["stale_reason"] = "worktree-drift"
                orchestration["integration_verification"] = None
                orchestration["review"] = None
                return {
                    "snapshot_id": snapshot_id,
                    "outcome": "STALE",
                    "code": "INTEGRATION_WORKTREE_DRIFT",
                    "expected_worktree_sha256s": expected,
                }
            if self._integration_verifier is None:
                raise _osc_error(
                    "TRUSTED_INTEGRATION_VERIFIER_REQUIRED",
                    "integration verification requires a controller-configured trusted verifier",
                )
            verifier_input = {
                "schema": ORCHESTRATION_INTEGRATION_SNAPSHOT_SCHEMA,
                "snapshot_id": snapshot_id,
                "snapshot_sha256": integration["snapshot_sha256"],
                "repository_set": integration["payload"][
                    "repository_set"
                ],
                "observed_worktree_sha256s": observed,
            }
            try:
                raw_observation = self._integration_verifier(
                    verifier_input
                )
            except Exception as exc:
                raise _osc_error(
                    "TRUSTED_INTEGRATION_VERIFICATION_FAILED",
                    "trusted integration verifier failed",
                    details={"type": type(exc).__name__},
                ) from exc
            if not isinstance(raw_observation, _OscMapping):
                raise _osc_error(
                    "TRUSTED_INTEGRATION_OBSERVATION_INVALID",
                    "trusted integration observation must be an object",
                )
            observation = dict(raw_observation)
            observation_fields = {
                "schema",
                "snapshot_id",
                "snapshot_sha256",
                "outcome",
                "evidence_sha256",
                "verifier_id",
                "attestation_sha256",
            }
            attested = {
                key: value
                for key, value in observation.items()
                if key != "attestation_sha256"
            }
            if (
                set(observation) != observation_fields
                or observation.get("schema")
                != ORCHESTRATION_TRUSTED_INTEGRATION_OBSERVATION_SCHEMA
                or observation.get("snapshot_id") != snapshot_id
                or observation.get("snapshot_sha256")
                != integration["snapshot_sha256"]
                or observation.get("outcome")
                not in {"SUCCEEDED", "FAILED"}
                or not isinstance(observation.get("verifier_id"), str)
                or not observation["verifier_id"]
                or not isinstance(
                    observation.get("evidence_sha256"), str
                )
                or len(observation["evidence_sha256"]) != 64
                or not isinstance(
                    observation.get("attestation_sha256"), str
                )
                or observation["attestation_sha256"]
                != _osc_digest(attested)
            ):
                raise _osc_error(
                    "TRUSTED_INTEGRATION_OBSERVATION_INVALID",
                    "trusted integration observation is not exact or sealed",
                )
            outcome = str(observation["outcome"])
            evidence_sha256 = str(
                observation["evidence_sha256"]
            )
            if outcome not in {"SUCCEEDED", "FAILED"}:
                raise _osc_error(
                    "INTEGRATION_OUTCOME_INVALID",
                    "integration verification outcome is unsupported",
                )
            payload = {
                "schema": ORCHESTRATION_INTEGRATION_VERIFICATION_SCHEMA,
                "snapshot_id": snapshot_id,
                "snapshot_sha256": integration["snapshot_sha256"],
                "repository_set": integration["payload"][
                    "repository_set"
                ],
                "outcome": outcome,
                "evidence_sha256": evidence_sha256,
                "observed_worktree_sha256s": expected,
                "verifier_id": observation["verifier_id"],
                "attestation_sha256": observation[
                    "attestation_sha256"
                ],
            }
            verification_id = (
                "integration-verification:" + _osc_digest(payload)
            )
            orchestration["integration_verification"] = {
                "verification_id": verification_id,
                "current": True,
                "payload": payload,
            }
            orchestration["review"] = None
            return {
                "verification_id": verification_id,
                "snapshot_id": snapshot_id,
                "outcome": outcome,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_INTEGRATION_VERIFY,
            event_type="orchestration_integration_verified",
            operation_facts={"snapshot_id": snapshot_id},
            mutate=mutate,
        )

    def record_independent_review(
        self,
        task_id: str,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            _state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            integration = orchestration.get("integration")
            verification = orchestration.get(
                "integration_verification"
            )
            if (
                not isinstance(integration, dict)
                or integration.get("current") is not True
                or not isinstance(verification, dict)
                or verification.get("current") is not True
                or verification["payload"]["outcome"] != "SUCCEEDED"
            ):
                raise _osc_error(
                    "INDEPENDENT_REVIEW_INTEGRATION_REQUIRED",
                    "review requires current successful integration verification",
                )
            implementation_actors = {
                value["actor_id"]
                for value in orchestration["dispatch"].values()
                if isinstance(value, dict)
            }
            expected = {
                member["repository_id"]: member[
                    "changed_paths_sha256"
                ]
                for member in integration["payload"]["members"]
            }
            if self._independent_reviewer is None:
                raise _osc_error(
                    "TRUSTED_INDEPENDENT_REVIEWER_REQUIRED",
                    "independent review requires a controller-configured trusted reviewer",
                )
            reviewer_input = {
                "schema": ORCHESTRATION_INTEGRATION_VERIFICATION_SCHEMA,
                "integration_verification_id": verification[
                    "verification_id"
                ],
                "snapshot_id": integration["snapshot_id"],
                "repository_set": integration["payload"][
                    "repository_set"
                ],
                "reviewed_surface_sha256s": expected,
                "implementation_actor_ids": sorted(
                    implementation_actors,
                    key=_osc_utf8_sort_key,
                ),
            }
            try:
                raw_observation = self._independent_reviewer(
                    reviewer_input
                )
            except Exception as exc:
                raise _osc_error(
                    "TRUSTED_INDEPENDENT_REVIEW_FAILED",
                    "trusted independent reviewer failed",
                    details={"type": type(exc).__name__},
                ) from exc
            if not isinstance(raw_observation, _OscMapping):
                raise _osc_error(
                    "TRUSTED_REVIEW_OBSERVATION_INVALID",
                    "trusted review observation must be an object",
                )
            observation = dict(raw_observation)
            fields = {
                "schema",
                "reviewer_id",
                "integration_verification_id",
                "snapshot_id",
                "reviewed_surface_sha256s",
                "outcome",
                "evidence_sha256",
                "attestation_sha256",
            }
            attested = {
                key: value
                for key, value in observation.items()
                if key != "attestation_sha256"
            }
            if (
                set(observation) != fields
                or observation.get("schema")
                != ORCHESTRATION_TRUSTED_REVIEW_OBSERVATION_SCHEMA
                or observation.get("integration_verification_id")
                != verification["verification_id"]
                or observation.get("snapshot_id")
                != integration["snapshot_id"]
                or observation.get("reviewed_surface_sha256s")
                != expected
                or observation.get("outcome")
                not in {"SUCCEEDED", "FAILED"}
                or not isinstance(observation.get("reviewer_id"), str)
                or not observation["reviewer_id"]
                or not isinstance(
                    observation.get("evidence_sha256"), str
                )
                or len(observation["evidence_sha256"]) != 64
                or observation.get("attestation_sha256")
                != _osc_digest(attested)
            ):
                raise _osc_error(
                    "TRUSTED_REVIEW_OBSERVATION_INVALID",
                    "trusted review observation is not exact or sealed",
                )
            reviewer_id = str(observation["reviewer_id"])
            outcome = str(observation["outcome"])
            evidence_sha256 = str(
                observation["evidence_sha256"]
            )
            if reviewer_id in implementation_actors:
                raise _osc_error(
                    "INDEPENDENT_REVIEWER_CONFLICT",
                    "final reviewer must be independent from implementation workers",
                )
            if outcome not in {"SUCCEEDED", "FAILED"}:
                raise _osc_error(
                    "INDEPENDENT_REVIEW_OUTCOME_INVALID",
                    "review outcome is unsupported",
                )
            payload = {
                "schema": ORCHESTRATION_INDEPENDENT_REVIEW_SCHEMA,
                "reviewer_id": reviewer_id,
                "integration_verification_id": verification[
                    "verification_id"
                ],
                "snapshot_id": integration["snapshot_id"],
                "repository_set": integration["payload"][
                    "repository_set"
                ],
                "reviewed_surface_sha256s": expected,
                "outcome": outcome,
                "evidence_sha256": evidence_sha256,
                "attestation_sha256": observation[
                    "attestation_sha256"
                ],
            }
            review_id = "independent-review:" + _osc_digest(payload)
            orchestration["review"] = {
                "review_id": review_id,
                "current": True,
                "payload": payload,
            }
            return {
                "review_id": review_id,
                "snapshot_id": integration["snapshot_id"],
                "outcome": outcome,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_REVIEW_RECORD,
            event_type="orchestration_independent_review_recorded",
            operation_facts={"semantic": "current-integration-review"},
            mutate=mutate,
        )

    def commit_finalization(
        self,
        task_id: str,
        *,
        request: object,
        principal: object,
        data_dir: object = None,
    ) -> OrchestrationCommitReceipt:
        def mutate(
            _task_dir: _OscPath,
            state: dict[str, object],
            orchestration: dict[str, object],
        ) -> _OscMapping[str, object]:
            status = _osc_terminal_orchestration_status(
                state, target_status="DONE"
            )
            if status.get("ready") is not True:
                raise _osc_error(
                    "ORCHESTRATION_FINALIZATION_BLOCKED",
                    "finalization requires the current complete orchestration closure",
                    details={
                        "blockers": status.get("blockers", [])
                    },
                )
            if orchestration.get("finalization") is not None:
                raise _osc_error(
                    "ORCHESTRATION_FINALIZATION_EXISTS",
                    "finalization already has a durable identity",
                )
            binding = {
                "task_id": task_id,
                "task_revision": state["revision"],
                "snapshot_id": status.get("snapshot_id"),
                "integration_verification": orchestration.get(
                    "integration_verification"
                ),
                "review": orchestration.get("review"),
            }
            finalization_id = "finalization:" + _osc_digest(binding)
            orchestration["finalization"] = {
                "finalization_id": finalization_id,
                "current": True,
                "binding_sha256": _osc_digest(binding),
                "snapshot_id": status.get("snapshot_id"),
            }
            return {
                "finalization_id": finalization_id,
                "snapshot_id": status.get("snapshot_id"),
                "ready": True,
            }

        return self._simple_authorized_mutation(
            task_id=task_id,
            data_dir=data_dir,
            request=request,
            principal=principal,
            action_id=ORCHESTRATION_OPERATION_FINALIZATION_COMMIT,
            event_type="orchestration_finalization_committed",
            operation_facts={"target_status": "DONE"},
            mutate=mutate,
        )

    def finalization_status(
        self,
        task_id: str,
        *,
        data_dir: object = None,
    ) -> dict[str, object]:
        try:
            with _osc_locked_current_state(
                task_id, data_dir
            ) as (task_dir, state):
                status = _osc_fresh_terminal_orchestration_status(
                    task_dir,
                    state,
                    target_status="DONE",
                )
                return {
                    "task_id": task_id,
                    "revision": state["revision"],
                    **status,
                }
        except Exception as exc:
            raise _osc_translate(exc) from exc


def orchestration_controller_service(
    *,
    secret_resolver: _OscCallable[[str], bytearray],
    secret_publisher: _OscOptional[
        _OscCallable[[str, bytes], None]
    ] = None,
    random_bytes: _OscCallable[[int], bytearray] = _osc_random_secret,
    wall_time_ns: _OscCallable[[], int] = _osc_time.time_ns,
    monotonic_ns: _OscCallable[[], int] = _osc_system_monotonic_ns,
    clock_id: str = "process-monotonic",
    runtime_stop_observer: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    runtime_stop_authenticator: _OscOptional[
        _OscCallable[
            [
                _OscMapping[str, object],
                _OscMapping[str, object],
            ],
            bool,
        ]
    ] = None,
    runtime_isolation_observer: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    runtime_recovery_observer: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    integration_verifier: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    independent_reviewer: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    host_capability_observer: _OscOptional[
        _OscCallable[[_OscMapping[str, object]], object]
    ] = None,
    trusted_host_adapter_ids: _OscSequence[str] = (),
    protected_read_identity_sha256s: _OscSequence[str] = (),
    mutating_tool_ids: _OscSequence[str] = _osc_mutating_tool_ids,
) -> OrchestrationControllerService:
    return OrchestrationControllerService(
        secret_resolver=secret_resolver,
        secret_publisher=secret_publisher,
        random_bytes=random_bytes,
        wall_time_ns=wall_time_ns,
        monotonic_ns=monotonic_ns,
        clock_id=clock_id,
        runtime_stop_observer=runtime_stop_observer,
        runtime_stop_authenticator=runtime_stop_authenticator,
        runtime_isolation_observer=runtime_isolation_observer,
        runtime_recovery_observer=runtime_recovery_observer,
        integration_verifier=integration_verifier,
        independent_reviewer=independent_reviewer,
        host_capability_observer=host_capability_observer,
        trusted_host_adapter_ids=trusted_host_adapter_ids,
        protected_read_identity_sha256s=(
            protected_read_identity_sha256s
        ),
        mutating_tool_ids=mutating_tool_ids,
    )


def manager_authority_transaction_service_v1(
    *,
    secret_publisher: _OscOptional[
        _OscCallable[[str, bytes], None]
    ] = None,
    random_bytes: _OscCallable[[int], bytearray] = _osc_random_secret,
    wall_time_ns: _OscCallable[[], int] = _osc_time.time_ns,
    monotonic_ns: _OscCallable[[], int] = _osc_system_monotonic_ns,
    clock_id: str = "process-monotonic",
) -> OrchestrationControllerService:
    """Build the sealed schema-v3 manager authority transaction service."""

    return orchestration_controller_service(
        secret_resolver=lambda _capability_id: bytearray(),
        secret_publisher=secret_publisher,
        random_bytes=random_bytes,
        wall_time_ns=wall_time_ns,
        monotonic_ns=monotonic_ns,
        clock_id=clock_id,
    )
