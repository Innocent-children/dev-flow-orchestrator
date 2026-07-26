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


class DevFlowIndexesTest(test_case.DevFlowTestCase):
    def test_degraded_index_requires_current_approval_and_structured_provenance(self) -> None:
        first, _ = self.make_repo("degraded-first")
        second, _ = self.make_repo("degraded-second")
        task = self.start(first, second, task_id="degraded-index")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "local baseline materialization approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        repository_ids = [repo["id"] for repo in task["repositories"]]

        unapproved = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            expected_code=2,
        )
        self.assertEqual(unapproved["error"]["code"], "APPROVAL_REQUIRED")
        self.mutate(
            "approve",
            task,
            "--gate",
            "impact-degraded",
            "--note",
            "memory index unavailable; fallback review approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        approval_id = task["approvals"]["impact-degraded"]["approval_id"]

        failed_with_index = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            "--index-id",
            "unexpected-index",
            "--metadata-json",
            json.dumps({"status": "failed"}),
            expected_code=2,
        )
        self.assertEqual(failed_with_index["error"]["code"], "INVALID_INDEX_METADATA")
        missing_metadata = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            expected_code=2,
        )
        self.assertEqual(
            missing_metadata["error"]["code"], "DEGRADED_INDEX_METADATA_REQUIRED"
        )
        wrong_binding = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            repository_ids[0],
            "--metadata-json",
            json.dumps(
                {
                    "status": "failed",
                    "impact_degraded_approval_id": "old-approval",
                    "error": "service unavailable",
                    "fallback_coverage": {"method": "manual rg review"},
                }
            ),
            expected_code=2,
        )
        self.assertEqual(wrong_binding["error"]["code"], "STALE_APPROVAL")

        degraded_metadata = json.dumps(
            {
                "status": "failed",
                "impact_degraded_approval_id": approval_id,
                "error": "service unavailable",
                "fallback_coverage": {"method": "manual rg review"},
            }
        )
        self.mutate(
            "record-index",
            task,
            "--repo",
            repository_ids[0],
            "--metadata-json",
            degraded_metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "BASELINED")
        self.mutate(
            "record-index",
            task,
            "--repo",
            repository_ids[1],
            "--metadata-json",
            degraded_metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(task["status"], "INDEXED")
        for repo_record in task["repositories"]:
            index = repo_record["index"]
            self.assertIsNone(index["index_id"])
            self.assertTrue(index["index_record_id"])
            self.assertEqual(index["impact_degraded_approval_id"], approval_id)
            self.assertEqual(
                index["metadata"]["impact_degraded_approval_id"], approval_id
            )

        digest = dev_flow._index_provenance_sha256(task)
        changed = dev_flow._copy_state(task)
        changed["repositories"][1]["index"]["index_record_id"] = "changed-token"
        self.assertNotEqual(dev_flow._index_provenance_sha256(changed), digest)
        impact = self.root / "degraded-impact.md"
        impact.write_text("degraded fallback impact\n", encoding="utf-8")
        recorded = self.mutate(
            "record-artifact", task, "--kind", "impact", "--path", str(impact)
        )
        self.assertEqual(
            recorded["artifact"]["metadata"]["index_provenance_sha256"], digest
        )

    def test_baseline_index_replacements_are_audited_and_history_ids_are_isolated(self) -> None:
        first, _ = self.make_repo("baseline-history-first")
        second, _ = self.make_repo("baseline-history-second")
        task = self.start(
            first, second, task_id="baseline-index-history"
        )["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "history test baselines approved",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("baseline", task, "--materialize")
        task = dev_flow.load_state(task["task_id"], self.data)
        first_id = task["repositories"][0]["id"]
        second_id = task["repositories"][1]["id"]
        project_a = "baseline-history-project-a"
        project_b = "baseline-history-project-b"
        project_c = "baseline-history-project-c"

        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_a,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_a = dev_flow._copy_state(task["repositories"][0]["index"])
        self.mutate(
            "record-index",
            task,
            "--repo",
            second_id,
            "--index-id",
            project_c,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_b,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        baseline_b = dev_flow._copy_state(task["repositories"][0]["index"])
        history = task["repositories"][0]["index_history"]
        self.assertEqual(len(history), 1)
        first_history = history[0]
        for key, value in baseline_a.items():
            self.assertEqual(first_history[key], value)
        self.assertTrue(first_history["superseded_at"])
        self.assertEqual(first_history["replacement_role"], "baseline")
        self.assertEqual(first_history["replacement_project"], project_b)
        self.assertEqual(
            first_history["replacement_index_record_id"],
            baseline_b["index_record_id"],
        )
        self.assertEqual(
            first_history["replacement"]["index_record_id"],
            baseline_b["index_record_id"],
        )

        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        replacement_event = next(
            event
            for event in events
            if event["type"] == "index_recorded"
            and (event["payload"].get("index_records") or [{}])[0]
            .get("current", {})
            .get("index_record_id")
            == baseline_b["index_record_id"]
        )
        event_change = replacement_event["payload"]["index_records"][0]
        self.assertEqual(event_change["previous"], baseline_a)
        self.assertEqual(event_change["current"], baseline_b)
        self.assertEqual(event_change["history_entry"], first_history)

        other_repo_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            second_id,
            "--index-id",
            project_a,
            expected_code=2,
        )
        self.assertEqual(
            other_repo_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in other_repo_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

        # A baseline may return to one of its own historical project IDs.
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_a,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-index",
            task,
            "--repo",
            first_id,
            "--index-id",
            project_b,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            [item["index_id"] for item in task["repositories"][0]["index_history"]],
            [project_a, project_b, project_a],
        )

        task = self.route_indexed_task_to_workspace(task)
        cross_role_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            cross_role_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in cross_role_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

    def test_workspace_index_replacements_are_audited_and_generation_scoped(self) -> None:
        first, _ = self.make_repo("workspace-history-first")
        second, _ = self.make_repo("workspace-history-second")
        task = self.ready_workspace_task(
            first, second, task_id="workspace-index-history"
        )
        first_id = task["repositories"][0]["id"]
        second_id = task["repositories"][1]["id"]
        project_a = "workspace-history-project-a"
        project_b = "workspace-history-project-b"
        metadata = json.dumps({"persistence": False})

        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_a = dev_flow._copy_state(
            task["repositories"][0]["workspace_index"]
        )
        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_b,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_b = dev_flow._copy_state(
            task["repositories"][0]["workspace_index"]
        )
        history = task["repositories"][0]["index_history"]
        self.assertEqual(len(history), 1)
        first_history = history[0]
        for key, value in workspace_a.items():
            self.assertEqual(first_history[key], value)
        self.assertEqual(first_history["replacement_role"], "workspace")
        self.assertEqual(first_history["replacement_project"], project_b)
        self.assertEqual(
            first_history["replacement_record_id"],
            workspace_b["index_record_id"],
        )

        other_repo_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            second_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
            expected_code=2,
        )
        self.assertEqual(
            other_repo_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                for conflict in other_repo_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

        # Same repository, role and generation may return to its own A project.
        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_a_again = task["repositories"][0]["workspace_index"]
        self.assertEqual(workspace_a_again["index_id"], project_a)
        self.assertEqual(
            [item["index_id"] for item in task["repositories"][0]["index_history"]],
            [project_a, project_b],
        )
        events = [
            json.loads(line)
            for line in (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        return_to_a = next(
            event
            for event in reversed(events)
            if event["type"] == "index_recorded"
            and (event["payload"].get("index_records") or [{}])[0]
            .get("current", {})
            .get("index_record_id")
            == workspace_a_again["index_record_id"]
        )
        self.assertEqual(
            return_to_a["payload"]["index_records"][0]["previous"],
            workspace_b,
        )

        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "move to the next workspace generation",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        cross_role_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--repo",
            first_id,
            "--index-id",
            project_a,
            expected_code=2,
        )
        self.assertEqual(
            cross_role_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )

        task = self.route_indexed_task_to_workspace(task)
        old_generation_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            project_a,
            "--metadata-json",
            metadata,
            expected_code=2,
        )
        self.assertEqual(
            old_generation_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        self.assertTrue(
            any(
                conflict.get("origin") == "index-history"
                and conflict.get("workspace_generation") == 0
                for conflict in old_generation_denied["error"]["details"][
                    "conflicts"
                ]
            )
        )

    def test_dual_index_roles_paths_and_read_only_phase_selection(self) -> None:
        repo, _ = self.make_repo("dual-index-selection")
        task = self.ready_workspace_task(
            repo, task_id="dual-index-selection"
        )
        repository = task["repositories"][0]
        baseline = repository["index"]
        workspace = repository["workspace"]
        self.assertEqual(baseline["role"], "baseline")
        self.assertEqual(
            baseline["repo_path"], repository["analysis_workspace"]["path"]
        )
        self.assertNotEqual(baseline["repo_path"], workspace["path"])

        before = self.cli("show", task["task_id"])
        selection = before["index_selection"]
        self.assertFalse(selection["automatic"])
        self.assertEqual(selection["selected_role"], "workspace")
        selected = selection["repositories"][0]
        self.assertIsNone(selected["recorded_project"])
        self.assertEqual(
            selected["recommended_project"],
            "devflow-dual-index-selection-dual-index-selection-workspace-r0",
        )
        self.assertEqual(
            selected["baseline"]["recorded_project"], baseline["index_id"]
        )
        self.assertEqual(selected["baseline"]["role"], "baseline")
        self.assertEqual(selected["workspace"]["role"], "workspace")

        response = self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--index-id",
            "actual-workspace-project",
            "--metadata-json",
            json.dumps({"persistence": False, "mode": "incremental"}),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(response["role"], "workspace")
        self.assertEqual(workspace_index["role"], "workspace")
        self.assertEqual(workspace_index["repo_path"], workspace["path"])
        self.assertEqual(workspace_index["workspace_generation"], 0)
        self.assertEqual(
            workspace_index["workspace_plan_sha256"],
            task["workspace"]["plan"]["sha256"],
        )
        self.assertEqual(
            workspace_index["fingerprint_sha256"],
            dev_flow._fingerprint_repo(Path(workspace["path"]))["sha256"],
        )
        selected = response["index_selection"]["repositories"][0]
        self.assertEqual(selected["recorded_project"], "actual-workspace-project")
        self.assertNotEqual(
            selected["recorded_project"], selected["recommended_project"]
        )

        baseline_phase = dev_flow._copy_state(task)
        baseline_phase["status"] = "ROUTE_APPROVED"
        baseline_selection = dev_flow._result("probe", baseline_phase)[
            "index_selection"
        ]
        self.assertEqual(baseline_selection["selected_role"], "baseline")
        self.assertEqual(
            baseline_selection["repositories"][0]["recorded_project"],
            baseline["index_id"],
        )
        blocked_phase = dev_flow._copy_state(task)
        blocked_phase["status"] = "BLOCKED"
        blocked_phase["blocked"] = {"from_status": "ROUTE_APPROVED"}
        self.assertEqual(
            dev_flow._index_selection(blocked_phase)["selected_role"],
            "baseline",
        )
        done_phase = dev_flow._copy_state(task)
        done_phase["status"] = "DONE"
        self.assertEqual(
            dev_flow._index_selection(done_phase)["selected_role"],
            "workspace",
        )

    def test_workspace_index_gate_detects_changes_and_refresh_preserves_baseline_digest(self) -> None:
        repo, _ = self.make_repo("workspace-index-freshness")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-freshness"
        )
        missing = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(missing["error"]["code"], "WORKSPACE_INDEX_REQUIRED")

        baseline_digest = dev_flow._index_provenance_sha256(task)
        task = self.record_workspace_indexes(task)
        first_index = task["repositories"][0]["workspace_index"]
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )
        workspace = Path(task["repositories"][0]["workspace"]["path"])
        (workspace / "tracked.txt").write_text(
            "implementation changed\n", encoding="utf-8"
        )
        stale = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(stale["error"]["code"], "STALE_WORKSPACE_INDEX")
        self.assertEqual(
            stale["error"]["details"]["repositories"][0]["reason"],
            "workspace content changed after indexing",
        )

        task = self.record_workspace_indexes(task)
        refreshed = task["repositories"][0]["workspace_index"]
        self.assertEqual(refreshed["index_id"], first_index["index_id"])
        self.assertNotEqual(
            refreshed["index_record_id"], first_index["index_record_id"]
        )
        self.assertNotEqual(
            refreshed["fingerprint_sha256"],
            first_index["fingerprint_sha256"],
        )
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )

        git(workspace, "add", "tracked.txt")
        staged = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(staged["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)

        (workspace / "new-untracked.txt").write_text(
            "untracked implementation evidence\n", encoding="utf-8"
        )
        untracked = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(untracked["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)

        git(workspace, "add", "new-untracked.txt")
        git(workspace, "commit", "-q", "-m", "advance indexed workspace")
        committed = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(committed["error"]["code"], "STALE_WORKSPACE_INDEX")
        task = self.record_workspace_indexes(task)
        self.assertEqual(
            dev_flow._index_provenance_sha256(task), baseline_digest
        )
        transitioned = self.mutate("transition", task, "PLANNING")
        self.assertEqual(transitioned["status"], "PLANNING")

    def test_workspace_index_freshness_guards_execution_and_review_gates(self) -> None:
        repo, _ = self.make_repo("workspace-index-downstream-gates")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-downstream-gates"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        contract = self.root / "workspace-index-gate-contract.md"
        contract.write_text("approved gate contract\n", encoding="utf-8")
        plan = self.mutate(
            "record-artifact",
            task,
            "--kind",
            "direct-contract",
            "--path",
            str(contract),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "plan",
            "--note",
            "downstream gate contract approved",
            "--artifact-sha256",
            plan["artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        workspace = Path(task["repositories"][0]["workspace"]["path"])

        (workspace / "tracked.txt").write_text(
            "planning drift\n", encoding="utf-8"
        )
        implementing_denied = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "IMPLEMENTING",
            expected_code=2,
        )
        self.assertEqual(
            implementing_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "IMPLEMENTING")
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "tracked.txt").write_text(
            "implementation drift\n", encoding="utf-8"
        )
        verifying_denied = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "VERIFYING",
            expected_code=2,
        )
        self.assertEqual(
            verifying_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate("transition", task, "VERIFYING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "recorded-unit-test",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)

        (workspace / "tracked.txt").write_text(
            "review drift\n", encoding="utf-8"
        )
        review_denied = self.cli(
            "review-snapshot",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            review_denied["error"]["code"], "STALE_WORKSPACE_INDEX"
        )
        task = self.record_workspace_indexes(task)
        self.mutate(
            "record-test",
            task,
            "--name",
            "unit",
            "--command",
            "recorded-unit-test",
            "--exit-code",
            "0",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        snapshot = self.mutate("review-snapshot", task)
        self.assertEqual(snapshot["status"], "REVIEWING")

    def test_workspace_index_ids_are_isolated_and_multi_repo_gate_is_complete(self) -> None:
        first, _ = self.make_repo("workspace-index-first")
        second, _ = self.make_repo("workspace-index-second")
        task = self.ready_workspace_task(
            first, second, task_id="workspace-index-multi"
        )
        repositories = task["repositories"]
        first_id = repositories[0]["id"]
        second_id = repositories[1]["id"]
        first_project = dev_flow._recommended_index_name(
            task, repositories[0], "workspace"
        )

        missing_id = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            expected_code=2,
        )
        self.assertEqual(
            missing_id["error"]["code"], "WORKSPACE_INDEX_ID_REQUIRED"
        )
        missing_persistence = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            expected_code=2,
        )
        self.assertEqual(
            missing_persistence["error"]["code"],
            "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
        )
        persistent = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": True}),
            expected_code=2,
        )
        self.assertEqual(
            persistent["error"]["code"],
            "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
        )
        same_for_all = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--index-id",
            "one-project-for-two-repositories",
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            same_for_all["error"]["code"], "WORKSPACE_INDEX_ID_CONFLICT"
        )
        baseline_conflict = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            repositories[1]["index"]["index_id"],
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            baseline_conflict["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )

        self.mutate(
            "record-index",
            task,
            "--role",
            "workspace",
            "--repo",
            first_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        partial = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(partial["error"]["code"], "WORKSPACE_INDEX_REQUIRED")
        self.assertEqual(
            partial["error"]["details"]["repository_ids"], [second_id]
        )
        cross_repo_conflict = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--repo",
            second_id,
            "--index-id",
            first_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            cross_repo_conflict["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        task = self.record_workspace_indexes(task)
        transitioned = self.mutate("transition", task, "PLANNING")
        self.assertEqual(transitioned["status"], "PLANNING")

    def test_workspace_index_receipt_tampering_requires_refresh(self) -> None:
        repo, _ = self.make_repo("workspace-index-receipt")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-receipt"
        )
        receipt = self.root / "workspace-index-receipt.json"
        receipt.write_text('{"indexed": true}\n', encoding="utf-8")
        task = self.record_workspace_indexes(task, receipt=receipt)
        original = task["repositories"][0]["workspace_index"]["receipt"]
        receipt.write_text('{"indexed": false}\n', encoding="utf-8")
        stale = self.cli(
            "transition",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "PLANNING",
            expected_code=2,
        )
        self.assertEqual(stale["error"]["code"], "STALE_WORKSPACE_INDEX")
        self.assertIn(
            "receipt",
            stale["error"]["details"]["repositories"][0]["reason"],
        )
        task = self.record_workspace_indexes(task, receipt=receipt)
        refreshed = task["repositories"][0]["workspace_index"]["receipt"]
        self.assertNotEqual(refreshed["sha256"], original["sha256"])
        self.mutate("transition", task, "PLANNING")

    def test_reassessment_archives_workspace_index_and_requires_new_generation_project(self) -> None:
        repo, _ = self.make_repo("workspace-index-reassessment")
        task = self.ready_workspace_task(
            repo, task_id="workspace-index-reassessment"
        )
        task = self.record_workspace_indexes(task)
        old_index = task["repositories"][0]["workspace_index"]
        old_project = old_index["index_id"]
        self.mutate("transition", task, "PLANNING")
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "transition",
            task,
            "INDEXED",
            "--note",
            "impact must be reassessed",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        repository = task["repositories"][0]
        self.assertIsNone(repository["workspace_index"])
        self.assertEqual(
            repository["workspace_history"][-1]["workspace_index"][
                "index_record_id"
            ],
            old_index["index_record_id"],
        )
        self.assertEqual(task["workspace"]["generation"], 1)
        self.assertEqual(
            dev_flow._index_selection(task)["selected_role"], "baseline"
        )
        baseline_reuse_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--index-id",
            old_project,
            expected_code=2,
        )
        self.assertEqual(
            baseline_reuse_denied["error"]["code"], "INDEX_ID_CONFLICT"
        )

        impact = self.root / "workspace-index-reassessed-impact.md"
        impact.write_text("reassessed impact\n", encoding="utf-8")
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
            "reassessed bounded change",
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate(
            "approve",
            task,
            "--gate",
            "route",
            "--note",
            "reassessed route approved",
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
            "new generation workspace approved",
            "--artifact-sha256",
            plan["plan_artifact"]["sha256"],
        )
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("prepare-workspace", task, "--execute")
        task = dev_flow.load_state(task["task_id"], self.data)
        old_project_denied = self.cli(
            "record-index",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--role",
            "workspace",
            "--index-id",
            old_project,
            "--metadata-json",
            json.dumps({"persistence": False}),
            expected_code=2,
        )
        self.assertEqual(
            old_project_denied["error"]["code"],
            "WORKSPACE_INDEX_ID_CONFLICT",
        )
        task = self.record_workspace_indexes(task)
        new_index = task["repositories"][0]["workspace_index"]
        self.assertNotEqual(new_index["index_id"], old_project)
        self.assertTrue(new_index["index_id"].endswith("-workspace-r1"))

    def test_schema_v1_state_without_additive_index_fields_remains_compatible(self) -> None:
        repo, _ = self.make_repo("legacy-workspace-index")
        task = self.start(repo, task_id="legacy-workspace-index")["task"]
        state_path = (
            self.data / "tasks" / task["task_id"] / "state.json"
        )
        legacy = json.loads(state_path.read_text(encoding="utf-8"))
        legacy["repositories"][0].pop("workspace_index", None)
        legacy["repositories"][0].pop("index_history", None)
        dev_flow._atomic_write_json(state_path, legacy)

        loaded = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(loaded["schema_version"], 1)
        self.assertIsNone(loaded["repositories"][0]["workspace_index"])
        self.assertEqual(loaded["repositories"][0]["index_history"], [])
        shown = self.cli("show", task["task_id"])
        self.assertIsNone(shown["task"]["repositories"][0]["workspace_index"])
        self.assertEqual(shown["task"]["repositories"][0]["index_history"], [])
        self.assertIsNone(shown["index_selection"]["selected_role"])
        self.mutate("preflight", loaded)
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("workspace_index", persisted["repositories"][0])
        self.assertEqual(persisted["repositories"][0]["index_history"], [])
        self.assertEqual(persisted["schema_version"], 1)

    def test_approval_events_preserve_overwritten_and_cleared_history(self) -> None:
        repo, _ = self.make_repo("approval-audit")
        task = self.start(repo, task_id="approval-audit")["task"]
        self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        first = self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "first approval",
        )["approval"]
        task = dev_flow.load_state(task["task_id"], self.data)
        second = self.mutate(
            "approve",
            task,
            "--gate",
            "baseline-fetch",
            "--note",
            "replacement approval",
            "--allow-fetch",
        )["approval"]
        task = dev_flow.load_state(task["task_id"], self.data)
        self.mutate("preflight", task)
        cleared = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("baseline-fetch", cleared["approvals"])
        events_path = self.data / "tasks" / task["task_id"] / "events.jsonl"
        approval_events = [
            event
            for event in map(json.loads, events_path.read_text(encoding="utf-8").splitlines())
            if event["type"] == "gate_approved"
        ]
        self.assertEqual(len(approval_events), 2)
        self.assertEqual(
            [event["payload"]["approval"]["approval_id"] for event in approval_events],
            [first["approval_id"], second["approval_id"]],
        )
        self.assertEqual(
            [event["payload"]["approval"]["note"] for event in approval_events],
            ["first approval", "replacement approval"],
        )
        self.assertFalse(approval_events[0]["payload"]["approval"]["fetch_allowed"])
        self.assertTrue(approval_events[1]["payload"]["approval"]["fetch_allowed"])



if __name__ == "__main__":
    unittest.main()
