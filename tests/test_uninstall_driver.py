"""Focused simulated evidence for durable source-independent uninstall."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import lifecycle_state
from scripts import render_dispatchers
from scripts import stable_dispatcher
from scripts import uninstall_driver


def _json(path: Path, value: object) -> bytes:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class _Crash(BaseException):
    pass


class FakeHost:
    def __init__(self, evidence: uninstall_driver.InstallationEvidence) -> None:
        self.evidence = evidence
        self.events: list[str] = []
        self.plugin_installed = True
        self.fail_plugin = False
        self.marketplace = uninstall_driver.CodexHostRemoval(
            evidence, lifecycle_state
        )

    def preflight(self, active):
        return uninstall_driver.RemovalEvidence(
            active is not None,
            (
                lifecycle_state.ExternalObservation(
                    "uninstall-host-identity",
                    "exact" if active is not None else "changed",
                ),
            ),
            retained_paths=()
            if active is not None
            else (str(self.evidence.runtime_root),),
        )

    def remove_plugin(self, active):
        self.events.append("plugin")
        if self.fail_plugin:
            return uninstall_driver.RemovalEvidence(
                False,
                (
                    lifecycle_state.ExternalObservation(
                        "codex-plugin", "unknown", detail="injected observation failure"
                    ),
                ),
                recovery=("Inspect the plugin before retrying.",),
            )
        applied = self.plugin_installed
        self.plugin_installed = False
        return uninstall_driver.RemovalEvidence(
            True,
            (lifecycle_state.ExternalObservation("codex-plugin", "absent"),),
            (
                lifecycle_state.ProvisionalEffect(
                    "plugin",
                    uninstall_driver.PLUGIN_ID,
                    "a" * 64 if applied else None,
                    None,
                    applied,
                ),
            ),
            removed_count=int(applied),
        )

    def remove_marketplace(self, active):
        self.events.append("marketplace")
        return self.marketplace.remove_marketplace(active)


class UninstallDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="Dev Flow uninstall root's 数据 "
        )
        self.base = Path(self.temporary.name).resolve()
        self.runtime = self.base / "managed runtime's 数据"
        self.releases = self.runtime / "releases"
        self.lifecycle = self.runtime / "lifecycle"
        self.bin_dir = self.base / "bin dir's 工具"
        self.driver_temp = self.base / "copied helper's 临时"
        for path in (
            self.releases,
            self.lifecycle,
            self.bin_dir,
            self.driver_temp,
        ):
            path.mkdir(parents=True)

        self.release = self.releases / "release-1"
        plugin = self.release / "plugin"
        plugin.mkdir(parents=True)
        payload = plugin / "payload.txt"
        payload.write_bytes(b"owned payload\n")
        payload_link = plugin / "payload-link"
        if os.name != "nt":
            payload_link.symlink_to("payload.txt")
        entries = [
            {
                "path": ".",
                "type": "directory",
                "mode": stat.S_IMODE(self.release.lstat().st_mode),
                "release_id": self.release.name,
            },
            {
                "path": "plugin",
                "type": "directory",
                "mode": stat.S_IMODE(plugin.lstat().st_mode),
                "release_id": self.release.name,
            },
            {
                "path": "plugin/payload.txt",
                "type": "file",
                "mode": stat.S_IMODE(payload.lstat().st_mode),
                "release_id": self.release.name,
                "sha256": _sha(payload.read_bytes()),
            },
        ]
        if os.name != "nt":
            entries.insert(
                2,
                {
                    "path": "plugin/payload-link",
                    "type": "symlink",
                    "mode": stat.S_IMODE(payload_link.lstat().st_mode),
                    "release_id": self.release.name,
                    "target": "payload.txt",
                },
            )
        ownership_raw = _json(
            self.release / "ownership-manifest.json",
            {
                "schema": uninstall_driver.OWNERSHIP_SCHEMA,
                "release_id": self.release.name,
                "entries": entries,
            },
        )
        receipt_raw = _json(
            self.release / "runtime-receipt.json",
            {
                "schema": uninstall_driver.ARTIFACT_RUNTIME_RECEIPT_SCHEMA,
                "release_id": self.release.name,
                "version": "1.0.0",
                "repository": "Innocent-children/dev-flow-orchestrator",
                "source_commit": "a" * 40,
                "source_tree": "b" * 40,
                "release_index_sha256": "1" * 64,
                "archive_sha256": "2" * 64,
                "artifact_manifest_sha256": "3" * 64,
                "wheel_sha256": "4" * 64,
                "runtime_requirements_sha256": "5" * 64,
                "uv_lock_sha256": "6" * 64,
                "plugin_path": str(self.release / "plugin"),
                "plugin_release_manifest_sha256": "7" * 64,
                "dev_flow": {},
                "dependencies": [],
                "python": {},
                "python_executable_sha256": "8" * 64,
                "runtime_path": str(self.release),
                "transaction_id": "install-authority",
                "verifier_sha256": "9" * 64,
                "lifecycle_helpers": [],
                "ownership_manifest_sha256": _sha(ownership_raw),
                "created_at": "2026-01-01T00:00:00Z",
            },
        )
        self.receipt_sha256 = _sha(receipt_raw)

        lifecycle_payloads = {
            "stable_dispatcher.py": b"# stable dispatcher\n",
            "lifecycle_state.py": (ROOT / "scripts/lifecycle_state.py").read_bytes(),
            "uninstall_driver.py": b"# copied removal driver\n",
            "release_commands.py": b"# release commands\n",
            "release_resolver.py": b"# release resolver\n",
        }
        for name, raw in lifecycle_payloads.items():
            (self.lifecycle / name).write_bytes(raw)

        self.data_root = self.base / "task data root's 保留"
        self.data_root.mkdir()
        (self.data_root / "0.4.0").mkdir()
        self.task_file = self.data_root / "0.4.0" / "tasks.json"
        self.task_file.write_text('{"task":"keep"}\n', encoding="utf-8")
        (self.data_root / "web-runtime").mkdir()
        (self.data_root / "web-runtime" / "server.log").write_text(
            "web log\n", encoding="utf-8"
        )
        marker = {
            "schema": "dev-flow-data-ownership/1.0.0",
            "product": uninstall_driver.PLUGIN_NAME,
            "data_root": str(self.data_root),
            "namespace": uninstall_driver.DATA_NAMESPACE,
            "web_runtime": uninstall_driver.WEB_RUNTIME_DIR,
        }
        _json(self.data_root / uninstall_driver.DATA_MARKER_NAME, marker)
        self.data_before = {
            str(path.relative_to(self.data_root)): path.read_bytes()
            for path in sorted(self.data_root.rglob("*"))
            if path.is_file()
        }

        suffix = ".cmd" if os.name == "nt" else ""
        self.dispatcher_payloads = {
            f"dev-flow{suffix}": b"stable cli\n",
            f"dev-flow-mcp{suffix}": b"stable mcp\n",
            f"dev-flow-uninstall{suffix}": b"stable uninstall\n",
        }
        for name, raw in self.dispatcher_payloads.items():
            (self.bin_dir / name).write_bytes(raw)

        self.marketplace = self.base / ".agents" / "plugins" / "marketplace.json"
        self.codex_home = self.base / "isolated Codex home"
        self.codex_home.mkdir()
        _json(
            self.marketplace,
            {
                "plugins": [
                    {
                        "name": uninstall_driver.PLUGIN_NAME,
                        "source": {
                            "source": "local",
                            "path": str(self.release / "plugin"),
                        },
                        "policy": {
                            "installation": "AVAILABLE",
                            "authentication": "ON_INSTALL",
                        },
                        "category": "Productivity",
                    },
                    {
                        "name": "unrelated-plugin",
                        "source": {"source": "git", "url": "https://example.invalid/x"},
                    },
                ]
            },
        )
        installation_raw = _json(
            self.lifecycle / "installation.json",
            {
                "schema": uninstall_driver.INSTALLATION_SCHEMA,
                "dispatcher_protocol": uninstall_driver.DISPATCHER_PROTOCOL,
                "uninstall_driver_sha256": _sha(
                    lifecycle_payloads["uninstall_driver.py"]
                ),
                "stable_dispatcher_sha256": _sha(
                    lifecycle_payloads["stable_dispatcher.py"]
                ),
                "lifecycle_state_sha256": _sha(
                    lifecycle_payloads["lifecycle_state.py"]
                ),
                "release_commands_sha256": _sha(
                    lifecycle_payloads["release_commands.py"]
                ),
                "release_resolver_sha256": _sha(
                    lifecycle_payloads["release_resolver.py"]
                ),
                "dispatchers": {
                    name: _sha(raw)
                    for name, raw in sorted(self.dispatcher_payloads.items())
                },
                "bin_dir": str(self.bin_dir),
                "marketplace_file": str(self.marketplace),
                "codex_home": str(self.codex_home),
                "plugin_id": uninstall_driver.PLUGIN_ID,
                "runtime_root": str(self.runtime),
                "data_root": str(self.data_root),
                "data_owned_paths": [
                    uninstall_driver.DATA_NAMESPACE,
                    uninstall_driver.WEB_RUNTIME_DIR,
                ],
                "data_marker_name": uninstall_driver.DATA_MARKER_NAME,
            },
        )
        self.evidence, observed_installation = uninstall_driver.load_installation(
            self.runtime, self.bin_dir, self.driver_temp
        )
        self.assertEqual(observed_installation, installation_raw)

        self.state = lifecycle_state.LifecycleState(self.runtime, self.releases)
        with self.state.lock() as token:
            empty = self.state.read_active(token)
            self.active = self.state.compare_and_set_active(
                token,
                empty,
                release_id=self.release.name,
                release_path=self.release,
                receipt_sha256=self.receipt_sha256,
                dispatcher_protocol=lifecycle_state.DISPATCHER_PROTOCOL,
                transaction_id="install-authority",
            )

        self.task_data = self.base / "controller task data" / "task.json"
        self.task_data.parent.mkdir()
        self.task_data.write_text("keep task data", encoding="utf-8")
        self.legacy_checkout = self.base / "legacy checkout" / ".git" / "HEAD"
        self.legacy_checkout.parent.mkdir(parents=True)
        self.legacy_checkout.write_text("ref: refs/heads/main\n", encoding="utf-8")
        self.unrelated_launcher = self.bin_dir / "unrelated-cli"
        self.unrelated_launcher.write_text("keep launcher", encoding="utf-8")
        self.standalone_mcp = self.base / ".codex" / "config.toml"
        self.standalone_mcp.parent.mkdir()
        self.standalone_mcp.write_text("[mcp_servers.unrelated]\n", encoding="utf-8")
        self.temp_sentinel = self.driver_temp / "copied-helper-sentinel"
        self.temp_sentinel.write_text("parent-owned cleanup", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _driver(self, host: FakeHost, **kwargs) -> uninstall_driver.DurableUninstaller:
        return uninstall_driver.DurableUninstaller(
            self.evidence,
            lifecycle_state,
            host,
            transaction_id_factory=lambda: "uninstall-test",
            **kwargs,
        )

    def _terminal(self):
        with self.state.lock() as token:
            return self.state.read_transaction(token, "uninstall-test").journal

    def _codex_plugin_list(self, *, version: str = "1.0.0") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            ["codex"],
            0,
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": uninstall_driver.PLUGIN_ID,
                            "installed": True,
                            "enabled": True,
                            "version": version,
                        }
                    ]
                }
            ).encode("utf-8"),
            stderr=b"",
        )

    def test_production_preflight_pins_codex_home_and_proves_joint_identity(self) -> None:
        host = uninstall_driver.CodexHostRemoval(self.evidence, lifecycle_state)
        hostile = str(self.base / "hostile parent Codex home")
        with (
            mock.patch.dict(os.environ, {"CODEX_HOME": hostile}),
            mock.patch.object(
                uninstall_driver.subprocess,
                "run",
                return_value=self._codex_plugin_list(),
            ) as invoked,
        ):
            evidence = host.preflight(self.active.record)

        self.assertTrue(evidence.exact, evidence.observations)
        self.assertEqual(
            invoked.call_args.kwargs["env"]["CODEX_HOME"], str(self.codex_home)
        )
        self.assertNotEqual(str(self.codex_home), hostile)

    def test_production_preflight_drift_is_partial_before_any_host_mutation(self) -> None:
        marketplace = json.loads(self.marketplace.read_text(encoding="utf-8"))
        marketplace["plugins"][0]["source"]["path"] = str(
            self.base / "different plugin"
        )
        _json(self.marketplace, marketplace)
        host = uninstall_driver.CodexHostRemoval(self.evidence, lifecycle_state)
        before = self.marketplace.read_bytes()
        with mock.patch.object(
            uninstall_driver.subprocess,
            "run",
            return_value=self._codex_plugin_list(),
        ) as invoked:
            result = self._driver(host).run()

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(invoked.call_count, 0)
        self.assertEqual(self.marketplace.read_bytes(), before)
        self.assertTrue(self.release.exists())
        self.assertTrue(self.state.active_path.exists())

    def test_active_absence_is_partial_before_any_host_mutation(self) -> None:
        with self.state.lock() as token:
            current = self.state.read_active(token)
            self.state.compare_and_delete_active(token, self.state.expectation(current))
        host = FakeHost(self.evidence)
        before = self.marketplace.read_bytes()

        result = self._driver(host).run()

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(host.events, [])
        self.assertEqual(self.marketplace.read_bytes(), before)
        self.assertTrue(self.release.exists())

    def test_exact_uninstall_preserves_every_out_of_scope_state_and_holds_lock(self) -> None:
        host = FakeHost(self.evidence)
        mutations: list[str] = []

        def assert_locked(point: str) -> None:
            result: list[str] = []

            def contender() -> None:
                try:
                    with self.state.lock(timeout_seconds=0.02):
                        result.append("acquired")
                except lifecycle_state.LockTimeoutError:
                    result.append("locked")

            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=1)
            self.assertEqual(result, ["locked"])
            mutations.append(point)

        result = self._driver(host, mutation_hook=assert_locked).run()

        self.assertEqual(result.outcome, "committed")
        self.assertFalse(self.release.exists())
        self.assertFalse(self.state.active_path.exists())
        for name in self.dispatcher_payloads:
            self.assertFalse((self.bin_dir / name).exists())
        self.assertFalse(self.lifecycle.exists())
        self.assertTrue(self.state.lock_path.exists())
        self.assertEqual(
            mutations[-2:],
            ["uninstall_dispatcher_removed", "recovery_support_removed"],
        )
        with self.state.lock(timeout_seconds=0.2):
            pass

        marketplace = json.loads(self.marketplace.read_text(encoding="utf-8"))
        self.assertEqual(
            [item["name"] for item in marketplace["plugins"]], ["unrelated-plugin"]
        )
        for preserved in (
            self.task_data,
            self.legacy_checkout,
            self.unrelated_launcher,
            self.standalone_mcp,
            self.temp_sentinel,
            self.data_root,
        ):
            self.assertTrue(preserved.exists(), str(preserved))
        data_after = {
            str(path.relative_to(self.data_root)): path.read_bytes()
            for path in sorted(self.data_root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(data_after, self.data_before)
        self.assertEqual(self._terminal().outcome, "committed")

    def test_interruption_after_release_removal_resumes_same_journal(self) -> None:
        host = FakeHost(self.evidence)
        fired = False

        def crash(point: str) -> None:
            nonlocal fired
            if point == "releases_removed" and not fired:
                fired = True
                raise _Crash()

        with self.assertRaises(_Crash):
            self._driver(host, crash_hook=crash).run()
        self.assertFalse(self.release.exists())
        with self.state.lock() as token:
            pending = self.state.non_terminal_transactions(token)
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].journal.phase, "removing_releases")

        result = self._driver(host).run()
        self.assertTrue(result.recovered)
        self.assertEqual(result.transaction_id, "uninstall-test")
        self.assertEqual(result.outcome, "committed")
        self.assertEqual(self._terminal().outcome, "committed")

    def test_uninstall_preserves_pending_reinstall_for_its_own_driver(self) -> None:
        transaction_id = "reinstall-" + "a" * 32
        backup = self.base / "pending reinstall backup"
        backup.mkdir()
        with self.state.lock() as token:
            current = self.state.read_active(token)
            self.state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=self.state.expectation(current),
                    target_release=None,
                    previous_authority=current.record,
                    phase="removing_data",
                    owned_paths=(str(backup),),
                ),
            )
        host = FakeHost(self.evidence)
        result = self._driver(host).run()
        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.transaction_id, transaction_id)
        self.assertEqual(host.events, [])
        self.assertIn(str(backup), result.retained_paths)
        with self.state.lock() as token:
            pending = self.state.read_transaction(token, transaction_id).journal
        self.assertIsNone(pending.outcome)
        self.assertEqual(pending.phase, "removing_data")

    def test_interruption_after_cli_mcp_removal_rechecks_that_phase(self) -> None:
        host = FakeHost(self.evidence)
        fired = False

        def crash(point: str) -> None:
            nonlocal fired
            if point == "cli_mcp_dispatchers_removed" and not fired:
                fired = True
                raise _Crash()

        with self.assertRaises(_Crash):
            self._driver(host, crash_hook=crash).run()
        with self.state.lock() as token:
            pending = self.state.non_terminal_transactions(token)
            self.assertEqual(pending[0].journal.phase, "removing_dispatchers")

        result = self._driver(host).run()
        self.assertTrue(result.recovered)
        self.assertEqual(result.outcome, "committed")
        self.assertEqual(self._terminal().outcome, "committed")

    @unittest.skipIf(os.name == "nt", "native cmd execution is covered on Windows")
    def test_new_dispatcher_process_recovers_after_lifecycle_removal(self) -> None:
        lifecycle_payloads = {
            "stable_dispatcher.py": (ROOT / "scripts/stable_dispatcher.py").read_bytes(),
            "lifecycle_state.py": (ROOT / "scripts/lifecycle_state.py").read_bytes(),
            "uninstall_driver.py": (ROOT / "scripts/uninstall_driver.py").read_bytes(),
            "release_commands.py": (ROOT / "scripts/release_commands.py").read_bytes(),
            "release_resolver.py": (ROOT / "scripts/release_resolver.py").read_bytes(),
        }
        for name, raw in lifecycle_payloads.items():
            (self.lifecycle / name).write_bytes(raw)
        rendered = render_dispatchers.render_dispatchers(self.runtime, windows=False)
        for name, raw in rendered.items():
            path = self.bin_dir / name
            path.write_bytes(raw)
            path.chmod(0o755)
        _json(
            self.lifecycle / "installation.json",
            {
                "schema": uninstall_driver.INSTALLATION_SCHEMA,
                "dispatcher_protocol": uninstall_driver.DISPATCHER_PROTOCOL,
                "uninstall_driver_sha256": _sha(
                    lifecycle_payloads["uninstall_driver.py"]
                ),
                "stable_dispatcher_sha256": _sha(
                    lifecycle_payloads["stable_dispatcher.py"]
                ),
                "lifecycle_state_sha256": _sha(
                    lifecycle_payloads["lifecycle_state.py"]
                ),
                "release_commands_sha256": _sha(
                    lifecycle_payloads["release_commands.py"]
                ),
                "release_resolver_sha256": _sha(
                    lifecycle_payloads["release_resolver.py"]
                ),
                "dispatchers": {
                    name: _sha(raw) for name, raw in sorted(rendered.items())
                },
                "bin_dir": str(self.bin_dir),
                "marketplace_file": str(self.marketplace),
                "codex_home": str(self.codex_home),
                "plugin_id": uninstall_driver.PLUGIN_ID,
                "runtime_root": str(self.runtime),
                "data_root": str(self.data_root),
                "data_owned_paths": [
                    uninstall_driver.DATA_NAMESPACE,
                    uninstall_driver.WEB_RUNTIME_DIR,
                ],
                "data_marker_name": uninstall_driver.DATA_MARKER_NAME,
            },
        )
        lifecycle_evidence, _ = uninstall_driver.load_installation(
            self.runtime, self.bin_dir, self.driver_temp
        )
        recovery_root = stable_dispatcher._recovery_root(self.runtime)
        fired = False

        def crash(point: str) -> None:
            nonlocal fired
            if point == "lifecycle_content_removed" and not fired:
                fired = True
                raise _Crash()

        with self.assertRaises(_Crash):
            uninstall_driver.DurableUninstaller(
                lifecycle_evidence,
                lifecycle_state,
                FakeHost(lifecycle_evidence),
                transaction_id_factory=lambda: "uninstall-test",
                crash_hook=crash,
            ).run()
        self.assertFalse(self.lifecycle.exists())
        uninstaller = self.bin_dir / "dev-flow-uninstall"
        self.assertTrue(uninstaller.exists())
        self.assertTrue(recovery_root.exists())

        completed = subprocess.run(
            [str(uninstaller)], capture_output=True, text=True, timeout=30
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(uninstaller.exists())
        self.assertFalse(recovery_root.exists())
        self.assertEqual(self._terminal().outcome, "committed")

    def test_unknown_release_content_is_retained_and_stops_later_mutation(self) -> None:
        unknown = self.release / "user-note.txt"
        unknown.write_text("not owned", encoding="utf-8")
        host = FakeHost(self.evidence)
        marketplace_before = self.marketplace.read_bytes()

        result = self._driver(host).run()

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(host.events, [])
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertTrue(unknown.exists())
        self.assertTrue(self.state.active_path.exists())
        for name in self.dispatcher_payloads:
            self.assertTrue((self.bin_dir / name).exists())
        self.assertTrue(self.lifecycle.exists())
        self.assertIn(str(self.release), result.retained_paths)

    def test_changed_dispatcher_is_retained_before_lifecycle_teardown(self) -> None:
        suffix = ".cmd" if os.name == "nt" else ""
        changed = self.bin_dir / f"dev-flow{suffix}"
        changed.write_bytes(b"user changed dispatcher\n")

        result = self._driver(FakeHost(self.evidence)).run()

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(changed.read_bytes(), b"user changed dispatcher\n")
        self.assertFalse(self.release.exists())
        self.assertFalse(self.state.active_path.exists())
        self.assertTrue((self.bin_dir / f"dev-flow-mcp{suffix}").exists())
        self.assertTrue((self.bin_dir / f"dev-flow-uninstall{suffix}").exists())
        self.assertTrue(self.lifecycle.exists())

    def test_host_uncertainty_stops_before_marketplace_and_runtime(self) -> None:
        host = FakeHost(self.evidence)
        host.fail_plugin = True
        marketplace_before = self.marketplace.read_bytes()

        result = self._driver(host).run()

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(host.events, ["plugin"])
        self.assertEqual(self.marketplace.read_bytes(), marketplace_before)
        self.assertTrue(self.release.exists())
        self.assertTrue(self.state.active_path.exists())

    @unittest.skipIf(os.name == "nt", "symlink creation needs explicit Windows privilege")
    def test_linked_release_is_retained_without_following_target(self) -> None:
        external = self.base / "outside target"
        external.mkdir()
        marker = external / "keep.txt"
        marker.write_text("keep external", encoding="utf-8")
        linked = self.releases / "0-linked-release"
        linked.symlink_to(external, target_is_directory=True)

        result = self._driver(FakeHost(self.evidence)).run()

        self.assertEqual(result.outcome, "partial")
        self.assertTrue(linked.is_symlink())
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep external")
        self.assertTrue(self.release.exists())
        self.assertTrue(self.state.active_path.exists())


if __name__ == "__main__":
    unittest.main()
