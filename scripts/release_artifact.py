#!/usr/bin/env python3
"""Verify and acquire a Dev Flow versioned release artifact.

This module is deliberately self-contained and standard-library only.  Release
bootstraps embed these bytes and run Phase A before any artifact code executes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Mapping, NamedTuple, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


INDEX_SCHEMA = "dev-flow-release-index/1.0.0"
ARTIFACT_SCHEMA = "dev-flow-release-artifact/1.0.0"
BOOTSTRAP_SCHEMA = "dev-flow-release-bootstrap/1.0.0"
CANONICAL_REPOSITORY = "Innocent-children/dev-flow-orchestrator"
PRODUCT_NAME = "dev-flow-orchestrator"
PROJECT_WHEEL_NAME = "dev_flow_orchestrator"
MANIFEST_NAME = "release-manifest.json"

# These bootstrap-owned values are hard ceilings.  An index may only lower
# them.  Length limits count ASCII characters, which are also UTF-8 bytes.
HARD_LIMITS: dict[str, int] = {
    "index_bytes": 256 * 1024,
    "manifest_bytes": 16 * 1024 * 1024,
    "archive_bytes": 256 * 1024 * 1024,
    "entry_count": 20_000,
    "component_length": 120,
    "path_length": 512,
    "nesting_depth": 16,
    "file_bytes": 64 * 1024 * 1024,
    "total_bytes": 256 * 1024 * 1024,
}

_INDEX_FIELDS = {
    "schema",
    "artifact_schema",
    "repository",
    "version",
    "source_commit",
    "source_tree",
    "archive",
    "manifest_sha256",
    "limits",
}
_ARCHIVE_FIELDS = {"name", "size", "sha256"}
_MANIFEST_FIELDS = {"schema", "version", "entries"}
_DIRECTORY_ENTRY_FIELDS = {"path", "type", "mode"}
_FILE_ENTRY_FIELDS = {"path", "type", "mode", "size", "sha256"}
_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_HEX = re.compile(r"^[0-9a-f]+$")
_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_WINDOWS_DEVICE = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)
_WHEEL = re.compile(
    r"^dev_flow_orchestrator-(?P<version>[0-9]+\.[0-9]+\.[0-9]+)-py3-none-any\.whl$"
)
_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?:\[(?P<extras>[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*)\])?"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)"
    r"(?:\s*;\s*(?P<marker>[A-Za-z0-9_.'\"<>=!~(), +\-]+))?\s+\\$"
)
_REQUIREMENT_HASH = re.compile(r"^\s+--hash=sha256:([0-9a-f]{64})(?:\s+\\)?$")
_PHASE_B_USER_OPTIONS = frozenset(
    {
        "--runtime-root",
        "--bin-dir",
        "--marketplace-file",
        "--codex-home",
        "--data-root",
        "--lock-timeout",
    }
)
_BOOTSTRAP_IDENTITY_OPTIONS = frozenset(
    {
        "--repository",
        "--version",
        "--archive-name",
        "--index-sha256",
    }
)


class ReleaseArtifactError(RuntimeError):
    """Raised when release bytes cannot be proven to satisfy the contract."""


class BootstrapResult(NamedTuple):
    returncode: int
    retained_paths: tuple[str, ...] = ()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key: {}".format(key))
        value[key] = item
    return value


def strict_json_bytes(raw: bytes, *, maximum: int, label: str) -> object:
    if not isinstance(raw, bytes):
        raise ReleaseArtifactError("{} must be bytes".format(label))
    if len(raw) > maximum:
        raise ReleaseArtifactError("{} exceeds the supported byte limit".format(label))
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError("non-finite JSON number: {}".format(item))
            ),
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ReleaseArtifactError("{} is not strict UTF-8 JSON".format(label)) from exc


def canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReleaseArtifactError("value is not canonical JSON") from exc


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path, *, maximum: int | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(128 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if maximum is not None and size > maximum:
                    raise ReleaseArtifactError("file exceeds the supported byte limit")
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseArtifactError("{} cannot be read".format(path)) from exc
    return size, digest.hexdigest()


def _object(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ReleaseArtifactError("{} fields are invalid".format(label))
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseArtifactError("{} is invalid".format(label))
    return value


def _integer(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReleaseArtifactError("{} is outside the supported range".format(label))
    return value


def _digest(value: object, label: str) -> str:
    value = _string(value, label)
    if len(value) != 64 or _HEX.fullmatch(value) is None:
        raise ReleaseArtifactError("{} must be lowercase SHA-256".format(label))
    return value


def _git_oid(value: object, label: str) -> str:
    value = _string(value, label)
    if len(value) not in {40, 64} or _HEX.fullmatch(value) is None:
        raise ReleaseArtifactError("{} must be a lowercase Git object ID".format(label))
    return value


def validate_version(value: object) -> str:
    value = _string(value, "release version")
    if _SEMVER.fullmatch(value) is None:
        raise ReleaseArtifactError("release version must be MAJOR.MINOR.PATCH")
    return value


def portable_path_parts(path: object, *, limits: Mapping[str, int] = HARD_LIMITS) -> tuple[str, ...]:
    path = _string(path, "artifact path")
    if len(path) > limits["path_length"]:
        raise ReleaseArtifactError("artifact path exceeds the supported length")
    if path.startswith("/") or path.startswith("\\") or "\\" in path or ":" in path:
        raise ReleaseArtifactError("artifact path is absolute, drive-qualified, or ambiguous")
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in path):
        raise ReleaseArtifactError("artifact path is not portable ASCII")
    components = path.split("/")
    if len(components) > limits["nesting_depth"]:
        raise ReleaseArtifactError("artifact path exceeds the supported nesting depth")
    for component in components:
        if (
            not component
            or component in {".", ".."}
            or len(component) > limits["component_length"]
            or component.endswith((".", " "))
            or _COMPONENT.fullmatch(component) is None
            or _WINDOWS_DEVICE.fullmatch(component) is not None
        ):
            raise ReleaseArtifactError("artifact path component is not portable: {}".format(component))
    return tuple(components)


def portable_path_key(path: object, *, limits: Mapping[str, int] = HARD_LIMITS) -> str:
    # The accepted grammar is ASCII, so lower() is an exact ASCII collision key.
    return "/".join(portable_path_parts(path, limits=limits)).lower()


def validate_limits(value: object) -> dict[str, int]:
    value = _object(value, set(HARD_LIMITS), "release limits")
    result: dict[str, int] = {}
    for name, hard_cap in HARD_LIMITS.items():
        result[name] = _integer(value.get(name), name, minimum=1, maximum=hard_cap)
    return result


def validate_release_index(value: object) -> dict[str, object]:
    value = _object(value, _INDEX_FIELDS, "release index")
    if value.get("schema") != INDEX_SCHEMA or value.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise ReleaseArtifactError("release index schema is invalid")
    version = validate_version(value.get("version"))
    repository = _string(value.get("repository"), "repository")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise ReleaseArtifactError("repository identity is invalid")
    archive = _object(value.get("archive"), _ARCHIVE_FIELDS, "archive identity")
    expected_archive_name = "{}-{}.tar.gz".format(PRODUCT_NAME, version)
    if archive.get("name") != expected_archive_name:
        raise ReleaseArtifactError("archive name does not match the release version")
    limits = validate_limits(value.get("limits"))
    archive_size = _integer(
        archive.get("size"),
        "archive size",
        minimum=1,
        maximum=limits["archive_bytes"],
    )
    return {
        "schema": INDEX_SCHEMA,
        "artifact_schema": ARTIFACT_SCHEMA,
        "repository": repository,
        "version": version,
        "source_commit": _git_oid(value.get("source_commit"), "source commit"),
        "source_tree": _git_oid(value.get("source_tree"), "source tree"),
        "archive": {
            "name": expected_archive_name,
            "size": archive_size,
            "sha256": _digest(archive.get("sha256"), "archive digest"),
        },
        "manifest_sha256": _digest(value.get("manifest_sha256"), "manifest digest"),
        "limits": limits,
    }


def verify_release_index_bytes(
    raw: bytes,
    expected_sha256: str,
    expected_repository: str,
    expected_version: str,
    expected_archive_name: str,
) -> dict[str, object]:
    """Digest-check raw index bytes before strict parsing and identity checks."""

    expected_sha256 = _digest(expected_sha256, "expected index digest")
    if sha256_bytes(raw) != expected_sha256:
        raise ReleaseArtifactError("release index digest mismatch")
    value = strict_json_bytes(raw, maximum=HARD_LIMITS["index_bytes"], label="release index")
    index = validate_release_index(value)
    if index["repository"] != expected_repository:
        raise ReleaseArtifactError("release index repository mismatch")
    if index["version"] != expected_version:
        raise ReleaseArtifactError("release index version mismatch")
    archive = index["archive"]
    assert isinstance(archive, Mapping)
    if archive["name"] != expected_archive_name:
        raise ReleaseArtifactError("release index archive name mismatch")
    return index


def validate_release_manifest(value: object, *, version: str, limits: Mapping[str, int]) -> dict[str, object]:
    value = _object(value, _MANIFEST_FIELDS, "release manifest")
    if value.get("schema") != ARTIFACT_SCHEMA:
        raise ReleaseArtifactError("release manifest schema is invalid")
    if value.get("version") != version:
        raise ReleaseArtifactError("release manifest version mismatch")
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ReleaseArtifactError("release manifest entries are invalid")
    if len(raw_entries) > limits["entry_count"]:
        raise ReleaseArtifactError("release manifest has too many entries")
    entries: list[dict[str, object]] = []
    paths: set[str] = set()
    collision_keys: set[str] = set()
    total = 0
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ReleaseArtifactError("release manifest entry is not an object")
        entry_type = raw_entry.get("type")
        fields = _DIRECTORY_ENTRY_FIELDS if entry_type == "directory" else _FILE_ENTRY_FIELDS
        entry = _object(raw_entry, fields, "release manifest entry")
        path = _string(entry.get("path"), "manifest entry path")
        portable_path_parts(path, limits=limits)
        if path == MANIFEST_NAME:
            raise ReleaseArtifactError("release manifest must exclude itself")
        key = portable_path_key(path, limits=limits)
        if path in paths or key in collision_keys:
            raise ReleaseArtifactError("release manifest contains a duplicate or case collision")
        paths.add(path)
        collision_keys.add(key)
        if entry_type == "directory":
            if entry.get("mode") != 0o755:
                raise ReleaseArtifactError("directory mode must be 0755")
            normalized = {"path": path, "type": "directory", "mode": 0o755}
        elif entry_type == "file":
            mode = entry.get("mode")
            if mode not in {0o644, 0o755}:
                raise ReleaseArtifactError("file mode is outside the supported profile")
            size = _integer(
                entry.get("size"), "manifest file size", minimum=0, maximum=limits["file_bytes"]
            )
            total += size
            if total > limits["total_bytes"]:
                raise ReleaseArtifactError("release manifest content exceeds the supported byte limit")
            normalized = {
                "path": path,
                "type": "file",
                "mode": mode,
                "size": size,
                "sha256": _digest(entry.get("sha256"), "manifest file digest"),
            }
        else:
            raise ReleaseArtifactError("release manifest entry type is unsupported")
        entries.append(normalized)
    if [entry["path"] for entry in entries] != sorted(paths, key=lambda item: item.encode("ascii")):
        raise ReleaseArtifactError("release manifest entries are not in canonical path order")
    directory_paths = {str(entry["path"]) for entry in entries if entry["type"] == "directory"}
    for entry in entries:
        parts = PurePosixPath(str(entry["path"])).parts
        for depth in range(1, len(parts)):
            if "/".join(parts[:depth]) not in directory_paths:
                raise ReleaseArtifactError("release manifest has an undeclared directory ancestor")
    return {"schema": ARTIFACT_SCHEMA, "version": version, "entries": entries}


def _expected_mode(path: str, is_directory: bool) -> int:
    if is_directory:
        return 0o755
    # Versioned Python entry points and POSIX helpers are the only executable
    # payload members. PowerShell/cmd assets remain ordinary data files.
    if path.startswith("lifecycle/") and path.endswith((".py", ".sh")):
        return 0o755
    if path.startswith("plugin/scripts/") and not path.endswith((".ps1", ".cmd", ".json")):
        return 0o755
    return 0o644


def _ustar_text(field: bytes, label: str) -> str:
    """Decode one fixed-width USTAR text field without extension semantics."""

    head, separator, tail = field.partition(b"\0")
    if separator and tail.strip(b"\0"):
        raise ReleaseArtifactError("{} has non-NUL padding".format(label))
    try:
        return head.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ReleaseArtifactError("{} is not portable ASCII".format(label)) from exc


def _ustar_octal(field: bytes, label: str) -> int:
    """Parse the portable octal numeric form and reject GNU base-256 values."""

    if field[:1] and field[0] & 0x80:
        raise ReleaseArtifactError("{} uses an unsupported base-256 value".format(label))
    value = field.strip(b" \0")
    if not value:
        return 0
    if any(character not in b"01234567" for character in value):
        raise ReleaseArtifactError("{} is not a portable octal value".format(label))
    return int(value, 8)


def _read_exact_bounded(stream: Any, size: int, *, consumed: list[int], maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(min(128 * 1024, remaining))
        if not chunk:
            raise ReleaseArtifactError("compressed tar stream is truncated")
        consumed[0] += len(chunk)
        if consumed[0] > maximum:
            raise ReleaseArtifactError("expanded tar stream exceeds the supported byte limit")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _inspect_ustar_headers(archive_path: Path, *, limits: Mapping[str, int]) -> None:
    """Read physical tar headers so transparent tarfile extensions cannot hide.

    ``tarfile`` intentionally consumes GNU long-name and PAX records before it
    exposes logical members. Phase A therefore performs this small USTAR scan
    first and accepts only physical regular-file and directory headers.
    """

    maximum_stream = (
        int(limits["total_bytes"])
        + (int(limits["entry_count"]) + 2) * 1024
        + 10 * 1024
    )
    consumed = [0]
    entries = 0
    total = 0
    zero_blocks = 0
    try:
        with gzip.open(archive_path, "rb") as stream:
            while True:
                header = stream.read(512)
                if not header:
                    raise ReleaseArtifactError("tar stream is missing its end marker")
                consumed[0] += len(header)
                if consumed[0] > maximum_stream:
                    raise ReleaseArtifactError(
                        "expanded tar stream exceeds the supported byte limit"
                    )
                if len(header) != 512:
                    raise ReleaseArtifactError("tar header is truncated")
                if header == b"\0" * 512:
                    zero_blocks += 1
                    if zero_blocks == 2:
                        break
                    continue
                if zero_blocks:
                    raise ReleaseArtifactError("tar end marker is incomplete")
                entries += 1
                if entries > int(limits["entry_count"]) + 2:
                    raise ReleaseArtifactError("archive has too many physical entries")
                if header[257:263] != b"ustar\0" or header[263:265] != b"00":
                    raise ReleaseArtifactError("tar header format is unsupported")
                type_flag = header[156:157]
                if type_flag not in {b"\0", tarfile.REGTYPE, tarfile.DIRTYPE}:
                    raise ReleaseArtifactError(
                        "tar extensions, links and special headers are unsupported"
                    )
                _ustar_text(header[0:100], "tar member name")
                _ustar_text(header[345:500], "tar member prefix")
                size = _ustar_octal(header[124:136], "tar member size")
                stored_checksum = _ustar_octal(header[148:156], "tar header checksum")
                computed_checksum = sum(header[:148]) + (8 * ord(" ")) + sum(header[156:])
                if stored_checksum != computed_checksum:
                    raise ReleaseArtifactError("tar header checksum is invalid")
                if type_flag == tarfile.DIRTYPE:
                    if size != 0:
                        raise ReleaseArtifactError("tar directory header has content")
                else:
                    if size > int(limits["file_bytes"]):
                        raise ReleaseArtifactError(
                            "archive member exceeds the supported byte limit"
                        )
                    total += size
                    if total > int(limits["total_bytes"]):
                        raise ReleaseArtifactError(
                            "archive content exceeds the supported byte limit"
                        )
                padded_size = ((size + 511) // 512) * 512
                if padded_size:
                    _read_exact_bounded(
                        stream,
                        padded_size,
                        consumed=consumed,
                        maximum=maximum_stream,
                    )
            while True:
                chunk = stream.read(128 * 1024)
                if not chunk:
                    break
                consumed[0] += len(chunk)
                if consumed[0] > maximum_stream:
                    raise ReleaseArtifactError(
                        "expanded tar stream exceeds the supported byte limit"
                    )
                if chunk.strip(b"\0"):
                    raise ReleaseArtifactError("tar stream has content after its end marker")
    except (EOFError, OSError) as exc:
        raise ReleaseArtifactError("compressed tar stream is invalid") from exc


def _tar_inventory(
    archive: tarfile.TarFile,
    *,
    version: str,
    limits: Mapping[str, int],
) -> tuple[str, list[tuple[tarfile.TarInfo, str]]]:
    if archive.pax_headers:
        raise ReleaseArtifactError("global tar extensions are unsupported")
    members = archive.getmembers()
    if len(members) > limits["entry_count"] + 2:
        raise ReleaseArtifactError("archive has too many entries")
    root = "{}-{}".format(PRODUCT_NAME, version)
    selected: list[tuple[tarfile.TarInfo, str]] = []
    seen: set[str] = set()
    collision_keys: set[str] = set()
    total = 0
    root_seen = False
    for member in members:
        if member.pax_headers or member.type in {
            tarfile.GNUTYPE_LONGNAME,
            tarfile.GNUTYPE_LONGLINK,
            tarfile.GNUTYPE_SPARSE,
            tarfile.XHDTYPE,
            tarfile.XGLTYPE,
        }:
            raise ReleaseArtifactError("tar extensions are unsupported")
        if member.type not in {tarfile.REGTYPE, tarfile.DIRTYPE}:
            raise ReleaseArtifactError("archive links and special members are unsupported")
        if (
            member.uid != 0
            or member.gid != 0
            or member.uname != ""
            or member.gname != ""
            or member.mtime != 0
            or member.linkname != ""
            or member.devmajor != 0
            or member.devminor != 0
        ):
            raise ReleaseArtifactError("archive member metadata is outside the supported tar profile")
        name = member.name[:-1] if member.name.endswith("/") else member.name
        portable_path_parts(name, limits={**limits, "nesting_depth": limits["nesting_depth"] + 1})
        if name == root:
            if not member.isdir() or root_seen:
                raise ReleaseArtifactError("archive top-level directory is invalid")
            if stat.S_IMODE(member.mode) != 0o755:
                raise ReleaseArtifactError("archive root mode is invalid")
            root_seen = True
            continue
        prefix = root + "/"
        if not name.startswith(prefix):
            raise ReleaseArtifactError("archive contains content outside its one top-level directory")
        relative = name[len(prefix) :]
        portable_path_parts(relative, limits=limits)
        key = portable_path_key(relative, limits=limits)
        if relative in seen or key in collision_keys:
            raise ReleaseArtifactError("archive contains a duplicate or case-colliding path")
        seen.add(relative)
        collision_keys.add(key)
        expected_mode = _expected_mode(relative, member.isdir())
        if stat.S_IMODE(member.mode) != expected_mode:
            raise ReleaseArtifactError("archive member mode is invalid: {}".format(relative))
        if member.isfile():
            if member.size < 0 or member.size > limits["file_bytes"]:
                raise ReleaseArtifactError("archive member exceeds the supported byte limit")
            if relative == MANIFEST_NAME and member.size > limits["manifest_bytes"]:
                raise ReleaseArtifactError("release manifest exceeds the supported byte limit")
            total += member.size
            if total > limits["total_bytes"]:
                raise ReleaseArtifactError("archive content exceeds the supported byte limit")
        selected.append((member, relative))
    if not root_seen:
        raise ReleaseArtifactError("archive top-level directory is missing")
    directories = {relative for member, relative in selected if member.isdir()}
    for _member, relative in selected:
        parts = PurePosixPath(relative).parts
        for depth in range(1, len(parts)):
            if "/".join(parts[:depth]) not in directories:
                raise ReleaseArtifactError("archive member has an undeclared directory ancestor")
    return root, selected


def validate_artifact_topology(root: Path, *, version: str) -> dict[str, str]:
    required_files = (
        "plugin/.codex-plugin/plugin.json",
        "plugin/.mcp.json",
        "plugin/skills/dev-flow/SKILL.md",
        "runtime-requirements.txt",
        "uv.lock",
        "lifecycle/release_lifecycle.py",
        "lifecycle/manage_runtime.py",
        "lifecycle/runtime_integrity.py",
        "lifecycle/validate_installed_stage1.py",
        "lifecycle/release_artifact.py",
        "lifecycle/release_commands.py",
        "lifecycle/release_resolver.py",
        "lifecycle/lifecycle_state.py",
        "lifecycle/lifecycle_machine.py",
        "lifecycle/legacy_migration.py",
        "lifecycle/legacy_predecessor.json",
        "lifecycle/render_dispatchers.py",
        "lifecycle/stable_dispatcher.py",
        "lifecycle/uninstall_driver.py",
    )
    for relative in required_files:
        path = root.joinpath(*relative.split("/"))
        if not path.is_file() or path.is_symlink():
            raise ReleaseArtifactError("required artifact file is missing: {}".format(relative))
    skills_root = root / "plugin" / "skills" / "dev-flow"
    if not any(path.is_file() and not path.is_symlink() for path in skills_root.rglob("*")):
        raise ReleaseArtifactError("bundled dev-flow Skill is empty")
    wheels_root = root / "wheels"
    wheel_files = sorted(path for path in wheels_root.iterdir() if path.is_file()) if wheels_root.is_dir() else []
    if len(wheel_files) != 1 or _WHEEL.fullmatch(wheel_files[0].name) is None:
        raise ReleaseArtifactError("artifact must contain exactly one pure-Python project wheel")
    match = _WHEEL.fullmatch(wheel_files[0].name)
    assert match is not None
    if match.group("version") != version:
        raise ReleaseArtifactError("project wheel version does not match the release")
    for path in root.rglob("*"):
        if path.is_file() and (path.name.endswith((".tar.gz", ".zip")) or path.suffix == ".whl"):
            if path != wheel_files[0]:
                raise ReleaseArtifactError("artifact contains an undeclared distribution")
    requirements = (root / "runtime-requirements.txt").read_text(encoding="utf-8")
    validate_requirements_text(requirements)
    return {
        "plugin_root": str((root / "plugin").resolve()),
        "wheel_path": str(wheel_files[0].resolve()),
        "requirements_path": str((root / "runtime-requirements.txt").resolve()),
        "lock_path": str((root / "uv.lock").resolve()),
        "lifecycle_root": str((root / "lifecycle").resolve()),
    }


def verify_extracted_artifact(
    root: Path,
    index_model: Mapping[str, object],
) -> dict[str, object]:
    """Re-verify one live extracted artifact against its index-bound manifest.

    This is the Phase B time-of-use boundary.  It observes every current
    descendant without following links or reparse points and does not accept a
    manifest as evidence for bytes that were not actually inspected.
    """

    index = validate_release_index(index_model)
    limits = index["limits"]
    assert isinstance(limits, Mapping)
    version = str(index["version"])
    root = Path(os.path.abspath(root))
    if root.name != "{}-{}".format(PRODUCT_NAME, version):
        raise ReleaseArtifactError("verified artifact root name is invalid")
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise ReleaseArtifactError("verified artifact root is unavailable") from exc
    root_reparse = bool(
        getattr(root_metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or root_reparse
    ):
        raise ReleaseArtifactError("verified artifact root is linked, reparsed, or special")

    manifest_path = root / MANIFEST_NAME
    try:
        manifest_metadata = manifest_path.lstat()
    except OSError as exc:
        raise ReleaseArtifactError("embedded release manifest is unavailable") from exc
    manifest_reparse = bool(
        getattr(manifest_metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if (
        not stat.S_ISREG(manifest_metadata.st_mode)
        or stat.S_ISLNK(manifest_metadata.st_mode)
        or manifest_reparse
        or stat.S_IMODE(manifest_metadata.st_mode) != 0o644
        or manifest_metadata.st_size > int(limits["manifest_bytes"])
    ):
        raise ReleaseArtifactError("embedded release manifest identity is invalid")
    try:
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ReleaseArtifactError("embedded release manifest cannot be read") from exc
    manifest_digest = sha256_bytes(manifest_raw)
    if manifest_digest != index["manifest_sha256"]:
        raise ReleaseArtifactError("release manifest digest mismatch")
    manifest = validate_release_manifest(
        strict_json_bytes(
            manifest_raw,
            maximum=int(limits["manifest_bytes"]),
            label="release manifest",
        ),
        version=version,
        limits=limits,
    )
    expected = {str(entry["path"]): entry for entry in manifest["entries"]}
    observed: dict[str, dict[str, object]] = {}
    collision_keys: set[str] = set()
    pending = [root]
    total_bytes = 0
    while pending:
        parent = pending.pop()
        try:
            children = sorted(parent.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ReleaseArtifactError("extracted inventory cannot be enumerated") from exc
        directories: list[Path] = []
        for path in children:
            relative = path.relative_to(root).as_posix()
            if relative == MANIFEST_NAME:
                continue
            portable_path_parts(relative, limits=limits)
            collision_key = portable_path_key(relative, limits=limits)
            if relative in observed or collision_key in collision_keys:
                raise ReleaseArtifactError(
                    "extracted inventory contains a duplicate or case-colliding path"
                )
            collision_keys.add(collision_key)
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ReleaseArtifactError(
                    "extracted inventory entry cannot be inspected"
                ) from exc
            reparse = bool(
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            if stat.S_ISLNK(metadata.st_mode) or reparse:
                raise ReleaseArtifactError(
                    "extracted inventory contains a link or reparse point"
                )
            if stat.S_ISDIR(metadata.st_mode):
                entry: dict[str, object] = {
                    "path": relative,
                    "type": "directory",
                    "mode": stat.S_IMODE(metadata.st_mode),
                }
                directories.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                entry_size, entry_digest = sha256_file(
                    path,
                    maximum=int(limits["file_bytes"]),
                )
                total_bytes += entry_size
                if total_bytes > int(limits["total_bytes"]):
                    raise ReleaseArtifactError(
                        "extracted inventory exceeds the supported byte limit"
                    )
                entry = {
                    "path": relative,
                    "type": "file",
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "size": entry_size,
                    "sha256": entry_digest,
                }
            else:
                raise ReleaseArtifactError(
                    "extracted inventory contains a special entry"
                )
            observed[relative] = entry
            if len(observed) > int(limits["entry_count"]):
                raise ReleaseArtifactError("extracted inventory has too many entries")
        pending.extend(reversed(directories))
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        changed = sorted(
            path
            for path in set(expected) & set(observed)
            if expected[path] != observed[path]
        )
        raise ReleaseArtifactError(
            "release inventory mismatch (missing={}, extra={}, changed={})".format(
                missing,
                extra,
                changed,
            )
        )
    topology = validate_artifact_topology(root, version=version)
    return {
        "root": str(root.resolve()),
        "release_id": "v{}-{}".format(version, manifest_digest[:16]),
        "index": index,
        "manifest": manifest,
        "manifest_sha256": manifest_digest,
        "inventory": manifest["entries"],
        "topology": topology,
    }


def validate_requirements_text(document: str) -> None:
    if not isinstance(document, str) or not document.strip():
        raise ReleaseArtifactError("runtime requirements are empty")
    current_requirement: str | None = None
    current_hashes: set[str] = set()
    saw_requirement = False

    def finish_requirement() -> None:
        nonlocal current_requirement, current_hashes
        if current_requirement is not None and not current_hashes:
            raise ReleaseArtifactError("every runtime requirement must be hash-locked")
        current_requirement = None
        current_hashes = set()

    for raw_line in document.splitlines():
        if not raw_line.strip():
            finish_requirement()
            continue
        hash_match = _REQUIREMENT_HASH.fullmatch(raw_line)
        if hash_match is not None:
            if current_requirement is None:
                raise ReleaseArtifactError("requirement hash has no exact requirement")
            digest = hash_match.group(1)
            _digest(digest, "requirement hash")
            if digest in current_hashes:
                raise ReleaseArtifactError("runtime requirement contains a duplicate hash")
            current_hashes.add(digest)
            continue
        if raw_line[:1].isspace():
            raise ReleaseArtifactError("runtime requirements contain an unsupported continuation")
        finish_requirement()
        match = _REQUIREMENT.fullmatch(raw_line)
        if match is None:
            raise ReleaseArtifactError(
                "runtime requirements must contain only exact registry versions and SHA-256 hashes"
            )
        marker = match.group("marker")
        if marker is not None and ("--" in marker or "@" in marker or "/" in marker or "\\" in marker):
            raise ReleaseArtifactError("runtime requirement marker is unsafe")
        current_requirement = match.group("name")
        saw_requirement = True
    finish_requirement()
    if not saw_requirement:
        raise ReleaseArtifactError("runtime requirements contain no requirements")


def _safe_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ReleaseArtifactError("extraction destination must be newly absent")
    parent = Path(os.path.abspath(destination.parent))
    parts = parent.parts
    current = Path(parts[0])
    for component in parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ReleaseArtifactError("extraction destination ancestor is unavailable") from exc
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or reparse:
            raise ReleaseArtifactError(
                "extraction destination ancestor is linked, reparsed, or not a directory"
            )


def _ensure_regular_ancestors(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts[:-1]:
        current /= part
        metadata = current.lstat()
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or reparse:
            raise ReleaseArtifactError("extraction path has a linked or non-directory ancestor")


def _remove_extraction(destination: Path) -> None:
    if not destination.exists() or destination.is_symlink():
        return
    for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            pass
    try:
        destination.rmdir()
    except OSError:
        pass


def _cleanup_installer_staging(root: Path) -> tuple[str, ...]:
    """Remove only this bootstrap's bounded tree without following links."""

    if not os.path.lexists(root):
        return ()
    retained: list[str] = []
    directories: list[Path] = []
    pending = [root]
    visited = 0
    maximum = HARD_LIMITS["entry_count"] + 16
    while pending:
        directory = pending.pop()
        visited += 1
        if visited > maximum:
            retained.append(str(root))
            break
        try:
            metadata = directory.lstat()
        except OSError:
            retained.append(str(directory))
            continue
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or reparse:
            retained.append(str(directory))
            continue
        directories.append(directory)
        try:
            children = list(directory.iterdir())
        except OSError:
            retained.append(str(directory))
            continue
        if visited + len(children) > maximum:
            retained.append(str(directory))
            continue
        for child in children:
            try:
                child_metadata = child.lstat()
            except OSError:
                retained.append(str(child))
                continue
            child_reparse = bool(
                getattr(child_metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            if (
                stat.S_ISDIR(child_metadata.st_mode)
                and not stat.S_ISLNK(child_metadata.st_mode)
                and not child_reparse
            ):
                pending.append(child)
            elif stat.S_ISREG(child_metadata.st_mode) and not child_reparse:
                try:
                    child.unlink()
                except OSError:
                    retained.append(str(child))
            else:
                retained.append(str(child))
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            retained.append(str(directory))
    unique = tuple(sorted(set(retained)))
    return unique if len(unique) <= 128 else (str(root),)


def inspect_and_extract_artifact(
    archive_path: Path,
    destination: Path,
    index_model: Mapping[str, object],
) -> dict[str, object]:
    """Verify compressed bytes and all headers before exclusive extraction.

    ``destination`` must not exist. The function has no product-state side
    effects; on failure, it best-effort removes only the directory it created.
    """

    index = validate_release_index(index_model)
    limits = index["limits"]
    archive_identity = index["archive"]
    assert isinstance(limits, Mapping) and isinstance(archive_identity, Mapping)
    try:
        archive_metadata = archive_path.lstat()
    except OSError as exc:
        raise ReleaseArtifactError("release archive is unavailable") from exc
    reparse = bool(
        getattr(archive_metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if not stat.S_ISREG(archive_metadata.st_mode) or stat.S_ISLNK(archive_metadata.st_mode) or reparse:
        raise ReleaseArtifactError("release archive must be a regular non-reparse file")
    archive_path = Path(os.path.abspath(archive_path))
    size, digest = sha256_file(archive_path, maximum=limits["archive_bytes"])
    if size != archive_identity["size"] or digest != archive_identity["sha256"]:
        raise ReleaseArtifactError("release archive size or digest mismatch")
    version = str(index["version"])
    _inspect_ustar_headers(archive_path, limits=limits)
    _safe_destination(destination)
    destination_created = False
    try:
        with tarfile.open(archive_path, mode="r:gz", encoding="utf-8", errors="strict") as archive:
            root_name, members = _tar_inventory(archive, version=version, limits=limits)
            try:
                destination.mkdir(mode=0o700, parents=False, exist_ok=False)
            except FileExistsError as exc:
                raise ReleaseArtifactError(
                    "extraction destination lost its exclusive-creation race"
                ) from exc
            destination_created = True
            # mkdir applies the ambient umask.  The extraction container is
            # private installer staging, so establish its intended mode before
            # creating any archive-owned children beneath it.
            destination.chmod(0o700)
            release_root = destination / root_name
            release_root.mkdir(mode=0o755, exist_ok=False)
            release_root.chmod(0o755)
            for member, relative in members:
                if relative == MANIFEST_NAME:
                    continue
                path = release_root.joinpath(*portable_path_parts(relative, limits=limits))
                if member.isdir():
                    path.mkdir(mode=0o755, parents=False, exist_ok=False)
                    path.chmod(0o755)
                    continue
                _ensure_regular_ancestors(release_root, path)
                source = archive.extractfile(member)
                if source is None:
                    raise ReleaseArtifactError("archive member cannot be read")
                copied = 0
                digest_object = hashlib.sha256()
                with path.open("xb") as output:
                    while True:
                        chunk = source.read(128 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > member.size:
                            raise ReleaseArtifactError("archive member expanded beyond its header")
                        output.write(chunk)
                        digest_object.update(chunk)
                if copied != member.size:
                    raise ReleaseArtifactError("archive member size changed during extraction")
                path.chmod(_expected_mode(relative, False))
            manifest_member = next(
                (member for member, relative in members if relative == MANIFEST_NAME),
                None,
            )
            if manifest_member is None or not manifest_member.isfile():
                raise ReleaseArtifactError("embedded release manifest is missing")
            manifest_source = archive.extractfile(manifest_member)
            if manifest_source is None:
                raise ReleaseArtifactError("embedded release manifest cannot be read")
            manifest_path = release_root / MANIFEST_NAME
            manifest_raw = manifest_source.read(limits["manifest_bytes"] + 1)
            if len(manifest_raw) != manifest_member.size:
                raise ReleaseArtifactError("embedded release manifest size is invalid")
            with manifest_path.open("xb") as output:
                output.write(manifest_raw)
            manifest_path.chmod(0o644)
        return verify_extracted_artifact(release_root, index)
    except tarfile.TarError as exc:
        if destination_created:
            _remove_extraction(destination)
        raise ReleaseArtifactError("archive tar profile is invalid") from exc
    except Exception:
        if destination_created:
            _remove_extraction(destination)
        raise


class _HttpsRedirectsOnly(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        absolute = urljoin(req.full_url, newurl)
        if urlparse(absolute).scheme.lower() != "https":
            raise ReleaseArtifactError("download redirect target is not HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _download(
    url: str,
    destination: Path,
    *,
    maximum: int,
    opener: Any = None,
    collect: bool = True,
) -> bytes:
    if urlparse(url).scheme.lower() != "https":
        raise ReleaseArtifactError("release download URL is not HTTPS")
    selected_opener = opener or build_opener(_HttpsRedirectsOnly())
    try:
        response = selected_opener.open(Request(url, headers={"User-Agent": "dev-flow-bootstrap/1"}), timeout=60)
        try:
            final_url = response.geturl()
            if urlparse(final_url).scheme.lower() != "https":
                raise ReleaseArtifactError("release download resolved to a non-HTTPS URL")
            content_length = None
            headers = getattr(response, "headers", None)
            if headers is not None:
                content_length = headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length, 10)
                except (TypeError, ValueError) as exc:
                    raise ReleaseArtifactError(
                        "release download Content-Length is invalid"
                    ) from exc
                if declared_length < 0 or declared_length > maximum:
                    raise ReleaseArtifactError(
                        "release download exceeds the supported byte limit"
                    )
            content = bytearray()
            received = 0
            with destination.open("xb") as output:
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > maximum:
                        raise ReleaseArtifactError(
                            "release download exceeds the supported byte limit"
                        )
                    output.write(chunk)
                    if collect:
                        content.extend(chunk)
            return bytes(content)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except (HTTPError, URLError, OSError) as exc:
        raise ReleaseArtifactError("release download failed") from exc


def normalize_phase_b_user_args(arguments: Sequence[str]) -> tuple[str, ...]:
    """Validate and canonicalize the caller-controlled Phase B option suffix."""

    normalized: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if not isinstance(token, str) or not token.startswith("--") or token == "--":
            raise ReleaseArtifactError(
                "Phase A accepts only closed Phase B options; positional input is rejected"
            )
        option, separator, attached = token.partition("=")
        if option not in _PHASE_B_USER_OPTIONS:
            if option in _BOOTSTRAP_IDENTITY_OPTIONS or any(
                marker in option
                for marker in (
                    "artifact",
                    "archive",
                    "index",
                    "repository",
                    "release",
                    "source",
                    "transaction",
                    "version",
                )
            ):
                raise ReleaseArtifactError(
                    "Phase A caller cannot select artifact or release identity option: "
                    + option
                )
            raise ReleaseArtifactError(
                "Phase A option is outside the closed whitelist; abbreviations are disabled: "
                + option
            )
        if option in seen:
            raise ReleaseArtifactError(
                "Phase A rejects repeated Phase B option: " + option
            )
        seen.add(option)
        if separator:
            value = attached
        else:
            index += 1
            if index >= len(arguments):
                raise ReleaseArtifactError("Phase A option requires one value: " + option)
            value = arguments[index]
            if value.startswith("--"):
                raise ReleaseArtifactError("Phase A option requires one value: " + option)
        if not value or "\x00" in value:
            raise ReleaseArtifactError(
                "Phase A option value must be non-empty and contain no NUL: " + option
            )
        normalized.extend((option, value))
        index += 1
    return tuple(normalized)


def bootstrap(
    *,
    repository: str,
    version: str,
    archive_name: str,
    index_sha256: str,
    phase_b_args: Sequence[str] = (),
    opener: Any = None,
) -> BootstrapResult:
    version = validate_version(version)
    expected_archive = "{}-{}.tar.gz".format(PRODUCT_NAME, version)
    if archive_name != expected_archive:
        raise ReleaseArtifactError("bootstrap archive name is invalid")
    if repository != CANONICAL_REPOSITORY:
        raise ReleaseArtifactError("bootstrap repository is not canonical")
    normalized_phase_b_args = normalize_phase_b_user_args(phase_b_args)
    base_url = "https://github.com/{}/releases/download/v{}/".format(repository, version)
    temporary_name = tempfile.mkdtemp(prefix="dev-flow-acquire-")
    return_code: int | None = None
    failure: Exception | None = None
    try:
        # Resolve platform temporary-directory aliases (for example macOS
        # /var -> /private/var) before the no-link ancestor check.
        temporary = Path(temporary_name).resolve()
        index_path = temporary / "release-index.json"
        archive_path = temporary / archive_name
        extraction = temporary / "extracted"
        index_raw = _download(base_url + "release-index.json", index_path, maximum=HARD_LIMITS["index_bytes"], opener=opener)
        index = verify_release_index_bytes(index_raw, index_sha256, repository, version, archive_name)
        archive_identity = index["archive"]
        assert isinstance(archive_identity, Mapping)
        _download(
            base_url + archive_name,
            archive_path,
            maximum=int(archive_identity["size"]),
            opener=opener,
            collect=False,
        )
        verified = inspect_and_extract_artifact(archive_path, extraction, index)
        # Re-observe the complete live tree at the Phase A -> Phase B handoff.
        # This catches a replaced wheel or lifecycle helper before artifact code
        # is selected for execution; Phase B repeats the same check at time of
        # use before candidate construction.
        verified = verify_extracted_artifact(Path(str(verified["root"])), index)
        lifecycle = Path(str(verified["root"])) / "lifecycle" / "release_lifecycle.py"
        command = [
            sys.executable,
            "-B",
            "-I",
            "-S",
            str(lifecycle),
            "install",
            "--release-index",
            str(index_path),
            "--release-index-sha256",
            index_sha256,
            *normalized_phase_b_args,
        ]
        completed = subprocess.run(command, check=False)
        return_code = completed.returncode
    except Exception as exc:
        failure = exc
    finally:
        retained_paths = _cleanup_installer_staging(Path(temporary_name))
    if failure is not None:
        if retained_paths:
            raise ReleaseArtifactError(
                "{}; installer staging retained at {}".format(
                    failure, ", ".join(retained_paths)
                )
            ) from failure
        raise failure
    assert return_code is not None
    return BootstrapResult(return_code, retained_paths)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("bootstrap", allow_abbrev=False)
    command.add_argument("--repository", required=True)
    command.add_argument("--version", required=True)
    command.add_argument("--archive-name", required=True)
    command.add_argument("--index-sha256", required=True)
    command.add_argument("phase_b_args", nargs=argparse.REMAINDER)
    return parser


def _reject_repeated_bootstrap_identity(arguments: Sequence[str]) -> None:
    seen: set[str] = set()
    for token in arguments:
        if token == "--":
            break
        option = token.partition("=")[0]
        if option not in _BOOTSTRAP_IDENTITY_OPTIONS:
            continue
        if option in seen:
            raise ReleaseArtifactError(
                "Phase A rejects repeated bootstrap identity option: " + option
            )
        seen.add(option)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        selected_argv = list(sys.argv[1:] if argv is None else argv)
        _reject_repeated_bootstrap_identity(selected_argv)
        arguments = _parser().parse_args(selected_argv)
        phase_b_args = list(arguments.phase_b_args)
        if phase_b_args[:1] == ["--"]:
            phase_b_args.pop(0)
        result = bootstrap(
            repository=arguments.repository,
            version=arguments.version,
            archive_name=arguments.archive_name,
            index_sha256=arguments.index_sha256,
            phase_b_args=phase_b_args,
        )
        print(
            json.dumps(
                {
                    "ok": result.returncode == 0,
                    "phase": "phase-b",
                    "returncode": result.returncode,
                    "retained_paths": list(result.retained_paths),
                },
                sort_keys=True,
            )
        )
        return result.returncode
    except (OSError, ReleaseArtifactError, subprocess.SubprocessError, tarfile.TarError) as exc:
        print(json.dumps({"error": str(exc), "ok": False, "phase": "phase-a"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
