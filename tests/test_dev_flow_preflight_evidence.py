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


class DevFlowPreflightEvidenceTest(test_case.DevFlowTestCase):
    def test_preflight_preview_binds_status_decision_and_refreshes_evidence(
        self,
    ) -> None:
        repo, _ = self.make_repo("preflight-preview")
        task = self.start(repo, task_id="preflight-preview")["task"]

        missing = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            expected_code=2,
        )
        self.assertEqual(
            missing["error"]["code"], "PREFLIGHT_PREVIEW_REQUIRED"
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data)["revision"],
            task["revision"],
        )

        preview = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--preview",
        )
        self.assertEqual(preview["command"], "preflight-preview")
        self.assertTrue(preview["transition_preview"]["changes_status"])
        self.assertEqual(
            preview["transition_preview"]["from"],
            {"id": "INTAKE", "name": "需求接收"},
        )
        self.assertEqual(
            preview["transition_preview"]["target"],
            {"id": "PREFLIGHTED", "name": "预检完成"},
        )
        persisted = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(persisted["status"], "INTAKE")
        self.assertIsNone(persisted["repositories"][0]["preflight"])
        state_before_refresh = dev_flow.load_state(
            task["task_id"], self.data
        )
        events_path = (
            self.data / "tasks" / task["task_id"] / "events.jsonl"
        )
        events_before_refresh = events_path.read_bytes()

        (repo / "tracked.txt").write_text(
            "changed after preview\n", encoding="utf-8"
        )
        refresh_required = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--confirm-preview",
            preview["transition_preview"]["token"],
            expected_code=2,
        )
        self.assertEqual(
            refresh_required["error"]["code"],
            "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
        )
        refresh_details = refresh_required["error"]["details"]
        self.assertTrue(refresh_details["token_reusable"])
        self.assertEqual(
            refresh_details["required_flag"],
            "--accept-evidence-refresh",
        )
        self.assertNotEqual(
            refresh_details["preview_observation_sha256"],
            refresh_details["current_observation_sha256"],
        )
        self.assertIn(
            "tracked.txt",
            refresh_details["repositories"][0]["preflight"]["unstaged"],
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data),
            state_before_refresh,
        )
        self.assertEqual(events_path.read_bytes(), events_before_refresh)

        applied = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--confirm-preview",
            preview["transition_preview"]["token"],
            "--accept-evidence-refresh",
        )
        self.assertEqual(applied["status"], "PREFLIGHTED")
        self.assertTrue(applied["evidence_refreshed_since_preview"])
        self.assertEqual(
            applied["preview_observation_sha256"],
            preview["transition_preview"]["observation_sha256"],
        )
        self.assertNotEqual(
            applied["preview_observation_sha256"],
            applied["captured_observation_sha256"],
        )
        persisted = dev_flow.load_state(task["task_id"], self.data)
        preflight = persisted["repositories"][0]["preflight"]
        self.assertTrue(preflight["evidence_complete"])
        self.assertEqual(preflight["capture_phase"], "confirm")
        self.assertIn("tracked.txt", preflight["unstaged"])
        self.assertEqual(
            preflight["worktree_fingerprint_sha256"],
            dev_flow._fingerprint_repo(repo)["sha256"],
        )
        event = json.loads(
            events_path.read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertEqual(event["type"], "preflight_recorded")
        self.assertTrue(
            event["payload"]["evidence_refreshed_since_preview"]
        )
        self.assertTrue(event["payload"]["evidence_refresh_accepted"])
        self.assertEqual(
            event["payload"]["accepted_observation_sha256"],
            applied["captured_observation_sha256"],
        )
        self.assertTrue(applied["evidence_refresh_accepted"])
        self.assertTrue(
            applied["confirmed_preview"][
                "evidence_refresh_accepted"
            ]
        )
        self.assertEqual(
            event["payload"]["preview_observation_sha256"],
            applied["preview_observation_sha256"],
        )
        self.assertEqual(
            event["payload"]["captured_observation_sha256"],
            applied["captured_observation_sha256"],
        )

    def test_preflight_preview_skips_full_capture_and_confirm_scans_each_repo_once(
        self,
    ) -> None:
        first, _ = self.make_repo("preflight-scan-first")
        second, _ = self.make_repo("preflight-scan-second")
        task = self.start(
            first, second, task_id="preflight-scan-count"
        )["task"]

        with mock.patch.object(
            dev_flow,
            "_fingerprint_repo",
            wraps=dev_flow._fingerprint_repo,
        ) as fingerprint_repo:
            preview = self.cli(
                "preflight",
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                "--preview",
            )
            self.assertEqual(fingerprint_repo.call_count, 0)
            self.assertTrue(
                all(
                    not repository["preflight"]["evidence_complete"]
                    for repository in preview["repositories"]
                )
            )

            confirmed = self.cli(
                "preflight",
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                "--confirm-preview",
                preview["transition_preview"]["token"],
            )

        self.assertEqual(confirmed["status"], "PREFLIGHTED")
        self.assertFalse(confirmed["evidence_refreshed_since_preview"])
        self.assertFalse(confirmed["evidence_refresh_accepted"])
        self.assertEqual(
            confirmed["confirmed_preview"]["token"],
            preview["transition_preview"]["token"],
        )
        self.assertEqual(
            confirmed["confirmed_preview"][
                "captured_observation_sha256"
            ],
            confirmed["captured_observation_sha256"],
        )
        self.assertEqual(fingerprint_repo.call_count, 2)
        self.assertCountEqual(
            [
                call.args[0].resolve()
                for call in fingerprint_repo.call_args_list
            ],
            [first.resolve(), second.resolve()],
        )
        event = json.loads(
            (
                self.data
                / "tasks"
                / task["task_id"]
                / "events.jsonl"
            ).read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertFalse(
            event["payload"]["evidence_refresh_accepted"]
        )
        self.assertIsNone(
            event["payload"]["accepted_observation_sha256"]
        )

    def test_preflight_rejects_legacy_preview_token_contract_without_mutation(
        self,
    ) -> None:
        repo, _ = self.make_repo("preflight-legacy-token")
        task = self.start(
            repo, task_id="preflight-legacy-token"
        )["task"]
        preview = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--preview",
        )
        state_before = dev_flow.load_state(task["task_id"], self.data)
        events_path = (
            self.data / "tasks" / task["task_id"] / "events.jsonl"
        )
        events_before = events_path.read_bytes()

        rejected = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--confirm-preview",
            "0" * 64,
            expected_code=2,
        )

        self.assertEqual(
            rejected["error"]["code"], "PREFLIGHT_PREVIEW_STALE"
        )
        self.assertEqual(
            rejected["error"]["details"]["reason"],
            "token_contract_changed",
        )
        self.assertIsNone(
            rejected["error"]["details"]["approved_decision_sha256"]
        )
        self.assertEqual(
            rejected["error"]["details"]["current_decision_sha256"],
            preview["transition_preview"]["decision_sha256"],
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data),
            state_before,
        )
        self.assertEqual(events_path.read_bytes(), events_before)

    def test_partial_multi_repo_preflight_requires_full_selection(self) -> None:
        first, _ = self.make_repo("partial-preflight-first")
        second, _ = self.make_repo("partial-preflight-second")
        task = self.start(
            first, second, task_id="partial-preflight"
        )["task"]

        for selected in (first, second):
            preview = self.cli(
                "preflight",
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                "--repo",
                str(selected),
                "--preview",
            )
            self.assertFalse(preview["ready"])
            self.assertFalse(
                preview["transition_preview"]["changes_status"]
            )
            self.assertEqual(
                preview["transition_preview"]["target"]["id"], "INTAKE"
            )
            applied = self.cli(
                "preflight",
                task["task_id"],
                "--expected-revision",
                str(task["revision"]),
                "--repo",
                str(selected),
                "--confirm-preview",
                preview["transition_preview"]["token"],
            )
            self.assertEqual(applied["status"], "INTAKE")
            task = dev_flow.load_state(task["task_id"], self.data)
            self.assertEqual(task["status"], "INTAKE")

        self.assertTrue(
            all(
                repository["preflight"] is not None
                for repository in task["repositories"]
            )
        )
        bypass = self.mutate(
            "transition",
            task,
            "--to",
            "PREFLIGHTED",
            expected_code=2,
        )
        self.assertEqual(
            bypass["error"]["code"],
            "PREFLIGHT_CONFIRMATION_REQUIRED",
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data)["status"],
            "INTAKE",
        )
        full_preview = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--preview",
        )
        self.assertTrue(full_preview["ready"])
        self.assertTrue(
            full_preview["transition_preview"]["changes_status"]
        )
        self.assertEqual(
            full_preview["transition_preview"]["target"]["id"],
            "PREFLIGHTED",
        )

        (first / "build.log").write_text(
            "generated after full preview\n", encoding="utf-8"
        )
        state_before_refresh = dev_flow.load_state(
            task["task_id"], self.data
        )
        events_path = (
            self.data / "tasks" / task["task_id"] / "events.jsonl"
        )
        events_before_refresh = events_path.read_bytes()
        refresh_required = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--confirm-preview",
            full_preview["transition_preview"]["token"],
            expected_code=2,
        )
        self.assertEqual(
            refresh_required["error"]["code"],
            "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
        )
        self.assertTrue(
            refresh_required["error"]["details"]["token_reusable"]
        )
        first_refresh = next(
            repository
            for repository in refresh_required["error"]["details"][
                "repositories"
            ]
            if repository["id"] == task["repositories"][0]["id"]
        )
        self.assertIn(
            "build.log",
            first_refresh["preflight"]["untracked"],
        )
        self.assertEqual(
            dev_flow.load_state(task["task_id"], self.data),
            state_before_refresh,
        )
        self.assertEqual(events_path.read_bytes(), events_before_refresh)

        applied = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--confirm-preview",
            full_preview["transition_preview"]["token"],
            "--accept-evidence-refresh",
        )
        self.assertEqual(applied["status"], "PREFLIGHTED")
        self.assertTrue(applied["evidence_refreshed_since_preview"])
        persisted = dev_flow.load_state(task["task_id"], self.data)
        first_preflight = next(
            repository["preflight"]
            for repository in persisted["repositories"]
            if repository["id"] == task["repositories"][0]["id"]
        )
        self.assertIn("build.log", first_preflight["untracked"])
        refresh_event = json.loads(
            events_path.read_text(encoding="utf-8").splitlines()[-1]
        )
        self.assertTrue(
            refresh_event["payload"][
                "evidence_refreshed_since_preview"
            ]
        )
        self.assertTrue(
            refresh_event["payload"]["evidence_refresh_accepted"]
        )
        partial_refresh = self.cli(
            "preflight",
            task["task_id"],
            "--expected-revision",
            str(applied["revision"]),
            "--repo",
            str(first),
            "--preview",
            expected_code=2,
        )
        self.assertEqual(
            partial_refresh["error"]["code"],
            "PREFLIGHT_FULL_SELECTION_REQUIRED",
        )

    def test_preflight_records_dirty_state_and_blocks_git_operation(self) -> None:
        repo, _ = self.make_repo("dirty")
        task = self.start(repo)["task"]
        (repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
        git(repo, "add", "staged.txt")
        (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        response = self.mutate("preflight", task)
        task = dev_flow.load_state(task["task_id"], self.data)
        preflight = task["repositories"][0]["preflight"]
        self.assertTrue(response["ready"])
        self.assertEqual(task["status"], "PREFLIGHTED")
        self.assertIn("staged.txt", preflight["staged"])
        self.assertIn("tracked.txt", preflight["unstaged"])
        self.assertIn("untracked.txt", preflight["untracked"])

        # A real sequencer directory is sufficient for Git to report an in-progress operation.
        git_dir = Path(git(repo, "rev-parse", "--absolute-git-dir"))
        (git_dir / "sequencer").mkdir()
        (git_dir / "sequencer" / "todo").write_text("pick deadbeef test\n")
        response = self.mutate("preflight", task)
        self.assertFalse(response["ready"])
        blocked = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn(
            "operation_in_progress:sequencer",
            blocked["repositories"][0]["preflight"]["blockers"],
        )

    def test_git_environment_redirects_cannot_change_repository_or_baseline(self) -> None:
        target, _ = self.make_repo("redirect-target")
        decoy, _ = self.make_repo("redirect-decoy")
        target_head = git(target, "rev-parse", "HEAD")
        decoy_head = git(decoy, "rev-parse", "HEAD")
        redirected_config = self.root / "redirected-git-config"
        redirected_config.write_text(
            '[branch "main"]\n\tremote = decoy\n', encoding="utf-8"
        )
        malicious_environment = {
            "GIT_DIR": str(decoy / ".git"),
            "GIT_WORK_TREE": str(decoy),
            "GIT_INDEX_FILE": str(decoy / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(decoy / ".git" / "objects"),
            "GIT_NAMESPACE": "redirected",
            "GIT_CONFIG": str(redirected_config),
            "GIT_GRAFT_FILE": str(self.root / "malicious-grafts"),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.bare",
            "GIT_CONFIG_VALUE_0": "false",
        }
        with mock.patch.dict(os.environ, malicious_environment):
            task = self.start(target, task_id="redirect-safe")["task"]
            self.assertEqual(
                Path(task["repositories"][0]["path"]).resolve(), target.resolve()
            )
            self.mutate("preflight", task)
            task = dev_flow.load_state(task["task_id"], self.data)
            preflight = task["repositories"][0]["preflight"]
            self.assertEqual(preflight["head_sha"], target_head)
            self.assertNotEqual(preflight["head_sha"], decoy_head)
            self.assertEqual(preflight["remote"], "origin")
            self.mutate(
                "approve",
                task,
                "--gate",
                "baseline-fetch",
                "--note",
                "the exact target repository is approved",
            )
            task = dev_flow.load_state(task["task_id"], self.data)
            self.mutate("baseline", task, "--materialize")

        state = dev_flow.load_state("redirect-safe", self.data)
        baseline = state["repositories"][0]["baseline"]
        analysis = state["repositories"][0]["analysis_workspace"]
        self.assertEqual(baseline["base_sha"], target_head)
        self.assertEqual(git(Path(analysis["path"]), "rev-parse", "HEAD"), target_head)
        self.assertEqual(git(decoy, "rev-parse", "HEAD"), decoy_head)

    def test_repository_grafts_cannot_forge_ancestry(self) -> None:
        repo, _ = self.make_repo("graft-ancestry")
        first = git(repo, "rev-parse", "HEAD")
        git(repo, "switch", "-q", "--orphan", "unrelated")
        (repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        git(repo, "add", "unrelated.txt")
        git(repo, "commit", "-q", "-m", "unrelated root")
        second = git(repo, "rev-parse", "HEAD")
        common_dir = Path(git(repo, "rev-parse", "--git-common-dir"))
        if not common_dir.is_absolute():
            common_dir = (repo / common_dir).resolve()
        info = common_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "grafts").write_text(f"{second} {first}\n", encoding="utf-8")
        result = dev_flow._run(
            [
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                first,
                second,
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)

    def test_git_evidence_ignores_external_diff_textconv_and_submodule_hiding(self) -> None:
        parent, _ = self.make_repo("evidence-parent")
        child, _ = self.make_repo("evidence-child")
        git(
            parent,
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(child),
            "vendor/child",
        )
        (parent / ".gitattributes").write_text(
            "tracked.txt diff=evil\n", encoding="utf-8"
        )
        git(parent, "add", ".gitattributes", ".gitmodules", "vendor/child")
        git(parent, "commit", "-q", "-m", "add adversarial diff fixtures")
        base_sha = git(parent, "rev-parse", "HEAD")

        inert_python_command = (
            f'"{sys.executable}" "{SUPPORT}" emit'
        )
        git(parent, "config", "diff.external", inert_python_command)
        git(parent, "config", "diff.ignoreSubmodules", "all")
        git(parent, "config", "diff.evil.command", inert_python_command)
        git(parent, "config", "diff.evil.textconv", inert_python_command)
        adversarial_environment = {
            "GIT_EXTERNAL_DIFF": inert_python_command,
            "GIT_DIFF_OPTS": "--unified=0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "diff.ignoreSubmodules",
            "GIT_CONFIG_VALUE_0": "all",
        }
        with mock.patch.dict(os.environ, adversarial_environment):
            clean = dev_flow._fingerprint_repo(parent)

        (parent / "tracked.txt").write_text("cached evidence\n", encoding="utf-8")
        git(parent, "add", "tracked.txt")
        (parent / "tracked.txt").write_text("unstaged evidence\n", encoding="utf-8")
        submodule = parent / "vendor" / "child"
        git(submodule, "config", "user.name", "Dev Flow Test")
        git(submodule, "config", "user.email", "dev-flow@example.invalid")
        (submodule / "tracked.txt").write_text(
            "committed submodule pointer change\n", encoding="utf-8"
        )
        git(submodule, "add", "tracked.txt")
        git(submodule, "commit", "-q", "-m", "move clean submodule head")
        repo_record = {
            "id": "evidence-parent",
            "path": str(parent),
            "protected_branches": ["main", "master", "trunk"],
            "baseline": {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "base_branch": "main",
                "base_sha": base_sha,
            },
            "workspace": None,
        }
        with mock.patch.dict(os.environ, adversarial_environment):
            dirty = dev_flow._fingerprint_repo(parent)
            preflight = dev_flow._preflight_repo(repo_record, None, None)
            review = dev_flow._write_review_repo(
                self.root / "adversarial-review", repo_record
            )

        self.assertNotEqual(clean["sha256"], dirty["sha256"])
        self.assertNotEqual(clean["cached_sha256"], dirty["cached_sha256"])
        self.assertNotEqual(clean["unstaged_sha256"], dirty["unstaged_sha256"])
        self.assertIn("tracked.txt", preflight["staged"])
        self.assertIn("tracked.txt", preflight["unstaged"])
        self.assertIn("vendor/child", preflight["unstaged"])
        sections = review["sections"]
        self.assertIn("tracked.txt", "\n".join(sections["cached"]["files"]))
        self.assertIn("tracked.txt", "\n".join(sections["unstaged"]["files"]))
        self.assertIn("vendor/child", "\n".join(sections["unstaged"]["files"]))
        self.assertIn(
            b"cached evidence",
            Path(sections["cached"]["path"]).read_bytes(),
        )
        self.assertIn(
            b"unstaged evidence",
            Path(sections["unstaged"]["path"]).read_bytes(),
        )

        for inner_content in ("dirty version a\n", "dirty version b\n"):
            with self.subTest(inner_content=inner_content.strip()):
                (submodule / "tracked.txt").write_text(
                    inner_content, encoding="utf-8"
                )
                with mock.patch.dict(os.environ, adversarial_environment):
                    with self.assertRaises(dev_flow.FlowError) as captured:
                        dev_flow._fingerprint_repo(parent)
                self.assertEqual(
                    captured.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED"
                )
                self.assertEqual(
                    captured.exception.details["submodules"][0]["path"],
                    "vendor/child",
                )
        (submodule / "tracked.txt").write_text(
            "committed submodule pointer change\n", encoding="utf-8"
        )
        (submodule / "inner-untracked.txt").write_text(
            "untracked submodule content\n", encoding="utf-8"
        )
        with mock.patch.dict(os.environ, adversarial_environment):
            with self.assertRaises(dev_flow.FlowError) as untracked_error:
                dev_flow._fingerprint_repo(parent)
        self.assertEqual(
            untracked_error.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED"
        )
        self.assertIn(
            "U",
            untracked_error.exception.details["submodules"][0][
                "submodule_status"
            ],
        )
        with mock.patch.dict(os.environ, adversarial_environment):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._write_review_repo(
                    self.root / "dirty-submodule-review", repo_record
                )
        self.assertEqual(captured.exception.code, "DIRTY_SUBMODULE_UNSUPPORTED")
        (submodule / "inner-untracked.txt").unlink()
        git(submodule, "update-index", "--assume-unchanged", "tracked.txt")
        for hidden_content in ("hidden submodule a\n", "hidden submodule b\n"):
            with self.subTest(hidden_content=hidden_content.strip()):
                (submodule / "tracked.txt").write_text(
                    hidden_content, encoding="utf-8"
                )
                with mock.patch.dict(os.environ, adversarial_environment):
                    with self.assertRaises(dev_flow.FlowError) as hidden_error:
                        dev_flow._fingerprint_repo(parent)
                self.assertEqual(hidden_error.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertEqual(
                    hidden_error.exception.details["entries"][0]["path"],
                    "vendor/child/tracked.txt",
                )
        git(submodule, "update-index", "--no-assume-unchanged", "tracked.txt")

    def test_content_filters_are_rejected_before_git_can_hide_bytes(self) -> None:
        repo, _ = self.make_repo("content-filter")
        (repo / ".gitattributes").write_text(
            "tracked.txt filter=hide\n", encoding="utf-8"
        )
        git(repo, "add", ".gitattributes")
        git(repo, "commit", "-q", "-m", "configure filtered path")
        git(repo, "config", "filter.hide.clean", "git show HEAD:tracked.txt")
        git(
            repo,
            "config",
            "filter.hide.smudge",
            "forbidden-filter-command",
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._fingerprint_repo(repo)
        self.assertEqual(captured.exception.code, "CONTENT_FILTER_UNSUPPORTED")
        self.assertEqual(
            captured.exception.details["entries"][0],
            {"path": "tracked.txt", "filter": "hide"},
        )

        global_repo, _ = self.make_repo("global-content-filter")
        global_home = self.root / "filter-home"
        global_home.mkdir()
        attributes = global_home / "global-attributes"
        attributes.write_text("tracked.txt filter=hide\n", encoding="utf-8")
        # Git config treats backslashes as escapes, so a raw Windows path breaks
        # parsing; forward slashes are accepted for paths on every platform.
        (global_home / ".gitconfig").write_text(
            "[core]\n"
            f"\tattributesFile = {attributes.as_posix()}\n"
            "[filter \"hide\"]\n"
            "\tclean = git show HEAD:tracked.txt\n"
            "\tsmudge = forbidden-filter-command\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"HOME": str(global_home)}):
            with self.assertRaises(dev_flow.FlowError) as global_error:
                dev_flow._fingerprint_repo(global_repo)
        self.assertEqual(
            global_error.exception.code, "CONTENT_FILTER_UNSUPPORTED"
        )

    def test_hidden_index_flags_are_rejected_before_fingerprinting(self) -> None:
        repo, _ = self.make_repo("hidden-index")
        original = (repo / "tracked.txt").read_text(encoding="utf-8")
        dev_flow._fingerprint_repo(repo)

        git(repo, "update-index", "--assume-unchanged", "tracked.txt")
        for content in ("assumed version a\n", "assumed version b\n"):
            with self.subTest(flag="assume-unchanged", content=content.strip()):
                (repo / "tracked.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._fingerprint_repo(repo)
                self.assertEqual(captured.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertEqual(
                    captured.exception.details["entries"][0]["flags"],
                    "assume-unchanged",
                )
                with self.assertRaises(dev_flow.FlowError) as status_error:
                    dev_flow._status_porcelain(repo)
                self.assertEqual(status_error.exception.code, "HIDDEN_INDEX_FLAGS")
        git(repo, "update-index", "--no-assume-unchanged", "tracked.txt")
        (repo / "tracked.txt").write_text(original, encoding="utf-8")

        git(repo, "update-index", "--skip-worktree", "tracked.txt")
        for content in ("skipped version a\n", "skipped version b\n"):
            with self.subTest(flag="skip-worktree", content=content.strip()):
                (repo / "tracked.txt").write_text(content, encoding="utf-8")
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._fingerprint_repo(repo)
                self.assertEqual(captured.exception.code, "HIDDEN_INDEX_FLAGS")
                self.assertIn(
                    "skip-worktree",
                    captured.exception.details["entries"][0]["flags"],
                )
        git(repo, "update-index", "--no-skip-worktree", "tracked.txt")

    def test_untracked_paths_are_nul_safe_and_archived_losslessly(self) -> None:
        repo, _ = self.make_repo("untracked-path-bytes")
        unicode_name = "未跟踪-文件.txt"
        newline_name = "line\nbreak.txt"
        (repo / unicode_name).write_bytes(b"unicode\n")
        expected_names = {os.fsencode(unicode_name)}
        try:
            (repo / newline_name).write_bytes(b"newline\n")
        except OSError:
            newline_name = ""
        else:
            expected_names.add(os.fsencode(newline_name))

        undecodable_name: bytes | None = (
            b"raw-\xff.bin" if os.name == "posix" else None
        )
        if undecodable_name is not None:
            try:
                descriptor = os.open(
                    os.path.join(os.fsencode(repo), undecodable_name),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except OSError:
                # Some sandboxed/macOS volumes reject non-UTF-8 entries.
                undecodable_name = None
            else:
                try:
                    os.write(descriptor, b"raw bytes\n")
                finally:
                    os.close(descriptor)
                expected_names.add(undecodable_name)
        fingerprint = dev_flow._fingerprint_repo(repo)
        items = fingerprint["untracked"]
        self.assertEqual(
            [item["path_bytes_hex"] for item in items],
            [name.hex() for name in sorted(expected_names)],
        )
        by_hex = {item["path_bytes_hex"]: item for item in items}
        self.assertEqual(by_hex[os.fsencode(unicode_name).hex()]["path"], unicode_name)
        if newline_name:
            self.assertEqual(
                by_hex[os.fsencode(newline_name).hex()]["path"],
                newline_name,
            )
        if undecodable_name is not None:
            self.assertIn("\ufffd", by_hex[undecodable_name.hex()]["path"])

        review = dev_flow._write_review_repo(
            self.root / "untracked-path-review",
            {
                "id": "untracked-path-bytes",
                "path": str(repo),
                "baseline": {
                    "evidence_contract_version": (
                        dev_flow.EVIDENCE_CONTRACT_VERSION
                    ),
                    "base_sha": git(repo, "rev-parse", "HEAD"),
                },
                "workspace": None,
            },
        )
        untracked = review["sections"]["untracked"]
        manifest = json.loads(
            Path(untracked["manifest_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            {bytes.fromhex(item["path_bytes_hex"]) for item in manifest},
            expected_names,
        )
        with tarfile.open(untracked["archive_path"], "r") as archive:
            archived_names = {os.fsencode(name) for name in archive.getnames()}
        self.assertEqual(archived_names, expected_names)

    def test_evidence_profiles_effective_git_and_preserves_raw_bytes(self) -> None:
        mode_repo, _ = self.make_repo("mode-evidence")
        git(mode_repo, "config", "core.fileMode", "false")
        clean_mode = dev_flow._fingerprint_repo(mode_repo)
        self.assertFalse(
            clean_mode["capability_profile"]["core_file_mode"]
        )
        tracked = mode_repo / "tracked.txt"
        if clean_mode["capability_profile"]["filesystem"]["file_mode"]:
            tracked.chmod(tracked.stat().st_mode | stat.S_IXUSR)
            executable_mode = dev_flow._fingerprint_repo(mode_repo)
            self.assertNotEqual(
                clean_mode["tracked_worktree_manifest_sha256"],
                executable_mode["tracked_worktree_manifest_sha256"],
            )
            mode_patch = dev_flow._git_diff(
                mode_repo, "--binary", "--full-index", "--", text=False
            )
            self.assertNotIn(b"old mode 100644", mode_patch)

        tracked.write_bytes(b"line one\r\nline two\r\n")
        crlf = dev_flow._fingerprint_repo(mode_repo)
        tracked.write_bytes(b"line one\nline two\n")
        lf = dev_flow._fingerprint_repo(mode_repo)
        self.assertNotEqual(
            crlf["tracked_worktree_manifest_sha256"],
            lf["tracked_worktree_manifest_sha256"],
        )
        self.assertEqual(
            next(
                item
                for item in lf["tracked_worktree"]
                if item["path"] == "tracked.txt"
            )["sha256"],
            dev_flow._sha256_file(tracked),
        )

        stat_repo, _ = self.make_repo("stat-evidence")
        git(stat_repo, "config", "core.trustctime", "false")
        git(stat_repo, "config", "core.checkStat", "minimal")
        stat_path = stat_repo / "tracked.txt"
        before = dev_flow._fingerprint_repo(stat_repo)
        original_stat = stat_path.stat()
        original_bytes = stat_path.read_bytes()
        replacement = b"x" * (len(original_bytes) - 1) + b"\n"
        self.assertEqual(len(replacement), len(original_bytes))
        stat_path.write_bytes(replacement)
        os.utime(
            stat_path,
            ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
        )
        after = dev_flow._fingerprint_repo(stat_repo)
        self.assertNotEqual(before["sha256"], after["sha256"])

        symlink_repo, _ = self.make_repo("symlink-evidence")
        symlink_profile = dev_flow._git_capability_profile(symlink_repo)
        if symlink_profile["filesystem"]["symlinks"]:
            link = symlink_repo / "tracked-link"
            link.symlink_to("tracked.txt")
            git(symlink_repo, "add", "tracked-link")
            git(symlink_repo, "commit", "-q", "-m", "add tracked symlink")
            git(symlink_repo, "config", "core.symlinks", "false")
            symlink_fingerprint = dev_flow._fingerprint_repo(
                symlink_repo
            )
            link.unlink()
            link.write_text("tracked.txt", encoding="utf-8")
            regular_fingerprint = dev_flow._fingerprint_repo(
                symlink_repo
            )
            self.assertNotEqual(
                symlink_fingerprint[
                    "tracked_worktree_manifest_sha256"
                ],
                regular_fingerprint[
                    "tracked_worktree_manifest_sha256"
                ],
            )

        ident_repo, _ = self.make_repo("ident-evidence")
        (ident_repo / "tracked.txt").write_text("$Id$\n", encoding="utf-8")
        (ident_repo / ".gitattributes").write_text(
            "tracked.txt ident\n", encoding="utf-8"
        )
        git(ident_repo, "add", "tracked.txt", ".gitattributes")
        git(ident_repo, "commit", "-q", "-m", "enable ident conversion")
        ident_before = dev_flow._fingerprint_repo(ident_repo)
        (ident_repo / "tracked.txt").write_text(
            "$Id: arbitrary-worktree-bytes $\n", encoding="utf-8"
        )
        self.assertEqual(dev_flow._git_diff(ident_repo, "--name-only", "--"), "")
        ident_after = dev_flow._fingerprint_repo(ident_repo)
        self.assertNotEqual(ident_before["sha256"], ident_after["sha256"])

    def test_capability_probe_is_clean_and_case_collisions_fail_closed(self) -> None:
        repo, _ = self.make_repo("capability-profile")
        before = git(repo, "status", "--porcelain=v1", "-uall")
        first = dev_flow._git_capability_profile(repo)
        second = dev_flow._git_capability_profile(repo)
        after = git(repo, "status", "--porcelain=v1", "-uall")
        self.assertEqual(before, after)
        self.assertFalse(
            list(repo.glob(".dev-flow-capability-*"))
        )
        self.assertEqual(
            first["evidence_contract_version"],
            dev_flow.EVIDENCE_CONTRACT_VERSION,
        )
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertIn(first["platform"], {"windows", "macos", "linux"})
        self.assertIn("core_autocrlf", first)
        self.assertIn("core_eol", first)
        self.assertIn("filesystem_identity", first)

        collision = repo / "Case.txt"
        collision.write_bytes(b"case\n")
        oid = b"0" * 40
        records = (
            b"100644 "
            + oid
            + b" 0\tCase.txt\0"
            + b"100644 "
            + oid
            + b" 0\tcase.txt\0"
        )
        case_insensitive_profile = {
            **first,
            "core_ignore_case": True,
            "filesystem": {
                **first["filesystem"],
                "case_sensitive": False,
            },
        }
        with mock.patch.object(
            dev_flow, "_git_evidence", return_value=records
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._tracked_worktree_manifest(
                    repo, case_insensitive_profile
                )
        self.assertEqual(
            captured.exception.code, "CASE_COLLISION_UNSUPPORTED"
        )

        composed_name = "\u00e9.txt"
        decomposed_name = "e\u0301.txt"
        (repo / composed_name).write_bytes(b"unicode\n")
        unicode_records = (
            b"100644 "
            + oid
            + b" 0\t"
            + composed_name.encode("utf-8")
            + b"\0"
            + b"100644 "
            + oid
            + b" 0\t"
            + decomposed_name.encode("utf-8")
            + b"\0"
        )
        normalization_aliasing_profile = {
            **first,
            "core_ignore_case": False,
            "filesystem": {
                **first["filesystem"],
                "case_sensitive": True,
                "unicode_normalization_distinct": False,
            },
        }
        with mock.patch.object(
            dev_flow, "_git_evidence", return_value=unicode_records
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._tracked_worktree_manifest(
                    repo, normalization_aliasing_profile
                )
        self.assertEqual(
            captured.exception.code,
            "CASE_COLLISION_UNSUPPORTED",
        )
        self.assertFalse(
            captured.exception.details["case_aliasing"]
        )
        self.assertTrue(
            captured.exception.details["unicode_aliasing"]
        )

    def test_evidence_contract_legacy_is_readable_but_not_reusable(self) -> None:
        repo, _ = self.make_repo("evidence-contract")
        task = self.start(repo, task_id="evidence-contract")["task"]
        self.mutate("preflight", task)
        state_path = (
            self.data / "tasks" / task["task_id"] / "state.json"
        )
        current = json.loads(state_path.read_text(encoding="utf-8"))
        legacy = json.loads(json.dumps(current))
        legacy.pop("evidence_contract_version", None)
        legacy["repositories"][0]["preflight"].pop(
            "evidence_contract_version", None
        )
        dev_flow._atomic_write_json(state_path, legacy)

        loaded = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(loaded["schema_version"], dev_flow.SCHEMA_VERSION)
        denied = self.mutate(
            "approve",
            loaded,
            "--gate",
            "baseline-fetch",
            "--note",
            "legacy evidence must not authorize a mutation",
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "EVIDENCE_REGENERATION_REQUIRED"
        )

        newer = json.loads(json.dumps(current))
        newer["repositories"][0]["preflight"][
            "evidence_contract_version"
        ] = dev_flow.EVIDENCE_CONTRACT_VERSION + 1
        dev_flow._atomic_write_json(state_path, newer)
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(
            captured.exception.code, "EVIDENCE_CONTRACT_UNSUPPORTED"
        )

    def test_controller_generated_artifact_kinds_cannot_be_recorded_manually(self) -> None:
        repo, _ = self.make_repo("reserved-artifact")
        task = self.start(repo, task_id="reserved-artifact")["task"]
        artifact = self.root / "forged-controller-artifact.json"
        artifact.write_text("{}\n", encoding="utf-8")
        for kind in ("workspace-plan", "review-snapshot"):
            with self.subTest(kind=kind):
                denied = self.cli(
                    "record-artifact",
                    task["task_id"],
                    "--expected-revision",
                    str(task["revision"]),
                    "--kind",
                    kind,
                    "--path",
                    str(artifact),
                    expected_code=2,
                )
                self.assertEqual(
                    denied["error"]["code"], "RESERVED_ARTIFACT_KIND"
                )



if __name__ == "__main__":
    unittest.main()
