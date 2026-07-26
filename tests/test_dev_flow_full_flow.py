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


class DevFlowFullFlowTest(test_case.DevFlowTestCase):
    def test_full_flow_creates_worktree_and_complete_review_snapshot(self) -> None:
        repo, _ = self.make_repo("flow")
        task = self.start(repo)["task"]
        self.assertEqual(task["impact_generation"], 0)
        self.assertEqual(task["planning_generation"], 0)
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["repositories"][0]["preflight"]["remote"], "origin")

        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--fetch",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local remote and detached analysis worktree approved",
            "--allow-fetch",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--fetch", "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline = task["repositories"][0]["baseline"]
        self.assertEqual(baseline["base_sha"], git(repo, "rev-parse", "origin/main"))
        analysis = task["repositories"][0]["analysis_workspace"]
        self.assertTrue(analysis["detached"])
        self.assertEqual(analysis["head_sha"], baseline["base_sha"])
        self.assertEqual(git(Path(analysis["path"]), "branch", "--show-current"), "")
        self.assertEqual(
            dev_flow.find_active_task_for_cwd(analysis["path"], self.data)["task_id"],
            task["task_id"],
        )

        git(repo, "commit", "-q", "--allow-empty", "-m", "source moved after baseline")
        mismatched = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--commit",
            git(repo, "rev-parse", "HEAD"),
            "--index-id",
            "memory-index-mismatch",
            expected_code=2,
        )
        self.assertEqual(mismatched["error"]["code"], "INDEX_BASE_MISMATCH")
        index_response = self.mutate(
            "record-index", task, "--index-id", "memory-index-1"
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "INDEXED")
        self.assertEqual(index_response["repositories"][0]["repo_path"], analysis["path"])

        impact = self.root / "impact.md"
        impact.write_text("# Impact\n\nOne repository.\n", encoding="utf-8")
        no_impact = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "must not route without impact",
            expected_code=2,
        )
        self.assertEqual(no_impact["error"]["code"], "ARTIFACT_REQUIRED")
        artifact_response = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            artifact_response["artifact"]["metadata"]["impact_generation"], 0
        )
        artifact_hash = artifact_response["artifact"]["sha256"]

        previous_index_record_id = task["repositories"][0]["index"]["index_record_id"]
        self.mutate("record-index", task, "--index-id", "memory-index-1")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotEqual(
            task["repositories"][0]["index"]["index_record_id"],
            previous_index_record_id,
        )
        stale_impact = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "stale impact must not route",
            expected_code=2,
        )
        self.assertEqual(stale_impact["error"]["code"], "STALE_IMPACT")
        impact.write_text("# Impact\n\nRefreshed index coverage.\n", encoding="utf-8")
        artifact_response = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        artifact_hash = artifact_response["artifact"]["sha256"]

        self.mutate("set-route", task, "direct", "--reason", "localized change")
        task = dev_flow.load_state(task["task_id"], self.data)
        impact.write_text("# Impact\n\nUpdated, still one repository.\n", encoding="utf-8")
        latest_impact = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["route"])
        missing_reselection = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "route must be selected again",
            "--artifact-sha256",
            latest_impact["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(missing_reselection["error"]["code"], "ROUTE_REQUIRED")
        self.mutate("set-route", task, "direct", "--reason", "updated impact")
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_route = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "stale impact",
            "--artifact-sha256",
            artifact_hash,
            expected_code=2,
        )
        self.assertEqual(stale_route["error"]["code"], "APPROVAL_ARTIFACT_MISMATCH")
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "impact reviewed",
            "--artifact-sha256",
            latest_impact["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)

        dry_run = self.mutate("prepare-workspace", task)
        self.assertTrue(dry_run["dry_run"])
        self.assertEqual(dry_run["revision"], task["revision"] + 1)
        self.assertFalse(Path(dry_run["plans"][0]["path"]).exists())
        workspace_plan_hash = dry_run["plan_artifact"]["sha256"]
        task = dev_flow.load_state(task["task_id"], self.data)
        repeated_plan = self.mutate("prepare-workspace", task)
        self.assertTrue(repeated_plan["unchanged"])
        self.assertEqual(repeated_plan["revision"], task["revision"])

        denied = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "worktree plan approved",
            "--artifact-sha256",
            workspace_plan_hash,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        plan_mismatch = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--execute",
            "--branch",
            "codex/not-approved",
            expected_code=2,
        )
        self.assertEqual(plan_mismatch["error"]["code"], "WORKSPACE_PLAN_MISMATCH")
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "WORKSPACE_READY")
        workspace = Path(task["repositories"][0]["workspace"]["path"])
        self.assertTrue(workspace.is_dir())
        self.assertEqual(git(workspace, "branch", "--show-current"), "codex/task-1")

        # A recorded workspace may move forward and is still reused idempotently.
        (workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        git(workspace, "add", "committed.txt")
        git(workspace, "commit", "-q", "-m", "early implementation")
        second = self.mutate("prepare-workspace", task, "--execute")
        self.assertFalse(second["workspaces"][0]["created"])
        self.assertEqual(second["workspaces"][0]["head_sha"], git(workspace, "rev-parse", "HEAD"))
        task = dev_flow.load_state(task["task_id"], self.data)
        replacement_path = self.root / "same-generation-replacement"
        replacement = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--path",
            str(replacement_path),
            "--branch",
            "codex/same-generation-replacement",
            expected_code=2,
        )
        self.assertEqual(
            replacement["error"]["code"], "WORKSPACE_REASSESSMENT_REQUIRED"
        )
        self.assertFalse(replacement_path.exists())

        task = self.record_workspace_indexes(task)
        workspace_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(workspace_index["role"], "workspace")
        self.assertEqual(workspace_index["repo_path"], str(workspace))
        git(workspace, "switch", "-q", "-c", "workspace-hijack")
        hijacked = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(hijacked["error"]["code"], "STALE_WORKSPACE_INDEX")
        git(workspace, "switch", "-q", "codex/task-1")
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["planning_generation"], 1)
        contract = self.root / "direct-contract.md"
        contract.write_text("# Contract\n\nOnly flow repo changes.\n", encoding="utf-8")
        contract_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        first_planning_context = contract_response["artifact"]["metadata"][
            "planning_context"
        ]
        self.assertEqual(first_planning_context["planning_generation"], 1)
        self.assertEqual(
            first_planning_context["route"]["approval_id"],
            task["approvals"]["route"]["approval_id"],
        )
        self.assertEqual(
            first_planning_context["workspace"]["generation"], 0
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "direct contract reviewed",
            "--artifact-sha256",
            contract_response["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        contract.write_text("# Contract\n\nUpdated contract.\n", encoding="utf-8")
        latest_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_plan = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(stale_plan["error"]["code"], "STALE_APPROVAL")
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "updated direct contract reviewed",
            "--artifact-sha256",
            latest_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "cached.txt").write_text("cached\n", encoding="utf-8")
        git(workspace, "add", "cached.txt")
        (workspace / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (workspace / "untracked.bin").write_bytes(b"\x00untracked\xff")
        task = self.record_workspace_indexes(task)

        # Editing approved evidence on disk is caught, then an explicit replan
        # clears the old approval and permits a new planning artifact.
        contract.write_text("# Contract\n\nChanged during implementation.\n", encoding="utf-8")
        stale_after_implementation = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "VERIFYING",
            expected_code=2,
        )
        self.assertEqual(stale_after_implementation["error"]["code"], "ARTIFACT_CHANGED")
        missing_note = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(missing_note["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "PLANNING",
            "--note",
            "implementation revealed a contract change",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("plan", task["approvals"])
        self.assertEqual(task["planning_generation"], 2)
        # Restore the previously recorded bytes so this rejection proves the
        # planning epoch binding rather than ordinary on-disk artifact drift.
        contract.write_text("# Contract\n\nUpdated contract.\n", encoding="utf-8")
        old_epoch_plan = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "plan",
            "--note",
            "old planning epoch must not be reapproved",
            "--artifact-sha256",
            latest_contract["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(old_epoch_plan["error"]["code"], "STALE_PLAN")
        contract.write_text(
            "# Contract\n\nChanged during implementation.\n", encoding="utf-8"
        )
        implementation_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            implementation_contract["artifact"]["metadata"]["planning_context"][
                "planning_generation"
            ],
            2,
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "implementation contract revision reviewed",
            "--artifact-sha256",
            implementation_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        # A later impact reassessment returns to INDEXED, preserves the actual
        # worktree/history, and invalidates every downstream human gate.
        self.mutate(
            "record-test",
            task,
            "--name",
            "pre-reassessment",
            "--command",
            "python -m unittest",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        missing_reassessment_note = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "INDEXED",
            expected_code=2,
        )
        self.assertEqual(missing_reassessment_note["error"]["code"], "INVALID_ARGUMENT")
        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "implementation exposed broader impact",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["route"])
        self.assertIsNone(task["repositories"][0]["workspace"])
        self.assertEqual(
            task["repositories"][0]["workspace_history"][-1]["path"], str(workspace)
        )
        self.assertEqual(
            task["repositories"][0]["workspace_history"][-1][
                "workspace_index"
            ]["index_id"],
            workspace_index["index_id"],
        )
        self.assertIsNone(task["repositories"][0]["workspace_index"])
        self.assertFalse(task["workspace"]["ready"])
        self.assertIsNone(task["workspace"]["plan"])
        self.assertEqual(task["workspace"]["generation"], 1)
        self.assertEqual(task["impact_generation"], 1)
        for cleared_gate in ("route", "workspace", "plan", "review"):
            self.assertNotIn(cleared_gate, task["approvals"])

        stale_impact_epoch = self.cli(
            "set-route",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "direct",
            "--reason",
            "old impact epoch must not be routed",
            expected_code=2,
        )
        self.assertEqual(stale_impact_epoch["error"]["code"], "STALE_IMPACT")
        impact.write_text("# Impact\n\nReassessed impact.\n", encoding="utf-8")
        reassessed_impact = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        self.assertEqual(
            reassessed_impact["artifact"]["metadata"]["impact_generation"], 1
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("set-route", task, "direct", "--reason", "reassessed localized change")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "reassessed impact approved",
            "--artifact-sha256",
            reassessed_impact["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        registry_path = self.data / "workspace-registry.json"
        registry_before_reuse = registry_path.read_bytes()
        revision_before_reuse = task["revision"]
        retired_reuse = self.cli(
            "prepare-workspace",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--path",
            str(workspace),
            "--branch",
            "codex/task-1",
            expected_code=2,
        )
        self.assertEqual(
            retired_reuse["error"]["code"], "RETIRED_WORKSPACE_REUSE"
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data)["revision"],
            revision_before_reuse,
        )
        self.assertEqual(registry_path.read_bytes(), registry_before_reuse)
        reassessed_workspace_plan = self.mutate("prepare-workspace", task)
        self.assertNotEqual(
            reassessed_workspace_plan["plan_artifact"]["sha256"],
            workspace_plan_hash,
        )
        self.assertEqual(
            reassessed_workspace_plan["plan_artifact"]["metadata"][
                "workspace_generation"
            ],
            1,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "workspace",
            "--note",
            "reassessed workspace plan approved",
            "--artifact-sha256",
            reassessed_workspace_plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        reassessed_workspace = Path(task["repositories"][0]["workspace"]["path"])
        self.assertNotEqual(reassessed_workspace, workspace)
        self.assertEqual(
            task["repositories"][0]["workspace"]["branch"], "codex/task-1-r1"
        )
        workspace = reassessed_workspace
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["planning_generation"], 3)
        stale_after_impact_reassessment = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "plan",
            "--note",
            "pre-reassessment plan must not be reapproved",
            "--artifact-sha256",
            implementation_contract["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(
            stale_after_impact_reassessment["error"]["code"], "STALE_PLAN"
        )
        contract.write_text("# Contract\n\nContract after impact reassessment.\n", encoding="utf-8")
        reassessed_contract = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        reassessed_context = reassessed_contract["artifact"]["metadata"][
            "planning_context"
        ]
        self.assertEqual(reassessed_context["planning_generation"], 3)
        self.assertEqual(reassessed_context["impact_generation"], 1)
        self.assertEqual(reassessed_context["workspace"]["generation"], 1)
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "reassessed contract approved",
            "--artifact-sha256",
            reassessed_contract["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)
        (workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        git(workspace, "add", "committed.txt")
        git(workspace, "commit", "-q", "-m", "reassessed implementation")
        (workspace / "cached.txt").write_text("cached\n", encoding="utf-8")
        git(workspace, "add", "cached.txt")
        (workspace / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (workspace / "untracked.bin").write_bytes(b"\x00untracked\xff")
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "VERIFYING")
        task = dev_flow.load_state(task["task_id"], self.data)
        old_test_denied = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(old_test_denied["error"]["code"], "CURRENT_TEST_REQUIRED")
        test_output = self.root / "unit-test-output.txt"
        test_output.write_text("all tests passed\n", encoding="utf-8")
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "python -m unittest",
            "--exit-code",
            "0",
            "--output",
            str(test_output),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        test_output.write_text("tampered output\n", encoding="utf-8")
        tampered_test_output = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            tampered_test_output["error"]["code"], "CURRENT_TEST_REQUIRED"
        )
        test_output.unlink()
        missing_test_output = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            missing_test_output["error"]["code"], "CURRENT_TEST_REQUIRED"
        )
        test_output.write_text("all tests passed\n", encoding="utf-8")
        response = self.mutate("review-snapshot", task)
        snapshot_receipt = response["snapshot"]
        self.assertNotIn("repositories", snapshot_receipt)
        self.assertEqual(response["status"], "REVIEWING")
        task = dev_flow.load_state(task["task_id"], self.data)
        snapshot = task["review_snapshots"][-1]
        sections = snapshot["repositories"][0]["sections"]
        fingerprint_reference = snapshot["repositories"][0]["fingerprint"]
        self.assertEqual(
            fingerprint_reference["storage"],
            dev_flow._FINGERPRINT_STORAGE_KIND,
        )
        self.assertTrue(Path(fingerprint_reference["path"]).is_file())
        self.assertIn("committed.txt", "\n".join(sections["committed"]["files"]))
        self.assertIn("cached.txt", "\n".join(sections["cached"]["files"]))
        self.assertIn("tracked.txt", "\n".join(sections["unstaged"]["files"]))
        self.assertIn("untracked.bin", [item["path"] for item in sections["untracked"]["files"]])
        with tarfile.open(sections["untracked"]["archive_path"], "r") as archive:
            self.assertIn("untracked.bin", archive.getnames())
        for name in ("committed", "cached", "unstaged"):
            self.assertTrue(Path(sections[name]["path"]).is_file())

        review_report = self.root / "review-report.md"
        review_report.write_text(
            "# Review\n\nVerdict: CONDITIONAL\n\nNo findings.\n", encoding="utf-8"
        )
        misplaced_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
            expected_code=2,
        )
        self.assertEqual(misplaced_verdict["error"]["code"], "INVALID_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: CONDITIONAL\n\n  Verdict: FAIL\n", encoding="utf-8"
        )
        duplicate_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
            expected_code=2,
        )
        self.assertEqual(duplicate_verdict["error"]["code"], "INVALID_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: CONDITIONAL\n\n# Review\n\nNo findings.\n", encoding="utf-8"
        )
        missing_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            expected_code=2,
        )
        self.assertEqual(missing_verdict["error"]["code"], "INVALID_ARGUMENT")
        mismatched_verdict = self.cli(
            "record-artifact",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "PASS",
            expected_code=2,
        )
        self.assertEqual(
            mismatched_verdict["error"]["code"], "REVIEW_VERDICT_MISMATCH"
        )
        report_response = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "CONDITIONAL",
        )
        self.assertEqual(
            report_response["artifact"]["metadata"]["review_snapshot_sha256"],
            snapshot["sha256"],
        )
        self.assertEqual(report_response["artifact"]["metadata"]["verdict"], "CONDITIONAL")
        task = dev_flow.load_state(task["task_id"], self.data)
        conditional_denied = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "review",
            "--note",
            "review report approved",
            "--artifact-sha256",
            report_response["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(
            conditional_denied["error"]["code"], "CONDITIONAL_ACCEPTANCE_REQUIRED"
        )
        conditional_approval = self.mutate(
            "approve",
            task,
            "--gate",
            "review",
            "--note",
            "conditional review explicitly accepted",
            "--artifact-sha256",
            report_response["artifact"]["sha256"],
            "--accept-conditional",
        )
        self.assertTrue(conditional_approval["approval"]["conditional_accepted"])
        task = dev_flow.load_state(task["task_id"], self.data)
        verified_conditional, _ = dev_flow._require_review_gate(task)
        self.assertTrue(verified_conditional["conditional_accepted"])
        newer_snapshot = self.mutate("review-snapshot", task)["snapshot"]
        self.assertNotEqual(newer_snapshot["sha256"], snapshot["sha256"])
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_report = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(stale_report["error"]["code"], "STALE_REVIEW_REPORT")
        review_report.write_text(
            "Verdict: FAIL\n\n# Review\n\nBlocking finding.\n", encoding="utf-8"
        )
        failing_report = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "FAIL",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        failed_approval = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "review",
            "--note",
            "must not approve",
            "--artifact-sha256",
            failing_report["artifact"]["sha256"],
            expected_code=2,
        )
        self.assertEqual(failed_approval["error"]["code"], "REVIEW_VERDICT_FAILED")
        failed_final = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(failed_final["error"]["code"], "REVIEW_VERDICT_FAILED")
        review_report.write_text(
            "Verdict: PASS\n\n# Review\n\nUpdated: no findings.\n", encoding="utf-8"
        )
        latest_report = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "review-report",
            "--path",
            str(review_report),
            "--verdict",
            "PASS",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        stale_review = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(stale_review["error"]["code"], "STALE_APPROVAL")
        self.mutate(
            "approve",
            task,
            "--gate",
            "review",
            "--note",
            "updated review report approved",
            "--artifact-sha256",
            latest_report["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        committed_patch = Path(
            newer_snapshot["repositories"][0]["sections"]["committed"]["path"]
        )
        original_patch = committed_patch.read_bytes()
        committed_patch.write_bytes(original_patch + b"tampered\n")
        tampered_snapshot = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "FINALIZING",
            expected_code=2,
        )
        self.assertEqual(tampered_snapshot["error"]["code"], "CURRENT_REVIEW_REQUIRED")
        self.assertIn("committed", tampered_snapshot["error"]["message"])
        committed_patch.write_bytes(original_patch)
        self.mutate("transition", task, "FINALIZING")
        task = dev_flow.load_state(task["task_id"], self.data)
        done = self.mutate("transition", task, "DONE")
        self.assertEqual(done["status"], "DONE")
        self.assertIsNone(dev_flow.find_active_task_for_cwd(workspace, self.data))

    def test_atomic_rollback_evidence_is_recoverable_and_unblocks_cancel(
        self,
    ) -> None:
        repo, _ = self.make_repo("rollback-residue")
        task = self.start(repo)["task"]
        task_dir = self.data / "tasks" / task["task_id"]
        state_path = task_dir / "state.json"
        residue = task_dir / ".state.json.rollback-deadbeef"
        # A SIGKILL, power loss, or hook timeout leaves the rollback file the
        # interrupted writer would have removed in its finally block.
        residue.write_bytes(state_path.read_bytes())
        # The same interruption can strand the shared configuration file
        # before it was ever committed.
        config_residue = self.data / ".config.json.rollback-cafe"
        config_residue.write_bytes(b"")

        blocked = self.mutate(
            "cancel", task, "--reason", "blocked by residue", expected_code=2
        )
        self.assertEqual(
            blocked["error"]["code"], "ATOMIC_RECOVERY_REQUIRED"
        )
        self.assertEqual(
            blocked["error"]["details"]["rollback_candidates"],
            [str(residue)],
        )
        self.assertEqual(
            blocked["error"]["details"]["recovery_command"],
            "recover-atomic-write",
        )
        blocked_scope = self.cli(
            "scope", "--add", str(repo), expected_code=2
        )
        self.assertEqual(
            blocked_scope["error"]["code"], "ATOMIC_RECOVERY_REQUIRED"
        )

        report = self.cli("recover-atomic-write")
        self.assertFalse(report["changed"])
        self.assertEqual(
            {
                candidate["destination"]["path"]: candidate["resolution"]
                for candidate in report["candidates"]
            },
            {
                str(self.data / "config.json"): "uncommitted",
                str(state_path): "identical",
            },
        )
        recorded = next(
            candidate
            for candidate in report["candidates"]
            if candidate["destination"]["path"] == str(state_path)
        )
        self.assertEqual(
            recorded["destination"]["sha256"],
            recorded["rollback"]["sha256"],
        )
        self.assertEqual(
            recorded["destination"]["schema"]["revision"],
            task["revision"],
        )
        # A report alone never touches the evidence.
        self.assertTrue(residue.exists())

        recovery = self.cli("recover-atomic-write", "--apply")
        self.assertTrue(recovery["changed"])
        self.assertEqual(
            sorted(recovery["removed"]),
            sorted([str(config_residue), str(residue)]),
        )
        self.assertFalse(residue.exists())
        self.assertFalse(config_residue.exists())
        self.assertEqual(
            state_path.read_bytes(),
            (self.data / "tasks" / task["task_id"] / "state.json").read_bytes(),
        )

        cancelled = self.mutate("cancel", task, "--reason", "recovered")
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(cancelled["revision"], task["revision"] + 1)

    def test_atomic_rollback_mismatch_needs_an_explicit_resolution(
        self,
    ) -> None:
        repo, _ = self.make_repo("rollback-mismatch")
        task = self.start(repo)["task"]
        task_dir = self.data / "tasks" / task["task_id"]
        state_path = task_dir / "state.json"
        superseded = json.loads(state_path.read_text(encoding="utf-8"))
        superseded["revision"] = 0
        residue = task_dir / ".state.json.rollback-cafe"
        residue.write_text(
            json.dumps(superseded, sort_keys=True), encoding="utf-8"
        )

        denied = self.cli(
            "recover-atomic-write", "--apply", expected_code=2
        )
        self.assertEqual(
            denied["error"]["code"], "ATOMIC_ROLLBACK_MISMATCH"
        )
        self.assertEqual(denied["error"]["details"]["removed"], [])
        blocked = denied["error"]["details"]["blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["resolution"], "mismatch")
        self.assertEqual(
            blocked[0]["destination"]["schema"]["revision"],
            task["revision"],
        )
        self.assertEqual(blocked[0]["rollback"]["schema"]["revision"], 0)
        self.assertNotEqual(
            blocked[0]["destination"]["sha256"],
            blocked[0]["rollback"]["sha256"],
        )
        self.assertEqual(
            denied["error"]["details"]["resolutions"],
            ["keep-current", "restore-rollback"],
        )
        # Nothing was chosen on the user's behalf.
        self.assertTrue(residue.exists())

        rollback_sha = blocked[0]["rollback"]["sha256"]
        stale = self.cli(
            "recover-atomic-write",
            "--path",
            str(state_path),
            "--resolve",
            "keep-current",
            "--rollback-sha256",
            "0" * 64,
            expected_code=2,
        )
        self.assertEqual(
            stale["error"]["code"], "ATOMIC_ROLLBACK_MISMATCH"
        )
        self.assertEqual(
            stale["error"]["details"]["expected_sha256"], rollback_sha
        )
        unproven = self.cli(
            "recover-atomic-write",
            "--path",
            str(state_path),
            "--resolve",
            "keep-current",
            expected_code=2,
        )
        self.assertEqual(unproven["error"]["code"], "INVALID_ARGUMENT")
        self.assertTrue(residue.exists())

        # The rollback file itself is an accepted spelling of the target.
        resolved = self.cli(
            "recover-atomic-write",
            "--path",
            str(residue),
            "--resolve",
            "keep-current",
            "--rollback-sha256",
            rollback_sha,
        )
        self.assertEqual(resolved["resolved"], "keep-current")
        self.assertEqual(resolved["removed"], [str(residue)])
        self.assertFalse(residue.exists())
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8"))["revision"],
            task["revision"],
        )
        self.assertEqual(
            self.cli("recover-atomic-write", "--apply", expected_code=2)[
                "error"
            ]["code"],
            "ATOMIC_ROLLBACK_NOT_FOUND",
        )
        self.mutate("cancel", task, "--reason", "resolved")

        # The opposite decision restores the preserved bytes verbatim.
        committed = state_path.read_bytes()
        restore = task_dir / ".state.json.rollback-beef"
        restore.write_bytes(
            json.dumps(superseded, sort_keys=True).encode("utf-8")
        )
        restore_sha = dev_flow._sha256_file(restore)
        restored = self.cli(
            "recover-atomic-write",
            "--path",
            str(state_path),
            "--resolve",
            "restore-rollback",
            "--rollback-sha256",
            restore_sha,
        )
        self.assertEqual(restored["restored"], [str(state_path)])
        self.assertFalse(restore.exists())
        self.assertNotEqual(state_path.read_bytes(), committed)
        self.assertEqual(dev_flow._sha256_file(state_path), restore_sha)

    def test_unknown_gate_is_rejected_without_consuming_a_revision(
        self,
    ) -> None:
        repo, _ = self.make_repo("unknown-gate")
        task = self.start(repo)["task"]
        self.assertEqual(task["status"], "INTAKE")
        denied = self.mutate(
            "approve",
            task,
            "--gate",
            "reviewwww",
            "--note",
            "typo",
            expected_code=2,
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"]["code"], "INVALID_ARGUMENT")

        state = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(state["revision"], task["revision"])
        self.assertEqual(state["status"], "INTAKE")
        self.assertEqual(state["approvals"], {})

        # The dispatch and the argparse surface share one vocabulary, so the
        # handler refuses the same value when it is called directly.
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow.command_approve(
                argparse.Namespace(
                    task_id=task["task_id"],
                    task_option=None,
                    data_dir=str(self.data),
                    expected_revision=task["revision"],
                    gate="reviewwww",
                    note="typo",
                    artifact_sha256=None,
                    accept_conditional=False,
                    allow_fetch=False,
                    allow_dirty=False,
                )
            )
        self.assertEqual(captured.exception.code, "INVALID_ARGUMENT")
        self.assertEqual(captured.exception.details["gate"], "reviewwww")
        self.assertEqual(
            dev_flow.APPROVAL_GATES,
            (
                "baseline-fetch",
                "impact-degraded",
                "route",
                "workspace",
                "plan",
                "review",
                dev_flow.LITE_GATE,
            ),
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data)["revision"],
            task["revision"],
        )

    def test_cancel_is_terminal_and_audited(self) -> None:
        repo, _ = self.make_repo("cancel")
        task = self.start(repo)["task"]
        response = self.mutate("cancel", task, "--reason", "requirement withdrawn")
        self.assertEqual(response["status"], "CANCELLED")
        state = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(state["cancelled"]["reason"], "requirement withdrawn")
        events = [
            json.loads(line)
            for line in (
                self.data / "tasks" / task["task_id"] / "events.jsonl"
            )
            .read_text()
            .splitlines()
        ]
        cancellation_facts = [
            event
            for event in events
            if event["revision"] == response["revision"]
        ]
        self.assertEqual(
            {event["type"] for event in cancellation_facts},
            {"task_cancelled", "state_transitioned"},
        )
        self.assertEqual(
            len(
                {
                    event["transaction_id"]
                    for event in cancellation_facts
                }
            ),
            1,
        )

    def test_nonstandard_feature_branch_needs_explicit_base(self) -> None:
        repo = self.root / "feature-only"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "feature", str(repo)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repo, "config", "user.name", "Dev Flow Test")
        git(repo, "config", "user.email", "dev-flow@example.invalid")
        (repo / "file.txt").write_text("one\n", encoding="utf-8")
        git(repo, "add", "file.txt")
        git(repo, "commit", "-q", "-m", "initial")
        task = self.start(repo, task_id="feature-base")["task"]
        response = self.mutate("preflight", task)
        self.assertFalse(response["ready"])
        self.assertEqual(response["status"], "BLOCKED")
        self.assertIn(
            "base_branch_unresolved",
            response["repositories"][0]["preflight"]["blockers"],
        )

    def test_baseline_approval_binds_exact_clean_or_explicit_dirty_snapshot(self) -> None:
        clean_repo, _ = self.make_repo("clean-preflight-drift")
        clean_task = self.start(clean_repo, task_id="clean-preflight-drift")["task"]
        self.mutate("preflight", clean_task)
        clean_task = dev_flow.load_state(clean_task["task_id"], self.data)
        self.mutate(
            "approve",
            clean_task,
            "--gate",
            "baseline-fetch",
            "--note",
            "clean snapshot approved",
        )
        clean_task = dev_flow.load_state(clean_task["task_id"], self.data)
        (clean_repo / "tracked.txt").write_text("changed after approval\n", encoding="utf-8")
        clean_drift = self.cli(
            "baseline",
            clean_task["task_id"],
            "--expected-revision",
            str(clean_task["revision"]),
            expected_code=2,
        )
        self.assertEqual(clean_drift["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED")

        dirty_repo, _ = self.make_repo("dirty-preflight-approval")
        (dirty_repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        git(dirty_repo, "add", "staged.txt")
        (dirty_repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (dirty_repo / "untracked.txt").write_text("original\n", encoding="utf-8")
        dirty_task = self.start(dirty_repo, task_id="dirty-preflight-approval")["task"]
        self.mutate("preflight", dirty_task)
        dirty_task = dev_flow.load_state(dirty_task["task_id"], self.data)
        denied = self.cli(
            "approve",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            "--gate",
            "baseline-fetch",
            "--note",
            "implicit dirty approval is forbidden",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "DIRTY_APPROVAL_REQUIRED")
        invalid_scope = self.cli(
            "approve",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            "--gate",
            "route",
            "--note",
            "invalid dirty flag scope",
            "--allow-dirty",
            expected_code=2,
        )
        self.assertEqual(invalid_scope["error"]["code"], "INVALID_ARGUMENT")
        approval = self.mutate(
            "approve",
            dirty_task,
            "--gate",
            "baseline-fetch",
            "--note",
            "exact dirty snapshot approved",
            "--allow-dirty",
        )["approval"]
        self.assertTrue(approval["dirty_allowed"])
        dirty_task = dev_flow.load_state(dirty_task["task_id"], self.data)
        (dirty_repo / "untracked.txt").write_text("changed\n", encoding="utf-8")
        dirty_drift = self.cli(
            "baseline",
            dirty_task["task_id"],
            "--expected-revision",
            str(dirty_task["revision"]),
            expected_code=2,
        )
        self.assertEqual(dirty_drift["error"]["code"], "PREFLIGHT_WORKTREE_CHANGED")
        (dirty_repo / "untracked.txt").write_text("original\n", encoding="utf-8")
        accepted = self.mutate("baseline", dirty_task, "--materialize")
        self.assertEqual(accepted["status"], "BASELINED")

    def test_materialize_can_resume_after_baseline_and_is_idempotent(self) -> None:
        repo, _ = self.make_repo("materialize-later")
        task = self.start(repo, task_id="materialize-later")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        fetch_denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--fetch",
            expected_code=2,
        )
        self.assertEqual(fetch_denied["error"]["code"], "FETCH_NOT_APPROVED")
        invalid_fetch_flag = self.cli(
            "approve",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--gate",
            "route",
            "--note",
            "invalid flag scope",
            "--allow-fetch",
            expected_code=2,
        )
        self.assertEqual(invalid_fetch_flag["error"]["code"], "INVALID_ARGUMENT")
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("baseline-fetch", task["approvals"])
        denied_after_preflight = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied_after_preflight["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "refreshed preflight approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_approval = task["approvals"]["baseline-fetch"]
        self.assertEqual(
            baseline_approval["preflight_remotes"][0]["remote"], "origin"
        )
        original_remote_url = git(repo, "remote", "get-url", "origin")
        replacement_remote = self.root / "replacement.git"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(repo), str(replacement_remote)],
            check=True,
        )
        git(repo, "remote", "set-url", "origin", str(replacement_remote))
        changed_remote = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(changed_remote["error"]["code"], "REMOTE_URL_CHANGED")
        git(repo, "remote", "set-url", "origin", original_remote_url)
        self.mutate("baseline", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertIsNone(task["repositories"][0]["analysis_workspace"])
        response = self.mutate("baseline", task, "--materialize")
        workspace = response["repositories"][0]["analysis_workspace"]
        self.assertTrue(workspace["created"])
        task = dev_flow.load_state(task["task_id"], self.data)
        repeated = self.mutate("baseline", task, "--materialize")
        self.assertFalse(repeated["repositories"][0]["analysis_workspace"]["created"])
        self.assertGreater(repeated["revision"], task["revision"])

        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_path = Path(task["repositories"][0]["analysis_workspace"]["path"])
        (workspace_path / "unexpected.txt").write_text("dirty\n", encoding="utf-8")
        dirty = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(dirty["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION")
        self.assertTrue(dirty["error"]["details"]["dirty"])
        (workspace_path / "unexpected.txt").unlink()

        git(workspace_path, "switch", "-q", "-c", "analysis-hijack")
        wrong_branch = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(
            wrong_branch["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION"
        )
        self.assertEqual(
            wrong_branch["error"]["details"]["actual_branch"], "analysis-hijack"
        )
        base_sha = task["repositories"][0]["baseline"]["base_sha"]
        git(workspace_path, "switch", "-q", "--detach", base_sha)

        shutil.rmtree(workspace_path)
        rebuilt = self.mutate("baseline", task, "--materialize")
        self.assertTrue(rebuilt["repositories"][0]["analysis_workspace"]["created"])
        self.assertEqual(git(workspace_path, "rev-parse", "HEAD"), base_sha)

        task = dev_flow.load_state(task["task_id"], self.data)
        git(repo, "worktree", "remove", "--force", str(workspace_path))
        foreign, _ = self.make_repo("analysis-foreign")
        foreign.rename(workspace_path)
        foreign_collision = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--materialize",
            expected_code=2,
        )
        self.assertEqual(
            foreign_collision["error"]["code"], "ANALYSIS_WORKSPACE_COLLISION"
        )
        self.assertFalse(foreign_collision["error"]["details"]["same_common_dir"])

    def test_record_index_rejects_replaced_analysis_clone(self) -> None:
        repo, _ = self.make_repo("analysis-replacement")
        task = self.start(repo, task_id="analysis-replacement")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "analysis materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        analysis = Path(task["repositories"][0]["analysis_workspace"]["path"])
        base_sha = task["repositories"][0]["baseline"]["base_sha"]
        git(repo, "worktree", "remove", "--force", str(analysis))
        subprocess.run(
            ["git", "clone", "-q", "--no-local", str(repo), str(analysis)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(analysis, "switch", "-q", "--detach", base_sha)
        denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--index-id",
            "replacement-index",
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "ANALYSIS_WORKSPACE_CHANGED"
        )

    def test_configured_remote_never_falls_back_to_local_base(self) -> None:
        repo = self.root / "missing-remote-ref"
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
        (repo / "file.txt").write_text("local main\n", encoding="utf-8")
        git(repo, "add", "file.txt")
        git(repo, "commit", "-q", "-m", "local main")
        empty_remote = self.root / "empty.git"
        subprocess.run(
            ["git", "init", "-q", "--bare", str(empty_remote)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repo, "remote", "add", "origin", str(empty_remote))

        task = self.start(repo, task_id="missing-remote-ref")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["repositories"][0]["preflight"]["remote"], "origin")
        self.assertEqual(task["repositories"][0]["preflight"]["base_branch"], "main")
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "baseline resolution approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "BASE_REF_NOT_FOUND")
        self.assertEqual(
            denied["error"]["details"]["required_ref"], "refs/remotes/origin/main"
        )
        self.assertEqual(dev_flow.load_state(task["task_id"], self.data)["status"], "PREFLIGHTED")

    def test_baseline_fetch_uses_only_the_approved_base_refspec(self) -> None:
        repo, _ = self.make_repo("explicit-fetch")
        old_remote_sha = git(repo, "rev-parse", "refs/remotes/origin/main")
        (repo / "tracked.txt").write_text("remote base advanced\n", encoding="utf-8")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-q", "-m", "advance remote base")
        new_remote_sha = git(repo, "rev-parse", "HEAD")
        git(repo, "push", "-q", "origin", "main")
        git(repo, "update-ref", "refs/remotes/origin/main", old_remote_sha)
        git(repo, "config", "--unset-all", "remote.origin.fetch")
        git(
            repo,
            "config",
            "--add",
            "remote.origin.fetch",
            "+refs/heads/other:refs/remotes/origin/other",
        )
        git(
            repo,
            "config",
            "remote.origin.uploadpack",
            "repository-controlled-upload-pack-must-not-run",
        )

        task = self.start(repo, task_id="explicit-fetch")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            task["repositories"][0]["preflight"]["fetch_refspec"],
            "+refs/heads/main:refs/remotes/origin/main",
        )
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "explicit main refspec fetch approved",
            "--allow-fetch",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        response = self.mutate("baseline", task, "--fetch")
        baseline = response["repositories"][0]["baseline"]
        self.assertEqual(baseline["base_sha"], new_remote_sha)
        self.assertEqual(
            baseline["fetch_refspec"],
            "+refs/heads/main:refs/remotes/origin/main",
        )
        self.assertEqual(
            git(repo, "rev-parse", "refs/remotes/origin/main"), new_remote_sha
        )

    def test_baseline_without_fetch_rejects_approved_ref_drift(self) -> None:
        repo, _ = self.make_repo("base-ref-drift")
        task = self.start(repo, task_id="base-ref-drift")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        approved_candidate = task["repositories"][0]["preflight"][
            "base_candidate_sha"
        ]
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "exact no-fetch base candidate approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        tree = git(repo, "rev-parse", "HEAD^{tree}")
        changed_candidate = git(repo, "commit-tree", tree, "-m", "ref-only drift")
        self.assertNotEqual(changed_candidate, approved_candidate)
        git(repo, "update-ref", "refs/remotes/origin/main", changed_candidate)
        denied = self.cli(
            "baseline",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "BASE_REF_CHANGED")

    def test_option_like_remote_name_is_rejected_before_fetch(self) -> None:
        repo, remote = self.make_repo("option-remote")
        git(repo, "config", "branch.main.remote", "--all")
        git(repo, "config", "remote.--all.url", str(remote))
        task = self.start(repo, task_id="option-remote")["task"]
        denied = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--preview",
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "INVALID_REMOTE")



if __name__ == "__main__":
    unittest.main()
