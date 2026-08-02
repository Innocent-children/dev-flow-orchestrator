"""JSON command-line adapter for the V5 controller."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .controller import Controller
from .model import DevFlowError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DevFlowError("ARGUMENT_INVALID", message)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="dev-flow")
    parser.add_argument("--data-dir", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--requirement", required=True)
    start.add_argument(
        "--workflow",
        required=True,
        help="built-in workflow id (lite) or absolute path to a workflow file",
    )
    start.add_argument("--repo", required=True, help="absolute repository path")
    start.add_argument("--task-id")

    show = commands.add_parser("show")
    show.add_argument("task_id")

    next_action = commands.add_parser("next")
    next_action.add_argument("task_id")

    apply_action = commands.add_parser("apply")
    apply_action.add_argument("task_id")
    apply_action.add_argument("--action", required=True)
    apply_action.add_argument("--payload-json", default="{}")

    cancel = commands.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", required=True)

    list_action = commands.add_parser("list")

    return parser


def _dispatch(arguments: argparse.Namespace) -> dict:
    controller = Controller(arguments.data_dir)
    if arguments.command == "start":
        state = controller.start(
            requirement=arguments.requirement,
            workflow=arguments.workflow,
            repository=arguments.repo,
            task_id=arguments.task_id,
        )
        return {
            "ok": True,
            "command": "start",
            "task": state.as_dict(),
        }
    if arguments.command == "show":
        state = controller.show(arguments.task_id)
        return {
            "ok": True,
            "command": "show",
            "task": state.as_dict(),
        }
    if arguments.command == "next":
        return {
            "ok": True,
            "command": "next",
            "projection": controller.next(arguments.task_id),
        }
    if arguments.command == "apply":
        try:
            payload = json.loads(arguments.payload_json)
        except ValueError as exc:
            raise DevFlowError(
                "ARGUMENT_JSON_INVALID",
                "--payload-json is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise DevFlowError(
                "ARGUMENT_JSON_INVALID",
                "--payload-json must be an object",
            )
        return {
            "ok": True,
            "command": "apply",
            **controller.apply(arguments.task_id, arguments.action, payload),
        }
    if arguments.command == "cancel":
        return {
            "ok": True,
            "command": "cancel",
            **controller.cancel(arguments.task_id, reason=arguments.reason),
        }
    if arguments.command == "list":
        return {
            "ok": True,
            "command": "list",
            "tasks": [state.as_dict() for state in controller.list_tasks()],
        }
    raise DevFlowError(
        "ACTION_UNSUPPORTED",
        "action is not implemented by this runtime",
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        result = _dispatch(arguments)
        exit_code = 0
    except DevFlowError as exc:
        result = exc.as_dict()
        exit_code = 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
