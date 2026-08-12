#!/usr/bin/env python3
"""Standard-library sealing, runtime verification, and exact removal helpers.

This module intentionally does not import Dev Flow.  Installed launchers execute it
before the managed package is imported.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tarfile
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


PLUGIN_MANIFEST_NAME = "release-manifest.json"
PLUGIN_MANIFEST_SCHEMA = "dev-flow-plugin-release/1.0.0"
RUNTIME_RECEIPT_NAME = "runtime-receipt.json"
# Version 2 is retained only for the immediately preceding checkout-based
# installation fixture.  New artifact installations use the closed version 3
# receipt below; keeping the legacy constant avoids silently reinterpreting an
# already-installed predecessor receipt.
RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/2.0.0"
ARTIFACT_RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/3.0.0"
CANONICAL_REPOSITORY = "Innocent-children/dev-flow-orchestrator"
OWNERSHIP_MANIFEST_NAME = "ownership-manifest.json"
OWNERSHIP_MANIFEST_SCHEMA = "dev-flow-runtime-ownership/1.0.0"
ROOT_MARKER = ".dev-flow-managed-runtime"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20_000
MAX_ARCHIVE_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 256 * 1024 * 1024
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_TRANSACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")


class IntegrityError(RuntimeError):
    """Raised when sealed or installed content cannot be proven exact."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IntegrityError("value is not canonical JSON") from exc


def pretty_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise IntegrityError("value is not JSON") from exc


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def read_json(path: Path, *, maximum: int = MAX_JSON_BYTES) -> object:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IntegrityError("{} cannot be read".format(path)) from exc
    if len(raw) > maximum:
        raise IntegrityError("{} exceeds the supported byte limit".format(path))
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number: {}".format(value))
            ),
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise IntegrityError("{} is not strict UTF-8 JSON".format(path)) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(128 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise IntegrityError("{} cannot be hashed".format(path)) from exc
    return digest.hexdigest()


def _validate_hex(value: object, *, label: str, length: int = 64) -> str:
    pattern = _HEX_40 if length == 40 else _HEX_64
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise IntegrityError("{} must be lowercase {}-hex".format(label, length))
    return value


def _validate_release_id(value: object) -> str:
    if not isinstance(value, str) or not _RELEASE_ID.fullmatch(value):
        raise IntegrityError("release_id is invalid")
    return value


def _relative_parts(value: str, *, allow_dot: bool = False) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise IntegrityError("relative path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        if allow_dot and value == ".":
            return ()
        raise IntegrityError("relative path is not normalized: {}".format(value))
    if any(":" in part for part in path.parts):
        raise IntegrityError("relative path contains a platform-ambiguous component")
    return tuple(path.parts)


def _path_from_relative(root: Path, value: str, *, allow_dot: bool = False) -> Path:
    return root.joinpath(*_relative_parts(value, allow_dot=allow_dot))


def _validate_path_ancestors(root: Path, path: Path) -> None:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise IntegrityError("inventory root is unavailable") from exc
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise IntegrityError("inventory root is not a regular directory")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise IntegrityError("entry escapes its declared root") from exc
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise IntegrityError("entry ancestor is unavailable") from exc
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError("entry has a symbolic-link or non-directory ancestor")


def _entry_for_path(root: Path, path: Path, *, release_id: str | None = None) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise IntegrityError("entry disappeared during inventory: {}".format(relative)) from exc
    mode = stat.S_IMODE(metadata.st_mode)
    common: dict[str, object] = {"path": relative, "mode": mode}
    if release_id is not None:
        common["release_id"] = release_id
    if stat.S_ISREG(metadata.st_mode):
        common.update({"type": "file", "sha256": sha256_file(path)})
    elif stat.S_ISDIR(metadata.st_mode):
        common.update({"type": "directory"})
    elif stat.S_ISLNK(metadata.st_mode):
        try:
            target = os.readlink(path)
        except OSError as exc:
            raise IntegrityError("symbolic link cannot be read: {}".format(relative)) from exc
        common.update({"type": "symlink", "target": target})
    else:
        raise IntegrityError("unsupported special entry: {}".format(relative))
    return common


def inventory_tree(
    root: Path,
    *,
    excluded: Iterable[str] = (),
    release_id: str | None = None,
    include_root: bool = False,
) -> list[dict[str, object]]:
    _validate_path_ancestors(root, root)
    excluded_set = set(excluded)
    entries: list[dict[str, object]] = []
    if include_root:
        entry = _entry_for_path(root.parent, root, release_id=release_id)
        entry["path"] = "."
        entries.append(entry)
    pending = [root]
    while pending:
        parent = pending.pop()
        try:
            children = sorted(parent.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise IntegrityError("cannot enumerate {}".format(parent)) from exc
        directories: list[Path] = []
        for child in children:
            relative = child.relative_to(root).as_posix()
            if relative in excluded_set:
                continue
            entry = _entry_for_path(root, child, release_id=release_id)
            entries.append(entry)
            if entry["type"] == "directory":
                directories.append(child)
        pending.extend(reversed(directories))
    return sorted(entries, key=lambda item: str(item["path"]))


def _validate_entry_shape(value: object, *, release_id: str | None = None) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise IntegrityError("manifest entry must be an object")
    entry_type = value.get("type")
    required = {"path", "type", "mode"}
    if release_id is not None:
        required.add("release_id")
    if entry_type == "file":
        required.add("sha256")
    elif entry_type == "symlink":
        required.add("target")
    elif entry_type != "directory":
        raise IntegrityError("manifest entry type is unsupported")
    if set(value) != required:
        raise IntegrityError("manifest entry fields are invalid")
    path = value.get("path")
    if not isinstance(path, str):
        raise IntegrityError("manifest entry path is invalid")
    _relative_parts(path, allow_dot=True)
    mode = value.get("mode")
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
        raise IntegrityError("manifest entry mode is invalid")
    result: dict[str, object] = {"path": path, "type": entry_type, "mode": mode}
    if release_id is not None:
        if value.get("release_id") != release_id:
            raise IntegrityError("manifest entry release_id is invalid")
        result["release_id"] = release_id
    if entry_type == "file":
        result["sha256"] = _validate_hex(value.get("sha256"), label="file digest")
    elif entry_type == "symlink":
        target = value.get("target")
        if not isinstance(target, str) or "\x00" in target or len(target.encode("utf-8")) > 4096:
            raise IntegrityError("manifest symlink target is invalid")
        result["target"] = target
    return result


def _entry_matches(root: Path, entry: Mapping[str, object]) -> bool:
    path = _path_from_relative(root, str(entry["path"]), allow_dot=True)
    try:
        _validate_path_ancestors(root, path)
        metadata = path.lstat()
    except (OSError, IntegrityError):
        return False
    if stat.S_IMODE(metadata.st_mode) != entry["mode"]:
        return False
    entry_type = entry["type"]
    if entry_type == "directory":
        return stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)
    if entry_type == "symlink":
        return stat.S_ISLNK(metadata.st_mode) and os.readlink(path) == entry["target"]
    return stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode) and sha256_file(path) == entry["sha256"]


def _safe_tar_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise IntegrityError("Git archive contains too many entries")
    seen: set[str] = set()
    symlinks: set[tuple[str, ...]] = set()
    total = 0
    for member in members:
        parts = _relative_parts(member.name.rstrip("/"))
        normalized = PurePosixPath(*parts).as_posix()
        if normalized in seen:
            raise IntegrityError("Git archive contains a duplicate path")
        seen.add(normalized)
        for index in range(1, len(parts)):
            if parts[:index] in symlinks:
                raise IntegrityError("Git archive entry has a symbolic-link ancestor")
        if member.islnk() or member.ischr() or member.isblk() or member.isfifo() or member.isdev():
            raise IntegrityError("Git archive contains a hard link or special entry")
        if not (member.isfile() or member.isdir() or member.issym()):
            raise IntegrityError("Git archive contains an unsupported entry")
        if member.isfile():
            if member.size < 0 or member.size > MAX_ARCHIVE_FILE_BYTES:
                raise IntegrityError("Git archive file exceeds the supported byte limit")
            total += member.size
            if total > MAX_ARCHIVE_CONTENT_BYTES:
                raise IntegrityError("Git archive content exceeds the supported byte limit")
        if member.issym():
            target = member.linkname
            if not isinstance(target, str) or "\x00" in target or "\\" in target:
                raise IntegrityError("Git archive symbolic-link target is invalid")
            target_path = PurePosixPath(target)
            if target_path.is_absolute():
                raise IntegrityError("Git archive symbolic link escapes the release")
            combined: list[str] = list(parts[:-1])
            for component in target_path.parts:
                if component in {"", "."}:
                    continue
                if component == "..":
                    if not combined:
                        raise IntegrityError("Git archive symbolic link escapes the release")
                    combined.pop()
                else:
                    if "\\" in component or ":" in component:
                        raise IntegrityError("Git archive symbolic-link target is ambiguous")
                    combined.append(component)
            symlinks.add(parts)
    declared_directories = {
        _relative_parts(member.name.rstrip("/"))
        for member in members
        if member.isdir()
    }
    for member in members:
        parts = _relative_parts(member.name.rstrip("/"))
        for index in range(1, len(parts)):
            if parts[:index] in symlinks:
                raise IntegrityError("Git archive entry has a symbolic-link ancestor")
            if parts[:index] not in declared_directories:
                raise IntegrityError("Git archive entry has an undeclared directory ancestor")
    return members


def _remove_created(created: list[Path], destination: Path) -> None:
    for path in reversed(created):
        try:
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            pass
    try:
        destination.rmdir()
    except OSError:
        pass


def seal_archive(
    archive_path: Path,
    destination: Path,
    source_commit: str,
    source_tree: str,
) -> dict[str, object]:
    source_commit = _validate_hex(source_commit, label="source commit", length=40)
    source_tree = _validate_hex(source_tree, label="source tree", length=40)
    archive_path = archive_path.expanduser().resolve()
    destination = destination.expanduser()
    if destination.exists() or destination.is_symlink():
        raise IntegrityError("sealed release destination already exists")
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise IntegrityError("Git archive cannot be read") from exc
    if archive_size > MAX_ARCHIVE_BYTES:
        raise IntegrityError("Git archive exceeds the supported byte limit")
    created: list[Path] = []
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            comment = archive.pax_headers.get("comment")
            if comment != source_commit:
                raise IntegrityError("Git archive commit identity does not match the verified commit")
            members = _safe_tar_members(archive)
            destination.mkdir(parents=False, exist_ok=False)
            created.append(destination)
            directories = [item for item in members if item.isdir()]
            regular = [item for item in members if item.isfile()]
            links = [item for item in members if item.issym()]
            for member in directories + regular + links:
                path = destination.joinpath(*_relative_parts(member.name.rstrip("/")))
                if member.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                    path.chmod(0o755)
                    created.append(path)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if member.isfile():
                    source = archive.extractfile(member)
                    if source is None:
                        raise IntegrityError("Git archive file cannot be read")
                    with path.open("xb") as output:
                        shutil.copyfileobj(source, output, length=128 * 1024)
                    path.chmod(0o755 if member.mode & 0o111 else 0o644)
                else:
                    path.symlink_to(member.linkname)
                created.append(path)
        entries = inventory_tree(destination)
        body = {
            "source_commit": source_commit,
            "source_tree": source_tree,
            "entries": entries,
        }
        content_digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        release_id = "r-{}-{}".format(source_commit[:12], content_digest[:16])
        manifest = {
            "schema": PLUGIN_MANIFEST_SCHEMA,
            "release_id": release_id,
            "source_commit": source_commit,
            "source_tree": source_tree,
            "content_sha256": content_digest,
            "entries": entries,
        }
        manifest_path = destination / PLUGIN_MANIFEST_NAME
        manifest_path.write_bytes(pretty_json_bytes(manifest))
        created.append(manifest_path)
        verified = verify_plugin_release(
            destination,
            source_commit=source_commit,
            source_tree=source_tree,
            release_id=release_id,
        )
        return {
            "ok": True,
            "plugin_root": str(destination.resolve()),
            "release_id": release_id,
            "source_commit": source_commit,
            "source_tree": source_tree,
            "release_manifest_path": str(manifest_path.resolve()),
            "release_manifest_sha256": verified["manifest_sha256"],
        }
    except Exception:
        _remove_created(created, destination)
        raise


def verify_plugin_release(
    plugin_root: Path,
    *,
    source_commit: str | None = None,
    source_tree: str | None = None,
    release_id: str | None = None,
) -> dict[str, object]:
    selected_root = plugin_root.expanduser()
    try:
        selected_metadata = selected_root.lstat()
    except OSError as exc:
        raise IntegrityError("plugin release root cannot be inspected") from exc
    if not stat.S_ISDIR(selected_metadata.st_mode) or stat.S_ISLNK(selected_metadata.st_mode):
        raise IntegrityError("plugin release root must be a regular directory")
    plugin_root = selected_root.resolve()
    manifest_path = plugin_root / PLUGIN_MANIFEST_NAME
    value = read_json(manifest_path)
    required = {
        "schema", "release_id", "source_commit", "source_tree",
        "content_sha256", "entries",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise IntegrityError("plugin release manifest fields are invalid")
    if value.get("schema") != PLUGIN_MANIFEST_SCHEMA:
        raise IntegrityError("plugin release manifest schema is incompatible")
    actual_release_id = _validate_release_id(value.get("release_id"))
    actual_commit = _validate_hex(value.get("source_commit"), label="source commit", length=40)
    actual_tree = _validate_hex(value.get("source_tree"), label="source tree", length=40)
    content_digest = _validate_hex(value.get("content_sha256"), label="release content digest")
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise IntegrityError("plugin release entries are invalid")
    entries = [_validate_entry_shape(item) for item in raw_entries]
    paths = [str(item["path"]) for item in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise IntegrityError("plugin release paths are not unique and sorted")
    body = {"source_commit": actual_commit, "source_tree": actual_tree, "entries": entries}
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != content_digest:
        raise IntegrityError("plugin release content digest is invalid")
    expected_release_id = "r-{}-{}".format(actual_commit[:12], content_digest[:16])
    if actual_release_id != expected_release_id:
        raise IntegrityError("plugin release_id is not derived from sealed content")
    if source_commit is not None and actual_commit != source_commit:
        raise IntegrityError("plugin release source commit does not match")
    if source_tree is not None and actual_tree != source_tree:
        raise IntegrityError("plugin release source tree does not match")
    if release_id is not None and actual_release_id != release_id:
        raise IntegrityError("plugin release_id does not match")
    actual_entries = inventory_tree(plugin_root, excluded=(PLUGIN_MANIFEST_NAME,))
    if actual_entries != entries:
        raise IntegrityError("plugin release content differs from its sealed inventory")
    return {
        "release_id": actual_release_id,
        "source_commit": actual_commit,
        "source_tree": actual_tree,
        "manifest_sha256": sha256_file(manifest_path),
        "entries": entries,
    }


def copy_plugin_release(source: Path, destination: Path) -> dict[str, object]:
    verified = verify_plugin_release(source)
    if destination.exists() or destination.is_symlink():
        raise IntegrityError("plugin copy destination already exists")
    destination.mkdir(parents=False, exist_ok=False)
    created = [destination]
    try:
        entries = verified["entries"]
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, Mapping)
            source_path = _path_from_relative(source, str(entry["path"]))
            target_path = _path_from_relative(destination, str(entry["path"]))
            if not _entry_matches(source, entry):
                raise IntegrityError("sealed plugin source changed during copy")
            if entry["type"] == "directory":
                target_path.mkdir(parents=True, exist_ok=True)
                target_path.chmod(int(entry["mode"]))
            elif entry["type"] == "symlink":
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.symlink_to(str(entry["target"]))
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with source_path.open("rb") as input_stream, target_path.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=128 * 1024)
                target_path.chmod(int(entry["mode"]))
            created.append(target_path)
            if not _entry_matches(destination, entry) or not _entry_matches(source, entry):
                raise IntegrityError("sealed plugin source changed during copy")
        manifest_source = source / PLUGIN_MANIFEST_NAME
        manifest_target = destination / PLUGIN_MANIFEST_NAME
        with manifest_source.open("rb") as input_stream, manifest_target.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=128 * 1024)
        manifest_target.chmod(stat.S_IMODE(manifest_source.lstat().st_mode))
        created.append(manifest_target)
        verify_plugin_release(source, release_id=str(verified["release_id"]))
        return verify_plugin_release(destination, release_id=str(verified["release_id"]))
    except Exception:
        _remove_created(created, destination)
        raise


def build_ownership_manifest(runtime_dir: Path, release_id: str) -> dict[str, object]:
    release_id = _validate_release_id(release_id)
    entries = inventory_tree(
        runtime_dir,
        excluded=(OWNERSHIP_MANIFEST_NAME, RUNTIME_RECEIPT_NAME),
        release_id=release_id,
        include_root=True,
    )
    return {
        "schema": OWNERSHIP_MANIFEST_SCHEMA,
        "release_id": release_id,
        "entries": entries,
    }


def validate_ownership_manifest(value: object, release_id: str) -> dict[str, object]:
    release_id = _validate_release_id(release_id)
    if not isinstance(value, Mapping) or set(value) != {"schema", "release_id", "entries"}:
        raise IntegrityError("ownership manifest fields are invalid")
    if value.get("schema") != OWNERSHIP_MANIFEST_SCHEMA or value.get("release_id") != release_id:
        raise IntegrityError("ownership manifest identity is incompatible")
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise IntegrityError("ownership manifest entries are invalid")
    entries = [_validate_entry_shape(item, release_id=release_id) for item in raw_entries]
    paths = [str(item["path"]) for item in entries]
    if paths != sorted(paths) or len(paths) != len(set(paths)) or paths.count(".") != 1:
        raise IntegrityError("ownership manifest paths are not unique and sorted")
    return {"schema": OWNERSHIP_MANIFEST_SCHEMA, "release_id": release_id, "entries": entries}


def _normalized_distribution_name(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityError("installed distribution name is invalid")
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,199}", normalized):
        raise IntegrityError("installed distribution name is invalid")
    return normalized


def _runtime_relative(physical_runtime: Path, path: Path) -> str:
    root = os.path.abspath(physical_runtime)
    candidate = os.path.abspath(path)
    try:
        if os.path.commonpath((root, candidate)) != root:
            raise IntegrityError("installed distribution path escapes the managed runtime")
    except ValueError as exc:
        raise IntegrityError("installed distribution path is on another volume") from exc
    relative = os.path.relpath(candidate, root).replace(os.sep, "/")
    _relative_parts(relative)
    return relative


def _regular_digest(path: Path, *, label: str) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise IntegrityError("{} is missing".format(label)) from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise IntegrityError("{} is not a regular file".format(label))
    return sha256_file(path)


def _record_paths(distribution: importlib.metadata.Distribution) -> list[Path]:
    distribution_path = Path(str(getattr(distribution, "_path", "")))
    record = distribution_path / "RECORD"
    try:
        raw = record.read_bytes()
    except OSError as exc:
        raise IntegrityError("installed distribution RECORD is missing") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise IntegrityError("installed distribution RECORD exceeds the byte limit")
    try:
        rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    except (UnicodeError, csv.Error) as exc:
        raise IntegrityError("installed distribution RECORD is malformed") from exc
    located: list[Path] = []
    for row in rows:
        if len(row) != 3 or not row[0] or "\\" in row[0] or "\x00" in row[0]:
            raise IntegrityError("installed distribution RECORD row is invalid")
        located.append(Path(os.path.normpath(str(distribution.locate_file(row[0])))))
    return located


def _walk_regular_files(root: Path) -> list[Path]:
    try:
        metadata = root.lstat()
    except OSError as exc:
        raise IntegrityError("installed distribution root is missing") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise IntegrityError("installed distribution root is not a regular directory")
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise IntegrityError("installed distribution cannot be enumerated") from exc
        for child in children:
            child_metadata = child.lstat()
            if stat.S_ISDIR(child_metadata.st_mode) and not stat.S_ISLNK(child_metadata.st_mode):
                pending.append(child)
            elif stat.S_ISREG(child_metadata.st_mode) and not stat.S_ISLNK(child_metadata.st_mode):
                files.append(child)
            else:
                raise IntegrityError("installed distribution contains a special or linked entry")
    return files


def installed_distribution_snapshot(
    physical_runtime: Path,
    recorded_runtime: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    physical_runtime = Path(os.path.abspath(physical_runtime))
    recorded_runtime = Path(os.path.abspath(recorded_runtime))
    expected_python = physical_runtime / "venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    current_python = Path(os.path.abspath(sys.executable))
    if current_python != Path(os.path.abspath(expected_python)):
        raise IntegrityError("installed distribution inventory is not running in the managed environment")
    candidate_site_roots = tuple(
        Path(os.path.abspath(path))
        for path in sys.path
        if path and ("site-packages" in Path(path).parts or "dist-packages" in Path(path).parts)
    )
    if not candidate_site_roots:
        raise IntegrityError("managed environment has no package inventory root")
    venv_root = physical_runtime / "venv"
    site_roots: list[Path] = []
    for root in candidate_site_roots:
        try:
            _runtime_relative(venv_root, root)
            _validate_path_ancestors(venv_root, root)
            metadata = root.lstat()
        except OSError as exc:
            raise IntegrityError("managed package inventory root is unavailable") from exc
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError("managed package inventory root is not a regular directory")
        site_roots.append(root)
    distributions: dict[str, importlib.metadata.Distribution] = {}
    for distribution in importlib.metadata.distributions(path=[str(path) for path in site_roots]):
        distribution_path = Path(os.path.abspath(str(getattr(distribution, "_path", ""))))
        contained = False
        for root in site_roots:
            try:
                contained = (
                    os.path.normcase(os.path.commonpath((str(root), str(distribution_path))))
                    == os.path.normcase(str(root))
                )
            except ValueError:
                contained = False
            if contained:
                break
        if not contained:
            raise IntegrityError("installed distribution escapes the managed environment")
        name = _normalized_distribution_name(distribution.metadata.get("Name"))
        if name in distributions:
            raise IntegrityError("installed runtime has duplicate distribution {}".format(name))
        distributions[name] = distribution
    project = distributions.pop("dev-flow-orchestrator", None)
    if project is None:
        raise IntegrityError("installed Dev Flow distribution is missing")

    def identity(distribution: importlib.metadata.Distribution) -> dict[str, object]:
        distribution_path = Path(str(getattr(distribution, "_path", "")))
        name = _normalized_distribution_name(distribution.metadata.get("Name"))
        version = distribution.version
        if not isinstance(version, str) or not version or len(version.encode("utf-8")) > 128:
            raise IntegrityError("installed distribution version is invalid")
        return {
            "name": name,
            "version": version,
            "metadata_sha256": _regular_digest(
                distribution_path / "METADATA", label="installed distribution METADATA"
            ),
            "record_sha256": _regular_digest(
                distribution_path / "RECORD", label="installed distribution RECORD"
            ),
        }

    project_identity = identity(project)
    project_dist_info = Path(str(getattr(project, "_path", "")))
    record_paths = _record_paths(project)
    actual_paths: set[Path] = set(record_paths)
    actual_paths.update(_walk_regular_files(project_dist_info))
    for record_path in record_paths:
        try:
            relative_to_site = record_path.relative_to(Path(str(project.locate_file(""))))
        except ValueError:
            continue
        if not relative_to_site.parts or relative_to_site.parts[0] != "dev_flow_orchestrator":
            continue
        top_level = Path(str(project.locate_file(relative_to_site.parts[0])))
        if top_level.is_dir() and not top_level.is_symlink():
            actual_paths.update(_walk_regular_files(top_level))
    files: list[dict[str, str]] = []
    for path in sorted(actual_paths, key=lambda item: str(item)):
        relative = _runtime_relative(physical_runtime, path)
        files.append({"path": relative, "sha256": _regular_digest(path, label=relative)})
    paths = [item["path"] for item in files]
    if len(paths) != len(set(paths)):
        raise IntegrityError("installed Dev Flow file inventory contains duplicate paths")
    project_identity["files"] = sorted(files, key=lambda item: item["path"])
    dependencies = sorted(
        (identity(distribution) for distribution in distributions.values()),
        key=lambda item: (str(item["name"]), str(item["version"])),
    )
    return project_identity, dependencies


def python_identity(physical_runtime: Path, recorded_runtime: Path) -> dict[str, object]:
    physical_runtime = Path(os.path.abspath(physical_runtime))
    recorded_runtime = Path(os.path.abspath(recorded_runtime))
    executable = Path(os.path.abspath(sys.executable))
    relative = _runtime_relative(physical_runtime, executable)
    recorded_executable = recorded_runtime.joinpath(*PurePosixPath(relative).parts)
    try:
        selected_metadata = executable.lstat()
        resolved_executable = executable.resolve(strict=True)
        resolved_metadata = resolved_executable.stat()
    except OSError as exc:
        raise IntegrityError("managed Python executable is unavailable") from exc
    if not (
        stat.S_ISREG(selected_metadata.st_mode) or stat.S_ISLNK(selected_metadata.st_mode)
    ) or not stat.S_ISREG(resolved_metadata.st_mode):
        raise IntegrityError("managed Python executable identity is unsupported")
    return {
        "path": str(recorded_executable),
        "executable_sha256": sha256_file(resolved_executable),
        "version": platform.python_version(),
        "architecture": platform.machine(),
        "bits": 64 if sys.maxsize > 2**32 else 32,
    }


def build_runtime_receipt(
    *,
    physical_runtime: Path,
    recorded_runtime: Path,
    release_id: str,
    source_commit: str,
    source_tree: str,
    dependency_lock_sha256: str,
    plugin_release_manifest_sha256: str,
    wheel_path: Path,
    launcher_path: Path,
    cli_launcher_path: Path | None,
    ownership_manifest_path: Path,
) -> dict[str, object]:
    release_id = _validate_release_id(release_id)
    source_commit = _validate_hex(source_commit, label="source commit", length=40)
    source_tree = _validate_hex(source_tree, label="source tree", length=40)
    dependency_lock_sha256 = _validate_hex(
        dependency_lock_sha256, label="dependency lock digest"
    )
    plugin_release_manifest_sha256 = _validate_hex(
        plugin_release_manifest_sha256, label="plugin release manifest digest"
    )
    project, dependencies = installed_distribution_snapshot(physical_runtime, recorded_runtime)
    value: dict[str, object] = {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "wheel_sha256": _regular_digest(wheel_path, label="built Dev Flow wheel"),
        "plugin_path": str(Path(os.path.abspath(recorded_runtime)) / "plugin"),
        "plugin_release_manifest_sha256": plugin_release_manifest_sha256,
        "dev_flow": project,
        "dependencies": dependencies,
        "python": python_identity(physical_runtime, recorded_runtime),
        "runtime_path": str(Path(os.path.abspath(recorded_runtime))),
        "launcher_sha256": _regular_digest(launcher_path, label="managed MCP launcher"),
        "cli_launcher_sha256": (
            None
            if cli_launcher_path is None
            else _regular_digest(cli_launcher_path, label="managed CLI launcher")
        ),
        "ownership_manifest_sha256": _regular_digest(
            ownership_manifest_path, label="runtime ownership manifest"
        ),
        "dependency_lock_sha256": dependency_lock_sha256,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return validate_runtime_receipt(value)


def _validate_file_inventory(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise IntegrityError("Dev Flow installed file inventory is invalid")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise IntegrityError("Dev Flow installed file entry is invalid")
        path = item.get("path")
        if not isinstance(path, str):
            raise IntegrityError("Dev Flow installed file path is invalid")
        _relative_parts(path)
        result.append({
            "path": path,
            "sha256": _validate_hex(item.get("sha256"), label="installed file digest"),
        })
    paths = [item["path"] for item in result]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise IntegrityError("Dev Flow installed file paths are not unique and sorted")
    return result


def _validate_distribution(value: object, *, project: bool) -> dict[str, object]:
    expected = {"name", "version", "metadata_sha256", "record_sha256"}
    if project:
        expected.add("files")
    if not isinstance(value, Mapping) or set(value) != expected:
        raise IntegrityError("installed distribution receipt fields are invalid")
    name = _normalized_distribution_name(value.get("name"))
    version = value.get("version")
    if not isinstance(version, str) or not version or len(version.encode("utf-8")) > 128:
        raise IntegrityError("installed distribution receipt version is invalid")
    result: dict[str, object] = {
        "name": name,
        "version": version,
        "metadata_sha256": _validate_hex(value.get("metadata_sha256"), label="METADATA digest"),
        "record_sha256": _validate_hex(value.get("record_sha256"), label="RECORD digest"),
    }
    if project:
        if name != "dev-flow-orchestrator":
            raise IntegrityError("Dev Flow distribution name is invalid")
        result["files"] = _validate_file_inventory(value.get("files"))
    return result


def validate_runtime_receipt(value: object) -> dict[str, object]:
    required = {
        "schema", "release_id", "source_commit", "source_tree", "wheel_sha256",
        "plugin_path", "plugin_release_manifest_sha256", "dev_flow", "dependencies",
        "python", "runtime_path", "launcher_sha256", "cli_launcher_sha256",
        "ownership_manifest_sha256",
        "dependency_lock_sha256", "created_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise IntegrityError("runtime receipt fields are invalid")
    if len(canonical_json_bytes(value)) > MAX_RECEIPT_BYTES:
        raise IntegrityError("runtime receipt exceeds the supported byte limit")
    if value.get("schema") != RUNTIME_RECEIPT_SCHEMA:
        raise IntegrityError("runtime receipt schema is incompatible")
    release_id = _validate_release_id(value.get("release_id"))
    runtime_path = value.get("runtime_path")
    plugin_path = value.get("plugin_path")
    if not isinstance(runtime_path, str) or not os.path.isabs(runtime_path):
        raise IntegrityError("runtime receipt path is invalid")
    runtime_path = os.path.abspath(runtime_path)
    if not isinstance(plugin_path, str) or os.path.abspath(plugin_path) != os.path.join(runtime_path, "plugin"):
        raise IntegrityError("runtime receipt plugin path is invalid")
    python_value = value.get("python")
    python_fields = {"path", "executable_sha256", "version", "architecture", "bits"}
    if not isinstance(python_value, Mapping) or set(python_value) != python_fields:
        raise IntegrityError("runtime receipt Python identity is invalid")
    python_path = python_value.get("path")
    if not isinstance(python_path, str) or not os.path.isabs(python_path):
        raise IntegrityError("runtime receipt Python path is invalid")
    try:
        if os.path.commonpath((runtime_path, os.path.abspath(python_path))) != runtime_path:
            raise IntegrityError("runtime receipt Python path escapes the release")
    except ValueError as exc:
        raise IntegrityError("runtime receipt Python path is invalid") from exc
    version = python_value.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"3\.(?:10|11|12|13|14)\.[0-9]+", version):
        raise IntegrityError("managed runtime requires Python 3.10 through 3.14")
    architecture = python_value.get("architecture")
    if not isinstance(architecture, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", architecture):
        raise IntegrityError("runtime receipt Python architecture is invalid")
    if isinstance(python_value.get("bits"), bool) or python_value.get("bits") != 64:
        raise IntegrityError("managed runtime requires 64-bit Python")
    dependencies_value = value.get("dependencies")
    if not isinstance(dependencies_value, list):
        raise IntegrityError("runtime dependency inventory is invalid")
    dependencies = [_validate_distribution(item, project=False) for item in dependencies_value]
    names = [str(item["name"]) for item in dependencies]
    if dependencies != sorted(dependencies, key=lambda item: (str(item["name"]), str(item["version"]))) or len(names) != len(set(names)):
        raise IntegrityError("runtime dependency inventory is not unique and sorted")
    if "dev-flow-orchestrator" in names:
        raise IntegrityError("runtime dependency inventory includes Dev Flow")
    created_at = value.get("created_at")
    if not isinstance(created_at, str) or not created_at.endswith("Z") or len(created_at) > 64:
        raise IntegrityError("runtime receipt timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(created_at[:-1] + "+00:00")
    except ValueError as exc:
        raise IntegrityError("runtime receipt timestamp is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IntegrityError("runtime receipt timestamp is not UTC")
    return {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "source_commit": _validate_hex(value.get("source_commit"), label="source commit", length=40),
        "source_tree": _validate_hex(value.get("source_tree"), label="source tree", length=40),
        "wheel_sha256": _validate_hex(value.get("wheel_sha256"), label="wheel digest"),
        "plugin_path": os.path.abspath(plugin_path),
        "plugin_release_manifest_sha256": _validate_hex(
            value.get("plugin_release_manifest_sha256"), label="plugin manifest digest"
        ),
        "dev_flow": _validate_distribution(value.get("dev_flow"), project=True),
        "dependencies": dependencies,
        "python": {
            "path": os.path.abspath(python_path),
            "executable_sha256": _validate_hex(
                python_value.get("executable_sha256"), label="Python executable digest"
            ),
            "version": version,
            "architecture": architecture,
            "bits": 64,
        },
        "runtime_path": runtime_path,
        "launcher_sha256": _validate_hex(value.get("launcher_sha256"), label="launcher digest"),
        "cli_launcher_sha256": (
            None
            if value.get("cli_launcher_sha256") is None
            else _validate_hex(value.get("cli_launcher_sha256"), label="CLI launcher digest")
        ),
        "ownership_manifest_sha256": _validate_hex(
            value.get("ownership_manifest_sha256"), label="ownership manifest digest"
        ),
        "dependency_lock_sha256": _validate_hex(
            value.get("dependency_lock_sha256"), label="dependency lock digest"
        ),
        "created_at": created_at,
    }


def read_runtime_receipt(path: Path) -> dict[str, object]:
    return validate_runtime_receipt(read_json(path, maximum=MAX_RECEIPT_BYTES))


def _validate_transaction_id(value: object) -> str:
    if not isinstance(value, str) or not _TRANSACTION_ID.fullmatch(value):
        raise IntegrityError("transaction_id is invalid")
    return value


def _validate_version(value: object) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise IntegrityError("release version is invalid")
    return value


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 64:
        raise IntegrityError("runtime receipt timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntegrityError("runtime receipt timestamp is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise IntegrityError("runtime receipt timestamp is not UTC")
    return value


def _validate_artifact_python(
    value: object,
    *,
    runtime_path: str,
) -> dict[str, object]:
    fields = {"path", "executable_sha256", "version", "architecture", "bits"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise IntegrityError("artifact runtime Python identity is invalid")
    expected_relative = os.path.join(
        "venv", "Scripts", "python.exe"
    ) if os.name == "nt" else os.path.join("venv", "bin", "python")
    expected_path = os.path.join(runtime_path, expected_relative)
    python_path = value.get("path")
    if not isinstance(python_path, str) or os.path.abspath(python_path) != expected_path:
        raise IntegrityError("artifact runtime Python path is invalid")
    version = value.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"3\.(?:10|11|12|13|14)\.[0-9]+", version
    ):
        raise IntegrityError("managed runtime requires Python 3.10 through 3.14")
    architecture = value.get("architecture")
    if not isinstance(architecture, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", architecture
    ):
        raise IntegrityError("artifact runtime Python architecture is invalid")
    if isinstance(value.get("bits"), bool) or value.get("bits") != 64:
        raise IntegrityError("managed runtime requires 64-bit Python")
    return {
        "path": expected_path,
        "executable_sha256": _validate_hex(
            value.get("executable_sha256"), label="Python executable digest"
        ),
        "version": version,
        "architecture": architecture,
        "bits": 64,
    }


def _validate_lifecycle_helpers(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise IntegrityError("versioned lifecycle helper inventory is invalid")
    helpers: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
            raise IntegrityError("versioned lifecycle helper entry is invalid")
        path = item.get("path")
        if not isinstance(path, str):
            raise IntegrityError("versioned lifecycle helper path is invalid")
        parts = _relative_parts(path)
        if not parts or parts[0] != "lifecycle":
            raise IntegrityError("versioned lifecycle helper escapes its directory")
        helpers.append(
            {
                "path": path,
                "sha256": _validate_hex(
                    item.get("sha256"), label="versioned lifecycle helper digest"
                ),
            }
        )
    paths = [item["path"] for item in helpers]
    if paths != sorted(paths) or len(paths) != len(set(paths)) or not helpers:
        raise IntegrityError("versioned lifecycle helper paths are not unique and sorted")
    mandatory = {
        "lifecycle/manage_runtime.py",
        "lifecycle/release_artifact.py",
        "lifecycle/release_lifecycle.py",
        "lifecycle/runtime_integrity.py",
        "lifecycle/validate_installed_stage1.py",
    }
    if not mandatory.issubset(paths):
        raise IntegrityError("required versioned lifecycle helpers are missing")
    return helpers


def lifecycle_helper_snapshot(physical_runtime: Path) -> list[dict[str, str]]:
    """Inventory every installed versioned lifecycle helper by exact bytes."""

    physical_runtime = Path(os.path.abspath(physical_runtime))
    lifecycle_root = physical_runtime / "lifecycle"
    files = _walk_regular_files(lifecycle_root)
    helpers = [
        {
            "path": _runtime_relative(physical_runtime, path),
            "sha256": _regular_digest(path, label="versioned lifecycle helper"),
        }
        for path in sorted(files, key=lambda item: str(item))
    ]
    return _validate_lifecycle_helpers(helpers)


def validate_artifact_runtime_receipt(value: object) -> dict[str, object]:
    """Validate the closed receipt used by checkout-free artifact installs."""

    required = {
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
    if not isinstance(value, Mapping) or set(value) != required:
        raise IntegrityError("artifact runtime receipt fields are invalid")
    if len(canonical_json_bytes(value)) > MAX_RECEIPT_BYTES:
        raise IntegrityError("artifact runtime receipt exceeds the supported byte limit")
    if value.get("schema") != ARTIFACT_RUNTIME_RECEIPT_SCHEMA:
        raise IntegrityError("artifact runtime receipt schema is incompatible")
    if value.get("repository") != CANONICAL_REPOSITORY:
        raise IntegrityError("artifact runtime repository identity is invalid")
    release_id = _validate_release_id(value.get("release_id"))
    version = _validate_version(value.get("version"))
    runtime_path_value = value.get("runtime_path")
    if not isinstance(runtime_path_value, str) or not os.path.isabs(runtime_path_value):
        raise IntegrityError("artifact runtime receipt path is invalid")
    runtime_path = os.path.abspath(runtime_path_value)
    if Path(runtime_path).name != release_id:
        raise IntegrityError("artifact runtime path does not match release_id")
    plugin_path_value = value.get("plugin_path")
    if (
        not isinstance(plugin_path_value, str)
        or os.path.abspath(plugin_path_value) != os.path.join(runtime_path, "plugin")
    ):
        raise IntegrityError("artifact runtime plugin path is invalid")
    project = _validate_distribution(value.get("dev_flow"), project=True)
    if project["version"] != version:
        raise IntegrityError("installed project version differs from the artifact version")
    dependencies_value = value.get("dependencies")
    if not isinstance(dependencies_value, list):
        raise IntegrityError("artifact runtime dependency inventory is invalid")
    dependencies = [
        _validate_distribution(item, project=False) for item in dependencies_value
    ]
    names = [str(item["name"]) for item in dependencies]
    if (
        dependencies
        != sorted(
            dependencies,
            key=lambda item: (str(item["name"]), str(item["version"])),
        )
        or len(names) != len(set(names))
        or "dev-flow-orchestrator" in names
    ):
        raise IntegrityError("artifact runtime dependency inventory is not unique and sorted")
    python = _validate_artifact_python(value.get("python"), runtime_path=runtime_path)
    python_executable_sha256 = _validate_hex(
        value.get("python_executable_sha256"), label="top-level Python executable digest"
    )
    if python_executable_sha256 != python["executable_sha256"]:
        raise IntegrityError("top-level Python executable digest disagrees with Python identity")
    return {
        "schema": ARTIFACT_RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "version": version,
        "repository": CANONICAL_REPOSITORY,
        "source_commit": _validate_hex(
            value.get("source_commit"), label="source commit", length=40
        ),
        "source_tree": _validate_hex(
            value.get("source_tree"), label="source tree", length=40
        ),
        "release_index_sha256": _validate_hex(
            value.get("release_index_sha256"), label="release index digest"
        ),
        "archive_sha256": _validate_hex(
            value.get("archive_sha256"), label="release archive digest"
        ),
        "artifact_manifest_sha256": _validate_hex(
            value.get("artifact_manifest_sha256"), label="artifact manifest digest"
        ),
        "wheel_sha256": _validate_hex(value.get("wheel_sha256"), label="wheel digest"),
        "runtime_requirements_sha256": _validate_hex(
            value.get("runtime_requirements_sha256"), label="runtime requirements digest"
        ),
        "uv_lock_sha256": _validate_hex(value.get("uv_lock_sha256"), label="uv.lock digest"),
        "plugin_path": os.path.join(runtime_path, "plugin"),
        "plugin_release_manifest_sha256": _validate_hex(
            value.get("plugin_release_manifest_sha256"), label="plugin manifest digest"
        ),
        "dev_flow": project,
        "dependencies": dependencies,
        "python": python,
        "python_executable_sha256": python_executable_sha256,
        "runtime_path": runtime_path,
        "transaction_id": _validate_transaction_id(value.get("transaction_id")),
        "verifier_sha256": _validate_hex(
            value.get("verifier_sha256"), label="versioned verifier digest"
        ),
        "lifecycle_helpers": _validate_lifecycle_helpers(value.get("lifecycle_helpers")),
        "ownership_manifest_sha256": _validate_hex(
            value.get("ownership_manifest_sha256"), label="ownership manifest digest"
        ),
        "created_at": _validate_timestamp(value.get("created_at")),
    }


def build_artifact_runtime_receipt(
    *,
    physical_runtime: Path,
    recorded_runtime: Path,
    release_id: str,
    version: str,
    transaction_id: str,
    source_commit: str,
    source_tree: str,
    release_index_sha256: str,
    archive_sha256: str,
    artifact_manifest_path: Path,
    wheel_path: Path,
    runtime_requirements_path: Path,
    uv_lock_path: Path,
    plugin_release_manifest_sha256: str,
    verifier_path: Path,
    ownership_manifest_path: Path,
) -> dict[str, object]:
    physical_runtime = Path(os.path.abspath(physical_runtime))
    recorded_runtime = Path(os.path.abspath(recorded_runtime))
    expected_verifier = physical_runtime / "integrity" / "runtime_integrity.py"
    if Path(os.path.abspath(verifier_path)) != expected_verifier:
        raise IntegrityError("versioned verifier is not installed at its fixed path")
    project, dependencies = installed_distribution_snapshot(
        physical_runtime, recorded_runtime
    )
    python = python_identity(physical_runtime, recorded_runtime)
    value: dict[str, object] = {
        "schema": ARTIFACT_RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "version": version,
        "repository": CANONICAL_REPOSITORY,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "release_index_sha256": release_index_sha256,
        "archive_sha256": archive_sha256,
        "artifact_manifest_sha256": _regular_digest(
            artifact_manifest_path, label="artifact release manifest"
        ),
        "wheel_sha256": _regular_digest(wheel_path, label="supplied project wheel"),
        "runtime_requirements_sha256": _regular_digest(
            runtime_requirements_path, label="runtime requirements"
        ),
        "uv_lock_sha256": _regular_digest(uv_lock_path, label="uv.lock"),
        "plugin_path": str(recorded_runtime / "plugin"),
        "plugin_release_manifest_sha256": plugin_release_manifest_sha256,
        "dev_flow": project,
        "dependencies": dependencies,
        "python": python,
        "python_executable_sha256": python["executable_sha256"],
        "runtime_path": str(recorded_runtime),
        "transaction_id": transaction_id,
        "verifier_sha256": _regular_digest(
            verifier_path, label="versioned runtime verifier"
        ),
        "lifecycle_helpers": lifecycle_helper_snapshot(physical_runtime),
        "ownership_manifest_sha256": _regular_digest(
            ownership_manifest_path, label="runtime ownership manifest"
        ),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return validate_artifact_runtime_receipt(value)


def read_artifact_runtime_receipt(path: Path) -> dict[str, object]:
    return validate_artifact_runtime_receipt(
        read_json(path, maximum=MAX_RECEIPT_BYTES)
    )


def artifact_digest_envelope(receipt: object) -> dict[str, str]:
    """Return the same-version immutable byte envelope used by repair."""

    value = validate_artifact_runtime_receipt(receipt)
    return {
        "release_index_sha256": str(value["release_index_sha256"]),
        "archive_sha256": str(value["archive_sha256"]),
        "artifact_manifest_sha256": str(value["artifact_manifest_sha256"]),
    }


def require_same_version_envelope(
    active_receipt: object,
    candidate_receipt: object,
) -> None:
    """Reject silent same-version replacement while allowing real upgrades."""

    active = validate_artifact_runtime_receipt(active_receipt)
    candidate = validate_artifact_runtime_receipt(candidate_receipt)
    if active["version"] != candidate["version"]:
        return
    if artifact_digest_envelope(active) != artifact_digest_envelope(candidate):
        raise IntegrityError(
            "same-version artifact digest envelope differs from the active receipt"
        )


def verify_runtime(
    runtime_dir: Path,
    launcher_path: Path,
    *,
    expected_release_id: str | None = None,
    allow_staging: bool = False,
) -> dict[str, object]:
    runtime_dir = Path(os.path.abspath(runtime_dir))
    try:
        runtime_metadata = runtime_dir.lstat()
    except OSError as exc:
        raise IntegrityError("managed runtime release is missing") from exc
    if not stat.S_ISDIR(runtime_metadata.st_mode) or stat.S_ISLNK(runtime_metadata.st_mode):
        raise IntegrityError("managed runtime release is not a regular directory")
    receipt = read_runtime_receipt(runtime_dir / RUNTIME_RECEIPT_NAME)
    release_id = str(receipt["release_id"])
    if expected_release_id is not None and release_id != expected_release_id:
        raise IntegrityError("managed runtime release_id does not match the launcher")
    recorded_runtime = Path(str(receipt["runtime_path"]))
    if not allow_staging and runtime_dir != Path(os.path.abspath(recorded_runtime)):
        raise IntegrityError("managed runtime path does not match its receipt")
    if not allow_staging and runtime_dir.name != release_id:
        raise IntegrityError("managed runtime directory does not match release_id")
    expected_python_relative = Path("venv") / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    current_python = Path(os.path.abspath(sys.executable))
    if current_python != Path(os.path.abspath(runtime_dir / expected_python_relative)):
        raise IntegrityError("verifier is not running with the selected managed Python")
    if Path(str(receipt["python"]["path"])) != recorded_runtime / expected_python_relative:
        raise IntegrityError("runtime receipt Python path does not select the managed interpreter")
    plugin_root = runtime_dir / "plugin"
    plugin = verify_plugin_release(
        plugin_root,
        source_commit=str(receipt["source_commit"]),
        source_tree=str(receipt["source_tree"]),
        release_id=release_id,
    )
    if plugin["manifest_sha256"] != receipt["plugin_release_manifest_sha256"]:
        raise IntegrityError("plugin release manifest digest differs from the runtime receipt")
    ownership_path = runtime_dir / OWNERSHIP_MANIFEST_NAME
    if _regular_digest(ownership_path, label="runtime ownership manifest") != receipt["ownership_manifest_sha256"]:
        raise IntegrityError("runtime ownership manifest digest differs from the receipt")
    ownership = validate_ownership_manifest(read_json(ownership_path), release_id)
    actual_ownership = build_ownership_manifest(runtime_dir, release_id)
    if ownership != actual_ownership:
        raise IntegrityError("managed runtime content differs from its ownership manifest")
    if _regular_digest(launcher_path, label="managed MCP launcher") != receipt["launcher_sha256"]:
        raise IntegrityError("managed MCP launcher digest differs from the receipt")
    cli_digest = receipt["cli_launcher_sha256"]
    cli_path = runtime_dir / "launchers" / "dev-flow.cmd"
    if (
        cli_digest is not None
        and _regular_digest(cli_path, label="managed CLI launcher") != cli_digest
    ):
        raise IntegrityError("managed CLI launcher digest differs from the receipt")
    if cli_digest is None and (cli_path.exists() or cli_path.is_symlink()):
        raise IntegrityError("unreceipted managed CLI launcher is present")
    artifacts = runtime_dir / "artifacts"
    try:
        wheels = [
            item for item in artifacts.iterdir()
            if item.name.endswith(".whl") and item.is_file() and not item.is_symlink()
        ]
    except OSError as exc:
        raise IntegrityError("managed wheel artifact cannot be enumerated") from exc
    if len(wheels) != 1 or sha256_file(wheels[0]) != receipt["wheel_sha256"]:
        raise IntegrityError("managed wheel artifact differs from the receipt")
    current_project, current_dependencies = installed_distribution_snapshot(
        runtime_dir, recorded_runtime
    )
    if current_project != receipt["dev_flow"]:
        raise IntegrityError("installed Dev Flow content differs from the receipt")
    if current_dependencies != receipt["dependencies"]:
        raise IntegrityError("installed dependency inventory differs from the receipt")
    if python_identity(runtime_dir, recorded_runtime) != receipt["python"]:
        raise IntegrityError("managed Python identity differs from the receipt")
    return receipt


def _plugin_product_version(plugin_root: Path) -> str:
    value = read_json(plugin_root / ".codex-plugin" / "plugin.json")
    if not isinstance(value, Mapping):
        raise IntegrityError("installed plugin manifest is invalid")
    if value.get("name") != "dev-flow-orchestrator":
        raise IntegrityError("installed plugin identity is invalid")
    return _validate_version(value.get("version"))


def _artifact_evidence_paths(runtime_dir: Path) -> tuple[Path, Path, Path, Path]:
    evidence = runtime_dir / "artifact"
    try:
        metadata = evidence.lstat()
    except OSError as exc:
        raise IntegrityError("installed artifact evidence is missing") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise IntegrityError("installed artifact evidence is not a regular directory")
    wheels_root = evidence / "wheels"
    try:
        wheel_entries = list(wheels_root.iterdir())
    except OSError as exc:
        raise IntegrityError("installed project wheel cannot be enumerated") from exc
    wheels: list[Path] = []
    for item in wheel_entries:
        try:
            item_metadata = item.lstat()
        except OSError as exc:
            raise IntegrityError("installed project wheel cannot be inspected") from exc
        if stat.S_ISREG(item_metadata.st_mode) and not stat.S_ISLNK(item_metadata.st_mode):
            wheels.append(item)
        else:
            raise IntegrityError("installed project wheel directory contains a non-file entry")
    if len(wheels) != 1 or not wheels[0].name.endswith("-py3-none-any.whl"):
        raise IntegrityError("installed artifact must retain one pure-Python project wheel")
    expected_names = {"release-manifest.json", "runtime-requirements.txt", "uv.lock", "wheels"}
    try:
        actual_names = {item.name for item in evidence.iterdir()}
    except OSError as exc:
        raise IntegrityError("installed artifact evidence cannot be enumerated") from exc
    if actual_names != expected_names:
        raise IntegrityError("installed artifact evidence topology is invalid")
    return (
        evidence / "release-manifest.json",
        wheels[0],
        evidence / "runtime-requirements.txt",
        evidence / "uv.lock",
    )


def verify_artifact_runtime(
    runtime_dir: Path,
    *,
    expected_release_id: str | None = None,
    expected_transaction_id: str | None = None,
    allow_staging: bool = False,
) -> dict[str, object]:
    """Attest a v3 managed release before any project import."""

    runtime_dir = Path(os.path.abspath(runtime_dir))
    try:
        runtime_metadata = runtime_dir.lstat()
    except OSError as exc:
        raise IntegrityError("managed artifact release is missing") from exc
    if not stat.S_ISDIR(runtime_metadata.st_mode) or stat.S_ISLNK(runtime_metadata.st_mode):
        raise IntegrityError("managed artifact release is not a regular directory")
    receipt = read_artifact_runtime_receipt(runtime_dir / RUNTIME_RECEIPT_NAME)
    release_id = str(receipt["release_id"])
    if expected_release_id is not None and release_id != expected_release_id:
        raise IntegrityError("managed artifact release_id does not match")
    if (
        expected_transaction_id is not None
        and receipt["transaction_id"] != expected_transaction_id
    ):
        raise IntegrityError("managed artifact transaction_id does not match")
    recorded_runtime = Path(str(receipt["runtime_path"]))
    if not allow_staging and runtime_dir != Path(os.path.abspath(recorded_runtime)):
        raise IntegrityError("managed artifact path does not match its receipt")
    if recorded_runtime.name != release_id:
        raise IntegrityError("managed artifact path does not match release_id")
    expected_python_relative = Path("venv") / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    current_python = Path(os.path.abspath(sys.executable))
    if current_python != Path(os.path.abspath(runtime_dir / expected_python_relative)):
        raise IntegrityError("artifact verifier is not running with the managed Python")
    if Path(str(receipt["python"]["path"])) != recorded_runtime / expected_python_relative:
        raise IntegrityError("artifact receipt Python path does not select the managed interpreter")
    try:
        resolved_python = current_python.resolve(strict=True)
        resolved_python_metadata = resolved_python.stat()
    except OSError as exc:
        raise IntegrityError("managed Python executable is unavailable") from exc
    if not stat.S_ISREG(resolved_python_metadata.st_mode):
        raise IntegrityError("managed Python executable is not a regular file")
    if sha256_file(resolved_python) != receipt["python_executable_sha256"]:
        raise IntegrityError("managed Python executable differs from the artifact receipt")
    plugin_root = runtime_dir / "plugin"
    plugin = verify_plugin_release(
        plugin_root,
        source_commit=str(receipt["source_commit"]),
        source_tree=str(receipt["source_tree"]),
    )
    if plugin["manifest_sha256"] != receipt["plugin_release_manifest_sha256"]:
        raise IntegrityError("plugin release manifest digest differs from the artifact receipt")
    if _plugin_product_version(plugin_root) != receipt["version"]:
        raise IntegrityError("plugin version differs from the artifact receipt")
    ownership_path = runtime_dir / OWNERSHIP_MANIFEST_NAME
    if (
        _regular_digest(ownership_path, label="runtime ownership manifest")
        != receipt["ownership_manifest_sha256"]
    ):
        raise IntegrityError("runtime ownership manifest digest differs from the artifact receipt")
    ownership = validate_ownership_manifest(read_json(ownership_path), release_id)
    if ownership != build_ownership_manifest(runtime_dir, release_id):
        raise IntegrityError("managed artifact content differs from its ownership manifest")
    verifier = runtime_dir / "integrity" / "runtime_integrity.py"
    if (
        _regular_digest(verifier, label="versioned runtime verifier")
        != receipt["verifier_sha256"]
    ):
        raise IntegrityError("versioned runtime verifier digest differs from the receipt")
    if lifecycle_helper_snapshot(runtime_dir) != receipt["lifecycle_helpers"]:
        raise IntegrityError("versioned lifecycle helpers differ from the receipt")
    manifest, wheel, requirements, lock = _artifact_evidence_paths(runtime_dir)
    expected_evidence = (
        (manifest, "artifact_manifest_sha256", "artifact release manifest"),
        (wheel, "wheel_sha256", "supplied project wheel"),
        (requirements, "runtime_requirements_sha256", "runtime requirements"),
        (lock, "uv_lock_sha256", "uv.lock"),
    )
    for path, field, label in expected_evidence:
        if _regular_digest(path, label=label) != receipt[field]:
            raise IntegrityError("{} differs from the artifact receipt".format(label))
    current_project, current_dependencies = installed_distribution_snapshot(
        runtime_dir, recorded_runtime
    )
    if current_project != receipt["dev_flow"]:
        raise IntegrityError("installed Dev Flow content differs from the artifact receipt")
    if current_dependencies != receipt["dependencies"]:
        raise IntegrityError("installed dependencies differ from the artifact receipt")
    current_python_identity = python_identity(runtime_dir, recorded_runtime)
    if current_python_identity != receipt["python"]:
        raise IntegrityError("managed Python identity differs from the artifact receipt")
    return receipt


def launch_artifact_runtime(
    runtime_dir: Path,
    mode: str,
    arguments: list[str],
) -> None:
    if mode not in {"cli", "mcp"}:
        raise IntegrityError("artifact runtime launch mode is invalid")
    if mode == "mcp" and arguments != ["--stdio"]:
        raise IntegrityError("managed MCP accepts exactly --stdio")
    receipt = verify_artifact_runtime(runtime_dir)
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    python_path = str(receipt["python"]["path"])
    module = "dev_flow_orchestrator.cli" if mode == "cli" else "dev_flow_orchestrator.mcp"
    os.execve(
        python_path,
        [python_path, "-B", "-I", "-m", module, *arguments],
        environment,
    )


def launch_mcp(
    runtime_dir: Path,
    launcher_path: Path,
    release_id: str,
    arguments: list[str],
) -> None:
    receipt = verify_runtime(
        runtime_dir,
        launcher_path,
        expected_release_id=release_id,
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    python_path = str(receipt["python"]["path"])
    os.execve(
        python_path,
        [python_path, "-B", "-I", "-m", "dev_flow_orchestrator.mcp", *arguments],
        environment,
    )


def _retained_entry(retained: list[dict[str, str]], path: Path, reason: str) -> None:
    rendered = str(path)
    if any(item["path"] == rendered for item in retained):
        return
    retained.append({"path": rendered, "reason": reason[:512]})


def _remove_matching_entry(
    root: Path,
    entry: Mapping[str, object],
    retained: list[dict[str, str]],
    sequence: int,
) -> bool:
    path = _path_from_relative(root, str(entry["path"]), allow_dot=True)
    if entry["type"] == "directory":
        try:
            _validate_path_ancestors(root, path)
            metadata = path.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                _retained_entry(retained, path, "owned directory changed type")
                return False
            if stat.S_IMODE(metadata.st_mode) != entry["mode"]:
                _retained_entry(retained, path, "owned directory mode changed")
                return False
            path.rmdir()
            return True
        except (OSError, IntegrityError):
            _retained_entry(retained, path, "owned directory is non-empty, missing, or changed")
            return False
    try:
        _validate_path_ancestors(root, path)
        before = path.lstat()
    except (OSError, IntegrityError):
        _retained_entry(retained, path, "owned entry is missing or inaccessible")
        return False
    try:
        if not _entry_matches(root, entry):
            _retained_entry(retained, path, "owned entry content, type, mode, or target changed")
            return False
        after = path.lstat()
    except (OSError, IntegrityError):
        _retained_entry(retained, path, "owned entry changed during validation")
        return False
    identity_before = (
        before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns
    )
    identity_after = (
        after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns
    )
    if identity_before != identity_after:
        _retained_entry(retained, path, "owned entry changed during validation")
        return False
    quarantine = path.with_name(".dev-flow-remove-{}-{}".format(os.getpid(), sequence))
    if quarantine.exists() or quarantine.is_symlink():
        _retained_entry(retained, path, "same-filesystem quarantine name is occupied")
        return False
    try:
        _validate_path_ancestors(root, path)
        path.rename(quarantine)
        quarantine_entry = dict(entry)
        quarantine_entry["path"] = quarantine.relative_to(root).as_posix()
        if not _entry_matches(root, quarantine_entry):
            if not path.exists() and not path.is_symlink():
                quarantine.rename(path)
            _retained_entry(retained, quarantine, "entry changed before quarantine revalidation")
            return False
        quarantine.unlink()
        return True
    except (OSError, IntegrityError):
        if (quarantine.exists() or quarantine.is_symlink()) and not (path.exists() or path.is_symlink()):
            try:
                quarantine.rename(path)
            except OSError:
                _retained_entry(retained, quarantine, "quarantined entry could not be restored")
        _retained_entry(retained, path, "owned entry could not be removed safely")
        return False


def _remove_control_file(
    path: Path,
    expected_digest: str | None,
    validator: Any,
    retained: list[dict[str, str]],
    sequence: int,
) -> bool:
    quarantine: Path | None = None
    try:
        _validate_path_ancestors(path.parent, path)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise IntegrityError("control file changed type")
        if expected_digest is not None and sha256_file(path) != expected_digest:
            raise IntegrityError("control file digest changed")
        validator(path)
        quarantine = path.with_name(".dev-flow-remove-{}-control-{}".format(os.getpid(), sequence))
        if quarantine.exists() or quarantine.is_symlink():
            raise IntegrityError("control quarantine is occupied")
        path.rename(quarantine)
        if expected_digest is not None and sha256_file(quarantine) != expected_digest:
            quarantine.rename(path)
            raise IntegrityError("control file changed during quarantine")
        validator(quarantine)
        quarantine.unlink()
        return True
    except (OSError, IntegrityError):
        if quarantine is not None and (quarantine.exists() or quarantine.is_symlink()) and not (path.exists() or path.is_symlink()):
            try:
                quarantine.rename(path)
            except OSError:
                _retained_entry(retained, quarantine, "quarantined control file could not be restored")
        _retained_entry(retained, path, "validated control file could not be removed safely")
        return False


def _validate_runtime_marker(path: Path) -> None:
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or path.read_bytes() != b"dev-flow-managed-runtime/1\n"
    ):
        raise IntegrityError("managed runtime ownership marker changed")


def _same_directory_identity(path: Path, expected: os.stat_result) -> bool:
    try:
        current = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and (current.st_dev, current.st_ino, current.st_mode)
        == (expected.st_dev, expected.st_ino, expected.st_mode)
    )


def read_any_runtime_receipt(path: Path) -> dict[str, object]:
    """Read either the frozen predecessor receipt or the active artifact receipt."""

    value = read_json(path, maximum=MAX_RECEIPT_BYTES)
    if not isinstance(value, Mapping):
        raise IntegrityError("runtime receipt must be an object")
    if value.get("schema") == RUNTIME_RECEIPT_SCHEMA:
        return validate_runtime_receipt(value)
    if value.get("schema") == ARTIFACT_RUNTIME_RECEIPT_SCHEMA:
        return validate_artifact_runtime_receipt(value)
    raise IntegrityError("runtime receipt schema is incompatible")


def remove_owned_release(release_path: Path) -> dict[str, object]:
    """Compare-and-remove exactly one receipted release, retaining all doubt.

    This API deliberately does not enumerate sibling releases or touch the
    runtime root.  Lifecycle code can therefore remove only the release named
    by its locked transaction journal.
    """

    selected = release_path.expanduser()
    retained: list[dict[str, str]] = []
    removed = 0
    try:
        selected_metadata = selected.lstat()
    except OSError:
        return {
            "ok": True,
            "action": "removed",
            "release_path": str(selected),
            "removed_count": 0,
            "retained": [],
            "retained_paths": [],
        }
    if not stat.S_ISDIR(selected_metadata.st_mode) or stat.S_ISLNK(selected_metadata.st_mode):
        raise IntegrityError("managed release is not a regular directory")
    release = selected.resolve()
    receipt_path = release / RUNTIME_RECEIPT_NAME
    manifest_path = release / OWNERSHIP_MANIFEST_NAME
    try:
        receipt_digest = sha256_file(receipt_path)
        receipt = read_any_runtime_receipt(receipt_path)
        if Path(str(receipt["runtime_path"])) != release:
            raise IntegrityError("receipt runtime path does not match release")
        release_id = str(receipt["release_id"])
        if release.name != release_id:
            raise IntegrityError("receipt release_id does not match release directory")
        if sha256_file(manifest_path) != receipt["ownership_manifest_sha256"]:
            raise IntegrityError("ownership manifest digest does not match receipt")
        manifest = validate_ownership_manifest(read_json(manifest_path), release_id)
    except (OSError, IntegrityError) as exc:
        _retained_entry(retained, release, "unverifiable release retained: {}".format(exc))
        return {
            "ok": False,
            "action": "retained",
            "release_path": str(release),
            "removed_count": 0,
            "retained": retained,
            "retained_paths": [item["path"] for item in retained],
        }
    entries = list(manifest["entries"])
    payload_entries = [item for item in entries if item["path"] != "."]
    nondirectories = [item for item in payload_entries if item["type"] != "directory"]
    directories = sorted(
        (item for item in payload_entries if item["type"] == "directory"),
        key=lambda item: (str(item["path"]).count("/"), str(item["path"])),
        reverse=True,
    )
    sequence = 0
    release_clean = True
    for entry in nondirectories + directories:
        sequence += 1
        if _remove_matching_entry(release, entry, retained, sequence):
            removed += 1
        else:
            release_clean = False
    if release_clean:
        sequence += 1
        receipt_ok = _remove_control_file(
            receipt_path,
            receipt_digest,
            read_any_runtime_receipt,
            retained,
            sequence,
        )
        if receipt_ok:
            removed += 1
            sequence += 1
            manifest_ok = _remove_control_file(
                manifest_path,
                str(receipt["ownership_manifest_sha256"]),
                lambda path: validate_ownership_manifest(read_json(path), release_id),
                retained,
                sequence,
            )
            if manifest_ok:
                removed += 1
                root_entry = next(item for item in entries if item["path"] == ".")
                if _remove_matching_entry(release, root_entry, retained, sequence + 1):
                    removed += 1
                else:
                    release_clean = False
            else:
                release_clean = False
        else:
            release_clean = False
    retained = sorted(retained, key=lambda item: (item["path"], item["reason"]))
    if not retained and not release.exists():
        action = "removed"
    elif removed:
        action = "partial"
    else:
        action = "retained"
    return {
        "ok": action == "removed",
        "action": action,
        "release_path": str(release),
        "removed_count": removed,
        "retained": retained,
        "retained_paths": [item["path"] for item in retained],
    }


def remove_owned(runtime_root: Path) -> dict[str, object]:
    selected_runtime_root = runtime_root.expanduser()
    retained: list[dict[str, str]] = []
    removed = 0
    try:
        root_metadata = selected_runtime_root.lstat()
    except OSError:
        return {
            "ok": True,
            "action": "removed",
            "removed_count": 0,
            "retained": [],
            "retained_paths": [],
        }
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise IntegrityError("managed runtime root is not a regular directory")
    runtime_root = selected_runtime_root.resolve()
    marker = runtime_root / ROOT_MARKER
    try:
        marker_metadata = marker.lstat()
        marker_valid = (
            stat.S_ISREG(marker_metadata.st_mode)
            and not stat.S_ISLNK(marker_metadata.st_mode)
            and marker.read_bytes() == b"dev-flow-managed-runtime/1\n"
        )
    except OSError:
        marker_valid = False
    if not marker_valid:
        raise IntegrityError("managed runtime root has no valid ownership marker")
    releases = runtime_root / "releases"
    try:
        releases_metadata = releases.lstat()
    except OSError:
        _retained_entry(retained, runtime_root, "managed releases directory is missing")
        releases_metadata = None
    if releases_metadata is not None and (
        not stat.S_ISDIR(releases_metadata.st_mode) or stat.S_ISLNK(releases_metadata.st_mode)
    ):
        raise IntegrityError("managed releases path is not a regular directory")
    release_paths = [] if releases_metadata is None else sorted(releases.iterdir(), key=lambda item: item.name)
    sequence = 0
    for release in release_paths:
        try:
            release_metadata = release.lstat()
        except OSError:
            _retained_entry(retained, release, "release disappeared during inventory")
            continue
        if not stat.S_ISDIR(release_metadata.st_mode) or stat.S_ISLNK(release_metadata.st_mode):
            _retained_entry(retained, release, "unknown non-directory release entry")
            continue
        try:
            receipt_path = release / RUNTIME_RECEIPT_NAME
            manifest_path = release / OWNERSHIP_MANIFEST_NAME
            receipt_digest = sha256_file(receipt_path)
            receipt = read_any_runtime_receipt(receipt_path)
            if Path(str(receipt["runtime_path"])) != release:
                raise IntegrityError("receipt runtime path does not match release")
            release_id = str(receipt["release_id"])
            if release.name != release_id:
                raise IntegrityError("receipt release_id does not match release directory")
            if sha256_file(manifest_path) != receipt["ownership_manifest_sha256"]:
                raise IntegrityError("ownership manifest digest does not match receipt")
            manifest = validate_ownership_manifest(read_json(manifest_path), release_id)
        except (OSError, IntegrityError) as exc:
            _retained_entry(retained, release, "legacy or unverifiable release retained: {}".format(exc))
            continue
        entries = list(manifest["entries"])
        payload_entries = [item for item in entries if item["path"] != "."]
        nondirectories = [item for item in payload_entries if item["type"] != "directory"]
        directories = sorted(
            (item for item in payload_entries if item["type"] == "directory"),
            key=lambda item: (str(item["path"]).count("/"), str(item["path"])),
            reverse=True,
        )
        release_clean = True
        for entry in nondirectories + directories:
            sequence += 1
            if _remove_matching_entry(release, entry, retained, sequence):
                removed += 1
            else:
                release_clean = False
        if release_clean:
            sequence += 1
            receipt_ok = _remove_control_file(
                receipt_path,
                receipt_digest,
                read_any_runtime_receipt,
                retained,
                sequence,
            )
            if receipt_ok:
                removed += 1
                sequence += 1
                manifest_ok = _remove_control_file(
                    manifest_path,
                    str(receipt["ownership_manifest_sha256"]),
                    lambda path: validate_ownership_manifest(read_json(path), release_id),
                    retained,
                    sequence,
                )
                if manifest_ok:
                    removed += 1
                    root_entry = next(item for item in entries if item["path"] == ".")
                    if _remove_matching_entry(release, root_entry, retained, sequence + 1):
                        removed += 1
                    else:
                        release_clean = False
                else:
                    release_clean = False
            else:
                release_clean = False
    try:
        remaining_releases = tuple(releases.iterdir()) if releases.exists() else ()
    except OSError:
        remaining_releases = (releases,)
    if (
        not remaining_releases
        and releases_metadata is not None
        and _same_directory_identity(releases, releases_metadata)
    ):
        try:
            releases.rmdir()
            removed += 1
        except OSError:
            _retained_entry(retained, releases, "managed releases directory could not be removed")
    elif not remaining_releases and releases.exists():
        _retained_entry(retained, releases, "managed releases directory changed during removal")
    if not retained and not releases.exists():
        try:
            root_entries = tuple(runtime_root.iterdir())
        except OSError:
            root_entries = (runtime_root,)
        unknown_root_entries = [item for item in root_entries if item != marker]
        if unknown_root_entries:
            for item in unknown_root_entries:
                _retained_entry(retained, item, "unknown runtime-root content")
            _retained_entry(retained, runtime_root, "managed runtime root retained for unknown content")
        else:
            marker_removed = False
            try:
                sequence += 1
                marker_removed = _remove_control_file(
                    marker,
                    hashlib.sha256(b"dev-flow-managed-runtime/1\n").hexdigest(),
                    _validate_runtime_marker,
                    retained,
                    sequence,
                )
                if not marker_removed:
                    raise IntegrityError("managed runtime ownership marker changed")
                removed += 1
                if not _same_directory_identity(runtime_root, root_metadata):
                    raise IntegrityError("managed runtime root changed during removal")
                runtime_root.rmdir()
                removed += 1
            except (OSError, IntegrityError):
                if marker_removed and runtime_root.exists() and not marker.exists():
                    try:
                        with marker.open("xb") as stream:
                            stream.write(b"dev-flow-managed-runtime/1\n")
                        marker.chmod(0o600)
                        removed -= 1
                    except OSError:
                        pass
                _retained_entry(retained, runtime_root, "managed runtime root contains concurrent content")
    elif runtime_root.exists():
        _retained_entry(retained, runtime_root, "managed runtime root retained for remaining content")
    retained = sorted(retained, key=lambda item: (item["path"], item["reason"]))
    if not retained and not runtime_root.exists():
        action = "removed"
    elif removed:
        action = "partial"
    else:
        action = "retained"
    return {
        "ok": action == "removed",
        "action": action,
        "removed_count": removed,
        "retained": retained,
        "retained_paths": [item["path"] for item in retained],
    }


def _write_json_result(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    seal = subparsers.add_parser("seal")
    seal.add_argument("--archive", required=True)
    seal.add_argument("--destination", required=True)
    seal.add_argument("--source-commit", required=True)
    seal.add_argument("--source-tree", required=True)
    verify_plugin = subparsers.add_parser("verify-plugin")
    verify_plugin.add_argument("--plugin-root", required=True)
    verify_plugin.add_argument("--source-commit")
    verify_plugin.add_argument("--source-tree")
    verify_plugin.add_argument("--release-id")
    verify = subparsers.add_parser("verify-runtime")
    verify.add_argument("--runtime-dir", required=True)
    verify.add_argument("--launcher", required=True)
    verify.add_argument("--release-id")
    verify.add_argument("--allow-staging", action="store_true")
    build_receipt = subparsers.add_parser("build-receipt")
    build_receipt.add_argument("--physical-runtime", required=True)
    build_receipt.add_argument("--recorded-runtime", required=True)
    build_receipt.add_argument("--release-id", required=True)
    build_receipt.add_argument("--source-commit", required=True)
    build_receipt.add_argument("--source-tree", required=True)
    build_receipt.add_argument("--dependency-lock-sha256", required=True)
    build_receipt.add_argument("--plugin-release-manifest-sha256", required=True)
    build_receipt.add_argument("--wheel", required=True)
    build_receipt.add_argument("--launcher", required=True)
    build_receipt.add_argument("--cli-launcher")
    build_receipt.add_argument("--ownership-manifest", required=True)
    build_artifact_receipt = subparsers.add_parser("build-artifact-receipt")
    build_artifact_receipt.add_argument("--physical-runtime", required=True)
    build_artifact_receipt.add_argument("--recorded-runtime", required=True)
    build_artifact_receipt.add_argument("--release-id", required=True)
    build_artifact_receipt.add_argument("--version", required=True)
    build_artifact_receipt.add_argument("--transaction-id", required=True)
    build_artifact_receipt.add_argument("--source-commit", required=True)
    build_artifact_receipt.add_argument("--source-tree", required=True)
    build_artifact_receipt.add_argument("--release-index-sha256", required=True)
    build_artifact_receipt.add_argument("--archive-sha256", required=True)
    build_artifact_receipt.add_argument("--artifact-manifest", required=True)
    build_artifact_receipt.add_argument("--wheel", required=True)
    build_artifact_receipt.add_argument("--runtime-requirements", required=True)
    build_artifact_receipt.add_argument("--uv-lock", required=True)
    build_artifact_receipt.add_argument("--plugin-release-manifest-sha256", required=True)
    build_artifact_receipt.add_argument("--verifier", required=True)
    build_artifact_receipt.add_argument("--ownership-manifest", required=True)
    verify_artifact = subparsers.add_parser("verify-artifact-runtime")
    verify_artifact.add_argument("--runtime-dir", required=True)
    verify_artifact.add_argument("--release-id")
    verify_artifact.add_argument("--transaction-id")
    verify_artifact.add_argument("--allow-staging", action="store_true")
    launch = subparsers.add_parser("launch-mcp")
    launch.add_argument("--runtime-dir")
    launch.add_argument("--runtime")
    launch.add_argument("--launcher")
    launch.add_argument("--release-id")
    launch.add_argument("arguments", nargs=argparse.REMAINDER)
    launch_cli = subparsers.add_parser("launch-cli")
    launch_cli.add_argument("--runtime", required=True)
    launch_cli.add_argument("arguments", nargs=argparse.REMAINDER)
    remove = subparsers.add_parser("remove-owned")
    remove.add_argument("--runtime-root", required=True)
    remove_release = subparsers.add_parser("remove-owned-release")
    remove_release.add_argument("--release-path", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "seal":
            result = seal_archive(
                Path(arguments.archive),
                Path(arguments.destination),
                arguments.source_commit,
                arguments.source_tree,
            )
        elif arguments.command == "verify-plugin":
            result = {
                "ok": True,
                **verify_plugin_release(
                    Path(arguments.plugin_root),
                    source_commit=arguments.source_commit,
                    source_tree=arguments.source_tree,
                    release_id=arguments.release_id,
                ),
            }
        elif arguments.command == "build-receipt":
            result = {
                "ok": True,
                "receipt": build_runtime_receipt(
                    physical_runtime=Path(arguments.physical_runtime),
                    recorded_runtime=Path(arguments.recorded_runtime),
                    release_id=arguments.release_id,
                    source_commit=arguments.source_commit,
                    source_tree=arguments.source_tree,
                    dependency_lock_sha256=arguments.dependency_lock_sha256,
                    plugin_release_manifest_sha256=arguments.plugin_release_manifest_sha256,
                    wheel_path=Path(arguments.wheel),
                    launcher_path=Path(arguments.launcher),
                    cli_launcher_path=(
                        None
                        if arguments.cli_launcher is None
                        else Path(arguments.cli_launcher)
                    ),
                    ownership_manifest_path=Path(arguments.ownership_manifest),
                ),
            }
        elif arguments.command == "build-artifact-receipt":
            result = {
                "ok": True,
                "receipt": build_artifact_runtime_receipt(
                    physical_runtime=Path(arguments.physical_runtime),
                    recorded_runtime=Path(arguments.recorded_runtime),
                    release_id=arguments.release_id,
                    version=arguments.version,
                    transaction_id=arguments.transaction_id,
                    source_commit=arguments.source_commit,
                    source_tree=arguments.source_tree,
                    release_index_sha256=arguments.release_index_sha256,
                    archive_sha256=arguments.archive_sha256,
                    artifact_manifest_path=Path(arguments.artifact_manifest),
                    wheel_path=Path(arguments.wheel),
                    runtime_requirements_path=Path(arguments.runtime_requirements),
                    uv_lock_path=Path(arguments.uv_lock),
                    plugin_release_manifest_sha256=(
                        arguments.plugin_release_manifest_sha256
                    ),
                    verifier_path=Path(arguments.verifier),
                    ownership_manifest_path=Path(arguments.ownership_manifest),
                ),
            }
        elif arguments.command == "verify-runtime":
            receipt = verify_runtime(
                Path(arguments.runtime_dir),
                Path(arguments.launcher),
                expected_release_id=arguments.release_id,
                allow_staging=arguments.allow_staging,
            )
            result = {"ok": True, "receipt": receipt}
        elif arguments.command == "verify-artifact-runtime":
            receipt = verify_artifact_runtime(
                Path(arguments.runtime_dir),
                expected_release_id=arguments.release_id,
                expected_transaction_id=arguments.transaction_id,
                allow_staging=arguments.allow_staging,
            )
            result = {"ok": True, "receipt": receipt}
        elif arguments.command == "remove-owned":
            result = remove_owned(Path(arguments.runtime_root))
        elif arguments.command == "remove-owned-release":
            result = remove_owned_release(Path(arguments.release_path))
        elif arguments.command == "launch-cli":
            launch_arguments = list(arguments.arguments)
            if launch_arguments[:1] == ["--"]:
                launch_arguments = launch_arguments[1:]
            launch_artifact_runtime(
                Path(arguments.runtime), "cli", launch_arguments
            )
            raise AssertionError("exec returned unexpectedly")
        else:
            launch_arguments = list(arguments.arguments)
            if launch_arguments[:1] == ["--"]:
                launch_arguments = launch_arguments[1:]
            if arguments.runtime is not None:
                if arguments.runtime_dir is not None or arguments.launcher is not None or arguments.release_id is not None:
                    raise IntegrityError("artifact MCP launch arguments are ambiguous")
                launch_artifact_runtime(
                    Path(arguments.runtime), "mcp", launch_arguments
                )
            else:
                if arguments.runtime_dir is None or arguments.launcher is None or arguments.release_id is None:
                    raise IntegrityError("legacy MCP launch identity is incomplete")
                launch_mcp(
                    Path(arguments.runtime_dir),
                    Path(arguments.launcher),
                    arguments.release_id,
                    launch_arguments,
                )
            raise AssertionError("exec returned unexpectedly")
    except (IntegrityError, OSError, ValueError) as exc:
        if arguments.command in {"launch-cli", "launch-mcp"}:
            message = str(exc).replace("\r", " ").replace("\n", " ")[:512]
            sys.stderr.write(
                "Dev Flow managed runtime verification failed; "
                "run the installer again to repair it: {}\n".format(message)
            )
        else:
            _write_json_result({"ok": False, "error": str(exc)})
        return 1
    _write_json_result(result)
    return 0


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
