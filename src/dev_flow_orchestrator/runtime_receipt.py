"""Strict managed MCP runtime receipt authority.

The receipt contains installation identity only. It deliberately excludes the
task-data root, source checkout path, runtime path, and executable path.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ._version import RELEASE_VERSION
from .model import DevFlowError, strict_json_loads


RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/1.0.0"
RUNTIME_RECEIPT_NAME = "runtime-receipt.json"
MAX_RUNTIME_RECEIPT_BYTES = 8 * 1024
MCP_LAUNCHER_IDENTITY = "dev-flow-mcp --stdio"
_LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_PYTHON_VERSION = re.compile(r"^(3)\.(1[0-4])\.(0|[1-9][0-9]*)$")
_ARCHITECTURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_runtime_receipt(
    *,
    source_commit: str,
    dependency_lock_digest: str,
    launcher_identity: str,
    runtime_identity: str,
    activation_action: str,
    python_executable: str | Path = sys.executable,
) -> dict[str, object]:
    if not isinstance(source_commit, str) or not _LOWER_HEX_40.fullmatch(source_commit):
        raise DevFlowError("RUNTIME_RECEIPT_INVALID", "source commit must be a full lowercase Git object id")
    if not isinstance(dependency_lock_digest, str) or not _LOWER_HEX_64.fullmatch(dependency_lock_digest):
        raise DevFlowError("RUNTIME_RECEIPT_INVALID", "dependency lock digest must be lowercase SHA-256")
    if launcher_identity != MCP_LAUNCHER_IDENTITY:
        raise DevFlowError("RUNTIME_RECEIPT_INVALID", "MCP launcher identity is invalid")
    if not isinstance(runtime_identity, str) or not _LOWER_HEX_64.fullmatch(runtime_identity):
        raise DevFlowError("RUNTIME_RECEIPT_INVALID", "managed runtime location identity is invalid")
    if activation_action not in {"create", "update"}:
        raise DevFlowError("RUNTIME_RECEIPT_INVALID", "managed runtime activation action is invalid")
    value = {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_version": RELEASE_VERSION,
        "source_commit": source_commit,
        "python": {
            "executable_sha256": sha256_file(python_executable),
            "version": platform.python_version(),
            "architecture": platform.machine(),
            "bits": 64 if sys.maxsize > 2**32 else 32,
        },
        "dependency_lock_sha256": dependency_lock_digest,
        "launcher_identity": launcher_identity,
        "runtime_identity": runtime_identity,
        "activation_action": activation_action,
        "activated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return validate_runtime_receipt(value)


def _invalid(message: str) -> DevFlowError:
    return DevFlowError("RUNTIME_RECEIPT_INVALID", message)


def _validated_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or len(value.encode("utf-8")) > 64:
        raise _invalid("runtime receipt activation timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _invalid("runtime receipt activation timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _invalid("runtime receipt activation timestamp must be UTC")
    return value


def validate_runtime_receipt(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid("runtime receipt must be an object")
    required = {
        "schema", "release_version", "source_commit", "python",
        "dependency_lock_sha256", "launcher_identity", "runtime_identity",
        "activation_action", "activated_at",
    }
    if set(value) != required or any(not isinstance(key, str) for key in value):
        raise _invalid("runtime receipt fields are invalid")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _invalid("runtime receipt is not canonical JSON") from exc
    if len(encoded) > MAX_RUNTIME_RECEIPT_BYTES:
        raise _invalid("runtime receipt exceeds the supported byte limit")
    if value.get("schema") != RUNTIME_RECEIPT_SCHEMA or value.get("release_version") != RELEASE_VERSION:
        raise _invalid("runtime receipt identity is incompatible")

    commit = value.get("source_commit")
    lock = value.get("dependency_lock_sha256")
    launcher = value.get("launcher_identity")
    runtime_identity = value.get("runtime_identity")
    activation_action = value.get("activation_action")
    python = value.get("python")
    if not isinstance(commit, str) or not _LOWER_HEX_40.fullmatch(commit):
        raise _invalid("runtime receipt source commit is invalid")
    if not isinstance(lock, str) or not _LOWER_HEX_64.fullmatch(lock):
        raise _invalid("runtime receipt lock digest is invalid")
    if launcher != MCP_LAUNCHER_IDENTITY:
        raise _invalid("runtime receipt launcher identity is invalid")
    if not isinstance(runtime_identity, str) or not _LOWER_HEX_64.fullmatch(runtime_identity):
        raise _invalid("runtime receipt managed location identity is invalid")
    if activation_action not in {"create", "update"}:
        raise _invalid("runtime receipt activation action is invalid")
    if not isinstance(python, Mapping) or set(python) != {
        "executable_sha256", "version", "architecture", "bits",
    }:
        raise _invalid("runtime receipt Python identity is invalid")
    executable_digest = python.get("executable_sha256")
    version = python.get("version")
    architecture = python.get("architecture")
    bits = python.get("bits")
    if not isinstance(executable_digest, str) or not _LOWER_HEX_64.fullmatch(executable_digest):
        raise _invalid("runtime receipt Python executable digest is invalid")
    if not isinstance(version, str) or not _PYTHON_VERSION.fullmatch(version):
        raise _invalid("managed MCP runtime requires Python 3.10 through 3.14")
    if not isinstance(architecture, str) or not _ARCHITECTURE.fullmatch(architecture):
        raise _invalid("runtime receipt Python architecture is invalid")
    if isinstance(bits, bool) or bits != 64:
        raise _invalid("managed MCP runtime requires 64-bit Python")
    activated_at = _validated_timestamp(value.get("activated_at"))
    return {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_version": RELEASE_VERSION,
        "source_commit": commit,
        "python": {
            "executable_sha256": executable_digest,
            "version": version,
            "architecture": architecture,
            "bits": 64,
        },
        "dependency_lock_sha256": lock,
        "launcher_identity": MCP_LAUNCHER_IDENTITY,
        "runtime_identity": runtime_identity,
        "activation_action": activation_action,
        "activated_at": activated_at,
    }


def read_runtime_receipt(path: str | Path) -> dict[str, object]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise _invalid("runtime receipt cannot be read") from exc
    if len(raw) > MAX_RUNTIME_RECEIPT_BYTES:
        raise _invalid("runtime receipt exceeds the supported byte limit")
    try:
        value = strict_json_loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise _invalid("runtime receipt must be strict UTF-8 JSON") from exc
    return validate_runtime_receipt(value)
