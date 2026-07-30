"""Pure external-tool capability and evidence contracts.

This fragment deliberately performs no discovery and no persistence.  It
normalizes identity-covered declarations, binds codebase-memory traffic to one
controller-selected source identity, and validates returned candidates before
they can be considered complete evidence.
"""
from __future__ import annotations

import hashlib as _external_tools_hashlib
import json as _external_tools_json
import re as _external_tools_re
import struct as _external_tools_struct
import unicodedata as _external_tools_unicodedata
from dataclasses import dataclass as _external_tools_dataclass
from types import MappingProxyType as _ExternalToolsMappingProxyType
from typing import (
    Iterable as _ExternalToolsIterable,
    Mapping as _ExternalToolsMapping,
    Optional as _ExternalToolsOptional,
    Sequence as _ExternalToolsSequence,
)


EXTERNAL_TOOL_CAPABILITY_SCHEMA = "dev-flow-external-tool-capability/v1"
CODEBASE_MEMORY_BINDING_SCHEMA = "dev-flow-codebase-memory-binding/v1"
CODEBASE_MEMORY_ASSIGNMENT_SCHEMA = "dev-flow-codebase-memory-assignment/v1"
CODEBASE_MEMORY_REQUEST_SCHEMA = "dev-flow-codebase-memory-request/v1"
CODEBASE_MEMORY_RESULT_SCHEMA = "dev-flow-codebase-memory-result/v1"
EXTERNAL_SOURCE_CANDIDATE_SCHEMA = "dev-flow-external-source-candidate/v1"
BOUND_SOURCE_CONFIRMATION_SCHEMA = "dev-flow-bound-source-confirmation/v1"
EXTERNAL_CONCLUSION_SCHEMA = "dev-flow-external-conclusion/v1"
EXTERNAL_EVIDENCE_DECISION_SCHEMA = "dev-flow-external-evidence-decision/v1"
EXTERNAL_TOOL_ROLE_PROFILE_SCHEMA = (
    "dev-flow-external-tool-role-profile/v1"
)
EXTERNAL_TOOL_EXECUTION_GRANT_SCHEMA = (
    "dev-flow-external-tool-execution-grant/v1"
)
EXTERNAL_TOOL_DECLARATION_SET_SCHEMA = (
    "dev-flow-external-tool-declaration-set/v1"
)

CODEBASE_MEMORY_TOOL_ID = "codebase-memory"
CODEBASE_MEMORY_BASELINE_PHASE = "baseline"
CODEBASE_MEMORY_CURRENT_PHASE = "current-generation-workspace"
CODEBASE_MEMORY_PHASES = frozenset(
    {
        CODEBASE_MEMORY_BASELINE_PHASE,
        CODEBASE_MEMORY_CURRENT_PHASE,
    }
)

_external_tools_digest_re = _external_tools_re.compile(r"^[0-9a-f]{64}$")
_external_tools_stable_id_re = _external_tools_re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$"
)
_external_tools_capability_id_re = _external_tools_re.compile(
    r"^tool\.[a-z0-9][a-z0-9.-]{0,126}/v[1-9][0-9]*$"
)
_external_tools_operation_values = frozenset(
    {"external-read", "external-write"}
)


class ExternalToolContractError(ValueError):
    """Stable fail-closed diagnostic for external-tool contracts."""

    __slots__ = ("code", "message", "details")

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _ExternalToolsOptional[
            _ExternalToolsMapping[str, object]
        ] = None,
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


def _external_tools_error(
    code: str,
    message: str,
    *,
    field: _ExternalToolsOptional[str] = None,
    details: _ExternalToolsOptional[
        _ExternalToolsMapping[str, object]
    ] = None,
) -> ExternalToolContractError:
    payload = dict(details or {})
    if field is not None:
        payload.setdefault("field", field)
    return ExternalToolContractError(code, message, details=payload)


def _external_tools_require_nfc(value: str, field: str) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise _external_tools_error(
            "EXTERNAL_TOOL_STRING_INVALID",
            "external-tool strings must be valid UTF-8",
            field=field,
        ) from exc
    if _external_tools_unicodedata.normalize("NFC", value) != value:
        raise _external_tools_error(
            "EXTERNAL_TOOL_STRING_NOT_CANONICAL",
            "external-tool strings must already use NFC normalization",
            field=field,
        )
    if len(encoded) > 4096:
        raise _external_tools_error(
            "EXTERNAL_TOOL_STRING_TOO_LARGE",
            "external-tool string exceeds its UTF-8 byte budget",
            field=field,
        )
    return value


def _external_tools_freeze(value: object, field: str = "$") -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return _external_tools_require_nfc(value, field)
    if isinstance(value, float):
        raise _external_tools_error(
            "EXTERNAL_TOOL_VALUE_INVALID",
            "floating-point values are not canonical external-tool values",
            field=field,
        )
    if isinstance(value, _ExternalToolsMapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise _external_tools_error(
                    "EXTERNAL_TOOL_VALUE_INVALID",
                    "external-tool object keys must be non-empty strings",
                    field=field,
                )
            canonical_key = _external_tools_require_nfc(key, field)
            if canonical_key in frozen:
                raise _external_tools_error(
                    "EXTERNAL_TOOL_VALUE_INVALID",
                    "external-tool object keys must be unique",
                    field=field,
                )
            frozen[canonical_key] = _external_tools_freeze(
                item, f"{field}/{canonical_key}"
            )
        return _ExternalToolsMappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _external_tools_freeze(item, f"{field}/{index}")
            for index, item in enumerate(value)
        )
    raise _external_tools_error(
        "EXTERNAL_TOOL_VALUE_INVALID",
        "external-tool values must use canonical JSON types",
        field=field,
        details={"type": type(value).__name__},
    )


def _external_tools_thaw(value: object) -> object:
    if isinstance(value, _ExternalToolsMapping):
        return {
            str(key): _external_tools_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_external_tools_thaw(item) for item in value]
    return value


def canonical_external_tool_bytes(value: object) -> bytes:
    """Return strict, deterministic UTF-8 JSON bytes."""

    frozen = _external_tools_freeze(value)
    try:
        return _external_tools_json.dumps(
            _external_tools_thaw(frozen),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, ExternalToolContractError):
            raise
        raise _external_tools_error(
            "EXTERNAL_TOOL_VALUE_INVALID",
            "external-tool value cannot be canonically encoded",
        ) from exc


def external_tool_content_sha256(domain: str, value: object) -> str:
    """Hash a canonical value with an unambiguous domain-separated preimage."""

    normalized_domain = _external_tools_require_stable_id(
        domain, "domain"
    )
    domain_bytes = normalized_domain.encode("utf-8")
    payload = canonical_external_tool_bytes(value)
    preimage = (
        _external_tools_struct.pack(">Q", len(domain_bytes))
        + domain_bytes
        + _external_tools_struct.pack(">Q", len(payload))
        + payload
    )
    return _external_tools_hashlib.sha256(preimage).hexdigest()


def _external_tools_require_string(
    value: object,
    field: str,
    *,
    maximum_bytes: int = 1024,
) -> str:
    if not isinstance(value, str) or not value:
        raise _external_tools_error(
            "EXTERNAL_TOOL_FIELD_REQUIRED",
            "external-tool field must be a non-empty string",
            field=field,
        )
    normalized = _external_tools_require_nfc(value, field)
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise _external_tools_error(
            "EXTERNAL_TOOL_FIELD_TOO_LARGE",
            "external-tool field exceeds its UTF-8 byte budget",
            field=field,
        )
    return normalized


def _external_tools_require_stable_id(
    value: object, field: str
) -> str:
    normalized = _external_tools_require_string(value, field)
    if not _external_tools_stable_id_re.fullmatch(normalized):
        raise _external_tools_error(
            "EXTERNAL_TOOL_ID_INVALID",
            "external-tool identifier is not canonical",
            field=field,
        )
    return normalized


def _external_tools_require_digest(
    value: object, field: str
) -> str:
    if (
        not isinstance(value, str)
        or not _external_tools_digest_re.fullmatch(value)
    ):
        raise _external_tools_error(
            "EXTERNAL_TOOL_DIGEST_INVALID",
            "external-tool digest must be lowercase SHA-256",
            field=field,
        )
    return value


def _external_tools_require_revision(
    value: object, field: str
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _external_tools_error(
            "EXTERNAL_TOOL_REVISION_INVALID",
            "controller revision must be a non-negative integer",
            field=field,
        )
    return value


def _external_tools_require_exact_keys(
    value: object,
    required: _ExternalToolsIterable[str],
    *,
    field: str,
) -> _ExternalToolsMapping[str, object]:
    if not isinstance(value, _ExternalToolsMapping):
        raise _external_tools_error(
            "EXTERNAL_TOOL_OBJECT_INVALID",
            "external-tool contract must be an object",
            field=field,
        )
    if any(not isinstance(key, str) for key in value.keys()):
        raise _external_tools_error(
            "EXTERNAL_TOOL_FIELDS_INVALID",
            "external-tool contract field names must be strings",
            field=field,
        )
    expected = frozenset(required)
    actual = frozenset(value.keys())
    if actual != expected:
        raise _external_tools_error(
            "EXTERNAL_TOOL_FIELDS_INVALID",
            "external-tool contract fields do not match its schema",
            field=field,
            details={
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            },
        )
    return value


def _external_tools_unique_sorted_ids(
    values: _ExternalToolsIterable[object], field: str
) -> tuple[str, ...]:
    normalized = tuple(
        _external_tools_require_stable_id(item, field)
        for item in values
    )
    if len(set(normalized)) != len(normalized):
        raise _external_tools_error(
            "EXTERNAL_TOOL_DUPLICATE_VALUE",
            "external-tool list values must be unique",
            field=field,
        )
    if normalized != tuple(sorted(normalized)):
        raise _external_tools_error(
            "EXTERNAL_TOOL_ORDER_INVALID",
            "external-tool list values must be sorted canonically",
            field=field,
        )
    return normalized


@_external_tools_dataclass(frozen=True)
class ExternalToolCapability:
    capability_id: str
    tool_id: str
    operations: tuple[str, ...]
    result_schema: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_id",
            _external_tools_require_string(
                self.capability_id, "capability_id"
            ),
        )
        if not _external_tools_capability_id_re.fullmatch(
            self.capability_id
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_CAPABILITY_ID_INVALID",
                "tool capability id must be versioned and canonical",
                field="capability_id",
            )
        object.__setattr__(
            self,
            "tool_id",
            _external_tools_require_stable_id(self.tool_id, "tool_id"),
        )
        normalized_operations = tuple(self.operations)
        if (
            not normalized_operations
            or normalized_operations
            != tuple(sorted(set(normalized_operations)))
            or any(
                operation not in _external_tools_operation_values
                for operation in normalized_operations
            )
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_OPERATIONS_INVALID",
                "tool operations must be a non-empty sorted unique subset",
                field="operations",
            )
        object.__setattr__(self, "operations", normalized_operations)
        object.__setattr__(
            self,
            "result_schema",
            _external_tools_require_stable_id(
                self.result_schema, "result_schema"
            ),
        )
        object.__setattr__(
            self,
            "scopes",
            _external_tools_unique_sorted_ids(self.scopes, "scopes"),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_TOOL_CAPABILITY_SCHEMA,
            "capability_id": self.capability_id,
            "tool_id": self.tool_id,
            "operations": list(self.operations),
            "result_schema": self.result_schema,
            "scopes": list(self.scopes),
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            EXTERNAL_TOOL_CAPABILITY_SCHEMA,
            self.identity_payload(),
        )

    def as_dict(self) -> dict[str, object]:
        result = self.identity_payload()
        result["sha256"] = self.sha256
        return result

    @classmethod
    def from_dict(
        cls, value: object
    ) -> "ExternalToolCapability":
        mapping = _external_tools_require_exact_keys(
            value,
            {
                "schema",
                "capability_id",
                "tool_id",
                "operations",
                "result_schema",
                "scopes",
                "sha256",
            },
            field="capability",
        )
        if mapping["schema"] != EXTERNAL_TOOL_CAPABILITY_SCHEMA:
            raise _external_tools_error(
                "EXTERNAL_TOOL_SCHEMA_INVALID",
                "tool capability schema is not supported",
                field="schema",
            )
        if not isinstance(mapping["operations"], (list, tuple)):
            raise _external_tools_error(
                "EXTERNAL_TOOL_OPERATIONS_INVALID",
                "tool capability operations must be an array",
                field="operations",
            )
        if not isinstance(mapping["scopes"], (list, tuple)):
            raise _external_tools_error(
                "EXTERNAL_TOOL_SCOPES_INVALID",
                "tool capability scopes must be an array",
                field="scopes",
            )
        result = cls(
            capability_id=mapping["capability_id"],  # type: ignore[arg-type]
            tool_id=mapping["tool_id"],  # type: ignore[arg-type]
            operations=tuple(mapping["operations"]),  # type: ignore[arg-type]
            result_schema=mapping["result_schema"],  # type: ignore[arg-type]
            scopes=tuple(mapping["scopes"]),  # type: ignore[arg-type]
        )
        supplied_sha256 = _external_tools_require_digest(
            mapping["sha256"], "sha256"
        )
        if supplied_sha256 != result.sha256:
            raise _external_tools_error(
                "EXTERNAL_TOOL_IDENTITY_MISMATCH",
                "tool capability identity does not match its content",
                field="sha256",
            )
        return result


def validate_tool_capability_exposure(
    declarations: _ExternalToolsSequence[ExternalToolCapability],
    exposed_capability_ids: _ExternalToolsIterable[object],
) -> tuple[ExternalToolCapability, ...]:
    """Return least-capability exposure, rejecting undeclared identities."""

    by_id: dict[str, ExternalToolCapability] = {}
    for declaration in declarations:
        if not isinstance(declaration, ExternalToolCapability):
            raise _external_tools_error(
                "EXTERNAL_TOOL_CAPABILITY_INVALID",
                "capability declarations must be validated contracts",
            )
        if declaration.capability_id in by_id:
            raise _external_tools_error(
                "EXTERNAL_TOOL_CAPABILITY_DUPLICATE",
                "capability ids must be unique",
                field="capability_id",
            )
        by_id[declaration.capability_id] = declaration
    exposed = _external_tools_unique_sorted_ids(
        exposed_capability_ids, "exposed_capability_ids"
    )
    undeclared = tuple(item for item in exposed if item not in by_id)
    if undeclared:
        raise _external_tools_error(
            "EXTERNAL_TOOL_CAPABILITY_UNDECLARED",
            "assignment or role profile exposes an undeclared tool",
            details={"capability_ids": list(undeclared)},
        )
    return tuple(by_id[item] for item in exposed)


def external_tool_capabilities_from_catalog(
    value: object,
) -> tuple[ExternalToolCapability, ...]:
    """Materialize the exact identity-covered catalog declarations."""

    graph = (
        getattr(value, "graph")
        if hasattr(value, "graph")
        else value
    )
    if not isinstance(graph, _ExternalToolsMapping):
        raise _external_tools_error(
            "EXTERNAL_TOOL_CATALOG_INVALID",
            "tool declarations require a validated workflow graph",
        )
    declarations = graph.get("tool_capabilities", ())
    if not isinstance(declarations, (list, tuple)):
        raise _external_tools_error(
            "EXTERNAL_TOOL_CATALOG_INVALID",
            "catalog tool declarations must be an array",
            field="tool_capabilities",
        )
    capabilities: list[ExternalToolCapability] = []
    for index, supplied in enumerate(declarations):
        mapping = _external_tools_require_exact_keys(
            supplied,
            {
                "schema",
                "capability_id",
                "tool_id",
                "operations",
                "result_schema",
                "scopes",
            },
            field=f"tool_capabilities/{index}",
        )
        if mapping["schema"] != EXTERNAL_TOOL_CAPABILITY_SCHEMA:
            raise _external_tools_error(
                "EXTERNAL_TOOL_SCHEMA_INVALID",
                "catalog tool capability schema is unsupported",
                field=f"tool_capabilities/{index}/schema",
            )
        if not isinstance(mapping["operations"], (list, tuple)) or not (
            isinstance(mapping["scopes"], (list, tuple))
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_CATALOG_INVALID",
                "catalog capability arrays are malformed",
                field=f"tool_capabilities/{index}",
            )
        capabilities.append(
            ExternalToolCapability(
                capability_id=mapping["capability_id"],  # type: ignore[arg-type]
                tool_id=mapping["tool_id"],  # type: ignore[arg-type]
                operations=tuple(mapping["operations"]),  # type: ignore[arg-type]
                result_schema=mapping["result_schema"],  # type: ignore[arg-type]
                scopes=tuple(mapping["scopes"]),  # type: ignore[arg-type]
            )
        )
    ids = tuple(item.capability_id for item in capabilities)
    if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
        raise _external_tools_error(
            "EXTERNAL_TOOL_CATALOG_INVALID",
            "catalog capabilities must have unique canonical identities",
            field="tool_capabilities",
        )
    return tuple(capabilities)


def external_tool_declaration_set_sha256(
    declarations: _ExternalToolsSequence[ExternalToolCapability],
) -> str:
    validated = validate_tool_capability_exposure(
        declarations,
        tuple(item.capability_id for item in declarations),
    )
    return external_tool_content_sha256(
        EXTERNAL_TOOL_DECLARATION_SET_SCHEMA,
        {
            "schema": EXTERNAL_TOOL_DECLARATION_SET_SCHEMA,
            "capabilities": [item.as_dict() for item in validated],
        },
    )


@_external_tools_dataclass(frozen=True)
class ExternalToolRoleProfile:
    role_id: str
    declaration_set_sha256: str
    capability_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "role_id",
            _external_tools_require_stable_id(self.role_id, "role_id"),
        )
        object.__setattr__(
            self,
            "declaration_set_sha256",
            _external_tools_require_digest(
                self.declaration_set_sha256,
                "declaration_set_sha256",
            ),
        )
        digests = tuple(
            _external_tools_require_digest(
                item, "capability_sha256s"
            )
            for item in self.capability_sha256s
        )
        if digests != tuple(sorted(set(digests))):
            raise _external_tools_error(
                "EXTERNAL_TOOL_ROLE_PROFILE_INVALID",
                "role capability digests must be unique and sorted",
                field="capability_sha256s",
            )
        object.__setattr__(self, "capability_sha256s", digests)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_TOOL_ROLE_PROFILE_SCHEMA,
            "role_id": self.role_id,
            "declaration_set_sha256": self.declaration_set_sha256,
            "capability_sha256s": list(self.capability_sha256s),
            "sha256": self.sha256,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            EXTERNAL_TOOL_ROLE_PROFILE_SCHEMA,
            {
                "schema": EXTERNAL_TOOL_ROLE_PROFILE_SCHEMA,
                "role_id": self.role_id,
                "declaration_set_sha256": (
                    self.declaration_set_sha256
                ),
                "capability_sha256s": list(
                    self.capability_sha256s
                ),
            },
        )


def build_external_tool_role_profile(
    *,
    role_id: str,
    declarations: _ExternalToolsSequence[ExternalToolCapability],
    exposed_capability_ids: _ExternalToolsIterable[object],
) -> ExternalToolRoleProfile:
    exposed = validate_tool_capability_exposure(
        declarations, exposed_capability_ids
    )
    return ExternalToolRoleProfile(
        role_id=role_id,
        declaration_set_sha256=external_tool_declaration_set_sha256(
            declarations
        ),
        capability_sha256s=tuple(
            sorted(item.sha256 for item in exposed)
        ),
    )


@_external_tools_dataclass(frozen=True)
class CodebaseMemoryBinding:
    phase: str
    generation: str
    repository_id: str
    source_snapshot_sha256: str
    project_id: str

    def __post_init__(self) -> None:
        if self.phase not in CODEBASE_MEMORY_PHASES:
            raise _external_tools_error(
                "CODEBASE_MEMORY_PHASE_INVALID",
                "codebase-memory phase is not supported",
                field="phase",
            )
        for field in ("generation", "repository_id", "project_id"):
            object.__setattr__(
                self,
                field,
                _external_tools_require_stable_id(
                    getattr(self, field), field
                ),
            )
        object.__setattr__(
            self,
            "source_snapshot_sha256",
            _external_tools_require_digest(
                self.source_snapshot_sha256,
                "source_snapshot_sha256",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CODEBASE_MEMORY_BINDING_SCHEMA,
            "phase": self.phase,
            "generation": self.generation,
            "repository_id": self.repository_id,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "project_id": self.project_id,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            CODEBASE_MEMORY_BINDING_SCHEMA, self.as_dict()
        )

    @classmethod
    def from_dict(cls, value: object) -> "CodebaseMemoryBinding":
        mapping = _external_tools_require_exact_keys(
            value,
            {
                "schema",
                "phase",
                "generation",
                "repository_id",
                "source_snapshot_sha256",
                "project_id",
            },
            field="binding",
        )
        if mapping["schema"] != CODEBASE_MEMORY_BINDING_SCHEMA:
            raise _external_tools_error(
                "CODEBASE_MEMORY_SCHEMA_INVALID",
                "codebase-memory binding schema is not supported",
                field="binding/schema",
            )
        return cls(
            phase=mapping["phase"],  # type: ignore[arg-type]
            generation=mapping["generation"],  # type: ignore[arg-type]
            repository_id=mapping["repository_id"],  # type: ignore[arg-type]
            source_snapshot_sha256=mapping[  # type: ignore[arg-type]
                "source_snapshot_sha256"
            ],
            project_id=mapping["project_id"],  # type: ignore[arg-type]
        )


def validate_codebase_memory_project_pair(
    baseline: CodebaseMemoryBinding,
    current: CodebaseMemoryBinding,
) -> tuple[CodebaseMemoryBinding, CodebaseMemoryBinding]:
    """Validate controller-selected baseline/current identities as a pair."""

    if (
        not isinstance(baseline, CodebaseMemoryBinding)
        or not isinstance(current, CodebaseMemoryBinding)
    ):
        raise _external_tools_error(
            "CODEBASE_MEMORY_BINDING_INVALID",
            "codebase-memory pair requires validated bindings",
        )
    if baseline.phase != CODEBASE_MEMORY_BASELINE_PHASE:
        raise _external_tools_error(
            "CODEBASE_MEMORY_PHASE_MISMATCH",
            "baseline binding has the wrong phase",
            field="baseline/phase",
        )
    if current.phase != CODEBASE_MEMORY_CURRENT_PHASE:
        raise _external_tools_error(
            "CODEBASE_MEMORY_PHASE_MISMATCH",
            "current workspace binding has the wrong phase",
            field="current/phase",
        )
    if baseline.repository_id != current.repository_id:
        raise _external_tools_error(
            "CODEBASE_MEMORY_REPOSITORY_MISMATCH",
            "baseline and current bindings must name one repository",
            field="repository_id",
        )
    if baseline.project_id == current.project_id:
        raise _external_tools_error(
            "CODEBASE_MEMORY_PROJECT_REUSED",
            "baseline and current workspace project identities must differ",
            field="project_id",
        )
    return baseline, current


@_external_tools_dataclass(frozen=True)
class CodebaseMemoryAssignment:
    capability_sha256: str
    binding: CodebaseMemoryBinding
    controller_revision: int
    scopes: tuple[str, ...]
    result_schema: str = CODEBASE_MEMORY_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "capability_sha256",
            _external_tools_require_digest(
                self.capability_sha256, "capability_sha256"
            ),
        )
        if not isinstance(self.binding, CodebaseMemoryBinding):
            raise _external_tools_error(
                "CODEBASE_MEMORY_BINDING_INVALID",
                "assignment binding must be validated",
                field="binding",
            )
        object.__setattr__(
            self,
            "controller_revision",
            _external_tools_require_revision(
                self.controller_revision, "controller_revision"
            ),
        )
        object.__setattr__(
            self,
            "scopes",
            _external_tools_unique_sorted_ids(self.scopes, "scopes"),
        )
        object.__setattr__(
            self,
            "result_schema",
            _external_tools_require_stable_id(
                self.result_schema, "result_schema"
            ),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": CODEBASE_MEMORY_ASSIGNMENT_SCHEMA,
            "capability_sha256": self.capability_sha256,
            "binding": self.binding.as_dict(),
            "controller_revision": self.controller_revision,
            "scopes": list(self.scopes),
            "result_schema": self.result_schema,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            CODEBASE_MEMORY_ASSIGNMENT_SCHEMA,
            self.identity_payload(),
        )

    def as_dict(self) -> dict[str, object]:
        result = self.identity_payload()
        result["sha256"] = self.sha256
        return result


def build_codebase_memory_assignment(
    capability: ExternalToolCapability,
    binding: CodebaseMemoryBinding,
    *,
    controller_revision: int,
    scopes: _ExternalToolsIterable[object],
) -> CodebaseMemoryAssignment:
    if not isinstance(capability, ExternalToolCapability):
        raise _external_tools_error(
            "EXTERNAL_TOOL_CAPABILITY_INVALID",
            "codebase-memory assignment requires a validated capability",
        )
    if (
        capability.tool_id != CODEBASE_MEMORY_TOOL_ID
        or capability.operations != ("external-read",)
    ):
        raise _external_tools_error(
            "CODEBASE_MEMORY_CAPABILITY_INVALID",
            "codebase-memory discovery must use a read-only capability",
        )
    normalized_scopes = _external_tools_unique_sorted_ids(
        scopes, "scopes"
    )
    undeclared = tuple(
        scope for scope in normalized_scopes if scope not in capability.scopes
    )
    if undeclared:
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPE_UNDECLARED",
            "assignment requests an undeclared codebase-memory scope",
            details={"scopes": list(undeclared)},
        )
    return CodebaseMemoryAssignment(
        capability_sha256=capability.sha256,
        binding=binding,
        controller_revision=controller_revision,
        scopes=normalized_scopes,
        result_schema=capability.result_schema,
    )


@_external_tools_dataclass(frozen=True)
class CodebaseMemoryRequest:
    assignment_sha256: str
    binding: CodebaseMemoryBinding
    controller_revision: int
    scopes: tuple[str, ...]
    query: str
    result_schema: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assignment_sha256",
            _external_tools_require_digest(
                self.assignment_sha256, "assignment_sha256"
            ),
        )
        if not isinstance(self.binding, CodebaseMemoryBinding):
            raise _external_tools_error(
                "CODEBASE_MEMORY_BINDING_INVALID",
                "request binding must be validated",
                field="binding",
            )
        object.__setattr__(
            self,
            "controller_revision",
            _external_tools_require_revision(
                self.controller_revision, "controller_revision"
            ),
        )
        object.__setattr__(
            self,
            "scopes",
            _external_tools_unique_sorted_ids(self.scopes, "scopes"),
        )
        object.__setattr__(
            self,
            "query",
            _external_tools_require_string(
                self.query, "query", maximum_bytes=8192
            ),
        )
        object.__setattr__(
            self,
            "result_schema",
            _external_tools_require_stable_id(
                self.result_schema, "result_schema"
            ),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": CODEBASE_MEMORY_REQUEST_SCHEMA,
            "assignment_sha256": self.assignment_sha256,
            "binding": self.binding.as_dict(),
            "controller_revision": self.controller_revision,
            "scopes": list(self.scopes),
            "query": self.query,
            "result_schema": self.result_schema,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            CODEBASE_MEMORY_REQUEST_SCHEMA, self.identity_payload()
        )

    def as_dict(self) -> dict[str, object]:
        result = self.identity_payload()
        result["sha256"] = self.sha256
        return result


def build_codebase_memory_request(
    assignment: CodebaseMemoryAssignment,
    *,
    query: str,
    scopes: _ExternalToolsOptional[
        _ExternalToolsIterable[object]
    ] = None,
) -> CodebaseMemoryRequest:
    if not isinstance(assignment, CodebaseMemoryAssignment):
        raise _external_tools_error(
            "CODEBASE_MEMORY_ASSIGNMENT_INVALID",
            "request requires a validated assignment",
        )
    normalized_scopes = (
        assignment.scopes
        if scopes is None
        else _external_tools_unique_sorted_ids(scopes, "scopes")
    )
    undeclared = tuple(
        scope
        for scope in normalized_scopes
        if scope not in assignment.scopes
    )
    if undeclared:
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPE_UNASSIGNED",
            "request uses scope not present in its assignment",
            details={"scopes": list(undeclared)},
        )
    return CodebaseMemoryRequest(
        assignment_sha256=assignment.sha256,
        binding=assignment.binding,
        controller_revision=assignment.controller_revision,
        scopes=normalized_scopes,
        query=query,
        result_schema=assignment.result_schema,
    )


@_external_tools_dataclass(frozen=True)
class ExternalToolExecutionGrant:
    """Exact external-tool authority shared by runtime and worker planes."""

    task_id: str
    workflow_bundle_sha256: str
    node_instance_id: str
    action_id: str
    execution_id: str
    effect_id: str
    attempt: int
    declaration_set_sha256: str
    edge_capability_ids: tuple[str, ...]
    capability: ExternalToolCapability
    assignment: CodebaseMemoryAssignment
    request: CodebaseMemoryRequest
    baseline_binding: CodebaseMemoryBinding
    current_binding: CodebaseMemoryBinding
    role_profile_sha256: _ExternalToolsOptional[str] = None

    def __post_init__(self) -> None:
        for field in (
            "task_id",
            "node_instance_id",
            "action_id",
            "execution_id",
            "effect_id",
        ):
            object.__setattr__(
                self,
                field,
                _external_tools_require_stable_id(
                    getattr(self, field), field
                ),
            )
        object.__setattr__(
            self,
            "workflow_bundle_sha256",
            _external_tools_require_digest(
                self.workflow_bundle_sha256,
                "workflow_bundle_sha256",
            ),
        )
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_ATTEMPT_INVALID",
                "external-tool attempt must be a positive integer",
                field="attempt",
            )
        object.__setattr__(
            self,
            "declaration_set_sha256",
            _external_tools_require_digest(
                self.declaration_set_sha256,
                "declaration_set_sha256",
            ),
        )
        object.__setattr__(
            self,
            "edge_capability_ids",
            _external_tools_unique_sorted_ids(
                self.edge_capability_ids, "edge_capability_ids"
            ),
        )
        if not isinstance(self.capability, ExternalToolCapability):
            raise _external_tools_error(
                "EXTERNAL_TOOL_CAPABILITY_INVALID",
                "execution grant requires a validated capability",
            )
        if not isinstance(self.assignment, CodebaseMemoryAssignment) or (
            not isinstance(self.request, CodebaseMemoryRequest)
        ):
            raise _external_tools_error(
                "CODEBASE_MEMORY_CONTRACT_INVALID",
                "execution grant requires assignment and request contracts",
            )
        baseline, current = validate_codebase_memory_project_pair(
            self.baseline_binding, self.current_binding
        )
        selected = (
            baseline
            if self.assignment.binding.phase
            == CODEBASE_MEMORY_BASELINE_PHASE
            else current
        )
        if selected.sha256 != self.assignment.binding.sha256:
            raise _external_tools_error(
                "CODEBASE_MEMORY_CONTROLLER_BINDING_MISMATCH",
                "grant assignment is not a controller-selected binding",
            )
        if (
            self.capability.tool_id != CODEBASE_MEMORY_TOOL_ID
            or self.capability.operations != ("external-read",)
            or self.capability.capability_id
            not in self.edge_capability_ids
            or self.assignment.capability_sha256
            != self.capability.sha256
            or self.request.assignment_sha256
            != self.assignment.sha256
            or self.request.binding.sha256
            != self.assignment.binding.sha256
            or self.request.controller_revision
            != self.assignment.controller_revision
            or self.request.result_schema
            != self.assignment.result_schema
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_EXECUTION_GRANT_INVALID",
                "grant capability, assignment, request, and edge differ",
            )
        if self.role_profile_sha256 is not None:
            object.__setattr__(
                self,
                "role_profile_sha256",
                _external_tools_require_digest(
                    self.role_profile_sha256,
                    "role_profile_sha256",
                ),
            )

    @property
    def binding(self) -> CodebaseMemoryBinding:
        return self.assignment.binding

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_TOOL_EXECUTION_GRANT_SCHEMA,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "action_id": self.action_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "attempt": self.attempt,
            "phase": self.binding.phase,
            "generation": self.binding.generation,
            "repository_id": self.binding.repository_id,
            "source_snapshot_sha256": (
                self.binding.source_snapshot_sha256
            ),
            "controller_revision": (
                self.assignment.controller_revision
            ),
            "project_id": self.binding.project_id,
            "declaration_set_sha256": (
                self.declaration_set_sha256
            ),
            "edge_capability_ids": list(
                self.edge_capability_ids
            ),
            "capability": self.capability.as_dict(),
            "assignment": self.assignment.as_dict(),
            "request": self.request.as_dict(),
            "baseline_binding": self.baseline_binding.as_dict(),
            "current_binding": self.current_binding.as_dict(),
            "role_profile_sha256": self.role_profile_sha256,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            EXTERNAL_TOOL_EXECUTION_GRANT_SCHEMA,
            self.identity_payload(),
        )

    def as_dict(self) -> dict[str, object]:
        value = self.identity_payload()
        value["sha256"] = self.sha256
        return value

    def runtime_binding(self) -> dict[str, object]:
        """Return the compact digest binding used in dispatch journals."""

        return {
            "schema": EXTERNAL_TOOL_EXECUTION_GRANT_SCHEMA,
            "sha256": self.sha256,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "action_id": self.action_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "attempt": self.attempt,
            "phase": self.binding.phase,
            "generation": self.binding.generation,
            "repository_id": self.binding.repository_id,
            "source_snapshot_sha256": (
                self.binding.source_snapshot_sha256
            ),
            "controller_revision": (
                self.assignment.controller_revision
            ),
            "project_id": self.binding.project_id,
            "declaration_set_sha256": (
                self.declaration_set_sha256
            ),
            "edge_capability_ids": list(
                self.edge_capability_ids
            ),
            "capability_sha256": self.capability.sha256,
            "assignment_sha256": self.assignment.sha256,
            "request_sha256": self.request.sha256,
            "baseline_binding_sha256": (
                self.baseline_binding.sha256
            ),
            "current_binding_sha256": self.current_binding.sha256,
            "role_profile_sha256": self.role_profile_sha256,
        }

    def as_safe_inputs(self) -> dict[str, object]:
        return {"external_tool_grant": self.runtime_binding()}


def build_external_tool_execution_grant(
    *,
    task_id: str,
    workflow_bundle_sha256: str,
    node_instance_id: str,
    action_id: str,
    execution_id: str,
    effect_id: str,
    attempt: int,
    declarations: _ExternalToolsSequence[ExternalToolCapability],
    edge_capability_ids: _ExternalToolsIterable[object],
    capability_id: str,
    assignment: CodebaseMemoryAssignment,
    request: CodebaseMemoryRequest,
    controller_project_bindings: _ExternalToolsSequence[
        CodebaseMemoryBinding
    ],
    role_profile: _ExternalToolsOptional[
        ExternalToolRoleProfile
    ] = None,
) -> ExternalToolExecutionGrant:
    exposed = validate_tool_capability_exposure(
        declarations, edge_capability_ids
    )
    by_id = {item.capability_id: item for item in exposed}
    if capability_id not in by_id:
        raise _external_tools_error(
            "EXTERNAL_TOOL_CAPABILITY_UNDECLARED",
            "execution requests a tool absent from its action edge",
            details={"capability_id": capability_id},
        )
    if len(controller_project_bindings) != 2:
        raise _external_tools_error(
            "CODEBASE_MEMORY_PROJECT_BINDINGS_INVALID",
            "execution grant requires baseline and current bindings",
        )
    declaration_digest = external_tool_declaration_set_sha256(
        declarations
    )
    if role_profile is not None:
        if (
            not isinstance(role_profile, ExternalToolRoleProfile)
            or role_profile.declaration_set_sha256
            != declaration_digest
            or by_id[capability_id].sha256
            not in role_profile.capability_sha256s
        ):
            raise _external_tools_error(
                "EXTERNAL_TOOL_ROLE_PROFILE_FORBIDDEN",
                "role profile does not expose the selected capability",
            )
    return ExternalToolExecutionGrant(
        task_id=task_id,
        workflow_bundle_sha256=workflow_bundle_sha256,
        node_instance_id=node_instance_id,
        action_id=action_id,
        execution_id=execution_id,
        effect_id=effect_id,
        attempt=attempt,
        declaration_set_sha256=declaration_digest,
        edge_capability_ids=tuple(
            item.capability_id for item in exposed
        ),
        capability=by_id[capability_id],
        assignment=assignment,
        request=request,
        baseline_binding=controller_project_bindings[0],
        current_binding=controller_project_bindings[1],
        role_profile_sha256=(
            None if role_profile is None else role_profile.sha256
        ),
    )


@_external_tools_dataclass(frozen=True)
class ExternalConclusion:
    conclusion_id: str
    claim: str
    material: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conclusion_id",
            _external_tools_require_stable_id(
                self.conclusion_id, "conclusion_id"
            ),
        )
        object.__setattr__(
            self,
            "claim",
            _external_tools_require_string(
                self.claim, "claim", maximum_bytes=4096
            ),
        )
        if not isinstance(self.material, bool):
            raise _external_tools_error(
                "EXTERNAL_CONCLUSION_MATERIAL_INVALID",
                "material must be a boolean",
                field="material",
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_CONCLUSION_SCHEMA,
            "conclusion_id": self.conclusion_id,
            "claim": self.claim,
            "material": self.material,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            EXTERNAL_CONCLUSION_SCHEMA, self.as_dict()
        )


@_external_tools_dataclass(frozen=True)
class ExternalSourceCandidate:
    binding: CodebaseMemoryBinding
    scope: str
    locator: str
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CodebaseMemoryBinding):
            raise _external_tools_error(
                "EXTERNAL_SOURCE_BINDING_INVALID",
                "source candidate binding must be validated",
                field="binding",
            )
        object.__setattr__(
            self,
            "scope",
            _external_tools_require_stable_id(self.scope, "scope"),
        )
        object.__setattr__(
            self,
            "locator",
            _external_tools_require_string(
                self.locator, "locator", maximum_bytes=2048
            ),
        )
        object.__setattr__(
            self,
            "source_sha256",
            _external_tools_require_digest(
                self.source_sha256, "source_sha256"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_SOURCE_CANDIDATE_SCHEMA,
            "binding": self.binding.as_dict(),
            "scope": self.scope,
            "locator": self.locator,
            "source_sha256": self.source_sha256,
        }


@_external_tools_dataclass(frozen=True)
class BoundSourceConfirmation:
    binding: CodebaseMemoryBinding
    conclusion_sha256: str
    scope: str
    locator: str
    source_sha256: str
    confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CodebaseMemoryBinding):
            raise _external_tools_error(
                "SOURCE_CONFIRMATION_BINDING_INVALID",
                "source confirmation binding must be validated",
                field="binding",
            )
        object.__setattr__(
            self,
            "conclusion_sha256",
            _external_tools_require_digest(
                self.conclusion_sha256, "conclusion_sha256"
            ),
        )
        object.__setattr__(
            self,
            "scope",
            _external_tools_require_stable_id(self.scope, "scope"),
        )
        object.__setattr__(
            self,
            "locator",
            _external_tools_require_string(
                self.locator, "locator", maximum_bytes=2048
            ),
        )
        object.__setattr__(
            self,
            "source_sha256",
            _external_tools_require_digest(
                self.source_sha256, "source_sha256"
            ),
        )
        if not isinstance(self.confirmed, bool):
            raise _external_tools_error(
                "SOURCE_CONFIRMATION_DECISION_INVALID",
                "source confirmation decision must be boolean",
                field="confirmed",
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BOUND_SOURCE_CONFIRMATION_SCHEMA,
            "binding": self.binding.as_dict(),
            "conclusion_sha256": self.conclusion_sha256,
            "scope": self.scope,
            "locator": self.locator,
            "source_sha256": self.source_sha256,
            "confirmed": self.confirmed,
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            BOUND_SOURCE_CONFIRMATION_SCHEMA, self.as_dict()
        )


@_external_tools_dataclass(frozen=True)
class CodebaseMemoryResult:
    assignment_sha256: str
    request_sha256: str
    binding: CodebaseMemoryBinding
    controller_revision: int
    result_schema: str
    covered_scopes: tuple[str, ...]
    source_candidates: tuple[ExternalSourceCandidate, ...]
    conclusions: tuple[ExternalConclusion, ...]

    def __post_init__(self) -> None:
        for field in ("assignment_sha256", "request_sha256"):
            object.__setattr__(
                self,
                field,
                _external_tools_require_digest(getattr(self, field), field),
            )
        if not isinstance(self.binding, CodebaseMemoryBinding):
            raise _external_tools_error(
                "CODEBASE_MEMORY_BINDING_INVALID",
                "result binding must be validated",
                field="binding",
            )
        object.__setattr__(
            self,
            "controller_revision",
            _external_tools_require_revision(
                self.controller_revision, "controller_revision"
            ),
        )
        object.__setattr__(
            self,
            "result_schema",
            _external_tools_require_stable_id(
                self.result_schema, "result_schema"
            ),
        )
        object.__setattr__(
            self,
            "covered_scopes",
            _external_tools_unique_sorted_ids(
                self.covered_scopes, "covered_scopes"
            ),
        )
        candidates = tuple(self.source_candidates)
        if any(
            not isinstance(item, ExternalSourceCandidate)
            for item in candidates
        ):
            raise _external_tools_error(
                "EXTERNAL_SOURCE_CANDIDATE_INVALID",
                "result source candidates must be validated contracts",
                field="source_candidates",
            )
        candidate_keys = tuple(
            (item.scope, item.locator, item.source_sha256)
            for item in candidates
        )
        if (
            len(set(candidate_keys)) != len(candidate_keys)
            or candidate_keys != tuple(sorted(candidate_keys))
        ):
            raise _external_tools_error(
                "EXTERNAL_SOURCE_CANDIDATES_INVALID",
                "source candidates must be unique and canonically sorted",
                field="source_candidates",
            )
        object.__setattr__(self, "source_candidates", candidates)
        conclusions = tuple(self.conclusions)
        if any(
            not isinstance(item, ExternalConclusion)
            for item in conclusions
        ):
            raise _external_tools_error(
                "EXTERNAL_CONCLUSION_INVALID",
                "result conclusions must be validated contracts",
                field="conclusions",
            )
        conclusion_ids = tuple(
            item.conclusion_id for item in conclusions
        )
        if (
            len(set(conclusion_ids)) != len(conclusion_ids)
            or conclusion_ids != tuple(sorted(conclusion_ids))
        ):
            raise _external_tools_error(
                "EXTERNAL_CONCLUSIONS_INVALID",
                "conclusions must be unique and canonically sorted",
                field="conclusions",
            )
        object.__setattr__(self, "conclusions", conclusions)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": CODEBASE_MEMORY_RESULT_SCHEMA,
            "assignment_sha256": self.assignment_sha256,
            "request_sha256": self.request_sha256,
            "binding": self.binding.as_dict(),
            "controller_revision": self.controller_revision,
            "result_schema": self.result_schema,
            "covered_scopes": list(self.covered_scopes),
            "source_candidates": [
                item.as_dict() for item in self.source_candidates
            ],
            "conclusions": [
                item.as_dict() for item in self.conclusions
            ],
        }

    @property
    def sha256(self) -> str:
        return external_tool_content_sha256(
            CODEBASE_MEMORY_RESULT_SCHEMA, self.identity_payload()
        )

    def as_dict(self) -> dict[str, object]:
        result = self.identity_payload()
        result["sha256"] = self.sha256
        return result


def parse_codebase_memory_assignment(
    value: object,
) -> CodebaseMemoryAssignment:
    mapping = _external_tools_require_exact_keys(
        value,
        {
            "schema",
            "capability_sha256",
            "binding",
            "controller_revision",
            "scopes",
            "result_schema",
            "sha256",
        },
        field="assignment",
    )
    if mapping["schema"] != CODEBASE_MEMORY_ASSIGNMENT_SCHEMA:
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCHEMA_INVALID",
            "codebase-memory assignment schema is not supported",
            field="assignment/schema",
        )
    if not isinstance(mapping["scopes"], (list, tuple)):
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPES_INVALID",
            "assignment scopes must be an array",
            field="assignment/scopes",
        )
    result = CodebaseMemoryAssignment(
        capability_sha256=mapping["capability_sha256"],  # type: ignore[arg-type]
        binding=CodebaseMemoryBinding.from_dict(mapping["binding"]),
        controller_revision=mapping["controller_revision"],  # type: ignore[arg-type]
        scopes=tuple(mapping["scopes"]),  # type: ignore[arg-type]
        result_schema=mapping["result_schema"],  # type: ignore[arg-type]
    )
    if _external_tools_require_digest(
        mapping["sha256"], "assignment/sha256"
    ) != result.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_IDENTITY_MISMATCH",
            "assignment identity does not match its content",
            field="assignment/sha256",
        )
    return result


def parse_codebase_memory_request(
    value: object,
) -> CodebaseMemoryRequest:
    mapping = _external_tools_require_exact_keys(
        value,
        {
            "schema",
            "assignment_sha256",
            "binding",
            "controller_revision",
            "scopes",
            "query",
            "result_schema",
            "sha256",
        },
        field="request",
    )
    if mapping["schema"] != CODEBASE_MEMORY_REQUEST_SCHEMA:
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCHEMA_INVALID",
            "codebase-memory request schema is not supported",
            field="request/schema",
        )
    if not isinstance(mapping["scopes"], (list, tuple)):
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPES_INVALID",
            "request scopes must be an array",
            field="request/scopes",
        )
    result = CodebaseMemoryRequest(
        assignment_sha256=mapping["assignment_sha256"],  # type: ignore[arg-type]
        binding=CodebaseMemoryBinding.from_dict(mapping["binding"]),
        controller_revision=mapping["controller_revision"],  # type: ignore[arg-type]
        scopes=tuple(mapping["scopes"]),  # type: ignore[arg-type]
        query=mapping["query"],  # type: ignore[arg-type]
        result_schema=mapping["result_schema"],  # type: ignore[arg-type]
    )
    if _external_tools_require_digest(
        mapping["sha256"], "request/sha256"
    ) != result.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_IDENTITY_MISMATCH",
            "request identity does not match its content",
            field="request/sha256",
        )
    return result


def parse_external_conclusion(value: object) -> ExternalConclusion:
    mapping = _external_tools_require_exact_keys(
        value,
        {"schema", "conclusion_id", "claim", "material"},
        field="conclusion",
    )
    if mapping["schema"] != EXTERNAL_CONCLUSION_SCHEMA:
        raise _external_tools_error(
            "EXTERNAL_CONCLUSION_SCHEMA_INVALID",
            "external conclusion schema is not supported",
            field="conclusion/schema",
        )
    return ExternalConclusion(
        conclusion_id=mapping["conclusion_id"],  # type: ignore[arg-type]
        claim=mapping["claim"],  # type: ignore[arg-type]
        material=mapping["material"],  # type: ignore[arg-type]
    )


def parse_external_source_candidate(
    value: object,
) -> ExternalSourceCandidate:
    mapping = _external_tools_require_exact_keys(
        value,
        {
            "schema",
            "binding",
            "scope",
            "locator",
            "source_sha256",
        },
        field="source_candidate",
    )
    if mapping["schema"] != EXTERNAL_SOURCE_CANDIDATE_SCHEMA:
        raise _external_tools_error(
            "EXTERNAL_SOURCE_SCHEMA_INVALID",
            "external source candidate schema is not supported",
            field="source_candidate/schema",
        )
    return ExternalSourceCandidate(
        binding=CodebaseMemoryBinding.from_dict(mapping["binding"]),
        scope=mapping["scope"],  # type: ignore[arg-type]
        locator=mapping["locator"],  # type: ignore[arg-type]
        source_sha256=mapping["source_sha256"],  # type: ignore[arg-type]
    )


def parse_bound_source_confirmation(
    value: object,
) -> BoundSourceConfirmation:
    mapping = _external_tools_require_exact_keys(
        value,
        {
            "schema",
            "binding",
            "conclusion_sha256",
            "scope",
            "locator",
            "source_sha256",
            "confirmed",
        },
        field="source_confirmation",
    )
    if mapping["schema"] != BOUND_SOURCE_CONFIRMATION_SCHEMA:
        raise _external_tools_error(
            "SOURCE_CONFIRMATION_SCHEMA_INVALID",
            "bound source confirmation schema is not supported",
            field="source_confirmation/schema",
        )
    return BoundSourceConfirmation(
        binding=CodebaseMemoryBinding.from_dict(mapping["binding"]),
        conclusion_sha256=mapping["conclusion_sha256"],  # type: ignore[arg-type]
        scope=mapping["scope"],  # type: ignore[arg-type]
        locator=mapping["locator"],  # type: ignore[arg-type]
        source_sha256=mapping["source_sha256"],  # type: ignore[arg-type]
        confirmed=mapping["confirmed"],  # type: ignore[arg-type]
    )


def parse_codebase_memory_result(
    value: object,
) -> CodebaseMemoryResult:
    mapping = _external_tools_require_exact_keys(
        value,
        {
            "schema",
            "assignment_sha256",
            "request_sha256",
            "binding",
            "controller_revision",
            "result_schema",
            "covered_scopes",
            "source_candidates",
            "conclusions",
            "sha256",
        },
        field="result",
    )
    if mapping["schema"] != CODEBASE_MEMORY_RESULT_SCHEMA:
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCHEMA_INVALID",
            "codebase-memory result envelope schema is not supported",
            field="result/schema",
        )
    for field in ("covered_scopes", "source_candidates", "conclusions"):
        if not isinstance(mapping[field], (list, tuple)):
            raise _external_tools_error(
                "CODEBASE_MEMORY_RESULT_FIELD_INVALID",
                "codebase-memory result array field is invalid",
                field=f"result/{field}",
            )
    result = CodebaseMemoryResult(
        assignment_sha256=mapping["assignment_sha256"],  # type: ignore[arg-type]
        request_sha256=mapping["request_sha256"],  # type: ignore[arg-type]
        binding=CodebaseMemoryBinding.from_dict(mapping["binding"]),
        controller_revision=mapping["controller_revision"],  # type: ignore[arg-type]
        result_schema=mapping["result_schema"],  # type: ignore[arg-type]
        covered_scopes=tuple(mapping["covered_scopes"]),  # type: ignore[arg-type]
        source_candidates=tuple(
            parse_external_source_candidate(item)
            for item in mapping["source_candidates"]  # type: ignore[union-attr]
        ),
        conclusions=tuple(
            parse_external_conclusion(item)
            for item in mapping["conclusions"]  # type: ignore[union-attr]
        ),
    )
    if _external_tools_require_digest(
        mapping["sha256"], "result/sha256"
    ) != result.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_IDENTITY_MISMATCH",
            "result identity does not match its content",
            field="result/sha256",
        )
    return result


@_external_tools_dataclass(frozen=True)
class ExternalEvidenceDecision:
    accepted_candidate: bool
    complete_evidence: bool
    result_sha256: str
    reasons: tuple[str, ...]
    confirmation_sha256s: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_EVIDENCE_DECISION_SCHEMA,
            "accepted_candidate": self.accepted_candidate,
            "complete_evidence": self.complete_evidence,
            "result_sha256": self.result_sha256,
            "reasons": list(self.reasons),
            "confirmation_sha256s": list(
                self.confirmation_sha256s
            ),
        }


def validate_codebase_memory_result(
    *,
    capability: ExternalToolCapability,
    assignment: CodebaseMemoryAssignment,
    request: CodebaseMemoryRequest,
    result: CodebaseMemoryResult,
    current_binding: CodebaseMemoryBinding,
    controller_project_bindings: _ExternalToolsSequence[
        CodebaseMemoryBinding
    ],
    current_controller_revision: int,
    source_confirmations: _ExternalToolsSequence[
        BoundSourceConfirmation
    ] = (),
) -> ExternalEvidenceDecision:
    """Validate a candidate and decide whether it is complete evidence.

    Structural, identity, scope-expansion, and currentness failures raise and
    therefore occur before candidate acceptance.  Missing coverage or missing
    bound-source confirmation yields an accepted discovery candidate that is
    explicitly incomplete.
    """

    if (
        not isinstance(capability, ExternalToolCapability)
        or not isinstance(assignment, CodebaseMemoryAssignment)
        or not isinstance(request, CodebaseMemoryRequest)
        or not isinstance(result, CodebaseMemoryResult)
        or not isinstance(current_binding, CodebaseMemoryBinding)
    ):
        raise _external_tools_error(
            "CODEBASE_MEMORY_CONTRACT_INVALID",
            "evidence validation requires validated contracts",
        )
    expected_revision = _external_tools_require_revision(
        current_controller_revision, "current_controller_revision"
    )
    if len(controller_project_bindings) != 2:
        raise _external_tools_error(
            "CODEBASE_MEMORY_PROJECT_BINDINGS_INVALID",
            "controller must supply one baseline and one current binding",
        )
    baseline_binding, current_workspace_binding = (
        validate_codebase_memory_project_pair(
            controller_project_bindings[0],
            controller_project_bindings[1],
        )
    )
    selected_binding = (
        baseline_binding
        if current_binding.phase == CODEBASE_MEMORY_BASELINE_PHASE
        else current_workspace_binding
    )
    if selected_binding.sha256 != current_binding.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_CONTROLLER_BINDING_MISMATCH",
            "selected binding is not the controller-recorded phase binding",
        )
    if (
        capability.tool_id != CODEBASE_MEMORY_TOOL_ID
        or capability.operations != ("external-read",)
    ):
        raise _external_tools_error(
            "CODEBASE_MEMORY_CAPABILITY_INVALID",
            "evidence uses an invalid codebase-memory capability",
        )
    if assignment.capability_sha256 != capability.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_CAPABILITY_MISMATCH",
            "assignment does not bind the selected capability",
        )
    if request.assignment_sha256 != assignment.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_ASSIGNMENT_MISMATCH",
            "request does not bind the selected assignment",
        )
    if result.assignment_sha256 != assignment.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_ASSIGNMENT_MISMATCH",
            "result does not bind the selected assignment",
        )
    if result.request_sha256 != request.sha256:
        raise _external_tools_error(
            "CODEBASE_MEMORY_REQUEST_MISMATCH",
            "result does not bind the exact request",
        )
    binding_sha256s = {
        assignment.binding.sha256,
        request.binding.sha256,
        result.binding.sha256,
        current_binding.sha256,
    }
    if len(binding_sha256s) != 1:
        raise _external_tools_error(
            "CODEBASE_MEMORY_BINDING_MISMATCH",
            "assignment, request, result, and current source binding differ",
        )
    revisions = {
        assignment.controller_revision,
        request.controller_revision,
        result.controller_revision,
        expected_revision,
    }
    if len(revisions) != 1:
        raise _external_tools_error(
            "CODEBASE_MEMORY_RESULT_STALE",
            "codebase-memory result is not current for this revision",
            details={
                "current_controller_revision": expected_revision,
                "result_controller_revision": result.controller_revision,
            },
        )
    if (
        assignment.result_schema != capability.result_schema
        or request.result_schema != assignment.result_schema
        or result.result_schema != request.result_schema
    ):
        raise _external_tools_error(
            "CODEBASE_MEMORY_RESULT_SCHEMA_MISMATCH",
            "codebase-memory result schema binding differs",
        )
    if any(scope not in assignment.scopes for scope in request.scopes):
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPE_UNASSIGNED",
            "request contains scope outside its assignment",
        )
    if any(scope not in request.scopes for scope in result.covered_scopes):
        raise _external_tools_error(
            "CODEBASE_MEMORY_SCOPE_EXPANDED",
            "result claims coverage outside the exact request",
        )
    for candidate in result.source_candidates:
        if candidate.binding.sha256 != current_binding.sha256:
            raise _external_tools_error(
                "CODEBASE_MEMORY_SOURCE_MISMATCH",
                "source candidate does not bind the current source snapshot",
            )
        if candidate.scope not in result.covered_scopes:
            raise _external_tools_error(
                "CODEBASE_MEMORY_SOURCE_SCOPE_INVALID",
                "source candidate is outside claimed result coverage",
            )

    missing_coverage = tuple(
        scope
        for scope in request.scopes
        if scope not in result.covered_scopes
        or not any(
            candidate.scope == scope
            for candidate in result.source_candidates
        )
    )
    confirmations = tuple(source_confirmations)
    if any(
        not isinstance(item, BoundSourceConfirmation)
        for item in confirmations
    ):
        raise _external_tools_error(
            "SOURCE_CONFIRMATION_INVALID",
            "source confirmations must be validated contracts",
        )
    confirmation_keys = tuple(item.sha256 for item in confirmations)
    if (
        len(set(confirmation_keys)) != len(confirmation_keys)
        or confirmation_keys != tuple(sorted(confirmation_keys))
    ):
        raise _external_tools_error(
            "SOURCE_CONFIRMATIONS_INVALID",
            "source confirmations must be unique and sorted by identity",
        )
    for confirmation in confirmations:
        if confirmation.binding.sha256 != current_binding.sha256:
            raise _external_tools_error(
                "SOURCE_CONFIRMATION_BINDING_MISMATCH",
                "source confirmation is not bound to the current snapshot",
            )
        if confirmation.scope not in request.scopes:
            raise _external_tools_error(
                "SOURCE_CONFIRMATION_SCOPE_INVALID",
                "source confirmation is outside the requested scope",
            )

    unconfirmed_material = tuple(
        conclusion.conclusion_id
        for conclusion in result.conclusions
        if conclusion.material
        and not any(
            confirmation.confirmed
            and confirmation.conclusion_sha256
            == conclusion.sha256
            for confirmation in confirmations
        )
    )
    reasons: list[str] = []
    if missing_coverage:
        reasons.append("insufficient-source-coverage")
    if unconfirmed_material:
        reasons.append("material-conclusion-unconfirmed")
    return ExternalEvidenceDecision(
        accepted_candidate=True,
        complete_evidence=not reasons,
        result_sha256=result.sha256,
        reasons=tuple(reasons),
        confirmation_sha256s=confirmation_keys,
    )
