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
from typing import Any, Mapping, NamedTuple, Optional, Sequence


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
    """Use the controller's read-only lookup and fail open on any mismatch."""

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
            f"Every controller call must explicitly include "
            f"--data-dir {_quote(str(data_dir))}; do not rely on environment fallback.",
        )
    )


def build_context(
    task: Mapping[str, Any],
    data_dir: Path,
    in_scope: bool = True,
    controller: Path = CONTROLLER,
) -> str:
    stage = _stage(task)
    flow = _flow(task)
    prefix = _controller_prefix(data_dir, controller)
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
        f"- Interpreter: {sys.executable}",
        f"- Controller: {controller}",
        f"- Data directory: {data_dir}",
        f"- Resume command: {prefix} show --task {_quote(task_id)}",
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


class _Inspection(NamedTuple):
    invocations: list[tuple[str, list[str], Path]]
    diagnostic: Optional[str]
    recognized_wrapper: bool
    parse_failed: bool


def _posix_segments(command: str) -> tuple[list[list[str]], Optional[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n{}")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError as exc:
        return [], f"POSIX shell payload has invalid quoting: {exc}"
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
    return result, None


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
    if dialect == "cmd":
        segments, error = _cmd_segments(command)
    elif dialect == "powershell":
        segments, error = _powershell_segments(command)
    else:
        segments, error = _posix_segments(command)
    if error is not None:
        diagnostic = _inspection_error(dialect, error) if strict else None
        return _Inspection([], diagnostic, False, True)
    return _inspect_tokens(segments, cwd, dialect, depth, strict)


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
    inspections = [primary]
    if not primary.recognized_wrapper:
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


def handle(
    payload: Mapping[str, Any],
    environ: Mapping[str, str],
    *,
    fallback_root: Optional[Path] = None,
    data_dir_from_cli: bool = False,
) -> Optional[dict[str, Any]]:
    event = str(payload.get("hook_event_name", ""))
    plugin = _resolve_plugin_context(
        environ,
        fallback_root=fallback_root,
        data_dir_from_cli=data_dir_from_cli,
    )
    if plugin.diagnostic is not None:
        if event in {"SessionStart", "UserPromptSubmit", "PreToolUse"}:
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

    candidates = [workdir] if workdir == cwd else [workdir, cwd]
    in_scope = in_configured_scope(
        data_dir, environ, *candidates, plugin_root=plugin.root
    )
    # Outside the configured scope the plugin must look uninstalled.  An active
    # task still owns its own directories, so narrowing the scope mid-flight
    # cannot silently drop that task's checkpoint or guardrails.
    if task is None and not in_scope:
        return None

    if event in {"SessionStart", "UserPromptSubmit"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": build_context(
                    task, data_dir, in_scope, plugin.controller
                )
                if task is not None
                else build_bootstrap_context(data_dir, plugin.controller),
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
            ).encode("utf-8")
            sys.stdout.buffer.write(encoded + b"\n")
    except Exception:
        # A hook protocol/stream failure must remain advisory and must never
        # emit a partial denial after an internal exception.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
