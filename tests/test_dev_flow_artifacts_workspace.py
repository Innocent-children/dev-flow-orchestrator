from __future__ import annotations

import argparse
import contextlib
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


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case

SCRIPT = test_case.SCRIPT
SUPPORT = test_case.SUPPORT
dev_flow = test_case.dev_flow
git = test_case.git


class DevFlowArtifactsWorkspaceTest(test_case.DevFlowTestCase):
    def test_directory_artifact_hash_changes_with_content(self) -> None:
        repo, _ = self.make_repo("artifact")
        task = self.start(repo)["task"]
        directory = self.root / "openspec-plan"
        (directory / "specs").mkdir(parents=True)
        (directory / "proposal.md").write_text("proposal one\n", encoding="utf-8")
        (directory / "specs" / "requirements.md").write_text("requirement\n", encoding="utf-8")
        first = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "directory-evidence",
            "--path",
            str(directory),
        )
        self.assertEqual(first["artifact"]["artifact_type"], "directory")
        self.assertEqual(first["artifact"]["file_count"], 2)
        task = dev_flow.load_state(task["task_id"], self.data)
        (directory / "proposal.md").write_text("proposal two\n", encoding="utf-8")
        drift_state = {
            "artifacts": [first["artifact"]],
            "approvals": {
                "evidence": {"artifact_sha256": first["artifact"]["sha256"]}
            },
        }
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._require_gate_for_latest_artifact(
                drift_state, "evidence", "directory-evidence"
            )
        self.assertEqual(captured.exception.code, "ARTIFACT_CHANGED")
        second = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "directory-evidence",
            "--path",
            str(directory),
        )
        self.assertNotEqual(first["artifact"]["sha256"], second["artifact"]["sha256"])

    def test_latest_passing_tests_are_aggregated_per_repository(self) -> None:
        first, _ = self.make_repo("test-first")
        second, _ = self.make_repo("test-second")
        first_repo = {"id": "first", "path": str(first), "workspace": None}
        second_repo = {"id": "second", "path": str(second), "workspace": None}
        first_fingerprint = dev_flow._fingerprint_repo(first)
        second_fingerprint = dev_flow._fingerprint_repo(second)
        plan_path = self.root / "aggregate-contract.md"
        plan_path.write_text("approved plan\n", encoding="utf-8")
        plan_sha = dev_flow._sha256_file(plan_path)
        approved_at = "2026-07-21T00:00:00.000Z"
        state = {
            "repositories": [first_repo, second_repo],
            "route": {"value": "direct"},
            "artifacts": [
                {
                    "evidence_contract_version": (
                        dev_flow.EVIDENCE_CONTRACT_VERSION
                    ),
                    "artifact_id": "plan-1",
                    "kind": "direct-contract",
                    "path": str(plan_path),
                    "path_identity": dev_flow._serializable_path_identity(
                        plan_path
                    ),
                    "sha256": plan_sha,
                }
            ],
            "approvals": {
                "plan": {
                    "approval_id": "plan-approval-1",
                    "artifact_sha256": plan_sha,
                    "approved_at": approved_at,
                }
            },
            "tests": [
                {
                    "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": ["first"],
                    "fingerprints": {"first": first_fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-1",
                    "recorded_at": "2026-07-21T00:00:01.000Z",
                },
                {
                    "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": ["second"],
                    "fingerprints": {"second": second_fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-1",
                    "recorded_at": "2026-07-21T00:00:02.000Z",
                },
            ],
        }
        plan_gate = mock.patch.object(
            dev_flow,
            "_require_current_plan_gate",
            side_effect=lambda value, _kind: (
                value["approvals"]["plan"],
                value["artifacts"][0],
            ),
        )
        plan_gate.start()
        self.addCleanup(plan_gate.stop)

        def latest_test_status() -> tuple[bool, str | None]:
            for record in state["tests"]:
                record["capability_profile_sha256"] = {
                    repository_id: record["fingerprints"][
                        repository_id
                    ]["capability_profile_sha256"]
                    for repository_id in record["repository_ids"]
                }
            return dev_flow._latest_passing_test_is_current(state)

        self.assertEqual(latest_test_status(), (True, None))
        state["approvals"]["plan"]["approval_id"] = "plan-approval-2"
        current, reason = latest_test_status()
        self.assertFalse(current)
        self.assertIn("current plan approval", reason)
        for repository_id, fingerprint, timestamp in (
            ("first", first_fingerprint, "2026-07-21T00:00:03.000Z"),
            ("second", second_fingerprint, "2026-07-21T00:00:04.000Z"),
        ):
            state["tests"].append(
                {
                    "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                    "name": "integration",
                    "command": "run integration",
                    "passed": True,
                    "repository_ids": [repository_id],
                    "fingerprints": {repository_id: fingerprint},
                    "plan_artifact_sha256": plan_sha,
                    "plan_approval_id": "plan-approval-2",
                    "recorded_at": timestamp,
                }
            )
        self.assertEqual(latest_test_status(), (True, None))
        state["tests"].append(
            {
                "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                "name": "integration",
                "command": "run integration",
                "passed": False,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:05.000Z",
            }
        )
        current, reason = latest_test_status()
        self.assertFalse(current)
        self.assertIn("integration", reason)
        state["tests"].append(
            {
                "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                "name": "lint",
                "command": "run lint",
                "passed": True,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:06.000Z",
            }
        )
        current, reason = latest_test_status()
        self.assertFalse(current)
        self.assertIn("integration", reason)
        state["tests"].append(
            {
                "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                "name": "integration",
                "command": "run integration",
                "passed": True,
                "repository_ids": ["first"],
                "fingerprints": {"first": first_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:07.000Z",
            }
        )
        self.assertEqual(latest_test_status(), (True, None))
        state["tests"].append(
            {
                "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                "name": "e2e",
                "command": "run e2e",
                "passed": False,
                "repository_ids": ["second"],
                "fingerprints": {"second": second_fingerprint},
                "plan_artifact_sha256": plan_sha,
                "plan_approval_id": "plan-approval-2",
                "recorded_at": "2026-07-21T00:00:08.000Z",
            }
        )
        current, reason = latest_test_status()
        self.assertFalse(current)
        self.assertIn("second", reason)

    def test_unrecorded_workspace_rejects_wrong_base_and_foreign_repo(self) -> None:
        repo, _ = self.make_repo("workspace-source")
        repo = repo.resolve()
        (repo / ".gitignore").write_text("*.ignored\n", encoding="utf-8")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-q", "-m", "add ignore rule")
        base = git(repo, "rev-parse", "HEAD")
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        ahead = git(repo, "commit-tree", tree, "-p", base, "-m", "unrelated old work")
        branch = "codex/collision"
        git(repo, "update-ref", f"refs/heads/{branch}", ahead)
        wrong_base_plan = self.current_workspace_plan(
            "source",
            repo,
            self.root / "wrong-base-workspace",
            branch,
            base,
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(wrong_base_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_BASE_MISMATCH")
        self.assertFalse(Path(wrong_base_plan["path"]).exists())

        source_checkout_plan = self.current_workspace_plan(
            "source", repo, repo, "main", base
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(source_checkout_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
        self.assertFalse(captured.exception.details["linked_worktree"])

        foreign, _ = self.make_repo("workspace-foreign")
        foreign_plan = self.current_workspace_plan(
            "source", repo, foreign, "main", base
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._execute_worktree(foreign_plan)
        self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
        self.assertFalse(captured.exception.details["same_common_dir"])

        unowned_branch = "codex/recover-clean"
        unowned_path = (self.root / "unowned-linked-worktree").resolve()
        git(
            repo,
            "worktree",
            "add",
            "-b",
            unowned_branch,
            str(unowned_path),
            base,
        )
        unowned_plan = self.current_workspace_plan(
            "source",
            repo,
            unowned_path,
            unowned_branch,
            base,
        )
        recovered = dev_flow._execute_worktree(unowned_plan)
        self.assertFalse(recovered["created"])
        self.assertTrue(recovered["recovered_unrecorded"])
        self.assertEqual(
            Path(git(unowned_path, "rev-parse", "--show-toplevel")).resolve(),
            unowned_path,
        )

        for dirty_kind in ("cached", "unstaged", "untracked", "ignored"):
            with self.subTest(dirty_kind=dirty_kind):
                dirty_branch = f"codex/unowned-{dirty_kind}"
                dirty_path = (
                    self.root / f"unowned-linked-worktree-{dirty_kind}"
                ).resolve()
                git(
                    repo,
                    "worktree",
                    "add",
                    "-b",
                    dirty_branch,
                    str(dirty_path),
                    base,
                )
                if dirty_kind == "cached":
                    (dirty_path / "cached.txt").write_text("cached\n", encoding="utf-8")
                    git(dirty_path, "add", "cached.txt")
                elif dirty_kind == "unstaged":
                    (dirty_path / "tracked.txt").write_text(
                        "unstaged\n", encoding="utf-8"
                    )
                elif dirty_kind == "untracked":
                    (dirty_path / "untracked.txt").write_text(
                        "untracked\n", encoding="utf-8"
                    )
                else:
                    (dirty_path / "residual.ignored").write_text(
                        "ignored\n", encoding="utf-8"
                    )
                dirty_plan = self.current_workspace_plan(
                    "source",
                    repo,
                    dirty_path,
                    dirty_branch,
                    base,
                )
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._execute_worktree(dirty_plan)
                self.assertEqual(captured.exception.code, "WORKSPACE_COLLISION")
                details = captured.exception.details
                self.assertEqual(details["reason"], "unrecorded_worktree_not_clean")
                self.assertTrue(details["dirty"])
                self.assertTrue(details["linked_worktree"])
                self.assertTrue(details["same_common_dir"])
                self.assertEqual(Path(details["actual_root"]).resolve(), dirty_path)
                self.assertTrue(details["status_porcelain"])

    def test_workspace_plan_rejects_source_and_analysis_overlap(self) -> None:
        repo, _ = self.make_repo("workspace-overlap")
        analysis_path = self.root / "analysis-owned"
        capability_profile = dev_flow._git_capability_profile(repo)
        record = {
            "id": "workspace-overlap",
            "path": str(repo),
            "protected_branches": ["main", "master", "trunk"],
            "baseline": {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "base_branch": "main",
                "base_sha": git(repo, "rev-parse", "HEAD"),
                "capability_profile": capability_profile,
                "capability_profile_sha256": capability_profile["sha256"],
            },
            "analysis_workspace": {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "path": str(analysis_path),
                "path_identity": dev_flow._serializable_path_identity(
                    analysis_path
                ),
                "ready": True,
            },
            "workspace": None,
        }
        state = {
            "task_id": "overlap-task",
            "workspace": {"generation": 0},
            "repositories": [record],
        }
        for invalid_path in (
            repo,
            analysis_path,
            analysis_path / "nested",
            self.data,
            self.data / "tasks" / "another-task",
            self.data / "analysis" / "another-task",
            self.data / "workspace-registry.json",
            self.data / "workspace-registry.lock",
            self.data / "workspaces" / "another-task" / record["id"],
            self.data / "workspaces" / state["task_id"] / "r1" / record["id"],
        ):
            with self.subTest(path=invalid_path):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._workspace_plan(
                        state,
                        [record],
                        self.data,
                        None,
                        str(invalid_path),
                    )
                self.assertEqual(captured.exception.code, "WORKSPACE_NOT_ISOLATED")
        self.assertFalse((self.data / "workspace-registry.json").exists())

        worktree_container = self.root / "user-worktree-container"
        worktree_container.mkdir()
        user_worktree = worktree_container / "registered"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "user-owned-worktree",
            str(user_worktree),
            "HEAD",
        )
        for invalid_path in (
            user_worktree,
            user_worktree / "nested",
            worktree_container,
        ):
            with self.subTest(registered_worktree_overlap=invalid_path):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._workspace_plan(
                        state,
                        [record],
                        self.data,
                        "codex/isolated-candidate",
                        str(invalid_path),
                    )
                self.assertEqual(captured.exception.code, "WORKSPACE_NOT_ISOLATED")
        self.assertFalse((user_worktree / "nested").exists())

        symbolic_branch = "codex/symbolic-workspace"
        git(
            repo,
            "symbolic-ref",
            f"refs/heads/{symbolic_branch}",
            "refs/heads/main",
        )
        symbolic_path = self.root / "symbolic-workspace"
        with self.assertRaises(dev_flow.FlowError) as symbolic_error:
            dev_flow._workspace_plan(
                state,
                [record],
                self.data,
                symbolic_branch,
                str(symbolic_path),
            )
        self.assertEqual(
            symbolic_error.exception.code, "SYMBOLIC_WORKSPACE_BRANCH"
        )
        self.assertFalse(symbolic_path.exists())

    def test_controller_worktree_creation_disables_checkout_hooks(self) -> None:
        repo, _ = self.make_repo("workspace-hook-dirty")
        repo = repo.resolve()
        (repo / ".gitignore").write_text("generated.ignored\n", encoding="utf-8")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-q", "-m", "ignore generated hook output")
        hook = repo / ".git" / "hooks" / "post-checkout"
        external_marker = self.root / "post-checkout-hook-ran"
        hook.write_bytes(
            b"this hook is deliberately invalid and must never execute\n"
        )
        hook.chmod(0o755)
        plan = self.current_workspace_plan(
            "workspace-hook-dirty",
            repo,
            self.root / "hook-dirty-workspace",
            "codex/hook-dirty",
            git(repo, "rev-parse", "HEAD"),
        )
        task_dir = self.root / "hook-worktree-task"
        dev_flow._ensure_private_dir(task_dir)
        current = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "task_id": "hook-worktree-task",
            "status": "IMPLEMENTING",
            "revision": 0,
        }
        dev_flow._atomic_write_json(task_dir / "state.json", current)
        with dev_flow._task_lock(task_dir):
            outcome = dev_flow._execute_worktree(plan)
            committed = dict(current)
            committed["workspace_created"] = True
            dev_flow._commit_state(
                current,
                committed,
                task_dir,
                "fixture_workspace_created",
            )
        self.assertTrue(outcome["ready"])
        self.assertTrue(outcome["created"])
        self.assertFalse(Path(plan["path"], "generated.ignored").exists())
        self.assertFalse(external_marker.exists())

    def test_workspace_plan_must_cover_every_repository(self) -> None:
        first, _ = self.make_repo("plan-first")
        second, _ = self.make_repo("plan-second")
        impact = self.root / "multi-impact.md"
        impact.write_text("impact\n", encoding="utf-8")
        impact_sha = dev_flow._sha256_file(impact)
        repositories = []
        for repo_id, path in (("first", first), ("second", second)):
            capability_profile = dev_flow._git_capability_profile(path)
            repositories.append(
                {
                    "id": repo_id,
                    "path": str(path),
                    "canonical_path": str(path),
                    "protected_branches": ["main", "master", "trunk"],
                    "baseline": {
                        "evidence_contract_version": (
                            dev_flow.EVIDENCE_CONTRACT_VERSION
                        ),
                        "base_branch": "main",
                        "base_sha": git(path, "rev-parse", "HEAD"),
                        "capability_profile": capability_profile,
                        "capability_profile_sha256": (
                            capability_profile["sha256"]
                        ),
                    },
                    "workspace": None,
                    "workspace_history": [],
                }
            )
        task_id = "all-repo-plan"
        state = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "task_id": task_id,
            "requirement": "multi repository plan",
            "status": "ROUTE_APPROVED",
            "revision": 1,
            "created_at": "2026-07-21T00:00:00.000Z",
            "updated_at": "2026-07-21T00:00:00.000Z",
            "route": {"value": "direct"},
            "repositories": repositories,
            "artifacts": [
                {
                    "evidence_contract_version": (
                        dev_flow.EVIDENCE_CONTRACT_VERSION
                    ),
                    "artifact_id": "impact-1",
                    "kind": "impact",
                    "path": str(impact),
                    "path_identity": dev_flow._serializable_path_identity(
                        impact
                    ),
                    "sha256": impact_sha,
                }
            ],
            "approvals": {
                "route": {
                    "approval_id": "route-1",
                    "artifact_sha256": impact_sha,
                }
            },
            "tests": [],
            "review_snapshots": [],
            "workspace": {"strategy": "worktree", "ready": False, "generation": 0},
            "blocked": None,
            "cancelled": None,
        }
        state_path = self.data / "tasks" / task_id / "state.json"
        dev_flow._atomic_write_json(state_path, state)
        response = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            "1",
            "--repo",
            "first",
            expected_code=2,
        )
        self.assertEqual(response["error"]["code"], "INCOMPLETE_WORKSPACE_PLAN")

    def test_workspace_claims_block_cross_task_path_and_branch_reuse(self) -> None:
        repo, _ = self.make_repo("shared-claim-source")
        repo = repo.resolve()

        def write_route_approved_state(task_id: str) -> dict:
            return self.route_approved_task(
                repo,
                task_id=task_id,
            )

        first = write_route_approved_state("claim-owner")
        second = write_route_approved_state("claim-contender")
        second_revision = second["revision"]
        claimed_path = (self.root / "claimed-workspace").resolve()
        claimed_branch = "codex/shared-claim"
        first_plan = self.cli(
            "prepare-workspace",
            first["task_id"],
            "--expected-revision",
            str(first["revision"]),
            "--path",
            str(claimed_path),
            "--branch",
            claimed_branch,
        )
        registry_path = self.data / "workspace-registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        owner_claims = [
            claim
            for claim in registry["claims"]
            if claim["task_id"] == first["task_id"]
        ]
        self.assertEqual(len(owner_claims), 1)
        self.assertFalse(claimed_path.exists())

        same_path = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(claimed_path),
            "--branch",
            "codex/different-branch",
            expected_code=2,
        )
        self.assertEqual(
            same_path["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(same_path["error"]["details"]["conflict"], "path")
        self.assertFalse(claimed_path.exists())

        same_branch_path = (self.root / "different-claim-path").resolve()
        same_branch = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(same_branch_path),
            "--branch",
            claimed_branch,
            expected_code=2,
        )
        self.assertEqual(
            same_branch["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(same_branch["error"]["details"]["conflict"], "branch")
        self.assertFalse(same_branch_path.exists())
        prefixed_branch_path = (self.root / "prefixed-claim-path").resolve()
        prefixed_branch = self.cli(
            "prepare-workspace",
            second["task_id"],
            "--expected-revision",
            str(second["revision"]),
            "--path",
            str(prefixed_branch_path),
            "--branch",
            f"{claimed_branch}/nested",
            expected_code=2,
        )
        self.assertEqual(
            prefixed_branch["error"]["code"], "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(
            prefixed_branch["error"]["details"]["conflict"], "branch"
        )
        self.assertFalse(prefixed_branch_path.exists())
        self.assertEqual(
            dev_flow.load_state(
                second["task_id"], self.data
            )["revision"],
            second_revision,
        )

        first = dev_flow.load_state(first["task_id"], self.data)
        self.mutate(
            "approve",
            first,
            "--gate",
            "workspace",
            "--note",
            "the durable claim and exact plan are approved",
            "--artifact-sha256",
            first_plan["plan_artifact"]["sha256"],
        )
        first = dev_flow.load_state(first["task_id"], self.data)
        executed = self.mutate(
            "prepare-workspace",
            first,
            "--execute",
            "--path",
            str(claimed_path),
            "--branch",
            claimed_branch,
        )
        self.assertTrue(executed["complete"])
        ready = dev_flow.load_state(first["task_id"], self.data)
        ready = self.record_workspace_indexes(ready)
        receipt = ready["repositories"][0]["workspace"]["workspace_claim"]
        self.assertEqual(receipt["plan_sha256"], first_plan["plan_artifact"]["sha256"])

        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        claimed = next(
            claim
            for claim in registry["claims"]
            if claim["claim_id"] == receipt["claim_id"]
        )
        claimed["branch"] = "codex/tampered-claim"
        dev_flow._atomic_write_json(registry_path, registry)
        stale_receipt = self.cli(
            "transition",
            ready["task_id"],
            "--expected-revision",
            str(ready["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(
            stale_receipt["error"]["code"], "STALE_WORKSPACE_INDEX"
        )

    def test_workspace_claim_rejects_sibling_plans_for_the_same_branch_store(self) -> None:
        repo, _ = self.make_repo("sibling-claim-source")
        linked_source = self.root / "sibling-linked-source"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "sibling-source",
            str(linked_source),
            "HEAD",
        )
        state = {
            "task_id": "sibling-claims",
            "workspace": {"generation": 0},
        }
        branch = "codex/sibling-claims"
        plans = [
            {
                "repository_id": "first",
                "source_path": str(repo),
                "path": str(self.root / "sibling-workspace-first"),
                "branch": branch,
            },
            {
                "repository_id": "second",
                "source_path": str(linked_source),
                "path": str(self.root / "sibling-workspace-second"),
                "branch": branch,
            },
        ]
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._claim_workspace_plan(self.data, state, "a" * 64, plans)
        self.assertEqual(
            captured.exception.code, "WORKSPACE_OWNERSHIP_CONFLICT"
        )
        self.assertEqual(captured.exception.details["conflict"], "branch")
        self.assertFalse((self.data / "workspace-registry.json").exists())
        self.assertFalse(Path(plans[0]["path"]).exists())
        self.assertFalse(Path(plans[1]["path"]).exists())

    def test_multi_repo_workspace_overrides_are_exact_and_executable(self) -> None:
        first, _ = self.make_repo("first")
        second, _ = self.make_repo("second")
        first = first.resolve()
        second = second.resolve()
        task_id = "all-repo-overrides"
        state = self.route_approved_task(
            first,
            second,
            task_id=task_id,
        )
        revision = str(state["revision"])
        custom_path = (self.root / "custom-first-workspace").resolve()
        other_path = (self.root / "different-first-workspace").resolve()

        unknown = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"missing={custom_path}",
            expected_code=2,
        )
        self.assertEqual(unknown["error"]["code"], "REPOSITORY_NOT_FOUND")
        duplicate = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-path",
            f"first={other_path}",
            expected_code=2,
        )
        self.assertEqual(
            duplicate["error"]["code"], "DUPLICATE_WORKSPACE_OVERRIDE"
        )
        relative = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            "first=relative/path",
            expected_code=2,
        )
        self.assertEqual(relative["error"]["code"], "INVALID_ARGUMENT")
        shared_path = (self.root / "shared-workspace").resolve()
        collision = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={shared_path}",
            "--workspace-path",
            f"second={shared_path}",
            expected_code=2,
        )
        self.assertEqual(collision["error"]["code"], "WORKSPACE_PLAN_COLLISION")

        planned = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            revision,
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-branch",
            "first=codex/custom-first",
        )
        by_id = {plan["repository_id"]: plan for plan in planned["plans"]}
        self.assertEqual(by_id["first"]["path"], str(custom_path))
        self.assertEqual(by_id["first"]["branch"], "codex/custom-first")
        task = dev_flow.load_state(task_id, self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "exact multi-repository workspace plan approved",
            "--artifact-sha256",
            planned["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task_id, self.data)
        mismatch = self.cli(
            "prepare-workspace",
            task_id,
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            "--workspace-path",
            f"first={other_path}",
            "--workspace-branch",
            "first=codex/custom-first",
            expected_code=2,
        )
        self.assertEqual(mismatch["error"]["code"], "WORKSPACE_PLAN_MISMATCH")
        executed = self.mutate(
            "prepare-workspace",
            task,
            "--execute",
            "--workspace-path",
            f"first={custom_path}",
            "--workspace-branch",
            "first=codex/custom-first",
        )
        self.assertTrue(executed["complete"])
        self.assertTrue(custom_path.is_dir())
        self.assertEqual(git(custom_path, "branch", "--show-current"), "codex/custom-first")



if __name__ == "__main__":
    unittest.main()
