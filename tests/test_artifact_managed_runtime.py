"""Focused artifact-backed managed runtime and v3 receipt tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import manage_runtime
from scripts import release_artifact
from scripts import runtime_integrity


HEX = "1" * 64
COMMIT = "2" * 40
TREE = "3" * 40


def _write_plugin(plugin: Path, version: str) -> dict[str, object]:
    (plugin / ".codex-plugin").mkdir(parents=True)
    (plugin / "skills" / "dev-flow").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    (plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "dev-flow-orchestrator", "version": version}),
        encoding="utf-8",
    )
    (plugin / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"dev-flow": {"command": "dev-flow-mcp", "args": ["--stdio"]}}}
        ),
        encoding="utf-8",
    )
    (plugin / "skills" / "dev-flow" / "SKILL.md").write_text(
        "---\nname: dev-flow\n---\n", encoding="utf-8"
    )
    (plugin / "scripts" / "validate_installed_stage1.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    (plugin / "scripts" / "validate_installed_stage1.py").chmod(0o755)
    entries = runtime_integrity.inventory_tree(plugin)
    body = {"source_commit": COMMIT, "source_tree": TREE, "entries": entries}
    content = hashlib.sha256(runtime_integrity.canonical_json_bytes(body)).hexdigest()
    release_id = "r-{}-{}".format(COMMIT[:12], content[:16])
    manifest = {
        "schema": runtime_integrity.PLUGIN_MANIFEST_SCHEMA,
        "release_id": release_id,
        "source_commit": COMMIT,
        "source_tree": TREE,
        "content_sha256": content,
        "entries": entries,
    }
    (plugin / "release-manifest.json").write_bytes(
        runtime_integrity.pretty_json_bytes(manifest)
    )
    return runtime_integrity.verify_plugin_release(plugin)


def _write_wheel(path: Path, version: str) -> None:
    dist_info = "dev_flow_orchestrator-{}.dist-info".format(version)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            dist_info + "/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            dist_info + "/METADATA",
            "Metadata-Version: 2.1\nName: dev-flow-orchestrator\nVersion: {}\n".format(version),
        )
        archive.writestr(dist_info + "/RECORD", "")
        archive.writestr("dev_flow_orchestrator/__init__.py", "")


def _write_artifact_manifest(artifact_root: Path, version: str) -> tuple[Path, str]:
    entries: list[dict[str, object]] = []
    for path in sorted(artifact_root.rglob("*")):
        relative = path.relative_to(artifact_root).as_posix()
        if relative == release_artifact.MANIFEST_NAME:
            continue
        if path.is_dir():
            path.chmod(0o755)
            entries.append(
                {"path": relative, "type": "directory", "mode": 0o755}
            )
        else:
            mode = release_artifact._expected_mode(relative, False)
            path.chmod(mode)
            raw = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    manifest = {
        "schema": release_artifact.ARTIFACT_SCHEMA,
        "version": version,
        "entries": entries,
    }
    path = artifact_root / release_artifact.MANIFEST_NAME
    path.write_bytes(release_artifact.canonical_json_bytes(manifest))
    path.chmod(0o644)
    return path, runtime_integrity.sha256_file(path)


def _receipt(runtime: Path, *, version: str = "0.6.0") -> dict[str, object]:
    python_relative = (
        Path("venv/Scripts/python.exe") if os.name == "nt" else Path("venv/bin/python")
    )
    lifecycle = [
        {"path": "lifecycle/" + name, "sha256": HEX}
        for name in sorted(
            (
                "manage_runtime.py",
                "release_artifact.py",
                "release_lifecycle.py",
                "runtime_integrity.py",
                "validate_installed_stage1.py",
            )
        )
    ]
    return {
        "schema": runtime_integrity.ARTIFACT_RUNTIME_RECEIPT_SCHEMA,
        "release_id": runtime.name,
        "version": version,
        "repository": runtime_integrity.CANONICAL_REPOSITORY,
        "source_commit": COMMIT,
        "source_tree": TREE,
        "release_index_sha256": "4" * 64,
        "archive_sha256": "5" * 64,
        "artifact_manifest_sha256": "6" * 64,
        "wheel_sha256": "7" * 64,
        "runtime_requirements_sha256": "8" * 64,
        "uv_lock_sha256": "9" * 64,
        "plugin_path": str(runtime / "plugin"),
        "plugin_release_manifest_sha256": "a" * 64,
        "dev_flow": {
            "name": "dev-flow-orchestrator",
            "version": version,
            "metadata_sha256": "b" * 64,
            "record_sha256": "c" * 64,
            "files": [],
        },
        "dependencies": [],
        "python": {
            "path": str(runtime / python_relative),
            "executable_sha256": "d" * 64,
            "version": "3.14.0",
            "architecture": "arm64",
            "bits": 64,
        },
        "python_executable_sha256": "d" * 64,
        "runtime_path": str(runtime),
        "transaction_id": "tx123",
        "verifier_sha256": "e" * 64,
        "lifecycle_helpers": lifecycle,
        "ownership_manifest_sha256": "f" * 64,
        "created_at": "2026-08-12T00:00:00Z",
    }


class ArtifactReceiptTests(unittest.TestCase):
    def test_distribution_inventory_rejects_site_packages_outside_managed_venv(self) -> None:
        with tempfile.TemporaryDirectory(prefix="artifact-distribution-root-") as temporary:
            base = Path(temporary).resolve()
            runtime = base / "runtime"
            expected_python = runtime / "venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            expected_python.parent.mkdir(parents=True)
            external = base / "external" / "site-packages"
            external.mkdir(parents=True)
            with (
                mock.patch.object(runtime_integrity.sys, "executable", str(expected_python)),
                mock.patch.object(runtime_integrity.sys, "path", [str(external)]),
            ):
                with self.assertRaisesRegex(runtime_integrity.IntegrityError, "escapes"):
                    runtime_integrity.installed_distribution_snapshot(runtime, runtime)

    def test_v3_receipt_is_closed_and_binds_dispatcher_minimum(self) -> None:
        runtime = Path(tempfile.gettempdir()) / "v0.6.0-1234567890abcdef-tx123"
        receipt = _receipt(runtime)
        validated = runtime_integrity.validate_artifact_runtime_receipt(receipt)
        self.assertEqual(validated["release_id"], runtime.name)
        self.assertEqual(validated["transaction_id"], "tx123")
        self.assertEqual(
            validated["python_executable_sha256"],
            validated["python"]["executable_sha256"],
        )
        changed = dict(receipt)
        changed["unknown"] = True
        with self.assertRaisesRegex(runtime_integrity.IntegrityError, "fields"):
            runtime_integrity.validate_artifact_runtime_receipt(changed)

    def test_same_version_digest_envelope_replacement_is_rejected(self) -> None:
        runtime = Path(tempfile.gettempdir()) / "v0.6.0-1234567890abcdef-tx123"
        active = _receipt(runtime)
        candidate = json.loads(json.dumps(active))
        candidate["archive_sha256"] = "0" * 64
        with self.assertRaisesRegex(runtime_integrity.IntegrityError, "same-version"):
            runtime_integrity.require_same_version_envelope(active, candidate)
        candidate["version"] = "0.7.0"
        candidate["dev_flow"]["version"] = "0.7.0"
        runtime_integrity.require_same_version_envelope(active, candidate)

    def test_exact_single_release_removal_supports_v3_and_retains_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="artifact-release-remove-") as temporary:
            release = Path(temporary).resolve() / "v0.6.0-1234567890abcdef-tx123"
            release.mkdir()
            payload = release / "owned.txt"
            payload.write_bytes(b"owned\n")
            ownership = runtime_integrity.build_ownership_manifest(release, release.name)
            ownership_path = release / runtime_integrity.OWNERSHIP_MANIFEST_NAME
            ownership_path.write_bytes(runtime_integrity.pretty_json_bytes(ownership))
            receipt = _receipt(release)
            receipt["ownership_manifest_sha256"] = runtime_integrity.sha256_file(
                ownership_path
            )
            (release / runtime_integrity.RUNTIME_RECEIPT_NAME).write_bytes(
                runtime_integrity.pretty_json_bytes(receipt)
            )
            payload.write_bytes(b"user changed\n")
            result = runtime_integrity.remove_owned_release(release)
            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "retained")
            self.assertTrue(payload.exists())
            self.assertIn(str(payload), result["retained_paths"])


class ArtifactCandidateBuildTests(unittest.TestCase):
    def test_builder_uses_only_supplied_wheel_and_wheel_only_hash_install(self) -> None:
        version = "0.6.0"
        with tempfile.TemporaryDirectory(prefix="artifact-candidate-") as temporary:
            base = Path(temporary).resolve()
            artifact = base / ("dev-flow-orchestrator-" + version)
            artifact.mkdir()
            plugin_seal = _write_plugin(artifact / "plugin", version)
            wheels = artifact / "wheels"
            wheels.mkdir()
            wheel = wheels / ("dev_flow_orchestrator-{}-py3-none-any.whl".format(version))
            _write_wheel(wheel, version)
            (artifact / "runtime-requirements.txt").write_text(
                "mcp==2.0.0 \\\n    --hash=sha256:{}\n".format("0" * 64),
                encoding="utf-8",
            )
            (artifact / "uv.lock").write_text("version = 1\n", encoding="utf-8")
            lifecycle = artifact / "lifecycle"
            lifecycle.mkdir()
            for name in (
                "manage_runtime.py",
                "release_artifact.py",
                "release_lifecycle.py",
                "runtime_integrity.py",
                "validate_installed_stage1.py",
                "lifecycle_state.py",
                "lifecycle_machine.py",
                "legacy_migration.py",
                "render_dispatchers.py",
                "stable_dispatcher.py",
                "uninstall_driver.py",
            ):
                source = ROOT / "scripts" / name
                (lifecycle / name).write_bytes(
                    source.read_bytes() if source.exists() else b"# fixture\n"
                )
            (lifecycle / "legacy_predecessor.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            manifest_path, manifest_digest = _write_artifact_manifest(
                artifact,
                version,
            )
            index = {
                "schema": "dev-flow-release-index/1.0.0",
                "artifact_schema": "dev-flow-release-artifact/1.0.0",
                "repository": runtime_integrity.CANONICAL_REPOSITORY,
                "version": version,
                "source_commit": COMMIT,
                "source_tree": TREE,
                "archive": {
                    "name": "dev-flow-orchestrator-{}.tar.gz".format(version),
                    "size": 123,
                    "sha256": "5" * 64,
                },
                "manifest_sha256": manifest_digest,
                "limits": dict(release_artifact.HARD_LIMITS),
            }
            index_path = base / "release-index.json"
            index_path.write_bytes(runtime_integrity.pretty_json_bytes(index))
            index_digest = runtime_integrity.sha256_file(index_path)
            release_id = "v{}-{}-tx123".format(version, manifest_digest[:16])
            target = base / "runtime" / "releases" / release_id
            receipt = _receipt(target)
            receipt.update(
                {
                    "release_id": release_id,
                    "runtime_path": str(target),
                    "plugin_path": str(target / "plugin"),
                    "release_index_sha256": index_digest,
                    "archive_sha256": "5" * 64,
                    "artifact_manifest_sha256": manifest_digest,
                    "plugin_release_manifest_sha256": plugin_seal["manifest_sha256"],
                }
            )
            commands: list[list[str]] = []

            def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                commands.append(list(arguments))
                if arguments[:2] == ["/usr/bin/uv", "venv"]:
                    venv = Path(arguments[-1])
                    python = venv / (
                        "Scripts/python.exe" if os.name == "nt" else "bin/python"
                    )
                    python.parent.mkdir(parents=True)
                    python.write_bytes(b"fixture-python\n")
                    python.chmod(0o755)
                    output = ""
                elif "-c" in arguments:
                    output = json.dumps(
                        {"version": [3, 14, 0], "bits": 64, "architecture": "arm64", "mcp": "2.0.0"}
                    )
                elif "build-artifact-receipt" in arguments:
                    output = json.dumps({"ok": True, "receipt": receipt})
                elif "verify-artifact-runtime" in arguments:
                    output = json.dumps({"ok": True, "receipt": receipt})
                elif any("validate_installed_stage1.py" in item for item in arguments):
                    output = json.dumps(
                        {
                            "ok": True,
                            "journey": {
                                "read_smoke": True,
                                "candidate_smoke": True,
                                "mutation_smoke": False,
                                "terminal_status": None,
                            },
                        }
                    )
                else:
                    output = ""
                return subprocess.CompletedProcess(arguments, 0, output, "")

            with (
                mock.patch.object(manage_runtime.shutil, "which", return_value="/usr/bin/uv"),
                mock.patch.object(manage_runtime, "_run", side_effect=fake_run),
            ):
                result = manage_runtime.build_artifact_candidate(
                    artifact,
                    base / "runtime",
                    index_path,
                    index_digest,
                    "tx123",
                    expected_release_id=release_id,
                )
            self.assertTrue(result["staged_health"])
            self.assertEqual(result["release_id"], release_id)
            uv_commands = [command for command in commands if command[:2] == ["/usr/bin/uv", "pip"]]
            self.assertEqual(len(uv_commands), 2)
            dependency_install, project_install = uv_commands
            self.assertIn("--require-hashes", dependency_install)
            self.assertIn("--only-binary", dependency_install)
            self.assertIn(":all:", dependency_install)
            self.assertIn("--no-deps", project_install)
            self.assertIn("--only-binary", project_install)
            self.assertFalse(any("build" in command[1:2] for command in commands))
            verify_positions = [
                index for index, command in enumerate(commands)
                if "verify-artifact-runtime" in command
            ]
            smoke_position = next(
                index for index, command in enumerate(commands)
                if any("validate_installed_stage1.py" in item for item in command)
            )
            self.assertIn("--candidate-smoke-only", commands[smoke_position])
            self.assertNotIn("--smoke-only", commands[smoke_position])
            self.assertLess(verify_positions[0], smoke_position)
            self.assertTrue(Path(result["runtime_dir"]).is_dir())

            with self.assertRaisesRegex(manage_runtime.RuntimeBuildError, "release_id"):
                manage_runtime.build_artifact_candidate(
                    artifact,
                    base / "another-runtime",
                    index_path,
                    index_digest,
                    "tx456",
                    expected_release_id=release_id,
                )

            for offset, path in enumerate((wheel, lifecycle / "release_lifecycle.py")):
                with self.subTest(replaced=path.name):
                    original = path.read_bytes()
                    path.write_bytes(b"replacement after Phase A\n")
                    try:
                        with (
                            mock.patch.object(manage_runtime, "_run") as run,
                            self.assertRaisesRegex(
                                manage_runtime.RuntimeBuildError,
                                "live artifact inventory",
                            ),
                        ):
                            manage_runtime.build_artifact_candidate(
                                artifact,
                                base / "replacement-runtime-{}".format(offset),
                                index_path,
                                index_digest,
                                "tx-replaced-{}".format(offset),
                            )
                        run.assert_not_called()
                    finally:
                        path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
