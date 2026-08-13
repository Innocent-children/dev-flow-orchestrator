#!/usr/bin/env python3
"""Classify only the frozen checkout-based predecessor from installed evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from typing import Mapping

from scripts import runtime_integrity


SCRIPT_ROOT = Path(__file__).resolve().parent
FIXTURE_PATH = SCRIPT_ROOT / "legacy_predecessor.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_LAUNCHER_BYTES = 256 * 1024


class MigrationClassificationError(RuntimeError):
    """Installed observations do not prove the one supported predecessor."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationClassificationError("installed JSON contains duplicate keys")
        result[key] = value
    return result


def _read_json_with_raw(
    path: Path, *, maximum: int = MAX_JSON_BYTES
) -> tuple[dict[str, object], bytes]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MigrationClassificationError(f"installed evidence is missing: {path}") from exc
    reparse = bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode) or reparse:
        raise MigrationClassificationError(f"installed evidence is linked or special: {path}")
    if metadata.st_size > maximum:
        raise MigrationClassificationError(f"installed evidence exceeds its byte cap: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > maximum:
                raise MigrationClassificationError(
                    f"installed evidence changed type or size: {path}"
                )
            raw = stream.read(maximum + 1)
    except OSError as exc:
        raise MigrationClassificationError(f"installed evidence cannot be read: {path}") from exc
    if len(raw) > maximum:
        raise MigrationClassificationError(f"installed evidence exceeds its byte cap: {path}")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationClassificationError(f"installed evidence is not strict JSON: {path}") from exc
    if not isinstance(value, dict):
        raise MigrationClassificationError(f"installed evidence must be an object: {path}")
    return value, raw


def _read_json(path: Path, *, maximum: int = MAX_JSON_BYTES) -> dict[str, object]:
    return _read_json_with_raw(path, maximum=maximum)[0]


def _fixture() -> dict[str, object]:
    value = _read_json(FIXTURE_PATH, maximum=64 * 1024)
    fields = {
        "schema",
        "plugin_id",
        "runtime_receipt_schema",
        "ownership_schema",
        "transaction_schema",
        "transaction_outcome",
        "transaction_step",
        "launcher_markers",
    }
    if set(value) != fields or value.get("schema") != "dev-flow-legacy-predecessor-fixture/1.0.0":
        raise MigrationClassificationError("legacy predecessor fixture is incompatible")
    return value


def _contained(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute():
        raise MigrationClassificationError(f"{label} is not absolute")
    path = Path(os.path.abspath(path))
    root = Path(os.path.abspath(root))
    try:
        if os.path.commonpath((str(root), str(path))) != str(root) or path == root:
            raise MigrationClassificationError(f"{label} is not contained")
    except ValueError as exc:
        raise MigrationClassificationError(f"{label} is on another volume") from exc
    cursor = root
    for component in path.relative_to(root).parts:
        cursor = cursor / component
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            raise MigrationClassificationError(f"{label} is unavailable") from exc
        reparse = bool(
            getattr(metadata, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
        if stat.S_ISLNK(metadata.st_mode) or reparse:
            raise MigrationClassificationError(f"{label} crosses a link or reparse point")
    return path


def _marketplace_plugin_root(path: Path) -> Path:
    marketplace = _read_json(path)
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise MigrationClassificationError("personal marketplace plugins are invalid")
    matches = [
        item
        for item in plugins
        if isinstance(item, dict) and item.get("name") == "dev-flow-orchestrator"
    ]
    if len(matches) != 1:
        raise MigrationClassificationError("personal marketplace does not prove one Dev Flow member")
    entry = matches[0]
    if set(entry) != {"name", "source", "policy", "category"}:
        raise MigrationClassificationError("Dev Flow marketplace member has an unsupported shape")
    source = entry.get("source")
    if not isinstance(source, dict) or set(source) != {"source", "path"} or source.get("source") != "local":
        raise MigrationClassificationError("Dev Flow marketplace source is unsupported")
    relative = source.get("path")
    if not isinstance(relative, str) or not relative.startswith("./"):
        raise MigrationClassificationError("Dev Flow marketplace path is not the predecessor form")
    return Path(os.path.abspath(path.parent.parent.parent / relative[2:]))


def _launcher(path: Path, marker: str, release_path: Path) -> str:
    try:
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise MigrationClassificationError(f"predecessor launcher is unavailable: {path}") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_size > MAX_LAUNCHER_BYTES
    ):
        raise MigrationClassificationError(f"predecessor launcher is linked, special, or oversized: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise MigrationClassificationError(f"predecessor launcher is not UTF-8: {path}") from exc
    if marker not in text or str(release_path) not in text:
        raise MigrationClassificationError(f"predecessor launcher identity is ambiguous: {path}")
    return hashlib.sha256(raw).hexdigest()


def classify_predecessor(
    *,
    runtime_root: Path,
    bin_dir: Path,
    marketplace_file: Path,
    plugin_observation: Mapping[str, object],
    windows: bool,
) -> dict[str, object]:
    """Return one proven predecessor authority without consulting its checkout."""

    fixture = _fixture()
    plugin_fields = {"plugin_id", "installed", "enabled", "version"}
    if set(plugin_observation) != plugin_fields:
        raise MigrationClassificationError("Codex plugin observation is not closed")
    if (
        plugin_observation.get("plugin_id") != fixture["plugin_id"]
        or plugin_observation.get("installed") is not True
        or plugin_observation.get("enabled") is not True
        or not isinstance(plugin_observation.get("version"), str)
    ):
        raise MigrationClassificationError("Codex plugin observation is not the active predecessor")
    runtime_root = Path(os.path.abspath(runtime_root))
    releases_root = _contained(runtime_root / "releases", runtime_root, "predecessor releases root")
    plugin_root = _contained(
        _marketplace_plugin_root(marketplace_file), releases_root, "predecessor plugin root"
    )
    if plugin_root.name != "plugin" or plugin_root.parent.parent != releases_root:
        raise MigrationClassificationError("marketplace path is not a managed predecessor release")
    release_path = plugin_root.parent
    receipt_path = release_path / "runtime-receipt.json"
    receipt, receipt_raw = _read_json_with_raw(receipt_path)
    if receipt.get("schema") != fixture["runtime_receipt_schema"]:
        raise MigrationClassificationError("runtime receipt is not the frozen predecessor schema")
    try:
        receipt = runtime_integrity.validate_runtime_receipt(receipt)
    except runtime_integrity.IntegrityError as exc:
        raise MigrationClassificationError(
            "runtime receipt does not match the closed frozen predecessor schema"
        ) from exc
    if receipt.get("runtime_path") != str(release_path) or receipt.get("plugin_path") != str(plugin_root):
        raise MigrationClassificationError("runtime receipt paths disagree with installed observations")
    project = receipt.get("dev_flow")
    if not isinstance(project, dict) or project.get("version") != plugin_observation["version"]:
        raise MigrationClassificationError("plugin and runtime versions disagree")
    release_id = receipt.get("release_id")
    if not isinstance(release_id, str) or release_id != release_path.name:
        raise MigrationClassificationError("runtime release identity is ambiguous")
    ownership_path = release_path / "ownership-manifest.json"
    ownership, ownership_raw = _read_json_with_raw(ownership_path)
    if hashlib.sha256(ownership_raw).hexdigest() != receipt.get("ownership_manifest_sha256"):
        raise MigrationClassificationError("predecessor ownership digest differs from its receipt")
    if ownership.get("schema") != fixture["ownership_schema"] or ownership.get("release_id") != release_id:
        raise MigrationClassificationError("predecessor ownership schema or identity is invalid")
    try:
        runtime_integrity.validate_ownership_manifest(ownership, release_id)
    except runtime_integrity.IntegrityError as exc:
        raise MigrationClassificationError(
            "predecessor ownership manifest is not closed"
        ) from exc
    markers = fixture["launcher_markers"]
    assert isinstance(markers, dict)
    suffix = ".cmd" if windows else ""
    cli_digest = _launcher(
        bin_dir / ("dev-flow" + suffix),
        str(markers["windows_cli" if windows else "posix_cli"]),
        release_path,
    )
    mcp_digest = _launcher(
        bin_dir / ("dev-flow-mcp" + suffix),
        str(markers["windows_mcp" if windows else "posix_mcp"]),
        release_path,
    )
    transactions_root = _contained(
        runtime_root / "transactions", runtime_root, "predecessor transactions root"
    )
    transactions = sorted(transactions_root.glob("*.json"))
    matches: list[tuple[Path, dict[str, object]]] = []
    for path in transactions:
        value = _read_json(path)
        if (
            set(value)
            == {
                "schema",
                "transaction_id",
                "operation",
                "previous_release",
                "candidate_release",
                "current_step",
                "components",
                "outcome",
                "blind_retry_safe",
                "retained_paths",
            }
            and
            value.get("schema") == fixture["transaction_schema"]
            and value.get("candidate_release") == release_id
            and value.get("current_step") == fixture["transaction_step"]
            and value.get("outcome") == fixture["transaction_outcome"]
            and value.get("blind_retry_safe") is True
        ):
            matches.append((path, value))
    if len(matches) != 1:
        raise MigrationClassificationError("predecessor transaction evidence is absent or ambiguous")
    transaction_path, transaction = matches[0]
    components = transaction.get("components")
    expected_components = {
            "plugin": "candidate",
            "marketplace": "candidate",
            "mcp_launcher": "candidate",
            "cli_launcher": "candidate",
            "runtime": "candidate-active",
    }
    if not isinstance(components, dict) or components != expected_components:
        raise MigrationClassificationError("predecessor transaction component evidence is incomplete")
    return {
        "schema": "dev-flow-proven-predecessor/1.0.0",
        "release_id": release_id,
        "release_path": str(release_path),
        "plugin_root": str(plugin_root),
        "version": plugin_observation["version"],
        "receipt_path": str(receipt_path),
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "ownership_path": str(ownership_path),
        "marketplace_file": str(marketplace_file),
        "transaction_path": str(transaction_path),
        "cli_launcher_sha256": cli_digest,
        "mcp_launcher_sha256": mcp_digest,
        "legacy_checkout_owned": False,
    }


__all__ = ["MigrationClassificationError", "classify_predecessor"]
