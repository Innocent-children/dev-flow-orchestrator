from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import candidate_identity
from scripts import run_bundled_validators
from scripts import windows_native_validation


class CandidateIdentityTests(unittest.TestCase):
    def _candidate(self, root: Path) -> Path:
        candidate = root / "candidate"
        (candidate / "scripts").mkdir(parents=True)
        (candidate / "README.md").write_bytes(b"hello\n")
        (candidate / "scripts" / "\u6d4b\u8bd5.py").write_bytes(b'print("ok")\n')
        return candidate

    def test_normative_golden_vector_is_exact(self) -> None:
        candidate_identity.assert_golden_vector()
        entries = [
            candidate_identity.CanonicalEntry("README.md", b"hello\n"),
            candidate_identity.CanonicalEntry(
                "scripts/\u6d4b\u8bd5.py",
                b'print("ok")\n',
            ),
        ]
        preimage = candidate_identity.canonical_preimage(entries)
        digest, count = candidate_identity.canonical_digest(entries)
        self.assertEqual(preimage.hex(), candidate_identity.GOLDEN_PREIMAGE_HEX)
        self.assertEqual(digest, candidate_identity.GOLDEN_SHA256)
        self.assertEqual(count, 2)

    def test_path_grammar_and_portable_collisions_fail_closed(self) -> None:
        for invalid in (
            "",
            "/absolute",
            "//server/share",
            "C:/drive",
            "scripts\\file.py",
            "./file",
            "scripts/../file",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(candidate_identity.CandidateIdentityError):
                    candidate_identity.validate_relative_path(invalid)
        with self.assertRaisesRegex(
            candidate_identity.CandidateIdentityError,
            "portable candidate path collision",
        ):
            candidate_identity.canonical_digest(
                [
                    candidate_identity.CanonicalEntry("README.md", b"a"),
                    candidate_identity.CanonicalEntry("readme.MD", b"b"),
                ]
            )

    def test_canonical_digest_ignores_mode_but_host_snapshot_keeps_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            script = candidate / "scripts" / "\u6d4b\u8bd5.py"
            script.chmod(0o600)
            canonical_before, _ = candidate_identity.candidate_digest(candidate)
            host_before, _ = run_bundled_validators.snapshot_digest(candidate)
            script.chmod(0o700)
            canonical_after, _ = candidate_identity.candidate_digest(candidate)
            host_after, _ = run_bundled_validators.snapshot_digest(candidate)
        self.assertEqual(canonical_before, canonical_after)
        if os.name != "nt":
            self.assertNotEqual(host_before, host_after)

    def test_bytes_change_digest_and_openspec_is_canonical_only_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            planning = candidate / "openspec" / "changes" / "sample"
            planning.mkdir(parents=True)
            task = planning / "tasks.md"
            task.write_text("- [ ] pending\n", encoding="utf-8")
            canonical_before, _ = candidate_identity.candidate_digest(candidate)
            host_before, _ = run_bundled_validators.snapshot_digest(candidate)
            task.write_text("- [x] complete\n", encoding="utf-8")
            canonical_after, _ = candidate_identity.candidate_digest(candidate)
            host_after, _ = run_bundled_validators.snapshot_digest(candidate)
            self.assertEqual(canonical_before, canonical_after)
            self.assertNotEqual(host_before, host_after)
            (candidate / "README.md").write_bytes(b"hello\r\n")
            transformed, _ = candidate_identity.candidate_digest(candidate)
        self.assertNotEqual(canonical_after, transformed)

    def test_exclusions_are_narrow_and_unexpected_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            (candidate / "__pycache__").mkdir()
            (candidate / "__pycache__" / "ignored.pyc").write_bytes(b"x")
            (candidate / ".DS_Store").write_bytes(b"x")
            candidate_identity.candidate_digest(candidate)
            (candidate / "unexpected.txt").write_bytes(b"x")
            with self.assertRaisesRegex(
                candidate_identity.CandidateIdentityError,
                "outside canonical allowlist",
            ):
                candidate_identity.candidate_digest(candidate)

    @unittest.skipIf(os.name == "nt", "POSIX symlink creation is exercised here")
    def test_handoff_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            os.symlink("README.md", candidate / "scripts" / "linked.py")
            with self.assertRaisesRegex(
                candidate_identity.CandidateIdentityError,
                "symlink/reparse",
            ):
                candidate_identity.candidate_digest(candidate)

    def test_handoff_is_reproducible_verified_and_binary_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            first_archive = root / "first.zip"
            first_manifest = root / "first.json"
            second_archive = root / "second.zip"
            second_manifest = root / "second.json"
            first = candidate_identity.build_handoff(
                candidate,
                first_archive,
                first_manifest,
            )
            second = candidate_identity.build_handoff(
                candidate,
                second_archive,
                second_manifest,
            )
            self.assertEqual(first_archive.read_bytes(), second_archive.read_bytes())
            self.assertEqual(first, second)
            expected = first["candidate"]["sha256"]
            verified, entries = candidate_identity.verify_handoff(
                first_archive,
                first_manifest,
                expected,
            )
            self.assertEqual(verified, first)
            self.assertEqual([entry.path for entry in entries], list(
                member["path"] for member in first["members"]
            ))
            extracted = root / "extracted"
            candidate_identity.extract_verified_handoff(
                first_archive,
                first_manifest,
                expected,
                extracted,
            )
            self.assertEqual(
                candidate_identity.candidate_digest(extracted)[0],
                expected,
            )
            with self.assertRaisesRegex(
                candidate_identity.CandidateIdentityError,
                "new",
            ):
                candidate_identity.build_handoff(
                    candidate,
                    first_archive,
                    root / "third.json",
                )

    def test_archive_metadata_and_member_set_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            document = candidate_identity.build_handoff(
                candidate,
                archive,
                manifest,
            )
            with zipfile.ZipFile(archive, "r") as bundle:
                self.assertTrue(
                    all(info.compress_type == zipfile.ZIP_STORED for info in bundle.infolist())
                )
                self.assertEqual(bundle.comment, b"")
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["members"].append(
                {"path": "../escape", "sha256": "0" * 64, "size": 0}
            )
            payload["candidate"]["path_count"] += 1
            invalid_manifest = root / "invalid.json"
            invalid_manifest.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaises(candidate_identity.CandidateIdentityError):
                candidate_identity.verify_handoff(
                    archive,
                    invalid_manifest,
                    document["candidate"]["sha256"],
                )

    def test_handoff_publication_failure_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            with mock.patch.object(
                candidate_identity.os,
                "link",
                side_effect=OSError("publication failed"),
            ):
                with self.assertRaises(candidate_identity.CandidateIdentityError):
                    candidate_identity.build_handoff(
                        candidate,
                        archive,
                        manifest,
                    )
            self.assertFalse(archive.exists())
            self.assertFalse(manifest.exists())
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["candidate"],
            )

    def test_manifest_destination_race_rolls_back_only_this_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            real_link = os.link
            link_count = 0

            def race_manifest(source, destination):
                nonlocal link_count
                link_count += 1
                if link_count == 2:
                    Path(destination).write_bytes(b"competing manifest\n")
                    raise FileExistsError("manifest destination won by competitor")
                return real_link(source, destination)

            with mock.patch.object(
                candidate_identity.os,
                "link",
                side_effect=race_manifest,
            ):
                with self.assertRaises(candidate_identity.CandidateIdentityError):
                    candidate_identity.build_handoff(
                        candidate,
                        archive,
                        manifest,
                    )
            self.assertEqual(link_count, 2)
            self.assertFalse(archive.exists())
            self.assertEqual(manifest.read_bytes(), b"competing manifest\n")
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["candidate", "candidate.json"],
            )

    def test_archive_temp_cleanup_failure_keeps_valid_handoff_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            real_unlink = Path.unlink

            def fail_archive_temp(path, *arguments, **keywords):
                if path.name.startswith(".candidate.zip.") and path.name.endswith(
                    ".tmp"
                ):
                    raise OSError("simulated Windows sharing violation")
                return real_unlink(path, *arguments, **keywords)

            with mock.patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=fail_archive_temp,
            ):
                document = candidate_identity.build_handoff(
                    candidate,
                    archive,
                    manifest,
                )
            verified, entries = candidate_identity.verify_handoff(
                archive,
                manifest,
                document["candidate"]["sha256"],
            )
            self.assertEqual(verified, document)
            self.assertEqual(len(entries), 2)
            self.assertEqual(
                len(list(root.glob(".candidate.zip.*.tmp"))),
                1,
            )

    def test_manifest_temp_cleanup_failure_keeps_valid_handoff_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            real_unlink = Path.unlink

            def fail_manifest_temp(path, *arguments, **keywords):
                if path.name.startswith(".candidate.json.") and path.name.endswith(
                    ".tmp"
                ):
                    raise OSError("simulated Windows sharing violation")
                return real_unlink(path, *arguments, **keywords)

            with mock.patch.object(
                Path,
                "unlink",
                autospec=True,
                side_effect=fail_manifest_temp,
            ):
                document = candidate_identity.build_handoff(
                    candidate,
                    archive,
                    manifest,
                )
            verified, entries = candidate_identity.verify_handoff(
                archive,
                manifest,
                document["candidate"]["sha256"],
            )
            self.assertEqual(verified, document)
            self.assertEqual(len(entries), 2)
            self.assertEqual(
                len(list(root.glob(".candidate.json.*.tmp"))),
                1,
            )

    def test_non_windows_runner_cannot_report_native_pass(self) -> None:
        if os.name == "nt":
            self.skipTest("non-Windows fail-closed behavior")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._candidate(root)
            archive = root / "candidate.zip"
            manifest = root / "candidate.json"
            document = candidate_identity.build_handoff(
                candidate,
                archive,
                manifest,
            )
            report = root / "native-report.json"
            arguments = [
                "run",
                "--archive",
                str(archive),
                "--manifest",
                str(manifest),
                "--expected-canonical",
                document["candidate"]["sha256"],
                "--local-root",
                str(root / "local"),
                "--unc-root",
                "//server/share/test",
                "--report",
                str(report),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = windows_native_validation.main(arguments)
            report_text = report.read_text(encoding="utf-8")
            value = json.loads(report_text)
            self.assertNotIn(str(root), report_text)
        self.assertNotEqual(exit_code, 0)
        self.assertEqual(value["result"], "incomplete")
        self.assertEqual(
            value["checks"][-1]["diagnostic"],
            "NATIVE_WINDOWS_REQUIRED",
        )

    def test_cleanup_requires_exact_direct_child_and_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / f"{windows_native_validation.CHILD_PREFIX}nonce"
            child.mkdir()
            expected = b'{"nonce":"nonce"}\n'
            (child / windows_native_validation.SENTINEL_NAME).write_bytes(b"wrong")
            with self.assertRaisesRegex(
                windows_native_validation.NativeValidationError,
                "sentinel",
            ):
                windows_native_validation.cleanup_owned_child(
                    root,
                    child,
                    expected,
                )
            self.assertTrue(root.exists())
            self.assertTrue(child.exists())

    def test_managed_worktree_orchestration_uses_controller_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_root = Path(__file__).resolve().parents[1]
            repo = root / "fixture-repository"
            windows_native_validation._initialize_repository(repo)
            windows_native_validation._configure_local_origin(
                candidate_root,
                repo,
                root / "fixture-origin.git",
            )
            contract = (
                windows_native_validation.exercise_controller_managed_worktree(
                    candidate_root,
                    root / "controller-state",
                    repo,
                    repo,
                    root / "managed-worktree",
                    root,
                )
            )
            self.assertEqual(
                contract,
                {
                    "claim_conflict": "WORKSPACE_OWNERSHIP_CONFLICT",
                    "drift_guard": "STALE_WORKSPACE_INDEX",
                    "postcondition": "WORKSPACE_READY",
                },
            )

    def test_release_workflow_binds_reviewed_canonical_in_every_matrix_job(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "cross-platform.yml"
        ).read_text(encoding="utf-8")
        for required in (
            "workflow_dispatch:",
            "reviewed_canonical:",
            "required: true",
            "DEV_FLOW_REVIEWED_CANONICAL:",
            "inputs.reviewed_canonical",
            "re.fullmatch(r'[0-9a-f]{64}',value)",
            "assert_golden_vector",
            "DEV_FLOW_EXPECTED_CANONICAL_SHA256:",
            "python scripts/run_bundled_validators.py --require-available",
        ):
            self.assertIn(required, workflow)
        self.assertEqual(workflow.count("jobs:"), 1)
        self.assertEqual(workflow.count("DEV_FLOW_REVIEWED_CANONICAL:"), 1)
        self.assertEqual(
            workflow.count("DEV_FLOW_EXPECTED_CANONICAL_SHA256:"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
