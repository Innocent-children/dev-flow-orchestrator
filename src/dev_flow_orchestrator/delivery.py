"""Pure delivery contracts, ledger seals, lineage and dossier views."""

from __future__ import annotations

import hashlib
import re
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence

from .model import DevFlowError, canonical_json_bytes, freeze_json, json_value
from .product import (
    ACTION_BINDING_SCHEMA,
    ARTIFACT_SCHEMA,
    DELIVERY_CONTRACT_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    OPENSPEC_TASKS_NORMALIZER,
    RECORD_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    product_domain,
)


CONTRACT_SCHEMA = DELIVERY_CONTRACT_SCHEMA
CONTRACT_FIELDS = {
    "schema",
    "revision",
    "summary",
    "acceptance_criteria",
    "scope",
    "constraints",
    "risks",
    "non_goals",
    "open_questions",
}
MAX_CONTRACT_BYTES = 64 * 1024
MAX_LIST_ITEMS = 128
MAX_TEXT_BYTES = 8192
MAX_RESOURCE_ITEMS = 64
CRITERION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DECISION_ID = CRITERION_ID
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _error("CONTRACT_INVALID", "contract field must be a string", field=field)
    encoded = value.encode("utf-8")
    if (not allow_empty and not value.strip()) or len(encoded) > MAX_TEXT_BYTES:
        raise _error("CONTRACT_INVALID", "contract text is empty or too large", field=field)
    return value


def _text_list(value: object, field: str) -> list:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_LIST_ITEMS:
        raise _error("CONTRACT_INVALID", "contract list is invalid", field=field)
    return [_text(item, field) for item in value]


def validate_contract(
    value: object,
    *,
    expected_revision: Optional[int] = None,
    state_error: bool = False,
) -> Mapping[str, object]:
    """Validate and freeze one complete structured delivery contract."""
    try:
        if not isinstance(value, Mapping) or set(value) != CONTRACT_FIELDS:
            raise _error(
                "CONTRACT_INVALID",
                "delivery contract fields are invalid",
                fields=(sorted(str(field) for field in value) if isinstance(value, Mapping) else []),
            )
        if value.get("schema") != CONTRACT_SCHEMA:
            raise _error("CONTRACT_INVALID", "delivery contract schema is invalid")
        revision = value.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise _error("CONTRACT_INVALID", "contract revision must be positive")
        if expected_revision is not None and revision != expected_revision:
            raise _error(
                "CONTRACT_REVISION_INVALID",
                "contract revision is not the expected next revision",
                expected_revision=expected_revision,
                actual_revision=revision,
            )
        criteria_value = value.get("acceptance_criteria")
        if not isinstance(criteria_value, (list, tuple)) or not criteria_value:
            raise _error("CONTRACT_INVALID", "acceptance criteria must be a non-empty list")
        if len(criteria_value) > MAX_LIST_ITEMS:
            raise _error("CONTRACT_INVALID", "too many acceptance criteria")
        criteria = []
        seen = set()
        for item in criteria_value:
            if not isinstance(item, Mapping) or set(item) != {"id", "statement"}:
                raise _error("CONTRACT_INVALID", "acceptance criterion is invalid")
            criterion_id = item.get("id")
            if not isinstance(criterion_id, str) or not CRITERION_ID.fullmatch(criterion_id):
                raise _error("CONTRACT_INVALID", "acceptance criterion id is invalid")
            if criterion_id in seen:
                raise _error("CONTRACT_INVALID", "acceptance criterion ids must be unique")
            seen.add(criterion_id)
            criteria.append({"id": criterion_id, "statement": _text(item.get("statement"), "statement")})
        normalized = {
            "schema": CONTRACT_SCHEMA,
            "revision": revision,
            "summary": _text(value.get("summary"), "summary"),
            "acceptance_criteria": criteria,
            "scope": _text_list(value.get("scope"), "scope"),
            "constraints": _text_list(value.get("constraints"), "constraints"),
            "risks": _text_list(value.get("risks"), "risks"),
            "non_goals": _text_list(value.get("non_goals"), "non_goals"),
            "open_questions": _text_list(value.get("open_questions"), "open_questions"),
        }
        if len(canonical_json_bytes(normalized)) > MAX_CONTRACT_BYTES:
            raise _error("CONTRACT_INVALID", "delivery contract exceeds the size budget")
        return freeze_json(normalized)
    except DevFlowError as exc:
        if not state_error:
            raise
        raise DevFlowError(
            "STATE_INVALID",
            "stored delivery contract is invalid",
            details={"cause": exc.code, "cause_details": exc.details},
        ) from exc


def minimal_contract(requirement: str) -> Mapping[str, object]:
    clean = requirement.strip()
    if not clean:
        raise _error("REQUIREMENT_INVALID", "requirement must not be empty")
    return validate_contract(
        {
            "schema": CONTRACT_SCHEMA,
            "revision": 1,
            "summary": clean,
            "acceptance_criteria": [{"id": "requirement", "statement": clean}],
            "scope": [clean],
            "constraints": [],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        },
        expected_revision=1,
    )


def contract_digest(contract: Mapping[str, object]) -> str:
    return hashlib.sha256(
        product_domain("delivery-contract") + canonical_json_bytes(contract)
    ).hexdigest()


def contract_summary(contract: Mapping[str, object]) -> dict:
    return {
        "revision": contract["revision"],
        "digest": contract_digest(contract),
        "summary": contract["summary"],
        "criterion_ids": sorted(
            item["id"] for item in contract["acceptance_criteria"]
        ),
    }


def effective_contract(
    original: Mapping[str, object], records: Sequence[object]
) -> Mapping[str, object]:
    current = validate_contract(original, expected_revision=1)
    for record in records:
        if isinstance(record, Mapping) and record.get("kind") == "contract-revision":
            payload = record.get("payload")
            if isinstance(payload, Mapping) and isinstance(payload.get("new_contract"), Mapping):
                current = validate_contract(
                    payload["new_contract"],
                    expected_revision=int(current["revision"]) + 1,
                    state_error=True,
                )
    return current


def _seal(prefix: bytes, value: Mapping[str, object]) -> str:
    return hashlib.sha256(prefix + canonical_json_bytes(value)).hexdigest()


def seal_artifact(value: Mapping[str, object]) -> Mapping[str, object]:
    base = {str(key): json_value(item) for key, item in value.items() if key != "digest"}
    base["schema"] = ARTIFACT_SCHEMA
    digest = _seal(product_domain("artifact"), base)
    return freeze_json({**base, "digest": digest})


def validate_artifact(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error("STATE_INVALID", "artifact descriptor is invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    if plain.get("schema") != ARTIFACT_SCHEMA or not isinstance(digest, str):
        raise _error("STATE_INVALID", "artifact schema or digest is invalid")
    if _seal(product_domain("artifact"), plain) != digest:
        raise _error("STATE_INVALID", "artifact digest does not match its content")
    return freeze_json({**plain, "digest": digest})


def seal_record(value: Mapping[str, object]) -> Mapping[str, object]:
    base = {
        str(key): json_value(item)
        for key, item in value.items()
        if key not in ("record_id", "digest")
    }
    base["schema"] = RECORD_SCHEMA
    digest = _seal(product_domain("record"), base)
    return freeze_json({**base, "record_id": "rec-{}".format(digest[:24]), "digest": digest})


def validate_record_seal(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error("STATE_INVALID", "record must be an object")
    plain = json_value(value)
    record_id = plain.pop("record_id", None)
    digest = plain.pop("digest", None)
    if plain.get("schema") != RECORD_SCHEMA or not isinstance(digest, str):
        raise _error("STATE_INVALID", "record schema or digest is invalid")
    expected = _seal(product_domain("record"), plain)
    if digest != expected or record_id != "rec-{}".format(expected[:24]):
        raise _error("STATE_INVALID", "record seal does not match its content")
    if "artifact" in plain and plain["artifact"] is not None:
        validate_artifact(plain["artifact"])
    return freeze_json({**plain, "record_id": record_id, "digest": digest})


def artifact_records(records: Sequence[object]) -> list:
    result = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        artifact = record.get("artifact")
        if isinstance(artifact, Mapping):
            result.append((record, artifact))
    return result


def record_by_id(records: Sequence[object]) -> dict:
    return {
        record["record_id"]: record
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get("record_id"), str)
    }


def artifact_by_record_id(records: Sequence[object]) -> dict:
    return {
        record["record_id"]: artifact
        for record, artifact in artifact_records(records)
    }


def decisions_for_contract(
    records: Sequence[object], contract: Mapping[str, object]
) -> list:
    digest = contract_digest(contract)
    return [
        json_value(record["payload"])
        for record in records
        if isinstance(record, Mapping)
        and record.get("kind") == "decision"
        and isinstance(record.get("contract"), Mapping)
        and record["contract"].get("digest") == digest
        and isinstance(record.get("payload"), Mapping)
    ]


def validate_decision(
    value: object,
    *,
    contract: Mapping[str, object],
    records: Sequence[object],
) -> Mapping[str, object]:
    fields = {"id", "kind", "subject", "outcome", "rationale", "actor_label"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("DECISION_INVALID", "decision fields are invalid")
    result = {key: value.get(key) for key in fields}
    for field in fields:
        if not isinstance(result[field], str) or not result[field].strip():
            raise _error("DECISION_INVALID", "decision field is invalid", field=field)
        if len(result[field].encode("utf-8")) > MAX_TEXT_BYTES:
            raise _error("DECISION_INVALID", "decision field is too large", field=field)
    if not DECISION_ID.fullmatch(result["id"]):
        raise _error("DECISION_INVALID", "decision id is invalid")
    current_digest = contract_digest(contract)
    all_decisions = [
        record.get("payload")
        for record in records
        if isinstance(record, Mapping) and record.get("kind") == "decision"
    ]
    if any(isinstance(item, Mapping) and item.get("id") == result["id"] for item in all_decisions):
        raise _error("DECISION_CONFLICT", "decision id was already used")
    current = decisions_for_contract(records, contract)
    if any(item.get("kind") == result["kind"] and item.get("subject") == result["subject"] for item in current):
        raise _error("DECISION_CONFLICT", "decision kind and subject were already decided")
    criterion_ids = {item["id"] for item in contract["acceptance_criteria"]}
    if result["kind"] == "criterion-waiver":
        if result["subject"] not in criterion_ids or result["outcome"] != "waived":
            raise _error("DECISION_INVALID", "criterion waiver subject or outcome is invalid")
    elif result["kind"] == "assurance-waiver":
        if result["outcome"] != "waived":
            raise _error("DECISION_INVALID", "assurance waiver outcome is invalid")
    if len(canonical_json_bytes(result)) > 16 * 1024:
        raise _error("DECISION_INVALID", "decision exceeds the payload budget")
    del current_digest
    return freeze_json(result)


def criterion_waivers(records: Sequence[object], contract: Mapping[str, object]) -> dict:
    return {
        item["subject"]: item
        for item in decisions_for_contract(records, contract)
        if item.get("kind") == "criterion-waiver" and item.get("outcome") == "waived"
    }


def assurance_waiver(
    records: Sequence[object], contract: Mapping[str, object], node_id: str
) -> Optional[dict]:
    for item in decisions_for_contract(records, contract):
        if (
            item.get("kind") == "assurance-waiver"
            and item.get("subject") == node_id
            and item.get("outcome") == "waived"
        ):
            return item
    return None


def resource_requests(
    payload: Mapping[str, object], repository_ids: Sequence[str]
) -> tuple:
    value = payload.get("resources")
    if value is None:
        return ()
    if not isinstance(value, Mapping) or set(value) != {"items"}:
        raise _error("NODE_OUTPUT_INVALID", "resources must contain exactly items")
    items = value.get("items")
    if not isinstance(items, (list, tuple)) or len(items) > MAX_RESOURCE_ITEMS:
        raise _error("NODE_OUTPUT_INVALID", "resource item list is invalid")
    normalized = []
    seen = set()
    member_ids = tuple(repository_ids)
    for item in items:
        expected_fields = {"path", "role", "normalizer", "repository_id"}
        if not isinstance(item, Mapping) or set(item) != expected_fields:
            raise _error("NODE_OUTPUT_INVALID", "resource item fields are invalid")
        repository_id = item.get("repository_id")
        if repository_id not in member_ids:
            raise _error(
                "NODE_OUTPUT_INVALID",
                "resource repository id is invalid",
                repository_id=repository_id,
                expected_repository_ids=list(member_ids),
            )
        path = item.get("path")
        role = item.get("role")
        normalizer = item.get("normalizer")
        if not isinstance(path, str) or not path or len(path.encode("utf-8")) > 4096:
            raise _error("NODE_OUTPUT_INVALID", "resource path is invalid")
        if role not in ("governing", "reported"):
            raise _error("NODE_OUTPUT_INVALID", "resource role is invalid")
        if normalizer not in ("none", OPENSPEC_TASKS_NORMALIZER):
            raise _error("NODE_OUTPUT_INVALID", "resource normalizer is invalid")
        identity = (repository_id, path, role, normalizer)
        if identity in seen:
            raise _error("NODE_OUTPUT_INVALID", "resource item is duplicated")
        seen.add(identity)
        normalized.append(
            {
                "repository_id": repository_id,
                "path": path,
                "role": role,
                "normalizer": normalizer,
            }
        )
    return tuple(normalized)


_TASK_BOX = re.compile(rb"(?m)^([ \t]*-[ \t]+)\[[ xX]\]")


def normalize_resource_bytes(data: bytes, normalizer: str) -> bytes:
    if normalizer == "none":
        return data
    if normalizer == OPENSPEC_TASKS_NORMALIZER:
        return _TASK_BOX.sub(rb"\1[ ]", data)
    raise _error("RESOURCE_NORMALIZER_INVALID", "resource normalizer is unsupported")


def governing_resource_requests(records: Sequence[object], contract: Mapping[str, object]) -> tuple:
    """Return current-contract resource bindings needed to reproduce snapshots.

    Reported resources do not govern artifact freshness, but they remain part
    of the canonical snapshot envelope and therefore must be recaptured with
    the same request identity on later actions.
    """
    digest = contract_digest(contract)
    seen = set()
    result = []
    for record, artifact in artifact_records(records):
        if artifact.get("contract_digest") != digest:
            continue
        resources = artifact.get("resources")
        if not isinstance(resources, (list, tuple)):
            continue
        for resource in resources:
            if not isinstance(resource, Mapping) or resource.get("role") not in (
                "governing",
                "reported",
            ):
                continue
            key = (
                resource.get("repository_id"),
                resource.get("path"),
                resource.get("role"),
                resource.get("normalizer", "none"),
            )
            if (
                key not in seen
                and isinstance(key[0], str)
                and isinstance(key[1], str)
            ):
                seen.add(key)
                result.append(
                    {
                        "repository_id": key[0],
                        "path": key[1],
                        "role": key[2],
                        "normalizer": key[3],
                    }
                )
    return tuple(result)


def _snapshot_resource_map(snapshot: Optional[Mapping[str, object]]) -> dict:
    if (
        not isinstance(snapshot, Mapping)
        or snapshot.get("schema") != REPOSITORY_SET_SNAPSHOT_SCHEMA
    ):
        return {}
    members = snapshot.get("repositories")
    if not isinstance(members, (list, tuple)):
        return {}
    result = {}
    for member in members:
        if not isinstance(member, Mapping):
            continue
        repository_id = member.get("repository_id")
        member_snapshot = member.get("snapshot")
        resources = (
            member_snapshot.get("resources")
            if isinstance(member_snapshot, Mapping)
            else None
        )
        if not isinstance(repository_id, str) or not isinstance(
            resources, (list, tuple)
        ):
            continue
        for item in resources:
            if isinstance(item, Mapping):
                result[
                    (
                        repository_id,
                        item.get("path"),
                        item.get("normalizer", "none"),
                    )
                ] = item
    return result


def _changed_repository_ids(left: object, right: object) -> tuple:
    left_map = _repository_snapshot_map(left)
    right_map = _repository_snapshot_map(right)
    if not left_map or not right_map:
        return ()
    repository_ids = sorted(set(left_map) | set(right_map))
    return tuple(
        repository_id
        for repository_id in repository_ids
        if not isinstance(left_map.get(repository_id), Mapping)
        or not isinstance(right_map.get(repository_id), Mapping)
        or left_map[repository_id].get("digest")
        != right_map[repository_id].get("digest")
    )


def artifact_freshness(
    records: Sequence[object],
    contract: Mapping[str, object],
    current_snapshot: Optional[Mapping[str, object]],
) -> dict:
    """Return bounded current/stale reasons for every typed artifact."""
    current_digest = contract_digest(contract)
    pairs = artifact_records(records)
    artifacts_by_id = artifact_by_record_id(records)
    records_by_id = record_by_id(records)
    latest_by_type = {}
    sources = []
    for record, artifact in pairs:
        if artifact.get("contract_digest") == current_digest:
            latest_by_type[artifact.get("type")] = record.get("record_id")
            if artifact.get("workspace_role") == "produces-source":
                sources.append((record, artifact))
    latest_source = sources[-1] if sources else None
    resource_map = _snapshot_resource_map(current_snapshot)
    result = {}
    for record, artifact in pairs:
        reasons = []
        record_id = record.get("record_id")
        if artifact.get("contract_digest") != current_digest:
            reasons.append("contract_changed")
        inputs = artifact.get("inputs")
        if not isinstance(inputs, (list, tuple)):
            reasons.append("inputs_invalid")
            inputs = ()
        for item in inputs:
            if not isinstance(item, Mapping):
                reasons.append("input_invalid")
                continue
            referenced = artifacts_by_id.get(item.get("record_id"))
            referenced_record = records_by_id.get(item.get("record_id"))
            if (
                referenced is None
                or referenced_record is None
                or referenced.get("digest") != item.get("artifact_digest")
                or referenced_record.get("digest") != item.get("record_digest")
            ):
                reasons.append("input_missing")
                continue
            if referenced.get("contract_digest") != current_digest:
                reasons.append("input_contract_changed")
            if item.get("edge") == "governing" and latest_by_type.get(item.get("type")) != item.get("record_id"):
                reasons.append("governing_input_replaced")
        resources = artifact.get("resources", ())
        if isinstance(resources, (list, tuple)):
            for resource in resources:
                if not isinstance(resource, Mapping) or resource.get("role") != "governing":
                    continue
                repository_id = resource.get("repository_id")
                current = resource_map.get(
                    (
                        repository_id,
                        resource.get("path"),
                        resource.get("normalizer", "none"),
                    )
                )
                if current is None or current.get("semantic_sha256") != resource.get("semantic_sha256"):
                    reasons.append("governing_resource_changed")
                    if isinstance(repository_id, str):
                        reasons.append(
                            "governing_resource_changed:" + repository_id
                        )
        role = artifact.get("workspace_role")
        if role == "verifies-source" and latest_source is not None:
            snapshot = artifact.get("snapshot")
            source_snapshot = latest_source[1].get("snapshot")
            if not isinstance(snapshot, Mapping) or not isinstance(source_snapshot, Mapping) or snapshot.get("digest") != source_snapshot.get("digest"):
                reasons.append("source_replaced")
                reasons.extend(
                    "source_replaced:" + repository_id
                    for repository_id in _changed_repository_ids(
                        snapshot, source_snapshot
                    )
                )
        if latest_source is not None and record_id == latest_source[0].get("record_id"):
            snapshot = artifact.get("snapshot")
            if not isinstance(snapshot, Mapping) or not isinstance(current_snapshot, Mapping) or snapshot.get("digest") != current_snapshot.get("digest"):
                reasons.append("workspace_changed")
                reasons.extend(
                    "workspace_changed:" + repository_id
                    for repository_id in _changed_repository_ids(
                        snapshot, current_snapshot
                    )
                )
        if latest_by_type.get(artifact.get("type")) != record_id:
            reasons.append("superseded")
        result[str(record_id)] = {
            "current": not reasons,
            "reasons": sorted(set(reasons)),
            "type": artifact.get("type"),
            "digest": artifact.get("digest"),
        }
    # Governing lineage propagates staleness through otherwise immutable
    # records.  The loop is bounded by the ledger length and therefore cannot
    # turn malformed cyclic input data into unbounded replay work.
    for _ in range(len(pairs)):
        changed = False
        for record, artifact in pairs:
            record_id = str(record.get("record_id"))
            entry = result[record_id]
            reasons = set(entry["reasons"])
            inputs = artifact.get("inputs", ())
            if isinstance(inputs, (list, tuple)):
                for item in inputs:
                    if not isinstance(item, Mapping) or item.get("edge") != "governing":
                        continue
                    upstream = result.get(str(item.get("record_id")))
                    if upstream is not None and not upstream["current"]:
                        reasons.add("governing_input_stale")
                        reasons.update(
                            reason
                            for reason in upstream["reasons"]
                            if isinstance(reason, str)
                            and reason.startswith(
                                (
                                    "governing_resource_changed:",
                                    "source_replaced:",
                                    "workspace_changed:",
                                )
                            )
                        )
            normalized = sorted(reasons)
            if normalized != entry["reasons"]:
                entry["reasons"] = normalized
                entry["current"] = not normalized
                changed = True
        if not changed:
            break
    return result


def resolve_inputs(
    records: Sequence[object],
    contract: Mapping[str, object],
    input_contracts: Iterable[object],
    current_snapshot: Optional[Mapping[str, object]],
    *,
    allow_revision_source: bool = False,
) -> tuple:
    pairs = artifact_records(records)
    current_digest = contract_digest(contract)
    freshness = artifact_freshness(records, contract, current_snapshot)
    resolved = []
    for declared in input_contracts:
        artifact_type = getattr(declared, "artifact_type", None)
        edge = getattr(declared, "edge_kind", None)
        candidates = [
            (record, artifact)
            for record, artifact in pairs
            if (
                artifact.get("type") == artifact_type
                or (
                    allow_revision_source
                    and artifact_type == "repository-baseline"
                    and artifact.get("type") == "revision-source"
                )
            )
            and artifact.get("contract_digest") == current_digest
        ]
        if edge == "source-predecessor":
            candidates = [
                pair for pair in pairs
                if pair[1].get("contract_digest") == current_digest
                and pair[1].get("workspace_role") == "produces-source"
                and (
                    artifact_type in (None, "*", pair[1].get("type"))
                    or (
                        allow_revision_source
                        and artifact_type == "repository-baseline"
                        and pair[1].get("type") == "revision-source"
                    )
                )
            ]
            if candidates:
                candidates = candidates[-1:]
                candidate_id = str(candidates[0][0].get("record_id"))
                if not freshness.get(candidate_id, {}).get("current"):
                    candidates = []
        elif edge == "governing":
            candidates = [pair for pair in candidates if freshness.get(str(pair[0].get("record_id")), {}).get("current")]
        if not candidates:
            raise _error(
                "ARTIFACT_INPUT_MISSING",
                "required artifact input is unavailable",
                artifact_type=artifact_type,
                edge=edge,
            )
        record, artifact = candidates[-1]
        resolved.append(
            {
                "type": artifact.get("type"),
                "edge": edge,
                "record_id": record.get("record_id"),
                "record_digest": record.get("digest"),
                "artifact_digest": artifact.get("digest"),
                "snapshot_digest": (
                    artifact.get("snapshot", {}).get("digest")
                    if isinstance(artifact.get("snapshot"), Mapping)
                    else None
                ),
                "summary": _artifact_summary(artifact),
            }
        )
    return tuple(resolved)


def _artifact_summary(artifact: Mapping[str, object]) -> str:
    body = artifact.get("body")
    if isinstance(body, Mapping):
        for key in ("summary", "change_summary", "handoff_recommendation"):
            value = body.get(key)
            if isinstance(value, str):
                return value[:512]
    return str(artifact.get("type", "artifact"))


def seal_action_binding(value: Mapping[str, object]) -> Mapping[str, object]:
    base = {str(key): json_value(item) for key, item in value.items() if key != "digest"}
    base["schema"] = ACTION_BINDING_SCHEMA
    return freeze_json(
        {**base, "digest": _seal(product_domain("action-binding"), base)}
    )


def validate_action_binding(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error("ACTION_BINDING_INVALID", "action binding is required")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    expected_fields = {
        "schema",
        "task_id",
        "task_revision",
        "action_id",
        "node_id",
        "contract_revision",
        "contract_digest",
        "inputs",
        "source_predecessor",
        "starting_snapshot_digest",
    }
    if (
        set(plain) != expected_fields
        or plain.get("schema") != ACTION_BINDING_SCHEMA
        or not isinstance(digest, str)
    ):
        raise _error("ACTION_BINDING_INVALID", "action binding schema is invalid")
    integer_fields = (plain.get("task_revision"), plain.get("contract_revision"))
    string_fields = (
        plain.get("task_id"),
        plain.get("action_id"),
        plain.get("node_id"),
        plain.get("contract_digest"),
        plain.get("starting_snapshot_digest"),
    )
    if (
        any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in integer_fields)
        or any(not isinstance(item, str) or not item for item in string_fields)
        or not isinstance(plain.get("inputs"), list)
        or (
            plain.get("source_predecessor") is not None
            and not isinstance(plain.get("source_predecessor"), dict)
        )
    ):
        raise _error("ACTION_BINDING_INVALID", "action binding fields are invalid")
    if _seal(product_domain("action-binding"), plain) != digest:
        raise _error("ACTION_BINDING_INVALID", "action binding digest is invalid")
    return freeze_json({**plain, "digest": digest})


def make_action_binding(
    *,
    task_id: str,
    revision: int,
    action_id: str,
    node_id: str,
    contract: Mapping[str, object],
    inputs: Sequence[Mapping[str, object]],
    current_snapshot: Mapping[str, object],
) -> Mapping[str, object]:
    predecessor = next((item for item in inputs if item.get("edge") == "source-predecessor"), None)
    starting_digest = current_snapshot.get("digest")
    if not isinstance(starting_digest, str):
        raise _error("ACTION_BINDING_INVALID", "starting snapshot digest is unavailable")
    return seal_action_binding(
        {
            "task_id": task_id,
            "task_revision": revision,
            "action_id": action_id,
            "node_id": node_id,
            "contract_revision": contract["revision"],
            "contract_digest": contract_digest(contract),
            "inputs": [json_value(item) for item in inputs],
            "source_predecessor": json_value(predecessor) if predecessor is not None else None,
            "starting_snapshot_digest": starting_digest,
        }
    )


def coverage_view(
    contract: Mapping[str, object],
    records: Sequence[object],
    verification_payload: Optional[Mapping[str, object]],
) -> dict:
    waivers = criterion_waivers(records, contract)
    coverage = (
        verification_payload.get("coverage", {})
        if isinstance(verification_payload, Mapping)
        else {}
    )
    submitted = (
        coverage.get("criteria", {})
        if isinstance(coverage, Mapping)
        else {}
    )
    result = {}
    for item in contract["acceptance_criteria"]:
        criterion_id = item["id"]
        if criterion_id in waivers:
            result[criterion_id] = {"status": "waived", "decision": waivers[criterion_id]}
        else:
            status = submitted.get(criterion_id) if isinstance(submitted, Mapping) else None
            result[criterion_id] = {"status": status if status in ("proven", "unverified") else "unverified"}
    return result


def _dossier_base(
    *,
    contract: Mapping[str, object],
    records: Sequence[object],
    current_snapshot: Mapping[str, object],
    outcome: str,
    supplied: Mapping[str, object],
) -> dict:
    current_digest = contract_digest(contract)
    pairs = [
        pair
        for pair in artifact_records(records)
        if pair[1].get("contract_digest") == current_digest
    ]
    freshness = artifact_freshness(records, contract, current_snapshot)
    latest_verification_pair = next(
        (pair for pair in reversed(pairs) if pair[1].get("type") == "verification-result"),
        None,
    )
    latest_review_pair = next(
        (pair for pair in reversed(pairs) if pair[1].get("type") == "review-result"),
        None,
    )
    latest_verification = None if latest_verification_pair is None else latest_verification_pair[1]
    latest_review_state = (
        freshness.get(str(latest_review_pair[0].get("record_id")), {})
        if latest_review_pair is not None
        else {}
    )
    latest_review = (
        latest_review_pair[1]
        if latest_review_pair is not None
        and latest_review_state.get("current") is True
        else None
    )
    verification_body = latest_verification.get("body") if isinstance(latest_verification, Mapping) else None
    review_body = latest_review.get("body") if isinstance(latest_review, Mapping) else None
    review_assurance = None
    if isinstance(latest_review, Mapping) and isinstance(review_body, Mapping):
        producer = latest_review.get("producer")
        node_id = producer.get("node_id") if isinstance(producer, Mapping) else None
        waiver = (
            assurance_waiver(records, contract, node_id)
            if isinstance(node_id, str)
            else None
        )
        if review_body.get("outcome") == "approved" and review_body.get("assurance") == "independent":
            review_assurance = {"status": "approved", "level": "independent"}
        elif review_body.get("outcome") == "unavailable" and waiver is not None:
            review_assurance = {
                "status": "waived",
                "level": review_body.get("assurance"),
                "decision": waiver,
                "remaining_risk": "independent review assurance was explicitly waived",
            }
        else:
            review_assurance = {
                "status": review_body.get("outcome"),
                "level": review_body.get("assurance"),
            }
    documentation = next(
        (
            artifact.get("body")
            for _, artifact in reversed(pairs)
            if artifact.get("type") == "documentation"
            and isinstance(artifact.get("body"), Mapping)
        ),
        None,
    )
    baseline = next(
        (
            artifact.get("snapshot")
            for _, artifact in pairs
            if artifact.get("type") in ("repository-baseline", "revision-source")
        ),
        None,
    )
    return {
        "schema": DELIVERY_DOSSIER_SCHEMA,
        "outcome": outcome,
        "contract": json_value(contract),
        "contract_digest": contract_digest(contract),
        "change_summary": supplied.get("change_summary", ""),
        "coverage": coverage_view(contract, records, verification_body),
        "verification": json_value(verification_body) if isinstance(verification_body, Mapping) else None,
        "review": json_value(review_body) if isinstance(review_body, Mapping) else None,
        "review_assurance": json_value(review_assurance),
        "documentation": json_value(documentation),
        "decisions": decisions_for_contract(records, contract),
        "artifacts": [
            {
                "record_id": record.get("record_id"),
                "type": artifact.get("type"),
                "digest": artifact.get("digest"),
                "producer": json_value(artifact.get("producer")),
                "current": freshness.get(str(record.get("record_id")), {}).get("current", False),
                "stale_reasons": freshness.get(str(record.get("record_id")), {}).get("reasons", []),
            }
            for record, artifact in pairs
        ],
        "repository_baseline": json_value(baseline),
        "repository_snapshot": json_value(current_snapshot),
        "remaining_risks": supplied.get("remaining_risks", {}),
        "handoff_recommendation": supplied.get("handoff_recommendation", ""),
    }


def _snapshot_summary(snapshot: object) -> Optional[dict]:
    if not isinstance(snapshot, Mapping):
        return None
    return {
        key: json_value(snapshot.get(key))
        for key in (
            "digest",
            "repository_root",
            "git_common_dir",
            "head",
            "branch",
            "clean",
            "status_sha256",
            "status_bytes",
        )
    }


def _repository_snapshot_map(snapshot: object) -> dict:
    if not isinstance(snapshot, Mapping) or snapshot.get("schema") != REPOSITORY_SET_SNAPSHOT_SCHEMA:
        return {}
    members = snapshot.get("repositories")
    if not isinstance(members, (list, tuple)):
        return {}
    return {
        item.get("repository_id"): item.get("snapshot")
        for item in members
        if isinstance(item, Mapping) and isinstance(item.get("repository_id"), str)
    }


def generate_dossier(
    *,
    contract: Mapping[str, object],
    records: Sequence[object],
    current_snapshot: Mapping[str, object],
    outcome: str,
    supplied: Mapping[str, object],
    repositories: Sequence[object],
) -> dict:
    """Generate the current repository-set Delivery Dossier."""
    base = _dossier_base(
        contract=contract,
        records=records,
        current_snapshot=current_snapshot,
        outcome=outcome,
        supplied=supplied,
    )
    current_digest = contract_digest(contract)
    current_contract_pairs = [
        pair
        for pair in artifact_records(records)
        if pair[1].get("contract_digest") == current_digest
    ]
    all_pairs = artifact_records(records)
    freshness = artifact_freshness(records, contract, current_snapshot)
    verification_attempts = []
    review_attempts = []
    current_verification = None
    for record, artifact in all_pairs:
        artifact_type = artifact.get("type")
        if artifact_type not in ("verification-result", "review-result"):
            continue
        entry = freshness.get(str(record.get("record_id")), {})
        body = artifact.get("body")
        attempt = {
            "record_id": record.get("record_id"),
            "producer": json_value(artifact.get("producer")),
            "current": bool(entry.get("current", False)),
            "stale_reasons": json_value(entry.get("reasons", [])),
            "result": json_value(body) if isinstance(body, Mapping) else None,
        }
        if artifact_type == "verification-result":
            verification_attempts.append(attempt)
            if attempt["current"] and isinstance(body, Mapping):
                current_verification = json_value(body)
        else:
            review_attempts.append(attempt)

    baseline_map = _repository_snapshot_map(base.get("repository_baseline"))
    final_map = _repository_snapshot_map(current_snapshot)
    members = []
    changed_repositories = []
    for repository in repositories:
        repository_id = getattr(repository, "repository_id", None)
        path = getattr(repository, "path", None)
        baseline = baseline_map.get(repository_id)
        final = final_map.get(repository_id)
        changed = (
            isinstance(baseline, Mapping)
            and isinstance(final, Mapping)
            and baseline.get("digest") != final.get("digest")
        )
        if changed:
            changed_repositories.append(repository_id)
        members.append(
            {
                "repository_id": repository_id,
                "path": path,
                "baseline": _snapshot_summary(baseline),
                "final": _snapshot_summary(final),
                "changed": changed,
            }
        )

    scoped_resources = []
    for record, artifact in current_contract_pairs:
        resources = artifact.get("resources")
        if not isinstance(resources, (list, tuple)):
            continue
        artifact_state = freshness.get(str(record.get("record_id")), {})
        for resource in resources:
            if not isinstance(resource, Mapping):
                continue
            scoped_resources.append(
                {
                    "record_id": record.get("record_id"),
                    "artifact_type": artifact.get("type"),
                    "current": bool(artifact_state.get("current", False)),
                    "stale_reasons": json_value(artifact_state.get("reasons", [])),
                    "resource": json_value(resource),
                }
            )

    latest_source = next(
        (
            (record, artifact)
            for record, artifact in reversed(current_contract_pairs)
            if artifact.get("workspace_role") == "produces-source"
        ),
        None,
    )
    source_entry = (
        freshness.get(str(latest_source[0].get("record_id")), {})
        if latest_source is not None
        else {}
    )
    verification_entry = next(
        (
            freshness.get(str(record.get("record_id")), {})
            for record, artifact in reversed(current_contract_pairs)
            if artifact.get("type") == "verification-result"
        ),
        {},
    )
    stale_reasons = sorted(
        set(source_entry.get("reasons", ()))
        | set(verification_entry.get("reasons", ()))
    )

    return {
        **base,
        "schema": DELIVERY_DOSSIER_SCHEMA,
        "repository_set": {
            "id": current_snapshot.get("repository_set_id"),
            "digest": current_snapshot.get("digest"),
            "members": members,
        },
        "changed_repositories": changed_repositories,
        "verification_attempts": verification_attempts,
        "review_attempts": review_attempts,
        "verification": current_verification,
        "resources": scoped_resources,
        "aggregate_freshness": {
            "current": bool(source_entry.get("current", False))
            and bool(verification_entry.get("current", False)),
            "source_current": bool(source_entry.get("current", False)),
            "verification_current": bool(
                verification_entry.get("current", False)
            ),
            "stale_reasons": stale_reasons,
        },
    }
