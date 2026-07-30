# Intended for the shared scripts/dev_flow.py namespace after the workflow
# contracts are stable.  Record construction and reporting are deliberately
# pure.  The store at the end of this module is an isolated, best-effort
# observational sink and must never authorize workflow movement or evidence.
from __future__ import annotations

import contextlib as _node_telemetry_contextlib
import datetime as _node_telemetry_datetime
import errno as _node_telemetry_errno
import hashlib
import json
import os as _node_telemetry_os
import re
import stat as _node_telemetry_stat
import tempfile as _node_telemetry_tempfile
import threading as _node_telemetry_threading
import time as _node_telemetry_time
from dataclasses import dataclass
from pathlib import Path as _NodeTelemetryPath
from types import MappingProxyType
from typing import Iterator, Mapping, Sequence

try:  # POSIX process lock; Windows uses msvcrt below.
    import fcntl as _node_telemetry_fcntl
except ImportError:  # pragma: no cover - exercised only on native Windows
    _node_telemetry_fcntl = None  # type: ignore[assignment]

try:  # Windows byte-range lock; absent on POSIX.
    import msvcrt as _node_telemetry_msvcrt
except ImportError:  # pragma: no cover - exercised only on POSIX
    _node_telemetry_msvcrt = None  # type: ignore[assignment]


NODE_TELEMETRY_SCHEMA = "dev-flow-node-telemetry/v1"
NODE_TELEMETRY_REPORT_SCHEMA = "dev-flow-node-telemetry-report/v1"
NODE_TELEMETRY_WRITE_RESULT_SCHEMA = (
    "dev-flow-node-telemetry-write-result/v1"
)
NODE_TELEMETRY_USAGE_AVAILABLE = "available"
NODE_TELEMETRY_USAGE_UNAVAILABLE = "unavailable"
NODE_MODEL_POLICY_MAP_SCHEMA = "dev-flow-model-policy-map/v1"
NODE_TELEMETRY_MODEL_POLICIES = frozenset(
    {"economy", "balanced", "critical"}
)
NODE_TELEMETRY_OUTCOMES = frozenset(
    {
        "BLOCKED",
        "CANCELLED",
        "FAILED",
        "SKIPPED",
        "SUCCEEDED",
        "WAITING",
    }
)

_node_telemetry_stable_id_re = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$"
)
_node_telemetry_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_node_telemetry_timestamp_re = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"
)
_node_telemetry_usage_count_fields = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
_node_telemetry_store_lock_timeout_seconds = 1.0
_node_telemetry_store_lock_poll_seconds = 0.01
_node_telemetry_process_lock = _node_telemetry_threading.Lock()


class NodeTelemetryError(ValueError):
    """Stable validation failure for observational telemetry contracts."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
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


def _node_telemetry_freeze(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise NodeTelemetryError(
            "TELEMETRY_VALUE_INVALID",
            "telemetry contracts do not accept floating-point values",
        )
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NodeTelemetryError(
                    "TELEMETRY_VALUE_INVALID",
                    "telemetry object keys must be strings",
                )
            frozen[key] = _node_telemetry_freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_node_telemetry_freeze(item) for item in value)
    raise NodeTelemetryError(
        "TELEMETRY_VALUE_INVALID",
        "telemetry values must use canonical JSON types",
        details={"type": type(value).__name__},
    )


def _node_telemetry_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _node_telemetry_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_node_telemetry_thaw(item) for item in value]
    return value


def _node_telemetry_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _node_telemetry_thaw(_node_telemetry_freeze(value)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, NodeTelemetryError):
            raise
        raise NodeTelemetryError(
            "TELEMETRY_VALUE_INVALID",
            "telemetry value cannot be canonically encoded",
        ) from exc


def _node_telemetry_sha256(value: object) -> str:
    return hashlib.sha256(_node_telemetry_json_bytes(value)).hexdigest()


def _node_telemetry_stable_id(
    value: object, field: str
) -> str:
    if (
        not isinstance(value, str)
        or not _node_telemetry_stable_id_re.fullmatch(value)
    ):
        raise NodeTelemetryError(
            "TELEMETRY_IDENTITY_INVALID",
            "telemetry identity is missing or malformed",
            details={"field": field},
        )
    return value


def _node_telemetry_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _node_telemetry_sha256_re.fullmatch(value)
    ):
        raise NodeTelemetryError(
            "TELEMETRY_IDENTITY_INVALID",
            "telemetry digest is missing or malformed",
            details={"field": field},
        )
    return value


def _node_telemetry_nonnegative_integer(
    value: object, field: str
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise NodeTelemetryError(
            "TELEMETRY_COUNT_INVALID",
            "telemetry counts must be non-negative integers",
            details={"field": field},
        )
    return value


def _node_telemetry_timestamp(value: object, field: str) -> tuple[str, object]:
    if (
        not isinstance(value, str)
        or not _node_telemetry_timestamp_re.fullmatch(value)
    ):
        raise NodeTelemetryError(
            "TELEMETRY_TIME_INVALID",
            "telemetry timestamps must be canonical UTC milliseconds",
            details={"field": field},
        )
    try:
        parsed = _node_telemetry_datetime.datetime.strptime(
            value, "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=_node_telemetry_datetime.timezone.utc)
    except ValueError as exc:
        raise NodeTelemetryError(
            "TELEMETRY_TIME_INVALID",
            "telemetry timestamp is not a real UTC instant",
            details={"field": field},
        ) from exc
    return value, parsed


def _node_telemetry_usage(
    supplied: object,
) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]:
    """Normalize malformed or missing adapter usage to unavailable.

    Usage is never evidence, so a malformed provider payload is retained only
    as a bounded diagnostic instead of rejecting an otherwise valid result.
    """

    if supplied is None:
        return (
            MappingProxyType(
                {
                    "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                    "reason": "executor-did-not-report-usage",
                }
            ),
            (),
        )
    if not isinstance(supplied, Mapping):
        diagnostic = MappingProxyType(
            {
                "code": "TELEMETRY_USAGE_INVALID",
                "field": "usage",
                "received_type": type(supplied).__name__,
            }
        )
        return (
            MappingProxyType(
                {
                    "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                    "reason": "malformed-executor-usage",
                }
            ),
            (diagnostic,),
        )
    expected = set(_node_telemetry_usage_count_fields)
    if set(supplied) != expected:
        diagnostic = MappingProxyType(
            {
                "code": "TELEMETRY_USAGE_INVALID",
                "field": "usage",
                "missing": tuple(sorted(expected - set(supplied))),
                "unknown": tuple(sorted(set(supplied) - expected)),
            }
        )
        return (
            MappingProxyType(
                {
                    "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                    "reason": "malformed-executor-usage",
                }
            ),
            (diagnostic,),
        )
    counts: dict[str, object] = {
        "status": NODE_TELEMETRY_USAGE_AVAILABLE
    }
    for field in _node_telemetry_usage_count_fields:
        value = supplied[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            diagnostic = MappingProxyType(
                {
                    "code": "TELEMETRY_USAGE_INVALID",
                    "field": f"usage.{field}",
                    "received_type": type(value).__name__,
                }
            )
            return (
                MappingProxyType(
                    {
                        "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                        "reason": "malformed-executor-usage",
                    }
                ),
                (diagnostic,),
            )
        counts[field] = value
    if int(counts["cached_input_tokens"]) > int(
        counts["input_tokens"]
    ):
        diagnostic = MappingProxyType(
            {
                "code": "TELEMETRY_USAGE_CONTRADICTORY",
                "field": "usage.cached_input_tokens",
            }
        )
        return (
            MappingProxyType(
                {
                    "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                    "reason": "contradictory-executor-usage",
                }
            ),
            (diagnostic,),
        )
    if int(counts["reasoning_output_tokens"]) > int(
        counts["output_tokens"]
    ):
        diagnostic = MappingProxyType(
            {
                "code": "TELEMETRY_USAGE_CONTRADICTORY",
                "field": "usage.reasoning_output_tokens",
            }
        )
        return (
            MappingProxyType(
                {
                    "status": NODE_TELEMETRY_USAGE_UNAVAILABLE,
                    "reason": "contradictory-executor-usage",
                }
            ),
            (diagnostic,),
        )
    return MappingProxyType(counts), ()


@dataclass(frozen=True)
class NodeTelemetryRecord:
    """One immutable observation bound to an exact node attempt."""

    telemetry_id: str
    task_id: str
    bundle_sha256: str
    node_instance_id: str
    repository_id: str | None
    revision: int
    attempt: int
    executor_policy: str
    model_policy: str
    orchestration_role: str
    adapter_outcome: str
    evidence_outcome: str
    started_at: str
    ended_at: str
    duration_ms: int
    response_bytes: int
    artifact_bytes: int
    usage: Mapping[str, object]
    diagnostics: tuple[Mapping[str, object], ...]
    schema: str = NODE_TELEMETRY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "usage", _node_telemetry_freeze(dict(self.usage))
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                _node_telemetry_freeze(dict(item))
                for item in self.diagnostics
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "telemetry_id": self.telemetry_id,
            "task_id": self.task_id,
            "bundle_sha256": self.bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "attempt": self.attempt,
            "executor_policy": self.executor_policy,
            "model_policy": self.model_policy,
            "orchestration_role": self.orchestration_role,
            "adapter_outcome": self.adapter_outcome,
            "evidence_outcome": self.evidence_outcome,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "response_bytes": self.response_bytes,
            "artifact_bytes": self.artifact_bytes,
            "usage": _node_telemetry_thaw(self.usage),
            "diagnostics": _node_telemetry_thaw(self.diagnostics),
        }


def build_node_telemetry(
    *,
    task_id: object,
    bundle_sha256: object,
    node_instance_id: object,
    repository_id: object = None,
    revision: object,
    attempt: object,
    executor_policy: object,
    model_policy: object,
    orchestration_role: object,
    adapter_outcome: object,
    evidence_outcome: object,
    started_at: object,
    ended_at: object,
    duration_ms: object,
    response_bytes: object,
    artifact_bytes: object,
    usage: object = None,
) -> NodeTelemetryRecord:
    """Validate identity/timing and record adapter usage observationally."""

    normalized_task = _node_telemetry_stable_id(task_id, "task_id")
    normalized_bundle = _node_telemetry_digest(
        bundle_sha256, "bundle_sha256"
    )
    normalized_node = _node_telemetry_stable_id(
        node_instance_id, "node_instance_id"
    )
    normalized_repository = (
        None
        if repository_id is None
        else _node_telemetry_stable_id(
            repository_id, "repository_id"
        )
    )
    normalized_revision = _node_telemetry_nonnegative_integer(
        revision, "revision"
    )
    normalized_attempt = _node_telemetry_nonnegative_integer(
        attempt, "attempt"
    )
    if normalized_attempt < 1:
        raise NodeTelemetryError(
            "TELEMETRY_COUNT_INVALID",
            "telemetry attempt must be at least one",
            details={"field": "attempt"},
        )
    normalized_executor = _node_telemetry_stable_id(
        executor_policy, "executor_policy"
    )
    if model_policy not in NODE_TELEMETRY_MODEL_POLICIES:
        raise NodeTelemetryError(
            "TELEMETRY_MODEL_POLICY_INVALID",
            "telemetry must use a logical model policy",
            details={
                "model_policy": model_policy,
                "supported": sorted(NODE_TELEMETRY_MODEL_POLICIES),
            },
        )
    if orchestration_role not in {"manager", "worker"}:
        raise NodeTelemetryError(
            "TELEMETRY_ROLE_INVALID",
            "telemetry orchestration role must be manager or worker",
            details={"orchestration_role": orchestration_role},
        )
    if adapter_outcome not in NODE_TELEMETRY_OUTCOMES:
        raise NodeTelemetryError(
            "TELEMETRY_OUTCOME_INVALID",
            "adapter telemetry outcome is unsupported",
            details={"adapter_outcome": adapter_outcome},
        )
    if evidence_outcome not in NODE_TELEMETRY_OUTCOMES:
        raise NodeTelemetryError(
            "TELEMETRY_OUTCOME_INVALID",
            "evidence-derived outcome is unsupported",
            details={"evidence_outcome": evidence_outcome},
        )
    normalized_started_at, parsed_started_at = (
        _node_telemetry_timestamp(started_at, "started_at")
    )
    normalized_ended_at, parsed_ended_at = (
        _node_telemetry_timestamp(ended_at, "ended_at")
    )
    if parsed_ended_at < parsed_started_at:
        raise NodeTelemetryError(
            "TELEMETRY_TIME_INVALID",
            "telemetry end time cannot precede its start time",
            details={"field": "ended_at"},
        )
    normalized_duration = _node_telemetry_nonnegative_integer(
        duration_ms, "duration_ms"
    )
    normalized_response_bytes = _node_telemetry_nonnegative_integer(
        response_bytes, "response_bytes"
    )
    normalized_artifact_bytes = _node_telemetry_nonnegative_integer(
        artifact_bytes, "artifact_bytes"
    )
    normalized_usage, diagnostics = _node_telemetry_usage(usage)
    diagnostic_items = list(diagnostics)
    if adapter_outcome != evidence_outcome:
        diagnostic_items.append(
            MappingProxyType(
                {
                    "code": "TELEMETRY_EVIDENCE_OUTCOME_CONFLICT",
                    "adapter_outcome": adapter_outcome,
                    "evidence_outcome": evidence_outcome,
                    "authoritative": "evidence_outcome",
                }
            )
        )
    payload = {
        "schema": NODE_TELEMETRY_SCHEMA,
        "task_id": normalized_task,
        "bundle_sha256": normalized_bundle,
        "node_instance_id": normalized_node,
        "repository_id": normalized_repository,
        "revision": normalized_revision,
        "attempt": normalized_attempt,
        "executor_policy": normalized_executor,
        "model_policy": model_policy,
        "orchestration_role": orchestration_role,
        "adapter_outcome": adapter_outcome,
        "evidence_outcome": evidence_outcome,
        "started_at": normalized_started_at,
        "ended_at": normalized_ended_at,
        "duration_ms": normalized_duration,
        "response_bytes": normalized_response_bytes,
        "artifact_bytes": normalized_artifact_bytes,
        "usage": _node_telemetry_thaw(normalized_usage),
        "diagnostics": _node_telemetry_thaw(tuple(diagnostic_items)),
    }
    telemetry_id = (
        f"{NODE_TELEMETRY_SCHEMA}:"
        f"{_node_telemetry_sha256(payload)}"
    )
    return NodeTelemetryRecord(
        telemetry_id=telemetry_id,
        task_id=normalized_task,
        bundle_sha256=normalized_bundle,
        node_instance_id=normalized_node,
        repository_id=normalized_repository,
        revision=normalized_revision,
        attempt=normalized_attempt,
        executor_policy=normalized_executor,
        model_policy=str(model_policy),
        orchestration_role=str(orchestration_role),
        adapter_outcome=str(adapter_outcome),
        evidence_outcome=str(evidence_outcome),
        started_at=normalized_started_at,
        ended_at=normalized_ended_at,
        duration_ms=normalized_duration,
        response_bytes=normalized_response_bytes,
        artifact_bytes=normalized_artifact_bytes,
        usage=normalized_usage,
        diagnostics=tuple(diagnostic_items),
    )


@dataclass(frozen=True)
class NodeTelemetryWriteResult:
    """Best-effort result from the isolated observational store."""

    status: str
    telemetry_id: str | None
    path: str | None
    diagnostic: Mapping[str, object] | None = None
    schema: str = NODE_TELEMETRY_WRITE_RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.status not in {"created", "existing", "diagnostic"}:
            raise ValueError("unsupported telemetry write result status")
        if self.diagnostic is not None:
            object.__setattr__(
                self,
                "diagnostic",
                _node_telemetry_freeze(dict(self.diagnostic)),
            )

    @property
    def persisted(self) -> bool:
        return self.status in {"created", "existing"}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "telemetry_id": self.telemetry_id,
            "path": self.path,
            "diagnostic": (
                None
                if self.diagnostic is None
                else _node_telemetry_thaw(self.diagnostic)
            ),
        }


def node_telemetry_record_identity(
    record: NodeTelemetryRecord,
) -> str:
    """Derive the canonical identity without trusting the stored identifier."""

    if not isinstance(record, NodeTelemetryRecord):
        raise NodeTelemetryError(
            "TELEMETRY_RECORD_INVALID",
            "telemetry storage accepts only validated record objects",
        )
    payload = record.as_dict()
    payload.pop("telemetry_id", None)
    return f"{NODE_TELEMETRY_SCHEMA}:{_node_telemetry_sha256(payload)}"


def _node_telemetry_invalid_record(
    message: str,
    *,
    field: str | None = None,
) -> NodeTelemetryError:
    details: dict[str, object] = {}
    if field is not None:
        details["field"] = field
    return NodeTelemetryError(
        "TELEMETRY_RECORD_INVALID",
        message,
        details=details,
    )


def _node_telemetry_validate_usage_diagnostic(
    diagnostic: Mapping[str, object],
) -> str:
    code = diagnostic.get("code")
    field = diagnostic.get("field")
    if code == "TELEMETRY_USAGE_CONTRADICTORY":
        if (
            set(diagnostic) != {"code", "field"}
            or field
            not in {
                "usage.cached_input_tokens",
                "usage.reasoning_output_tokens",
            }
        ):
            raise _node_telemetry_invalid_record(
                "contradictory usage diagnostic is not canonical",
                field="diagnostics",
            )
        return str(code)
    if code != "TELEMETRY_USAGE_INVALID":
        raise _node_telemetry_invalid_record(
            "usage diagnostic code is unsupported",
            field="diagnostics",
        )
    if set(diagnostic) == {"code", "field", "received_type"}:
        received_type = diagnostic.get("received_type")
        if (
            not isinstance(field, str)
            or (
                field != "usage"
                and field
                not in {
                    f"usage.{item}"
                    for item in _node_telemetry_usage_count_fields
                }
            )
            or not isinstance(received_type, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", received_type)
        ):
            raise _node_telemetry_invalid_record(
                "malformed usage type diagnostic is not canonical",
                field="diagnostics",
            )
        return str(code)
    if set(diagnostic) == {"code", "field", "missing", "unknown"}:
        missing = diagnostic.get("missing")
        unknown = diagnostic.get("unknown")
        if (
            field != "usage"
            or not isinstance(missing, tuple)
            or not isinstance(unknown, tuple)
            or tuple(sorted(missing)) != missing
            or tuple(sorted(unknown)) != unknown
            or any(
                not isinstance(item, str)
                for item in (*missing, *unknown)
            )
            or any(
                item not in _node_telemetry_usage_count_fields
                for item in missing
            )
            or not missing
            and not unknown
        ):
            raise _node_telemetry_invalid_record(
                "malformed usage field diagnostic is not canonical",
                field="diagnostics",
            )
        return str(code)
    raise _node_telemetry_invalid_record(
        "usage diagnostic fields are not canonical",
        field="diagnostics",
    )


def _node_telemetry_validate_record(
    record: NodeTelemetryRecord,
) -> bytes:
    if not isinstance(record, NodeTelemetryRecord):
        raise _node_telemetry_invalid_record(
            "telemetry storage accepts only validated record objects"
        )
    if record.schema != NODE_TELEMETRY_SCHEMA:
        raise _node_telemetry_invalid_record(
            "telemetry record schema is unsupported",
            field="schema",
        )
    _node_telemetry_stable_id(record.task_id, "task_id")
    _node_telemetry_digest(record.bundle_sha256, "bundle_sha256")
    _node_telemetry_stable_id(
        record.node_instance_id, "node_instance_id"
    )
    if record.repository_id is not None:
        _node_telemetry_stable_id(
            record.repository_id, "repository_id"
        )
    _node_telemetry_stable_id(
        record.executor_policy, "executor_policy"
    )
    _node_telemetry_nonnegative_integer(record.revision, "revision")
    attempt = _node_telemetry_nonnegative_integer(
        record.attempt, "attempt"
    )
    if attempt < 1:
        raise _node_telemetry_invalid_record(
            "telemetry attempt must be at least one",
            field="attempt",
        )
    if record.model_policy not in NODE_TELEMETRY_MODEL_POLICIES:
        raise _node_telemetry_invalid_record(
            "telemetry model policy is unsupported",
            field="model_policy",
        )
    if record.orchestration_role not in {"manager", "worker"}:
        raise _node_telemetry_invalid_record(
            "telemetry orchestration role is unsupported",
            field="orchestration_role",
        )
    if (
        record.adapter_outcome not in NODE_TELEMETRY_OUTCOMES
        or record.evidence_outcome not in NODE_TELEMETRY_OUTCOMES
    ):
        raise _node_telemetry_invalid_record(
            "telemetry outcome is unsupported",
            field="outcome",
        )
    _, started_at = _node_telemetry_timestamp(
        record.started_at, "started_at"
    )
    _, ended_at = _node_telemetry_timestamp(
        record.ended_at, "ended_at"
    )
    if ended_at < started_at:
        raise _node_telemetry_invalid_record(
            "telemetry end time precedes its start time",
            field="ended_at",
        )
    for field in ("duration_ms", "response_bytes", "artifact_bytes"):
        _node_telemetry_nonnegative_integer(
            getattr(record, field), field
        )

    usage = dict(record.usage)
    usage_status = usage.get("status")
    expected_usage_diagnostic: str | None = None
    if usage_status == NODE_TELEMETRY_USAGE_AVAILABLE:
        if set(usage) != {
            "status",
            *_node_telemetry_usage_count_fields,
        }:
            raise _node_telemetry_invalid_record(
                "available usage fields are not canonical",
                field="usage",
            )
        for field in _node_telemetry_usage_count_fields:
            _node_telemetry_nonnegative_integer(
                usage.get(field), f"usage.{field}"
            )
        if int(usage["cached_input_tokens"]) > int(
            usage["input_tokens"]
        ) or int(usage["reasoning_output_tokens"]) > int(
            usage["output_tokens"]
        ):
            raise _node_telemetry_invalid_record(
                "available usage counts are contradictory",
                field="usage",
            )
    elif usage_status == NODE_TELEMETRY_USAGE_UNAVAILABLE:
        if set(usage) != {"status", "reason"}:
            raise _node_telemetry_invalid_record(
                "unavailable usage fields are not canonical",
                field="usage",
            )
        reason = usage.get("reason")
        if reason == "executor-did-not-report-usage":
            expected_usage_diagnostic = None
        elif reason == "malformed-executor-usage":
            expected_usage_diagnostic = "TELEMETRY_USAGE_INVALID"
        elif reason == "contradictory-executor-usage":
            expected_usage_diagnostic = (
                "TELEMETRY_USAGE_CONTRADICTORY"
            )
        else:
            raise _node_telemetry_invalid_record(
                "unavailable usage reason is unsupported",
                field="usage.reason",
            )
    else:
        raise _node_telemetry_invalid_record(
            "telemetry usage status is unsupported",
            field="usage.status",
        )

    diagnostics = tuple(dict(item) for item in record.diagnostics)
    expected_diagnostic_count = int(
        expected_usage_diagnostic is not None
    ) + int(record.adapter_outcome != record.evidence_outcome)
    if len(diagnostics) != expected_diagnostic_count:
        raise _node_telemetry_invalid_record(
            "telemetry diagnostics do not match the observation",
            field="diagnostics",
        )
    diagnostic_offset = 0
    if expected_usage_diagnostic is not None:
        actual_usage_diagnostic = (
            _node_telemetry_validate_usage_diagnostic(diagnostics[0])
        )
        if actual_usage_diagnostic != expected_usage_diagnostic:
            raise _node_telemetry_invalid_record(
                "usage diagnostic does not match usage availability",
                field="diagnostics",
            )
        diagnostic_offset = 1
    if record.adapter_outcome != record.evidence_outcome:
        expected_conflict = {
            "code": "TELEMETRY_EVIDENCE_OUTCOME_CONFLICT",
            "adapter_outcome": record.adapter_outcome,
            "evidence_outcome": record.evidence_outcome,
            "authoritative": "evidence_outcome",
        }
        if diagnostics[diagnostic_offset] != expected_conflict:
            raise _node_telemetry_invalid_record(
                "evidence conflict diagnostic is not canonical",
                field="diagnostics",
            )

    expected_identity = node_telemetry_record_identity(record)
    if record.telemetry_id != expected_identity:
        raise _node_telemetry_invalid_record(
            "telemetry identity does not match canonical record content",
            field="telemetry_id",
        )
    return _node_telemetry_json_bytes(record.as_dict()) + b"\n"


def _node_telemetry_lock_busy(error: OSError) -> bool:
    return error.errno in {
        _node_telemetry_errno.EACCES,
        _node_telemetry_errno.EAGAIN,
        _node_telemetry_errno.EDEADLK,
    }


def _node_telemetry_acquire_os_lock(
    handle: object,
    lock_path: _NodeTelemetryPath,
    deadline: float,
) -> None:
    while True:
        try:
            if _node_telemetry_fcntl is not None:
                _node_telemetry_fcntl.lockf(
                    handle.fileno(),  # type: ignore[attr-defined]
                    (
                        _node_telemetry_fcntl.LOCK_EX
                        | _node_telemetry_fcntl.LOCK_NB
                    ),
                    1,
                    0,
                    _node_telemetry_os.SEEK_SET,
                )
            elif _node_telemetry_msvcrt is not None:
                handle.seek(0)  # type: ignore[attr-defined]
                _node_telemetry_msvcrt.locking(
                    handle.fileno(),  # type: ignore[attr-defined]
                    _node_telemetry_msvcrt.LK_NBLCK,
                    1,
                )
            else:
                raise OSError(
                    _node_telemetry_errno.ENOSYS,
                    "no supported telemetry lock backend",
                    str(lock_path),
                )
            return
        except OSError as exc:
            if (
                _node_telemetry_lock_busy(exc)
                and _node_telemetry_time.monotonic() < deadline
            ):
                _node_telemetry_time.sleep(
                    _node_telemetry_store_lock_poll_seconds
                )
                continue
            if _node_telemetry_lock_busy(exc):
                raise TimeoutError(
                    "timed out waiting for the independent telemetry lock"
                ) from exc
            raise


def _node_telemetry_release_os_lock(
    handle: object,
) -> None:
    if _node_telemetry_fcntl is not None:
        _node_telemetry_fcntl.lockf(
            handle.fileno(),  # type: ignore[attr-defined]
            _node_telemetry_fcntl.LOCK_UN,
            1,
            0,
            _node_telemetry_os.SEEK_SET,
        )
    elif _node_telemetry_msvcrt is not None:
        handle.seek(0)  # type: ignore[attr-defined]
        _node_telemetry_msvcrt.locking(
            handle.fileno(),  # type: ignore[attr-defined]
            _node_telemetry_msvcrt.LK_UNLCK,
            1,
        )


def _node_telemetry_open_regular(
    path: _NodeTelemetryPath,
    *,
    create: bool,
) -> object:
    """Open one store file without following a replaceable symlink."""

    flags = _node_telemetry_os.O_RDWR
    if create:
        flags |= _node_telemetry_os.O_CREAT
    nofollow = getattr(_node_telemetry_os, "O_NOFOLLOW", 0)
    cloexec = getattr(_node_telemetry_os, "O_CLOEXEC", 0)
    binary = getattr(_node_telemetry_os, "O_BINARY", 0)
    try:
        before = path.lstat()
    except FileNotFoundError:
        before = None
    if before is not None and _node_telemetry_stat.S_ISLNK(
        before.st_mode
    ):
        raise OSError(
            _node_telemetry_errno.ELOOP,
            "telemetry store files must not be symbolic links",
            str(path),
        )
    descriptor = _node_telemetry_os.open(
        path, flags | nofollow | cloexec | binary, 0o600
    )
    try:
        opened = _node_telemetry_os.fstat(descriptor)
        after = path.lstat()
        if (
            not _node_telemetry_stat.S_ISREG(opened.st_mode)
            or _node_telemetry_stat.S_ISLNK(after.st_mode)
            or (
                hasattr(opened, "st_ino")
                and hasattr(after, "st_ino")
                and (
                    opened.st_ino != after.st_ino
                    or opened.st_dev != after.st_dev
                )
            )
        ):
            raise OSError(
                _node_telemetry_errno.ELOOP,
                "telemetry store file identity changed during open",
                str(path),
            )
        return _node_telemetry_os.fdopen(descriptor, "r+b")
    except BaseException:
        _node_telemetry_os.close(descriptor)
        raise


@_node_telemetry_contextlib.contextmanager
def _node_telemetry_store_lock(
    lock_path: _NodeTelemetryPath,
    timeout_seconds: float,
) -> Iterator[None]:
    acquired_process_lock = _node_telemetry_process_lock.acquire(
        timeout=timeout_seconds
    )
    if not acquired_process_lock:
        raise TimeoutError(
            "timed out waiting for the in-process telemetry lock"
        )
    handle = None
    locked = False
    try:
        handle = _node_telemetry_open_regular(
            lock_path, create=True
        )
        if _node_telemetry_os.name != "nt":
            _node_telemetry_os.chmod(lock_path, 0o600)
        handle.seek(0, _node_telemetry_os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            _node_telemetry_os.fsync(handle.fileno())
        handle.seek(0)
        _node_telemetry_acquire_os_lock(
            handle,
            lock_path,
            _node_telemetry_time.monotonic() + timeout_seconds,
        )
        locked = True
        yield
    finally:
        try:
            if handle is not None and locked:
                _node_telemetry_release_os_lock(handle)
        finally:
            if handle is not None:
                handle.close()
            _node_telemetry_process_lock.release()


def _node_telemetry_fsync_directory(
    directory: _NodeTelemetryPath,
) -> None:
    if _node_telemetry_os.name == "nt":
        return
    descriptor = _node_telemetry_os.open(
        directory, _node_telemetry_os.O_RDONLY
    )
    try:
        _node_telemetry_os.fsync(descriptor)
    finally:
        _node_telemetry_os.close(descriptor)


def _node_telemetry_atomic_create(
    path: _NodeTelemetryPath,
    content: bytes,
) -> bool:
    descriptor, temporary_name = _node_telemetry_tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = _NodeTelemetryPath(temporary_name)
    try:
        if _node_telemetry_os.name != "nt":
            _node_telemetry_os.fchmod(descriptor, 0o600)
        with _node_telemetry_os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            _node_telemetry_os.fsync(handle.fileno())
        try:
            _node_telemetry_os.link(temporary, path)
        except FileExistsError:
            return False
        _node_telemetry_fsync_directory(path.parent)
        return True
    finally:
        if descriptor >= 0:
            _node_telemetry_os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _node_telemetry_write_result(
    *,
    status: str,
    telemetry_id: str | None,
    path: _NodeTelemetryPath | None,
    diagnostic: Mapping[str, object] | None = None,
) -> NodeTelemetryWriteResult:
    return NodeTelemetryWriteResult(
        status=status,
        telemetry_id=telemetry_id,
        path=None if path is None else str(path),
        diagnostic=diagnostic,
    )


def _node_telemetry_store_diagnostic(
    *,
    code: str,
    message: str,
    telemetry_id: str | None,
    path: _NodeTelemetryPath | None,
    details: Mapping[str, object] | None = None,
) -> NodeTelemetryWriteResult:
    return _node_telemetry_write_result(
        status="diagnostic",
        telemetry_id=telemetry_id,
        path=path,
        diagnostic={
            "code": code,
            "message": message,
            "details": dict(details or {}),
        },
    )


def _node_telemetry_existing_result(
    path: _NodeTelemetryPath,
    expected: bytes,
    telemetry_id: str,
) -> NodeTelemetryWriteResult:
    with _node_telemetry_open_regular(path, create=False) as handle:
        handle.seek(0, _node_telemetry_os.SEEK_END)
        size = handle.tell()
        if size > 1024 * 1024:
            return _node_telemetry_store_diagnostic(
                code="TELEMETRY_STORE_CORRUPT",
                message=(
                    "the content-addressed telemetry path exceeds the "
                    "bounded record size"
                ),
                telemetry_id=telemetry_id,
                path=path,
            )
        handle.seek(0)
        existing = handle.read()
    if existing == expected:
        return _node_telemetry_write_result(
            status="existing",
            telemetry_id=telemetry_id,
            path=path,
        )
    try:
        parsed = json.loads(existing.decode("utf-8"))
        canonical_existing = (
            _node_telemetry_json_bytes(parsed) + b"\n"
        )
    except (UnicodeError, json.JSONDecodeError, NodeTelemetryError):
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_STORE_CORRUPT",
            message=(
                "the content-addressed telemetry path contains corrupt "
                "or non-canonical bytes"
            ),
            telemetry_id=telemetry_id,
            path=path,
        )
    if canonical_existing != existing or not isinstance(parsed, dict):
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_STORE_CORRUPT",
            message=(
                "the content-addressed telemetry path contains corrupt "
                "or non-canonical bytes"
            ),
            telemetry_id=telemetry_id,
            path=path,
        )
    if (
        parsed.get("schema") == NODE_TELEMETRY_SCHEMA
        and parsed.get("telemetry_id") == telemetry_id
    ):
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_STORE_CONFLICT",
            message=(
                "the telemetry identity is already bound to different "
                "canonical bytes"
            ),
            telemetry_id=telemetry_id,
            path=path,
        )
    return _node_telemetry_store_diagnostic(
        code="TELEMETRY_STORE_CORRUPT",
        message=(
            "the content-addressed telemetry path is bound to the wrong "
            "record identity"
        ),
        telemetry_id=telemetry_id,
        path=path,
    )


def _node_telemetry_created_directory(
    path: _NodeTelemetryPath,
) -> None:
    existed = path.exists()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise OSError(
            _node_telemetry_errno.ENOTDIR,
            "telemetry store path is not a controller-owned directory",
            str(path),
        )
    if not existed and _node_telemetry_os.name != "nt":
        _node_telemetry_os.chmod(path, 0o700)


def write_node_telemetry_record(
    data_dir: str | _node_telemetry_os.PathLike[str],
    record: NodeTelemetryRecord,
    *,
    lock_timeout_seconds: float = (
        _node_telemetry_store_lock_timeout_seconds
    ),
) -> NodeTelemetryWriteResult:
    """Best-effort atomic creation under ``<data-dir>/telemetry/node``.

    This function deliberately has no task-state, evidence, guard, readiness,
    plan, or outbox dependency.  Every validation, locking, and filesystem
    failure is returned as an observational diagnostic.
    """

    telemetry_id = (
        record.telemetry_id
        if isinstance(record, NodeTelemetryRecord)
        and isinstance(record.telemetry_id, str)
        else None
    )
    record_path: _NodeTelemetryPath | None = None
    try:
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or lock_timeout_seconds < 0
        ):
            raise ValueError("invalid telemetry lock timeout")
        canonical = _node_telemetry_validate_record(record)
        telemetry_id = record.telemetry_id
        digest = telemetry_id.rsplit(":", 1)[1]
        root = _NodeTelemetryPath(data_dir).expanduser().resolve(
            strict=False
        )
        telemetry_root = root / "telemetry"
        _node_telemetry_created_directory(telemetry_root)
        lock_path = telemetry_root / "node.lock"
        with _node_telemetry_store_lock(
            lock_path, float(lock_timeout_seconds)
        ):
            node_root = telemetry_root / "node"
            _node_telemetry_created_directory(node_root)
            shard = node_root / digest[:2]
            _node_telemetry_created_directory(shard)
            record_path = shard / f"{digest}.json"
            if record_path.is_symlink():
                raise OSError(
                    _node_telemetry_errno.ELOOP,
                    "telemetry record path must not be a symbolic link",
                    str(record_path),
                )
            if record_path.exists():
                return _node_telemetry_existing_result(
                    record_path, canonical, telemetry_id
                )
            created = _node_telemetry_atomic_create(
                record_path, canonical
            )
            if created:
                return _node_telemetry_write_result(
                    status="created",
                    telemetry_id=telemetry_id,
                    path=record_path,
                )
            return _node_telemetry_existing_result(
                record_path, canonical, telemetry_id
            )
    except NodeTelemetryError as exc:
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_RECORD_REJECTED",
            message="telemetry record validation failed",
            telemetry_id=telemetry_id,
            path=record_path,
            details={"record_error": exc.as_dict()},
        )
    except PermissionError as exc:
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_STORE_UNWRITABLE",
            message="the observational telemetry store is not writable",
            telemetry_id=telemetry_id,
            path=record_path,
            details={"error_type": type(exc).__name__},
        )
    except TimeoutError as exc:
        return _node_telemetry_store_diagnostic(
            code="TELEMETRY_STORE_UNAVAILABLE",
            message="the independent telemetry lock is unavailable",
            telemetry_id=telemetry_id,
            path=record_path,
            details={"error_type": type(exc).__name__},
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        code = (
            "TELEMETRY_STORE_UNWRITABLE"
            if isinstance(exc, OSError)
            and exc.errno
            in {
                _node_telemetry_errno.EACCES,
                _node_telemetry_errno.ENOSPC,
                _node_telemetry_errno.EPERM,
                _node_telemetry_errno.EROFS,
            }
            else "TELEMETRY_STORE_UNAVAILABLE"
        )
        return _node_telemetry_store_diagnostic(
            code=code,
            message="the observational telemetry store is unavailable",
            telemetry_id=telemetry_id,
            path=record_path,
            details={"error_type": type(exc).__name__},
        )


def _node_telemetry_record_tokens(
    record: NodeTelemetryRecord,
) -> int | None:
    if (
        record.usage.get("status")
        != NODE_TELEMETRY_USAGE_AVAILABLE
    ):
        return None
    # Codex reports cached input as a subset of input tokens and reasoning
    # output as a subset of output tokens.  The non-overlapping total is
    # therefore input + output; summing all four fields double-counts both
    # detail categories.
    return (
        int(record.usage["input_tokens"])
        + int(record.usage["output_tokens"])
    )


def _node_telemetry_usage_field_total(
    records: Sequence[NodeTelemetryRecord], field: str
) -> int:
    return sum(
        int(record.usage[field])
        for record in records
        if (
            record.usage.get("status")
            == NODE_TELEMETRY_USAGE_AVAILABLE
        )
    )


def _node_telemetry_percentile(
    values: Sequence[int], numerator: int, denominator: int
) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(
        1,
        (len(ordered) * numerator + denominator - 1) // denominator,
    )
    return ordered[min(rank - 1, len(ordered) - 1)]


def build_node_telemetry_report(
    records: Sequence[NodeTelemetryRecord],
    *,
    successful_task_ids: Sequence[str] = (),
    single_agent_baseline_tokens: int | None = None,
    observed_wall_time_ms: int | None = None,
    single_agent_baseline_wall_time_ms: int | None = None,
    accepted_results: int | None = None,
    evaluated_results: int | None = None,
) -> Mapping[str, object]:
    """Aggregate portable integer metrics without affecting task truth."""

    if any(
        not isinstance(record, NodeTelemetryRecord)
        for record in records
    ):
        raise NodeTelemetryError(
            "TELEMETRY_RECORD_INVALID",
            "telemetry reports accept only validated records",
        )
    if len({record.telemetry_id for record in records}) != len(records):
        raise NodeTelemetryError(
            "TELEMETRY_RECORD_DUPLICATE",
            "telemetry record identities must be unique",
        )
    successful = tuple(
        sorted(
            {
                _node_telemetry_stable_id(item, "successful_task_ids")
                for item in successful_task_ids
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    token_values = [
        value
        for value in (
            _node_telemetry_record_tokens(record)
            for record in records
        )
        if value is not None
    ]
    total_tokens = sum(token_values)
    total_input_tokens = _node_telemetry_usage_field_total(
        records, "input_tokens"
    )
    cached_input_tokens = _node_telemetry_usage_field_total(
        records, "cached_input_tokens"
    )
    total_output_tokens = _node_telemetry_usage_field_total(
        records, "output_tokens"
    )
    reasoning_output_tokens = _node_telemetry_usage_field_total(
        records, "reasoning_output_tokens"
    )
    retry_waste_tokens = sum(
        value
        for record, value in (
            (record, _node_telemetry_record_tokens(record))
            for record in records
        )
        if value is not None
        and record.evidence_outcome == "FAILED"
    )
    manager_tokens = sum(
        value
        for record, value in (
            (record, _node_telemetry_record_tokens(record))
            for record in records
        )
        if value is not None and record.orchestration_role == "manager"
    )
    if single_agent_baseline_tokens is not None:
        baseline = _node_telemetry_nonnegative_integer(
            single_agent_baseline_tokens,
            "single_agent_baseline_tokens",
        )
        if baseline == 0:
            raise NodeTelemetryError(
                "TELEMETRY_BASELINE_INVALID",
                "parallel comparison baseline must be positive",
            )
        parallel_multiplier_millis = total_tokens * 1000 // baseline
    else:
        parallel_multiplier_millis = None
    if (
        observed_wall_time_ms is None
        and single_agent_baseline_wall_time_ms is None
    ):
        observed_wall_time = None
        baseline_wall_time = None
        wall_time_ratio_millis = None
        wall_time_speedup_millis = None
        wall_time_saved_ms = None
        wall_time_gain_millis = None
    elif (
        observed_wall_time_ms is None
        or single_agent_baseline_wall_time_ms is None
    ):
        raise NodeTelemetryError(
            "TELEMETRY_WALL_TIME_BASELINE_INVALID",
            "observed and single-agent wall-time baselines must appear together",
        )
    else:
        observed_wall_time = _node_telemetry_nonnegative_integer(
            observed_wall_time_ms, "observed_wall_time_ms"
        )
        baseline_wall_time = _node_telemetry_nonnegative_integer(
            single_agent_baseline_wall_time_ms,
            "single_agent_baseline_wall_time_ms",
        )
        if observed_wall_time == 0 or baseline_wall_time == 0:
            raise NodeTelemetryError(
                "TELEMETRY_WALL_TIME_BASELINE_INVALID",
                "wall-time baselines must be positive",
            )
        wall_time_ratio_millis = (
            observed_wall_time * 1000 // baseline_wall_time
        )
        wall_time_speedup_millis = (
            baseline_wall_time * 1000 // observed_wall_time
        )
        wall_time_saved_ms = baseline_wall_time - observed_wall_time
        wall_time_gain_millis = (
            wall_time_saved_ms * 1000 // baseline_wall_time
        )
    if accepted_results is None and evaluated_results is None:
        quality_rate_millis = None
    else:
        accepted = _node_telemetry_nonnegative_integer(
            accepted_results, "accepted_results"
        )
        evaluated = _node_telemetry_nonnegative_integer(
            evaluated_results, "evaluated_results"
        )
        if accepted > evaluated or evaluated == 0:
            raise NodeTelemetryError(
                "TELEMETRY_QUALITY_INVALID",
                "quality counts require 0 <= accepted <= evaluated",
            )
        quality_rate_millis = accepted * 1000 // evaluated
    report = {
        "schema": NODE_TELEMETRY_REPORT_SCHEMA,
        "record_count": len(records),
        "usage_available_count": len(token_values),
        "usage_unavailable_count": len(records) - len(token_values),
        "total_tokens": total_tokens,
        "input_tokens": total_input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": total_output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "cached_input_ratio_millis": (
            cached_input_tokens * 1000 // total_input_tokens
            if total_input_tokens
            else None
        ),
        "tokens_per_successful_task": (
            total_tokens // len(successful) if successful else None
        ),
        "retry_waste_tokens": retry_waste_tokens,
        "retry_waste_ratio_millis": (
            retry_waste_tokens * 1000 // total_tokens
            if total_tokens
            else None
        ),
        "orchestration_overhead_tokens": manager_tokens,
        "orchestration_overhead_ratio_millis": (
            manager_tokens * 1000 // total_tokens
            if total_tokens
            else None
        ),
        "parallel_multiplier_millis": parallel_multiplier_millis,
        "observed_wall_time_ms": observed_wall_time,
        "single_agent_baseline_wall_time_ms": baseline_wall_time,
        "wall_time_ratio_millis": wall_time_ratio_millis,
        "wall_time_speedup_millis": wall_time_speedup_millis,
        "wall_time_saved_ms": wall_time_saved_ms,
        "wall_time_gain_millis": wall_time_gain_millis,
        "duration_ms_p50": _node_telemetry_percentile(
            [record.duration_ms for record in records], 50, 100
        ),
        "duration_ms_p95": _node_telemetry_percentile(
            [record.duration_ms for record in records], 95, 100
        ),
        "response_bytes": sum(
            record.response_bytes for record in records
        ),
        "artifact_bytes": sum(
            record.artifact_bytes for record in records
        ),
        "quality_rate_millis": quality_rate_millis,
        "successful_task_ids": list(successful),
    }
    return _node_telemetry_freeze(report)  # type: ignore[return-value]


def resolve_node_model_policy(
    policy: object,
    host_configuration: object,
) -> Mapping[str, object]:
    """Resolve a logical policy solely through explicit host configuration."""

    if policy not in NODE_TELEMETRY_MODEL_POLICIES:
        raise NodeTelemetryError(
            "TELEMETRY_MODEL_POLICY_INVALID",
            "telemetry must use a logical model policy",
            details={"model_policy": policy},
        )
    if not isinstance(host_configuration, Mapping):
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_INVALID",
            "host model policy configuration must be an object",
        )
    if set(host_configuration) != {"schema", "policies"}:
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_INVALID",
            "host model policy configuration fields are incomplete or unknown",
            details={
                "fields": sorted(
                    str(item) for item in host_configuration
                )
            },
        )
    if host_configuration.get("schema") != NODE_MODEL_POLICY_MAP_SCHEMA:
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_UNSUPPORTED",
            "host model policy configuration schema is unsupported",
            details={"schema": host_configuration.get("schema")},
        )
    policies = host_configuration.get("policies")
    if (
        not isinstance(policies, Mapping)
        or set(policies) != NODE_TELEMETRY_MODEL_POLICIES
    ):
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_INVALID",
            "host configuration must resolve every logical model policy",
            details={
                "missing": sorted(
                    NODE_TELEMETRY_MODEL_POLICIES
                    - set(policies if isinstance(policies, Mapping) else ())
                ),
                "unknown": sorted(
                    set(policies if isinstance(policies, Mapping) else ())
                    - NODE_TELEMETRY_MODEL_POLICIES
                ),
            },
        )
    selected = policies[policy]
    if not isinstance(selected, Mapping) or set(selected) not in (
        {"model", "reasoning_effort"},
        {"model", "reasoning_effort", "service_tier"},
    ):
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_INVALID",
            "resolved model policy fields are incomplete or unknown",
            details={"model_policy": policy},
        )
    for field in ("model", "reasoning_effort"):
        value = selected.get(field)
        if not isinstance(value, str) or not value:
            raise NodeTelemetryError(
                "MODEL_POLICY_CONFIGURATION_INVALID",
                "resolved model policy values must be non-empty strings",
                details={
                    "model_policy": policy,
                    "field": field,
                },
            )
    service_tier = selected.get("service_tier")
    if service_tier is not None and (
        not isinstance(service_tier, str) or not service_tier
    ):
        raise NodeTelemetryError(
            "MODEL_POLICY_CONFIGURATION_INVALID",
            "resolved service tier must be a non-empty string",
            details={"model_policy": policy},
        )
    result = {
        "schema": NODE_MODEL_POLICY_MAP_SCHEMA,
        "policy": policy,
        **dict(selected),
    }
    return _node_telemetry_freeze(result)  # type: ignore[return-value]


__all__ = [
    "NODE_TELEMETRY_MODEL_POLICIES",
    "NODE_MODEL_POLICY_MAP_SCHEMA",
    "NODE_TELEMETRY_OUTCOMES",
    "NODE_TELEMETRY_REPORT_SCHEMA",
    "NODE_TELEMETRY_SCHEMA",
    "NODE_TELEMETRY_WRITE_RESULT_SCHEMA",
    "NodeTelemetryError",
    "NodeTelemetryRecord",
    "NodeTelemetryWriteResult",
    "build_node_telemetry",
    "build_node_telemetry_report",
    "node_telemetry_record_identity",
    "resolve_node_model_policy",
    "write_node_telemetry_record",
]
