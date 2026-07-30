from __future__ import annotations

import argparse
import contextlib
import dataclasses
import errno
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
from types import MappingProxyType


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"
SUPPORT = Path(__file__).resolve().with_name("support.py")
SPEC = importlib.util.spec_from_file_location("dev_flow", SCRIPT)
assert SPEC and SPEC.loader
dev_flow = importlib.util.module_from_spec(SPEC)
sys.modules["dev_flow"] = dev_flow
SPEC.loader.exec_module(dev_flow)


def inactive_workflow_runtime_services() -> object:
    """Freeze legacy regression tests below the v3 activation boundary."""

    services = dev_flow.workflow_runtime_services()
    activations = tuple(
        MappingProxyType(
            {
                **dict(item),
                "active": False,
                "required_suites": [],
            }
        )
        for item in services.catalog.activations
    )
    return dataclasses.replace(
        services,
        catalog=dataclasses.replace(
            services.catalog,
            activations=activations,
        ),
    )


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


class DevFlowTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.data = self.root / "state"
        git_home = self.root / "isolated git home"
        git_home.mkdir()
        self.environment = mock.patch.dict(
            os.environ,
            {
                "HOME": str(git_home),
                "USERPROFILE": str(git_home),
                "XDG_CONFIG_HOME": str(git_home / "xdg"),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )
        self.environment.start()
        # The production candidate activates schema-v3 creation. Historical
        # CLI/state regression cases must continue to exercise the frozen v2
        # adapters explicitly; v3 suites opt back into an exact profile.
        self.workflow_runtime = mock.patch.object(
            dev_flow,
            "_workflow_runtime_services",
            inactive_workflow_runtime_services(),
        )
        self.workflow_runtime.start()
        self.workspace_plan_fixture_counter = 0

    def tearDown(self) -> None:
        self.workflow_runtime.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def make_repo(self, name: str) -> tuple[Path, Path]:
        repo = self.root / name
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(repo)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repo, "config", "user.name", "Dev Flow Test")
        git(repo, "config", "user.email", "dev-flow@example.invalid")
        (repo / "tracked.txt").write_text(f"initial {name}\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "initial")
        remote = self.root / f"{name}.git"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(repo), str(remote)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "fetch", "-q", "origin")
        git(repo, "remote", "set-head", "origin", "main")
        return repo, remote

    def cli(self, *arguments: str, expected_code: int = 0) -> dict:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = dev_flow.main([*arguments, "--data-dir", str(self.data)])
        self.assertEqual(code, expected_code, stdout.getvalue())
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1, stdout.getvalue())
        return json.loads(lines[0])

    def controller_process(
        self, *arguments: str
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                *arguments,
                "--data-dir",
                str(self.data),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )

    def process_response(
        self, process: subprocess.Popen[bytes]
    ) -> tuple[int, dict]:
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(stderr, b"")
        self.assertTrue(stdout.endswith(b"\n"), stdout)
        self.assertNotIn(b"\r\n", stdout)
        lines = stdout.splitlines()
        self.assertEqual(len(lines), 1, stdout)
        return process.returncode, json.loads(lines[0].decode("utf-8"))

    def wait_for_path(self, path: Path, process: subprocess.Popen[bytes]) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(
                    f"helper exited before creating {path}: "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            time.sleep(0.01)
        self.fail(f"timed out waiting for helper marker: {path}")

    def current_workspace_plan(
        self,
        repository_id: str,
        source: Path,
        destination: Path,
        branch: str,
        base_sha: str,
        *,
        previously_recorded: bool = False,
    ) -> dict:
        """Build and claim a controller-current low-level worktree plan."""

        self.workspace_plan_fixture_counter += 1
        source = source.resolve(strict=True)
        destination = destination.resolve(strict=False)
        task_id = (
            f"fixture-plan-{self.workspace_plan_fixture_counter}"
        )
        source_profile = dev_flow._git_capability_profile(source)
        destination_profile = dev_flow._git_capability_profile(
            source, destination
        )
        branch_state = dev_flow._branch_ref_state(source, branch, [])
        plan = {
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "repository_id": repository_id,
            "source_path": str(source),
            "source_identity": dev_flow._serializable_path_identity(
                source
            ),
            "path": str(destination),
            "path_identity": dev_flow._serializable_path_identity(
                destination
            ),
            "branch": branch,
            "branch_ref": branch_state["branch_ref"],
            "planned_ref_oid": branch_state["planned_ref_oid"],
            "ref_case_sensitive": branch_state[
                "ref_case_sensitive"
            ],
            "ref_unicode_normalization_distinct": branch_state[
                "ref_unicode_normalization_distinct"
            ],
            "source_common_dir": branch_state["git_common_dir"],
            "source_common_dir_identity": branch_state[
                "git_common_dir_identity"
            ],
            "base_sha": base_sha,
            "capability_profile": destination_profile,
            "capability_profile_sha256": destination_profile["sha256"],
            "source_capability_profile_sha256": source_profile["sha256"],
            "strategy": "worktree",
            "owner_task_id": task_id,
            "workspace_generation": 0,
            "previously_recorded": previously_recorded,
        }
        claim_root = (
            self.root
            / "workspace plan claims"
            / str(self.workspace_plan_fixture_counter)
        )
        plan_sha256 = dev_flow._sha256_bytes(
            dev_flow._json_bytes(
                {
                    key: value
                    for key, value in plan.items()
                    if key != "capability_profile"
                }
            )
        )
        dev_flow._claim_workspace_plan(
            claim_root,
            {
                "task_id": task_id,
                "repositories": [],
                "workspace": {"generation": 0},
            },
            plan_sha256,
            [plan],
        )
        return plan

    def canonical(self, *paths: Path) -> list[str]:
        """Scope directories are stored resolved; temp roots may be symlinked."""

        return sorted(str(path.resolve()) for path in paths)

    def start(self, *repos: Path, task_id: str = "task-1") -> dict:
        arguments = [
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "Implement deterministic flow",
        ]
        for repo in repos:
            arguments.extend(["--repo", str(repo)])
        return self.cli(*arguments)

    def mutate(
        self, command: str, task: dict, *arguments: str, expected_code: int = 0
    ) -> dict:
        if (
            command == "record-artifact"
            and "--kind" in arguments
            and arguments[arguments.index("--kind") + 1] == "impact"
            and "--metadata-json" not in arguments
        ):
            repositories = []
            degraded = False
            for repository in task.get("repositories", []):
                index = repository.get("index") or {}
                index_id = index.get("index_id")
                if not index_id:
                    degraded = True
                checks = {
                    name: {"status": "complete"}
                    for name in dev_flow.IMPACT_CHECKS
                }
                unknowns = []
                if not index_id:
                    checks["source_confirmation"] = {
                        "status": "degraded",
                        "reason": "baseline index unavailable in test fixture",
                    }
                    unknowns.append("baseline index unavailable")
                receipt = index.get("receipt") or {}
                metadata = index.get("metadata") or {}
                repositories.append(
                    {
                        "repository_id": repository["id"],
                        "index_id": index_id,
                        "index_mode": (
                            receipt.get("mode")
                            or metadata.get("mode")
                            or "fast"
                        ),
                        "checks": checks,
                        "queries": {
                            name: 0
                            for name in dev_flow.IMPACT_QUERY_KEYS
                        },
                        "unresolved_truncations": [],
                        "material_unknowns": unknowns,
                    }
                )
            cross_status = (
                "complete"
                if len(repositories) > 1 and not degraded
                else "degraded"
                if len(repositories) > 1
                else "not_applicable"
            )
            cross = {"status": cross_status}
            if cross_status != "complete":
                cross["reason"] = (
                    "baseline index unavailable in test fixture"
                    if degraded
                    else "single repository test fixture"
                )
            contract = {
                "schema": "dev-flow-impact-analysis/v1",
                "strategy": "funnel",
                "coverage": "degraded" if degraded else "complete",
                "budget_profile": "seed-v1",
                "repositories": repositories,
                "cross_repository": cross,
            }
            arguments = (
                *arguments,
                "--metadata-json",
                json.dumps(contract, sort_keys=True),
            )
        if command == "preflight":
            preview = self.cli(
                command,
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                *arguments,
                "--preview",
                expected_code=expected_code,
            )
            if expected_code != 0:
                return preview
            return self.cli(
                command,
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                *arguments,
                "--confirm-preview",
                preview["transition_preview"]["token"],
            )
        if (
            command in {"transition", "cancel"}
            and expected_code == 0
            and int(task.get("schema_version", 1))
            >= dev_flow.TASK_SCHEMA_VERSION
            and "--preview" not in arguments
            and "--confirm-intent" not in arguments
        ):
            target = "CANCELLED"
            if command == "transition":
                if "--to" in arguments:
                    target = arguments[arguments.index("--to") + 1]
                else:
                    target = next(
                        (
                            value
                            for value in arguments
                            if value in dev_flow.ALL_STATES
                        ),
                        None,
                    )
            needs_preview = command == "cancel" or (
                target is not None
                and dev_flow._transition_confirmation_mode(
                    task, task["status"], target
                )
                == "explicit"
            )
            if needs_preview:
                preview = self.cli(
                    command,
                    task["task_id"],
                    "--expected-revision",
                    str(task["revision"]),
                    *arguments,
                    "--preview",
                )
                intent = preview.get("preview")
                if isinstance(intent, dict) and intent.get(
                    "requires_confirmation"
                ):
                    return self.cli(
                        command,
                        task["task_id"],
                        "--expected-revision",
                        str(task["revision"]),
                        *arguments,
                        "--confirm-intent",
                        intent["intent_id"],
                    )
        return self.cli(
            command,
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            *arguments,
            expected_code=expected_code,
        )

    def ready_workspace_task(
        self, *repos: Path, task_id: str = "workspace-task"
    ) -> dict:
        task = self.start(*repos, task_id=task_id)["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local baseline and analysis worktree approved",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task_id, self.data)
        for repository in task["repositories"]:
            self.mutate(
                "record-index",
                task,
                "--repo",
                repository["id"],
                "--index-id",
                dev_flow._recommended_index_name(
                    task, repository, "baseline"
                ),
            )
            task = dev_flow.load_state(task_id, self.data)
        impact = self.root / f"{task_id}-impact.md"
        impact.write_text("current impact\n", encoding="utf-8")
        impact_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "bounded test change",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "impact and direct route approved",
            "--artifact-sha256",
            impact_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        workspace_plan = self.mutate("prepare-workspace", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "workspace plan approved",
            "--artifact-sha256",
            workspace_plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("prepare-workspace", task, "--execute")
        return dev_flow.load_state(task_id, self.data)

    def route_approved_task(
        self, *repos: Path, task_id: str
    ) -> dict:
        """Create a current full-flow task immediately before workspace planning."""

        task = self.start(*repos, task_id=task_id)["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "fixture baseline approved",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task_id, self.data)
        for repository in task["repositories"]:
            self.mutate(
                "record-index",
                task,
                "--repo",
                repository["id"],
                "--index-id",
                dev_flow._recommended_index_name(
                    task, repository, "baseline"
                ),
            )
            task = dev_flow.load_state(task_id, self.data)
        impact = self.root / f"{task_id} current impact.md"
        impact.write_text("current impact\n", encoding="utf-8")
        recorded = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "bounded fixture route",
        )
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "fixture route approved",
            "--artifact-sha256",
            recorded["artifact"]["sha256"],
        )
        return dev_flow.load_state(task_id, self.data)

    def record_workspace_indexes(
        self,
        task: dict,
        *,
        receipt: Path | None = None,
        metadata: dict | None = None,
    ) -> dict:
        for repository in task["repositories"]:
            arguments = [
                "--role",
                "workspace",
                "--repo",
                repository["id"],
                "--index-id",
                dev_flow._recommended_index_name(
                    task, repository, "workspace"
                ),
                "--metadata-json",
                json.dumps(
                    {"persistence": False}
                    if metadata is None
                    else metadata
                ),
            ]
            if receipt is not None:
                arguments.extend(["--receipt", str(receipt)])
            self.mutate("record-index", task, *arguments)
            task = dev_flow.load_state(task["task_id"], self.data)
        return task

    def route_indexed_task_to_workspace(self, task: dict) -> dict:
        self.assertEqual(task["status"], "INDEXED")
        impact = self.root / (
            f"{task['task_id']}-history-impact-"
            f"r{task.get('impact_generation', 0)}.md"
        )
        impact.write_text("history-aware impact\n", encoding="utf-8")
        impact_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "impact",
            "--path",
            str(impact),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "set-route",
            task,
            "direct",
            "--reason",
            "bounded history test",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "history-aware impact approved",
            "--artifact-sha256",
            impact_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        plan = self.mutate("prepare-workspace", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "history test workspace approved",
            "--artifact-sha256",
            plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        return dev_flow.load_state(task["task_id"], self.data)
