"""Stable, adapter-neutral independent-review guidance authority.

The Controller and protocol adapters share this canonical document and digest.
Keeping the authority outside an adapter prevents the persisted workflow core from
depending on MCP implementation modules or third-party protocol packages.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping


def canonical_guidance_bytes(value: Mapping[str, object]) -> bytes:
    """Encode a guidance document using its release-stable digest form."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


INDEPENDENT_REVIEW_GUIDANCE = {
    "schema": "dev-flow-mcp-guidance/1.0.0",
    "objective": (
        "Perform one complete task-wide review of the exact current aggregate "
        "workspace and return structured causal findings for Controller judgment."
    ),
    "must_read": [
        "task.task_id and task.revision",
        "contract and repository_set, including every member current snapshot digest",
        "action.binding and its starting snapshot digest",
        "action.current_obligation, fingerprint, evidence contract, prerequisites, and task_change_slice",
        "action.assurance plan digest, obligation states, reuse decisions, not-required reasons, and budgets",
        "action.review_contract, including contract, plan, manifest, scope, guidance, and workspace digests",
        "inputs and resources as the current input-artifact and governing-resource manifests",
        "action.review_state and every unresolved finding or disposition relevant to the current task",
    ],
    "allowed_effects": "source-verifying",
    "required_evidence": [
        "Use a genuinely separate reviewer context when available and identify its stable reviewer digest.",
        "Review every repository member, the complete task-change slice, and cross-repository behavior against the bound review package, contract, and plan.",
        "Return dev-flow-review-finding/0.4.0 causal findings bound to the projected scope, guidance, reviewer, manifest, contract, plan, and fresh workspace digests.",
        "Return a fresh aggregate workspace digest; source mutation during review invalidates the binding.",
        "If no separate reviewer is available, report unavailable independent assurance or truthful self-review and do not claim independent approval.",
    ],
    "payload_notes": [
        "Submit only the projected current assurance obligation; never submit an aggregate verdict for other obligations.",
        "The review result must report reviewer_available, independent, reviewer_digest, review_scope_digest, guidance_digest, workspace_digest, findings, and claimed_outcome exactly as projected.",
        "Self-review may report truthful findings but independent must be false; the Controller remains verdict authority.",
        "Do not dispose, waive, hide, merge, or reclassify a finding without a separately projected governance action.",
    ],
    "driver": {
        "tool": "independent-review",
        "phase": "current independent-review obligation only",
        "required_output": "bound review result and dev-flow-review-finding/0.4.0 values",
        "source_confirmation": "inspect the exact current repository set and fresh aggregate snapshot",
        "fallback": "report unavailable independent assurance or truthful non-independent self-review",
        "truth_rule": "never describe self-review or unavailable review as independent approval",
    },
    "stale_recovery": (
        "Treat this guidance and the exact binding as one authority snapshot. On any "
        "task, plan, manifest, resource, task-change, review-guidance, or workspace "
        "change, call dev_flow_get_next_action and do not reuse either value."
    ),
    "completion_rule": (
        "Progress exists only after the Controller records the current review result "
        "and returns a fresh next action or terminal authority; only the Controller "
        "derives approval, rework, triage, unavailability, or budget exhaustion."
    ),
}

INDEPENDENT_REVIEW_GUIDANCE_DIGEST = hashlib.sha256(
    canonical_guidance_bytes(INDEPENDENT_REVIEW_GUIDANCE)
).hexdigest()
