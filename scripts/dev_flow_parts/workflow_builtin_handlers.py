# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: side-effect-free built-in guard, reducer, and executor bindings.
from __future__ import annotations

from typing import Mapping, Optional, Sequence


def _workflow_handlers_candidate_delta(
    *,
    set_values: Optional[Mapping[str, object]] = None,
    remove_paths: Sequence[str] = (),
    operations: Sequence[str] = (),
) -> dict[str, object]:
    """Build a side-effect-free candidate delta for the transition kernel."""

    return {
        "set": dict(set_values or {}),
        "remove": list(remove_paths),
        "operations": list(operations),
    }


def _reduce_status(
    projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={"/status": projection.get("target_status")}
    )


def _reduce_block(
    projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={"/blocked": projection.get("blocked")}
    )


def _reduce_resume(
    _projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={"/blocked": None}
    )


def _reduce_cancel(
    projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={
            "/status": "CANCELLED",
            "/cancelled": projection.get("cancelled"),
        }
    )


def _reduce_invalidate_review(
    _projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={"/review_snapshots": []},
        remove_paths=("/approvals/review",),
    )


def _reduce_invalidate_plan(
    _projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={"/review_snapshots": []},
        remove_paths=("/approvals/plan", "/approvals/review"),
    )


def _reduce_impact_reassess(
    _projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    return _workflow_handlers_candidate_delta(
        set_values={
            "/route": None,
            "/review_snapshots": [],
            "/status": "INDEXED",
        },
        remove_paths=(
            "/approvals/plan",
            "/approvals/review",
            "/approvals/route",
            "/approvals/workspace",
        ),
        operations=(
            "increment-impact-generation",
            "retire-current-workspaces",
            "increment-workspace-generation",
        ),
    )


def _reduce_action_outcome(
    projection: Mapping[str, object],
    _capabilities: ReducerCapabilities,
) -> dict[str, object]:
    """Return only a copied candidate delta; the engine bounds writes."""

    candidate = projection.get("candidate_delta")
    if not isinstance(candidate, Mapping):
        return _workflow_handlers_candidate_delta()
    set_values = candidate.get("set")
    remove_paths = candidate.get("remove")
    operations = candidate.get("operations")
    return _workflow_handlers_candidate_delta(
        set_values=set_values if isinstance(set_values, Mapping) else {},
        remove_paths=(
            tuple(remove_paths)
            if isinstance(remove_paths, (list, tuple))
            else ()
        ),
        operations=(
            tuple(operations)
            if isinstance(operations, (list, tuple))
            else ()
        ),
    )


def _guard_note_required(
    projection: Mapping[str, object],
    _capabilities: GuardCapabilities,
) -> bool:
    if projection.get("requires_note") is not True:
        return True
    note = projection.get("note")
    return isinstance(note, str) and bool(note.strip())


def _guard_blocked_resume_target(
    projection: Mapping[str, object],
    _capabilities: GuardCapabilities,
) -> bool:
    """Bind every resume edge to the target recorded by the blocker."""

    blocked = projection.get("blocked")
    target = projection.get("target_status")
    return (
        isinstance(blocked, Mapping)
        and isinstance(target, str)
        and bool(target)
        and blocked.get("from_status") == target
    )


def _workflow_handlers_guard_multi_repository_authority(
    projection: Mapping[str, object],
    _capabilities: GuardCapabilities,
) -> bool:
    """Expose an explicit pinned guard ID for controller-owned authority.

    The authoritative transition service evaluates the corresponding fresh
    orchestration predicate while holding the task/workspace locks.  Registry
    execution is intentionally conservative: a direct runtime invocation must
    carry the package-produced current-authority marker.
    """

    if projection.get("execution_profile") != "multi-repository":
        return True
    return projection.get("multi_repository_authority_current") is True


def _disabled_executor_dispatch(
    _request: Mapping[str, object],
    _capabilities: object,
) -> object:
    """Prevent descriptor-only executors from running before activation."""

    raise RuntimeError(
        "executor registration is descriptor-only until its runtime adapter "
        "and activation evidence are installed"
    )
