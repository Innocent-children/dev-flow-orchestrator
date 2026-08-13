#!/usr/bin/env python3
"""Stable, standard-library dispatch for an attested managed release.

This module is installation infrastructure.  It deliberately performs only
the small trust transition needed to select the active release and verify the
versioned verifier before that verifier is allowed to run.  Full receipt and
installed-content validation remains versioned inside the managed release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence


ACTIVE_SCHEMA = "dev-flow-active-release/1.0.0"
RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/3.0.0"
INSTALLATION_SCHEMA = "dev-flow-lifecycle-installation/2.0.0"
DISPATCHER_PROTOCOL = "dev-flow-dispatcher/1.0.0"
MAX_ACTIVE_BYTES = 16 * 1024
MAX_RECEIPT_BYTES = 512 * 1024
MAX_INSTALLATION_BYTES = 32 * 1024
_HEX = frozenset("0123456789abcdef")
_RECOVERY_PREFIX = ".dev-flow-uninstall-recovery-"
_SUPPORT_NAMES = (
    "stable_dispatcher.py",
    "lifecycle_state.py",
    "uninstall_driver.py",
    "installation.json",
)
_DATA_OWNED_PATHS = ["0.4.0", "web-runtime"]
_DATA_MARKER_NAME = "dev-flow-data.json"


class DispatchError(RuntimeError):
    """An installed authority could not be proven without importing it."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DispatchError("JSON contains a duplicate object member")
        result[key] = value
    return result


def _read_json(path: Path, maximum: int, label: str) -> tuple[dict[str, object], bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DispatchError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise DispatchError(f"{label} must be a regular file")
    if _is_reparse(metadata):
        raise DispatchError(f"{label} must not be a reparse point")
    if metadata.st_size > maximum:
        raise DispatchError(f"{label} exceeds its byte limit")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DispatchError(f"{label} cannot be read") from exc
    if len(raw) > maximum:
        raise DispatchError(f"{label} exceeds its byte limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise DispatchError(f"{label} must be a JSON object")
    return value, raw


def _is_reparse(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & flag)


def _hex_digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise DispatchError(f"{label} is invalid")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path, label: str) -> str:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DispatchError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise DispatchError(f"{label} must be a regular file")
    if _is_reparse(metadata):
        raise DispatchError(f"{label} must not be a reparse point")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise DispatchError(f"{label} cannot be read") from exc
    return digest.hexdigest()


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


def _sha256_python(path: Path) -> str:
    """Hash the venv-selected executable, allowing the normal POSIX venv link."""

    try:
        selected = path.lstat()
    except OSError as exc:
        raise DispatchError("managed Python executable is unavailable") from exc
    if _is_reparse(selected):
        raise DispatchError("managed Python executable must not be a reparse point")
    if stat.S_ISREG(selected.st_mode):
        target = path
    elif stat.S_ISLNK(selected.st_mode) and os.name != "nt":
        try:
            target = path.resolve(strict=True)
            target_metadata = target.lstat()
        except OSError as exc:
            raise DispatchError("managed Python executable link is invalid") from exc
        if not stat.S_ISREG(target_metadata.st_mode) or _is_reparse(target_metadata):
            raise DispatchError("managed Python executable link target is not regular")
    else:
        raise DispatchError("managed Python executable is not a supported file")
    return _sha256_file(target, "managed Python executable target")


def _absolute_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise DispatchError(f"{label} must be absolute")
    path = Path(os.path.abspath(path))
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DispatchError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise DispatchError(f"{label} must be a regular directory")
    if _is_reparse(metadata):
        raise DispatchError(f"{label} must not be a reparse point")
    return path


def _contained_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not os.path.isabs(value):
        raise DispatchError(f"{label} must be an absolute path")
    path = Path(os.path.abspath(value))
    try:
        if os.path.commonpath((str(root), str(path))) != str(root) or path == root:
            raise DispatchError(f"{label} escapes the managed releases root")
    except ValueError as exc:
        raise DispatchError(f"{label} is not on the managed volume") from exc
    relative = path.relative_to(root)
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            raise DispatchError(f"{label} has an unavailable ancestor") from exc
        if stat.S_ISLNK(metadata.st_mode) or _is_reparse(metadata):
            raise DispatchError(f"{label} crosses a link or reparse point")
    return path


def _validate_active(value: Mapping[str, object], releases_root: Path) -> dict[str, object]:
    fields = {
        "schema",
        "generation",
        "release_id",
        "release_path",
        "receipt_sha256",
        "dispatcher_protocol",
        "transaction_id",
    }
    if set(value) != fields or value.get("schema") != ACTIVE_SCHEMA:
        raise DispatchError("active record fields or schema are incompatible")
    generation = value.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise DispatchError("active generation is invalid")
    release_id = value.get("release_id")
    transaction_id = value.get("transaction_id")
    if not isinstance(release_id, str) or not release_id or len(release_id) > 128:
        raise DispatchError("active release ID is invalid")
    if not isinstance(transaction_id, str) or not transaction_id or len(transaction_id) > 128:
        raise DispatchError("active transaction ID is invalid")
    if value.get("dispatcher_protocol") != DISPATCHER_PROTOCOL:
        raise DispatchError("active dispatcher protocol is incompatible")
    release_path = _contained_path(releases_root, value.get("release_path"), "active release path")
    if release_path.name != release_id:
        raise DispatchError("active release path disagrees with its release ID")
    return {
        "schema": ACTIVE_SCHEMA,
        "generation": generation,
        "release_id": release_id,
        "release_path": str(release_path),
        "receipt_sha256": _hex_digest(value.get("receipt_sha256"), "active receipt digest"),
        "dispatcher_protocol": DISPATCHER_PROTOCOL,
        "transaction_id": transaction_id,
    }


def resolve_active(runtime_root: Path) -> dict[str, object]:
    """Resolve the one active authority without importing managed code."""

    runtime_root = _absolute_directory(runtime_root, "managed runtime root")
    releases_root = _absolute_directory(runtime_root / "releases", "managed releases root")
    active_value, _ = _read_json(runtime_root / "active.json", MAX_ACTIVE_BYTES, "active record")
    active = _validate_active(active_value, releases_root)
    release_path = Path(str(active["release_path"]))
    receipt_path = release_path / "runtime-receipt.json"
    receipt, raw_receipt = _read_json(receipt_path, MAX_RECEIPT_BYTES, "runtime receipt")
    if _sha256(raw_receipt) != active["receipt_sha256"]:
        raise DispatchError("runtime receipt digest differs from the active record")
    if receipt.get("schema") != RUNTIME_RECEIPT_SCHEMA:
        raise DispatchError("runtime receipt schema is incompatible")
    if receipt.get("release_id") != active["release_id"]:
        raise DispatchError("runtime receipt release ID differs from the active record")
    if receipt.get("runtime_path") != active["release_path"]:
        raise DispatchError("runtime receipt path differs from the active record")
    if receipt.get("transaction_id") != active["transaction_id"]:
        raise DispatchError("runtime receipt transaction differs from the active record")
    verifier = release_path / "integrity" / "runtime_integrity.py"
    expected_verifier = _hex_digest(receipt.get("verifier_sha256"), "runtime verifier digest")
    if _sha256_file(verifier, "versioned runtime verifier") != expected_verifier:
        raise DispatchError("versioned runtime verifier digest differs from the receipt")
    runtime_python = release_path / "venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    runtime_python_digest = _hex_digest(
        receipt.get("python_executable_sha256"), "managed Python executable digest"
    )
    if _sha256_python(runtime_python) != runtime_python_digest:
        raise DispatchError("managed Python executable digest differs from the receipt")
    return {
        "active": active,
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "verifier": str(verifier),
        "runtime_python": str(runtime_python),
    }


def prepare_active_command(runtime_root: Path, mode: str, arguments: Sequence[str]) -> list[str]:
    if mode not in {"cli", "mcp"}:
        raise DispatchError("dispatcher mode is invalid")
    if mode == "mcp" and list(arguments) != ["--stdio"]:
        raise DispatchError("dev-flow-mcp accepts exactly --stdio")
    resolved = resolve_active(runtime_root)
    verifier_arguments = [
        str(resolved["runtime_python"]),
        "-B",
        "-I",
        str(resolved["verifier"]),
        "launch-cli" if mode == "cli" else "launch-mcp",
        "--runtime",
        str(resolved["active"]["release_path"]),
        "--",
        *arguments,
    ]
    return verifier_arguments


def _installation_contract(
    support_root: Path,
    runtime_root: Path | None = None,
) -> tuple[dict[str, object], bytes, dict[str, str], str]:
    installation, installation_raw = _read_json(
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
    if set(installation) != fields or installation.get("schema") != INSTALLATION_SCHEMA:
        raise DispatchError("lifecycle installation record is incompatible")
    if installation.get("dispatcher_protocol") != DISPATCHER_PROTOCOL:
        raise DispatchError("lifecycle dispatcher protocol is incompatible")
    expected_dispatcher = _hex_digest(
        installation.get("stable_dispatcher_sha256"), "stable dispatcher digest"
    )
    expected_state = _hex_digest(
        installation.get("lifecycle_state_sha256"), "lifecycle state digest"
    )
    dispatchers = installation.get("dispatchers")
    expected_names = (
        {"dev-flow.cmd", "dev-flow-mcp.cmd", "dev-flow-uninstall.cmd"}
        if os.name == "nt"
        else {"dev-flow", "dev-flow-mcp", "dev-flow-uninstall"}
    )
    if not isinstance(dispatchers, Mapping) or set(dispatchers) != expected_names:
        raise DispatchError("installed dispatcher evidence is invalid")
    for name in sorted(expected_names):
        _hex_digest(dispatchers.get(name), f"{name} digest")
    bin_dir = installation.get("bin_dir")
    if not isinstance(bin_dir, str) or not os.path.isabs(bin_dir):
        raise DispatchError("installed dispatcher directory is invalid")
    marketplace_file = installation.get("marketplace_file")
    if not isinstance(marketplace_file, str) or not os.path.isabs(marketplace_file):
        raise DispatchError("installed marketplace path is invalid")
    codex_home = installation.get("codex_home")
    if not isinstance(codex_home, str) or not os.path.isabs(codex_home):
        raise DispatchError("installed Codex home path is invalid")
    if installation.get("plugin_id") != "dev-flow-orchestrator@personal":
        raise DispatchError("installed plugin identity is invalid")
    _hex_digest(
        installation.get("release_commands_sha256"), "release commands digest"
    )
    _hex_digest(
        installation.get("release_resolver_sha256"), "release resolver digest"
    )
    recorded_runtime = installation.get("runtime_root")
    if (
        not isinstance(recorded_runtime, str)
        or not os.path.isabs(recorded_runtime)
    ):
        raise DispatchError("installed runtime root evidence is invalid")
    if runtime_root is not None:
        selected_runtime = _absolute_directory(runtime_root, "managed runtime root")
        if os.path.normcase(os.path.abspath(recorded_runtime)) != os.path.normcase(
            str(selected_runtime)
        ):
            raise DispatchError("installed runtime root evidence is invalid")
    data_root = installation.get("data_root")
    if not isinstance(data_root, str) or not os.path.isabs(data_root):
        raise DispatchError("installed task-data root is invalid")
    owned_paths = installation.get("data_owned_paths")
    if owned_paths != _DATA_OWNED_PATHS:
        raise DispatchError("installed data ownership paths are invalid")
    marker_name = installation.get("data_marker_name")
    if marker_name != _DATA_MARKER_NAME:
        raise DispatchError("installed data marker name is invalid")
    expected_driver = _hex_digest(
        installation.get("uninstall_driver_sha256"), "uninstall driver digest"
    )
    expected = {
        "stable_dispatcher.py": expected_dispatcher,
        "lifecycle_state.py": expected_state,
        "uninstall_driver.py": expected_driver,
        "installation.json": _sha256(installation_raw),
    }
    for name, digest in expected.items():
        if _sha256_file(support_root / name, f"uninstall support {name}") != digest:
            label = {
                "stable_dispatcher.py": "stable dispatcher",
                "lifecycle_state.py": "installed lifecycle state helper",
                "uninstall_driver.py": "uninstall driver",
                "installation.json": "installation record",
            }[name]
            raise DispatchError(f"{label} digest differs from installation evidence")
    return installation, installation_raw, expected, bin_dir


def _prepare_release_command(
    runtime_root: Path, mode: str, temporary_prefix: str = "dev-flow-lifecycle-"
) -> tuple[list[str], Path]:
    """Verify and copy the update/reinstall driver outside the runtime."""

    if mode not in {"update", "reinstall"}:
        raise DispatchError("lifecycle command mode is invalid")
    runtime_root = _absolute_directory(runtime_root, "managed runtime root")
    lifecycle_root = runtime_root / "lifecycle"
    running_dispatcher = Path(os.path.abspath(__file__))
    if os.path.normcase(str(running_dispatcher)) != os.path.normcase(
        str(lifecycle_root / "stable_dispatcher.py")
    ):
        raise DispatchError(
            "lifecycle commands require the installed stable dispatcher"
        )
    support_root = _absolute_directory(lifecycle_root, "lifecycle support root")
    installation, _raw, expected, _bin_dir = _installation_contract(
        support_root, runtime_root
    )
    if _sha256_file(running_dispatcher, "running stable dispatcher") != expected[
        "stable_dispatcher.py"
    ]:
        raise DispatchError(
            "running stable dispatcher digest differs from installation evidence"
        )
    expected_commands = _hex_digest(
        installation.get("release_commands_sha256"), "release commands digest"
    )
    if _sha256_file(support_root / "release_commands.py", "release command driver") != expected_commands:
        raise DispatchError(
            "release command driver digest differs from installation evidence"
        )
    temporary_root = Path(tempfile.mkdtemp(prefix=temporary_prefix))
    copied = temporary_root / "release_commands.py"
    try:
        with copied.open("xb") as output, (
            support_root / "release_commands.py"
        ).open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush()
            os.fsync(output.fileno())
        if _sha256_file(copied, "copied release command driver") != expected_commands:
            raise DispatchError("copied release command driver digest is invalid")
    except BaseException:
        try:
            copied.unlink()
            temporary_root.rmdir()
        except OSError:
            pass
        raise
    command = [
        sys.executable,
        "-B",
        "-I",
        str(copied),
        "--runtime-root",
        str(runtime_root),
        "--support-root",
        str(support_root),
        "--mode",
        mode,
    ]
    return command, temporary_root


def _prepare_uninstall(runtime_root: Path) -> tuple[list[str], Path]:
    runtime_root = _absolute_directory(runtime_root, "managed runtime root")
    lifecycle_root = runtime_root / "lifecycle"
    recovery_root = _recovery_root(runtime_root)
    running_dispatcher = Path(os.path.abspath(__file__))
    if os.path.normcase(str(running_dispatcher)) == os.path.normcase(
        str(lifecycle_root / "stable_dispatcher.py")
    ):
        support_root = _absolute_directory(
            lifecycle_root, "lifecycle support root"
        )
        installation, _raw, expected, bin_dir = _installation_contract(
            support_root, runtime_root
        )
        temporary_root = Path(tempfile.mkdtemp(prefix="dev-flow-uninstall-"))
        copied = temporary_root / "uninstall_driver.py"
        try:
            with copied.open("xb") as output, (
                support_root / "uninstall_driver.py"
            ).open("rb") as input_stream:
                shutil.copyfileobj(input_stream, output)
                output.flush()
                os.fsync(output.fileno())
            if _sha256_file(copied, "copied uninstall driver") != expected[
                "uninstall_driver.py"
            ]:
                raise DispatchError("copied uninstall driver digest is invalid")
        except BaseException:
            try:
                copied.unlink()
                temporary_root.rmdir()
            except OSError:
                pass
            raise
    elif os.path.normcase(str(running_dispatcher)) == os.path.normcase(
        str(recovery_root / "stable_dispatcher.py")
    ):
        support_root = _absolute_directory(
            recovery_root, "uninstall recovery support root"
        )
        installation, _raw, expected, bin_dir = _installation_contract(
            support_root, runtime_root
        )
        temporary_root = support_root
    else:
        raise DispatchError("running stable dispatcher is outside installed support")
    if _sha256_file(running_dispatcher, "running stable dispatcher") != expected[
        "stable_dispatcher.py"
    ]:
        raise DispatchError(
            "running stable dispatcher digest differs from installation evidence"
        )
    copied = temporary_root / "uninstall_driver.py"
    command = [
        sys.executable,
        "-B",
        "-I",
        str(copied),
        "--runtime-root",
        str(runtime_root),
        "--bin-dir",
        bin_dir,
        "--temporary-root",
        str(temporary_root),
        "--support-root",
        str(support_root),
    ]
    return command, temporary_root


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("mode", choices=("cli", "mcp", "uninstall"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    forwarded = list(arguments.arguments)
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    try:
        if arguments.mode == "cli" and forwarded[:1] in (["update"], ["reinstall"]):
            # Lifecycle commands are recognized and handled before the active
            # release is resolved, so they stay executable when it cannot start.
            if len(forwarded) != 1:
                raise DispatchError(
                    "dev-flow {} accepts no arguments".format(forwarded[0])
                )
            command, temporary_root = _prepare_release_command(
                arguments.runtime_root, forwarded[0]
            )
            try:
                return subprocess.run(command, check=False).returncode
            finally:
                try:
                    (temporary_root / "release_commands.py").unlink()
                    temporary_root.rmdir()
                except OSError:
                    print(
                        "Dev Flow temporary lifecycle helper retained at: "
                        f"{temporary_root}",
                        file=sys.stderr,
                    )
        if arguments.mode == "uninstall":
            if forwarded:
                raise DispatchError("dev-flow-uninstall accepts no arguments")
            command, temporary_root = _prepare_uninstall(arguments.runtime_root)
            try:
                return subprocess.run(command, check=False).returncode
            finally:
                if temporary_root.name.startswith("dev-flow-uninstall-"):
                    try:
                        (temporary_root / "uninstall_driver.py").unlink()
                        temporary_root.rmdir()
                    except OSError:
                        print(
                            "Dev Flow temporary uninstall helper retained at: "
                            f"{temporary_root}",
                            file=sys.stderr,
                        )
        command = prepare_active_command(arguments.runtime_root, arguments.mode, forwarded)
        os.execv(command[0], command)
    except DispatchError as exc:
        print(
            "Dev Flow startup attestation failed: {}. Rerun the exact-version bootstrap for repair.".format(exc),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
