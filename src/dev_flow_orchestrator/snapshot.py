"""Pure workspace-snapshot schema, canonicalization, and validation."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Mapping

from .model import DevFlowError, canonical_json_bytes, json_value
from .product import WORKSPACE_SNAPSHOT_SCHEMA


MAX_GIT_OUTPUT_BYTES = 1024 * 1024
MAX_SNAPSHOT_PATHS = 4096
MAX_SNAPSHOT_PATH_BYTES = 64 * 1024
MAX_SNAPSHOT_RESOURCES = 64
MAX_SNAPSHOT_FILE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_CONTENT_BYTES = 32 * 1024 * 1024

_SNAPSHOT_DOMAIN = b"dev-flow-workspace-snapshot/v1\x00"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MODE = re.compile(r"^[0-7]{6}$")
_ENTRY_FIELDS = {
    "path", "kind", "mode", "size", "content_sha256", "index_oid", "submodule_head",
}
_RESOURCE_FIELDS = {
    "path", "role", "normalizer", "kind", "raw_sha256", "semantic_sha256",
}
_SNAPSHOT_FIELDS = {
    "schema", "repository_root", "git_common_dir", "head", "branch", "clean",
    "status_sha256", "status_bytes", "entries", "resources", "digest",
}


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def valid_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    if not encoded or value.startswith("/") or "\x00" in value:
        return False
    return all(component not in ("", ".", "..") for component in value.split("/"))


def path_key(path: str) -> bytes:
    return path.encode("utf-8")


def resource_key(resource: Mapping[str, object]) -> tuple:
    return (
        path_key(str(resource["path"])),
        str(resource["role"]),
        str(resource["normalizer"]),
    )


def snapshot_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_SNAPSHOT_DOMAIN + canonical_json_bytes(value)).hexdigest()


def validate_snapshot(value: object) -> dict:
    """Validate one persisted workspace snapshot and its canonical seal."""
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    if plain.get("schema") != WORKSPACE_SNAPSHOT_SCHEMA:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot schema is invalid")
    for field in ("repository_root", "git_common_dir"):
        item = plain.get(field)
        if (
            not isinstance(item, str)
            or not os.path.isabs(item)
            or "\x00" in item
            or os.path.normpath(item) != item
        ):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot path is invalid", field=field)
        try:
            item.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _error(
                "SNAPSHOT_INVALID", "workspace snapshot path is not UTF-8", field=field,
            ) from exc
    head = plain.get("head")
    branch = plain.get("branch")
    status_sha256 = plain.get("status_sha256")
    status_bytes = plain.get("status_bytes")
    if not isinstance(head, str) or not _OBJECT_ID.fullmatch(head):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot HEAD is invalid")
    if branch is not None and (not isinstance(branch, str) or not branch):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot branch is invalid")
    if isinstance(branch, str):
        try:
            branch.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot branch is not UTF-8") from exc
    if not isinstance(plain.get("clean"), bool):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot clean flag is invalid")
    if not isinstance(status_sha256, str) or not _SHA256.fullmatch(status_sha256):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot status digest is invalid")
    if (
        isinstance(status_bytes, bool)
        or not isinstance(status_bytes, int)
        or status_bytes < 0
        or status_bytes > MAX_GIT_OUTPUT_BYTES
        or plain["clean"] != (status_bytes == 0)
        or (status_bytes == 0 and status_sha256 != hashlib.sha256(b"").hexdigest())
    ):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot status metadata is invalid")

    entries = plain.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_SNAPSHOT_PATHS:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot entries are invalid")
    seen_paths = set()
    path_bytes = 0
    content_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot entry fields are invalid")
        path = entry.get("path")
        kind = entry.get("kind")
        mode = entry.get("mode")
        size = entry.get("size")
        content = entry.get("content_sha256")
        index_oid = entry.get("index_oid")
        submodule_head = entry.get("submodule_head")
        if not valid_relative_path(path) or path in seen_paths:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot entry path is invalid")
        seen_paths.add(path)
        path_bytes += len(path.encode("utf-8"))
        if kind not in ("regular", "symlink", "gitlink", "missing"):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot entry kind is invalid")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or size > MAX_SNAPSHOT_FILE_BYTES
        ):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot entry size is invalid")
        if kind in ("regular", "symlink"):
            if (
                not isinstance(mode, str)
                or not _MODE.fullmatch(mode)
                or not isinstance(content, str)
                or not _SHA256.fullmatch(content)
                or index_oid is not None
                or submodule_head is not None
            ):
                raise _error("SNAPSHOT_INVALID", "workspace snapshot file entry is invalid")
            content_bytes += size
        elif kind == "gitlink":
            if (
                mode != "160000"
                or size != 0
                or content is not None
                or not isinstance(index_oid, str)
                or not _OBJECT_ID.fullmatch(index_oid)
                or not isinstance(submodule_head, str)
                or not _OBJECT_ID.fullmatch(submodule_head)
            ):
                raise _error("SNAPSHOT_INVALID", "workspace snapshot gitlink entry is invalid")
            content_bytes += len(b"gitlink\x00") + len(index_oid) + 1 + len(submodule_head)
        elif any(item is not None for item in (mode, content, index_oid, submodule_head)) or size != 0:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot missing entry is invalid")
    if path_bytes > MAX_SNAPSHOT_PATH_BYTES or content_bytes > MAX_SNAPSHOT_CONTENT_BYTES:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot exceeds canonical budgets")
    if entries != sorted(entries, key=lambda item: path_key(item["path"])):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot entries are not canonical")

    resources = plain.get("resources")
    if not isinstance(resources, list) or len(resources) > MAX_SNAPSHOT_RESOURCES:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot resources are invalid")
    entry_kinds = {entry["path"]: entry["kind"] for entry in entries}
    seen_resources = set()
    for resource in resources:
        if not isinstance(resource, dict) or set(resource) != _RESOURCE_FIELDS:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot resource fields are invalid")
        path = resource.get("path")
        role = resource.get("role")
        normalizer = resource.get("normalizer")
        kind = resource.get("kind")
        raw_digest = resource.get("raw_sha256")
        semantic_digest = resource.get("semantic_sha256")
        identity = (path, role, normalizer)
        if (
            not valid_relative_path(path)
            or path not in entry_kinds
            or kind != entry_kinds[path]
            or role not in ("governing", "reported")
            or normalizer not in ("none", "openspec-tasks-v1")
            or identity in seen_resources
        ):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot resource is invalid")
        seen_resources.add(identity)
        if kind == "missing":
            if raw_digest is not None or semantic_digest is not None:
                raise _error("SNAPSHOT_INVALID", "missing resource digests must be null")
        elif (
            not isinstance(raw_digest, str)
            or not _SHA256.fullmatch(raw_digest)
            or not isinstance(semantic_digest, str)
            or not _SHA256.fullmatch(semantic_digest)
            or (normalizer == "none" and raw_digest != semantic_digest)
        ):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot resource digest is invalid")
    if resources != sorted(resources, key=resource_key):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot resources are not canonical")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot seal is invalid")
    if snapshot_digest(plain) != digest:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot seal does not match its content")
    return {**plain, "digest": digest}
