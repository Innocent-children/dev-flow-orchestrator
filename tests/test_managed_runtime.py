"""Focused managed-runtime and wheel asset boundaries."""

from __future__ import annotations

import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.product import WORKFLOW_IDS
from dev_flow_orchestrator.workflows import load_definition
from scripts import manage_runtime
from scripts import runtime_integrity
from support import hermetic_subprocess_env, probe_subprocess_runtime_roots


class ManagedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._candidate_temporary = tempfile.TemporaryDirectory(
            prefix="dev-flow-sealed-candidate-"
        )
        base = Path(cls._candidate_temporary.name)
        repository = base / "repository"
        ignored = shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
            ".mypy_cache", ".codebase-memory", "dist", "build",
        )
        shutil.copytree(ROOT, repository, symlinks=True, ignore=ignored)
        executable = repository / "sealed-executable.sh"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
        if os.name != "nt":
            (repository / "sealed-link").symlink_to("sealed-executable.sh")
        environment = hermetic_subprocess_env(base)
        commands = (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "runtime@example.invalid"],
            ["git", "config", "user.name", "Runtime Test"],
            ["git", "add", "-A"],
            ["git", "commit", "-qm", "sealed candidate"],
        )
        for command in commands:
            subprocess.run(command, cwd=repository, env=environment, check=True)
        cls.source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, env=environment,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        cls.source_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=repository, env=environment,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        archive = base / "candidate.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", "-o", str(archive), "HEAD"],
            cwd=repository, env=environment, check=True,
        )
        sealed = base / "sealed"
        result = runtime_integrity.seal_archive(
            archive, sealed, cls.source_commit, cls.source_tree
        )
        cls.sealed = sealed
        cls.release_id = str(result["release_id"])
        (repository / "scripts" / "runtime_integrity.py").unlink()
        subprocess.run(
            ["git", "add", "-A"], cwd=repository, env=environment, check=True
        )
        subprocess.run(
            ["git", "commit", "-qm", "legacy source without runtime helper"],
            cwd=repository, env=environment, check=True,
        )
        cls.legacy_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repository, env=environment,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        cls.legacy_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=repository, env=environment,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        legacy_archive = base / "legacy.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", "-o", str(legacy_archive), "HEAD"],
            cwd=repository, env=environment, check=True,
        )
        legacy_sealed = base / "legacy-sealed"
        legacy_result = runtime_integrity.seal_archive(
            legacy_archive, legacy_sealed, cls.legacy_commit, cls.legacy_tree
        )
        cls.legacy_sealed = legacy_sealed
        cls.legacy_release_id = str(legacy_result["release_id"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._candidate_temporary.cleanup()

    def test_real_locked_runtime_create_receipt_smoke_and_reuse(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required for managed-runtime integration")
        with tempfile.TemporaryDirectory(prefix="dev-flow-managed-runtime-") as temporary:
            base = Path(temporary)
            environment = hermetic_subprocess_env(base)
            roots = probe_subprocess_runtime_roots(base, environment)
            self.assertTrue(roots["data"].is_relative_to(base.resolve()))
            self.assertTrue(roots["runtime"].is_relative_to(base.resolve()))
            status_before = subprocess.run(
                ["git", "status", "--porcelain", "--ignored"],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            runtime_root = base / "runtime with spaces 雪's"
            data_root = base / "task data"
            data_root.mkdir()
            sentinel = data_root / "existing-task-bytes"
            sentinel.write_bytes(b"unchanged\n")

            with mock.patch.dict(os.environ, environment, clear=True):
                created = manage_runtime.build(
                    self.sealed, runtime_root, self.source_commit, self.source_tree,
                    self.release_id, data_root,
                )
                reused = manage_runtime.build(
                    self.sealed, runtime_root, self.source_commit, self.source_tree,
                    self.release_id, data_root,
                )

            self.assertTrue(created["ok"])
            self.assertFalse(created["reused"])
            self.assertTrue(reused["reused"])
            self.assertEqual(created["runtime_dir"], reused["runtime_dir"])
            self.assertEqual(created["receipt"], reused["receipt"])
            receipt = created["receipt"]
            self.assertEqual(receipt["schema"], runtime_integrity.RUNTIME_RECEIPT_SCHEMA)
            self.assertEqual(receipt["source_commit"], self.source_commit)
            self.assertEqual(receipt["source_tree"], self.source_tree)
            self.assertEqual(receipt["release_id"], self.release_id)
            self.assertEqual(Path(created["plugin_root"]).parent, Path(created["runtime_dir"]))
            installed_plugin = Path(created["plugin_root"])
            skill_files = (
                "skills/dev-flow/SKILL.md",
                "skills/dev-flow/agents/openai.yaml",
                "skills/dev-flow/references/activation-and-routing.md",
            )
            for relative in skill_files:
                self.assertEqual(
                    (installed_plugin / relative).read_bytes(),
                    (ROOT / relative).read_bytes(),
                )
            self.assertEqual(len(receipt["wheel_sha256"]), 64)
            self.assertEqual(len(receipt["launcher_sha256"]), 64)
            self.assertEqual(len(receipt["ownership_manifest_sha256"]), 64)
            self.assertEqual(receipt["dev_flow"]["name"], "dev-flow-orchestrator")
            self.assertGreater(len(receipt["dev_flow"]["files"]), 10)
            self.assertGreater(len(receipt["dependencies"]), 0)
            ownership = runtime_integrity.validate_ownership_manifest(
                runtime_integrity.read_json(Path(created["ownership_manifest_path"])),
                self.release_id,
            )
            ownership_paths = {
                str(entry["path"])
                for entry in ownership["entries"]
                if entry.get("type") == "file"
            }
            self.assertTrue(
                {
                    "plugin/" + relative
                    for relative in skill_files
                }.issubset(ownership_paths)
            )
            self.assertEqual(sentinel.read_bytes(), b"unchanged\n")
            self.assertNotIn(str(data_root), json.dumps(created["receipt"]))
            package_file = next(
                item for item in receipt["dev_flow"]["files"]
                if str(item["path"]).endswith("/dev_flow_orchestrator/delivery.py")
            )
            tampered = Path(created["runtime_dir"]) / str(package_file["path"])
            tampered.write_bytes(tampered.read_bytes() + b"\n# tampered-runtime\n")
            with mock.patch.dict(os.environ, environment, clear=True):
                rebuilt = manage_runtime.build(
                    self.sealed, runtime_root, self.source_commit, self.source_tree,
                    self.release_id, data_root,
                )
            self.assertFalse(rebuilt["reused"])
            self.assertEqual(len(rebuilt["retained_paths"]), 1)
            rebuilt_file = Path(rebuilt["runtime_dir"]) / str(package_file["path"])
            self.assertNotIn(b"tampered-runtime", rebuilt_file.read_bytes())
            status_after = subprocess.run(
                ["git", "status", "--porcelain", "--ignored"],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(status_after, status_before)

    def test_external_sealed_builder_makes_legacy_source_without_helper_runnable(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required for managed-runtime integration")
        self.assertFalse(
            (self.legacy_sealed / "scripts" / "runtime_integrity.py").exists()
        )
        with tempfile.TemporaryDirectory(prefix="dev-flow-legacy-runtime-") as temporary:
            base = Path(temporary)
            environment = hermetic_subprocess_env(base)
            with mock.patch.dict(os.environ, environment, clear=True):
                built = manage_runtime.build(
                    self.legacy_sealed,
                    base / "runtime",
                    self.legacy_commit,
                    self.legacy_tree,
                    self.legacy_release_id,
                    None,
                )
            self.assertTrue(Path(built["verifier_path"]).is_file())
            self.assertTrue(Path(built["launcher_path"]).is_file())
            self.assertFalse(
                (Path(built["plugin_root"]) / "scripts" / "runtime_integrity.py").exists()
            )

    def test_runtime_verifier_rejects_bound_identity_mismatches_before_import(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is required for managed-runtime integration")
        with tempfile.TemporaryDirectory(prefix="dev-flow-verifier-matrix-") as temporary:
            base = Path(temporary)
            environment = hermetic_subprocess_env(base)
            runtime_root = base / "runtime"
            data_root = base / "data"
            data_root.mkdir()
            with mock.patch.dict(os.environ, environment, clear=True):
                built = manage_runtime.build(
                    self.sealed, runtime_root, self.source_commit, self.source_tree,
                    self.release_id, data_root,
                )
            runtime_dir = Path(built["runtime_dir"])
            runtime_python = runtime_dir / "venv" / (
                "Scripts/python.exe" if os.name == "nt" else "bin/python"
            )
            verifier = Path(built["verifier_path"])
            launcher = Path(built["launcher_path"])
            receipt_path = Path(built["receipt_path"])
            ownership_path = Path(built["ownership_manifest_path"])
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)

            def verify() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        str(runtime_python), "-B", "-I", str(verifier),
                        "verify-runtime", "--runtime-dir", str(runtime_dir),
                        "--launcher", str(launcher), "--release-id", self.release_id,
                    ],
                    cwd=base,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            def launch() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(launcher), "--stdio"],
                    cwd=base,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )

            def assert_launcher_repair(label: str) -> None:
                if os.name == "nt":
                    return
                completed = launch()
                self.assertNotEqual(completed.returncode, 0, label)
                self.assertEqual(completed.stdout, "", label)
                self.assertIn("repair", completed.stderr.casefold(), label)

            self.assertEqual(verify().returncode, 0)

            backup = receipt_path.with_name("receipt.backup")
            receipt_path.rename(backup)
            try:
                self.assertNotEqual(verify().returncode, 0, "missing receipt")
                assert_launcher_repair("missing receipt launcher")
            finally:
                backup.rename(receipt_path)

            receipt_path.write_bytes(b"{malformed")
            try:
                self.assertNotEqual(verify().returncode, 0, "malformed receipt")
                assert_launcher_repair("malformed receipt launcher")
            finally:
                receipt_path.write_bytes(receipt_bytes)

            def receipt_mismatch(label: str, mutate: object) -> None:
                changed = json.loads(receipt_bytes)
                mutate(changed)
                receipt_path.write_text(
                    json.dumps(changed, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                try:
                    self.assertNotEqual(verify().returncode, 0, label)
                finally:
                    receipt_path.write_bytes(receipt_bytes)

            receipt_mismatch(
                "schema mismatch",
                lambda value: value.__setitem__("schema", "incompatible-runtime-receipt"),
            )
            changed_schema = json.loads(receipt_bytes)
            changed_schema["schema"] = "incompatible-runtime-receipt"
            receipt_path.write_text(
                json.dumps(changed_schema, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            try:
                assert_launcher_repair("schema mismatch launcher")
            finally:
                receipt_path.write_bytes(receipt_bytes)

            def wrong_path(value: dict[str, object]) -> None:
                wrong = str(base / "different-release")
                value["runtime_path"] = wrong
                value["plugin_path"] = wrong + "/plugin"
                value["python"]["path"] = wrong + (
                    "/venv/Scripts/python.exe" if os.name == "nt" else "/venv/bin/python"
                )

            receipt_mismatch("runtime path mismatch", wrong_path)
            receipt_mismatch(
                "Python identity mismatch",
                lambda value: value["python"].__setitem__("executable_sha256", "0" * 64),
            )
            receipt_mismatch(
                "dependency inventory mismatch",
                lambda value: value["dependencies"][0].__setitem__(
                    "version", str(value["dependencies"][0]["version"]) + ".changed"
                ),
            )

            site_packages_candidates = list(
                (runtime_dir / "venv").glob("lib/python*/site-packages")
            ) + list((runtime_dir / "venv").glob("Lib/site-packages"))
            self.assertEqual(len(site_packages_candidates), 1)
            site_packages = site_packages_candidates[0]
            dependency_name = str(receipt["dependencies"][0]["name"])

            def normalized(value: str) -> str:
                result = value.casefold().replace("_", "-").replace(".", "-")
                while "--" in result:
                    result = result.replace("--", "-")
                return result

            dependency_dist_info = None
            for metadata in site_packages.glob("*.dist-info/METADATA"):
                name_line = next(
                    (
                        line[6:].strip()
                        for line in metadata.read_text(
                            encoding="utf-8", errors="strict"
                        ).splitlines()
                        if line.startswith("Name: ")
                    ),
                    "",
                )
                if normalized(name_line) == dependency_name:
                    dependency_dist_info = metadata.parent
                    break
            self.assertIsNotNone(dependency_dist_info)
            assert dependency_dist_info is not None
            missing_backup = base / "missing-dependency-dist-info"
            dependency_dist_info.rename(missing_backup)
            try:
                self.assertNotEqual(verify().returncode, 0, "missing dependency")
            finally:
                missing_backup.rename(dependency_dist_info)

            dependency_metadata = dependency_dist_info / "METADATA"
            dependency_metadata_bytes = dependency_metadata.read_bytes()
            dependency_metadata.write_bytes(
                dependency_metadata_bytes.replace(b"Version: ", b"Version: 99.", 1)
            )
            try:
                self.assertNotEqual(verify().returncode, 0, "dependency version drift")
            finally:
                dependency_metadata.write_bytes(dependency_metadata_bytes)

            extra_dist = site_packages / "dfo_audit_extra_dependency-9.9.9.dist-info"
            extra_dist.mkdir()
            (extra_dist / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: dfo-audit-extra-dependency\nVersion: 9.9.9\n",
                encoding="utf-8",
            )
            (extra_dist / "RECORD").write_text("", encoding="utf-8")
            try:
                self.assertNotEqual(verify().returncode, 0, "extra dependency")
            finally:
                (extra_dist / "METADATA").unlink()
                (extra_dist / "RECORD").unlink()
                extra_dist.rmdir()

            def installed_path(suffix: str) -> Path:
                return runtime_dir / next(
                    str(item["path"]) for item in receipt["dev_flow"]["files"]
                    if str(item["path"]).endswith(suffix)
                )

            for label, suffix in (
                ("Dev Flow METADATA mismatch", ".dist-info/METADATA"),
                ("Dev Flow RECORD mismatch", ".dist-info/RECORD"),
            ):
                path = installed_path(suffix)
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged\n")
                try:
                    self.assertNotEqual(verify().returncode, 0, label)
                finally:
                    path.write_bytes(original)

            ownership_bytes = ownership_path.read_bytes()
            ownership_path.write_bytes(ownership_bytes + b" ")
            try:
                self.assertNotEqual(verify().returncode, 0, "ownership mismatch")
            finally:
                ownership_path.write_bytes(ownership_bytes)

            launcher_bytes = launcher.read_bytes()
            launcher.write_bytes(launcher_bytes + b"\n# changed\n")
            try:
                self.assertNotEqual(verify().returncode, 0, "launcher mismatch")
            finally:
                launcher.write_bytes(launcher_bytes)

            package_root = installed_path("/dev_flow_orchestrator/__init__.py").parent
            extra = package_root / "unrecorded_runtime_file.py"
            extra.write_text("EXTRA = True\n", encoding="utf-8")
            try:
                self.assertNotEqual(verify().returncode, 0, "extra package file")
            finally:
                extra.unlink()

            init_path = package_root / "__init__.py"
            init_bytes = init_path.read_bytes()
            sentinel = base / "candidate-imported"
            init_path.write_bytes(
                b"import os\nfrom pathlib import Path\n"
                b"Path(os.environ['DEV_FLOW_IMPORT_SENTINEL']).write_text('imported')\n"
                + init_bytes
            )
            environment["DEV_FLOW_IMPORT_SENTINEL"] = str(sentinel)
            try:
                self.assertNotEqual(verify().returncode, 0, "package byte mismatch")
                self.assertFalse(sentinel.exists(), "candidate imported before verification")
                if os.name != "nt":
                    launched = launch()
                    self.assertNotEqual(launched.returncode, 0)
                    self.assertEqual(launched.stdout, "")
                    self.assertIn("repair", launched.stderr.casefold())
                    self.assertFalse(sentinel.exists(), "launcher imported candidate before verification")
            finally:
                init_path.write_bytes(init_bytes)

            launcher_repair_marker = b"\n# launcher-tamper-repair\n"
            launcher.write_bytes(launcher.read_bytes() + launcher_repair_marker)
            with mock.patch.dict(os.environ, environment, clear=True):
                repaired = manage_runtime.build(
                    self.sealed,
                    runtime_root,
                    self.source_commit,
                    self.source_tree,
                    self.release_id,
                    data_root,
                )
            self.assertFalse(repaired["reused"])
            self.assertEqual(len(repaired["retained_paths"]), 1)
            self.assertNotIn(
                launcher_repair_marker, Path(repaired["launcher_path"]).read_bytes()
            )

    def test_existing_unmarked_runtime_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-unowned-runtime-") as temporary:
            runtime_root = Path(temporary) / "existing"
            runtime_root.mkdir()
            sentinel = runtime_root / "user-owned"
            sentinel.write_bytes(b"preserve\n")
            environment = hermetic_subprocess_env(Path(temporary))
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(manage_runtime.RuntimeBuildError) as context:
                    manage_runtime.build(
                        self.sealed, runtime_root, self.source_commit, self.source_tree,
                        self.release_id, None,
                    )
            self.assertIn("ownership marker", str(context.exception))
            self.assertEqual(sentinel.read_bytes(), b"preserve\n")
            self.assertFalse((runtime_root / manage_runtime.ROOT_MARKER).exists())

    @unittest.skipIf(os.name == "nt", "ordinary Windows users may lack symlink privilege")
    def test_runtime_root_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-runtime-link-") as temporary:
            base = Path(temporary)
            target = base / "target"
            target.mkdir()
            selected = base / "selected"
            selected.symlink_to(target, target_is_directory=True)
            environment = hermetic_subprocess_env(base)
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(manage_runtime.RuntimeBuildError) as context:
                    manage_runtime.build(
                        self.sealed, selected, self.source_commit, self.source_tree,
                        self.release_id, None,
                    )
            self.assertIn("symbolic link", str(context.exception))
            self.assertEqual(tuple(target.iterdir()), ())

    @unittest.skipIf(os.name == "nt", "ordinary Windows users may lack symlink privilege")
    def test_plugin_root_symlink_is_rejected_before_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-plugin-link-") as temporary:
            selected = Path(temporary) / "selected"
            selected.symlink_to(self.sealed, target_is_directory=True)
            with self.assertRaisesRegex(runtime_integrity.IntegrityError, "regular directory"):
                runtime_integrity.verify_plugin_release(selected)

    @unittest.skipIf(os.name == "nt", "ordinary Windows users may lack symlink privilege")
    def test_sealed_git_tree_preserves_executable_and_symbolic_link_semantics(self) -> None:
        executable = self.sealed / "sealed-executable.sh"
        link = self.sealed / "sealed-link"
        self.assertTrue(executable.is_file())
        self.assertTrue(executable.stat().st_mode & 0o111)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "sealed-executable.sh")
        self.assertEqual(link.read_bytes(), executable.read_bytes())

    def test_sealer_rejects_escape_hardlink_special_and_symlink_ancestor(self) -> None:
        cases: dict[str, list[tarfile.TarInfo]] = {}
        absolute = tarfile.TarInfo("/absolute")
        absolute.size = 1
        traversal = tarfile.TarInfo("../escape")
        traversal.size = 1
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "other"
        special = tarfile.TarInfo("special")
        special.type = tarfile.FIFOTYPE
        link = tarfile.TarInfo("parent")
        link.type = tarfile.SYMTYPE
        link.linkname = "safe"
        child = tarfile.TarInfo("parent/child")
        child.size = 1
        cases["absolute"] = [absolute]
        cases["traversal"] = [traversal]
        cases["hardlink"] = [hardlink]
        cases["special"] = [special]
        cases["symlink-ancestor"] = [link, child]
        with tempfile.TemporaryDirectory(prefix="dev-flow-seal-reject-") as temporary:
            base = Path(temporary)
            for label, members in cases.items():
                with self.subTest(label=label):
                    archive_path = base / (label + ".tar")
                    with tarfile.open(
                        archive_path,
                        mode="w",
                        format=tarfile.PAX_FORMAT,
                        pax_headers={"comment": "a" * 40},
                    ) as archive:
                        for member in members:
                            content = io.BytesIO(b"x") if member.isfile() else None
                            archive.addfile(member, content)
                    destination = base / (label + "-sealed")
                    with self.assertRaises(runtime_integrity.IntegrityError):
                        runtime_integrity.seal_archive(
                            archive_path, destination, "a" * 40, "b" * 40
                        )
                    self.assertFalse(destination.exists())
            self.assertFalse((base / "escape").exists())

    def _write_synthetic_release(
        self,
        runtime_root: Path,
        *,
        linked_parent: Path | None = None,
    ) -> tuple[Path, Path | None]:
        runtime_root.mkdir()
        (runtime_root / manage_runtime.ROOT_MARKER).write_text(
            "dev-flow-managed-runtime/1\n", encoding="utf-8"
        )
        releases = runtime_root / "releases"
        releases.mkdir()
        release_id = "r-synthetic"
        release = releases / release_id
        release.mkdir()
        canonical_release = release.resolve()
        root_mode = release.stat().st_mode & 0o7777
        entries: list[dict[str, object]] = [{
            "path": ".", "type": "directory", "mode": root_mode,
            "release_id": release_id,
        }]
        sentinel: Path | None = None
        if linked_parent is None:
            payload = release / "payload.txt"
            payload.write_bytes(b"owned\n")
            entries.append({
                "path": "payload.txt", "type": "file",
                "mode": payload.stat().st_mode & 0o7777,
                "release_id": release_id,
                "sha256": runtime_integrity.sha256_file(payload),
            })
        else:
            linked_parent.mkdir()
            sentinel = linked_parent / "owned.txt"
            sentinel.write_bytes(b"external-sentinel\n")
            (release / "parent").symlink_to(linked_parent, target_is_directory=True)
            entries.extend([
                {
                    "path": "parent", "type": "directory", "mode": 0o755,
                    "release_id": release_id,
                },
                {
                    "path": "parent/owned.txt", "type": "file", "mode": 0o644,
                    "release_id": release_id,
                    "sha256": runtime_integrity.sha256_file(sentinel),
                },
            ])
        entries.sort(key=lambda item: str(item["path"]))
        manifest = {
            "schema": runtime_integrity.OWNERSHIP_MANIFEST_SCHEMA,
            "release_id": release_id,
            "entries": entries,
        }
        manifest_path = release / runtime_integrity.OWNERSHIP_MANIFEST_NAME
        manifest_path.write_bytes(runtime_integrity.pretty_json_bytes(manifest))
        dummy = "a" * 64
        receipt = runtime_integrity.validate_runtime_receipt({
            "schema": runtime_integrity.RUNTIME_RECEIPT_SCHEMA,
            "release_id": release_id,
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "wheel_sha256": dummy,
            "plugin_path": str(canonical_release / "plugin"),
            "plugin_release_manifest_sha256": dummy,
            "dev_flow": {
                "name": "dev-flow-orchestrator", "version": "0.5.0",
                "metadata_sha256": dummy, "record_sha256": dummy, "files": [],
            },
            "dependencies": [],
            "python": {
                "path": str(canonical_release / "venv" / "bin" / "python"),
                "executable_sha256": dummy, "version": "3.14.0",
                "architecture": "test", "bits": 64,
            },
            "runtime_path": str(canonical_release),
            "launcher_sha256": dummy,
            "cli_launcher_sha256": None,
            "ownership_manifest_sha256": runtime_integrity.sha256_file(manifest_path),
            "dependency_lock_sha256": dummy,
            "created_at": "2026-08-09T00:00:00Z",
        })
        (release / runtime_integrity.RUNTIME_RECEIPT_NAME).write_bytes(
            runtime_integrity.pretty_json_bytes(receipt)
        )
        return release, sentinel

    def test_exact_owned_removal_is_individual_and_complete(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-remove-owned-") as temporary:
            runtime_root = Path(temporary) / "runtime"
            self._write_synthetic_release(runtime_root)
            result = runtime_integrity.remove_owned(runtime_root)
            self.assertEqual(result["action"], "removed", result)
            self.assertTrue(result["ok"])
            self.assertFalse(runtime_root.exists())

    def test_exact_owned_removal_preserves_unknown_runtime_root_content_and_marker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-remove-root-unknown-") as temporary:
            runtime_root = Path(temporary) / "runtime"
            self._write_synthetic_release(runtime_root)
            unknown = runtime_root / "user-owned"
            unknown.write_bytes(b"preserve\n")
            result = runtime_integrity.remove_owned(runtime_root)
            self.assertEqual(result["action"], "partial", result)
            self.assertEqual(unknown.read_bytes(), b"preserve\n")
            self.assertTrue((runtime_root / manage_runtime.ROOT_MARKER).is_file())

    def test_runtime_marker_replaced_during_removal_is_retained(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-remove-marker-race-") as temporary:
            runtime_root = Path(temporary) / "runtime"
            self._write_synthetic_release(runtime_root)
            marker = runtime_root / manage_runtime.ROOT_MARKER
            replacement = b"concurrent user marker replacement\x00\xff"
            original_remove_control = runtime_integrity._remove_control_file

            def replace_marker_after_manifest(
                path: Path,
                expected_digest: str | None,
                validator: object,
                retained: list[dict[str, str]],
                sequence: int,
            ) -> bool:
                removed = original_remove_control(
                    path, expected_digest, validator, retained, sequence
                )
                if (
                    removed
                    and path.name == runtime_integrity.OWNERSHIP_MANIFEST_NAME
                ):
                    marker.unlink()
                    marker.write_bytes(replacement)
                return removed

            with mock.patch.object(
                runtime_integrity,
                "_remove_control_file",
                side_effect=replace_marker_after_manifest,
            ):
                result = runtime_integrity.remove_owned(runtime_root)

            self.assertIn(result["action"], {"partial", "retained"})
            self.assertEqual(marker.read_bytes(), replacement)
            self.assertTrue(runtime_root.is_dir())
            self.assertTrue(
                any(
                    Path(item["path"]).resolve() == marker.resolve()
                    for item in result["retained"]
                ),
                result,
            )

    @unittest.skipIf(os.name == "nt", "ordinary Windows users may lack symlink privilege")
    def test_owned_removal_rejects_symlink_ancestor_and_preserves_external_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dev-flow-remove-link-") as temporary:
            base = Path(temporary)
            runtime_root = base / "runtime"
            _, sentinel = self._write_synthetic_release(
                runtime_root, linked_parent=base / "external"
            )
            result = runtime_integrity.remove_owned(runtime_root)
            self.assertIn(result["action"], {"partial", "retained"})
            self.assertIsNotNone(sentinel)
            self.assertEqual(sentinel.read_bytes(), b"external-sentinel\n")
            self.assertTrue(
                any("parent" in item["path"] for item in result["retained"]), result
            )

    def test_built_wheel_contains_and_resolves_the_exact_official_workflows(self) -> None:
        expected = {
            workflow_id: load_definition(workflow_id).identity
            for workflow_id in WORKFLOW_IDS
        }
        with tempfile.TemporaryDirectory(prefix="dev-flow-wheel-assets-") as temporary:
            root = Path(temporary)
            environment = hermetic_subprocess_env(root)
            roots = probe_subprocess_runtime_roots(root, environment)
            self.assertTrue(roots["data"].is_relative_to(root.resolve()))
            self.assertTrue(roots["runtime"].is_relative_to(root.resolve()))
            wheel_dir = root / "dist"
            completed = subprocess.run(
                ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            wheels = list(wheel_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            extracted = root / "extracted"
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                for workflow_id in WORKFLOW_IDS:
                    self.assertIn(
                        "dev_flow_orchestrator/workflow_assets/{}.yaml".format(
                            workflow_id
                        ),
                        names,
                    )
                archive.extractall(extracted)

            code = """
import json,sys
sys.path.insert(0, sys.argv[1])
from dev_flow_orchestrator.product import WORKFLOW_IDS
from dev_flow_orchestrator.workflows import BUILTIN_DIR, load_definition
print(json.dumps({
    'builtin_dir': BUILTIN_DIR.name,
    'identities': {item: load_definition(item).identity for item in WORKFLOW_IDS},
}, sort_keys=True))
"""
            probed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", code, str(extracted)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(probed.returncode, 0, probed.stderr)
            result = json.loads(probed.stdout)
            self.assertEqual(result["builtin_dir"], "workflow_assets")
            self.assertEqual(result["identities"], expected)


if __name__ == "__main__":
    unittest.main()
