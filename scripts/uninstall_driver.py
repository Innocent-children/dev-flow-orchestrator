#!/usr/bin/env python3
"""Source-independent, ownership-bounded Dev Flow removal driver.

The stable dispatcher copies this file outside the managed runtime before it
is executed.  Runtime releases are removed only through their receipt-bound
ownership manifests; this module never performs recursive deletion.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, Tuple
import uuid


INSTALLATION_SCHEMA = "dev-flow-lifecycle-installation/1.0.0"
DISPATCHER_PROTOCOL = "dev-flow-dispatcher/1.0.0"
OWNERSHIP_SCHEMA = "dev-flow-runtime-ownership/1.0.0"
RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/2.0.0"
ARTIFACT_RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/3.0.0"
PLUGIN_ID = "dev-flow-orchestrator@personal"
PLUGIN_NAME = "dev-flow-orchestrator"

MAX_INSTALLATION_BYTES = 32 * 1024
MAX_RECEIPT_BYTES = 512 * 1024
MAX_OWNERSHIP_BYTES = 8 * 1024 * 1024
MAX_MARKETPLACE_BYTES = 2 * 1024 * 1024
MAX_CODEX_BYTES = 1024 * 1024
# Each release contributes bounded inventory and removal observations to the
# shared 128-item journal arrays.  This cap leaves room for host, active,
# dispatcher, lifecycle, and recovery evidence in the same transaction.
MAX_RELEASES = 24
MAX_OWNERSHIP_ENTRIES = 100_000
MAX_PATH_BYTES = 8192
_HEX = frozenset("0123456789abcdef")
_RECOVERY_PREFIX = ".dev-flow-uninstall-recovery-"
_RECOVERY_SUPPORT_NAMES = (
    "stable_dispatcher.py",
    "lifecycle_state.py",
    "uninstall_driver.py",
    "installation.json",
)


class UninstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class InstallationEvidence:
    runtime_root: Path
    releases_root: Path
    lifecycle_root: Path
    support_root: Path
    bin_dir: Path
    temporary_root: Path
    marketplace_file: Path
    codex_home: Path
    plugin_id: str
    dispatchers: Mapping[str, str]
    uninstall_driver_sha256: str
    stable_dispatcher_sha256: str
    lifecycle_state_sha256: str
    installation_sha256: str


@dataclass(frozen=True)
class ReleaseClaim:
    path: Path
    release_id: str
    receipt_sha256: Optional[str]
    ownership_sha256: Optional[str]


@dataclass(frozen=True)
class RemovalEvidence:
    exact: bool
    observations: Tuple[Any, ...] = ()
    effects: Tuple[Any, ...] = ()
    retained_paths: Tuple[str, ...] = ()
    recovery: Tuple[str, ...] = ()
    removed_count: int = 0


@dataclass(frozen=True)
class UninstallResult:
    transaction_id: str
    outcome: str
    retained_paths: Tuple[str, ...]
    recovered: bool = False
    detail: Optional[str] = None


class HostRemovalAdapter(Protocol):
    def preflight(self, active: Optional[Any]) -> RemovalEvidence: ...

    def remove_plugin(self, active: Optional[Any]) -> RemovalEvidence: ...

    def remove_marketplace(self, active: Optional[Any]) -> RemovalEvidence: ...


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise UninstallError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise UninstallError(f"non-finite JSON number is forbidden: {value}")


def _read_json(path: Path, maximum: int, label: str) -> tuple[dict[str, Any], bytes]:
    metadata = _regular_metadata(path, label)
    if metadata.st_size > maximum:
        raise UninstallError(f"{label} exceeds its fixed byte cap")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UninstallError(f"{label} cannot be read") from exc
    if len(raw) > maximum:
        raise UninstallError(f"{label} exceeds its fixed byte cap")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UninstallError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise UninstallError(f"{label} must be a JSON object")
    return value, raw


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise UninstallError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path, label: str) -> str:
    _regular_metadata(path, label)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise UninstallError(f"{label} cannot be hashed") from exc
    return digest.hexdigest()


def _is_reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & flag)


def _absolute(path: Path | str, label: str) -> Path:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise UninstallError(f"{label} is invalid")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES or not os.path.isabs(raw):
        raise UninstallError(f"{label} must be a bounded absolute path")
    normalized = os.path.normpath(raw)
    if normalized != raw.rstrip(os.sep) and not (
        Path(raw) == Path(Path(raw).anchor) and normalized == raw
    ):
        raise UninstallError(f"{label} must be lexically normalized")
    return Path(raw)


def _components(path: Path) -> Sequence[Path]:
    parts = path.parts
    current = Path(parts[0])
    result = [current]
    for part in parts[1:]:
        current = current / part
        result.append(current)
    return result


def _safe_ancestors(path: Path, *, leaf: Optional[str] = None) -> None:
    components = _components(path)
    for index, component in enumerate(components):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise UninstallError(f"cannot inspect {component}") from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise UninstallError(f"linked or reparse path is retained: {component}")
        is_leaf = index == len(components) - 1
        if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
            raise UninstallError(f"non-directory ancestor is retained: {component}")
        if is_leaf and leaf == "directory" and not stat.S_ISDIR(metadata.st_mode):
            raise UninstallError(f"special/non-directory path is retained: {component}")
        if is_leaf and leaf == "file" and not stat.S_ISREG(metadata.st_mode):
            raise UninstallError(f"special/non-file path is retained: {component}")


def _regular_metadata(path: Path, label: str) -> os.stat_result:
    _safe_ancestors(path, leaf="file")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UninstallError(f"{label} is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise UninstallError(f"{label} is not a safe regular file")
    return metadata


def _safe_directory(path: Path, label: str) -> Path:
    path = _absolute(path, label)
    _safe_ancestors(path, leaf="directory")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UninstallError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise UninstallError(f"{label} is not a safe directory")
    return path


def _contained(root: Path, path: Path, label: str, *, allow_root: bool = False) -> None:
    try:
        common = os.path.commonpath((os.fspath(root), os.fspath(path)))
    except ValueError as exc:
        raise UninstallError(f"{label} is on another volume") from exc
    if os.path.normcase(common) != os.path.normcase(os.fspath(root)):
        raise UninstallError(f"{label} escapes its product-owned root")
    if path == root and not allow_root:
        raise UninstallError(f"{label} may not select the ownership root")


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _recovery_root(runtime_root: Path) -> Path:
    identity = hashlib.sha256(
        os.path.normcase(str(runtime_root)).encode("utf-8")
    ).hexdigest()[:24]
    return runtime_root.parent / (_RECOVERY_PREFIX + identity)


def load_installation(
    runtime_root: Path,
    bin_dir: Path,
    temporary_root: Path,
    support_root: Optional[Path] = None,
) -> tuple[InstallationEvidence, bytes]:
    runtime_root = _safe_directory(runtime_root, "managed runtime root")
    releases_root = _safe_directory(runtime_root / "releases", "managed releases root")
    lifecycle_root = _absolute(runtime_root / "lifecycle", "lifecycle support root")
    _contained(runtime_root, lifecycle_root, "lifecycle support root")
    support_root = _safe_directory(
        support_root if support_root is not None else lifecycle_root,
        "uninstall support root",
    )
    recovery_root = _absolute(_recovery_root(runtime_root), "uninstall recovery root")
    if support_root not in {lifecycle_root, recovery_root}:
        raise UninstallError("uninstall support root is not a recognized product path")
    bin_dir = _safe_directory(bin_dir, "stable dispatcher directory")
    temporary_root = _safe_directory(temporary_root, "temporary driver root")
    try:
        if os.path.commonpath((str(runtime_root), str(temporary_root))) == str(
            runtime_root
        ):
            raise UninstallError("temporary driver root must be outside managed runtime")
    except ValueError:
        pass
    if support_root != lifecycle_root and temporary_root != support_root:
        raise UninstallError(
            "recovery execution must use its verified support root as temporary root"
        )
    value, raw = _read_json(
        support_root / "installation.json",
        MAX_INSTALLATION_BYTES,
        "lifecycle installation record",
    )
    fields = {
        "schema",
        "dispatcher_protocol",
        "uninstall_driver_sha256",
        "stable_dispatcher_sha256",
        "lifecycle_state_sha256",
        "dispatchers",
        "bin_dir",
        "marketplace_file",
        "codex_home",
        "plugin_id",
    }
    if set(value) != fields or value["schema"] != INSTALLATION_SCHEMA:
        raise UninstallError("lifecycle installation record is not closed")
    if value["dispatcher_protocol"] != DISPATCHER_PROTOCOL:
        raise UninstallError("dispatcher protocol is incompatible")
    if value["plugin_id"] != PLUGIN_ID:
        raise UninstallError("plugin identity is incompatible")
    recorded_bin = _absolute(value["bin_dir"], "recorded dispatcher directory")
    if os.path.normcase(str(recorded_bin)) != os.path.normcase(str(bin_dir)):
        raise UninstallError("dispatcher CLI path disagrees with installation evidence")
    marketplace = _absolute(value["marketplace_file"], "marketplace path")
    codex_home = _absolute(value["codex_home"], "recorded Codex home")
    _safe_ancestors(codex_home)
    dispatchers = value["dispatchers"]
    expected_names = (
        {"dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"}
        if os.name == "nt"
        else {"dev-flow", "dev-flow-mcp", "dev-flow-uninstall"}
    )
    if not isinstance(dispatchers, dict) or set(dispatchers) != expected_names:
        raise UninstallError("dispatcher evidence is not closed")
    validated_dispatchers = {
        name: _digest(dispatchers[name], f"{name} digest")
        for name in sorted(expected_names)
    }
    evidence = InstallationEvidence(
        runtime_root=runtime_root,
        releases_root=releases_root,
        lifecycle_root=lifecycle_root,
        support_root=support_root,
        bin_dir=bin_dir,
        temporary_root=temporary_root,
        marketplace_file=marketplace,
        codex_home=codex_home,
        plugin_id=PLUGIN_ID,
        dispatchers=validated_dispatchers,
        uninstall_driver_sha256=_digest(
            value["uninstall_driver_sha256"], "uninstall driver digest"
        ),
        stable_dispatcher_sha256=_digest(
            value["stable_dispatcher_sha256"], "stable dispatcher digest"
        ),
        lifecycle_state_sha256=_digest(
            value["lifecycle_state_sha256"], "lifecycle state digest"
        ),
        installation_sha256=_sha256_bytes(raw),
    )
    return evidence, raw


def load_lifecycle_state(evidence: InstallationEvidence) -> Any:
    path = evidence.support_root / "lifecycle_state.py"
    if _sha256_file(path, "installed lifecycle state helper") != evidence.lifecycle_state_sha256:
        raise UninstallError("installed lifecycle state helper digest differs")
    name = "_dev_flow_installed_lifecycle_state"
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise UninstallError("installed lifecycle state helper cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise UninstallError("installed lifecycle state helper cannot be loaded") from exc
    return module


def _relative_parts(value: Any, *, allow_root: bool = False) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise UninstallError("ownership path is invalid")
    if allow_root and value == ".":
        return ()
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UninstallError("ownership path is not normalized")
    if any(":" in part for part in path.parts):
        raise UninstallError("ownership path is platform ambiguous")
    if len(value.encode("utf-8")) > MAX_PATH_BYTES:
        raise UninstallError("ownership path exceeds its fixed cap")
    return tuple(path.parts)


def _validate_manifest(value: Any, release_id: str) -> list[dict[str, Any]]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "release_id", "entries"}
        or value["schema"] != OWNERSHIP_SCHEMA
        or value["release_id"] != release_id
        or not isinstance(value["entries"], list)
    ):
        raise UninstallError("runtime ownership manifest is incompatible")
    if len(value["entries"]) > MAX_OWNERSHIP_ENTRIES:
        raise UninstallError("runtime ownership manifest has too many entries")
    entries: list[dict[str, Any]] = []
    for raw in value["entries"]:
        if not isinstance(raw, dict):
            raise UninstallError("ownership entry must be an object")
        entry_type = raw.get("type")
        fields = {"path", "type", "mode", "release_id"}
        if entry_type == "file":
            fields.add("sha256")
        elif entry_type == "symlink":
            fields.add("target")
        elif entry_type != "directory":
            raise UninstallError("ownership entry type is unsupported")
        if set(raw) != fields or raw.get("release_id") != release_id:
            raise UninstallError("ownership entry fields are not closed")
        _relative_parts(raw.get("path"), allow_root=True)
        mode = raw.get("mode")
        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise UninstallError("ownership entry mode is invalid")
        entry = dict(raw)
        if entry_type == "file":
            entry["sha256"] = _digest(raw.get("sha256"), "owned file digest")
        elif entry_type == "symlink":
            target = raw.get("target")
            if not isinstance(target, str) or not target or "\x00" in target:
                raise UninstallError("owned symlink target is invalid")
        entries.append(entry)
    paths = [entry["path"] for entry in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)) or paths.count(".") != 1:
        raise UninstallError("ownership paths are not unique and sorted")
    return entries


def _entry_path(root: Path, entry: Mapping[str, Any]) -> Path:
    return root.joinpath(*_relative_parts(entry["path"], allow_root=True))


def _safe_entry_ancestors(root: Path, path: Path) -> None:
    _safe_ancestors(root, leaf="directory")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UninstallError("owned entry escapes release root") from exc
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        metadata = current.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
        ):
            raise UninstallError("owned entry crosses a linked or special ancestor")


def _entry_matches(root: Path, entry: Mapping[str, Any]) -> bool:
    path = _entry_path(root, entry)
    try:
        _safe_entry_ancestors(root, path)
        metadata = path.lstat()
    except (OSError, UninstallError):
        return False
    if _is_reparse(metadata) or stat.S_IMODE(metadata.st_mode) != entry["mode"]:
        return False
    if entry["type"] == "directory":
        return stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)
    if entry["type"] == "symlink":
        # An exact POSIX ownership entry can be unlinked without following its
        # target.  Windows reparse-backed links remain outside this contract.
        try:
            return (
                stat.S_ISLNK(metadata.st_mode)
                and not _is_reparse(metadata)
                and os.readlink(path) == entry["target"]
            )
        except OSError:
            return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and _sha256_file(path, "owned runtime file") == entry["sha256"]
    )


def _verify_release_inventory(root: Path, entries: Sequence[Mapping[str, Any]]) -> None:
    """Prove a complete, non-linked release inventory before any removal."""

    expected = {str(entry["path"]) for entry in entries if entry["path"] != "."}
    declared_by_path = {
        str(entry["path"]): entry for entry in entries if entry["path"] != "."
    }
    expected.update({"runtime-receipt.json", "ownership-manifest.json"})
    actual: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            raise UninstallError("release inventory cannot be enumerated") from exc
        for child in children:
            try:
                metadata = child.lstat()
            except OSError as exc:
                raise UninstallError("release inventory changed during observation") from exc
            relative = child.relative_to(root).as_posix()
            actual.add(relative)
            if len(actual) > MAX_OWNERSHIP_ENTRIES + 2:
                raise UninstallError("release inventory exceeds its fixed entry cap")
            if stat.S_ISLNK(metadata.st_mode):
                declared = declared_by_path.get(relative)
                if declared is None or _is_reparse(metadata):
                    raise UninstallError(f"linked release entry: {relative}")
                if declared["type"] != "symlink":
                    raise UninstallError(f"linked release entry changed: {relative}")
                try:
                    if os.readlink(child) != declared["target"]:
                        raise UninstallError(f"linked release entry changed: {relative}")
                except OSError as exc:
                    raise UninstallError(
                        f"linked release entry is unreadable: {relative}"
                    ) from exc
                continue
            if _is_reparse(metadata):
                raise UninstallError(f"reparse release entry: {relative}")
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(child)
            elif not stat.S_ISREG(metadata.st_mode):
                raise UninstallError(f"special release entry: {relative}")
    if actual != expected:
        missing = sorted(expected - actual)[:4]
        extra = sorted(actual - expected)[:4]
        raise UninstallError(
            f"release inventory differs from ownership (missing={missing}, extra={extra})"
        )
    for entry in entries:
        if not _entry_matches(root, entry):
            raise UninstallError(f"owned release entry changed: {entry['path']}")


def _remove_exact_entry(
    root: Path, entry: Mapping[str, Any], transaction_id: str
) -> tuple[bool, Optional[str]]:
    path = _entry_path(root, entry)
    quarantine = path.with_name(f".{path.name}.uninstall-{transaction_id}")
    if not os.path.lexists(path) and os.path.lexists(quarantine):
        if entry["type"] == "directory":
            return False, f"{quarantine}: unexpected directory quarantine retained"
        try:
            relocated = dict(entry)
            relocated["path"] = quarantine.relative_to(root).as_posix()
            if not _entry_matches(root, relocated):
                return False, f"{quarantine}: quarantine no longer matches ownership"
            quarantine.unlink()
            _fsync_directory(path.parent)
            return True, None
        except (OSError, UninstallError) as exc:
            return False, f"{quarantine}: interrupted removal cannot be completed: {exc}"
    try:
        _safe_entry_ancestors(root, path)
        before = path.lstat()
    except FileNotFoundError:
        return True, None
    except (OSError, UninstallError) as exc:
        return False, f"{path}: {exc}"
    if _is_reparse(before) or (
        stat.S_ISLNK(before.st_mode) and entry["type"] != "symlink"
    ):
        return False, f"{path}: linked or reparse content retained"
    if entry["type"] == "directory":
        if not _entry_matches(root, entry):
            return False, f"{path}: owned directory changed"
        try:
            path.rmdir()
            _fsync_directory(path.parent)
            return True, None
        except OSError:
            return False, f"{path}: directory is non-empty or concurrent"
    if not _entry_matches(root, entry):
        return False, f"{path}: owned content, type, mode, or digest changed"
    try:
        after = path.lstat()
    except OSError:
        return False, f"{path}: entry changed during validation"
    if _identity(before) != _identity(after):
        return False, f"{path}: entry changed during validation"
    if os.path.lexists(quarantine):
        return False, f"{quarantine}: exact-removal quarantine is occupied"
    try:
        path.rename(quarantine)
        relocated = dict(entry)
        relocated["path"] = quarantine.relative_to(root).as_posix()
        if not _entry_matches(root, relocated):
            if not os.path.lexists(path):
                quarantine.rename(path)
            return False, f"{quarantine}: entry changed before removal"
        quarantine.unlink()
        _fsync_directory(path.parent)
        return True, None
    except (OSError, UninstallError):
        if os.path.lexists(quarantine) and not os.path.lexists(path):
            try:
                quarantine.rename(path)
            except OSError:
                return False, f"{quarantine}: quarantined entry could not be restored"
        return False, f"{path}: exact owned entry could not be removed"


def _remove_exact_file(
    path: Path, expected_digest: str, transaction_id: str, label: str
) -> tuple[bool, bool, Optional[str]]:
    quarantine = path.with_name(f".{path.name}.uninstall-{transaction_id}")
    if not os.path.lexists(path) and os.path.lexists(quarantine):
        try:
            if _sha256_file(quarantine, label) != expected_digest:
                return False, False, f"{quarantine}: quarantine digest changed"
            quarantine.unlink()
            _fsync_directory(path.parent)
            return True, True, None
        except (OSError, UninstallError) as exc:
            return False, False, f"{quarantine}: {exc}"
    if not os.path.lexists(path):
        return True, False, None
    try:
        before = _regular_metadata(path, label)
        if _sha256_file(path, label) != expected_digest:
            return False, False, f"{path}: digest changed"
        after = path.lstat()
        if _identity(before) != _identity(after):
            return False, False, f"{path}: changed during validation"
    except (OSError, UninstallError) as exc:
        return False, False, f"{path}: {exc}"
    if os.path.lexists(quarantine):
        return False, False, f"{quarantine}: quarantine is occupied"
    try:
        path.rename(quarantine)
        if _sha256_file(quarantine, label) != expected_digest:
            quarantine.rename(path)
            return False, False, f"{path}: changed before quarantine verification"
        quarantine.unlink()
        _fsync_directory(path.parent)
        return True, True, None
    except (OSError, UninstallError):
        if os.path.lexists(quarantine) and not os.path.lexists(path):
            try:
                quarantine.rename(path)
            except OSError:
                return False, False, f"{quarantine}: could not restore quarantine"
        return False, False, f"{path}: exact file removal failed"


_RECEIPT_V2_FIELDS = {
    "schema",
    "release_id",
    "source_commit",
    "source_tree",
    "wheel_sha256",
    "plugin_path",
    "plugin_release_manifest_sha256",
    "dev_flow",
    "dependencies",
    "python",
    "runtime_path",
    "launcher_sha256",
    "cli_launcher_sha256",
    "ownership_manifest_sha256",
    "dependency_lock_sha256",
    "created_at",
}
_RECEIPT_V3_FIELDS = {
    "schema",
    "release_id",
    "version",
    "repository",
    "source_commit",
    "source_tree",
    "release_index_sha256",
    "archive_sha256",
    "artifact_manifest_sha256",
    "wheel_sha256",
    "runtime_requirements_sha256",
    "uv_lock_sha256",
    "plugin_path",
    "plugin_release_manifest_sha256",
    "dev_flow",
    "dependencies",
    "python",
    "python_executable_sha256",
    "runtime_path",
    "transaction_id",
    "verifier_sha256",
    "lifecycle_helpers",
    "ownership_manifest_sha256",
    "created_at",
}


def _validate_receipt_identity(
    receipt: Mapping[str, Any], path: Path, release_id: str
) -> str:
    schema = receipt.get("schema")
    expected_fields = (
        _RECEIPT_V3_FIELDS
        if schema == ARTIFACT_RUNTIME_RECEIPT_SCHEMA
        else _RECEIPT_V2_FIELDS
        if schema == RUNTIME_RECEIPT_SCHEMA
        else None
    )
    if expected_fields is None or set(receipt) != expected_fields:
        raise UninstallError("runtime receipt schema or closed fields are incompatible")
    if receipt.get("release_id") != release_id:
        raise UninstallError("receipt release ID differs from directory")
    if receipt.get("runtime_path") != str(path):
        raise UninstallError("receipt runtime path differs from directory")
    if receipt.get("plugin_path") != str(path / "plugin"):
        raise UninstallError("receipt plugin path differs from release")
    return _digest(
        receipt.get("ownership_manifest_sha256"), "ownership manifest digest"
    )


def inspect_release(path: Path, active: Optional[Any]) -> tuple[ReleaseClaim, str, str]:
    release_id = path.name
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise UninstallError("release path is linked content")
        if _is_reparse(metadata):
            raise UninstallError("release path is reparse content")
        if not stat.S_ISDIR(metadata.st_mode):
            raise UninstallError("release path is special/non-directory content")
        receipt, receipt_raw = _read_json(
            path / "runtime-receipt.json", MAX_RECEIPT_BYTES, "runtime receipt"
        )
        ownership_digest = _validate_receipt_identity(receipt, path, release_id)
        receipt_digest = _sha256_bytes(receipt_raw)
        if (
            active is not None
            and active.release_id == release_id
            and active.receipt_sha256 != receipt_digest
        ):
            raise UninstallError("active receipt digest differs from release receipt")
        if (
            active is not None
            and active.release_id == release_id
            and receipt.get("schema") == ARTIFACT_RUNTIME_RECEIPT_SCHEMA
            and active.transaction_id != receipt.get("transaction_id")
        ):
            raise UninstallError("active transaction identity differs from release receipt")
        manifest_path = path / "ownership-manifest.json"
        if _sha256_file(manifest_path, "ownership manifest") != ownership_digest:
            raise UninstallError("ownership manifest digest differs from receipt")
        manifest, _ = _read_json(
            manifest_path, MAX_OWNERSHIP_BYTES, "runtime ownership manifest"
        )
        entries = _validate_manifest(manifest, release_id)
        _verify_release_inventory(path, entries)
        return (
            ReleaseClaim(path, release_id, receipt_digest, ownership_digest),
            "exact",
            "receipt and ownership manifest are digest-bound",
        )
    except (OSError, UninstallError) as exc:
        detail = str(exc)
        if "linked" in detail:
            state = "linked"
        elif "reparse" in detail:
            state = "reparse"
        elif "special" in detail:
            state = "special"
        else:
            state = "unknown"
        return ReleaseClaim(path, release_id, None, None), state, str(exc)


def remove_release(claim: ReleaseClaim, transaction_id: str) -> RemovalEvidence:
    path = claim.path
    if not os.path.lexists(path):
        return RemovalEvidence(True, removed_count=0)
    if claim.receipt_sha256 is None or claim.ownership_sha256 is None:
        return RemovalEvidence(
            False,
            retained_paths=(str(path),),
            recovery=("Inspect the unverifiable release without broad deletion.",),
        )
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
        ):
            raise UninstallError("managed release is linked, reparse, or special")
        receipt_path = path / "runtime-receipt.json"
        manifest_path = path / "ownership-manifest.json"
        if os.path.lexists(receipt_path):
            receipt, raw = _read_json(receipt_path, MAX_RECEIPT_BYTES, "runtime receipt")
            if _sha256_bytes(raw) != claim.receipt_sha256:
                raise UninstallError("runtime receipt changed")
            if _validate_receipt_identity(receipt, path, claim.release_id) != claim.ownership_sha256:
                raise UninstallError("runtime receipt identity changed")
        if not os.path.lexists(manifest_path):
            # Only an already empty directory can be classified after an
            # interruption that removed both control files.
            if any(path.iterdir()):
                raise UninstallError("ownership manifest is missing with remaining content")
            path.rmdir()
            _fsync_directory(path.parent)
            return RemovalEvidence(True, removed_count=1)
        manifest, raw_manifest = _read_json(
            manifest_path, MAX_OWNERSHIP_BYTES, "runtime ownership manifest"
        )
        if _sha256_bytes(raw_manifest) != claim.ownership_sha256:
            raise UninstallError("runtime ownership manifest changed")
        entries = _validate_manifest(manifest, claim.release_id)
    except (OSError, UninstallError) as exc:
        return RemovalEvidence(
            False,
            retained_paths=(str(path),),
            recovery=(f"Retained release: {str(exc)[:512]}",),
        )

    payload = [entry for entry in entries if entry["path"] != "."]
    nondirectories = [entry for entry in payload if entry["type"] != "directory"]
    directories = sorted(
        (entry for entry in payload if entry["type"] == "directory"),
        key=lambda entry: (str(entry["path"]).count("/"), str(entry["path"])),
        reverse=True,
    )
    removed = 0
    retained: list[str] = []
    for entry in nondirectories + directories:
        ok, reason = _remove_exact_entry(path, entry, transaction_id)
        if ok:
            removed += 1
        elif reason is not None:
            retained.append(str(_entry_path(path, entry)))
    if retained:
        return RemovalEvidence(
            False,
            retained_paths=tuple(dict.fromkeys(retained)),
            recovery=("Changed, linked, special, or concurrent release content was retained.",),
            removed_count=removed,
        )
    receipt_ok, receipt_removed, receipt_reason = _remove_exact_file(
        receipt_path, claim.receipt_sha256, transaction_id, "runtime receipt"
    )
    if not receipt_ok:
        return RemovalEvidence(
            False,
            retained_paths=(str(receipt_path),),
            recovery=(receipt_reason or "Runtime receipt was retained.",),
            removed_count=removed,
        )
    removed += int(receipt_removed)
    manifest_ok, manifest_removed, manifest_reason = _remove_exact_file(
        manifest_path,
        claim.ownership_sha256,
        transaction_id,
        "runtime ownership manifest",
    )
    if not manifest_ok:
        return RemovalEvidence(
            False,
            retained_paths=(str(manifest_path),),
            recovery=(manifest_reason or "Ownership manifest was retained.",),
            removed_count=removed,
        )
    removed += int(manifest_removed)
    root_entry = next(entry for entry in entries if entry["path"] == ".")
    ok, reason = _remove_exact_entry(path, root_entry, transaction_id)
    if not ok:
        return RemovalEvidence(
            False,
            retained_paths=(str(path),),
            recovery=(reason or "Release root contains unknown content.",),
            removed_count=removed,
        )
    return RemovalEvidence(True, removed_count=removed + 1)


class CodexHostRemoval:
    """Production exact plugin and personal-marketplace removal adapter."""

    def __init__(self, evidence: InstallationEvidence, state_module: Any) -> None:
        self.evidence = evidence
        self.state = state_module

    def _observation(
        self, subject: str, state: str, digest: Optional[str] = None, detail: Optional[str] = None
    ) -> Any:
        return self.state.ExternalObservation(subject, state, digest, detail)

    def _effect(
        self,
        kind: str,
        subject: str,
        before: Optional[str],
        after: Optional[str],
        applied: bool,
    ) -> Any:
        return self.state.ProvisionalEffect(kind, subject, before, after, applied)

    def _codex_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["CODEX_HOME"] = str(self.evidence.codex_home)
        return environment

    def _plugin_list(self) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        try:
            completed = subprocess.run(
                ["codex", "plugin", "list", "--marketplace", "personal", "--json"],
                check=False,
                capture_output=True,
                timeout=30,
                env=self._codex_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, str(exc)
        if completed.returncode != 0 or len(completed.stdout) > MAX_CODEX_BYTES:
            return None, "Codex plugin observation failed or exceeded its cap"
        try:
            value = json.loads(
                completed.stdout.decode("utf-8"),
                object_pairs_hook=_strict_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, UninstallError) as exc:
            return None, f"Codex plugin observation is invalid: {exc}"
        installed = value.get("installed") if isinstance(value, dict) else None
        if not isinstance(installed, list):
            return None, "Codex plugin observation has no installed array"
        matches = [
            item
            for item in installed
            if isinstance(item, dict) and item.get("pluginId") == PLUGIN_ID
        ]
        if len(matches) > 1:
            return None, "Codex plugin observation contains duplicate product identities"
        return (matches[0] if matches else {}), None

    def _active_version(self, active: Optional[Any]) -> str:
        if active is None:
            raise UninstallError("active authority is absent")
        release_path = _absolute(active.release_path, "active release path")
        if (
            release_path.parent != self.evidence.releases_root
            or release_path.name != active.release_id
        ):
            raise UninstallError("active release path is outside managed releases")
        receipt, raw = _read_json(
            release_path / "runtime-receipt.json",
            MAX_RECEIPT_BYTES,
            "active runtime receipt",
        )
        if _sha256_bytes(raw) != active.receipt_sha256:
            raise UninstallError("active receipt digest differs from active authority")
        _validate_receipt_identity(receipt, release_path, active.release_id)
        if receipt.get("schema") != ARTIFACT_RUNTIME_RECEIPT_SCHEMA:
            raise UninstallError("active runtime is not a versioned artifact release")
        if receipt.get("transaction_id") != active.transaction_id:
            raise UninstallError("active receipt transaction differs from active authority")
        version = receipt.get("version")
        if not isinstance(version, str) or not version:
            raise UninstallError("active receipt version is invalid")
        return version

    def _marketplace_identity(self, active: Any) -> tuple[dict[str, Any], bytes]:
        path = self.evidence.marketplace_file
        if not os.path.lexists(path):
            raise UninstallError("personal marketplace product member is absent")
        marketplace, raw = _read_json(
            path, MAX_MARKETPLACE_BYTES, "personal marketplace"
        )
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list):
            raise UninstallError("personal marketplace has no plugins array")
        matches = [
            item
            for item in plugins
            if isinstance(item, dict) and item.get("name") == PLUGIN_NAME
        ]
        if len(matches) != 1:
            raise UninstallError("personal marketplace product identity is not unique")
        entry = matches[0]
        expected_fields = {"name", "source", "policy", "category"}
        if set(entry) != expected_fields:
            raise UninstallError("personal marketplace product member is not exact")
        if entry.get("policy") != {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        } or entry.get("category") != "Productivity":
            raise UninstallError("personal marketplace product policy is not exact")
        selected = self._marketplace_entry_path(entry)
        expected = Path(active.release_path) / "plugin"
        if selected is None or os.path.normcase(str(selected)) != os.path.normcase(
            str(expected)
        ):
            raise UninstallError("personal marketplace does not select the active plugin")
        return entry, raw

    def preflight(self, active: Optional[Any]) -> RemovalEvidence:
        """Jointly prove active, marketplace, and Codex identity before mutation."""

        retained = (str(self.evidence.marketplace_file),)
        try:
            version = self._active_version(active)
            assert active is not None
            entry, marketplace_raw = self._marketplace_identity(active)
            plugin, error = self._plugin_list()
            if error is not None or plugin is None:
                raise UninstallError(error or "Codex plugin observation is unavailable")
            if (
                plugin.get("pluginId") != PLUGIN_ID
                or plugin.get("installed") is not True
                or plugin.get("enabled") is not True
                or plugin.get("version") != version
            ):
                raise UninstallError(
                    "Codex plugin ID, version, enabled state, or installation state drifted"
                )
            identity = _sha256_bytes(
                json.dumps(
                    {"entry": entry, "plugin": plugin, "version": version},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            return RemovalEvidence(
                True,
                (
                    self._observation(
                        "uninstall-host-identity",
                        "exact",
                        identity,
                        "active receipt, marketplace member, and Codex plugin agree",
                    ),
                    self._observation(
                        "uninstall-marketplace-file",
                        "exact",
                        _sha256_bytes(marketplace_raw),
                        str(self.evidence.marketplace_file),
                    ),
                ),
            )
        except (OSError, UninstallError) as exc:
            if active is not None:
                retained = (str(active.release_path),) + retained
            return RemovalEvidence(
                False,
                (
                    self._observation(
                        "uninstall-host-identity", "changed", detail=str(exc)[:512]
                    ),
                ),
                retained_paths=tuple(dict.fromkeys(retained)),
                recovery=(
                    "Preserve active, marketplace, and Codex state; repair their exact identity before uninstall.",
                ),
            )

    def remove_plugin(self, active: Optional[Any]) -> RemovalEvidence:
        try:
            expected_version = self._active_version(active)
        except (OSError, UninstallError) as exc:
            return RemovalEvidence(
                False,
                (self._observation("codex-plugin", "unknown", detail=str(exc)[:512]),),
                recovery=("Preserve Codex plugin state until active identity is proven.",),
            )
        item, error = self._plugin_list()
        if error is not None or item is None:
            return RemovalEvidence(
                False,
                (self._observation("codex-plugin", "unknown", detail=error),),
                recovery=("Inspect Codex plugin state and rerun uninstall.",),
            )
        if not item or item.get("installed") is not True:
            return RemovalEvidence(
                True,
                (self._observation("codex-plugin", "absent"),),
                (self._effect("plugin", PLUGIN_ID, None, None, False),),
            )
        if item.get("enabled") is not True or item.get("version") != expected_version:
            return RemovalEvidence(
                False,
                (
                    self._observation(
                        "codex-plugin",
                        "changed",
                        detail="plugin ID, version, enabled state, or installation state drifted",
                    ),
                ),
                recovery=("Preserve the drifted Codex plugin and inspect its identity.",),
            )
        before = _sha256_bytes(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        try:
            completed = subprocess.run(
                ["codex", "plugin", "remove", PLUGIN_ID],
                check=False,
                capture_output=True,
                timeout=60,
                env=self._codex_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return RemovalEvidence(
                False,
                (self._observation("codex-plugin", "unknown", before, str(exc)),),
                recovery=("Codex plugin removal failed; no later uninstall stage ran.",),
            )
        after_item, after_error = self._plugin_list()
        if completed.returncode != 0 or after_error is not None or after_item:
            return RemovalEvidence(
                False,
                (
                    self._observation(
                        "codex-plugin",
                        "changed" if after_item else "unknown",
                        before,
                        after_error or "plugin is still installed",
                    ),
                ),
                (self._effect("plugin", PLUGIN_ID, before, None, completed.returncode == 0),),
                recovery=("Read back the personal plugin state before rerunning.",),
            )
        return RemovalEvidence(
            True,
            (self._observation("codex-plugin", "absent", detail="remove read-back exact"),),
            (self._effect("plugin", PLUGIN_ID, before, None, True),),
            removed_count=1,
        )

    def _marketplace_entry_path(self, entry: Mapping[str, Any]) -> Optional[Path]:
        source = entry.get("source")
        if not isinstance(source, dict) or source.get("source") != "local":
            return None
        value = source.get("path")
        if not isinstance(value, str) or not value or "\x00" in value:
            return None
        marketplace_root = self.evidence.marketplace_file.parent.parent.parent
        candidate = Path(value)
        selected = Path(
            os.path.normpath(
                value if candidate.is_absolute() else str(marketplace_root / candidate)
            )
        )
        try:
            _contained(marketplace_root, selected, "marketplace plugin path")
            _safe_ancestors(selected, leaf="directory")
        except UninstallError:
            return None
        return selected

    def remove_marketplace(self, active: Optional[Any]) -> RemovalEvidence:
        path = self.evidence.marketplace_file
        if not os.path.lexists(path):
            return RemovalEvidence(
                True,
                (self._observation("personal-marketplace", "absent"),),
                (self._effect("marketplace", str(path), None, None, False),),
            )
        try:
            marketplace, raw = _read_json(
                path, MAX_MARKETPLACE_BYTES, "personal marketplace"
            )
            plugins = marketplace.get("plugins")
            if not isinstance(plugins, list):
                raise UninstallError("personal marketplace has no plugins array")
            matches = [
                (index, item)
                for index, item in enumerate(plugins)
                if isinstance(item, dict) and item.get("name") == PLUGIN_NAME
            ]
            if len(matches) > 1:
                raise UninstallError("personal marketplace has duplicate product entries")
            if not matches:
                return RemovalEvidence(
                    True,
                    (self._observation("personal-marketplace", "absent"),),
                    (self._effect("marketplace", str(path), None, None, False),),
                )
            index, entry = matches[0]
            if active is None:
                raise UninstallError("marketplace entry exists without active authority")
            expected_plugin = Path(active.release_path) / "plugin"
            selected_plugin = self._marketplace_entry_path(entry)
            if selected_plugin is None or os.path.normcase(str(selected_plugin)) != os.path.normcase(
                str(expected_plugin)
            ):
                raise UninstallError(
                    "marketplace product entry does not select active plugin"
                )
            before_digest = _sha256_bytes(raw)
            before_metadata = path.lstat()
            replacement = dict(marketplace)
            replacement["plugins"] = plugins[:index] + plugins[index + 1 :]
            payload = (
                json.dumps(replacement, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".marketplace.uninstall-", dir=str(path.parent)
            )
            temporary: Optional[Path] = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name != "nt":
                    temporary.chmod(stat.S_IMODE(before_metadata.st_mode))
                current = path.lstat()
                if _identity(current) != _identity(before_metadata) or _sha256_file(
                    path, "personal marketplace"
                ) != before_digest:
                    raise UninstallError("personal marketplace changed concurrently")
                os.replace(temporary, path)
                temporary = None
                if os.name != "nt":
                    descriptor_dir = os.open(str(path.parent), os.O_RDONLY)
                    try:
                        os.fsync(descriptor_dir)
                    finally:
                        os.close(descriptor_dir)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink()
                    except OSError:
                        pass
            after, _ = _read_json(
                path, MAX_MARKETPLACE_BYTES, "personal marketplace"
            )
            if after != replacement:
                raise UninstallError("personal marketplace removal read-back differs")
        except (OSError, UninstallError) as exc:
            state = "concurrent" if "concurrently" in str(exc) else "changed"
            return RemovalEvidence(
                False,
                (self._observation("personal-marketplace", state, detail=str(exc)),),
                retained_paths=(str(path),),
                recovery=(
                    "Preserve the marketplace and resolve its exact product member.",
                ),
            )
        return RemovalEvidence(
            True,
            (
                self._observation(
                    "personal-marketplace",
                    "absent",
                    detail="member-only read-back exact",
                ),
            ),
            (
                self._effect(
                    "marketplace",
                    str(path),
                    before_digest,
                    _sha256_bytes(payload),
                    True,
                ),
            ),
            removed_count=1,
        )


class DurableUninstaller:
    """Run or resume one uninstall transaction under the installation lock."""

    _PHASE_ORDER = {
        "created": 0,
        "removing_host_state": 1,
        "removing_releases": 2,
        "active_removed": 3,
        "removing_dispatchers": 4,
        "removing_lifecycle": 5,
    }

    def __init__(
        self,
        evidence: InstallationEvidence,
        state_module: Any,
        host: HostRemovalAdapter,
        *,
        transaction_id_factory: Callable[[], str] = lambda: "uninstall-" + uuid.uuid4().hex,
        crash_hook: Optional[Callable[[str], None]] = None,
        mutation_hook: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.evidence = evidence
        self.ls = state_module
        self.host = host
        self.transaction_id_factory = transaction_id_factory
        self.crash_hook = crash_hook or (lambda _point: None)
        self.mutation_hook = mutation_hook or (lambda _point: None)
        self.state = state_module.LifecycleState(
            evidence.runtime_root, evidence.releases_root
        )

    def run(self) -> UninstallResult:
        with self.state.lock() as token:
            pending = self.state.non_terminal_transactions(token)
            if len(pending) > 1:
                identifiers = []
                for snapshot in pending:
                    identifiers.append(snapshot.journal.transaction_id)
                    self.state.finish_transaction(
                        token,
                        snapshot,
                        "partial",
                        observations=(
                            self._observation(
                                "uninstall-recovery",
                                "unknown",
                                detail="multiple non-terminal transactions are ambiguous",
                            ),
                        ),
                        recovery=(
                            "Inspect every transaction before further identity-specific mutation.",
                        ),
                    )
                return UninstallResult(
                    identifiers[0],
                    "partial",
                    (),
                    recovered=True,
                    detail="multiple non-terminal transactions classified partial",
                )
            recovered = bool(pending)
            if pending:
                journal = pending[0]
                if journal.journal.operation != "uninstall":
                    terminal = self.state.finish_transaction(
                        token,
                        journal,
                        "partial",
                        observations=(
                            self._observation(
                                "uninstall-recovery",
                                "unknown",
                                detail="pending operation requires its version-matched driver",
                            ),
                        ),
                        recovery=(
                            "Recover the pending operation before starting uninstall.",
                        ),
                    )
                    return self._result(terminal, recovered=True)
                journal = self.state.advance_transaction(
                    token,
                    journal,
                    observations=(
                        self._observation(
                            "uninstall-recovery",
                            "exact",
                            detail=f"resuming {journal.journal.phase}",
                        ),
                    ),
                )
            else:
                completed = [
                    snapshot
                    for snapshot in self.state.scan_transactions(token)
                    if snapshot.journal.operation == "uninstall"
                    and str(self.evidence.support_root)
                    in snapshot.journal.owned_paths
                ]
                if (
                    completed
                    and self.evidence.support_root != self.evidence.lifecycle_root
                    and not os.path.lexists(self.evidence.lifecycle_root)
                ):
                    terminal = completed[-1]
                    if terminal.journal.outcome == "committed":
                        dispatcher = self._remove_uninstall_dispatcher(
                            terminal.journal.transaction_id
                        )
                        recovery = self._remove_recovery_support(
                            terminal.journal.transaction_id
                        ) if dispatcher.exact else RemovalEvidence(False)
                        detail = None
                        if not dispatcher.exact or not recovery.exact:
                            detail = (
                                "committed uninstall retained exact terminal cleanup residue"
                            )
                        return self._result(
                            terminal,
                            recovered=True,
                            detail=detail,
                            existing_only=True,
                        )
                    return self._result(
                        terminal,
                        recovered=True,
                        detail="prior partial uninstall remains authoritative; no new mutation ran",
                    )
                journal = self._create_transaction(token)
            if journal.journal.retained_paths:
                terminal = self.state.finish_transaction(
                    token,
                    journal,
                    "partial",
                    observations=(
                        self._observation(
                            "uninstall-preflight",
                            "unknown",
                            detail="initial or interrupted evidence is unprovable",
                        ),
                    ),
                    recovery=(
                        "Inspect retained paths before starting any identity-specific removal.",
                    ),
                )
                return self._result(
                    terminal,
                    recovered=recovered,
                    detail="uninstall preflight retained unprovable content",
                )
            recovery = self._ensure_recovery_support(
                journal.journal.transaction_id
            )
            journal = self._record(token, journal, recovery)
            if not recovery.exact:
                return self._partial(
                    token,
                    journal,
                    "uninstall recovery support could not be proven exact",
                    recovered,
                )
            self.mutation_hook("recovery_support_ready")
            return self._resume(token, journal, recovered=recovered)

    def _create_transaction(self, token: Any) -> Any:
        active = self.state.read_active(token)
        try:
            claims, observations = self._inventory_release_claims(active.record)
        except UninstallError as exc:
            claims = []
            observations = [
                self._observation(
                    "release-inventory", "unknown", detail=str(exc)[:512]
                )
            ]
        unprovable = tuple(
            str(claim.path)
            for claim in claims
            if claim.receipt_sha256 is None or claim.ownership_sha256 is None
        )
        if not claims and observations and observations[0].state == "unknown":
            unprovable = (str(self.evidence.releases_root),)
        host_preflight = RemovalEvidence(False)
        if not unprovable:
            host_preflight = self._safe_host(
                lambda: self.host.preflight(active.record), "uninstall-host-identity"
            )
            observations.extend(host_preflight.observations)
            if not host_preflight.exact:
                unprovable = tuple(
                    dict.fromkeys(unprovable + host_preflight.retained_paths)
                )
        owned_paths = [str(claim.path) for claim in claims]
        owned_paths.extend(
            str(self.evidence.bin_dir / name)
            for name in sorted(self.evidence.dispatchers)
        )
        owned_paths.extend(
            str(path)
            for path in self._lifecycle_paths()
        )
        recovery_root = _recovery_root(self.evidence.runtime_root)
        owned_paths.extend(
            str(recovery_root / name) for name in _RECOVERY_SUPPORT_NAMES
        )
        owned_paths.append(str(recovery_root))
        owned_paths.append(
            str(self.evidence.temporary_root / "uninstall_driver.py")
        )
        owned_paths = list(dict.fromkeys(owned_paths))
        transaction_id = self.transaction_id_factory()
        return self.state.create_transaction(
            token,
            self.ls.TransactionJournal(
                transaction_id=transaction_id,
                operation="uninstall",
                expected_active=self.state.expectation(active),
                target_release=None,
                previous_authority=active.record,
                external_observations=tuple(observations),
                owned_paths=tuple(owned_paths),
                retained_paths=unprovable,
                recovery=(
                    (
                        "Unprovable managed release or host identity was retained.",
                    )
                    if unprovable
                    else ()
                )
                + host_preflight.recovery,
            ),
        )

    def _inventory_release_claims(
        self, active: Optional[Any]
    ) -> tuple[list[ReleaseClaim], list[Any]]:
        try:
            _safe_ancestors(self.evidence.releases_root, leaf="directory")
            paths = sorted(self.evidence.releases_root.iterdir(), key=lambda item: item.name)
        except (OSError, UninstallError) as exc:
            raise UninstallError("managed releases cannot be inventoried safely") from exc
        if len(paths) > MAX_RELEASES:
            raise UninstallError("managed release count exceeds uninstall cap")
        claims = []
        observations = []
        for path in paths:
            claim, state, detail = inspect_release(path, active)
            claims.append(claim)
            observations.append(
                self._observation("release-inventory", state, detail=str(path))
            )
            if claim.receipt_sha256 is not None:
                observations.append(
                    self._observation(
                        "release-receipt", "exact", claim.receipt_sha256, str(path)
                    )
                )
            if claim.ownership_sha256 is not None:
                observations.append(
                    self._observation(
                        "release-ownership", "exact", claim.ownership_sha256, str(path)
                    )
                )
        return claims, observations

    def _claims_from_journal(self, journal: Any) -> list[ReleaseClaim]:
        receipt: dict[str, str] = {}
        ownership: dict[str, str] = {}
        for item in journal.external_observations:
            if item.detail is None or item.digest is None:
                continue
            if item.subject == "release-receipt":
                receipt[item.detail] = item.digest
            elif item.subject == "release-ownership":
                ownership[item.detail] = item.digest
        claims = []
        for rendered in journal.owned_paths:
            path = Path(rendered)
            if path.parent != self.evidence.releases_root:
                continue
            claims.append(
                ReleaseClaim(
                    path,
                    path.name,
                    receipt.get(str(path)),
                    ownership.get(str(path)),
                )
            )
        return claims

    def _resume(self, token: Any, journal: Any, *, recovered: bool) -> UninstallResult:
        phase = journal.journal.phase
        if phase not in self._PHASE_ORDER:
            terminal = self.state.finish_transaction(
                token,
                journal,
                "partial",
                observations=(
                    self._observation(
                        "uninstall-recovery",
                        "unknown",
                        detail=f"unsupported uninstall phase {phase}",
                    ),
                ),
                recovery=("Inspect the journal before retrying uninstall.",),
            )
            return self._result(terminal, recovered=recovered)

        if self._PHASE_ORDER[phase] <= self._PHASE_ORDER["removing_host_state"]:
            if phase == "created":
                journal = self.state.advance_transaction(
                    token, journal, phase="removing_host_state"
                )
            active = journal.journal.previous_authority
            plugin = self._safe_host(lambda: self.host.remove_plugin(active), "plugin")
            journal = self._record(token, journal, plugin)
            if not plugin.exact:
                return self._partial(
                    token, journal, "Codex plugin state could not be removed exactly", recovered
                )
            self.mutation_hook("plugin_removed")
            self.crash_hook("plugin_removed")
            marketplace = self._safe_host(
                lambda: self.host.remove_marketplace(active), "marketplace"
            )
            journal = self._record(token, journal, marketplace)
            if not marketplace.exact:
                return self._partial(
                    token,
                    journal,
                    "personal marketplace member could not be removed exactly",
                    recovered,
                )
            self.mutation_hook("marketplace_removed")
            self.crash_hook("marketplace_removed")
            journal = self.state.advance_transaction(
                token, journal, phase="removing_releases"
            )
            phase = journal.journal.phase

        if phase == "removing_releases":
            claims = self._claims_from_journal(journal.journal)
            try:
                current_paths = self._current_release_paths()
            except UninstallError as exc:
                journal = self._record(
                    token,
                    journal,
                    RemovalEvidence(
                        False,
                        (
                            self._observation(
                                "release-inventory", "unknown", detail=str(exc)[:512]
                            ),
                        ),
                        retained_paths=(str(self.evidence.releases_root),),
                        recovery=("Managed release inventory was retained.",),
                    ),
                )
                return self._partial(
                    token, journal, "managed release inventory is unprovable", recovered
                )
            claimed_paths = {claim.path for claim in claims}
            unknown = sorted(current_paths - claimed_paths, key=str)
            if unknown:
                journal = self._record(
                    token,
                    journal,
                    RemovalEvidence(
                        False,
                        tuple(
                            self._observation(
                                "release-inventory", "concurrent", detail=str(path)
                            )
                            for path in unknown
                        ),
                        retained_paths=tuple(str(path) for path in unknown),
                        recovery=("Concurrent or undeclared release entries were retained.",),
                    ),
                )
                return self._partial(
                    token, journal, "managed release inventory changed", recovered
                )
            for claim in claims:
                removal = remove_release(claim, journal.journal.transaction_id)
                removal = self._with_release_evidence(removal, claim)
                journal = self._record(token, journal, removal)
                if not removal.exact:
                    return self._partial(
                        token,
                        journal,
                        f"managed release retained: {claim.path}",
                        recovered,
                    )
                self.mutation_hook(f"release_removed:{claim.release_id}")
                self.crash_hook(f"release_removed:{claim.release_id}")
            self.crash_hook("releases_removed")
            active_removal = self._remove_active(token, journal)
            journal = self._record(token, journal, active_removal)
            if not active_removal.exact:
                return self._partial(
                    token, journal, "active authority CAS could not be proven", recovered
                )
            journal = self.state.advance_transaction(
                token, journal, phase="active_removed"
            )
            self.mutation_hook("active_removed")
            self.crash_hook("active_removed")
            phase = journal.journal.phase

        if phase in {"active_removed", "removing_dispatchers"}:
            if phase == "active_removed":
                journal = self.state.advance_transaction(
                    token, journal, phase="removing_dispatchers"
                )
            dispatch = self._remove_cli_mcp_dispatchers(journal.journal.transaction_id)
            journal = self._record(token, journal, dispatch)
            if not dispatch.exact:
                return self._partial(
                    token, journal, "stable CLI/MCP dispatcher removal was partial", recovered
                )
            self.mutation_hook("cli_mcp_dispatchers_removed")
            self.crash_hook("cli_mcp_dispatchers_removed")
            journal = self.state.advance_transaction(
                token, journal, phase="removing_lifecycle"
            )
            phase = journal.journal.phase

        if phase == "removing_lifecycle":
            lifecycle = self._remove_lifecycle_content(journal.journal.transaction_id)
            journal = self._record(token, journal, lifecycle)
            if not lifecycle.exact:
                return self._partial(
                    token, journal, "lifecycle support removal was partial", recovered
                )
            self.mutation_hook("lifecycle_content_removed")
            self.crash_hook("lifecycle_content_removed")

        residue = self._non_authoritative_residue(journal.journal.transaction_id)
        terminal = self.state.finish_transaction(
            token,
            journal,
            "committed",
            retained_paths=self._new_retained(journal, residue),
            recovery=(
                "The persistent lock, generation watermark, and terminal journal are inert uninstall evidence.",
            ),
        )
        self.crash_hook("terminal_durable")
        # The final public entry point remains callable until the transaction
        # is durably terminal.  This closes the otherwise unrecoverable crash
        # window between lifecycle support deletion and journal completion.
        uninstall_dispatcher = self._remove_uninstall_dispatcher(
            terminal.journal.transaction_id
        )
        detail = None
        if uninstall_dispatcher.exact:
            self.mutation_hook("uninstall_dispatcher_removed")
            self.crash_hook("uninstall_dispatcher_removed")
        else:
            detail = "terminal uninstall retained the final dispatcher for exact cleanup"
        recovery_support = self._remove_recovery_support(
            terminal.journal.transaction_id
        ) if uninstall_dispatcher.exact else RemovalEvidence(False)
        if not recovery_support.exact:
            detail = "terminal uninstall retained exact recovery-support residue"
        else:
            self.mutation_hook("recovery_support_removed")
        return self._result(
            terminal,
            recovered=recovered,
            detail=detail,
            existing_only=True,
        )

    def _observation(
        self,
        subject: str,
        state: str,
        digest: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> Any:
        return self.ls.ExternalObservation(subject, state, digest, detail)

    def _effect(
        self,
        kind: str,
        subject: str,
        before: Optional[str],
        after: Optional[str],
        applied: bool,
    ) -> Any:
        return self.ls.ProvisionalEffect(kind, subject, before, after, applied)

    def _record(self, token: Any, journal: Any, evidence: RemovalEvidence) -> Any:
        return self.state.advance_transaction(
            token,
            journal,
            observations=evidence.observations,
            provisional_effects=evidence.effects,
            retained_paths=self._new_retained(journal, evidence.retained_paths),
            recovery=evidence.recovery,
        )

    @staticmethod
    def _new_retained(journal: Any, paths: Sequence[str]) -> Tuple[str, ...]:
        existing = set(journal.journal.retained_paths)
        return tuple(path for path in paths if path not in existing)

    def _partial(
        self, token: Any, journal: Any, detail: str, recovered: bool
    ) -> UninstallResult:
        retained: Tuple[str, ...] = ()
        recovery = (
            "Stop automatic deletion; inspect retained paths and rerun the stable uninstaller.",
        )
        if (
            self.evidence.support_root != self.evidence.lifecycle_root
            and not os.path.lexists(self.evidence.lifecycle_root)
        ):
            retained = self._new_retained(
                journal, (str(self.evidence.support_root),)
            )
            recovery += (
                "The verified uninstall recovery helper was retained at "
                f"{self.evidence.support_root}.",
            )
        terminal = self.state.finish_transaction(
            token,
            journal,
            "partial",
            observations=(self._observation("uninstall", "unknown", detail=detail),),
            retained_paths=retained,
            recovery=recovery,
        )
        return self._result(terminal, recovered=recovered, detail=detail)

    def _result(
        self,
        terminal: Any,
        *,
        recovered: bool,
        detail: Optional[str] = None,
        existing_only: bool = False,
    ) -> UninstallResult:
        retained_paths = tuple(terminal.journal.retained_paths)
        if existing_only:
            retained_paths = tuple(
                path for path in retained_paths if os.path.lexists(path)
            )
        return UninstallResult(
            terminal.journal.transaction_id,
            str(terminal.journal.outcome),
            retained_paths,
            recovered=recovered,
            detail=detail,
        )

    def _safe_host(
        self, callback: Callable[[], RemovalEvidence], label: str
    ) -> RemovalEvidence:
        try:
            value = callback()
            if not isinstance(value, RemovalEvidence):
                raise TypeError("host adapter returned invalid removal evidence")
            return value
        except Exception as exc:
            return RemovalEvidence(
                False,
                (
                    self._observation(
                        label, "unknown", detail=str(exc).replace("\x00", "")[:512]
                    ),
                ),
                recovery=(f"Inspect {label} state before rerunning uninstall.",),
            )

    def _current_release_paths(self) -> set[Path]:
        if not os.path.lexists(self.evidence.releases_root):
            return set()
        try:
            _safe_ancestors(self.evidence.releases_root, leaf="directory")
            paths = set(self.evidence.releases_root.iterdir())
        except (OSError, UninstallError) as exc:
            raise UninstallError("managed releases cannot be re-observed safely") from exc
        if len(paths) > MAX_RELEASES:
            raise UninstallError("managed release count exceeds uninstall cap")
        return paths

    def _with_release_evidence(
        self, removal: RemovalEvidence, claim: ReleaseClaim
    ) -> RemovalEvidence:
        absent = not os.path.lexists(claim.path)
        state = "absent" if removal.exact and absent else "changed"
        retained = removal.retained_paths
        if not absent and str(claim.path) not in retained:
            retained = retained + (str(claim.path),)
        return RemovalEvidence(
            removal.exact and absent,
            removal.observations
            + (
                self._observation(
                    "managed-release", state, claim.receipt_sha256, str(claim.path)
                ),
            ),
            removal.effects
            + (
                self._effect(
                    "runtime",
                    str(claim.path),
                    claim.receipt_sha256,
                    None,
                    removal.removed_count > 0,
                ),
            ),
            retained,
            removal.recovery,
            removal.removed_count,
        )

    def _remove_active(self, token: Any, journal: Any) -> RemovalEvidence:
        expectation = journal.journal.expected_active
        try:
            current = self.state.read_active(token)
            applied = False
            if expectation.present:
                if (
                    current.present
                    and current.generation == expectation.generation
                    and current.digest == expectation.digest
                ):
                    current = self.state.compare_and_delete_active(token, expectation)
                    applied = True
                elif (
                    not current.present
                    and current.generation == expectation.generation + 1
                ):
                    # A crash can occur after the durable delete and before the
                    # journal effect is appended.  The single increment is the
                    # exact idempotence witness for this transaction.
                    applied = True
                else:
                    raise UninstallError("active generation or digest changed")
            elif current.present or current.generation != expectation.generation:
                raise UninstallError("active absence expectation changed")
            return RemovalEvidence(
                True,
                (
                    self._observation(
                        "active-authority",
                        "absent",
                        detail=f"generation={current.generation}",
                    ),
                ),
                (
                    self._effect(
                        "active",
                        str(self.state.active_path),
                        expectation.digest,
                        None,
                        applied,
                    ),
                ),
                removed_count=int(applied),
            )
        except (OSError, self.ls.LifecycleStateError, UninstallError) as exc:
            return RemovalEvidence(
                False,
                (
                    self._observation(
                        "active-authority", "concurrent", detail=str(exc)[:512]
                    ),
                ),
                retained_paths=(str(self.state.active_path),),
                recovery=("Preserve active authority and resolve the CAS mismatch.",),
            )

    def _recovery_expected(self) -> Mapping[str, str]:
        return {
            "stable_dispatcher.py": self.evidence.stable_dispatcher_sha256,
            "lifecycle_state.py": self.evidence.lifecycle_state_sha256,
            "uninstall_driver.py": self.evidence.uninstall_driver_sha256,
            "installation.json": self.evidence.installation_sha256,
        }

    def _ensure_recovery_support(self, transaction_id: str) -> RemovalEvidence:
        recovery_root = _recovery_root(self.evidence.runtime_root)
        expected = self._recovery_expected()
        source_root = self.evidence.support_root
        observations: list[Any] = []
        effects: list[Any] = []
        created = 0
        try:
            _safe_directory(recovery_root.parent, "uninstall recovery parent")
            if os.path.lexists(recovery_root):
                _safe_directory(recovery_root, "uninstall recovery support root")
            else:
                recovery_root.mkdir(mode=0o700)
                _fsync_directory(recovery_root.parent)
                created += 1
            entries = {child.name for child in recovery_root.iterdir()}
            unknown = entries - set(_RECOVERY_SUPPORT_NAMES)
            if unknown:
                raise UninstallError(
                    "uninstall recovery support contains undeclared content: "
                    + ", ".join(sorted(unknown))
                )
            for name in _RECOVERY_SUPPORT_NAMES:
                source = source_root / name
                destination = recovery_root / name
                digest = expected[name]
                if os.path.lexists(destination):
                    if _sha256_file(destination, "uninstall recovery support") != digest:
                        raise UninstallError(f"recovery support {name} digest changed")
                    observations.append(
                        self._observation(
                            "uninstall-recovery-support", "exact", digest, str(destination)
                        )
                    )
                    continue
                if _sha256_file(source, "verified uninstall support") != digest:
                    raise UninstallError(f"source support {name} digest changed")
                with destination.open("xb") as output, source.open("rb") as input_stream:
                    while True:
                        chunk = input_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if _sha256_file(destination, "copied uninstall support") != digest:
                    raise UninstallError(f"copied support {name} digest differs")
                _fsync_directory(recovery_root)
                created += 1
                effects.append(
                    self._effect("recovery-support", str(destination), None, digest, True)
                )
                observations.append(
                    self._observation(
                        "uninstall-recovery-support", "exact", digest, str(destination)
                    )
                )
            return RemovalEvidence(
                True,
                tuple(observations),
                tuple(effects),
                removed_count=created,
            )
        except (OSError, UninstallError) as exc:
            return RemovalEvidence(
                False,
                tuple(observations)
                + (
                    self._observation(
                        "uninstall-recovery-support", "unknown", detail=str(exc)[:512]
                    ),
                ),
                tuple(effects),
                (str(recovery_root),) if os.path.lexists(recovery_root) else (),
                (
                    "Preserve the bounded recovery support and inspect it before retrying.",
                ),
                created,
            )

    def _remove_recovery_support(self, transaction_id: str) -> RemovalEvidence:
        recovery_root = _recovery_root(self.evidence.runtime_root)
        if not os.path.lexists(recovery_root):
            return RemovalEvidence(True)
        try:
            _safe_directory(recovery_root, "uninstall recovery support root")
            entries = {child.name for child in recovery_root.iterdir()}
        except (OSError, UninstallError) as exc:
            return RemovalEvidence(
                False,
                retained_paths=(str(recovery_root),),
                recovery=(f"Recovery support inspection failed: {exc}",),
            )
        if entries != set(_RECOVERY_SUPPORT_NAMES):
            return RemovalEvidence(
                False,
                retained_paths=(str(recovery_root),),
                recovery=("Unknown recovery support content was retained.",),
            )
        effects: list[Any] = []
        for name in (
            "uninstall_driver.py",
            "lifecycle_state.py",
            "installation.json",
            "stable_dispatcher.py",
        ):
            path = recovery_root / name
            digest = self._recovery_expected()[name]
            ok, applied, reason = _remove_exact_file(
                path, digest, transaction_id, "uninstall recovery support"
            )
            effects.append(
                self._effect("recovery-support", str(path), digest, None, applied)
            )
            if not ok:
                return RemovalEvidence(
                    False,
                    effects=tuple(effects),
                    retained_paths=(str(recovery_root),),
                    recovery=(reason or "Recovery support was retained.",),
                )
        try:
            recovery_root.rmdir()
            _fsync_directory(recovery_root.parent)
        except OSError as exc:
            return RemovalEvidence(
                False,
                effects=tuple(effects),
                retained_paths=(str(recovery_root),),
                recovery=(f"Recovery support directory was retained: {exc}",),
            )
        return RemovalEvidence(True, effects=tuple(effects), removed_count=5)

    def _remove_named_dispatchers(
        self, names: Sequence[str], transaction_id: str
    ) -> RemovalEvidence:
        candidates: list[tuple[Path, str]] = []
        retained: list[str] = []
        observations: list[Any] = []
        for name in names:
            path = self.evidence.bin_dir / name
            expected = self.evidence.dispatchers[name]
            if not os.path.lexists(path):
                quarantine = path.with_name(
                    f".{path.name}.uninstall-{transaction_id}"
                )
                if os.path.lexists(quarantine):
                    candidates.append((path, expected))
                    observations.append(
                        self._observation(
                            "stable-dispatcher",
                            "exact",
                            expected,
                            f"interrupted quarantine for {path}",
                        )
                    )
                    continue
                observations.append(
                    self._observation("stable-dispatcher", "absent", detail=str(path))
                )
                continue
            try:
                current = _sha256_file(path, f"stable dispatcher {name}")
                if current != expected:
                    raise UninstallError("dispatcher digest changed")
                candidates.append((path, expected))
                observations.append(
                    self._observation("stable-dispatcher", "exact", current, str(path))
                )
            except (OSError, UninstallError) as exc:
                retained.append(str(path))
                observations.append(
                    self._observation(
                        "stable-dispatcher", "changed", detail=f"{path}: {exc}"
                    )
                )
        if retained:
            return RemovalEvidence(
                False,
                tuple(observations),
                retained_paths=tuple(retained),
                recovery=("Changed or linked stable dispatchers were retained.",),
            )
        effects: list[Any] = []
        removed = 0
        for path, expected in candidates:
            ok, applied, reason = _remove_exact_file(
                path, expected, transaction_id, "stable dispatcher"
            )
            effects.append(
                self._effect("dispatcher", str(path), expected, None, applied)
            )
            removed += int(applied)
            if not ok:
                retained.append(str(path))
                observations.append(
                    self._observation(
                        "stable-dispatcher", "concurrent", detail=reason
                    )
                )
                break
        return RemovalEvidence(
            not retained,
            tuple(observations),
            tuple(effects),
            tuple(retained),
            (() if not retained else ("Concurrent dispatcher content was retained.",)),
            removed,
        )

    def _remove_cli_mcp_dispatchers(self, transaction_id: str) -> RemovalEvidence:
        suffix = ".cmd" if os.name == "nt" else ""
        return self._remove_named_dispatchers(
            (f"dev-flow{suffix}", f"dev-flow-mcp{suffix}"), transaction_id
        )

    def _remove_uninstall_dispatcher(self, transaction_id: str) -> RemovalEvidence:
        suffix = ".cmd" if os.name == "nt" else ""
        return self._remove_named_dispatchers(
            (f"dev-flow-uninstall{suffix}",), transaction_id
        )

    def _lifecycle_paths(self) -> Tuple[Path, ...]:
        return (
            self.evidence.lifecycle_root / "stable_dispatcher.py",
            self.evidence.lifecycle_root / "lifecycle_state.py",
            self.evidence.lifecycle_root / "uninstall_driver.py",
            self.evidence.lifecycle_root / "installation.json",
        )

    def _remove_lifecycle_content(self, transaction_id: str) -> RemovalEvidence:
        expected = {
            self.evidence.lifecycle_root / "stable_dispatcher.py": self.evidence.stable_dispatcher_sha256,
            self.evidence.lifecycle_root / "lifecycle_state.py": self.evidence.lifecycle_state_sha256,
            self.evidence.lifecycle_root / "uninstall_driver.py": self.evidence.uninstall_driver_sha256,
            self.evidence.lifecycle_root / "installation.json": self.evidence.installation_sha256,
        }
        if not os.path.lexists(self.evidence.lifecycle_root):
            return RemovalEvidence(True)
        try:
            _safe_ancestors(self.evidence.lifecycle_root, leaf="directory")
            entries = set(self.evidence.lifecycle_root.iterdir())
        except (OSError, UninstallError) as exc:
            return RemovalEvidence(
                False,
                retained_paths=(str(self.evidence.lifecycle_root),),
                recovery=(f"Lifecycle support could not be inspected: {exc}",),
            )
        allowed_quarantines = {
            path.with_name(f".{path.name}.uninstall-{transaction_id}")
            for path in expected
        }
        unknown = sorted(entries - set(expected) - allowed_quarantines, key=str)
        observations: list[Any] = []
        retained: list[str] = []
        candidates: list[tuple[Path, str]] = []
        for path in unknown:
            retained.append(str(path))
            observations.append(
                self._observation("lifecycle-content", "unknown", detail=str(path))
            )
        for path, digest in expected.items():
            if not os.path.lexists(path):
                quarantine = path.with_name(
                    f".{path.name}.uninstall-{transaction_id}"
                )
                if os.path.lexists(quarantine):
                    candidates.append((path, digest))
                    observations.append(
                        self._observation(
                            "lifecycle-content",
                            "exact",
                            digest,
                            f"interrupted quarantine for {path}",
                        )
                    )
                    continue
                observations.append(
                    self._observation("lifecycle-content", "absent", detail=str(path))
                )
                continue
            try:
                if _sha256_file(path, "lifecycle support") != digest:
                    raise UninstallError("digest changed")
                candidates.append((path, digest))
                observations.append(
                    self._observation("lifecycle-content", "exact", digest, str(path))
                )
            except (OSError, UninstallError) as exc:
                retained.append(str(path))
                observations.append(
                    self._observation(
                        "lifecycle-content", "changed", detail=f"{path}: {exc}"
                    )
                )
        if retained:
            return RemovalEvidence(
                False,
                tuple(observations),
                retained_paths=tuple(retained),
                recovery=("Unknown or changed lifecycle content was retained.",),
            )
        effects: list[Any] = []
        removed = 0
        # installation.json is removed last so all prior removals remain bound
        # to evidence available on disk until the final support-file step.
        candidates.sort(key=lambda pair: pair[0].name == "installation.json")
        for path, digest in candidates:
            ok, applied, reason = _remove_exact_file(
                path, digest, transaction_id, "lifecycle support"
            )
            effects.append(
                self._effect("lifecycle", str(path), digest, None, applied)
            )
            removed += int(applied)
            if not ok:
                return RemovalEvidence(
                    False,
                    tuple(observations)
                    + (
                        self._observation(
                            "lifecycle-content", "concurrent", detail=reason
                        ),
                    ),
                    tuple(effects),
                    (str(path),),
                    ("Concurrent lifecycle support was retained.",),
                    removed,
                )
        try:
            self.evidence.lifecycle_root.rmdir()
            _fsync_directory(self.evidence.lifecycle_root.parent)
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            return RemovalEvidence(
                False,
                tuple(observations),
                tuple(effects),
                (str(self.evidence.lifecycle_root),),
                ("Non-empty or concurrent lifecycle directory was retained.",),
                removed,
            )
        return RemovalEvidence(True, tuple(observations), tuple(effects), removed_count=removed)

    def _non_authoritative_residue(self, transaction_id: str) -> Tuple[str, ...]:
        suffix = ".cmd" if os.name == "nt" else ""
        paths = (
            self.evidence.runtime_root,
            self.evidence.releases_root,
            self.state.lock_path,
            self.state.generation_path,
            self.state.transactions_path,
            self.state.transactions_path / f"{transaction_id}.json",
            self.evidence.bin_dir / f"dev-flow-uninstall{suffix}",
            self.evidence.support_root,
            self.evidence.temporary_root / "uninstall_driver.py",
            self.evidence.temporary_root,
        )
        return tuple(
            dict.fromkeys(str(path) for path in paths if os.path.lexists(path))
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--bin-dir", required=True, type=Path)
    parser.add_argument("--temporary-root", required=True, type=Path)
    parser.add_argument("--support-root", type=Path)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        evidence, _ = load_installation(
            arguments.runtime_root,
            arguments.bin_dir,
            arguments.temporary_root,
            arguments.support_root,
        )
        state_module = load_lifecycle_state(evidence)
        result = DurableUninstaller(
            evidence, state_module, CodexHostRemoval(evidence, state_module)
        ).run()
        print(
            json.dumps(
                {
                    "transaction_id": result.transaction_id,
                    "outcome": result.outcome,
                    "retained_paths": list(result.retained_paths),
                    "recovered": result.recovered,
                    "detail": result.detail,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result.outcome == "committed" else 3
    except (OSError, UninstallError) as exc:
        print(f"Dev Flow uninstall failed safely: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
