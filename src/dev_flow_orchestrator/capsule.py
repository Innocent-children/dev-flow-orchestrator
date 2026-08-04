"""Pure 0.3 task-change capsule, ownership, and ambient-drift authority."""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from .model import DevFlowError, canonical_json_bytes, json_value
from .product import (
    MAX_OWNERSHIP_CLAIMS,
    MAX_TASK_CHANGE_MANIFEST_ENTRIES,
    PREFLIGHT_BASELINE_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
    TASK_CHANGE_MANIFEST_SCHEMA,
    product_domain,
)
from .snapshot import validate_task_snapshot, valid_relative_path


OWNERSHIP_CLASSIFICATIONS = (
    "configuration",
    "documentation",
    "generated",
    "implementation",
    "investigation",
    "test",
)

_BASELINE_DOMAIN = product_domain("preflight-baseline")
_MANIFEST_DOMAIN = product_domain("task-change-manifest")


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def _seal(domain: bytes, value: Mapping[str, object]) -> str:
    return hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def _member_map(snapshot: Mapping[str, object]) -> dict:
    return {
        item["repository_id"]: item["snapshot"]
        for item in snapshot["repositories"]
    }


def _entry_map(member_snapshot: Mapping[str, object]) -> dict:
    return {item["path"]: item for item in member_snapshot["entries"]}


def path_identity(entry: object) -> dict:
    """Return the two-plane identity used by manifests and drift reports."""
    if entry is None:
        return {
            "worktree": {
                "kind": "missing",
                "mode": None,
                "size": 0,
                "content_sha256": None,
                "submodule_head": None,
            },
            "index_entries": [],
        }
    if not isinstance(entry, Mapping):
        raise _error("CAPSULE_INVALID", "snapshot path entry is invalid")
    return {
        "worktree": {
            "kind": entry.get("kind"),
            "mode": entry.get("mode"),
            "size": entry.get("size"),
            "content_sha256": entry.get("content_sha256"),
            "submodule_head": entry.get("submodule_head"),
        },
        "index_entries": json_value(entry.get("index_entries", [])),
    }


def derive_path_changes(
    before_snapshot: object,
    after_snapshot: object,
    repositories: object,
) -> tuple:
    """Derive the exact canonical per-path delta between two complete captures."""
    before = validate_task_snapshot(before_snapshot, repositories)
    after = validate_task_snapshot(after_snapshot, repositories)
    if before["repository_set_id"] != after["repository_set_id"]:
        raise _error("CAPSULE_INVALID", "snapshot repository sets differ")
    before_members = _member_map(before)
    after_members = _member_map(after)
    changes = []
    for member in before["repositories"]:
        repository_id = member["repository_id"]
        before_entries = _entry_map(before_members[repository_id])
        after_entries = _entry_map(after_members[repository_id])
        for path in sorted(
            set(before_entries) | set(after_entries), key=lambda item: item.encode("utf-8")
        ):
            old = path_identity(before_entries.get(path))
            new = path_identity(after_entries.get(path))
            if old == new:
                continue
            old_missing = old["worktree"]["kind"] == "missing" and not old["index_entries"]
            new_missing = new["worktree"]["kind"] == "missing" and not new["index_entries"]
            change_kind = "added" if old_missing else "deleted" if new_missing else "modified"
            changes.append(
                {
                    "repository_id": repository_id,
                    "path": path,
                    "change_kind": change_kind,
                    "before": old,
                    "after": new,
                }
            )
    return tuple(changes)


def make_preflight_baseline(
    *,
    task_id: str,
    contract_digest: str,
    snapshot: object,
    repositories: object,
) -> dict:
    validated = validate_task_snapshot(snapshot, repositories)
    base = {
        "schema": PREFLIGHT_BASELINE_SCHEMA,
        "task_id": task_id,
        "contract_digest": contract_digest,
        "repository_set_id": validated["repository_set_id"],
        "snapshot": validated,
    }
    return {**base, "digest": _seal(_BASELINE_DOMAIN, base)}


def validate_preflight_baseline(
    value: object,
    *,
    task_id: str,
    contract_digest: str,
    repositories: object,
) -> dict:
    expected = {
        "schema", "task_id", "contract_digest", "repository_set_id", "snapshot", "digest"
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise _error("CAPSULE_INVALID", "preflight baseline fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    snapshot = validate_task_snapshot(plain.get("snapshot"), repositories)
    if (
        plain.get("schema") != PREFLIGHT_BASELINE_SCHEMA
        or plain.get("task_id") != task_id
        or plain.get("contract_digest") != contract_digest
        or plain.get("repository_set_id") != snapshot["repository_set_id"]
        or digest != _seal(_BASELINE_DOMAIN, plain)
    ):
        raise _error("CAPSULE_INVALID", "preflight baseline identity is invalid")
    return {**plain, "digest": digest}


def _criteria(contract: Mapping[str, object]) -> set:
    values = contract.get("acceptance_criteria")
    if not isinstance(values, (list, tuple)):
        raise _error("CAPSULE_INVALID", "delivery contract criteria are invalid")
    return {
        item.get("id")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    }


def validate_ownership_claims(
    value: object,
    *,
    changes: Sequence[Mapping[str, object]],
    contract: Mapping[str, object],
) -> tuple:
    """Require one bounded claim for every and only controller-derived path."""
    if not isinstance(value, Mapping) or set(value) != {"schema", "claims"}:
        raise _error("OWNERSHIP_CLAIMS_INVALID", "ownership claim envelope is invalid")
    if value.get("schema") != TASK_CHANGE_CLAIMS_SCHEMA:
        raise _error("OWNERSHIP_CLAIMS_INVALID", "ownership claim schema is unsupported")
    claims = value.get("claims")
    if not isinstance(claims, (list, tuple)) or len(claims) > MAX_OWNERSHIP_CLAIMS:
        raise _error(
            "OWNERSHIP_CLAIMS_INVALID",
            "ownership claim count exceeds its product bound",
            claim_limit=MAX_OWNERSHIP_CLAIMS,
        )
    expected_keys = {
        (str(change["repository_id"]), str(change["path"])) for change in changes
    }
    criterion_ids = _criteria(contract)
    normalized = []
    seen = set()
    for claim in claims:
        fields = {"repository_id", "path", "classification", "criterion_ids", "purpose"}
        if not isinstance(claim, Mapping) or set(claim) != fields:
            raise _error("OWNERSHIP_CLAIMS_INVALID", "ownership claim fields are invalid")
        repository_id = claim.get("repository_id")
        path = claim.get("path")
        classification = claim.get("classification")
        purpose = claim.get("purpose")
        claimed_criteria = claim.get("criterion_ids")
        key = (repository_id, path)
        if (
            not isinstance(repository_id, str)
            or not valid_relative_path(path)
            or key in seen
            or classification not in OWNERSHIP_CLASSIFICATIONS
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose.encode("utf-8")) > 8192
            or not isinstance(claimed_criteria, (list, tuple))
            or not claimed_criteria
            or any(not isinstance(item, str) for item in claimed_criteria)
            or len(set(claimed_criteria)) != len(claimed_criteria)
            or tuple(claimed_criteria) != tuple(sorted(claimed_criteria))
            or not set(claimed_criteria).issubset(criterion_ids)
        ):
            raise _error("OWNERSHIP_CLAIMS_INVALID", "ownership claim is invalid")
        seen.add(key)
        normalized.append(
            {
                "repository_id": repository_id,
                "path": path,
                "classification": classification,
                "criterion_ids": list(claimed_criteria),
                "purpose": purpose.strip(),
            }
        )
    if seen != expected_keys:
        raise _error(
            "OWNERSHIP_CLAIMS_INVALID",
            "ownership claims do not exactly cover the observed source interval",
            missing=[list(item) for item in sorted(expected_keys - seen)],
            unexpected=[list(item) for item in sorted(seen - expected_keys)],
        )
    return tuple(sorted(normalized, key=lambda item: (
        item["repository_id"].encode("utf-8"), item["path"].encode("utf-8")
    )))


def derive_manifest(
    *,
    task_id: str,
    contract: Mapping[str, object],
    contract_digest: str,
    repositories: object,
    preflight: Mapping[str, object],
    predecessor: object,
    before_snapshot: object,
    after_snapshot: object,
    claims: object,
    producer: Mapping[str, object],
) -> dict:
    """Roll one claimed source interval into the current net task-owned manifest."""
    baseline = validate_preflight_baseline(
        preflight,
        task_id=task_id,
        contract_digest=str(preflight.get("contract_digest")),
        repositories=repositories,
    )
    before = validate_task_snapshot(before_snapshot, repositories)
    after = validate_task_snapshot(after_snapshot, repositories)
    changes = derive_path_changes(before, after, repositories)
    normalized_claims = validate_ownership_claims(
        claims, changes=changes, contract=contract
    )
    claim_map = {
        (item["repository_id"], item["path"]): item for item in normalized_claims
    }
    existing = {}
    predecessor_digest = None
    if predecessor is not None:
        prior = validate_manifest(
            predecessor,
            task_id=task_id,
            repository_set_id=after["repository_set_id"],
        )
        predecessor_digest = prior["digest"]
        existing = {
            (item["repository_id"], item["path"]): item for item in prior["entries"]
        }
    baseline_members = _member_map(baseline["snapshot"])
    baseline_entries = {
        (repository_id, path): path_identity(entry)
        for repository_id, member in baseline_members.items()
        for path, entry in _entry_map(member).items()
    }
    producer_value = json_value(producer)
    required_producer = {"action_id", "task_revision", "contract_revision", "binding_digest"}
    if not isinstance(producer_value, dict) or set(producer_value) != required_producer:
        raise _error("CAPSULE_INVALID", "manifest producer is invalid")
    for change in changes:
        key = (change["repository_id"], change["path"])
        claim = claim_map[key]
        prior = existing.get(key)
        origin = baseline_entries.get(key, path_identity(None))
        if change["after"] == origin:
            existing.pop(key, None)
            continue
        lineage = [] if prior is None else list(prior["producer_lineage"])
        lineage.append(producer_value)
        existing[key] = {
            "repository_id": key[0],
            "path": key[1],
            "change_kind": (
                "added"
                if origin["worktree"]["kind"] == "missing" and not origin["index_entries"]
                else "deleted"
                if change["after"]["worktree"]["kind"] == "missing"
                and not change["after"]["index_entries"]
                else "modified"
            ),
            "original_before": origin,
            "current_after": change["after"],
            "original_producer": producer_value if prior is None else prior["original_producer"],
            "producer_lineage": lineage,
            "classification": claim["classification"],
            "criterion_ids": claim["criterion_ids"],
            "purpose": claim["purpose"],
        }
    entries = sorted(
        existing.values(),
        key=lambda item: (
            item["repository_id"].encode("utf-8"), item["path"].encode("utf-8")
        ),
    )
    if len(entries) > MAX_TASK_CHANGE_MANIFEST_ENTRIES:
        raise _error(
            "CAPSULE_BUDGET_EXCEEDED",
            "task change manifest exceeds its product bound",
            entry_limit=MAX_TASK_CHANGE_MANIFEST_ENTRIES,
        )
    base = {
        "schema": TASK_CHANGE_MANIFEST_SCHEMA,
        "task_id": task_id,
        "repository_set_id": after["repository_set_id"],
        "contract_digest": contract_digest,
        "preflight_digest": baseline["digest"],
        "predecessor_digest": predecessor_digest,
        "source_interval": {
            "before_snapshot_digest": before["digest"],
            "after_snapshot_digest": after["digest"],
        },
        "entries": entries,
    }
    return {**base, "digest": _seal(_MANIFEST_DOMAIN, base)}


def validate_manifest(
    value: object,
    *,
    task_id: str,
    repository_set_id: str,
) -> dict:
    fields = {
        "schema", "task_id", "repository_set_id", "contract_digest",
        "preflight_digest", "predecessor_digest", "source_interval", "entries", "digest"
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("CAPSULE_INVALID", "task change manifest fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    entries = plain.get("entries")
    if (
        plain.get("schema") != TASK_CHANGE_MANIFEST_SCHEMA
        or plain.get("task_id") != task_id
        or plain.get("repository_set_id") != repository_set_id
        or not isinstance(entries, list)
        or len(entries) > MAX_TASK_CHANGE_MANIFEST_ENTRIES
        or digest != _seal(_MANIFEST_DOMAIN, plain)
    ):
        raise _error("CAPSULE_INVALID", "task change manifest identity is invalid")
    keys = []
    for entry in entries:
        expected = {
            "repository_id", "path", "change_kind", "original_before", "current_after",
            "original_producer", "producer_lineage", "classification", "criterion_ids", "purpose"
        }
        if not isinstance(entry, dict) or set(entry) != expected:
            raise _error("CAPSULE_INVALID", "task change manifest entry is invalid")
        if not valid_relative_path(entry.get("path")):
            raise _error("CAPSULE_INVALID", "task change manifest path is invalid")
        keys.append((entry.get("repository_id"), entry.get("path")))
    if len(keys) != len(set(keys)) or keys != sorted(
        keys, key=lambda item: (str(item[0]).encode("utf-8"), str(item[1]).encode("utf-8"))
    ):
        raise _error("CAPSULE_INVALID", "task change manifest entries are not canonical")
    return {**plain, "digest": digest}


def ambient_drift(
    accepted_snapshot: object,
    current_snapshot: object,
    repositories: object,
) -> dict:
    accepted = validate_task_snapshot(accepted_snapshot, repositories)
    current = validate_task_snapshot(current_snapshot, repositories)
    paths = list(derive_path_changes(accepted, current, repositories))
    accepted_members = _member_map(accepted)
    current_members = _member_map(current)
    member_planes = []
    for repository_id in accepted_members:
        old = accepted_members[repository_id]
        new = current_members[repository_id]
        changed = [
            field
            for field in (
                "head", "branch", "status_sha256", "git_worktree_dir", "git_common_dir",
                "object_format"
            )
            if old.get(field) != new.get(field)
        ]
        if changed:
            member_planes.append({"repository_id": repository_id, "planes": changed})
    return {
        "present": bool(paths or member_planes),
        "paths": paths,
        "member_planes": member_planes,
        "accepted_snapshot_digest": accepted["digest"],
        "current_snapshot_digest": current["digest"],
    }


def snapshot_has_unmerged_entries(snapshot: object, repositories: object) -> bool:
    value = validate_task_snapshot(snapshot, repositories)
    return any(item["snapshot"]["has_unmerged_entries"] for item in value["repositories"])
