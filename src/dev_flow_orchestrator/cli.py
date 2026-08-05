"""Strict JSON command-line adapter for the current controller."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Mapping, Optional, Sequence

from .controller import Controller
from .model import DevFlowError, strict_json_loads


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
        help=(
            "official id (lite, feature, bugfix, investigation, refactor, full) "
            "or an absolute current-version workflow path"
        ),
    )
    start.add_argument(
        "--repo",
        action="append",
        required=True,
        metavar="ROOT",
        help=(
            "absolute root of a user-prepared Git worktree; repeat for an "
            "exact repository set"
        ),
    )
    start.add_argument("--task-id")
    start.add_argument("--contract-json")

    show = commands.add_parser("show")
    show.add_argument("task_id")

    next_action = commands.add_parser("next")
    next_action.add_argument("task_id")

    apply_action = commands.add_parser("apply")
    apply_action.add_argument("task_id")
    apply_action.add_argument("--action", required=True)
    apply_action.add_argument("--payload-json", default="{}")
    apply_action.add_argument("--binding-json", required=True)

    revision = commands.add_parser("revise-contract")
    revision.add_argument("task_id")
    revision.add_argument("--contract-json", required=True)
    revision.add_argument("--ownership-claims-json")
    revision.add_argument("--reason", required=True)
    revision.add_argument("--actor-label", required=True)

    decision = commands.add_parser("decide")
    decision.add_argument("task_id")
    decision.add_argument("--decision-json", required=True)

    disposition = commands.add_parser("dispose-finding")
    disposition.add_argument("task_id")
    disposition.add_argument("--disposition-json", required=True)
    disposition.add_argument("--actor-authorized", action="store_true")

    cancel = commands.add_parser("cancel")
    cancel.add_argument("task_id")
    cancel.add_argument("--reason", required=True)

    commands.add_parser("list")
    return parser


def _json_object(value: str, flag: str) -> Mapping[str, object]:
    try:
        parsed = strict_json_loads(value)
    except (UnicodeError, ValueError) as exc:
        raise DevFlowError(
            "ARGUMENT_JSON_INVALID",
            "{} is not strict JSON".format(flag),
        ) from exc
    if not isinstance(parsed, dict):
        raise DevFlowError(
            "ARGUMENT_JSON_INVALID",
            "{} must be a JSON object".format(flag),
        )
    return parsed


def _dispatch(arguments: argparse.Namespace) -> dict:
    controller = Controller(arguments.data_dir)
    if arguments.command == "start":
        contract = (
            None
            if arguments.contract_json is None
            else _json_object(arguments.contract_json, "--contract-json")
        )
        state = controller.start(
            requirement=arguments.requirement,
            workflow=arguments.workflow,
            repositories=arguments.repo,
            task_id=arguments.task_id,
            contract=contract,
        )
        return {"ok": True, "command": "start", "task": state.as_dict()}
    if arguments.command == "show":
        return {
            "ok": True,
            "command": "show",
            "task": controller.show_view(arguments.task_id),
        }
    if arguments.command == "next":
        return {
            "ok": True,
            "command": "next",
            "projection": controller.next(arguments.task_id),
        }
    if arguments.command == "apply":
        payload = _json_object(arguments.payload_json, "--payload-json")
        binding = _json_object(arguments.binding_json, "--binding-json")
        return {
            "ok": True,
            "command": "apply",
            **controller.apply(
                arguments.task_id,
                arguments.action,
                payload,
                binding=binding,
            ),
        }
    if arguments.command == "revise-contract":
        return {
            "ok": True,
            "command": "revise-contract",
            **controller.revise_contract(
                arguments.task_id,
                contract=_json_object(arguments.contract_json, "--contract-json"),
                ownership_claims=(
                    None
                    if arguments.ownership_claims_json is None
                    else _json_object(
                        arguments.ownership_claims_json,
                        "--ownership-claims-json",
                    )
                ),
                reason=arguments.reason,
                actor_label=arguments.actor_label,
            ),
        }
    if arguments.command == "decide":
        return {
            "ok": True,
            "command": "decide",
            **controller.decide(
                arguments.task_id,
                decision=_json_object(arguments.decision_json, "--decision-json"),
            ),
        }
    if arguments.command == "dispose-finding":
        return {
            "ok": True,
            "command": "dispose-finding",
            **controller.dispose_finding(
                arguments.task_id,
                disposition=_json_object(
                    arguments.disposition_json,
                    "--disposition-json",
                ),
                actor_authorized=arguments.actor_authorized,
            ),
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
    raise DevFlowError("ACTION_UNSUPPORTED", "command is not implemented")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        result = _dispatch(_parser().parse_args(argv))
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
            allow_nan=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
