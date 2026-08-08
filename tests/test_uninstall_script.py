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
import hashlib
import platform
from typing import Mapping, Optional
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNINSTALLER = ROOT / "scripts" / "uninstall.sh"
CANONICAL_BUNDLED_MCP = {
    "name": "dev-flow",
    "enabled": True,
    "disabled_reason": None,
    "transport": {
        "type": "stdio",
        "command": "dev-flow-mcp",
        "args": ["--stdio"],
    },
}


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
            "  'mcp list --json')\n"
            "    if [ \"${DEV_FLOW_MCP_LIST_JSON+x}\" = x ]; then\n"
            "      printf '%s\\n' \"$DEV_FLOW_MCP_LIST_JSON\"\n"
            "    elif [ -f \"$DEV_FLOW_CODEX_STATE\" ]; then\n"
            "      printf '%s\\n' \"$DEV_FLOW_ACTIVE_MCP_LIST_JSON\"\n"
            "    else\n"
            "      printf '[]\\n'\n"
            "    fi\n"
            "    ;;\n"
            "  'plugin list --json')\n"
            "    if [ -f \"$DEV_FLOW_CODEX_STATE\" ]; then\n"
            "      printf '{\"installed\":[{\"pluginId\":\"dev-flow-orchestrator@personal\",\"installed\":true,\"enabled\":%s}]}\\n' \"${DEV_FLOW_CODEX_ENABLED_JSON:-true}\"\n"
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
                "DEV_FLOW_CODEX_ENABLED_JSON": "true",
                "DEV_FLOW_ACTIVE_MCP_LIST_JSON": json.dumps(
                    [CANONICAL_BUNDLED_MCP]
                ),
                "DEV_FLOW_BIN_DIR": str(fake_bin),
                "DEV_FLOW_RUNTIME_HOME": str(self.test_root / "managed runtime"),
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

    def write_codex_config(self, content: str) -> Path:
        config = self.codex_root / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(content, encoding="utf-8")
        return config

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

    def write_managed_runtime(self) -> Path:
        runtime_root = Path(self.environment["DEV_FLOW_RUNTIME_HOME"])
        runtime_root.mkdir(parents=True)
        (runtime_root / ".dev-flow-managed-runtime").write_text(
            "dev-flow-managed-runtime/1\n", encoding="utf-8"
        )
        commit = "a" * 40
        lock = "b" * 64
        release = runtime_root / "releases" / "0.5.0-{}-{}".format(
            commit[:12], lock[:12]
        )
        executable = release / "venv" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(Path(sys.executable).resolve())
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        receipt = {
            "schema": "dev-flow-runtime-receipt/1.0.0",
            "release_version": "0.5.0",
            "source_commit": commit,
            "python": {
                "executable_sha256": digest,
                "version": platform.python_version(),
                "architecture": platform.machine(),
                "bits": 64,
            },
            "dependency_lock_sha256": lock,
            "launcher_identity": "dev-flow-mcp --stdio",
            "runtime_identity": hashlib.sha256(
                os.path.normcase(str(release.resolve())).encode("utf-8")
            ).hexdigest(),
            "activation_action": "create",
            "activated_at": "2026-08-08T00:00:00Z",
        }
        (release / "runtime-receipt.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        return runtime_root

    def test_default_uninstall_removes_plugin_entry_and_clean_source(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        plugin_config = self.write_codex_config(
            '[plugins."dev-flow-orchestrator@personal"]\nenabled = true\n'
        )
        task_data = self.codex_root / "plugins" / "data" / "task.json"
        task_data.parent.mkdir(parents=True)
        task_data.write_text("preserve me\n", encoding="utf-8")
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        launcher.write_text(
            "#!/bin/sh\n# dev-flow-orchestrator managed launcher\nexit 0\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        mcp_launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        mcp_launcher.write_text(
            "#!/bin/sh\n# dev-flow-orchestrator managed MCP launcher\nexit 0\n",
            encoding="utf-8",
        )
        mcp_launcher.chmod(0o755)
        runtime_root = self.write_managed_runtime()

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
        self.assertEqual(
            plugin_config.read_text(encoding="utf-8"),
            '[plugins."dev-flow-orchestrator@personal"]\nenabled = true\n',
        )
        self.assertFalse(launcher.exists())
        self.assertFalse(mcp_launcher.exists())
        self.assertFalse(runtime_root.exists())
        self.assertIn("// SYSTEM OFFLINE", result.stdout)
        self.assertIn("UNINSTALL RECEIPT", result.stdout)
        self.assertIn("External Dev Flow task data", result.stdout)

    def test_uninstall_uses_the_same_path_directory_selection(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        launcher.write_text(
            "#!/bin/sh\n# dev-flow-orchestrator managed launcher\nexit 0\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)

        result = self.run_uninstaller(overrides={"DEV_FLOW_BIN_DIR": ""})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(launcher.exists())

    def test_unowned_launcher_is_preserved_and_blocks_uninstall(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        launcher.write_text("#!/bin/sh\necho user-owned\n", encoding="utf-8")
        launcher.chmod(0o755)

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not owned by Dev Flow", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(launcher.read_text(encoding="utf-8"), "#!/bin/sh\necho user-owned\n")
        self.assertEqual(self.activation_calls(), [])

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

    def test_mismatched_runtime_receipt_fails_closed_before_any_mutation(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        receipt = next(runtime_root.glob("releases/*/runtime-receipt.json"))
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["dependency_lock_sha256"] = "c" * 64
        receipt.write_text(json.dumps(value), encoding="utf-8")
        marketplace_before = self.marketplace.read_bytes()

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership receipt", result.stderr)
        self.assertTrue(runtime_root.exists())
        self.assertTrue(self.codex_state.exists())
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_enabled_standalone_owned_launcher_blocks_bundled_uninstall(self) -> None:
        self.write_marketplace()
        marketplace_before = self.marketplace.read_bytes()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        mcp_launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp"
        mcp_launcher.write_text(
            "#!/bin/sh\n# dev-flow-orchestrator managed MCP launcher\nexit 0\n",
            encoding="utf-8",
        )
        mcp_launcher.chmod(0o755)
        owned = str(Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow-mcp")
        registration = json.dumps(
            [
                CANONICAL_BUNDLED_MCP,
                {"name": "custom-name", "enabled": True, "command": owned},
            ]
        )

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_MCP_LIST_JSON": registration}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertTrue(runtime_root.exists())
        self.assertTrue(mcp_launcher.exists())
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_disabled_extra_owned_registration_blocks_bundled_uninstall(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        registration = json.dumps(
            [
                CANONICAL_BUNDLED_MCP,
                {
                    "name": "disabled-custom",
                    "enabled": False,
                    "command": "dev-flow-mcp",
                },
            ]
        )

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_MCP_LIST_JSON": registration}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no additional owned-launcher registrations", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_active_plugin_missing_canonical_registration_fails_closed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_MCP_LIST_JSON": "[]"}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one enabled canonical", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_disabled_plugin_with_canonical_registration_fails_closed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_CODEX_ENABLED_JSON": "false"}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_disabled_bundled_registration_fails_closed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        disabled = {
            **CANONICAL_BUNDLED_MCP,
            "enabled": False,
        }

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_MCP_LIST_JSON": json.dumps([disabled])}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly one enabled canonical", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_canonical_registration_without_installed_plugin_fails_closed(self) -> None:
        self.write_marketplace()

        result = self.run_uninstaller(
            overrides={
                "DEV_FLOW_MCP_LIST_JSON": json.dumps([CANONICAL_BUNDLED_MCP])
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone Dev Flow MCP registration", result.stderr)
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_explicit_same_name_standalone_config_blocks_bundled_uninstall(
        self,
    ) -> None:
        self.write_marketplace()
        marketplace_before = self.marketplace.read_bytes()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        config = self.write_codex_config(
            '[plugins."dev-flow-orchestrator@personal"]\n'
            'enabled = true\n\n'
            '[mcp_servers."dev-flow"]\n'
            'command = "dev-flow-mcp"\n'
            'args = ["--stdio"]\n'
        )
        config_before = config.read_bytes()

        result = self.run_uninstaller()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit standalone Dev Flow MCP registration", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertTrue(runtime_root.exists())
        self.assertEqual(config.read_bytes(), config_before)
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertEqual(self.activation_calls(), [])

    def test_duplicate_canonical_bundled_registrations_fail_closed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")

        result = self.run_uninstaller(
            overrides={
                "DEV_FLOW_MCP_LIST_JSON": json.dumps(
                    [CANONICAL_BUNDLED_MCP, CANONICAL_BUNDLED_MCP]
                )
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no additional owned-launcher registrations", result.stderr)
        self.assertTrue(self.codex_state.exists())
        self.assertTrue(self.source_root.exists())
        self.assertEqual(self.activation_calls(), [])

    def test_unrelated_similarly_named_registration_is_preserved(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        managed_runtime = self.write_managed_runtime()
        unrelated_runtime = self.test_root / "other product" / "runtime"
        unrelated_runtime.mkdir(parents=True)
        unrelated_server = unrelated_runtime / "other-server"
        unrelated_server.write_text("preserve me\n", encoding="utf-8")
        registration = json.dumps(
            [
                CANONICAL_BUNDLED_MCP,
                {
                    "name": "dev-flow",
                    "enabled": True,
                    "command": str(unrelated_server),
                },
            ]
        )

        result = self.run_uninstaller(
            "--keep-source", overrides={"DEV_FLOW_MCP_LIST_JSON": registration}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preserved / no owned registration removed", result.stdout)
        self.assertFalse(self.codex_state.exists())
        self.assertFalse(managed_runtime.exists())
        self.assertEqual(unrelated_server.read_text(encoding="utf-8"), "preserve me\n")
        self.assertEqual(
            self.activation_calls(),
            ["plugin remove dev-flow-orchestrator@personal"],
        )

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
