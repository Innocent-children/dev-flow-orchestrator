# Loaded by scripts/dev_flow.py only after orchestration integration is ready.
# This fragment is deliberately pure: task locking, artifact persistence,
# durable events, runtime control, filesystem observation, and Git inspection
# remain controller or host-adapter responsibilities.
from __future__ import annotations

import hashlib
import hmac
import json
import re
import struct
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Sequence


ORCHESTRATION_NODE_RESULT_SCHEMA = "dev-flow-node-result/v1"
NODE_RESULT_EXPECTATION_SCHEMA = "dev-flow-node-result-expectation/v1"
NODE_RESULT_VERIFIED_OUTPUT_SCHEMA = (
    "dev-flow-node-result-verified-output/v1"
)
RESULT_BARRIER_SCHEMA = "dev-flow-result-barrier/v1"
RESULT_BARRIER_AGGREGATE_SCHEMA = (
    "dev-flow-result-barrier-aggregate/v1"
)
RESULT_BARRIER_CURRENT_MEMBER_SCHEMA = (
    "dev-flow-result-barrier-current-member/v1"
)
ACCEPTED_NODE_RESULT_SCHEMA = "dev-flow-accepted-node-result/v1"
RUNTIME_LEASE_STATE_SCHEMA = "dev-flow-runtime-lease-state/v1"
WORKTREE_POSTCONDITION_SCHEMA = (
    "dev-flow-worktree-postcondition/v1"
)
RUNTIME_STOP_OBSERVATION_SCHEMA = (
    "dev-flow-runtime-stop-observation/v1"
)
RUNTIME_RECOVERY_OBSERVATION_SCHEMA = (
    "dev-flow-runtime-recovery-observation/v1"
)
LEASE_QUIESCENCE_PROOF_SCHEMA = (
    "dev-flow-lease-quiescence-proof/v1"
)

NODE_RESULT_DOMAIN = b"dev-flow-node-result-v1\x00"
RESULT_BARRIER_DOMAIN = b"dev-flow-result-barrier-v1\x00"
LEASE_QUIESCENCE_DOMAIN = b"dev-flow-lease-quiescence-v1\x00"

# This is kernel policy, not bundle or ordinary configuration.  A caller may
# request a longer interval but cannot lower this positive floor.
KERNEL_MINIMUM_STABILITY_NS = 1_000_000_000
NODE_RESULT_BUDGET = 2048
NODE_RESULT_SUMMARY_BUDGET = 512

_orchestration_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_orchestration_stable_id_re = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$"
)
_orchestration_node_result_id_re = re.compile(
    r"^node-result-[0-9a-f]{64}$"
)
_orchestration_content_addressed_id_re = re.compile(
    r"^[A-Za-z][A-Za-z0-9._-]{0,63}:[0-9a-f]{64}$"
)
_orchestration_signed_int64_max = 2**63 - 1
_orchestration_signed_int64_min = -(2**63)

_orchestration_result_outcomes = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
    }
)
_orchestration_barrier_outcomes = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
    }
)
_orchestration_lease_statuses = frozenset(
    {
        "ACTIVE",
        "REVOCATION_REQUESTED",
        "REVOKED",
        "EXPIRED",
        "ORPHANED",
        "QUIESCED",
    }
)
_orchestration_terminal_lease_statuses = frozenset(
    {"REVOKED", "EXPIRED", "ORPHANED", "QUIESCED"}
)

_orchestration_node_result_fields = frozenset(
    {
        "schema",
        "result_id",
        "task_id",
        "workflow_bundle_sha256",
        "map_epoch",
        "repository_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "lease_nonce",
        "input_sha256",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
        "outcome",
        "summary",
        "blockers",
        "plan_drift",
        "artifact_refs",
        "evidence_refs",
        "runtime_handle",
    }
)
_orchestration_compact_ref_fields = frozenset(
    {
        "id",
        "semantic_sha256",
        "sha256",
        "size",
        "kind",
        "locator",
    }
)
_orchestration_plan_drift_fields = frozenset(
    {"detected", "reasons"}
)
_orchestration_expectation_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "plan_artifact_sha256",
        "dag_sha256",
        "semantic_input_sha256",
        "map_epoch",
        "repository_id",
        "repository_identity_sha256",
        "node_instance_id",
        "attempt",
        "assignment_revision",
        "assignment_id",
        "assignment_sha256",
        "lease_id",
        "lease_nonce",
        "input_sha256",
        "interface_contract_sha256",
        "input_worktree_fingerprint_sha256",
        "actor_id",
        "host_assignment_id",
        "runtime_handle_id",
        "lease_active",
    }
)
_orchestration_verified_output_fields = frozenset(
    {
        "schema",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
        "artifacts",
        "evidence",
    }
)
_orchestration_verified_evidence_fields = frozenset(
    {
        "sha256",
        "semantic_sha256",
        "size",
        "kind",
        "locator",
        "current",
    }
)
_orchestration_history_entry_fields = frozenset(
    {"result", "receipt"}
)
_orchestration_barrier_fields = frozenset(
    {
        "schema",
        "barrier_id",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "map_epoch",
        "node_instance_id",
        "members",
    }
)
_orchestration_barrier_member_fields = frozenset(
    {
        "node_instance_id",
        "repository_id",
        "required",
        "allowed_outcomes",
    }
)
_orchestration_accepted_result_fields = frozenset(
    {
        "schema",
        "accepted",
        "current",
        "repository_evidence_sha256",
        "lease_quiesced",
        "runtime_live",
        "result",
    }
)
_orchestration_barrier_aggregate_fields = frozenset(
    {
        "schema",
        "barrier_sha256",
        "barrier_id",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "map_epoch",
        "node_instance_id",
        "members",
    }
)
_orchestration_barrier_aggregate_member_fields = frozenset(
    {
        "node_instance_id",
        "repository_id",
        "result_id",
        "outcome",
        "input_sha256",
        "output_sha256",
        "repository_evidence_sha256",
        "worktree_sha256",
        "artifact_refs",
        "evidence_refs",
    }
)


class OrchestrationResultError(ValueError):
    """Stable structured blocker from the pure orchestration boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
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


class _OrchestrationJsonSemanticError(Exception):
    def __init__(
        self,
        code: str,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class NodeResultAcceptanceCandidate:
    disposition: str
    result_id: str
    content_sha256: str
    expected_revision: int
    candidate_revision: int
    result: Mapping[str, object]
    prior_receipt: Optional[Mapping[str, object]]


@dataclass(frozen=True)
class BarrierMemberBlocker:
    node_instance_id: str
    repository_id: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class BarrierEvaluation:
    status: str
    blockers: tuple[BarrierMemberBlocker, ...]
    current_results: tuple[Mapping[str, object], ...]
    aggregate: Optional[Mapping[str, object]]
    invalidated_node_instance_ids: tuple[str, ...]
    dependent_result_ids_to_invalidate: tuple[str, ...]


def _orchestration_error(
    code: str,
    message: str,
    *,
    pointer: str = "/",
    details: Optional[Mapping[str, object]] = None,
) -> OrchestrationResultError:
    error_details = {"pointer": pointer}
    error_details.update(details or {})
    return OrchestrationResultError(
        code, message, details=error_details
    )


def _orchestration_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _orchestration_utf8_key(value: str) -> bytes:
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _orchestration_error(
            "ORCHESTRATION_UNICODE_INVALID",
            "identifiers must be valid UTF-8",
            details={"value": repr(value)},
        ) from exc


def _orchestration_u64be(value: int) -> bytes:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value < 2**64
    ):
        raise _orchestration_error(
            "ORCHESTRATION_U64_INVALID",
            "value does not fit U64BE",
            details={"value": value if isinstance(value, int) else None},
        )
    return struct.pack(">Q", value)


def _orchestration_parse_integer(literal: str) -> int:
    negative = literal.startswith("-")
    digits = literal[1:] if negative else literal
    limit = "9223372036854775808" if negative else "9223372036854775807"
    if len(digits) > len(limit) or (
        len(digits) == len(limit) and digits > limit
    ):
        raise _OrchestrationJsonSemanticError(
            "ORCHESTRATION_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    return int(literal)


def _orchestration_reject_float(literal: str) -> object:
    raise _OrchestrationJsonSemanticError(
        "ORCHESTRATION_FLOAT_FORBIDDEN",
        {"literal": literal[:80]},
    )


def _orchestration_reject_constant(literal: str) -> object:
    raise _OrchestrationJsonSemanticError(
        "ORCHESTRATION_NONFINITE_FORBIDDEN",
        {"literal": literal},
    )


def _orchestration_strict_object(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _OrchestrationJsonSemanticError(
                "ORCHESTRATION_DUPLICATE_KEY",
                {"key": key},
            )
        result[key] = value
    return result


def _orchestration_validate_json(
    value: object,
    pointer: str = "",
) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not (
            _orchestration_signed_int64_min
            <= value
            <= _orchestration_signed_int64_max
        ):
            raise _orchestration_error(
                "ORCHESTRATION_INTEGER_OUT_OF_RANGE",
                "JSON integers must fit the signed 64-bit range",
                pointer=pointer or "/",
            )
        return
    if isinstance(value, float):
        raise _orchestration_error(
            "ORCHESTRATION_FLOAT_FORBIDDEN",
            "floating-point values are forbidden",
            pointer=pointer or "/",
        )
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _orchestration_error(
                "ORCHESTRATION_UNICODE_INVALID",
                "strings must be valid UTF-8",
                pointer=pointer or "/",
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise _orchestration_error(
                "ORCHESTRATION_STRING_NOT_NFC",
                "strings must use Unicode NFC",
                pointer=pointer or "/",
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _orchestration_error(
                    "ORCHESTRATION_KEY_INVALID",
                    "object keys must be strings",
                    pointer=pointer or "/",
                )
            child_pointer = (
                f"{pointer}/{_orchestration_pointer_segment(key)}"
            )
            _orchestration_validate_json(key, child_pointer)
            _orchestration_validate_json(item, child_pointer)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _orchestration_validate_json(
                item, f"{pointer}/{index}"
            )
        return
    raise _orchestration_error(
        "ORCHESTRATION_VALUE_INVALID",
        "values must be canonical JSON values",
        pointer=pointer or "/",
        details={"type": type(value).__name__},
    )


def _orchestration_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _orchestration_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_orchestration_thaw(item) for item in value]
    return value


def _orchestration_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _orchestration_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_orchestration_freeze(item) for item in value)
    return value


def _orchestration_canonical_bytes(value: object) -> bytes:
    _orchestration_validate_json(value)
    try:
        return json.dumps(
            _orchestration_thaw(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _orchestration_error(
            "ORCHESTRATION_CANONICALIZATION_FAILED",
            "value cannot be canonically encoded",
        ) from exc


def _orchestration_require_mapping(
    value: object,
    pointer: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            "field must be an object",
            pointer=pointer,
            details={"type": type(value).__name__},
        )
    if any(not isinstance(key, str) for key in value):
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            "object keys must be strings",
            pointer=pointer,
        )
    return value


def _orchestration_reject_unknown(
    value: Mapping[str, object],
    allowed: frozenset[str],
    pointer: str,
    *,
    code: str,
) -> None:
    unknown = sorted(
        set(value) - allowed, key=_orchestration_utf8_key
    )
    if unknown:
        raise _orchestration_error(
            code,
            "contract contains unsupported fields",
            pointer=pointer,
            details={"fields": unknown},
        )


def _orchestration_require_fields(
    value: Mapping[str, object],
    required: frozenset[str],
    pointer: str,
    *,
    code: str,
) -> None:
    missing = sorted(
        required - set(value), key=_orchestration_utf8_key
    )
    if missing:
        raise _orchestration_error(
            code,
            "contract is missing required fields",
            pointer=pointer,
            details={"fields": missing},
        )


def _orchestration_require_string(
    value: object,
    pointer: str,
    *,
    stable_id: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            "field must be a non-empty string",
            pointer=pointer,
        )
    _orchestration_validate_json(value, pointer)
    if stable_id and not _orchestration_stable_id_re.fullmatch(value):
        raise _orchestration_error(
            "ORCHESTRATION_IDENTIFIER_INVALID",
            "identifier is not stable and portable",
            pointer=pointer,
            details={"value": value},
        )
    if stable_id and any(
        segment in {"", ".", ".."} for segment in value.split("/")
    ):
        raise _orchestration_error(
            "ORCHESTRATION_IDENTIFIER_INVALID",
            "identifier contains a non-portable path-like segment",
            pointer=pointer,
            details={"value": value},
        )
    return value


def _orchestration_require_digest(
    value: object,
    pointer: str,
) -> str:
    digest = _orchestration_require_string(value, pointer)
    if not _orchestration_sha256_re.fullmatch(digest):
        raise _orchestration_error(
            "ORCHESTRATION_DIGEST_INVALID",
            "digest must be lowercase SHA-256",
            pointer=pointer,
            details={"value": digest},
        )
    return digest


def _orchestration_require_int(
    value: object,
    pointer: str,
    *,
    minimum: int = 0,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _orchestration_signed_int64_max
    ):
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            f"field must be an integer >= {minimum}",
            pointer=pointer,
            details={"value": value},
        )
    return value


def _orchestration_require_bool(
    value: object,
    pointer: str,
) -> bool:
    if not isinstance(value, bool):
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            "field must be boolean",
            pointer=pointer,
        )
    return value


def _orchestration_require_sequence(
    value: object,
    pointer: str,
) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise _orchestration_error(
            "ORCHESTRATION_FIELD_INVALID",
            "field must be an array",
            pointer=pointer,
        )
    return value


def _orchestration_require_ordered_strings(
    value: object,
    pointer: str,
    *,
    stable_ids: bool = False,
    digests: bool = False,
    allowed: Optional[frozenset[str]] = None,
) -> tuple[str, ...]:
    sequence = _orchestration_require_sequence(value, pointer)
    result: list[str] = []
    for index, item in enumerate(sequence):
        item_pointer = f"{pointer}/{index}"
        if digests:
            parsed = _orchestration_require_digest(
                item, item_pointer
            )
        else:
            parsed = _orchestration_require_string(
                item, item_pointer, stable_id=stable_ids
            )
        if allowed is not None and parsed not in allowed:
            raise _orchestration_error(
                "ORCHESTRATION_ENUM_INVALID",
                "array contains an unsupported value",
                pointer=item_pointer,
                details={"value": parsed},
            )
        result.append(parsed)
    if len(result) != len(set(result)):
        raise _orchestration_error(
            "ORCHESTRATION_DUPLICATE_IDENTITY",
            "array values must be unique",
            pointer=pointer,
        )
    if stable_ids:
        _orchestration_reject_portable_identity_collisions(
            result,
            pointer=pointer,
            code="ORCHESTRATION_PORTABLE_IDENTITY_COLLISION",
        )
    expected = tuple(
        sorted(result, key=_orchestration_utf8_key)
    )
    if tuple(result) != expected:
        raise _orchestration_error(
            "ORCHESTRATION_ORDER_INVALID",
            "array values must use deterministic UTF-8 order",
            pointer=pointer,
        )
    return tuple(result)


def _orchestration_reject_portable_identity_collisions(
    values: Sequence[str],
    *,
    pointer: str,
    code: str,
) -> None:
    observed: dict[str, str] = {}
    for value in values:
        portable = unicodedata.normalize("NFC", value).casefold()
        previous = observed.get(portable)
        if previous is not None:
            raise _orchestration_error(
                code,
                "identities collide under NFC plus Unicode case-folding",
                pointer=pointer,
                details={"first": previous, "second": value},
            )
        observed[portable] = value


def _orchestration_domain_identity(
    domain: bytes,
    value: object,
) -> tuple[str, bytes]:
    canonical = _orchestration_canonical_bytes(value)
    preimage = domain + _orchestration_u64be(len(canonical)) + canonical
    return hashlib.sha256(preimage).hexdigest(), canonical


def _orchestration_validate_compact_refs(
    value: object,
    *,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    pointer_root = f"/{field}"
    sequence = _orchestration_require_sequence(value, pointer_root)
    result: list[Mapping[str, object]] = []
    ids: list[str] = []
    for index, raw in enumerate(sequence):
        pointer = f"{pointer_root}/{index}"
        item = _orchestration_require_mapping(raw, pointer)
        _orchestration_reject_unknown(
            item,
            _orchestration_compact_ref_fields,
            pointer,
            code="NODE_RESULT_REFERENCE_INVALID",
        )
        _orchestration_require_fields(
            item,
            _orchestration_compact_ref_fields,
            pointer,
            code="NODE_RESULT_REFERENCE_INVALID",
        )
        reference_id = _orchestration_require_string(
            item["id"],
            f"{pointer}/id",
            stable_id=True,
        )
        ids.append(reference_id)
        result.append(
            MappingProxyType(
                {
                    "id": reference_id,
                    "semantic_sha256": (
                        _orchestration_require_digest(
                            item["semantic_sha256"],
                            f"{pointer}/semantic_sha256",
                        )
                    ),
                    "sha256": _orchestration_require_digest(
                        item["sha256"], f"{pointer}/sha256"
                    ),
                    "size": _orchestration_require_int(
                        item["size"], f"{pointer}/size"
                    ),
                    "kind": _orchestration_require_string(
                        item["kind"],
                        f"{pointer}/kind",
                        stable_id=True,
                    ),
                    "locator": _orchestration_require_string(
                        item["locator"],
                        f"{pointer}/locator",
                        stable_id=True,
                    ),
                }
            )
        )
    if len(ids) != len(set(ids)):
        raise _orchestration_error(
            "NODE_RESULT_REFERENCE_DUPLICATE",
            "node result reference identities must be unique",
            pointer=pointer_root,
        )
    _orchestration_reject_portable_identity_collisions(
        ids,
        pointer=pointer_root,
        code="NODE_RESULT_REFERENCE_PORTABLE_COLLISION",
    )
    if ids != sorted(ids, key=_orchestration_utf8_key):
        raise _orchestration_error(
            "NODE_RESULT_REFERENCE_ORDER_INVALID",
            "node result references must use deterministic UTF-8 order",
            pointer=pointer_root,
        )
    return tuple(result)


def _orchestration_validate_node_result_payload(
    value: object,
    *,
    require_identity: bool,
) -> Mapping[str, object]:
    result = _orchestration_require_mapping(value, "/result")
    _orchestration_validate_json(result, "/result")
    _orchestration_reject_unknown(
        result,
        _orchestration_node_result_fields,
        "/result",
        code="NODE_RESULT_UNKNOWN_FIELD",
    )
    required = (
        _orchestration_node_result_fields
        if require_identity
        else _orchestration_node_result_fields - {"result_id"}
    )
    _orchestration_require_fields(
        result,
        required,
        "/result",
        code="NODE_RESULT_MISSING_FIELD",
    )
    if result.get("schema") != ORCHESTRATION_NODE_RESULT_SCHEMA:
        raise _orchestration_error(
            "NODE_RESULT_SCHEMA_UNSUPPORTED",
            "node result schema is unsupported",
            pointer="/result/schema",
            details={"schema": result.get("schema")},
        )
    normalized: dict[str, object] = {
        "schema": ORCHESTRATION_NODE_RESULT_SCHEMA
    }
    if require_identity:
        result_id = _orchestration_require_string(
            result.get("result_id"),
            "/result/result_id",
        )
        if not _orchestration_node_result_id_re.fullmatch(result_id):
            raise _orchestration_error(
                "NODE_RESULT_ID_INVALID",
                "result ID must be a content-addressed node-result identity",
                pointer="/result/result_id",
                details={"value": result_id},
            )
        normalized["result_id"] = result_id
    for field in ("task_id", "node_instance_id"):
        normalized[field] = _orchestration_require_string(
            result.get(field),
            f"/result/{field}",
            stable_id=True,
        )
    repository_id = result.get("repository_id")
    normalized["repository_id"] = (
        None
        if repository_id is None
        else _orchestration_require_string(
            repository_id,
            "/result/repository_id",
            stable_id=True,
        )
    )
    assignment_id = _orchestration_require_string(
        result.get("assignment_id"),
        "/result/assignment_id",
        stable_id=True,
    )
    if not _orchestration_content_addressed_id_re.fullmatch(
        assignment_id
    ):
        raise _orchestration_error(
            "NODE_RESULT_ASSIGNMENT_ID_INVALID",
            "assignment ID must be a content-addressed identity",
            pointer="/result/assignment_id",
        )
    normalized["assignment_id"] = assignment_id
    for field in (
        "workflow_bundle_sha256",
        "input_sha256",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
    ):
        normalized[field] = _orchestration_require_digest(
            result.get(field), f"/result/{field}"
        )
    lease_id = result.get("lease_id")
    lease_nonce = result.get("lease_nonce")
    if (lease_id is None) != (lease_nonce is None):
        raise _orchestration_error(
            "NODE_RESULT_LEASE_BINDING_INVALID",
            "lease ID and nonce must both be present or both be null",
            pointer="/result/lease_id",
        )
    if lease_id is None:
        normalized["lease_id"] = None
        normalized["lease_nonce"] = None
    else:
        parsed_lease_id = _orchestration_require_string(
            lease_id, "/result/lease_id", stable_id=True
        )
        if not _orchestration_content_addressed_id_re.fullmatch(
            parsed_lease_id
        ):
            raise _orchestration_error(
                "NODE_RESULT_LEASE_ID_INVALID",
                "lease ID must be a content-addressed identity",
                pointer="/result/lease_id",
            )
        normalized["lease_id"] = parsed_lease_id
        normalized["lease_nonce"] = _orchestration_require_digest(
            lease_nonce, "/result/lease_nonce"
        )
    for field, minimum in (
        ("map_epoch", 1),
        ("attempt", 1),
    ):
        normalized[field] = _orchestration_require_int(
            result.get(field),
            f"/result/{field}",
            minimum=minimum,
        )
    outcome = _orchestration_require_string(
        result.get("outcome"), "/result/outcome"
    )
    if outcome not in _orchestration_result_outcomes:
        raise _orchestration_error(
            "NODE_RESULT_OUTCOME_UNSUPPORTED",
            "node result outcome is unsupported",
            pointer="/result/outcome",
            details={"outcome": outcome},
        )
    normalized["outcome"] = outcome
    summary = _orchestration_require_string(
        result.get("summary"), "/result/summary"
    )
    if len(summary.encode("utf-8")) > NODE_RESULT_SUMMARY_BUDGET:
        raise _orchestration_error(
            "NODE_RESULT_SUMMARY_BUDGET_EXCEEDED",
            "inline node result summary exceeds 512 UTF-8 bytes",
            pointer="/result/summary",
            details={"bytes": len(summary.encode("utf-8"))},
        )
    normalized["summary"] = summary
    normalized["blockers"] = _orchestration_require_ordered_strings(
        result.get("blockers"),
        "/result/blockers",
        stable_ids=True,
    )

    plan_drift = _orchestration_require_mapping(
        result.get("plan_drift"), "/result/plan_drift"
    )
    _orchestration_reject_unknown(
        plan_drift,
        _orchestration_plan_drift_fields,
        "/result/plan_drift",
        code="NODE_RESULT_PLAN_DRIFT_INVALID",
    )
    _orchestration_require_fields(
        plan_drift,
        _orchestration_plan_drift_fields,
        "/result/plan_drift",
        code="NODE_RESULT_PLAN_DRIFT_INVALID",
    )
    drift_detected = _orchestration_require_bool(
        plan_drift["detected"], "/result/plan_drift/detected"
    )
    drift_reasons = _orchestration_require_ordered_strings(
        plan_drift["reasons"],
        "/result/plan_drift/reasons",
        stable_ids=True,
    )
    if drift_detected != bool(drift_reasons):
        raise _orchestration_error(
            "NODE_RESULT_PLAN_DRIFT_INVALID",
            "plan-drift flag and reasons must agree",
            pointer="/result/plan_drift",
        )
    if drift_detected and outcome != "BLOCKED":
        raise _orchestration_error(
            "NODE_RESULT_PLAN_DRIFT_OUTCOME_INVALID",
            "declared plan drift must produce a blocked result",
            pointer="/result/outcome",
        )
    if outcome == "SUCCEEDED" and normalized["blockers"]:
        raise _orchestration_error(
            "NODE_RESULT_SUCCESS_BLOCKED",
            "successful result cannot contain blockers",
            pointer="/result/blockers",
        )
    if outcome == "BLOCKED" and not (
        normalized["blockers"] or drift_detected
    ):
        raise _orchestration_error(
            "NODE_RESULT_BLOCKER_REQUIRED",
            "blocked result must identify a blocker or plan drift",
            pointer="/result/blockers",
        )
    normalized["plan_drift"] = MappingProxyType(
        {
            "detected": drift_detected,
            "reasons": drift_reasons,
        }
    )

    normalized["artifact_refs"] = (
        _orchestration_validate_compact_refs(
            result.get("artifact_refs"), field="artifact_refs"
        )
    )
    normalized["evidence_refs"] = (
        _orchestration_validate_compact_refs(
            result.get("evidence_refs"), field="evidence_refs"
        )
    )
    runtime_handle = result.get("runtime_handle")
    normalized["runtime_handle"] = (
        None
        if runtime_handle is None
        else _orchestration_require_string(
            runtime_handle,
            "/result/runtime_handle",
            stable_id=True,
        )
    )
    frozen = _orchestration_freeze(normalized)
    if require_identity:
        size = len(_orchestration_canonical_bytes(frozen))
        if size > NODE_RESULT_BUDGET:
            raise _orchestration_error(
                "NODE_RESULT_BUDGET_EXCEEDED",
                "manager-visible node result exceeds 2,048 UTF-8 bytes",
                pointer="/result",
                details={"size": size, "budget": NODE_RESULT_BUDGET},
            )
    return frozen  # type: ignore[return-value]


def bind_node_result_identity(
    value: object,
) -> Mapping[str, object]:
    """Return one deeply immutable result with its canonical identity bound."""

    raw = _orchestration_require_mapping(value, "/result")
    candidate = {
        str(key): _orchestration_thaw(item)
        for key, item in raw.items()
        if key != "result_id"
    }
    normalized = _orchestration_validate_node_result_payload(
        candidate, require_identity=False
    )
    digest, _ = _orchestration_domain_identity(
        NODE_RESULT_DOMAIN, normalized
    )
    bound = dict(_orchestration_thaw(normalized))
    bound["result_id"] = "node-result-" + digest
    return _orchestration_validate_node_result_payload(
        bound, require_identity=True
    )


def parse_node_result_json(source: object) -> Mapping[str, object]:
    """Parse strict UTF-8 JSON and validate one content-addressed result."""

    if isinstance(source, str):
        text = source
    elif isinstance(source, (bytes, bytearray, memoryview)):
        payload = bytes(source)
        if payload.startswith(b"\xef\xbb\xbf"):
            raise _orchestration_error(
                "ORCHESTRATION_BOM_FORBIDDEN",
                "node result JSON must not contain a UTF-8 BOM",
            )
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _orchestration_error(
                "ORCHESTRATION_UTF8_INVALID",
                "node result JSON must be valid UTF-8",
                details={"start": exc.start, "end": exc.end},
            ) from exc
    else:
        raise _orchestration_error(
            "ORCHESTRATION_JSON_SOURCE_INVALID",
            "node result JSON source must be text or bytes",
            details={"type": type(source).__name__},
        )
    if text.startswith("\ufeff"):
        raise _orchestration_error(
            "ORCHESTRATION_BOM_FORBIDDEN",
            "node result JSON must not contain a UTF-8 BOM",
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_orchestration_strict_object,
            parse_float=_orchestration_reject_float,
            parse_int=_orchestration_parse_integer,
            parse_constant=_orchestration_reject_constant,
        )
    except _OrchestrationJsonSemanticError as exc:
        messages = {
            "ORCHESTRATION_DUPLICATE_KEY": (
                "node result object keys must be unique"
            ),
            "ORCHESTRATION_FLOAT_FORBIDDEN": (
                "node result floating-point values are forbidden"
            ),
            "ORCHESTRATION_INTEGER_OUT_OF_RANGE": (
                "node result integers must fit signed 64-bit range"
            ),
            "ORCHESTRATION_NONFINITE_FORBIDDEN": (
                "node result NaN and infinity values are forbidden"
            ),
        }
        raise OrchestrationResultError(
            exc.code, messages[exc.code], details=exc.details
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        details: dict[str, object] = {}
        if isinstance(exc, json.JSONDecodeError):
            details = {
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            }
        raise OrchestrationResultError(
            "ORCHESTRATION_JSON_MALFORMED",
            "node result JSON is malformed",
            details=details,
        ) from exc
    return validate_orchestration_node_result(value)


def validate_orchestration_node_result(
    value: object,
) -> Mapping[str, object]:
    """Validate exact v1 fields and verify the content-addressed result ID."""

    normalized = _orchestration_validate_node_result_payload(
        value, require_identity=True
    )
    content = {
        str(key): _orchestration_thaw(item)
        for key, item in normalized.items()
        if key != "result_id"
    }
    digest, _ = _orchestration_domain_identity(
        NODE_RESULT_DOMAIN, content
    )
    expected_id = "node-result-" + digest
    if not hmac.compare_digest(
        str(normalized["result_id"]), expected_id
    ):
        raise _orchestration_error(
            "NODE_RESULT_IDENTITY_MISMATCH",
            "result ID does not match canonical result content",
            pointer="/result/result_id",
            details={
                "expected": expected_id,
                "actual": normalized["result_id"],
            },
        )
    return normalized


def node_result_content_sha256(value: object) -> str:
    result = validate_orchestration_node_result(value)
    return str(result["result_id"])[len("node-result-") :]


def canonical_node_result_bytes(value: object) -> bytes:
    return _orchestration_canonical_bytes(
        validate_orchestration_node_result(value)
    )


def _orchestration_validate_expectation(
    value: object,
) -> Mapping[str, object]:
    expected = _orchestration_require_mapping(value, "/expected")
    _orchestration_reject_unknown(
        expected,
        _orchestration_expectation_fields,
        "/expected",
        code="NODE_RESULT_EXPECTATION_INVALID",
    )
    _orchestration_require_fields(
        expected,
        _orchestration_expectation_fields,
        "/expected",
        code="NODE_RESULT_EXPECTATION_INVALID",
    )
    if expected["schema"] != NODE_RESULT_EXPECTATION_SCHEMA:
        raise _orchestration_error(
            "NODE_RESULT_EXPECTATION_UNSUPPORTED",
            "result expectation schema is unsupported",
            pointer="/expected/schema",
        )
    normalized: dict[str, object] = {
        "schema": NODE_RESULT_EXPECTATION_SCHEMA
    }
    for field in (
        "task_id",
        "plan_id",
        "repository_id",
        "node_instance_id",
        "actor_id",
        "host_assignment_id",
    ):
        normalized[field] = _orchestration_require_string(
            expected[field],
            f"/expected/{field}",
            stable_id=True,
        )
    runtime_handle_id = expected["runtime_handle_id"]
    normalized["runtime_handle_id"] = (
        None
        if runtime_handle_id is None
        else _orchestration_require_string(
            runtime_handle_id,
            "/expected/runtime_handle_id",
            stable_id=True,
        )
    )
    for field in ("assignment_id", "lease_id"):
        parsed_id = _orchestration_require_string(
            expected[field], f"/expected/{field}", stable_id=True
        )
        if not _orchestration_content_addressed_id_re.fullmatch(
            parsed_id
        ):
            raise _orchestration_error(
                "NODE_RESULT_EXPECTATION_INVALID",
                f"{field} must be a content-addressed identity",
                pointer=f"/expected/{field}",
            )
        normalized[field] = parsed_id
    normalized["lease_nonce"] = _orchestration_require_digest(
        expected["lease_nonce"], "/expected/lease_nonce"
    )
    for field in (
        "workflow_bundle_sha256",
        "plan_artifact_sha256",
        "dag_sha256",
        "semantic_input_sha256",
        "repository_identity_sha256",
        "assignment_sha256",
        "input_sha256",
        "input_worktree_fingerprint_sha256",
    ):
        normalized[field] = _orchestration_require_digest(
            expected[field], f"/expected/{field}"
        )
    normalized["interface_contract_sha256"] = (
        _orchestration_require_ordered_strings(
            expected["interface_contract_sha256"],
            "/expected/interface_contract_sha256",
            digests=True,
        )
    )
    for field, minimum in (
        ("map_epoch", 1),
        ("attempt", 1),
        ("assignment_revision", 0),
    ):
        normalized[field] = _orchestration_require_int(
            expected[field],
            f"/expected/{field}",
            minimum=minimum,
        )
    normalized["lease_active"] = _orchestration_require_bool(
        expected["lease_active"], "/expected/lease_active"
    )
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def _orchestration_validate_verified_output(
    value: object,
) -> Mapping[str, object]:
    verified = _orchestration_require_mapping(
        value, "/verified_output"
    )
    _orchestration_reject_unknown(
        verified,
        _orchestration_verified_output_fields,
        "/verified_output",
        code="NODE_RESULT_VERIFIED_OUTPUT_INVALID",
    )
    _orchestration_require_fields(
        verified,
        _orchestration_verified_output_fields,
        "/verified_output",
        code="NODE_RESULT_VERIFIED_OUTPUT_INVALID",
    )
    if verified["schema"] != NODE_RESULT_VERIFIED_OUTPUT_SCHEMA:
        raise _orchestration_error(
            "NODE_RESULT_VERIFIED_OUTPUT_UNSUPPORTED",
            "verified output schema is unsupported",
            pointer="/verified_output/schema",
        )
    normalized: dict[str, object] = {
        "schema": NODE_RESULT_VERIFIED_OUTPUT_SCHEMA
    }
    for field in (
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
    ):
        normalized[field] = _orchestration_require_digest(
            verified[field], f"/verified_output/{field}"
        )
    artifacts = _orchestration_require_mapping(
        verified["artifacts"], "/verified_output/artifacts"
    )
    normalized_artifacts: dict[str, str] = {}
    for artifact_id in sorted(
        artifacts, key=_orchestration_utf8_key
    ):
        parsed_id = _orchestration_require_string(
            artifact_id,
            (
                "/verified_output/artifacts/"
                + _orchestration_pointer_segment(artifact_id)
            ),
            stable_id=True,
        )
        normalized_artifacts[parsed_id] = (
            _orchestration_require_digest(
                artifacts[artifact_id],
                (
                    "/verified_output/artifacts/"
                    + _orchestration_pointer_segment(artifact_id)
                ),
            )
        )
    _orchestration_reject_portable_identity_collisions(
        tuple(normalized_artifacts),
        pointer="/verified_output/artifacts",
        code="NODE_RESULT_ARTIFACT_REF_PORTABLE_COLLISION",
    )
    evidence = _orchestration_require_mapping(
        verified["evidence"], "/verified_output/evidence"
    )
    normalized_evidence: dict[str, object] = {}
    for evidence_id in sorted(
        evidence, key=_orchestration_utf8_key
    ):
        pointer = (
            "/verified_output/evidence/"
            + _orchestration_pointer_segment(evidence_id)
        )
        parsed_id = _orchestration_require_string(
            evidence_id, pointer, stable_id=True
        )
        fact = _orchestration_require_mapping(
            evidence[evidence_id], pointer
        )
        _orchestration_reject_unknown(
            fact,
            _orchestration_verified_evidence_fields,
            pointer,
            code="NODE_RESULT_VERIFIED_EVIDENCE_INVALID",
        )
        _orchestration_require_fields(
            fact,
            _orchestration_verified_evidence_fields,
            pointer,
            code="NODE_RESULT_VERIFIED_EVIDENCE_INVALID",
        )
        normalized_evidence[parsed_id] = MappingProxyType(
            {
                "sha256": _orchestration_require_digest(
                    fact["sha256"], f"{pointer}/sha256"
                ),
                "semantic_sha256": (
                    _orchestration_require_digest(
                        fact["semantic_sha256"],
                        f"{pointer}/semantic_sha256",
                    )
                ),
                "size": _orchestration_require_int(
                    fact["size"], f"{pointer}/size"
                ),
                "kind": _orchestration_require_string(
                    fact["kind"],
                    f"{pointer}/kind",
                    stable_id=True,
                ),
                "locator": _orchestration_require_string(
                    fact["locator"],
                    f"{pointer}/locator",
                    stable_id=True,
                ),
                "current": _orchestration_require_bool(
                    fact["current"], f"{pointer}/current"
                ),
            }
        )
    _orchestration_reject_portable_identity_collisions(
        tuple(normalized_evidence),
        pointer="/verified_output/evidence",
        code="NODE_RESULT_EVIDENCE_REF_PORTABLE_COLLISION",
    )
    normalized["artifacts"] = MappingProxyType(normalized_artifacts)
    normalized["evidence"] = MappingProxyType(normalized_evidence)
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def _orchestration_compare_bindings(
    result: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    plan_fields = (
        "workflow_bundle_sha256",
        "map_epoch",
    )
    binding_fields = (
        "task_id",
        "repository_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "lease_nonce",
        "input_sha256",
    )
    for fields, code, message in (
        (
            plan_fields,
            "NODE_RESULT_PLAN_DRIFT",
            "result no longer matches the approved plan",
        ),
        (
            binding_fields,
            "NODE_RESULT_BINDING_MISMATCH",
            "result does not match its assignment and active lease",
        ),
    ):
        mismatched = []
        for field in fields:
            result_value = _orchestration_thaw(result[field])
            expected_value = _orchestration_thaw(expected[field])
            if field == "lease_nonce":
                differs = not hmac.compare_digest(
                    str(result_value), str(expected_value)
                )
            else:
                differs = result_value != expected_value
            if differs:
                mismatched.append(field)
        if mismatched:
            raise _orchestration_error(
                code,
                message,
                pointer="/result",
                details={"fields": mismatched},
            )
    if result["runtime_handle"] != expected["runtime_handle_id"]:
        raise _orchestration_error(
            "NODE_RESULT_RUNTIME_HANDLE_MISMATCH",
            "result runtime handle does not match its assignment",
            pointer="/result/runtime_handle",
        )
    if result["lease_id"] is not None and not expected["lease_active"]:
        raise _orchestration_error(
            "NODE_RESULT_LATE_OR_ORPHANED",
            "inactive, expired, revoked, or superseded lease cannot accept output",
            pointer="/expected/lease_active",
        )


def _orchestration_verify_result_output(
    result: Mapping[str, object],
    verified: Mapping[str, object],
) -> None:
    direct_fields = (
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
    )
    mismatched = [
        field
        for field in direct_fields
        if result[field] != verified[field]
    ]
    if mismatched:
        code = (
            "NODE_RESULT_WORKTREE_DRIFT"
            if "worktree_sha256" in mismatched
            else "NODE_RESULT_OUTPUT_UNVERIFIED"
        )
        raise _orchestration_error(
            code,
            "worker output differs from controller-verified facts",
            pointer="/result",
            details={"fields": mismatched},
        )
    verified_artifacts = verified["artifacts"]
    verified_evidence = verified["evidence"]
    assert isinstance(verified_artifacts, Mapping)
    assert isinstance(verified_evidence, Mapping)
    for artifact in result["artifact_refs"]:
        actual = verified_artifacts.get(artifact["id"])
        if actual != artifact["sha256"]:
            raise _orchestration_error(
                "NODE_RESULT_ARTIFACT_UNVERIFIED",
                "artifact reference is absent or has a different digest",
                pointer="/result/artifact_refs",
                details={"artifact_id": artifact["id"]},
            )
    for evidence in result["evidence_refs"]:
        actual = verified_evidence.get(evidence["id"])
        if not isinstance(actual, Mapping):
            raise _orchestration_error(
                "NODE_RESULT_EVIDENCE_UNVERIFIED",
                "evidence reference is absent from controller facts",
                pointer="/result/evidence_refs",
                details={"evidence_id": evidence["id"]},
            )
        expected_fact = {
            "sha256": evidence["sha256"],
            "semantic_sha256": evidence["semantic_sha256"],
            "size": evidence["size"],
            "kind": evidence["kind"],
            "locator": evidence["locator"],
        }
        mismatch = [
            field
            for field, expected_value in expected_fact.items()
            if actual.get(field) != expected_value
        ]
        if mismatch or not actual.get("current"):
            raise _orchestration_error(
                "NODE_RESULT_EVIDENCE_UNVERIFIED",
                "evidence is stale or does not match controller facts",
                pointer="/result/evidence_refs",
                details={
                    "evidence_id": evidence["id"],
                    "fields": mismatch,
                },
            )


def _orchestration_history_result(
    value: object,
) -> tuple[object, Optional[Mapping[str, object]]]:
    if isinstance(value, Mapping) and set(value) == set(
        _orchestration_history_entry_fields
    ):
        receipt_raw = value["receipt"]
        receipt = _orchestration_require_mapping(
            receipt_raw, "/history/receipt"
        )
        _orchestration_validate_json(receipt, "/history/receipt")
        return value["result"], _orchestration_freeze(receipt)  # type: ignore[return-value]
    return value, None


def evaluate_node_result_acceptance(
    value: object,
    *,
    expected_revision: int,
    current_revision: int,
    expected_bindings: object,
    verified_output: object,
    observed_results: Optional[Mapping[str, object]] = None,
) -> NodeResultAcceptanceCandidate:
    """Build a serialized CAS candidate without mutating task state.

    Idempotency lookup intentionally precedes the revision check.  This lets a
    manager recover a lost receipt after the original acceptance advanced the
    revision, while different bytes under the same result ID fail closed.
    """

    raw = _orchestration_require_mapping(value, "/result")
    supplied_id = _orchestration_require_string(
        raw.get("result_id"), "/result/result_id"
    )
    history = _orchestration_require_mapping(
        observed_results or {}, "/observed_results"
    )
    existing_raw = history.get(supplied_id)
    if existing_raw is not None:
        existing_result_raw, prior_receipt = (
            _orchestration_history_result(existing_raw)
        )
        if (
            _orchestration_canonical_bytes(raw)
            != _orchestration_canonical_bytes(existing_result_raw)
        ):
            raise _orchestration_error(
                "NODE_RESULT_IDEMPOTENCY_CONFLICT",
                "an observed result ID has different canonical content",
                pointer="/result/result_id",
                details={"result_id": supplied_id},
            )
        result = validate_orchestration_node_result(raw)
        existing_result = validate_orchestration_node_result(
            existing_result_raw
        )
        if (
            canonical_node_result_bytes(result)
            != canonical_node_result_bytes(existing_result)
        ):
            raise _orchestration_error(
                "NODE_RESULT_IDEMPOTENCY_CONFLICT",
                "an observed result ID has different normalized content",
                pointer="/result/result_id",
                details={"result_id": supplied_id},
            )
        revision = _orchestration_require_int(
            current_revision, "/current_revision"
        )
        return NodeResultAcceptanceCandidate(
            disposition="IDEMPOTENT",
            result_id=str(result["result_id"]),
            content_sha256=node_result_content_sha256(result),
            expected_revision=_orchestration_require_int(
                expected_revision, "/expected_revision"
            ),
            candidate_revision=revision,
            result=result,
            prior_receipt=prior_receipt,
        )

    result = validate_orchestration_node_result(raw)
    expected = _orchestration_validate_expectation(
        expected_bindings
    )
    verified = _orchestration_validate_verified_output(
        verified_output
    )
    requested_revision = _orchestration_require_int(
        expected_revision, "/expected_revision"
    )
    actual_revision = _orchestration_require_int(
        current_revision, "/current_revision"
    )
    if requested_revision != actual_revision:
        raise _orchestration_error(
            "NODE_RESULT_REVISION_CONFLICT",
            "result acceptance expected revision is stale",
            pointer="/expected_revision",
            details={
                "expected": requested_revision,
                "current": actual_revision,
            },
        )
    if actual_revision == _orchestration_signed_int64_max:
        raise _orchestration_error(
            "NODE_RESULT_REVISION_EXHAUSTED",
            "task revision cannot be incremented",
            pointer="/current_revision",
        )
    _orchestration_compare_bindings(result, expected)
    _orchestration_verify_result_output(result, verified)
    plan_drift = result["plan_drift"]
    assert isinstance(plan_drift, Mapping)
    disposition = (
        "REPLAN_REQUIRED"
        if plan_drift["detected"]
        else "ACCEPT"
    )
    return NodeResultAcceptanceCandidate(
        disposition=disposition,
        result_id=str(result["result_id"]),
        content_sha256=node_result_content_sha256(result),
        expected_revision=requested_revision,
        candidate_revision=actual_revision + 1,
        result=result,
        prior_receipt=None,
    )


def _orchestration_validate_barrier(
    value: object,
) -> Mapping[str, object]:
    barrier = _orchestration_require_mapping(value, "/barrier")
    _orchestration_validate_json(barrier, "/barrier")
    _orchestration_reject_unknown(
        barrier,
        _orchestration_barrier_fields,
        "/barrier",
        code="RESULT_BARRIER_INVALID",
    )
    _orchestration_require_fields(
        barrier,
        _orchestration_barrier_fields,
        "/barrier",
        code="RESULT_BARRIER_INVALID",
    )
    if barrier["schema"] != RESULT_BARRIER_SCHEMA:
        raise _orchestration_error(
            "RESULT_BARRIER_SCHEMA_UNSUPPORTED",
            "result barrier schema is unsupported",
            pointer="/barrier/schema",
        )
    normalized: dict[str, object] = {
        "schema": RESULT_BARRIER_SCHEMA
    }
    for field in (
        "barrier_id",
        "task_id",
        "plan_id",
        "node_instance_id",
    ):
        normalized[field] = _orchestration_require_string(
            barrier[field],
            f"/barrier/{field}",
            stable_id=True,
        )
    for field in ("workflow_bundle_sha256", "dag_sha256"):
        normalized[field] = _orchestration_require_digest(
            barrier[field], f"/barrier/{field}"
        )
    normalized["map_epoch"] = _orchestration_require_int(
        barrier["map_epoch"], "/barrier/map_epoch", minimum=1
    )
    members_raw = _orchestration_require_sequence(
        barrier["members"], "/barrier/members"
    )
    members: list[Mapping[str, object]] = []
    node_ids: list[str] = []
    repository_ids: list[str] = []
    for index, raw_member in enumerate(members_raw):
        pointer = f"/barrier/members/{index}"
        member = _orchestration_require_mapping(
            raw_member, pointer
        )
        _orchestration_reject_unknown(
            member,
            _orchestration_barrier_member_fields,
            pointer,
            code="RESULT_BARRIER_MEMBER_INVALID",
        )
        _orchestration_require_fields(
            member,
            _orchestration_barrier_member_fields,
            pointer,
            code="RESULT_BARRIER_MEMBER_INVALID",
        )
        node_id = _orchestration_require_string(
            member["node_instance_id"],
            f"{pointer}/node_instance_id",
            stable_id=True,
        )
        repository_id = _orchestration_require_string(
            member["repository_id"],
            f"{pointer}/repository_id",
            stable_id=True,
        )
        allowed_outcomes = _orchestration_require_ordered_strings(
            member["allowed_outcomes"],
            f"{pointer}/allowed_outcomes",
            allowed=_orchestration_barrier_outcomes,
        )
        required = _orchestration_require_bool(
            member["required"], f"{pointer}/required"
        )
        if required and not allowed_outcomes:
            raise _orchestration_error(
                "RESULT_BARRIER_POLICY_INVALID",
                "required member must declare an accepted outcome",
                pointer=f"{pointer}/allowed_outcomes",
            )
        node_ids.append(node_id)
        repository_ids.append(repository_id)
        members.append(
            MappingProxyType(
                {
                    "node_instance_id": node_id,
                    "repository_id": repository_id,
                    "required": required,
                    "allowed_outcomes": allowed_outcomes,
                }
            )
        )
    if not members:
        raise _orchestration_error(
            "RESULT_BARRIER_MEMBER_REQUIRED",
            "result barrier requires at least one member",
            pointer="/barrier/members",
        )
    if len(node_ids) != len(set(node_ids)) or len(
        repository_ids
    ) != len(set(repository_ids)):
        raise _orchestration_error(
            "RESULT_BARRIER_MEMBER_DUPLICATE",
            "barrier node and repository identities must be unique",
            pointer="/barrier/members",
        )
    _orchestration_reject_portable_identity_collisions(
        node_ids,
        pointer="/barrier/members",
        code="RESULT_BARRIER_MEMBER_PORTABLE_COLLISION",
    )
    _orchestration_reject_portable_identity_collisions(
        repository_ids,
        pointer="/barrier/members",
        code="RESULT_BARRIER_REPOSITORY_PORTABLE_COLLISION",
    )
    if node_ids != sorted(node_ids, key=_orchestration_utf8_key):
        raise _orchestration_error(
            "RESULT_BARRIER_MEMBER_ORDER_INVALID",
            "barrier members must use node-instance UTF-8 order",
            pointer="/barrier/members",
        )
    normalized["members"] = tuple(members)
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def _orchestration_validate_accepted_result(
    value: object,
    *,
    pointer: str,
) -> Mapping[str, object]:
    record = _orchestration_require_mapping(value, pointer)
    _orchestration_reject_unknown(
        record,
        _orchestration_accepted_result_fields,
        pointer,
        code="ACCEPTED_NODE_RESULT_INVALID",
    )
    _orchestration_require_fields(
        record,
        _orchestration_accepted_result_fields,
        pointer,
        code="ACCEPTED_NODE_RESULT_INVALID",
    )
    if record["schema"] != ACCEPTED_NODE_RESULT_SCHEMA:
        raise _orchestration_error(
            "ACCEPTED_NODE_RESULT_SCHEMA_UNSUPPORTED",
            "accepted result record schema is unsupported",
            pointer=f"{pointer}/schema",
        )
    runtime_live = _orchestration_require_bool(
        record["runtime_live"], f"{pointer}/runtime_live"
    )
    lease_quiesced = _orchestration_require_bool(
        record["lease_quiesced"], f"{pointer}/lease_quiesced"
    )
    if runtime_live and lease_quiesced:
        raise _orchestration_error(
            "ACCEPTED_NODE_RESULT_LEASE_CONTRADICTION",
            "a live runtime cannot be marked quiesced",
            pointer=pointer,
        )
    return MappingProxyType(
        {
            "schema": ACCEPTED_NODE_RESULT_SCHEMA,
            "accepted": _orchestration_require_bool(
                record["accepted"], f"{pointer}/accepted"
            ),
            "current": _orchestration_require_bool(
                record["current"], f"{pointer}/current"
            ),
            "repository_evidence_sha256": (
                _orchestration_require_digest(
                    record["repository_evidence_sha256"],
                    f"{pointer}/repository_evidence_sha256",
                )
            ),
            "lease_quiesced": lease_quiesced,
            "runtime_live": runtime_live,
            "result": validate_orchestration_node_result(
                record["result"]
            ),
        }
    )


def _orchestration_barrier_aggregate_payload(
    barrier: Mapping[str, object],
    members: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    payload = {
        "schema": RESULT_BARRIER_AGGREGATE_SCHEMA,
        "barrier_id": barrier["barrier_id"],
        "task_id": barrier["task_id"],
        "workflow_bundle_sha256": barrier[
            "workflow_bundle_sha256"
        ],
        "plan_id": barrier["plan_id"],
        "dag_sha256": barrier["dag_sha256"],
        "map_epoch": barrier["map_epoch"],
        "node_instance_id": barrier["node_instance_id"],
        "members": [
            _orchestration_thaw(item) for item in members
        ],
    }
    digest, _ = _orchestration_domain_identity(
        RESULT_BARRIER_DOMAIN, payload
    )
    payload["barrier_sha256"] = digest
    return _orchestration_freeze(payload)  # type: ignore[return-value]


def _orchestration_validate_prior_aggregate(
    value: object,
) -> Mapping[str, object]:
    aggregate = _orchestration_require_mapping(
        value, "/previous_aggregate"
    )
    _orchestration_reject_unknown(
        aggregate,
        _orchestration_barrier_aggregate_fields,
        "/previous_aggregate",
        code="RESULT_BARRIER_AGGREGATE_INVALID",
    )
    _orchestration_require_fields(
        aggregate,
        _orchestration_barrier_aggregate_fields,
        "/previous_aggregate",
        code="RESULT_BARRIER_AGGREGATE_INVALID",
    )
    if aggregate["schema"] != RESULT_BARRIER_AGGREGATE_SCHEMA:
        raise _orchestration_error(
            "RESULT_BARRIER_AGGREGATE_UNSUPPORTED",
            "barrier aggregate schema is unsupported",
            pointer="/previous_aggregate/schema",
        )
    for field in (
        "barrier_id",
        "task_id",
        "plan_id",
        "node_instance_id",
    ):
        _orchestration_require_string(
            aggregate[field],
            f"/previous_aggregate/{field}",
            stable_id=True,
        )
    for field in (
        "barrier_sha256",
        "workflow_bundle_sha256",
        "dag_sha256",
    ):
        _orchestration_require_digest(
            aggregate[field], f"/previous_aggregate/{field}"
        )
    _orchestration_require_int(
        aggregate["map_epoch"],
        "/previous_aggregate/map_epoch",
        minimum=1,
    )
    members = _orchestration_require_sequence(
        aggregate["members"], "/previous_aggregate/members"
    )
    node_ids: list[str] = []
    for index, raw in enumerate(members):
        pointer = f"/previous_aggregate/members/{index}"
        member = _orchestration_require_mapping(raw, pointer)
        _orchestration_reject_unknown(
            member,
            _orchestration_barrier_aggregate_member_fields,
            pointer,
            code="RESULT_BARRIER_AGGREGATE_INVALID",
        )
        _orchestration_require_fields(
            member,
            _orchestration_barrier_aggregate_member_fields,
            pointer,
            code="RESULT_BARRIER_AGGREGATE_INVALID",
        )
        node_id = _orchestration_require_string(
            member["node_instance_id"],
            f"{pointer}/node_instance_id",
            stable_id=True,
        )
        node_ids.append(node_id)
        _orchestration_require_string(
            member["repository_id"],
            f"{pointer}/repository_id",
            stable_id=True,
        )
        result_id = _orchestration_require_string(
            member["result_id"], f"{pointer}/result_id"
        )
        if not _orchestration_node_result_id_re.fullmatch(result_id):
            raise _orchestration_error(
                "RESULT_BARRIER_AGGREGATE_INVALID",
                "aggregate result ID is not content-addressed",
                pointer=f"{pointer}/result_id",
            )
        outcome = _orchestration_require_string(
            member["outcome"], f"{pointer}/outcome"
        )
        if outcome not in _orchestration_barrier_outcomes:
            raise _orchestration_error(
                "RESULT_BARRIER_AGGREGATE_INVALID",
                "aggregate member outcome is unsupported",
                pointer=f"{pointer}/outcome",
            )
        for field in (
            "input_sha256",
            "output_sha256",
            "repository_evidence_sha256",
            "worktree_sha256",
        ):
            _orchestration_require_digest(
                member[field], f"{pointer}/{field}"
            )
        _orchestration_validate_compact_refs(
            member["artifact_refs"], field="artifact_refs"
        )
        _orchestration_validate_compact_refs(
            member["evidence_refs"], field="evidence_refs"
        )
    if node_ids != sorted(node_ids, key=_orchestration_utf8_key):
        raise _orchestration_error(
            "RESULT_BARRIER_MEMBER_ORDER_INVALID",
            "aggregate members must use deterministic UTF-8 order",
            pointer="/previous_aggregate/members",
        )
    if len(node_ids) != len(set(node_ids)):
        raise _orchestration_error(
            "RESULT_BARRIER_AGGREGATE_INVALID",
            "aggregate member identities must be unique",
            pointer="/previous_aggregate/members",
        )
    _orchestration_reject_portable_identity_collisions(
        node_ids,
        pointer="/previous_aggregate/members",
        code="RESULT_BARRIER_MEMBER_PORTABLE_COLLISION",
    )
    supplied_digest = _orchestration_require_digest(
        aggregate["barrier_sha256"],
        "/previous_aggregate/barrier_sha256",
    )
    payload = {
        str(key): _orchestration_thaw(item)
        for key, item in aggregate.items()
        if key != "barrier_sha256"
    }
    expected_digest, _ = _orchestration_domain_identity(
        RESULT_BARRIER_DOMAIN, payload
    )
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise _orchestration_error(
            "RESULT_BARRIER_AGGREGATE_IDENTITY_MISMATCH",
            "barrier aggregate identity does not match its content",
            pointer="/previous_aggregate/barrier_sha256",
        )
    return _orchestration_freeze(aggregate)  # type: ignore[return-value]


def evaluate_result_barrier(
    barrier_value: object,
    current_result_values: Mapping[str, object],
    *,
    previous_aggregate: Optional[Mapping[str, object]] = None,
    dependent_result_ids: Sequence[str] = (),
) -> BarrierEvaluation:
    """Evaluate complete current fan-in facts in canonical member order."""

    barrier = _orchestration_validate_barrier(barrier_value)
    downstream = _orchestration_require_ordered_strings(
        dependent_result_ids,
        "/dependent_result_ids",
        stable_ids=True,
    )
    raw_results = _orchestration_require_mapping(
        current_result_values, "/current_results"
    )
    members = barrier["members"]
    assert isinstance(members, tuple)
    known_node_ids = {
        str(member["node_instance_id"]) for member in members
    }
    unknown = sorted(
        set(raw_results) - known_node_ids,
        key=_orchestration_utf8_key,
    )
    if unknown:
        raise _orchestration_error(
            "RESULT_BARRIER_UNKNOWN_MEMBER",
            "current results contain a node outside barrier membership",
            pointer="/current_results",
            details={"node_instance_ids": unknown},
        )
    normalized_results: dict[str, Mapping[str, object]] = {}
    for node_id in sorted(
        raw_results, key=_orchestration_utf8_key
    ):
        normalized_results[node_id] = (
            _orchestration_validate_accepted_result(
                raw_results[node_id],
                pointer=(
                    "/current_results/"
                    + _orchestration_pointer_segment(node_id)
                ),
            )
        )

    blockers: list[BarrierMemberBlocker] = []
    aggregate_members: list[Mapping[str, object]] = []
    complete_projection: list[Mapping[str, object]] = []
    for member in members:
        node_id = str(member["node_instance_id"])
        repository_id = str(member["repository_id"])
        record = normalized_results.get(node_id)
        codes: set[str] = set()
        result: Optional[Mapping[str, object]] = None
        if record is None:
            if member["required"]:
                codes.add("RESULT_MISSING")
        else:
            result = record["result"]
            assert isinstance(result, Mapping)
            if result["node_instance_id"] != node_id:
                codes.add("RESULT_NODE_MISMATCH")
            if result["repository_id"] != repository_id:
                codes.add("RESULT_REPOSITORY_MISMATCH")
            for field in (
                "task_id",
                "workflow_bundle_sha256",
                "map_epoch",
            ):
                if result[field] != barrier[field]:
                    codes.add("RESULT_PLAN_BINDING_DRIFT")
            if not record["accepted"]:
                codes.add("RESULT_NOT_ACCEPTED")
            if not record["current"]:
                codes.add("RESULT_STALE")
            if result["outcome"] not in member["allowed_outcomes"]:
                codes.add("RESULT_OUTCOME_NOT_ALLOWED")
            if not record["lease_quiesced"]:
                codes.add("LEASE_NOT_QUIESCED")
            if record["runtime_live"]:
                codes.add("RUNTIME_STILL_LIVE")
            if not codes:
                aggregate_members.append(
                    MappingProxyType(
                        {
                            "node_instance_id": node_id,
                            "repository_id": repository_id,
                            "result_id": result["result_id"],
                            "outcome": result["outcome"],
                            "input_sha256": result["input_sha256"],
                            "output_sha256": result["output_sha256"],
                            "repository_evidence_sha256": record[
                                "repository_evidence_sha256"
                            ],
                            "worktree_sha256": result[
                                "worktree_sha256"
                            ],
                            "artifact_refs": result["artifact_refs"],
                            "evidence_refs": result["evidence_refs"],
                        }
                    )
                )
        complete_projection.append(
            _orchestration_freeze(
                {
                    "schema": (
                        RESULT_BARRIER_CURRENT_MEMBER_SCHEMA
                    ),
                    "node_instance_id": node_id,
                    "repository_id": repository_id,
                    "required": member["required"],
                    "present": record is not None,
                    "accepted": (
                        bool(record["accepted"])
                        if record is not None
                        else False
                    ),
                    "current": (
                        bool(record["current"])
                        if record is not None
                        else False
                    ),
                    "result_id": (
                        result["result_id"]
                        if result is not None
                        else None
                    ),
                    "outcome": (
                        result["outcome"]
                        if result is not None
                        else None
                    ),
                    "repository_evidence_sha256": (
                        record["repository_evidence_sha256"]
                        if record is not None
                        else None
                    ),
                    "lease_quiesced": (
                        bool(record["lease_quiesced"])
                        if record is not None
                        else False
                    ),
                    "runtime_live": (
                        bool(record["runtime_live"])
                        if record is not None
                        else False
                    ),
                    "blocker_codes": tuple(
                        sorted(codes, key=_orchestration_utf8_key)
                    ),
                }
            )
        )
        if codes and member["required"]:
            blockers.append(
                BarrierMemberBlocker(
                    node_instance_id=node_id,
                    repository_id=repository_id,
                    codes=tuple(
                        sorted(codes, key=_orchestration_utf8_key)
                    ),
                )
            )

    prior = (
        None
        if previous_aggregate is None
        else _orchestration_validate_prior_aggregate(
            previous_aggregate
        )
    )
    if prior is not None:
        mismatched_prior = [
            field
            for field in (
                "barrier_id",
                "task_id",
                "workflow_bundle_sha256",
                "plan_id",
                "dag_sha256",
                "map_epoch",
                "node_instance_id",
            )
            if prior[field] != barrier[field]
        ]
        if mismatched_prior:
            raise _orchestration_error(
                "RESULT_BARRIER_AGGREGATE_BINDING_MISMATCH",
                "prior aggregate belongs to a different barrier",
                pointer="/previous_aggregate",
                details={"fields": mismatched_prior},
            )
        prior_unknown = sorted(
            (
                str(member["node_instance_id"])
                for member in prior["members"]
                if str(member["node_instance_id"])
                not in known_node_ids
            ),
            key=_orchestration_utf8_key,
        )
        if prior_unknown:
            raise _orchestration_error(
                "RESULT_BARRIER_AGGREGATE_BINDING_MISMATCH",
                "prior aggregate contains a node outside barrier membership",
                pointer="/previous_aggregate/members",
                details={"node_instance_ids": prior_unknown},
            )
    invalidated_ids: tuple[str, ...] = ()
    if prior is not None:
        prior_by_node = {
            str(member["node_instance_id"]): str(member["result_id"])
            for member in prior["members"]
        }
        current_by_node = {
            str(member["node_instance_id"]): str(member["result_id"])
            for member in aggregate_members
        }
        invalidated_ids = tuple(
            sorted(
                (
                    node_id
                    for node_id, result_id in prior_by_node.items()
                    if current_by_node.get(node_id) != result_id
                ),
                key=_orchestration_utf8_key,
            )
        )
    if blockers:
        status = "REOPENED" if prior is not None else "OPEN"
        return BarrierEvaluation(
            status=status,
            blockers=tuple(blockers),
            current_results=tuple(complete_projection),
            aggregate=None,
            invalidated_node_instance_ids=invalidated_ids,
            dependent_result_ids_to_invalidate=(
                downstream if invalidated_ids else ()
            ),
        )
    aggregate = _orchestration_barrier_aggregate_payload(
        barrier, aggregate_members
    )
    return BarrierEvaluation(
        status="CLOSED",
        blockers=(),
        current_results=tuple(complete_projection),
        aggregate=aggregate,
        invalidated_node_instance_ids=invalidated_ids,
        dependent_result_ids_to_invalidate=(
            downstream if invalidated_ids else ()
        ),
    )


_orchestration_runtime_lease_state_fields = frozenset(
    {
        "schema",
        "lease_id",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "map_epoch",
        "repository_id",
        "repository_identity_sha256",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "assignment_sha256",
        "input_sha256",
        "worktree_identity_sha256",
        "worktree_fingerprint_sha256",
        "repository_common_dir_sha256",
        "ownership_claim_sha256",
        "runtime_handle_id",
        "host_assignment_id",
        "runtime_authentication_sha256",
        "status",
        "writable",
        "issued_monotonic_ns",
        "expires_monotonic_ns",
        "clock_id",
    }
)
_orchestration_worktree_snapshot_fields = frozenset(
    {
        "schema",
        "repository_id",
        "repository_identity_sha256",
        "initial_worktree_fingerprint_sha256",
        "worktree_fingerprint_sha256",
        "repository_common_dir_sha256",
        "ownership_claim_sha256",
        "git_state_sha256",
        "changed_paths_sha256",
        "complete",
        "active_writer",
        "mutation_quarantine",
    }
)
_orchestration_runtime_stop_fields = frozenset(
    {
        "schema",
        "task_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "runtime_handle_id",
        "host_assignment_id",
        "authentication_sha256",
        "stopped",
    }
)
_orchestration_runtime_recovery_fields = frozenset(
    {
        "schema",
        "task_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "runtime_handle_id",
        "host_assignment_id",
        "found",
        "authenticated",
        "live",
        "worktree_fingerprint_sha256",
    }
)
_orchestration_retry_policy_fields = frozenset(
    {"max_attempts", "retryable_outcomes", "requires_approval"}
)


@dataclass(frozen=True)
class LeaseTimeoutDecision:
    lease_id: str
    expired: bool
    authorization_active: bool
    cancellation_requested: bool
    quiesced: bool
    observed_monotonic_ns: int
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class CancellationCandidate:
    expected_revision: int
    candidate_revision: int
    requested: bool
    quiesced: bool
    lease_ids_to_revoke: tuple[str, ...]
    lease_ids_requiring_reconciliation: tuple[str, ...]


@dataclass(frozen=True)
class AuthenticatedRuntimeStop:
    lease_id: str
    assignment_id: str
    runtime_handle_id: Optional[str]
    host_assignment_id: str
    observation_sha256: str


@dataclass(frozen=True)
class StableReconciliationProbe:
    lease_id: str
    assignment_id: str
    lease_binding_sha256: str
    clock_id: str
    started_monotonic_ns: int
    required_stability_ns: int
    snapshot_sha256: str
    snapshot: Mapping[str, object]
    reason: str
    termination_confirmed: bool
    termination_evidence_sha256: Optional[str]
    operator_isolation_confirmed: bool
    operator_isolation_evidence_sha256: Optional[str]


@dataclass(frozen=True)
class LeaseQuiescenceProof:
    lease_id: str
    assignment_id: str
    method: str
    worktree_fingerprint_sha256: str
    proof_sha256: str
    quiesced: bool
    canonical_bytes: bytes


@dataclass(frozen=True)
class RuntimeRecoveryDecision:
    status: str
    reattach: bool
    orphaned: bool
    quiesced: bool
    replacement_allowed: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ReplacementLeaseCandidate:
    prior_lease_id: str
    next_attempt: int
    worktree_strategy: str
    worktree_fingerprint_sha256: str
    authorized: bool


@dataclass(frozen=True)
class RetryCandidate:
    node_instance_id: str
    previous_attempt: int
    next_attempt: int
    expected_revision: int
    candidate_revision: int
    worktree_strategy: str
    worktree_fingerprint_sha256: str


@dataclass(frozen=True)
class CancellationQuiescence:
    requested: bool
    quiesced: bool
    uncertain_lease_ids: tuple[str, ...]


def validate_runtime_lease_state(
    value: object,
) -> Mapping[str, object]:
    """Validate a recovery projection derived from authority and runtime facts."""

    lease = _orchestration_require_mapping(value, "/lease")
    _orchestration_validate_json(lease, "/lease")
    _orchestration_reject_unknown(
        lease,
        _orchestration_runtime_lease_state_fields,
        "/lease",
        code="WORKER_LEASE_INVALID",
    )
    _orchestration_require_fields(
        lease,
        _orchestration_runtime_lease_state_fields,
        "/lease",
        code="WORKER_LEASE_INVALID",
    )
    if lease["schema"] != RUNTIME_LEASE_STATE_SCHEMA:
        raise _orchestration_error(
            "RUNTIME_LEASE_STATE_SCHEMA_UNSUPPORTED",
            "runtime lease-state schema is unsupported",
            pointer="/lease/schema",
        )
    normalized: dict[str, object] = {
        "schema": RUNTIME_LEASE_STATE_SCHEMA
    }
    for field in (
        "lease_id",
        "task_id",
        "plan_id",
        "repository_id",
        "node_instance_id",
        "assignment_id",
        "host_assignment_id",
        "clock_id",
    ):
        normalized[field] = _orchestration_require_string(
            lease[field],
            f"/lease/{field}",
            stable_id=True,
        )
    for field in (
        "workflow_bundle_sha256",
        "dag_sha256",
        "repository_identity_sha256",
        "assignment_sha256",
        "input_sha256",
        "worktree_identity_sha256",
        "worktree_fingerprint_sha256",
        "repository_common_dir_sha256",
        "ownership_claim_sha256",
        "runtime_authentication_sha256",
    ):
        normalized[field] = _orchestration_require_digest(
            lease[field], f"/lease/{field}"
        )
    runtime_handle_id = lease["runtime_handle_id"]
    normalized["runtime_handle_id"] = (
        None
        if runtime_handle_id is None
        else _orchestration_require_string(
            runtime_handle_id,
            "/lease/runtime_handle_id",
            stable_id=True,
        )
    )
    for field, minimum in (
        ("map_epoch", 1),
        ("attempt", 1),
        ("issued_monotonic_ns", 0),
        ("expires_monotonic_ns", 1),
    ):
        normalized[field] = _orchestration_require_int(
            lease[field],
            f"/lease/{field}",
            minimum=minimum,
        )
    if normalized["expires_monotonic_ns"] <= normalized[
        "issued_monotonic_ns"
    ]:
        raise _orchestration_error(
            "WORKER_LEASE_INTERVAL_INVALID",
            "worker lease expiry must follow issuance",
            pointer="/lease/expires_monotonic_ns",
        )
    status = _orchestration_require_string(
        lease["status"], "/lease/status"
    )
    if status not in _orchestration_lease_statuses:
        raise _orchestration_error(
            "WORKER_LEASE_STATUS_UNSUPPORTED",
            "worker lease status is unsupported",
            pointer="/lease/status",
            details={"status": status},
        )
    normalized["status"] = status
    normalized["writable"] = _orchestration_require_bool(
        lease["writable"], "/lease/writable"
    )
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def _orchestration_read_monotonic_ns(
    monotonic_ns: Callable[[], int],
) -> int:
    if not callable(monotonic_ns):
        raise _orchestration_error(
            "MONOTONIC_CLOCK_INVALID",
            "monotonic clock must be callable",
            pointer="/monotonic_ns",
        )
    try:
        value = monotonic_ns()
    except Exception as exc:
        raise _orchestration_error(
            "MONOTONIC_CLOCK_FAILED",
            "monotonic clock observation failed",
            pointer="/monotonic_ns",
            details={"type": type(exc).__name__},
        ) from exc
    return _orchestration_require_int(
        value, "/monotonic_ns/value", minimum=0
    )


def evaluate_lease_timeout(
    lease_value: object,
    *,
    monotonic_ns: Callable[[], int],
    clock_id: str,
) -> LeaseTimeoutDecision:
    """Classify logical expiry without claiming the worker has stopped."""

    lease = validate_runtime_lease_state(lease_value)
    observed_clock_id = _orchestration_require_string(
        clock_id, "/clock_id", stable_id=True
    )
    if observed_clock_id != lease["clock_id"]:
        raise _orchestration_error(
            "MONOTONIC_CLOCK_ID_MISMATCH",
            "lease expiry cannot use a different monotonic clock",
            pointer="/clock_id",
        )
    now = _orchestration_read_monotonic_ns(monotonic_ns)
    expired_by_clock = now >= int(lease["expires_monotonic_ns"])
    status = str(lease["status"])
    authorization_active = (
        status == "ACTIVE" and not expired_by_clock
    )
    expired = expired_by_clock or status == "EXPIRED"
    blockers: list[str] = []
    if expired and status != "QUIESCED":
        blockers.append("LEASE_EXPIRED_NOT_QUIESCED")
    if status in {
        "REVOCATION_REQUESTED",
        "REVOKED",
        "ORPHANED",
    }:
        blockers.append("LEASE_REVOKED_NOT_QUIESCED")
    return LeaseTimeoutDecision(
        lease_id=str(lease["lease_id"]),
        expired=expired,
        authorization_active=authorization_active,
        cancellation_requested=(
            status != "QUIESCED"
            and (
                expired
                or status
                in {
                    "REVOCATION_REQUESTED",
                    "REVOKED",
                    "ORPHANED",
                }
            )
        ),
        quiesced=status == "QUIESCED",
        observed_monotonic_ns=now,
        blockers=tuple(
            sorted(set(blockers), key=_orchestration_utf8_key)
        ),
    )


def build_cancellation_candidate(
    lease_values: Sequence[object],
    *,
    expected_revision: int,
    current_revision: int,
    approval_current: bool,
) -> CancellationCandidate:
    """Build cancellation intent; it never equates revocation with quiescence."""

    requested = _orchestration_require_int(
        expected_revision, "/expected_revision"
    )
    current = _orchestration_require_int(
        current_revision, "/current_revision"
    )
    if requested != current:
        raise _orchestration_error(
            "CANCELLATION_REVISION_CONFLICT",
            "cancellation expected revision is stale",
            pointer="/expected_revision",
            details={"expected": requested, "current": current},
        )
    if not _orchestration_require_bool(
        approval_current, "/approval_current"
    ):
        raise _orchestration_error(
            "CANCELLATION_APPROVAL_REQUIRED",
            "cancellation requires a current explicit approval",
            pointer="/approval_current",
        )
    if current == _orchestration_signed_int64_max:
        raise _orchestration_error(
            "CANCELLATION_REVISION_EXHAUSTED",
            "task revision cannot be incremented",
            pointer="/current_revision",
        )
    leases = tuple(
        validate_runtime_lease_state(value)
        for value in lease_values
    )
    lease_ids = [str(lease["lease_id"]) for lease in leases]
    if len(lease_ids) != len(set(lease_ids)):
        raise _orchestration_error(
            "WORKER_LEASE_DUPLICATE",
            "cancellation lease identities must be unique",
            pointer="/leases",
        )
    to_revoke = tuple(
        sorted(
            (
                str(lease["lease_id"])
                for lease in leases
                if lease["status"] == "ACTIVE"
            ),
            key=_orchestration_utf8_key,
        )
    )
    to_reconcile = tuple(
        sorted(
            (
                str(lease["lease_id"])
                for lease in leases
                if lease["status"] != "QUIESCED"
            ),
            key=_orchestration_utf8_key,
        )
    )
    return CancellationCandidate(
        expected_revision=requested,
        candidate_revision=current + 1,
        requested=True,
        quiesced=False,
        lease_ids_to_revoke=to_revoke,
        lease_ids_requiring_reconciliation=to_reconcile,
    )


def _orchestration_validate_worktree_snapshot(
    value: object,
    *,
    require_safe: bool,
) -> Mapping[str, object]:
    snapshot = _orchestration_require_mapping(value, "/snapshot")
    _orchestration_validate_json(snapshot, "/snapshot")
    _orchestration_reject_unknown(
        snapshot,
        _orchestration_worktree_snapshot_fields,
        "/snapshot",
        code="WORKTREE_POSTCONDITION_INVALID",
    )
    _orchestration_require_fields(
        snapshot,
        _orchestration_worktree_snapshot_fields,
        "/snapshot",
        code="WORKTREE_POSTCONDITION_INVALID",
    )
    if snapshot["schema"] != WORKTREE_POSTCONDITION_SCHEMA:
        raise _orchestration_error(
            "WORKTREE_POSTCONDITION_SCHEMA_UNSUPPORTED",
            "worktree postcondition schema is unsupported",
            pointer="/snapshot/schema",
        )
    normalized: dict[str, object] = {
        "schema": WORKTREE_POSTCONDITION_SCHEMA,
        "repository_id": _orchestration_require_string(
            snapshot["repository_id"],
            "/snapshot/repository_id",
            stable_id=True,
        ),
    }
    for field in (
        "repository_identity_sha256",
        "initial_worktree_fingerprint_sha256",
        "worktree_fingerprint_sha256",
        "repository_common_dir_sha256",
        "ownership_claim_sha256",
        "git_state_sha256",
        "changed_paths_sha256",
    ):
        normalized[field] = _orchestration_require_digest(
            snapshot[field], f"/snapshot/{field}"
        )
    for field in (
        "complete",
        "active_writer",
        "mutation_quarantine",
    ):
        normalized[field] = _orchestration_require_bool(
            snapshot[field], f"/snapshot/{field}"
        )
    if require_safe:
        if not normalized["complete"]:
            raise _orchestration_error(
                "WORKTREE_POSTCONDITION_INCOMPLETE",
                "reconciliation requires a complete worktree snapshot",
                pointer="/snapshot/complete",
            )
        if normalized["active_writer"]:
            raise _orchestration_error(
                "WORKTREE_ACTIVE_WRITER",
                "worktree still has an observed active writer",
                pointer="/snapshot/active_writer",
            )
        if normalized["mutation_quarantine"]:
            raise _orchestration_error(
                "WORKTREE_MUTATION_QUARANTINED",
                "worktree has unresolved mutation quarantine",
                pointer="/snapshot/mutation_quarantine",
            )
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def _orchestration_snapshot_matches_lease(
    snapshot: Mapping[str, object],
    lease: Mapping[str, object],
) -> None:
    mismatched = []
    for snapshot_field, lease_field in (
        ("repository_id", "repository_id"),
        ("repository_identity_sha256", "repository_identity_sha256"),
        (
            "initial_worktree_fingerprint_sha256",
            "worktree_fingerprint_sha256",
        ),
        (
            "repository_common_dir_sha256",
            "repository_common_dir_sha256",
        ),
        ("ownership_claim_sha256", "ownership_claim_sha256"),
    ):
        if snapshot[snapshot_field] != lease[lease_field]:
            mismatched.append(snapshot_field)
    if mismatched:
        raise _orchestration_error(
            "WORKTREE_POSTCONDITION_BINDING_MISMATCH",
            "worktree snapshot does not belong to the lease repository",
            pointer="/snapshot",
            details={"fields": mismatched},
        )


def authenticate_runtime_stop(
    lease_value: object,
    observation_value: object,
    *,
    authentication_verifier: Callable[
        [Mapping[str, object], Mapping[str, object]], bool
    ],
) -> AuthenticatedRuntimeStop:
    """Authenticate stop for the exact runtime and host assignment."""

    lease = validate_runtime_lease_state(lease_value)
    observation = _orchestration_require_mapping(
        observation_value, "/runtime_stop"
    )
    _orchestration_validate_json(observation, "/runtime_stop")
    _orchestration_reject_unknown(
        observation,
        _orchestration_runtime_stop_fields,
        "/runtime_stop",
        code="RUNTIME_STOP_INVALID",
    )
    _orchestration_require_fields(
        observation,
        _orchestration_runtime_stop_fields,
        "/runtime_stop",
        code="RUNTIME_STOP_INVALID",
    )
    if observation["schema"] != RUNTIME_STOP_OBSERVATION_SCHEMA:
        raise _orchestration_error(
            "RUNTIME_STOP_SCHEMA_UNSUPPORTED",
            "runtime stop observation schema is unsupported",
            pointer="/runtime_stop/schema",
        )
    normalized: dict[str, object] = {
        "schema": RUNTIME_STOP_OBSERVATION_SCHEMA
    }
    for field in (
        "task_id",
        "node_instance_id",
        "assignment_id",
        "lease_id",
        "host_assignment_id",
    ):
        normalized[field] = _orchestration_require_string(
            observation[field],
            f"/runtime_stop/{field}",
            stable_id=True,
        )
    runtime_handle_id = observation["runtime_handle_id"]
    normalized["runtime_handle_id"] = (
        None
        if runtime_handle_id is None
        else _orchestration_require_string(
            runtime_handle_id,
            "/runtime_stop/runtime_handle_id",
            stable_id=True,
        )
    )
    normalized["attempt"] = _orchestration_require_int(
        observation["attempt"],
        "/runtime_stop/attempt",
        minimum=1,
    )
    normalized["authentication_sha256"] = (
        _orchestration_require_digest(
            observation["authentication_sha256"],
            "/runtime_stop/authentication_sha256",
        )
    )
    normalized["stopped"] = _orchestration_require_bool(
        observation["stopped"], "/runtime_stop/stopped"
    )
    binding_fields = (
        "task_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "runtime_handle_id",
        "host_assignment_id",
    )
    if lease["runtime_handle_id"] is None:
        raise _orchestration_error(
            "RUNTIME_STOP_HANDLE_REQUIRED",
            "authenticated runtime stop requires a persisted runtime handle",
            pointer="/lease/runtime_handle_id",
        )
    mismatched = [
        field
        for field in binding_fields
        if normalized[field] != lease[field]
    ]
    if mismatched:
        raise _orchestration_error(
            "RUNTIME_STOP_BINDING_MISMATCH",
            "runtime stop does not bind the exact lease assignment",
            pointer="/runtime_stop",
            details={"fields": mismatched},
        )
    if not hmac.compare_digest(
        str(normalized["authentication_sha256"]),
        str(lease["runtime_authentication_sha256"]),
    ):
        raise _orchestration_error(
            "RUNTIME_STOP_AUTHENTICATION_FAILED",
            "runtime stop authentication does not match the lease",
            pointer="/runtime_stop/authentication_sha256",
        )
    if not normalized["stopped"]:
        raise _orchestration_error(
            "RUNTIME_STOP_NOT_ESTABLISHED",
            "runtime stop observation does not establish exit",
            pointer="/runtime_stop/stopped",
        )
    if not callable(authentication_verifier):
        raise _orchestration_error(
            "RUNTIME_STOP_VERIFIER_INVALID",
            "runtime stop authentication verifier must be callable",
            pointer="/authentication_verifier",
        )
    frozen_observation = _orchestration_freeze(normalized)
    assert isinstance(frozen_observation, Mapping)
    try:
        verified = authentication_verifier(
            lease, frozen_observation
        )
    except Exception as exc:
        raise _orchestration_error(
            "RUNTIME_STOP_VERIFIER_FAILED",
            "runtime stop authentication verifier failed",
            pointer="/authentication_verifier",
            details={"type": type(exc).__name__},
        ) from exc
    if not isinstance(verified, bool) or not verified:
        raise _orchestration_error(
            "RUNTIME_STOP_AUTHENTICATION_FAILED",
            "runtime stop proof was not authenticated by the host verifier",
            pointer="/runtime_stop",
        )
    digest, _ = _orchestration_domain_identity(
        LEASE_QUIESCENCE_DOMAIN, frozen_observation
    )
    return AuthenticatedRuntimeStop(
        lease_id=str(lease["lease_id"]),
        assignment_id=str(lease["assignment_id"]),
        runtime_handle_id=lease["runtime_handle_id"],
        host_assignment_id=str(lease["host_assignment_id"]),
        observation_sha256=digest,
    )


def _orchestration_quiescence_proof(
    lease: Mapping[str, object],
    *,
    method: str,
    snapshot: Mapping[str, object],
    evidence: Mapping[str, object],
) -> LeaseQuiescenceProof:
    lease_binding = {
        str(key): _orchestration_thaw(item)
        for key, item in lease.items()
        if key != "status"
    }
    payload = {
        "schema": LEASE_QUIESCENCE_PROOF_SCHEMA,
        "lease_binding": lease_binding,
        "lease_status_at_proof": lease["status"],
        "method": method,
        "snapshot": _orchestration_thaw(snapshot),
        "evidence": _orchestration_thaw(evidence),
    }
    digest, canonical = _orchestration_domain_identity(
        LEASE_QUIESCENCE_DOMAIN, payload
    )
    return LeaseQuiescenceProof(
        lease_id=str(lease["lease_id"]),
        assignment_id=str(lease["assignment_id"]),
        method=method,
        worktree_fingerprint_sha256=str(
            snapshot["worktree_fingerprint_sha256"]
        ),
        proof_sha256=digest,
        quiesced=True,
        canonical_bytes=canonical,
    )


def validate_lease_quiescence_proof(
    lease_value: object,
    proof: object,
) -> LeaseQuiescenceProof:
    """Verify persisted proof bytes and their exact runtime-lease binding."""

    lease = validate_runtime_lease_state(lease_value)
    if not isinstance(proof, LeaseQuiescenceProof):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease quiescence proof object is required",
            pointer="/quiescence_proof",
        )
    projected_lease_id = _orchestration_require_string(
        proof.lease_id,
        "/quiescence_proof/lease_id",
        stable_id=True,
    )
    projected_assignment_id = _orchestration_require_string(
        proof.assignment_id,
        "/quiescence_proof/assignment_id",
        stable_id=True,
    )
    projected_method = _orchestration_require_string(
        proof.method, "/quiescence_proof/method"
    )
    projected_worktree = _orchestration_require_digest(
        proof.worktree_fingerprint_sha256,
        "/quiescence_proof/worktree_fingerprint_sha256",
    )
    projected_digest = _orchestration_require_digest(
        proof.proof_sha256,
        "/quiescence_proof/proof_sha256",
    )
    if not _orchestration_require_bool(
        proof.quiesced, "/quiescence_proof/quiesced"
    ):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease quiescence proof must establish quiescence",
            pointer="/quiescence_proof/quiesced",
        )
    if not isinstance(proof.canonical_bytes, bytes):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease quiescence proof content must be immutable bytes",
            pointer="/quiescence_proof/canonical_bytes",
        )
    computed = hashlib.sha256(
        LEASE_QUIESCENCE_DOMAIN
        + _orchestration_u64be(len(proof.canonical_bytes))
        + proof.canonical_bytes
    ).hexdigest()
    if not hmac.compare_digest(computed, projected_digest):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_IDENTITY_MISMATCH",
            "lease quiescence proof identity does not match its bytes",
            pointer="/quiescence_proof/proof_sha256",
        )
    try:
        payload = json.loads(
            proof.canonical_bytes.decode("utf-8", errors="strict")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease quiescence proof bytes are not canonical JSON",
            pointer="/quiescence_proof/canonical_bytes",
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or _orchestration_canonical_bytes(payload)
        != proof.canonical_bytes
    ):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease quiescence proof bytes are not canonical",
            pointer="/quiescence_proof/canonical_bytes",
        )
    required_fields = frozenset(
        {
            "schema",
            "lease_binding",
            "lease_status_at_proof",
            "method",
            "snapshot",
            "evidence",
        }
    )
    _orchestration_reject_unknown(
        payload,
        required_fields,
        "/quiescence_proof",
        code="LEASE_QUIESCENCE_PROOF_INVALID",
    )
    _orchestration_require_fields(
        payload,
        required_fields,
        "/quiescence_proof",
        code="LEASE_QUIESCENCE_PROOF_INVALID",
    )
    if payload["schema"] != LEASE_QUIESCENCE_PROOF_SCHEMA:
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_SCHEMA_UNSUPPORTED",
            "lease quiescence proof schema is unsupported",
            pointer="/quiescence_proof/schema",
        )
    method = _orchestration_require_string(
        payload["method"], "/quiescence_proof/method"
    )
    if method not in {
        "authenticated-runtime-stop",
        "stable-postcondition-reconciliation",
    }:
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_METHOD_UNSUPPORTED",
            "lease quiescence proof method is unsupported",
            pointer="/quiescence_proof/method",
        )
    lease_binding = _orchestration_require_mapping(
        payload["lease_binding"],
        "/quiescence_proof/lease_binding",
    )
    expected_binding = {
        str(key): _orchestration_thaw(item)
        for key, item in lease.items()
        if key != "status"
    }
    if _orchestration_thaw(lease_binding) != expected_binding:
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_BINDING_MISMATCH",
            "lease quiescence proof belongs to a different lease binding",
            pointer="/quiescence_proof/lease_binding",
        )
    status_at_proof = _orchestration_require_string(
        payload["lease_status_at_proof"],
        "/quiescence_proof/lease_status_at_proof",
    )
    if status_at_proof not in _orchestration_lease_statuses:
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_INVALID",
            "lease status at proof is unsupported",
            pointer="/quiescence_proof/lease_status_at_proof",
        )
    snapshot = _orchestration_validate_worktree_snapshot(
        payload["snapshot"], require_safe=True
    )
    _orchestration_snapshot_matches_lease(snapshot, lease)
    _orchestration_require_mapping(
        payload["evidence"], "/quiescence_proof/evidence"
    )
    if (
        projected_lease_id != lease["lease_id"]
        or projected_assignment_id != lease["assignment_id"]
        or projected_method != method
        or projected_worktree
        != snapshot["worktree_fingerprint_sha256"]
    ):
        raise _orchestration_error(
            "LEASE_QUIESCENCE_PROOF_BINDING_MISMATCH",
            "lease quiescence proof projection differs from its bytes",
            pointer="/quiescence_proof",
        )
    return proof


def prove_quiescence_from_runtime_stop(
    lease_value: object,
    stop: AuthenticatedRuntimeStop,
    post_stop_snapshot_value: object,
) -> LeaseQuiescenceProof:
    """Require authenticated stop plus one complete post-stop snapshot."""

    lease = validate_runtime_lease_state(lease_value)
    if not isinstance(stop, AuthenticatedRuntimeStop):
        raise _orchestration_error(
            "RUNTIME_STOP_PROOF_INVALID",
            "authenticated runtime stop proof is required",
            pointer="/runtime_stop",
        )
    if (
        stop.lease_id != lease["lease_id"]
        or stop.assignment_id != lease["assignment_id"]
        or stop.runtime_handle_id != lease["runtime_handle_id"]
        or stop.host_assignment_id != lease["host_assignment_id"]
    ):
        raise _orchestration_error(
            "RUNTIME_STOP_PROOF_MISMATCH",
            "runtime stop proof belongs to a different lease",
            pointer="/runtime_stop",
        )
    snapshot = _orchestration_validate_worktree_snapshot(
        post_stop_snapshot_value, require_safe=True
    )
    _orchestration_snapshot_matches_lease(snapshot, lease)
    return _orchestration_quiescence_proof(
        lease,
        method="authenticated-runtime-stop",
        snapshot=snapshot,
        evidence=MappingProxyType(
            {"runtime_stop_sha256": stop.observation_sha256}
        ),
    )


def _orchestration_validate_stability_interval(
    value: object,
) -> int:
    interval = _orchestration_require_int(
        value, "/required_stability_ns", minimum=0
    )
    if interval < KERNEL_MINIMUM_STABILITY_NS:
        raise _orchestration_error(
            "STABILITY_INTERVAL_BELOW_KERNEL_MINIMUM",
            "stability interval cannot reduce the positive kernel minimum",
            pointer="/required_stability_ns",
            details={
                "minimum": KERNEL_MINIMUM_STABILITY_NS,
                "requested": interval,
            },
        )
    return interval


def begin_stable_reconciliation(
    lease_value: object,
    first_snapshot_value: object,
    *,
    monotonic_ns: Callable[[], int],
    clock_id: str,
    required_stability_ns: int = KERNEL_MINIMUM_STABILITY_NS,
    reason: str,
    termination_confirmed: bool,
    operator_isolation_confirmed: bool,
    termination_evidence_sha256: Optional[str] = None,
    operator_isolation_evidence_sha256: Optional[str] = None,
) -> StableReconciliationProbe:
    """Capture the first complete safe snapshot using an injected clock."""

    lease = validate_runtime_lease_state(lease_value)
    if lease["status"] not in {
        "REVOCATION_REQUESTED",
        "REVOKED",
        "EXPIRED",
        "ORPHANED",
    }:
        raise _orchestration_error(
            "STABLE_RECONCILIATION_LEASE_ACTIVE",
            "active or already-quiesced lease cannot begin reconciliation",
            pointer="/lease/status",
        )
    interval = _orchestration_validate_stability_interval(
        required_stability_ns
    )
    reconciliation_clock_id = _orchestration_require_string(
        clock_id, "/clock_id", stable_id=True
    )
    parsed_reason = _orchestration_require_string(
        reason, "/reason"
    )
    termination = _orchestration_require_bool(
        termination_confirmed, "/termination_confirmed"
    )
    isolation = _orchestration_require_bool(
        operator_isolation_confirmed,
        "/operator_isolation_confirmed",
    )
    if not (termination or isolation):
        raise _orchestration_error(
            "TERMINATION_OR_ISOLATION_NOT_CONFIRMED",
            "stable reconciliation requires termination or operator isolation",
            pointer="/termination_confirmed",
        )
    termination_evidence = (
        _orchestration_require_digest(
            termination_evidence_sha256,
            "/termination_evidence_sha256",
        )
        if termination_evidence_sha256 is not None
        else None
    )
    isolation_evidence = (
        _orchestration_require_digest(
            operator_isolation_evidence_sha256,
            "/operator_isolation_evidence_sha256",
        )
        if operator_isolation_evidence_sha256 is not None
        else None
    )
    if termination != (termination_evidence is not None):
        raise _orchestration_error(
            "TERMINATION_EVIDENCE_INVALID",
            "termination confirmation and evidence digest must appear together",
            pointer="/termination_evidence_sha256",
        )
    if isolation != (isolation_evidence is not None):
        raise _orchestration_error(
            "ISOLATION_EVIDENCE_INVALID",
            "operator isolation and evidence digest must appear together",
            pointer="/operator_isolation_evidence_sha256",
        )
    snapshot = _orchestration_validate_worktree_snapshot(
        first_snapshot_value, require_safe=True
    )
    _orchestration_snapshot_matches_lease(snapshot, lease)
    snapshot_digest = hashlib.sha256(
        _orchestration_canonical_bytes(snapshot)
    ).hexdigest()
    lease_binding = {
        str(key): _orchestration_thaw(item)
        for key, item in lease.items()
        if key != "status"
    }
    lease_binding_sha256 = hashlib.sha256(
        _orchestration_canonical_bytes(lease_binding)
    ).hexdigest()
    return StableReconciliationProbe(
        lease_id=str(lease["lease_id"]),
        assignment_id=str(lease["assignment_id"]),
        lease_binding_sha256=lease_binding_sha256,
        clock_id=reconciliation_clock_id,
        started_monotonic_ns=_orchestration_read_monotonic_ns(
            monotonic_ns
        ),
        required_stability_ns=interval,
        snapshot_sha256=snapshot_digest,
        snapshot=snapshot,
        reason=parsed_reason,
        termination_confirmed=termination,
        termination_evidence_sha256=termination_evidence,
        operator_isolation_confirmed=isolation,
        operator_isolation_evidence_sha256=isolation_evidence,
    )


def complete_stable_reconciliation(
    lease_value: object,
    probe: StableReconciliationProbe,
    second_snapshot_value: object,
    *,
    monotonic_ns: Callable[[], int],
    clock_id: str,
) -> LeaseQuiescenceProof:
    """Require two byte-equal complete snapshots across the kernel interval."""

    lease = validate_runtime_lease_state(lease_value)
    if not isinstance(probe, StableReconciliationProbe):
        raise _orchestration_error(
            "STABLE_RECONCILIATION_PROBE_INVALID",
            "stable reconciliation probe is required",
            pointer="/probe",
        )
    if (
        probe.lease_id != lease["lease_id"]
        or probe.assignment_id != lease["assignment_id"]
    ):
        raise _orchestration_error(
            "STABLE_RECONCILIATION_PROBE_MISMATCH",
            "stable reconciliation probe belongs to another lease",
            pointer="/probe",
        )
    current_lease_binding = {
        str(key): _orchestration_thaw(item)
        for key, item in lease.items()
        if key != "status"
    }
    if hashlib.sha256(
        _orchestration_canonical_bytes(current_lease_binding)
    ).hexdigest() != probe.lease_binding_sha256:
        raise _orchestration_error(
            "STABLE_RECONCILIATION_LEASE_DRIFT",
            "lease binding changed during stable reconciliation",
            pointer="/lease",
        )
    _orchestration_validate_stability_interval(
        probe.required_stability_ns
    )
    observed_clock_id = _orchestration_require_string(
        clock_id, "/clock_id", stable_id=True
    )
    if observed_clock_id != probe.clock_id:
        raise _orchestration_error(
            "MONOTONIC_CLOCK_ID_MISMATCH",
            "stable reconciliation must use one monotonic clock",
            pointer="/clock_id",
        )
    second = _orchestration_validate_worktree_snapshot(
        second_snapshot_value, require_safe=True
    )
    _orchestration_snapshot_matches_lease(second, lease)
    finished = _orchestration_read_monotonic_ns(monotonic_ns)
    if finished < probe.started_monotonic_ns:
        raise _orchestration_error(
            "MONOTONIC_CLOCK_REVERSED",
            "monotonic clock moved backwards",
            pointer="/monotonic_ns",
        )
    elapsed = finished - probe.started_monotonic_ns
    if elapsed < probe.required_stability_ns:
        raise _orchestration_error(
            "STABLE_RECONCILIATION_INTERVAL_INCOMPLETE",
            "second snapshot was captured before the stability interval",
            pointer="/monotonic_ns",
            details={
                "required": probe.required_stability_ns,
                "observed": elapsed,
            },
        )
    second_bytes = _orchestration_canonical_bytes(second)
    second_digest = hashlib.sha256(second_bytes).hexdigest()
    if (
        second_digest != probe.snapshot_sha256
        or second_bytes
        != _orchestration_canonical_bytes(probe.snapshot)
    ):
        raise _orchestration_error(
            "STABLE_RECONCILIATION_SNAPSHOT_CHANGED",
            "complete worktree snapshots differ across the interval",
            pointer="/snapshot",
        )
    return _orchestration_quiescence_proof(
        lease,
        method="stable-postcondition-reconciliation",
        snapshot=second,
        evidence=MappingProxyType(
            {
                "first_snapshot_sha256": probe.snapshot_sha256,
                "second_snapshot_sha256": second_digest,
                "started_monotonic_ns": (
                    probe.started_monotonic_ns
                ),
                "finished_monotonic_ns": finished,
                "required_stability_ns": (
                    probe.required_stability_ns
                ),
                "clock_id": probe.clock_id,
                "reason": probe.reason,
                "termination_confirmed": (
                    probe.termination_confirmed
                ),
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
        ),
    )


def _orchestration_validate_runtime_recovery_observation(
    value: object,
) -> Mapping[str, object]:
    observation = _orchestration_require_mapping(
        value, "/runtime_recovery"
    )
    _orchestration_validate_json(
        observation, "/runtime_recovery"
    )
    _orchestration_reject_unknown(
        observation,
        _orchestration_runtime_recovery_fields,
        "/runtime_recovery",
        code="RUNTIME_RECOVERY_OBSERVATION_INVALID",
    )
    _orchestration_require_fields(
        observation,
        _orchestration_runtime_recovery_fields,
        "/runtime_recovery",
        code="RUNTIME_RECOVERY_OBSERVATION_INVALID",
    )
    if observation["schema"] != RUNTIME_RECOVERY_OBSERVATION_SCHEMA:
        raise _orchestration_error(
            "RUNTIME_RECOVERY_SCHEMA_UNSUPPORTED",
            "runtime recovery observation schema is unsupported",
            pointer="/runtime_recovery/schema",
        )
    normalized: dict[str, object] = {
        "schema": RUNTIME_RECOVERY_OBSERVATION_SCHEMA
    }
    for field in (
        "task_id",
        "node_instance_id",
        "assignment_id",
        "lease_id",
        "host_assignment_id",
    ):
        normalized[field] = _orchestration_require_string(
            observation[field],
            f"/runtime_recovery/{field}",
            stable_id=True,
        )
    runtime_handle_id = observation["runtime_handle_id"]
    normalized["runtime_handle_id"] = (
        None
        if runtime_handle_id is None
        else _orchestration_require_string(
            runtime_handle_id,
            "/runtime_recovery/runtime_handle_id",
            stable_id=True,
        )
    )
    normalized["attempt"] = _orchestration_require_int(
        observation["attempt"],
        "/runtime_recovery/attempt",
        minimum=1,
    )
    normalized["worktree_fingerprint_sha256"] = (
        _orchestration_require_digest(
            observation["worktree_fingerprint_sha256"],
            "/runtime_recovery/worktree_fingerprint_sha256",
        )
    )
    for field in ("found", "authenticated", "live"):
        normalized[field] = _orchestration_require_bool(
            observation[field], f"/runtime_recovery/{field}"
        )
    if not normalized["found"] and (
        normalized["authenticated"] or normalized["live"]
    ):
        raise _orchestration_error(
            "RUNTIME_RECOVERY_OBSERVATION_CONTRADICTORY",
            "missing runtime cannot be authenticated or live",
            pointer="/runtime_recovery",
        )
    if normalized["authenticated"] and not normalized["found"]:
        raise _orchestration_error(
            "RUNTIME_RECOVERY_OBSERVATION_CONTRADICTORY",
            "authenticated runtime must have been found",
            pointer="/runtime_recovery/authenticated",
        )
    return _orchestration_freeze(normalized)  # type: ignore[return-value]


def evaluate_runtime_recovery(
    lease_value: object,
    observation_value: object,
    *,
    monotonic_ns: Callable[[], int],
    clock_id: str,
) -> RuntimeRecoveryDecision:
    """Classify reattachment or orphan uncertainty without redispatch."""

    lease = validate_runtime_lease_state(lease_value)
    observation = (
        _orchestration_validate_runtime_recovery_observation(
            observation_value
        )
    )
    now = _orchestration_read_monotonic_ns(monotonic_ns)
    observed_clock_id = _orchestration_require_string(
        clock_id, "/clock_id", stable_id=True
    )
    if observed_clock_id != lease["clock_id"]:
        raise _orchestration_error(
            "MONOTONIC_CLOCK_ID_MISMATCH",
            "runtime recovery cannot compare lease expiry on another clock",
            pointer="/clock_id",
        )
    binding_fields = (
        "task_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "runtime_handle_id",
        "host_assignment_id",
    )
    binding_mismatch = [
        field
        for field in binding_fields
        if observation[field] != lease[field]
    ]
    worktree_drift = (
        observation["worktree_fingerprint_sha256"]
        != lease["worktree_fingerprint_sha256"]
    )
    expired = now >= int(lease["expires_monotonic_ns"])
    status = str(lease["status"])
    blockers: set[str] = set()
    if binding_mismatch:
        blockers.add("RUNTIME_BINDING_MISMATCH")
    if worktree_drift:
        blockers.add("WORKTREE_FINGERPRINT_DRIFT")
    if expired or status == "EXPIRED":
        blockers.add("LEASE_EXPIRED")
    if status in {"REVOCATION_REQUESTED", "REVOKED"}:
        blockers.add("LEASE_REVOKED")
    if observation["live"] and (
        expired
        or status
        in {"REVOCATION_REQUESTED", "REVOKED", "ORPHANED"}
    ):
        blockers.add("REVOKED_OR_EXPIRED_RUNTIME_LIVE")
        recovery_status = "REVOKED_OR_EXPIRED_LIVE"
    elif (
        status == "ACTIVE"
        and not expired
        and observation["found"]
        and observation["authenticated"]
        and observation["live"]
        and not binding_mismatch
        and not worktree_drift
    ):
        return RuntimeRecoveryDecision(
            status="REATTACH",
            reattach=True,
            orphaned=False,
            quiesced=False,
            replacement_allowed=False,
            blockers=(),
        )
    else:
        if not observation["found"]:
            blockers.add("RUNTIME_NOT_OBSERVED")
        elif not observation["authenticated"]:
            blockers.add("RUNTIME_NOT_AUTHENTICATED")
        elif not observation["live"]:
            blockers.add("RUNTIME_STOP_NOT_AUTHENTICATED")
        blockers.add("TERMINATION_UNCERTAIN")
        recovery_status = "ORPHANED_UNCERTAIN"
    return RuntimeRecoveryDecision(
        status=recovery_status,
        reattach=False,
        orphaned=True,
        quiesced=False,
        replacement_allowed=False,
        blockers=tuple(
            sorted(blockers, key=_orchestration_utf8_key)
        ),
    )


def authorize_replacement_lease(
    prior_lease_value: object,
    quiescence_proof: Optional[LeaseQuiescenceProof],
    *,
    next_attempt: int,
    worktree_strategy: str,
    worktree_fingerprint_sha256: str,
) -> ReplacementLeaseCandidate:
    """Refuse replacement until revocation and quiescence are both proven."""

    lease = validate_runtime_lease_state(prior_lease_value)
    if lease["status"] not in _orchestration_terminal_lease_statuses:
        raise _orchestration_error(
            "REPLACEMENT_LEASE_PRIOR_NOT_REVOKED",
            "replacement requires prior lease revocation or expiry",
            pointer="/lease/status",
            details={"status": lease["status"]},
        )
    if (
        not isinstance(quiescence_proof, LeaseQuiescenceProof)
    ):
        raise _orchestration_error(
            "REPLACEMENT_LEASE_QUIESCENCE_REQUIRED",
            "revocation or expiry alone does not authorize replacement",
            pointer="/quiescence_proof",
        )
    validated_proof = validate_lease_quiescence_proof(
        lease, quiescence_proof
    )
    parsed_attempt = _orchestration_require_int(
        next_attempt, "/next_attempt", minimum=2
    )
    if parsed_attempt != int(lease["attempt"]) + 1:
        raise _orchestration_error(
            "REPLACEMENT_LEASE_ATTEMPT_INVALID",
            "replacement attempt must increment exactly once",
            pointer="/next_attempt",
            details={
                "previous": lease["attempt"],
                "requested": parsed_attempt,
            },
        )
    strategy = _orchestration_require_string(
        worktree_strategy, "/worktree_strategy"
    )
    if strategy not in {"resume-verified", "separate-planned"}:
        raise _orchestration_error(
            "REPLACEMENT_LEASE_STRATEGY_INVALID",
            "replacement worktree strategy is unsupported",
            pointer="/worktree_strategy",
        )
    fingerprint = _orchestration_require_digest(
        worktree_fingerprint_sha256,
        "/worktree_fingerprint_sha256",
    )
    if (
        strategy == "resume-verified"
        and fingerprint
        != validated_proof.worktree_fingerprint_sha256
    ):
        raise _orchestration_error(
            "RETRY_WORKTREE_DRIFT",
            "resumed worktree differs from quiesced evidence",
            pointer="/worktree_fingerprint_sha256",
        )
    return ReplacementLeaseCandidate(
        prior_lease_id=str(lease["lease_id"]),
        next_attempt=parsed_attempt,
        worktree_strategy=strategy,
        worktree_fingerprint_sha256=fingerprint,
        authorized=True,
    )


def build_retry_candidate(
    prior_result_value: object,
    prior_lease_value: object,
    quiescence_proof: Optional[LeaseQuiescenceProof],
    retry_policy_value: object,
    *,
    expected_revision: int,
    current_revision: int,
    retry_approval_current: bool,
    worktree_strategy: str,
    worktree_fingerprint_sha256: str,
) -> RetryCandidate:
    """Build a bounded retry candidate while retaining prior attempt facts."""

    accepted_record = _orchestration_validate_accepted_result(
        prior_result_value, pointer="/prior_result"
    )
    if not accepted_record["accepted"] or not accepted_record["current"]:
        raise _orchestration_error(
            "RETRY_PRIOR_RESULT_NOT_CURRENT",
            "retry requires a current accepted prior attempt result",
            pointer="/prior_result",
        )
    result = accepted_record["result"]
    assert isinstance(result, Mapping)
    lease = validate_runtime_lease_state(prior_lease_value)
    if (
        result["node_instance_id"] != lease["node_instance_id"]
        or result["attempt"] != lease["attempt"]
        or result["lease_id"] != lease["lease_id"]
    ):
        raise _orchestration_error(
            "RETRY_PRIOR_ATTEMPT_MISMATCH",
            "retry result and prior lease do not identify one attempt",
            pointer="/prior_result",
        )
    policy = _orchestration_require_mapping(
        retry_policy_value, "/retry_policy"
    )
    _orchestration_reject_unknown(
        policy,
        _orchestration_retry_policy_fields,
        "/retry_policy",
        code="RETRY_POLICY_INVALID",
    )
    _orchestration_require_fields(
        policy,
        _orchestration_retry_policy_fields,
        "/retry_policy",
        code="RETRY_POLICY_INVALID",
    )
    max_attempts = _orchestration_require_int(
        policy["max_attempts"],
        "/retry_policy/max_attempts",
        minimum=1,
    )
    retryable = _orchestration_require_ordered_strings(
        policy["retryable_outcomes"],
        "/retry_policy/retryable_outcomes",
        allowed=frozenset({"FAILED", "BLOCKED"}),
    )
    requires_approval = _orchestration_require_bool(
        policy["requires_approval"],
        "/retry_policy/requires_approval",
    )
    approval_current = _orchestration_require_bool(
        retry_approval_current, "/retry_approval_current"
    )
    if result["outcome"] not in retryable:
        raise _orchestration_error(
            "RETRY_OUTCOME_NOT_ALLOWED",
            "prior result outcome is not retryable",
            pointer="/prior_result/outcome",
            details={"outcome": result["outcome"]},
        )
    next_attempt = int(result["attempt"]) + 1
    if next_attempt > max_attempts:
        raise _orchestration_error(
            "RETRY_ATTEMPTS_EXHAUSTED",
            "retry policy has no remaining attempt",
            pointer="/retry_policy/max_attempts",
            details={
                "max_attempts": max_attempts,
                "next_attempt": next_attempt,
            },
        )
    if requires_approval and not approval_current:
        raise _orchestration_error(
            "RETRY_APPROVAL_REQUIRED",
            "retry requires a current explicit approval",
            pointer="/retry_approval_current",
        )
    requested_revision = _orchestration_require_int(
        expected_revision, "/expected_revision"
    )
    actual_revision = _orchestration_require_int(
        current_revision, "/current_revision"
    )
    if requested_revision != actual_revision:
        raise _orchestration_error(
            "RETRY_REVISION_CONFLICT",
            "retry expected revision is stale",
            pointer="/expected_revision",
            details={
                "expected": requested_revision,
                "current": actual_revision,
            },
        )
    if actual_revision == _orchestration_signed_int64_max:
        raise _orchestration_error(
            "RETRY_REVISION_EXHAUSTED",
            "task revision cannot be incremented",
            pointer="/current_revision",
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
    if (
        not isinstance(quiescence_proof, LeaseQuiescenceProof)
        or quiescence_proof.worktree_fingerprint_sha256
        != result["worktree_sha256"]
    ):
        raise _orchestration_error(
            "RETRY_WORKTREE_DRIFT",
            "failed-attempt worktree differs from quiescence evidence",
            pointer="/quiescence_proof",
        )
    return RetryCandidate(
        node_instance_id=str(result["node_instance_id"]),
        previous_attempt=int(result["attempt"]),
        next_attempt=replacement.next_attempt,
        expected_revision=requested_revision,
        candidate_revision=actual_revision + 1,
        worktree_strategy=replacement.worktree_strategy,
        worktree_fingerprint_sha256=(
            replacement.worktree_fingerprint_sha256
        ),
    )


def evaluate_cancellation_quiescence(
    lease_values: Sequence[object],
    quiescence_proofs: Mapping[str, LeaseQuiescenceProof],
) -> CancellationQuiescence:
    """Close cancellation only after every affected lease has exact proof."""

    leases = tuple(
        validate_runtime_lease_state(value)
        for value in lease_values
    )
    proofs = _orchestration_require_mapping(
        quiescence_proofs, "/quiescence_proofs"
    )
    known_ids = {str(lease["lease_id"]) for lease in leases}
    unknown = sorted(
        set(proofs) - known_ids, key=_orchestration_utf8_key
    )
    if unknown:
        raise _orchestration_error(
            "CANCELLATION_QUIESCENCE_UNKNOWN_LEASE",
            "quiescence proofs name leases outside cancellation",
            pointer="/quiescence_proofs",
            details={"lease_ids": unknown},
        )
    uncertain: list[str] = []
    for lease in leases:
        lease_id = str(lease["lease_id"])
        proof = proofs.get(lease_id)
        if (
            not isinstance(proof, LeaseQuiescenceProof)
        ):
            uncertain.append(lease_id)
            continue
        try:
            validate_lease_quiescence_proof(lease, proof)
        except OrchestrationResultError:
            uncertain.append(lease_id)
    uncertain_tuple = tuple(
        sorted(uncertain, key=_orchestration_utf8_key)
    )
    return CancellationQuiescence(
        requested=True,
        quiesced=not uncertain_tuple,
        uncertain_lease_ids=uncertain_tuple,
    )
