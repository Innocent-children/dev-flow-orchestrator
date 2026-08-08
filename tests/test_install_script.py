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
PACKAGE_VERSION = json.loads(
    (ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
)["version"]


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
        self.codex_state = self.test_root / "installed plugin version.txt"
        self.codex_candidate_active = self.test_root / "candidate plugin active"
        self.publisher_counter = 0

        fake_bin = self.test_root / "fake bin"
        fake_bin.mkdir()
        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  'mcp list --json')\n"
            "    if [ -f \"$DEV_FLOW_CODEX_CANDIDATE_ACTIVE\" ]; then\n"
            "      printf '%s\\n' \"$DEV_FLOW_ACTIVE_MCP_LIST_JSON\"\n"
            "    elif [ -n \"${DEV_FLOW_MCP_LIST_JSON+x}\" ]; then\n"
            "      printf '%s\\n' \"$DEV_FLOW_MCP_LIST_JSON\"\n"
            "    elif [ -f \"$DEV_FLOW_CODEX_STATE\" ]; then\n"
            "      printf '%s\\n' \"$DEV_FLOW_ACTIVE_MCP_LIST_JSON\"\n"
            "    else\n"
            "      printf '[]\\n'\n"
            "    fi\n"
            "    ;;\n"
            "  'plugin list --marketplace personal --json')\n"
            "    if [ -f \"$DEV_FLOW_CODEX_STATE\" ]; then\n"
            "      version=\"$(cat \"$DEV_FLOW_CODEX_STATE\")\"\n"
            "      printf '{\"installed\":[{\"pluginId\":\"dev-flow-orchestrator@personal\",\"version\":\"%s\",\"installed\":true,\"enabled\":%s}]}\\n' \"$version\" \"${DEV_FLOW_CODEX_ENABLED_JSON:-true}\"\n"
            "    else\n"
            "      printf '{\"installed\":[]}\\n'\n"
            "    fi\n"
            "    ;;\n"
            "  'plugin remove dev-flow-orchestrator@personal')\n"
            "    printf '%s\\n' \"$*\" >> \"$DEV_FLOW_CODEX_LOG\"\n"
            "    exit_code=\"${DEV_FLOW_CODEX_REMOVE_EXIT:-0}\"\n"
            "    [ \"$exit_code\" -eq 0 ] || exit \"$exit_code\"\n"
            "    rm -f \"$DEV_FLOW_CODEX_STATE\"\n"
            "    rm -f \"$DEV_FLOW_CODEX_CANDIDATE_ACTIVE\"\n"
            "    ;;\n"
            "  'plugin add dev-flow-orchestrator@personal')\n"
            "    printf '%s\\n' \"$*\" >> \"$DEV_FLOW_CODEX_LOG\"\n"
            "    if [ -n \"${DEV_FLOW_CODEX_ADD_FAIL_ONCE_FILE:-}\" ] && [ ! -f \"$DEV_FLOW_CODEX_ADD_FAIL_ONCE_FILE\" ]; then\n"
            "      : > \"$DEV_FLOW_CODEX_ADD_FAIL_ONCE_FILE\"\n"
            "      exit \"${DEV_FLOW_CODEX_ADD_FAIL_ONCE_EXIT:-17}\"\n"
            "    fi\n"
            "    exit_code=\"${DEV_FLOW_CODEX_ADD_EXIT:-0}\"\n"
            "    [ \"$exit_code\" -eq 0 ] || exit \"$exit_code\"\n"
            "    printf '%s\\n' \"${DEV_FLOW_PACKAGE_VERSION:-0.4.0}\" > \"$DEV_FLOW_CODEX_STATE\"\n"
            "    : > \"$DEV_FLOW_CODEX_CANDIDATE_ACTIVE\"\n"
            "    if [ -n \"${DEV_FLOW_CODEX_CORRUPT_LAUNCHER:-}\" ] && [ -n \"${DEV_FLOW_CODEX_CORRUPT_ONCE_FILE:-}\" ] && [ ! -f \"$DEV_FLOW_CODEX_CORRUPT_ONCE_FILE\" ]; then\n"
            "      : > \"$DEV_FLOW_CODEX_CORRUPT_ONCE_FILE\"\n"
            "      printf '#!/bin/sh\\nexit 44\\n' > \"$DEV_FLOW_CODEX_CORRUPT_LAUNCHER\"\n"
            "    fi\n"
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
                "DEV_FLOW_CODEX_LOG": str(self.codex_log),
                "DEV_FLOW_CODEX_STATE": str(self.codex_state),
                "DEV_FLOW_CODEX_CANDIDATE_ACTIVE": str(
                    self.codex_candidate_active
                ),
                "DEV_FLOW_CODEX_ADD_EXIT": "0",
                "DEV_FLOW_CODEX_REMOVE_EXIT": "0",
                "DEV_FLOW_CODEX_ENABLED_JSON": "true",
                "DEV_FLOW_ACTIVE_MCP_LIST_JSON": json.dumps(
                    [
                        {
                            "name": "dev-flow",
                            "enabled": True,
                            "disabled_reason": None,
                            "transport": {
                                "type": "stdio",
                                "command": "dev-flow-mcp",
                                "args": ["--stdio"],
                            },
                        }
                    ]
                ),
                "DEV_FLOW_PACKAGE_VERSION": PACKAGE_VERSION,
                "DEV_FLOW_BIN_DIR": str(fake_bin),
                "DEV_FLOW_RUNTIME_HOME": str(self.test_root / "managed runtime"),
                "CODEX_HOME": str(self.test_root / ".codex"),
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

    def set_installed_version(self, version: str) -> None:
        self.codex_state.write_text(version + "\n", encoding="utf-8")

    def write_codex_config(self, content: str) -> None:
        config = Path(self.environment["CODEX_HOME"]) / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(content, encoding="utf-8")

    def marketplace_plugins(self) -> list[object]:
        return json.loads(self.marketplace.read_text(encoding="utf-8"))["plugins"]

    def runtime_releases(self) -> tuple[Path, ...]:
        releases = Path(self.environment["DEV_FLOW_RUNTIME_HOME"]) / "releases"
        if not releases.is_dir():
            return ()
        return tuple(sorted(path for path in releases.iterdir() if path.is_dir()))

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
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        self.assertTrue(launcher.is_file())
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)
        launcher_text = launcher.read_text(encoding="utf-8")
        self.assertIn("# dev-flow-orchestrator managed launcher", launcher_text)
        self.assertIn(str(self.source_root / "scripts" / "dev_flow.py"), launcher_text)
        mcp_launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        self.assertTrue(mcp_launcher.stat().st_mode & stat.S_IXUSR)
        mcp_text = mcp_launcher.read_text(encoding="utf-8")
        self.assertIn("# dev-flow-orchestrator managed MCP launcher", mcp_text)
        self.assertNotIn("__DEV_FLOW_RUNTIME_PYTHON__", mcp_text)
        releases = self.runtime_releases()
        self.assertEqual(len(releases), 1)
        runtime_python = releases[0] / "venv" / "bin" / "python"
        self.assertIn(str(runtime_python), mcp_text)
        receipt = json.loads(
            (releases[0] / "runtime-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(receipt),
            {
                "activated_at",
                "activation_action",
                "dependency_lock_sha256",
                "launcher_identity",
                "python",
                "release_version",
                "runtime_identity",
                "schema",
                "source_commit",
            },
        )
        self.assertEqual(receipt["activation_action"], "create")

    def test_launcher_uses_automatic_codex_data_directory(self) -> None:
        self.install_successfully()
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"

        completed = subprocess.run(
            [str(launcher), "web", "status"],
            cwd=self.test_root,
            env=self.environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["status"], "stopped")
        expected = (
            Path(self.environment["CODEX_HOME"])
            / "plugins"
            / "data"
            / "dev-flow-orchestrator-personal"
            / "0.4.0"
        )
        self.assertFalse(expected.exists())

    def test_launcher_defaults_to_a_writable_directory_already_on_path(self) -> None:
        result = self.run_installer({"DEV_FLOW_BIN_DIR": ""})

        self.assertEqual(result.returncode, 0, result.stderr)
        path_directory = Path(self.environment["DEV_FLOW_BIN_DIR"])
        launcher = path_directory / "dev-flow"
        self.assertTrue(launcher.is_file())
        self.assertIn(str(launcher), result.stdout)

    def test_unowned_launcher_collision_stops_before_activation(self) -> None:
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        launcher.write_text("#!/bin/sh\necho user-owned\n", encoding="utf-8")
        launcher.chmod(0o755)

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not owned by Dev Flow", result.stderr)
        self.assertEqual(launcher.read_text(encoding="utf-8"), "#!/bin/sh\necho user-owned\n")
        self.assertEqual(self.activation_calls(), [])

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
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
        )

    def test_success_prints_receipt_and_touched_directories(self) -> None:
        result = self.install_successfully()

        self.assertIn("DEV FLOW ORCHESTRATOR", result.stdout)
        self.assertIn("// SYSTEM ONLINE", result.stdout)
        self.assertIn("CONTROL PLANE READY", result.stdout)
        self.assertIn("VERSION {}".format(PACKAGE_VERSION), result.stdout)
        self.assertIn("INSTALLATION RECEIPT", result.stdout)
        self.assertIn("dev-flow-orchestrator@personal", result.stdout)
        self.assertIn("ACTION     installed", result.stdout)
        self.assertIn("INSTALLED  {}".format(PACKAGE_VERSION), result.stdout)
        self.assertIn(str(self.source_root), result.stdout)
        self.assertIn(str(self.marketplace.parent), result.stdout)
        self.assertIn(str(self.test_root / ".codex"), result.stdout)
        self.assertIn("call dev_flow_server_info", result.stdout)
        self.assertNotIn("\x1b[", result.stdout)

    def test_success_uses_neon_colors_when_forced(self) -> None:
        result = self.run_installer({"DEV_FLOW_FORCE_COLOR": "1"})

        self.assertEqual(
            result.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr),
        )
        self.assertIn("\x1b[38;5;51m", result.stdout)
        self.assertIn("\x1b[38;5;213m", result.stdout)
        self.assertIn("\x1b[38;5;82m", result.stdout)
        self.assertIn("\x1b[0m", result.stdout)

    def test_no_color_disables_forced_neon_output(self) -> None:
        result = self.run_installer(
            {"DEV_FLOW_FORCE_COLOR": "1", "NO_COLOR": "1"}
        )

        self.assertEqual(
            result.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr),
        )
        self.assertNotIn("\x1b[", result.stdout)

    def test_older_installed_plugin_is_upgraded_automatically(self) -> None:
        self.set_installed_version("0.2.0")

        result = self.install_successfully()

        self.assertEqual(
            self.activation_calls(),
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
        )
        self.assertIn("ACTION     upgraded", result.stdout)
        self.assertIn("PREVIOUS   0.2.0", result.stdout)
        self.assertIn("INSTALLED  {}".format(PACKAGE_VERSION), result.stdout)
        self.assertEqual(
            self.codex_state.read_text(encoding="utf-8"),
            PACKAGE_VERSION + "\n",
        )

    def test_current_installed_plugin_is_repaired_automatically(self) -> None:
        self.set_installed_version(PACKAGE_VERSION)

        result = self.install_successfully()

        self.assertEqual(
            self.activation_calls(),
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
        )
        self.assertIn("ACTION     repaired", result.stdout)
        self.assertIn("PREVIOUS   {}".format(PACKAGE_VERSION), result.stdout)
        self.assertIn("INSTALLED  {}".format(PACKAGE_VERSION), result.stdout)

    def test_remove_failure_preserves_installed_plugin_and_stops(self) -> None:
        self.set_installed_version(PACKAGE_VERSION)

        result = self.run_installer({"DEV_FLOW_CODEX_REMOVE_EXIT": "19"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Finish or cancel active Dev Flow tasks", result.stderr)
        self.assertEqual(
            self.activation_calls(),
            ["plugin remove dev-flow-orchestrator@personal"],
        )
        self.assertEqual(
            self.codex_state.read_text(encoding="utf-8"),
            PACKAGE_VERSION + "\n",
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
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
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
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
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

    def test_duplicate_marketplace_entries_fail_without_editing_policy(self) -> None:
        duplicate = {
            "name": "dev-flow-orchestrator",
            "source": {"source": "local", "path": "./old"},
            "policy": {"installation": "MANUAL", "authentication": "NEVER"},
        }
        self.marketplace.parent.mkdir(parents=True)
        before = (
            json.dumps(
                {
                    "name": "personal",
                    "plugins": [duplicate, dict(duplicate)],
                    "unrelatedPolicy": {"keep": True},
                },
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        self.marketplace.write_bytes(before)

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate Dev Flow entries", result.stderr)
        self.assertEqual(self.marketplace.read_bytes(), before)
        self.assertFalse(
            (Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp").exists()
        )
        self.assertEqual(self.activation_calls(), [])

    def test_enabled_owned_standalone_registration_blocks_bundled_activation(self) -> None:
        registration = [
            {
                "name": "standalone-dev-flow",
                "enabled": True,
                "transport": {
                    "command": str(
                        Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
                    ),
                    "args": ["--stdio"],
                },
            }
        ]

        result = self.run_installer(
            {"DEV_FLOW_MCP_LIST_JSON": json.dumps(registration)}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertIn("disable or remove", result.stderr)
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_fresh_install_rejects_canonical_owned_standalone_registration(self) -> None:
        registration = json.loads(self.environment["DEV_FLOW_ACTIVE_MCP_LIST_JSON"])

        result = self.run_installer(
            {"DEV_FLOW_MCP_LIST_JSON": json.dumps(registration)}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_disabled_plugin_does_not_exempt_canonical_owned_registration(self) -> None:
        self.set_installed_version(PACKAGE_VERSION)

        result = self.run_installer({"DEV_FLOW_CODEX_ENABLED_JSON": "false"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_same_name_explicit_config_blocks_active_bundled_shape(self) -> None:
        self.set_installed_version(PACKAGE_VERSION)
        self.write_codex_config(
            '[plugins."dev-flow-orchestrator@personal"]\n'
            "enabled = true\n\n"
            "[mcp_servers.dev-flow]\n"
            'command = "dev-flow-mcp"\n'
            'args = ["--stdio"]\n'
        )

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit standalone Dev Flow MCP registration", result.stderr)
        self.assertIn("config.toml", result.stderr)
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_extra_name_standalone_blocks_active_bundled_repair(self) -> None:
        self.set_installed_version(PACKAGE_VERSION)
        registration = json.loads(self.environment["DEV_FLOW_ACTIVE_MCP_LIST_JSON"])
        registration.append(
            {
                "name": "legacy-dev-flow",
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": str(
                        Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
                    ),
                    "args": ["--stdio"],
                },
            }
        )

        result = self.run_installer(
            {"DEV_FLOW_MCP_LIST_JSON": json.dumps(registration)}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy-dev-flow", result.stderr)
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_missing_bundled_registration_after_activation_rolls_back(self) -> None:
        result = self.run_installer({"DEV_FLOW_ACTIVE_MCP_LIST_JSON": "[]"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bundled MCP registration is missing", result.stderr)
        self.assertEqual(
            self.activation_calls(),
            [
                "plugin add dev-flow-orchestrator@personal",
                "plugin remove dev-flow-orchestrator@personal",
            ],
        )
        self.assertFalse(self.marketplace.exists())
        self.assertFalse(
            (Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp").exists()
        )

    def test_disabled_bundled_registration_after_activation_rolls_back(self) -> None:
        registration = json.loads(self.environment["DEV_FLOW_ACTIVE_MCP_LIST_JSON"])
        registration[0]["enabled"] = False

        result = self.run_installer(
            {"DEV_FLOW_ACTIVE_MCP_LIST_JSON": json.dumps(registration)}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bundled MCP registration is missing", result.stderr)
        self.assertEqual(
            self.activation_calls(),
            [
                "plugin add dev-flow-orchestrator@personal",
                "plugin remove dev-flow-orchestrator@personal",
            ],
        )

    def test_unrelated_similarly_named_registration_is_not_edited(self) -> None:
        registration = [
            {
                "name": "dev-flow-metrics",
                "enabled": True,
                "transport": {
                    "command": str(self.test_root / "unrelated-dev-flow-metrics"),
                    "args": ["--stdio"],
                },
                "policy": {"operatorOwned": True},
            }
        ]

        result = self.run_installer(
            {"DEV_FLOW_MCP_LIST_JSON": json.dumps(registration)}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.activation_calls(), ["plugin add dev-flow-orchestrator@personal"]
        )

    def test_simulated_unsupported_python_refuses_before_source_or_runtime(self) -> None:
        fake_python = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "python3"
        fake_python.write_text("#!/bin/sh\nexit 39\n", encoding="utf-8")
        fake_python.chmod(0o755)

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("64-bit Python 3.10-3.14 is required", result.stderr)
        self.assertFalse(self.source_root.exists())
        self.assertFalse(Path(self.environment["DEV_FLOW_RUNTIME_HOME"]).exists())
        self.assertEqual(self.activation_calls(), [])

    def test_failed_runtime_build_preserves_previous_runtime_plugin_and_data(self) -> None:
        self.install_successfully()
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        launcher_before = launcher.read_bytes()
        marketplace_before = self.marketplace.read_bytes()
        releases_before = self.runtime_releases()
        data_root = (
            Path(self.environment["CODEX_HOME"])
            / "plugins"
            / "data"
            / "dev-flow-orchestrator-personal"
            / "0.4.0"
        )
        data_root.mkdir(parents=True)
        sentinel = data_root / "existing-task-bytes"
        sentinel.write_bytes(b"preserve exact task data\n")
        self.advance_remote_main()
        fake_uv = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "uv"
        fake_uv.write_text("#!/bin/sh\nexit 31\n", encoding="utf-8")
        fake_uv.chmod(0o755)
        self.clear_activation_calls()

        result = self.run_installer()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot build and validate the managed MCP runtime", result.stderr)
        self.assertEqual(launcher.read_bytes(), launcher_before)
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.runtime_releases(), releases_before)
        self.assertEqual(
            self.codex_state.read_text(encoding="utf-8"), PACKAGE_VERSION + "\n"
        )
        self.assertEqual(sentinel.read_bytes(), b"preserve exact task data\n")
        self.assertEqual(self.activation_calls(), [])

    def test_failed_upgrade_activation_restores_previous_launcher_and_plugin(self) -> None:
        self.install_successfully()
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        launcher_before = launcher.read_bytes()
        marketplace_before = self.marketplace.read_bytes()
        old_release = self.runtime_releases()[0]
        self.advance_remote_main()
        self.clear_activation_calls()
        fail_once = self.test_root / "candidate-add-failed-once"

        result = self.run_installer(
            {
                "DEV_FLOW_CODEX_ADD_FAIL_ONCE_FILE": str(fail_once),
                "DEV_FLOW_CODEX_ADD_FAIL_ONCE_EXIT": "17",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Previous plugin activation was restored", result.stderr)
        self.assertEqual(launcher.read_bytes(), launcher_before)
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertTrue(old_release.is_dir())
        self.assertEqual(
            self.codex_state.read_text(encoding="utf-8"), PACKAGE_VERSION + "\n"
        )
        self.assertEqual(
            self.activation_calls(),
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
        )

    def test_post_activation_mcp_failure_restores_previous_activation(self) -> None:
        self.install_successfully()
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        launcher_before = launcher.read_bytes()
        marketplace_before = self.marketplace.read_bytes()
        old_release = self.runtime_releases()[0]
        self.advance_remote_main()
        self.clear_activation_calls()

        result = self.run_installer(
            {
                "DEV_FLOW_CODEX_CORRUPT_LAUNCHER": str(launcher),
                "DEV_FLOW_CODEX_CORRUPT_ONCE_FILE": str(
                    self.test_root / "candidate-launcher-corrupted-once"
                ),
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("real installed launcher failed", result.stderr)
        self.assertIn("Previous plugin activation was restored", result.stderr)
        self.assertEqual(launcher.read_bytes(), launcher_before)
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertTrue(old_release.is_dir())
        self.assertEqual(
            self.codex_state.read_text(encoding="utf-8"), PACKAGE_VERSION + "\n"
        )
        self.assertEqual(
            self.activation_calls(),
            [
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
                "plugin remove dev-flow-orchestrator@personal",
                "plugin add dev-flow-orchestrator@personal",
            ],
        )

    def test_plugin_activation_failure_reports_rerun_guidance(self) -> None:
        result = self.run_installer({"DEV_FLOW_CODEX_ADD_EXIT": "17"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Plugin activation failed: Codex rejected the candidate plugin",
            result.stderr,
        )
        self.assertTrue(self.source_root.is_dir())
        self.assertEqual(
            self.activation_calls(),
            ["plugin add dev-flow-orchestrator@personal"],
        )
        self.assertFalse(self.marketplace.exists())
        self.assertFalse(
            (Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp").exists()
        )


if __name__ == "__main__":
    unittest.main()
