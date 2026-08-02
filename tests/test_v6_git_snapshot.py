"""Focused V6 content-sensitive Git workspace snapshot tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from unittest import mock
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.git_client import GitClient, validate_snapshot
from dev_flow_orchestrator.model import DevFlowError
from support import RepositoryTestCase, make_repository


def resource(path: str, role: str = "governing", normalizer: str = "none") -> dict:
    return {"path": path, "role": role, "normalizer": normalizer}


class GitSnapshotTests(RepositoryTestCase):
    def _entry(self, snapshot: dict, path: str) -> dict:
        return next(item for item in snapshot["entries"] if item["path"] == path)

    def _resource(self, snapshot: dict, path: str, normalizer: str) -> dict:
        return next(
            item
            for item in snapshot["resources"]
            if item["path"] == path and item["normalizer"] == normalizer
        )

    def _fake_git(self, body: str) -> Path:
        directory = self.root / "fake-bin"
        directory.mkdir(exist_ok=True)
        executable = directory / "git"
        executable.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        return directory

    def test_repository_fsmonitor_is_not_executed(self) -> None:
        marker = self.root / "fsmonitor-ran"
        monitor = self.root / "fsmonitor"
        monitor.write_text(
            "#!/bin/sh\n: > {!r}\n".format(str(marker)),
            encoding="utf-8",
        )
        monitor.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "config",
                "core.fsmonitor",
                str(monitor),
            ],
            check=True,
        )
        GitClient.snapshot(str(self.repository))
        self.assertFalse(marker.exists())

    def test_command_timeout_terminates_process(self) -> None:
        fake_bin = self._fake_git("while :; do :; done\n")
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"PATH": str(fake_bin)}), mock.patch(
            "dev_flow_orchestrator.git_client.GIT_COMMAND_TIMEOUT_SECONDS", 0.05
        ), mock.patch(
            "dev_flow_orchestrator.git_client.GIT_TERMINATE_GRACE_SECONDS", 0.05
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient._run(self.repository, "status")
        self.assertEqual(context.exception.code, "GIT_COMMAND_TIMEOUT")
        self.assertLess(time.monotonic() - started, 2)

    def test_combined_output_budget_is_enforced_without_deadlock(self) -> None:
        fake_bin = self._fake_git(
            "while :; do printf 1234567890; printf abcdefghij >&2; done\n"
        )
        with mock.patch.dict(os.environ, {"PATH": str(fake_bin)}), mock.patch(
            "dev_flow_orchestrator.git_client.MAX_GIT_OUTPUT_BYTES", 256
        ), mock.patch(
            "dev_flow_orchestrator.git_client.GIT_TERMINATE_GRACE_SECONDS", 0.05
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient._run(self.repository, "status")
        self.assertEqual(context.exception.code, "GIT_OUTPUT_TOO_LARGE")
        self.assertEqual(context.exception.details["limit_bytes"], 256)

    def test_modified_and_untracked_content_change_digest_with_same_status(self) -> None:
        (self.repository / "a.txt").write_text("first\n", encoding="utf-8")
        (self.repository / "new.txt").write_text("alpha\n", encoding="utf-8")
        first = GitClient.snapshot(str(self.repository))

        (self.repository / "a.txt").write_text("other\n", encoding="utf-8")
        second = GitClient.snapshot(str(self.repository))
        self.assertEqual(first["status_sha256"], second["status_sha256"])
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertNotEqual(
            self._entry(first, "a.txt")["content_sha256"],
            self._entry(second, "a.txt")["content_sha256"],
        )

        (self.repository / "new.txt").write_text("omega\n", encoding="utf-8")
        third = GitClient.snapshot(str(self.repository))
        self.assertEqual(second["status_sha256"], third["status_sha256"])
        self.assertNotEqual(second["digest"], third["digest"])

    def test_resource_normalization_and_stable_missing_resource(self) -> None:
        tasks = self.repository / "tasks.md"
        tasks.write_bytes(b"- [ ] required test\n")
        subprocess.run(["git", "-C", str(self.repository), "add", "tasks.md"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qm", "tasks"],
            check=True,
        )
        requests = (
            resource("tasks.md", "reported", "none"),
            resource("tasks.md", "governing", "openspec-tasks-v1"),
            resource("future.md", "governing", "none"),
        )
        first = GitClient.snapshot(str(self.repository), requests)
        missing = self._resource(first, "future.md", "none")
        self.assertEqual(missing["kind"], "missing")
        self.assertIsNone(missing["raw_sha256"])
        self.assertIsNone(missing["semantic_sha256"])

        tasks.write_bytes(b"- [x] required test\n")
        second = GitClient.snapshot(str(self.repository), requests)
        self.assertNotEqual(
            self._resource(first, "tasks.md", "none")["raw_sha256"],
            self._resource(second, "tasks.md", "none")["raw_sha256"],
        )
        self.assertEqual(
            self._resource(first, "tasks.md", "openspec-tasks-v1")["semantic_sha256"],
            self._resource(second, "tasks.md", "openspec-tasks-v1")["semantic_sha256"],
        )

        tasks.write_bytes(b"- [x] changed obligation\n")
        third = GitClient.snapshot(str(self.repository), requests)
        self.assertNotEqual(
            self._resource(second, "tasks.md", "openspec-tasks-v1")["semantic_sha256"],
            self._resource(third, "tasks.md", "openspec-tasks-v1")["semantic_sha256"],
        )

    def test_symlink_hashes_target_bytes_and_special_file_is_rejected(self) -> None:
        outside = self.root / "outside.txt"
        outside.write_text("secret one\n", encoding="utf-8")
        link = self.repository / "outside-link"
        link.symlink_to(outside)
        first = GitClient.snapshot(str(self.repository))
        entry = self._entry(first, "outside-link")
        self.assertEqual(entry["kind"], "symlink")
        self.assertEqual(
            entry["content_sha256"],
            hashlib.sha256(os.fsencode(str(outside))).hexdigest(),
        )

        outside.write_text("secret two\n", encoding="utf-8")
        second = GitClient.snapshot(str(self.repository))
        self.assertEqual(first["digest"], second["digest"])

        fifo = self.repository / "named-pipe"
        os.mkfifo(fifo)
        with self.assertRaises(DevFlowError) as context:
            GitClient.snapshot(str(self.repository), (resource("named-pipe"),))
        self.assertEqual(context.exception.code, "SNAPSHOT_SPECIAL_FILE")
        self.assertEqual(context.exception.details["kind"], "fifo")

    def test_explicit_content_and_path_budgets_fail(self) -> None:
        (self.repository / "large.txt").write_bytes(b"1234")
        with mock.patch(
            "dev_flow_orchestrator.git_client.MAX_SNAPSHOT_FILE_BYTES", 3
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")

        with mock.patch("dev_flow_orchestrator.git_client.MAX_SNAPSHOT_PATHS", 0):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository), (resource("missing.md"),))
        self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")

        with mock.patch(
            "dev_flow_orchestrator.git_client.MAX_SNAPSHOT_CONTENT_BYTES", 1
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")

        with mock.patch(
            "dev_flow_orchestrator.git_client.MAX_SNAPSHOT_PATH_BYTES", 0
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")

        with mock.patch(
            "dev_flow_orchestrator.git_client.SNAPSHOT_TIMEOUT_SECONDS", 0
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")

    def test_snapshot_validation_and_exact_root(self) -> None:
        snapshot = GitClient.snapshot(str(self.repository))
        self.assertEqual(validate_snapshot(snapshot), snapshot)
        tampered = {**snapshot, "branch": "tampered"}
        with self.assertRaises(DevFlowError) as context:
            validate_snapshot(tampered)
        self.assertEqual(context.exception.code, "SNAPSHOT_INVALID")

        child = self.repository / "child"
        child.mkdir()
        with self.assertRaises(DevFlowError) as context:
            GitClient.snapshot(str(child))
        self.assertEqual(context.exception.code, "REPOSITORY_ROOT_REQUIRED")

    def test_snapshot_does_not_rewrite_the_git_index(self) -> None:
        index = self.repository / ".git" / "index"
        before = index.read_bytes()
        tracked = self.repository / "a.txt"
        current = tracked.stat()
        os.utime(tracked, (current.st_atime + 5, current.st_mtime + 5))
        snapshot = GitClient.snapshot(str(self.repository))
        self.assertTrue(snapshot["clean"])
        self.assertEqual(index.read_bytes(), before)

    def test_path_replacement_and_git_enumeration_races_fail(self) -> None:
        tracked = self.repository / "a.txt"
        tracked.write_text("already modified\n", encoding="utf-8")
        original_read = GitClient._read_path
        replaced = [False]

        def replace_after_read(*args, **kwargs):
            result = original_read(*args, **kwargs)
            if args[2] == "a.txt" and not replaced[0]:
                replacement = self.repository / "replacement"
                replacement.write_text("replacement body\n", encoding="utf-8")
                os.replace(replacement, tracked)
                replaced[0] = True
            return result

        with mock.patch.object(GitClient, "_read_path", side_effect=replace_after_read):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_UNSTABLE")

        original_capture = GitClient._capture_enumeration
        calls = [0]

        def change_before_second_capture(repository: Path, deadline: float):
            calls[0] += 1
            if calls[0] == 2:
                (repository / "late.txt").write_text("late\n", encoding="utf-8")
            return original_capture(repository, deadline)

        with mock.patch.object(
            GitClient,
            "_capture_enumeration",
            side_effect=change_before_second_capture,
        ):
            with self.assertRaises(DevFlowError) as context:
                GitClient.snapshot(str(self.repository))
        self.assertEqual(context.exception.code, "SNAPSHOT_UNSTABLE")

    def test_clean_gitlink_is_hashed_and_dirty_or_missing_gitlink_fails(self) -> None:
        source = make_repository(self.root, "submodule-source")
        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "-C",
                str(self.repository),
                "submodule",
                "add",
                "-q",
                str(source),
                "vendor/module",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qam", "submodule"],
            check=True,
        )
        request = (resource("vendor/module"),)
        clean = GitClient.snapshot(str(self.repository), request)
        entry = self._entry(clean, "vendor/module")
        self.assertEqual(entry["kind"], "gitlink")
        self.assertEqual(entry["index_oid"], entry["submodule_head"])

        checkout = self.repository / "vendor" / "module"
        (checkout / "a.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(DevFlowError) as context:
            GitClient.snapshot(str(self.repository), request)
        self.assertEqual(context.exception.code, "SNAPSHOT_GITLINK_DIRTY")

        (checkout / "a.txt").write_text("hello\n", encoding="utf-8")
        checkout.rename(self.root / "saved-submodule")
        with self.assertRaises(DevFlowError) as context:
            GitClient.snapshot(str(self.repository), request)
        self.assertEqual(context.exception.code, "SNAPSHOT_GITLINK_MISSING")


if __name__ == "__main__":
    unittest.main()
