"""Pure workspace-snapshot schema, canonicalization, and validation."""

from __future__ import annotations

import hashlib
import os
import re
from typing import Mapping, Tuple

from .model import (
    DevFlowError,
    RepositoryRecord,
    canonical_json_bytes,
    json_value,
    repository_by_id,
    repository_set_id,
    validate_repositories,
)
from .product import (
    MAX_INDEX_COMMAND_OUTPUT_BYTES,
    MAX_INDEX_STAGE_ENTRIES,
    MAX_SNAPSHOT_PATHS,
    OPENSPEC_TASKS_NORMALIZER,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    WORKSPACE_SNAPSHOT_SCHEMA,
    product_domain,
)


MAX_GIT_OUTPUT_BYTES = 1024 * 1024
MAX_SNAPSHOT_PATH_BYTES = 64 * 1024
MAX_SNAPSHOT_RESOURCES = 64
MAX_SNAPSHOT_FILE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_CONTENT_BYTES = 32 * 1024 * 1024

_SNAPSHOT_DOMAIN = product_domain("workspace-snapshot")
_REPOSITORY_SET_SNAPSHOT_DOMAIN = product_domain("repository-set-snapshot")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_MODE = re.compile(r"^[0-7]{6}$")
_INDEX_ENTRY_FIELDS = {"mode", "oid", "stage"}
_ENTRY_FIELDS = {
    "path", "kind", "mode", "size", "content_sha256", "index_entries", "submodule_head",
}
_RESOURCE_FIELDS = {
    "path", "role", "normalizer", "kind", "raw_sha256", "semantic_sha256",
}
_SNAPSHOT_FIELDS = {
    "schema", "repository_root", "git_worktree_dir", "git_common_dir",
    "object_format", "head", "branch", "clean", "status_sha256", "status_bytes",
    "index_entry_count", "index_output_bytes", "has_unmerged_entries",
    "entries", "resources", "digest",
}
_REPOSITORY_SET_SNAPSHOT_FIELDS = {
    "schema", "repository_set_id", "repositories", "digest",
}
_REPOSITORY_SET_MEMBER_FIELDS = {"repository_id", "snapshot"}


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


def repository_set_snapshot_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        _REPOSITORY_SET_SNAPSHOT_DOMAIN + canonical_json_bytes(value)
    ).hexdigest()


def validate_snapshot(value: object) -> dict:
    """Validate one persisted workspace snapshot and its canonical seal."""
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    if plain.get("schema") != WORKSPACE_SNAPSHOT_SCHEMA:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot schema is invalid")
    for field in ("repository_root", "git_worktree_dir", "git_common_dir"):
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
    object_format = plain.get("object_format")
    if object_format not in ("sha1", "sha256"):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot object format is invalid")
    oid_length = 40 if object_format == "sha1" else 64
    head = plain.get("head")
    branch = plain.get("branch")
    status_sha256 = plain.get("status_sha256")
    status_bytes = plain.get("status_bytes")
    if (
        not isinstance(head, str)
        or len(head) != oid_length
        or not _OBJECT_ID.fullmatch(head)
    ):
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

    index_entry_count = plain.get("index_entry_count")
    index_output_bytes = plain.get("index_output_bytes")
    has_unmerged_entries = plain.get("has_unmerged_entries")
    if (
        isinstance(index_entry_count, bool)
        or not isinstance(index_entry_count, int)
        or index_entry_count < 0
        or index_entry_count > MAX_INDEX_STAGE_ENTRIES
        or isinstance(index_output_bytes, bool)
        or not isinstance(index_output_bytes, int)
        or index_output_bytes < 0
        or index_output_bytes > MAX_INDEX_COMMAND_OUTPUT_BYTES
        or not isinstance(has_unmerged_entries, bool)
    ):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot index metadata is invalid")

    entries = plain.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_SNAPSHOT_PATHS:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot entries are invalid")
    seen_paths = set()
    path_bytes = 0
    content_bytes = 0
    observed_index_count = 0
    observed_unmerged = False
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot entry fields are invalid")
        path = entry.get("path")
        kind = entry.get("kind")
        mode = entry.get("mode")
        size = entry.get("size")
        content = entry.get("content_sha256")
        index_entries = entry.get("index_entries")
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
        if not isinstance(index_entries, list):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot index entries are invalid")
        canonical_index_entries = []
        seen_stages = set()
        for index_entry in index_entries:
            if not isinstance(index_entry, dict) or set(index_entry) != _INDEX_ENTRY_FIELDS:
                raise _error("SNAPSHOT_INVALID", "workspace snapshot index entry fields are invalid")
            index_mode = index_entry.get("mode")
            index_oid = index_entry.get("oid")
            index_stage = index_entry.get("stage")
            if (
                not isinstance(index_mode, str)
                or not _MODE.fullmatch(index_mode)
                or not isinstance(index_oid, str)
                or len(index_oid) != oid_length
                or not _OBJECT_ID.fullmatch(index_oid)
                or isinstance(index_stage, bool)
                or not isinstance(index_stage, int)
                or index_stage not in (0, 1, 2, 3)
                or index_stage in seen_stages
            ):
                raise _error("SNAPSHOT_INVALID", "workspace snapshot index entry is invalid")
            seen_stages.add(index_stage)
            observed_unmerged = observed_unmerged or index_stage != 0
            canonical_index_entries.append(index_entry)
        if index_entries != sorted(
            canonical_index_entries,
            key=lambda item: (item["stage"], item["mode"], item["oid"]),
        ):
            raise _error("SNAPSHOT_INVALID", "workspace snapshot index entries are not canonical")
        observed_index_count += len(index_entries)
        if kind in ("regular", "symlink"):
            if (
                not isinstance(mode, str)
                or not _MODE.fullmatch(mode)
                or not isinstance(content, str)
                or not _SHA256.fullmatch(content)
                or submodule_head is not None
            ):
                raise _error("SNAPSHOT_INVALID", "workspace snapshot file entry is invalid")
            content_bytes += size
        elif kind == "gitlink":
            if (
                mode != "160000"
                or size != 0
                or content is not None
                or not any(item["mode"] == "160000" for item in index_entries)
                or not isinstance(submodule_head, str)
                or len(submodule_head) != oid_length
                or not _OBJECT_ID.fullmatch(submodule_head)
            ):
                raise _error("SNAPSHOT_INVALID", "workspace snapshot gitlink entry is invalid")
            content_bytes += len(b"gitlink\x00") + sum(
                len(item["mode"]) + len(item["oid"]) + 2 for item in index_entries
            ) + len(submodule_head)
        elif any(item is not None for item in (mode, content, submodule_head)) or size != 0:
            raise _error("SNAPSHOT_INVALID", "workspace snapshot missing entry is invalid")
    if path_bytes > MAX_SNAPSHOT_PATH_BYTES or content_bytes > MAX_SNAPSHOT_CONTENT_BYTES:
        raise _error("SNAPSHOT_INVALID", "workspace snapshot exceeds canonical budgets")
    if entries != sorted(entries, key=lambda item: path_key(item["path"])):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot entries are not canonical")
    if (
        observed_index_count != index_entry_count
        or observed_unmerged != has_unmerged_entries
    ):
        raise _error("SNAPSHOT_INVALID", "workspace snapshot index summary is inconsistent")

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
            or normalizer not in ("none", OPENSPEC_TASKS_NORMALIZER)
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


def validate_repository_set_snapshot(
    value: object,
    repositories: object,
) -> dict:
    """Validate one repository-set wrapper against immutable task membership."""
    members = validate_repositories(repositories)
    if (
        not isinstance(value, Mapping)
        or set(value) != _REPOSITORY_SET_SNAPSHOT_FIELDS
    ):
        raise _error("SNAPSHOT_INVALID", "repository-set snapshot fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    if plain.get("schema") != REPOSITORY_SET_SNAPSHOT_SCHEMA:
        raise _error("SNAPSHOT_INVALID", "repository-set snapshot schema is invalid")
    expected_set_id = repository_set_id(members)
    if plain.get("repository_set_id") != expected_set_id:
        raise _error(
            "SNAPSHOT_INVALID",
            "repository-set snapshot identity is invalid",
        )
    snapshots = plain.get("repositories")
    if not isinstance(snapshots, list) or len(snapshots) != len(members):
        raise _error(
            "SNAPSHOT_INVALID",
            "repository-set snapshot membership is invalid",
        )
    validated_members = []
    git_common_dirs = set()
    for repository, item in zip(members, snapshots):
        if not isinstance(item, dict) or set(item) != _REPOSITORY_SET_MEMBER_FIELDS:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set snapshot member fields are invalid",
            )
        if item.get("repository_id") != repository.repository_id:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set snapshot membership is not canonical",
                repository_id=repository.repository_id,
            )
        member_snapshot = validate_snapshot(item.get("snapshot"))
        if member_snapshot["repository_root"] != repository.path:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set member root does not match task membership",
                repository_id=repository.repository_id,
                repository_root=member_snapshot["repository_root"],
                expected_repository_root=repository.path,
            )
        if member_snapshot["git_worktree_dir"] != repository.git_worktree_dir:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set member worktree Git directory does not match task membership",
                repository_id=repository.repository_id,
            )
        if member_snapshot["git_common_dir"] != repository.git_common_dir:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set member Git common directory does not match task membership",
                repository_id=repository.repository_id,
            )
        git_common_dir = member_snapshot["git_common_dir"]
        if git_common_dir in git_common_dirs:
            raise _error(
                "SNAPSHOT_INVALID",
                "repository-set members share a Git common directory",
                repository_id=repository.repository_id,
                git_common_dir=git_common_dir,
            )
        git_common_dirs.add(git_common_dir)
        validated_members.append(
            {
                "repository_id": repository.repository_id,
                "snapshot": member_snapshot,
            }
        )
    plain["repositories"] = validated_members
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise _error("SNAPSHOT_INVALID", "repository-set snapshot seal is invalid")
    if repository_set_snapshot_digest(plain) != digest:
        raise _error(
            "SNAPSHOT_INVALID",
            "repository-set snapshot seal does not match its content",
        )
    return {**plain, "digest": digest}


def make_repository_set_snapshot(
    repositories: object,
    member_snapshots_by_id: object,
) -> dict:
    """Seal complete member snapshots in canonical task membership order."""
    members = validate_repositories(repositories)
    if not isinstance(member_snapshots_by_id, Mapping):
        raise _error(
            "SNAPSHOT_INVALID",
            "repository-set member snapshots must be an identity map",
        )
    expected_ids = {member.repository_id for member in members}
    if set(member_snapshots_by_id) != expected_ids:
        raise _error(
            "SNAPSHOT_INVALID",
            "repository-set member snapshots do not match task membership",
        )
    base = {
        "schema": REPOSITORY_SET_SNAPSHOT_SCHEMA,
        "repository_set_id": repository_set_id(members),
        "repositories": [
            {
                "repository_id": member.repository_id,
                "snapshot": validate_snapshot(
                    member_snapshots_by_id[member.repository_id]
                ),
            }
            for member in members
        ],
    }
    return validate_repository_set_snapshot(
        {**base, "digest": repository_set_snapshot_digest(base)},
        members,
    )


def validate_task_snapshot(value: object, repositories: object) -> dict:
    """Validate the current task snapshot against immutable membership."""
    return validate_repository_set_snapshot(value, repositories)


def iter_repository_snapshots(
    value: object,
    repositories: object,
) -> Tuple[Tuple[RepositoryRecord, dict], ...]:
    """Return canonical `(RepositoryRecord, workspace snapshot)` members."""
    members = validate_repositories(repositories)
    snapshot = validate_task_snapshot(value, members)
    return tuple(
        (repository, item["snapshot"])
        for repository, item in zip(members, snapshot["repositories"])
    )


def repository_snapshot(
    value: object,
    repositories: object,
    repository_id: object,
) -> dict:
    """Return one member workspace snapshot by explicit repository identity."""
    members = validate_repositories(repositories)
    member = repository_by_id(members, repository_id)
    for repository, snapshot in iter_repository_snapshots(value, members):
        if repository == member:
            return snapshot
    raise _error(
        "SNAPSHOT_INVALID",
        "repository-set snapshot member is unavailable",
        repository_id=member.repository_id,
    )
