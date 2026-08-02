"""Git preflight is side-effect-free and bounded on this macOS host."""

from __future__ import annotations

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

from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase


class GitReadOnlyTests(V5TestCase):
    def test_inspect_does_not_rewrite_index(self) -> None:
        index = self.repository / ".git" / "index"
        before = index.read_bytes()
        tracked = self.repository / "a.txt"
        current = tracked.stat()
        os.utime(tracked, (current.st_atime + 5, current.st_mtime + 5))
        evidence = GitClient.inspect(str(self.repository))
        self.assertEqual(index.read_bytes(), before)
        self.assertTrue(evidence["clean"])

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
        GitClient.inspect(str(self.repository))
        self.assertFalse(marker.exists())

    def _fake_git(self, body: str) -> Path:
        directory = self.root / "fake-bin"
        directory.mkdir(exist_ok=True)
        executable = directory / "git"
        executable.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        return directory

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


if __name__ == "__main__":
    unittest.main()
