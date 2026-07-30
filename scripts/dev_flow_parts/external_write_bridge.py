"""Opaque workflow authorization and host-owned external-write bridge.

The controller may issue an in-process authorization, but it cannot approve a
provider write on behalf of the host.  This module enforces those boundaries
serially and consumes every authorization before asking the host to approve
the exact request.  It contains no provider-specific code.
"""
from __future__ import annotations

import hashlib as _external_write_hashlib
import hmac as _external_write_hmac
import json as _external_write_json
import math as _external_write_math
import re as _external_write_re
import secrets as _external_write_secrets
import struct as _external_write_struct
import threading as _external_write_threading
import time as _external_write_time
import unicodedata as _external_write_unicodedata
from dataclasses import dataclass as _external_write_dataclass
from types import MappingProxyType as _ExternalWriteMappingProxyType
from typing import (
    Callable as _ExternalWriteCallable,
    Mapping as _ExternalWriteMapping,
    Optional as _ExternalWriteOptional,
)


WORKFLOW_WRITE_GATE_SCHEMA = "dev-flow-workflow-write-gate/v1"
WORKFLOW_WRITE_BINDING_SCHEMA = "dev-flow-workflow-write-binding/v1"
EXTERNAL_WRITE_INVOCATION_RECEIPT_SCHEMA = (
    "dev-flow-external-write-invocation-receipt/v1"
)

_external_write_digest_re = _external_write_re.compile(
    r"^[0-9a-f]{64}$"
)
_external_write_stable_id_re = _external_write_re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$"
)
_external_write_gate_decisions = frozenset({"approved", "denied"})
_EXTERNAL_WRITE_AUTHORIZATION_DOMAIN = (
    b"dev-flow-workflow-write-authorization/v1"
)
_EXTERNAL_WRITE_REQUEST_DOMAIN = "dev-flow-external-write-request/v1"
_EXTERNAL_WRITE_TARGET_DOMAIN = "dev-flow-external-write-target/v1"
_EXTERNAL_WRITE_RECEIPT_DOMAIN = (
    "dev-flow-external-write-invocation-receipt/v1"
)


class ExternalWriteError(RuntimeError):
    """Stable fail-closed diagnostic for the serial write boundary."""

    __slots__ = ("code", "message", "details")

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _ExternalWriteOptional[
            _ExternalWriteMapping[str, object]
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


class ExternalWriteUnavailable(ExternalWriteError):
    """Raised when no host-owned serial bridge is installed."""


def _external_write_error(
    code: str,
    message: str,
    *,
    field: _ExternalWriteOptional[str] = None,
    details: _ExternalWriteOptional[
        _ExternalWriteMapping[str, object]
    ] = None,
) -> ExternalWriteError:
    payload = dict(details or {})
    if field is not None:
        payload.setdefault("field", field)
    return ExternalWriteError(code, message, details=payload)


def _external_write_require_nfc(value: str, field: str) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise _external_write_error(
            "EXTERNAL_WRITE_STRING_INVALID",
            "external-write strings must be valid UTF-8",
            field=field,
        ) from exc
    if _external_write_unicodedata.normalize("NFC", value) != value:
        raise _external_write_error(
            "EXTERNAL_WRITE_STRING_NOT_CANONICAL",
            "external-write strings must already use NFC normalization",
            field=field,
        )
    if len(encoded) > 65536:
        raise _external_write_error(
            "EXTERNAL_WRITE_STRING_TOO_LARGE",
            "external-write string exceeds its UTF-8 byte budget",
            field=field,
        )
    return value


def _external_write_freeze(value: object, field: str = "$") -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return _external_write_require_nfc(value, field)
    if isinstance(value, float):
        raise _external_write_error(
            "EXTERNAL_WRITE_VALUE_INVALID",
            "floating-point values are not canonical write values",
            field=field,
        )
    if isinstance(value, _ExternalWriteMapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise _external_write_error(
                    "EXTERNAL_WRITE_VALUE_INVALID",
                    "write object keys must be non-empty strings",
                    field=field,
                )
            normalized_key = _external_write_require_nfc(key, field)
            frozen[normalized_key] = _external_write_freeze(
                item, f"{field}/{normalized_key}"
            )
        return _ExternalWriteMappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _external_write_freeze(item, f"{field}/{index}")
            for index, item in enumerate(value)
        )
    raise _external_write_error(
        "EXTERNAL_WRITE_VALUE_INVALID",
        "write values must use canonical JSON types",
        field=field,
        details={"type": type(value).__name__},
    )


def _external_write_thaw(value: object) -> object:
    if isinstance(value, _ExternalWriteMapping):
        return {
            str(key): _external_write_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_external_write_thaw(item) for item in value]
    return value


def canonical_external_write_bytes(value: object) -> bytes:
    frozen = _external_write_freeze(value)
    try:
        return _external_write_json.dumps(
            _external_write_thaw(frozen),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, ExternalWriteError):
            raise
        raise _external_write_error(
            "EXTERNAL_WRITE_VALUE_INVALID",
            "write value cannot be canonically encoded",
        ) from exc


def _external_write_content_sha256(
    domain: str, value: object
) -> str:
    domain_value = _external_write_require_stable_id(domain, "domain")
    domain_bytes = domain_value.encode("utf-8")
    payload = canonical_external_write_bytes(value)
    preimage = (
        _external_write_struct.pack(">Q", len(domain_bytes))
        + domain_bytes
        + _external_write_struct.pack(">Q", len(payload))
        + payload
    )
    return _external_write_hashlib.sha256(preimage).hexdigest()


def canonical_external_write_request_sha256(request: object) -> str:
    return _external_write_content_sha256(
        _EXTERNAL_WRITE_REQUEST_DOMAIN, request
    )


def canonical_external_write_target_sha256(target: object) -> str:
    return _external_write_content_sha256(
        _EXTERNAL_WRITE_TARGET_DOMAIN, target
    )


def _external_write_require_string(
    value: object, field: str, *, maximum_bytes: int = 1024
) -> str:
    if not isinstance(value, str) or not value:
        raise _external_write_error(
            "EXTERNAL_WRITE_FIELD_REQUIRED",
            "write field must be a non-empty string",
            field=field,
        )
    normalized = _external_write_require_nfc(value, field)
    if len(normalized.encode("utf-8")) > maximum_bytes:
        raise _external_write_error(
            "EXTERNAL_WRITE_FIELD_TOO_LARGE",
            "write field exceeds its UTF-8 byte budget",
            field=field,
        )
    return normalized


def _external_write_require_stable_id(
    value: object, field: str
) -> str:
    normalized = _external_write_require_string(value, field)
    if not _external_write_stable_id_re.fullmatch(normalized):
        raise _external_write_error(
            "EXTERNAL_WRITE_ID_INVALID",
            "write identifier is not canonical",
            field=field,
        )
    return normalized


def _external_write_require_digest(
    value: object, field: str
) -> str:
    if (
        not isinstance(value, str)
        or not _external_write_digest_re.fullmatch(value)
    ):
        raise _external_write_error(
            "EXTERNAL_WRITE_DIGEST_INVALID",
            "write digest must be lowercase SHA-256",
            field=field,
        )
    return value


def _external_write_require_revision(
    value: object, field: str
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _external_write_error(
            "EXTERNAL_WRITE_REVISION_INVALID",
            "write revision must be a non-negative integer",
            field=field,
        )
    return value


@_external_write_dataclass(frozen=True)
class WorkflowWriteGateDecision:
    gate_id: str
    decision: str
    controller_revision: int
    decision_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "gate_id",
            _external_write_require_stable_id(
                self.gate_id, "gate_id"
            ),
        )
        if self.decision not in _external_write_gate_decisions:
            raise _external_write_error(
                "WORKFLOW_WRITE_GATE_DECISION_INVALID",
                "workflow write gate decision is invalid",
                field="decision",
            )
        object.__setattr__(
            self,
            "controller_revision",
            _external_write_require_revision(
                self.controller_revision, "controller_revision"
            ),
        )
        object.__setattr__(
            self,
            "decision_sha256",
            _external_write_require_digest(
                self.decision_sha256, "decision_sha256"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_WRITE_GATE_SCHEMA,
            "gate_id": self.gate_id,
            "decision": self.decision,
            "controller_revision": self.controller_revision,
            "decision_sha256": self.decision_sha256,
        }

    @property
    def sha256(self) -> str:
        return _external_write_content_sha256(
            WORKFLOW_WRITE_GATE_SCHEMA, self.as_dict()
        )


@_external_write_dataclass(frozen=True)
class WorkflowWriteBinding:
    bundle_sha256: str
    action_id: str
    execution_id: str
    effect_id: str
    gate_sha256: str
    nonce: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bundle_sha256",
            _external_write_require_digest(
                self.bundle_sha256, "bundle_sha256"
            ),
        )
        for field in ("action_id", "execution_id", "effect_id"):
            object.__setattr__(
                self,
                field,
                _external_write_require_stable_id(
                    getattr(self, field), field
                ),
            )
        object.__setattr__(
            self,
            "gate_sha256",
            _external_write_require_digest(
                self.gate_sha256, "gate_sha256"
            ),
        )
        object.__setattr__(
            self,
            "nonce",
            _external_write_require_digest(self.nonce, "nonce"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": WORKFLOW_WRITE_BINDING_SCHEMA,
            "bundle_sha256": self.bundle_sha256,
            "action_id": self.action_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "gate_sha256": self.gate_sha256,
            "nonce": self.nonce,
        }

    @property
    def sha256(self) -> str:
        return _external_write_content_sha256(
            WORKFLOW_WRITE_BINDING_SCHEMA, self.as_dict()
        )


@_external_write_dataclass(frozen=True, repr=False)
class _ExternalWriteAuthorizationRecord:
    binding_sha256: str
    request_sha256: str
    target_sha256: str
    issued_at_ns: int
    expires_at_ns: int
    issuance_id_sha256: str
    seal: bytes

    def __repr__(self) -> str:
        return "<_ExternalWriteAuthorizationRecord redacted>"


@_external_write_dataclass(frozen=True)
class _ConsumedWorkflowWriteAuthorization:
    binding_sha256: str
    request_sha256: str
    target_sha256: str
    issuance_id_sha256: str
    consumed_at_ns: int


class WorkflowWriteAuthorization:
    """Opaque, process-local, non-copyable, non-serializable handle."""

    __slots__ = ("_issuer_marker", "_record_marker")

    def __init__(self, issuer_marker: object, record_marker: object) -> None:
        self._issuer_marker = issuer_marker
        self._record_marker = record_marker

    def __repr__(self) -> str:
        return "<WorkflowWriteAuthorization opaque>"

    def __copy__(self) -> "WorkflowWriteAuthorization":
        raise TypeError("workflow write authorization cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "WorkflowWriteAuthorization":
        del memo
        raise TypeError("workflow write authorization cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError(
            "workflow write authorization cannot be serialized"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "workflow write authorization cannot be serialized"
        )


class WorkflowWriteAuthorizationIssuer:
    """Process-local authorization issuer with a startup key and registry."""

    __slots__ = (
        "_clock",
        "_issuer_marker",
        "_lock",
        "_private_key",
        "_records",
        "_seen_nonce_sha256s",
    )

    def __init__(
        self,
        *,
        monotonic_clock: _ExternalWriteCallable[
            [], float
        ] = _external_write_time.monotonic,
    ) -> None:
        if not callable(monotonic_clock):
            raise TypeError("monotonic_clock must be callable")
        self._clock = monotonic_clock
        self._issuer_marker = object()
        self._lock = _external_write_threading.RLock()
        self._private_key = _external_write_secrets.token_bytes(32)
        self._records: dict[
            object, _ExternalWriteAuthorizationRecord
        ] = {}
        self._seen_nonce_sha256s: set[str] = set()

    def __repr__(self) -> str:
        return "<WorkflowWriteAuthorizationIssuer opaque>"

    def __copy__(self) -> "WorkflowWriteAuthorizationIssuer":
        raise TypeError("workflow authorization issuer cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "WorkflowWriteAuthorizationIssuer":
        del memo
        raise TypeError("workflow authorization issuer cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError(
            "workflow authorization issuer cannot be serialized"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "workflow authorization issuer cannot be serialized"
        )

    def _now_ns(self) -> int:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not _external_write_math.isfinite(float(value))
            or value < 0
        ):
            raise _external_write_error(
                "WORKFLOW_AUTHORIZATION_CLOCK_INVALID",
                "authorization clock returned an invalid value",
            )
        return int(float(value) * 1_000_000_000)

    def _seal_payload(
        self, payload: _ExternalWriteMapping[str, object]
    ) -> bytes:
        encoded = canonical_external_write_bytes(payload)
        preimage = (
            _EXTERNAL_WRITE_AUTHORIZATION_DOMAIN
            + _external_write_struct.pack(">Q", len(encoded))
            + encoded
        )
        return _external_write_hmac.new(
            self._private_key,
            preimage,
            _external_write_hashlib.sha256,
        ).digest()

    @staticmethod
    def _record_payload(
        *,
        binding_sha256: str,
        request_sha256: str,
        target_sha256: str,
        issued_at_ns: int,
        expires_at_ns: int,
        issuance_id_sha256: str,
    ) -> dict[str, object]:
        return {
            "binding_sha256": binding_sha256,
            "request_sha256": request_sha256,
            "target_sha256": target_sha256,
            "issued_at_ns": issued_at_ns,
            "expires_at_ns": expires_at_ns,
            "issuance_id_sha256": issuance_id_sha256,
        }

    def issue(
        self,
        *,
        binding: WorkflowWriteBinding,
        request: object,
        target: object,
        gate: _ExternalWriteOptional[WorkflowWriteGateDecision],
        ttl_seconds: object = 30,
    ) -> WorkflowWriteAuthorization:
        if not isinstance(binding, WorkflowWriteBinding):
            raise _external_write_error(
                "WORKFLOW_WRITE_BINDING_INVALID",
                "workflow write binding must be validated",
            )
        if gate is None:
            raise _external_write_error(
                "WORKFLOW_WRITE_GATE_MISSING",
                "workflow write authorization requires a current gate",
            )
        if not isinstance(gate, WorkflowWriteGateDecision):
            raise _external_write_error(
                "WORKFLOW_WRITE_GATE_INVALID",
                "workflow write gate must be a validated decision",
            )
        if gate.decision != "approved":
            raise _external_write_error(
                "WORKFLOW_WRITE_GATE_DENIED",
                "workflow write gate does not permit this effect",
            )
        if gate.sha256 != binding.gate_sha256:
            raise _external_write_error(
                "WORKFLOW_WRITE_GATE_MISMATCH",
                "workflow write binding names a different gate decision",
            )
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not _external_write_math.isfinite(float(ttl_seconds))
            or float(ttl_seconds) <= 0
            or float(ttl_seconds) > 300
        ):
            raise _external_write_error(
                "WORKFLOW_AUTHORIZATION_TTL_INVALID",
                "authorization TTL must be within (0, 300] seconds",
                field="ttl_seconds",
            )
        request_sha256 = canonical_external_write_request_sha256(
            request
        )
        target_sha256 = canonical_external_write_target_sha256(target)
        issued_at_ns = self._now_ns()
        expires_at_ns = issued_at_ns + int(
            float(ttl_seconds) * 1_000_000_000
        )
        issuance_secret = _external_write_secrets.token_bytes(32)
        issuance_id_sha256 = _external_write_hashlib.sha256(
            issuance_secret
        ).hexdigest()
        nonce_sha256 = _external_write_hashlib.sha256(
            binding.nonce.encode("ascii")
        ).hexdigest()
        payload = self._record_payload(
            binding_sha256=binding.sha256,
            request_sha256=request_sha256,
            target_sha256=target_sha256,
            issued_at_ns=issued_at_ns,
            expires_at_ns=expires_at_ns,
            issuance_id_sha256=issuance_id_sha256,
        )
        seal = self._seal_payload(payload)
        record = _ExternalWriteAuthorizationRecord(
            binding_sha256=binding.sha256,
            request_sha256=request_sha256,
            target_sha256=target_sha256,
            issued_at_ns=issued_at_ns,
            expires_at_ns=expires_at_ns,
            issuance_id_sha256=issuance_id_sha256,
            seal=seal,
        )
        record_marker = object()
        with self._lock:
            if nonce_sha256 in self._seen_nonce_sha256s:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_NONCE_REUSED",
                    "workflow write nonce was already used in this process",
                )
            self._seen_nonce_sha256s.add(nonce_sha256)
            self._records[record_marker] = record
        return WorkflowWriteAuthorization(
            self._issuer_marker, record_marker
        )

    def revoke(self, authorization: object) -> bool:
        if (
            not isinstance(authorization, WorkflowWriteAuthorization)
            or authorization._issuer_marker is not self._issuer_marker
        ):
            return False
        with self._lock:
            return (
                self._records.pop(
                    authorization._record_marker, None
                )
                is not None
            )

    def consume(
        self,
        authorization: object,
        *,
        binding: WorkflowWriteBinding,
        request_sha256: str,
        target_sha256: str,
    ) -> _ConsumedWorkflowWriteAuthorization:
        if not isinstance(authorization, WorkflowWriteAuthorization):
            raise _external_write_error(
                "WORKFLOW_AUTHORIZATION_INVALID",
                "workflow write authorization is not an opaque handle",
            )
        if authorization._issuer_marker is not self._issuer_marker:
            raise _external_write_error(
                "WORKFLOW_AUTHORIZATION_WRONG_ISSUER",
                "workflow write authorization belongs to another issuer",
            )
        if not isinstance(binding, WorkflowWriteBinding):
            raise _external_write_error(
                "WORKFLOW_WRITE_BINDING_INVALID",
                "workflow write binding must be validated",
            )
        normalized_request = _external_write_require_digest(
            request_sha256, "request_sha256"
        )
        normalized_target = _external_write_require_digest(
            target_sha256, "target_sha256"
        )
        with self._lock:
            record = self._records.pop(
                authorization._record_marker, None
            )
            now_ns = self._now_ns()
            if record is None:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_REPLAYED",
                    "workflow write authorization is unknown or consumed",
                )
            payload = self._record_payload(
                binding_sha256=record.binding_sha256,
                request_sha256=record.request_sha256,
                target_sha256=record.target_sha256,
                issued_at_ns=record.issued_at_ns,
                expires_at_ns=record.expires_at_ns,
                issuance_id_sha256=record.issuance_id_sha256,
            )
            expected_seal = self._seal_payload(payload)
            if not _external_write_hmac.compare_digest(
                record.seal, expected_seal
            ):
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_CORRUPT",
                    "workflow write authorization seal is invalid",
                )
            if now_ns >= record.expires_at_ns:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_EXPIRED",
                    "workflow write authorization has expired",
                )
            if record.binding_sha256 != binding.sha256:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_BINDING_MISMATCH",
                    "workflow write authorization binding differs",
                )
            if record.request_sha256 != normalized_request:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_REQUEST_MISMATCH",
                    "workflow write authorization names another request",
                )
            if record.target_sha256 != normalized_target:
                raise _external_write_error(
                    "WORKFLOW_AUTHORIZATION_TARGET_MISMATCH",
                    "workflow write authorization names another target",
                )
            return _ConsumedWorkflowWriteAuthorization(
                binding_sha256=record.binding_sha256,
                request_sha256=record.request_sha256,
                target_sha256=record.target_sha256,
                issuance_id_sha256=record.issuance_id_sha256,
                consumed_at_ns=now_ns,
            )


class HostApprovalGrant:
    """Opaque grant minted only from the bridge's current challenge."""

    __slots__ = (
        "_bridge_marker",
        "_challenge_marker",
        "_request_sha256",
        "_target_sha256",
    )

    def __init__(
        self,
        bridge_marker: object,
        challenge_marker: object,
        request_sha256: str,
        target_sha256: str,
    ) -> None:
        self._bridge_marker = bridge_marker
        self._challenge_marker = challenge_marker
        self._request_sha256 = request_sha256
        self._target_sha256 = target_sha256

    def __repr__(self) -> str:
        return "<HostApprovalGrant opaque>"

    def __copy__(self) -> "HostApprovalGrant":
        raise TypeError("host approval grant cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "HostApprovalGrant":
        del memo
        raise TypeError("host approval grant cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("host approval grant cannot be serialized")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("host approval grant cannot be serialized")


class HostApprovalChallenge:
    """Request-bound challenge visible only to the configured host callback."""

    __slots__ = (
        "_bridge_marker",
        "_challenge_marker",
        "_challenge_sha256",
        "_consumed",
        "_request_sha256",
        "_target_sha256",
    )

    def __init__(
        self,
        bridge_marker: object,
        challenge_marker: object,
        challenge_sha256: str,
        request_sha256: str,
        target_sha256: str,
    ) -> None:
        self._bridge_marker = bridge_marker
        self._challenge_marker = challenge_marker
        self._challenge_sha256 = challenge_sha256
        self._request_sha256 = request_sha256
        self._target_sha256 = target_sha256
        self._consumed = False

    @property
    def request_sha256(self) -> str:
        return self._request_sha256

    @property
    def target_sha256(self) -> str:
        return self._target_sha256

    def approve(
        self, *, request: object, target: object
    ) -> HostApprovalGrant:
        if self._consumed:
            raise _external_write_error(
                "HOST_APPROVAL_CHALLENGE_REPLAYED",
                "host approval challenge was already answered",
            )
        self._consumed = True
        return HostApprovalGrant(
            self._bridge_marker,
            self._challenge_marker,
            canonical_external_write_request_sha256(request),
            canonical_external_write_target_sha256(target),
        )

    def __repr__(self) -> str:
        return "<HostApprovalChallenge opaque>"

    def __copy__(self) -> "HostApprovalChallenge":
        raise TypeError("host approval challenge cannot be copied")

    def __deepcopy__(
        self, memo: dict[int, object]
    ) -> "HostApprovalChallenge":
        del memo
        raise TypeError("host approval challenge cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("host approval challenge cannot be serialized")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("host approval challenge cannot be serialized")


@_external_write_dataclass(frozen=True)
class ExternalWriteInvocationReceipt:
    workflow_binding_sha256: str
    request_sha256: str
    target_sha256: str
    challenge_sha256: str
    authorization_sha256: str
    provider_result_sha256: str
    invoked_at_ns: int

    def __post_init__(self) -> None:
        for field in (
            "workflow_binding_sha256",
            "request_sha256",
            "target_sha256",
            "challenge_sha256",
            "authorization_sha256",
            "provider_result_sha256",
        ):
            object.__setattr__(
                self,
                field,
                _external_write_require_digest(getattr(self, field), field),
            )
        if (
            isinstance(self.invoked_at_ns, bool)
            or not isinstance(self.invoked_at_ns, int)
            or self.invoked_at_ns < 0
        ):
            raise _external_write_error(
                "EXTERNAL_WRITE_RECEIPT_TIME_INVALID",
                "receipt invocation time must be non-negative nanoseconds",
                field="invoked_at_ns",
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": EXTERNAL_WRITE_INVOCATION_RECEIPT_SCHEMA,
            "workflow_binding_sha256": self.workflow_binding_sha256,
            "request_sha256": self.request_sha256,
            "target_sha256": self.target_sha256,
            "challenge_sha256": self.challenge_sha256,
            "authorization_sha256": self.authorization_sha256,
            "provider_result_sha256": self.provider_result_sha256,
            "invoked_at_ns": self.invoked_at_ns,
        }

    @property
    def sha256(self) -> str:
        return _external_write_content_sha256(
            _EXTERNAL_WRITE_RECEIPT_DOMAIN, self.identity_payload()
        )

    def as_dict(self) -> dict[str, object]:
        value = self.identity_payload()
        value["sha256"] = self.sha256
        return value


@_external_write_dataclass(frozen=True)
class ExternalWriteOutcome:
    receipt: ExternalWriteInvocationReceipt
    provider_result: object


class HostOwnedExternalWriteBridge:
    """Serial host approval and provider invocation boundary."""

    __slots__ = (
        "_active_thread_id",
        "_approval_callback",
        "_bridge_marker",
        "_issuer",
        "_lock",
        "_provider",
        "_reentrancy_tainted",
        "_wall_clock_ns",
    )

    def __init__(
        self,
        *,
        issuer: WorkflowWriteAuthorizationIssuer,
        approval_callback: _ExternalWriteOptional[
            _ExternalWriteCallable[
                [HostApprovalChallenge, object, object], object
            ]
        ],
        provider: _ExternalWriteOptional[
            _ExternalWriteCallable[[object, object], object]
        ],
        wall_clock_ns: _ExternalWriteCallable[
            [], int
        ] = _external_write_time.time_ns,
    ) -> None:
        if not isinstance(
            issuer, WorkflowWriteAuthorizationIssuer
        ):
            raise TypeError("issuer must be a workflow authorization issuer")
        if approval_callback is not None and not callable(
            approval_callback
        ):
            raise TypeError("approval_callback must be callable or None")
        if provider is not None and not callable(provider):
            raise TypeError("provider must be callable or None")
        if not callable(wall_clock_ns):
            raise TypeError("wall_clock_ns must be callable")
        self._issuer = issuer
        self._approval_callback = approval_callback
        self._provider = provider
        self._wall_clock_ns = wall_clock_ns
        self._bridge_marker = object()
        self._lock = _external_write_threading.RLock()
        self._active_thread_id: _ExternalWriteOptional[int] = None
        self._reentrancy_tainted = False

    @property
    def writes_available(self) -> bool:
        return (
            self._approval_callback is not None
            and self._provider is not None
        )

    def invoke(
        self,
        *,
        authorization: object,
        binding: WorkflowWriteBinding,
        request: object,
        target: object,
        **caller_approval_fields: object,
    ) -> ExternalWriteOutcome:
        if caller_approval_fields:
            raise _external_write_error(
                "CALLER_HOST_APPROVAL_FORBIDDEN",
                "caller booleans, model fields, worker fields, and receipts "
                "cannot authorize an external write",
                details={
                    "fields": sorted(caller_approval_fields.keys())
                },
            )
        if not self.writes_available:
            raise ExternalWriteUnavailable(
                "EXTERNAL_WRITE_BRIDGE_UNAVAILABLE",
                "externally visible writes require a host-owned serial bridge",
            )
        request_bytes = canonical_external_write_bytes(request)
        target_bytes = canonical_external_write_bytes(target)
        exact_request = _external_write_json.loads(
            request_bytes.decode("utf-8")
        )
        exact_target = _external_write_json.loads(
            target_bytes.decode("utf-8")
        )
        request_sha256 = canonical_external_write_request_sha256(
            exact_request
        )
        target_sha256 = canonical_external_write_target_sha256(
            exact_target
        )
        current_thread_id = _external_write_threading.get_ident()
        if self._active_thread_id == current_thread_id:
            self._reentrancy_tainted = True
            raise _external_write_error(
                "EXTERNAL_WRITE_BRIDGE_REENTRANT",
                "host approval cannot re-enter its active serial bridge",
            )
        with self._lock:
            self._active_thread_id = current_thread_id
            self._reentrancy_tainted = False
            try:
                return self._invoke_locked(
                    authorization=authorization,
                    binding=binding,
                    request_bytes=request_bytes,
                    target_bytes=target_bytes,
                    request_sha256=request_sha256,
                    target_sha256=target_sha256,
                )
            finally:
                self._active_thread_id = None
                self._reentrancy_tainted = False

    def _invoke_locked(
        self,
        *,
        authorization: object,
        binding: WorkflowWriteBinding,
        request_bytes: bytes,
        target_bytes: bytes,
        request_sha256: str,
        target_sha256: str,
    ) -> ExternalWriteOutcome:
        consumed = self._issuer.consume(
            authorization,
            binding=binding,
            request_sha256=request_sha256,
            target_sha256=target_sha256,
        )
        challenge_secret = _external_write_secrets.token_bytes(32)
        challenge_sha256 = _external_write_hashlib.sha256(
            challenge_secret
        ).hexdigest()
        challenge_marker = object()
        challenge = HostApprovalChallenge(
            self._bridge_marker,
            challenge_marker,
            challenge_sha256,
            request_sha256,
            target_sha256,
        )
        callback = self._approval_callback
        provider = self._provider
        if callback is None or provider is None:
            raise ExternalWriteUnavailable(
                "EXTERNAL_WRITE_BRIDGE_UNAVAILABLE",
                "host-owned serial bridge became unavailable",
            )
        host_result = callback(
            challenge,
            _external_write_json.loads(
                request_bytes.decode("utf-8")
            ),
            _external_write_json.loads(
                target_bytes.decode("utf-8")
            ),
        )
        if self._reentrancy_tainted:
            raise _external_write_error(
                "EXTERNAL_WRITE_BRIDGE_REENTRANT",
                "host approval re-entered the active serial bridge",
            )
        if not isinstance(host_result, HostApprovalGrant):
            raise _external_write_error(
                "CURRENT_HOST_APPROVAL_DENIED",
                "current host approval is absent or denied",
            )
        if (
            host_result._bridge_marker is not self._bridge_marker
            or host_result._challenge_marker is not challenge_marker
            or host_result._request_sha256 != request_sha256
            or host_result._target_sha256 != target_sha256
        ):
            raise _external_write_error(
                "CURRENT_HOST_APPROVAL_MISMATCH",
                "host approval does not bind the current exact request",
            )
        provider_result = provider(
            _external_write_json.loads(
                request_bytes.decode("utf-8")
            ),
            _external_write_json.loads(
                target_bytes.decode("utf-8")
            ),
        )
        provider_result_sha256 = _external_write_content_sha256(
            "dev-flow-external-provider-result/v1",
            provider_result,
        )
        invoked_at_ns = self._wall_clock_ns()
        if (
            isinstance(invoked_at_ns, bool)
            or not isinstance(invoked_at_ns, int)
            or invoked_at_ns < 0
        ):
            raise _external_write_error(
                "EXTERNAL_WRITE_RECEIPT_TIME_INVALID",
                "host wall clock returned invalid nanoseconds",
            )
        receipt = ExternalWriteInvocationReceipt(
            workflow_binding_sha256=binding.sha256,
            request_sha256=request_sha256,
            target_sha256=target_sha256,
            challenge_sha256=challenge_sha256,
            authorization_sha256=consumed.issuance_id_sha256,
            provider_result_sha256=provider_result_sha256,
            invoked_at_ns=invoked_at_ns,
        )
        return ExternalWriteOutcome(
            receipt=receipt,
            provider_result=_external_write_freeze(provider_result),
        )


class ExternalProviderAccess:
    """Expose reads independently while keeping writes bridge-gated."""

    __slots__ = ("_read_provider", "_write_bridge")

    def __init__(
        self,
        *,
        read_provider: _ExternalWriteOptional[
            _ExternalWriteCallable[[object], object]
        ],
        write_bridge: _ExternalWriteOptional[
            HostOwnedExternalWriteBridge
        ] = None,
    ) -> None:
        if read_provider is not None and not callable(read_provider):
            raise TypeError("read_provider must be callable or None")
        if write_bridge is not None and not isinstance(
            write_bridge, HostOwnedExternalWriteBridge
        ):
            raise TypeError("write_bridge must be a host-owned bridge")
        self._read_provider = read_provider
        self._write_bridge = write_bridge

    @property
    def reads_available(self) -> bool:
        return self._read_provider is not None

    @property
    def writes_available(self) -> bool:
        return (
            self._write_bridge is not None
            and self._write_bridge.writes_available
        )

    def read(self, request: object) -> object:
        if self._read_provider is None:
            raise ExternalWriteUnavailable(
                "EXTERNAL_READ_UNAVAILABLE",
                "external read provider is unavailable",
            )
        encoded = canonical_external_write_bytes(request)
        return self._read_provider(
            _external_write_json.loads(encoded.decode("utf-8"))
        )

    def write(self, **kwargs: object) -> ExternalWriteOutcome:
        if not self.writes_available or self._write_bridge is None:
            raise ExternalWriteUnavailable(
                "EXTERNAL_WRITE_BRIDGE_UNAVAILABLE",
                "external writes are unavailable without the serial bridge",
            )
        return self._write_bridge.invoke(**kwargs)
