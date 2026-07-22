from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_ROOT / "hooks" / "dev_flow_hook.py"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


class DevFlowHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "plugin-data"
        self.data_dir.mkdir()
        self.cwd = Path(self.temporary.name) / "repository"
        self.cwd.mkdir()

    def invoke(
        self,
        payload: dict,
        *,
        cwd: Path | None = None,
        include_plugin_root: bool = True,
    ) -> tuple[str, str]:
        invocation = dict(payload)
        invocation.setdefault("cwd", str(cwd or self.cwd))
        environment = os.environ.copy()
        if include_plugin_root:
            environment["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        else:
            environment.pop("PLUGIN_ROOT", None)
        environment["PLUGIN_DATA"] = str(self.data_dir)
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(invocation),
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout, completed.stderr

    def activate(self, stage: str, **extra: object) -> Path:
        values = {
            "route": {"value": "direct", "reason": "bounded change"},
            "pending_gate": "workspace-approval" if stage == "ROUTE_APPROVED" else None,
            "next_action": "prepare the managed worktree",
        }
        values.update(extra)
        return self.write_core_state(
            "TASK-42",
            stage,
            **values,
        )

    def write_core_state(
        self,
        task_id: str,
        stage: str,
        *,
        updated_at: str = "2026-07-21T12:00:00Z",
        repository: dict | None = None,
        **extra: object,
    ) -> Path:
        task_dir = self.data_dir / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "schema_version": 1,
            "task_id": task_id,
            "status": stage,
            "updated_at": updated_at,
            "route": "standard",
            "repositories": [repository or {"id": "repo", "path": str(self.cwd)}],
            "approvals": {},
            "workspace": {},
        }
        state.update(extra)
        state_file = task_dir / "state.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return state_file

    def assert_denied(self, command: str, *, cwd: Path | None = None) -> str:
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            cwd=cwd,
        )
        self.assertEqual(stderr, "")
        output = json.loads(stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertTrue(specific["permissionDecisionReason"])
        return specific["permissionDecisionReason"]

    def test_default_plugin_hook_discovery_and_commands(self) -> None:
        document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        hooks = document["hooks"]
        self.assertEqual(
            set(hooks), {"SessionStart", "UserPromptSubmit", "PreToolUse"}
        )
        self.assertNotIn("Stop", hooks)
        for groups in hooks.values():
            for group in groups:
                for handler in group["hooks"]:
                    self.assertIn("$PLUGIN_ROOT/hooks/dev_flow_hook.py", handler["command"])
                    self.assertNotIn("~", handler["command"])

    def test_session_start_injects_active_task_checkpoint(self) -> None:
        self.activate("ROUTE_APPROVED")
        stdout, stderr = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        self.assertEqual(stderr, "")
        output = json.loads(stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "SessionStart")
        context = specific["additionalContext"]
        self.assertIn("Active task: TASK-42", context)
        self.assertIn("Stage: ROUTE_APPROVED", context)
        self.assertIn("Route: direct", context)
        self.assertIn("Pending gate: workspace-approval", context)
        self.assertIn("Next action: prepare the managed worktree", context)
        self.assertIn(f"Data directory: {self.data_dir.resolve()}", context)
        self.assertIn(f"Controller: {PLUGIN_ROOT / 'scripts' / 'dev_flow.py'}", context)
        self.assertIn(f"--data-dir {self.data_dir.resolve()}", context)
        self.assertIn("show --task TASK-42", context)
        self.assertIn("Every controller call must explicitly include", context)
        self.assertNotIn("$PLUGIN_ROOT", context)

    def test_user_prompt_submit_uses_its_own_output_event_name(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        output = json.loads(stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        self.assertIn("Next action: write the plan", specific["additionalContext"])

    def test_context_selects_baseline_index_explicitly_before_workspace(self) -> None:
        self.activate(
            "INDEXED",
            repository={
                "id": "service",
                "path": str(self.cwd),
                "index": {"index_id": "task-service-baseline"},
            },
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(
            "codebase-memory selection: explicit project parameter; never automatic",
            context,
        )
        self.assertIn("Active index role: baseline", context)
        self.assertIn("Active index projects: service=task-service-baseline", context)

    def test_context_requires_workspace_index_after_workspace_creation(self) -> None:
        self.activate(
            "WORKSPACE_READY",
            repository={
                "id": "service",
                "path": str(self.cwd),
                "index": {"index_id": "task-service-baseline"},
            },
            next_action=None,
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Active index role: workspace", context)
        self.assertIn("Active index projects: service=MISSING", context)
        self.assertIn(
            "Next action: create or refresh every workspace index, then create the implementation plan",
            context,
        )

    def test_context_selects_current_workspace_project_and_blocked_origin(self) -> None:
        repository = {
            "id": "service",
            "path": str(self.cwd),
            "index": {"index_id": "task-service-baseline"},
            "workspace_index": {"index_id": "task-service-workspace-r0"},
        }
        state_file = self.activate("IMPLEMENTING", repository=repository)
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Active index role: workspace", context)
        self.assertIn(
            "Active index projects: service=task-service-workspace-r0", context
        )

        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "BLOCKED"
        task["blocked"] = {"from_status": "INDEXED", "reason": "example"}
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Active index role: baseline", context)
        self.assertIn("Active index projects: service=task-service-baseline", context)

    def test_context_uses_controller_gate_keys_and_stage_actions(self) -> None:
        state_file = self.activate(
            "PREFLIGHTED", pending_gate=None, next_action=None, approvals={}
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Pending gate: baseline fetch/materialization approval", context)

        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "REVIEWING"
        task["approvals"] = {}
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Pending gate: review approval", context)
        self.assertIn("Next action: approve the review and then finalize", context)

        task["status"] = "FINALIZING"
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Pending gate: none", context)

    def test_current_core_layout_selects_latest_nonterminal_task_for_cwd(self) -> None:
        self.write_core_state(
            "TASK-OLD", "PLANNING", updated_at="2026-07-21T10:00:00Z"
        )
        self.write_core_state(
            "TASK-NEW",
            "IMPLEMENTING",
            updated_at="2026-07-21T11:00:00Z",
            next_action="run focused tests",
        )
        self.write_core_state(
            "TASK-DONE", "DONE", updated_at="2026-07-21T12:00:00Z"
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Active task: TASK-NEW", context)
        self.assertIn("Stage: IMPLEMENTING", context)
        self.assertNotIn("TASK-DONE", context)

    def test_current_core_layout_matches_managed_workspace_path(self) -> None:
        source = Path(self.temporary.name) / "source-repository"
        source.mkdir()
        self.write_core_state(
            "TASK-WORKSPACE",
            "WORKSPACE_READY",
            repository={
                "id": "repo",
                "path": str(source),
                "canonical_path": str(source.resolve()),
                "workspace": {
                    "path": str(self.cwd),
                    "branch": "dev-flow/TASK-WORKSPACE",
                },
            },
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Active task: TASK-WORKSPACE", context)

    def test_analysis_workspace_is_active_but_remains_write_guarded(self) -> None:
        source = Path(self.temporary.name) / "source-repository"
        source.mkdir()
        managed = Path(self.temporary.name) / "managed-workspace"
        managed.mkdir()
        self.write_core_state(
            "TASK-ANALYSIS",
            "WORKSPACE_READY",
            repository={
                "id": "repo",
                "path": str(source),
                "canonical_path": str(source.resolve()),
                "analysis_workspace": {
                    "path": str(self.cwd),
                    "base_sha": "a" * 40,
                },
                "workspace": {
                    "path": str(managed),
                    "branch": "codex/TASK-ANALYSIS",
                    "ready": True,
                },
            },
        )
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch"},
            }
        )
        specific = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertIn("analysis workspaces", specific["permissionDecisionReason"])

    def test_context_events_bootstrap_without_an_active_task_or_plugin_root(self) -> None:
        for event, extra in (
            ("SessionStart", {"source": "startup"}),
            ("UserPromptSubmit", {"prompt": "hello"}),
        ):
            with self.subTest(event=event):
                stdout, stderr = self.invoke(
                    {"hook_event_name": event, **extra},
                    include_plugin_root=False,
                )
                self.assertEqual(stderr, "")
                specific = json.loads(stdout)["hookSpecificOutput"]
                self.assertEqual(specific["hookEventName"], event)
                context = specific["additionalContext"]
                self.assertIn("Dev Flow controller bootstrap", context)
                self.assertIn(
                    f"Controller: {PLUGIN_ROOT / 'scripts' / 'dev_flow.py'}",
                    context,
                )
                self.assertIn(f"Data directory: {self.data_dir.resolve()}", context)
                self.assertIn(f"--data-dir {self.data_dir.resolve()}", context)
                self.assertIn("Every controller call must explicitly include", context)
                self.assertNotIn("$PLUGIN_ROOT", context)

    def test_destructive_and_workflow_bypass_commands_are_denied(self) -> None:
        self.activate("INTAKE")
        commands = (
            "git push --force origin feature",
            "git push --force-with-lease origin feature",
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git pull --ff-only",
            "git switch feature/TASK-42",
            "git checkout -b feature/TASK-42",
            "git worktree add ../task-worktree -b feature/TASK-42",
            "cd subdir && git push origin main",
            "bash -lc 'git reset --hard HEAD'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)
        reason = self.assert_denied("git pull --ff-only")
        self.assertIn(str(PLUGIN_ROOT / "scripts" / "dev_flow.py"), reason)
        self.assertIn(f"--data-dir {self.data_dir.resolve()}", reason)
        self.assertNotIn("$PLUGIN_ROOT", reason)

    def test_direct_push_and_commit_on_protected_branch_are_denied(self) -> None:
        subprocess.run(
            ["git", "init", "-q", str(self.cwd)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.cwd), "symbolic-ref", "HEAD", "refs/heads/main"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.activate("INTAKE")
        self.assertIn("protected branch", self.assert_denied("git commit -m change"))
        self.assertIn("Direct pushes", self.assert_denied("git push origin main"))
        self.assertIn("Direct pushes", self.assert_denied("git push"))

        outer = Path(self.temporary.name) / "outer"
        outer.mkdir()
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git commit -m change",
                    "workdir": str(self.cwd),
                },
            },
            cwd=outer,
        )
        self.assertEqual(
            json.loads(stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_recorded_default_branch_is_also_protected(self) -> None:
        subprocess.run(
            ["git", "init", "-q", str(self.cwd)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(self.cwd), "symbolic-ref", "HEAD", "refs/heads/develop"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.write_core_state(
            "TASK-DEVELOP",
            "WORKSPACE_READY",
            repository={
                "id": "repo",
                "path": str(self.cwd),
                "preflight": {"base_branch": "develop"},
            },
        )
        reason = self.assert_denied("git commit -m change")
        self.assertIn("develop", reason)

    def test_read_only_git_commands_and_feature_push_are_not_blocked(self) -> None:
        self.activate("IMPLEMENTING")
        commands = (
            "git status --short",
            "git diff --stat",
            "git log -1 --oneline",
            "git show HEAD:README.md",
            "git branch --show-current",
            "echo git push --force origin main",
            "git push origin feature/TASK-42",
            "python3 scripts/dev_flow.py workspace prepare TASK-42",
        )
        for command in commands:
            with self.subTest(command=command):
                stdout, stderr = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "")

    def test_file_writes_are_denied_until_workspace_ready(self) -> None:
        task_file = self.activate("ROUTE_APPROVED")
        for tool_name in ("apply_patch", "Write"):
            with self.subTest(tool_name=tool_name):
                stdout, _ = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": tool_name,
                        "tool_input": {"command": "*** Begin Patch"},
                    }
                )
                specific = json.loads(stdout)["hookSpecificOutput"]
                self.assertEqual(specific["permissionDecision"], "deny")
                self.assertIn("source repositories", specific["permissionDecisionReason"])

        task = json.loads(task_file.read_text(encoding="utf-8"))
        task["status"] = "WORKSPACE_READY"
        managed = Path(self.temporary.name) / "managed-workspace"
        managed.mkdir()
        task["repositories"][0]["workspace"] = {
            "path": str(managed),
            "branch": "codex/TASK-42",
            "ready": True,
        }
        task_file.write_text(json.dumps(task), encoding="utf-8")

        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch"},
            }
        )
        reason = json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("source repositories", reason)

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch"},
            },
            cwd=managed,
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": "*** Begin Patch",
                    "workdir": str(managed),
                },
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_explicit_write_targets_must_all_be_in_ready_workspaces(self) -> None:
        managed = Path(self.temporary.name) / "managed-workspace"
        managed.mkdir()
        state_file = self.activate("WORKSPACE_READY")
        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["repositories"][0]["workspace"] = {
            "path": str(managed),
            "branch": "codex/TASK-42",
            "ready": True,
        }
        state_file.write_text(json.dumps(task), encoding="utf-8")

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(managed / "new.py")},
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

        mixed_patch = "\n".join(
            (
                "*** Begin Patch",
                "*** Update File: managed.py",
                f"*** Delete File: {self.cwd / 'source.py'}",
                "*** End Patch",
            )
        )
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": mixed_patch, "workdir": str(managed)},
            }
        )
        reason = json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("source repositories", reason)

        # Free-form apply_patch input may be exposed under `patch` rather than
        # `command`; it must receive the same multi-target path validation.
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"patch": mixed_patch, "workdir": str(managed)},
            }
        )
        reason = json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("source repositories", reason)

    def test_indexed_task_can_write_only_its_artifacts_directory(self) -> None:
        self.activate("INDEXED")
        artifacts = self.data_dir / "tasks" / "TASK-42" / "artifacts"
        artifacts.mkdir()

        for tool_input, invocation_cwd in (
            ({"file_path": str(artifacts / "impact.md")}, self.cwd),
            (
                {
                    "command": "*** Begin Patch\n*** Add File: impact.md\n*** End Patch",
                    "workdir": str(artifacts),
                },
                self.cwd,
            ),
            ({"file_path": str(artifacts / "from-artifact-cwd.md")}, artifacts),
        ):
            with self.subTest(tool_input=tool_input, cwd=invocation_cwd):
                stdout, stderr = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "apply_patch"
                        if "command" in tool_input
                        else "Write",
                        "tool_input": tool_input,
                    },
                    cwd=invocation_cwd,
                )
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "")

        forbidden_targets = (
            self.data_dir / "tasks" / "TASK-42" / "state.json",
            self.data_dir / "tasks" / "TASK-42" / "events.jsonl",
            self.data_dir / "tasks" / "TASK-42" / "reviews" / "review.md",
            self.data_dir / "tasks" / "OTHER" / "artifacts" / "impact.md",
        )
        for target in forbidden_targets:
            with self.subTest(target=target):
                stdout, _ = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Write",
                        "tool_input": {"file_path": str(target)},
                    }
                )
                specific = json.loads(stdout)["hookSpecificOutput"]
                self.assertEqual(specific["permissionDecision"], "deny")

        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.cwd / "business.py")},
            }
        )
        reason = json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("source repositories", reason)

        state_file = self.data_dir / "tasks" / "TASK-42" / "state.json"
        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "BLOCKED"
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(artifacts / "blocked.md")},
            }
        )
        specific = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        self.assertIn("BLOCKED", specific["permissionDecisionReason"])

    def test_unified_exec_cmd_alias_is_guarded(self) -> None:
        self.activate("INTAKE")
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"cmd": "git reset --hard HEAD"},
            }
        )
        self.assertEqual(
            json.loads(stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_shell_policy_is_silent_without_an_active_task(self) -> None:
        for command in (
            "git pull --ff-only",
            "git switch feature/unrelated",
            "git reset --hard HEAD",
            "git clean -fd",
            "git push --force origin feature/unrelated",
        ):
            with self.subTest(command=command):
                stdout, stderr = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    }
                )
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "")

    def test_file_write_without_active_task_is_not_blocked(self) -> None:
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch"},
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")


if __name__ == "__main__":
    unittest.main()
