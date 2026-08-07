"""Small fail-open Codex Hook adapter for current task context."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Mapping, Optional, Sequence

from ._platform.paths import canonical_data_root, path_contains
from .controller import Controller
from .product import PLUGIN_DATA_NAMESPACE, RELEASE_VERSION


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-flow-hook")
    parser.add_argument("--data-dir")
    return parser


@dataclass(frozen=True)
class HookConfig:
    controller_argv: tuple
    state_data_dir: str
    protected_data_root: str


def _configuration(
    arguments: argparse.Namespace,
    controller_argv: Sequence[str],
) -> Optional[HookConfig]:
    if not controller_argv or any(
        not isinstance(item, str) or not item for item in controller_argv
    ):
        return None
    if arguments.data_dir:
        state_root = Path(arguments.data_dir).expanduser().resolve()
        protected_root = state_root
    else:
        plugin_data = os.environ.get("PLUGIN_DATA")
        if not plugin_data:
            return None
        protected_root = Path(plugin_data).expanduser().resolve()
        state_root = protected_root / PLUGIN_DATA_NAMESPACE
    return HookConfig(
        tuple(controller_argv),
        str(state_root),
        str(protected_root),
    )


def _powershell_literal(value: str) -> str:
    return "'{}'".format(value.replace("'", "''"))


def _controller_command(
    config: HookConfig,
    *,
    windows: Optional[bool] = None,
) -> str:
    arguments = (*config.controller_argv, "--data-dir", config.state_data_dir)
    if windows if windows is not None else os.name == "nt":
        return "& " + " ".join(_powershell_literal(item) for item in arguments)
    return shlex.join(arguments)


def _context(
    controller: Controller,
    cwd: str,
    config: HookConfig,
) -> str:
    diagnostics = controller.inventory_diagnostics()
    tasks = controller.tasks_for_path(cwd)
    locator = _controller_command(config)
    product_name = "Dev Flow {}".format(RELEASE_VERSION)
    if diagnostics:
        return (
            product_name
            + " current task inventory is unavailable; automatic discovery is "
            "disabled and new task admission remains blocked. diagnostics="
            + json.dumps(
                diagnostics,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + " locator="
            + locator
        )
    if not tasks:
        return (
            product_name
            + " is available. Invoke $follow-dev-flow, then use the "
            "injected controller locator with an official --workflow and one "
            "or more repeatable --repo values for user-prepared Git worktrees. "
            "The task keeps one current action for one Codex executor: "
            + locator
        )
    if len(tasks) > 1:
        task_ids = ", ".join(task.task_id for task in tasks)
        return (
            "Multiple current "
            + product_name
            + " tasks cover this directory: "
            + task_ids
            + ". Select one task explicitly with: "
            + locator
        )
    projection = controller.next(tasks[0].task_id)
    return (
        "Current "
        + product_name
        + " task. Invoke $follow-dev-flow and use only this "
        "controller locator. Execute its one current action across the exact "
        "repository set with one Codex; Git-changing operations remain "
        "user-owned. Do not edit task state directly. locator="
        + locator
        + " projection="
        + json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _deny(event: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Dev Flow task state is controller-owned; use the injected "
                "controller locator."
            ),
        }
    }


def _inside(candidate: Path, root: Path) -> bool:
    try:
        resolved = canonical_data_root(candidate)
    except OSError:
        resolved = candidate.expanduser().absolute()
    return path_contains(root, resolved)


def _shell_tokens(command: str) -> Optional[tuple]:
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars="|&;<>()",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return tuple(lexer)
    except ValueError:
        return None


def _is_shell_operator(token: str) -> bool:
    return bool(token) and all(char in "|&;<>()" for char in token)


def _is_exact_controller_invocation(
    command: str,
    config: HookConfig,
    *,
    windows: Optional[bool] = None,
) -> bool:
    if windows if windows is not None else os.name == "nt":
        prefix = _controller_command(config, windows=True)
        if not command.startswith(prefix):
            return False
        suffix = command[len(prefix):]
        return not any(marker in suffix for marker in (
            "\n", "\r", "`", "$(", ";", "|", "&", "<", ">",
        ))
    if any(marker in command for marker in ("\n", "\r", "`", "$(")):
        return False
    if re.search(r"\$(?:\{PLUGIN_DATA\}|PLUGIN_DATA\b)", command):
        return False
    tokens = _shell_tokens(command)
    if tokens is None or any(_is_shell_operator(token) for token in tokens):
        return False
    prefix = (
        *config.controller_argv,
        "--data-dir",
        config.state_data_dir,
    )
    return len(tokens) >= len(prefix) and tokens[:len(prefix)] == prefix


_PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add File|Update File|Delete File|Move to):\s*(.+?)\s*$"
)


def _apply_patch_paths(command: str, cwd: str) -> tuple:
    paths = []
    for line in command.splitlines():
        match = _PATCH_PATH.match(line)
        if match is None:
            continue
        candidate = Path(match.group(1)).expanduser()
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        paths.append(candidate)
    return tuple(paths)


def _command_references_protected_data(
    command: str,
    cwd: str,
    config: HookConfig,
) -> bool:
    if re.search(
        r"(?:\$(?:\{PLUGIN_DATA\}|PLUGIN_DATA\b)|\$env:PLUGIN_DATA\b|"
        r"\$\{env:PLUGIN_DATA\}|%PLUGIN_DATA%)",
        command,
        flags=re.IGNORECASE,
    ):
        return True
    root = Path(config.protected_data_root).resolve()
    if str(root) in command:
        return True
    tokens = _shell_tokens(command)
    if tokens is None:
        return False
    for token in tokens:
        if _is_shell_operator(token) or token.startswith("-"):
            continue
        if token.startswith(("/", "./", "../", "~")) or "/" in token:
            candidate = Path(token).expanduser()
            if not candidate.is_absolute():
                candidate = Path(cwd) / candidate
            if _inside(candidate, root):
                return True
    return False


def _guard_pre_tool_use(
    payload: Mapping[str, object],
    *,
    event: str,
    cwd: str,
    config: HookConfig,
) -> Optional[dict]:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, Mapping):
        return None
    normalized_name = tool_name.lower()
    command = tool_input.get("command")
    command_text = command if isinstance(command, str) else ""
    if normalized_name == "bash":
        if _is_exact_controller_invocation(command_text, config):
            return None
        if _command_references_protected_data(
            command_text, cwd, config
        ):
            return _deny(event)
        return None
    root = Path(config.protected_data_root).resolve()
    if normalized_name == "apply_patch":
        if any(
            _inside(candidate, root)
            for candidate in _apply_patch_paths(command_text, cwd)
        ):
            return _deny(event)
        if _command_references_protected_data(command_text, cwd, config):
            return _deny(event)
        return None
    if normalized_name in {"edit", "write"}:
        supplied_path = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(supplied_path, str):
            candidate = Path(supplied_path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(cwd) / candidate
            if _inside(candidate, root):
                return _deny(event)
    return None


def handle(
    payload: Mapping[str, object],
    *,
    config: HookConfig,
) -> Optional[dict]:
    event = payload.get("hook_event_name")
    if not isinstance(event, str):
        return None
    cwd = payload.get("cwd")
    effective_cwd = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    if event == "PreToolUse":
        guarded = _guard_pre_tool_use(
            payload,
            event=event,
            cwd=effective_cwd,
            config=config,
        )
        if guarded is not None:
            return guarded
    try:
        controller = Controller(config.state_data_dir)
        context = _context(controller, effective_cwd, config)
        if event in {"SessionStart", "UserPromptSubmit"}:
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            }
        if event != "PreToolUse":
            return None
        if controller.tasks_for_path(effective_cwd):
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": context,
                }
            }
    except Exception:
        # Hook failures never take authority away from the user or controller.
        return None
    return None


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    controller_argv: Optional[Sequence[str]] = None,
) -> int:
    try:
        arguments = _parser().parse_args(argv)
        plugin_root = Path(__file__).resolve().parents[2]
        launcher_name = (
            "dev_flow_python_launcher.cmd"
            if os.name == "nt"
            else "dev_flow_python_launcher"
        )
        config = _configuration(
            arguments,
            controller_argv
            or (
                str(plugin_root / "scripts" / launcher_name),
                str(plugin_root / "scripts" / "dev_flow.py"),
            ),
        )
        if config is None:
            return 0
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            return 0
        output = handle(
            payload,
            config=config,
        )
        if output is not None:
            sys.stdout.write(
                json.dumps(
                    output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            sys.stdout.flush()
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
