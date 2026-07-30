# Loaded by scripts/dev_flow.py after the compact agent protocol once runtime
# wiring is enabled.  This fragment is deliberately pure and standard-library
# only: it prepares typed adapter requests, parses supplied executor output,
# and decides whether an already-recorded runtime attempt is safe to resume.
# It never starts a process, imports an optional SDK, or persists workflow
# state.
from __future__ import annotations

import hashlib as _runtime_adapter_hashlib
import json as _runtime_adapter_json
import math as _runtime_adapter_math
import ntpath as _runtime_adapter_ntpath
import posixpath as _runtime_adapter_posixpath
import re as _runtime_adapter_re
import struct as _runtime_adapter_struct
import threading as _runtime_adapter_threading
import time as _runtime_adapter_time
import unicodedata as _runtime_adapter_unicodedata
from dataclasses import dataclass as _runtime_adapter_dataclass
from types import MappingProxyType as _RuntimeAdapterMappingProxyType
from typing import (
    Callable as _RuntimeAdapterCallable,
    Iterable as _RuntimeAdapterIterable,
    Mapping as _RuntimeAdapterMapping,
    Sequence as _RuntimeAdapterSequence,
)


RUNTIME_ADAPTER_CONTRACT_SCHEMA = "dev-flow-runtime-adapter-contract/v1"
RUNTIME_EXECUTION_REQUEST_SCHEMA = "dev-flow-executor-request/v1"
RUNTIME_ATTEMPT_RECORD_SCHEMA = "dev-flow-runtime-attempt/v1"
RUNTIME_HANDLE_SCHEMA = "dev-flow-runtime-handle/v1"
RUNTIME_HANDLE_RECORD_SCHEMA = "dev-flow-runtime-handle-record/v1"
RUNTIME_REPLACEMENT_PROOF_SCHEMA = "dev-flow-runtime-replacement-proof/v1"
RUNTIME_DISPATCH_DECISION_SCHEMA = "dev-flow-runtime-dispatch-decision/v1"
V4_RUNTIME_SETTLEMENT_EVIDENCE_SCHEMA = (
    "dev-flow-v4-runtime-settlement-evidence/v1"
)
V4_RUNTIME_ABANDONED_AUTHORITY_SCHEMA = (
    "dev-flow-v4-runtime-abandoned-authority/v1"
)
CODEX_EXEC_INVOCATION_SCHEMA = "dev-flow-codex-exec-invocation/v1"
CODEX_EXEC_RESULT_SCHEMA = "dev-flow-codex-exec-result/v1"
CODEX_EXEC_RESULT_CANDIDATE_SCHEMA = (
    "dev-flow-codex-exec-result-candidate/v1"
)
CODEX_EXEC_EVENT_PROTOCOL = "codex-exec-jsonl/v1"
CODEX_EXEC_PROMPT_BUDGET = 16384
CODEX_EXEC_JSONL_BUDGET = 4 * 1024 * 1024
CODEX_EXEC_EVENT_BUDGET = 10000
CODEX_EXEC_LINE_BUDGET = 1024 * 1024

_runtime_adapter_digest_re = _runtime_adapter_re.compile(r"^[0-9a-f]{64}$")
_runtime_adapter_stable_id_re = _runtime_adapter_re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$"
)
_runtime_adapter_executor_id_re = _runtime_adapter_re.compile(
    r"^executor\.[a-z0-9][a-z0-9-]{0,62}/v[1-9][0-9]*$"
)
_runtime_adapter_contract_version_re = _runtime_adapter_re.compile(
    r"^[A-Za-z][A-Za-z0-9._/-]{0,127}$"
)
_runtime_adapter_model_policies = frozenset(
    {"economy", "balanced", "critical"}
)
_runtime_adapter_sandbox_modes = frozenset(
    {"read-only", "workspace-write"}
)
_runtime_adapter_attempt_phases = frozenset(
    {"issued", "running", "unavailable", "quiesced"}
)
_runtime_adapter_handle_states = frozenset(
    {"available", "unavailable", "quiesced"}
)
_runtime_adapter_replacement_reasons = frozenset(
    {"operator-authorized", "recovery", "retry"}
)
_runtime_adapter_v4_settlements = frozenset({"EXITED", "QUIESCED"})
_V4_RUNTIME_RESULT_EVENT_DOMAIN = (
    b"dev-flow-v4-runtime-result-event/v1\x00"
)
_V4_RUNTIME_SETTLEMENT_EVIDENCE_DOMAIN = (
    b"dev-flow-v4-runtime-settlement-evidence/v1\x00"
)
_V4_RUNTIME_ABANDONED_AUTHORITY_DOMAIN = (
    b"dev-flow-v4-runtime-abandoned-authority/v1\x00"
)
_V4_RUNTIME_EVIDENCE_MAX_TTL_SECONDS = 300
_runtime_adapter_candidate_required_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "node_instance_id",
        "attempt",
        "input_sha256",
        "outcome",
        "summary",
        "artifact_refs",
        "evidence_refs",
        "changed_files",
        "blockers",
        "plan_drift",
    }
)


class RuntimeAdapterError(ValueError):
    """Stable fail-closed diagnostic for pure runtime-adapter contracts."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _RuntimeAdapterMapping[str, object] | None = None,
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


def _runtime_adapter_error(
    code: str,
    message: str,
    *,
    field: str | None = None,
    details: _RuntimeAdapterMapping[str, object] | None = None,
) -> RuntimeAdapterError:
    payload = dict(details or {})
    if field is not None:
        payload.setdefault("field", field)
    return RuntimeAdapterError(code, message, details=payload)


def _runtime_adapter_freeze(value: object, path: str = "$") -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise _runtime_adapter_error(
            "RUNTIME_VALUE_INVALID",
            "runtime adapter values must not use floating-point numbers",
            field=path,
        )
    if isinstance(value, _RuntimeAdapterMapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _runtime_adapter_error(
                    "RUNTIME_VALUE_INVALID",
                    "runtime adapter object keys must be strings",
                    field=path,
                )
            frozen[key] = _runtime_adapter_freeze(
                item, f"{path}/{key}"
            )
        return _RuntimeAdapterMappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _runtime_adapter_freeze(item, f"{path}/{index}")
            for index, item in enumerate(value)
        )
    raise _runtime_adapter_error(
        "RUNTIME_VALUE_INVALID",
        "runtime adapter values must use canonical JSON types",
        field=path,
        details={"type": type(value).__name__},
    )


def _runtime_adapter_thaw(value: object) -> object:
    if isinstance(value, _RuntimeAdapterMapping):
        return {
            str(key): _runtime_adapter_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_runtime_adapter_thaw(item) for item in value]
    return value


def canonical_runtime_adapter_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON bytes for an adapter contract value."""

    try:
        return _runtime_adapter_json.dumps(
            _runtime_adapter_thaw(_runtime_adapter_freeze(value)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, RuntimeAdapterError):
            raise
        raise _runtime_adapter_error(
            "RUNTIME_VALUE_INVALID",
            "runtime adapter value cannot be canonically encoded",
        ) from exc


def _runtime_adapter_sha256(value: object) -> str:
    return _runtime_adapter_hashlib.sha256(
        canonical_runtime_adapter_bytes(value)
    ).hexdigest()


def _runtime_adapter_domain_sha256(
    domain: bytes, value: object
) -> str:
    if not isinstance(domain, bytes) or not domain.endswith(b"\x00"):
        raise _runtime_adapter_error(
            "RUNTIME_DOMAIN_INVALID",
            "runtime digest domain must be NUL-terminated bytes",
        )
    encoded = canonical_runtime_adapter_bytes(value)
    return _runtime_adapter_hashlib.sha256(
        domain
        + _runtime_adapter_struct.pack(">Q", len(encoded))
        + encoded
    ).hexdigest()


def v4_runtime_result_event_sha256(event: object) -> str:
    """Digest one exact authoritative V4 runtime result event."""

    return _runtime_adapter_domain_sha256(
        _V4_RUNTIME_RESULT_EVENT_DOMAIN, event
    )


def _runtime_adapter_require_string(
    value: object,
    field: str,
    *,
    stable_id: bool = False,
    maximum_bytes: int | None = None,
) -> str:
    if not isinstance(value, str) or not value:
        raise _runtime_adapter_error(
            "RUNTIME_FIELD_REQUIRED",
            "runtime adapter field must be a non-empty string",
            field=field,
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise _runtime_adapter_error(
            "RUNTIME_FIELD_INVALID",
            "runtime adapter strings must be valid UTF-8",
            field=field,
        ) from exc
    if maximum_bytes is not None and len(encoded) > maximum_bytes:
        raise _runtime_adapter_error(
            "RUNTIME_FIELD_TOO_LARGE",
            "runtime adapter string exceeds its UTF-8 byte budget",
            field=field,
            details={"size": len(encoded), "budget": maximum_bytes},
        )
    if stable_id and not _runtime_adapter_stable_id_re.fullmatch(value):
        raise _runtime_adapter_error(
            "RUNTIME_IDENTITY_INVALID",
            "runtime adapter identity is not portable",
            field=field,
        )
    return value


def _runtime_adapter_require_digest(
    value: object, field: str
) -> str:
    if (
        not isinstance(value, str)
        or not _runtime_adapter_digest_re.fullmatch(value)
    ):
        raise _runtime_adapter_error(
            "RUNTIME_DIGEST_INVALID",
            "runtime adapter digest must be lowercase SHA-256",
            field=field,
        )
    return value


def _runtime_adapter_require_int(
    value: object, field: str, *, minimum: int = 0
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
    ):
        raise _runtime_adapter_error(
            "RUNTIME_INTEGER_INVALID",
            "runtime adapter integer is outside its accepted range",
            field=field,
            details={"minimum": minimum},
        )
    return value


def _runtime_adapter_ordered_ids(
    values: _RuntimeAdapterIterable[object],
    field: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, _RuntimeAdapterMapping)):
        raise _runtime_adapter_error(
            "RUNTIME_FIELD_INVALID",
            "runtime adapter identity collection must be an array",
            field=field,
        )
    normalized = tuple(
        _runtime_adapter_require_string(
            item, f"{field}/{index}", stable_id=True
        )
        for index, item in enumerate(values)
    )
    if len(normalized) != len(set(normalized)):
        raise _runtime_adapter_error(
            "RUNTIME_IDENTITY_DUPLICATE",
            "runtime adapter identities must be unique",
            field=field,
        )
    return tuple(sorted(normalized, key=lambda item: item.encode("utf-8")))


def _runtime_adapter_portable_relative_paths(
    values: _RuntimeAdapterIterable[object],
    field: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, _RuntimeAdapterMapping)):
        raise _runtime_adapter_error(
            "RUNTIME_FIELD_INVALID",
            "approved paths must be an array",
            field=field,
        )
    normalized: list[str] = []
    portable_keys: set[str] = set()
    for index, item in enumerate(values):
        text = _runtime_adapter_require_string(
            item, f"{field}/{index}", maximum_bytes=1024
        )
        if "\x00" in text or "\r" in text or "\n" in text:
            raise _runtime_adapter_error(
                "RUNTIME_PATH_INVALID",
                "approved paths cannot contain control separators",
                field=f"{field}/{index}",
            )
        text = _runtime_adapter_unicodedata.normalize(
            "NFC", text.replace("\\", "/")
        )
        if (
            text.startswith("/")
            or _runtime_adapter_ntpath.isabs(text)
            or _runtime_adapter_ntpath.splitdrive(text)[0]
        ):
            raise _runtime_adapter_error(
                "RUNTIME_PATH_INVALID",
                "approved paths must be repository-relative",
                field=f"{field}/{index}",
            )
        parts = tuple(part for part in text.split("/") if part)
        if (
            not parts
            or any(part in {".", ".."} for part in parts)
            or _runtime_adapter_posixpath.normpath(text)
            != "/".join(parts)
        ):
            raise _runtime_adapter_error(
                "RUNTIME_PATH_INVALID",
                "approved paths must be normalized without dot segments",
                field=f"{field}/{index}",
            )
        value = "/".join(parts)
        portable = value.casefold()
        if portable in portable_keys:
            raise _runtime_adapter_error(
                "RUNTIME_PATH_COLLISION",
                "approved paths collide under portable comparison",
                field=field,
                details={"path": value},
            )
        portable_keys.add(portable)
        normalized.append(value)
    if len(normalized) != len(set(normalized)):
        raise _runtime_adapter_error(
            "RUNTIME_PATH_COLLISION",
            "approved paths must be unique",
            field=field,
        )
    return tuple(sorted(normalized, key=lambda item: item.encode("utf-8")))


def _runtime_adapter_absolute_path(
    value: object, field: str
) -> str:
    text = _runtime_adapter_require_string(
        value, field, maximum_bytes=4096
    )
    if "\x00" in text or "\r" in text or "\n" in text:
        raise _runtime_adapter_error(
            "RUNTIME_PATH_INVALID",
            "runtime paths cannot contain control separators",
            field=field,
        )
    text = _runtime_adapter_unicodedata.normalize(
        "NFC", text.replace("\\", "/")
    )
    is_absolute = (
        _runtime_adapter_posixpath.isabs(text)
        or _runtime_adapter_ntpath.isabs(text)
    )
    if not is_absolute:
        raise _runtime_adapter_error(
            "RUNTIME_PATH_INVALID",
            "runtime path must be absolute",
            field=field,
        )
    parts = text.split("/")
    if any(part in {".", ".."} for part in parts):
        raise _runtime_adapter_error(
            "RUNTIME_PATH_INVALID",
            "runtime path must not contain dot segments",
            field=field,
        )
    if text == "/" or _runtime_adapter_re.fullmatch(
        r"[A-Za-z]:/", text
    ):
        return text
    return text.rstrip("/")


@_runtime_adapter_dataclass(frozen=True)
class NodeResultAdapterProfile:
    """Map a package-owned structured result onto issued-attempt bindings."""

    profile_id: str
    result_schema: str
    authoritative: bool
    required_fields: tuple[str, ...]
    task_id_field: str
    workflow_bundle_field: str
    node_instance_field: str
    repository_field: str | None
    attempt_field: str
    input_sha256_field: str
    forbidden_model_fields: tuple[str, ...] = (
        "runtime_handle",
        "usage",
    )

    def __post_init__(self) -> None:
        _runtime_adapter_require_string(
            self.profile_id, "profile_id", stable_id=True
        )
        _runtime_adapter_require_string(
            self.result_schema, "result_schema", stable_id=True
        )
        required = _runtime_adapter_ordered_ids(
            self.required_fields, "required_fields"
        )
        forbidden = _runtime_adapter_ordered_ids(
            self.forbidden_model_fields, "forbidden_model_fields"
        )
        binding_fields = (
            self.task_id_field,
            self.workflow_bundle_field,
            self.node_instance_field,
            self.attempt_field,
            self.input_sha256_field,
        )
        for field in binding_fields:
            _runtime_adapter_require_string(
                field, "binding_field", stable_id=True
            )
            if field not in required:
                raise _runtime_adapter_error(
                    "RUNTIME_NODE_RESULT_PROFILE_INVALID",
                    "structured-result binding field must be required",
                    details={"field": field},
                )
        if self.repository_field is not None:
            _runtime_adapter_require_string(
                self.repository_field,
                "repository_field",
                stable_id=True,
            )
        object.__setattr__(self, "required_fields", required)
        object.__setattr__(
            self, "forbidden_model_fields", forbidden
        )


CODEX_EXEC_CANDIDATE_PROFILE = NodeResultAdapterProfile(
    profile_id="codex-exec-result-candidate/v1",
    result_schema=CODEX_EXEC_RESULT_CANDIDATE_SCHEMA,
    authoritative=False,
    required_fields=tuple(_runtime_adapter_candidate_required_fields),
    task_id_field="task_id",
    workflow_bundle_field="workflow_bundle_sha256",
    node_instance_field="node_instance_id",
    repository_field="repository_id",
    attempt_field="attempt",
    input_sha256_field="input_sha256",
)

# This profile does not validate the rich artifact itself.  Production callers
# must inject ``validate_orchestration_node_result`` from
# orchestration_results.py.  Keeping the binding map here lets the adapter
# check its exact issued request without importing or weakening that authority.
ORCHESTRATION_NODE_RESULT_PROFILE = NodeResultAdapterProfile(
    profile_id="orchestration-node-result/v1",
    result_schema="dev-flow-node-result/v1",
    authoritative=True,
    required_fields=(
        "attempt",
        "input_sha256",
        "node_instance_id",
        "repository_id",
        "task_id",
        "workflow_bundle_sha256",
    ),
    task_id_field="task_id",
    workflow_bundle_field="workflow_bundle_sha256",
    node_instance_field="node_instance_id",
    repository_field="repository_id",
    attempt_field="attempt",
    input_sha256_field="input_sha256",
)


@_runtime_adapter_dataclass(frozen=True)
class ExecutorAdapterContract:
    """Pure metadata for one sealed executor adapter contract."""

    identifier: str
    contract_version: str
    adapter_kind: str
    authority: tuple[str, ...]
    effect_classifications: tuple[str, ...]
    dispatch_protocol: str
    result_schema: str
    runtime_handle_kind: str | None
    supports_resume: bool
    optional_runtime: str | None
    requires_jsonl: bool
    requires_output_schema: bool
    requires_host_isolation: bool
    sandbox_by_effect: _RuntimeAdapterMapping[str, str]
    schema: str = RUNTIME_ADAPTER_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        if not _runtime_adapter_executor_id_re.fullmatch(self.identifier):
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "executor contract identifier is not versioned and portable",
                field="identifier",
            )
        if not _runtime_adapter_contract_version_re.fullmatch(
            self.contract_version
        ):
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "executor contract version is malformed",
                field="contract_version",
            )
        _runtime_adapter_require_string(
            self.adapter_kind, "adapter_kind", stable_id=True
        )
        _runtime_adapter_require_string(
            self.dispatch_protocol, "dispatch_protocol", stable_id=True
        )
        _runtime_adapter_require_string(
            self.result_schema, "result_schema", stable_id=True
        )
        authority = _runtime_adapter_ordered_ids(
            self.authority, "authority"
        )
        effects = _runtime_adapter_ordered_ids(
            self.effect_classifications, "effect_classifications"
        )
        if not effects:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "executor contract requires at least one effect classification",
                field="effect_classifications",
            )
        if self.runtime_handle_kind is not None:
            _runtime_adapter_require_string(
                self.runtime_handle_kind,
                "runtime_handle_kind",
                stable_id=True,
            )
        if self.supports_resume and self.runtime_handle_kind is None:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "resumable executor contracts require a runtime handle kind",
                field="supports_resume",
            )
        optional_runtime = self.optional_runtime
        if optional_runtime is not None:
            _runtime_adapter_require_string(
                optional_runtime, "optional_runtime", stable_id=True
            )
        if self.requires_output_schema and not self.requires_jsonl:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "structured streaming executors require JSONL with output schema",
                field="requires_output_schema",
            )
        sandbox = dict(self.sandbox_by_effect)
        unknown_sandbox_effects = sorted(
            set(sandbox) - set(effects),
            key=lambda item: str(item).encode("utf-8"),
        )
        if unknown_sandbox_effects:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "sandbox policy names an unsupported effect classification",
                field="sandbox_by_effect",
                details={"effects": unknown_sandbox_effects},
            )
        for effect, mode in sandbox.items():
            _runtime_adapter_require_string(
                effect, f"sandbox_by_effect/{effect}", stable_id=True
            )
            if mode not in _runtime_adapter_sandbox_modes:
                raise _runtime_adapter_error(
                    "RUNTIME_CONTRACT_INVALID",
                    "executor sandbox mode is unsupported",
                    field=f"sandbox_by_effect/{effect}",
                    details={"mode": mode},
                )
        if self.requires_jsonl and set(sandbox) != set(effects):
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_INVALID",
                "JSONL subprocess contracts require an explicit sandbox per effect",
                field="sandbox_by_effect",
            )
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "effect_classifications", effects)
        object.__setattr__(
            self,
            "sandbox_by_effect",
            _RuntimeAdapterMappingProxyType(
                {
                    key: sandbox[key]
                    for key in sorted(
                        sandbox, key=lambda item: item.encode("utf-8")
                    )
                }
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "identifier": self.identifier,
            "contract_version": self.contract_version,
            "adapter_kind": self.adapter_kind,
            "authority": list(self.authority),
            "effect_classifications": list(self.effect_classifications),
            "dispatch_protocol": self.dispatch_protocol,
            "result_schema": self.result_schema,
            "runtime_handle_kind": self.runtime_handle_kind,
            "supports_resume": self.supports_resume,
            "optional_runtime": self.optional_runtime,
            "requires_jsonl": self.requires_jsonl,
            "requires_output_schema": self.requires_output_schema,
            "requires_host_isolation": self.requires_host_isolation,
            "sandbox_by_effect": dict(self.sandbox_by_effect),
        }


class RuntimeAdapterContractRegistry:
    """Deterministic pre-start registry for package-owned adapter metadata."""

    def __init__(self) -> None:
        self._entries: dict[str, ExecutorAdapterContract] = {}
        self._sealed = False

    @property
    def sealed(self) -> bool:
        return self._sealed

    @property
    def entries(
        self,
    ) -> _RuntimeAdapterMapping[str, ExecutorAdapterContract]:
        return _RuntimeAdapterMappingProxyType(dict(self._entries))

    def register(
        self, contract: ExecutorAdapterContract
    ) -> ExecutorAdapterContract:
        if self._sealed:
            raise _runtime_adapter_error(
                "RUNTIME_REGISTRY_SEALED",
                "runtime adapter registry is already sealed",
            )
        if not isinstance(contract, ExecutorAdapterContract):
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_TYPE_INVALID",
                "runtime adapter registry accepts only executor contracts",
            )
        existing = self._entries.get(contract.identifier)
        if existing is not None:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_DUPLICATE",
                "executor adapter contract identifier is already registered",
                details={"identifier": contract.identifier},
            )
        self._entries[contract.identifier] = contract
        return contract

    def seal(self) -> None:
        if self._sealed:
            raise _runtime_adapter_error(
                "RUNTIME_REGISTRY_SEALED",
                "runtime adapter registry is already sealed",
            )
        self._entries = {
            key: self._entries[key]
            for key in sorted(
                self._entries, key=lambda item: item.encode("utf-8")
            )
        }
        self._sealed = True

    def resolve(self, identifier: str) -> ExecutorAdapterContract:
        if not self._sealed:
            raise _runtime_adapter_error(
                "RUNTIME_REGISTRY_UNSEALED",
                "runtime adapter registry must be sealed before resolution",
            )
        contract = self._entries.get(identifier)
        if contract is None:
            raise _runtime_adapter_error(
                "RUNTIME_CONTRACT_UNAVAILABLE",
                "requested executor adapter contract is unavailable",
                details={"identifier": identifier},
            )
        return contract


def _runtime_adapter_builtin_contracts(
) -> tuple[ExecutorAdapterContract, ...]:
    result_schema = "dev-flow-node-result/v1"
    contract_version = "dev-flow-executor/v1"
    return (
        ExecutorAdapterContract(
            identifier="executor.deterministic/v1",
            contract_version=contract_version,
            adapter_kind="deterministic",
            authority=("controller-compute",),
            effect_classifications=("controller", "none", "read-only"),
            dispatch_protocol="controller-call/v1",
            result_schema=result_schema,
            runtime_handle_kind=None,
            supports_resume=False,
            optional_runtime=None,
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=False,
            sandbox_by_effect={},
        ),
        ExecutorAdapterContract(
            identifier="executor.native-subagents/v1",
            contract_version=contract_version,
            adapter_kind="native-subagents",
            authority=("external-dispatch",),
            effect_classifications=("repository-write",),
            dispatch_protocol="native-subagent/v1",
            result_schema=result_schema,
            runtime_handle_kind="native-subagent",
            supports_resume=True,
            optional_runtime=None,
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=True,
            sandbox_by_effect={},
        ),
        ExecutorAdapterContract(
            identifier="executor.codex-exec/v1",
            contract_version=contract_version,
            adapter_kind="codex-exec",
            authority=("external-dispatch",),
            effect_classifications=(
                "external-read",
                "repository-write",
            ),
            dispatch_protocol=CODEX_EXEC_EVENT_PROTOCOL,
            result_schema=result_schema,
            runtime_handle_kind=None,
            supports_resume=False,
            optional_runtime="codex-cli",
            requires_jsonl=True,
            requires_output_schema=True,
            requires_host_isolation=False,
            sandbox_by_effect={
                "external-read": "read-only",
                "repository-write": "workspace-write",
            },
        ),
        ExecutorAdapterContract(
            identifier="executor.codex-thread/v1",
            contract_version=contract_version,
            adapter_kind="codex-thread",
            authority=("external-dispatch",),
            effect_classifications=("repository-write",),
            dispatch_protocol="codex-thread/v1",
            result_schema=result_schema,
            runtime_handle_kind="codex-thread",
            supports_resume=True,
            optional_runtime="codex-sdk",
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=False,
            sandbox_by_effect={},
        ),
        ExecutorAdapterContract(
            identifier="executor.external-tool/v1",
            contract_version=contract_version,
            adapter_kind="external-tool",
            authority=("external-dispatch",),
            effect_classifications=("external-read", "external-write"),
            dispatch_protocol="external-tool/v1",
            result_schema=result_schema,
            runtime_handle_kind="external-job",
            supports_resume=True,
            optional_runtime="host-provider",
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=False,
            sandbox_by_effect={},
        ),
        ExecutorAdapterContract(
            identifier="executor.barrier/v1",
            contract_version=contract_version,
            adapter_kind="barrier",
            authority=("controller-compute",),
            effect_classifications=("barrier",),
            dispatch_protocol="barrier/v1",
            result_schema=result_schema,
            runtime_handle_kind=None,
            supports_resume=False,
            optional_runtime=None,
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=False,
            sandbox_by_effect={},
        ),
        ExecutorAdapterContract(
            identifier="executor.human-gate/v1",
            contract_version=contract_version,
            adapter_kind="human-gate",
            authority=("approval-build",),
            effect_classifications=("approval",),
            dispatch_protocol="human-gate/v1",
            result_schema=result_schema,
            runtime_handle_kind=None,
            supports_resume=False,
            optional_runtime=None,
            requires_jsonl=False,
            requires_output_schema=False,
            requires_host_isolation=False,
            sandbox_by_effect={},
        ),
    )


def build_runtime_adapter_registry() -> RuntimeAdapterContractRegistry:
    """Build and seal the exact package-owned adapter contract set."""

    registry = RuntimeAdapterContractRegistry()
    for contract in _runtime_adapter_builtin_contracts():
        registry.register(contract)
    registry.seal()
    return registry


_RUNTIME_ADAPTER_REGISTRY = build_runtime_adapter_registry()


def runtime_adapter_contracts(
) -> _RuntimeAdapterMapping[str, ExecutorAdapterContract]:
    return _RUNTIME_ADAPTER_REGISTRY.entries


def _runtime_adapter_external_tool_binding(
    grant: object,
    *,
    executor_id: str,
    task_id: str,
    workflow_bundle_sha256: str,
    node_instance_id: str,
    repository_id: str | None,
    revision: int,
    attempt: int,
    effect_classification: str,
    capabilities: tuple[str, ...],
) -> dict[str, object]:
    if executor_id != "executor.external-tool/v1":
        raise _runtime_adapter_error(
            "RUNTIME_EXTERNAL_TOOL_GRANT_FORBIDDEN",
            "only the external-tool executor may receive a tool grant",
            field="external_tool_grant",
        )
    if capabilities:
        raise _runtime_adapter_error(
            "RUNTIME_EXTERNAL_TOOL_CAPABILITY_CHANNEL_FORBIDDEN",
            "worker mutation capabilities cannot expose external tools",
            field="capabilities",
        )
    if not isinstance(grant, ExternalToolExecutionGrant):
        raise _runtime_adapter_error(
            "RUNTIME_EXTERNAL_TOOL_GRANT_INVALID",
            "external-tool grant must be a verified typed contract",
            field="external_tool_grant",
        )
    exact = (
        ("task_id", task_id, grant.task_id),
        (
            "workflow_bundle_sha256",
            workflow_bundle_sha256,
            grant.workflow_bundle_sha256,
        ),
        ("node_instance_id", node_instance_id, grant.node_instance_id),
        ("repository_id", repository_id, grant.binding.repository_id),
        (
            "revision",
            revision,
            grant.assignment.controller_revision,
        ),
        ("attempt", attempt, grant.attempt),
        (
            "effect_classification",
            effect_classification,
            grant.capability.operations[0],
        ),
    )
    mismatches = [
        field
        for field, expected, actual in exact
        if expected != actual
    ]
    if mismatches:
        raise _runtime_adapter_error(
            "RUNTIME_EXTERNAL_TOOL_BINDING_MISMATCH",
            "runtime request differs from its external-tool grant",
            details={"fields": mismatches},
        )
    return grant.runtime_binding()


@_runtime_adapter_dataclass(frozen=True)
class RuntimeExecutionRequest:
    """Content-bound executor request; it contains no mutable workflow state."""

    request_id: str
    executor_id: str
    contract_version: str
    task_id: str
    workflow_bundle_sha256: str
    node_instance_id: str
    repository_id: str | None
    revision: int
    attempt: int
    input_sha256: str
    effect_classification: str
    logical_model_policy: str | None
    capabilities: tuple[str, ...]
    workspace_path: str | None
    approved_paths: tuple[str, ...]
    prompt_sha256: str | None
    output_schema_sha256: str | None
    external_tool_grant: object | None = None
    schema: str = RUNTIME_EXECUTION_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        _runtime_adapter_require_string(
            self.request_id, "request_id", stable_id=True
        )
        if not self.request_id.startswith("runtime-request:"):
            raise _runtime_adapter_error(
                "RUNTIME_REQUEST_ID_INVALID",
                "runtime request identity must be content-addressed",
                field="request_id",
            )
        _runtime_adapter_require_string(
            self.executor_id, "executor_id", stable_id=True
        )
        _runtime_adapter_require_string(
            self.contract_version, "contract_version", stable_id=True
        )
        _runtime_adapter_require_string(
            self.task_id, "task_id", stable_id=True
        )
        _runtime_adapter_require_digest(
            self.workflow_bundle_sha256, "workflow_bundle_sha256"
        )
        _runtime_adapter_require_string(
            self.node_instance_id,
            "node_instance_id",
            stable_id=True,
        )
        if self.repository_id is not None:
            _runtime_adapter_require_string(
                self.repository_id,
                "repository_id",
                stable_id=True,
            )
        _runtime_adapter_require_int(self.revision, "revision")
        _runtime_adapter_require_int(self.attempt, "attempt", minimum=1)
        _runtime_adapter_require_digest(
            self.input_sha256, "input_sha256"
        )
        _runtime_adapter_require_string(
            self.effect_classification,
            "effect_classification",
            stable_id=True,
        )
        if self.logical_model_policy is not None:
            if self.logical_model_policy not in _runtime_adapter_model_policies:
                raise _runtime_adapter_error(
                    "RUNTIME_MODEL_POLICY_INVALID",
                    "runtime request must use a logical model policy",
                    field="logical_model_policy",
                    details={
                        "supported": sorted(
                            _runtime_adapter_model_policies
                        )
                    },
                )
        object.__setattr__(
            self,
            "capabilities",
            _runtime_adapter_ordered_ids(
                self.capabilities, "capabilities"
            ),
        )
        object.__setattr__(
            self,
            "approved_paths",
            _runtime_adapter_portable_relative_paths(
                self.approved_paths, "approved_paths"
            ),
        )
        if self.workspace_path is not None:
            object.__setattr__(
                self,
                "workspace_path",
                _runtime_adapter_absolute_path(
                    self.workspace_path, "workspace_path"
                ),
            )
        if self.prompt_sha256 is not None:
            _runtime_adapter_require_digest(
                self.prompt_sha256, "prompt_sha256"
            )
        if self.output_schema_sha256 is not None:
            _runtime_adapter_require_digest(
                self.output_schema_sha256, "output_schema_sha256"
            )
        external_tool_binding = (
            None
            if self.external_tool_grant is None
            else _runtime_adapter_external_tool_binding(
                self.external_tool_grant,
                executor_id=self.executor_id,
                task_id=self.task_id,
                workflow_bundle_sha256=self.workflow_bundle_sha256,
                node_instance_id=self.node_instance_id,
                repository_id=self.repository_id,
                revision=self.revision,
                attempt=self.attempt,
                effect_classification=self.effect_classification,
                capabilities=self.capabilities,
            )
        )
        if (
            self.executor_id == "executor.external-tool/v1"
            and external_tool_binding is None
        ):
            raise _runtime_adapter_error(
                "RUNTIME_EXTERNAL_TOOL_GRANT_REQUIRED",
                "external-tool requests require a verified named grant",
                field="external_tool_grant",
            )
        if (
            self.executor_id != "executor.external-tool/v1"
            and external_tool_binding is not None
        ):
            raise _runtime_adapter_error(
                "RUNTIME_EXTERNAL_TOOL_GRANT_FORBIDDEN",
                "only the external-tool executor may receive a tool grant",
                field="external_tool_grant",
            )
        identity_payload = {
            "schema": RUNTIME_EXECUTION_REQUEST_SCHEMA,
            "executor_id": self.executor_id,
            "contract_version": self.contract_version,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "attempt": self.attempt,
            "input_sha256": self.input_sha256,
            "effect_classification": self.effect_classification,
            "logical_model_policy": self.logical_model_policy,
            "capabilities": list(self.capabilities),
            "workspace_path": self.workspace_path,
            "approved_paths": list(self.approved_paths),
            "prompt_sha256": self.prompt_sha256,
            "output_schema_sha256": self.output_schema_sha256,
            "external_tool_grant": external_tool_binding,
        }
        expected_request_id = (
            f"runtime-request:{_runtime_adapter_sha256(identity_payload)}"
        )
        if self.request_id != expected_request_id:
            raise _runtime_adapter_error(
                "RUNTIME_REQUEST_ID_INVALID",
                "runtime request identity does not match its canonical fields",
                field="request_id",
            )

    def binding(self) -> tuple[object, ...]:
        return (
            self.executor_id,
            self.task_id,
            self.workflow_bundle_sha256,
            self.node_instance_id,
            self.repository_id,
            self.attempt,
            self.input_sha256,
            (
                None
                if self.external_tool_grant is None
                else self.external_tool_grant.sha256
            ),
        )

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": self.schema,
            "request_id": self.request_id,
            "executor_id": self.executor_id,
            "contract_version": self.contract_version,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "revision": self.revision,
            "attempt": self.attempt,
            "input_sha256": self.input_sha256,
            "effect_classification": self.effect_classification,
            "capabilities": list(self.capabilities),
            "approved_paths": list(self.approved_paths),
            "external_tool_grant": (
                None
                if self.external_tool_grant is None
                else self.external_tool_grant.runtime_binding()
            ),
        }
        for key, value in (
            ("repository_id", self.repository_id),
            ("logical_model_policy", self.logical_model_policy),
            ("workspace_path", self.workspace_path),
            ("prompt_sha256", self.prompt_sha256),
            ("output_schema_sha256", self.output_schema_sha256),
        ):
            if value is not None:
                payload[key] = value
        return payload


def build_runtime_execution_request(
    *,
    executor_id: str,
    task_id: str,
    workflow_bundle_sha256: str,
    node_instance_id: str,
    revision: int,
    attempt: int,
    input_sha256: str,
    effect_classification: str,
    repository_id: str | None = None,
    logical_model_policy: str | None = None,
    capabilities: _RuntimeAdapterIterable[object] = (),
    workspace_path: str | None = None,
    approved_paths: _RuntimeAdapterIterable[object] = (),
    prompt_sha256: str | None = None,
    output_schema_sha256: str | None = None,
    external_tool_grant: object | None = None,
    registry: RuntimeAdapterContractRegistry | None = None,
) -> RuntimeExecutionRequest:
    """Validate and content-address one exact node-attempt dispatch request."""

    resolved_registry = registry or _RUNTIME_ADAPTER_REGISTRY
    contract = resolved_registry.resolve(executor_id)
    if effect_classification not in contract.effect_classifications:
        raise _runtime_adapter_error(
            "RUNTIME_EFFECT_UNSUPPORTED",
            "executor contract does not permit the requested effect",
            field="effect_classification",
            details={
                "executor_id": executor_id,
                "supported": list(contract.effect_classifications),
            },
        )
    normalized_workspace = (
        None
        if workspace_path is None
        else _runtime_adapter_absolute_path(
            workspace_path, "workspace_path"
        )
    )
    normalized_paths = _runtime_adapter_portable_relative_paths(
        approved_paths, "approved_paths"
    )
    normalized_capabilities = _runtime_adapter_ordered_ids(
        capabilities, "capabilities"
    )
    if effect_classification == "repository-write":
        if repository_id is None or normalized_workspace is None:
            raise _runtime_adapter_error(
                "RUNTIME_WRITE_SCOPE_REQUIRED",
                "repository-write requests require repository and worktree scope",
            )
        if not normalized_paths:
            raise _runtime_adapter_error(
                "RUNTIME_WRITE_SCOPE_REQUIRED",
                "repository-write requests require explicit approved paths",
                field="approved_paths",
            )
    elif normalized_paths:
        raise _runtime_adapter_error(
            "RUNTIME_WRITE_SCOPE_FORBIDDEN",
            "non-repository executors cannot receive repository write paths",
            field="approved_paths",
        )
    external_tool_binding = None
    if executor_id == "executor.external-tool/v1":
        if external_tool_grant is None:
            raise _runtime_adapter_error(
                "RUNTIME_EXTERNAL_TOOL_GRANT_REQUIRED",
                "external-tool requests require a verified named grant",
                field="external_tool_grant",
            )
        external_tool_binding = _runtime_adapter_external_tool_binding(
            external_tool_grant,
            executor_id=executor_id,
            task_id=task_id,
            workflow_bundle_sha256=workflow_bundle_sha256,
            node_instance_id=node_instance_id,
            repository_id=repository_id,
            revision=revision,
            attempt=attempt,
            effect_classification=effect_classification,
            capabilities=normalized_capabilities,
        )
    elif external_tool_grant is not None:
        raise _runtime_adapter_error(
            "RUNTIME_EXTERNAL_TOOL_GRANT_FORBIDDEN",
            "only the external-tool executor may receive a tool grant",
            field="external_tool_grant",
        )
    if contract.requires_jsonl:
        if prompt_sha256 is None or output_schema_sha256 is None:
            raise _runtime_adapter_error(
                "CODEX_EXEC_BINDING_REQUIRED",
                "codex exec requests require prompt and output-schema digests",
            )
    elif output_schema_sha256 is not None:
        raise _runtime_adapter_error(
            "RUNTIME_OUTPUT_SCHEMA_FORBIDDEN",
            "only structured JSONL subprocess contracts bind an output schema",
            field="output_schema_sha256",
        )
    if (
        executor_id
        in {
            "executor.codex-exec/v1",
            "executor.codex-thread/v1",
            "executor.native-subagents/v1",
        }
        and logical_model_policy is None
    ):
        raise _runtime_adapter_error(
            "RUNTIME_MODEL_POLICY_REQUIRED",
            "model-backed executors require a host-resolved logical policy",
            field="logical_model_policy",
        )
    payload: dict[str, object] = {
        "schema": RUNTIME_EXECUTION_REQUEST_SCHEMA,
        "executor_id": executor_id,
        "contract_version": contract.contract_version,
        "task_id": task_id,
        "workflow_bundle_sha256": workflow_bundle_sha256,
        "node_instance_id": node_instance_id,
        "repository_id": repository_id,
        "revision": revision,
        "attempt": attempt,
        "input_sha256": input_sha256,
        "effect_classification": effect_classification,
        "logical_model_policy": logical_model_policy,
        "capabilities": list(normalized_capabilities),
        "workspace_path": normalized_workspace,
        "approved_paths": list(normalized_paths),
        "prompt_sha256": prompt_sha256,
        "output_schema_sha256": output_schema_sha256,
        "external_tool_grant": external_tool_binding,
    }
    request_id = f"runtime-request:{_runtime_adapter_sha256(payload)}"
    return RuntimeExecutionRequest(
        request_id=request_id,
        executor_id=executor_id,
        contract_version=contract.contract_version,
        task_id=task_id,
        workflow_bundle_sha256=workflow_bundle_sha256,
        node_instance_id=node_instance_id,
        repository_id=repository_id,
        revision=revision,
        attempt=attempt,
        input_sha256=input_sha256,
        effect_classification=effect_classification,
        logical_model_policy=logical_model_policy,
        capabilities=tuple(payload["capabilities"]),
        workspace_path=normalized_workspace,
        approved_paths=normalized_paths,
        prompt_sha256=prompt_sha256,
        output_schema_sha256=output_schema_sha256,
        external_tool_grant=external_tool_grant,
    )


def codex_exec_result_candidate_schema() -> dict[str, object]:
    """Return a strict bounded candidate schema for default codex exec output.

    The candidate is deliberately *not* ``dev-flow-node-result/v1``.  It must
    be materialized as a controller-owned artifact and validated through
    ``validate_orchestration_node_result`` before it can become authoritative.
    """

    digest = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
        "minLength": 64,
        "maxLength": 64,
    }
    stable_id = {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$",
        "minLength": 1,
        "maxLength": 256,
    }
    artifact_reference = {
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "const": "dev-flow-artifact-reference/v1",
            },
            "artifact_id": stable_id,
            "task_id": stable_id,
            "semantic_sha256": digest,
            "sha256": digest,
            "size": {"type": "integer", "minimum": 0},
            "media_type": {
                "type": "string",
                "minLength": 1,
                "maxLength": 256,
            },
            "kind": stable_id,
            "locator": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1024,
            },
            "path_identity_sha256": digest,
        },
        "required": [
            "schema",
            "artifact_id",
            "task_id",
            "semantic_sha256",
            "sha256",
            "size",
            "media_type",
            "kind",
            "locator",
        ],
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CODEX_EXEC_RESULT_CANDIDATE_SCHEMA,
        "type": "object",
        "properties": {
            "schema": {
                "type": "string",
                "const": CODEX_EXEC_RESULT_CANDIDATE_SCHEMA,
            },
            "task_id": stable_id,
            "workflow_bundle_sha256": digest,
            "node_instance_id": stable_id,
            "repository_id": stable_id,
            "attempt": {"type": "integer", "minimum": 1},
            "input_sha256": digest,
            "outcome": {
                "type": "string",
                "enum": [
                    "BLOCKED",
                    "FAILED",
                    "SUCCEEDED",
                    "WAITING_APPROVAL",
                    "WAITING_EXTERNAL",
                ],
            },
            "summary": {
                "type": "string",
                "maxLength": 512,
            },
            "artifact_refs": {
                "type": "array",
                "items": artifact_reference,
            },
            "evidence_refs": {
                "type": "array",
                "items": artifact_reference,
            },
            "changed_files": {
                "type": "array",
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1024,
                },
            },
            "blockers": {
                "type": "array",
                "items": stable_id,
            },
            "plan_drift": {
                "type": "object",
                "properties": {
                    "detected": {"type": "boolean"},
                    "reasons": {
                        "type": "array",
                        "items": stable_id,
                    },
                },
                "required": ["detected"],
                "additionalProperties": False,
            },
        },
        "required": sorted(
            _runtime_adapter_candidate_required_fields,
            key=lambda item: item.encode("utf-8"),
        ),
        "additionalProperties": False,
    }


def _runtime_adapter_candidate_artifact_refs(
    value: object,
    *,
    field: str,
    task_id: str,
) -> tuple[_RuntimeAdapterMapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate artifact references must be an array",
            field=field,
        )
    references: list[_RuntimeAdapterMapping[str, object]] = []
    artifact_ids: list[str] = []
    allowed = {
        "schema",
        "artifact_id",
        "task_id",
        "semantic_sha256",
        "sha256",
        "size",
        "media_type",
        "kind",
        "locator",
        "path_identity_sha256",
    }
    required = allowed - {"path_identity_sha256"}
    for index, supplied in enumerate(value):
        pointer = f"{field}/{index}"
        if not isinstance(supplied, _RuntimeAdapterMapping):
            raise _runtime_adapter_error(
                "CODEX_EXEC_CANDIDATE_INVALID",
                "candidate artifact reference must be an object",
                field=pointer,
            )
        unknown = sorted(
            set(supplied) - allowed,
            key=lambda item: str(item).encode("utf-8"),
        )
        missing = sorted(
            required - set(supplied), key=lambda item: item.encode("utf-8")
        )
        if unknown or missing:
            raise _runtime_adapter_error(
                "CODEX_EXEC_CANDIDATE_INVALID",
                "candidate artifact reference fields are incomplete",
                field=pointer,
                details={"unknown": unknown, "missing": missing},
            )
        if supplied["schema"] != "dev-flow-artifact-reference/v1":
            raise _runtime_adapter_error(
                "CODEX_EXEC_CANDIDATE_INVALID",
                "candidate artifact reference schema is unsupported",
                field=f"{pointer}/schema",
            )
        artifact_id = _runtime_adapter_require_string(
            supplied["artifact_id"],
            f"{pointer}/artifact_id",
            stable_id=True,
        )
        supplied_task = _runtime_adapter_require_string(
            supplied["task_id"], f"{pointer}/task_id", stable_id=True
        )
        if supplied_task != task_id:
            raise _runtime_adapter_error(
                "CODEX_EXEC_CANDIDATE_INVALID",
                "candidate artifact reference belongs to another task",
                field=f"{pointer}/task_id",
            )
        normalized: dict[str, object] = {
            "schema": "dev-flow-artifact-reference/v1",
            "artifact_id": artifact_id,
            "task_id": supplied_task,
            "semantic_sha256": _runtime_adapter_require_digest(
                supplied["semantic_sha256"],
                f"{pointer}/semantic_sha256",
            ),
            "sha256": _runtime_adapter_require_digest(
                supplied["sha256"], f"{pointer}/sha256"
            ),
            "size": _runtime_adapter_require_int(
                supplied["size"], f"{pointer}/size"
            ),
            "media_type": _runtime_adapter_require_string(
                supplied["media_type"],
                f"{pointer}/media_type",
                maximum_bytes=256,
            ),
            "kind": _runtime_adapter_require_string(
                supplied["kind"], f"{pointer}/kind", stable_id=True
            ),
            "locator": _runtime_adapter_require_string(
                supplied["locator"],
                f"{pointer}/locator",
                maximum_bytes=1024,
            ),
        }
        if "path_identity_sha256" in supplied:
            normalized["path_identity_sha256"] = (
                _runtime_adapter_require_digest(
                    supplied["path_identity_sha256"],
                    f"{pointer}/path_identity_sha256",
                )
            )
        artifact_ids.append(artifact_id)
        references.append(
            _runtime_adapter_freeze(normalized)  # type: ignore[arg-type]
        )
    if len(artifact_ids) != len(set(artifact_ids)):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate artifact identities must be unique",
            field=field,
        )
    if artifact_ids != sorted(
        artifact_ids, key=lambda item: item.encode("utf-8")
    ):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate artifact references must use UTF-8 identity order",
            field=field,
        )
    return tuple(references)


def _runtime_adapter_candidate_ordered_ids(
    value: object, field: str
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate identity collection must be an array",
            field=field,
        )
    normalized = _runtime_adapter_ordered_ids(value, field)
    if tuple(value) != normalized:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate identities must use canonical UTF-8 order",
            field=field,
        )
    return normalized


def validate_codex_exec_result_candidate(
    value: object,
) -> _RuntimeAdapterMapping[str, object]:
    """Validate the bounded non-authoritative default model projection."""

    if not isinstance(value, _RuntimeAdapterMapping):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "codex exec result candidate must be an object",
        )
    _runtime_adapter_freeze(value)
    allowed = set(_runtime_adapter_candidate_required_fields) | {
        "repository_id"
    }
    unknown = sorted(
        set(value) - allowed, key=lambda item: str(item).encode("utf-8")
    )
    missing = sorted(
        _runtime_adapter_candidate_required_fields - set(value),
        key=lambda item: item.encode("utf-8"),
    )
    if unknown or missing:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "codex exec result candidate fields are incomplete",
            details={"unknown": unknown, "missing": missing},
        )
    if value["schema"] != CODEX_EXEC_RESULT_CANDIDATE_SCHEMA:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_UNSUPPORTED",
            "codex exec result candidate schema is unsupported",
            field="schema",
        )
    task_id = _runtime_adapter_require_string(
        value["task_id"], "task_id", stable_id=True
    )
    normalized: dict[str, object] = {
        "schema": CODEX_EXEC_RESULT_CANDIDATE_SCHEMA,
        "task_id": task_id,
        "workflow_bundle_sha256": _runtime_adapter_require_digest(
            value["workflow_bundle_sha256"],
            "workflow_bundle_sha256",
        ),
        "node_instance_id": _runtime_adapter_require_string(
            value["node_instance_id"],
            "node_instance_id",
            stable_id=True,
        ),
        "attempt": _runtime_adapter_require_int(
            value["attempt"], "attempt", minimum=1
        ),
        "input_sha256": _runtime_adapter_require_digest(
            value["input_sha256"], "input_sha256"
        ),
    }
    if "repository_id" in value:
        normalized["repository_id"] = _runtime_adapter_require_string(
            value["repository_id"],
            "repository_id",
            stable_id=True,
        )
    outcome = _runtime_adapter_require_string(
        value["outcome"], "outcome", stable_id=True
    )
    if outcome not in {
        "BLOCKED",
        "FAILED",
        "SUCCEEDED",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
    }:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate outcome is unsupported",
            field="outcome",
        )
    normalized["outcome"] = outcome
    normalized["summary"] = _runtime_adapter_require_string(
        value["summary"], "summary", maximum_bytes=512
    )
    normalized["artifact_refs"] = (
        _runtime_adapter_candidate_artifact_refs(
            value["artifact_refs"],
            field="artifact_refs",
            task_id=task_id,
        )
    )
    normalized["evidence_refs"] = (
        _runtime_adapter_candidate_artifact_refs(
            value["evidence_refs"],
            field="evidence_refs",
            task_id=task_id,
        )
    )
    changed_files = value["changed_files"]
    if not isinstance(changed_files, (list, tuple)):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate changed files must be an array",
            field="changed_files",
        )
    normalized_changed = _runtime_adapter_portable_relative_paths(
        changed_files, "changed_files"
    )
    if tuple(changed_files) != normalized_changed:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate changed files must use canonical UTF-8 order",
            field="changed_files",
        )
    normalized["changed_files"] = normalized_changed
    blockers = _runtime_adapter_candidate_ordered_ids(
        value["blockers"], "blockers"
    )
    normalized["blockers"] = blockers
    plan_drift = value["plan_drift"]
    if (
        not isinstance(plan_drift, _RuntimeAdapterMapping)
        or set(plan_drift) != {"detected", "reasons"}
        or not isinstance(plan_drift.get("detected"), bool)
    ):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate plan drift must declare detected and reasons",
            field="plan_drift",
        )
    drift_reasons = _runtime_adapter_candidate_ordered_ids(
        plan_drift["reasons"], "plan_drift/reasons"
    )
    drift_detected = bool(plan_drift["detected"])
    if drift_detected != bool(drift_reasons):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate plan-drift flag and reasons must agree",
            field="plan_drift",
        )
    if drift_detected and outcome != "BLOCKED":
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "candidate plan drift must produce a blocked outcome",
            field="outcome",
        )
    if outcome == "SUCCEEDED" and blockers:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "successful candidate cannot contain blockers",
            field="blockers",
        )
    if outcome == "BLOCKED" and not (blockers or drift_detected):
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_INVALID",
            "blocked candidate requires a blocker or plan drift",
            field="blockers",
        )
    normalized["plan_drift"] = {
        "detected": drift_detected,
        "reasons": drift_reasons,
    }
    candidate_id = (
        "codex-candidate-" + _runtime_adapter_sha256(normalized)
    )
    normalized["candidate_id"] = candidate_id
    size = len(canonical_runtime_adapter_bytes(normalized))
    if size > 2048:
        raise _runtime_adapter_error(
            "CODEX_EXEC_CANDIDATE_BUDGET_EXCEEDED",
            "codex exec result candidate exceeds 2,048 UTF-8 bytes",
            details={"size": size, "budget": 2048},
        )
    return _runtime_adapter_freeze(normalized)  # type: ignore[return-value]


@_runtime_adapter_dataclass(frozen=True)
class CodexExecInvocation:
    request_id: str
    argv: tuple[str, ...]
    stdin_bytes: bytes
    output_schema_path: str
    output_schema_sha256: str
    output_schema_bytes: bytes
    sandbox: str
    event_protocol: str = CODEX_EXEC_EVENT_PROTOCOL
    schema: str = CODEX_EXEC_INVOCATION_SCHEMA

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "argv": list(self.argv),
            "stdin_sha256": _runtime_adapter_hashlib.sha256(
                self.stdin_bytes
            ).hexdigest(),
            "stdin_size": len(self.stdin_bytes),
            "output_schema_path": self.output_schema_path,
            "output_schema_sha256": self.output_schema_sha256,
            "output_schema_size": len(self.output_schema_bytes),
            "sandbox": self.sandbox,
            "event_protocol": self.event_protocol,
        }


def build_codex_exec_invocation(
    request: RuntimeExecutionRequest,
    *,
    prompt: str,
    output_schema_path: str,
    output_schema: _RuntimeAdapterMapping[str, object] | None = None,
    resolved_model: str | None = None,
    codex_binary: str = "codex",
    registry: RuntimeAdapterContractRegistry | None = None,
) -> CodexExecInvocation:
    """Prepare, but do not run, a least-privilege ``codex exec`` process."""

    if not isinstance(request, RuntimeExecutionRequest):
        raise _runtime_adapter_error(
            "CODEX_EXEC_REQUEST_INVALID",
            "codex exec requires a validated runtime execution request",
        )
    resolved_registry = registry or _RUNTIME_ADAPTER_REGISTRY
    contract = resolved_registry.resolve(request.executor_id)
    if request.executor_id != "executor.codex-exec/v1":
        raise _runtime_adapter_error(
            "CODEX_EXEC_REQUEST_INVALID",
            "runtime request does not select the codex exec adapter",
            details={"executor_id": request.executor_id},
        )
    prompt_text = _runtime_adapter_require_string(
        prompt, "prompt", maximum_bytes=CODEX_EXEC_PROMPT_BUDGET
    )
    prompt_bytes = prompt_text.encode("utf-8")
    prompt_sha256 = _runtime_adapter_hashlib.sha256(
        prompt_bytes
    ).hexdigest()
    if request.prompt_sha256 != prompt_sha256:
        raise _runtime_adapter_error(
            "CODEX_EXEC_PROMPT_MISMATCH",
            "codex exec prompt does not match the bound request digest",
            details={
                "expected": request.prompt_sha256,
                "actual": prompt_sha256,
            },
        )
    schema_value = (
        codex_exec_result_candidate_schema()
        if output_schema is None
        else dict(output_schema)
    )
    if (
        schema_value.get("type") != "object"
        or schema_value.get("additionalProperties") is not False
    ):
        raise _runtime_adapter_error(
            "CODEX_EXEC_OUTPUT_SCHEMA_INVALID",
            "codex exec output schema must be a closed object schema",
            field="output_schema",
        )
    schema_bytes = canonical_runtime_adapter_bytes(schema_value)
    schema_sha256 = _runtime_adapter_hashlib.sha256(
        schema_bytes
    ).hexdigest()
    if request.output_schema_sha256 != schema_sha256:
        raise _runtime_adapter_error(
            "CODEX_EXEC_OUTPUT_SCHEMA_MISMATCH",
            "codex exec schema does not match the bound request digest",
            details={
                "expected": request.output_schema_sha256,
                "actual": schema_sha256,
            },
        )
    schema_path = _runtime_adapter_absolute_path(
        output_schema_path, "output_schema_path"
    )
    binary = _runtime_adapter_require_string(
        codex_binary, "codex_binary", maximum_bytes=1024
    )
    if "\x00" in binary or "\r" in binary or "\n" in binary:
        raise _runtime_adapter_error(
            "CODEX_EXEC_BINARY_INVALID",
            "codex binary locator contains a control separator",
            field="codex_binary",
        )
    sandbox = contract.sandbox_by_effect.get(
        request.effect_classification
    )
    if sandbox not in _runtime_adapter_sandbox_modes:
        raise _runtime_adapter_error(
            "CODEX_EXEC_SANDBOX_UNAVAILABLE",
            "codex exec effect has no least-privilege sandbox mapping",
            details={"effect": request.effect_classification},
        )
    if request.workspace_path is None:
        raise _runtime_adapter_error(
            "CODEX_EXEC_WORKSPACE_REQUIRED",
            "codex exec requires one exact workspace root",
            field="workspace_path",
        )
    argv: list[str] = [
        binary,
        "exec",
        "--json",
        "--color",
        "never",
        "--sandbox",
        sandbox,
        "--cd",
        request.workspace_path,
        "--output-schema",
        schema_path,
        "--ephemeral",
        "--ignore-user-config",
    ]
    if resolved_model is None:
        raise _runtime_adapter_error(
            "CODEX_EXEC_MODEL_UNRESOLVED",
            "codex exec requires host resolution of its logical model policy",
            details={"logical_policy": request.logical_model_policy},
        )
    model = _runtime_adapter_require_string(
        resolved_model, "resolved_model", maximum_bytes=256
    )
    if "\x00" in model or "\r" in model or "\n" in model:
        raise _runtime_adapter_error(
            "CODEX_EXEC_MODEL_INVALID",
            "resolved model contains a control separator",
            field="resolved_model",
        )
    argv.extend(("--model", model))
    argv.append("-")
    forbidden = {
        "--add-dir",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--ignore-rules",
    }
    if forbidden.intersection(argv):
        raise _runtime_adapter_error(
            "CODEX_EXEC_PRIVILEGE_INVALID",
            "codex exec invocation contains a forbidden privilege option",
        )
    return CodexExecInvocation(
        request_id=request.request_id,
        argv=tuple(argv),
        stdin_bytes=prompt_bytes,
        output_schema_path=schema_path,
        output_schema_sha256=schema_sha256,
        output_schema_bytes=schema_bytes,
        sandbox=sandbox,
    )


def _runtime_adapter_json_pairs(
    pairs: _RuntimeAdapterSequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _runtime_adapter_error(
                "CODEX_EXEC_JSON_DUPLICATE_KEY",
                "codex exec JSON contains a duplicate object key",
                details={"key": key},
            )
        result[key] = value
    return result


def _runtime_adapter_reject_float(value: str) -> object:
    raise _runtime_adapter_error(
        "CODEX_EXEC_JSON_NUMBER_INVALID",
        "codex exec JSON must not contain floating-point numbers",
        details={"value": value[:64]},
    )


def _runtime_adapter_reject_constant(value: str) -> object:
    raise _runtime_adapter_error(
        "CODEX_EXEC_JSON_NUMBER_INVALID",
        "codex exec JSON must not contain non-finite numbers",
        details={"value": value},
    )


def _runtime_adapter_parse_json(
    text: str, *, field: str
) -> object:
    try:
        return _runtime_adapter_json.loads(
            text,
            object_pairs_hook=_runtime_adapter_json_pairs,
            parse_float=_runtime_adapter_reject_float,
            parse_constant=_runtime_adapter_reject_constant,
        )
    except RuntimeAdapterError:
        raise
    except (_runtime_adapter_json.JSONDecodeError, UnicodeError) as exc:
        raise _runtime_adapter_error(
            "CODEX_EXEC_JSON_INVALID",
            "codex exec emitted malformed JSON",
            field=field,
            details={"line": getattr(exc, "lineno", None)},
        ) from exc


def _runtime_adapter_usage(
    value: object,
) -> tuple[_RuntimeAdapterMapping[str, int] | None, dict[str, object] | None]:
    fields = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    if not isinstance(value, _RuntimeAdapterMapping):
        return (
            None,
            {
                "code": "CODEX_EXEC_USAGE_UNAVAILABLE",
                "reason": "turn-completed-usage-missing",
            },
        )
    normalized: dict[str, int] = {}
    for field in fields:
        supplied = value.get(field)
        if (
            isinstance(supplied, bool)
            or not isinstance(supplied, int)
            or supplied < 0
        ):
            return (
                None,
                {
                    "code": "CODEX_EXEC_USAGE_UNAVAILABLE",
                    "reason": "turn-completed-usage-malformed",
                    "field": field,
                },
            )
        normalized[field] = supplied
    if (
        normalized["cached_input_tokens"] > normalized["input_tokens"]
        or normalized["reasoning_output_tokens"]
        > normalized["output_tokens"]
    ):
        return (
            None,
            {
                "code": "CODEX_EXEC_USAGE_UNAVAILABLE",
                "reason": "turn-completed-usage-contradictory",
            },
        )
    return _RuntimeAdapterMappingProxyType(normalized), None


@_runtime_adapter_dataclass(frozen=True)
class CodexExecResult:
    request_id: str
    thread_id: str
    structured_result: _RuntimeAdapterMapping[str, object]
    result_profile_id: str
    authoritative: bool
    usage: _RuntimeAdapterMapping[str, int] | None
    usage_diagnostic: _RuntimeAdapterMapping[str, object] | None
    event_count: int
    response_bytes: int
    schema: str = CODEX_EXEC_RESULT_SCHEMA

    def __post_init__(self) -> None:
        _runtime_adapter_require_string(
            self.result_profile_id,
            "result_profile_id",
            stable_id=True,
        )
        if not isinstance(self.authoritative, bool):
            raise _runtime_adapter_error(
                "CODEX_EXEC_RESULT_INVALID",
                "authoritative marker must be boolean",
                field="authoritative",
            )
        object.__setattr__(
            self,
            "structured_result",
            _runtime_adapter_freeze(dict(self.structured_result)),
        )
        if self.usage is not None:
            object.__setattr__(
                self,
                "usage",
                _runtime_adapter_freeze(dict(self.usage)),
            )
        if self.usage_diagnostic is not None:
            object.__setattr__(
                self,
                "usage_diagnostic",
                _runtime_adapter_freeze(
                    dict(self.usage_diagnostic)
                ),
            )

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": self.schema,
            "request_id": self.request_id,
            "thread_id": self.thread_id,
            "structured_result": _runtime_adapter_thaw(
                self.structured_result
            ),
            "result_profile_id": self.result_profile_id,
            "authoritative": self.authoritative,
            "event_count": self.event_count,
            "response_bytes": self.response_bytes,
        }
        if self.usage is not None:
            payload["usage"] = _runtime_adapter_thaw(self.usage)
        if self.usage_diagnostic is not None:
            payload["usage_diagnostic"] = _runtime_adapter_thaw(
                self.usage_diagnostic
            )
        return payload


def parse_codex_exec_jsonl(
    data: bytes | str,
    *,
    request: RuntimeExecutionRequest,
    node_result_validator: _RuntimeAdapterCallable[..., object] | None = None,
    result_profile: NodeResultAdapterProfile = (
        CODEX_EXEC_CANDIDATE_PROFILE
    ),
) -> CodexExecResult:
    """Parse one completed ``codex exec --json`` turn without side effects."""

    if request.executor_id != "executor.codex-exec/v1":
        raise _runtime_adapter_error(
            "CODEX_EXEC_REQUEST_INVALID",
            "JSONL result belongs to a non-codex-exec request",
        )
    if isinstance(data, bytes):
        raw = data
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _runtime_adapter_error(
                "CODEX_EXEC_JSONL_ENCODING_INVALID",
                "codex exec JSONL must be UTF-8",
            ) from exc
    elif isinstance(data, str):
        text = data
        try:
            raw = data.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _runtime_adapter_error(
                "CODEX_EXEC_JSONL_ENCODING_INVALID",
                "codex exec JSONL must be UTF-8",
            ) from exc
    else:
        raise _runtime_adapter_error(
            "CODEX_EXEC_JSONL_INVALID",
            "codex exec JSONL must be bytes or text",
        )
    if len(raw) > CODEX_EXEC_JSONL_BUDGET:
        raise _runtime_adapter_error(
            "CODEX_EXEC_JSONL_TOO_LARGE",
            "codex exec JSONL exceeds its adapter byte budget",
            details={
                "size": len(raw),
                "budget": CODEX_EXEC_JSONL_BUDGET,
            },
        )
    lines = text.splitlines()
    if not lines:
        raise _runtime_adapter_error(
            "CODEX_EXEC_INCOMPLETE",
            "codex exec produced no JSONL events",
        )
    if len(lines) > CODEX_EXEC_EVENT_BUDGET:
        raise _runtime_adapter_error(
            "CODEX_EXEC_EVENT_LIMIT_EXCEEDED",
            "codex exec emitted too many events",
            details={
                "count": len(lines),
                "budget": CODEX_EXEC_EVENT_BUDGET,
            },
        )
    events: list[_RuntimeAdapterMapping[str, object]] = []
    for index, line in enumerate(lines):
        if not line:
            raise _runtime_adapter_error(
                "CODEX_EXEC_JSONL_INVALID",
                "codex exec JSONL contains a blank event",
                details={"line": index + 1},
            )
        if len(line.encode("utf-8")) > CODEX_EXEC_LINE_BUDGET:
            raise _runtime_adapter_error(
                "CODEX_EXEC_EVENT_TOO_LARGE",
                "codex exec event exceeds its line budget",
                details={"line": index + 1},
            )
        event = _runtime_adapter_parse_json(
            line, field=f"events/{index}"
        )
        if not isinstance(event, _RuntimeAdapterMapping):
            raise _runtime_adapter_error(
                "CODEX_EXEC_EVENT_INVALID",
                "codex exec events must be JSON objects",
                details={"line": index + 1},
            )
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise _runtime_adapter_error(
                "CODEX_EXEC_EVENT_INVALID",
                "codex exec event requires a string type",
                details={"line": index + 1},
            )
        events.append(event)
    thread_events = [
        event for event in events if event.get("type") == "thread.started"
    ]
    if len(thread_events) != 1 or events[0].get("type") != "thread.started":
        raise _runtime_adapter_error(
            "CODEX_EXEC_THREAD_EVENT_INVALID",
            "codex exec requires exactly one leading thread.started event",
            details={"count": len(thread_events)},
        )
    thread_id = _runtime_adapter_require_string(
        thread_events[0].get("thread_id"),
        "events/0/thread_id",
        stable_id=True,
    )
    failure = next(
        (
            event
            for event in events
            if event.get("type") in {"error", "turn.failed"}
        ),
        None,
    )
    if failure is not None:
        message = failure.get("message")
        if not isinstance(message, str):
            error = failure.get("error")
            message = (
                error.get("message")
                if isinstance(error, _RuntimeAdapterMapping)
                and isinstance(error.get("message"), str)
                else "codex exec reported a failed turn"
            )
        raise _runtime_adapter_error(
            "CODEX_EXEC_TURN_FAILED",
            "codex exec reported a failed or interrupted turn",
            details={"diagnostic": message[:512]},
        )
    completed_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("type") == "turn.completed"
    ]
    if len(completed_indexes) != 1:
        raise _runtime_adapter_error(
            "CODEX_EXEC_INCOMPLETE",
            "codex exec requires exactly one turn.completed event",
            details={"count": len(completed_indexes)},
        )
    completed_index = completed_indexes[0]
    if completed_index != len(events) - 1:
        raise _runtime_adapter_error(
            "CODEX_EXEC_EVENT_ORDER_INVALID",
            "codex exec emitted events after turn.completed",
        )
    messages: list[str] = []
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if (
            isinstance(item, _RuntimeAdapterMapping)
            and item.get("type") == "agent_message"
        ):
            message = item.get("text")
            if not isinstance(message, str):
                raise _runtime_adapter_error(
                    "CODEX_EXEC_FINAL_OUTPUT_INVALID",
                    "completed agent message must contain text",
                )
            messages.append(message)
    if len(messages) != 1:
        raise _runtime_adapter_error(
            "CODEX_EXEC_FINAL_OUTPUT_AMBIGUOUS",
            "codex exec requires exactly one final agent message",
            details={"count": len(messages)},
        )
    supplied_result = _runtime_adapter_parse_json(
        messages[0], field="final_output"
    )
    if not isinstance(supplied_result, _RuntimeAdapterMapping):
        raise _runtime_adapter_error(
            "CODEX_EXEC_FINAL_OUTPUT_INVALID",
            "codex exec final output must be a NodeResult object",
        )
    if not isinstance(result_profile, NodeResultAdapterProfile):
        raise _runtime_adapter_error(
            "RUNTIME_NODE_RESULT_PROFILE_INVALID",
            "codex exec requires a validated structured-result profile",
        )
    missing = sorted(
        set(result_profile.required_fields) - set(supplied_result),
        key=lambda item: item.encode("utf-8"),
    )
    if missing:
        raise _runtime_adapter_error(
            "CODEX_EXEC_NODE_RESULT_INCOMPLETE",
            "codex exec final structured result is missing required fields",
            details={"fields": missing},
        )
    forbidden = sorted(
        (
            field
            for field in result_profile.forbidden_model_fields
            if field in supplied_result
            and supplied_result[field] is not None
        ),
        key=lambda item: item.encode("utf-8"),
    )
    if forbidden:
        raise _runtime_adapter_error(
            "CODEX_EXEC_NODE_RESULT_AUTHORITY_INVALID",
            "model output cannot mint runtime handles or usage telemetry",
            details={"fields": forbidden},
        )
    validator = node_result_validator
    if validator is None:
        if result_profile == CODEX_EXEC_CANDIDATE_PROFILE:
            validator = validate_codex_exec_result_candidate
        elif result_profile == ORCHESTRATION_NODE_RESULT_PROFILE:
            candidate = globals().get(
                "validate_orchestration_node_result"
            )
            if callable(candidate):
                validator = candidate
    if not callable(validator):
        raise _runtime_adapter_error(
            "RUNTIME_NODE_RESULT_VALIDATOR_UNAVAILABLE",
            "no package-owned NodeResult validator is available",
        )
    try:
        validated_object = validator(supplied_result)
    except Exception as exc:
        raise _runtime_adapter_error(
            "CODEX_EXEC_NODE_RESULT_INVALID",
            "codex exec final output failed NodeResult validation",
            details={
                "validator_code": getattr(exc, "code", None),
                "diagnostic": str(exc)[:512],
            },
        ) from exc
    if not isinstance(validated_object, _RuntimeAdapterMapping):
        raise _runtime_adapter_error(
            "CODEX_EXEC_NODE_RESULT_INVALID",
            "NodeResult validator returned a non-object",
        )
    validated = dict(validated_object)
    expected = {
        result_profile.task_id_field: request.task_id,
        result_profile.workflow_bundle_field: (
            request.workflow_bundle_sha256
        ),
        result_profile.node_instance_field: request.node_instance_id,
        result_profile.attempt_field: request.attempt,
        result_profile.input_sha256_field: request.input_sha256,
    }
    for field, expected_value in expected.items():
        if validated.get(field) != expected_value:
            raise _runtime_adapter_error(
                "CODEX_EXEC_NODE_RESULT_BINDING_MISMATCH",
                "NodeResult does not match its exact execution request",
                field=field,
                details={
                    "expected": expected_value,
                    "actual": validated.get(field),
                },
            )
    if request.repository_id is None:
        if (
            result_profile.repository_field is not None
            and result_profile.repository_field in supplied_result
        ):
            raise _runtime_adapter_error(
                "CODEX_EXEC_NODE_RESULT_BINDING_MISMATCH",
                "task-scoped NodeResult must not claim a repository",
                field=result_profile.repository_field,
            )
    elif (
        result_profile.repository_field is None
        or validated.get(result_profile.repository_field)
        != request.repository_id
    ):
        raise _runtime_adapter_error(
            "CODEX_EXEC_NODE_RESULT_BINDING_MISMATCH",
            "NodeResult repository does not match its request",
            field=result_profile.repository_field,
            details={
                "expected": request.repository_id,
                "actual": (
                    None
                    if result_profile.repository_field is None
                    else validated.get(result_profile.repository_field)
                ),
            },
        )
    usage, usage_diagnostic = _runtime_adapter_usage(
        events[completed_index].get("usage")
    )
    return CodexExecResult(
        request_id=request.request_id,
        thread_id=thread_id,
        structured_result=validated,
        result_profile_id=result_profile.profile_id,
        authoritative=result_profile.authoritative,
        usage=usage,
        usage_diagnostic=usage_diagnostic,
        event_count=len(events),
        response_bytes=len(raw),
    )


@_runtime_adapter_dataclass(frozen=True)
class RuntimeHandleRecord:
    """Adapter-owned handle metadata; never a node outcome or evidence fact."""

    handle_id: str
    kind: str
    executor_id: str
    request_id: str
    task_id: str
    node_instance_id: str
    repository_id: str | None
    attempt: int
    availability: str
    quiescence_evidence_sha256: str | None = None
    schema: str = RUNTIME_HANDLE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        for field, value in (
            ("handle_id", self.handle_id),
            ("kind", self.kind),
            ("executor_id", self.executor_id),
            ("request_id", self.request_id),
            ("task_id", self.task_id),
            ("node_instance_id", self.node_instance_id),
        ):
            _runtime_adapter_require_string(
                value, field, stable_id=True
            )
        if self.repository_id is not None:
            _runtime_adapter_require_string(
                self.repository_id,
                "repository_id",
                stable_id=True,
            )
        _runtime_adapter_require_int(self.attempt, "attempt", minimum=1)
        if self.availability not in _runtime_adapter_handle_states:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_STATE_INVALID",
                "runtime handle availability is unsupported",
                field="availability",
            )
        if self.availability == "quiesced":
            _runtime_adapter_require_digest(
                self.quiescence_evidence_sha256,
                "quiescence_evidence_sha256",
            )
        elif self.quiescence_evidence_sha256 is not None:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_STATE_INVALID",
                "only a quiesced handle may bind quiescence evidence",
                field="quiescence_evidence_sha256",
            )

    def binding(self) -> tuple[object, ...]:
        return (
            self.executor_id,
            self.task_id,
            self.node_instance_id,
            self.repository_id,
            self.attempt,
            self.request_id,
        )

    def workflow_reference(self) -> dict[str, object]:
        """Return only the safe locator accepted by schema-v3 task state."""

        value: dict[str, object] = {
            "schema": RUNTIME_HANDLE_SCHEMA,
            "handle_id": self.handle_id,
            "kind": self.kind,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
        }
        if self.repository_id is not None:
            value["repository_id"] = self.repository_id
        return value

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": self.schema,
            "handle_id": self.handle_id,
            "kind": self.kind,
            "executor_id": self.executor_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "availability": self.availability,
        }
        if self.repository_id is not None:
            value["repository_id"] = self.repository_id
        if self.quiescence_evidence_sha256 is not None:
            value["quiescence_evidence_sha256"] = (
                self.quiescence_evidence_sha256
            )
        return value


def build_runtime_handle_record(
    request: RuntimeExecutionRequest,
    *,
    handle_id: str,
    registry: RuntimeAdapterContractRegistry | None = None,
) -> RuntimeHandleRecord:
    registry = registry or _RUNTIME_ADAPTER_REGISTRY
    contract = registry.resolve(request.executor_id)
    if contract.runtime_handle_kind is None:
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_FORBIDDEN",
            "executor contract does not use resumable runtime handles",
            details={"executor_id": request.executor_id},
        )
    return RuntimeHandleRecord(
        handle_id=handle_id,
        kind=contract.runtime_handle_kind,
        executor_id=request.executor_id,
        request_id=request.request_id,
        task_id=request.task_id,
        node_instance_id=request.node_instance_id,
        repository_id=request.repository_id,
        attempt=request.attempt,
        availability="available",
    )


def update_runtime_handle(
    record: RuntimeHandleRecord,
    *,
    availability: str,
    quiescence_evidence_sha256: str | None = None,
) -> RuntimeHandleRecord:
    if not isinstance(record, RuntimeHandleRecord):
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_INVALID",
            "runtime handle update requires a validated handle record",
        )
    if record.availability == "quiesced":
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_TERMINAL",
            "a quiesced runtime handle cannot become live again",
        )
    if (
        record.availability == "unavailable"
        and availability == "available"
    ):
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_REATTACH_REQUIRED",
            "an unavailable handle requires explicit reattachment validation",
        )
    return RuntimeHandleRecord(
        handle_id=record.handle_id,
        kind=record.kind,
        executor_id=record.executor_id,
        request_id=record.request_id,
        task_id=record.task_id,
        node_instance_id=record.node_instance_id,
        repository_id=record.repository_id,
        attempt=record.attempt,
        availability=availability,
        quiescence_evidence_sha256=quiescence_evidence_sha256,
    )


def reattach_runtime_handle(
    record: RuntimeHandleRecord,
    *,
    observed_handle_id: str,
) -> RuntimeHandleRecord:
    if record.availability != "unavailable":
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_REATTACH_INVALID",
            "only an unavailable handle may be reattached",
        )
    if observed_handle_id != record.handle_id:
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_REATTACH_MISMATCH",
            "reattached handle identity differs from the recorded handle",
        )
    return RuntimeHandleRecord(
        handle_id=record.handle_id,
        kind=record.kind,
        executor_id=record.executor_id,
        request_id=record.request_id,
        task_id=record.task_id,
        node_instance_id=record.node_instance_id,
        repository_id=record.repository_id,
        attempt=record.attempt,
        availability="available",
    )


@_runtime_adapter_dataclass(frozen=True)
class RuntimeAttemptRecord:
    """Adapter dispatch metadata stored outside durable workflow facts."""

    record_id: str
    executor_id: str
    request_id: str
    task_id: str
    node_instance_id: str
    repository_id: str | None
    attempt: int
    input_sha256: str
    phase: str
    runtime_handle_id: str | None
    quiescence_evidence_sha256: str | None
    schema: str = RUNTIME_ATTEMPT_RECORD_SCHEMA

    def __post_init__(self) -> None:
        for field, value in (
            ("record_id", self.record_id),
            ("executor_id", self.executor_id),
            ("request_id", self.request_id),
            ("task_id", self.task_id),
            ("node_instance_id", self.node_instance_id),
        ):
            _runtime_adapter_require_string(
                value, field, stable_id=True
            )
        if not self.record_id.startswith("runtime-attempt:"):
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_ID_INVALID",
                "runtime attempt record must be content-addressed",
                field="record_id",
            )
        if self.repository_id is not None:
            _runtime_adapter_require_string(
                self.repository_id,
                "repository_id",
                stable_id=True,
            )
        _runtime_adapter_require_int(self.attempt, "attempt", minimum=1)
        _runtime_adapter_require_digest(
            self.input_sha256, "input_sha256"
        )
        if self.phase not in _runtime_adapter_attempt_phases:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_PHASE_INVALID",
                "runtime attempt phase is unsupported",
                field="phase",
            )
        if self.runtime_handle_id is not None:
            _runtime_adapter_require_string(
                self.runtime_handle_id,
                "runtime_handle_id",
                stable_id=True,
            )
        if self.phase == "quiesced":
            _runtime_adapter_require_digest(
                self.quiescence_evidence_sha256,
                "quiescence_evidence_sha256",
            )
        elif self.quiescence_evidence_sha256 is not None:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_PHASE_INVALID",
                "only a quiesced attempt may bind quiescence evidence",
                field="quiescence_evidence_sha256",
            )
        identity_payload = {
            "schema": RUNTIME_ATTEMPT_RECORD_SCHEMA,
            "executor_id": self.executor_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "attempt": self.attempt,
            "input_sha256": self.input_sha256,
        }
        expected_record_id = (
            f"runtime-attempt:{_runtime_adapter_sha256(identity_payload)}"
        )
        if self.record_id != expected_record_id:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_ID_INVALID",
                "runtime attempt identity does not match its canonical fields",
                field="record_id",
            )

    def scope(self) -> tuple[object, ...]:
        return (
            self.executor_id,
            self.task_id,
            self.node_instance_id,
            self.repository_id,
        )

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": self.schema,
            "record_id": self.record_id,
            "executor_id": self.executor_id,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "input_sha256": self.input_sha256,
            "phase": self.phase,
        }
        if self.repository_id is not None:
            value["repository_id"] = self.repository_id
        if self.runtime_handle_id is not None:
            value["runtime_handle_id"] = self.runtime_handle_id
        if self.quiescence_evidence_sha256 is not None:
            value["quiescence_evidence_sha256"] = (
                self.quiescence_evidence_sha256
            )
        return value


def _runtime_adapter_attempt_record_id(
    request: RuntimeExecutionRequest,
) -> str:
    payload = {
        "schema": RUNTIME_ATTEMPT_RECORD_SCHEMA,
        "executor_id": request.executor_id,
        "request_id": request.request_id,
        "task_id": request.task_id,
        "node_instance_id": request.node_instance_id,
        "repository_id": request.repository_id,
        "attempt": request.attempt,
        "input_sha256": request.input_sha256,
    }
    return f"runtime-attempt:{_runtime_adapter_sha256(payload)}"


def build_runtime_attempt_record(
    request: RuntimeExecutionRequest,
    *,
    phase: str = "issued",
    runtime_handle: RuntimeHandleRecord | None = None,
    quiescence_evidence_sha256: str | None = None,
) -> RuntimeAttemptRecord:
    if runtime_handle is not None:
        expected = (
            request.executor_id,
            request.task_id,
            request.node_instance_id,
            request.repository_id,
            request.attempt,
            request.request_id,
        )
        if runtime_handle.binding() != expected:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_BINDING_MISMATCH",
                "runtime handle does not match its exact request",
            )
    return RuntimeAttemptRecord(
        record_id=_runtime_adapter_attempt_record_id(request),
        executor_id=request.executor_id,
        request_id=request.request_id,
        task_id=request.task_id,
        node_instance_id=request.node_instance_id,
        repository_id=request.repository_id,
        attempt=request.attempt,
        input_sha256=request.input_sha256,
        phase=phase,
        runtime_handle_id=(
            None if runtime_handle is None else runtime_handle.handle_id
        ),
        quiescence_evidence_sha256=quiescence_evidence_sha256,
    )


def update_runtime_attempt(
    record: RuntimeAttemptRecord,
    *,
    phase: str,
    runtime_handle: RuntimeHandleRecord | None = None,
    quiescence_evidence_sha256: str | None = None,
) -> RuntimeAttemptRecord:
    if record.phase == "quiesced":
        raise _runtime_adapter_error(
            "RUNTIME_ATTEMPT_TERMINAL",
            "a quiesced runtime attempt cannot become live again",
        )
    handle_id = record.runtime_handle_id
    if runtime_handle is not None:
        expected = (
            record.executor_id,
            record.task_id,
            record.node_instance_id,
            record.repository_id,
            record.attempt,
            record.request_id,
        )
        if runtime_handle.binding() != expected:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_BINDING_MISMATCH",
                "runtime handle does not match its attempt record",
            )
        if handle_id is not None and runtime_handle.handle_id != handle_id:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_REPLACEMENT_FORBIDDEN",
                "a runtime handle cannot be replaced within one attempt",
            )
        handle_id = runtime_handle.handle_id
    return RuntimeAttemptRecord(
        record_id=record.record_id,
        executor_id=record.executor_id,
        request_id=record.request_id,
        task_id=record.task_id,
        node_instance_id=record.node_instance_id,
        repository_id=record.repository_id,
        attempt=record.attempt,
        input_sha256=record.input_sha256,
        phase=phase,
        runtime_handle_id=handle_id,
        quiescence_evidence_sha256=quiescence_evidence_sha256,
    )


class V4RuntimeSettlementEvidence:
    """Opaque controller-owned runtime exit/quiescence observation."""

    __slots__ = ("_authority_marker", "_record_marker")

    def __init__(
        self, authority_marker: object, record_marker: object
    ) -> None:
        self._authority_marker = authority_marker
        self._record_marker = record_marker

    def __repr__(self) -> str:
        return "<V4RuntimeSettlementEvidence opaque>"

    def __copy__(self) -> "V4RuntimeSettlementEvidence":
        raise TypeError("V4 runtime settlement evidence cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "V4RuntimeSettlementEvidence":
        del memo
        raise TypeError("V4 runtime settlement evidence cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError(
            "V4 runtime settlement evidence cannot be serialized"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "V4 runtime settlement evidence cannot be serialized"
        )


class V4TerminalAbandonedAuthority:
    """Opaque terminal ABANDONED authority for one exact prior attempt."""

    __slots__ = ("_authority_marker", "_record_marker")

    def __init__(
        self, authority_marker: object, record_marker: object
    ) -> None:
        self._authority_marker = authority_marker
        self._record_marker = record_marker

    def __repr__(self) -> str:
        return "<V4TerminalAbandonedAuthority opaque>"

    def __copy__(self) -> "V4TerminalAbandonedAuthority":
        raise TypeError("V4 terminal ABANDONED authority cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "V4TerminalAbandonedAuthority":
        del memo
        raise TypeError("V4 terminal ABANDONED authority cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError(
            "V4 terminal ABANDONED authority cannot be serialized"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "V4 terminal ABANDONED authority cannot be serialized"
        )


class V4RuntimeEvidenceAuthority:
    """Issue and authenticate short-lived controller-owned V4 evidence.

    Evidence handles are process-local and cannot be reconstructed from their
    public digest fields.  A restarted controller must authenticate the live
    target again and issue fresh evidence.
    """

    __slots__ = (
        "_authority_marker",
        "_clock",
        "_lock",
        "_settlements",
        "_abandonments",
    )

    def __init__(
        self,
        *,
        monotonic_clock: _RuntimeAdapterCallable[
            [], float
        ] = _runtime_adapter_time.monotonic,
    ) -> None:
        if not callable(monotonic_clock):
            raise TypeError("monotonic_clock must be callable")
        self._authority_marker = object()
        self._clock = monotonic_clock
        self._lock = _runtime_adapter_threading.RLock()
        self._settlements: dict[object, dict[str, object]] = {}
        self._abandonments: dict[object, dict[str, object]] = {}

    def __repr__(self) -> str:
        return "<V4RuntimeEvidenceAuthority opaque>"

    def __copy__(self) -> "V4RuntimeEvidenceAuthority":
        raise TypeError("V4 runtime evidence authority cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "V4RuntimeEvidenceAuthority":
        del memo
        raise TypeError("V4 runtime evidence authority cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError(
            "V4 runtime evidence authority cannot be serialized"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "V4 runtime evidence authority cannot be serialized"
        )

    def _now_ns(self) -> int:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not _runtime_adapter_math.isfinite(float(value))
            or value < 0
        ):
            raise _runtime_adapter_error(
                "V4_RUNTIME_EVIDENCE_CLOCK_INVALID",
                "controller evidence clock returned an invalid value",
            )
        return int(float(value) * 1_000_000_000)

    @staticmethod
    def _expiry_ns(now_ns: int, ttl_seconds: int) -> int:
        _runtime_adapter_require_int(
            ttl_seconds, "ttl_seconds", minimum=1
        )
        if ttl_seconds > _V4_RUNTIME_EVIDENCE_MAX_TTL_SECONDS:
            raise _runtime_adapter_error(
                "V4_RUNTIME_EVIDENCE_TTL_INVALID",
                "controller evidence lifetime exceeds its safety bound",
                field="ttl_seconds",
                details={
                    "maximum": _V4_RUNTIME_EVIDENCE_MAX_TTL_SECONDS
                },
            )
        return now_ns + ttl_seconds * 1_000_000_000

    @staticmethod
    def _identity(
        *,
        task_id: object,
        execution_id: object,
        effect_id: object,
        claim_id: object,
        attempt_id: object,
        runtime_attempt: object,
        executor_id: object,
        request_id: object,
        node_instance_id: object,
        repository_id: object,
        runtime_handle_sha256: object,
        containment_record_sha256: object,
        runtime_reservation_record_sha256: object,
    ) -> dict[str, object]:
        return {
            "task_id": _runtime_adapter_require_string(
                task_id, "task_id", stable_id=True
            ),
            "execution_id": _runtime_adapter_require_string(
                execution_id, "execution_id", stable_id=True
            ),
            "effect_id": _runtime_adapter_require_string(
                effect_id, "effect_id", stable_id=True
            ),
            "claim_id": _runtime_adapter_require_string(
                claim_id, "claim_id", stable_id=True
            ),
            "attempt_id": _runtime_adapter_require_string(
                attempt_id, "attempt_id", stable_id=True
            ),
            "runtime_attempt": _runtime_adapter_require_int(
                runtime_attempt, "runtime_attempt", minimum=1
            ),
            "executor_id": _runtime_adapter_require_string(
                executor_id, "executor_id", stable_id=True
            ),
            "request_id": _runtime_adapter_require_string(
                request_id, "request_id", stable_id=True
            ),
            "node_instance_id": _runtime_adapter_require_string(
                node_instance_id, "node_instance_id", stable_id=True
            ),
            "repository_id": (
                None
                if repository_id is None
                else _runtime_adapter_require_string(
                    repository_id,
                    "repository_id",
                    stable_id=True,
                )
            ),
            "runtime_handle_sha256": _runtime_adapter_require_digest(
                runtime_handle_sha256, "runtime_handle_sha256"
            ),
            "containment_record_sha256": (
                _runtime_adapter_require_digest(
                    containment_record_sha256,
                    "containment_record_sha256",
                )
            ),
            "runtime_reservation_record_sha256": (
                _runtime_adapter_require_digest(
                    runtime_reservation_record_sha256,
                    "runtime_reservation_record_sha256",
                )
            ),
        }

    def issue_settlement(
        self,
        *,
        task_id: str,
        execution_id: str,
        effect_id: str,
        claim_id: str,
        attempt_id: str,
        runtime_attempt: int,
        executor_id: str,
        request_id: str,
        node_instance_id: str,
        repository_id: str | None,
        runtime_handle_sha256: str,
        containment_record_sha256: str,
        runtime_reservation_record_sha256: str,
        settlement: str,
        runtime_exit_or_quiescence_sha256: str,
        authoritative_event: object,
        ttl_seconds: int = 60,
    ) -> V4RuntimeSettlementEvidence:
        """Bind a fresh target observation to one exact durable reservation."""

        identity = self._identity(
            task_id=task_id,
            execution_id=execution_id,
            effect_id=effect_id,
            claim_id=claim_id,
            attempt_id=attempt_id,
            runtime_attempt=runtime_attempt,
            executor_id=executor_id,
            request_id=request_id,
            node_instance_id=node_instance_id,
            repository_id=repository_id,
            runtime_handle_sha256=runtime_handle_sha256,
            containment_record_sha256=containment_record_sha256,
            runtime_reservation_record_sha256=(
                runtime_reservation_record_sha256
            ),
        )
        if settlement not in _runtime_adapter_v4_settlements:
            raise _runtime_adapter_error(
                "V4_RUNTIME_SETTLEMENT_INVALID",
                "V4 runtime evidence requires EXITED or QUIESCED",
                field="settlement",
            )
        now_ns = self._now_ns()
        payload = {
            "schema": V4_RUNTIME_SETTLEMENT_EVIDENCE_SCHEMA,
            **identity,
            "settlement": settlement,
            "runtime_exit_or_quiescence_sha256": (
                _runtime_adapter_require_digest(
                    runtime_exit_or_quiescence_sha256,
                    "runtime_exit_or_quiescence_sha256",
                )
            ),
            "result_event_sha256": v4_runtime_result_event_sha256(
                authoritative_event
            ),
            "observed_at_ns": now_ns,
            "expires_at_ns": self._expiry_ns(now_ns, ttl_seconds),
        }
        payload["evidence_sha256"] = _runtime_adapter_domain_sha256(
            _V4_RUNTIME_SETTLEMENT_EVIDENCE_DOMAIN, payload
        )
        record_marker = object()
        with self._lock:
            self._settlements[record_marker] = payload
        return V4RuntimeSettlementEvidence(
            self._authority_marker, record_marker
        )

    def _settlement_record(
        self, evidence: object
    ) -> dict[str, object]:
        if (
            type(evidence) is not V4RuntimeSettlementEvidence
            or evidence._authority_marker is not self._authority_marker
        ):
            raise _runtime_adapter_error(
                "V4_RUNTIME_EVIDENCE_INVALID",
                "runtime evidence was not issued by this controller authority",
            )
        with self._lock:
            record = self._settlements.get(evidence._record_marker)
            if record is None:
                raise _runtime_adapter_error(
                    "V4_RUNTIME_EVIDENCE_INVALID",
                    "runtime evidence is unknown to this controller authority",
                )
            if self._now_ns() >= int(record["expires_at_ns"]):
                raise _runtime_adapter_error(
                    "V4_RUNTIME_EVIDENCE_EXPIRED",
                    "runtime evidence expired before it was authenticated",
                )
            return dict(record)

    def authenticate_settlement(
        self, evidence: object
    ) -> dict[str, object]:
        """Return authenticated public bindings for a live opaque handle."""

        return self._settlement_record(evidence)

    def issue_terminal_abandoned(
        self,
        settlement_evidence: object,
        *,
        terminal_reconciliation_record_sha256: str,
        no_accepted_outcome_evidence_sha256: str,
        authorization_sha256: str,
    ) -> V4TerminalAbandonedAuthority:
        """Bind terminal ABANDONED authorization to fresh quiescence."""

        settlement = self._settlement_record(settlement_evidence)
        if settlement["settlement"] != "QUIESCED":
            raise _runtime_adapter_error(
                "V4_RUNTIME_ABANDONED_NOT_QUIESCED",
                "terminal ABANDONED authority requires fresh quiescence",
            )
        payload = {
            "schema": V4_RUNTIME_ABANDONED_AUTHORITY_SCHEMA,
            **{
                field: settlement[field]
                for field in (
                    "task_id",
                    "execution_id",
                    "effect_id",
                    "claim_id",
                    "attempt_id",
                    "runtime_attempt",
                    "executor_id",
                    "request_id",
                    "node_instance_id",
                    "repository_id",
                    "runtime_handle_sha256",
                    "containment_record_sha256",
                    "runtime_reservation_record_sha256",
                    "runtime_exit_or_quiescence_sha256",
                )
            },
            "decision": "ABANDONED",
            "settlement_evidence_sha256": settlement[
                "evidence_sha256"
            ],
            "terminal_reconciliation_record_sha256": (
                _runtime_adapter_require_digest(
                    terminal_reconciliation_record_sha256,
                    "terminal_reconciliation_record_sha256",
                )
            ),
            "no_accepted_outcome_evidence_sha256": (
                _runtime_adapter_require_digest(
                    no_accepted_outcome_evidence_sha256,
                    "no_accepted_outcome_evidence_sha256",
                )
            ),
            "authorization_sha256": _runtime_adapter_require_digest(
                authorization_sha256, "authorization_sha256"
            ),
            "observed_at_ns": settlement["observed_at_ns"],
            "expires_at_ns": settlement["expires_at_ns"],
        }
        payload["authority_sha256"] = _runtime_adapter_domain_sha256(
            _V4_RUNTIME_ABANDONED_AUTHORITY_DOMAIN, payload
        )
        record_marker = object()
        with self._lock:
            self._abandonments[record_marker] = payload
        return V4TerminalAbandonedAuthority(
            self._authority_marker, record_marker
        )

    def _abandoned_record(
        self, authority: object
    ) -> dict[str, object]:
        if (
            type(authority) is not V4TerminalAbandonedAuthority
            or authority._authority_marker is not self._authority_marker
        ):
            raise _runtime_adapter_error(
                "V4_RUNTIME_ABANDONED_AUTHORITY_INVALID",
                "terminal ABANDONED authority was not issued by this controller",
            )
        with self._lock:
            record = self._abandonments.get(authority._record_marker)
            if record is None:
                raise _runtime_adapter_error(
                    "V4_RUNTIME_ABANDONED_AUTHORITY_INVALID",
                    "terminal ABANDONED authority is unknown",
                )
            if self._now_ns() >= int(record["expires_at_ns"]):
                raise _runtime_adapter_error(
                    "V4_RUNTIME_ABANDONED_AUTHORITY_EXPIRED",
                    "terminal ABANDONED authority is no longer fresh",
                )
            return dict(record)

    def authenticate_terminal_abandoned(
        self, authority: object
    ) -> dict[str, object]:
        """Authenticate one exact, fresh terminal ABANDONED authority."""

        return self._abandoned_record(authority)


@_runtime_adapter_dataclass(frozen=True)
class RuntimeReplacementProof:
    proof_id: str
    task_id: str
    node_instance_id: str
    repository_id: str | None
    executor_id: str
    previous_attempt: int
    next_attempt: int
    previous_request_id: str
    quiescence_evidence_sha256: str
    authorization_sha256: str
    reason: str
    schema: str = RUNTIME_REPLACEMENT_PROOF_SCHEMA

    def __post_init__(self) -> None:
        for field, value in (
            ("proof_id", self.proof_id),
            ("task_id", self.task_id),
            ("node_instance_id", self.node_instance_id),
            ("executor_id", self.executor_id),
            ("previous_request_id", self.previous_request_id),
        ):
            _runtime_adapter_require_string(
                value, field, stable_id=True
            )
        if not self.proof_id.startswith("runtime-replacement:"):
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_PROOF_INVALID",
                "replacement proof identity must be content-addressed",
                field="proof_id",
            )
        if self.repository_id is not None:
            _runtime_adapter_require_string(
                self.repository_id,
                "repository_id",
                stable_id=True,
            )
        _runtime_adapter_require_int(
            self.previous_attempt, "previous_attempt", minimum=1
        )
        _runtime_adapter_require_int(
            self.next_attempt, "next_attempt", minimum=2
        )
        if self.next_attempt != self.previous_attempt + 1:
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_PROOF_INVALID",
                "replacement proof must bind the immediately next attempt",
            )
        _runtime_adapter_require_digest(
            self.quiescence_evidence_sha256,
            "quiescence_evidence_sha256",
        )
        _runtime_adapter_require_digest(
            self.authorization_sha256, "authorization_sha256"
        )
        if self.reason not in _runtime_adapter_replacement_reasons:
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_PROOF_INVALID",
                "replacement reason is unsupported",
                field="reason",
            )
        identity_payload = {
            "schema": RUNTIME_REPLACEMENT_PROOF_SCHEMA,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "executor_id": self.executor_id,
            "previous_attempt": self.previous_attempt,
            "next_attempt": self.next_attempt,
            "previous_request_id": self.previous_request_id,
            "quiescence_evidence_sha256": (
                self.quiescence_evidence_sha256
            ),
            "authorization_sha256": self.authorization_sha256,
            "reason": self.reason,
        }
        expected_proof_id = (
            "runtime-replacement:"
            + _runtime_adapter_sha256(identity_payload)
        )
        if self.proof_id != expected_proof_id:
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_PROOF_INVALID",
                "replacement proof identity does not match its fields",
                field="proof_id",
            )

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": self.schema,
            "proof_id": self.proof_id,
            "task_id": self.task_id,
            "node_instance_id": self.node_instance_id,
            "executor_id": self.executor_id,
            "previous_attempt": self.previous_attempt,
            "next_attempt": self.next_attempt,
            "previous_request_id": self.previous_request_id,
            "quiescence_evidence_sha256": (
                self.quiescence_evidence_sha256
            ),
            "authorization_sha256": self.authorization_sha256,
            "reason": self.reason,
        }
        if self.repository_id is not None:
            value["repository_id"] = self.repository_id
        return value


def build_runtime_replacement_proof(
    previous: RuntimeAttemptRecord,
    *,
    next_attempt: int,
    authorization_sha256: str,
    reason: str,
) -> RuntimeReplacementProof:
    """Bind controller-validated authorization to a quiesced prior attempt."""

    if previous.phase != "quiesced":
        raise _runtime_adapter_error(
            "RUNTIME_REPLACEMENT_NOT_QUIESCED",
            "replacement proof requires a quiesced prior attempt",
        )
    quiescence = _runtime_adapter_require_digest(
        previous.quiescence_evidence_sha256,
        "quiescence_evidence_sha256",
    )
    authorization = _runtime_adapter_require_digest(
        authorization_sha256, "authorization_sha256"
    )
    payload = {
        "schema": RUNTIME_REPLACEMENT_PROOF_SCHEMA,
        "task_id": previous.task_id,
        "node_instance_id": previous.node_instance_id,
        "repository_id": previous.repository_id,
        "executor_id": previous.executor_id,
        "previous_attempt": previous.attempt,
        "next_attempt": next_attempt,
        "previous_request_id": previous.request_id,
        "quiescence_evidence_sha256": quiescence,
        "authorization_sha256": authorization,
        "reason": reason,
    }
    return RuntimeReplacementProof(
        proof_id=f"runtime-replacement:{_runtime_adapter_sha256(payload)}",
        task_id=previous.task_id,
        node_instance_id=previous.node_instance_id,
        repository_id=previous.repository_id,
        executor_id=previous.executor_id,
        previous_attempt=previous.attempt,
        next_attempt=next_attempt,
        previous_request_id=previous.request_id,
        quiescence_evidence_sha256=quiescence,
        authorization_sha256=authorization,
        reason=reason,
    )


def build_v4_runtime_replacement_proof(
    previous: RuntimeAttemptRecord,
    *,
    next_attempt: int,
    evidence_authority: V4RuntimeEvidenceAuthority,
    terminal_abandoned_authority: V4TerminalAbandonedAuthority,
) -> RuntimeReplacementProof:
    """Build a V4 replacement proof only from terminal ABANDONED authority."""

    if type(evidence_authority) is not V4RuntimeEvidenceAuthority:
        raise _runtime_adapter_error(
            "V4_RUNTIME_ABANDONED_AUTHORITY_REQUIRED",
            "V4 replacement requires the controller evidence authority",
        )
    abandoned = evidence_authority.authenticate_terminal_abandoned(
        terminal_abandoned_authority
    )
    if (
        type(previous) is not RuntimeAttemptRecord
        or previous.phase != "quiesced"
        or abandoned["decision"] != "ABANDONED"
        or abandoned["task_id"] != previous.task_id
        or abandoned["runtime_attempt"] != previous.attempt
        or abandoned["executor_id"] != previous.executor_id
        or abandoned["request_id"] != previous.request_id
        or abandoned["node_instance_id"] != previous.node_instance_id
        or abandoned["repository_id"] != previous.repository_id
        or abandoned["runtime_exit_or_quiescence_sha256"]
        != previous.quiescence_evidence_sha256
    ):
        raise _runtime_adapter_error(
            "V4_RUNTIME_ABANDONED_AUTHORITY_MISMATCH",
            "terminal ABANDONED authority differs from the prior attempt",
        )
    return build_runtime_replacement_proof(
        previous,
        next_attempt=next_attempt,
        authorization_sha256=str(abandoned["authority_sha256"]),
        reason="recovery",
    )


@_runtime_adapter_dataclass(frozen=True)
class RuntimeDispatchDecision:
    action: str
    request_id: str
    attempt: int
    runtime_handle_id: str | None
    replaced_attempt: int | None
    schema: str = RUNTIME_DISPATCH_DECISION_SCHEMA

    def __post_init__(self) -> None:
        if self.action not in {"start", "resume", "replace"}:
            raise _runtime_adapter_error(
                "RUNTIME_DISPATCH_DECISION_INVALID",
                "runtime dispatch decision is unsupported",
                field="action",
            )

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": self.schema,
            "action": self.action,
            "request_id": self.request_id,
            "attempt": self.attempt,
        }
        if self.runtime_handle_id is not None:
            value["runtime_handle_id"] = self.runtime_handle_id
        if self.replaced_attempt is not None:
            value["replaced_attempt"] = self.replaced_attempt
        return value


def plan_runtime_dispatch(
    request: RuntimeExecutionRequest,
    *,
    attempts: _RuntimeAdapterSequence[RuntimeAttemptRecord] = (),
    handles: _RuntimeAdapterSequence[RuntimeHandleRecord] = (),
    replacement_proof: RuntimeReplacementProof | None = None,
    registry: RuntimeAdapterContractRegistry | None = None,
) -> RuntimeDispatchDecision:
    """Fail closed unless a start, exact resume, or proven replacement is safe."""

    registry = registry or _RUNTIME_ADAPTER_REGISTRY
    contract = registry.resolve(request.executor_id)
    expected_scope = (
        request.executor_id,
        request.task_id,
        request.node_instance_id,
        request.repository_id,
    )
    for record in attempts:
        if not isinstance(record, RuntimeAttemptRecord):
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_RECORD_INVALID",
                "dispatch history contains an unvalidated attempt record",
            )
        if record.scope() != expected_scope:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_SCOPE_MISMATCH",
                "dispatch history belongs to another executor scope",
            )
    attempt_numbers = [record.attempt for record in attempts]
    if len(attempt_numbers) != len(set(attempt_numbers)):
        raise _runtime_adapter_error(
            "RUNTIME_DUPLICATE_ATTEMPT",
            "dispatch history contains duplicate attempt generations",
        )
    ordered_attempts = tuple(
        sorted(attempts, key=lambda item: item.attempt)
    )
    if ordered_attempts:
        expected_numbers = tuple(
            range(1, ordered_attempts[-1].attempt + 1)
        )
        if tuple(item.attempt for item in ordered_attempts) != expected_numbers:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_HISTORY_INVALID",
                "runtime attempt history must be consecutive from one",
            )
    handle_by_id: dict[str, RuntimeHandleRecord] = {}
    for handle in handles:
        if not isinstance(handle, RuntimeHandleRecord):
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_INVALID",
                "dispatch history contains an unvalidated runtime handle",
            )
        if handle.handle_id in handle_by_id:
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_DUPLICATE",
                "runtime handle identity is duplicated",
                details={"handle_id": handle.handle_id},
            )
        if handle.binding()[:4] != (
            request.executor_id,
            request.task_id,
            request.node_instance_id,
            request.repository_id,
        ):
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_SCOPE_MISMATCH",
                "runtime handle belongs to another executor scope",
            )
        if (
            contract.runtime_handle_kind is None
            or handle.kind != contract.runtime_handle_kind
        ):
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_KIND_MISMATCH",
                "runtime handle kind is incompatible with its executor",
                details={
                    "expected": contract.runtime_handle_kind,
                    "actual": handle.kind,
                },
            )
        handle_by_id[handle.handle_id] = handle
    referenced_handle_ids = {
        record.runtime_handle_id
        for record in ordered_attempts
        if record.runtime_handle_id is not None
    }
    orphan_ids = sorted(
        set(handle_by_id) - referenced_handle_ids,
        key=lambda item: item.encode("utf-8"),
    )
    if orphan_ids:
        raise _runtime_adapter_error(
            "RUNTIME_ORPHAN_HANDLE",
            "unattached runtime handles require reconciliation before dispatch",
            details={"handle_ids": orphan_ids},
        )
    missing_handle_ids = sorted(
        referenced_handle_ids - set(handle_by_id),
        key=lambda item: item.encode("utf-8"),
    )
    if missing_handle_ids:
        raise _runtime_adapter_error(
            "RUNTIME_HANDLE_UNAVAILABLE",
            "attempt references a runtime handle that is not available",
            details={"handle_ids": missing_handle_ids},
        )
    same_attempt = next(
        (
            record
            for record in ordered_attempts
            if record.attempt == request.attempt
        ),
        None,
    )
    if same_attempt is not None:
        if same_attempt.request_id != request.request_id:
            raise _runtime_adapter_error(
                "RUNTIME_DUPLICATE_ATTEMPT_CONFLICT",
                "attempt generation is already bound to a different request",
                details={"attempt": request.attempt},
            )
        if replacement_proof is not None:
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_SAME_ATTEMPT_FORBIDDEN",
                "replacement cannot reuse an existing attempt generation",
            )
        if same_attempt.phase == "quiesced":
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_QUIESCED",
                "a quiesced attempt cannot be resumed or redispatched",
            )
        if same_attempt.runtime_handle_id is None:
            raise _runtime_adapter_error(
                "RUNTIME_DUPLICATE_ATTEMPT",
                "recorded attempt without a resumable handle cannot be redispatched",
                details={"attempt": request.attempt},
            )
        handle = handle_by_id[same_attempt.runtime_handle_id]
        if handle.binding() != (
            request.executor_id,
            request.task_id,
            request.node_instance_id,
            request.repository_id,
            request.attempt,
            request.request_id,
        ):
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_BINDING_MISMATCH",
                "runtime handle does not match the recorded request",
            )
        if not contract.supports_resume:
            raise _runtime_adapter_error(
                "RUNTIME_RESUME_UNSUPPORTED",
                "executor contract does not support same-attempt resume",
            )
        if handle.availability == "unavailable":
            raise _runtime_adapter_error(
                "RUNTIME_HANDLE_UNAVAILABLE",
                "runtime handle cannot currently be resumed",
                details={"handle_id": handle.handle_id},
            )
        if handle.availability == "quiesced":
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_QUIESCED",
                "quiesced runtime handle cannot be resumed",
            )
        return RuntimeDispatchDecision(
            action="resume",
            request_id=request.request_id,
            attempt=request.attempt,
            runtime_handle_id=handle.handle_id,
            replaced_attempt=None,
        )
    if not ordered_attempts:
        if request.attempt != 1:
            raise _runtime_adapter_error(
                "RUNTIME_ATTEMPT_HISTORY_INVALID",
                "first runtime dispatch must use attempt one",
            )
        if replacement_proof is not None:
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_PROOF_UNEXPECTED",
                "initial dispatch cannot carry a replacement proof",
            )
        return RuntimeDispatchDecision(
            action="start",
            request_id=request.request_id,
            attempt=request.attempt,
            runtime_handle_id=None,
            replaced_attempt=None,
        )
    previous = ordered_attempts[-1]
    if request.attempt != previous.attempt + 1:
        raise _runtime_adapter_error(
            "RUNTIME_ATTEMPT_HISTORY_INVALID",
            "new dispatch must use the immediately next attempt generation",
            details={"expected": previous.attempt + 1},
        )
    if previous.phase != "quiesced":
        raise _runtime_adapter_error(
            "RUNTIME_REPLACEMENT_NOT_QUIESCED",
            "replacement is forbidden until the prior attempt is quiesced",
            details={"phase": previous.phase},
        )
    if replacement_proof is None:
        raise _runtime_adapter_error(
            "RUNTIME_REPLACEMENT_PROOF_REQUIRED",
            "replacement requires explicit controller authorization",
        )
    expected_proof = (
        request.task_id,
        request.node_instance_id,
        request.repository_id,
        request.executor_id,
        previous.attempt,
        request.attempt,
        previous.request_id,
        previous.quiescence_evidence_sha256,
    )
    actual_proof = (
        replacement_proof.task_id,
        replacement_proof.node_instance_id,
        replacement_proof.repository_id,
        replacement_proof.executor_id,
        replacement_proof.previous_attempt,
        replacement_proof.next_attempt,
        replacement_proof.previous_request_id,
        replacement_proof.quiescence_evidence_sha256,
    )
    if actual_proof != expected_proof:
        raise _runtime_adapter_error(
            "RUNTIME_REPLACEMENT_PROOF_MISMATCH",
            "replacement proof does not match the prior and next attempts",
        )
    if previous.runtime_handle_id is not None:
        previous_handle = handle_by_id[previous.runtime_handle_id]
        if (
            previous_handle.availability != "quiesced"
            or previous_handle.quiescence_evidence_sha256
            != previous.quiescence_evidence_sha256
        ):
            raise _runtime_adapter_error(
                "RUNTIME_REPLACEMENT_NOT_QUIESCED",
                "attempt and runtime handle lack matching quiescence evidence",
            )
    return RuntimeDispatchDecision(
        action="replace",
        request_id=request.request_id,
        attempt=request.attempt,
        runtime_handle_id=None,
        replaced_attempt=previous.attempt,
    )


def plan_v4_runtime_dispatch(
    request: RuntimeExecutionRequest,
    *,
    attempts: _RuntimeAdapterSequence[RuntimeAttemptRecord] = (),
    handles: _RuntimeAdapterSequence[RuntimeHandleRecord] = (),
    replacement_proof: RuntimeReplacementProof | None = None,
    evidence_authority: V4RuntimeEvidenceAuthority | None = None,
    terminal_abandoned_authority: (
        V4TerminalAbandonedAuthority | None
    ) = None,
    registry: RuntimeAdapterContractRegistry | None = None,
) -> RuntimeDispatchDecision:
    """Apply V4's terminal-ABANDONED gate to every new attempt.

    Initial dispatch and exact same-attempt resume retain the pure adapter
    behavior.  A next generation is forbidden unless a fresh opaque authority
    for the exact prior attempt remains authenticated at planning time.
    """

    same_attempt = any(
        type(record) is RuntimeAttemptRecord
        and record.attempt == request.attempt
        for record in attempts
    )
    if any(
        type(record) is not RuntimeAttemptRecord for record in attempts
    ):
        raise _runtime_adapter_error(
            "RUNTIME_ATTEMPT_RECORD_INVALID",
            "dispatch history contains an unvalidated attempt record",
        )
    replacement_requested = bool(attempts) and not same_attempt
    if replacement_requested:
        if (
            type(replacement_proof) is not RuntimeReplacementProof
            or type(evidence_authority)
            is not V4RuntimeEvidenceAuthority
            or type(terminal_abandoned_authority)
            is not V4TerminalAbandonedAuthority
        ):
            raise _runtime_adapter_error(
                "V4_RUNTIME_ABANDONED_AUTHORITY_REQUIRED",
                "V4 new attempts require fresh terminal ABANDONED authority",
            )
        abandoned = (
            evidence_authority.authenticate_terminal_abandoned(
                terminal_abandoned_authority
            )
        )
        previous = max(attempts, key=lambda item: item.attempt)
        if (
            abandoned["decision"] != "ABANDONED"
            or abandoned["task_id"] != request.task_id
            or abandoned["runtime_attempt"] != previous.attempt
            or abandoned["executor_id"] != previous.executor_id
            or abandoned["request_id"] != previous.request_id
            or abandoned["node_instance_id"] != previous.node_instance_id
            or abandoned["repository_id"] != previous.repository_id
            or abandoned["runtime_exit_or_quiescence_sha256"]
            != previous.quiescence_evidence_sha256
            or replacement_proof.authorization_sha256
            != abandoned["authority_sha256"]
        ):
            raise _runtime_adapter_error(
                "V4_RUNTIME_ABANDONED_AUTHORITY_MISMATCH",
                "V4 replacement authority differs from its request or prior attempt",
            )
    elif (
        evidence_authority is not None
        or terminal_abandoned_authority is not None
    ):
        raise _runtime_adapter_error(
            "V4_RUNTIME_ABANDONED_AUTHORITY_UNEXPECTED",
            "terminal ABANDONED authority is valid only for a new attempt",
        )
    return plan_runtime_dispatch(
        request,
        attempts=attempts,
        handles=handles,
        replacement_proof=replacement_proof,
        registry=registry,
    )


__all__ = [
    "CODEX_EXEC_CANDIDATE_PROFILE",
    "CODEX_EXEC_EVENT_BUDGET",
    "CODEX_EXEC_EVENT_PROTOCOL",
    "CODEX_EXEC_INVOCATION_SCHEMA",
    "CODEX_EXEC_JSONL_BUDGET",
    "CODEX_EXEC_LINE_BUDGET",
    "CODEX_EXEC_PROMPT_BUDGET",
    "CODEX_EXEC_RESULT_SCHEMA",
    "CODEX_EXEC_RESULT_CANDIDATE_SCHEMA",
    "CodexExecInvocation",
    "CodexExecResult",
    "ExecutorAdapterContract",
    "NodeResultAdapterProfile",
    "ORCHESTRATION_NODE_RESULT_PROFILE",
    "RUNTIME_ADAPTER_CONTRACT_SCHEMA",
    "RUNTIME_ATTEMPT_RECORD_SCHEMA",
    "RUNTIME_DISPATCH_DECISION_SCHEMA",
    "RUNTIME_EXECUTION_REQUEST_SCHEMA",
    "RUNTIME_HANDLE_RECORD_SCHEMA",
    "RUNTIME_HANDLE_SCHEMA",
    "RUNTIME_REPLACEMENT_PROOF_SCHEMA",
    "V4_RUNTIME_ABANDONED_AUTHORITY_SCHEMA",
    "V4_RUNTIME_SETTLEMENT_EVIDENCE_SCHEMA",
    "RuntimeAdapterContractRegistry",
    "RuntimeAdapterError",
    "RuntimeAttemptRecord",
    "RuntimeDispatchDecision",
    "RuntimeExecutionRequest",
    "RuntimeHandleRecord",
    "RuntimeReplacementProof",
    "V4RuntimeEvidenceAuthority",
    "V4RuntimeSettlementEvidence",
    "V4TerminalAbandonedAuthority",
    "build_codex_exec_invocation",
    "build_runtime_adapter_registry",
    "build_runtime_attempt_record",
    "build_runtime_execution_request",
    "build_runtime_handle_record",
    "build_runtime_replacement_proof",
    "build_v4_runtime_replacement_proof",
    "canonical_runtime_adapter_bytes",
    "codex_exec_result_candidate_schema",
    "parse_codex_exec_jsonl",
    "plan_runtime_dispatch",
    "plan_v4_runtime_dispatch",
    "reattach_runtime_handle",
    "runtime_adapter_contracts",
    "update_runtime_attempt",
    "update_runtime_handle",
    "validate_codex_exec_result_candidate",
    "v4_runtime_result_event_sha256",
]
