from __future__ import annotations

import dataclasses
import json
import socket
import subprocess
from pathlib import Path
from types import MappingProxyType
from unittest import mock

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class V3CommandBoundaryMatrixTests(DevFlowTestCase):
    def _active_multi_services(self) -> object:
        services = dev_flow.workflow_runtime_services()
        activations = []
        for frozen in services.catalog.activations:
            item = dict(frozen)
            active = (
                item["workflow_id"] == "full"
                and item["workflow_version"] == 3
                and item["execution_profile"] == "single-repository"
            )
            item["active"] = active
            item["required_suites"] = (
                sorted(
                    {
                        *dev_flow.WORKFLOW_V3_REQUIRED_SUITES[
                            "single-repository"
                        ],
                        *{
                            str(suite)
                            for edge in services.catalog.resolve(
                                "full", 3
                            ).action_edges
                            for suite in edge["required_suites"]
                        },
                    }
                )
                if active
                else []
            )
            activations.append(MappingProxyType(item))
        return dataclasses.replace(
            services,
            catalog=dataclasses.replace(
                services.catalog, activations=tuple(activations)
            ),
        )

    def _start(self, task_id: str) -> tuple[dict, Path]:
        repository, _ = self.make_repo(f"{task_id}-repository")
        with mock.patch.object(
            dev_flow,
            "_workflow_runtime_services",
            self._active_multi_services(),
        ):
            started = self.cli(
                "start",
                "prove the schema-v3 command boundary",
                "--repo",
                str(repository),
                "--task-id",
                task_id,
                "--workspace-strategy",
                "worktree",
            )
        return started, repository

    def _authorize(
        self, task_id: str, revision: int, action_id: str
    ) -> tuple[dict, bytearray]:
        preview = self.cli(
            "manager-authorize",
            task_id,
            "--expected-revision",
            str(revision),
            "--manager-session-id",
            "v3-boundary-manager",
            "--ttl-seconds",
            "60",
            "--preview",
        )
        publisher, consumer = socket.socketpair()
        try:
            authorized = self.cli(
                "manager-authorize",
                task_id,
                "--expected-revision",
                str(revision),
                "--manager-session-id",
                "v3-boundary-manager",
                "--ttl-seconds",
                "60",
                "--confirm-intent",
                preview["preview"]["intent_id"],
                "--manager-secret-fd",
                str(publisher.fileno()),
            )
            secret = dev_flow.resolve_manager_secret(
                dev_flow.ManagerSecretChannelConfig(consumer.fileno())
            )
        finally:
            publisher.close()
            consumer.close()
        self.assertIn(
            action_id, authorized["capability"]["allowed_actions"]
        )
        return authorized, secret

    def _manager_apply(
        self,
        *arguments: str,
        request: dict,
        secret: bytearray,
        expected_code: int = 0,
    ) -> dict:
        publisher, consumer = socket.socketpair()
        try:
            dev_flow.publish_manager_secret(
                dev_flow.ManagerSecretChannelConfig(publisher.fileno()),
                secret,
            )
            return self.cli(
                *arguments,
                "--manager-request-json",
                json.dumps(
                    request,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "--manager-secret-fd",
                str(consumer.fileno()),
                expected_code=expected_code,
            )
        finally:
            publisher.close()
            consumer.close()

    def _data_snapshot(self) -> dict[str, bytes]:
        return {
            str(path.relative_to(self.data)): path.read_bytes()
            for path in sorted(self.data.rglob("*"))
            if path.is_file()
        }

    @staticmethod
    def _git_snapshot(repository: Path) -> tuple[str, bytes]:
        head = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        return head, status

    @staticmethod
    def _legacy_path_used(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("schema-v3 command entered a legacy path")

    def test_transition_uses_engine_intent_and_wrong_token_is_zero_write(
        self,
    ) -> None:
        started, repository = self._start("v3-intent-zero-write")
        authorized, secret = self._authorize(
            started["task_id"],
            started["revision"],
            "task.transition",
        )
        try:
            with (
                mock.patch.object(
                    dev_flow,
                    "_transition_guard",
                    self._legacy_path_used,
                ),
                mock.patch.object(
                    dev_flow,
                    "_transition_intent_preview",
                    self._legacy_path_used,
                ),
                mock.patch.object(
                    dev_flow,
                    "FORWARD_EDGES",
                    {"INTAKE": {"DONE"}},
                ),
                mock.patch.object(
                    dev_flow,
                    "REWORK_EDGES",
                    {"INTAKE": {"DONE"}},
                ),
            ):
                preview = self.cli(
                    "transition",
                    started["task_id"],
                    "--expected-revision",
                    str(authorized["revision"]),
                    "--to",
                    "BLOCKED",
                    "--note",
                    "waiting for a decision",
                    "--preview",
                )["preview"]
                self.assertTrue(
                    preview["intent_id"].startswith(
                        "dev-flow-transition-intent/v1:"
                    )
                )
                self.assertEqual(
                    preview["edge_id"], "full.block.intake.blocked"
                )
                self.assertNotIn(
                    "blocked", preview["action_parameters"]
                )
                before_data = self._data_snapshot()
                before_git = self._git_snapshot(repository)
                wrong = preview["intent_id"][:-1] + (
                    "0" if preview["intent_id"][-1] != "0" else "1"
                )
                request = {
                    "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
                    "capability_id": authorized["capability"][
                        "capability_id"
                    ],
                    "task_id": started["task_id"],
                    "manager_session_id": "v3-boundary-manager",
                    "action_id": "task.transition",
                    "expected_revision": authorized["revision"],
                    "request_nonce": "a" * 64,
                }
                rejected = self._manager_apply(
                    "transition",
                    started["task_id"],
                    "--expected-revision",
                    str(authorized["revision"]),
                    "--to",
                    "BLOCKED",
                    "--note",
                    "waiting for a decision",
                    "--confirm-intent",
                    wrong,
                    request=request,
                    secret=secret,
                    expected_code=2,
                )
                self.assertEqual(rejected["error"]["code"], "INTENT_STALE")
                self.assertEqual(self._data_snapshot(), before_data)
                self.assertEqual(
                    self._git_snapshot(repository), before_git
                )

                with mock.patch.object(
                    dev_flow,
                    "_atomic_write_json",
                    side_effect=dev_flow.FlowError(
                        "INJECTED_ATOMIC_WRITE_FAILURE",
                        "fail before durable state publication",
                    ),
                ):
                    failed_commit = self._manager_apply(
                        "transition",
                        started["task_id"],
                        "--expected-revision",
                        str(authorized["revision"]),
                        "--to",
                        "BLOCKED",
                        "--note",
                        "waiting for a decision",
                        "--confirm-intent",
                        preview["intent_id"],
                        request=request,
                        secret=secret,
                        expected_code=2,
                    )
                self.assertEqual(
                    failed_commit["error"]["code"],
                    "INJECTED_ATOMIC_WRITE_FAILURE",
                )
                self.assertEqual(self._data_snapshot(), before_data)
                self.assertEqual(
                    self._git_snapshot(repository), before_git
                )

                applied = self._manager_apply(
                    "transition",
                    started["task_id"],
                    "--expected-revision",
                    str(authorized["revision"]),
                    "--to",
                    "BLOCKED",
                    "--note",
                    "waiting for a decision",
                    "--confirm-intent",
                    preview["intent_id"],
                    request=request,
                    secret=secret,
                )
            self.assertEqual(applied["status"], "BLOCKED")
            self.assertEqual(
                dev_flow.load_state(
                    started["task_id"], self.data
                )["blocked"]["reason"],
                "waiting for a decision",
            )
        finally:
            dev_flow._manager_zeroize(secret)

    def test_cancel_record_is_reducer_owned_and_legacy_intent_is_unreachable(
        self,
    ) -> None:
        started, _repository = self._start("v3-cancel-boundary")
        authorized, secret = self._authorize(
            started["task_id"], started["revision"], "task.cancel"
        )
        request = {
            "schema": dev_flow.MANAGER_CAPABILITY_REQUEST_SCHEMA,
            "capability_id": authorized["capability"]["capability_id"],
            "task_id": started["task_id"],
            "manager_session_id": "v3-boundary-manager",
            "action_id": "task.cancel",
            "expected_revision": authorized["revision"],
            "request_nonce": "b" * 64,
        }
        try:
            with mock.patch.object(
                dev_flow,
                "_transition_intent_preview",
                self._legacy_path_used,
            ):
                preview = self.cli(
                    "cancel",
                    started["task_id"],
                    "--expected-revision",
                    str(authorized["revision"]),
                    "--reason",
                    "superseded",
                    "--preview",
                )["preview"]
                self.assertEqual(
                    preview["edge_id"], "full.cancel.intake.cancelled"
                )
                self.assertNotIn(
                    "cancelled", preview["action_parameters"]
                )
                applied = self._manager_apply(
                    "cancel",
                    started["task_id"],
                    "--expected-revision",
                    str(authorized["revision"]),
                    "--reason",
                    "superseded",
                    "--confirm-intent",
                    preview["intent_id"],
                    request=request,
                    secret=secret,
                )
            self.assertEqual(applied["status"], "CANCELLED")
            self.assertEqual(
                applied["cancelled"]["reason"], "superseded"
            )
            events = [
                json.loads(line)
                for line in (
                    self.data
                    / "tasks"
                    / started["task_id"]
                    / "events.jsonl"
                )
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            reducer_facts = [
                item
                for item in events
                if item["revision"] == applied["revision"]
                and item["type"] == "workflow_audit_fact"
                and item["payload"]["fact_type"]
                == "registered-reducer-applied"
            ]
            self.assertTrue(reducer_facts)
        finally:
            dev_flow._manager_zeroize(secret)
