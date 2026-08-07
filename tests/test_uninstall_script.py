"""Black-box coverage for the public macOS uninstaller."""

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
UNINSTALLER = ROOT / "scripts" / "uninstall.sh"


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
    _git("config", "user.name", "Uninstaller Test", cwd=repository)
    _git("config", "user.email", "uninstaller-test@example.invalid", cwd=repository)


@unittest.skipUnless(sys.platform == "darwin", "uninstaller supports macOS only")
class UninstallerBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.test_root = Path(self.temporary.name)
        self.source_root = self.test_root / "plugins" / "dev-flow-orchestrator"
        self.marketplace = (
            self.test_root / ".agents" / "plugins" / "marketplace.json"
        )
        self.codex_root = self.test_root / ".codex"
        self.codex_state = self.test_root / "installed plugin.txt"
        self.codex_log = self.test_root / "codex calls.log"

        seed = self.test_root / "seed"
        manifest = seed / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps(
                {
                    "name": "dev-flow-orchestrator",
                    "version": "0.4.0",
                    "description": "test candidate",
                }
            ),
            encoding="utf-8",
        )
        _git("init", "--initial-branch=main", cwd=seed)
        _configure_identity(seed)
        _git("add", "--all", cwd=seed)
        _git("commit", "-m", "candidate", cwd=seed)

        self.remote = self.test_root / "origin.git"
        _git("init", "--bare", str(self.remote))
        _git("remote", "add", "origin", str(self.remote), cwd=seed)
        _git("push", "origin", "main", cwd=seed)
        self.remote_url = self.remote.as_uri()
        self.source_root.parent.mkdir(parents=True)
        _git(
            "clone",
            "--branch",
            "main",
            self.remote_url,
            str(self.source_root),
        )

        fake_bin = self.test_root / "fake bin"
        fake_bin.mkdir()
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  'plugin list --json')\n"
            "    if [ -f \"$DEV_FLOW_CODEX_STATE\" ]; then\n"
            "      printf '{\"installed\":[{\"pluginId\":\"dev-flow-orchestrator@personal\",\"installed\":true}]}\\n'\n"
            "    else\n"
            "      printf '{\"installed\":[]}\\n'\n"
            "    fi\n"
            "    ;;\n"
            "  'plugin remove dev-flow-orchestrator@personal')\n"
            "    printf '%s\\n' \"$*\" >> \"$DEV_FLOW_CODEX_LOG\"\n"
            "    exit_code=\"${DEV_FLOW_CODEX_REMOVE_EXIT:-0}\"\n"
            "    [ \"$exit_code\" -eq 0 ] || exit \"$exit_code\"\n"
            "    rm -f \"$DEV_FLOW_CODEX_STATE\"\n"
            "    ;;\n"
            "  *)\n"
            "    exit 2\n"
            "    ;;\n"
            "esac\n",
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
        for name in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "NO_COLOR",
            "DEV_FLOW_FORCE_COLOR",
        ):
            self.environment.pop(name, None)
        self.environment.update(
            {
                "DEV_FLOW_REPOSITORY_URL": self.remote_url,
                "DEV_FLOW_SOURCE_ROOT": str(self.source_root),
                "DEV_FLOW_MARKETPLACE_FILE": str(self.marketplace),
                "DEV_FLOW_CODEX_STATE": str(self.codex_state),
                "DEV_FLOW_CODEX_LOG": str(self.codex_log),
                "DEV_FLOW_CODEX_REMOVE_EXIT": "0",
                "CODEX_HOME": str(self.codex_root),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "LANG": "C",
                "LC_ALL": "C",
                "PATH": str(fake_bin)
                + os.pathsep
                + self.environment.get("PATH", ""),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_marketplace(self, *, include_dev_flow: bool = True) -> None:
        plugins: list[object] = [
            {
                "name": "other-plugin",
                "source": {"source": "local", "path": "./plugins/other"},
            }
        ]
        if include_dev_flow:
            plugins.append(
                {
                    "name": "dev-flow-orchestrator",
                    "source": {
                        "source": "local",
                        "path": "./plugins/dev-flow-orchestrator",
                    },
                }
            )
        self.marketplace.parent.mkdir(parents=True, exist_ok=True)
        self.marketplace.write_text(
            json.dumps({"name": "personal", "plugins": plugins}),
            encoding="utf-8",
        )

    def run_uninstaller(
        self,
        *arguments: str,
        overrides: Optional[Mapping[str, str]] = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = self.environment.copy()
        if overrides:
            environment.update(overrides)
        return subprocess.run(
            ["/bin/sh", str(UNINSTALLER), *arguments],
            cwd=self.test_root,
            env=environment,
            capture_output=True,
            text=True,
        )

    def activation_calls(self) -> list[str]:
        if not self.codex_log.exists():
            return []
        return self.codex_log.read_text(encoding="utf-8").splitlines()

    def test_default_uninstall_removes_plugin_entry_and_clean_source(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        task_data = self.codex_root / "plugins" / "data" / "task.json"
        task_data.parent.mkdir(parents=True)
        task_data.write_text("preserve me\n", encoding="utf-8")

        result = self.run_uninstaller()

        self.assertEqual(
            result.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr),
        )
        self.assertFalse(self.source_root.exists())
        self.assertFalse(self.codex_state.exists())
        self.assertEqual(
            self.activation_calls(),
            ["plugin remove dev-flow-orchestrator@personal"],
        )
        plugins = json.loads(self.marketplace.read_text(encoding="utf-8"))[
            "plugins"
        ]
        self.assertEqual([item["name"] for item in plugins], ["other-plugin"])
        self.assertEqual(task_data.read_text(encoding="utf-8"), "preserve me\n")
        self.assertIn("// SYSTEM OFFLINE", result.stdout)
        self.assertIn("UNINSTALL RECEIPT", result.stdout)
        self.assertIn("External Dev Flow task data", result.stdout)

    def test_keep_source_allows_local_work_and_preserves_checkout(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        local_file = self.source_root / "local work.txt"
        local_file.write_text("preserve me\n", encoding="utf-8")

        result = self.run_uninstaller("--keep-source")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(local_file.read_text(encoding="utf-8"), "preserve me\n")
        self.assertIn("preserved (--keep-source)", result.stdout)
        self.assertFalse(self.codex_state.exists())

    def test_dirty_source_stops_before_any_uninstall_mutation(self) -> None:
        self.write_marketplace()
        marketplace_before = self.marketplace.read_bytes()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        (self.source_root / "local work.txt").write_text(
            "preserve me\n", encoding="utf-8"
        )

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has local changes", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_ignored_source_path_stops_before_mutation(self) -> None:
        self.write_marketplace()
        marketplace_before = self.marketplace.read_bytes()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        ignored_name = "ignored-local-data.txt"
        (self.source_root / ".git" / "info" / "exclude").write_text(
            "/{}\n".format(ignored_name), encoding="utf-8"
        )
        (self.source_root / ignored_name).write_text(
            "preserve me\n", encoding="utf-8"
        )
        self.assertEqual(_git("status", "--porcelain", cwd=self.source_root), "")

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("contains ignored paths", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_local_only_commit_stops_before_mutation(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        _configure_identity(self.source_root)
        local_file = self.source_root / "local-commit.txt"
        local_file.write_text("preserve me\n", encoding="utf-8")
        _git("add", "local-commit.txt", cwd=self.source_root)
        _git("commit", "-m", "local commit", cwd=self.source_root)

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commits that are not present on origin", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_plugin_remove_failure_preserves_entry_and_source(self) -> None:
        self.write_marketplace()
        marketplace_before = self.marketplace.read_bytes()
        self.codex_state.write_text("installed\n", encoding="utf-8")

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_CODEX_REMOVE_EXIT": "17"}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Finish or cancel active Dev Flow tasks", result.stderr)
        self.assertTrue(self.source_root.exists())
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)

    def test_malformed_marketplace_stops_before_plugin_remove(self) -> None:
        self.marketplace.parent.mkdir(parents=True)
        malformed = b"{not valid json\n"
        self.marketplace.write_bytes(malformed)
        self.codex_state.write_text("installed\n", encoding="utf-8")

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot validate the personal marketplace", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.marketplace.read_bytes(), malformed)
        self.assertEqual(self.activation_calls(), [])

    def test_already_absent_uninstall_is_idempotent(self) -> None:
        self.write_marketplace(include_dev_flow=False)
        shutil.rmtree(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.activation_calls(), [])
        self.assertIn("already absent", result.stdout)

    def test_uninstall_receipt_uses_neon_colors_when_forced(self) -> None:
        self.write_marketplace()

        result = self.run_uninstaller(
            "--keep-source", overrides={"DEV_FLOW_FORCE_COLOR": "1"}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\x1b[38;5;51m", result.stdout)
        self.assertIn("\x1b[38;5;213m", result.stdout)
        self.assertIn("\x1b[38;5;82m", result.stdout)


if __name__ == "__main__":
    unittest.main()
