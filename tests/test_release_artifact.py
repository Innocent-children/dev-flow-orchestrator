"""Focused Phase A release-artifact contract tests."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "release_artifact", ROOT / "scripts" / "release_artifact.py"
)
assert SPEC is not None and SPEC.loader is not None
release_artifact = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_artifact)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _manifest_entry(path: str, raw: bytes | None = None) -> dict[str, object]:
    if raw is None:
        return {"path": path, "type": "directory", "mode": 0o755}
    executable = (
        path.startswith("lifecycle/") and path.endswith((".py", ".sh"))
    )
    return {
        "path": path,
        "type": "file",
        "mode": 0o755 if executable else 0o644,
        "size": len(raw),
        "sha256": _sha256(raw),
    }


def artifact_fixture(
    work: Path,
    *,
    version: str = "1.2.3",
    extra_files: dict[str, bytes] | None = None,
    manifest_mutator=None,
    tar_mutator=None,
    member_mutator=None,
) -> tuple[Path, dict[str, object], bytes]:
    files = {
        "plugin/.codex-plugin/plugin.json": json.dumps(
            {"name": "dev-flow-orchestrator", "version": version}
        ).encode(),
        "plugin/.mcp.json": b'{"mcpServers":{}}\n',
        "plugin/skills/dev-flow/SKILL.md": b"---\nname: dev-flow\n---\n",
        "wheels/dev_flow_orchestrator-{}-py3-none-any.whl".format(version): b"wheel",
        "runtime-requirements.txt": (
            "dependency==1.0 ; python_version >= '3.10' \\\n"
            "    --hash=sha256:{}\n".format("a" * 64)
        ).encode(),
        "uv.lock": b"version = 1\n",
    }
    for lifecycle_name in (
        "release_lifecycle.py",
        "manage_runtime.py",
        "runtime_integrity.py",
        "validate_installed_stage1.py",
        "release_artifact.py",
        "lifecycle_state.py",
        "lifecycle_machine.py",
        "legacy_migration.py",
        "render_dispatchers.py",
        "stable_dispatcher.py",
        "uninstall_driver.py",
    ):
        files["lifecycle/" + lifecycle_name] = b"#!/usr/bin/env python3\n"
    files["lifecycle/legacy_predecessor.json"] = b"{}\n"
    files.update(extra_files or {})
    directories: set[str] = set()
    for name in files:
        parts = name.split("/")
        directories.update("/".join(parts[:depth]) for depth in range(1, len(parts)))
    entries = [_manifest_entry(path) for path in sorted(directories)]
    entries += [_manifest_entry(path, raw) for path, raw in sorted(files.items())]
    entries.sort(key=lambda item: str(item["path"]))
    manifest: dict[str, object] = {
        "schema": release_artifact.ARTIFACT_SCHEMA,
        "version": version,
        "entries": entries,
    }
    if manifest_mutator:
        manifest_mutator(manifest)
    manifest_raw = release_artifact.canonical_json_bytes(manifest)
    all_files = dict(files)
    all_files[release_artifact.MANIFEST_NAME] = manifest_raw
    root_name = "dev-flow-orchestrator-{}".format(version)
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        root_info = tarfile.TarInfo(root_name)
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        root_info.mtime = 0
        archive.addfile(root_info)
        for directory in sorted(directories):
            info = tarfile.TarInfo(root_name + "/" + directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.mtime = 0
            archive.addfile(info)
        for name, raw in sorted(all_files.items()):
            info = tarfile.TarInfo(root_name + "/" + name)
            info.size = len(raw)
            info.mode = release_artifact._expected_mode(name, False)
            info.mtime = 0
            if member_mutator:
                member_mutator(info, name)
            archive.addfile(info, io.BytesIO(raw))
        if tar_mutator:
            tar_mutator(archive, root_name)
    archive_path = work / "dev-flow-orchestrator-{}.tar.gz".format(version)
    with archive_path.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            compressed.write(tar_buffer.getvalue())
    archive_raw = archive_path.read_bytes()
    index = {
        "schema": release_artifact.INDEX_SCHEMA,
        "artifact_schema": release_artifact.ARTIFACT_SCHEMA,
        "repository": release_artifact.CANONICAL_REPOSITORY,
        "version": version,
        "source_commit": "1" * 40,
        "source_tree": "2" * 40,
        "archive": {
            "name": archive_path.name,
            "size": len(archive_raw),
            "sha256": _sha256(archive_raw),
        },
        "manifest_sha256": _sha256(manifest_raw),
        "limits": dict(release_artifact.HARD_LIMITS),
    }
    return archive_path, index, manifest_raw


class ReleaseIndexTests(unittest.TestCase):
    def test_digest_is_checked_before_malformed_index_is_parsed(self) -> None:
        raw = b'{"schema":'
        with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "digest mismatch"):
            release_artifact.verify_release_index_bytes(
                raw,
                "0" * 64,
                release_artifact.CANONICAL_REPOSITORY,
                "1.2.3",
                "dev-flow-orchestrator-1.2.3.tar.gz",
            )

    def test_duplicate_and_unknown_index_fields_are_rejected(self) -> None:
        duplicate = b'{"schema":"a","schema":"b"}'
        with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "strict UTF-8 JSON"):
            release_artifact.strict_json_bytes(duplicate, maximum=1000, label="index")
        with tempfile.TemporaryDirectory() as temporary:
            _, index, _ = artifact_fixture(Path(temporary))
            index["unknown"] = True
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "fields"):
                release_artifact.validate_release_index(index)

    def test_index_cannot_raise_a_bootstrap_hard_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, index, _ = artifact_fixture(Path(temporary))
            index["limits"]["entry_count"] = release_artifact.HARD_LIMITS["entry_count"] + 1
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "supported range"):
                release_artifact.validate_release_index(index)

    def test_index_json_byte_cap_is_applied_before_parsing(self) -> None:
        raw = b" " * (release_artifact.HARD_LIMITS["index_bytes"] + 1)
        with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "byte limit"):
            release_artifact.strict_json_bytes(
                raw,
                maximum=release_artifact.HARD_LIMITS["index_bytes"],
                label="release index",
            )


class PhaseBoundaryArgumentTests(unittest.TestCase):
    def test_allowed_options_preserve_equals_spaces_apostrophes_and_unicode(self) -> None:
        values = {
            "--runtime-root": "/tmp/Dev Flow runtime's 数据",
            "--bin-dir": "/tmp/Dev Flow bin's 数据",
            "--marketplace-file": "/tmp/市场's 路径/marketplace.json",
            "--codex-home": "/tmp/Codex home ' 数据",
            "--data-root": "/tmp/task data's 数据",
            "--lock-timeout": "1.25",
        }
        supplied: list[str] = []
        expected: list[str] = []
        for offset, (option, value) in enumerate(values.items()):
            supplied.extend(
                [option + "=" + value] if offset % 2 == 0 else [option, value]
            )
            expected.extend((option, value))
        self.assertEqual(
            release_artifact.normalize_phase_b_user_args(supplied),
            tuple(expected),
        )

    def test_duplicates_abbreviations_identity_and_positional_input_are_rejected(self) -> None:
        invalid = (
            ("--runtime-root", "/tmp/a", "--runtime-root=/tmp/b"),
            ("--runtime", "/tmp/a"),
            ("--artifact-root", "/tmp/a"),
            ("--release-index=/tmp/index.json",),
            ("--repository", release_artifact.CANONICAL_REPOSITORY),
            ("--version=1.2.3",),
            ("positional",),
            ("--",),
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(
                release_artifact.ReleaseArtifactError
            ):
                release_artifact.normalize_phase_b_user_args(arguments)


class PortablePathTests(unittest.TestCase):
    def test_portable_ascii_paths_and_collision_key(self) -> None:
        self.assertEqual(
            release_artifact.portable_path_parts("plugin/.codex-plugin/plugin.json"),
            ("plugin", ".codex-plugin", "plugin.json"),
        )
        self.assertEqual(
            release_artifact.portable_path_key("Plugin/File.TXT"), "plugin/file.txt"
        )

    def test_unsafe_and_windows_device_paths_are_rejected(self) -> None:
        unsafe = (
            "/absolute",
            "C:/drive",
            "a\\b",
            "a//b",
            "a/../b",
            "a/.",
            "a/trailing.",
            "a/trailing ",
            "a/control\x1f",
            "unicod\N{LATIN SMALL LETTER E WITH ACUTE}",
            "CON",
            "nul.txt",
            "dir/COM9.log",
            "LPT1",
        )
        for path in unsafe:
            with self.subTest(path=path):
                with self.assertRaises(release_artifact.ReleaseArtifactError):
                    release_artifact.portable_path_parts(path)


class ArtifactExtractionTests(unittest.TestCase):
    def test_complete_artifact_is_extracted_and_manifest_excludes_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, manifest_raw = artifact_fixture(work)
            index_raw = release_artifact.canonical_json_bytes(index)
            parsed = release_artifact.verify_release_index_bytes(
                index_raw,
                _sha256(index_raw),
                release_artifact.CANONICAL_REPOSITORY,
                "1.2.3",
                archive.name,
            )
            result = release_artifact.inspect_and_extract_artifact(
                archive, work.resolve() / "extract", parsed
            )
            self.assertEqual(result["manifest_sha256"], _sha256(manifest_raw))
            self.assertEqual(result["release_id"], "v1.2.3-" + _sha256(manifest_raw)[:16])
            paths = {entry["path"] for entry in result["inventory"]}
            self.assertNotIn(release_artifact.MANIFEST_NAME, paths)
            self.assertTrue(Path(result["topology"]["wheel_path"]).is_file())

    @unittest.skipIf(os.name == "nt", "POSIX umask semantics are required")
    def test_restrictive_umask_preserves_verified_archive_directory_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work)
            destination = work / "extract"
            previous_umask = os.umask(0o077)
            try:
                result = release_artifact.inspect_and_extract_artifact(
                    archive, destination, index
                )
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            release_root = Path(result["root"])
            self.assertEqual(stat.S_IMODE(release_root.stat().st_mode), 0o755)
            for entry in result["inventory"]:
                if entry["type"] != "directory":
                    continue
                extracted = release_root.joinpath(*str(entry["path"]).split("/"))
                self.assertEqual(
                    stat.S_IMODE(extracted.stat().st_mode),
                    0o755,
                    str(entry["path"]),
                )

    def test_destination_must_be_new(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, _ = artifact_fixture(work)
            destination = work.resolve() / "exists"
            destination.mkdir()
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "newly absent"):
                release_artifact.inspect_and_extract_artifact(archive, destination, index)

    def test_manifest_missing_inventory_entry_is_rejected_and_cleaned(self) -> None:
        def mutate(manifest: dict[str, object]) -> None:
            manifest["entries"] = [
                item for item in manifest["entries"] if item["path"] != "uv.lock"
            ]

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, _ = artifact_fixture(work, manifest_mutator=mutate)
            destination = work.resolve() / "extract"
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "inventory mismatch"):
                release_artifact.inspect_and_extract_artifact(archive, destination, index)
            self.assertFalse(destination.exists())

    def test_manifest_self_entry_is_rejected(self) -> None:
        def mutate(manifest: dict[str, object]) -> None:
            manifest["entries"].append(
                _manifest_entry(release_artifact.MANIFEST_NAME, b"impossible")
            )
            manifest["entries"].sort(key=lambda item: item["path"])

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, _ = artifact_fixture(work, manifest_mutator=mutate)
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "exclude itself"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work.resolve() / "extract", index
                )

    def test_link_tar_member_is_rejected_before_extraction(self) -> None:
        def mutate(archive: tarfile.TarFile, root: str) -> None:
            info = tarfile.TarInfo(root + "/plugin/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "../uv.lock"
            info.mode = 0o644
            archive.addfile(info)

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, _ = artifact_fixture(work, tar_mutator=mutate)
            destination = work.resolve() / "extract"
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "links and special"):
                release_artifact.inspect_and_extract_artifact(archive, destination, index)
            self.assertFalse(destination.exists())

    def test_case_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            archive, index, _ = artifact_fixture(
                work,
                extra_files={
                    "plugin/Case.txt": b"a",
                    "plugin/case.txt": b"b",
                },
            )
            with self.assertRaisesRegex(
                release_artifact.ReleaseArtifactError, "case-colliding"
            ):
                release_artifact.inspect_and_extract_artifact(
                    archive, work.resolve() / "extract", index
                )

    def test_archive_and_manifest_digest_mismatch_fail_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work)
            changed_archive = dict(index)
            changed_archive["archive"] = dict(index["archive"])
            changed_archive["archive"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "digest mismatch"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "archive-digest", changed_archive
                )
            changed_manifest = dict(index)
            changed_manifest["manifest_sha256"] = "0" * 64
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "manifest digest"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "manifest-digest", changed_manifest
                )
            self.assertFalse((work / "archive-digest").exists())
            self.assertFalse((work / "manifest-digest").exists())

    def test_declared_missing_member_and_file_hard_cap_are_rejected(self) -> None:
        def declare_missing(manifest: dict[str, object]) -> None:
            manifest["entries"].append(_manifest_entry("plugin/missing.txt", b"missing"))
            manifest["entries"].sort(key=lambda item: item["path"])

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work, manifest_mutator=declare_missing)
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "inventory mismatch"):
                release_artifact.inspect_and_extract_artifact(archive, work / "missing", index)
            archive, index, _ = artifact_fixture(work)
            index["limits"] = dict(index["limits"])
            index["limits"]["file_bytes"] = 1
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "byte limit"):
                release_artifact.inspect_and_extract_artifact(archive, work / "capped", index)

    def test_hardlink_sparse_fifo_and_tar_extension_are_rejected(self) -> None:
        cases = (
            ("hardlink", tarfile.LNKTYPE),
            ("sparse", tarfile.GNUTYPE_SPARSE),
            ("fifo", tarfile.FIFOTYPE),
            ("extension", tarfile.XHDTYPE),
        )
        for label, member_type in cases:
            with self.subTest(member=label), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary).resolve()

                def mutate(archive: tarfile.TarFile, root: str) -> None:
                    info = tarfile.TarInfo(root + "/plugin/" + label)
                    info.type = member_type
                    info.linkname = "uv.lock" if member_type == tarfile.LNKTYPE else ""
                    info.mode = 0o644
                    archive.addfile(info)

                archive, index, _ = artifact_fixture(work, tar_mutator=mutate)
                with self.assertRaises(release_artifact.ReleaseArtifactError):
                    release_artifact.inspect_and_extract_artifact(
                        archive, work / "extract", index
                    )

    def test_noncanonical_tar_metadata_is_rejected(self) -> None:
        def mutate(archive: tarfile.TarFile, root: str) -> None:
            info = tarfile.TarInfo(root + "/plugin/noncanonical.txt")
            info.type = tarfile.REGTYPE
            info.mode = 0o644
            info.uid = 501
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work, tar_mutator=mutate)
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "tar profile"):
                release_artifact.inspect_and_extract_artifact(archive, work / "extract", index)

    def test_physical_gnu_longname_header_hidden_by_tarfile_is_rejected(self) -> None:
        long_name = "dev-flow-orchestrator-1.2.3/plugin/" + ("a" * 101)

        def mutate(archive: tarfile.TarFile, _root: str) -> None:
            long_name_raw = long_name.encode("ascii") + b"\0"
            extension = tarfile.TarInfo("././@LongLink")
            extension.type = tarfile.GNUTYPE_LONGNAME
            extension.mode = 0o644
            extension.mtime = 0
            extension.size = len(long_name_raw)
            archive.addfile(extension, io.BytesIO(long_name_raw))
            payload = tarfile.TarInfo("placeholder")
            payload.type = tarfile.REGTYPE
            payload.mode = 0o644
            payload.mtime = 0
            payload.size = 1
            archive.addfile(payload, io.BytesIO(b"x"))

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work, tar_mutator=mutate)
            # tarfile consumes the physical GNU header and exposes only its
            # logical regular-file member, which is why Phase A scans headers.
            with tarfile.open(archive, "r:gz") as parsed:
                self.assertNotIn(
                    tarfile.GNUTYPE_LONGNAME,
                    {member.type for member in parsed.getmembers()},
                )
            with self.assertRaisesRegex(
                release_artifact.ReleaseArtifactError,
                "extensions, links and special headers",
            ):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "extract", index
                )
            self.assertFalse((work / "extract").exists())

    def test_manifest_and_archive_resource_caps_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, manifest_raw = artifact_fixture(work)

            manifest_capped = dict(index)
            manifest_capped["limits"] = dict(index["limits"])
            manifest_capped["limits"]["manifest_bytes"] = len(manifest_raw) - 1
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "manifest"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "manifest-capped", manifest_capped
                )
            self.assertFalse((work / "manifest-capped").exists())

            archive_capped = dict(index)
            archive_capped["limits"] = dict(index["limits"])
            archive_capped["limits"]["archive_bytes"] = int(index["archive"]["size"]) - 1
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "supported range"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "archive-capped", archive_capped
                )
            self.assertFalse((work / "archive-capped").exists())

            oversized_archive = work / "oversized.tar.gz"
            oversized_archive.write_bytes(archive.read_bytes() + b"x")
            streaming_capped = dict(index)
            streaming_capped["archive"] = dict(index["archive"])
            streaming_capped["limits"] = dict(index["limits"])
            streaming_capped["limits"]["archive_bytes"] = int(index["archive"]["size"])
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "byte limit"):
                release_artifact.inspect_and_extract_artifact(
                    oversized_archive, work / "streaming-capped", streaming_capped
                )
            self.assertFalse((work / "streaming-capped").exists())

    def test_wrong_member_mode_is_rejected_before_extraction(self) -> None:
        def change_mode(info: tarfile.TarInfo, relative: str) -> None:
            if relative == "uv.lock":
                info.mode = 0o755

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work, member_mutator=change_mode)
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "member mode"):
                release_artifact.inspect_and_extract_artifact(
                    archive, work / "extract", index
                )
            self.assertFalse((work / "extract").exists())

    def test_linked_destination_ancestor_and_existing_destination_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work)
            real_parent = work / "real-parent"
            real_parent.mkdir()
            linked_parent = work / "linked-parent"
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "linked, reparsed"):
                release_artifact.inspect_and_extract_artifact(
                    archive, linked_parent / "extract", index
                )
            self.assertFalse((real_parent / "extract").exists())

    def test_mocked_windows_reparse_ancestor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            ancestor = work / "mocked-reparse"
            ancestor.mkdir()
            original_lstat = Path.lstat

            def lstat_with_reparse(path: Path):
                metadata = original_lstat(path)
                if path == ancestor:
                    return mock.Mock(
                        st_mode=metadata.st_mode,
                        st_file_attributes=0x400,
                    )
                return metadata

            with mock.patch.object(Path, "lstat", lstat_with_reparse):
                with self.assertRaisesRegex(
                    release_artifact.ReleaseArtifactError, "linked, reparsed"
                ):
                    release_artifact._safe_destination(ancestor / "extract")

    def test_exclusive_creation_race_preserves_the_competing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work)
            destination = work / "raced"
            original_safe_destination = release_artifact._safe_destination

            def introduce_race(path: Path) -> None:
                original_safe_destination(path)
                path.mkdir()
                (path / "not-installer-owned").write_text("preserve", encoding="utf-8")

            with mock.patch.object(
                release_artifact,
                "_safe_destination",
                side_effect=introduce_race,
            ):
                with self.assertRaisesRegex(
                    release_artifact.ReleaseArtifactError, "exclusive-creation race"
                ):
                    release_artifact.inspect_and_extract_artifact(
                        archive, destination, index
                    )
            self.assertEqual(
                (destination / "not-installer-owned").read_text(encoding="utf-8"),
                "preserve",
            )

    def test_phase_a_failure_never_executes_artifact_code(self) -> None:
        class Response:
            def __init__(self, raw: bytes, url: str):
                self.raw = io.BytesIO(raw)
                self.url = url

            def geturl(self) -> str:
                return self.url

            def read(self, size: int = -1) -> bytes:
                return self.raw.read(size)

        class Opener:
            def __init__(self, index_raw: bytes, archive_raw: bytes):
                self.index_raw = index_raw
                self.archive_raw = archive_raw

            def open(self, request, timeout: int):
                url = request.full_url
                return Response(
                    self.index_raw if url.endswith("release-index.json") else self.archive_raw,
                    url,
                )

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            marker = work / "artifact-code-executed"
            product_state = work / "product-state"
            malicious = (
                "from pathlib import Path\nPath({!r}).write_text('executed')\n".format(str(marker))
            ).encode()
            archive, index, _ = artifact_fixture(
                work,
                extra_files={"lifecycle/release_lifecycle.py": malicious},
            )
            index["manifest_sha256"] = "0" * 64
            index_raw = release_artifact.canonical_json_bytes(index)
            with mock.patch.object(release_artifact.subprocess, "run") as run:
                with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "manifest digest"):
                    release_artifact.bootstrap(
                        repository=release_artifact.CANONICAL_REPOSITORY,
                        version="1.2.3",
                        archive_name=archive.name,
                        index_sha256=_sha256(index_raw),
                        phase_b_args=("--runtime-root", str(product_state)),
                        opener=Opener(index_raw, archive.read_bytes()),
                    )
            run.assert_not_called()
            self.assertFalse(marker.exists())
            self.assertFalse(product_state.exists())

    def test_phase_a_rejects_user_override_of_artifact_identity(self) -> None:
        class Response:
            def __init__(self, raw: bytes, url: str):
                self.raw = io.BytesIO(raw)
                self.url = url

            def geturl(self) -> str:
                return self.url

            def read(self, size: int = -1) -> bytes:
                return self.raw.read(size)

        class Opener:
            def __init__(self, index_raw: bytes, archive_raw: bytes):
                self.index_raw = index_raw
                self.archive_raw = archive_raw

            def open(self, request, timeout: int):
                url = request.full_url
                raw = (
                    self.index_raw
                    if url.endswith("release-index.json")
                    else self.archive_raw
                )
                return Response(raw, url)

        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            archive, index, _ = artifact_fixture(work)
            index_raw = release_artifact.canonical_json_bytes(index)
            with mock.patch.object(release_artifact.subprocess, "run") as run:
                with self.assertRaisesRegex(
                    release_artifact.ReleaseArtifactError,
                    "artifact-root|identity",
                ):
                    release_artifact.bootstrap(
                        repository=release_artifact.CANONICAL_REPOSITORY,
                        version="1.2.3",
                        archive_name=archive.name,
                        index_sha256=_sha256(index_raw),
                        phase_b_args=(
                            "--artifact-root",
                            str(work / "attacker-controlled"),
                        ),
                        opener=Opener(index_raw, archive.read_bytes()),
                    )
            run.assert_not_called()

    def test_phase_a_rechecks_wheel_and_lifecycle_before_execution(self) -> None:
        class Response:
            def __init__(self, raw: bytes, url: str):
                self.raw = io.BytesIO(raw)
                self.url = url

            def geturl(self) -> str:
                return self.url

            def read(self, size: int = -1) -> bytes:
                return self.raw.read(size)

        class Opener:
            def __init__(self, index_raw: bytes, archive_raw: bytes):
                self.index_raw = index_raw
                self.archive_raw = archive_raw

            def open(self, request, timeout: int):
                url = request.full_url
                raw = (
                    self.index_raw
                    if url.endswith("release-index.json")
                    else self.archive_raw
                )
                return Response(raw, url)

        for relative in (
            "wheels/dev_flow_orchestrator-1.2.3-py3-none-any.whl",
            "lifecycle/release_lifecycle.py",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary).resolve()
                archive, index, _ = artifact_fixture(work)
                index_raw = release_artifact.canonical_json_bytes(index)
                original = release_artifact.inspect_and_extract_artifact

                def replace_after_extract(*args, **kwargs):
                    verified = original(*args, **kwargs)
                    (Path(str(verified["root"])) / relative).write_bytes(b"replacement\n")
                    return verified

                with (
                    mock.patch.object(
                        release_artifact,
                        "inspect_and_extract_artifact",
                        side_effect=replace_after_extract,
                    ),
                    mock.patch.object(release_artifact.subprocess, "run") as run,
                    self.assertRaisesRegex(
                        release_artifact.ReleaseArtifactError,
                        "inventory mismatch",
                    ),
                ):
                    release_artifact.bootstrap(
                        repository=release_artifact.CANONICAL_REPOSITORY,
                        version="1.2.3",
                        archive_name=archive.name,
                        index_sha256=_sha256(index_raw),
                        opener=Opener(index_raw, archive.read_bytes()),
                    )
                run.assert_not_called()


class DownloadBoundaryTests(unittest.TestCase):
    class Response:
        def __init__(
            self,
            raw: bytes,
            *,
            final_url: str = "https://objects.githubusercontent.com/release",
            content_length: str | None = None,
        ) -> None:
            self._raw = io.BytesIO(raw)
            self._final_url = final_url
            self.headers = {}
            if content_length is not None:
                self.headers["Content-Length"] = content_length
            self.closed = False

        def geturl(self) -> str:
            return self._final_url

        def read(self, size: int = -1) -> bytes:
            return self._raw.read(size)

        def close(self) -> None:
            self.closed = True

    class Opener:
        def __init__(self, response) -> None:
            self.response = response
            self.calls = 0

        def open(self, request, timeout: int):
            self.calls += 1
            return self.response

    def test_installer_staging_cleanup_is_bounded_and_reports_exact_residue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "staging"
            nested = root / "nested"
            nested.mkdir(parents=True)
            retained = nested / "locked.bin"
            retained.write_bytes(b"locked")
            original_unlink = Path.unlink

            def unlink(path: Path, *args, **kwargs):
                if path == retained:
                    raise PermissionError("fixture lock")
                return original_unlink(path, *args, **kwargs)

            with mock.patch.object(
                Path, "unlink", autospec=True, side_effect=unlink
            ):
                residue = release_artifact._cleanup_installer_staging(root)
            self.assertIn(str(retained), residue)
            self.assertIn(str(root), residue)
            self.assertTrue(retained.exists())

    def test_streaming_download_stops_at_the_fixed_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "bounded"
            response = self.Response(b"12345")
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "byte limit"):
                release_artifact._download(
                    "https://github.com/example/release",
                    destination,
                    maximum=4,
                    opener=self.Opener(response),
                    collect=False,
                )
            self.assertTrue(response.closed)
            self.assertEqual(destination.read_bytes(), b"")

    def test_download_rejects_non_https_input_redirect_and_final_url(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            opener = self.Opener(self.Response(b"unused"))
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "not HTTPS"):
                release_artifact._download(
                    "http://github.com/example/release",
                    work / "initial-http",
                    maximum=10,
                    opener=opener,
                )
            self.assertEqual(opener.calls, 0)

            response = self.Response(b"unused", final_url="http://example.invalid/release")
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "non-HTTPS"):
                release_artifact._download(
                    "https://github.com/example/release",
                    work / "final-http",
                    maximum=10,
                    opener=self.Opener(response),
                )
            self.assertTrue(response.closed)

            handler = release_artifact._HttpsRedirectsOnly()
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "not HTTPS"):
                handler.redirect_request(
                    mock.Mock(full_url="https://github.com/example/release"),
                    None,
                    302,
                    "Found",
                    {},
                    "http://example.invalid/release",
                )

    def test_declared_download_size_is_bounded_before_file_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "declared-too-large"
            response = self.Response(b"x", content_length="5")
            with self.assertRaisesRegex(release_artifact.ReleaseArtifactError, "byte limit"):
                release_artifact._download(
                    "https://github.com/example/release",
                    destination,
                    maximum=4,
                    opener=self.Opener(response),
                )
            self.assertTrue(response.closed)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
