from __future__ import annotations

import contextlib
import errno
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_flow.py"
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_cross_platform_safety", SCRIPT
)
assert SPEC and SPEC.loader
dev_flow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dev_flow
SPEC.loader.exec_module(dev_flow)


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


class CrossPlatformSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        # macOS commonly exposes /var as an alias of /private/var.  Use the
        # canonical spelling so the lock-held directory and commit directory
        # exercise one identity rather than two textual aliases.
        self.root = Path(self.temporary.name).resolve()
        self.task_dir = self.root / "state" / "tasks" / "safety-task"
        dev_flow._ensure_private_dir(self.task_dir)
        self.state = {
            "schema_version": dev_flow.SCHEMA_VERSION,
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "task_id": "safety-task",
            "status": "INTAKE",
            "revision": 1,
            "repositories": [],
            "artifacts": [],
            "approvals": {},
            "tests": [],
            "review_snapshots": [],
            "mutation_recoveries": [],
        }
        dev_flow._atomic_write_json(
            self.task_dir / "state.json", self.state
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_repo(self, name: str) -> Path:
        repository = self.root / name
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(repository)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repository, "config", "user.name", "Safety Test")
        git(
            repository,
            "config",
            "user.email",
            "safety@example.invalid",
        )
        (repository / "tracked.txt").write_text(
            "initial\n", encoding="utf-8"
        )
        git(repository, "add", "tracked.txt")
        git(repository, "commit", "-q", "-m", "initial")
        return repository

    def run_controller(self, *arguments: str) -> dict:
        isolated_home = self.root / "isolated-controller-home"
        isolated_home.mkdir(exist_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                *arguments,
                "--data-dir",
                str(self.root / "state"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            encoding="utf-8",
            timeout=60,
            env={
                **os.environ,
                "HOME": str(isolated_home),
                "USERPROFILE": str(isolated_home),
                "XDG_CONFIG_HOME": str(isolated_home / "xdg"),
                "GIT_TERMINAL_PROMPT": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        return json.loads(lines[0])

    def test_baseline_fetch_disables_reference_transaction_hook(self) -> None:
        repository = self.make_repo("baseline-hook-source")
        remote = self.root / "baseline-hook-remote.git"
        subprocess.run(
            ["git", "clone", "-q", "--bare", str(repository), str(remote)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(repository, "remote", "add", "origin", str(remote))
        git(repository, "fetch", "-q", "origin")
        git(repository, "remote", "set-head", "origin", "main")
        old_remote_sha = git(
            repository, "rev-parse", "refs/remotes/origin/main"
        )

        started = self.run_controller(
            "start",
            "--task-id",
            "baseline-hook-fetch",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "pin an explicitly fetched baseline without executing hooks",
            "--repo",
            str(repository),
        )["task"]
        preview = self.run_controller(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--preview",
        )
        self.run_controller(
            "preflight",
            started["task_id"],
            "--expected-revision",
            str(started["revision"]),
            "--confirm-preview",
            preview["transition_preview"]["token"],
        )
        current = dev_flow.load_state(
            started["task_id"], self.root / "state"
        )
        self.run_controller(
            "approve",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--gate",
            "baseline-fetch",
            "--note",
            "explicit baseline fetch approved",
            "--allow-fetch",
        )

        publisher = self.root / "baseline-hook-publisher"
        subprocess.run(
            ["git", "clone", "-q", str(remote), str(publisher)],
            check=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        git(publisher, "config", "user.name", "Safety Test")
        git(
            publisher,
            "config",
            "user.email",
            "safety@example.invalid",
        )
        (publisher / "tracked.txt").write_text(
            "advanced remote baseline\n", encoding="utf-8"
        )
        git(publisher, "add", "tracked.txt")
        git(publisher, "commit", "-q", "-m", "advance remote baseline")
        new_remote_sha = git(publisher, "rev-parse", "HEAD")
        git(publisher, "push", "-q", "origin", "main")

        hook = repository / ".git" / "hooks" / "reference-transaction"
        hook.write_bytes(
            b"this hook is deliberately invalid and must never execute\n"
        )
        hook.chmod(0o755)
        fetch_refspec = "+refs/heads/main:refs/remotes/origin/main"
        unisolated_fetch = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "--",
                "origin",
                fetch_refspec,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            env={
                **os.environ,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
        self.assertNotEqual(unisolated_fetch.returncode, 0)
        self.assertEqual(
            git(repository, "rev-parse", "refs/remotes/origin/main"),
            old_remote_sha,
        )

        current = dev_flow.load_state(
            started["task_id"], self.root / "state"
        )
        response = self.run_controller(
            "baseline",
            current["task_id"],
            "--expected-revision",
            str(current["revision"]),
            "--fetch",
        )
        baseline = response["repositories"][0]["baseline"]
        self.assertEqual(baseline["base_sha"], new_remote_sha)
        self.assertEqual(baseline["fetch_refspec"], fetch_refspec)
        self.assertEqual(
            git(repository, "rev-parse", "refs/remotes/origin/main"),
            new_remote_sha,
        )

    def test_pre_spawn_intent_failure_never_calls_popen(self) -> None:
        denied = dev_flow.FlowError(
            "ATOMIC_WRITE_FAILED", "injected intent write failure"
        )
        with dev_flow._task_lock(self.task_dir), mock.patch.object(
            dev_flow,
            "_atomic_write_json",
            side_effect=denied,
        ), mock.patch.object(
            dev_flow.subprocess, "Popen"
        ) as popen:
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._run(
                    [sys.executable, "-c", "pass"],
                    mutation=True,
                )
        self.assertEqual(
            captured.exception.code, "ATOMIC_WRITE_FAILED"
        )
        popen.assert_not_called()

    def test_mutation_intent_survives_child_until_state_commit(self) -> None:
        marker = dev_flow._quarantine_path(self.task_dir)
        with dev_flow._task_lock(self.task_dir):
            result = dev_flow._run(
                [sys.executable, "-c", "pass"],
                mutation=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(marker.is_file())
            evidence = json.loads(
                marker.read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["phase"], "child_quiescent")
            self.assertEqual(
                evidence["state_revision"], self.state["revision"]
            )

            updated = dict(self.state)
            updated["status"] = "PREFLIGHTED"
            dev_flow._commit_state(
                self.state,
                updated,
                self.task_dir,
                "fixture_committed",
            )
            self.assertFalse(marker.exists())
            self.assertEqual(updated["revision"], 2)

    def test_later_unstarted_child_preserves_prior_mutation_intent(self) -> None:
        marker = dev_flow._quarantine_path(self.task_dir)
        first_command = [sys.executable, "-c", "pass"]
        second_command = [sys.executable, "-c", "raise SystemExit(9)"]
        with dev_flow._task_lock(self.task_dir):
            self.assertEqual(
                dev_flow._run(first_command, mutation=True).returncode,
                0,
            )
            with mock.patch.object(
                dev_flow.subprocess,
                "Popen",
                side_effect=OSError(errno.ENOENT, "injected spawn failure"),
            ):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._run(second_command, mutation=True)
            self.assertEqual(captured.exception.code, "COMMAND_FAILED")
            evidence = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(len(evidence["operations"]), 1)
            self.assertEqual(evidence["command"], first_command)
            self.assertEqual(evidence["phase"], "child_quiescent")
            self.assertIn(
                str(marker),
                dev_flow._ACTIVE_MUTATION_INTENTS.get(),
            )

    def test_read_only_protected_child_does_not_require_job_ownership(
        self,
    ) -> None:
        events: list[dict[str, object]] = []

        class Process:
            pid = 8181
            returncode = 0
            _handle = 0x1_0000_8181

            def communicate(self, input=None):
                return (b"out", b"")

        held_token = dev_flow._HELD_LOCK_DIRECTORIES.set(
            (str(self.task_dir),)
        )
        try:
            with mock.patch.object(
                dev_flow.os, "name", "nt"
            ), mock.patch.object(
                dev_flow.subprocess, "Popen", return_value=Process()
            ), mock.patch.object(
                dev_flow,
                "_windows_kill_on_close_job",
                side_effect=lambda *_, **kwargs: events.append(kwargs)
                or None,
            ), mock.patch.object(
                dev_flow, "_quiesce_windows_job"
            ) as quiesce, mock.patch.object(
                dev_flow, "_close_windows_job"
            ):
                result = dev_flow._run(["git.exe", "ls-files"])
        finally:
            dev_flow._HELD_LOCK_DIRECTORIES.reset(held_token)

        self.assertEqual(result.stdout, "out")
        self.assertEqual(events, [{"require_ownership": False}])
        # No job exists, so there is nothing to prove quiescent.
        quiesce.assert_not_called()

    @unittest.skipUnless(
        os.name == "nt", "requires native Windows job objects"
    )
    def test_exited_read_only_child_survives_job_assignment_race(
        self,
    ) -> None:
        def exited_child() -> subprocess.Popen[bytes]:
            process = subprocess.Popen(
                [sys.executable, "-c", "pass"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                ),
            )
            process.communicate(timeout=20)
            return process

        # A read-only child may exit before AssignProcessToJobObject runs;
        # Windows then refuses the assignment with ERROR_ACCESS_DENIED, which
        # must not turn a read-only command into an ownership failure.
        self.assertIsNone(
            dev_flow._windows_kill_on_close_job(
                exited_child(),
                ["git", "ls-files"],
                require_ownership=False,
            )
        )

        # A gated mutation is blocked on its gate byte and must stay
        # fail-closed, so the same refusal remains an ownership failure.
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._windows_kill_on_close_job(
                exited_child(), ["git", "commit"]
            )
        self.assertEqual(
            captured.exception.code, "PROCESS_OWNERSHIP_FAILED"
        )
        self.assertEqual(captured.exception.details["winerror"], 5)

        live = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read(1)"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ),
        )
        try:
            job = dev_flow._windows_kill_on_close_job(
                live, ["git", "ls-files"], require_ownership=False
            )
            self.assertTrue(job)
            self.assertEqual(
                dev_flow._windows_job_active_processes(job), 1
            )
        finally:
            live.communicate(input=b"G", timeout=20)
            dev_flow._close_windows_job(job)

    def test_mutation_gate_orders_durable_intent_before_release(self) -> None:
        code = dev_flow._MUTATION_GATE_CODE
        self.assertLess(
            code.index("gate = sys.stdin.buffer.read(1)"),
            code.index("result = subprocess.run("),
        )
        self.assertIn('if gate != b"G"', code)
        gate_command = dev_flow._mutation_gate_command(
            ["git.exe", "status"]
        )
        self.assertEqual(gate_command[:3], [sys.executable, "-I", "-S"])

        events: list[str] = []

        class Process:
            pid = 7878
            returncode = 0
            _handle = 0x1_0000_7878

            def communicate(self, input=None):
                events.append(f"gate:{input!r}")
                return (
                    dev_flow._MUTATION_GATE_ENVELOPE
                    + (
                        b'{"returncode":0,"status":"completed",'
                        b'"stderr":"","stdout":"","version":1}'
                    ),
                    b"",
                )

        process = Process()
        intent = self.task_dir / "mutation-quarantine.json"

        def begin(_command):
            events.append("intent:spawn_pending")
            return intent

        def update(
            _path,
            _process,
            _command,
            *,
            phase,
            cause=None,
            target_release_authorized=None,
        ):
            events.append(
                f"intent:{phase}:{target_release_authorized!r}"
            )

        held_token = dev_flow._HELD_LOCK_DIRECTORIES.set(
            (str(self.task_dir),)
        )
        try:
            with mock.patch.object(
                dev_flow.os, "name", "nt"
            ), mock.patch.object(
                dev_flow.subprocess,
                "Popen",
                return_value=process,
            ) as popen, mock.patch.object(
                dev_flow,
                "_begin_mutation_intent",
                side_effect=begin,
            ), mock.patch.object(
                dev_flow,
                "_update_mutation_intent",
                side_effect=update,
            ), mock.patch.object(
                dev_flow,
                "_windows_kill_on_close_job",
                side_effect=lambda *_, **kwargs: events.append(
                    f"job:assigned:{kwargs['require_ownership']}"
                )
                or 999,
            ), mock.patch.object(
                dev_flow,
                "_quiesce_windows_job",
                side_effect=lambda *_: events.append("job:zero"),
            ), mock.patch.object(
                dev_flow, "_close_windows_job"
            ):
                result = dev_flow._run(
                    ["git.exe", "fetch"],
                    mutation=True,
                )
        finally:
            dev_flow._HELD_LOCK_DIRECTORIES.reset(held_token)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            events[:5],
            [
                "intent:spawn_pending",
                "job:assigned:True",
                "intent:child_owned:None",
                "intent:target_release_authorized:True",
                "gate:b'G'",
            ],
        )
        self.assertEqual(
            events[-2:],
            ["job:zero", "intent:child_quiescent:None"],
        )
        launched = popen.call_args.args[0]
        self.assertEqual(launched[:3], [sys.executable, "-I", "-S"])
        self.assertNotEqual(launched, ["git.exe", "fetch"])

        with mock.patch.object(
            dev_flow.os, "name", "nt"
        ), mock.patch.object(
            dev_flow,
            "_windows_job_active_processes",
            side_effect=[1, 0],
        ) as active, mock.patch.object(
            dev_flow, "_terminate_windows_job"
        ) as terminate:
            dev_flow._quiesce_windows_job(
                999, process, ["git.exe", "fetch"]
            )
        terminate.assert_called_once_with(999)
        self.assertEqual(active.call_count, 2)

    def test_review_fingerprint_and_section_drift_fail(self) -> None:
        repository = self.make_repo("review-source")
        base = git(repository, "rev-parse", "HEAD")
        record = {
            "id": "review-source",
            "path": str(repository),
            "baseline": {
                "evidence_contract_version": (
                    dev_flow.EVIDENCE_CONTRACT_VERSION
                ),
                "base_sha": base,
            },
            "workspace": None,
        }
        fingerprint = dev_flow._fingerprint_repo(repository)
        drifted = {**fingerprint, "sha256": "0" * 64}
        with mock.patch.object(
            dev_flow,
            "_fingerprint_repo",
            side_effect=[fingerprint, drifted, fingerprint],
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._write_review_repo(
                    self.root / "fingerprint-drift", record
                )
        self.assertEqual(
            captured.exception.code, "REVIEW_SNAPSHOT_CHANGED"
        )

        original_diff = dev_flow._git_diff
        committed_binary_calls = 0

        def drifting_diff(repo, *arguments, **options):
            nonlocal committed_binary_calls
            value = original_diff(repo, *arguments, **options)
            if (
                options.get("text") is False
                and any("...HEAD" in item for item in arguments)
            ):
                committed_binary_calls += 1
                if committed_binary_calls == 2:
                    return value + b"injected-section-drift"
            return value

        with mock.patch.object(
            dev_flow,
            "_fingerprint_repo",
            return_value=fingerprint,
        ), mock.patch.object(
            dev_flow, "_git_diff", side_effect=drifting_diff
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._write_review_repo(
                    self.root / "section-drift", record
                )
        self.assertEqual(
            captured.exception.code, "REVIEW_SNAPSHOT_CHANGED"
        )

    def test_review_command_removes_partial_snapshot_on_failure(self) -> None:
        repository = {"id": "repo", "path": str(self.root)}
        current = {
            **self.state,
            "status": "VERIFYING",
            "repositories": [repository],
            "route": {"value": "direct"},
        }

        @contextlib.contextmanager
        def locked(*_args, **_kwargs):
            yield self.task_dir, current

        fingerprint = {"sha256": "a" * 64}

        def fail_after_writing(
            snapshot_root: Path,
            _repository,
            *,
            initial_fingerprint=None,
        ):
            self.assertIs(initial_fingerprint, fingerprint)
            (snapshot_root / "partial").mkdir(parents=True)
            (snapshot_root / "partial" / "section.patch").write_bytes(
                b"partial"
            )
            raise dev_flow.FlowError(
                "REVIEW_SNAPSHOT_CHANGED", "injected drift"
            )

        arguments = types.SimpleNamespace(
            task_id="safety-task",
            task_option=None,
            data_dir=str(self.root / "state"),
            expected_revision=1,
            repo=None,
        )
        with mock.patch.object(
            dev_flow, "_locked_state", side_effect=locked
        ), mock.patch.object(
            dev_flow, "_assert_flow"
        ), mock.patch.object(
            dev_flow, "_assert_status"
        ), mock.patch.object(
            dev_flow, "_require_current_workspace_indexes"
        ), mock.patch.object(
            dev_flow, "_require_workspace_ready"
        ), mock.patch.object(
            dev_flow, "_require_current_plan_gate"
        ), mock.patch.object(
            dev_flow, "_fingerprint_repo", return_value=fingerprint
        ), mock.patch.object(
            dev_flow,
            "_latest_passing_test_is_current",
            return_value=(True, None),
        ), mock.patch.object(
            dev_flow,
            "_repo_by_selector",
            return_value=[repository],
        ), mock.patch.object(
            dev_flow,
            "_write_review_repo",
            side_effect=fail_after_writing,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow.command_review_snapshot(arguments)
        self.assertEqual(
            captured.exception.code, "REVIEW_SNAPSHOT_CHANGED"
        )
        reviews = self.task_dir / "reviews"
        self.assertFalse(reviews.exists() and any(reviews.iterdir()))

    def test_legacy_registry_blocks_use_but_current_plan_regenerates(self) -> None:
        data_root = self.root / "registry"
        data_root.mkdir()
        source = self.root / "source"
        source.mkdir()
        workspace = self.root / "workspace"
        legacy_claim = {
            "task_id": "legacy-task",
            "repository_id": "repo",
            "source_path": str(source),
            "path": str(workspace),
            "branch": "codex/legacy",
            "workspace_generation": 0,
            "plan_sha256": "a" * 64,
        }
        registry_path = data_root / "workspace-registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": dev_flow.SCHEMA_VERSION,
                    "claims": [legacy_claim],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow._load_workspace_registry(data_root)
        self.assertEqual(
            captured.exception.code, "EVIDENCE_REGENERATION_REQUIRED"
        )
        state = {
            "task_id": "legacy-task",
            "workspace": {"generation": 0},
            "repositories": [],
        }
        repo = {"id": "repo"}
        self.assertFalse(
            dev_flow._has_exact_workspace_claim(
                data_root,
                state,
                repo,
                workspace,
                "codex/legacy",
            )
        )
        plan = {
            "repository_id": "repo",
            "source_path": str(source),
            "path": str(workspace),
            "branch": "codex/legacy",
        }
        with mock.patch.object(
            dev_flow,
            "_source_common_dir_for_claim",
            return_value=f"unavailable:{source}",
        ):
            dev_flow._claim_workspace_plan(
                data_root, state, "b" * 64, [plan]
            )
        regenerated = json.loads(
            registry_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            regenerated["evidence_contract_version"],
            dev_flow.EVIDENCE_CONTRACT_VERSION,
        )
        self.assertTrue(
            any(
                claim.get("evidence_contract_version")
                == dev_flow.EVIDENCE_CONTRACT_VERSION
                for claim in regenerated["claims"]
            )
        )
        self.assertTrue(
            dev_flow._has_exact_workspace_claim(
                data_root,
                state,
                repo,
                workspace,
                "codex/legacy",
            )
        )

    def test_metadata_version_is_namespaced_and_new_input_is_rejected(self) -> None:
        old_record = {
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "metadata": {
                "evidence_contract_version": 999,
                "nested": {
                    "evidence_contract_version": "integration-v2"
                },
            },
        }
        dev_flow._assert_supported_evidence_versions(old_record)
        self.assertEqual(
            list(dev_flow._declared_evidence_versions(old_record)),
            [dev_flow.EVIDENCE_CONTRACT_VERSION],
        )
        for value in (
            '{"evidence_contract_version":1}',
            '{"nested":{"evidence_contract_version":1}}',
        ):
            with self.subTest(value=value):
                with self.assertRaises(dev_flow.FlowError) as captured:
                    dev_flow._parse_json_object(value, "--metadata-json")
                self.assertEqual(
                    captured.exception.code, "RESERVED_METADATA_KEY"
                )

    def test_atomic_postcheck_restores_or_preserves_rollback(self) -> None:
        destination = self.root / "atomic" / "state.json"
        dev_flow._atomic_write_bytes(destination, b"old\n")
        real_permissions = dev_flow._set_private_permissions
        destination_checks = 0

        def fail_first_destination(path: Path, mode: int) -> None:
            nonlocal destination_checks
            if path == destination:
                destination_checks += 1
                if destination_checks == 1:
                    raise dev_flow.FlowError(
                        "PERMISSIONS_UNSAFE", "injected postcheck"
                    )
            real_permissions(path, mode)

        with mock.patch.object(
            dev_flow,
            "_set_private_permissions",
            side_effect=fail_first_destination,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._atomic_write_bytes(destination, b"new\n")
        self.assertEqual(
            captured.exception.code, "ATOMIC_POSTCHECK_FAILED"
        )
        self.assertEqual(destination.read_bytes(), b"old\n")
        self.assertFalse(
            list(destination.parent.glob(".state.json.rollback-*"))
        )

        destination_checks = 0
        real_replace = dev_flow.os.replace

        def fail_rollback_restore(source, target):
            if (
                Path(source).name.startswith(".state.json.rollback-")
                and Path(target) == destination
            ):
                raise OSError(errno.EIO, "injected restore failure")
            return real_replace(source, target)

        with mock.patch.object(
            dev_flow,
            "_set_private_permissions",
            side_effect=fail_first_destination,
        ), mock.patch.object(
            dev_flow.os,
            "replace",
            side_effect=fail_rollback_restore,
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._atomic_write_bytes(destination, b"uncertain\n")
        self.assertEqual(
            captured.exception.code, "ATOMIC_RECOVERY_UNCERTAIN"
        )
        self.assertEqual(destination.read_bytes(), b"uncertain\n")
        rollback = list(
            destination.parent.glob(".state.json.rollback-*")
        )
        self.assertEqual(len(rollback), 1)
        self.assertEqual(rollback[0].read_bytes(), b"old\n")

    def test_planned_identity_is_stable_and_file_id_aliases_match(self) -> None:
        planned = self.root / "planned" / "nested" / "workspace"
        before = dev_flow._serializable_path_identity(planned)
        planned.mkdir(parents=True)
        after = dev_flow._serializable_path_identity(planned)
        self.assertTrue(dev_flow._path_identity_equal(before, after))

        first_parent = self.root / "alias-one"
        second_parent = self.root / "alias-two"
        first_parent.mkdir()
        second_parent.mkdir()
        canonical = self.root / "canonical-parent"
        stable = {
            "kind": "posix-file-id",
            "device": 77,
            "inode": 88,
            "final_path": str(canonical),
        }
        with mock.patch.object(
            dev_flow,
            "_stable_existing_identity",
            return_value=stable,
        ), mock.patch.object(
            dev_flow,
            "_probe_filesystem_case_sensitive",
            return_value=True,
        ), mock.patch.object(
            dev_flow,
            "_probe_filesystem_unicode_distinct",
            return_value=True,
        ):
            first = dev_flow._serializable_path_identity(
                first_parent / "future"
            )
            second = dev_flow._serializable_path_identity(
                second_parent / "future"
            )
        self.assertTrue(dev_flow._path_identity_equal(first, second))
        self.assertEqual(
            first["ancestor_identity"], second["ancestor_identity"]
        )

    def test_containment_uses_file_ids_across_capability_boundaries(self) -> None:
        parent = self.root / "identity-parent"
        child = parent / "case-sensitive-child"
        child.mkdir(parents=True)
        parent_stable = {
            key: value
            for key, value in dev_flow._stable_existing_identity(
                parent
            ).items()
            if key != "final_path"
        }
        child_stable = {
            key: value
            for key, value in dev_flow._stable_existing_identity(
                child
            ).items()
            if key != "final_path"
        }

        def identity(path: Path):
            resolved = Path(path).resolve()
            is_child = resolved == child
            return {
                "normalized": (
                    "X:/alias/child"
                    if is_child
                    else "//server/share/parent"
                ),
                "anchor": "X:/" if is_child else "//server/share/",
                "parts": (
                    ("alias", "child") if is_child else ("parent",)
                ),
                "case_sensitive": is_child,
                "unicode_normalization_distinct": True,
                "ancestor": str(resolved),
                "ancestor_identity": (
                    child_stable if is_child else parent_stable
                ),
                "suffix_parts": (),
            }

        with mock.patch.object(
            dev_flow,
            "_filesystem_identity",
            side_effect=identity,
        ):
            self.assertTrue(dev_flow._is_within(child, parent))
        self.assertNotEqual(parent_stable, child_stable)

    def test_normalization_only_manifest_collision_is_rejected(self) -> None:
        repository = self.root / "manifest"
        repository.mkdir()
        composed = "\u00e9.txt"
        decomposed = "e\u0301.txt"
        (repository / composed).write_bytes(b"content\n")
        object_id = b"0" * 40
        records = (
            b"100644 "
            + object_id
            + b" 0\t"
            + composed.encode("utf-8")
            + b"\0"
            + b"100644 "
            + object_id
            + b" 0\t"
            + decomposed.encode("utf-8")
            + b"\0"
        )
        profile = {
            "core_ignore_case": False,
            "filesystem": {
                "case_sensitive": True,
                "unicode_normalization_distinct": False,
            },
        }
        with mock.patch.object(
            dev_flow, "_git_evidence", return_value=records
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._tracked_worktree_manifest(
                    repository, profile
                )
        self.assertEqual(
            captured.exception.code, "CASE_COLLISION_UNSUPPORTED"
        )
        self.assertFalse(captured.exception.details["case_aliasing"])
        self.assertTrue(captured.exception.details["unicode_aliasing"])


if __name__ == "__main__":
    unittest.main()
