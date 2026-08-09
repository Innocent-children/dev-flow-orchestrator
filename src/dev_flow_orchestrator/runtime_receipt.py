"""Strict exact-content receipt schema for the managed MCP runtime."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from datetime import datetime, timezone
from typing import Mapping

from .model import DevFlowError, strict_json_loads


RUNTIME_RECEIPT_SCHEMA = "dev-flow-runtime-receipt/2.0.0"
RUNTIME_RECEIPT_NAME = "runtime-receipt.json"
MAX_RUNTIME_RECEIPT_BYTES = 4 * 1024 * 1024
MCP_LAUNCHER_IDENTITY = "dev-flow-mcp --stdio"
_LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PYTHON_VERSION = re.compile(r"^3\.(?:10|11|12|13|14)\.(?:0|[1-9][0-9]*)$")
_ARCHITECTURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid(message: str) -> DevFlowError:
    return DevFlowError("RUNTIME_RECEIPT_INVALID", message)


def _digest(value: object, label: str, *, length: int = 64) -> str:
    pattern = _LOWER_HEX_40 if length == 40 else _LOWER_HEX_64
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _invalid("runtime receipt {} is invalid".format(label))
    return value


def _normalized_name(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid("runtime receipt distribution name is invalid")
    normalized = re.sub(r"[-_.]+", "-", value).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,199}", normalized):
        raise _invalid("runtime receipt distribution name is invalid")
    return normalized


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _invalid("runtime receipt installed file path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
        raise _invalid("runtime receipt installed file path is invalid")
    return value


def _distribution(value: object, *, project: bool) -> dict[str, object]:
    required = {"name", "version", "metadata_sha256", "record_sha256"}
    if project:
        required.add("files")
    if not isinstance(value, Mapping) or set(value) != required:
        raise _invalid("runtime receipt distribution fields are invalid")
    name = _normalized_name(value.get("name"))
    version = value.get("version")
    if not isinstance(version, str) or not version or len(version.encode("utf-8")) > 128:
        raise _invalid("runtime receipt distribution version is invalid")
    result: dict[str, object] = {
        "name": name,
        "version": version,
        "metadata_sha256": _digest(value.get("metadata_sha256"), "METADATA digest"),
        "record_sha256": _digest(value.get("record_sha256"), "RECORD digest"),
    }
    if project:
        if name != "dev-flow-orchestrator":
            raise _invalid("runtime receipt Dev Flow distribution name is invalid")
        raw_files = value.get("files")
        if not isinstance(raw_files, list):
            raise _invalid("runtime receipt installed file inventory is invalid")
        files: list[dict[str, str]] = []
        for item in raw_files:
            if not isinstance(item, Mapping) or set(item) != {"path", "sha256"}:
                raise _invalid("runtime receipt installed file entry is invalid")
            files.append({
                "path": _relative_path(item.get("path")),
                "sha256": _digest(item.get("sha256"), "installed file digest"),
            })
        paths = [item["path"] for item in files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise _invalid("runtime receipt installed file paths are not unique and sorted")
        result["files"] = files
    return result


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z") or len(value) > 64:
        raise _invalid("runtime receipt timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _invalid("runtime receipt timestamp is invalid") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _invalid("runtime receipt timestamp must be UTC")
    return value


def validate_runtime_receipt(value: object) -> dict[str, object]:
    required = {
        "schema", "release_id", "source_commit", "source_tree", "wheel_sha256",
        "plugin_path", "plugin_release_manifest_sha256", "dev_flow", "dependencies",
        "python", "runtime_path", "launcher_sha256", "ownership_manifest_sha256",
        "dependency_lock_sha256", "created_at",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise _invalid("runtime receipt fields are invalid")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _invalid("runtime receipt is not canonical JSON") from exc
    if len(encoded) > MAX_RUNTIME_RECEIPT_BYTES:
        raise _invalid("runtime receipt exceeds the supported byte limit")
    if value.get("schema") != RUNTIME_RECEIPT_SCHEMA:
        raise _invalid("runtime receipt schema is incompatible")
    release_id = value.get("release_id")
    if not isinstance(release_id, str) or not _RELEASE_ID.fullmatch(release_id):
        raise _invalid("runtime receipt release_id is invalid")
    runtime_path = value.get("runtime_path")
    plugin_path = value.get("plugin_path")
    if not isinstance(runtime_path, str) or not os.path.isabs(runtime_path):
        raise _invalid("runtime receipt managed path is invalid")
    runtime_path = os.path.abspath(runtime_path)
    if not isinstance(plugin_path, str) or os.path.abspath(plugin_path) != os.path.join(runtime_path, "plugin"):
        raise _invalid("runtime receipt plugin path is invalid")
    python = value.get("python")
    python_fields = {"path", "executable_sha256", "version", "architecture", "bits"}
    if not isinstance(python, Mapping) or set(python) != python_fields:
        raise _invalid("runtime receipt Python identity is invalid")
    python_path = python.get("path")
    if not isinstance(python_path, str) or not os.path.isabs(python_path):
        raise _invalid("runtime receipt Python path is invalid")
    try:
        if os.path.commonpath((runtime_path, os.path.abspath(python_path))) != runtime_path:
            raise _invalid("runtime receipt Python path escapes the managed release")
    except ValueError as exc:
        raise _invalid("runtime receipt Python path is invalid") from exc
    version = python.get("version")
    architecture = python.get("architecture")
    if not isinstance(version, str) or not _PYTHON_VERSION.fullmatch(version):
        raise _invalid("managed MCP runtime requires Python 3.10 through 3.14")
    if not isinstance(architecture, str) or not _ARCHITECTURE.fullmatch(architecture):
        raise _invalid("runtime receipt Python architecture is invalid")
    if isinstance(python.get("bits"), bool) or python.get("bits") != 64:
        raise _invalid("managed MCP runtime requires 64-bit Python")
    raw_dependencies = value.get("dependencies")
    if not isinstance(raw_dependencies, list):
        raise _invalid("runtime receipt dependency inventory is invalid")
    dependencies = [_distribution(item, project=False) for item in raw_dependencies]
    names = [str(item["name"]) for item in dependencies]
    if dependencies != sorted(dependencies, key=lambda item: (str(item["name"]), str(item["version"]))) or len(names) != len(set(names)):
        raise _invalid("runtime receipt dependency inventory is not unique and sorted")
    return {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "source_commit": _digest(value.get("source_commit"), "source commit", length=40),
        "source_tree": _digest(value.get("source_tree"), "source tree", length=40),
        "wheel_sha256": _digest(value.get("wheel_sha256"), "wheel digest"),
        "plugin_path": os.path.abspath(plugin_path),
        "plugin_release_manifest_sha256": _digest(
            value.get("plugin_release_manifest_sha256"), "plugin manifest digest"
        ),
        "dev_flow": _distribution(value.get("dev_flow"), project=True),
        "dependencies": dependencies,
        "python": {
            "path": os.path.abspath(python_path),
            "executable_sha256": _digest(
                python.get("executable_sha256"), "Python executable digest"
            ),
            "version": version,
            "architecture": architecture,
            "bits": 64,
        },
        "runtime_path": runtime_path,
        "launcher_sha256": _digest(value.get("launcher_sha256"), "launcher digest"),
        "ownership_manifest_sha256": _digest(
            value.get("ownership_manifest_sha256"), "ownership manifest digest"
        ),
        "dependency_lock_sha256": _digest(
            value.get("dependency_lock_sha256"), "dependency lock digest"
        ),
        "created_at": _timestamp(value.get("created_at")),
    }


def build_runtime_receipt(
    *,
    release_id: str,
    source_commit: str,
    source_tree: str,
    wheel_sha256: str,
    plugin_path: str | Path,
    plugin_release_manifest_sha256: str,
    dev_flow: Mapping[str, object],
    dependencies: list[Mapping[str, object]],
    python: Mapping[str, object],
    runtime_path: str | Path,
    launcher_sha256: str,
    ownership_manifest_sha256: str,
    dependency_lock_sha256: str,
    created_at: str | None = None,
) -> dict[str, object]:
    return validate_runtime_receipt({
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "release_id": release_id,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "wheel_sha256": wheel_sha256,
        "plugin_path": str(plugin_path),
        "plugin_release_manifest_sha256": plugin_release_manifest_sha256,
        "dev_flow": dict(dev_flow),
        "dependencies": [dict(item) for item in dependencies],
        "python": dict(python),
        "runtime_path": str(runtime_path),
        "launcher_sha256": launcher_sha256,
        "ownership_manifest_sha256": ownership_manifest_sha256,
        "dependency_lock_sha256": dependency_lock_sha256,
        "created_at": created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })


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
