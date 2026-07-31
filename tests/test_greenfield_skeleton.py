from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.engine import NODE_FAMILY_CATALOG
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import PROFILES
from dev_flow_orchestrator import workflow as workflow_module
from dev_flow_orchestrator.workflow import workflow_identity


class GreenfieldSkeletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = self.root / "data"
        self.repositories = [
            self._repository("repo-one"),
            self._repository("repo-two"),
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _repository(self, name: str) -> Path:
        repository = self.root / name
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(repository)],
            check=True,
        )
        (repository / "README.md").write_text(name + "\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository), "add", "README.md"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
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
        return repository

    def test_product_matrix_has_exactly_four_profiles(self) -> None:
        self.assertEqual(
            set(PROFILES),
            {
                ("full", "single-repository"),
                ("full", "multi-repository"),
                ("lite", "single-repository"),
                ("lite", "multi-repository"),
            },
        )

    def test_all_four_profiles_create_schema_v4_tasks(self) -> None:
        controller = Controller(str(self.data_dir))
        selections = [
            ("full", self.repositories[:1]),
            ("full", self.repositories),
            ("lite", self.repositories[:1]),
            ("lite", self.repositories),
        ]
        for index, (workflow, repositories) in enumerate(selections):
            state = controller.start(
                requirement="profile {}".format(index),
                workflow=workflow,
                workspace_strategy="in-place",
                repositories=[str(path) for path in repositories],
                task_id="profile-{}".format(index),
            )
            self.assertEqual(state.schema_version, 4)
            self.assertEqual(state.workflow_id, workflow)
            self.assertEqual(
                state.topology,
                (
                    "single-repository"
                    if len(repositories) == 1
                    else "multi-repository"
                ),
            )
            self.assertEqual(
                state.workflow_identity,
                workflow_identity(state.workflow_id, state.topology),
            )

    def test_data_directory_must_be_outside_every_repository(self) -> None:
        repository = self.repositories[0]
        candidates = (
            repository,
            repository / ".dev-flow-data",
        )
        alias = self.root / "repository-alias"
        alias.symlink_to(repository, target_is_directory=True)
        candidates = (*candidates, alias / ".dev-flow-data")
        for index, candidate in enumerate(candidates):
            with self.subTest(candidate=candidate):
                controller = Controller(str(candidate))
                with self.assertRaises(DevFlowError) as captured:
                    controller.start(
                        requirement="isolated state",
                        workflow="lite",
                        workspace_strategy="in-place",
                        repositories=[str(repository)],
                        task_id="inside-{}".format(index),
                    )
                self.assertEqual(
                    captured.exception.code,
                    "DATA_DIR_INSIDE_REPOSITORY",
                )
                self.assertFalse(
                    (
                        candidate.resolve()
                        / "tasks"
                        / "inside-{}".format(index)
                        / "state.json"
                    ).exists()
                )

    def test_persisted_task_is_bound_to_the_installed_workflow_graph(self) -> None:
        controller = Controller(str(self.data_dir))
        state = controller.start(
            requirement="pin graph",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repositories[0])],
            task_id="graph-pin",
        )
        self.assertEqual(len(state.workflow_identity), 64)
        path = self.data_dir / "tasks" / "graph-pin" / "state.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["workflow"]["identity"] = "0" * 64
        path.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(DevFlowError) as captured:
            controller.show("graph-pin")
        self.assertEqual(captured.exception.code, "WORKFLOW_IDENTITY_MISMATCH")

    def test_workflow_identity_covers_entry_and_shared_cancel_contracts(self) -> None:
        original = workflow_identity("lite", "multi-repository")
        with mock.patch.object(
            workflow_module,
            "PREFLIGHT_CONTRACT",
            replace(
                workflow_module.PREFLIGHT_CONTRACT,
                effect_port="git.changed-entry",
            ),
        ):
            self.assertNotEqual(
                workflow_identity("lite", "multi-repository"),
                original,
            )
        with mock.patch.object(
            workflow_module,
            "REPOSITORY_CANCEL_CONTRACT",
            replace(
                workflow_module.REPOSITORY_CANCEL_CONTRACT,
                required_authority="task-revision+changed-manager",
            ),
        ):
            self.assertNotEqual(
                workflow_identity("lite", "multi-repository"),
                original,
            )

    def test_every_executable_contract_binds_a_direct_handler_and_effect_port(
        self,
    ) -> None:
        contracts = [
            workflow_module.PREFLIGHT_CONTRACT,
            workflow_module.REPOSITORY_CANCEL_CONTRACT,
            *workflow_module.FULL_GRAPH.values(),
            *workflow_module.LITE_GRAPH.values(),
            *workflow_module.REPOSITORY_GRAPH.values(),
        ]
        for contract in contracts:
            with self.subTest(action=contract.action_id):
                family = NODE_FAMILY_CATALOG[contract.handler_id]
                self.assertTrue(callable(family.handler))
                self.assertEqual(family.effect_port, contract.effect_port)

    def test_lite_multi_repository_does_not_require_full(self) -> None:
        controller = Controller(str(self.data_dir))
        state = controller.start(
            requirement="small coordinated edit",
            workflow="lite",
            workspace_strategy="branch",
            repositories=[str(path) for path in self.repositories],
            task_id="lite-multi",
        )
        self.assertEqual(state.workflow_id, "lite")
        self.assertEqual(state.topology, "multi-repository")
        controller.preflight("lite-multi", 0)
        state = controller.show("lite-multi")
        self.assertEqual(state.status, "ORCHESTRATING")
        self.assertEqual(state.current_node, "repository-plan")

    def test_state_permissions_are_private(self) -> None:
        state = Controller(str(self.data_dir)).start(
            requirement="private state",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repositories[0])],
            task_id="private",
        )
        state_path = self.data_dir / "tasks" / "private" / "state.json"
        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(state_path.parent.stat().st_mode),
            0o700,
        )
        with self.assertRaises(AttributeError):
            state.repositories[0].workspace = {"path": "changed"}

    def test_preflight_records_git_evidence(self) -> None:
        controller = Controller(str(self.data_dir))
        controller.start(
            requirement="preflight",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repositories[0])],
            task_id="preflight",
        )
        receipt = controller.preflight("preflight", 0)
        state = controller.show("preflight")
        self.assertEqual(receipt.committed_revision, 1)
        self.assertEqual(state.status, "IMPLEMENTING")
        self.assertEqual(state.current_node, "implement")
        self.assertEqual(
            state.repositories[0].preflight["repository_root"],
            str(self.repositories[0].resolve()),
        )

    def test_packaged_user_prompt_uses_the_shared_data_directory(self) -> None:
        controller = Controller(str(self.data_dir))
        controller.start(
            requirement="packaged confirmation route",
            workflow="lite",
            workspace_strategy="in-place",
            repositories=[str(self.repositories[0])],
            task_id="packaged-hook",
        )
        controller.preflight("packaged-hook", 0)
        with self.assertRaises(DevFlowError) as captured:
            controller.apply(
                "packaged-hook",
                1,
                "task.implementation.complete",
                {"summary": "implemented"},
                session_id="packaged-session",
                request_turn_id="request-turn",
            )
        self.assertEqual(captured.exception.code, "CONFIRMATION_REQUIRED")
        request_id = captured.exception.details["confirmation"]["request_id"]

        hooks = json.loads(
            (ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )
        user_prompt = hooks["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(user_prompt), 1)
        self.assertEqual(len(user_prompt[0]["hooks"]), 1)
        self.assertEqual(
            user_prompt[0]["hooks"][0]["command"],
            '"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" '
            '"$PLUGIN_ROOT/hooks/dev_flow_hook.py"',
        )

        cache_parent = self.root / "installed cache with spaces"
        cache_parent.mkdir()
        installed_root = cache_parent / "dev-flow-orchestrator"
        installed_root.symlink_to(ROOT, target_is_directory=True)
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "packaged-session",
            "turn_id": "reply-turn",
            "cwd": str(self.repositories[0]),
            "prompt": "approve " + request_id,
        }
        environment = os.environ.copy()
        environment["PLUGIN_DATA"] = str(self.data_dir)
        completed = subprocess.run(
            [
                str(installed_root / "scripts" / "dev_flow_python_launcher"),
                str(installed_root / "hooks" / "dev_flow_hook.py"),
            ],
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.repositories[0]),
            env=environment,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        output = json.loads(completed.stdout.decode("utf-8"))
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"status":"CONFIRMED"', context)
        self.assertEqual(controller.show("packaged-hook").revision, 1)
        self.assertEqual(
            controller.next(
                "packaged-hook",
                session_id="packaged-session",
            )["confirmation"]["status"],
            "CONFIRMED",
        )

    def test_stale_preflight_is_rejected_before_effect(self) -> None:
        controller = Controller(str(self.data_dir))
        controller.start(
            requirement="stale",
            workflow="full",
            workspace_strategy="worktree",
            repositories=[str(self.repositories[0])],
            task_id="stale",
        )
        with self.assertRaises(DevFlowError) as captured:
            controller.preflight("stale", 1)
        self.assertEqual(captured.exception.code, "REVISION_CONFLICT")
        self.assertEqual(controller.show("stale").revision, 0)

    def test_isolated_cli_returns_one_json_object(self) -> None:
        command = [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "dev_flow.py"),
            "--data-dir",
            str(self.data_dir),
            "start",
            "--requirement",
            "cli skeleton",
            "--workflow",
            "lite",
            "--workspace-strategy",
            "in-place",
            "--repo",
            str(self.repositories[0]),
            "--task-id",
            "cli-skeleton",
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        lines = completed.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(json.loads(lines[0])["ok"])

    def test_architecture_validator_accepts_skeleton(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "validate_greenfield_architecture.py"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout.decode())
        result = json.loads(completed.stdout.decode("utf-8"))
        self.assertTrue(result["runtime_present"])
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
