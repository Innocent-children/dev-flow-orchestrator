"""Bounded read models for the integrated local Web UI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Optional, Tuple

from ._platform.paths import path_is_absolute, paths_equal
from .delivery import effective_contract
from .engine import is_terminal_state, task_view
from .model import DevFlowError, TaskState
from .product import PRODUCT_IDENTITY, PRODUCT_VERSION
from .workflow import WorkflowDefinition


DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
MAX_QUERY_LENGTH = 256
MAX_TEXT_LENGTH = 1024


def _bounded_text(value: object, limit: int = MAX_TEXT_LENGTH) -> Optional[str]:
    if not isinstance(value, str):
        return None
    return value if len(value) <= limit else value[:limit]


def _page(offset: int, limit: int) -> Tuple[int, int]:
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 1
        or limit > MAX_PAGE_LIMIT
    ):
        raise DevFlowError(
            "VIEW_QUERY_INVALID",
            "offset and limit are outside the supported view bounds",
            details={"max_limit": MAX_PAGE_LIMIT},
        )
    return offset, limit


def envelope(view: str, observed_at: str, result: Mapping[str, object]) -> dict:
    return {
        "ok": True,
        "version": PRODUCT_VERSION,
        "product_identity": PRODUCT_IDENTITY,
        "view": view,
        "observed_at": observed_at,
        "result": dict(result),
    }


def product_metadata(observed_at: str) -> dict:
    return envelope(
        "product-meta",
        observed_at,
        {
            "product": "dev-flow-orchestrator",
            "version": PRODUCT_VERSION,
            "product_identity": PRODUCT_IDENTITY,
            "surface": "local-read-only-web-ui",
            "capabilities": ["stored-inspection", "explicit-live-observation"],
        },
    )


def _contract_summary(state: TaskState) -> dict:
    contract = effective_contract(state.original_contract, state.records)
    criteria = contract.get("acceptance_criteria", ())
    criterion_ids = []
    criterion_summaries = []
    if isinstance(criteria, Sequence) and not isinstance(criteria, (str, bytes)):
        for item in criteria[:64]:
            identifier = item.get("id") if isinstance(item, Mapping) else None
            if isinstance(identifier, str):
                criterion_ids.append(_bounded_text(identifier, 128))
                criterion_summaries.append(
                    {
                        "id": _bounded_text(identifier, 128),
                        "statement": _bounded_text(item.get("statement")),
                    }
                )
    return {
        "revision": contract.get("revision"),
        "summary": _bounded_text(contract.get("summary")),
        "criterion_ids": criterion_ids,
        "criteria": criterion_summaries,
        "constraint_count": len(contract.get("constraints", ()))
        if isinstance(contract.get("constraints"), Sequence)
        else 0,
        "risk_count": len(contract.get("risks", ()))
        if isinstance(contract.get("risks"), Sequence)
        else 0,
        "open_question_count": len(contract.get("open_questions", ()))
        if isinstance(contract.get("open_questions"), Sequence)
        else 0,
    }


def _repository_ids(state: TaskState) -> list:
    return [item.repository_id for item in state.repositories]


def _repository_membership(state: TaskState) -> dict:
    return {
        "repository_set_id": _bounded_text(state.repository_set_id, 128),
        "repository_ids": _repository_ids(state),
        "count": len(state.repositories),
    }


def _inventory_row(state: TaskState, definition: WorkflowDefinition) -> dict:
    terminal = is_terminal_state(state, definition)
    return {
        "task_id": state.task_id,
        "revision": state.revision,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
        "workflow": state.workflow_id,
        "workflow_version": state.workflow_version,
        "status": state.status,
        "current_node": state.current_node,
        "terminal": terminal,
        "health": "terminal" if terminal else "not-evaluated",
        "repository_ids": _repository_ids(state),
        "repository_count": len(state.repositories),
        "contract": _contract_summary(state),
    }


def inventory_view(
    entries: Sequence[Tuple[TaskState, WorkflowDefinition]],
    diagnostics: Sequence[Mapping[str, object]],
    observed_at: str,
    *,
    query: str = "",
    statuses: Sequence[str] = (),
    workflows: Sequence[str] = (),
    repositories: Sequence[str] = (),
    terminal: Optional[bool] = None,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict:
    offset, limit = _page(offset, limit)
    if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH:
        raise DevFlowError(
            "VIEW_QUERY_INVALID",
            "inventory query is outside the supported view bounds",
            details={"max_query_length": MAX_QUERY_LENGTH},
        )
    if terminal is not None and not isinstance(terminal, bool):
        raise DevFlowError("VIEW_QUERY_INVALID", "terminal filter must be boolean")
    for values in (statuses, workflows, repositories):
        if any(not isinstance(value, str) or not value for value in values):
            raise DevFlowError("VIEW_QUERY_INVALID", "inventory filters are invalid")

    normalized_query = query.casefold().strip()
    status_filter = set(statuses)
    workflow_filter = set(workflows)
    repository_filter = set(repositories)
    rows = []
    for state, definition in entries:
        row = _inventory_row(state, definition)
        searchable = " ".join(
            [
                state.task_id,
                state.status,
                state.current_node,
                state.workflow_id,
                str(row["contract"].get("summary") or ""),
                *_repository_ids(state),
                *(item.path for item in state.repositories),
            ]
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        if status_filter and state.status not in status_filter:
            continue
        if workflow_filter and state.workflow_id not in workflow_filter:
            continue
        repository_matches = any(
            candidate == item.repository_id or paths_equal(candidate, item.path)
            for candidate in repository_filter
            for item in state.repositories
        )
        if repository_filter and not repository_matches:
            continue
        if terminal is not None and row["terminal"] is not terminal:
            continue
        rows.append(row)

    rows.sort(key=lambda item: item["task_id"].encode("utf-8"))
    rows.sort(key=lambda item: item["updated_at"], reverse=True)
    selected = rows[offset : offset + limit]
    next_offset = offset + len(selected) if offset + len(selected) < len(rows) else None
    safe_diagnostics = [
        {
            key: value
            for key, value in diagnostic.items()
            if key in {"code", "task_id", "entry", "entry_truncated"}
        }
        for diagnostic in diagnostics[:MAX_PAGE_LIMIT]
    ]
    return envelope(
        "task-inventory",
        observed_at,
        {
            "health": "degraded" if diagnostics else "ready",
            "filters": {
                "q": query.strip(),
                "status": sorted(status_filter),
                "workflow": sorted(workflow_filter),
                "repository": sorted(
                    value for value in repository_filter if not path_is_absolute(value)
                ),
                "repository_path_count": sum(
                    1 for value in repository_filter if path_is_absolute(value)
                ),
                "terminal": terminal,
            },
            "tasks": selected,
            "diagnostics": safe_diagnostics,
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(selected),
                "total": len(rows),
                "next_offset": next_offset,
            },
        },
    )


def _timeline_record(record: object, sequence: int) -> dict:
    if not isinstance(record, Mapping):
        return {"sequence": sequence, "kind": "unavailable"}
    artifact = record.get("artifact")
    producer = record.get("producer")
    transition = record.get("transition")
    payload = record.get("payload")
    return {
        "sequence": sequence,
        "revision": record.get("task_revision")
        if isinstance(record.get("task_revision"), int)
        else None,
        "kind": _bounded_text(record.get("kind"), 128),
        "record_id": _bounded_text(record.get("record_id"), 128),
        "node": _bounded_text(
            producer.get("node_id") if isinstance(producer, Mapping) else None,
            128,
        ),
        "action_id": _bounded_text(
            producer.get("action_id") if isinstance(producer, Mapping) else None,
            128,
        ),
        "recorded_at": _bounded_text(
            record.get("timestamp") or record.get("recorded_at"), 128
        ),
        "summary": _bounded_text(
            payload.get("summary") or payload.get("reason")
            if isinstance(payload, Mapping)
            else None
        ),
        "transition": {
            key: _bounded_text(transition.get(key), 128)
            for key in ("from", "to", "status", "route")
        }
        if isinstance(transition, Mapping)
        else None,
        "artifact_type": _bounded_text(
            artifact.get("type") if isinstance(artifact, Mapping) else None,
            128,
        ),
        "artifact_id": _bounded_text(
            artifact.get("artifact_id") if isinstance(artifact, Mapping) else None,
            128,
        ),
        "artifact_digest": _bounded_text(
            artifact.get("digest") if isinstance(artifact, Mapping) else None,
            128,
        ),
    }


def _recent_timeline(state: TaskState) -> dict:
    records = list(reversed(state.records))[:8]
    return {
        "records": [
            _timeline_record(record, index + 1)
            for index, record in enumerate(records)
        ],
        "returned": len(records),
        "total": len(state.records),
    }


def _artifact_summaries(state: TaskState) -> list:
    summaries = []
    for record in reversed(state.records):
        artifact = record.get("artifact") if isinstance(record, Mapping) else None
        if not isinstance(artifact, Mapping):
            continue
        summaries.append(
            {
                "record_id": _bounded_text(record.get("record_id"), 128),
                "type": _bounded_text(artifact.get("type"), 128),
                "artifact_id": _bounded_text(artifact.get("artifact_id"), 128),
                "digest": _bounded_text(artifact.get("digest"), 128),
            }
        )
        if len(summaries) >= MAX_PAGE_LIMIT:
            break
    return summaries


def _bounded_dossier(dossier: object) -> object:
    if not isinstance(dossier, Mapping):
        return None
    coverage = dossier.get("coverage")
    return {
        "record_id": _bounded_text(dossier.get("record_id"), 128),
        "digest": _bounded_text(dossier.get("digest"), 128),
        "outcome": _bounded_text(dossier.get("outcome"), 128),
        "schema": _bounded_text(dossier.get("schema"), 128),
        "repository_set_id": _bounded_text(dossier.get("repository_set_id"), 128),
        "coverage": {
            key: value
            for key, value in coverage.items()
            if key in {"proven", "waived", "unverified"}
            and isinstance(value, int)
            and not isinstance(value, bool)
        }
        if isinstance(coverage, Mapping)
        else {},
        "current": dossier.get("current")
        if isinstance(dossier.get("current"), bool)
        else None,
        "stale_reasons": [
            _bounded_text(item, 128)
            for item in dossier.get("stale_reasons", ())[:8]
            if isinstance(item, str)
        ]
        if isinstance(dossier.get("stale_reasons"), Sequence)
        and not isinstance(dossier.get("stale_reasons"), (str, bytes))
        else [],
    }


def _dossier_summary(state: TaskState, definition: WorkflowDefinition) -> object:
    return _bounded_dossier(task_view(state, definition, None).get("dossier"))


def _state_summary(state: TaskState, terminal: bool) -> dict:
    return {
        "status": state.status,
        "current_node": state.current_node,
        "terminal": terminal,
        "outcome": state.status if terminal else None,
    }


def _stored_why_next(state: TaskState, terminal: bool) -> dict:
    return {
        **_state_summary(state, terminal),
        "readiness": "terminal" if terminal else "not-evaluated",
        "declared_action": None,
        "action_id": None,
        "handler": None,
        "blocker": None,
        "blocked_code": None,
        "retry": None,
        "assurance": None,
        "obligation": None,
        "summary": "Task is terminal"
        if terminal
        else "Run explicit live observation to derive current action readiness",
    }


def _recovery_brief(
    state: TaskState,
    *,
    terminal: bool,
    contract: Mapping[str, object],
    why_next: Mapping[str, object],
    dossier: object,
    freshness: object = None,
    review: object = None,
) -> dict:
    assurance = why_next.get("assurance")
    outstanding = (
        list(assurance.get("outstanding", ()))
        if isinstance(assurance, Mapping)
        and isinstance(assurance.get("outstanding"), Sequence)
        and not isinstance(assurance.get("outstanding"), (str, bytes))
        else []
    )
    exhausted = (
        list(assurance.get("exhausted", ()))
        if isinstance(assurance, Mapping)
        and isinstance(assurance.get("exhausted"), Sequence)
        and not isinstance(assurance.get("exhausted"), (str, bytes))
        else []
    )
    return {
        "prompt": "$follow-dev-flow task_id={}".format(state.task_id),
        "task_id": state.task_id,
        "revision": state.revision,
        "requirement": _bounded_text(state.requirement),
        "contract": dict(contract),
        "contract_summary": contract.get("summary"),
        "repositories": _repository_membership(state),
        "repository_ids": _repository_ids(state),
        "updated_at": state.updated_at,
        "workflow": state.workflow_id,
        "status": state.status,
        "current_node": state.current_node,
        "state": _state_summary(state, terminal),
        "why_next": dict(why_next),
        "retry": why_next.get("retry"),
        "assurance": assurance,
        "outstanding_assurance": outstanding,
        "exhausted_assurance": exhausted,
        "freshness": freshness,
        "review": review,
        "dossier": dossier,
        "recent_timeline": _recent_timeline(state),
    }


def stored_task_view(
    state: TaskState,
    definition: WorkflowDefinition,
    observed_at: str,
    *,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict:
    offset, limit = _page(offset, limit)
    terminal = is_terminal_state(state, definition)
    ordered_records = list(reversed(state.records))
    records = ordered_records[offset : offset + limit]
    next_offset = offset + len(records) if offset + len(records) < len(ordered_records) else None
    contract = _contract_summary(state)
    dossier = _dossier_summary(state, definition)
    why_next = _stored_why_next(state, terminal)
    result = {
        "task": {
            "task_id": state.task_id,
            "requirement": _bounded_text(state.requirement),
            "revision": state.revision,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "workflow": state.workflow_id,
            "workflow_version": state.workflow_version,
            "status": state.status,
            "current_node": state.current_node,
            "terminal": terminal,
            "repository_set_id": state.repository_set_id,
            "repository_ids": _repository_ids(state),
            "repository_count": len(state.repositories),
            "contract": contract,
        },
        "health": "terminal" if terminal else "not-evaluated",
        "why_next": why_next,
        "timeline": {
            "records": [
                _timeline_record(record, offset + index + 1)
                for index, record in enumerate(records)
            ],
            "page": {
                "offset": offset,
                "limit": limit,
                "returned": len(records),
                "total": len(state.records),
                "next_offset": next_offset,
            },
        },
        "artifacts": _artifact_summaries(state),
        "dossier": dossier,
        "recovery": _recovery_brief(
            state,
            terminal=terminal,
            contract=contract,
            why_next=why_next,
            dossier=dossier,
        ),
    }
    return envelope("task-detail", observed_at, result)


def _snapshot_projection(projection: Mapping[str, object]) -> object:
    repository_set = projection.get("repository_set")
    if not isinstance(repository_set, Mapping):
        return None
    repositories = []
    for item in repository_set.get("repositories", ())[:8]:
        if not isinstance(item, Mapping):
            continue
        snapshot = item.get("snapshot")
        repositories.append(
            {
                "repository_id": _bounded_text(item.get("id"), 128),
                "snapshot": {
                    key: snapshot.get(key)
                    for key in (
                        "digest",
                        "head",
                        "branch",
                        "clean",
                        "has_unmerged_entries",
                        "index_entry_count",
                    )
                    if isinstance(snapshot, Mapping)
                    and isinstance(snapshot.get(key), (str, int, bool))
                },
            }
        )
    return {
        "repository_set_id": _bounded_text(repository_set.get("id"), 128),
        "digest": _bounded_text(repository_set.get("digest"), 128),
        "repositories": repositories,
    }


def _freshness_projection(projection: Mapping[str, object]) -> object:
    freshness = projection.get("freshness")
    if not isinstance(freshness, Mapping):
        return None
    counts = {"current": 0, "stale": 0, "unknown": 0}
    entries = []
    for record_id in sorted(str(key) for key in freshness)[:MAX_PAGE_LIMIT]:
        item = freshness.get(record_id)
        if not isinstance(item, Mapping):
            counts["unknown"] += 1
            continue
        current = item.get("current")
        counts["current" if current is True else "stale" if current is False else "unknown"] += 1
        reasons = item.get("reasons")
        entries.append(
            {
                "record_id": _bounded_text(record_id, 128),
                "current": current if isinstance(current, bool) else None,
                "reasons": [
                    _bounded_text(reason, 128)
                    for reason in reasons[:8]
                    if isinstance(reason, str)
                ]
                if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes))
                else [],
            }
        )
    return {"counts": counts, "entries": entries}


def _review_projection(projection: Mapping[str, object]) -> object:
    review = projection.get("review")
    if not isinstance(review, Mapping):
        return None
    findings = review.get("findings")
    return {
        key: _bounded_text(review.get(key), 128)
        if isinstance(review.get(key), str)
        else review.get(key)
        for key in (
            "claimed_outcome",
            "outcome",
            "status",
            "current",
            "reviewer_available",
            "review_scope_digest",
            "workspace_digest",
        )
        if isinstance(review.get(key), (str, bool))
    } | {
        "finding_count": len(findings)
        if isinstance(findings, Sequence) and not isinstance(findings, (str, bytes))
        else 0
    }


def _relative_path(value: object) -> Optional[str]:
    text = _bounded_text(value)
    if text is None or text.startswith(("/", "\\")):
        return None
    if len(text) >= 3 and text[1] == ":" and text[2] in ("/", "\\"):
        return None
    return text


def _blocker_evidence(details: object) -> object:
    if not isinstance(details, Mapping):
        return None
    drift = details.get("ambient_drift")
    if not isinstance(drift, Mapping):
        return None
    paths = drift.get("paths")
    safe_paths = []
    if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes)):
        for item in paths[:8]:
            if not isinstance(item, Mapping):
                continue
            safe_paths.append(
                {
                    "repository_id": _bounded_text(item.get("repository_id"), 128),
                    "path": _relative_path(item.get("path")),
                    "change_kind": _bounded_text(item.get("change_kind"), 128),
                }
            )
    member_planes = drift.get("member_planes")
    safe_member_planes = []
    allowed_planes = {
        "head",
        "branch",
        "status_sha256",
        "git_worktree_dir",
        "git_common_dir",
        "object_format",
    }
    if isinstance(member_planes, Sequence) and not isinstance(
        member_planes, (str, bytes)
    ):
        for item in member_planes[:8]:
            if not isinstance(item, Mapping):
                continue
            planes = item.get("planes")
            safe_member_planes.append(
                {
                    "repository_id": _bounded_text(item.get("repository_id"), 128),
                    "planes": [
                        plane
                        for plane in planes[:8]
                        if isinstance(plane, str) and plane in allowed_planes
                    ]
                    if isinstance(planes, Sequence)
                    and not isinstance(planes, (str, bytes))
                    else [],
                }
            )
    return {
        "ambient_drift": {
            "present": drift.get("present")
            if isinstance(drift.get("present"), bool)
            else None,
            "path_count": len(paths)
            if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes))
            else 0,
            "paths": safe_paths,
            "member_plane_count": len(member_planes)
            if isinstance(member_planes, Sequence)
            and not isinstance(member_planes, (str, bytes))
            else 0,
            "member_planes": safe_member_planes,
        }
    }


def _blocker_projection(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    details = value.get("details")
    recovery = details.get("recovery") if isinstance(details, Mapping) else None
    return {
        "code": _bounded_text(value.get("code"), 128),
        "reason": _bounded_text(value.get("message") or value.get("reason")),
        "evidence": _blocker_evidence(details),
        "recovery_choices": [
            _bounded_text(item, 128)
            for item in recovery[:8]
            if isinstance(item, str)
        ]
        if isinstance(recovery, Sequence) and not isinstance(recovery, (str, bytes))
        else [],
    }


def _retry_projection(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    return {
        key: _bounded_text(item, 128) if isinstance(item, str) else item
        for key, item in value.items()
        if key
        in {
            "obligation_id",
            "kind",
            "attempts_used",
            "max_attempts",
            "remaining",
            "allowance",
            "used",
            "state",
        }
        and isinstance(item, (str, int))
        and not isinstance(item, bool)
    }


def _obligation_projection(value: object) -> object:
    if not isinstance(value, Mapping):
        return None
    result = {
        key: _bounded_text(item, 128) if isinstance(item, str) else item
        for key, item in value.items()
        if key
        in {
            "obligation_id",
            "kind",
            "state",
            "attempts_used",
            "allowance",
            "remaining",
        }
        and isinstance(item, (str, int))
        and not isinstance(item, bool)
    }
    repository_ids = value.get("repository_ids")
    if isinstance(repository_ids, Sequence) and not isinstance(
        repository_ids, (str, bytes)
    ):
        result["repository_ids"] = [
            _bounded_text(item, 128)
            for item in repository_ids[:8]
            if isinstance(item, str)
        ]
    return result


def _assurance_projection(action: Mapping[str, object]) -> object:
    assurance = action.get("assurance")
    if not isinstance(assurance, Mapping):
        return None
    budget = assurance.get("budget")
    safe_budget = None
    if isinstance(budget, Mapping):
        safe_budget = {
            "maximum_remaining_actions": budget.get("maximum_remaining_actions")
            if isinstance(budget.get("maximum_remaining_actions"), int)
            and not isinstance(budget.get("maximum_remaining_actions"), bool)
            else None,
            "remaining": {
                key: value
                for key, value in budget.get("remaining", {}).items()
                if isinstance(key, str)
                and isinstance(value, int)
                and not isinstance(value, bool)
            }
            if isinstance(budget.get("remaining"), Mapping)
            else {},
            "used": {
                key: value
                for key, value in budget.get("used", {}).items()
                if isinstance(key, str)
                and isinstance(value, int)
                and not isinstance(value, bool)
            }
            if isinstance(budget.get("used"), Mapping)
            else {},
        }
    states = assurance.get("obligation_states")
    state_counts = {}
    obligations = []
    if isinstance(states, Sequence) and not isinstance(states, (str, bytes)):
        for item in states[:MAX_PAGE_LIMIT]:
            state = item.get("state") if isinstance(item, Mapping) else None
            if isinstance(state, str):
                state_counts[state] = state_counts.get(state, 0) + 1
            projected = _obligation_projection(item)
            if isinstance(projected, Mapping):
                obligations.append(projected)
    outstanding = [
        item
        for item in obligations
        if item.get("state") in {"required", "blocked", "outstanding"}
    ]
    exhausted = [item for item in obligations if item.get("state") == "exhausted"]
    return {
        "policy": _bounded_text(assurance.get("policy"), 128),
        "profile": _bounded_text(assurance.get("profile"), 128),
        "plan_id": _bounded_text(assurance.get("plan_id"), 128),
        "plan_digest": _bounded_text(assurance.get("plan_digest"), 128),
        "confidence": _bounded_text(assurance.get("confidence"), 128),
        "maximum_remaining_actions": assurance.get("maximum_remaining_actions")
        if isinstance(assurance.get("maximum_remaining_actions"), int)
        and not isinstance(assurance.get("maximum_remaining_actions"), bool)
        else None,
        "obligation_state_counts": state_counts,
        "obligations": obligations,
        "outstanding": outstanding,
        "exhausted": exhausted,
        "budget": safe_budget,
    }


def live_task_view(
    state: TaskState,
    definition: WorkflowDefinition,
    observed_at: str,
    *,
    projection: Optional[Mapping[str, object]] = None,
    snapshot_error_code: Optional[str] = None,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> dict:
    stored = stored_task_view(
        state,
        definition,
        observed_at,
        offset=offset,
        limit=limit,
    )["result"]
    terminal = bool(stored["task"]["terminal"])
    action = projection.get("action") if isinstance(projection, Mapping) else None
    blocked = action.get("blocked") if isinstance(action, Mapping) else None
    if terminal:
        health = "terminal"
    elif snapshot_error_code is not None:
        health = "unavailable"
    elif blocked:
        health = "blocked"
    else:
        health = "ready"
    action_summary = None
    if isinstance(action, Mapping):
        obligation = action.get("current_obligation")
        blocker = _blocker_projection(blocked)
        retry = _retry_projection(action.get("retry_budget"))
        assurance = _assurance_projection(action)
        action_summary = {
            "action_id": _bounded_text(action.get("action_id"), 128),
            "handler": _bounded_text(action.get("handler"), 128),
            "blocked": bool(blocked),
            "blocker": blocker,
            "blocked_details": blocker,
            "retry": retry,
            "assurance": assurance,
            "current_obligation": _obligation_projection(obligation),
        }
    stored["health"] = health
    stored["live"] = {
        "snapshot": "unavailable" if snapshot_error_code else "captured",
        "snapshot_summary": _snapshot_projection(projection)
        if isinstance(projection, Mapping)
        else None,
        "freshness": _freshness_projection(projection)
        if isinstance(projection, Mapping)
        else None,
        "review": _review_projection(projection)
        if isinstance(projection, Mapping)
        else None,
        "error": None
        if snapshot_error_code is None
        else {"code": snapshot_error_code},
        "action": action_summary,
    }
    declared_action = (
        {
            "action_id": action_summary.get("action_id"),
            "handler": action_summary.get("handler"),
        }
        if action_summary is not None
        else None
    )
    blocker = action_summary.get("blocker") if action_summary else None
    if blocker is None and snapshot_error_code is not None and not terminal:
        blocker = {
            "code": _bounded_text(snapshot_error_code, 128),
            "reason": "Repository observation is unavailable",
            "evidence": None,
            "recovery_choices": [],
        }
    assurance = action_summary.get("assurance") if action_summary else None
    retry = action_summary.get("retry") if action_summary else None
    stored["why_next"] = {
        **_state_summary(state, terminal),
        "readiness": health,
        "declared_action": declared_action,
        "action_id": action_summary.get("action_id") if action_summary else None,
        "handler": action_summary.get("handler") if action_summary else None,
        "blocker": blocker,
        "blocked_code": blocker.get("code") if isinstance(blocker, Mapping) else None,
        "retry": retry,
        "assurance": assurance,
        "obligation": action_summary.get("current_obligation") if action_summary else None,
        "summary": "Task is terminal"
        if terminal
        else "Current action is blocked"
        if blocked
        else "Current action is ready"
        if snapshot_error_code is None
        else "Repository observation is unavailable",
    }
    if isinstance(projection, Mapping):
        stored["dossier"] = _bounded_dossier(projection.get("dossier"))
    recovery = stored.get("recovery")
    if isinstance(recovery, dict):
        recovery["why_next"] = dict(stored["why_next"])
        recovery["retry"] = retry
        recovery["assurance"] = assurance
        recovery["outstanding_assurance"] = (
            list(assurance.get("outstanding", ()))
            if isinstance(assurance, Mapping)
            else []
        )
        recovery["exhausted_assurance"] = (
            list(assurance.get("exhausted", ()))
            if isinstance(assurance, Mapping)
            else []
        )
        recovery["freshness"] = stored["live"]["freshness"]
        recovery["review"] = stored["live"]["review"]
        recovery["dossier"] = stored["dossier"]
    return envelope("task-live-detail", observed_at, stored)
