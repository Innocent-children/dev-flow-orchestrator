"""Black-box coverage for the public macOS uninstaller."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import hashlib
import platform
from typing import Mapping, Optional
import unittest


ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

from support import (
    assert_hermetic_subprocess_env,
    hermetic_subprocess_env,
    probe_subprocess_runtime_roots,
)

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
    if cwd is not None:
        isolation_root = cwd.resolve()
    else:
        absolute = next(
            (Path(value) for value in arguments if Path(value).is_absolute()),
            None,
        )
        if absolute is None:
            raise AssertionError("fixture Git command has no temporary path authority")
        isolation_root = absolute.resolve().parent
    completed = subprocess.run(
        [
            "git",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            *arguments,
        ],
        cwd=cwd,
        env=hermetic_subprocess_env(isolation_root),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _configure_identity(repository: Path) -> None:
    _git("config", "user.name", "Uninstaller Test", cwd=repository)
    _git("config", "user.email", "uninstaller-test@example.invalid", cwd=repository)


def _tree_snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    """Capture paths, types, modes, link targets, and file bytes without following links."""

    entries: list[tuple[object, ...]] = []

    def visit(path: Path, relative: str) -> None:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            entries.append((relative, "symlink", mode, os.readlink(path)))
            return
        if stat.S_ISDIR(metadata.st_mode):
            entries.append((relative, "directory", mode))
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                child_relative = child.name if not relative else f"{relative}/{child.name}"
                visit(child, child_relative)
            return
        entries.append((relative, "file", mode, path.read_bytes()))

    visit(root, "")
    return tuple(entries)


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
        self.runtime_external_target = self.test_root / "external runtime target.bin"
        self.runtime_external_target.write_bytes(b"external runtime target\x00\xff")
        self.runtime_external_target.chmod(0o755)

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
            "    if [ -n \"${DEV_FLOW_CODEX_CREATE_SOURCE_FILE:-}\" ]; then\n"
            "      printf 'created during plugin removal\\n' > \"$DEV_FLOW_CODEX_CREATE_SOURCE_FILE\"\n"
            "    fi\n"
            "    if [ -n \"${DEV_FLOW_CODEX_CREATE_RUNTIME_FILE:-}\" ]; then\n"
            "      printf 'created during plugin removal\\n' > \"$DEV_FLOW_CODEX_CREATE_RUNTIME_FILE\"\n"
            "    fi\n"
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

        self.environment = hermetic_subprocess_env(
            self.test_root,
            path_entries=(fake_bin,),
            overrides={
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
            },
        )
        for authority in (
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "XDG_DATA_HOME",
            "CODEX_HOME",
            "DEV_FLOW_DATA_DIR",
            "PLUGIN_DATA",
            "DEV_FLOW_RUNTIME_HOME",
            "DEV_FLOW_SOURCE_ROOT",
            "DEV_FLOW_MARKETPLACE_FILE",
            "DEV_FLOW_BIN_DIR",
        ):
            Path(self.environment[authority]).resolve().relative_to(
                self.test_root.resolve()
            )
        self.assertEqual(
            Path(self.environment["PATH"].split(os.pathsep)[0]).resolve(),
            fake_bin.resolve(),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_marketplace(self, *, include_dev_flow: bool = True) -> None:
        plugins: list[object] = [
            {
                "name": "other-plugin",
                "source": {"source": "local", "path": "./plugins/other"},
                "opaque": {"bytes-as-text": "00ff", "label": "保留"},
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
        assert_hermetic_subprocess_env(self.test_root, environment)
        probe_subprocess_runtime_roots(self.test_root, environment)
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

    def assert_source_containment_receipt(
        self,
        result: subprocess.CompletedProcess[str],
        expected_path: Path,
    ) -> None:
        self.assertIn("OUTCOME", result.stdout)
        self.assertIn("partial", result.stdout)
        self.assertIn("SOURCE", result.stdout)
        self.assertIn("retained (destructive removal disabled)", result.stdout)
        self.assertIn("SOURCE PATH", result.stdout)
        self.assertIn(str(expected_path.absolute()), result.stdout)
        self.assertIn(
            "destructive removal disabled: no verifiable exact-ownership manifest",
            result.stdout,
        )
        self.assertIn("TASK DATA", result.stdout)
        self.assertIn("preserved", result.stdout)
        self.assertIn("MANUAL ACTION", result.stdout)
        self.assertIn("Inspect and back up", result.stdout)
        self.assertIn("independently confirm ownership", result.stdout)
        self.assertNotIn("SOURCE       removed", result.stdout)

    def write_managed_runtime(self) -> Path:
        runtime_root = Path(self.environment["DEV_FLOW_RUNTIME_HOME"])
        runtime_root.mkdir(parents=True)
        (runtime_root / ".dev-flow-managed-runtime").write_text(
            "dev-flow-managed-runtime/1\n", encoding="utf-8"
        )
        self.write_managed_release(runtime_root, "r-test-owned-release")
        return runtime_root

    def write_managed_release(self, runtime_root: Path, release_id: str) -> Path:
        release = runtime_root / "releases" / release_id
        executable = release / "venv" / "bin" / "python"
        executable.parent.mkdir(parents=True)
        executable.symlink_to(self.runtime_external_target.resolve())
        site_packages = (
            release
            / "venv"
            / "lib"
            / "python{}.{}".format(sys.version_info.major, sys.version_info.minor)
            / "site-packages"
        )
        (site_packages / "dev_flow_orchestrator").mkdir(parents=True)
        (site_packages / "dev_flow_orchestrator-0.5.0.dist-info").mkdir()
        plugin = release / "plugin"
        plugin.mkdir()
        (plugin / "payload.txt").write_bytes(b"owned plugin payload\n")
        physical_release = release.resolve()

        entries: list[dict[str, object]] = [
            {
                "path": ".",
                "type": "directory",
                "mode": stat.S_IMODE(release.lstat().st_mode),
                "release_id": release_id,
            }
        ]
        for path in sorted(release.rglob("*"), key=lambda item: item.as_posix()):
            metadata = path.lstat()
            entry: dict[str, object] = {
                "path": path.relative_to(release).as_posix(),
                "mode": stat.S_IMODE(metadata.st_mode),
                "release_id": release_id,
            }
            if stat.S_ISLNK(metadata.st_mode):
                entry.update({"type": "symlink", "target": os.readlink(path)})
            elif stat.S_ISDIR(metadata.st_mode):
                entry["type"] = "directory"
            elif stat.S_ISREG(metadata.st_mode):
                entry.update(
                    {
                        "type": "file",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
            else:
                raise AssertionError("fixture produced an unsupported owned entry")
            entries.append(entry)
        entries.sort(key=lambda item: str(item["path"]))
        ownership = {
            "schema": "dev-flow-runtime-ownership/1.0.0",
            "release_id": release_id,
            "entries": entries,
        }
        ownership_path = release / "ownership-manifest.json"
        ownership_path.write_text(
            json.dumps(ownership, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        ownership_digest = hashlib.sha256(ownership_path.read_bytes()).hexdigest()
        receipt = {
            "schema": "dev-flow-runtime-receipt/2.0.0",
            "release_id": release_id,
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "wheel_sha256": "c" * 64,
            "plugin_path": str(physical_release / "plugin"),
            "plugin_release_manifest_sha256": "d" * 64,
            "dev_flow": {
                "name": "dev-flow-orchestrator",
                "version": "0.5.0",
                "metadata_sha256": "e" * 64,
                "record_sha256": "f" * 64,
                "files": [],
            },
            "dependencies": [],
            "python": {
                "path": str(physical_release / "venv" / "bin" / "python"),
                "executable_sha256": hashlib.sha256(
                    executable.resolve().read_bytes()
                ).hexdigest(),
                "version": platform.python_version(),
                "architecture": platform.machine(),
                "bits": 64,
            },
            "runtime_path": str(physical_release),
            "launcher_sha256": "1" * 64,
            "ownership_manifest_sha256": ownership_digest,
            "dependency_lock_sha256": "2" * 64,
            "created_at": "2026-08-08T00:00:00Z",
        }
        (release / "runtime-receipt.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        return release

    def test_default_uninstall_reports_partial_and_retains_clean_source(self) -> None:
        self.write_marketplace()
        unrelated_before = json.loads(
            self.marketplace.read_text(encoding="utf-8")
        )["plugins"][0]
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
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(
            result.returncode,
            0,
            "stdout:\n{}\nstderr:\n{}".format(result.stdout, result.stderr),
        )
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertFalse(self.codex_state.exists())
        self.assertEqual(
            self.activation_calls(),
            ["plugin remove dev-flow-orchestrator@personal"],
        )
        plugins = json.loads(self.marketplace.read_text(encoding="utf-8"))[
            "plugins"
        ]
        self.assertEqual(plugins, [unrelated_before])
        self.assertEqual(task_data.read_text(encoding="utf-8"), "preserve me\n")
        self.assertEqual(
            plugin_config.read_text(encoding="utf-8"),
            '[plugins."dev-flow-orchestrator@personal"]\nenabled = true\n',
        )
        self.assertFalse(launcher.exists())
        self.assertFalse(mcp_launcher.exists())
        self.assertFalse(runtime_root.exists())
        self.assertEqual(
            self.runtime_external_target.read_bytes(),
            b"external runtime target\x00\xff",
        )
        self.assertIn(
            "MCP RUNTIME  removed (exact ownership manifest)", result.stdout
        )
        self.assert_source_containment_receipt(result, self.source_root)
        self.assertIn("// SYSTEM OFFLINE", result.stdout)
        self.assertIn("UNINSTALL RECEIPT", result.stdout)
        self.assertIn("External Dev Flow task data", result.stdout)

    def test_unknown_entries_across_runtime_scopes_are_retained_exactly(
        self,
    ) -> None:
        self.write_marketplace()
        marketplace = json.loads(self.marketplace.read_text(encoding="utf-8"))
        unrelated_before = json.dumps(
            marketplace["plugins"][0],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.codex_state.write_text("installed\n", encoding="utf-8")
        task_data = self.codex_root / "plugins" / "data" / "task.bin"
        task_data.parent.mkdir(parents=True)
        task_data.write_bytes(b"task sentinel\x00\xff")
        task_before = task_data.read_bytes()
        source_before = _tree_snapshot(self.source_root)
        external_before = self.runtime_external_target.read_bytes()

        runtime_root = self.write_managed_runtime()
        active_release = runtime_root / "releases" / "r-test-owned-release"
        inactive_release = self.write_managed_release(
            runtime_root, "r-test-inactive-release"
        )
        site_packages = (
            active_release
            / "venv"
            / "lib"
            / "python{}.{}".format(sys.version_info.major, sys.version_info.minor)
            / "site-packages"
        )
        unknown_entries = {
            runtime_root / "runtime-root-extra.bin": b"runtime root\x00\xff",
            active_release / "active-release-extra.bin": b"active release\x00\xff",
            inactive_release / "inactive-release-extra.bin": b"inactive release\x00\xff",
            active_release / "venv" / "venv-extra.bin": b"venv\x00\xff",
            site_packages / "site-packages-extra.py": b"site packages\x00\xff",
            active_release / "venv" / "bin" / "bin-extra": b"bin\x00\xff",
            site_packages
            / "dev_flow_orchestrator-0.5.0.dist-info"
            / "metadata-extra.bin": b"metadata\x00\xff",
        }
        for path, content in unknown_entries.items():
            path.write_bytes(content)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "MCP RUNTIME  partial (unknown or changed content retained)",
            result.stdout,
        )
        for path, content in unknown_entries.items():
            with self.subTest(path=path):
                self.assertEqual(path.read_bytes(), content)
        self.assertIn(str(runtime_root.resolve()), result.stdout)
        self.assertIn(str(inactive_release.resolve()), result.stdout)
        self.assertIn(str((active_release / "venv").resolve()), result.stdout)
        self.assertFalse((active_release / "plugin" / "payload.txt").exists())
        self.assertFalse((inactive_release / "plugin" / "payload.txt").exists())
        self.assertEqual(task_data.read_bytes(), task_before)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertEqual(self.runtime_external_target.read_bytes(), external_before)
        unrelated_after = json.dumps(
            json.loads(self.marketplace.read_text(encoding="utf-8"))["plugins"][0],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(unrelated_after, unrelated_before)

    def test_changed_known_owned_file_is_retained_without_deleting_neighbors(
        self,
    ) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        release = runtime_root / "releases" / "r-test-owned-release"
        replaced = release / "plugin" / "payload.txt"
        replaced.write_bytes(b"user replacement\x00\xff")
        external_before = self.runtime_external_target.read_bytes()

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(replaced.read_bytes(), b"user replacement\x00\xff")
        self.assertTrue((release / "runtime-receipt.json").is_file())
        self.assertTrue((release / "ownership-manifest.json").is_file())
        self.assertFalse((release / "venv" / "bin" / "python").exists())
        self.assertEqual(self.runtime_external_target.read_bytes(), external_before)
        self.assertIn(
            "MCP RUNTIME  partial (unknown or changed content retained)",
            result.stdout,
        )
        self.assertIn(str(replaced.resolve()), result.stdout)

    def test_unknown_symlink_and_external_target_are_retained_without_following(
        self,
    ) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        release = runtime_root / "releases" / "r-test-owned-release"
        external_target = self.test_root / "external symlink target.bin"
        external_target.write_bytes(b"external symlink target\x00\xff")
        external_before = external_target.read_bytes()
        unknown_link = release / "plugin" / "user-link"
        unknown_link.symlink_to(external_target.resolve())
        link_target = os.readlink(unknown_link)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(unknown_link.is_symlink())
        self.assertEqual(os.readlink(unknown_link), link_target)
        self.assertEqual(external_target.read_bytes(), external_before)
        self.assertFalse((release / "plugin" / "payload.txt").exists())
        self.assertIn(
            "MCP RUNTIME  partial (unknown or changed content retained)",
            result.stdout,
        )

    def test_unknown_fifo_and_socket_are_retained_when_supported(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        fifo_path = runtime_root / "f"
        os.mkfifo(fifo_path)
        socket_path = runtime_root / "s"
        unix_socket: Optional[socket.socket] = None
        socket_supported = False
        try:
            unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            unix_socket.bind(str(socket_path))
            socket_supported = True

            result = self.run_uninstaller()

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(stat.S_ISFIFO(fifo_path.lstat().st_mode))
            if socket_supported:
                self.assertTrue(stat.S_ISSOCK(socket_path.lstat().st_mode))
            self.assertIn(
                "MCP RUNTIME  partial (unknown or changed content retained)",
                result.stdout,
            )
        finally:
            if unix_socket is not None:
                unix_socket.close()

    def test_runtime_file_created_during_plugin_removal_is_retained(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        late_file = runtime_root / "arrived-during-plugin-removal.bin"

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_CODEX_CREATE_RUNTIME_FILE": str(late_file)}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            late_file.read_bytes(), b"created during plugin removal\n"
        )
        self.assertTrue(runtime_root.is_dir())
        self.assertIn(str(late_file.resolve()), result.stdout)
        self.assertIn(
            "MCP RUNTIME  partial (unknown or changed content retained)",
            result.stdout,
        )

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

    def test_keep_source_allows_local_work_and_reports_common_containment(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        local_file = self.source_root / "local work.txt"
        local_file.write_text("preserve me\n", encoding="utf-8")
        task_data = self.codex_root / "plugins" / "data" / "task.json"
        task_data.parent.mkdir(parents=True)
        task_data.write_bytes(b"task bytes\x00\xff")
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller("--keep-source")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertEqual(local_file.read_text(encoding="utf-8"), "preserve me\n")
        self.assertEqual(task_data.read_bytes(), b"task bytes\x00\xff")
        self.assert_source_containment_receipt(result, self.source_root)
        self.assertFalse(self.codex_state.exists())

    def test_untracked_source_work_is_retained_while_other_components_proceed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        local_file = self.source_root / "local work.txt"
        local_file.write_text(
            "preserve me\n", encoding="utf-8"
        )
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertEqual(local_file.read_text(encoding="utf-8"), "preserve me\n")
        self.assertFalse(self.codex_state.exists())
        self.assert_source_containment_receipt(result, self.source_root)

    def test_ignored_source_path_is_retained_while_other_components_proceed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        ignored_name = "ignored-local-data.txt"
        (self.source_root / ".git" / "info" / "exclude").write_text(
            "/{}\n".format(ignored_name), encoding="utf-8"
        )
        (self.source_root / ignored_name).write_text(
            "preserve me\n", encoding="utf-8"
        )
        self.assertEqual(_git("status", "--porcelain", cwd=self.source_root), "")
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertFalse(self.codex_state.exists())
        self.assert_source_containment_receipt(result, self.source_root)

    def test_local_only_commit_is_retained_while_other_components_proceed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        _configure_identity(self.source_root)
        local_file = self.source_root / "local-commit.txt"
        local_file.write_text("preserve me\n", encoding="utf-8")
        _git("add", "local-commit.txt", cwd=self.source_root)
        _git("commit", "-m", "local commit", cwd=self.source_root)
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertFalse(self.codex_state.exists())
        self.assert_source_containment_receipt(result, self.source_root)

    def test_tracked_modification_is_retained_while_other_components_proceed(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        manifest = self.source_root / ".codex-plugin" / "plugin.json"
        manifest.write_bytes(manifest.read_bytes() + b"\nuser edit\n")
        source_before = _tree_snapshot(self.source_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(self.source_root), source_before)
        self.assertFalse(self.codex_state.exists())
        self.assert_source_containment_receipt(result, self.source_root)

    def test_file_created_during_plugin_removal_is_retained(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        late_file = self.source_root / "arrived-during-plugin-removal.txt"

        result = self.run_uninstaller(
            overrides={"DEV_FLOW_CODEX_CREATE_SOURCE_FILE": str(late_file)}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            late_file.read_text(encoding="utf-8"),
            "created during plugin removal\n",
        )
        self.assertTrue(self.source_root.is_dir())
        self.assert_source_containment_receipt(result, self.source_root)

    def test_source_symlink_and_target_are_retained_without_canonicalization(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        shutil.rmtree(self.source_root)
        user_checkout = self.test_root / "user checkout outside marketplace"
        user_checkout.mkdir()
        user_file = user_checkout / "user work.bin"
        user_file.write_bytes(b"preserve\x00me\xff")
        self.source_root.symlink_to(user_checkout, target_is_directory=True)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.source_root.is_symlink())
        self.assertEqual(os.readlink(self.source_root), str(user_checkout))
        self.assertEqual(user_file.read_bytes(), b"preserve\x00me\xff")
        self.assert_source_containment_receipt(result, self.source_root)

    def test_unknown_remove_source_fails_before_any_mutation(self) -> None:
        self.write_marketplace()
        self.codex_state.write_text("installed\n", encoding="utf-8")
        launcher = Path(self.environment["DEV_FLOW_BIN_DIR"]) / "dev-flow"
        launcher.write_text(
            "#!/bin/sh\n# dev-flow-orchestrator managed launcher\nexit 0\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        self.write_managed_runtime()
        probe_subprocess_runtime_roots(self.test_root, self.environment)
        before = _tree_snapshot(self.test_root)

        result = self.run_uninstaller("--remove-source")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown argument '--remove-source'", result.stderr)
        self.assertEqual(_tree_snapshot(self.test_root), before)
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

    def test_mismatched_runtime_receipt_fails_closed_before_any_mutation(
        self,
    ) -> None:
        """Keep the historical selector while asserting current retained/partial safety."""
        self.write_marketplace()
        unrelated_before = json.loads(
            self.marketplace.read_text(encoding="utf-8")
        )["plugins"][0]
        self.codex_state.write_text("installed\n", encoding="utf-8")
        runtime_root = self.write_managed_runtime()
        receipt = next(runtime_root.glob("releases/*/runtime-receipt.json"))
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["schema"] = "dev-flow-runtime-receipt/1.0.0"
        receipt.write_text(json.dumps(value), encoding="utf-8")
        receipt.with_name("ownership-manifest.json").unlink()
        runtime_before = _tree_snapshot(runtime_root)

        result = self.run_uninstaller()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_tree_snapshot(runtime_root), runtime_before)
        self.assertFalse(self.codex_state.exists())
        self.assertEqual(
            json.loads(self.marketplace.read_text(encoding="utf-8"))["plugins"],
            [unrelated_before],
        )
        self.assertEqual(
            self.activation_calls(),
            ["plugin remove dev-flow-orchestrator@personal"],
        )
        self.assertIn(
            "MCP RUNTIME  retained (legacy, missing, or mismatched exact ownership)",
            result.stdout,
        )
        self.assertIn(str(runtime_root.resolve()), result.stdout)

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


class RuntimeDeletionContainmentStaticTests(unittest.TestCase):
    def test_uninstallers_never_recursively_delete_managed_runtime_roots(self) -> None:
        posix = UNINSTALLER.read_text(encoding="utf-8")
        runtime_integrity = (ROOT / "scripts" / "runtime_integrity.py").read_text(
            encoding="utf-8"
        )
        powershell = (ROOT / "scripts" / "uninstall.ps1").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('rm -rf -- "$RUNTIME_ROOT"', posix)
        self.assertNotIn('rm -rf "$RUNTIME_ROOT"', posix)
        self.assertNotRegex(
            posix,
            r'(?m)^\s*rm\b[^\n]*(?:-[^\s]*[rR][^\s]*|--recursive)[^\n]*RUNTIME_ROOT',
        )
        self.assertNotIn(
            "Remove-Item -LiteralPath $RuntimeRoot -Recurse",
            powershell,
        )
        self.assertNotIn("shutil.rmtree", posix)
        self.assertNotIn("shutil.rmtree", runtime_integrity)
        self.assertNotIn("shutil.rmtree", powershell)


if __name__ == "__main__":
    unittest.main()
