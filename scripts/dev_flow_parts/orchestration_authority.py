# Loaded by scripts/dev_flow.py only after orchestration integration is ready.
# This first-wave module is deliberately pure: callers supply randomness,
# clocks, trusted-host configuration, persisted records, and atomic storage.
# It performs no filesystem, Git, process, network, or controller mutation.
from __future__ import annotations

import hashlib
import hmac
import json
import re
import struct
import unicodedata
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Optional, Sequence, Tuple, Union


WORKER_ASSIGNMENT_SCHEMA = "dev-flow-worker-assignment/v1"
WORKER_LEASE_SCHEMA = "dev-flow-worker-lease/v1"
WORKER_LEASE_CREDENTIAL_SCHEMA = (
    "dev-flow-worker-lease-credential/v1"
)
MANAGER_CAPABILITY_SCHEMA = (
    "dev-flow-manager-capability-verifier/v1"
)
MANAGER_CAPABILITY_REQUEST_SCHEMA = (
    "dev-flow-manager-capability-request/v1"
)
AGENT_PRINCIPAL_SCHEMA = "dev-flow-agent-principal/v1"
HOST_CAPABILITY_REPORT_SCHEMA = (
    "dev-flow-host-capability-report/v1"
)
HOST_ISOLATION_DECISION_SCHEMA = (
    "dev-flow-host-isolation-decision/v1"
)
MANAGER_AUTHORIZATION_SCHEMA = (
    "dev-flow-manager-authorization/v1"
)

MAX_MANAGER_CAPABILITY_TTL_NS = 15 * 60 * 1_000_000_000
MAX_WORKER_LEASE_TTL_NS = 24 * 60 * 60 * 1_000_000_000
MIN_MANAGER_SECRET_BYTES = 32
MIN_LEASE_NONCE_BYTES = 32

WORKER_WRITE_POLICIES = frozenset({"read-only", "scoped-write"})
WORKER_EXECUTOR_CAPABILITIES = frozenset(
    {
        "artifact.read/v1",
        "playbook.read/v1",
        "process.run-approved/v1",
        "repository.read/v1",
        "repository.write-approved/v1",
        "result.emit-candidate/v1",
    }
)
WORKER_LEASE_STATES = frozenset({"ACTIVE", "REVOKED", "EXPIRED"})
AGENT_PRINCIPAL_ROLES = frozenset({"manager", "worker", "operator"})
MANAGER_SECRET_TRANSPORTS = frozenset(
    {"local-secret-channel", "mcp-secret-channel"}
)

_authority_signed_int64_min = -(2**63)
_authority_signed_int64_max = 2**63 - 1
_authority_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_authority_stable_id_re = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$"
)
_authority_request_nonce_re = re.compile(r"^[0-9a-f]{64}$")
_authority_assignment_domain = b"dev-flow-worker-assignment-v1\x00"
_authority_lease_domain = b"dev-flow-worker-lease-v1\x00"
_authority_lease_credential_domain = (
    b"dev-flow-worker-lease-credential-v1\x00"
)
_authority_capability_verifier_domain = (
    b"dev-flow-manager-capability-verifier-v1\x00"
)
_authority_capability_id_domain = (
    b"dev-flow-manager-capability-id-v1\x00"
)
_authority_request_domain = (
    b"dev-flow-manager-capability-request-v1\x00"
)
_authority_request_nonce_domain = (
    b"dev-flow-manager-capability-request-nonce-v1\x00"
)
_authority_authorization_domain = (
    b"dev-flow-manager-authorization-v1\x00"
)


class OrchestrationAuthorityError(ValueError):
    """Stable structured failure from the pure orchestration boundary."""

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


def _authority_error(
    code: str,
    message: str,
    *,
    pointer: str = "/",
    details: Optional[Mapping[str, object]] = None,
) -> OrchestrationAuthorityError:
    result = {"pointer": pointer}
    result.update(details or {})
    return OrchestrationAuthorityError(code, message, details=result)


def _authority_u64be(value: int) -> bytes:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= 2**64
    ):
        raise _authority_error(
            "ORCHESTRATION_U64_INVALID",
            "value does not fit unsigned 64-bit big-endian encoding",
            details={"value": value if isinstance(value, int) else None},
        )
    return struct.pack(">Q", value)


def _authority_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _authority_utf8_key(value: str) -> bytes:
    return value.encode("utf-8", errors="strict")


def _authority_validate_json_value(
    value: object, pointer: str = ""
) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not (
            _authority_signed_int64_min
            <= value
            <= _authority_signed_int64_max
        ):
            raise _authority_error(
                "ORCHESTRATION_JSON_INTEGER_OUT_OF_RANGE",
                "JSON integers must fit the signed 64-bit range",
                pointer=pointer or "/",
            )
        return
    if isinstance(value, float):
        raise _authority_error(
            "ORCHESTRATION_JSON_FLOAT_FORBIDDEN",
            "JSON floating-point values are forbidden",
            pointer=pointer or "/",
        )
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise _authority_error(
                "ORCHESTRATION_JSON_UNICODE_INVALID",
                "JSON strings must be valid UTF-8",
                pointer=pointer or "/",
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise _authority_error(
                "ORCHESTRATION_JSON_STRING_NOT_NFC",
                "JSON strings must be NFC",
                pointer=pointer or "/",
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _authority_error(
                    "ORCHESTRATION_JSON_KEY_INVALID",
                    "JSON object keys must be strings",
                    pointer=pointer or "/",
                )
            child = f"{pointer}/{_authority_pointer_segment(key)}"
            _authority_validate_json_value(key, child)
            _authority_validate_json_value(item, child)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _authority_validate_json_value(item, f"{pointer}/{index}")
        return
    raise _authority_error(
        "ORCHESTRATION_JSON_VALUE_INVALID",
        "contract values must be canonical JSON values",
        pointer=pointer or "/",
        details={"type": type(value).__name__},
    )


def _authority_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _authority_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_authority_thaw(item) for item in value]
    return value


def canonical_orchestration_bytes(value: object) -> bytes:
    """Return strict canonical JSON bytes for an authority contract."""

    _authority_validate_json_value(value)
    try:
        return json.dumps(
            _authority_thaw(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise OrchestrationAuthorityError(
            "ORCHESTRATION_JSON_CANONICALIZATION_FAILED",
            "authority contract cannot be canonically encoded",
        ) from exc


def _authority_digest(domain: bytes, value: object) -> str:
    payload = canonical_orchestration_bytes(value)
    return hashlib.sha256(
        domain + _authority_u64be(len(payload)) + payload
    ).hexdigest()


def _authority_require_mapping(
    value: object, pointer: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "contract field must be an object",
            pointer=pointer,
            details={"type": type(value).__name__},
        )
    if any(not isinstance(key, str) for key in value):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "contract object keys must be strings",
            pointer=pointer,
        )
    return value


def _authority_reject_unknown(
    value: Mapping[str, object],
    allowed: frozenset[str],
    pointer: str,
) -> None:
    unknown = sorted(set(value) - allowed, key=_authority_utf8_key)
    if unknown:
        raise _authority_error(
            "ORCHESTRATION_UNKNOWN_FIELD",
            "contract contains unsupported fields",
            pointer=pointer,
            details={"fields": unknown},
        )


def _authority_require_string(
    value: object,
    pointer: str,
    *,
    stable_id: bool = False,
) -> str:
    if not isinstance(value, str) or not value:
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "contract field must be a non-empty string",
            pointer=pointer,
        )
    _authority_validate_json_value(value, pointer)
    if stable_id:
        if (
            not _authority_stable_id_re.fullmatch(value)
            or "//" in value
            or any(part in {".", ".."} for part in value.split("/"))
        ):
            raise _authority_error(
                "ORCHESTRATION_IDENTIFIER_INVALID",
                "identifier is not stable and portable",
                pointer=pointer,
                details={"value": value},
            )
    return value


def _authority_require_digest(value: object, pointer: str) -> str:
    digest = _authority_require_string(value, pointer)
    if not _authority_sha256_re.fullmatch(digest):
        raise _authority_error(
            "ORCHESTRATION_DIGEST_INVALID",
            "digest must be lowercase SHA-256",
            pointer=pointer,
            details={"value": digest},
        )
    return digest


def _authority_require_int(
    value: object,
    pointer: str,
    *,
    minimum: int = 0,
    maximum: int = _authority_signed_int64_max,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            f"contract field must be an integer from {minimum} to {maximum}",
            pointer=pointer,
            details={"value": value},
        )
    return value


def _authority_require_bool(value: object, pointer: str) -> bool:
    if not isinstance(value, bool):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "contract field must be boolean",
            pointer=pointer,
        )
    return value


def _authority_require_optional_int(
    value: object, pointer: str
) -> Optional[int]:
    if value is None:
        return None
    return _authority_require_int(value, pointer)


def _authority_require_optional_digest(
    value: object, pointer: str
) -> Optional[str]:
    if value is None:
        return None
    return _authority_require_digest(value, pointer)


def _authority_require_canonical_strings(
    value: object,
    pointer: str,
    *,
    stable_ids: bool = False,
    digests: bool = False,
) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "contract field must be an array",
            pointer=pointer,
        )
    result = []
    for index, item in enumerate(value):
        item_pointer = f"{pointer}/{index}"
        if digests:
            result.append(_authority_require_digest(item, item_pointer))
        else:
            result.append(
                _authority_require_string(
                    item, item_pointer, stable_id=stable_ids
                )
            )
    if len(result) != len(set(result)):
        raise _authority_error(
            "ORCHESTRATION_DUPLICATE_VALUE",
            "contract array entries must be unique",
            pointer=pointer,
        )
    expected = tuple(sorted(result, key=_authority_utf8_key))
    if tuple(result) != expected:
        raise _authority_error(
            "ORCHESTRATION_ORDER_INVALID",
            "contract arrays must use deterministic UTF-8 order",
            pointer=pointer,
        )
    return expected


def _authority_portable_relative_path(
    value: object, pointer: str
) -> str:
    path = _authority_require_string(value, pointer)
    if (
        "\x00" in path
        or "\\" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or any(character in path for character in "*?[]")
        or "//" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise _authority_error(
            "ORCHESTRATION_PATH_INVALID",
            "path must be an exact portable relative POSIX path",
            pointer=pointer,
            details={"path": path},
        )
    return path


def _authority_require_approved_paths(
    value: object, pointer: str
) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _authority_error(
            "ORCHESTRATION_FIELD_INVALID",
            "approved paths must be an array",
            pointer=pointer,
        )
    paths = tuple(
        _authority_portable_relative_path(item, f"{pointer}/{index}")
        for index, item in enumerate(value)
    )
    if len(paths) != len(set(paths)):
        raise _authority_error(
            "ORCHESTRATION_DUPLICATE_VALUE",
            "approved paths must be unique",
            pointer=pointer,
        )
    expected = tuple(sorted(paths, key=_authority_utf8_key))
    if paths != expected:
        raise _authority_error(
            "ORCHESTRATION_ORDER_INVALID",
            "approved paths must use deterministic UTF-8 order",
            pointer=pointer,
        )
    portable_seen = {}
    for path in paths:
        portable = unicodedata.normalize("NFC", path).casefold()
        previous = portable_seen.get(portable)
        if previous is not None:
            raise _authority_error(
                "ORCHESTRATION_PATH_COLLISION",
                "approved paths collide under portable comparison",
                pointer=pointer,
                details={"first": previous, "second": path},
            )
        portable_seen[portable] = path
    for index, path in enumerate(paths):
        for other in paths[index + 1 :]:
            if other.startswith(path + "/"):
                raise _authority_error(
                    "ORCHESTRATION_PATH_OVERLAP",
                    "approved paths must not contain ancestor overlaps",
                    pointer=pointer,
                    details={"ancestor": path, "descendant": other},
                )
    return paths


def _authority_require_worktree_path(
    value: object, pointer: str
) -> str:
    path = _authority_require_string(value, pointer)
    if "\x00" in path or "\\" in path or "//" in path[2:]:
        raise _authority_error(
            "ORCHESTRATION_WORKTREE_PATH_INVALID",
            "worktree path must use canonical forward-slash form",
            pointer=pointer,
        )
    if re.match(r"^[A-Z]:/", path):
        parts = path[3:].split("/")
    elif path.startswith("//"):
        parts = path[2:].split("/")
        if len(parts) < 3:
            parts = []
    elif path.startswith("/") and not path.startswith("//"):
        parts = path[1:].split("/")
    else:
        parts = []
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or (
            re.match(r"^[A-Za-z]:", path)
            and not re.match(r"^[A-Z]:/", path)
        )
    ):
        raise _authority_error(
            "ORCHESTRATION_WORKTREE_PATH_INVALID",
            "worktree path must be a canonical absolute POSIX, drive, or UNC path",
            pointer=pointer,
            details={"path": path},
        )
    return path


def _authority_require_clock(
    *,
    wall_time_ns: object,
    monotonic_time_ns: object,
    clock_id: object,
    prefix: str = "/",
) -> Tuple[int, int, str]:
    wall = _authority_require_int(
        wall_time_ns, f"{prefix.rstrip('/')}/wall_time_ns"
    )
    monotonic = _authority_require_int(
        monotonic_time_ns,
        f"{prefix.rstrip('/')}/monotonic_time_ns",
    )
    identifier = _authority_require_string(
        clock_id, f"{prefix.rstrip('/')}/clock_id", stable_id=True
    )
    return wall, monotonic, identifier


def _authority_check_ttl(
    ttl_ns: object, pointer: str, maximum: int
) -> int:
    return _authority_require_int(
        ttl_ns, pointer, minimum=1, maximum=maximum
    )


@dataclass(frozen=True)
class WorkerLeaseRecord:
    schema: str
    lease_id: str
    task_id: str
    task_revision: int
    workflow_bundle_sha256: str
    map_epoch: int
    node_instance_id: str
    repository_id: str
    repository_identity_sha256: str
    worktree_identity_sha256: str
    attempt: int
    input_evidence_sha256: str
    plan_dag_sha256: str
    semantic_input_sha256: str
    interface_contract_sha256s: Tuple[str, ...]
    approved_paths: Tuple[str, ...]
    allowed_actions: Tuple[str, ...]
    write_policy: str
    lease_nonce: str
    issued_at_wall_ns: int
    expires_at_wall_ns: int
    issued_at_monotonic_ns: int
    ttl_ns: int
    clock_id: str
    state: str
    revoked_at_wall_ns: Optional[int]
    revocation_reason: Optional[str]
    quiesced_at_wall_ns: Optional[int]
    quiescence_evidence_sha256: Optional[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "lease_id": self.lease_id,
            "task_id": self.task_id,
            "task_revision": self.task_revision,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "map_epoch": self.map_epoch,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "repository_identity_sha256": (
                self.repository_identity_sha256
            ),
            "worktree_identity_sha256": self.worktree_identity_sha256,
            "attempt": self.attempt,
            "input_evidence_sha256": self.input_evidence_sha256,
            "plan_dag_sha256": self.plan_dag_sha256,
            "semantic_input_sha256": self.semantic_input_sha256,
            "interface_contract_sha256s": list(
                self.interface_contract_sha256s
            ),
            "approved_paths": list(self.approved_paths),
            "allowed_actions": list(self.allowed_actions),
            "write_policy": self.write_policy,
            "lease_nonce": self.lease_nonce,
            "issued_at_wall_ns": self.issued_at_wall_ns,
            "expires_at_wall_ns": self.expires_at_wall_ns,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "ttl_ns": self.ttl_ns,
            "clock_id": self.clock_id,
            "state": self.state,
            "revoked_at_wall_ns": self.revoked_at_wall_ns,
            "revocation_reason": self.revocation_reason,
            "quiesced_at_wall_ns": self.quiesced_at_wall_ns,
            "quiescence_evidence_sha256": (
                self.quiescence_evidence_sha256
            ),
        }


@dataclass(frozen=True)
class WorkerLeaseCredential:
    schema: str
    credential_id: str
    lease_id: str
    lease_nonce: str
    task_id: str
    workflow_bundle_sha256: str
    node_instance_id: str
    repository_id: str
    worktree_identity_sha256: str
    attempt: int
    allowed_actions: Tuple[str, ...]
    expires_at_wall_ns: int
    mutation_authority: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "credential_id": self.credential_id,
            "lease_id": self.lease_id,
            "lease_nonce": self.lease_nonce,
            "task_id": self.task_id,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "node_instance_id": self.node_instance_id,
            "repository_id": self.repository_id,
            "worktree_identity_sha256": self.worktree_identity_sha256,
            "attempt": self.attempt,
            "allowed_actions": list(self.allowed_actions),
            "expires_at_wall_ns": self.expires_at_wall_ns,
            "mutation_authority": self.mutation_authority,
        }


@dataclass(frozen=True)
class WorkerLeaseStatus:
    lease_id: str
    effective_state: str
    authorized: bool
    quiesced: bool
    blocker_codes: Tuple[str, ...]


@dataclass(frozen=True)
class WorkerAssignment:
    schema: str
    assignment_id: str
    task_id: str
    expected_revision: int
    workflow_bundle_sha256: str
    map_epoch: int
    node_id: str
    node_instance_id: str
    attempt: int
    repository_id: str
    repository_identity_sha256: str
    worktree_path: str
    worktree_identity_sha256: str
    controller_claim_sha256: str
    approved_paths: Tuple[str, ...]
    write_policy: str
    plan_id: str
    plan_artifact_sha256: str
    plan_dag_sha256: str
    semantic_input_sha256: str
    interface_contract_sha256s: Tuple[str, ...]
    input_evidence_sha256: str
    lease_credential: WorkerLeaseCredential
    capabilities: Tuple[str, ...]
    playbook_locator: str
    playbook_sha256: str
    required_evidence_contract_sha256s: Tuple[str, ...]
    external_tool_grant_sha256s: Tuple[str, ...] = ()
    external_tool_role_profile_sha256: Optional[str] = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema": self.schema,
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "expected_revision": self.expected_revision,
            "workflow_bundle_sha256": self.workflow_bundle_sha256,
            "map_epoch": self.map_epoch,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "attempt": self.attempt,
            "repository_id": self.repository_id,
            "repository_identity_sha256": (
                self.repository_identity_sha256
            ),
            "worktree_path": self.worktree_path,
            "worktree_identity_sha256": self.worktree_identity_sha256,
            "controller_claim_sha256": self.controller_claim_sha256,
            "approved_paths": list(self.approved_paths),
            "write_policy": self.write_policy,
            "plan_id": self.plan_id,
            "plan_artifact_sha256": self.plan_artifact_sha256,
            "plan_dag_sha256": self.plan_dag_sha256,
            "semantic_input_sha256": self.semantic_input_sha256,
            "interface_contract_sha256s": list(
                self.interface_contract_sha256s
            ),
            "input_evidence_sha256": self.input_evidence_sha256,
            "lease_credential": self.lease_credential.as_dict(),
            "capabilities": list(self.capabilities),
            "playbook_locator": self.playbook_locator,
            "playbook_sha256": self.playbook_sha256,
            "required_evidence_contract_sha256s": list(
                self.required_evidence_contract_sha256s
            ),
        }
        if self.external_tool_grant_sha256s:
            result["external_tool_grant_sha256s"] = list(
                self.external_tool_grant_sha256s
            )
        if self.external_tool_role_profile_sha256 is not None:
            result["external_tool_role_profile_sha256"] = (
                self.external_tool_role_profile_sha256
            )
        return result


@dataclass(frozen=True)
class ManagerCapabilityVerifier:
    schema: str
    capability_id: str
    task_id: str
    issued_for_task_revision: int
    manager_session_id: str
    allowed_actions: Tuple[str, ...]
    issued_at_wall_ns: int
    expires_at_wall_ns: int
    issued_at_monotonic_ns: int
    ttl_ns: int
    clock_id: str
    secret_transport: str
    operator_confirmation_sha256: str
    issuance_audit_sha256: str
    verifier_hmac_sha256: str
    revoked_at_wall_ns: Optional[int]
    revocation_reason: Optional[str]
    revocation_audit_sha256: Optional[str]
    used_request_nonce_sha256s: Tuple[str, ...]

    def as_persistent_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "issued_for_task_revision": self.issued_for_task_revision,
            "manager_session_id": self.manager_session_id,
            "allowed_actions": list(self.allowed_actions),
            "issued_at_wall_ns": self.issued_at_wall_ns,
            "expires_at_wall_ns": self.expires_at_wall_ns,
            "issued_at_monotonic_ns": self.issued_at_monotonic_ns,
            "ttl_ns": self.ttl_ns,
            "clock_id": self.clock_id,
            "secret_transport": self.secret_transport,
            "operator_confirmation_sha256": (
                self.operator_confirmation_sha256
            ),
            "issuance_audit_sha256": self.issuance_audit_sha256,
            "verifier_hmac_sha256": self.verifier_hmac_sha256,
            "revoked_at_wall_ns": self.revoked_at_wall_ns,
            "revocation_reason": self.revocation_reason,
            "revocation_audit_sha256": self.revocation_audit_sha256,
            "used_request_nonce_sha256s": list(
                self.used_request_nonce_sha256s
            ),
        }


@dataclass(frozen=True)
class ManagerCapabilityRequest:
    schema: str
    capability_id: str
    task_id: str
    manager_session_id: str
    action_id: str
    expected_revision: int
    request_nonce: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "manager_session_id": self.manager_session_id,
            "action_id": self.action_id,
            "expected_revision": self.expected_revision,
            "request_nonce": self.request_nonce,
        }


@dataclass(frozen=True)
class AgentPrincipal:
    schema: str
    role: str
    session_id: str
    os_user_identity_sha256: str
    host_identity_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "role": self.role,
            "session_id": self.session_id,
            "os_user_identity_sha256": self.os_user_identity_sha256,
            "host_identity_sha256": self.host_identity_sha256,
        }


@dataclass(frozen=True)
class ManagerAuthorization:
    schema: str
    authorization_id: str
    capability_id: str
    task_id: str
    manager_session_id: str
    action_id: str
    expected_revision: int
    request_fingerprint_sha256: str
    verifier_state: ManagerCapabilityVerifier

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "capability_id": self.capability_id,
            "task_id": self.task_id,
            "manager_session_id": self.manager_session_id,
            "action_id": self.action_id,
            "expected_revision": self.expected_revision,
            "request_fingerprint_sha256": (
                self.request_fingerprint_sha256
            ),
            "verifier_state": self.verifier_state.as_persistent_dict(),
        }


@dataclass(frozen=True)
class HostCapabilityReport:
    schema: str
    adapter_id: str
    assignment_id: str
    worker_session_id: str
    worker_identity_sha256: str
    attestation_sha256: str
    host_enforced: bool
    allowed_write_identity_sha256s: Tuple[str, ...]
    denied_read_identity_sha256s: Tuple[str, ...]
    denied_tool_ids: Tuple[str, ...]
    all_other_writes_denied: bool
    manager_secret_channel_excluded: bool
    controller_state_excluded: bool
    mutation_tools_excluded: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "adapter_id": self.adapter_id,
            "assignment_id": self.assignment_id,
            "worker_session_id": self.worker_session_id,
            "worker_identity_sha256": self.worker_identity_sha256,
            "attestation_sha256": self.attestation_sha256,
            "host_enforced": self.host_enforced,
            "allowed_write_identity_sha256s": list(
                self.allowed_write_identity_sha256s
            ),
            "denied_read_identity_sha256s": list(
                self.denied_read_identity_sha256s
            ),
            "denied_tool_ids": list(self.denied_tool_ids),
            "all_other_writes_denied": self.all_other_writes_denied,
            "manager_secret_channel_excluded": (
                self.manager_secret_channel_excluded
            ),
            "controller_state_excluded": (
                self.controller_state_excluded
            ),
            "mutation_tools_excluded": self.mutation_tools_excluded,
        }


@dataclass(frozen=True)
class HostIsolationDecision:
    schema: str
    assignment_id: str
    parallel_dispatch_allowed: bool
    dispatch_mode: str
    blocker_codes: Tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "assignment_id": self.assignment_id,
            "parallel_dispatch_allowed": (
                self.parallel_dispatch_allowed
            ),
            "dispatch_mode": self.dispatch_mode,
            "blocker_codes": list(self.blocker_codes),
        }


_worker_lease_fields = frozenset(
    {
        "schema",
        "lease_id",
        "task_id",
        "task_revision",
        "workflow_bundle_sha256",
        "map_epoch",
        "node_instance_id",
        "repository_id",
        "repository_identity_sha256",
        "worktree_identity_sha256",
        "attempt",
        "input_evidence_sha256",
        "plan_dag_sha256",
        "semantic_input_sha256",
        "interface_contract_sha256s",
        "approved_paths",
        "allowed_actions",
        "write_policy",
        "lease_nonce",
        "issued_at_wall_ns",
        "expires_at_wall_ns",
        "issued_at_monotonic_ns",
        "ttl_ns",
        "clock_id",
        "state",
        "revoked_at_wall_ns",
        "revocation_reason",
        "quiesced_at_wall_ns",
        "quiescence_evidence_sha256",
    }
)
_worker_lease_spec_fields = frozenset(
    {
        "task_id",
        "task_revision",
        "workflow_bundle_sha256",
        "map_epoch",
        "node_instance_id",
        "repository_id",
        "repository_identity_sha256",
        "worktree_identity_sha256",
        "attempt",
        "input_evidence_sha256",
        "plan_dag_sha256",
        "semantic_input_sha256",
        "interface_contract_sha256s",
        "approved_paths",
        "allowed_actions",
        "write_policy",
    }
)
_worker_lease_credential_fields = frozenset(
    {
        "schema",
        "credential_id",
        "lease_id",
        "lease_nonce",
        "task_id",
        "workflow_bundle_sha256",
        "node_instance_id",
        "repository_id",
        "worktree_identity_sha256",
        "attempt",
        "allowed_actions",
        "expires_at_wall_ns",
        "mutation_authority",
    }
)
_worker_assignment_fields = frozenset(
    {
        "schema",
        "assignment_id",
        "task_id",
        "expected_revision",
        "workflow_bundle_sha256",
        "map_epoch",
        "node_id",
        "node_instance_id",
        "attempt",
        "repository_id",
        "repository_identity_sha256",
        "worktree_path",
        "worktree_identity_sha256",
        "controller_claim_sha256",
        "approved_paths",
        "write_policy",
        "plan_id",
        "plan_artifact_sha256",
        "plan_dag_sha256",
        "semantic_input_sha256",
        "interface_contract_sha256s",
        "input_evidence_sha256",
        "lease_credential",
        "capabilities",
        "playbook_locator",
        "playbook_sha256",
        "required_evidence_contract_sha256s",
        "external_tool_grant_sha256s",
        "external_tool_role_profile_sha256",
    }
)
_worker_assignment_optional_fields = frozenset(
    {
        "external_tool_grant_sha256s",
        "external_tool_role_profile_sha256",
    }
)
_manager_capability_fields = frozenset(
    {
        "schema",
        "capability_id",
        "task_id",
        "issued_for_task_revision",
        "manager_session_id",
        "allowed_actions",
        "issued_at_wall_ns",
        "expires_at_wall_ns",
        "issued_at_monotonic_ns",
        "ttl_ns",
        "clock_id",
        "secret_transport",
        "operator_confirmation_sha256",
        "issuance_audit_sha256",
        "verifier_hmac_sha256",
        "revoked_at_wall_ns",
        "revocation_reason",
        "revocation_audit_sha256",
        "used_request_nonce_sha256s",
    }
)
_manager_request_fields = frozenset(
    {
        "schema",
        "capability_id",
        "task_id",
        "manager_session_id",
        "action_id",
        "expected_revision",
        "request_nonce",
    }
)
_agent_principal_fields = frozenset(
    {
        "schema",
        "role",
        "session_id",
        "os_user_identity_sha256",
        "host_identity_sha256",
    }
)
_host_capability_report_fields = frozenset(
    {
        "schema",
        "adapter_id",
        "assignment_id",
        "worker_session_id",
        "worker_identity_sha256",
        "attestation_sha256",
        "host_enforced",
        "allowed_write_identity_sha256s",
        "denied_read_identity_sha256s",
        "denied_tool_ids",
        "all_other_writes_denied",
        "manager_secret_channel_excluded",
        "controller_state_excluded",
        "mutation_tools_excluded",
    }
)


def _validate_worker_scope(
    write_policy: str,
    approved_paths: Tuple[str, ...],
    allowed_actions: Tuple[str, ...],
) -> None:
    unknown = sorted(
        set(allowed_actions) - WORKER_EXECUTOR_CAPABILITIES,
        key=_authority_utf8_key,
    )
    if unknown:
        raise _authority_error(
            "WORKER_CAPABILITY_FORBIDDEN",
            "worker assignment requests an unknown or mutating capability",
            pointer="/allowed_actions",
            details={"capabilities": unknown},
        )
    required = {"repository.read/v1", "result.emit-candidate/v1"}
    if not required.issubset(allowed_actions):
        raise _authority_error(
            "WORKER_CAPABILITY_INCOMPLETE",
            "worker scope must permit repository reads and candidate output",
            pointer="/allowed_actions",
            details={"required": sorted(required)},
        )
    write_capability = "repository.write-approved/v1"
    if write_policy == "scoped-write":
        if not approved_paths or write_capability not in allowed_actions:
            raise _authority_error(
                "WORKER_WRITE_SCOPE_INVALID",
                "writable workers require approved paths and the "
                "scoped write capability",
                pointer="/write_policy",
            )
    elif approved_paths or write_capability in allowed_actions:
        raise _authority_error(
            "WORKER_WRITE_SCOPE_INVALID",
            "read-only workers cannot receive paths or write capability",
            pointer="/write_policy",
        )


def _worker_lease_identity_payload(
    lease: WorkerLeaseRecord,
) -> dict[str, object]:
    value = lease.as_dict()
    value.pop("lease_id")
    value.pop("state")
    value.pop("revoked_at_wall_ns")
    value.pop("revocation_reason")
    value.pop("quiesced_at_wall_ns")
    value.pop("quiescence_evidence_sha256")
    return value


def validate_worker_lease(
    value: Union[WorkerLeaseRecord, Mapping[str, object]]
) -> WorkerLeaseRecord:
    if isinstance(value, WorkerLeaseRecord):
        source = value.as_dict()
    else:
        source = _authority_require_mapping(value, "/")
    _authority_reject_unknown(source, _worker_lease_fields, "/")
    missing = sorted(_worker_lease_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "worker lease is missing required fields",
            details={"fields": missing},
        )
    schema = _authority_require_string(source["schema"], "/schema")
    if schema != WORKER_LEASE_SCHEMA:
        raise _authority_error(
            "WORKER_LEASE_SCHEMA_UNSUPPORTED",
            "worker lease schema is unsupported",
            pointer="/schema",
            details={"schema": schema},
        )
    lease_id = _authority_require_string(
        source["lease_id"], "/lease_id", stable_id=True
    )
    task_id = _authority_require_string(
        source["task_id"], "/task_id", stable_id=True
    )
    task_revision = _authority_require_int(
        source["task_revision"], "/task_revision"
    )
    bundle = _authority_require_digest(
        source["workflow_bundle_sha256"],
        "/workflow_bundle_sha256",
    )
    map_epoch = _authority_require_int(
        source["map_epoch"], "/map_epoch", minimum=1
    )
    node_instance_id = _authority_require_string(
        source["node_instance_id"],
        "/node_instance_id",
        stable_id=True,
    )
    repository_id = _authority_require_string(
        source["repository_id"], "/repository_id", stable_id=True
    )
    repository_identity = _authority_require_digest(
        source["repository_identity_sha256"],
        "/repository_identity_sha256",
    )
    worktree_identity = _authority_require_digest(
        source["worktree_identity_sha256"],
        "/worktree_identity_sha256",
    )
    attempt = _authority_require_int(
        source["attempt"], "/attempt", minimum=1
    )
    input_digest = _authority_require_digest(
        source["input_evidence_sha256"], "/input_evidence_sha256"
    )
    dag_digest = _authority_require_digest(
        source["plan_dag_sha256"], "/plan_dag_sha256"
    )
    semantic_digest = _authority_require_digest(
        source["semantic_input_sha256"], "/semantic_input_sha256"
    )
    contracts = _authority_require_canonical_strings(
        source["interface_contract_sha256s"],
        "/interface_contract_sha256s",
        digests=True,
    )
    approved_paths = _authority_require_approved_paths(
        source["approved_paths"], "/approved_paths"
    )
    allowed_actions = _authority_require_canonical_strings(
        source["allowed_actions"],
        "/allowed_actions",
        stable_ids=True,
    )
    write_policy = _authority_require_string(
        source["write_policy"], "/write_policy"
    )
    if write_policy not in WORKER_WRITE_POLICIES:
        raise _authority_error(
            "WORKER_WRITE_POLICY_UNSUPPORTED",
            "worker write policy is unsupported",
            pointer="/write_policy",
        )
    _validate_worker_scope(
        write_policy, approved_paths, allowed_actions
    )
    lease_nonce = _authority_require_string(
        source["lease_nonce"], "/lease_nonce"
    )
    if not _authority_request_nonce_re.fullmatch(lease_nonce):
        raise _authority_error(
            "WORKER_LEASE_NONCE_INVALID",
            "lease nonce must encode 256 bits as lowercase hex",
            pointer="/lease_nonce",
        )
    issued_wall = _authority_require_int(
        source["issued_at_wall_ns"], "/issued_at_wall_ns"
    )
    expires_wall = _authority_require_int(
        source["expires_at_wall_ns"], "/expires_at_wall_ns"
    )
    issued_monotonic = _authority_require_int(
        source["issued_at_monotonic_ns"],
        "/issued_at_monotonic_ns",
    )
    ttl = _authority_check_ttl(
        source["ttl_ns"], "/ttl_ns", MAX_WORKER_LEASE_TTL_NS
    )
    if expires_wall - issued_wall != ttl:
        raise _authority_error(
            "WORKER_LEASE_TIME_INVALID",
            "worker lease wall-clock expiry must equal issuance plus TTL",
            pointer="/expires_at_wall_ns",
        )
    clock_id = _authority_require_string(
        source["clock_id"], "/clock_id", stable_id=True
    )
    state = _authority_require_string(source["state"], "/state")
    if state not in WORKER_LEASE_STATES:
        raise _authority_error(
            "WORKER_LEASE_STATE_INVALID",
            "worker lease state is unsupported",
            pointer="/state",
        )
    revoked_at = _authority_require_optional_int(
        source["revoked_at_wall_ns"], "/revoked_at_wall_ns"
    )
    revocation_reason_value = source["revocation_reason"]
    revocation_reason = None
    if revocation_reason_value is not None:
        revocation_reason = _authority_require_string(
            revocation_reason_value,
            "/revocation_reason",
            stable_id=True,
        )
    if state == "REVOKED":
        if revoked_at is None or revocation_reason is None:
            raise _authority_error(
                "WORKER_LEASE_REVOCATION_INVALID",
                "revoked leases require timestamp and reason",
                pointer="/state",
            )
    elif revoked_at is not None or revocation_reason is not None:
        raise _authority_error(
            "WORKER_LEASE_REVOCATION_INVALID",
            "only revoked leases carry revocation fields",
            pointer="/state",
        )
    quiesced_at = _authority_require_optional_int(
        source["quiesced_at_wall_ns"], "/quiesced_at_wall_ns"
    )
    quiescence_digest = _authority_require_optional_digest(
        source["quiescence_evidence_sha256"],
        "/quiescence_evidence_sha256",
    )
    if (quiesced_at is None) != (quiescence_digest is None):
        raise _authority_error(
            "WORKER_LEASE_QUIESCENCE_INVALID",
            "quiescence timestamp and evidence must appear together",
            pointer="/quiesced_at_wall_ns",
        )
    if quiesced_at is not None and state == "ACTIVE":
        raise _authority_error(
            "WORKER_LEASE_QUIESCENCE_INVALID",
            "an active lease cannot be quiesced",
            pointer="/state",
        )
    lease = WorkerLeaseRecord(
        schema=schema,
        lease_id=lease_id,
        task_id=task_id,
        task_revision=task_revision,
        workflow_bundle_sha256=bundle,
        map_epoch=map_epoch,
        node_instance_id=node_instance_id,
        repository_id=repository_id,
        repository_identity_sha256=repository_identity,
        worktree_identity_sha256=worktree_identity,
        attempt=attempt,
        input_evidence_sha256=input_digest,
        plan_dag_sha256=dag_digest,
        semantic_input_sha256=semantic_digest,
        interface_contract_sha256s=contracts,
        approved_paths=approved_paths,
        allowed_actions=allowed_actions,
        write_policy=write_policy,
        lease_nonce=lease_nonce,
        issued_at_wall_ns=issued_wall,
        expires_at_wall_ns=expires_wall,
        issued_at_monotonic_ns=issued_monotonic,
        ttl_ns=ttl,
        clock_id=clock_id,
        state=state,
        revoked_at_wall_ns=revoked_at,
        revocation_reason=revocation_reason,
        quiesced_at_wall_ns=quiesced_at,
        quiescence_evidence_sha256=quiescence_digest,
    )
    expected_id = "worker-lease:" + _authority_digest(
        _authority_lease_domain, _worker_lease_identity_payload(lease)
    )
    if not hmac.compare_digest(lease_id, expected_id):
        raise _authority_error(
            "WORKER_LEASE_IDENTITY_MISMATCH",
            "worker lease identity does not match canonical content",
            pointer="/lease_id",
            details={"expected": expected_id, "actual": lease_id},
        )
    return lease


def _worker_lease_from_spec(
    source: Mapping[str, object],
    *,
    lease_nonce: str,
    wall_time_ns: int,
    monotonic_time_ns: int,
    ttl_ns: int,
    clock_id: str,
) -> WorkerLeaseRecord:
    provisional = {
        "schema": WORKER_LEASE_SCHEMA,
        "lease_id": "worker-lease:" + "0" * 64,
        **dict(source),
        "lease_nonce": lease_nonce,
        "issued_at_wall_ns": wall_time_ns,
        "expires_at_wall_ns": wall_time_ns + ttl_ns,
        "issued_at_monotonic_ns": monotonic_time_ns,
        "ttl_ns": ttl_ns,
        "clock_id": clock_id,
        "state": "ACTIVE",
        "revoked_at_wall_ns": None,
        "revocation_reason": None,
        "quiesced_at_wall_ns": None,
        "quiescence_evidence_sha256": None,
    }
    # Parse all fields once with a temporary identity, then bind the final ID.
    parsed = _parse_worker_lease_without_identity(provisional)
    lease_id = "worker-lease:" + _authority_digest(
        _authority_lease_domain, _worker_lease_identity_payload(parsed)
    )
    return validate_worker_lease(
        {**parsed.as_dict(), "lease_id": lease_id}
    )


def _parse_worker_lease_without_identity(
    value: Mapping[str, object],
) -> WorkerLeaseRecord:
    # Reuse the full validator while allowing only the factory placeholder.
    placeholder = _authority_require_string(
        value.get("lease_id"), "/lease_id", stable_id=True
    )
    if placeholder != "worker-lease:" + "0" * 64:
        return validate_worker_lease(value)
    shadow = dict(value)
    shadow["lease_id"] = "worker-lease:" + "1" * 64
    try:
        validate_worker_lease(shadow)
    except OrchestrationAuthorityError as exc:
        if exc.code != "WORKER_LEASE_IDENTITY_MISMATCH":
            raise
        expected = exc.details.get("expected")
        if not isinstance(expected, str):
            raise
        shadow["lease_id"] = expected
    parsed = validate_worker_lease(shadow)
    return replace(parsed, lease_id=placeholder)


def worker_lease_status(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]],
    *,
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
) -> WorkerLeaseStatus:
    record = validate_worker_lease(lease)
    wall, monotonic, current_clock = _authority_require_clock(
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
        prefix="/clock",
    )
    blockers = []
    effective = record.state
    if current_clock != record.clock_id:
        blockers.append("WORKER_LEASE_CLOCK_CONTEXT_MISMATCH")
    elif (
        wall < record.issued_at_wall_ns
        or monotonic < record.issued_at_monotonic_ns
    ):
        blockers.append("WORKER_LEASE_CLOCK_ROLLBACK")
    elif record.state == "ACTIVE" and (
        wall >= record.expires_at_wall_ns
        or monotonic - record.issued_at_monotonic_ns >= record.ttl_ns
    ):
        effective = "EXPIRED"
        blockers.append("WORKER_LEASE_EXPIRED")
    if record.state == "REVOKED":
        blockers.append("WORKER_LEASE_REVOKED")
    elif record.state == "EXPIRED":
        blockers.append("WORKER_LEASE_EXPIRED")
    blockers = sorted(set(blockers), key=_authority_utf8_key)
    return WorkerLeaseStatus(
        lease_id=record.lease_id,
        effective_state=effective,
        authorized=not blockers and effective == "ACTIVE",
        quiesced=record.quiesced_at_wall_ns is not None,
        blocker_codes=tuple(blockers),
    )


def assert_worker_lease_available(
    candidate: Mapping[str, object],
    existing_leases: Iterable[
        Union[WorkerLeaseRecord, Mapping[str, object]]
    ],
    *,
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
) -> None:
    node_id = _authority_require_string(
        candidate.get("node_instance_id"),
        "/node_instance_id",
        stable_id=True,
    )
    worktree_id = _authority_require_digest(
        candidate.get("worktree_identity_sha256"),
        "/worktree_identity_sha256",
    )
    for value in existing_leases:
        lease = validate_worker_lease(value)
        status = worker_lease_status(
            lease,
            wall_time_ns=wall_time_ns,
            monotonic_time_ns=monotonic_time_ns,
            clock_id=clock_id,
        )
        same_node = lease.node_instance_id == node_id
        same_worktree = lease.worktree_identity_sha256 == worktree_id
        if (same_node or same_worktree) and not status.quiesced:
            raise _authority_error(
                "WORKER_LEASE_EXCLUSIVE_CONFLICT",
                "a prior writer remains active or non-quiesced",
                details={
                    "conflicting_lease_id": lease.lease_id,
                    "same_node": same_node,
                    "same_worktree": same_worktree,
                    "effective_state": status.effective_state,
                },
            )


def issue_worker_lease(
    spec: Mapping[str, object],
    *,
    lease_nonce_bytes: bytes,
    wall_time_ns: int,
    monotonic_time_ns: int,
    ttl_ns: int,
    clock_id: str,
    existing_leases: Iterable[
        Union[WorkerLeaseRecord, Mapping[str, object]]
    ] = (),
    cancellation_requested: bool = False,
) -> WorkerLeaseRecord:
    """Build an active lease after pure scope and exclusivity checks.

    ``lease_nonce_bytes`` must come from the controller's cryptographic random
    source.  The resulting nonce is only a candidate-output identity and never
    authorizes a controller mutation.
    """

    source = _authority_require_mapping(spec, "/")
    if not isinstance(cancellation_requested, bool):
        raise _authority_error(
            "CANCELLATION_STATE_INVALID",
            "lease issuance requires controller cancellation truth",
            pointer="/cancellation_requested",
        )
    if cancellation_requested:
        raise _authority_error(
            "WORKER_LEASE_CANCELLATION_REQUESTED",
            "a task with requested cancellation cannot issue a worker lease",
            pointer="/cancellation_requested",
        )
    _authority_reject_unknown(source, _worker_lease_spec_fields, "/")
    missing = sorted(_worker_lease_spec_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "worker lease spec is missing required fields",
            details={"fields": missing},
        )
    if not isinstance(lease_nonce_bytes, bytes) or len(
        lease_nonce_bytes
    ) != MIN_LEASE_NONCE_BYTES:
        raise _authority_error(
            "WORKER_LEASE_NONCE_INVALID",
            "controller must supply exactly 256 bits for a lease nonce",
            pointer="/lease_nonce_bytes",
        )
    wall, monotonic, current_clock = _authority_require_clock(
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
        prefix="/clock",
    )
    ttl = _authority_check_ttl(
        ttl_ns, "/ttl_ns", MAX_WORKER_LEASE_TTL_NS
    )
    if wall > _authority_signed_int64_max - ttl:
        raise _authority_error(
            "WORKER_LEASE_TIME_INVALID",
            "worker lease expiry exceeds the canonical integer range",
            pointer="/ttl_ns",
        )
    assert_worker_lease_available(
        source,
        existing_leases,
        wall_time_ns=wall,
        monotonic_time_ns=monotonic,
        clock_id=current_clock,
    )
    return _worker_lease_from_spec(
        source,
        lease_nonce=lease_nonce_bytes.hex(),
        wall_time_ns=wall,
        monotonic_time_ns=monotonic,
        ttl_ns=ttl,
        clock_id=current_clock,
    )


def expire_worker_lease(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]],
    *,
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
) -> WorkerLeaseRecord:
    record = validate_worker_lease(lease)
    status = worker_lease_status(
        record,
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
    )
    if record.state == "REVOKED":
        raise _authority_error(
            "WORKER_LEASE_REVOKED",
            "a revoked lease cannot transition to expired",
            pointer="/state",
        )
    if status.effective_state != "EXPIRED":
        raise _authority_error(
            "WORKER_LEASE_NOT_EXPIRED",
            "worker lease has not reached expiry",
            pointer="/expires_at_wall_ns",
        )
    # Expiry explicitly does not claim process or worktree quiescence.
    return validate_worker_lease(
        {
            **record.as_dict(),
            "state": "EXPIRED",
            "quiesced_at_wall_ns": None,
            "quiescence_evidence_sha256": None,
        }
    )


def revoke_worker_lease(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]],
    *,
    revoked_at_wall_ns: int,
    reason: str,
) -> WorkerLeaseRecord:
    record = validate_worker_lease(lease)
    revoked_at = _authority_require_int(
        revoked_at_wall_ns, "/revoked_at_wall_ns"
    )
    reason_value = _authority_require_string(
        reason, "/revocation_reason", stable_id=True
    )
    if revoked_at < record.issued_at_wall_ns:
        raise _authority_error(
            "WORKER_LEASE_TIME_INVALID",
            "revocation cannot predate lease issuance",
            pointer="/revoked_at_wall_ns",
        )
    if record.state == "REVOKED":
        if (
            record.revoked_at_wall_ns == revoked_at
            and record.revocation_reason == reason_value
        ):
            return record
        raise _authority_error(
            "WORKER_LEASE_REVOCATION_CONFLICT",
            "worker lease was already revoked with different facts",
            pointer="/state",
        )
    # Revocation, like expiry, is authorization revocation only.
    return validate_worker_lease(
        {
            **record.as_dict(),
            "state": "REVOKED",
            "revoked_at_wall_ns": revoked_at,
            "revocation_reason": reason_value,
            "quiesced_at_wall_ns": None,
            "quiescence_evidence_sha256": None,
        }
    )


def validate_worker_lease_candidate(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]],
    *,
    task_id: str,
    node_instance_id: str,
    repository_id: str,
    worktree_identity_sha256: str,
    attempt: int,
    lease_nonce: str,
    current_attempt: int,
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
) -> WorkerLeaseRecord:
    record = validate_worker_lease(lease)
    expected_attempt = _authority_require_int(
        current_attempt, "/current_attempt", minimum=1
    )
    submitted_attempt = _authority_require_int(
        attempt, "/attempt", minimum=1
    )
    if (
        submitted_attempt != expected_attempt
        or record.attempt != expected_attempt
    ):
        raise _authority_error(
            "WORKER_LEASE_STALE_ATTEMPT",
            "candidate output belongs to a superseded attempt",
            pointer="/attempt",
            details={
                "lease_attempt": record.attempt,
                "submitted_attempt": submitted_attempt,
                "current_attempt": expected_attempt,
            },
        )
    comparisons = (
        ("task_id", record.task_id, task_id),
        ("node_instance_id", record.node_instance_id, node_instance_id),
        ("repository_id", record.repository_id, repository_id),
        (
            "worktree_identity_sha256",
            record.worktree_identity_sha256,
            worktree_identity_sha256,
        ),
    )
    for field, expected, actual in comparisons:
        if not isinstance(actual, str) or not hmac.compare_digest(
            expected, actual
        ):
            raise _authority_error(
                "WORKER_LEASE_SCOPE_MISMATCH",
                "candidate output is outside the worker lease scope",
                pointer=f"/{field}",
            )
    if not isinstance(lease_nonce, str) or not hmac.compare_digest(
        record.lease_nonce, lease_nonce
    ):
        raise _authority_error(
            "WORKER_LEASE_NONCE_MISMATCH",
            "candidate output does not identify the current lease",
            pointer="/lease_nonce",
        )
    status = worker_lease_status(
        record,
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
    )
    if not status.authorized:
        code = (
            status.blocker_codes[0]
            if status.blocker_codes
            else "WORKER_LEASE_INACTIVE"
        )
        raise _authority_error(
            code,
            "candidate output was produced under an inactive lease",
            pointer="/lease_id",
        )
    return record


def worker_lease_credential(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]]
) -> WorkerLeaseCredential:
    record = validate_worker_lease(lease)
    payload = {
        "schema": WORKER_LEASE_CREDENTIAL_SCHEMA,
        "lease_id": record.lease_id,
        "lease_nonce": record.lease_nonce,
        "task_id": record.task_id,
        "workflow_bundle_sha256": record.workflow_bundle_sha256,
        "node_instance_id": record.node_instance_id,
        "repository_id": record.repository_id,
        "worktree_identity_sha256": record.worktree_identity_sha256,
        "attempt": record.attempt,
        "allowed_actions": list(record.allowed_actions),
        "expires_at_wall_ns": record.expires_at_wall_ns,
        "mutation_authority": "none",
    }
    credential_id = "worker-credential:" + _authority_digest(
        _authority_lease_credential_domain, payload
    )
    payload["allowed_actions"] = tuple(payload["allowed_actions"])
    return WorkerLeaseCredential(
        credential_id=credential_id, **payload
    )


def validate_worker_lease_credential(
    value: Union[WorkerLeaseCredential, Mapping[str, object]]
) -> WorkerLeaseCredential:
    source = (
        value.as_dict()
        if isinstance(value, WorkerLeaseCredential)
        else _authority_require_mapping(value, "/lease_credential")
    )
    _authority_reject_unknown(
        source, _worker_lease_credential_fields, "/lease_credential"
    )
    missing = sorted(_worker_lease_credential_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "worker lease credential is missing fields",
            pointer="/lease_credential",
            details={"fields": missing},
        )
    schema = _authority_require_string(
        source["schema"], "/lease_credential/schema"
    )
    if schema != WORKER_LEASE_CREDENTIAL_SCHEMA:
        raise _authority_error(
            "WORKER_LEASE_CREDENTIAL_SCHEMA_UNSUPPORTED",
            "worker lease credential schema is unsupported",
            pointer="/lease_credential/schema",
        )
    payload = {
        "schema": schema,
        "lease_id": _authority_require_string(
            source["lease_id"],
            "/lease_credential/lease_id",
            stable_id=True,
        ),
        "lease_nonce": _authority_require_string(
            source["lease_nonce"], "/lease_credential/lease_nonce"
        ),
        "task_id": _authority_require_string(
            source["task_id"],
            "/lease_credential/task_id",
            stable_id=True,
        ),
        "workflow_bundle_sha256": _authority_require_digest(
            source["workflow_bundle_sha256"],
            "/lease_credential/workflow_bundle_sha256",
        ),
        "node_instance_id": _authority_require_string(
            source["node_instance_id"],
            "/lease_credential/node_instance_id",
            stable_id=True,
        ),
        "repository_id": _authority_require_string(
            source["repository_id"],
            "/lease_credential/repository_id",
            stable_id=True,
        ),
        "worktree_identity_sha256": _authority_require_digest(
            source["worktree_identity_sha256"],
            "/lease_credential/worktree_identity_sha256",
        ),
        "attempt": _authority_require_int(
            source["attempt"],
            "/lease_credential/attempt",
            minimum=1,
        ),
        "allowed_actions": list(
            _authority_require_canonical_strings(
                source["allowed_actions"],
                "/lease_credential/allowed_actions",
                stable_ids=True,
            )
        ),
        "expires_at_wall_ns": _authority_require_int(
            source["expires_at_wall_ns"],
            "/lease_credential/expires_at_wall_ns",
        ),
        "mutation_authority": _authority_require_string(
            source["mutation_authority"],
            "/lease_credential/mutation_authority",
        ),
    }
    if payload["mutation_authority"] != "none":
        raise _authority_error(
            "WORKER_MUTATION_AUTHORITY_FORBIDDEN",
            "worker lease credentials never grant controller mutation",
            pointer="/lease_credential/mutation_authority",
        )
    unknown_actions = sorted(
        set(payload["allowed_actions"]) - WORKER_EXECUTOR_CAPABILITIES,
        key=_authority_utf8_key,
    )
    if unknown_actions:
        raise _authority_error(
            "WORKER_CAPABILITY_FORBIDDEN",
            "worker credential contains an unknown or mutating capability",
            pointer="/lease_credential/allowed_actions",
            details={"capabilities": unknown_actions},
        )
    nonce = payload["lease_nonce"]
    if not isinstance(nonce, str) or not _authority_request_nonce_re.fullmatch(
        nonce
    ):
        raise _authority_error(
            "WORKER_LEASE_NONCE_INVALID",
            "lease nonce must encode 256 bits as lowercase hex",
            pointer="/lease_credential/lease_nonce",
        )
    credential_id = _authority_require_string(
        source["credential_id"],
        "/lease_credential/credential_id",
        stable_id=True,
    )
    expected_id = "worker-credential:" + _authority_digest(
        _authority_lease_credential_domain, payload
    )
    if not hmac.compare_digest(credential_id, expected_id):
        raise _authority_error(
            "WORKER_LEASE_CREDENTIAL_IDENTITY_MISMATCH",
            "worker lease credential identity does not match content",
            pointer="/lease_credential/credential_id",
        )
    return WorkerLeaseCredential(
        credential_id=credential_id,
        allowed_actions=tuple(payload.pop("allowed_actions")),
        **payload,
    )


def _worker_assignment_identity_payload(
    assignment: WorkerAssignment,
) -> dict[str, object]:
    payload = assignment.as_dict()
    payload.pop("assignment_id")
    return payload


def validate_worker_assignment(
    value: Union[WorkerAssignment, Mapping[str, object]]
) -> WorkerAssignment:
    source = (
        value.as_dict()
        if isinstance(value, WorkerAssignment)
        else _authority_require_mapping(value, "/")
    )
    _authority_reject_unknown(source, _worker_assignment_fields, "/")
    missing = sorted(
        _worker_assignment_fields
        - _worker_assignment_optional_fields
        - set(source)
    )
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "worker assignment is missing required fields",
            details={"fields": missing},
        )
    schema = _authority_require_string(source["schema"], "/schema")
    if schema != WORKER_ASSIGNMENT_SCHEMA:
        raise _authority_error(
            "WORKER_ASSIGNMENT_SCHEMA_UNSUPPORTED",
            "worker assignment schema is unsupported",
            pointer="/schema",
        )
    assignment_id = _authority_require_string(
        source["assignment_id"], "/assignment_id", stable_id=True
    )
    task_id = _authority_require_string(
        source["task_id"], "/task_id", stable_id=True
    )
    expected_revision = _authority_require_int(
        source["expected_revision"], "/expected_revision"
    )
    bundle = _authority_require_digest(
        source["workflow_bundle_sha256"],
        "/workflow_bundle_sha256",
    )
    map_epoch = _authority_require_int(
        source["map_epoch"], "/map_epoch", minimum=1
    )
    node_id = _authority_require_string(
        source["node_id"], "/node_id", stable_id=True
    )
    node_instance_id = _authority_require_string(
        source["node_instance_id"],
        "/node_instance_id",
        stable_id=True,
    )
    attempt = _authority_require_int(
        source["attempt"], "/attempt", minimum=1
    )
    repository_id = _authority_require_string(
        source["repository_id"], "/repository_id", stable_id=True
    )
    repository_identity = _authority_require_digest(
        source["repository_identity_sha256"],
        "/repository_identity_sha256",
    )
    worktree_path = _authority_require_worktree_path(
        source["worktree_path"], "/worktree_path"
    )
    worktree_identity = _authority_require_digest(
        source["worktree_identity_sha256"],
        "/worktree_identity_sha256",
    )
    controller_claim = _authority_require_digest(
        source["controller_claim_sha256"],
        "/controller_claim_sha256",
    )
    approved_paths = _authority_require_approved_paths(
        source["approved_paths"], "/approved_paths"
    )
    write_policy = _authority_require_string(
        source["write_policy"], "/write_policy"
    )
    if write_policy not in WORKER_WRITE_POLICIES:
        raise _authority_error(
            "WORKER_WRITE_POLICY_UNSUPPORTED",
            "worker write policy is unsupported",
            pointer="/write_policy",
        )
    plan_id = _authority_require_string(
        source["plan_id"], "/plan_id", stable_id=True
    )
    plan_artifact = _authority_require_digest(
        source["plan_artifact_sha256"], "/plan_artifact_sha256"
    )
    dag_digest = _authority_require_digest(
        source["plan_dag_sha256"], "/plan_dag_sha256"
    )
    semantic_digest = _authority_require_digest(
        source["semantic_input_sha256"], "/semantic_input_sha256"
    )
    contracts = _authority_require_canonical_strings(
        source["interface_contract_sha256s"],
        "/interface_contract_sha256s",
        digests=True,
    )
    input_digest = _authority_require_digest(
        source["input_evidence_sha256"], "/input_evidence_sha256"
    )
    credential = validate_worker_lease_credential(
        source["lease_credential"]
    )
    capabilities = _authority_require_canonical_strings(
        source["capabilities"], "/capabilities", stable_ids=True
    )
    _validate_worker_scope(write_policy, approved_paths, capabilities)
    playbook_locator = _authority_portable_relative_path(
        source["playbook_locator"], "/playbook_locator"
    )
    playbook_digest = _authority_require_digest(
        source["playbook_sha256"], "/playbook_sha256"
    )
    required_evidence = _authority_require_canonical_strings(
        source["required_evidence_contract_sha256s"],
        "/required_evidence_contract_sha256s",
        digests=True,
    )
    external_tool_grants = _authority_require_canonical_strings(
        source.get("external_tool_grant_sha256s", ()),
        "/external_tool_grant_sha256s",
        digests=True,
    )
    role_profile_value = source.get(
        "external_tool_role_profile_sha256"
    )
    role_profile_sha256 = (
        None
        if role_profile_value is None
        else _authority_require_digest(
            role_profile_value,
            "/external_tool_role_profile_sha256",
        )
    )
    if role_profile_sha256 is not None and not external_tool_grants:
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_PROFILE_UNBOUND",
            "worker role profile requires an assigned external-tool grant",
            pointer="/external_tool_role_profile_sha256",
        )
    assignment = WorkerAssignment(
        schema=schema,
        assignment_id=assignment_id,
        task_id=task_id,
        expected_revision=expected_revision,
        workflow_bundle_sha256=bundle,
        map_epoch=map_epoch,
        node_id=node_id,
        node_instance_id=node_instance_id,
        attempt=attempt,
        repository_id=repository_id,
        repository_identity_sha256=repository_identity,
        worktree_path=worktree_path,
        worktree_identity_sha256=worktree_identity,
        controller_claim_sha256=controller_claim,
        approved_paths=approved_paths,
        write_policy=write_policy,
        plan_id=plan_id,
        plan_artifact_sha256=plan_artifact,
        plan_dag_sha256=dag_digest,
        semantic_input_sha256=semantic_digest,
        interface_contract_sha256s=contracts,
        input_evidence_sha256=input_digest,
        lease_credential=credential,
        capabilities=capabilities,
        playbook_locator=playbook_locator,
        playbook_sha256=playbook_digest,
        required_evidence_contract_sha256s=required_evidence,
        external_tool_grant_sha256s=external_tool_grants,
        external_tool_role_profile_sha256=role_profile_sha256,
    )
    lease_matches = (
        ("task_id", task_id, credential.task_id),
        (
            "workflow_bundle_sha256",
            bundle,
            credential.workflow_bundle_sha256,
        ),
        ("node_instance_id", node_instance_id, credential.node_instance_id),
        ("repository_id", repository_id, credential.repository_id),
        (
            "worktree_identity_sha256",
            worktree_identity,
            credential.worktree_identity_sha256,
        ),
        ("attempt", attempt, credential.attempt),
        ("capabilities", capabilities, credential.allowed_actions),
    )
    for field, assignment_value, credential_value in lease_matches:
        if assignment_value != credential_value:
            raise _authority_error(
                "WORKER_ASSIGNMENT_LEASE_MISMATCH",
                "assignment does not exactly match its lease credential",
                pointer=f"/{field}",
            )
    expected_id = "worker-assignment:" + _authority_digest(
        _authority_assignment_domain,
        _worker_assignment_identity_payload(assignment),
    )
    if not hmac.compare_digest(assignment_id, expected_id):
        raise _authority_error(
            "WORKER_ASSIGNMENT_IDENTITY_MISMATCH",
            "worker assignment identity does not match canonical content",
            pointer="/assignment_id",
            details={"expected": expected_id, "actual": assignment_id},
        )
    return assignment


def create_worker_assignment(
    lease: Union[WorkerLeaseRecord, Mapping[str, object]],
    *,
    node_id: str,
    worktree_path: str,
    controller_claim_sha256: str,
    plan_id: str,
    plan_artifact_sha256: str,
    playbook_locator: str,
    playbook_sha256: str,
    required_evidence_contract_sha256s: Sequence[str],
    external_tool_grants: Sequence[object] = (),
    external_tool_role_profile: object = None,
) -> WorkerAssignment:
    record = validate_worker_lease(lease)
    if record.state != "ACTIVE":
        raise _authority_error(
            "WORKER_LEASE_INACTIVE",
            "worker assignment requires an active persisted lease",
            pointer="/lease/state",
        )
    credential = worker_lease_credential(record)
    grant_type = globals().get("ExternalToolExecutionGrant")
    role_profile_type = globals().get("ExternalToolRoleProfile")
    normalized_grants = tuple(external_tool_grants)
    if any(
        grant_type is None or not isinstance(item, grant_type)
        for item in normalized_grants
    ):
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_GRANT_INVALID",
            "worker external-tool grants must be verified contracts",
            pointer="/external_tool_grants",
        )
    grant_sha256s = tuple(
        sorted(item.sha256 for item in normalized_grants)
    )
    if len(grant_sha256s) != len(set(grant_sha256s)):
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_GRANT_INVALID",
            "worker external-tool grants must be unique",
            pointer="/external_tool_grants",
        )
    for grant in normalized_grants:
        mismatches = [
            field
            for field, expected, actual in (
                ("task_id", record.task_id, grant.task_id),
                (
                    "workflow_bundle_sha256",
                    record.workflow_bundle_sha256,
                    grant.workflow_bundle_sha256,
                ),
                (
                    "node_instance_id",
                    record.node_instance_id,
                    grant.node_instance_id,
                ),
                (
                    "repository_id",
                    record.repository_id,
                    grant.binding.repository_id,
                ),
                (
                    "expected_revision",
                    record.task_revision,
                    grant.assignment.controller_revision,
                ),
                ("attempt", record.attempt, grant.attempt),
            )
            if expected != actual
        ]
        if mismatches:
            raise _authority_error(
                "WORKER_EXTERNAL_TOOL_BINDING_MISMATCH",
                "worker lease and external-tool grant differ",
                details={"fields": mismatches},
            )
    if external_tool_role_profile is None:
        role_profile_sha256 = None
    else:
        if (
            role_profile_type is None
            or not isinstance(
                external_tool_role_profile, role_profile_type
            )
        ):
            raise _authority_error(
                "WORKER_EXTERNAL_TOOL_PROFILE_INVALID",
                "worker external-tool role profile is not verified",
            )
        role_profile_sha256 = external_tool_role_profile.sha256
        if not normalized_grants or any(
            grant.role_profile_sha256 != role_profile_sha256
            for grant in normalized_grants
        ):
            raise _authority_error(
                "WORKER_EXTERNAL_TOOL_PROFILE_MISMATCH",
                "worker grants do not bind the supplied role profile",
            )
    provisional = {
        "schema": WORKER_ASSIGNMENT_SCHEMA,
        "assignment_id": "worker-assignment:" + "0" * 64,
        "task_id": record.task_id,
        "expected_revision": record.task_revision,
        "workflow_bundle_sha256": record.workflow_bundle_sha256,
        "map_epoch": record.map_epoch,
        "node_id": node_id,
        "node_instance_id": record.node_instance_id,
        "attempt": record.attempt,
        "repository_id": record.repository_id,
        "repository_identity_sha256": (
            record.repository_identity_sha256
        ),
        "worktree_path": worktree_path,
        "worktree_identity_sha256": record.worktree_identity_sha256,
        "controller_claim_sha256": controller_claim_sha256,
        "approved_paths": list(record.approved_paths),
        "write_policy": record.write_policy,
        "plan_id": plan_id,
        "plan_artifact_sha256": plan_artifact_sha256,
        "plan_dag_sha256": record.plan_dag_sha256,
        "semantic_input_sha256": record.semantic_input_sha256,
        "interface_contract_sha256s": list(
            record.interface_contract_sha256s
        ),
        "input_evidence_sha256": record.input_evidence_sha256,
        "lease_credential": credential.as_dict(),
        "capabilities": list(record.allowed_actions),
        "playbook_locator": playbook_locator,
        "playbook_sha256": playbook_sha256,
        "required_evidence_contract_sha256s": list(
            required_evidence_contract_sha256s
        ),
    }
    if grant_sha256s:
        provisional["external_tool_grant_sha256s"] = list(
            grant_sha256s
        )
    if role_profile_sha256 is not None:
        provisional["external_tool_role_profile_sha256"] = (
            role_profile_sha256
        )
    # Validate every field before deriving the final content identity.
    shadow = dict(provisional)
    shadow["assignment_id"] = "worker-assignment:" + "1" * 64
    try:
        validate_worker_assignment(shadow)
    except OrchestrationAuthorityError as exc:
        if exc.code != "WORKER_ASSIGNMENT_IDENTITY_MISMATCH":
            raise
        expected_id = exc.details.get("expected")
        if not isinstance(expected_id, str):
            raise
    else:
        raise AssertionError("placeholder assignment unexpectedly validated")
    provisional["assignment_id"] = expected_id
    return validate_worker_assignment(provisional)


def validate_worker_external_tool_grant(
    assignment: Union[WorkerAssignment, Mapping[str, object]],
    grant: object,
    *,
    role_profile: object = None,
) -> object:
    """Validate one separately transported grant against a worker."""

    worker = validate_worker_assignment(assignment)
    grant_type = globals().get("ExternalToolExecutionGrant")
    role_profile_type = globals().get("ExternalToolRoleProfile")
    if grant_type is None or not isinstance(grant, grant_type):
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_GRANT_INVALID",
            "worker external-tool grant is not a verified contract",
        )
    if grant.sha256 not in worker.external_tool_grant_sha256s:
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_GRANT_UNASSIGNED",
            "external-tool grant is absent from the worker assignment",
        )
    mismatches = [
        field
        for field, expected, actual in (
            ("task_id", worker.task_id, grant.task_id),
            (
                "workflow_bundle_sha256",
                worker.workflow_bundle_sha256,
                grant.workflow_bundle_sha256,
            ),
            (
                "node_instance_id",
                worker.node_instance_id,
                grant.node_instance_id,
            ),
            (
                "repository_id",
                worker.repository_id,
                grant.binding.repository_id,
            ),
            (
                "expected_revision",
                worker.expected_revision,
                grant.assignment.controller_revision,
            ),
            ("attempt", worker.attempt, grant.attempt),
        )
        if expected != actual
    ]
    if mismatches:
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_BINDING_MISMATCH",
            "worker assignment and external-tool grant differ",
            details={"fields": mismatches},
        )
    expected_profile = worker.external_tool_role_profile_sha256
    if expected_profile is None:
        if role_profile is not None or grant.role_profile_sha256 is not None:
            raise _authority_error(
                "WORKER_EXTERNAL_TOOL_PROFILE_MISMATCH",
                "worker assignment does not bind a role profile",
            )
    elif (
        role_profile_type is None
        or not isinstance(role_profile, role_profile_type)
        or role_profile.sha256 != expected_profile
        or grant.role_profile_sha256 != expected_profile
        or grant.capability.sha256
        not in role_profile.capability_sha256s
    ):
        raise _authority_error(
            "WORKER_EXTERNAL_TOOL_PROFILE_MISMATCH",
            "worker role profile does not expose the assigned tool",
        )
    return grant


def _manager_capability_scope_payload(
    verifier: ManagerCapabilityVerifier,
) -> dict[str, object]:
    return {
        "schema": verifier.schema,
        "task_id": verifier.task_id,
        "issued_for_task_revision": verifier.issued_for_task_revision,
        "manager_session_id": verifier.manager_session_id,
        "allowed_actions": list(verifier.allowed_actions),
        "issued_at_wall_ns": verifier.issued_at_wall_ns,
        "expires_at_wall_ns": verifier.expires_at_wall_ns,
        "issued_at_monotonic_ns": verifier.issued_at_monotonic_ns,
        "ttl_ns": verifier.ttl_ns,
        "clock_id": verifier.clock_id,
        "secret_transport": verifier.secret_transport,
        "operator_confirmation_sha256": (
            verifier.operator_confirmation_sha256
        ),
        "issuance_audit_sha256": verifier.issuance_audit_sha256,
    }


def _manager_capability_expected_id(
    scope: object, verifier_hmac_sha256: str
) -> str:
    payload = {
        "scope": scope,
        "verifier_hmac_sha256": verifier_hmac_sha256,
    }
    return "manager-capability:" + _authority_digest(
        _authority_capability_id_domain, payload
    )


def _manager_verifier_hmac(
    manager_secret: Union[bytes, bytearray], scope: object
) -> str:
    payload = canonical_orchestration_bytes(scope)
    message = (
        _authority_capability_verifier_domain
        + _authority_u64be(len(payload))
        + payload
    )
    return hmac.new(manager_secret, message, hashlib.sha256).hexdigest()


def validate_manager_capability_verifier(
    value: Union[ManagerCapabilityVerifier, Mapping[str, object]]
) -> ManagerCapabilityVerifier:
    source = (
        value.as_persistent_dict()
        if isinstance(value, ManagerCapabilityVerifier)
        else _authority_require_mapping(value, "/")
    )
    _authority_reject_unknown(source, _manager_capability_fields, "/")
    missing = sorted(_manager_capability_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "manager capability verifier is missing fields",
            details={"fields": missing},
        )
    schema = _authority_require_string(source["schema"], "/schema")
    if schema != MANAGER_CAPABILITY_SCHEMA:
        raise _authority_error(
            "MANAGER_CAPABILITY_SCHEMA_UNSUPPORTED",
            "manager capability schema is unsupported",
            pointer="/schema",
        )
    capability_id = _authority_require_string(
        source["capability_id"], "/capability_id", stable_id=True
    )
    task_id = _authority_require_string(
        source["task_id"], "/task_id", stable_id=True
    )
    issued_revision = _authority_require_int(
        source["issued_for_task_revision"],
        "/issued_for_task_revision",
    )
    session_id = _authority_require_string(
        source["manager_session_id"],
        "/manager_session_id",
        stable_id=True,
    )
    actions = _authority_require_canonical_strings(
        source["allowed_actions"],
        "/allowed_actions",
        stable_ids=True,
    )
    if not actions:
        raise _authority_error(
            "MANAGER_CAPABILITY_SCOPE_EMPTY",
            "manager capability requires at least one exact action",
            pointer="/allowed_actions",
        )
    if any(action == "*" or "*" in action for action in actions):
        raise _authority_error(
            "MANAGER_CAPABILITY_WILDCARD_FORBIDDEN",
            "manager capability actions cannot contain wildcards",
            pointer="/allowed_actions",
        )
    issued_wall = _authority_require_int(
        source["issued_at_wall_ns"], "/issued_at_wall_ns"
    )
    expires_wall = _authority_require_int(
        source["expires_at_wall_ns"], "/expires_at_wall_ns"
    )
    issued_monotonic = _authority_require_int(
        source["issued_at_monotonic_ns"],
        "/issued_at_monotonic_ns",
    )
    ttl = _authority_check_ttl(
        source["ttl_ns"],
        "/ttl_ns",
        MAX_MANAGER_CAPABILITY_TTL_NS,
    )
    if expires_wall - issued_wall != ttl:
        raise _authority_error(
            "MANAGER_CAPABILITY_TIME_INVALID",
            "capability wall-clock expiry must equal issuance plus TTL",
            pointer="/expires_at_wall_ns",
        )
    clock_id = _authority_require_string(
        source["clock_id"], "/clock_id", stable_id=True
    )
    transport = _authority_require_string(
        source["secret_transport"], "/secret_transport"
    )
    if transport not in MANAGER_SECRET_TRANSPORTS:
        raise _authority_error(
            "MANAGER_CAPABILITY_SECRET_TRANSPORT_FORBIDDEN",
            "manager proof must use a manager-scoped secret channel",
            pointer="/secret_transport",
        )
    confirmation = _authority_require_digest(
        source["operator_confirmation_sha256"],
        "/operator_confirmation_sha256",
    )
    issuance_audit = _authority_require_digest(
        source["issuance_audit_sha256"],
        "/issuance_audit_sha256",
    )
    verifier_hmac = _authority_require_digest(
        source["verifier_hmac_sha256"],
        "/verifier_hmac_sha256",
    )
    revoked_at = _authority_require_optional_int(
        source["revoked_at_wall_ns"], "/revoked_at_wall_ns"
    )
    revocation_reason = None
    if source["revocation_reason"] is not None:
        revocation_reason = _authority_require_string(
            source["revocation_reason"],
            "/revocation_reason",
            stable_id=True,
        )
    revocation_audit = _authority_require_optional_digest(
        source["revocation_audit_sha256"],
        "/revocation_audit_sha256",
    )
    revocation_fields_present = (
        revoked_at is not None,
        revocation_reason is not None,
        revocation_audit is not None,
    )
    if any(revocation_fields_present) and not all(
        revocation_fields_present
    ):
        raise _authority_error(
            "MANAGER_CAPABILITY_REVOCATION_INVALID",
            "revocation timestamp, reason, and audit digest appear together",
            pointer="/revoked_at_wall_ns",
        )
    used_requests = _authority_require_canonical_strings(
        source["used_request_nonce_sha256s"],
        "/used_request_nonce_sha256s",
        digests=True,
    )
    verifier = ManagerCapabilityVerifier(
        schema=schema,
        capability_id=capability_id,
        task_id=task_id,
        issued_for_task_revision=issued_revision,
        manager_session_id=session_id,
        allowed_actions=actions,
        issued_at_wall_ns=issued_wall,
        expires_at_wall_ns=expires_wall,
        issued_at_monotonic_ns=issued_monotonic,
        ttl_ns=ttl,
        clock_id=clock_id,
        secret_transport=transport,
        operator_confirmation_sha256=confirmation,
        issuance_audit_sha256=issuance_audit,
        verifier_hmac_sha256=verifier_hmac,
        revoked_at_wall_ns=revoked_at,
        revocation_reason=revocation_reason,
        revocation_audit_sha256=revocation_audit,
        used_request_nonce_sha256s=used_requests,
    )
    expected_id = _manager_capability_expected_id(
        _manager_capability_scope_payload(verifier), verifier_hmac
    )
    if not hmac.compare_digest(capability_id, expected_id):
        raise _authority_error(
            "MANAGER_CAPABILITY_IDENTITY_MISMATCH",
            "manager capability identity does not match verifier content",
            pointer="/capability_id",
        )
    return verifier


def issue_manager_capability(
    *,
    task_id: str,
    issued_for_task_revision: int,
    manager_session_id: str,
    allowed_actions: Sequence[str],
    ttl_ns: int,
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
    secret_transport: str,
    operator_confirmation_sha256: str,
    issuance_audit_sha256: str,
    manager_secret: Union[bytes, bytearray],
) -> ManagerCapabilityVerifier:
    """Issue verifier-only persistent material for a transient secret.

    The caller generates ``manager_secret`` using a cryptographic random source
    and retains it only in the selected manager-scoped secret channel.  This
    return value deliberately cannot reproduce or serialize that secret.
    """

    if not isinstance(manager_secret, (bytes, bytearray)) or len(
        manager_secret
    ) < MIN_MANAGER_SECRET_BYTES:
        raise _authority_error(
            "MANAGER_CAPABILITY_SECRET_TOO_SHORT",
            "controller must supply at least 256 random secret bits",
            pointer="/manager_secret",
        )
    wall, monotonic, current_clock = _authority_require_clock(
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
        prefix="/clock",
    )
    ttl = _authority_check_ttl(
        ttl_ns, "/ttl_ns", MAX_MANAGER_CAPABILITY_TTL_NS
    )
    if wall > _authority_signed_int64_max - ttl:
        raise _authority_error(
            "MANAGER_CAPABILITY_TIME_INVALID",
            "capability expiry exceeds the canonical integer range",
            pointer="/ttl_ns",
        )
    actions = _authority_require_canonical_strings(
        allowed_actions,
        "/allowed_actions",
        stable_ids=True,
    )
    provisional = ManagerCapabilityVerifier(
        schema=MANAGER_CAPABILITY_SCHEMA,
        capability_id="manager-capability:" + "0" * 64,
        task_id=_authority_require_string(
            task_id, "/task_id", stable_id=True
        ),
        issued_for_task_revision=_authority_require_int(
            issued_for_task_revision, "/issued_for_task_revision"
        ),
        manager_session_id=_authority_require_string(
            manager_session_id,
            "/manager_session_id",
            stable_id=True,
        ),
        allowed_actions=actions,
        issued_at_wall_ns=wall,
        expires_at_wall_ns=wall + ttl,
        issued_at_monotonic_ns=monotonic,
        ttl_ns=ttl,
        clock_id=current_clock,
        secret_transport=_authority_require_string(
            secret_transport, "/secret_transport"
        ),
        operator_confirmation_sha256=_authority_require_digest(
            operator_confirmation_sha256,
            "/operator_confirmation_sha256",
        ),
        issuance_audit_sha256=_authority_require_digest(
            issuance_audit_sha256, "/issuance_audit_sha256"
        ),
        verifier_hmac_sha256="0" * 64,
        revoked_at_wall_ns=None,
        revocation_reason=None,
        revocation_audit_sha256=None,
        used_request_nonce_sha256s=(),
    )
    scope = _manager_capability_scope_payload(provisional)
    verifier_hmac = _manager_verifier_hmac(manager_secret, scope)
    capability_id = _manager_capability_expected_id(
        scope, verifier_hmac
    )
    return validate_manager_capability_verifier(
        {
            **provisional.as_persistent_dict(),
            "capability_id": capability_id,
            "verifier_hmac_sha256": verifier_hmac,
        }
    )


def revoke_manager_capability(
    verifier: Union[
        ManagerCapabilityVerifier, Mapping[str, object]
    ],
    *,
    revoked_at_wall_ns: int,
    reason: str,
    revocation_audit_sha256: str,
) -> ManagerCapabilityVerifier:
    record = validate_manager_capability_verifier(verifier)
    revoked_at = _authority_require_int(
        revoked_at_wall_ns, "/revoked_at_wall_ns"
    )
    reason_value = _authority_require_string(
        reason, "/revocation_reason", stable_id=True
    )
    audit_digest = _authority_require_digest(
        revocation_audit_sha256, "/revocation_audit_sha256"
    )
    if revoked_at < record.issued_at_wall_ns:
        raise _authority_error(
            "MANAGER_CAPABILITY_TIME_INVALID",
            "revocation cannot predate capability issuance",
            pointer="/revoked_at_wall_ns",
        )
    if record.revoked_at_wall_ns is not None:
        if (
            record.revoked_at_wall_ns == revoked_at
            and record.revocation_reason == reason_value
            and record.revocation_audit_sha256 == audit_digest
        ):
            return record
        raise _authority_error(
            "MANAGER_CAPABILITY_REVOCATION_CONFLICT",
            "manager capability was already revoked with different facts",
            pointer="/revoked_at_wall_ns",
        )
    return validate_manager_capability_verifier(
        {
            **record.as_persistent_dict(),
            "revoked_at_wall_ns": revoked_at,
            "revocation_reason": reason_value,
            "revocation_audit_sha256": audit_digest,
        }
    )


def validate_manager_capability_request(
    value: Union[ManagerCapabilityRequest, Mapping[str, object]]
) -> ManagerCapabilityRequest:
    source = (
        value.as_dict()
        if isinstance(value, ManagerCapabilityRequest)
        else _authority_require_mapping(value, "/request")
    )
    _authority_reject_unknown(
        source, _manager_request_fields, "/request"
    )
    missing = sorted(_manager_request_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "manager capability request is missing fields",
            pointer="/request",
            details={"fields": missing},
        )
    schema = _authority_require_string(
        source["schema"], "/request/schema"
    )
    if schema != MANAGER_CAPABILITY_REQUEST_SCHEMA:
        raise _authority_error(
            "MANAGER_CAPABILITY_REQUEST_SCHEMA_UNSUPPORTED",
            "manager capability request schema is unsupported",
            pointer="/request/schema",
        )
    nonce = _authority_require_string(
        source["request_nonce"], "/request/request_nonce"
    )
    if not _authority_request_nonce_re.fullmatch(nonce):
        raise _authority_error(
            "MANAGER_CAPABILITY_REQUEST_NONCE_INVALID",
            "request nonce must encode 256 bits as lowercase hex",
            pointer="/request/request_nonce",
        )
    return ManagerCapabilityRequest(
        schema=schema,
        capability_id=_authority_require_string(
            source["capability_id"],
            "/request/capability_id",
            stable_id=True,
        ),
        task_id=_authority_require_string(
            source["task_id"], "/request/task_id", stable_id=True
        ),
        manager_session_id=_authority_require_string(
            source["manager_session_id"],
            "/request/manager_session_id",
            stable_id=True,
        ),
        action_id=_authority_require_string(
            source["action_id"],
            "/request/action_id",
            stable_id=True,
        ),
        expected_revision=_authority_require_int(
            source["expected_revision"],
            "/request/expected_revision",
        ),
        request_nonce=nonce,
    )


def validate_agent_principal(
    value: Union[AgentPrincipal, Mapping[str, object]]
) -> AgentPrincipal:
    source = (
        value.as_dict()
        if isinstance(value, AgentPrincipal)
        else _authority_require_mapping(value, "/principal")
    )
    _authority_reject_unknown(
        source, _agent_principal_fields, "/principal"
    )
    missing = sorted(_agent_principal_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "agent principal is missing fields",
            pointer="/principal",
            details={"fields": missing},
        )
    schema = _authority_require_string(
        source["schema"], "/principal/schema"
    )
    if schema != AGENT_PRINCIPAL_SCHEMA:
        raise _authority_error(
            "AGENT_PRINCIPAL_SCHEMA_UNSUPPORTED",
            "agent principal schema is unsupported",
            pointer="/principal/schema",
        )
    role = _authority_require_string(
        source["role"], "/principal/role"
    )
    if role not in AGENT_PRINCIPAL_ROLES:
        raise _authority_error(
            "AGENT_PRINCIPAL_ROLE_INVALID",
            "agent principal role is unsupported",
            pointer="/principal/role",
        )
    return AgentPrincipal(
        schema=schema,
        role=role,
        session_id=_authority_require_string(
            source["session_id"],
            "/principal/session_id",
            stable_id=True,
        ),
        os_user_identity_sha256=_authority_require_digest(
            source["os_user_identity_sha256"],
            "/principal/os_user_identity_sha256",
        ),
        host_identity_sha256=_authority_require_digest(
            source["host_identity_sha256"],
            "/principal/host_identity_sha256",
        ),
    )


def manager_request_fingerprint(
    request: Union[ManagerCapabilityRequest, Mapping[str, object]]
) -> str:
    parsed = validate_manager_capability_request(request)
    return _authority_digest(
        _authority_request_domain, parsed.as_dict()
    )


def manager_request_nonce_digest(
    request: Union[ManagerCapabilityRequest, Mapping[str, object]]
) -> str:
    parsed = validate_manager_capability_request(request)
    return _authority_digest(
        _authority_request_nonce_domain,
        {
            "capability_id": parsed.capability_id,
            "request_nonce": parsed.request_nonce,
        },
    )


def verify_manager_capability_replay_request(
    verifier: Union[
        ManagerCapabilityVerifier, Mapping[str, object]
    ],
    request: Union[ManagerCapabilityRequest, Mapping[str, object]],
    principal: Union[AgentPrincipal, Mapping[str, object]],
    *,
    manager_secret: Union[bytes, bytearray],
) -> ManagerAuthorization:
    """Authenticate recovery of an already-consumed manager request.

    This is intentionally not mutation authority. It accepts only a nonce
    already present in the persisted verifier and leaves that verifier
    unchanged. Expiry or later revocation therefore cannot erase a durable
    receipt, while the original principal, scope, and HMAC proof remain
    mandatory.
    """

    record = validate_manager_capability_verifier(verifier)
    candidate = validate_manager_capability_request(request)
    caller = validate_agent_principal(principal)
    if caller.role != "manager":
        raise _authority_error(
            "ORCHESTRATION_WORKER_MUTATION_DENIED",
            "only the designated manager may recover a manager receipt",
            pointer="/principal/role",
        )
    if caller.session_id != candidate.manager_session_id:
        raise _authority_error(
            "MANAGER_CAPABILITY_PRINCIPAL_MISMATCH",
            "authenticated principal does not own the request session",
            pointer="/principal/session_id",
        )
    comparisons = (
        (
            "capability_id",
            record.capability_id,
            candidate.capability_id,
            "MANAGER_CAPABILITY_ID_MISMATCH",
        ),
        (
            "task_id",
            record.task_id,
            candidate.task_id,
            "MANAGER_CAPABILITY_TASK_MISMATCH",
        ),
        (
            "manager_session_id",
            record.manager_session_id,
            candidate.manager_session_id,
            "MANAGER_CAPABILITY_SESSION_MISMATCH",
        ),
    )
    for field, expected, actual, code in comparisons:
        if not hmac.compare_digest(expected, actual):
            raise _authority_error(
                code,
                "manager capability request is outside its exact scope",
                pointer=f"/request/{field}",
            )
    if candidate.action_id not in record.allowed_actions:
        raise _authority_error(
            "MANAGER_CAPABILITY_ACTION_DENIED",
            "manager capability does not authorize this action",
            pointer="/request/action_id",
        )
    if not isinstance(manager_secret, (bytes, bytearray)) or len(
        manager_secret
    ) < MIN_MANAGER_SECRET_BYTES:
        raise _authority_error(
            "MANAGER_CAPABILITY_PROOF_INVALID",
            "manager proof is invalid",
            pointer="/manager_secret",
        )
    supplied_verifier = _manager_verifier_hmac(
        manager_secret, _manager_capability_scope_payload(record)
    )
    if not hmac.compare_digest(
        supplied_verifier, record.verifier_hmac_sha256
    ):
        raise _authority_error(
            "MANAGER_CAPABILITY_PROOF_INVALID",
            "manager proof is invalid",
            pointer="/manager_secret",
        )
    nonce_digest = manager_request_nonce_digest(candidate)
    if nonce_digest not in record.used_request_nonce_sha256s:
        raise _authority_error(
            "MANAGER_CAPABILITY_REQUEST_NOT_COMMITTED",
            "manager request nonce has not been consumed",
            pointer="/request/request_nonce",
        )
    fingerprint = manager_request_fingerprint(candidate)
    receipt_payload = {
        "schema": MANAGER_AUTHORIZATION_SCHEMA,
        "capability_id": record.capability_id,
        "task_id": candidate.task_id,
        "manager_session_id": candidate.manager_session_id,
        "action_id": candidate.action_id,
        "expected_revision": candidate.expected_revision,
        "request_fingerprint_sha256": fingerprint,
    }
    authorization_id = "manager-authorization:" + _authority_digest(
        _authority_authorization_domain, receipt_payload
    )
    return ManagerAuthorization(
        authorization_id=authorization_id,
        verifier_state=record,
        **receipt_payload,
    )


def consume_manager_capability_request(
    verifier: Union[
        ManagerCapabilityVerifier, Mapping[str, object]
    ],
    request: Union[ManagerCapabilityRequest, Mapping[str, object]],
    principal: Union[AgentPrincipal, Mapping[str, object]],
    *,
    manager_secret: Union[bytes, bytearray],
    wall_time_ns: int,
    monotonic_time_ns: int,
    clock_id: str,
) -> ManagerAuthorization:
    """Verify and consume one manager request nonce without side effects.

    Persistence of ``authorization.verifier_state`` and the authorized
    controller mutation must be one external atomic CAS transaction.
    """

    record = validate_manager_capability_verifier(verifier)
    candidate = validate_manager_capability_request(request)
    caller = validate_agent_principal(principal)
    if caller.role != "manager":
        raise _authority_error(
            "ORCHESTRATION_WORKER_MUTATION_DENIED",
            "only the designated manager may request agent-plane mutation",
            pointer="/principal/role",
        )
    if caller.session_id != candidate.manager_session_id:
        raise _authority_error(
            "MANAGER_CAPABILITY_PRINCIPAL_MISMATCH",
            "authenticated principal does not own the request session",
            pointer="/principal/session_id",
        )
    if record.revoked_at_wall_ns is not None:
        raise _authority_error(
            "MANAGER_CAPABILITY_REVOKED",
            "manager capability has been revoked",
            pointer="/capability_id",
        )
    wall, monotonic, current_clock = _authority_require_clock(
        wall_time_ns=wall_time_ns,
        monotonic_time_ns=monotonic_time_ns,
        clock_id=clock_id,
        prefix="/clock",
    )
    if current_clock != record.clock_id:
        raise _authority_error(
            "MANAGER_CAPABILITY_CLOCK_CONTEXT_MISMATCH",
            "manager capability cannot cross monotonic clock contexts",
            pointer="/clock/clock_id",
        )
    if (
        wall < record.issued_at_wall_ns
        or monotonic < record.issued_at_monotonic_ns
    ):
        raise _authority_error(
            "MANAGER_CAPABILITY_CLOCK_ROLLBACK",
            "manager capability clock moved before issuance",
            pointer="/clock",
        )
    if (
        wall >= record.expires_at_wall_ns
        or monotonic - record.issued_at_monotonic_ns >= record.ttl_ns
    ):
        raise _authority_error(
            "MANAGER_CAPABILITY_EXPIRED",
            "manager capability has expired",
            pointer="/capability_id",
        )
    comparisons = (
        (
            "capability_id",
            record.capability_id,
            candidate.capability_id,
            "MANAGER_CAPABILITY_ID_MISMATCH",
        ),
        (
            "task_id",
            record.task_id,
            candidate.task_id,
            "MANAGER_CAPABILITY_TASK_MISMATCH",
        ),
        (
            "manager_session_id",
            record.manager_session_id,
            candidate.manager_session_id,
            "MANAGER_CAPABILITY_SESSION_MISMATCH",
        ),
    )
    for field, expected, actual, code in comparisons:
        if not hmac.compare_digest(expected, actual):
            raise _authority_error(
                code,
                "manager capability request is outside its exact scope",
                pointer=f"/request/{field}",
            )
    if candidate.action_id not in record.allowed_actions:
        raise _authority_error(
            "MANAGER_CAPABILITY_ACTION_DENIED",
            "manager capability does not authorize this action",
            pointer="/request/action_id",
        )
    if not isinstance(manager_secret, (bytes, bytearray)) or len(
        manager_secret
    ) < MIN_MANAGER_SECRET_BYTES:
        raise _authority_error(
            "MANAGER_CAPABILITY_PROOF_INVALID",
            "manager proof is invalid",
            pointer="/manager_secret",
        )
    supplied_verifier = _manager_verifier_hmac(
        manager_secret, _manager_capability_scope_payload(record)
    )
    if not hmac.compare_digest(
        supplied_verifier, record.verifier_hmac_sha256
    ):
        raise _authority_error(
            "MANAGER_CAPABILITY_PROOF_INVALID",
            "manager proof is invalid",
            pointer="/manager_secret",
        )
    fingerprint = manager_request_fingerprint(candidate)
    nonce_digest = manager_request_nonce_digest(candidate)
    if nonce_digest in record.used_request_nonce_sha256s:
        raise _authority_error(
            "MANAGER_CAPABILITY_REQUEST_REPLAYED",
            "manager request nonce has already been consumed",
            pointer="/request/request_nonce",
        )
    used = tuple(
        sorted(
            (*record.used_request_nonce_sha256s, nonce_digest),
            key=_authority_utf8_key,
        )
    )
    next_state = validate_manager_capability_verifier(
        {
            **record.as_persistent_dict(),
            "used_request_nonce_sha256s": list(used),
        }
    )
    receipt_payload = {
        "schema": MANAGER_AUTHORIZATION_SCHEMA,
        "capability_id": record.capability_id,
        "task_id": candidate.task_id,
        "manager_session_id": candidate.manager_session_id,
        "action_id": candidate.action_id,
        "expected_revision": candidate.expected_revision,
        "request_fingerprint_sha256": fingerprint,
    }
    authorization_id = "manager-authorization:" + _authority_digest(
        _authority_authorization_domain, receipt_payload
    )
    return ManagerAuthorization(
        authorization_id=authorization_id,
        verifier_state=next_state,
        **receipt_payload,
    )


def validate_host_capability_report(
    value: Union[HostCapabilityReport, Mapping[str, object]]
) -> HostCapabilityReport:
    source = (
        value.as_dict()
        if isinstance(value, HostCapabilityReport)
        else _authority_require_mapping(value, "/")
    )
    _authority_reject_unknown(
        source, _host_capability_report_fields, "/"
    )
    missing = sorted(_host_capability_report_fields - set(source))
    if missing:
        raise _authority_error(
            "ORCHESTRATION_FIELD_MISSING",
            "host capability report is missing fields",
            details={"fields": missing},
        )
    schema = _authority_require_string(source["schema"], "/schema")
    if schema != HOST_CAPABILITY_REPORT_SCHEMA:
        raise _authority_error(
            "HOST_CAPABILITY_REPORT_SCHEMA_UNSUPPORTED",
            "host capability report schema is unsupported",
            pointer="/schema",
        )
    return HostCapabilityReport(
        schema=schema,
        adapter_id=_authority_require_string(
            source["adapter_id"], "/adapter_id", stable_id=True
        ),
        assignment_id=_authority_require_string(
            source["assignment_id"],
            "/assignment_id",
            stable_id=True,
        ),
        worker_session_id=_authority_require_string(
            source["worker_session_id"],
            "/worker_session_id",
            stable_id=True,
        ),
        worker_identity_sha256=_authority_require_digest(
            source["worker_identity_sha256"],
            "/worker_identity_sha256",
        ),
        attestation_sha256=_authority_require_digest(
            source["attestation_sha256"], "/attestation_sha256"
        ),
        host_enforced=_authority_require_bool(
            source["host_enforced"], "/host_enforced"
        ),
        allowed_write_identity_sha256s=(
            _authority_require_canonical_strings(
                source["allowed_write_identity_sha256s"],
                "/allowed_write_identity_sha256s",
                digests=True,
            )
        ),
        denied_read_identity_sha256s=(
            _authority_require_canonical_strings(
                source["denied_read_identity_sha256s"],
                "/denied_read_identity_sha256s",
                digests=True,
            )
        ),
        denied_tool_ids=_authority_require_canonical_strings(
            source["denied_tool_ids"],
            "/denied_tool_ids",
            stable_ids=True,
        ),
        all_other_writes_denied=_authority_require_bool(
            source["all_other_writes_denied"],
            "/all_other_writes_denied",
        ),
        manager_secret_channel_excluded=_authority_require_bool(
            source["manager_secret_channel_excluded"],
            "/manager_secret_channel_excluded",
        ),
        controller_state_excluded=_authority_require_bool(
            source["controller_state_excluded"],
            "/controller_state_excluded",
        ),
        mutation_tools_excluded=_authority_require_bool(
            source["mutation_tools_excluded"],
            "/mutation_tools_excluded",
        ),
    )


def evaluate_host_isolation(
    report: Union[HostCapabilityReport, Mapping[str, object]],
    assignment: Union[WorkerAssignment, Mapping[str, object]],
    *,
    trusted_adapter_ids: Sequence[str],
    protected_read_identity_sha256s: Sequence[str],
    mutating_tool_ids: Sequence[str],
) -> HostIsolationDecision:
    """Evaluate host-enforced writable-worker separation.

    Insufficient or unverifiable separation produces a deterministic serial
    fallback.  The trusted adapter list and protected identities are supplied
    by the controller, never by a workflow bundle or worker.
    """

    attestation = validate_host_capability_report(report)
    work = validate_worker_assignment(assignment)
    trusted = set(
        _authority_require_canonical_strings(
            trusted_adapter_ids,
            "/trusted_adapter_ids",
            stable_ids=True,
        )
    )
    protected = set(
        _authority_require_canonical_strings(
            protected_read_identity_sha256s,
            "/protected_read_identity_sha256s",
            digests=True,
        )
    )
    mutating = set(
        _authority_require_canonical_strings(
            mutating_tool_ids,
            "/mutating_tool_ids",
            stable_ids=True,
        )
    )
    blockers = []
    if attestation.assignment_id != work.assignment_id:
        blockers.append("HOST_ASSIGNMENT_MISMATCH")
    if attestation.adapter_id not in trusted:
        blockers.append("HOST_ADAPTER_UNTRUSTED")
    if not attestation.host_enforced:
        blockers.append("HOST_BOUNDARY_NOT_ENFORCED")
    if not attestation.manager_secret_channel_excluded:
        blockers.append("HOST_MANAGER_SECRET_NOT_EXCLUDED")
    if not attestation.controller_state_excluded:
        blockers.append("HOST_CONTROLLER_STATE_NOT_EXCLUDED")
    if not attestation.mutation_tools_excluded:
        blockers.append("HOST_MUTATION_TOOLS_NOT_EXCLUDED")
    if not protected.issubset(
        attestation.denied_read_identity_sha256s
    ):
        blockers.append("HOST_PROTECTED_READ_SCOPE_INCOMPLETE")
    if not mutating.issubset(attestation.denied_tool_ids):
        blockers.append("HOST_MUTATION_TOOL_SCOPE_INCOMPLETE")
    expected_write_identities = (
        {work.worktree_identity_sha256}
        if work.write_policy == "scoped-write"
        else set()
    )
    if expected_write_identities & protected:
        blockers.append("HOST_PROTECTED_RESOURCE_WRITE_OVERLAP")
    if (
        set(attestation.allowed_write_identity_sha256s)
        != expected_write_identities
        or not attestation.all_other_writes_denied
    ):
        blockers.append("HOST_WRITE_SCOPE_NOT_EXACT")
    ordered_blockers = tuple(
        sorted(set(blockers), key=_authority_utf8_key)
    )
    if ordered_blockers:
        return HostIsolationDecision(
            schema=HOST_ISOLATION_DECISION_SCHEMA,
            assignment_id=work.assignment_id,
            parallel_dispatch_allowed=False,
            dispatch_mode="manager-serial",
            blocker_codes=ordered_blockers,
        )
    return HostIsolationDecision(
        schema=HOST_ISOLATION_DECISION_SCHEMA,
        assignment_id=work.assignment_id,
        parallel_dispatch_allowed=True,
        dispatch_mode=(
            "parallel-writable-worker"
            if work.write_policy == "scoped-write"
            else "parallel-read-only-worker"
        ),
        blocker_codes=(),
    )
