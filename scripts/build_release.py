#!/usr/bin/env python3
"""Build one deterministic, closed Dev Flow release asset set."""

from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
from email.policy import compat32
import gzip
import hashlib
import io
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
import tomllib
from typing import Any, Callable, Iterable, Mapping, Sequence
import zipfile

import release_artifact as artifact
import release_resolver as resolver


BUILDER_SCHEMA = "dev-flow-release-builder/1.0.0"
DEFAULT_CONFIG_NAME = "release-builder.json"
PLUGIN_SEAL_SCHEMA = "dev-flow-plugin-release/1.0.0"
CANONICAL_PLUGIN_FILES = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "scripts/dev_flow.py",
    "scripts/dev_flow_mcp.py",
    "scripts/dev_flow_mcp_launcher",
    "scripts/dev_flow_mcp_launcher.cmd",
    "scripts/dev_flow_python_launcher",
    "scripts/validate_installed_stage1.py",
)
CANONICAL_PLUGIN_TREES = ("skills/dev-flow",)
LIFECYCLE_FILES = (
    "release_lifecycle.py",
    "manage_runtime.py",
    "runtime_integrity.py",
    "validate_installed_stage1.py",
    "release_artifact.py",
    "release_commands.py",
    "release_resolver.py",
    "lifecycle_state.py",
    "lifecycle_machine.py",
    "legacy_migration.py",
    "legacy_predecessor.json",
    "render_dispatchers.py",
    "stable_dispatcher.py",
    "uninstall_driver.py",
)
_CONFIG_FIELDS = {
    "schema",
    "python",
    "uv",
    "build_backend",
    "tar_format",
    "gzip_profile",
}
_SECRET_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("AWS access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    (
        "generic credential literal",
        re.compile(
            rb"(?i)['\"]?(?:password|secret|token)['\"]?\s*[=:]\s*"
            rb"['\"][A-Za-z0-9_./+=:-]{12,}['\"]"
        ),
    ),
)
_LOCAL_PATH_PATTERNS = (
    re.compile(rb"/(?:Users|home)/[A-Za-z0-9._-]+/"),
    re.compile(rb"[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\"),
)
_BUILD_BACKEND_PIN = re.compile(r"^hatchling==(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_PROHIBITED_PURE_WHEEL_SUFFIXES = (
    ".dll",
    ".dylib",
    ".exe",
    ".pdb",
    ".pth",
    ".pyc",
    ".pyd",
    ".so",
)


class ReleaseBuildError(RuntimeError):
    """Raised when release production cannot prove its pinned inputs."""


def _run(
    runner: Callable[..., Any],
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = runner(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReleaseBuildError("command could not run: {}".format(command[0])) from exc
    if completed.returncode != 0:
        raise ReleaseBuildError(
            "command failed: {}: {}".format(" ".join(command), completed.stderr.strip())
        )
    return completed


def load_builder_config(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReleaseBuildError("release builder configuration cannot be read") from exc
    value = artifact.strict_json_bytes(raw, maximum=64 * 1024, label="release builder configuration")
    if not isinstance(value, Mapping) or set(value) != _CONFIG_FIELDS:
        raise ReleaseBuildError("release builder configuration fields are invalid")
    if value.get("schema") != BUILDER_SCHEMA:
        raise ReleaseBuildError("release builder configuration schema is invalid")
    expected = {
        "tar_format": "python-stdlib-ustar",
        "gzip_profile": "python-stdlib-mtime-zero",
    }
    for field, literal in expected.items():
        if value.get(field) != literal:
            raise ReleaseBuildError("release builder {} is unsupported".format(field))
    result: dict[str, str] = {}
    for field in sorted(_CONFIG_FIELDS):
        item = value.get(field)
        if not isinstance(item, str) or not item:
            raise ReleaseBuildError("release builder {} is invalid".format(field))
        result[field] = item
    if _BUILD_BACKEND_PIN.fullmatch(result["build_backend"]) is None:
        raise ReleaseBuildError("release builder build_backend is not an exact supported pin")
    return result


def validate_builder_environment(
    config: Mapping[str, str], *, root: Path, runner: Callable[..., Any] = subprocess.run
) -> None:
    observed_python = "{}.{}.{}".format(*sys.version_info[:3])
    if observed_python != config["python"]:
        raise ReleaseBuildError(
            "builder Python differs: expected {}, got {}".format(config["python"], observed_python)
        )
    completed = _run(runner, ["uv", "--version"], cwd=root)
    observed_uv = completed.stdout.strip().split()
    if len(observed_uv) < 2 or observed_uv[:2] != ["uv", config["uv"]]:
        raise ReleaseBuildError("builder uv version differs")
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        build_system = project["build-system"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise ReleaseBuildError("project build-system configuration is invalid") from exc
    if not isinstance(build_system, Mapping) or set(build_system) != {"requires", "build-backend"}:
        raise ReleaseBuildError("project build-system fields are not closed")
    if build_system.get("requires") != [config["build_backend"]]:
        raise ReleaseBuildError("project build requirement differs from the pinned builder")
    if build_system.get("build-backend") != "hatchling.build":
        raise ReleaseBuildError("project build backend is unsupported")


def validate_clean_tag(
    root: Path,
    version: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> tuple[str, str]:
    version = artifact.validate_version(version)
    root = root.resolve()
    status = _run(
        runner,
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored"],
        cwd=root,
    ).stdout
    disallowed = []
    for raw_line in status.splitlines():
        code = raw_line[:2]
        relative = raw_line[3:]
        if code == "!!" and _allowed_ignored_release_input(relative):
            continue
        disallowed.append(raw_line)
    if disallowed:
        raise ReleaseBuildError("release source must be exactly clean")
    head = _run(runner, ["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    tagged = _run(
        runner, ["git", "rev-parse", "v{}^{{commit}}".format(version)], cwd=root
    ).stdout.strip()
    if tagged != head:
        raise ReleaseBuildError("release source is not the exact v{} tag".format(version))
    tags = set(
        _run(runner, ["git", "tag", "--points-at", "HEAD"], cwd=root).stdout.splitlines()
    )
    if "v{}".format(version) not in tags:
        raise ReleaseBuildError("release tag is missing from HEAD")
    tree = _run(runner, ["git", "rev-parse", "HEAD^{tree}"], cwd=root).stdout.strip()
    # Reuse the closed OID grammar from the index validator.
    artifact._git_oid(head, "source commit")
    artifact._git_oid(tree, "source tree")
    return head, tree


def _allowed_ignored_release_input(relative: str) -> bool:
    normalized = relative.rstrip("/")
    return normalized in {".venv", ".DS_Store"} or normalized.startswith(
        (".venv/", "__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/")
    ) or "/__pycache__/" in normalized


def _safe_source_file(root: Path, relative: str) -> Path:
    artifact.portable_path_parts(relative)
    path = root.joinpath(*relative.split("/"))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ReleaseBuildError("allow-listed input is missing: {}".format(relative)) from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ReleaseBuildError("allow-listed input is not a regular file: {}".format(relative))
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ReleaseBuildError("allow-listed input escapes the source root") from exc
    return path


def _tree_files(root: Path, relative: str) -> list[tuple[str, Path]]:
    source_root = root.joinpath(*relative.split("/"))
    try:
        metadata = source_root.lstat()
    except OSError as exc:
        raise ReleaseBuildError("allow-listed input tree is missing: {}".format(relative)) from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ReleaseBuildError("allow-listed input tree is not a regular directory")
    result: list[tuple[str, Path]] = []
    for path in sorted(source_root.rglob("*")):
        child = path.relative_to(root).as_posix()
        child_metadata = path.lstat()
        if stat.S_ISDIR(child_metadata.st_mode) and not stat.S_ISLNK(child_metadata.st_mode):
            continue
        if not stat.S_ISREG(child_metadata.st_mode) or stat.S_ISLNK(child_metadata.st_mode):
            raise ReleaseBuildError("allow-listed tree contains a link or special entry")
        artifact.portable_path_parts(child)
        result.append((child, path))
    if not result:
        raise ReleaseBuildError("allow-listed input tree is empty")
    return result


def closed_plugin_inputs(root: Path) -> list[tuple[str, Path]]:
    selected = [(relative, _safe_source_file(root, relative)) for relative in CANONICAL_PLUGIN_FILES]
    for relative in CANONICAL_PLUGIN_TREES:
        selected.extend(_tree_files(root, relative))
    names = [name for name, _path in selected]
    if len(names) != len(set(names)):
        raise ReleaseBuildError("plugin input allow-list contains duplicates")
    return sorted(selected)


def scan_known_secrets_and_local_paths(
    inputs: Iterable[tuple[str, Path]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative, path in inputs:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ReleaseBuildError("release input cannot be scanned: {}".format(relative)) from exc
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(raw):
                findings.append({"kind": "known-secret", "path": relative, "pattern": label})
        for pattern in _LOCAL_PATH_PATTERNS:
            if pattern.search(raw):
                findings.append({"kind": "local-path", "path": relative, "pattern": pattern.pattern.decode()})
    return findings


def _ensure_staging_directories(root: Path, parent: Path) -> None:
    """Create contained staging directories with modes independent of umask."""

    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ReleaseBuildError("release staging destination escapes its root") from exc
    current = root
    for component in relative.parts:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o755, parents=False, exist_ok=False)
            current.chmod(0o755)
            continue
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise ReleaseBuildError("release staging parent is linked or not a directory")


def _copy_file(source: Path, destination: Path, *, mode: int, staging_root: Path) -> None:
    _ensure_staging_directories(staging_root, destination.parent)
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream, length=128 * 1024)
    destination.chmod(mode)


def _inventory(root: Path, *, exclude: Iterable[str] = ()) -> list[dict[str, object]]:
    excluded = set(exclude)
    entries: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            entries.append({"path": relative, "type": "directory", "mode": 0o755})
        elif stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            raw = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": artifact._expected_mode(relative, False),
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        else:
            raise ReleaseBuildError("staging contains a link or special entry")
    return entries


def _plugin_seal_inventory(plugin_root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(plugin_root.rglob("*")):
        relative = path.relative_to(plugin_root).as_posix()
        if relative == artifact.MANIFEST_NAME:
            continue
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            entries.append({"path": relative, "type": "directory", "mode": mode})
        elif stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        else:
            raise ReleaseBuildError("plugin staging contains a link or special entry")
    return entries


def _runtime_canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_plugin_seal(plugin_root: Path, source_commit: str, source_tree: str) -> dict[str, str]:
    entries = _plugin_seal_inventory(plugin_root)
    body = {"source_commit": source_commit, "source_tree": source_tree, "entries": entries}
    content_digest = hashlib.sha256(_runtime_canonical_json(body)).hexdigest()
    release_id = "r-{}-{}".format(source_commit[:12], content_digest[:16])
    manifest = {
        "schema": PLUGIN_SEAL_SCHEMA,
        "release_id": release_id,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "content_sha256": content_digest,
        "entries": entries,
    }
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path = plugin_root / artifact.MANIFEST_NAME
    path.write_bytes(raw)
    path.chmod(0o644)
    return {"release_id": release_id, "sha256": hashlib.sha256(raw).hexdigest()}


def validate_project_wheel(path: Path, *, version: str) -> dict[str, object]:
    expected_name = "dev_flow_orchestrator-{}-py3-none-any.whl".format(version)
    if path.name != expected_name or not path.is_file() or path.is_symlink():
        raise ReleaseBuildError("project wheel name or type is invalid")
    try:
        wheel_size = path.stat().st_size
    except OSError as exc:
        raise ReleaseBuildError("project wheel cannot be inspected") from exc
    if wheel_size <= 0 or wheel_size > artifact.HARD_LIMITS["file_bytes"]:
        raise ReleaseBuildError("project wheel exceeds the supported byte limit")
    dist_info = "dev_flow_orchestrator-{}.dist-info".format(version)
    allowed_roots = {"dev_flow_orchestrator", dist_info}
    try:
        with zipfile.ZipFile(path) as wheel:
            infos = wheel.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or not names:
                raise ReleaseBuildError("project wheel contains duplicate or no members")
            if len(infos) > artifact.HARD_LIMITS["entry_count"]:
                raise ReleaseBuildError("project wheel contains too many members")
            collision_keys: set[str] = set()
            member_types: dict[str, str] = {}
            total_size = 0
            for info in infos:
                name = info.filename[:-1] if info.filename.endswith("/") else info.filename
                artifact.portable_path_parts(name)
                key = artifact.portable_path_key(name)
                if key in collision_keys:
                    raise ReleaseBuildError("project wheel contains a case collision")
                collision_keys.add(key)
                if PurePosixPath(name).parts[0] not in allowed_roots:
                    raise ReleaseBuildError("project wheel contains an unexpected top-level member")
                if info.flag_bits & 0x1:
                    raise ReleaseBuildError("project wheel contains an encrypted member")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ReleaseBuildError("project wheel uses an unsupported compression method")
                if info.file_size < 0 or info.file_size > artifact.HARD_LIMITS["file_bytes"]:
                    raise ReleaseBuildError("project wheel member exceeds the supported byte limit")
                total_size += info.file_size
                if total_size > artifact.HARD_LIMITS["total_bytes"]:
                    raise ReleaseBuildError("project wheel expands beyond the supported byte limit")
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                expected_type = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
                if file_type not in {0, expected_type}:
                    raise ReleaseBuildError("project wheel contains a link or special member")
                member_type = "directory" if info.is_dir() else "file"
                member_types[name] = member_type
                for parent in PurePosixPath(name).parents:
                    parent_name = parent.as_posix()
                    if parent_name == ".":
                        break
                    if member_types.get(parent_name) == "file":
                        raise ReleaseBuildError("project wheel has a file as a member ancestor")
                if not info.is_dir() and name.lower().endswith(_PROHIBITED_PURE_WHEEL_SUFFIXES):
                    raise ReleaseBuildError("project wheel contains a non-pure or startup-control member")
            for name, member_type in member_types.items():
                if member_type == "file" and any(
                    other.startswith(name + "/") for other in member_types if other != name
                ):
                    raise ReleaseBuildError("project wheel has a file as a member ancestor")

            regular_infos = {info.filename: info for info in infos if not info.is_dir()}
            record_name = dist_info + "/RECORD"
            if record_name not in regular_infos:
                raise ReleaseBuildError("project wheel RECORD is missing")
            record_raw = wheel.read(regular_infos[record_name])
            if len(record_raw) > artifact.HARD_LIMITS["manifest_bytes"]:
                raise ReleaseBuildError("project wheel RECORD exceeds the supported byte limit")
            try:
                record_text = record_raw.decode("utf-8")
            except UnicodeError as exc:
                raise ReleaseBuildError("project wheel RECORD is not UTF-8") from exc
            record_entries: dict[str, tuple[str, str]] = {}
            for row in csv.reader(io.StringIO(record_text), strict=True):
                if len(row) != 3 or not row[0]:
                    raise ReleaseBuildError("project wheel RECORD row is invalid")
                artifact.portable_path_parts(row[0])
                if row[0] in record_entries:
                    raise ReleaseBuildError("project wheel RECORD contains a duplicate member")
                record_entries[row[0]] = (row[1], row[2])
            if set(record_entries) != set(regular_infos):
                raise ReleaseBuildError("project wheel RECORD does not declare the complete member set")
            for name, info in regular_infos.items():
                declared_hash, declared_size = record_entries[name]
                if name == record_name:
                    if declared_hash or declared_size:
                        raise ReleaseBuildError("project wheel RECORD self-entry must be unhashed")
                    continue
                if declared_size != str(info.file_size):
                    raise ReleaseBuildError("project wheel RECORD member size differs")
                if not declared_hash.startswith("sha256="):
                    raise ReleaseBuildError("project wheel RECORD member is not SHA-256 locked")
                encoded = declared_hash.removeprefix("sha256=")
                if re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded) is None:
                    raise ReleaseBuildError("project wheel RECORD SHA-256 is invalid")
                try:
                    expected_digest = base64.urlsafe_b64decode(encoded + "=")
                except (ValueError, TypeError) as exc:
                    raise ReleaseBuildError("project wheel RECORD SHA-256 is invalid") from exc
                digest = hashlib.sha256()
                with wheel.open(info) as member_stream:
                    while True:
                        chunk = member_stream.read(128 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                if digest.digest() != expected_digest:
                    raise ReleaseBuildError("project wheel RECORD member digest differs")
            wheel_metadata = BytesParser(policy=compat32).parsebytes(
                wheel.read(dist_info + "/WHEEL")
            )
            package_metadata = BytesParser(policy=compat32).parsebytes(
                wheel.read(dist_info + "/METADATA")
            )
            wheel.read("dev_flow_orchestrator/__init__.py")
    except artifact.ReleaseArtifactError as exc:
        raise ReleaseBuildError("project wheel member path is invalid") from exc
    except (OSError, KeyError, UnicodeError, csv.Error, zipfile.BadZipFile) as exc:
        raise ReleaseBuildError("project wheel is not a closed readable wheel") from exc
    if wheel_metadata.get_all("Root-Is-Purelib") != ["true"] or wheel_metadata.get_all("Tag") != [
        "py3-none-any"
    ]:
        raise ReleaseBuildError("project wheel is not pure Python py3-none-any")
    if package_metadata.get_all("Name") != ["dev-flow-orchestrator"]:
        raise ReleaseBuildError("project wheel project name is invalid")
    if package_metadata.get_all("Version") != [version]:
        raise ReleaseBuildError("project wheel version is invalid")
    size, digest = artifact.sha256_file(path)
    return {"name": path.name, "size": size, "sha256": digest}


def _plugin_version(root: Path) -> str:
    path = root / ".codex-plugin" / "plugin.json"
    value = artifact.strict_json_bytes(path.read_bytes(), maximum=256 * 1024, label="plugin manifest")
    if not isinstance(value, Mapping) or not isinstance(value.get("version"), str):
        raise ReleaseBuildError("plugin manifest version is invalid")
    return str(value["version"])


def _aggregate_digest(entries: Iterable[Mapping[str, object]], prefix: str) -> str:
    selected = [entry for entry in entries if str(entry["path"]) == prefix or str(entry["path"]).startswith(prefix + "/")]
    return hashlib.sha256(artifact.canonical_json_bytes(selected)).hexdigest()


def _tar_info(name: str, *, directory: bool, mode: int, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    info.mode = mode
    info.size = 0 if directory else size
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    return info


def _write_archive(release_root: Path, archive_path: Path) -> None:
    root_name = release_root.name
    tar_buffer = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(_tar_info(root_name, directory=True, mode=0o755))
        for path in sorted(release_root.rglob("*")):
            relative = path.relative_to(release_root).as_posix()
            name = root_name + "/" + relative
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                archive.addfile(_tar_info(name, directory=True, mode=0o755))
            elif stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                raw = path.read_bytes()
                archive.addfile(
                    _tar_info(
                        name,
                        directory=False,
                        mode=artifact._expected_mode(relative, False),
                        size=len(raw),
                    ),
                    io.BytesIO(raw),
                )
            else:
                raise ReleaseBuildError("release staging contains a link or special entry")
    tar_buffer.seek(0)
    with archive_path.open("xb") as output:
        with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0, compresslevel=9) as compressed:
            shutil.copyfileobj(tar_buffer, compressed, length=128 * 1024)
    tar_buffer.close()


def _default_bootstrap_renderer(
    platform_name: str,
    *,
    repository: str,
    version: str,
    archive_name: str,
    index_sha256: str,
    phase_a_source: bytes,
) -> bytes:
    assets = render_bootstrap_assets(
        phase_a_source,
        index_sha256=index_sha256,
        version=version,
        repository=repository,
        archive_name=archive_name,
    )
    if platform_name == "posix":
        return assets["install-{}.sh".format(version)]
    if platform_name == "windows":
        return assets["install-{}.ps1".format(version)]
    raise ReleaseBuildError("bootstrap platform is unsupported")


def render_bootstrap_assets(
    verifier_bytes: bytes,
    *,
    index_sha256: str,
    version: str,
    repository: str = artifact.CANONICAL_REPOSITORY,
    archive_name: str | None = None,
) -> dict[str, bytes]:
    """Render both versioned bootstraps around one byte-identical verifier body."""

    version = artifact.validate_version(version)
    artifact._digest(index_sha256, "bootstrap index digest")
    if repository != artifact.CANONICAL_REPOSITORY:
        raise ReleaseBuildError("bootstrap repository is not canonical")
    expected_archive = "dev-flow-orchestrator-{}.tar.gz".format(version)
    if archive_name is None:
        archive_name = expected_archive
    if archive_name != expected_archive:
        raise ReleaseBuildError("bootstrap archive name is invalid")
    replacements = {
        "@DEV_FLOW_BOOTSTRAP_SCHEMA@": artifact.BOOTSTRAP_SCHEMA,
        "@DEV_FLOW_REPOSITORY@": repository,
        "@DEV_FLOW_RELEASE_VERSION@": version,
        "@DEV_FLOW_ARCHIVE_NAME@": archive_name,
        "@DEV_FLOW_INDEX_SHA256@": index_sha256,
        "@DEV_FLOW_PHASE_A_B64@": base64.b64encode(verifier_bytes).decode("ascii"),
    }
    rendered: dict[str, bytes] = {}
    script_root = Path(__file__).resolve().parent
    for name in ("install-versioned.sh", "install-versioned.ps1"):
        try:
            document = (script_root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReleaseBuildError("release bootstrap template is unavailable: {}".format(name)) from exc
        for marker, replacement in replacements.items():
            if document.count(marker) != 1:
                raise ReleaseBuildError(
                    "release bootstrap template marker is invalid: {} {}".format(name, marker)
                )
            document = document.replace(marker, replacement)
        if re.search(r"@DEV_FLOW_[A-Z_]+@", document):
            raise ReleaseBuildError("release bootstrap template retains an unresolved marker")
        output_name = (
            "install-{}.sh".format(version)
            if name.endswith(".sh")
            else "install-{}.ps1".format(version)
        )
        rendered[output_name] = document.encode("utf-8")
    return rendered


def render_universal_assets(
    resolver_bytes: bytes,
    *,
    repository: str = artifact.CANONICAL_REPOSITORY,
    schema: str = "dev-flow-release-resolver/1.0.0",
) -> dict[str, bytes]:
    """Render the version-agnostic first-install entries for both platforms."""

    if repository != artifact.CANONICAL_REPOSITORY:
        raise ReleaseBuildError("install entry repository is not canonical")
    replacements = {
        "@DEV_FLOW_BOOTSTRAP_SCHEMA@": schema,
        "@DEV_FLOW_REPOSITORY@": repository,
        "@DEV_FLOW_RESOLVER_B64@": base64.b64encode(resolver_bytes).decode("ascii"),
    }
    rendered: dict[str, bytes] = {}
    script_root = Path(__file__).resolve().parent
    for name in ("install.sh", "install.ps1"):
        try:
            document = (script_root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReleaseBuildError("install entry template is unavailable: {}".format(name)) from exc
        for marker, replacement in replacements.items():
            if document.count(marker) != 1:
                raise ReleaseBuildError(
                    "install entry template marker is invalid: {} {}".format(name, marker)
                )
            document = document.replace(marker, replacement)
        if re.search(r"@DEV_FLOW_[A-Z_]+@", document):
            raise ReleaseBuildError("install entry template retains an unresolved marker")
        rendered[name] = document.encode("utf-8")
    return rendered


def assemble_release(
    root: Path,
    output_dir: Path,
    *,
    version: str,
    source_commit: str,
    source_tree: str,
    wheel_path: Path,
    requirements_path: Path,
    bootstrap_renderer: Callable[..., bytes] | None = None,
) -> dict[str, object]:
    version = artifact.validate_version(version)
    artifact._git_oid(source_commit, "source commit")
    artifact._git_oid(source_tree, "source tree")
    root = root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise ReleaseBuildError("release output directory must be newly absent")
    if _plugin_version(root) != version:
        raise ReleaseBuildError("plugin version does not match the release")
    wheel_identity = validate_project_wheel(wheel_path, version=version)
    requirements_raw = requirements_path.read_bytes()
    try:
        requirements_text = requirements_raw.decode("utf-8")
    except UnicodeError as exc:
        raise ReleaseBuildError("runtime requirements are not UTF-8") from exc
    artifact.validate_requirements_text(requirements_text)
    plugin_inputs = closed_plugin_inputs(root)
    lifecycle_inputs = [
        ("scripts/" + name, _safe_source_file(root, "scripts/" + name))
        for name in LIFECYCLE_FILES
    ]
    findings = scan_known_secrets_and_local_paths(plugin_inputs + lifecycle_inputs)
    if findings:
        raise ReleaseBuildError("release input scan found known secret or local path: {}".format(findings))
    renderer = bootstrap_renderer or _default_bootstrap_renderer
    phase_a_source = (root / "scripts" / "release_artifact.py").read_bytes()
    resolver_source = (root / "scripts" / "release_resolver.py").read_bytes()
    archive_name = "dev-flow-orchestrator-{}.tar.gz".format(version)
    try:
        output_dir.mkdir(parents=False, exist_ok=False)
        with tempfile.TemporaryDirectory(prefix="dev-flow-release-stage-") as temporary_name:
            stage = Path(temporary_name) / "dev-flow-orchestrator-{}".format(version)
            stage.mkdir(mode=0o755)
            stage.chmod(0o755)
            plugin_root = stage / "plugin"
            for relative, source in plugin_inputs:
                _copy_file(
                    source,
                    plugin_root.joinpath(*relative.split("/")),
                    mode=artifact._expected_mode("plugin/" + relative, False),
                    staging_root=stage,
                )
            plugin_seal = _write_plugin_seal(plugin_root, source_commit, source_tree)
            lifecycle_root = stage / "lifecycle"
            for source_relative, source in lifecycle_inputs:
                name = PurePosixPath(source_relative).name
                _copy_file(
                    source,
                    lifecycle_root / name,
                    mode=0o755,
                    staging_root=stage,
                )
            wheels_root = stage / "wheels"
            wheels_root.mkdir(mode=0o755)
            wheels_root.chmod(0o755)
            _copy_file(
                wheel_path,
                wheels_root / wheel_path.name,
                mode=0o644,
                staging_root=stage,
            )
            (stage / "runtime-requirements.txt").write_bytes(requirements_raw)
            (stage / "runtime-requirements.txt").chmod(0o644)
            _copy_file(
                root / "uv.lock",
                stage / "uv.lock",
                mode=0o644,
                staging_root=stage,
            )
            entries = _inventory(stage, exclude={artifact.MANIFEST_NAME})
            manifest = {
                "schema": artifact.ARTIFACT_SCHEMA,
                "version": version,
                "entries": entries,
            }
            artifact.validate_release_manifest(manifest, version=version, limits=artifact.HARD_LIMITS)
            manifest_raw = artifact.canonical_json_bytes(manifest)
            manifest_path = stage / artifact.MANIFEST_NAME
            manifest_path.write_bytes(manifest_raw)
            manifest_path.chmod(0o644)
            archive_path = output_dir / archive_name
            _write_archive(stage, archive_path)
            archive_size, archive_digest = artifact.sha256_file(
                archive_path, maximum=artifact.HARD_LIMITS["archive_bytes"]
            )
            index = {
                "schema": artifact.INDEX_SCHEMA,
                "artifact_schema": artifact.ARTIFACT_SCHEMA,
                "repository": artifact.CANONICAL_REPOSITORY,
                "version": version,
                "source_commit": source_commit,
                "source_tree": source_tree,
                "archive": {
                    "name": archive_name,
                    "size": archive_size,
                    "sha256": archive_digest,
                },
                "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                "limits": dict(artifact.HARD_LIMITS),
            }
            artifact.validate_release_index(index)
            index_raw = artifact.canonical_json_bytes(index)
            index_path = output_dir / "release-index.json"
            index_path.write_bytes(index_raw)
            index_digest = hashlib.sha256(index_raw).hexdigest()
            install_sh = renderer(
                "posix",
                repository=artifact.CANONICAL_REPOSITORY,
                version=version,
                archive_name=archive_name,
                index_sha256=index_digest,
                phase_a_source=phase_a_source,
            )
            install_ps1 = renderer(
                "windows",
                repository=artifact.CANONICAL_REPOSITORY,
                version=version,
                archive_name=archive_name,
                index_sha256=index_digest,
                phase_a_source=phase_a_source,
            )
            universal = render_universal_assets(
                resolver_source,
                repository=artifact.CANONICAL_REPOSITORY,
                schema=resolver.RESOLVER_SCHEMA,
            )
            if not isinstance(install_sh, bytes) or not isinstance(install_ps1, bytes):
                raise ReleaseBuildError("bootstrap renderer must return bytes")
            (output_dir / "install-{}.sh".format(version)).write_bytes(install_sh)
            (output_dir / "install-{}.ps1".format(version)).write_bytes(install_ps1)
            (output_dir / "install.sh").write_bytes(universal["install.sh"])
            (output_dir / "install.ps1").write_bytes(universal["install.ps1"])
            with tempfile.TemporaryDirectory(prefix="dev-flow-release-verify-") as verify_name:
                verified_index = artifact.verify_release_index_bytes(
                    index_raw,
                    index_digest,
                    artifact.CANONICAL_REPOSITORY,
                    version,
                    archive_name,
                )
                verified = artifact.inspect_and_extract_artifact(
                    archive_path, Path(verify_name).resolve() / "extracted", verified_index
                )
            component_digests = {
                "index": index_digest,
                "archive": archive_digest,
                "manifest": hashlib.sha256(manifest_raw).hexdigest(),
                "wheel": str(wheel_identity["sha256"]),
                "requirements": hashlib.sha256(requirements_raw).hexdigest(),
                "lock": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
                "plugin": _aggregate_digest(entries, "plugin"),
                "lifecycle": _aggregate_digest(entries, "lifecycle"),
                "install_sh": hashlib.sha256(universal["install.sh"]).hexdigest(),
                "install_ps1": hashlib.sha256(universal["install.ps1"]).hexdigest(),
                "install_versioned_sh": hashlib.sha256(install_sh).hexdigest(),
                "install_versioned_ps1": hashlib.sha256(install_ps1).hexdigest(),
            }
            return {
                "ok": True,
                "version": version,
                "source_commit": source_commit,
                "source_tree": source_tree,
                "release_id": verified["release_id"],
                "plugin_release_id": plugin_seal["release_id"],
                "output_dir": str(output_dir),
                "assets": [
                    archive_name,
                    "release-index.json",
                    "install.sh",
                    "install.ps1",
                    "install-{}.sh".format(version),
                    "install-{}.ps1".format(version),
                ],
                "manifest": manifest,
                "component_digests": component_digests,
            }
    except Exception:
        if output_dir.exists() and not output_dir.is_symlink():
            shutil.rmtree(output_dir, ignore_errors=True)
        raise


def export_requirements(
    root: Path,
    destination: Path,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    _run(
        runner,
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-header",
            "--no-annotate",
            "--format",
            "requirements.txt",
            "--output-file",
            str(destination),
        ],
        cwd=root,
    )
    artifact.validate_requirements_text(destination.read_text(encoding="utf-8"))


def build_release(
    root: Path,
    output_dir: Path,
    *,
    version: str,
    runner: Callable[..., Any] = subprocess.run,
    bootstrap_renderer: Callable[..., bytes] | None = None,
) -> dict[str, object]:
    config = load_builder_config(root / DEFAULT_CONFIG_NAME)
    validate_builder_environment(config, root=root, runner=runner)
    source_commit, source_tree = validate_clean_tag(root, version, runner=runner)
    with tempfile.TemporaryDirectory(prefix="dev-flow-release-build-") as temporary_name:
        temporary = Path(temporary_name)
        wheel_dir = temporary / "wheel"
        wheel_dir.mkdir()
        _run(
            runner,
            ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
            cwd=root,
        )
        wheels = sorted(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise ReleaseBuildError("builder must produce exactly one project wheel")
        requirements = temporary / "runtime-requirements.txt"
        export_requirements(root, requirements, runner=runner)
        return assemble_release(
            root,
            output_dir,
            version=version,
            source_commit=source_commit,
            source_tree=source_tree,
            wheel_path=wheels[0],
            requirements_path=requirements,
            bootstrap_renderer=bootstrap_renderer,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = build_release(
            arguments.root.resolve(),
            arguments.output_dir,
            version=arguments.version,
        )
    except (OSError, ValueError, artifact.ReleaseArtifactError, ReleaseBuildError) as exc:
        print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
