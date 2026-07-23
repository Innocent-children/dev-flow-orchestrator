#!/usr/bin/env python3
"""Inject Dev Flow state and provide best-effort Codex tool guardrails."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


CONTROLLER = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"


STAGES = (
    "INTAKE",
    "PREFLIGHTED",
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
)
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}
DEFAULT_PROTECTED_BRANCHES = {"main", "master", "trunk"}
NEXT_ACTIONS = {
    "INTAKE": "run preflight",
    "PREFLIGHTED": "approve and capture the baseline",
    "BASELINED": "index every repository",
    "INDEXED": "review change impact and select a route",
    "IMPACT_REVIEW": "approve the selected route",
    "ROUTE_APPROVED": "approve and prepare the managed workspace",
    "WORKSPACE_READY": "create or refresh every workspace index, then create the implementation plan",
    "PLANNING": "create and approve the plan, then refresh workspace indexes before implementation",
    "IMPLEMENTING": "implement the approved scope, then refresh workspace indexes before verification",
    "VERIFYING": "run checks, refresh workspace indexes, then capture and independently review the snapshot",
    "REVIEWING": "approve the review and then finalize",
    "FINALIZING": "complete the handoff",
    "DONE": "no further action",
    "BLOCKED": "resolve the recorded blocker",
}
LITE_NEXT_ACTIONS = {
    "INTAKE": "run preflight",
    "PREFLIGHTED": "present the in-place scope and obtain the lite approval",
    "IMPLEMENTING": "implement the approved scope inside the source checkout",
    "VERIFYING": "run checks and record results, then finish",
    "DONE": "no further action",
    "BLOCKED": "resolve the recorded blocker",
}
PENDING_GATES = {
    "PREFLIGHTED": ("baseline-fetch", "baseline fetch/materialization approval"),
    "IMPACT_REVIEW": ("route", "route approval"),
    "ROUTE_APPROVED": ("workspace", "workspace approval"),
    "PLANNING": ("plan", "planning approval"),
    "REVIEWING": ("review", "review approval"),
    "BLOCKED": ("unblock", "unblock decision"),
}
LITE_PENDING_GATES = {
    "PREFLIGHTED": ("lite", "lite in-place approval"),
    "BLOCKED": ("unblock", "unblock decision"),
}

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SEPARATOR_CHARS = set(";&|()<>\n{}")
_LEADING_WORDS = {"!", "if", "then", "elif", "while", "until", "do"}
_WRAPPERS = {"command", "env", "exec", "nice", "nohup", "sudo", "time"}
_SHELLS = {"bash", "dash", "ksh", "sh", "zsh"}
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


def _import_controller() -> None:
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))


def in_configured_scope(
    data_dir: Path, environ: Mapping[str, str], *candidates: Path
) -> bool:
    """Report whether any candidate directory is inside the configured scope.

    An unreadable configuration or an unavailable controller fails open, so a
    broken scope file never hides the workflow from the directories that need
    it.  The controller owns the matching rules; this only aggregates them.
    """

    _import_controller()
    try:
        from dev_flow import evaluate_scope, resolve_scope

        scope = resolve_scope(data_dir, environ)
        return any(
            evaluate_scope(candidate, scope).get("in_scope") for candidate in candidates
        )
    except Exception:
        return True


def load_active_task(data_dir: Path, cwd: Path) -> Optional[dict[str, Any]]:
    """Use the controller's read-only lookup and fail open on any mismatch."""

    _import_controller()
    try:
        from dev_flow import find_active_task_for_cwd, load_state

        task = find_active_task_for_cwd(cwd=cwd, data_dir=data_dir)
        if task is None:
            relative = cwd.relative_to(data_dir / "tasks")
            if len(relative.parts) >= 2 and relative.parts[1] == "artifacts":
                candidate = load_state(relative.parts[0], data_dir=data_dir)
                if candidate.get("status") not in {"DONE", "CANCELLED"}:
                    task = candidate
    except Exception:
        return None
    return dict(task) if isinstance(task, Mapping) else None


def _stage(task: Mapping[str, Any]) -> str:
    value = task.get("status", task.get("stage", "UNKNOWN"))
    return str(value).upper()


def _flow(task: Mapping[str, Any]) -> str:
    value = task.get("flow")
    return value if value in {"full", "lite"} else "full"


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


def _pending_gate(task: Mapping[str, Any]) -> str:
    explicit = task.get("pending_gate", task.get("pendingGate"))
    if explicit not in (None, ""):
        return _render(explicit, "none")
    gates = LITE_PENDING_GATES if _flow(task) == "lite" else PENDING_GATES
    gate = gates.get(_stage(task))
    if gate is None:
        return "none"
    key, label = gate
    approvals = task.get("approvals")
    if isinstance(approvals, Mapping) and key in approvals:
        return "none"
    return label


def _index_stage(task: Mapping[str, Any]) -> str:
    stage = _stage(task)
    if stage == "BLOCKED":
        blocked = task.get("blocked")
        if isinstance(blocked, Mapping):
            stage = str(blocked.get("from_status", "BLOCKED")).upper()
    return stage


def _selected_index_role(task: Mapping[str, Any]) -> Optional[str]:
    if _flow(task) == "lite":
        return None
    stage = _index_stage(task)
    if stage in {
        "BASELINED",
        "INDEXED",
        "IMPACT_REVIEW",
        "ROUTE_APPROVED",
    }:
        return "baseline"
    if stage in {
        "WORKSPACE_READY",
        "PLANNING",
        "IMPLEMENTING",
        "VERIFYING",
        "REVIEWING",
        "FINALIZING",
        "DONE",
    }:
        return "workspace"
    return None


def _index_selection_context(task: Mapping[str, Any]) -> tuple[str, str]:
    role = _selected_index_role(task)
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


def _controller_prefix(data_dir: Path) -> str:
    return (
        f"python3 {shlex.quote(str(CONTROLLER))} "
        f"--data-dir {shlex.quote(str(data_dir))}"
    )


def build_bootstrap_context(data_dir: Path) -> str:
    prefix = _controller_prefix(data_dir)
    return "\n".join(
        (
            "Dev Flow controller bootstrap:",
            f"- Controller: {CONTROLLER}",
            f"- Data directory: {data_dir}",
            f"- Bootstrap command: {prefix} list",
            f"Every controller call must explicitly include "
            f"--data-dir {shlex.quote(str(data_dir))}; do not rely on environment fallback.",
        )
    )


def build_context(
    task: Mapping[str, Any], data_dir: Path, in_scope: bool = True
) -> str:
    stage = _stage(task)
    flow = _flow(task)
    prefix = _controller_prefix(data_dir)
    task_id = _render(task.get("task_id"), "unknown")
    index_role, index_projects = _index_selection_context(task)
    next_actions = LITE_NEXT_ACTIONS if flow == "lite" else NEXT_ACTIONS
    lines = [
        "Dev Flow active-task checkpoint:",
        f"- Active task: {task_id}",
        f"- Flow: {'lite (in place, no managed worktree)' if flow == 'lite' else 'full'}",
        f"- Stage: {stage}",
        f"- Route: {_render(task.get('route'), 'not selected')}",
        f"- Pending gate: {_pending_gate(task)}",
        "- codebase-memory selection: explicit project parameter; never automatic",
        f"- Active index role: {index_role}",
        f"- Active index projects: {index_projects}",
        f"- Next action: "
        f"{_render(task.get('next_action'), next_actions.get(stage, 'inspect task state'))}",
        f"- Controller: {CONTROLLER}",
        f"- Data directory: {data_dir}",
        f"- Resume command: {prefix} show --task {shlex.quote(task_id)}",
    ]
    if not in_scope:
        lines.append(
            "- Directory scope: outside the configured scope; this active task "
            "keeps the hooks enabled here"
        )
    lines.append(
        f"Every controller call must explicitly include "
        f"--data-dir {shlex.quote(str(data_dir))}; do not rely on environment fallback."
    )
    return "\n".join(lines)


def _stage_allows_writes(task: Mapping[str, Any]) -> bool:
    stage = _stage(task)
    if _flow(task) == "lite":
        return stage in {"IMPLEMENTING", "VERIFYING"}
    return stage not in {"BLOCKED", "CANCELLED", "DONE"} and STAGE_INDEX.get(
        stage, -1
    ) >= STAGE_INDEX["WORKSPACE_READY"]


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
    if _stage_allows_writes(task):
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


def _segments(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n{}")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return []
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and all(char in _SEPARATOR_CHARS for char in token):
            if current:
                result.append(current)
                current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def _basename(token: str) -> str:
    return token.rsplit("/", 1)[-1].lower()


def _simple_command(tokens: Sequence[str]) -> tuple[Optional[str], list[str]]:
    index = 0
    while index < len(tokens) and (tokens[index] in _LEADING_WORDS or _ASSIGNMENT.match(tokens[index])):
        index += 1
    while index < len(tokens):
        name = _basename(tokens[index])
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


def _git_invocations(command: str, cwd: Path, depth: int = 0) -> list[tuple[str, list[str], Path]]:
    if depth > 3:
        return []
    result: list[tuple[str, list[str], Path]] = []
    for segment in _segments(command):
        name, args = _simple_command(segment)
        if name == "git":
            parsed = _parse_git(args, cwd)
            if parsed is not None:
                result.append(parsed)
        elif name in _SHELLS:
            for index, argument in enumerate(args):
                if argument.startswith("-") and "c" in argument[1:] and index + 1 < len(args):
                    result.extend(_git_invocations(args[index + 1], cwd, depth + 1))
                    break
    return result


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
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return _normal_branch(result.stdout)
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
) -> Optional[str]:
    controller = _controller_prefix(data_dir)
    for subcommand, args, git_cwd in _git_invocations(command, cwd):
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


def handle(payload: Mapping[str, Any], environ: Mapping[str, str]) -> Optional[dict[str, Any]]:
    raw_data_dir = environ.get("PLUGIN_DATA")
    if not raw_data_dir:
        return None
    data_dir = _path(raw_data_dir)
    cwd = _path(str(payload.get("cwd") or os.getcwd()))
    event = str(payload.get("hook_event_name", ""))
    tool_input_value = payload.get("tool_input")
    tool_input = tool_input_value if isinstance(tool_input_value, Mapping) else {}
    raw_workdir = tool_input.get("workdir")
    if isinstance(raw_workdir, str) and raw_workdir.strip():
        workdir = _path(raw_workdir.strip(), cwd)
    else:
        workdir = cwd
    task = load_active_task(data_dir, workdir)
    if task is None and workdir != cwd:
        task = load_active_task(data_dir, cwd)

    candidates = [workdir] if workdir == cwd else [workdir, cwd]
    in_scope = in_configured_scope(data_dir, environ, *candidates)
    # Outside the configured scope the plugin must look uninstalled.  An active
    # task still owns its own directories, so narrowing the scope mid-flight
    # cannot silently drop that task's checkpoint or guardrails.
    if task is None and not in_scope:
        return None

    if event in {"SessionStart", "UserPromptSubmit"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": build_context(task, data_dir, in_scope)
                if task is not None
                else build_bootstrap_context(data_dir),
            }
        }
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
    reason = command_denial_reason(command, workdir, task, data_dir)
    return _deny(reason) if reason else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        output = handle(payload, os.environ) if isinstance(payload, Mapping) else None
    except Exception:
        # Hooks are an auxiliary defense; malformed state must not disable Codex.
        return 0
    if output is not None:
        json.dump(output, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
