# Loaded by scripts/dev_flow.py after the compact agent protocol and before
# controller commands.  It derives every model-visible workflow projection
# from the task-pinned package bundle; it never owns transition truth.
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence


WORKFLOW_AGENT_PROFILE = "agent-v1"
WORKFLOW_NODE_DESCRIPTION = "dev-flow-node-description/v1"
WORKFLOW_NODE_PLAYBOOK = "dev-flow-node-playbook/v1"
WORKFLOW_PROGRESS_PROJECTION = "dev-flow-workflow-progress/v1"
WORKFLOW_PLAYBOOK_BUDGET = 4096

_workflow_projection_frontier_states = frozenset(
    {
        "READY",
        "RUNNING",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
        "BLOCKED",
    }
)


class WorkflowProjectionError(Exception):
    """Stable failure to derive required metadata from pinned workflow truth."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


def _workflow_projection_public(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _workflow_projection_public(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_workflow_projection_public(item) for item in value]
    return value


def _workflow_projection_resolution(
    state: Mapping[str, object],
) -> tuple[object, Mapping[str, object]]:
    try:
        resolution = resolve_loaded_task_workflow(
            state, purpose="inspection"
        )
        digest = resolution.get("bundle_sha256")
        if not isinstance(digest, str) or not digest:
            raise WorkflowProjectionError(
                "WORKFLOW_PROJECTION_IDENTITY_MISSING",
                "resolved workflow has no exact bundle identity",
            )
        bundle = workflow_runtime_services().catalog.resolve_identity(
            digest
        )
    except WorkflowProjectionError:
        raise
    except Exception as exc:
        code = getattr(exc, "code", "WORKFLOW_PROJECTION_UNAVAILABLE")
        details = getattr(exc, "details", {})
        raise WorkflowProjectionError(
            str(code),
            str(
                getattr(
                    exc,
                    "message",
                    "task-pinned workflow projection is unavailable",
                )
            ),
            details=details if isinstance(details, Mapping) else {},
        ) from exc
    return bundle, resolution


def _workflow_projection_playbook(
    bundle: object,
    node: Mapping[str, object],
) -> dict[str, object]:
    playbook = node.get("playbook")
    if not isinstance(playbook, Mapping):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_MISSING",
            "workflow node does not declare a playbook locator",
            details={"node_id": node.get("id")},
        )
    path = playbook.get("path")
    anchor = playbook.get("anchor")
    if not isinstance(path, str) or not path:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_MISSING",
            "workflow node playbook path is invalid",
            details={"node_id": node.get("id")},
        )
    bundle_sha256 = getattr(bundle, "bundle_sha256", None)
    locator = f"bundle/{bundle_sha256}/{path}"
    if isinstance(anchor, str) and anchor:
        locator += f"#{anchor}"
    return {
        "bundle_sha256": bundle_sha256,
        "path": path,
        "anchor": anchor,
        "locator": locator,
    }


def _workflow_projection_playbook_section(
    source: str,
    anchor: str | None,
) -> str:
    if not anchor:
        return source
    lines = source.splitlines(keepends=True)
    heading = f"## {anchor}"
    start: int | None = None
    end = len(lines)
    for index, line in enumerate(lines):
        normalized = line.rstrip("\r\n")
        if start is None:
            if normalized == heading:
                start = index
            continue
        if normalized.startswith("## "):
            end = index
            break
    if start is None:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_ANCHOR_MISSING",
            "workflow playbook does not contain its declared node anchor",
            details={"anchor": anchor},
        )
    return "".join(lines[start:end]).rstrip() + "\n"


def workflow_node_playbook(
    state: Mapping[str, object],
    node_id: str | None = None,
    *,
    locator: str | None = None,
) -> dict[str, object]:
    """Return the exact bounded playbook section pinned by one task bundle."""

    bundle, resolution = _workflow_projection_resolution(state)
    selected = state.get("status") if node_id is None else node_id
    if not isinstance(selected, str) or not selected:
        raise WorkflowProjectionError(
            "WORKFLOW_NODE_UNKNOWN", "node identity is required"
        )
    node = bundle.node(selected)
    declared = _workflow_projection_playbook(bundle, node)
    if locator is not None and locator != declared["locator"]:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_LOCATOR_MISMATCH",
            "requested playbook locator is not the task-pinned node locator",
            details={
                "expected": declared["locator"],
                "actual": locator,
            },
        )
    resources = getattr(bundle, "resources", None)
    if not isinstance(resources, Mapping):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_UNAVAILABLE",
            "resolved workflow bundle has no sealed resource inventory",
        )
    resource = resources.get(str(declared["path"]))
    if (
        not isinstance(resource, tuple)
        or len(resource) != 2
        or resource[0] != "T"
        or not isinstance(resource[1], bytes)
    ):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_UNAVAILABLE",
            "declared workflow playbook is absent from sealed text resources",
            details={"path": declared["path"]},
        )
    try:
        source = resource[1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_INVALID",
            "sealed workflow playbook is not valid UTF-8",
            details={"path": declared["path"]},
        ) from exc
    content = _workflow_projection_playbook_section(
        source,
        (
            str(declared["anchor"])
            if isinstance(declared.get("anchor"), str)
            else None
        ),
    )
    encoded = content.encode("utf-8")
    if len(encoded) > WORKFLOW_PLAYBOOK_BUDGET:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_PLAYBOOK_BUDGET_EXCEEDED",
            "node playbook section exceeds its UTF-8 byte budget",
            details={
                "size": len(encoded),
                "budget": WORKFLOW_PLAYBOOK_BUDGET,
                "locator": declared["locator"],
            },
        )
    return {
        "contract": WORKFLOW_NODE_PLAYBOOK,
        "workflow": {
            key: resolution[key]
            for key in (
                "id",
                "version",
                "schema",
                "graph_sha256",
                "bundle_sha256",
                "adapter",
            )
            if key in resolution
        },
        "node_id": selected,
        "locator": declared["locator"],
        "path": declared["path"],
        "anchor": declared["anchor"],
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "size": len(encoded),
        "content": content,
    }


def _workflow_projection_edge_action(
    bundle: object,
    edge: Mapping[str, object],
    node: Mapping[str, object],
    *,
    compact: bool = False,
) -> dict[str, object]:
    trigger = edge.get("trigger")
    if not isinstance(trigger, Mapping):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_EDGE_INVALID",
            "workflow edge has no typed trigger",
            details={"edge_id": edge.get("id")},
        )
    action_id = trigger.get("id")
    if not isinstance(action_id, str) or not action_id:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_EDGE_INVALID",
            "workflow edge trigger has no stable action identity",
            details={"edge_id": edge.get("id")},
        )
    result: dict[str, object] = {
        "action_id": action_id,
        "edge_id": edge.get("id"),
        "target": edge.get("target"),
        "confirmation": edge.get("confirmation"),
    }
    same_node = edge.get("source") == edge.get("target")
    if same_node:
        result["same_node"] = True
    public_command = edge.get("public_command")
    if isinstance(public_command, Mapping):
        result["command"] = (
            public_command.get("id")
            if compact
            else _workflow_projection_public(public_command)
        )
        values = public_command.get("values")
        if compact and isinstance(values, (list, tuple)) and values:
            result["selectors"] = list(values)
    if not compact:
        result.update(
            {
                "class": edge.get("class"),
                "automatic": edge.get("automatic"),
                "requires_note": edge.get("requires_note"),
                "required_sections": list(
                    node.get("required_sections", ())
                    if isinstance(
                        node.get("required_sections"), (list, tuple)
                    )
                    else ()
                ),
                "playbook": _workflow_projection_playbook(bundle, node)[
                    "locator"
                ],
            }
        )
        for field in (
            "allowed_artifact_kinds",
            "canonical_event",
            "effect_classification",
            "effects",
            "kernel_effects",
            "kernel_invalidates",
            "kernel_state_writes",
            "required_suites",
            "resume_policy",
            "side_effects",
            "tool_policy",
        ):
            if field in edge:
                result[field] = _workflow_projection_public(edge[field])
    elif edge.get("requires_note") is True:
        result["requires_note"] = True
    if compact and edge.get("automatic") is True:
        result["automatic"] = True
    gate = edge.get("gate")
    if isinstance(gate, Mapping):
        result["gate"] = (
            gate.get("id")
            if compact
            else _workflow_projection_public(gate)
        )
    return result


def workflow_progress_projection(
    state: Mapping[str, object],
) -> dict[str, object]:
    """Return graph-derived labels, order, progress, and pending gates."""

    bundle, resolution = _workflow_projection_resolution(state)
    status = state.get("status")
    if not isinstance(status, str):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_STATE_INVALID",
            "task status is required for workflow projection",
        )
    node = bundle.node(status)
    graph = getattr(bundle, "graph", None)
    if not isinstance(graph, Mapping):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_GRAPH_INVALID",
            "resolved bundle has no validated graph",
        )
    ordered = graph.get("ordered_nodes")
    if not isinstance(ordered, (list, tuple)) or status not in ordered:
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_ORDER_MISSING",
            "current node is absent from the pinned workflow order",
            details={"node_id": status},
        )
    position = tuple(ordered).index(status)
    pending_gates = []
    for edge in bundle.legal_edges(status):
        gate = edge.get("gate")
        if isinstance(gate, Mapping):
            pending_gates.append(_workflow_projection_public(gate))
    labels = node.get("labels")
    if not isinstance(labels, Mapping):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_LABEL_MISSING",
            "current workflow node has no localized labels",
            details={"node_id": status},
        )
    result = {
        "contract": WORKFLOW_PROGRESS_PROJECTION,
        "workflow": {
            key: resolution[key]
            for key in (
                "id",
                "version",
                "schema",
                "graph_sha256",
                "bundle_sha256",
            )
            if key in resolution
        },
        "node_id": status,
        "labels": _workflow_projection_public(labels),
        "phase": node.get("phase"),
        "position": position,
        "completed_nodes": position,
        "total_nodes": len(ordered),
        "terminal": bool(node.get("terminal")),
        "waiting": bool(node.get("waiting")),
        "pending_gates": pending_gates,
        "index_role": node.get("index_role"),
        "required_sections": list(node.get("required_sections", ())),
        "playbook": _workflow_projection_playbook(bundle, node),
    }
    return result


def workflow_node_description(
    state: Mapping[str, object],
    node_id: str | None = None,
) -> dict[str, object]:
    """Describe one node entirely from its pinned validated definition."""

    bundle, resolution = _workflow_projection_resolution(state)
    selected = state.get("status") if node_id is None else node_id
    if not isinstance(selected, str) or not selected:
        raise WorkflowProjectionError(
            "WORKFLOW_NODE_UNKNOWN", "node identity is required"
        )
    node = bundle.node(selected)
    legal_edges = [
        _workflow_projection_edge_action(bundle, edge, node)
        for edge in bundle.legal_edges(selected)
    ]
    result = {
        "contract": WORKFLOW_NODE_DESCRIPTION,
        "workflow": {
            key: resolution[key]
            for key in (
                "id",
                "version",
                "schema",
                "graph_sha256",
                "bundle_sha256",
            )
            if key in resolution
        },
        "node": _workflow_projection_public(node),
        "legal_actions": legal_edges,
        "playbook": _workflow_projection_playbook(bundle, node),
    }
    return result


def _workflow_projection_frontier(
    state: Mapping[str, object],
    bundle: object,
) -> list[dict[str, object]]:
    node_instances = state.get("node_instances")
    frontier: list[dict[str, object]] = []
    if isinstance(node_instances, (list, tuple)):
        for item in node_instances:
            if not isinstance(item, Mapping):
                continue
            lifecycle = item.get("state")
            if lifecycle not in _workflow_projection_frontier_states:
                continue
            node_id = item.get("node_id")
            if not isinstance(node_id, str):
                continue
            node = bundle.node(node_id)
            labels = node.get("labels")
            frontier.append(
                {
                    key: value
                    for key, value in {
                        "node_instance_id": item.get("node_instance_id"),
                        "repository_id": item.get("repository_id"),
                        "node_id": node_id,
                        "state": lifecycle,
                        "label": (
                            labels.get("zh-CN")
                            if isinstance(labels, Mapping)
                            else None
                        ),
                    }.items()
                    if value is not None
                }
            )
    if frontier:
        return frontier
    node_id = state.get("status")
    if not isinstance(node_id, str):
        return []
    node = bundle.node(node_id)
    labels = node.get("labels")
    return [
        {
            "node_id": node_id,
            "state": (
                "BLOCKED"
                if node_id == "BLOCKED"
                else "SUCCEEDED"
                if bool(node.get("terminal"))
                else "READY"
            ),
            "label": (
                labels.get("zh-CN")
                if isinstance(labels, Mapping)
                else node_id
            ),
        }
    ]


def _workflow_projection_artifact_writer(
    data_dir: str | Path | None,
) -> Any:
    def write(task_id: str, kind: str, content: bytes) -> Mapping[str, object]:
        digest = hashlib.sha256(content).hexdigest()
        task_dir = _task_dir(task_id, data_dir)
        artifact_dir = task_dir / "artifacts" / "protocol"
        _ensure_private_dir(artifact_dir)
        destination = artifact_dir / f"{digest}.json"
        if destination.exists():
            observed = destination.read_bytes()
            if observed != content:
                raise WorkflowProjectionError(
                    "PROTOCOL_ARTIFACT_CONFLICT",
                    "content-addressed protocol artifact conflicts",
                    details={"sha256": digest},
                )
        else:
            _atomic_write_bytes(destination, content)
        relative = destination.relative_to(task_dir).as_posix()
        return {
            "schema": ARTIFACT_REFERENCE_SCHEMA,
            "artifact_id": f"protocol-{digest}",
            "task_id": task_id,
            "semantic_sha256": digest,
            "sha256": digest,
            "size": len(content),
            "media_type": "application/json",
            "kind": kind,
            "locator": relative,
        }

    return write


def build_workflow_task_next(
    state: Mapping[str, object],
    *,
    data_dir: str | Path | None = None,
    revision_delta: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the bounded `agent-v1` frontier from one pinned bundle."""

    bundle, resolution = _workflow_projection_resolution(state)
    status = state.get("status")
    if not isinstance(status, str):
        raise WorkflowProjectionError(
            "WORKFLOW_PROJECTION_STATE_INVALID",
            "task status is required for agent projection",
        )
    node = bundle.node(status)
    actions = [
        _workflow_projection_edge_action(
            bundle, edge, node, compact=True
        )
        for edge in bundle.legal_edges(status)
    ]
    condition: dict[str, object] = {
        "kind": (
            "terminal"
            if bool(node.get("terminal"))
            else "blocked"
            if status == "BLOCKED"
            else "waiting"
            if bool(node.get("waiting"))
            else "ready"
        ),
        "node_id": status,
        "required_sections": list(
            node.get("required_sections", ())
        ),
    }
    locator = _workflow_projection_playbook(bundle, node)
    workflow_ref = {
        key: resolution[key]
        for key in (
            "id",
            "version",
            "schema",
            "graph_sha256",
            "bundle_sha256",
        )
        if key in resolution
    }
    return build_task_next(
        state,
        workflow_ref=workflow_ref,
        frontier=_workflow_projection_frontier(state, bundle),
        actions=actions,
        condition=condition,
        locator=locator,
        revision_delta=revision_delta,
        artifact_writer=_workflow_projection_artifact_writer(data_dir),
    )


def resolve_workflow_protocol_artifact(
    task_id: str,
    locator: str,
    *,
    data_dir: str | Path | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Resolve and verify a task-scoped compact-protocol artifact."""

    if (
        not isinstance(locator, str)
        or not locator.startswith("artifacts/protocol/")
        or not locator.endswith(".json")
        or "\\" in locator
        or ".." in locator.split("/")
    ):
        raise WorkflowProjectionError(
            "PROTOCOL_ARTIFACT_LOCATOR_INVALID",
            "protocol artifact locator is not task scoped",
        )
    task_dir = _task_dir(task_id, data_dir).resolve()
    path = (task_dir / locator).resolve()
    try:
        path.relative_to(task_dir)
    except ValueError as exc:
        raise WorkflowProjectionError(
            "PROTOCOL_ARTIFACT_PATH_ESCAPE",
            "protocol artifact resolves outside the task",
        ) from exc
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise WorkflowProjectionError(
            "PROTOCOL_ARTIFACT_UNAVAILABLE",
            "protocol artifact cannot be read",
            details={"locator": locator},
        ) from exc
    digest = hashlib.sha256(content).hexdigest()
    expected_name = f"{digest}.json"
    if path.name != expected_name:
        raise WorkflowProjectionError(
            "PROTOCOL_ARTIFACT_INTEGRITY_MISMATCH",
            "protocol artifact digest does not match its locator",
            details={"sha256": digest},
        )
    return content, {
        "schema": ARTIFACT_REFERENCE_SCHEMA,
        "artifact_id": f"protocol-{digest}",
        "task_id": task_id,
        "semantic_sha256": digest,
        "sha256": digest,
        "size": len(content),
        "media_type": "application/json",
        "kind": "protocol-overflow",
        "locator": locator,
    }
