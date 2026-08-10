"""Focused exact-set Controller and CLI coverage for the current product."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.model import DevFlowError, json_value
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    PLUGIN_DATA_NAMESPACE,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
)
from support import (
    hermetic_subprocess_env,
    make_repository,
    probe_subprocess_runtime_roots,
)


class CountingGitClient:
    def __init__(self) -> None:
        self.calls = []
        self.mutate_before_call = None
        self.mutation_path = None

    def snapshot(self, repository_path: str, resources=()) -> dict:
        call_number = len(self.calls) + 1
        if (
            self.mutate_before_call == call_number
            and self.mutation_path is not None
        ):
            with self.mutation_path.open("a", encoding="utf-8") as stream:
                stream.write("changed between complete passes\n")
        self.calls.append(
            (
                repository_path,
                tuple(dict(resource) for resource in resources),
            )
        )
        return GitClient.snapshot(repository_path, resources=resources)


class MultiRepositoryControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.first = make_repository(self.root, "api")
        self.second = make_repository(self.root, "client")
        self.data_dir = str(self.root / "data")
        self.controller = Controller(self.data_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start_multi(self, controller=None):
        return (controller or self.controller).start(
            requirement="Deliver API and client together",
            workflow="lite",
            repositories=(str(self.second), str(self.first)),
        )

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        action = projection["action"]
        obligation = action.get("current_obligation")
        if isinstance(obligation, dict):
            result = {
                "obligation_id": obligation["obligation_id"],
                "passed": bool(payload.get("passed", True)),
                "evidence": [{
                    "kind": "command",
                    "reference": str(payload.get("command", "repository-set-check")),
                    "summary": str(payload.get("summary", "Assurance recorded")),
                }],
                "limitations": [],
            }
            if obligation["kind"] == "independent-review":
                review = action["review_contract"]
                result["review"] = {
                    "reviewer_available": True,
                    "independent": True,
                    "reviewer_digest": "a" * 64,
                    "review_scope_digest": review["review_scope_digest"],
                    "guidance_digest": review["guidance_digest"],
                    "workspace_digest": review["workspace_digest"],
                    "findings": [],
                    "claimed_outcome": "approved",
                }
                result["passed"] = True
            payload = {
                "summary": str(payload.get("summary", "Assurance recorded")),
                "assurance_result": result,
            }
        return self.controller.apply(
            task_id,
            action["action_id"],
            payload,
            binding=action["binding"],
        )

    @staticmethod
    def passing_verification(state, command: str) -> dict:
        repository_ids = [
            repository.repository_id for repository in state.repositories
        ]
        return {
            "passed": True,
            "command": command,
            "coverage": {
                "schema": VERIFICATION_COVERAGE_SCHEMA,
                "criteria": {"requirement": "proven"},
                "repositories": {
                    repository_id: {"command": command, "passed": True}
                    for repository_id in repository_ids
                },
                "integration": {"command": command, "passed": True},
            },
            "summary": "Repository-set verification passed",
        }

    def test_repeated_cli_repo_and_one_member_python_call_share_one_model(self) -> None:
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        probe_subprocess_runtime_roots(self.root, environment)
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "--data-dir",
                self.data_dir,
                "start",
                "--requirement",
                "CLI exact set",
                "--workflow",
                "lite",
                "--repo",
                str(self.second),
                "--repo",
                str(self.first),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        task = json.loads(completed.stdout)["task"]
        self.assertEqual(
            [item["path"] for item in task["repositories"]],
            sorted((str(self.first.resolve()), str(self.second.resolve()))),
        )

        one_member_controller = Controller(str(self.root / "one-member-data"))
        one_member = one_member_controller.start(
            requirement="One-member exact set",
            workflow="lite",
            repositories=(str(self.first),),
        )
        projection = one_member_controller.next(one_member.task_id)
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertNotIn("repository", projection)
        self.assertEqual(projection["repository_set"]["id"], one_member.repository_set_id)
        self.assertEqual(len(projection["repository_set"]["repositories"]), 1)
        self.assertEqual(
            projection["repository_set"]["repositories"][0]["path"],
            str(self.first.resolve()),
        )
        view = one_member_controller.show_view(one_member.task_id)
        self.assertEqual(
            view["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(len(view["current_snapshot"]["repositories"]), 1)

        with self.assertRaises(DevFlowError) as bare_string:
            Controller(str(self.root / "bare-string-data")).start(
                requirement="Reject an accidental character iterable",
                workflow="lite",
                repositories=str(self.first),
            )
        self.assertEqual(
            bare_string.exception.code,
            "REPOSITORY_COUNT_INVALID",
        )

    def test_admission_rejects_aliases_overlap_and_non_root(self) -> None:
        alias = self.root / "api-alias"
        alias.symlink_to(self.first, target_is_directory=True)
        with self.assertRaises(DevFlowError) as duplicate:
            self.controller.start(
                requirement="No aliases",
                workflow="lite",
                repositories=(str(self.first), str(alias)),
            )
        self.assertEqual(duplicate.exception.code, "REPOSITORY_DUPLICATE")

        nested = make_repository(self.first, "nested")
        with self.assertRaises(DevFlowError) as overlap:
            self.controller.start(
                requirement="No overlap",
                workflow="lite",
                repositories=(str(self.first), str(nested)),
            )
        self.assertEqual(overlap.exception.code, "REPOSITORY_OVERLAP")

        subdirectory = self.second / "not-the-root"
        subdirectory.mkdir()
        with self.assertRaises(DevFlowError) as non_root:
            self.controller.start(
                requirement="Exact roots only",
                workflow="lite",
                repositories=(str(subdirectory),),
            )
        self.assertEqual(non_root.exception.code, "REPOSITORY_ROOT_REQUIRED")
        self.assertFalse(
            (Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "tasks").exists()
        )

    def test_admission_rejects_shared_git_common_directory_and_count_bounds(self) -> None:
        linked = self.root / "api-linked-worktree"
        subprocess.run(
            [
                "git",
                "-C",
                str(self.first),
                "worktree",
                "add",
                "-q",
                "-b",
                "linked-test-branch",
                str(linked),
            ],
            env=hermetic_subprocess_env(self.root),
            check=True,
        )
        with self.assertRaises(DevFlowError) as shared:
            self.controller.start(
                requirement="Independent Git identities",
                workflow="lite",
                repositories=(str(self.first), str(linked)),
            )
        self.assertEqual(
            shared.exception.code,
            "REPOSITORY_GIT_IDENTITY_DUPLICATE",
        )
        self.assertEqual(len(shared.exception.details["repository_ids"]), 2)

        for repositories in ((), (str(self.first),) * 9):
            with self.subTest(repository_count=len(repositories)):
                with self.assertRaises(DevFlowError) as bounded:
                    self.controller.start(
                        requirement="Bounded set",
                        workflow="lite",
                        repositories=repositories,
                    )
                self.assertEqual(
                    bounded.exception.code,
                    "REPOSITORY_COUNT_INVALID",
                )

    def test_live_projection_and_mutation_fail_closed_for_conflicting_active_inventory(self) -> None:
        state = self.controller.start(
            requirement="Unique lease",
            workflow="lite",
            repositories=(str(self.first),),
            task_id="task-primary",
        )
        conflicting = replace(state, task_id="task-conflict")
        self.controller.store.create(conflicting)

        with self.assertRaises(DevFlowError) as projected:
            self.controller.next(state.task_id)
        self.assertEqual(projected.exception.code, "LEASE_INTEGRITY_CONFLICT")
        self.assertEqual(self.controller.show(state.task_id).revision, 0)

        with self.assertRaises(DevFlowError) as mutated:
            self.controller.cancel(state.task_id, reason="must not advance")
        self.assertEqual(mutated.exception.code, "LEASE_INTEGRITY_CONFLICT")
        self.assertEqual(self.controller.show(state.task_id).revision, 0)

    def test_capture_partitions_resources_and_discovers_from_secondary_member(self) -> None:
        (self.first / "plan.md").write_text("api plan\n", encoding="utf-8")
        (self.second / "plan.md").write_text("client plan\n", encoding="utf-8")
        state = self.start_multi()
        by_path = {repository.path: repository for repository in state.repositories}
        first_id = by_path[str(self.first.resolve())].repository_id
        second_id = by_path[str(self.second.resolve())].repository_id
        snapshot = self.controller._snapshot(
            state,
            additional_resources=(
                {
                    "repository_id": first_id,
                    "path": "plan.md",
                    "role": "governing",
                    "normalizer": "none",
                },
                {
                    "repository_id": second_id,
                    "path": "plan.md",
                    "role": "governing",
                    "normalizer": "none",
                },
            ),
        )
        self.assertEqual(snapshot["schema"], REPOSITORY_SET_SNAPSHOT_SCHEMA)
        for member in snapshot["repositories"]:
            self.assertEqual(
                member["snapshot"]["resources"],
                [
                    {
                        "path": "plan.md",
                        "role": "governing",
                        "normalizer": "none",
                        "kind": "regular",
                        "raw_sha256": member["snapshot"]["resources"][0][
                            "raw_sha256"
                        ],
                        "semantic_sha256": member["snapshot"]["resources"][0][
                            "semantic_sha256"
                        ],
                    }
                ],
            )

        with self.assertRaises(DevFlowError) as missing_scope:
            self.controller._snapshot(
                state,
                additional_resources=(
                    {
                        "path": "plan.md",
                        "role": "governing",
                        "normalizer": "none",
                    },
                ),
            )
        self.assertEqual(missing_scope.exception.code, "NODE_OUTPUT_INVALID")

        nested = self.second / "src"
        nested.mkdir()
        matches = self.controller.tasks_for_path(str(nested))
        self.assertEqual([item.task_id for item in matches], [state.task_id])

    def test_reads_use_two_passes_and_mutations_use_three_complete_captures(self) -> None:
        one_member_git = CountingGitClient()
        one_member_controller = Controller(
            str(self.root / "single-data"),
            git_client=one_member_git,
        )
        one_member_state = one_member_controller.start(
            requirement="One member",
            workflow="lite",
            repositories=(str(self.first),),
        )
        one_member_git.calls.clear()
        one_member_projection = one_member_controller.next(one_member_state.task_id)
        self.assertEqual(one_member_projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            len(one_member_projection["repository_set"]["repositories"]),
            1,
        )
        self.assertEqual(
            [path for path, _ in one_member_git.calls],
            [str(self.first.resolve()), str(self.first.resolve())],
        )

        multi_git = CountingGitClient()
        multi = Controller(
            str(self.root / "multi-data"),
            git_client=multi_git,
        )
        state = self.start_multi(multi)
        expected_order = [repository.path for repository in state.repositories]
        multi_git.calls.clear()
        projection = multi.next(state.task_id)
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            [path for path, _ in multi_git.calls],
            expected_order * 2,
        )

        binding = projection["action"]["binding"]
        multi_git.calls.clear()
        applied = multi.apply(
            state.task_id,
            projection["action"]["action_id"],
            {},
            binding=binding,
        )
        self.assertEqual(applied["receipt"]["committed_revision"], 1)
        self.assertEqual(
            [path for path, _ in multi_git.calls],
            expected_order * 6,
        )

        current = multi.show(state.task_id)
        revised_contract = json_value(current.original_contract)
        revised_contract["revision"] = 2
        revised_contract["summary"] = "Revised repository-set delivery"
        multi_git.calls.clear()
        revised = multi.revise_contract(
            state.task_id,
            contract=revised_contract,
            reason="Clarify the exact-set scope",
            actor_label="maintainer",
        )
        self.assertEqual(revised["receipt"]["committed_revision"], 2)
        self.assertEqual(
            [path for path, _ in multi_git.calls],
            expected_order * 6,
        )

        cancel_git = CountingGitClient()
        cancel_controller = Controller(
            str(self.root / "cancel-data"),
            git_client=cancel_git,
        )
        cancel_state = self.start_multi(cancel_controller)
        cancel_order = [
            repository.path for repository in cancel_state.repositories
        ]
        cancel_git.calls.clear()
        cancelled = cancel_controller.cancel(
            cancel_state.task_id,
            reason="Stop before preflight",
        )
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")
        self.assertEqual(
            [path for path, _ in cancel_git.calls],
            cancel_order * 6,
        )

    def test_multi_repository_verification_and_dossier_remain_aggregate(self) -> None:
        state = self.start_multi()
        self.apply_current(state.task_id, {})
        self.apply_current(
            state.task_id,
            {
                "summary": "Repository-set impact recorded",
                "driver_result": {
                    "schema": DRIVER_RESULT_SCHEMA,
                    "status": "degraded",
                },
                "impact_manifest": {
                    "confidence": "unknown",
                    "entries": [],
                    "edges": [],
                    "risk_triggers": [],
                    "public_behavior": False,
                    "documentation_required": False,
                    "manual_evidence_required": False,
                    "executable_reproduction_required": False,
                    "overflow": False,
                    "limitations": ["Explicit aggregate uncertainty"],
                },
            },
        )
        self.apply_current(
            state.task_id,
            {
                "summary": "Implemented the repository set",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [],
                },
            },
        )

        verification = self.controller.next(state.task_id)
        self.assertEqual(verification["schema"], AGENT_PROTOCOL_SCHEMA)
        repository_ids = [
            repository.repository_id for repository in state.repositories
        ]
        command = "python3 -m unittest repository-set"
        targeted = set()
        while self.controller.next(state.task_id)["action"]["action_id"] == "assurance.execute":
            obligation = self.controller.next(state.task_id)["action"]["current_obligation"]
            targeted.update(obligation["repository_ids"])
            self.apply_current(
                state.task_id,
                self.passing_verification(state, command),
            )
        self.assertEqual(targeted, set(repository_ids))
        completed = self.apply_current(
            state.task_id,
            {
                "summary": "Delivered the repository set",
                "remaining_risks": {},
                "handoff": "Ready for operator publication",
            },
        )

        summary = completed["projection"]["dossier"]
        self.assertEqual(summary["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(summary["repository_set_id"], state.repository_set_id)
        self.assertTrue(summary["current"])
        self.assertEqual(
            summary["coverage"],
            {"proven": 1, "waived": 0, "unverified": 0},
        )

        view = self.controller.show_view(state.task_id)
        self.assertEqual(
            view["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        dossier = view["records"][-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(dossier["repository_set"]["id"], state.repository_set_id)
        self.assertEqual(
            [
                member["repository_id"]
                for member in dossier["repository_set"]["members"]
            ],
            repository_ids,
        )
        criterion = dossier["coverage"]["requirement"]
        self.assertEqual(criterion["status"], "proven")
        self.assertEqual(
            {
                repository_id
                for proof in criterion["proofs"]
                for repository_id in proof["repository_ids"]
            },
            set(repository_ids),
        )
        self.assertTrue(dossier["aggregate_freshness"]["current"])

    def test_unstable_capture_and_unavailable_member_leave_state_unchanged(self) -> None:
        git = CountingGitClient()
        controller = Controller(
            str(self.root / "unstable-data"),
            git_client=git,
        )
        state = self.start_multi(controller)
        git.calls.clear()
        git.mutate_before_call = 3
        git.mutation_path = self.first / "a.txt"
        with self.assertRaises(DevFlowError) as unstable:
            controller.next(state.task_id)
        self.assertEqual(unstable.exception.code, "SNAPSHOT_UNSTABLE")
        self.assertEqual(controller.show(state.task_id).revision, 0)

        state = self.start_multi()
        self.apply_current(state.task_id, {})
        before = self.controller.show(state.task_id)
        unavailable = self.root / "client-unavailable"
        self.second.rename(unavailable)
        with self.assertRaises(DevFlowError) as missing:
            self.controller.cancel(state.task_id, reason="Stop atomically")
        self.assertEqual(missing.exception.details["repository_id"], next(
            repository.repository_id
            for repository in state.repositories
            if repository.path == str(self.second.resolve())
        ))
        self.assertEqual(self.controller.show(state.task_id), before)
        unavailable_view = self.controller.show_view(state.task_id)
        self.assertEqual(unavailable_view["revision"], before.revision)
        self.assertEqual(unavailable_view["records"], json_value(before.records))
        self.assertIsNone(unavailable_view["current_snapshot"])
        self.assertIsNone(unavailable_view["artifact_freshness"])
        self.assertEqual(
            unavailable_view["snapshot_error"]["code"],
            "REPOSITORY_INVALID",
        )
        self.assertIn(
            "repository_id",
            unavailable_view["snapshot_error"]["details"],
        )

        environment = hermetic_subprocess_env(self.root)
        probe_subprocess_runtime_roots(self.root, environment)
        shown = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts" / "dev_flow.py"),
                "--data-dir",
                self.data_dir,
                "show",
                state.task_id,
            ],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_task = json.loads(shown.stdout)["task"]
        self.assertEqual(shown_task["revision"], before.revision)
        self.assertIsNone(shown_task["current_snapshot"])
        self.assertEqual(
            shown_task["snapshot_error"]["details"]["repository_id"],
            unavailable_view["snapshot_error"]["details"]["repository_id"],
        )
        unavailable.rename(self.second)
        cancelled = self.controller.cancel(state.task_id, reason="Stop atomically")
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
