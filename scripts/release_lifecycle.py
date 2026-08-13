#!/usr/bin/env python3
"""Versioned Phase B installer for a Phase-A-verified release artifact.

The bootstrap executes this module only after the index, archive, manifest,
inventory, and static artifact topology have been verified.  This module is
standard-library-only; project and MCP imports are confined to the managed
runtime after its receipt has been constructed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import types
from typing import Any, Mapping, Optional, Sequence
import uuid


SCRIPT_ROOT = Path(__file__).resolve().parent
PLUGIN_ID = "dev-flow-orchestrator@personal"
PLUGIN_NAME = "dev-flow-orchestrator"
INSTALLATION_SCHEMA = "dev-flow-lifecycle-installation/2.0.0"
PREDECESSOR_INSTALLATION_SCHEMA = "dev-flow-lifecycle-installation/1.0.0"
REINSTALL_TRANSACTION_ENV = "DEV_FLOW_REINSTALL_TRANSACTION_ID"
_REINSTALL_TRANSACTION = re.compile(r"reinstall-[0-9a-f]{32}\Z")
# Frozen SHA-256 identities of the protocol-stable support shipped by the
# immediate predecessor release.
# Only this immediate predecessor may replace its evidence-bound files while
# introducing the second-generation installation evidence and installed
# release commands.
PREDECESSOR_SUPPORT_SHA256 = {
    "stable_dispatcher.py": "c04862bd88fc99cd1a09a2588d577d3e2e68971d74d9d44aab6178f8b1fe8a27",
    "lifecycle_state.py": "797db98b86c9376bb213dfe287e3d18efea03068fbae03cbc4490109d15e6a29",
    "uninstall_driver.py": "78e76a40d09e071fd083e1ef6ce2523f0937d981f17b798b6b8b0612fa9c7015",
}
MAX_INDEX_BYTES = 256 * 1024
MAX_MARKETPLACE_BYTES = 2 * 1024 * 1024
MAX_CODEX_BYTES = 1024 * 1024
MAX_PROOF_BYTES = 1024 * 1024
MAX_PATH_BYTES = 8192
_HEX = frozenset("0123456789abcdef")


class ReleaseLifecycleError(RuntimeError):
    """Phase B could not reach a classified, durable lifecycle result."""


def _load_sibling(name: str) -> Any:
    """Load a packaged lifecycle helper without relying on ``sys.path``.

    Production invokes this script with ``-I -S``.  ``lifecycle_machine`` has
    a normal ``scripts.lifecycle_state`` import for repository tests, so a
    narrow synthetic namespace is provided when the artifact is isolated.
    """

    package = sys.modules.get("scripts")
    if package is None:
        package = types.ModuleType("scripts")
        package.__path__ = [str(SCRIPT_ROOT)]  # type: ignore[attr-defined]
        sys.modules["scripts"] = package
    qualified = "scripts." + name
    existing = sys.modules.get(qualified)
    if existing is not None:
        return existing
    path = SCRIPT_ROOT / (name + ".py")
    specification = importlib.util.spec_from_file_location(qualified, path)
    if specification is None or specification.loader is None:
        raise ReleaseLifecycleError("versioned lifecycle helper is unavailable: " + name)
    module = importlib.util.module_from_spec(specification)
    sys.modules[qualified] = module
    setattr(package, name, module)
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(qualified, None)
        try:
            delattr(package, name)
        except AttributeError:
            pass
        raise
    return module


lifecycle_state = _load_sibling("lifecycle_state")
lifecycle_machine = _load_sibling("lifecycle_machine")
runtime_integrity = _load_sibling("runtime_integrity")
manage_runtime = _load_sibling("manage_runtime")
release_artifact = _load_sibling("release_artifact")
release_resolver = _load_sibling("release_resolver")
render_dispatchers = _load_sibling("render_dispatchers")
legacy_migration = _load_sibling("legacy_migration")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseLifecycleError("JSON contains a duplicate object member")
        value[key] = item
    return value


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
        raise ReleaseLifecycleError("lifecycle evidence is not JSON-safe") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path, label: str, maximum: int | None = None) -> str:
    metadata = _regular_file(path, label)
    if maximum is not None and metadata.st_size > maximum:
        raise ReleaseLifecycleError(label + " exceeds its fixed byte cap")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseLifecycleError(label + " cannot be hashed") from exc
    return digest.hexdigest()


def _digest(value: str, label: str) -> str:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise ReleaseLifecycleError(label + " must be a lowercase SHA-256 digest")
    return value


def _is_reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _components(path: Path) -> list[Path]:
    parts = path.parts
    current = Path(parts[0])
    result = [current]
    for part in parts[1:]:
        current = current / part
        result.append(current)
    return result


def _check_existing_ancestors(path: Path, label: str, leaf: str | None = None) -> None:
    components = _components(path)
    for index, component in enumerate(components):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ReleaseLifecycleError("cannot inspect {} ancestor".format(label)) from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise ReleaseLifecycleError(label + " crosses a link or reparse point")
        is_leaf = index == len(components) - 1
        if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
            raise ReleaseLifecycleError(label + " crosses a non-directory ancestor")
        if is_leaf and leaf == "file" and not stat.S_ISREG(metadata.st_mode):
            raise ReleaseLifecycleError(label + " is not a regular file")
        if is_leaf and leaf == "directory" and not stat.S_ISDIR(metadata.st_mode):
            raise ReleaseLifecycleError(label + " is not a regular directory")


def _native_absolute(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ReleaseLifecycleError(label + " is invalid")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES or not os.path.isabs(raw):
        raise ReleaseLifecycleError(label + " must be a bounded absolute native path")
    path = Path(os.path.abspath(raw))
    _check_existing_ancestors(path, label)
    return path


def _regular_file(path: Path, label: str) -> os.stat_result:
    _check_existing_ancestors(path, label, "file")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseLifecycleError(label + " is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or _is_reparse(metadata)
    ):
        raise ReleaseLifecycleError(label + " is not a safe regular file")
    return metadata


def _regular_directory(path: Path, label: str) -> os.stat_result:
    _check_existing_ancestors(path, label, "directory")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseLifecycleError(label + " is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse(metadata):
        raise ReleaseLifecycleError(label + " is not a safe directory")
    return metadata


def _ensure_directory(path: Path, mode: int = 0o700) -> None:
    if path.exists():
        _regular_directory(path, str(path))
        return
    parent = path.parent
    if parent != path:
        _ensure_directory(parent, mode)
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        pass
    _regular_directory(path, str(path))


def _atomic_write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    _ensure_directory(path.parent)
    if os.path.lexists(path):
        _regular_file(path, str(path))
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory = None
        if directory is not None:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path, maximum: int, label: str) -> tuple[dict[str, object], bytes]:
    metadata = _regular_file(path, label)
    if metadata.st_size > maximum:
        raise ReleaseLifecycleError(label + " exceeds its fixed byte cap")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseLifecycleError(label + " is not strict UTF-8 JSON") from exc
    if len(raw) > maximum or not isinstance(value, dict):
        raise ReleaseLifecycleError(label + " is invalid")
    return value, raw


def _run(
    arguments: Sequence[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 30,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    selected_environment = os.environ.copy()
    selected_environment.pop(REINSTALL_TRANSACTION_ENV, None)
    selected_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if environment:
        selected_environment.update(environment)
    try:
        completed = subprocess.run(
            list(arguments),
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            env=selected_environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseLifecycleError("command could not run: " + Path(arguments[0]).name) from exc
    if len(completed.stdout) > MAX_PROOF_BYTES or len(completed.stderr) > MAX_PROOF_BYTES:
        raise ReleaseLifecycleError("command output exceeds its fixed byte cap")
    return completed


@dataclass(frozen=True)
class InstallPaths:
    artifact_root: Path
    release_index: Path
    runtime_root: Path
    bin_dir: Path
    marketplace_file: Path
    codex_home: Path
    data_root: Path
    runtime_root_preexisting: bool


@dataclass(frozen=True)
class IndexIdentity:
    version: str
    index_sha256: str
    archive_sha256: str
    manifest_sha256: str
    model: Mapping[str, object] | None = None


def load_index_identity(path: Path, expected_sha256: str) -> IndexIdentity:
    expected_sha256 = _digest(expected_sha256, "release index digest")
    _regular_file(path, "Phase A release index")
    if _sha256_file(path, "Phase A release index", MAX_INDEX_BYTES) != expected_sha256:
        raise ReleaseLifecycleError("release index digest differs from Phase A evidence")
    value, raw = _read_json(path, MAX_INDEX_BYTES, "Phase A release index")
    if _sha256(raw) != expected_sha256:
        raise ReleaseLifecycleError("release index changed while it was read")
    try:
        index = release_artifact.validate_release_index(value)
    except Exception as exc:
        raise ReleaseLifecycleError(str(exc)) from exc
    if index["repository"] != release_artifact.CANONICAL_REPOSITORY:
        raise ReleaseLifecycleError("release index repository is not canonical")
    archive = index["archive"]
    assert isinstance(archive, Mapping)
    return IndexIdentity(
        str(index["version"]),
        expected_sha256,
        str(archive["sha256"]),
        str(index["manifest_sha256"]),
        index,
    )


def _default_runtime_root() -> Path:
    selected = os.environ.get("DEV_FLOW_RUNTIME_HOME")
    if selected:
        return _native_absolute(selected, "managed runtime root")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
    return _native_absolute(root / "dev-flow-orchestrator" / "runtime", "managed runtime root")


def _select_bin_dir(explicit: str | None) -> Path:
    candidates = [explicit] if explicit else os.environ.get("PATH", "").split(os.pathsep)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = _native_absolute(candidate, "dispatcher directory")
            _regular_directory(path, "dispatcher directory")
        except ReleaseLifecycleError:
            continue
        if os.access(path, os.W_OK | os.X_OK):
            return path
    raise ReleaseLifecycleError(
        "PATH has no writable absolute directory; pass --bin-dir or set DEV_FLOW_BIN_DIR"
    )


def resolve_install_paths(arguments: argparse.Namespace) -> InstallPaths:
    artifact_root = _native_absolute(SCRIPT_ROOT.parent, "verified artifact root")
    _regular_directory(artifact_root, "verified artifact root")
    release_index = _native_absolute(arguments.release_index, "Phase A release index")
    _regular_file(release_index, "Phase A release index")
    codex_home = _native_absolute(
        arguments.codex_home or os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        "Codex home",
    )
    runtime_root = (
        _native_absolute(arguments.runtime_root, "managed runtime root")
        if arguments.runtime_root
        else _default_runtime_root()
    )
    runtime_preexisting = os.path.lexists(runtime_root)
    marketplace_file = _native_absolute(
        arguments.marketplace_file
        or os.environ.get(
            "DEV_FLOW_MARKETPLACE_FILE",
            str(Path.home() / ".agents" / "plugins" / "marketplace.json"),
        ),
        "personal marketplace file",
    )
    if (
        marketplace_file.name != "marketplace.json"
        or marketplace_file.parent.name != "plugins"
        or marketplace_file.parent.parent.name != ".agents"
    ):
        raise ReleaseLifecycleError(
            "personal marketplace file must be <marketplace-root>/.agents/plugins/marketplace.json"
        )
    data_root = _native_absolute(
        arguments.data_root
        or os.environ.get(
            "DEV_FLOW_DATA_DIR",
            str(codex_home / "plugins" / "data" / "dev-flow-orchestrator-personal"),
        ),
        "Controller task-data root",
    )
    try:
        if os.path.commonpath((str(runtime_root), str(data_root))) in {
            str(runtime_root),
            str(data_root),
        }:
            raise ReleaseLifecycleError(
                "managed runtime and Controller task-data roots must be disjoint"
            )
    except ValueError:
        pass
    bin_dir = _select_bin_dir(arguments.bin_dir or os.environ.get("DEV_FLOW_BIN_DIR"))
    return InstallPaths(
        artifact_root,
        release_index,
        runtime_root,
        bin_dir,
        marketplace_file,
        codex_home,
        data_root,
        runtime_preexisting,
    )


class InfrastructureManager:
    """Install protocol-stable support with exact per-transaction rollback."""

    def __init__(self, paths: InstallPaths) -> None:
        self.paths = paths
        self.lifecycle_root = paths.runtime_root / "lifecycle"
        self.backups_root = paths.runtime_root / "infrastructure-backups"
        self._changed: dict[str, Path] = {}

    @property
    def dispatcher_names(self) -> tuple[str, ...]:
        suffix = ".cmd" if os.name == "nt" else ""
        return tuple(name + suffix for name in ("dev-flow", "dev-flow-mcp", "dev-flow-uninstall"))

    def _sources(self) -> dict[Path, bytes]:
        source_root = self.paths.artifact_root / "lifecycle"
        mapping: dict[Path, bytes] = {}
        for name in (
            "stable_dispatcher.py",
            "lifecycle_state.py",
            "uninstall_driver.py",
            "release_commands.py",
            "release_resolver.py",
        ):
            source = source_root / name
            _regular_file(source, "artifact lifecycle support " + name)
            mapping[self.lifecycle_root / name] = source.read_bytes()
        rendered = render_dispatchers.render_dispatchers(
            self.paths.runtime_root, windows=os.name == "nt"
        )
        for name, raw in rendered.items():
            mapping[self.paths.bin_dir / name] = raw
        evidence = {
            "schema": INSTALLATION_SCHEMA,
            "dispatcher_protocol": lifecycle_state.DISPATCHER_PROTOCOL,
            "uninstall_driver_sha256": _sha256(mapping[self.lifecycle_root / "uninstall_driver.py"]),
            "stable_dispatcher_sha256": _sha256(mapping[self.lifecycle_root / "stable_dispatcher.py"]),
            "lifecycle_state_sha256": _sha256(mapping[self.lifecycle_root / "lifecycle_state.py"]),
            "release_commands_sha256": _sha256(mapping[self.lifecycle_root / "release_commands.py"]),
            "release_resolver_sha256": _sha256(mapping[self.lifecycle_root / "release_resolver.py"]),
            "dispatchers": {
                name: _sha256(mapping[self.paths.bin_dir / name])
                for name in self.dispatcher_names
            },
            "bin_dir": str(self.paths.bin_dir),
            "marketplace_file": str(self.paths.marketplace_file),
            "codex_home": str(self.paths.codex_home),
            "plugin_id": PLUGIN_ID,
            "runtime_root": str(self.paths.runtime_root),
            "data_root": str(self.paths.data_root),
            "data_owned_paths": [
                release_resolver.DATA_NAMESPACE,
                release_resolver.WEB_RUNTIME_DIR,
            ],
            "data_marker_name": release_resolver.DATA_MARKER_NAME,
        }
        mapping[self.lifecycle_root / "installation.json"] = _canonical_bytes(evidence)
        return mapping

    def _desired_mode(self, path: Path) -> int:
        return (
            0o755
            if path.parent == self.paths.bin_dir and os.name != "nt"
            else 0o600
        )

    def _installation_identity_is_proven(self, desired: Mapping[Path, bytes]) -> bool:
        """Return whether closed evidence proves ownership of this exact layout.

        The evidence is allowed to have formatting or mode drift because those
        are repairable installed-content properties.  Its strict JSON value,
        including every absolute installation identity and stable digest, must
        still match the Phase-A-verified artifact's expected closed value.
        """

        path = self.lifecycle_root / "installation.json"
        if not os.path.lexists(path):
            return False
        try:
            current, _ = _read_json(path, 128 * 1024, "lifecycle installation evidence")
            expected = json.loads(
                desired[path].decode("utf-8"), object_pairs_hook=_strict_object
            )
        except (ReleaseLifecycleError, UnicodeError, json.JSONDecodeError, KeyError):
            return False
        return isinstance(expected, dict) and current == expected

    def _predecessor_owned_paths(
        self, desired: Mapping[Path, bytes]
    ) -> frozenset[Path]:
        """Prove the exact immediate predecessor before its one-time migration."""

        evidence_path = self.lifecycle_root / "installation.json"
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
        try:
            evidence, _raw = _read_json(
                evidence_path, 128 * 1024, "predecessor installation evidence"
            )
            if (
                set(evidence) != fields
                or evidence.get("schema") != PREDECESSOR_INSTALLATION_SCHEMA
                or evidence.get("dispatcher_protocol")
                != lifecycle_state.DISPATCHER_PROTOCOL
                or evidence.get("plugin_id") != PLUGIN_ID
            ):
                return frozenset()
            expected_paths = {
                "bin_dir": self.paths.bin_dir,
                "marketplace_file": self.paths.marketplace_file,
                "codex_home": self.paths.codex_home,
            }
            for field, expected_path in expected_paths.items():
                recorded = evidence.get(field)
                if (
                    not isinstance(recorded, str)
                    or not os.path.isabs(recorded)
                    or os.path.normcase(os.path.abspath(recorded))
                    != os.path.normcase(str(expected_path))
                ):
                    return frozenset()
            support_paths: set[Path] = set()
            for name, expected_digest in PREDECESSOR_SUPPORT_SHA256.items():
                field = name.removesuffix(".py") + "_sha256"
                if evidence.get(field) != expected_digest:
                    return frozenset()
                path = self.lifecycle_root / name
                metadata = _regular_file(path, "predecessor lifecycle support")
                if _sha256_file(path, "predecessor lifecycle support") != expected_digest:
                    return frozenset()
                if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o600:
                    return frozenset()
                support_paths.add(path)
            dispatchers = evidence.get("dispatchers")
            if not isinstance(dispatchers, dict) or set(dispatchers) != set(
                self.dispatcher_names
            ):
                return frozenset()
            dispatcher_paths: set[Path] = set()
            for name in self.dispatcher_names:
                path = self.paths.bin_dir / name
                expected = desired[path]
                if dispatchers.get(name) != _sha256(expected):
                    return frozenset()
                metadata = _regular_file(path, "predecessor stable dispatcher")
                if path.read_bytes() != expected:
                    return frozenset()
                if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != 0o755:
                    return frozenset()
                dispatcher_paths.add(path)
            evidence_metadata = _regular_file(
                evidence_path, "predecessor installation evidence"
            )
            if os.name != "nt" and stat.S_IMODE(evidence_metadata.st_mode) != 0o600:
                return frozenset()
            return frozenset(
                support_paths | dispatcher_paths | {evidence_path}
            )
        except (KeyError, OSError, ReleaseLifecycleError, TypeError, ValueError):
            return frozenset()

    def attest(self) -> tuple[bool, str, str]:
        """Attest closed evidence plus every stable file's bytes and mode."""

        try:
            desired = self._sources()
            if not self._installation_identity_is_proven(desired):
                return (
                    False,
                    "unknown",
                    "closed lifecycle installation identity is absent or changed",
                )
            for path, expected in desired.items():
                if not os.path.lexists(path):
                    return False, "changed", "stable infrastructure member is absent: " + str(path)
                metadata = _regular_file(path, "installed lifecycle infrastructure")
                if path.read_bytes() != expected:
                    return False, "changed", "stable infrastructure bytes differ: " + str(path)
                if os.name != "nt" and stat.S_IMODE(metadata.st_mode) != self._desired_mode(path):
                    return False, "changed", "stable infrastructure mode differs: " + str(path)
        except (OSError, ReleaseLifecycleError) as exc:
            return False, "unknown", str(exc)
        return True, "exact", "closed installation evidence and stable infrastructure are exact"

    @staticmethod
    def _backup_name(index: int) -> str:
        return "before-{:03d}.bin".format(index)

    def ensure(self, transaction_id: str, operation: str) -> tuple[str, ...]:
        desired = self._sources()
        suffix = ".cmd" if os.name == "nt" else ""
        proven_predecessor_dispatchers = {
            self.paths.bin_dir / ("dev-flow" + suffix),
            self.paths.bin_dir / ("dev-flow-mcp" + suffix),
        }
        changes: list[tuple[Path, bytes | None, int | None, bytes, int]] = []
        for path, after in desired.items():
            after_mode = self._desired_mode(path)
            if os.path.lexists(path):
                metadata = _regular_file(path, "installed lifecycle infrastructure")
                before = path.read_bytes()
                before_mode = stat.S_IMODE(metadata.st_mode)
                mode_exact = os.name == "nt" or before_mode == after_mode
                if before == after and mode_exact:
                    continue
                changes.append((path, before, before_mode, after, after_mode))
            else:
                changes.append((path, None, None, after, after_mode))
        if not changes:
            return ()
        repair_proven = operation == "repair" and self._installation_identity_is_proven(
            desired
        )
        predecessor_owned = (
            self._predecessor_owned_paths(desired)
            if operation == "upgrade"
            else frozenset()
        )
        for path, before, _, _, _ in changes:
            existing_change_is_allowed = (
                before is None
                or repair_proven
                or path in predecessor_owned
                or (
                    operation == "migration"
                    and path in proven_predecessor_dispatchers
                )
            )
            if not existing_change_is_allowed:
                raise ReleaseLifecycleError(
                    "installed lifecycle infrastructure is not the proven predecessor and is not proven product-owned; preserve it and inspect manually"
                )
        if operation == "repair" and not repair_proven:
            raise ReleaseLifecycleError(
                "closed lifecycle installation identity is not proven; preserve stable paths and inspect manually"
            )
        backup = self.backups_root / transaction_id
        if os.path.lexists(backup):
            raise ReleaseLifecycleError("transaction infrastructure backup already exists")
        _ensure_directory(backup)
        entries: list[dict[str, object]] = []
        for index, (path, before, before_mode, after, after_mode) in enumerate(changes):
            before_name: str | None = None
            if before is not None:
                before_name = self._backup_name(index)
                saved = backup / before_name
                with saved.open("xb") as stream:
                    stream.write(before)
                    stream.flush()
                    os.fsync(stream.fileno())
                saved.chmod(0o600)
            entries.append(
                {
                    "path": str(path),
                    "before": None if before is None else _sha256(before),
                    "before_file": before_name,
                    "after": _sha256(after),
                    "before_mode": before_mode,
                    "after_mode": after_mode,
                }
            )
        manifest = {"schema": "dev-flow-infrastructure-backup/1.0.0", "entries": entries}
        _atomic_write(backup / "manifest.json", _canonical_bytes(manifest))
        try:
            for path, _, _, after, after_mode in changes:
                _atomic_write(path, after, after_mode)
        except BaseException:
            self._changed[transaction_id] = backup
            self.rollback(transaction_id)
            raise
        self._changed[transaction_id] = backup
        return (str(backup),)

    def _backup(self, transaction_id: str) -> tuple[Path, list[Mapping[str, object]]] | None:
        backup = self._changed.get(transaction_id, self.backups_root / transaction_id)
        if not os.path.lexists(backup):
            return None
        value, _ = _read_json(backup / "manifest.json", 128 * 1024, "infrastructure backup")
        if set(value) != {"schema", "entries"} or value["schema"] != "dev-flow-infrastructure-backup/1.0.0":
            raise ReleaseLifecycleError("infrastructure backup schema is invalid")
        entries = value["entries"]
        if not isinstance(entries, list) or len(entries) > 16:
            raise ReleaseLifecycleError("infrastructure backup entries are invalid")
        if not all(isinstance(item, Mapping) for item in entries):
            raise ReleaseLifecycleError("infrastructure backup entry is invalid")
        return backup, entries  # type: ignore[return-value]

    def rollback(self, transaction_id: str) -> tuple[str, ...]:
        selected = self._backup(transaction_id)
        if selected is None:
            return ()
        backup, entries = selected
        retained: list[str] = []
        for item in reversed(entries):
            path_value = item.get("path")
            after = item.get("after")
            before = item.get("before")
            before_file = item.get("before_file")
            if not isinstance(path_value, str) or not isinstance(after, str):
                retained.append(str(backup))
                break
            path = _native_absolute(path_value, "backed-up infrastructure path")
            if not os.path.lexists(path):
                if before is not None:
                    retained.append(str(path))
                continue
            try:
                current = _sha256_file(path, "installed lifecycle infrastructure")
            except ReleaseLifecycleError:
                retained.append(str(path))
                continue
            if current != after:
                retained.append(str(path))
                continue
            if before is None:
                try:
                    path.unlink()
                except OSError:
                    retained.append(str(path))
            else:
                saved = backup / str(before_file)
                try:
                    raw = saved.read_bytes()
                    if _sha256(raw) != before:
                        raise ReleaseLifecycleError("infrastructure backup digest differs")
                    before_mode = item.get("before_mode")
                    if (
                        isinstance(before_mode, bool)
                        or not isinstance(before_mode, int)
                        or not 0 <= before_mode <= 0o777
                    ):
                        raise ReleaseLifecycleError(
                            "infrastructure backup mode is invalid"
                        )
                    _atomic_write(path, raw, before_mode)
                except (OSError, ReleaseLifecycleError, ValueError):
                    retained.append(str(path))
        if not retained:
            self._remove_backup(backup)
            try:
                self.lifecycle_root.rmdir()
            except OSError:
                pass
        return tuple(retained)

    def commit(self, transaction_id: str) -> tuple[str, ...]:
        selected = self._backup(transaction_id)
        if selected is None:
            return ()
        backup, _ = selected
        try:
            self._remove_backup(backup)
            return ()
        except OSError:
            return (str(backup),)

    @staticmethod
    def _remove_backup(backup: Path) -> None:
        for path in sorted(backup.iterdir(), key=lambda item: item.name):
            _regular_file(path, "infrastructure backup member")
            path.unlink()
        backup.rmdir()
        try:
            backup.parent.rmdir()
        except OSError:
            pass


def _runtime_python(release_path: Path) -> Path:
    return release_path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class DataOwnership:
    """Write and roll back the small data-root ownership marker.

    The marker proves which top-level entries under the recorded task-data
    root are Dev Flow-owned and is the exact identity ``dev-flow reinstall``
    verifies before any cleanup.  Install never rewrites pre-existing marker
    content; drift stops installation before product mutation.
    """

    MAX_MARKER_BYTES = 16 * 1024

    def __init__(self, paths: InstallPaths) -> None:
        self.paths = paths

    def _model(self) -> dict[str, object]:
        return {
            "schema": release_resolver.DATA_OWNERSHIP_SCHEMA,
            "product": release_resolver.PRODUCT_NAME,
            "data_root": str(self.paths.data_root),
            "namespace": release_resolver.DATA_NAMESPACE,
            "web_runtime": release_resolver.WEB_RUNTIME_DIR,
        }

    def _marker_path(self) -> Path:
        return self.paths.data_root / release_resolver.DATA_MARKER_NAME

    def ensure(self) -> tuple[bool, bool]:
        """Return (created_root, created_marker) for exact transaction rollback."""

        data_root = self.paths.data_root
        root_existed = os.path.lexists(data_root)
        marker_path = self._marker_path()
        marker_existed = os.path.lexists(marker_path)
        expected = self._model()
        if marker_existed:
            value, _ = _read_json(
                marker_path, self.MAX_MARKER_BYTES, "data ownership marker"
            )
            if value != expected:
                raise ReleaseLifecycleError(
                    "data ownership marker drift must be preserved and inspected"
                )
            return False, False
        if not root_existed:
            _ensure_directory(data_root)
        else:
            _regular_directory(data_root, "Controller task-data root")
        _atomic_write(marker_path, _canonical_bytes(expected))
        return not root_existed, True

    def rollback(self, created_root: bool, created_marker: bool) -> tuple[str, ...]:
        if not created_marker:
            return ()
        retained: list[str] = []
        marker_path = self._marker_path()
        try:
            if os.path.lexists(marker_path):
                value, _ = _read_json(
                    marker_path, self.MAX_MARKER_BYTES, "data ownership marker"
                )
                if value == self._model():
                    marker_path.unlink()
        except (OSError, ReleaseLifecycleError):
            retained.append(str(marker_path))
        if created_root and not retained:
            try:
                self.paths.data_root.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                retained.append(str(self.paths.data_root))
        return tuple(retained)


class ArtifactCandidates:
    def __init__(self, paths: InstallPaths, index: IndexIdentity, infrastructure: InfrastructureManager) -> None:
        self.paths = paths
        self.index = index
        self.infrastructure = infrastructure
        self.data_ownership = DataOwnership(paths)
        self._built: dict[str, Mapping[str, object]] = {}
        self._marker_created: set[str] = set()
        self._data_created: dict[str, tuple[bool, bool]] = {}

    @property
    def envelope(self) -> Any:
        return lifecycle_machine.ArtifactEnvelope(
            self.index.index_sha256,
            self.index.archive_sha256,
            self.index.manifest_sha256,
        )

    def _ensure_runtime_marker(self) -> bool:
        marker = self.paths.runtime_root / manage_runtime.ROOT_MARKER
        if os.path.lexists(marker):
            _regular_file(marker, "managed runtime marker")
            if marker.read_bytes() != b"dev-flow-managed-runtime/1\n":
                raise ReleaseLifecycleError("managed runtime marker is incompatible")
            return False
        allowed = {"lifecycle.lock", "transactions"}
        unexpected = [item.name for item in self.paths.runtime_root.iterdir() if item.name not in allowed]
        if unexpected:
            raise ReleaseLifecycleError("fresh runtime root contains unowned content")
        with marker.open("xb") as stream:
            stream.write(b"dev-flow-managed-runtime/1\n")
            stream.flush()
            os.fsync(stream.fileno())
        marker.chmod(0o600)
        return True

    def _receipt_identity(self, active: Any) -> tuple[dict[str, object] | None, str | None]:
        try:
            release = _native_absolute(active.release_path, "active release path")
            receipt_path = release / runtime_integrity.RUNTIME_RECEIPT_NAME
            receipt, raw = _read_json(
                receipt_path, runtime_integrity.MAX_RECEIPT_BYTES, "active runtime receipt"
            )
            if _sha256(raw) != active.receipt_sha256:
                return None, "active receipt digest differs from active authority"
            receipt = runtime_integrity.validate_artifact_runtime_receipt(receipt)
            if receipt["release_id"] != active.release_id or receipt["runtime_path"] != str(release):
                return None, "active receipt identity differs from active authority"
            return receipt, None
        except Exception as exc:
            return None, str(exc)

    def active_version(self, active: Any) -> str | None:
        receipt, _ = self._receipt_identity(active)
        return None if receipt is None else str(receipt["version"])

    def _full_attestation(self, active: Any) -> bool:
        try:
            release = Path(active.release_path)
            verifier = release / "integrity" / "runtime_integrity.py"
            command = [
                str(_runtime_python(release)),
                "-B",
                "-I",
                str(verifier),
                "verify-artifact-runtime",
                "--runtime-dir",
                str(release),
                "--release-id",
                active.release_id,
                "--transaction-id",
                active.transaction_id,
            ]
            completed = _run(command)
        except ReleaseLifecycleError:
            return False
        try:
            result = json.loads(completed.stdout.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError):
            return False
        return isinstance(result, dict) and result.get("ok") is True

    def attest_active(self, active: Any) -> Any:
        receipt, error = self._receipt_identity(active)
        if receipt is None:
            return lifecycle_machine.ActiveAttestation(
                False,
                False,
                None,
                None,
                (
                    lifecycle_state.ExternalObservation(
                        "active-receipt", "unknown", detail=error
                    ),
                ),
            )
        envelope = lifecycle_machine.ArtifactEnvelope(
            str(receipt["release_index_sha256"]),
            str(receipt["archive_sha256"]),
            str(receipt["artifact_manifest_sha256"]),
        )
        runtime_reusable = self._full_attestation(active)
        infrastructure_exact, infrastructure_state, infrastructure_detail = (
            self.infrastructure.attest()
        )
        reusable = runtime_reusable and infrastructure_exact
        return lifecycle_machine.ActiveAttestation(
            True,
            reusable,
            str(receipt["version"]),
            envelope,
            (
                lifecycle_state.ExternalObservation(
                    "active-runtime", "exact" if runtime_reusable else "changed",
                    active.receipt_sha256,
                    "complete receipt and managed-release attestation"
                    if runtime_reusable
                    else "managed-release attestation detected drift",
                ),
                lifecycle_state.ExternalObservation(
                    "stable-infrastructure",
                    infrastructure_state,
                    detail=infrastructure_detail,
                ),
            ),
        )

    def build_candidate(self, request: Any) -> Any:
        marker_created = self._ensure_runtime_marker()
        if marker_created:
            self._marker_created.add(request.transaction_id)
        try:
            result = manage_runtime.build_artifact_candidate(
                self.paths.artifact_root,
                self.paths.runtime_root,
                self.paths.release_index,
                self.index.index_sha256,
                request.transaction_id,
                self.paths.data_root,
                expected_release_id=request.release_id,
            )
            owned = self.infrastructure.ensure(request.transaction_id, request.operation)
            self._data_created[request.transaction_id] = self.data_ownership.ensure()
        except BaseException:
            retained = self.infrastructure.rollback(request.transaction_id)
            data_created = self._data_created.pop(request.transaction_id, (False, False))
            retained += self.data_ownership.rollback(*data_created)
            release_path = Path(request.release_path)
            if os.path.lexists(release_path):
                try:
                    removal = runtime_integrity.remove_owned_release(release_path)
                    if removal.get("retained_paths"):
                        retained += tuple(removal["retained_paths"])
                except Exception:
                    retained += (str(release_path),)
            releases = self.paths.runtime_root / "releases"
            if marker_created and not retained:
                try:
                    releases.rmdir()
                except FileNotFoundError:
                    pass
                except OSError:
                    retained += (str(releases),)
            if marker_created and not retained:
                marker = self.paths.runtime_root / manage_runtime.ROOT_MARKER
                try:
                    if marker.read_bytes() == b"dev-flow-managed-runtime/1\n":
                        marker.unlink()
                except OSError:
                    retained += (str(marker),)
            if not retained:
                self._marker_created.discard(request.transaction_id)
            if retained:
                raise lifecycle_machine.AdapterFailure(
                    "candidate construction failed and exact cleanup was incomplete",
                    retained_paths=retained,
                    recovery=("Inspect retained transaction-owned paths before retrying.",),
                    uncertain=True,
                )
            raise
        self._built[request.release_id] = result
        return lifecycle_machine.Candidate(
            str(result["version"]),
            str(result["release_id"]),
            str(result["runtime_dir"]),
            str(result["receipt_sha256"]),
            request.envelope,
            (str(result["runtime_dir"]), *owned),
        )

    def staged_health(self, candidate: Any) -> Any:
        built = self._built.get(candidate.release_id)
        exact = bool(
            built is not None
            and built.get("staged_health") is True
            and built.get("receipt_sha256") == candidate.receipt_sha256
        )
        return lifecycle_machine.StepEvidence(
            exact,
            (
                lifecycle_state.ExternalObservation(
                    "candidate-staged-health",
                    "exact" if exact else "changed",
                    candidate.receipt_sha256 if exact else None,
                ),
            ),
            recovery=() if exact else ("Rebuild the candidate from the verified artifact.",),
        )

    def cleanup_owned(self, journal: Any) -> Any:
        retained = list(self.infrastructure.rollback(journal.transaction_id))
        data_created = self._data_created.pop(
            journal.transaction_id, (False, False)
        )
        retained.extend(self.data_ownership.rollback(*data_created))
        target = journal.target_release
        if target is not None and os.path.lexists(target.release_path):
            try:
                result = runtime_integrity.remove_owned_release(Path(target.release_path))
                retained.extend(str(item) for item in result.get("retained_paths", ()))
            except Exception:
                retained.append(target.release_path)
        fresh_marker = (
            journal.transaction_id in self._marker_created
            or (journal.operation == "install" and journal.previous_authority is None)
        )
        if fresh_marker and not retained:
            releases = self.paths.runtime_root / "releases"
            try:
                releases.rmdir()
            except FileNotFoundError:
                pass
            except OSError:
                retained.append(str(releases))
        if fresh_marker and not retained:
            marker = self.paths.runtime_root / manage_runtime.ROOT_MARKER
            try:
                if marker.read_bytes() != b"dev-flow-managed-runtime/1\n":
                    retained.append(str(marker))
                else:
                    marker.unlink()
            except OSError:
                retained.append(str(marker))
        if not retained:
            self._marker_created.discard(journal.transaction_id)
        retained = sorted(set(retained))
        return lifecycle_machine.StepEvidence(
            not retained,
            (
                lifecycle_state.ExternalObservation(
                    "candidate-cleanup", "exact" if not retained else "unknown"
                ),
            ),
            retained_paths=tuple(retained),
            recovery=("Inspect retained candidate paths before removing them.",) if retained else (),
        )

    def cleanup_inactive(self, previous: Any | None, active: Any) -> Any:
        """Remove only a proven inactive v3 release after public startup proof.

        Cleanup is deliberately non-authoritative: an unknown or changed
        inactive path is retained and reported while the proven target may
        still commit.  The infrastructure backup belongs to the committing
        transaction and is removed at the same terminal boundary.
        """

        infrastructure_retained = list(self.infrastructure.commit(active.transaction_id))
        retained = list(infrastructure_retained)
        observations: list[Any] = []
        if previous is not None and Path(previous.release_path) != Path(active.release_path):
            previous_path = Path(previous.release_path)
            if not os.path.lexists(previous_path):
                observations.append(
                    lifecycle_state.ExternalObservation(
                        "inactive-previous-release",
                        "absent",
                        previous.receipt_sha256,
                        "already absent during interrupted cleanup recovery",
                    )
                )
            else:
                try:
                    receipt, raw = _read_json(
                        previous_path / runtime_integrity.RUNTIME_RECEIPT_NAME,
                        runtime_integrity.MAX_RECEIPT_BYTES,
                        "inactive runtime receipt",
                    )
                    validated = runtime_integrity.validate_artifact_runtime_receipt(receipt)
                    if (
                        _sha256(raw) != previous.receipt_sha256
                        or validated["release_id"] != previous.release_id
                        or validated["runtime_path"] != previous.release_path
                        or validated["transaction_id"] != previous.transaction_id
                    ):
                        raise ReleaseLifecycleError(
                            "inactive runtime receipt differs from previous active authority"
                        )
                    result = runtime_integrity.remove_owned_release(previous_path)
                    release_retained = [
                        str(item) for item in result.get("retained_paths", ())
                    ]
                    retained.extend(release_retained)
                    observations.append(
                        lifecycle_state.ExternalObservation(
                            "inactive-previous-release",
                            "exact" if not release_retained else "changed",
                            previous.receipt_sha256,
                            "removed by exact ownership comparison"
                            if not result.get("retained_paths")
                            else "unknown or changed content was retained",
                        )
                    )
                except Exception as exc:
                    retained.append(previous.release_path)
                    observations.append(
                        lifecycle_state.ExternalObservation(
                            "inactive-previous-release", "unknown", detail=str(exc)
                        )
                    )
        if infrastructure_retained:
            observations.append(
                lifecycle_state.ExternalObservation(
                    "infrastructure-backup-cleanup",
                    "changed",
                    detail="transaction infrastructure backup was retained",
                )
            )
        retained = sorted(set(retained))
        if not observations:
            observations.append(
                lifecycle_state.ExternalObservation(
                    "inactive-release-cleanup", "exact",
                    detail="no previous artifact release required removal",
                )
            )
        return lifecycle_machine.StepEvidence(
            not retained,
            tuple(observations),
            retained_paths=tuple(retained),
            recovery=(
                "Retained inactive paths are non-authoritative; remove them only after exact ownership verification.",
            )
            if retained
            else (),
        )


def _normalized_plugin(item: object) -> dict[str, object] | None:
    if not isinstance(item, Mapping) or item.get("installed") is not True:
        return None
    version = item.get("version")
    enabled = item.get("enabled")
    if not isinstance(version, str) or not version or not isinstance(enabled, bool):
        raise ReleaseLifecycleError("Codex plugin observation is incomplete")
    return {"plugin_id": PLUGIN_ID, "installed": True, "enabled": enabled, "version": version}


class ArtifactHost:
    def __init__(
        self,
        paths: InstallPaths,
        index: IndexIdentity,
        infrastructure: InfrastructureManager | None = None,
    ) -> None:
        self.paths = paths
        self.index = index
        self.infrastructure = infrastructure
        self.migration: Optional[Mapping[str, object]] = None
        self._previous: Optional[dict[str, object]] = None
        self._restored_legacy_version: str | None = None

    def _run_codex(
        self,
        arguments: Sequence[str],
        *,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run Codex against the installation-bound home, never the parent one."""

        return _run(
            arguments,
            timeout=timeout,
            environment={"CODEX_HOME": str(self.paths.codex_home)},
        )

    def _plugin(self) -> dict[str, object] | None:
        completed = self._run_codex(
            ["codex", "plugin", "list", "--marketplace", "personal", "--json"]
        )
        if completed.returncode != 0 or len(completed.stdout) > MAX_CODEX_BYTES:
            raise ReleaseLifecycleError("Codex plugin observation failed")
        try:
            value = json.loads(completed.stdout.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseLifecycleError("Codex plugin observation is invalid") from exc
        installed = value.get("installed") if isinstance(value, Mapping) else None
        if not isinstance(installed, list):
            raise ReleaseLifecycleError("Codex plugin observation has no installed array")
        matches = [
            item for item in installed
            if isinstance(item, Mapping) and item.get("pluginId") == PLUGIN_ID
        ]
        if len(matches) > 1:
            raise ReleaseLifecycleError("Codex plugin observation contains duplicate identities")
        return None if not matches else _normalized_plugin(matches[0])

    def _marketplace(self) -> tuple[dict[str, object], bool, dict[str, object] | None]:
        path = self.paths.marketplace_file
        if not os.path.lexists(path):
            value: dict[str, object] = {
                "name": "personal",
                "interface": {"displayName": "Personal"},
                "plugins": [],
            }
            return value, False, None
        value, _ = _read_json(path, MAX_MARKETPLACE_BYTES, "personal marketplace")
        plugins = value.get("plugins")
        if not isinstance(plugins, list):
            raise ReleaseLifecycleError("personal marketplace has no plugins array")
        matches = [
            item for item in plugins
            if isinstance(item, Mapping) and item.get("name") == PLUGIN_NAME
        ]
        if len(matches) > 1:
            raise ReleaseLifecycleError("personal marketplace has duplicate product entries")
        return value, True, None if not matches else dict(matches[0])

    def product_present(self) -> bool:
        plugin = self._plugin()
        _, _, marketplace = self._marketplace()
        return plugin is not None or marketplace is not None

    def _entry(self, release_path: str) -> dict[str, object]:
        plugin = Path(release_path) / "plugin"
        marketplace_root = self.paths.marketplace_file.parent.parent.parent
        try:
            source = "./" + plugin.relative_to(marketplace_root).as_posix()
        except ValueError:
            source = str(plugin)
        return {
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": source},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }

    def _entry_path(self, entry: Mapping[str, object] | None) -> Path | None:
        if entry is None:
            return None
        source = entry.get("source")
        if not isinstance(source, Mapping) or source.get("source") != "local":
            raise ReleaseLifecycleError("personal marketplace source is invalid")
        value = source.get("path")
        if not isinstance(value, str) or not value:
            raise ReleaseLifecycleError("personal marketplace path is invalid")
        if value.startswith("./"):
            return Path(os.path.abspath(self.paths.marketplace_file.parent.parent.parent / value[2:]))
        return _native_absolute(value, "personal marketplace plugin path")

    @staticmethod
    def _same(left: object, right: object) -> bool:
        return _canonical_bytes(left) == _canonical_bytes(right)

    def _replace_marketplace(
        self,
        expected: Mapping[str, object] | None,
        replacement: Mapping[str, object] | None,
        *,
        remove_file_after_empty: bool = False,
    ) -> None:
        value, existed, current = self._marketplace()
        if not self._same(current, expected):
            raise ReleaseLifecycleError("personal marketplace member changed concurrently")
        plugins = value["plugins"]
        assert isinstance(plugins, list)
        kept = [
            item for item in plugins
            if not (isinstance(item, Mapping) and item.get("name") == PLUGIN_NAME)
        ]
        value["plugins"] = kept + ([] if replacement is None else [dict(replacement)])
        if remove_file_after_empty and not kept and replacement is None:
            if existed:
                self.paths.marketplace_file.unlink()
            return
        _atomic_write(self.paths.marketplace_file, _canonical_bytes(value))

    @staticmethod
    def _observation(subject: str, state: str, value: object | None = None) -> Any:
        raw = None if value is None else _canonical_bytes(value)
        detail = None if value is None else raw.decode("utf-8").rstrip("\n")
        if detail is not None and len(detail.encode("utf-8")) > 3500:
            raise ReleaseLifecycleError(subject + " observation exceeds journal bound")
        return lifecycle_state.ExternalObservation(
            subject, state, None if raw is None else _sha256(raw), detail
        )

    @staticmethod
    def _effect(kind: str, subject: str, before: object, after: object, applied: bool = True) -> Any:
        before_raw = None if before is None else _canonical_bytes(before)
        after_raw = None if after is None else _canonical_bytes(after)
        return lifecycle_state.ProvisionalEffect(
            kind,
            subject,
            None if before_raw is None else _sha256(before_raw),
            None if after_raw is None else _sha256(after_raw),
            applied,
        )

    def _expected_identity(self, active: Any | None) -> tuple[Path | None, str | None]:
        if active is not None:
            receipt, _ = _read_json(
                Path(active.release_path) / runtime_integrity.RUNTIME_RECEIPT_NAME,
                runtime_integrity.MAX_RECEIPT_BYTES,
                "active runtime receipt",
            )
            return Path(active.release_path) / "plugin", str(receipt.get("version"))
        if self.migration is not None:
            return Path(str(self.migration["plugin_root"])), str(self.migration["version"])
        return None, None

    def observe_previous(self, active: Any | None) -> Any:
        try:
            _, existed, entry = self._marketplace()
            plugin = self._plugin()
            expected_path, expected_version = self._expected_identity(active)
            actual_path = self._entry_path(entry)
            exact = (
                entry is None and plugin is None
                if expected_path is None
                else (
                    actual_path == expected_path
                    and plugin is not None
                    and plugin["enabled"] is True
                    and plugin["version"] == expected_version
                )
            )
            snapshot = {
                "marketplace_file_existed": existed,
                "marketplace_entry": entry,
                "plugin": plugin,
            }
            self._previous = snapshot
            return lifecycle_machine.StepEvidence(
                exact,
                (
                    self._observation(
                        "previous-host-snapshot", "exact" if exact else "changed", snapshot
                    ),
                ),
                recovery=() if exact else ("Inspect installed plugin and marketplace identity.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("previous-host-snapshot", "unknown", detail=str(exc)),),
                recovery=("Inspect installed plugin and marketplace identity.",),
            )

    def provision_marketplace(self, candidate: Any) -> Any:
        current: Mapping[str, object] | None = None
        replacement: Mapping[str, object] | None = None
        applied = False
        try:
            _, _, current = self._marketplace()
            replacement = self._entry(candidate.release_path)
            self._replace_marketplace(current, replacement)
            applied = True
            _, _, observed = self._marketplace()
            exact = self._same(observed, replacement)
            return lifecycle_machine.StepEvidence(
                exact,
                (self._observation("candidate-marketplace", "exact" if exact else "changed", observed),),
                (self._effect("marketplace", str(self.paths.marketplace_file), current, replacement),),
                recovery=() if exact else ("Restore the recorded previous marketplace member.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("candidate-marketplace", "unknown", detail=str(exc)),),
                (
                    self._effect(
                        "marketplace",
                        str(self.paths.marketplace_file),
                        current,
                        replacement,
                        applied,
                    ),
                ),
                recovery=("Inspect the marketplace member before retrying.",),
            )

    def _activate_plugin(self) -> tuple[bool, bool]:
        before = self._plugin()
        removed = False
        if before is not None:
            completed = self._run_codex(["codex", "plugin", "remove", PLUGIN_ID])
            if completed.returncode != 0:
                return False, False
            removed = True
        completed = self._run_codex(["codex", "plugin", "add", PLUGIN_ID])
        return completed.returncode == 0, removed or completed.returncode == 0

    def provision_plugin(self, candidate: Any) -> Any:
        before: Mapping[str, object] | None = None
        observed: Mapping[str, object] | None = None
        applied = False
        try:
            before = self._plugin()
            command_ok, applied = self._activate_plugin()
            observed = self._plugin()
            exact = bool(
                command_ok
                and observed is not None
                and observed["enabled"] is True
                and observed["version"] == candidate.version
            )
            return lifecycle_machine.StepEvidence(
                exact,
                (self._observation("candidate-codex-plugin", "exact" if exact else "changed", observed),),
                (self._effect("plugin", PLUGIN_ID, before, observed, applied),),
                recovery=() if exact else ("Restore the recorded previous Codex plugin state.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("candidate-codex-plugin", "unknown", detail=str(exc)),),
                (self._effect("plugin", PLUGIN_ID, before, observed, applied),),
                recovery=("Inspect Codex plugin state before retrying.",),
            )

    def _mcp_visible(self) -> bool:
        completed = self._run_codex(["codex", "mcp", "list", "--json"])
        if completed.returncode != 0:
            return False
        try:
            value = json.loads(completed.stdout.decode("utf-8"), object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(value, list):
            return False
        matches = []
        for item in value:
            if not isinstance(item, Mapping) or item.get("name") != "dev-flow":
                continue
            transport = item.get("transport")
            if (
                item.get("enabled") is True
                and isinstance(transport, Mapping)
                and transport.get("type") == "stdio"
                and transport.get("command") == "dev-flow-mcp"
                and transport.get("args") == ["--stdio"]
            ):
                matches.append(item)
        return len(matches) == 1

    def _read_back(self, release_path: str, version: str) -> Any:
        try:
            _, _, entry = self._marketplace()
            plugin = self._plugin()
            exact = bool(
                self._entry_path(entry) == Path(release_path) / "plugin"
                and plugin is not None
                and plugin["enabled"] is True
                and plugin["version"] == version
                and self._mcp_visible()
            )
            return lifecycle_machine.StepEvidence(
                exact,
                (
                    self._observation("host-plugin-marketplace-read-back", "exact" if exact else "changed"),
                ),
                recovery=() if exact else ("Read back Codex plugin and bundled MCP discovery.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("host-plugin-marketplace-read-back", "unknown", detail=str(exc)),),
                recovery=("Read back Codex plugin and bundled MCP discovery.",),
            )

    def read_back_candidate(self, candidate: Any) -> Any:
        return self._read_back(candidate.release_path, candidate.version)

    def read_back_active(self, active: Any) -> Any:
        try:
            receipt, _ = _read_json(
                Path(active.release_path) / runtime_integrity.RUNTIME_RECEIPT_NAME,
                runtime_integrity.MAX_RECEIPT_BYTES,
                "active runtime receipt",
            )
            return self._read_back(active.release_path, str(receipt["version"]))
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("active-host-read-back", "unknown", detail=str(exc)),),
            )

    @staticmethod
    def _snapshot_from_journal(journal: Any) -> dict[str, object]:
        for observation in journal.external_observations:
            if observation.subject == "previous-host-snapshot" and observation.detail:
                try:
                    value = json.loads(observation.detail, object_pairs_hook=_strict_object)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ReleaseLifecycleError("previous host snapshot is invalid") from exc
                if isinstance(value, dict) and set(value) == {
                    "marketplace_file_existed", "marketplace_entry", "plugin"
                }:
                    return value
        raise ReleaseLifecycleError("previous host snapshot is unavailable")

    def restore_previous(self, journal: Any) -> Any:
        try:
            if journal.operation == "migration":
                if self.infrastructure is None:
                    raise ReleaseLifecycleError(
                        "migration infrastructure restoration is unavailable"
                    )
                retained = self.infrastructure.rollback(journal.transaction_id)
                if retained:
                    return lifecycle_machine.StepEvidence(
                        False,
                        (
                            lifecycle_state.ExternalObservation(
                                "previous-infrastructure-restoration",
                                "unknown",
                                detail="proven predecessor launchers could not be restored exactly",
                            ),
                        ),
                        retained_paths=retained,
                        recovery=(
                            "Stop automatic mutation and inspect retained predecessor infrastructure.",
                        ),
                    )
            snapshot = self._previous or self._snapshot_from_journal(journal)
            previous_entry = snapshot["marketplace_entry"]
            previous_plugin = snapshot["plugin"]
            _, _, current_entry = self._marketplace()
            self._replace_marketplace(
                current_entry,
                previous_entry if isinstance(previous_entry, Mapping) else None,
                remove_file_after_empty=snapshot["marketplace_file_existed"] is False,
            )
            current_plugin = self._plugin()
            if current_plugin is not None:
                if self._run_codex(
                    ["codex", "plugin", "remove", PLUGIN_ID]
                ).returncode != 0:
                    raise ReleaseLifecycleError("previous Codex plugin could not be restored")
            if previous_plugin is not None:
                if not isinstance(previous_plugin, Mapping) or previous_plugin.get("enabled") is not True:
                    raise ReleaseLifecycleError("previous inactive plugin state cannot be restored exactly")
                if self._run_codex(
                    ["codex", "plugin", "add", PLUGIN_ID]
                ).returncode != 0:
                    raise ReleaseLifecycleError("previous Codex plugin could not be restored")
            _, _, observed_entry = self._marketplace()
            observed_plugin = self._plugin()
            exact = self._same(observed_entry, previous_entry) and self._same(
                observed_plugin, previous_plugin
            )
            if journal.operation == "migration" and isinstance(previous_plugin, Mapping):
                version = previous_plugin.get("version")
                if isinstance(version, str) and version:
                    self._restored_legacy_version = version
            return lifecycle_machine.StepEvidence(
                exact,
                (self._observation("previous-host-restoration", "exact" if exact else "changed"),),
                recovery=() if exact else ("Inspect retained previous host state.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("previous-host-restoration", "unknown", detail=str(exc)),),
                recovery=("Stop automatic mutation and inspect the recorded previous host state.",),
            )

    def _public_mcp(self, version: str) -> bool:
        initialize = _canonical_bytes(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "dev-flow-public-proof", "version": "1"},
                },
            }
        )
        command = self.paths.bin_dir / ("dev-flow-mcp.cmd" if os.name == "nt" else "dev-flow-mcp")
        completed = _run(
            [str(command), "--stdio"],
            input_bytes=initialize,
            environment={"PLUGIN_DATA": str(self.paths.data_root), "CODEX_HOME": str(self.paths.codex_home)},
        )
        if completed.returncode != 0:
            return False
        for raw_line in completed.stdout.splitlines():
            try:
                value = json.loads(raw_line.decode("utf-8"), object_pairs_hook=_strict_object)
            except (UnicodeError, json.JSONDecodeError):
                continue
            result = value.get("result") if isinstance(value, Mapping) and value.get("id") == 1 else None
            server = result.get("serverInfo") if isinstance(result, Mapping) else None
            if isinstance(server, Mapping):
                return server.get("name") == "dev-flow" and server.get("version") == version
        return False

    def _public_release(self, version: str) -> tuple[bool, bool]:
        cli = self.paths.bin_dir / ("dev-flow.cmd" if os.name == "nt" else "dev-flow")
        completed = _run(
            [str(cli), "list"],
            environment={
                "PLUGIN_DATA": str(self.paths.data_root),
                "CODEX_HOME": str(self.paths.codex_home),
            },
        )
        cli_exact = completed.returncode == 0
        if cli_exact:
            try:
                cli_exact = isinstance(
                    json.loads(
                        completed.stdout.decode("utf-8"),
                        object_pairs_hook=_strict_object,
                    ),
                    dict,
                )
            except (UnicodeError, json.JSONDecodeError):
                cli_exact = False
        return cli_exact, self._public_mcp(version)

    def public_proof(self, active: Any | None) -> Any:
        if active is None:
            try:
                if self._restored_legacy_version is not None:
                    cli_exact, mcp_exact = self._public_release(
                        self._restored_legacy_version
                    )
                    exact = cli_exact and mcp_exact
                    return lifecycle_machine.StepEvidence(
                        exact,
                        (
                            lifecycle_state.ExternalObservation(
                                "previous-public-cli-startup",
                                "exact" if cli_exact else "changed",
                            ),
                            lifecycle_state.ExternalObservation(
                                "previous-public-mcp-startup",
                                "exact" if mcp_exact else "changed",
                            ),
                        ),
                        recovery=()
                        if exact
                        else ("Inspect restored frozen predecessor startup.",),
                    )
                _, _, entry = self._marketplace()
                exact = entry is None and self._plugin() is None
            except Exception as exc:
                return lifecycle_machine.StepEvidence(
                    False,
                    (lifecycle_state.ExternalObservation("public-absence-proof", "unknown", detail=str(exc)),),
                )
            return lifecycle_machine.StepEvidence(
                exact,
                (lifecycle_state.ExternalObservation("public-absence-proof", "exact" if exact else "changed"),),
            )
        try:
            receipt, _ = _read_json(
                Path(active.release_path) / runtime_integrity.RUNTIME_RECEIPT_NAME,
                runtime_integrity.MAX_RECEIPT_BYTES,
                "active runtime receipt",
            )
            version = str(receipt["version"])
            cli_exact, mcp_exact = self._public_release(version)
            exact = cli_exact and mcp_exact
            return lifecycle_machine.StepEvidence(
                exact,
                (
                    lifecycle_state.ExternalObservation(
                        "public-cli-startup", "exact" if cli_exact else "changed"
                    ),
                    lifecycle_state.ExternalObservation(
                        "public-mcp-startup", "exact" if mcp_exact else "changed"
                    ),
                ),
                recovery=() if exact else ("Rerun the exact-version bootstrap after inspecting public startup.",),
            )
        except Exception as exc:
            return lifecycle_machine.StepEvidence(
                False,
                (lifecycle_state.ExternalObservation("public-startup", "unknown", detail=str(exc)),),
                recovery=("Inspect stable dispatcher and active receipt evidence.",),
            )


class FrozenMigration:
    def __init__(self, paths: InstallPaths, host: ArtifactHost) -> None:
        self.paths = paths
        self.host = host

    def classify(self) -> Any:
        try:
            plugin = self.host._plugin()
            if plugin is None:
                raise ReleaseLifecycleError("no installed predecessor plugin is observable")
            proven = legacy_migration.classify_predecessor(
                runtime_root=self.paths.runtime_root,
                bin_dir=self.paths.bin_dir,
                marketplace_file=self.paths.marketplace_file,
                plugin_observation=plugin,
                windows=os.name == "nt",
            )
            self.host.migration = proven
            # The frozen installed observations prove which untouched public
            # predecessor must remain startable if candidate construction or
            # staged health fails before any host mutation.
            self.host._restored_legacy_version = str(proven["version"])
            return lifecycle_machine.MigrationClassification(
                True,
                (
                    lifecycle_state.ExternalObservation(
                        "legacy-predecessor", "exact", str(proven["receipt_sha256"]),
                        "frozen immediate predecessor proven from installed observations",
                    ),
                ),
            )
        except Exception as exc:
            return lifecycle_machine.MigrationClassification(
                False,
                (lifecycle_state.ExternalObservation("legacy-predecessor", "unknown", detail=str(exc)),),
                ("Inspect the frozen predecessor evidence without reading or changing its checkout.",),
            )


def _operation(active: Any, candidates: ArtifactCandidates, host: ArtifactHost) -> str:
    if active.record is not None:
        version = candidates.active_version(active.record)
        return "repair" if version is None or version == candidates.index.version else "upgrade"
    try:
        return "migration" if host.product_present() else "install"
    except Exception:
        # An unobservable installed identity is not safe to treat as fresh.
        # The frozen classifier will record a bounded terminal refusal.
        return "migration"


def _request(operation: str, transaction_id: str, paths: InstallPaths, index: IndexIdentity) -> Any:
    release_id = "v{}-{}-{}".format(index.version, index.manifest_sha256[:16], transaction_id)
    return lifecycle_machine.ActivationRequest(
        operation,
        transaction_id,
        index.version,
        release_id,
        str(paths.runtime_root / "releases" / release_id),
        lifecycle_machine.ArtifactEnvelope(
            index.index_sha256, index.archive_sha256, index.manifest_sha256
        ),
    )


def run_locked_auto(machine: Any, candidates: ArtifactCandidates, host: ArtifactHost, paths: InstallPaths, index: IndexIdentity) -> Any:
    """Select the operation only after the shared installation lock is held."""

    recovered: list[str] = []
    with machine.state.lock(timeout_seconds=machine.lock_timeout_seconds) as token:
        all_pending = machine.state.non_terminal_transactions(token)
        reinstall_pending = tuple(
            snapshot
            for snapshot in all_pending
            if snapshot.journal.operation == "reinstall"
        )
        authorized_reinstall = os.environ.get(REINSTALL_TRANSACTION_ENV)
        if authorized_reinstall is None:
            if reinstall_pending:
                # Do not terminalize or otherwise reinterpret a durable data
                # transaction.  Its installed command driver must resume it.
                machine.state.require_no_non_terminal(token)
        else:
            if _REINSTALL_TRANSACTION.fullmatch(authorized_reinstall) is None:
                raise ReleaseLifecycleError(
                    "internal reinstall transaction authorization is invalid"
                )
            if (
                len(reinstall_pending) != 1
                or reinstall_pending[0].journal.transaction_id
                != authorized_reinstall
                or reinstall_pending[0].journal.phase != "removing_data"
            ):
                raise ReleaseLifecycleError(
                    "internal reinstall transaction authorization does not match "
                    "one removing-data journal"
                )
        pending_transactions = [
            snapshot
            for snapshot in all_pending
            if snapshot.journal.transaction_id != authorized_reinstall
        ]
        if any(
            snapshot.journal.operation
            not in lifecycle_machine.ACTIVATION_OPERATIONS
            for snapshot in pending_transactions
        ):
            machine.state.require_no_non_terminal(
                token, except_transaction_id=authorized_reinstall
            )
        if len(pending_transactions) > 1:
            for pending in pending_transactions:
                machine.state.finish_transaction(
                    token,
                    pending,
                    "partial",
                    observations=(
                        lifecycle_state.ExternalObservation(
                            "transaction-recovery", "unknown",
                            detail="multiple non-terminal journals are ambiguous",
                        ),
                    ),
                    recovery=("Inspect every recorded transaction before further mutation.",),
                )
                recovered.append(pending.journal.transaction_id)
            return lifecycle_machine.LifecycleResult(
                pending_transactions[0].journal.transaction_id,
                "partial",
                machine.state.read_active(token),
                recovered_transactions=tuple(recovered),
                detail="multiple non-terminal lifecycle transactions were classified partial",
            )
        for pending in pending_transactions:
            result = machine._recover_one(token, pending)
            recovered.append(result.transaction_id)
            if result.outcome == "partial":
                return lifecycle_machine.LifecycleResult(
                    result.transaction_id,
                    "partial",
                    machine.state.read_active(token),
                    recovered_transactions=tuple(recovered),
                    detail="prior lifecycle transaction remains unresolved",
                )
        machine.state.require_no_non_terminal(
            token, except_transaction_id=authorized_reinstall
        )
        active = machine.state.read_active(token)
        operation = _operation(active, candidates, host)
        transaction_id = "tx-" + uuid.uuid4().hex
        request = _request(operation, transaction_id, paths, index)
        result = machine._run_locked(token, request)
        return lifecycle_machine.LifecycleResult(
            result.transaction_id,
            result.outcome,
            result.active,
            reused=result.reused,
            recovered_transactions=tuple(recovered),
            detail=result.detail,
        )


def execute_install(paths: InstallPaths, index: IndexIdentity, *, lock_timeout: float = 30.0) -> Any:
    releases = paths.runtime_root / "releases"
    state = lifecycle_state.LifecycleState(paths.runtime_root, releases)
    infrastructure = InfrastructureManager(paths)
    candidates = ArtifactCandidates(paths, index, infrastructure)
    host = ArtifactHost(paths, index, infrastructure)
    migration = FrozenMigration(paths, host)
    machine = lifecycle_machine.LifecycleMachine(
        state,
        candidates,
        host,
        migration_classifier=migration,
        lock_timeout_seconds=lock_timeout,
    )
    return run_locked_auto(machine, candidates, host, paths, index)


def _result_json(result: Any) -> dict[str, object]:
    active = result.active.record
    return {
        "ok": result.outcome == "committed",
        "outcome": result.outcome,
        "transaction_id": result.transaction_id,
        "reused": bool(result.reused),
        "recovered_transactions": list(result.recovered_transactions),
        "active": None if active is None else active.as_dict(),
        "detail": result.detail,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", allow_abbrev=False)
    install.add_argument("--release-index", required=True)
    install.add_argument("--release-index-sha256", required=True)
    install.add_argument("--runtime-root")
    install.add_argument("--bin-dir")
    install.add_argument("--marketplace-file")
    install.add_argument("--codex-home")
    install.add_argument("--data-root")
    install.add_argument("--lock-timeout", type=float, default=30.0)
    return parser


def _reject_repeated_options(arguments: Sequence[str]) -> None:
    seen: set[str] = set()
    for token in arguments:
        if not isinstance(token, str) or not token.startswith("--") or token == "--":
            continue
        option = token.partition("=")[0]
        if option in seen:
            raise ReleaseLifecycleError("repeated lifecycle option is rejected: " + option)
        seen.add(option)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        if "DEV_FLOW_SOURCE_ROOT" in os.environ:
            raise ReleaseLifecycleError(
                "DEV_FLOW_SOURCE_ROOT is unsupported; rerun the exact-version artifact bootstrap"
            )
        selected_argv = list(sys.argv[1:] if argv is None else argv)
        _reject_repeated_options(selected_argv)
        arguments = _parser().parse_args(selected_argv)
        if arguments.lock_timeout <= 0:
            raise ReleaseLifecycleError("lifecycle lock timeout must be positive")
        paths = resolve_install_paths(arguments)
        index = load_index_identity(paths.release_index, arguments.release_index_sha256)
        if index.model is None:
            raise ReleaseLifecycleError("Phase A release index model is unavailable")
        try:
            release_artifact.verify_extracted_artifact(
                paths.artifact_root,
                index.model,
            )
        except Exception as exc:
            raise ReleaseLifecycleError(
                "Phase B live artifact inventory verification failed: " + str(exc)
            ) from exc
        result = execute_install(paths, index, lock_timeout=arguments.lock_timeout)
        payload = _result_json(result)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if result.outcome == "committed" else 1
    except (ReleaseLifecycleError, OSError, ValueError, lifecycle_state.LifecycleStateError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "outcome": "partial",
                    "transaction_id": None,
                    "error": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
