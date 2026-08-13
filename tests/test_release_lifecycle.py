"""Focused orchestration tests for the versioned Phase B lifecycle driver."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import lifecycle_state
from scripts import release_artifact
from scripts import release_lifecycle


def _index() -> dict[str, object]:
    return {
        "schema": release_artifact.INDEX_SCHEMA,
        "artifact_schema": release_artifact.ARTIFACT_SCHEMA,
        "repository": release_artifact.CANONICAL_REPOSITORY,
        "version": "0.6.0",
        "source_commit": "a" * 40,
        "source_tree": "b" * 40,
        "archive": {
            "name": "dev-flow-orchestrator-0.6.0.tar.gz",
            "size": 123,
            "sha256": "c" * 64,
        },
        "manifest_sha256": "d" * 64,
        "limits": dict(release_artifact.HARD_LIMITS),
    }


def _write_executable(path: Path, document: str) -> None:
    path.write_text(document, encoding="utf-8")
    path.chmod(
        stat.S_IRUSR
        | stat.S_IWUSR
        | stat.S_IXUSR
        | stat.S_IRGRP
        | stat.S_IXGRP
        | stat.S_IROTH
        | stat.S_IXOTH
    )


class ReleaseLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="Dev Flow Phase B root's 数据 "
        )
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _paths(self) -> release_lifecycle.InstallPaths:
        artifact = self.root / "artifact" / "dev-flow-orchestrator-0.6.0"
        lifecycle = artifact / "lifecycle"
        lifecycle.mkdir(parents=True)
        for name in ("stable_dispatcher.py", "lifecycle_state.py", "uninstall_driver.py"):
            (lifecycle / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        index_path = self.root / "download" / "release-index.json"
        index_path.parent.mkdir()
        index_path.write_bytes(release_artifact.canonical_json_bytes(_index()))
        runtime = self.root / "managed runtime's 数据"
        runtime.mkdir()
        bin_dir = self.root / "bin path's 数据"
        bin_dir.mkdir()
        marketplace = self.root / "marketplace" / ".agents" / "plugins" / "marketplace.json"
        codex = self.root / "Codex home 数据"
        data = codex / "plugins" / "data" / "dev-flow-orchestrator-personal"
        return release_lifecycle.InstallPaths(
            artifact,
            index_path,
            runtime,
            bin_dir,
            marketplace,
            codex,
            data,
            False,
        )

    def test_release_index_is_digest_bound_and_closed(self) -> None:
        path = self.root / "release-index.json"
        raw = release_artifact.canonical_json_bytes(_index())
        path.write_bytes(raw)
        identity = release_lifecycle.load_index_identity(
            path, hashlib.sha256(raw).hexdigest()
        )
        self.assertEqual(identity.version, "0.6.0")
        self.assertEqual(identity.archive_sha256, "c" * 64)
        self.assertEqual(identity.manifest_sha256, "d" * 64)

        with self.assertRaisesRegex(
            release_lifecycle.ReleaseLifecycleError, "differs from Phase A"
        ):
            release_lifecycle.load_index_identity(path, "f" * 64)

        changed = _index()
        changed["unknown"] = True
        raw = release_artifact.canonical_json_bytes(changed)
        path.write_bytes(raw)
        with self.assertRaises(release_lifecycle.ReleaseLifecycleError):
            release_lifecycle.load_index_identity(
                path, hashlib.sha256(raw).hexdigest()
            )

    def test_source_root_is_rejected_before_argument_or_state_processing(self) -> None:
        output = StringIO()
        with (
            mock.patch.dict(os.environ, {"DEV_FLOW_SOURCE_ROOT": str(self.root / "checkout")}),
            mock.patch.object(release_lifecycle, "_parser") as parser,
            mock.patch.object(release_lifecycle, "execute_install") as execute,
            redirect_stdout(output),
        ):
            self.assertEqual(release_lifecycle.main(["install"]), 1)
        parser.assert_not_called()
        execute.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["outcome"], "partial")
        self.assertIn("DEV_FLOW_SOURCE_ROOT", result["error"])

    @unittest.skipIf(os.name == "nt", "POSIX byte and executable-mode fixture")
    def test_dispatchers_are_stable_across_ordinary_upgrade(self) -> None:
        paths = self._paths()
        manager = release_lifecycle.InfrastructureManager(paths)
        owned = manager.ensure("tx-first", "install")
        self.assertEqual(len(owned), 1)
        first = {
            name: (paths.bin_dir / name).read_bytes()
            for name in ("dev-flow", "dev-flow-mcp", "dev-flow-uninstall")
        }
        first_stats = {
            name: (paths.bin_dir / name).stat().st_mtime_ns for name in first
        }
        self.assertEqual(manager.commit("tx-first"), ())

        self.assertEqual(manager.ensure("tx-upgrade", "upgrade"), ())
        self.assertEqual(
            {name: (paths.bin_dir / name).read_bytes() for name in first}, first
        )
        self.assertEqual(
            {name: (paths.bin_dir / name).stat().st_mtime_ns for name in first},
            first_stats,
        )
        evidence = json.loads(
            (paths.runtime_root / "lifecycle" / "installation.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            set(evidence["dispatchers"]),
            {"dev-flow", "dev-flow-mcp", "dev-flow-uninstall"},
        )
        self.assertEqual(evidence["codex_home"], str(paths.codex_home))

    @unittest.skipIf(os.name == "nt", "POSIX infrastructure mode fixture")
    def test_active_reuse_requires_exact_stable_infrastructure(self) -> None:
        paths = self._paths()
        manager = release_lifecycle.InfrastructureManager(paths)
        manager.ensure("tx-install", "install")
        self.assertEqual(manager.commit("tx-install"), ())
        candidates = release_lifecycle.ArtifactCandidates(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            manager,
        )
        receipt = {
            "version": "0.6.0",
            "release_index_sha256": "a" * 64,
            "archive_sha256": "b" * 64,
            "artifact_manifest_sha256": "c" * 64,
        }
        active = SimpleNamespace(receipt_sha256="d" * 64)
        with (
            mock.patch.object(
                candidates, "_receipt_identity", return_value=(receipt, None)
            ),
            mock.patch.object(candidates, "_full_attestation", return_value=True),
        ):
            self.assertTrue(candidates.attest_active(active).reusable)
            _write_executable(
                paths.bin_dir / "dev-flow",
                "#!/bin/sh\nexec /tmp/forwarded-dev-flow \"$@\"\n",
            )
            attestation = candidates.attest_active(active)

        self.assertFalse(attestation.reusable)
        infrastructure = next(
            item
            for item in attestation.observations
            if item.subject == "stable-infrastructure"
        )
        self.assertEqual(infrastructure.state, "changed")

    @unittest.skipIf(os.name == "nt", "POSIX infrastructure mode fixture")
    def test_proven_repair_replaces_stable_drift_with_transaction_rollback(self) -> None:
        paths = self._paths()
        manager = release_lifecycle.InfrastructureManager(paths)
        manager.ensure("tx-install", "install")
        self.assertEqual(manager.commit("tx-install"), ())
        dispatcher = paths.bin_dir / "dev-flow"
        expected = dispatcher.read_bytes()
        drifted = b"#!/bin/sh\nexec /tmp/forwarded-dev-flow \"$@\"\n"
        dispatcher.write_bytes(drifted)
        dispatcher.chmod(0o711)

        self.assertFalse(manager.attest()[0])
        owned = manager.ensure("tx-repair-rollback", "repair")
        self.assertEqual(len(owned), 1)
        self.assertEqual(dispatcher.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(dispatcher.stat().st_mode), 0o755)

        self.assertEqual(manager.rollback("tx-repair-rollback"), ())
        self.assertEqual(dispatcher.read_bytes(), drifted)
        self.assertEqual(stat.S_IMODE(dispatcher.stat().st_mode), 0o711)

        manager.ensure("tx-repair-commit", "repair")
        self.assertEqual(manager.commit("tx-repair-commit"), ())
        self.assertEqual(dispatcher.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(dispatcher.stat().st_mode), 0o755)
        self.assertTrue(manager.attest()[0])

    @unittest.skipIf(os.name == "nt", "POSIX infrastructure fixture")
    def test_repair_preserves_drift_when_installation_identity_is_unproven(self) -> None:
        paths = self._paths()
        manager = release_lifecycle.InfrastructureManager(paths)
        manager.ensure("tx-install", "install")
        self.assertEqual(manager.commit("tx-install"), ())
        dispatcher = paths.bin_dir / "dev-flow"
        drifted = b"user-owned replacement\n"
        dispatcher.write_bytes(drifted)
        evidence_path = paths.runtime_root / "lifecycle" / "installation.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["plugin_id"] = "changed-identity@personal"
        changed_evidence = release_lifecycle._canonical_bytes(evidence)
        evidence_path.write_bytes(changed_evidence)

        with self.assertRaisesRegex(
            release_lifecycle.ReleaseLifecycleError, "not proven product-owned"
        ):
            manager.ensure("tx-unproven-repair", "repair")

        self.assertEqual(dispatcher.read_bytes(), drifted)
        self.assertEqual(evidence_path.read_bytes(), changed_evidence)
        self.assertFalse((paths.runtime_root / "infrastructure-backups").exists())

    def test_codex_commands_use_installation_home_not_parent_environment(self) -> None:
        paths = self._paths()
        host = release_lifecycle.ArtifactHost(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
        )
        completed = SimpleNamespace(returncode=0, stdout=b'{"installed":[]}', stderr=b"")
        with (
            mock.patch.dict(
                os.environ,
                {"CODEX_HOME": str(self.root / "hostile parent Codex home")},
            ),
            mock.patch.object(
                release_lifecycle.subprocess, "run", return_value=completed
            ) as invoked,
        ):
            self.assertIsNone(host._plugin())
        environment = invoked.call_args.kwargs["env"]
        self.assertEqual(environment["CODEX_HOME"], str(paths.codex_home))
        self.assertNotEqual(environment["CODEX_HOME"], os.environ.get("CODEX_HOME"))

    @unittest.skipIf(os.name == "nt", "POSIX infrastructure fixture")
    def test_infrastructure_commit_removes_transaction_backup(self) -> None:
        paths = self._paths()
        manager = release_lifecycle.InfrastructureManager(paths)
        owned = manager.ensure("tx-commit", "install")
        self.assertEqual(len(owned), 1)
        backup = Path(owned[0])
        self.assertTrue(backup.is_dir())
        self.assertEqual(manager.commit("tx-commit"), ())
        self.assertFalse(backup.exists())
        self.assertTrue((paths.bin_dir / "dev-flow").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX migration launcher fixture")
    def test_migration_dispatcher_change_has_exact_transaction_rollback(self) -> None:
        paths = self._paths()
        originals = {
            "dev-flow": b"#!/bin/sh\n# dev-flow-orchestrator managed CLI launcher\nexit 0\n",
            "dev-flow-mcp": b"#!/bin/sh\n# dev-flow-orchestrator managed MCP launcher\nexit 0\n",
        }
        for name, raw in originals.items():
            path = paths.bin_dir / name
            path.write_bytes(raw)
            path.chmod(0o711 if name == "dev-flow" else 0o755)
        manager = release_lifecycle.InfrastructureManager(paths)
        manager.ensure("tx-migration", "migration")
        self.assertNotEqual((paths.bin_dir / "dev-flow").read_bytes(), originals["dev-flow"])
        self.assertEqual(manager.rollback("tx-migration"), ())
        for name, raw in originals.items():
            self.assertEqual((paths.bin_dir / name).read_bytes(), raw)
        self.assertEqual(
            stat.S_IMODE((paths.bin_dir / "dev-flow").stat().st_mode), 0o711
        )
        self.assertFalse((paths.bin_dir / "dev-flow-uninstall").exists())
        self.assertFalse((paths.runtime_root / "lifecycle" / "installation.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX infrastructure fixture")
    def test_migration_preserves_unrelated_uninstall_dispatcher(self) -> None:
        paths = self._paths()
        for name in ("dev-flow", "dev-flow-mcp"):
            _write_executable(
                paths.bin_dir / name,
                "#!/bin/sh\n# dev-flow-orchestrator managed {} launcher\n".format(
                    "CLI" if name == "dev-flow" else "MCP"
                ),
            )
        unrelated = paths.bin_dir / "dev-flow-uninstall"
        unrelated.write_bytes(b"user-owned bytes\n")
        manager = release_lifecycle.InfrastructureManager(paths)
        with self.assertRaisesRegex(
            release_lifecycle.ReleaseLifecycleError, "not the proven predecessor"
        ):
            manager.ensure("tx-migration", "migration")
        self.assertEqual(unrelated.read_bytes(), b"user-owned bytes\n")

    def test_operation_selection_is_bound_to_locked_active_observation(self) -> None:
        candidates = SimpleNamespace(
            index=SimpleNamespace(version="0.6.0"),
            active_version=lambda active: "0.6.0",
        )
        host = SimpleNamespace(product_present=lambda: False)
        absent = lifecycle_state.ActiveSnapshot(0, None, None)
        self.assertEqual(
            release_lifecycle._operation(absent, candidates, host), "install"
        )
        host.product_present = lambda: True
        self.assertEqual(
            release_lifecycle._operation(absent, candidates, host), "migration"
        )
        record = lifecycle_state.ActiveRecord(
            1,
            "release-a",
            str(self.root / "releases" / "release-a"),
            "a" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-a",
        )
        active = lifecycle_state.ActiveSnapshot(1, "b" * 64, record)
        self.assertEqual(
            release_lifecycle._operation(active, candidates, host), "repair"
        )
        candidates.active_version = lambda active: "0.5.0"
        self.assertEqual(
            release_lifecycle._operation(active, candidates, host), "upgrade"
        )

    def test_success_cleanup_removes_only_proven_inactive_release_and_backup(self) -> None:
        paths = self._paths()
        previous_path = paths.runtime_root / "releases" / "release-old"
        active_path = paths.runtime_root / "releases" / "release-new"
        previous_path.mkdir(parents=True)
        active_path.mkdir()
        receipt = {
            "release_id": "release-old",
            "runtime_path": str(previous_path),
            "transaction_id": "tx-old",
        }
        receipt_raw = release_lifecycle._canonical_bytes(receipt)
        (previous_path / "runtime-receipt.json").write_bytes(receipt_raw)
        previous = lifecycle_state.ActiveRecord(
            1,
            "release-old",
            str(previous_path),
            hashlib.sha256(receipt_raw).hexdigest(),
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-old",
        )
        active = lifecycle_state.ActiveRecord(
            2,
            "release-new",
            str(active_path),
            "d" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-new",
        )
        infrastructure = mock.Mock()
        infrastructure.commit.return_value = ()
        candidates = release_lifecycle.ArtifactCandidates(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            infrastructure,
        )
        with (
            mock.patch.object(
                release_lifecycle.runtime_integrity,
                "validate_artifact_runtime_receipt",
                return_value=receipt,
            ),
            mock.patch.object(
                release_lifecycle.runtime_integrity,
                "remove_owned_release",
                return_value={"retained_paths": []},
            ) as remove,
        ):
            evidence = candidates.cleanup_inactive(previous, active)
        self.assertTrue(evidence.exact)
        remove.assert_called_once_with(previous_path)
        infrastructure.commit.assert_called_once_with("tx-new")

    def test_success_cleanup_reports_inactive_residue_without_touching_active(self) -> None:
        paths = self._paths()
        previous_path = paths.runtime_root / "releases" / "release-old"
        active_path = paths.runtime_root / "releases" / "release-new"
        previous_path.mkdir(parents=True)
        active_path.mkdir()
        previous = lifecycle_state.ActiveRecord(
            1,
            "release-old",
            str(previous_path),
            "a" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-old",
        )
        active = lifecycle_state.ActiveRecord(
            2,
            "release-new",
            str(active_path),
            "b" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-new",
        )
        infrastructure = mock.Mock()
        infrastructure.commit.return_value = (str(paths.runtime_root / "backup"),)
        candidates = release_lifecycle.ArtifactCandidates(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            infrastructure,
        )
        evidence = candidates.cleanup_inactive(previous, active)
        self.assertFalse(evidence.exact)
        self.assertIn(str(previous_path), evidence.retained_paths)
        self.assertTrue(active_path.is_dir())

    def test_interrupted_inactive_cleanup_accepts_already_absent_previous(self) -> None:
        paths = self._paths()
        previous_path = paths.runtime_root / "releases" / "release-old"
        active_path = paths.runtime_root / "releases" / "release-new"
        active_path.mkdir(parents=True)
        previous = lifecycle_state.ActiveRecord(
            1,
            "release-old",
            str(previous_path),
            "a" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-old",
        )
        active = lifecycle_state.ActiveRecord(
            2,
            "release-new",
            str(active_path),
            "b" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-new",
        )
        infrastructure = mock.Mock()
        infrastructure.commit.return_value = ()
        candidates = release_lifecycle.ArtifactCandidates(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            infrastructure,
        )

        evidence = candidates.cleanup_inactive(previous, active)

        self.assertTrue(evidence.exact)
        self.assertEqual(evidence.retained_paths, ())
        self.assertEqual(evidence.observations[0].state, "absent")

    def test_auto_driver_selects_operation_and_runs_machine_under_one_lock(self) -> None:
        events: list[str] = []
        absent = lifecycle_state.ActiveSnapshot(0, None, None)

        class FakeState:
            @contextmanager
            def lock(self, timeout_seconds: float):
                events.append("lock-acquired")
                yield object()
                events.append("lock-released")

            def non_terminal_transactions(self, token):
                return ()

            def require_no_non_terminal(self, token):
                events.append("journals-clear")

            def read_active(self, token):
                events.append("active-read")
                return absent

        class FakeInfrastructure:
            pass

        class FakeMachine:
            state = FakeState()
            lock_timeout_seconds = 7.0

            def _run_locked(self, token, request):
                events.append("machine:" + request.operation)
                return SimpleNamespace(
                    transaction_id=request.transaction_id,
                    outcome="committed",
                    active=absent,
                    reused=False,
                    detail=None,
                )

        paths = self._paths()
        identity = release_lifecycle.IndexIdentity(
            "0.6.0", "a" * 64, "b" * 64, "c" * 64
        )
        candidates = SimpleNamespace(
            index=identity,
            active_version=lambda active: None,
            infrastructure=FakeInfrastructure(),
        )
        host = SimpleNamespace(product_present=lambda: True)
        result = release_lifecycle.run_locked_auto(
            FakeMachine(), candidates, host, paths, identity
        )
        self.assertEqual(result.outcome, "committed")
        self.assertEqual(
            events,
            [
                "lock-acquired",
                "journals-clear",
                "active-read",
                "machine:migration",
                "lock-released",
            ],
        )

    @unittest.skipIf(os.name == "nt", "POSIX public dispatcher fixture")
    def test_public_proof_uses_real_cli_and_mcp_dispatcher_paths(self) -> None:
        paths = self._paths()
        release = paths.runtime_root / "releases" / "release-a"
        release.mkdir(parents=True)
        (release / "runtime-receipt.json").write_text(
            json.dumps({"version": "0.6.0"}), encoding="utf-8"
        )
        _write_executable(
            paths.bin_dir / "dev-flow",
            "#!/bin/sh\nprintf '%s\\n' '{\"tasks\":[]}'\n",
        )
        _write_executable(
            paths.bin_dir / "dev-flow-mcp",
            "#!/bin/sh\n"
            "IFS= read -r request\n"
            "printf '%s\\n' '{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"serverInfo\":{\"name\":\"dev-flow\",\"version\":\"0.6.0\"}}}'\n",
        )
        host = release_lifecycle.ArtifactHost(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
        )
        active = lifecycle_state.ActiveRecord(
            1,
            "release-a",
            str(release),
            "d" * 64,
            lifecycle_state.DISPATCHER_PROTOCOL,
            "tx-a",
        )
        proof = host.public_proof(active)
        self.assertTrue(proof.exact, proof.observations)
        self.assertEqual(
            [item.subject for item in proof.observations],
            ["public-cli-startup", "public-mcp-startup"],
        )

    def test_migration_restores_infrastructure_before_proving_predecessor(self) -> None:
        paths = self._paths()
        events: list[str] = []
        infrastructure = mock.Mock()
        infrastructure.rollback.side_effect = lambda transaction_id: (
            events.append("infrastructure"),
            (),
        )[1]
        host = release_lifecycle.ArtifactHost(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            infrastructure,
        )
        previous_plugin = {
            "plugin_id": release_lifecycle.PLUGIN_ID,
            "installed": True,
            "enabled": True,
            "version": "0.5.0",
        }
        host._previous = {
            "marketplace_file_existed": True,
            "marketplace_entry": {"name": release_lifecycle.PLUGIN_NAME},
            "plugin": previous_plugin,
        }
        candidate_plugin = dict(previous_plugin, version="0.6.0")
        with (
            mock.patch.object(
                host,
                "_marketplace",
                side_effect=lambda: (
                    events.append("marketplace"),
                    ({"plugins": []}, True, {"name": release_lifecycle.PLUGIN_NAME}),
                )[1],
            ),
            mock.patch.object(host, "_replace_marketplace"),
            mock.patch.object(host, "_plugin", side_effect=[candidate_plugin, previous_plugin]),
            mock.patch.object(
                release_lifecycle,
                "_run",
                return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            ),
        ):
            restored = host.restore_previous(
                SimpleNamespace(operation="migration", transaction_id="tx-migration")
            )
        self.assertTrue(restored.exact)
        self.assertEqual(events[:2], ["infrastructure", "marketplace"])
        with mock.patch.object(host, "_public_release", return_value=(True, True)) as proof:
            self.assertTrue(host.public_proof(None).exact)
        proof.assert_called_once_with("0.5.0")

    def test_proven_untouched_predecessor_can_be_publicly_reproved(self) -> None:
        paths = self._paths()
        host = release_lifecycle.ArtifactHost(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
        )
        classifier = release_lifecycle.FrozenMigration(paths, host)
        plugin = {
            "plugin_id": release_lifecycle.PLUGIN_ID,
            "installed": True,
            "enabled": True,
            "version": "0.5.0",
        }
        proven = {
            "version": "0.5.0",
            "receipt_sha256": "d" * 64,
        }
        with (
            mock.patch.object(host, "_plugin", return_value=plugin),
            mock.patch.object(
                release_lifecycle.legacy_migration,
                "classify_predecessor",
                return_value=proven,
            ),
        ):
            classification = classifier.classify()
        self.assertTrue(classification.exact_predecessor)
        with mock.patch.object(host, "_public_release", return_value=(True, True)) as proof:
            self.assertTrue(host.public_proof(None).exact)
        proof.assert_called_once_with("0.5.0")

    def test_migration_stops_when_infrastructure_restoration_is_uncertain(self) -> None:
        paths = self._paths()
        infrastructure = mock.Mock()
        retained = str(paths.runtime_root / "infrastructure-backups" / "tx-migration")
        infrastructure.rollback.return_value = (retained,)
        host = release_lifecycle.ArtifactHost(
            paths,
            release_lifecycle.IndexIdentity(
                "0.6.0", "a" * 64, "b" * 64, "c" * 64
            ),
            infrastructure,
        )
        with mock.patch.object(host, "_marketplace") as marketplace:
            restored = host.restore_previous(
                SimpleNamespace(operation="migration", transaction_id="tx-migration")
            )
        self.assertFalse(restored.exact)
        self.assertEqual(restored.retained_paths, (retained,))
        marketplace.assert_not_called()

    def test_terminal_json_and_exit_code_never_treat_rollback_as_success(self) -> None:
        paths = self._paths()
        identity = release_lifecycle.IndexIdentity(
            "0.6.0", "a" * 64, "b" * 64, "c" * 64
        )
        committed = SimpleNamespace(
            outcome="committed",
            transaction_id="tx-committed",
            reused=False,
            recovered_transactions=(),
            active=lifecycle_state.ActiveSnapshot(0, None, None),
            detail=None,
        )
        rolled_back = SimpleNamespace(
            outcome="rolled_back",
            transaction_id="tx-rollback",
            reused=False,
            recovered_transactions=(),
            active=lifecycle_state.ActiveSnapshot(0, None, None),
            detail="candidate failed",
        )
        argv = [
            "install",
            "--artifact-root",
            str(paths.artifact_root),
            "--release-index",
            str(paths.release_index),
            "--release-index-sha256",
            "a" * 64,
        ]
        for result, expected in ((committed, 0), (rolled_back, 1)):
            output = StringIO()
            with (
                mock.patch.dict(os.environ, {}, clear=False),
                mock.patch.object(release_lifecycle, "resolve_install_paths", return_value=paths),
                mock.patch.object(release_lifecycle, "load_index_identity", return_value=identity),
                mock.patch.object(release_lifecycle, "execute_install", return_value=result),
                redirect_stdout(output),
            ):
                os.environ.pop("DEV_FLOW_SOURCE_ROOT", None)
                self.assertEqual(release_lifecycle.main(argv), expected)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["outcome"], result.outcome)
            self.assertEqual(payload["ok"], result.outcome == "committed")


if __name__ == "__main__":
    unittest.main()
