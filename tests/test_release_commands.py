"""Installed update and reinstall command driver tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import lifecycle_state
from scripts import release_commands
from scripts import release_resolver


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path, value: object) -> bytes:
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _marker(data_root: Path) -> dict[str, object]:
    return {
        "schema": release_resolver.DATA_OWNERSHIP_SCHEMA,
        "product": release_resolver.PRODUCT_NAME,
        "data_root": str(data_root),
        "namespace": release_resolver.DATA_NAMESPACE,
        "web_runtime": release_resolver.WEB_RUNTIME_DIR,
    }


class InstallationFixture:
    def __init__(self, base: Path, *, with_data: bool = True) -> None:
        self.base = base
        self.runtime = base / "managed runtime's 数据"
        self.releases = self.runtime / "releases"
        self.lifecycle = self.runtime / "lifecycle"
        self.bin_dir = base / "bin dir's 工具"
        self.codex_home = base / "Codex home's 数据"
        self.marketplace = base / ".agents" / "plugins" / "marketplace.json"
        self.data_root = base / "task data root's 数据"
        for path in (self.releases, self.lifecycle, self.bin_dir, self.codex_home):
            path.mkdir(parents=True, exist_ok=True)
        for name in (
            "stable_dispatcher.py",
            "lifecycle_state.py",
            "uninstall_driver.py",
            "release_commands.py",
            "release_resolver.py",
        ):
            (self.lifecycle / name).write_bytes(
                (ROOT / "scripts" / name).read_bytes()
            )
        dispatchers = {}
        suffix = ".cmd" if os.name == "nt" else ""
        for name in ("dev-flow", "dev-flow-mcp", "dev-flow-uninstall"):
            raw = ("stable {}\n".format(name)).encode()
            path = self.bin_dir / (name + suffix)
            path.write_bytes(raw)
            dispatchers[name + suffix] = raw
        if with_data:
            self._write_data()
        _json(
            self.lifecycle / "installation.json",
            {
                "schema": release_commands.INSTALLATION_SCHEMA,
                "dispatcher_protocol": release_commands.DISPATCHER_PROTOCOL,
                "uninstall_driver_sha256": _sha((self.lifecycle / "uninstall_driver.py").read_bytes()),
                "stable_dispatcher_sha256": _sha((self.lifecycle / "stable_dispatcher.py").read_bytes()),
                "lifecycle_state_sha256": _sha((self.lifecycle / "lifecycle_state.py").read_bytes()),
                "release_commands_sha256": _sha((self.lifecycle / "release_commands.py").read_bytes()),
                "release_resolver_sha256": _sha((self.lifecycle / "release_resolver.py").read_bytes()),
                "dispatchers": {name: _sha(raw) for name, raw in sorted(dispatchers.items())},
                "bin_dir": str(self.bin_dir),
                "marketplace_file": str(self.marketplace),
                "codex_home": str(self.codex_home),
                "plugin_id": release_commands.PLUGIN_ID,
                "runtime_root": str(self.runtime),
                "data_root": str(self.data_root),
                "data_owned_paths": [
                    release_resolver.DATA_NAMESPACE,
                    release_resolver.WEB_RUNTIME_DIR,
                ],
                "data_marker_name": release_resolver.DATA_MARKER_NAME,
            },
        )
        self.evidence, self.raw = release_commands.load_installation(
            self.lifecycle, self.runtime
        )

    def _write_data(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        namespace = self.data_root / release_resolver.DATA_NAMESPACE
        tasks = namespace / "tasks"
        tasks.mkdir(parents=True)
        self.task_state = tasks / "task-1" / "state.json"
        self.task_state.parent.mkdir()
        self.task_state.write_text('{"status":"DONE"}\n', encoding="utf-8")
        self.lock_file = namespace / "locks" / "task-1.lock"
        self.lock_file.parent.mkdir()
        self.lock_file.write_bytes(b"lock\n")
        web = self.data_root / release_resolver.WEB_RUNTIME_DIR
        web.mkdir()
        self.web_log = web / "server.log"
        self.web_log.write_text("server log\n", encoding="utf-8")
        _json(self.data_root / release_resolver.DATA_MARKER_NAME, _marker(self.data_root))
        self.data_before = {
            str(path.relative_to(self.data_root)): path.read_bytes()
            for path in sorted(self.data_root.rglob("*"))
            if path.is_file()
        }

    def state(self):
        return lifecycle_state.LifecycleState(self.runtime, self.releases)

    def make_active(self, version: str = "0.6.0") -> None:
        release_id = "v{}-{}-tx-upgrade".format(version, "a" * 16)
        release = self.releases / release_id
        (release / "plugin").mkdir(parents=True)
        receipt = {
            "schema": release_commands.ARTIFACT_RUNTIME_RECEIPT_SCHEMA,
            "release_id": release_id,
            "version": version,
            "runtime_path": str(release),
            "transaction_id": "tx-upgrade",
        }
        receipt_raw = _json(release / "runtime-receipt.json", receipt)
        state = self.state()
        with state.lock() as token:
            empty = state.read_active(token)
            state.compare_and_set_active(
                token,
                empty,
                release_id=release_id,
                release_path=str(release),
                receipt_sha256=_sha(receipt_raw),
                dispatcher_protocol=lifecycle_state.DISPATCHER_PROTOCOL,
                transaction_id="tx-upgrade",
            )

    def resolver_module(self):
        return sys.modules["_dev_flow_installed_release_resolver"]

    def bootstrap_active(self, version: str) -> dict[str, object]:
        state = self.state()
        with state.lock() as token:
            current = state.read_active(token)
            if current.record is not None:
                return current.record.as_dict()
            transaction_id = "tx-bootstrap-active"
            release_id = "v{}-{}-{}".format(version, "b" * 16, transaction_id)
            release = self.releases / release_id
            release.mkdir(parents=True, exist_ok=True)
            activated = state.compare_and_set_active(
                token,
                current,
                release_id=release_id,
                release_path=str(release),
                receipt_sha256="c" * 64,
                dispatcher_protocol=lifecycle_state.DISPATCHER_PROTOCOL,
                transaction_id=transaction_id,
            )
            assert activated.record is not None
            return activated.record.as_dict()


class ReleaseCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="Dev Flow commands 数据's ")
        self.base = Path(self.temporary.name).resolve()
        self.fixture = InstallationFixture(self.base)
        release_commands.load_support_modules(self.fixture.evidence)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _pin_latest(self, version: str = "0.9.9"):
        module = self.fixture.resolver_module()
        return mock.patch.object(module, "resolve_latest_version", return_value=version)

    def _bootstrap(
        self,
        *,
        outcome: str = "committed",
        returncode: int = 0,
        reused: bool = False,
    ):
        def run(
            evidence,
            resolver,
            version,
            timeout=None,
            reinstall_transaction_id=None,
        ):
            payload = {
                "ok": outcome == "committed",
                "outcome": outcome,
                "transaction_id": "tx-bootstrap",
                "detail": "simulated bootstrap",
                "reused": reused,
            }
            if outcome == "committed":
                payload["active"] = self.fixture.bootstrap_active(version)
            return {
                "returncode": returncode,
                "outcome": outcome,
                "payload": payload,
            }

        return mock.patch.object(
            release_commands,
            "_run_bootstrap",
            side_effect=run,
        )


class UpdateCommandTests(ReleaseCommandTests):
    def test_latest_active_runs_full_phase_b_reuse_attestation(self) -> None:
        self.fixture.make_active("0.6.8")
        with self._pin_latest("0.6.8"), self._bootstrap(reused=True) as bootstrap:
            result = release_commands.update_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["version"], "0.6.8")
        self.assertTrue(result["reused"])
        bootstrap.assert_called_once()

    def test_older_active_runs_the_latest_bootstrap_with_recorded_paths(self) -> None:
        self.fixture.make_active("0.6.0")
        captured: dict = {}
        original = release_commands._run_bootstrap

        def fake_run(evidence, resolver, version, timeout=None):
            captured["arguments"] = {
                "version": version,
                "runtime_root": str(evidence.runtime_root),
                "data_root": str(evidence.data_root),
            }
            return {
                "returncode": 0,
                "outcome": "committed",
                "payload": {
                    "ok": True,
                    "outcome": "committed",
                    "transaction_id": "tx-upgrade-done",
                },
            }

        with self._pin_latest("0.9.9"), mock.patch.object(
            release_commands, "_run_bootstrap", side_effect=fake_run
        ):
            result = release_commands.update_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(captured["arguments"]["version"], "0.9.9")
        self.assertEqual(
            captured["arguments"]["runtime_root"], str(self.fixture.runtime)
        )
        self.assertEqual(
            captured["arguments"]["data_root"], str(self.fixture.data_root)
        )

    def test_broken_active_receipt_still_runs_the_bootstrap_for_repair(self) -> None:
        self.fixture.make_active("0.6.8")
        receipt_path = next(self.fixture.releases.rglob("runtime-receipt.json"))
        receipt_path.write_bytes(b"drifted receipt\n")
        with self._pin_latest("0.6.8"), self._bootstrap(outcome="committed") as bootstrap:
            result = release_commands.update_command(self.fixture.evidence)
        bootstrap.assert_called_once()
        self.assertTrue(result["ok"])

    def test_pending_transaction_never_takes_the_up_to_date_fast_path(self) -> None:
        self.fixture.make_active("0.6.8")
        state = self.fixture.state()
        with state.lock() as token:
            state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id="tx-pending",
                    operation="upgrade",
                    expected_active=lifecycle_state.ActiveExpectation(1, "a" * 64, True),
                    target_release=None,
                    previous_authority=None,
                    phase="candidate_ready",
                ),
            )
        with self._pin_latest("0.6.8"), self._bootstrap(outcome="committed") as bootstrap:
            result = release_commands.update_command(self.fixture.evidence)
        bootstrap.assert_called_once()
        self.assertTrue(result["ok"])

    def test_latest_resolution_failure_exits_before_any_mutation(self) -> None:
        self.fixture.make_active("0.6.0")
        module = self.fixture.resolver_module()

        def fail():
            raise release_resolver.ReleaseResolveError("simulated lookup failure")

        with mock.patch.object(module, "resolve_latest_version", side_effect=fail), self._bootstrap() as bootstrap:
            with self.assertRaises(release_resolver.ReleaseResolveError):
                release_commands.update_command(self.fixture.evidence)
        bootstrap.assert_not_called()
        self.assertEqual(
            self.fixture.data_before,
            {
                str(path.relative_to(self.fixture.data_root)): path.read_bytes()
                for path in sorted(self.fixture.data_root.rglob("*"))
                if path.is_file()
            },
        )


class ReinstallCommandTests(ReleaseCommandTests):
    def _data_now(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.fixture.data_root)): path.read_bytes()
            for path in sorted(self.fixture.data_root.rglob("*"))
            if path.is_file()
        }

    def test_reinstall_clears_owned_data_and_commits_latest(self) -> None:
        with self._pin_latest("0.9.9"), self._bootstrap(
            outcome="committed"
        ) as bootstrap:
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(result["version"], "0.9.9")
        state = self.fixture.state()
        with state.lock() as token:
            terminal = state.read_transaction(token, result["transaction_id"]).journal
        self.assertEqual(terminal.outcome, "committed")
        # The data root holds only the fresh marker; the backup is removed.
        remaining = {
            str(path.relative_to(self.fixture.data_root)): path.read_bytes()
            for path in sorted(self.fixture.data_root.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(
            remaining,
            {
                release_resolver.DATA_MARKER_NAME: _json(
                    self.fixture.data_root / release_resolver.DATA_MARKER_NAME,
                    _marker(self.fixture.data_root),
                )
            },
        )
        self.assertEqual(
            list(self.fixture.data_root.parent.glob(
                release_commands.BACKUP_PREFIX + "*"
            )),
            [],
        )
        self.assertEqual(
            bootstrap.call_args.kwargs["reinstall_transaction_id"],
            result["transaction_id"],
        )

    def test_concurrent_reinstall_driver_cannot_resume_the_same_journal(self) -> None:
        state_module, _resolver = release_commands.load_support_modules(
            self.fixture.evidence
        )
        guard = state_module.LifecycleState(
            self.fixture.runtime / release_commands.REINSTALL_GUARD_DIR,
            self.fixture.releases,
        )
        with guard.lock(timeout_seconds=1.0), self._bootstrap() as bootstrap:
            with self.assertRaisesRegex(Exception, "lock timed out"):
                release_commands.reinstall_command(
                    self.fixture.evidence, lock_timeout=0.01
                )
        bootstrap.assert_not_called()

    def test_failed_install_restores_every_data_byte_and_rolls_back(self) -> None:
        before = self._data_now()
        with self._pin_latest("0.9.9"), self._bootstrap(outcome="rolled_back", returncode=1):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "rolled_back")
        self.assertEqual(self._data_now(), before)
        state = self.fixture.state()
        with state.lock() as token:
            terminal = state.read_transaction(token, result["transaction_id"]).journal
        self.assertEqual(terminal.outcome, "rolled_back")
        self.assertEqual(
            list(self.fixture.data_root.parent.glob(release_commands.BACKUP_PREFIX + "*")),
            [],
        )

    def test_unowned_top_level_entry_preserves_all_data_and_reports_partial(self) -> None:
        unowned = self.fixture.data_root / "user-notes.txt"
        unowned.write_text("user owned", encoding="utf-8")
        before = self._data_now()
        with self._pin_latest("0.9.9"), self._bootstrap() as bootstrap:
            result = release_commands.reinstall_command(self.fixture.evidence)
        bootstrap.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(self._data_now(), before)

    def test_linked_data_entry_is_retained_as_partial(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX symlink fixture")
        link = self.fixture.data_root / release_resolver.DATA_NAMESPACE / "linked"
        link.symlink_to(self.fixture.task_state)
        before = self._data_now()
        with self._pin_latest("0.9.9"), self._bootstrap() as bootstrap:
            result = release_commands.reinstall_command(self.fixture.evidence)
        bootstrap.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(self._data_now(), before)

    def test_drifted_marker_is_preserved_and_reported_partial(self) -> None:
        marker_path = self.fixture.data_root / release_resolver.DATA_MARKER_NAME
        value = json.loads(marker_path.read_text(encoding="utf-8"))
        value["namespace"] = "other"
        _json(marker_path, value)
        before = self._data_now()
        with self._pin_latest("0.9.9"), self._bootstrap() as bootstrap:
            result = release_commands.reinstall_command(self.fixture.evidence)
        bootstrap.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(self._data_now(), before)

    def test_legacy_unmarked_data_root_with_only_owned_names_is_cleaned(self) -> None:
        (self.fixture.data_root / release_resolver.DATA_MARKER_NAME).unlink()
        with self._pin_latest("0.9.9"), self._bootstrap(outcome="committed"):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])

    def test_absent_data_root_is_created_with_marker_and_rolled_back_on_failure(self) -> None:
        import shutil

        shutil.rmtree(self.fixture.data_root)
        with self._pin_latest("0.9.9"), self._bootstrap(outcome="rolled_back", returncode=1):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "rolled_back")
        self.assertFalse(self.fixture.data_root.exists())

    def test_interrupted_removal_resumes_one_journal_and_converges(self) -> None:
        state = self.fixture.state()
        state_module = lifecycle_state
        resolver = self.fixture.resolver_module()
        with state.lock() as token:
            active = state.read_active(token)
            transaction_id = "reinstall-interrupted"
            backup_root = self.fixture.data_root.parent / (
                release_commands.BACKUP_PREFIX + transaction_id
            )
            journal = state.create_transaction(
                token,
                state_module.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    owned_paths=(
                        str(self.fixture.data_root),
                        str(backup_root),
                        str(backup_root / "data"),
                    ),
                ),
            )
            journal, step = release_commands._ensure_data_removed(
                state, state_module, token, journal, self.fixture.evidence, resolver
            )
        self.assertEqual(step, "completed")
        # Crash before the bootstrap and terminal classification.
        with state.lock() as token:
            pending = state.non_terminal_transactions(token)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].journal.phase, "removing_data")

        with self._pin_latest("0.9.9"), self._bootstrap(outcome="committed"):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transaction_id"], transaction_id)
        with state.lock() as token:
            terminal = state.read_transaction(token, transaction_id).journal
        self.assertEqual(terminal.outcome, "committed")

    def test_interrupted_after_payload_move_before_marker_converges(self) -> None:
        state = self.fixture.state()
        resolver = self.fixture.resolver_module()
        transaction_id = "reinstall-before-marker"
        backup_root, payload = release_commands._backup_paths(
            self.fixture.evidence, transaction_id
        )
        with state.lock() as token:
            active = state.read_active(token)
            journal = state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    owned_paths=(str(self.fixture.data_root), str(backup_root)),
                ),
            )
            _journal, step = release_commands._ensure_data_removed(
                state,
                lifecycle_state,
                token,
                journal,
                self.fixture.evidence,
                resolver,
            )
        self.assertEqual(step, "completed")
        self.assertTrue(payload.is_dir())
        (self.fixture.data_root / release_resolver.DATA_MARKER_NAME).unlink()
        self.fixture.data_root.rmdir()

        with self._pin_latest("0.9.9"), self._bootstrap(outcome="committed"):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transaction_id"], transaction_id)

    def test_changed_backup_file_is_restored_from_quarantine_and_retained(self) -> None:
        state = self.fixture.state()
        resolver = self.fixture.resolver_module()
        transaction_id = "reinstall-changed-backup"
        backup_root, payload = release_commands._backup_paths(
            self.fixture.evidence, transaction_id
        )
        with state.lock() as token:
            active = state.read_active(token)
            journal = state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    owned_paths=(str(self.fixture.data_root), str(backup_root)),
                ),
            )
            journal, step = release_commands._ensure_data_removed(
                state,
                lifecycle_state,
                token,
                journal,
                self.fixture.evidence,
                resolver,
            )
        self.assertEqual(step, "completed")
        changed = payload / release_resolver.DATA_NAMESPACE / "tasks" / "task-1" / "state.json"
        changed.write_bytes(b"concurrent change\n")
        with state.lock() as token:
            journal = state.read_transaction(token, transaction_id)
            _journal, exact = release_commands._remove_backup_after_commit(
                state,
                lifecycle_state,
                token,
                journal,
                self.fixture.evidence,
            )
        self.assertFalse(exact)
        self.assertEqual(changed.read_bytes(), b"concurrent change\n")
        self.assertFalse((backup_root / ".deletion-quarantine").exists())

    def test_crash_after_manifest_before_rename_retries_exactly(self) -> None:
        state = self.fixture.state()
        resolver = self.fixture.resolver_module()
        transaction_id = "reinstall-pre-move"
        backup_root, _payload = release_commands._backup_paths(
            self.fixture.evidence, transaction_id
        )
        owned = {
            self.fixture.evidence.data_marker_name,
            *self.fixture.evidence.data_owned_paths,
        }
        entries, error = release_commands._inventory_data_root(
            self.fixture.data_root, owned_names=owned
        )
        self.assertIsNone(error)
        backup_root.mkdir()
        release_commands._atomic_write(
            backup_root / "inventory.json",
            release_commands._canonical_bytes(
                release_commands._backup_manifest(
                    self.fixture.evidence, transaction_id, entries
                )
            ),
        )
        with state.lock() as token:
            active = state.read_active(token)
            state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    phase="removing_data",
                    owned_paths=(str(self.fixture.data_root), str(backup_root)),
                ),
            )
        with self._pin_latest("0.9.9"), self._bootstrap(outcome="committed"):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transaction_id"], transaction_id)
        self.assertFalse(backup_root.exists())

    def test_committed_bootstrap_with_changed_active_retains_backup_as_partial(self) -> None:
        bootstrap = {
            "returncode": 0,
            "outcome": "committed",
            "payload": {
                "ok": True,
                "outcome": "committed",
                "active": {"schema": "not-the-current-active-authority"},
            },
        }
        with self._pin_latest("0.9.9"), mock.patch.object(
            release_commands, "_run_bootstrap", return_value=bootstrap
        ):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "partial")
        self.assertTrue(result["retained_paths"])
        backup_root, payload = release_commands._backup_paths(
            self.fixture.evidence, result["transaction_id"]
        )
        self.assertTrue(backup_root.is_dir())
        self.assertTrue(payload.is_dir())

    def test_interrupted_failure_restores_data_from_the_same_journal(self) -> None:
        state = self.fixture.state()
        state_module = lifecycle_state
        resolver = self.fixture.resolver_module()
        before = self._data_now()
        with state.lock() as token:
            active = state.read_active(token)
            transaction_id = "reinstall-interrupted-fail"
            backup_root = self.fixture.data_root.parent / (
                release_commands.BACKUP_PREFIX + transaction_id
            )
            journal = state.create_transaction(
                token,
                state_module.TransactionJournal(
                    transaction_id=transaction_id,
                    operation="reinstall",
                    expected_active=state.expectation(active),
                    target_release=None,
                    previous_authority=active.record,
                    owned_paths=(
                        str(self.fixture.data_root),
                        str(backup_root),
                        str(backup_root / "data"),
                    ),
                ),
            )
            _journal, step = release_commands._ensure_data_removed(
                state, state_module, token, journal, self.fixture.evidence, resolver
            )
        self.assertEqual(step, "completed")
        with self._pin_latest("0.9.9"), self._bootstrap(outcome="rolled_back", returncode=1):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "rolled_back")
        self.assertEqual(self._data_now(), before)
        self.assertEqual(
            list(self.fixture.data_root.parent.glob(release_commands.BACKUP_PREFIX + "*")),
            [],
        )

    def test_prior_activation_transaction_is_recovered_before_data_mutation(self) -> None:
        state = self.fixture.state()
        with state.lock() as token:
            state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id="tx-interrupted-upgrade",
                    operation="upgrade",
                    expected_active=lifecycle_state.ActiveExpectation(0, None, False),
                    target_release=None,
                    previous_authority=None,
                    phase="candidate_ready",
                ),
            )
        runs = []

        def recovering_bootstrap(
            evidence,
            resolver,
            version,
            timeout=None,
            reinstall_transaction_id=None,
        ):
            runs.append(version)
            state = lifecycle_state.LifecycleState(
                evidence.runtime_root, evidence.releases_root
            )
            with state.lock() as token:
                pending = state.non_terminal_transactions(token)
                if pending and pending[0].journal.operation != "reinstall":
                    state.finish_transaction(token, pending[0], "rolled_back")
            payload = {"ok": True, "outcome": "committed"}
            if reinstall_transaction_id is not None:
                payload["active"] = self.fixture.bootstrap_active(version)
            return {
                "returncode": 0,
                "outcome": "committed",
                "payload": payload,
            }

        with self._pin_latest("0.9.9"), mock.patch.object(
            release_commands, "_run_bootstrap", side_effect=recovering_bootstrap
        ):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertTrue(result["ok"])
        self.assertEqual(runs, ["0.9.9", "0.9.9"])
        self.assertFalse(self.fixture.task_state.exists())
        with state.lock() as token:
            recovered = state.read_transaction(token, "tx-interrupted-upgrade").journal
        self.assertEqual(recovered.outcome, "rolled_back")

    def test_backup_cleanup_failure_reports_committed_with_retained_paths(self) -> None:
        original = release_commands._remove_backup_payload

        def partial_removal(payload, entries):
            retained, removed = original(payload, entries)
            return ([str(payload / "0.4.0")] if not retained else retained), removed

        with self._pin_latest("0.9.9"), self._bootstrap(outcome="committed"), mock.patch.object(
            release_commands, "_remove_backup_payload", side_effect=partial_removal
        ):
            result = release_commands.reinstall_command(self.fixture.evidence)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "committed")
        self.assertTrue(result["retained_paths"])
        state = self.fixture.state()
        with state.lock() as token:
            terminal = state.read_transaction(token, result["transaction_id"]).journal
        self.assertEqual(terminal.outcome, "committed")

    def test_reinstall_requires_exact_installation_evidence(self) -> None:
        value = json.loads(
            (self.fixture.lifecycle / "installation.json").read_text(encoding="utf-8")
        )
        value["data_root"] = str(self.fixture.runtime / "nested" / "data")
        _json(self.fixture.lifecycle / "installation.json", value)
        with self.assertRaisesRegex(release_commands.ReleaseCommandError, "overlaps"):
            release_commands.load_installation(self.fixture.lifecycle, self.fixture.runtime)

    def test_reinstall_rejects_broadened_data_ownership_evidence(self) -> None:
        value = json.loads(
            (self.fixture.lifecycle / "installation.json").read_text(encoding="utf-8")
        )
        value["data_owned_paths"].append("user-content")
        _json(self.fixture.lifecycle / "installation.json", value)
        with self.assertRaisesRegex(
            release_commands.ReleaseCommandError, "ownership paths"
        ):
            release_commands.load_installation(
                self.fixture.lifecycle, self.fixture.runtime
            )

    def test_support_file_digest_drift_blocks_all_commands(self) -> None:
        (self.fixture.lifecycle / "release_resolver.py").write_bytes(b"drift\n")
        with self.assertRaisesRegex(release_commands.ReleaseCommandError, "digest"):
            release_commands.load_installation(self.fixture.lifecycle, self.fixture.runtime)


class MainEntryTests(ReleaseCommandTests):
    def test_source_root_environment_fails_before_evidence_or_mutation(self) -> None:
        with mock.patch.dict(
            os.environ, {"DEV_FLOW_SOURCE_ROOT": str(self.base / "checkout")}
        ):
            self.assertEqual(
                release_commands.main(
                    [
                        "--runtime-root",
                        str(self.fixture.runtime),
                        "--support-root",
                        str(self.fixture.lifecycle),
                        "--mode",
                        "update",
                    ]
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
