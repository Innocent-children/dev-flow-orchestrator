"""Current Hook context injection, data-dir write guard, and subprocess launch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Optional
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.hook import HookConfig, _controller_command, handle
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    PLUGIN_DATA_NAMESPACE,
    PRODUCT_VERSION,
)
from support import RepositoryTestCase


def event_payload(event: str, cwd: str) -> dict:
    return {
        "hook_event_name": event,
        "cwd": cwd,
    }


class HookTests(RepositoryTestCase):
    def config(
        self,
        state_data_dir: Optional[str] = None,
        protected_data_root: Optional[str] = None,
    ) -> HookConfig:
        data_dir = state_data_dir or self.data_dir
        return HookConfig(
            (
                str(ROOT / "scripts" / "dev_flow_python_launcher"),
                str(ROOT / "scripts" / "dev_flow.py"),
            ),
            data_dir,
            protected_data_root or data_dir,
        )

    def run_hook(self, payload: dict) -> dict:
        result = handle(
            payload,
            config=self.config(),
        )
        self.assertIsNotNone(result)
        return result["hookSpecificOutput"]

    def test_session_start_injects_projection(self) -> None:
        task_id = self.start_lite()
        output = self.run_hook(event_payload("SessionStart", str(self.repository)))
        context = output["additionalContext"]
        self.assertIn("locator=", context)
        self.assertIn(task_id, context)
        self.assertIn("projection", context)
        projection = json.loads(
            context.split("projection=", 1)[1].strip()
        )
        self.assertEqual(
            set(projection),
            {
                "schema",
                "task_id",
                "revision",
                "workflow",
                "status",
                "current_node",
                "contract",
                "repository_set",
                "freshness",
                "review",
                "action",
                "dossier",
                "done",
            },
        )
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(projection["task_id"], task_id)
        self.assertEqual(projection["workflow"]["version"], PRODUCT_VERSION)
        self.assertEqual(
            projection["contract"],
            {
                "revision": 1,
                "digest": projection["contract"]["digest"],
                "summary": "A test requirement",
                "criterion_ids": ["requirement"],
            },
        )
        repository_set = projection["repository_set"]
        state = self.controller.show(task_id)
        self.assertEqual(repository_set["id"], state.repository_set_id)
        self.assertEqual(len(repository_set["digest"]), 64)
        self.assertEqual(len(repository_set["repositories"]), 1)
        member = repository_set["repositories"][0]
        self.assertEqual(member["id"], state.repositories[0].repository_id)
        self.assertEqual(member["path"], str(self.repository.resolve()))
        self.assertEqual(
            set(member["snapshot"]),
            {
                "digest",
                "head",
                "branch",
                "clean",
                "status_sha256",
                "status_bytes",
                "object_format",
                "index_entry_count",
                "index_output_bytes",
                "has_unmerged_entries",
                "git_worktree_dir",
                "git_common_dir",
            },
        )
        self.assertEqual(projection["action"]["action_id"], "task.preflight")
        self.assertEqual(
            projection["action"]["binding"]["starting_snapshot_digest"],
            repository_set["digest"],
        )
        self.assertIsInstance(projection["action"]["binding"], dict)
        self.assertIsNone(projection["dossier"])
        self.assertFalse(projection["done"])
        locator = context.split(" locator=", 1)[1].split(" projection=", 1)[0]
        self.assertEqual(shlex.split(locator)[:2], list(self.config().controller_argv))

    def test_no_task_returns_locator_hint(self) -> None:
        output = self.run_hook(
            event_payload("SessionStart", str(self.root / "elsewhere"))
        )
        context = output["additionalContext"]
        self.assertIn("controller locator", context)
        self.assertIn("--workflow", context)
        self.assertIn("--data-dir", context)

    def test_pre_tool_use_denies_data_dir_writes(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {"file_path": str(Path(self.data_dir) / "tasks" / "x")},
        }
        result = handle(
            payload,
            config=self.config(),
        )
        self.assertIsNotNone(result)
        output = result["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    def test_user_prompt_submit_does_not_mutate_state(self) -> None:
        task_id = self.start_lite()
        payload = event_payload("UserPromptSubmit", str(self.repository))
        payload["session_id"] = "s1"
        payload["turn_id"] = "t1"
        payload["prompt"] = "do the work"
        self.run_hook(payload)
        self.assertEqual(self.controller.show(task_id).revision, 0)

    def test_pre_tool_use_allows_regular_files(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {"file_path": str(self.root / "notes.txt")},
        }
        result = handle(
            payload,
            config=self.config(),
        )
        self.assertIsNone(result)

    def test_subprocess_launch_with_plugin_data(self) -> None:
        plugin_data = self.root / "plugin data"
        state_data = plugin_data / PLUGIN_DATA_NAMESPACE
        controller = Controller(str(state_data))
        task_id = controller.start(
            requirement="subprocess requirement",
            workflow="lite",
            repositories=(str(self.repository),),
        ).task_id
        launcher = ROOT / "scripts" / "dev_flow_python_launcher"
        hook_script = ROOT / "hooks" / "dev_flow_hook.py"
        payload = event_payload("SessionStart", str(self.repository))
        completed = subprocess.run(
            [
                str(launcher),
                str(hook_script),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PLUGIN_DATA": str(plugin_data),
                "DEV_FLOW_PYTHON": sys.executable,
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn(task_id, context)
        self.assertIn(shlex.quote(str(state_data.resolve())), context)
        self.assertIn("dev_flow_python_launcher", context)

    def test_locator_with_spaces_executes_via_shell(self) -> None:
        state_data = self.root / "state data with spaces"
        config = self.config(str(state_data), str(state_data))
        locator = _controller_command(config)
        completed = subprocess.run(
            ["/bin/sh", "-c", locator + " --help"],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "DEV_FLOW_PYTHON": sys.executable},
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage: dev-flow", completed.stdout)

    def test_apply_patch_command_targeting_data_is_denied(self) -> None:
        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / "x"
            / "state.json"
        )
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: {}\n*** End Patch".format(
                    state_path
                )
            },
        }
        output = handle(payload, config=self.config())["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    def test_bash_data_references_are_denied(self) -> None:
        for command in (
            "touch {}/tasks/x".format(self.data_dir),
            'printf x > "{}PLUGIN_DATA/{}/tasks/x"'.format(
                "$", PLUGIN_DATA_NAMESPACE
            ),
            'printf x > "{}{{PLUGIN_DATA}}/{}/tasks/x"'.format(
                "$", PLUGIN_DATA_NAMESPACE
            ),
        ):
            payload = {
                "hook_event_name": "PreToolUse",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            output = handle(payload, config=self.config())["hookSpecificOutput"]
            self.assertEqual(output["permissionDecision"], "deny")

    def test_exact_controller_command_is_allowed(self) -> None:
        task_id = self.start_lite()
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.repository),
            "tool_name": "Bash",
            "tool_input": {
                "command": _controller_command(self.config()) + " next " + task_id
            },
        }
        output = handle(payload, config=self.config())["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", output)

    def test_controller_command_with_shell_tail_is_denied(self) -> None:
        command = (
            _controller_command(self.config())
            + " list\ntouch "
            + str(Path(self.data_dir) / "tasks" / "x")
        )
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.repository),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        output = handle(payload, config=self.config())["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

    def test_regular_bash_is_allowed(self) -> None:
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "Bash",
            "tool_input": {"command": "git status --short"},
        }
        self.assertIsNone(handle(payload, config=self.config()))

    def test_guard_runs_before_corrupt_state_loading(self) -> None:
        task_id = self.start_lite()
        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )
        state_path.write_text("{broken", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: {}\n*** End Patch".format(
                    state_path
                )
            },
        }
        output = handle(payload, config=self.config())["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")

if __name__ == "__main__":
    unittest.main()
