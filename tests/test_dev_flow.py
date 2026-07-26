from __future__ import annotations

import argparse
import contextlib
import errno
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case

SCRIPT = test_case.SCRIPT
SUPPORT = test_case.SUPPORT
dev_flow = test_case.dev_flow
git = test_case.git


class DevFlowStateTest(test_case.DevFlowTestCase):
    def test_data_dir_precedence_and_helper_lookup(self) -> None:
        explicit = self.root / "explicit"
        with mock.patch.dict(
            os.environ,
            {"DEV_FLOW_DATA_DIR": str(self.root / "env"), "PLUGIN_DATA": str(self.root / "plugin")},
        ):
            self.assertEqual(dev_flow.resolve_data_dir(explicit), explicit.resolve())
            self.assertEqual(dev_flow.resolve_data_dir(), (self.root / "env").resolve())
        with mock.patch.dict(
            os.environ,
            {"PLUGIN_DATA": str(self.root / "plugin")},
            clear=True,
        ):
            self.assertEqual(dev_flow.resolve_data_dir(), (self.root / "plugin").resolve())

        repo, _ = self.make_repo("one")
        response = self.start(repo)
        task = response["task"]
        found = dev_flow.find_active_task_for_cwd(repo, self.data)
        self.assertIsNotNone(found)
        self.assertEqual(found["task_id"], task["task_id"])
        loaded = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(loaded["revision"], 1)

    def test_data_dir_whitespace_actor_and_platform_defaults(self) -> None:
        environment = {
            "DEV_FLOW_DATA_DIR": " \t ",
            "PLUGIN_DATA": str(self.root / "plugin fallback"),
            "DEV_FLOW_ACTOR": " ",
            "USER": " ",
            "USERNAME": " windows-user ",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                dev_flow.resolve_data_dir(" \n "),
                (self.root / "plugin fallback").resolve(),
            )
            self.assertEqual(dev_flow._actor(), "windows-user")

        home = self.root / "home defaults"
        with mock.patch.object(Path, "home", return_value=home):
            with mock.patch.dict(
                os.environ,
                {
                    "DEV_FLOW_DATA_DIR": " ",
                    "PLUGIN_DATA": "\t",
                    "XDG_STATE_HOME": str(self.root / "xdg state"),
                },
                clear=True,
            ), mock.patch.object(
                dev_flow, "_platform_family", return_value="linux"
            ):
                self.assertEqual(
                    dev_flow.resolve_data_dir(),
                    (
                        self.root
                        / "xdg state"
                        / "dev-flow-orchestrator"
                    ).resolve(),
                )
            with mock.patch.dict(
                os.environ,
                {
                    "DEV_FLOW_DATA_DIR": " ",
                    "PLUGIN_DATA": " ",
                    "XDG_STATE_HOME": " ",
                },
                clear=True,
            ), mock.patch.object(
                dev_flow, "_platform_family", return_value="linux"
            ):
                self.assertEqual(
                    dev_flow.resolve_data_dir(),
                    (
                        home
                        / ".local"
                        / "state"
                        / "dev-flow-orchestrator"
                    ).resolve(),
                )
            with mock.patch.dict(
                os.environ,
                {
                    "DEV_FLOW_DATA_DIR": " ",
                    "PLUGIN_DATA": " ",
                },
                clear=True,
            ), mock.patch.object(
                dev_flow, "_platform_family", return_value="macos"
            ):
                self.assertEqual(
                    dev_flow.resolve_data_dir(),
                    (
                        home
                        / "Library"
                        / "Application Support"
                        / "dev-flow-orchestrator"
                    ).resolve(),
                )
            with mock.patch.dict(
                os.environ,
                {
                    "DEV_FLOW_DATA_DIR": " ",
                    "PLUGIN_DATA": " ",
                    "LOCALAPPDATA": str(self.root / "Local App Data"),
                },
                clear=True,
            ), mock.patch.object(
                dev_flow, "_platform_family", return_value="windows"
            ):
                self.assertEqual(
                    dev_flow.resolve_data_dir(),
                    (
                        self.root
                        / "Local App Data"
                        / "dev-flow-orchestrator"
                    ).resolve(),
                )

    def test_task_id_portable_boundaries_and_case_collision(self) -> None:
        repo, _ = self.make_repo("task-id-repository")
        for task_id in ("a", "x" * 64):
            with self.subTest(valid=task_id):
                response = self.start(repo, task_id=task_id)
                self.assertEqual(response["task"]["task_id"], task_id)

        invalid_ids = (
            "x" * 65,
            "任务",
            "trailing.",
            "CON",
            "con.txt",
            "Aux.log",
            "LPT9",
            "COM1.port",
            ".",
        )
        for task_id in invalid_ids:
            with self.subTest(invalid=task_id):
                before = {
                    path.name
                    for path in (self.data / "tasks").iterdir()
                    if path.is_dir()
                }
                denied = self.cli(
                    "start",
                    "--task-id",
                    task_id,
                    "--workspace-strategy",
                    "worktree",
                    "--requirement",
                    "reject non-portable identifier",
                    "--repo",
                    str(repo),
                    expected_code=2,
                )
                self.assertEqual(
                    denied["error"]["code"], "INVALID_TASK_ID"
                )
                self.assertEqual(
                    {
                        path.name
                        for path in (self.data / "tasks").iterdir()
                        if path.is_dir()
                    },
                    before,
                )

        self.start(repo, task_id="PortableCase")
        denied = self.cli(
            "start",
            "--task-id",
            "portablecase",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "portable namespace collision",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "TASK_ID_COLLISION"
        )
        self.assertEqual(
            [
                path.name
                for path in (self.data / "tasks").iterdir()
                if path.is_dir()
                and path.name.casefold() == "portablecase"
            ],
            ["PortableCase"],
        )

    def test_task_namespace_lock_serializes_concurrent_case_collisions(self) -> None:
        repo, _ = self.make_repo("parallel namespace repository")
        common = [
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "parallel portable task namespace",
            "--repo",
            str(repo),
        ]
        first = self.controller_process(
            "start", "--task-id", "ParallelCase", *common
        )
        second = self.controller_process(
            "start", "--task-id", "parallelcase", *common
        )
        results = [
            self.process_response(first),
            self.process_response(second),
        ]
        successes = [
            response
            for code, response in results
            if code == 0 and response.get("ok")
        ]
        failures = [
            response
            for code, response in results
            if code != 0 and not response.get("ok")
        ]
        self.assertEqual(len(successes), 1, results)
        self.assertEqual(len(failures), 1, results)
        self.assertIn(
            failures[0]["error"]["code"],
            {"TASK_ID_COLLISION", "TASK_EXISTS"},
        )
        task_directories = [
            path
            for path in (self.data / "tasks").iterdir()
            if path.is_dir()
        ]
        self.assertEqual(len(task_directories), 1)
        self.assertEqual(
            task_directories[0].name.casefold(), "parallelcase"
        )

    def test_filesystem_identity_and_path_selectors_are_alias_safe(self) -> None:
        repository = self.root / "unicode repository"
        repository.mkdir()
        state = {
            "repositories": [
                {
                    "id": "configured-repository",
                    "path": str(repository),
                    "canonical_path": str(repository.resolve()),
                }
            ]
        }
        alias_spelling = repository.parent / "." / repository.name
        self.assertEqual(
            dev_flow._repo_by_selector(
                state, [str(alias_spelling)]
            )[0]["id"],
            "configured-repository",
        )

        symbolic_alias = self.root / "symbolic repository alias"
        try:
            symbolic_alias.symlink_to(repository, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.assertTrue(
                dev_flow._same_path(repository, repository / ".")
            )
        else:
            self.assertTrue(
                dev_flow._same_path(repository, symbolic_alias)
            )

        composed = self.root / "\u00e9"
        composed.mkdir()
        decomposed = self.root / "e\u0301"
        unicode_distinct = dev_flow._probe_filesystem_unicode_distinct(
            self.root
        )
        self.assertEqual(
            dev_flow._same_path(composed, decomposed),
            not unicode_distinct,
        )

        uppercase = self.root / "CaseIdentity"
        uppercase.mkdir()
        lowercase = self.root / "caseidentity"
        with mock.patch.object(
            dev_flow,
            "_probe_filesystem_case_sensitive",
            return_value=False,
        ):
            self.assertTrue(
                dev_flow._same_path(uppercase, lowercase)
            )

        for selector in (
            str(self.root / "missing" / repository.name),
            f"C:\\missing\\{repository.name}",
            f"\\\\server\\share\\{repository.name}",
        ):
            with self.subTest(path_selector=selector):
                with self.assertRaises(
                    dev_flow.FlowError
                ) as captured:
                    dev_flow._repo_by_selector(state, [selector])
                expected_codes = {"REPOSITORY_NOT_FOUND"}
                if os.name == "nt" and selector.startswith("\\\\"):
                    # Managed Windows hosts may deny identity probes for an
                    # unavailable UNC root.  That stronger fail-closed result
                    # is valid and must not be downgraded to a false match.
                    expected_codes.add("PATH_IDENTITY_UNAVAILABLE")
                self.assertIn(
                    captured.exception.code, expected_codes
                )

    def test_start_multi_repo_atomic_state_events_and_revision_conflict(self) -> None:
        first, _ = self.make_repo("first")
        second, _ = self.make_repo("second")
        response = self.start(first, second, task_id="multi")
        task = response["task"]
        self.assertEqual(task["status"], "INTAKE")
        self.assertEqual(task["revision"], 1)
        self.assertEqual(len(task["repositories"]), 2)
        task_dir = self.data / "tasks" / "multi"
        self.assertTrue((task_dir / "state.json").is_file())
        self.assertTrue((task_dir / "artifacts").is_dir())
        if os.name == "posix":
            self.assertEqual((task_dir / "artifacts").stat().st_mode & 0o777, 0o700)
        events = (task_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0])["type"], "task_started")

        conflict = self.cli(
            "preflight",
            "multi",
            "--expected-revision",
            "0",
            expected_code=3,
        )
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(dev_flow.load_state("multi", self.data)["revision"], 1)
        self.assertEqual(len((task_dir / "events.jsonl").read_text().splitlines()), 1)

    def test_sensitive_remote_values_are_redacted_from_state_and_quarantine(
        self,
    ) -> None:
        repo, _ = self.make_repo("credential-redaction")
        token = "very-secret-remote-token"
        remote_url = (
            f"https://build-user:{token}@example.invalid/team/repo.git"
            f"?access_token={token}"
        )
        git(repo, "remote", "set-url", "origin", remote_url)
        task = self.start(repo, task_id="credential-redaction")["task"]
        self.mutate("preflight", task)
        state = dev_flow.load_state(task["task_id"], self.data)
        preflight = state["repositories"][0]["preflight"]
        self.assertNotIn(token, json.dumps(state, ensure_ascii=False))
        self.assertNotIn(token, preflight["remote_url"])
        self.assertEqual(
            preflight["remote_url_sha256"],
            dev_flow._sensitive_value_sha256(remote_url),
        )

        task_dir = self.data / "tasks" / task["task_id"]
        state_path = task_dir / "state.json"
        legacy_state = json.loads(state_path.read_text(encoding="utf-8"))
        legacy_state["legacy_error"] = f"stderr: token={token}"
        dev_flow._atomic_write_json(state_path, legacy_state)
        migrated = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn(token, json.dumps(migrated, ensure_ascii=False))
        self.assertNotIn(token, state_path.read_text(encoding="utf-8"))

        quarantine_path = task_dir / "mutation-quarantine.json"
        dev_flow._atomic_write_json(
            quarantine_path,
            {
                "ready": False,
                "command": [
                    "git",
                    "fetch",
                    remote_url,
                    "--token",
                    token,
                ],
                "stderr": f"password={token}",
            },
        )
        quarantine = dev_flow._read_quarantine(task_dir)
        self.assertIsNotNone(quarantine)
        self.assertNotIn(token, json.dumps(quarantine, ensure_ascii=False))
        self.assertNotIn(token, quarantine_path.read_text(encoding="utf-8"))

    def test_structured_redaction_preserves_operational_state_and_split_tokens(
        self,
    ) -> None:
        repo, _ = self.make_repo("token=abc")
        task = self.start(repo, task_id="structured-redaction")["task"]
        stored_repo = task["repositories"][0]
        self.assertEqual(stored_repo["path"], str(repo.resolve()))
        self.assertEqual(stored_repo["canonical_path"], str(repo.resolve()))
        self.assertEqual(
            dev_flow.find_active_task_for_cwd(repo, self.data)["task_id"],
            task["task_id"],
        )

        first_secret = "VERY_SECRET_TOKEN"
        second_secret = "VERY_SECRET_PASSWORD"
        preview_token = "v3:decision:observation"
        safe = dev_flow._redact_sensitive_value(
            {
                "path": str(repo),
                "branch": "feature/token=refresh",
                "requirement": "keep token=literal as workflow text",
                "command": (
                    f"pytest --token {first_secret} "
                    f"--password {second_secret}"
                ),
                "stderr": f"password={second_secret}",
                "password": second_secret,
                "token": first_secret,
                "transition_preview": {"token": preview_token},
            }
        )
        self.assertEqual(safe["path"], str(repo))
        self.assertEqual(safe["branch"], "feature/token=refresh")
        self.assertEqual(
            safe["requirement"], "keep token=literal as workflow text"
        )
        self.assertEqual(
            safe["transition_preview"]["token"], preview_token
        )
        self.assertEqual(safe["password"], "<redacted>")
        self.assertEqual(safe["token"], "<redacted>")
        self.assertNotIn(first_secret, safe["command"])
        self.assertNotIn(second_secret, safe["command"])
        self.assertNotIn(second_secret, safe["stderr"])

        redacted_argv = dev_flow._redacted_command(
            [
                "tool",
                "--token",
                first_secret,
                "--password",
                second_secret,
                "--api-key=THIRD_SECRET",
            ]
        )
        self.assertEqual(
            redacted_argv,
            [
                "tool",
                "--token",
                "<redacted>",
                "--password",
                "<redacted>",
                "--api-key=<redacted>",
            ],
        )

        current = dev_flow.load_state(task["task_id"], self.data)
        replacement = dev_flow._copy_state(current)
        replacement["tests"] = [
            {
                "command": f"pytest --token {first_secret}",
                "repository_ids": [stored_repo["id"]],
            }
        ]
        task_dir = self.data / "tasks" / task["task_id"]
        dev_flow._commit_state(
            current,
            replacement,
            task_dir,
            "structured_redaction_probe",
        )
        persisted = (task_dir / "state.json").read_text(encoding="utf-8")
        self.assertNotIn(first_secret, persisted)
        persisted_state = json.loads(persisted)
        self.assertEqual(
            persisted_state["repositories"][0]["path"],
            str(repo.resolve()),
        )

    def test_active_repository_claim_rejects_duplicate_start_and_ambiguity(
        self,
    ) -> None:
        repo, _ = self.make_repo("repository-claim")
        first = self.start(repo, task_id="claim-owner")["task"]
        denied = self.cli(
            "start",
            "--task-id",
            "claim-contender",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "must not share an active repository",
            "--repo",
            str(repo),
            expected_code=2,
        )
        self.assertEqual(denied["error"]["code"], "REPOSITORY_CLAIM_CONFLICT")
        claim = first["repositories"][0]["repository_claim"]
        self.assertIn("canonical_path_identity", claim)
        self.assertIn("git_common_dir_identity", claim)

        duplicate_dir = self.data / "tasks" / "legacy-conflict"
        dev_flow._ensure_private_dir(duplicate_dir)
        duplicate = json.loads(
            (self.data / "tasks" / first["task_id"] / "state.json").read_text(
                encoding="utf-8"
            )
        )
        duplicate["task_id"] = "legacy-conflict"
        duplicate["repositories"][0].pop("repository_claim", None)
        dev_flow._atomic_write_json(duplicate_dir / "state.json", duplicate)
        with self.assertRaises(dev_flow.FlowError) as captured:
            dev_flow.find_active_task_for_cwd(repo, self.data)
        self.assertEqual(captured.exception.code, "ACTIVE_TASK_AMBIGUITY")

    def test_pending_event_recovery_is_idempotent_and_partial_writes_complete(
        self,
    ) -> None:
        repo, _ = self.make_repo("event-outbox")
        task = self.start(repo, task_id="event-outbox")["task"]
        task_dir = self.data / "tasks" / task["task_id"]
        current = dev_flow.load_state(task["task_id"], self.data)
        replacement = dev_flow._copy_state(current)
        replacement["requirement"] = "commit after injected event failure"
        with mock.patch.object(
            dev_flow,
            "_append_event",
            side_effect=dev_flow.FlowError("EVENT_APPEND_FAILED", "injected"),
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._commit_state(
                    current,
                    replacement,
                    task_dir,
                    "injected_event",
                )
        self.assertEqual(captured.exception.code, "EVENT_DELIVERY_PENDING")
        persisted = json.loads((task_dir / "state.json").read_text(encoding="utf-8"))
        self.assertIn("pending_event", persisted)
        event_id = persisted["pending_event"]["event_id"]

        recovered = dev_flow.load_state(task["task_id"], self.data)
        self.assertNotIn("pending_event", recovered)
        events_path = task_dir / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sum(item["event_id"] == event_id for item in events), 1)
        dev_flow.load_state(task["task_id"], self.data)
        events_again = events_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(events_again), len(events))

        partial_path = task_dir / "partial-events.jsonl"
        partial_event = {"event_id": "partial-event", "payload": {"ok": True}}
        real_write = os.write

        def partial_write(descriptor: int, data: object) -> int:
            payload = bytes(data)
            return real_write(descriptor, payload[: max(1, len(payload) // 2)])

        with mock.patch.object(dev_flow.os, "write", side_effect=partial_write):
            dev_flow._append_event(partial_path, partial_event)
        self.assertEqual(
            json.loads(partial_path.read_text(encoding="utf-8")), partial_event
        )
        dev_flow._append_event(partial_path, partial_event)
        self.assertEqual(
            len(partial_path.read_text(encoding="utf-8").splitlines()), 1
        )

    def test_currentness_helpers_accept_a_shared_fingerprint_observation(
        self,
    ) -> None:
        fingerprint = {
            "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
            "sha256": "fingerprint",
            "capability_profile_sha256": "capability",
        }
        state = {
            "flow": "full",
            "repositories": [{"id": "repo"}],
            "tests": [
                {
                    "evidence_contract_version": dev_flow.EVIDENCE_CONTRACT_VERSION,
                    "name": "unit",
                    "command": "run unit",
                    "passed": True,
                    "repository_ids": ["repo"],
                    "fingerprints": {"repo": fingerprint},
                    "capability_profile_sha256": {"repo": "capability"},
                    "plan_artifact_sha256": "plan",
                    "plan_approval_id": "approval",
                    "recorded_at": "2026-07-21T00:00:01.000Z",
                }
            ],
        }
        with mock.patch.object(
            dev_flow,
            "_require_current_plan_gate",
            return_value=(
                {"approval_id": "approval", "approved_at": "2026-07-21T00:00:00.000Z"},
                {"sha256": "plan"},
            ),
        ), mock.patch.object(
            dev_flow,
            "_fingerprint_repo",
            side_effect=AssertionError("shared observation should be reused"),
        ):
            self.assertEqual(
                dev_flow._latest_passing_test_is_current(
                    state,
                    fingerprints={"repo": fingerprint},
                ),
                (True, None),
            )

        review_state = {
            "repositories": [{"id": "repo"}],
            "review_snapshots": [
                {
                    "repositories": [
                        {
                            "repository_id": "repo",
                            "fingerprint": {"sha256": "fingerprint"},
                            "capability_profile_sha256": "capability",
                        }
                    ]
                }
            ],
        }
        with mock.patch.object(
            dev_flow,
            "_review_snapshot_integrity_error",
            return_value=None,
        ), mock.patch.object(
            dev_flow,
            "_workspace_integrity_error",
            return_value=None,
        ), mock.patch.object(
            dev_flow,
            "_fingerprint_repo",
            side_effect=AssertionError("shared observation should be reused"),
        ):
            self.assertEqual(
                dev_flow._review_is_current(
                    review_state,
                    fingerprints={"repo": fingerprint},
                ),
                (True, None),
            )

    def test_start_rejects_two_worktrees_from_the_same_git_repository(self) -> None:
        repo, _ = self.make_repo("duplicate-common-dir")
        linked = self.root / "duplicate-common-linked"
        git(
            repo,
            "worktree",
            "add",
            "-q",
            "-b",
            "duplicate-common-linked",
            str(linked),
            "HEAD",
        )
        denied = self.cli(
            "start",
            "--task-id",
            "duplicate-common-dir",
            "--workspace-strategy",
            "worktree",
            "--requirement",
            "must not double-count one Git repository",
            "--repo",
            str(repo),
            "--repo",
            str(linked),
            expected_code=2,
        )
        self.assertEqual(
            denied["error"]["code"], "DUPLICATE_GIT_REPOSITORY"
        )
        self.assertFalse(
            (self.data / "tasks" / "duplicate-common-dir" / "state.json").exists()
        )

    def test_private_permissions_and_atomic_replace_failure(self) -> None:
        private_directory = self.root / "private state"
        dev_flow._ensure_private_dir(private_directory)
        state_path = private_directory / "state.json"
        dev_flow._atomic_write_bytes(state_path, b"old\n")
        if os.name == "posix":
            self.assertEqual(
                stat.S_IMODE(private_directory.stat().st_mode), 0o700
            )
            self.assertEqual(
                stat.S_IMODE(state_path.stat().st_mode), 0o600
            )

        with mock.patch.object(
            dev_flow.os,
            "replace",
            side_effect=OSError(errno.EIO, "injected replace failure"),
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._atomic_write_bytes(state_path, b"new\n")
        self.assertEqual(captured.exception.code, "ATOMIC_WRITE_FAILED")
        self.assertEqual(
            captured.exception.details["phase"], "replace"
        )
        self.assertEqual(state_path.read_bytes(), b"old\n")
        self.assertEqual(
            list(private_directory.glob(".state.json.*")), []
        )



if __name__ == "__main__":
    unittest.main()
