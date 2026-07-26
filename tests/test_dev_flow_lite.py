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


class DevFlowLiteTest(test_case.DevFlowTestCase):
    def start_lite(self, *repos: Path, task_id: str = "lite-1") -> dict:
        arguments = [
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "in-place",
            "--requirement",
            "Fix a bounded bug in place",
            "--change-category",
            "internal",
            "--target-path",
            "tracked.txt",
        ]
        for repo in repos:
            arguments.extend(["--repo", str(repo)])
        return self.cli(*arguments)

    def approved_lite_task(
        self, repo: Path, *, task_id: str = "lite-1", allow_dirty: bool = False
    ) -> dict:
        self.start_lite(repo, task_id=task_id)
        task = dev_flow.load_state(task_id, self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state(task_id, self.data)
        arguments = ["--gate", "lite", "--note", "in-place fix approved"]
        if allow_dirty:
            arguments.append("--allow-dirty")
        self.mutate("approve", task, *arguments)
        return dev_flow.load_state(task_id, self.data)

    def test_lite_flow_runs_in_place_to_done(self) -> None:
        repo, _ = self.make_repo("lite-repo")
        response = self.start_lite(repo)
        self.assertEqual(response["flow"], "lite")
        self.assertEqual(response["flow_name"], "精简流程")
        self.assertEqual(response["status_name"], "需求接收")
        self.assertEqual(response["workspace_strategy_name"], "使用当前分支")
        self.assertEqual(
            [item["id"] for item in response["workflow"]["remaining"]],
            ["PREFLIGHTED", "IMPLEMENTING", "VERIFYING", "DONE"],
        )
        task = response["task"]
        self.assertEqual(task["flow"], "lite")
        self.assertEqual(task["workspace"]["strategy"], "in-place")
        self.assertIsNone(response["index_selection"]["selected_role"])

        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-1", self.data)
        self.assertEqual(task["status"], "PREFLIGHTED")

        approved = self.mutate(
            "approve", task, "--gate", "lite", "--note", "fix in place"
        )
        self.assertTrue(approved["approval"]["preflight_evidence_sha256"])
        self.assertEqual(
            approved["approval"]["preflight_evidence_sha256"],
            dev_flow._lite_preflight_evidence_sha256(
                dev_flow.load_state("lite-1", self.data)
            ),
        )

        task = dev_flow.load_state("lite-1", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-1", self.data)
        self.assertEqual(task["status"], "IMPLEMENTING")
        self.assertIsNone(
            dev_flow._index_selection(task)["selected_role"]
        )

        (repo / "tracked.txt").write_text("fixed in place\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-1", self.data)

        recorded = self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        self.assertIn("lite_approval_id", recorded["test"])
        self.assertNotIn("plan_artifact_sha256", recorded["test"])
        self.assertNotIn("fingerprints", recorded["test"])
        self.assertTrue(recorded["test"]["fingerprint_sha256"])
        recorded_state = dev_flow.load_state("lite-1", self.data)
        fingerprint_reference = next(
            iter(recorded_state["tests"][-1]["fingerprints"].values())
        )
        self.assertEqual(
            fingerprint_reference["storage"],
            dev_flow._FINGERPRINT_STORAGE_KIND,
        )
        self.assertTrue(Path(fingerprint_reference["path"]).is_file())
        task = dev_flow.load_state("lite-1", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(dev_flow.load_state("lite-1", self.data)["status"], "DONE")

    def test_record_test_reuses_task_local_fingerprint_blob_and_fails_closed(self) -> None:
        repo, _ = self.make_repo("lite-fingerprint-cas")
        task = self.approved_lite_task(
            repo,
            task_id="lite-fingerprint-cas",
        )
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-fingerprint-cas", self.data)
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-fingerprint-cas", self.data)

        first = self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "python -m unittest",
            "--exit-code",
            "0",
        )
        self.assertNotIn("fingerprints", first["test"])
        task = dev_flow.load_state("lite-fingerprint-cas", self.data)
        first_reference = next(
            iter(task["tests"][-1]["fingerprints"].values())
        )
        first_path = Path(first_reference["path"])
        self.assertEqual(
            first_reference["sha256"],
            next(iter(first["test"]["fingerprint_sha256"].values())),
        )
        self.assertNotIn(
            "evidence_contract_version",
            first_reference,
        )
        with self.assertRaises(dev_flow.FlowError) as legacy_gate:
            dev_flow._require_current_evidence(
                first_reference,
                "legacy-controller-fingerprint",
            )
        self.assertEqual(
            legacy_gate.exception.code,
            "EVIDENCE_REGENERATION_REQUIRED",
        )

        second = self.mutate(
            "record-test",
            task,
            "--name",
            "integration",
            "--command",
            "python -m unittest discover",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-fingerprint-cas", self.data)
        second_reference = next(
            iter(task["tests"][-1]["fingerprints"].values())
        )
        self.assertEqual(second_reference["path"], str(first_path))
        self.assertEqual(
            len(list(first_path.parent.glob("*.json"))),
            1,
        )
        self.assertNotIn("fingerprints", second["test"])
        state_text = (
            self.data
            / "tasks"
            / "lite-fingerprint-cas"
            / "state.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"tracked_worktree":', state_text)
        self.assertLess(len(json.dumps(second).encode("utf-8")), 5000)

        with self.assertRaises(dev_flow.FlowError) as unsupported:
            dev_flow._load_recorded_fingerprint(
                {**first_reference, "storage": "future-format"},
                "test:future-format",
            )
        self.assertEqual(
            unsupported.exception.code,
            "FINGERPRINT_STORAGE_UNSUPPORTED",
        )

        rollback = first_path.parent / (
            f".{first_path.name}"
            f"{dev_flow._ROLLBACK_MARKER}test"
        )
        rollback.write_bytes(b"")
        with self.assertRaises(dev_flow.FlowError) as unresolved:
            dev_flow._load_recorded_fingerprint(
                first_reference,
                "test:rollback",
            )
        self.assertEqual(
            unresolved.exception.code,
            "ATOMIC_RECOVERY_REQUIRED",
        )
        rollback.unlink()

        first_path.write_text("{}\n", encoding="utf-8")
        rejected = self.mutate(
            "transition",
            task,
            "--to",
            "DONE",
            expected_code=2,
        )
        self.assertEqual(
            rejected["error"]["code"],
            "CURRENT_TEST_REQUIRED",
        )

    def test_start_records_an_explicit_branch_strategy_and_chinese_progress(self) -> None:
        repo, _ = self.make_repo("lite-branch")

        missing_strategy = self.cli(
            "start",
            "--task-id",
            "missing-workspace-strategy",
            "--flow",
            "lite",
            "--requirement",
            "A work mode must be selected before start",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(
            missing_strategy["error"]["code"], "WORKSPACE_STRATEGY_REQUIRED"
        )

        protected = self.cli(
            "start",
            "--task-id",
            "lite-protected-branch",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Fix a bounded bug on a new branch",
            "--change-category",
            "internal",
            "--target-path",
            "tracked.txt",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(protected["error"]["code"], "PROTECTED_BRANCH")

        git(repo, "checkout", "-q", "-b", "codex/lite-branch")
        # --flow remains a compatibility assertion when it explicitly agrees
        # with the flow inferred from --workspace-strategy.
        response = self.cli(
            "start",
            "--task-id",
            "lite-new-branch",
            "--flow",
            "lite",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Fix a bounded bug on a new branch",
            "--change-category",
            "internal",
            "--target-path",
            "tracked.txt",
            "--repo",
            str(repo),
        )
        self.assertEqual(response["flow"], "lite")
        self.assertEqual(response["flow_name"], "精简流程")
        self.assertEqual(response["workspace_strategy"], "branch")
        self.assertEqual(
            response["workspace_strategy_name"], "新建并切换分支"
        )
        self.assertEqual(
            response["workflow"]["current"],
            {"id": "INTAKE", "name": "需求接收"},
        )

        shown = self.cli("show", "lite-new-branch")
        self.assertEqual(shown["workspace_strategy"], "branch")
        self.assertEqual(
            [item["name"] for item in shown["workflow"]["remaining"]],
            ["预检完成", "实现中", "验证中", "已完成"],
        )
        listed = self.cli("list")["tasks"][0]
        self.assertEqual(listed["flow_name"], "精简流程")
        self.assertEqual(listed["status_name"], "需求接收")
        self.assertEqual(
            listed["workspace_strategy_name"], "新建并切换分支"
        )

        full_rejected = self.cli(
            "start",
            "--task-id",
            "full-branch-mismatch",
            "--flow",
            "full",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Full task cannot use source branch mode",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(
            full_rejected["error"]["code"],
            "FLOW_WORKSPACE_STRATEGY_MISMATCH",
        )

        lite_rejected = self.cli(
            "start",
            "--task-id",
            "lite-worktree-mismatch",
            "--flow",
            "lite",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "Lite task cannot use worktree mode",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(
            lite_rejected["error"]["code"],
            "FLOW_WORKSPACE_STRATEGY_MISMATCH",
        )

    def test_branch_strategy_preflight_rejects_checkout_identity_drift(
        self,
    ) -> None:
        for drift in ("branch", "head"):
            with self.subTest(drift=drift):
                repo, _ = self.make_repo(f"branch-{drift}-drift")
                approved_branch = f"codex/{drift}-drift"
                git(repo, "checkout", "-q", "-b", approved_branch)
                response = self.cli(
                    "start",
                    "--task-id",
                    f"branch-{drift}-drift",
                    "--workspace-strategy",
                    "branch",
                    "--requirement",
                    "Reject checkout identity drift before preflight",
                    "--change-category",
                    "internal",
                    "--target-path",
                    "tracked.txt",
                    "--repo",
                    str(repo),
                )
                task = response["task"]
                approved_head = git(repo, "rev-parse", "HEAD")

                if drift == "branch":
                    git(
                        repo,
                        "checkout",
                        "-q",
                        "-b",
                        "codex/switched-after-start",
                    )
                else:
                    (repo / "tracked.txt").write_text(
                        "committed after start\n", encoding="utf-8"
                    )
                    git(repo, "add", "tracked.txt")
                    git(repo, "commit", "-q", "-m", "drift HEAD")

                actual_branch = git(repo, "branch", "--show-current")
                actual_head = git(repo, "rev-parse", "HEAD")
                state_before = dev_flow.load_state(
                    task["task_id"], self.data
                )
                events_path = (
                    self.data
                    / "tasks"
                    / task["task_id"]
                    / "events.jsonl"
                )
                events_before = events_path.read_bytes()
                rejected = self.cli(
                    "preflight",
                    task["task_id"],
                    "--expected-revision",
                    str(task["revision"]),
                    "--preview",
                    expected_code=2,
                )
                self.assertEqual(
                    rejected["error"]["code"], "CHECKOUT_DRIFT"
                )
                self.assertEqual(
                    rejected["error"]["details"]["approved_branch"],
                    approved_branch,
                )
                self.assertEqual(
                    rejected["error"]["details"]["actual_branch"],
                    actual_branch,
                )
                self.assertEqual(
                    rejected["error"]["details"]["approved_head_sha"],
                    approved_head,
                )
                self.assertEqual(
                    rejected["error"]["details"]["actual_head_sha"],
                    actual_head,
                )
                self.assertEqual(
                    dev_flow.load_state(task["task_id"], self.data),
                    state_before,
                )
                self.assertEqual(events_path.read_bytes(), events_before)

    def test_branch_strategy_binding_allows_confirmed_head_reassessment(
        self,
    ) -> None:
        repo, _ = self.make_repo("branch-binding-lifecycle")
        branch = "codex/branch-binding-lifecycle"
        git(repo, "checkout", "-q", "-b", branch)
        started = self.cli(
            "start",
            "--task-id",
            "branch-binding-lifecycle",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Allow a new HEAD only after the initial checkout is confirmed",
            "--change-category",
            "internal",
            "--target-path",
            "tracked.txt",
            "--repo",
            str(repo),
        )
        binding = started["task"]["repositories"][0]["branch_binding"]
        self.assertEqual(binding["branch"], branch)
        self.assertEqual(binding["head_sha"], git(repo, "rev-parse", "HEAD"))
        self.assertFalse(binding["initial_preflight_confirmed"])

        task = started["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertTrue(
            task["repositories"][0]["branch_binding"][
                "initial_preflight_confirmed"
            ]
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "approved branch checkout",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")

        (repo / "tracked.txt").write_text(
            "committed implementation\n", encoding="utf-8"
        )
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "implementation")
        new_head = git(repo, "rev-parse", "HEAD")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "transition",
            task,
            "--to",
            "PREFLIGHTED",
            "--note",
            "reassess the committed implementation",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        reassessed = self.mutate("preflight", task)
        self.assertEqual(reassessed["status"], "PREFLIGHTED")
        state_value = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            state_value["repositories"][0]["preflight"]["head_sha"],
            new_head,
        )
        self.assertEqual(
            state_value["repositories"][0]["branch_binding"]["branch"],
            branch,
        )

        self.mutate(
            "approve",
            state_value,
            "--gate",
            "lite",
            "--note",
            "approved reassessed branch checkout",
        )
        state_value = dev_flow.load_state(task["task_id"], self.data)
        legacy = dev_flow._copy_state(state_value)
        legacy["repositories"][0].pop("branch_binding")
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._require_lite_gate(legacy)
        self.assertEqual(
            captured.exception.code, "CHECKOUT_BINDING_MISSING"
        )

    def test_custom_protected_branch_extends_default_protection(self) -> None:
        repo, _ = self.make_repo("extended-protected-branches")
        for branch in ("main", "release"):
            with self.subTest(branch=branch):
                if branch != git(repo, "branch", "--show-current"):
                    git(repo, "checkout", "-q", "-b", branch)
                rejected = self.cli(
                    "start",
                    "--task-id",
                    f"protected-{branch}",
                    "--workspace-strategy",
                    "branch",
                    "--protected-branch",
                    "release",
                    "--requirement",
                    "Custom protection must preserve default branches",
                    "--repo",
                    str(repo),
                    expected_code=2,
                )
                self.assertEqual(
                    rejected["error"]["code"], "PROTECTED_BRANCH"
                )
                self.assertEqual(
                    rejected["error"]["details"]["branch"], branch
                )

    def test_branch_strategy_rejects_remote_default_and_symbolic_head(
        self,
    ) -> None:
        repo, remote = self.make_repo("nonstandard-default-branch")
        git(repo, "checkout", "-q", "-b", "develop")
        git(repo, "push", "-q", "-u", "origin", "develop")
        git(remote, "symbolic-ref", "HEAD", "refs/heads/develop")
        git(repo, "remote", "set-head", "origin", "develop")
        default_rejected = self.cli(
            "start",
            "--task-id",
            "nonstandard-default-branch",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Do not treat a remote default branch as a feature branch",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(
            default_rejected["error"]["code"], "PROTECTED_BRANCH"
        )
        self.assertEqual(
            default_rejected["error"]["details"]["branch"], "develop"
        )

        symbolic_repo, _ = self.make_repo("symbolic-branch-head")
        git(symbolic_repo, "branch", "codex/direct-target")
        git(
            symbolic_repo,
            "symbolic-ref",
            "refs/heads/codex/alias",
            "refs/heads/codex/direct-target",
        )
        git(
            symbolic_repo,
            "symbolic-ref",
            "HEAD",
            "refs/heads/codex/alias",
        )
        symbolic_rejected = self.cli(
            "start",
            "--task-id",
            "symbolic-branch-head",
            "--workspace-strategy",
            "branch",
            "--requirement",
            "Branch mode requires a direct local branch",
            "--repo",
            str(symbolic_repo),
            expected_code=2,
        )
        self.assertEqual(
            symbolic_rejected["error"]["code"],
            "SYMBOLIC_WORKSPACE_BRANCH",
        )

    def test_lite_flow_rejects_full_flow_commands_and_gates(self) -> None:
        repo, _ = self.make_repo("lite-guard")
        self.start_lite(repo, task_id="lite-guard")
        task = dev_flow.load_state("lite-guard", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-guard", self.data)

        for arguments in (
            ["approve", "--gate", "baseline-fetch", "--note", "no"],
            ["baseline", "--materialize"],
            ["record-index", "--index-id", "nope"],
            ["set-route", "direct", "--reason", "no"],
            ["prepare-workspace"],
            ["review-snapshot"],
        ):
            with self.subTest(command=arguments[0], arguments=arguments[1:]):
                rejected = self.mutate(
                    arguments[0], task, *arguments[1:], expected_code=2
                )
                self.assertEqual(rejected["error"]["code"], "FLOW_MISMATCH")

        blocked_transition = self.mutate(
            "transition", task, "--to", "BASELINED", expected_code=2
        )
        self.assertEqual(
            blocked_transition["error"]["code"], "INVALID_TRANSITION"
        )
        self.assertEqual(
            blocked_transition["error"]["details"]["allowed"],
            ["BLOCKED", "CANCELLED", "IMPLEMENTING"],
        )

        full_repo, _ = self.make_repo("full-guard")
        self.start(full_repo, task_id="full-guard")
        full_task = dev_flow.load_state("full-guard", self.data)
        rejected = self.mutate(
            "approve",
            full_task,
            "--gate",
            "lite",
            "--note",
            "not applicable",
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "FLOW_MISMATCH")

    def test_lite_gate_requires_allow_dirty_and_a_fresh_preflight(self) -> None:
        repo, _ = self.make_repo("lite-dirty")
        (repo / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
        self.start_lite(repo, task_id="lite-dirty")
        task = dev_flow.load_state("lite-dirty", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-dirty", self.data)

        rejected = self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "dirty tree",
            expected_code=2,
        )
        self.assertEqual(rejected["error"]["code"], "DIRTY_APPROVAL_REQUIRED")

        approved = self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "dirty tree accepted",
            "--allow-dirty",
        )
        self.assertTrue(approved["approval"]["dirty_allowed"])

        # A refreshed preflight invalidates the earlier lite approval.
        task = dev_flow.load_state("lite-dirty", self.data)
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-dirty", self.data)
        self.assertNotIn("lite", task["approvals"])
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "APPROVAL_REQUIRED")

    def test_lite_implementation_entry_rejects_checkout_drift(self) -> None:
        repo, _ = self.make_repo("lite-drift")
        task = self.approved_lite_task(repo, task_id="lite-drift")

        (repo / "tracked.txt").write_text("early edit\n", encoding="utf-8")
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(
            rejected["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED"
        )

        (repo / "tracked.txt").write_text("initial lite-drift\n", encoding="utf-8")
        git(repo, "checkout", "-q", "-b", "elsewhere")
        task = dev_flow.load_state("lite-drift", self.data)
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CHECKOUT_DRIFT")

        git(repo, "checkout", "-q", "main")
        task = dev_flow.load_state("lite-drift", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        self.assertEqual(
            dev_flow.load_state("lite-drift", self.data)["status"],
            "IMPLEMENTING",
        )

    def test_lite_done_requires_current_passing_tests(self) -> None:
        repo, _ = self.make_repo("lite-verify")
        task = self.approved_lite_task(repo, task_id="lite-verify")
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-verify", self.data)
        (repo / "tracked.txt").write_text("candidate fix\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-verify", self.data)

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "1",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        (repo / "tracked.txt").write_text("changed after tests\n", encoding="utf-8")
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")

        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-verify", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(
            dev_flow.load_state("lite-verify", self.data)["status"], "DONE"
        )

    def test_lite_rework_reopens_scope_with_note_and_invalidates_tests(self) -> None:
        repo, _ = self.make_repo("lite-rework")
        task = self.approved_lite_task(repo, task_id="lite-rework")
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-rework", self.data)
        (repo / "tracked.txt").write_text("first attempt\n", encoding="utf-8")
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-rework", self.data)

        rejected = self.mutate(
            "transition", task, "--to", "PREFLIGHTED", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "--to",
            "PREFLIGHTED",
            "--note",
            "scope grew beyond the approved fix",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.assertEqual(task["status"], "PREFLIGHTED")

        # The edited tree no longer matches the approved snapshot, so a fresh
        # preflight and a new dirty-approval are required to continue.
        rejected = self.mutate(
            "transition", task, "--to", "IMPLEMENTING", expected_code=2
        )
        self.assertEqual(
            rejected["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED"
        )
        self.mutate("preflight", task)
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "lite",
            "--note",
            "wider fix approved",
            "--allow-dirty",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "IMPLEMENTING")
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "VERIFYING")
        task = dev_flow.load_state("lite-rework", self.data)

        # Tests recorded under the earlier approval are historical only.
        rejected = self.mutate(
            "transition", task, "--to", "DONE", expected_code=2
        )
        self.assertEqual(rejected["error"]["code"], "CURRENT_TEST_REQUIRED")
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "pytest -q",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state("lite-rework", self.data)
        self.mutate("transition", task, "--to", "DONE")
        self.assertEqual(
            dev_flow.load_state("lite-rework", self.data)["status"], "DONE"
        )


if __name__ == "__main__":
    unittest.main()
