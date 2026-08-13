"""Focused deterministic release-builder and promotion-contract tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_release  # noqa: E402
import promote_release  # noqa: E402
import release_artifact  # noqa: E402


VERSION = "1.2.3"
COMMIT = "1" * 40
TREE = "2" * 40


def _write(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(mode)


def _wheel(path: Path, version: str = VERSION) -> None:
    dist_info = "dev_flow_orchestrator-{}.dist-info".format(version)
    members = {
        "dev_flow_orchestrator/__init__.py": b"VALUE = 1\n",
        dist_info + "/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        dist_info + "/METADATA": (
            "Metadata-Version: 2.1\nName: dev-flow-orchestrator\nVersion: {}\n".format(version)
        ).encode(),
    }
    record_name = dist_info + "/RECORD"
    records = []
    for name, raw in members.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
        records.append("{},sha256={},{}".format(name, digest, len(raw)))
    records.append("{},,".format(record_name))
    members[record_name] = ("\n".join(records) + "\n").encode()
    with zipfile.ZipFile(path, mode="w", compression=zipfile.ZIP_DEFLATED) as wheel:
        for name, raw in members.items():
            wheel.writestr(name, raw)


def _source_fixture(root: Path, version: str = VERSION) -> tuple[Path, Path]:
    _write(
        root / ".codex-plugin" / "plugin.json",
        json.dumps({"name": "dev-flow-orchestrator", "version": version}).encode(),
    )
    _write(root / ".mcp.json", b'{"mcpServers":{"dev-flow":{}}}\n')
    _write(root / "skills" / "dev-flow" / "SKILL.md", b"---\nname: dev-flow\n---\n")
    _write(root / "skills" / "dev-flow" / "agents" / "openai.yaml", b"interface: {}\n")
    for name in build_release.CANONICAL_PLUGIN_FILES:
        path = root / name
        if path.exists():
            continue
        _write(path, ("# {}\n".format(name)).encode(), 0o755 if path.suffix not in {".cmd"} else 0o644)
    for name in build_release.LIFECYCLE_FILES:
        source = ROOT / "scripts" / name
        if name == "release_artifact.py":
            _write(root / "scripts" / name, source.read_bytes(), 0o755)
        elif not (root / "scripts" / name).exists():
            _write(root / "scripts" / name, b"#!/usr/bin/env python3\n", 0o755)
    _write(root / "uv.lock", b"version = 1\n")
    wheel = root / "input" / "dev_flow_orchestrator-{}-py3-none-any.whl".format(version)
    wheel.parent.mkdir()
    _wheel(wheel, version)
    requirements = root / "input" / "requirements.txt"
    _write(
        requirements,
        (
            "dependency==1.0 ; python_version >= '3.10' \\\n"
            "    --hash=sha256:{}\n".format("a" * 64)
        ).encode(),
    )
    return wheel, requirements


def _assemble(root: Path, output: Path) -> dict[str, object]:
    wheel, requirements = _source_fixture(root)
    return build_release.assemble_release(
        root,
        output,
        version=VERSION,
        source_commit=COMMIT,
        source_tree=TREE,
        wheel_path=wheel,
        requirements_path=requirements,
    )


class ReleaseBuilderTests(unittest.TestCase):
    def test_deterministic_double_build_and_exact_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            source = work / "source"
            source.mkdir()
            wheel, requirements = _source_fixture(source)
            first = build_release.assemble_release(
                source,
                work / "first",
                version=VERSION,
                source_commit=COMMIT,
                source_tree=TREE,
                wheel_path=wheel,
                requirements_path=requirements,
            )
            second = build_release.assemble_release(
                source,
                work / "second",
                version=VERSION,
                source_commit=COMMIT,
                source_tree=TREE,
                wheel_path=wheel,
                requirements_path=requirements,
            )
            self.assertEqual(first["manifest"], second["manifest"])
            self.assertEqual(first["component_digests"], second["component_digests"])
            for name in first["assets"]:
                self.assertEqual((work / "first" / name).read_bytes(), (work / "second" / name).read_bytes())
            archive = work / "first" / "dev-flow-orchestrator-1.2.3.tar.gz"
            with tarfile.open(archive, "r:gz") as release:
                names = {member.name.rstrip("/") for member in release.getmembers()}
            prefix = "dev-flow-orchestrator-1.2.3/"
            self.assertIn(prefix + "release-manifest.json", names)
            self.assertIn(prefix + "plugin/.codex-plugin/plugin.json", names)
            self.assertIn(prefix + "plugin/.mcp.json", names)
            self.assertIn(prefix + "plugin/skills/dev-flow/SKILL.md", names)
            self.assertIn(prefix + "plugin/release-manifest.json", names)
            self.assertIn(prefix + "wheels/dev_flow_orchestrator-1.2.3-py3-none-any.whl", names)
            for helper in build_release.LIFECYCLE_FILES:
                self.assertIn(prefix + "lifecycle/" + helper, names)

    @unittest.skipIf(os.name == "nt", "POSIX umask semantics are required")
    def test_restrictive_umask_does_not_change_assets_or_release_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            source = work / "source"
            source.mkdir()
            wheel, requirements = _source_fixture(source)

            previous_umask = os.umask(0o022)
            try:
                baseline = build_release.assemble_release(
                    source,
                    work / "baseline",
                    version=VERSION,
                    source_commit=COMMIT,
                    source_tree=TREE,
                    wheel_path=wheel,
                    requirements_path=requirements,
                )
            finally:
                os.umask(previous_umask)

            previous_umask = os.umask(0o077)
            try:
                restrictive = build_release.assemble_release(
                    source,
                    work / "restrictive",
                    version=VERSION,
                    source_commit=COMMIT,
                    source_tree=TREE,
                    wheel_path=wheel,
                    requirements_path=requirements,
                )
            finally:
                os.umask(previous_umask)

            self.assertEqual(baseline["release_id"], restrictive["release_id"])
            self.assertEqual(
                baseline["plugin_release_id"], restrictive["plugin_release_id"]
            )
            self.assertEqual(baseline["manifest"], restrictive["manifest"])
            self.assertEqual(
                baseline["component_digests"], restrictive["component_digests"]
            )
            for name in baseline["assets"]:
                self.assertEqual(
                    (work / "baseline" / name).read_bytes(),
                    (work / "restrictive" / name).read_bytes(),
                    name,
                )

    def test_bootstraps_embed_one_byte_identical_verifier_and_identity(self) -> None:
        verifier = b"print('phase a')\n\x00"
        index_digest = "a" * 64
        assets = build_release.render_bootstrap_assets(
            verifier,
            index_sha256=index_digest,
            version=VERSION,
        )
        shell = assets["install.sh"].decode()
        powershell = assets["install.ps1"].decode()
        shell_encoded = re.search(
            r"DEV_FLOW_PHASE_A_B64='([A-Za-z0-9+/=]+)'", shell
        )
        powershell_encoded = re.search(
            r"\$PhaseABase64 = '([A-Za-z0-9+/=]+)'", powershell
        )
        self.assertIsNotNone(shell_encoded)
        self.assertIsNotNone(powershell_encoded)
        self.assertEqual(shell_encoded.group(1), powershell_encoded.group(1))
        self.assertEqual(base64.b64decode(shell_encoded.group(1)), verifier)
        for document in (shell, powershell):
            self.assertIn(release_artifact.CANONICAL_REPOSITORY, document)
            self.assertIn(VERSION, document)
            self.assertIn(index_digest, document)
            self.assertIn("DEV_FLOW_SOURCE_ROOT", document)

    def test_version_disagreement_and_non_pure_wheel_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            source = work / "source"
            source.mkdir()
            wheel, requirements = _source_fixture(source, version="1.2.4")
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "plugin version"):
                build_release.assemble_release(
                    source,
                    work / "output",
                    version=VERSION,
                    source_commit=COMMIT,
                    source_tree=TREE,
                    wheel_path=wheel,
                    requirements_path=requirements,
                )

    def test_requirements_must_be_exact_and_hash_locked(self) -> None:
        invalid = (
            "dependency>=1 \\\n    --hash=sha256:{}\n".format("a" * 64),
            "dependency==1\n",
            "git+https://example.invalid/x\n",
            "dependency @ https://example.invalid/dependency.whl \\\n    --hash=sha256:{}\n".format("a" * 64),
            "-e dependency==1 \\\n    --hash=sha256:{}\n".format("a" * 64),
            "--index-url https://example.invalid/simple\n",
            "dependency==1 --hash=sha256:{}\n".format("a" * 64),
            "dependency==1 \\\n    --hash=sha512:{}\n".format("a" * 64),
            "dependency==1 ; python_version >= '3.10' --no-binary package \\\n    --hash=sha256:{}\n".format("a" * 64),
        )
        for document in invalid:
            with self.subTest(document=document):
                with self.assertRaises(release_artifact.ReleaseArtifactError):
                    release_artifact.validate_requirements_text(document)

        release_artifact.validate_requirements_text(
            "dependency==1.2.3 ; python_version >= '3.10' \\\n"
            "    --hash=sha256:{} \\\n"
            "    --hash=sha256:{}\n".format("a" * 64, "b" * 64)
        )

    def test_known_secret_and_local_path_scan_reports_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            secret = work / "secret.txt"
            secret.write_bytes(
                b"-----BEGIN PRIVATE KEY-----\n"
                b"token = '0123456789abcdef'\n"
                b"path=/Users/alice/project/file\n"
            )
            findings = build_release.scan_known_secrets_and_local_paths(
                [("plugin/secret.txt", secret)]
            )
            self.assertEqual({item["kind"] for item in findings}, {"known-secret", "local-path"})

            ordinary = work / "ordinary.py"
            ordinary.write_bytes(b"def read(token: object) -> None:\n    pass\n")
            self.assertEqual(
                build_release.scan_known_secrets_and_local_paths(
                    [("lifecycle/ordinary.py", ordinary)]
                ),
                [],
            )

    def test_wheel_rejects_unexpected_or_unsafe_members(self) -> None:
        unsafe = (
            ("other_project/file.py", None, "unexpected top-level"),
            ("../dev_flow_orchestrator/payload.py", None, "member path"),
            ("dev_flow_orchestrator\\payload.py", None, "member path"),
            ("DEV_FLOW_ORCHESTRATOR/__init__.py", None, "case collision"),
            ("dev_flow_orchestrator/startup.pth", None, "non-pure|startup-control"),
            (
                "dev_flow_orchestrator/link.py",
                stat.S_IFLNK | 0o777,
                "link or special",
            ),
            (
                "dev_flow_orchestrator/fifo",
                stat.S_IFIFO | 0o644,
                "link or special",
            ),
        )
        for name, unix_mode, message in unsafe:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                wheel = work / "dev_flow_orchestrator-1.2.3-py3-none-any.whl"
                _wheel(wheel)
                with zipfile.ZipFile(wheel, "a") as archive:
                    if unix_mode is None:
                        archive.writestr(name, "")
                    else:
                        info = zipfile.ZipInfo(name)
                        info.create_system = 3
                        info.external_attr = unix_mode << 16
                        archive.writestr(info, "")
                with self.assertRaisesRegex(build_release.ReleaseBuildError, message):
                    build_release.validate_project_wheel(wheel, version=VERSION)

    def test_wheel_rejects_duplicate_and_incomplete_record_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            wheel = work / "dev_flow_orchestrator-1.2.3-py3-none-any.whl"
            _wheel(wheel)
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("dev_flow_orchestrator/extra.py", "")
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "complete member set"):
                build_release.validate_project_wheel(wheel, version=VERSION)

            duplicate = work / "duplicate" / wheel.name
            duplicate.parent.mkdir()
            _wheel(duplicate)
            with self.assertWarns(UserWarning), zipfile.ZipFile(duplicate, "a") as archive:
                archive.writestr("dev_flow_orchestrator/__init__.py", "replacement")
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "duplicate"):
                build_release.validate_project_wheel(duplicate, version=VERSION)

            valid_for_corrupt = work / "valid" / wheel.name
            valid_for_corrupt.parent.mkdir()
            _wheel(valid_for_corrupt)
            corrupt = work / "corrupt" / wheel.name
            corrupt.parent.mkdir()
            with zipfile.ZipFile(valid_for_corrupt) as source, zipfile.ZipFile(
                corrupt, "w", compression=zipfile.ZIP_DEFLATED
            ) as destination:
                for info in source.infolist():
                    raw = source.read(info)
                    if info.filename == "dev_flow_orchestrator/__init__.py":
                        raw = b"VALUE = 2\n"
                    destination.writestr(info, raw)
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "digest differs"):
                build_release.validate_project_wheel(corrupt, version=VERSION)

    def test_wheel_rejects_file_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheel = Path(temporary) / "dev_flow_orchestrator-1.2.3-py3-none-any.whl"
            _wheel(wheel)
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("dev_flow_orchestrator/node", "file")
                archive.writestr("dev_flow_orchestrator/node/child.py", "child")
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "member ancestor"):
                build_release.validate_project_wheel(wheel, version=VERSION)

    def test_clean_tag_validation_rejects_dirty_or_wrong_provenance(self) -> None:
        class FakeRunner:
            def __init__(self, *, dirty: bool = False, tagged: str = COMMIT) -> None:
                self.dirty = dirty
                self.tagged = tagged

            def __call__(self, command, **_kwargs):
                joined = " ".join(command)
                if "status" in command:
                    stdout = "?? local.txt\n" if self.dirty else ""
                elif "v1.2.3^{commit}" in command:
                    stdout = self.tagged + "\n"
                elif "--points-at" in command:
                    stdout = "v1.2.3\n"
                elif command[-1] == "HEAD^{tree}":
                    stdout = TREE + "\n"
                elif command[-1] == "HEAD":
                    stdout = COMMIT + "\n"
                else:
                    raise AssertionError(joined)
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "clean"):
                build_release.validate_clean_tag(root, VERSION, runner=FakeRunner(dirty=True))
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "exact"):
                build_release.validate_clean_tag(root, VERSION, runner=FakeRunner(tagged="3" * 40))
            self.assertEqual(
                build_release.validate_clean_tag(root, VERSION, runner=FakeRunner()),
                (COMMIT, TREE),
            )


class BuilderConfigurationTests(unittest.TestCase):
    def test_repository_builder_configuration_is_closed(self) -> None:
        config = build_release.load_builder_config(ROOT / "release-builder.json")
        self.assertEqual(config["schema"], build_release.BUILDER_SCHEMA)
        self.assertRegex(config["build_backend"], r"^hatchling==[0-9.]+$")
        self.assertEqual(config["tar_format"], "python-stdlib-ustar")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "release-builder.json"
            invalid = dict(config)
            invalid["build_backend"] = "hatchling>=1.27.0"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "exact supported pin"):
                build_release.load_builder_config(path)

    def test_builder_environment_binds_pyproject_build_backend(self) -> None:
        class FakeRunner:
            def __call__(self, command, **_kwargs):
                self.assert_command = command
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="uv 9.9.9 (packager metadata may follow)\n",
                    stderr="",
                )

        config = {
            "python": "{}.{}.{}".format(*sys.version_info[:3]),
            "uv": "9.9.9",
            "build_backend": "hatchling==1.27.0",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write(
                root / "pyproject.toml",
                b'[build-system]\nrequires = ["hatchling==1.27.0"]\nbuild-backend = "hatchling.build"\n',
            )
            build_release.validate_builder_environment(config, root=root, runner=FakeRunner())
            _write(
                root / "pyproject.toml",
                b'[build-system]\nrequires = ["hatchling>=1.27.0"]\nbuild-backend = "hatchling.build"\n',
            )
            with self.assertRaisesRegex(build_release.ReleaseBuildError, "differs"):
                build_release.validate_builder_environment(config, root=root, runner=FakeRunner())


class PromotionTests(unittest.TestCase):
    class FakeAPI:
        def __init__(
            self,
            assets: Path,
            *,
            existing: str | None = None,
            corrupt: str | None = None,
            wrong_source: bool = False,
            interrupt_upload_once: bool = False,
        ) -> None:
            self.assets = assets
            self.existing = existing
            self.corrupt = corrupt
            self.wrong_source = wrong_source
            self.interrupt_upload_once = interrupt_upload_once
            self.release_id = 42
            self.asset_ids: dict[str, int] = {}
            self.events: list[str] = []
            self._next_asset_id = 100

        def tag_identity(self, tag: str) -> tuple[str, str]:
            self.events.append("tag_identity:" + tag)
            return (("9" * 40, TREE) if self.wrong_source else (COMMIT, TREE))

        def release_by_tag(self, tag: str) -> dict[str, object] | None:
            self.events.append("release_by_tag:" + tag)
            if self.existing is None:
                return None
            return {
                "id": self.release_id,
                "tag_name": tag,
                "target_commitish": COMMIT,
                "draft": self.existing == "draft",
                "prerelease": False,
                "assets": [
                    {"id": asset_id, "name": name}
                    for name, asset_id in sorted(self.asset_ids.items())
                ],
            }

        def create_draft(self, tag: str, commit: str, title: str) -> None:
            self.events.append("create_draft")
            self.assert_equal(commit, COMMIT)
            self.assert_equal(tag, "v" + VERSION)
            self.assert_equal(title, "Dev Flow Orchestrator " + VERSION)
            self.existing = "draft"

        def upload(self, _tag: str, assets: list[Path]) -> None:
            self.events.append("upload:" + ",".join(path.name for path in assets))
            for path in assets:
                self.asset_ids[path.name] = self._next_asset_id
                self._next_asset_id += 1
            if self.interrupt_upload_once:
                self.interrupt_upload_once = False
                raise promote_release.PromotionError("simulated upload response loss")

        def download_asset(
            self,
            asset_id: int,
            destination: Path,
            maximum: int,
        ) -> None:
            self.events.append("download:{}:{}".format(asset_id, self.existing))
            name = next(
                name for name, observed_id in self.asset_ids.items() if observed_id == asset_id
            )
            source = self.assets / name
            self.assert_less_equal(source.stat().st_size, maximum)
            if name == self.corrupt:
                destination.write_bytes(b"changed authenticated asset\n")
            else:
                shutil.copyfile(source, destination)

        def publish(self, _tag: str) -> None:
            self.events.append("publish")
            self.existing = "published"

        @staticmethod
        def assert_equal(left: object, right: object) -> None:
            if left != right:
                raise AssertionError((left, right))

        @staticmethod
        def assert_less_equal(left: int, right: int) -> None:
            if left > right:
                raise AssertionError((left, right))

    def _fixture(self, work: Path) -> tuple[Path, Path]:
        source = work / "source"
        source.mkdir()
        assets = work / "assets"
        _assemble(source, assets)
        return assets, work / "promotion.json"

    def test_promotion_refuses_existing_version_without_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets, existing="published")
            with self.assertRaisesRegex(promote_release.PromotionError, "overwrite"):
                promote_release.promote_release(
                    assets,
                    version=VERSION,
                    journal_path=journal,
                    api=api,
                )
            self.assertNotIn("create_draft", api.events)
            self.assertNotIn("publish", api.events)

    def test_promotion_refuses_unrecorded_existing_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets, existing="draft")
            with self.assertRaisesRegex(promote_release.PromotionError, "ambiguous"):
                promote_release.promote_release(
                    assets,
                    version=VERSION,
                    journal_path=journal,
                    api=api,
                )
            self.assertNotIn("upload:", "\n".join(api.events))
            self.assertNotIn("publish", api.events)

    def test_promotion_redownloads_and_records_all_component_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets)

            result = promote_release.promote_release(
                assets,
                version=VERSION,
                journal_path=journal,
                api=api,
            )
            self.assertTrue(result["redownloaded"])
            self.assertTrue(result["published"])
            self.assertEqual(result["phase"], "published")
            self.assertEqual(result["schema"], promote_release.PROMOTION_SCHEMA)
            self.assertEqual(
                set(result["final_component_digests"]),
                {
                    "index",
                    "archive",
                    "manifest",
                    "wheel",
                    "requirements",
                    "lock",
                    "plugin",
                    "lifecycle",
                    "install_sh",
                    "install_ps1",
                },
            )
            self.assertEqual(
                json.loads(journal.read_text(encoding="utf-8"))["phase"],
                "published",
            )

    def test_promotion_keeps_release_draft_until_redownload_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets)

            promote_release.promote_release(
                assets,
                version=VERSION,
                journal_path=journal,
                api=api,
            )
            download_positions = [
                index for index, event in enumerate(api.events) if event.startswith("download:")
            ]
            publish_position = api.events.index("publish")
            self.assertEqual(len(download_positions), 4)
            self.assertTrue(all(position < publish_position for position in download_positions))
            self.assertTrue(
                all(api.events[position].endswith(":draft") for position in download_positions)
            )

    def test_promotion_rejects_redownload_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets, corrupt="install.ps1")

            with self.assertRaises(promote_release.PromotionError):
                promote_release.promote_release(
                    assets,
                    version=VERSION,
                    journal_path=journal,
                    api=api,
                )
            self.assertEqual(api.existing, "draft")
            self.assertNotIn("publish", api.events)
            record = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(record["phase"], "assets_uploaded")
            self.assertIsInstance(record["diagnostic"], str)

    def test_promotion_proves_remote_source_before_creating_draft(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets, wrong_source=True)
            with self.assertRaisesRegex(promote_release.PromotionError, "commit/tree"):
                promote_release.promote_release(
                    assets,
                    version=VERSION,
                    journal_path=journal,
                    api=api,
                )
            self.assertNotIn("create_draft", api.events)

    def test_promotion_resumes_recorded_draft_after_upload_response_loss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            assets, journal = self._fixture(work)
            api = self.FakeAPI(assets, interrupt_upload_once=True)
            with self.assertRaisesRegex(promote_release.PromotionError, "response loss"):
                promote_release.promote_release(
                    assets,
                    version=VERSION,
                    journal_path=journal,
                    api=api,
                )
            first_uploads = sum(event.startswith("upload:") for event in api.events)
            self.assertEqual(first_uploads, 1)
            result = promote_release.promote_release(
                assets,
                version=VERSION,
                journal_path=journal,
                api=api,
            )
            self.assertEqual(result["phase"], "published")
            self.assertEqual(
                sum(event.startswith("upload:") for event in api.events),
                1,
            )

    def test_default_api_uses_draft_and_authenticated_asset_id_endpoints(self) -> None:
        class Runner:
            def __init__(self, raw: bytes) -> None:
                self.raw = raw
                self.commands: list[list[str]] = []

            def __call__(self, command, **kwargs):
                self.commands.append(list(command))
                output = kwargs.get("stdout")
                if output is not None:
                    output.write(self.raw)
                    return subprocess.CompletedProcess(command, 0, stdout=None, stderr=b"")
                return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            runner = Runner(b"authenticated bytes")
            api = promote_release.GitHubReleaseAPI(
                release_artifact.CANONICAL_REPOSITORY,
                work,
                runner,
            )
            api.create_draft("v1.2.3", COMMIT, "release")
            destination = work / "asset.bin"
            api.download_asset(123, destination, 1024)
            api.publish("v1.2.3")
            self.assertEqual(destination.read_bytes(), b"authenticated bytes")
            create = runner.commands[0]
            download = runner.commands[1]
            publish = runner.commands[2]
            self.assertIn("--draft", create)
            self.assertIn("repos/{}/releases/assets/123".format(
                release_artifact.CANONICAL_REPOSITORY
            ), download)
            self.assertIn("Accept: application/octet-stream", download)
            self.assertIn("--draft=false", publish)


if __name__ == "__main__":
    unittest.main()
