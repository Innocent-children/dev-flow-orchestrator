from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator import cli as cli_adapter
from dev_flow_orchestrator import hook as hook_adapter
from dev_flow_orchestrator import mcp as mcp_adapter
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError


class GreenfieldAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = self.root / "data"
        self.repository = self.root / "repository"
        self.repository.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        (self.repository / "README.md").write_text("adapter\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "README.md"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "-c",
                "user.name=Greenfield Test",
                "-c",
                "user.email=greenfield@example.invalid",
                "commit",
                "-q",
                "-m",
                "initial",
            ],
            check=True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _mcp(self, requests: list[dict]) -> list[dict]:
        payload = "".join(
            json.dumps(item, separators=(",", ":")) + "\n"
            for item in requests
        ).encode("utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow_mcp.py"),
                "--data-dir",
                str(self.data_dir),
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return [
            json.loads(line)
            for line in completed.stdout.decode("utf-8").splitlines()
        ]

    def _hook(self, payload: dict) -> dict | None:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "hooks" / "dev_flow_hook.py"),
                "--data-dir",
                str(self.data_dir),
            ],
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        if not completed.stdout:
            return None
        return json.loads(completed.stdout.decode("utf-8"))

    def test_mcp_and_cli_read_the_same_controller_projection(self) -> None:
        responses = self._mcp(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "task-start",
                        "arguments": {
                            "requirement": "adapter parity",
                            "workflow": "lite",
                            "workspace_strategy": "in-place",
                            "repositories": [str(self.repository)],
                            "task_id": "adapter-parity",
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "task-next",
                        "arguments": {
                            "task_id": "adapter-parity",
                            "session_id": "adapter-session",
                        },
                    },
                },
            ]
        )
        self.assertEqual(len(responses), 3)
        mcp_projection = responses[-1]["result"]["structuredContent"]["result"]
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "--data-dir",
                str(self.data_dir),
                "next",
                "adapter-parity",
                "--session-id",
                "adapter-session",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        cli_projection = json.loads(
            completed.stdout.decode("utf-8")
        )["projection"]
        self.assertEqual(mcp_projection, cli_projection)

    def test_mcp_lists_only_current_greenfield_tools_without_fallback(self) -> None:
        response = self._mcp(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                }
            ]
        )[0]
        names = [item["name"] for item in response["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "task-start",
                "task-show",
                "task-next",
                "task-preflight",
                "action-apply",
                "effect-inspect",
                "effect-recover",
            ],
        )
        self.assertNotIn(
            "fallback",
            json.dumps(response, separators=(",", ":")).lower(),
        )
        tools = {
            item["name"]: item
            for item in response["result"]["tools"]
        }
        self.assertEqual(
            set(tools["task-next"]["inputSchema"]["properties"]),
            {"task_id", "session_id"},
        )
        self.assertEqual(
            set(tools["action-apply"]["inputSchema"]["properties"]),
            {
                "task_id",
                "expected_revision",
                "action_id",
                "payload",
                "session_id",
                "request_turn_id",
            },
        )
        self.assertEqual(
            set(tools["effect-recover"]["inputSchema"]["properties"]),
            {
                "task_id",
                "execution_id",
                "mode",
                "session_id",
                "request_turn_id",
            },
        )
        for tool_name, fields in {
            "task-next": ("session_id",),
            "action-apply": ("session_id", "request_turn_id"),
            "effect-recover": ("session_id", "request_turn_id"),
        }.items():
            for field in fields:
                self.assertEqual(
                    tools[tool_name]["inputSchema"]["properties"][field][
                        "maxLength"
                    ],
                    256,
                )
        self.assertNotIn("authorize", tools)

    def test_hook_injects_projection_without_transition(self) -> None:
        controller = Controller(str(self.data_dir))
        controller.start(
            requirement="hook observation",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repository)],
            task_id="hook-observe",
        )
        before = controller.show("hook-observe")
        output = self._hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "hook-session",
                "turn_id": "hook-turn",
                "cwd": str(self.repository),
                "prompt": "unrelated prompt",
            }
        )
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("hook-observe", context)
        self.assertIn('"current_node":"preflight"', context)
        self.assertIn(
            'conversation_routing={"request_turn_id":"hook-turn",'
            '"session_id":"hook-session"}',
            context,
        )
        after = controller.show("hook-observe")
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.as_dict(), before.as_dict())

    def test_user_prompt_hook_forwards_only_bounded_complete_event_fields(self) -> None:
        controller = mock.Mock()
        controller.tasks_for_path.return_value = []
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-1",
            "turn_id": "turn-2",
            "cwd": str(self.repository),
            "prompt": "  同意 req-123  ",
        }
        with mock.patch.object(
            hook_adapter,
            "Controller",
            return_value=controller,
        ):
            output = hook_adapter.handle(
                payload,
                data_dir=str(self.data_dir),
                controller_path=str(ROOT / "scripts" / "dev_flow.py"),
            )
        controller.observe_user_prompt.assert_called_once_with(
            session_id="session-1",
            turn_id="turn-2",
            cwd=str(self.repository),
            prompt="  同意 req-123  ",
        )
        self.assertEqual(
            controller.mock_calls[:2],
            [
                mock.call.observe_user_prompt(
                    session_id="session-1",
                    turn_id="turn-2",
                    cwd=str(self.repository),
                    prompt="  同意 req-123  ",
                ),
                mock.call.tasks_for_path(str(self.repository)),
            ],
        )
        self.assertEqual(
            output["hookSpecificOutput"]["hookEventName"],
            "UserPromptSubmit",
        )
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn(
            'conversation_routing={"request_turn_id":"turn-2",'
            '"session_id":"session-1"}',
            context,
        )
        self.assertIn("grants no authority", context)

        limits = {
            "session_id": hook_adapter.SESSION_ID_MAX_BYTES,
            "turn_id": hook_adapter.TURN_ID_MAX_BYTES,
            "cwd": hook_adapter.CWD_MAX_BYTES,
            "prompt": hook_adapter.PROMPT_MAX_BYTES,
        }
        for field, maximum in limits.items():
            with self.subTest(field=field):
                controller.reset_mock()
                controller.tasks_for_path.return_value = []
                oversized = dict(payload)
                oversized[field] = "x" * (maximum + 1)
                with mock.patch.object(
                    hook_adapter,
                    "Controller",
                    return_value=controller,
                ):
                    hook_adapter.handle(
                        oversized,
                        data_dir=str(self.data_dir),
                        controller_path=str(ROOT / "scripts" / "dev_flow.py"),
                    )
                controller.observe_user_prompt.assert_not_called()

        controller.reset_mock()
        controller.tasks_for_path.return_value = []
        session_start = dict(payload)
        session_start["hook_event_name"] = "SessionStart"
        with mock.patch.object(
            hook_adapter,
            "Controller",
            return_value=controller,
        ):
            hook_adapter.handle(
                session_start,
                data_dir=str(self.data_dir),
                controller_path=str(ROOT / "scripts" / "dev_flow.py"),
            )
        controller.observe_user_prompt.assert_not_called()

    def test_hook_denies_direct_task_state_write_and_fails_open(self) -> None:
        denied = self._hook(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(self.repository),
                "tool_name": "Write",
                "tool_input": {
                    "file_path": str(
                        self.data_dir / "tasks" / "task" / "state.json"
                    )
                },
            }
        )
        specific = denied["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        malformed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "hooks" / "dev_flow_hook.py"),
                "--data-dir",
                str(self.data_dir),
            ],
            input=b"{not-json",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(malformed.returncode, 0)
        self.assertEqual(malformed.stdout, b"")

    def test_development_adapter_bootstraps_do_not_reference_old_runtime(self) -> None:
        paths = (
            ROOT / "scripts" / "dev_flow.py",
            ROOT / "scripts" / "dev_flow_mcp.py",
            ROOT / "hooks" / "dev_flow_hook.py",
        )
        for path in paths:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("dev_flow_parts", source)
            self.assertNotIn("exec(", source)

    def test_authority_has_no_separate_agent_invocable_issuer(self) -> None:
        application_help = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "--data-dir",
                str(self.data_dir),
                "--help",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(application_help.returncode, 0)
        self.assertNotIn("authorize", application_help.stdout.decode("utf-8"))
        self.assertFalse((ROOT / "scripts" / "dev_flow_authority.py").exists())
        self.assertFalse(
            (ROOT / "src" / "dev_flow_orchestrator" / "authority_cli.py").exists()
        )

    def test_adapters_reject_forbidden_confirmation_input_matrix(self) -> None:
        forbidden = {
            "approval": True,
            "approved": True,
            "confirmation": True,
            "confirmation_id": "caller-forged",
            "request_id": "caller-forged",
            "authority": "caller-forged",
            "authority_id": "caller-forged",
            "issuer": {"channel": "caller"},
            "actor": "caller",
            "actor_id": "caller",
            "prompt": "approve",
            "record": {"status": "CONFIRMED"},
            "confirmation_record": {"status": "CONFIRMED"},
            "authority_record": {"status": "CONFIRMED"},
        }
        requests = [
            {
                "jsonrpc": "2.0",
                "id": index,
                "method": "tools/call",
                "params": {
                    "name": "action-apply",
                    "arguments": {
                        "task_id": "missing",
                        "expected_revision": 0,
                        "action_id": "task.preflight",
                        field: value,
                    },
                },
            }
            for index, (field, value) in enumerate(forbidden.items(), start=1)
        ]
        responses = self._mcp(requests)
        self.assertEqual(len(responses), len(forbidden))
        for field, response in zip(forbidden, responses):
            with self.subTest(adapter="mcp", field=field):
                self.assertEqual(response["error"]["code"], -32602)
                self.assertIn(field, response["error"]["message"])

        for field, value in forbidden.items():
            cli_value = (
                json.dumps(value, separators=(",", ":"))
                if not isinstance(value, str)
                else value
            )
            with self.subTest(adapter="cli", field=field):
                with self.assertRaises(DevFlowError) as raised:
                    cli_adapter._parser().parse_args(
                        [
                            "--data-dir",
                            str(self.data_dir),
                            "apply",
                            "missing",
                            "--expected-revision",
                            "0",
                            "--action",
                            "task.preflight",
                            "--" + field.replace("_", "-"),
                            cli_value,
                        ]
                    )
                self.assertEqual(raised.exception.code, "ARGUMENT_INVALID")

    def test_cli_and_mcp_forward_only_conversation_routing_fields(self) -> None:
        cli_controller = mock.Mock()
        cli_receipt = mock.Mock()
        cli_receipt.as_dict.return_value = {"schema": "test-receipt"}
        cli_controller.apply.return_value = cli_receipt
        cli_controller.next.return_value = {"schema": "test-projection"}
        cli_controller.recover_effect.return_value = {
            "schema": "test-recovery"
        }
        with mock.patch.object(
            cli_adapter,
            "Controller",
            return_value=cli_controller,
        ):
            arguments = cli_adapter._parser().parse_args(
                [
                    "--data-dir",
                    str(self.data_dir),
                    "apply",
                    "routing-task",
                    "--expected-revision",
                    "4",
                    "--action",
                    "task.implementation.complete",
                    "--payload-json",
                    '{"summary":"done"}',
                    "--session-id",
                    "session-1",
                    "--request-turn-id",
                    "turn-1",
                ]
            )
            cli_adapter._dispatch(arguments)
            cli_adapter._dispatch(
                cli_adapter._parser().parse_args(
                    [
                        "--data-dir",
                        str(self.data_dir),
                        "next",
                        "routing-task",
                        "--session-id",
                        "session-1",
                    ]
                )
            )
            cli_adapter._dispatch(
                cli_adapter._parser().parse_args(
                    [
                        "--data-dir",
                        str(self.data_dir),
                        "effect-recover",
                        "routing-task",
                        "--execution-id",
                        "execution-1",
                        "--mode",
                        "settle",
                        "--session-id",
                        "session-1",
                        "--request-turn-id",
                        "turn-1",
                    ]
                )
            )
        cli_controller.apply.assert_called_once_with(
            "routing-task",
            4,
            "task.implementation.complete",
            {"summary": "done"},
            session_id="session-1",
            request_turn_id="turn-1",
        )
        cli_controller.next.assert_called_once_with(
            "routing-task",
            session_id="session-1",
        )
        cli_controller.recover_effect.assert_called_once_with(
            "routing-task",
            "execution-1",
            "settle",
            session_id="session-1",
            request_turn_id="turn-1",
        )

        mcp_controller = mock.Mock()
        mcp_receipt = mock.Mock()
        mcp_receipt.as_dict.return_value = {"schema": "test-receipt"}
        mcp_controller.apply.return_value = mcp_receipt
        mcp_controller.next.return_value = {"schema": "test-projection"}
        mcp_controller.recover_effect.return_value = {
            "schema": "test-recovery"
        }
        with mock.patch.object(
            mcp_adapter,
            "Controller",
            return_value=mcp_controller,
        ):
            server = mcp_adapter.McpServer(str(self.data_dir))
            result = server._dispatch_tool(
                "action-apply",
                {
                    "task_id": "routing-task",
                    "expected_revision": 4,
                    "action_id": "task.implementation.complete",
                    "payload": {"summary": "done"},
                    "session_id": "session-1",
                    "request_turn_id": "turn-1",
                },
            )
            server._dispatch_tool(
                "task-next",
                {
                    "task_id": "routing-task",
                    "session_id": "session-1",
                },
            )
            server._dispatch_tool(
                "effect-recover",
                {
                    "task_id": "routing-task",
                    "execution_id": "execution-1",
                    "mode": "settle",
                    "session_id": "session-1",
                    "request_turn_id": "turn-1",
                },
            )
        self.assertFalse(result["isError"])
        mcp_controller.apply.assert_called_once_with(
            "routing-task",
            4,
            "task.implementation.complete",
            {"summary": "done"},
            session_id="session-1",
            request_turn_id="turn-1",
        )
        mcp_controller.next.assert_called_once_with(
            "routing-task",
            session_id="session-1",
        )
        mcp_controller.recover_effect.assert_called_once_with(
            "routing-task",
            "execution-1",
            "settle",
            session_id="session-1",
            request_turn_id="turn-1",
        )

        with self.assertRaises(DevFlowError):
            cli_adapter._parser().parse_args(
                [
                    "--data-dir",
                    str(self.data_dir),
                    "next",
                    "routing-task",
                    "--session-id",
                    "同" * 129,
                ]
            )
        with self.assertRaises(mcp_adapter.McpError) as raised:
            server._dispatch_tool(
                "task-next",
                {"task_id": "routing-task", "session_id": "同" * 129},
            )
        self.assertEqual(raised.exception.code, -32602)

    def test_adapters_emit_machine_readable_argument_errors(self) -> None:
        response = self._mcp(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": {
                        "name": "action-apply",
                        "arguments": {
                            "task_id": "missing",
                            "expected_revision": 0,
                            "action_id": "task.preflight",
                            "authority_id": "caller-forged",
                        },
                    },
                }
            ]
        )[0]
        self.assertEqual(response["error"]["code"], -32602)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "--data-dir",
                str(self.data_dir),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, b"")
        result = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(result["error"]["code"], "ARGUMENT_INVALID")


if __name__ == "__main__":
    unittest.main()
