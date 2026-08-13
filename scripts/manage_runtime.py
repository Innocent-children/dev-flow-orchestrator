#!/usr/bin/env python3
"""Build or completely verify one sealed Dev Flow managed runtime release."""

# The external runtime_receipt authority is verified before reuse and launch.

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any
import zipfile


sys.dont_write_bytecode = True
SCRIPT_ROOT = Path(__file__).resolve().parent
_HELPER_PATH = SCRIPT_ROOT / "runtime_integrity.py"
_HELPER_SPEC = importlib.util.spec_from_file_location("dev_flow_runtime_integrity", _HELPER_PATH)
if _HELPER_SPEC is None or _HELPER_SPEC.loader is None:
    raise RuntimeError("managed runtime integrity helper cannot be loaded")
integrity = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(integrity)
_ARTIFACT_PATH = SCRIPT_ROOT / "release_artifact.py"
_ARTIFACT_SPEC = importlib.util.spec_from_file_location(
    "dev_flow_release_artifact",
    _ARTIFACT_PATH,
)
if _ARTIFACT_SPEC is None or _ARTIFACT_SPEC.loader is None:
    raise RuntimeError("release artifact verifier cannot be loaded")
release_artifact = importlib.util.module_from_spec(_ARTIFACT_SPEC)
_ARTIFACT_SPEC.loader.exec_module(release_artifact)


ROOT_MARKER = ".dev-flow-managed-runtime"
RUNTIME_RECEIPT_NAME = integrity.RUNTIME_RECEIPT_NAME
OWNERSHIP_MANIFEST_NAME = integrity.OWNERSHIP_MANIFEST_NAME


class RuntimeBuildError(RuntimeError):
    pass


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    extra_environment: dict[str, str] | None = None,
    timeout: float = 180.0,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_environment:
        environment.update(extra_environment)
    try:
        completed = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeBuildError(
            "command could not complete within its bounded execution: {}".format(
                Path(arguments[0]).name
            )
        ) from exc
    if completed.returncode:
        raise RuntimeBuildError(
            "command failed with exit status {}: {}; {}".format(
                completed.returncode,
                Path(arguments[0]).name,
                completed.stderr.strip()[-2048:] or completed.stdout.strip()[-2048:],
            )
        )
    return completed


def _json_output(completed: subprocess.CompletedProcess[str], label: str) -> dict[str, object]:
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeBuildError("{} returned invalid JSON".format(label)) from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeBuildError("{} did not report success".format(label))
    return value


def _inside(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        return False


def _python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _target_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except OSError:
        return False


def _regular_file(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeBuildError("{} is unavailable".format(label)) from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RuntimeBuildError("{} must be a regular file".format(label))
    return path


def _regular_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeBuildError("{} is unavailable".format(label)) from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise RuntimeBuildError("{} must be a regular directory".format(label))
    return path


def _strict_index_identity(
    index_path: Path,
    expected_index_sha256: str,
) -> dict[str, object]:
    if integrity.sha256_file(_regular_file(index_path, "verified release index")) != expected_index_sha256:
        raise RuntimeBuildError("release index digest differs from Phase A evidence")
    value = integrity.read_json(index_path)
    fields = {
        "schema", "artifact_schema", "repository", "version", "source_commit",
        "source_tree", "archive", "manifest_sha256", "limits",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise RuntimeBuildError("release index fields are invalid")
    if value.get("schema") != "dev-flow-release-index/1.0.0":
        raise RuntimeBuildError("release index schema is incompatible")
    if value.get("artifact_schema") != "dev-flow-release-artifact/1.0.0":
        raise RuntimeBuildError("release artifact schema is incompatible")
    if value.get("repository") != integrity.CANONICAL_REPOSITORY:
        raise RuntimeBuildError("release index repository is invalid")
    version = value.get("version")
    if not isinstance(version, str) or not integrity._VERSION.fullmatch(version):
        raise RuntimeBuildError("release index version is invalid")
    try:
        integrity._validate_hex(value.get("source_commit"), label="source commit", length=40)
        integrity._validate_hex(value.get("source_tree"), label="source tree", length=40)
        integrity._validate_hex(value.get("manifest_sha256"), label="artifact manifest digest")
        integrity._validate_hex(expected_index_sha256, label="release index digest")
    except integrity.IntegrityError as exc:
        raise RuntimeBuildError(str(exc)) from exc
    archive = value.get("archive")
    if not isinstance(archive, dict) or set(archive) != {"name", "size", "sha256"}:
        raise RuntimeBuildError("release index archive identity is invalid")
    expected_archive_name = "dev-flow-orchestrator-{}.tar.gz".format(version)
    if archive.get("name") != expected_archive_name:
        raise RuntimeBuildError("release index archive name is invalid")
    if (
        isinstance(archive.get("size"), bool)
        or not isinstance(archive.get("size"), int)
        or int(archive["size"]) <= 0
    ):
        raise RuntimeBuildError("release index archive size is invalid")
    try:
        integrity._validate_hex(archive.get("sha256"), label="release archive digest")
    except integrity.IntegrityError as exc:
        raise RuntimeBuildError(str(exc)) from exc
    limit_fields = {
        "index_bytes", "manifest_bytes", "archive_bytes", "entry_count",
        "component_length", "path_length", "nesting_depth", "file_bytes", "total_bytes",
    }
    limits = value.get("limits")
    if not isinstance(limits, dict) or set(limits) != limit_fields:
        raise RuntimeBuildError("release index resource limits are invalid")
    if any(
        isinstance(limits[field], bool)
        or not isinstance(limits[field], int)
        or int(limits[field]) <= 0
        for field in limit_fields
    ):
        raise RuntimeBuildError("release index resource limits are invalid")
    return value


def _artifact_manifest_identity(
    artifact_root: Path,
    index: dict[str, object],
) -> Path:
    manifest_path = _regular_file(
        artifact_root / "release-manifest.json", "artifact release manifest"
    )
    if integrity.sha256_file(manifest_path) != index["manifest_sha256"]:
        raise RuntimeBuildError("artifact release manifest differs from the release index")
    value = integrity.read_json(manifest_path)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "version", "entries"}
        or value.get("schema") != "dev-flow-release-artifact/1.0.0"
        or value.get("version") != index["version"]
        or not isinstance(value.get("entries"), list)
    ):
        raise RuntimeBuildError("artifact release manifest identity is invalid")
    return manifest_path


def _project_wheel(artifact_root: Path, version: str) -> Path:
    wheels_root = _regular_directory(artifact_root / "wheels", "artifact wheels directory")
    try:
        entries = list(wheels_root.iterdir())
    except OSError as exc:
        raise RuntimeBuildError("artifact wheels directory cannot be enumerated") from exc
    expected_name = "dev_flow_orchestrator-{}-py3-none-any.whl".format(version)
    if len(entries) != 1 or entries[0].name != expected_name:
        raise RuntimeBuildError("artifact must contain exactly one version-matched pure-Python wheel")
    wheel = _regular_file(entries[0], "supplied project wheel")
    try:
        with zipfile.ZipFile(wheel, "r") as archive:
            wheel_metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")
            ]
            project_metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(wheel_metadata_names) != 1 or len(project_metadata_names) != 1:
                raise RuntimeBuildError("supplied project wheel metadata topology is invalid")
            wheel_metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(wheel_metadata_names[0])
            )
            project_metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(project_metadata_names[0])
            )
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise RuntimeBuildError("supplied project wheel is malformed") from exc
    if (
        wheel_metadata.get("Root-Is-Purelib", "").casefold() != "true"
        or "py3-none-any" not in wheel_metadata.get_all("Tag", [])
        or project_metadata.get("Name") != "dev-flow-orchestrator"
        or project_metadata.get("Version") != version
    ):
        raise RuntimeBuildError("supplied project wheel identity is invalid")
    return wheel


def _copy_regular_tree(source: Path, destination: Path, label: str) -> None:
    _regular_directory(source, label)
    if _target_exists(destination):
        raise RuntimeBuildError("{} destination already exists".format(label))
    destination.mkdir(mode=0o700)
    pending = [(source, destination)]
    while pending:
        source_parent, destination_parent = pending.pop()
        try:
            children = sorted(source_parent.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise RuntimeBuildError("{} cannot be enumerated".format(label)) from exc
        directories: list[tuple[Path, Path]] = []
        for source_child in children:
            destination_child = destination_parent / source_child.name
            try:
                metadata = source_child.lstat()
            except OSError as exc:
                raise RuntimeBuildError("{} entry cannot be inspected".format(label)) from exc
            if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                destination_child.mkdir(mode=stat.S_IMODE(metadata.st_mode))
                directories.append((source_child, destination_child))
            elif stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                with source_child.open("rb") as input_stream, destination_child.open("xb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=128 * 1024)
                destination_child.chmod(stat.S_IMODE(metadata.st_mode))
                if integrity.sha256_file(source_child) != integrity.sha256_file(destination_child):
                    raise RuntimeBuildError("{} changed while it was copied".format(label))
            else:
                raise RuntimeBuildError("{} contains a linked or special entry".format(label))
        pending.extend(reversed(directories))


def _python_probe(runtime_python: Path, scratch: Path) -> dict[str, Any]:
    code = (
        "import importlib.metadata,json,platform,struct,sys;"
        "print(json.dumps({"
        "'version':list(sys.version_info[:3]),"
        "'bits':struct.calcsize('P')*8,"
        "'architecture':platform.machine(),"
        "'mcp':importlib.metadata.version('mcp')"
        "},sort_keys=True))"
    )
    completed = _run(
        [str(runtime_python), "-B", "-I", "-c", code],
        cwd=scratch,
    )
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeBuildError("managed runtime Python probe returned invalid JSON") from exc
    version = value.get("version") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(version, list)
        or len(version) != 3
        or not all(isinstance(item, int) for item in version)
        or not ((3, 10) <= tuple(version[:2]) < (3, 15))
        or value.get("bits") != 64
        or not isinstance(value.get("architecture"), str)
        or not str(value.get("mcp", "")).startswith("2.")
    ):
        raise RuntimeBuildError(
            "managed runtime requires 64-bit Python 3.10 through 3.14 and MCP SDK major 2"
        )
    return value


def _smoke(plugin_root: Path, runtime_python: Path, scratch: Path) -> None:
    runner = plugin_root / "scripts" / "validate_installed_stage1.py"
    if not runner.is_file() or runner.is_symlink():
        raise RuntimeBuildError("sealed release is missing the installed MCP acceptance runner")
    completed = _run(
        [
            str(runtime_python),
            "-B",
            "-I",
            str(runner),
            "--plugin-root",
            str(plugin_root),
            "--launcher",
            str(runtime_python),
            "--launcher-arg=-B",
            "--launcher-arg=-I",
            "--launcher-arg=-m",
            "--launcher-arg=dev_flow_orchestrator.mcp",
            "--candidate-smoke-only",
        ],
        cwd=scratch,
    )
    evidence = _json_output(completed, "staged MCP STDIO smoke")
    journey = evidence.get("journey")
    if (
        not isinstance(journey, dict)
        or journey.get("read_smoke") is not True
        or journey.get("candidate_smoke") is not True
        or journey.get("mutation_smoke") is not False
        or journey.get("terminal_status") is not None
    ):
        raise RuntimeBuildError("checkout-free staged Skill/MCP health check failed")


def _render_launcher(target: Path, staging: Path, release_id: str) -> Path:
    windows = os.name == "nt"
    template = SCRIPT_ROOT / (
        "dev_flow_mcp_launcher.cmd" if windows else "dev_flow_mcp_launcher"
    )
    if not template.is_file() or template.is_symlink():
        raise RuntimeBuildError("sealed release is missing the managed MCP launcher template")
    try:
        payload = template.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeBuildError("managed MCP launcher template cannot be read") from exc
    final_python = _python(target / "venv")
    final_verifier = target / "integrity" / "runtime_integrity.py"
    replacements = {
        "__DEV_FLOW_RUNTIME_PYTHON__": str(final_python),
        "__DEV_FLOW_RUNTIME_VERIFIER__": str(final_verifier),
        "__DEV_FLOW_RUNTIME_DIR__": str(target),
        "__DEV_FLOW_RELEASE_ID__": release_id,
    }
    for placeholder, value in replacements.items():
        if payload.count(placeholder) != 1:
            raise RuntimeBuildError("managed MCP launcher template placeholders are invalid")
        rendered = value.replace("%", "%%") if windows else shlex.quote(value)
        payload = payload.replace(placeholder, rendered)
    launchers = staging / "launchers"
    launchers.mkdir(parents=False, exist_ok=False)
    launcher = launchers / ("dev-flow-mcp.cmd" if windows else "dev-flow-mcp")
    launcher.write_text(payload, encoding="utf-8", newline="")
    launcher.chmod(0o644 if windows else 0o755)
    return launcher


def _render_cli_launcher(target: Path, staging: Path, mcp_launcher: Path) -> Path | None:
    if os.name != "nt":
        return None
    runtime_python = _python(target / "venv")
    verifier = target / "integrity" / "runtime_integrity.py"
    plugin_cli = target / "plugin" / "scripts" / "dev_flow.py"
    payload = (
        "@echo off\r\n"
        "rem dev-flow-orchestrator managed CLI launcher\r\n"
        "set \"PYTHONDONTWRITEBYTECODE=1\"\r\n"
        f'"{runtime_python}" -B -I "{verifier}" verify-runtime '
        f'--runtime-dir "{target}" --launcher "{mcp_launcher}"\r\n'
        "if errorlevel 1 exit /b %errorlevel%\r\n"
        f'"{runtime_python}" -B -I "{plugin_cli}" %*\r\n'
    )
    launcher = staging / "launchers" / "dev-flow.cmd"
    launcher.write_text(payload, encoding="utf-8", newline="")
    launcher.chmod(0o644)
    return launcher


def _verify_with_runtime(
    *,
    runtime_dir: Path,
    recorded_target: Path,
    helper: Path,
    launcher: Path,
    release_id: str,
    allow_staging: bool,
) -> dict[str, object]:
    runtime_python = _python(runtime_dir / "venv")
    arguments = [
        str(runtime_python), "-B", "-I", str(helper), "verify-runtime",
        "--runtime-dir", str(runtime_dir), "--launcher", str(launcher),
        "--release-id", release_id,
    ]
    if allow_staging:
        arguments.append("--allow-staging")
    result = _json_output(
        _run(arguments, cwd=runtime_dir),
        "managed runtime verifier",
    )
    receipt = result.get("receipt")
    if not isinstance(receipt, dict) or receipt.get("runtime_path") != str(recorded_target):
        raise RuntimeBuildError("managed runtime verifier returned the wrong release")
    return receipt


def _verify_artifact_with_runtime(
    *,
    runtime_dir: Path,
    recorded_target: Path,
    helper: Path,
    release_id: str,
    transaction_id: str,
    allow_staging: bool,
) -> dict[str, object]:
    arguments = [
        str(_python(runtime_dir / "venv")),
        "-B",
        "-I",
        str(helper),
        "verify-artifact-runtime",
        "--runtime-dir",
        str(runtime_dir),
        "--release-id",
        release_id,
        "--transaction-id",
        transaction_id,
    ]
    if allow_staging:
        arguments.append("--allow-staging")
    result = _json_output(
        _run(arguments, cwd=runtime_dir), "managed artifact runtime verifier"
    )
    receipt = result.get("receipt")
    if not isinstance(receipt, dict) or receipt.get("runtime_path") != str(recorded_target):
        raise RuntimeBuildError("managed artifact verifier returned the wrong release")
    return receipt


def _artifact_runtime_result(
    target: Path,
    receipt: dict[str, object],
) -> dict[str, object]:
    receipt_path = target / RUNTIME_RECEIPT_NAME
    return {
        "ok": True,
        "reused": False,
        "release_id": receipt["release_id"],
        "version": receipt["version"],
        "transaction_id": receipt["transaction_id"],
        "runtime_dir": str(target),
        "plugin_root": str(target / "plugin"),
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "receipt_sha256": integrity.sha256_file(receipt_path),
        "ownership_manifest_path": str(target / OWNERSHIP_MANIFEST_NAME),
        "ownership_manifest_sha256": receipt["ownership_manifest_sha256"],
        "verifier_path": str(target / "integrity" / "runtime_integrity.py"),
        "verifier_sha256": receipt["verifier_sha256"],
        "lifecycle_root": str(target / "lifecycle"),
        "artifact_sha256": receipt["archive_sha256"],
        "staged_health": True,
        "retained_paths": [],
    }


def _runtime_result(
    target: Path,
    receipt: dict[str, object],
    *,
    reused: bool,
    retained_paths: list[str],
) -> dict[str, object]:
    launcher = target / "launchers" / (
        "dev-flow-mcp.cmd" if os.name == "nt" else "dev-flow-mcp"
    )
    cli_launcher = target / "launchers" / "dev-flow.cmd"
    return {
        "ok": True,
        "reused": reused,
        "release_id": receipt["release_id"],
        "runtime_dir": str(target),
        "plugin_root": str(target / "plugin"),
        "receipt": receipt,
        "receipt_path": str(target / RUNTIME_RECEIPT_NAME),
        "ownership_manifest_path": str(target / OWNERSHIP_MANIFEST_NAME),
        "ownership_manifest_sha256": receipt["ownership_manifest_sha256"],
        "verifier_path": str(target / "integrity" / "runtime_integrity.py"),
        "launcher_path": str(launcher),
        "launcher_sha256": receipt["launcher_sha256"],
        "cli_launcher_path": str(cli_launcher) if cli_launcher.exists() else None,
        "cli_launcher_sha256": receipt["cli_launcher_sha256"],
        "retained_paths": retained_paths,
    }


def build_artifact_candidate(
    artifact_root: Path,
    runtime_root: Path,
    release_index_path: Path,
    release_index_sha256: str,
    transaction_id: str,
    data_root: Path | None = None,
    *,
    expected_release_id: str | None = None,
) -> dict[str, object]:
    """Build one transaction-owned candidate from a Phase-A-verified artifact.

    This Phase B entry point never builds project source.  It installs only the
    supplied pure-Python wheel plus hash-locked, wheel-only requirements, then
    fully attests and smoke-tests the candidate without reading public active
    authority.
    """

    selected_artifact = artifact_root.expanduser()
    _regular_directory(selected_artifact, "verified artifact root")
    artifact_root = selected_artifact.resolve()
    index = _strict_index_identity(
        release_index_path.expanduser(), release_index_sha256
    )
    try:
        release_artifact.verify_extracted_artifact(artifact_root, index)
    except release_artifact.ReleaseArtifactError as exc:
        raise RuntimeBuildError(
            "live artifact inventory differs from Phase A evidence: " + str(exc)
        ) from exc
    version = str(index["version"])
    expected_artifact_name = "dev-flow-orchestrator-{}".format(version)
    if artifact_root.name != expected_artifact_name:
        raise RuntimeBuildError("verified artifact root name is invalid")
    manifest_path = _artifact_manifest_identity(artifact_root, index)
    manifest_digest = str(index["manifest_sha256"])
    transaction_id = integrity._validate_transaction_id(transaction_id)
    release_id = "v{}-{}-{}".format(
        version, manifest_digest[:16], transaction_id
    )
    try:
        release_id = integrity._validate_release_id(release_id)
    except integrity.IntegrityError as exc:
        raise RuntimeBuildError(
            "transaction_id cannot form the required candidate release_id"
        ) from exc
    if expected_release_id is not None and expected_release_id != release_id:
        raise RuntimeBuildError("candidate release_id differs from its artifact and transaction")
    source_commit = str(index["source_commit"])
    source_tree = str(index["source_tree"])
    plugin_source = artifact_root / "plugin"
    try:
        sealed_plugin = integrity.verify_plugin_release(
            plugin_source,
            source_commit=source_commit,
            source_tree=source_tree,
        )
    except integrity.IntegrityError as exc:
        raise RuntimeBuildError(str(exc)) from exc
    plugin_manifest = integrity.read_json(
        plugin_source / ".codex-plugin" / "plugin.json"
    )
    if (
        not isinstance(plugin_manifest, dict)
        or plugin_manifest.get("name") != "dev-flow-orchestrator"
        or plugin_manifest.get("version") != version
    ):
        raise RuntimeBuildError("artifact plugin identity differs from the release index")
    wheel_source = _project_wheel(artifact_root, version)
    requirements_source = _regular_file(
        artifact_root / "runtime-requirements.txt", "runtime requirements"
    )
    lock_source = _regular_file(artifact_root / "uv.lock", "artifact uv.lock")
    lifecycle_source = _regular_directory(
        artifact_root / "lifecycle", "versioned lifecycle helpers"
    )
    required_lifecycle = {
        "manage_runtime.py",
        "release_artifact.py",
        "release_commands.py",
        "release_lifecycle.py",
        "release_resolver.py",
        "runtime_integrity.py",
        "validate_installed_stage1.py",
    }
    if not all(
        _regular_file(lifecycle_source / name, "versioned lifecycle helper").is_file()
        for name in required_lifecycle
    ):
        raise RuntimeBuildError("required versioned lifecycle helpers are missing")

    selected_runtime_root = runtime_root.expanduser()
    if selected_runtime_root.is_symlink():
        raise RuntimeBuildError("managed runtime root must not be a symbolic link")
    runtime_root_existed = selected_runtime_root.exists()
    runtime_root = selected_runtime_root.resolve()
    if _inside(runtime_root, artifact_root) or _inside(artifact_root, runtime_root):
        raise RuntimeBuildError("managed runtime and artifact root must be disjoint")
    if data_root is not None:
        selected_data_root = data_root.expanduser().resolve()
        if _inside(runtime_root, selected_data_root) or _inside(selected_data_root, runtime_root):
            raise RuntimeBuildError("managed runtime and task data must be disjoint")
    if not ((3, 10) <= sys.version_info[:2] < (3, 15)) or struct.calcsize("P") != 8:
        raise RuntimeBuildError("managed runtime requires 64-bit Python 3.10 through 3.14")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeBuildError("uv is required to install the exact artifact runtime")
    marker = runtime_root / ROOT_MARKER
    if runtime_root_existed:
        _regular_directory(runtime_root, "managed runtime root")
        if (
            not marker.is_file()
            or marker.is_symlink()
            or marker.read_bytes() != b"dev-flow-managed-runtime/1\n"
        ):
            raise RuntimeBuildError("existing managed runtime root has no valid ownership marker")
    else:
        runtime_root.mkdir(parents=True, exist_ok=False)
        marker.write_bytes(b"dev-flow-managed-runtime/1\n")
        marker.chmod(0o600)
    releases = runtime_root / "releases"
    if _target_exists(releases):
        _regular_directory(releases, "managed releases path")
    else:
        releases.mkdir(mode=0o700)
    target = releases / release_id
    if _target_exists(target):
        raise RuntimeBuildError("transaction-owned candidate release path already exists")

    with tempfile.TemporaryDirectory(
        prefix=".candidate-{}-".format(transaction_id), dir=str(releases)
    ) as transaction_text:
        transaction = Path(transaction_text)
        staging = transaction / "runtime"
        staging.mkdir(mode=0o700)
        try:
            staged_plugin = staging / "plugin"
            staged_plugin_manifest = integrity.copy_plugin_release(
                plugin_source, staged_plugin
            )
        except integrity.IntegrityError as exc:
            raise RuntimeBuildError(str(exc)) from exc
        lifecycle = staging / "lifecycle"
        _copy_regular_tree(lifecycle_source, lifecycle, "versioned lifecycle helpers")
        verifier_directory = staging / "integrity"
        verifier_directory.mkdir(mode=0o700)
        verifier = verifier_directory / "runtime_integrity.py"
        shutil.copyfile(lifecycle / "runtime_integrity.py", verifier)
        verifier.chmod(0o644)
        evidence = staging / "artifact"
        evidence.mkdir(mode=0o700)
        evidence_wheels = evidence / "wheels"
        evidence_wheels.mkdir(mode=0o700)
        copied_manifest = evidence / "release-manifest.json"
        copied_requirements = evidence / "runtime-requirements.txt"
        copied_lock = evidence / "uv.lock"
        copied_wheel = evidence_wheels / wheel_source.name
        for source, destination in (
            (manifest_path, copied_manifest),
            (requirements_source, copied_requirements),
            (lock_source, copied_lock),
            (wheel_source, copied_wheel),
        ):
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
            if integrity.sha256_file(source) != integrity.sha256_file(destination):
                raise RuntimeBuildError("artifact evidence changed while it was copied")
        venv = staging / "venv"
        cache = transaction / "uv-cache"
        uv_environment = {"UV_CACHE_DIR": str(cache)}
        _run(
            [uv, "venv", "--python", sys.executable, str(venv)],
            cwd=transaction,
            extra_environment=uv_environment,
        )
        runtime_python = _python(venv)
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(runtime_python),
                "--require-hashes",
                "--only-binary",
                ":all:",
                "-r",
                str(copied_requirements),
            ],
            cwd=transaction,
            extra_environment=uv_environment,
        )
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(runtime_python),
                "--no-deps",
                "--only-binary",
                ":all:",
                str(copied_wheel),
            ],
            cwd=transaction,
            extra_environment=uv_environment,
        )
        _python_probe(runtime_python, transaction)
        try:
            integrity.verify_plugin_release(
                plugin_source, source_commit=source_commit, source_tree=source_tree
            )
            staged_plugin_manifest = integrity.verify_plugin_release(
                staged_plugin, source_commit=source_commit, source_tree=source_tree
            )
        except integrity.IntegrityError as exc:
            raise RuntimeBuildError(str(exc)) from exc
        ownership = integrity.build_ownership_manifest(staging, release_id)
        ownership_path = staging / OWNERSHIP_MANIFEST_NAME
        ownership_path.write_bytes(integrity.pretty_json_bytes(ownership))
        receipt_result = _json_output(
            _run(
                [
                    str(runtime_python),
                    "-B",
                    "-I",
                    str(verifier),
                    "build-artifact-receipt",
                    "--physical-runtime",
                    str(staging),
                    "--recorded-runtime",
                    str(target),
                    "--release-id",
                    release_id,
                    "--version",
                    version,
                    "--transaction-id",
                    transaction_id,
                    "--source-commit",
                    source_commit,
                    "--source-tree",
                    source_tree,
                    "--release-index-sha256",
                    release_index_sha256,
                    "--archive-sha256",
                    str(index["archive"]["sha256"]),
                    "--artifact-manifest",
                    str(copied_manifest),
                    "--wheel",
                    str(copied_wheel),
                    "--runtime-requirements",
                    str(copied_requirements),
                    "--uv-lock",
                    str(copied_lock),
                    "--plugin-release-manifest-sha256",
                    str(staged_plugin_manifest["manifest_sha256"]),
                    "--verifier",
                    str(verifier),
                    "--ownership-manifest",
                    str(ownership_path),
                ],
                cwd=transaction,
            ),
            "artifact runtime receipt builder",
        )
        receipt = receipt_result.get("receipt")
        if not isinstance(receipt, dict):
            raise RuntimeBuildError("artifact runtime receipt builder returned no receipt")
        try:
            receipt = integrity.validate_artifact_runtime_receipt(receipt)
        except integrity.IntegrityError as exc:
            raise RuntimeBuildError(str(exc)) from exc
        (staging / RUNTIME_RECEIPT_NAME).write_bytes(
            integrity.pretty_json_bytes(receipt)
        )
        _verify_artifact_with_runtime(
            runtime_dir=staging,
            recorded_target=target,
            helper=verifier,
            release_id=release_id,
            transaction_id=transaction_id,
            allow_staging=True,
        )
        _smoke(staged_plugin, runtime_python, transaction)
        os.replace(staging, target)
        final_helper = target / "integrity" / "runtime_integrity.py"
        receipt = _verify_artifact_with_runtime(
            runtime_dir=target,
            recorded_target=target,
            helper=final_helper,
            release_id=release_id,
            transaction_id=transaction_id,
            allow_staging=False,
        )
        return _artifact_runtime_result(target, receipt)


# Short public name used by versioned lifecycle helpers.
build_artifact = build_artifact_candidate


def build(
    source_root: Path,
    runtime_root: Path,
    source_commit: str,
    source_tree: str,
    release_id: str,
    data_root: Path | None,
) -> dict[str, object]:
    selected_source = source_root.expanduser()
    try:
        source_metadata = selected_source.lstat()
    except OSError as exc:
        raise RuntimeBuildError("sealed plugin release is unavailable") from exc
    if not stat.S_ISDIR(source_metadata.st_mode) or stat.S_ISLNK(source_metadata.st_mode):
        raise RuntimeBuildError("sealed plugin release must be a regular directory")
    source_root = selected_source.resolve()
    try:
        sealed = integrity.verify_plugin_release(
            source_root,
            source_commit=source_commit,
            source_tree=source_tree,
            release_id=release_id,
        )
    except integrity.IntegrityError as exc:
        raise RuntimeBuildError(str(exc)) from exc
    selected_runtime_root = runtime_root.expanduser()
    if selected_runtime_root.is_symlink():
        raise RuntimeBuildError("managed runtime root must not be a symbolic link")
    runtime_root_existed = selected_runtime_root.exists()
    runtime_root = selected_runtime_root.resolve()
    if _inside(runtime_root, source_root) or _inside(source_root, runtime_root):
        raise RuntimeBuildError("managed runtime and sealed plugin release must be disjoint")
    if data_root is not None:
        data_root = data_root.expanduser().resolve()
        if _inside(runtime_root, data_root) or _inside(data_root, runtime_root):
            raise RuntimeBuildError("managed runtime and task data must be disjoint")
    if not ((3, 10) <= sys.version_info[:2] < (3, 15)) or struct.calcsize("P") != 8:
        raise RuntimeBuildError("managed runtime requires 64-bit Python 3.10 through 3.14")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeBuildError("uv is required to build the exact locked MCP runtime")
    marker = runtime_root / ROOT_MARKER
    if runtime_root_existed:
        try:
            root_metadata = runtime_root.lstat()
        except OSError as exc:
            raise RuntimeBuildError("managed runtime root cannot be inspected") from exc
        if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
            raise RuntimeBuildError("managed runtime root is not a regular directory")
        if (
            not marker.is_file()
            or marker.is_symlink()
            or marker.read_bytes() != b"dev-flow-managed-runtime/1\n"
        ):
            raise RuntimeBuildError("existing managed runtime root has no valid ownership marker")
    else:
        runtime_root.mkdir(parents=True, exist_ok=False)
        marker.write_bytes(b"dev-flow-managed-runtime/1\n")
        marker.chmod(0o600)
    releases = runtime_root / "releases"
    if _target_exists(releases):
        releases_metadata = releases.lstat()
        if not stat.S_ISDIR(releases_metadata.st_mode) or stat.S_ISLNK(releases_metadata.st_mode):
            raise RuntimeBuildError("managed releases path is not a regular directory")
    else:
        releases.mkdir(mode=0o700)
    target = releases / release_id
    source_helper = _HELPER_PATH
    source_manifest_digest = str(sealed["manifest_sha256"])
    lock_digest = integrity.sha256_file(source_root / "uv.lock")
    retained_paths: list[str] = []
    if _target_exists(target):
        try:
            launcher = target / "launchers" / (
                "dev-flow-mcp.cmd" if os.name == "nt" else "dev-flow-mcp"
            )
            receipt = _verify_with_runtime(
                runtime_dir=target,
                recorded_target=target,
                helper=source_helper,
                launcher=launcher,
                release_id=release_id,
                allow_staging=False,
            )
            if (
                receipt.get("source_commit") != source_commit
                or receipt.get("source_tree") != source_tree
                or receipt.get("dependency_lock_sha256") != lock_digest
                or receipt.get("plugin_release_manifest_sha256") != source_manifest_digest
            ):
                raise RuntimeBuildError("managed runtime receipt does not match the sealed release")
            integrity.verify_plugin_release(source_root, release_id=release_id)
            return _runtime_result(
                target, receipt, reused=True, retained_paths=retained_paths
            )
        except (OSError, RuntimeBuildError, integrity.IntegrityError):
            pass

    with tempfile.TemporaryDirectory(prefix=".transaction-", dir=str(releases)) as transaction_text:
        transaction = Path(transaction_text)
        staging = transaction / "runtime"
        build_source = transaction / "build-source"
        staging.mkdir(mode=0o700)
        try:
            staged_plugin = staging / "plugin"
            staged_plugin_manifest = integrity.copy_plugin_release(source_root, staged_plugin)
            integrity.copy_plugin_release(source_root, build_source)
        except integrity.IntegrityError as exc:
            raise RuntimeBuildError(str(exc)) from exc
        requirements = transaction / "requirements.txt"
        artifacts = staging / "artifacts"
        artifacts.mkdir()
        venv = staging / "venv"
        cache = transaction / "uv-cache"
        uv_environment = {"UV_CACHE_DIR": str(cache)}
        _run([uv, "venv", "--python", sys.executable, str(venv)], cwd=build_source, extra_environment=uv_environment)
        _run(
            [
                uv, "export", "--locked", "--no-dev", "--no-emit-project",
                "--format", "requirements.txt", "--output-file", str(requirements),
            ],
            cwd=build_source,
            extra_environment=uv_environment,
        )
        runtime_python = _python(venv)
        _run(
            [
                uv, "pip", "install", "--python", str(runtime_python),
                "--require-hashes", "-r", str(requirements),
            ],
            cwd=build_source,
            extra_environment=uv_environment,
        )
        _run(
            [uv, "build", "--wheel", "--out-dir", str(artifacts)],
            cwd=build_source,
            extra_environment=uv_environment,
        )
        wheels = tuple(artifacts.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeBuildError("runtime build did not produce exactly one wheel")
        _run(
            [
                uv, "pip", "install", "--python", str(runtime_python),
                "--no-deps", str(wheels[0]),
            ],
            cwd=build_source,
            extra_environment=uv_environment,
        )
        _python_probe(runtime_python, transaction)
        _smoke(staged_plugin, runtime_python, transaction)
        try:
            integrity.verify_plugin_release(source_root, release_id=release_id)
            integrity.verify_plugin_release(build_source, release_id=release_id)
            staged_plugin_manifest = integrity.verify_plugin_release(
                staged_plugin, release_id=release_id
            )
        except integrity.IntegrityError as exc:
            raise RuntimeBuildError(str(exc)) from exc
        verifier_directory = staging / "integrity"
        verifier_directory.mkdir()
        verifier = verifier_directory / "runtime_integrity.py"
        shutil.copyfile(_HELPER_PATH, verifier)
        verifier.chmod(0o644)
        launcher = _render_launcher(target, staging, release_id)
        cli_launcher = _render_cli_launcher(target, staging, launcher)
        ownership = integrity.build_ownership_manifest(staging, release_id)
        ownership_path = staging / OWNERSHIP_MANIFEST_NAME
        ownership_path.write_bytes(integrity.pretty_json_bytes(ownership))
        receipt_result = _json_output(
            _run(
                [
                    str(runtime_python), "-B", "-I", str(verifier), "build-receipt",
                    "--physical-runtime", str(staging),
                    "--recorded-runtime", str(target),
                    "--release-id", release_id,
                    "--source-commit", source_commit,
                    "--source-tree", source_tree,
                    "--dependency-lock-sha256", lock_digest,
                    "--plugin-release-manifest-sha256", str(staged_plugin_manifest["manifest_sha256"]),
                    "--wheel", str(wheels[0]),
                    "--launcher", str(launcher),
                    *([] if cli_launcher is None else ["--cli-launcher", str(cli_launcher)]),
                    "--ownership-manifest", str(ownership_path),
                ],
                cwd=transaction,
            ),
            "runtime receipt builder",
        )
        receipt = receipt_result.get("receipt")
        if not isinstance(receipt, dict):
            raise RuntimeBuildError("runtime receipt builder returned no receipt")
        (staging / RUNTIME_RECEIPT_NAME).write_bytes(
            integrity.pretty_json_bytes(receipt)
        )
        _verify_with_runtime(
            runtime_dir=staging,
            recorded_target=target,
            helper=verifier,
            launcher=launcher,
            release_id=release_id,
            allow_staging=True,
        )
        retained: Path | None = None
        if _target_exists(target):
            retained = releases / "retained-{}-{}-{}".format(
                release_id,
                int(time.time_ns()),
                os.getpid(),
            )
            target.rename(retained)
            retained_paths.append(str(retained))
        try:
            os.replace(staging, target)
        except OSError:
            if retained is not None and not _target_exists(target):
                try:
                    retained.rename(target)
                    retained_paths.clear()
                except OSError:
                    pass
            raise
        final_helper = target / "integrity" / "runtime_integrity.py"
        final_launcher = target / "launchers" / launcher.name
        receipt = _verify_with_runtime(
            runtime_dir=target,
            recorded_target=target,
            helper=final_helper,
            launcher=final_launcher,
            release_id=release_id,
            allow_staging=False,
        )
        return _runtime_result(
            target,
            receipt,
            reused=False,
            retained_paths=retained_paths,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--source-root")
    parser.add_argument("--artifact-root")
    parser.add_argument("--release-index")
    parser.add_argument("--release-index-sha256")
    parser.add_argument("--transaction-id")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--source-tree")
    parser.add_argument("--release-id")
    parser.add_argument("--data-root")
    selected_argv = list(sys.argv[1:] if argv is None else argv)
    seen_options: set[str] = set()
    for token in selected_argv:
        if token.startswith("--"):
            option = token.partition("=")[0]
            if option in seen_options:
                print(
                    json.dumps(
                        {"ok": False, "error": "repeated runtime option is rejected: " + option},
                        sort_keys=True,
                    )
                )
                return 1
            seen_options.add(option)
    arguments = parser.parse_args(selected_argv)
    try:
        if "DEV_FLOW_SOURCE_ROOT" in os.environ:
            raise RuntimeBuildError(
                "DEV_FLOW_SOURCE_ROOT is unsupported; rerun the exact-version artifact bootstrap"
            )
        if arguments.artifact_root is not None:
            if arguments.source_root is not None:
                raise RuntimeBuildError("artifact and checkout runtime inputs are mutually exclusive")
            if (
                arguments.release_index is None
                or arguments.release_index_sha256 is None
                or arguments.transaction_id is None
            ):
                raise RuntimeBuildError("artifact runtime inputs are incomplete")
            result = build_artifact_candidate(
                Path(arguments.artifact_root),
                Path(arguments.runtime_root),
                Path(arguments.release_index),
                arguments.release_index_sha256,
                arguments.transaction_id,
                Path(arguments.data_root) if arguments.data_root else None,
                expected_release_id=arguments.release_id,
            )
        else:
            raise RuntimeBuildError(
                "checkout-driven runtime construction is unsupported; "
                "rerun the exact-version artifact bootstrap"
            )
    except (OSError, RuntimeBuildError, ValueError, integrity.IntegrityError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
