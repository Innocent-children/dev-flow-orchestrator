from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_ROOT / "hooks" / "dev_flow_hook.py"
WINDOWS_HOOK = PLUGIN_ROOT / "hooks" / "dev_flow_hook.cmd"
POSIX_PYTHON_LAUNCHER = (
    PLUGIN_ROOT / "scripts" / "dev_flow_python_launcher"
)
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


class DevFlowHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "plugin-data"
        self.data_dir.mkdir()
        self.cwd = Path(self.temporary.name) / "repository"
        self.cwd.mkdir()

    def write_scope(self, *, include: list[Path] | None = None, exclude: list[Path] | None = None) -> None:
        scope = {
            "mode": "allowlist" if include else "all",
            "include": [str(path) for path in include or []],
            "exclude": [str(path) for path in exclude or []],
        }
        (self.data_dir / "config.json").write_text(
            json.dumps({"schema_version": 1, "scope": scope}), encoding="utf-8"
        )

    def invoke(
        self,
        payload: dict,
        *,
        cwd: Path | None = None,
        include_plugin_root: bool = True,
        include_plugin_data: bool = True,
        env: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        invocation = dict(payload)
        invocation.setdefault("cwd", str(cwd or self.cwd))
        environment = os.environ.copy()
        if include_plugin_root:
            environment["PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        else:
            environment.pop("PLUGIN_ROOT", None)
        if include_plugin_data:
            environment["PLUGIN_DATA"] = str(self.data_dir)
        else:
            environment.pop("PLUGIN_DATA", None)
        environment.update(env or {})
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(invocation),
            text=True,
            encoding="utf-8",
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

    def checkpoint_marker(self, session_id: str) -> Path:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return self.data_dir / "hook-checkpoints" / f"{digest}.json"

    def locator_payload(self, stdout: str) -> dict:
        output = json.loads(stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        return json.loads(context)

    def add_worker_assignment(
        self,
        state_file: Path,
        *,
        host_agent_id: str = "agent-7",
        parallel_dispatch_allowed: bool = True,
        manager_secret: str | None = None,
    ) -> dict:
        from tests import test_orchestration_authority as authority_fixture

        scripts = str(PLUGIN_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import dev_flow

        state = json.loads(state_file.read_text(encoding="utf-8"))
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        creation = dev_flow.build_v3_task_creation_fields(
            state["task_id"],
            bundle,
            execution_profile="multi-repository",
        )
        state.update(
            {
                "schema_version": 3,
                "revision": 41,
                "flow": "full",
                **creation,
            }
        )
        lease_values = authority_fixture.lease_spec()
        lease_values["task_id"] = state["task_id"]
        lease_values["repository_id"] = state["repositories"][0]["id"]
        lease_values["workflow_bundle_sha256"] = bundle.bundle_sha256
        lease = authority_fixture.issue_lease(lease_values)
        assignment = dev_flow.create_worker_assignment(
            lease.as_dict(),
            node_id="repository.implement/v1",
            worktree_path=str(self.cwd.resolve()),
            controller_claim_sha256=authority_fixture.digest("9"),
            plan_id="repository-plan:task-7:3",
            plan_artifact_sha256=authority_fixture.digest("a"),
            playbook_locator="playbooks/repository-implement.md",
            playbook_sha256=authority_fixture.digest("b"),
            required_evidence_contract_sha256s=[
                authority_fixture.digest("c"),
                authority_fixture.digest("d"),
            ],
        ).as_dict()
        dispatch_mode = (
            "parallel-writable-worker"
            if parallel_dispatch_allowed
            else "manager-serial"
        )
        orchestration = state["orchestration"]
        orchestration.update(
            {
                "assignments": {
                    assignment["assignment_id"]: assignment,
                },
                "dispatch": {
                    assignment["assignment_id"]: {
                        "decision": {
                            "schema": (
                                "dev-flow-host-isolation-decision/v1"
                            ),
                            "assignment_id": assignment["assignment_id"],
                            "parallel_dispatch_allowed": (
                                parallel_dispatch_allowed
                            ),
                            "dispatch_mode": dispatch_mode,
                            "blocker_codes": (
                                []
                                if parallel_dispatch_allowed
                                else ["HOST_BOUNDARY_NOT_ENFORCED"]
                            ),
                        },
                        "host_assignment_id": host_agent_id,
                        **(
                            {"manager_secret": manager_secret}
                            if manager_secret is not None
                            else {}
                        ),
                    }
                },
            }
        )
        state["status"] = "IMPLEMENTING"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        return assignment

    def node_result_for_assignment(self, assignment: dict) -> dict:
        import dev_flow

        credential = assignment["lease_credential"]
        candidate = {
            "schema": "dev-flow-node-result/v1",
            "task_id": assignment["task_id"],
            "workflow_bundle_sha256": assignment[
                "workflow_bundle_sha256"
            ],
            "map_epoch": assignment["map_epoch"],
            "repository_id": assignment["repository_id"],
            "node_instance_id": assignment["node_instance_id"],
            "attempt": assignment["attempt"],
            "assignment_id": assignment["assignment_id"],
            "lease_id": credential["lease_id"],
            "lease_nonce": credential["lease_nonce"],
            "input_sha256": assignment["input_evidence_sha256"],
            "output_sha256": "1" * 64,
            "worktree_sha256": assignment[
                "worktree_identity_sha256"
            ],
            "changed_paths_sha256": "2" * 64,
            "verification_sha256": "3" * 64,
            "outcome": "SUCCEEDED",
            "summary": "implemented the scoped node",
            "blockers": [],
            "plan_drift": {"detected": False, "reasons": []},
            "artifact_refs": [],
            "evidence_refs": [],
            "runtime_handle": None,
        }
        bound = dev_flow.bind_node_result_identity(candidate)
        return json.loads(dev_flow.canonical_node_result_bytes(bound))

    def upgrade_state_to_v2(self, state_file: Path, *, revision: int = 7) -> None:
        policy = {
            "schema": "dev-flow-risk-policy/v1",
            "protected_paths": [],
        }

        def controller_sha256(value: object) -> str:
            encoded = (
                json.dumps(
                    value,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8", "backslashreplace")
            return hashlib.sha256(encoded).hexdigest()

        risk = {
            "schema": "dev-flow-risk-assessment/v1",
            "decision": "requires_full",
            "categories": [],
            "target_paths": [],
            "repository_count": 1,
            "policy": policy,
            "policy_sha256": controller_sha256(policy),
            "reasons": [
                {"code": "change_category_unknown"},
                {"code": "target_paths_unknown"},
            ],
            "evaluated_at": "2026-07-26T00:00:00Z",
        }
        risk["sha256"] = controller_sha256(risk)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state.update(
            {
                "schema_version": 2,
                "evidence_contract_version": 2,
                "confirmation_contract_version": 1,
                "revision": revision,
                "flow": "full",
                "risk_assessment": risk,
                "workspace": {
                    "strategy": "worktree",
                    "ready": False,
                    "generation": 0,
                },
            }
        )
        state_file.write_text(json.dumps(state), encoding="utf-8")

    def test_multiple_active_tasks_are_denied_without_newest_selection(self) -> None:
        self.write_core_state("TASK-42", "INTAKE")
        self.write_core_state("TASK-43", "IMPLEMENTING")
        reason = self.assert_denied("echo must-not-run")
        self.assertIn("Multiple non-terminal tasks", reason)
        self.assertIn("TASK-42", reason)
        self.assertIn("TASK-43", reason)

    def test_default_plugin_hook_discovery_and_commands(self) -> None:
        document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        hooks = document["hooks"]
        self.assertEqual(
            set(hooks),
            {
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "SubagentStart",
                "SubagentStop",
                "PreCompact",
                "PostCompact",
            },
        )
        self.assertNotIn("Stop", hooks)
        self.assertIn("Bash", hooks["PreToolUse"][0]["matcher"])
        for groups in hooks.values():
            for group in groups:
                for handler in group["hooks"]:
                    self.assertIn(
                        "$PLUGIN_ROOT/scripts/dev_flow_python_launcher",
                        handler["command"],
                    )
                    self.assertIn("$PLUGIN_ROOT/hooks/dev_flow_hook.py", handler["command"])
                    self.assertIn("commandWindows", handler)
                    self.assertIn(
                        "%PLUGIN_ROOT%\\hooks\\dev_flow_hook.cmd",
                        handler["commandWindows"],
                    )
                    self.assertNotIn("python3", handler["commandWindows"].lower())
                    self.assertNotIn("~", handler["command"])
                    self.assertNotIn("~", handler["commandWindows"])
                    self.assertNotIn("python3", handler["command"])
        shim = WINDOWS_HOOK.read_text(encoding="utf-8")
        self.assertIn("setlocal DisableDelayedExpansion", shim)
        self.assertIn("py -3", shim)
        for version in ("3.14", "3.13", "3.12", "3.11", "3.10", "3.9"):
            self.assertIn(version, shim)
        self.assertIn("python", shim)
        self.assertIn("(3, 9) <= sys.version_info[:2] < (3, 15)", shim)
        self.assertIn('"%PLUGIN_ROOT%\\hooks\\dev_flow_hook.py"', shim)
        self.assertIn("%*", shim)
        self.assertIn("exit /b %errorlevel%", shim)
        posix = POSIX_PYTHON_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn(
            "(3, 9) <= sys.version_info[:2] < (3, 15)",
            posix,
        )
        self.assertIn("python3.14", posix)
        self.assertIn("python3.9", posix)
        self.assertIn("DEV_FLOW_PYTHON", posix)

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
        locator = json.loads(context)
        self.assertEqual(locator["contract"], "dev-flow-hook-checkpoint/v1")
        self.assertEqual(locator["task_id"], "TASK-42")
        self.assertEqual(locator["revision"], 0)
        self.assertEqual(locator["condition"]["node_id"], "ROUTE_APPROVED")
        self.assertRegex(locator["frontier_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn(f"--data-dir {self.data_dir.resolve()}", context)
        self.assertIn("show --task TASK-42 --next --profile agent-v1", context)
        self.assertLessEqual(len(context.encode("utf-8")), 600)
        self.assertNotIn("$PLUGIN_ROOT", context)

    def test_data_dir_argument_replaces_missing_plugin_data(self) -> None:
        # Global registrations run without either plugin variable and pass an
        # absolute hook path plus --data-dir.
        environment = os.environ.copy()
        environment.pop("PLUGIN_DATA", None)
        environment.pop("PLUGIN_ROOT", None)
        completed = subprocess.run(
            [sys.executable, str(HOOK), "--data-dir", str(self.data_dir)],
            input=json.dumps(
                {"hook_event_name": "SessionStart", "cwd": str(self.cwd)}
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        context = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Dev Flow controller bootstrap:", context)
        self.assertIn("启动前确认：", context)
        self.assertIn("新建并切换分支（精简流程）", context)
        self.assertIn(f"Controller: {PLUGIN_ROOT / 'scripts' / 'dev_flow.py'}", context)
        self.assertIn(f"Data directory: {self.data_dir.resolve()}", context)

    def test_data_dir_argument_outranks_inherited_plugin_data(self) -> None:
        other = Path(self.temporary.name) / "stale-plugin-data"
        other.mkdir()
        completed = subprocess.run(
            [sys.executable, str(HOOK), f"--data-dir={self.data_dir}"],
            input=json.dumps(
                {"hook_event_name": "SessionStart", "cwd": str(self.cwd)}
            ),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PLUGIN_ROOT": str(PLUGIN_ROOT),
                "PLUGIN_DATA": str(other),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        context = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"Data directory: {self.data_dir.resolve()}", context)

    def test_hook_protocol_is_utf8_bytes_with_one_lf_and_accepts_crlf(self) -> None:
        unicode_data = Path(self.temporary.name) / "插件 data ü"
        unicode_data.mkdir()
        unicode_cwd = Path(self.temporary.name) / "仓库 ü"
        unicode_cwd.mkdir()
        payload = {
            "hook_event_name": "SessionStart",
            "source": "startup",
            "cwd": str(unicode_cwd),
        }
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\r\n",
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PLUGIN_ROOT": str(PLUGIN_ROOT),
                "PLUGIN_DATA": str(unicode_data),
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        self.assertTrue(completed.stdout.endswith(b"\n"))
        self.assertFalse(completed.stdout.endswith(b"\r\n"))
        self.assertEqual(completed.stdout.count(b"\n"), 1)
        output = json.loads(completed.stdout.decode("utf-8"))
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn(str(unicode_data.resolve()), context)
        self.assertIn("插件", context)

    def test_malformed_utf8_protocol_input_fails_open_silently(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=b"\xff\xfe\r\n",
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PLUGIN_ROOT": str(PLUGIN_ROOT),
                "PLUGIN_DATA": str(self.data_dir),
            },
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, b"")
        self.assertEqual(completed.stderr, b"")

    def test_actual_packaged_hook_command_for_native_platform(self) -> None:
        special_root = (
            Path(self.temporary.name) / "插件 root ! & (hooks) $literal"
        )
        special_data = (
            Path(self.temporary.name) / "数据 state ! & (flow) $literal"
        )
        special_cwd = Path(self.temporary.name) / "仓库 work & (tree)"
        (special_root / "hooks").mkdir(parents=True)
        (special_root / "scripts").mkdir()
        special_data.mkdir()
        special_cwd.mkdir()
        shutil.copy2(HOOK, special_root / "hooks" / HOOK.name)
        shutil.copy2(WINDOWS_HOOK, special_root / "hooks" / WINDOWS_HOOK.name)
        shutil.copy2(
            POSIX_PYTHON_LAUNCHER,
            special_root / "scripts" / POSIX_PYTHON_LAUNCHER.name,
        )
        shutil.copy2(
            PLUGIN_ROOT / "scripts" / "dev_flow.py",
            special_root / "scripts" / "dev_flow.py",
        )
        shutil.copy2(
            PLUGIN_ROOT / "scripts" / "workflow_bundle_identity.py",
            special_root / "scripts" / "workflow_bundle_identity.py",
        )
        shutil.copytree(
            PLUGIN_ROOT / "scripts" / "dev_flow_parts",
            special_root / "scripts" / "dev_flow_parts",
        )
        shutil.copytree(
            PLUGIN_ROOT / "workflows",
            special_root / "workflows",
        )

        task_dir = special_data / "tasks" / "PACKAGED-1"
        task_dir.mkdir(parents=True)
        (task_dir / "state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "task_id": "PACKAGED-1",
                    "status": "INTAKE",
                    "updated_at": "2026-07-24T01:00:00Z",
                    "route": None,
                    "repositories": [
                        {"id": "repo", "path": str(special_cwd)}
                    ],
                    "approvals": {},
                    "workspace": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        payloads = {
            "SessionStart": {
                "hook_event_name": "SessionStart",
                "source": "startup",
                "cwd": str(special_cwd),
            },
            "UserPromptSubmit": {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "继续",
                "cwd": str(special_cwd),
            },
            "PreToolUse": {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git pull --ff-only"},
                "cwd": str(special_cwd),
            },
            "SubagentStart": {
                "hook_event_name": "SubagentStart",
                "agent_type": "worker",
                "cwd": str(special_cwd),
            },
            "SubagentStop": {
                "hook_event_name": "SubagentStop",
                "agent_type": "worker",
                "cwd": str(special_cwd),
            },
            "PreCompact": {
                "hook_event_name": "PreCompact",
                "session_id": "packaged-session",
                "cwd": str(special_cwd),
            },
            "PostCompact": {
                "hook_event_name": "PostCompact",
                "session_id": "packaged-session",
                "cwd": str(special_cwd),
            },
        }
        command_key = "commandWindows" if os.name == "nt" else "command"
        environment = {
            **os.environ,
            "PLUGIN_ROOT": str(special_root),
            "PLUGIN_DATA": str(special_data),
        }
        document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        for event, groups in document["hooks"].items():
            for group in groups:
                for handler in group["hooks"]:
                    command = handler[command_key]
                    with self.subTest(event=event, command=command_key):
                        completed = subprocess.run(
                            command,
                            shell=True,
                            input=(
                                json.dumps(
                                    payloads[event], ensure_ascii=False
                                ).encode("utf-8")
                                + b"\r\n"
                            ),
                            capture_output=True,
                            check=False,
                            env=environment,
                            timeout=20,
                        )
                        self.assertEqual(
                            completed.returncode, 0, completed.stderr
                        )
                        self.assertEqual(completed.stderr, b"")
                        if event in {"SubagentStop", "PostCompact"}:
                            self.assertEqual(completed.stdout, b"")
                            continue
                        self.assertTrue(completed.stdout.endswith(b"\n"))
                        self.assertFalse(completed.stdout.endswith(b"\r\n"))
                        output = json.loads(completed.stdout.decode("utf-8"))
                        if event == "PreCompact":
                            self.assertEqual(output, {})
                            continue
                        specific = output["hookSpecificOutput"]
                        self.assertEqual(specific["hookEventName"], event)
                        if event == "SubagentStart":
                            context = specific["additionalContext"]
                            fallback = json.loads(context)
                            self.assertEqual(
                                fallback["contract"],
                                "dev-flow-subagent-serial-fallback/v1",
                            )
                            self.assertEqual(
                                fallback["dispatch_mode"],
                                "manager-serial",
                            )
                            self.assertNotIn(str(special_data), context)
                            continue
                        if event == "PreToolUse":
                            self.assertEqual(
                                specific["permissionDecision"], "deny"
                            )
                            reason = specific["permissionDecisionReason"]
                            self.assertIn(str(special_root), reason)
                            self.assertIn(str(special_data), reason)
                        else:
                            context = specific["additionalContext"]
                            self.assertIn(str(special_root), context)
                            self.assertIn(str(special_data), context)
                            locator = json.loads(context)
                            self.assertEqual(
                                locator["contract"],
                                "dev-flow-hook-checkpoint/v1",
                            )
                            self.assertIn(sys.executable, locator["controller"])

    @unittest.skipUnless(
        os.name == "nt", "requires native cmd.exe launcher resolution"
    )
    def test_windows_launcher_falls_back_when_py_is_unsupported(self) -> None:
        launcher_dir = Path(self.temporary.name) / "fake launchers"
        launcher_dir.mkdir()
        launch_log = Path(self.temporary.name) / "launcher.log"
        (launcher_dir / "py.cmd").write_text(
            "\n".join(
                (
                    "@echo off",
                    "setlocal DisableDelayedExpansion",
                    '>>"%DEV_FLOW_LAUNCH_LOG%" echo py-unsupported',
                    "exit /b 1",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (launcher_dir / "python.cmd").write_text(
            "\n".join(
                (
                    "@echo off",
                    "setlocal DisableDelayedExpansion",
                    '>>"%DEV_FLOW_LAUNCH_LOG%" echo python-supported',
                    f'"{sys.executable}" %*',
                    "exit /b %errorlevel%",
                    "",
                )
            ),
            encoding="utf-8",
        )
        document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        command = document["hooks"]["SessionStart"][0]["hooks"][0][
            "commandWindows"
        ]
        completed = subprocess.run(
            command,
            shell=True,
            input=json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "cwd": str(self.cwd),
                }
            ).encode("utf-8"),
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PATH": str(launcher_dir)
                + os.pathsep
                + os.environ.get("PATH", ""),
                "DEV_FLOW_LAUNCH_LOG": str(launch_log),
                "PLUGIN_ROOT": str(PLUGIN_ROOT),
                "PLUGIN_DATA": str(self.data_dir),
            },
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        self.assertIn("Dev Flow controller bootstrap", completed.stdout.decode("utf-8"))
        self.assertEqual(
            launch_log.read_text(encoding="utf-8").splitlines(),
            [
                *(["py-unsupported"] * 7),
                "python-supported",
                "python-supported",
            ],
        )

    @unittest.skipIf(
        os.name == "nt", "requires the packaged POSIX /bin/sh launcher"
    )
    def test_posix_launcher_handles_sparse_path_fallback_and_exact_stdio(
        self,
    ) -> None:
        root = Path(self.temporary.name)
        launcher_dir = root / "稀疏 launchers"
        handler_dir = root / "插件 handler ü"
        launcher_dir.mkdir()
        handler_dir.mkdir()
        handler = handler_dir / "echo exit ü.py"
        handler.write_text(
            "import sys\n"
            "payload = sys.stdin.buffer.read()\n"
            "sys.stdout.buffer.write(payload)\n"
            "sys.stdout.buffer.flush()\n"
            "raise SystemExit(int(sys.argv[1]))\n",
            encoding="utf-8",
        )
        unsupported = launcher_dir / "python3"
        unsupported.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' python3 >>\"$DEV_FLOW_LAUNCH_LOG\"\n"
            "exit 1\n",
            encoding="utf-8",
        )
        supported_name = (
            f"python{sys.version_info.major}.{sys.version_info.minor}"
        )
        supported = launcher_dir / supported_name
        supported.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$0\" >>\"$DEV_FLOW_LAUNCH_LOG\"\n"
            "exec \"$DEV_FLOW_REAL_PYTHON\" \"$@\"\n",
            encoding="utf-8",
        )
        unsupported.chmod(0o755)
        supported.chmod(0o755)
        launch_log = root / "launch log.txt"
        payload = "stdio 保真 ü\n".encode("utf-8")
        completed = subprocess.run(
            [
                str(POSIX_PYTHON_LAUNCHER),
                str(handler),
                "7",
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={
                "PATH": str(launcher_dir),
                "DEV_FLOW_LAUNCH_LOG": str(launch_log),
                "DEV_FLOW_REAL_PYTHON": sys.executable,
            },
            timeout=20,
        )
        self.assertEqual(completed.returncode, 7, completed.stderr)
        self.assertEqual(completed.stdout, payload)
        self.assertEqual(completed.stderr, b"")
        observed = launch_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(observed[0], "python3")
        self.assertTrue(observed[-1].endswith(supported_name), observed)

    @unittest.skipUnless(
        os.name == "nt", "requires native cmd.exe launcher resolution"
    )
    def test_windows_launcher_finds_supported_explicit_py_version(self) -> None:
        launcher_dir = Path(self.temporary.name) / "versioned launchers"
        launcher_dir.mkdir()
        launch_log = Path(self.temporary.name) / "versioned-launcher.log"
        supported_version = (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        (launcher_dir / "py.cmd").write_text(
            "\n".join(
                (
                    "@echo off",
                    "setlocal DisableDelayedExpansion",
                    '>>"%DEV_FLOW_LAUNCH_LOG%" echo py-%~1',
                    f'if not "%~1"=="-{supported_version}" exit /b 1',
                    'if "%~2"=="-c" "%DEV_FLOW_REAL_PYTHON%" -c "%~3"',
                    'if not "%~2"=="-c" "%DEV_FLOW_REAL_PYTHON%" "%~2"',
                    "exit /b %errorlevel%",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (launcher_dir / "python.cmd").write_text(
            "@echo off\nexit /b 1\n",
            encoding="utf-8",
        )
        document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        command = document["hooks"]["SessionStart"][0]["hooks"][0][
            "commandWindows"
        ]
        completed = subprocess.run(
            command,
            shell=True,
            input=json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "cwd": str(self.cwd),
                }
            ).encode("utf-8"),
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PATH": str(launcher_dir)
                + os.pathsep
                + os.environ.get("PATH", ""),
                "DEV_FLOW_LAUNCH_LOG": str(launch_log),
                "DEV_FLOW_REAL_PYTHON": sys.executable,
                "PLUGIN_ROOT": str(PLUGIN_ROOT),
                "PLUGIN_DATA": str(self.data_dir),
            },
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b"")
        self.assertIn(
            "Dev Flow controller bootstrap",
            completed.stdout.decode("utf-8"),
        )
        self.assertEqual(
            launch_log.read_text(encoding="utf-8").splitlines(),
            [
                "py--3",
                *[
                    f"py--3.{minor}"
                    for minor in range(14, sys.version_info.minor - 1, -1)
                ],
                f"py--{supported_version}",
            ],
        )

    def test_user_prompt_submit_uses_its_own_output_event_name(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        output = json.loads(stdout)
        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        context = specific["additionalContext"]
        locator = json.loads(context)
        self.assertEqual(locator["task_id"], "TASK-42")
        self.assertEqual(locator["condition"]["node_id"], "PLANNING")
        self.assertIn("show --task TASK-42 --next", locator["controller"])
        self.assertNotIn("\n", context)
        self.assertLessEqual(len(context.encode("utf-8")), 600)

    def test_user_prompt_submit_suppresses_same_session_and_exact_context(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        session_id = "session/private id/42"
        first, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": "turn-1",
                "prompt": "continue",
            }
        )
        context = json.loads(first)["hookSpecificOutput"]["additionalContext"]
        second, second_stderr = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": "turn-2",
                "prompt": "different prompt text",
            }
        )
        self.assertEqual(second, "")
        self.assertEqual(second_stderr, "")

        marker = self.checkpoint_marker(session_id)
        self.assertTrue(marker.is_file())
        self.assertNotIn(session_id, str(marker))
        document = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "dev-flow-hook-checkpoint/v1")
        self.assertEqual(
            document["session_sha256"],
            hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            document["context_sha256"],
            hashlib.sha256(context.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(session_id, marker.read_text(encoding="utf-8"))

    def test_session_start_always_emits_and_primes_compact_checkpoint(self) -> None:
        self.activate("IMPLEMENTING", pending_gate=None, next_action="run tests")
        session_id = "session-start-prime"
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": session_id,
            "source": "resume",
        }
        first, _ = self.invoke(payload)
        second, _ = self.invoke(payload)
        self.assertEqual(
            json.loads(first)["hookSpecificOutput"]["hookEventName"],
            "SessionStart",
        )
        self.assertEqual(
            json.loads(second)["hookSpecificOutput"]["hookEventName"],
            "SessionStart",
        )

        prompt, prompt_stderr = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": "turn-after-start",
                "prompt": "continue",
            }
        )
        self.assertEqual(prompt, "")
        self.assertEqual(prompt_stderr, "")

    def test_schema_v2_session_start_primes_equivalent_compact_checkpoint(
        self,
    ) -> None:
        state_file = self.activate(
            "PLANNING",
            pending_gate=None,
            next_action="write the approved plan",
        )
        self.upgrade_state_to_v2(state_file)
        session_id = "schema-v2-session"

        started, started_stderr = self.invoke(
            {
                "hook_event_name": "SessionStart",
                "session_id": session_id,
                "source": "resume",
            }
        )
        self.assertEqual(started_stderr, "")
        context = json.loads(started)["hookSpecificOutput"][
            "additionalContext"
        ]
        locator = json.loads(context)
        self.assertEqual(locator["revision"], 7)
        self.assertEqual(locator["condition"]["node_id"], "PLANNING")
        self.assertIn("show --task TASK-42 --next", locator["controller"])
        self.assertLessEqual(len(context.encode("utf-8")), 600)

        prompt, prompt_stderr = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": "turn-after-schema-v2-start",
                "prompt": "continue",
            }
        )
        self.assertEqual(prompt, "")
        self.assertEqual(prompt_stderr, "")

    def test_subagent_start_never_uses_user_prompt_checkpoint_marker(self) -> None:
        self.activate(
            "PLANNING",
            pending_gate=None,
            next_action="write the plan",
        )
        session_id = "parent-session-shared-with-subagent"
        subagent, subagent_stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "session_id": session_id,
                "turn_id": "turn-1",
                "agent_id": "agent-1",
                "agent_type": "reviewer",
            }
        )
        fallback = json.loads(
            json.loads(subagent)["hookSpecificOutput"][
                "additionalContext"
            ]
        )
        self.assertEqual(
            fallback["contract"],
            "dev-flow-subagent-serial-fallback/v1",
        )
        self.assertEqual(fallback["owner"], "manager")
        self.assertEqual(fallback["authority"], "none")
        self.assertEqual(subagent_stderr, "")
        self.assertFalse(self.checkpoint_marker(session_id).exists())

        prompt, prompt_stderr = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": "turn-1",
                "prompt": "continue",
            }
        )
        self.assertTrue(prompt)
        self.assertEqual(prompt_stderr, "")
        self.assertTrue(self.checkpoint_marker(session_id).is_file())

    def test_subagent_start_injects_only_exact_scoped_assignment(self) -> None:
        state_file = self.activate("IMPLEMENTING")
        assignment = self.add_worker_assignment(state_file)
        before = state_file.read_bytes()
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-7",
                "agent_type": "worker",
                "unsupported_host_field": {
                    "manager_secret": "must-not-leak"
                },
            }
        )
        self.assertEqual(stderr, "")
        output = json.loads(stdout)
        self.assertEqual(
            output["hookSpecificOutput"]["hookEventName"],
            "SubagentStart",
        )
        context = output["hookSpecificOutput"]["additionalContext"]
        projected = json.loads(context)
        self.assertEqual(projected["assignment"], assignment)
        self.assertEqual(
            projected["dispatch_mode"],
            "parallel-writable-worker",
        )
        self.assertEqual(
            projected["assignment"]["worktree_path"],
            str(self.cwd.resolve()),
        )
        self.assertEqual(
            projected["assignment"]["approved_paths"],
            ["src", "tests"],
        )
        self.assertEqual(
            projected["assignment"]["playbook_locator"],
            "playbooks/repository-implement.md",
        )
        self.assertNotIn("manager_secret", context)
        self.assertNotIn("manager-capability", context)
        self.assertNotIn("action.apply", context)
        self.assertNotIn(str(self.data_dir), context)
        self.assertEqual(state_file.read_bytes(), before)

    def test_subagent_start_serial_fallback_never_releases_assignment(
        self,
    ) -> None:
        state_file = self.activate("IMPLEMENTING")
        self.add_worker_assignment(
            state_file, parallel_dispatch_allowed=False
        )
        before = state_file.read_bytes()

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-7",
                "agent_type": "worker",
            }
        )

        self.assertEqual(stderr, "")
        context = json.loads(stdout)["hookSpecificOutput"][
            "additionalContext"
        ]
        fallback = json.loads(context)
        self.assertEqual(
            fallback["contract"],
            "dev-flow-subagent-serial-fallback/v1",
        )
        self.assertEqual(fallback["dispatch_mode"], "manager-serial")
        self.assertEqual(fallback["authority"], "none")
        self.assertNotIn("assignment", fallback)
        self.assertLessEqual(len(context.encode("utf-8")), 600)
        self.assertEqual(state_file.read_bytes(), before)

    def test_subagent_start_unsafe_assignment_is_not_injected(
        self,
    ) -> None:
        state_file = self.activate("IMPLEMENTING")
        assignment = self.add_worker_assignment(state_file)
        state = json.loads(state_file.read_text(encoding="utf-8"))
        persisted = state["orchestration"]["assignments"][
            assignment["assignment_id"]
        ]
        persisted["capabilities"].append("action.apply/v1")
        state_file.write_text(json.dumps(state), encoding="utf-8")

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-7",
            }
        )

        self.assertEqual(stderr, "")
        context = json.loads(stdout)["hookSpecificOutput"][
            "additionalContext"
        ]
        fallback = json.loads(context)
        self.assertEqual(
            fallback["contract"],
            "dev-flow-subagent-serial-fallback/v1",
        )
        self.assertNotIn("assignment", fallback)
        self.assertNotIn("action.apply/v1", context)

    def test_subagent_start_controller_projection_never_leaks_manager_secret(
        self,
    ) -> None:
        state_file = self.activate("IMPLEMENTING")
        secret = "manager-only-value-7"
        assignment = self.add_worker_assignment(
            state_file, manager_secret=secret
        )

        stdout, stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "agent-7",
            }
        )

        self.assertEqual(stderr, "")
        context = json.loads(stdout)["hookSpecificOutput"][
            "additionalContext"
        ]
        projection = json.loads(context)
        self.assertEqual(projection["assignment"], assignment)
        self.assertNotIn("manager_secret", context)
        self.assertNotIn(secret, context)
        self.assertNotIn(str(self.data_dir), context)

    def test_subagent_stop_requests_continuation_without_committing(self) -> None:
        state_file = self.activate("IMPLEMENTING")
        assignment = self.add_worker_assignment(state_file)
        before = state_file.read_bytes()
        missing, missing_stderr = self.invoke(
            {
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-7",
                "last_assistant_message": "work is done",
            }
        )
        self.assertEqual(missing_stderr, "")
        continuation = json.loads(missing)
        self.assertEqual(continuation["decision"], "block")
        self.assertIn("Continue", continuation["reason"])
        self.assertIn("<=2048", continuation["reason"])
        self.assertEqual(state_file.read_bytes(), before)

        result = self.node_result_for_assignment(assignment)
        accepted, accepted_stderr = self.invoke(
            {
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-7",
                "last_assistant_message": json.dumps(
                    result, separators=(",", ":"), sort_keys=True
                ),
            }
        )
        self.assertEqual(accepted, "")
        self.assertEqual(accepted_stderr, "")
        self.assertEqual(state_file.read_bytes(), before)

    def test_subagent_result_budget_and_unknown_assignment_fail_open(self) -> None:
        state_file = self.activate("IMPLEMENTING")
        self.add_worker_assignment(state_file)
        oversized, _ = self.invoke(
            {
                "hook_event_name": "SubagentStop",
                "agent_id": "agent-7",
                "last_assistant_message": json.dumps(
                    {"schema": "dev-flow-node-result/v1", "raw": "x" * 9000}
                ),
            }
        )
        self.assertEqual(json.loads(oversized)["decision"], "block")
        unknown, unknown_stderr = self.invoke(
            {
                "hook_event_name": "SubagentStart",
                "agent_id": "unknown-agent",
                "agent_type": ["unsupported"],
            }
        )
        fallback = json.loads(
            json.loads(unknown)["hookSpecificOutput"][
                "additionalContext"
            ]
        )
        self.assertEqual(
            fallback["contract"],
            "dev-flow-subagent-serial-fallback/v1",
        )
        self.assertNotIn("assignment", fallback)
        self.assertEqual(unknown_stderr, "")

    def test_compact_checkpoint_uses_session_start_wire_contract(self) -> None:
        state_file = self.activate("IMPLEMENTING")
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["revision"] = 9
        state_file.write_text(json.dumps(state), encoding="utf-8")
        session_id = "compact-session-9"
        before = state_file.read_bytes()

        pre, pre_stderr = self.invoke(
            {
                "hook_event_name": "PreCompact",
                "session_id": session_id,
                "trigger": "auto",
                "unsupported_host_field": ["ignored"],
            }
        )
        self.assertEqual(pre_stderr, "")
        self.assertEqual(json.loads(pre), {})
        marker = self.checkpoint_marker(session_id)
        document = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(document["task_id"], "TASK-42")
        self.assertEqual(document["revision"], 9)
        self.assertRegex(
            document["frontier_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            document["projection_contract"],
            "dev-flow-hook-checkpoint/v1",
        )

        post, post_stderr = self.invoke(
            {
                "hook_event_name": "PostCompact",
                "session_id": session_id,
                "compaction_id": "unsupported-but-safe",
            }
        )
        self.assertEqual(post_stderr, "")
        self.assertEqual(post, "")

        restored, restored_stderr = self.invoke(
            {
                "hook_event_name": "SessionStart",
                "session_id": session_id,
                "source": "compact",
            }
        )
        self.assertEqual(restored_stderr, "")
        locator = self.locator_payload(restored)
        self.assertEqual(locator["revision"], 9)
        self.assertEqual(locator["condition"]["node_id"], "IMPLEMENTING")
        encoded = json.dumps(
            locator,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), 600)
        self.assertTrue(locator["controller"].startswith("cli:"))
        self.assertIn("--next --profile agent-v1", locator["controller"])
        self.assertEqual(state_file.read_bytes(), before)

    def test_post_compact_emits_no_unsupported_hook_specific_output(
        self,
    ) -> None:
        self.activate("IMPLEMENTING")
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PostCompact",
                "turn_id": "turn-compact-wire",
                "trigger": "auto",
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

    def test_concurrent_corrupt_checkpoint_markers_fail_open(self) -> None:
        self.activate("PLANNING")
        session_id = "concurrent-corrupt"
        marker = self.checkpoint_marker(session_id)
        marker.parent.mkdir()
        marker.write_bytes(b"{corrupt")
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": "continue",
        }
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.invoke, payload) for _ in range(4)]
            results = [future.result() for future in futures]
        self.assertTrue(any(stdout for stdout, _ in results))
        self.assertTrue(all(stderr == "" for _, stderr in results))
        healed = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(healed["schema"], "dev-flow-hook-checkpoint/v1")
        self.assertEqual(healed["task_id"], "TASK-42")

    def test_checkpoint_is_scoped_by_session_and_compact_context(self) -> None:
        state_file = self.activate(
            "IMPLEMENTING", pending_gate=None, next_action="run tests"
        )
        first_session, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "prompt": "continue",
            }
        )
        second_session, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-b",
                "prompt": "continue",
            }
        )
        self.assertTrue(first_session)
        self.assertTrue(second_session)

        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["revision"] = 1
        state_file.write_text(json.dumps(state), encoding="utf-8")
        changed, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "prompt": "continue",
            }
        )
        changed_context = json.loads(changed)["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertEqual(json.loads(changed_context)["revision"], 1)
        repeated, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "session-a",
                "prompt": "continue again",
            }
        )
        self.assertEqual(repeated, "")

    def test_missing_or_invalid_session_id_fails_open_without_marker(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        for session_value in (None, "", "   ", ["not", "a", "string"]):
            with self.subTest(session_id=session_value):
                payload = {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "continue",
                }
                if session_value is not None:
                    payload["session_id"] = session_value
                first, _ = self.invoke(payload)
                second, _ = self.invoke(payload)
                self.assertTrue(first)
                self.assertTrue(second)
        self.assertFalse((self.data_dir / "hook-checkpoints").exists())

    def test_corrupt_or_unreadable_checkpoint_fails_open(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        session_id = "session-corrupt"
        marker = self.checkpoint_marker(session_id)
        marker.parent.mkdir()
        marker.write_text("{not-json", encoding="utf-8")

        emitted, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "prompt": "continue",
            }
        )
        self.assertTrue(emitted)
        healed = json.loads(marker.read_text(encoding="utf-8"))
        self.assertEqual(healed["schema"], "dev-flow-hook-checkpoint/v1")

        unreadable_session = "session-marker-is-directory"
        unreadable = self.checkpoint_marker(unreadable_session)
        unreadable.mkdir()
        first, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": unreadable_session,
                "prompt": "continue",
            }
        )
        second, _ = self.invoke(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": unreadable_session,
                "prompt": "continue",
            }
        )
        self.assertTrue(first)
        self.assertTrue(second)

    def test_checkpoint_write_failure_fails_open(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        (self.data_dir / "hook-checkpoints").write_text(
            "directory unavailable", encoding="utf-8"
        )
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "session-write-failure",
            "prompt": "continue",
        }
        first, first_stderr = self.invoke(payload)
        second, second_stderr = self.invoke(payload)
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(first_stderr, "")
        self.assertEqual(second_stderr, "")

    def test_checkpoint_is_not_written_when_stdout_flush_fails(self) -> None:
        self.activate("PLANNING", pending_gate=None, next_action="write the plan")
        spec = importlib.util.spec_from_file_location(
            "_dev_flow_hook_flush_failure", HOOK
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        session_id = "session-flush-failure"
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "prompt": "continue",
            "cwd": str(self.cwd),
        }

        class Input:
            buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

        class FlushFailureBuffer:
            def write(self, value: bytes) -> int:
                return len(value)

            def flush(self) -> None:
                raise OSError("simulated stdout flush failure")

        class Output:
            buffer = FlushFailureBuffer()

        with mock.patch.object(module.sys, "stdin", Input()):
            with mock.patch.object(module.sys, "stdout", Output()):
                with mock.patch.object(module.sys, "argv", [str(HOOK)]):
                    with mock.patch.dict(
                        module.os.environ,
                        {
                            "PLUGIN_ROOT": str(PLUGIN_ROOT),
                            "PLUGIN_DATA": str(self.data_dir),
                        },
                    ):
                        self.assertEqual(module.main(), 0)
        self.assertFalse(self.checkpoint_marker(session_id).exists())

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
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "TASK-42")
        self.assertEqual(locator["condition"]["node_id"], "INDEXED")
        self.assertLessEqual(
            len(
                json.dumps(
                    locator,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ),
            600,
        )

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
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "WORKSPACE_READY")
        self.assertIn("--next --profile agent-v1", locator["controller"])

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
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "IMPLEMENTING")

        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "BLOCKED"
        task["blocked"] = {"from_status": "INDEXED", "reason": "example"}
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "resume"}
        )
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "BLOCKED")
        self.assertEqual(locator["condition"]["kind"], "blocked")

    def test_context_uses_controller_gate_keys_and_stage_actions(self) -> None:
        state_file = self.activate(
            "PREFLIGHTED", pending_gate=None, next_action=None, approvals={}
        )
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "PREFLIGHTED")

        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "REVIEWING"
        task["approvals"] = {}
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}
        )
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "REVIEWING")

        task["status"] = "FINALIZING"
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["condition"]["node_id"], "FINALIZING")

    def test_current_core_layout_preserves_nonterminal_task_ambiguity(self) -> None:
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
        self.assertIn("Multiple non-terminal tasks match this repository", context)
        self.assertIn("no task was selected", context)
        self.assertIn("TASK-OLD", context)
        self.assertIn("TASK-NEW", context)
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
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "TASK-WORKSPACE")

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

    def test_context_events_diagnose_missing_plugin_environment(self) -> None:
        for event, extra in (
            ("SessionStart", {"source": "startup"}),
            ("UserPromptSubmit", {"prompt": "hello"}),
        ):
            for missing in ("PLUGIN_ROOT", "PLUGIN_DATA"):
                with self.subTest(event=event, missing=missing):
                    stdout, stderr = self.invoke(
                        {"hook_event_name": event, **extra},
                        include_plugin_root=missing != "PLUGIN_ROOT",
                        include_plugin_data=missing != "PLUGIN_DATA",
                    )
                    self.assertEqual(stderr, "")
                    specific = json.loads(stdout)["hookSpecificOutput"]
                    self.assertEqual(specific["hookEventName"], event)
                    context = specific["additionalContext"]
                    self.assertIn("Dev Flow hook diagnostic", context)
                    self.assertIn(f"{missing} is missing or empty", context)
                    self.assertIn("No controller command was constructed", context)
                    self.assertNotIn("Bootstrap command:", context)
                    self.assertNotIn("Resume command:", context)

    def test_bundled_environment_rejects_relative_blank_and_invalid_roots(
        self,
    ) -> None:
        missing_root = Path(self.temporary.name) / "missing-plugin"
        cases = (
            ({"PLUGIN_ROOT": "."}, "PLUGIN_ROOT must be an absolute path"),
            ({"PLUGIN_DATA": "."}, "PLUGIN_DATA must be an absolute path"),
            ({"PLUGIN_ROOT": "   "}, "PLUGIN_ROOT is missing or empty"),
            ({"PLUGIN_DATA": "\t"}, "PLUGIN_DATA is missing or empty"),
            (
                {"PLUGIN_ROOT": str(missing_root)},
                "PLUGIN_ROOT does not contain scripts/dev_flow.py",
            ),
        )
        for environment, expected in cases:
            with self.subTest(environment=environment):
                stdout, stderr = self.invoke(
                    {"hook_event_name": "SessionStart", "source": "startup"},
                    env=environment,
                )
                self.assertEqual(stderr, "")
                context = json.loads(stdout)["hookSpecificOutput"][
                    "additionalContext"
                ]
                self.assertIn(expected, context)
                self.assertIn("No controller command was constructed", context)
                self.assertNotIn("Bootstrap command:", context)

    def test_pre_tool_use_missing_environment_is_diagnostic_not_denial(self) -> None:
        for missing in ("PLUGIN_ROOT", "PLUGIN_DATA"):
            with self.subTest(missing=missing):
                stdout, stderr = self.invoke(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_name": "Bash",
                        "tool_input": {"command": "git reset --hard HEAD"},
                    },
                    include_plugin_root=missing != "PLUGIN_ROOT",
                    include_plugin_data=missing != "PLUGIN_DATA",
                )
                self.assertEqual(stderr, "")
                specific = json.loads(stdout)["hookSpecificOutput"]
                self.assertEqual(specific["hookEventName"], "PreToolUse")
                self.assertNotIn("permissionDecision", specific)
                context = specific["additionalContext"]
                self.assertIn(f"{missing} is missing or empty", context)
                self.assertIn("no workflow state was mutated", context)

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

    def test_posix_redirections_cannot_bypass_destructive_git_guardrails(self) -> None:
        self.activate("INTAKE")
        reset_commands = (
            "> out.txt git reset --hard HEAD",
            "2>/dev/null git reset --hard HEAD",
            "git > out.txt reset --hard HEAD",
            "git 2>/dev/null reset --hard HEAD",
            "git 2>&1 reset --hard HEAD",
            "git <&0 reset --hard HEAD",
            "git >|out.txt reset --hard HEAD",
            "git <<< input reset --hard HEAD",
            "git <<'EOF' reset --hard HEAD\nignored\nEOF",
            "bash -lc '> out.txt git reset --hard HEAD'",
            "bash -lc '2>/dev/null git reset --hard HEAD'",
            "bash -lc 'git > out.txt reset --hard HEAD'",
        )
        for command in reset_commands:
            with self.subTest(command=command):
                reason = self.assert_denied(command)
                self.assertIn("git reset --hard", reason)
        self.assertIn("git clean", self.assert_denied("> out.txt git clean -fd"))

    def test_posix_redirections_preserve_benign_git_commands(self) -> None:
        self.activate("IMPLEMENTING")
        commands = (
            "git status --short > status.txt",
            "> status.txt git status --short",
            "2>/dev/null git status --short",
            "git 2>&1 status --short",
            "git >|status.txt status --short",
            "git <<< input status --short",
            "bash -lc 'git > status.txt status --short'",
            "cat <<'EOF'\ngit reset --hard HEAD\nEOF",
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

    def test_protected_git_decision_is_equivalent_across_executables_and_wrappers(
        self,
    ) -> None:
        self.activate("INTAKE")
        commands = (
            "git reset --hard HEAD",
            "git.exe reset --hard HEAD",
            "/usr/bin/git reset --hard HEAD",
            '"C:/Program Files/Git/cmd/git.exe" reset --hard HEAD',
            r'"C:\Program Files\Git\cmd\git.exe" reset --hard HEAD',
            r"C:\Git\cmd\git.exe reset --hard HEAD",
            r'"\\server\share\Git\cmd\git.exe" reset --hard HEAD',
            r"/opt/Git\ Tools/bin/git reset --hard HEAD",
            "sh -c 'git reset --hard HEAD'",
            "bash -lc 'echo safe && git reset --hard HEAD'",
            'cmd.exe /d /s /c "echo safe && git.exe reset --hard HEAD"',
            r"cmd.exe /c C:\Program^ Files\Git\cmd\git.exe reset --hard HEAD",
            (
                'cmd.exe /d /s /c ""C:\\Program Files\\Git\\cmd\\git.exe" '
                'reset --hard HEAD"'
            ),
            (
                'powershell.exe -NoProfile -Command '
                '"Write-Output safe; git.exe reset --hard HEAD"'
            ),
            (
                "pwsh -Command "
                "'& \"C:\\Program Files\\Git\\cmd\\git.exe\" reset --hard HEAD'"
            ),
            (
                "pwsh -Command "
                r"'& C:\Program` Files\Git\cmd\git.exe reset --hard HEAD'"
            ),
        )
        expected: str | None = None
        for command in commands:
            with self.subTest(command=command):
                reason = self.assert_denied(command)
                self.assertIn("git reset --hard", reason)
                if expected is None:
                    expected = reason
                self.assertEqual(reason, expected)

    def test_benign_git_decision_is_equivalent_across_wrappers(self) -> None:
        self.activate("IMPLEMENTING")
        commands = (
            "git status --short",
            "git.exe status --short",
            '"C:/Program Files/Git/cmd/git.exe" status --short',
            r'"C:\Program Files\Git\cmd\git.exe" status --short',
            r'"\\server\share\Git\cmd\git.exe" status --short',
            r"/opt/Git\ Tools/bin/git status --short",
            "sh -c 'git status --short'",
            "bash -lc 'echo safe && git status --short'",
            "bash -lc 'git status -- \\$literal'",
            "bash -lc \"git status -- '\\$literal'\"",
            'cmd.exe /d /s /c "echo safe && git.exe status --short"',
            r"cmd.exe /c C:\Program^ Files\Git\cmd\git.exe status --short",
            (
                'cmd.exe /d /s /c ""C:\\Program Files\\Git\\cmd\\git.exe" '
                'status --short"'
            ),
            (
                'powershell.exe -NoProfile -Command '
                '"Write-Output safe; git.exe status --short"'
            ),
            (
                "pwsh -Command "
                "'& \"C:\\Program Files\\Git\\cmd\\git.exe\" status --short'"
            ),
            'pwsh -Command "git status -- \'$literal\'"',
            "pwsh -Command 'git status -- `$literal'",
            (
                "pwsh -Command "
                r"'& C:\Program` Files\Git\cmd\git.exe status --short'"
            ),
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

    def test_ambiguous_recognized_wrappers_are_denied_with_diagnostics(self) -> None:
        self.activate("INTAKE")
        commands = (
            "bash -lc '$GIT reset --hard HEAD'",
            'cmd.exe /c "%GIT% reset --hard HEAD"',
            "powershell.exe -Command '& $git reset --hard HEAD'",
            "pwsh -EncodedCommand Z2l0IHJlc2V0IC0taGFyZA==",
            "bash -lc 'echo $DYNAMIC_COMMAND'",
            "bash workflow-script.sh",
            'cmd.exe /c "echo %DYNAMIC_COMMAND%"',
            "cmd.exe /k git reset --hard HEAD",
            "pwsh -Command 'Write-Output $dynamicCommand'",
            'powershell.exe -Command "& (Get-Command git) reset --hard HEAD"',
            'cmd.exe /c "git reset --hard',
            'powershell.exe -Command "git reset --hard',
        )
        for command in commands:
            with self.subTest(command=command):
                reason = self.assert_denied(command)
                self.assertIn("could not be inspected safely", reason)

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

    def test_lite_task_checkpoint_names_flow_gate_and_no_index_role(self) -> None:
        self.write_core_state(
            "LITE-7",
            "PREFLIGHTED",
            flow="lite",
            route=None,
            next_action=None,
        )
        stdout, stderr = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        self.assertEqual(stderr, "")
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "LITE-7")
        self.assertEqual(locator["condition"]["node_id"], "PREFLIGHTED")
        self.assertLessEqual(
            len(
                json.dumps(
                    locator,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ),
            600,
        )

    def test_lite_branch_checkpoint_uses_the_user_selected_chinese_name(self) -> None:
        self.write_core_state(
            "LITE-BRANCH",
            "INTAKE",
            flow="lite",
            route=None,
            workspace={"strategy": "branch"},
            next_action=None,
        )
        stdout, stderr = self.invoke(
            {"hook_event_name": "SessionStart", "source": "resume"}
        )
        self.assertEqual(stderr, "")
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "LITE-BRANCH")
        self.assertEqual(locator["condition"]["node_id"], "INTAKE")

    def test_lite_task_source_writes_follow_the_stage(self) -> None:
        state_file = self.write_core_state(
            "LITE-7",
            "PREFLIGHTED",
            flow="lite",
        )
        artifacts = self.data_dir / "tasks" / "LITE-7" / "artifacts"
        artifacts.mkdir(parents=True)

        # Before implementation, only the artifacts directory is writable.
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.cwd / "bug.py")},
            }
        )
        specific = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], "deny")
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(artifacts / "scope.md")},
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

        # During implementation the source checkout itself is the workspace.
        task = json.loads(state_file.read_text(encoding="utf-8"))
        task["status"] = "IMPLEMENTING"
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, stderr = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.cwd / "bug.py")},
            }
        )
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")

        # A blocked lite task blocks writes again.
        task["status"] = "BLOCKED"
        state_file.write_text(json.dumps(task), encoding="utf-8")
        stdout, _ = self.invoke(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.cwd / "bug.py")},
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

    def test_bootstrap_is_silent_outside_the_configured_scope(self) -> None:
        included = Path(self.temporary.name) / "included"
        included.mkdir()
        self.write_scope(include=[included])
        for event in ("SessionStart", "UserPromptSubmit"):
            with self.subTest(event=event):
                stdout, stderr = self.invoke({"hook_event_name": event})
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "")
        stdout, _ = self.invoke({"hook_event_name": "SessionStart"}, cwd=included)
        self.assertIn(
            "Dev Flow controller bootstrap",
            json.loads(stdout)["hookSpecificOutput"]["additionalContext"],
        )

    def test_scope_accepts_subdirectories_and_the_environment_override(self) -> None:
        nested = self.cwd / "packages" / "api"
        nested.mkdir(parents=True)
        excluded = self.cwd / "vendor"
        excluded.mkdir()
        self.write_scope(include=[self.cwd], exclude=[excluded])
        stdout, _ = self.invoke({"hook_event_name": "SessionStart"}, cwd=nested)
        self.assertIn("Dev Flow controller bootstrap", stdout)
        stdout, _ = self.invoke({"hook_event_name": "SessionStart"}, cwd=excluded)
        self.assertEqual(stdout, "")
        # The environment override replaces the stored included directories.
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        override = {"DEV_FLOW_SCOPE": str(outside)}
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart"}, cwd=outside, env=override
        )
        self.assertIn("Dev Flow controller bootstrap", stdout)
        stdout, _ = self.invoke(
            {"hook_event_name": "SessionStart"}, cwd=nested, env=override
        )
        self.assertEqual(stdout, "")

    def test_active_task_keeps_hooks_enabled_outside_the_scope(self) -> None:
        self.activate(
            "IMPLEMENTING",
            repository={
                "id": "repo",
                "path": str(self.cwd),
                "preflight": {"branch": "main"},
            },
        )
        included = Path(self.temporary.name) / "included"
        included.mkdir()
        self.write_scope(include=[included])
        stdout, _ = self.invoke({"hook_event_name": "SessionStart"})
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "TASK-42")
        self.assertIn(
            "Direct commits on protected branch",
            self.assert_denied("git commit -m 'out of scope'"),
        )

    def test_in_scope_checkpoint_omits_the_scope_notice(self) -> None:
        self.activate("IMPLEMENTING")
        self.write_scope(include=[self.cwd])
        stdout, _ = self.invoke({"hook_event_name": "SessionStart"})
        locator = self.locator_payload(stdout)
        self.assertEqual(locator["task_id"], "TASK-42")

    def test_unreadable_scope_configuration_keeps_the_hook_active(self) -> None:
        (self.data_dir / "config.json").write_text("{ not json", encoding="utf-8")
        stdout, stderr = self.invoke({"hook_event_name": "SessionStart"})
        self.assertEqual(stderr, "")
        self.assertIn("Dev Flow controller bootstrap", stdout)


if __name__ == "__main__":
    unittest.main()
