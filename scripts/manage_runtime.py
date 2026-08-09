#!/usr/bin/env python3
"""Build or completely verify one sealed Dev Flow managed runtime release."""

# The external runtime_receipt authority is verified before reuse and launch.

from __future__ import annotations

import argparse
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


sys.dont_write_bytecode = True
SCRIPT_ROOT = Path(__file__).resolve().parent
_HELPER_PATH = SCRIPT_ROOT / "runtime_integrity.py"
_HELPER_SPEC = importlib.util.spec_from_file_location("dev_flow_runtime_integrity", _HELPER_PATH)
if _HELPER_SPEC is None or _HELPER_SPEC.loader is None:
    raise RuntimeError("managed runtime integrity helper cannot be loaded")
integrity = importlib.util.module_from_spec(_HELPER_SPEC)
_HELPER_SPEC.loader.exec_module(integrity)


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
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_environment:
        environment.update(extra_environment)
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
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
            "--smoke-only",
        ],
        cwd=scratch,
    )
    evidence = _json_output(completed, "staged MCP STDIO smoke")
    journey = evidence.get("journey")
    if (
        not isinstance(journey, dict)
        or journey.get("read_smoke") is not True
        or journey.get("mutation_smoke") is not True
        or journey.get("terminal_status") != "CANCELLED"
    ):
        raise RuntimeBuildError("staged MCP STDIO initialize/catalog/read/mutation smoke failed")


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--data-root")
    arguments = parser.parse_args(argv)
    try:
        result = build(
            Path(arguments.source_root),
            Path(arguments.runtime_root),
            arguments.source_commit,
            arguments.source_tree,
            arguments.release_id,
            Path(arguments.data_root) if arguments.data_root else None,
        )
    except (OSError, RuntimeBuildError, ValueError, integrity.IntegrityError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
