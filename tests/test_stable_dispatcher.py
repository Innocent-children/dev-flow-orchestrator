from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stable_dispatcher", ROOT / "scripts" / "stable_dispatcher.py"
)
assert SPEC is not None and SPEC.loader is not None
dispatcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dispatcher)


def _write_json(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def _installation_value(
    lifecycle: Path,
    runtime: Path,
    base: Path,
) -> dict[str, object]:
    stable = lifecycle / "stable_dispatcher.py"
    state = lifecycle / "lifecycle_state.py"
    driver = lifecycle / "uninstall_driver.py"
    commands = lifecycle / "release_commands.py"
    resolver = lifecycle / "release_resolver.py"
    return {
        "schema": dispatcher.INSTALLATION_SCHEMA,
        "dispatcher_protocol": dispatcher.DISPATCHER_PROTOCOL,
        "uninstall_driver_sha256": hashlib.sha256(driver.read_bytes()).hexdigest(),
        "stable_dispatcher_sha256": hashlib.sha256(stable.read_bytes()).hexdigest(),
        "lifecycle_state_sha256": hashlib.sha256(state.read_bytes()).hexdigest(),
        "release_commands_sha256": hashlib.sha256(commands.read_bytes()).hexdigest(),
        "release_resolver_sha256": hashlib.sha256(resolver.read_bytes()).hexdigest(),
        "dispatchers": {
            "dev-flow": "c" * 64,
            "dev-flow-mcp": "d" * 64,
            "dev-flow-uninstall": "e" * 64,
        },
        "bin_dir": str(base / "bin space"),
        "marketplace_file": str(base / ".agents" / "plugins" / "marketplace.json"),
        "codex_home": str(base / "isolated codex home"),
        "plugin_id": "dev-flow-orchestrator@personal",
        "runtime_root": str(runtime),
        "data_root": str(base / "task data root"),
        "data_owned_paths": ["0.4.0", "web-runtime"],
        "data_marker_name": "dev-flow-data.json",
    }


class StableDispatcherTests(unittest.TestCase):
    def _installation(self, base: Path) -> tuple[Path, Path, dict[str, object]]:
        runtime = base / "运行 root's space"
        release = runtime / "releases" / "r-0.6.0-test"
        (release / "integrity").mkdir(parents=True)
        python = release / "venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_bytes(b"python")
        verifier = release / "integrity" / "runtime_integrity.py"
        verifier.write_bytes(b"# verifier\n")
        transaction_id = "tx-0123456789abcdef"
        receipt = {
            "schema": dispatcher.RUNTIME_RECEIPT_SCHEMA,
            "release_id": release.name,
            "runtime_path": str(release),
            "transaction_id": transaction_id,
            "verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
            "python_executable_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
            "additional_complete_receipt_evidence": {},
        }
        receipt_raw = _write_json(release / "runtime-receipt.json", receipt)
        active = {
            "schema": dispatcher.ACTIVE_SCHEMA,
            "generation": 1,
            "release_id": release.name,
            "release_path": str(release),
            "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "dispatcher_protocol": dispatcher.DISPATCHER_PROTOCOL,
            "transaction_id": transaction_id,
        }
        _write_json(runtime / "active.json", active)
        return runtime, release, active

    def test_prepares_cli_and_exact_stdio_through_attested_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, release, _ = self._installation(Path(temporary))
            cli = dispatcher.prepare_active_command(runtime, "cli", ["web", "status"])
            self.assertEqual(cli[-2:], ["web", "status"])
            self.assertEqual(cli[3], str(release / "integrity" / "runtime_integrity.py"))
            mcp = dispatcher.prepare_active_command(runtime, "mcp", ["--stdio"])
            self.assertEqual(mcp[-1], "--stdio")
            with self.assertRaisesRegex(dispatcher.DispatchError, "exactly --stdio"):
                dispatcher.prepare_active_command(runtime, "mcp", [])

    def test_active_is_closed_and_receipt_and_verifier_are_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, release, active = self._installation(Path(temporary))
            active["unknown"] = True
            _write_json(runtime / "active.json", active)
            with self.assertRaisesRegex(dispatcher.DispatchError, "fields or schema"):
                dispatcher.resolve_active(runtime)
            del active["unknown"]
            _write_json(runtime / "active.json", active)
            (release / "integrity" / "runtime_integrity.py").write_bytes(b"drift")
            with self.assertRaisesRegex(dispatcher.DispatchError, "verifier digest"):
                dispatcher.resolve_active(runtime)

    def test_duplicate_active_member_and_release_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _release, active = self._installation(Path(temporary))
            raw = json.dumps(active)
            (runtime / "active.json").write_text(
                raw[:-1] + ', "generation": 1}', encoding="utf-8"
            )
            with self.assertRaisesRegex(dispatcher.DispatchError, "duplicate"):
                dispatcher.resolve_active(runtime)
            active["release_path"] = str(Path(temporary) / "elsewhere")
            _write_json(runtime / "active.json", active)
            with self.assertRaisesRegex(dispatcher.DispatchError, "escapes"):
                dispatcher.resolve_active(runtime)

    def test_uninstall_driver_is_verified_and_copied_outside_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _release, _ = self._installation(Path(temporary))
            lifecycle = runtime / "lifecycle"
            lifecycle.mkdir()
            stable = lifecycle / "stable_dispatcher.py"
            stable.write_bytes((ROOT / "scripts" / "stable_dispatcher.py").read_bytes())
            state = lifecycle / "lifecycle_state.py"
            state.write_bytes(b"# lifecycle state\n")
            driver = lifecycle / "uninstall_driver.py"
            driver.write_bytes(b"# removal driver\n")
            commands = lifecycle / "release_commands.py"
            commands.write_bytes(b"# release commands\n")
            resolver = lifecycle / "release_resolver.py"
            resolver.write_bytes(b"# release resolver\n")
            _write_json(
                lifecycle / "installation.json",
                _installation_value(lifecycle, runtime, Path(temporary)),
            )
            with mock.patch.object(dispatcher, "__file__", str(stable)):
                command, copied_root = dispatcher._prepare_uninstall(runtime)
            try:
                self.assertNotEqual(copied_root.parent, runtime)
                self.assertEqual(Path(command[3]).read_bytes(), driver.read_bytes())
                self.assertEqual(command[-2:], ["--support-root", str(lifecycle)])
            finally:
                Path(command[3]).unlink()
                copied_root.rmdir()

    def test_uninstall_rejects_stable_dispatcher_or_state_drift_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _release, _ = self._installation(Path(temporary))
            lifecycle = runtime / "lifecycle"
            lifecycle.mkdir()
            stable = lifecycle / "stable_dispatcher.py"
            stable.write_bytes((ROOT / "scripts" / "stable_dispatcher.py").read_bytes())
            state = lifecycle / "lifecycle_state.py"
            state.write_bytes(b"# lifecycle state\n")
            driver = lifecycle / "uninstall_driver.py"
            driver.write_bytes(b"# removal driver\n")
            commands = lifecycle / "release_commands.py"
            commands.write_bytes(b"# release commands\n")
            resolver = lifecycle / "release_resolver.py"
            resolver.write_bytes(b"# release resolver\n")
            installation = _installation_value(lifecycle, runtime, Path(temporary))
            installation["bin_dir"] = str(Path(temporary) / "bin")
            installation["marketplace_file"] = str(Path(temporary) / "marketplace.json")
            _write_json(lifecycle / "installation.json", installation)
            with mock.patch.object(dispatcher, "__file__", str(stable)):
                stable.write_bytes(b"drift")
                with self.assertRaisesRegex(dispatcher.DispatchError, "stable dispatcher digest"):
                    dispatcher._prepare_uninstall(runtime)
                stable.write_bytes((ROOT / "scripts" / "stable_dispatcher.py").read_bytes())
                installation["stable_dispatcher_sha256"] = hashlib.sha256(
                    stable.read_bytes()
                ).hexdigest()
                _write_json(lifecycle / "installation.json", installation)
                state.write_bytes(b"state drift")
                with self.assertRaisesRegex(dispatcher.DispatchError, "state helper digest"):
                    dispatcher._prepare_uninstall(runtime)

    def test_posix_venv_python_symlink_is_digest_bound(self) -> None:
        if __import__("os").name == "nt":
            self.skipTest("POSIX venv-link behavior")
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, release, active = self._installation(base)
            python = release / "venv" / "bin" / "python"
            target = base / "system python"
            target.write_bytes(b"real interpreter")
            python.unlink()
            python.symlink_to(target)
            receipt_path = release / "runtime-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["python_executable_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
            receipt_raw = _write_json(receipt_path, receipt)
            active["receipt_sha256"] = hashlib.sha256(receipt_raw).hexdigest()
            _write_json(runtime / "active.json", active)
            self.assertEqual(
                dispatcher.resolve_active(runtime)["runtime_python"], str(python)
            )


if __name__ == "__main__":
    unittest.main()


class StableDispatcherLifecycleCommandTests(unittest.TestCase):
    def _support(self, base: Path) -> tuple[Path, Path]:
        runtime = base / "运行 root's space"
        (runtime / "lifecycle").mkdir(parents=True)
        lifecycle = runtime / "lifecycle"
        stable = lifecycle / "stable_dispatcher.py"
        stable.write_bytes((ROOT / "scripts" / "stable_dispatcher.py").read_bytes())
        (lifecycle / "lifecycle_state.py").write_bytes(b"# lifecycle state\n")
        (lifecycle / "uninstall_driver.py").write_bytes(b"# removal driver\n")
        (lifecycle / "release_commands.py").write_bytes(b"# release commands\n")
        (lifecycle / "release_resolver.py").write_bytes(b"# release resolver\n")
        installation = _installation_value(lifecycle, runtime, base)
        _write_json(lifecycle / "installation.json", installation)
        return runtime, lifecycle

    def test_update_and_reinstall_run_without_active_release_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            # A corrupt active record must not block lifecycle dispatch.
            (runtime / "active.json").write_text("{broken\n", encoding="utf-8")
            for mode in ("update", "reinstall"):
                with mock.patch.object(
                    dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
                ), mock.patch.object(
                    dispatcher.subprocess, "run", return_value=mock.Mock(returncode=0)
                ) as run:
                    command, copied_root = dispatcher._prepare_release_command(runtime, mode)
                    try:
                        self.assertEqual(run.call_count, 0)
                        self.assertEqual(Path(command[3]).read_bytes(), (lifecycle / "release_commands.py").read_bytes())
                        self.assertEqual(command[-2:], ["--mode", mode])
                    finally:
                        (copied_root / "release_commands.py").unlink()
                        copied_root.rmdir()

    def test_release_command_copy_resolves_linked_temporary_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            real_temporary = base / "real-temporary"
            real_temporary.mkdir()
            alias = base / "temporary-alias"
            try:
                alias.symlink_to(real_temporary, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            created = alias / "release-command-copy"
            created.mkdir()
            with (
                mock.patch.object(
                    dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
                ),
                mock.patch.object(
                    dispatcher.tempfile, "mkdtemp", return_value=str(created)
                ),
            ):
                command, copied_root = dispatcher._prepare_release_command(
                    runtime, "update"
                )
            try:
                self.assertEqual(copied_root, created.resolve())
                self.assertEqual(Path(command[3]).parent, created.resolve())
            finally:
                (copied_root / "release_commands.py").unlink()
                copied_root.rmdir()

    def test_update_rejects_extra_arguments_before_any_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            with mock.patch.object(
                dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
            ):
                self.assertEqual(
                    dispatcher.main(
                        ["--runtime-root", str(runtime), "cli", "update", "extra"]
                    ),
                    2,
                )

    def test_release_command_driver_digest_is_verified_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            (lifecycle / "release_commands.py").write_bytes(b"drifted driver\n")
            with mock.patch.object(
                dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
            ):
                with self.assertRaisesRegex(dispatcher.DispatchError, "release command driver digest"):
                    dispatcher._prepare_release_command(runtime, "update")

    def test_installed_evidence_requires_data_ownership_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            installation = json.loads(
                (lifecycle / "installation.json").read_text(encoding="utf-8")
            )
            del installation["data_root"]
            _write_json(lifecycle / "installation.json", installation)
            with mock.patch.object(
                dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
            ):
                with self.assertRaisesRegex(dispatcher.DispatchError, "installation record is incompatible"):
                    dispatcher._prepare_release_command(runtime, "update")

    def test_installed_evidence_rejects_broadened_data_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            runtime, lifecycle = self._support(base)
            installation = json.loads(
                (lifecycle / "installation.json").read_text(encoding="utf-8")
            )
            installation["data_owned_paths"].append("user-content")
            _write_json(lifecycle / "installation.json", installation)
            with mock.patch.object(
                dispatcher, "__file__", str(lifecycle / "stable_dispatcher.py")
            ):
                with self.assertRaisesRegex(
                    dispatcher.DispatchError, "ownership paths"
                ):
                    dispatcher._prepare_release_command(runtime, "reinstall")
