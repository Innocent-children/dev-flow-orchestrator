#!/usr/bin/env python3
"""Durable, standard-library-only lifecycle authority primitives.

The active record is the sole selector of an installed release.  The separate
generation watermark carries no release identity; it only prevents an absent
active record from re-introducing an ABA window after uninstall or rollback.

Every public authority operation requires a live token returned by
``LifecycleState.lock()``.  This makes the required ordering (lock, then
observe, then compare-and-swap) explicit at the API boundary.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import threading
import time
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

if os.name == "nt":  # pragma: no cover - imported and exercised on Windows
    import msvcrt
else:  # pragma: no branch - exactly one native implementation is imported
    import fcntl


ACTIVE_SCHEMA = "dev-flow-active-release/1.0.0"
DISPATCHER_PROTOCOL = "dev-flow-dispatcher/1.0.0"
GENERATION_SCHEMA = "dev-flow-active-generation/1.0.0"
TRANSACTION_SCHEMA = "dev-flow-lifecycle-transaction/1.0.0"

ACTIVE_MAX_BYTES = 16 * 1024
GENERATION_MAX_BYTES = 1024
JOURNAL_MAX_BYTES = 256 * 1024
MAX_JOURNALS = 64
MAX_COLLECTION_ITEMS = 128
MAX_TEXT_BYTES = 4096
MAX_PATH_BYTES = 8192
MAX_JSON_DEPTH = 12

TERMINAL_OUTCOMES = frozenset({"committed", "rolled_back", "partial"})
OPERATIONS = frozenset(
    {"install", "repair", "upgrade", "migration", "recovery", "uninstall"}
)
NON_TERMINAL_PHASES = frozenset(
    {
        "created",
        "candidate_ready",
        "provisional_activation",
        "host_read_back",
        "active_committed",
        "public_proof",
        "restoring",
        "removing_host_state",
        "removing_releases",
        "active_removed",
        "removing_dispatchers",
        "removing_lifecycle",
        "recovering",
    }
)
TERMINAL_PHASE = "terminal"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PROTOCOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
_PHASE_TRANSITIONS = {
    "created": {
        "candidate_ready",
        "removing_host_state",
        "recovering",
        TERMINAL_PHASE,
    },
    "candidate_ready": {
        "provisional_activation",
        "restoring",
        "recovering",
        TERMINAL_PHASE,
    },
    "provisional_activation": {
        "host_read_back",
        "restoring",
        "recovering",
        TERMINAL_PHASE,
    },
    "host_read_back": {
        "active_committed",
        "restoring",
        "recovering",
        TERMINAL_PHASE,
    },
    "active_committed": {
        "public_proof",
        "restoring",
        "recovering",
        TERMINAL_PHASE,
    },
    "public_proof": {"restoring", "recovering", TERMINAL_PHASE},
    "restoring": {"recovering", TERMINAL_PHASE},
    "removing_host_state": {
        "removing_releases",
        "recovering",
        TERMINAL_PHASE,
    },
    "removing_releases": {"active_removed", "recovering", TERMINAL_PHASE},
    "active_removed": {"removing_dispatchers", "recovering", TERMINAL_PHASE},
    "removing_dispatchers": {
        "removing_lifecycle",
        "recovering",
        TERMINAL_PHASE,
    },
    "removing_lifecycle": {"recovering", TERMINAL_PHASE},
    "recovering": {"restoring", TERMINAL_PHASE},
    TERMINAL_PHASE: set(),
}


class LifecycleStateError(RuntimeError):
    """Base error for lifecycle authority violations."""


class SchemaError(LifecycleStateError):
    """A durable record violates its closed schema."""


class ResourceLimitError(SchemaError):
    """A durable record exceeds a fixed resource bound."""


class UnsafePathError(LifecycleStateError):
    """A path is linked, reparsed, special, relative, or uncontained."""


class LockRequiredError(LifecycleStateError):
    """Authority was observed or mutated without the installation lock."""


class LockTimeoutError(LifecycleStateError):
    """The installation-wide lock was not acquired before the deadline."""


class CasMismatchError(LifecycleStateError):
    """The active record or journal changed after it was observed."""


class TransitionError(LifecycleStateError):
    """A transaction attempted an invalid state transition."""


class UnresolvedTransactionError(LifecycleStateError):
    """A new operation was requested while a prior journal is non-terminal."""

    def __init__(self, transaction_ids: Sequence[str]) -> None:
        self.transaction_ids = tuple(transaction_ids)
        super().__init__(
            "non-terminal lifecycle transaction(s) require recovery or "
            "classification: {}".format(", ".join(self.transaction_ids))
        )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _closed(mapping: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise SchemaError(
            f"{label} fields are not closed (missing={missing}, unknown={unknown})"
        )


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise SchemaError(f"non-finite JSON number is forbidden: {value}")


def _depth(value: Any, current: int = 0) -> int:
    if current > MAX_JSON_DEPTH:
        raise ResourceLimitError("JSON nesting exceeds the fixed hard cap")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise SchemaError("JSON object key is not a string")
            _depth(item, current + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, current + 1)
    return current


def strict_json_bytes(payload: bytes, *, maximum: int, label: str) -> dict[str, Any]:
    if len(payload) > maximum:
        raise ResourceLimitError(f"{label} exceeds its fixed byte cap")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SchemaError(f"{label} is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SchemaError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise SchemaError(f"{label} must be a JSON object")
    _depth(value)
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _string(value: Any, label: str, *, maximum: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaError(f"{label} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise ResourceLimitError(f"{label} exceeds its fixed string cap")
    return value


def _optional_string(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _string(value, label)


def _identifier(value: Any, label: str) -> str:
    result = _string(value, label, maximum=128)
    if not _IDENTIFIER.fullmatch(result):
        raise SchemaError(f"{label} has an invalid identifier")
    return result


def _digest(value: Any, label: str) -> str:
    result = _string(value, label, maximum=64)
    if not _SHA256.fullmatch(result):
        raise SchemaError(f"{label} must be a lowercase SHA-256 digest")
    return result


def _optional_digest(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return _digest(value, label)


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise SchemaError(f"{label} must be an integer >= {minimum}")
    return value


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _lexical_absolute(path_value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(path_value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise UnsafePathError(f"{label} is not a valid filesystem path")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise UnsafePathError(f"{label} exceeds the fixed path cap")
    path = Path(raw)
    if not path.is_absolute():
        raise UnsafePathError(f"{label} must be absolute")
    if any(part in (".", "..") for part in path.parts):
        raise UnsafePathError(f"{label} must be lexically normalized")
    normalized = os.path.normpath(raw)
    if normalized != raw.rstrip(os.sep) and not (
        path == Path(path.anchor) and normalized == raw
    ):
        raise UnsafePathError(f"{label} must be lexically normalized")
    return path


def _contained(path: Path, root: Path, label: str) -> None:
    try:
        common = os.path.commonpath((os.fspath(root), os.fspath(path)))
    except ValueError as exc:
        raise UnsafePathError(f"{label} is on a different filesystem root") from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(root)) or path == root:
        raise UnsafePathError(f"{label} is outside the managed release root")


def _existing_components(path: Path) -> Iterable[Path]:
    parts = path.parts
    current = Path(parts[0])
    yield current
    for part in parts[1:]:
        current = current / part
        yield current


def _check_ancestors(path: Path, *, leaf_kind: Optional[str] = None) -> None:
    components = tuple(_existing_components(path))
    for index, component in enumerate(components):
        try:
            info = os.lstat(component)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info):
            raise UnsafePathError(f"linked or reparse path is forbidden: {component}")
        is_leaf = index == len(components) - 1
        if not is_leaf and not stat.S_ISDIR(info.st_mode):
            raise UnsafePathError(f"non-directory ancestor is forbidden: {component}")
        if is_leaf and leaf_kind == "directory" and not stat.S_ISDIR(info.st_mode):
            raise UnsafePathError(f"expected a directory: {component}")
        if is_leaf and leaf_kind == "file" and not stat.S_ISREG(info.st_mode):
            raise UnsafePathError(f"expected a regular file: {component}")


def _ensure_directory(path: Path) -> None:
    for component in _existing_components(path):
        created = False
        try:
            info = os.lstat(component)
        except FileNotFoundError:
            try:
                os.mkdir(component, 0o700)
                created = True
            except FileExistsError:
                pass
            info = os.lstat(component)
        if stat.S_ISLNK(info.st_mode) or _is_reparse(info) or not stat.S_ISDIR(
            info.st_mode
        ):
            raise UnsafePathError(f"unsafe lifecycle directory: {component}")
        if created and os.name != "nt":
            os.chmod(component, 0o700)


def _read_file(path: Path, maximum: int, label: str) -> bytes:
    _check_ancestors(path, leaf_kind="file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        flags |= os.O_BINARY
    try:
        descriptor = os.open(os.fspath(path), flags)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise UnsafePathError(f"unsafe {label} path: {path}") from exc
        raise
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
            raise UnsafePathError(f"{label} is not a safe regular file")
        if info.st_size > maximum:
            raise ResourceLimitError(f"{label} exceeds its fixed byte cap")
        chunks = bytearray()
        while len(chunks) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if len(chunks) > maximum:
            raise ResourceLimitError(f"{label} exceeds its fixed byte cap")
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(os.fspath(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes, maximum: int, label: str) -> None:
    if len(payload) > maximum:
        raise ResourceLimitError(f"{label} exceeds its fixed byte cap")
    _ensure_directory(path.parent)
    if os.path.lexists(path):
        _check_ancestors(path, leaf_kind="file")
    descriptor: Optional[int] = None
    temporary: Optional[Path] = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.write-", suffix=".tmp", dir=os.fspath(path.parent)
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = None
            if os.name != "nt":
                os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.lexists(path):
            _check_ancestors(path, leaf_kind="file")
        os.replace(os.fspath(temporary), os.fspath(path))
        temporary = None
        _fsync_directory(path.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class ActiveRecord:
    generation: int
    release_id: str
    release_path: str
    receipt_sha256: str
    dispatcher_protocol: str
    transaction_id: str
    schema: str = ACTIVE_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "generation": self.generation,
            "release_id": self.release_id,
            "release_path": self.release_path,
            "receipt_sha256": self.receipt_sha256,
            "dispatcher_protocol": self.dispatcher_protocol,
            "transaction_id": self.transaction_id,
        }


@dataclass(frozen=True)
class ActiveSnapshot:
    """One lock-protected observation, including the absence watermark."""

    generation: int
    digest: Optional[str]
    record: Optional[ActiveRecord]

    @property
    def present(self) -> bool:
        return self.record is not None


@dataclass(frozen=True)
class ActiveExpectation:
    generation: int
    digest: Optional[str]
    present: bool

    @classmethod
    def from_snapshot(cls, snapshot: ActiveSnapshot) -> "ActiveExpectation":
        return cls(snapshot.generation, snapshot.digest, snapshot.present)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "digest": self.digest,
            "present": self.present,
        }


@dataclass(frozen=True)
class TargetRelease:
    release_id: str
    release_path: str
    artifact_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "release_path": self.release_path,
            "artifact_sha256": self.artifact_sha256,
        }


@dataclass(frozen=True)
class ExternalObservation:
    subject: str
    state: str
    digest: Optional[str] = None
    detail: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "state": self.state,
            "digest": self.digest,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProvisionalEffect:
    kind: str
    subject: str
    before_digest: Optional[str]
    after_digest: Optional[str]
    applied: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "applied": self.applied,
        }


@dataclass(frozen=True)
class TransactionJournal:
    transaction_id: str
    operation: str
    expected_active: ActiveExpectation
    target_release: Optional[TargetRelease]
    previous_authority: Optional[ActiveRecord]
    external_observations: Tuple[ExternalObservation, ...] = ()
    provisional_effects: Tuple[ProvisionalEffect, ...] = ()
    owned_paths: Tuple[str, ...] = ()
    phase: str = "created"
    outcome: Optional[str] = None
    retained_paths: Tuple[str, ...] = ()
    recovery: Tuple[str, ...] = ()
    schema: str = TRANSACTION_SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "expected_active": self.expected_active.as_dict(),
            "target_release": (
                None if self.target_release is None else self.target_release.as_dict()
            ),
            "previous_authority": (
                None
                if self.previous_authority is None
                else self.previous_authority.as_dict()
            ),
            "external_observations": [item.as_dict() for item in self.external_observations],
            "provisional_effects": [item.as_dict() for item in self.provisional_effects],
            "owned_paths": list(self.owned_paths),
            "phase": self.phase,
            "outcome": self.outcome,
            "retained_paths": list(self.retained_paths),
            "recovery": list(self.recovery),
        }


@dataclass(frozen=True)
class TransactionSnapshot:
    journal: TransactionJournal
    digest: str


def _parse_active(value: Mapping[str, Any], managed_root: Path) -> ActiveRecord:
    _closed(
        value,
        {
            "schema",
            "generation",
            "release_id",
            "release_path",
            "receipt_sha256",
            "dispatcher_protocol",
            "transaction_id",
        },
        "active record",
    )
    if value["schema"] != ACTIVE_SCHEMA:
        raise SchemaError("unsupported active-record schema")
    generation = _integer(value["generation"], "active generation", minimum=1)
    release_id = _identifier(value["release_id"], "release ID")
    release_path = _lexical_absolute(value["release_path"], "release path")
    _contained(release_path, managed_root, "release path")
    receipt = _digest(value["receipt_sha256"], "receipt digest")
    protocol = _string(value["dispatcher_protocol"], "dispatcher protocol", maximum=128)
    if not _PROTOCOL.fullmatch(protocol) or protocol != DISPATCHER_PROTOCOL:
        raise SchemaError("unsupported dispatcher protocol")
    transaction_id = _identifier(
        value["transaction_id"], "committing transaction ID"
    )
    return ActiveRecord(
        generation=generation,
        release_id=release_id,
        release_path=os.fspath(release_path),
        receipt_sha256=receipt,
        dispatcher_protocol=protocol,
        transaction_id=transaction_id,
    )


def _parse_expectation(value: Any) -> ActiveExpectation:
    if not isinstance(value, dict):
        raise SchemaError("expected_active must be an object")
    _closed(value, {"generation", "digest", "present"}, "active expectation")
    generation = _integer(value["generation"], "expected active generation")
    if not isinstance(value["present"], bool):
        raise SchemaError("expected active present must be boolean")
    digest = _optional_digest(value["digest"], "expected active digest")
    if value["present"] != (digest is not None):
        raise SchemaError("active expectation digest/presence disagree")
    return ActiveExpectation(generation, digest, value["present"])


def _parse_target(value: Any, managed_root: Path) -> Optional[TargetRelease]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SchemaError("target_release must be an object or null")
    _closed(value, {"release_id", "release_path", "artifact_sha256"}, "target release")
    release_path = _lexical_absolute(value["release_path"], "target release path")
    _contained(release_path, managed_root, "target release path")
    return TargetRelease(
        _identifier(value["release_id"], "target release ID"),
        os.fspath(release_path),
        _digest(value["artifact_sha256"], "target artifact digest"),
    )


_OBSERVATION_STATES = frozenset(
    {
        "absent",
        "exact",
        "changed",
        "unknown",
        "concurrent",
        "linked",
        "reparse",
        "special",
        "unreadable",
    }
)


def _parse_observation(value: Any) -> ExternalObservation:
    if not isinstance(value, dict):
        raise SchemaError("external observation must be an object")
    _closed(value, {"subject", "state", "digest", "detail"}, "external observation")
    state = _string(value["state"], "observation state", maximum=32)
    if state not in _OBSERVATION_STATES:
        raise SchemaError("unsupported external observation state")
    return ExternalObservation(
        _string(value["subject"], "observation subject"),
        state,
        _optional_digest(value["digest"], "observation digest"),
        _optional_string(value["detail"], "observation detail"),
    )


def _parse_effect(value: Any) -> ProvisionalEffect:
    if not isinstance(value, dict):
        raise SchemaError("provisional effect must be an object")
    _closed(
        value,
        {"kind", "subject", "before_digest", "after_digest", "applied"},
        "provisional effect",
    )
    if not isinstance(value["applied"], bool):
        raise SchemaError("provisional effect applied must be boolean")
    return ProvisionalEffect(
        _identifier(value["kind"], "provisional effect kind"),
        _string(value["subject"], "provisional effect subject"),
        _optional_digest(value["before_digest"], "provisional before digest"),
        _optional_digest(value["after_digest"], "provisional after digest"),
        value["applied"],
    )


def _bounded_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SchemaError(f"{label} must be an array")
    if len(value) > MAX_COLLECTION_ITEMS:
        raise ResourceLimitError(f"{label} exceeds its fixed item cap")
    return value


def _path_key(path: str) -> str:
    """Return the same lexical identity key used by the closed path schema."""

    return os.path.normcase(path)


def _path_list(value: Any, label: str) -> Tuple[str, ...]:
    result = []
    for item in _bounded_list(value, label):
        result.append(os.fspath(_lexical_absolute(item, label)))
    if len({_path_key(item) for item in result}) != len(result):
        raise SchemaError(f"{label} contains duplicate paths")
    return tuple(result)


def _append_unique_paths(
    existing: Sequence[str], additions: Sequence[str], label: str
) -> Tuple[str, ...]:
    """Append normalized paths once while preserving the durable prefix order."""

    result = list(existing)
    seen = {_path_key(item) for item in existing}
    for item in additions:
        normalized = os.fspath(_lexical_absolute(item, label))
        key = _path_key(normalized)
        if key in seen:
            continue
        result.append(normalized)
        seen.add(key)
    return tuple(result)


def _text_list(value: Any, label: str) -> Tuple[str, ...]:
    return tuple(_string(item, label) for item in _bounded_list(value, label))


def _parse_journal(value: Mapping[str, Any], managed_root: Path) -> TransactionJournal:
    _closed(
        value,
        {
            "schema",
            "transaction_id",
            "operation",
            "expected_active",
            "target_release",
            "previous_authority",
            "external_observations",
            "provisional_effects",
            "owned_paths",
            "phase",
            "outcome",
            "retained_paths",
            "recovery",
        },
        "transaction journal",
    )
    if value["schema"] != TRANSACTION_SCHEMA:
        raise SchemaError("unsupported transaction-journal schema")
    operation = _string(value["operation"], "operation", maximum=32)
    if operation not in OPERATIONS:
        raise SchemaError("unsupported lifecycle operation")
    previous = value["previous_authority"]
    if previous is not None and not isinstance(previous, dict):
        raise SchemaError("previous_authority must be an object or null")
    phase = _string(value["phase"], "transaction phase", maximum=64)
    if phase not in NON_TERMINAL_PHASES and phase != TERMINAL_PHASE:
        raise SchemaError("unsupported transaction phase")
    outcome = value["outcome"]
    if outcome is not None:
        outcome = _string(outcome, "transaction outcome", maximum=32)
    if (phase == TERMINAL_PHASE) != (outcome in TERMINAL_OUTCOMES):
        raise SchemaError("terminal phase and outcome disagree")
    return TransactionJournal(
        transaction_id=_identifier(value["transaction_id"], "transaction ID"),
        operation=operation,
        expected_active=_parse_expectation(value["expected_active"]),
        target_release=_parse_target(value["target_release"], managed_root),
        previous_authority=(
            None if previous is None else _parse_active(previous, managed_root)
        ),
        external_observations=tuple(
            _parse_observation(item)
            for item in _bounded_list(
                value["external_observations"], "external observations"
            )
        ),
        provisional_effects=tuple(
            _parse_effect(item)
            for item in _bounded_list(value["provisional_effects"], "provisional effects")
        ),
        owned_paths=_path_list(value["owned_paths"], "transaction-owned paths"),
        phase=phase,
        outcome=outcome,
        retained_paths=_path_list(value["retained_paths"], "retained paths"),
        recovery=_text_list(value["recovery"], "recovery guidance"),
    )


_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}


def _thread_lock(path: Path) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(os.fspath(path)))
    with _registry_guard:
        return _thread_locks.setdefault(key, threading.Lock())


class _LockToken:
    __slots__ = ("_owner", "_nonce", "_active", "_thread")

    def __init__(self, owner: "LifecycleState") -> None:
        self._owner = owner
        self._nonce = owner._nonce
        self._active = True
        self._thread = threading.get_ident()


class _LockContext(AbstractContextManager[_LockToken]):
    def __init__(self, owner: "LifecycleState", timeout_seconds: float) -> None:
        self.owner = owner
        self.timeout_seconds = timeout_seconds
        self.thread_lock = _thread_lock(owner.lock_path)
        self.descriptor: Optional[int] = None
        self.token: Optional[_LockToken] = None

    def __enter__(self) -> _LockToken:
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("lock timeout must be positive")
        deadline = time.monotonic() + float(self.timeout_seconds)
        if not self.thread_lock.acquire(timeout=float(self.timeout_seconds)):
            raise LockTimeoutError("installation lifecycle lock timed out")
        try:
            _ensure_directory(self.owner.root)
            if os.path.lexists(self.owner.lock_path):
                _check_ancestors(self.owner.lock_path, leaf_kind="file")
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            if os.name == "nt":
                flags |= os.O_BINARY
            self.descriptor = os.open(os.fspath(self.owner.lock_path), flags, 0o600)
            info = os.fstat(self.descriptor)
            if not stat.S_ISREG(info.st_mode) or _is_reparse(info):
                raise UnsafePathError("lifecycle lock is not a safe regular file")
            if os.name == "nt" and info.st_size == 0:
                os.write(self.descriptor, b"\0")
                os.fsync(self.descriptor)
            while True:
                try:
                    if os.name == "nt":
                        os.lseek(self.descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(self.descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (
                        errno.EACCES,
                        errno.EAGAIN,
                        getattr(errno, "EDEADLK", -1),
                    ):
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LockTimeoutError(
                            "installation lifecycle lock timed out"
                        ) from exc
                    time.sleep(min(0.025, remaining))
            self.token = _LockToken(self.owner)
            return self.token
        except BaseException:
            self._close_descriptor(unlock=False)
            self.thread_lock.release()
            raise

    def _close_descriptor(self, *, unlock: bool) -> None:
        if self.descriptor is None:
            return
        try:
            if unlock:
                if os.name == "nt":
                    os.lseek(self.descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(self.descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.descriptor)
            self.descriptor = None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.token is not None:
            self.token._active = False
        try:
            self._close_descriptor(unlock=True)
        finally:
            self.thread_lock.release()
        return None


class LifecycleState:
    """Own active authority and bounded journals below one installation root."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        managed_releases_root: str | os.PathLike[str],
    ) -> None:
        self.root = _lexical_absolute(root, "lifecycle state root")
        self.managed_releases_root = _lexical_absolute(
            managed_releases_root, "managed releases root"
        )
        self.lock_path = self.root / "lifecycle.lock"
        self.active_path = self.root / "active.json"
        self.generation_path = self.root / "active-generation.json"
        self.transactions_path = self.root / "transactions"
        self._nonce = object()

    def lock(self, *, timeout_seconds: float = 30.0) -> _LockContext:
        return _LockContext(self, timeout_seconds)

    def _require_lock(self, token: _LockToken) -> None:
        if (
            not isinstance(token, _LockToken)
            or token._owner is not self
            or token._nonce is not self._nonce
            or not token._active
            or token._thread != threading.get_ident()
        ):
            raise LockRequiredError(
                "a live installation-wide lifecycle lock token is required"
            )

    def _watermark(self, token: _LockToken) -> int:
        self._require_lock(token)
        if not os.path.lexists(self.generation_path):
            return 0
        payload = _read_file(
            self.generation_path, GENERATION_MAX_BYTES, "generation watermark"
        )
        value = strict_json_bytes(
            payload, maximum=GENERATION_MAX_BYTES, label="generation watermark"
        )
        _closed(value, {"schema", "generation"}, "generation watermark")
        if value["schema"] != GENERATION_SCHEMA:
            raise SchemaError("unsupported generation-watermark schema")
        return _integer(value["generation"], "generation watermark")

    def _write_watermark(self, token: _LockToken, generation: int) -> None:
        self._require_lock(token)
        current = self._watermark(token)
        if generation < current:
            raise CasMismatchError("active generation watermark cannot decrease")
        _atomic_write(
            self.generation_path,
            _canonical_bytes({"schema": GENERATION_SCHEMA, "generation": generation}),
            GENERATION_MAX_BYTES,
            "generation watermark",
        )

    def read_active(self, token: _LockToken) -> ActiveSnapshot:
        self._require_lock(token)
        watermark = self._watermark(token)
        if not os.path.lexists(self.active_path):
            return ActiveSnapshot(watermark, None, None)
        payload = _read_file(self.active_path, ACTIVE_MAX_BYTES, "active record")
        value = strict_json_bytes(payload, maximum=ACTIVE_MAX_BYTES, label="active record")
        record = _parse_active(value, self.managed_releases_root)
        return ActiveSnapshot(max(watermark, record.generation), _sha256(payload), record)

    @staticmethod
    def expectation(snapshot: ActiveSnapshot) -> ActiveExpectation:
        return ActiveExpectation.from_snapshot(snapshot)

    @staticmethod
    def _matches(snapshot: ActiveSnapshot, expected: ActiveExpectation) -> bool:
        return (
            snapshot.generation == expected.generation
            and snapshot.digest == expected.digest
            and snapshot.present == expected.present
        )

    def compare_and_set_active(
        self,
        token: _LockToken,
        expected: ActiveExpectation | ActiveSnapshot,
        *,
        release_id: str,
        release_path: str | os.PathLike[str],
        receipt_sha256: str,
        dispatcher_protocol: str,
        transaction_id: str,
    ) -> ActiveSnapshot:
        self._require_lock(token)
        if isinstance(expected, ActiveSnapshot):
            expected = ActiveExpectation.from_snapshot(expected)
        observed = self.read_active(token)
        if not self._matches(observed, expected):
            raise CasMismatchError("active authority changed after observation")
        path = _lexical_absolute(release_path, "release path")
        _contained(path, self.managed_releases_root, "release path")
        _check_ancestors(path, leaf_kind="directory")
        generation = observed.generation + 1
        record = _parse_active(
            {
                "schema": ACTIVE_SCHEMA,
                "generation": generation,
                "release_id": release_id,
                "release_path": os.fspath(path),
                "receipt_sha256": receipt_sha256,
                "dispatcher_protocol": dispatcher_protocol,
                "transaction_id": transaction_id,
            },
            self.managed_releases_root,
        )
        payload = _canonical_bytes(record.as_dict())
        _atomic_write(self.active_path, payload, ACTIVE_MAX_BYTES, "active record")
        self._write_watermark(token, generation)
        return ActiveSnapshot(generation, _sha256(payload), record)

    def restore_active(
        self,
        token: _LockToken,
        expected: ActiveExpectation | ActiveSnapshot,
        previous: ActiveRecord,
        *,
        transaction_id: Optional[str] = None,
    ) -> ActiveSnapshot:
        """Restore prior identity at a new generation without changing its receipt identity.

        ``transaction_id`` remains accepted for compatibility with the first
        state-machine caller.  The compensating operation belongs in that
        transaction's journal; the restored active record must retain the
        previous committing transaction because runtime receipts and startup
        attestation bind that identity.
        """

        del transaction_id

        return self.compare_and_set_active(
            token,
            expected,
            release_id=previous.release_id,
            release_path=previous.release_path,
            receipt_sha256=previous.receipt_sha256,
            dispatcher_protocol=previous.dispatcher_protocol,
            transaction_id=previous.transaction_id,
        )

    def compare_and_delete_active(
        self,
        token: _LockToken,
        expected: ActiveExpectation | ActiveSnapshot,
    ) -> ActiveSnapshot:
        self._require_lock(token)
        if isinstance(expected, ActiveSnapshot):
            expected = ActiveExpectation.from_snapshot(expected)
        observed = self.read_active(token)
        if not self._matches(observed, expected):
            raise CasMismatchError("active authority changed after observation")
        if not observed.present:
            raise CasMismatchError("active authority is already absent")
        generation = observed.generation + 1
        # Persist the non-selecting watermark first so deletion cannot reopen an
        # old expected-absence generation after a crash.
        self._write_watermark(token, generation)
        _check_ancestors(self.active_path, leaf_kind="file")
        os.unlink(self.active_path)
        _fsync_directory(self.active_path.parent)
        return ActiveSnapshot(generation, None, None)

    def create_transaction(
        self, token: _LockToken, journal: TransactionJournal
    ) -> TransactionSnapshot:
        self._require_lock(token)
        parsed = _parse_journal(journal.as_dict(), self.managed_releases_root)
        path = self._journal_path(parsed.transaction_id)
        _ensure_directory(self.transactions_path)
        existing = list(self.transactions_path.glob("*.json"))
        if len(existing) >= MAX_JOURNALS:
            raise ResourceLimitError("transaction journal count exceeds fixed cap")
        if os.path.lexists(path):
            raise CasMismatchError("transaction journal already exists")
        payload = _canonical_bytes(parsed.as_dict())
        _atomic_write(path, payload, JOURNAL_MAX_BYTES, "transaction journal")
        return TransactionSnapshot(parsed, _sha256(payload))

    def _journal_path(self, transaction_id: str) -> Path:
        return self.transactions_path / f"{_identifier(transaction_id, 'transaction ID')}.json"

    def read_transaction(
        self, token: _LockToken, transaction_id: str
    ) -> TransactionSnapshot:
        self._require_lock(token)
        path = self._journal_path(transaction_id)
        payload = _read_file(path, JOURNAL_MAX_BYTES, "transaction journal")
        value = strict_json_bytes(
            payload, maximum=JOURNAL_MAX_BYTES, label="transaction journal"
        )
        journal = _parse_journal(value, self.managed_releases_root)
        if journal.transaction_id != transaction_id:
            raise SchemaError("journal filename and transaction ID disagree")
        return TransactionSnapshot(journal, _sha256(payload))

    def write_transaction(
        self,
        token: _LockToken,
        expected: TransactionSnapshot,
        journal: TransactionJournal,
    ) -> TransactionSnapshot:
        self._require_lock(token)
        current = self.read_transaction(token, expected.journal.transaction_id)
        if current.digest != expected.digest:
            raise CasMismatchError("transaction journal changed after observation")
        parsed = _parse_journal(journal.as_dict(), self.managed_releases_root)
        self._validate_transition(current.journal, parsed)
        payload = _canonical_bytes(parsed.as_dict())
        _atomic_write(
            self._journal_path(parsed.transaction_id),
            payload,
            JOURNAL_MAX_BYTES,
            "transaction journal",
        )
        return TransactionSnapshot(parsed, _sha256(payload))

    @staticmethod
    def _validate_transition(old: TransactionJournal, new: TransactionJournal) -> None:
        immutable = (
            "schema",
            "transaction_id",
            "operation",
            "expected_active",
            "target_release",
            "previous_authority",
        )
        for field in immutable:
            if getattr(old, field) != getattr(new, field):
                raise TransitionError(f"transaction field is immutable: {field}")
        if old.phase == TERMINAL_PHASE:
            raise TransitionError("terminal transaction is immutable")
        if new.phase != old.phase and new.phase not in _PHASE_TRANSITIONS[old.phase]:
            raise TransitionError(f"invalid phase transition: {old.phase} -> {new.phase}")
        if not new.external_observations[: len(old.external_observations)] == old.external_observations:
            raise TransitionError("external observations are append-only")
        if not new.provisional_effects[: len(old.provisional_effects)] == old.provisional_effects:
            raise TransitionError("provisional effects are append-only")
        if not new.owned_paths[: len(old.owned_paths)] == old.owned_paths:
            raise TransitionError("transaction-owned paths are append-only")
        if not new.retained_paths[: len(old.retained_paths)] == old.retained_paths:
            raise TransitionError("retained paths are append-only")
        if not new.recovery[: len(old.recovery)] == old.recovery:
            raise TransitionError("recovery guidance is append-only")

    def advance_transaction(
        self,
        token: _LockToken,
        expected: TransactionSnapshot,
        *,
        phase: Optional[str] = None,
        observations: Sequence[ExternalObservation] = (),
        provisional_effects: Sequence[ProvisionalEffect] = (),
        owned_paths: Sequence[str] = (),
        retained_paths: Sequence[str] = (),
        recovery: Sequence[str] = (),
    ) -> TransactionSnapshot:
        journal = expected.journal
        updated = replace(
            journal,
            phase=journal.phase if phase is None else phase,
            external_observations=journal.external_observations + tuple(observations),
            provisional_effects=journal.provisional_effects + tuple(provisional_effects),
            owned_paths=journal.owned_paths + tuple(owned_paths),
            retained_paths=_append_unique_paths(
                journal.retained_paths, retained_paths, "retained paths"
            ),
            recovery=journal.recovery + tuple(recovery),
        )
        return self.write_transaction(token, expected, updated)

    def finish_transaction(
        self,
        token: _LockToken,
        expected: TransactionSnapshot,
        outcome: str,
        *,
        observations: Sequence[ExternalObservation] = (),
        retained_paths: Sequence[str] = (),
        recovery: Sequence[str] = (),
    ) -> TransactionSnapshot:
        if outcome not in TERMINAL_OUTCOMES:
            raise TransitionError("unsupported terminal outcome")
        journal = expected.journal
        updated = replace(
            journal,
            phase=TERMINAL_PHASE,
            outcome=outcome,
            external_observations=journal.external_observations + tuple(observations),
            retained_paths=_append_unique_paths(
                journal.retained_paths, retained_paths, "retained paths"
            ),
            recovery=journal.recovery + tuple(recovery),
        )
        return self.write_transaction(token, expected, updated)

    def scan_transactions(self, token: _LockToken) -> Tuple[TransactionSnapshot, ...]:
        self._require_lock(token)
        if not os.path.lexists(self.transactions_path):
            return ()
        _check_ancestors(self.transactions_path, leaf_kind="directory")
        entries = sorted(self.transactions_path.iterdir(), key=lambda item: item.name)
        if len(entries) > MAX_JOURNALS:
            raise ResourceLimitError("transaction journal count exceeds fixed cap")
        result = []
        for path in entries:
            if not path.name.endswith(".json"):
                raise SchemaError(f"undeclared transaction-state entry: {path.name}")
            result.append(self.read_transaction(token, path.name[:-5]))
        return tuple(result)

    def non_terminal_transactions(
        self, token: _LockToken
    ) -> Tuple[TransactionSnapshot, ...]:
        return tuple(
            snapshot
            for snapshot in self.scan_transactions(token)
            if snapshot.journal.outcome is None
        )

    def require_no_non_terminal(
        self, token: _LockToken, *, except_transaction_id: Optional[str] = None
    ) -> None:
        unresolved = [
            snapshot.journal.transaction_id
            for snapshot in self.non_terminal_transactions(token)
            if snapshot.journal.transaction_id != except_transaction_id
        ]
        if unresolved:
            raise UnresolvedTransactionError(unresolved)


__all__ = [
    "ACTIVE_SCHEMA",
    "DISPATCHER_PROTOCOL",
    "TRANSACTION_SCHEMA",
    "TERMINAL_OUTCOMES",
    "ActiveExpectation",
    "ActiveRecord",
    "ActiveSnapshot",
    "CasMismatchError",
    "ExternalObservation",
    "LifecycleState",
    "LifecycleStateError",
    "LockRequiredError",
    "LockTimeoutError",
    "ProvisionalEffect",
    "ResourceLimitError",
    "SchemaError",
    "TargetRelease",
    "TransactionJournal",
    "TransactionSnapshot",
    "TransitionError",
    "UnsafePathError",
    "UnresolvedTransactionError",
    "strict_json_bytes",
]
