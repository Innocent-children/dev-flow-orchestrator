# Loaded by scripts/dev_flow.py immediately after action_execution_journal.py.
# This module is the filesystem adapter for that pure contract.  It deliberately
# does not acquire controller locks, obtain manager secrets, dispatch effects,
# or write task state, outbox records, or manager nonces.
from __future__ import annotations

import contextlib as _action_store_contextlib
import copy as _action_store_copy
import errno as _action_store_errno
import hmac as _action_store_hmac
import itertools as _action_store_itertools
import os as _action_store_os
import stat as _action_store_stat
from dataclasses import dataclass as _action_store_dataclass
from pathlib import Path as _ActionStorePath
from typing import Callable as _ActionStoreCallable
from typing import Iterator as _ActionStoreIterator
from typing import Mapping as _ActionStoreMapping
from typing import Sequence as _ActionStoreSequence


# Direct imports of this source need the pure contract explicitly.  In the
# bundled runtime the contract is already present in the shared namespace and
# importing the package would break isolated ``python -I -S`` execution.
if "ACTION_EXECUTION_INDEX_PATH" not in globals():
    from .action_execution_journal import (
        ACTION_EXECUTION_INDEX_PATH,
        ACTION_EXECUTION_JOURNAL_SCHEMA,
        ACTION_COMPENSATION_EXECUTION_SCHEMA,
        CASToken,
        ControlRotationPlan,
        action_compensation_active_path,
        action_compensation_archive_path,
        action_effect_containment_path,
        action_execution_active_path,
        action_execution_archive_path,
        action_reconciliation_archive_path,
        action_reconciliation_attempt_path,
        action_reconciliation_rotation_path,
        advance_compensation_execution,
        advance_containment,
        assert_cas,
        assert_journal_promoted,
        cas_token,
        new_index,
        normalize_containment,
        normalize_compensation_execution,
        normalize_index,
        normalize_journal,
        normalize_lock_claims,
        normalize_reconciliation_attempt,
        normalize_runtime_reservation,
        orphan_active_matches_archive,
        parse_semantic_json,
        plan_archive,
        plan_compensation_control_rotation,
        plan_compensation_index_closure,
        plan_compensation_update,
        plan_effect_claim,
        plan_index_closure,
        plan_initial_write,
        plan_journal_update,
        plan_reconciliation_initial_write,
        plan_reconciliation_control_rotation,
        plan_reconciliation_update,
        plan_runtime_reservation_release,
        recover_pending_promotion,
        required_lock_claims,
        scopes_subset,
        seal_index,
        semantic_json_bytes,
        verify_journal_seal,
    )

if "V4RuntimeEvidenceAuthority" not in globals():
    from .runtime_adapters import (
        RuntimeAdapterError,
        V4RuntimeEvidenceAuthority,
        V4RuntimeSettlementEvidence,
        v4_runtime_result_event_sha256,
    )


ACTION_EXECUTION_RUNTIME_RESERVATION_DIRECTORY = (
    "action-executions/runtime-reservations"
)

ACTION_EXECUTION_STORE_FAILURE_POINTS = (
    "initialize-index:before",
    "initialize-index:after-temp-fsync",
    "initialize-index:after-replace",
    "initialize-index:after-dir-fsync",
    "initialize-index:after-verify",
    "wal-reserve-index:before",
    "wal-reserve-index:after-temp-fsync",
    "wal-reserve-index:after-replace",
    "wal-reserve-index:after-dir-fsync",
    "wal-reserve-index:after-verify",
    "wal-write-record:before",
    "wal-write-record:after-temp-fsync",
    "wal-write-record:after-replace",
    "wal-write-record:after-dir-fsync",
    "wal-write-record:after-verify",
    "wal-promote-index:before",
    "wal-promote-index:after-temp-fsync",
    "wal-promote-index:after-replace",
    "wal-promote-index:after-dir-fsync",
    "wal-promote-index:after-verify",
    "recover-promote-index:before",
    "recover-promote-index:after-temp-fsync",
    "recover-promote-index:after-replace",
    "recover-promote-index:after-dir-fsync",
    "recover-promote-index:after-verify",
    "containment-record:before",
    "containment-record:after-temp-fsync",
    "containment-record:after-replace",
    "containment-record:after-dir-fsync",
    "containment-record:after-verify",
    "runtime-reservation-record:before",
    "runtime-reservation-record:after-temp-fsync",
    "runtime-reservation-record:after-replace",
    "runtime-reservation-record:after-dir-fsync",
    "runtime-reservation-record:after-verify",
    "terminal-archive:before",
    "terminal-archive:after-temp-fsync",
    "terminal-archive:after-replace",
    "terminal-archive:after-dir-fsync",
    "terminal-archive:after-verify",
    "terminal-index-closure:before",
    "terminal-index-closure:after-temp-fsync",
    "terminal-index-closure:after-replace",
    "terminal-index-closure:after-dir-fsync",
    "terminal-index-closure:after-verify",
    "terminal-active-cleanup:before",
    "terminal-active-cleanup:after-unlink",
    "terminal-active-cleanup:after-dir-fsync",
    "runtime-reservation-settle:before",
    "runtime-reservation-settle:after-temp-fsync",
    "runtime-reservation-settle:after-replace",
    "runtime-reservation-settle:after-dir-fsync",
    "runtime-reservation-settle:after-verify",
    "runtime-reservation-release:before",
    "runtime-reservation-release:after-temp-fsync",
    "runtime-reservation-release:after-replace",
    "runtime-reservation-release:after-dir-fsync",
    "runtime-reservation-release:after-verify",
    "control-rotation-reserve:before",
    "control-rotation-reserve:after-temp-fsync",
    "control-rotation-reserve:after-replace",
    "control-rotation-reserve:after-dir-fsync",
    "control-rotation-reserve:after-verify",
    "control-rotation-write:before",
    "control-rotation-write:after-temp-fsync",
    "control-rotation-write:after-replace",
    "control-rotation-write:after-dir-fsync",
    "control-rotation-write:after-verify",
    "control-rotation-promote:before",
    "control-rotation-promote:after-temp-fsync",
    "control-rotation-promote:after-replace",
    "control-rotation-promote:after-dir-fsync",
    "control-rotation-promote:after-verify",
    "control-rotation-archive:before",
    "control-rotation-archive:after-temp-fsync",
    "control-rotation-archive:after-replace",
    "control-rotation-archive:after-dir-fsync",
    "control-rotation-archive:after-verify",
    "control-rotation-cleanup:before",
    "control-rotation-cleanup:after-unlink",
    "control-rotation-cleanup:after-dir-fsync",
    "compensation-final-reconciliation:before",
    "compensation-target-archive:before",
    "compensation-reconciliation-archive:before",
    "compensation-execution-archive:before",
    "compensation-index-closure:before",
    "compensation-active-cleanup:before",
)

_ACTION_STORE_MAX_RECORD_BYTES = 64 * 1024 * 1024
_ACTION_STORE_TEMP_COUNTER = _action_store_itertools.count()
_ACTION_STORE_REPARSE_ATTRIBUTE = 0x400


class ActionExecutionStoreError(RuntimeError):
    """Stable fail-closed rejection from the journal filesystem adapter."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: _ActionStoreMapping[str, object] | None = None,
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


@_action_store_dataclass(frozen=True)
class StoredActionExecution:
    status: str
    index: dict[str, object]
    record: dict[str, object] | None
    record_path: str | None
    required_lock_claims: tuple[tuple[str, str], ...]


@_action_store_dataclass(frozen=True)
class ActionDispatchPlan:
    """A just-persisted first-claim plan, not a durable authority token.

    The caller must consume this object immediately while retaining all
    declared controller locks.  The store never recreates it for an already
    claimed effect, including after a lost response.
    """

    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    journal_revision: int
    journal_record_sha256: str
    index_revision: int
    index_record_sha256: str
    safe_inputs: dict[str, object]
    required_lock_claims: tuple[tuple[str, str], ...]


@_action_store_dataclass(frozen=True)
class CompensationDispatchPlan:
    """A process-local permit emitted only by a new durable claim."""

    task_id: str
    execution_id: str
    target_execution_id: str
    authorization_attempt_id: str
    claim_id: str
    journal_revision: int
    journal_record_sha256: str
    index_revision: int
    index_record_sha256: str
    compensation_plan: dict[str, object]
    required_lock_claims: tuple[tuple[str, str], ...]


@_action_store_dataclass(frozen=True)
class ActionExecutionRecovery:
    status: str
    index: dict[str, object]
    record: dict[str, object] | None
    required_lock_claims: tuple[tuple[str, str], ...]


@_action_store_dataclass(frozen=True)
class ActionExecutionClosure:
    index: dict[str, object]
    archive_path: str
    active_removed: bool
    mode: str
    required_lock_claims: tuple[tuple[str, str], ...]


def _action_store_error(
    code: str,
    message: str,
    *,
    details: _ActionStoreMapping[str, object] | None = None,
) -> ActionExecutionStoreError:
    return ActionExecutionStoreError(code, message, details=details)


def _action_store_hook(
    failure_hook: _ActionStoreCallable[[str], None] | None,
    stage: str,
) -> None:
    # The hook is deliberately a transparent test seam.  Production follows
    # the exact same branch with ``None`` and hook failures are never hidden.
    if failure_hook is not None:
        failure_hook(stage)


def _action_store_is_reparse(metadata: object) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & _ACTION_STORE_REPARSE_ATTRIBUTE
    )


def _action_store_same_identity(
    first: object,
    second: object,
) -> bool:
    if hasattr(first, "st_ino") and hasattr(second, "st_ino"):
        return (
            getattr(first, "st_ino") == getattr(second, "st_ino")
            and getattr(first, "st_dev") == getattr(second, "st_dev")
        )
    return True


def _action_store_exact_bytes(first: bytes, second: bytes) -> bool:
    return _action_store_hmac.compare_digest(first, second)


def _action_store_path_components(relative: str) -> tuple[str, ...]:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith(("/", "\\"))
        or "\\" in relative
    ):
        raise _action_store_error(
            "ACTION_STORE_PATH_INVALID",
            "store paths must be non-empty relative POSIX paths",
            details={"path": relative},
        )
    components = tuple(relative.split("/"))
    if any(
        not component
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
        for component in components
    ):
        raise _action_store_error(
            "ACTION_STORE_PATH_ESCAPE",
            "store path cannot escape or alias its task directory",
            details={"path": relative},
        )
    return components


def _action_store_absolute_task_dir(
    task_dir: str | _action_store_os.PathLike[str],
) -> _ActionStorePath:
    try:
        raw = _action_store_os.fspath(task_dir)
    except TypeError as exc:
        raise _action_store_error(
            "ACTION_STORE_TASK_DIR_INVALID",
            "task_dir must be an explicit filesystem path",
        ) from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise _action_store_error(
            "ACTION_STORE_TASK_DIR_INVALID",
            "task_dir must be a non-empty text path",
        )
    candidate = _ActionStorePath(raw)
    if not candidate.is_absolute():
        raise _action_store_error(
            "ACTION_STORE_TASK_DIR_NOT_ABSOLUTE",
            "task_dir must be absolute and must not depend on process cwd",
            details={"task_dir": raw},
        )
    if ".." in candidate.parts:
        raise _action_store_error(
            "ACTION_STORE_PATH_ESCAPE",
            "task_dir must not contain parent traversal components",
            details={"task_dir": raw},
        )
    return candidate


def _action_store_validate_path_chain(path: _ActionStorePath) -> None:
    candidates = list(reversed(path.parents)) + [path]
    for candidate in candidates:
        try:
            metadata = _action_store_os.lstat(candidate)
        except OSError as exc:
            raise _action_store_error(
                "ACTION_STORE_TASK_DIR_UNAVAILABLE",
                "task_dir and all ancestors must already exist",
                details={"path": str(candidate), "error": str(exc)},
            ) from exc
        if (
            _action_store_stat.S_ISLNK(metadata.st_mode)
            or _action_store_is_reparse(metadata)
        ):
            raise _action_store_error(
                "ACTION_STORE_SYMLINK_REJECTED",
                "task_dir must not traverse symbolic links or reparse points",
                details={"path": str(candidate)},
            )
        if not _action_store_stat.S_ISDIR(metadata.st_mode):
            raise _action_store_error(
                "ACTION_STORE_SPECIAL_PATH_REJECTED",
                "task_dir and all ancestors must be directories",
                details={"path": str(candidate)},
            )


class _ActionStoreRoot:
    def __init__(
        self,
        task_dir: str | _action_store_os.PathLike[str],
    ) -> None:
        self.path = _action_store_absolute_task_dir(task_dir)
        self.descriptor = -1
        self._dir_fd = (
            _action_store_os.open in _action_store_os.supports_dir_fd
            and _action_store_os.stat in _action_store_os.supports_dir_fd
            and _action_store_os.mkdir in _action_store_os.supports_dir_fd
            and _action_store_os.unlink in _action_store_os.supports_dir_fd
        )

    def __enter__(self) -> "_ActionStoreRoot":
        _action_store_validate_path_chain(self.path)
        flags = _action_store_os.O_RDONLY
        flags |= getattr(_action_store_os, "O_DIRECTORY", 0)
        flags |= getattr(_action_store_os, "O_NOFOLLOW", 0)
        flags |= getattr(_action_store_os, "O_CLOEXEC", 0)
        try:
            if self._dir_fd and _action_store_os.name != "nt":
                anchor = _ActionStorePath(self.path.anchor)
                descriptor = _action_store_os.open(anchor, flags)
                current_path = anchor
                try:
                    for component in self.path.parts[1:]:
                        child = _action_store_os.open(
                            component, flags, dir_fd=descriptor
                        )
                        try:
                            opened = _action_store_os.fstat(child)
                            current = _action_store_os.stat(
                                component,
                                dir_fd=descriptor,
                                follow_symlinks=False,
                            )
                            if (
                                not _action_store_stat.S_ISDIR(
                                    opened.st_mode
                                )
                                or _action_store_stat.S_ISLNK(
                                    current.st_mode
                                )
                                or _action_store_is_reparse(current)
                                or not _action_store_same_identity(
                                    opened, current
                                )
                            ):
                                raise _action_store_error(
                                    "ACTION_STORE_TASK_DIR_RACE",
                                    "task_dir ancestor changed during traversal",
                                    details={
                                        "path": str(
                                            current_path / component
                                        )
                                    },
                                )
                        except BaseException:
                            _action_store_os.close(child)
                            raise
                        _action_store_os.close(descriptor)
                        descriptor = child
                        current_path /= component
                    self.descriptor = descriptor
                    descriptor = -1
                finally:
                    if descriptor >= 0:
                        _action_store_os.close(descriptor)
            else:
                self.descriptor = _action_store_os.open(
                    self.path, flags
                )
        except OSError as exc:
            raise _action_store_error(
                "ACTION_STORE_TASK_DIR_UNSAFE",
                "task_dir could not be opened without following links",
                details={"task_dir": str(self.path), "error": str(exc)},
            ) from exc
        opened = _action_store_os.fstat(self.descriptor)
        current = _action_store_os.lstat(self.path)
        if (
            not _action_store_stat.S_ISDIR(opened.st_mode)
            or _action_store_stat.S_ISLNK(current.st_mode)
            or _action_store_is_reparse(current)
            or not _action_store_same_identity(opened, current)
        ):
            self.close()
            raise _action_store_error(
                "ACTION_STORE_TASK_DIR_RACE",
                "task_dir identity changed while it was opened",
                details={"task_dir": str(self.path)},
            )
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self.descriptor >= 0:
            _action_store_os.close(self.descriptor)
            self.descriptor = -1

    def _verify_root(self) -> None:
        try:
            opened = _action_store_os.fstat(self.descriptor)
            current = _action_store_os.lstat(self.path)
        except OSError as exc:
            raise _action_store_error(
                "ACTION_STORE_TASK_DIR_RACE",
                "task_dir disappeared during the store operation",
                details={"task_dir": str(self.path), "error": str(exc)},
            ) from exc
        if (
            _action_store_stat.S_ISLNK(current.st_mode)
            or _action_store_is_reparse(current)
            or not _action_store_same_identity(opened, current)
        ):
            raise _action_store_error(
                "ACTION_STORE_TASK_DIR_RACE",
                "task_dir identity changed during the store operation",
                details={"task_dir": str(self.path)},
            )

    def _open_child_directory(
        self,
        parent_descriptor: int,
        parent_path: _ActionStorePath,
        component: str,
        *,
        create: bool,
    ) -> tuple[int, _ActionStorePath]:
        child_path = parent_path / component
        if self._dir_fd:
            if create:
                try:
                    _action_store_os.mkdir(
                        component, 0o700, dir_fd=parent_descriptor
                    )
                    if _action_store_os.name != "nt":
                        _action_store_os.fsync(parent_descriptor)
                except FileExistsError:
                    pass
            flags = _action_store_os.O_RDONLY
            flags |= getattr(_action_store_os, "O_DIRECTORY", 0)
            flags |= getattr(_action_store_os, "O_NOFOLLOW", 0)
            flags |= getattr(_action_store_os, "O_CLOEXEC", 0)
            try:
                descriptor = _action_store_os.open(
                    component, flags, dir_fd=parent_descriptor
                )
                opened = _action_store_os.fstat(descriptor)
                current = _action_store_os.stat(
                    component,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError as exc:
                if "descriptor" in locals():
                    _action_store_os.close(descriptor)
                raise _action_store_error(
                    "ACTION_STORE_DIRECTORY_MISSING",
                    "store directory is missing",
                    details={"path": str(child_path)},
                ) from exc
            except OSError as exc:
                if "descriptor" in locals():
                    _action_store_os.close(descriptor)
                raise _action_store_error(
                    "ACTION_STORE_DIRECTORY_UNSAFE",
                    "store directory is missing, linked, or not a directory",
                    details={"path": str(child_path), "error": str(exc)},
                ) from exc
            if (
                not _action_store_stat.S_ISDIR(opened.st_mode)
                or _action_store_stat.S_ISLNK(current.st_mode)
                or _action_store_is_reparse(current)
                or not _action_store_same_identity(opened, current)
            ):
                _action_store_os.close(descriptor)
                raise _action_store_error(
                    "ACTION_STORE_DIRECTORY_UNSAFE",
                    "store directory identity changed during traversal",
                    details={"path": str(child_path)},
                )
            return descriptor, child_path

        if create:
            try:
                child_path.mkdir(mode=0o700)
            except FileExistsError:
                pass
        try:
            metadata = child_path.lstat()
        except FileNotFoundError as exc:
            raise _action_store_error(
                "ACTION_STORE_DIRECTORY_MISSING",
                "store directory is missing",
                details={"path": str(child_path)},
            ) from exc
        if (
            not _action_store_stat.S_ISDIR(metadata.st_mode)
            or _action_store_stat.S_ISLNK(metadata.st_mode)
            or _action_store_is_reparse(metadata)
        ):
            raise _action_store_error(
                "ACTION_STORE_DIRECTORY_UNSAFE",
                "store directory must not be linked or special",
                details={"path": str(child_path)},
            )
        return -1, child_path

    @_action_store_contextlib.contextmanager
    def parent(
        self,
        relative: str,
        *,
        create: bool,
    ) -> _ActionStoreIterator[tuple[int, _ActionStorePath, str]]:
        components = _action_store_path_components(relative)
        current_descriptor = (
            _action_store_os.dup(self.descriptor) if self._dir_fd else -1
        )
        current_path = self.path
        try:
            for component in components[:-1]:
                next_descriptor, next_path = self._open_child_directory(
                    current_descriptor,
                    current_path,
                    component,
                    create=create,
                )
                if current_descriptor >= 0:
                    _action_store_os.close(current_descriptor)
                current_descriptor = next_descriptor
                current_path = next_path
            yield current_descriptor, current_path, components[-1]
        finally:
            if current_descriptor >= 0:
                try:
                    try:
                        opened = _action_store_os.fstat(
                            current_descriptor
                        )
                        current = _action_store_os.lstat(current_path)
                    except OSError as exc:
                        raise _action_store_error(
                            "ACTION_STORE_DIRECTORY_RACE",
                            "store directory disappeared during the operation",
                            details={
                                "path": str(current_path),
                                "error": str(exc),
                            },
                        ) from exc
                    if (
                        not _action_store_stat.S_ISDIR(opened.st_mode)
                        or _action_store_stat.S_ISLNK(current.st_mode)
                        or _action_store_is_reparse(current)
                        or not _action_store_same_identity(
                            opened, current
                        )
                    ):
                        raise _action_store_error(
                            "ACTION_STORE_DIRECTORY_RACE",
                            "store directory identity changed during the operation",
                            details={"path": str(current_path)},
                        )
                finally:
                    _action_store_os.close(current_descriptor)

    def _read_from_parent(
        self,
        parent_descriptor: int,
        parent_path: _ActionStorePath,
        filename: str,
        *,
        missing_ok: bool,
    ) -> bytes | None:
        flags = _action_store_os.O_RDONLY
        flags |= getattr(_action_store_os, "O_NOFOLLOW", 0)
        flags |= getattr(_action_store_os, "O_CLOEXEC", 0)
        flags |= getattr(_action_store_os, "O_BINARY", 0)
        # Opening a hostile FIFO for a pre-open type check must never block.
        flags |= getattr(_action_store_os, "O_NONBLOCK", 0)
        path = parent_path / filename
        try:
            before = (
                _action_store_os.stat(
                    filename,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if self._dir_fd
                else _action_store_os.lstat(path)
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise _action_store_error(
                "ACTION_STORE_RECORD_MISSING",
                "required store record is missing",
                details={"path": str(path)},
            )
        except OSError as exc:
            raise _action_store_error(
                "ACTION_STORE_RECORD_UNSAFE",
                "store record could not be inspected safely",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        if (
            not _action_store_stat.S_ISREG(before.st_mode)
            or _action_store_stat.S_ISLNK(before.st_mode)
            or _action_store_is_reparse(before)
        ):
            raise _action_store_error(
                "ACTION_STORE_RECORD_UNSAFE",
                "store record must be an unlinked regular file",
                details={"path": str(path)},
            )
        try:
            descriptor = (
                _action_store_os.open(
                    filename, flags, dir_fd=parent_descriptor
                )
                if self._dir_fd
                else _action_store_os.open(path, flags)
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise _action_store_error(
                "ACTION_STORE_RECORD_MISSING",
                "required store record is missing",
                details={"path": str(path)},
            )
        except OSError as exc:
            raise _action_store_error(
                "ACTION_STORE_RECORD_UNSAFE",
                "store record could not be opened without following links",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        try:
            opened = _action_store_os.fstat(descriptor)
            current = (
                _action_store_os.stat(
                    filename,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if self._dir_fd
                else _action_store_os.lstat(path)
            )
            if (
                not _action_store_stat.S_ISREG(opened.st_mode)
                or _action_store_stat.S_ISLNK(current.st_mode)
                or _action_store_is_reparse(current)
                or not _action_store_same_identity(before, opened)
                or not _action_store_same_identity(opened, current)
            ):
                raise _action_store_error(
                    "ACTION_STORE_RECORD_UNSAFE",
                    "store record is linked, special, or changed during open",
                    details={"path": str(path)},
                )
            if opened.st_size > _ACTION_STORE_MAX_RECORD_BYTES:
                raise _action_store_error(
                    "ACTION_STORE_RECORD_TOO_LARGE",
                    "store record exceeds the bounded read size",
                    details={"path": str(path), "size": opened.st_size},
                )
            chunks: list[bytes] = []
            remaining = _ACTION_STORE_MAX_RECORD_BYTES + 1
            while remaining:
                chunk = _action_store_os.read(
                    descriptor, min(1024 * 1024, remaining)
                )
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if remaining == 0:
                raise _action_store_error(
                    "ACTION_STORE_RECORD_TOO_LARGE",
                    "store record changed beyond the bounded read size",
                    details={"path": str(path)},
                )
            after = (
                _action_store_os.stat(
                    filename,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if self._dir_fd
                else _action_store_os.lstat(path)
            )
            if not _action_store_same_identity(opened, after):
                raise _action_store_error(
                    "ACTION_STORE_RECORD_RACE",
                    "store record identity changed while it was read",
                    details={"path": str(path)},
                )
            return b"".join(chunks)
        finally:
            _action_store_os.close(descriptor)

    def read_bytes(
        self,
        relative: str,
        *,
        missing_ok: bool = False,
    ) -> bytes | None:
        try:
            with self.parent(relative, create=False) as (
                descriptor,
                parent_path,
                filename,
            ):
                result = self._read_from_parent(
                    descriptor,
                    parent_path,
                    filename,
                    missing_ok=missing_ok,
                )
        except ActionExecutionStoreError as exc:
            if (
                missing_ok
                and exc.code == "ACTION_STORE_DIRECTORY_MISSING"
            ):
                return None
            raise
        self._verify_root()
        return result

    def _temporary_name(self, filename: str) -> str:
        return (
            f".{filename}.tmp-{_action_store_os.getpid()}-"
            f"{next(_ACTION_STORE_TEMP_COUNTER):016x}"
        )

    def _write_all(self, descriptor: int, content: bytes) -> None:
        view = memoryview(content)
        offset = 0
        while offset < len(view):
            written = _action_store_os.write(descriptor, view[offset:])
            if written <= 0:
                raise OSError(
                    _action_store_errno.EIO,
                    "short write to action execution store",
                )
            offset += written

    def atomic_write(
        self,
        relative: str,
        content: bytes,
        *,
        expected_bytes: bytes | None,
        allow_existing_exact: bool,
        failure_hook: _ActionStoreCallable[[str], None] | None,
        stage_prefix: str,
    ) -> str:
        if not isinstance(content, bytes):
            raise _action_store_error(
                "ACTION_STORE_BYTES_REQUIRED",
                "atomic store writes require exact bytes",
            )
        if len(content) > _ACTION_STORE_MAX_RECORD_BYTES:
            raise _action_store_error(
                "ACTION_STORE_RECORD_TOO_LARGE",
                "atomic store write exceeds the bounded record size",
            )
        with self.parent(relative, create=True) as (
            parent_descriptor,
            parent_path,
            filename,
        ):
            path = parent_path / filename
            current = self._read_from_parent(
                parent_descriptor,
                parent_path,
                filename,
                missing_ok=True,
            )
            if (
                allow_existing_exact
                and current is not None
                and _action_store_exact_bytes(current, content)
            ):
                return "existing"
            if expected_bytes is None:
                if current is not None:
                    raise _action_store_error(
                        "ACTION_STORE_CAS_CONFLICT",
                        "record was expected to be absent",
                        details={"path": str(path)},
                    )
            elif current is None or not _action_store_exact_bytes(
                current, expected_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_CAS_CONFLICT",
                    "record bytes changed before atomic replacement",
                    details={"path": str(path)},
                )

            _action_store_hook(failure_hook, f"{stage_prefix}:before")
            temporary_name = self._temporary_name(filename)
            flags = _action_store_os.O_WRONLY | _action_store_os.O_CREAT
            flags |= _action_store_os.O_EXCL
            flags |= getattr(_action_store_os, "O_NOFOLLOW", 0)
            flags |= getattr(_action_store_os, "O_CLOEXEC", 0)
            flags |= getattr(_action_store_os, "O_BINARY", 0)
            descriptor = -1
            installed = False
            try:
                descriptor = (
                    _action_store_os.open(
                        temporary_name,
                        flags,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                    if self._dir_fd
                    else _action_store_os.open(
                        parent_path / temporary_name, flags, 0o600
                    )
                )
                opened = _action_store_os.fstat(descriptor)
                if not _action_store_stat.S_ISREG(opened.st_mode):
                    raise _action_store_error(
                        "ACTION_STORE_TEMP_UNSAFE",
                        "atomic write temporary is not a regular file",
                        details={"path": str(parent_path / temporary_name)},
                    )
                if _action_store_os.name != "nt":
                    _action_store_os.fchmod(descriptor, 0o600)
                self._write_all(descriptor, content)
                _action_store_os.fsync(descriptor)
                _action_store_os.close(descriptor)
                descriptor = -1
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-temp-fsync"
                )

                # Recheck the exact compare-and-swap immediately before the
                # rename.  The controller lock is the serialization primitive;
                # this second read detects stale or copied lock assertions.
                before_replace = self._read_from_parent(
                    parent_descriptor,
                    parent_path,
                    filename,
                    missing_ok=True,
                )
                if expected_bytes is None:
                    if before_replace is not None:
                        raise _action_store_error(
                            "ACTION_STORE_CAS_CONFLICT",
                            "record appeared during atomic creation",
                            details={"path": str(path)},
                        )
                    try:
                        if self._dir_fd:
                            _action_store_os.link(
                                temporary_name,
                                filename,
                                src_dir_fd=parent_descriptor,
                                dst_dir_fd=parent_descriptor,
                                follow_symlinks=False,
                            )
                            _action_store_os.unlink(
                                temporary_name, dir_fd=parent_descriptor
                            )
                        else:
                            _action_store_os.link(
                                parent_path / temporary_name, path
                            )
                            (parent_path / temporary_name).unlink()
                    except FileExistsError as exc:
                        raise _action_store_error(
                            "ACTION_STORE_CAS_CONFLICT",
                            "record appeared during atomic creation",
                            details={"path": str(path)},
                        ) from exc
                else:
                    if (
                        before_replace is None
                        or not _action_store_exact_bytes(
                            before_replace, expected_bytes
                        )
                    ):
                        raise _action_store_error(
                            "ACTION_STORE_CAS_CONFLICT",
                            "record changed immediately before replacement",
                            details={"path": str(path)},
                        )
                    if self._dir_fd:
                        _action_store_os.replace(
                            temporary_name,
                            filename,
                            src_dir_fd=parent_descriptor,
                            dst_dir_fd=parent_descriptor,
                        )
                    else:
                        _action_store_os.replace(
                            parent_path / temporary_name, path
                        )
                installed = True
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-replace"
                )
                if _action_store_os.name != "nt":
                    _action_store_os.fsync(parent_descriptor)
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-dir-fsync"
                )
                stored = self._read_from_parent(
                    parent_descriptor,
                    parent_path,
                    filename,
                    missing_ok=False,
                )
                assert stored is not None
                if not _action_store_exact_bytes(stored, content):
                    raise _action_store_error(
                        "ACTION_STORE_WRITE_VERIFY_FAILED",
                        "atomic replacement did not preserve exact bytes",
                        details={"path": str(path)},
                    )
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-verify"
                )
            finally:
                if descriptor >= 0:
                    _action_store_os.close(descriptor)
                if not installed:
                    try:
                        if self._dir_fd:
                            _action_store_os.unlink(
                                temporary_name, dir_fd=parent_descriptor
                            )
                        else:
                            (parent_path / temporary_name).unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        # An unlinked or unavailable temporary grants no
                        # authority; preserve the original operation error.
                        pass
        self._verify_root()
        return "written"

    def unlink_exact(
        self,
        relative: str,
        expected_bytes: bytes,
        *,
        failure_hook: _ActionStoreCallable[[str], None] | None,
        stage_prefix: str,
    ) -> bool:
        try:
            with self.parent(relative, create=False) as (
                parent_descriptor,
                parent_path,
                filename,
            ):
                current = self._read_from_parent(
                    parent_descriptor,
                    parent_path,
                    filename,
                    missing_ok=True,
                )
                if current is None:
                    return False
                if not _action_store_exact_bytes(current, expected_bytes):
                    raise _action_store_error(
                        "ACTION_STORE_ORPHAN_MISMATCH",
                        "record cannot be removed without exact durable bytes",
                        details={"path": str(parent_path / filename)},
                    )
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:before"
                )
                if self._dir_fd:
                    _action_store_os.unlink(
                        filename, dir_fd=parent_descriptor
                    )
                else:
                    (parent_path / filename).unlink()
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-unlink"
                )
                if _action_store_os.name != "nt":
                    _action_store_os.fsync(parent_descriptor)
                _action_store_hook(
                    failure_hook, f"{stage_prefix}:after-dir-fsync"
                )
        except ActionExecutionStoreError:
            raise
        self._verify_root()
        return True


def _action_store_runtime_reservation_path(execution_id: str) -> str:
    # Reuse the journal's portable component validation.
    active = action_execution_active_path(execution_id)
    filename = active.rsplit("/", 1)[1]
    return f"{ACTION_EXECUTION_RUNTIME_RESERVATION_DIRECTORY}/{filename}"


def action_execution_runtime_reservation_path(execution_id: str) -> str:
    return _action_store_runtime_reservation_path(execution_id)


def _action_store_claim_tuple(
    claims: _ActionStoreSequence[_ActionStoreMapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    normalized = normalize_lock_claims(list(claims))
    return tuple(
        (str(claim["kind"]), str(claim["identity"]))
        for claim in normalized
    )


def action_execution_required_lock_claims(
    journal: object,
    *,
    registry_ids: _ActionStoreSequence[str] = (),
) -> tuple[tuple[str, str], ...]:
    """Declare locks the caller must acquire before any store mutation."""

    return _action_store_claim_tuple(
        required_lock_claims(journal, registry_ids=registry_ids)
    )


def _action_store_task_claim(
    task_id: str,
) -> tuple[tuple[str, str], ...]:
    return _action_store_claim_tuple(
        [{"kind": "task", "identity": task_id}]
    )


def _action_store_scope_claims(
    task_id: str,
    scopes: _ActionStoreMapping[str, object],
) -> tuple[tuple[str, str], ...]:
    claims: list[dict[str, str]] = [
        {"kind": "task", "identity": task_id}
    ]
    for kind, field in (
        ("repository", "repository_ids"),
        ("worktree", "worktree_ids"),
        ("lease", "lease_ids"),
    ):
        values = scopes.get(field)
        if not isinstance(values, list):
            raise _action_store_error(
                "ACTION_STORE_SCOPE_INVALID",
                "indexed scope cannot declare required locks",
                details={"field": field},
            )
        for identity in values:
            if not isinstance(identity, str):
                raise _action_store_error(
                    "ACTION_STORE_SCOPE_INVALID",
                    "indexed scope lock identity must be text",
                    details={"field": field},
                )
            claims.append({"kind": kind, "identity": identity})
    return _action_store_claim_tuple(claims)


def action_runtime_reservation_required_lock_claims(
    reservation: object,
) -> tuple[tuple[str, str], ...]:
    normalized = normalize_runtime_reservation(reservation)
    scopes = normalized["scopes"]
    assert isinstance(scopes, dict)
    return _action_store_scope_claims(
        str(normalized["task_id"]), scopes
    )


def _action_store_record(
    raw: bytes,
    normalizer: _ActionStoreCallable[[object], dict[str, object]],
    *,
    role: str,
) -> dict[str, object]:
    try:
        parsed = parse_semantic_json(raw)
        record = normalizer(parsed)
        canonical = semantic_json_bytes(record)
    except Exception:
        raise
    if not _action_store_exact_bytes(raw, canonical):
        raise _action_store_error(
            "ACTION_STORE_NONCANONICAL_RECORD",
            "persisted record bytes are not exact semantic JSON",
            details={"role": role},
        )
    return record


def _action_store_v4_authoritative_event_sha256(
    root: _ActionStoreRoot,
    event: object,
) -> str:
    """Require one exact event in pending task state or delivered outbox."""

    try:
        expected = semantic_json_bytes(event)
    except Exception as exc:
        raise _action_store_error(
            "ACTION_STORE_V4_RUNTIME_EVENT_INVALID",
            "V4 runtime release event is not canonical semantic JSON",
        ) from exc

    sources: list[tuple[str, tuple[object, ...]]] = []
    state_bytes = root.read_bytes("state.json", missing_ok=True)
    if state_bytes is not None:
        try:
            state = parse_semantic_json(state_bytes)
        except Exception as exc:
            raise _action_store_error(
                "ACTION_STORE_V4_RUNTIME_EVENT_INVALID",
                "authoritative task state could not be parsed",
            ) from exc
        if not isinstance(state, dict):
            raise _action_store_error(
                "ACTION_STORE_V4_RUNTIME_EVENT_INVALID",
                "authoritative task state is not an object",
            )
        pending = state.get("pending_events")
        if pending is None and state.get("pending_event") is not None:
            pending = [state["pending_event"]]
        sources.append(
            (
                "pending task outbox",
                tuple(pending) if isinstance(pending, list) else (),
            )
        )

    delivered_bytes = root.read_bytes("events.jsonl", missing_ok=True)
    delivered: list[object] = []
    if delivered_bytes is not None:
        for line_number, line in enumerate(
            delivered_bytes.splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                delivered.append(parse_semantic_json(line))
            except Exception as exc:
                raise _action_store_error(
                    "ACTION_STORE_V4_RUNTIME_EVENT_INVALID",
                    "authoritative delivered outbox could not be parsed",
                    details={"line": line_number},
                ) from exc
    sources.append(("delivered outbox", tuple(delivered)))

    for role, candidates in sources:
        matches = [
            candidate
            for candidate in candidates
            if _action_store_exact_bytes(
                semantic_json_bytes(candidate), expected
            )
        ]
        if len(matches) > 1:
            raise _action_store_error(
                "ACTION_STORE_V4_RUNTIME_EVENT_DUPLICATE",
                "authoritative outbox duplicates the runtime result event",
                details={"source": role},
            )
        if len(matches) == 1:
            return v4_runtime_result_event_sha256(matches[0])
    raise _action_store_error(
        "ACTION_STORE_V4_RUNTIME_EVENT_MISSING",
        "runtime result event is not authoritative task/outbox state",
    )


def _action_store_authenticate_journal(
    record: _ActionStoreMapping[str, object],
    manager_secret: str | bytes | None,
) -> None:
    bindings = record["bindings"]
    assert isinstance(bindings, dict)
    if bindings["authorization_kind"] == "manager":
        if manager_secret is None or not verify_journal_seal(
            record,
            manager_secret,
            expected_task_id=str(record["task_id"]),
            expected_execution_id=str(record["execution_id"]),
        ):
            raise _action_store_error(
                "ACTION_STORE_JOURNAL_REAUTHENTICATION_REQUIRED",
                "manager journal failed current secret-channel verification",
            )
    elif manager_secret is not None:
        raise _action_store_error(
            "ACTION_STORE_MANAGER_SECRET_UNEXPECTED",
            "operator journal must not receive a manager secret",
        )


def _action_store_read_index(
    root: _ActionStoreRoot,
    *,
    expected_task_id: str | None = None,
) -> tuple[dict[str, object], bytes]:
    raw = root.read_bytes(ACTION_EXECUTION_INDEX_PATH)
    assert raw is not None
    record = _action_store_record(raw, normalize_index, role="index")
    if (
        expected_task_id is not None
        and record["task_id"] != expected_task_id
    ):
        raise _action_store_error(
            "ACTION_STORE_TASK_MISMATCH",
            "action execution index belongs to another task",
            details={
                "expected_task_id": expected_task_id,
                "actual_task_id": record["task_id"],
            },
        )
    return record, raw


def _action_store_read_journal(
    root: _ActionStoreRoot,
    execution_id: str,
    *,
    manager_secret: str | bytes | None,
) -> tuple[dict[str, object], bytes]:
    relative = action_execution_active_path(execution_id)
    raw = root.read_bytes(relative)
    assert raw is not None
    record = _action_store_record(raw, normalize_journal, role="journal")
    _action_store_authenticate_journal(record, manager_secret)
    return record, raw


def _action_store_assert_token(
    record: object,
    expected: CASToken,
) -> None:
    assert_cas(record, expected)


def _action_store_effect(
    journal: _ActionStoreMapping[str, object],
    effect_id: str,
) -> dict[str, object]:
    effects = journal["effects"]
    assert isinstance(effects, list)
    for candidate in effects:
        assert isinstance(candidate, dict)
        if candidate["effect_id"] == effect_id:
            return dict(candidate)
    raise _action_store_error(
        "ACTION_STORE_EFFECT_MISSING",
        "journal does not declare the requested effect",
        details={"effect_id": effect_id},
    )


def _action_store_apply_wal(
    root: _ActionStoreRoot,
    *,
    current_index: dict[str, object],
    current_index_bytes: bytes,
    current_record: dict[str, object] | None,
    current_record_bytes: bytes | None,
    record_relative: str,
    plan: object,
    record_normalizer: _ActionStoreCallable[
        [object], dict[str, object]
    ],
    manager_secret: str | bytes | None,
    failure_hook: _ActionStoreCallable[[str], None] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    _action_store_assert_token(current_index, plan.expected_index)
    if plan.expected_journal is None:
        if current_record is not None or current_record_bytes is not None:
            raise _action_store_error(
                "ACTION_STORE_CAS_CONFLICT",
                "initial WAL record already exists",
                details={"path": record_relative},
            )
    else:
        if current_record is None or current_record_bytes is None:
            raise _action_store_error(
                "ACTION_STORE_RECORD_MISSING",
                "WAL update requires its expected current record",
                details={"path": record_relative},
            )
        _action_store_assert_token(
            current_record, plan.expected_journal
        )

    reserved_bytes = semantic_json_bytes(plan.reserved_index)
    root.atomic_write(
        ACTION_EXECUTION_INDEX_PATH,
        reserved_bytes,
        expected_bytes=current_index_bytes,
        allow_existing_exact=False,
        failure_hook=failure_hook,
        stage_prefix="wal-reserve-index",
    )
    reserved_raw = root.read_bytes(ACTION_EXECUTION_INDEX_PATH)
    assert reserved_raw is not None
    reserved = _action_store_record(
        reserved_raw, normalize_index, role="reserved index"
    )
    if not _action_store_exact_bytes(reserved_raw, reserved_bytes):
        raise _action_store_error(
            "ACTION_STORE_WAL_RESERVATION_MISMATCH",
            "reserved index differs from the planned exact bytes",
        )

    root.atomic_write(
        record_relative,
        plan.journal_bytes,
        expected_bytes=current_record_bytes,
        allow_existing_exact=False,
        failure_hook=failure_hook,
        stage_prefix="wal-write-record",
    )
    stored_raw = root.read_bytes(record_relative)
    assert stored_raw is not None
    stored = _action_store_record(
        stored_raw, record_normalizer, role="WAL record"
    )
    if not _action_store_exact_bytes(stored_raw, plan.journal_bytes):
        raise _action_store_error(
            "ACTION_STORE_WAL_RECORD_MISMATCH",
            "stored WAL record differs from the planned exact bytes",
        )
    if record_normalizer is normalize_journal:
        _action_store_authenticate_journal(stored, manager_secret)
    if not _action_store_hmac.compare_digest(
        str(stored["record_sha256"]),
        str(plan.journal_record_sha256),
    ):
        raise _action_store_error(
            "ACTION_STORE_WAL_RECORD_DIGEST_MISMATCH",
            "stored WAL record digest differs from the reservation",
        )

    # The reservation is re-read immediately before promotion.  Promotion
    # uses its exact bytes as the second index compare-and-swap.
    before_promote = root.read_bytes(ACTION_EXECUTION_INDEX_PATH)
    assert before_promote is not None
    if not _action_store_exact_bytes(before_promote, reserved_bytes):
        raise _action_store_error(
            "ACTION_STORE_CAS_CONFLICT",
            "reserved index changed before promotion",
        )
    promoted_bytes = semantic_json_bytes(plan.promoted_index)
    root.atomic_write(
        ACTION_EXECUTION_INDEX_PATH,
        promoted_bytes,
        expected_bytes=reserved_bytes,
        allow_existing_exact=False,
        failure_hook=failure_hook,
        stage_prefix="wal-promote-index",
    )
    promoted_raw = root.read_bytes(ACTION_EXECUTION_INDEX_PATH)
    assert promoted_raw is not None
    promoted = _action_store_record(
        promoted_raw, normalize_index, role="promoted index"
    )
    if not _action_store_exact_bytes(promoted_raw, promoted_bytes):
        raise _action_store_error(
            "ACTION_STORE_WAL_PROMOTION_MISMATCH",
            "promoted index differs from the planned exact bytes",
        )
    if record_normalizer is normalize_journal:
        assert_journal_promoted(
            promoted,
            stored,
            expected_index=cas_token(promoted),
            manager_secret=manager_secret,
        )
    return promoted, stored


def _action_store_apply_control_rotation(
    root: _ActionStoreRoot,
    *,
    current_index: dict[str, object],
    current_index_bytes: bytes,
    old_record_relative: str,
    old_archive_relative: str,
    new_record_relative: str,
    plan: ControlRotationPlan,
    new_record_normalizer: _ActionStoreCallable[
        [object], dict[str, object]
    ],
    failure_hook: _ActionStoreCallable[[str], None] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Idempotently finish one index-CAS control rotation.

    The reserved index already contains the new pending control and therefore
    keeps the target scope blocked through every write/promote/archive/cleanup
    crash.  A retry may resume only the exact reserved or promoted bytes.
    """

    expected_bytes = semantic_json_bytes(current_index)
    reserved_bytes = semantic_json_bytes(plan.reserved_index)
    promoted_bytes = semantic_json_bytes(plan.promoted_index)
    if _action_store_exact_bytes(current_index_bytes, expected_bytes):
        try:
            _action_store_assert_token(
                current_index, plan.expected_index
            )
        except Exception:
            if not (
                _action_store_exact_bytes(
                    current_index_bytes, reserved_bytes
                )
                or _action_store_exact_bytes(
                    current_index_bytes, promoted_bytes
                )
            ):
                raise _action_store_error(
                    "ACTION_STORE_CAS_CONFLICT",
                    "control rotation lost its exact index compare-and-swap",
                )
    state = (
        "INITIAL"
        if (
            current_index["revision"] == plan.expected_index.revision
            and current_index["record_sha256"]
            == plan.expected_index.record_sha256
        )
        else (
            "RESERVED"
            if _action_store_exact_bytes(
                current_index_bytes, reserved_bytes
            )
            else (
                "PROMOTED"
                if _action_store_exact_bytes(
                    current_index_bytes, promoted_bytes
                )
                else "CONFLICT"
            )
        )
    )
    if state == "CONFLICT":
        raise _action_store_error(
            "ACTION_STORE_CAS_CONFLICT",
            "control rotation lost its exact index compare-and-swap",
        )
    if state == "INITIAL":
        root.atomic_write(
            ACTION_EXECUTION_INDEX_PATH,
            reserved_bytes,
            expected_bytes=current_index_bytes,
            allow_existing_exact=False,
            failure_hook=failure_hook,
            stage_prefix="control-rotation-reserve",
        )
        state = "RESERVED"
    new_bytes = root.read_bytes(
        new_record_relative, missing_ok=True
    )
    if state == "RESERVED":
        if new_bytes is None:
            root.atomic_write(
                new_record_relative,
                plan.record_bytes,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="control-rotation-write",
            )
        elif not _action_store_exact_bytes(
            new_bytes, plan.record_bytes
        ):
            raise _action_store_error(
                "ACTION_STORE_CAS_CONFLICT",
                "rotated control record already has different bytes",
            )
        before_promote = root.read_bytes(
            ACTION_EXECUTION_INDEX_PATH
        )
        assert before_promote is not None
        if not _action_store_exact_bytes(
            before_promote, reserved_bytes
        ):
            raise _action_store_error(
                "ACTION_STORE_CAS_CONFLICT",
                "reserved rotation index changed before promotion",
            )
        root.atomic_write(
            ACTION_EXECUTION_INDEX_PATH,
            promoted_bytes,
            expected_bytes=reserved_bytes,
            allow_existing_exact=False,
            failure_hook=failure_hook,
            stage_prefix="control-rotation-promote",
        )
    stored_bytes = root.read_bytes(new_record_relative)
    assert stored_bytes is not None
    if not _action_store_exact_bytes(
        stored_bytes, plan.record_bytes
    ):
        raise _action_store_error(
            "ACTION_STORE_CONTROL_ROTATION_RECORD_MISMATCH",
            "promoted control differs from its exact reserved bytes",
        )
    stored = _action_store_record(
        stored_bytes,
        new_record_normalizer,
        role="rotated control",
    )
    if not _action_store_hmac.compare_digest(
        str(stored["record_sha256"]),
        plan.new_record_sha256,
    ):
        raise _action_store_error(
            "ACTION_STORE_CONTROL_ROTATION_RECORD_MISMATCH",
            "rotated control digest differs from its reservation",
        )
    promoted, actual_promoted_bytes = _action_store_read_index(root)
    if not _action_store_exact_bytes(
        actual_promoted_bytes, promoted_bytes
    ):
        raise _action_store_error(
            "ACTION_STORE_CONTROL_ROTATION_PROMOTION_MISMATCH",
            "promoted control index differs from its exact plan",
        )
    old_active = root.read_bytes(
        old_record_relative, missing_ok=True
    )
    old_archive = root.read_bytes(
        old_archive_relative, missing_ok=True
    )
    if old_active is None:
        if old_archive is None:
            raise _action_store_error(
                "ACTION_STORE_CONTROL_ROTATION_PREDECESSOR_MISSING",
                "rotated predecessor is neither active nor archived",
            )
        parsed_archive = parse_semantic_json(old_archive)
        if (
            not isinstance(parsed_archive, dict)
            or parsed_archive.get("record_sha256")
            != plan.old_record_sha256
        ):
            raise _action_store_error(
                "ACTION_STORE_CONTROL_ROTATION_ARCHIVE_MISMATCH",
                "rotated predecessor archive differs from the CAS plan",
            )
    else:
        parsed_old = parse_semantic_json(old_active)
        if (
            not isinstance(parsed_old, dict)
            or parsed_old.get("record_sha256")
            != plan.old_record_sha256
        ):
            raise _action_store_error(
                "ACTION_STORE_CONTROL_ROTATION_PREDECESSOR_MISMATCH",
                "rotated predecessor bytes differ from the CAS plan",
            )
        if old_archive is None:
            root.atomic_write(
                old_archive_relative,
                old_active,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="control-rotation-archive",
            )
            old_archive = root.read_bytes(old_archive_relative)
        if old_archive is None or not _action_store_exact_bytes(
            old_archive, old_active
        ):
            raise _action_store_error(
                "ACTION_STORE_CONTROL_ROTATION_ARCHIVE_MISMATCH",
                "rotated predecessor archive differs from active bytes",
            )
        root.unlink_exact(
            old_record_relative,
            old_archive,
            failure_hook=failure_hook,
            stage_prefix="control-rotation-cleanup",
        )
    return promoted, stored


class ActionExecutionStore:
    """Strict storage adapter for one explicit controller task directory.

    Every mutating method requires the caller to retain the claims returned by
    :func:`action_execution_required_lock_claims`.  This adapter does not
    trust a serializable ``held=True`` assertion and does not acquire locks.
    """

    def __init__(
        self,
        task_dir: str | _action_store_os.PathLike[str],
    ) -> None:
        self._task_dir = _action_store_absolute_task_dir(task_dir)

    @property
    def task_dir(self) -> str:
        return str(self._task_dir)

    def initialize_index(
        self,
        task_id: str,
        *,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        index = new_index(task_id)
        content = semantic_json_bytes(index)
        with _ActionStoreRoot(self._task_dir) as root:
            existing = root.read_bytes(
                ACTION_EXECUTION_INDEX_PATH, missing_ok=True
            )
            if existing is not None:
                current = _action_store_record(
                    existing, normalize_index, role="index"
                )
                if current["task_id"] != task_id:
                    raise _action_store_error(
                        "ACTION_STORE_TASK_MISMATCH",
                        "existing index belongs to another task",
                    )
                return StoredActionExecution(
                    status="existing",
                    index=current,
                    record=None,
                    record_path=None,
                    required_lock_claims=_action_store_task_claim(task_id),
                )
            root.atomic_write(
                ACTION_EXECUTION_INDEX_PATH,
                content,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="initialize-index",
            )
            current, raw = _action_store_read_index(
                root, expected_task_id=task_id
            )
            if not _action_store_exact_bytes(raw, content):
                raise _action_store_error(
                    "ACTION_STORE_INDEX_INITIALIZATION_MISMATCH",
                    "initialized index differs from its canonical bytes",
                )
        return StoredActionExecution(
            status="initialized",
            index=current,
            record=None,
            record_path=None,
            required_lock_claims=_action_store_task_claim(task_id),
        )

    def read_index(
        self,
        *,
        expected_task_id: str | None = None,
    ) -> dict[str, object]:
        with _ActionStoreRoot(self._task_dir) as root:
            index, _ = _action_store_read_index(
                root, expected_task_id=expected_task_id
            )
            return index

    def read_active_journal(
        self,
        execution_id: str,
        *,
        manager_secret: str | bytes | None = None,
    ) -> dict[str, object]:
        with _ActionStoreRoot(self._task_dir) as root:
            record, _ = _action_store_read_journal(
                root,
                execution_id,
                manager_secret=manager_secret,
            )
            return record

    def read_promoted_context(
        self,
        execution_id: str,
        *,
        expected_index: CASToken | None = None,
        expected_journal: CASToken | None = None,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
    ) -> StoredActionExecution:
        """Reload one exact promoted index/journal pair under caller locks."""

        relative = action_execution_active_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            index, _ = _action_store_read_index(root)
            if expected_index is not None:
                _action_store_assert_token(index, expected_index)
            current, _ = _action_store_read_journal(
                root, execution_id, manager_secret=manager_secret
            )
            if expected_journal is not None:
                _action_store_assert_token(current, expected_journal)
            assert_journal_promoted(
                index,
                current,
                expected_index=cas_token(index),
                manager_secret=manager_secret,
            )
            return StoredActionExecution(
                status="promoted",
                index=index,
                record=current,
                record_path=str(self._task_dir / relative),
                required_lock_claims=(
                    action_execution_required_lock_claims(
                        current, registry_ids=registry_ids
                    )
                ),
            )

    def read_archive_journal(
        self,
        execution_id: str,
        *,
        manager_secret: str | bytes | None = None,
    ) -> dict[str, object]:
        relative = action_execution_archive_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            record = _action_store_record(
                raw, normalize_journal, role="archive journal"
            )
            _action_store_authenticate_journal(
                record, manager_secret
            )
            return record

    def persist_initial(
        self,
        journal: object,
        *,
        expected_index: CASToken,
        entry_kind: str = "ordinary",
        target_execution_id: str | None = None,
        control_action_id: str | None = None,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        normalized = normalize_journal(journal)
        _action_store_authenticate_journal(normalized, manager_secret)
        claims = action_execution_required_lock_claims(
            normalized, registry_ids=registry_ids
        )
        relative = action_execution_active_path(
            str(normalized["execution_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(normalized["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            existing_bytes = root.read_bytes(relative, missing_ok=True)
            existing = (
                None
                if existing_bytes is None
                else _action_store_record(
                    existing_bytes, normalize_journal, role="journal"
                )
            )
            plan = plan_initial_write(
                index,
                normalized,
                expected_index=expected_index,
                entry_kind=entry_kind,
                target_execution_id=target_execution_id,
                control_action_id=control_action_id,
                manager_secret=manager_secret,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=existing,
                current_record_bytes=existing_bytes,
                record_relative=relative,
                plan=plan,
                record_normalizer=normalize_journal,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
        return StoredActionExecution(
            status="promoted",
            index=promoted,
            record=stored,
            record_path=str(self._task_dir / relative),
            required_lock_claims=claims,
        )

    def persist_update(
        self,
        updated_journal: object,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        updated = normalize_journal(updated_journal)
        _action_store_authenticate_journal(updated, manager_secret)
        claims = action_execution_required_lock_claims(
            updated, registry_ids=registry_ids
        )
        relative = action_execution_active_path(
            str(updated["execution_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(updated["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            current, current_bytes = _action_store_read_journal(
                root,
                str(updated["execution_id"]),
                manager_secret=manager_secret,
            )
            _action_store_assert_token(current, expected_journal)
            plan = plan_journal_update(
                index,
                current,
                updated,
                expected_index=expected_index,
                expected_journal=expected_journal,
                manager_secret=manager_secret,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=current,
                current_record_bytes=current_bytes,
                record_relative=relative,
                plan=plan,
                record_normalizer=normalize_journal,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
        return StoredActionExecution(
            status="promoted",
            index=promoted,
            record=stored,
            record_path=str(self._task_dir / relative),
            required_lock_claims=claims,
        )

    def claim_for_dispatch(
        self,
        execution_id: str,
        effect_id: str,
        claim_id: str,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> ActionDispatchPlan:
        relative = action_execution_active_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(root)
            _action_store_assert_token(index, expected_index)
            current, current_bytes = _action_store_read_journal(
                root, execution_id, manager_secret=manager_secret
            )
            _action_store_assert_token(current, expected_journal)
            claims = action_execution_required_lock_claims(
                current, registry_ids=registry_ids
            )
            effects = current["effects"]
            assert isinstance(effects, list)
            if any(
                candidate["effect_id"] != effect_id
                and candidate["claim_id"] == claim_id
                for candidate in effects
                if isinstance(candidate, dict)
            ):
                raise _action_store_error(
                    "ACTION_STORE_CLAIM_ID_REUSED",
                    "claim identity must be unique within the execution",
                    details={"claim_id": claim_id},
                )
            claim = plan_effect_claim(
                current,
                effect_id,
                claim_id,
                index=index,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            if not claim.first_claim:
                raise _action_store_error(
                    "ACTION_STORE_DISPATCH_FORBIDDEN",
                    "only a newly persisted first claim may open dispatch",
                )
            wal = plan_journal_update(
                index,
                current,
                claim.journal,
                expected_index=expected_index,
                expected_journal=expected_journal,
                manager_secret=manager_secret,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=current,
                current_record_bytes=current_bytes,
                record_relative=relative,
                plan=wal,
                record_normalizer=normalize_journal,
                manager_secret=manager_secret,
                failure_hook=failure_hook,
            )
            assert_journal_promoted(
                promoted,
                stored,
                expected_index=cas_token(promoted),
                manager_secret=manager_secret,
            )
            effect = _action_store_effect(stored, effect_id)
            if (
                effect["phase"] != "CLAIMED"
                or effect["claim_id"] != claim_id
            ):
                raise _action_store_error(
                    "ACTION_STORE_DISPATCH_FORBIDDEN",
                    "promoted journal does not contain the exact first claim",
                )
            safe_inputs = _action_store_copy.deepcopy(
                effect["safe_inputs"]
            )
            assert isinstance(safe_inputs, dict)
            return ActionDispatchPlan(
                task_id=str(stored["task_id"]),
                execution_id=str(stored["execution_id"]),
                effect_id=str(effect["effect_id"]),
                claim_id=str(effect["claim_id"]),
                attempt_id=str(effect["attempt_id"]),
                journal_revision=int(stored["revision"]),
                journal_record_sha256=str(stored["record_sha256"]),
                index_revision=int(promoted["revision"]),
                index_record_sha256=str(promoted["record_sha256"]),
                safe_inputs=safe_inputs,
                required_lock_claims=claims,
            )

    def recover_pending(
        self,
        execution_id: str,
        *,
        manager_secret: str | bytes | None = None,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> ActionExecutionRecovery:
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(root)
            entries = index["entries"]
            assert isinstance(entries, list)
            entry = next(
                (
                    candidate
                    for candidate in entries
                    if candidate["execution_id"] == execution_id
                ),
                None,
            )
            if entry is None or entry["pending_record_sha256"] is None:
                raise _action_store_error(
                    "ACTION_STORE_PENDING_ENTRY_MISSING",
                    "execution has no pending WAL reservation",
                )
            entry_kind = str(entry["entry_kind"])
            if entry_kind == "control":
                reconciliation_relative = (
                    action_reconciliation_attempt_path(execution_id)
                )
                compensation_relative = (
                    action_compensation_active_path(execution_id)
                )
                relative = reconciliation_relative
                active_bytes = root.read_bytes(relative, missing_ok=True)
                if active_bytes is None:
                    relative = compensation_relative
                    active_bytes = root.read_bytes(
                        relative, missing_ok=True
                    )
                if active_bytes is None:
                    return ActionExecutionRecovery(
                        status="BLOCKED_MISSING_RECORD",
                        index=index,
                        record=None,
                        required_lock_claims=_action_store_scope_claims(
                            str(index["task_id"]), entry["scopes"]
                        ),
                    )
                try:
                    parsed = parse_semantic_json(active_bytes)
                    normalizer = (
                        normalize_compensation_execution
                        if (
                            isinstance(parsed, dict)
                            and parsed.get("schema")
                            == ACTION_COMPENSATION_EXECUTION_SCHEMA
                        )
                        else normalize_reconciliation_attempt
                    )
                    record = _action_store_record(
                        active_bytes,
                        normalizer,
                        role="control record",
                    )
                except Exception:
                    return ActionExecutionRecovery(
                        status="QUARANTINE_MISMATCH",
                        index=index,
                        record=None,
                        required_lock_claims=_action_store_scope_claims(
                            str(index["task_id"]), entry["scopes"]
                        ),
                    )
                target_entry = next(
                    (
                        candidate
                        for candidate in entries
                        if candidate["execution_id"]
                        == entry["target_execution_id"]
                    ),
                    None,
                )
                record_identity = (
                    record["execution_id"]
                    if normalizer is normalize_compensation_execution
                    else record["attempt_id"]
                )
                record_action = (
                    record["bindings"]["compensation_plan"][
                        "action_id"
                    ]
                    if normalizer is normalize_compensation_execution
                    else record["bindings"]["recovery_action_id"]
                )
                target_digest = record["bindings"][
                    "target_journal_record_sha256"
                ]
                if (
                    record_identity != execution_id
                    or record["task_id"] != index["task_id"]
                    or record["target_execution_id"]
                    != entry["target_execution_id"]
                    or record_action != entry["control_action_id"]
                    or target_entry is None
                    or target_entry["entry_kind"] == "control"
                    or target_entry["pending_record_sha256"] is not None
                    or not _action_store_hmac.compare_digest(
                        str(target_entry["record_sha256"]),
                        str(target_digest),
                    )
                    or not _action_store_hmac.compare_digest(
                        str(record["record_sha256"]),
                        str(entry["pending_record_sha256"]),
                    )
                ):
                    return ActionExecutionRecovery(
                        status="QUARANTINE_MISMATCH",
                        index=index,
                        record=record,
                        required_lock_claims=_action_store_scope_claims(
                            str(index["task_id"]), entry["scopes"]
                        ),
                    )
                recovered_entries = [
                    dict(candidate) for candidate in entries
                ]
                for candidate in recovered_entries:
                    if candidate["execution_id"] == execution_id:
                        candidate["record_sha256"] = candidate[
                            "pending_record_sha256"
                        ]
                        candidate["pending_record_sha256"] = None
                recovered = seal_index(
                    {
                        "schema": index["schema"],
                        "task_id": index["task_id"],
                        "revision": int(index["revision"]) + 1,
                        "entries": recovered_entries,
                    }
                )
                status = "PROMOTE"
            else:
                relative = action_execution_active_path(execution_id)
                active_bytes = root.read_bytes(relative, missing_ok=True)
                status, recovered = recover_pending_promotion(
                    index,
                    execution_id,
                    active_bytes,
                    manager_secret=manager_secret,
                )
                record = None
                if active_bytes is not None:
                    try:
                        record = _action_store_record(
                            active_bytes,
                            normalize_journal,
                            role="journal",
                        )
                    except Exception:
                        record = None
                if status != "PROMOTE":
                    claims = (
                        _action_store_scope_claims(
                            str(index["task_id"]), entry["scopes"]
                        )
                        if record is None
                        else action_execution_required_lock_claims(record)
                    )
                    return ActionExecutionRecovery(
                        status=status,
                        index=index,
                        record=record,
                        required_lock_claims=claims,
                    )
                assert recovered is not None

            recovered_bytes = semantic_json_bytes(recovered)
            root.atomic_write(
                ACTION_EXECUTION_INDEX_PATH,
                recovered_bytes,
                expected_bytes=index_bytes,
                allow_existing_exact=False,
                failure_hook=failure_hook,
                stage_prefix="recover-promote-index",
            )
            verified, verified_bytes = _action_store_read_index(root)
            if not _action_store_exact_bytes(
                verified_bytes, recovered_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_RECOVERY_MISMATCH",
                    "recovered index differs from its exact plan",
                )
            if entry_kind != "control" and record is not None:
                assert_journal_promoted(
                    verified,
                    record,
                    expected_index=cas_token(verified),
                    manager_secret=manager_secret,
                )
            claims = (
                _action_store_scope_claims(
                    str(index["task_id"]), entry["scopes"]
                )
                if entry_kind == "control" or record is None
                else action_execution_required_lock_claims(record)
            )
            return ActionExecutionRecovery(
                status="PROMOTED",
                index=verified,
                record=record,
                required_lock_claims=claims,
            )

    def read_containment(
        self,
        execution_id: str,
        effect_id: str,
    ) -> dict[str, object]:
        relative = action_effect_containment_path(
            execution_id, effect_id
        )
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw, normalize_containment, role="containment"
            )

    def persist_containment(
        self,
        record: object,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        expected_containment: CASToken | None = None,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        updated = normalize_containment(record)
        execution_id = str(updated["execution_id"])
        effect_id = str(updated["effect_id"])
        relative = action_effect_containment_path(
            execution_id, effect_id
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, _ = _action_store_read_index(
                root, expected_task_id=str(updated["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            journal, _ = _action_store_read_journal(
                root, execution_id, manager_secret=manager_secret
            )
            _action_store_assert_token(journal, expected_journal)
            assert_journal_promoted(
                index,
                journal,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            claims = action_execution_required_lock_claims(
                journal, registry_ids=registry_ids
            )
            effect = _action_store_effect(journal, effect_id)
            if (
                updated["task_id"] != journal["task_id"]
                or updated["claim_id"] != effect["claim_id"]
                or updated["attempt_id"] != effect["attempt_id"]
                or updated["journal_schema"]
                != ACTION_EXECUTION_JOURNAL_SCHEMA
            ):
                raise _action_store_error(
                    "ACTION_STORE_CONTAINMENT_CROSSLINK_INVALID",
                    "containment does not bind the promoted journal effect",
                )
            current_bytes = root.read_bytes(relative, missing_ok=True)
            current = (
                None
                if current_bytes is None
                else _action_store_record(
                    current_bytes,
                    normalize_containment,
                    role="containment",
                )
            )
            if expected_containment is None:
                if current is not None:
                    if _action_store_exact_bytes(
                        current_bytes, semantic_json_bytes(updated)
                    ):
                        return StoredActionExecution(
                            status="existing",
                            index=index,
                            record=current,
                            record_path=str(self._task_dir / relative),
                            required_lock_claims=claims,
                        )
                    raise _action_store_error(
                        "ACTION_STORE_CAS_CONFLICT",
                        "containment already exists with different bytes",
                    )
                if (
                    updated["phase"] != "SPAWN_PENDING"
                    or updated["revision"] != 0
                    or updated["journal_record_sha256"]
                    != journal["record_sha256"]
                ):
                    raise _action_store_error(
                        "ACTION_STORE_CONTAINMENT_INITIAL_INVALID",
                        "initial containment must bind the claimed journal",
                    )
            else:
                if current is None:
                    raise _action_store_error(
                        "ACTION_STORE_RECORD_MISSING",
                        "containment update requires its current record",
                    )
                _action_store_assert_token(
                    current, expected_containment
                )
                expected_update = advance_containment(
                    current,
                    str(updated["phase"]),
                    runtime_handle_sha256=(
                        str(updated["runtime_handle_sha256"])
                        if updated["runtime_handle_sha256"] is not None
                        else None
                    ),
                    receipt_sha256=(
                        str(updated["receipt_sha256"])
                        if updated["receipt_sha256"] is not None
                        else None
                    ),
                )
                if not _action_store_exact_bytes(
                    semantic_json_bytes(expected_update),
                    semantic_json_bytes(updated),
                ):
                    raise _action_store_error(
                        "ACTION_STORE_CONTAINMENT_EVOLUTION_INVALID",
                        "containment update is not the exact next phase",
                    )
                journal_link = effect["containment_record_sha256"]
                if (
                    effect["phase"]
                    in {
                        "RUNNING",
                        "QUIESCED",
                        "HANDOFF_VERIFIED",
                        "VERIFIED",
                    }
                    and journal_link is None
                ):
                    raise _action_store_error(
                        "ACTION_STORE_CONTAINMENT_CROSSLINK_INVALID",
                        "advanced effect lost its containment cross-link",
                    )
            updated_bytes = semantic_json_bytes(updated)
            status = root.atomic_write(
                relative,
                updated_bytes,
                expected_bytes=current_bytes,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="containment-record",
            )
            verified_bytes = root.read_bytes(relative)
            assert verified_bytes is not None
            verified = _action_store_record(
                verified_bytes,
                normalize_containment,
                role="containment",
            )
            if not _action_store_exact_bytes(
                verified_bytes, updated_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_CONTAINMENT_WRITE_MISMATCH",
                    "containment write did not preserve exact bytes",
                )
            return StoredActionExecution(
                status=status,
                index=index,
                record=verified,
                record_path=str(self._task_dir / relative),
                required_lock_claims=claims,
            )

    def persist_reconciliation_initial(
        self,
        attempt: object,
        *,
        target_execution_id: str,
        expected_index: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        normalized = normalize_reconciliation_attempt(attempt)
        relative = action_reconciliation_attempt_path(
            str(normalized["attempt_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(normalized["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            target, _ = _action_store_read_journal(
                root,
                target_execution_id,
                manager_secret=manager_secret,
            )
            assert_journal_promoted(
                index,
                target,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            if normalized["target_execution_id"] != target_execution_id:
                raise _action_store_error(
                    "ACTION_STORE_RECONCILIATION_TARGET_INVALID",
                    "attempt names another target execution",
                )
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            existing_bytes = root.read_bytes(relative, missing_ok=True)
            existing = (
                None
                if existing_bytes is None
                else _action_store_record(
                    existing_bytes,
                    normalize_reconciliation_attempt,
                    role="reconciliation attempt",
                )
            )
            plan = plan_reconciliation_initial_write(
                index,
                normalized,
                target_journal=target,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=existing,
                current_record_bytes=existing_bytes,
                record_relative=relative,
                plan=plan,
                record_normalizer=normalize_reconciliation_attempt,
                manager_secret=None,
                failure_hook=failure_hook,
            )
            return StoredActionExecution(
                status="promoted",
                index=promoted,
                record=stored,
                record_path=str(self._task_dir / relative),
                required_lock_claims=claims,
            )

    def read_reconciliation(
        self,
        attempt_id: str,
    ) -> dict[str, object]:
        relative = action_reconciliation_attempt_path(attempt_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_reconciliation_attempt,
                role="reconciliation attempt",
            )

    def persist_reconciliation_update(
        self,
        updated_attempt: object,
        *,
        expected_index: CASToken,
        expected_attempt: CASToken,
        target_manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        updated = normalize_reconciliation_attempt(updated_attempt)
        relative = action_reconciliation_attempt_path(
            str(updated["attempt_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(updated["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            target, _ = _action_store_read_journal(
                root,
                str(updated["target_execution_id"]),
                manager_secret=target_manager_secret,
            )
            assert_journal_promoted(
                index,
                target,
                expected_index=expected_index,
                manager_secret=target_manager_secret,
            )
            current_bytes = root.read_bytes(relative)
            assert current_bytes is not None
            current = _action_store_record(
                current_bytes,
                normalize_reconciliation_attempt,
                role="reconciliation attempt",
            )
            _action_store_assert_token(current, expected_attempt)
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            plan = plan_reconciliation_update(
                index,
                current,
                updated,
                expected_index=expected_index,
                expected_attempt=expected_attempt,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=current,
                current_record_bytes=current_bytes,
                record_relative=relative,
                plan=plan,
                record_normalizer=normalize_reconciliation_attempt,
                manager_secret=None,
                failure_hook=failure_hook,
            )
            return StoredActionExecution(
                status="promoted",
                index=promoted,
                record=stored,
                record_path=str(self._task_dir / relative),
                required_lock_claims=claims,
            )

    def read_reconciliation_archive(
        self,
        attempt_id: str,
    ) -> dict[str, object]:
        relative = action_reconciliation_archive_path(attempt_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_reconciliation_attempt,
                role="reconciliation archive",
            )

    def read_rotated_reconciliation(
        self,
        attempt_id: str,
    ) -> dict[str, object]:
        relative = action_reconciliation_rotation_path(attempt_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_reconciliation_attempt,
                role="rotated reconciliation authorization",
            )

    def rotate_reconciliation_control(
        self,
        old_attempt: object,
        new_attempt: object,
        *,
        target_execution_id: str,
        expected_index: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        rotation_plan: ControlRotationPlan | None = None,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        old = normalize_reconciliation_attempt(old_attempt)
        new = normalize_reconciliation_attempt(new_attempt)
        old_relative = action_reconciliation_attempt_path(
            str(old["attempt_id"])
        )
        old_archive = action_reconciliation_archive_path(
            str(old["attempt_id"])
        )
        new_relative = action_reconciliation_attempt_path(
            str(new["attempt_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(new["task_id"])
            )
            target, _ = _action_store_read_journal(
                root,
                target_execution_id,
                manager_secret=manager_secret,
            )
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            plan = rotation_plan
            if plan is None:
                _action_store_assert_token(index, expected_index)
                plan = plan_reconciliation_control_rotation(
                    index,
                    old,
                    new,
                    target_journal=target,
                    expected_index=expected_index,
                    manager_secret=manager_secret,
                )
            if (
                plan.old_execution_id != old["attempt_id"]
                or plan.new_execution_id != new["attempt_id"]
                or not _action_store_exact_bytes(
                    plan.record_bytes, semantic_json_bytes(new)
                )
            ):
                raise _action_store_error(
                    "ACTION_STORE_CONTROL_ROTATION_PLAN_MISMATCH",
                    "reconciliation rotation plan differs from supplied records",
                )
            promoted, stored = _action_store_apply_control_rotation(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                old_record_relative=old_relative,
                old_archive_relative=old_archive,
                new_record_relative=new_relative,
                plan=plan,
                new_record_normalizer=normalize_reconciliation_attempt,
                failure_hook=failure_hook,
            )
            return StoredActionExecution(
                status="rotated",
                index=promoted,
                record=stored,
                record_path=str(self._task_dir / new_relative),
                required_lock_claims=claims,
            )

    def rotate_to_compensation_control(
        self,
        authorized_attempt: object,
        compensation_execution: object,
        *,
        target_execution_id: str,
        expected_index: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        rotation_plan: ControlRotationPlan | None = None,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        attempt = normalize_reconciliation_attempt(
            authorized_attempt
        )
        compensation = normalize_compensation_execution(
            compensation_execution
        )
        old_relative = action_reconciliation_attempt_path(
            str(attempt["attempt_id"])
        )
        old_archive = action_reconciliation_rotation_path(
            str(attempt["attempt_id"])
        )
        new_relative = action_compensation_active_path(
            str(compensation["execution_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(compensation["task_id"])
            )
            target, _ = _action_store_read_journal(
                root,
                target_execution_id,
                manager_secret=manager_secret,
            )
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            plan = rotation_plan
            if plan is None:
                _action_store_assert_token(index, expected_index)
                plan = plan_compensation_control_rotation(
                    index,
                    attempt,
                    compensation,
                    target_journal=target,
                    expected_index=expected_index,
                    manager_secret=manager_secret,
                )
            if (
                plan.old_execution_id != attempt["attempt_id"]
                or plan.new_execution_id
                != compensation["execution_id"]
                or not _action_store_exact_bytes(
                    plan.record_bytes,
                    semantic_json_bytes(compensation),
                )
            ):
                raise _action_store_error(
                    "ACTION_STORE_CONTROL_ROTATION_PLAN_MISMATCH",
                    "compensation rotation plan differs from supplied records",
                )
            promoted, stored = _action_store_apply_control_rotation(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                old_record_relative=old_relative,
                old_archive_relative=old_archive,
                new_record_relative=new_relative,
                plan=plan,
                new_record_normalizer=normalize_compensation_execution,
                failure_hook=failure_hook,
            )
            return StoredActionExecution(
                status="rotated",
                index=promoted,
                record=stored,
                record_path=str(self._task_dir / new_relative),
                required_lock_claims=claims,
            )

    def read_compensation(
        self,
        execution_id: str,
    ) -> dict[str, object]:
        relative = action_compensation_active_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_compensation_execution,
                role="compensation execution",
            )

    def read_compensation_archive(
        self,
        execution_id: str,
    ) -> dict[str, object]:
        relative = action_compensation_archive_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_compensation_execution,
                role="compensation archive",
            )

    def persist_compensation_update(
        self,
        updated_execution: object,
        *,
        expected_index: CASToken,
        expected_execution: CASToken,
        target_manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        updated = normalize_compensation_execution(
            updated_execution
        )
        relative = action_compensation_active_path(
            str(updated["execution_id"])
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(updated["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            target, _ = _action_store_read_journal(
                root,
                str(updated["target_execution_id"]),
                manager_secret=target_manager_secret,
            )
            current_bytes = root.read_bytes(relative)
            assert current_bytes is not None
            current = _action_store_record(
                current_bytes,
                normalize_compensation_execution,
                role="compensation execution",
            )
            _action_store_assert_token(current, expected_execution)
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            plan = plan_compensation_update(
                index,
                current,
                updated,
                expected_index=expected_index,
                expected_execution=expected_execution,
            )
            promoted, stored = _action_store_apply_wal(
                root,
                current_index=index,
                current_index_bytes=index_bytes,
                current_record=current,
                current_record_bytes=current_bytes,
                record_relative=relative,
                plan=plan,
                record_normalizer=normalize_compensation_execution,
                manager_secret=None,
                failure_hook=failure_hook,
            )
            return StoredActionExecution(
                status="promoted",
                index=promoted,
                record=stored,
                record_path=str(self._task_dir / relative),
                required_lock_claims=claims,
            )

    def claim_compensation_for_dispatch(
        self,
        execution_id: str,
        claim_id: str,
        *,
        expected_index: CASToken,
        expected_execution: CASToken,
        target_manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> CompensationDispatchPlan:
        current = self.read_compensation(execution_id)
        if current["phase"] != "PREPARED":
            raise _action_store_error(
                "ACTION_STORE_DISPATCH_FORBIDDEN",
                "only a new compensation claim may open dispatch",
            )
        claimed = advance_compensation_execution(
            current, "CLAIMED", claim_id=claim_id
        )
        stored = self.persist_compensation_update(
            claimed,
            expected_index=expected_index,
            expected_execution=expected_execution,
            target_manager_secret=target_manager_secret,
            registry_ids=registry_ids,
            failure_hook=failure_hook,
        )
        assert stored.record is not None
        plan = stored.record["bindings"]["compensation_plan"]
        assert isinstance(plan, dict)
        return CompensationDispatchPlan(
            task_id=str(stored.record["task_id"]),
            execution_id=str(stored.record["execution_id"]),
            target_execution_id=str(
                stored.record["target_execution_id"]
            ),
            authorization_attempt_id=str(
                stored.record["authorization_attempt_id"]
            ),
            claim_id=str(stored.record["claim_id"]),
            journal_revision=int(stored.record["revision"]),
            journal_record_sha256=str(
                stored.record["record_sha256"]
            ),
            index_revision=int(stored.index["revision"]),
            index_record_sha256=str(
                stored.index["record_sha256"]
            ),
            compensation_plan=_action_store_copy.deepcopy(plan),
            required_lock_claims=stored.required_lock_claims,
        )

    def persist_runtime_reservation(
        self,
        reservation: object,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        normalized = normalize_runtime_reservation(reservation)
        execution_id = str(normalized["execution_id"])
        effect_id = str(normalized["effect_id"])
        relative = _action_store_runtime_reservation_path(execution_id)
        containment_relative = action_effect_containment_path(
            execution_id, effect_id
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, _ = _action_store_read_index(
                root, expected_task_id=str(normalized["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            journal, _ = _action_store_read_journal(
                root, execution_id, manager_secret=manager_secret
            )
            _action_store_assert_token(journal, expected_journal)
            assert_journal_promoted(
                index,
                journal,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            if journal["phase"] != "COMMITTED":
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RESERVATION_PREMATURE",
                    "runtime reservation requires a committed handoff journal",
                )
            containment_bytes = root.read_bytes(containment_relative)
            assert containment_bytes is not None
            containment = _action_store_record(
                containment_bytes,
                normalize_containment,
                role="containment",
            )
            effect = _action_store_effect(journal, effect_id)
            if (
                effect["settlement"] != "asynchronous-handoff"
                or effect["settled_as"] != "HANDOFF_VERIFIED"
                or containment["phase"] != "HANDOFF_VERIFIED"
                or normalized["phase"] != "ACTIVE"
                or normalized["task_id"] != journal["task_id"]
                or normalized["containment_record_sha256"]
                != containment["record_sha256"]
                or normalized["runtime_handle_sha256"]
                != containment["runtime_handle_sha256"]
                or normalized["handoff_receipt_sha256"]
                != containment["receipt_sha256"]
                or effect["containment_record_sha256"]
                != containment["record_sha256"]
                or not scopes_subset(
                    normalized["scopes"], effect["scopes"]
                )
            ):
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RESERVATION_CROSSLINK_INVALID",
                    "runtime reservation does not bind the durable handoff",
                )
            claims = action_execution_required_lock_claims(
                journal, registry_ids=registry_ids
            )
            current = root.read_bytes(relative, missing_ok=True)
            content = semantic_json_bytes(normalized)
            if current is not None:
                if not _action_store_exact_bytes(current, content):
                    raise _action_store_error(
                        "ACTION_STORE_CAS_CONFLICT",
                        "runtime reservation already has different bytes",
                    )
                status = "existing"
            else:
                status = root.atomic_write(
                    relative,
                    content,
                    expected_bytes=None,
                    allow_existing_exact=True,
                    failure_hook=failure_hook,
                    stage_prefix="runtime-reservation-record",
                )
            verified_bytes = root.read_bytes(relative)
            assert verified_bytes is not None
            verified = _action_store_record(
                verified_bytes,
                normalize_runtime_reservation,
                role="runtime reservation",
            )
            return StoredActionExecution(
                status=status,
                index=index,
                record=verified,
                record_path=str(self._task_dir / relative),
                required_lock_claims=claims,
            )

    def read_runtime_reservation(
        self,
        execution_id: str,
    ) -> dict[str, object]:
        relative = _action_store_runtime_reservation_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            raw = root.read_bytes(relative)
            assert raw is not None
            return _action_store_record(
                raw,
                normalize_runtime_reservation,
                role="runtime reservation",
            )

    def archive_and_close(
        self,
        execution_id: str,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        authoritative_event_sha256: str,
        reconciliation_attempt_id: str | None = None,
        promote_runtime_reservation: bool = False,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> ActionExecutionClosure:
        active_relative = action_execution_active_path(execution_id)
        archive_relative = action_execution_archive_path(execution_id)
        reconciliation_active_relative = None
        reconciliation_archive_relative = None
        if reconciliation_attempt_id is not None:
            reconciliation_active_relative = (
                action_reconciliation_attempt_path(
                    reconciliation_attempt_id
                )
            )
            reconciliation_archive_relative = (
                action_reconciliation_archive_path(
                    reconciliation_attempt_id
                )
            )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(root)
            _action_store_assert_token(index, expected_index)
            journal, active_bytes = _action_store_read_journal(
                root, execution_id, manager_secret=manager_secret
            )
            _action_store_assert_token(journal, expected_journal)
            assert_journal_promoted(
                index,
                journal,
                expected_index=expected_index,
                manager_secret=manager_secret,
            )
            claims = action_execution_required_lock_claims(
                journal, registry_ids=registry_ids
            )
            containments: list[dict[str, object]] = []
            effects = journal["effects"]
            assert isinstance(effects, list)
            for effect in effects:
                assert isinstance(effect, dict)
                relative = action_effect_containment_path(
                    execution_id, str(effect["effect_id"])
                )
                raw = root.read_bytes(relative)
                assert raw is not None
                containments.append(
                    _action_store_record(
                        raw, normalize_containment, role="containment"
                    )
                )
            reconciliation = None
            if reconciliation_attempt_id is not None:
                assert reconciliation_active_relative is not None
                raw = root.read_bytes(
                    reconciliation_active_relative
                )
                assert raw is not None
                reconciliation = _action_store_record(
                    raw,
                    normalize_reconciliation_attempt,
                    role="reconciliation attempt",
                )
            reservation = None
            if promote_runtime_reservation:
                relative = _action_store_runtime_reservation_path(
                    execution_id
                )
                raw = root.read_bytes(relative)
                assert raw is not None
                reservation = _action_store_record(
                    raw,
                    normalize_runtime_reservation,
                    role="runtime reservation",
                )

            archive = plan_archive(
                journal,
                reconciliation_attempt=reconciliation,
                manager_secret=manager_secret,
            )
            archive_status = root.atomic_write(
                archive_relative,
                archive.archive_bytes,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="terminal-archive",
            )
            del archive_status
            durable_archive = root.read_bytes(archive_relative)
            assert durable_archive is not None
            if not _action_store_exact_bytes(
                durable_archive, archive.archive_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_ARCHIVE_VERIFY_FAILED",
                    "terminal archive is not the exact active journal",
                )
            reconciliation_archive_bytes = None
            if reconciliation is not None:
                assert reconciliation_archive_relative is not None
                reconciliation_archive_bytes = semantic_json_bytes(
                    reconciliation
                )
                root.atomic_write(
                    reconciliation_archive_relative,
                    reconciliation_archive_bytes,
                    expected_bytes=None,
                    allow_existing_exact=True,
                    failure_hook=failure_hook,
                    stage_prefix="terminal-reconciliation-archive",
                )
                durable_reconciliation = root.read_bytes(
                    reconciliation_archive_relative
                )
                if not _action_store_exact_bytes(
                    durable_reconciliation,
                    reconciliation_archive_bytes,
                ):
                    raise _action_store_error(
                        "ACTION_STORE_ARCHIVE_VERIFY_FAILED",
                        "terminal reconciliation archive differs from exact active bytes",
                    )
            closure = plan_index_closure(
                index,
                journal,
                durable_archive,
                expected_index=expected_index,
                authoritative_event_sha256=authoritative_event_sha256,
                containment_records=containments,
                reconciliation_attempt=reconciliation,
                runtime_reservation=reservation,
                manager_secret=manager_secret,
            )
            closure_bytes = semantic_json_bytes(closure.index)
            root.atomic_write(
                ACTION_EXECUTION_INDEX_PATH,
                closure_bytes,
                expected_bytes=index_bytes,
                allow_existing_exact=False,
                failure_hook=failure_hook,
                stage_prefix="terminal-index-closure",
            )
            closed_index, closed_bytes = _action_store_read_index(root)
            if not _action_store_exact_bytes(
                closed_bytes, closure_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_CLOSURE_VERIFY_FAILED",
                    "terminal index closure differs from its exact plan",
                )
            if not orphan_active_matches_archive(
                active_bytes, durable_archive
            ):
                raise _action_store_error(
                    "ACTION_STORE_ORPHAN_MISMATCH",
                    "active journal differs from the durable archive",
                )
            active_removed = root.unlink_exact(
                active_relative,
                durable_archive,
                failure_hook=failure_hook,
                stage_prefix="terminal-active-cleanup",
            )
            if reconciliation_archive_bytes is not None:
                assert reconciliation_active_relative is not None
                active_removed = (
                    root.unlink_exact(
                        reconciliation_active_relative,
                        reconciliation_archive_bytes,
                        failure_hook=failure_hook,
                        stage_prefix=(
                            "terminal-reconciliation-active-cleanup"
                        ),
                    )
                    and active_removed
                )
            return ActionExecutionClosure(
                index=closed_index,
                archive_path=str(self._task_dir / archive_relative),
                active_removed=active_removed,
                mode=closure.mode,
                required_lock_claims=claims,
            )

    def finalize_compensation_and_close(
        self,
        terminal_reconciliation: object,
        committed_compensation: object,
        *,
        expected_index: CASToken,
        expected_journal: CASToken,
        manager_secret: str | bytes | None = None,
        registry_ids: _ActionStoreSequence[str] = (),
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> ActionExecutionClosure:
        reconciliation = normalize_reconciliation_attempt(
            terminal_reconciliation
        )
        compensation = normalize_compensation_execution(
            committed_compensation
        )
        target_id = str(reconciliation["target_execution_id"])
        compensation_id = str(compensation["execution_id"])
        attempt_id = str(reconciliation["attempt_id"])
        target_active_relative = action_execution_active_path(
            target_id
        )
        target_archive_relative = action_execution_archive_path(
            target_id
        )
        authorization_relative = action_reconciliation_rotation_path(
            attempt_id
        )
        reconciliation_archive_relative = (
            action_reconciliation_archive_path(attempt_id)
        )
        compensation_active_relative = (
            action_compensation_active_path(compensation_id)
        )
        compensation_archive_relative = (
            action_compensation_archive_path(compensation_id)
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(root)
            target_active_bytes = root.read_bytes(
                target_active_relative, missing_ok=True
            )
            target_archive_bytes = root.read_bytes(
                target_archive_relative, missing_ok=True
            )
            source_target_bytes = (
                target_active_bytes
                if target_active_bytes is not None
                else target_archive_bytes
            )
            if source_target_bytes is None:
                raise _action_store_error(
                    "ACTION_STORE_COMPENSATION_TARGET_MISSING",
                    "compensation target is neither active nor archived",
                )
            target = _action_store_record(
                source_target_bytes,
                normalize_journal,
                role="compensation target",
            )
            _action_store_authenticate_journal(
                target, manager_secret
            )
            _action_store_assert_token(target, expected_journal)
            claims = action_execution_required_lock_claims(
                target, registry_ids=registry_ids
            )
            authorization_bytes = root.read_bytes(
                authorization_relative
            )
            assert authorization_bytes is not None
            authorization = _action_store_record(
                authorization_bytes,
                normalize_reconciliation_attempt,
                role="rotated compensation authorization",
            )
            outcome = reconciliation["outcome"]
            assert isinstance(outcome, dict)
            if (
                authorization["phase"]
                != "COMPENSATION_AUTHORIZED"
                or authorization["attempt_id"] != attempt_id
                or not _action_store_hmac.compare_digest(
                    str(authorization["record_sha256"]),
                    str(
                        outcome[
                            "compensation_authorization_sha256"
                        ]
                    ),
                )
            ):
                raise _action_store_error(
                    "ACTION_STORE_COMPENSATION_AUTHORIZATION_MISMATCH",
                    "terminal reconciliation differs from rotated authorization",
                )
            compensation_active_bytes = root.read_bytes(
                compensation_active_relative, missing_ok=True
            )
            compensation_archive_bytes = root.read_bytes(
                compensation_archive_relative, missing_ok=True
            )
            source_compensation_bytes = (
                compensation_active_bytes
                if compensation_active_bytes is not None
                else compensation_archive_bytes
            )
            if source_compensation_bytes is None:
                raise _action_store_error(
                    "ACTION_STORE_COMPENSATION_RECORD_MISSING",
                    "committed compensation is neither active nor archived",
                )
            durable_compensation = _action_store_record(
                source_compensation_bytes,
                normalize_compensation_execution,
                role="committed compensation",
            )
            if not _action_store_exact_bytes(
                semantic_json_bytes(durable_compensation),
                semantic_json_bytes(compensation),
            ):
                raise _action_store_error(
                    "ACTION_STORE_COMPENSATION_RECORD_MISMATCH",
                    "supplied compensation differs from durable bytes",
                )
            entries = index["entries"]
            assert isinstance(entries, list)
            target_entry = next(
                (
                    entry
                    for entry in entries
                    if entry["execution_id"] == target_id
                ),
                None,
            )
            compensation_entry = next(
                (
                    entry
                    for entry in entries
                    if entry["execution_id"] == compensation_id
                ),
                None,
            )
            already_closed = (
                target_entry is None and compensation_entry is None
            )
            if already_closed:
                for durable, expected, role in (
                    (
                        target_archive_bytes,
                        semantic_json_bytes(target),
                        "target",
                    ),
                    (
                        root.read_bytes(
                            reconciliation_archive_relative,
                            missing_ok=True,
                        ),
                        semantic_json_bytes(reconciliation),
                        "reconciliation",
                    ),
                    (
                        compensation_archive_bytes,
                        semantic_json_bytes(compensation),
                        "compensation",
                    ),
                ):
                    if durable is None or not _action_store_exact_bytes(
                        durable, expected
                    ):
                        raise _action_store_error(
                            "ACTION_STORE_COMPENSATION_ARCHIVE_MISMATCH",
                            "closed compensation has non-exact archives",
                            details={"role": role},
                        )
                active_removed = True
                if target_active_bytes is not None:
                    active_removed = root.unlink_exact(
                        target_active_relative,
                        target_archive_bytes,
                        failure_hook=failure_hook,
                        stage_prefix="compensation-active-cleanup",
                    )
                if compensation_active_bytes is not None:
                    active_removed = (
                        root.unlink_exact(
                            compensation_active_relative,
                            compensation_archive_bytes,
                            failure_hook=failure_hook,
                            stage_prefix="compensation-active-cleanup",
                        )
                        and active_removed
                    )
                return ActionExecutionClosure(
                    index=index,
                    archive_path=str(
                        self._task_dir / target_archive_relative
                    ),
                    active_removed=active_removed,
                    mode="COMPENSATED",
                    required_lock_claims=claims,
                )
            _action_store_assert_token(index, expected_index)
            containments: list[dict[str, object]] = []
            effects = target["effects"]
            assert isinstance(effects, list)
            for effect in effects:
                relative = action_effect_containment_path(
                    target_id, str(effect["effect_id"])
                )
                raw = root.read_bytes(relative)
                assert raw is not None
                containments.append(
                    _action_store_record(
                        raw,
                        normalize_containment,
                        role="containment",
                    )
                )
            target_content = semantic_json_bytes(target)
            reconciliation_content = semantic_json_bytes(
                reconciliation
            )
            compensation_content = semantic_json_bytes(compensation)
            root.atomic_write(
                target_archive_relative,
                target_content,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="compensation-target-archive",
            )
            root.atomic_write(
                reconciliation_archive_relative,
                reconciliation_content,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="compensation-reconciliation-archive",
            )
            root.atomic_write(
                compensation_archive_relative,
                compensation_content,
                expected_bytes=None,
                allow_existing_exact=True,
                failure_hook=failure_hook,
                stage_prefix="compensation-execution-archive",
            )
            durable_target_archive = root.read_bytes(
                target_archive_relative
            )
            durable_reconciliation_archive = root.read_bytes(
                reconciliation_archive_relative
            )
            durable_compensation_archive = root.read_bytes(
                compensation_archive_relative
            )
            assert durable_target_archive is not None
            assert durable_reconciliation_archive is not None
            assert durable_compensation_archive is not None
            closure = plan_compensation_index_closure(
                index,
                target,
                durable_target_archive,
                reconciliation,
                durable_reconciliation_archive,
                compensation,
                durable_compensation_archive,
                expected_index=expected_index,
                containment_records=containments,
                manager_secret=manager_secret,
            )
            closure_bytes = semantic_json_bytes(closure.index)
            root.atomic_write(
                ACTION_EXECUTION_INDEX_PATH,
                closure_bytes,
                expected_bytes=index_bytes,
                allow_existing_exact=False,
                failure_hook=failure_hook,
                stage_prefix="compensation-index-closure",
            )
            closed_index, closed_bytes = _action_store_read_index(root)
            if not _action_store_exact_bytes(
                closed_bytes, closure_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_COMPENSATION_CLOSURE_MISMATCH",
                    "compensation index closure differs from exact plan",
                )
            active_removed = True
            if target_active_bytes is not None:
                active_removed = root.unlink_exact(
                    target_active_relative,
                    durable_target_archive,
                    failure_hook=failure_hook,
                    stage_prefix="compensation-active-cleanup",
                )
            if compensation_active_bytes is not None:
                active_removed = (
                    root.unlink_exact(
                        compensation_active_relative,
                        durable_compensation_archive,
                        failure_hook=failure_hook,
                        stage_prefix="compensation-active-cleanup",
                    )
                    and active_removed
                )
            return ActionExecutionClosure(
                index=closed_index,
                archive_path=str(
                    self._task_dir / target_archive_relative
                ),
                active_removed=active_removed,
                mode=closure.mode,
                required_lock_claims=claims,
            )

    def cleanup_orphan_active(
        self,
        execution_id: str,
        *,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> bool:
        active_relative = action_execution_active_path(execution_id)
        archive_relative = action_execution_archive_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            archive = root.read_bytes(archive_relative)
            assert archive is not None
            active = root.read_bytes(active_relative, missing_ok=True)
            if active is None:
                return False
            if not orphan_active_matches_archive(active, archive):
                raise _action_store_error(
                    "ACTION_STORE_ORPHAN_MISMATCH",
                    "orphan active bytes do not exactly match archive",
                )
            return root.unlink_exact(
                active_relative,
                archive,
                failure_hook=failure_hook,
                stage_prefix="terminal-active-cleanup",
            )

    def release_v4_runtime_reservation(
        self,
        settled_reservation: object,
        *,
        expected_index: CASToken,
        expected_reservation_record_sha256: str,
        evidence_authority: V4RuntimeEvidenceAuthority,
        settlement_evidence: V4RuntimeSettlementEvidence,
        authoritative_event: object,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        """Release V4 scope only from controller evidence and exact outbox."""

        if (
            type(evidence_authority)
            is not V4RuntimeEvidenceAuthority
            or type(settlement_evidence)
            is not V4RuntimeSettlementEvidence
        ):
            raise _action_store_error(
                "ACTION_STORE_V4_RUNTIME_EVIDENCE_REQUIRED",
                "V4 runtime release requires exact opaque controller evidence",
            )
        try:
            evidence = evidence_authority.authenticate_settlement(
                settlement_evidence
            )
        except RuntimeAdapterError as exc:
            raise _action_store_error(
                "ACTION_STORE_V4_RUNTIME_EVIDENCE_INVALID",
                "V4 runtime settlement evidence is not authentic and fresh",
                details={"cause": exc.code},
            ) from exc

        settled = normalize_runtime_reservation(settled_reservation)
        execution_id = str(settled["execution_id"])
        effect_id = str(settled["effect_id"])
        reservation_relative = (
            _action_store_runtime_reservation_path(execution_id)
        )
        containment_relative = action_effect_containment_path(
            execution_id, effect_id
        )
        with _ActionStoreRoot(self._task_dir) as root:
            index, _ = _action_store_read_index(
                root, expected_task_id=str(settled["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            active_bytes = root.read_bytes(reservation_relative)
            assert active_bytes is not None
            active = _action_store_record(
                active_bytes,
                normalize_runtime_reservation,
                role="runtime reservation",
            )
            containment_bytes = root.read_bytes(containment_relative)
            assert containment_bytes is not None
            containment = _action_store_record(
                containment_bytes,
                normalize_containment,
                role="containment",
            )
            event_sha256 = (
                _action_store_v4_authoritative_event_sha256(
                    root, authoritative_event
                )
            )
            expected_evidence = {
                "task_id": active["task_id"],
                "execution_id": active["execution_id"],
                "effect_id": active["effect_id"],
                "claim_id": containment["claim_id"],
                "attempt_id": containment["attempt_id"],
                "runtime_handle_sha256": active[
                    "runtime_handle_sha256"
                ],
                "containment_record_sha256": active[
                    "containment_record_sha256"
                ],
                "runtime_reservation_record_sha256": active[
                    "record_sha256"
                ],
                "settlement": settled["phase"],
                "result_event_sha256": event_sha256,
            }
            mismatches = sorted(
                field
                for field, expected in expected_evidence.items()
                if evidence.get(field) != expected
            )
            if (
                active["phase"] != "ACTIVE"
                or settled["phase"] not in {"EXITED", "QUIESCED"}
                or settled["result_event_sha256"] != event_sha256
                or active["record_sha256"]
                != expected_reservation_record_sha256
                or containment["record_sha256"]
                != active["containment_record_sha256"]
                or containment["runtime_handle_sha256"]
                != active["runtime_handle_sha256"]
                or mismatches
            ):
                raise _action_store_error(
                    "ACTION_STORE_V4_RUNTIME_EVIDENCE_MISMATCH",
                    "V4 runtime evidence differs from durable reservation, "
                    "containment, settlement, or authoritative event",
                    details={"fields": mismatches},
                )

        return self.release_runtime_reservation(
            settled,
            expected_index=expected_index,
            expected_reservation_record_sha256=(
                expected_reservation_record_sha256
            ),
            authenticated_exit_or_quiescence_sha256=str(
                evidence["evidence_sha256"]
            ),
            result_or_cancellation_event_sha256=event_sha256,
            failure_hook=failure_hook,
        )

    def release_runtime_reservation(
        self,
        settled_reservation: object,
        *,
        expected_index: CASToken,
        expected_reservation_record_sha256: str,
        authenticated_exit_or_quiescence_sha256: str,
        result_or_cancellation_event_sha256: str,
        failure_hook: _ActionStoreCallable[[str], None] | None = None,
    ) -> StoredActionExecution:
        settled = normalize_runtime_reservation(settled_reservation)
        execution_id = str(settled["execution_id"])
        relative = _action_store_runtime_reservation_path(execution_id)
        with _ActionStoreRoot(self._task_dir) as root:
            index, index_bytes = _action_store_read_index(
                root, expected_task_id=str(settled["task_id"])
            )
            _action_store_assert_token(index, expected_index)
            entries = index["entries"]
            assert isinstance(entries, list)
            entry = next(
                (
                    candidate
                    for candidate in entries
                    if candidate["execution_id"] == execution_id
                ),
                None,
            )
            if (
                entry is None
                or entry["entry_kind"] != "runtime-reservation"
            ):
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RESERVATION_MISSING",
                    "index has no active runtime reservation",
                )
            active = entry["runtime_reservation"]
            assert isinstance(active, dict)
            if not _action_store_hmac.compare_digest(
                str(active["record_sha256"]),
                expected_reservation_record_sha256,
            ):
                raise _action_store_error(
                    "ACTION_STORE_CAS_CONFLICT",
                    "runtime reservation digest changed",
                )
            if (
                active["phase"] != "ACTIVE"
                or settled["phase"] not in {"EXITED", "QUIESCED"}
                or settled["result_event_sha256"]
                != result_or_cancellation_event_sha256
            ):
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RELEASE_INVALID",
                    "runtime release requires exact settlement and result event",
                )
            immutable = set(active) - {
                "phase",
                "result_event_sha256",
                "record_sha256",
            }
            if any(active[field] != settled[field] for field in immutable):
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RELEASE_INVALID",
                    "runtime settlement changed immutable reservation facts",
                )
            current_bytes = root.read_bytes(relative)
            assert current_bytes is not None
            current = _action_store_record(
                current_bytes,
                normalize_runtime_reservation,
                role="runtime reservation",
            )
            active_bytes = semantic_json_bytes(active)
            settled_bytes = semantic_json_bytes(settled)
            if _action_store_exact_bytes(
                current_bytes, settled_bytes
            ):
                status = "existing"
            else:
                if not _action_store_exact_bytes(
                    current_bytes, active_bytes
                ):
                    raise _action_store_error(
                        "ACTION_STORE_CAS_CONFLICT",
                        "durable runtime reservation changed before settlement",
                    )
                status = root.atomic_write(
                    relative,
                    settled_bytes,
                    expected_bytes=current_bytes,
                    allow_existing_exact=False,
                    failure_hook=failure_hook,
                    stage_prefix="runtime-reservation-settle",
                )
            release = plan_runtime_reservation_release(
                index,
                execution_id,
                expected_index=expected_index,
                authenticated_exit_or_quiescence_sha256=(
                    authenticated_exit_or_quiescence_sha256
                ),
                result_or_cancellation_event_sha256=(
                    result_or_cancellation_event_sha256
                ),
            )
            release_bytes = semantic_json_bytes(release.index)
            root.atomic_write(
                ACTION_EXECUTION_INDEX_PATH,
                release_bytes,
                expected_bytes=index_bytes,
                allow_existing_exact=False,
                failure_hook=failure_hook,
                stage_prefix="runtime-reservation-release",
            )
            released, released_bytes = _action_store_read_index(root)
            if not _action_store_exact_bytes(
                released_bytes, release_bytes
            ):
                raise _action_store_error(
                    "ACTION_STORE_RUNTIME_RELEASE_MISMATCH",
                    "released index differs from its exact plan",
                )
            del current
            return StoredActionExecution(
                status=status,
                index=released,
                record=settled,
                record_path=str(self._task_dir / relative),
                required_lock_claims=(
                    action_runtime_reservation_required_lock_claims(
                        settled
                    )
                ),
            )


__all__ = [
    "ACTION_EXECUTION_RUNTIME_RESERVATION_DIRECTORY",
    "ACTION_EXECUTION_STORE_FAILURE_POINTS",
    "ActionDispatchPlan",
    "CompensationDispatchPlan",
    "ActionExecutionClosure",
    "ActionExecutionRecovery",
    "ActionExecutionStore",
    "ActionExecutionStoreError",
    "StoredActionExecution",
    "action_execution_required_lock_claims",
    "action_execution_runtime_reservation_path",
    "action_runtime_reservation_required_lock_claims",
]
