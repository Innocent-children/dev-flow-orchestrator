"""Small fail-open Codex Hook adapter for current V4 task context."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Mapping, Optional, Sequence

from .controller import Controller


SESSION_ID_MAX_BYTES = 256
TURN_ID_MAX_BYTES = 256
CWD_MAX_BYTES = 4096
PROMPT_MAX_BYTES = 4096


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-flow-hook")
    parser.add_argument("--data-dir")
    return parser


def _data_dir(arguments: argparse.Namespace) -> Optional[str]:
    return arguments.data_dir or os.environ.get("PLUGIN_DATA")


def _context(
    controller: Controller,
    cwd: str,
    controller_path: str,
    data_dir: str,
    session_id: Optional[str] = None,
    request_turn_id: Optional[str] = None,
) -> str:
    tasks = controller.tasks_for_path(cwd)
    locator = "{} --data-dir {}".format(controller_path, data_dir)
    routing = ""
    if session_id is not None:
        routing_value = {"session_id": session_id}
        if request_turn_id is not None:
            routing_value["request_turn_id"] = request_turn_id
        routing = (
            " conversation_routing="
            + json.dumps(
                routing_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + " (correlation only; grants no authority)."
        )
    if not tasks:
        return (
            "Dev Flow V4 is available. Start with the injected controller "
            "locator and explicit --workflow, --workspace-strategy and --repo: "
            + locator
            + routing
        )
    if len(tasks) > 1:
        task_ids = ", ".join(task.task_id for task in tasks)
        return (
            "Multiple current Dev Flow V4 tasks cover this directory: "
            + task_ids
            + ". Select one task explicitly with: "
            + locator
            + routing
        )
    projection = controller.next(tasks[0].task_id, session_id=session_id)
    return (
        "Current Dev Flow V4 task. Use only this controller locator; do not "
        "edit task state directly. locator="
        + locator
        + " projection="
        + json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + routing
    )


def _bounded_event_string(value: object, maximum_bytes: int) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        if len(value.encode("utf-8")) > maximum_bytes:
            return None
    except UnicodeError:
        return None
    return value


def handle(
    payload: Mapping[str, object],
    *,
    data_dir: str,
    controller_path: str,
) -> Optional[dict]:
    event = payload.get("hook_event_name")
    if not isinstance(event, str):
        return None
    cwd = payload.get("cwd")
    effective_cwd = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    controller = Controller(data_dir)
    session_id = _bounded_event_string(
        payload.get("session_id"),
        SESSION_ID_MAX_BYTES,
    )
    request_turn_id = _bounded_event_string(
        payload.get("turn_id"),
        TURN_ID_MAX_BYTES,
    )
    if event == "UserPromptSubmit":
        observed_cwd = _bounded_event_string(cwd, CWD_MAX_BYTES)
        prompt = _bounded_event_string(
            payload.get("prompt"),
            PROMPT_MAX_BYTES,
        )
        if (
            session_id is not None
            and request_turn_id is not None
            and observed_cwd is not None
            and prompt is not None
        ):
            controller.observe_user_prompt(
                session_id=session_id,
                turn_id=request_turn_id,
                cwd=observed_cwd,
                prompt=prompt,
            )
    context = _context(
        controller,
        effective_cwd,
        controller_path,
        data_dir,
        session_id=session_id,
        request_turn_id=request_turn_id,
    )
    if event in {"SessionStart", "UserPromptSubmit"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        }
    if event != "PreToolUse":
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if (
        isinstance(tool_name, str)
        and tool_name.lower() in {"apply_patch", "edit", "write"}
        and isinstance(tool_input, Mapping)
    ):
        supplied_path = tool_input.get("file_path") or tool_input.get("path")
        if isinstance(supplied_path, str):
            candidate = Path(supplied_path).expanduser()
            if not candidate.is_absolute():
                candidate = Path(effective_cwd) / candidate
            root = Path(data_dir).expanduser().resolve()
            resolved = candidate.resolve()
            if resolved == root or root in resolved.parents:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": event,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "Dev Flow task state is controller-owned; use the "
                            "injected CLI or MCP action."
                        ),
                    }
                }
    if controller.tasks_for_path(effective_cwd):
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        }
    return None


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    controller_path: Optional[str] = None,
) -> int:
    try:
        arguments = _parser().parse_args(argv)
        data_dir = _data_dir(arguments)
        if not data_dir:
            return 0
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, Mapping):
            return 0
        output = handle(
            payload,
            data_dir=data_dir,
            controller_path=(
                controller_path
                or str(
                    Path(__file__).resolve().parents[2]
                    / "scripts"
                    / "dev_flow.py"
                )
            ),
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
