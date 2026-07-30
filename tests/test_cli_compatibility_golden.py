from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import SCRIPT, dev_flow


FIXTURE_ROOT = Path(__file__).with_name("fixtures")
CLI_FIXTURE = FIXTURE_ROOT / "workflow_legacy" / "cli_contract.json"
CLI_REGISTRY_FIXTURE = (
    FIXTURE_ROOT / "workflow_legacy" / "cli_registry_parser.json"
)
SIZE_FIXTURE_ROOT = FIXTURE_ROOT / "protocol_sizes"
SIZE_BASELINE = SIZE_FIXTURE_ROOT / "baseline.json"
WORKER_SUMMARY = SIZE_FIXTURE_ROOT / "representative_worker_summary.json"
HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "dev_flow_hook.py"


def _json_default(value: object) -> object:
    if value is argparse.SUPPRESS:
        return "<SUPPRESS>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _parser_action(action: argparse.Action) -> dict[str, object]:
    return {
        "dest": action.dest,
        "option_strings": list(action.option_strings),
        "required": bool(action.required),
        "nargs": _json_default(action.nargs),
        "default": _json_default(action.default),
        "choices": (
            sorted(action.choices) if action.choices is not None else None
        ),
        "action": type(action).__name__,
        "type": getattr(action.type, "__name__", None),
    }


def _parser_contract() -> dict[str, object]:
    parser = dev_flow.build_parser()
    subcommands = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    def actions(value: argparse.ArgumentParser) -> list[dict[str, object]]:
        return [
            _parser_action(action)
            for action in value._actions
            if not isinstance(
                action, (argparse._HelpAction, argparse._SubParsersAction)
            )
        ]

    return {
        "prog": parser.prog,
        "root": actions(parser),
        "subparser_required": subcommands.required,
        "commands": {
            name: actions(command_parser)
            for name, command_parser in sorted(subcommands.choices.items())
        },
    }


def _canonical_contract_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _parser_help_contract() -> dict[str, object]:
    parser = dev_flow.build_parser()
    subcommands = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    def metadata(
        value: argparse.ArgumentParser,
    ) -> dict[str, object]:
        return {
            "description": value.description,
            "actions": [
                {
                    "dest": action.dest,
                    "option_strings": list(action.option_strings),
                    "help": action.help,
                    "metavar": action.metavar,
                }
                for action in value._actions
                if not isinstance(
                    action,
                    (
                        argparse._HelpAction,
                        argparse._SubParsersAction,
                    ),
                )
            ],
            "mutually_exclusive_groups": [
                [
                    action.dest
                    for action in group._group_actions
                ]
                for group in value._mutually_exclusive_groups
            ],
        }

    return {
        "command_order": list(subcommands.choices),
        "command_help": {
            action.dest: action.help
            for action in subcommands._choices_actions
        },
        "root": metadata(parser),
        "commands": {
            name: metadata(command_parser)
            for name, command_parser in subcommands.choices.items()
        },
    }


def _load_hook() -> object:
    spec = importlib.util.spec_from_file_location(
        "dev_flow_hook_compatibility_golden", HOOK_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _representative_state(schema_version: int = 2) -> dict[str, object]:
    state: dict[str, object] = {
        "schema_version": schema_version,
        "task_id": "TASK-GOLDEN",
        "requirement": "Preserve the legacy workflow contract",
        "revision": 17,
        "status": "IMPLEMENTING",
        "flow": "full",
        "updated_at": "2026-07-27T00:00:00Z",
        "route": {
            "value": "direct",
            "reason": "bounded compatibility change",
        },
        "next_action": "implement the approved compatibility baseline",
        "pending_gate": None,
        "workspace": {
            "strategy": "worktree",
            "ready": True,
            "generation": 3,
        },
        "repositories": [
            {
                "id": "repo-alpha",
                "path": "/workspace/repo-alpha",
                "index": {
                    "index_record_id": "index-baseline-1",
                    "index_id": "baseline-project",
                    "repo_path": "/analysis/repo-alpha",
                    "receipt": {
                        "mode": "baseline",
                        "persistence": True,
                    },
                },
                "workspace_index": {
                    "index_record_id": "index-workspace-1",
                    "index_id": "workspace-project",
                    "repo_path": "/workspace/repo-alpha",
                    "workspace_generation": 3,
                    "receipt": {
                        "mode": "workspace",
                        "persistence": False,
                    },
                },
            }
        ],
        "artifacts": [
            {"artifact_id": "artifact-plan-1", "kind": "direct-contract"}
        ],
        "tests": [{"test_id": "test-1", "passed": True}],
        "review_snapshots": [],
        "approvals": {"plan": {"approval_id": "approval-plan-1"}},
        "blocked": None,
        "cancelled": None,
        "risk_assessment": {"decision": "requires_full"},
    }
    if schema_version == 2:
        state["confirmation_contract_version"] = (
            dev_flow.CONFIRMATION_CONTRACT_VERSION
        )
    return state


class CliCompatibilityGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CLI_FIXTURE.read_text(encoding="utf-8"))
        cls.registry_contract = json.loads(
            CLI_REGISTRY_FIXTURE.read_text(encoding="utf-8")
        )
        cls.size_baseline = json.loads(
            SIZE_BASELINE.read_text(encoding="utf-8")
        )

    def _invoke_main(self, arguments: list[str]) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            return_code = dev_flow.main(arguments)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1, output.getvalue())
        return return_code, json.loads(lines[0])

    def test_complete_cli_grammar_matches_pristine_golden(self) -> None:
        grammar = _parser_contract()
        fixture = self.contract["grammar"]
        legacy_commands = set(fixture["commands"])
        extensions = sorted(
            set(grammar["commands"]) - legacy_commands
        )
        self.assertEqual(
            extensions,
            [
                "action-recovery-apply",
                "action-recovery-inspect",
                "action-recovery-preview",
                "manager-authorize",
                "manager-revoke",
            ],
        )
        legacy_grammar = {
            **grammar,
            "commands": {
                name: grammar["commands"][name]
                for name in fixture["commands"]
            },
        }
        payload = _canonical_contract_bytes(legacy_grammar)
        self.assertEqual(
            sorted(legacy_grammar["commands"]), fixture["commands"]
        )
        self.assertEqual(
            len(legacy_grammar["commands"]),
            fixture["command_count"],
        )
        self.assertEqual(
            sum(
                len(actions)
                for actions in legacy_grammar["commands"].values()
            ),
            fixture["action_count"],
        )
        self.assertEqual(len(payload), fixture["canonical_bytes"])
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), fixture["sha256"]
        )

    def test_registry_generated_parser_preserves_help_and_order(self) -> None:
        contract = _parser_help_contract()
        fixture = self.registry_contract
        legacy_order = fixture["command_order"]
        self.assertEqual(
            [
                command
                for command in contract["command_order"]
                if command not in legacy_order
            ],
            [
                "manager-authorize",
                "manager-revoke",
                "action-recovery-apply",
                "action-recovery-inspect",
                "action-recovery-preview",
            ],
        )
        legacy_contract = {
            **contract,
            "command_order": [
                command
                for command in contract["command_order"]
                if command in legacy_order
            ],
            "command_help": {
                command: contract["command_help"][command]
                for command in legacy_order
            },
            "commands": {
                command: contract["commands"][command]
                for command in legacy_order
            },
        }
        payload = _canonical_contract_bytes(legacy_contract)
        self.assertEqual(
            legacy_contract["command_order"],
            fixture["command_order"],
        )
        self.assertEqual(len(payload), fixture["canonical_bytes"])
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(), fixture["sha256"]
        )

    def test_manager_command_extensions_are_exact_and_appended(self) -> None:
        parser = dev_flow.build_parser()
        subcommands = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        legacy_order = self.registry_contract["command_order"]
        self.assertEqual(
            list(subcommands.choices),
            [
                *legacy_order,
                "manager-authorize",
                "manager-revoke",
                "action-recovery-apply",
                "action-recovery-inspect",
                "action-recovery-preview",
            ],
        )
        authorize = subcommands.choices["manager-authorize"]
        revoke = subcommands.choices["manager-revoke"]
        recovery_apply = subcommands.choices["action-recovery-apply"]
        recovery_inspect = subcommands.choices["action-recovery-inspect"]
        recovery_preview = subcommands.choices[
            "action-recovery-preview"
        ]
        self.assertEqual(
            [
                action.dest
                for action in authorize._actions
                if not isinstance(action, argparse._HelpAction)
            ],
            [
                "task_id",
                "task_option",
                "expected_revision",
                "manager_session_id",
                "ttl_seconds",
                "preview",
                "confirm_intent",
                "manager_secret_fd",
                "data_dir",
            ],
        )
        self.assertEqual(
            [
                action.dest
                for action in revoke._actions
                if not isinstance(action, argparse._HelpAction)
            ],
            [
                "task_id",
                "task_option",
                "expected_revision",
                "capability_id",
                "reason",
                "preview",
                "confirm_intent",
                "data_dir",
            ],
        )
        authorize_groups = [
            [
                action.dest
                for action in group._group_actions
            ]
            for group in authorize._mutually_exclusive_groups
        ]
        revoke_groups = [
            [
                action.dest
                for action in group._group_actions
            ]
            for group in revoke._mutually_exclusive_groups
        ]
        self.assertEqual(
            authorize_groups, [["preview", "confirm_intent"]]
        )
        self.assertEqual(
            revoke_groups, [["preview", "confirm_intent"]]
        )
        self.assertEqual(
            [
                action.dest
                for action in recovery_apply._actions
                if not isinstance(action, argparse._HelpAction)
            ],
            [
                "task_id",
                "task_option",
                "expected_revision",
                "data_dir",
                "execution_id",
                "attempt_id",
                "outcome",
                "confirm_preview",
                "evidence_json",
            ],
        )
        self.assertEqual(
            [
                action.dest
                for action in recovery_inspect._actions
                if not isinstance(action, argparse._HelpAction)
            ],
            [
                "task_id",
                "task_option",
                "execution_id",
                "data_dir",
            ],
        )
        self.assertEqual(
            [
                action.dest
                for action in recovery_preview._actions
                if not isinstance(action, argparse._HelpAction)
            ],
            [
                "task_id",
                "task_option",
                "execution_id",
                "attempt_id",
                "outcome",
                "expected_revision",
                "evidence_json",
                "data_dir",
            ],
        )
        self.assertEqual(recovery_apply._mutually_exclusive_groups, [])
        self.assertEqual(
            recovery_inspect._mutually_exclusive_groups, []
        )
        self.assertEqual(
            recovery_preview._mutually_exclusive_groups, []
        )
        self.assertTrue(
            authorize._mutually_exclusive_groups[0].required
        )
        self.assertTrue(
            revoke._mutually_exclusive_groups[0].required
        )
        parsed_authorize = parser.parse_args(
            [
                "manager-authorize",
                "--task",
                "TASK-1",
                "--expected-revision",
                "7",
                "--manager-session-id",
                "manager-1",
                "--ttl-seconds",
                "90",
                "--confirm-intent",
                "manager-capability-intent:" + "1" * 64,
                "--manager-secret-fd",
                "9",
            ]
        )
        self.assertEqual(parsed_authorize.expected_revision, 7)
        self.assertEqual(parsed_authorize.ttl_seconds, 90)
        self.assertEqual(parsed_authorize.manager_secret_fd, 9)
        parsed_revoke = parser.parse_args(
            [
                "manager-revoke",
                "TASK-1",
                "--expected-revision",
                "8",
                "--capability-id",
                "manager-capability:" + "2" * 64,
                "--reason",
                "operator-requested",
                "--preview",
            ]
        )
        self.assertEqual(parsed_revoke.expected_revision, 8)
        self.assertTrue(parsed_revoke.preview)
        registry = (
            dev_flow.workflow_runtime_services()
            .registries.commands
        )
        extensions = {
            entry.command: (
                entry.parser_order,
                entry.action_id,
            )
            for entry in registry.entries.values()
            if entry.command
            in {
                "manager-authorize",
                "manager-revoke",
                "action-recovery-apply",
                "action-recovery-inspect",
                "action-recovery-preview",
            }
        }
        self.assertEqual(
            extensions,
            {
                "manager-authorize": (
                    17,
                    "manager.capability.authorize",
                ),
                "manager-revoke": (
                    18,
                    "manager.capability.revoke",
                ),
                "action-recovery-apply": (
                    19,
                    "control.reconcile/v1",
                ),
                "action-recovery-inspect": (
                    20,
                    "control.reconcile.inspect/v1",
                ),
                "action-recovery-preview": (
                    21,
                    "control.reconcile.preview/v1",
                ),
            },
        )
        for command in legacy_order:
            options = {
                option
                for action in subcommands.choices[
                    command
                ]._actions
                for option in action.option_strings
            }
            self.assertNotIn("--manager-request-json", options)
            self.assertNotIn("--manager-secret-fd", options)
        public_request = json.dumps(
            {
                "schema": (
                    "dev-flow-manager-capability-request/v1"
                ),
                "capability_id": (
                    "manager-capability:" + "3" * 64
                ),
                "task_id": "TASK-1",
                "manager_session_id": "manager-1",
                "action_id": "task.transition",
                "expected_revision": 7,
                "request_nonce": "4" * 64,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        remaining, request_value, secret_fd = (
            dev_flow._extract_manager_cli_authority_options(
                [
                    "transition",
                    "TASK-1",
                    "--expected-revision",
                    "7",
                    "--to",
                    "BLOCKED",
                    "--manager-request-json",
                    public_request,
                    "--manager-secret-fd=9",
                ]
            )
        )
        self.assertEqual(
            remaining,
            [
                "transition",
                "TASK-1",
                "--expected-revision",
                "7",
                "--to",
                "BLOCKED",
            ],
        )
        self.assertEqual(request_value, public_request)
        self.assertEqual(secret_fd, 9)

    def test_default_show_is_full_and_preserves_v1_v2_schema(self) -> None:
        expected = self.contract["default_show"]
        for schema_version in expected["supported_schema_versions"]:
            state = _representative_state(schema_version)
            with mock.patch.object(
                dev_flow,
                "load_state_for_inspection",
                return_value=(state, None),
            ):
                return_code, response = self._invoke_main(
                    ["show", "--task", "TASK-GOLDEN"]
                )
            self.assertEqual(return_code, 0)
            self.assertEqual(response["command"], "show")
            self.assertIn(expected["full_state_field"], response)
            for compact_only in expected["compact_only_fields"]:
                self.assertNotIn(compact_only, response)
            self.assertEqual(
                response["task"]["schema_version"], schema_version
            )

    def test_schema_v1_and_v2_snapshots_load_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = dev_flow._normalize_risk_policy(
                {
                    "schema": "dev-flow-risk-policy/v1",
                    "protected_paths": [],
                }
            )
            reasons = dev_flow._declared_risk_reasons(0, [], [], policy)
            for schema_version in (1, 2):
                state: dict[str, object] = {
                    "schema_version": schema_version,
                    "evidence_contract_version": (
                        dev_flow.EVIDENCE_CONTRACT_VERSION
                    ),
                    "task_id": f"schema-{schema_version}",
                    "status": "INTAKE",
                    "revision": 4,
                    "flow": "full",
                    "workspace": {
                        "strategy": "worktree",
                        "ready": False,
                        "generation": 0,
                    },
                    "repositories": [],
                }
                if schema_version == 2:
                    risk = {
                        "schema": "dev-flow-risk-assessment/v1",
                        "decision": "requires_full",
                        "categories": [],
                        "target_paths": [],
                        "repository_count": 0,
                        "policy": policy,
                        "policy_sha256": dev_flow._sha256_bytes(
                            dev_flow._json_bytes(policy)
                        ),
                        "reasons": reasons,
                        "evaluated_at": "2026-07-27T00:00:00.000Z",
                    }
                    risk["sha256"] = dev_flow._sha256_bytes(
                        dev_flow._json_bytes(risk)
                    )
                    state.update(
                        {
                            "confirmation_contract_version": (
                                dev_flow.CONFIRMATION_CONTRACT_VERSION
                            ),
                            "risk_assessment": risk,
                        }
                    )
                path = root / f"schema-{schema_version}" / "state.json"
                path.parent.mkdir()
                path.write_bytes(dev_flow._json_bytes(state))
                before = path.read_bytes()
                loaded = dev_flow.load_state(path)
                self.assertEqual(loaded["schema_version"], schema_version)
                self.assertEqual(path.read_bytes(), before)

    def test_stable_error_codes_and_exit_codes_match_golden(self) -> None:
        cases = self.contract["stable_errors"]
        return_code, response = self._invoke_main([])
        self.assertEqual(
            (response["error"]["code"], return_code),
            (
                cases["missing-command"]["code"],
                cases["missing-command"]["exit_code"],
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            return_code, response = self._invoke_main(
                [
                    "--data-dir",
                    temporary,
                    "show",
                    "--task",
                    "missing-task",
                ]
            )
        self.assertEqual(
            (response["error"]["code"], return_code),
            (
                cases["missing-task"]["code"],
                cases["missing-task"]["exit_code"],
            ),
        )

        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._check_revision({"task_id": "task", "revision": 8}, 7)
        self.assertEqual(
            (raised.exception.code, raised.exception.exit_code),
            (
                cases["revision-conflict"]["code"],
                cases["revision-conflict"]["exit_code"],
            ),
        )

    def test_isolated_stdlib_startup_contract(self) -> None:
        expected = self.contract["isolated_startup"]
        with tempfile.TemporaryDirectory() as temporary:
            environment = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    *expected["interpreter_flags"],
                    str(SCRIPT),
                    "--data-dir",
                    temporary,
                    "list",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
        self.assertEqual(completed.returncode, expected["exit_code"])
        self.assertEqual(completed.stderr, b"")
        self.assertTrue(completed.stdout.endswith(b"\n"))
        response = json.loads(completed.stdout)
        self.assertEqual(
            {
                "ok": response["ok"],
                "command": response["command"],
                "count": response["count"],
                "tasks": response["tasks"],
            },
            expected["response"],
        )

    def _production_size_payloads(self) -> dict[str, bytes]:
        state = _representative_state()
        hook = _load_hook()
        with mock.patch.object(hook.sys, "executable", "/usr/bin/python3"):
            session_context = hook.build_context(
                state,
                Path("/plugin-data"),
                True,
                Path("/plugin/scripts/dev_flow.py"),
            )
            compact_context = hook.build_compact_context(
                state,
                Path("/plugin-data"),
                True,
                Path("/plugin/scripts/dev_flow.py"),
            )
        compact_read = dev_flow._result(
            "show",
            state,
            summary=dev_flow._show_summary(state),
        )
        mutation_receipt = dev_flow._result(
            "transition",
            state,
            transition={
                "from": "PLANNING",
                "to": "IMPLEMENTING",
                "note": "approved plan",
                "confirmation_mode": "explicit",
            },
        )
        return {
            "hook_session_start": session_context.encode("utf-8"),
            "hook_compact": compact_context.encode("utf-8"),
            "compact_task_read": dev_flow._protocol_json_bytes(compact_read),
            "common_mutation_receipt": dev_flow._protocol_json_bytes(
                mutation_receipt
            ),
            "representative_worker_summary": (
                WORKER_SUMMARY.read_bytes()
            ),
        }

    def test_protocol_size_inventory_records_current_bytes_not_future_budgets(
        self,
    ) -> None:
        payloads = self._production_size_payloads()
        self.assertEqual(
            set(payloads), set(self.size_baseline["payloads"])
        )
        for name, payload in payloads.items():
            with self.subTest(payload=name):
                expected = self.size_baseline["payloads"][name]
                self.assertEqual(len(payload), expected["bytes"])
                self.assertEqual(
                    hashlib.sha256(payload).hexdigest(),
                    expected["sha256"],
                )
                self.assertNotIn("budget", expected)
                self.assertNotIn("maximum", expected)

        worker_summary = json.loads(
            payloads["representative_worker_summary"]
        )
        self.assertEqual(worker_summary["status"], "completed")
        self.assertIsInstance(worker_summary["summary"], str)
        self.assertTrue(worker_summary["artifacts"])
        self.assertTrue(worker_summary["tests"]["passed"])


if __name__ == "__main__":
    unittest.main()
