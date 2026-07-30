#!/usr/bin/env python3
"""Inject Dev Flow state and provide best-effort Codex tool guardrails."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Optional, Sequence


CONTROLLER = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"
CHECKPOINT_MARKER_SCHEMA = "dev-flow-hook-checkpoint/v1"
CHECKPOINT_MARKER_DIRECTORY = "hook-checkpoints"
WORKER_ASSIGNMENT_CONTEXT_BUDGET = 8192
SERIAL_FALLBACK_CONTEXT_BUDGET = 600


class _PendingCheckpoint(NamedTuple):
    path: Path
    session_sha256: str
    context_sha256: str
    task_id: Optional[str]
    revision: Optional[int]
    frontier_sha256: Optional[str]
    projection_contract: Optional[str]


class _HookOutput(dict[str, Any]):
    """Protocol output with process-local post-flush work attached."""

    pending_checkpoint: Optional[_PendingCheckpoint]

    def __init__(
        self,
        value: Mapping[str, Any],
        pending_checkpoint: Optional[_PendingCheckpoint] = None,
    ) -> None:
        super().__init__(value)
        self.pending_checkpoint = pending_checkpoint


class _WorkerProjection(NamedTuple):
    assignment: Mapping[str, Any]
    dispatch_mode: str


WORKSPACE_STRATEGY_NAMES_ZH = {
    "branch": "新建并切换分支",
    "in-place": "使用当前分支",
    "worktree": "创建独立工作树",
}
DEFAULT_PROTECTED_BRANCHES = {"main", "master", "trunk"}

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_POSIX_CONTROL_CHARS = set(";&|()\n{}")
_GIT_TOKEN = re.compile(
    r"(?:^|[^A-Za-z0-9_.-])git(?:\.exe)?(?=$|[^A-Za-z0-9_.-])",
    re.IGNORECASE,
)
_LEADING_WORDS = {"!", "if", "then", "elif", "while", "until", "do"}
_WRAPPERS = {"call", "command", "env", "exec", "nice", "nohup", "sudo", "time"}
_SHELLS = {"bash", "dash", "ksh", "sh", "zsh"}
_CMD_SHELLS = {"cmd"}
_POWERSHELLS = {"powershell", "pwsh"}
_WRAPPER_VALUE_OPTIONS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "sudo": {"-C", "-D", "-g", "-h", "-p", "-R", "-r", "-t", "-u", "-U"},
    "time": {"-f", "--format", "-o", "--output"},
}
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$|^\*\*\* Move to:\s*(.+?)\s*$",
    re.MULTILINE,
)


def _path(value: str, base: Optional[Path] = None) -> Path:
    result = Path(value).expanduser()
    if base is not None and not result.is_absolute():
        result = base / result
    return result.resolve(strict=False)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _import_controller(plugin_root: Optional[Path] = None) -> None:
    scripts_dir = (plugin_root or Path(__file__).resolve().parents[1]) / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def in_configured_scope(
    data_dir: Path,
    environ: Mapping[str, str],
    *candidates: Path,
    plugin_root: Optional[Path] = None,
) -> bool:
    """Report whether any candidate directory is inside the configured scope.

    An unreadable configuration or an unavailable controller fails open, so a
    broken scope file never hides the workflow from the directories that need
    it.  The controller owns the matching rules; this only aggregates them.
    """

    _import_controller(plugin_root)
    try:
        from dev_flow import evaluate_scope, resolve_scope

        scope = resolve_scope(data_dir, environ)
        return any(
            evaluate_scope(candidate, scope).get("in_scope") for candidate in candidates
        )
    except Exception:
        return True


def load_active_task(
    data_dir: Path, cwd: Path, plugin_root: Optional[Path] = None
) -> Optional[dict[str, Any]]:
    """Use the controller's read-only lookup and preserve ownership ambiguity."""

    _import_controller(plugin_root)
    try:
        from dev_flow import find_active_task_for_cwd, load_state

        task = find_active_task_for_cwd(cwd=cwd, data_dir=data_dir)
        if task is None:
            relative = cwd.relative_to(data_dir / "tasks")
            if len(relative.parts) >= 2 and relative.parts[1] == "artifacts":
                candidate = load_state(relative.parts[0], data_dir=data_dir)
                if candidate.get("status") not in {"DONE", "CANCELLED"}:
                    task = candidate
    except Exception as exc:
        if getattr(exc, "code", None) == "ACTIVE_TASK_AMBIGUITY":
            return {
                "task_id": "active-task-ambiguity",
                "status": "BLOCKED",
                "flow": "full",
                "workspace": {"strategy": "worktree", "ready": False},
                "repositories": [],
                "_active_task_ambiguity": True,
                "ambiguity": dict(getattr(exc, "details", {})),
            }
        return None
    return dict(task) if isinstance(task, Mapping) else None


def _stage(task: Mapping[str, Any]) -> str:
    value = task.get("status", task.get("stage", "UNKNOWN"))
    return str(value).upper()


def _flow(task: Mapping[str, Any]) -> str:
    value = task.get("flow")
    return value if value in {"full", "lite"} else "full"


def _workspace_strategy(task: Mapping[str, Any]) -> str:
    workspace = task.get("workspace")
    value = workspace.get("strategy") if isinstance(workspace, Mapping) else None
    if value in WORKSPACE_STRATEGY_NAMES_ZH:
        return str(value)
    return "in-place" if _flow(task) == "lite" else "worktree"


class _WorkflowView(NamedTuple):
    bundle: Any
    resolution: Mapping[str, Any]
    progress: Mapping[str, Any]
    node: Mapping[str, Any]
    actions: Sequence[Mapping[str, object]]
    task_next: Mapping[str, Any]


def _controller_workflow_view(
    task: Mapping[str, Any],
    data_dir: Path,
    plugin_root: Optional[Path] = None,
) -> _WorkflowView:
    """Read all Hook metadata through the controller's pinned catalog.

    A blocked task projects progress from its recorded origin, while its
    current node and legal frontier remain BLOCKED.  No Hook-local workflow
    ordering, labels, gates, or next-action table participates in this view.
    """

    _import_controller(plugin_root)
    from dev_flow import (
        _workflow_projection_frontier,
        build_task_next,
        resolve_loaded_task_workflow,
        workflow_node_description,
        workflow_progress_projection,
        workflow_runtime_services,
    )

    resolution = resolve_loaded_task_workflow(task, purpose="inspection")
    services = workflow_runtime_services()
    bundle = services.catalog.resolve_identity(
        str(resolution["bundle_sha256"])
    )
    progress_state: Mapping[str, Any] = task
    if _stage(task) == "BLOCKED":
        blocked = task.get("blocked")
        origin = (
            blocked.get("from_status")
            if isinstance(blocked, Mapping)
            else None
        )
        if isinstance(origin, str) and origin:
            candidate = dict(task)
            candidate["status"] = origin
            progress_state = candidate
    protocol_state = task
    revision = task.get("revision")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        compatible = dict(task)
        compatible["revision"] = 0
        protocol_state = compatible
    node_description = workflow_node_description(task)
    node = node_description.get("node")
    actions: list[dict[str, object]] = []
    legal_actions = node_description.get("legal_actions")
    if isinstance(legal_actions, list):
        for action in legal_actions:
            if not isinstance(action, Mapping):
                continue
            action_id = action.get("action_id")
            if not isinstance(action_id, str):
                continue
            projected: dict[str, object] = {"action_id": action_id}
            edge_id = action.get("edge_id")
            if isinstance(edge_id, str):
                projected["edge_id"] = edge_id
            actions.append(projected)
    status = task.get("status")
    current_node = bundle.node(status) if isinstance(status, str) else {}
    condition = {
        "kind": (
            "terminal"
            if bool(current_node.get("terminal"))
            else "blocked"
            if status == "BLOCKED"
            else "waiting"
            if bool(current_node.get("waiting"))
            else "ready"
        ),
        "node_id": status,
    }
    task_next = build_task_next(
        protocol_state,
        workflow_ref=resolution,
        frontier=_workflow_projection_frontier(protocol_state, bundle),
        # A compact Hook locator includes a next action only when the
        # controller projects exactly one unambiguous choice.  Keep the full
        # catalog action set separately for the legacy human-readable
        # projection helpers; serializing every legal edge can exceed the
        # agent-v1 task-next budget and would require an artifact write.
        actions=actions if len(actions) == 1 else (),
        condition=condition,
    )
    return _WorkflowView(
        bundle=bundle,
        resolution=resolution,
        progress=workflow_progress_projection(progress_state),
        node=node_description,
        actions=tuple(actions),
        task_next=task_next,
    )


def _localized_label(value: object, fallback: str) -> str:
    if isinstance(value, Mapping):
        for key in ("zh-CN", "en"):
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return " ".join(label.split())
    return fallback


def _workflow_name(view: _WorkflowView, fallback: str) -> str:
    graph = getattr(view.bundle, "graph", None)
    labels = graph.get("labels") if isinstance(graph, Mapping) else None
    label = _localized_label(labels, fallback)
    # Frozen legacy adapter labels deliberately announce their provenance.
    # Preserve the established Hook display wording without a second label
    # table by removing only those provenance markers.
    if view.resolution.get("adapter") is not None:
        compatible = label.replace("冻结", "").replace("旧版", "")
        return compatible or fallback
    return label


def _node_label(view: _WorkflowView, fallback: str) -> str:
    node = view.node.get("node")
    labels = node.get("labels") if isinstance(node, Mapping) else None
    return _localized_label(labels, fallback)


def _ordered_node_ids(view: _WorkflowView) -> tuple[str, ...]:
    graph = getattr(view.bundle, "graph", None)
    ordered = graph.get("ordered_nodes") if isinstance(graph, Mapping) else None
    if not isinstance(ordered, (list, tuple)):
        return ()
    return tuple(item for item in ordered if isinstance(item, str))


def _remaining_workflow(view: _WorkflowView) -> str:
    ordered = _ordered_node_ids(view)
    position = view.progress.get("position")
    if (
        not isinstance(position, int)
        or isinstance(position, bool)
        or position < 0
        or position >= len(ordered)
    ):
        return "无"
    remaining = ordered[position + 1 :]
    if not remaining:
        return "无"
    values = []
    for node_id in remaining:
        node = view.bundle.node(node_id)
        labels = node.get("labels") if isinstance(node, Mapping) else None
        values.append(
            f"{_localized_label(labels, node_id)}（{node_id}）"
        )
    return " → ".join(values)


def _render(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    if isinstance(value, Mapping):
        for key in ("value", "name", "gate", "action", "command", "id"):
            if value.get(key) not in (None, ""):
                return _render(value[key], fallback)
        rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    elif isinstance(value, list):
        rendered = ", ".join(_render(item, "") for item in value)
    else:
        rendered = str(value)
    return " ".join(rendered.split())[:500] or fallback


def _pending_gate(task: Mapping[str, Any], view: _WorkflowView) -> str:
    explicit = task.get("pending_gate", task.get("pendingGate"))
    if explicit not in (None, ""):
        return _render(explicit, "none")
    gates: list[str] = []
    if isinstance(view.actions, (list, tuple)):
        for action in view.actions:
            if not isinstance(action, Mapping):
                continue
            gate = action.get("gate")
            if gate not in (None, ""):
                rendered = _render(gate, "")
                if rendered and rendered not in gates:
                    gates.append(rendered)
    if not gates:
        projected = view.progress.get("pending_gates")
        if isinstance(projected, list):
            for gate in projected:
                rendered = _render(gate, "")
                if rendered and rendered not in gates:
                    gates.append(rendered)
    return ", ".join(gates) if gates else "none"


def _selected_index_role(view: _WorkflowView) -> Optional[str]:
    role = view.progress.get("index_role")
    if not isinstance(role, str) or role in {"", "origin"}:
        return None
    return role


def _index_selection_context(
    task: Mapping[str, Any], view: _WorkflowView
) -> tuple[str, str]:
    role = _selected_index_role(view)
    if role is None:
        return "none", "none"
    projects: list[str] = []
    for repo in _task_repositories(task):
        repository_id = _render(repo.get("id"), "unknown")
        record = repo.get("index" if role == "baseline" else "workspace_index")
        project = None
        if isinstance(record, Mapping):
            value = record.get("index_id")
            if isinstance(value, str) and value.strip():
                project = value.strip()
        projects.append(f"{repository_id}={project or 'MISSING'}")
    return role, ", ".join(projects) or "none"


def _quote(value: str) -> str:
    """Quote one argument for the shell family native to this platform."""
    if os.name == "nt":
        needs_quotes = (
            not value
            or any(char in value for char in " \t&|<>()^")
        )
        if not needs_quotes:
            return value
        rendered = ['"']
        backslashes = 0
        for char in value:
            if char == "\\":
                backslashes += 1
                continue
            if char == '"':
                rendered.append("\\" * (backslashes * 2 + 1))
                rendered.append('"')
            else:
                rendered.append("\\" * backslashes)
                rendered.append(char)
            backslashes = 0
        rendered.append("\\" * (backslashes * 2))
        rendered.append('"')
        return "".join(rendered)
    return shlex.quote(value)


def _controller_prefix(data_dir: Path, controller: Path = CONTROLLER) -> str:
    # sys.executable, not "python3": the interpreter running this hook is the
    # one the registration chose, and "python3" does not exist on stock Windows.
    return (
        f"{_quote(sys.executable)} {_quote(str(controller))} "
        f"--data-dir {_quote(str(data_dir))}"
    )


def build_bootstrap_context(data_dir: Path, controller: Path = CONTROLLER) -> str:
    prefix = _controller_prefix(data_dir, controller)
    return "\n".join(
        (
            "Dev Flow controller bootstrap:",
            f"- Interpreter: {sys.executable}",
            f"- Controller: {controller}",
            f"- Data directory: {data_dir}",
            f"- Bootstrap command: {prefix} list",
            "- 启动前确认：必须用中文询问用户选择“使用当前分支（精简流程）”、"
            "“新建并切换分支（精简流程）”或“创建独立工作树（完整流程）”。"
            "未经明确选择，不得启动任务、切换分支或创建工作树。",
            f"Every controller call must explicitly include "
            f"--data-dir {_quote(str(data_dir))}; do not rely on environment fallback.",
        )
    )


def build_compact_bootstrap_context(
    data_dir: Path,
    controller: Path = CONTROLLER,
) -> str:
    prefix = _controller_prefix(data_dir, controller)
    return (
        "Dev Flow controller bootstrap: no active task | "
        "启动前必须用中文让用户选择当前分支、新分支或独立工作树；"
        "未经明确选择不得 start 或改变 Git | "
        f"Bootstrap command: {prefix} list | "
        "Every controller call must explicitly include "
        f"--data-dir {_quote(str(data_dir))}"
    )


def _uses_v2_confirmation_contract(task: Mapping[str, Any]) -> bool:
    schema_version = task.get("schema_version")
    return (
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version >= 2
        and task.get("confirmation_contract_version") == 1
    )


def _confirmation_checkpoint(
    task: Mapping[str, Any], view: _WorkflowView
) -> str:
    if not _uses_v2_confirmation_contract(task):
        return (
            "状态切换确认（schema v1）：每条状态边仍须单独用中文展示并取得"
            "明确确认；transition/cancel 使用旧的直接调用"
        )
    automatic_edges: list[str] = []
    for source in _ordered_node_ids(view):
        for edge in view.bundle.legal_edges(source):
            if not isinstance(edge, Mapping) or edge.get("automatic") is not True:
                continue
            trigger = edge.get("trigger")
            action_id = (
                trigger.get("id")
                if isinstance(trigger, Mapping)
                else None
            )
            target = edge.get("target")
            if isinstance(action_id, str) and isinstance(target, str):
                automatic_edges.append(f"{action_id} {source}→{target}")
    automatic = "、".join(automatic_edges) or "none"
    return (
        f"状态切换确认（schema v2）：自动边仅 {automatic}；其他 "
        "transition/cancel 必须先 --preview，再用同一 revision 的 "
        "--confirm-intent；DONE/CANCELLED 永远显式确认"
    )


def _projected_next_action(
    task: Mapping[str, Any], view: _WorkflowView
) -> str:
    explicit = task.get("next_action")
    if explicit not in (None, ""):
        return _render(explicit, "inspect task state")
    action_ids: list[str] = []
    if isinstance(view.actions, (list, tuple)):
        for action in view.actions:
            if not isinstance(action, Mapping):
                continue
            action_id = action.get("action_id")
            if isinstance(action_id, str) and action_id not in action_ids:
                action_ids.append(action_id)
    if action_ids:
        return ", ".join(action_ids)
    condition = view.task_next.get("condition")
    kind = condition.get("kind") if isinstance(condition, Mapping) else None
    return f"no legal action ({kind})" if isinstance(kind, str) else "inspect task state"


def build_context(
    task: Mapping[str, Any],
    data_dir: Path,
    in_scope: bool = True,
    controller: Path = CONTROLLER,
) -> str:
    stage = _stage(task)
    flow = _flow(task)
    view = _controller_workflow_view(task, data_dir, controller.parent.parent)
    prefix = _controller_prefix(data_dir, controller)
    task_id = _render(task.get("task_id"), "unknown")
    index_role, index_projects = _index_selection_context(task, view)
    strategy = _workspace_strategy(task)
    revision = _render(task.get("revision"), "unknown")
    scope = "in" if in_scope else "outside"
    confirmation = _confirmation_checkpoint(task, view)
    lines = [
        "Dev Flow active-task checkpoint:",
        f"- Active task: {task_id}",
        f"- Revision: {revision}",
        f"- 流程名称: {_workflow_name(view, flow)}（{flow}）",
        f"- 工作方式: {WORKSPACE_STRATEGY_NAMES_ZH[strategy]}（{strategy}）",
        f"- 当前状态: {_node_label(view, stage)}（{stage}）",
        f"- 剩余流程: {_remaining_workflow(view)}",
        f"- Route: {_render(task.get('route'), 'not selected')}",
        f"- Pending gate: {_pending_gate(task, view)}",
        "- codebase-memory selection: explicit project parameter; never automatic",
        f"- Active index role: {index_role}",
        f"- Active index projects: {index_projects}",
        f"- Next action: {_projected_next_action(task, view)}",
        f"- Scope: {scope}",
        f"- Interpreter: {sys.executable}",
        f"- Controller: {controller}",
        f"- Data directory: {data_dir}",
        f"- Resume command: {prefix} show --task {_quote(task_id)} --compact",
        f"- {confirmation}",
        "- 预检必须先执行不提交任务状态的 preflight --preview；确认其返回的"
        "唯一 transition_preview 后，用 preflight --confirm-preview <token>"
        " 确认这一条状态边。只有决策输入或状态边漂移才必须重新 preview。",
        "- 若仅轻量观察（observation）或证据摘要（evidence summary）刷新，"
        "必须停下并向用户展示当前证据；取得用户明确接受后，可用同一 token"
        " 执行 preflight --confirm-preview <token> --accept-evidence-refresh"
        " 继续确认。部分仓库预检只能记录证据；状态变化必须由覆盖全部仓库的"
        "预览/确认对完成。",
    ]
    if not in_scope:
        lines.append(
            "- Directory scope: outside the configured scope; this active task "
            "keeps the hooks enabled here"
        )
    lines.append(
        f"Every controller call must explicitly include "
        f"--data-dir {_quote(str(data_dir))}; do not rely on environment fallback."
    )
    return "\n".join(lines)


def build_compact_context(
    task: Mapping[str, Any],
    data_dir: Path,
    in_scope: bool = True,
    controller: Path = CONTROLLER,
) -> str:
    stage = _stage(task)
    flow = _flow(task)
    view = _controller_workflow_view(task, data_dir, controller.parent.parent)
    strategy = _workspace_strategy(task)
    task_id = _render(task.get("task_id"), "unknown")
    revision = _render(task.get("revision"), "unknown")
    index_role, index_projects = _index_selection_context(task, view)
    scope = "in" if in_scope else "outside"
    prefix = _controller_prefix(data_dir, controller)
    confirmation = _confirmation_checkpoint(task, view)
    return " | ".join(
        (
            "Dev Flow active-task checkpoint",
            f"Active task: {task_id}",
            f"Revision: {revision}",
            f"流程名称: {_workflow_name(view, flow)}（{flow}）",
            (
                "工作方式: "
                f"{WORKSPACE_STRATEGY_NAMES_ZH[strategy]}（{strategy}）"
            ),
            f"当前状态: {_node_label(view, stage)}（{stage}）",
            f"剩余流程: {_remaining_workflow(view)}",
            f"Pending gate: {_pending_gate(task, view)}",
            f"Active index role: {index_role}",
            f"Active index projects: {index_projects}",
            f"Next action: {_projected_next_action(task, view)}",
            f"Scope: {scope}",
            f"Resume command: {prefix} show --task {_quote(task_id)} --compact",
            confirmation,
            (
                "Every controller call must explicitly include "
                f"--data-dir {_quote(str(data_dir))}"
            ),
        )
    )


def build_locator_context(
    task: Mapping[str, Any],
    data_dir: Path,
    controller: Path = CONTROLLER,
) -> tuple[str, Mapping[str, Any]]:
    """Return the controller-built, budgeted model-visible checkpoint."""

    view = _controller_workflow_view(
        task, data_dir, controller.parent.parent
    )
    _import_controller(controller.parent.parent)
    from dev_flow import build_hook_checkpoint

    task_id = _render(task.get("task_id"), "unknown")
    cli = (
        f"{_controller_prefix(data_dir, controller)} show "
        f"--task {_quote(task_id)} --next --profile agent-v1"
    )
    checkpoint = build_hook_checkpoint(
        view.task_next,
        controller_locator=f"cli:{cli}",
    )
    condition = checkpoint.get("condition")
    if isinstance(condition, dict) and not isinstance(
        condition.get("node_id"), str
    ):
        node = view.node.get("node")
        node_id = node.get("id") if isinstance(node, Mapping) else None
        if isinstance(node_id, str):
            condition["node_id"] = node_id
    encoded = json.dumps(
        checkpoint,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    # The controller is normative for this budget. Keep this local assertion
    # only as a fail-open packaging guard in case an incompatible controller
    # is paired with the Hook.
    if len(encoded) > 600:
        raise ValueError("controller hook checkpoint exceeds 600 UTF-8 bytes")
    return encoded.decode("utf-8"), checkpoint


def _stage_allows_writes(
    task: Mapping[str, Any], data_dir: Path
) -> bool:
    """Project repository-write eligibility from the pinned workflow."""

    try:
        view = _controller_workflow_view(task, data_dir)
    except Exception:
        return False
    node = view.node.get("node")
    effect_policy = (
        node.get("effect_policy") if isinstance(node, Mapping) else None
    )
    effects = (
        effect_policy.get("effects")
        if isinstance(effect_policy, Mapping)
        else None
    )
    if isinstance(effects, (list, tuple)) and "repository-write" in effects:
        return True
    # Frozen adapters preserve the legacy source-write window. Derive its
    # boundary from catalog metadata rather than Hook-local stage constants:
    # full flow starts at the first workspace-index node; lite flow starts at
    # the first destination reached through an approval-gated edge.
    if view.resolution.get("adapter") is None:
        return False
    if bool(view.progress.get("terminal")) or bool(
        view.progress.get("waiting")
    ):
        return False
    if view.progress.get("index_role") == "workspace":
        return True
    ordered = _ordered_node_ids(view)
    if any(
        isinstance(view.bundle.node(node_id), Mapping)
        and view.bundle.node(node_id).get("index_role") == "workspace"
        for node_id in ordered
    ):
        return False
    current = view.progress.get("position")
    if (
        not isinstance(current, int)
        or isinstance(current, bool)
        or current < 0
    ):
        return False
    gate_destinations: list[int] = []
    for source in ordered:
        for edge in view.bundle.legal_edges(source):
            if not isinstance(edge, Mapping) or not isinstance(
                edge.get("gate"), Mapping
            ):
                continue
            target = edge.get("target")
            if isinstance(target, str) and target in ordered:
                gate_destinations.append(ordered.index(target))
    return bool(gate_destinations) and current >= min(gate_destinations)


def _evidence_root(task: Mapping[str, Any], data_dir: Path) -> Optional[Path]:
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        return None
    if _stage(task) in {"BLOCKED", "CANCELLED", "DONE"}:
        return None
    return _path(str(data_dir / "tasks" / task_id / "artifacts"))


def _task_repositories(task: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    repositories = task.get("repositories")
    if not isinstance(repositories, list):
        return []
    return [repo for repo in repositories if isinstance(repo, Mapping)]


def _ready_workspaces(task: Mapping[str, Any]) -> list[Path]:
    result: list[Path] = []
    if _flow(task) == "lite":
        # The lite flow implements directly inside the source checkouts, so
        # they are its writable workspaces once the stage allows writes.
        for repo in _task_repositories(task):
            for value in (repo.get("path"), repo.get("canonical_path")):
                if isinstance(value, str) and value:
                    result.append(_path(value))
        return result
    for repo in _task_repositories(task):
        workspace = repo.get("workspace")
        if not isinstance(workspace, Mapping) or workspace.get("ready") is not True:
            continue
        value = workspace.get("path")
        if isinstance(value, str) and value:
            result.append(_path(value))
    return result


def _non_writable_roots(task: Mapping[str, Any]) -> list[Path]:
    if _flow(task) == "lite":
        return []
    result: list[Path] = []
    for repo in _task_repositories(task):
        for value in (repo.get("path"), repo.get("canonical_path")):
            if isinstance(value, str) and value:
                result.append(_path(value))
        analysis = repo.get("analysis_workspace")
        if isinstance(analysis, Mapping) and isinstance(analysis.get("path"), str):
            result.append(_path(analysis["path"]))
    return result


def _write_targets(
    tool_name: str,
    tool_input: Mapping[str, Any],
    workdir: Path,
) -> tuple[list[Path], bool]:
    """Return explicit target paths and whether target metadata was present."""

    raw_targets: list[str] = []
    target_metadata = False
    for key in ("file_path", "path"):
        if key not in tool_input:
            continue
        target_metadata = True
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            raw_targets.append(value.strip())
    if tool_name == "apply_patch":
        for key in ("command", "patch", "input"):
            patch_value = tool_input.get(key)
            if not isinstance(patch_value, str):
                continue
            matches = _PATCH_PATH.findall(patch_value)
            if matches:
                target_metadata = True
                raw_targets.extend((first or second).strip() for first, second in matches)
    targets: list[Path] = []
    for value in raw_targets:
        try:
            targets.append(_path(value, workdir))
        except (OSError, RuntimeError):
            target_metadata = True
    return targets, target_metadata


def _write_denial_reason(
    task: Mapping[str, Any],
    data_dir: Path,
    tool_name: str,
    tool_input: Mapping[str, Any],
    workdir: Path,
    workdir_valid: bool,
) -> Optional[str]:
    targets, has_target_metadata = _write_targets(tool_name, tool_input, workdir)
    if has_target_metadata and not targets:
        return "The file-write target could not be resolved to an allowed Dev Flow write root."
    if not targets and not workdir_valid:
        return "The file-write working directory could not be verified."
    candidates = targets or [workdir]
    forbidden = _non_writable_roots(task)
    for candidate in candidates:
        if any(_within(candidate, root) for root in forbidden):
            return "File writes to source repositories or analysis workspaces are blocked."
    allowed: list[Path] = []
    evidence = _evidence_root(task, data_dir)
    if evidence is not None:
        allowed.append(evidence)
    if _stage_allows_writes(task, data_dir):
        allowed.extend(_ready_workspaces(task))
    if not allowed:
        return f"Task writes are blocked while the active task is at {_stage(task)}."
    for candidate in candidates:
        if not any(_within(candidate, root) for root in allowed):
            return (
                "Every file-write target must be inside this task's artifacts directory "
                "or a verified ready managed workspace."
            )
    return None


class _Inspection(NamedTuple):
    invocations: list[tuple[str, list[str], Path]]
    diagnostic: Optional[str]
    recognized_wrapper: bool
    parse_failed: bool
    has_posix_heredoc: bool = False


class _PosixParse(NamedTuple):
    segments: list[list[str]]
    error: Optional[str]
    has_heredoc: bool


def _skip_posix_heredocs(
    command: str,
    index: int,
    delimiters: Sequence[tuple[str, bool]],
) -> tuple[int, Optional[str]]:
    """Skip static here-document bodies after their opening command line."""

    for delimiter, strip_tabs in delimiters:
        while True:
            if index >= len(command):
                return index, "POSIX shell here-document has no closing delimiter"
            newline = command.find("\n", index)
            if newline < 0:
                line = command[index:]
                index = len(command)
            else:
                line = command[index:newline]
                index = newline + 1
            if line.endswith("\r"):
                line = line[:-1]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                break
            if newline < 0:
                return index, "POSIX shell here-document has no closing delimiter"
    return index, None


def _parse_posix_segments(command: str) -> _PosixParse:
    """Split static POSIX commands without treating redirections as pipelines."""

    result: list[list[str]] = []
    current: list[str] = []
    word: list[str] = []
    quote: Optional[str] = None
    word_started = False
    word_protected = False
    pending_redirection: Optional[str] = None
    here_docs: list[tuple[str, bool]] = []
    has_heredoc = False
    index = 0

    def finish_word() -> None:
        nonlocal has_heredoc
        nonlocal pending_redirection
        nonlocal word_protected
        nonlocal word_started

        if not word_started:
            return
        value = "".join(word)
        if pending_redirection is not None:
            if pending_redirection in {"<<", "<<-"}:
                here_docs.append((value, pending_redirection == "<<-"))
                has_heredoc = True
            pending_redirection = None
        else:
            current.append(value)
        word.clear()
        word_started = False
        word_protected = False

    def finish_segment() -> None:
        finish_word()
        if current:
            result.append(list(current))
            current.clear()

    def redirection_operator(start: int) -> tuple[str, int]:
        if command[start] == "<":
            if command.startswith("<<<", start):
                return "<<<", start + 3
            if command.startswith("<<-", start):
                return "<<-", start + 3
            if command.startswith("<<", start):
                return "<<", start + 2
            if command.startswith("<&", start):
                return "<&", start + 2
            if command.startswith("<>", start):
                return "<>", start + 2
            return "<", start + 1
        if command.startswith(">>", start):
            return ">>", start + 2
        if command.startswith(">&", start):
            return ">&", start + 2
        if command.startswith(">|", start):
            return ">|", start + 2
        return ">", start + 1

    while index < len(command):
        char = command[index]
        if quote is not None:
            if char == quote:
                quote = None
                word_started = True
                word_protected = True
                index += 1
                continue
            if char == "\\" and quote == '"':
                index += 1
                if index >= len(command):
                    return _PosixParse(
                        [], "POSIX shell payload ends with an incomplete escape", has_heredoc
                    )
                escaped = command[index]
                if escaped != "\n":
                    word.append(escaped)
                    word_started = True
                index += 1
                continue
            word.append(char)
            word_started = True
            index += 1
            continue

        if char in " \t\r":
            finish_word()
            index += 1
            continue
        if char == "#":
            finish_word()
            newline = command.find("\n", index)
            index = len(command) if newline < 0 else newline
            continue
        if char == "\\":
            index += 1
            if index >= len(command):
                return _PosixParse(
                    [], "POSIX shell payload ends with an incomplete escape", has_heredoc
                )
            escaped = command[index]
            if escaped != "\n":
                word.append(escaped)
                word_started = True
                word_protected = True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            word_started = True
            word_protected = True
            index += 1
            continue
        if char in "<>":
            if word_started:
                if not word_protected and "".join(word).isdigit():
                    word.clear()
                    word_started = False
                    word_protected = False
                else:
                    finish_word()
            if pending_redirection is not None:
                return _PosixParse(
                    [],
                    "POSIX shell payload has a redirection without a target",
                    has_heredoc,
                )
            pending_redirection, index = redirection_operator(index)
            continue
        if char == "&" and command.startswith("&>", index):
            finish_word()
            if pending_redirection is not None:
                return _PosixParse(
                    [],
                    "POSIX shell payload has a redirection without a target",
                    has_heredoc,
                )
            if command.startswith("&>>", index):
                pending_redirection = "&>>"
                index += 3
            else:
                pending_redirection = "&>"
                index += 2
            continue
        if char in _POSIX_CONTROL_CHARS:
            finish_segment()
            if pending_redirection is not None:
                return _PosixParse(
                    [],
                    "POSIX shell payload has a redirection without a target",
                    has_heredoc,
                )
            index += 1
            if char != "\n":
                while index < len(command) and command[index] == char:
                    index += 1
            if char == "\n" and here_docs:
                index, error = _skip_posix_heredocs(command, index, here_docs)
                if error is not None:
                    return _PosixParse([], error, has_heredoc)
                here_docs.clear()
            continue
        word.append(char)
        word_started = True
        index += 1

    if quote is not None:
        return _PosixParse(
            [], f"POSIX shell payload has an unmatched {quote} quote", has_heredoc
        )
    finish_segment()
    if pending_redirection is not None:
        return _PosixParse(
            [], "POSIX shell payload has a redirection without a target", has_heredoc
        )
    if here_docs:
        return _PosixParse(
            [], "POSIX shell here-document has no closing delimiter", has_heredoc
        )
    return _PosixParse(result, None, has_heredoc)


def _posix_segments(command: str) -> tuple[list[list[str]], Optional[str]]:
    parsed = _parse_posix_segments(command)
    return parsed.segments, parsed.error


def _cmd_segments(command: str) -> tuple[list[list[str]], Optional[str]]:
    """Tokenize the conservative cmd.exe subset used by command hooks."""

    result: list[list[str]] = []
    current: list[str] = []
    token: list[str] = []
    quoted = False
    index = 0

    def finish_token() -> None:
        if token:
            current.append("".join(token))
            token.clear()

    def finish_segment() -> None:
        finish_token()
        if current:
            result.append(list(current))
            current.clear()

    while index < len(command):
        char = command[index]
        if char == "^":
            index += 1
            if index >= len(command):
                return [], "cmd.exe payload ends with an incomplete caret escape"
            token.append(command[index])
            index += 1
            continue
        if char == '"':
            quoted = not quoted
            index += 1
            continue
        if not quoted and char in " \t\r":
            finish_token()
            index += 1
            continue
        if not quoted and char in "&|()\n":
            finish_segment()
            index += 1
            while index < len(command) and command[index] == char:
                index += 1
            continue
        token.append(char)
        index += 1
    if quoted:
        return [], "cmd.exe payload has an unmatched double quote"
    finish_segment()
    return result, None


def _powershell_segments(command: str) -> tuple[list[list[str]], Optional[str]]:
    """Tokenize a static PowerShell command payload without evaluating it."""

    result: list[list[str]] = []
    current: list[str] = []
    token: list[str] = []
    quote: Optional[str] = None
    index = 0

    def finish_token() -> None:
        if token:
            current.append("".join(token))
            token.clear()

    def finish_segment() -> None:
        finish_token()
        if current:
            result.append(list(current))
            current.clear()

    while index < len(command):
        char = command[index]
        if quote == "'" and char == "'" and index + 1 < len(command) and command[index + 1] == "'":
            token.append("'")
            index += 2
            continue
        if char == "`" and quote != "'":
            index += 1
            if index >= len(command):
                return [], "PowerShell payload ends with an incomplete backtick escape"
            token.append(command[index])
            index += 1
            continue
        if char in {"'", '"'}:
            if quote is None:
                quote = char
                index += 1
                continue
            if quote == char:
                quote = None
                index += 1
                continue
        if quote is None and char in " \t\r":
            finish_token()
            index += 1
            continue
        if quote is None and char == "#":
            finish_segment()
            newline = command.find("\n", index)
            if newline < 0:
                index = len(command)
            else:
                index = newline
            continue
        if quote is None and char in ";|(){}\n":
            if char in "({" and current == ["&"] and not token:
                return [], (
                    "PowerShell call operator targets a computed expression "
                    "or script block"
                )
            finish_segment()
            index += 1
            while index < len(command) and command[index] == char:
                index += 1
            continue
        if quote is None and char == "&":
            if not current and not token:
                current.append("&")
            else:
                finish_segment()
            index += 1
            if index < len(command) and command[index] == "&":
                index += 1
            continue
        token.append(char)
        index += 1
    if quote is not None:
        return [], f"PowerShell payload has an unmatched {quote} quote"
    finish_segment()
    return result, None


def _basename(token: str) -> str:
    basename = re.split(r"[\\/]", token)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if basename.endswith(suffix):
            return basename[: -len(suffix)]
    return basename


def _simple_command(tokens: Sequence[str]) -> tuple[Optional[str], list[str]]:
    index = 0
    while index < len(tokens) and (
        tokens[index] in _LEADING_WORDS
        or tokens[index] == "&"
        or _ASSIGNMENT.match(tokens[index])
    ):
        index += 1
    while index < len(tokens):
        executable = tokens[index]
        if executable.startswith("@"):
            executable = executable[1:]
        name = _basename(executable)
        index += 1
        if name not in _WRAPPERS:
            return name, list(tokens[index:])
        value_options = _WRAPPER_VALUE_OPTIONS.get(name, set())
        while index < len(tokens):
            token = tokens[index]
            if _ASSIGNMENT.match(token):
                index += 1
                continue
            if token == "--":
                index += 1
                break
            if not token.startswith("-"):
                break
            option = token.split("=", 1)[0]
            index += 1
            if option in value_options and "=" not in token and index < len(tokens):
                index += 1
    return None, []


def _payload_has_dynamic_expansion(command: str, dialect: str) -> bool:
    """Recognize expansion syntax while preserving quote/escape provenance."""

    quote: Optional[str] = None
    index = 0
    while index < len(command):
        char = command[index]
        if dialect == "cmd":
            if char == "^":
                index += 2
                continue
            if char in {"%", "!"}:
                return True
            index += 1
            continue

        if dialect == "powershell":
            if (
                quote == "'"
                and char == "'"
                and index + 1 < len(command)
                and command[index + 1] == "'"
            ):
                index += 2
                continue
            if char == "`" and quote != "'":
                index += 2
                continue
        elif char == "\\" and quote != "'":
            index += 2
            continue

        if char in {"'", '"'}:
            if quote is None:
                quote = char
                index += 1
                continue
            if quote == char:
                quote = None
                index += 1
                continue
        if quote != "'" and (
            char == "$" or (dialect == "posix" and char == "`")
        ):
            return True
        index += 1
    return False


def _posix_shell_payload(args: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    for index, argument in enumerate(args):
        if argument in {"-c", "--command"} or (
            argument.startswith("-")
            and not argument.startswith("--")
            and "c" in argument[1:]
        ):
            if index + 1 >= len(args):
                return None, "POSIX shell command option has no payload"
            return args[index + 1], None
    return None, "POSIX shell invocation has no inspectable command payload"


def _cmd_shell_payload(args: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    matches: list[tuple[int, str]] = []
    for index, argument in enumerate(args):
        lowered = argument.lower()
        if lowered == "/c":
            matches.append((index, ""))
        elif lowered.startswith("/c") and len(argument) > 2:
            matches.append((index, argument[2:]))
    if len(matches) > 1:
        return None, "cmd.exe payload has more than one /c option"
    if not matches:
        return None, "cmd.exe invocation has no supported static /c payload"
    index, attached = matches[0]
    parts = ([attached] if attached else []) + list(args[index + 1 :])
    if not parts or not any(part.strip() for part in parts):
        return None, "cmd.exe /c option has no payload"
    return " ".join(parts), None


def _powershell_payload(args: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    matches: list[tuple[int, str]] = []
    for index, argument in enumerate(args):
        lowered = argument.lower()
        if lowered in {"-encodedcommand", "-enc", "-e"}:
            return None, "encoded PowerShell commands cannot be inspected safely"
        if lowered in {"-file", "-f"}:
            return None, "PowerShell -File commands cannot be inspected safely"
        if lowered in {"-command", "-c", "/command", "/c"}:
            matches.append((index, ""))
        elif lowered.startswith(("-command:", "/command:")):
            matches.append((index, argument.split(":", 1)[1]))
    if len(matches) > 1:
        return None, "PowerShell payload has more than one command option"
    if not matches:
        return None, "PowerShell invocation has no supported static -Command payload"
    index, attached = matches[0]
    parts = ([attached] if attached else []) + list(args[index + 1 :])
    if not parts or not any(part.strip() for part in parts) or parts[0] == "-":
        return None, "PowerShell command option has no static payload"
    return " ".join(parts), None


def _inspection_error(wrapper: str, detail: str) -> str:
    return (
        f"Dev Flow blocked a recognized {wrapper} wrapper because its payload "
        f"could not be inspected safely: {detail}."
    )


def _inspect_tokens(
    segments: Sequence[Sequence[str]],
    cwd: Path,
    dialect: str,
    depth: int,
    strict: bool,
) -> _Inspection:
    invocations: list[tuple[str, list[str], Path]] = []
    recognized = False
    ambiguous_commands = {
        "posix": {"eval", "source", "."},
        "cmd": {"for", "if"},
        "powershell": {"iex", "invoke-expression"},
    }
    for segment in segments:
        name, args = _simple_command(segment)
        if name is None:
            continue
        if strict and (
            name in ambiguous_commands.get(dialect, set())
        ):
            return _Inspection(
                invocations,
                _inspection_error(dialect, f"dynamic command {name!r}"),
                recognized,
                False,
            )
        if name == "git":
            parsed = _parse_git(args, cwd)
            if parsed is not None:
                invocations.append(parsed)
            continue
        if name in _SHELLS:
            recognized = True
            payload, error = _posix_shell_payload(args)
            wrapper = f"{name} POSIX shell"
            child_dialect = "posix"
        elif name in _CMD_SHELLS:
            recognized = True
            payload, error = _cmd_shell_payload(args)
            wrapper = "cmd.exe"
            child_dialect = "cmd"
        elif name in _POWERSHELLS:
            recognized = True
            payload, error = _powershell_payload(args)
            wrapper = f"{name} PowerShell"
            child_dialect = "powershell"
        else:
            continue
        if error is not None:
            return _Inspection(
                invocations,
                _inspection_error(wrapper, error),
                recognized,
                False,
            )
        if payload is None:
            continue
        if depth >= 4:
            return _Inspection(
                invocations,
                _inspection_error(wrapper, "wrapper nesting exceeds the supported depth"),
                recognized,
                False,
            )
        nested = _inspect_payload(payload, cwd, child_dialect, depth + 1, True)
        invocations.extend(nested.invocations)
        recognized = recognized or nested.recognized_wrapper
        if nested.diagnostic is not None:
            return _Inspection(invocations, nested.diagnostic, recognized, False)
    return _Inspection(invocations, None, recognized, False)


def _inspect_payload(
    command: str,
    cwd: Path,
    dialect: str,
    depth: int,
    strict: bool,
) -> _Inspection:
    if strict and _payload_has_dynamic_expansion(command, dialect):
        return _Inspection(
            [],
            _inspection_error(
                dialect,
                "dynamic expansion could change the command or its separators",
            ),
            False,
            False,
        )
    has_posix_heredoc = False
    if dialect == "cmd":
        segments, error = _cmd_segments(command)
    elif dialect == "powershell":
        segments, error = _powershell_segments(command)
    else:
        parsed = _parse_posix_segments(command)
        segments, error = parsed.segments, parsed.error
        has_posix_heredoc = parsed.has_heredoc
    if error is not None:
        diagnostic = _inspection_error(dialect, error) if strict else None
        return _Inspection([], diagnostic, False, True)
    inspection = _inspect_tokens(segments, cwd, dialect, depth, strict)
    if has_posix_heredoc:
        return _Inspection(
            inspection.invocations,
            inspection.diagnostic,
            inspection.recognized_wrapper,
            inspection.parse_failed,
            has_posix_heredoc=True,
        )
    return inspection


def _recognized_wrapper_prefix(command: str) -> Optional[str]:
    raw = command.lstrip()
    if not raw:
        return None
    if raw[0] in {"'", '"'}:
        quote = raw[0]
        end = raw.find(quote, 1)
        token = raw[1:] if end < 0 else raw[1:end]
    else:
        token = raw.split(None, 1)[0]
    name = _basename(token)
    if name in _SHELLS | _CMD_SHELLS | _POWERSHELLS:
        return name
    return None


def _raw_cmd_prefix_payload(command: str) -> tuple[Optional[str], Optional[str]]:
    match = re.search(r"(?i)(?:^|\s)/c(?=\s|$)", command)
    if match is None:
        return None, None
    payload = command[match.end() :].lstrip()
    if not payload:
        return None, "cmd.exe /c option has no payload"
    # With /s /c, Command Prompt conventionally wraps a quoted executable and
    # its arguments in one extra pair of quotes:
    #   cmd.exe /s /c ""C:\Program Files\Git\cmd\git.exe" status"
    if len(payload) >= 2 and payload[0] == payload[-1] == '"':
        payload = payload[1:-1]
    return payload, None


def _parse_git(args: Sequence[str], cwd: Path) -> Optional[tuple[str, list[str], Path]]:
    index = 0
    git_cwd = cwd
    value_options = {
        "-c",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
    while index < len(args):
        token = args[index]
        if token == "-C" and index + 1 < len(args):
            git_cwd = _path(args[index + 1], git_cwd)
            index += 2
            continue
        if token.startswith("-C") and len(token) > 2:
            git_cwd = _path(token[2:], git_cwd)
            index += 1
            continue
        option = token.split("=", 1)[0]
        if token.startswith("-"):
            index += 1
            if option in value_options and "=" not in token and index < len(args):
                index += 1
            continue
        return token.lower(), list(args[index + 1 :]), git_cwd
    return None


def _may_contain_git(command: str) -> bool:
    return _GIT_TOKEN.search(command) is not None


def _git_invocations(
    command: str, cwd: Path
) -> tuple[list[tuple[str, list[str], Path]], Optional[str]]:
    # Codex's canonical command tool is named Bash on every platform, but its
    # payload may contain native Windows executables.  Inspect once with POSIX
    # rules and once with cmd rules so unquoted backslash paths are not damaged.
    prefix = _recognized_wrapper_prefix(command)
    if prefix == "cmd":
        payload, error = _raw_cmd_prefix_payload(command)
        if error is not None:
            return [], _inspection_error("cmd.exe", error)
        if payload is not None:
            inspection = _inspect_payload(payload, cwd, "cmd", 1, True)
            return inspection.invocations, inspection.diagnostic

    primary = _inspect_payload(command, cwd, "posix", 0, False)
    if primary.parse_failed and _may_contain_git(command):
        return [], _inspection_error(
            "POSIX shell",
            "the command may invoke Git but its POSIX syntax could not be inspected safely",
        )
    inspections = [primary]
    if not primary.recognized_wrapper and not primary.has_posix_heredoc:
        inspections.append(_inspect_payload(command, cwd, "cmd", 0, False))
    result: list[tuple[str, list[str], Path]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for inspection in inspections:
        if inspection.diagnostic is not None:
            return result, inspection.diagnostic
        for subcommand, args, git_cwd in inspection.invocations:
            key = (subcommand, tuple(args), str(git_cwd))
            if key not in seen:
                seen.add(key)
                result.append((subcommand, args, git_cwd))
    if all(inspection.parse_failed for inspection in inspections):
        wrapper = prefix
        if wrapper is not None:
            return result, _inspection_error(
                wrapper, "the outer command line has invalid quoting or escaping"
            )
    return result, None


def _repo_paths(repo: Mapping[str, Any]) -> list[Path]:
    values = [repo.get("path"), repo.get("canonical_path")]
    for key in ("analysis_workspace", "workspace"):
        workspace = repo.get(key)
        if isinstance(workspace, Mapping):
            values.append(workspace.get("path"))
    result: list[Path] = []
    for value in values:
        if isinstance(value, str) and value:
            try:
                result.append(_path(value))
            except (OSError, RuntimeError):
                pass
    return result


def _matching_repo(task: Optional[Mapping[str, Any]], cwd: Path) -> Optional[Mapping[str, Any]]:
    if task is None:
        return None
    repositories = task.get("repositories")
    if not isinstance(repositories, list):
        return None
    for repo in repositories:
        if isinstance(repo, Mapping) and any(_within(cwd, candidate) for candidate in _repo_paths(repo)):
            return repo
    return None


def _normal_branch(value: Any) -> str:
    branch = str(value or "").strip().lstrip("+")
    for prefix in ("refs/heads/", "heads/"):
        if branch.startswith(prefix):
            branch = branch[len(prefix) :]
    return branch


def _protected_branches(task: Optional[Mapping[str, Any]], cwd: Path) -> set[str]:
    protected = set(DEFAULT_PROTECTED_BRANCHES)
    repo = _matching_repo(task, cwd)
    if repo is None:
        return protected
    configured = repo.get("protected_branches")
    if isinstance(configured, str):
        protected.update(item for item in re.split(r"[,\s]+", configured) if item)
    elif isinstance(configured, list):
        protected.update(_normal_branch(item) for item in configured if item)
    for key in ("preflight", "baseline"):
        record = repo.get(key)
        if isinstance(record, Mapping) and record.get("base_branch"):
            protected.add(_normal_branch(record["base_branch"]))
    return {branch for branch in protected if branch}


def _current_branch(cwd: Path, task: Optional[Mapping[str, Any]]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "branch", "--show-current"],
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return _normal_branch(result.stdout.decode("utf-8", errors="replace"))
    repo = _matching_repo(task, cwd)
    if repo is None:
        return None
    for key in ("workspace", "analysis_workspace", "preflight"):
        record = repo.get(key)
        if isinstance(record, Mapping) and record.get("branch"):
            return _normal_branch(record["branch"])
    return None


def _force_push(args: Sequence[str]) -> bool:
    for arg in args:
        if arg in {"-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror"}:
            return True
        if arg.startswith(("--force=", "--force-with-lease=", "--force-if-includes=")):
            return True
        if arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:]:
            return True
        if arg.startswith("+"):
            return True
    return False


def _push_args(args: Sequence[str]) -> tuple[list[str], bool, bool, bool]:
    positionals: list[str] = []
    delete = False
    all_refs = False
    remote_option = False
    value_options = {"--exec", "--push-option", "--receive-pack", "--repo", "-o"}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positionals.extend(args[index + 1 :])
            break
        option = arg.split("=", 1)[0]
        delete = delete or option in {"--delete", "-d"}
        all_refs = all_refs or option in {"--all", "--mirror"}
        remote_option = remote_option or option == "--repo"
        if arg.startswith("-"):
            index += 1
            if option in value_options and "=" not in arg and index < len(args):
                index += 1
            continue
        positionals.append(arg)
        index += 1
    return positionals, delete, all_refs, remote_option


def _protected_ref(refspec: str, protected: set[str], branch: Optional[str]) -> bool:
    value = refspec.lstrip("+")
    target = value.rsplit(":", 1)[-1] if ":" in value else value
    target = _normal_branch(target)
    if target in {"HEAD", "@"}:
        target = branch or ""
    if target in protected:
        return True
    return "*" in target and any(fnmatch.fnmatchcase(item, target) for item in protected)


def _pushes_protected(args: Sequence[str], protected: set[str], branch: Optional[str]) -> bool:
    positionals, delete, all_refs, remote_option = _push_args(args)
    if all_refs:
        return True
    refspecs = positionals if remote_option else positionals[1:]
    if not refspecs:
        return branch in protected
    if delete:
        return any(_normal_branch(refspec) in protected for refspec in refspecs)
    return any(_protected_ref(refspec, protected, branch) for refspec in refspecs)


def _has_option(args: Sequence[str], *options: str) -> bool:
    for arg in args:
        if arg in options:
            return True
        if any(option.startswith("--") and arg.startswith(f"{option}=") for option in options):
            return True
        if "-b" in options and arg.startswith("-b") and not arg.startswith("--"):
            return True
        if "-B" in options and arg.startswith("-B") and not arg.startswith("--"):
            return True
    return False


def command_denial_reason(
    command: str,
    cwd: Path,
    task: Optional[Mapping[str, Any]],
    data_dir: Path,
    controller_path: Path = CONTROLLER,
) -> Optional[str]:
    controller = _controller_prefix(data_dir, controller_path)
    invocations, diagnostic = _git_invocations(command, cwd)
    if diagnostic is not None:
        return diagnostic
    for subcommand, args, git_cwd in invocations:
        if subcommand == "push" and _force_push(args):
            return f"Force-push is blocked by Dev Flow; use {controller}."
        if subcommand == "reset" and _has_option(args, "--hard"):
            return "git reset --hard is blocked because it can discard workspace changes."
        if subcommand == "clean":
            return "git clean is blocked because it can permanently remove workspace files."
        if subcommand == "pull":
            return (
                "Direct git pull bypasses Dev Flow baseline management; "
                f"use {controller}."
            )
        if subcommand == "switch":
            return (
                "Direct git switch bypasses Dev Flow workspace management; "
                f"use {controller}."
            )
        if subcommand == "checkout" and _has_option(args, "-b", "-B", "--branch"):
            return f"Direct branch creation bypasses Dev Flow; use {controller}."
        if subcommand == "worktree":
            operation = next((arg for arg in args if not arg.startswith("-")), None)
            if operation == "add":
                return f"Direct git worktree add bypasses Dev Flow; use {controller}."
        if subcommand not in {"commit", "push"}:
            continue
        branch = _current_branch(git_cwd, task)
        protected = _protected_branches(task, git_cwd)
        if subcommand == "commit" and branch in protected:
            return f"Direct commits on protected branch {branch!r} are blocked."
        if subcommand == "push" and _pushes_protected(args, protected, branch):
            target = branch if branch in protected else "a protected branch"
            return f"Direct pushes to {target!r} are blocked; use {controller}."
    return None


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _active_task_ambiguity_context(task: Mapping[str, Any]) -> str:
    details = task.get("ambiguity")
    task_ids = (
        details.get("task_ids")
        if isinstance(details, Mapping)
        else None
    )
    rendered_ids = _render(task_ids, "unknown")
    return "\n".join(
        (
            "Dev Flow active-task ownership conflict:",
            "- Multiple non-terminal tasks match this repository; no task was selected.",
            f"- Conflicting task IDs: {rendered_ids}",
            "- All tool operations are blocked until the conflicting tasks are resolved or cancelled.",
        )
    )


class _PluginContext(NamedTuple):
    root: Optional[Path]
    data_dir: Optional[Path]
    controller: Optional[Path]
    diagnostic: Optional[str]


def _resolve_plugin_context(
    environ: Mapping[str, str],
    *,
    fallback_root: Optional[Path] = None,
    data_dir_from_cli: bool = False,
) -> _PluginContext:
    problems: list[str] = []
    root: Optional[Path] = None
    data_dir: Optional[Path] = None
    controller: Optional[Path] = None

    raw_root = environ.get("PLUGIN_ROOT")
    if not isinstance(raw_root, str) or not raw_root.strip():
        if fallback_root is None:
            problems.append("PLUGIN_ROOT is missing or empty")
        else:
            root = fallback_root.resolve(strict=False)
            controller = root / "scripts" / "dev_flow.py"
            if not controller.is_file():
                problems.append(
                    "the absolute hook path does not contain scripts/dev_flow.py"
                )
                controller = None
    else:
        try:
            supplied_root = Path(raw_root).expanduser()
            if not supplied_root.is_absolute():
                problems.append("PLUGIN_ROOT must be an absolute path")
            else:
                root = supplied_root.resolve(strict=False)
                controller = root / "scripts" / "dev_flow.py"
            if root is not None and not controller.is_file():
                problems.append(
                    "PLUGIN_ROOT does not contain scripts/dev_flow.py"
                )
                controller = None
        except (OSError, RuntimeError, ValueError):
            problems.append("PLUGIN_ROOT is not a resolvable filesystem path")
            root = None

    raw_data_dir = environ.get("PLUGIN_DATA")
    if not isinstance(raw_data_dir, str) or not raw_data_dir.strip():
        problems.append("PLUGIN_DATA is missing or empty")
    else:
        try:
            supplied_data_dir = Path(raw_data_dir).expanduser()
            if not data_dir_from_cli and not supplied_data_dir.is_absolute():
                problems.append("PLUGIN_DATA must be an absolute path")
            else:
                data_dir = supplied_data_dir.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            problems.append("PLUGIN_DATA is not a resolvable filesystem path")
            data_dir = None

    diagnostic = "; ".join(problems) if problems else None
    return _PluginContext(root, data_dir, controller, diagnostic)


def _environment_diagnostic(event: str, detail: str) -> dict[str, Any]:
    message = "\n".join(
        (
            "Dev Flow hook diagnostic:",
            f"- Required plugin environment is unavailable: {detail}.",
            "- No controller command was constructed and no workflow state was mutated.",
        )
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": message,
        }
    }


def _pending_checkpoint(
    payload: Mapping[str, Any],
    data_dir: Path,
    context: str,
    checkpoint_identity: Optional[Mapping[str, Any]] = None,
) -> Optional[_PendingCheckpoint]:
    raw_session_id = payload.get("session_id")
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        return None
    try:
        session_bytes = raw_session_id.encode("utf-8")
        context_bytes = context.encode("utf-8")
    except UnicodeEncodeError:
        return None
    session_sha256 = hashlib.sha256(session_bytes).hexdigest()
    identity = checkpoint_identity or {}
    task_id = identity.get("task_id")
    revision = identity.get("revision")
    frontier_sha256 = identity.get("frontier_sha256")
    projection_contract = identity.get("contract")
    return _PendingCheckpoint(
        data_dir / CHECKPOINT_MARKER_DIRECTORY / f"{session_sha256}.json",
        session_sha256,
        hashlib.sha256(context_bytes).hexdigest(),
        task_id if isinstance(task_id, str) else None,
        (
            revision
            if isinstance(revision, int) and not isinstance(revision, bool)
            else None
        ),
        frontier_sha256 if isinstance(frontier_sha256, str) else None,
        (
            projection_contract
            if isinstance(projection_contract, str)
            else None
        ),
    )


def _checkpoint_matches(checkpoint: _PendingCheckpoint) -> bool:
    try:
        with checkpoint.path.open("rb") as stream:
            encoded = stream.read(4097)
        if len(encoded) > 4096:
            return False
        document = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return False
    return (
        isinstance(document, Mapping)
        and set(document)
        == {
            "schema",
            "session_sha256",
            "context_sha256",
            "task_id",
            "revision",
            "frontier_sha256",
            "projection_contract",
        }
        and document.get("schema") == CHECKPOINT_MARKER_SCHEMA
        and document.get("session_sha256") == checkpoint.session_sha256
        and document.get("context_sha256") == checkpoint.context_sha256
        and document.get("task_id") == checkpoint.task_id
        and document.get("revision") == checkpoint.revision
        and document.get("frontier_sha256")
        == checkpoint.frontier_sha256
        and document.get("projection_contract")
        == checkpoint.projection_contract
    )


def _checkpointed_context_output(
    event: str,
    context: str,
    checkpoint_context: str,
    payload: Mapping[str, Any],
    data_dir: Path,
    checkpoint_identity: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    # UserPromptSubmit is the main-session user-prompt lifecycle event.  Codex
    # gives subagents their own SubagentStart/Stop events (with agent_id) while
    # reusing the parent session_id, so those events must never share this
    # prompt checkpoint marker.
    checkpoint = _pending_checkpoint(
        payload,
        data_dir,
        checkpoint_context,
        checkpoint_identity,
    )
    if (
        event == "UserPromptSubmit"
        and checkpoint is not None
        and _checkpoint_matches(checkpoint)
    ):
        return None
    return _HookOutput(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        },
        checkpoint,
    )


def _write_checkpoint(checkpoint: _PendingCheckpoint) -> None:
    directory = checkpoint.path.parent
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    encoded = json.dumps(
        {
            "schema": CHECKPOINT_MARKER_SCHEMA,
            "session_sha256": checkpoint.session_sha256,
            "context_sha256": checkpoint.context_sha256,
            "task_id": checkpoint.task_id,
            "revision": checkpoint.revision,
            "frontier_sha256": checkpoint.frontier_sha256,
            "projection_contract": checkpoint.projection_contract,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{checkpoint.path.name}.",
        suffix=".tmp",
        dir=directory,
    )
    temporary_path = Path(temporary_name)
    try:
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, checkpoint.path)
        try:
            checkpoint.path.chmod(0o600)
        except OSError:
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _payload_string(
    payload: Mapping[str, Any], *keys: str
) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _persisted_assignment_candidates(
    payload: Mapping[str, Any],
    task: Mapping[str, Any],
) -> list[str]:
    """Resolve host selectors only through persisted assignment/dispatch IDs."""

    orchestration = task.get("orchestration")
    if not isinstance(orchestration, Mapping):
        return []
    assignments = orchestration.get("assignments")
    dispatch = orchestration.get("dispatch")
    if not isinstance(assignments, Mapping) or not isinstance(
        dispatch, Mapping
    ):
        return []
    selector = _payload_string(
        payload, "assignment_id", "host_assignment_id"
    )
    agent_id = _payload_string(payload, "agent_id")
    agent_type = _payload_string(payload, "agent_type")
    if selector is None and agent_id is None and agent_type is None:
        return []
    matches: list[str] = []
    for assignment_id, assignment in assignments.items():
        if not isinstance(assignment_id, str) or not isinstance(
            assignment, Mapping
        ):
            continue
        record = dispatch.get(assignment_id)
        if not isinstance(record, Mapping):
            continue
        host_assignment_id = _payload_string(
            record, "host_assignment_id", "agent_id"
        )
        host_agent_type = _payload_string(
            record, "host_agent_type", "agent_type"
        )
        if not (
            (selector is not None and selector == assignment_id)
            or (
                selector is not None
                and selector == host_assignment_id
            )
            or (agent_id is not None and agent_id == assignment_id)
            or (
                agent_id is not None
                and agent_id == host_assignment_id
            )
            or (
                agent_type is not None
                and agent_type == host_agent_type
            )
        ):
            continue
        matches.append(assignment_id)
    return matches


def _selected_worker_assignment(
    payload: Mapping[str, Any],
    task: Mapping[str, Any],
    data_dir: Path,
    plugin_root: Path,
) -> Optional[_WorkerProjection]:
    """Return only the controller's host-isolation-safe worker projection."""

    candidates = _persisted_assignment_candidates(payload, task)
    if len(candidates) != 1:
        return None
    _import_controller(plugin_root)

    def unavailable_secret(_secret_id: str) -> bytes:
        raise RuntimeError("secret resolution is unavailable to Hooks")

    try:
        from dev_flow import (
            orchestration_controller_service,
            resolve_loaded_task_workflow,
            validate_worker_assignment,
        )
        resolution = resolve_loaded_task_workflow(
            task, purpose="inspection"
        )
        service = orchestration_controller_service(
            secret_resolver=unavailable_secret
        )
        view = service.worker_assignment_view(
            str(task.get("task_id")),
            candidates[0],
            data_dir=data_dir,
        ).as_dict()
    except Exception:
        return None
    assignment = view.get("assignment")
    dispatch_mode = view.get("dispatch_mode")
    blocker_codes = view.get("blocker_codes")
    if not isinstance(assignment, Mapping):
        return None
    try:
        value = validate_worker_assignment(assignment).as_dict()
    except Exception:
        return None
    expected_mode = (
        "parallel-writable-worker"
        if value.get("write_policy") == "scoped-write"
        else "parallel-read-only-worker"
    )
    if (
        dispatch_mode != expected_mode
        or blocker_codes not in ([], ())
        or value.get("assignment_id") != candidates[0]
        or value.get("task_id") != task.get("task_id")
        or value.get("workflow_bundle_sha256")
        != resolution.get("bundle_sha256")
    ):
        return None
    revision = task.get("revision")
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or value.get("expected_revision") != revision
    ):
        return None
    return _WorkerProjection(value, str(dispatch_mode))


def _worker_assignment_context(
    projection: _WorkerProjection,
) -> str:
    # The controller view is released only after its persisted host-isolation
    # decision permits parallel dispatch. The validated assignment schema
    # contains worker capabilities but no manager capability, controller
    # mutation tool, or plugin-data locator.
    payload = {
        "contract": "dev-flow-subagent-assignment-context/v1",
        "assignment": dict(projection.assignment),
        "dispatch_mode": projection.dispatch_mode,
        "authority": "candidate-output-only",
    }
    context = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(context.encode("utf-8")) > WORKER_ASSIGNMENT_CONTEXT_BUDGET:
        raise ValueError("worker assignment context exceeds its byte budget")
    return context


def _manager_serial_fallback_context(
    task: Mapping[str, Any],
) -> str:
    """Return bounded, non-authoritative guidance without controller secrets."""

    payload = {
        "contract": "dev-flow-subagent-serial-fallback/v1",
        "task_id": _render(task.get("task_id"), "unknown"),
        "revision": (
            task.get("revision")
            if isinstance(task.get("revision"), int)
            and not isinstance(task.get("revision"), bool)
            else 0
        ),
        "dispatch_mode": "manager-serial",
        "owner": "manager",
        "authority": "none",
        "instruction": (
            "No writable worker assignment was released. Return control; "
            "the manager owns serial execution."
        ),
    }
    context = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(context.encode("utf-8")) > SERIAL_FALLBACK_CONTEXT_BUDGET:
        raise ValueError("serial fallback context exceeds its byte budget")
    return context


def _structured_node_result(
    payload: Mapping[str, Any],
    assignment: Mapping[str, Any],
    plugin_root: Path,
) -> Optional[Mapping[str, Any]]:
    candidates: list[object] = [
        payload.get("node_result"),
        payload.get("structured_result"),
        payload.get("agent_result"),
        payload.get("result"),
    ]
    message = payload.get("last_assistant_message")
    if isinstance(message, str) and len(message.encode("utf-8")) <= 8192:
        try:
            candidates.append(json.loads(message))
        except (TypeError, ValueError):
            pass
    _import_controller(plugin_root)
    try:
        from dev_flow import validate_orchestration_node_result
    except Exception:
        return None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        try:
            encoded = json.dumps(
                candidate,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            continue
        if len(encoded) > 2048:
            continue
        try:
            validated = validate_orchestration_node_result(candidate)
        except Exception:
            continue
        expected = {
            "task_id": assignment.get("task_id"),
            "workflow_bundle_sha256": assignment.get(
                "workflow_bundle_sha256"
            ),
            "node_instance_id": assignment.get("node_instance_id"),
            "attempt": assignment.get("attempt"),
            "assignment_id": assignment.get("assignment_id"),
            "repository_id": assignment.get("repository_id"),
            "map_epoch": assignment.get("map_epoch"),
        }
        if all(validated.get(key) == value for key, value in expected.items()):
            return validated
    return None


def _subagent_continuation() -> dict[str, Any]:
    return {
        "decision": "block",
        "reason": (
            "Dev Flow requires one canonical dev-flow-node-result/v1 JSON "
            "object (<=2048 UTF-8 bytes; summary <=512) for the exact "
            "assignment before this subagent may stop. Continue and emit "
            "the structured result; the Hook will not commit workflow state."
        ),
    }


def handle(
    payload: Mapping[str, Any],
    environ: Mapping[str, str],
    *,
    fallback_root: Optional[Path] = None,
    data_dir_from_cli: bool = False,
) -> Optional[dict[str, Any]]:
    event = str(payload.get("hook_event_name", ""))
    if event == "PostCompact":
        # Codex 0.145 accepts only the common Hook output fields for
        # PostCompact; hookSpecificOutput.additionalContext is not part of
        # this event's wire contract.  A successful empty stdout is the
        # documented no-op.  SessionStart(source=compact) performs the actual
        # developer-context restoration immediately after compaction.
        return None
    plugin = _resolve_plugin_context(
        environ,
        fallback_root=fallback_root,
        data_dir_from_cli=data_dir_from_cli,
    )
    if plugin.diagnostic is not None:
        if event in {
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
        }:
            return _environment_diagnostic(event, plugin.diagnostic)
        return None
    assert plugin.root is not None
    assert plugin.data_dir is not None
    assert plugin.controller is not None
    data_dir = plugin.data_dir
    cwd = _path(str(payload.get("cwd") or os.getcwd()))
    tool_input_value = payload.get("tool_input")
    tool_input = tool_input_value if isinstance(tool_input_value, Mapping) else {}
    raw_workdir = tool_input.get("workdir")
    if isinstance(raw_workdir, str) and raw_workdir.strip():
        workdir = _path(raw_workdir.strip(), cwd)
    else:
        workdir = cwd
    task = load_active_task(data_dir, workdir, plugin.root)
    if task is None and workdir != cwd:
        task = load_active_task(data_dir, cwd, plugin.root)

    if task is not None and task.get("_active_task_ambiguity") is True:
        message = _active_task_ambiguity_context(task)
        if event == "PreToolUse":
            return _deny(message)
        if event in {"SessionStart", "UserPromptSubmit"}:
            return _checkpointed_context_output(
                event, message, message, payload, data_dir
            )
        return None

    candidates = [workdir] if workdir == cwd else [workdir, cwd]
    in_scope = in_configured_scope(
        data_dir, environ, *candidates, plugin_root=plugin.root
    )
    # Outside the configured scope the plugin must look uninstalled.  An active
    # task still owns its own directories, so narrowing the scope mid-flight
    # cannot silently drop that task's checkpoint or guardrails.
    if task is None and not in_scope:
        return None

    if event == "SubagentStart":
        if task is None:
            return None
        projection = _selected_worker_assignment(
            payload, task, data_dir, plugin.root
        )
        if (
            projection is None
            and _payload_string(
                payload,
                "assignment_id",
                "host_assignment_id",
                "agent_id",
                "agent_type",
            )
            is None
        ):
            return None
        try:
            context = (
                _worker_assignment_context(projection)
                if projection is not None
                else _manager_serial_fallback_context(task)
            )
        except Exception:
            context = _manager_serial_fallback_context(task)
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        }
    if event == "SubagentStop":
        if task is None:
            return None
        projection = _selected_worker_assignment(
            payload, task, data_dir, plugin.root
        )
        if projection is None:
            return None
        if (
            _structured_node_result(
                payload, projection.assignment, plugin.root
            )
            is not None
        ):
            return None
        return _subagent_continuation()
    if event == "PreCompact":
        if task is None:
            return None
        context, identity = build_locator_context(
            task, data_dir, plugin.controller
        )
        checkpoint = _pending_checkpoint(
            payload, data_dir, context, identity
        )
        return _HookOutput({}, checkpoint)
    if event == "SessionStart":
        if task is not None:
            context, identity = build_locator_context(
                task, data_dir, plugin.controller
            )
            checkpoint_context = context
        else:
            context = build_bootstrap_context(
                data_dir, plugin.controller
            )
            checkpoint_context = build_compact_bootstrap_context(
                data_dir, plugin.controller
            )
            identity = None
        return _checkpointed_context_output(
            event,
            context,
            checkpoint_context,
            payload,
            data_dir,
            identity,
        )
    if event == "UserPromptSubmit":
        if task is not None:
            context, identity = build_locator_context(
                task, data_dir, plugin.controller
            )
        else:
            context = build_compact_bootstrap_context(
                data_dir, plugin.controller
            )
            identity = None
        return _checkpointed_context_output(
            event, context, context, payload, data_dir, identity
        )
    if event != "PreToolUse":
        return None

    tool_name = str(payload.get("tool_name", "")).lower()
    if tool_name in {"apply_patch", "edit", "write"}:
        if task is not None:
            reason = _write_denial_reason(
                task,
                data_dir,
                tool_name,
                tool_input,
                workdir,
                workdir.is_dir(),
            )
            if reason:
                return _deny(reason)
        return None
    if tool_name not in {"bash", "exec_command", "shell"}:
        return None
    # Workflow command policy is scoped to an active task. Installing the
    # plugin must not alter unrelated Codex sessions or ordinary Git work.
    if task is None:
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        command = tool_input.get("cmd")
    if not isinstance(command, str):
        return None
    reason = command_denial_reason(
        command, workdir, task, data_dir, plugin.controller
    )
    return _deny(reason) if reason else None


def _cli_data_dir(argv: Sequence[str]) -> Optional[str]:
    for index, arg in enumerate(argv):
        if arg == "--data-dir" and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith("--data-dir="):
            return arg.split("=", 1)[1]
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        # Codex global hook registrations run without PLUGIN_DATA in the
        # environment, so the installer passes --data-dir explicitly; the
        # argument outranks any inherited variable.
        environ: Mapping[str, str] = os.environ
        data_dir = _cli_data_dir(sys.argv[1:])
        if data_dir is not None:
            environ = {**os.environ, "PLUGIN_DATA": data_dir}
        output = (
            handle(
                payload,
                environ,
                fallback_root=Path(__file__).resolve().parents[1]
                if data_dir is not None
                else None,
                data_dir_from_cli=data_dir is not None,
            )
            if isinstance(payload, Mapping)
            else None
        )
    except Exception:
        # Hooks are an auxiliary defense; malformed state must not disable Codex.
        return 0
    try:
        if output is not None:
            encoded = json.dumps(
                output, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            written = sys.stdout.buffer.write(encoded)
            if written is not None and written != len(encoded):
                raise OSError("incomplete hook protocol write")
            sys.stdout.buffer.flush()
    except Exception:
        # A hook protocol/stream failure must remain advisory and must never
        # emit a partial denial after an internal exception.
        return 0
    if isinstance(output, _HookOutput) and output.pending_checkpoint is not None:
        try:
            _write_checkpoint(output.pending_checkpoint)
        except Exception:
            # Checkpoint persistence is a token optimization only.  A failure
            # must never alter hook output or block the Codex session.
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
