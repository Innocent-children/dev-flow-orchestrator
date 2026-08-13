#!/usr/bin/env python3
"""Installed lifecycle command driver for ``dev-flow update`` and ``reinstall``.

The stable dispatcher copies this file outside the managed runtime and verifies
its digest against the installation record before it runs, so both commands
remain executable even when the active release cannot start.  This module is
standard-library only; lifecycle-state and release-resolution code is loaded
from the digest-pinned installation support root.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Mapping, Optional, Sequence, Tuple


INSTALLATION_SCHEMA = "dev-flow-lifecycle-installation/2.0.0"
DISPATCHER_PROTOCOL = "dev-flow-dispatcher/1.0.0"
PLUGIN_ID = "dev-flow-orchestrator@personal"
ARTIFACT_RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/3.0.0"
MAX_INSTALLATION_BYTES = 32 * 1024
MAX_MARKER_BYTES = 16 * 1024
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_PATH_BYTES = 8192
MAX_STDERR_DETAIL = 2048
BACKUP_SCHEMA = "dev-flow-reinstall-backup/1.0.0"
BACKUP_PREFIX = ".dev-flow-reinstall-backup-"
MARKER_QUARANTINE_PREFIX = ".dev-flow-reinstall-marker-"
REINSTALL_TRANSACTION_ENV = "DEV_FLOW_REINSTALL_TRANSACTION_ID"
REINSTALL_GUARD_DIR = "reinstall-command-guard"
EXPECTED_DATA_OWNED_PATHS = ("0.4.0", "web-runtime")
EXPECTED_DATA_MARKER_NAME = "dev-flow-data.json"
# Bounded inventory caps for reinstall data backup and exact removal.
DATA_LIMITS = {
    "entries": 20_000,
    "file_bytes": 64 * 1024 * 1024,
    "total_bytes": 256 * 1024 * 1024,
    "depth": 16,
}
_HEX = frozenset("0123456789abcdef")


class ReleaseCommandError(RuntimeError):
    """Raised when an installed lifecycle command cannot complete safely."""


@dataclass(frozen=True)
class InstallationEvidence:
    runtime_root: Path
    releases_root: Path
    support_root: Path
    bin_dir: Path
    marketplace_file: Path
    codex_home: Path
    data_root: Path
    plugin_id: str
    dispatchers: Mapping[str, str]
    uninstall_driver_sha256: str
    stable_dispatcher_sha256: str
    lifecycle_state_sha256: str
    release_commands_sha256: str
    release_resolver_sha256: str
    installation_sha256: str
    data_owned_paths: Tuple[str, ...]
    data_marker_name: str


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseCommandError("JSON contains a duplicate member: " + key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ReleaseCommandError("non-finite JSON number is forbidden")


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
        raise ReleaseCommandError(label + " cannot be hashed") from exc
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReleaseCommandError("lifecycle evidence is not JSON-safe") from exc


def _is_reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & flag)


def _absolute(path: Path | str, label: str) -> Path:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ReleaseCommandError(label + " is invalid")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES or not os.path.isabs(raw):
        raise ReleaseCommandError(label + " must be a bounded absolute path")
    normalized = os.path.normpath(raw)
    if normalized != raw.rstrip(os.sep) and not (
        Path(raw) == Path(Path(raw).anchor) and normalized == raw
    ):
        raise ReleaseCommandError(label + " must be lexically normalized")
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
            raise ReleaseCommandError("cannot inspect " + str(component)) from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise ReleaseCommandError("linked or reparse path is retained: " + str(component))
        is_leaf = index == len(components) - 1
        if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
            raise ReleaseCommandError("non-directory ancestor is retained: " + str(component))
        if is_leaf and leaf == "directory" and not stat.S_ISDIR(metadata.st_mode):
            raise ReleaseCommandError("special/non-directory path is retained: " + str(component))
        if is_leaf and leaf == "file" and not stat.S_ISREG(metadata.st_mode):
            raise ReleaseCommandError("special/non-file path is retained: " + str(component))


def _regular_metadata(path: Path, label: str) -> os.stat_result:
    _safe_ancestors(path, leaf="file")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseCommandError(label + " is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise ReleaseCommandError(label + " is not a safe regular file")
    return metadata


def _safe_directory(path: Path, label: str) -> Path:
    path = _absolute(path, label)
    _safe_ancestors(path, leaf="directory")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseCommandError(label + " is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise ReleaseCommandError(label + " is not a safe directory")
    return path


def _read_json(path: Path, maximum: int, label: str) -> tuple[dict[str, Any], bytes]:
    metadata = _regular_metadata(path, label)
    if metadata.st_size > maximum:
        raise ReleaseCommandError(label + " exceeds its fixed byte cap")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReleaseCommandError(label + " cannot be read") from exc
    if len(raw) > maximum:
        raise ReleaseCommandError(label + " exceeds its fixed byte cap")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseCommandError(label + " is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReleaseCommandError(label + " must be a JSON object")
    return value, raw


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    if not os.path.lexists(path.parent):
        raise ReleaseCommandError("atomic write parent is absent: " + str(path.parent))
    if os.path.lexists(path):
        _regular_metadata(path, "atomic write target")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + path.name + ".", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def _ensure_directory(path: Path, mode: int = 0o700) -> None:
    for component in _components(path):
        try:
            metadata = os.lstat(component)
        except FileNotFoundError:
            try:
                os.mkdir(component, mode)
            except FileExistsError:
                pass
            metadata = os.lstat(component)
        if (
            stat.S_ISLNK(metadata.st_mode)
            or _is_reparse(metadata)
            or not stat.S_ISDIR(metadata.st_mode)
        ):
            raise ReleaseCommandError(
                "unsafe data directory component: " + str(component)
            )


def _digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise ReleaseCommandError(label + " is not a lowercase SHA-256 digest")
    return value


def load_installation(
    support_root: Path,
    runtime_root: Path,
) -> tuple[InstallationEvidence, bytes]:
    """Load and digest-verify the closed installation evidence."""

    support_root = _safe_directory(support_root, "lifecycle support root")
    runtime_root = _safe_directory(runtime_root, "managed runtime root")
    if support_root != runtime_root / "lifecycle":
        raise ReleaseCommandError("support root is not the managed lifecycle root")
    releases_root = _safe_directory(runtime_root / "releases", "managed releases root")
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
        "release_commands_sha256",
        "release_resolver_sha256",
        "dispatchers",
        "bin_dir",
        "marketplace_file",
        "codex_home",
        "plugin_id",
        "runtime_root",
        "data_root",
        "data_owned_paths",
        "data_marker_name",
    }
    if set(value) != fields or value["schema"] != INSTALLATION_SCHEMA:
        raise ReleaseCommandError("lifecycle installation record is not closed")
    if value["dispatcher_protocol"] != DISPATCHER_PROTOCOL:
        raise ReleaseCommandError("dispatcher protocol is incompatible")
    if value["plugin_id"] != PLUGIN_ID:
        raise ReleaseCommandError("plugin identity is incompatible")
    recorded_runtime = _absolute(value["runtime_root"], "recorded runtime root")
    if os.path.normcase(str(recorded_runtime)) != os.path.normcase(str(runtime_root)):
        raise ReleaseCommandError("recorded runtime root disagrees with the managed runtime")
    bin_dir = _safe_directory(value["bin_dir"], "recorded dispatcher directory")
    marketplace_file = _absolute(value["marketplace_file"], "marketplace path")
    codex_home = _absolute(value["codex_home"], "recorded Codex home")
    _safe_ancestors(codex_home)
    data_root = _absolute(value["data_root"], "recorded Controller task-data root")
    try:
        if os.path.commonpath((str(runtime_root), str(data_root))) in {
            str(runtime_root),
            str(data_root),
        }:
            raise ReleaseCommandError(
                "recorded task-data root overlaps the managed runtime root"
            )
    except ValueError:
        pass
    owned_paths = value["data_owned_paths"]
    if owned_paths != list(EXPECTED_DATA_OWNED_PATHS):
        raise ReleaseCommandError("recorded data ownership paths are invalid")
    marker_name = value["data_marker_name"]
    if marker_name != EXPECTED_DATA_MARKER_NAME:
        raise ReleaseCommandError("recorded data marker name is invalid")
    dispatchers = value["dispatchers"]
    expected_names = (
        {"dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"}
        if os.name == "nt"
        else {"dev-flow", "dev-flow-mcp", "dev-flow-uninstall"}
    )
    if not isinstance(dispatchers, dict) or set(dispatchers) != expected_names:
        raise ReleaseCommandError("dispatcher evidence is not closed")
    evidence = InstallationEvidence(
        runtime_root=runtime_root,
        releases_root=releases_root,
        support_root=support_root,
        bin_dir=bin_dir,
        marketplace_file=marketplace_file,
        codex_home=codex_home,
        data_root=data_root,
        plugin_id=PLUGIN_ID,
        dispatchers={name: _digest(dispatchers[name], name + " digest") for name in sorted(expected_names)},
        uninstall_driver_sha256=_digest(value["uninstall_driver_sha256"], "uninstall driver digest"),
        stable_dispatcher_sha256=_digest(value["stable_dispatcher_sha256"], "stable dispatcher digest"),
        lifecycle_state_sha256=_digest(value["lifecycle_state_sha256"], "lifecycle state digest"),
        release_commands_sha256=_digest(value["release_commands_sha256"], "release commands digest"),
        release_resolver_sha256=_digest(value["release_resolver_sha256"], "release resolver digest"),
        installation_sha256=_sha256_bytes(raw),
        data_owned_paths=tuple(str(item) for item in owned_paths),
        data_marker_name=str(marker_name),
    )
    expected = {
        "stable_dispatcher.py": evidence.stable_dispatcher_sha256,
        "lifecycle_state.py": evidence.lifecycle_state_sha256,
        "uninstall_driver.py": evidence.uninstall_driver_sha256,
        "release_commands.py": evidence.release_commands_sha256,
        "release_resolver.py": evidence.release_resolver_sha256,
        "installation.json": evidence.installation_sha256,
    }
    for name, digest in expected.items():
        if _sha256_file(support_root / name, "installed support " + name) != digest:
            raise ReleaseCommandError(
                "installed support digest differs from installation evidence: " + name
            )
    running = Path(os.path.abspath(__file__))
    if _sha256_file(running, "running release command driver") != evidence.release_commands_sha256:
        raise ReleaseCommandError("running release command driver differs from installation evidence")
    return evidence, raw


def load_support_modules(evidence: InstallationEvidence) -> tuple[Any, Any]:
    """Load digest-pinned lifecycle-state and release-resolver support code."""

    module_names = (
        ("lifecycle_state.py", "_dev_flow_installed_lifecycle_state"),
        ("release_resolver.py", "_dev_flow_installed_release_resolver"),
    )
    cached = tuple(sys.modules.get(module_name) for _name, module_name in module_names)
    if all(module is not None for module in cached):
        return cached[0], cached[1]
    loaded: list[Any] = []
    for name, module_name in module_names:
        path = evidence.support_root / name
        specification = importlib.util.spec_from_file_location(module_name, path)
        if specification is None or specification.loader is None:
            raise ReleaseCommandError("installed support helper cannot be loaded: " + name)
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        try:
            specification.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise ReleaseCommandError("installed support helper failed to load: " + name) from exc
        loaded.append(module)
    return loaded[0], loaded[1]


def _marker_model(evidence: InstallationEvidence, resolver: Any) -> dict[str, object]:
    return {
        "schema": resolver.DATA_OWNERSHIP_SCHEMA,
        "product": resolver.PRODUCT_NAME,
        "data_root": str(evidence.data_root),
        "namespace": resolver.DATA_NAMESPACE,
        "web_runtime": resolver.WEB_RUNTIME_DIR,
    }


def _marker_state(
    evidence: InstallationEvidence, resolver: Any
) -> tuple[bool, Optional[str]]:
    """Return (exact, error) for the current data-ownership marker."""

    path = evidence.data_root / evidence.data_marker_name
    if not os.path.lexists(path):
        return False, None
    try:
        value, _ = _read_json(path, MAX_MARKER_BYTES, "data ownership marker")
    except ReleaseCommandError as exc:
        return False, str(exc)
    if value != _marker_model(evidence, resolver):
        return False, "data ownership marker differs from installation evidence"
    return True, None


def _inventory_data_root(
    data_root: Path,
    *,
    owned_names: set[str],
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Prove a bounded, link-free inventory below the owned data-root names."""

    _safe_directory(data_root, "Controller task-data root")
    entries: list[dict[str, Any]] = []
    total = 0
    pending = [data_root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            return [], "data root cannot be enumerated: " + str(exc)
        directories: list[Path] = []
        for child in children:
            relative = child.relative_to(data_root)
            depth = len(relative.parts)
            if depth > DATA_LIMITS["depth"]:
                return [], "data root exceeds its nesting depth cap"
            if depth == 1 and child.name not in owned_names:
                return [], "data root contains an unowned top-level entry: " + child.name
            try:
                metadata = child.lstat()
            except OSError as exc:
                return [], "data root entry cannot be inspected: " + str(exc)
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
                return [], "data root contains a linked or reparse entry: " + str(child)
            if stat.S_ISDIR(metadata.st_mode):
                entries.append(
                    {
                        "path": relative.as_posix(),
                        "type": "directory",
                        "mode": stat.S_IMODE(metadata.st_mode),
                    }
                )
                directories.append(child)
            elif stat.S_ISREG(metadata.st_mode):
                size, digest = _sha256_entry(child, "data root file")
                total += size
                if total > DATA_LIMITS["total_bytes"]:
                    return [], "data root exceeds its total byte cap"
                entries.append(
                    {
                        "path": relative.as_posix(),
                        "type": "file",
                        "mode": stat.S_IMODE(metadata.st_mode),
                        "size": size,
                        "sha256": digest,
                    }
                )
            else:
                return [], "data root contains a special entry: " + str(child)
            if len(entries) + 1 > DATA_LIMITS["entries"]:
                return [], "data root exceeds its entry cap"
        pending.extend(reversed(directories))
    entries.sort(key=lambda item: str(item["path"]))
    return entries, None


def _sha256_entry(path: Path, label: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(128 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > DATA_LIMITS["file_bytes"]:
                    raise ReleaseCommandError(label + " exceeds its file byte cap")
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseCommandError(label + " cannot be hashed") from exc
    return size, digest.hexdigest()


def _backup_paths(evidence: InstallationEvidence, transaction_id: str) -> tuple[Path, Path]:
    backup_root = evidence.data_root.parent / (BACKUP_PREFIX + transaction_id)
    return backup_root, backup_root / "data"


def _backup_manifest(
    evidence: InstallationEvidence, transaction_id: str, entries: list[dict[str, Any]]
) -> dict[str, object]:
    return {
        "schema": BACKUP_SCHEMA,
        "transaction_id": transaction_id,
        "data_root": str(evidence.data_root),
        "entries": entries,
    }


def _load_backup_manifest(
    backup_root: Path,
    evidence: InstallationEvidence,
    transaction_id: str,
) -> tuple[list[dict[str, Any]], bytes]:
    inventory = backup_root / "inventory.json"
    quarantined = backup_root / ".inventory-delete"
    if os.path.lexists(inventory) and os.path.lexists(quarantined):
        raise ReleaseCommandError("reinstall backup has two inventory authorities")
    selected = inventory if os.path.lexists(inventory) else quarantined
    value, raw = _read_json(
        selected, MAX_MANIFEST_BYTES, "reinstall backup manifest"
    )
    if (
        set(value) != {"schema", "transaction_id", "data_root", "entries"}
        or value["schema"] != BACKUP_SCHEMA
        or value["transaction_id"] != transaction_id
        or value["data_root"] != str(evidence.data_root)
        or not isinstance(value["entries"], list)
    ):
        raise ReleaseCommandError("reinstall backup manifest identity is invalid")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for raw_item in value["entries"]:
        if not isinstance(raw_item, dict):
            raise ReleaseCommandError("reinstall backup entry is not an object")
        kind = raw_item.get("type")
        expected_fields = (
            {"path", "type", "mode", "size", "sha256"}
            if kind == "file"
            else {"path", "type", "mode"}
        )
        if kind not in {"file", "directory"} or set(raw_item) != expected_fields:
            raise ReleaseCommandError("reinstall backup entry is not closed")
        relative = raw_item.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or len(relative.encode("utf-8")) > MAX_PATH_BYTES
            or len(relative.split("/")) > DATA_LIMITS["depth"]
            or relative in seen
        ):
            raise ReleaseCommandError("reinstall backup entry path is invalid")
        mode = raw_item.get("mode")
        if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o7777:
            raise ReleaseCommandError("reinstall backup entry mode is invalid")
        if kind == "file":
            size = raw_item.get("size")
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or not 0 <= size <= DATA_LIMITS["file_bytes"]
            ):
                raise ReleaseCommandError("reinstall backup entry size is invalid")
            _digest(raw_item.get("sha256"), "reinstall backup entry digest")
            total += size
            if total > DATA_LIMITS["total_bytes"]:
                raise ReleaseCommandError("reinstall backup exceeds its total byte cap")
        seen.add(relative)
        entries.append(dict(raw_item))
        if len(entries) > DATA_LIMITS["entries"]:
            raise ReleaseCommandError("reinstall backup exceeds its entry cap")
    if entries != sorted(entries, key=lambda item: str(item["path"])):
        raise ReleaseCommandError("reinstall backup entries are not canonical")
    return entries, raw


def _inventory_digest(entries: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(
        _canonical_bytes({"entries": [dict(item) for item in entries]})
    )


def _bound_inventory_digest(
    journal: Any, evidence: InstallationEvidence
) -> Optional[str]:
    digests = {
        effect.before_digest
        for effect in journal.journal.provisional_effects
        if effect.kind == "data"
        and effect.subject == str(evidence.data_root)
        and effect.applied
        and effect.before_digest is not None
    }
    if len(digests) > 1:
        raise ReleaseCommandError("reinstall journal has conflicting data inventories")
    return next(iter(digests), None)


def _require_bound_inventory(
    journal: Any,
    evidence: InstallationEvidence,
    entries: Sequence[Mapping[str, Any]],
) -> str:
    observed = _inventory_digest(entries)
    expected = _bound_inventory_digest(journal, evidence)
    if expected is None or expected != observed:
        raise ReleaseCommandError(
            "reinstall backup inventory differs from its durable journal"
        )
    return observed


def _verify_backup_payload(
    payload: Path, entries: Sequence[Mapping[str, Any]]
) -> Optional[str]:
    """Prove the moved payload still matches its recorded inventory."""

    try:
        metadata = payload.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            return "backup payload is not a safe directory"
    except OSError as exc:
        return "backup payload is unavailable: " + str(exc)
    expected = {str(item["path"]): item for item in entries}
    observed: set[str] = set()
    pending = [payload]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            return "backup payload cannot be enumerated: " + str(exc)
        for child in children:
            relative = child.relative_to(payload).as_posix()
            if relative not in expected or relative in observed:
                return "backup payload contains an undeclared entry: " + relative
            observed.add(relative)
            item = expected[relative]
            try:
                metadata = child.lstat()
            except OSError as exc:
                return "backup payload entry is unavailable: " + str(exc)
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
                return "backup payload contains a link or reparse entry: " + relative
            if item["type"] == "directory":
                if not stat.S_ISDIR(metadata.st_mode):
                    return "backup payload entry type changed: " + relative
                if stat.S_IMODE(metadata.st_mode) != item["mode"]:
                    return "backup payload directory mode changed: " + relative
                pending.append(child)
            elif item["type"] == "file":
                if not stat.S_ISREG(metadata.st_mode):
                    return "backup payload entry type changed: " + relative
                if stat.S_IMODE(metadata.st_mode) != item["mode"]:
                    return "backup payload file mode changed: " + relative
                size, digest = _sha256_entry(child, "backup payload file")
                if size != item["size"] or digest != item["sha256"]:
                    return "backup payload entry changed: " + relative
            else:
                return "backup payload entry kind is invalid: " + relative
    if observed != set(expected):
        return "backup payload inventory differs from the recorded manifest"
    return None


def _quarantine_remove_file(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    quarantine: Path,
) -> bool:
    """Atomically isolate one path, reverify it, and only then unlink it."""

    if os.path.lexists(path) and os.path.lexists(quarantine):
        return False
    if os.path.lexists(quarantine):
        candidate = quarantine
    elif not os.path.lexists(path):
        return True
    else:
        _regular_metadata(path, "verified removal source")
        _ensure_directory(quarantine.parent)
        try:
            os.rename(path, quarantine)
            _fsync_directory(path.parent)
            if quarantine.parent != path.parent:
                _fsync_directory(quarantine.parent)
        except OSError as exc:
            raise ReleaseCommandError("verified removal source could not be isolated") from exc
        candidate = quarantine
    try:
        metadata = _regular_metadata(candidate, "verified removal quarantine")
        size, digest = _sha256_entry(candidate, "verified removal quarantine")
        if metadata.st_size != expected_size or size != expected_size or digest != expected_sha256:
            if not os.path.lexists(path):
                try:
                    os.rename(candidate, path)
                    _fsync_directory(path.parent)
                except OSError:
                    pass
            return False
        candidate.unlink()
        _fsync_directory(candidate.parent)
        return True
    except (OSError, ReleaseCommandError):
        return False


def _remove_backup_payload(
    payload: Path, entries: Sequence[Mapping[str, Any]]
) -> tuple[list[str], int]:
    """Remove only manifest-proven files, with crash-resumable quarantine."""

    retained: list[str] = []
    removed = 0
    nondirectories = [item for item in entries if item["type"] == "file"]
    directories = sorted(
        (item for item in entries if item["type"] == "directory"),
        key=lambda item: (str(item["path"]).count("/"), str(item["path"])),
        reverse=True,
    )
    quarantine_root = payload.parent / ".deletion-quarantine"
    for index, item in enumerate(nondirectories):
        path = payload.joinpath(*item["path"].split("/"))
        quarantine = quarantine_root / ("entry-{:06d}.bin".format(index))
        if _quarantine_remove_file(
            path,
            expected_size=int(item["size"]),
            expected_sha256=str(item["sha256"]),
            quarantine=quarantine,
        ):
            removed += 1
        else:
            retained.extend(
                str(item_path)
                for item_path in (path, quarantine)
                if os.path.lexists(item_path)
            )
    for item in directories:
        path = payload.joinpath(*item["path"].split("/"))
        if not os.path.lexists(path):
            continue
        try:
            metadata = path.lstat()
            if (
                stat.S_ISDIR(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and not _is_reparse(metadata)
                and stat.S_IMODE(metadata.st_mode) == item["mode"]
            ):
                path.rmdir()
                removed += 1
                continue
        except OSError:
            pass
        retained.append(str(path))
    try:
        payload.rmdir()
        removed += 1
    except OSError:
        retained.append(str(payload))
    if os.path.lexists(quarantine_root):
        try:
            quarantine_root.rmdir()
            _fsync_directory(quarantine_root.parent)
        except OSError:
            retained.append(str(quarantine_root))
    return retained, removed


def _run_bootstrap(
    evidence: InstallationEvidence,
    resolver: Any,
    version: str,
    *,
    timeout: float | None = None,
    reinstall_transaction_id: Optional[str] = None,
) -> dict[str, object]:
    """Acquire and run the target version's bootstrap with recorded paths."""

    with tempfile.TemporaryDirectory(prefix="dev-flow-lifecycle-") as name:
        staging = Path(name).resolve()
        bootstrap = resolver.acquire_version_bootstrap(
            version,
            windows=os.name == "nt",
            destination_dir=staging,
        )
        arguments = [
            "--runtime-root",
            str(evidence.runtime_root),
            "--bin-dir",
            str(evidence.bin_dir),
            "--marketplace-file",
            str(evidence.marketplace_file),
            "--codex-home",
            str(evidence.codex_home),
            "--data-root",
            str(evidence.data_root),
        ]
        environment = os.environ.copy()
        environment.pop("DEV_FLOW_SOURCE_ROOT", None)
        environment.pop(REINSTALL_TRANSACTION_ENV, None)
        if reinstall_transaction_id is not None:
            environment[REINSTALL_TRANSACTION_ENV] = reinstall_transaction_id
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if os.name == "nt":
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(bootstrap),
                *arguments,
            ]
        else:
            command = ["/bin/sh", str(bootstrap), *arguments]
        try:
            completed = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseCommandError(
                "versioned bootstrap could not run: " + str(exc)
            ) from exc
        payload: Optional[dict[str, Any]] = None
        for raw_line in completed.stdout.splitlines():
            try:
                value = json.loads(raw_line.decode("utf-8"), object_pairs_hook=_strict_object)
            except (UnicodeDecodeError, ValueError):
                continue
            if isinstance(value, dict) and "outcome" in value:
                payload = value
            elif isinstance(value, dict) and "ok" in value and payload is None:
                payload = value
        if payload is None:
            payload = {"ok": False}
        return {
            "returncode": completed.returncode,
            "outcome": payload.get("outcome", "committed" if completed.returncode == 0 else "partial"),
            "payload": payload,
        }


def update_command(
    evidence: InstallationEvidence,
    *,
    lock_timeout: float = 30.0,
) -> dict[str, object]:
    """Upgrade to the latest official release, idempotently when already there."""

    _state_module, resolver = load_support_modules(evidence)
    latest = resolver.resolve_latest_version()
    # Phase B owns the complete reuse decision: it attests the managed runtime,
    # startup/read-back, public dispatcher proof, and stable infrastructure.
    # A receipt-only shortcut would incorrectly accept a latest release whose
    # verifier, environment, plugin, or public startup path is broken.
    bootstrap = _run_bootstrap(evidence, resolver, latest)
    committed = bool(
        bootstrap["returncode"] == 0 and bootstrap["outcome"] == "committed"
    )
    result = {
        "ok": committed,
        "mode": "update",
        "outcome": bootstrap["outcome"],
        "version": latest,
        "transaction_id": None,
        "detail": "the latest official release bootstrap completed",
    }
    payload = bootstrap["payload"]
    if isinstance(payload, dict):
        result["transaction_id"] = payload.get("transaction_id")
        result["reused"] = bool(payload.get("reused"))
        result["detail"] = payload.get("detail") or result["detail"]
    return result


def _ensure_data_removed(
    state: Any,
    state_module: Any,
    token: Any,
    journal: Any,
    evidence: InstallationEvidence,
    resolver: Any,
) -> tuple[Any, str]:
    """Remove Dev Flow-owned data under one durable reinstall journal.

    Removal is idempotent: an interrupted run resumes from the journal phase
    and the on-disk backup layout without re-mutating already removed data.
    """

    transaction_id = journal.journal.transaction_id
    if journal.journal.phase == "created":
        journal = state.advance_transaction(token, journal, phase="removing_data")
    data_root = evidence.data_root
    backup_root, payload = _backup_paths(evidence, transaction_id)
    marker = _marker_model(evidence, resolver)
    marker_path = data_root / evidence.data_marker_name
    owned = {evidence.data_marker_name, *evidence.data_owned_paths}
    payload_exists = os.path.lexists(payload)
    backup_exists = os.path.lexists(backup_root)
    marker_exact = data_root.exists() and _marker_state(evidence, resolver)[0]
    existing_owned = {
        os.path.normcase(item) for item in journal.journal.owned_paths
    }

    def new_owned(paths: Sequence[Path]) -> tuple[str, ...]:
        result = []
        for path in paths:
            rendered = str(path)
            if os.path.normcase(rendered) not in existing_owned:
                result.append(rendered)
                existing_owned.add(os.path.normcase(rendered))
        return tuple(result)

    def observation(subject: str, state_value: str, detail: Optional[str] = None) -> Any:
        return state_module.ExternalObservation(subject, state_value, detail=detail)

    if payload_exists and marker_exact:
        try:
            entries, _manifest_raw = _load_backup_manifest(
                backup_root, evidence, transaction_id
            )
            error = _verify_backup_payload(payload, entries)
            if error is not None:
                raise ReleaseCommandError(error)
            observed_inventory = _inventory_digest(entries)
            bound_inventory = _bound_inventory_digest(journal, evidence)
            if (
                bound_inventory is not None
                and bound_inventory != observed_inventory
            ):
                raise ReleaseCommandError(
                    "reinstall backup inventory differs from its durable journal"
                )
        except (OSError, ReleaseCommandError) as exc:
            journal = state.advance_transaction(
                token,
                journal,
                observations=(
                    observation("data-removal", "changed", str(exc)),
                ),
                retained_paths=(str(backup_root), str(data_root)),
                recovery=("Inspect the changed reinstall backup before retrying.",),
            )
            return journal, "partial"
        journal = state.advance_transaction(
            token,
            journal,
            observations=(
                observation(
                    "data-removal", "exact",
                    "resumed after data removal completed; backup retained for rollback",
                ),
            ),
            provisional_effects=(
                ()
                if bound_inventory is not None
                else (
                    state_module.ProvisionalEffect(
                        "data",
                        str(data_root),
                        observed_inventory,
                        _sha256_bytes(_canonical_bytes(marker)),
                        True,
                    ),
                )
            ),
            owned_paths=new_owned((backup_root, payload, data_root, marker_path)),
            recovery=("The reinstall backup is required until the new install commits.",),
        )
        return journal, "completed"
    if backup_exists and not payload_exists:
        try:
            _safe_directory(backup_root, "reinstall backup root")
            children = sorted(child.name for child in backup_root.iterdir())
            if children not in (["inventory.json"], [".inventory-delete"]):
                raise ReleaseCommandError(
                    "pre-move reinstall backup contains unexpected content"
                )
            entries, manifest_raw = _load_backup_manifest(
                backup_root, evidence, transaction_id
            )
            error = _verify_backup_payload(data_root, entries)
            if error is not None:
                raise ReleaseCommandError(error)
            if not _quarantine_remove_file(
                backup_root / "inventory.json",
                expected_size=len(manifest_raw),
                expected_sha256=_sha256_bytes(manifest_raw),
                quarantine=backup_root / ".inventory-delete",
            ):
                raise ReleaseCommandError(
                    "pre-move reinstall inventory could not be removed exactly"
                )
            backup_root.rmdir()
            _fsync_directory(backup_root.parent)
        except (OSError, ReleaseCommandError) as exc:
            journal = state.advance_transaction(
                token,
                journal,
                observations=(
                    observation(
                        "data-removal",
                        "unknown",
                        "pre-move reinstall backup could not be recovered: " + str(exc),
                    ),
                ),
                retained_paths=(str(backup_root), str(data_root)),
                recovery=("Inspect the reinstall backup before further data mutation.",),
            )
            return journal, "partial"
        # The crash happened after the manifest was durable but before the
        # rename.  Exact inventory equality proves that no data mutation had
        # begun, so remove the stale shell and retry the same transaction.
        return _ensure_data_removed(
            state, state_module, token, journal, evidence, resolver
        )
    if payload_exists and data_root.exists() and not marker_exact:
        try:
            _safe_directory(data_root, "fresh Controller task-data root")
            if list(data_root.iterdir()):
                raise ReleaseCommandError("fresh task-data root is not empty")
            entries, _manifest_raw = _load_backup_manifest(
                backup_root, evidence, transaction_id
            )
            error = _verify_backup_payload(payload, entries)
            if error is not None:
                raise ReleaseCommandError(error)
            _atomic_write(marker_path, _canonical_bytes(marker))
        except (OSError, ReleaseCommandError) as exc:
            journal = state.advance_transaction(
                token,
                journal,
                observations=(
                    observation(
                        "data-removal",
                        "concurrent",
                        "data root reappeared without its marker: " + str(exc),
                    ),
                ),
                retained_paths=(str(backup_root), str(data_root)),
                recovery=("Inspect the reinstall backup and recreated data root.",),
            )
            return journal, "partial"
        return _ensure_data_removed(
            state, state_module, token, journal, evidence, resolver
        )

    if not os.path.lexists(data_root):
        _ensure_directory(data_root)
        _atomic_write(marker_path, _canonical_bytes(marker))
        if payload_exists:
            return _ensure_data_removed(
                state, state_module, token, journal, evidence, resolver
            )
        journal = state.advance_transaction(
            token,
            journal,
            observations=(
                observation("data-removal", "exact", "task-data root was absent; created fresh with marker"),
            ),
            provisional_effects=(
                state_module.ProvisionalEffect(
                    "data", str(marker_path), None, _sha256_bytes(_canonical_bytes(marker)), True
                ),
            ),
            owned_paths=new_owned((data_root, marker_path)),
        )
        return journal, "completed"

    marker_error: Optional[str] = None
    _safe_directory(data_root, "Controller task-data root")
    marker_exact, marker_error = _marker_state(evidence, resolver)
    if marker_error is not None:
        journal = state.advance_transaction(
            token,
            journal,
            observations=(observation("data-removal", "changed", marker_error),),
            retained_paths=(str(data_root),),
            recovery=("Preserve the drifted data ownership marker and inspect it.",),
        )
        return journal, "partial"
    entries, error = _inventory_data_root(data_root, owned_names=owned)
    if error is not None:
        journal = state.advance_transaction(
            token,
            journal,
            observations=(observation("data-removal", "unknown", error),),
            retained_paths=(str(data_root),),
            recovery=(
                "Preserve unowned, linked, special, or unbounded data content before retrying.",
            ),
        )
        return journal, "partial"

    backup_root.mkdir(mode=0o700, exist_ok=False)
    _fsync_directory(backup_root.parent)
    _atomic_write(
        backup_root / "inventory.json",
        _canonical_bytes(_backup_manifest(evidence, transaction_id, entries)),
    )
    try:
        os.rename(data_root, payload)
        _fsync_directory(backup_root.parent)
    except OSError as exc:
        retained = (str(backup_root), str(data_root))
        journal = state.advance_transaction(
            token,
            journal,
            observations=(observation("data-removal", "unknown", "data root could not be moved: " + str(exc)),),
            retained_paths=retained,
            recovery=("Inspect the reinstall backup and the unmoved data root.",),
        )
        return journal, "partial"
    _ensure_directory(data_root)
    _atomic_write(marker_path, _canonical_bytes(marker))
    journal = state.advance_transaction(
        token,
        journal,
        observations=(
            observation("data-removal", "exact", "Dev Flow-owned task data moved to the transaction backup"),
        ),
        provisional_effects=(
            state_module.ProvisionalEffect(
                "data",
                str(data_root),
                _inventory_digest(entries),
                _sha256_bytes(_canonical_bytes(marker)),
                True,
            ),
        ),
        owned_paths=new_owned((backup_root, payload, data_root, marker_path)),
        recovery=("The reinstall backup is required until the new install commits.",),
    )
    return journal, "completed"


def _remove_fresh_data_root(
    evidence: InstallationEvidence, resolver: Any, transaction_id: str
) -> tuple[list[str], bool]:
    """Remove the marker-only data root created by removal; verify it first."""

    data_root = evidence.data_root
    marker_path = data_root / evidence.data_marker_name
    quarantine = data_root.parent / (
        MARKER_QUARANTINE_PREFIX + transaction_id
    )
    retained: list[str] = []
    try:
        marker_raw = _canonical_bytes(_marker_model(evidence, resolver))
        children = sorted(child.name for child in data_root.iterdir())
        allowed = (
            [evidence.data_marker_name]
            if os.path.lexists(marker_path)
            else []
        )
        if children != allowed or (
            not os.path.lexists(marker_path) and not os.path.lexists(quarantine)
        ):
            return [str(data_root), str(quarantine)], False
        if not _quarantine_remove_file(
            marker_path,
            expected_size=len(marker_raw),
            expected_sha256=_sha256_bytes(marker_raw),
            quarantine=quarantine,
        ):
            return [str(data_root), str(quarantine)], False
        data_root.rmdir()
        _fsync_directory(data_root.parent)
        return [], True
    except (OSError, ReleaseCommandError):
        return [str(data_root)], False


def _restore_data(
    state: Any,
    state_module: Any,
    token: Any,
    journal: Any,
    evidence: InstallationEvidence,
    resolver: Any,
) -> tuple[Any, str]:
    """Restore the moved task data exactly after a failed install."""

    transaction_id = journal.journal.transaction_id
    data_root = evidence.data_root
    backup_root, payload = _backup_paths(evidence, transaction_id)
    marker = _marker_model(evidence, resolver)
    marker_path = data_root / evidence.data_marker_name

    def observation(subject: str, state_value: str, detail: Optional[str] = None) -> Any:
        return state_module.ExternalObservation(subject, state_value, detail=detail)

    if not os.path.lexists(backup_root) and not os.path.lexists(payload):
        if not os.path.lexists(data_root):
            journal = state.advance_transaction(
                token, journal,
                observations=(observation("data-restoration", "exact", "no task data required restoration"),),
            )
            return journal, "rolled_back"
        retained, exact = _remove_fresh_data_root(
            evidence, resolver, transaction_id
        )
        journal = state.advance_transaction(
            token,
            journal,
            observations=(
                observation(
                    "data-restoration",
                    "exact" if exact else "changed",
                    "removed the marker-only data root created for an absent task-data root",
                ),
            ),
            retained_paths=tuple(retained),
            recovery=() if exact else ("Inspect the retained data root.",),
        )
        return journal, "rolled_back" if exact else "partial"
    if not os.path.lexists(payload):
        try:
            _safe_directory(backup_root, "reinstall backup root")
            children = sorted(child.name for child in backup_root.iterdir())
            if children not in (["inventory.json"], [".inventory-delete"]):
                raise ReleaseCommandError(
                    "restored reinstall backup contains unexpected content"
                )
            entries, manifest_raw = _load_backup_manifest(
                backup_root, evidence, transaction_id
            )
            _require_bound_inventory(journal, evidence, entries)
            error = _verify_backup_payload(data_root, entries)
            if error is not None:
                raise ReleaseCommandError(error)
            if not _quarantine_remove_file(
                backup_root / "inventory.json",
                expected_size=len(manifest_raw),
                expected_sha256=_sha256_bytes(manifest_raw),
                quarantine=backup_root / ".inventory-delete",
            ):
                raise ReleaseCommandError(
                    "restored backup inventory could not be removed exactly"
                )
            backup_root.rmdir()
            _fsync_directory(backup_root.parent)
        except (OSError, ReleaseCommandError) as exc:
            journal = state.advance_transaction(
                token,
                journal,
                observations=(
                    observation(
                        "data-restoration",
                        "unknown",
                        "backup payload is missing: " + str(exc),
                    ),
                ),
                retained_paths=(str(backup_root), str(data_root)),
                recovery=("Inspect the incomplete reinstall backup before retrying.",),
            )
            return journal, "partial"
        journal = state.advance_transaction(
            token,
            journal,
            observations=(
                observation(
                    "data-restoration",
                    "exact",
                    "resumed after the moved task data had already been restored",
                ),
            ),
        )
        return journal, "rolled_back"
    try:
        entries, manifest_raw = _load_backup_manifest(
            backup_root, evidence, transaction_id
        )
        _require_bound_inventory(journal, evidence, entries)
        error = _verify_backup_payload(payload, entries)
        if error is not None:
            raise ReleaseCommandError(error)
        marker_raw = _canonical_bytes(marker)
        marker_quarantine = backup_root / ".fresh-marker-delete"
        if os.path.lexists(data_root):
            children = sorted(child.name for child in data_root.iterdir())
            allowed = (
                [evidence.data_marker_name]
                if os.path.lexists(marker_path)
                else []
            )
            if children != allowed or (
                not os.path.lexists(marker_path)
                and not os.path.lexists(marker_quarantine)
            ):
                raise ReleaseCommandError("fresh data root contains unexpected content")
            if not _quarantine_remove_file(
                marker_path,
                expected_size=len(marker_raw),
                expected_sha256=_sha256_bytes(marker_raw),
                quarantine=marker_quarantine,
            ):
                raise ReleaseCommandError("fresh data root marker changed during removal")
            data_root.rmdir()
            _fsync_directory(data_root.parent)
        elif os.path.lexists(marker_quarantine) and not _quarantine_remove_file(
            marker_path,
            expected_size=len(marker_raw),
            expected_sha256=_sha256_bytes(marker_raw),
            quarantine=marker_quarantine,
        ):
            raise ReleaseCommandError("fresh data root marker quarantine changed")
        os.rename(payload, data_root)
        _fsync_directory(data_root.parent)
        if not _quarantine_remove_file(
            backup_root / "inventory.json",
            expected_size=len(manifest_raw),
            expected_sha256=_sha256_bytes(manifest_raw),
            quarantine=backup_root / ".inventory-delete",
        ):
            raise ReleaseCommandError("backup inventory could not be removed exactly")
        backup_root.rmdir()
        _fsync_directory(backup_root.parent)
    except (OSError, ReleaseCommandError) as exc:
        journal = state.advance_transaction(
            token,
            journal,
            observations=(observation("data-restoration", "unknown", str(exc))),
            retained_paths=(str(backup_root), str(data_root)),
            recovery=("Inspect the reinstall backup and restore it manually.",),
        )
        return journal, "partial"
    journal = state.advance_transaction(
        token,
        journal,
        observations=(
            observation("data-restoration", "exact", "moved task data restored to its recorded root"),
            observation(
                "data-restoration-check",
                "exact",
                "restored inventory still matches the recorded manifest",
            ),
        ),
        provisional_effects=(
            state_module.ProvisionalEffect(
                "data",
                str(data_root),
                None,
                _sha256_bytes(_canonical_bytes(marker)),
                True,
            ),
        ),
    )
    return journal, "rolled_back"


def _remove_backup_after_commit(
    state: Any,
    state_module: Any,
    token: Any,
    journal: Any,
    evidence: InstallationEvidence,
) -> tuple[Any, bool]:
    """Delete the verified backup after a committed install, or retain it."""

    transaction_id = journal.journal.transaction_id
    backup_root, payload = _backup_paths(evidence, transaction_id)
    if not os.path.lexists(backup_root) and not os.path.lexists(payload):
        return journal, True
    retained: list[str] = []
    try:
        if not os.path.lexists(payload):
            raise ReleaseCommandError("backup payload is missing")
        entries, manifest_raw = _load_backup_manifest(
            backup_root, evidence, transaction_id
        )
        _require_bound_inventory(journal, evidence, entries)
        retained, _removed = _remove_backup_payload(payload, entries)
        if retained:
            raise ReleaseCommandError("backup payload removal was not exact")
        if not _quarantine_remove_file(
            backup_root / "inventory.json",
            expected_size=len(manifest_raw),
            expected_sha256=_sha256_bytes(manifest_raw),
            quarantine=backup_root / ".inventory-delete",
        ):
            raise ReleaseCommandError("backup inventory could not be removed exactly")
        backup_root.rmdir()
        _fsync_directory(backup_root.parent)
    except (OSError, ReleaseCommandError) as exc:
        retained = sorted(set(retained) | {str(backup_root)})
        journal = state.advance_transaction(
            token,
            journal,
            observations=(
                state_module.ExternalObservation(
                    "data-backup-cleanup", "unknown", detail=str(exc)
                ),
            ),
            retained_paths=tuple(retained),
            recovery=(
                "The committed reinstall retained its verified backup for exact cleanup.",
            ),
        )
        return journal, False
    journal = state.advance_transaction(
        token,
        journal,
        observations=(
            state_module.ExternalObservation(
                "data-backup-cleanup", "exact", detail="verified backup removed"
            ),
        ),
    )
    return journal, True


def _bootstrap_active_matches(
    state: Any, token: Any, bootstrap: Mapping[str, object]
) -> bool:
    """Bind a committed bootstrap result to the lock-protected active record."""

    payload = bootstrap.get("payload")
    if not isinstance(payload, dict):
        return False
    reported = payload.get("active")
    if not isinstance(reported, dict):
        return False
    current = state.read_active(token).record
    return current is not None and reported == current.as_dict()


def _reinstall_command_guarded(
    evidence: InstallationEvidence,
    state_module: Any,
    resolver: Any,
    *,
    lock_timeout: float = 30.0,
) -> dict[str, object]:
    """Run one reinstall while its process-level operation guard is held."""

    latest = resolver.resolve_latest_version()
    state = state_module.LifecycleState(evidence.runtime_root, evidence.releases_root)

    def observation(subject: str, state_value: str, detail: Optional[str] = None) -> Any:
        return state_module.ExternalObservation(subject, state_value, detail=detail)

    # If any non-reinstall transaction is pending, one bootstrap run lets the
    # activation machine recover or classify it before data mutation starts.
    with state.lock(timeout_seconds=lock_timeout) as token:
        initial_pending = state.non_terminal_transactions(token)
        other_pending = [
            item for item in initial_pending if item.journal.operation != "reinstall"
        ]
        reinstall_pending = [
            item for item in initial_pending if item.journal.operation == "reinstall"
        ]
    if other_pending:
        _run_bootstrap(
            evidence,
            resolver,
            latest,
            reinstall_transaction_id=(
                reinstall_pending[0].journal.transaction_id
                if len(reinstall_pending) == 1
                and reinstall_pending[0].journal.phase == "removing_data"
                else None
            ),
        )

    with state.lock(timeout_seconds=lock_timeout) as token:
        pending = state.non_terminal_transactions(token)
        other_pending = [
            item for item in pending if item.journal.operation != "reinstall"
        ]
        if other_pending:
            return {
                "ok": False,
                "mode": "reinstall",
                "outcome": "partial",
                "version": latest,
                "transaction_id": None,
                "detail": (
                    "prior lifecycle transaction remains unresolved and was preserved; "
                    "task data was not mutated"
                ),
            }
        reinstall_journals = [
            item for item in pending if item.journal.operation == "reinstall"
        ]
        if len(reinstall_journals) > 1:
            for item in reinstall_journals:
                state.finish_transaction(
                    token,
                    item,
                    "partial",
                    observations=(
                        observation(
                            "transaction-recovery",
                            "unknown",
                            "multiple reinstall journals are ambiguous",
                        ),
                    ),
                    recovery=("Inspect every recorded reinstall transaction.",),
                )
            return {
                "ok": False,
                "mode": "reinstall",
                "outcome": "partial",
                "version": latest,
                "transaction_id": None,
                "detail": "multiple non-terminal reinstall transactions were classified partial",
            }
        if reinstall_journals:
            journal = reinstall_journals[0]
            transaction_id = journal.journal.transaction_id
        else:
            active = state.read_active(token)
            transaction_id = "reinstall-" + uuid.uuid4().hex
            backup_root, payload = _backup_paths(evidence, transaction_id)
            journal = state.create_transaction(
                token,
                state_module.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    owned_paths=(
                        str(evidence.data_root),
                        str(backup_root),
                        str(payload),
                    ),
                ),
            )
        journal, step = _ensure_data_removed(
            state, state_module, token, journal, evidence, resolver
        )
        if step == "partial":
            return {
                "ok": False,
                "mode": "reinstall",
                "outcome": "partial",
                "version": latest,
                "transaction_id": transaction_id,
                "detail": "Dev Flow-owned task data could not be removed exactly; it was preserved",
            }

    bootstrap = _run_bootstrap(
        evidence,
        resolver,
        latest,
        reinstall_transaction_id=transaction_id,
    )

    with state.lock(timeout_seconds=lock_timeout) as token:
        journal = state.read_transaction(token, transaction_id)
        if bootstrap["returncode"] == 0 and bootstrap["outcome"] == "committed":
            if not _bootstrap_active_matches(state, token, bootstrap):
                backup_root, _payload = _backup_paths(evidence, transaction_id)
                journal = state.advance_transaction(
                    token,
                    journal,
                    observations=(
                        observation(
                            "reinstall-install",
                            "concurrent",
                            "the committed bootstrap result no longer matches the active authority",
                        ),
                    ),
                    retained_paths=(str(backup_root), str(evidence.data_root)),
                    recovery=(
                        "Inspect the active authority and retained task-data backup before retrying.",
                    ),
                )
                terminal = state.finish_transaction(token, journal, "partial")
                retained = tuple(
                    path
                    for path in terminal.journal.retained_paths
                    if os.path.lexists(path)
                )
                return {
                    "ok": False,
                    "mode": "reinstall",
                    "outcome": "partial",
                    "version": latest,
                    "transaction_id": transaction_id,
                    "retained_paths": list(retained),
                    "detail": (
                        "reinstall bootstrap committed but its active identity could not be "
                        "proven; task-data backup was retained"
                    ),
                }
            journal, backup_clean = _remove_backup_after_commit(
                state, state_module, token, journal, evidence
            )
            terminal = state.finish_transaction(
                token,
                journal,
                "committed",
                observations=(
                    observation(
                        "reinstall-install",
                        "exact",
                        "the latest official release bootstrap committed",
                    ),
                ),
            )
            retained = tuple(path for path in terminal.journal.retained_paths if os.path.lexists(path))
            return {
                "ok": backup_clean and not retained,
                "mode": "reinstall",
                "outcome": "committed",
                "version": latest,
                "transaction_id": transaction_id,
                "retained_paths": list(retained),
                "detail": (
                    "reinstall completed"
                    if backup_clean and not retained
                    else "reinstall completed but the verified task-data backup was retained"
                ),
            }
        journal, restore = _restore_data(
            state, state_module, token, journal, evidence, resolver
        )
        terminal_outcome = restore if restore == "rolled_back" else "partial"
        terminal = state.finish_transaction(
            token,
            journal,
            terminal_outcome,
            observations=(
                observation(
                    "reinstall-install",
                    "changed",
                    "the latest official release bootstrap did not commit; task data was restored",
                ),
            ),
        )
        retained = tuple(path for path in terminal.journal.retained_paths if os.path.lexists(path))
        return {
            "ok": False,
            "mode": "reinstall",
            "outcome": terminal_outcome,
            "version": latest,
            "transaction_id": transaction_id,
            "retained_paths": list(retained),
            "detail": (
                "reinstall failed safely and the previous task data was restored"
                if terminal_outcome == "rolled_back"
                else "reinstall failed and task-data restoration is incomplete"
            ),
        }


def reinstall_command(
    evidence: InstallationEvidence,
    *,
    lock_timeout: float = 30.0,
) -> dict[str, object]:
    """Clear Dev Flow-owned task data and install the latest official release."""

    state_module, resolver = load_support_modules(evidence)
    # Phase B must acquire the installation lock itself, so the parent cannot
    # retain that lock while it invokes the child bootstrap.  This independent
    # operation guard stays locked across the whole parent command and prevents
    # two reinstall drivers from resuming the same durable journal at once.
    guard = state_module.LifecycleState(
        evidence.runtime_root / REINSTALL_GUARD_DIR,
        evidence.releases_root,
    )
    with guard.lock(timeout_seconds=lock_timeout):
        return _reinstall_command_guarded(
            evidence,
            state_module,
            resolver,
            lock_timeout=lock_timeout,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--support-root", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("update", "reinstall"))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if "DEV_FLOW_SOURCE_ROOT" in os.environ:
            raise ReleaseCommandError(
                "DEV_FLOW_SOURCE_ROOT is unsupported; run the installed dev-flow command"
            )
        evidence, _ = load_installation(
            Path(arguments.support_root),
            Path(arguments.runtime_root),
        )
        if arguments.mode == "update":
            result = update_command(evidence)
        else:
            result = reinstall_command(evidence)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, ReleaseCommandError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": arguments.mode,
                    "outcome": "partial",
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - bounded terminal classification
        # Lifecycle-state helpers are loaded at runtime; any unclassified
        # authority error must still be reported honestly and non-zero.
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": arguments.mode,
                    "outcome": "partial",
                    "error": str(exc)[:2048],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
