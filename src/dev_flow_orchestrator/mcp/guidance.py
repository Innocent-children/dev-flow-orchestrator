"""Bounded, action-specific model guidance derived from live projections."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from ..model import DevFlowError
from ..review_guidance import (
    INDEPENDENT_REVIEW_GUIDANCE,
    INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
)
from .identity import MCP_GUIDANCE_MAX_BYTES, MCP_GUIDANCE_SCHEMA


# A host that surfaces exactly 512 leading bytes receives one complete authority
# paragraph.  Padding prevents the following operational note being cut mid-sentence.
_AUTHORITY_INSTRUCTIONS = (
    "Controller is the only Dev Flow task-state writer. Before starting/resuming, call "
    "dev_flow_find_tasks_for_path: select one task, or call dev_flow_start_task only if none "
    "matches. Call dev_flow_get_next_action to obtain exactly one action; perform only it "
    "across the immutable repository set. Call dev_flow_apply_action with its exact current "
    "binding and closed payload. Never guess or reuse stale, ambiguous, unavailable, or "
    "terminal authority; refresh or stop. Direct task-state file access is unsupported."
)
SERVER_INSTRUCTIONS = (
    _AUTHORITY_INSTRUCTIONS
    + " " * (512 - len(_AUTHORITY_INSTRUCTIONS.encode("ascii")))
    + "Do not blindly retry a mutation after a lost response; read the task and current action "
    "before deciding whether it committed. Normal execution does not require reading "
    "skills/, hooks/, CLI source, MCP adapter source, launcher source, or Controller "
    "state. Reading repository source needed for the user's implementation, "
    "verification, or review remains allowed."
)


_BASE_GUIDANCE = {
    "schema": MCP_GUIDANCE_SCHEMA,
    "objective": "Complete only the authoritative current action.",
    "must_read": [
        "task, contract, and the complete repository_set",
        "action.payload_schema, action.binding, and action.context",
        "inputs, resources, and any projected driver or current obligation",
    ],
    "allowed_effects": "read-only",
    "required_evidence": [
        "Return only evidence required by action.payload_schema and its current provenance contracts."
    ],
    "payload_notes": [
        "Use the closed projected payload shape; do not infer, omit, rename, or add fields.",
        "Submit the exact unmodified binding with the current action ID.",
        "Do not read or edit Controller task-state files or package source to discover workflow semantics.",
    ],
    "driver": None,
    "stale_recovery": (
        "Treat guidance and binding as one authority snapshot. If task revision, "
        "inputs, resources, repository evidence, or action changes, call "
        "dev_flow_get_next_action and reuse neither value."
    ),
    "completion_rule": (
        "Progress is confirmed only when the Controller accepts the exact current "
        "mutation and returns a fresh next action or terminal authority."
    ),
}


GUIDANCE_CATALOG = {
    "actions": {
        "preflight": {
            "objective": "Perform only the bounded read-only preflight for the exact repository set.",
            "must_read": [
                "repository_set identity and every member's current Git evidence",
                "action.binding and action.context.blocked",
            ],
            "allowed_effects": "read-only",
            "required_evidence": [
                "No caller-authored evidence is required; the Controller captures and seals the repository baseline."
            ],
            "payload_notes": ["Submit exactly an empty payload object."],
        },
        "impact": {
            "objective": "Record current requirement-relevant impact, uncertainty, risks, and assurance inputs.",
        "must_read": ["the governing repository baseline in inputs and resources"],
        "required_evidence": [
            "Keep current and baseline codebase-memory projects separate; confirm each graph generation and conclusion against source.",
                "Keep missing, stale, partial, degraded, unavailable, unconfirmed, or inconsistent impact evidence unknown."
            ],
        },
        "planning": {
            "objective": "Produce the current repository-backed plan and bind every governing or reported resource.",
            "must_read": [
                "the source predecessor, impact input, repository-scoped resources, and semantic OpenSpec tasks normalizer"
            ],
            "required_evidence": [
                "Record current machine-readable plan status, concrete paths, digests, source stage, validation state, and driver provenance."
            ],
        },
        "implementation": {
            "objective": "Implement only the accepted requirement and current plan across the exact repository set.",
        },
        "investigation": {
            "objective": "Establish the bounded reproducible cause and evidence-backed conclusion without changing source.",
            "required_evidence": ["Separate observed facts, source-confirmed inferences, and remaining uncertainty."],
        },
        "documentation": {
            "objective": "Synchronize only the product documentation required by the implemented behavior and contract.",
            "required_evidence": ["Preserve repository-declared paired-language and governing-resource rules."],
        },
        "rework": {
            "objective": "Resolve only the currently bound assurance, review, or investigation gap.",
            "must_read": ["action.rework, action.review_state, causal inputs, and the fresh task-change slice"],
            "required_evidence": ["Preserve finding causality; do not hide, waive, or reclassify a gap without authority."],
        },
        "assurance": {
            "objective": "Execute exactly the one projected current assurance obligation.",
            "must_read": [
                "action.current_obligation and fingerprint",
                "action.task_change_slice, prerequisites, evidence contract, repository and integration scope",
                "action.assurance obligation states, reuse decisions, not-required reasons, and budgets",
                "action.retry_budget and action.verification_coverage when present",
            ],
            "allowed_effects": "source-verifying",
            "required_evidence": [
                "Run only the smallest command or manual check required by the current obligation.",
                "Record the actual result once; do not run an undeclared retry or submit an aggregate verdict."
            ],
            "payload_notes": [
                "Evidence reuse is allowed only when the Controller projects current reuse for the unchanged governing fingerprint and disjoint task-change slice.",
                "Intersecting or ambiguous source, resource, impact-closure, or prerequisite changes require fresh projected evidence; not-required remains a Controller decision."
            ],
        },
        "finalize": {
            "objective": "Finalize only the projected outcome and let the Controller produce the authoritative Delivery Dossier.",
            "must_read": ["all governing inputs, freshness, review state, remaining risks, and projected finalization outcome"],
            "allowed_effects": "source-verifying",
            "required_evidence": ["Report truthful remaining risks and handoff without claiming unconfirmed completion."],
        },
        "cancel": {
            "objective": "Request cancellation only through currently projected workflow authority.",
            "payload_notes": ["Provide the exact non-empty reason; cancellation is terminal only after Controller confirmation."],
        },
        "generic": {},
    },
    "workspace_roles": {
        "context": {
            "allowed_effects": "read-only",
            "payload_notes": ["Do not mutate repository source while producing context evidence."],
        },
        "produces-source": {
            "allowed_effects": "source-producing",
            "must_read": [
                "action.binding.starting_snapshot_digest, the complete current repository_set, source predecessor, and governing inputs"
            ],
            "required_evidence": [
                "Compare the bound starting snapshot with fresh complete repository-set evidence.",
                "Return dev-flow-task-change-claims/0.4.0 for every and only task-owned observed changed path, including repository_id, relative path, classification, criterion_ids, and purpose."
            ],
            "payload_notes": [
                "Do not silently adopt ambient drift, omit a changed member, claim unowned drift, change repository membership, or edit Controller state.",
                "If action.context.blocked or the binding is null, do not change source or submit the action; follow only projected recovery."
            ],
            "stale_recovery": (
                "Keep the exact issued binding while performing the task-owned source edits authorized by this action. "
                "If dev_flow_apply_action rejects a pre-commit payload with NODE_OUTPUT_INVALID, correct the payload and resubmit the same binding when task revision, action, contract, inputs, and repository membership are unchanged. "
                "Do not refresh solely because those authorized edits changed repository evidence; refresh when task authority changes, and never claim unrelated ambient drift."
            ),
        },
        "verifies-source": {
            "allowed_effects": "source-verifying",
            "required_evidence": ["Capture fresh complete repository-set evidence after the check."],
            "payload_notes": ["Do not mutate source; any member snapshot change invalidates the current binding and evidence."],
        },
        "none": {},
    },
    "obligations": {
        "repository-check": {
            "objective": "Execute only the projected member-local repository check.",
            "required_evidence": ["Run the smallest required command in only the projected repository scope."],
        },
        "integration-check": {
            "objective": "Execute only the projected integration evidence contract across its declared members and edges.",
        },
        "documentation-check": {
            "objective": "Check only the projected documentation obligation against its current governing slice.",
        },
        "manual-evidence": {
            "objective": "Perform only the projected bounded manual check and record source-confirmed observations.",
        },
        "generic": {},
    },
    "terminal": {
        "schema": MCP_GUIDANCE_SCHEMA,
        "objective": "Inspect the Controller-confirmed terminal authority and Delivery Dossier; perform no action.",
        "must_read": ["task status, repository_set, terminal.done, and terminal.dossier"],
        "allowed_effects": "read-only",
        "required_evidence": ["No action evidence is accepted after terminal authority."],
        "payload_notes": ["There is no executable action or binding; do not fabricate, replay, or infer one."],
        "driver": None,
        "stale_recovery": "Re-read the stored task if a fresh terminal summary is needed; do not request or guess another action.",
        "completion_rule": "DONE, INCOMPLETE, or CANCELLED and its Dossier are authoritative only when returned by the Controller.",
    },
    "independent_review": INDEPENDENT_REVIEW_GUIDANCE,
}


_GUIDANCE_KEYS = {
    "schema",
    "objective",
    "must_read",
    "allowed_effects",
    "required_evidence",
    "payload_notes",
    "driver",
    "stale_recovery",
    "completion_rule",
}


def _copy(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _extend_unique(target: dict, key: str, values: object) -> None:
    if not isinstance(values, list):
        return
    current = target.setdefault(key, [])
    for item in values:
        if item not in current:
            current.append(item)


def _merge(target: dict, fragment: Mapping[str, object]) -> None:
    for key, value in fragment.items():
        if key in {"must_read", "required_evidence", "payload_notes"}:
            _extend_unique(target, key, _copy(value))
        else:
            target[key] = _copy(value)


def _action_entry(action: Mapping[str, object]) -> str:
    action_id = action.get("action_id") or action.get("id")
    handler = action.get("handler") or action.get("kind")
    node_id = action.get("node_id")
    if handler == "preflight" or action_id == "task.preflight":
        return "preflight"
    if handler in {"assurance.dispatch", "verification.record"}:
        return "assurance"
    if handler == "delivery.finalize" or (
        isinstance(action_id, str) and action_id.startswith("delivery.finalize.")
    ):
        return "finalize"
    if action_id == "impact.record" or node_id == "impact":
        return "impact"
    if action_id == "plan.record" or node_id == "planning":
        return "planning"
    if action_id == "implementation.record" or node_id == "implement":
        return "implementation"
    if action_id == "investigation.record" or node_id == "investigate":
        return "investigation"
    if action_id == "documentation.record" or node_id == "documentation":
        return "documentation"
    if any("rework" in value for value in (action_id, node_id) if isinstance(value, str)):
        return "rework"
    if action_id == "task.cancel" or node_id == "cancel":
        return "cancel"
    return "generic"


def _workspace_role(action: Mapping[str, object]) -> str:
    artifact = action.get("artifact")
    if not isinstance(artifact, Mapping):
        return "none"
    role = artifact.get("workspace")
    return (
        role
        if isinstance(role, str) and role in GUIDANCE_CATALOG["workspace_roles"]
        else "none"
    )


def _payload_fields(payload: object) -> set:
    if not isinstance(payload, Mapping):
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action payload contract is invalid")
    properties = payload.get("properties")
    fields = set(properties) if payload.get("type") == "object" and isinstance(properties, Mapping) else set(payload)
    if not all(isinstance(item, str) and item for item in fields):
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action payload fields are invalid")
    return fields


def _payload_notes(payload: object) -> list:
    fields = _payload_fields(payload)
    if not fields:
        return ["The projected payload is exactly an empty object."]
    notes = ["Projected payload fields are exactly: {}.".format(", ".join(sorted(fields)))]
    if "driver_result" in fields:
        notes.append(
            "driver_result must use dev-flow-driver-result/0.4.0 and truthfully report available, degraded, or unavailable provenance."
        )
    if "resources" in fields:
        notes.append(
            "resources must be exactly {items: [{repository_id, path, role, normalizer}]}; use a projected repository_id, a relative path, role governing or reported, and normalizer none or openspec-tasks/0.4.0."
        )
    if "assurance_result" in fields:
        notes.append("assurance_result must name only action.current_obligation.obligation_id.")
    if "remaining_risks" in fields:
        notes.append("remaining_risks must remain truthful and bounded; an incomplete route is not success.")
    if "reason" in fields:
        notes.append("reason must be non-empty and must not imply authority the Controller has not returned.")
    return notes


def _driver_guidance(action: Mapping[str, object], entry: str) -> object:
    declared = action.get("driver")
    obligation = action.get("current_obligation")
    obligation_driver = obligation.get("driver") if isinstance(obligation, Mapping) else None
    if isinstance(declared, Mapping):
        tool = declared.get("tool")
        if not isinstance(tool, str) or not tool:
            raise DevFlowError("MCP_PROJECTION_INVALID", "current optional driver is invalid")
        base = {
            "tool": tool,
            "phase": entry,
            "required_output": declared.get("produces"),
            "fallback": declared.get("fallback"),
            "status_values": ["available", "degraded", "unavailable"],
            "truth_rule": "fallback evidence is never the named driver's result",
        }
        if tool == "codebase-memory":
            base["source_confirmation"] = (
                "match each current graph generation to its member workspace and confirm findings in source; stale or unmatched graphs require degraded status and conservative impact"
            )
        elif tool == "openspec":
            base["source_confirmation"] = (
                "obtain current machine-readable status and instructions, concrete paths, governing bindings, digests, source stage, and validation state"
            )
        else:
            base["source_confirmation"] = "confirm named-tool output against the exact current projection and repository source"
        return base
    if obligation_driver == "local-command":
        return {
            "tool": "local-command",
            "phase": "current obligation only",
            "required_output": "the obligation's exact command evidence and provenance",
            "fallback": "record the actual unavailable or incomplete result once",
            "truth_rule": "no undeclared retry or substituted aggregate result",
        }
    if obligation_driver in {"manual-or-local-command", "manual-evidence"}:
        return {
            "tool": obligation_driver,
            "phase": "current obligation only",
            "required_output": "the smallest projected manual or command evidence",
            "fallback": "record truthful limitations or unavailability once",
            "truth_rule": "do not convert missing evidence into a pass",
        }
    if isinstance(obligation_driver, str):
        return {
            "tool": obligation_driver,
            "phase": "current obligation only",
            "required_output": "the current obligation's projected evidence contract",
            "fallback": "record truthful unavailability and limitations once",
            "truth_rule": "do not fabricate named-driver evidence",
        }
    return None


def _seal(guidance: Mapping[str, object]) -> dict:
    if set(guidance) != _GUIDANCE_KEYS:
        raise DevFlowError("MCP_PROJECTION_INVALID", "generated current-action guidance fields are invalid")
    body = dict(guidance)
    digest = hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    result = {**body, "guidance_digest": digest}
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MCP_GUIDANCE_MAX_BYTES:
        raise DevFlowError(
            "MCP_RESULT_LIMIT",
            "exact current-action guidance exceeds the bounded MCP result limit",
            details={
                "limit_bytes": MCP_GUIDANCE_MAX_BYTES,
                "recovery": "Do not execute the action from partial guidance; use a compatible bounded interface.",
            },
        )
    return result


def guidance_for_projection(projection: object) -> dict:
    """Return guidance for exactly the live projected action or terminal state."""
    if not isinstance(projection, Mapping):
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action projection is invalid")
    action = projection.get("action")
    if action is None:
        if projection.get("done") is not True:
            raise DevFlowError("MCP_PROJECTION_INVALID", "non-terminal projection has no current action")
        return _seal(_copy(GUIDANCE_CATALOG["terminal"]))
    if not isinstance(action, Mapping):
        raise DevFlowError("MCP_PROJECTION_INVALID", "current action projection is invalid")

    entry = _action_entry(action)
    role = _workspace_role(action)
    obligation = action.get("current_obligation")
    obligation_kind = obligation.get("kind") if isinstance(obligation, Mapping) else None
    if obligation_kind == "independent-review":
        review_contract = action.get("review_contract")
        payload = action.get("payload")
        if (
            entry != "assurance"
            or role != "verifies-source"
            or not isinstance(review_contract, Mapping)
            or review_contract.get("guidance_digest") != INDEPENDENT_REVIEW_GUIDANCE_DIGEST
            or "assurance_result" not in _payload_fields(payload)
        ):
            raise DevFlowError("MCP_PROJECTION_INVALID", "independent-review guidance binding is invalid")
        guidance = _seal(_copy(INDEPENDENT_REVIEW_GUIDANCE))
        if guidance["guidance_digest"] != INDEPENDENT_REVIEW_GUIDANCE_DIGEST:
            raise DevFlowError("MCP_PROJECTION_INVALID", "independent-review guidance authority diverged")
        return guidance

    guidance = _copy(_BASE_GUIDANCE)
    if entry != "preflight":
        _merge(guidance, GUIDANCE_CATALOG["workspace_roles"][role])
    _merge(guidance, GUIDANCE_CATALOG["actions"][entry])
    description = action.get("description")
    if entry == "generic" and isinstance(description, str) and description.strip():
        guidance["objective"] = description.strip()
    if entry == "preflight":
        guidance["allowed_effects"] = "read-only"
    if entry == "assurance":
        obligation_entry = (
            obligation_kind
            if isinstance(obligation_kind, str)
            and obligation_kind in GUIDANCE_CATALOG["obligations"]
            else "generic"
        )
        _merge(guidance, GUIDANCE_CATALOG["obligations"][obligation_entry])
    _extend_unique(guidance, "payload_notes", _payload_notes(action.get("payload")))
    guidance["driver"] = _driver_guidance(action, entry)
    return _seal(guidance)
