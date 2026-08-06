"""Bounded, content-sensitive and read-only Git workspace evidence."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import os
from pathlib import Path
import stat
import threading
import time
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from ._platform.paths import canonical_git_path, canonical_repository_root, paths_equal
from ._platform.process import ProcessFailure, run_bounded_process
from .delivery import normalize_resource_bytes
from .model import DevFlowError, json_value
from .product import (
    MAX_INDEX_COMMAND_OUTPUT_BYTES,
    MAX_INDEX_STAGE_ENTRIES,
    WORKSPACE_SNAPSHOT_SCHEMA,
)
from .snapshot import (
    MAX_GIT_OUTPUT_BYTES,
    MAX_SNAPSHOT_CONTENT_BYTES,
    MAX_SNAPSHOT_FILE_BYTES,
    MAX_SNAPSHOT_PATH_BYTES,
    MAX_SNAPSHOT_PATHS,
    MAX_SNAPSHOT_RESOURCES,
    _MODE,
    _OBJECT_ID,
    path_key as _path_key,
    resource_key as _resource_key,
    snapshot_digest as _snapshot_digest,
    valid_relative_path as _valid_relative_path,
    validate_snapshot,
)
from .product import OPENSPEC_TASKS_NORMALIZER


GIT_COMMAND_TIMEOUT_SECONDS = 30
SNAPSHOT_TIMEOUT_SECONDS = 30
SNAPSHOT_READ_CHUNK_BYTES = 64 * 1024


_GIT_CANCEL_EVENT: contextvars.ContextVar[Optional[threading.Event]] = (
    contextvars.ContextVar("dev_flow_git_cancel_event", default=None)
)


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def _utf8(value: str) -> bytes:
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _error(
            "SNAPSHOT_PATH_INVALID",
            "snapshot paths must be valid UTF-8",
        ) from exc


class GitClient:
    """Read current repository evidence without mutating Git state."""

    @staticmethod
    @contextlib.contextmanager
    def cancellation(cancel_event: Optional[threading.Event]) -> Iterator[None]:
        """Scope optional cooperative cancellation to the current capture context."""
        token = _GIT_CANCEL_EVENT.set(cancel_event)
        try:
            yield
        finally:
            _GIT_CANCEL_EVENT.reset(token)

    @staticmethod
    def _check_cancelled(
        cancel_event: Optional[threading.Event],
    ) -> None:
        if cancel_event is None or not cancel_event.is_set():
            return
        raise DevFlowError(
            "GIT_COMMAND_CANCELLED",
            "Git evidence collection was cancelled",
        )

    @staticmethod
    def _run(
        repository: Path,
        *arguments: str,
        timeout_seconds: Optional[float] = None,
        output_limit_bytes: Optional[int] = None,
    ) -> bytes:
        cancel_event = _GIT_CANCEL_EVENT.get()
        GitClient._check_cancelled(cancel_event)
        effective_output_limit = (
            MAX_GIT_OUTPUT_BYTES
            if output_limit_bytes is None
            else output_limit_bytes
        )
        inherited_names = ("PATH", "HOME")
        if os.name == "nt":
            inherited_names = (
                "PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC",
                "PATHEXT", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
                "HOMEPATH", "HOME",
            )
        environment = {
            name: os.environ[name]
            for name in inherited_names
            if name in os.environ
        }
        environment.update({
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
        })
        command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repository),
            *arguments,
        ]
        effective_timeout = (
            GIT_COMMAND_TIMEOUT_SECONDS
            if timeout_seconds is None
            else max(0.001, timeout_seconds)
        )
        try:
            result = run_bounded_process(
                command, environment, effective_timeout, effective_output_limit,
                cancel_event,
            )
        except ProcessFailure as exc:
            details = {"arguments": list(arguments), **exc.details}
            if exc.kind == "unavailable":
                raise DevFlowError("GIT_UNAVAILABLE", "Git could not be executed", details=details) from exc
            if exc.kind == "cancelled":
                raise DevFlowError("GIT_COMMAND_CANCELLED", "Git evidence collection was cancelled", details=details) from exc
            if exc.kind == "timeout":
                details["timeout_seconds"] = effective_timeout
                raise DevFlowError("GIT_COMMAND_TIMEOUT", "Git command exceeded the preflight time budget", details=details) from exc
            if exc.kind == "output-too-large":
                raise DevFlowError("GIT_OUTPUT_TOO_LARGE", "Git output exceeds the preflight budget", details=details) from exc
            raise DevFlowError("GIT_COMMAND_FAILED", "Git evidence collection failed", details=details) from exc
        if result.returncode != 0:
            raise DevFlowError(
                "GIT_COMMAND_FAILED",
                "required Git evidence is unavailable",
                details={
                    "arguments": list(arguments),
                    "returncode": result.returncode,
                    "stderr": result.stderr.decode(
                        "utf-8",
                        errors="replace",
                    )[:1024],
                },
            )
        return result.stdout

    @classmethod
    def _text(cls, repository: Path, *arguments: str) -> str:
        raw = cls._run(repository, *arguments)
        return cls._decode_text(raw, arguments)

    @staticmethod
    def _decode_text(raw: bytes, arguments: Iterable[str]) -> str:
        try:
            return raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise DevFlowError(
                "GIT_OUTPUT_INVALID",
                "required Git output is not UTF-8",
                details={"arguments": list(arguments)},
            ) from exc

    @classmethod
    def _run_snapshot(
        cls,
        repository: Path,
        deadline: float,
        *arguments: str,
        output_limit_bytes: Optional[int] = None,
    ) -> bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _error(
                "SNAPSHOT_BUDGET_EXCEEDED",
                "workspace snapshot exceeded its elapsed-time budget",
                limit_seconds=SNAPSHOT_TIMEOUT_SECONDS,
            )
        return cls._run(
            repository,
            *arguments,
            timeout_seconds=min(float(GIT_COMMAND_TIMEOUT_SECONDS), remaining),
            output_limit_bytes=output_limit_bytes,
        )

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if time.monotonic() > deadline:
            raise _error(
                "SNAPSHOT_BUDGET_EXCEEDED",
                "workspace snapshot exceeded its elapsed-time budget",
                limit_seconds=SNAPSHOT_TIMEOUT_SECONDS,
            )

    @classmethod
    def _branch_bytes(cls, repository: Path, deadline: float) -> Optional[bytes]:
        try:
            return cls._run_snapshot(
                repository,
                deadline,
                "symbolic-ref",
                "--quiet",
                "--short",
                "HEAD",
            )
        except DevFlowError as exc:
            if exc.code == "GIT_COMMAND_FAILED" and exc.details.get("returncode") == 1:
                return None
            raise

    @classmethod
    def _capture_enumeration(cls, repository: Path, deadline: float) -> dict:
        evidence = {
            "top_level": cls._run_snapshot(
                repository, deadline, "rev-parse", "--show-toplevel"
            ),
            "git_common": cls._run_snapshot(
                repository, deadline, "rev-parse", "--git-common-dir"
            ),
            "git_worktree": cls._run_snapshot(
                repository, deadline, "rev-parse", "--git-dir"
            ),
            "object_format": cls._run_snapshot(
                repository, deadline, "rev-parse", "--show-object-format"
            ),
            "head": cls._run_snapshot(repository, deadline, "rev-parse", "HEAD"),
            "branch": cls._branch_bytes(repository, deadline),
            "status": cls._run_snapshot(
                repository,
                deadline,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ),
            "tracked": cls._run_snapshot(
                repository,
                deadline,
                "diff-index",
                "--no-ext-diff",
                "--name-only",
                "-z",
                "--no-renames",
                "HEAD",
                "--",
            ),
            "untracked": cls._run_snapshot(
                repository,
                deadline,
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
            ),
        }
        for field in (
            "top_level", "git_common", "git_worktree", "object_format", "head", "status"
        ):
            cls._decode_text(evidence[field], (field,))
        if evidence["branch"] is not None:
            cls._decode_text(evidence["branch"], ("branch",))
        return evidence

    @staticmethod
    def _decode_paths(raw: bytes, source: str) -> tuple:
        if raw and not raw.endswith(b"\x00"):
            raise _error(
                "GIT_OUTPUT_INVALID",
                "Git path enumeration is not NUL terminated",
                source=source,
            )
        result = []
        for encoded in raw.split(b"\x00")[:-1]:
            try:
                path = encoded.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise _error(
                    "GIT_OUTPUT_INVALID",
                    "Git returned a path that is not UTF-8",
                    source=source,
                ) from exc
            if not _valid_relative_path(path):
                raise _error(
                    "SNAPSHOT_PATH_INVALID",
                    "Git returned a non-canonical repository-relative path",
                    path=path,
                    source=source,
                )
            result.append(path)
        return tuple(result)

    @staticmethod
    def _resource_requests(resources: Sequence[Mapping[str, object]]) -> tuple:
        if isinstance(resources, (str, bytes, Mapping)):
            raise _error("SNAPSHOT_RESOURCE_INVALID", "resource requests must be a sequence")
        normalized = []
        seen = set()
        try:
            iterator = iter(resources)
        except TypeError as exc:
            raise _error("SNAPSHOT_RESOURCE_INVALID", "resource requests must be a sequence") from exc
        for item in iterator:
            if len(normalized) >= MAX_SNAPSHOT_RESOURCES:
                raise _error(
                    "SNAPSHOT_BUDGET_EXCEEDED",
                    "resource request count exceeds the snapshot budget",
                    limit=MAX_SNAPSHOT_RESOURCES,
                )
            if not isinstance(item, Mapping) or set(item) != {"path", "role", "normalizer"}:
                raise _error("SNAPSHOT_RESOURCE_INVALID", "resource request fields are invalid")
            path = item.get("path")
            role = item.get("role")
            normalizer = item.get("normalizer")
            if (
                not _valid_relative_path(path)
                or role not in ("governing", "reported")
                or normalizer not in ("none", OPENSPEC_TASKS_NORMALIZER)
            ):
                raise _error(
                    "SNAPSHOT_RESOURCE_INVALID",
                    "resource request is invalid",
                    path=path if isinstance(path, str) else None,
                )
            identity = (path, role, normalizer)
            if identity in seen:
                raise _error(
                    "SNAPSHOT_RESOURCE_INVALID",
                    "resource request is duplicated",
                    path=path,
                )
            seen.add(identity)
            normalized.append({"path": path, "role": role, "normalizer": normalizer})
        return tuple(sorted(normalized, key=_resource_key))

    @staticmethod
    def _directory_identity(value: os.stat_result) -> tuple:
        return (
            value.st_dev,
            value.st_ino,
            stat.S_IFMT(value.st_mode),
            stat.S_IMODE(value.st_mode),
        )

    @staticmethod
    def _file_identity(value: os.stat_result) -> tuple:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    @staticmethod
    def _directory_flags() -> int:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory = getattr(os, "O_DIRECTORY", 0)
        if not nofollow or not directory:
            raise _error(
                "SNAPSHOT_UNSUPPORTED",
                "this platform cannot safely open repository directories without following links",
            )
        return (
            os.O_RDONLY
            | nofollow
            | directory
            | getattr(os, "O_CLOEXEC", 0)
        )

    @classmethod
    def _open_root(cls, root: Path) -> tuple:
        try:
            before = os.stat(str(root), follow_symlinks=False)
            descriptor = os.open(str(root), cls._directory_flags())
            opened = os.fstat(descriptor)
        except OSError as exc:
            raise _error(
                "REPOSITORY_INVALID",
                "repository root cannot be opened safely",
                path=str(root),
                error=str(exc),
            ) from exc
        if not stat.S_ISDIR(before.st_mode) or cls._directory_identity(before) != cls._directory_identity(opened):
            os.close(descriptor)
            raise _error(
                "SNAPSHOT_UNSTABLE",
                "repository root changed while the snapshot was opened",
                path=str(root),
            )
        return descriptor, cls._directory_identity(opened)

    @classmethod
    def _lookup_parent(cls, root_fd: int, path: str) -> dict:
        components = [_utf8(component) for component in path.split("/")]
        current = os.dup(root_fd)
        parents = [cls._directory_identity(os.fstat(current))]
        for index, component in enumerate(components[:-1]):
            try:
                before = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                os.close(current)
                return {"parent_fd": None, "parents": tuple(parents), "missing_at": index}
            except OSError as exc:
                os.close(current)
                raise _error(
                    "SNAPSHOT_PATH_UNSAFE",
                    "snapshot parent path cannot be inspected safely",
                    path=path,
                    error=str(exc),
                ) from exc
            if not stat.S_ISDIR(before.st_mode):
                os.close(current)
                raise _error(
                    "SNAPSHOT_PATH_UNSAFE",
                    "snapshot parent path is not a real directory",
                    path=path,
                )
            try:
                child = os.open(component, cls._directory_flags(), dir_fd=current)
                opened = os.fstat(child)
            except OSError as exc:
                os.close(current)
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot parent path changed while it was opened",
                    path=path,
                    error=str(exc),
                ) from exc
            if cls._directory_identity(before) != cls._directory_identity(opened):
                os.close(child)
                os.close(current)
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot parent path was replaced while it was opened",
                    path=path,
                )
            os.close(current)
            current = child
            parents.append(cls._directory_identity(opened))
        return {
            "parent_fd": current,
            "parents": tuple(parents),
            "missing_at": None,
            "name": components[-1],
        }

    @classmethod
    def _index_entries(
        cls,
        repository: Path,
        paths: Sequence[str],
        deadline: float,
    ) -> tuple:
        if not paths:
            return b"", {}
        arguments = ["ls-files", "--stage", "-z", "--"]
        arguments.extend(":(literal){}".format(path) for path in paths)
        raw = cls._run_snapshot(
            repository,
            deadline,
            *arguments,
            output_limit_bytes=MAX_INDEX_COMMAND_OUTPUT_BYTES,
        )
        if raw and not raw.endswith(b"\x00"):
            raise _error("GIT_OUTPUT_INVALID", "Git index enumeration is not NUL terminated")
        requested = set(paths)
        result = {}
        entry_count = 0
        for encoded in raw.split(b"\x00")[:-1]:
            try:
                header, encoded_path = encoded.split(b"\t", 1)
                mode_raw, oid_raw, stage_raw = header.split()
                path = encoded_path.decode("utf-8")
                mode = mode_raw.decode("ascii")
                oid = oid_raw.decode("ascii")
                stage = stage_raw.decode("ascii")
            except (ValueError, UnicodeDecodeError) as exc:
                raise _error("GIT_OUTPUT_INVALID", "Git index entry is malformed") from exc
            if (
                not _valid_relative_path(path)
                or not _MODE.fullmatch(mode)
                or not _OBJECT_ID.fullmatch(oid)
                or stage not in ("0", "1", "2", "3")
            ):
                raise _error("GIT_OUTPUT_INVALID", "Git index entry is invalid", path=path)
            if path in requested:
                entry_count += 1
                if entry_count > MAX_INDEX_STAGE_ENTRIES:
                    raise _error(
                        "SNAPSHOT_BUDGET_EXCEEDED",
                        "Git index entry enumeration exceeds its budget",
                        entry_count=entry_count,
                        entry_limit=MAX_INDEX_STAGE_ENTRIES,
                    )
                if any(item[2] == stage for item in result.get(path, ())):
                    raise _error(
                        "GIT_OUTPUT_INVALID",
                        "Git index contains a duplicate path stage",
                        path=path,
                        stage=stage,
                    )
                result.setdefault(path, []).append((mode, oid, stage))
        return raw, {
            path: tuple(sorted(items, key=lambda item: (int(item[2]), item[0], item[1])))
            for path, items in result.items()
        }

    @staticmethod
    def _serialized_index_entries(
        path: str,
        index_entries: Mapping[str, Sequence[tuple]],
    ) -> list:
        return [
            {"mode": mode, "oid": oid, "stage": int(stage)}
            for mode, oid, stage in index_entries.get(path, ())
        ]

    @classmethod
    def _head_entries(
        cls,
        repository: Path,
        paths: Sequence[str],
        deadline: float,
    ) -> tuple:
        """Read the immutable HEAD-tree identity for only the bounded snapshot paths."""
        if not paths:
            return b"", {}
        arguments = ["ls-tree", "-z", "HEAD", "--"]
        arguments.extend(":(literal){}".format(path) for path in paths)
        raw = cls._run_snapshot(
            repository,
            deadline,
            *arguments,
            output_limit_bytes=MAX_INDEX_COMMAND_OUTPUT_BYTES,
        )
        if raw and not raw.endswith(b"\x00"):
            raise _error("GIT_OUTPUT_INVALID", "Git HEAD-tree enumeration is not NUL terminated")
        requested = set(paths)
        result = {}
        for encoded in raw.split(b"\x00")[:-1]:
            try:
                header, encoded_path = encoded.split(b"\t", 1)
                mode_raw, type_raw, oid_raw = header.split()
                path = encoded_path.decode("utf-8")
                mode = mode_raw.decode("ascii")
                object_type = type_raw.decode("ascii")
                oid = oid_raw.decode("ascii")
            except (ValueError, UnicodeDecodeError) as exc:
                raise _error("GIT_OUTPUT_INVALID", "Git HEAD-tree entry is malformed") from exc
            if (
                path not in requested
                or not _valid_relative_path(path)
                or not _MODE.fullmatch(mode)
                or not _OBJECT_ID.fullmatch(oid)
                or object_type not in ("blob", "commit")
                or (object_type == "commit") != (mode == "160000")
                or path in result
            ):
                raise _error("GIT_OUTPUT_INVALID", "Git HEAD-tree entry is invalid", path=path)
            result[path] = {"mode": mode, "oid": oid}
        return raw, result

    @staticmethod
    def _gitlink_entry(path: str, index_entries: Mapping[str, Sequence[tuple]]) -> Optional[tuple]:
        items = tuple(index_entries.get(path, ()))
        gitlinks = [item for item in items if item[0] == "160000"]
        if not gitlinks:
            return None
        return next((item for item in gitlinks if item[2] == "0"), gitlinks[0])

    @staticmethod
    def _special_kind(mode: int) -> str:
        if stat.S_ISDIR(mode):
            return "directory"
        if stat.S_ISFIFO(mode):
            return "fifo"
        if stat.S_ISSOCK(mode):
            return "socket"
        if stat.S_ISCHR(mode):
            return "character-device"
        if stat.S_ISBLK(mode):
            return "block-device"
        return "special"

    @staticmethod
    def _consume_content(total: list, amount: int, path: str) -> None:
        if amount > MAX_SNAPSHOT_FILE_BYTES:
            raise _error(
                "SNAPSHOT_BUDGET_EXCEEDED",
                "snapshot entry exceeds the per-file content budget",
                path=path,
                limit_bytes=MAX_SNAPSHOT_FILE_BYTES,
            )
        if total[0] + amount > MAX_SNAPSHOT_CONTENT_BYTES:
            raise _error(
                "SNAPSHOT_BUDGET_EXCEEDED",
                "snapshot content exceeds the total byte budget",
                path=path,
                limit_bytes=MAX_SNAPSHOT_CONTENT_BYTES,
            )
        total[0] += amount

    @classmethod
    def _read_regular(
        cls,
        parent_fd: int,
        name: bytes,
        before: os.stat_result,
        path: str,
        deadline: float,
        total: list,
    ) -> bytes:
        if before.st_size > MAX_SNAPSHOT_FILE_BYTES:
            cls._consume_content(total, before.st_size, path)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise _error(
                "SNAPSHOT_UNSTABLE",
                "snapshot file changed before it could be opened safely",
                path=path,
                error=str(exc),
            ) from exc
        data = bytearray()
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or cls._file_identity(before) != cls._file_identity(opened):
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot file was replaced while it was opened",
                    path=path,
                )
            while True:
                cls._check_deadline(deadline)
                try:
                    chunk = os.read(descriptor, SNAPSHOT_READ_CHUNK_BYTES)
                except OSError as exc:
                    raise _error(
                        "SNAPSHOT_READ_FAILED",
                        "snapshot file could not be read",
                        path=path,
                        error=str(exc),
                    ) from exc
                if not chunk:
                    break
                if len(data) + len(chunk) > MAX_SNAPSHOT_FILE_BYTES:
                    raise _error(
                        "SNAPSHOT_BUDGET_EXCEEDED",
                        "snapshot entry exceeds the per-file content budget",
                        path=path,
                        limit_bytes=MAX_SNAPSHOT_FILE_BYTES,
                    )
                cls._consume_content(total, len(chunk), path)
                data.extend(chunk)
            after = os.fstat(descriptor)
            if cls._file_identity(opened) != cls._file_identity(after):
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot file changed while it was read",
                    path=path,
                )
        finally:
            os.close(descriptor)
        try:
            final = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise _error(
                "SNAPSHOT_UNSTABLE",
                "snapshot file changed after it was read",
                path=path,
                error=str(exc),
            ) from exc
        if cls._file_identity(before) != cls._file_identity(final):
            raise _error(
                "SNAPSHOT_UNSTABLE",
                "snapshot file changed while it was read",
                path=path,
            )
        return bytes(data)

    @classmethod
    def _gitlink_state(cls, path: Path, display_path: str, deadline: float) -> tuple:
        try:
            top_raw = cls._run_snapshot(path, deadline, "rev-parse", "--show-toplevel")
            head_raw = cls._run_snapshot(path, deadline, "rev-parse", "HEAD")
            status = cls._run_snapshot(
                path,
                deadline,
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            )
        except DevFlowError as exc:
            if exc.code == "GIT_COMMAND_FAILED":
                raise _error(
                    "SNAPSHOT_GITLINK_MISSING",
                    "gitlink is not an initialized submodule",
                    path=display_path,
                ) from exc
            raise
        top = cls._decode_text(top_raw, ("rev-parse", "--show-toplevel"))
        head = cls._decode_text(head_raw, ("rev-parse", "HEAD"))
        cls._decode_text(status, ("status",))
        try:
            canonical_top = canonical_git_path(top, repository_root=path)
            canonical_path = canonical_repository_root(path)
        except (OSError, RuntimeError, ValueError):
            canonical_top = None
            canonical_path = path
        if not paths_equal(canonical_top, canonical_path) or not _OBJECT_ID.fullmatch(head):
            raise _error(
                "SNAPSHOT_GITLINK_MISSING",
                "gitlink is not an initialized submodule",
                path=display_path,
            )
        if status:
            raise _error(
                "SNAPSHOT_GITLINK_DIRTY",
                "gitlink submodule contains uncommitted changes",
                path=display_path,
                status_sha256=hashlib.sha256(status).hexdigest(),
            )
        return top_raw, head_raw, status, head

    @classmethod
    def _read_path(
        cls,
        root: Path,
        root_fd: Optional[int],
        path: str,
        index_entries: Mapping[str, Sequence[tuple]],
        head_entries: Mapping[str, Mapping[str, str]],
        deadline: float,
        total: list,
        object_format: str,
    ) -> tuple:
        if os.name == "nt":
            return cls._read_path_windows(
                root, path, index_entries, head_entries, deadline, total,
                object_format,
            )
        if root_fd is None:
            raise AssertionError("POSIX snapshot requires a root descriptor")
        cls._check_deadline(deadline)
        lookup = cls._lookup_parent(root_fd, path)
        gitlink = cls._gitlink_entry(path, index_entries)
        serialized_index = cls._serialized_index_entries(path, index_entries)
        head_entry = json_value(head_entries.get(path))
        parent_fd = lookup.get("parent_fd")
        if parent_fd is None:
            if gitlink is not None:
                raise _error(
                    "SNAPSHOT_GITLINK_MISSING",
                    "gitlink worktree is missing",
                    path=path,
                )
            entry = {
                "path": path,
                "kind": "missing",
                "mode": None,
                "size": 0,
                "content_sha256": None,
                "worktree_oid": None,
                "index_entries": serialized_index,
                "head_entry": head_entry,
                "submodule_head": None,
            }
            observation = {
                "parents": lookup["parents"],
                "missing_at": lookup["missing_at"],
                "kind": "missing",
            }
            return entry, None, observation
        name = lookup["name"]
        try:
            try:
                before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                if gitlink is not None:
                    raise _error(
                        "SNAPSHOT_GITLINK_MISSING",
                        "gitlink worktree is missing",
                        path=path,
                    )
                entry = {
                    "path": path,
                    "kind": "missing",
                    "mode": None,
                    "size": 0,
                    "content_sha256": None,
                    "worktree_oid": None,
                    "index_entries": serialized_index,
                    "head_entry": head_entry,
                    "submodule_head": None,
                }
                observation = {
                    "parents": lookup["parents"],
                    "missing_at": len(path.split("/")) - 1,
                    "kind": "missing",
                }
                return entry, None, observation
            except OSError as exc:
                raise _error(
                    "SNAPSHOT_READ_FAILED",
                    "snapshot entry cannot be inspected",
                    path=path,
                    error=str(exc),
                ) from exc

            if gitlink is not None:
                if not stat.S_ISDIR(before.st_mode):
                    raise _error(
                        "SNAPSHOT_GITLINK_MISSING",
                        "gitlink worktree is missing",
                        path=path,
                    )
                state = cls._gitlink_state(root / path, path, deadline)
                serialized_index_bytes = b"\x00".join(
                    "{} {} {}".format(
                        item["mode"], item["oid"], item["stage"]
                    ).encode("ascii")
                    for item in serialized_index
                )
                raw = (
                    b"gitlink\x00"
                    + serialized_index_bytes
                    + b"\x00"
                    + state[3].encode("ascii")
                )
                cls._consume_content(total, len(raw), path)
                entry = {
                    "path": path,
                    "kind": "gitlink",
                    "mode": "160000",
                    "size": 0,
                    "content_sha256": None,
                    "worktree_oid": state[3],
                    "index_entries": serialized_index,
                    "head_entry": head_entry,
                    "submodule_head": state[3],
                }
                observation = {
                    "parents": lookup["parents"],
                    "missing_at": None,
                    "kind": "gitlink",
                    "identity": cls._file_identity(before),
                    "gitlink_state": state[:3],
                }
                return entry, raw, observation

            if stat.S_ISREG(before.st_mode):
                raw = cls._read_regular(parent_fd, name, before, path, deadline, total)
                kind = "regular"
            elif stat.S_ISLNK(before.st_mode):
                try:
                    raw = os.readlink(name, dir_fd=parent_fd)
                except OSError as exc:
                    raise _error(
                        "SNAPSHOT_UNSTABLE",
                        "snapshot symbolic link changed while it was read",
                        path=path,
                        error=str(exc),
                    ) from exc
                if isinstance(raw, str):
                    raw = _utf8(raw)
                cls._consume_content(total, len(raw), path)
                try:
                    after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except OSError as exc:
                    raise _error(
                        "SNAPSHOT_UNSTABLE",
                        "snapshot symbolic link changed while it was read",
                        path=path,
                        error=str(exc),
                    ) from exc
                if cls._file_identity(before) != cls._file_identity(after):
                    raise _error(
                        "SNAPSHOT_UNSTABLE",
                        "snapshot symbolic link changed while it was read",
                        path=path,
                    )
                kind = "symlink"
            else:
                raise _error(
                    "SNAPSHOT_SPECIAL_FILE",
                    "snapshot path has an unsupported filesystem type",
                    path=path,
                    kind=cls._special_kind(before.st_mode),
                )
            entry = {
                "path": path,
                "kind": kind,
                "mode": "{:06o}".format(before.st_mode),
                "size": len(raw),
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "worktree_oid": cls._blob_oid(raw, object_format),
                "index_entries": serialized_index,
                "head_entry": head_entry,
                "submodule_head": None,
            }
            observation = {
                "parents": lookup["parents"],
                "missing_at": None,
                "kind": kind,
                "identity": cls._file_identity(before),
                "raw": raw if kind == "symlink" else None,
            }
            return entry, raw, observation
        finally:
            os.close(parent_fd)

    @classmethod
    def _read_path_windows(
        cls,
        root: Path,
        path: str,
        index_entries: Mapping[str, Sequence[tuple]],
        head_entries: Mapping[str, Mapping[str, str]],
        deadline: float,
        total: list,
        object_format: str,
    ) -> tuple:
        cls._check_deadline(deadline)
        target = root.joinpath(*path.split("/"))
        gitlink = cls._gitlink_entry(path, index_entries)
        serialized_index = cls._serialized_index_entries(path, index_entries)
        head_entry = json_value(head_entries.get(path))
        try:
            before = target.lstat()
        except FileNotFoundError:
            if gitlink is not None:
                raise _error("SNAPSHOT_GITLINK_MISSING", "gitlink worktree is missing", path=path)
            entry = {
                "path": path, "kind": "missing", "mode": None, "size": 0,
                "content_sha256": None, "worktree_oid": None,
                "index_entries": serialized_index, "head_entry": head_entry,
                "submodule_head": None,
            }
            return entry, None, {"kind": "missing"}
        except OSError as exc:
            raise _error(
                "SNAPSHOT_READ_FAILED", "snapshot entry cannot be inspected",
                path=path, error=str(exc),
            ) from exc

        if gitlink is not None:
            if not stat.S_ISDIR(before.st_mode):
                raise _error("SNAPSHOT_GITLINK_MISSING", "gitlink worktree is missing", path=path)
            state = cls._gitlink_state(target, path, deadline)
            serialized_bytes = b"\x00".join(
                "{} {} {}".format(item["mode"], item["oid"], item["stage"]).encode("ascii")
                for item in serialized_index
            )
            raw = b"gitlink\x00" + serialized_bytes + b"\x00" + state[3].encode("ascii")
            cls._consume_content(total, len(raw), path)
            entry = {
                "path": path, "kind": "gitlink", "mode": "160000", "size": 0,
                "content_sha256": None, "worktree_oid": state[3],
                "index_entries": serialized_index, "head_entry": head_entry,
                "submodule_head": state[3],
            }
            observation = {
                "kind": "gitlink", "identity": cls._file_identity(before),
                "gitlink_state": state[:3],
            }
            return entry, raw, observation

        if stat.S_ISREG(before.st_mode):
            if before.st_size > MAX_SNAPSHOT_FILE_BYTES:
                cls._consume_content(total, before.st_size, path)
            data = bytearray()
            try:
                with target.open("rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if cls._file_identity(before) != cls._file_identity(opened):
                        raise _error(
                            "SNAPSHOT_UNSTABLE", "snapshot file was replaced while it was opened",
                            path=path,
                        )
                    while True:
                        cls._check_deadline(deadline)
                        chunk = stream.read(SNAPSHOT_READ_CHUNK_BYTES)
                        if not chunk:
                            break
                        if len(data) + len(chunk) > MAX_SNAPSHOT_FILE_BYTES:
                            raise _error(
                                "SNAPSHOT_BUDGET_EXCEEDED",
                                "snapshot entry exceeds the per-file content budget",
                                path=path, limit_bytes=MAX_SNAPSHOT_FILE_BYTES,
                            )
                        cls._consume_content(total, len(chunk), path)
                        data.extend(chunk)
            except DevFlowError:
                raise
            except OSError as exc:
                raise _error(
                    "SNAPSHOT_READ_FAILED", "snapshot file could not be read",
                    path=path, error=str(exc),
                ) from exc
            try:
                after = target.lstat()
            except OSError as exc:
                raise _error(
                    "SNAPSHOT_UNSTABLE", "snapshot file changed while it was read",
                    path=path, error=str(exc),
                ) from exc
            if cls._file_identity(before) != cls._file_identity(after):
                raise _error("SNAPSHOT_UNSTABLE", "snapshot file changed while it was read", path=path)
            raw = bytes(data)
            kind = "regular"
        elif stat.S_ISLNK(before.st_mode):
            try:
                link = os.readlink(str(target))
                raw = _utf8(link) if isinstance(link, str) else link
                after = target.lstat()
            except OSError as exc:
                raise _error(
                    "SNAPSHOT_UNSTABLE", "snapshot symbolic link changed while it was read",
                    path=path, error=str(exc),
                ) from exc
            if cls._file_identity(before) != cls._file_identity(after):
                raise _error(
                    "SNAPSHOT_UNSTABLE", "snapshot symbolic link changed while it was read",
                    path=path,
                )
            cls._consume_content(total, len(raw), path)
            kind = "symlink"
        else:
            raise _error(
                "SNAPSHOT_SPECIAL_FILE", "snapshot path has an unsupported filesystem type",
                path=path, kind=cls._special_kind(before.st_mode),
            )
        entry = {
            "path": path, "kind": kind, "mode": "{:06o}".format(before.st_mode),
            "size": len(raw), "content_sha256": hashlib.sha256(raw).hexdigest(),
            "worktree_oid": cls._blob_oid(raw, object_format),
            "index_entries": serialized_index, "head_entry": head_entry,
            "submodule_head": None,
        }
        observation = {
            "kind": kind, "identity": cls._file_identity(before),
            "raw": raw if kind == "symlink" else None,
        }
        return entry, raw, observation

    @classmethod
    def _verify_observation(
        cls,
        root: Path,
        root_fd: Optional[int],
        path: str,
        observation: Mapping[str, object],
        deadline: float,
    ) -> None:
        if os.name == "nt":
            cls._verify_observation_windows(root, path, observation, deadline)
            return
        if root_fd is None:
            raise AssertionError("POSIX snapshot requires a root descriptor")
        cls._check_deadline(deadline)
        lookup = cls._lookup_parent(root_fd, path)
        parent_fd = lookup.get("parent_fd")
        try:
            if lookup["parents"] != observation["parents"]:
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot parent path changed during collection",
                    path=path,
                )
            if parent_fd is None:
                actual_missing = lookup["missing_at"]
                if observation["kind"] == "missing" and actual_missing == observation["missing_at"]:
                    return
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot path changed during collection",
                    path=path,
                )
            try:
                current = os.stat(lookup["name"], dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                actual_missing = len(path.split("/")) - 1
                if observation["kind"] == "missing" and actual_missing == observation["missing_at"]:
                    return
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot path changed during collection",
                    path=path,
                )
            if observation["kind"] == "missing" or cls._file_identity(current) != observation["identity"]:
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "snapshot path changed during collection",
                    path=path,
                )
            if observation["kind"] == "symlink":
                target = os.readlink(lookup["name"], dir_fd=parent_fd)
                if isinstance(target, str):
                    target = _utf8(target)
                if target != observation["raw"]:
                    raise _error(
                        "SNAPSHOT_UNSTABLE",
                        "snapshot symbolic link changed during collection",
                        path=path,
                    )
            elif observation["kind"] == "gitlink":
                state = cls._gitlink_state(root / path, path, deadline)
                if state[:3] != observation["gitlink_state"]:
                    raise _error(
                        "SNAPSHOT_UNSTABLE",
                        "gitlink changed during snapshot collection",
                        path=path,
                    )
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

    @classmethod
    def _verify_observation_windows(
        cls,
        root: Path,
        path: str,
        observation: Mapping[str, object],
        deadline: float,
    ) -> None:
        cls._check_deadline(deadline)
        target = root.joinpath(*path.split("/"))
        try:
            current = target.lstat()
        except FileNotFoundError:
            if observation["kind"] == "missing":
                return
            raise _error(
                "SNAPSHOT_UNSTABLE", "snapshot path changed during collection", path=path
            )
        if observation["kind"] == "missing" or cls._file_identity(current) != observation["identity"]:
            raise _error(
                "SNAPSHOT_UNSTABLE", "snapshot path changed during collection", path=path
            )
        if observation["kind"] == "symlink":
            target_value = os.readlink(str(target))
            raw = _utf8(target_value) if isinstance(target_value, str) else target_value
            if raw != observation["raw"]:
                raise _error(
                    "SNAPSHOT_UNSTABLE", "snapshot symbolic link changed during collection",
                    path=path,
                )
        elif observation["kind"] == "gitlink":
            state = cls._gitlink_state(target, path, deadline)
            if state[:3] != observation["gitlink_state"]:
                raise _error(
                    "SNAPSHOT_UNSTABLE", "gitlink changed during snapshot collection", path=path
                )

    @classmethod
    def snapshot(
        cls,
        repository_path: str,
        resources: Sequence[Mapping[str, object]] = (),
    ) -> dict:
        """Capture one bounded content snapshot of an exact Git worktree root."""
        deadline = time.monotonic() + SNAPSHOT_TIMEOUT_SECONDS
        requests = cls._resource_requests(resources)
        try:
            supplied = canonical_repository_root(repository_path)
            _utf8(str(supplied))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise _error(
                "REPOSITORY_INVALID",
                "repository path cannot be resolved",
                path=str(repository_path),
            ) from exc
        if not supplied.is_dir():
            raise _error(
                "REPOSITORY_INVALID",
                "repository path is not a directory",
                path=str(supplied),
            )
        top_raw = cls._run_snapshot(supplied, deadline, "rev-parse", "--show-toplevel")
        try:
            root = canonical_git_path(
                cls._decode_text(top_raw, ("rev-parse", "--show-toplevel")),
                repository_root=supplied,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise _error(
                "REPOSITORY_INVALID", "Git worktree root cannot be resolved",
                path=str(supplied), error=str(exc),
            ) from exc
        if not paths_equal(root, supplied):
            raise _error(
                "REPOSITORY_ROOT_REQUIRED",
                "repository path must name the Git worktree root",
                path=str(supplied),
                root=str(root),
            )
        initial = cls._capture_enumeration(root, deadline)
        initial_root = canonical_git_path(
            cls._decode_text(initial["top_level"], ("top_level",)),
            repository_root=root,
        )
        if not paths_equal(initial_root, root):
            raise _error(
                "SNAPSHOT_UNSTABLE",
                "repository root changed during snapshot collection",
                path=str(root),
            )
        tracked = cls._decode_paths(initial["tracked"], "tracked")
        untracked = cls._decode_paths(initial["untracked"], "untracked")
        requested_paths = tuple(request["path"] for request in requests)
        paths = tuple(sorted(set(tracked) | set(untracked) | set(requested_paths), key=_path_key))
        path_bytes = sum(len(_utf8(path)) for path in paths)
        if len(paths) > MAX_SNAPSHOT_PATHS or path_bytes > MAX_SNAPSHOT_PATH_BYTES:
            raise _error(
                "SNAPSHOT_BUDGET_EXCEEDED",
                "snapshot path enumeration exceeds its budget",
                path_count=len(paths),
                path_bytes=path_bytes,
                path_limit=MAX_SNAPSHOT_PATHS,
                byte_limit=MAX_SNAPSHOT_PATH_BYTES,
            )
        object_format = cls._decode_text(
            initial["object_format"], ("rev-parse", "--show-object-format")
        )
        if object_format not in ("sha1", "sha256"):
            raise _error("GIT_OUTPUT_INVALID", "Git object format is unsupported")
        initial_index, index_entries = cls._index_entries(root, paths, deadline)
        initial_head_tree, head_entries = cls._head_entries(root, paths, deadline)
        if os.name == "nt":
            root_fd = None
            root_identity = cls._directory_identity(root.lstat())
        else:
            root_fd, root_identity = cls._open_root(root)
        entries = []
        raw_by_path = {}
        observations = {}
        total = [0]
        try:
            for path in paths:
                entry, raw, observation = cls._read_path(
                    root,
                    root_fd,
                    path,
                    index_entries,
                    head_entries,
                    deadline,
                    total,
                    object_format,
                )
                entries.append(entry)
                raw_by_path[path] = raw
                observations[path] = observation
            final = cls._capture_enumeration(root, deadline)
            final_index, _ = cls._index_entries(root, paths, deadline)
            final_head_tree, _ = cls._head_entries(root, paths, deadline)
            if (
                final != initial
                or final_index != initial_index
                or final_head_tree != initial_head_tree
            ):
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "Git repository metadata or path enumeration changed during collection",
                )
            for path in paths:
                cls._verify_observation(root, root_fd, path, observations[path], deadline)
            try:
                final_root = os.stat(str(root), follow_symlinks=False)
            except OSError as exc:
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "repository root changed during snapshot collection",
                    path=str(root),
                    error=str(exc),
                ) from exc
            if cls._directory_identity(final_root) != root_identity:
                raise _error(
                    "SNAPSHOT_UNSTABLE",
                    "repository root changed during snapshot collection",
                    path=str(root),
                )
        finally:
            if root_fd is not None:
                os.close(root_fd)
        cls._check_deadline(deadline)

        resource_entries = []
        entry_kinds = {entry["path"]: entry["kind"] for entry in entries}
        for request in requests:
            raw = raw_by_path[request["path"]]
            if raw is None:
                raw_digest = None
                semantic_digest = None
            else:
                raw_digest = hashlib.sha256(raw).hexdigest()
                semantic_digest = hashlib.sha256(
                    normalize_resource_bytes(raw, request["normalizer"])
                ).hexdigest()
            resource_entries.append(
                {
                    **request,
                    "kind": entry_kinds[request["path"]],
                    "raw_sha256": raw_digest,
                    "semantic_sha256": semantic_digest,
                }
            )

        oid_length = 40 if object_format == "sha1" else 64
        for path, items in index_entries.items():
            if any(len(item[1]) != oid_length for item in items):
                raise _error(
                    "GIT_OUTPUT_INVALID",
                    "Git index object ID does not match the repository object format",
                    path=path,
                    object_format=object_format,
                )
        head = cls._decode_text(initial["head"], ("rev-parse", "HEAD"))
        if len(head) != oid_length or not _OBJECT_ID.fullmatch(head):
            raise _error("GIT_OUTPUT_INVALID", "Git HEAD object ID is invalid")
        branch = (
            cls._decode_text(initial["branch"], ("symbolic-ref", "HEAD"))
            if initial["branch"] is not None
            else None
        )
        git_common = cls._decode_text(initial["git_common"], ("git-common-dir",))
        git_common_path = canonical_git_path(git_common, repository_root=root)
        git_worktree = cls._decode_text(initial["git_worktree"], ("git-dir",))
        git_worktree_path = canonical_git_path(git_worktree, repository_root=root)
        index_entry_count = sum(len(items) for items in index_entries.values())
        status = initial["status"]
        base = {
            "schema": WORKSPACE_SNAPSHOT_SCHEMA,
            "repository_root": str(root),
            "git_worktree_dir": str(git_worktree_path),
            "git_common_dir": str(git_common_path),
            "object_format": object_format,
            "head": head,
            "branch": branch,
            "clean": not status,
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "status_bytes": len(status),
            "index_entry_count": index_entry_count,
            "index_output_bytes": len(initial_index),
            "has_unmerged_entries": any(
                item[2] != "0"
                for items in index_entries.values()
                for item in items
            ),
            "entries": entries,
            "resources": resource_entries,
        }
        return validate_snapshot({**base, "digest": _snapshot_digest(base)})
    @staticmethod
    def _blob_oid(raw: bytes, object_format: str) -> str:
        digest = hashlib.sha1() if object_format == "sha1" else hashlib.sha256()
        digest.update("blob {}\0".format(len(raw)).encode("ascii"))
        digest.update(raw)
        return digest.hexdigest()
