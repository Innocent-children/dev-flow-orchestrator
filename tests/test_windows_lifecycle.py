"""Black-box representative Windows PowerShell install/uninstall coverage."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def configure(repository: Path) -> None:
    git("config", "user.name", "Windows Lifecycle Test", cwd=repository)
    git("config", "user.email", "windows-test@example.invalid", cwd=repository)


@unittest.skipUnless(sys.platform == "win32", "requires native Windows PowerShell")
class WindowsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = tempfile.TemporaryDirectory()
        fixture = Path(cls.fixture.name)
        seed = fixture / "candidate seed"
        seed.mkdir()
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        for raw in listed.split(b"\0"):
            if not raw:
                continue
            relative = Path(os.fsdecode(raw))
            source = ROOT / relative
            if source.is_file():
                target = seed / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        git("init", "--initial-branch=main", cwd=seed)
        configure(seed)
        git("add", "--all", cwd=seed)
        git("commit", "-m", "candidate", cwd=seed)
        cls.remote_template = fixture / "remote.git"
        git("init", "--bare", str(cls.remote_template))
        git("remote", "add", "origin", str(cls.remote_template), cwd=seed)
        git("push", "origin", "main", cwd=seed)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote copy.git"
        shutil.copytree(self.remote_template, self.remote)
        self.source = self.root / "plugins" / "source with spaces"
        self.marketplace = self.root / ".agents" / "plugins" / "marketplace.json"
        self.state = self.root / "plugin-state.txt"
        self.log = self.root / "codex.log"
        fake_bin = self.root / "fake bin"
        fake_bin.mkdir()
        (fake_bin / "codex.cmd").write_text(
            '@echo off\r\n"%DEV_FLOW_PYTHON%" "%~dp0codex_stub.py" %*\r\n',
            encoding="ascii",
        )
        (fake_bin / "codex_stub.py").write_text(
            """import json
import os
import sys

args = sys.argv[1:]
state = os.environ["DEV_FLOW_CODEX_STATE"]
if args[:3] == ["plugin", "list", "--marketplace"]:
    installed = []
    if os.path.exists(state):
        installed.append({"pluginId": "dev-flow-orchestrator@personal", "version": open(state).read(), "installed": True})
    print(json.dumps({"installed": installed}))
elif args == ["plugin", "remove", "dev-flow-orchestrator@personal"]:
    open(os.environ["DEV_FLOW_CODEX_LOG"], "a").write("remove\\n")
    if os.path.exists(state):
        os.unlink(state)
elif args == ["plugin", "add", "dev-flow-orchestrator@personal"]:
    if os.environ.get("DEV_FLOW_CODEX_ADD_EXIT") != "0":
        sys.exit(int(os.environ["DEV_FLOW_CODEX_ADD_EXIT"]))
    open(os.environ["DEV_FLOW_CODEX_LOG"], "a").write("add\\n")
    open(state, "w").write("0.3.0")
else:
    sys.exit(2)
""",
            encoding="utf-8",
        )
        self.environment = {
            **os.environ,
            "DEV_FLOW_REPOSITORY_URL": self.remote.as_uri(),
            "DEV_FLOW_SOURCE_ROOT": str(self.source),
            "DEV_FLOW_MARKETPLACE_FILE": str(self.marketplace),
            "DEV_FLOW_PYTHON": sys.executable,
            "DEV_FLOW_CODEX_STATE": str(self.state),
            "DEV_FLOW_CODEX_LOG": str(self.log),
            "DEV_FLOW_CODEX_ADD_EXIT": "0",
            "CODEX_HOME": str(self.root / ".codex"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(self, name: str, *arguments: str, overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        if overrides:
            environment.update(overrides)
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / name), *arguments],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def advance_remote(self, name: str = "incoming.txt") -> str:
        checkout = self.root / ("remote advance " + name.replace(".", "-"))
        git("clone", str(self.remote), str(checkout))
        configure(checkout)
        (checkout / name).write_text("incoming\n", encoding="utf-8")
        git("add", name, cwd=checkout)
        git("commit", "-m", "advance", cwd=checkout)
        commit = git("rev-parse", "HEAD", cwd=checkout)
        git("push", "origin", "main", cwd=checkout)
        return commit

    def test_fresh_install_and_repair_preserve_one_marketplace_entry(self) -> None:
        first = self.run_script("install.ps1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("HOOK REVIEW", first.stdout)
        self.assertIn("does not establish Hook trust", first.stdout)
        for label in ("ACTION", "VERSION", "SOURCE", "MARKETPLACE", "CODEX HOME", "FIRST PROMPT"):
            self.assertIn(label, first.stdout)
        second = self.run_script("install.ps1")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("repaired", second.stdout)
        plugins = json.loads(self.marketplace.read_text(encoding="utf-8-sig"))["plugins"]
        self.assertEqual(sum(item.get("name") == "dev-flow-orchestrator" for item in plugins), 1)

    def test_older_version_is_upgraded(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        self.state.write_text("0.2.0", encoding="utf-8")
        result = self.run_script("install.ps1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ACTION         upgraded", result.stdout)
        self.assertIn("PREVIOUS       0.2.0", result.stdout)

    def test_dirty_source_is_rejected_without_activation(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        self.log.write_text("", encoding="utf-8")
        (self.source / "local.txt").write_text("work", encoding="utf-8")
        result = self.run_script("install.ps1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_activation_failure_is_nonzero_with_recovery_command(self) -> None:
        result = self.run_script("install.ps1", overrides={"DEV_FLOW_CODEX_ADD_EXIT": "17"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("codex plugin add", result.stderr)

    def test_keep_source_uninstall_preserves_checkout_and_task_data(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        task_data = self.root / ".codex" / "plugins" / "data" / "task.json"
        task_data.parent.mkdir(parents=True)
        task_data.write_text("preserve", encoding="utf-8")
        result = self.run_script("uninstall.ps1", "-KeepSource")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.source.is_dir())
        self.assertEqual(task_data.read_text(encoding="utf-8"), "preserve")
        self.assertIn("TASK DATA", result.stdout)

    def test_fast_forward_install_and_default_uninstall_preserve_task_data(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        expected = self.advance_remote()
        repaired = self.run_script("install.ps1")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.source), expected)

        task_data = self.root / ".codex" / "plugins" / "data" / "task.json"
        task_data.parent.mkdir(parents=True)
        task_data.write_text("preserve", encoding="utf-8")
        removed = self.run_script("uninstall.ps1")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(self.source.exists())
        self.assertEqual(task_data.read_text(encoding="utf-8"), "preserve")

    def test_malformed_marketplace_preserves_original_bytes(self) -> None:
        self.marketplace.parent.mkdir(parents=True)
        original = b"{ malformed marketplace \xff"
        self.marketplace.write_bytes(original)
        result = self.run_script("install.ps1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.marketplace.read_bytes(), original)
        self.assertFalse(self.state.exists())

    def test_ignored_predecessor_cache_failure_has_recovery_commands(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        legacy = self.source / "scripts" / "dev_flow_parts" / "__pycache__"
        legacy.mkdir(parents=True)
        (legacy / "old.cpython-314.pyc").write_bytes(b"cache")
        self.log.write_text("", encoding="utf-8")

        result = self.run_script("install.ps1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git.exe -C", result.stderr)
        self.assertIn("status --ignored --porcelain", result.stderr)
        self.assertIn("powershell.exe -NoProfile", result.stderr)
        self.assertIn("Preserve and inspect", result.stderr)
        self.assertTrue(legacy.is_dir())
        self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_unrelated_marketplace_entries_are_preserved(self) -> None:
        self.marketplace.parent.mkdir(parents=True)
        self.marketplace.write_text(
            json.dumps({"name": "personal", "plugins": [{"name": "unrelated"}]}),
            encoding="utf-8",
        )
        installed = self.run_script("install.ps1")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        document = json.loads(self.marketplace.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            [item["name"] for item in document["plugins"]],
            ["unrelated", "dev-flow-orchestrator"],
        )
        removed = self.run_script("uninstall.ps1", "-KeepSource")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        document = json.loads(self.marketplace.read_text(encoding="utf-8-sig"))
        self.assertEqual([item["name"] for item in document["plugins"]], ["unrelated"])

    def assert_reinstall_refused_without_activation(self, scenario: str) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        self.log.write_text("", encoding="utf-8")
        if scenario == "branch":
            git("switch", "-c", "topic", cwd=self.source)
        elif scenario == "detached":
            git("switch", "--detach", cwd=self.source)
        else:
            git("remote", "set-url", "origin", str(self.root / "unexpected.git"), cwd=self.source)
        result = self.run_script("install.ps1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_non_main_source_is_rejected(self) -> None:
        self.assert_reinstall_refused_without_activation("branch")

    def test_detached_source_is_rejected(self) -> None:
        self.assert_reinstall_refused_without_activation("detached")

    def test_unexpected_origin_is_rejected(self) -> None:
        self.assert_reinstall_refused_without_activation("origin")

    def test_incoming_main_does_not_overwrite_ignored_path(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        (self.source / ".git" / "info" / "exclude").write_text(
            "incoming.txt\n", encoding="utf-8"
        )
        (self.source / "incoming.txt").write_text("local ignored\n", encoding="utf-8")
        self.advance_remote("incoming.txt")
        self.log.write_text("", encoding="utf-8")
        result = self.run_script("install.ps1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.source / "incoming.txt").read_text(encoding="utf-8"), "local ignored\n")
        self.assertEqual(self.log.read_text(encoding="utf-8"), "")

    def test_local_ahead_and_diverged_histories_are_rejected(self) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        (self.source / "local-only.txt").write_text("local\n", encoding="utf-8")
        git("add", "local-only.txt", cwd=self.source)
        git("commit", "-m", "local ahead", cwd=self.source)
        ahead = self.run_script("install.ps1")
        self.assertNotEqual(ahead.returncode, 0)
        self.assertIn("local commits", ahead.stderr)

        self.advance_remote("remote-only.txt")
        diverged = self.run_script("install.ps1")
        self.assertNotEqual(diverged.returncode, 0)
        self.assertIn("diverged", diverged.stderr)

    def assert_unsafe_uninstall_preserves_source(self, scenario: str) -> None:
        self.assertEqual(self.run_script("install.ps1").returncode, 0)
        if scenario == "ignored":
            (self.source / ".git" / "info" / "exclude").write_text(
                "local-cache.txt\n", encoding="utf-8"
            )
            (self.source / "local-cache.txt").write_text("cache", encoding="utf-8")
        else:
            (self.source / "local-commit.txt").write_text("local", encoding="utf-8")
            git("add", "local-commit.txt", cwd=self.source)
            git("commit", "-m", "local only", cwd=self.source)
        result = self.run_script("uninstall.ps1")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.source.is_dir())

    def test_uninstaller_refuses_ignored_source(self) -> None:
        self.assert_unsafe_uninstall_preserves_source("ignored")

    def test_uninstaller_refuses_local_only_commit(self) -> None:
        self.assert_unsafe_uninstall_preserves_source("local-commit")


if __name__ == "__main__":
    unittest.main()
