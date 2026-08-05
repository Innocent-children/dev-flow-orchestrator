"""Black-box coverage for the public macOS installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Optional
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install.sh"


def _git(*arguments: str, cwd: Optional[Path] = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _configure_identity(repository: Path) -> None:
    _git("config", "user.name", "Installer Test", cwd=repository)
    _git("config", "user.email", "installer-test@example.invalid", cwd=repository)


def _copy_candidate(destination: Path) -> None:
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    for encoded_relative in listed.split(b"\0"):
        if not encoded_relative:
            continue
        relative = Path(os.fsdecode(encoded_relative))
        source = ROOT / relative
        if not source.is_file() and not source.is_symlink():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, target)


@unittest.skipUnless(sys.platform == "darwin", "installer supports macOS only")
class InstallerBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_temporary = tempfile.TemporaryDirectory()
        fixture_root = Path(cls.fixture_temporary.name)
        seed = fixture_root / "candidate seed"
        seed.mkdir()
        _copy_candidate(seed)

        _git("init", "--initial-branch=main", cwd=seed)
        _configure_identity(seed)
        _git("add", "--all", cwd=seed)
        _git("commit", "-m", "candidate main", cwd=seed)

        cls.remote_template = fixture_root / "remote template.git"
        _git("init", "--bare", str(cls.remote_template))
        _git("remote", "add", "origin", str(cls.remote_template), cwd=seed)
        _git("push", "origin", "main", cwd=seed)

        _git("switch", "-c", "other", cwd=seed)
        (seed / "default-branch-marker.txt").write_text(
            "this branch is intentionally not authoritative\n",
            encoding="utf-8",
        )
        _git("add", "default-branch-marker.txt", cwd=seed)
        _git("commit", "-m", "non-authoritative default branch", cwd=seed)
        _git("push", "origin", "other", cwd=seed)
        _git(
            "--git-dir",
            str(cls.remote_template),
            "symbolic-ref",
            "HEAD",
            "refs/heads/other",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_temporary.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temporary.name)
        self.remote = self.test_root / "authoritative remote.git"
        shutil.copytree(self.remote_template, self.remote)
        self.remote_url = self.remote.as_uri()
        self.source_root = (
            self.test_root / "plugins" / "installed source with spaces"
        )
        self.marketplace = (
            self.test_root / ".agents" / "plugins" / "marketplace.json"
        )
        self.codex_log = self.test_root / "codex calls.log"
        self.publisher_counter = 0

        fake_bin = self.test_root / "fake bin"
        fake_bin.mkdir()
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$DEV_FLOW_CODEX_LOG\"\n"
            "exit \"${DEV_FLOW_CODEX_EXIT:-0}\"\n",
            encoding="utf-8",
        )
        fake_codex.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )

        self.environment = os.environ.copy()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.environment.pop(name, None)
        self.environment.update(
            {
                "DEV_FLOW_REPOSITORY_URL": self.remote_url,
                "DEV_FLOW_SOURCE_ROOT": str(self.source_root),
                "DEV_FLOW_MARKETPLACE_FILE": str(self.marketplace),
                "DEV_FLOW_CODEX_LOG": str(self.codex_log),
                "DEV_FLOW_CODEX_EXIT": "0",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": str(fake_bin)
                + os.pathsep
                + self.environment.get("PATH", ""),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_installer(
        self,
        overrides: Optional[Mapping[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        if overrides:
            environment.update(overrides)
        return subprocess.run(
            ["/bin/sh", str(INSTALLER)],
            cwd=self.test_root,
            env=environment,
            capture_output=True,
            text=True,
        )

    def install_successfully(self) -> subprocess.CompletedProcess[str]:
        result = self.run_installer()
        self.assertEqual(
            result.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr),
        )
        return result

    def activation_calls(self) -> list[str]:
        if not self.codex_log.exists():
            return []
        return self.codex_log.read_text(encoding="utf-8").splitlines()

    def clear_activation_calls(self) -> None:
        if self.codex_log.exists():
            self.codex_log.unlink()

    def marketplace_plugins(self) -> list[object]:
        return json.loads(self.marketplace.read_text(encoding="utf-8"))["plugins"]

    def advance_remote_main(self) -> str:
        self.publisher_counter += 1
        publisher = self.test_root / "publisher-{}".format(self.publisher_counter)
        _git("clone", "--branch", "main", self.remote_url, str(publisher))
        _configure_identity(publisher)
        readme = publisher / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8")
            + "\ninstaller fixture update {}\n".format(self.publisher_counter),
            encoding="utf-8",
        )
        _git("add", "README.md", cwd=publisher)
        _git(
            "commit",
            "-m",
            "remote update {}".format(self.publisher_counter),
            cwd=publisher,
        )
        _git("push", "origin", "main", cwd=publisher)
        return _git("rev-parse", "HEAD", cwd=publisher)

    def add_remote_main_file(self, relative_path: str, content: str) -> str:
        self.publisher_counter += 1
        publisher = self.test_root / "publisher-{}".format(self.publisher_counter)
        _git("clone", "--branch", "main", self.remote_url, str(publisher))
        _configure_identity(publisher)
        published_file = publisher / relative_path
        published_file.parent.mkdir(parents=True, exist_ok=True)
        published_file.write_text(content, encoding="utf-8")
        _git("add", "--", relative_path, cwd=publisher)
        _git(
            "commit",
            "-m",
            "add remote file {}".format(self.publisher_counter),
            cwd=publisher,
        )
        _git("push", "origin", "main", cwd=publisher)
        return _git("rev-parse", "HEAD", cwd=publisher)

    def test_fresh_install_selects_main_and_preserves_marketplace_entries(self) -> None:
        other_entry = {
            "name": "other-plugin",
            "source": {"source": "local", "path": "/tmp/other-plugin"},
        }
        stale_entry = {
            "name": "dev-flow-orchestrator",
            "source": {"source": "local", "path": "/tmp/stale"},
        }
        self.marketplace.parent.mkdir(parents=True)
        self.marketplace.write_text(
            json.dumps(
                {
                    "name": "personal",
                    "interface": {"displayName": "Personal"},
                    "plugins": [other_entry, stale_entry],
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            _git("--git-dir", str(self.remote), "symbolic-ref", "--short", "HEAD"),
            "other",
        )
        self.install_successfully()

        self.assertEqual(
            _git("symbolic-ref", "--short", "HEAD", cwd=self.source_root),
            "main",
        )
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.source_root),
            _git("--git-dir", str(self.remote), "rev-parse", "refs/heads/main"),
        )
        plugins = self.marketplace_plugins()
        self.assertIn(other_entry, plugins)
        dev_flow_entries = [
            item
            for item in plugins
            if isinstance(item, dict)
            and item.get("name") == "dev-flow-orchestrator"
        ]
        self.assertEqual(len(dev_flow_entries), 1)
        self.assertEqual(
            dev_flow_entries[0]["source"]["path"],
            "./plugins/installed source with spaces",
        )
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )

    def test_existing_install_is_idempotent(self) -> None:
        self.install_successfully()
        installed_head = _git("rev-parse", "HEAD", cwd=self.source_root)
        self.clear_activation_calls()

        self.install_successfully()

        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.source_root),
            installed_head,
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in self.marketplace_plugins()
                    if isinstance(item, dict)
                    and item.get("name") == "dev-flow-orchestrator"
                ]
            ),
            1,
        )
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )

    def test_existing_install_fast_forwards_to_fetched_main(self) -> None:
        self.install_successfully()
        old_head = _git("rev-parse", "HEAD", cwd=self.source_root)
        authoritative_head = self.advance_remote_main()
        self.clear_activation_calls()

        self.install_successfully()

        self.assertNotEqual(old_head, authoritative_head)
        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.source_root),
            authoritative_head,
        )
        self.assertEqual(_git("status", "--porcelain", cwd=self.source_root), "")
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )

    def test_dirty_checkout_is_preserved_and_rejected(self) -> None:
        self.install_successfully()
        dirty_file = self.source_root / "keep-local-work.txt"
        dirty_file.write_text("do not overwrite\n", encoding="utf-8")
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has local changes", result.stderr)
        self.assertEqual(dirty_file.read_text(encoding="utf-8"), "do not overwrite\n")
        self.assertEqual(self.activation_calls(), [])

    def test_ignored_path_collision_is_preserved_and_rejected(self) -> None:
        self.install_successfully()
        relative_path = "ignored local work.txt"
        ignored_file = self.source_root / relative_path
        ignored_file.write_bytes(b"local valuable content\n")
        exclude_file = self.source_root / ".git" / "info" / "exclude"
        with exclude_file.open("a", encoding="utf-8") as stream:
            stream.write("/{}\n".format(relative_path))
        self.assertEqual(
            _git("check-ignore", "--", relative_path, cwd=self.source_root),
            relative_path,
        )
        self.assertEqual(_git("status", "--porcelain", cwd=self.source_root), "")
        head_before = _git("rev-parse", "HEAD", cwd=self.source_root)
        marketplace_before = self.marketplace.read_bytes()
        authoritative_head = self.add_remote_main_file(
            relative_path,
            "upstream content\n",
        )
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("without overwriting local work", result.stderr)
        self.assertNotEqual(head_before, authoritative_head)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.source_root), head_before)
        self.assertEqual(ignored_file.read_bytes(), b"local valuable content\n")
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_unrelated_ignored_file_is_preserved_during_fast_forward(self) -> None:
        self.install_successfully()
        relative_path = "ignored local cache.txt"
        ignored_file = self.source_root / relative_path
        ignored_file.write_bytes(b"local cache content\n")
        exclude_file = self.source_root / ".git" / "info" / "exclude"
        with exclude_file.open("a", encoding="utf-8") as stream:
            stream.write("/{}\n".format(relative_path))
        authoritative_head = self.advance_remote_main()
        self.clear_activation_calls()

        self.install_successfully()

        self.assertEqual(
            _git("rev-parse", "HEAD", cwd=self.source_root),
            authoritative_head,
        )
        self.assertEqual(ignored_file.read_bytes(), b"local cache content\n")
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )

    def test_unexpected_origin_is_rejected_before_activation(self) -> None:
        self.install_successfully()
        marketplace_before = self.marketplace.read_bytes()
        _git(
            "remote",
            "set-url",
            "origin",
            (self.test_root / "unexpected.git").as_uri(),
            cwd=self.source_root,
        )
        head_before = _git("rev-parse", "HEAD", cwd=self.source_root)
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected '{}'".format(self.remote_url), result.stderr)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.source_root), head_before)
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_unexpected_branch_is_not_switched_or_activated(self) -> None:
        self.install_successfully()
        _git("switch", "-c", "feature", cwd=self.source_root)
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected branch 'main'", result.stderr)
        self.assertEqual(
            _git("symbolic-ref", "--short", "HEAD", cwd=self.source_root),
            "feature",
        )
        self.assertEqual(self.activation_calls(), [])

    def test_local_ahead_checkout_is_preserved_and_rejected(self) -> None:
        self.install_successfully()
        _configure_identity(self.source_root)
        local_file = self.source_root / "local-only.txt"
        local_file.write_text("local commit\n", encoding="utf-8")
        _git("add", "local-only.txt", cwd=self.source_root)
        _git("commit", "-m", "local commit", cwd=self.source_root)
        local_head = _git("rev-parse", "HEAD", cwd=self.source_root)
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has local commits beyond authoritative origin/main", result.stderr)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.source_root), local_head)
        self.assertEqual(local_file.read_text(encoding="utf-8"), "local commit\n")
        self.assertEqual(self.activation_calls(), [])

    def test_diverged_checkout_is_preserved_and_rejected(self) -> None:
        self.install_successfully()
        _configure_identity(self.source_root)
        local_file = self.source_root / "local-divergence.txt"
        local_file.write_text("local side\n", encoding="utf-8")
        _git("add", "local-divergence.txt", cwd=self.source_root)
        _git("commit", "-m", "local side", cwd=self.source_root)
        local_head = _git("rev-parse", "HEAD", cwd=self.source_root)
        self.advance_remote_main()
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has diverged from authoritative origin/main", result.stderr)
        self.assertEqual(_git("rev-parse", "HEAD", cwd=self.source_root), local_head)
        self.assertEqual(local_file.read_text(encoding="utf-8"), "local side\n")
        self.assertEqual(self.activation_calls(), [])

    def test_malformed_marketplace_is_preserved_and_not_activated(self) -> None:
        self.marketplace.parent.mkdir(parents=True)
        malformed = b"{not valid json\n"
        self.marketplace.write_bytes(malformed)

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot read", result.stderr)
        self.assertEqual(self.marketplace.read_bytes(), malformed)
        self.assertEqual(self.activation_calls(), [])

    def test_plugin_activation_failure_reports_recovery_commands(self) -> None:
        result = self.run_installer({"DEV_FLOW_CODEX_EXIT": "17"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "codex plugin remove dev-flow-orchestrator@personal",
            result.stderr,
        )
        self.assertIn(
            "codex plugin add dev-flow-orchestrator@personal",
            result.stderr,
        )
        self.assertTrue(self.source_root.is_dir())
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in self.marketplace_plugins()
                    if isinstance(item, dict)
                    and item.get("name") == "dev-flow-orchestrator"
                ]
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
