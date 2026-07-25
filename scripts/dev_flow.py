#!/usr/bin/env python3
"""A deterministic, local control plane for Codex development work.

The module intentionally depends only on Python's standard library.  Every
normal CLI response (including errors) is one JSON object on stdout so hooks
and skills do not need to scrape prose.
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import datetime as dt
import errno
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Iterator, Sequence

try:  # POSIX is the primary Codex environment; Windows uses msvcrt below.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows byte-range locking; absent on POSIX where fcntl is used instead.
    import msvcrt
except ImportError:  # pragma: no cover - exercised only on POSIX
    msvcrt = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
EVIDENCE_CONTRACT_VERSION = 1
TERMINAL_STATES = {"DONE", "CANCELLED"}
ORDERED_STATES = [
    "INTAKE",
    "PREFLIGHTED",
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
]
ALL_STATES = set(ORDERED_STATES) | {"BLOCKED", "CANCELLED"}
FORWARD_EDGES = {
    state: {ORDERED_STATES[index + 1]}
    for index, state in enumerate(ORDERED_STATES[:-1])
}
FORWARD_EDGES["DONE"] = set()
REWORK_EDGES = {
    "IMPLEMENTING": {"PLANNING"},
    "VERIFYING": {"IMPLEMENTING", "PLANNING"},
    "REVIEWING": {"IMPLEMENTING", "PLANNING"},
    "FINALIZING": {"IMPLEMENTING", "PLANNING"},
}
IMPACT_REASSESS_SOURCES = {
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
}
for _reassess_source in IMPACT_REASSESS_SOURCES:
    REWORK_EDGES.setdefault(_reassess_source, set()).add("INDEXED")
FLOW_MODES = ("full", "lite")
DEFAULT_FLOW = "full"
FLOW_NAMES_ZH = {
    "full": "完整流程",
    "lite": "精简流程",
}
STATE_NAMES_ZH = {
    "INTAKE": "需求接收",
    "PREFLIGHTED": "预检完成",
    "BASELINED": "基线就绪",
    "INDEXED": "索引完成",
    "IMPACT_REVIEW": "影响评审",
    "ROUTE_APPROVED": "路线已批准",
    "WORKSPACE_READY": "工作区就绪",
    "PLANNING": "方案规划",
    "IMPLEMENTING": "实现中",
    "VERIFYING": "验证中",
    "REVIEWING": "独立审查",
    "FINALIZING": "交付确认",
    "DONE": "已完成",
    "BLOCKED": "已阻塞",
    "CANCELLED": "已取消",
}
FLOW_BY_WORKSPACE_STRATEGY = {
    "branch": "lite",
    "in-place": "lite",
    "worktree": "full",
}
WORKSPACE_STRATEGIES = tuple(FLOW_BY_WORKSPACE_STRATEGY)
WORKSPACE_STRATEGY_NAMES_ZH = {
    "branch": "新建并切换分支",
    "in-place": "使用当前分支",
    "worktree": "创建独立工作树",
}
LITE_GATE = "lite"
FULL_GATES = (
    "baseline-fetch",
    "impact-degraded",
    "route",
    "workspace",
    "plan",
    "review",
)
# One vocabulary shared by the argparse surface and the approve dispatch, so
# an unrecognized gate can never record an approval, consume a revision, or
# skip the status/flow assertions bound to each real gate.
APPROVAL_GATES = (*FULL_GATES, LITE_GATE)
# The lite flow works in place inside the user's own checkouts.  It keeps
# preflight evidence, one explicit human gate, and test-currency enforcement,
# and deliberately has no baseline, index, impact, route, managed workspace,
# plan, or independent-review machinery.
LITE_ORDERED_STATES = [
    "INTAKE",
    "PREFLIGHTED",
    "IMPLEMENTING",
    "VERIFYING",
    "DONE",
]
LITE_FORWARD_EDGES = {
    state: {LITE_ORDERED_STATES[index + 1]}
    for index, state in enumerate(LITE_ORDERED_STATES[:-1])
}
LITE_FORWARD_EDGES["DONE"] = set()
# Backward edges: rework the implementation, or re-open scope evidence with a
# fresh preflight when the checkout drifted or the fix outgrew its approval.
LITE_REWORK_EDGES = {
    "IMPLEMENTING": {"PREFLIGHTED"},
    "VERIFYING": {"IMPLEMENTING", "PREFLIGHTED"},
}
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WINDOWS_RESERVED_TASK_STEMS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PROTECTED_BRANCHES = ["main", "master", "trunk"]
REVIEW_VERDICTS = {"PASS", "CONDITIONAL", "FAIL"}
REVIEW_VERDICT_RE = re.compile(
    r"^Verdict: (PASS|CONDITIONAL|FAIL)$", re.MULTILINE
)
BASELINE_INDEX_STATES = {
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
}
WORKSPACE_INDEX_STATES = {
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
}
SCOPE_MODES = ("all", "allowlist")
SCOPE_INCLUDE_ENV = "DEV_FLOW_SCOPE"
SCOPE_EXCLUDE_ENV = "DEV_FLOW_SCOPE_EXCLUDE"
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.05
_FILESYSTEM_CASE_CACHE: dict[Any, bool] = {}
_FILESYSTEM_UNICODE_CACHE: dict[Any, bool] = {}
_HELD_LOCK_DIRECTORIES: contextvars.ContextVar[tuple[str, ...]] = (
    contextvars.ContextVar("dev_flow_held_lock_directories", default=())
)
_ACTIVE_MUTATION_INTENTS: contextvars.ContextVar[tuple[str, ...]] = (
    contextvars.ContextVar("dev_flow_active_mutation_intents", default=())
)


class FlowError(Exception):
    """A predictable user-facing error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise FlowError("INVALID_ARGUMENT", message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _nonempty(value: Any) -> str | None:
    """Return a stripped non-empty environment/argument value."""

    if value is None:
        return None
    text = os.fspath(value) if isinstance(value, os.PathLike) else str(value)
    text = text.strip()
    return text or None


def _platform_family() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve state storage using CLI, environment, then platform state dir.

    Resolution order is deliberately exposed for hooks: explicit ``data_dir``;
    ``DEV_FLOW_DATA_DIR``; ``PLUGIN_DATA``; finally the user's state directory.
    The returned path is absolute, but this function does not create it.
    """

    candidate = _nonempty(data_dir)
    if candidate is None:
        candidate = _nonempty(os.environ.get("DEV_FLOW_DATA_DIR"))
    if candidate is None:
        candidate = _nonempty(os.environ.get("PLUGIN_DATA"))
    if candidate is None:
        platform_family = _platform_family()
        if platform_family == "macos":
            candidate = str(
                Path.home()
                / "Library"
                / "Application Support"
                / "dev-flow-orchestrator"
            )
        elif platform_family == "windows":  # pragma: no cover - native Windows
            local_app_data = _nonempty(os.environ.get("LOCALAPPDATA"))
            root = (
                Path(local_app_data)
                if local_app_data is not None
                else Path.home() / "AppData" / "Local"
            )
            candidate = str(root / "dev-flow-orchestrator")
        else:
            xdg_state_home = _nonempty(os.environ.get("XDG_STATE_HOME"))
            root = (
                Path(xdg_state_home)
                if xdg_state_home is not None
                else Path.home() / ".local" / "state"
            )
            candidate = str(root / "dev-flow-orchestrator")
    return Path(candidate).expanduser().resolve(strict=False)


def _validate_task_id(task_id: str) -> str:
    encoded_length = len(task_id.encode("ascii", "ignore"))
    if (
        not task_id.isascii()
        or encoded_length != len(task_id)
        or not TASK_ID_RE.fullmatch(task_id)
        or task_id.endswith(".")
        or task_id.split(".", 1)[0].lower() in WINDOWS_RESERVED_TASK_STEMS
    ):
        raise FlowError(
            "INVALID_TASK_ID",
            (
                "task id must be 1-64 ASCII bytes matching "
                "[A-Za-z0-9][A-Za-z0-9._-]{0,63}, must not end in '.', and "
                "must not use a Windows reserved device-name stem"
            ),
            details={
                "task_id": task_id,
                "ascii_bytes": encoded_length if task_id.isascii() else None,
            },
        )
    return task_id


def _task_identity(task_id: str) -> str:
    return _validate_task_id(task_id).lower()


def _task_dir(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "tasks" / _validate_task_id(task_id)


def _state_path(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return _task_dir(task_id, data_dir) / "state.json"


def _nearest_existing_path(path: Path) -> tuple[Path, tuple[str, ...]]:
    """Return the nearest existing ancestor and the uncreated suffix."""

    suffix: list[str] = []
    current = path.expanduser()
    while not current.exists():
        if current.parent == current:
            raise FlowError(
                "PATH_IDENTITY_UNAVAILABLE",
                "path has no existing ancestor whose filesystem identity can be verified",
                details={"path": str(path)},
            )
        suffix.append(current.name)
        current = current.parent
    try:
        ancestor = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not resolve an existing path ancestor",
            details={"path": str(path), "ancestor": str(current), "error": str(exc)},
        ) from exc
    return ancestor, tuple(reversed(suffix))


def _windows_existing_identity(path: Path) -> dict[str, Any]:
    """Return volume/file identity plus a handle-canonical Windows path."""

    if os.name != "nt":  # pragma: no cover - native Windows helper
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "Windows file identity is unavailable on this platform",
            details={"path": str(path)},
        )
    import ctypes
    from ctypes import wintypes

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(
        str(path),
        0,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not open a Windows path for stable identity",
            details={
                "path": str(path),
                "winerror": ctypes.get_last_error(),
            },
        )
    try:
        information = BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(
            handle, ctypes.byref(information)
        ):
            raise FlowError(
                "PATH_IDENTITY_UNAVAILABLE",
                "could not read Windows volume/file identity",
                details={
                    "path": str(path),
                    "winerror": ctypes.get_last_error(),
                },
            )
        final_path: str | None = None
        for flags in (0x1, 0x0):  # volume GUID, then normalized DOS path
            required = kernel32.GetFinalPathNameByHandleW(
                handle, None, 0, flags
            )
            if not required:
                continue
            buffer = ctypes.create_unicode_buffer(required + 1)
            rendered = kernel32.GetFinalPathNameByHandleW(
                handle, buffer, len(buffer), flags
            )
            if rendered and rendered < len(buffer):
                final_path = buffer.value
                break
        if final_path is None:
            raise FlowError(
                "PATH_IDENTITY_UNAVAILABLE",
                "could not canonicalize a Windows path by handle",
                details={
                    "path": str(path),
                    "winerror": ctypes.get_last_error(),
                },
            )
        file_index = (
            int(information.nFileIndexHigh) << 32
        ) | int(information.nFileIndexLow)
        return {
            "kind": "windows-file-id",
            "volume_serial": int(
                information.dwVolumeSerialNumber
            ),
            "file_index": file_index,
            "final_path": final_path,
        }
    finally:
        kernel32.CloseHandle(handle)


def _stable_existing_identity(path: Path) -> dict[str, Any]:
    if os.name == "nt":  # pragma: no cover - native Windows
        return _windows_existing_identity(path)
    try:
        metadata = path.stat()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not read stable filesystem identity",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    return {
        "kind": "posix-file-id",
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "final_path": str(path.resolve(strict=True)),
    }


def _windows_directory_case_sensitive(path: Path) -> bool | None:
    if os.name != "nt":  # pragma: no cover - native Windows helper
        return None
    import ctypes
    from ctypes import wintypes

    class FILE_CASE_SENSITIVE_INFORMATION(ctypes.Structure):
        _fields_ = [("Flags", wintypes.ULONG)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(
        str(path),
        0,
        0x00000001 | 0x00000002 | 0x00000004,
        None,
        3,
        0x02000000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not open a Windows directory for case-sensitivity identity",
            details={
                "path": str(path),
                "winerror": ctypes.get_last_error(),
            },
        )
    try:
        information = FILE_CASE_SENSITIVE_INFORMATION()
        if kernel32.GetFileInformationByHandleEx(
            handle,
            23,  # FileCaseSensitiveInfo
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            return bool(information.Flags & 0x1)
        error = ctypes.get_last_error()
        if error in {1, 50, 87, 120}:
            return None
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not query Windows per-directory case sensitivity",
            details={"path": str(path), "winerror": error},
        )
    finally:
        kernel32.CloseHandle(handle)


def _probe_filesystem_case_sensitive(existing: Path) -> bool:
    """Probe case behavior on the same filesystem and clean up unconditionally."""

    probe_parent = existing if existing.is_dir() else existing.parent
    stable = _stable_existing_identity(probe_parent)
    if os.name == "nt":  # pragma: no cover - native Windows
        native = _windows_directory_case_sensitive(probe_parent)
        if native is not None:
            return native
        cache_key: Any = (
            "windows-directory",
            stable.get("volume_serial"),
            stable.get("file_index"),
        )
    else:
        cache_key = ("posix-device", stable.get("device"))
    cached = _FILESYSTEM_CASE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    probe_dir: Path | None = None
    try:
        probe_dir = Path(
            tempfile.mkdtemp(prefix=".dev-flow-case-", dir=str(probe_parent))
        )
        mixed = probe_dir / "CaseProbe"
        alternate = probe_dir / "caseprobe"
        mixed.write_bytes(b"case")
        case_sensitive = not alternate.exists()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not verify filesystem case behavior",
            details={"path": str(probe_parent), "error": str(exc)},
        ) from exc
    finally:
        if probe_dir is not None:
            try:
                shutil.rmtree(probe_dir)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "PATH_IDENTITY_UNAVAILABLE",
                    "filesystem case probe could not be cleaned up safely",
                    details={"path": str(probe_dir), "error": str(exc)},
                ) from exc
    _FILESYSTEM_CASE_CACHE[cache_key] = case_sensitive
    return case_sensitive


def _probe_filesystem_unicode_distinct(existing: Path) -> bool:
    probe_parent = existing if existing.is_dir() else existing.parent
    stable = _stable_existing_identity(probe_parent)
    cache_key: Any = (
        "windows-volume",
        stable.get("volume_serial"),
    ) if os.name == "nt" else (
        "posix-device",
        stable.get("device"),
    )
    cached = _FILESYSTEM_UNICODE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    probe_dir: Path | None = None
    try:
        probe_dir = Path(
            tempfile.mkdtemp(prefix=".dev-flow-unicode-", dir=str(probe_parent))
        )
        composed = probe_dir / "\u00e9"
        decomposed = probe_dir / "e\u0301"
        composed.write_bytes(b"unicode")
        distinct = not decomposed.exists()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not verify filesystem Unicode normalization behavior",
            details={"path": str(probe_parent), "error": str(exc)},
        ) from exc
    finally:
        if probe_dir is not None:
            try:
                shutil.rmtree(probe_dir)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "PATH_IDENTITY_UNAVAILABLE",
                    "filesystem Unicode probe could not be cleaned up safely",
                    details={"path": str(probe_dir), "error": str(exc)},
                ) from exc
    _FILESYSTEM_UNICODE_CACHE[cache_key] = distinct
    return distinct


def _filesystem_identity(path: Path) -> dict[str, Any]:
    """Return a canonical identity for existing and planned filesystem paths."""

    try:
        supplied = Path(
            os.path.abspath(os.fspath(path.expanduser()))
        )
    except (OSError, TypeError, ValueError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "path spelling could not be normalized safely",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    ancestor, suffix = _nearest_existing_path(supplied)
    stable_ancestor = _stable_existing_identity(ancestor)
    case_sensitive = _probe_filesystem_case_sensitive(ancestor)
    unicode_distinct = _probe_filesystem_unicode_distinct(ancestor)

    def normalize(value: str) -> str:
        return (
            value
            if unicode_distinct
            else unicodedata.normalize("NFC", value)
        )

    display = ancestor.joinpath(*suffix)
    canonical_ancestor = Path(
        str(stable_ancestor.get("final_path") or ancestor)
    )
    canonical_display = canonical_ancestor.joinpath(*suffix)
    normalized = normalize(
        os.path.normpath(str(canonical_display))
    )
    if not case_sensitive:
        normalized = normalized.casefold()
    try:
        anchor = canonical_ancestor.anchor or str(
            canonical_ancestor
        )
        relative = canonical_ancestor.relative_to(anchor)
        anchor_normalized = normalize(str(anchor))
        relative_parts = tuple(
            normalize(part) for part in relative.parts
        )
    except (TypeError, ValueError):
        anchor_normalized = normalize(canonical_ancestor.anchor)
        relative_parts = tuple(
            normalize(part) for part in canonical_ancestor.parts
        )
    suffix_parts = tuple(normalize(part) for part in suffix)
    identity_parts = relative_parts + suffix_parts
    if not case_sensitive:
        anchor_normalized = anchor_normalized.casefold()
        identity_parts = tuple(part.casefold() for part in identity_parts)
    return {
        "path": str(display),
        "normalized": normalized,
        "anchor": anchor_normalized,
        "parts": identity_parts,
        "case_sensitive": case_sensitive,
        "unicode_normalization_distinct": unicode_distinct,
        "ancestor": str(ancestor),
        "ancestor_identity": {
            key: value
            for key, value in stable_ancestor.items()
            if key != "final_path"
        },
        "suffix_parts": suffix_parts,
    }


def _same_path(left: Path, right: Path) -> bool:
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            pass
    left_identity = _filesystem_identity(left)
    right_identity = _filesystem_identity(right)
    same_ancestor = (
        left_identity.get("ancestor_identity")
        == right_identity.get("ancestor_identity")
        and left_identity.get("suffix_parts")
        == right_identity.get("suffix_parts")
    )
    return (
        (
            same_ancestor
            or left_identity.get("normalized")
            == right_identity.get("normalized")
            or (
                left_identity["anchor"]
                == right_identity["anchor"]
                and left_identity["parts"]
                == right_identity["parts"]
            )
        )
        and left_identity["case_sensitive"]
        == right_identity["case_sensitive"]
        and left_identity["unicode_normalization_distinct"]
        == right_identity["unicode_normalization_distinct"]
    )


def _serializable_path_identity(path: Path) -> dict[str, Any]:
    identity = _filesystem_identity(path)
    return {
        "normalized": identity["normalized"],
        "anchor": identity["anchor"],
        "parts": list(identity["parts"]),
        "case_sensitive": identity["case_sensitive"],
        "unicode_normalization_distinct": identity[
            "unicode_normalization_distinct"
        ],
        "ancestor_identity": identity.get("ancestor_identity"),
        "suffix_parts": list(identity.get("suffix_parts") or ()),
    }


def _capability_path_identity(path: Path) -> dict[str, Any]:
    """Return the location fields that stay stable across path creation.

    Stable file IDs intentionally change when a previously planned path is
    materialized: before creation they identify the nearest existing ancestor,
    while afterwards they identify the new directory itself.  Capability
    profiles need to bind the canonical location without treating that expected
    transition as capability drift.  Ownership checks continue to use the full
    serializable identity, including file IDs.
    """

    identity = _serializable_path_identity(path)
    return {
        "normalized": identity["normalized"],
        "anchor": identity["anchor"],
        "parts": identity["parts"],
        "case_sensitive": identity["case_sensitive"],
        "unicode_normalization_distinct": identity[
            "unicode_normalization_distinct"
        ],
    }


def _path_identity_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    modern_identity = (
        isinstance(left.get("ancestor_identity"), dict)
        and isinstance(right.get("ancestor_identity"), dict)
    )
    location_matches = (
        (
            isinstance(left.get("normalized"), str)
            and left.get("normalized") == right.get("normalized")
        )
        or (
            modern_identity
            and left.get("ancestor_identity")
            == right.get("ancestor_identity")
            and tuple(left.get("suffix_parts") or ())
            == tuple(right.get("suffix_parts") or ())
        )
        or (
            left.get("anchor") == right.get("anchor")
            and tuple(left.get("parts") or ())
            == tuple(right.get("parts") or ())
        )
    )
    return (
        location_matches
        and left.get("case_sensitive") == right.get("case_sensitive")
        and left.get("unicode_normalization_distinct")
        == right.get("unicode_normalization_distinct")
    )


def _recorded_path_matches(
    recorded_identity: Any, recorded_path: Any, candidate: Path
) -> bool:
    candidate_identity = _serializable_path_identity(candidate)
    if isinstance(recorded_identity, dict):
        return _path_identity_equal(recorded_identity, candidate_identity)
    if not recorded_path:
        return False
    return _same_path(Path(str(recorded_path)), candidate)


def _declared_evidence_versions(value: Any) -> Iterator[int]:
    if isinstance(value, dict):
        declared = value.get("evidence_contract_version")
        if declared is not None:
            if not isinstance(declared, int) or isinstance(declared, bool):
                raise FlowError(
                    "EVIDENCE_CONTRACT_INVALID",
                    "evidence contract versions must be integers",
                    details={"value": declared},
                )
            yield declared
        for key, nested in value.items():
            # ``metadata`` is an explicit user/integration namespace.  A
            # third-party payload may legitimately describe its own evidence
            # contract and must never be mistaken for this controller's
            # durable evidence version.
            if key == "metadata":
                continue
            yield from _declared_evidence_versions(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _declared_evidence_versions(nested)


def _assert_supported_evidence_versions(value: Any) -> None:
    newer = sorted(
        {
            version
            for version in _declared_evidence_versions(value)
            if version > EVIDENCE_CONTRACT_VERSION
        }
    )
    if newer:
        raise FlowError(
            "EVIDENCE_CONTRACT_UNSUPPORTED",
            "task evidence was created by a newer incompatible controller",
            details={
                "supported_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_versions": newer,
            },
        )


def _require_current_evidence(record: Any, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            f"{label} evidence is missing and must be regenerated",
            details={"label": label, "required_version": EVIDENCE_CONTRACT_VERSION},
        )
    version = record.get("evidence_contract_version")
    if version != EVIDENCE_CONTRACT_VERSION:
        if isinstance(version, int) and version > EVIDENCE_CONTRACT_VERSION:
            raise FlowError(
                "EVIDENCE_CONTRACT_UNSUPPORTED",
                f"{label} evidence uses a newer incompatible contract",
                details={
                    "label": label,
                    "supported_version": EVIDENCE_CONTRACT_VERSION,
                    "encountered_version": version,
                },
            )
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            f"legacy {label} evidence must be regenerated by the current controller",
            details={
                "label": label,
                "required_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_version": version,
            },
        )
    return record


def load_state(
    task_id: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load a task snapshot by id, or load an explicit ``state.json`` path."""

    supplied = Path(task_id)
    if supplied.name == "state.json" or supplied.is_file():
        path = supplied.expanduser().resolve(strict=False)
    else:
        path = _state_path(str(task_id), data_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise FlowError(
            "TASK_NOT_FOUND",
            f"task state does not exist: {path}",
            details={"path": str(path)},
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowError(
            "STATE_READ_FAILED",
            f"could not read task state: {path}",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise FlowError(
            "UNSUPPORTED_STATE",
            f"unsupported or invalid task state: {path}",
            details={"path": str(path), "schema_version": value.get("schema_version") if isinstance(value, dict) else None},
        )
    stored_task_id = value.get("task_id")
    if not isinstance(stored_task_id, str):
        raise FlowError(
            "UNSUPPORTED_STATE",
            f"task state does not contain a valid task identifier: {path}",
            details={"path": str(path), "task_id": stored_task_id},
        )
    _validate_task_id(stored_task_id)
    _assert_supported_evidence_versions(value)
    # Schema v1 predates implementation-worktree indexes.  Keep the schema
    # number stable and make the additive field visible to old task snapshots
    # without rewriting them merely because they were read.
    for repository in value.get("repositories", []):
        if isinstance(repository, dict):
            repository.setdefault("workspace_index", None)
            repository.setdefault("index_history", [])
    # Tasks recorded before flow selection are full-flow tasks by definition.
    value.setdefault("flow", DEFAULT_FLOW)
    return value


def _is_within(path: Path, parent: Path) -> bool:
    path_identity = _filesystem_identity(path)
    parent_identity = _filesystem_identity(parent)

    def stable_id(identity: dict[str, Any]) -> dict[str, Any] | None:
        value = identity.get("ancestor_identity")
        return value if isinstance(value, dict) else None

    path_ancestor_id = stable_id(path_identity)
    parent_ancestor_id = stable_id(parent_identity)
    if (
        path_ancestor_id is not None
        and path_ancestor_id == parent_ancestor_id
    ):
        parent_suffix = tuple(
            parent_identity.get("suffix_parts") or ()
        )
        path_suffix = tuple(
            path_identity.get("suffix_parts") or ()
        )
        return (
            path_suffix[: len(parent_suffix)] == parent_suffix
        )

    # Existing descendants can cross a mapped-drive/UNC, symlink/junction, or
    # per-directory case-sensitivity boundary.  Textual anchors and capability
    # flags are not sufficient there, so walk the existing ancestor chain and
    # compare stable volume/file identities.  A non-existing parent is handled
    # by the common-ancestor/suffix rule above.
    if (
        parent_ancestor_id is not None
        and not tuple(parent_identity.get("suffix_parts") or ())
    ):
        candidate = Path(str(path_identity.get("ancestor") or ""))
        while candidate:
            try:
                candidate_stable = _stable_existing_identity(candidate)
            except FlowError:
                break
            candidate_id = {
                key: value
                for key, value in candidate_stable.items()
                if key != "final_path"
            }
            if candidate_id == parent_ancestor_id:
                return True
            if candidate.parent == candidate:
                break
            candidate = candidate.parent

    if (
        path_identity["case_sensitive"]
        != parent_identity["case_sensitive"]
        or path_identity["unicode_normalization_distinct"]
        != parent_identity["unicode_normalization_distinct"]
    ):
        return False
    if path_identity["anchor"] != parent_identity["anchor"]:
        return False
    parent_parts = parent_identity["parts"]
    return path_identity["parts"][: len(parent_parts)] == parent_parts


def find_active_task_for_cwd(
    cwd: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Return the newest non-terminal task whose repo/workspace contains cwd."""

    current = Path(cwd or os.getcwd()).expanduser().resolve(strict=False)
    tasks_dir = resolve_data_dir(data_dir) / "tasks"
    if not tasks_dir.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for state_file in tasks_dir.glob("*/state.json"):
        try:
            state_value = load_state(state_file)
        except FlowError:
            continue
        if state_value.get("status") in TERMINAL_STATES:
            continue
        for repo in state_value.get("repositories", []):
            candidates = [repo.get("path"), repo.get("canonical_path")]
            workspace = repo.get("workspace")
            if isinstance(workspace, dict):
                candidates.append(workspace.get("path"))
            analysis_workspace = repo.get("analysis_workspace")
            if isinstance(analysis_workspace, dict):
                candidates.append(analysis_workspace.get("path"))
            if any(
                item and _is_within(current, Path(item).expanduser().resolve(strict=False))
                for item in candidates
            ):
                matches.append(state_value)
                break
    if not matches:
        return None
    return max(matches, key=lambda value: (str(value.get("updated_at", "")), int(value.get("revision", 0))))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _windows_security_descriptor(path: Path) -> dict[str, Any]:
    """Read owner and DACL details through Win32 using only ``ctypes``."""

    if os.name != "nt":  # pragma: no cover - native Windows implementation
        raise FlowError(
            "PERMISSIONS_UNSUPPORTED",
            "Windows security descriptors are unavailable on this platform",
            details={"path": str(path)},
        )
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    class ACL_HEADER(ctypes.Structure):
        _fields_ = [
            ("AclRevision", ctypes.c_ubyte),
            ("Sbz1", ctypes.c_ubyte),
            ("AclSize", ctypes.c_ushort),
            ("AceCount", ctypes.c_ushort),
            ("Sbz2", ctypes.c_ushort),
        ]

    class ACE_HEADER(ctypes.Structure):
        _fields_ = [
            ("AceType", ctypes.c_ubyte),
            ("AceFlags", ctypes.c_ubyte),
            ("AceSize", ctypes.c_ushort),
        ]

    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def sid_string(sid: ctypes.c_void_p) -> str:
        rendered = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(rendered)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(rendered.value)
        finally:
            kernel32.LocalFree(
                ctypes.cast(rendered, ctypes.c_void_p)
            )

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(
            token, 1, None, 0, ctypes.byref(required)
        )
        if required.value <= 0:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        current_sid = sid_string(
            ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents.User.Sid
        )
    finally:
        kernel32.CloseHandle(token)

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,  # SE_FILE_OBJECT
        0x00000001 | 0x00000004,  # OWNER_SECURITY_INFORMATION | DACL
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        raise OSError(result, f"GetNamedSecurityInfoW failed for {path}")
    try:
        if not owner.value or not dacl.value:
            return {
                "owner": sid_string(owner) if owner.value else None,
                "current_user": current_sid,
                "null_dacl": not bool(dacl.value),
                "aces": [],
            }
        acl_header = ACL_HEADER.from_address(dacl.value)
        aces: list[dict[str, Any]] = []
        for index in range(int(acl_header.AceCount)):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise ctypes.WinError(ctypes.get_last_error())
            header = ACE_HEADER.from_address(ace_pointer.value)
            # File DACLs should use ordinary allowed/denied ACEs. Object ACEs
            # have variable SID offsets; treating them as unverifiable keeps
            # the controller fail closed instead of guessing.
            if header.AceType not in {0, 1}:
                aces.append(
                    {
                        "type": int(header.AceType),
                        "sid": None,
                        "mask": None,
                        "inherited": bool(header.AceFlags & 0x10),
                        "unverifiable": True,
                    }
                )
                continue
            mask = ctypes.c_uint32.from_address(ace_pointer.value + 4).value
            sid = sid_string(ctypes.c_void_p(ace_pointer.value + 8))
            aces.append(
                {
                    "type": "allow" if header.AceType == 0 else "deny",
                    "sid": sid,
                    "mask": int(mask),
                    "inherited": bool(header.AceFlags & 0x10),
                    "unverifiable": False,
                }
            )
        return {
            "owner": sid_string(owner),
            "current_user": current_sid,
            "null_dacl": False,
            "aces": aces,
        }
    finally:
        kernel32.LocalFree(descriptor)


def _verify_windows_private_path(path: Path) -> None:
    try:
        descriptor = _windows_security_descriptor(path)
    except (OSError, ValueError) as exc:
        raise FlowError(
            "PERMISSIONS_UNVERIFIABLE",
            "could not verify the Windows owner and DACL",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    owner = descriptor.get("owner")
    current_user = descriptor.get("current_user")
    trusted_owners = {current_user, "S-1-5-18", "S-1-5-32-544"}
    if descriptor.get("null_dacl") or not owner or owner not in trusted_owners:
        raise FlowError(
            "PERMISSIONS_UNSAFE",
            "controller-managed Windows storage has an unsafe owner or null DACL",
            details={"path": str(path), "owner": owner, "null_dacl": True},
        )
    forbidden = {
        "S-1-1-0",  # Everyone
        "S-1-5-7",  # Anonymous Logon
        "S-1-5-11",  # Authenticated Users
        "S-1-5-32-545",  # BUILTIN\Users
    }
    write_mask = (
        0x40000000  # GENERIC_WRITE
        | 0x10000000  # GENERIC_ALL
        | 0x00010000  # DELETE
        | 0x00040000  # WRITE_DAC
        | 0x00080000  # WRITE_OWNER
        | 0x00000002  # FILE_ADD_FILE / FILE_WRITE_DATA
        | 0x00000004  # FILE_ADD_SUBDIRECTORY / FILE_APPEND_DATA
        | 0x00000010  # FILE_WRITE_EA
        | 0x00000040  # FILE_DELETE_CHILD
        | 0x00000100  # FILE_WRITE_ATTRIBUTES
    )
    current_user_write = False
    for ace in descriptor.get("aces", []):
        if ace.get("unverifiable"):
            raise FlowError(
                "PERMISSIONS_UNVERIFIABLE",
                "controller-managed Windows storage has an unsupported ACE",
                details={"path": str(path), "ace": ace},
            )
        if ace.get("type") != "allow":
            continue
        mask = int(ace.get("mask") or 0)
        sid = ace.get("sid")
        if sid in forbidden and mask & write_mask:
            raise FlowError(
                "PERMISSIONS_UNSAFE",
                "controller-managed Windows storage grants broad write access",
                details={"path": str(path), "sid": sid, "mask": mask},
            )
        if sid == current_user and mask & write_mask and not ace.get("inherited"):
            current_user_write = True
    if owner != current_user and not current_user_write:
        raise FlowError(
            "PERMISSIONS_UNSAFE",
            "trusted-system-owned Windows storage lacks an explicit current-user write grant",
            details={"path": str(path), "owner": owner},
        )


def _set_private_permissions(path: Path, mode: int) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on native Windows
        _verify_windows_private_path(path)
        return
    try:
        path.chmod(mode)
        actual = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise FlowError(
            "PERMISSIONS_UNVERIFIABLE",
            "could not apply private controller storage permissions",
            details={"path": str(path), "mode": oct(mode), "error": str(exc)},
        ) from exc
    if actual != mode:
        raise FlowError(
            "PERMISSIONS_UNSAFE",
            "controller-managed storage permissions are broader than required",
            details={"path": str(path), "expected": oct(mode), "actual": oct(actual)},
        )


def _ensure_private_dir(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise FlowError(
                "PERMISSIONS_UNVERIFIABLE",
                "could not create private controller storage",
                details={"path": str(directory), "error": str(exc)},
            ) from exc
        _set_private_permissions(directory, 0o700)
    if not path.is_dir():
        raise FlowError(
            "PERMISSIONS_UNVERIFIABLE",
            "controller storage directory path is not a directory",
            details={"path": str(path)},
        )
    _set_private_permissions(path, 0o700)


_ROLLBACK_MARKER = ".rollback-"
_ROLLBACK_RECOVERY_COMMAND = "recover-atomic-write"


def _rollback_evidence_destination(candidate: Path) -> Path | None:
    """Map `.NAME.rollback-XXXX` back to the NAME it was captured for."""

    name = candidate.name
    if not name.startswith("."):
        return None
    destination, marker, _ = name[1:].rpartition(_ROLLBACK_MARKER)
    if not marker or not destination:
        return None
    return candidate.parent / destination


def _rollback_evidence_for(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f".{path.name}{_ROLLBACK_MARKER}*"))


def _atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    _ensure_private_dir(path.parent)
    rollback_prefix = f".{path.name}{_ROLLBACK_MARKER}"
    unresolved = _rollback_evidence_for(path)
    if unresolved:
        raise FlowError(
            "ATOMIC_RECOVERY_REQUIRED",
            "a prior atomic replacement left rollback evidence",
            details={
                "path": str(path),
                "rollback_candidates": [
                    str(candidate) for candidate in unresolved
                ],
                "recovery_command": _ROLLBACK_RECOVERY_COMMAND,
            },
        )

    def fsync_parent() -> None:
        if os.name == "nt":
            return
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    rollback_descriptor = -1
    rollback: Path | None = None
    original_existed = path.exists()
    try:
        rollback_descriptor, rollback_name = tempfile.mkstemp(
            prefix=rollback_prefix, dir=path.parent
        )
        rollback = Path(rollback_name)
        if os.name != "nt":
            os.fchmod(rollback_descriptor, mode)
        else:  # pragma: no cover - native Windows
            _verify_windows_private_path(rollback)
        with os.fdopen(rollback_descriptor, "wb") as rollback_handle:
            rollback_descriptor = -1
            if original_existed:
                try:
                    with path.open("rb") as original:
                        shutil.copyfileobj(original, rollback_handle)
                except OSError as exc:
                    raise FlowError(
                        "ATOMIC_WRITE_FAILED",
                        "could not preserve the prior committed file",
                        details={
                            "path": str(path),
                            "rollback": str(rollback),
                            "phase": "backup",
                            "error": str(exc),
                        },
                    ) from exc
            rollback_handle.flush()
            os.fsync(rollback_handle.fileno())
        _set_private_permissions(rollback, mode)
        if (
            original_existed
            and _sha256_file(rollback) != _sha256_file(path)
        ):
            raise FlowError(
                "ATOMIC_WRITE_FAILED",
                "prior committed file changed while rollback evidence was captured",
                details={
                    "path": str(path),
                    "rollback": str(rollback),
                    "phase": "backup",
                },
            )
    except BaseException:
        if rollback_descriptor >= 0:
            try:
                os.close(rollback_descriptor)
            except OSError:
                pass
        if rollback is not None:
            try:
                rollback.unlink()
            except OSError:
                pass
        raise

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        if rollback is not None:
            try:
                rollback.unlink()
            except OSError:
                pass
        raise FlowError(
            "ATOMIC_WRITE_FAILED",
            "could not create a same-directory temporary state file",
            details={"path": str(path), "error": str(exc), "phase": "create"},
        ) from exc
    temporary = Path(temporary_name)
    replaced = False
    restored = False
    recovery_uncertain = False
    try:
        if os.name != "nt":
            try:
                os.fchmod(descriptor, mode)
            except OSError as exc:
                raise FlowError(
                    "PERMISSIONS_UNVERIFIABLE",
                    "could not apply private permissions to a temporary state file",
                    details={"path": str(temporary), "mode": oct(mode), "error": str(exc)},
                ) from exc
        else:  # pragma: no cover - native Windows
            _verify_windows_private_path(temporary)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
            replaced = True
        except OSError as exc:
            raise FlowError(
                "ATOMIC_WRITE_FAILED",
                "atomic state replacement failed; the previous file was preserved",
                details={"path": str(path), "error": str(exc), "phase": "replace"},
            ) from exc
        try:
            _set_private_permissions(path, mode)
            fsync_parent()
        except (FlowError, OSError) as post_error:
            try:
                if original_existed:
                    if rollback is None:
                        raise OSError(
                            errno.ENOENT,
                            "rollback evidence is unavailable",
                        )
                    os.replace(rollback, path)
                    rollback = None
                    _set_private_permissions(path, mode)
                else:
                    path.unlink()
                fsync_parent()
                restored = True
            except (FlowError, OSError) as restore_error:
                recovery_uncertain = True
                raise FlowError(
                    "ATOMIC_RECOVERY_UNCERTAIN",
                    (
                        "replacement post-check failed and the previous "
                        "destination could not be restored safely"
                    ),
                    details={
                        "path": str(path),
                        "rollback": (
                            str(rollback) if rollback else None
                        ),
                        "committed": True,
                        "post_error": str(post_error),
                        "restore_error": str(restore_error),
                    },
                ) from restore_error
            raise FlowError(
                "ATOMIC_POSTCHECK_FAILED",
                (
                    "replacement post-check failed; the previously "
                    "committed destination was restored"
                ),
                details={
                    "path": str(path),
                    "committed": False,
                    "restored": True,
                    "error": str(post_error),
                },
            ) from post_error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            if not replaced:
                raise FlowError(
                    "ATOMIC_CLEANUP_FAILED",
                    "an uncommitted temporary state file could not be removed",
                    details={"path": str(temporary), "error": str(exc)},
                ) from exc
        if rollback is not None and not recovery_uncertain:
            try:
                rollback.unlink()
                rollback = None
                if replaced and not restored:
                    fsync_parent()
            except OSError as exc:
                if replaced and not restored:
                    raise FlowError(
                        "ATOMIC_COMMIT_UNCERTAIN",
                        (
                            "replacement committed but rollback-evidence "
                            "cleanup could not be proven durable"
                        ),
                        details={
                            "path": str(path),
                            "rollback": str(rollback),
                            "committed": True,
                            "error": str(exc),
                        },
                    ) from exc


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, _json_bytes(value))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8", "backslashreplace"
    )


def _protocol_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8", "backslashreplace")


def _write_protocol_response(value: Any) -> None:
    payload = _protocol_json_bytes(value)
    binary = getattr(sys.stdout, "buffer", None)
    if binary is not None:
        binary.write(payload)
        binary.flush()
    else:
        sys.stdout.write(payload.decode("utf-8"))
        sys.stdout.flush()


def _append_event(path: Path, event: dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    if path.exists():
        _set_private_permissions(path, 0o600)
    payload = (
        json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8", "backslashreplace")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        else:  # pragma: no cover - exercised on native Windows
            _verify_windows_private_path(path)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _set_private_permissions(path, 0o600)


def _quarantine_path(directory: Path) -> Path:
    return directory / "mutation-quarantine.json"


def _read_quarantine(directory: Path) -> dict[str, Any] | None:
    path = _quarantine_path(directory)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "mutation quarantine evidence is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("ready") is not False:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "mutation quarantine evidence is invalid",
            details={"path": str(path)},
        )
    return value


def _assert_no_mutation_quarantine(directory: Path) -> None:
    quarantine = _read_quarantine(directory)
    if quarantine is not None:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "a prior mutating child was not proven quiescent",
            details={
                "path": str(_quarantine_path(directory)),
                "pid": quarantine.get("pid"),
                "command": quarantine.get("command"),
                "recovery": (
                    "prove the recorded child is gone and validate partial "
                    "Git/filesystem postconditions before recovery"
                ),
            },
        )


def _held_task_directory() -> Path | None:
    held = [Path(value) for value in _HELD_LOCK_DIRECTORIES.get()]
    return next(
        (
            candidate
            for candidate in held
            if (candidate / "state.json").is_file()
        ),
        None,
    )


def _begin_mutation_intent(command: Sequence[str]) -> Path | None:
    """Durably announce a mutating child before it is allowed to start."""

    directory = _held_task_directory()
    if directory is None:
        return None
    path = _quarantine_path(directory)
    active = set(_ACTIVE_MUTATION_INTENTS.get())
    if str(path) in active:
        evidence = _read_quarantine(directory)
        if evidence is None:
            raise FlowError(
                "MUTATION_INTENT_LOST",
                "active mutation intent disappeared before state commit",
                details={"path": str(path)},
            )
        operations = list(evidence.get("operations") or [])
        operations.append(
            {
                "command": list(command),
                "announced_at": utc_now(),
                "phase": "spawn_pending",
                "gate_protocol_version": 1,
                "target_release_authorized": False,
                "containment_kind": (
                    "windows_job_kill_on_close"
                    if os.name == "nt"
                    else "posix_process_group"
                ),
                "containment_established": False,
            }
        )
        evidence["operations"] = operations
        evidence["command"] = list(command)
        evidence["phase"] = "spawn_pending"
        evidence["pid"] = None
        evidence["process_group"] = None
        evidence["gate_protocol_version"] = 1
        evidence["target_release_authorized"] = False
        evidence["containment_kind"] = (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        )
        evidence["containment_established"] = False
        _atomic_write_json(path, evidence)
        return path
    if path.exists():
        raise FlowError(
            "MUTATION_QUARANTINED",
            "a prior mutation intent remains active",
            details={"path": str(path)},
        )
    state_revision: int | None = None
    try:
        state_value = json.loads(
            (directory / "state.json").read_text(encoding="utf-8")
        )
        if isinstance(state_value, dict):
            state_revision = int(state_value.get("revision", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    announced_at = utc_now()
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": False,
        "recovery_id": str(uuid.uuid4()),
        "created_at": announced_at,
        "updated_at": announced_at,
        "phase": "spawn_pending",
        "pid": None,
        "process_group": None,
        "gate_protocol_version": 1,
        "target_release_authorized": False,
        "containment_kind": (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        ),
        "containment_established": False,
        "command": list(command),
        "operations": [
            {
                "command": list(command),
                "announced_at": announced_at,
                "phase": "spawn_pending",
                "gate_protocol_version": 1,
                "target_release_authorized": False,
                "containment_kind": (
                    "windows_job_kill_on_close"
                    if os.name == "nt"
                    else "posix_process_group"
                ),
                "containment_established": False,
            }
        ],
        "platform": _platform_family(),
        "state_revision": state_revision,
        "expected_committed_revision": (
            state_revision + 1
            if isinstance(state_revision, int)
            else None
        ),
        "cause": None,
        "required_recovery": [
            "prove_child_quiescent",
            "validate_partial_git_and_filesystem_postconditions",
        ],
    }
    # This write is deliberately before Popen.  If it cannot be committed,
    # the target process is never started.
    _atomic_write_json(path, evidence)
    _ACTIVE_MUTATION_INTENTS.set(
        (*_ACTIVE_MUTATION_INTENTS.get(), str(path))
    )
    return path


def _update_mutation_intent(
    path: Path | None,
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    phase: str,
    cause: BaseException | None = None,
    target_release_authorized: bool | None = None,
) -> None:
    if path is None:
        return
    directory = path.parent
    evidence = _read_quarantine(directory)
    if evidence is None:
        raise FlowError(
            "MUTATION_INTENT_LOST",
            "mutation intent disappeared while its child was active",
            details={"path": str(path), "pid": process.pid},
        )
    evidence.update(
        {
            "updated_at": utc_now(),
            "phase": phase,
            "pid": process.pid,
            "process_group": (
                process.pid if os.name != "nt" else None
            ),
            "command": list(command),
            "cause": (
                f"{type(cause).__name__}: {cause}"
                if cause is not None
                else None
            ),
        }
    )
    if target_release_authorized is not None:
        evidence["target_release_authorized"] = (
            target_release_authorized
        )
    if phase == "child_owned":
        evidence["containment_established"] = True
    operations = list(evidence.get("operations") or [])
    if operations:
        operations[-1] = {
            **operations[-1],
            "phase": phase,
            "pid": process.pid,
            "updated_at": evidence["updated_at"],
        }
        if target_release_authorized is not None:
            operations[-1]["target_release_authorized"] = (
                target_release_authorized
            )
        if phase == "child_owned":
            operations[-1]["containment_established"] = True
    evidence["operations"] = operations
    _atomic_write_json(path, evidence)


def _forget_active_mutation_intents(directory: Path) -> None:
    prefix = str(_quarantine_path(directory))
    _ACTIVE_MUTATION_INTENTS.set(
        tuple(
            item
            for item in _ACTIVE_MUTATION_INTENTS.get()
            if item != prefix
        )
    )


def _complete_mutation_intent(
    task_dir: Path, committed_revision: int
) -> None:
    path = _quarantine_path(task_dir)
    if str(path) not in set(_ACTIVE_MUTATION_INTENTS.get()):
        return
    evidence = _read_quarantine(task_dir)
    if evidence is None:
        raise FlowError(
            "MUTATION_INTENT_LOST",
            "mutation committed but its durable intent disappeared",
            details={
                "path": str(path),
                "committed_revision": committed_revision,
            },
        )
    evidence.update(
        {
            "updated_at": utc_now(),
            "phase": "postconditions_committed",
            "committed_revision": committed_revision,
            "pid": None,
            "process_group": None,
        }
    )
    _atomic_write_json(path, evidence)
    try:
        path.unlink()
        if os.name != "nt":
            directory_fd = os.open(task_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        if not path.exists():
            try:
                evidence["phase"] = "clear_durability_uncertain"
                _atomic_write_json(path, evidence)
            except FlowError:
                pass
        raise FlowError(
            "MUTATION_COMMITTED_QUARANTINE",
            (
                "state committed but mutation-intent cleanup could not be "
                "proven durable; reload and recover before continuing"
            ),
            details={
                "path": str(path),
                "committed_revision": committed_revision,
                "error": str(exc),
            },
        ) from exc
    finally:
        _forget_active_mutation_intents(task_dir)


def _abandon_unstarted_mutation_intent(path: Path | None) -> None:
    """Withdraw only the newest intent when its real target never started.

    A single controller transition can perform several mutating Git commands
    before committing state (for example, one fetch or worktree creation per
    repository).  If a later target cannot start, earlier operations still
    require durable recovery evidence; removing the whole marker would lose
    that fact.
    """

    if path is None:
        return
    forget_active = False
    try:
        evidence = _read_quarantine(path.parent)
        if evidence is None:
            forget_active = True
            return
        operations = list(evidence.get("operations") or [])
        if len(operations) > 1:
            operations.pop()
            previous = operations[-1]
            evidence.update(
                {
                    "updated_at": utc_now(),
                    "operations": operations,
                    "command": list(previous.get("command") or []),
                    "phase": previous.get("phase") or "child_quiescent",
                    "pid": previous.get("pid"),
                    "process_group": (
                        previous.get("pid")
                        if os.name != "nt"
                        else None
                    ),
                    "gate_protocol_version": previous.get(
                        "gate_protocol_version"
                    ),
                    "target_release_authorized": bool(
                        previous.get("target_release_authorized")
                    ),
                    "containment_kind": previous.get(
                        "containment_kind"
                    ),
                    "containment_established": bool(
                        previous.get("containment_established")
                    ),
                    "cause": None,
                }
            )
            _atomic_write_json(path, evidence)
            return
        path.unlink()
        forget_active = True
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except FileNotFoundError:
        forget_active = True
    except OSError as exc:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "an unstarted mutation intent could not be cleared durably",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    finally:
        if forget_active:
            _forget_active_mutation_intents(path.parent)


def _persist_mutation_quarantine(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    error: BaseException,
) -> Path | None:
    directory = _held_task_directory()
    if directory is None:
        return None
    path = _quarantine_path(directory)
    try:
        if path.exists():
            _update_mutation_intent(
                path,
                process,
                command,
                phase="quiescence_unproven",
                cause=error,
            )
            return path
    except FlowError:
        # The pre-spawn marker is already durable.  Preserve it rather than
        # letting an update failure erase the only fail-closed evidence.
        if path.exists():
            return path
    state_revision: int | None = None
    state_path = directory / "state.json"
    try:
        state_value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(state_value, dict):
            state_revision = int(state_value.get("revision", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    evidence = {
        "schema_version": 1,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": False,
        "created_at": utc_now(),
        "pid": process.pid,
        "process_group": (
            process.pid if os.name != "nt" else None
        ),
        "containment_kind": (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        ),
        "containment_established": os.name != "nt",
        "command": list(command),
        "platform": _platform_family(),
        "state_revision": state_revision,
        "cause": f"{type(error).__name__}: {error}",
        "required_recovery": [
            "prove_child_quiescent",
            "validate_partial_git_and_filesystem_postconditions",
        ],
    }
    _atomic_write_json(path, evidence)
    return path


def _quarantined_process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise FlowError(
            "QUARANTINE_INVALID",
            "mutation quarantine does not contain a valid child process id",
            details={"pid": pid},
        )
    if os.name == "nt":  # pragma: no cover - exercised on native Windows
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x00100000, False, pid)
        if not process:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process is gone.
                return False
            if error == 5:  # Access denied proves a process still owns the id.
                return True
            raise FlowError(
                "QUARANTINE_PROCESS_UNVERIFIABLE",
                "could not determine whether the quarantined child still exists",
                details={"pid": pid, "winerror": error},
            )
        try:
            wait_result = int(kernel32.WaitForSingleObject(process, 0))
            if wait_result == 258:  # WAIT_TIMEOUT
                return True
            if wait_result == 0:  # WAIT_OBJECT_0
                return False
            raise FlowError(
                "QUARANTINE_PROCESS_UNVERIFIABLE",
                "could not wait on the quarantined child process",
                details={
                    "pid": pid,
                    "wait_result": wait_result,
                    "winerror": ctypes.get_last_error(),
                },
            )
        finally:
            kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise FlowError(
            "QUARANTINE_PROCESS_UNVERIFIABLE",
            "could not determine whether the quarantined child still exists",
            details={"pid": pid, "error": str(exc)},
        ) from exc
    return True


def _quarantine_processes_alive(quarantine: dict[str, Any]) -> bool:
    if (
        quarantine.get("gate_protocol_version") == 1
        and quarantine.get("phase") == "spawn_pending"
        and quarantine.get("pid") is None
        and quarantine.get("target_release_authorized") is False
        and quarantine.get("containment_established") is False
    ):
        # The only process that could have existed was the no-side-effect gate.
        # The controller lock can be reacquired only after its parent has
        # exited, which closes the gate pipe; without a durable release
        # authorization the real target could never have started.
        return False
    if quarantine.get("gate_protocol_version") == 1:
        expected_containment = (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        )
        if (
            quarantine.get("containment_kind")
            != expected_containment
            or quarantine.get("containment_established") is not True
        ):
            raise FlowError(
                "QUARANTINE_INVALID",
                "mutation quarantine lacks valid child-containment evidence",
                details={
                    "containment_kind": quarantine.get(
                        "containment_kind"
                    ),
                    "containment_established": quarantine.get(
                        "containment_established"
                    ),
                },
            )
    if (
        quarantine.get("pid") is None
        and quarantine.get("phase")
        in {"postconditions_committed", "clear_durability_uncertain"}
    ):
        return False
    process_group = quarantine.get("process_group")
    if os.name != "nt" and isinstance(process_group, int):
        return _posix_process_group_alive(process_group)
    return _quarantined_process_alive(quarantine.get("pid"))


def _validate_partial_workspace_plan(
    state_value: dict[str, Any], task_dir: Path
) -> list[dict[str, Any]]:
    controller_plan = (state_value.get("workspace") or {}).get("plan") or {}
    plan_path_value = controller_plan.get("path")
    if not plan_path_value:
        return []
    plan_path = Path(str(plan_path_value))
    try:
        evidence = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "QUARANTINE_POSTCONDITION_FAILED",
            "workspace plan cannot be read during quarantine recovery",
            details={"path": str(plan_path), "error": str(exc)},
        ) from exc
    _require_current_evidence(evidence, "workspace plan")
    if _sha256_file(plan_path) != controller_plan.get("sha256"):
        raise FlowError(
            "QUARANTINE_POSTCONDITION_FAILED",
            "workspace plan changed while a mutation was quarantined",
            details={"path": str(plan_path)},
        )
    by_id = {
        repo.get("id"): repo for repo in state_value.get("repositories", [])
    }
    checked: list[dict[str, Any]] = []
    data_root = task_dir.parent.parent
    for plan in evidence.get("repositories", []):
        repo = by_id.get(plan.get("repository_id"))
        if not repo:
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "workspace plan names an unknown repository",
                details={"repository_id": plan.get("repository_id")},
            )
        destination = Path(str(plan.get("path", ""))).resolve(strict=False)
        workspace = repo.get("workspace") or {}
        if workspace.get("ready") and _recorded_path_matches(
            workspace.get("path_identity"),
            workspace.get("path"),
            destination,
        ):
            checked.append(
                {
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "state": "recorded-ready",
                }
            )
            continue
        if not destination.exists():
            checked.append(
                {
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "state": "absent",
                }
            )
            continue
        source = Path(repo["path"]).resolve(strict=True)
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        branch = _git_optional(
            destination, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        head = _git_optional(destination, "rev-parse", "HEAD")
        status_available, status_porcelain = _status_porcelain(destination)
        entry = next(
            (
                item
                for item in _worktree_entries(source)
                if item.get("worktree")
                and _same_path(Path(item["worktree"]), destination)
            ),
            None,
        )
        if (
            not root
            or not _same_path(Path(root), destination)
            or not _same_path(
                _git_common_dir(destination), _git_common_dir(source)
            )
            or not _is_linked_worktree(destination)
            or branch != plan.get("branch")
            or head != plan.get("base_sha")
            or not status_available
            or bool(status_porcelain)
            or not entry
            or entry.get("branch") != plan.get("branch_ref")
            or entry.get("HEAD") != head
            or not _has_exact_workspace_claim(
                data_root,
                state_value,
                repo,
                destination,
                str(plan.get("branch")),
            )
        ):
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "partial workspace mutation does not satisfy the approved clean postconditions",
                details={
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "branch": branch,
                    "head": head,
                    "dirty": bool(status_porcelain),
                },
            )
        checked.append(
            {
                "repository_id": repo["id"],
                "path": str(destination),
                "state": "complete-unrecorded",
            }
        )
    return checked


def _validate_quarantine_postconditions(
    state_value: dict[str, Any],
    task_dir: Path,
    quarantine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    partial_analysis: list[dict[str, Any]] = []
    mutation_commands = [
        item.get("command")
        for item in (quarantine or {}).get("operations", [])
        if isinstance(item, dict)
        and isinstance(item.get("command"), list)
    ]
    if isinstance((quarantine or {}).get("command"), list):
        mutation_commands.append((quarantine or {})["command"])
    data_root = task_dir.parent.parent
    for repo in state_value.get("repositories", []):
        source = Path(repo["path"]).resolve(strict=True)
        canonical = _canonical_repo(str(source))
        if not _same_path(source, canonical):
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "repository root identity changed during the quarantined mutation",
                details={"repository_id": repo.get("id")},
            )
        operations = _operation_state(source)
        active = [name for name, value in operations.items() if value]
        if active:
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "repository still has an incomplete Git operation",
                details={
                    "repository_id": repo.get("id"),
                    "operations": active,
                },
            )
        baseline = repo.get("baseline")
        if isinstance(baseline, dict):
            _require_current_evidence(
                baseline, f"baseline:{repo.get('id')}"
            )
            source_profile = _git_capability_profile(source)
            if source_profile["sha256"] != baseline.get(
                "capability_profile_sha256"
            ):
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    "repository capability profile changed during the quarantined mutation",
                    details={"repository_id": repo.get("id")},
                )
        analysis = repo.get("analysis_workspace")
        if isinstance(analysis, dict) and analysis.get("ready"):
            error = _analysis_workspace_integrity_error(repo)
            if error:
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    error,
                    details={"repository_id": repo.get("id")},
                )
        else:
            candidate = (
                data_root
                / "analysis"
                / str(state_value.get("task_id"))
                / str(repo.get("id"))
            ).resolve(strict=False)
            if candidate.exists():
                matching_command = next(
                    (
                        command
                        for command in mutation_commands
                        if "worktree" in command
                        and "add" in command
                        and str(candidate) in command
                    ),
                    None,
                )
                expected_head = (
                    str(matching_command[-1])
                    if matching_command
                    else None
                )
                root = _git_optional(
                    candidate, "rev-parse", "--show-toplevel"
                )
                head = _git_optional(
                    candidate, "rev-parse", "HEAD"
                )
                branch = _git_optional(
                    candidate,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                )
                status_available, status_porcelain = (
                    _status_porcelain(candidate)
                )
                entry = next(
                    (
                        item
                        for item in _worktree_entries(source)
                        if item.get("worktree")
                        and _same_path(
                            Path(item["worktree"]), candidate
                        )
                    ),
                    None,
                )
                permissions_safe = True
                try:
                    if os.name == "nt":
                        _verify_windows_private_path(candidate)
                    else:
                        permissions_safe = (
                            stat.S_IMODE(candidate.stat().st_mode)
                            == 0o700
                        )
                except FlowError:
                    permissions_safe = False
                if (
                    expected_head is None
                    or not root
                    or not _same_path(Path(root), candidate)
                    or not _same_path(
                        _git_common_dir(candidate),
                        _git_common_dir(source),
                    )
                    or not _is_linked_worktree(candidate)
                    or head != expected_head
                    or branch is not None
                    or not status_available
                    or bool(status_porcelain)
                    or not entry
                    or entry.get("HEAD") != head
                    or "detached" not in entry
                    or not permissions_safe
                ):
                    raise FlowError(
                        "QUARANTINE_POSTCONDITION_FAILED",
                        (
                            "unrecorded analysis worktree does not match "
                            "the quarantined approved mutation"
                        ),
                        details={
                            "repository_id": repo.get("id"),
                            "path": str(candidate),
                            "expected_head": expected_head,
                            "actual_head": head,
                            "branch": branch,
                            "dirty": bool(status_porcelain),
                            "permissions_safe": permissions_safe,
                        },
                    )
                partial_analysis.append(
                    {
                        "repository_id": repo.get("id"),
                        "path": str(candidate),
                        "head_sha": head,
                        "state": "complete-unrecorded",
                    }
                )
        workspace = repo.get("workspace")
        if isinstance(workspace, dict) and workspace.get("ready"):
            error = _workspace_integrity_error(state_value, repo)
            if error:
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    error,
                    details={"repository_id": repo.get("id")},
                )
        repositories.append(
            {
                "repository_id": repo.get("id"),
                "source_path": str(source),
                "operations": operations,
            }
        )
    partial_workspaces = _validate_partial_workspace_plan(
        state_value, task_dir
    )
    return {
        "repositories": repositories,
        "partial_analysis_worktrees": partial_analysis,
        "partial_workspaces": partial_workspaces,
    }


def _acquire_exclusive(handle: Any, lock_path: Path) -> None:
    """Take an exclusive advisory lock on an open lock file.

    POSIX uses ``fcntl.lockf``; Windows uses ``msvcrt.locking`` over byte zero.
    Both release automatically when the process exits. Every unsupported or
    failed backend is a structured fail-closed error.
    """

    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            if fcntl is not None:
                fcntl.lockf(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                    1,
                    0,
                    os.SEEK_SET,
                )
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise FlowError(
                    "LOCK_UNSUPPORTED",
                    "no verified operating-system lock backend is available",
                    details={
                        "path": str(lock_path),
                        "platform": _platform_family(),
                    },
                )
            return
        except FlowError:
            raise
        except (OSError, ValueError) as exc:
            busy = isinstance(exc, OSError) and exc.errno in {
                errno.EACCES,
                errno.EAGAIN,
                errno.EDEADLK,
            }
            if busy and time.monotonic() < deadline:
                time.sleep(LOCK_POLL_SECONDS)
                continue
            if busy:
                raise FlowError(
                    "LOCK_TIMEOUT",
                    "timed out waiting for the exclusive controller lock",
                    details={
                        "path": str(lock_path),
                        "platform": _platform_family(),
                        "timeout_seconds": LOCK_TIMEOUT_SECONDS,
                    },
                ) from exc
            raise FlowError(
                "LOCK_ACQUIRE_FAILED",
                "could not acquire the exclusive controller lock",
                details={
                    "path": str(lock_path),
                    "platform": _platform_family(),
                    "error": str(exc),
                },
            ) from exc


def _release_exclusive(handle: Any, lock_path: Path) -> None:
    try:
        if fcntl is not None:
            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_UN,
                1,
                0,
                os.SEEK_SET,
            )
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            raise FlowError(
                "LOCK_UNSUPPORTED",
                "no verified operating-system lock backend is available",
                details={"path": str(lock_path), "platform": _platform_family()},
            )
    except FlowError:
        raise
    except (OSError, ValueError) as exc:
        raise FlowError(
            "LOCK_RELEASE_FAILED",
            (
                "exclusive controller lock release could not be verified; "
                "reload durable state before any retry"
            ),
            details={
                "path": str(lock_path),
                "platform": _platform_family(),
                "error": str(exc),
            },
        ) from exc


@contextlib.contextmanager
def _file_lock(
    directory: Path, name: str, *, allow_quarantine: bool = False
) -> Iterator[None]:
    _ensure_private_dir(directory)
    lock_path = directory / name
    with lock_path.open("a+b") as handle:
        _set_private_permissions(lock_path, 0o600)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        _acquire_exclusive(handle, lock_path)
        token: contextvars.Token[tuple[str, ...]] | None = None
        try:
            if not allow_quarantine:
                _assert_no_mutation_quarantine(directory)
            token = _HELD_LOCK_DIRECTORIES.set(
                (
                    *_HELD_LOCK_DIRECTORIES.get(),
                    str(directory.resolve(strict=False)),
                )
            )
            yield
        finally:
            if token is not None:
                _HELD_LOCK_DIRECTORIES.reset(token)
            try:
                _release_exclusive(handle, lock_path)
            finally:
                _forget_active_mutation_intents(directory)


@contextlib.contextmanager
def _task_lock(
    task_dir: Path, *, allow_quarantine: bool = False
) -> Iterator[None]:
    with _file_lock(
        task_dir, "state.lock", allow_quarantine=allow_quarantine
    ):
        yield


@contextlib.contextmanager
def _task_namespace_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "task-namespace.lock"):
        yield


@contextlib.contextmanager
def _workspace_registry_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "workspace-registry.lock"):
        yield


@contextlib.contextmanager
def _config_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "config.lock"):
        yield


def config_path(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "config.json"


def _default_config() -> dict[str, Any]:
    """The absent-configuration default keeps the plugin active everywhere."""

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {"mode": "all", "include": [], "exclude": []},
    }


def _normalize_scope_root(
    value: Any, option: str, *, code: str = "INVALID_ARGUMENT"
) -> str:
    text = str(value or "").strip()
    if not text:
        raise FlowError(code, f"{option} requires a non-empty directory path")
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise FlowError(
            code,
            f"{option} is not a usable directory path",
            details={"path": text, "error": str(exc)},
        ) from exc


def _normalize_scope(value: Any) -> dict[str, Any]:
    """Coerce a stored scope object into its canonical absolute-path form."""

    supplied = value if isinstance(value, dict) else {}
    mode = str(supplied.get("mode", "all")).strip().lower() or "all"
    if mode not in SCOPE_MODES:
        raise FlowError(
            "CONFIG_INVALID",
            f"scope.mode must be one of: {', '.join(SCOPE_MODES)}",
            details={"mode": mode},
        )
    scope: dict[str, Any] = {"mode": mode}
    for key in ("include", "exclude"):
        raw = supplied.get(key) or []
        if not isinstance(raw, list):
            raise FlowError(
                "CONFIG_INVALID",
                f"scope.{key} must be a list of directories",
                details={"key": key},
            )
        roots: list[str] = []
        for item in raw:
            root = _normalize_scope_root(
                item, f"scope.{key}", code="CONFIG_INVALID"
            )
            if not any(
                _same_path(Path(root), Path(existing))
                for existing in roots
            ):
                roots.append(root)
        scope[key] = sorted(roots)
    return scope


def load_config(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the stored plugin configuration, or the defaults when absent."""

    path = config_path(data_dir)
    if not path.exists():
        return _default_config()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration has an unsupported structure",
            details={
                "path": str(path),
                "schema_version": value.get("schema_version")
                if isinstance(value, dict)
                else None,
            },
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": _normalize_scope(value.get("scope")),
    }


def _scope_env_roots(environ: Any, name: str) -> list[str] | None:
    """Parse one ``os.pathsep`` separated override, or None when unset."""

    raw = environ.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    roots: list[str] = []
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        root = _normalize_scope_root(item, name)
        if not any(
            _same_path(Path(root), Path(existing)) for existing in roots
        ):
            roots.append(root)
    return sorted(roots) or None


def resolve_scope(
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Return the stored scope after applying the environment overrides.

    ``DEV_FLOW_SCOPE`` replaces the included directories and forces allowlist
    mode; ``DEV_FLOW_SCOPE_EXCLUDE`` replaces the excluded directories in
    either mode.  ``overrides`` records which list the environment supplied.
    """

    values = os.environ if environ is None else environ
    scope = load_config(data_dir)["scope"]
    overrides: dict[str, str] = {}
    include = _scope_env_roots(values, SCOPE_INCLUDE_ENV)
    if include is not None:
        scope.update({"mode": "allowlist", "include": include})
        overrides["include"] = SCOPE_INCLUDE_ENV
    exclude = _scope_env_roots(values, SCOPE_EXCLUDE_ENV)
    if exclude is not None:
        scope["exclude"] = exclude
        overrides["exclude"] = SCOPE_EXCLUDE_ENV
    scope["overrides"] = overrides
    return scope


def evaluate_scope(path: str | os.PathLike[str], scope: dict[str, Any]) -> dict[str, Any]:
    """Decide whether one directory is in scope; the deepest root wins.

    A directory nested under both an included and an excluded root follows the
    more specific one, so an allowlist can carve exceptions back out of an
    exclusion.  An exactly equal pair resolves to the exclusion.
    """

    current = Path(path).expanduser().resolve(strict=False)
    matched: str | None = None
    rule = "default"
    depth = -1
    for candidate_rule in ("include", "exclude"):
        for root in scope.get(candidate_rule) or []:
            candidate = Path(root)
            if not _is_within(current, candidate):
                continue
            candidate_depth = len(
                _filesystem_identity(candidate)["parts"]
            )
            if candidate_depth > depth or (
                candidate_depth == depth and candidate_rule == "exclude"
            ):
                matched, rule, depth = root, candidate_rule, candidate_depth
    if rule == "default":
        in_scope = str(scope.get("mode", "all")) != "allowlist"
    else:
        in_scope = rule == "include"
    return {
        "path": str(current),
        "in_scope": in_scope,
        "rule": rule,
        "matched": matched,
        "mode": str(scope.get("mode", "all")),
    }


def evaluate_scope_for_path(
    path: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Resolve the effective scope and evaluate one directory against it."""

    return evaluate_scope(path, resolve_scope(data_dir, environ))


def _scope_summary(scope: dict[str, Any]) -> str:
    if str(scope.get("mode", "all")) == "allowlist":
        if not scope.get("include"):
            return "inactive in every directory"
        if scope.get("exclude"):
            return "active only inside the included directories, minus the excluded ones"
        return "active only inside the included directories"
    if scope.get("exclude"):
        return "active in every directory except the excluded ones"
    return "active in every directory"


def _assert_path_in_scope(
    path: Path, label: str, data_dir: str | os.PathLike[str] | None
) -> None:
    decision = evaluate_scope_for_path(path, data_dir)
    if decision["in_scope"]:
        return
    raise FlowError(
        "OUT_OF_SCOPE",
        f"{label} is outside the configured Dev Flow scope",
        details={
            "path": decision["path"],
            "matched": decision["matched"],
            "rule": decision["rule"],
            "mode": decision["mode"],
            "config_path": str(config_path(data_dir)),
            "remedy": "add the directory with the scope command, or widen the scope",
        },
    )


def _load_workspace_registry(
    data_root: Path, *, allow_legacy_container: bool = False
) -> dict[str, Any]:
    path = data_root / "workspace-registry.json"
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "claims": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or not isinstance(value.get("claims"), list)
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has an unsupported structure",
            details={"path": str(path)},
        )
    _assert_supported_evidence_versions(value)
    if (
        value.get("evidence_contract_version")
        != EVIDENCE_CONTRACT_VERSION
        and not allow_legacy_container
    ):
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            (
                "legacy workspace registry evidence must be regenerated from "
                "a current approved workspace plan"
            ),
            details={
                "path": str(path),
                "required_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_version": value.get(
                    "evidence_contract_version"
                ),
            },
        )
    return value


def _source_common_dir_for_claim(source_path: Any) -> str:
    source = Path(str(source_path)).expanduser().resolve(strict=False)
    try:
        return str(_git_evidence_path(source, "--git-common-dir"))
    except (FlowError, OSError):
        return f"unavailable:{source}"


def _state_workspace_claims(data_root: Path) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    tasks_dir = data_root / "tasks"
    if not tasks_dir.is_dir():
        return claims
    for state_path in tasks_dir.glob("*/state.json"):
        try:
            state_value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(state_value, dict) or not state_value.get("task_id"):
            continue
        task_id = state_value["task_id"]
        for repo in state_value.get("repositories", []):
            common_dir = _source_common_dir_for_claim(repo.get("path"))
            for workspace in [repo.get("workspace"), *repo.get("workspace_history", [])]:
                if not isinstance(workspace, dict) or not workspace.get("path"):
                    continue
                workspace_path = Path(workspace["path"]).resolve(strict=False)
                source_path = Path(repo.get("path", "")).resolve(strict=False)
                common_path = (
                    Path(common_dir)
                    if not common_dir.startswith("unavailable:")
                    else None
                )
                claims.append(
                    {
                        "evidence_contract_version": workspace.get(
                            "evidence_contract_version"
                        ),
                        "task_id": task_id,
                        "repository_id": repo.get("id"),
                        "source_path": str(source_path),
                        "source_identity": _serializable_path_identity(source_path),
                        "path": str(workspace_path),
                        "path_identity": _serializable_path_identity(workspace_path),
                        "branch": workspace.get("branch"),
                        "branch_ref": workspace.get("branch_ref"),
                        "planned_ref_oid": workspace.get(
                            "planned_ref_oid"
                        ),
                        "ref_case_sensitive": workspace.get(
                            "ref_case_sensitive"
                        ),
                        "ref_unicode_normalization_distinct": workspace.get(
                            "ref_unicode_normalization_distinct"
                        ),
                        "source_common_dir": common_dir,
                        "source_common_dir_identity": (
                            _serializable_path_identity(common_path)
                            if common_path is not None
                            else None
                        ),
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": (
                            workspace.get("workspace_claim") or {}
                        ).get("plan_sha256"),
                        "origin": "task-state",
                    }
                )
        controller_plan = (state_value.get("workspace") or {}).get("plan") or {}
        plan_path = controller_plan.get("path")
        if plan_path:
            try:
                evidence = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for planned in evidence.get("repositories", []):
                if not planned.get("path"):
                    continue
                planned_path = Path(planned["path"]).resolve(strict=False)
                source_path = Path(
                    planned.get("source_path", "")
                ).resolve(strict=False)
                common_dir = _source_common_dir_for_claim(source_path)
                common_path = (
                    Path(common_dir)
                    if not common_dir.startswith("unavailable:")
                    else None
                )
                claims.append(
                    {
                        "evidence_contract_version": evidence.get(
                            "evidence_contract_version"
                        ),
                        "task_id": task_id,
                        "repository_id": planned.get("repository_id"),
                        "source_path": str(source_path),
                        "source_identity": planned.get("source_identity")
                        or _serializable_path_identity(source_path),
                        "path": str(planned_path),
                        "path_identity": planned.get("path_identity")
                        or _serializable_path_identity(planned_path),
                        "branch": planned.get("branch"),
                        "branch_ref": planned.get("branch_ref"),
                        "planned_ref_oid": planned.get(
                            "planned_ref_oid"
                        ),
                        "ref_case_sensitive": planned.get(
                            "ref_case_sensitive"
                        ),
                        "ref_unicode_normalization_distinct": planned.get(
                            "ref_unicode_normalization_distinct"
                        ),
                        "source_common_dir": common_dir,
                        "source_common_dir_identity": planned.get(
                            "source_common_dir_identity"
                        )
                        or (
                            _serializable_path_identity(common_path)
                            if common_path is not None
                            else None
                        ),
                        "workspace_generation": controller_plan.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": controller_plan.get("sha256"),
                        "origin": "task-plan",
                    }
                )
    return claims


def _claim_workspace_plan(
    data_root: Path,
    state_value: dict[str, Any],
    plan_sha256: str,
    plans: Sequence[dict[str, Any]],
    *,
    registry_locked: bool = False,
) -> dict[str, dict[str, Any]]:
    lock_context = (
        contextlib.nullcontext()
        if registry_locked
        else _workspace_registry_lock(data_root)
    )
    with lock_context:
        registry = _load_workspace_registry(
            data_root, allow_legacy_container=True
        )
        existing_claims = [*registry["claims"], *_state_workspace_claims(data_root)]
        proposed: list[dict[str, Any]] = []
        for plan in plans:
            source_path = Path(plan["source_path"]).resolve(strict=False)
            workspace_path = Path(plan["path"]).resolve(strict=False)
            source_common_dir = _source_common_dir_for_claim(source_path)
            source_common_path = (
                Path(source_common_dir)
                if not source_common_dir.startswith("unavailable:")
                else None
            )
            proposed.append(
                {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "claim_id": str(uuid.uuid4()),
                    "task_id": state_value["task_id"],
                    "repository_id": plan["repository_id"],
                    "source_path": str(source_path),
                    "source_identity": _serializable_path_identity(source_path),
                    "source_common_dir": source_common_dir,
                    "source_common_dir_identity": (
                        _serializable_path_identity(source_common_path)
                        if source_common_path is not None
                        else None
                    ),
                    "path": str(workspace_path),
                    "path_identity": _serializable_path_identity(workspace_path),
                    "branch": plan["branch"],
                    "branch_ref": plan.get("branch_ref"),
                    "planned_ref_oid": plan.get("planned_ref_oid"),
                    "ref_case_sensitive": plan.get("ref_case_sensitive"),
                    "ref_unicode_normalization_distinct": plan.get(
                        "ref_unicode_normalization_distinct"
                    ),
                    "workspace_generation": int(
                        (state_value.get("workspace") or {}).get("generation", 0)
                    ),
                    "plan_sha256": plan_sha256,
                    "claimed_at": utc_now(),
                }
            )
        for candidate_index, candidate in enumerate(proposed):
            candidate_path = Path(candidate["path"])
            for claimed in [*existing_claims, *proposed[:candidate_index]]:
                exact_retry = (
                    claimed.get("task_id") == candidate["task_id"]
                    and claimed.get("repository_id")
                    == candidate["repository_id"]
                    and _recorded_path_matches(
                        claimed.get("path_identity"),
                        claimed.get("path"),
                        candidate_path,
                    )
                    and claimed.get("branch") == candidate["branch"]
                    and claimed.get("branch_ref")
                    == candidate.get("branch_ref")
                    and claimed.get("planned_ref_oid")
                    == candidate.get("planned_ref_oid")
                    and claimed.get(
                        "ref_unicode_normalization_distinct"
                    )
                    == candidate.get(
                        "ref_unicode_normalization_distinct"
                    )
                    and (
                        _path_identity_equal(
                            claimed.get("source_common_dir_identity"),
                            candidate.get("source_common_dir_identity"),
                        )
                        if candidate.get("source_common_dir_identity")
                        else claimed.get("source_common_dir")
                        == candidate["source_common_dir"]
                    )
                    and claimed.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claimed.get("plan_sha256") == candidate["plan_sha256"]
                )
                if exact_retry:
                    continue
                regenerating_same_legacy_claim = (
                    claimed.get("evidence_contract_version")
                    != EVIDENCE_CONTRACT_VERSION
                    and claimed.get("task_id") == candidate["task_id"]
                    and claimed.get("repository_id")
                    == candidate["repository_id"]
                    and claimed.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and _recorded_path_matches(
                        claimed.get("path_identity"),
                        claimed.get("path"),
                        candidate_path,
                    )
                    and claimed.get("branch") == candidate["branch"]
                )
                if regenerating_same_legacy_claim:
                    continue
                claimed_path_value = claimed.get("path")
                claimed_path = (
                    Path(claimed_path_value).resolve(strict=False)
                    if claimed_path_value
                    else None
                )
                path_conflict = bool(
                    claimed_path
                    and (
                        _is_within(candidate_path, claimed_path)
                        or _is_within(claimed_path, candidate_path)
                    )
                )
                candidate_ref = candidate.get("branch_ref") or (
                    f"refs/heads/{candidate['branch']}"
                    if candidate.get("branch")
                    else None
                )
                claimed_ref = claimed.get("branch_ref") or (
                    f"refs/heads/{claimed['branch']}"
                    if claimed.get("branch")
                    else None
                )
                ref_case_sensitive = bool(
                    candidate.get("ref_case_sensitive", True)
                    and claimed.get("ref_case_sensitive", True)
                )
                ref_unicode_distinct = bool(
                    candidate.get(
                        "ref_unicode_normalization_distinct", True
                    )
                    and claimed.get(
                        "ref_unicode_normalization_distinct", True
                    )
                )
                candidate_ref_identity = (
                    (
                        str(candidate_ref)
                        if ref_unicode_distinct
                        else unicodedata.normalize(
                            "NFC", str(candidate_ref)
                        )
                    )
                    if candidate_ref
                    else None
                )
                claimed_ref_identity = (
                    (
                        str(claimed_ref)
                        if ref_unicode_distinct
                        else unicodedata.normalize(
                            "NFC", str(claimed_ref)
                        )
                    )
                    if claimed_ref
                    else None
                )
                if not ref_case_sensitive:
                    candidate_ref_identity = (
                        candidate_ref_identity.casefold()
                        if candidate_ref_identity
                        else None
                    )
                    claimed_ref_identity = (
                        claimed_ref_identity.casefold()
                        if claimed_ref_identity
                        else None
                    )
                branch_conflict = bool(
                    candidate_ref_identity
                    and claimed_ref_identity
                    and (
                        candidate_ref_identity == claimed_ref_identity
                        or candidate_ref_identity.startswith(
                            f"{claimed_ref_identity}/"
                        )
                        or claimed_ref_identity.startswith(
                            f"{candidate_ref_identity}/"
                        )
                    )
                    and candidate.get("source_common_dir")
                    and (
                        _path_identity_equal(
                            candidate.get("source_common_dir_identity"),
                            claimed.get("source_common_dir_identity"),
                        )
                        if candidate.get("source_common_dir_identity")
                        and claimed.get("source_common_dir_identity")
                        else _same_path(
                            Path(candidate["source_common_dir"]),
                            Path(str(claimed.get("source_common_dir"))),
                        )
                        if claimed.get("source_common_dir")
                        and not str(claimed.get("source_common_dir")).startswith(
                            "unavailable:"
                        )
                        else candidate.get("source_common_dir")
                        == claimed.get("source_common_dir")
                    )
                )
                if path_conflict or branch_conflict:
                    raise FlowError(
                        "WORKSPACE_OWNERSHIP_CONFLICT",
                        "workspace path or repository branch is already claimed by another task or repository plan",
                        details={
                            "task_id": state_value["task_id"],
                            "repository_id": candidate["repository_id"],
                            "path": candidate["path"],
                            "branch": candidate["branch"],
                            "owner_task_id": claimed.get("task_id"),
                            "owner_path": claimed.get("path"),
                            "owner_branch": claimed.get("branch"),
                            "conflict": "path" if path_conflict else "branch",
                        },
                    )
        selected_claims: dict[str, dict[str, Any]] = {}
        for candidate in proposed:
            existing = next(
                (
                    claim
                    for claim in registry["claims"]
                    if claim.get("evidence_contract_version")
                    == EVIDENCE_CONTRACT_VERSION
                    and claim.get("task_id") == candidate["task_id"]
                    and claim.get("repository_id") == candidate["repository_id"]
                    and claim.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claim.get("plan_sha256") == candidate["plan_sha256"]
                    and _recorded_path_matches(
                        claim.get("path_identity"),
                        claim.get("path"),
                        Path(candidate["path"]),
                    )
                    and claim.get("branch") == candidate["branch"]
                    and claim.get("branch_ref")
                    == candidate.get("branch_ref")
                    and claim.get("planned_ref_oid")
                    == candidate.get("planned_ref_oid")
                    and claim.get(
                        "ref_unicode_normalization_distinct"
                    )
                    == candidate.get(
                        "ref_unicode_normalization_distinct"
                    )
                ),
                None,
            )
            if existing is None:
                registry["claims"].append(candidate)
                existing = candidate
            selected_claims[candidate["repository_id"]] = existing
        registry["evidence_contract_version"] = (
            EVIDENCE_CONTRACT_VERSION
        )
        _atomic_write_json(data_root / "workspace-registry.json", registry)
        for plan in plans:
            claim = selected_claims[plan["repository_id"]]
            plan["workspace_claim"] = {
                "claim_id": claim["claim_id"],
                "registry_path": str(data_root / "workspace-registry.json"),
                "registry_identity": _serializable_path_identity(
                    data_root / "workspace-registry.json"
                ),
                "plan_sha256": plan_sha256,
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "path_identity": claim.get("path_identity"),
                "source_identity": claim.get("source_identity"),
                "source_common_dir_identity": claim.get(
                    "source_common_dir_identity"
                ),
            }
        return selected_claims


def _actor() -> str:
    return (
        _nonempty(os.environ.get("DEV_FLOW_ACTOR"))
        or _nonempty(os.environ.get("USER"))
        or _nonempty(os.environ.get("USERNAME"))
        or "unknown"
    )


def _commit_state(
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any],
    task_dir: Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_revision = int(old_state.get("revision", 0)) if old_state else 0
    revision = previous_revision + 1
    now = utc_now()
    new_state["revision"] = revision
    new_state["updated_at"] = now
    event = {
        "event_id": str(uuid.uuid4()),
        "task_id": new_state["task_id"],
        "type": event_type,
        "at": now,
        "actor": _actor(),
        "previous_revision": previous_revision,
        "revision": revision,
        "status": new_state["status"],
        "payload": payload or {},
    }
    _atomic_write_json(task_dir / "state.json", new_state)
    _append_event(task_dir / "events.jsonl", event)
    _complete_mutation_intent(task_dir, revision)
    return event


def _check_revision(state_value: dict[str, Any], expected_revision: int) -> None:
    actual = int(state_value.get("revision", 0))
    if expected_revision != actual:
        raise FlowError(
            "REVISION_CONFLICT",
            f"expected revision {expected_revision}, but current revision is {actual}",
            details={
                "task_id": state_value.get("task_id"),
                "expected_revision": expected_revision,
                "actual_revision": actual,
            },
            exit_code=3,
        )


@contextlib.contextmanager
def _locked_state(
    task_id: str,
    data_dir: str | os.PathLike[str] | None,
    expected_revision: int,
    *,
    lock_workspace_registry: bool = False,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    task_dir = _task_dir(task_id, data_dir)
    with _task_lock(task_dir):
        state_value = load_state(task_id, data_dir)
        _check_revision(state_value, expected_revision)
        if lock_workspace_registry:
            with _workspace_registry_lock(resolve_data_dir(data_dir)):
                yield task_dir, state_value
        else:
            yield task_dir, state_value


def _posix_process_group_alive(process_group: int) -> bool:
    if os.name == "nt":  # pragma: no cover - POSIX helper
        return False
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise
    return True


def _quiesce_completed_process_group(
    process: subprocess.Popen[bytes], command: Sequence[str]
) -> None:
    if os.name == "nt" or not _posix_process_group_alive(process.pid):
        return
    for signal_number, timeout_seconds in ((15, 2.0), (9, 5.0)):
        try:
            os.killpg(process.pid, signal_number)
        except ProcessLookupError:
            return
        except OSError:
            pass
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not _posix_process_group_alive(process.pid):
                return
            time.sleep(0.05)
    error = RuntimeError(
        "owned process group remained active after its leader exited"
    )
    quarantine = _persist_mutation_quarantine(process, command, error)
    raise FlowError(
        "MUTATION_QUARANTINED",
        "mutating child descendants could not be proven quiescent",
        details={
            "pid": process.pid,
            "process_group": process.pid,
            "command": list(command),
            "quarantine": str(quarantine) if quarantine else None,
        },
    )


def _windows_kill_on_close_job(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    require_ownership: bool = True,
) -> Any:
    """Place a protected child in a kill-on-close job.

    ``require_ownership`` is true for a gated mutation, whose child is blocked
    reading its gate byte and is therefore provably still alive: failing to
    own it is a real failure and stays fail-closed, because kill-on-job-close
    containment is what the quarantine mechanism relies on.  A read-only
    protected child is contained on the same terms when Windows allows it, but
    an unownable one is not an error; see the failure branch below.
    """

    if os.name != "nt":  # pragma: no cover - native Windows helper
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def ownership_failure(message: str, error: int) -> None:
        try:
            process.terminate()
            process.wait(timeout=5.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "unowned Windows child could not be proven quiescent",
                details={
                    "pid": process.pid,
                    "winerror": error,
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
        raise FlowError(
            "PROCESS_OWNERSHIP_FAILED",
            message,
            details={"pid": process.pid, "winerror": error},
        )

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        if not require_ownership:
            return None
        ownership_failure(
            "could not create a Windows child-process job",
            ctypes.get_last_error(),
        )
    limits = EXTENDED_LIMITS()
    limits.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel32.AssignProcessToJobObject(
        job, wintypes.HANDLE(process._handle)  # type: ignore[attr-defined]
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        if not require_ownership:
            # Containment of a read-only child is best effort, not a
            # precondition.  Such a child runs under DEVNULL stdin with no
            # gate holding it, so it regularly finishes between Popen and
            # this assignment, and Windows answers ERROR_ACCESS_DENIED for a
            # process that has terminated or is terminating -- sometimes
            # before its handle is even signalled, so an exit check cannot
            # recognize every instance.  There is no mutation to contain, so
            # continue with an unowned child rather than failing a read-only
            # command with a mutation-ownership error.
            return None
        ownership_failure(
            "could not place a mutating child in an owned Windows job",
            error,
        )
    return job


def _terminate_windows_job(job: Any) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
    ]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    if not kernel32.TerminateJobObject(job, 1):
        raise OSError(
            ctypes.get_last_error(), "TerminateJobObject failed"
        )


def _windows_job_active_processes(job: Any) -> int:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return 0
    import ctypes
    from ctypes import wintypes

    class BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    accounting = BASIC_ACCOUNTING()
    returned = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
        job,
        1,  # JobObjectBasicAccountingInformation
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        ctypes.byref(returned),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "QueryInformationJobObject failed",
        )
    return int(accounting.ActiveProcesses)


def _quiesce_windows_job(
    job: Any,
    process: subprocess.Popen[bytes],
    command: Sequence[str],
) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    try:
        active = _windows_job_active_processes(job)
        if active:
            _terminate_windows_job(job)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if _windows_job_active_processes(job) == 0:
                    return
                time.sleep(0.05)
            active = _windows_job_active_processes(job)
        if active:
            raise OSError(
                errno.EBUSY,
                f"Windows job still contains {active} active processes",
            )
    except OSError as exc:
        quarantine = _persist_mutation_quarantine(
            process, command, exc
        )
        raise FlowError(
            "MUTATION_QUARANTINED",
            "Windows child job could not be proven quiescent",
            details={
                "pid": process.pid,
                "command": list(command),
                "quarantine": (
                    str(quarantine) if quarantine else None
                ),
                "error": str(exc),
            },
        ) from exc


def _close_windows_job(job: Any) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(job):
        raise OSError(ctypes.get_last_error(), "CloseHandle failed")


_MUTATION_GATE_ENVELOPE = b"DEV_FLOW_GATE_V1:"
_MUTATION_GATE_CODE = """
import base64
import json
import subprocess
import sys

gate = sys.stdin.buffer.read(1)
command = json.loads(sys.argv[1])
if gate != b"G":
    sys.exit(253)
try:
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    envelope = {
        "version": 1,
        "status": "completed",
        "returncode": result.returncode,
        "stdout": base64.b64encode(result.stdout).decode("ascii"),
        "stderr": base64.b64encode(result.stderr).decode("ascii"),
    }
except (OSError, ValueError, subprocess.SubprocessError) as exc:
    envelope = {
        "version": 1,
        "status": "spawn_error",
        "error": str(exc),
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
    }
payload = json.dumps(
    envelope,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8", "backslashreplace")
sys.stdout.buffer.write(b"DEV_FLOW_GATE_V1:" + payload)
sys.stdout.buffer.flush()
""".strip()
# Compatibility aliases retained for focused downstream tests and diagnostics.
_WINDOWS_MUTATION_GATE_CODE = _MUTATION_GATE_CODE


def _mutation_gate_command(
    command: Sequence[str],
) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-S",
        "-c",
        _MUTATION_GATE_CODE,
        json.dumps(list(command), ensure_ascii=True),
    ]


def _windows_mutation_gate_command(
    command: Sequence[str],
) -> list[str]:
    return _mutation_gate_command(command)


def _terminate_and_quiesce_owned_child(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    protected_child: bool,
    windows_job: Any,
) -> bool:
    """Best-effort termination whose result is safe to use before unlock."""

    try:
        if os.name == "nt" and windows_job:
            _terminate_windows_job(windows_job)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
            _quiesce_windows_job(windows_job, process, command)
            return _windows_job_active_processes(windows_job) == 0
        if os.name != "nt" and protected_child:
            process_group = process.pid
            if _posix_process_group_alive(process_group):
                try:
                    os.killpg(process_group, 15)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 2.0
            while (
                time.monotonic() < deadline
                and _posix_process_group_alive(process_group)
            ):
                time.sleep(0.05)
            if _posix_process_group_alive(process_group):
                try:
                    os.killpg(process_group, 9)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
            deadline = time.monotonic() + 5.0
            while (
                time.monotonic() < deadline
                and _posix_process_group_alive(process_group)
            ):
                time.sleep(0.05)
            return not _posix_process_group_alive(process_group)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
        return process.poll() is not None
    except BaseException:
        return False


def _parse_mutation_gate_envelope(
    stdout: bytes, stderr: bytes, returncode: int
) -> dict[str, Any]:
    if (
        returncode != 0
        or stderr
        or not stdout.startswith(_MUTATION_GATE_ENVELOPE)
    ):
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate did not return its private completion envelope",
            details={
                "gate_returncode": returncode,
                "stdout_sha256": _sha256_bytes(stdout),
                "stderr_sha256": _sha256_bytes(stderr),
            },
        )
    payload = stdout[len(_MUTATION_GATE_ENVELOPE) :]
    try:
        envelope = json.loads(payload.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate returned an invalid completion envelope",
            details={
                "payload_sha256": _sha256_bytes(payload),
                "error": str(exc),
            },
        ) from exc
    if not isinstance(envelope, dict) or envelope.get("version") != 1:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate returned an unsupported completion envelope",
        )
    status = envelope.get("status")
    if status == "spawn_error":
        return envelope
    returncode_value = envelope.get("returncode")
    if (
        status != "completed"
        or not isinstance(returncode_value, int)
        or isinstance(returncode_value, bool)
        or not isinstance(envelope.get("stdout"), str)
        or not isinstance(envelope.get("stderr"), str)
    ):
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate completion envelope is incomplete",
        )
    import base64
    import binascii

    try:
        target_stdout = base64.b64decode(
            envelope["stdout"].encode("ascii"), validate=True
        )
        target_stderr = base64.b64decode(
            envelope["stderr"].encode("ascii"), validate=True
        )
    except (UnicodeError, binascii.Error) as exc:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate completion bytes are invalid",
            details={"error": str(exc)},
        ) from exc
    return {
        **envelope,
        "stdout_bytes": target_stdout,
        "stderr_bytes": target_stderr,
    }


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    text: bool = True,
    evidence_git: bool = False,
    mutation: bool = False,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    executable = (
        re.split(r"[\\/]", str(command[0]))[-1].casefold()
        if command
        else ""
    )
    is_git = executable in {"git", "git.exe"}
    if is_git:
        # ``git -C`` does not override repository redirection variables.  A
        # caller-controlled environment must not be able to make identity,
        # baseline, worktree, or side-effect commands operate on another
        # repository or index.
        for key in list(environment):
            if key in {
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_INDEX_FILE",
                "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE",
                "GIT_CONFIG",
                "GIT_CONFIG_PARAMETERS",
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_CEILING_DIRECTORIES",
                "GIT_DISCOVERY_ACROSS_FILESYSTEM",
                "GIT_EXEC_PATH",
                "GIT_SHALLOW_FILE",
                "GIT_GRAFT_FILE",
                "GIT_TEMPLATE_DIR",
                "GIT_REPLACE_REF_BASE",
                "GIT_ALLOW_PROTOCOL",
                "GIT_PROTOCOL_FROM_USER",
                "GIT_REDIRECT_STDERR",
            } or key.startswith(
                (
                    "GIT_CONFIG_KEY_",
                    "GIT_CONFIG_VALUE_",
                    "GIT_TRACE",
                )
            ):
                environment.pop(key, None)
        environment.pop("GIT_CONFIG_COUNT", None)
        for key in (
            "GIT_ASKPASS",
            "GIT_PROXY_COMMAND",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GIT_SSH_VARIANT",
            "SSH_ASKPASS",
            "SSH_ASKPASS_REQUIRE",
        ):
            environment.pop(key, None)
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["SSH_ASKPASS_REQUIRE"] = "never"
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        environment["GIT_NO_LAZY_FETCH"] = "1"
        # Disable both environment-selected and repository-local legacy grafts.
        environment["GIT_GRAFT_FILE"] = os.devnull
    if evidence_git:
        environment.pop("GIT_EXTERNAL_DIFF", None)
        environment.pop("GIT_DIFF_OPTS", None)
    protected_child = bool(_HELD_LOCK_DIRECTORIES.get())
    if mutation and not protected_child:
        raise FlowError(
            "MUTATION_LOCK_REQUIRED",
            "a mutating child cannot start outside a controller lock",
            details={"command": list(command)},
        )
    mutation_intent = (
        _begin_mutation_intent(command) if mutation else None
    )
    gated_mutation = bool(mutation and protected_child)
    launch_command = (
        _mutation_gate_command(command)
        if gated_mutation
        else list(command)
    )
    process_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": environment,
        "stdin": (
            subprocess.PIPE
            if gated_mutation
            else subprocess.DEVNULL
        ),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": False,
    }
    if protected_child and os.name == "nt":  # pragma: no cover - native Windows
        process_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    elif protected_child:
        process_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(launch_command, **process_kwargs)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _abandon_unstarted_mutation_intent(mutation_intent)
        raise FlowError(
            "COMMAND_FAILED",
            f"could not execute {command[0]}",
            details={
                "command": list(command),
                "cwd": str(cwd) if cwd else None,
                "error": str(exc),
                "failure_kind": "spawn",
                "errno": getattr(exc, "errno", None),
            },
        ) from exc
    windows_job: Any = None
    if protected_child and os.name == "nt":  # pragma: no cover - native Windows
        try:
            windows_job = _windows_kill_on_close_job(
                process, command, require_ownership=gated_mutation
            )
        except FlowError as exc:
            if (
                gated_mutation
                and exc.code == "PROCESS_OWNERSHIP_FAILED"
            ):
                _abandon_unstarted_mutation_intent(
                    mutation_intent
                )
            raise
    if mutation:
        try:
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase="child_owned",
            )
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase="target_release_authorized",
                target_release_authorized=True,
            )
        except BaseException as exc:
            cleanup_error: BaseException | None = None
            try:
                _terminate_and_quiesce_owned_child(
                    process,
                    command,
                    protected_child=protected_child,
                    windows_job=windows_job,
                )
            except BaseException as nested_error:
                cleanup_error = nested_error
                if os.name == "nt" and windows_job:
                    try:
                        _terminate_windows_job(windows_job)
                    except BaseException:
                        pass
                elif os.name != "nt" and protected_child:
                    try:
                        os.killpg(process.pid, 9)
                    except BaseException:
                        pass
            if os.name == "nt" and windows_job:
                try:
                    _close_windows_job(windows_job)
                except BaseException:
                    pass
            quarantine = _persist_mutation_quarantine(
                process, command, cleanup_error or exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                (
                    "mutating child ownership was established but its "
                    "durable PID evidence could not be updated"
                ),
                details={
                    "pid": process.pid,
                    "command": list(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
    try:
        if gated_mutation:
            stdout_bytes, stderr_bytes = process.communicate(
                input=b"G"
            )
        else:
            stdout_bytes, stderr_bytes = process.communicate()
        if os.name == "nt" and windows_job:
            _quiesce_windows_job(
                windows_job, process, command
            )
        elif protected_child and os.name != "nt":
            _quiesce_completed_process_group(process, command)
    except BaseException as exc:
        cleanup_error = None
        try:
            quiescent = _terminate_and_quiesce_owned_child(
                process,
                command,
                protected_child=protected_child,
                windows_job=windows_job,
            )
        except BaseException as nested_error:
            quiescent = False
            cleanup_error = nested_error
            if os.name == "nt" and windows_job:
                try:
                    _terminate_windows_job(windows_job)
                except BaseException:
                    pass
            elif os.name != "nt" and protected_child:
                try:
                    os.killpg(process.pid, 9)
                except BaseException:
                    pass
        if not quiescent:
            quarantine = _persist_mutation_quarantine(
                process, command, cleanup_error or exc
            )
            try:
                _close_windows_job(windows_job)
            except BaseException:
                pass
            raise FlowError(
                "MUTATION_QUARANTINED",
                "protected child failed and could not be proven quiescent",
                details={
                    "pid": process.pid,
                    "command": list(command),
                    "quarantine": str(quarantine) if quarantine else None,
                },
            ) from exc
        if mutation:
            try:
                _update_mutation_intent(
                    mutation_intent,
                    process,
                    command,
                    phase="interrupted_quiescent",
                    cause=exc,
                )
            except BaseException as evidence_error:
                quarantine = _persist_mutation_quarantine(
                    process, command, evidence_error
                )
                try:
                    _close_windows_job(windows_job)
                except BaseException:
                    pass
                raise FlowError(
                    "MUTATION_QUARANTINED",
                    "child was quiesced but interruption evidence could not be finalized",
                    details={
                        "pid": process.pid,
                        "quarantine": (
                            str(quarantine) if quarantine else None
                        ),
                    },
                ) from evidence_error
        try:
            _close_windows_job(windows_job)
        except BaseException as close_error:
            quarantine = _persist_mutation_quarantine(
                process, command, close_error
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "Windows child job could not be closed after interruption",
                details={
                    "pid": process.pid,
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from close_error
        raise
    try:
        _close_windows_job(windows_job)
    except BaseException as exc:
        quarantine = _persist_mutation_quarantine(process, command, exc)
        raise FlowError(
            "MUTATION_QUARANTINED",
            "Windows child-process ownership could not be released safely",
            details={
                "pid": process.pid,
                "command": list(command),
                "quarantine": str(quarantine) if quarantine else None,
                "error": str(exc),
            },
        ) from exc
    stdout_bytes = stdout_bytes or b""
    stderr_bytes = stderr_bytes or b""
    effective_returncode = int(process.returncode or 0)
    if gated_mutation:
        try:
            gate_envelope = _parse_mutation_gate_envelope(
                stdout_bytes,
                stderr_bytes,
                effective_returncode,
            )
        except FlowError as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "mutation gate completion could not be authenticated",
                details={
                    "pid": process.pid,
                    "command": list(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
        if gate_envelope.get("status") == "spawn_error":
            spawn_details = {
                key: gate_envelope.get(key)
                for key in ("error", "errno", "winerror")
            }
            _abandon_unstarted_mutation_intent(mutation_intent)
            raise FlowError(
                "COMMAND_FAILED",
                f"could not execute {command[0]}",
                details={
                    "command": list(command),
                    "cwd": str(cwd) if cwd else None,
                    "failure_kind": "spawn",
                    **spawn_details,
                },
            )
        effective_returncode = int(gate_envelope["returncode"])
        stdout_bytes = gate_envelope["stdout_bytes"]
        stderr_bytes = gate_envelope["stderr_bytes"]
    if mutation:
        try:
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase=(
                    "child_quiescent"
                    if effective_returncode == 0
                    else "child_failed_quiescent"
                ),
            )
        except BaseException as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "child exited but durable mutation evidence could not be finalized",
                details={
                    "pid": process.pid,
                    "command": list(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
    if text:
        stdout: Any = stdout_bytes.decode("utf-8", "backslashreplace")
        stderr: Any = stderr_bytes.decode("utf-8", "backslashreplace")
    else:
        stdout = stdout_bytes
        stderr = stderr_bytes
    result = subprocess.CompletedProcess(
        args=list(command),
        returncode=effective_returncode,
        stdout=stdout,
        stderr=stderr,
    )
    if check and result.returncode != 0:
        rendered_stderr = (
            result.stderr.strip()
            if text
            else result.stderr.decode("utf-8", "backslashreplace").strip()
        )
        raise FlowError(
            "COMMAND_FAILED",
            f"command failed with exit code {result.returncode}",
            details={
                "command": list(command),
                "cwd": str(cwd) if cwd else None,
                "stderr": rendered_stderr,
                "stderr_sha256": _sha256_bytes(stderr_bytes),
                "failure_kind": "exit",
                "returncode": result.returncode,
            },
        )
    return result


def _git(repo: Path, *arguments: str, check: bool = True, text: bool = True) -> Any:
    result = _run(["git", "-C", str(repo), *arguments], check=check, text=text)
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_mutating(
    repo: Path, *arguments: str, text: bool = True
) -> Any:
    result = _run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        text=text,
        mutation=True,
    )
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(["git", "-C", str(repo), *arguments], check=False, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_config_value(repo: Path, key: str) -> str | None:
    result = _run(
        ["git", "-C", str(repo), "config", "--get", key],
        check=False,
        text=True,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise FlowError(
            "GIT_CAPABILITY_UNAVAILABLE",
            f"could not read effective Git setting {key}",
            details={
                "repository": str(repo),
                "key": key,
                "stderr": result.stderr.strip(),
            },
        )
    return result.stdout.strip()


def _git_bool_config(repo: Path, key: str, default: bool) -> bool:
    value = _git_config_value(repo, key)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "on", "1"}:
        return True
    if lowered in {"false", "no", "off", "0"}:
        return False
    raise FlowError(
        "GIT_CAPABILITY_CONTRADICTION",
        f"effective Git setting {key} is not boolean",
        details={"repository": str(repo), "key": key, "value": value},
    )


def _probe_worktree_capabilities(repo: Path) -> dict[str, Any]:
    probe_root: Path | None = None
    try:
        probe_root = Path(
            tempfile.mkdtemp(prefix=".dev-flow-capability-", dir=str(repo))
        )
        regular = probe_root / "mode-probe"
        regular.write_bytes(b"mode")
        before = stat.S_IMODE(regular.stat().st_mode)
        file_mode = False
        if os.name != "nt":
            regular.chmod(before ^ stat.S_IXUSR)
            after = stat.S_IMODE(regular.stat().st_mode)
            file_mode = bool((before ^ after) & stat.S_IXUSR)
        target = probe_root / "symlink-target"
        link = probe_root / "symlink-probe"
        target.write_bytes(b"target")
        try:
            os.symlink(target.name, link)
            symlinks = link.is_symlink()
        except (OSError, NotImplementedError):
            symlinks = False
        unicode_normalization_distinct = (
            _probe_filesystem_unicode_distinct(probe_root)
        )
        case_sensitive = _probe_filesystem_case_sensitive(probe_root)
        return {
            "case_sensitive": case_sensitive,
            "file_mode": file_mode,
            "symlinks": symlinks,
            "unicode_normalization_distinct": unicode_normalization_distinct,
        }
    except FlowError:
        raise
    except OSError as exc:
        raise FlowError(
            "GIT_CAPABILITY_UNAVAILABLE",
            "could not probe worktree filesystem capabilities",
            details={"repository": str(repo), "error": str(exc)},
        ) from exc
    finally:
        if probe_root is not None:
            try:
                shutil.rmtree(probe_root)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "GIT_CAPABILITY_UNAVAILABLE",
                    "worktree capability probe could not be cleaned up",
                    details={"repository": str(repo), "path": str(probe_root), "error": str(exc)},
                ) from exc


def _git_capability_profile(
    repo: Path,
    filesystem_path: Path | None = None,
    *,
    filesystem_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = repo.resolve(strict=True)
    profile_path = filesystem_path or resolved
    probe_target = resolved
    if filesystem_path is not None:
        probe_target, _ = _nearest_existing_path(filesystem_path)
        if not probe_target.is_dir():
            probe_target = probe_target.parent
    filesystem = (
        dict(filesystem_capabilities)
        if filesystem_capabilities is not None
        else _probe_worktree_capabilities(probe_target)
    )
    core_file_mode = _git_bool_config(
        resolved, "core.fileMode", filesystem["file_mode"]
    )
    core_symlinks = _git_bool_config(
        resolved, "core.symlinks", filesystem["symlinks"]
    )
    core_ignore_case = _git_bool_config(
        resolved, "core.ignoreCase", not filesystem["case_sensitive"]
    )
    contradictions: list[str] = []
    if core_file_mode and not filesystem["file_mode"]:
        contradictions.append("core.fileMode=true but executable mode changes are unavailable")
    if core_symlinks and not filesystem["symlinks"]:
        contradictions.append("core.symlinks=true but native symlink creation is unavailable")
    if not core_ignore_case and not filesystem["case_sensitive"]:
        contradictions.append("core.ignoreCase=false on a case-insensitive filesystem")
    if contradictions:
        raise FlowError(
            "GIT_CAPABILITY_CONTRADICTION",
            "effective Git settings contradict verified worktree capabilities",
            details={
                "repository": str(resolved),
                "contradictions": contradictions,
                "filesystem": filesystem,
            },
        )
    autocrlf = (_git_config_value(resolved, "core.autocrlf") or "false").lower()
    eol = (_git_config_value(resolved, "core.eol") or "native").lower()
    if autocrlf not in {"true", "false", "input"} or eol not in {
        "native",
        "lf",
        "crlf",
    }:
        raise FlowError(
            "GIT_CAPABILITY_CONTRADICTION",
            "effective line-ending settings are not recognized",
            details={
                "repository": str(resolved),
                "core.autocrlf": autocrlf,
                "core.eol": eol,
            },
        )
    profile: dict[str, Any] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "platform": _platform_family(),
        "core_file_mode": core_file_mode,
        "core_symlinks": core_symlinks,
        "core_ignore_case": core_ignore_case,
        "core_autocrlf": autocrlf,
        "core_eol": eol,
        "filesystem": filesystem,
        "filesystem_identity": _capability_path_identity(profile_path),
        "git_version": _run(["git", "--version"]).stdout.strip(),
    }
    profile["sha256"] = _sha256_bytes(
        json.dumps(profile, sort_keys=True, separators=(",", ":")).encode(
            "utf-8", "backslashreplace"
        )
    )
    return profile


def _evidence_git_command(repo: Path, *arguments: str) -> list[str]:
    return [
        "git",
        "-c",
        "color.ui=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.ignoreStat=false",
        "-c",
        "core.trustctime=true",
        "-c",
        "core.checkStat=default",
        "-c",
        "core.quotePath=true",
        "-c",
        "diff.external=",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.noprefix=false",
        "-c",
        "diff.srcPrefix=a/",
        "-c",
        "diff.dstPrefix=b/",
        "-c",
        "diff.ignoreSubmodules=none",
        "-c",
        "diff.submodule=short",
        "-C",
        str(repo),
        *arguments,
    ]


def _git_evidence(
    repo: Path, *arguments: str, check: bool = True, text: bool = True
) -> Any:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=check,
        text=text,
        evidence_git=True,
    )
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_evidence_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=False,
        text=True,
        evidence_git=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_diff(repo: Path, *arguments: str, text: bool = True) -> Any:
    return _git_evidence(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--submodule=short",
        "--no-renames",
        "--no-color",
        "--no-indent-heuristic",
        "--diff-algorithm=myers",
        "--unified=3",
        "--inter-hunk-context=0",
        *arguments,
        text=text,
    )


def _git_evidence_path(repo: Path, option: str) -> Path:
    raw = Path(_git_evidence(repo, "rev-parse", option))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _dirty_initialized_submodules(repo: Path) -> list[dict[str, str]]:
    """Return initialized submodules with unbound inner worktree content.

    A parent diff records a dirty submodule only as ``<gitlink>-dirty``.  It
    therefore cannot distinguish two different inner worktree states.  Clean
    submodule HEAD changes are safe because the changed gitlink commit remains
    part of the parent diff; tracked or untracked content below that HEAD is
    not safe evidence and must be rejected.
    """

    output = _git_evidence(
        repo,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
        "--no-renames",
        text=False,
    )
    dirty: list[dict[str, str]] = []
    records = output.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or record[:2] not in {b"1 ", b"2 ", b"u "}:
            continue
        kind = record[:1]
        path_field = {b"1": 8, b"2": 9, b"u": 10}[kind]
        fields = record.split(b" ", path_field)
        if len(fields) <= path_field or len(fields) < 3:
            continue
        submodule = fields[2]
        # Porcelain v2 uses S<c><m><u>: c is a clean pointer/HEAD change,
        # while m/u mean modified/untracked content inside the submodule.
        if (
            len(submodule) == 4
            and submodule.startswith(b"S")
            and (submodule[2:3] != b"." or submodule[3:4] != b".")
        ):
            dirty.append(
                {
                    "path": fields[path_field].decode("utf-8", "replace"),
                    "submodule_status": submodule.decode("ascii", "replace"),
                }
            )
        if kind == b"2" and index < len(records):
            # A rename/copy record is followed by its original path.
            index += 1
    return dirty


def _initialized_submodule_worktrees(repo: Path) -> list[tuple[str, Path]]:
    output = _git_evidence(
        repo, "ls-files", "--stage", "-z", "--cached", "--", text=False
    )
    initialized: list[tuple[str, Path]] = []
    for record in output.split(b"\0"):
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator or not metadata.startswith(b"160000 "):
            continue
        relative = os.fsdecode(path_bytes)
        target = (repo / relative).resolve(strict=False)
        root = _git_evidence_optional(target, "rev-parse", "--show-toplevel")
        if root and Path(root).resolve(strict=False) == target:
            initialized.append((relative, target))
    return initialized


def _hidden_index_entries(repo: Path) -> list[dict[str, str]]:
    """Return tracked paths hidden from ordinary status/diff inspection."""

    output = _git_evidence(repo, "ls-files", "-v", "-z", "--cached", "--", text=False)
    hidden: list[dict[str, str]] = []
    for record in output.split(b"\0"):
        if len(record) < 3 or record[1:2] != b" ":
            continue
        tag = record[:1]
        assume_unchanged = tag.isalpha() and tag == tag.lower()
        skip_worktree = tag.upper() == b"S"
        if assume_unchanged or skip_worktree:
            flags: list[str] = []
            if assume_unchanged:
                flags.append("assume-unchanged")
            if skip_worktree:
                flags.append("skip-worktree")
            hidden.append(
                {
                    "path": record[2:].decode("utf-8", "replace"),
                    "flags": ",".join(flags),
                    "tag": tag.decode("ascii", "replace"),
                }
            )
    return hidden


def _content_filter_entries(
    repo: Path, source: str | None = None
) -> list[dict[str, str]]:
    """Return tracked paths whose Git attributes select a content filter."""

    if source:
        tracked_raw = _git_evidence(
            repo, "ls-tree", "-r", "-z", "--name-only", source, text=False
        )
    else:
        tracked_raw = _git_evidence(
            repo, "ls-files", "-z", "--cached", "--", text=False
        )
    tracked = [os.fsdecode(item) for item in tracked_raw.split(b"\0") if item]
    filtered: list[dict[str, str]] = []
    for offset in range(0, len(tracked), 128):
        batch = tracked[offset : offset + 128]
        source_arguments = ["--source", source] if source else []
        output = _git_evidence(
            repo,
            "check-attr",
            "-z",
            *source_arguments,
            "filter",
            "--",
            *batch,
            text=False,
        )
        fields = output.split(b"\0")
        for index in range(0, len(fields) - 2, 3):
            path_bytes, attribute, value = fields[index : index + 3]
            if attribute != b"filter" or value in {b"unspecified", b"unset"}:
                continue
            filtered.append(
                {
                    "path": path_bytes.decode("utf-8", "replace"),
                    "filter": value.decode("utf-8", "replace"),
                }
            )
    return filtered


def _assert_tree_checkout_supported(repo: Path, source: str) -> None:
    filtered = _content_filter_entries(repo, source)
    if filtered:
        raise FlowError(
            "CONTENT_FILTER_UNSUPPORTED",
            "target tree uses Git content filters that can execute during checkout",
            details={
                "repository": str(repo.resolve(strict=False)),
                "source": source,
                "entries": filtered,
                "hint": "remove filter attributes before materializing a worktree",
            },
        )


def _assert_no_hidden_index_entries(repo: Path) -> None:
    hidden = _hidden_index_entries(repo)
    if hidden:
        raise FlowError(
            "HIDDEN_INDEX_FLAGS",
            "tracked paths hidden by index flags cannot be used as complete evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "entries": hidden,
                "hint": (
                    "clear assume-unchanged/skip-worktree flags and use a full "
                    "non-sparse checkout before continuing"
                ),
            },
        )


def _prefixed_evidence_path(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def _assert_evidence_supported(repo: Path) -> None:
    evidence_root = repo.resolve(strict=True)
    visited: set[Path] = set()

    def visit(current: Path, prefix: str) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        hidden = _hidden_index_entries(resolved)
        if hidden:
            for entry in hidden:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "HIDDEN_INDEX_FLAGS",
                "tracked paths hidden by index flags cannot be used as complete evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": hidden,
                    "hint": (
                        "clear assume-unchanged/skip-worktree flags in every "
                        "initialized submodule and use a full non-sparse checkout"
                    ),
                },
            )
        filtered = _content_filter_entries(resolved)
        if filtered:
            for entry in filtered:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "CONTENT_FILTER_UNSUPPORTED",
                "Git clean/process filters cannot be used as complete byte evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": filtered,
                    "hint": "remove filter attributes before continuing",
                },
            )
        children = _initialized_submodule_worktrees(resolved)
        for relative, child in children:
            visit(child, _prefixed_evidence_path(prefix, relative))
        dirty = _dirty_initialized_submodules(resolved)
        if dirty:
            for entry in dirty:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "DIRTY_SUBMODULE_UNSUPPORTED",
                "dirty initialized submodules cannot be represented by complete review evidence",
                details={
                    "repository": str(evidence_root),
                    "submodules": dirty,
                    "hint": (
                        "commit each submodule change and update its parent gitlink, "
                        "or configure the submodule as a separate task repository"
                    ),
                },
            )

    visit(evidence_root, "")


def _assert_no_dirty_submodules(repo: Path) -> None:
    dirty = _dirty_initialized_submodules(repo)
    if dirty:
        raise FlowError(
            "DIRTY_SUBMODULE_UNSUPPORTED",
            "dirty initialized submodules cannot be represented by complete review evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "submodules": dirty,
                "hint": (
                    "commit each submodule change and update its parent gitlink, "
                    "or configure the submodule as a separate task repository"
                ),
            },
        )


def _tracked_worktree_manifest(
    repo: Path, capability_profile: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Bind raw tracked filesystem bytes/types/modes, including submodules."""

    manifest: list[dict[str, Any]] = []
    visited: set[Path] = set()
    profile = capability_profile or _git_capability_profile(repo)
    case_aliases: dict[str, str] = {}

    def visit(current: Path, prefix: bytes) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        output = _git_evidence(
            resolved, "ls-files", "--stage", "-z", "--cached", "--", text=False
        )
        for record in output.split(b"\0"):
            if not record:
                continue
            metadata, separator, path_bytes = record.partition(b"\t")
            fields = metadata.split(b" ")
            if not separator or len(fields) != 3:
                raise FlowError(
                    "GIT_EVIDENCE_MALFORMED",
                    "git ls-files returned a malformed tracked-entry record",
                    details={
                        "repository": str(resolved),
                        "record_hex": record.hex(),
                    },
                )
            index_mode, index_oid, stage = fields
            full_path = prefix + (b"/" if prefix else b"") + path_bytes
            display_path = os.fsdecode(full_path)
            filesystem = profile.get("filesystem") or {}
            case_aliasing = bool(
                profile.get("core_ignore_case")
                or not filesystem.get("case_sensitive", True)
            )
            unicode_aliasing = not filesystem.get(
                "unicode_normalization_distinct", True
            )
            if case_aliasing or unicode_aliasing:
                alias = (
                    unicodedata.normalize("NFC", display_path)
                    if unicode_aliasing
                    else display_path
                )
                if case_aliasing:
                    alias = alias.casefold()
                previous = case_aliases.get(alias)
                if previous is not None and previous != full_path.hex():
                    raise FlowError(
                        "CASE_COLLISION_UNSUPPORTED",
                        "tracked paths collide on the verified worktree filesystem",
                        details={
                            "repository": str(repo),
                            "first_path_bytes_hex": previous,
                            "second_path_bytes_hex": full_path.hex(),
                            "case_aliasing": case_aliasing,
                            "unicode_aliasing": unicode_aliasing,
                        },
                    )
                case_aliases[alias] = full_path.hex()
            target = resolved / os.fsdecode(path_bytes)
            item: dict[str, Any] = {
                "path": full_path.decode("utf-8", "replace"),
                "path_bytes_hex": full_path.hex(),
                "index_mode": index_mode.decode("ascii", "replace"),
                "index_oid": index_oid.decode("ascii", "replace"),
                "index_stage": stage.decode("ascii", "replace"),
            }
            try:
                metadata_value = target.lstat()
            except FileNotFoundError:
                item["worktree_type"] = "missing"
            else:
                item["worktree_mode"] = format(metadata_value.st_mode & 0o177777, "06o")
                item["size"] = metadata_value.st_size
                if stat.S_ISLNK(metadata_value.st_mode):
                    target_bytes = os.fsencode(os.readlink(target))
                    item["worktree_type"] = "symlink"
                    item["sha256"] = _sha256_bytes(target_bytes)
                elif stat.S_ISREG(metadata_value.st_mode):
                    item["worktree_type"] = "file"
                    item["sha256"] = _sha256_file(target)
                elif stat.S_ISDIR(metadata_value.st_mode):
                    item["worktree_type"] = "directory"
                else:
                    item["worktree_type"] = "other"
            manifest.append(item)
        for relative, child in _initialized_submodule_worktrees(resolved):
            relative_bytes = os.fsencode(relative)
            child_prefix = prefix + (b"/" if prefix else b"") + relative_bytes
            visit(child, child_prefix)

    visit(repo, b"")
    manifest.sort(
        key=lambda item: (item["path_bytes_hex"], item["index_stage"], item["index_oid"])
    )
    return manifest


def _canonical_repo(path_value: str) -> Path:
    supplied = Path(path_value).expanduser().resolve(strict=False)
    root = _git_optional(supplied, "rev-parse", "--show-toplevel")
    if not root:
        raise FlowError(
            "NOT_A_GIT_REPOSITORY",
            f"not a Git repository: {supplied}",
            details={"path": str(supplied)},
        )
    return Path(root).resolve(strict=True)


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return result or "repo"


def _repo_id(root: Path, existing: set[str]) -> str:
    base = _slug(root.name)[:40]
    candidate = base
    if candidate in existing:
        digest = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:8]
        candidate = f"{base}-{digest}"
    return candidate


def _split_lines(value: str | None) -> list[str]:
    if not value:
        return []
    return [line for line in value.splitlines() if line]


def _selector_is_path_like(selector: str) -> bool:
    return bool(
        "/" in selector
        or "\\" in selector
        or selector.startswith((".", "~"))
        or re.match(r"^[A-Za-z]:", selector)
        or selector.startswith(("//", "\\\\"))
    )


def _selector_path(selector: str) -> Path | None:
    windows_drive = bool(re.match(r"^[A-Za-z]:[\\/]", selector))
    windows_unc = selector.startswith("\\\\")
    if os.name != "nt" and (windows_drive or windows_unc):
        # A foreign Windows absolute path is still path-like, and therefore
        # must never fall back to a basename selector on a POSIX host.
        return None
    normalized = selector
    if os.name != "nt" and "\\" in normalized:
        normalized = normalized.replace("\\", "/")
    try:
        return Path(normalized).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "repository selector path could not be normalized",
            details={"selector": selector, "error": str(exc)},
        ) from exc


def _repo_by_selector(state_value: dict[str, Any], selectors: Sequence[str] | None) -> list[dict[str, Any]]:
    repositories = state_value.get("repositories", [])
    if not selectors:
        return repositories
    selected: list[dict[str, Any]] = []
    for selector in selectors:
        if _selector_is_path_like(selector):
            normalized_path = _selector_path(selector)
            matches = []
            if normalized_path is not None:
                for repo in repositories:
                    recorded_paths = {
                        str(value)
                        for value in (
                            repo.get("path"),
                            repo.get("canonical_path"),
                        )
                        if value
                    }
                    if any(
                        _same_path(normalized_path, Path(value))
                        for value in recorded_paths
                    ):
                        matches.append(repo)
        else:
            matches = [
                repo
                for repo in repositories
                if selector == repo.get("id")
                or selector == Path(str(repo.get("path", ""))).name
            ]
        matches = list(
            {
                str(repo.get("id")): repo
                for repo in matches
            }.values()
        )
        if len(matches) != 1:
            raise FlowError(
                "REPOSITORY_NOT_FOUND" if not matches else "AMBIGUOUS_REPOSITORY",
                f"repository selector must match exactly one configured repository: {selector}",
                details={"selector": selector, "matches": [repo.get("id") for repo in matches]},
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def _assert_status(state_value: dict[str, Any], allowed: set[str], command: str) -> None:
    current = state_value.get("status")
    if current not in allowed:
        raise FlowError(
            "INVALID_STATE",
            f"{command} is not allowed while task is {current}",
            details={"status": current, "allowed": sorted(allowed), "command": command},
        )


def _flow(state_value: dict[str, Any]) -> str:
    value = state_value.get("flow")
    return value if value in FLOW_MODES else DEFAULT_FLOW


def _workspace_strategy(state_value: dict[str, Any]) -> str:
    workspace = state_value.get("workspace")
    value = workspace.get("strategy") if isinstance(workspace, dict) else None
    if value in WORKSPACE_STRATEGIES:
        return value
    return "in-place" if _flow(state_value) == "lite" else "worktree"


def _workflow_progress(state_value: dict[str, Any]) -> dict[str, Any]:
    flow = _flow(state_value)
    ordered = LITE_ORDERED_STATES if flow == "lite" else ORDERED_STATES
    status = str(state_value.get("status") or "INTAKE")
    progress_status = status
    resume_state: dict[str, str] | None = None
    if status == "BLOCKED":
        blocked = state_value.get("blocked")
        candidate = (
            blocked.get("from_status")
            if isinstance(blocked, dict)
            else None
        )
        if candidate in ordered:
            progress_status = candidate
            resume_state = {
                "id": candidate,
                "name": STATE_NAMES_ZH[candidate],
            }
    if progress_status in ordered:
        index = ordered.index(progress_status)
        remaining_ids = ordered[index + 1 :]
    else:
        remaining_ids = []
    strategy = _workspace_strategy(state_value)
    return {
        "flow": {
            "id": flow,
            "name": FLOW_NAMES_ZH[flow],
        },
        "workspace_strategy": {
            "id": strategy,
            "name": WORKSPACE_STRATEGY_NAMES_ZH[strategy],
        },
        "current": {
            "id": status,
            "name": STATE_NAMES_ZH.get(status, status),
        },
        "resume_state": resume_state,
        "remaining": [
            {"id": state, "name": STATE_NAMES_ZH[state]}
            for state in remaining_ids
        ],
    }


def _assert_flow(state_value: dict[str, Any], required: str, command: str) -> None:
    actual = _flow(state_value)
    if actual != required:
        raise FlowError(
            "FLOW_MISMATCH",
            f"{command} is not part of the {actual} flow",
            details={"flow": actual, "required_flow": required, "command": command},
        )


def _operation_state(repo: Path) -> dict[str, bool]:
    git_dir_text = _git(repo, "rev-parse", "--absolute-git-dir")
    git_dir = Path(git_dir_text)
    return {
        "merge": (git_dir / "MERGE_HEAD").exists(),
        "rebase": (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists(),
        "cherry_pick": (git_dir / "CHERRY_PICK_HEAD").exists(),
        "revert": (git_dir / "REVERT_HEAD").exists(),
        "bisect": (git_dir / "BISECT_LOG").exists(),
        "sequencer": (git_dir / "sequencer").exists(),
    }


def _ref_exists(repo: Path, ref: str) -> bool:
    result = _run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref], check=False)
    return result.returncode == 0


def _default_remote(repo: Path, branch: str | None) -> str | None:
    if branch:
        configured = _git_optional(repo, "config", "--get", f"branch.{branch}.remote")
        if configured and configured != ".":
            return configured
    for key in ("remote.pushDefault", "checkout.defaultRemote"):
        configured = _git_optional(repo, "config", "--get", key)
        if configured:
            return configured
    remotes = _split_lines(_git_optional(repo, "remote"))
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else None


def _default_base(repo: Path, remote: str | None, branch: str | None, protected: Sequence[str]) -> str | None:
    if remote:
        symbolic = _git_optional(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
        if symbolic and symbolic.startswith(f"{remote}/"):
            return symbolic[len(remote) + 1 :]
    for candidate in protected:
        if remote and _ref_exists(repo, f"refs/remotes/{remote}/{candidate}"):
            return candidate
        if _ref_exists(repo, f"refs/heads/{candidate}"):
            return candidate
    # A feature branch is not a safe implicit baseline.  Repositories with a
    # non-standard default branch must expose remote/HEAD or pass --base.
    return branch if branch in protected else None


def _remote_url(repo: Path, remote: str | None) -> str | None:
    if not remote:
        return None
    return _git_optional(repo, "remote", "get-url", "--", remote)


def _approved_fetch_refspec(remote: str | None, base_branch: str | None) -> str | None:
    if not remote or not base_branch:
        return None
    return f"+refs/heads/{base_branch}:refs/remotes/{remote}/{base_branch}"


def _baseline_source_ref(remote: str | None, base_branch: str | None) -> str | None:
    if not base_branch:
        return None
    return (
        f"refs/remotes/{remote}/{base_branch}"
        if remote
        else f"refs/heads/{base_branch}"
    )


def _preflight_repo(
    repo_record: dict[str, Any],
    remote_override: str | None,
    base_override: str | None,
    *,
    capture_fingerprint: bool = True,
) -> dict[str, Any]:
    repo = Path(repo_record["path"])
    _assert_evidence_supported(repo)
    repository_root = Path(
        _git_evidence(repo, "rev-parse", "--show-toplevel")
    ).resolve(strict=True)
    git_dir = _git_evidence_path(repo, "--git-dir")
    git_common_dir = _git_evidence_path(repo, "--git-common-dir")
    branch = _git_optional(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    head_sha = _git(repo, "rev-parse", "HEAD")
    remote = remote_override or _default_remote(repo, branch)
    base_branch = base_override or _default_base(
        repo, remote, branch, repo_record.get("protected_branches", DEFAULT_PROTECTED_BRANCHES)
    )
    if remote and (
        remote.startswith("-")
        or _run(
            ["git", "check-ref-format", f"refs/remotes/{remote}/base"],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_REMOTE",
            "remote name is not safe for deterministic fetch operations",
            details={"repository": str(repo), "remote": remote},
        )
    if base_branch and (
        _run(
            ["git", "check-ref-format", "--branch", base_branch],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_BASE_BRANCH",
            "base branch name is invalid",
            details={"repository": str(repo), "base_branch": base_branch},
        )
    base_candidate_ref = _baseline_source_ref(remote, base_branch)
    base_candidate_sha = (
        _git_optional(
            repo, "rev-parse", "--verify", f"{base_candidate_ref}^{{commit}}"
        )
        if base_candidate_ref
        else None
    )
    staged_raw = _git_diff(
        repo,
        "--cached",
        "--name-only",
        "-z",
        "--",
        text=False,
    )
    unstaged_raw = _git_diff(
        repo,
        "--name-only",
        "-z",
        "--",
        text=False,
    )
    untracked_raw = _git_evidence(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    conflicts_raw = _git_diff(
        repo,
        "--name-only",
        "--diff-filter=U",
        "-z",
        "--",
        text=False,
    )
    staged = [
        os.fsdecode(item) for item in staged_raw.split(b"\0") if item
    ]
    unstaged = [
        os.fsdecode(item) for item in unstaged_raw.split(b"\0") if item
    ]
    untracked = [
        os.fsdecode(item) for item in untracked_raw.split(b"\0") if item
    ]
    conflicts = [
        os.fsdecode(item) for item in conflicts_raw.split(b"\0") if item
    ]
    operations = _operation_state(repo)
    blockers: list[str] = []
    if branch is None:
        blockers.append("detached_head")
    if conflicts:
        blockers.append("unmerged_conflicts")
    blockers.extend(f"operation_in_progress:{name}" for name, active in operations.items() if active)
    if not base_branch:
        blockers.append("base_branch_unresolved")
    if remote and remote not in _split_lines(_git_optional(repo, "remote")):
        blockers.append("remote_not_found")
    evidence: dict[str, Any] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "checked_at": utc_now(),
        "repository_root": str(repository_root),
        "repository_path_identity": _serializable_path_identity(repo),
        "repository_root_identity": _serializable_path_identity(
            repository_root
        ),
        "git_dir": str(git_dir),
        "git_dir_identity": _serializable_path_identity(git_dir),
        "git_common_dir": str(git_common_dir),
        "git_common_dir_identity": _serializable_path_identity(
            git_common_dir
        ),
        "branch": branch,
        "head_sha": head_sha,
        "remote": remote,
        "remote_url": _remote_url(repo, remote),
        "base_branch": base_branch,
        "base_candidate_ref": base_candidate_ref,
        "base_candidate_sha": base_candidate_sha,
        "fetch_refspec": _approved_fetch_refspec(remote, base_branch),
        "staged": staged,
        "staged_paths_sha256": _sha256_bytes(staged_raw),
        "unstaged": unstaged,
        "unstaged_paths_sha256": _sha256_bytes(unstaged_raw),
        "untracked": untracked,
        "untracked_paths_sha256": _sha256_bytes(untracked_raw),
        "conflicts": conflicts,
        "conflict_paths_sha256": _sha256_bytes(conflicts_raw),
        "operations": operations,
        "dirty": bool(staged or unstaged or untracked or conflicts),
        "blockers": blockers,
        "ready": not blockers,
        "evidence_complete": capture_fingerprint,
        "capture_phase": (
            "confirm" if capture_fingerprint else "preview"
        ),
    }
    if capture_fingerprint:
        fingerprint = _fingerprint_repo(repo)
        evidence.update(
            {
                "worktree_fingerprint_sha256": fingerprint["sha256"],
                "capability_profile": fingerprint["capability_profile"],
                "capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
                "tracked_worktree_manifest_sha256": fingerprint[
                    "tracked_worktree_manifest_sha256"
                ],
            }
        )
    return evidence


def _baseline_ref(repo: Path, remote: str | None, base_branch: str) -> tuple[str, str]:
    if remote:
        # Never label a local branch as a remote baseline.  If the tracking
        # ref is absent, the caller must explicitly fetch (behind its gate) or
        # fix the remote rather than silently pinning stale local state.
        candidates = [f"refs/remotes/{remote}/{base_branch}"]
    else:
        candidates = [f"refs/heads/{base_branch}", base_branch]
    for candidate in candidates:
        sha = _git_optional(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}")
        if sha:
            return candidate, sha
    raise FlowError(
        "BASE_REF_NOT_FOUND",
        f"could not resolve base branch {base_branch}",
        details={
            "repository": str(repo),
            "remote": remote,
            "base_branch": base_branch,
            "required_ref": f"refs/remotes/{remote}/{base_branch}" if remote else f"refs/heads/{base_branch}",
            "hint": "approve baseline-fetch and rerun baseline --fetch" if remote else "pass --base during preflight",
        },
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_artifact(path: Path) -> dict[str, Any]:
    """Hash a file or a directory without following directory symlinks.

    Directory hashes are a canonical JSONL manifest over sorted relative
    paths.  Entries bind path, type, file content, or symlink target; empty
    directories therefore remain significant too.
    """

    if path.is_file():
        size = path.stat().st_size
        return {
            "artifact_type": "file",
            "sha256": _sha256_file(path),
            "size": size,
            "file_count": 1,
            "total_size": size,
        }
    if not path.is_dir():
        raise FlowError("INVALID_ARTIFACT", f"artifact must be a regular file or directory: {path}")

    entries: list[dict[str, Any]] = [{"path": ".", "type": "directory"}]
    file_count = 0
    total_size = 0

    def visit(directory: Path, relative_directory: Path) -> None:
        nonlocal file_count, total_size
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise FlowError(
                "ARTIFACT_READ_FAILED",
                f"could not enumerate artifact directory: {directory}",
                details={"path": str(directory), "error": str(exc)},
            ) from exc
        for child in children:
            relative = (relative_directory / child.name).as_posix()
            try:
                if child.is_symlink():
                    target = os.readlink(child.path)
                    entries.append({"path": relative, "type": "symlink", "target": target})
                    file_count += 1
                elif child.is_dir(follow_symlinks=False):
                    entries.append({"path": relative, "type": "directory"})
                    visit(Path(child.path), relative_directory / child.name)
                elif child.is_file(follow_symlinks=False):
                    child_path = Path(child.path)
                    size = child.stat(follow_symlinks=False).st_size
                    entries.append(
                        {
                            "path": relative,
                            "type": "file",
                            "size": size,
                            "sha256": _sha256_file(child_path),
                        }
                    )
                    file_count += 1
                    total_size += size
                else:
                    entries.append({"path": relative, "type": "other"})
                    file_count += 1
            except OSError as exc:
                raise FlowError(
                    "ARTIFACT_READ_FAILED",
                    f"could not read artifact entry: {child.path}",
                    details={"path": child.path, "error": str(exc)},
                ) from exc

    visit(path, Path())
    manifest = b"".join(
        (
            json.dumps(
                entry,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8", "backslashreplace")
        for entry in entries
    )
    return {
        "artifact_type": "directory",
        "sha256": _sha256_bytes(manifest),
        "size": total_size,
        "file_count": file_count,
        "total_size": total_size,
        "manifest_entry_count": len(entries),
    }


def _parse_review_report_verdict(path: Path) -> str:
    if not path.is_file():
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be a UTF-8 text file containing one 'Verdict: VALUE' line",
            details={"path": str(path)},
        )
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be readable UTF-8 text",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    nonempty_lines = [line for line in body.splitlines() if line.strip()]
    first_match = (
        REVIEW_VERDICT_RE.fullmatch(nonempty_lines[0]) if nonempty_lines else None
    )
    verdict_lines = [
        line for line in body.splitlines() if line.lstrip().startswith("Verdict:")
    ]
    if first_match is None or len(verdict_lines) != 1:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "the first non-empty review-report line must be exactly 'Verdict: PASS|CONDITIONAL|FAIL', with no second Verdict line",
            details={
                "path": str(path),
                "verdict_field_count": len(verdict_lines),
                "first_nonempty_line": nonempty_lines[0] if nonempty_lines else None,
            },
        )
    return first_match.group(1)


def _latest_artifact(state_value: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (artifact for artifact in reversed(state_value.get("artifacts", [])) if artifact.get("kind") == kind),
        None,
    )


def _assert_artifact_unchanged(artifact: dict[str, Any]) -> None:
    _require_current_evidence(artifact, "artifact")
    path_value = artifact.get("path")
    if not path_value:
        raise FlowError(
            "ARTIFACT_CHANGED",
            "recorded artifact has no verifiable path",
            details={"artifact_id": artifact.get("artifact_id")},
        )
    path = Path(path_value)
    if not _recorded_path_matches(
        artifact.get("path_identity"), path_value, path
    ):
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact path identity changed: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
            },
        )
    try:
        current = _hash_artifact(path)
    except (FlowError, OSError) as exc:
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact is missing or unreadable: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "error": str(exc),
            },
        ) from exc
    if current.get("sha256") != artifact.get("sha256"):
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact changed on disk: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "current_sha256": current.get("sha256"),
            },
        )


def _require_gate(state_value: dict[str, Any], gate: str) -> dict[str, Any]:
    approval = state_value.get("approvals", {}).get(gate)
    if not approval:
        raise FlowError(
            "APPROVAL_REQUIRED",
            f"the {gate} gate must be approved first",
            details={"gate": gate},
        )
    return approval


def _require_gate_for_latest_artifact(
    state_value: dict[str, Any], gate: str, artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _latest_artifact(state_value, artifact_kind)
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            f"the {gate} gate requires a recorded {artifact_kind} artifact",
            details={"gate": gate, "artifact_kind": artifact_kind},
        )
    _assert_artifact_unchanged(artifact)
    approval = _require_gate(state_value, gate)
    if approval.get("artifact_sha256") != artifact.get("sha256"):
        raise FlowError(
            "STALE_APPROVAL",
            f"the {gate} approval must bind the latest {artifact_kind} artifact",
            details={
                "gate": gate,
                "artifact_kind": artifact_kind,
                "expected_sha256": artifact.get("sha256"),
                "approved_sha256": approval.get("artifact_sha256"),
            },
        )
    return approval, artifact


def _require_current_impact(state_value: dict[str, Any]) -> dict[str, Any]:
    artifact = _latest_artifact(state_value, "impact")
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            "route selection requires a current impact artifact",
            details={"artifact_kind": "impact"},
        )
    _assert_artifact_unchanged(artifact)
    expected = _index_provenance_sha256(state_value)
    metadata = artifact.get("metadata") or {}
    recorded = metadata.get("index_provenance_sha256")
    expected_generation = int(state_value.get("impact_generation", 0))
    recorded_generation = metadata.get("impact_generation")
    if recorded != expected or recorded_generation != expected_generation:
        raise FlowError(
            "STALE_IMPACT",
            "latest impact artifact does not describe the current impact epoch and all-repository index provenance",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "expected_index_provenance_sha256": expected,
                "recorded_index_provenance_sha256": recorded,
                "expected_impact_generation": expected_generation,
                "recorded_impact_generation": recorded_generation,
            },
        )
    return artifact


def _require_current_route_selection(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    impact = _require_current_impact(state_value)
    route = state_value.get("route")
    if not isinstance(route, dict) or route.get("value") not in {"direct", "openspec"}:
        raise FlowError("ROUTE_REQUIRED", "a route must be selected for the current impact")
    if (
        route.get("impact_artifact_id") != impact.get("artifact_id")
        or route.get("impact_sha256") != impact.get("sha256")
        or route.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or route.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
    ):
        raise FlowError(
            "STALE_ROUTE_SELECTION",
            "route selection is not bound to the latest current impact artifact",
        )
    return route, impact


def _require_route_gate(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, impact = _require_current_route_selection(state_value)
    approval, approved_impact = _require_gate_for_latest_artifact(
        state_value, "route", "impact"
    )
    if (
        approval.get("artifact_id") != impact.get("artifact_id")
        or approval.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or approval.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "route approval is not bound to the current impact record and index provenance",
        )
    return approval, approved_impact


def _latest_review_snapshot(state_value: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = state_value.get("review_snapshots", [])
    return snapshots[-1] if snapshots else None


def _require_review_report_for_latest_snapshot(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _latest_review_snapshot(state_value)
    if not snapshot:
        raise FlowError("CURRENT_REVIEW_REQUIRED", "a review snapshot is required")
    report = _latest_artifact(state_value, "review-report")
    if not report:
        raise FlowError("ARTIFACT_REQUIRED", "the review gate requires a review-report artifact")
    _assert_artifact_unchanged(report)
    body_verdict = _parse_review_report_verdict(Path(report["path"]))
    metadata_verdict = (report.get("metadata") or {}).get("verdict")
    if body_verdict != metadata_verdict:
        raise FlowError(
            "REVIEW_VERDICT_MISMATCH",
            "review report Verdict field no longer matches its recorded metadata",
            details={
                "body_verdict": body_verdict,
                "metadata_verdict": metadata_verdict,
                "path": report.get("path"),
            },
        )
    bound_snapshot = (report.get("metadata") or {}).get("review_snapshot_sha256")
    if bound_snapshot != snapshot.get("sha256"):
        raise FlowError(
            "STALE_REVIEW_REPORT",
            "the latest review report is not bound to the latest review snapshot",
            details={
                "report_sha256": report.get("sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "bound_review_snapshot_sha256": bound_snapshot,
            },
        )
    return report, snapshot


def _require_review_gate(state_value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report, snapshot = _require_review_report_for_latest_snapshot(state_value)
    verdict = (report.get("metadata") or {}).get("verdict")
    if verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
        raise FlowError(
            "INVALID_REVIEW_VERDICT",
            "latest review report has no valid structured verdict",
            details={"verdict": verdict},
        )
    if verdict == "FAIL":
        raise FlowError(
            "REVIEW_VERDICT_FAILED",
            "a FAIL review report cannot pass the final review gate",
        )
    approval = _require_gate(state_value, "review")
    if (
        approval.get("artifact_sha256") != report.get("sha256")
        or approval.get("review_snapshot_sha256") != snapshot.get("sha256")
        or approval.get("review_verdict") != verdict
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "the review approval must bind the latest report and review snapshot",
            details={
                "expected_report_sha256": report.get("sha256"),
                "approved_report_sha256": approval.get("artifact_sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "approved_review_snapshot_sha256": approval.get("review_snapshot_sha256"),
                "expected_verdict": verdict,
                "approved_verdict": approval.get("review_verdict"),
            },
        )
    if verdict == "CONDITIONAL" and approval.get("conditional_accepted") is not True:
        raise FlowError(
            "CONDITIONAL_ACCEPTANCE_REQUIRED",
            "the CONDITIONAL review verdict lacks explicit acceptance",
        )
    return approval, report


def _fingerprint_repo_once(
    repo: Path,
    *,
    filesystem_capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_repo = repo.resolve(strict=True)
    capability_profile = _git_capability_profile(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    _assert_evidence_supported(repo)
    head = _git_evidence(repo, "rev-parse", "HEAD")
    cached = _git_diff(
        repo, "--binary", "--full-index", "--cached", "--", text=False
    )
    unstaged = _git_diff(repo, "--binary", "--full-index", "--", text=False)
    untracked_output = _git_evidence(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    untracked_paths = [item for item in untracked_output.split(b"\0") if item]
    untracked: list[dict[str, Any]] = []
    for relative_bytes in sorted(untracked_paths):
        relative = relative_bytes.decode("utf-8", "replace")
        target = repo / os.fsdecode(relative_bytes)
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            raise FlowError(
                "WORKTREE_CHANGED",
                f"untracked path disappeared while creating a snapshot: {relative}",
                details={"repository": str(repo), "path": relative},
            )
        if stat.S_ISLNK(metadata.st_mode):
            content_hash = _sha256_bytes(os.readlink(target).encode("utf-8", "surrogateescape"))
            item_type = "symlink"
        elif stat.S_ISREG(metadata.st_mode):
            content_hash = _sha256_file(target)
            item_type = "file"
        else:
            raise FlowError(
                "UNTRACKED_TYPE_UNSUPPORTED",
                "untracked review evidence supports only regular files and symlinks",
                details={
                    "repository": str(repo),
                    "path": relative,
                    "mode": format(metadata.st_mode & 0o177777, "06o"),
                },
            )
        untracked.append(
            {
                "path": relative,
                "path_bytes_hex": relative_bytes.hex(),
                "type": item_type,
                "size": metadata.st_size,
                "sha256": content_hash,
            }
        )
    tracked_worktree = _tracked_worktree_manifest(repo, capability_profile)
    payload = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(resolved_repo),
        "root": _git_evidence(repo, "rev-parse", "--show-toplevel"),
        "branch": _git_evidence_optional(
            repo, "symbolic-ref", "--quiet", "--short", "HEAD"
        ),
        "git_dir": str(_git_evidence_path(repo, "--git-dir")),
        "git_common_dir": str(_git_evidence_path(repo, "--git-common-dir")),
        "linked_worktree": _git_evidence_path(
            repo, "--git-dir"
        )
        != _git_evidence_path(repo, "--git-common-dir"),
        "head_sha": head,
        "cached_sha256": _sha256_bytes(cached),
        "unstaged_sha256": _sha256_bytes(unstaged),
        "capability_profile": capability_profile,
        "capability_profile_sha256": capability_profile["sha256"],
        "tracked_worktree": tracked_worktree,
        "tracked_worktree_manifest_sha256": _sha256_bytes(
            json.dumps(
                tracked_worktree, sort_keys=True, separators=(",", ":")
            ).encode("utf-8", "backslashreplace")
        ),
        "untracked": untracked,
    }
    payload["sha256"] = _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8", "backslashreplace"
        )
    )
    return payload


def _fingerprint_repo(repo: Path) -> dict[str, Any]:
    """Return a complete fingerprint only after two identical observations."""

    # Filesystem capabilities are stable for the duration of one capture.
    # Probe them once, while still rebuilding the effective Git profile and
    # all repository byte evidence independently in both observations.
    filesystem_capabilities = _probe_worktree_capabilities(
        repo.resolve(strict=True)
    )
    first = _fingerprint_repo_once(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    second = _fingerprint_repo_once(
        repo,
        filesystem_capabilities=filesystem_capabilities,
    )
    if first.get("sha256") != second.get("sha256"):
        raise FlowError(
            "WORKTREE_CHANGED",
            "repository changed while complete byte evidence was being captured",
            details={
                "repository": str(repo.resolve(strict=False)),
                "first_sha256": first.get("sha256"),
                "second_sha256": second.get("sha256"),
            },
        )
    return second


def _untracked_filesystem_path(item: dict[str, Any]) -> str:
    raw_hex = item.get("path_bytes_hex")
    if isinstance(raw_hex, str):
        try:
            return os.fsdecode(bytes.fromhex(raw_hex))
        except ValueError as exc:
            raise FlowError(
                "REVIEW_SNAPSHOT_INVALID",
                "untracked evidence contains an invalid raw path encoding",
                details={"path": item.get("path"), "path_bytes_hex": raw_hex},
            ) from exc
    # Compatibility for evidence recorded before raw path bytes were bound.
    return str(item.get("path", ""))


def _validate_untracked_archive(
    archive_path: Path, manifest: Sequence[dict[str, Any]]
) -> None:
    """Prove that archived untracked entries match their byte manifest."""

    try:
        with tarfile.open(archive_path, mode="r") as archive:
            members = {
                member.name.rstrip("/"): member
                for member in archive.getmembers()
            }
            for item in manifest:
                relative = _untracked_filesystem_path(item).replace(
                    os.sep, "/"
                )
                member = members.get(relative.rstrip("/"))
                if member is None:
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        "untracked archive is missing a manifest entry",
                        details={
                            "archive": str(archive_path),
                            "path": item.get("path"),
                        },
                    )
                item_type = item.get("type")
                type_matches = (
                    (item_type == "file" and member.isfile())
                    or (item_type == "symlink" and member.issym())
                    or (
                        item_type == "other"
                        and not member.isfile()
                        and not member.issym()
                    )
                )
                if item_type == "file":
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise FlowError(
                            "REVIEW_SNAPSHOT_CHANGED",
                            "untracked regular file has no archived bytes",
                            details={
                                "archive": str(archive_path),
                                "path": item.get("path"),
                            },
                        )
                    digest = hashlib.sha256()
                    with extracted:
                        for chunk in iter(
                            lambda: extracted.read(1024 * 1024), b""
                        ):
                            digest.update(chunk)
                    actual_sha = digest.hexdigest()
                elif item_type == "symlink":
                    actual_sha = (
                        _sha256_bytes(os.fsencode(member.linkname))
                        if member.issym()
                        else None
                    )
                else:
                    actual_sha = None
                if (
                    not type_matches
                    or actual_sha != item.get("sha256")
                    or (
                        item_type == "file"
                        and member.size != item.get("size")
                    )
                ):
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        "untracked archive bytes differ from the manifest",
                        details={
                            "archive": str(archive_path),
                            "path": item.get("path"),
                            "expected_sha256": item.get("sha256"),
                            "actual_sha256": actual_sha,
                        },
                    )
    except FlowError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FlowError(
            "REVIEW_SNAPSHOT_INVALID",
            "untracked review archive could not be verified",
            details={"archive": str(archive_path), "error": str(exc)},
        ) from exc


def _working_path(repo: dict[str, Any]) -> Path:
    workspace = repo.get("workspace")
    if isinstance(workspace, dict) and workspace.get("ready") and workspace.get("path"):
        return Path(workspace["path"])
    return Path(repo["path"])


def _copy_state(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _recommended_index_name(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> str:
    prefix = f"devflow-{state_value['task_id']}-{repo['id']}"
    if role == "baseline":
        return f"{prefix}-baseline"
    if role == "workspace":
        generation = int(
            (state_value.get("workspace") or {}).get("generation", 0)
        )
        return f"{prefix}-workspace-r{generation}"
    raise ValueError(f"unknown index role: {role}")


def _index_role_for_status(state_value: dict[str, Any]) -> str | None:
    if _flow(state_value) == "lite":
        # Lite tasks record no controller-bound indexes; ad-hoc codebase-memory
        # use stays outside the evidence chain.
        return None
    status = state_value.get("status")
    if status == "BLOCKED":
        status = (state_value.get("blocked") or {}).get("from_status")
    if status in BASELINE_INDEX_STATES:
        return "baseline"
    if status in WORKSPACE_INDEX_STATES:
        return "workspace"
    return None


def _index_role_summary(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> dict[str, Any]:
    record = repo.get("index" if role == "baseline" else "workspace_index")
    record = record if isinstance(record, dict) else {}
    summary: dict[str, Any] = {
        "role": role,
        "recorded_project": record.get("index_id"),
        "recommended_project": _recommended_index_name(
            state_value, repo, role
        ),
        "recorded": bool(record),
        "repo_path": record.get("repo_path"),
    }
    if role == "workspace":
        summary["workspace_generation"] = record.get(
            "workspace_generation"
        )
    return summary


def _index_selection(state_value: dict[str, Any]) -> dict[str, Any]:
    """Describe the exact phase-selected project without selecting it for callers."""

    selected_role = _index_role_for_status(state_value)
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        baseline = _index_role_summary(state_value, repo, "baseline")
        workspace = _index_role_summary(state_value, repo, "workspace")
        selected = (
            baseline
            if selected_role == "baseline"
            else workspace
            if selected_role == "workspace"
            else None
        )
        repositories.append(
            {
                "repository_id": repo.get("id"),
                "selected_role": selected_role,
                "role": selected_role,
                "recorded_project": (
                    selected.get("recorded_project") if selected else None
                ),
                "recommended_project": (
                    selected.get("recommended_project") if selected else None
                ),
                "baseline": baseline,
                "workspace": workspace,
            }
        )
    return {
        "automatic": False,
        "selected_role": selected_role,
        # ``role`` is retained as a compact compatibility alias.  Consumers
        # should use selected_role and pass recorded_project explicitly.
        "role": selected_role,
        "repositories": repositories,
    }


def _result(command: str, state_value: dict[str, Any], **extra: Any) -> dict[str, Any]:
    workflow = _workflow_progress(state_value)
    response: dict[str, Any] = {
        "ok": True,
        "command": command,
        "task_id": state_value["task_id"],
        "revision": state_value["revision"],
        "status": state_value["status"],
        "status_name": workflow["current"]["name"],
        "flow": _flow(state_value),
        "flow_name": workflow["flow"]["name"],
        "workspace_strategy": workflow["workspace_strategy"]["id"],
        "workspace_strategy_name": workflow["workspace_strategy"]["name"],
        "workflow": workflow,
        "index_selection": _index_selection(state_value),
    }
    response.update(extra)
    return response


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    requirement = (args.requirement_option or args.requirement or "").strip()
    if not requirement:
        raise FlowError("INVALID_ARGUMENT", "start requires a non-empty requirement")
    workspace_strategy = getattr(args, "workspace_strategy", None)
    if workspace_strategy is None:
        raise FlowError(
            "WORKSPACE_STRATEGY_REQUIRED",
            (
                "start requires an explicit --workspace-strategy selected "
                "before task creation"
            ),
            details={
                "choices": [
                    {
                        "flow": "lite",
                        "workspace_strategy": "in-place",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['in-place']}"
                            f"（{FLOW_NAMES_ZH['lite']}）"
                        ),
                    },
                    {
                        "flow": "lite",
                        "workspace_strategy": "branch",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['branch']}"
                            f"（{FLOW_NAMES_ZH['lite']}）"
                        ),
                    },
                    {
                        "flow": "full",
                        "workspace_strategy": "worktree",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['worktree']}"
                            f"（{FLOW_NAMES_ZH['full']}）"
                        ),
                    },
                ]
            },
        )
    if workspace_strategy not in FLOW_BY_WORKSPACE_STRATEGY:
        raise FlowError(
            "INVALID_ARGUMENT",
            (
                "workspace strategy must be one of: "
                f"{', '.join(WORKSPACE_STRATEGIES)}"
            ),
            details={"workspace_strategy": workspace_strategy},
        )
    inferred_flow = FLOW_BY_WORKSPACE_STRATEGY[workspace_strategy]
    requested_flow = getattr(args, "flow", None)
    if requested_flow is not None and requested_flow not in FLOW_MODES:
        raise FlowError(
            "INVALID_ARGUMENT",
            f"flow must be one of: {', '.join(FLOW_MODES)}",
            details={"flow": requested_flow},
        )
    flow = requested_flow or inferred_flow
    if flow != inferred_flow:
        raise FlowError(
            "FLOW_WORKSPACE_STRATEGY_MISMATCH",
            (
                f"workspace strategy {workspace_strategy!r} is not valid "
                f"for the {flow} flow"
            ),
            details={
                "flow": flow,
                "workspace_strategy": workspace_strategy,
                "inferred_flow": inferred_flow,
                "allowed": [
                    strategy
                    for strategy, strategy_flow in (
                        FLOW_BY_WORKSPACE_STRATEGY.items()
                    )
                    if strategy_flow == flow
                ],
            },
        )
    task_id = args.task_id or f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    _validate_task_id(task_id)
    if not args.repo:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one --repo")
    roots: list[Path] = []
    for supplied in args.repo:
        root = _canonical_repo(supplied)
        if not any(_same_path(root, existing) for existing in roots):
            roots.append(root)
    if not roots:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one distinct Git repository")
    for root in roots:
        _assert_path_in_scope(root, "repository", args.data_dir)
    common_dirs: list[tuple[Path, Path]] = []
    for root in roots:
        common_dir = _git_evidence_path(root, "--git-common-dir")
        previous = next(
            (
                previous_root
                for previous_common_dir, previous_root in common_dirs
                if _same_path(common_dir, previous_common_dir)
            ),
            None,
        )
        if previous is not None:
            raise FlowError(
                "DUPLICATE_GIT_REPOSITORY",
                "multiple configured checkouts share the same Git common directory",
                details={
                    "repository": str(root),
                    "duplicate_of": str(previous),
                    "git_common_dir": str(common_dir),
                },
            )
        common_dirs.append((common_dir, root))
    protected = list(
        dict.fromkeys(
            [*DEFAULT_PROTECTED_BRANCHES, *(args.protected_branch or [])]
        )
    )
    branch_bindings: dict[str, dict[str, Any]] = {}
    if workspace_strategy == "branch":
        for root in roots:
            branch = _git_optional(
                root, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            if not branch:
                raise FlowError(
                    "BRANCH_STRATEGY_NOT_READY",
                    (
                        "branch workspace strategy requires a named branch "
                        "to be checked out before start"
                    ),
                    details={"repository": str(root), "branch": branch},
                )
            head_ref = _git_optional(
                root,
                "symbolic-ref",
                "--quiet",
                "--no-recurse",
                "HEAD",
            )
            branch_ref = f"refs/heads/{branch}"
            if head_ref != branch_ref:
                raise FlowError(
                    "SYMBOLIC_WORKSPACE_BRANCH",
                    (
                        "branch workspace strategy requires HEAD to point "
                        "directly at the selected local branch"
                    ),
                    details={
                        "repository": str(root),
                        "branch": branch,
                        "branch_ref": branch_ref,
                        "head_ref": head_ref,
                    },
                )
            default_remote = _default_remote(root, branch)
            resolved_base = _default_base(
                root,
                default_remote,
                branch,
                protected,
            )
            protected_for_repo = [
                *protected,
                *([resolved_base] if resolved_base else []),
            ]
            branch_state = _branch_ref_state(
                root,
                branch,
                protected_for_repo,
            )
            head_sha = _git(root, "rev-parse", "HEAD")
            if branch_state.get("planned_ref_oid") != head_sha:
                raise FlowError(
                    "CHECKOUT_DRIFT",
                    "checked-out branch does not resolve to the current HEAD",
                    details={
                        "repository": str(root),
                        "approved_branch": branch,
                        "actual_branch": branch,
                        "approved_head_sha": branch_state.get(
                            "planned_ref_oid"
                        ),
                        "actual_head_sha": head_sha,
                    },
                )
            branch_bindings[str(root)] = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "branch": branch,
                "head_sha": head_sha,
                "initial_preflight_confirmed": False,
            }
    repositories: list[dict[str, Any]] = []
    ids: set[str] = set()
    for root in roots:
        repo_id = _repo_id(root, ids)
        ids.add(repo_id)
        repositories.append(
            {
                "id": repo_id,
                "path": str(root),
                "canonical_path": str(root),
                "protected_branches": protected,
                "branch_binding": branch_bindings.get(str(root)),
                "preflight": None,
                "baseline": None,
                "analysis_workspace": None,
                "index": None,
                "workspace": None,
                "workspace_index": None,
                "index_history": [],
                "workspace_history": [],
            }
        )
    data_root = resolve_data_dir(args.data_dir)
    task_dir = _task_dir(task_id, data_root)
    identity = _task_identity(task_id)
    with _task_namespace_lock(data_root):
        tasks_root = data_root / "tasks"
        if tasks_root.is_dir():
            for candidate in tasks_root.iterdir():
                if not candidate.is_dir():
                    continue
                try:
                    candidate_identity = _task_identity(candidate.name)
                except FlowError:
                    # Non-portable legacy directories are not adoptable by a
                    # new task, but still reserve their literal case-folded
                    # spelling so creation cannot alias them.
                    candidate_identity = candidate.name.lower()
                if candidate_identity == identity:
                    code = "TASK_EXISTS" if candidate.name == task_id else "TASK_ID_COLLISION"
                    raise FlowError(
                        code,
                        (
                            f"task already exists: {task_id}"
                            if code == "TASK_EXISTS"
                            else "task id has the same portable identity as an existing task"
                        ),
                        details={
                            "task_id": task_id,
                            "existing_task_id": candidate.name,
                            "portable_identity": identity,
                        },
                    )
        with _task_lock(task_dir):
            if (task_dir / "state.json").exists():
                raise FlowError(
                    "TASK_EXISTS",
                    f"task already exists: {task_id}",
                    details={"task_id": task_id},
                )
            _ensure_private_dir(task_dir / "artifacts")
            created = utc_now()
            state_value: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "task_id": task_id,
                "requirement": requirement,
                "status": "INTAKE",
                "revision": 0,
                "created_at": created,
                "updated_at": created,
                "flow": flow,
                "route": None,
                "repositories": repositories,
                "artifacts": [],
                "approvals": {},
                "tests": [],
                "review_snapshots": [],
                "mutation_recoveries": [],
                "impact_generation": 0,
                "planning_generation": 0,
                "workspace": {
                    "strategy": workspace_strategy,
                    "ready": False,
                    "generation": 0,
                },
                "blocked": None,
                "cancelled": None,
            }
            _commit_state(
                None,
                state_value,
                task_dir,
                "task_started",
                {"repository_ids": sorted(ids)},
            )
    return _result("start", state_value, task=state_value)


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    state_value = load_state(_task_arg(args), args.data_dir)
    return _result("show", state_value, task=state_value)


def _archive_quarantine(
    task_dir: Path, quarantine: dict[str, Any]
) -> Path:
    recovery_id = str(
        quarantine.get("recovery_id") or uuid.uuid4()
    )
    source = _quarantine_path(task_dir)
    archive = task_dir / f"mutation-quarantine.recovered-{recovery_id}.json"
    try:
        os.replace(source, archive)
    except OSError as exc:
        raise FlowError(
            "QUARANTINE_ARCHIVE_FAILED",
            "validated quarantine could not be archived; mutations remain blocked",
            details={
                "source": str(source),
                "archive": str(archive),
                "error": str(exc),
            },
        ) from exc
    _set_private_permissions(archive, 0o600)
    return archive


def command_recover_quarantine(
    args: argparse.Namespace,
) -> dict[str, Any]:
    task_id = _task_arg(args)
    task_dir = _task_dir(task_id, args.data_dir)
    with _task_lock(task_dir, allow_quarantine=True):
        current = load_state(task_id, args.data_dir)
        _check_revision(current, args.expected_revision)
        quarantine = _read_quarantine(task_dir)
        if quarantine is None:
            raise FlowError(
                "QUARANTINE_NOT_FOUND",
                "task has no active mutation quarantine",
                details={"task_id": task_id},
            )
        _require_current_evidence(quarantine, "mutation quarantine")
        recovery_id = quarantine.get("recovery_id")
        validated_revision = quarantine.get(
            "recovery_validated_revision"
        )
        recoveries = current.get("mutation_recoveries") or []
        completed = next(
            (
                item
                for item in recoveries
                if isinstance(item, dict)
                and item.get("recovery_id") == recovery_id
            ),
            None,
        )
        if (
            recovery_id
            and validated_revision == current.get("revision")
            and completed
        ):
            archive = _archive_quarantine(task_dir, quarantine)
            return _result(
                "recover-quarantine",
                current,
                recovered=True,
                unchanged=True,
                recovery=completed,
                archive_path=str(archive),
            )
        compatible_revisions = {
            quarantine.get("state_revision"),
            quarantine.get("expected_committed_revision"),
            quarantine.get("committed_revision"),
        }
        if current.get("revision") not in compatible_revisions:
            raise FlowError(
                "QUARANTINE_REVISION_CHANGED",
                "task revision changed after the quarantined child was recorded",
                details={
                    "quarantine_revision": quarantine.get(
                        "state_revision"
                    ),
                    "expected_committed_revision": quarantine.get(
                        "expected_committed_revision"
                    ),
                    "committed_revision": quarantine.get(
                        "committed_revision"
                    ),
                    "current_revision": current.get("revision"),
                },
            )
        if _quarantine_processes_alive(quarantine):
            raise FlowError(
                "QUARANTINE_CHILD_ACTIVE",
                "the quarantined child process is still active",
                details={"pid": quarantine.get("pid")},
            )
        validation = _validate_quarantine_postconditions(
            current, task_dir, quarantine
        )
        recovery_id = str(uuid.uuid4())
        recovery = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "recovery_id": recovery_id,
            "recovered_at": utc_now(),
            "quarantined_pid": quarantine.get("pid"),
            "quarantined_command": quarantine.get("command"),
            "state_revision": current.get("revision"),
            "validation": validation,
        }
        validated_quarantine = {
            **quarantine,
            "recovery_id": recovery_id,
            "recovery_validated_at": recovery["recovered_at"],
            "recovery_validated_revision": int(
                current.get("revision", 0)
            )
            + 1,
            "validation": validation,
        }
        _atomic_write_json(
            _quarantine_path(task_dir), validated_quarantine
        )
        state_value = _copy_state(current)
        state_value.setdefault("mutation_recoveries", []).append(recovery)
        _commit_state(
            current,
            state_value,
            task_dir,
            "mutation_quarantine_recovered",
            {
                "recovery_id": recovery_id,
                "quarantined_pid": quarantine.get("pid"),
            },
        )
        archive = _archive_quarantine(task_dir, validated_quarantine)
    return _result(
        "recover-quarantine",
        state_value,
        recovered=True,
        recovery=recovery,
        archive_path=str(archive),
    )


def _atomic_evidence_summary(path: Path) -> dict[str, Any]:
    """Describe one side of a rollback pair well enough to decide about it."""

    summary: dict[str, Any] = {"path": str(path), "present": path.is_file()}
    if not summary["present"]:
        return summary
    try:
        summary["size"] = path.stat().st_size
        summary["sha256"] = _sha256_file(path)
        raw = path.read_bytes()
    except OSError as exc:
        summary["readable"] = False
        summary["error"] = str(exc)
        return summary
    summary["readable"] = True
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        summary["json"] = False
        return summary
    summary["json"] = True
    if isinstance(value, dict):
        summary["schema"] = {
            key: value.get(key)
            for key in (
                "schema_version",
                "evidence_contract_version",
                "task_id",
                "status",
                "revision",
                "updated_at",
            )
            if key in value
        }
    return summary


def _classify_rollback_candidate(
    destination: Path, rollback: Path
) -> dict[str, Any]:
    """Decide whether rollback evidence can be cleared without a choice."""

    destination_summary = _atomic_evidence_summary(destination)
    rollback_summary = _atomic_evidence_summary(rollback)
    if destination_summary.get("present") and destination_summary.get(
        "sha256"
    ) == rollback_summary.get("sha256"):
        # The interrupted writer either had not replaced the destination yet
        # or had already restored it; the evidence is a proven duplicate.
        resolution = "identical"
    elif (
        not destination_summary.get("present")
        and rollback_summary.get("size") == 0
    ):
        # The interrupted write was creating a new file, so the empty
        # placeholder preserves nothing and no destination was committed.
        resolution = "uncommitted"
    else:
        resolution = "mismatch"
    return {
        "resolution": resolution,
        "destination": destination_summary,
        "rollback": rollback_summary,
    }


def _atomic_rollback_candidates(
    data_root: Path,
) -> list[tuple[Path, Path]]:
    """Every controller-owned destination that still carries rollback evidence.

    The scan covers the controller's own state files only: the data root and
    every task directory.  Managed worktrees hold repository content, never
    atomically written controller state.
    """

    found: list[Path] = []
    if data_root.is_dir():
        found.extend(sorted(data_root.glob(f".*{_ROLLBACK_MARKER}*")))
        tasks_root = data_root / "tasks"
        if tasks_root.is_dir():
            found.extend(
                sorted(tasks_root.rglob(f".*{_ROLLBACK_MARKER}*"))
            )
    pairs: list[tuple[Path, Path]] = []
    for candidate in found:
        if not candidate.is_file():
            continue
        destination = _rollback_evidence_destination(candidate)
        if destination is None:
            continue
        pairs.append((destination, candidate))
    return pairs


def _atomic_recovery_lock(
    data_root: Path, destination: Path
) -> contextlib.AbstractContextManager[None]:
    """Hold the same lock the interrupted writer of this file would hold."""

    tasks_root = data_root / "tasks"
    try:
        relative = destination.relative_to(tasks_root)
    except ValueError:
        relative = None
    if relative is not None and relative.parts:
        # A quarantined task is exactly the case that needs recovering.
        return _task_lock(
            tasks_root / relative.parts[0], allow_quarantine=True
        )
    if destination.parent == data_root:
        if destination.name == "config.json":
            return _config_lock(data_root)
        if destination.name == "workspace-registry.json":
            return _workspace_registry_lock(data_root)
    return contextlib.nullcontext()


def _discard_rollback_evidence(rollback: Path) -> None:
    try:
        rollback.unlink()
    except OSError as exc:
        raise FlowError(
            "ATOMIC_ROLLBACK_CLEANUP_FAILED",
            "rollback evidence could not be removed",
            details={"rollback": str(rollback), "error": str(exc)},
        ) from exc


def _restore_rollback_evidence(destination: Path, rollback: Path) -> None:
    try:
        os.replace(rollback, destination)
    except OSError as exc:
        raise FlowError(
            "ATOMIC_ROLLBACK_RESTORE_FAILED",
            "rollback evidence could not be restored over the destination",
            details={
                "path": str(destination),
                "rollback": str(rollback),
                "error": str(exc),
            },
        ) from exc
    _set_private_permissions(destination, 0o600)


def command_recover_atomic_write(
    args: argparse.Namespace,
) -> dict[str, Any]:
    data_root = resolve_data_dir(args.data_dir)
    selected: Path | None = None
    if args.path:
        supplied = Path(args.path).expanduser()
        if not supplied.is_absolute():
            raise FlowError(
                "INVALID_ARGUMENT",
                "--path requires an absolute path",
                details={"path": args.path},
            )
        # Both spellings are accepted: the blocked destination, or one of the
        # rollback files named by details.rollback_candidates.
        selected = _rollback_evidence_destination(supplied) or supplied
    if args.resolve and selected is None:
        raise FlowError(
            "INVALID_ARGUMENT",
            "--resolve requires --path naming one blocked destination",
        )
    if args.rollback_sha256 and not SHA256_RE.fullmatch(
        args.rollback_sha256
    ):
        raise FlowError(
            "INVALID_ARGUMENT",
            "--rollback-sha256 must be 64 lowercase hexadecimal characters",
        )
    candidates = [
        pair
        for pair in _atomic_rollback_candidates(data_root)
        if selected is None or _same_path(pair[0], selected)
    ]
    reports = [
        _classify_rollback_candidate(destination, rollback)
        for destination, rollback in candidates
    ]
    response: dict[str, Any] = {
        "ok": True,
        "command": "recover-atomic-write",
        "data_dir": str(data_root),
        "changed": False,
        "candidates": reports,
        "removed": [],
        "restored": [],
    }
    if not (args.apply or args.resolve):
        return response
    if not candidates:
        raise FlowError(
            "ATOMIC_ROLLBACK_NOT_FOUND",
            "no rollback evidence is present for the selected scope",
            details={
                "data_dir": str(data_root),
                "path": str(selected) if selected else None,
            },
        )
    if args.resolve:
        if len(candidates) > 1:
            raise FlowError(
                "ATOMIC_ROLLBACK_AMBIGUOUS",
                "--resolve needs exactly one rollback file; name it with --path",
                details={
                    "path": str(selected),
                    "rollback_candidates": [
                        str(rollback) for _, rollback in candidates
                    ],
                },
            )
        if not args.rollback_sha256:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--resolve requires --rollback-sha256 naming the inspected evidence",
                details={"candidate": reports[0]},
            )
        destination, rollback = candidates[0]
        with _atomic_recovery_lock(data_root, destination):
            report = _classify_rollback_candidate(destination, rollback)
            if report["rollback"].get("sha256") != args.rollback_sha256:
                raise FlowError(
                    "ATOMIC_ROLLBACK_MISMATCH",
                    "--rollback-sha256 does not name the current rollback evidence",
                    details={
                        "expected_sha256": report["rollback"].get("sha256"),
                        "provided_sha256": args.rollback_sha256,
                        "candidate": report,
                    },
                )
            if args.resolve == "restore-rollback":
                _restore_rollback_evidence(destination, rollback)
                response["restored"].append(str(destination))
            else:
                _discard_rollback_evidence(rollback)
                response["removed"].append(str(rollback))
        response["changed"] = True
        response["candidates"] = [report]
        response["resolved"] = args.resolve
        return response
    blocked: list[dict[str, Any]] = []
    for destination, rollback in candidates:
        with _atomic_recovery_lock(data_root, destination):
            report = _classify_rollback_candidate(destination, rollback)
            if report["resolution"] == "mismatch":
                blocked.append(report)
                continue
            _discard_rollback_evidence(rollback)
        response["removed"].append(str(rollback))
    response["changed"] = bool(response["removed"])
    if blocked:
        # Fail closed: differing content is a decision about committed state,
        # never something this command may make on the user's behalf.
        raise FlowError(
            "ATOMIC_ROLLBACK_MISMATCH",
            (
                "rollback evidence differs from the committed destination and "
                "needs an explicit resolution"
            ),
            details={
                "data_dir": str(data_root),
                "removed": response["removed"],
                "blocked": blocked,
                "resolutions": ["keep-current", "restore-rollback"],
            },
        )
    return response


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    tasks_dir = resolve_data_dir(args.data_dir) / "tasks"
    values: list[dict[str, Any]] = []
    if tasks_dir.is_dir():
        for state_file in tasks_dir.glob("*/state.json"):
            try:
                state_value = load_state(state_file)
            except FlowError as exc:
                if exc.code == "EVIDENCE_CONTRACT_UNSUPPORTED":
                    raise
                continue
            if args.active_only and state_value.get("status") in TERMINAL_STATES:
                continue
            if args.status and state_value.get("status") not in args.status:
                continue
            workflow = _workflow_progress(state_value)
            values.append(
                {
                    "task_id": state_value.get("task_id"),
                    "requirement": state_value.get("requirement"),
                    "status": state_value.get("status"),
                    "status_name": workflow["current"]["name"],
                    "flow": workflow["flow"]["id"],
                    "flow_name": workflow["flow"]["name"],
                    "workspace_strategy": workflow["workspace_strategy"]["id"],
                    "workspace_strategy_name": workflow[
                        "workspace_strategy"
                    ]["name"],
                    "revision": state_value.get("revision"),
                    "updated_at": state_value.get("updated_at"),
                    "repositories": [repo.get("path") for repo in state_value.get("repositories", [])],
                }
            )
    values.sort(key=lambda item: (str(item.get("updated_at", "")), str(item.get("task_id", ""))), reverse=True)
    return {"ok": True, "command": "list", "count": len(values), "tasks": values}


def _apply_scope_changes(scope: dict[str, Any], args: argparse.Namespace) -> None:
    """Apply one invocation's edits: mode, then removals, then additions."""

    if args.mode:
        scope["mode"] = args.mode
    for option, key in (("remove", "include"), ("remove_exclude", "exclude")):
        for supplied in getattr(args, option) or []:
            flag = "--" + option.replace("_", "-")
            root = _normalize_scope_root(supplied, flag)
            matches = [
                configured
                for configured in scope[key]
                if _same_path(Path(root), Path(configured))
            ]
            if len(matches) != 1:
                raise FlowError(
                    "SCOPE_PATH_NOT_CONFIGURED",
                    f"{flag} does not match a configured scope directory",
                    details={
                        "path": root,
                        "configured": list(scope[key]),
                        "identity_matches": matches,
                    },
                )
            scope[key].remove(matches[0])
    # Adding the first included directory is what turns the allowlist on; an
    # include recorded while the mode stays "all" would silently do nothing.
    activates = args.mode is None and scope["mode"] == "all" and not scope["include"]
    for option, key in (("add", "include"), ("add_exclude", "exclude")):
        for supplied in getattr(args, option) or []:
            root = _normalize_scope_root(supplied, "--" + option.replace("_", "-"))
            if not any(
                _same_path(Path(root), Path(configured))
                for configured in scope[key]
            ):
                scope[key].append(root)
    if activates and scope["include"]:
        scope["mode"] = "allowlist"


def command_scope(args: argparse.Namespace) -> dict[str, Any]:
    path = config_path(args.data_dir)
    edits = (
        args.clear
        or args.mode
        or args.add
        or args.remove
        or args.add_exclude
        or args.remove_exclude
    )
    if edits:
        with _config_lock(resolve_data_dir(args.data_dir)):
            try:
                config = load_config(args.data_dir)
                # load_config already normalized; repeat it for an independent
                # snapshot the edits below cannot mutate through shared lists.
                before = _normalize_scope(config["scope"])
            except FlowError:
                # An unusable configuration must still be resettable.
                if not args.clear:
                    raise
                before = None
            if args.clear:
                config = _default_config()
            _apply_scope_changes(config["scope"], args)
            config["scope"] = _normalize_scope(config["scope"])
            _atomic_write_json(path, config)
            stored = config["scope"]
    else:
        before = stored = load_config(args.data_dir)["scope"]
    effective = resolve_scope(args.data_dir)
    overrides = effective.pop("overrides", {})
    response = {
        "ok": True,
        "command": "scope",
        "config_path": str(path),
        "changed": stored != before,
        "scope": stored,
        "effective": effective,
        "overrides": overrides,
        "summary": _scope_summary(effective),
        "missing_paths": [
            root
            for root in (*effective["include"], *effective["exclude"])
            if not Path(root).is_dir()
        ],
    }
    if args.check is not None:
        response["check"] = evaluate_scope(
            _normalize_scope_root(args.check, "--check"), effective
        )
    return response


PREFLIGHT_PREVIEW_TOKEN_VERSION = "v2"
PREFLIGHT_DECISION_FIELDS = (
    "evidence_contract_version",
    "repository_root",
    "repository_path_identity",
    "repository_root_identity",
    "git_dir",
    "git_dir_identity",
    "git_common_dir",
    "git_common_dir_identity",
    "branch",
    "head_sha",
    "remote",
    "remote_url",
    "base_branch",
    "base_candidate_ref",
    "base_candidate_sha",
    "fetch_refspec",
    "conflicts",
    "conflict_paths_sha256",
    "operations",
    "blockers",
    "ready",
)
PREFLIGHT_OBSERVATION_FIELDS = (
    *PREFLIGHT_DECISION_FIELDS,
    "staged",
    "staged_paths_sha256",
    "unstaged",
    "unstaged_paths_sha256",
    "untracked",
    "untracked_paths_sha256",
    "dirty",
)
PREFLIGHT_LIST_FIELDS = {
    "blockers",
    "conflicts",
    "staged",
    "unstaged",
    "untracked",
}
def _preflight_repository_projection(
    selected: list[dict[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for repo in selected:
        evidence = repo["preflight"]
        projected: dict[str, Any] = {}
        for field in fields:
            value = evidence.get(field)
            if field in PREFLIGHT_LIST_FIELDS and isinstance(value, list):
                value = sorted(value)
            projected[field] = value
        repositories.append(
            {
                "id": repo["id"],
                "path": repo.get("canonical_path") or repo.get("path"),
                "preflight": projected,
            }
        )
    repositories.sort(key=lambda item: str(item["id"]))
    return repositories


def _preflight_preview_hashes(
    current: dict[str, Any],
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    selection_complete: bool,
    args: argparse.Namespace,
) -> tuple[str, str]:
    common = {
        "task_id": current["task_id"],
        "revision": current["revision"],
        "from_status": current["status"],
        "to_status": state_value["status"],
        "flow": _flow(state_value),
        "workspace_strategy": _workspace_strategy(state_value),
        "repository_ids": sorted(repo["id"] for repo in selected),
        "selection_complete": selection_complete,
        "all_checked": all(
            repo.get("preflight") is not None
            for repo in state_value.get("repositories", [])
        ),
        "remote_override": args.remote,
        "base_override": args.base,
        "blockers": sorted(
            (
                {
                    "repository_id": item["repository_id"],
                    "blockers": sorted(item["blockers"]),
                }
                for item in blockers
            ),
            key=lambda item: str(item["repository_id"]),
        ),
    }
    decision_payload = {
        **common,
        "repositories": _preflight_repository_projection(
            selected,
            PREFLIGHT_DECISION_FIELDS,
        ),
    }
    observation_payload = {
        **common,
        "repositories": _preflight_repository_projection(
            selected,
            PREFLIGHT_OBSERVATION_FIELDS,
        ),
    }
    return (
        _sha256_bytes(_json_bytes(decision_payload)),
        _sha256_bytes(_json_bytes(observation_payload)),
    )


def _preflight_preview_token(
    decision_sha256: str,
    observation_sha256: str,
) -> str:
    return (
        f"{PREFLIGHT_PREVIEW_TOKEN_VERSION}:"
        f"{decision_sha256}:{observation_sha256}"
    )


def _parse_preflight_preview_token(token: str | None) -> tuple[str | None, str | None]:
    if not isinstance(token, str):
        return None, None
    version, separator, remainder = token.partition(":")
    decision_sha256, second_separator, observation_sha256 = (
        remainder.partition(":")
    )
    if (
        version != PREFLIGHT_PREVIEW_TOKEN_VERSION
        or not separator
        or not second_separator
        or not SHA256_RE.fullmatch(decision_sha256)
        or not SHA256_RE.fullmatch(observation_sha256)
    ):
        return None, None
    return decision_sha256, observation_sha256


def _assert_branch_checkout_binding(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> None:
    if _workspace_strategy(state_value) != "branch":
        return
    binding = repo.get("branch_binding")
    if not isinstance(binding, dict):
        raise FlowError(
            "CHECKOUT_BINDING_MISSING",
            "branch workspace task has no start-time checkout binding",
            details={"repository_id": repo.get("id")},
        )
    _require_current_evidence(
        binding, f"branch-binding:{repo.get('id')}"
    )
    path = Path(repo["path"])
    actual_branch = _git_optional(
        path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    actual_head_ref = _git_optional(
        path,
        "symbolic-ref",
        "--quiet",
        "--no-recurse",
        "HEAD",
    )
    actual_head = _git_optional(path, "rev-parse", "HEAD")
    approved_branch = binding.get("branch")
    approved_head_ref = (
        f"refs/heads/{approved_branch}"
        if isinstance(approved_branch, str)
        else None
    )
    approved_head = binding.get("head_sha")
    initial_head_required = (
        binding.get("initial_preflight_confirmed") is not True
    )
    if (
        actual_branch != approved_branch
        or actual_head_ref != approved_head_ref
        or (initial_head_required and actual_head != approved_head)
    ):
        raise FlowError(
            "CHECKOUT_DRIFT",
            "branch workspace checkout changed after task start",
            details={
                "repository_id": repo.get("id"),
                "approved_branch": approved_branch,
                "actual_branch": actual_branch,
                "approved_head_ref": approved_head_ref,
                "actual_head_ref": actual_head_ref,
                "approved_head_sha": approved_head,
                "actual_head_sha": actual_head,
                "initial_head_required": initial_head_required,
            },
        )


def _guard_branch_workspace_base(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    if _workspace_strategy(state_value) != "branch":
        return
    branch = evidence.get("branch")
    base_branch = evidence.get("base_branch")
    if not isinstance(branch, str) or not isinstance(base_branch, str):
        return
    try:
        _branch_ref_state(
            Path(repo["path"]),
            branch,
            [base_branch],
        )
    except FlowError as exc:
        if exc.code != "PROTECTED_BRANCH":
            raise
        blockers = evidence.setdefault("blockers", [])
        if "branch_matches_base" not in blockers:
            blockers.append("branch_matches_base")
        evidence["ready"] = False


def _preflight_blockers(
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    selection_complete: bool,
) -> list[dict[str, Any]]:
    repositories = (
        state_value["repositories"] if selection_complete else selected
    )
    return [
        {
            "repository_id": repo["id"],
            "blockers": repo["preflight"]["blockers"],
        }
        for repo in repositories
        if repo.get("preflight") and repo["preflight"]["blockers"]
    ]


def _apply_preflight_outcome(
    current: dict[str, Any],
    state_value: dict[str, Any],
    *,
    selection_complete: bool,
    all_checked: bool,
    blockers: list[dict[str, Any]],
) -> None:
    if selection_complete and blockers:
        previous = (
            current["status"]
            if current["status"] != "BLOCKED"
            else (current.get("blocked") or {}).get(
                "from_status",
                "INTAKE",
            )
        )
        state_value["status"] = "BLOCKED"
        state_value["blocked"] = {
            "phase": "preflight",
            "from_status": previous,
            "reason": "preflight blockers detected",
            "details": blockers,
            "at": utc_now(),
        }
    elif selection_complete and all_checked:
        state_value["status"] = "PREFLIGHTED"
        state_value["blocked"] = None


def command_preflight(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    if args.preview and args.confirm_preview:
        raise FlowError(
            "INVALID_ARGUMENT",
            "preflight accepts either --preview or --confirm-preview, not both",
        )
    if getattr(args, "accept_evidence_refresh", False) and not args.confirm_preview:
        raise FlowError(
            "INVALID_ARGUMENT",
            "--accept-evidence-refresh requires --confirm-preview",
        )
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        if not args.preview and not args.confirm_preview:
            raise FlowError(
                "PREFLIGHT_PREVIEW_REQUIRED",
                (
                    "preflight must first run with --preview, then rerun with "
                    "--confirm-preview <token> after any required status-edge confirmation"
                ),
            )
        allowed = {"INTAKE", "PREFLIGHTED"}
        if current.get("status") == "BLOCKED" and (current.get("blocked") or {}).get("phase") == "preflight":
            allowed.add("BLOCKED")
        _assert_status(current, allowed, "preflight")
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        selected_ids = {repo["id"] for repo in selected}
        configured_ids = {
            repo["id"] for repo in state_value["repositories"]
        }
        selection_complete = selected_ids == configured_ids
        if (
            current.get("status") == "PREFLIGHTED"
            and not selection_complete
        ):
            raise FlowError(
                "PREFLIGHT_FULL_SELECTION_REQUIRED",
                (
                    "refreshing a preflighted task requires selecting every "
                    "configured repository"
                ),
                details={
                    "selected_repository_ids": sorted(selected_ids),
                    "required_repository_ids": sorted(configured_ids),
                },
            )
        for repo in selected:
            try:
                _assert_branch_checkout_binding(state_value, repo)
            except FlowError as exc:
                if (
                    args.confirm_preview
                    and exc.code == "CHECKOUT_DRIFT"
                ):
                    raise FlowError(
                        "PREFLIGHT_PREVIEW_STALE",
                        (
                            "branch checkout changed after preview; rerun "
                            "--preview after restoring the approved checkout"
                        ),
                        details=exc.details,
                    ) from exc
                raise
            repo["preflight"] = _preflight_repo(
                repo,
                args.remote,
                args.base,
                capture_fingerprint=False,
            )
            _guard_branch_workspace_base(
                state_value, repo, repo["preflight"]
            )
        all_checked = all(repo.get("preflight") is not None for repo in state_value["repositories"])
        blockers = _preflight_blockers(
            state_value,
            selected,
            selection_complete,
        )
        _apply_preflight_outcome(
            current,
            state_value,
            selection_complete=selection_complete,
            all_checked=all_checked,
            blockers=blockers,
        )
        decision_sha256, observation_sha256 = _preflight_preview_hashes(
            current,
            state_value,
            selected,
            blockers,
            selection_complete,
            args,
        )
        preview_token = _preflight_preview_token(
            decision_sha256,
            observation_sha256,
        )
        prospective_workflow = _workflow_progress(state_value)
        transition_preview = {
            "token": preview_token,
            "decision_sha256": decision_sha256,
            "observation_sha256": observation_sha256,
            "changes_status": state_value["status"] != current["status"],
            "from": {
                "id": current["status"],
                "name": STATE_NAMES_ZH.get(current["status"], current["status"]),
            },
            "target": prospective_workflow["current"],
            "remaining": prospective_workflow["remaining"],
        }
        repositories = [
            {"id": repo["id"], "preflight": repo["preflight"]}
            for repo in selected
        ]
        if args.preview:
            return _result(
                "preflight-preview",
                current,
                ready=selection_complete and all_checked and not blockers,
                selection_complete=selection_complete,
                confirmation_scope={
                    "decision": "must_remain_unchanged",
                    "observation": (
                        "refresh_requires_explicit_acceptance"
                    ),
                    "evidence": "captured_on_confirm",
                },
                transition_preview=transition_preview,
                repositories=repositories,
            )
        (
            approved_decision_sha256,
            approved_observation_sha256,
        ) = _parse_preflight_preview_token(args.confirm_preview)
        token_contract_current = (
            isinstance(args.confirm_preview, str)
            and args.confirm_preview.startswith(
                f"{PREFLIGHT_PREVIEW_TOKEN_VERSION}:"
            )
        )
        if (
            approved_decision_sha256 is None
            or not secrets.compare_digest(
                approved_decision_sha256,
                decision_sha256,
            )
        ):
            raise FlowError(
                "PREFLIGHT_PREVIEW_STALE",
                (
                    "the preflight status decision changed after preview; rerun "
                    "--preview and confirm the newly reported status edge"
                ),
                details={
                    "reason": (
                        "status_decision_changed"
                        if approved_decision_sha256 is not None
                        else (
                            "invalid_token"
                            if token_contract_current
                            else "token_contract_changed"
                        )
                    ),
                    "from_status": current["status"],
                    "prospective_status": state_value["status"],
                    "revision": current["revision"],
                    "approved_decision_sha256": approved_decision_sha256,
                    "current_decision_sha256": decision_sha256,
                },
            )
        observation_changed_before_capture = (
            approved_observation_sha256 is None
            or not secrets.compare_digest(
                approved_observation_sha256,
                observation_sha256,
            )
        )
        if (
            observation_changed_before_capture
            and not args.accept_evidence_refresh
        ):
            raise FlowError(
                "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
                (
                    "the preflight worktree summary changed after preview; "
                    "inspect the current evidence and rerun the same token with "
                    "--accept-evidence-refresh"
                ),
                details={
                    "token_reusable": True,
                    "required_flag": "--accept-evidence-refresh",
                    "acceptance_scope": (
                        "current_observation_at_successful_confirm"
                    ),
                    "preview_observation_sha256": (
                        approved_observation_sha256
                    ),
                    "current_observation_sha256": observation_sha256,
                    "repositories": repositories,
                },
            )

        captured_fingerprints: dict[str, dict[str, Any]] = {}
        for repo in selected:
            captured_fingerprints[repo["id"]] = _fingerprint_repo(
                Path(repo["path"])
            )

        # Re-sample every selected repository only after all complete
        # fingerprints have finished. This detects decision-level drift
        # observed after capture across every repository without repeating the
        # byte-complete scan; external repositories cannot form one atomic
        # cross-repository snapshot.
        for repo in selected:
            try:
                _assert_branch_checkout_binding(state_value, repo)
            except FlowError as exc:
                if exc.code == "CHECKOUT_DRIFT":
                    raise FlowError(
                        "PREFLIGHT_PREVIEW_STALE",
                        (
                            "branch checkout changed while preflight evidence "
                            "was captured; rerun --preview"
                        ),
                        details={
                            **exc.details,
                            "reason": "decision_changed_during_capture",
                        },
                    ) from exc
                raise
            post_capture = _preflight_repo(
                repo,
                args.remote,
                args.base,
                capture_fingerprint=False,
            )
            _guard_branch_workspace_base(
                state_value,
                repo,
                post_capture,
            )
            fingerprint = captured_fingerprints[repo["id"]]
            identity_matches = (
                isinstance(fingerprint.get("path"), str)
                and _same_path(
                    Path(fingerprint["path"]),
                    Path(repo["path"]),
                )
                and isinstance(fingerprint.get("root"), str)
                and _same_path(
                    Path(fingerprint["root"]),
                    Path(post_capture["repository_root"]),
                )
                and isinstance(fingerprint.get("git_dir"), str)
                and _same_path(
                    Path(fingerprint["git_dir"]),
                    Path(post_capture["git_dir"]),
                )
                and isinstance(fingerprint.get("git_common_dir"), str)
                and _same_path(
                    Path(fingerprint["git_common_dir"]),
                    Path(post_capture["git_common_dir"]),
                )
                and fingerprint.get("branch")
                == post_capture.get("branch")
                and fingerprint.get("head_sha")
                == post_capture.get("head_sha")
            )
            if not identity_matches:
                raise FlowError(
                    "PREFLIGHT_PREVIEW_STALE",
                    (
                        "repository identity changed while complete preflight "
                        "evidence was captured; rerun --preview"
                    ),
                    details={
                        "repository_id": repo["id"],
                        "reason": "decision_changed_during_capture",
                        "fingerprint_branch": fingerprint.get("branch"),
                        "observed_branch": post_capture.get("branch"),
                        "fingerprint_head_sha": fingerprint.get("head_sha"),
                        "observed_head_sha": post_capture.get("head_sha"),
                    },
                )
            post_capture.update(
                {
                    "evidence_complete": True,
                    "capture_phase": "confirm",
                    "worktree_fingerprint_sha256": fingerprint["sha256"],
                    "capability_profile": fingerprint[
                        "capability_profile"
                    ],
                    "capability_profile_sha256": fingerprint[
                        "capability_profile_sha256"
                    ],
                    "tracked_worktree_manifest_sha256": fingerprint[
                        "tracked_worktree_manifest_sha256"
                    ],
                }
            )
            repo["preflight"] = post_capture

        all_checked = all(
            repo.get("preflight") is not None
            for repo in state_value["repositories"]
        )
        blockers = _preflight_blockers(
            state_value,
            selected,
            selection_complete,
        )
        state_value["status"] = current["status"]
        state_value["blocked"] = _copy_state(current).get("blocked")
        _apply_preflight_outcome(
            current,
            state_value,
            selection_complete=selection_complete,
            all_checked=all_checked,
            blockers=blockers,
        )
        post_decision_sha256, captured_observation_sha256 = (
            _preflight_preview_hashes(
                current,
                state_value,
                selected,
                blockers,
                selection_complete,
                args,
            )
        )
        if not secrets.compare_digest(
            decision_sha256,
            post_decision_sha256,
        ):
            raise FlowError(
                "PREFLIGHT_PREVIEW_STALE",
                (
                    "the preflight status decision changed while complete "
                    "evidence was captured; rerun --preview"
                ),
                details={
                    "reason": "decision_changed_during_capture",
                    "before_capture_decision_sha256": decision_sha256,
                    "after_capture_decision_sha256": (
                        post_decision_sha256
                    ),
                    "from_status": current["status"],
                    "prospective_status": state_value["status"],
                    "revision": current["revision"],
                },
            )
        observation_changed_since_preview = (
            approved_observation_sha256 is None
            or not secrets.compare_digest(
                approved_observation_sha256,
                captured_observation_sha256,
            )
        )
        evidence_refresh_observed = (
            observation_changed_before_capture
            or observation_changed_since_preview
        )
        evidence_refresh_accepted = bool(
            args.accept_evidence_refresh
            and evidence_refresh_observed
        )
        repositories = [
            {"id": repo["id"], "preflight": repo["preflight"]}
            for repo in selected
        ]
        if (
            observation_changed_since_preview
            and not args.accept_evidence_refresh
        ):
            raise FlowError(
                "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
                (
                    "the preflight worktree summary changed while complete "
                    "evidence was captured; inspect the current evidence and "
                    "rerun the same token with --accept-evidence-refresh"
                ),
                details={
                    "token_reusable": True,
                    "required_flag": "--accept-evidence-refresh",
                    "acceptance_scope": (
                        "current_observation_at_successful_confirm"
                    ),
                    "preview_observation_sha256": (
                        approved_observation_sha256
                    ),
                    "current_observation_sha256": (
                        captured_observation_sha256
                    ),
                    "repositories": repositories,
                },
            )
        if (
            selection_complete
            and state_value["status"] == "PREFLIGHTED"
            and _workspace_strategy(state_value) == "branch"
        ):
            for repo in state_value["repositories"]:
                binding = repo.get("branch_binding")
                if not isinstance(binding, dict):
                    raise FlowError(
                        "CHECKOUT_BINDING_MISSING",
                        (
                            "branch workspace task has no start-time "
                            "checkout binding"
                        ),
                        details={"repository_id": repo.get("id")},
                    )
                binding["initial_preflight_confirmed"] = True
        # Remote/base selection and HEAD evidence were just refreshed.  A
        # previous baseline or lite approval must never authorize this new
        # preflight.
        state_value["approvals"].pop("baseline-fetch", None)
        state_value["approvals"].pop(LITE_GATE, None)
        _commit_state(
            current,
            state_value,
            task_dir,
            "preflight_recorded",
            {
                "repository_ids": [repo["id"] for repo in selected],
                "blockers": blockers,
                "decision_sha256": post_decision_sha256,
                "preview_observation_sha256": (
                    approved_observation_sha256
                ),
                "captured_observation_sha256": (
                    captured_observation_sha256
                ),
                "evidence_refreshed_since_preview": (
                    evidence_refresh_observed
                ),
                "evidence_refresh_accepted": evidence_refresh_accepted,
                "accepted_observation_sha256": (
                    captured_observation_sha256
                    if evidence_refresh_accepted
                    else None
                ),
            },
        )
    return _result(
        "preflight",
        state_value,
        ready=selection_complete and all_checked and not blockers,
        selection_complete=selection_complete,
        transition_preview=transition_preview,
        evidence_refreshed_since_preview=(
            evidence_refresh_observed
        ),
        evidence_refresh_accepted=evidence_refresh_accepted,
        preview_observation_sha256=approved_observation_sha256,
        captured_observation_sha256=captured_observation_sha256,
        confirmed_preview={
            "token": args.confirm_preview,
            "decision_sha256": post_decision_sha256,
            "preview_observation_sha256": (
                approved_observation_sha256
            ),
            "captured_observation_sha256": (
                captured_observation_sha256
            ),
            "evidence_refresh_accepted": (
                evidence_refresh_accepted
            ),
        },
        repositories=repositories,
    )


def _git_common_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _git_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _is_linked_worktree(repo: Path) -> bool:
    return _git_dir(repo) != _git_common_dir(repo)


def _status_porcelain(repo: Path) -> tuple[bool, str]:
    try:
        _assert_evidence_supported(repo)
    except FlowError as exc:
        if exc.code == "COMMAND_FAILED":
            return False, ""
        raise
    result = _run(
        _evidence_git_command(
            repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
            "--no-renames",
        ),
        check=False,
        evidence_git=True,
    )
    if result.returncode != 0:
        return False, result.stdout.strip()
    return True, result.stdout.strip()


def _preflight_remote_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "base_branch": preflight.get("base_branch"),
                "base_candidate_ref": preflight.get("base_candidate_ref"),
                "base_candidate_sha": preflight.get("base_candidate_sha"),
                "fetch_refspec": preflight.get("fetch_refspec"),
                "head_sha": preflight.get("head_sha"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _preflight_remote_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_preflight_remote_evidence(state_value)))


def _require_baseline_fetch_approval(state_value: dict[str, Any]) -> dict[str, Any]:
    approval = _require_gate(state_value, "baseline-fetch")
    current_evidence_sha = _preflight_remote_evidence_sha256(state_value)
    if approval.get("preflight_remote_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "baseline-fetch approval does not bind the current preflight remote evidence",
            details={
                "expected_preflight_remote_sha256": current_evidence_sha,
                "approved_preflight_remote_sha256": approval.get("preflight_remote_sha256"),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require baseline-fetch approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        remote = preflight.get("remote")
        recorded_url = preflight.get("remote_url")
        actual_url = _remote_url(Path(repo["path"]), remote)
        if actual_url != recorded_url:
            raise FlowError(
                "REMOTE_URL_CHANGED",
                f"remote URL changed after preflight approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "remote": remote,
                    "recorded_url": recorded_url,
                    "actual_url": actual_url,
                },
            )
        actual_fingerprint = _fingerprint_repo(Path(repo["path"]))["sha256"]
        recorded_fingerprint = preflight.get("worktree_fingerprint_sha256")
        if actual_fingerprint != recorded_fingerprint:
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after preflight approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": recorded_fingerprint,
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _lite_preflight_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    """The exact checkout identity a lite approval authorizes working inside."""

    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "branch": preflight.get("branch"),
                "head_sha": preflight.get("head_sha"),
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _lite_preflight_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_lite_preflight_evidence(state_value)))


def _require_lite_gate(
    state_value: dict[str, Any], *, verify_worktree: bool = False
) -> dict[str, Any]:
    """Require a lite approval bound to the current preflight evidence.

    The approval authorizes in-place work on the exact recorded checkouts, so
    the branch identity is revalidated live at every downstream gate.  The
    worktree fingerprint and ``HEAD`` are only revalidated when entering
    implementation: after that point the edits themselves legitimately change
    both, and test currency binds the final tree instead.
    """

    approval = _require_gate(state_value, LITE_GATE)
    current_evidence_sha = _lite_preflight_evidence_sha256(state_value)
    if approval.get("preflight_evidence_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "lite approval does not bind the current preflight evidence",
            details={
                "expected_preflight_evidence_sha256": current_evidence_sha,
                "approved_preflight_evidence_sha256": approval.get(
                    "preflight_evidence_sha256"
                ),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require lite approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        _assert_branch_checkout_binding(state_value, repo)
        path = Path(repo["path"])
        actual_branch = _git_optional(
            path, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        if actual_branch != preflight.get("branch"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout branch changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_branch": preflight.get("branch"),
                    "actual_branch": actual_branch,
                },
            )
        if not verify_worktree:
            continue
        actual_head = _git_optional(path, "rev-parse", "HEAD")
        if actual_head != preflight.get("head_sha"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout HEAD changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_head_sha": preflight.get("head_sha"),
                    "actual_head_sha": actual_head,
                },
            )
        actual_fingerprint = _fingerprint_repo(path)["sha256"]
        if actual_fingerprint != preflight.get("worktree_fingerprint_sha256"):
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _materialize_analysis_workspace(
    state_value: dict[str, Any], repo: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    source = Path(repo["path"]).resolve(strict=True)
    baseline = _require_current_evidence(
        repo.get("baseline"), f"baseline:{repo.get('id')}"
    )
    _assert_evidence_supported(source)
    base_sha = baseline.get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
    _assert_tree_checkout_supported(source, base_sha)
    destination = (
        data_root / "analysis" / state_value["task_id"] / repo["id"]
    ).resolve(strict=False)
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != baseline.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "source repository capabilities changed after baseline",
            details={"repository_id": repo.get("id")},
        )
    destination_profile = _git_capability_profile(source, destination)
    entries = _worktree_entries(source)
    destination_entry = next(
        (
            entry
            for entry in entries
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        head = _git_optional(destination, "rev-parse", "HEAD")
        branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _same_path(
                    _git_common_dir(destination), _git_common_dir(source)
                )
                linked_worktree = _is_linked_worktree(destination)
            except (FlowError, OSError):
                same_common_dir = False
        if (
            not root
            or not _same_path(Path(root), destination)
            or not same_common_dir
            or not linked_worktree
            or head != base_sha
            or branch is not None
            or not destination_entry
            or destination_entry.get("HEAD") != head
            or "detached" not in destination_entry
            or not status_available
            or bool(status_porcelain)
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"analysis path exists but is not the pinned detached worktree: {destination}",
                details={
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "expected_head": base_sha,
                    "actual_head": head,
                    "actual_branch": branch,
                    "same_common_dir": same_common_dir,
                    "linked_worktree": linked_worktree,
                    "dirty": bool(status_porcelain),
                    "status_porcelain": status_porcelain,
                },
            )
        fingerprint = _fingerprint_repo(destination)
        if fingerprint["capability_profile_sha256"] != destination_profile[
            "sha256"
        ]:
            raise FlowError(
                "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                "analysis worktree capabilities differ from the approved destination profile",
                details={"repository_id": repo.get("id")},
            )
        _set_private_permissions(destination, 0o700)
        return {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(destination),
            "path_identity": _serializable_path_identity(destination),
            "source_identity": _serializable_path_identity(source),
            "source_common_dir_identity": _serializable_path_identity(
                _git_common_dir(source)
            ),
            "head_sha": head,
            "detached": True,
            "ready": True,
            "created": False,
            "materialized_at": utc_now(),
            "filesystem_identity": _serializable_path_identity(destination),
            "source_capability_profile_sha256": source_profile["sha256"],
            "capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
            "fingerprint_sha256": fingerprint["sha256"],
        }
    if destination_entry:
        recorded = repo.get("analysis_workspace") or {}
        if not recorded.get("ready") or not _recorded_path_matches(
            recorded.get("path_identity"),
            recorded.get("path"),
            destination,
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"Git reports an unowned analysis path that is unavailable: {destination}",
                details={"repository_id": repo["id"], "path": str(destination)},
            )
    _ensure_private_dir(destination.parent)
    add_arguments = ["worktree", "add"]
    if destination_entry:
        add_arguments.append("--force")
    add_arguments.extend(["--detach", str(destination), base_sha])
    _git_mutating(
        source,
        "-c",
        f"core.hooksPath={os.devnull}",
        *add_arguments,
    )
    head = _git(destination, "rev-parse", "HEAD")
    branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(destination)
    created_entry = next(
        (
            entry
            for entry in _worktree_entries(source)
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if (
        head != base_sha
        or branch is not None
        or not _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
        or not _is_linked_worktree(destination)
        or not status_available
        or bool(status_porcelain)
        or not created_entry
        or created_entry.get("HEAD") != head
        or "detached" not in created_entry
    ):
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            f"created analysis worktree failed verification: {destination}",
            details={
                "expected_head": base_sha,
                "actual_head": head,
                "actual_branch": branch,
                "dirty": bool(status_porcelain),
                "status_porcelain": status_porcelain,
            },
        )
    fingerprint = _fingerprint_repo(destination)
    if fingerprint["capability_profile_sha256"] != destination_profile[
        "sha256"
    ]:
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            "analysis worktree capabilities differ from the approved destination profile",
            details={"repository_id": repo.get("id")},
        )
    _set_private_permissions(destination, 0o700)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(destination),
        "path_identity": _serializable_path_identity(destination),
        "source_identity": _serializable_path_identity(source),
        "source_common_dir_identity": _serializable_path_identity(
            _git_common_dir(source)
        ),
        "head_sha": head,
        "detached": True,
        "ready": True,
        "created": True,
        "materialized_at": utc_now(),
        "filesystem_identity": _serializable_path_identity(destination),
        "source_capability_profile_sha256": source_profile["sha256"],
        "capability_profile_sha256": fingerprint["capability_profile_sha256"],
        "fingerprint_sha256": fingerprint["sha256"],
    }


def _analysis_workspace_integrity_error(repo: dict[str, Any]) -> str | None:
    analysis = repo.get("analysis_workspace") or {}
    try:
        _require_current_evidence(repo.get("baseline"), f"baseline:{repo.get('id')}")
        _require_current_evidence(analysis, f"analysis-workspace:{repo.get('id')}")
    except FlowError as exc:
        return exc.message
    if not analysis.get("ready") or not analysis.get("path"):
        return f"analysis workspace is not ready: {repo.get('id')}"
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(analysis["path"]).resolve(strict=False)
    if not _recorded_path_matches(
        analysis.get("source_identity"), repo.get("path"), source
    ):
        return f"analysis source identity changed: {repo.get('id')}"
    if not _recorded_path_matches(
        analysis.get("path_identity"), analysis.get("path"), path
    ):
        return f"analysis workspace path identity changed: {repo.get('id')}"
    if not path.is_dir():
        return f"analysis workspace path is missing: {repo.get('id')}"
    expected_head = (repo.get("baseline") or {}).get("base_sha")
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    head = _git_optional(path, "rev-parse", "HEAD")
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(path)
    try:
        same_common_dir = _same_path(
            _git_common_dir(path), _git_common_dir(source)
        )
        linked_worktree = _is_linked_worktree(path)
    except (FlowError, OSError):
        same_common_dir = False
        linked_worktree = False
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if item.get("worktree")
            and _same_path(Path(item["worktree"]), path)
        ),
        None,
    )
    if (
        not root
        or not _same_path(Path(root), path)
        or head != expected_head
        or branch is not None
        or not same_common_dir
        or not linked_worktree
        or not status_available
        or bool(status_porcelain)
        or not entry
        or entry.get("HEAD") != head
        or "detached" not in entry
    ):
        return f"analysis workspace identity, baseline or cleanliness changed: {repo.get('id')}"
    try:
        fingerprint = _fingerprint_repo(path)
    except FlowError as exc:
        return f"analysis workspace evidence cannot be regenerated: {repo.get('id')}: {exc.message}"
    if (
        fingerprint.get("capability_profile_sha256")
        != analysis.get("capability_profile_sha256")
    ):
        return f"analysis workspace capability profile changed: {repo.get('id')}"
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != analysis.get(
        "source_capability_profile_sha256"
    ):
        return f"analysis source capability profile changed: {repo.get('id')}"
    if fingerprint.get("sha256") != analysis.get("fingerprint_sha256"):
        return f"analysis workspace fingerprint changed: {repo.get('id')}"
    return None


def command_baseline(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "baseline")
        _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "baseline")
        baseline_approval = _require_baseline_fetch_approval(current)
        if args.fetch and baseline_approval.get("fetch_allowed") is not True:
            raise FlowError(
                "FETCH_NOT_APPROVED",
                "baseline --fetch requires baseline-fetch approval with --allow-fetch",
            )
        already_baselined = current.get("status") == "BASELINED" and all(
            repo.get("baseline") for repo in current["repositories"]
        )
        regenerate_baseline = already_baselined and any(
            (repo.get("baseline") or {}).get(
                "evidence_contract_version"
            )
            != EVIDENCE_CONTRACT_VERSION
            for repo in current["repositories"]
        )
        if already_baselined and args.fetch:
            raise FlowError(
                "BASELINE_ALREADY_PINNED",
                "--fetch cannot repin an existing baseline; the recorded base is immutable",
            )
        if (
            already_baselined
            and not regenerate_baseline
            and not args.materialize
        ):
            return _result(
                "baseline",
                current,
                unchanged=True,
                repositories=[
                    {
                        "id": repo["id"],
                        "baseline": repo["baseline"],
                        "analysis_workspace": repo.get("analysis_workspace"),
                    }
                    for repo in current["repositories"]
                ],
            )
        state_value = _copy_state(current)
        if not already_baselined or regenerate_baseline:
            for repo in state_value["repositories"]:
                previous_baseline = repo.get("baseline") or {}
                preflight = repo.get("preflight") or {}
                if not preflight.get("ready"):
                    raise FlowError(
                        "PREFLIGHT_REQUIRED",
                        f"repository has not passed preflight: {repo['id']}",
                        details={"repository_id": repo["id"]},
                    )
                path = Path(repo["path"])
                current_head = _git(path, "rev-parse", "HEAD")
                if current_head != preflight.get("head_sha"):
                    raise FlowError(
                        "HEAD_CHANGED",
                        f"repository HEAD changed after preflight: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "preflight_head": preflight.get("head_sha"),
                            "current_head": current_head,
                        },
                    )
                remote = preflight.get("remote")
                candidate_ref = _baseline_source_ref(
                    remote, preflight.get("base_branch")
                )
                pre_fetch_sha = (
                    _git_optional(
                        path,
                        "rev-parse",
                        "--verify",
                        f"{candidate_ref}^{{commit}}",
                    )
                    if candidate_ref
                    else None
                )
                if args.fetch and remote:
                    fetch_refspec = preflight.get("fetch_refspec")
                    remote_url = preflight.get("remote_url")
                    if fetch_refspec != _approved_fetch_refspec(
                        remote, preflight.get("base_branch")
                    ):
                        raise FlowError(
                            "STALE_APPROVAL",
                            "approved fetch refspec no longer matches the selected remote base",
                            details={
                                "repository_id": repo["id"],
                                "fetch_refspec": fetch_refspec,
                            },
                        )
                    if (
                        not isinstance(remote_url, str)
                        or not remote_url.strip()
                    ):
                        raise FlowError(
                            "REMOTE_URL_UNAVAILABLE",
                            "approved fetch has no usable remote URL",
                            details={
                                "repository_id": repo["id"],
                                "remote": remote,
                            },
                        )
                    _git_mutating(
                        path,
                        "-c",
                        f"core.hooksPath={os.devnull}",
                        "-c",
                        "core.fsmonitor=false",
                        "-c",
                        "core.gitProxy=",
                        "-c",
                        "core.askPass=",
                        "-c",
                        "core.sshCommand=ssh",
                        "-c",
                        "credential.helper=",
                        "-c",
                        "maintenance.auto=false",
                        "-c",
                        "gc.auto=0",
                        "-c",
                        "protocol.allow=never",
                        "-c",
                        "protocol.file.allow=always",
                        "-c",
                        "protocol.git.allow=always",
                        "-c",
                        "protocol.http.allow=always",
                        "-c",
                        "protocol.https.allow=always",
                        "-c",
                        "protocol.ssh.allow=always",
                        "-c",
                        "protocol.ext.allow=never",
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "--no-auto-maintenance",
                        "--no-write-commit-graph",
                        "--no-prune",
                        "--no-prune-tags",
                        "--upload-pack=git-upload-pack",
                        "--",
                        remote_url,
                        fetch_refspec,
                    )
                source_ref, base_sha = _baseline_ref(path, remote, preflight["base_branch"])
                if not args.fetch and (
                    source_ref != preflight.get("base_candidate_ref")
                    or base_sha != preflight.get("base_candidate_sha")
                ):
                    raise FlowError(
                        "BASE_REF_CHANGED",
                        "base ref changed after preflight approval",
                        details={
                            "repository_id": repo["id"],
                            "approved_ref": preflight.get("base_candidate_ref"),
                            "approved_sha": preflight.get("base_candidate_sha"),
                            "actual_ref": source_ref,
                            "actual_sha": base_sha,
                        },
                    )
                if (
                    regenerate_baseline
                    and previous_baseline.get("base_sha") != base_sha
                ):
                    raise FlowError(
                        "EVIDENCE_REGENERATION_REQUIRED",
                        "legacy baseline no longer resolves to its recorded immutable object",
                        details={
                            "repository_id": repo["id"],
                            "recorded_base_sha": previous_baseline.get(
                                "base_sha"
                            ),
                            "current_base_sha": base_sha,
                        },
                    )
                repo["baseline"] = {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "recorded_at": utc_now(),
                    "remote": remote,
                    "base_branch": preflight["base_branch"],
                    "source_ref": source_ref,
                    "base_sha": base_sha,
                    "remote_base_sha": base_sha,
                    "head_sha": preflight["head_sha"],
                    "fetched": bool(args.fetch and remote),
                    "pre_fetch_base_sha": pre_fetch_sha,
                    "fetch_refspec": preflight.get("fetch_refspec"),
                    "capability_profile": preflight.get("capability_profile"),
                    "capability_profile_sha256": preflight.get(
                        "capability_profile_sha256"
                    ),
                    "worktree_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
                }
        if args.materialize:
            source_fingerprints = {
                repo["id"]: _fingerprint_repo(Path(repo["path"]))["sha256"]
                for repo in state_value["repositories"]
            }
            for repo in state_value["repositories"]:
                repo["analysis_workspace"] = _materialize_analysis_workspace(
                    state_value, repo, resolve_data_dir(args.data_dir)
                )
            for repo in state_value["repositories"]:
                error = _analysis_workspace_integrity_error(repo)
                if error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                        error,
                        details={"repository_id": repo["id"]},
                    )
                current_source = _fingerprint_repo(Path(repo["path"]))["sha256"]
                if current_source != source_fingerprints[repo["id"]]:
                    raise FlowError(
                        "SOURCE_WORKTREE_CHANGED",
                        "source checkout changed while materializing analysis worktrees",
                        details={"repository_id": repo["id"]},
                    )
        state_value["status"] = "BASELINED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "baseline_recorded",
            {
                "fetch": bool(args.fetch),
                "materialize": bool(args.materialize),
                "base_shas": {
                    repo["id"]: repo["baseline"]["base_sha"]
                    for repo in state_value["repositories"]
                },
            },
        )
    return _result(
        "baseline",
        state_value,
        repositories=[
            {
                "id": repo["id"],
                "baseline": repo["baseline"],
                "analysis_workspace": repo.get("analysis_workspace"),
            }
            for repo in state_value["repositories"]
        ],
    )


def _validate_degraded_index_metadata(
    metadata: dict[str, Any], approval: dict[str, Any]
) -> None:
    if metadata.get("status") != "failed":
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "an index without --index-id requires metadata status='failed'",
        )
    if metadata.get("impact_degraded_approval_id") != approval.get("approval_id"):
        raise FlowError(
            "STALE_APPROVAL",
            "degraded index metadata must bind the current impact-degraded approval",
            details={
                "expected_approval_id": approval.get("approval_id"),
                "provided_approval_id": metadata.get("impact_degraded_approval_id"),
            },
        )
    if not isinstance(metadata.get("error"), str) or not metadata["error"].strip():
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires a non-empty error",
        )
    if not metadata.get("fallback_coverage"):
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires non-empty fallback_coverage",
        )


def _index_provenance_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        index = repo.get("index")
        if not isinstance(index, dict):
            raise FlowError(
                "INDEX_REQUIRED",
                f"repository is missing index provenance: {repo.get('id')}",
            )
        _require_current_evidence(index, f"baseline-index:{repo.get('id')}")
        integrity_error = _analysis_workspace_integrity_error(repo)
        if integrity_error:
            raise FlowError(
                "ANALYSIS_WORKSPACE_CHANGED",
                integrity_error,
                details={"repository_id": repo.get("id")},
            )
        analysis_workspace = repo.get("analysis_workspace") or {}
        analysis_path = Path(str(analysis_workspace.get("path", "")))
        if (
            not _recorded_path_matches(
                index.get("repo_path_identity"),
                index.get("repo_path"),
                analysis_path,
            )
            or index.get("commit_sha")
            != (repo.get("baseline") or {}).get("base_sha")
            or index.get("capability_profile_sha256")
            != analysis_workspace.get("capability_profile_sha256")
            or index.get("fingerprint_sha256")
            != analysis_workspace.get("fingerprint_sha256")
        ):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                "baseline index no longer binds the current analysis evidence",
                details={"repository_id": repo.get("id")},
            )
        if not index.get("index_record_id"):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                f"repository index has no stable record token: {repo.get('id')}",
            )
        receipt = index.get("receipt")
        if isinstance(receipt, dict):
            _require_current_evidence(
                receipt, f"index-receipt:{repo.get('id')}"
            )
            receipt_path = Path(str(receipt.get("path", "")))
            expected_receipt_sha = receipt.get("sha256")
            try:
                actual_receipt_sha = (
                    _sha256_file(receipt_path) if receipt_path.is_file() else None
                )
            except OSError:
                actual_receipt_sha = None
            if (
                not isinstance(expected_receipt_sha, str)
                or actual_receipt_sha != expected_receipt_sha
                or not _recorded_path_matches(
                    receipt.get("path_identity"),
                    receipt.get("path"),
                    receipt_path,
                )
            ):
                raise FlowError(
                    "INDEX_RECEIPT_CHANGED",
                    f"index receipt is missing or changed: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "path": str(receipt_path),
                        "expected_sha256": expected_receipt_sha,
                        "actual_sha256": actual_receipt_sha,
                    },
                )
        if not index.get("index_id"):
            approval = _require_gate(state_value, "impact-degraded")
            _validate_degraded_index_metadata(index.get("metadata") or {}, approval)
            if index.get("impact_degraded_approval_id") != approval.get("approval_id"):
                raise FlowError(
                    "STALE_APPROVAL",
                    f"degraded index no longer binds the current approval: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "expected_approval_id": approval.get("approval_id"),
                        "recorded_approval_id": index.get("impact_degraded_approval_id"),
                    },
                )
        repositories.append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "repository_id": repo["id"],
                "index_record_id": index["index_record_id"],
                "commit_sha": index.get("commit_sha"),
                "index_id": index.get("index_id"),
                "receipt": index.get("receipt"),
                "repo_path_identity": index.get("repo_path_identity"),
                "capability_profile_sha256": index.get(
                    "capability_profile_sha256"
                ),
                "fingerprint_sha256": index.get("fingerprint_sha256"),
                "metadata": index.get("metadata") or {},
                "impact_degraded_approval_id": index.get(
                    "impact_degraded_approval_id"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _index_provenance_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_index_provenance_evidence(state_value)))


def _index_receipt(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    receipt_path = Path(path_value).expanduser().resolve(strict=True)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(receipt_path),
        "path_identity": _serializable_path_identity(receipt_path),
        "sha256": _sha256_file(receipt_path),
        "size": receipt_path.stat().st_size,
    }


def _repository_index_history(repo: dict[str, Any]) -> list[dict[str, Any]]:
    history = repo.setdefault("index_history", [])
    if not isinstance(history, list) or not all(
        isinstance(item, dict) for item in history
    ):
        raise FlowError(
            "INDEX_HISTORY_INVALID",
            f"repository index history has an invalid structure: {repo.get('id')}",
            details={"repository_id": repo.get("id")},
        )
    return history


def _archive_replaced_index(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    previous_role: str,
    replacement: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(previous, dict):
        return None, None
    previous_record = _copy_state(previous)
    previous_record.setdefault("role", previous_role)
    replacement_binding = {
        "role": replacement.get("role"),
        "project": replacement.get("index_id"),
        "index_id": replacement.get("index_id"),
        "index_record_id": replacement.get("index_record_id"),
    }
    archived = {
        **previous_record,
        "superseded_at": replacement.get("recorded_at") or utc_now(),
        "replacement_role": replacement_binding["role"],
        "replacement_project": replacement_binding["project"],
        "replacement_index_id": replacement_binding["index_id"],
        "replacement_record_id": replacement_binding["index_record_id"],
        "replacement_index_record_id": replacement_binding[
            "index_record_id"
        ],
        "replacement": replacement_binding,
    }
    _repository_index_history(repo).append(archived)
    return previous_record, archived


def _recorded_index_change(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    role: str,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    previous_record, history_entry = _archive_replaced_index(
        repo, previous, role, replacement
    )
    return {
        "repository_id": repo.get("id"),
        "role": role,
        "previous": previous_record,
        "current": _copy_state(replacement),
        "history_entry": _copy_state(history_entry)
        if history_entry is not None
        else None,
    }


def _archived_workspace_indexes(repo: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for workspace in repo.get("workspace_history", []):
        if not isinstance(workspace, dict):
            continue
        archived = workspace.get("workspace_index")
        if isinstance(archived, dict):
            yield archived


def _assert_index_id_available(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    role: str,
    index_id: str,
) -> None:
    conflicts: list[dict[str, Any]] = []
    current_generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    for candidate in state_value.get("repositories", []):
        baseline = candidate.get("index")
        if isinstance(baseline, dict) and baseline.get("index_id") == index_id:
            same_role_refresh = (
                role == "baseline" and candidate.get("id") == repo.get("id")
            )
            if not same_role_refresh:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "baseline",
                        "recorded_project": index_id,
                    }
                )
        workspace = candidate.get("workspace_index")
        if isinstance(workspace, dict) and workspace.get("index_id") == index_id:
            same_current_record = (
                role == "workspace"
                and candidate.get("id") == repo.get("id")
                and workspace.get("workspace_generation")
                == current_generation
            )
            if not same_current_record:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace",
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for historical in _repository_index_history(candidate):
            if historical.get("index_id") != index_id:
                continue
            historical_role = historical.get("role")
            same_repository_role = (
                candidate.get("id") == repo.get("id")
                and historical_role == role
            )
            reusable_history = same_repository_role and (
                role == "baseline"
                or (
                    role == "workspace"
                    and historical.get("workspace_generation")
                    == current_generation
                )
            )
            if not reusable_history:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": historical_role,
                        "origin": "index-history",
                        "workspace_generation": historical.get(
                            "workspace_generation"
                        ),
                        "index_record_id": historical.get(
                            "index_record_id"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for archived in _archived_workspace_indexes(candidate):
            if archived.get("index_id") == index_id:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace-history",
                        "origin": "workspace-history",
                        "workspace_generation": archived.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
    if conflicts:
        error_code = (
            "WORKSPACE_INDEX_ID_CONFLICT"
            if role == "workspace"
            else "INDEX_ID_CONFLICT"
        )
        raise FlowError(
            error_code,
            "index project must be distinct across role/repository pairs and retired workspace generations",
            details={
                "repository_id": repo.get("id"),
                "role": role,
                "index_id": index_id,
                "conflicts": conflicts,
            },
        )


def command_record_index(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "record-index")
        role = args.role
        if role == "baseline":
            _assert_status(current, {"BASELINED", "INDEXED"}, "record-index")
        else:
            _assert_status(
                current,
                {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING"},
                "record-index --role workspace",
            )
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        metadata = _parse_json_object(args.metadata_json, "--metadata-json")
        degraded_approval: dict[str, Any] | None = None
        normalized_index_id = args.index_id.strip() if args.index_id else None
        if role == "workspace":
            if not normalized_index_id:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_REQUIRED",
                    "workspace indexes require a successful non-empty --index-id",
                )
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "workspace index metadata cannot record a failed index",
                )
            if metadata.get("persistence") is not False:
                raise FlowError(
                    "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
                    "workspace index metadata must explicitly set persistence=false",
                )
            _require_workspace_ready(current)
            if len(selected) > 1:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_CONFLICT",
                    "one workspace project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "workspace", normalized_index_id
            )
        elif normalized_index_id:
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "metadata status='failed' is only valid when --index-id is omitted",
                )
            if len(selected) > 1:
                raise FlowError(
                    "INDEX_ID_CONFLICT",
                    "one baseline project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "baseline", normalized_index_id
            )
        else:
            degraded_approval = _require_gate(current, "impact-degraded")
            _validate_degraded_index_metadata(metadata, degraded_approval)
        receipt = _index_receipt(args.receipt)
        index_changes: list[dict[str, Any]] = []
        for repo in selected:
            if role == "baseline":
                analysis_workspace = repo.get("analysis_workspace") or {}
                if not analysis_workspace.get("ready"):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_REQUIRED",
                        f"materialize the pinned baseline before recording an index: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "hint": "baseline --materialize",
                        },
                    )
                integrity_error = _analysis_workspace_integrity_error(repo)
                if integrity_error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        integrity_error,
                        details={"repository_id": repo["id"]},
                    )
                repo_path = Path(analysis_workspace["path"])
                expected_sha = repo["baseline"]["base_sha"]
                analysis_head = _git(repo_path, "rev-parse", "HEAD")
                analysis_branch = _git_optional(
                    repo_path,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                )
                status_available, analysis_status = _status_porcelain(repo_path)
                if (
                    analysis_head != expected_sha
                    or analysis_branch is not None
                    or not status_available
                    or analysis_status
                ):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        f"analysis worktree no longer exactly represents the pinned base: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_head": expected_sha,
                            "actual_head": analysis_head,
                            "actual_branch": analysis_branch,
                            "dirty": bool(analysis_status),
                        },
                    )
                commit_sha = args.commit or expected_sha
                resolved = _git_optional(
                    repo_path,
                    "rev-parse",
                    "--verify",
                    f"{commit_sha}^{{commit}}",
                )
                if not resolved:
                    raise FlowError(
                        "INVALID_COMMIT",
                        f"index commit does not exist in repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "commit": commit_sha,
                        },
                    )
                if resolved != expected_sha:
                    raise FlowError(
                        "INDEX_BASE_MISMATCH",
                        f"recorded index must target the pinned base for repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_commit": expected_sha,
                            "provided_commit": resolved,
                        },
                    )
                replacement = {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "index_record_id": str(uuid.uuid4()),
                    "recorded_at": utc_now(),
                    "role": "baseline",
                    "commit_sha": resolved,
                    "repo_path": str(repo_path),
                    "repo_path_identity": _serializable_path_identity(
                        repo_path
                    ),
                    "capability_profile_sha256": analysis_workspace.get(
                        "capability_profile_sha256"
                    ),
                    "fingerprint_sha256": analysis_workspace.get(
                        "fingerprint_sha256"
                    ),
                    "index_id": normalized_index_id,
                    "recommended_index_id": _recommended_index_name(
                        state_value, repo, "baseline"
                    ),
                    "receipt": receipt,
                    "metadata": metadata,
                    "impact_degraded_approval_id": (
                        degraded_approval.get("approval_id")
                        if degraded_approval
                        else None
                    ),
                }
                index_changes.append(
                    _recorded_index_change(
                        repo, repo.get("index"), "baseline", replacement
                    )
                )
                repo["index"] = replacement
                continue

            workspace = repo.get("workspace") or {}
            integrity_error = _workspace_integrity_error(state_value, repo)
            if integrity_error:
                raise FlowError(
                    "WORKSPACE_INTEGRITY_FAILED",
                    integrity_error,
                    details={"repository_id": repo["id"]},
                )
            repo_path = Path(workspace["path"]).resolve(strict=True)
            actual_branch = _git_optional(
                repo_path, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            actual_head = _git(repo_path, "rev-parse", "HEAD")
            commit_sha = args.commit or actual_head
            resolved = _git_optional(
                repo_path,
                "rev-parse",
                "--verify",
                f"{commit_sha}^{{commit}}",
            )
            if not resolved:
                raise FlowError(
                    "INVALID_COMMIT",
                    f"index commit does not exist in workspace {repo['id']}",
                    details={"repository_id": repo["id"], "commit": commit_sha},
                )
            if resolved != actual_head:
                raise FlowError(
                    "INDEX_WORKSPACE_MISMATCH",
                    f"workspace index must target the current HEAD for repository {repo['id']}",
                    details={
                        "repository_id": repo["id"],
                        "expected_head": actual_head,
                        "provided_commit": resolved,
                    },
                )
            generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            plan_sha = (
                (state_value.get("workspace") or {}).get("plan") or {}
            ).get("sha256")
            fingerprint = _fingerprint_repo(repo_path)
            replacement = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "index_record_id": str(uuid.uuid4()),
                "recorded_at": utc_now(),
                "role": "workspace",
                "commit_sha": actual_head,
                "repo_path": str(repo_path),
                "repo_path_identity": _serializable_path_identity(repo_path),
                "index_id": normalized_index_id,
                "recommended_index_id": _recommended_index_name(
                    state_value, repo, "workspace"
                ),
                "receipt": receipt,
                "metadata": metadata,
                "fingerprint_sha256": fingerprint["sha256"],
                "capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
                "workspace_generation": generation,
                "workspace_plan_sha256": plan_sha,
                "workspace_branch": actual_branch,
                "workspace_head_sha": actual_head,
            }
            index_changes.append(
                _recorded_index_change(
                    repo,
                    repo.get("workspace_index"),
                    "workspace",
                    replacement,
                )
            )
            repo["workspace_index"] = replacement
        if role == "baseline":
            all_indexed = all(
                repo.get("index") for repo in state_value["repositories"]
            )
            if all_indexed:
                state_value["status"] = "INDEXED"
        else:
            all_indexed = all(
                repo.get("workspace_index")
                for repo in state_value["repositories"]
            )
        _commit_state(
            current,
            state_value,
            task_dir,
            "index_recorded",
            {
                "role": role,
                "repository_ids": [repo["id"] for repo in selected],
                "complete": all_indexed,
                "index_records": index_changes,
            },
        )
    return _result(
        "record-index",
        state_value,
        role=role,
        complete=all_indexed,
        repositories=[
            {
                "id": repo["id"],
                "role": role,
                "repo_path": (
                    repo["analysis_workspace"]["path"]
                    if role == "baseline"
                    else repo["workspace"]["path"]
                ),
                "index": (
                    repo["index"]
                    if role == "baseline"
                    else repo["workspace_index"]
                ),
                **(
                    {"workspace_index": repo["workspace_index"]}
                    if role == "workspace"
                    else {}
                ),
            }
            for repo in selected
        ],
    )


def command_record_artifact(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    artifact_path = Path(args.path).expanduser().resolve(strict=True)
    metadata = _parse_json_object(args.metadata_json, "--metadata-json")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        artifact_hash = _hash_artifact(artifact_path)
        digest = artifact_hash["sha256"]
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "record-artifact")
        if args.kind in {"workspace-plan", "review-snapshot"}:
            raise FlowError(
                "RESERVED_ARTIFACT_KIND",
                f"{args.kind} is controller-generated and cannot be recorded manually",
                details={"kind": args.kind},
            )
        if args.kind != "review-report" and args.verdict:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--verdict is only valid with --kind review-report",
            )
        if args.kind == "review-report":
            _assert_status(current, {"REVIEWING"}, "record-artifact --kind review-report")
            if not args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--kind review-report requires --verdict PASS, CONDITIONAL or FAIL",
                )
            body_verdict = _parse_review_report_verdict(artifact_path)
            if body_verdict != args.verdict:
                raise FlowError(
                    "REVIEW_VERDICT_MISMATCH",
                    "--verdict does not match the review report's Verdict field",
                    details={
                        "path": str(artifact_path),
                        "body_verdict": body_verdict,
                        "verdict": args.verdict,
                    },
                )
            snapshot = _latest_review_snapshot(current)
            if not snapshot:
                raise FlowError(
                    "CURRENT_REVIEW_REQUIRED",
                    "record a review snapshot before recording a review report",
                )
            supplied_binding = metadata.get("review_snapshot_sha256")
            if supplied_binding and supplied_binding != snapshot.get("sha256"):
                raise FlowError(
                    "STALE_REVIEW_REPORT",
                    "review report metadata does not name the latest review snapshot",
                    details={
                        "expected_review_snapshot_sha256": snapshot.get("sha256"),
                        "provided_review_snapshot_sha256": supplied_binding,
                    },
                )
            metadata = dict(metadata)
            metadata["review_snapshot_sha256"] = snapshot["sha256"]
            supplied_verdict = metadata.get("verdict")
            if supplied_verdict and supplied_verdict != args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "review report metadata verdict conflicts with --verdict",
                    details={
                        "metadata_verdict": supplied_verdict,
                        "verdict": args.verdict,
                    },
                )
            metadata["verdict"] = args.verdict
        elif args.kind == "impact":
            _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "record-artifact --kind impact")
            index_provenance_sha = _index_provenance_sha256(current)
            impact_generation = int(current.get("impact_generation", 0))
            supplied_binding = metadata.get("index_provenance_sha256")
            if supplied_binding and supplied_binding != index_provenance_sha:
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata does not bind the current all-repository index provenance",
                    details={
                        "expected_index_provenance_sha256": index_provenance_sha,
                        "provided_index_provenance_sha256": supplied_binding,
                    },
                )
            supplied_generation = metadata.get("impact_generation")
            if (
                supplied_generation is not None
                and supplied_generation != impact_generation
            ):
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata names a stale impact generation",
                    details={
                        "expected_impact_generation": impact_generation,
                        "provided_impact_generation": supplied_generation,
                    },
                )
            metadata = dict(metadata)
            metadata["index_provenance_sha256"] = index_provenance_sha
            metadata["impact_generation"] = impact_generation
        elif args.kind in {"direct-contract", "openspec-plan"}:
            _assert_status(
                current,
                {"PLANNING"},
                f"record-artifact --kind {args.kind}",
            )
            if args.kind == "openspec-plan":
                _assert_openspec_plan_in_current_workspace(current, artifact_path)
            planning_context = _current_planning_context(current)
            planning_context_sha = _planning_context_sha256(planning_context)
            supplied_context = metadata.get("planning_context")
            supplied_context_sha = metadata.get("planning_context_sha256")
            if (
                supplied_context is not None
                and supplied_context != planning_context
            ) or (
                supplied_context_sha is not None
                and supplied_context_sha != planning_context_sha
            ):
                raise FlowError(
                    "STALE_PLAN",
                    "supplied plan metadata names a stale planning context",
                )
            metadata = dict(metadata)
            metadata["planning_context"] = planning_context
            metadata["planning_context_sha256"] = planning_context_sha
        final_artifact_hash = _hash_artifact(artifact_path)
        if final_artifact_hash != artifact_hash:
            raise FlowError(
                "ARTIFACT_CHANGED",
                "artifact changed while it was being recorded",
                details={"path": str(artifact_path)},
            )
        state_value = _copy_state(current)
        artifact = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "kind": args.kind,
            "path": str(artifact_path),
            "path_identity": _serializable_path_identity(artifact_path),
            "sha256": digest,
            "artifact_type": artifact_hash["artifact_type"],
            "size": artifact_hash["size"],
            "file_count": artifact_hash["file_count"],
            "total_size": artifact_hash["total_size"],
            "recorded_at": utc_now(),
            "metadata": metadata,
        }
        if "manifest_entry_count" in artifact_hash:
            artifact["manifest_entry_count"] = artifact_hash["manifest_entry_count"]
        state_value["artifacts"].append(artifact)
        if args.kind == "impact":
            state_value["route"] = None
            state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "artifact_recorded", {"artifact_id": artifact["artifact_id"], "kind": args.kind, "sha256": digest})
    return _result("record-artifact", state_value, artifact=artifact)


def command_set_route(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    route = args.route_option or args.route
    if route not in {"direct", "openspec"}:
        raise FlowError("INVALID_ARGUMENT", "route must be 'direct' or 'openspec'")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "set-route")
        _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "set-route")
        impact = _require_current_impact(current)
        state_value = _copy_state(current)
        state_value["route"] = {
            "value": route,
            "reason": args.reason,
            "set_at": utc_now(),
            "impact_artifact_id": impact["artifact_id"],
            "impact_sha256": impact["sha256"],
            "index_provenance_sha256": (impact.get("metadata") or {})[
                "index_provenance_sha256"
            ],
            "impact_generation": (impact.get("metadata") or {})[
                "impact_generation"
            ],
        }
        state_value["status"] = "IMPACT_REVIEW"
        state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "route_set", {"route": route, "reason": args.reason})
    return _result("set-route", state_value, route=state_value["route"])


def command_approve(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    if args.gate not in APPROVAL_GATES:
        # Rejected before the lock so an unknown gate cannot consume a
        # revision or leave a permanent approval behind.
        raise FlowError(
            "INVALID_ARGUMENT",
            "--gate must name a defined approval gate: "
            + ", ".join(APPROVAL_GATES),
            details={"gate": args.gate, "gates": list(APPROVAL_GATES)},
        )
    artifact_sha = args.artifact_sha256
    if artifact_sha and not SHA256_RE.fullmatch(artifact_sha):
        raise FlowError("INVALID_ARGUMENT", "--artifact-sha256 must be 64 lowercase hexadecimal characters")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "approve")
        if args.accept_conditional and args.gate != "review":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--accept-conditional is only valid for the review gate",
            )
        if args.allow_fetch and args.gate != "baseline-fetch":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-fetch is only valid for the baseline-fetch gate",
            )
        if args.allow_dirty and args.gate not in {"baseline-fetch", LITE_GATE}:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-dirty is only valid for the baseline-fetch and lite gates",
            )
        if artifact_sha and not any(item.get("sha256") == artifact_sha for item in current.get("artifacts", [])):
            raise FlowError("ARTIFACT_NOT_FOUND", "approval artifact hash is not recorded on this task", details={"sha256": artifact_sha})
        required_artifact_kind: str | None = None
        review_verdict: str | None = None
        baseline_remote_evidence: dict[str, Any] | None = None
        route_impact: dict[str, Any] | None = None
        plan_artifact: dict[str, Any] | None = None
        plan_context: dict[str, Any] | None = None
        lite_evidence: dict[str, Any] | None = None
        if args.gate in FULL_GATES:
            _assert_flow(current, "full", f"approve --gate {args.gate}")
        if args.gate == "route":
            _assert_status(current, {"IMPACT_REVIEW"}, "approve --gate route")
            _, route_impact = _require_current_route_selection(current)
            required_artifact_kind = "impact"
        elif args.gate == "plan":
            _assert_status(current, {"PLANNING"}, "approve --gate plan")
            route_value = (current.get("route") or {}).get("value")
            if route_value not in {"direct", "openspec"}:
                raise FlowError("ROUTE_REQUIRED", "an approved route is required before plan approval")
            required_artifact_kind = (
                "direct-contract" if route_value == "direct" else "openspec-plan"
            )
            plan_artifact, plan_context = _require_current_plan_artifact(
                current, required_artifact_kind
            )
        elif args.gate == "review":
            _assert_status(current, {"REVIEWING"}, "approve --gate review")
            required_artifact_kind = "review-report"
            review_report, _ = _require_review_report_for_latest_snapshot(current)
            review_verdict = (review_report.get("metadata") or {}).get("verdict")
            if review_verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
                raise FlowError(
                    "INVALID_REVIEW_VERDICT",
                    "latest review report has no valid structured verdict",
                    details={"verdict": review_verdict},
                )
            if review_verdict == "FAIL":
                raise FlowError(
                    "REVIEW_VERDICT_FAILED",
                    "a FAIL review report cannot be approved",
                )
            if review_verdict == "CONDITIONAL" and not args.accept_conditional:
                raise FlowError(
                    "CONDITIONAL_ACCEPTANCE_REQUIRED",
                    "approving a CONDITIONAL review requires --accept-conditional",
                )
            if review_verdict == "PASS" and args.accept_conditional:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--accept-conditional is not valid for a PASS review",
                )
        elif args.gate == "baseline-fetch":
            _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "approve --gate baseline-fetch")
            baseline_remote_evidence = _preflight_remote_evidence(current)
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "impact-degraded":
            _assert_status(
                current,
                {"BASELINED", "INDEXED"},
                "approve --gate impact-degraded",
            )
        elif args.gate == LITE_GATE:
            _assert_flow(current, "lite", "approve --gate lite")
            _assert_status(current, {"PREFLIGHTED"}, "approve --gate lite")
            lite_evidence = _lite_preflight_evidence(current)
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "workspace":
            _assert_status(current, {"ROUTE_APPROVED", "WORKSPACE_READY"}, "approve --gate workspace")
            required_artifact_kind = "workspace-plan"
        if required_artifact_kind:
            latest = _latest_artifact(current, required_artifact_kind)
            if not latest:
                raise FlowError(
                    "ARTIFACT_REQUIRED",
                    f"the {args.gate} gate requires a recorded {required_artifact_kind} artifact",
                    details={"gate": args.gate, "artifact_kind": required_artifact_kind},
                )
            _assert_artifact_unchanged(latest)
            if artifact_sha != latest.get("sha256"):
                raise FlowError(
                    "APPROVAL_ARTIFACT_MISMATCH",
                    f"the {args.gate} gate must bind the latest {required_artifact_kind} artifact",
                    details={
                        "gate": args.gate,
                        "artifact_kind": required_artifact_kind,
                        "expected_sha256": latest.get("sha256"),
                        "provided_sha256": artifact_sha,
                    },
                )
            if args.gate == "workspace":
                current_generation = int(
                    (current.get("workspace") or {}).get("generation", 0)
                )
                controller_plan = (
                    (current.get("workspace") or {}).get("plan") or {}
                )
                if (
                    (latest.get("metadata") or {}).get("workspace_generation")
                    != current_generation
                    or controller_plan.get("sha256") != latest.get("sha256")
                    or controller_plan.get("artifact_id")
                    != latest.get("artifact_id")
                    or controller_plan.get("path") != latest.get("path")
                ):
                    raise FlowError(
                        "STALE_WORKSPACE_PLAN",
                        "workspace plan is not current for this workspace generation",
                    )
        state_value = _copy_state(current)
        approval = {
            "approval_id": str(uuid.uuid4()),
            "gate": args.gate,
            "note": args.note,
            "artifact_sha256": artifact_sha,
            "approved_at": utc_now(),
            "approved_by": _actor(),
        }
        if args.gate == "review":
            approval["review_snapshot_sha256"] = _latest_review_snapshot(current)["sha256"]
            approval["review_verdict"] = review_verdict
            approval["conditional_accepted"] = bool(
                review_verdict == "CONDITIONAL" and args.accept_conditional
            )
        if args.gate == "baseline-fetch":
            approval["preflight_remote_sha256"] = _sha256_bytes(
                _json_bytes(baseline_remote_evidence)
            )
            approval["preflight_remotes"] = baseline_remote_evidence["repositories"]
            approval["fetch_allowed"] = bool(args.allow_fetch)
            approval["dirty_allowed"] = bool(args.allow_dirty)
        if args.gate == LITE_GATE:
            approval["preflight_evidence_sha256"] = _sha256_bytes(
                _json_bytes(lite_evidence)
            )
            approval["preflight_repositories"] = lite_evidence["repositories"]
            approval["dirty_allowed"] = bool(args.allow_dirty)
        if args.gate == "route":
            approval["artifact_id"] = route_impact["artifact_id"]
            approval["index_provenance_sha256"] = (
                route_impact.get("metadata") or {}
            )["index_provenance_sha256"]
            approval["impact_generation"] = (
                route_impact.get("metadata") or {}
            )["impact_generation"]
        if args.gate == "workspace":
            approval["artifact_id"] = latest["artifact_id"]
            approval["workspace_generation"] = (
                latest.get("metadata") or {}
            )["workspace_generation"]
        if args.gate == "plan":
            approval["artifact_id"] = plan_artifact["artifact_id"]
            approval["planning_context_sha256"] = _planning_context_sha256(
                plan_context
            )
        state_value["approvals"][args.gate] = approval
        if args.gate == "route":
            state_value["status"] = "ROUTE_APPROVED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "gate_approved",
            {
                "gate": args.gate,
                "artifact_sha256": artifact_sha,
                "approval": approval,
            },
        )
    return _result("approve", state_value, approval=approval)


def _parse_workspace_overrides(
    state_value: dict[str, Any],
    values: Sequence[str] | None,
    option: str,
    *,
    require_absolute_path: bool,
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values or []:
        selector, separator, supplied = raw.partition("=")
        if not separator or not selector or not supplied:
            raise FlowError(
                "INVALID_ARGUMENT",
                f"{option} must use REPOSITORY=VALUE",
                details={"value": raw},
            )
        repo = _repo_by_selector(state_value, [selector])[0]
        if repo["id"] in overrides:
            raise FlowError(
                "DUPLICATE_WORKSPACE_OVERRIDE",
                f"{option} repeats repository: {repo['id']}",
                details={"repository_id": repo["id"]},
            )
        if require_absolute_path:
            candidate = Path(supplied).expanduser()
            if not candidate.is_absolute():
                raise FlowError(
                    "INVALID_ARGUMENT",
                    f"{option} requires an absolute path",
                    details={"repository_id": repo["id"], "path": supplied},
                )
            supplied = str(candidate.resolve(strict=False))
        overrides[repo["id"]] = supplied
    return overrides


def _has_exact_workspace_claim(
    data_root: Path,
    state_value: dict[str, Any],
    repo: dict[str, Any],
    path: Path,
    branch: str,
) -> bool:
    registry = _load_workspace_registry(
        data_root, allow_legacy_container=True
    )
    generation = int((state_value.get("workspace") or {}).get("generation", 0))
    return any(
        isinstance(claim, dict)
        and claim.get("evidence_contract_version")
        == EVIDENCE_CONTRACT_VERSION
        and claim.get("task_id") == state_value.get("task_id")
        and claim.get("repository_id") == repo.get("id")
        and claim.get("workspace_generation") == generation
        and _recorded_path_matches(
            claim.get("path_identity"), claim.get("path"), path
        )
        and claim.get("branch") == branch
        for claim in registry.get("claims", [])
    )


def _containing_git_worktree(path: Path) -> Path | None:
    ancestor = path.resolve(strict=False)
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        return None
    root = _git_optional(ancestor, "rev-parse", "--show-toplevel")
    return Path(root).resolve(strict=False) if root else None


def _branch_ref_state(
    source: Path, branch: str, protected_branches: Sequence[str]
) -> dict[str, Any]:
    branch_ref = f"refs/heads/{branch}"
    common_dir = _git_common_dir(source)
    ref_case_sensitive = _probe_filesystem_case_sensitive(common_dir)
    ref_unicode_distinct = _probe_filesystem_unicode_distinct(common_dir)
    output = _git(
        source,
        "for-each-ref",
        "--format=%(refname)%09%(objectname)",
        "refs/heads",
        text=False,
    )
    refs: dict[str, str] = {}
    for line in output.splitlines():
        ref_name_bytes, separator, object_id_bytes = line.partition(b"\t")
        if (
            not separator
            or not ref_name_bytes
            or not object_id_bytes
        ):
            raise FlowError(
                "GIT_EVIDENCE_MALFORMED",
                "Git returned malformed local-ref identity evidence",
                details={
                    "repository": str(source),
                    "record_hex": line.hex(),
                },
            )
        try:
            ref_name = ref_name_bytes.decode("utf-8", "strict")
            object_id = object_id_bytes.decode("ascii", "strict")
        except UnicodeError as exc:
            raise FlowError(
                "REF_IDENTITY_UNAVAILABLE",
                "local ref identity is not representable losslessly",
                details={
                    "repository": str(source),
                    "record_hex": line.hex(),
                },
            ) from exc
        refs[ref_name] = object_id

    def alias(value: str) -> str:
        normalized = (
            value
            if ref_unicode_distinct
            else unicodedata.normalize("NFC", value)
        )
        return normalized if ref_case_sensitive else normalized.casefold()

    protected_refs = {f"refs/heads/{item}" for item in protected_branches}
    if any(alias(item) == alias(branch_ref) for item in protected_refs):
        raise FlowError(
            "PROTECTED_BRANCH",
            f"workspace branch aliases a protected branch: {branch}",
            details={
                "repository": str(source),
                "branch": branch,
                "branch_ref": branch_ref,
                "ref_case_sensitive": ref_case_sensitive,
                "ref_unicode_normalization_distinct": ref_unicode_distinct,
            },
        )
    for existing_ref in refs:
        if existing_ref == branch_ref:
            continue
        filesystem_alias = alias(existing_ref) == alias(branch_ref)
        directory_file_alias = (
            existing_ref.startswith(f"{branch_ref}/")
            or branch_ref.startswith(f"{existing_ref}/")
        )
        if filesystem_alias or directory_file_alias:
            raise FlowError(
                "WORKSPACE_REF_COLLISION",
                "workspace branch is path-equivalent to an incompatible existing ref",
                details={
                    "repository": str(source),
                    "branch_ref": branch_ref,
                    "existing_ref": existing_ref,
                    "ref_case_sensitive": ref_case_sensitive,
                    "ref_unicode_normalization_distinct": ref_unicode_distinct,
                    "collision": (
                        "filesystem_alias"
                        if filesystem_alias
                        else "directory_file_alias"
                    ),
                },
            )
    return {
        "branch_ref": branch_ref,
        "planned_ref_oid": refs.get(branch_ref),
        "ref_case_sensitive": ref_case_sensitive,
        "ref_unicode_normalization_distinct": ref_unicode_distinct,
        "git_common_dir": str(common_dir),
        "git_common_dir_identity": _serializable_path_identity(common_dir),
    }


def _workspace_plan(
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    data_root: Path,
    branch_override: str | None,
    path_override: str | None,
    branch_overrides: dict[str, str] | None = None,
    path_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if path_override and len(selected) != 1:
        raise FlowError("INVALID_ARGUMENT", "--path can only be used when exactly one repository is selected")
    plans: list[dict[str, Any]] = []
    branch_overrides = branch_overrides or {}
    path_overrides = path_overrides or {}
    generation = int((state_value.get("workspace") or {}).get("generation", 0))
    resolved_data_root = data_root.resolve(strict=False)
    managed_generation_root = (
        resolved_data_root
        / "workspaces"
        / state_value["task_id"]
        / (f"r{generation}" if generation else "")
    ).resolve(strict=False)
    for repo in selected:
        baseline = _require_current_evidence(repo.get("baseline"), "baseline")
        source_repo = Path(repo["path"]).resolve(strict=True)
        source_capability_profile = _git_capability_profile(source_repo)
        if (
            baseline.get("capability_profile_sha256")
            != source_capability_profile["sha256"]
        ):
            raise FlowError(
                "GIT_CAPABILITY_CHANGED",
                "repository capabilities changed after the approved baseline",
                details={
                    "repository_id": repo["id"],
                    "baseline_capability_profile_sha256": baseline.get(
                        "capability_profile_sha256"
                    ),
                    "current_capability_profile_sha256": (
                        source_capability_profile["sha256"]
                    ),
                },
            )
        default_branch = f"codex/{state_value['task_id']}"
        if generation:
            default_branch = f"{default_branch}-r{generation}"
        branch = branch_overrides.get(repo["id"]) or branch_override or default_branch
        protected = set(repo.get("protected_branches", DEFAULT_PROTECTED_BRANCHES))
        base_branch = (repo.get("baseline") or {}).get("base_branch")
        if branch in protected or branch == base_branch:
            raise FlowError(
                "PROTECTED_BRANCH",
                f"workspace branch is protected or is the base branch: {branch}",
                details={"repository_id": repo["id"], "branch": branch},
            )
        if (
            _run(
                ["git", "check-ref-format", "--branch", branch],
                check=False,
            ).returncode
            != 0
        ):
            raise FlowError(
                "INVALID_WORKSPACE_BRANCH",
                f"workspace branch name is invalid: {branch}",
                details={"repository_id": repo["id"], "branch": branch},
            )
        protected_ref_names = set(protected)
        if base_branch:
            protected_ref_names.add(base_branch)
        branch_state = _branch_ref_state(
            source_repo, branch, sorted(protected_ref_names)
        )
        symbolic_target = _git_optional(
            source_repo,
            "symbolic-ref",
            "--quiet",
            f"refs/heads/{branch}",
        )
        if symbolic_target:
            raise FlowError(
                "SYMBOLIC_WORKSPACE_BRANCH",
                "workspace branch refs must be direct refs, not symbolic refs",
                details={
                    "repository_id": repo["id"],
                    "branch": branch,
                    "symbolic_target": symbolic_target,
                },
            )
        explicit_path = repo["id"] in path_overrides or bool(path_override)
        managed_repository_root = (
            managed_generation_root / repo["id"]
        ).resolve(strict=False)
        if repo["id"] in path_overrides:
            path = Path(path_overrides[repo["id"]]).resolve(strict=False)
        elif path_override:
            path = Path(path_override).expanduser().resolve(strict=False)
        elif generation:
            path = data_root / "workspaces" / state_value["task_id"] / f"r{generation}" / repo["id"]
        else:
            path = data_root / "workspaces" / state_value["task_id"] / repo["id"]
        capability_profile = _git_capability_profile(source_repo, path)
        recorded = repo.get("workspace") or {}
        exact_recorded = bool(
            recorded.get("ready")
            and _recorded_path_matches(
                recorded.get("path_identity"),
                recorded.get("path"),
                path,
            )
            and recorded.get("branch") == branch
            and recorded.get("workspace_generation") == generation
        )
        exact_claimed = _has_exact_workspace_claim(
            data_root, state_value, repo, path, branch
        )
        for retired in repo.get("workspace_history", []):
            retired_path_value = retired.get("path")
            retired_path = (
                Path(retired_path_value).resolve(strict=False)
                if retired_path_value
                else None
            )
            if (
                retired_path is not None
                and _recorded_path_matches(
                    retired.get("path_identity"),
                    retired.get("path"),
                    path,
                )
            ) or retired.get("branch") == branch:
                raise FlowError(
                    "RETIRED_WORKSPACE_REUSE",
                    "a retired workspace path or branch cannot be reused",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "branch": branch,
                        "retired_path": retired.get("path"),
                        "retired_branch": retired.get("branch"),
                    },
                )
        if _is_within(resolved_data_root, path):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace path cannot be the controller data root or one of its ancestors",
                details={"repository_id": repo["id"], "path": str(path)},
            )
        if (
            explicit_path
            and _is_within(path, resolved_data_root)
            and not _is_within(path, managed_repository_root)
        ):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace overrides inside controller data must stay in this task and generation namespace",
                details={
                    "repository_id": repo["id"],
                    "path": str(path),
                    "managed_namespace": str(managed_repository_root),
                },
            )
        for reserved in (
            (data_root / "tasks").resolve(strict=False),
            (data_root / "analysis").resolve(strict=False),
        ):
            if _is_within(path, reserved) or _is_within(reserved, path):
                raise FlowError(
                    "WORKSPACE_NOT_ISOLATED",
                    "implementation workspace must be independent from controller and analysis data",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "reserved_path": str(reserved),
                    },
                )
        for configured_repo in state_value.get("repositories", []):
            configured_source = Path(configured_repo["path"]).resolve(
                strict=False
            )
            if _is_within(path, configured_source) or _is_within(
                configured_source, path
            ):
                raise FlowError(
                    "WORKSPACE_NOT_ISOLATED",
                    "workspace path must be independent from every source checkout",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "source_path": str(configured_source),
                    },
                )
            analysis = configured_repo.get("analysis_workspace") or {}
            if analysis.get("path"):
                analysis_path = Path(analysis["path"]).resolve(strict=False)
                if _is_within(path, analysis_path) or _is_within(analysis_path, path):
                    raise FlowError(
                        "WORKSPACE_NOT_ISOLATED",
                        "implementation workspace must be independent from every analysis worktree",
                        details={
                            "repository_id": repo["id"],
                            "path": str(path),
                            "analysis_path": str(analysis_path),
                        },
                    )
            for entry in _worktree_entries(Path(configured_repo["path"])):
                entry_path_value = entry.get("worktree")
                if not entry_path_value:
                    continue
                entry_path = Path(entry_path_value).resolve(strict=False)
                exact_allowed = bool(
                    _same_path(entry_path, path)
                    and configured_repo.get("id") == repo.get("id")
                    and (exact_recorded or exact_claimed)
                )
                if not exact_allowed and (
                    _is_within(path, entry_path) or _is_within(entry_path, path)
                ):
                    raise FlowError(
                        "WORKSPACE_NOT_ISOLATED",
                        "workspace path overlaps an existing registered Git worktree",
                        details={
                            "repository_id": repo["id"],
                            "path": str(path),
                            "existing_worktree": str(entry_path),
                        },
                    )
        containing_root = _containing_git_worktree(path)
        if containing_root and not (
            _same_path(containing_root, path)
            and (exact_recorded or exact_claimed)
        ):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace path is nested in an existing Git worktree",
                details={
                    "repository_id": repo["id"],
                    "path": str(path),
                    "existing_worktree": str(containing_root),
                },
            )
        base_sha = (repo.get("baseline") or {}).get("base_sha")
        if not base_sha:
            raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
        plans.append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "source_identity": _serializable_path_identity(source_repo),
                "path": str(path),
                "path_identity": _serializable_path_identity(path),
                "branch": branch,
                "branch_ref": branch_state["branch_ref"],
                "planned_ref_oid": (
                    recorded.get("planned_ref_oid")
                    if exact_recorded
                    else branch_state["planned_ref_oid"]
                ),
                "ref_case_sensitive": branch_state["ref_case_sensitive"],
                "ref_unicode_normalization_distinct": branch_state[
                    "ref_unicode_normalization_distinct"
                ],
                "source_common_dir": branch_state["git_common_dir"],
                "source_common_dir_identity": branch_state[
                    "git_common_dir_identity"
                ],
                "base_sha": base_sha,
                "capability_profile": capability_profile,
                "capability_profile_sha256": capability_profile["sha256"],
                "source_capability_profile_sha256": (
                    source_capability_profile["sha256"]
                ),
                "strategy": "worktree",
                "owner_task_id": state_value["task_id"],
                "workspace_generation": generation,
                "previously_recorded": bool(
                    recorded.get("ready")
                    and _recorded_path_matches(
                        recorded.get("path_identity"),
                        recorded.get("path"),
                        path,
                    )
                    and recorded.get("branch") == branch
                    and recorded.get("base_sha") == base_sha
                ),
            }
        )
    for index, plan in enumerate(plans):
        plan_path = Path(plan["path"])
        for other in plans[index + 1 :]:
            other_path = Path(other["path"])
            if _is_within(plan_path, other_path) or _is_within(other_path, plan_path):
                raise FlowError(
                    "WORKSPACE_PLAN_COLLISION",
                    "workspace paths for different repositories must be independent",
                    details={"path": str(plan_path), "other_path": str(other_path)},
                )
    return plans


def _workspace_plan_evidence(
    state_value: dict[str, Any], plans: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    evidence_repositories = [
        {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "repository_id": plan["repository_id"],
            "source_path": plan["source_path"],
            "source_identity": plan["source_identity"],
            "path": plan["path"],
            # The approval digest must survive the expected transition from a
            # planned path (identified through its nearest existing ancestor)
            # to a materialized directory (which has its own file ID).  Live
            # ownership checks retain and revalidate the complete identities.
            "path_identity": _capability_path_identity(
                Path(plan["path"])
            ),
            "branch": plan["branch"],
            "branch_ref": plan["branch_ref"],
            "planned_ref_oid": plan["planned_ref_oid"],
            "ref_case_sensitive": plan["ref_case_sensitive"],
            "ref_unicode_normalization_distinct": plan[
                "ref_unicode_normalization_distinct"
            ],
            "source_common_dir": plan["source_common_dir"],
            "source_common_dir_identity": plan[
                "source_common_dir_identity"
            ],
            "base_sha": plan["base_sha"],
            "capability_profile_sha256": plan[
                "capability_profile_sha256"
            ],
            "source_capability_profile_sha256": plan[
                "source_capability_profile_sha256"
            ],
            "strategy": "worktree",
        }
        for plan in plans
    ]
    evidence_repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "strategy": "worktree",
        "workspace_generation": int(
            (state_value.get("workspace") or {}).get("generation", 0)
        ),
        "repositories": evidence_repositories,
    }


def _worktree_entries(repo: Path) -> list[dict[str, str]]:
    output = _git(repo, "worktree", "list", "--porcelain", "-z", text=False)
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for field in output.split(b"\0") + [b""]:
        if not field:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = field.partition(b" ")
        current[key.decode("ascii", "replace")] = os.fsdecode(value)
    return entries


def _assert_workspace_plan_claim(plan: dict[str, Any]) -> None:
    receipt = plan.get("workspace_claim") or {}
    registry_path_value = receipt.get("registry_path")
    claim_id = receipt.get("claim_id")
    if not registry_path_value or not claim_id:
        raise FlowError(
            "WORKSPACE_OWNERSHIP_CONFLICT",
            "workspace plan has no durable ownership receipt",
            details={"repository_id": plan.get("repository_id")},
        )
    registry_path = Path(str(registry_path_value))
    if not _recorded_path_matches(
        receipt.get("registry_identity"), registry_path_value, registry_path
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry path identity changed",
            details={"path": str(registry_path)},
        )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry cannot be revalidated",
            details={"path": str(registry_path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != SCHEMA_VERSION
        or not isinstance(registry.get("claims"), list)
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has an invalid structure",
            details={"path": str(registry_path)},
        )
    _assert_supported_evidence_versions(registry)
    _require_current_evidence(registry, "workspace registry")
    claim = next(
        (
            item
            for item in registry.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    _require_current_evidence(claim, "workspace ownership claim")
    destination = Path(plan["path"])
    source = Path(plan["source_path"])
    if (
        not claim
        or claim.get("task_id") != plan.get("owner_task_id")
        or claim.get("repository_id") != plan.get("repository_id")
        or not _recorded_path_matches(
            claim.get("path_identity"), claim.get("path"), destination
        )
        or not _recorded_path_matches(
            claim.get("source_identity"), claim.get("source_path"), source
        )
        or claim.get("branch_ref") != plan.get("branch_ref")
        or claim.get("planned_ref_oid") != plan.get("planned_ref_oid")
        or claim.get("ref_case_sensitive")
        != plan.get("ref_case_sensitive")
        or claim.get("ref_unicode_normalization_distinct")
        != plan.get("ref_unicode_normalization_distinct")
        or claim.get("plan_sha256") != receipt.get("plan_sha256")
    ):
        raise FlowError(
            "WORKSPACE_OWNERSHIP_CONFLICT",
            "workspace ownership claim changed after plan approval",
            details={
                "repository_id": plan.get("repository_id"),
                "claim_id": claim_id,
                "registry_path": str(registry_path),
            },
        )


def _workspace_outcome(
    plan: dict[str, Any],
    *,
    created: bool,
    head_sha: str,
    recovered_unrecorded: bool = False,
) -> dict[str, Any]:
    destination = Path(plan["path"]).resolve(strict=True)
    fingerprint = _fingerprint_repo(destination)
    if fingerprint["capability_profile_sha256"] != plan.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "WORKSPACE_VERIFY_FAILED",
            "materialized worktree capability profile differs from the approved plan",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "capability_profile_sha256"
                ),
                "actual_capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
            },
        )
    return {
        **plan,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": True,
        "created": created,
        "head_sha": head_sha,
        "recovered_unrecorded": recovered_unrecorded,
        "path_identity": _serializable_path_identity(destination),
        "source_identity": _serializable_path_identity(
            Path(plan["source_path"])
        ),
        "capability_profile": fingerprint["capability_profile"],
        "capability_profile_sha256": fingerprint[
            "capability_profile_sha256"
        ],
        "fingerprint_sha256": fingerprint["sha256"],
        "tracked_worktree_manifest_sha256": fingerprint[
            "tracked_worktree_manifest_sha256"
        ],
    }


def _execute_worktree(plan: dict[str, Any]) -> dict[str, Any]:
    _require_current_evidence(plan, "workspace plan")
    source = Path(plan["source_path"]).resolve(strict=True)
    if not _recorded_path_matches(
        plan.get("source_identity"), plan.get("source_path"), source
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace plan source identity changed before mutation",
            details={"repository_id": plan.get("repository_id")},
        )
    _assert_evidence_supported(source)
    _assert_tree_checkout_supported(source, plan["base_sha"])
    destination = Path(plan["path"]).resolve(strict=False)
    if not _recorded_path_matches(
        plan.get("path_identity"), plan.get("path"), destination
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace destination identity changed before mutation",
            details={"repository_id": plan.get("repository_id")},
        )
    current_source_profile = _git_capability_profile(source)
    if current_source_profile["sha256"] != plan.get(
        "source_capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "source repository capabilities changed after workspace approval",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "source_capability_profile_sha256"
                ),
                "current_capability_profile_sha256": (
                    current_source_profile["sha256"]
                ),
            },
        )
    current_workspace_profile = _git_capability_profile(source, destination)
    if current_workspace_profile["sha256"] != plan.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "workspace filesystem capabilities changed after approval",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "capability_profile_sha256"
                ),
                "current_capability_profile_sha256": (
                    current_workspace_profile["sha256"]
                ),
            },
        )
    if (
        _run(
            ["git", "-C", str(source), "cat-file", "-e", f"{plan['base_sha']}^{{commit}}"],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "WORKSPACE_BASE_MISMATCH",
            "approved workspace base object is no longer available",
            details={
                "repository_id": plan.get("repository_id"),
                "base_sha": plan.get("base_sha"),
            },
        )
    branch = plan["branch"]
    branch_ref = plan.get("branch_ref") or f"refs/heads/{branch}"
    if branch_ref != f"refs/heads/{branch}":
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace branch and full ref identity disagree",
            details={"branch": branch, "branch_ref": branch_ref},
        )
    previously_recorded = bool(plan.get("previously_recorded"))
    current_branch_state = _branch_ref_state(source, branch, [])
    current_ref_oid = current_branch_state["planned_ref_oid"]
    if (
        (
            not previously_recorded
            and current_ref_oid != plan.get("planned_ref_oid")
        )
        or current_branch_state["branch_ref"] != branch_ref
        or current_branch_state["ref_case_sensitive"]
        != plan.get("ref_case_sensitive")
        or current_branch_state["ref_unicode_normalization_distinct"]
        != plan.get("ref_unicode_normalization_distinct")
        or not _path_identity_equal(
            current_branch_state["git_common_dir_identity"],
            plan.get("source_common_dir_identity"),
        )
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace branch or ref-storage identity changed after plan approval",
            details={
                "branch_ref": branch_ref,
                "planned_ref_oid": plan.get("planned_ref_oid"),
                "current_ref_oid": current_ref_oid,
                "planned_ref_case_sensitive": plan.get(
                    "ref_case_sensitive"
                ),
                "current_ref_case_sensitive": current_branch_state[
                    "ref_case_sensitive"
                ],
            },
        )
    _assert_workspace_plan_claim(plan)
    registry_path = Path(
        str((plan.get("workspace_claim") or {}).get("registry_path"))
    )
    managed_destination = _is_within(destination, registry_path.parent)
    entries = _worktree_entries(source)
    branch_entry = next((entry for entry in entries if entry.get("branch") == branch_ref), None)
    destination_entry = next(
        (
            entry
            for entry in entries
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        actual_branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        actual_head = _git_optional(destination, "rev-parse", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _same_path(
                    _git_common_dir(destination), _git_common_dir(source)
                )
                linked_worktree = _is_linked_worktree(destination)
            except (FlowError, OSError):
                same_common_dir = False
        base_is_ancestor = (
            _run(
                [
                    "git",
                    "-C",
                    str(destination),
                    "merge-base",
                    "--is-ancestor",
                    plan["base_sha"],
                    "HEAD",
                ],
                check=False,
            ).returncode
            == 0
        )
        head_is_acceptable = (
            base_is_ancestor if previously_recorded else actual_head == plan["base_sha"]
        )
        unrecorded_is_clean = status_available and not status_porcelain
        if (
            not root
            or not _same_path(Path(root), destination)
            or not same_common_dir
            or not linked_worktree
            or actual_branch != branch
            or not head_is_acceptable
            or not destination_entry
            or destination_entry.get("branch") != branch_ref
            or destination_entry.get("HEAD") != actual_head
            or not unrecorded_is_clean
        ):
            reason = (
                "unrecorded_worktree_not_clean"
                if not previously_recorded and not unrecorded_is_clean
                else "workspace_integrity_mismatch"
            )
            raise FlowError(
                "WORKSPACE_COLLISION",
                f"workspace path exists but is not the requested worktree: {destination}",
                details={
                    "path": str(destination),
                    "actual_root": root,
                    "expected_branch": branch,
                    "actual_branch": actual_branch,
                    "expected_base": plan["base_sha"],
                    "actual_head": actual_head,
                    "same_common_dir": same_common_dir,
                    "linked_worktree": linked_worktree,
                    "previously_recorded": previously_recorded,
                    "recovery_candidate_clean": unrecorded_is_clean,
                    "dirty": bool(status_porcelain),
                    "status_porcelain": status_porcelain,
                    "reason": reason,
                },
            )
        if managed_destination:
            _set_private_permissions(destination, 0o700)
        return _workspace_outcome(
            plan,
            created=False,
            head_sha=actual_head,
            recovered_unrecorded=not previously_recorded,
        )
    if destination_entry:
        raise FlowError("WORKSPACE_COLLISION", f"Git reports the workspace path but it is unavailable: {destination}", details={"path": str(destination)})
    if branch_entry:
        raise FlowError(
            "BRANCH_ALREADY_CHECKED_OUT",
            f"workspace branch is already checked out elsewhere: {branch}",
            details={"branch": branch, "path": branch_entry.get("worktree")},
        )
    symbolic_target = _git_optional(
        source, "symbolic-ref", "--quiet", branch_ref
    )
    if symbolic_target:
        raise FlowError(
            "SYMBOLIC_WORKSPACE_BRANCH",
            "workspace branch refs must be direct refs, not symbolic refs",
            details={
                "branch": branch,
                "symbolic_target": symbolic_target,
            },
        )
    if managed_destination:
        _ensure_private_dir(destination.parent)
    else:
        _ensure_dir(destination.parent)
    if _ref_exists(source, branch_ref):
        branch_head = _git(source, "rev-parse", branch_ref)
        if previously_recorded:
            base_is_ancestor = (
                _run(
                    [
                        "git",
                        "-C",
                        str(source),
                        "merge-base",
                        "--is-ancestor",
                        plan["base_sha"],
                        branch_ref,
                    ],
                    check=False,
                ).returncode
                == 0
            )
            acceptable = base_is_ancestor
        else:
            acceptable = branch_head == plan["base_sha"]
        if not acceptable:
            raise FlowError(
                "WORKSPACE_BASE_MISMATCH",
                f"existing workspace branch is not at the approved base: {branch}",
                details={
                    "branch": branch,
                    "expected_base": plan["base_sha"],
                    "actual_head": branch_head,
                    "previously_recorded": previously_recorded,
                },
            )
        _git_mutating(
            source,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            str(destination),
            branch,
        )
    else:
        _git_mutating(
            source,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            "-b",
            branch,
            str(destination),
            plan["base_sha"],
        )
    actual_root = _git_optional(destination, "rev-parse", "--show-toplevel")
    actual_branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
    actual_head = _git_optional(destination, "rev-parse", "HEAD")
    status_available, status_porcelain = _status_porcelain(destination)
    created_entry = next(
        (
            entry
            for entry in _worktree_entries(source)
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if (
        not actual_root
        or not _same_path(Path(actual_root), destination)
        or actual_branch != branch
        or actual_head != plan["base_sha"]
        or not _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
        or not _is_linked_worktree(destination)
        or not status_available
        or bool(status_porcelain)
        or not created_entry
        or created_entry.get("branch") != branch_ref
        or created_entry.get("HEAD") != actual_head
    ):
        raise FlowError(
            "WORKSPACE_VERIFY_FAILED",
            f"created worktree failed branch, ownership or cleanliness verification: {destination}",
            details={
                "expected_branch": branch,
                "actual_branch": actual_branch,
                "expected_head": plan["base_sha"],
                "actual_head": actual_head,
                "dirty": bool(status_porcelain),
                "status_porcelain": status_porcelain,
            },
        )
    if managed_destination:
        _set_private_permissions(destination, 0o700)
    return _workspace_outcome(
        plan, created=True, head_sha=actual_head
    )


def _workspace_claim_integrity_error(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> str | None:
    workspace = repo.get("workspace") or {}
    receipt = workspace.get("workspace_claim") or {}
    try:
        _require_current_evidence(workspace, "workspace")
        _require_current_evidence(receipt, "workspace claim receipt")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    registry_path_value = receipt.get("registry_path")
    claim_id = receipt.get("claim_id")
    if not registry_path_value or not claim_id:
        return f"workspace has no durable ownership claim: {repo.get('id')}"
    registry_path = Path(registry_path_value)
    if not _recorded_path_matches(
        receipt.get("registry_identity"),
        registry_path_value,
        registry_path,
    ):
        return f"workspace ownership registry identity changed: {repo.get('id')}"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"workspace ownership registry cannot be read: {repo.get('id')}: {exc}"
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != SCHEMA_VERSION
        or not isinstance(registry.get("claims"), list)
    ):
        return f"workspace ownership registry has an invalid structure: {repo.get('id')}"
    try:
        _assert_supported_evidence_versions(registry)
        _require_current_evidence(registry, "workspace registry")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    claim = next(
        (
            item
            for item in registry.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    try:
        _require_current_evidence(claim, "workspace ownership claim")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    expected_plan_sha = ((state_value.get("workspace") or {}).get("plan") or {}).get(
        "sha256"
    )
    expected_source = str(Path(repo.get("path", "")).resolve(strict=False))
    expected_common_dir = _source_common_dir_for_claim(repo.get("path"))
    expected_workspace_path = Path(
        workspace.get("path", "")
    ).resolve(strict=False)
    expected_source_path = Path(expected_source)
    expected_common_path = Path(expected_common_dir)
    try:
        _require_current_evidence(claim, "workspace ownership claim")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    if (
        not claim
        or claim.get("task_id") != state_value.get("task_id")
        or claim.get("repository_id") != repo.get("id")
        or not _recorded_path_matches(
            claim.get("source_identity"),
            claim.get("source_path"),
            expected_source_path,
        )
        or not _recorded_path_matches(
            claim.get("source_common_dir_identity"),
            claim.get("source_common_dir"),
            expected_common_path,
        )
        or not _recorded_path_matches(
            claim.get("path_identity"),
            claim.get("path"),
            expected_workspace_path,
        )
        or claim.get("branch") != workspace.get("branch")
        or claim.get("branch_ref") != workspace.get("branch_ref")
        or claim.get("planned_ref_oid") != workspace.get("planned_ref_oid")
        or claim.get("ref_case_sensitive")
        != workspace.get("ref_case_sensitive")
        or claim.get("ref_unicode_normalization_distinct")
        != workspace.get("ref_unicode_normalization_distinct")
        or claim.get("workspace_generation")
        != int((state_value.get("workspace") or {}).get("generation", 0))
        or claim.get("plan_sha256") != expected_plan_sha
        or receipt.get("plan_sha256") != expected_plan_sha
    ):
        return f"workspace durable ownership claim is stale or mismatched: {repo.get('id')}"
    return None


def _workspace_integrity_error(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> str | None:
    workspace = repo.get("workspace") or {}
    try:
        _require_current_evidence(workspace, "workspace")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    if not workspace.get("ready"):
        return f"workspace is not ready: {repo.get('id')}"
    if workspace.get("owner_task_id") != state_value.get("task_id"):
        return f"workspace ownership does not match task: {repo.get('id')}"
    if workspace.get("workspace_generation") != int(
        (state_value.get("workspace") or {}).get("generation", 0)
    ):
        return f"workspace generation does not match task: {repo.get('id')}"
    claim_error = _workspace_claim_integrity_error(state_value, repo)
    if claim_error:
        return claim_error
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(workspace.get("path", "")).resolve(strict=False)
    if not _recorded_path_matches(
        workspace.get("source_identity"), repo.get("path"), source
    ):
        return f"workspace source filesystem identity changed: {repo.get('id')}"
    if not _recorded_path_matches(
        workspace.get("path_identity"), workspace.get("path"), path
    ):
        return f"workspace filesystem identity changed: {repo.get('id')}"
    for configured_repo in state_value.get("repositories", []):
        configured_source = Path(configured_repo["path"]).resolve(strict=False)
        if _is_within(path, configured_source) or _is_within(configured_source, path):
            return f"workspace is not independent from source checkout: {repo.get('id')}"
        analysis = configured_repo.get("analysis_workspace") or {}
        if analysis.get("path"):
            analysis_path = Path(analysis["path"]).resolve(strict=False)
            if _is_within(path, analysis_path) or _is_within(analysis_path, path):
                return f"workspace is not independent from analysis worktree: {repo.get('id')}"
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    if not root or not _same_path(Path(root), path):
        return f"workspace path is not a Git worktree root: {repo.get('id')}"
    try:
        if not _same_path(_git_common_dir(path), _git_common_dir(source)):
            return f"workspace belongs to a different Git repository: {repo.get('id')}"
        if not _is_linked_worktree(path):
            return f"workspace is not a linked worktree: {repo.get('id')}"
        source_profile = _git_capability_profile(source)
        workspace_profile = _git_capability_profile(path)
        if source_profile["sha256"] != workspace.get(
            "source_capability_profile_sha256"
        ):
            return f"source capability profile changed: {repo.get('id')}"
        if workspace_profile["sha256"] != workspace.get(
            "capability_profile_sha256"
        ):
            return f"workspace capability profile changed: {repo.get('id')}"
        branch_state = _branch_ref_state(
            source, str(workspace.get("branch")), []
        )
        if (
            branch_state.get("branch_ref")
            != workspace.get("branch_ref")
            or branch_state.get("ref_case_sensitive")
            != workspace.get("ref_case_sensitive")
            or branch_state.get("ref_unicode_normalization_distinct")
            != workspace.get("ref_unicode_normalization_distinct")
            or not _path_identity_equal(
                branch_state.get("git_common_dir_identity"),
                workspace.get("source_common_dir_identity"),
            )
        ):
            return f"workspace ref-storage identity changed: {repo.get('id')}"
    except (FlowError, OSError) as exc:
        return f"workspace Git ownership cannot be verified: {repo.get('id')}: {exc}"
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != workspace.get("branch"):
        return f"workspace branch changed: {repo.get('id')}"
    head = _git_optional(path, "rev-parse", "HEAD")
    base_sha = workspace.get("base_sha")
    if not head or not base_sha:
        return f"workspace HEAD/base metadata is incomplete: {repo.get('id')}"
    if (
        _run(
            ["git", "-C", str(path), "merge-base", "--is-ancestor", base_sha, "HEAD"],
            check=False,
        ).returncode
        != 0
    ):
        return f"workspace HEAD no longer descends from approved base: {repo.get('id')}"
    expected_ref = workspace.get("branch_ref")
    if expected_ref != f"refs/heads/{workspace.get('branch')}":
        return f"workspace full ref identity is invalid: {repo.get('id')}"
    resolved_ref = _git_optional(
        source, "rev-parse", "--verify", f"{expected_ref}^{{commit}}"
    )
    if resolved_ref != head:
        return f"workspace ref object changed independently of HEAD: {repo.get('id')}"
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if item.get("worktree")
            and _same_path(Path(item["worktree"]), path)
        ),
        None,
    )
    if (
        not entry
        or entry.get("branch") != expected_ref
        or entry.get("HEAD") != head
    ):
        return f"workspace is not registered as the approved linked worktree: {repo.get('id')}"
    return None


def _require_workspace_ready(state_value: dict[str, Any]) -> dict[str, Any]:
    approval, artifact = _require_gate_for_latest_artifact(
        state_value, "workspace", "workspace-plan"
    )
    current_generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    if (
        approval.get("artifact_id") != artifact.get("artifact_id")
        or approval.get("workspace_generation") != current_generation
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "workspace approval is not bound to the current plan record and generation",
        )
    repositories = state_value.get("repositories", [])
    required_ids = {repo["id"] for repo in repositories}
    try:
        evidence = json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_PLAN_INVALID",
            "approved workspace plan cannot be parsed",
            details={"path": artifact.get("path"), "error": str(exc)},
        ) from exc
    _require_current_evidence(evidence, "workspace plan")
    evidence_repositories = evidence.get("repositories", []) if isinstance(evidence, dict) else []
    evidence_ids = [item.get("repository_id") for item in evidence_repositories]
    if (
        evidence.get("task_id") != state_value.get("task_id")
        or evidence.get("workspace_generation")
        != int((state_value.get("workspace") or {}).get("generation", 0))
        or len(evidence_ids) != len(required_ids)
        or set(evidence_ids) != required_ids
    ):
        raise FlowError(
            "INCOMPLETE_WORKSPACE_PLAN",
            "approved workspace plan does not cover exactly every task repository",
            details={
                "required_repository_ids": sorted(required_ids),
                "planned_repository_ids": sorted(str(item) for item in evidence_ids),
            },
        )
    plans: list[dict[str, Any]] = []
    for repo in repositories:
        workspace = repo.get("workspace") or {}
        if not workspace.get("ready"):
            raise FlowError(
                "WORKSPACE_REQUIRED",
                f"repository has no ready workspace: {repo['id']}",
            )
        plans.append(
            {
                "evidence_contract_version": workspace.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "source_identity": workspace.get("source_identity"),
                "path": workspace.get("path"),
                "path_identity": workspace.get("path_identity"),
                "branch": workspace.get("branch"),
                "branch_ref": workspace.get("branch_ref"),
                "planned_ref_oid": workspace.get("planned_ref_oid"),
                "ref_case_sensitive": workspace.get("ref_case_sensitive"),
                "ref_unicode_normalization_distinct": workspace.get(
                    "ref_unicode_normalization_distinct"
                ),
                "source_common_dir": workspace.get("source_common_dir"),
                "source_common_dir_identity": workspace.get(
                    "source_common_dir_identity"
                ),
                "base_sha": workspace.get("base_sha"),
                "capability_profile_sha256": workspace.get(
                    "capability_profile_sha256"
                ),
                "source_capability_profile_sha256": workspace.get(
                    "source_capability_profile_sha256"
                ),
                "strategy": "worktree",
            }
        )
    current_evidence = _workspace_plan_evidence(state_value, plans)
    current_sha = _sha256_bytes(_json_bytes(current_evidence))
    if current_sha != artifact.get("sha256") or current_evidence != evidence:
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "ready workspaces no longer match the approved all-repository plan",
            details={
                "approved_sha256": artifact.get("sha256"),
                "current_sha256": current_sha,
            },
        )
    controller_workspace = state_value.get("workspace") or {}
    controller_plan = controller_workspace.get("plan") or {}
    if (
        not controller_workspace.get("ready")
        or controller_plan.get("artifact_id") != artifact.get("artifact_id")
        or controller_plan.get("path") != artifact.get("path")
        or controller_plan.get("sha256") != artifact.get("sha256")
        or controller_plan.get("workspace_generation")
        != int(controller_workspace.get("generation", 0))
    ):
        raise FlowError(
            "WORKSPACE_REQUIRED",
            "controller workspace readiness is not bound to the approved plan",
        )
    for repo in repositories:
        error = _workspace_integrity_error(state_value, repo)
        if error:
            raise FlowError(
                "WORKSPACE_INTEGRITY_FAILED",
                error,
                details={"repository_id": repo["id"]},
            )
    return approval


def _workspace_index_staleness(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    index: dict[str, Any],
) -> dict[str, Any] | None:
    repository_id = repo.get("id")
    try:
        _require_current_evidence(index, f"workspace-index:{repository_id}")
    except FlowError as exc:
        return {
            "repository_id": repository_id,
            "reason": exc.message,
        }
    if index.get("role") != "workspace" or not index.get("index_id"):
        return {
            "repository_id": repository_id,
            "reason": "workspace index role or project id is invalid",
        }
    if (index.get("metadata") or {}).get("persistence") is not False:
        return {
            "repository_id": repository_id,
            "reason": "workspace index does not explicitly disable persistence",
        }
    receipt = index.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, dict) or not receipt.get("path"):
            return {
                "repository_id": repository_id,
                "reason": "workspace index receipt metadata is incomplete",
            }
        try:
            _require_current_evidence(
                receipt, f"workspace-index-receipt:{repository_id}"
            )
        except FlowError as exc:
            return {
                "repository_id": repository_id,
                "reason": exc.message,
            }
        receipt_path = Path(str(receipt["path"]))
        try:
            actual_sha = (
                _sha256_file(receipt_path) if receipt_path.is_file() else None
            )
            actual_size = (
                receipt_path.stat().st_size if receipt_path.is_file() else None
            )
        except OSError:
            actual_sha = None
            actual_size = None
        if (
            actual_sha != receipt.get("sha256")
            or actual_size != receipt.get("size")
            or not _recorded_path_matches(
                receipt.get("path_identity"),
                receipt.get("path"),
                receipt_path,
            )
        ):
            return {
                "repository_id": repository_id,
                "reason": "workspace index receipt is missing or changed",
                "receipt_path": str(receipt_path),
                "expected_receipt_sha256": receipt.get("sha256"),
                "actual_receipt_sha256": actual_sha,
            }

    integrity_error = _workspace_integrity_error(state_value, repo)
    if integrity_error:
        return {
            "repository_id": repository_id,
            "reason": integrity_error,
        }
    workspace = repo.get("workspace") or {}
    workspace_path_value = workspace.get("path")
    recorded_path_value = index.get("repo_path")
    if not workspace_path_value or not recorded_path_value:
        return {
            "repository_id": repository_id,
            "reason": "workspace index path binding is incomplete",
        }
    workspace_path = Path(workspace_path_value).resolve(strict=False)
    recorded_path = Path(recorded_path_value).resolve(strict=False)
    if not _recorded_path_matches(
        index.get("repo_path_identity"),
        recorded_path_value,
        workspace_path,
    ):
        return {
            "repository_id": repository_id,
            "reason": "workspace index path identity changed",
        }
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    plan_sha = (
        (state_value.get("workspace") or {}).get("plan") or {}
    ).get("sha256")
    actual_branch = _git_optional(
        workspace_path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    actual_head = _git_optional(workspace_path, "rev-parse", "HEAD")
    bindings = {
        "workspace_generation": (
            index.get("workspace_generation"),
            generation,
        ),
        "workspace_plan_sha256": (
            index.get("workspace_plan_sha256"),
            plan_sha,
        ),
        "workspace_branch": (
            index.get("workspace_branch"),
            actual_branch,
        ),
        "commit_sha": (index.get("commit_sha"), actual_head),
        "workspace_head_sha": (
            index.get("workspace_head_sha"),
            actual_head,
        ),
    }
    mismatches = {
        name: {"recorded": recorded, "current": current}
        for name, (recorded, current) in bindings.items()
        if recorded != current
    }
    if mismatches:
        return {
            "repository_id": repository_id,
            "reason": "workspace identity, generation, branch or HEAD changed",
            "mismatches": mismatches,
        }
    try:
        fingerprint = _fingerprint_repo(workspace_path)
    except (FlowError, OSError) as exc:
        return {
            "repository_id": repository_id,
            "reason": f"workspace fingerprint cannot be verified: {exc}",
        }
    if fingerprint["capability_profile_sha256"] != index.get(
        "capability_profile_sha256"
    ):
        return {
            "repository_id": repository_id,
            "reason": "workspace capability profile changed after indexing",
            "recorded_capability_profile_sha256": index.get(
                "capability_profile_sha256"
            ),
            "current_capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
        }
    current_fingerprint = fingerprint["sha256"]
    if current_fingerprint != index.get("fingerprint_sha256"):
        return {
            "repository_id": repository_id,
            "reason": "workspace content changed after indexing",
            "recorded_fingerprint_sha256": index.get("fingerprint_sha256"),
            "current_fingerprint_sha256": current_fingerprint,
        }
    return None


def _require_current_workspace_indexes(
    state_value: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    missing = [
        repo.get("id")
        for repo in state_value.get("repositories", [])
        if not isinstance(repo.get("workspace_index"), dict)
        or not (repo.get("workspace_index") or {}).get("index_id")
    ]
    if missing:
        raise FlowError(
            "WORKSPACE_INDEX_REQUIRED",
            "every repository requires a recorded workspace index for the current implementation worktree",
            details={
                "repository_ids": missing,
                "selected_role": "workspace",
            },
        )
    stale: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {}
    for repo in state_value.get("repositories", []):
        index = repo["workspace_index"]
        records[repo["id"]] = index
        error = _workspace_index_staleness(state_value, repo, index)
        if error:
            stale.append(error)
    if stale:
        raise FlowError(
            "STALE_WORKSPACE_INDEX",
            "one or more workspace indexes no longer describe the current implementation worktree",
            details={"repositories": stale, "selected_role": "workspace"},
        )
    return records


def _current_planning_context(state_value: dict[str, Any]) -> dict[str, Any]:
    route_approval, impact = _require_route_gate(state_value)
    workspace_approval = _require_workspace_ready(state_value)
    workspace_plan = _latest_artifact(state_value, "workspace-plan")
    if not workspace_plan:
        raise FlowError("WORKSPACE_REQUIRED", "a current workspace plan is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "planning_generation": int(state_value.get("planning_generation", 0)),
        "impact_generation": int(state_value.get("impact_generation", 0)),
        "route": {
            "value": (state_value.get("route") or {}).get("value"),
            "approval_id": route_approval.get("approval_id"),
            "impact_artifact_id": impact.get("artifact_id"),
            "impact_sha256": impact.get("sha256"),
        },
        "workspace": {
            "generation": int(
                (state_value.get("workspace") or {}).get("generation", 0)
            ),
            "approval_id": workspace_approval.get("approval_id"),
            "plan_artifact_id": workspace_plan.get("artifact_id"),
            "plan_sha256": workspace_plan.get("sha256"),
        },
    }


def _planning_context_sha256(context: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(context))


def _assert_openspec_plan_in_current_workspace(
    state_value: dict[str, Any], artifact_path: Path
) -> None:
    resolved = artifact_path.resolve(strict=True)
    if not any(
        (repo.get("workspace") or {}).get("ready")
        and _is_within(
            resolved,
            Path((repo.get("workspace") or {})["path"]).resolve(strict=True),
        )
        for repo in state_value.get("repositories", [])
    ):
        raise FlowError(
            "OPENSPEC_PLAN_OUTSIDE_WORKSPACE",
            "openspec-plan must be recorded from a current ready implementation workspace",
            details={"path": str(resolved)},
        )


def _require_current_plan_artifact(
    state_value: dict[str, Any], artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _latest_artifact(state_value, artifact_kind)
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            f"the plan gate requires a recorded {artifact_kind} artifact",
        )
    _assert_artifact_unchanged(artifact)
    if artifact_kind == "openspec-plan":
        _assert_openspec_plan_in_current_workspace(
            state_value, Path(artifact["path"])
        )
    expected_context = _current_planning_context(state_value)
    metadata = artifact.get("metadata") or {}
    recorded_context = metadata.get("planning_context")
    recorded_context_sha = metadata.get("planning_context_sha256")
    expected_context_sha = _planning_context_sha256(expected_context)
    if (
        recorded_context != expected_context
        or recorded_context_sha != expected_context_sha
    ):
        raise FlowError(
            "STALE_PLAN",
            "latest plan artifact is not bound to the current planning epoch, route and workspace",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "expected_planning_context_sha256": expected_context_sha,
                "recorded_planning_context_sha256": recorded_context_sha,
            },
        )
    return artifact, expected_context


def _require_current_plan_gate(
    state_value: dict[str, Any], artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact, context = _require_current_plan_artifact(state_value, artifact_kind)
    approval = _require_gate(state_value, "plan")
    context_sha = _planning_context_sha256(context)
    if (
        approval.get("artifact_sha256") != artifact.get("sha256")
        or approval.get("artifact_id") != artifact.get("artifact_id")
        or approval.get("planning_context_sha256") != context_sha
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "plan approval is not bound to the current plan record and planning context",
        )
    return approval, artifact


def command_prepare_workspace(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    data_root = resolve_data_dir(args.data_dir)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        lock_workspace_registry=True,
    ) as (task_dir, current):
        _assert_flow(current, "full", "prepare-workspace")
        _assert_status(current, {"ROUTE_APPROVED", "WORKSPACE_READY"}, "prepare-workspace")
        selected_current = _repo_by_selector(current, args.repo)
        configured_ids = {repo["id"] for repo in current.get("repositories", [])}
        selected_ids = {repo["id"] for repo in selected_current}
        if selected_ids != configured_ids:
            raise FlowError(
                "INCOMPLETE_WORKSPACE_PLAN",
                "workspace plans must cover every repository in the task",
                details={
                    "required_repository_ids": sorted(configured_ids),
                    "selected_repository_ids": sorted(selected_ids),
                },
            )
        _require_route_gate(current)
        path_overrides = _parse_workspace_overrides(
            current,
            args.workspace_path,
            "--workspace-path",
            require_absolute_path=True,
        )
        branch_overrides = _parse_workspace_overrides(
            current,
            args.workspace_branch,
            "--workspace-branch",
            require_absolute_path=False,
        )
        if args.path and path_overrides:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--path cannot be combined with --workspace-path",
            )
        plans = _workspace_plan(
            current,
            selected_current,
            data_root,
            args.branch,
            args.path,
            branch_overrides,
            path_overrides,
        )
        evidence = _workspace_plan_evidence(current, plans)
        evidence_bytes = _json_bytes(evidence)
        evidence_sha = _sha256_bytes(evidence_bytes)
        if current.get("status") == "WORKSPACE_READY":
            ready_plan = (current.get("workspace") or {}).get("plan") or {}
            if ready_plan.get("sha256") != evidence_sha:
                raise FlowError(
                    "WORKSPACE_REASSESSMENT_REQUIRED",
                    "a ready workspace cannot be replaced within the same generation",
                    details={
                        "workspace_generation": evidence["workspace_generation"],
                        "ready_plan_sha256": ready_plan.get("sha256"),
                        "requested_plan_sha256": evidence_sha,
                    },
                )
        if not args.execute:
            _claim_workspace_plan(
                data_root,
                current,
                evidence_sha,
                plans,
                registry_locked=True,
            )
            plan_path = task_dir / "workspace-plans" / f"{evidence_sha}.json"
            latest_plan = _latest_artifact(current, "workspace-plan")
            current_workspace_plan = (current.get("workspace") or {}).get("plan") or {}
            if (
                latest_plan
                and latest_plan.get("sha256") == evidence_sha
                and current_workspace_plan.get("sha256") == evidence_sha
                and current_workspace_plan.get("artifact_id")
                == latest_plan.get("artifact_id")
                and current_workspace_plan.get("path")
                == latest_plan.get("path")
                and current_workspace_plan.get("workspace_generation")
                == evidence["workspace_generation"]
                and (latest_plan.get("metadata") or {}).get(
                    "workspace_generation"
                )
                == evidence["workspace_generation"]
            ):
                try:
                    _assert_artifact_unchanged(latest_plan)
                except FlowError:
                    _atomic_write_bytes(plan_path, evidence_bytes)
                else:
                    return _result(
                        "prepare-workspace",
                        current,
                        dry_run=True,
                        unchanged=True,
                        plans=plans,
                        plan_artifact=latest_plan,
                    )
            _atomic_write_bytes(plan_path, evidence_bytes)
            state_value = _copy_state(current)
            plan_artifact = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "artifact_id": str(uuid.uuid4()),
                "kind": "workspace-plan",
                "path": str(plan_path),
                "path_identity": _serializable_path_identity(plan_path),
                "sha256": evidence_sha,
                "artifact_type": "file",
                "size": len(evidence_bytes),
                "file_count": 1,
                "total_size": len(evidence_bytes),
                "recorded_at": utc_now(),
                "metadata": {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "repository_ids": [item["repository_id"] for item in evidence["repositories"]],
                    "workspace_generation": evidence["workspace_generation"],
                    "capability_profile_sha256": {
                        item["repository_id"]: item[
                            "capability_profile_sha256"
                        ]
                        for item in evidence["repositories"]
                    },
                },
            }
            state_value["artifacts"].append(plan_artifact)
            workspace_state = dict(state_value.get("workspace") or {})
            workspace_state["strategy"] = "worktree"
            workspace_state["plan"] = {
                "artifact_id": plan_artifact["artifact_id"],
                "sha256": evidence_sha,
                "path": str(plan_path),
                "repository_ids": plan_artifact["metadata"]["repository_ids"],
                "recorded_at": plan_artifact["recorded_at"],
                "workspace_generation": evidence["workspace_generation"],
            }
            state_value["workspace"] = workspace_state
            state_value["approvals"].pop("workspace", None)
            _commit_state(
                current,
                state_value,
                task_dir,
                "workspace_plan_recorded",
                {
                    "sha256": evidence_sha,
                    "repository_ids": plan_artifact["metadata"]["repository_ids"],
                },
            )
            return _result(
                "prepare-workspace",
                state_value,
                dry_run=True,
                plans=plans,
                plan_artifact=plan_artifact,
            )
        workspace_approval, approved_plan = _require_gate_for_latest_artifact(
            current, "workspace", "workspace-plan"
        )
        controller_plan = (current.get("workspace") or {}).get("plan") or {}
        if (
            workspace_approval.get("artifact_id")
            != approved_plan.get("artifact_id")
            or controller_plan.get("artifact_id")
            != approved_plan.get("artifact_id")
            or controller_plan.get("path") != approved_plan.get("path")
            or controller_plan.get("sha256") != approved_plan.get("sha256")
        ):
            raise FlowError(
                "STALE_WORKSPACE_PLAN",
                "workspace approval and controller state are not bound to the latest plan record",
            )
        if evidence_sha != approved_plan.get("sha256"):
            raise FlowError(
                "WORKSPACE_PLAN_MISMATCH",
                "execute arguments do not match the approved workspace plan",
                details={
                    "approved_sha256": approved_plan.get("sha256"),
                    "requested_sha256": evidence_sha,
                    "approved_path": approved_plan.get("path"),
                },
            )
        approved_generation = (approved_plan.get("metadata") or {}).get(
            "workspace_generation"
        )
        if approved_generation != evidence["workspace_generation"]:
            raise FlowError(
                "WORKSPACE_PLAN_MISMATCH",
                "approved workspace plan belongs to a different workspace generation",
                details={
                    "approved_workspace_generation": approved_generation,
                    "current_workspace_generation": evidence["workspace_generation"],
                },
            )
        _claim_workspace_plan(
            data_root,
            current,
            evidence_sha,
            plans,
            registry_locked=True,
        )
        state_value = _copy_state(current)
        by_id = {repo["id"]: repo for repo in state_value["repositories"]}
        source_fingerprints = {
            repo["id"]: _fingerprint_repo(Path(repo["path"]))["sha256"]
            for repo in state_value["repositories"]
        }
        outcomes: list[dict[str, Any]] = []
        for plan in plans:
            outcome = _execute_worktree(plan)
            outcomes.append(outcome)
            repository = by_id[plan["repository_id"]]
            previous_workspace = repository.get("workspace") or {}
            same_workspace = (
                previous_workspace.get("ready")
                and previous_workspace.get("path") == outcome.get("path")
                and previous_workspace.get("branch") == outcome.get("branch")
                and previous_workspace.get("workspace_generation")
                == outcome.get("workspace_generation")
            )
            if not same_workspace:
                repository["workspace_index"] = None
            repository["workspace"] = outcome
        for outcome in outcomes:
            if not (
                outcome.get("created") or outcome.get("recovered_unrecorded")
            ):
                continue
            status_available, status_porcelain = _status_porcelain(
                Path(outcome["path"])
            )
            if not status_available or status_porcelain:
                raise FlowError(
                    "WORKSPACE_VERIFY_FAILED",
                    "a newly prepared workspace changed before atomic state commit",
                    details={
                        "repository_id": outcome["repository_id"],
                        "path": outcome["path"],
                        "status_porcelain": status_porcelain,
                    },
                )
        for repo in state_value["repositories"]:
            current_source = _fingerprint_repo(Path(repo["path"]))["sha256"]
            if current_source != source_fingerprints[repo["id"]]:
                raise FlowError(
                    "SOURCE_WORKTREE_CHANGED",
                    "source checkout changed while preparing implementation workspaces",
                    details={"repository_id": repo["id"]},
                )
        all_ready = all((repo.get("workspace") or {}).get("ready") for repo in state_value["repositories"])
        workspace_state = dict(state_value.get("workspace") or {})
        workspace_state.update(
            {
                "strategy": "worktree",
                "ready": all_ready,
                "prepared_at": utc_now() if all_ready else None,
            }
        )
        state_value["workspace"] = workspace_state
        if all_ready:
            _require_workspace_ready(state_value)
            state_value["status"] = "WORKSPACE_READY"
        _commit_state(current, state_value, task_dir, "workspace_prepared", {"repository_ids": [item["repository_id"] for item in outcomes], "complete": all_ready})
    return _result("prepare-workspace", state_value, dry_run=False, complete=all_ready, workspaces=outcomes)


def _test_identity(name: Any, command: Any) -> str:
    return _sha256_bytes(
        _json_bytes({"name": str(name or ""), "command": str(command or "")})
    )


def command_record_test(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    output_record: dict[str, Any] | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve(strict=True)
        output_record = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(output_path),
            "path_identity": _serializable_path_identity(output_path),
            "sha256": _sha256_file(output_path),
            "size": output_path.stat().st_size,
        }
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_status(current, {"IMPLEMENTING", "VERIFYING"}, "record-test")
        if _flow(current) == "lite":
            # Lite tests bind the lite approval instead of a plan artifact:
            # re-approving the gate invalidates older results the same way a
            # plan reapproval does on the full flow.
            lite_approval = _require_lite_gate(current)
            binding = {
                "lite_approval_id": lite_approval["approval_id"],
                "lite_approved_at": lite_approval["approved_at"],
            }
        else:
            _require_workspace_ready(current)
            route_value = (current.get("route") or {}).get("value")
            plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
            plan_approval, plan_artifact = _require_current_plan_gate(
                current, plan_kind
            )
            binding = {
                "plan_artifact_sha256": plan_artifact["sha256"],
                "plan_approved_at": plan_approval["approved_at"],
                "plan_approval_id": plan_approval["approval_id"],
            }
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        fingerprints = {repo["id"]: _fingerprint_repo(_working_path(repo)) for repo in selected}
        test_record = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "test_id": str(uuid.uuid4()),
            "name": args.name,
            "command": args.test_command,
            "test_identity": _test_identity(args.name, args.test_command),
            "exit_code": args.exit_code,
            "passed": args.exit_code == 0,
            "recorded_at": utc_now(),
            "repository_ids": [repo["id"] for repo in selected],
            "fingerprints": fingerprints,
            "capability_profile_sha256": {
                repository_id: fingerprint[
                    "capability_profile_sha256"
                ]
                for repository_id, fingerprint in fingerprints.items()
            },
            **binding,
            "output": output_record,
        }
        state_value["tests"].append(test_record)
        _commit_state(current, state_value, task_dir, "test_recorded", {"test_id": test_record["test_id"], "passed": test_record["passed"], "repository_ids": test_record["repository_ids"]})
    return _result("record-test", state_value, test=test_record)


def _write_review_repo(snapshot_root: Path, repo: dict[str, Any]) -> dict[str, Any]:
    working = _working_path(repo)
    _assert_evidence_supported(working)
    base_sha = (repo.get("baseline") or {}).get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")

    def capture_sections() -> tuple[
        str, dict[str, bytes], dict[str, list[str]]
    ]:
        captured_head = _git_evidence(working, "rev-parse", "HEAD")
        captured_sections = {
            "committed": _git_diff(
                working,
                "--binary",
                "--full-index",
                f"{base_sha}...HEAD",
                "--",
                text=False,
            ),
            "cached": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--cached",
                "--",
                text=False,
            ),
            "unstaged": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--",
                text=False,
            ),
        }
        captured_files = {
            "committed": _split_lines(
                _git_diff(
                    working,
                    "--name-status",
                    f"{base_sha}...HEAD",
                    "--",
                )
            ),
            "cached": _split_lines(
                _git_diff(
                    working, "--cached", "--name-status", "--"
                )
            ),
            "unstaged": _split_lines(
                _git_diff(working, "--name-status", "--")
            ),
        }
        return captured_head, captured_sections, captured_files

    fingerprint = _fingerprint_repo(working)
    repo_dir = snapshot_root / repo["id"]
    _ensure_private_dir(repo_dir)
    head_sha, sections, section_files = capture_sections()
    if head_sha != fingerprint.get("head_sha"):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository HEAD changed before review sections were captured",
            details={
                "repository_id": repo["id"],
                "fingerprint_head": fingerprint.get("head_sha"),
                "section_head": head_sha,
            },
        )
    section_records: dict[str, Any] = {}
    for name, content in sections.items():
        path = repo_dir / f"{name}.patch"
        _atomic_write_bytes(path, content)
        section_records[name] = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(path),
            "path_identity": _serializable_path_identity(path),
            "sha256": _sha256_bytes(content),
            "size": len(content),
            "files": section_files[name],
            "range": f"{base_sha}...{head_sha}" if name == "committed" else None,
        }
    untracked_manifest_path = repo_dir / "untracked.json"
    _atomic_write_json(untracked_manifest_path, fingerprint["untracked"])
    tar_path = repo_dir / "untracked.tar"
    with tarfile.open(tar_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for item in fingerprint["untracked"]:
            relative = _untracked_filesystem_path(item)
            archive.add(working / relative, arcname=relative, recursive=False)
    _set_private_permissions(tar_path, 0o600)
    # Windows requires a writable descriptor for fsync; no bytes are changed.
    with tar_path.open("rb+") as archive_handle:
        os.fsync(archive_handle.fileno())
    _validate_untracked_archive(tar_path, fingerprint["untracked"])
    middle_fingerprint = _fingerprint_repo(working)
    verify_head, verify_sections, verify_files = capture_sections()
    final_fingerprint = _fingerprint_repo(working)
    if (
        fingerprint.get("sha256") != middle_fingerprint.get("sha256")
        or fingerprint.get("sha256") != final_fingerprint.get("sha256")
        or verify_head != head_sha
        or verify_sections != sections
        or verify_files != section_files
    ):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository changed while the complete review snapshot was being built",
            details={
                "repository_id": repo["id"],
                "before_sha256": fingerprint.get("sha256"),
                "middle_sha256": middle_fingerprint.get("sha256"),
                "after_sha256": final_fingerprint.get("sha256"),
                "before_head": head_sha,
                "after_head": verify_head,
            },
        )
    section_records["untracked"] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "manifest_path": str(untracked_manifest_path),
        "manifest_path_identity": _serializable_path_identity(
            untracked_manifest_path
        ),
        "manifest_sha256": _sha256_file(untracked_manifest_path),
        "archive_path": str(tar_path),
        "archive_path_identity": _serializable_path_identity(tar_path),
        "archive_sha256": _sha256_file(tar_path),
        "size": tar_path.stat().st_size,
        "files": fingerprint["untracked"],
    }
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "repository_id": repo["id"],
        "working_path": str(working),
        "working_path_identity": _serializable_path_identity(working),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "capability_profile_sha256": fingerprint[
            "capability_profile_sha256"
        ],
        "tracked_worktree_manifest_sha256": fingerprint[
            "tracked_worktree_manifest_sha256"
        ],
        "fingerprint": fingerprint,
        "sections": section_records,
    }


def _latest_passing_test_is_current(state_value: dict[str, Any]) -> tuple[bool, str | None]:
    """Require each repo's newest relevant test record to pass and remain current."""

    if _flow(state_value) == "lite":
        lite_approval = _require_lite_gate(state_value)

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return test.get("lite_approval_id") == lite_approval.get(
                "approval_id"
            ) and str(test.get("recorded_at", "")) >= str(
                lite_approval.get("approved_at", "")
            )

        missing_message = "no test result for the current lite approval covers repository"
    else:
        route_value = (state_value.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        plan_approval, plan_artifact = _require_current_plan_gate(
            state_value, plan_kind
        )

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return (
                test.get("plan_artifact_sha256") == plan_artifact.get("sha256")
                and test.get("plan_approval_id")
                == plan_approval.get("approval_id")
                and str(test.get("recorded_at", ""))
                >= str(plan_approval.get("approved_at", ""))
            )

        missing_message = "no test result for the current plan approval covers repository"
    tests = state_value.get("tests", [])
    for repo in state_value["repositories"]:
        latest_by_identity: dict[str, dict[str, Any]] = {}
        for test in tests:
            if repo["id"] not in test.get("repository_ids", []):
                continue
            if not _bound_to_current_approval(test):
                continue
            identity = test.get("test_identity") or _test_identity(
                test.get("name"), test.get("command")
            )
            latest_by_identity[identity] = test
        if not latest_by_identity:
            return (
                False,
                f"{missing_message}: {repo['id']}",
            )
        current = _fingerprint_repo(_working_path(repo))
        for latest in latest_by_identity.values():
            label = latest.get("name") or latest.get("test_identity") or "unnamed"
            try:
                _require_current_evidence(latest, f"test:{label}")
            except FlowError as exc:
                return False, exc.message
            if not latest.get("passed"):
                return (
                    False,
                    f"latest result for test identity {label!r} failed for repository: {repo['id']}",
                )
            output = latest.get("output")
            if output is not None:
                try:
                    _require_current_evidence(
                        output, f"test-output:{label}"
                    )
                except FlowError as exc:
                    return False, exc.message
                output_path = Path(str((output or {}).get("path", "")))
                try:
                    output_sha = (
                        _sha256_file(output_path)
                        if output_path.is_file()
                        else None
                    )
                    output_size = (
                        output_path.stat().st_size
                        if output_path.is_file()
                        else None
                    )
                except OSError:
                    output_sha = None
                    output_size = None
                if (
                    output_sha != (output or {}).get("sha256")
                    or output_size != (output or {}).get("size")
                    or not _recorded_path_matches(
                        (output or {}).get("path_identity"),
                        (output or {}).get("path"),
                        output_path,
                    )
                ):
                    return (
                        False,
                        f"test output for identity {label!r} is missing or changed: {output_path}",
                    )
            recorded = latest.get("fingerprints", {}).get(repo["id"], {})
            try:
                _require_current_evidence(
                    recorded, f"test-fingerprint:{label}:{repo['id']}"
                )
            except FlowError as exc:
                return False, exc.message
            if current.get("sha256") != recorded.get("sha256"):
                return (
                    False,
                    f"repository changed after test identity {label!r} passed: {repo['id']}",
                )
            recorded_profiles = latest.get(
                "capability_profile_sha256", {}
            )
            if (
                current.get("capability_profile_sha256")
                != recorded_profiles.get(repo["id"])
            ):
                return (
                    False,
                    f"repository capability profile changed after test identity {label!r}: {repo['id']}",
                )
    return True, None


def command_review_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "review-snapshot")
        _assert_status(current, {"VERIFYING", "REVIEWING"}, "review-snapshot")
        _require_current_workspace_indexes(current)
        _require_workspace_ready(current)
        route_value = (current.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(current, plan_kind)
        passing, reason = _latest_passing_test_is_current(current)
        if not passing:
            raise FlowError("CURRENT_TEST_REQUIRED", reason or "a current passing test is required")
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        if len(selected) != len(state_value["repositories"]):
            raise FlowError("INCOMPLETE_REVIEW", "review-snapshot must include every configured repository")
        snapshot_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        snapshot_root = task_dir / "reviews" / snapshot_id
        try:
            repositories = [
                _write_review_repo(snapshot_root, repo)
                for repo in selected
            ]
            for repository in repositories:
                current_fingerprint = _fingerprint_repo(
                    Path(repository["working_path"])
                )
                recorded_fingerprint = repository.get(
                    "fingerprint"
                ) or {}
                if current_fingerprint.get(
                    "sha256"
                ) != recorded_fingerprint.get("sha256"):
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        (
                            "a repository changed after its section of the "
                            "multi-repository snapshot was captured"
                        ),
                        details={
                            "repository_id": repository[
                                "repository_id"
                            ],
                            "recorded_sha256": recorded_fingerprint.get(
                                "sha256"
                            ),
                            "current_sha256": current_fingerprint.get(
                                "sha256"
                            ),
                        },
                    )
            snapshot = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": utc_now(),
                "repository_ids": [repo["id"] for repo in selected],
                "repositories": repositories,
            }
            manifest_path = snapshot_root / "manifest.json"
            _atomic_write_json(manifest_path, snapshot)
            snapshot["manifest_path"] = str(manifest_path)
            snapshot["manifest_path_identity"] = (
                _serializable_path_identity(manifest_path)
            )
            snapshot["sha256"] = _sha256_file(manifest_path)
            integrity_error = _review_snapshot_integrity_error(
                snapshot
            )
            if integrity_error:
                raise FlowError(
                    "REVIEW_SNAPSHOT_INVALID",
                    integrity_error,
                    details={"snapshot_id": snapshot_id},
                )
        except BaseException as exc:
            if snapshot_root.exists():
                try:
                    shutil.rmtree(snapshot_root)
                except OSError as cleanup_error:
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CLEANUP_FAILED",
                        (
                            "an incomplete review snapshot could not be "
                            "removed and was not recorded as usable"
                        ),
                        details={
                            "snapshot_root": str(snapshot_root),
                            "error": str(cleanup_error),
                            "cause": f"{type(exc).__name__}: {exc}",
                        },
                    ) from cleanup_error
            raise
        state_value["review_snapshots"].append(snapshot)
        state_value["artifacts"].append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "artifact_id": str(uuid.uuid4()),
                "kind": "review-snapshot",
                "path": str(manifest_path),
                "path_identity": _serializable_path_identity(manifest_path),
                "sha256": snapshot["sha256"],
                "size": manifest_path.stat().st_size,
                "recorded_at": utc_now(),
                "metadata": {
                    "snapshot_id": snapshot_id,
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "capability_profile_sha256": {
                        item["repository_id"]: item[
                            "capability_profile_sha256"
                        ]
                        for item in repositories
                    },
                },
            }
        )
        state_value["status"] = "REVIEWING"
        _commit_state(current, state_value, task_dir, "review_snapshot_recorded", {"snapshot_id": snapshot_id, "sha256": snapshot["sha256"], "repository_ids": snapshot["repository_ids"]})
    return _result("review-snapshot", state_value, snapshot=snapshot)


def _snapshot_file_error(
    path_value: Any,
    expected_sha: Any,
    label: str,
    path_identity: Any = None,
) -> str | None:
    if not isinstance(path_value, str) or not path_value or not isinstance(expected_sha, str):
        return f"review snapshot has incomplete {label} integrity metadata"
    path = Path(path_value)
    if not _recorded_path_matches(path_identity, path_value, path):
        return f"review snapshot {label} path identity changed: {path}"
    if not path.is_file():
        return f"review snapshot {label} file is missing: {path}"
    try:
        current_sha = _sha256_file(path)
    except OSError as exc:
        return f"review snapshot {label} file is unreadable: {path}: {exc}"
    if current_sha != expected_sha:
        return f"review snapshot {label} file changed: {path}"
    return None


def _review_snapshot_integrity_error(snapshot: dict[str, Any]) -> str | None:
    try:
        _require_current_evidence(snapshot, "review snapshot")
    except FlowError as exc:
        return exc.message
    error = _snapshot_file_error(
        snapshot.get("manifest_path"),
        snapshot.get("sha256"),
        "manifest",
        snapshot.get("manifest_path_identity"),
    )
    if error:
        return error
    for repository in snapshot.get("repositories", []):
        repository_id = repository.get("repository_id", "unknown")
        try:
            _require_current_evidence(
                repository, f"review-repository:{repository_id}"
            )
            _require_current_evidence(
                repository.get("fingerprint"),
                f"review-fingerprint:{repository_id}",
            )
        except FlowError as exc:
            return exc.message
        sections = repository.get("sections") or {}
        for section_name in ("committed", "cached", "unstaged"):
            section = sections.get(section_name) or {}
            error = _snapshot_file_error(
                section.get("path"),
                section.get("sha256"),
                f"{repository_id}/{section_name}",
                section.get("path_identity"),
            )
            if error:
                return error
        untracked = sections.get("untracked") or {}
        error = _snapshot_file_error(
            untracked.get("manifest_path"),
            untracked.get("manifest_sha256"),
            f"{repository_id}/untracked-manifest",
            untracked.get("manifest_path_identity"),
        )
        if error:
            return error
        error = _snapshot_file_error(
            untracked.get("archive_path"),
            untracked.get("archive_sha256"),
            f"{repository_id}/untracked-archive",
            untracked.get("archive_path_identity"),
        )
        if error:
            return error
    return None


def _review_is_current(state_value: dict[str, Any]) -> tuple[bool, str | None]:
    snapshots = state_value.get("review_snapshots", [])
    if not snapshots:
        return False, "no review snapshot has been recorded"
    latest = snapshots[-1]
    integrity_error = _review_snapshot_integrity_error(latest)
    if integrity_error:
        return False, integrity_error
    by_id = {item["repository_id"]: item for item in latest.get("repositories", [])}
    for repo in state_value["repositories"]:
        workspace_error = _workspace_integrity_error(state_value, repo)
        if workspace_error:
            return False, workspace_error
        recorded = by_id.get(repo["id"])
        if not recorded:
            return False, f"review snapshot does not cover repository: {repo['id']}"
        current = _fingerprint_repo(_working_path(repo))
        if current.get("sha256") != (recorded.get("fingerprint") or {}).get("sha256"):
            return False, f"repository changed after review snapshot: {repo['id']}"
        if current.get("capability_profile_sha256") != recorded.get(
            "capability_profile_sha256"
        ):
            return False, f"repository capability profile changed after review snapshot: {repo['id']}"
    return True, None


def _lite_transition_guard(state_value: dict[str, Any], target: str) -> None:
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
    if target == "IMPLEMENTING":
        # Entering implementation from PREFLIGHTED must find the exact approved
        # checkouts untouched; re-entering from rework legitimately finds the
        # tree already edited, so only branch identity is revalidated there.
        _require_lite_gate(
            state_value,
            verify_worktree=state_value.get("status") == "PREFLIGHTED",
        )
    if target in {"VERIFYING", "DONE"}:
        _require_lite_gate(state_value)
    if target == "DONE":
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")


def _transition_guard(state_value: dict[str, Any], target: str) -> None:
    if _flow(state_value) == "lite":
        _lite_transition_guard(state_value, target)
        return
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
    if target == "BASELINED":
        if not all(repo.get("baseline") for repo in repositories):
            raise FlowError(
                "BASELINE_REQUIRED",
                "all repositories must have a pinned baseline",
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("baseline"), f"baseline:{repo.get('id')}"
            )
    if target in {"INDEXED", "IMPACT_REVIEW"}:
        if not all(repo.get("index") for repo in repositories):
            raise FlowError(
                "INDEX_REQUIRED",
                "all repositories must have a recorded index",
            )
        _index_provenance_evidence(state_value)
    if target == "ROUTE_APPROVED":
        _require_route_gate(state_value)
    if target in {"PLANNING", "IMPLEMENTING", "VERIFYING"}:
        _require_current_workspace_indexes(state_value)
    if target in {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        _require_route_gate(state_value)
        _require_workspace_ready(state_value)
    if target in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        route_value = (state_value.get("route") or {}).get("value")
        artifact_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(state_value, artifact_kind)
    if target == "REVIEWING":
        current, reason = _review_is_current(state_value)
        if not current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", reason or "a current review snapshot is required")
    if target in {"FINALIZING", "DONE"}:
        review_current, review_reason = _review_is_current(state_value)
        if not review_current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", review_reason or "a current review snapshot is required")
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")
        _require_review_gate(state_value)
    if target == "DONE":
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")


def command_transition(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    target = args.to_option or args.to
    if target not in ALL_STATES:
        raise FlowError("INVALID_ARGUMENT", f"unknown target state: {target}", details={"allowed": sorted(ALL_STATES)})
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        source = current["status"]
        if source == target:
            return _result("transition", current, unchanged=True, transition={"from": source, "to": target})
        if source in TERMINAL_STATES:
            raise FlowError("INVALID_TRANSITION", f"terminal task cannot transition from {source}")
        if (
            target == "PREFLIGHTED"
            and (
                source == "INTAKE"
                or (
                    source == "BLOCKED"
                    and (current.get("blocked") or {}).get("phase")
                    == "preflight"
                )
            )
        ):
            raise FlowError(
                "PREFLIGHT_CONFIRMATION_REQUIRED",
                (
                    "initial and preflight-blocked transitions to "
                    "PREFLIGHTED require an all-repository "
                    "preflight --preview/--confirm-preview pair"
                ),
                details={"from": source, "to": target},
            )
        if target == "CANCELLED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to CANCELLED requires --note; cancel is preferred")
        elif target == "BLOCKED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to BLOCKED requires --note")
        elif source == "BLOCKED":
            expected = (current.get("blocked") or {}).get("from_status")
            if target != expected:
                raise FlowError("INVALID_TRANSITION", f"blocked task can only resume to {expected}", details={"from": source, "to": target, "allowed": [expected]})
        else:
            lite = _flow(current) == "lite"
            forward_edges = LITE_FORWARD_EDGES if lite else FORWARD_EDGES
            rework_edges = LITE_REWORK_EDGES if lite else REWORK_EDGES
            allowed = set(forward_edges.get(source, set())) | set(rework_edges.get(source, set()))
            if target not in allowed:
                raise FlowError("INVALID_TRANSITION", f"transition {source} -> {target} is not allowed", details={"from": source, "to": target, "allowed": sorted(allowed | {"BLOCKED", "CANCELLED"})})
            if (
                target == "PLANNING"
                and source in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "replanning requires --note",
                    details={"from": source, "to": target},
                )
            if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES and not args.note:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "impact reassessment requires --note",
                    details={"from": source, "to": target},
                )
            if (
                lite
                and target == "PREFLIGHTED"
                and source in {"IMPLEMENTING", "VERIFYING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "reopening lite scope evidence requires --note",
                    details={"from": source, "to": target},
                )
        _transition_guard(current, target)
        state_value = _copy_state(current)
        state_value["status"] = target
        if target == "PLANNING" and source != "BLOCKED":
            state_value["planning_generation"] = int(
                current.get("planning_generation", 0)
            ) + 1
        if target == "BLOCKED":
            state_value["blocked"] = {"phase": "manual", "from_status": source, "reason": args.note, "details": [], "at": utc_now()}
        elif source == "BLOCKED":
            state_value["blocked"] = None
        if target == "CANCELLED":
            state_value["cancelled"] = {"reason": args.note, "at": utc_now(), "by": _actor()}
        if target == "IMPLEMENTING" and source in {"VERIFYING", "REVIEWING", "FINALIZING"}:
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("review", None)
        if target == "PLANNING" and source != "BLOCKED":
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("plan", None)
            state_value["approvals"].pop("review", None)
        if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES:
            state_value["impact_generation"] = int(
                current.get("impact_generation", 0)
            ) + 1
            state_value["route"] = None
            for gate in ("route", "workspace", "plan", "review"):
                state_value["approvals"].pop(gate, None)
            state_value["review_snapshots"] = []
            reassessed_at = utc_now()
            for repo in state_value.get("repositories", []):
                previous_workspace = repo.get("workspace")
                if previous_workspace:
                    history = repo.setdefault("workspace_history", [])
                    history.append(
                        {
                            **previous_workspace,
                            "workspace_index": repo.get("workspace_index"),
                            "retired_at": reassessed_at,
                            "retired_reason": args.note,
                        }
                    )
                repo["workspace"] = None
                repo["workspace_index"] = None
            previous_generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            state_value["workspace"] = {
                "strategy": "worktree",
                "ready": False,
                "generation": previous_generation + 1,
                "plan": None,
                "reassessed_at": reassessed_at,
            }
        _commit_state(current, state_value, task_dir, "state_transitioned", {"from": source, "to": target, "note": args.note})
    return _result("transition", state_value, transition={"from": source, "to": target, "note": args.note})


def command_cancel(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        if current.get("status") == "CANCELLED":
            return _result("cancel", current, unchanged=True, cancelled=current.get("cancelled"))
        if current.get("status") == "DONE":
            raise FlowError("INVALID_STATE", "completed task cannot be cancelled")
        state_value = _copy_state(current)
        source = state_value["status"]
        state_value["status"] = "CANCELLED"
        state_value["cancelled"] = {"reason": args.reason, "at": utc_now(), "by": _actor(), "from_status": source}
        _commit_state(current, state_value, task_dir, "task_cancelled", {"from": source, "reason": args.reason})
    return _result("cancel", state_value, cancelled=state_value["cancelled"])


def _parse_json_object(value: str | None, option: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise FlowError("INVALID_ARGUMENT", f"{option} is not valid JSON", details={"error": str(exc)}) from exc
    if not isinstance(parsed, dict):
        raise FlowError("INVALID_ARGUMENT", f"{option} must contain a JSON object")
    stack: list[tuple[str, Any]] = [("$", parsed)]
    while stack:
        location, candidate = stack.pop()
        if isinstance(candidate, dict):
            if "evidence_contract_version" in candidate:
                raise FlowError(
                    "RESERVED_METADATA_KEY",
                    (
                        f"{option} must not contain the controller-reserved "
                        "evidence_contract_version key"
                    ),
                    details={
                        "option": option,
                        "location": location,
                        "key": "evidence_contract_version",
                    },
                )
            stack.extend(
                (f"{location}.{key}", nested)
                for key, nested in candidate.items()
            )
        elif isinstance(candidate, list):
            stack.extend(
                (f"{location}[{index}]", nested)
                for index, nested in enumerate(candidate)
            )
    return parsed


def _task_arg(args: argparse.Namespace) -> str:
    task_id = getattr(args, "task_option", None) or getattr(args, "task_id", None)
    if not task_id:
        raise FlowError("INVALID_ARGUMENT", "task id is required (positional or --task)")
    return _validate_task_id(task_id)


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="state directory (overrides DEV_FLOW_DATA_DIR and PLUGIN_DATA)",
    )


def _add_task(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", nargs="?", help="task id")
    parser.add_argument("--task", dest="task_option", help="task id (alternative to positional form)")


def _add_mutation(parser: argparse.ArgumentParser) -> None:
    _add_task(parser)
    parser.add_argument(
        "--expected-revision",
        type=int,
        required=True,
        help="current state revision; stale writers fail with REVISION_CONFLICT",
    )
    _add_data_dir(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="dev_flow.py",
        description="Deterministic Codex + OpenSpec + codebase-memory development-flow control plane.",
    )
    parser.add_argument("--data-dir", help="state directory (may also follow a subcommand)")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    start = subparsers.add_parser(
        "start",
        help="create an INTAKE task for one or more repositories",
    )
    start.add_argument("requirement", nargs="?", help="requirement text")
    start.add_argument("--requirement", dest="requirement_option", help="requirement text (alternative to positional form)")
    start.add_argument("--repo", action="append", required=True, help="Git repository path; repeat for multiple repositories")
    start.add_argument("--task-id", help="stable task id (generated when omitted)")
    start.add_argument(
        "--flow",
        choices=sorted(FLOW_MODES),
        help=(
            "optional compatibility assertion; the flow is inferred from "
            "--workspace-strategy"
        ),
    )
    start.add_argument(
        "--workspace-strategy",
        choices=sorted(WORKSPACE_STRATEGIES),
        help=(
            "required work mode: in-place and branch infer the lite flow; "
            "worktree infers the full flow"
        ),
    )
    start.add_argument(
        "--protected-branch",
        action="append",
        help=(
            "additional protected branch name; repeat to extend, never "
            "replace, the default main/master/trunk set"
        ),
    )
    _add_data_dir(start)
    start.set_defaults(handler=command_start)

    show = subparsers.add_parser("show", help="show one full task snapshot")
    _add_task(show)
    _add_data_dir(show)
    show.set_defaults(handler=command_show)

    recover_quarantine = subparsers.add_parser(
        "recover-quarantine",
        help=(
            "prove an interrupted child is gone, validate partial "
            "postconditions, and archive its durable quarantine"
        ),
    )
    _add_mutation(recover_quarantine)
    recover_quarantine.set_defaults(handler=command_recover_quarantine)

    recover_atomic_write = subparsers.add_parser(
        "recover-atomic-write",
        help=(
            "inspect and clear rollback evidence left behind by an "
            "interrupted atomic state write"
        ),
    )
    recover_atomic_write.add_argument(
        "--path",
        help=(
            "absolute blocked destination, or one of its rollback files as "
            "reported in details.rollback_candidates"
        ),
    )
    recover_atomic_write.add_argument(
        "--apply",
        action="store_true",
        help=(
            "remove rollback evidence that provably matches the committed "
            "destination; mismatches remain blocked"
        ),
    )
    recover_atomic_write.add_argument(
        "--resolve",
        choices=("keep-current", "restore-rollback"),
        help=(
            "resolve one mismatching candidate; requires --path and "
            "--rollback-sha256"
        ),
    )
    recover_atomic_write.add_argument(
        "--rollback-sha256",
        help="digest of the exact inspected rollback file",
    )
    _add_data_dir(recover_atomic_write)
    recover_atomic_write.set_defaults(
        handler=command_recover_atomic_write
    )

    listing = subparsers.add_parser("list", help="list task summaries")
    listing.add_argument("--active-only", action="store_true", help="exclude DONE and CANCELLED tasks")
    listing.add_argument(
        "--status",
        action="append",
        choices=sorted(ALL_STATES),
        help=(
            "filter by stable status ID; repeat as needed; results also "
            "include display names"
        ),
    )
    _add_data_dir(listing)
    listing.set_defaults(handler=command_list)

    scope = subparsers.add_parser(
        "scope",
        help="show or change the directories where this plugin is active",
    )
    scope.add_argument(
        "--mode",
        choices=sorted(SCOPE_MODES),
        help="allowlist activates only inside included directories; all activates everywhere except excluded ones",
    )
    scope.add_argument(
        "--add",
        action="append",
        metavar="DIR",
        help="include a directory and its subdirectories; the first one switches to allowlist mode; repeatable",
    )
    scope.add_argument(
        "--remove", action="append", metavar="DIR", help="drop an included directory; repeatable"
    )
    scope.add_argument(
        "--add-exclude",
        action="append",
        metavar="DIR",
        help="exclude a directory and its subdirectories; repeatable",
    )
    scope.add_argument(
        "--remove-exclude",
        action="append",
        metavar="DIR",
        help="drop an excluded directory; repeatable",
    )
    scope.add_argument(
        "--clear",
        action="store_true",
        help="reset to the default scope: active in every directory",
    )
    scope.add_argument(
        "--check",
        nargs="?",
        const=".",
        metavar="DIR",
        help="report whether a directory is in scope; defaults to the current directory",
    )
    _add_data_dir(scope)
    scope.set_defaults(handler=command_scope)

    preflight = subparsers.add_parser(
        "preflight",
        help=(
            "preview one exact status decision, then capture and record "
            "complete Git/worktree evidence with the confirmed token"
        ),
    )
    _add_mutation(preflight)
    preflight.add_argument(
        "--repo",
        action="append",
        help=(
            "repository id or path; partial selections only record evidence, "
            "while status transitions require the default all-repository selection"
        ),
    )
    preflight.add_argument("--remote", help="override the parsed default remote")
    preflight.add_argument("--base", help="override the parsed default base branch")
    preflight.add_argument(
        "--preview",
        action="store_true",
        help=(
            "inspect lightweight preflight identity and status inputs without "
            "committing task state, then return the exact prospective edge and token"
        ),
    )
    preflight.add_argument(
        "--confirm-preview",
        metavar="TOKEN",
        help=(
            "apply an unchanged preflight status decision after the reported "
            "edge is confirmed, capturing complete evidence at confirmation time"
        ),
    )
    preflight.add_argument(
        "--accept-evidence-refresh",
        action="store_true",
        help=(
            "with --confirm-preview, explicitly accept the current lightweight "
            "worktree summary when it changed after preview"
        ),
    )
    preflight.set_defaults(handler=command_preflight)

    baseline = subparsers.add_parser(
        "baseline",
        help="pin each repository's remote base commit after baseline-fetch approval",
    )
    _add_mutation(baseline)
    baseline.add_argument(
        "--fetch",
        action="store_true",
        help="fetch before pinning; approval must include --allow-fetch",
    )
    baseline.add_argument(
        "--materialize",
        action="store_true",
        help="create/reuse a detached analysis worktree at base_sha; requires baseline-fetch approval",
    )
    baseline.set_defaults(handler=command_baseline)

    record_index = subparsers.add_parser("record-index", help="record codebase-memory indexing provenance")
    _add_mutation(record_index)
    record_index.add_argument(
        "--role",
        choices=["baseline", "workspace"],
        default="baseline",
        help="index role; baseline is the backward-compatible default",
    )
    record_index.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    record_index.add_argument(
        "--commit",
        help="indexed commit; defaults to pinned base for baseline or current HEAD for workspace",
    )
    record_index.add_argument(
        "--index-id",
        help="external index id; omission requires impact-degraded approval and failed metadata",
    )
    record_index.add_argument("--receipt", help="optional index receipt file to hash")
    record_index.add_argument(
        "--metadata-json",
        help="JSON provenance; workspace requires persistence:false; degraded baseline requires failure provenance",
    )
    record_index.set_defaults(handler=command_record_index)

    artifact = subparsers.add_parser(
        "record-artifact",
        help="hash and record an immutable file or deterministic directory artifact",
    )
    _add_mutation(artifact)
    artifact.add_argument(
        "--path", "--artifact", dest="path", required=True, help="artifact file or directory"
    )
    artifact.add_argument("--kind", required=True, help="artifact kind, for example impact, openspec, plan or review")
    artifact.add_argument(
        "--verdict",
        choices=["PASS", "CONDITIONAL", "FAIL"],
        help="must match the review report's unique first non-empty Verdict: line",
    )
    artifact.add_argument("--metadata-json", help="optional JSON object")
    artifact.set_defaults(handler=command_record_artifact)

    route = subparsers.add_parser("set-route", help="bind direct or openspec to the current impact/index evidence")
    _add_mutation(route)
    route.add_argument("route", nargs="?", choices=["direct", "openspec"], help="development route")
    route.add_argument("--route", dest="route_option", choices=["direct", "openspec"], help="development route")
    route.add_argument("--reason", required=True, help="why this route fits the impact")
    route.set_defaults(handler=command_set_route)

    approve = subparsers.add_parser("approve", help="approve a named gate with an auditable note")
    _add_mutation(approve)
    approve.add_argument(
        "--gate",
        required=True,
        choices=APPROVAL_GATES,
        help="gate name; route approval advances to ROUTE_APPROVED",
    )
    approve.add_argument("--note", required=True, help="approval note")
    approve.add_argument("--artifact-sha256", help="artifact hash; required by evidence-bound gates")
    approve.add_argument(
        "--accept-conditional",
        action="store_true",
        help="explicitly accept a CONDITIONAL review verdict",
    )
    approve.add_argument(
        "--allow-fetch",
        action="store_true",
        help="authorize network fetches (only for --gate baseline-fetch)",
    )
    approve.add_argument(
        "--allow-dirty",
        action="store_true",
        help="approve the exact dirty preflight snapshot (only for baseline-fetch or lite)",
    )
    approve.set_defaults(handler=command_approve)

    transition = subparsers.add_parser(
        "transition",
        help="perform one guarded, separately confirmed state transition",
    )
    _add_mutation(transition)
    transition.add_argument(
        "to",
        nargs="?",
        choices=sorted(ALL_STATES),
        help="target state as a stable ID; responses also include a display name",
    )
    transition.add_argument(
        "--to",
        dest="to_option",
        choices=sorted(ALL_STATES),
        help="target state as a stable ID; responses also include a display name",
    )
    transition.add_argument("--note", help="transition note; required for BLOCKED or CANCELLED")
    transition.set_defaults(handler=command_transition)

    workspace = subparsers.add_parser(
        "prepare-workspace",
        help="record an approvable plan or create its exact isolated Git worktrees",
    )
    _add_mutation(workspace)
    workspace.add_argument("--repo", action="append", help="repository id or path; if supplied, must enumerate all task repositories")
    workspace.add_argument("--branch", help="workspace branch; defaults to codex/<task-id>")
    workspace.add_argument("--path", help="workspace path (only with one selected repository)")
    workspace.add_argument(
        "--workspace-path",
        action="append",
        help="per-repository absolute path override as REPOSITORY=PATH; repeatable",
    )
    workspace.add_argument(
        "--workspace-branch",
        action="append",
        help="per-repository branch override as REPOSITORY=BRANCH; repeatable",
    )
    mode = workspace.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="execute the latest workspace-gate-approved plan exactly",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="record/return a deterministic workspace-plan artifact (default)",
    )
    workspace.set_defaults(handler=command_prepare_workspace)

    tests = subparsers.add_parser("record-test", help="record a named command identity against exact repository fingerprints")
    _add_mutation(tests)
    tests.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    tests.add_argument("--name", required=True, help="test suite name")
    tests.add_argument("--command", dest="test_command", required=True, help="command that was run (recorded, never executed)")
    tests.add_argument("--exit-code", type=int, required=True, help="observed process exit code")
    tests.add_argument("--output", help="optional captured test output file to hash")
    tests.set_defaults(handler=command_record_test)

    review = subparsers.add_parser("review-snapshot", help="capture base...HEAD, cached, unstaged and untracked review inputs")
    _add_mutation(review)
    review.add_argument("--repo", action="append", help="repository id or path; must cover all repositories")
    review.set_defaults(handler=command_review_snapshot)

    cancel = subparsers.add_parser("cancel", help="cancel a non-terminal task with a reason")
    _add_mutation(cancel)
    cancel.add_argument("--reason", required=True, help="cancellation reason")
    cancel.set_defaults(handler=command_cancel)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = build_parser()
        args, unknown = parser.parse_known_args(argv)
        # argparse cannot intermix optional arguments between two optional
        # positionals.  Accept the natural `TASK --expected-revision N TARGET`
        # spelling for these two commands without weakening typo detection.
        if unknown:
            if (
                args.command == "set-route"
                and len(unknown) == 1
                and args.route is None
                and unknown[0] in {"direct", "openspec"}
            ):
                args.route = unknown[0]
            elif (
                args.command == "transition"
                and len(unknown) == 1
                and args.to is None
                and unknown[0] in ALL_STATES
            ):
                args.to = unknown[0]
            else:
                parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        if not hasattr(args, "data_dir"):
            args.data_dir = None
        response = args.handler(args)
        _write_protocol_response(response)
        return 0
    except FlowError as exc:
        response = {
            "ok": False,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }
        _write_protocol_response(response)
        return exc.exit_code
    except KeyboardInterrupt:
        _write_protocol_response(
            {
                "ok": False,
                "error": {
                    "code": "INTERRUPTED",
                    "message": "operation interrupted",
                    "details": {},
                },
            }
        )
        return 130
    except Exception as exc:  # Keep the machine contract even for unexpected failures.
        _write_protocol_response(
            {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "details": {"type": type(exc).__name__},
                },
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
