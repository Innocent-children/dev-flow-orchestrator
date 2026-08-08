"""Lossless current-action projection for the bounded MCP context."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from ..model import DevFlowError
from .identity import MCP_ACTION_SCHEMA, MCP_CURRENT_ACTION_MAX_BYTES


# Backward-compatible public name used by package and focused tests.
MAX_CURRENT_ACTION_BYTES = MCP_CURRENT_ACTION_MAX_BYTES

# Every retained field has an execution consumer.  The manifest is intentionally
# leaf-oriented so a projection refactor cannot hide a dropped authority field
# behind a broad parent entry.
FIELD_USE_MANIFEST = {
    "schema": ("interface-dispatch",),
    "task.task_id": ("selection", "mutation"),
    "task.status": ("terminal-authority", "recovery"),
    "task.revision": ("revision-conflict-recovery",),
    "task.current_node": ("workflow-execution",),
    "task.workflow": ("workflow-execution",),
    "contract": ("payload-construction", "governance", "review"),
    "repository_set.repository_set_id": ("exact-set-execution", "review"),
    "repository_set.workspace_snapshot_digest": ("freshness", "review"),
    "repository_set.repositories[].id": ("exact-set-execution", "evidence-provenance"),
    "repository_set.repositories[].path": ("exact-set-execution",),
    "repository_set.repositories[].snapshot_digest": ("freshness", "review"),
    "repository_set.repositories[].head": ("freshness", "review"),
    "repository_set.repositories[].branch": ("freshness",),
    "repository_set.repositories[].clean": ("freshness",),
    "repository_set.repositories[].status_sha256": ("freshness", "review"),
    "repository_set.repositories[].status_bytes": ("freshness",),
    "repository_set.repositories[].object_format": ("repository-identity",),
    "repository_set.repositories[].index_entry_count": ("freshness",),
    "repository_set.repositories[].index_output_bytes": ("freshness",),
    "repository_set.repositories[].has_unmerged_entries": ("preflight", "freshness"),
    "action.id": ("mutation",),
    "action.kind": ("guidance-selection", "payload-construction"),
    "action.payload_schema": ("payload-construction",),
    "action.binding": ("mutation", "starting-snapshot"),
    "action.retry_budget": ("recovery", "assurance-budget"),
    "action.driver": ("optional-driver",),
    "action.current_obligation": ("assurance",),
    "action.task_change_slice": ("assurance-freshness", "review"),
    "action.assurance": ("assurance-plan", "reuse", "budgets"),
    "action.review_state": ("review", "rework"),
    "action.review_contract": ("review-binding",),
    "action.verification_coverage": ("verification-payload",),
    "action.context.node_id": ("workflow-execution",),
    "action.context.target": ("completion",),
    "action.context.writes": ("controller-effects",),
    "action.context.description": ("objective",),
    "action.context.artifact": ("workspace-role", "input-contract"),
    "action.context.rework": ("recovery", "budgets"),
    "action.context.finalize": ("terminal-outcome",),
    "action.context.blocked": ("safe-recovery", "ambient-drift"),
    "action.context.freshness": ("governing-input-freshness",),
    "inputs": ("payload-construction", "input-artifact-manifest", "review"),
    "resources": ("governing-resource-manifest", "review"),
    "guidance.schema": ("guidance-version",),
    "guidance.objective": ("current-action-outcome",),
    "guidance.must_read": ("context-selection",),
    "guidance.allowed_effects": ("workspace-authority",),
    "guidance.required_evidence": ("payload-construction",),
    "guidance.payload_notes": ("payload-construction",),
    "guidance.driver": ("driver-execution",),
    "guidance.stale_recovery": ("safe-recovery",),
    "guidance.completion_rule": ("controller-progress",),
    "guidance.guidance_digest": ("guidance-freshness", "review-binding"),
    "terminal.done": ("terminal-authority",),
    "terminal.dossier": ("terminal-delivery",),
    "source_projection_digest": ("projection-parity", "diagnostics"),
}


_MEMBER_SNAPSHOT_FIELDS = (
    "digest",
    "head",
    "branch",
    "clean",
    "status_sha256",
    "status_bytes",
    "object_format",
    "index_entry_count",
    "index_output_bytes",
    "has_unmerged_entries",
)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DevFlowError(
            "MCP_PROJECTION_INVALID",
            "current action projection is not canonical JSON",
        ) from exc


def _sequence(value: object, field: str) -> list:
    if not isinstance(value, (list, tuple)):
        raise DevFlowError("MCP_PROJECTION_INVALID", "{} is invalid".format(field))
    return list(value)


def _governing_resources(action: Mapping[str, object], inputs: list) -> list:
    declared = action.get("resources")
    if declared is not None:
        return _sequence(declared, "current action resources")
    return [
        item
        for item in inputs
        if isinstance(item, Mapping) and item.get("edge") == "governing"
    ]


def compact_current_action(
    projection: Mapping[str, object],
    guidance: Mapping[str, object],
) -> dict:
    """Retain all current execution authority and fail atomically on overflow."""
    if not isinstance(projection, Mapping) or not isinstance(guidance, Mapping):
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action projection is invalid")
    workflow = projection.get("workflow")
    task = {
        "task_id": projection.get("task_id"),
        "status": projection.get("status"),
        "revision": projection.get("revision"),
        "current_node": projection.get("current_node"),
        "workflow": workflow.get("id") if isinstance(workflow, Mapping) else workflow,
    }
    action = projection.get("action")
    if action is None:
        if projection.get("done") is not True:
            raise DevFlowError("MCP_PROJECTION_INVALID", "non-terminal projection has no current action")
        compact = {
            "schema": MCP_ACTION_SCHEMA,
            "task": task,
            "contract": projection.get("contract"),
            "repository_set": _repository_set(projection.get("repository_set")),
            "action": None,
            "inputs": [],
            "resources": [],
            "guidance": dict(guidance),
            "terminal": {
                "done": True,
                "dossier": projection.get("dossier"),
            },
            "source_projection_digest": hashlib.sha256(
                _canonical_bytes(projection)
            ).hexdigest(),
        }
    elif isinstance(action, Mapping):
        inputs = _sequence(action.get("inputs"), "current action inputs")
        compact = {
            "schema": MCP_ACTION_SCHEMA,
            "task": task,
            "contract": projection.get("contract"),
            "repository_set": _repository_set(projection.get("repository_set")),
            "action": {
                "id": action.get("action_id"),
                "kind": action.get("handler"),
                "payload_schema": action.get("payload"),
                # Binding is intentionally passed through without normalization,
                # copying, trimming, or key reordering.
                "binding": action.get("binding"),
                "retry_budget": action.get("retry_budget"),
                "driver": action.get("driver"),
                "current_obligation": action.get("current_obligation"),
                "task_change_slice": action.get("task_change_slice"),
                "assurance": action.get("assurance"),
                "review_state": action.get("review_state"),
                "review_contract": action.get("review_contract"),
                "verification_coverage": action.get("verification_coverage"),
                "context": {
                    "node_id": action.get("node_id"),
                    "target": action.get("target"),
                    "writes": action.get("writes"),
                    "description": action.get("description"),
                    "artifact": action.get("artifact"),
                    "rework": action.get("rework"),
                    "finalize": action.get("finalize"),
                    "blocked": action.get("blocked"),
                    "freshness": projection.get("freshness"),
                },
            },
            "inputs": inputs,
            "resources": _governing_resources(action, inputs),
            "guidance": dict(guidance),
            "terminal": None,
            "source_projection_digest": hashlib.sha256(
                _canonical_bytes(projection)
            ).hexdigest(),
        }
    else:
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action projection is invalid")
    encoded = _canonical_bytes(compact)
    if len(encoded) > MAX_CURRENT_ACTION_BYTES:
        raise DevFlowError(
            "MCP_RESULT_LIMIT",
            "exact current action exceeds the bounded MCP response limit",
            details={
                "limit_bytes": MAX_CURRENT_ACTION_BYTES,
                "recovery": (
                    "Do not execute from a truncated projection; use a compatible "
                    "bounded interface that can return the exact action."
                ),
            },
        )
    return compact


def _repository_set(value: object) -> dict:
    if not isinstance(value, Mapping):
        raise DevFlowError("MCP_PROJECTION_INVALID", "repository-set projection is invalid")
    source_repositories = value.get("repositories")
    if not isinstance(source_repositories, (list, tuple)):
        raise DevFlowError("MCP_PROJECTION_INVALID", "repository member projection is invalid")
    repositories = []
    for item in source_repositories:
        if not isinstance(item, Mapping):
            raise DevFlowError("MCP_PROJECTION_INVALID", "repository member projection is invalid")
        snapshot = item.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise DevFlowError("MCP_PROJECTION_INVALID", "repository snapshot projection is invalid")
        repositories.append(
            {
                "id": item.get("id"),
                "path": item.get("path"),
                **{
                    ("snapshot_digest" if key == "digest" else key): snapshot.get(key)
                    for key in _MEMBER_SNAPSHOT_FIELDS
                },
            }
        )
    return {
        "repository_set_id": value.get("id"),
        "repositories": repositories,
        "workspace_snapshot_digest": value.get("digest"),
    }
