from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
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

    def test_workflow_inventory_is_part_of_the_canonical_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            workflow_root = candidate / "workflows"
            workflow_root.mkdir()
            catalog = workflow_root / "catalog.json"
            catalog.write_bytes(b'{"schema":"example/v1"}\n')
            before, before_count = candidate_identity.candidate_digest(
                candidate
            )
            catalog.write_bytes(b'{"schema":"example/v2"}\n')
            after, after_count = candidate_identity.candidate_digest(candidate)
        self.assertEqual(before_count, after_count)
        self.assertNotEqual(before, after)

    def test_mcp_configuration_is_part_of_the_canonical_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            configuration = candidate / ".mcp.json"
            configuration.write_bytes(
                b'{"dev-flow":{"enabled":true}}\n'
            )
            before, before_count = candidate_identity.candidate_digest(
                candidate
            )
            configuration.write_bytes(
                b'{"dev-flow":{"enabled":false}}\n'
            )
            after, after_count = candidate_identity.candidate_digest(
                candidate
            )
        self.assertEqual(before_count, after_count)
        self.assertNotEqual(before, after)

    def test_exclusions_are_narrow_and_unexpected_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            (candidate / "CONTRIBUTING.md").write_bytes(b"contract\n")
            reports = candidate / "docs"
            reports.mkdir()
            (reports / "local-review.md").write_bytes(b"not shipped\n")
            entries = candidate_identity.canonical_entries(candidate)
            paths = {entry.path for entry in entries}
            self.assertIn("CONTRIBUTING.md", paths)
            self.assertNotIn("docs/local-review.md", paths)
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

    def test_host_local_exclusions_are_exact_not_directory_wildcards(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = self._candidate(Path(temporary))
            local_settings = (
                candidate / ".claude" / "settings.local.json"
            )
            local_settings.parent.mkdir()
            local_settings.write_text(
                '{"permissions":{"allow":[]}}\n', encoding="utf-8"
            )
            (candidate / "AGENTS.md").write_text(
                "host-only instructions\n", encoding="utf-8"
            )
            (candidate / "pyproject.toml").write_text(
                "[project]\nname='host-local'\n", encoding="utf-8"
            )
            (candidate / "uv.lock").write_text(
                "version = 1\n", encoding="utf-8"
            )
            before, before_count = candidate_identity.candidate_digest(
                candidate
            )
            local_settings.write_text("{}\n", encoding="utf-8")
            (candidate / "AGENTS.md").write_text(
                "changed host-only instructions\n", encoding="utf-8"
            )
            (candidate / "pyproject.toml").write_text(
                "[project]\nname='changed'\n", encoding="utf-8"
            )
            (candidate / "uv.lock").write_text(
                "version = 2\n", encoding="utf-8"
            )
            (candidate / ".venv").mkdir()
            (candidate / ".venv" / "pyvenv.cfg").write_text(
                "home = host-local\n", encoding="utf-8"
            )
            after, after_count = candidate_identity.candidate_digest(
                candidate
            )
            self.assertEqual((before, before_count), (after, after_count))

            nested = candidate / "scripts" / "pyproject.toml"
            nested.write_text("shipped\n", encoding="utf-8")
            nested_digest, nested_count = (
                candidate_identity.candidate_digest(candidate)
            )
            self.assertNotEqual(after, nested_digest)
            self.assertEqual(nested_count, after_count + 1)

            nested_agents = candidate / "scripts" / "AGENTS.md"
            nested_agents.write_text(
                "shipped nested instructions\n", encoding="utf-8"
            )
            nested_agents_digest, nested_agents_count = (
                candidate_identity.candidate_digest(candidate)
            )
            self.assertNotEqual(nested_digest, nested_agents_digest)
            self.assertEqual(nested_agents_count, nested_count + 1)

            unexpected_venv = candidate / ".venv-other"
            unexpected_venv.mkdir()
            with self.assertRaisesRegex(
                candidate_identity.CandidateIdentityError,
                "outside canonical allowlist",
            ):
                candidate_identity.candidate_digest(candidate)
            unexpected_venv.rmdir()

            (candidate / ".claude" / "settings.json").write_text(
                "{}\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                candidate_identity.CandidateIdentityError,
                "outside canonical allowlist",
            ):
                candidate_identity.candidate_digest(candidate)

    def test_release_tools_import_without_loading_controller_runtime(
        self,
    ) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        environment = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for script in (
            "run_bundled_validators.py",
            "windows_native_validation.py",
        ):
            with self.subTest(script=script):
                module = f"scripts.{Path(script).stem}"
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        module,
                        "--help",
                    ],
                    cwd=plugin_root,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    completed.returncode, 0, completed.stderr
                )
                self.assertIn(b"usage:", completed.stdout.lower())

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

    def test_windows_mcp_profile_is_bound_to_native_runner(self) -> None:
        candidate_root = Path(__file__).resolve().parents[1]
        responses = (
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-initialize",
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {
                        "name": "dev-flow-orchestrator",
                        "version": "1.0.0",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-tools",
                "result": {
                    "tools": [
                        {"name": name}
                        for name in windows_native_validation.MCP_EXPECTED_TOOLS
                    ]
                },
            },
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-shutdown",
                "result": None,
            },
        )
        completed = subprocess.CompletedProcess(
            ["cmd.exe"],
            0,
            stdout=b"".join(
                windows_native_validation._stable_json_bytes(response)
                for response in responses
            ),
            stderr=b"",
        )
        with mock.patch.object(
            windows_native_validation,
            "_run",
            return_value=completed,
        ) as run:
            check = windows_native_validation._check_windows_mcp_launcher(
                candidate_root
            )
        self.assertEqual(check["status"], "passed")
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[0:3], ["cmd.exe", "/d", "/c"])
        self.assertTrue(arguments[3].endswith("dev_flow_mcp_launcher.cmd"))
        self.assertEqual(run.call_args.kwargs["cwd"], candidate_root)
        probe = [
            json.loads(line)
            for line in run.call_args.kwargs["stdin"].splitlines()
        ]
        self.assertEqual(
            [message["method"] for message in probe],
            [
                "initialize",
                "notifications/initialized",
                "tools/list",
                "shutdown",
                "exit",
            ],
        )
        self.assertEqual(
            check["tool_names"],
            list(windows_native_validation.MCP_EXPECTED_TOOLS),
        )

    def test_mcp_probe_rejects_unbounded_or_changed_tool_surface(
        self,
    ) -> None:
        responses = (
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-initialize",
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "dev-flow-orchestrator"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-tools",
                "result": {
                    "tools": [
                        *[
                            {"name": name}
                            for name in windows_native_validation.MCP_EXPECTED_TOOLS
                        ],
                        {"name": "unexpected-tool"},
                    ]
                },
            },
            {
                "jsonrpc": "2.0",
                "id": "dev-flow-native-shutdown",
                "result": None,
            },
        )
        completed = subprocess.CompletedProcess(
            ["cmd.exe"],
            0,
            stdout=b"".join(
                windows_native_validation._stable_json_bytes(response)
                for response in responses
            ),
            stderr=b"",
        )
        with self.assertRaisesRegex(
            windows_native_validation.NativeValidationError,
            "bounded count",
        ):
            windows_native_validation._validate_mcp_probe(
                completed,
                label="portable test",
            )

    def test_windows_compact_hook_lifecycle_contract_is_portable(
        self,
    ) -> None:
        candidate_root = Path(__file__).resolve().parents[1]
        payloads = windows_native_validation._compact_hook_payloads(
            Path("C:/native fixture"),
            "portable-session",
        )
        self.assertEqual(
            [event for event, _ in payloads],
            ["PreCompact", "PostCompact", "SessionStart"],
        )
        self.assertEqual(payloads[-1][1]["source"], "compact")
        for event, _ in payloads:
            self.assertEqual(
                windows_native_validation._packaged_windows_hook_command(
                    candidate_root,
                    event,
                ),
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    '"%PLUGIN_ROOT%\\hooks\\dev_flow_hook.cmd"',
                ],
            )
        session_start = windows_native_validation._stable_json_bytes(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": json.dumps(
                        {
                            "contract": "dev-flow-hook-checkpoint/v1",
                            "task_id": "native-hook-compact",
                            "revision": 3,
                            "controller": "cli:python controller",
                        },
                        separators=(",", ":"),
                    ),
                }
            }
        )
        observed = (
            windows_native_validation._validate_compact_hook_outputs(
                pre_compact=b"{}\n",
                post_compact=b"",
                session_start=session_start,
                expected_task_id="native-hook-compact",
            )
        )
        self.assertEqual(observed["post_compact_shape"], "empty")
        with self.assertRaisesRegex(
            windows_native_validation.NativeValidationError,
            "unsupported hook-specific",
        ):
            windows_native_validation._validate_compact_hook_outputs(
                pre_compact=b"{}\n",
                post_compact=windows_native_validation._stable_json_bytes(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostCompact",
                            "additionalContext": "unsupported",
                        }
                    }
                ),
                session_start=session_start,
                expected_task_id="native-hook-compact",
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
            task_dir = (
                root
                / "controller-state"
                / "tasks"
                / "native-managed-owner"
            )
            state = json.loads(
                (task_dir / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["schema_version"], 2)
            self.assertNotIn("orchestration", state)
            event_types = {
                json.loads(line)["type"]
                for line in (task_dir / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            }
            self.assertNotIn(
                "manager_capability_authorized", event_types
            )
            self.assertNotIn(
                "manager_capability_request_consumed", event_types
            )

    def test_manager_secret_pipe_is_inherited_without_text_transport(
        self,
    ) -> None:
        read_descriptor, write_descriptor = os.pipe()
        secret = bytearray(b"n" * 32)
        try:
            windows_native_validation._publish_manager_secret(
                write_descriptor,
                secret,
            )
            os.close(write_descriptor)
            write_descriptor = -1
            child = (
                "import hashlib,os,struct,sys;"
                "payload=os.fdopen(int(sys.argv[1]),'rb').read();"
                "size=struct.unpack('>I',payload[:4])[0];"
                "assert size==len(payload[4:]);"
                "sys.stdout.write(hashlib.sha256(payload[4:]).hexdigest())"
            )
            completed = windows_native_validation._run(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(read_descriptor),
                ],
                inherited_fds=(read_descriptor,),
            )
        finally:
            windows_native_validation._close_descriptor(read_descriptor)
            if write_descriptor >= 0:
                windows_native_validation._close_descriptor(
                    write_descriptor
                )
            for index in range(len(secret)):
                secret[index] = 0
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.decode("ascii"),
            hashlib.sha256(b"n" * 32).hexdigest(),
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
