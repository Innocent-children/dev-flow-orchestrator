# Loaded by scripts/dev_flow.py only after controller integration is ready.
# This fragment is deliberately pure: artifact persistence, approval commits,
# task-state mutation, leases, dispatch, and Git effects remain controller
# responsibilities supplied by a future integration layer.
from __future__ import annotations

import hashlib
import json
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence


REPOSITORY_PLAN_SCHEMA = "dev-flow-repository-plan/v1"
REPOSITORY_PLAN_APPROVAL_SCHEMA = (
    "dev-flow-repository-plan-approval/v1"
)
REPOSITORY_MAP_EXPANSION_SCHEMA = (
    "dev-flow-repository-map-expansion/v1"
)
REPOSITORY_PLAN_DOMAIN = b"dev-flow-repository-plan-v1\x00"
REPOSITORY_PLAN_SEMANTIC_INPUT_DOMAIN = (
    b"dev-flow-repository-plan-semantic-input-v1\x00"
)
REPOSITORY_NODE_INSTANCE_DOMAIN = (
    b"dev-flow-repository-node-instance-v1\x00"
)
REPOSITORY_MAP_EXPANSION_DOMAIN = (
    b"dev-flow-repository-map-expansion-v1\x00"
)

_repository_plan_signed_int64_min = -(2**63)
_repository_plan_signed_int64_max = 2**63 - 1
_repository_plan_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_repository_plan_stable_id_re = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$"
)
_repository_plan_glob_characters = frozenset("*?[]")
_repository_plan_retryable_states = frozenset({"FAILED", "BLOCKED"})
_repository_plan_node_states = frozenset(
    {
        "PENDING",
        "READY",
        "RUNNING",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
        "BLOCKED",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
    }
)
_repository_plan_candidate_states = frozenset(
    {"PENDING", "READY", "WAITING_APPROVAL", "WAITING_EXTERNAL"}
)
_repository_plan_write_policies = frozenset(
    {"read-only", "scoped-write"}
)
_repository_plan_top_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "map_node_id",
        "map_epoch",
        "plan_input_revision",
        "semantic_input_sha256",
        "repository_set",
        "repositories",
        "interface_contracts",
        "dependencies",
        "worktree_policy",
        "concurrency_policy",
        "retry_policy",
        "integration_policy",
    }
)
_repository_plan_repository_fields = frozenset(
    {
        "repository_id",
        "identity_sha256",
        "repository_path",
        "approved_paths",
        "write_policy",
        "required_approval_ids",
        "required_evidence_contract_sha256",
    }
)
_repository_plan_contract_fields = frozenset(
    {"contract_id", "artifact_id", "sha256"}
)
_repository_plan_dependency_fields = frozenset(
    {
        "edge_id",
        "from_repository_id",
        "to_repository_id",
        "input_contract_sha256",
        "output_contract_sha256",
        "required_evidence_contract_sha256",
    }
)
_repository_plan_worktree_fields = frozenset(
    {"mode", "require_clean", "distinct"}
)
_repository_plan_concurrency_fields = frozenset(
    {"max_workers", "max_writable_workers"}
)
_repository_plan_retry_fields = frozenset(
    {"max_attempts", "retryable_states", "requires_approval"}
)
_repository_plan_integration_fields = frozenset(
    {"commands", "evidence_contract_sha256"}
)
_repository_plan_approval_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "plan_artifact_id",
        "plan_artifact_sha256",
        "dag_sha256",
        "semantic_input_sha256",
        "plan_input_revision",
        "approval_commit_revision",
        "map_epoch",
        "repository_set",
        "repository_identities",
        "interface_contracts",
        "dependency_edges",
        "approved_paths",
        "execution_policies",
        "approval_intent",
    }
)
_repository_plan_approval_repository_identity_fields = frozenset(
    {"repository_id", "identity_sha256"}
)
_repository_plan_approval_contract_fields = frozenset(
    {"contract_id", "sha256"}
)
_repository_plan_approval_path_fields = frozenset(
    {"repository_id", "paths"}
)
_repository_plan_expansion_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "semantic_input_sha256",
        "map_node_id",
        "map_epoch",
        "repository_set",
        "children",
    }
)
_repository_plan_child_fields = frozenset(
    {
        "node_instance_id",
        "node_id",
        "repository_id",
        "repository_identity_sha256",
        "map_epoch",
        "dependencies",
    }
)
_repository_plan_node_fact_fields = frozenset(
    {"state", "attempts_started"}
)
_repository_plan_result_fields = frozenset(
    {
        "result_id",
        "outcome",
        "accepted",
        "current",
        "output_contract_sha256",
    }
)
_repository_plan_fact_fields = frozenset(
    {"accepted", "current", "repository_id", "result_id"}
)


class RepositoryPlanError(ValueError):
    """Stable structured blocker from the pure repository-plan boundary."""

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


@dataclass(frozen=True)
class RepositoryPlanIdentity:
    """Content identities for one schema-valid repository-plan artifact."""

    task_id: str
    plan_id: str
    semantic_input_sha256: str
    artifact_sha256: str
    dag_sha256: str
    canonical_bytes: bytes


@dataclass(frozen=True)
class RepositoryPlanArtifact:
    """Pure content to be persisted by a task-scoped artifact service."""

    schema: str
    task_id: str
    artifact_id: str
    media_type: str
    sha256: str
    size: int
    dag_sha256: str
    semantic_input_sha256: str
    content: bytes


@dataclass(frozen=True)
class ReadyRepository:
    node_instance_id: str
    repository_id: str
    repository_identity_sha256: str
    attempt: int
    write_policy: str
    dependency_node_instance_ids: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryReadinessBlocker:
    repository_id: str
    codes: tuple[str, ...]


@dataclass(frozen=True)
class RepositoryReadyFrontier:
    """The semantic ready set and the concurrency-limited dispatch subset."""

    ready: tuple[ReadyRepository, ...]
    dispatchable: tuple[ReadyRepository, ...]
    blocked: tuple[RepositoryReadinessBlocker, ...]
    active_workers: int
    active_writable_workers: int
    available_workers: int
    available_writable_workers: int


class _RepositoryPlanJsonSemanticError(Exception):
    def __init__(
        self,
        code: str,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


def _repository_plan_error(
    code: str,
    message: str,
    *,
    pointer: str = "/",
    details: Optional[Mapping[str, object]] = None,
) -> RepositoryPlanError:
    result = {"pointer": pointer}
    result.update(details or {})
    return RepositoryPlanError(code, message, details=result)


def _repository_plan_u64be(value: int) -> bytes:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value < 2**64
    ):
        raise RepositoryPlanError(
            "REPOSITORY_PLAN_U64_INVALID",
            "value does not fit U64BE",
            details={"value": value if isinstance(value, int) else None},
        )
    return struct.pack(">Q", value)


def _repository_plan_utf8_key(value: str) -> bytes:
    return value.encode("utf-8", errors="strict")


def _repository_plan_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _repository_plan_parse_integer(literal: str) -> int:
    negative = literal.startswith("-")
    digits = literal[1:] if negative else literal
    limit = "9223372036854775808" if negative else "9223372036854775807"
    if len(digits) > len(limit) or (
        len(digits) == len(limit) and digits > limit
    ):
        raise _RepositoryPlanJsonSemanticError(
            "REPOSITORY_PLAN_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": literal[:80]},
        )
    return int(literal)


def _repository_plan_reject_float(literal: str) -> object:
    raise _RepositoryPlanJsonSemanticError(
        "REPOSITORY_PLAN_JSON_FLOAT_FORBIDDEN",
        {"literal": literal[:80]},
    )


def _repository_plan_reject_constant(literal: str) -> object:
    raise _RepositoryPlanJsonSemanticError(
        "REPOSITORY_PLAN_JSON_NONFINITE_FORBIDDEN",
        {"literal": literal},
    )


def _repository_plan_strict_object(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _RepositoryPlanJsonSemanticError(
                "REPOSITORY_PLAN_JSON_DUPLICATE_KEY",
                {"key": key},
            )
        result[key] = value
    return result


def _repository_plan_validate_json_value(
    value: object,
    pointer: str = "",
) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not (
            _repository_plan_signed_int64_min
            <= value
            <= _repository_plan_signed_int64_max
        ):
            raise _repository_plan_error(
                "REPOSITORY_PLAN_JSON_INTEGER_OUT_OF_RANGE",
                "JSON integers must fit the signed 64-bit range",
                pointer=pointer or "/",
                details={"value": value},
            )
        return
    if isinstance(value, float):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_JSON_FLOAT_FORBIDDEN",
            "JSON floating-point numbers are forbidden",
            pointer=pointer or "/",
        )
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_JSON_UNICODE_INVALID",
                "JSON strings must be valid UTF-8",
                pointer=pointer or "/",
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_JSON_STRING_NOT_NFC",
                "JSON strings must be NFC",
                pointer=pointer or "/",
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _repository_plan_error(
                    "REPOSITORY_PLAN_JSON_KEY_INVALID",
                    "JSON object keys must be strings",
                    pointer=pointer or "/",
                )
            key_pointer = (
                f"{pointer}/{_repository_plan_pointer_segment(key)}"
            )
            _repository_plan_validate_json_value(key, key_pointer)
            _repository_plan_validate_json_value(item, key_pointer)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _repository_plan_validate_json_value(
                item, f"{pointer}/{index}"
            )
        return
    raise _repository_plan_error(
        "REPOSITORY_PLAN_JSON_VALUE_INVALID",
        "repository plans contain only canonical JSON values",
        pointer=pointer or "/",
        details={"type": type(value).__name__},
    )


def _repository_plan_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _repository_plan_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_repository_plan_thaw(item) for item in value]
    if isinstance(value, list):
        return [_repository_plan_thaw(item) for item in value]
    return value


def _repository_plan_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _repository_plan_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_repository_plan_freeze(item) for item in value)
    return value


def _repository_plan_canonical_json_bytes(value: object) -> bytes:
    _repository_plan_validate_json_value(value)
    try:
        return json.dumps(
            _repository_plan_thaw(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RepositoryPlanError(
            "REPOSITORY_PLAN_JSON_CANONICALIZATION_FAILED",
            "repository plan cannot be canonically encoded",
        ) from exc


def parse_repository_plan_json(
    source: object,
) -> Mapping[str, object]:
    """Parse strict JSON without accepting duplicate keys or numeric drift."""

    if isinstance(source, str):
        text = source
    elif isinstance(source, (bytes, bytearray, memoryview)):
        payload = bytes(source)
        if payload.startswith(b"\xef\xbb\xbf"):
            raise RepositoryPlanError(
                "REPOSITORY_PLAN_JSON_BOM_FORBIDDEN",
                "repository plan JSON must not contain a UTF-8 BOM",
            )
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RepositoryPlanError(
                "REPOSITORY_PLAN_JSON_UTF8_INVALID",
                "repository plan JSON must be valid UTF-8",
                details={"start": exc.start, "end": exc.end},
            ) from exc
    else:
        raise RepositoryPlanError(
            "REPOSITORY_PLAN_JSON_SOURCE_INVALID",
            "repository plan JSON source must be text or bytes",
            details={"type": type(source).__name__},
        )
    if text.startswith("\ufeff"):
        raise RepositoryPlanError(
            "REPOSITORY_PLAN_JSON_BOM_FORBIDDEN",
            "repository plan JSON must not contain a UTF-8 BOM",
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_repository_plan_strict_object,
            parse_float=_repository_plan_reject_float,
            parse_int=_repository_plan_parse_integer,
            parse_constant=_repository_plan_reject_constant,
        )
    except _RepositoryPlanJsonSemanticError as exc:
        messages = {
            "REPOSITORY_PLAN_JSON_DUPLICATE_KEY": (
                "repository plan object keys must be unique"
            ),
            "REPOSITORY_PLAN_JSON_FLOAT_FORBIDDEN": (
                "repository plan floating-point numbers are forbidden"
            ),
            "REPOSITORY_PLAN_JSON_INTEGER_OUT_OF_RANGE": (
                "repository plan integers must fit signed 64-bit range"
            ),
            "REPOSITORY_PLAN_JSON_NONFINITE_FORBIDDEN": (
                "repository plan NaN and infinity values are forbidden"
            ),
        }
        raise RepositoryPlanError(
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
        raise RepositoryPlanError(
            "REPOSITORY_PLAN_JSON_MALFORMED",
            "repository plan JSON is malformed",
            details=details,
        ) from exc
    if not isinstance(value, Mapping):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_TYPE_INVALID",
            "repository plan must be a JSON object",
        )
    _repository_plan_validate_json_value(value)
    return _repository_plan_freeze(value)  # type: ignore[return-value]


def _repository_plan_require_mapping(
    value: object,
    pointer: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            "repository plan field must be an object",
            pointer=pointer,
            details={"type": type(value).__name__},
        )
    if any(not isinstance(key, str) for key in value):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            "repository plan object keys must be strings",
            pointer=pointer,
        )
    return value


def _repository_plan_reject_unknown(
    value: Mapping[str, object],
    allowed: frozenset[str],
    pointer: str,
) -> None:
    unknown = sorted(set(value) - allowed, key=_repository_plan_utf8_key)
    if unknown:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_UNKNOWN_FIELD",
            "repository plan contains unsupported fields",
            pointer=pointer,
            details={"fields": unknown},
        )


def _repository_plan_require_string(
    value: object,
    pointer: str,
    *,
    stable_id: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            "repository plan field must be a non-empty string",
            pointer=pointer,
        )
    _repository_plan_validate_json_value(value, pointer)
    if stable_id and not _repository_plan_stable_id_re.fullmatch(value):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_IDENTIFIER_INVALID",
            "repository plan identifier is not stable and portable",
            pointer=pointer,
            details={"value": value},
        )
    return value


def _repository_plan_require_digest(
    value: object,
    pointer: str,
) -> str:
    digest = _repository_plan_require_string(value, pointer)
    if not _repository_plan_sha256_re.fullmatch(digest):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_DIGEST_INVALID",
            "repository plan digest must be lowercase SHA-256",
            pointer=pointer,
            details={"value": digest},
        )
    return digest


def _repository_plan_require_int(
    value: object,
    pointer: str,
    *,
    minimum: int = 0,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _repository_plan_signed_int64_max
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            f"repository plan field must be an integer >= {minimum}",
            pointer=pointer,
            details={"value": value},
        )
    return value


def _repository_plan_require_bool(
    value: object,
    pointer: str,
) -> bool:
    if not isinstance(value, bool):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            "repository plan field must be boolean",
            pointer=pointer,
        )
    return value


def _repository_plan_require_list(
    value: object,
    pointer: str,
) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_FIELD_INVALID",
            "repository plan field must be an array",
            pointer=pointer,
        )
    return value


def _repository_plan_require_canonical_strings(
    value: object,
    pointer: str,
    *,
    stable_ids: bool = False,
    digests: bool = False,
) -> tuple[str, ...]:
    sequence = _repository_plan_require_list(value, pointer)
    result: list[str] = []
    for index, item in enumerate(sequence):
        item_pointer = f"{pointer}/{index}"
        if digests:
            result.append(
                _repository_plan_require_digest(item, item_pointer)
            )
        else:
            result.append(
                _repository_plan_require_string(
                    item, item_pointer, stable_id=stable_ids
                )
            )
    if len(result) != len(set(result)):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_DUPLICATE_IDENTITY",
            "repository plan array entries must be unique",
            pointer=pointer,
        )
    expected = tuple(sorted(result, key=_repository_plan_utf8_key))
    if tuple(result) != expected:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "repository plan arrays must use deterministic UTF-8 order",
            pointer=pointer,
        )
    return tuple(result)


def _repository_plan_portable_path(
    value: object,
    pointer: str,
) -> tuple[str, str]:
    path = _repository_plan_require_string(value, pointer)
    if (
        "\x00" in path
        or "\\" in path
        or path.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", path)
        or any(
            character in path
            for character in _repository_plan_glob_characters
        )
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_PATH_INVALID",
            "path must be an exact portable relative POSIX path",
            pointer=pointer,
            details={"path": path},
        )
    parsed = PurePosixPath(path)
    if (
        parsed.as_posix() != path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_PATH_INVALID",
            "path must be an exact portable relative POSIX path",
            pointer=pointer,
            details={"path": path},
        )
    portable = unicodedata.normalize("NFC", path).casefold()
    return path, portable


def _repository_plan_check_portable_identities(
    entries: Iterable[tuple[str, str]],
    *,
    pointer: str,
) -> None:
    observed: dict[str, str] = {}
    for identity, item_pointer in entries:
        portable = unicodedata.normalize("NFC", identity).casefold()
        previous = observed.get(portable)
        if previous is not None:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_PORTABLE_COLLISION",
                "identities collide under NFC plus Unicode case-folding",
                pointer=pointer,
                details={
                    "first": previous,
                    "second": identity,
                    "second_pointer": item_pointer,
                },
            )
        observed[portable] = identity


def _repository_plan_check_path_collisions(
    entries: Iterable[tuple[str, str, str]],
    *,
    reject_ancestor_overlap: bool,
) -> None:
    observed: list[tuple[str, str, str]] = []
    for path, portable, pointer in entries:
        for previous_path, previous_portable, previous_pointer in observed:
            collision = portable == previous_portable
            overlap = (
                reject_ancestor_overlap
                and (
                    portable.startswith(previous_portable + "/")
                    or previous_portable.startswith(portable + "/")
                )
            )
            if collision or overlap:
                raise _repository_plan_error(
                    "REPOSITORY_PLAN_PATH_COLLISION",
                    "repository plan paths collide or overlap portably",
                    pointer=pointer,
                    details={
                        "first_path": previous_path,
                        "first_pointer": previous_pointer,
                        "second_path": path,
                    },
                )
        observed.append((path, portable, pointer))


def _repository_plan_validate_repositories(
    value: object,
) -> tuple[Mapping[str, object], ...]:
    sequence = _repository_plan_require_list(value, "/repositories")
    if not sequence:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_REPOSITORY_SET_EMPTY",
            "repository plan must select at least one repository",
            pointer="/repositories",
        )
    result: list[Mapping[str, object]] = []
    identity_entries: list[tuple[str, str]] = []
    repository_identity_digests: set[str] = set()
    root_paths: list[tuple[str, str, str]] = []
    for index, item in enumerate(sequence):
        pointer = f"/repositories/{index}"
        repository = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            repository, _repository_plan_repository_fields, pointer
        )
        repository_id = _repository_plan_require_string(
            repository.get("repository_id"),
            f"{pointer}/repository_id",
            stable_id=True,
        )
        identity_entries.append(
            (repository_id, f"{pointer}/repository_id")
        )
        identity_sha256 = _repository_plan_require_digest(
            repository.get("identity_sha256"),
            f"{pointer}/identity_sha256",
        )
        if identity_sha256 in repository_identity_digests:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_DUPLICATE_IDENTITY",
                "canonical repository identities must be unique",
                pointer=f"{pointer}/identity_sha256",
                details={"sha256": identity_sha256},
            )
        repository_identity_digests.add(identity_sha256)
        repository_path, portable_root = _repository_plan_portable_path(
            repository.get("repository_path"),
            f"{pointer}/repository_path",
        )
        root_paths.append(
            (
                repository_path,
                portable_root,
                f"{pointer}/repository_path",
            )
        )
        approved_sequence = _repository_plan_require_list(
            repository.get("approved_paths"),
            f"{pointer}/approved_paths",
        )
        approved_paths: list[str] = []
        approved_portable: list[tuple[str, str, str]] = []
        for path_index, path_value in enumerate(approved_sequence):
            path_pointer = f"{pointer}/approved_paths/{path_index}"
            approved_path, portable_path = _repository_plan_portable_path(
                path_value, path_pointer
            )
            approved_paths.append(approved_path)
            approved_portable.append(
                (approved_path, portable_path, path_pointer)
            )
        expected_paths = tuple(
            sorted(approved_paths, key=_repository_plan_utf8_key)
        )
        if tuple(approved_paths) != expected_paths:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_ORDER_INVALID",
                "approved paths must use deterministic UTF-8 order",
                pointer=f"{pointer}/approved_paths",
            )
        _repository_plan_check_path_collisions(
            approved_portable, reject_ancestor_overlap=True
        )
        write_policy = _repository_plan_require_string(
            repository.get("write_policy"),
            f"{pointer}/write_policy",
        )
        if write_policy not in _repository_plan_write_policies:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_POLICY_INVALID",
                "repository write policy is unsupported",
                pointer=f"{pointer}/write_policy",
                details={"value": write_policy},
            )
        if write_policy == "scoped-write" and not approved_paths:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_POLICY_INVALID",
                "writable repositories require at least one approved path",
                pointer=f"{pointer}/approved_paths",
            )
        required_approvals = _repository_plan_require_canonical_strings(
            repository.get("required_approval_ids"),
            f"{pointer}/required_approval_ids",
            stable_ids=True,
        )
        required_evidence = _repository_plan_require_canonical_strings(
            repository.get("required_evidence_contract_sha256"),
            f"{pointer}/required_evidence_contract_sha256",
            digests=True,
        )
        result.append(
            {
                "repository_id": repository_id,
                "identity_sha256": identity_sha256,
                "repository_path": repository_path,
                "approved_paths": approved_paths,
                "write_policy": write_policy,
                "required_approval_ids": list(required_approvals),
                "required_evidence_contract_sha256": list(
                    required_evidence
                ),
            }
        )
    repository_ids = [
        str(item["repository_id"]) for item in result
    ]
    expected = sorted(repository_ids, key=_repository_plan_utf8_key)
    if repository_ids != expected:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "repositories must use deterministic UTF-8 identifier order",
            pointer="/repositories",
        )
    _repository_plan_check_portable_identities(
        identity_entries, pointer="/repositories"
    )
    _repository_plan_check_path_collisions(
        root_paths, reject_ancestor_overlap=True
    )
    return tuple(
        _repository_plan_freeze(item) for item in result
    )  # type: ignore[return-value]


def _repository_plan_validate_contracts(
    value: object,
) -> tuple[Mapping[str, object], ...]:
    sequence = _repository_plan_require_list(
        value, "/interface_contracts"
    )
    result: list[Mapping[str, object]] = []
    identities: list[tuple[str, str]] = []
    for index, item in enumerate(sequence):
        pointer = f"/interface_contracts/{index}"
        contract = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            contract, _repository_plan_contract_fields, pointer
        )
        contract_id = _repository_plan_require_string(
            contract.get("contract_id"),
            f"{pointer}/contract_id",
            stable_id=True,
        )
        identities.append((contract_id, f"{pointer}/contract_id"))
        result.append(
            {
                "contract_id": contract_id,
                "artifact_id": _repository_plan_require_string(
                    contract.get("artifact_id"),
                    f"{pointer}/artifact_id",
                    stable_id=True,
                ),
                "sha256": _repository_plan_require_digest(
                    contract.get("sha256"), f"{pointer}/sha256"
                ),
            }
        )
    contract_ids = [str(item["contract_id"]) for item in result]
    expected = sorted(contract_ids, key=_repository_plan_utf8_key)
    if contract_ids != expected:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "interface contracts must use deterministic UTF-8 order",
            pointer="/interface_contracts",
        )
    _repository_plan_check_portable_identities(
        identities, pointer="/interface_contracts"
    )
    return tuple(
        _repository_plan_freeze(item) for item in result
    )  # type: ignore[return-value]


def _repository_plan_validate_dependencies(
    value: object,
    *,
    repositories: tuple[Mapping[str, object], ...],
    contracts: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    sequence = _repository_plan_require_list(value, "/dependencies")
    repository_ids = {
        str(item["repository_id"]) for item in repositories
    }
    contract_digests = {str(item["sha256"]) for item in contracts}
    result: list[Mapping[str, object]] = []
    identities: list[tuple[str, str]] = []
    endpoint_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(sequence):
        pointer = f"/dependencies/{index}"
        dependency = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            dependency, _repository_plan_dependency_fields, pointer
        )
        edge_id = _repository_plan_require_string(
            dependency.get("edge_id"),
            f"{pointer}/edge_id",
            stable_id=True,
        )
        identities.append((edge_id, f"{pointer}/edge_id"))
        predecessor = _repository_plan_require_string(
            dependency.get("from_repository_id"),
            f"{pointer}/from_repository_id",
            stable_id=True,
        )
        successor = _repository_plan_require_string(
            dependency.get("to_repository_id"),
            f"{pointer}/to_repository_id",
            stable_id=True,
        )
        if predecessor not in repository_ids or successor not in repository_ids:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_DEPENDENCY_UNKNOWN",
                "dependency names a repository outside the selected set",
                pointer=pointer,
                details={
                    "from_repository_id": predecessor,
                    "to_repository_id": successor,
                },
            )
        if predecessor == successor:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_DEPENDENCY_SELF",
                "repository dependency must not be a self-edge",
                pointer=pointer,
                details={"repository_id": predecessor},
            )
        pair = (predecessor, successor)
        if pair in endpoint_pairs:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_DEPENDENCY_AMBIGUOUS",
                "repository endpoint pair has more than one dependency",
                pointer=pointer,
                details={
                    "from_repository_id": predecessor,
                    "to_repository_id": successor,
                },
            )
        endpoint_pairs.add(pair)
        input_contract = _repository_plan_require_digest(
            dependency.get("input_contract_sha256"),
            f"{pointer}/input_contract_sha256",
        )
        output_contract = _repository_plan_require_digest(
            dependency.get("output_contract_sha256"),
            f"{pointer}/output_contract_sha256",
        )
        required_evidence = _repository_plan_require_canonical_strings(
            dependency.get("required_evidence_contract_sha256"),
            f"{pointer}/required_evidence_contract_sha256",
            digests=True,
        )
        referenced = {
            input_contract,
            output_contract,
            *required_evidence,
        }
        unknown_contracts = sorted(
            referenced - contract_digests, key=_repository_plan_utf8_key
        )
        if unknown_contracts:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_CONTRACT_UNKNOWN",
                "dependency references a contract absent from the plan",
                pointer=pointer,
                details={"sha256": unknown_contracts},
            )
        result.append(
            {
                "edge_id": edge_id,
                "from_repository_id": predecessor,
                "to_repository_id": successor,
                "input_contract_sha256": input_contract,
                "output_contract_sha256": output_contract,
                "required_evidence_contract_sha256": list(
                    required_evidence
                ),
            }
        )
    edge_ids = [str(item["edge_id"]) for item in result]
    expected = sorted(edge_ids, key=_repository_plan_utf8_key)
    if edge_ids != expected:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "dependencies must use deterministic UTF-8 edge order",
            pointer="/dependencies",
        )
    _repository_plan_check_portable_identities(
        identities, pointer="/dependencies"
    )
    return tuple(
        _repository_plan_freeze(item) for item in result
    )  # type: ignore[return-value]


def _repository_plan_validate_dag(
    repositories: tuple[Mapping[str, object], ...],
    dependencies: tuple[Mapping[str, object], ...],
) -> None:
    repository_ids = tuple(
        str(item["repository_id"]) for item in repositories
    )
    indegree = {repository_id: 0 for repository_id in repository_ids}
    successors: dict[str, list[str]] = {
        repository_id: [] for repository_id in repository_ids
    }
    for edge in dependencies:
        predecessor = str(edge["from_repository_id"])
        successor = str(edge["to_repository_id"])
        successors[predecessor].append(successor)
        indegree[successor] += 1
    ready = sorted(
        (
            repository_id
            for repository_id, count in indegree.items()
            if count == 0
        ),
        key=_repository_plan_utf8_key,
    )
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for successor in sorted(
            successors[current], key=_repository_plan_utf8_key
        ):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort(key=_repository_plan_utf8_key)
    if len(visited) != len(repository_ids):
        cycle_nodes = sorted(
            (
                repository_id
                for repository_id, count in indegree.items()
                if count > 0
            ),
            key=_repository_plan_utf8_key,
        )
        raise _repository_plan_error(
            "REPOSITORY_PLAN_DEPENDENCY_CYCLE",
            "repository dependencies must form an acyclic graph",
            pointer="/dependencies",
            details={"repository_ids": cycle_nodes},
        )


def _repository_plan_validate_policies(
    value: Mapping[str, object],
    *,
    contract_digests: frozenset[str],
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
]:
    worktree = _repository_plan_require_mapping(
        value.get("worktree_policy"), "/worktree_policy"
    )
    _repository_plan_reject_unknown(
        worktree, _repository_plan_worktree_fields, "/worktree_policy"
    )
    mode = _repository_plan_require_string(
        worktree.get("mode"), "/worktree_policy/mode"
    )
    if mode != "controller-owned":
        raise _repository_plan_error(
            "REPOSITORY_PLAN_POLICY_INVALID",
            "worktree policy must be controller-owned",
            pointer="/worktree_policy/mode",
            details={"value": mode},
        )
    worktree_value = {
        "mode": mode,
        "require_clean": _repository_plan_require_bool(
            worktree.get("require_clean"),
            "/worktree_policy/require_clean",
        ),
        "distinct": _repository_plan_require_bool(
            worktree.get("distinct"), "/worktree_policy/distinct"
        ),
    }
    if not worktree_value["distinct"]:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_POLICY_INVALID",
            "repository worktrees must be distinct",
            pointer="/worktree_policy/distinct",
        )

    concurrency = _repository_plan_require_mapping(
        value.get("concurrency_policy"), "/concurrency_policy"
    )
    _repository_plan_reject_unknown(
        concurrency,
        _repository_plan_concurrency_fields,
        "/concurrency_policy",
    )
    concurrency_value = {
        "max_workers": _repository_plan_require_int(
            concurrency.get("max_workers"),
            "/concurrency_policy/max_workers",
            minimum=1,
        ),
        "max_writable_workers": _repository_plan_require_int(
            concurrency.get("max_writable_workers"),
            "/concurrency_policy/max_writable_workers",
            minimum=0,
        ),
    }
    if (
        concurrency_value["max_writable_workers"]
        > concurrency_value["max_workers"]
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_POLICY_INVALID",
            "writable concurrency must not exceed total concurrency",
            pointer="/concurrency_policy/max_writable_workers",
        )

    retry = _repository_plan_require_mapping(
        value.get("retry_policy"), "/retry_policy"
    )
    _repository_plan_reject_unknown(
        retry, _repository_plan_retry_fields, "/retry_policy"
    )
    retryable_states = _repository_plan_require_canonical_strings(
        retry.get("retryable_states"),
        "/retry_policy/retryable_states",
    )
    unsupported_states = sorted(
        set(retryable_states) - _repository_plan_retryable_states,
        key=_repository_plan_utf8_key,
    )
    if unsupported_states:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_POLICY_INVALID",
            "retry policy names unsupported states",
            pointer="/retry_policy/retryable_states",
            details={"states": unsupported_states},
        )
    retry_value = {
        "max_attempts": _repository_plan_require_int(
            retry.get("max_attempts"),
            "/retry_policy/max_attempts",
            minimum=1,
        ),
        "retryable_states": list(retryable_states),
        "requires_approval": _repository_plan_require_bool(
            retry.get("requires_approval"),
            "/retry_policy/requires_approval",
        ),
    }

    integration = _repository_plan_require_mapping(
        value.get("integration_policy"), "/integration_policy"
    )
    _repository_plan_reject_unknown(
        integration,
        _repository_plan_integration_fields,
        "/integration_policy",
    )
    command_values = _repository_plan_require_list(
        integration.get("commands"), "/integration_policy/commands"
    )
    commands: list[list[str]] = []
    for command_index, command in enumerate(command_values):
        command_pointer = (
            f"/integration_policy/commands/{command_index}"
        )
        argv_values = _repository_plan_require_list(
            command, command_pointer
        )
        if not argv_values:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_POLICY_INVALID",
                "integration commands must contain argv",
                pointer=command_pointer,
            )
        argv = [
            _repository_plan_require_string(
                argument, f"{command_pointer}/{argument_index}"
            )
            for argument_index, argument in enumerate(argv_values)
        ]
        commands.append(argv)
    evidence_contracts = _repository_plan_require_canonical_strings(
        integration.get("evidence_contract_sha256"),
        "/integration_policy/evidence_contract_sha256",
        digests=True,
    )
    unknown = sorted(
        set(evidence_contracts) - contract_digests,
        key=_repository_plan_utf8_key,
    )
    if unknown:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_CONTRACT_UNKNOWN",
            "integration policy references a contract absent from the plan",
            pointer="/integration_policy/evidence_contract_sha256",
            details={"sha256": unknown},
        )
    integration_value = {
        "commands": commands,
        "evidence_contract_sha256": list(evidence_contracts),
    }
    return (
        _repository_plan_freeze(worktree_value),
        _repository_plan_freeze(concurrency_value),
        _repository_plan_freeze(retry_value),
        _repository_plan_freeze(integration_value),
    )  # type: ignore[return-value]


def _repository_plan_semantic_preimage_from_validated(
    plan: Mapping[str, object],
) -> bytes:
    semantic_value = _repository_plan_thaw(plan)
    assert isinstance(semantic_value, dict)
    semantic_value.pop("semantic_input_sha256", None)
    semantic_bytes = _repository_plan_canonical_json_bytes(semantic_value)
    return (
        REPOSITORY_PLAN_SEMANTIC_INPUT_DOMAIN
        + _repository_plan_u64be(len(semantic_bytes))
        + semantic_bytes
    )


def _repository_plan_validate(
    value: object,
    *,
    verify_semantic_digest: bool,
    previous_map_epoch: Optional[int] = None,
) -> Mapping[str, object]:
    _repository_plan_validate_json_value(value)
    plan = _repository_plan_require_mapping(value, "/")
    _repository_plan_reject_unknown(
        plan, _repository_plan_top_fields, "/"
    )
    if plan.get("schema") != REPOSITORY_PLAN_SCHEMA:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_SCHEMA_UNSUPPORTED",
            "repository plan schema is unsupported",
            pointer="/schema",
            details={"schema": plan.get("schema")},
        )
    task_id = _repository_plan_require_string(
        plan.get("task_id"), "/task_id", stable_id=True
    )
    workflow_bundle_sha256 = _repository_plan_require_digest(
        plan.get("workflow_bundle_sha256"),
        "/workflow_bundle_sha256",
    )
    plan_id = _repository_plan_require_string(
        plan.get("plan_id"), "/plan_id", stable_id=True
    )
    map_node_id = _repository_plan_require_string(
        plan.get("map_node_id"), "/map_node_id", stable_id=True
    )
    map_epoch = _repository_plan_require_int(
        plan.get("map_epoch"), "/map_epoch", minimum=1
    )
    if previous_map_epoch is not None:
        previous = _repository_plan_require_int(
            previous_map_epoch, "/previous_map_epoch", minimum=0
        )
        if map_epoch <= previous:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_MAP_EPOCH_NOT_MONOTONIC",
                "replacement repository plans require a greater map epoch",
                pointer="/map_epoch",
                details={"map_epoch": map_epoch, "previous": previous},
            )
    plan_input_revision = _repository_plan_require_int(
        plan.get("plan_input_revision"),
        "/plan_input_revision",
        minimum=0,
    )
    semantic_input_sha256 = _repository_plan_require_digest(
        plan.get("semantic_input_sha256"),
        "/semantic_input_sha256",
    )
    repositories = _repository_plan_validate_repositories(
        plan.get("repositories")
    )
    repository_set = _repository_plan_require_canonical_strings(
        plan.get("repository_set"),
        "/repository_set",
        stable_ids=True,
    )
    actual_repository_set = tuple(
        str(item["repository_id"]) for item in repositories
    )
    if repository_set != actual_repository_set:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_REPOSITORY_SET_MISMATCH",
            "repository_set must exactly match repository identities",
            pointer="/repository_set",
            details={
                "expected": list(actual_repository_set),
                "actual": list(repository_set),
            },
        )
    contracts = _repository_plan_validate_contracts(
        plan.get("interface_contracts")
    )
    contract_digests = frozenset(
        str(item["sha256"]) for item in contracts
    )
    for repository_index, repository in enumerate(repositories):
        unknown = sorted(
            set(
                str(item)
                for item in repository[
                    "required_evidence_contract_sha256"
                ]
            )
            - contract_digests,
            key=_repository_plan_utf8_key,
        )
        if unknown:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_CONTRACT_UNKNOWN",
                "repository references a contract absent from the plan",
                pointer=(
                    f"/repositories/{repository_index}/"
                    "required_evidence_contract_sha256"
                ),
                details={"sha256": unknown},
            )
    dependencies = _repository_plan_validate_dependencies(
        plan.get("dependencies"),
        repositories=repositories,
        contracts=contracts,
    )
    _repository_plan_validate_dag(repositories, dependencies)
    (
        worktree_policy,
        concurrency_policy,
        retry_policy,
        integration_policy,
    ) = _repository_plan_validate_policies(
        plan, contract_digests=contract_digests
    )
    normalized = _repository_plan_freeze(
        {
            "schema": REPOSITORY_PLAN_SCHEMA,
            "task_id": task_id,
            "workflow_bundle_sha256": workflow_bundle_sha256,
            "plan_id": plan_id,
            "map_node_id": map_node_id,
            "map_epoch": map_epoch,
            "plan_input_revision": plan_input_revision,
            "semantic_input_sha256": semantic_input_sha256,
            "repository_set": list(repository_set),
            "repositories": list(repositories),
            "interface_contracts": list(contracts),
            "dependencies": list(dependencies),
            "worktree_policy": worktree_policy,
            "concurrency_policy": concurrency_policy,
            "retry_policy": retry_policy,
            "integration_policy": integration_policy,
        }
    )
    assert isinstance(normalized, Mapping)
    if verify_semantic_digest:
        expected = hashlib.sha256(
            _repository_plan_semantic_preimage_from_validated(normalized)
        ).hexdigest()
        if semantic_input_sha256 != expected:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_SEMANTIC_DIGEST_MISMATCH",
                "semantic-input digest does not match bound plan inputs",
                pointer="/semantic_input_sha256",
                details={
                    "expected": expected,
                    "actual": semantic_input_sha256,
                },
            )
    return normalized


def bind_repository_plan_semantic_input(
    value: Mapping[str, object],
    *,
    previous_map_epoch: Optional[int] = None,
) -> Mapping[str, object]:
    """Return a validated immutable plan with its semantic digest populated."""

    candidate = _repository_plan_thaw(value)
    if not isinstance(candidate, dict):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_TYPE_INVALID",
            "repository plan must be a JSON object",
        )
    candidate["semantic_input_sha256"] = "0" * 64
    provisional = _repository_plan_validate(
        candidate,
        verify_semantic_digest=False,
        previous_map_epoch=previous_map_epoch,
    )
    digest = hashlib.sha256(
        _repository_plan_semantic_preimage_from_validated(provisional)
    ).hexdigest()
    candidate["semantic_input_sha256"] = digest
    return _repository_plan_validate(
        candidate,
        verify_semantic_digest=True,
        previous_map_epoch=previous_map_epoch,
    )


def validate_repository_plan(
    value: object,
    *,
    previous_map_epoch: Optional[int] = None,
) -> Mapping[str, object]:
    """Validate and deeply freeze one complete repository plan."""

    return _repository_plan_validate(
        value,
        verify_semantic_digest=True,
        previous_map_epoch=previous_map_epoch,
    )


def _repository_plan_descriptor_value(
    descriptor: object, *names: str
) -> object:
    for name in names:
        if isinstance(descriptor, Mapping) and name in descriptor:
            return descriptor[name]
        if hasattr(descriptor, name):
            return getattr(descriptor, name)
    return None


def _repository_plan_workflow_binding(
    workflow_bundle: object,
) -> Mapping[str, object]:
    graph = _repository_plan_descriptor_value(workflow_bundle, "graph")
    if not isinstance(graph, Mapping):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_INVALID",
            "pinned workflow bundle does not expose a validated graph",
            pointer="/workflow_bundle",
        )
    bundle_sha256 = _repository_plan_require_digest(
        _repository_plan_descriptor_value(
            workflow_bundle, "bundle_sha256"
        ),
        "/workflow_bundle/bundle_sha256",
    )
    profiles = _repository_plan_descriptor_value(
        workflow_bundle, "execution_profiles"
    )
    if profiles is None:
        profiles = graph.get("execution_profiles")
    if not isinstance(profiles, (list, tuple)) or (
        "multi-repository" not in profiles
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_PROFILE_MISMATCH",
            "repository plans require a pinned multi-repository profile",
            pointer="/workflow_bundle/execution_profiles",
        )
    metadata = _repository_plan_descriptor_value(
        workflow_bundle, "repository_orchestration"
    )
    if metadata is None:
        metadata = graph.get("repository_orchestration")
    metadata = _repository_plan_require_mapping(
        metadata, "/workflow_bundle/repository_orchestration"
    )
    if (
        metadata.get("schema")
        != "dev-flow-repository-orchestration/v1"
        or metadata.get("execution_profile") != "multi-repository"
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_INVALID",
            "pinned workflow repository orchestration contract is unsupported",
            pointer="/workflow_bundle/repository_orchestration",
        )
    map_value = _repository_plan_require_mapping(
        metadata.get("map"),
        "/workflow_bundle/repository_orchestration/map",
    )
    child_template = _repository_plan_require_mapping(
        map_value.get("child_template"),
        (
            "/workflow_bundle/repository_orchestration/"
            "map/child_template"
        ),
    )
    join_value = _repository_plan_require_mapping(
        metadata.get("join"),
        "/workflow_bundle/repository_orchestration/join",
    )
    map_operation_id = _repository_plan_require_string(
        map_value.get("operation_id"),
        (
            "/workflow_bundle/repository_orchestration/"
            "map/operation_id"
        ),
        stable_id=True,
    )
    template_id = _repository_plan_require_string(
        child_template.get("template_id"),
        (
            "/workflow_bundle/repository_orchestration/"
            "map/child_template/template_id"
        ),
        stable_id=True,
    )
    child_node_id = _repository_plan_require_string(
        child_template.get("node_id"),
        (
            "/workflow_bundle/repository_orchestration/"
            "map/child_template/node_id"
        ),
        stable_id=True,
    )
    map_parent_node_id = _repository_plan_require_string(
        map_value.get("parent_node_id"),
        (
            "/workflow_bundle/repository_orchestration/"
            "map/parent_node_id"
        ),
        stable_id=True,
    )
    join_node_id = _repository_plan_require_string(
        join_value.get("node_id"),
        (
            "/workflow_bundle/repository_orchestration/"
            "join/node_id"
        ),
        stable_id=True,
    )
    if template_id != map_operation_id:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_INVALID",
            "pinned child template does not bind the map operation",
            pointer=(
                "/workflow_bundle/repository_orchestration/"
                "map/child_template/template_id"
            ),
        )
    if join_node_id in {map_parent_node_id, child_node_id}:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_INVALID",
            "pinned repository map and join node bindings must be distinct",
            pointer="/workflow_bundle/repository_orchestration",
        )
    nodes = _repository_plan_descriptor_value(workflow_bundle, "nodes")
    if isinstance(nodes, Mapping):
        node_ids = set(nodes)
    else:
        graph_nodes = graph.get("nodes")
        if not isinstance(graph_nodes, (list, tuple)):
            raise _repository_plan_error(
                "REPOSITORY_PLAN_WORKFLOW_INVALID",
                "pinned workflow bundle does not expose node declarations",
                pointer="/workflow_bundle/nodes",
            )
        node_ids = {
            str(node.get("id"))
            for node in graph_nodes
            if isinstance(node, Mapping)
            and isinstance(node.get("id"), str)
        }
    missing_nodes = sorted(
        {map_parent_node_id, child_node_id, join_node_id} - node_ids,
        key=_repository_plan_utf8_key,
    )
    if missing_nodes:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_INVALID",
            "pinned repository orchestration references unknown nodes",
            pointer="/workflow_bundle/repository_orchestration",
            details={"node_ids": missing_nodes},
        )
    return _repository_plan_freeze(
        {
            "bundle_sha256": bundle_sha256,
            "map_template_id": template_id,
            "map_parent_node_id": map_parent_node_id,
            "child_node_id": child_node_id,
            "join_node_id": join_node_id,
        }
    )  # type: ignore[return-value]


def validate_repository_plan_against_workflow_bundle(
    plan_value: object, workflow_bundle: object
) -> Mapping[str, object]:
    """Bind a repository plan to package-owned pinned map metadata."""

    plan = validate_repository_plan(plan_value)
    binding = _repository_plan_workflow_binding(workflow_bundle)
    if (
        plan["workflow_bundle_sha256"] != binding["bundle_sha256"]
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_WORKFLOW_MISMATCH",
            "repository plan bundle identity differs from the pinned workflow",
            pointer="/workflow_bundle_sha256",
            details={
                "expected": binding["bundle_sha256"],
                "actual": plan["workflow_bundle_sha256"],
            },
        )
    if plan["map_node_id"] != binding["map_template_id"]:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_MAP_BINDING_MISMATCH",
            "repository plan map node differs from the pinned child template",
            pointer="/map_node_id",
            details={
                "expected": binding["map_template_id"],
                "actual": plan["map_node_id"],
            },
        )
    return plan


def load_repository_plan(
    source: object,
    *,
    previous_map_epoch: Optional[int] = None,
) -> Mapping[str, object]:
    return validate_repository_plan(
        parse_repository_plan_json(source),
        previous_map_epoch=previous_map_epoch,
    )


def repository_plan_semantic_input_preimage(
    value: object,
) -> bytes:
    plan = _repository_plan_validate(
        value, verify_semantic_digest=False
    )
    return _repository_plan_semantic_preimage_from_validated(plan)


def repository_plan_semantic_input_sha256(
    value: object,
) -> str:
    return hashlib.sha256(
        repository_plan_semantic_input_preimage(value)
    ).hexdigest()


def canonical_repository_plan_bytes(value: object) -> bytes:
    return _repository_plan_canonical_json_bytes(
        validate_repository_plan(value)
    )


def repository_plan_preimage(value: object) -> bytes:
    canonical = canonical_repository_plan_bytes(value)
    return (
        REPOSITORY_PLAN_DOMAIN
        + _repository_plan_u64be(len(canonical))
        + canonical
    )


def repository_plan_dag_sha256(value: object) -> str:
    return hashlib.sha256(repository_plan_preimage(value)).hexdigest()


def repository_plan_identity(value: object) -> RepositoryPlanIdentity:
    plan = validate_repository_plan(value)
    canonical = _repository_plan_canonical_json_bytes(plan)
    return RepositoryPlanIdentity(
        task_id=str(plan["task_id"]),
        plan_id=str(plan["plan_id"]),
        semantic_input_sha256=str(plan["semantic_input_sha256"]),
        artifact_sha256=hashlib.sha256(canonical).hexdigest(),
        dag_sha256=hashlib.sha256(
            REPOSITORY_PLAN_DOMAIN
            + _repository_plan_u64be(len(canonical))
            + canonical
        ).hexdigest(),
        canonical_bytes=canonical,
    )


def build_repository_plan_artifact(
    value: object,
) -> RepositoryPlanArtifact:
    """Build immutable content; the caller still owns task-local persistence."""

    identity = repository_plan_identity(value)
    return RepositoryPlanArtifact(
        schema=REPOSITORY_PLAN_SCHEMA,
        task_id=identity.task_id,
        artifact_id="repository-plan-" + identity.dag_sha256,
        media_type="application/json",
        sha256=identity.artifact_sha256,
        size=len(identity.canonical_bytes),
        dag_sha256=identity.dag_sha256,
        semantic_input_sha256=identity.semantic_input_sha256,
        content=identity.canonical_bytes,
    )


def validate_repository_plan_contract_artifacts(
    value: object,
    available_artifacts: Mapping[str, object],
) -> Mapping[str, object]:
    """Confirm every contract reference against injected task-local facts.

    ``available_artifacts`` is intentionally only an identity-to-digest view.
    Reading and persisting the referenced bytes remains an artifact-service
    responsibility outside this pure module.
    """

    plan = validate_repository_plan(value)
    artifacts = _repository_plan_require_mapping(
        available_artifacts, "/available_artifacts"
    )
    for artifact_id, digest_value in artifacts.items():
        _repository_plan_require_string(
            artifact_id,
            (
                "/available_artifacts/"
                + _repository_plan_pointer_segment(artifact_id)
            ),
            stable_id=True,
        )
        _repository_plan_require_digest(
            digest_value,
            (
                "/available_artifacts/"
                + _repository_plan_pointer_segment(artifact_id)
            ),
        )
    for contract in plan["interface_contracts"]:
        artifact_id = str(contract["artifact_id"])
        expected_digest = str(contract["sha256"])
        actual_digest = artifacts.get(artifact_id)
        if actual_digest is None:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_CONTRACT_ARTIFACT_MISSING",
                "interface contract is absent from task-local artifacts",
                pointer="/available_artifacts",
                details={
                    "artifact_id": artifact_id,
                    "contract_id": contract["contract_id"],
                },
            )
        if actual_digest != expected_digest:
            raise _repository_plan_error(
                "REPOSITORY_PLAN_CONTRACT_ARTIFACT_MISMATCH",
                "interface contract digest differs from task-local artifact",
                pointer=(
                    "/available_artifacts/"
                    + _repository_plan_pointer_segment(artifact_id)
                ),
                details={
                    "artifact_id": artifact_id,
                    "expected": expected_digest,
                    "actual": actual_digest,
                },
            )
    return plan


def _repository_plan_approval_projection(
    plan: Mapping[str, object],
    *,
    plan_artifact_id: str,
    approval_intent: str,
    approval_commit_revision: int,
) -> Mapping[str, object]:
    identity = repository_plan_identity(plan)
    repositories = plan["repositories"]
    contracts = plan["interface_contracts"]
    dependencies = plan["dependencies"]
    assert isinstance(repositories, tuple)
    assert isinstance(contracts, tuple)
    assert isinstance(dependencies, tuple)
    return _repository_plan_freeze(
        {
            "schema": REPOSITORY_PLAN_APPROVAL_SCHEMA,
            "task_id": plan["task_id"],
            "workflow_bundle_sha256": plan[
                "workflow_bundle_sha256"
            ],
            "plan_id": plan["plan_id"],
            "plan_artifact_id": plan_artifact_id,
            "plan_artifact_sha256": identity.artifact_sha256,
            "dag_sha256": identity.dag_sha256,
            "semantic_input_sha256": plan["semantic_input_sha256"],
            "plan_input_revision": plan["plan_input_revision"],
            "approval_commit_revision": approval_commit_revision,
            "map_epoch": plan["map_epoch"],
            "repository_set": list(plan["repository_set"]),
            "repository_identities": [
                {
                    "repository_id": repository["repository_id"],
                    "identity_sha256": repository["identity_sha256"],
                }
                for repository in repositories
            ],
            "interface_contracts": [
                {
                    "contract_id": contract["contract_id"],
                    "sha256": contract["sha256"],
                }
                for contract in contracts
            ],
            "dependency_edges": [
                {
                    field: edge[field]
                    for field in (
                        "edge_id",
                        "from_repository_id",
                        "to_repository_id",
                        "input_contract_sha256",
                        "output_contract_sha256",
                        "required_evidence_contract_sha256",
                    )
                }
                for edge in dependencies
            ],
            "approved_paths": [
                {
                    "repository_id": repository["repository_id"],
                    "paths": list(repository["approved_paths"]),
                }
                for repository in repositories
            ],
            "execution_policies": {
                "worktree": plan["worktree_policy"],
                "concurrency": plan["concurrency_policy"],
                "retry": plan["retry_policy"],
                "integration": plan["integration_policy"],
                "repository_write": [
                    {
                        "repository_id": repository["repository_id"],
                        "write_policy": repository["write_policy"],
                    }
                    for repository in repositories
                ],
            },
            "approval_intent": approval_intent,
        }
    )  # type: ignore[return-value]


def create_repository_plan_approval(
    value: object,
    *,
    plan_artifact_id: Optional[str] = None,
    approval_intent: str,
    approval_commit_revision: int,
) -> Mapping[str, object]:
    """Create the immutable approval payload; this does not persist approval."""

    plan = validate_repository_plan(value)
    expected_artifact_id = build_repository_plan_artifact(
        plan
    ).artifact_id
    artifact_id = (
        expected_artifact_id
        if plan_artifact_id is None
        else _repository_plan_require_string(
            plan_artifact_id,
            "/plan_artifact_id",
            stable_id=True,
        )
    )
    if artifact_id != expected_artifact_id:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ARTIFACT_IDENTITY_MISMATCH",
            "plan artifact identity must be the canonical content identity",
            pointer="/plan_artifact_id",
            details={
                "expected": expected_artifact_id,
                "actual": artifact_id,
            },
        )
    intent = _repository_plan_require_string(
        approval_intent, "/approval_intent", stable_id=True
    )
    commit_revision = _repository_plan_require_int(
        approval_commit_revision,
        "/approval_commit_revision",
        minimum=0,
    )
    if commit_revision <= int(plan["plan_input_revision"]):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_APPROVAL_REVISION_INVALID",
            "approval commit revision must follow plan input revision",
            pointer="/approval_commit_revision",
            details={
                "plan_input_revision": plan["plan_input_revision"],
                "approval_commit_revision": commit_revision,
            },
        )
    return _repository_plan_approval_projection(
        plan,
        plan_artifact_id=artifact_id,
        approval_intent=intent,
        approval_commit_revision=commit_revision,
    )


def _repository_plan_validate_approval_shape(
    value: object,
) -> Mapping[str, object]:
    approval = _repository_plan_require_mapping(value, "/approval")
    _repository_plan_validate_json_value(approval, "/approval")
    _repository_plan_reject_unknown(
        approval, _repository_plan_approval_fields, "/approval"
    )
    if approval.get("schema") != REPOSITORY_PLAN_APPROVAL_SCHEMA:
        raise _repository_plan_error(
            "REPOSITORY_PLAN_APPROVAL_SCHEMA_UNSUPPORTED",
            "repository plan approval schema is unsupported",
            pointer="/approval/schema",
            details={"schema": approval.get("schema")},
        )
    for field in (
        "task_id",
        "plan_id",
        "plan_artifact_id",
        "approval_intent",
    ):
        _repository_plan_require_string(
            approval.get(field),
            f"/approval/{field}",
            stable_id=True,
        )
    for field in (
        "workflow_bundle_sha256",
        "plan_artifact_sha256",
        "dag_sha256",
        "semantic_input_sha256",
    ):
        _repository_plan_require_digest(
            approval.get(field), f"/approval/{field}"
        )
    for field in (
        "plan_input_revision",
        "approval_commit_revision",
        "map_epoch",
    ):
        _repository_plan_require_int(
            approval.get(field),
            f"/approval/{field}",
            minimum=0,
        )
    if int(approval["approval_commit_revision"]) <= int(
        approval["plan_input_revision"]
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_APPROVAL_REVISION_INVALID",
            "approval commit revision must follow plan input revision",
            pointer="/approval/approval_commit_revision",
            details={
                "plan_input_revision": approval[
                    "plan_input_revision"
                ],
                "approval_commit_revision": approval[
                    "approval_commit_revision"
                ],
            },
        )
    _repository_plan_require_canonical_strings(
        approval.get("repository_set"),
        "/approval/repository_set",
        stable_ids=True,
    )
    identity_values = _repository_plan_require_list(
        approval.get("repository_identities"),
        "/approval/repository_identities",
    )
    identity_ids: list[str] = []
    for index, item in enumerate(identity_values):
        pointer = f"/approval/repository_identities/{index}"
        identity = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            identity,
            _repository_plan_approval_repository_identity_fields,
            pointer,
        )
        identity_ids.append(
            _repository_plan_require_string(
                identity.get("repository_id"),
                f"{pointer}/repository_id",
                stable_id=True,
            )
        )
        _repository_plan_require_digest(
            identity.get("identity_sha256"),
            f"{pointer}/identity_sha256",
        )
    if identity_ids != sorted(
        identity_ids, key=_repository_plan_utf8_key
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "approval repository identities must be ordered",
            pointer="/approval/repository_identities",
        )
    contract_values = _repository_plan_require_list(
        approval.get("interface_contracts"),
        "/approval/interface_contracts",
    )
    contract_ids: list[str] = []
    for index, item in enumerate(contract_values):
        pointer = f"/approval/interface_contracts/{index}"
        contract = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            contract,
            _repository_plan_approval_contract_fields,
            pointer,
        )
        contract_ids.append(
            _repository_plan_require_string(
                contract.get("contract_id"),
                f"{pointer}/contract_id",
                stable_id=True,
            )
        )
        _repository_plan_require_digest(
            contract.get("sha256"), f"{pointer}/sha256"
        )
    if contract_ids != sorted(
        contract_ids, key=_repository_plan_utf8_key
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "approval interface contracts must be ordered",
            pointer="/approval/interface_contracts",
        )
    path_values = _repository_plan_require_list(
        approval.get("approved_paths"), "/approval/approved_paths"
    )
    path_repository_ids: list[str] = []
    for index, item in enumerate(path_values):
        pointer = f"/approval/approved_paths/{index}"
        path_binding = _repository_plan_require_mapping(item, pointer)
        _repository_plan_reject_unknown(
            path_binding,
            _repository_plan_approval_path_fields,
            pointer,
        )
        path_repository_ids.append(
            _repository_plan_require_string(
                path_binding.get("repository_id"),
                f"{pointer}/repository_id",
                stable_id=True,
            )
        )
        paths = _repository_plan_require_list(
            path_binding.get("paths"), f"{pointer}/paths"
        )
        for path_index, path in enumerate(paths):
            _repository_plan_portable_path(
                path, f"{pointer}/paths/{path_index}"
            )
    if path_repository_ids != sorted(
        path_repository_ids, key=_repository_plan_utf8_key
    ):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_ORDER_INVALID",
            "approval path bindings must be ordered",
            pointer="/approval/approved_paths",
        )
    _repository_plan_require_list(
        approval.get("dependency_edges"),
        "/approval/dependency_edges",
    )
    _repository_plan_require_mapping(
        approval.get("execution_policies"),
        "/approval/execution_policies",
    )
    return _repository_plan_freeze(approval)  # type: ignore[return-value]


def validate_repository_plan_approval(
    plan_value: object,
    approval_value: object,
    *,
    current_semantic_input_sha256: Optional[str] = None,
) -> Mapping[str, object]:
    """Validate exact plan binding without depending on current task revision."""

    plan = validate_repository_plan(plan_value)
    approval = _repository_plan_validate_approval_shape(approval_value)
    expected = _repository_plan_approval_projection(
        plan,
        plan_artifact_id=build_repository_plan_artifact(
            plan
        ).artifact_id,
        approval_intent=str(approval["approval_intent"]),
        approval_commit_revision=int(
            approval["approval_commit_revision"]
        ),
    )
    if _repository_plan_thaw(approval) != _repository_plan_thaw(expected):
        raise _repository_plan_error(
            "REPOSITORY_PLAN_APPROVAL_BINDING_MISMATCH",
            "repository plan approval does not bind the exact plan",
            pointer="/approval",
        )
    if current_semantic_input_sha256 is not None:
        current = _repository_plan_require_digest(
            current_semantic_input_sha256,
            "/current_semantic_input_sha256",
        )
        if current != str(plan["semantic_input_sha256"]):
            raise _repository_plan_error(
                "REPOSITORY_PLAN_APPROVAL_STALE",
                "live semantic inputs no longer match the approved plan",
                pointer="/current_semantic_input_sha256",
                details={
                    "approved": plan["semantic_input_sha256"],
                    "current": current,
                },
            )
    return approval


def repository_node_instance_preimage(
    *,
    task_id: str,
    workflow_bundle_sha256: str,
    plan_id: str,
    dag_sha256: str,
    map_epoch: int,
    repository_id: str,
    map_node_id: str,
) -> bytes:
    """Frame task/bundle/plan/epoch/repository/map-node in exact order."""

    fields = (
        _repository_plan_require_string(
            task_id, "/task_id", stable_id=True
        ),
        _repository_plan_require_digest(
            workflow_bundle_sha256, "/workflow_bundle_sha256"
        ),
        _repository_plan_require_string(
            plan_id, "/plan_id", stable_id=True
        ),
        _repository_plan_require_digest(
            dag_sha256, "/dag_sha256"
        ),
    )
    framed = bytearray(REPOSITORY_NODE_INSTANCE_DOMAIN)
    for field in fields:
        encoded = field.encode("utf-8")
        framed.extend(_repository_plan_u64be(len(encoded)))
        framed.extend(encoded)
    framed.extend(_repository_plan_u64be(map_epoch))
    for field, pointer in (
        (repository_id, "/repository_id"),
        (map_node_id, "/map_node_id"),
    ):
        validated = _repository_plan_require_string(
            field, pointer, stable_id=True
        )
        encoded = validated.encode("utf-8")
        framed.extend(_repository_plan_u64be(len(encoded)))
        framed.extend(encoded)
    return bytes(framed)


def repository_node_instance_id(
    *,
    task_id: str,
    workflow_bundle_sha256: str,
    plan_id: str,
    dag_sha256: str,
    map_epoch: int,
    repository_id: str,
    map_node_id: str,
) -> str:
    return "repository-node-" + hashlib.sha256(
        repository_node_instance_preimage(
            task_id=task_id,
            workflow_bundle_sha256=workflow_bundle_sha256,
            plan_id=plan_id,
            dag_sha256=dag_sha256,
            map_epoch=map_epoch,
            repository_id=repository_id,
            map_node_id=map_node_id,
        )
    ).hexdigest()


def _repository_plan_expected_expansion(
    plan: Mapping[str, object],
    *,
    child_node_id: Optional[str] = None,
) -> Mapping[str, object]:
    identity = repository_plan_identity(plan)
    repositories = plan["repositories"]
    dependencies = plan["dependencies"]
    assert isinstance(repositories, tuple)
    assert isinstance(dependencies, tuple)
    node_ids = {
        str(repository["repository_id"]): repository_node_instance_id(
            task_id=str(plan["task_id"]),
            workflow_bundle_sha256=str(
                plan["workflow_bundle_sha256"]
            ),
            plan_id=str(plan["plan_id"]),
            dag_sha256=identity.dag_sha256,
            map_epoch=int(plan["map_epoch"]),
            repository_id=str(repository["repository_id"]),
            map_node_id=str(plan["map_node_id"]),
        )
        for repository in repositories
    }
    predecessor_ids: dict[str, list[str]] = {
        repository_id: [] for repository_id in node_ids
    }
    for edge in dependencies:
        predecessor_ids[str(edge["to_repository_id"])].append(
            node_ids[str(edge["from_repository_id"])]
        )
    children = []
    persisted_child_node_id = (
        str(plan["map_node_id"])
        if child_node_id is None
        else _repository_plan_require_string(
            child_node_id,
            "/workflow_bundle/repository_orchestration/map/child_template/node_id",
            stable_id=True,
        )
    )
    for repository in repositories:
        repository_id = str(repository["repository_id"])
        children.append(
            {
                "node_instance_id": node_ids[repository_id],
                "node_id": persisted_child_node_id,
                "repository_id": repository_id,
                "repository_identity_sha256": repository[
                    "identity_sha256"
                ],
                "map_epoch": plan["map_epoch"],
                "dependencies": sorted(
                    predecessor_ids[repository_id],
                    key=_repository_plan_utf8_key,
                ),
            }
        )
    return _repository_plan_freeze(
        {
            "schema": REPOSITORY_MAP_EXPANSION_SCHEMA,
            "task_id": plan["task_id"],
            "workflow_bundle_sha256": plan[
                "workflow_bundle_sha256"
            ],
            "plan_id": plan["plan_id"],
            "dag_sha256": identity.dag_sha256,
            "semantic_input_sha256": plan[
                "semantic_input_sha256"
            ],
            "map_node_id": plan["map_node_id"],
            "map_epoch": plan["map_epoch"],
            "repository_set": list(plan["repository_set"]),
            "children": children,
        }
    )  # type: ignore[return-value]


def validate_repository_map_expansion(
    plan_value: object,
    expansion_value: object,
    *,
    workflow_bundle: object | None = None,
) -> Mapping[str, object]:
    plan = (
        validate_repository_plan(plan_value)
        if workflow_bundle is None
        else validate_repository_plan_against_workflow_bundle(
            plan_value, workflow_bundle
        )
    )
    expansion = _repository_plan_require_mapping(
        expansion_value, "/expansion"
    )
    _repository_plan_validate_json_value(expansion, "/expansion")
    _repository_plan_reject_unknown(
        expansion, _repository_plan_expansion_fields, "/expansion"
    )
    if expansion.get("schema") != REPOSITORY_MAP_EXPANSION_SCHEMA:
        raise _repository_plan_error(
            "REPOSITORY_MAP_EXPANSION_SCHEMA_UNSUPPORTED",
            "repository map expansion schema is unsupported",
            pointer="/expansion/schema",
            details={"schema": expansion.get("schema")},
        )
    children = _repository_plan_require_list(
        expansion.get("children"), "/expansion/children"
    )
    for index, child_value in enumerate(children):
        pointer = f"/expansion/children/{index}"
        child = _repository_plan_require_mapping(child_value, pointer)
        _repository_plan_reject_unknown(
            child, _repository_plan_child_fields, pointer
        )
        for field in (
            "node_instance_id",
            "node_id",
            "repository_id",
        ):
            _repository_plan_require_string(
                child.get(field),
                f"{pointer}/{field}",
                stable_id=True,
            )
        _repository_plan_require_digest(
            child.get("repository_identity_sha256"),
            f"{pointer}/repository_identity_sha256",
        )
        _repository_plan_require_int(
            child.get("map_epoch"),
            f"{pointer}/map_epoch",
            minimum=1,
        )
        _repository_plan_require_canonical_strings(
            child.get("dependencies"),
            f"{pointer}/dependencies",
            stable_ids=True,
        )
    child_node_id = None
    if workflow_bundle is not None:
        child_node_id = str(
            _repository_plan_workflow_binding(workflow_bundle)[
                "child_node_id"
            ]
        )
    expected = _repository_plan_expected_expansion(
        plan, child_node_id=child_node_id
    )
    if _repository_plan_thaw(expansion) != _repository_plan_thaw(expected):
        raise _repository_plan_error(
            "REPOSITORY_MAP_EXPANSION_CONFLICT",
            "persisted expansion differs from canonical map input",
            pointer="/expansion",
        )
    return expected


def expand_repository_map(
    plan_value: object,
    approval_value: object,
    *,
    current_semantic_input_sha256: Optional[str] = None,
    existing_expansion: Optional[Mapping[str, object]] = None,
    workflow_bundle: object | None = None,
) -> Mapping[str, object]:
    """Derive stable children without persisting or dispatching them."""

    plan = (
        validate_repository_plan(plan_value)
        if workflow_bundle is None
        else validate_repository_plan_against_workflow_bundle(
            plan_value, workflow_bundle
        )
    )
    validate_repository_plan_approval(
        plan,
        approval_value,
        current_semantic_input_sha256=current_semantic_input_sha256,
    )
    child_node_id = None
    if workflow_bundle is not None:
        child_node_id = str(
            _repository_plan_workflow_binding(workflow_bundle)[
                "child_node_id"
            ]
        )
    expected = _repository_plan_expected_expansion(
        plan, child_node_id=child_node_id
    )
    if existing_expansion is not None:
        return validate_repository_map_expansion(
            plan,
            existing_expansion,
            workflow_bundle=workflow_bundle,
        )
    return expected


def expand_repository_map_for_workflow_bundle(
    plan_value: object,
    approval_value: object,
    workflow_bundle: object,
    *,
    current_semantic_input_sha256: Optional[str] = None,
    existing_expansion: Optional[Mapping[str, object]] = None,
) -> Mapping[str, object]:
    """Derive children bound to the pinned bundle child-node template."""

    return expand_repository_map(
        plan_value,
        approval_value,
        current_semantic_input_sha256=current_semantic_input_sha256,
        existing_expansion=existing_expansion,
        workflow_bundle=workflow_bundle,
    )


def repository_map_expansion_sha256(
    expansion_value: object,
) -> str:
    expansion = _repository_plan_require_mapping(
        expansion_value, "/expansion"
    )
    _repository_plan_validate_json_value(expansion, "/expansion")
    canonical = _repository_plan_canonical_json_bytes(expansion)
    preimage = (
        REPOSITORY_MAP_EXPANSION_DOMAIN
        + _repository_plan_u64be(len(canonical))
        + canonical
    )
    return hashlib.sha256(preimage).hexdigest()


def repository_retry_approval_id(
    repository_id: str,
    attempt: int,
) -> str:
    validated_id = _repository_plan_require_string(
        repository_id, "/repository_id", stable_id=True
    )
    validated_attempt = _repository_plan_require_int(
        attempt, "/attempt", minimum=2
    )
    return f"retry/{validated_id}/{validated_attempt}"


def _repository_plan_validate_boolean_fact(
    facts: Mapping[str, object],
    identifier: str,
    *,
    pointer: str,
    expected_repository_id: Optional[str] = None,
    expected_result_id: Optional[str] = None,
) -> bool:
    raw = facts.get(identifier)
    if raw is None:
        return False
    fact = _repository_plan_require_mapping(
        raw, f"{pointer}/{_repository_plan_pointer_segment(identifier)}"
    )
    _repository_plan_reject_unknown(
        fact,
        _repository_plan_fact_fields,
        f"{pointer}/{_repository_plan_pointer_segment(identifier)}",
    )
    fact_pointer = (
        f"{pointer}/{_repository_plan_pointer_segment(identifier)}"
    )
    accepted = _repository_plan_require_bool(
        fact.get("accepted"), f"{fact_pointer}/accepted"
    )
    current = _repository_plan_require_bool(
        fact.get("current"), f"{fact_pointer}/current"
    )
    repository_id = fact.get("repository_id")
    if repository_id is not None:
        repository_id = _repository_plan_require_string(
            repository_id,
            f"{fact_pointer}/repository_id",
            stable_id=True,
        )
    result_id = fact.get("result_id")
    if result_id is not None:
        result_id = _repository_plan_require_string(
            result_id,
            f"{fact_pointer}/result_id",
            stable_id=True,
        )
    repository_matches = (
        expected_repository_id is None
        or repository_id == expected_repository_id
    )
    result_matches = (
        expected_result_id is None or result_id == expected_result_id
    )
    return accepted and current and repository_matches and result_matches


def calculate_repository_ready_frontier(
    plan_value: object,
    approval_value: object,
    *,
    node_facts: Optional[Mapping[str, object]] = None,
    accepted_results: Optional[Mapping[str, object]] = None,
    approval_facts: Optional[Mapping[str, object]] = None,
    evidence_facts: Optional[Mapping[str, object]] = None,
    current_semantic_input_sha256: Optional[str] = None,
) -> RepositoryReadyFrontier:
    """Compute readiness from pinned facts; never infer dependency edges."""

    plan = validate_repository_plan(plan_value)
    validate_repository_plan_approval(
        plan,
        approval_value,
        current_semantic_input_sha256=current_semantic_input_sha256,
    )
    nodes = _repository_plan_require_mapping(
        node_facts or {}, "/node_facts"
    )
    results = _repository_plan_require_mapping(
        accepted_results or {}, "/accepted_results"
    )
    approvals = _repository_plan_require_mapping(
        approval_facts or {}, "/approval_facts"
    )
    evidence = _repository_plan_require_mapping(
        evidence_facts or {}, "/evidence_facts"
    )
    repository_ids = tuple(str(item) for item in plan["repository_set"])
    unknown_node_ids = sorted(
        (set(nodes) | set(results)) - set(repository_ids),
        key=_repository_plan_utf8_key,
    )
    if unknown_node_ids:
        raise _repository_plan_error(
            "REPOSITORY_READY_FACT_UNKNOWN_REPOSITORY",
            "runtime facts name repositories outside the approved set",
            pointer="/node_facts",
            details={"repository_ids": unknown_node_ids},
        )
    expansion = _repository_plan_expected_expansion(plan)
    child_by_repository = {
        str(child["repository_id"]): child
        for child in expansion["children"]
    }
    repository_by_id = {
        str(repository["repository_id"]): repository
        for repository in plan["repositories"]
    }
    incoming: dict[str, list[Mapping[str, object]]] = {
        repository_id: [] for repository_id in repository_ids
    }
    for edge in plan["dependencies"]:
        incoming[str(edge["to_repository_id"])].append(edge)
    normalized_nodes: dict[str, Mapping[str, object]] = {}
    active_workers = 0
    active_writable_workers = 0
    for repository_id in repository_ids:
        raw = nodes.get(
            repository_id,
            {"state": "PENDING", "attempts_started": 0},
        )
        pointer = (
            f"/node_facts/{_repository_plan_pointer_segment(repository_id)}"
        )
        node = _repository_plan_require_mapping(raw, pointer)
        _repository_plan_reject_unknown(
            node, _repository_plan_node_fact_fields, pointer
        )
        state = _repository_plan_require_string(
            node.get("state"), f"{pointer}/state"
        )
        if state not in _repository_plan_node_states:
            raise _repository_plan_error(
                "REPOSITORY_READY_NODE_STATE_INVALID",
                "repository node state is unsupported",
                pointer=f"{pointer}/state",
                details={"state": state},
            )
        attempts_started = _repository_plan_require_int(
            node.get("attempts_started"),
            f"{pointer}/attempts_started",
            minimum=0,
        )
        if (
            state in _repository_plan_retryable_states
            and attempts_started == 0
        ):
            raise _repository_plan_error(
                "REPOSITORY_READY_ATTEMPT_INVALID",
                "failed or blocked nodes require a recorded attempt",
                pointer=f"{pointer}/attempts_started",
                details={"state": state},
            )
        normalized_nodes[repository_id] = MappingProxyType(
            {
                "state": state,
                "attempts_started": attempts_started,
            }
        )
        if state == "RUNNING":
            active_workers += 1
            if (
                repository_by_id[repository_id]["write_policy"]
                == "scoped-write"
            ):
                active_writable_workers += 1

    normalized_results: dict[str, Mapping[str, object]] = {}
    for repository_id, raw_result in results.items():
        pointer = (
            "/accepted_results/"
            + _repository_plan_pointer_segment(repository_id)
        )
        result = _repository_plan_require_mapping(raw_result, pointer)
        _repository_plan_reject_unknown(
            result, _repository_plan_result_fields, pointer
        )
        outcome = _repository_plan_require_string(
            result.get("outcome"), f"{pointer}/outcome"
        )
        if outcome not in {"SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED"}:
            raise _repository_plan_error(
                "REPOSITORY_READY_RESULT_INVALID",
                "accepted result outcome is unsupported",
                pointer=f"{pointer}/outcome",
                details={"outcome": outcome},
            )
        normalized_results[repository_id] = MappingProxyType(
            {
                "result_id": _repository_plan_require_string(
                    result.get("result_id"),
                    f"{pointer}/result_id",
                    stable_id=True,
                ),
                "outcome": outcome,
                "accepted": _repository_plan_require_bool(
                    result.get("accepted"), f"{pointer}/accepted"
                ),
                "current": _repository_plan_require_bool(
                    result.get("current"), f"{pointer}/current"
                ),
                "output_contract_sha256": (
                    _repository_plan_require_canonical_strings(
                        result.get("output_contract_sha256"),
                        f"{pointer}/output_contract_sha256",
                        digests=True,
                    )
                ),
            }
        )

    retry_policy = plan["retry_policy"]
    concurrency_policy = plan["concurrency_policy"]
    assert isinstance(retry_policy, Mapping)
    assert isinstance(concurrency_policy, Mapping)
    ready: list[ReadyRepository] = []
    blocked: list[RepositoryReadinessBlocker] = []
    for repository_id in repository_ids:
        node = normalized_nodes[repository_id]
        repository = repository_by_id[repository_id]
        state = str(node["state"])
        attempts_started = int(node["attempts_started"])
        blocker_codes: set[str] = set()
        retrying = state in _repository_plan_retryable_states
        if state in {"RUNNING", "SUCCEEDED", "SKIPPED"}:
            blocker_codes.add("NODE_NOT_PENDING")
        elif retrying:
            if state not in set(retry_policy["retryable_states"]):
                blocker_codes.add("RETRY_STATE_NOT_ALLOWED")
            if attempts_started >= int(retry_policy["max_attempts"]):
                blocker_codes.add("RETRY_EXHAUSTED")
            next_attempt = attempts_started + 1
            if retry_policy["requires_approval"]:
                retry_approval = repository_retry_approval_id(
                    repository_id, next_attempt
                )
                if not _repository_plan_validate_boolean_fact(
                    approvals,
                    retry_approval,
                    pointer="/approval_facts",
                ):
                    blocker_codes.add("RETRY_APPROVAL_NOT_CURRENT")
        elif state not in _repository_plan_candidate_states:
            blocker_codes.add("NODE_NOT_PENDING")

        for approval_id in repository["required_approval_ids"]:
            if not _repository_plan_validate_boolean_fact(
                approvals,
                str(approval_id),
                pointer="/approval_facts",
            ):
                blocker_codes.add("REQUIRED_APPROVAL_NOT_CURRENT")
        for digest in repository[
            "required_evidence_contract_sha256"
        ]:
            if not _repository_plan_validate_boolean_fact(
                evidence,
                str(digest),
                pointer="/evidence_facts",
            ):
                blocker_codes.add("REQUIRED_EVIDENCE_NOT_CURRENT")

        for edge in incoming[repository_id]:
            predecessor = str(edge["from_repository_id"])
            result = normalized_results.get(predecessor)
            if result is None:
                blocker_codes.add("DEPENDENCY_RESULT_MISSING")
                continue
            if not result["accepted"]:
                blocker_codes.add("DEPENDENCY_RESULT_NOT_ACCEPTED")
            if not result["current"]:
                blocker_codes.add("DEPENDENCY_RESULT_STALE")
            if result["outcome"] != "SUCCEEDED":
                blocker_codes.add("DEPENDENCY_RESULT_NOT_SUCCESSFUL")
            output_contract = str(edge["output_contract_sha256"])
            if output_contract not in result["output_contract_sha256"]:
                blocker_codes.add("DEPENDENCY_OUTPUT_CONTRACT_MISMATCH")
            if not _repository_plan_validate_boolean_fact(
                evidence,
                output_contract,
                pointer="/evidence_facts",
                expected_repository_id=predecessor,
                expected_result_id=str(result["result_id"]),
            ):
                blocker_codes.add("DEPENDENCY_OUTPUT_EVIDENCE_NOT_CURRENT")
            for required_digest in edge[
                "required_evidence_contract_sha256"
            ]:
                if not _repository_plan_validate_boolean_fact(
                    evidence,
                    str(required_digest),
                    pointer="/evidence_facts",
                ):
                    blocker_codes.add(
                        "DEPENDENCY_REQUIRED_EVIDENCE_NOT_CURRENT"
                    )

        if blocker_codes:
            blocked.append(
                RepositoryReadinessBlocker(
                    repository_id=repository_id,
                    codes=tuple(
                        sorted(
                            blocker_codes,
                            key=_repository_plan_utf8_key,
                        )
                    ),
                )
            )
            continue
        child = child_by_repository[repository_id]
        ready.append(
            ReadyRepository(
                node_instance_id=str(child["node_instance_id"]),
                repository_id=repository_id,
                repository_identity_sha256=str(
                    repository["identity_sha256"]
                ),
                attempt=attempts_started + 1,
                write_policy=str(repository["write_policy"]),
                dependency_node_instance_ids=tuple(
                    str(item) for item in child["dependencies"]
                ),
            )
        )

    available_workers = max(
        0, int(concurrency_policy["max_workers"]) - active_workers
    )
    available_writable = max(
        0,
        int(concurrency_policy["max_writable_workers"])
        - active_writable_workers,
    )
    dispatchable: list[ReadyRepository] = []
    remaining_workers = available_workers
    remaining_writable = available_writable
    for item in ready:
        if remaining_workers == 0:
            break
        if item.write_policy == "scoped-write":
            if remaining_writable == 0:
                continue
            remaining_writable -= 1
        dispatchable.append(item)
        remaining_workers -= 1
    return RepositoryReadyFrontier(
        ready=tuple(ready),
        dispatchable=tuple(dispatchable),
        blocked=tuple(blocked),
        active_workers=active_workers,
        active_writable_workers=active_writable_workers,
        available_workers=available_workers,
        available_writable_workers=available_writable,
    )
