# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: side-effect-free schema-v3 gate and reducer bindings.
from __future__ import annotations


def _workflow_v3_gate_outcome_builder(projection, _capabilities):
    """Return only approval material already validated by the kernel."""

    return {
        "gate_id": projection.get("gate_id"),
        "proposed_edge_id": projection.get("proposed_edge_id"),
        "approval": projection.get("approval"),
    }


def _workflow_v3_reduce_invalidate_plan(_projection, _capabilities):
    return {
        "set": {"/review_snapshots": []},
        "remove": ["/approvals/plan", "/approvals/review"],
        "operations": ["increment-planning-generation"],
    }


def _workflow_v3_reduce_invalidate_review(_projection, _capabilities):
    return {
        "set": {"/review_snapshots": []},
        "remove": ["/approvals/review"],
        "operations": [],
    }


def _workflow_v3_reduce_impact_reassess(_projection, _capabilities):
    return {
        "set": {
            "/route": None,
            "/review_snapshots": [],
            "/status": "INDEXED",
        },
        "remove": [
            "/approvals/plan",
            "/approvals/review",
            "/approvals/route",
            "/approvals/workspace",
        ],
        "operations": [
            "increment-impact-generation",
            "retire-current-workspaces",
            "increment-workspace-generation",
        ],
    }


def _workflow_v3_reduce_cancel(projection, _capabilities):
    return {
        "set": {
            "/status": "CANCELLED",
            "/cancelled": projection.get("cancelled"),
        },
        "remove": [],
        "operations": [],
    }
