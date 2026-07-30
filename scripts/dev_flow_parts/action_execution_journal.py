"""Pure schema-v4 action-execution journal and index contracts.

This module deliberately owns no I/O and grants no execution authority.  It
normalizes and verifies strict records, computes portable identities, and
returns compare-and-swap/write-ahead plans for a controller-owned persistence
layer.  In particular, a claim plan is only data: callers must durably commit
the returned journal/index bytes under the required controller locks before
starting an executor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import struct
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Sequence


ACTION_EXECUTION_INDEX_SCHEMA = "dev-flow-v4-action-execution-index/v1"
ACTION_EXECUTION_JOURNAL_SCHEMA = "dev-flow-v4-action-execution-journal/v1"
ACTION_EFFECT_CONTAINMENT_SCHEMA = (
    "dev-flow-v4-action-effect-containment/v1"
)
ACTION_RUNTIME_RESERVATION_SCHEMA = (
    "dev-flow-v4-action-runtime-reservation/v1"
)
ACTION_RECONCILIATION_ATTEMPT_SCHEMA = (
    "dev-flow-v4-action-reconciliation-attempt/v1"
)
ACTION_COMPENSATION_EXECUTION_SCHEMA = (
    "dev-flow-v4-action-compensation-execution/v1"
)
ACTION_COMPENSATION_PLAN_SCHEMA = (
    "dev-flow-v4-action-compensation-plan/v1"
)
ACTION_EXECUTION_INDEX_PATH = "action-executions/index.json"

JOURNAL_RECORD_DOMAIN = (
    b"dev-flow-v4-action-execution-journal-record-v1\x00"
)
INDEX_RECORD_DOMAIN = b"dev-flow-v4-action-execution-index-record-v1\x00"
JOURNAL_KEY_DOMAIN = b"dev-flow-v4-action-execution-journal-key-v1\x00"
JOURNAL_SEAL_DOMAIN = (
    b"dev-flow-v4-action-execution-journal-seal-v1\x00"
)
ENGINE_PROOF_DOMAIN = b"dev-flow-v4-engine-commit-proof-v1\x00"
CONTAINMENT_RECORD_DOMAIN = (
    b"dev-flow-v4-action-effect-containment-record-v1\x00"
)
RUNTIME_RESERVATION_RECORD_DOMAIN = (
    b"dev-flow-v4-action-runtime-reservation-record-v1\x00"
)
RUNTIME_BINDING_DOMAIN = (
    b"dev-flow-v4-action-runtime-binding-v1\x00"
)
RECONCILIATION_RECORD_DOMAIN = (
    b"dev-flow-v4-action-reconciliation-attempt-record-v1\x00"
)
COMPENSATION_RECORD_DOMAIN = (
    b"dev-flow-v4-action-compensation-execution-record-v1\x00"
)
COMPENSATION_PLAN_DOMAIN = (
    b"dev-flow-v4-action-compensation-plan-v1\x00"
)
COMPENSATION_RECEIPT_DOMAIN = (
    b"dev-flow-v4-action-compensation-receipt-v1\x00"
)
SAFE_INPUT_DOMAIN = b"dev-flow-v4-action-effect-safe-input-v1\x00"
ACTION_EXECUTION_LOCK_ORDER = (
    "task",
    "repository",
    "worktree",
    "lease",
    "registry",
)

_SIGNED_INT64_MIN = -(2**63)
_SIGNED_INT64_MAX = 2**63 - 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "manager_secret",
        "raw_manager_secret",
        "secret_channel_value",
        "nonce",
        "raw_nonce",
        "request_nonce",
        "capability",
        "capability_token",
        "manager_capability",
    }
)
_SCOPE_FIELDS = (
    "repository_ids",
    "node_ids",
    "worktree_ids",
    "lease_ids",
    "paths",
    "external_resources",
)
_INDEX_FIELDS = frozenset(
    {"schema", "task_id", "revision", "entries", "record_sha256"}
)
_INDEX_ENTRY_FIELDS = frozenset(
    {
        "execution_id",
        "entry_kind",
        "target_execution_id",
        "control_action_id",
        "concurrency_class",
        "scopes",
        "pending_record_sha256",
        "record_sha256",
        "runtime_reservation",
    }
)
_JOURNAL_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "execution_id",
        "revision",
        "phase",
        "bindings",
        "effects",
        "receipt",
        "quarantine",
        "reconciliation_attempt_ids",
        "finalization",
        "record_sha256",
        "seal",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "task_revision",
        "pre_effect_state_sha256",
        "workflow_id",
        "workflow_version",
        "workflow_bundle_sha256",
        "action_edge_id",
        "authorization_action_edge_id",
        "completion_edge_id",
        "handler_id",
        "effect_plan_sha256",
        "concurrency_class",
        "scopes",
        "authorized_paths",
        "confirmation_sha256",
        "operation_sha256",
        "semantic_operation_sha256",
        "authorization_kind",
        "authorization_sha256",
        "capability_sha256",
        "request_sha256",
        "request_nonce_sha256",
        "principal",
        "guard_projection_sha256",
        "evidence_sha256",
        "approval_sha256",
        "ownership_sha256",
        "registry_state_sha256",
        "postcondition_contract_sha256",
        "verifier_before_sha256",
        "candidate_after_sha256",
        "revision_policy",
    }
)
_EFFECT_FIELDS = frozenset(
    {
        "effect_id",
        "kind",
        "settlement",
        "scopes",
        "safe_inputs",
        "safe_input_sha256",
        "idempotency_key_sha256",
        "predecessors",
        "parallel_group",
        "attempt_id",
        "phase",
        "settled_as",
        "claim_id",
        "containment_record_sha256",
        "runtime_binding_sha256",
        "receipt_sha256",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "receipt_sha256",
        "candidate_state_sha256",
        "event_batch_sha256",
        "engine_proof_sha256",
        "authorization_action_edge_id",
        "completion_edge_id",
    }
)
_QUARANTINE_FIELDS = frozenset(
    {"reason_code", "effect_id", "receipt_sha256", "details_sha256"}
)
_FINALIZATION_FIELDS = frozenset(
    {
        "task_commit_revision",
        "task_state_sha256",
        "event_sha256",
        "outbox_sha256",
        "nonce_consumed",
    }
)
_CONTAINMENT_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "execution_id",
        "effect_id",
        "claim_id",
        "attempt_id",
        "journal_schema",
        "journal_record_sha256",
        "revision",
        "phase",
        "runtime_handle_sha256",
        "receipt_sha256",
        "record_sha256",
    }
)
_RUNTIME_RESERVATION_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "execution_id",
        "effect_id",
        "lease_id",
        "runtime_handle_sha256",
        "scopes",
        "containment_record_sha256",
        "handoff_receipt_sha256",
        "stop_action_id",
        "reconcile_action_id",
        "phase",
        "result_event_sha256",
        "record_sha256",
    }
)
_RECONCILIATION_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "attempt_id",
        "target_execution_id",
        "revision",
        "phase",
        "bindings",
        "compensation_authorization",
        "outcome",
        "record_sha256",
    }
)
_COMPENSATION_AUTHORIZATION_FIELDS = frozenset(
    {
        "compensation_execution_id",
        "compensation_plan",
        "compensation_plan_sha256",
        "dual_approval_sha256",
        "host_principal",
        "host_approval_sha256",
        "workflow_principal",
        "workflow_approval_sha256",
    }
)
_RECONCILIATION_BINDING_FIELDS = frozenset(
    {
        "target_journal_record_sha256",
        "target_receipt_sha256",
        "effect_id",
        "expected_task_revision",
        "expected_index_revision",
        "expected_index_sha256",
        "expected_journal_revision",
        "expected_journal_sha256",
        "recovery_action_id",
        "authorization_kind",
        "authorization_sha256",
        "capability_sha256",
        "gate_sha256",
        "request_nonce_sha256",
        "engine_proof_sha256",
        "principal",
    }
)
_RECONCILIATION_OUTCOME_FIELDS = frozenset(
    {
        "decision",
        "proof_kind",
        "evidence_sha256",
        "recovery_event_sha256",
        "task_commit_revision",
        "task_state_sha256",
        "outbox_sha256",
        "nonce_consumed",
        "compensation_execution_id",
        "compensation_receipt_sha256",
        "dual_approval_sha256",
        "compensation_authorization_sha256",
        "runtime_reservation_sha256",
    }
)
_COMPENSATION_PLAN_FIELDS = frozenset(
    {
        "schema",
        "action_id",
        "effect_id",
        "safe_inputs",
        "safe_inputs_sha256",
        "postcondition_contract_sha256",
    }
)
_COMPENSATION_EXECUTION_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "execution_id",
        "target_execution_id",
        "authorization_attempt_id",
        "revision",
        "phase",
        "bindings",
        "claim_id",
        "receipt",
        "finalization",
        "record_sha256",
    }
)
_COMPENSATION_BINDING_FIELDS = frozenset(
    {
        "target_journal_record_sha256",
        "authorization_record_sha256",
        "compensation_plan",
        "compensation_plan_sha256",
        "dual_approval_sha256",
    }
)
_COMPENSATION_RECEIPT_FIELDS = frozenset(
    {
        "execution_id",
        "claim_id",
        "target_journal_record_sha256",
        "authorization_record_sha256",
        "compensation_plan_sha256",
        "effect_receipt_sha256",
        "postcondition_proof_sha256",
        "receipt_sha256",
    }
)
_COMPENSATION_FINALIZATION_FIELDS = frozenset(
    {
        "compensation_receipt_sha256",
        "recovery_event_sha256",
        "task_commit_revision",
        "task_state_sha256",
        "outbox_sha256",
        "nonce_consumed",
    }
)
_REVISION_FACT_FIELDS = frozenset(
    {
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
    }
)

_INDEX_ENTRY_KINDS = frozenset(
    {"ordinary", "control", "runtime-reservation"}
)
_CONCURRENCY_CLASSES = frozenset(
    {"exclusive-task", "scoped", "target-control"}
)
_JOURNAL_PHASES = frozenset(
    {
        "PREPARED",
        "DISPATCH_CLAIMED",
        "RUNNING",
        "QUIESCED",
        "HANDOFF_VERIFIED",
        "RECEIPT_VERIFIED",
        "COMMITTED",
        "QUARANTINED",
    }
)
_EFFECT_PHASES = frozenset(
    {
        "PLANNED",
        "CLAIMED",
        "RUNNING",
        "QUIESCED",
        "HANDOFF_VERIFIED",
        "VERIFIED",
        "QUARANTINED",
    }
)
_EFFECT_KINDS = frozenset(
    {
        "process",
        "git",
        "filesystem",
        "registry",
        "external",
        "runtime-dispatch",
        "control",
        "compensation",
    }
)
_SETTLEMENTS = frozenset(
    {"synchronous-quiescence", "asynchronous-handoff"}
)
_CONTAINMENT_PHASES = frozenset(
    {
        "SPAWN_PENDING",
        "RUNTIME_BOUND",
        "RELEASED",
        "QUIESCED",
        "HANDOFF_VERIFIED",
        "CLOSED",
        "QUARANTINED",
    }
)
_RUNTIME_RESERVATION_PHASES = frozenset(
    {"ACTIVE", "EXITED", "QUIESCED"}
)
_RECONCILIATION_PHASES = frozenset(
    {
        "PREPARED",
        "CLAIMED",
        "COMPENSATION_AUTHORIZED",
        "ACCEPTED",
        "ABANDONED",
        "COMPENSATED",
        "UNRESOLVED",
    }
)
_COMPENSATION_EXECUTION_PHASES = frozenset(
    {"PREPARED", "CLAIMED", "RECEIPT_VERIFIED", "COMMITTED"}
)
_TERMINAL_RECONCILIATION_PHASES = frozenset(
    {"ACCEPTED", "ABANDONED", "COMPENSATED", "UNRESOLVED"}
)
_CLOSING_RECONCILIATION_PHASES = frozenset(
    {"ACCEPTED", "ABANDONED", "COMPENSATED"}
)


class ActionExecutionJournalError(ValueError):
    """Stable structured rejection from the pure journal contract."""

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


@dataclass(frozen=True)
class CASToken:
    revision: int
    record_sha256: str


@dataclass(frozen=True)
class WriteAheadPlan:
    """The three durable stages of one index/journal write-ahead update."""

    expected_index: CASToken
    expected_journal: CASToken | None
    reserved_index: dict[str, object]
    journal_bytes: bytes
    promoted_index: dict[str, object]
    journal_record_sha256: str


@dataclass(frozen=True)
class ControlRotationPlan:
    """One CAS replacement of an indexed target-control child."""

    expected_index: CASToken
    old_execution_id: str
    old_record_sha256: str
    new_execution_id: str
    new_record_sha256: str
    reserved_index: dict[str, object]
    record_bytes: bytes
    promoted_index: dict[str, object]


@dataclass(frozen=True)
class EffectClaimPlan:
    """A first-claim CAS plan; it is not an execution credential."""

    expected_journal: CASToken
    expected_index: CASToken
    journal: dict[str, object]
    effect_id: str
    claim_id: str
    first_claim: bool


@dataclass(frozen=True)
class RecoveryDisposition:
    action: str
    requires_new_durable_claim: bool
    dispatcher_reinvocation_allowed: bool
    preserves_receipt: bool


@dataclass(frozen=True)
class ArchivePlan:
    execution_id: str
    record_sha256: str
    archive_bytes: bytes


@dataclass(frozen=True)
class IndexClosurePlan:
    expected_index: CASToken
    index: dict[str, object]
    mode: str


class _JsonSemanticError(Exception):
    def __init__(self, code: str, details: Mapping[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details)


def _error(
    code: str,
    message: str,
    *,
    details: Mapping[str, object] | None = None,
) -> ActionExecutionJournalError:
    return ActionExecutionJournalError(code, message, details=details)


def u64be(value: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(
            "ACTION_JOURNAL_U64_INVALID",
            "length must be an integer",
        )
    if value < 0 or value > 2**64 - 1:
        raise _error(
            "ACTION_JOURNAL_U64_INVALID",
            "value does not fit U64BE",
            details={"value": value},
        )
    return struct.pack(">Q", value)


def _reject_float(literal: str) -> object:
    raise _JsonSemanticError(
        "ACTION_JOURNAL_JSON_FLOAT_FORBIDDEN",
        {"literal": literal[:80]},
    )


def _parse_integer(literal: str) -> int:
    digits = literal[1:] if literal.startswith("-") else literal
    if len(digits) > 19:
        raise _JsonSemanticError(
            "ACTION_JOURNAL_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    value = int(literal)
    if value < _SIGNED_INT64_MIN or value > _SIGNED_INT64_MAX:
        raise _JsonSemanticError(
            "ACTION_JOURNAL_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    return value


def _reject_constant(literal: str) -> object:
    raise _JsonSemanticError(
        "ACTION_JOURNAL_JSON_NONFINITE_FORBIDDEN",
        {"literal": literal},
    )


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _JsonSemanticError(
                "ACTION_JOURNAL_JSON_DUPLICATE_KEY",
                {"key": key},
            )
        result[key] = value
    return result


def _validate_semantic_value(value: object, pointer: str = "") -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value < _SIGNED_INT64_MIN or value > _SIGNED_INT64_MAX:
            raise _error(
                "ACTION_JOURNAL_JSON_INTEGER_OUT_OF_RANGE",
                "semantic JSON integers must fit signed 64-bit",
                details={"pointer": pointer or "/", "value": str(value)[:80]},
            )
        return value
    if isinstance(value, float):
        raise _error(
            "ACTION_JOURNAL_JSON_FLOAT_FORBIDDEN",
            "semantic JSON forbids floats",
            details={"pointer": pointer or "/"},
        )
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _error(
                "ACTION_JOURNAL_JSON_UNICODE_INVALID",
                "semantic JSON strings must be valid Unicode",
                details={"pointer": pointer or "/"},
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise _error(
                "ACTION_JOURNAL_JSON_NOT_NFC",
                "semantic JSON strings and keys must use Unicode NFC",
                details={"pointer": pointer or "/"},
            )
        return value
    if isinstance(value, list):
        return [
            _validate_semantic_value(item, f"{pointer}/{index}")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(
                    "ACTION_JOURNAL_JSON_KEY_INVALID",
                    "semantic JSON object keys must be strings",
                    details={"pointer": pointer or "/"},
                )
            normalized_key = _validate_semantic_value(
                key, f"{pointer}/{key}"
            )
            assert isinstance(normalized_key, str)
            result[normalized_key] = _validate_semantic_value(
                item, f"{pointer}/{key}"
            )
        return result
    raise _error(
        "ACTION_JOURNAL_JSON_TYPE_INVALID",
        "value is not representable by strict semantic JSON",
        details={"pointer": pointer or "/", "type": type(value).__name__},
    )


def parse_semantic_json(source: bytes) -> object:
    if not isinstance(source, bytes):
        raise _error(
            "ACTION_JOURNAL_JSON_SOURCE_INVALID",
            "semantic JSON source must be bytes",
        )
    if source.startswith(b"\xef\xbb\xbf"):
        raise _error(
            "ACTION_JOURNAL_JSON_BOM_FORBIDDEN",
            "semantic JSON must not contain a UTF-8 BOM",
        )
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(
            "ACTION_JOURNAL_JSON_UTF8_INVALID",
            "semantic JSON must be valid UTF-8",
            details={"position": exc.start},
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_int=_parse_integer,
            parse_constant=_reject_constant,
        )
    except _JsonSemanticError as exc:
        raise _error(
            exc.code,
            "semantic JSON contains an ambiguous value",
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        details: dict[str, object] = {}
        if isinstance(exc, json.JSONDecodeError):
            details.update({"line": exc.lineno, "column": exc.colno})
        raise _error(
            "ACTION_JOURNAL_JSON_MALFORMED",
            "semantic JSON is malformed",
            details=details,
        ) from exc
    return _validate_semantic_value(value)


def semantic_json_bytes(value: object) -> bytes:
    normalized = _validate_semantic_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def semantic_sha256(domain: bytes, value: object) -> str:
    if not isinstance(domain, bytes) or not domain.endswith(b"\x00"):
        raise _error(
            "ACTION_JOURNAL_DOMAIN_INVALID",
            "digest domain must be NUL-terminated bytes",
        )
    payload = semantic_json_bytes(value)
    return hashlib.sha256(domain + u64be(len(payload)) + payload).hexdigest()


def _expect_object(value: object, pointer: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _error(
            "ACTION_JOURNAL_FIELD_INVALID",
            "value must be an object",
            details={"pointer": pointer, "type": type(value).__name__},
        )
    normalized = _validate_semantic_value(value, pointer)
    assert isinstance(normalized, dict)
    return normalized


def _expect_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    pointer: str,
) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise _error(
            "ACTION_JOURNAL_UNKNOWN_FIELD",
            "strict record contains unknown fields",
            details={"pointer": pointer, "fields": unknown},
        )
    if missing:
        raise _error(
            "ACTION_JOURNAL_REQUIRED_FIELD",
            "strict record is missing required fields",
            details={"pointer": pointer, "fields": missing},
        )


def _expect_string(
    value: object,
    pointer: str,
    *,
    identifier: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise _error(
            "ACTION_JOURNAL_FIELD_INVALID",
            "value must be a non-empty string",
            details={"pointer": pointer},
        )
    normalized = _validate_semantic_value(value, pointer)
    assert isinstance(normalized, str)
    if identifier and (
        not normalized[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:@/+-")
            for character in normalized
        )
    ):
        raise _error(
            "ACTION_JOURNAL_IDENTIFIER_INVALID",
            "identifier contains unsupported characters",
            details={"pointer": pointer, "value": normalized},
        )
    return normalized


def _expect_revision(value: object, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _error(
            "ACTION_JOURNAL_REVISION_INVALID",
            "revision must be a non-negative integer",
            details={"pointer": pointer},
        )
    if value > _SIGNED_INT64_MAX:
        raise _error(
            "ACTION_JOURNAL_REVISION_INVALID",
            "revision must fit signed 64-bit",
            details={"pointer": pointer},
        )
    return value


def _expect_path_component(value: object, pointer: str) -> str:
    text = _expect_string(value, pointer)
    if (
        text in {".", ".."}
        or text.endswith((".", " "))
        or any(
            character in '/\\:*?"<>|'
            or ord(character) < 32
            or ord(character) == 127
            for character in text
        )
    ):
        raise _error(
            "ACTION_JOURNAL_PATH_COMPONENT_INVALID",
            "record identity is not a safe single path component",
            details={"pointer": pointer, "value": text},
        )
    return text


def action_execution_active_path(execution_id: str) -> str:
    component = _expect_path_component(execution_id, "/execution_id")
    return f"action-executions/active/{component}.json"


def action_execution_archive_path(execution_id: str) -> str:
    component = _expect_path_component(execution_id, "/execution_id")
    return f"action-executions/archive/{component}.json"


def action_effect_containment_path(
    execution_id: str,
    effect_id: str,
) -> str:
    execution = _expect_path_component(execution_id, "/execution_id")
    effect = _expect_path_component(effect_id, "/effect_id")
    return f"action-executions/containment/{execution}/{effect}.json"


def action_reconciliation_attempt_path(attempt_id: str) -> str:
    component = _expect_path_component(attempt_id, "/attempt_id")
    return f"action-executions/reconciliation/{component}.json"


def action_reconciliation_archive_path(attempt_id: str) -> str:
    component = _expect_path_component(attempt_id, "/attempt_id")
    return f"action-executions/reconciliation/archive/{component}.json"


def action_reconciliation_rotation_path(attempt_id: str) -> str:
    component = _expect_path_component(attempt_id, "/attempt_id")
    return f"action-executions/reconciliation/rotated/{component}.json"


def action_compensation_active_path(execution_id: str) -> str:
    component = _expect_path_component(execution_id, "/execution_id")
    return f"action-executions/compensation/active/{component}.json"


def action_compensation_archive_path(execution_id: str) -> str:
    component = _expect_path_component(execution_id, "/execution_id")
    return f"action-executions/compensation/archive/{component}.json"


def _expect_sha256(
    value: object,
    pointer: str,
    *,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise _error(
            "ACTION_JOURNAL_DIGEST_INVALID",
            "digest must be lowercase hexadecimal SHA-256",
            details={"pointer": pointer},
        )
    return value


def _digest_equal(first: object, second: object) -> bool:
    return (
        isinstance(first, str)
        and isinstance(second, str)
        and _SHA256_RE.fullmatch(first) is not None
        and _SHA256_RE.fullmatch(second) is not None
        and hmac.compare_digest(first, second)
    )


def _expect_bool(value: object, pointer: str) -> bool:
    if not isinstance(value, bool):
        raise _error(
            "ACTION_JOURNAL_FIELD_INVALID",
            "value must be a boolean",
            details={"pointer": pointer},
        )
    return value


def _expect_choice(
    value: object,
    choices: frozenset[str],
    pointer: str,
) -> str:
    text = _expect_string(value, pointer)
    if text not in choices:
        raise _error(
            "ACTION_JOURNAL_ENUM_INVALID",
            "value is not in the closed enum",
            details={"pointer": pointer, "value": text},
        )
    return text


def _expect_sorted_unique_strings(
    value: object,
    pointer: str,
    *,
    identifiers: bool = False,
    paths: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise _error(
            "ACTION_JOURNAL_FIELD_INVALID",
            "value must be an array",
            details={"pointer": pointer},
        )
    result: list[str] = []
    for index, item in enumerate(value):
        text = _expect_string(
            item,
            f"{pointer}/{index}",
            identifier=identifiers,
        )
        if paths:
            text = _normalize_path(text, f"{pointer}/{index}")
        result.append(text)
    canonical = sorted(set(result), key=lambda item: item.encode("utf-8"))
    if result != canonical or len(result) != len(canonical):
        raise _error(
            "ACTION_JOURNAL_ORDER_INVALID",
            "array must be unique and sorted by NFC UTF-8 bytes",
            details={"pointer": pointer},
        )
    return result


def _normalize_path(value: str, pointer: str) -> str:
    if (
        "\x00" in value
        or "\\" in value
        or "//" in value
        or (value != "/" and value.endswith("/"))
    ):
        raise _error(
            "ACTION_JOURNAL_PATH_INVALID",
            "path scope must use canonical forward-slash spelling",
            details={"pointer": pointer, "value": value},
        )
    parts = value.split("/")
    significant = parts[1:] if value.startswith("/") else parts
    if not significant or any(part in {"", ".", ".."} for part in significant):
        if value != "/":
            raise _error(
                "ACTION_JOURNAL_PATH_INVALID",
                "path scope must not contain empty, dot, or dot-dot segments",
                details={"pointer": pointer, "value": value},
            )
    return value


def _reject_secret_fields(value: object, pointer: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in _FORBIDDEN_SECRET_KEYS:
                raise _error(
                    "ACTION_JOURNAL_RAW_SECRET_FORBIDDEN",
                    "raw nonce, manager secret, and capability fields are forbidden",
                    details={"pointer": f"{pointer}/{key}"},
                )
            _reject_secret_fields(item, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_fields(item, f"{pointer}/{index}")


def _contains_exact_string(value: object, candidate: str) -> bool:
    if isinstance(value, str):
        return hmac.compare_digest(value.encode("utf-8"), candidate.encode("utf-8"))
    if isinstance(value, dict):
        return any(
            _contains_exact_string(key, candidate)
            or _contains_exact_string(item, candidate)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_exact_string(item, candidate) for item in value)
    return False


def normalize_scopes(value: object, pointer: str = "/scopes") -> dict[str, object]:
    scopes = _expect_object(value, pointer)
    _expect_exact_fields(scopes, frozenset(_SCOPE_FIELDS), pointer)
    normalized: dict[str, object] = {}
    for field in _SCOPE_FIELDS:
        normalized[field] = _expect_sorted_unique_strings(
            scopes[field],
            f"{pointer}/{field}",
            identifiers=field != "paths",
            paths=field == "paths",
        )
    return normalized


def _scopes_nonempty(scopes: Mapping[str, object]) -> bool:
    return any(bool(scopes[field]) for field in _SCOPE_FIELDS)


def scopes_overlap(first: object, second: object) -> bool:
    left = normalize_scopes(first, "/first_scopes")
    right = normalize_scopes(second, "/second_scopes")
    for field in _SCOPE_FIELDS:
        if field == "paths":
            continue
        if set(left[field]) & set(right[field]):  # type: ignore[arg-type]
            return True
    for left_path in left["paths"]:  # type: ignore[union-attr]
        for right_path in right["paths"]:  # type: ignore[union-attr]
            if _paths_overlap(left_path, right_path):
                return True
    return False


def scopes_subset(child: object, parent: object) -> bool:
    child_scopes = normalize_scopes(child, "/child_scopes")
    parent_scopes = normalize_scopes(parent, "/parent_scopes")
    for field in _SCOPE_FIELDS:
        if field == "paths":
            continue
        if not set(child_scopes[field]).issubset(  # type: ignore[arg-type]
            set(parent_scopes[field])  # type: ignore[arg-type]
        ):
            return False
    for child_path in child_scopes["paths"]:  # type: ignore[union-attr]
        if not any(
            _path_contains(parent_path, child_path)
            for parent_path in parent_scopes["paths"]  # type: ignore[union-attr]
        ):
            return False
    return True


def normalize_lock_claims(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise _error(
            "ACTION_JOURNAL_LOCK_ORDER_INVALID",
            "lock claims must be an array",
        )
    result: list[dict[str, str]] = []
    previous_key: tuple[int, bytes] | None = None
    seen: set[tuple[str, str]] = set()
    for position, item in enumerate(value):
        claim = _expect_object(item, f"/lock_claims/{position}")
        _expect_exact_fields(
            claim, frozenset({"kind", "identity"}), f"/lock_claims/{position}"
        )
        kind = _expect_choice(
            claim["kind"],
            frozenset(ACTION_EXECUTION_LOCK_ORDER),
            f"/lock_claims/{position}/kind",
        )
        identity = _expect_string(
            claim["identity"],
            f"/lock_claims/{position}/identity",
            identifier=True,
        )
        key = (ACTION_EXECUTION_LOCK_ORDER.index(kind), identity.encode("utf-8"))
        if previous_key is not None and key <= previous_key:
            raise _error(
                "ACTION_JOURNAL_LOCK_ORDER_INVALID",
                "locks must follow task/repository/worktree/lease/registry order and UTF-8 identity order",
            )
        if (kind, identity) in seen:
            raise _error(
                "ACTION_JOURNAL_LOCK_ORDER_INVALID",
                "lock claims must be unique",
            )
        previous_key = key
        seen.add((kind, identity))
        result.append({"kind": kind, "identity": identity})
    return result


def required_lock_claims(
    journal: object,
    *,
    registry_ids: Sequence[str] = (),
) -> list[dict[str, str]]:
    normalized = normalize_journal(journal)
    scopes = normalized["bindings"]["scopes"]  # type: ignore[index]
    assert isinstance(scopes, dict)
    claims: list[dict[str, str]] = [
        {"kind": "task", "identity": str(normalized["task_id"])}
    ]
    for kind, scope_field in (
        ("repository", "repository_ids"),
        ("worktree", "worktree_ids"),
        ("lease", "lease_ids"),
    ):
        for identity in scopes[scope_field]:
            claims.append({"kind": kind, "identity": str(identity)})
    normalized_registry_ids = sorted(
        {
            _expect_string(
                identity, "/registry_ids", identifier=True
            )
            for identity in registry_ids
        },
        key=lambda item: item.encode("utf-8"),
    )
    for identity in normalized_registry_ids:
        claims.append({"kind": "registry", "identity": identity})
    return normalize_lock_claims(claims)


def _paths_overlap(first: str, second: str) -> bool:
    return _path_contains(first, second) or _path_contains(second, first)


def _path_contains(parent: str, child: str) -> bool:
    if parent == "/":
        return child.startswith("/")
    return child == parent or child.startswith(parent + "/")


def _core_bytes(record: Mapping[str, object], excluded: frozenset[str]) -> bytes:
    core = {key: value for key, value in record.items() if key not in excluded}
    return semantic_json_bytes(core)


def _record_digest(
    record: Mapping[str, object],
    domain: bytes,
    excluded: frozenset[str],
) -> str:
    core_bytes = _core_bytes(record, excluded)
    return hashlib.sha256(
        domain + u64be(len(core_bytes)) + core_bytes
    ).hexdigest()


def _strict_secret_bytes(manager_secret: str | bytes) -> bytes:
    if isinstance(manager_secret, str):
        try:
            encoded = manager_secret.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _error(
                "ACTION_JOURNAL_MANAGER_SECRET_INVALID",
                "manager secret must be valid UTF-8",
            ) from exc
        if not encoded:
            raise _error(
                "ACTION_JOURNAL_MANAGER_SECRET_INVALID",
                "manager secret must not be empty",
            )
        return encoded
    if isinstance(manager_secret, bytes):
        try:
            manager_secret.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _error(
                "ACTION_JOURNAL_MANAGER_SECRET_INVALID",
                "manager secret bytes must be valid UTF-8",
            ) from exc
        if not manager_secret:
            raise _error(
                "ACTION_JOURNAL_MANAGER_SECRET_INVALID",
                "manager secret must not be empty",
            )
        return manager_secret
    raise _error(
        "ACTION_JOURNAL_MANAGER_SECRET_INVALID",
        "manager secret must be a string or UTF-8 bytes",
    )


def derive_execution_key(
    manager_secret: str | bytes,
    task_id: str,
    execution_id: str,
) -> bytes:
    secret_bytes = _strict_secret_bytes(manager_secret)
    task_bytes = _expect_string(
        task_id, "/task_id", identifier=True
    ).encode("utf-8")
    execution_bytes = _expect_path_component(
        execution_id, "/execution_id"
    ).encode("utf-8")
    return hmac.new(
        secret_bytes,
        JOURNAL_KEY_DOMAIN
        + u64be(len(task_bytes))
        + task_bytes
        + u64be(len(execution_bytes))
        + execution_bytes,
        hashlib.sha256,
    ).digest()


def journal_record_sha256(record: Mapping[str, object]) -> str:
    return _record_digest(
        record,
        JOURNAL_RECORD_DOMAIN,
        frozenset({"record_sha256", "seal"}),
    )


def index_record_sha256(record: Mapping[str, object]) -> str:
    return _record_digest(
        record,
        INDEX_RECORD_DOMAIN,
        frozenset({"record_sha256"}),
    )


def journal_seal(
    record: Mapping[str, object],
    manager_secret: str | bytes,
) -> str:
    task_id = _expect_string(record.get("task_id"), "/task_id", identifier=True)
    execution_id = _expect_path_component(
        record.get("execution_id"), "/execution_id"
    )
    core_bytes = _core_bytes(
        record, frozenset({"record_sha256", "seal"})
    )
    execution_key = derive_execution_key(
        manager_secret, task_id, execution_id
    )
    return hmac.new(
        execution_key,
        JOURNAL_SEAL_DOMAIN + u64be(len(core_bytes)) + core_bytes,
        hashlib.sha256,
    ).hexdigest()


def engine_proof_mac(private_key: bytes, payload: object) -> str:
    """Compute the normative MAC primitive, not a registered commit proof.

    The transition engine must separately own its process-private key and
    one-shot issuance registry.  A string returned here grants no mutation or
    dispatch authority.
    """

    if not isinstance(private_key, bytes) or not private_key:
        raise _error(
            "ACTION_JOURNAL_PROOF_KEY_INVALID",
            "engine proof key must be non-empty bytes",
        )
    core_bytes = semantic_json_bytes(payload)
    return hmac.new(
        private_key,
        ENGINE_PROOF_DOMAIN + u64be(len(core_bytes)) + core_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_engine_proof_mac(
    private_key: bytes,
    payload: object,
    candidate_mac: str,
) -> bool:
    if not isinstance(candidate_mac, str) or not _SHA256_RE.fullmatch(
        candidate_mac
    ):
        return False
    return hmac.compare_digest(
        engine_proof_mac(private_key, payload), candidate_mac
    )


def _seal_unsealed_record(
    core: Mapping[str, object],
    *,
    domain: bytes,
) -> dict[str, object]:
    normalized = _expect_object(dict(core), "/")
    if "record_sha256" in normalized:
        raise _error(
            "ACTION_JOURNAL_SELF_DIGEST_FORBIDDEN",
            "unsealed core must not include its own digest",
        )
    sealed = dict(normalized)
    sealed["record_sha256"] = _record_digest(
        sealed, domain, frozenset({"record_sha256"})
    )
    return sealed


def seal_index(core: Mapping[str, object]) -> dict[str, object]:
    if "record_sha256" in core:
        raise _error(
            "ACTION_JOURNAL_SELF_DIGEST_FORBIDDEN",
            "index core must not include record_sha256",
        )
    sealed = dict(_expect_object(dict(core), "/"))
    sealed["record_sha256"] = index_record_sha256(sealed)
    return normalize_index(sealed)


def seal_journal(
    core: Mapping[str, object],
    *,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    if "record_sha256" in core or "seal" in core:
        raise _error(
            "ACTION_JOURNAL_SELF_DIGEST_FORBIDDEN",
            "journal core must not include record_sha256 or seal",
        )
    unsealed = dict(_expect_object(dict(core), "/"))
    bindings = _expect_object(unsealed.get("bindings"), "/bindings")
    authorization_kind = bindings.get("authorization_kind")
    if authorization_kind == "manager":
        if manager_secret is None:
            raise _error(
                "ACTION_JOURNAL_MANAGER_SECRET_REQUIRED",
                "manager-authorized journal requires the secret channel value",
            )
        secret_text = _strict_secret_bytes(manager_secret).decode("utf-8")
        if _contains_exact_string(unsealed, secret_text):
            raise _error(
                "ACTION_JOURNAL_RAW_SECRET_FORBIDDEN",
                "manager secret must never be serialized in journal content",
            )
    elif manager_secret is not None:
        raise _error(
            "ACTION_JOURNAL_MANAGER_SECRET_UNEXPECTED",
            "operator-authorized journal must not receive a manager secret",
        )
    unsealed["record_sha256"] = journal_record_sha256(unsealed)
    unsealed["seal"] = (
        journal_seal(unsealed, manager_secret)
        if manager_secret is not None
        else None
    )
    sealed = normalize_journal(unsealed)
    if manager_secret is not None and not verify_journal_seal(
        sealed, manager_secret
    ):
        raise AssertionError("newly sealed journal did not verify")
    return sealed


def _reseal_journal(
    record: Mapping[str, object],
    *,
    manager_secret: str | bytes | None,
) -> dict[str, object]:
    core = {
        key: value
        for key, value in record.items()
        if key not in {"record_sha256", "seal"}
    }
    return seal_journal(core, manager_secret=manager_secret)


def _reseal_index(record: Mapping[str, object]) -> dict[str, object]:
    return seal_index(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _normalize_bindings(value: object) -> dict[str, object]:
    bindings = _expect_object(value, "/bindings")
    _expect_exact_fields(bindings, _BINDING_FIELDS, "/bindings")
    result: dict[str, object] = {
        "task_revision": _expect_revision(
            bindings["task_revision"], "/bindings/task_revision"
        ),
        "pre_effect_state_sha256": _expect_sha256(
            bindings["pre_effect_state_sha256"],
            "/bindings/pre_effect_state_sha256",
        ),
        "workflow_id": _expect_string(
            bindings["workflow_id"],
            "/bindings/workflow_id",
            identifier=True,
        ),
        "workflow_version": _expect_string(
            bindings["workflow_version"],
            "/bindings/workflow_version",
            identifier=True,
        ),
        "workflow_bundle_sha256": _expect_sha256(
            bindings["workflow_bundle_sha256"],
            "/bindings/workflow_bundle_sha256",
        ),
        "action_edge_id": _expect_string(
            bindings["action_edge_id"],
            "/bindings/action_edge_id",
            identifier=True,
        ),
        "authorization_action_edge_id": _expect_string(
            bindings["authorization_action_edge_id"],
            "/bindings/authorization_action_edge_id",
            identifier=True,
        ),
        "completion_edge_id": _expect_string(
            bindings["completion_edge_id"],
            "/bindings/completion_edge_id",
            identifier=True,
        ),
        "handler_id": _expect_string(
            bindings["handler_id"],
            "/bindings/handler_id",
            identifier=True,
        ),
        "effect_plan_sha256": _expect_sha256(
            bindings["effect_plan_sha256"],
            "/bindings/effect_plan_sha256",
        ),
        "concurrency_class": _expect_choice(
            bindings["concurrency_class"],
            frozenset({"exclusive-task", "scoped"}),
            "/bindings/concurrency_class",
        ),
        "scopes": normalize_scopes(bindings["scopes"], "/bindings/scopes"),
        "authorized_paths": _expect_sorted_unique_strings(
            bindings["authorized_paths"],
            "/bindings/authorized_paths",
            paths=True,
        ),
        "confirmation_sha256": _expect_sha256(
            bindings["confirmation_sha256"],
            "/bindings/confirmation_sha256",
        ),
        "operation_sha256": _expect_sha256(
            bindings["operation_sha256"], "/bindings/operation_sha256"
        ),
        "semantic_operation_sha256": _expect_sha256(
            bindings["semantic_operation_sha256"],
            "/bindings/semantic_operation_sha256",
        ),
        "authorization_kind": _expect_choice(
            bindings["authorization_kind"],
            frozenset({"manager", "operator"}),
            "/bindings/authorization_kind",
        ),
        "authorization_sha256": _expect_sha256(
            bindings["authorization_sha256"],
            "/bindings/authorization_sha256",
        ),
        "capability_sha256": _expect_sha256(
            bindings["capability_sha256"],
            "/bindings/capability_sha256",
            nullable=True,
        ),
        "request_sha256": _expect_sha256(
            bindings["request_sha256"], "/bindings/request_sha256"
        ),
        "request_nonce_sha256": _expect_sha256(
            bindings["request_nonce_sha256"],
            "/bindings/request_nonce_sha256",
        ),
        "principal": _expect_string(
            bindings["principal"], "/bindings/principal"
        ),
        "guard_projection_sha256": _expect_sha256(
            bindings["guard_projection_sha256"],
            "/bindings/guard_projection_sha256",
        ),
        "evidence_sha256": _expect_sha256(
            bindings["evidence_sha256"], "/bindings/evidence_sha256"
        ),
        "approval_sha256": _expect_sha256(
            bindings["approval_sha256"], "/bindings/approval_sha256"
        ),
        "ownership_sha256": _expect_sha256(
            bindings["ownership_sha256"], "/bindings/ownership_sha256"
        ),
        "registry_state_sha256": _expect_sha256(
            bindings["registry_state_sha256"],
            "/bindings/registry_state_sha256",
        ),
        "postcondition_contract_sha256": _expect_sha256(
            bindings["postcondition_contract_sha256"],
            "/bindings/postcondition_contract_sha256",
        ),
        "verifier_before_sha256": _expect_sha256(
            bindings["verifier_before_sha256"],
            "/bindings/verifier_before_sha256",
        ),
        "candidate_after_sha256": _expect_sha256(
            bindings["candidate_after_sha256"],
            "/bindings/candidate_after_sha256",
        ),
        "revision_policy": _expect_choice(
            bindings["revision_policy"],
            frozenset({"exact-revision", "disjoint-scope-revalidate"}),
            "/bindings/revision_policy",
        ),
    }
    if result["action_edge_id"] != result["completion_edge_id"]:
        raise _error(
            "ACTION_JOURNAL_EDGE_ROLE_ALIAS_INVALID",
            "action_edge_id must equal completion_edge_id",
        )
    if (
        result["authorization_kind"] == "manager"
        and result["capability_sha256"] is None
    ):
        raise _error(
            "ACTION_JOURNAL_CAPABILITY_BINDING_REQUIRED",
            "manager authorization must bind its verifier capability digest",
        )
    if (
        result["authorization_kind"] == "operator"
        and result["capability_sha256"] is not None
    ):
        raise _error(
            "ACTION_JOURNAL_CAPABILITY_BINDING_FORBIDDEN",
            "operator authorization cannot claim a manager capability",
        )
    if (
        result["concurrency_class"] == "scoped"
        and not _scopes_nonempty(result["scopes"])  # type: ignore[arg-type]
    ):
        raise _error(
            "ACTION_JOURNAL_SCOPE_REQUIRED",
            "scoped execution must bind at least one canonical scope",
        )
    declared_paths = result["scopes"]["paths"]  # type: ignore[index]
    for authorized_path in result["authorized_paths"]:  # type: ignore[union-attr]
        if not any(
            _path_contains(scope_path, authorized_path)
            for scope_path in declared_paths
        ):
            raise _error(
                "ACTION_JOURNAL_AUTHORIZED_PATH_WIDENED",
                "authorized path must be contained by a canonical path scope",
                details={"path": authorized_path},
            )
    return result


def _normalize_effect(value: object, pointer: str) -> dict[str, object]:
    effect = _expect_object(value, pointer)
    _expect_exact_fields(effect, _EFFECT_FIELDS, pointer)
    safe_inputs = _expect_object(effect["safe_inputs"], f"{pointer}/safe_inputs")
    _reject_secret_fields(safe_inputs, f"{pointer}/safe_inputs")
    safe_input_sha256 = _expect_sha256(
        effect["safe_input_sha256"], f"{pointer}/safe_input_sha256"
    )
    expected_safe_digest = semantic_sha256(SAFE_INPUT_DOMAIN, safe_inputs)
    if not hmac.compare_digest(safe_input_sha256, expected_safe_digest):
        raise _error(
            "ACTION_JOURNAL_SAFE_INPUT_DIGEST_MISMATCH",
            "safe effect input digest does not match canonical inputs",
            details={"pointer": pointer},
        )
    settlement = _expect_choice(
        effect["settlement"], _SETTLEMENTS, f"{pointer}/settlement"
    )
    kind = _expect_choice(effect["kind"], _EFFECT_KINDS, f"{pointer}/kind")
    if settlement == "asynchronous-handoff" and kind != "runtime-dispatch":
        raise _error(
            "ACTION_JOURNAL_HANDOFF_FORBIDDEN",
            "only package-owned runtime-dispatch effects may hand off",
            details={"pointer": pointer},
        )
    phase = _expect_choice(
        effect["phase"], _EFFECT_PHASES, f"{pointer}/phase"
    )
    settled_as = effect["settled_as"]
    if settled_as is not None:
        settled_as = _expect_choice(
            settled_as,
            frozenset({"QUIESCED", "HANDOFF_VERIFIED"}),
            f"{pointer}/settled_as",
        )
    claim_id = effect["claim_id"]
    if claim_id is not None:
        claim_id = _expect_string(
            claim_id, f"{pointer}/claim_id", identifier=True
        )
    if phase == "PLANNED" and claim_id is not None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_CLAIM_INVALID",
            "planned effect must not already have a claim identity",
            details={"pointer": pointer},
        )
    if phase != "PLANNED" and claim_id is None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_CLAIM_REQUIRED",
            "claimed or later effect phase requires a claim identity",
            details={"pointer": pointer},
        )
    if phase == "HANDOFF_VERIFIED" and settlement != "asynchronous-handoff":
        raise _error(
            "ACTION_JOURNAL_HANDOFF_FORBIDDEN",
            "synchronous effect cannot enter HANDOFF_VERIFIED",
            details={"pointer": pointer},
        )
    if phase in {"QUIESCED", "HANDOFF_VERIFIED", "VERIFIED"}:
        if settled_as is None:
            raise _error(
                "ACTION_JOURNAL_EFFECT_SETTLEMENT_REQUIRED",
                "settled effect phase must preserve its exact settlement branch",
                details={"pointer": pointer},
            )
        if phase in {"QUIESCED", "HANDOFF_VERIFIED"} and settled_as != phase:
            raise _error(
                "ACTION_JOURNAL_EFFECT_SETTLEMENT_INVALID",
                "effect phase and settlement branch disagree",
                details={"pointer": pointer},
            )
    elif phase != "QUARANTINED" and settled_as is not None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_SETTLEMENT_INVALID",
            "unsettled effect phase cannot declare a settlement branch",
            details={"pointer": pointer},
        )
    if settled_as == "HANDOFF_VERIFIED" and settlement != "asynchronous-handoff":
        raise _error(
            "ACTION_JOURNAL_HANDOFF_FORBIDDEN",
            "synchronous effect cannot preserve a handoff settlement",
            details={"pointer": pointer},
        )
    receipt_sha256 = _expect_sha256(
        effect["receipt_sha256"],
        f"{pointer}/receipt_sha256",
        nullable=True,
    )
    if phase == "VERIFIED" and receipt_sha256 is None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_RECEIPT_REQUIRED",
            "verified effect must bind a typed receipt digest",
            details={"pointer": pointer},
        )
    containment_sha256 = _expect_sha256(
        effect["containment_record_sha256"],
        f"{pointer}/containment_record_sha256",
        nullable=True,
    )
    runtime_binding_sha256 = _expect_sha256(
        effect["runtime_binding_sha256"],
        f"{pointer}/runtime_binding_sha256",
        nullable=True,
    )
    if phase in {
        "RUNNING",
        "QUIESCED",
        "HANDOFF_VERIFIED",
        "VERIFIED",
    } and containment_sha256 is None:
        raise _error(
            "ACTION_JOURNAL_CONTAINMENT_REQUIRED",
            "started effect phase must bind its containment record",
            details={"pointer": pointer},
        )
    if (
        settled_as == "HANDOFF_VERIFIED"
        and runtime_binding_sha256 is None
    ):
        raise _error(
            "ACTION_JOURNAL_RUNTIME_BINDING_REQUIRED",
            "handoff settlement must preserve an authenticated runtime binding",
            details={"pointer": pointer},
        )
    parallel_group = effect["parallel_group"]
    if parallel_group is not None:
        parallel_group = _expect_string(
            parallel_group, f"{pointer}/parallel_group", identifier=True
        )
    normalized_scopes = normalize_scopes(
        effect["scopes"], f"{pointer}/scopes"
    )
    if not _scopes_nonempty(normalized_scopes):
        raise _error(
            "ACTION_JOURNAL_SCOPE_REQUIRED",
            "every effect must bind at least one canonical scope",
            details={"pointer": pointer},
        )
    return {
        "effect_id": _expect_path_component(
            effect["effect_id"], f"{pointer}/effect_id"
        ),
        "kind": kind,
        "settlement": settlement,
        "scopes": normalized_scopes,
        "safe_inputs": safe_inputs,
        "safe_input_sha256": safe_input_sha256,
        "idempotency_key_sha256": _expect_sha256(
            effect["idempotency_key_sha256"],
            f"{pointer}/idempotency_key_sha256",
        ),
        "predecessors": _expect_sorted_unique_strings(
            effect["predecessors"],
            f"{pointer}/predecessors",
            identifiers=True,
        ),
        "parallel_group": parallel_group,
        "attempt_id": _expect_path_component(
            effect["attempt_id"], f"{pointer}/attempt_id"
        ),
        "phase": phase,
        "settled_as": settled_as,
        "claim_id": claim_id,
        "containment_record_sha256": containment_sha256,
        "runtime_binding_sha256": runtime_binding_sha256,
        "receipt_sha256": receipt_sha256,
    }


def _validate_effect_graph(
    effects: Sequence[Mapping[str, object]],
    journal_scopes: Mapping[str, object],
) -> None:
    ids = [str(effect["effect_id"]) for effect in effects]
    canonical = sorted(set(ids), key=lambda item: item.encode("utf-8"))
    if ids != canonical or len(ids) != len(canonical):
        raise _error(
            "ACTION_JOURNAL_EFFECT_ORDER_INVALID",
            "effects must have unique identities sorted by NFC UTF-8 bytes",
        )
    known = set(ids)
    graph: dict[str, list[str]] = {}
    for effect in effects:
        effect_id = str(effect["effect_id"])
        predecessors = list(effect["predecessors"])  # type: ignore[arg-type]
        if effect_id in predecessors or not set(predecessors).issubset(known):
            raise _error(
                "ACTION_JOURNAL_EFFECT_DEPENDENCY_INVALID",
                "effect predecessors must be known and cannot include self",
                details={"effect_id": effect_id},
            )
        if not scopes_subset(effect["scopes"], journal_scopes):
            raise _error(
                "ACTION_JOURNAL_EFFECT_SCOPE_WIDENED",
                "effect scope must be contained by the sealed action scope",
                details={"effect_id": effect_id},
            )
        graph[effect_id] = predecessors
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(effect_id: str) -> None:
        if effect_id in visited:
            return
        if effect_id in visiting:
            raise _error(
                "ACTION_JOURNAL_EFFECT_DEPENDENCY_CYCLE",
                "effect dependency graph must be acyclic",
                details={"effect_id": effect_id},
            )
        visiting.add(effect_id)
        for predecessor in graph[effect_id]:
            visit(predecessor)
        visiting.remove(effect_id)
        visited.add(effect_id)

    for effect_id in ids:
        visit(effect_id)


def _normalize_receipt(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    receipt = _expect_object(value, "/receipt")
    _expect_exact_fields(receipt, _RECEIPT_FIELDS, "/receipt")
    return {
        "receipt_sha256": _expect_sha256(
            receipt["receipt_sha256"], "/receipt/receipt_sha256"
        ),
        "candidate_state_sha256": _expect_sha256(
            receipt["candidate_state_sha256"],
            "/receipt/candidate_state_sha256",
        ),
        "event_batch_sha256": _expect_sha256(
            receipt["event_batch_sha256"],
            "/receipt/event_batch_sha256",
        ),
        "engine_proof_sha256": _expect_sha256(
            receipt["engine_proof_sha256"],
            "/receipt/engine_proof_sha256",
        ),
        "authorization_action_edge_id": _expect_string(
            receipt["authorization_action_edge_id"],
            "/receipt/authorization_action_edge_id",
            identifier=True,
        ),
        "completion_edge_id": _expect_string(
            receipt["completion_edge_id"],
            "/receipt/completion_edge_id",
            identifier=True,
        ),
    }


def _normalize_quarantine(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    quarantine = _expect_object(value, "/quarantine")
    _expect_exact_fields(quarantine, _QUARANTINE_FIELDS, "/quarantine")
    return {
        "reason_code": _expect_string(
            quarantine["reason_code"], "/quarantine/reason_code", identifier=True
        ),
        "effect_id": (
            None
            if quarantine["effect_id"] is None
            else _expect_path_component(
                quarantine["effect_id"], "/quarantine/effect_id"
            )
        ),
        "receipt_sha256": _expect_sha256(
            quarantine["receipt_sha256"],
            "/quarantine/receipt_sha256",
            nullable=True,
        ),
        "details_sha256": _expect_sha256(
            quarantine["details_sha256"],
            "/quarantine/details_sha256",
        ),
    }


def _normalize_finalization(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    finalization = _expect_object(value, "/finalization")
    _expect_exact_fields(finalization, _FINALIZATION_FIELDS, "/finalization")
    return {
        "task_commit_revision": _expect_revision(
            finalization["task_commit_revision"],
            "/finalization/task_commit_revision",
        ),
        "task_state_sha256": _expect_sha256(
            finalization["task_state_sha256"],
            "/finalization/task_state_sha256",
        ),
        "event_sha256": _expect_sha256(
            finalization["event_sha256"], "/finalization/event_sha256"
        ),
        "outbox_sha256": _expect_sha256(
            finalization["outbox_sha256"], "/finalization/outbox_sha256"
        ),
        "nonce_consumed": _expect_bool(
            finalization["nonce_consumed"], "/finalization/nonce_consumed"
        ),
    }


def _validate_global_phase(
    phase: str,
    effects: Sequence[Mapping[str, object]],
) -> None:
    effect_phases = [str(effect["phase"]) for effect in effects]
    if phase == "PREPARED" and any(
        effect_phase != "PLANNED" for effect_phase in effect_phases
    ):
        raise _error(
            "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
            "PREPARED journal may contain only unclaimed effects",
        )
    if phase == "DISPATCH_CLAIMED":
        if "CLAIMED" not in effect_phases or any(
            effect_phase
            not in {"PLANNED", "CLAIMED"}
            for effect_phase in effect_phases
        ):
            raise _error(
                "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
                "DISPATCH_CLAIMED must preserve at least one fresh claim",
            )
    if phase == "RUNNING":
        if all(effect_phase == "PLANNED" for effect_phase in effect_phases):
            raise _error(
                "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
                "RUNNING requires at least one started effect",
            )
    if phase in {"QUIESCED", "HANDOFF_VERIFIED"}:
        if any(
            effect_phase not in {"QUIESCED", "HANDOFF_VERIFIED", "VERIFIED"}
            for effect_phase in effect_phases
        ):
            raise _error(
                "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
                "global settlement requires every effect to be settled",
            )
        any_handoff = any(
            effect["settled_as"] == "HANDOFF_VERIFIED"
            for effect in effects
        )
        if (phase == "HANDOFF_VERIFIED") != any_handoff:
            raise _error(
                "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
                "global settlement branch must preserve effect handoff history",
            )
    if phase in {"RECEIPT_VERIFIED", "COMMITTED"} and any(
        effect_phase != "VERIFIED" for effect_phase in effect_phases
    ):
        raise _error(
            "ACTION_JOURNAL_GLOBAL_PHASE_INVALID",
            "receipt and commit phases require every effect to be verified",
        )


def normalize_journal(value: object) -> dict[str, object]:
    journal = _expect_object(value, "/")
    _expect_exact_fields(journal, _JOURNAL_FIELDS, "/")
    _reject_secret_fields(journal)
    if journal["schema"] != ACTION_EXECUTION_JOURNAL_SCHEMA:
        raise _error(
            "ACTION_JOURNAL_SCHEMA_INVALID",
            "journal schema is not supported",
        )
    bindings = _normalize_bindings(journal["bindings"])
    if not isinstance(journal["effects"], list) or not journal["effects"]:
        raise _error(
            "ACTION_JOURNAL_EFFECTS_INVALID",
            "journal must contain at least one declared effect",
        )
    effects = [
        _normalize_effect(effect, f"/effects/{index}")
        for index, effect in enumerate(journal["effects"])
    ]
    _validate_effect_graph(effects, bindings["scopes"])  # type: ignore[arg-type]
    phase = _expect_choice(journal["phase"], _JOURNAL_PHASES, "/phase")
    _validate_global_phase(phase, effects)
    receipt = _normalize_receipt(journal["receipt"])
    quarantine = _normalize_quarantine(journal["quarantine"])
    finalization = _normalize_finalization(journal["finalization"])
    if phase == "QUARANTINED":
        if quarantine is None:
            raise _error(
                "ACTION_JOURNAL_QUARANTINE_REQUIRED",
                "quarantined journal must preserve quarantine evidence",
            )
    elif quarantine is not None:
        raise _error(
            "ACTION_JOURNAL_QUARANTINE_INVALID",
            "non-quarantined journal cannot contain quarantine evidence",
        )
    if phase in {"RECEIPT_VERIFIED", "COMMITTED"} and receipt is None:
        raise _error(
            "ACTION_JOURNAL_RECEIPT_REQUIRED",
            "receipt-time phases must bind receipt and commit-intent digests",
        )
    if phase == "COMMITTED" and finalization is None:
        raise _error(
            "ACTION_JOURNAL_FINALIZATION_REQUIRED",
            "committed journal must bind the authoritative task transaction",
        )
    if phase != "COMMITTED" and finalization is not None:
        raise _error(
            "ACTION_JOURNAL_FINALIZATION_INVALID",
            "only a committed journal may contain finalization facts",
        )
    reconciliation_attempt_ids = _expect_sorted_unique_strings(
        journal["reconciliation_attempt_ids"],
        "/reconciliation_attempt_ids",
        identifiers=True,
    )
    for position, attempt_id in enumerate(reconciliation_attempt_ids):
        _expect_path_component(
            attempt_id, f"/reconciliation_attempt_ids/{position}"
        )
    result: dict[str, object] = {
        "schema": ACTION_EXECUTION_JOURNAL_SCHEMA,
        "task_id": _expect_string(
            journal["task_id"], "/task_id", identifier=True
        ),
        "execution_id": _expect_path_component(
            journal["execution_id"], "/execution_id"
        ),
        "revision": _expect_revision(journal["revision"], "/revision"),
        "phase": phase,
        "bindings": bindings,
        "effects": effects,
        "receipt": receipt,
        "quarantine": quarantine,
        "reconciliation_attempt_ids": reconciliation_attempt_ids,
        "finalization": finalization,
        "record_sha256": _expect_sha256(
            journal["record_sha256"], "/record_sha256"
        ),
        "seal": _expect_sha256(journal["seal"], "/seal", nullable=True),
    }
    if bindings["authorization_kind"] == "manager":
        if result["seal"] is None:
            raise _error(
                "ACTION_JOURNAL_SEAL_REQUIRED",
                "manager-authorized journal requires a durable seal",
            )
    elif result["seal"] is not None:
        raise _error(
            "ACTION_JOURNAL_SEAL_FORBIDDEN",
            "operator-authorized journal must not contain a manager seal",
        )
    expected_digest = journal_record_sha256(result)
    assert isinstance(result["record_sha256"], str)
    if not hmac.compare_digest(result["record_sha256"], expected_digest):
        raise _error(
            "ACTION_JOURNAL_RECORD_DIGEST_MISMATCH",
            "journal record digest does not match canonical core bytes",
        )
    return result


def verify_journal_seal(
    journal: object,
    manager_secret: str | bytes,
    *,
    expected_task_id: str | None = None,
    expected_execution_id: str | None = None,
) -> bool:
    try:
        normalized = normalize_journal(journal)
        if normalized["bindings"]["authorization_kind"] != "manager":  # type: ignore[index]
            return False
        if (
            expected_task_id is not None
            and normalized["task_id"] != expected_task_id
        ):
            return False
        if (
            expected_execution_id is not None
            and normalized["execution_id"] != expected_execution_id
        ):
            return False
        expected = journal_seal(normalized, manager_secret)
        candidate = normalized["seal"]
        return isinstance(candidate, str) and hmac.compare_digest(
            candidate, expected
        )
    except ActionExecutionJournalError:
        return False


def _require_journal_authenticity(
    normalized_journal: Mapping[str, object],
    manager_secret: str | bytes | None,
) -> None:
    bindings = normalized_journal["bindings"]
    assert isinstance(bindings, dict)
    if bindings["authorization_kind"] == "manager":
        if manager_secret is None or not verify_journal_seal(
            normalized_journal,
            manager_secret,
            expected_task_id=str(normalized_journal["task_id"]),
            expected_execution_id=str(normalized_journal["execution_id"]),
        ):
            raise _error(
                "ACTION_JOURNAL_REAUTHENTICATION_REQUIRED",
                "manager-authorized journal requires its current secret-channel seal",
            )
    elif manager_secret is not None:
        raise _error(
            "ACTION_JOURNAL_MANAGER_SECRET_UNEXPECTED",
            "operator-authorized journal must not receive a manager secret",
        )


def _normalize_runtime_reservation_embedded(
    value: object,
) -> dict[str, object] | None:
    if value is None:
        return None
    return normalize_runtime_reservation(value)


def _normalize_index_entry(value: object, pointer: str) -> dict[str, object]:
    entry = _expect_object(value, pointer)
    _expect_exact_fields(entry, _INDEX_ENTRY_FIELDS, pointer)
    kind = _expect_choice(
        entry["entry_kind"], _INDEX_ENTRY_KINDS, f"{pointer}/entry_kind"
    )
    concurrency_class = _expect_choice(
        entry["concurrency_class"],
        _CONCURRENCY_CLASSES,
        f"{pointer}/concurrency_class",
    )
    target = entry["target_execution_id"]
    if target is not None:
        target = _expect_path_component(
            target, f"{pointer}/target_execution_id"
        )
    control_action = entry["control_action_id"]
    if control_action is not None:
        control_action = _expect_string(
            control_action, f"{pointer}/control_action_id", identifier=True
        )
    pending = _expect_sha256(
        entry["pending_record_sha256"],
        f"{pointer}/pending_record_sha256",
        nullable=True,
    )
    record = _expect_sha256(
        entry["record_sha256"],
        f"{pointer}/record_sha256",
        nullable=True,
    )
    reservation = _normalize_runtime_reservation_embedded(
        entry["runtime_reservation"]
    )
    if kind == "control":
        if (
            concurrency_class != "target-control"
            or target is None
            or control_action is None
            or reservation is not None
        ):
            raise _error(
                "ACTION_JOURNAL_CONTROL_ENTRY_INVALID",
                "control entry must bind one target and exact control action",
                details={"pointer": pointer},
            )
    elif concurrency_class == "target-control":
        raise _error(
            "ACTION_JOURNAL_INDEX_ENTRY_INVALID",
            "only a target-bound control child may use target-control",
            details={"pointer": pointer},
        )
    elif target is not None or control_action is not None:
        raise _error(
            "ACTION_JOURNAL_INDEX_ENTRY_INVALID",
            "ordinary and runtime-reservation entries cannot name control target",
            details={"pointer": pointer},
        )
    if kind == "runtime-reservation":
        if reservation is None or pending is not None or record is not None:
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "runtime reservation entry must contain only its reservation",
                details={"pointer": pointer},
            )
    elif reservation is not None:
        raise _error(
            "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
            "non-reservation index entry cannot embed a runtime reservation",
            details={"pointer": pointer},
        )
    if kind in {"ordinary", "control"} and pending is None and record is None:
        raise _error(
            "ACTION_JOURNAL_INDEX_ENTRY_INVALID",
            "active entry must reserve a pending or promoted journal digest",
            details={"pointer": pointer},
        )
    return {
        "execution_id": _expect_path_component(
            entry["execution_id"], f"{pointer}/execution_id"
        ),
        "entry_kind": kind,
        "target_execution_id": target,
        "control_action_id": control_action,
        "concurrency_class": concurrency_class,
        "scopes": normalize_scopes(entry["scopes"], f"{pointer}/scopes"),
        "pending_record_sha256": pending,
        "record_sha256": record,
        "runtime_reservation": reservation,
    }


def normalize_index(value: object) -> dict[str, object]:
    index = _expect_object(value, "/")
    _expect_exact_fields(index, _INDEX_FIELDS, "/")
    if index["schema"] != ACTION_EXECUTION_INDEX_SCHEMA:
        raise _error(
            "ACTION_JOURNAL_INDEX_SCHEMA_INVALID",
            "action-execution index schema is not supported",
        )
    if not isinstance(index["entries"], list):
        raise _error(
            "ACTION_JOURNAL_FIELD_INVALID",
            "index entries must be an array",
            details={"pointer": "/entries"},
        )
    entries = [
        _normalize_index_entry(entry, f"/entries/{position}")
        for position, entry in enumerate(index["entries"])
    ]
    ids = [str(entry["execution_id"]) for entry in entries]
    canonical = sorted(set(ids), key=lambda item: item.encode("utf-8"))
    if ids != canonical or len(ids) != len(canonical):
        raise _error(
            "ACTION_JOURNAL_INDEX_ORDER_INVALID",
            "index entries must have unique execution identities in UTF-8 order",
        )
    by_id = {str(entry["execution_id"]): entry for entry in entries}
    for entry in entries:
        if entry["entry_kind"] == "control":
            target_id = str(entry["target_execution_id"])
            target = by_id.get(target_id)
            if target is None:
                raise _error(
                    "ACTION_JOURNAL_CONTROL_TARGET_MISSING",
                    "control child target must be active in the same index",
                    details={"execution_id": entry["execution_id"]},
                )
            if not scopes_subset(entry["scopes"], target["scopes"]):
                raise _error(
                    "ACTION_JOURNAL_CONTROL_SCOPE_WIDENED",
                    "control child cannot widen its target scope",
                    details={"execution_id": entry["execution_id"]},
                )
        if entry["entry_kind"] == "runtime-reservation":
            reservation = entry["runtime_reservation"]
            assert isinstance(reservation, dict)
            if (
                reservation["task_id"] != index["task_id"]
                or reservation["execution_id"] != entry["execution_id"]
                or semantic_json_bytes(reservation["scopes"])
                != semantic_json_bytes(entry["scopes"])
            ):
                raise _error(
                    "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                    "embedded reservation must bind index task, execution, and scope",
                    details={"execution_id": entry["execution_id"]},
                )
    for left_position, left in enumerate(entries):
        for right in entries[left_position + 1 :]:
            if left["entry_kind"] == "control":
                if (
                    left["target_execution_id"] != right["execution_id"]
                    and scopes_overlap(left["scopes"], right["scopes"])
                ):
                    raise _error(
                        "ACTION_JOURNAL_SCOPE_CONFLICT",
                        "control child overlaps an execution other than its target",
                    )
                continue
            if right["entry_kind"] == "control":
                if (
                    right["target_execution_id"] != left["execution_id"]
                    and scopes_overlap(left["scopes"], right["scopes"])
                ):
                    raise _error(
                        "ACTION_JOURNAL_SCOPE_CONFLICT",
                        "control child overlaps an execution other than its target",
                    )
                continue
            if _ordinary_conflict(
                str(left["concurrency_class"]),
                left["scopes"],  # type: ignore[arg-type]
                right,
            ):
                raise _error(
                    "ACTION_JOURNAL_SCOPE_CONFLICT",
                    "index contains conflicting ordinary execution scopes",
                )
    result: dict[str, object] = {
        "schema": ACTION_EXECUTION_INDEX_SCHEMA,
        "task_id": _expect_string(
            index["task_id"], "/task_id", identifier=True
        ),
        "revision": _expect_revision(index["revision"], "/revision"),
        "entries": entries,
        "record_sha256": _expect_sha256(
            index["record_sha256"], "/record_sha256"
        ),
    }
    expected = index_record_sha256(result)
    assert isinstance(result["record_sha256"], str)
    if not hmac.compare_digest(result["record_sha256"], expected):
        raise _error(
            "ACTION_JOURNAL_INDEX_DIGEST_MISMATCH",
            "index digest does not match canonical core bytes",
        )
    return result


def new_index(task_id: str) -> dict[str, object]:
    return seal_index(
        {
            "schema": ACTION_EXECUTION_INDEX_SCHEMA,
            "task_id": _expect_string(task_id, "/task_id", identifier=True),
            "revision": 0,
            "entries": [],
        }
    )


def cas_token(record: object) -> CASToken:
    normalized = _expect_object(record, "/")
    return CASToken(
        _expect_revision(normalized.get("revision"), "/revision"),
        _expect_sha256(
            normalized.get("record_sha256"), "/record_sha256"
        ),  # type: ignore[arg-type]
    )


def assert_cas(record: object, expected: CASToken) -> None:
    actual = cas_token(record)
    if actual.revision != expected.revision or not hmac.compare_digest(
        actual.record_sha256, expected.record_sha256
    ):
        raise _error(
            "ACTION_JOURNAL_CAS_CONFLICT",
            "revision or canonical record digest changed",
            details={
                "expected_revision": expected.revision,
                "actual_revision": actual.revision,
            },
        )


def _entries(index: Mapping[str, object]) -> list[dict[str, object]]:
    return [
        dict(entry)
        for entry in index["entries"]  # type: ignore[union-attr]
    ]


def _entry_for(
    index: Mapping[str, object], execution_id: str
) -> dict[str, object] | None:
    for entry in index["entries"]:  # type: ignore[union-attr]
        if entry["execution_id"] == execution_id:
            return dict(entry)
    return None


def _require_promoted_journal(
    index: object,
    journal: Mapping[str, object],
    expected_index: CASToken,
) -> dict[str, object]:
    normalized_index = normalize_index(index)
    assert_cas(normalized_index, expected_index)
    if normalized_index["task_id"] != journal["task_id"]:
        raise _error(
            "ACTION_JOURNAL_TASK_MISMATCH",
            "index and journal must belong to the same task",
        )
    entry = _entry_for(normalized_index, str(journal["execution_id"]))
    if (
        entry is None
        or entry["pending_record_sha256"] is not None
        or not _digest_equal(
            entry["record_sha256"], journal["record_sha256"]
        )
    ):
        raise _error(
            "ACTION_JOURNAL_NOT_PROMOTED",
            "journal must be exactly promoted in the index before claim or containment",
        )
    return normalized_index


def assert_journal_promoted(
    index: object,
    journal: object,
    *,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> None:
    normalized_journal = normalize_journal(journal)
    _require_journal_authenticity(normalized_journal, manager_secret)
    _require_promoted_journal(index, normalized_journal, expected_index)


def _ordinary_conflict(
    requested_class: str,
    requested_scopes: Mapping[str, object],
    existing: Mapping[str, object],
) -> bool:
    existing_class = str(existing["concurrency_class"])
    if (
        requested_class == "exclusive-task"
        or existing_class == "exclusive-task"
    ):
        return True
    return scopes_overlap(requested_scopes, existing["scopes"])


def _validate_new_index_entry_conflicts(
    index: Mapping[str, object],
    entry: Mapping[str, object],
) -> None:
    if entry["entry_kind"] == "control":
        target_id = entry["target_execution_id"]
        target = _entry_for(index, str(target_id))
        if target is None:
            raise _error(
                "ACTION_JOURNAL_CONTROL_TARGET_MISSING",
                "control child target is not active",
            )
        if not scopes_subset(entry["scopes"], target["scopes"]):
            raise _error(
                "ACTION_JOURNAL_CONTROL_SCOPE_WIDENED",
                "control child cannot widen target scope",
            )
        for existing in index["entries"]:  # type: ignore[union-attr]
            if existing["execution_id"] == target_id:
                continue
            if scopes_overlap(entry["scopes"], existing["scopes"]):
                raise _error(
                    "ACTION_JOURNAL_SCOPE_CONFLICT",
                    "control child overlaps an execution other than its target",
                    details={"existing_execution_id": existing["execution_id"]},
                )
        return
    for existing in index["entries"]:  # type: ignore[union-attr]
        if _ordinary_conflict(
            str(entry["concurrency_class"]),
            entry["scopes"],  # type: ignore[arg-type]
            existing,
        ):
            raise _error(
                "ACTION_JOURNAL_SCOPE_CONFLICT",
                "execution conflicts with an active indexed scope",
                details={"existing_execution_id": existing["execution_id"]},
            )


def _journal_entry(
    journal: Mapping[str, object],
    *,
    pending: str | None,
    record: str | None,
    entry_kind: str = "ordinary",
    target_execution_id: str | None = None,
    control_action_id: str | None = None,
) -> dict[str, object]:
    bindings = journal["bindings"]
    assert isinstance(bindings, dict)
    return {
        "execution_id": journal["execution_id"],
        "entry_kind": entry_kind,
        "target_execution_id": target_execution_id,
        "control_action_id": control_action_id,
        "concurrency_class": (
            "target-control"
            if entry_kind == "control"
            else bindings["concurrency_class"]
        ),
        "scopes": bindings["scopes"],
        "pending_record_sha256": pending,
        "record_sha256": record,
        "runtime_reservation": None,
    }


def plan_initial_write(
    index: object,
    journal: object,
    *,
    expected_index: CASToken,
    entry_kind: str = "ordinary",
    target_execution_id: str | None = None,
    control_action_id: str | None = None,
    manager_secret: str | bytes | None = None,
) -> WriteAheadPlan:
    normalized_index = normalize_index(index)
    normalized_journal = normalize_journal(journal)
    _require_journal_authenticity(normalized_journal, manager_secret)
    assert_cas(normalized_index, expected_index)
    if normalized_index["task_id"] != normalized_journal["task_id"]:
        raise _error(
            "ACTION_JOURNAL_TASK_MISMATCH",
            "index and journal must belong to the same task",
        )
    if normalized_journal["phase"] != "PREPARED":
        raise _error(
            "ACTION_JOURNAL_INITIAL_PHASE_INVALID",
            "initial journal must be PREPARED",
        )
    execution_id = str(normalized_journal["execution_id"])
    if _entry_for(normalized_index, execution_id) is not None:
        raise _error(
            "ACTION_JOURNAL_EXECUTION_EXISTS",
            "execution identity is already indexed",
        )
    digest = str(normalized_journal["record_sha256"])
    reserved_entry = _journal_entry(
        normalized_journal,
        pending=digest,
        record=None,
        entry_kind=entry_kind,
        target_execution_id=target_execution_id,
        control_action_id=control_action_id,
    )
    _validate_new_index_entry_conflicts(normalized_index, reserved_entry)
    reserved_entries = _entries(normalized_index) + [reserved_entry]
    reserved_entries.sort(
        key=lambda item: str(item["execution_id"]).encode("utf-8")
    )
    reserved = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": reserved_entries,
        }
    )
    promoted_entries = _entries(reserved)
    for entry in promoted_entries:
        if entry["execution_id"] == execution_id:
            entry["pending_record_sha256"] = None
            entry["record_sha256"] = digest
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return WriteAheadPlan(
        expected_index=expected_index,
        expected_journal=None,
        reserved_index=reserved,
        journal_bytes=semantic_json_bytes(normalized_journal),
        promoted_index=promoted,
        journal_record_sha256=digest,
    )


def plan_journal_update(
    index: object,
    current_journal: object,
    updated_journal: object,
    *,
    expected_index: CASToken,
    expected_journal: CASToken,
    manager_secret: str | bytes | None = None,
) -> WriteAheadPlan:
    normalized_index = normalize_index(index)
    current = normalize_journal(current_journal)
    updated = normalize_journal(updated_journal)
    _require_journal_authenticity(current, manager_secret)
    _require_journal_authenticity(updated, manager_secret)
    assert_cas(normalized_index, expected_index)
    assert_cas(current, expected_journal)
    if (
        current["task_id"] != updated["task_id"]
        or current["execution_id"] != updated["execution_id"]
    ):
        raise _error(
            "ACTION_JOURNAL_IDENTITY_CHANGED",
            "journal update cannot change task or execution identity",
        )
    if int(updated["revision"]) != int(current["revision"]) + 1:
        raise _error(
            "ACTION_JOURNAL_REVISION_STEP_INVALID",
            "journal revision must increase by exactly one",
        )
    _validate_journal_evolution(current, updated)
    entry = _entry_for(normalized_index, str(current["execution_id"]))
    if entry is None:
        raise _error(
            "ACTION_JOURNAL_INDEX_ENTRY_MISSING",
            "journal update requires an active index entry",
        )
    if entry["pending_record_sha256"] is not None:
        raise _error(
            "ACTION_JOURNAL_PENDING_UPDATE",
            "prior pending journal update must be recovered first",
        )
    if not isinstance(entry["record_sha256"], str) or not hmac.compare_digest(
        entry["record_sha256"], str(current["record_sha256"])
    ):
        raise _error(
            "ACTION_JOURNAL_INDEX_RECORD_MISMATCH",
            "index does not point to the expected current journal",
        )
    updated_digest = str(updated["record_sha256"])
    reserved_entries = _entries(normalized_index)
    for candidate in reserved_entries:
        if candidate["execution_id"] == current["execution_id"]:
            candidate["pending_record_sha256"] = updated_digest
    reserved = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": reserved_entries,
        }
    )
    promoted_entries = _entries(reserved)
    for candidate in promoted_entries:
        if candidate["execution_id"] == current["execution_id"]:
            candidate["record_sha256"] = updated_digest
            candidate["pending_record_sha256"] = None
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return WriteAheadPlan(
        expected_index=expected_index,
        expected_journal=expected_journal,
        reserved_index=reserved,
        journal_bytes=semantic_json_bytes(updated),
        promoted_index=promoted,
        journal_record_sha256=updated_digest,
    )


def recover_pending_promotion(
    index: object,
    execution_id: str,
    active_journal_bytes: bytes | None,
    *,
    manager_secret: str | bytes | None = None,
) -> tuple[str, dict[str, object] | None]:
    normalized_index = normalize_index(index)
    entry = _entry_for(
        normalized_index,
        _expect_path_component(execution_id, "/execution_id"),
    )
    if entry is None or entry["pending_record_sha256"] is None:
        raise _error(
            "ACTION_JOURNAL_PENDING_ENTRY_MISSING",
            "execution has no pending journal update",
        )
    if active_journal_bytes is None:
        return "BLOCKED_MISSING_RECORD", None
    parsed = parse_semantic_json(active_journal_bytes)
    try:
        journal = normalize_journal(parsed)
    except ActionExecutionJournalError:
        return "QUARANTINE_MISMATCH", None
    try:
        _require_journal_authenticity(journal, manager_secret)
    except ActionExecutionJournalError:
        return "QUARANTINE_REAUTH_REQUIRED", None
    if (
        journal["task_id"] != normalized_index["task_id"]
        or journal["execution_id"] != execution_id
        or not hmac.compare_digest(
            str(journal["record_sha256"]),
            str(entry["pending_record_sha256"]),
        )
        or semantic_json_bytes(journal) != active_journal_bytes
    ):
        return "QUARANTINE_MISMATCH", None
    entries = _entries(normalized_index)
    for candidate in entries:
        if candidate["execution_id"] == execution_id:
            candidate["record_sha256"] = candidate["pending_record_sha256"]
            candidate["pending_record_sha256"] = None
    promoted = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": entries,
        }
    )
    return "PROMOTE", promoted


def _same_semantic_value(first: object, second: object) -> bool:
    return hmac.compare_digest(
        semantic_json_bytes(first), semantic_json_bytes(second)
    )


def _validate_journal_evolution(
    current: Mapping[str, object],
    updated: Mapping[str, object],
) -> None:
    if not _same_semantic_value(current["bindings"], updated["bindings"]):
        raise _error(
            "ACTION_JOURNAL_IMMUTABLE_BINDING_CHANGED",
            "execution authorization bindings are immutable",
        )
    if (
        current["task_id"] != updated["task_id"]
        or current["execution_id"] != updated["execution_id"]
        or current["schema"] != updated["schema"]
    ):
        raise _error(
            "ACTION_JOURNAL_IDENTITY_CHANGED",
            "journal identity is immutable",
        )
    global_transitions = {
        "PREPARED": frozenset({"DISPATCH_CLAIMED", "QUARANTINED"}),
        "DISPATCH_CLAIMED": frozenset(
            {"DISPATCH_CLAIMED", "RUNNING", "QUARANTINED"}
        ),
        "RUNNING": frozenset(
            {"RUNNING", "QUIESCED", "HANDOFF_VERIFIED", "QUARANTINED"}
        ),
        "QUIESCED": frozenset(
            {"QUIESCED", "RECEIPT_VERIFIED", "QUARANTINED"}
        ),
        "HANDOFF_VERIFIED": frozenset(
            {"HANDOFF_VERIFIED", "RECEIPT_VERIFIED", "QUARANTINED"}
        ),
        "RECEIPT_VERIFIED": frozenset({"COMMITTED", "QUARANTINED"}),
        "COMMITTED": frozenset(),
        "QUARANTINED": frozenset(),
    }
    if updated["phase"] not in global_transitions[str(current["phase"])]:
        raise _error(
            "ACTION_JOURNAL_PHASE_INVALID",
            "global phase transition is not monotonic",
            details={
                "current": current["phase"],
                "updated": updated["phase"],
            },
        )
    current_effects = {
        str(effect["effect_id"]): effect
        for effect in current["effects"]  # type: ignore[union-attr]
    }
    updated_effects = {
        str(effect["effect_id"]): effect
        for effect in updated["effects"]  # type: ignore[union-attr]
    }
    if set(current_effects) != set(updated_effects):
        raise _error(
            "ACTION_JOURNAL_IMMUTABLE_EFFECT_CHANGED",
            "declared effect identities are immutable",
        )
    immutable_effect_fields = frozenset(
        {
            "effect_id",
            "kind",
            "settlement",
            "scopes",
            "safe_inputs",
            "safe_input_sha256",
            "idempotency_key_sha256",
            "predecessors",
            "parallel_group",
            "attempt_id",
        }
    )
    effect_transitions = {
        "PLANNED": frozenset({"PLANNED", "CLAIMED", "QUARANTINED"}),
        "CLAIMED": frozenset({"CLAIMED", "RUNNING", "QUARANTINED"}),
        "RUNNING": frozenset(
            {"RUNNING", "QUIESCED", "HANDOFF_VERIFIED", "QUARANTINED"}
        ),
        "QUIESCED": frozenset({"QUIESCED", "VERIFIED", "QUARANTINED"}),
        "HANDOFF_VERIFIED": frozenset(
            {"HANDOFF_VERIFIED", "VERIFIED", "QUARANTINED"}
        ),
        "VERIFIED": frozenset({"VERIFIED", "QUARANTINED"}),
        "QUARANTINED": frozenset(),
    }
    for effect_id, old_effect in current_effects.items():
        new_effect = updated_effects[effect_id]
        if not _same_semantic_value(
            {
                field: old_effect[field]
                for field in immutable_effect_fields
            },
            {
                field: new_effect[field]
                for field in immutable_effect_fields
            },
        ):
            raise _error(
                "ACTION_JOURNAL_IMMUTABLE_EFFECT_CHANGED",
                "effect plan metadata is immutable",
                details={"effect_id": effect_id},
            )
        if new_effect["phase"] not in effect_transitions[
            str(old_effect["phase"])
        ]:
            raise _error(
                "ACTION_JOURNAL_EFFECT_PHASE_INVALID",
                "effect phase transition is not monotonic",
                details={"effect_id": effect_id},
            )
        for field in (
            "claim_id",
            "settled_as",
            "runtime_binding_sha256",
            "receipt_sha256",
        ):
            old_value = old_effect[field]
            new_value = new_effect[field]
            changed = (
                not _digest_equal(old_value, new_value)
                if field.endswith("_sha256") and old_value is not None
                else old_value != new_value
            )
            if old_value is not None and changed:
                raise _error(
                    "ACTION_JOURNAL_EFFECT_BINDING_CHANGED",
                    "durable effect binding cannot be replaced or cleared",
                    details={"effect_id": effect_id, "field": field},
                )
        if (
            old_effect["containment_record_sha256"] is not None
            and new_effect["containment_record_sha256"] is None
        ):
            raise _error(
                "ACTION_JOURNAL_EFFECT_BINDING_CHANGED",
                "containment link cannot be cleared",
                details={"effect_id": effect_id},
            )
    for field in ("receipt", "quarantine", "finalization"):
        old_value = current[field]
        if old_value is not None and not _same_semantic_value(
            old_value, updated[field]
        ):
            raise _error(
                "ACTION_JOURNAL_TERMINAL_BINDING_CHANGED",
                "receipt, quarantine, and finalization facts are immutable once set",
                details={"field": field},
            )
    if not _same_semantic_value(
        current["reconciliation_attempt_ids"],
        updated["reconciliation_attempt_ids"],
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_LINK_CHANGED",
            "reconciliation attempts are independent immutable control records",
        )
    old_business = {
        key: value
        for key, value in current.items()
        if key not in {"revision", "record_sha256", "seal"}
    }
    new_business = {
        key: value
        for key, value in updated.items()
        if key not in {"revision", "record_sha256", "seal"}
    }
    if _same_semantic_value(old_business, new_business):
        raise _error(
            "ACTION_JOURNAL_NOOP_UPDATE",
            "journal revision cannot advance without a semantic phase update",
        )


def _journal_with(
    journal: Mapping[str, object],
    *,
    manager_secret: str | bytes | None,
    **changes: object,
) -> dict[str, object]:
    _require_journal_authenticity(journal, manager_secret)
    updated = dict(journal)
    updated.update(changes)
    updated["revision"] = int(journal["revision"]) + 1
    sealed = _reseal_journal(updated, manager_secret=manager_secret)
    _validate_journal_evolution(journal, sealed)
    return sealed


def _effect_position(
    journal: Mapping[str, object], effect_id: str
) -> tuple[int, dict[str, object]]:
    target = _expect_path_component(effect_id, "/effect_id")
    for position, effect in enumerate(journal["effects"]):  # type: ignore[union-attr]
        if effect["effect_id"] == target:
            return position, dict(effect)
    raise _error(
        "ACTION_JOURNAL_EFFECT_MISSING",
        "effect is not declared by this journal",
        details={"effect_id": target},
    )


def revision_revalidation_disposition(
    journal: object,
    current_task_revision: int,
    *,
    current_facts: object | None = None,
    manager_secret: str | bytes | None = None,
) -> str:
    normalized = normalize_journal(journal)
    try:
        _require_journal_authenticity(normalized, manager_secret)
    except ActionExecutionJournalError:
        return "QUARANTINE_REAUTH_REQUIRED"
    current_revision = _expect_revision(
        current_task_revision, "/current_task_revision"
    )
    bindings = normalized["bindings"]
    assert isinstance(bindings, dict)
    if current_revision == bindings["task_revision"]:
        return "CURRENT_REVISION"
    if bindings["revision_policy"] == "exact-revision":
        return "QUARANTINE_EXACT_REVISION_DRIFT"
    facts = _expect_object(current_facts, "/current_facts")
    _expect_exact_fields(facts, _REVISION_FACT_FIELDS, "/current_facts")
    normalized_facts = {
        "workflow_bundle_sha256": _expect_sha256(
            facts["workflow_bundle_sha256"],
            "/current_facts/workflow_bundle_sha256",
        ),
        "effect_plan_sha256": _expect_sha256(
            facts["effect_plan_sha256"],
            "/current_facts/effect_plan_sha256",
        ),
        "semantic_operation_sha256": _expect_sha256(
            facts["semantic_operation_sha256"],
            "/current_facts/semantic_operation_sha256",
        ),
        "scopes": normalize_scopes(
            facts["scopes"], "/current_facts/scopes"
        ),
        "guard_projection_sha256": _expect_sha256(
            facts["guard_projection_sha256"],
            "/current_facts/guard_projection_sha256",
        ),
        "evidence_sha256": _expect_sha256(
            facts["evidence_sha256"], "/current_facts/evidence_sha256"
        ),
        "approval_sha256": _expect_sha256(
            facts["approval_sha256"], "/current_facts/approval_sha256"
        ),
        "ownership_sha256": _expect_sha256(
            facts["ownership_sha256"], "/current_facts/ownership_sha256"
        ),
        "registry_state_sha256": _expect_sha256(
            facts["registry_state_sha256"],
            "/current_facts/registry_state_sha256",
        ),
        "postcondition_contract_sha256": _expect_sha256(
            facts["postcondition_contract_sha256"],
            "/current_facts/postcondition_contract_sha256",
        ),
    }
    for field in _REVISION_FACT_FIELDS - {"scopes"}:
        if not _digest_equal(normalized_facts[field], bindings[field]):
            return "QUARANTINE_BOUND_FACT_DRIFT"
    if not hmac.compare_digest(
        semantic_json_bytes(normalized_facts["scopes"]),
        semantic_json_bytes(bindings["scopes"]),
    ):
        return "QUARANTINE_BOUND_FACT_DRIFT"
    return "REEVALUATE_CURRENT_STATE"


def _active_effects(
    journal: Mapping[str, object], *, excluding: str
) -> list[Mapping[str, object]]:
    return [
        effect
        for effect in journal["effects"]  # type: ignore[union-attr]
        if effect["effect_id"] != excluding
        and effect["phase"] in {"CLAIMED", "RUNNING"}
    ]


def plan_effect_claim(
    journal: object,
    effect_id: str,
    claim_id: str,
    *,
    index: object,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> EffectClaimPlan:
    normalized = normalize_journal(journal)
    _require_journal_authenticity(normalized, manager_secret)
    _require_promoted_journal(index, normalized, expected_index)
    position, effect = _effect_position(normalized, effect_id)
    expected = cas_token(normalized)
    if normalized["phase"] not in {
        "PREPARED",
        "DISPATCH_CLAIMED",
        "RUNNING",
    }:
        raise _error(
            "ACTION_JOURNAL_CLAIM_PHASE_INVALID",
            "global phase does not admit a new effect claim",
        )
    if effect["phase"] != "PLANNED":
        raise _error(
            "ACTION_JOURNAL_EFFECT_ALREADY_CLAIMED",
            "claimed effect can never produce a second first-claim plan",
            details={"effect_id": effect_id},
        )
    effects_by_id = {
        str(candidate["effect_id"]): candidate
        for candidate in normalized["effects"]  # type: ignore[union-attr]
    }
    for predecessor in effect["predecessors"]:  # type: ignore[union-attr]
        if effects_by_id[str(predecessor)]["phase"] != "VERIFIED":
            raise _error(
                "ACTION_JOURNAL_EFFECT_DEPENDENCY_BLOCKED",
                "effect predecessor is not verified",
                details={
                    "effect_id": effect_id,
                    "predecessor": predecessor,
                },
            )
    for active in _active_effects(normalized, excluding=effect_id):
        if (
            effect["parallel_group"] is None
            or effect["parallel_group"] != active["parallel_group"]
            or scopes_overlap(effect["scopes"], active["scopes"])
        ):
            raise _error(
                "ACTION_JOURNAL_EFFECT_PARALLEL_CONFLICT",
                "concurrent effect claims require one declared disjoint parallel group",
                details={
                    "effect_id": effect_id,
                    "active_effect_id": active["effect_id"],
                },
            )
    effect["phase"] = "CLAIMED"
    effect["claim_id"] = _expect_string(
        claim_id, "/claim_id", identifier=True
    )
    effects = [dict(candidate) for candidate in normalized["effects"]]  # type: ignore[union-attr]
    effects[position] = effect
    phase = (
        "DISPATCH_CLAIMED"
        if normalized["phase"] == "PREPARED"
        else normalized["phase"]
    )
    updated = _journal_with(
        normalized,
        manager_secret=manager_secret,
        effects=effects,
        phase=phase,
    )
    return EffectClaimPlan(
        expected_journal=expected,
        expected_index=expected_index,
        journal=updated,
        effect_id=str(effect["effect_id"]),
        claim_id=str(effect["claim_id"]),
        first_claim=True,
    )


def recovery_disposition(
    journal: object,
    effect_id: str,
    *,
    authenticated_live_runtime: bool = False,
    complete_stored_receipt: bool = False,
    manager_secret: str | bytes | None = None,
) -> RecoveryDisposition:
    normalized = normalize_journal(journal)
    try:
        _require_journal_authenticity(normalized, manager_secret)
    except ActionExecutionJournalError:
        return RecoveryDisposition(
            action="QUARANTINE_REAUTH_REQUIRED",
            requires_new_durable_claim=False,
            dispatcher_reinvocation_allowed=False,
            preserves_receipt=True,
        )
    _, effect = _effect_position(normalized, effect_id)
    phase = str(effect["phase"])
    if phase == "PLANNED":
        return RecoveryDisposition(
            action="CLAIM_UNSTARTED",
            requires_new_durable_claim=True,
            dispatcher_reinvocation_allowed=False,
            preserves_receipt=True,
        )
    if complete_stored_receipt or effect["receipt_sha256"] is not None:
        return RecoveryDisposition(
            action="OBSERVE_STORED_RECEIPT",
            requires_new_durable_claim=False,
            dispatcher_reinvocation_allowed=False,
            preserves_receipt=True,
        )
    if (
        authenticated_live_runtime
        and effect["kind"] == "runtime-dispatch"
        and effect["runtime_binding_sha256"] is not None
    ):
        return RecoveryDisposition(
            action="REATTACH_OBSERVE_ONLY",
            requires_new_durable_claim=False,
            dispatcher_reinvocation_allowed=False,
            preserves_receipt=True,
        )
    if phase == "QUARANTINED":
        return RecoveryDisposition(
            action="RECONCILE_QUARANTINE",
            requires_new_durable_claim=False,
            dispatcher_reinvocation_allowed=False,
            preserves_receipt=True,
        )
    return RecoveryDisposition(
        action="QUARANTINE_NO_AUTHENTIC_HANDLE_OR_RECEIPT",
        requires_new_durable_claim=False,
        dispatcher_reinvocation_allowed=False,
        preserves_receipt=True,
    )


def advance_effect_phase(
    journal: object,
    effect_id: str,
    new_phase: str,
    *,
    manager_secret: str | bytes | None = None,
    containment_record_sha256: str | None = None,
    runtime_binding_sha256: str | None = None,
    receipt_sha256: str | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    if normalized["phase"] in {"COMMITTED", "QUARANTINED"}:
        raise _error(
            "ACTION_JOURNAL_PHASE_ABSORBING",
            "terminal global journal phase cannot be advanced",
        )
    position, effect = _effect_position(normalized, effect_id)
    requested = _expect_choice(new_phase, _EFFECT_PHASES, "/new_phase")
    current = str(effect["phase"])
    ordinary_transitions = {
        "CLAIMED": frozenset({"RUNNING"}),
        "RUNNING": frozenset({"QUIESCED", "HANDOFF_VERIFIED"}),
        "QUIESCED": frozenset({"VERIFIED"}),
        "HANDOFF_VERIFIED": frozenset({"VERIFIED"}),
    }
    if requested == "QUARANTINED":
        if current == "QUARANTINED":
            raise _error(
                "ACTION_JOURNAL_EFFECT_PHASE_INVALID",
                "quarantined effect phase is absorbing",
            )
    elif requested not in ordinary_transitions.get(current, frozenset()):
        raise _error(
            "ACTION_JOURNAL_EFFECT_PHASE_INVALID",
            "effect phase transition is not monotonic",
            details={"current": current, "requested": requested},
        )
    if (
        requested == "HANDOFF_VERIFIED"
        and effect["settlement"] != "asynchronous-handoff"
    ):
        raise _error(
            "ACTION_JOURNAL_HANDOFF_FORBIDDEN",
            "synchronous effect cannot enter HANDOFF_VERIFIED",
        )
    effect["phase"] = requested
    if requested in {"QUIESCED", "HANDOFF_VERIFIED"}:
        effect["settled_as"] = requested
    if containment_record_sha256 is not None:
        effect["containment_record_sha256"] = _expect_sha256(
            containment_record_sha256, "/containment_record_sha256"
        )
    if runtime_binding_sha256 is not None:
        effect["runtime_binding_sha256"] = _expect_sha256(
            runtime_binding_sha256, "/runtime_binding_sha256"
        )
    if receipt_sha256 is not None:
        effect["receipt_sha256"] = _expect_sha256(
            receipt_sha256, "/receipt_sha256"
        )
    if requested in {"RUNNING", "QUIESCED", "HANDOFF_VERIFIED", "VERIFIED"}:
        if effect["containment_record_sha256"] is None:
            raise _error(
                "ACTION_JOURNAL_CONTAINMENT_REQUIRED",
                "effect phase requires its linked containment record",
            )
    if requested == "HANDOFF_VERIFIED" and effect["runtime_binding_sha256"] is None:
        raise _error(
            "ACTION_JOURNAL_RUNTIME_BINDING_REQUIRED",
            "handoff requires an authenticated runtime binding",
        )
    if requested == "VERIFIED" and effect["receipt_sha256"] is None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_RECEIPT_REQUIRED",
            "verified effect requires its typed receipt digest",
        )
    effects = [dict(candidate) for candidate in normalized["effects"]]  # type: ignore[union-attr]
    effects[position] = effect
    global_phase = normalized["phase"]
    if requested == "RUNNING" and global_phase == "DISPATCH_CLAIMED":
        global_phase = "RUNNING"
    if requested == "QUARANTINED":
        global_phase = "QUARANTINED"
    return _journal_with(
        normalized,
        manager_secret=manager_secret,
        effects=effects,
        phase=global_phase,
        quarantine=(
            {
                "reason_code": "effect-phase-quarantined",
                "effect_id": effect_id,
                "receipt_sha256": effect["receipt_sha256"],
                "details_sha256": hashlib.sha256(
                    b"effect-phase-quarantined"
                ).hexdigest(),
            }
            if requested == "QUARANTINED"
            else normalized["quarantine"]
        ),
    )


def advance_global_settlement(
    journal: object,
    *,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    if normalized["phase"] != "RUNNING":
        raise _error(
            "ACTION_JOURNAL_PHASE_INVALID",
            "global settlement requires RUNNING",
        )
    effects = list(normalized["effects"])  # type: ignore[arg-type]
    settled = {"QUIESCED", "HANDOFF_VERIFIED", "VERIFIED"}
    if any(effect["phase"] not in settled for effect in effects):
        raise _error(
            "ACTION_JOURNAL_EFFECTS_UNSETTLED",
            "all effects must settle before global settlement",
        )
    phase = (
        "HANDOFF_VERIFIED"
        if any(
            effect["settled_as"] == "HANDOFF_VERIFIED"
            for effect in effects
        )
        else "QUIESCED"
    )
    return _journal_with(
        normalized, manager_secret=manager_secret, phase=phase
    )


def verify_receipt_intent(
    journal: object,
    receipt: object,
    *,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    if normalized["phase"] not in {"QUIESCED", "HANDOFF_VERIFIED"}:
        raise _error(
            "ACTION_JOURNAL_PHASE_INVALID",
            "receipt verification requires settled global execution",
        )
    normalized_receipt = _normalize_receipt(receipt)
    assert normalized_receipt is not None
    bindings = normalized["bindings"]
    assert isinstance(bindings, dict)
    if (
        normalized_receipt["authorization_action_edge_id"]
        != bindings["authorization_action_edge_id"]
        or normalized_receipt["completion_edge_id"]
        != bindings["completion_edge_id"]
    ):
        raise _error(
            "ACTION_JOURNAL_RECEIPT_EDGE_ROLE_MISMATCH",
            "receipt must bind the exact authorization and completion edges",
        )
    effects = list(normalized["effects"])  # type: ignore[arg-type]
    if any(effect["phase"] != "VERIFIED" for effect in effects):
        raise _error(
            "ACTION_JOURNAL_EFFECTS_UNVERIFIED",
            "all effect receipts must be verified first",
        )
    return _journal_with(
        normalized,
        manager_secret=manager_secret,
        phase="RECEIPT_VERIFIED",
        receipt=normalized_receipt,
    )


def commit_journal(
    journal: object,
    finalization: object,
    *,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    if normalized["phase"] != "RECEIPT_VERIFIED":
        raise _error(
            "ACTION_JOURNAL_PHASE_INVALID",
            "commit requires RECEIPT_VERIFIED",
        )
    normalized_finalization = _normalize_finalization(finalization)
    assert normalized_finalization is not None
    if normalized["bindings"]["authorization_kind"] == "manager":  # type: ignore[index]
        if not normalized_finalization["nonce_consumed"]:
            raise _error(
                "ACTION_JOURNAL_NONCE_COMMIT_REQUIRED",
                "manager task transaction must consume the bound nonce",
            )
    return _journal_with(
        normalized,
        manager_secret=manager_secret,
        phase="COMMITTED",
        finalization=normalized_finalization,
    )


def quarantine_journal(
    journal: object,
    *,
    reason_code: str,
    details_sha256: str,
    effect_id: str | None = None,
    receipt_sha256: str | None = None,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    if normalized["phase"] in {"COMMITTED", "QUARANTINED"}:
        raise _error(
            "ACTION_JOURNAL_PHASE_ABSORBING",
            "committed and quarantined journal phases are absorbing",
        )
    effects = list(normalized["effects"])  # type: ignore[arg-type]
    if effect_id is not None:
        position, effect = _effect_position(normalized, effect_id)
        effect["phase"] = "QUARANTINED"
        effects[position] = effect
    return _journal_with(
        normalized,
        manager_secret=manager_secret,
        effects=effects,
        phase="QUARANTINED",
        quarantine={
            "reason_code": _expect_string(
                reason_code, "/reason_code", identifier=True
            ),
            "effect_id": effect_id,
            "receipt_sha256": _expect_sha256(
                receipt_sha256, "/receipt_sha256", nullable=True
            ),
            "details_sha256": _expect_sha256(
                details_sha256, "/details_sha256"
            ),
        },
    )


def _normalize_digest_record(
    value: object,
    *,
    fields: frozenset[str],
    schema: str,
    domain: bytes,
    normalizer,
) -> dict[str, object]:
    record = _expect_object(value, "/")
    _expect_exact_fields(record, fields, "/")
    if record["schema"] != schema:
        raise _error(
            "ACTION_JOURNAL_SCHEMA_INVALID",
            "record schema is not supported",
            details={"schema": record.get("schema")},
        )
    normalized = normalizer(record)
    digest = _expect_sha256(
        normalized["record_sha256"], "/record_sha256"
    )
    expected = _record_digest(
        normalized, domain, frozenset({"record_sha256"})
    )
    assert digest is not None
    if not hmac.compare_digest(digest, expected):
        raise _error(
            "ACTION_JOURNAL_RECORD_DIGEST_MISMATCH",
            "record digest does not match canonical core bytes",
        )
    return normalized


def seal_containment(core: Mapping[str, object]) -> dict[str, object]:
    return normalize_containment(
        _seal_unsealed_record(core, domain=CONTAINMENT_RECORD_DOMAIN)
    )


def normalize_containment(value: object) -> dict[str, object]:
    def normalize(record: Mapping[str, object]) -> dict[str, object]:
        phase = _expect_choice(
            record["phase"], _CONTAINMENT_PHASES, "/phase"
        )
        runtime_handle = _expect_sha256(
            record["runtime_handle_sha256"],
            "/runtime_handle_sha256",
            nullable=True,
        )
        receipt = _expect_sha256(
            record["receipt_sha256"], "/receipt_sha256", nullable=True
        )
        if phase in {"RUNTIME_BOUND", "RELEASED", "HANDOFF_VERIFIED"}:
            if runtime_handle is None:
                raise _error(
                    "ACTION_JOURNAL_RUNTIME_BINDING_REQUIRED",
                    "containment phase requires a runtime handle binding",
                )
        if phase in {"QUIESCED", "HANDOFF_VERIFIED", "CLOSED"} and receipt is None:
            raise _error(
                "ACTION_JOURNAL_CONTAINMENT_RECEIPT_REQUIRED",
                "settled containment phase requires an observation digest",
            )
        return {
            "schema": ACTION_EFFECT_CONTAINMENT_SCHEMA,
            "task_id": _expect_string(
                record["task_id"], "/task_id", identifier=True
            ),
            "execution_id": _expect_path_component(
                record["execution_id"], "/execution_id"
            ),
            "effect_id": _expect_path_component(
                record["effect_id"], "/effect_id"
            ),
            "claim_id": _expect_string(
                record["claim_id"], "/claim_id", identifier=True
            ),
            "attempt_id": _expect_path_component(
                record["attempt_id"], "/attempt_id"
            ),
            "journal_schema": (
                ACTION_EXECUTION_JOURNAL_SCHEMA
                if record["journal_schema"]
                == ACTION_EXECUTION_JOURNAL_SCHEMA
                else _expect_choice(
                    record["journal_schema"],
                    frozenset({ACTION_EXECUTION_JOURNAL_SCHEMA}),
                    "/journal_schema",
                )
            ),
            "journal_record_sha256": _expect_sha256(
                record["journal_record_sha256"],
                "/journal_record_sha256",
            ),
            "revision": _expect_revision(record["revision"], "/revision"),
            "phase": phase,
            "runtime_handle_sha256": runtime_handle,
            "receipt_sha256": receipt,
            "record_sha256": _expect_sha256(
                record["record_sha256"], "/record_sha256"
            ),
        }

    return _normalize_digest_record(
        value,
        fields=_CONTAINMENT_FIELDS,
        schema=ACTION_EFFECT_CONTAINMENT_SCHEMA,
        domain=CONTAINMENT_RECORD_DOMAIN,
        normalizer=normalize,
    )


def new_containment(
    journal: object,
    effect_id: str,
    *,
    index: object,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    normalized = normalize_journal(journal)
    _require_journal_authenticity(normalized, manager_secret)
    _require_promoted_journal(index, normalized, expected_index)
    _, effect = _effect_position(normalized, effect_id)
    if effect["phase"] != "CLAIMED" or effect["claim_id"] is None:
        raise _error(
            "ACTION_JOURNAL_EFFECT_CLAIM_REQUIRED",
            "containment can be created only after durable effect claim",
        )
    return seal_containment(
        {
            "schema": ACTION_EFFECT_CONTAINMENT_SCHEMA,
            "task_id": normalized["task_id"],
            "execution_id": normalized["execution_id"],
            "effect_id": effect["effect_id"],
            "claim_id": effect["claim_id"],
            "attempt_id": effect["attempt_id"],
            "journal_schema": ACTION_EXECUTION_JOURNAL_SCHEMA,
            "journal_record_sha256": normalized["record_sha256"],
            "revision": 0,
            "phase": "SPAWN_PENDING",
            "runtime_handle_sha256": None,
            "receipt_sha256": None,
        }
    )


def advance_containment(
    containment: object,
    new_phase: str,
    *,
    runtime_handle_sha256: str | None = None,
    receipt_sha256: str | None = None,
) -> dict[str, object]:
    normalized = normalize_containment(containment)
    requested = _expect_choice(
        new_phase, _CONTAINMENT_PHASES, "/new_phase"
    )
    current = str(normalized["phase"])
    transitions = {
        "SPAWN_PENDING": frozenset({"RUNTIME_BOUND", "QUIESCED"}),
        "RUNTIME_BOUND": frozenset({"RELEASED"}),
        "RELEASED": frozenset({"QUIESCED", "HANDOFF_VERIFIED"}),
        "QUIESCED": frozenset({"CLOSED"}),
        "HANDOFF_VERIFIED": frozenset({"CLOSED"}),
    }
    if requested == "QUARANTINED":
        if current in {"CLOSED", "QUARANTINED"}:
            raise _error(
                "ACTION_JOURNAL_CONTAINMENT_PHASE_INVALID",
                "terminal containment phase is absorbing",
            )
    elif requested not in transitions.get(current, frozenset()):
        raise _error(
            "ACTION_JOURNAL_CONTAINMENT_PHASE_INVALID",
            "containment phase transition is not monotonic",
            details={"current": current, "requested": requested},
        )
    updated = {
        **normalized,
        "revision": int(normalized["revision"]) + 1,
        "phase": requested,
    }
    if runtime_handle_sha256 is not None:
        updated["runtime_handle_sha256"] = _expect_sha256(
            runtime_handle_sha256, "/runtime_handle_sha256"
        )
    if receipt_sha256 is not None:
        updated["receipt_sha256"] = _expect_sha256(
            receipt_sha256, "/receipt_sha256"
        )
    if current == "HANDOFF_VERIFIED" and requested == "CLOSED":
        if receipt_sha256 is None or _digest_equal(
            normalized["receipt_sha256"], updated["receipt_sha256"]
        ):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_EXIT_EVIDENCE_REQUIRED",
                "closing a handed-off containment requires fresh authenticated exit or quiescence evidence",
            )
    return seal_containment(
        {
            key: value
            for key, value in updated.items()
            if key != "record_sha256"
        }
    )


def seal_runtime_reservation(
    core: Mapping[str, object],
) -> dict[str, object]:
    return normalize_runtime_reservation(
        _seal_unsealed_record(
            core, domain=RUNTIME_RESERVATION_RECORD_DOMAIN
        )
    )


def runtime_binding_sha256(
    *,
    task_id: str,
    execution_id: str,
    effect_id: str,
    claim_id: str,
    attempt_id: str,
    lease_id: str,
    runtime_handle_sha256: str,
    stop_action_id: str,
    reconcile_action_id: str,
) -> str:
    """Digest one exact runtime handoff identity without secret material."""

    binding = {
        "task_id": _expect_string(
            task_id, "/task_id", identifier=True
        ),
        "execution_id": _expect_path_component(
            execution_id, "/execution_id"
        ),
        "effect_id": _expect_path_component(
            effect_id, "/effect_id"
        ),
        "claim_id": _expect_string(
            claim_id, "/claim_id", identifier=True
        ),
        "attempt_id": _expect_path_component(
            attempt_id, "/attempt_id"
        ),
        "lease_id": _expect_string(
            lease_id, "/lease_id", identifier=True
        ),
        "runtime_handle_sha256": _expect_sha256(
            runtime_handle_sha256, "/runtime_handle_sha256"
        ),
        "stop_action_id": _expect_string(
            stop_action_id, "/stop_action_id", identifier=True
        ),
        "reconcile_action_id": _expect_string(
            reconcile_action_id,
            "/reconcile_action_id",
            identifier=True,
        ),
    }
    return semantic_sha256(RUNTIME_BINDING_DOMAIN, binding)


def new_runtime_reservation(
    committed_journal: object,
    effect_id: str,
    containment_record: object,
    *,
    lease_id: str,
    runtime_handle_sha256: str,
    stop_action_id: str,
    reconcile_action_id: str,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    """Build the only reservation allowed by a committed exact handoff."""

    journal = normalize_journal(committed_journal)
    _require_journal_authenticity(journal, manager_secret)
    containment = normalize_containment(containment_record)
    _, effect = _effect_position(journal, effect_id)
    claim_id = effect["claim_id"]
    if not isinstance(claim_id, str):
        raise _error(
            "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
            "runtime reservation requires one durable effect claim",
        )
    expected_binding = runtime_binding_sha256(
        task_id=str(journal["task_id"]),
        execution_id=str(journal["execution_id"]),
        effect_id=str(effect["effect_id"]),
        claim_id=claim_id,
        attempt_id=str(effect["attempt_id"]),
        lease_id=lease_id,
        runtime_handle_sha256=runtime_handle_sha256,
        stop_action_id=stop_action_id,
        reconcile_action_id=reconcile_action_id,
    )
    scopes = effect["scopes"]
    assert isinstance(scopes, dict)
    if (
        journal["phase"] != "COMMITTED"
        or effect["kind"] != "runtime-dispatch"
        or effect["settlement"] != "asynchronous-handoff"
        or effect["settled_as"] != "HANDOFF_VERIFIED"
        or effect["phase"] != "VERIFIED"
        or containment["phase"] != "HANDOFF_VERIFIED"
        or containment["task_id"] != journal["task_id"]
        or containment["execution_id"] != journal["execution_id"]
        or containment["effect_id"] != effect["effect_id"]
        or containment["claim_id"] != claim_id
        or containment["attempt_id"] != effect["attempt_id"]
        or not _digest_equal(
            containment["record_sha256"],
            effect["containment_record_sha256"],
        )
        or not _digest_equal(
            containment["receipt_sha256"],
            effect["receipt_sha256"],
        )
        or not _digest_equal(
            containment["runtime_handle_sha256"],
            runtime_handle_sha256,
        )
        or not _digest_equal(
            effect["runtime_binding_sha256"], expected_binding
        )
        or lease_id not in scopes["lease_ids"]
    ):
        raise _error(
            "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
            "reservation differs from the committed handoff cross-links",
        )
    return seal_runtime_reservation(
        {
            "schema": ACTION_RUNTIME_RESERVATION_SCHEMA,
            "task_id": journal["task_id"],
            "execution_id": journal["execution_id"],
            "effect_id": effect["effect_id"],
            "lease_id": lease_id,
            "runtime_handle_sha256": runtime_handle_sha256,
            "scopes": scopes,
            "containment_record_sha256": containment[
                "record_sha256"
            ],
            "handoff_receipt_sha256": containment[
                "receipt_sha256"
            ],
            "stop_action_id": stop_action_id,
            "reconcile_action_id": reconcile_action_id,
            "phase": "ACTIVE",
            "result_event_sha256": None,
        }
    )


def normalize_runtime_reservation(value: object) -> dict[str, object]:
    def normalize(record: Mapping[str, object]) -> dict[str, object]:
        lease_id = _expect_string(
            record["lease_id"], "/lease_id", identifier=True
        )
        scopes = normalize_scopes(record["scopes"], "/scopes")
        if not _scopes_nonempty(scopes):
            raise _error(
                "ACTION_JOURNAL_SCOPE_REQUIRED",
                "runtime reservation must preserve a canonical scope",
            )
        if lease_id not in scopes["lease_ids"]:
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "reservation lease must be present in its canonical scope",
            )
        return {
            "schema": ACTION_RUNTIME_RESERVATION_SCHEMA,
            "task_id": _expect_string(
                record["task_id"], "/task_id", identifier=True
            ),
            "execution_id": _expect_path_component(
                record["execution_id"], "/execution_id"
            ),
            "effect_id": _expect_path_component(
                record["effect_id"], "/effect_id"
            ),
            "lease_id": lease_id,
            "runtime_handle_sha256": _expect_sha256(
                record["runtime_handle_sha256"],
                "/runtime_handle_sha256",
            ),
            "scopes": scopes,
            "containment_record_sha256": _expect_sha256(
                record["containment_record_sha256"],
                "/containment_record_sha256",
            ),
            "handoff_receipt_sha256": _expect_sha256(
                record["handoff_receipt_sha256"],
                "/handoff_receipt_sha256",
            ),
            "stop_action_id": _expect_string(
                record["stop_action_id"],
                "/stop_action_id",
                identifier=True,
            ),
            "reconcile_action_id": _expect_string(
                record["reconcile_action_id"],
                "/reconcile_action_id",
                identifier=True,
            ),
            "phase": _expect_choice(
                record["phase"], _RUNTIME_RESERVATION_PHASES, "/phase"
            ),
            "result_event_sha256": _expect_sha256(
                record["result_event_sha256"],
                "/result_event_sha256",
                nullable=True,
            ),
            "record_sha256": _expect_sha256(
                record["record_sha256"], "/record_sha256"
            ),
        }

    return _normalize_digest_record(
        value,
        fields=_RUNTIME_RESERVATION_FIELDS,
        schema=ACTION_RUNTIME_RESERVATION_SCHEMA,
        domain=RUNTIME_RESERVATION_RECORD_DOMAIN,
        normalizer=normalize,
    )


def seal_reconciliation_attempt(
    core: Mapping[str, object],
) -> dict[str, object]:
    return normalize_reconciliation_attempt(
        _seal_unsealed_record(core, domain=RECONCILIATION_RECORD_DOMAIN)
    )


def _normalize_reconciliation_bindings(value: object) -> dict[str, object]:
    bindings = _expect_object(value, "/bindings")
    _expect_exact_fields(
        bindings, _RECONCILIATION_BINDING_FIELDS, "/bindings"
    )
    return {
        "target_journal_record_sha256": _expect_sha256(
            bindings["target_journal_record_sha256"],
            "/bindings/target_journal_record_sha256",
        ),
        "target_receipt_sha256": _expect_sha256(
            bindings["target_receipt_sha256"],
            "/bindings/target_receipt_sha256",
            nullable=True,
        ),
        "effect_id": _expect_path_component(
            bindings["effect_id"], "/bindings/effect_id"
        ),
        "expected_task_revision": _expect_revision(
            bindings["expected_task_revision"],
            "/bindings/expected_task_revision",
        ),
        "expected_index_revision": _expect_revision(
            bindings["expected_index_revision"],
            "/bindings/expected_index_revision",
        ),
        "expected_index_sha256": _expect_sha256(
            bindings["expected_index_sha256"],
            "/bindings/expected_index_sha256",
        ),
        "expected_journal_revision": _expect_revision(
            bindings["expected_journal_revision"],
            "/bindings/expected_journal_revision",
        ),
        "expected_journal_sha256": _expect_sha256(
            bindings["expected_journal_sha256"],
            "/bindings/expected_journal_sha256",
        ),
        "recovery_action_id": _expect_string(
            bindings["recovery_action_id"],
            "/bindings/recovery_action_id",
            identifier=True,
        ),
        "authorization_kind": _expect_choice(
            bindings["authorization_kind"],
            frozenset({"manager", "operator"}),
            "/bindings/authorization_kind",
        ),
        "authorization_sha256": _expect_sha256(
            bindings["authorization_sha256"],
            "/bindings/authorization_sha256",
        ),
        "capability_sha256": _expect_sha256(
            bindings["capability_sha256"],
            "/bindings/capability_sha256",
            nullable=True,
        ),
        "gate_sha256": _expect_sha256(
            bindings["gate_sha256"], "/bindings/gate_sha256"
        ),
        "request_nonce_sha256": _expect_sha256(
            bindings["request_nonce_sha256"],
            "/bindings/request_nonce_sha256",
        ),
        "engine_proof_sha256": _expect_sha256(
            bindings["engine_proof_sha256"],
            "/bindings/engine_proof_sha256",
        ),
        "principal": _expect_string(
            bindings["principal"], "/bindings/principal"
        ),
    }


def _normalize_compensation_plan(value: object) -> dict[str, object]:
    plan = _expect_object(value, "/compensation_plan")
    _expect_exact_fields(
        plan, _COMPENSATION_PLAN_FIELDS, "/compensation_plan"
    )
    if plan["schema"] != ACTION_COMPENSATION_PLAN_SCHEMA:
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PLAN_SCHEMA_INVALID",
            "compensation plan schema is not supported",
        )
    safe_inputs = _expect_object(
        plan["safe_inputs"], "/compensation_plan/safe_inputs"
    )
    _reject_secret_fields(
        safe_inputs, "/compensation_plan/safe_inputs"
    )
    safe_inputs_sha256 = _expect_sha256(
        plan["safe_inputs_sha256"],
        "/compensation_plan/safe_inputs_sha256",
    )
    expected_safe_inputs = semantic_sha256(
        SAFE_INPUT_DOMAIN, safe_inputs
    )
    if not _digest_equal(safe_inputs_sha256, expected_safe_inputs):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_SAFE_INPUT_MISMATCH",
            "compensation safe-input digest does not match canonical inputs",
        )
    return {
        "schema": ACTION_COMPENSATION_PLAN_SCHEMA,
        "action_id": _expect_string(
            plan["action_id"],
            "/compensation_plan/action_id",
            identifier=True,
        ),
        "effect_id": _expect_path_component(
            plan["effect_id"], "/compensation_plan/effect_id"
        ),
        "safe_inputs": safe_inputs,
        "safe_inputs_sha256": safe_inputs_sha256,
        "postcondition_contract_sha256": _expect_sha256(
            plan["postcondition_contract_sha256"],
            "/compensation_plan/postcondition_contract_sha256",
        ),
    }


def normalize_compensation_plan(value: object) -> dict[str, object]:
    return _normalize_compensation_plan(value)


def compensation_plan_sha256(value: object) -> str:
    return semantic_sha256(
        COMPENSATION_PLAN_DOMAIN,
        _normalize_compensation_plan(value),
    )


def _normalize_compensation_authorization(
    value: object,
) -> dict[str, object] | None:
    if value is None:
        return None
    authorization = _expect_object(
        value, "/compensation_authorization"
    )
    _expect_exact_fields(
        authorization,
        _COMPENSATION_AUTHORIZATION_FIELDS,
        "/compensation_authorization",
    )
    plan = _normalize_compensation_plan(
        authorization["compensation_plan"]
    )
    plan_sha256 = _expect_sha256(
        authorization["compensation_plan_sha256"],
        "/compensation_authorization/compensation_plan_sha256",
    )
    if not _digest_equal(
        plan_sha256, compensation_plan_sha256(plan)
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PLAN_DIGEST_MISMATCH",
            "compensation authorization does not bind its exact versioned plan",
        )
    host_principal = _expect_string(
        authorization["host_principal"],
        "/compensation_authorization/host_principal",
    )
    workflow_principal = _expect_string(
        authorization["workflow_principal"],
        "/compensation_authorization/workflow_principal",
    )
    if host_principal == workflow_principal:
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_DUAL_APPROVAL_INVALID",
            "host and workflow compensation approvals require distinct principals",
        )
    return {
        "compensation_execution_id": _expect_path_component(
            authorization["compensation_execution_id"],
            "/compensation_authorization/compensation_execution_id",
        ),
        "compensation_plan": plan,
        "compensation_plan_sha256": plan_sha256,
        "dual_approval_sha256": _expect_sha256(
            authorization["dual_approval_sha256"],
            "/compensation_authorization/dual_approval_sha256",
        ),
        "host_principal": host_principal,
        "host_approval_sha256": _expect_sha256(
            authorization["host_approval_sha256"],
            "/compensation_authorization/host_approval_sha256",
        ),
        "workflow_principal": workflow_principal,
        "workflow_approval_sha256": _expect_sha256(
            authorization["workflow_approval_sha256"],
            "/compensation_authorization/workflow_approval_sha256",
        ),
    }


def _normalize_reconciliation_outcome(
    value: object,
) -> dict[str, object] | None:
    if value is None:
        return None
    outcome = _expect_object(value, "/outcome")
    _expect_exact_fields(
        outcome, _RECONCILIATION_OUTCOME_FIELDS, "/outcome"
    )
    decision = _expect_choice(
        outcome["decision"],
        _TERMINAL_RECONCILIATION_PHASES,
        "/outcome/decision",
    )
    expected_proof_kind = {
        "ACCEPTED": "receipt-postconditions",
        "ABANDONED": "no-outcome-quiescence",
        "COMPENSATED": "compensation-receipt",
        "UNRESOLVED": "unresolved-diagnostic",
    }[decision]
    proof_kind = _expect_choice(
        outcome["proof_kind"],
        frozenset(
            {
                "receipt-postconditions",
                "no-outcome-quiescence",
                "compensation-receipt",
                "unresolved-diagnostic",
            }
        ),
        "/outcome/proof_kind",
    )
    if proof_kind != expected_proof_kind:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PROOF_INVALID",
            "decision must bind its exact proof contract",
        )
    compensation_execution_id = outcome["compensation_execution_id"]
    if compensation_execution_id is not None:
        compensation_execution_id = _expect_path_component(
            compensation_execution_id,
            "/outcome/compensation_execution_id",
        )
    compensation_receipt = _expect_sha256(
        outcome["compensation_receipt_sha256"],
        "/outcome/compensation_receipt_sha256",
        nullable=True,
    )
    dual_approval = _expect_sha256(
        outcome["dual_approval_sha256"],
        "/outcome/dual_approval_sha256",
        nullable=True,
    )
    compensation_authorization_sha256 = _expect_sha256(
        outcome["compensation_authorization_sha256"],
        "/outcome/compensation_authorization_sha256",
        nullable=True,
    )
    if decision == "COMPENSATED":
        if (
            compensation_execution_id is None
            or compensation_receipt is None
            or dual_approval is None
            or compensation_authorization_sha256 is None
        ):
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_PROOF_REQUIRED",
                "compensated decision requires separate execution, receipt, and dual approval",
            )
    elif (
        compensation_execution_id is not None
        or compensation_receipt is not None
        or dual_approval is not None
        or compensation_authorization_sha256 is not None
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PROOF_FORBIDDEN",
            "only compensated decision may bind compensation execution",
        )
    task_commit_revision = outcome["task_commit_revision"]
    task_state_sha256 = _expect_sha256(
        outcome["task_state_sha256"],
        "/outcome/task_state_sha256",
        nullable=True,
    )
    outbox_sha256 = _expect_sha256(
        outcome["outbox_sha256"],
        "/outcome/outbox_sha256",
        nullable=True,
    )
    nonce_consumed = _expect_bool(
        outcome["nonce_consumed"], "/outcome/nonce_consumed"
    )
    if decision == "UNRESOLVED":
        if (
            task_commit_revision is not None
            or task_state_sha256 is not None
            or outbox_sha256 is not None
            or nonce_consumed
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_COMMIT_FORBIDDEN",
                "unresolved attempt cannot claim task commit or nonce consumption",
            )
    else:
        task_commit_revision = _expect_revision(
            task_commit_revision, "/outcome/task_commit_revision"
        )
        if (
            task_state_sha256 is None
            or outbox_sha256 is None
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_COMMIT_REQUIRED",
                "closing decision must bind task state and outbox",
            )
    return {
        "decision": decision,
        "proof_kind": proof_kind,
        "evidence_sha256": _expect_sha256(
            outcome["evidence_sha256"], "/outcome/evidence_sha256"
        ),
        "recovery_event_sha256": _expect_sha256(
            outcome["recovery_event_sha256"],
            "/outcome/recovery_event_sha256",
            nullable=decision == "UNRESOLVED",
        ),
        "task_commit_revision": task_commit_revision,
        "task_state_sha256": task_state_sha256,
        "outbox_sha256": outbox_sha256,
        "nonce_consumed": nonce_consumed,
        "compensation_execution_id": compensation_execution_id,
        "compensation_receipt_sha256": compensation_receipt,
        "dual_approval_sha256": dual_approval,
        "compensation_authorization_sha256": (
            compensation_authorization_sha256
        ),
        "runtime_reservation_sha256": _expect_sha256(
            outcome["runtime_reservation_sha256"],
            "/outcome/runtime_reservation_sha256",
            nullable=True,
        ),
    }


def normalize_reconciliation_attempt(value: object) -> dict[str, object]:
    def normalize(record: Mapping[str, object]) -> dict[str, object]:
        phase = _expect_choice(
            record["phase"], _RECONCILIATION_PHASES, "/phase"
        )
        bindings = _normalize_reconciliation_bindings(
            record["bindings"]
        )
        outcome = _normalize_reconciliation_outcome(record["outcome"])
        compensation_authorization = (
            _normalize_compensation_authorization(
                record["compensation_authorization"]
            )
        )
        if (
            phase in {"PREPARED", "CLAIMED", "COMPENSATION_AUTHORIZED"}
            and outcome is not None
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_OUTCOME_INVALID",
                "nonterminal attempt cannot contain an outcome",
            )
        if phase in _TERMINAL_RECONCILIATION_PHASES:
            if outcome is None or outcome["decision"] != phase:
                raise _error(
                    "ACTION_JOURNAL_RECONCILIATION_OUTCOME_REQUIRED",
                    "terminal attempt must bind its exact decision",
                )
            expected_nonce_consumed = (
                bindings["authorization_kind"] == "manager"
                and phase != "UNRESOLVED"
            )
            if (
                outcome["nonce_consumed"]
                is not expected_nonce_consumed
            ):
                raise _error(
                    "ACTION_JOURNAL_RECONCILIATION_NONCE_INVALID",
                    "outcome nonce consumption differs from its authorization kind",
                )
        if phase == "COMPENSATION_AUTHORIZED":
            if compensation_authorization is None:
                raise _error(
                    "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_REQUIRED",
                    "authorized compensation phase requires its exact plan and approvals",
                )
        elif phase == "COMPENSATED":
            if compensation_authorization is None:
                raise _error(
                    "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_REQUIRED",
                    "compensated outcome must retain its authorization",
                )
        elif compensation_authorization is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_FORBIDDEN",
                "only compensation phases may contain authorization facts",
            )
        return {
            "schema": ACTION_RECONCILIATION_ATTEMPT_SCHEMA,
            "task_id": _expect_string(
                record["task_id"], "/task_id", identifier=True
            ),
            "attempt_id": _expect_path_component(
                record["attempt_id"], "/attempt_id"
            ),
            "target_execution_id": _expect_path_component(
                record["target_execution_id"], "/target_execution_id"
            ),
            "revision": _expect_revision(record["revision"], "/revision"),
            "phase": phase,
            "bindings": bindings,
            "compensation_authorization": compensation_authorization,
            "outcome": outcome,
            "record_sha256": _expect_sha256(
                record["record_sha256"], "/record_sha256"
            ),
        }

    return _normalize_digest_record(
        value,
        fields=_RECONCILIATION_FIELDS,
        schema=ACTION_RECONCILIATION_ATTEMPT_SCHEMA,
        domain=RECONCILIATION_RECORD_DOMAIN,
        normalizer=normalize,
    )


def new_reconciliation_attempt(
    quarantined_journal: object,
    index: object,
    *,
    attempt_id: str,
    effect_id: str,
    expected_task_revision: int,
    recovery_action_id: str,
    authorization_kind: str,
    authorization_sha256: str,
    capability_sha256: str | None,
    gate_sha256: str,
    request_nonce_sha256: str,
    engine_proof_sha256: str,
    principal: str,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    journal = normalize_journal(quarantined_journal)
    _require_journal_authenticity(journal, manager_secret)
    normalized_index = normalize_index(index)
    if journal["phase"] != "QUARANTINED":
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_TARGET_INVALID",
            "reconciliation target must remain QUARANTINED",
        )
    entry = _entry_for(normalized_index, str(journal["execution_id"]))
    if entry is None or not _digest_equal(
        entry["record_sha256"], journal["record_sha256"]
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_TARGET_INVALID",
            "quarantined journal must remain indexed at its exact digest",
        )
    receipt = journal["receipt"]
    receipt_sha256 = (
        receipt["receipt_sha256"]  # type: ignore[index]
        if isinstance(receipt, dict)
        else (
            journal["quarantine"]["receipt_sha256"]  # type: ignore[index]
            if isinstance(journal["quarantine"], dict)
            else None
        )
    )
    target_effects = journal["effects"]
    if (
        not isinstance(target_effects, list)
        or not any(
            isinstance(item, Mapping)
            and item.get("effect_id") == effect_id
            for item in target_effects
        )
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_EFFECT_INVALID",
            "reconciliation must bind one exact target effect",
        )
    if authorization_kind == "manager":
        capability_sha256 = _expect_sha256(
            capability_sha256, "/capability_sha256"
        )
    elif capability_sha256 is not None:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_AUTHORIZATION_INVALID",
            "operator reconciliation cannot bind manager capability",
        )
    return seal_reconciliation_attempt(
        {
            "schema": ACTION_RECONCILIATION_ATTEMPT_SCHEMA,
            "task_id": journal["task_id"],
            "attempt_id": _expect_path_component(
                attempt_id, "/attempt_id"
            ),
            "target_execution_id": journal["execution_id"],
            "revision": 0,
            "phase": "PREPARED",
            "bindings": {
                "target_journal_record_sha256": journal["record_sha256"],
                "target_receipt_sha256": receipt_sha256,
                "effect_id": _expect_path_component(
                    effect_id, "/effect_id"
                ),
                "expected_task_revision": _expect_revision(
                    expected_task_revision, "/expected_task_revision"
                ),
                "expected_index_revision": normalized_index["revision"],
                "expected_index_sha256": normalized_index["record_sha256"],
                "expected_journal_revision": journal["revision"],
                "expected_journal_sha256": journal["record_sha256"],
                "recovery_action_id": recovery_action_id,
                "authorization_kind": authorization_kind,
                "authorization_sha256": authorization_sha256,
                "capability_sha256": capability_sha256,
                "gate_sha256": gate_sha256,
                "request_nonce_sha256": request_nonce_sha256,
                "engine_proof_sha256": engine_proof_sha256,
                "principal": principal,
            },
            "compensation_authorization": None,
            "outcome": None,
        }
    )


def advance_reconciliation_attempt(
    attempt: object,
    new_phase: str,
    *,
    evidence_sha256: str | None = None,
    recovery_event_sha256: str | None = None,
    task_commit_revision: int | None = None,
    task_state_sha256: str | None = None,
    outbox_sha256: str | None = None,
    nonce_consumed: bool = False,
    compensation_execution_id: str | None = None,
    compensation_receipt_sha256: str | None = None,
    dual_approval_sha256: str | None = None,
    compensation_authorization_sha256: str | None = None,
    runtime_reservation_sha256: str | None = None,
) -> dict[str, object]:
    normalized = normalize_reconciliation_attempt(attempt)
    current = str(normalized["phase"])
    requested = _expect_choice(
        new_phase, _RECONCILIATION_PHASES, "/new_phase"
    )
    if current in _TERMINAL_RECONCILIATION_PHASES:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_REPLAY",
            "terminal reconciliation attempt cannot be replayed",
        )
    if current == "PREPARED" and requested != "CLAIMED":
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PHASE_INVALID",
            "reconciliation must be claimed before decision",
        )
    if (
        current == "CLAIMED"
        and requested
        not in (
            _TERMINAL_RECONCILIATION_PHASES
            | {"COMPENSATION_AUTHORIZED"}
        )
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PHASE_INVALID",
            "claimed reconciliation requires one terminal decision",
        )
    if current == "CLAIMED" and requested == "COMPENSATED":
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_REQUIRED",
            "compensation must first bind a versioned plan and dual approval",
        )
    if (
        current == "COMPENSATION_AUTHORIZED"
        and requested != "COMPENSATED"
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PHASE_INVALID",
            "authorized compensation may close only as COMPENSATED",
        )
    outcome = None
    if requested in _TERMINAL_RECONCILIATION_PHASES:
        if (
            requested == "ACCEPTED"
            and normalized["bindings"]["target_receipt_sha256"] is None  # type: ignore[index]
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_RECEIPT_REQUIRED",
                "acceptance must reuse a stored target receipt",
            )
        outcome = {
            "decision": requested,
            "proof_kind": {
                "ACCEPTED": "receipt-postconditions",
                "ABANDONED": "no-outcome-quiescence",
                "COMPENSATED": "compensation-receipt",
                "UNRESOLVED": "unresolved-diagnostic",
            }[requested],
            "evidence_sha256": _expect_sha256(
                evidence_sha256, "/evidence_sha256"
            ),
            "recovery_event_sha256": _expect_sha256(
                recovery_event_sha256,
                "/recovery_event_sha256",
                nullable=requested == "UNRESOLVED",
            ),
            "task_commit_revision": task_commit_revision,
            "task_state_sha256": _expect_sha256(
                task_state_sha256,
                "/task_state_sha256",
                nullable=True,
            ),
            "outbox_sha256": _expect_sha256(
                outbox_sha256,
                "/outbox_sha256",
                nullable=True,
            ),
            "nonce_consumed": _expect_bool(
                nonce_consumed, "/nonce_consumed"
            ),
            "compensation_execution_id": compensation_execution_id,
            "compensation_receipt_sha256": _expect_sha256(
                compensation_receipt_sha256,
                "/compensation_receipt_sha256",
                nullable=True,
            ),
            "dual_approval_sha256": _expect_sha256(
                dual_approval_sha256,
                "/dual_approval_sha256",
                nullable=True,
            ),
            "compensation_authorization_sha256": _expect_sha256(
                compensation_authorization_sha256,
                "/compensation_authorization_sha256",
                nullable=True,
            ),
            "runtime_reservation_sha256": _expect_sha256(
                runtime_reservation_sha256,
                "/runtime_reservation_sha256",
                nullable=True,
            ),
        }
    return seal_reconciliation_attempt(
        {
            **{
                key: value
                for key, value in normalized.items()
                if key != "record_sha256"
            },
            "revision": int(normalized["revision"]) + 1,
            "phase": requested,
            "outcome": outcome,
        }
    )


def authorize_reconciliation_compensation(
    attempt: object,
    *,
    compensation_execution_id: str,
    compensation_plan: object,
    dual_approval_sha256: str,
    host_principal: str,
    host_approval_sha256: str,
    workflow_principal: str,
    workflow_approval_sha256: str,
) -> dict[str, object]:
    normalized = normalize_reconciliation_attempt(attempt)
    if normalized["phase"] != "CLAIMED":
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PHASE_INVALID",
            "compensation authorization requires a claimed reconciliation",
        )
    authorization = _normalize_compensation_authorization(
        {
            "compensation_execution_id": compensation_execution_id,
            "compensation_plan": compensation_plan,
            "compensation_plan_sha256": compensation_plan_sha256(
                compensation_plan
            ),
            "dual_approval_sha256": dual_approval_sha256,
            "host_principal": host_principal,
            "host_approval_sha256": host_approval_sha256,
            "workflow_principal": workflow_principal,
            "workflow_approval_sha256": workflow_approval_sha256,
        }
    )
    assert authorization is not None
    return seal_reconciliation_attempt(
        {
            **{
                key: value
                for key, value in normalized.items()
                if key != "record_sha256"
            },
            "revision": int(normalized["revision"]) + 1,
            "phase": "COMPENSATION_AUTHORIZED",
            "compensation_authorization": authorization,
            "outcome": None,
        }
    )


def reconciliation_eligibility(
    attempt: object,
    quarantined_journal: object,
    *,
    current_task_revision: int,
    authorization_current: bool,
    gate_current: bool,
    nonce_unused: bool,
    engine_proof_current: bool,
    manager_secret: str | bytes | None = None,
) -> str:
    normalized_attempt = normalize_reconciliation_attempt(attempt)
    target = normalize_journal(quarantined_journal)
    try:
        _require_journal_authenticity(target, manager_secret)
    except ActionExecutionJournalError:
        return "AUTHORIZATION_EXPIRED_OR_REVOKED"
    if normalized_attempt["phase"] not in {"PREPARED", "CLAIMED"}:
        return "ATTEMPT_TERMINAL"
    if target["phase"] != "QUARANTINED":
        return "TARGET_NOT_QUARANTINED"
    if (
        normalized_attempt["task_id"] != target["task_id"]
        or normalized_attempt["target_execution_id"]
        != target["execution_id"]
    ):
        return "TARGET_IDENTITY_DRIFT"
    bindings = normalized_attempt["bindings"]
    assert isinstance(bindings, dict)
    if (
        bindings["expected_journal_revision"] != target["revision"]
        or not _digest_equal(
            bindings["expected_journal_sha256"],
            target["record_sha256"],
        )
        or not _digest_equal(
            bindings["target_journal_record_sha256"],
            target["record_sha256"],
        )
    ):
        return "TARGET_JOURNAL_DRIFT"
    if _expect_revision(
        current_task_revision, "/current_task_revision"
    ) != bindings["expected_task_revision"]:
        return "TASK_REVISION_DRIFT"
    for current, code in (
        (authorization_current, "AUTHORIZATION_EXPIRED_OR_REVOKED"),
        (gate_current, "GATE_NOT_CURRENT"),
        (nonce_unused, "NONCE_REPLAY"),
        (engine_proof_current, "ENGINE_PROOF_NOT_CURRENT"),
    ):
        _expect_bool(current, "/current_reconciliation_fact")
        if not current:
            return code
    return "CURRENT"


def plan_reconciliation_initial_write(
    index: object,
    attempt: object,
    *,
    target_journal: object,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> WriteAheadPlan:
    """Reserve and promote one target-bound reconciliation control child."""

    normalized_index = normalize_index(index)
    normalized_attempt = normalize_reconciliation_attempt(attempt)
    normalized_target = normalize_journal(target_journal)
    _require_journal_authenticity(normalized_target, manager_secret)
    assert_cas(normalized_index, expected_index)
    bindings = normalized_attempt["bindings"]
    assert isinstance(bindings, dict)
    if (
        normalized_attempt["task_id"] != normalized_index["task_id"]
        or bindings["expected_index_revision"] != normalized_index["revision"]
        or not hmac.compare_digest(
            str(bindings["expected_index_sha256"]),
            str(normalized_index["record_sha256"]),
        )
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_CAS_STALE",
            "attempt is not bound to the current index",
        )
    target = _entry_for(
        normalized_index, str(normalized_attempt["target_execution_id"])
    )
    if (
        target is None
        or target["entry_kind"] == "control"
        or target["pending_record_sha256"] is not None
        or normalized_target["phase"] != "QUARANTINED"
        or normalized_target["task_id"] != normalized_attempt["task_id"]
        or normalized_target["execution_id"]
        != normalized_attempt["target_execution_id"]
        or not _digest_equal(
            target["record_sha256"], normalized_target["record_sha256"]
        )
        or not _digest_equal(
            bindings["target_journal_record_sha256"],
            normalized_target["record_sha256"],
        )
        or bindings["expected_journal_revision"]
        != normalized_target["revision"]
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_TARGET_INVALID",
            "reconciliation target is not the exact promoted quarantine",
        )
    execution_id = str(normalized_attempt["attempt_id"])
    if _entry_for(normalized_index, execution_id) is not None:
        raise _error(
            "ACTION_JOURNAL_EXECUTION_EXISTS",
            "reconciliation attempt identity is already indexed",
        )
    digest = str(normalized_attempt["record_sha256"])
    entry = {
        "execution_id": execution_id,
        "entry_kind": "control",
        "target_execution_id": normalized_attempt["target_execution_id"],
        "control_action_id": bindings["recovery_action_id"],
        "concurrency_class": "target-control",
        "scopes": target["scopes"],
        "pending_record_sha256": digest,
        "record_sha256": None,
        "runtime_reservation": None,
    }
    _validate_new_index_entry_conflicts(normalized_index, entry)
    entries = _entries(normalized_index) + [entry]
    entries.sort(key=lambda item: str(item["execution_id"]).encode("utf-8"))
    reserved = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": entries,
        }
    )
    promoted_entries = _entries(reserved)
    for candidate in promoted_entries:
        if candidate["execution_id"] == execution_id:
            candidate["pending_record_sha256"] = None
            candidate["record_sha256"] = digest
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return WriteAheadPlan(
        expected_index=expected_index,
        expected_journal=None,
        reserved_index=reserved,
        journal_bytes=semantic_json_bytes(normalized_attempt),
        promoted_index=promoted,
        journal_record_sha256=digest,
    )


def plan_reconciliation_update(
    index: object,
    current_attempt: object,
    updated_attempt: object,
    *,
    expected_index: CASToken,
    expected_attempt: CASToken,
) -> WriteAheadPlan:
    normalized_index = normalize_index(index)
    current = normalize_reconciliation_attempt(current_attempt)
    updated = normalize_reconciliation_attempt(updated_attempt)
    assert_cas(normalized_index, expected_index)
    assert_cas(current, expected_attempt)
    if (
        current["task_id"] != updated["task_id"]
        or current["attempt_id"] != updated["attempt_id"]
        or current["target_execution_id"] != updated["target_execution_id"]
    ):
        raise _error(
            "ACTION_JOURNAL_IDENTITY_CHANGED",
            "reconciliation update cannot change bound identities",
        )
    if int(updated["revision"]) != int(current["revision"]) + 1:
        raise _error(
            "ACTION_JOURNAL_REVISION_STEP_INVALID",
            "attempt revision must increase by exactly one",
        )
    if not _same_semantic_value(current["bindings"], updated["bindings"]):
        raise _error(
            "ACTION_JOURNAL_IMMUTABLE_BINDING_CHANGED",
            "reconciliation authorization bindings are immutable",
        )
    allowed_attempt_phase = {
        "PREPARED": frozenset({"CLAIMED"}),
        "CLAIMED": (
            _TERMINAL_RECONCILIATION_PHASES
            | {"COMPENSATION_AUTHORIZED"}
        )
        - {"COMPENSATED"},
        "COMPENSATION_AUTHORIZED": frozenset({"COMPENSATED"}),
    }.get(str(current["phase"]))
    if (
        allowed_attempt_phase is None
        or updated["phase"] not in allowed_attempt_phase
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_PHASE_INVALID",
            "reconciliation update is not monotonic",
        )
    if current["outcome"] is not None:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_REPLAY",
            "terminal reconciliation cannot be updated",
        )
    if current["phase"] in {"PREPARED", "CLAIMED"}:
        if (
            current["compensation_authorization"] is not None
            or (
                updated["phase"] != "COMPENSATION_AUTHORIZED"
                and updated["compensation_authorization"] is not None
            )
        ):
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_INVALID",
                "compensation authorization may be introduced only by its explicit phase",
            )
    elif not _same_semantic_value(
        current["compensation_authorization"],
        updated["compensation_authorization"],
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_CHANGED",
            "terminal compensation must retain its exact authorization",
        )
    entry = _entry_for(normalized_index, str(current["attempt_id"]))
    bindings = current["bindings"]
    assert isinstance(bindings, dict)
    target_entry = _entry_for(
        normalized_index, str(current["target_execution_id"])
    )
    if (
        entry is None
        or entry["entry_kind"] != "control"
        or entry["target_execution_id"] != current["target_execution_id"]
        or entry["pending_record_sha256"] is not None
        or not _digest_equal(
            entry["record_sha256"], current["record_sha256"]
        )
    ):
        raise _error(
            "ACTION_JOURNAL_INDEX_RECORD_MISMATCH",
            "index does not point to the expected reconciliation attempt",
        )
    if (
        target_entry is None
        or target_entry["entry_kind"] == "control"
        or target_entry["pending_record_sha256"] is not None
        or not _digest_equal(
            target_entry["record_sha256"],
            bindings["target_journal_record_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_TARGET_INVALID",
            "quarantined target changed while reconciliation was active",
        )
    updated_digest = str(updated["record_sha256"])
    entries = _entries(normalized_index)
    for candidate in entries:
        if candidate["execution_id"] == current["attempt_id"]:
            candidate["pending_record_sha256"] = updated_digest
    reserved = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": entries,
        }
    )
    promoted_entries = _entries(reserved)
    for candidate in promoted_entries:
        if candidate["execution_id"] == current["attempt_id"]:
            candidate["pending_record_sha256"] = None
            candidate["record_sha256"] = updated_digest
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return WriteAheadPlan(
        expected_index=expected_index,
        expected_journal=expected_attempt,
        reserved_index=reserved,
        journal_bytes=semantic_json_bytes(updated),
        promoted_index=promoted,
        journal_record_sha256=updated_digest,
    )


def _normalize_compensation_receipt(
    value: object,
) -> dict[str, object] | None:
    if value is None:
        return None
    receipt = _expect_object(value, "/receipt")
    _expect_exact_fields(
        receipt, _COMPENSATION_RECEIPT_FIELDS, "/receipt"
    )
    core = {
        "execution_id": _expect_path_component(
            receipt["execution_id"], "/receipt/execution_id"
        ),
        "claim_id": _expect_path_component(
            receipt["claim_id"], "/receipt/claim_id"
        ),
        "target_journal_record_sha256": _expect_sha256(
            receipt["target_journal_record_sha256"],
            "/receipt/target_journal_record_sha256",
        ),
        "authorization_record_sha256": _expect_sha256(
            receipt["authorization_record_sha256"],
            "/receipt/authorization_record_sha256",
        ),
        "compensation_plan_sha256": _expect_sha256(
            receipt["compensation_plan_sha256"],
            "/receipt/compensation_plan_sha256",
        ),
        "effect_receipt_sha256": _expect_sha256(
            receipt["effect_receipt_sha256"],
            "/receipt/effect_receipt_sha256",
        ),
        "postcondition_proof_sha256": _expect_sha256(
            receipt["postcondition_proof_sha256"],
            "/receipt/postcondition_proof_sha256",
        ),
    }
    receipt_sha256 = _expect_sha256(
        receipt["receipt_sha256"], "/receipt/receipt_sha256"
    )
    expected = semantic_sha256(COMPENSATION_RECEIPT_DOMAIN, core)
    if not _digest_equal(receipt_sha256, expected):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_RECEIPT_DIGEST_MISMATCH",
            "compensation receipt digest does not match its exact cross-links",
        )
    return {**core, "receipt_sha256": receipt_sha256}


def seal_compensation_receipt(
    core: Mapping[str, object],
) -> dict[str, object]:
    normalized_core = _expect_object(dict(core), "/receipt")
    if "receipt_sha256" in normalized_core:
        raise _error(
            "ACTION_JOURNAL_SELF_DIGEST_FORBIDDEN",
            "compensation receipt core must not include receipt_sha256",
        )
    return _normalize_compensation_receipt(
        {
            **normalized_core,
            "receipt_sha256": semantic_sha256(
                COMPENSATION_RECEIPT_DOMAIN, normalized_core
            ),
        }
    )  # type: ignore[return-value]


def _normalize_compensation_finalization(
    value: object,
) -> dict[str, object] | None:
    if value is None:
        return None
    finalization = _expect_object(value, "/finalization")
    _expect_exact_fields(
        finalization,
        _COMPENSATION_FINALIZATION_FIELDS,
        "/finalization",
    )
    return {
        "compensation_receipt_sha256": _expect_sha256(
            finalization["compensation_receipt_sha256"],
            "/finalization/compensation_receipt_sha256",
        ),
        "recovery_event_sha256": _expect_sha256(
            finalization["recovery_event_sha256"],
            "/finalization/recovery_event_sha256",
        ),
        "task_commit_revision": _expect_revision(
            finalization["task_commit_revision"],
            "/finalization/task_commit_revision",
        ),
        "task_state_sha256": _expect_sha256(
            finalization["task_state_sha256"],
            "/finalization/task_state_sha256",
        ),
        "outbox_sha256": _expect_sha256(
            finalization["outbox_sha256"],
            "/finalization/outbox_sha256",
        ),
        "nonce_consumed": _expect_bool(
            finalization["nonce_consumed"],
            "/finalization/nonce_consumed",
        ),
    }


def _normalize_compensation_bindings(
    value: object,
) -> dict[str, object]:
    bindings = _expect_object(value, "/bindings")
    _expect_exact_fields(
        bindings, _COMPENSATION_BINDING_FIELDS, "/bindings"
    )
    plan = _normalize_compensation_plan(bindings["compensation_plan"])
    plan_digest = _expect_sha256(
        bindings["compensation_plan_sha256"],
        "/bindings/compensation_plan_sha256",
    )
    if not _digest_equal(
        plan_digest, compensation_plan_sha256(plan)
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PLAN_DIGEST_MISMATCH",
            "compensation execution does not bind its exact plan",
        )
    return {
        "target_journal_record_sha256": _expect_sha256(
            bindings["target_journal_record_sha256"],
            "/bindings/target_journal_record_sha256",
        ),
        "authorization_record_sha256": _expect_sha256(
            bindings["authorization_record_sha256"],
            "/bindings/authorization_record_sha256",
        ),
        "compensation_plan": plan,
        "compensation_plan_sha256": plan_digest,
        "dual_approval_sha256": _expect_sha256(
            bindings["dual_approval_sha256"],
            "/bindings/dual_approval_sha256",
        ),
    }


def seal_compensation_execution(
    core: Mapping[str, object],
) -> dict[str, object]:
    return normalize_compensation_execution(
        _seal_unsealed_record(core, domain=COMPENSATION_RECORD_DOMAIN)
    )


def normalize_compensation_execution(
    value: object,
) -> dict[str, object]:
    def normalize(record: Mapping[str, object]) -> dict[str, object]:
        phase = _expect_choice(
            record["phase"],
            _COMPENSATION_EXECUTION_PHASES,
            "/phase",
        )
        claim_id = record["claim_id"]
        if claim_id is not None:
            claim_id = _expect_path_component(claim_id, "/claim_id")
        receipt = _normalize_compensation_receipt(record["receipt"])
        finalization = _normalize_compensation_finalization(
            record["finalization"]
        )
        if phase == "PREPARED" and (
            claim_id is not None
            or receipt is not None
            or finalization is not None
        ):
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_CLAIM_INVALID",
                "prepared compensation cannot contain a claim, receipt, or finalization",
            )
        if phase != "PREPARED" and claim_id is None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_CLAIM_REQUIRED",
                "claimed compensation requires its one-shot claim identity",
            )
        if phase in {"PREPARED", "CLAIMED"} and receipt is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_RECEIPT_INVALID",
                "receipt is allowed only after exact verification",
            )
        if phase in {"RECEIPT_VERIFIED", "COMMITTED"} and receipt is None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_RECEIPT_REQUIRED",
                "verified compensation requires its exact receipt",
            )
        if phase != "COMMITTED" and finalization is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_COMMIT_INVALID",
                "only committed compensation may bind engine finalization",
            )
        if phase == "COMMITTED" and finalization is None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_COMMIT_REQUIRED",
                "committed compensation requires authoritative engine finalization",
            )
        bindings = _normalize_compensation_bindings(record["bindings"])
        if receipt is not None:
            for receipt_field, binding_field in (
                (
                    "target_journal_record_sha256",
                    "target_journal_record_sha256",
                ),
                (
                    "authorization_record_sha256",
                    "authorization_record_sha256",
                ),
                (
                    "compensation_plan_sha256",
                    "compensation_plan_sha256",
                ),
            ):
                if receipt[receipt_field] != bindings[binding_field]:
                    raise _error(
                        "ACTION_JOURNAL_COMPENSATION_RECEIPT_CROSSLINK_INVALID",
                        "compensation receipt differs from an immutable binding",
                        details={"field": receipt_field},
                    )
            if (
                receipt["execution_id"] != record["execution_id"]
                or receipt["claim_id"] != claim_id
            ):
                raise _error(
                    "ACTION_JOURNAL_COMPENSATION_RECEIPT_CROSSLINK_INVALID",
                    "compensation receipt differs from execution or claim",
                )
        if (
            finalization is not None
            and (
                receipt is None
                or not _digest_equal(
                    finalization["compensation_receipt_sha256"],
                    receipt["receipt_sha256"],
                )
            )
        ):
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_COMMIT_INVALID",
                "engine finalization must bind the exact verified compensation receipt",
            )
        return {
            "schema": ACTION_COMPENSATION_EXECUTION_SCHEMA,
            "task_id": _expect_string(
                record["task_id"], "/task_id", identifier=True
            ),
            "execution_id": _expect_path_component(
                record["execution_id"], "/execution_id"
            ),
            "target_execution_id": _expect_path_component(
                record["target_execution_id"],
                "/target_execution_id",
            ),
            "authorization_attempt_id": _expect_path_component(
                record["authorization_attempt_id"],
                "/authorization_attempt_id",
            ),
            "revision": _expect_revision(
                record["revision"], "/revision"
            ),
            "phase": phase,
            "bindings": bindings,
            "claim_id": claim_id,
            "receipt": receipt,
            "finalization": finalization,
            "record_sha256": _expect_sha256(
                record["record_sha256"], "/record_sha256"
            ),
        }

    return _normalize_digest_record(
        value,
        fields=_COMPENSATION_EXECUTION_FIELDS,
        schema=ACTION_COMPENSATION_EXECUTION_SCHEMA,
        domain=COMPENSATION_RECORD_DOMAIN,
        normalizer=normalize,
    )


def new_compensation_execution(
    authorized_attempt: object,
    quarantined_journal: object,
    *,
    manager_secret: str | bytes | None = None,
) -> dict[str, object]:
    attempt = normalize_reconciliation_attempt(authorized_attempt)
    target = normalize_journal(quarantined_journal)
    _require_journal_authenticity(target, manager_secret)
    authorization = attempt["compensation_authorization"]
    if (
        attempt["phase"] != "COMPENSATION_AUTHORIZED"
        or not isinstance(authorization, dict)
        or target["phase"] != "QUARANTINED"
        or attempt["task_id"] != target["task_id"]
        or attempt["target_execution_id"] != target["execution_id"]
        or not _digest_equal(
            attempt["bindings"]["target_journal_record_sha256"],  # type: ignore[index]
            target["record_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_AUTHORIZATION_INVALID",
            "compensation execution requires an exact authorized quarantine",
        )
    return seal_compensation_execution(
        {
            "schema": ACTION_COMPENSATION_EXECUTION_SCHEMA,
            "task_id": target["task_id"],
            "execution_id": authorization[
                "compensation_execution_id"
            ],
            "target_execution_id": target["execution_id"],
            "authorization_attempt_id": attempt["attempt_id"],
            "revision": 0,
            "phase": "PREPARED",
            "bindings": {
                "target_journal_record_sha256": target[
                    "record_sha256"
                ],
                "authorization_record_sha256": attempt[
                    "record_sha256"
                ],
                "compensation_plan": authorization[
                    "compensation_plan"
                ],
                "compensation_plan_sha256": authorization[
                    "compensation_plan_sha256"
                ],
                "dual_approval_sha256": authorization[
                    "dual_approval_sha256"
                ],
            },
            "claim_id": None,
            "receipt": None,
            "finalization": None,
        }
    )


def advance_compensation_execution(
    execution: object,
    new_phase: str,
    *,
    claim_id: str | None = None,
    receipt: object | None = None,
    recovery_event_sha256: str | None = None,
    task_commit_revision: int | None = None,
    task_state_sha256: str | None = None,
    outbox_sha256: str | None = None,
    nonce_consumed: bool = False,
) -> dict[str, object]:
    current = normalize_compensation_execution(execution)
    requested = _expect_choice(
        new_phase, _COMPENSATION_EXECUTION_PHASES, "/new_phase"
    )
    allowed = {
        "PREPARED": "CLAIMED",
        "CLAIMED": "RECEIPT_VERIFIED",
        "RECEIPT_VERIFIED": "COMMITTED",
    }.get(str(current["phase"]))
    if allowed != requested:
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PHASE_INVALID",
            "compensation execution transition is not monotonic",
        )
    updated_claim = current["claim_id"]
    updated_receipt = current["receipt"]
    updated_finalization = current["finalization"]
    if requested == "CLAIMED":
        updated_claim = _expect_path_component(claim_id, "/claim_id")
        if receipt is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_RECEIPT_INVALID",
                "dispatch claim cannot contain a receipt",
            )
    elif requested == "RECEIPT_VERIFIED":
        if claim_id is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_CLAIM_REPLAY",
                "claimed compensation cannot change claim identity",
            )
        updated_receipt = _normalize_compensation_receipt(receipt)
        if updated_receipt is None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_RECEIPT_REQUIRED",
                "receipt verification requires an exact receipt",
            )
    else:
        if claim_id is not None or receipt is not None:
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_COMMIT_INVALID",
                "commit reuses the already verified receipt without new inputs",
            )
        assert isinstance(updated_receipt, dict)
        updated_finalization = {
            "compensation_receipt_sha256": updated_receipt[
                "receipt_sha256"
            ],
            "recovery_event_sha256": _expect_sha256(
                recovery_event_sha256,
                "/recovery_event_sha256",
            ),
            "task_commit_revision": _expect_revision(
                task_commit_revision,
                "/task_commit_revision",
            ),
            "task_state_sha256": _expect_sha256(
                task_state_sha256,
                "/task_state_sha256",
            ),
            "outbox_sha256": _expect_sha256(
                outbox_sha256,
                "/outbox_sha256",
            ),
            "nonce_consumed": _expect_bool(
                nonce_consumed, "/nonce_consumed"
            ),
        }
    return seal_compensation_execution(
        {
            **{
                key: value
                for key, value in current.items()
                if key != "record_sha256"
            },
            "revision": int(current["revision"]) + 1,
            "phase": requested,
            "claim_id": updated_claim,
            "receipt": updated_receipt,
            "finalization": updated_finalization,
        }
    )


def finalize_reconciliation_compensation(
    authorized_attempt: object,
    committed_compensation: object,
) -> dict[str, object]:
    attempt = normalize_reconciliation_attempt(authorized_attempt)
    compensation = normalize_compensation_execution(
        committed_compensation
    )
    authorization = attempt["compensation_authorization"]
    receipt = compensation["receipt"]
    finalization = compensation["finalization"]
    if (
        attempt["phase"] != "COMPENSATION_AUTHORIZED"
        or compensation["phase"] != "COMMITTED"
        or not isinstance(authorization, dict)
        or not isinstance(receipt, dict)
        or not isinstance(finalization, dict)
        or compensation["authorization_attempt_id"]
        != attempt["attempt_id"]
        or compensation["execution_id"]
        != authorization["compensation_execution_id"]
        or compensation["target_execution_id"]
        != attempt["target_execution_id"]
        or not _digest_equal(
            compensation["bindings"]["authorization_record_sha256"],  # type: ignore[index]
            attempt["record_sha256"],
        )
        or not _digest_equal(
            compensation["bindings"]["dual_approval_sha256"],  # type: ignore[index]
            authorization["dual_approval_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_FINALIZATION_INVALID",
            "committed compensation differs from its authorization",
        )
    return advance_reconciliation_attempt(
        attempt,
        "COMPENSATED",
        evidence_sha256=str(receipt["postcondition_proof_sha256"]),
        recovery_event_sha256=str(
            finalization["recovery_event_sha256"]
        ),
        task_commit_revision=int(
            finalization["task_commit_revision"]
        ),
        task_state_sha256=str(
            finalization["task_state_sha256"]
        ),
        outbox_sha256=str(finalization["outbox_sha256"]),
        nonce_consumed=bool(finalization["nonce_consumed"]),
        compensation_execution_id=str(
            compensation["execution_id"]
        ),
        compensation_receipt_sha256=str(
            receipt["receipt_sha256"]
        ),
        dual_approval_sha256=str(
            authorization["dual_approval_sha256"]
        ),
        compensation_authorization_sha256=str(
            attempt["record_sha256"]
        ),
    )


def _plan_control_rotation(
    index: Mapping[str, object],
    *,
    expected_index: CASToken,
    old_execution_id: str,
    old_record_sha256: str,
    new_execution_id: str,
    new_record_sha256: str,
    target_execution_id: str,
    control_action_id: str,
    scopes: Mapping[str, object],
    record_bytes: bytes,
) -> ControlRotationPlan:
    assert_cas(index, expected_index)
    old_entry = _entry_for(index, old_execution_id)
    target_entry = _entry_for(index, target_execution_id)
    if (
        old_entry is None
        or old_entry["entry_kind"] != "control"
        or old_entry["target_execution_id"] != target_execution_id
        or old_entry["pending_record_sha256"] is not None
        or not _digest_equal(
            old_entry["record_sha256"], old_record_sha256
        )
        or target_entry is None
        or target_entry["entry_kind"] == "control"
        or target_entry["pending_record_sha256"] is not None
        or semantic_json_bytes(old_entry["scopes"])
        != semantic_json_bytes(scopes)
    ):
        raise _error(
            "ACTION_JOURNAL_CONTROL_ROTATION_STALE",
            "control rotation requires the exact promoted predecessor and target",
        )
    if (
        new_execution_id == old_execution_id
        or _entry_for(index, new_execution_id) is not None
    ):
        raise _error(
            "ACTION_JOURNAL_CONTROL_ROTATION_ID_INVALID",
            "rotated control requires a fresh execution identity",
        )
    base_entries = [
        entry
        for entry in _entries(index)
        if entry["execution_id"] != old_execution_id
    ]
    base_index = _reseal_index(
        {
            **index,
            "entries": base_entries,
        }
    )
    replacement = {
        "execution_id": new_execution_id,
        "entry_kind": "control",
        "target_execution_id": target_execution_id,
        "control_action_id": control_action_id,
        "concurrency_class": "target-control",
        "scopes": normalize_scopes(scopes),
        "pending_record_sha256": new_record_sha256,
        "record_sha256": None,
        "runtime_reservation": None,
    }
    _validate_new_index_entry_conflicts(base_index, replacement)
    reserved_entries = base_entries + [replacement]
    reserved_entries.sort(
        key=lambda item: str(item["execution_id"]).encode("utf-8")
    )
    reserved = _reseal_index(
        {
            **index,
            "revision": int(index["revision"]) + 1,
            "entries": reserved_entries,
        }
    )
    promoted_entries = _entries(reserved)
    for entry in promoted_entries:
        if entry["execution_id"] == new_execution_id:
            entry["pending_record_sha256"] = None
            entry["record_sha256"] = new_record_sha256
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return ControlRotationPlan(
        expected_index=expected_index,
        old_execution_id=old_execution_id,
        old_record_sha256=old_record_sha256,
        new_execution_id=new_execution_id,
        new_record_sha256=new_record_sha256,
        reserved_index=reserved,
        record_bytes=record_bytes,
        promoted_index=promoted,
    )


def plan_reconciliation_control_rotation(
    index: object,
    old_attempt: object,
    new_attempt: object,
    *,
    target_journal: object,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> ControlRotationPlan:
    normalized_index = normalize_index(index)
    old = normalize_reconciliation_attempt(old_attempt)
    new = normalize_reconciliation_attempt(new_attempt)
    target = normalize_journal(target_journal)
    _require_journal_authenticity(target, manager_secret)
    bindings = new["bindings"]
    old_bindings = old["bindings"]
    assert isinstance(bindings, dict)
    assert isinstance(old_bindings, dict)
    reused_fresh_fact = any(
        _digest_equal(bindings[field], old_bindings[field])
        for field in (
            "authorization_sha256",
            "gate_sha256",
            "request_nonce_sha256",
            "engine_proof_sha256",
        )
    )
    if (
        old["phase"] != "UNRESOLVED"
        or new["phase"] != "PREPARED"
        or reused_fresh_fact
        or old["task_id"] != new["task_id"]
        or old["target_execution_id"] != new["target_execution_id"]
        or new["target_execution_id"] != target["execution_id"]
        or target["phase"] != "QUARANTINED"
        or not _digest_equal(
            old["bindings"]["target_journal_record_sha256"],  # type: ignore[index]
            target["record_sha256"],
        )
        or not _digest_equal(
            bindings["target_journal_record_sha256"],
            target["record_sha256"],
        )
        or bindings["expected_index_revision"]
        != normalized_index["revision"]
        or not _digest_equal(
            bindings["expected_index_sha256"],
            normalized_index["record_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_ROTATION_INVALID",
            "fresh reconciliation must replace one exact unresolved control",
        )
    target_entry = _entry_for(
        normalized_index, str(target["execution_id"])
    )
    if target_entry is None:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_TARGET_INVALID",
            "rotation target is not indexed",
        )
    return _plan_control_rotation(
        normalized_index,
        expected_index=expected_index,
        old_execution_id=str(old["attempt_id"]),
        old_record_sha256=str(old["record_sha256"]),
        new_execution_id=str(new["attempt_id"]),
        new_record_sha256=str(new["record_sha256"]),
        target_execution_id=str(target["execution_id"]),
        control_action_id=str(bindings["recovery_action_id"]),
        scopes=target_entry["scopes"],  # type: ignore[arg-type]
        record_bytes=semantic_json_bytes(new),
    )


def plan_compensation_control_rotation(
    index: object,
    authorized_attempt: object,
    compensation_execution: object,
    *,
    target_journal: object,
    expected_index: CASToken,
    manager_secret: str | bytes | None = None,
) -> ControlRotationPlan:
    normalized_index = normalize_index(index)
    attempt = normalize_reconciliation_attempt(authorized_attempt)
    compensation = normalize_compensation_execution(
        compensation_execution
    )
    target = normalize_journal(target_journal)
    _require_journal_authenticity(target, manager_secret)
    authorization = attempt["compensation_authorization"]
    bindings = compensation["bindings"]
    if (
        attempt["phase"] != "COMPENSATION_AUTHORIZED"
        or compensation["phase"] != "PREPARED"
        or not isinstance(authorization, dict)
        or compensation["task_id"] != attempt["task_id"]
        or compensation["target_execution_id"]
        != attempt["target_execution_id"]
        or compensation["authorization_attempt_id"]
        != attempt["attempt_id"]
        or compensation["execution_id"]
        != authorization["compensation_execution_id"]
        or target["phase"] != "QUARANTINED"
        or target["execution_id"] != attempt["target_execution_id"]
        or not _digest_equal(
            bindings["target_journal_record_sha256"],  # type: ignore[index]
            target["record_sha256"],
        )
        or not _digest_equal(
            bindings["authorization_record_sha256"],  # type: ignore[index]
            attempt["record_sha256"],
        )
        or not _digest_equal(
            bindings["compensation_plan_sha256"],  # type: ignore[index]
            authorization["compensation_plan_sha256"],
        )
        or not _digest_equal(
            bindings["dual_approval_sha256"],  # type: ignore[index]
            authorization["dual_approval_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_ROTATION_INVALID",
            "compensation control differs from its exact authorization",
        )
    target_entry = _entry_for(
        normalized_index, str(target["execution_id"])
    )
    if target_entry is None:
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_TARGET_INVALID",
            "compensation target is not indexed",
        )
    plan = authorization["compensation_plan"]
    assert isinstance(plan, dict)
    return _plan_control_rotation(
        normalized_index,
        expected_index=expected_index,
        old_execution_id=str(attempt["attempt_id"]),
        old_record_sha256=str(attempt["record_sha256"]),
        new_execution_id=str(compensation["execution_id"]),
        new_record_sha256=str(compensation["record_sha256"]),
        target_execution_id=str(target["execution_id"]),
        control_action_id=str(plan["action_id"]),
        scopes=target_entry["scopes"],  # type: ignore[arg-type]
        record_bytes=semantic_json_bytes(compensation),
    )


def plan_compensation_update(
    index: object,
    current_execution: object,
    updated_execution: object,
    *,
    expected_index: CASToken,
    expected_execution: CASToken,
) -> WriteAheadPlan:
    normalized_index = normalize_index(index)
    current = normalize_compensation_execution(current_execution)
    updated = normalize_compensation_execution(updated_execution)
    assert_cas(normalized_index, expected_index)
    assert_cas(current, expected_execution)
    if (
        current["task_id"] != updated["task_id"]
        or current["execution_id"] != updated["execution_id"]
        or current["target_execution_id"]
        != updated["target_execution_id"]
        or current["authorization_attempt_id"]
        != updated["authorization_attempt_id"]
        or not _same_semantic_value(
            current["bindings"], updated["bindings"]
        )
        or int(updated["revision"]) != int(current["revision"]) + 1
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_UPDATE_INVALID",
            "compensation update changed immutable facts",
        )
    allowed = {
        "PREPARED": "CLAIMED",
        "CLAIMED": "RECEIPT_VERIFIED",
        "RECEIPT_VERIFIED": "COMMITTED",
    }.get(str(current["phase"]))
    if allowed != updated["phase"]:
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_PHASE_INVALID",
            "compensation update is not monotonic",
        )
    entry = _entry_for(
        normalized_index, str(current["execution_id"])
    )
    target = _entry_for(
        normalized_index, str(current["target_execution_id"])
    )
    if (
        entry is None
        or entry["entry_kind"] != "control"
        or entry["target_execution_id"]
        != current["target_execution_id"]
        or entry["pending_record_sha256"] is not None
        or not _digest_equal(
            entry["record_sha256"], current["record_sha256"]
        )
        or target is None
        or target["pending_record_sha256"] is not None
        or not _digest_equal(
            target["record_sha256"],
            current["bindings"][
                "target_journal_record_sha256"
            ],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_INDEX_MISMATCH",
            "index does not point to the exact compensation and target",
        )
    updated_digest = str(updated["record_sha256"])
    reserved_entries = _entries(normalized_index)
    for candidate in reserved_entries:
        if candidate["execution_id"] == current["execution_id"]:
            candidate["pending_record_sha256"] = updated_digest
    reserved = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": reserved_entries,
        }
    )
    promoted_entries = _entries(reserved)
    for candidate in promoted_entries:
        if candidate["execution_id"] == current["execution_id"]:
            candidate["pending_record_sha256"] = None
            candidate["record_sha256"] = updated_digest
    promoted = _reseal_index(
        {
            **reserved,
            "revision": int(reserved["revision"]) + 1,
            "entries": promoted_entries,
        }
    )
    return WriteAheadPlan(
        expected_index=expected_index,
        expected_journal=expected_execution,
        reserved_index=reserved,
        journal_bytes=semantic_json_bytes(updated),
        promoted_index=promoted,
        journal_record_sha256=updated_digest,
    )


def plan_archive(
    journal: object,
    *,
    reconciliation_attempt: object | None = None,
    manager_secret: str | bytes | None = None,
) -> ArchivePlan:
    normalized = normalize_journal(journal)
    _require_journal_authenticity(normalized, manager_secret)
    if normalized["phase"] not in {"COMMITTED", "QUARANTINED"}:
        raise _error(
            "ACTION_JOURNAL_ARCHIVE_PHASE_INVALID",
            "only committed or reconciled quarantined journal can be archived",
        )
    if normalized["phase"] == "QUARANTINED":
        if reconciliation_attempt is None:
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_REQUIRED",
                "quarantined journal cannot be archived before a closing reconciliation decision",
            )
        attempt = normalize_reconciliation_attempt(reconciliation_attempt)
        if (
            attempt["phase"] not in _CLOSING_RECONCILIATION_PHASES
            or attempt["target_execution_id"] != normalized["execution_id"]
            or not _digest_equal(
                attempt["bindings"]["target_journal_record_sha256"],  # type: ignore[index]
                normalized["record_sha256"],
            )
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_INVALID",
                "archive plan is not bound to a closing reconciliation decision",
            )
    elif reconciliation_attempt is not None:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_UNEXPECTED",
            "committed journal archive does not use reconciliation",
        )
    return ArchivePlan(
        execution_id=str(normalized["execution_id"]),
        record_sha256=str(normalized["record_sha256"]),
        archive_bytes=semantic_json_bytes(normalized),
    )


def plan_index_closure(
    index: object,
    journal: object,
    archive_bytes: bytes,
    *,
    expected_index: CASToken,
    authoritative_event_sha256: str,
    containment_records: Sequence[object],
    reconciliation_attempt: object | None = None,
    runtime_reservation: object | None = None,
    manager_secret: str | bytes | None = None,
) -> IndexClosurePlan:
    normalized_index = normalize_index(index)
    normalized_journal = normalize_journal(journal)
    _require_journal_authenticity(normalized_journal, manager_secret)
    assert_cas(normalized_index, expected_index)
    expected_archive = semantic_json_bytes(normalized_journal)
    if not isinstance(archive_bytes, bytes) or not hmac.compare_digest(
        archive_bytes, expected_archive
    ):
        raise _error(
            "ACTION_JOURNAL_ARCHIVE_MISMATCH",
            "durable archive bytes must exactly match the terminal journal",
        )
    _expect_sha256(
        authoritative_event_sha256, "/authoritative_event_sha256"
    )
    entry = _entry_for(
        normalized_index, str(normalized_journal["execution_id"])
    )
    if (
        entry is None
        or entry["pending_record_sha256"] is not None
        or not _digest_equal(
            entry["record_sha256"],
            normalized_journal["record_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_INDEX_RECORD_MISMATCH",
            "index must point at the exact terminal journal before closure",
        )
    containments = [
        normalize_containment(record) for record in containment_records
    ]
    effect_ids = {
        str(effect["effect_id"])
        for effect in normalized_journal["effects"]  # type: ignore[union-attr]
    }
    containment_ids = {
        str(record["effect_id"]) for record in containments
    }
    if effect_ids != containment_ids:
        raise _error(
            "ACTION_JOURNAL_CONTAINMENT_SET_MISMATCH",
            "terminal closure requires one linked containment per effect",
        )
    for record in containments:
        linked_effect = next(
            effect
            for effect in normalized_journal["effects"]  # type: ignore[union-attr]
            if effect["effect_id"] == record["effect_id"]
        )
        if (
            record["task_id"] != normalized_journal["task_id"]
            or record["execution_id"] != normalized_journal["execution_id"]
            or record["claim_id"] != linked_effect["claim_id"]
            or record["attempt_id"] != linked_effect["attempt_id"]
            or not _digest_equal(
                record["record_sha256"],
                linked_effect["containment_record_sha256"],
            )
            or record["phase"] not in {"CLOSED", "HANDOFF_VERIFIED"}
        ):
            raise _error(
                "ACTION_JOURNAL_CONTAINMENT_UNSETTLED",
                "containment must be closed or validly handed off",
            )
    reconciliation_attempt_id: str | None = None
    reconciliation_outcome: dict[str, object] | None = None
    if normalized_journal["phase"] == "QUARANTINED":
        if reconciliation_attempt is None:
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_REQUIRED",
                "quarantined journal requires a terminal reconciliation attempt",
            )
        attempt = normalize_reconciliation_attempt(reconciliation_attempt)
        if (
            attempt["target_execution_id"]
            != normalized_journal["execution_id"]
            or not _digest_equal(
                attempt["bindings"]["target_journal_record_sha256"],  # type: ignore[index]
                normalized_journal["record_sha256"],
            )
            or attempt["phase"] not in _CLOSING_RECONCILIATION_PHASES
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_INVALID",
                "attempt does not authorize closure of this quarantine",
            )
        outcome = attempt["outcome"]
        assert isinstance(outcome, dict)
        reconciliation_attempt_id = str(attempt["attempt_id"])
        reconciliation_outcome = outcome
        if not _digest_equal(
            outcome["recovery_event_sha256"],
            authoritative_event_sha256,
        ):
            raise _error(
                "ACTION_JOURNAL_EVENT_MISMATCH",
                "authoritative recovery event does not match reconciliation",
            )
        attempt_entry = _entry_for(
            normalized_index, str(attempt["attempt_id"])
        )
        if (
            attempt_entry is None
            or attempt_entry["entry_kind"] != "control"
            or attempt_entry["target_execution_id"]
            != normalized_journal["execution_id"]
            or attempt_entry["pending_record_sha256"] is not None
            or not _digest_equal(
                attempt_entry["record_sha256"], attempt["record_sha256"]
            )
        ):
            raise _error(
                "ACTION_JOURNAL_RECONCILIATION_INDEX_MISMATCH",
                "terminal reconciliation attempt must remain exactly indexed",
            )
    elif reconciliation_attempt is not None:
        raise _error(
            "ACTION_JOURNAL_RECONCILIATION_UNEXPECTED",
            "committed journal closure does not use quarantine reconciliation",
        )
    elif (
        not isinstance(normalized_journal["finalization"], dict)
        or not _digest_equal(
            normalized_journal["finalization"]["event_sha256"],
            authoritative_event_sha256,
        )
    ):
        raise _error(
            "ACTION_JOURNAL_EVENT_MISMATCH",
            "authoritative task event does not match journal finalization",
        )
    entries = _entries(normalized_index)
    if runtime_reservation is None:
        if any(record["phase"] != "CLOSED" for record in containments):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_REQUIRED",
                "handed-off containment requires a runtime reservation",
            )
        entries = [
            candidate
            for candidate in entries
            if candidate["execution_id"]
            not in {
                normalized_journal["execution_id"],
                reconciliation_attempt_id,
            }
        ]
        if (
            reconciliation_outcome is not None
            and reconciliation_outcome["runtime_reservation_sha256"]
            is not None
        ):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "reconciliation outcome names a runtime reservation that was not promoted",
            )
        mode = "REMOVE"
    else:
        reservation = normalize_runtime_reservation(runtime_reservation)
        if (
            reservation["task_id"] != normalized_journal["task_id"]
            or reservation["execution_id"]
            != normalized_journal["execution_id"]
            or not scopes_subset(
                reservation["scopes"], entry["scopes"]
            )
        ):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "runtime reservation does not bind the archived execution",
            )
        if not any(
            record["phase"] == "HANDOFF_VERIFIED"
            and _digest_equal(
                record["record_sha256"],
                reservation["containment_record_sha256"],
            )
            for record in containments
        ):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "reservation must bind a handed-off containment record",
            )
        if reconciliation_outcome is not None and not _digest_equal(
            reconciliation_outcome["runtime_reservation_sha256"],
            reservation["record_sha256"],
        ):
            raise _error(
                "ACTION_JOURNAL_RUNTIME_RESERVATION_INVALID",
                "reconciliation outcome must bind the exact promoted reservation",
            )
        for candidate in entries:
            if candidate["execution_id"] == normalized_journal["execution_id"]:
                candidate.update(
                    {
                        "entry_kind": "runtime-reservation",
                        "target_execution_id": None,
                        "control_action_id": None,
                        "pending_record_sha256": None,
                        "record_sha256": None,
                        "runtime_reservation": reservation,
                    }
                )
        if reconciliation_attempt_id is not None:
            entries = [
                candidate
                for candidate in entries
                if candidate["execution_id"] != reconciliation_attempt_id
            ]
        mode = "PROMOTE_RUNTIME_RESERVATION"
    closed_index = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": entries,
        }
    )
    return IndexClosurePlan(
        expected_index=expected_index,
        index=closed_index,
        mode=mode,
    )


def plan_compensation_index_closure(
    index: object,
    quarantined_journal: object,
    target_archive_bytes: bytes,
    terminal_reconciliation: object,
    reconciliation_archive_bytes: bytes,
    committed_compensation: object,
    compensation_archive_bytes: bytes,
    *,
    expected_index: CASToken,
    containment_records: Sequence[object],
    manager_secret: str | bytes | None = None,
) -> IndexClosurePlan:
    normalized_index = normalize_index(index)
    target = normalize_journal(quarantined_journal)
    reconciliation = normalize_reconciliation_attempt(
        terminal_reconciliation
    )
    compensation = normalize_compensation_execution(
        committed_compensation
    )
    _require_journal_authenticity(target, manager_secret)
    assert_cas(normalized_index, expected_index)
    for supplied, expected, role in (
        (
            target_archive_bytes,
            semantic_json_bytes(target),
            "target",
        ),
        (
            reconciliation_archive_bytes,
            semantic_json_bytes(reconciliation),
            "reconciliation",
        ),
        (
            compensation_archive_bytes,
            semantic_json_bytes(compensation),
            "compensation",
        ),
    ):
        if not isinstance(supplied, bytes) or not hmac.compare_digest(
            supplied, expected
        ):
            raise _error(
                "ACTION_JOURNAL_COMPENSATION_ARCHIVE_MISMATCH",
                "compensation closure requires exact durable archive bytes",
                details={"role": role},
            )
    target_entry = _entry_for(
        normalized_index, str(target["execution_id"])
    )
    compensation_entry = _entry_for(
        normalized_index, str(compensation["execution_id"])
    )
    outcome = reconciliation["outcome"]
    authorization = reconciliation["compensation_authorization"]
    receipt = compensation["receipt"]
    finalization = compensation["finalization"]
    compensation_bindings = compensation["bindings"]
    if (
        target["phase"] != "QUARANTINED"
        or reconciliation["phase"] != "COMPENSATED"
        or compensation["phase"] != "COMMITTED"
        or not isinstance(outcome, dict)
        or not isinstance(authorization, dict)
        or not isinstance(receipt, dict)
        or not isinstance(finalization, dict)
        or target_entry is None
        or target_entry["pending_record_sha256"] is not None
        or not _digest_equal(
            target_entry["record_sha256"], target["record_sha256"]
        )
        or compensation_entry is None
        or compensation_entry["entry_kind"] != "control"
        or compensation_entry["target_execution_id"]
        != target["execution_id"]
        or compensation_entry["pending_record_sha256"] is not None
        or not _digest_equal(
            compensation_entry["record_sha256"],
            compensation["record_sha256"],
        )
        or reconciliation["target_execution_id"]
        != target["execution_id"]
        or compensation["target_execution_id"]
        != target["execution_id"]
        or reconciliation["attempt_id"]
        != compensation["authorization_attempt_id"]
        or outcome["compensation_execution_id"]
        != compensation["execution_id"]
        or not _digest_equal(
            outcome["compensation_receipt_sha256"],
            receipt["receipt_sha256"],
        )
        or not _digest_equal(
            outcome["dual_approval_sha256"],
            authorization["dual_approval_sha256"],
        )
        or not _digest_equal(
            outcome["compensation_authorization_sha256"],
            compensation_bindings["authorization_record_sha256"],  # type: ignore[index]
        )
        or not _digest_equal(
            compensation_bindings["target_journal_record_sha256"],  # type: ignore[index]
            target["record_sha256"],
        )
        or outcome["task_commit_revision"]
        != finalization["task_commit_revision"]
        or outcome["task_state_sha256"]
        != finalization["task_state_sha256"]
        or outcome["outbox_sha256"]
        != finalization["outbox_sha256"]
        or outcome["recovery_event_sha256"]
        != finalization["recovery_event_sha256"]
        or outcome["nonce_consumed"]
        != finalization["nonce_consumed"]
        or not _digest_equal(
            finalization["compensation_receipt_sha256"],
            receipt["receipt_sha256"],
        )
    ):
        raise _error(
            "ACTION_JOURNAL_COMPENSATION_CLOSURE_INVALID",
            "target, authorization, receipt, proof, outbox, or index cross-link differs",
        )
    containments = [
        normalize_containment(record) for record in containment_records
    ]
    effects = target["effects"]
    assert isinstance(effects, list)
    if {
        str(item["effect_id"]) for item in effects
    } != {
        str(item["effect_id"]) for item in containments
    }:
        raise _error(
            "ACTION_JOURNAL_CONTAINMENT_SET_MISMATCH",
            "compensation closure requires every target containment",
        )
    for containment in containments:
        effect = next(
            item
            for item in effects
            if item["effect_id"] == containment["effect_id"]
        )
        if (
            containment["phase"] != "CLOSED"
            or containment["task_id"] != target["task_id"]
            or containment["execution_id"] != target["execution_id"]
            or containment["record_sha256"]
            != effect["containment_record_sha256"]
        ):
            raise _error(
                "ACTION_JOURNAL_CONTAINMENT_UNSETTLED",
                "compensation closure requires exact closed containment",
            )
    retained = [
        entry
        for entry in _entries(normalized_index)
        if entry["execution_id"]
        not in {
            target["execution_id"],
            compensation["execution_id"],
        }
    ]
    closed = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": retained,
        }
    )
    return IndexClosurePlan(
        expected_index=expected_index,
        index=closed,
        mode="COMPENSATED",
    )


def plan_runtime_reservation_release(
    index: object,
    execution_id: str,
    *,
    expected_index: CASToken,
    authenticated_exit_or_quiescence_sha256: str,
    result_or_cancellation_event_sha256: str,
) -> IndexClosurePlan:
    normalized_index = normalize_index(index)
    assert_cas(normalized_index, expected_index)
    _expect_sha256(
        authenticated_exit_or_quiescence_sha256,
        "/authenticated_exit_or_quiescence_sha256",
    )
    _expect_sha256(
        result_or_cancellation_event_sha256,
        "/result_or_cancellation_event_sha256",
    )
    target = _entry_for(
        normalized_index,
        _expect_path_component(execution_id, "/execution_id"),
    )
    if target is None or target["entry_kind"] != "runtime-reservation":
        raise _error(
            "ACTION_JOURNAL_RUNTIME_RESERVATION_MISSING",
            "runtime reservation is not active",
        )
    entries = [
        entry
        for entry in _entries(normalized_index)
        if entry["execution_id"] != execution_id
    ]
    released = _reseal_index(
        {
            **normalized_index,
            "revision": int(normalized_index["revision"]) + 1,
            "entries": entries,
        }
    )
    return IndexClosurePlan(
        expected_index=expected_index,
        index=released,
        mode="RELEASE_RUNTIME_RESERVATION",
    )


def orphan_active_matches_archive(
    active_bytes: bytes,
    archive_bytes: bytes,
) -> bool:
    if not isinstance(active_bytes, bytes) or not isinstance(
        archive_bytes, bytes
    ):
        return False
    return hmac.compare_digest(active_bytes, archive_bytes)


__all__ = [
    "ACTION_COMPENSATION_EXECUTION_SCHEMA",
    "ACTION_COMPENSATION_PLAN_SCHEMA",
    "ACTION_EFFECT_CONTAINMENT_SCHEMA",
    "ACTION_EXECUTION_INDEX_SCHEMA",
    "ACTION_EXECUTION_INDEX_PATH",
    "ACTION_EXECUTION_JOURNAL_SCHEMA",
    "ACTION_EXECUTION_LOCK_ORDER",
    "ACTION_RECONCILIATION_ATTEMPT_SCHEMA",
    "ACTION_RUNTIME_RESERVATION_SCHEMA",
    "ActionExecutionJournalError",
    "ArchivePlan",
    "CASToken",
    "ControlRotationPlan",
    "EffectClaimPlan",
    "IndexClosurePlan",
    "RecoveryDisposition",
    "WriteAheadPlan",
    "action_compensation_active_path",
    "action_compensation_archive_path",
    "action_effect_containment_path",
    "action_execution_active_path",
    "action_execution_archive_path",
    "action_reconciliation_attempt_path",
    "action_reconciliation_archive_path",
    "action_reconciliation_rotation_path",
    "advance_compensation_execution",
    "advance_containment",
    "advance_effect_phase",
    "advance_global_settlement",
    "advance_reconciliation_attempt",
    "authorize_reconciliation_compensation",
    "assert_cas",
    "assert_journal_promoted",
    "cas_token",
    "commit_journal",
    "compensation_plan_sha256",
    "derive_execution_key",
    "engine_proof_mac",
    "finalize_reconciliation_compensation",
    "index_record_sha256",
    "journal_record_sha256",
    "journal_seal",
    "new_containment",
    "new_compensation_execution",
    "new_index",
    "new_reconciliation_attempt",
    "new_runtime_reservation",
    "normalize_containment",
    "normalize_compensation_execution",
    "normalize_compensation_plan",
    "normalize_index",
    "normalize_journal",
    "normalize_lock_claims",
    "normalize_reconciliation_attempt",
    "normalize_runtime_reservation",
    "normalize_scopes",
    "orphan_active_matches_archive",
    "parse_semantic_json",
    "plan_archive",
    "plan_compensation_control_rotation",
    "plan_compensation_index_closure",
    "plan_compensation_update",
    "plan_effect_claim",
    "plan_index_closure",
    "plan_initial_write",
    "plan_journal_update",
    "plan_reconciliation_initial_write",
    "plan_reconciliation_control_rotation",
    "plan_reconciliation_update",
    "plan_runtime_reservation_release",
    "quarantine_journal",
    "reconciliation_eligibility",
    "recover_pending_promotion",
    "recovery_disposition",
    "required_lock_claims",
    "revision_revalidation_disposition",
    "runtime_binding_sha256",
    "scopes_overlap",
    "scopes_subset",
    "seal_containment",
    "seal_compensation_execution",
    "seal_compensation_receipt",
    "seal_index",
    "seal_journal",
    "seal_reconciliation_attempt",
    "seal_runtime_reservation",
    "semantic_json_bytes",
    "semantic_sha256",
    "u64be",
    "verify_engine_proof_mac",
    "verify_journal_seal",
    "verify_receipt_intent",
]
