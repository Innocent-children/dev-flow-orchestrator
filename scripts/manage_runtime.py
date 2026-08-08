#!/usr/bin/env python3
"""Build and validate the isolated Dev Flow MCP runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any


SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

from dev_flow_orchestrator._version import RELEASE_VERSION  # noqa: E402
from dev_flow_orchestrator.runtime_receipt import (  # noqa: E402
    RUNTIME_RECEIPT_NAME,
    build_runtime_receipt,
    read_runtime_receipt,
    sha256_file,
)


ROOT_MARKER = ".dev-flow-managed-runtime"


class RuntimeBuildError(RuntimeError):
    pass


def _run(arguments: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
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
                completed.stderr.strip()[-2048:],
            )
        )
    return completed


def _inside(left: Path, right: Path) -> bool:
    try:
        left.relative_to(right)
        return True
    except ValueError:
        return False


def _python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _runtime_identity(release_path: Path) -> str:
    canonical_location = os.path.normcase(str(release_path.resolve()))
    return hashlib.sha256(
        canonical_location.encode("utf-8")
    ).hexdigest()


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
    completed = _run([str(runtime_python), "-I", "-c", code], cwd=scratch)
    try:
        value = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeBuildError("managed runtime Python probe returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeBuildError("managed runtime Python probe returned an invalid result")
    version = value.get("version")
    if (
        not isinstance(version, list)
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


def _smoke(source_root: Path, runtime_python: Path, scratch: Path) -> None:
    """Exercise the staged wheel over real STDIO through the official client."""
    runner = source_root / "scripts" / "validate_installed_stage1.py"
    if not runner.is_file():
        raise RuntimeBuildError("candidate is missing the installed MCP acceptance runner")
    completed = _run(
        [
            str(runtime_python),
            "-I",
            str(runner),
            "--plugin-root",
            str(source_root),
            "--launcher",
            str(runtime_python),
            "--launcher-arg=-I",
            "--launcher-arg=-m",
            "--launcher-arg=dev_flow_orchestrator.mcp",
            "--smoke-only",
        ],
        cwd=scratch,
    )
    try:
        evidence = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeBuildError("staged MCP STDIO smoke returned invalid evidence") from exc
    journey = evidence.get("journey") if isinstance(evidence, dict) else None
    if (
        not isinstance(evidence, dict)
        or evidence.get("ok") is not True
        or not isinstance(journey, dict)
        or journey.get("read_smoke") is not True
        or journey.get("mutation_smoke") is not True
        or journey.get("terminal_status") != "CANCELLED"
    ):
        raise RuntimeBuildError("staged MCP STDIO initialize/catalog/read/mutation smoke failed")


def _validate_runtime(
    *,
    target: Path,
    source_commit: str,
    lock_digest: str,
    runtime_identity: str,
) -> tuple[dict[str, object], Path]:
    receipt = read_runtime_receipt(target / RUNTIME_RECEIPT_NAME)
    runtime_python = _python(target / "venv")
    if (
        receipt.get("source_commit") != source_commit
        or receipt.get("dependency_lock_sha256") != lock_digest
        or receipt.get("launcher_identity") != "dev-flow-mcp --stdio"
        or receipt.get("runtime_identity") != runtime_identity
        or not runtime_python.is_file()
    ):
        raise RuntimeBuildError("existing managed runtime receipt does not match verified inputs")
    python_receipt = receipt.get("python")
    if (
        not isinstance(python_receipt, dict)
        or python_receipt.get("executable_sha256") != sha256_file(runtime_python)
    ):
        raise RuntimeBuildError("managed runtime Python does not match its ownership receipt")
    probe = _python_probe(runtime_python, target)
    version = probe["version"]
    if (
        python_receipt.get("version") != "{}.{}.{}".format(*version)
        or python_receipt.get("architecture") != probe["architecture"]
        or python_receipt.get("bits") != probe["bits"]
    ):
        raise RuntimeBuildError("managed runtime Python identity drifted from its receipt")
    return receipt, runtime_python


def _validate_owned_releases(releases: Path) -> int:
    if not releases.exists():
        return 0
    if not releases.is_dir() or releases.is_symlink():
        raise RuntimeBuildError("managed runtime releases path is not a regular directory")
    count = 0
    for release in releases.iterdir():
        if not release.is_dir() or release.is_symlink():
            raise RuntimeBuildError("managed runtime contains a non-release entry")
        receipt = read_runtime_receipt(release / RUNTIME_RECEIPT_NAME)
        expected_name = "{}-{}-{}".format(
            receipt["release_version"],
            str(receipt["source_commit"])[:12],
            str(receipt["dependency_lock_sha256"])[:12],
        )
        runtime_python = _python(release / "venv")
        python_receipt = receipt.get("python")
        if (
            release.name != expected_name
            or receipt.get("runtime_identity") != _runtime_identity(release)
            or not runtime_python.is_file()
            or not isinstance(python_receipt, dict)
            or python_receipt.get("executable_sha256") != sha256_file(runtime_python)
        ):
            raise RuntimeBuildError("managed runtime contains an unverified prior release")
        count += 1
    return count


def build(source_root: Path, runtime_root: Path, source_commit: str, data_root: Path | None) -> dict:
    source_root = source_root.expanduser().resolve()
    selected_runtime_root = runtime_root.expanduser()
    if selected_runtime_root.is_symlink():
        raise RuntimeBuildError("managed runtime root must not be a symbolic link")
    runtime_root_existed = selected_runtime_root.exists()
    runtime_root = selected_runtime_root.resolve()
    if not (source_root / "uv.lock").is_file() or not (source_root / "pyproject.toml").is_file():
        raise RuntimeBuildError("verified source is missing pyproject.toml or uv.lock")
    if (
        len(source_commit) != 40
        or any(character not in "0123456789abcdef" for character in source_commit)
    ):
        raise RuntimeBuildError("verified source commit must be a full lowercase Git object id")
    if _inside(runtime_root, source_root) or _inside(source_root, runtime_root):
        raise RuntimeBuildError("managed runtime and verified source must be disjoint")
    if data_root is not None:
        data_root = data_root.expanduser().resolve()
        if _inside(runtime_root, data_root) or _inside(data_root, runtime_root):
            raise RuntimeBuildError("managed runtime and task data must be disjoint")
    if not ((3, 10) <= sys.version_info[:2] < (3, 15)) or struct.calcsize("P") != 8:
        raise RuntimeBuildError("managed runtime requires 64-bit Python 3.10 through 3.14")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeBuildError("uv is required to build the exact locked MCP runtime")

    lock_digest = sha256_file(source_root / "uv.lock")
    release_name = "{}-{}-{}".format(RELEASE_VERSION, source_commit[:12], lock_digest[:12])
    releases = runtime_root / "releases"
    target = releases / release_name
    runtime_identity = _runtime_identity(target)
    receipt_path = target / RUNTIME_RECEIPT_NAME

    marker = runtime_root / ROOT_MARKER
    if runtime_root_existed:
        if not runtime_root.is_dir() or runtime_root.is_symlink():
            raise RuntimeBuildError("managed runtime root is not a regular directory")
        if (
            not marker.is_file()
            or marker.is_symlink()
            or marker.read_text(encoding="utf-8") != "dev-flow-managed-runtime/1\n"
        ):
            raise RuntimeBuildError("existing managed runtime root has no valid ownership marker")
    else:
        runtime_root.mkdir(parents=True, exist_ok=False)
        marker.write_text("dev-flow-managed-runtime/1\n", encoding="utf-8")
    prior_release_count = _validate_owned_releases(releases)
    if receipt_path.is_file():
        receipt, expected_python = _validate_runtime(
            target=target,
            source_commit=source_commit,
            lock_digest=lock_digest,
            runtime_identity=runtime_identity,
        )
        _smoke(source_root, expected_python, target)
        return {"ok": True, "reused": True, "runtime_dir": str(target), "receipt": receipt}
    if target.exists() or target.is_symlink():
        raise RuntimeBuildError("managed runtime target exists without a valid ownership receipt")

    releases.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=".build-", dir=str(releases)))
    try:
        venv = staging / "venv"
        requirements = staging / "requirements.txt"
        wheel_dir = staging / "dist"
        _run([uv, "venv", "--python", sys.executable, str(venv)], cwd=source_root)
        _run([
            uv, "export", "--locked", "--no-dev", "--no-emit-project",
            "--format", "requirements.txt", "--output-file", str(requirements),
        ], cwd=source_root)
        runtime_python = _python(venv)
        _run([uv, "pip", "install", "--python", str(runtime_python), "--require-hashes", "-r", str(requirements)], cwd=source_root)
        _run([uv, "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=source_root)
        wheels = tuple(wheel_dir.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeBuildError("runtime build did not produce exactly one wheel")
        _run([uv, "pip", "install", "--python", str(runtime_python), "--no-deps", str(wheels[0])], cwd=source_root)
        _python_probe(runtime_python, staging)
        _smoke(source_root, runtime_python, staging)
        receipt = build_runtime_receipt(
            source_commit=source_commit,
            dependency_lock_digest=lock_digest,
            launcher_identity="dev-flow-mcp --stdio",
            runtime_identity=runtime_identity,
            activation_action="update" if prior_release_count else "create",
            python_executable=runtime_python,
        )
        (staging / RUNTIME_RECEIPT_NAME).write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(str(staging), str(target))
        staging = None
        return {"ok": True, "reused": False, "runtime_dir": str(target), "receipt": receipt}
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--data-root")
    arguments = parser.parse_args(argv)
    try:
        result = build(
            Path(arguments.source_root),
            Path(arguments.runtime_root),
            arguments.source_commit,
            Path(arguments.data_root) if arguments.data_root else None,
        )
    except (OSError, RuntimeBuildError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
