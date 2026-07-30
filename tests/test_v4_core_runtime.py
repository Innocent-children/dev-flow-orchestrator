from __future__ import annotations

import concurrent.futures
import copy
import errno
import json
import os
import stat
import subprocess
import sys
from unittest import mock

from tests.support import V4TestCase, load_controller


class V4CoreRuntimeTests(V4TestCase):
    def _assert_created(self, result, workflow_id: str) -> None:
        task = result["task"]
        self.assertEqual(task["schema_version"], 4)
        self.assertEqual(task["workflow_ref"]["id"], workflow_id)
        self.assertEqual(task["workflow_ref"]["version"], 4)
        self.assertEqual(result["revision"], 1)

    def _exercise_current_transition(
        self, task_id: str, strategy: str, workflow_id: str
    ) -> None:
        self.environment["DEV_FLOW_ACTOR"] = "执行者 空格"
        created = self.start(task_id, strategy)
        self._assert_created(created, workflow_id)

        namespace = load_controller()
        task_dir = namespace["_task_dir"](task_id, self.data_dir)
        with namespace["_task_lock"](task_dir):
            current = namespace["_finish_loaded_state"](
                task_dir / "state.json",
                namespace["_read_task_state_structural_snapshot"](
                    task_dir / "state.json"
                ),
            )
            record = {
                "blocked": {
                    "phase": "manual",
                    "from_status": "INTAKE",
                    "reason": "focused V4 transition",
                    "details": [],
                    "at": current["updated_at"],
                }
            }
            evaluation = namespace["evaluate_v4_command_movement"](
                current,
                target="BLOCKED",
                event_type="state_transitioned",
                action_id="transition",
                action_parameters={
                    "from": "INTAKE",
                    "to": "BLOCKED",
                    "note": "focused V4 transition",
                },
                state_records=record,
                preview=True,
            )
            self.assertEqual(evaluation.source, "INTAKE")
            self.assertEqual(evaluation.target, "BLOCKED")
            self.assertEqual(
                [identifier for identifier, _result in evaluation.guard_results],
                ["guard.note-required/v1"],
            )
            self.assertIn(
                "registered-reducer-applied",
                {fact.fact_type for fact in evaluation.audit_facts},
            )
            self.assertEqual(
                set(evaluation.changed_paths),
                {"/blocked", "/node_instances", "/status"},
            )
            candidate = copy.deepcopy(
                namespace["_workflow_transition_public"](
                    evaluation.candidate_state
                )
            )
            with self.assertRaises(namespace["FlowError"]) as raised:
                namespace["_commit_state"](
                    current,
                    candidate,
                    task_dir,
                    "state_transitioned",
                )
            self.assertEqual(
                raised.exception.code, "V4_ENGINE_COMMIT_PROOF_REQUIRED"
            )

        authorization, secret = self.authorize_manager(task_id, 1)
        self.assertEqual(authorization["revision"], 2)
        preview = self.controller(
            "transition",
            task_id,
            "--expected-revision",
            "2",
            "--to",
            "BLOCKED",
            "--note",
            "focused V4 transition",
            "--preview",
        )
        request = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": authorization["capability"]["capability_id"],
            "task_id": task_id,
            "manager_session_id": "focused-manager",
            "action_id": "task.transition",
            "expected_revision": 2,
            "request_nonce": "5" * 64,
        }
        completed = self.manager_controller_process(
            request,
            secret,
            "transition",
            task_id,
            "--expected-revision",
            "2",
            "--to",
            "BLOCKED",
            "--note",
            "focused V4 transition",
            "--confirm-intent",
            preview["preview"]["intent_id"],
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )
        applied = json.loads(completed.stdout)
        self.assertTrue(applied["transition_applied"])
        self.assertEqual(applied["revision"], 3)
        self.assertEqual(applied["status"], "BLOCKED")

        projection = self.controller("show", task_id, "--next")
        self.assertEqual(projection["profile"], "agent-v1")
        self.assertEqual(projection["revision"], 3)
        self.assertEqual(projection["status"], "BLOCKED")
        self.assertEqual(projection["next"]["contract"], "agent-v1")
        self.assertEqual(projection["next"]["task_id"], task_id)

        events = [
            json.loads(line)
            for line in (task_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        self.assertTrue(
            all(event["actor"] == "执行者 空格" for event in events)
        )
        audit_types = {
            event["payload"].get("fact_type")
            for event in events
            if event["type"] == "workflow_audit_fact"
        }
        self.assertIn("registered-reducer-applied", audit_types)
        self.assertIn("node-lifecycle-advanced", audit_types)

    def test_lite_creation_and_current_transition(self) -> None:
        self._exercise_current_transition("lite-v4", "in-place", "lite")

    def test_full_creation_and_current_transition(self) -> None:
        self._exercise_current_transition("full-v4", "worktree", "full")

    def test_concurrent_current_writers_serialize_on_revision_cas(self) -> None:
        self.start("writer-race", "in-place")
        authorization, secret = self.authorize_manager("writer-race", 1)
        preview = self.controller(
            "transition",
            "writer-race",
            "--expected-revision",
            "2",
            "--to",
            "BLOCKED",
            "--note",
            "serialized writer",
            "--preview",
        )

        def invoke(nonce: str) -> subprocess.CompletedProcess[str]:
            return self.manager_controller_process(
                {
                    "schema": "dev-flow-manager-capability-request/v1",
                    "capability_id": authorization["capability"][
                        "capability_id"
                    ],
                    "task_id": "writer-race",
                    "manager_session_id": "focused-manager",
                    "action_id": "task.transition",
                    "expected_revision": 2,
                    "request_nonce": nonce * 64,
                },
                secret,
                "transition",
                "writer-race",
                "--expected-revision",
                "2",
                "--to",
                "BLOCKED",
                "--note",
                "serialized writer",
                "--confirm-intent",
                preview["preview"]["intent_id"],
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            completed = list(pool.map(invoke, ("6", "7")))
        self.assertEqual(
            sorted(item.returncode for item in completed), [0, 3]
        )
        failure = json.loads(
            next(item.stdout for item in completed if item.returncode)
        )
        self.assertEqual(failure["error"]["code"], "REVISION_CONFLICT")
        state = self.controller("show", "writer-race", "--compact")
        self.assertEqual(state["revision"], 3)

    def test_macos_lock_modes_protocol_and_process_containment(self) -> None:
        self.start("native-safety", "in-place")
        namespace = load_controller()
        task_dir = namespace["_task_dir"]("native-safety", self.data_dir)

        self.assertEqual(stat.S_IMODE(self.data_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(task_dir.stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE((task_dir / "state.json").stat().st_mode), 0o600
        )

        lock_path = self.temp / "native lock"
        handle = mock.Mock()
        handle.fileno.return_value = 17
        with mock.patch.object(
            namespace["fcntl"],
            "lockf",
            side_effect=OSError(errno.EIO, "acquire failed"),
        ):
            with self.assertRaises(namespace["FlowError"]) as raised:
                namespace["_acquire_exclusive"](handle, lock_path)
        self.assertEqual(raised.exception.code, "LOCK_ACQUIRE_FAILED")

        with mock.patch.object(
            namespace["fcntl"],
            "lockf",
            side_effect=[None, OSError(errno.EIO, "release failed")],
        ):
            namespace["_acquire_exclusive"](handle, lock_path)
            with self.assertRaises(namespace["FlowError"]) as raised:
                namespace["_release_exclusive"](handle, lock_path)
        self.assertEqual(raised.exception.code, "LOCK_RELEASE_FAILED")

        decoded = namespace["_run"](
            [
                sys.executable,
                "-c",
                "import sys;sys.stdout.buffer.write(b'\\xff\\r\\n')",
            ]
        )
        self.assertEqual(decoded.stdout, "\\xff\r\n")

        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import signal,time;"
                    "signal.signal(signal.SIGTERM,lambda *_:None);"
                    "print('ready',flush=True);"
                    "time.sleep(30)"
                ),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            text=False,
        )
        self.assertEqual(child.stdout.readline(), b"ready\n")
        self.assertTrue(
            namespace["_terminate_and_quiesce_owned_child"](
                child, [sys.executable, "-c", "bounded"], protected_child=True
            )
        )
        child.communicate()
        self.assertIsNotNone(child.poll())

        invalid = self.controller_process(
            "start",
            "invalid task",
            "--repo",
            str(self.repo),
            "--task-id",
            "../escape",
            "--workspace-strategy",
            "in-place",
            "--change-category",
            "docs",
            "--target-path",
            "README.md",
        )
        self.assertNotEqual(invalid.returncode, 0)
        self.assertEqual(
            json.loads(invalid.stdout)["error"]["code"], "INVALID_TASK_ID"
        )
        direct_identity = namespace["_serializable_path_identity"](self.repo)
        alias_identity = namespace["_serializable_path_identity"](
            self.repo.parent / "." / self.repo.name
        )
        self.assertEqual(direct_identity, alias_identity)

    def test_real_git_evidence_ignores_host_configuration(self) -> None:
        self.start("git-evidence", "in-place")
        namespace = load_controller()
        self._git("branch", "main")
        self._git("remote", "add", "origin", str(self.repo))
        self._git(
            "fetch",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        )
        preflight = namespace["_preflight_repo"](
            {
                "id": "repo",
                "path": str(self.repo),
                "protected_branches": ["main"],
            },
            "origin",
            "main",
        )
        self.assertTrue(preflight["ready"])
        self.assertTrue(preflight["evidence_complete"])
        baseline_ref, baseline_sha = namespace["_baseline_ref"](
            self.repo, "origin", "main"
        )
        self.assertEqual(baseline_ref, "refs/remotes/origin/main")

        analysis = self.temp / "analysis 工作树"
        self._git(
            "worktree",
            "add",
            "--detach",
            str(analysis),
            baseline_ref,
        )
        self.assertTrue(namespace["_is_linked_worktree"](analysis))
        analysis_fingerprint = namespace["_fingerprint_repo"](analysis)
        self.assertEqual(
            analysis_fingerprint["head_sha"], baseline_sha
        )

        hook_dir = self.temp / "host hooks"
        hook_dir.mkdir()
        hook = hook_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        hook.chmod(0o755)
        hostile = self.temp / "hostile.gitconfig"
        hostile.write_text(
            f"[core]\n\thooksPath = {hook_dir}\n",
            encoding="utf-8",
        )
        task_dir = namespace["_task_dir"]("git-evidence", self.data_dir)
        with mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG_GLOBAL": str(hostile),
                "GIT_CONFIG_NOSYSTEM": "0",
            },
        ):
            with namespace["_task_lock"](task_dir):
                committed = namespace["_run"](
                    [
                        "git",
                        "-C",
                        str(self.repo),
                        "commit",
                        "--allow-empty",
                        "-m",
                        "isolated config",
                    ],
                    mutation=True,
                )
        self.assertEqual(committed.returncode, 0)

        before = namespace["_fingerprint_repo"](self.repo)
        (self.repo / "README.md").write_text(
            "V4 changed\n", encoding="utf-8"
        )
        after = namespace["_fingerprint_repo"](self.repo)
        self.assertNotEqual(before["sha256"], after["sha256"])
        head_sha, sections, files = namespace[
            "_v4_review_capture_sections"
        ](self.repo, baseline_sha)
        self.assertNotEqual(head_sha, baseline_sha)
        self.assertTrue(sections["unstaged"])
        self.assertEqual(files["unstaged"], ["M\tREADME.md"])

        test_record = {
            "evidence_contract_version": namespace[
                "EVIDENCE_CONTRACT_VERSION"
            ],
            "test_id": "focused-test",
            "name": "v4-core-runtime",
            "command": "python3 -m unittest tests.test_v4_core_runtime",
            "test_identity": namespace["_test_identity"](
                "v4-core-runtime",
                "python3 -m unittest tests.test_v4_core_runtime",
            ),
            "exit_code": 0,
            "passed": True,
            "recorded_at": "2026-07-30T00:00:00.000Z",
            "repository_ids": ["repo"],
            "fingerprints": {"repo": after},
        }
        receipt = namespace["_test_receipt"](test_record)
        self.assertTrue(receipt["passed"])
        self.assertEqual(
            receipt["fingerprint_sha256"]["repo"], after["sha256"]
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
