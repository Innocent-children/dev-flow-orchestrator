from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = (
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "mcp_controller_service.py"
)


def load_service_namespace(**dependencies):
    namespace = {
        "__file__": str(SERVICE_PATH),
        "__name__": "dev_flow_mcp_controller_service_test",
        "ARTIFACT_REFERENCE_SCHEMA": (
            "dev-flow-artifact-reference/v1"
        ),
    }
    namespace.update(dependencies)
    source = SERVICE_PATH.read_bytes()
    exec(
        compile(source, str(SERVICE_PATH), "exec"),
        namespace,
        namespace,
    )
    return SimpleNamespace(**namespace)


def request(tool: str, arguments: dict) -> dict:
    return {
        "schema": "dev-flow-controller-mcp-request/v1",
        "tool": tool,
        "arguments": arguments,
        "request_identity": (
            arguments.get("request_identity")
            if tool in {"action-apply", "worker-result"}
            else None
        ),
    }


class McpControllerServiceTests(unittest.TestCase):
    def test_same_known_revision_returns_bounded_unchanged_without_projection(
        self,
    ) -> None:
        calls = []

        def forbidden_projection(_state, *, data_dir=None):
            calls.append(data_dir)
            raise AssertionError("unchanged read must not build projection")

        module = load_service_namespace(
            load_state=lambda task_id, _data_dir: {
                "task_id": task_id,
                "revision": 9,
            },
            build_workflow_task_next=forbidden_projection,
        )
        service = module.McpControllerService(data_dir="/data")

        value = service.dispatch_mcp_tool(
            request(
                "task-next",
                {
                    "contract": "dev-flow-mcp-task-next/v1",
                    "task_id": "task-1",
                    "known_revision": 9,
                },
            )
        )

        self.assertEqual(
            value,
            {
                "contract": "dev-flow-task-next-unchanged/v1",
                "task_id": "task-1",
                "revision": 9,
                "known_revision": 9,
                "unchanged": True,
            },
        )
        self.assertLess(
            len(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            256,
        )
        self.assertEqual(calls, [])

    def test_older_known_revision_returns_current_projection_with_delta(
        self,
    ) -> None:
        module = load_service_namespace(
            load_state=lambda task_id, _data_dir: {
                "task_id": task_id,
                "revision": 7,
            },
            build_workflow_task_next=lambda state, *, data_dir=None,
            revision_delta=None: {
                "contract": "dev-flow-agent-v1",
                "task_id": state["task_id"],
                "revision": state["revision"],
                "frontier_digest": "f" * 64,
                **(
                    {"revision_delta": revision_delta}
                    if revision_delta is not None
                    else {}
                ),
            },
        )
        calls = []

        def revision_delta(
            task_id, data_dir, known_revision, current_revision
        ):
            calls.append(
                (
                    task_id,
                    data_dir,
                    known_revision,
                    current_revision,
                )
            )
            return {
                "contract": "dev-flow-task-next-delta/v1",
                "from_revision": known_revision,
                "to_revision": current_revision,
                "revision_count": 2,
                "delta_sha256": "d" * 64,
                "reset_required": False,
            }

        service = module.McpControllerService(
            data_dir="/data",
            revision_delta_reader=revision_delta,
        )

        value = service.dispatch_mcp_tool(
            request(
                "task-next",
                {
                    "contract": "dev-flow-mcp-task-next/v1",
                    "task_id": "task-1",
                    "known_revision": 5,
                },
            )
        )

        self.assertEqual(value["revision"], 7)
        self.assertEqual(
            value["revision_delta"]["contract"],
            "dev-flow-task-next-delta/v1",
        )
        self.assertEqual(
            value["revision_delta"]["from_revision"], 5
        )
        self.assertEqual(
            calls, [("task-1", "/data", 5, 7)]
        )

    def test_factory_composes_revision_delta_from_runtime_store(
        self,
    ) -> None:
        calls = []

        def task_directory(task_id, data_dir):
            calls.append(("task-directory", task_id, data_dir))
            return Path(data_dir) / "tasks" / task_id

        def read_bounded_events(task_dir):
            calls.append(("read-events", str(task_dir)))
            return (
                {
                    "event_id": "event-6",
                    "task_id": "task-1",
                    "type": "state_transitioned",
                    "previous_revision": 5,
                    "revision": 6,
                },
                {
                    "event_id": "event-7-primary",
                    "task_id": "task-1",
                    "type": "gate_approved",
                    "previous_revision": 6,
                    "revision": 7,
                },
                {
                    "event_id": "event-7-secondary",
                    "task_id": "task-1",
                    "type": "state_transitioned",
                    "previous_revision": 6,
                    "revision": 7,
                },
            )

        module = load_service_namespace(
            load_state=lambda task_id, _data_dir: {
                "task_id": task_id,
                "revision": 7,
            },
            build_workflow_task_next=lambda state, *, data_dir=None,
            revision_delta=None: {
                "contract": "dev-flow-agent-v1",
                "task_id": state["task_id"],
                "revision": state["revision"],
                "frontier_digest": "f" * 64,
                **(
                    {"revision_delta": revision_delta}
                    if revision_delta is not None
                    else {}
                ),
            },
            workflow_runtime_services=lambda: SimpleNamespace(
                store=SimpleNamespace(
                    task_directory=task_directory,
                    read_bounded_events=read_bounded_events,
                )
            ),
        )
        service = module.create_mcp_controller_service(
            data_dir="/data"
        )

        value = service.dispatch_mcp_tool(
            request(
                "task-next",
                {
                    "contract": "dev-flow-mcp-task-next/v1",
                    "task_id": "task-1",
                    "known_revision": 5,
                },
            )
        )

        delta = value["revision_delta"]
        self.assertEqual(
            delta["contract"], "dev-flow-task-next-delta/v1"
        )
        self.assertEqual(delta["from_revision"], 5)
        self.assertEqual(delta["to_revision"], 7)
        self.assertEqual(delta["revision_count"], 2)
        self.assertFalse(delta["reset_required"])
        self.assertRegex(delta["delta_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            calls,
            [
                ("task-directory", "task-1", "/data"),
                ("read-events", "/data/tasks/task-1"),
            ],
        )

    def test_incomplete_event_delta_requires_checkpoint_reset(
        self,
    ) -> None:
        module = load_service_namespace()

        delta = module._mcs_event_revision_delta(
            "task-1",
            "/data",
            5,
            7,
            task_directory=lambda task_id, data_dir: (
                Path(data_dir) / "tasks" / task_id
            ),
            event_reader=lambda _task_dir: (
                {
                    "event_id": "event-7",
                    "task_id": "task-1",
                    "type": "state_transitioned",
                    "previous_revision": 6,
                    "revision": 7,
                    "payload": {"status": "VERIFYING"},
                },
            ),
        )

        self.assertEqual(delta["revision_count"], 1)
        self.assertTrue(delta["reset_required"])

    def test_node_instance_must_bind_the_requested_catalog_node(
        self,
    ) -> None:
        module = load_service_namespace(
            load_state=lambda task_id, _data_dir: {
                "task_id": task_id,
                "revision": 4,
                "node_instances": [
                    {
                        "node_instance_id": "node-instance-1",
                        "node_id": "IMPLEMENTING",
                    }
                ],
            },
            workflow_node_description=lambda _state, _node_id: {
                "contract": "dev-flow-node-description/v1"
            },
        )
        service = module.McpControllerService()

        with self.assertRaises(
            module.McpControllerServiceError
        ) as raised:
            service.dispatch_mcp_tool(
                request(
                    "node-description",
                    {
                        "contract": (
                            "dev-flow-mcp-node-description/v1"
                        ),
                        "task_id": "task-1",
                        "node_id": "VERIFYING",
                        "node_instance_id": "node-instance-1",
                    },
                )
            )

        self.assertEqual(
            raised.exception.code, "MCP_NODE_INSTANCE_MISMATCH"
        )

    def test_evidence_read_is_task_scoped_digest_bound_and_bounded(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task_dir = root / "tasks" / "task-1"
            artifact_dir = task_dir / "artifacts" / "orchestration"
            artifact_dir.mkdir(parents=True)
            content = b'{"result":"verified"}\n'
            digest = hashlib.sha256(content).hexdigest()
            locator = f"artifacts/orchestration/{digest}.json"
            (task_dir / locator).write_bytes(content)
            reference = {
                "id": "evidence-1",
                "semantic_sha256": digest,
                "sha256": digest,
                "size": len(content),
                "kind": "test.report.v1",
                "locator": locator,
            }
            state = {
                "task_id": "task-1",
                "revision": 12,
                "orchestration": {
                    "artifacts": {"evidence-1": reference}
                },
            }
            module = load_service_namespace(
                load_state=lambda _task_id, _data_dir: state,
                _osc_state_copy=lambda value: value["orchestration"],
                _osc_artifact_locator=(
                    lambda value: (
                        f"artifacts/orchestration/{value}.json"
                    )
                ),
                _task_dir=lambda task_id, _data_dir: (
                    root / "tasks" / task_id
                ),
            )
            service = module.McpControllerService(data_dir=root)

            value = service.dispatch_mcp_tool(
                request(
                    "evidence-read",
                    {
                        "contract": "dev-flow-mcp-evidence-read/v1",
                        "task_id": "task-1",
                        "evidence_id": "evidence-1",
                        "expected_sha256": digest,
                    },
                )
            )

            self.assertTrue(value["inline"])
            self.assertEqual(value["reference"]["sha256"], digest)
            self.assertEqual(value["reference"]["locator"], locator)
            with self.assertRaises(
                module.McpControllerServiceError
            ) as raised:
                service.dispatch_mcp_tool(
                    request(
                        "evidence-read",
                        {
                            "contract": (
                                "dev-flow-mcp-evidence-read/v1"
                            ),
                            "task_id": "task-1",
                            "evidence_id": "evidence-1",
                            "expected_sha256": "0" * 64,
                        },
                    )
                )
            self.assertEqual(
                raised.exception.code,
                "MCP_EVIDENCE_EXPECTED_DIGEST_MISMATCH",
            )

    def test_action_services_fail_closed_when_not_injected(
        self,
    ) -> None:
        module = load_service_namespace()
        service = module.McpControllerService()

        with self.assertRaises(
            module.McpControllerServiceError
        ) as raised:
            service.dispatch_mcp_tool(
                request(
                    "action-preview",
                    {
                        "contract": "dev-flow-mcp-action-preview/v1",
                        "task_id": "task-1",
                        "expected_revision": 3,
                        "action_id": "transition",
                        "input": {
                            "contract": (
                                "dev-flow-action-transition-input/v1"
                            ),
                            "to": "VERIFYING",
                            "note": None,
                        },
                    },
                )
            )

        self.assertEqual(
            raised.exception.code,
            "MCP_ACTION_SERVICE_UNAVAILABLE",
        )

    def test_missing_manager_channel_preserves_reads_and_denies_writes(
        self,
    ) -> None:
        calls = {"factory": 0, "apply": 0, "result": 0}

        def unavailable_channel():
            calls["factory"] += 1
            raise RuntimeError("manager FD is not configured")

        def preview_action(
            task_id,
            *,
            expected_revision,
            action_id,
            input_value,
            data_dir=None,
        ):
            return {
                "contract": (
                    "dev-flow-mcp-action-preview-result/v1"
                ),
                "task_id": task_id,
                "revision": expected_revision,
                "action_id": action_id,
                "input_sha256": hashlib.sha256(
                    json.dumps(
                        input_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "preview_intent": "intent-1",
                "applicable": True,
                "blockers": [],
            }

        def forbidden_apply(*_args, **_kwargs):
            calls["apply"] += 1
            raise AssertionError("write service must not be entered")

        class ForbiddenResultService:
            def accept_result(self, *_args, **_kwargs):
                calls["result"] += 1
                raise AssertionError(
                    "result service must not be entered"
                )

        module = load_service_namespace()
        service = module.create_mcp_controller_service(
            action_preview=preview_action,
            action_apply=forbidden_apply,
            manager_channel_factory=unavailable_channel,
            orchestration_service=ForbiddenResultService(),
        )
        input_value = {
            "contract": "dev-flow-action-transition-input/v1",
            "to": "VERIFYING",
            "note": None,
        }
        preview = service.dispatch_mcp_tool(
            request(
                "action-preview",
                {
                    "contract": "dev-flow-mcp-action-preview/v1",
                    "task_id": "task-1",
                    "expected_revision": 7,
                    "action_id": "transition",
                    "input": input_value,
                },
            )
        )
        identity = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": "capability-1",
            "task_id": "task-1",
            "manager_session_id": "manager-1",
            "action_id": "transition",
            "expected_revision": 7,
            "request_nonce": "3" * 64,
        }

        with self.assertRaises(
            module.McpControllerServiceError
        ) as raised:
            service.dispatch_mcp_tool(
                request(
                    "action-apply",
                    {
                        "contract": (
                            "dev-flow-mcp-action-apply/v1"
                        ),
                        "task_id": "task-1",
                        "expected_revision": 7,
                        "action_id": "transition",
                        "preview_intent": preview[
                            "preview_intent"
                        ],
                        "request_identity": identity,
                        "input": input_value,
                    },
                )
            )

        self.assertEqual(
            raised.exception.code,
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
        )
        worker_identity = {
            **identity,
            "action_id": "worker-result.submit/v1",
            "request_nonce": "4" * 64,
        }
        with self.assertRaises(
            module.McpControllerServiceError
        ) as worker_raised:
            service.dispatch_mcp_tool(
                request(
                    "worker-result",
                    {
                        "contract": (
                            "dev-flow-mcp-worker-result/v1"
                        ),
                        "task_id": "task-1",
                        "expected_revision": 7,
                        "request_identity": worker_identity,
                        "result": {
                            "schema": "dev-flow-node-result/v1",
                            "result_id": (
                                "node-result-" + "4" * 64
                            ),
                        },
                    },
                )
            )
        self.assertEqual(
            worker_raised.exception.code,
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
        )
        self.assertEqual(
            calls, {"factory": 1, "apply": 0, "result": 0}
        )

    def test_worker_result_uses_atomic_acceptance_without_verified_input(
        self,
    ) -> None:
        observed = {}

        class AtomicResultService:
            def accept_result(
                self,
                task_id,
                result_value,
                *,
                request,
                principal,
                data_dir=None,
            ):
                observed.update(
                    {
                        "task_id": task_id,
                        "result": result_value,
                        "request": request,
                        "principal": principal,
                        "data_dir": data_dir,
                    }
                )
                return {
                    "task_id": task_id,
                    "revision": 8,
                    "event_id": "event-result-1",
                    "event_type": "orchestration_result_accepted",
                    "authorization_id": "authorization-1",
                    "payload": {},
                }

        module = load_service_namespace()
        principal = {
            "schema": "dev-flow-agent-principal/v1",
            "role": "manager",
            "session_id": "manager-1",
            "os_user_identity_sha256": "1" * 64,
            "host_identity_sha256": "2" * 64,
        }
        service = module.McpControllerService(
            data_dir="/data",
            principal_resolver=lambda _request: principal,
            orchestration_service=AtomicResultService(),
        )
        identity = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": "capability-1",
            "task_id": "task-1",
            "manager_session_id": "manager-1",
            "action_id": "worker-result.submit/v1",
            "expected_revision": 7,
            "request_nonce": "3" * 64,
        }
        candidate = {
            "schema": "dev-flow-node-result/v1",
            "result_id": "node-result-" + "4" * 64,
        }

        value = service.dispatch_mcp_tool(
            request(
                "worker-result",
                {
                    "contract": "dev-flow-mcp-worker-result/v1",
                    "task_id": "task-1",
                    "expected_revision": 7,
                    "request_identity": identity,
                    "result": candidate,
                },
            )
        )

        self.assertEqual(
            value["contract"],
            "dev-flow-worker-result-acceptance/v1",
        )
        self.assertEqual(observed["principal"], principal)
        self.assertNotIn("verified_output", observed)
        self.assertEqual(observed["result"], candidate)

    def test_factory_uses_one_channel_for_principal_and_zeroized_secret(
        self,
    ) -> None:
        calls = {"factory": 0, "principal": 0, "secret": 0}
        issued_buffers = []

        class Channel:
            def principal_for(self, request_identity):
                calls["principal"] += 1
                return {
                    "schema": "dev-flow-agent-principal/v1",
                    "role": "manager",
                    "session_id": request_identity[
                        "manager_session_id"
                    ],
                    "os_user_identity_sha256": "1" * 64,
                    "host_identity_sha256": "2" * 64,
                }

            def resolve_secret(self, _capability_id):
                calls["secret"] += 1
                value = bytearray(b"s" * 32)
                issued_buffers.append(value)
                return value

        channel = Channel()

        def channel_factory():
            calls["factory"] += 1
            return channel

        class AtomicResultService:
            def __init__(self, secret_resolver):
                self.secret_resolver = secret_resolver

            def accept_result(
                self,
                task_id,
                result_value,
                *,
                request,
                principal,
                data_dir=None,
            ):
                secret = self.secret_resolver(
                    request["capability_id"]
                )
                self.consumed_secret = secret
                try:
                    return {
                        "task_id": task_id,
                        "revision": 8,
                        "event_id": "event-result-1",
                        "event_type": (
                            "orchestration_result_accepted"
                        ),
                        "authorization_id": "authorization-1",
                        "payload": {},
                    }
                finally:
                    for index in range(len(secret)):
                        secret[index] = 0

        module = load_service_namespace(
            manager_secret_channel_from_environment=channel_factory,
            orchestration_controller_service=(
                lambda *, secret_resolver, clock_id: AtomicResultService(
                    secret_resolver
                )
            ),
            MANAGER_CAPABILITY_CLOCK_ID="test-clock/v1",
        )
        service = module.create_mcp_controller_service(
            data_dir="/data"
        )
        identity = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": "capability-1",
            "task_id": "task-1",
            "manager_session_id": "manager-1",
            "action_id": "worker-result.submit/v1",
            "expected_revision": 7,
            "request_nonce": "3" * 64,
        }

        service.dispatch_mcp_tool(
            request(
                "worker-result",
                {
                    "contract": "dev-flow-mcp-worker-result/v1",
                    "task_id": "task-1",
                    "expected_revision": 7,
                    "request_identity": identity,
                    "result": {
                        "schema": "dev-flow-node-result/v1",
                        "result_id": "node-result-" + "4" * 64,
                    },
                },
            )
        )

        self.assertEqual(calls, {
            "factory": 1,
            "principal": 1,
            "secret": 1,
        })
        self.assertEqual(
            issued_buffers, [bytearray(b"\x00" * 32)]
        )
        self.assertIs(
            service._orchestration_service.consumed_secret,
            issued_buffers[0],
        )

    def test_action_apply_receives_the_factory_channel_and_principal(
        self,
    ) -> None:
        calls = {"factory": 0, "principal": 0, "secret": 0}
        issued_buffers = []
        observed = {}

        class Channel:
            def principal_for(self, request_identity):
                calls["principal"] += 1
                return {
                    "schema": "dev-flow-agent-principal/v1",
                    "role": "manager",
                    "session_id": request_identity[
                        "manager_session_id"
                    ],
                    "os_user_identity_sha256": "1" * 64,
                    "host_identity_sha256": "2" * 64,
                }

            def resolve_secret(self, _capability_id):
                calls["secret"] += 1
                value = bytearray(b"s" * 32)
                issued_buffers.append(value)
                return value

        channel = Channel()

        def channel_factory():
            calls["factory"] += 1
            return channel

        def apply_action(
            task_id,
            *,
            expected_revision,
            action_id,
            input_value,
            preview_intent,
            request,
            principal,
            manager_channel,
            data_dir=None,
        ):
            observed.update(
                {
                    "task_id": task_id,
                    "principal": principal,
                    "manager_channel": manager_channel,
                    "data_dir": data_dir,
                }
            )
            secret = manager_channel.resolve_secret(
                request["capability_id"]
            )
            try:
                return {
                    "revision": expected_revision + 1,
                    "event_id": "event-action-1",
                    "event_type": "state_transitioned",
                    "authorization_id": "authorization-1",
                }
            finally:
                for index in range(len(secret)):
                    secret[index] = 0

        module = load_service_namespace(
            controller_action_apply=apply_action,
            manager_secret_channel_from_environment=channel_factory,
        )
        service = module.create_mcp_controller_service(
            data_dir="/data"
        )
        identity = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": "capability-1",
            "task_id": "task-1",
            "manager_session_id": "manager-1",
            "action_id": "transition",
            "expected_revision": 7,
            "request_nonce": "3" * 64,
        }

        value = service.dispatch_mcp_tool(
            request(
                "action-apply",
                {
                    "contract": "dev-flow-mcp-action-apply/v1",
                    "task_id": "task-1",
                    "expected_revision": 7,
                    "action_id": "transition",
                    "preview_intent": "intent-1",
                    "request_identity": identity,
                    "input": {
                        "contract": (
                            "dev-flow-action-transition-input/v1"
                        ),
                        "to": "VERIFYING",
                        "note": None,
                    },
                },
            )
        )

        self.assertEqual(
            value["contract"],
            "dev-flow-mcp-action-apply-result/v1",
        )
        self.assertIs(observed["manager_channel"], channel)
        self.assertEqual(
            observed["principal"],
            {
                "schema": "dev-flow-agent-principal/v1",
                "role": "manager",
                "session_id": "manager-1",
                "os_user_identity_sha256": "1" * 64,
                "host_identity_sha256": "2" * 64,
            },
        )
        self.assertEqual(
            calls, {"factory": 1, "principal": 1, "secret": 1}
        )
        self.assertEqual(
            issued_buffers, [bytearray(b"\x00" * 32)]
        )

    def test_secret_consumer_failure_zeroizes_without_disclosure(
        self,
    ) -> None:
        proof = b"proof-material-that-must-not-leak!"
        issued_buffers = []

        class Channel:
            def principal_for(self, request_identity):
                return {
                    "schema": "dev-flow-agent-principal/v1",
                    "role": "manager",
                    "session_id": request_identity[
                        "manager_session_id"
                    ],
                    "os_user_identity_sha256": "1" * 64,
                    "host_identity_sha256": "2" * 64,
                }

            def resolve_secret(self, _capability_id):
                value = bytearray(proof)
                issued_buffers.append(value)
                return value

        class FailingConsumer:
            def __init__(self, secret_resolver):
                self.secret_resolver = secret_resolver

            def accept_result(
                self,
                _task_id,
                _result_value,
                *,
                request,
                principal,
                data_dir=None,
            ):
                secret = self.secret_resolver(
                    request["capability_id"]
                )
                try:
                    raise RuntimeError(secret.decode("ascii"))
                finally:
                    for index in range(len(secret)):
                        secret[index] = 0

        module = load_service_namespace(
            manager_secret_channel_from_environment=lambda: Channel(),
            orchestration_controller_service=(
                lambda *, secret_resolver, clock_id: FailingConsumer(
                    secret_resolver
                )
            ),
            MANAGER_CAPABILITY_CLOCK_ID="test-clock/v1",
        )
        service = module.create_mcp_controller_service()
        identity = {
            "schema": "dev-flow-manager-capability-request/v1",
            "capability_id": "capability-1",
            "task_id": "task-1",
            "manager_session_id": "manager-1",
            "action_id": "worker-result.submit/v1",
            "expected_revision": 7,
            "request_nonce": "3" * 64,
        }

        with self.assertRaises(
            module.McpControllerServiceError
        ) as raised:
            service.dispatch_mcp_tool(
                request(
                    "worker-result",
                    {
                        "contract": (
                            "dev-flow-mcp-worker-result/v1"
                        ),
                        "task_id": "task-1",
                        "expected_revision": 7,
                        "request_identity": identity,
                        "result": {
                            "schema": "dev-flow-node-result/v1",
                            "result_id": (
                                "node-result-" + "4" * 64
                            ),
                        },
                    },
                )
            )

        self.assertEqual(
            issued_buffers, [bytearray(b"\x00" * len(proof))]
        )
        serialized = json.dumps(
            {
                "code": raised.exception.code,
                "message": raised.exception.message,
                "details": raised.exception.details,
            },
            sort_keys=True,
        ).encode("utf-8")
        self.assertNotIn(proof, serialized)


if __name__ == "__main__":
    unittest.main()
