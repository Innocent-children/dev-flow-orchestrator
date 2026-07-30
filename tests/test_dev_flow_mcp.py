from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import io
import json
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Tuple
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MCP_PATH = ROOT / "scripts" / "dev_flow_mcp.py"
FIXTURES = ROOT / "tests" / "fixtures" / "mcp"
SPEC = importlib.util.spec_from_file_location(
    "dev_flow_mcp_test_module", MCP_PATH
)
assert SPEC is not None and SPEC.loader is not None
mcp = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mcp
SPEC.loader.exec_module(mcp)
RESULT_SPEC = importlib.util.spec_from_file_location(
    "dev_flow_mcp_authoritative_results",
    ROOT
    / "scripts"
    / "dev_flow_parts"
    / "orchestration_results.py",
)
assert RESULT_SPEC is not None and RESULT_SPEC.loader is not None
orchestration_results = importlib.util.module_from_spec(RESULT_SPEC)
sys.modules[RESULT_SPEC.name] = orchestration_results
RESULT_SPEC.loader.exec_module(orchestration_results)


def fixture(name: str) -> dict:
    return json.loads(
        (FIXTURES / name).read_text(encoding="utf-8")
    )


def rpc_request(
    request_id: object,
    method: str,
    params: object,
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


class RecordingControllerService:
    """Small durable-service double; protocol idempotency stays downstream."""

    def __init__(self, *, role: str = "manager") -> None:
        self.role = role
        self.calls: list[dict] = []
        self.commits = 0
        self.outcomes: dict[str, tuple[str, dict]] = {}

    def dispatch_mcp_tool(self, request: dict) -> dict:
        copied = copy.deepcopy(request)
        self.calls.append(copied)
        tool = request["tool"]
        arguments = request["arguments"]
        if tool in {"action-apply", "worker-result"}:
            if self.role != "manager":
                raise mcp.ControllerServiceError(
                    "MANAGER_REQUIRED",
                    "only the designated manager may mutate controller state",
                )
            identity = request["request_identity"]
            nonce = identity["request_nonce"]
            fingerprint = hashlib.sha256(
                mcp.canonical_json_bytes(arguments)
            ).hexdigest()
            prior = self.outcomes.get(nonce)
            if prior is not None:
                prior_fingerprint, prior_value = prior
                if prior_fingerprint != fingerprint:
                    raise mcp.ControllerServiceError(
                        "MANAGER_CAPABILITY_REPLAY",
                        "request nonce was reused with different content",
                    )
                return copy.deepcopy(prior_value)
            self.commits += 1
            if tool == "action-apply":
                value = {
                    "contract": (
                        "dev-flow-mcp-action-apply-result/v1"
                    ),
                    "task_id": arguments["task_id"],
                    "action_id": arguments["action_id"],
                    "preview_intent": arguments["preview_intent"],
                    "revision": arguments["expected_revision"] + 1,
                    "event_id": f"event-{self.commits}",
                    "event_type": "test_action_applied",
                    "authorization_id": f"authorization-{self.commits}",
                }
            else:
                value = {
                    "contract": (
                        "dev-flow-worker-result-acceptance/v1"
                    ),
                    "task_id": arguments["task_id"],
                    "result_id": arguments["result"]["result_id"],
                    "revision": arguments["expected_revision"] + 1,
                    "event_id": f"event-{self.commits}",
                    "event_type": "test_worker_result_accepted",
                    "authorization_id": f"authorization-{self.commits}",
                }
            self.outcomes[nonce] = (fingerprint, copy.deepcopy(value))
            return value
        if tool == "task-next":
            condition = {"kind": "ready"}
            return {
                "contract": "agent-v1",
                "task_id": arguments["task_id"],
                "revision": arguments.get("known_revision", 7),
                "workflow": {
                    "id": "full",
                    "version": 3,
                    "schema": "dev-flow-workflow/v1",
                    "graph_sha256": "1" * 64,
                    "bundle_sha256": "2" * 64,
                },
                "frontier": [],
                "actions": [],
                "frontier_sha256": hashlib.sha256(
                    mcp.canonical_json_bytes(
                        {
                            "frontier": [],
                            "actions": [],
                            "condition": condition,
                        }
                    )
                ).hexdigest(),
                "condition": condition,
            }
        if tool == "node-description":
            return {
                "contract": "dev-flow-node-description/v1",
                "workflow": {
                    "id": "full",
                    "version": 3,
                    "schema": "dev-flow-workflow/v1",
                    "graph_sha256": "1" * 64,
                    "bundle_sha256": "2" * 64,
                },
                "node": {"id": arguments["node_id"]},
                "legal_actions": [],
                "playbook": {},
            }
        if tool == "evidence-read":
            evidence_id = arguments["evidence_id"]
            digest = hashlib.sha256(b"{}").hexdigest()
            return {
                "contract": "dev-flow-evidence-projection/v1",
                "task_id": arguments["task_id"],
                "revision": 7,
                "evidence_id": evidence_id,
                "reference": {
                    "schema": "dev-flow-artifact-reference/v1",
                    "artifact_id": evidence_id,
                    "task_id": arguments["task_id"],
                    "semantic_sha256": digest,
                    "sha256": digest,
                    "size": 2,
                    "media_type": "application/json",
                    "kind": "test",
                    "locator": "artifacts/test.json",
                },
                "inline": True,
                "content_encoding": "base64",
                "content_base64": "e30=",
            }
        assert tool == "action-preview"
        input_value = arguments.get("input", {})
        return {
            "contract": "dev-flow-mcp-action-preview-result/v1",
            "task_id": arguments["task_id"],
            "revision": arguments["expected_revision"],
            "action_id": arguments["action_id"],
            "input_sha256": hashlib.sha256(
                mcp.canonical_json_bytes(input_value)
            ).hexdigest(),
            "preview_intent": "intent-1",
            "applicable": True,
            "blockers": [],
        }


class FailingControllerService:
    def dispatch_mcp_tool(self, _request: dict) -> dict:
        raise mcp.ControllerServiceError(
            "CONTROLLER_REJECTED",
            "x" * 4000,
            details={
                "manager_secret": "do-not-disclose",
                "nested": {"proof": "also-secret"},
                "noise": "y" * 10000,
            },
        )


class DevFlowMcpTests(unittest.TestCase):
    def initialized_server(
        self,
        service: Optional[object] = None,
        *,
        enabled_tools: Optional[Tuple[str, ...]] = None,
    ):
        server = mcp.McpServer(
            service or RecordingControllerService(),
            enabled_tools=enabled_tools,
        )
        init = fixture("initialize.json")["request"]
        response = server.handle_message(init)
        self.assertIsNotNone(response)
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        return server

    def call(self, server, name: str, arguments: dict, request_id=9):
        return server.handle_message(
            rpc_request(
                request_id,
                "tools/call",
                {"name": name, "arguments": arguments},
            )
        )

    def test_versioned_initialization_fixture(self) -> None:
        document = fixture("initialize.json")
        server = mcp.McpServer(RecordingControllerService())

        response = server.handle_message(document["request"])

        expected = document["expected"]
        self.assertEqual(
            response["result"]["protocolVersion"],
            expected["protocolVersion"],
        )
        self.assertEqual(
            response["result"]["serverInfo"]["name"],
            expected["serverName"],
        )
        self.assertEqual(
            response["result"]["capabilities"]["tools"][
                "listChanged"
            ],
            expected["toolsListChanged"],
        )
        before_ready = server.handle_message(
            rpc_request(2, "tools/list", {})
        )
        self.assertEqual(
            before_ready["error"]["data"]["code"],
            "SERVER_NOT_INITIALIZED",
        )

    def test_tool_listing_fixture_has_strict_schemas_and_annotations(
        self,
    ) -> None:
        document = fixture("tool-list.json")
        server = self.initialized_server()

        response = server.handle_message(document["request"])
        tools = response["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}

        self.assertEqual(
            [tool["name"] for tool in tools],
            document["expectedNames"],
        )
        for name in document["readOnly"]:
            self.assertTrue(
                by_name[name]["annotations"]["readOnlyHint"]
            )
        for name in document["write"]:
            self.assertFalse(
                by_name[name]["annotations"]["readOnlyHint"]
            )
        for name, tool in by_name.items():
            self.assertEqual(
                tool["inputSchema"]["additionalProperties"], False
            )
            self.assertEqual(
                tool["outputSchema"]["additionalProperties"], False
            )
            self.assertFalse(
                tool["annotations"]["openWorldHint"]
            )
            value_schema = tool["outputSchema"]["properties"][
                "value"
            ]
            self.assertNotEqual(value_schema, {"type": "object"})
            branches = value_schema.get(
                "oneOf", [value_schema]
            )
            self.assertTrue(branches)
            self.assertTrue(
                all(
                    branch.get("additionalProperties") is False
                    for branch in branches
                )
            )
            self.assertEqual(
                tool["annotations"]["destructiveHint"],
                name in document["destructive"],
            )
        self.assertFalse(
            by_name["action-apply"]["inputSchema"]["properties"][
                "request_identity"
            ]["additionalProperties"]
        )
        self.assertFalse(
            by_name["worker-result"]["inputSchema"]["properties"][
                "result"
            ]["additionalProperties"]
        )
        for name in ("action-preview", "action-apply"):
            action_input = by_name[name]["inputSchema"][
                "properties"
            ]["input"]
            self.assertEqual(len(action_input["oneOf"]), 2)
            self.assertTrue(
                all(
                    branch["additionalProperties"] is False
                    for branch in action_input["oneOf"]
                )
            )
        task_next_projection = next(
            branch
            for branch in by_name["task-next"]["outputSchema"][
                "properties"
            ]["value"]["oneOf"]
            if branch["properties"]["contract"].get("const")
            == "agent-v1"
        )
        self.assertFalse(
            task_next_projection["properties"]["revision_delta"][
                "additionalProperties"
            ]
        )

    def test_all_successful_call_fixtures_delegate_to_one_service(
        self,
    ) -> None:
        service = RecordingControllerService()
        server = self.initialized_server(service)
        cases = fixture("successful-calls.json")["cases"]

        for index, case in enumerate(cases):
            response = self.call(
                server,
                case["name"],
                case["arguments"],
                request_id=100 + index,
            )
            result = response["result"]
            self.assertFalse(result["isError"], case["name"])
            self.assertEqual(
                result["structuredContent"]["tool"], case["name"]
            )
            self.assertTrue(
                result["structuredContent"]["ok"], case["name"]
            )
        self.assertEqual(len(service.calls), len(cases))
        self.assertEqual(service.commits, 2)
        for request in service.calls:
            self.assertEqual(
                request["schema"],
                "dev-flow-controller-mcp-request/v1",
            )
            serialized = mcp.canonical_json_bytes(request)
            self.assertNotIn(b'"proof"', serialized)
            self.assertNotIn(b'"secret"', serialized)

    def test_worker_result_schema_is_the_authoritative_v1_contract(
        self,
    ) -> None:
        result = next(
            case["arguments"]["result"]
            for case in fixture("successful-calls.json")["cases"]
            if case["name"] == "worker-result"
        )

        parsed = orchestration_results.parse_node_result_json(
            mcp.canonical_json_bytes(result)
        )

        self.assertEqual(
            parsed["result_id"], result["result_id"]
        )
        self.assertEqual(
            set(result),
            set(
                orchestration_results._orchestration_node_result_fields
            ),
        )

    def test_malformed_json_fixture_is_bounded_and_non_mutating(
        self,
    ) -> None:
        document = fixture("malformed.json")
        service = RecordingControllerService()
        server = mcp.McpServer(service)

        encoded = server.process_line(
            document["input"].encode("utf-8")
        )
        response = json.loads(encoded)

        self.assertEqual(
            response["error"]["code"], document["expectedRpcCode"]
        )
        self.assertEqual(
            response["error"]["data"]["code"],
            document["expectedStableCode"],
        )
        self.assertLess(len(encoded), 1024)
        self.assertEqual(service.calls, [])

    def test_unsupported_version_fixture_fails_closed(self) -> None:
        document = fixture("unsupported-version.json")
        service = RecordingControllerService()
        server = mcp.McpServer(service)

        response = server.handle_message(document["request"])

        self.assertEqual(
            response["error"]["code"], document["expectedRpcCode"]
        )
        self.assertEqual(
            response["error"]["data"]["code"],
            document["expectedStableCode"],
        )
        self.assertEqual(service.calls, [])

    def test_disabled_tool_is_neither_discovered_nor_callable(
        self,
    ) -> None:
        document = fixture("disabled-tool.json")
        service = RecordingControllerService()
        server = self.initialized_server(
            service,
            enabled_tools=tuple(document["enabledTools"]),
        )

        listing = server.handle_message(
            rpc_request(2, "tools/list", {})
        )
        self.assertEqual(
            [tool["name"] for tool in listing["result"]["tools"]],
            document["enabledTools"],
        )
        response = server.handle_message(document["request"])

        self.assertEqual(
            response["error"]["code"], document["expectedRpcCode"]
        )
        self.assertEqual(
            response["error"]["data"]["code"],
            document["expectedStableCode"],
        )
        self.assertEqual(service.calls, [])

    def test_eof_disconnect_is_graceful_and_non_mutating(self) -> None:
        document = fixture("disconnect.json")
        service = RecordingControllerService()
        server = mcp.McpServer(service)
        payload = b"".join(
            mcp.canonical_json_bytes(message) + b"\n"
            for message in document["messages"]
        )
        output = io.BytesIO()

        exit_code = server.run_stream(io.BytesIO(payload), output)

        self.assertEqual(exit_code, document["expectedExitCode"])
        self.assertTrue(server.stopped)
        self.assertEqual(
            len(service.calls),
            document["expectedControllerCalls"],
        )
        responses = [
            json.loads(line)
            for line in output.getvalue().splitlines()
        ]
        self.assertEqual(len(responses), 1)
        self.assertIn("result", responses[0])

    def test_shutdown_then_exit_is_graceful(self) -> None:
        server = self.initialized_server()

        shutdown = server.handle_message(
            rpc_request(2, "shutdown", {})
        )
        self.assertIsNone(shutdown["result"])
        self.assertFalse(server.stopped)

        response = server.handle_message(
            {"jsonrpc": "2.0", "method": "exit", "params": {}}
        )
        self.assertIsNone(response)
        self.assertTrue(server.stopped)

    def test_cli_fallback_fixture_is_exact_and_contains_no_proof(
        self,
    ) -> None:
        document = fixture("cli-fallback.json")
        controller = ROOT / "scripts" / "dev_flow.py"
        service = mcp.UnavailableControllerService(
            controller, "/plugin-data"
        )
        server = self.initialized_server(service)

        response = self.call(
            server, document["tool"], document["arguments"]
        )
        result = response["result"]
        structured = result["structuredContent"]

        self.assertTrue(result["isError"])
        self.assertEqual(
            structured["error"]["code"],
            document["expectedErrorCode"],
        )
        self.assertEqual(
            structured["fallback"]["arguments"],
            document["expectedArguments"],
        )
        self.assertEqual(
            structured["fallback"]["controller"],
            str(controller),
        )
        serialized = mcp.canonical_json_bytes(structured)
        self.assertNotIn(b"manager_secret", serialized)
        self.assertNotIn(b"request_nonce", serialized)

    def test_write_tools_require_bound_public_request_identity(
        self,
    ) -> None:
        service = RecordingControllerService()
        server = self.initialized_server(service)
        arguments = copy.deepcopy(
            next(
                case["arguments"]
                for case in fixture("successful-calls.json")["cases"]
                if case["name"] == "action-apply"
            )
        )
        arguments.pop("request_identity")

        missing = self.call(server, "action-apply", arguments)
        self.assertEqual(
            missing["error"]["data"]["code"], "MISSING_FIELD"
        )

        arguments["request_identity"] = copy.deepcopy(
            next(
                case["arguments"]["request_identity"]
                for case in fixture("successful-calls.json")["cases"]
                if case["name"] == "action-apply"
            )
        )
        arguments["request_identity"]["task_id"] = "other-task"
        mismatch = self.call(server, "action-apply", arguments)
        self.assertEqual(
            mismatch["error"]["data"]["code"],
            "MANAGER_REQUEST_TASK_MISMATCH",
        )
        self.assertEqual(service.calls, [])

    def test_worker_principal_cannot_commit_mutations(self) -> None:
        service = RecordingControllerService(role="worker")
        server = self.initialized_server(service)
        case = next(
            case
            for case in fixture("successful-calls.json")["cases"]
            if case["name"] == "worker-result"
        )

        response = self.call(
            server, case["name"], case["arguments"]
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "MANAGER_REQUIRED",
        )
        self.assertEqual(service.commits, 0)

    def test_lost_response_retry_cannot_double_commit(self) -> None:
        document = fixture("lost-response.json")
        service = RecordingControllerService()
        first_server = self.initialized_server(service)

        first_response = self.call(
            first_server, document["tool"], document["arguments"]
        )
        self.assertFalse(first_response["result"]["isError"])
        # Simulate a transport loss by deliberately discarding first_response.

        retry_server = self.initialized_server(service)
        retry_response = self.call(
            retry_server, document["tool"], document["arguments"]
        )

        self.assertFalse(retry_response["result"]["isError"])
        first_value = first_response["result"]["structuredContent"][
            "value"
        ]
        retry_value = retry_response["result"]["structuredContent"][
            "value"
        ]
        self.assertEqual(retry_value, first_value)
        self.assertEqual(
            retry_value["event_id"],
            "event-1",
        )
        self.assertEqual(
            retry_value["authorization_id"], "authorization-1"
        )
        self.assertEqual(
            service.commits, document["expectedCommitCount"]
        )

    def test_worker_result_lost_response_retry_preserves_receipt(
        self,
    ) -> None:
        case = next(
            item
            for item in fixture("successful-calls.json")["cases"]
            if item["name"] == "worker-result"
        )
        service = RecordingControllerService()
        first = self.call(
            self.initialized_server(service),
            case["name"],
            case["arguments"],
        )
        retry = self.call(
            self.initialized_server(service),
            case["name"],
            case["arguments"],
            request_id=10,
        )

        self.assertFalse(first["result"]["isError"])
        self.assertFalse(retry["result"]["isError"])
        self.assertEqual(
            retry["result"]["structuredContent"]["value"],
            first["result"]["structuredContent"]["value"],
        )
        self.assertEqual(service.commits, 1)
        self.assertEqual(
            retry["result"]["structuredContent"]["value"][
                "authorization_id"
            ],
            "authorization-1",
        )

    def test_same_nonce_with_different_body_is_replay_conflict(
        self,
    ) -> None:
        document = fixture("lost-response.json")
        service = RecordingControllerService()
        server = self.initialized_server(service)
        self.call(server, document["tool"], document["arguments"])
        conflicting = copy.deepcopy(document["arguments"])
        conflicting["preview_intent"] = "different-intent"

        response = self.call(
            server, document["tool"], conflicting, request_id=10
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "MANAGER_CAPABILITY_REPLAY",
        )
        self.assertEqual(service.commits, 1)

    def test_service_errors_are_bounded_and_secret_redacted(
        self,
    ) -> None:
        server = self.initialized_server(FailingControllerService())
        case = fixture("successful-calls.json")["cases"][0]

        response = self.call(
            server, case["name"], case["arguments"]
        )
        encoded = mcp.canonical_json_bytes(response)

        self.assertTrue(response["result"]["isError"])
        self.assertLessEqual(len(encoded), mcp.MAX_RESPONSE_BYTES)
        self.assertNotIn(b"do-not-disclose", encoded)
        self.assertNotIn(b"also-secret", encoded)
        self.assertIn(b"[REDACTED]", encoded)

    def test_output_budget_failure_is_structured_not_truncated(
        self,
    ) -> None:
        class OversizedService:
            def dispatch_mcp_tool(self, request):
                condition = {
                    "required": "z"
                    * (mcp.MAX_TOOL_VALUE_BYTES + 1)
                }
                return {
                    "contract": "agent-v1",
                    "task_id": request["arguments"]["task_id"],
                    "revision": 1,
                    "workflow": {
                        "id": "full",
                        "version": 3,
                        "schema": "dev-flow-workflow/v1",
                        "graph_sha256": "1" * 64,
                        "bundle_sha256": "2" * 64,
                    },
                    "frontier": [],
                    "actions": [],
                    "frontier_sha256": hashlib.sha256(
                        mcp.canonical_json_bytes(
                            {
                                "frontier": [],
                                "actions": [],
                                "condition": condition,
                            }
                        )
                    ).hexdigest(),
                    "condition": condition,
                }

        server = self.initialized_server(OversizedService())
        case = fixture("successful-calls.json")["cases"][0]

        response = self.call(
            server, case["name"], case["arguments"]
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "CONTROLLER_RESPONSE_TOO_LARGE",
        )

    def test_task_next_revision_delta_is_strictly_bound(
        self,
    ) -> None:
        class DeltaService:
            def dispatch_mcp_tool(self, request):
                condition = {"kind": "ready"}
                return {
                    "contract": "agent-v1",
                    "task_id": request["arguments"]["task_id"],
                    "revision": 3,
                    "workflow": {
                        "id": "full",
                        "version": 3,
                        "schema": "dev-flow-workflow/v1",
                        "graph_sha256": "1" * 64,
                        "bundle_sha256": "2" * 64,
                    },
                    "frontier": [],
                    "actions": [],
                    "frontier_sha256": hashlib.sha256(
                        mcp.canonical_json_bytes(
                            {
                                "frontier": [],
                                "actions": [],
                                "condition": condition,
                            }
                        )
                    ).hexdigest(),
                    "condition": condition,
                    "revision_delta": {
                        "contract": "dev-flow-task-next-delta/v1",
                        "from_revision": 1,
                        "to_revision": 3,
                        "revision_count": 2,
                        "delta_sha256": "3" * 64,
                        "reset_required": False,
                    },
                }

        server = self.initialized_server(DeltaService())
        response = self.call(
            server,
            "task-next",
            {
                "contract": "dev-flow-mcp-task-next/v1",
                "task_id": "task-1",
                "known_revision": 1,
            },
        )

        self.assertFalse(response["result"]["isError"])
        value = response["result"]["structuredContent"]["value"]
        self.assertEqual(value["revision"], 3)
        self.assertEqual(
            value["revision_delta"]["delta_sha256"], "3" * 64
        )
        self.assertLessEqual(
            len(mcp.canonical_json_bytes(value)), 1024
        )

    def test_task_next_stale_checkpoint_requires_revision_delta(
        self,
    ) -> None:
        class MissingDeltaService:
            def dispatch_mcp_tool(self, request):
                condition = {"kind": "ready"}
                return {
                    "contract": "agent-v1",
                    "task_id": request["arguments"]["task_id"],
                    "revision": 3,
                    "workflow": {
                        "id": "full",
                        "version": 3,
                        "schema": "dev-flow-workflow/v1",
                        "graph_sha256": "1" * 64,
                        "bundle_sha256": "2" * 64,
                    },
                    "frontier": [],
                    "actions": [],
                    "frontier_sha256": hashlib.sha256(
                        mcp.canonical_json_bytes(
                            {
                                "frontier": [],
                                "actions": [],
                                "condition": condition,
                            }
                        )
                    ).hexdigest(),
                    "condition": condition,
                }

        server = self.initialized_server(MissingDeltaService())
        response = self.call(
            server,
            "task-next",
            {
                "contract": "dev-flow-mcp-task-next/v1",
                "task_id": "task-1",
                "known_revision": 1,
            },
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "CONTROLLER_RESPONSE_INVALID",
        )

    def test_controller_value_contract_and_unknown_fields_are_rejected(
        self,
    ) -> None:
        class MalformedService:
            def dispatch_mcp_tool(self, request):
                condition = {"kind": "ready"}
                return {
                    "contract": "agent-v1",
                    "task_id": request["arguments"]["task_id"],
                    "revision": 1,
                    "workflow": {
                        "id": "full",
                        "version": 3,
                        "schema": "dev-flow-workflow/v1",
                        "graph_sha256": "1" * 64,
                        "bundle_sha256": "2" * 64,
                    },
                    "frontier": [],
                    "actions": [],
                    "frontier_sha256": hashlib.sha256(
                        mcp.canonical_json_bytes(
                            {
                                "frontier": [],
                                "actions": [],
                                "condition": condition,
                            }
                        )
                    ).hexdigest(),
                    "condition": condition,
                    "untrusted": True,
                }

        server = self.initialized_server(MalformedService())
        case = fixture("successful-calls.json")["cases"][0]

        response = self.call(
            server, case["name"], case["arguments"]
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "CONTROLLER_RESPONSE_INVALID",
        )

    def test_controller_preview_must_bind_canonical_action_input(
        self,
    ) -> None:
        class StalePreviewService(RecordingControllerService):
            def dispatch_mcp_tool(self, request):
                value = super().dispatch_mcp_tool(request)
                value["input_sha256"] = "0" * 64
                return value

        server = self.initialized_server(StalePreviewService())
        case = next(
            item
            for item in fixture("successful-calls.json")["cases"]
            if item["name"] == "action-preview"
        )

        response = self.call(
            server, case["name"], case["arguments"]
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "CONTROLLER_RESPONSE_INVALID",
        )

    def test_controller_evidence_inline_bytes_must_match_reference(
        self,
    ) -> None:
        class CorruptEvidenceService(RecordingControllerService):
            def dispatch_mcp_tool(self, request):
                value = super().dispatch_mcp_tool(request)
                value["content_base64"] = "e1td"
                return value

        server = self.initialized_server(CorruptEvidenceService())
        case = next(
            item
            for item in fixture("successful-calls.json")["cases"]
            if item["name"] == "evidence-read"
        )

        response = self.call(
            server, case["name"], case["arguments"]
        )

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["error"]["code"],
            "CONTROLLER_RESPONSE_INVALID",
        )

    def test_malformed_cli_fallback_is_not_surfaced(
        self,
    ) -> None:
        class MaliciousFallbackService:
            def dispatch_mcp_tool(self, _request):
                raise mcp.ControllerServiceError(
                    "CONTROLLER_SERVICE_UNAVAILABLE",
                    "controller unavailable",
                    fallback={
                        "schema": "dev-flow-cli-fallback/v1",
                        "controller": str(
                            ROOT / "scripts" / "dev_flow.py"
                        ),
                        "data_dir": "/plugin-data",
                        "arguments": [
                            "show",
                            "--proof",
                            "do-not-disclose",
                        ],
                    },
                )

        server = self.initialized_server(
            MaliciousFallbackService()
        )
        case = fixture("successful-calls.json")["cases"][0]

        response = self.call(
            server, case["name"], case["arguments"]
        )
        structured = response["result"]["structuredContent"]

        self.assertTrue(response["result"]["isError"])
        self.assertNotIn("fallback", structured)
        self.assertNotIn(
            b"do-not-disclose",
            mcp.canonical_json_bytes(response),
        )

    def test_environment_tool_filter_is_exact(self) -> None:
        self.assertEqual(
            mcp._enabled_tools_from_environment(
                {
                    "DEV_FLOW_MCP_ENABLED_TOOLS": (
                        "task-next,evidence-read"
                    )
                }
            ),
            ("task-next", "evidence-read"),
        )
        with self.assertRaises(ValueError):
            mcp.McpServer(
                RecordingControllerService(),
                enabled_tools=("unknown",),
            )

    def test_package_controller_service_loads_real_factory_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )

            first = adapter._load(None)
            second = adapter._load(None)

            self.assertIs(first, second)
            self.assertTrue(
                callable(getattr(first, "dispatch_mcp_tool", None))
            )

    def test_package_controller_service_uses_runtime_adapter_boundary(
        self,
    ) -> None:
        calls = []

        class LoadedModule:
            pass

        class Service:
            def dispatch_mcp_tool(self, _request):
                return {}

        service = Service()

        def runtime_factory(*, data_dir=None):
            calls.append(("runtime-adapter", data_dir))
            return service

        def forbidden_direct_factory(**_kwargs):
            raise AssertionError("direct facade factory must not be used")

        class Adapters:
            create_mcp_controller_service = staticmethod(runtime_factory)

        class Runtime:
            adapters = Adapters()

        class Loader:
            def exec_module(self, module):
                module.create_mcp_controller_service = (
                    forbidden_direct_factory
                )
                module.workflow_runtime_services = lambda: Runtime()

        class Spec:
            name = "_dev_flow_mcp_controller_boundary_test"
            loader = Loader()

        loaded_module = LoadedModule()
        with (
            tempfile.TemporaryDirectory() as data_dir,
            mock.patch.object(
                mcp.importlib.util,
                "spec_from_file_location",
                return_value=Spec(),
            ),
            mock.patch.object(
                mcp.importlib.util,
                "module_from_spec",
                return_value=loaded_module,
            ),
        ):
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            observed = adapter._load(None)

        self.assertIs(observed, service)
        self.assertEqual(calls, [("runtime-adapter", data_dir)])
        sys.modules.pop(Spec.name, None)

    def test_packaged_factory_reaches_domain_service(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            service = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            server = self.initialized_server(service)

            response = self.call(
                server,
                "task-next",
                {
                    "contract": "dev-flow-mcp-task-next/v1",
                    "task_id": "missing-task",
                },
            )

            self.assertTrue(response["result"]["isError"])
            self.assertNotEqual(
                response["result"]["structuredContent"]["error"][
                    "code"
                ],
                "CONTROLLER_SERVICE_UNAVAILABLE",
            )

    def test_packaged_factory_binds_real_worker_service_once(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            adapter._load(None)
            controller = sys.modules["_dev_flow_mcp_controller"]
            calls = {"factory": 0, "principal": 0, "secret": 0}

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
                    return bytearray(b"s" * 32)

            channel = Channel()

            def channel_factory():
                calls["factory"] += 1
                return channel

            service = controller.create_mcp_controller_service(
                data_dir=data_dir,
                manager_channel_factory=channel_factory,
            )
            server = self.initialized_server(service)
            case = next(
                item
                for item in fixture("successful-calls.json")[
                    "cases"
                ]
                if item["name"] == "worker-result"
            )

            response = self.call(
                server, case["name"], case["arguments"]
            )

            self.assertTrue(response["result"]["isError"])
            self.assertNotIn(
                response["result"]["structuredContent"]["error"][
                    "code"
                ],
                {
                    "CONTROLLER_SERVICE_UNAVAILABLE",
                    "MCP_WORKER_RESULT_SERVICE_UNAVAILABLE",
                },
            )
            self.assertIsInstance(
                service._orchestration_service,
                controller.OrchestrationControllerService,
            )
            # Missing task state fails before proof resolution. This still
            # proves that one channel supplied the authenticated principal
            # and that the real atomic worker service was reached.
            self.assertEqual(
                calls, {"factory": 1, "principal": 1, "secret": 0}
            )

    def test_packaged_worker_service_rejects_before_resolving_channel_secret(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            adapter._load(None)
            controller = sys.modules["_dev_flow_mcp_controller"]
            task_id = "mcp-worker-binding"
            bundle = controller._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
                ("full", 3)
            ]
            state = {
                "schema_version": 3,
                "confirmation_contract_version": 1,
                "task_id": task_id,
                "revision": 0,
                "status": "INTAKE",
                "flow": "full",
                **controller.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="multi-repository",
                ),
            }
            secret = b"s" * 32
            verifier = controller.issue_manager_capability(
                task_id=task_id,
                issued_for_task_revision=0,
                manager_session_id="manager-1",
                allowed_actions=(
                    controller.ORCHESTRATION_ACTION_RESULT_ACCEPT,
                ),
                ttl_ns=60 * 1_000_000_000,
                wall_time_ns=time.time_ns(),
                monotonic_time_ns=(
                    controller._manager_system_monotonic_ns()
                ),
                clock_id=controller.MANAGER_CAPABILITY_CLOCK_ID,
                secret_transport="local-secret-channel",
                operator_confirmation_sha256="a" * 64,
                issuance_audit_sha256="b" * 64,
                manager_secret=secret,
            )
            orchestration = controller._osc_state_copy(state)
            orchestration["expansion"] = {
                "schema": "dev-flow-repository-map-expansion/v1",
                "task_id": task_id,
                "workflow_bundle_sha256": state["workflow_ref"][
                    "bundle_sha256"
                ],
                "plan_id": "test-plan",
                "dag_sha256": "3" * 64,
                "semantic_input_sha256": "4" * 64,
                "map_node_id": "map.repositories/v1",
                "map_epoch": 1,
                "repository_set": [],
                "current": True,
                "children": [],
            }
            orchestration["manager_capabilities"][
                verifier.capability_id
            ] = verifier.as_persistent_dict()
            state["orchestration"] = orchestration
            task_dir = Path(data_dir) / "tasks" / task_id
            task_dir.mkdir(parents=True)
            state_path = task_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    state,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            before_state = state_path.read_bytes()
            issued_buffers = []
            calls = {"factory": 0, "principal": 0, "secret": 0}

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

                def resolve_secret(self, capability_id):
                    self.assert_capability = capability_id
                    calls["secret"] += 1
                    value = bytearray(secret)
                    issued_buffers.append(value)
                    return value

            channel = Channel()

            def channel_factory():
                calls["factory"] += 1
                return channel

            service = controller.create_mcp_controller_service(
                data_dir=data_dir,
                manager_channel_factory=channel_factory,
            )
            server = self.initialized_server(service)
            case = copy.deepcopy(
                next(
                    item
                    for item in fixture("successful-calls.json")[
                        "cases"
                    ]
                    if item["name"] == "worker-result"
                )
            )
            arguments = case["arguments"]
            arguments["task_id"] = task_id
            arguments["expected_revision"] = 0
            arguments["request_identity"].update(
                {
                    "capability_id": verifier.capability_id,
                    "task_id": task_id,
                    "expected_revision": 0,
                    "request_nonce": "d" * 64,
                }
            )
            arguments["result"]["task_id"] = task_id
            arguments["result"]["workflow_bundle_sha256"] = (
                state["workflow_ref"]["bundle_sha256"]
            )
            # Keep the candidate structurally valid. The atomic service must
            # reject the missing assignment before resolving manager secret
            # material.
            result_payload = {
                key: value
                for key, value in arguments["result"].items()
                if key != "result_id"
            }
            arguments["result"] = (
                orchestration_results._orchestration_thaw(
                    orchestration_results.bind_node_result_identity(
                        result_payload
                    )
                )
            )

            response = self.call(
                server, case["name"], arguments
            )

            self.assertTrue(response["result"]["isError"])
            self.assertEqual(
                calls, {"factory": 1, "principal": 1, "secret": 0}
            )
            self.assertFalse(hasattr(channel, "assert_capability"))
            self.assertEqual(issued_buffers, [])
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertFalse((task_dir / "events.jsonl").exists())
            self.assertNotIn(
                secret,
                mcp.canonical_json_bytes(response),
            )

    def test_packaged_action_lost_response_replays_one_receipt(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            adapter._load(None)
            controller = sys.modules["_dev_flow_mcp_controller"]
            task_id = "mcp-action-replay"
            bundle = controller._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
                ("full", 3)
            ]
            repository = Path(data_dir) / "repository"
            repository.mkdir()
            subprocess.run(
                ["git", "init", "-q", "-b", "main", str(repository)],
                check=True,
            )
            (repository / "tracked.txt").write_text(
                "initial\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "tracked.txt"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=Dev Flow",
                    "-c",
                    "user.email=dev-flow@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "initial",
                ],
                check=True,
            )
            services = controller.workflow_runtime_services()
            activations = []
            for frozen in services.catalog.activations:
                activation = dict(frozen)
                active = (
                    activation["workflow_id"] == "full"
                    and activation["workflow_version"] == 3
                    and activation["execution_profile"]
                    == "single-repository"
                )
                activation["active"] = active
                activation["required_suites"] = (
                    sorted(
                        {
                            *controller.WORKFLOW_V3_REQUIRED_SUITES[
                                "single-repository"
                            ],
                            *{
                                str(suite)
                                for edge in bundle.action_edges
                                for suite in edge["required_suites"]
                            },
                        }
                    )
                    if active
                    else []
                )
                activations.append(MappingProxyType(activation))
            active_services = dataclasses.replace(
                services,
                catalog=dataclasses.replace(
                    services.catalog,
                    activations=tuple(activations),
                ),
            )
            start_args = controller.build_parser().parse_args(
                [
                    "start",
                    "exercise MCP lost-response replay",
                    "--repo",
                    str(repository),
                    "--task-id",
                    task_id,
                    "--workspace-strategy",
                    "worktree",
                    "--data-dir",
                    data_dir,
                ]
            )
            with mock.patch.object(
                controller,
                "_workflow_runtime_services",
                active_services,
            ):
                start_args.handler(start_args)
            task_dir = Path(data_dir) / "tasks" / task_id
            state_path = task_dir / "state.json"
            state = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            revision = int(state["revision"])
            secret = b"a" * 32
            verifier = controller.issue_manager_capability(
                task_id=task_id,
                issued_for_task_revision=revision,
                manager_session_id="manager-1",
                allowed_actions=("transition",),
                ttl_ns=60 * 1_000_000_000,
                wall_time_ns=time.time_ns(),
                monotonic_time_ns=(
                    controller._manager_system_monotonic_ns()
                ),
                clock_id=controller.MANAGER_CAPABILITY_CLOCK_ID,
                secret_transport="local-secret-channel",
                operator_confirmation_sha256="a" * 64,
                issuance_audit_sha256="b" * 64,
                manager_secret=secret,
            )
            state["orchestration"] = {
                "schema": "dev-flow-orchestration-state/v1",
                "manager_capabilities": {
                    verifier.capability_id: (
                        verifier.as_persistent_dict()
                    )
                },
            }
            state_path.write_text(
                json.dumps(
                    state,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            issued_buffers = []
            calls = {"factory": 0, "principal": 0, "secret": 0}

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

                def resolve_secret(self, capability_id):
                    self.last_capability_id = capability_id
                    calls["secret"] += 1
                    value = bytearray(secret)
                    issued_buffers.append(value)
                    return value

            channel = Channel()

            def channel_factory():
                calls["factory"] += 1
                return channel

            service = controller.create_mcp_controller_service(
                data_dir=data_dir,
                manager_channel_factory=channel_factory,
            )
            # Keep the package adapter in the call path so package-domain
            # failures are translated into the public MCP error contract.
            adapter._loaded = service
            input_value = {
                "contract": "dev-flow-action-transition-input/v1",
                "to": "BLOCKED",
                "note": "waiting for operator evidence",
            }
            preview_arguments = {
                "contract": "dev-flow-mcp-action-preview/v1",
                "task_id": task_id,
                "expected_revision": revision,
                "action_id": "transition",
                "input": input_value,
            }
            preview_response = self.call(
                self.initialized_server(adapter),
                "action-preview",
                preview_arguments,
            )
            self.assertFalse(
                preview_response["result"]["isError"],
                preview_response,
            )
            preview = preview_response["result"][
                "structuredContent"
            ]["value"]
            self.assertTrue(preview["applicable"], preview)
            identity = {
                "schema": "dev-flow-manager-capability-request/v1",
                "capability_id": verifier.capability_id,
                "task_id": task_id,
                "manager_session_id": "manager-1",
                "action_id": "transition",
                "expected_revision": revision,
                "request_nonce": "e" * 64,
            }
            apply_arguments = {
                "contract": "dev-flow-mcp-action-apply/v1",
                "task_id": task_id,
                "expected_revision": revision,
                "action_id": "transition",
                "preview_intent": preview["preview_intent"],
                "request_identity": identity,
                "input": input_value,
            }

            committed_receipts = []
            original_receipt = (
                controller._controller_action_committed_receipt
            )

            def lose_committed_response(*args, **kwargs):
                receipt = original_receipt(*args, **kwargs)
                committed_receipts.append(receipt)
                raise RuntimeError("simulated committed response loss")

            with mock.patch.object(
                controller,
                "_controller_action_committed_receipt",
                lose_committed_response,
            ):
                first = self.call(
                    self.initialized_server(adapter),
                    "action-apply",
                    apply_arguments,
                )
            self.assertTrue(first["result"]["isError"])
            self.assertEqual(
                first["result"]["structuredContent"]["error"][
                    "code"
                ],
                "MCP_CONTROLLER_SERVICE_FAILED",
            )
            state_after_first = state_path.read_bytes()
            events_path = task_dir / "events.jsonl"
            events_after_first = events_path.read_bytes()
            retry = self.call(
                self.initialized_server(adapter),
                "action-apply",
                apply_arguments,
                request_id=10,
            )

            self.assertFalse(retry["result"]["isError"])
            self.assertEqual(
                retry["result"]["structuredContent"]["value"],
                {
                    "contract": (
                        "dev-flow-mcp-action-apply-result/v1"
                    ),
                    "task_id": task_id,
                    "action_id": "transition",
                    "preview_intent": preview[
                        "preview_intent"
                    ],
                    **committed_receipts[0],
                },
            )
            self.assertEqual(
                state_path.read_bytes(), state_after_first
            )
            self.assertEqual(
                events_path.read_bytes(), events_after_first
            )
            self.assertEqual(
                calls, {"factory": 1, "principal": 4, "secret": 2}
            )
            self.assertEqual(
                issued_buffers,
                [bytearray(b"\x00" * len(secret))] * 2,
            )
            self.assertEqual(
                channel.last_capability_id, verifier.capability_id
            )

            conflict_arguments = copy.deepcopy(apply_arguments)
            conflict_arguments["input"]["note"] = (
                "different canonical request"
            )
            conflict = self.call(
                self.initialized_server(adapter),
                "action-apply",
                conflict_arguments,
                request_id=11,
            )

            self.assertTrue(conflict["result"]["isError"])
            self.assertEqual(
                conflict["result"]["structuredContent"]["error"][
                    "code"
                ],
                "MANAGER_CAPABILITY_REQUEST_REPLAY_CONFLICT",
            )
            self.assertEqual(
                state_path.read_bytes(), state_after_first
            )
            self.assertEqual(
                events_path.read_bytes(), events_after_first
            )
            self.assertEqual(
                calls, {"factory": 1, "principal": 6, "secret": 3}
            )
            self.assertEqual(
                issued_buffers,
                [bytearray(b"\x00" * len(secret))] * 3,
            )

    def test_packaged_task_next_reads_real_state_without_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            adapter._load(None)
            controller = sys.modules["_dev_flow_mcp_controller"]
            bundle = controller._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
                ("full", 3)
            ]
            creation = controller.build_v3_task_creation_fields(
                "mcp-read-task",
                bundle,
                execution_profile="single-repository",
            )
            task_dir = (
                Path(data_dir) / "tasks" / "mcp-read-task"
            )
            task_dir.mkdir(parents=True)
            state_path = task_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "task_id": "mcp-read-task",
                        "revision": 0,
                        "status": "INTAKE",
                        "flow": "full",
                        **creation,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            before_state = state_path.read_bytes()
            events_path = task_dir / "events.jsonl"

            value = adapter.dispatch_mcp_tool(
                {
                    "schema": "dev-flow-controller-mcp-request/v1",
                    "tool": "task-next",
                    "arguments": {
                        "contract": "dev-flow-mcp-task-next/v1",
                        "task_id": "mcp-read-task",
                    },
                    "request_identity": None,
                }
            )

            self.assertEqual(value["contract"], "agent-v1")
            self.assertLessEqual(
                len(mcp.canonical_json_bytes(value)), 1024
            )
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertFalse(events_path.exists())

    def test_packaged_task_next_reads_real_revision_delta(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            adapter = mcp.PackageControllerService(
                plugin_root=ROOT,
                data_dir=data_dir,
            )
            adapter._load(None)
            controller = sys.modules["_dev_flow_mcp_controller"]
            bundle = controller._WORKFLOW_RUNTIME_SERVICES.catalog.bundles[
                ("full", 3)
            ]
            task_id = "mcp-delta-task"
            creation = controller.build_v3_task_creation_fields(
                task_id,
                bundle,
                execution_profile="single-repository",
            )
            task_dir = Path(data_dir) / "tasks" / task_id
            task_dir.mkdir(parents=True)
            state_path = task_dir / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "task_id": task_id,
                        "revision": 2,
                        "status": "INTAKE",
                        "flow": "full",
                        **creation,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            events_path = task_dir / "events.jsonl"
            events = (
                {
                    "event_id": "event-1",
                    "task_id": task_id,
                    "type": "state_transitioned",
                    "previous_revision": 0,
                    "revision": 1,
                    "payload": {"step": 1},
                },
                {
                    "event_id": "event-2",
                    "task_id": task_id,
                    "type": "gate_approved",
                    "previous_revision": 1,
                    "revision": 2,
                    "payload": {"step": 2},
                },
            )
            events_path.write_text(
                "".join(
                    json.dumps(
                        event,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                    for event in events
                ),
                encoding="utf-8",
            )
            before_state = state_path.read_bytes()
            before_events = events_path.read_bytes()

            response = self.call(
                self.initialized_server(adapter),
                "task-next",
                {
                    "contract": "dev-flow-mcp-task-next/v1",
                    "task_id": task_id,
                    "known_revision": 0,
                },
            )

            self.assertFalse(response["result"]["isError"])
            value = response["result"]["structuredContent"]["value"]
            self.assertEqual(value["revision"], 2)
            self.assertEqual(
                value["revision_delta"]["revision_count"], 2
            )
            self.assertFalse(
                value["revision_delta"]["reset_required"]
            )
            self.assertLessEqual(
                len(mcp.canonical_json_bytes(value)), 1024
            )
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(events_path.read_bytes(), before_events)


if __name__ == "__main__":
    unittest.main()
