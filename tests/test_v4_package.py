from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT


EXPECTED_TOOLS = {
    "task-next",
    "node-description",
    "evidence-read",
    "action-preview",
    "action-apply",
    "worker-result",
}


class V4PackageLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="dev-flow-v4-package-")
        temporary_root = Path(self._temporary.name)
        self.plugin_root = temporary_root / "插件 V4"
        self.plugin_root.mkdir()
        for name in ("hooks", "scripts", "workflows"):
            shutil.copytree(ROOT / name, self.plugin_root / name)
        shutil.copy2(ROOT / ".mcp.json", self.plugin_root / ".mcp.json")
        self.data_dir = temporary_root / "状态 数据"
        self.repo = temporary_root / "项目 空格"
        self.repo.mkdir()
        self.empty_git_config = temporary_root / "empty.gitconfig"
        self.empty_git_config.write_text("", encoding="utf-8")
        self.environment = os.environ.copy()
        for key in list(self.environment):
            if key.startswith("GIT_"):
                self.environment.pop(key, None)
        self.environment.update(
            {
                "DEV_FLOW_PYTHON": sys.executable,
                "PLUGIN_ROOT": str(self.plugin_root),
                "PLUGIN_DATA": str(self.data_dir),
                "PYTHONPYCACHEPREFIX": str(temporary_root / "pycache"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(self.empty_git_config),
                "GIT_CONFIG_SYSTEM": str(self.empty_git_config),
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        self._git("init", "-b", "feature")
        self._git("config", "user.email", "package@example.invalid")
        self._git("config", "user.name", "V4 Package")
        (self.repo / "README.md").write_text("package V4\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-m", "initial")
        started = subprocess.run(
            [
                sys.executable,
                str(self.plugin_root / "scripts/dev_flow.py"),
                "start",
                "package hook task",
                "--repo",
                str(self.repo),
                "--task-id",
                "package-hook",
                "--workspace-strategy",
                "in-place",
                "--change-category",
                "docs",
                "--target-path",
                "README.md",
                "--data-dir",
                str(self.data_dir),
            ],
            cwd=self.plugin_root,
            env=self.environment,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(
            started.returncode,
            0,
            msg=f"stdout={started.stdout}\nstderr={started.stderr}",
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            env=self.environment,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _launch_hook(
        self, event: str, payload: dict[str, object]
    ) -> tuple[subprocess.CompletedProcess[bytes], object]:
        hook_configuration = json.loads(
            (self.plugin_root / "hooks/hooks.json").read_text(
                encoding="utf-8"
            )
        )
        command = hook_configuration["hooks"][event][0]["hooks"][0][
            "command"
        ]
        source = {
            "hook_event_name": event,
            "session_id": "会话-v4",
            "cwd": str(self.repo),
            **payload,
        }
        completed = subprocess.run(
            command,
            cwd=self.plugin_root,
            env=self.environment,
            executable="/bin/sh",
            shell=True,
            input=(
                json.dumps(
                    source,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\r\n"
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
        decoded = completed.stdout.decode("utf-8")
        response = json.loads(decoded) if decoded.strip() else None
        return completed, response

    def test_exact_packaged_mcp_profile_initializes_and_lists_tools(self) -> None:
        configuration = json.loads(
            (self.plugin_root / ".mcp.json").read_text(encoding="utf-8")
        )
        profile = configuration["mcpServers"]["dev-flow-macos"]
        frames = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "v4-package-test", "version": "1"},
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        ]
        payload = "".join(
            json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n"
            for frame in frames
        ).encode("utf-8")
        completed = subprocess.run(
            [profile["command"], *profile["args"]],
            cwd=self.plugin_root / profile["cwd"],
            env=self.environment,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=15,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stderr.decode("utf-8", errors="replace"),
        )
        responses = [
            json.loads(line)
            for line in completed.stdout.decode("utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual([response["id"] for response in responses], [1, 2])
        self.assertEqual(
            responses[0]["result"]["serverInfo"]["name"],
            "dev-flow-orchestrator",
        )
        self.assertEqual(
            {
                tool["name"]
                for tool in responses[1]["result"]["tools"]
            },
            EXPECTED_TOOLS,
        )

    def test_exact_packaged_hook_command_accepts_crlf_utf8_event(self) -> None:
        completed, response = self._launch_hook(
            "SessionStart", {"source": "startup"}
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stderr.decode("utf-8", errors="replace"),
        )
        specific = response["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        self.assertIn("package-hook", specific["additionalContext"])

    def test_every_packaged_handler_launches_and_compaction_restores(self) -> None:
        payloads = {
            "SessionStart": {"source": "startup"},
            "UserPromptSubmit": {"prompt": "continue"},
            "SubagentStart": {"agent_id": "unassigned"},
            "SubagentStop": {"agent_id": "unassigned"},
            "PreCompact": {"trigger": "manual"},
            "PostCompact": {"trigger": "manual"},
            "PreToolUse": {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git status --short",
                    "workdir": str(self.repo),
                },
            },
        }
        for event, payload in payloads.items():
            with self.subTest(event=event):
                completed, _response = self._launch_hook(event, payload)
                self.assertEqual(
                    completed.returncode,
                    0,
                    msg=completed.stderr.decode(
                        "utf-8", errors="replace"
                    ),
                )

        pre, pre_response = self._launch_hook(
            "PreCompact", {"trigger": "manual"}
        )
        self.assertEqual(pre.returncode, 0)
        self.assertEqual(pre_response, {})
        post, post_response = self._launch_hook(
            "PostCompact", {"trigger": "manual"}
        )
        self.assertEqual(post.returncode, 0)
        self.assertIsNone(post_response)
        resumed, response = self._launch_hook(
            "SessionStart", {"source": "compact"}
        )
        self.assertEqual(resumed.returncode, 0)
        context = response["hookSpecificOutput"]["additionalContext"]
        self.assertIn("package-hook", context)
        self.assertIn("revision", context)

    def test_pretooluse_denies_protected_wrappers_and_allows_benign_git(
        self,
    ) -> None:
        cases = (
            ("git reset --hard", True),
            ("sh -c 'git reset --hard'", True),
            ("sh -c 'git reset --hard", True),
            ("git status --short", False),
        )
        for command, denied in cases:
            with self.subTest(command=command):
                completed, response = self._launch_hook(
                    "PreToolUse",
                    {
                        "tool_name": "Bash",
                        "tool_input": {
                            "command": command,
                            "workdir": str(self.repo),
                        },
                    },
                )
                self.assertEqual(completed.returncode, 0)
                if denied:
                    specific = response["hookSpecificOutput"]
                    self.assertEqual(
                        specific["permissionDecision"], "deny"
                    )
                    self.assertTrue(
                        specific["permissionDecisionReason"]
                    )
                else:
                    self.assertIsNone(response)

    def test_hook_parser_recognizes_direct_git_and_posix_shell_wrapper(self) -> None:
        namespace = runpy.run_path(
            str(self.plugin_root / "hooks/dev_flow_hook.py"),
            run_name="v4_package_hook",
        )
        inspect_git = namespace["_git_invocations"]
        direct, direct_error = inspect_git("git status --short", self.plugin_root)
        wrapped, wrapped_error = inspect_git(
            "sh -c 'git status --short'",
            self.plugin_root,
        )
        self.assertIsNone(direct_error)
        self.assertIsNone(wrapped_error)
        self.assertEqual(direct, [("status", ["--short"], self.plugin_root)])
        self.assertEqual(wrapped, [("status", ["--short"], self.plugin_root)])


if __name__ == "__main__":
    unittest.main()
