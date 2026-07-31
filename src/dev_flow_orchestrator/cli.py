"""JSON command-line adapter for the greenfield V4 controller."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .controller import Controller
from .model import DevFlowError
from .product import WORKFLOW_IDS, WORKSPACE_STRATEGIES


ROUTING_ID_MAX_BYTES = 256


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DevFlowError("ARGUMENT_INVALID", message)


def _routing_id(value: str) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise argparse.ArgumentTypeError(
            "conversation routing IDs must be valid UTF-8"
        ) from exc
    if not value.strip() or len(encoded) > ROUTING_ID_MAX_BYTES:
        raise argparse.ArgumentTypeError(
            "conversation routing IDs must be 1..{} UTF-8 bytes".format(
                ROUTING_ID_MAX_BYTES
            )
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="dev-flow")
    parser.add_argument("--data-dir", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--requirement", required=True)
    start.add_argument("--workflow", choices=WORKFLOW_IDS, required=True)
    start.add_argument(
        "--workspace-strategy",
        choices=WORKSPACE_STRATEGIES,
        required=True,
    )
    start.add_argument("--repo", action="append", required=True)
    start.add_argument("--task-id")

    show = commands.add_parser("show")
    show.add_argument("task_id")

    preflight = commands.add_parser("preflight")
    preflight.add_argument("task_id")
    preflight.add_argument("--expected-revision", type=int, required=True)

    next_action = commands.add_parser("next")
    next_action.add_argument("task_id")
    next_action.add_argument("--session-id", type=_routing_id)

    apply_action = commands.add_parser("apply")
    apply_action.add_argument("task_id")
    apply_action.add_argument("--action", required=True)
    apply_action.add_argument("--expected-revision", type=int, required=True)
    apply_action.add_argument("--payload-json", default="{}")
    apply_action.add_argument("--session-id", type=_routing_id)
    apply_action.add_argument("--request-turn-id", type=_routing_id)

    effect_inspect = commands.add_parser("effect-inspect")
    effect_inspect.add_argument("task_id")

    effect_recover = commands.add_parser("effect-recover")
    effect_recover.add_argument("task_id")
    effect_recover.add_argument("--execution-id", required=True)
    effect_recover.add_argument(
        "--mode",
        choices=("settle", "abandon", "reattach", "compensate"),
        required=True,
    )
    effect_recover.add_argument("--session-id", type=_routing_id)
    effect_recover.add_argument("--request-turn-id", type=_routing_id)

    return parser


def _dispatch(arguments: argparse.Namespace) -> dict:
    controller = Controller(arguments.data_dir)
    if arguments.command == "start":
        state = controller.start(
            requirement=arguments.requirement,
            workflow=arguments.workflow,
            workspace_strategy=arguments.workspace_strategy,
            repositories=arguments.repo,
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
    if arguments.command == "preflight":
        receipt = controller.preflight(
            arguments.task_id,
            arguments.expected_revision,
        )
        return {
            "ok": True,
            "command": "preflight",
            "receipt": receipt.as_dict(),
        }
    if arguments.command == "next":
        return {
            "ok": True,
            "command": "next",
            "projection": controller.next(
                arguments.task_id,
                session_id=arguments.session_id,
            ),
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
        receipt = controller.apply(
            arguments.task_id,
            arguments.expected_revision,
            arguments.action,
            payload,
            session_id=arguments.session_id,
            request_turn_id=arguments.request_turn_id,
        )
        return {
            "ok": True,
            "command": "apply",
            "receipt": receipt.as_dict(),
        }
    if arguments.command == "effect-inspect":
        return {
            "ok": True,
            "command": "effect-inspect",
            "inspection": controller.effect_inspect(arguments.task_id),
        }
    if arguments.command == "effect-recover":
        return {
            "ok": True,
            "command": "effect-recover",
            "recovery": controller.recover_effect(
                arguments.task_id,
                arguments.execution_id,
                arguments.mode,
                session_id=arguments.session_id,
                request_turn_id=arguments.request_turn_id,
            ),
        }
    raise DevFlowError(
        "ACTION_UNSUPPORTED",
        "action is not implemented by the greenfield runtime",
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
