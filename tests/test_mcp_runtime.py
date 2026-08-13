from __future__ import annotations

import argparse
import ast
import asyncio
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import MCPServer
from mcp.types import CallToolResult
from jsonschema import Draft202012Validator

from dev_flow_orchestrator import assurance as assurance_module
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator import cli as cli_module
from dev_flow_orchestrator import git_client as git_client_module
from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.mcp.application import MCPApplication
from dev_flow_orchestrator.mcp.catalog import catalog_digest, canonical_tool_projection
from dev_flow_orchestrator.mcp.concurrency import BoundedCoordinator
from dev_flow_orchestrator.mcp.guidance import SERVER_INSTRUCTIONS
from dev_flow_orchestrator.mcp.results import MCPRuntimeFailure
from dev_flow_orchestrator.mcp.server import create_server
from dev_flow_orchestrator.mcp import runtime as mcp_runtime
from dev_flow_orchestrator.mcp.runtime import main as mcp_main
from dev_flow_orchestrator.mcp.schemas import (
    OUTPUT_SCHEMAS,
    ResultSchemaViolation,
    validate_current_action,
)
from dev_flow_orchestrator.product import (
    DRIVER_RESULT_SCHEMA,
    IMPACT_CONFIDENCE_VALUES,
    MODEL_VERSION,
    RECEIPT_SCHEMA,
    WORKSPACE_FRESHNESS_SCHEMA,
)
from dev_flow_orchestrator.runtime_paths import resolve_managed_runtime_root
from dev_flow_orchestrator.runtime_receipt import (
    MAX_RUNTIME_RECEIPT_BYTES,
    RUNTIME_RECEIPT_SCHEMA,
    build_runtime_receipt,
    read_runtime_receipt,
    validate_runtime_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

from support import hermetic_subprocess_env, probe_subprocess_runtime_roots

EXPECTED_TOOLS = (
    "dev_flow_apply_action",
    "dev_flow_cancel_task",
    "dev_flow_dispose_finding",
    "dev_flow_find_tasks_for_path",
    "dev_flow_get_next_action",
    "dev_flow_get_task",
    "dev_flow_list_tasks",
    "dev_flow_record_decision",
    "dev_flow_revise_contract",
    "dev_flow_server_info",
    "dev_flow_start_task",
)
REQUEST_ID_PATTERN = re.compile(
    r"^mcp-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class MCPRuntimeTests(unittest.TestCase):
    def _repository(self, root: Path, name: str) -> Path:
        repository = root / name
        repository.mkdir()
        environment = hermetic_subprocess_env(root)
        subprocess.run(
            ["git", "init", "-q"], cwd=repository, env=environment, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "mcp@example.invalid"],
            cwd=repository,
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "MCP Test"],
            cwd=repository,
            env=environment,
            check=True,
        )
        (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "tracked.txt"],
            cwd=repository,
            env=environment,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-qm", "baseline"],
            cwd=repository,
            env=environment,
            check=True,
        )
        return repository

    def test_precommit_lock_timeout_has_retry_later_domain_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            application = MCPApplication(str(Path(temporary) / "data"))
            with mock.patch.object(
                application,
                "_dispatch",
                side_effect=DevFlowError(
                    "STATE_LOCK_TIMEOUT",
                    "state lock could not be acquired before the deadline",
                    details={"timeout_seconds": 30.0},
                ),
            ):
                result = application.call(
                    "dev_flow_start_task",
                    {
                        "requirement": "bounded lock",
                        "workflow": "lite",
                        "repositories": [str(Path(temporary) / "repository")],
                        "task_id": "task-lock-timeout",
                    },
                )

        self.assertTrue(result.is_error)
        error = result.structured_content["error"]
        self.assertEqual(error["code"], "STATE_LOCK_TIMEOUT")
        self.assertNotEqual(error["code"], "MCP_COMPLETION_UNCERTAIN")
        self.assertEqual(error["recovery"]["kind"], "retry-later")
        self.assertTrue(error["recovery"]["blind_retry"])
        self.assertNotIn("path", error["details"])
        self.assertNotIn(temporary, json.dumps(result.structured_content))

    def _run_cli(self, *arguments: str) -> dict:
        try:
            data_index = arguments.index("--data-dir") + 1
            fixture_root = Path(arguments[data_index]).resolve().parent
        except (ValueError, IndexError) as exc:
            raise AssertionError("CLI fixture requires an explicit temporary data root") from exc
        environment = hermetic_subprocess_env(fixture_root)
        probe_subprocess_runtime_roots(fixture_root, environment)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "dev_flow.py"), *arguments],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_catalog_is_exact_closed_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            server = create_server(data_dir)
            tools = asyncio.run(server.list_tools())
        self.assertEqual(tuple(sorted(tool.name for tool in tools)), EXPECTED_TOOLS)
        self.assertLessEqual(len(SERVER_INSTRUCTIONS.encode("utf-8")), 4 * 1024)
        self.assertLessEqual(
            len(json.dumps([tool.model_dump(by_alias=True) for tool in tools], separators=(",", ":")).encode("utf-8")),
            96 * 1024,
        )
        for tool in tools:
            self.assertIs(tool.input_schema.get("additionalProperties"), False)
            self.assertIsNotNone(tool.output_schema)
            self.assertEqual(tool.output_schema.get("type"), "object")
            self.assertEqual(tool.execution.task_support, "forbidden")
            self.assertLessEqual(len((tool.description or "").encode("utf-8")), 512)
            self.assertIs(tool.annotations.open_world_hint, False)
            self.assertEqual(tool.meta.get("dev-flow/taskSupport"), "forbidden")

    def test_bundled_skill_does_not_change_the_mcp_catalog_or_registration(self) -> None:
        manifest = json.loads(
            (ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8")
        )
        registration = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")
        self.assertEqual(
            registration,
            {
                "mcpServers": {
                    "dev-flow": {
                        "command": "dev-flow-mcp",
                        "args": ["--stdio"],
                    }
                }
            },
        )
        with tempfile.TemporaryDirectory() as data_dir:
            tools = asyncio.run(create_server(data_dir).list_tools())
        self.assertEqual(tuple(sorted(tool.name for tool in tools)), EXPECTED_TOOLS)

    def test_server_info_keeps_release_and_model_authorities_separate(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            result = asyncio.run(create_server(data_dir).call_tool("dev_flow_server_info", {}))
        self.assertFalse(result.is_error)
        data = result.structured_content["result"]
        self.assertEqual(data["release_version"], "0.6.9")
        self.assertEqual(data["model_version"], MODEL_VERSION)
        self.assertEqual(data["model_namespace"], MODEL_VERSION)
        self.assertEqual(data["repository_count"], {"minimum": 1, "maximum": 8})
        self.assertEqual(data["registration_mode"], "unknown")
        self.assertEqual(data["health"], {"status": "ready", "code": None})
        self.assertTrue(data["data_root_available"])
        self.assertEqual(MODEL_VERSION, "0.4.0")
        self.assertEqual(len(result.content), 1)
        self.assertNotIn('"release_version"', result.content[0].text)

    def test_catalog_digest_covers_every_observable_field_but_not_order(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            server = create_server(data_dir)
            tools = list(server._tool_manager.list_tools())
        projection = canonical_tool_projection(tools, output_schemas=OUTPUT_SCHEMAS)
        baseline = catalog_digest(projection)
        self.assertEqual(baseline, server.tool_catalog_digest)
        self.assertEqual(baseline, catalog_digest(list(reversed(projection))))
        for field in (
            "description", "inputSchema", "outputSchema", "annotations", "execution", "meta"
        ):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(projection))
                value = changed[0][field]
                changed[0][field] = {"changed": value}
                self.assertNotEqual(baseline, catalog_digest(changed))

    def test_success_and_domain_failure_use_the_exact_envelope(self) -> None:
        expected_fields = {
            "schema", "ok", "tool", "request_id", "result", "error",
        }
        with tempfile.TemporaryDirectory() as data_dir:
            server = create_server(data_dir)
            success_result = asyncio.run(server.call_tool("dev_flow_server_info", {}))
            failed_result = asyncio.run(server.call_tool(
                "dev_flow_get_task", {"task_id": "missing-task"},
            ))
        success_envelope = success_result.structured_content
        failure_envelope = failed_result.structured_content
        self.assertEqual(set(success_envelope), expected_fields)
        self.assertEqual(set(failure_envelope), expected_fields)
        self.assertTrue(success_envelope["ok"])
        self.assertIsNotNone(success_envelope["result"])
        self.assertIsNone(success_envelope["error"])
        self.assertFalse(failure_envelope["ok"])
        self.assertIsNone(failure_envelope["result"])
        self.assertEqual(failure_envelope["error"]["code"], "TASK_NOT_FOUND")
        self.assertRegex(success_envelope["request_id"], REQUEST_ID_PATTERN)
        self.assertRegex(failure_envelope["request_id"], REQUEST_ID_PATTERN)
        self.assertEqual(
            set(failure_envelope["error"]),
            {"code", "message", "details", "recovery"},
        )

    def test_server_info_reports_unavailable_data_root_without_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_path = Path(temporary) / "not-a-directory"
            data_path.write_text("occupied", encoding="utf-8")
            result = asyncio.run(create_server(str(data_path)).call_tool(
                "dev_flow_server_info", {},
            ))
        self.assertFalse(result.is_error)
        info = result.structured_content["result"]
        self.assertFalse(info["data_root_available"])
        self.assertEqual(info["health"]["status"], "unavailable")
        self.assertNotIn(str(data_path), json.dumps(result.structured_content))

    def test_managed_runtime_path_and_receipt_are_data_root_independent(self) -> None:
        environment = {
            "DEV_FLOW_RUNTIME_HOME": "/tmp/Dev Flow 运行时's",
            "PLUGIN_DATA": "/tmp/secret-task-data",
        }
        runtime = resolve_managed_runtime_root(environment=environment)
        self.assertTrue(runtime.endswith("Dev Flow 运行时's"))
        self.assertNotIn("secret-task-data", runtime)
        managed_release = "/tmp/managed-runtime/releases/r-test"
        digest = "b" * 64
        receipt = build_runtime_receipt(
            release_id="r-test",
            source_commit="a" * 40,
            source_tree="c" * 40,
            wheel_sha256=digest,
            plugin_path=managed_release + "/plugin",
            plugin_release_manifest_sha256=digest,
            dev_flow={
                "name": "dev-flow-orchestrator", "version": "0.5.0",
                "metadata_sha256": digest, "record_sha256": digest,
                "files": [{"path": "venv/lib/site-packages/dev_flow_orchestrator/__init__.py", "sha256": digest}],
            },
            dependencies=[{
                "name": "mcp", "version": "2.0.0",
                "metadata_sha256": digest, "record_sha256": digest,
            }],
            python={
                "path": managed_release + "/venv/bin/python",
                "executable_sha256": digest, "version": "3.14.0",
                "architecture": "test", "bits": 64,
            },
            runtime_path=managed_release,
            launcher_sha256=digest,
            ownership_manifest_sha256=digest,
            dependency_lock_sha256=digest,
            created_at="2026-08-09T00:00:00Z",
        )
        self.assertEqual(validate_runtime_receipt(receipt), receipt)
        self.assertEqual(receipt["schema"], RUNTIME_RECEIPT_SCHEMA)
        self.assertEqual(receipt["release_id"], "r-test")
        self.assertNotIn("secret-task-data", json.dumps(receipt))

        with self.assertRaisesRegex(DevFlowError, "disjoint"):
            resolve_managed_runtime_root(
                "/tmp/shared/root/runtime",
                source_root="/tmp/shared/root",
            )

    def test_runtime_receipt_rejects_invalid_identity_and_first_excess_file(self) -> None:
        managed_release = "/tmp/managed-runtime/releases/r-test"
        digest = "b" * 64
        receipt = build_runtime_receipt(
            release_id="r-test",
            source_commit="a" * 40,
            source_tree="c" * 40,
            wheel_sha256=digest,
            plugin_path=managed_release + "/plugin",
            plugin_release_manifest_sha256=digest,
            dev_flow={
                "name": "dev-flow-orchestrator", "version": "0.5.0",
                "metadata_sha256": digest, "record_sha256": digest,
                "files": [],
            },
            dependencies=[{
                "name": "mcp", "version": "2.0.0",
                "metadata_sha256": digest, "record_sha256": digest,
            }],
            python={
                "path": managed_release + "/venv/bin/python",
                "executable_sha256": digest, "version": "3.14.0",
                "architecture": "test", "bits": 64,
            },
            runtime_path=managed_release,
            launcher_sha256=digest,
            ownership_manifest_sha256=digest,
            dependency_lock_sha256=digest,
            created_at="2026-08-09T00:00:00Z",
        )
        invalid = json.loads(json.dumps(receipt))
        invalid["python"]["version"] = "3.9.99"
        with self.assertRaisesRegex(DevFlowError, "Python 3.10"):
            validate_runtime_receipt(invalid)
        invalid = json.loads(json.dumps(receipt))
        invalid["unexpected"] = True
        with self.assertRaisesRegex(DevFlowError, "fields"):
            validate_runtime_receipt(invalid)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime-receipt.json"
            path.write_bytes(b" " * (MAX_RUNTIME_RECEIPT_BYTES + 1))
            with self.assertRaisesRegex(DevFlowError, "byte limit"):
                read_runtime_receipt(path)

    def test_managed_launchers_route_through_stdlib_verifier_before_candidate_import(self) -> None:
        for name in ("dev_flow_mcp_launcher", "dev_flow_mcp_launcher.cmd"):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertIn("PYTHONDONTWRITEBYTECODE", text)
            self.assertIn(" -B -I ", text)
            self.assertIn("__DEV_FLOW_RUNTIME_VERIFIER__", text)
            self.assertIn("launch-mcp", text)
            command_lines = [
                line for line in text.splitlines()
                if line and not line.lstrip().startswith(("#", "rem "))
            ]
            self.assertNotIn("-m dev_flow_orchestrator.mcp", "\n".join(command_lines))
        helper_tree = ast.parse(
            (ROOT / "scripts" / "runtime_integrity.py").read_text(encoding="utf-8")
        )
        imported = set()
        for node in ast.walk(helper_tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertFalse(
            any(name == "dev_flow_orchestrator" or name.startswith("dev_flow_orchestrator.") for name in imported)
        )

    def test_read_tools_page_discover_secondary_member_and_isolate_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self._repository(root, "first")
            second = self._repository(root, "second")
            third = self._repository(root, "third")
            nested = second / "nested"
            nested.mkdir()
            data_dir = root / "data"
            server = create_server(str(data_dir))
            one = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "multi", "workflow": "lite",
                "repositories": [str(first), str(second)], "task_id": "task-one",
            }))
            two = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "other", "workflow": "lite",
                "repositories": [str(third)], "task_id": "task-two",
            }))
            self.assertFalse(one.is_error)
            self.assertFalse(two.is_error)

            page_one = asyncio.run(server.call_tool("dev_flow_list_tasks", {"limit": 1}))
            inventory = page_one.structured_content["result"]
            self.assertEqual(len(inventory["tasks"]), 1)
            self.assertIsNotNone(inventory["next_cursor"])
            page_two = asyncio.run(server.call_tool(
                "dev_flow_list_tasks", {"limit": 1, "cursor": inventory["next_cursor"]},
            ))
            self.assertNotEqual(
                inventory["tasks"][0]["task_id"],
                page_two.structured_content["result"]["tasks"][0]["task_id"],
            )
            found = asyncio.run(server.call_tool(
                "dev_flow_find_tasks_for_path", {"path": str(nested)},
            ))
            self.assertEqual(found.structured_content["result"]["classification"], "single")
            self.assertEqual(found.structured_content["result"]["tasks"][0]["task_id"], "task-one")
            detail = asyncio.run(server.call_tool("dev_flow_get_task", {"task_id": "task-one"}))
            self.assertEqual(detail.structured_content["result"]["task"]["repository_count"], 2)

            state_path = data_dir / MODEL_VERSION / "tasks" / "task-two" / "state.json"
            state_path.write_text("{invalid", encoding="utf-8")
            degraded = asyncio.run(server.call_tool("dev_flow_list_tasks", {}))
            degraded_data = degraded.structured_content["result"]
            self.assertEqual([item["task_id"] for item in degraded_data["tasks"]], ["task-one"])
            self.assertEqual(degraded_data["diagnostics"], [{"code": "STATE_INVALID", "task_id": "task-two"}])
            self.assertNotIn(str(data_dir), json.dumps(degraded.structured_content))

            unavailable = asyncio.run(server.call_tool(
                "dev_flow_find_tasks_for_path",
                {"path": str(first)},
            ))
            self.assertEqual(
                unavailable.structured_content["result"]["classification"],
                "inventory-unavailable",
            )

    def test_discovery_classifies_none_terminal_and_lease_ambiguity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            unrelated = root / "unrelated"
            unrelated.mkdir()
            application = MCPApplication(str(root / "data"))
            started = application.call("dev_flow_start_task", {
                "requirement": "discovery classification",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "task-discovery",
            })
            self.assertFalse(started.is_error)
            none = application.call(
                "dev_flow_find_tasks_for_path",
                {"path": str(unrelated)},
            )
            self.assertEqual(none.structured_content["result"]["classification"], "none")
            cancelled = application.call(
                "dev_flow_cancel_task",
                {"task_id": "task-discovery", "reason": "terminal discovery"},
            )
            self.assertFalse(cancelled.is_error)
            terminal = application.call(
                "dev_flow_find_tasks_for_path",
                {"path": str(repository)},
            )
            self.assertEqual(
                terminal.structured_content["result"]["classification"],
                "none",
            )

        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            controller = mock.Mock()
            controller.inventory_diagnostics.return_value = ()
            controller.tasks_for_path.side_effect = DevFlowError(
                "LEASE_INTEGRITY_CONFLICT",
                "multiple active tasks claim the path",
                details={"task_ids": ["task-a", "task-b"]},
            )
            application._controller = controller
            ambiguous = application.call(
                "dev_flow_find_tasks_for_path",
                {"path": str(Path(data_dir).resolve())},
            )
            result = ambiguous.structured_content["result"]
            self.assertEqual(result["classification"], "ambiguous")
            self.assertEqual(result["tasks"], [{"task_id": "task-a"}, {"task_id": "task-b"}])

    def test_stored_reads_survive_a_missing_repository_and_limit_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            server = create_server(str(root / "data"))
            started = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "stored read",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "task-stored-read",
            }))
            self.assertFalse(started.is_error)
            repository.rename(root / "repository-unavailable")
            listed = asyncio.run(server.call_tool("dev_flow_list_tasks", {"limit": 100}))
            detail = asyncio.run(server.call_tool(
                "dev_flow_get_task",
                {"task_id": "task-stored-read"},
            ))
            self.assertFalse(listed.is_error)
            self.assertFalse(detail.is_error)
            self.assertEqual(listed.structured_content["result"]["tasks"][0]["task_id"], "task-stored-read")
            self.assertEqual(detail.structured_content["result"]["task"]["task_id"], "task-stored-read")

        with tempfile.TemporaryDirectory() as data_dir, mock.patch(
            "dev_flow_orchestrator.mcp.application.Controller",
        ) as controller:
            bounded_server = create_server(data_dir)
            with self.assertRaises(Exception):
                asyncio.run(bounded_server.call_tool("dev_flow_list_tasks", {"limit": 101}))
        controller.assert_not_called()

    def test_repository_admission_and_missing_member_errors_remain_domain_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            server = create_server(str(root / "data"))
            started = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "lease owner",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "lease-owner",
            }))
            self.assertFalse(started.is_error)
            leased = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "lease conflict",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "lease-contender",
            }))
            self.assertEqual(
                leased.structured_content["error"]["code"],
                "TASK_MEMBERSHIP_LEASED",
            )
            missing = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "missing",
                "workflow": "lite",
                "repositories": [str(root / "does-not-exist")],
                "task_id": "missing-member",
            }))
            self.assertEqual(missing.structured_content["error"]["code"], "REPOSITORY_INVALID")
            moved = root / "repository-moved"
            repository.rename(moved)
            unavailable = asyncio.run(server.call_tool(
                "dev_flow_get_next_action", {"task_id": "lease-owner"},
            ))
            self.assertEqual(
                unavailable.structured_content["error"]["code"],
                "REPOSITORY_INVALID",
            )

    def test_nonfinite_input_is_rejected_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            with mock.patch.object(application, "_dispatch") as dispatch:
                result = application.call("dev_flow_apply_action", {
                    "task_id": "task", "action_id": "action", "payload": {"value": float("nan")},
                    "binding": {},
                })
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "INTERNAL_ERROR")
        dispatch.assert_not_called()

    def test_adapter_output_violation_becomes_internal_error(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            with mock.patch.object(
                application,
                "_dispatch",
                return_value=({"release_version": "missing-fields"}, "bad output"),
            ):
                result = application.call("dev_flow_server_info", {})
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "INTERNAL_ERROR")
        self.assertIsNone(result.structured_content["result"])

    def test_transport_rejects_invalid_nested_mutation_contracts(self) -> None:
        tool = "dev_flow_apply_action"
        valid_receipt = {
            "schema": RECEIPT_SCHEMA,
            "task_id": "task-transport-boundary",
            "action_id": "task.preflight",
            "committed_revision": 1,
            "status": "ANALYZING",
            "current_node": "impact",
            "committed": True,
            "workspace_freshness": {
                "schema": WORKSPACE_FRESHNESS_SCHEMA,
                "status": True,
                "observed_at": "2026-08-09T00:00:00Z",
                "reasons": [],
            },
            "blind_retry": False,
            "recovery": {
                "kind": "read-after-write",
                "tool": "dev_flow_get_next_action",
                "task_id": "task-transport-boundary",
                "blind_retry": False,
            },
        }

        def invalid_observed_at(result: dict) -> None:
            result["receipt"]["workspace_freshness"]["observed_at"] = []

        def invalid_recovery(result: dict) -> None:
            result["receipt"]["recovery"] = {}

        def invalid_current(result: dict) -> None:
            result["current"] = {}

        for label, corrupt in (
            ("observed-at", invalid_observed_at),
            ("recovery", invalid_recovery),
            ("current", invalid_current),
        ):
            with self.subTest(field=label), tempfile.TemporaryDirectory() as data_dir:
                structured = {
                    "schema": "dev-flow-mcp-result/1.0.0",
                    "ok": True,
                    "tool": tool,
                    "request_id": "mcp-01234567-89ab-4cde-8fab-0123456789ab",
                    "result": {
                        "receipt": json.loads(json.dumps(valid_receipt)),
                        "current": None,
                    },
                    "error": None,
                }
                corrupt(structured["result"])
                published_error = next(
                    Draft202012Validator(OUTPUT_SCHEMAS[tool]).iter_errors(
                        structured
                    ),
                    None,
                )
                if label == "current":
                    self.assertIsNotNone(published_error)
                    continue
                self.assertIsNone(published_error)
                forged = CallToolResult(
                    content=[],
                    structuredContent=structured,
                    isError=False,
                )
                server = create_server(data_dir)
                with mock.patch.object(
                    MCPServer,
                    "call_tool",
                    new=mock.AsyncMock(return_value=forged),
                ):
                    result = asyncio.run(server.call_tool(
                        tool,
                        {"task_id": "task-transport-boundary"},
                    ))

                self.assertTrue(result.is_error)
                self.assertEqual(
                    result.structured_content["error"]["code"],
                    "MCP_COMPLETION_UNCERTAIN",
                )
                self.assertEqual(
                    result.structured_content["request_id"],
                    structured["request_id"],
                )
                recovery = result.structured_content["error"]["recovery"]
                self.assertEqual(recovery["kind"], "read-after-write")
                self.assertEqual(recovery["task_id"], "task-transport-boundary")
                self.assertFalse(recovery["blind_retry"])
                self.assertIsNone(result.structured_content["result"])

    def test_first_excess_structured_result_is_rejected(self) -> None:
        oversized = {
            "task": {},
            "health": "not-evaluated",
            "why_next": {},
            "timeline": {},
            "artifacts": ["x" * (512 * 1024)],
            "dossier": None,
            "recovery": {},
        }
        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            with mock.patch.object(
                application,
                "_dispatch",
                return_value=(oversized, "oversized"),
            ):
                result = application.call("dev_flow_get_task", {"task_id": "task-one"})
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "MCP_RESULT_LIMIT")

    def test_auto_task_id_survives_uncertain_start_postprocessing(self) -> None:
        failures = (
            (
                "result-limit",
                MCPRuntimeFailure(
                    "MCP_RESULT_LIMIT",
                    "forced post-controller result limit",
                    recovery={"kind": "narrow-request", "blind_retry": False},
                ),
            ),
            (
                "result-envelope",
                ResultSchemaViolation("forced structured result validation failure"),
            ),
            (
                "unexpected",
                RuntimeError("forced unexpected post-controller failure"),
            ),
        )
        for boundary, failure in failures:
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                repository = self._repository(root, "repository")
                data_dir = root / "data"
                application = MCPApplication(str(data_dir))
                failure_patch = (
                    mock.patch(
                        "dev_flow_orchestrator.mcp.application.success",
                        side_effect=failure,
                    )
                    if boundary == "result-envelope"
                    else mock.patch.object(
                        application,
                        "_enforce_result_limits",
                        side_effect=failure,
                    )
                )
                with failure_patch:
                    result = application.call(
                        "dev_flow_start_task",
                        {
                            "requirement": "retain the generated task ID",
                            "workflow": "lite",
                            "repositories": [str(repository)],
                        },
                    )

                states = Controller(str(data_dir)).list_tasks()
                self.assertEqual(len(states), 1)
                task_id = states[0].task_id
                self.assertTrue(result.is_error)
                error = result.structured_content["error"]
                self.assertEqual(error["code"], "MCP_COMPLETION_UNCERTAIN")
                self.assertEqual(error["details"]["task_id"], task_id)
                self.assertEqual(error["recovery"]["task_id"], task_id)
                self.assertEqual(error["recovery"]["tool"], "dev_flow_get_task")
                self.assertFalse(error["recovery"]["blind_retry"])
                recovered = application.call(
                    error["recovery"]["tool"],
                    {"task_id": error["recovery"]["task_id"]},
                )
                self.assertFalse(recovered.is_error)

    def test_auto_task_id_survives_server_outer_output_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            data_dir = root / "data"
            server = create_server(str(data_dir))
            with mock.patch(
                "dev_flow_orchestrator.mcp.server.validate_structured_result",
                side_effect=ResultSchemaViolation("forced outer output guard"),
            ):
                result = asyncio.run(server.call_tool(
                    "dev_flow_start_task",
                    {
                        "requirement": "retain the generated task ID",
                        "workflow": "lite",
                        "repositories": [str(repository)],
                    },
                ))

            states = Controller(str(data_dir)).list_tasks()
            self.assertEqual(len(states), 1)
            task_id = states[0].task_id
            self.assertTrue(result.is_error)
            error = result.structured_content["error"]
            self.assertEqual(error["code"], "MCP_COMPLETION_UNCERTAIN")
            self.assertEqual(error["details"]["task_id"], task_id)
            self.assertEqual(error["recovery"]["task_id"], task_id)
            self.assertFalse(error["recovery"]["blind_retry"])
            recovered = asyncio.run(server.call_tool(
                error["recovery"]["tool"],
                {"task_id": error["recovery"]["task_id"]},
            ))
            self.assertFalse(recovered.is_error)

    def test_cancellation_before_entry_and_after_commit_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            application = MCPApplication(str(root / "data"))
            with mock.patch.object(application, "_dispatch") as dispatch:
                cancelled = application.call(
                    "dev_flow_start_task",
                    {"requirement": "cancel", "workflow": "lite", "repositories": [str(repository)]},
                    cancellation_check=lambda: True,
                )
            self.assertEqual(cancelled.structured_content["error"]["code"], "REQUEST_CANCELLED")
            dispatch.assert_not_called()

            task_id = "task-uncertain"
            cancelled_after = False
            original_dispatch = application._dispatch

            def dispatch_then_cancel(tool, arguments, **kwargs):
                nonlocal cancelled_after
                value = original_dispatch(tool, arguments, **kwargs)
                cancelled_after = True
                return value

            with mock.patch.object(application, "_dispatch", side_effect=dispatch_then_cancel):
                uncertain = application.call(
                    "dev_flow_start_task",
                    {
                        "requirement": "possible commit",
                        "workflow": "lite",
                        "repositories": [str(repository)],
                        "task_id": task_id,
                    },
                    cancellation_check=lambda: cancelled_after,
                )
            self.assertEqual(
                uncertain.structured_content["error"]["code"],
                "MCP_COMPLETION_UNCERTAIN",
            )
            recovery = uncertain.structured_content["error"]["recovery"]
            self.assertEqual(recovery["kind"], "read-after-write")
            self.assertEqual(recovery["tool"], "dev_flow_get_task")
            self.assertEqual(recovery["task_id"], task_id)
            self.assertFalse(recovery["blind_retry"])
            self.assertEqual(Controller(str(root / "data")).show(task_id).revision, 0)

    def test_live_mcp_git_calls_receive_request_scoped_cancellation_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            application = MCPApplication(str(root / "data"))
            started = application.call("dev_flow_start_task", {
                "requirement": "git cancellation scope",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "task-git-cancel-scope",
            })
            self.assertFalse(started.is_error)
            observed = []
            original = GitClient._run

            def record_signal(repository_path, *arguments, **kwargs):
                observed.append(git_client_module._GIT_CANCEL_EVENT.get())
                return original(repository_path, *arguments, **kwargs)

            with mock.patch.object(GitClient, "_run", side_effect=record_signal):
                current = application.call(
                    "dev_flow_get_next_action",
                    {"task_id": "task-git-cancel-scope"},
                )
            self.assertFalse(current.is_error)
            self.assertTrue(observed)
            self.assertTrue(all(signal is not None for signal in observed))

    def test_cancellation_after_capture_before_commit_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            application = MCPApplication(str(root / "data"))
            started = application.call("dev_flow_start_task", {
                "requirement": "pre-commit cancellation",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "task-precommit-cancel",
            })
            self.assertFalse(started.is_error)
            current = application.call(
                "dev_flow_get_next_action",
                {"task_id": "task-precommit-cancel"},
            ).structured_content["result"]
            binding = current["action"]["binding"]
            cancelled = False
            original_capture = application.controller._capture_snapshot

            def capture_then_cancel(*args, **kwargs):
                nonlocal cancelled
                snapshot = original_capture(*args, **kwargs)
                cancelled = True
                return snapshot

            with mock.patch.object(
                application.controller,
                "_capture_snapshot",
                side_effect=capture_then_cancel,
            ), mock.patch.object(
                application.controller.store,
                "commit_repository_mutation",
                wraps=application.controller.store.commit_repository_mutation,
            ) as commit, mock.patch.object(
                application.controller.store,
                "_atomic_write",
                wraps=application.controller.store._atomic_write,
            ) as write:
                result = application.call(
                    "dev_flow_apply_action",
                    {
                        "task_id": "task-precommit-cancel",
                        "action_id": "task.preflight",
                        "payload": {},
                        "binding": binding,
                    },
                    cancellation_check=lambda: cancelled,
                )

            self.assertTrue(result.is_error)
            self.assertEqual(
                result.structured_content["error"]["code"],
                "REQUEST_CANCELLED",
            )
            commit.assert_called_once()
            write.assert_not_called()
            state = Controller(str(root / "data")).show("task-precommit-cancel")
            self.assertEqual(state.revision, 0)

    def test_mutation_freshness_false_and_unknown_are_successful_mcp_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            application = MCPApplication(str(root / "data"))
            started = application.call(
                "dev_flow_start_task",
                {
                    "requirement": "adapter freshness contract",
                    "workflow": "lite",
                    "repositories": [str(repository)],
                    "task_id": "task-adapter-freshness",
                },
            )
            self.assertFalse(started.is_error)
            projection = application.controller.next("task-adapter-freshness")
            binding = projection["action"]["binding"]
            cases = (
                (
                    "changed",
                    {
                        "status": False,
                        "observed_at": "2026-08-09T00:00:00Z",
                        "reasons": [
                            "workspace_changed",
                            "workspace_changed:repository",
                        ],
                    },
                    projection,
                    False,
                ),
                (
                    "unknown",
                    {
                        "status": "unknown",
                        "observed_at": None,
                        "reasons": ["observation_failed:OBSERVATION_FAILED"],
                    },
                    None,
                    True,
                ),
            )
            for label, freshness, mutation_projection, current_is_null in cases:
                with self.subTest(freshness=label):
                    receipt = {
                        "schema": RECEIPT_SCHEMA,
                        "task_id": "task-adapter-freshness",
                        "action_id": "task.preflight",
                        "committed_revision": 1,
                        "status": "ANALYZING",
                        "current_node": "impact",
                        "committed": True,
                        "workspace_freshness": {
                            "schema": WORKSPACE_FRESHNESS_SCHEMA,
                            **freshness,
                        },
                        "blind_retry": False,
                        "recovery": {
                            "kind": "read-after-write",
                            "tool": "dev_flow_get_next_action",
                            "task_id": "task-adapter-freshness",
                            "blind_retry": False,
                        },
                    }
                    with mock.patch.object(
                        application.controller,
                        "apply",
                        return_value={
                            "receipt": receipt,
                            "projection": mutation_projection,
                        },
                    ):
                        result = application.call(
                            "dev_flow_apply_action",
                            {
                                "task_id": "task-adapter-freshness",
                                "action_id": "task.preflight",
                                "payload": {},
                                "binding": binding,
                            },
                        )

                    self.assertFalse(result.is_error)
                    content = result.structured_content["result"]
                    self.assertEqual(content["receipt"], receipt)
                    self.assertEqual(content["current"] is None, current_is_null)

    def test_invalid_cursor_fails_closed_without_inventory_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            with mock.patch.object(application.controller, "inspect_tasks") as inspect_tasks:
                result = application.call("dev_flow_list_tasks", {"cursor": "***", "limit": 20})
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "CURSOR_INVALID")
        inspect_tasks.assert_not_called()

    def test_unknown_input_field_is_rejected_before_controller_construction(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir, mock.patch(
            "dev_flow_orchestrator.mcp.application.Controller",
        ) as controller:
            server = create_server(data_dir)
            with self.assertRaises(Exception):
                asyncio.run(server.call_tool(
                    "dev_flow_get_task",
                    {"task_id": "task-one", "unknown": True},
                ))
        controller.assert_not_called()

    def test_bounded_coordinator_rejects_overlapping_task_mutation_and_capture(self) -> None:
        coordinator = BoundedCoordinator()
        with coordinator.capture(), coordinator.capture(), coordinator.capture(), coordinator.capture():
            self.assertEqual(coordinator.active_count, 4)
            with self.assertRaises(MCPRuntimeFailure) as raised:
                with coordinator.capture():
                    self.fail("first excess capture entered its critical section")
            self.assertEqual(raised.exception.code, "MCP_RUNTIME_UNAVAILABLE")
        self.assertEqual(coordinator.active_count, 0)

        first_entered = threading.Event()
        release_first = threading.Event()
        order = []

        def first() -> None:
            with coordinator.mutation("task-one"):
                order.append("first")
                first_entered.set()
                release_first.wait(2)

        def second() -> None:
            first_entered.wait(2)
            with coordinator.mutation("task-one"):
                order.append("second")

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        self.assertTrue(first_entered.wait(2))
        self.assertEqual(order, ["first"])
        release_first.set()
        first_thread.join(2)
        second_thread.join(2)
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(coordinator.mutation_count, 0)

    def test_same_task_concurrent_mutations_commit_at_most_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            application = MCPApplication(str(root / "data"))
            started = application.call("dev_flow_start_task", {
                "requirement": "concurrent mutation",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": "task-concurrent",
            })
            self.assertFalse(started.is_error)
            current = application.call(
                "dev_flow_get_next_action",
                {"task_id": "task-concurrent"},
            ).structured_content["result"]
            binding = current["action"]["binding"]
            barrier = threading.Barrier(3)
            results = []

            def mutate() -> None:
                barrier.wait()
                results.append(application.call(
                    "dev_flow_apply_action",
                    {
                        "task_id": "task-concurrent",
                        "action_id": "task.preflight",
                        "payload": {},
                        "binding": binding,
                    },
                ))

            threads = [threading.Thread(target=mutate) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(sum(not result.is_error for result in results), 1)
            failures = [result for result in results if result.is_error]
            self.assertEqual(len(failures), 1)
            self.assertIn(
                failures[0].structured_content["error"]["code"],
                {"ACTION_BINDING_STALE", "REVISION_CONFLICT"},
            )
            self.assertEqual(
                Controller(str(root / "data")).show("task-concurrent").revision,
                1,
            )

    def test_unexpected_failure_is_redacted_and_returns_request_id(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            application = MCPApplication(data_dir)
            secret = "do-not-log-this-secret"
            with mock.patch.object(
                application.controller,
                "inspect_product",
                side_effect=RuntimeError(secret),
            ), self.assertLogs("dev_flow_orchestrator.mcp", level="ERROR") as logs:
                result = application.call("dev_flow_server_info", {})
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["error"]["code"], "INTERNAL_ERROR")
        self.assertRegex(result.structured_content["request_id"], REQUEST_ID_PATTERN)
        self.assertNotIn(secret, "\n".join(logs.output))
        self.assertNotIn(str(data_dir), "\n".join(logs.output))

    def test_remote_transport_options_fail_without_stdout(self) -> None:
        from io import StringIO

        stdout = StringIO()
        stderr = StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(mcp_main(["--http", "--port", "8080"]), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("MCP_RUNTIME_UNAVAILABLE", stderr.getvalue())

    def test_runtime_argument_failures_use_the_closed_bounded_startup_code(self) -> None:
        from io import StringIO

        for arguments in (("--unknown-option",), ("--stdio", "--log-level", "INFO")):
            with self.subTest(arguments=arguments):
                stdout = StringIO()
                stderr = StringIO()
                with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr), mock.patch.object(
                    mcp_runtime,
                    "create_server",
                ) as create:
                    self.assertEqual(mcp_main(list(arguments)), 2)
                self.assertEqual(stdout.getvalue(), "")
                diagnostic = stderr.getvalue().strip()
                self.assertLessEqual(len(diagnostic.encode("utf-8")), 4 * 1024)
                self.assertEqual(
                    json.loads(diagnostic)["code"],
                    "MCP_RUNTIME_UNAVAILABLE",
                )
                create.assert_not_called()

    def test_startup_self_check_rejects_runtime_identity_drift_without_stdout(self) -> None:
        from contextlib import ExitStack
        from io import StringIO

        actual_version = mcp_runtime.importlib.metadata.version

        def sdk_major_drift(package: str) -> str:
            return "3.0.0" if package == "mcp" else actual_version(package)

        def release_drift(package: str) -> str:
            return "0.5.2" if package == "dev-flow-orchestrator" else actual_version(package)

        cases = (
            ("python-3.9", ((mcp_runtime.sys, "version_info", (3, 9, 19)),)),
            ("32-bit", ((mcp_runtime.struct, "calcsize", lambda _format: 4),)),
            ("sdk-major", ((mcp_runtime.importlib.metadata, "version", sdk_major_drift),)),
            ("release", ((mcp_runtime.importlib.metadata, "version", release_drift),)),
            ("model", ((mcp_runtime, "MODEL_VERSION", "0.5.0"),)),
            ("namespace", ((mcp_runtime, "PLUGIN_DATA_NAMESPACE", "0.5.0"),)),
            ("interface", ((mcp_runtime, "MCP_INTERFACE_SCHEMA", "dev-flow-mcp/2.0.0"),)),
            ("guidance-digest", ((mcp_runtime, "GUIDANCE_CATALOG_DIGEST", "0" * 64),)),
        )
        for name, patches in cases:
            with self.subTest(name=name), ExitStack() as stack:
                for target, attribute, value in patches:
                    stack.enter_context(mock.patch.object(target, attribute, value))
                create = stack.enter_context(mock.patch.object(mcp_runtime, "create_server"))
                stdout = StringIO()
                stderr = StringIO()
                stack.enter_context(mock.patch("sys.stdout", stdout))
                stack.enter_context(mock.patch("sys.stderr", stderr))
                self.assertEqual(mcp_main(["--stdio"]), 2)
                self.assertEqual(stdout.getvalue(), "")
                diagnostic = stderr.getvalue().strip()
                self.assertLessEqual(len(diagnostic.encode("utf-8")), 4 * 1024)
                self.assertEqual(
                    json.loads(diagnostic)["code"],
                    "MCP_DEPENDENCY_INVALID",
                )
                create.assert_not_called()

    def test_raw_stdio_rejects_duplicate_keys_and_invalid_utf8_without_stdout_noise(self) -> None:
        initialize = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "raw-test", "version": "1"},
                },
            },
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        invalid_messages = (
            b'{"jsonrpc":"2.0","id":99,"id":98,"method":"initialize","params":{}}\n',
            b"\xff\n",
        )
        with tempfile.TemporaryDirectory() as data_dir:
            for invalid in invalid_messages:
                environment = hermetic_subprocess_env(Path(data_dir))
                probe_subprocess_runtime_roots(Path(data_dir), environment)
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "dev_flow_orchestrator.mcp",
                        "--stdio",
                        "--data-dir",
                        data_dir,
                    ],
                    cwd=ROOT,
                    env=environment,
                    input=invalid + initialize,
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                lines = completed.stdout.splitlines()
                self.assertEqual(len(lines), 1, completed.stdout)
                response = json.loads(lines[0].decode("utf-8"))
                self.assertEqual(response["jsonrpc"], "2.0")
                self.assertEqual(response["id"], 1)
                self.assertIn("serverInfo", response["result"])
                self.assertNotIn(b"Traceback", completed.stdout)

    def test_deep_bounded_json_does_not_discard_following_initialize(self) -> None:
        initialize = json.dumps({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "deep-test", "version": "1"},
            },
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        deep = b"[" * 4000 + b"0" + b"]" * 4000 + b"\n"
        with tempfile.TemporaryDirectory() as data_dir:
            environment = hermetic_subprocess_env(Path(data_dir))
            probe_subprocess_runtime_roots(Path(data_dir), environment)
            completed = subprocess.run(
                [
                    sys.executable, "-m", "dev_flow_orchestrator.mcp", "--stdio",
                    "--data-dir", data_dir,
                ],
                cwd=ROOT,
                env=environment,
                input=deep + deep + initialize,
                capture_output=True,
                check=False,
                timeout=10,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        initialized = next(item for item in responses if item.get("id") == 7)
        self.assertIn("serverInfo", initialized["result"])
        self.assertLessEqual(len(completed.stderr), 16 * 1024)

    def test_core_modules_do_not_import_mcp_framework(self) -> None:
        package = ROOT / "src" / "dev_flow_orchestrator"
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            self.assertFalse(
                any(name == "mcp" or name.startswith(("mcp.", "pydantic", "starlette", "anyio")) for name in imports),
                str(path),
            )

    def test_governance_adapter_and_cli_dispatch_use_identical_controller_calls(self) -> None:
        contract = {"schema": "contract"}
        claims = {"schema": "claims"}
        decision = {"id": "decision"}
        disposition = {"schema": "disposition"}
        cases = (
            (
                "dev_flow_revise_contract",
                {
                    "task_id": "task-one",
                    "contract": contract,
                    "ownership_claims": claims,
                    "reason": "scope changed",
                    "actor_label": "maintainer",
                },
                argparse.Namespace(
                    data_dir="unused",
                    command="revise-contract",
                    task_id="task-one",
                    contract_json=json.dumps(contract),
                    ownership_claims_json=json.dumps(claims),
                    reason="scope changed",
                    actor_label="maintainer",
                ),
                "revise_contract",
            ),
            (
                "dev_flow_record_decision",
                {"task_id": "task-one", "decision": decision},
                argparse.Namespace(
                    data_dir="unused",
                    command="decide",
                    task_id="task-one",
                    decision_json=json.dumps(decision),
                ),
                "decide",
            ),
            (
                "dev_flow_dispose_finding",
                {
                    "task_id": "task-one",
                    "disposition": disposition,
                    "actor_authorized": False,
                },
                argparse.Namespace(
                    data_dir="unused",
                    command="dispose-finding",
                    task_id="task-one",
                    disposition_json=json.dumps(disposition),
                    actor_authorized=False,
                ),
                "dispose_finding",
            ),
            (
                "dev_flow_cancel_task",
                {"task_id": "task-one", "reason": "stop"},
                argparse.Namespace(
                    data_dir="unused",
                    command="cancel",
                    task_id="task-one",
                    reason="stop",
                ),
                "cancel",
            ),
        )
        for tool, mcp_arguments, cli_arguments, method_name in cases:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as data_dir:
                cli_controller = mock.Mock()
                getattr(cli_controller, method_name).return_value = {}
                with mock.patch.object(cli_module, "Controller", return_value=cli_controller):
                    cli_module._dispatch(cli_arguments)

                mcp_controller = mock.Mock()
                getattr(mcp_controller, method_name).return_value = {}
                application = MCPApplication(data_dir)
                application._controller = mcp_controller
                with mock.patch.object(application, "_mutation_view", return_value={}):
                    application._dispatch(tool, mcp_arguments)
                self.assertEqual(
                    getattr(mcp_controller, method_name).call_args,
                    getattr(cli_controller, method_name).call_args,
                )

    def test_governance_domain_errors_preserve_controller_codes(self) -> None:
        cases = (
            (
                "dev_flow_revise_contract",
                {
                    "task_id": "task-one",
                    "contract": {},
                    "ownership_claims": None,
                    "reason": "reason",
                    "actor_label": "actor",
                },
                "revise_contract",
                "CONTRACT_REVISION_INVALID",
            ),
            (
                "dev_flow_record_decision",
                {"task_id": "task-one", "decision": {}},
                "decide",
                "DECISION_INVALID",
            ),
            (
                "dev_flow_dispose_finding",
                {"task_id": "task-one", "disposition": {}, "actor_authorized": False},
                "dispose_finding",
                "FINDING_DISPOSITION_FORBIDDEN",
            ),
            (
                "dev_flow_cancel_task",
                {"task_id": "task-one", "reason": "reason"},
                "cancel",
                "ACTION_NOT_AVAILABLE",
            ),
        )
        for tool, arguments, method_name, code in cases:
            with self.subTest(tool=tool), tempfile.TemporaryDirectory() as data_dir:
                controller = mock.Mock()
                getattr(controller, method_name).side_effect = DevFlowError(
                    code,
                    "bounded domain rejection",
                )
                application = MCPApplication(data_dir)
                application._controller = controller
                result = application.call(tool, arguments)
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content["error"]["code"], code)
                self.assertIsNone(result.structured_content["result"])

    def test_invalid_action_payload_returns_correct_request_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            controller = mock.Mock()
            controller.apply.side_effect = DevFlowError(
                "NODE_OUTPUT_INVALID",
                "resources must be an object containing exactly items",
                details={"field": "resources", "expected_fields": ["items"]},
            )
            application = MCPApplication(data_dir)
            application._controller = controller
            result = application.call(
                "dev_flow_apply_action",
                {
                    "task_id": "task-one",
                    "action_id": "plan.record",
                    "payload": {"resources": []},
                    "binding": {},
                },
            )

        self.assertTrue(result.is_error)
        error = result.structured_content["error"]
        self.assertEqual(error["code"], "NODE_OUTPUT_INVALID")
        self.assertEqual(error["details"]["expected_fields"], ["items"])
        self.assertEqual(
            error["recovery"],
            {
                "kind": "correct-request",
                "tool": "dev_flow_apply_action",
                "task_id": "task-one",
                "blind_retry": False,
            },
        )

    def test_current_action_is_compact_and_keeps_the_exact_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            environment = hermetic_subprocess_env(root)
            subprocess.run(["git", "init", "-q"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "config", "user.email", "mcp@example.invalid"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "config", "user.name", "MCP Test"], cwd=repository, env=environment, check=True)
            (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repository, env=environment, check=True)
            data_dir = root / "data"
            server = create_server(str(data_dir))
            started = asyncio.run(server.call_tool(
                "dev_flow_start_task",
                {
                    "requirement": "verify compact action",
                    "workflow": str((ROOT / "workflows" / "lite.yaml").resolve()),
                    "repositories": [str(repository)],
                },
            ))
            task_id = started.structured_content["result"]["task_id"]
            authoritative = Controller(str(data_dir)).next(task_id)
            result = asyncio.run(server.call_tool("dev_flow_get_next_action", {"task_id": task_id}))
            compact = result.structured_content["result"]
            self.assertEqual(compact["schema"], "dev-flow-mcp-action/1.0.0")
            self.assertEqual(compact["action"]["id"], "task.preflight")
            self.assertEqual(compact["action"]["binding"], authoritative["action"]["binding"])
            self.assertNotIn("snapshot", compact["repository_set"]["repositories"][0])
            self.assertLessEqual(len(json.dumps(compact).encode("utf-8")), 128 * 1024)
            blocked = json.loads(json.dumps(compact))
            blocked["action"]["binding"] = None
            blocked["action"]["context"]["blocked"] = {
                "code": "ARTIFACT_INPUT_MISSING",
                "message": "required input is stale",
            }
            validate_current_action(blocked)
            blocked["action"]["context"]["blocked"] = None
            with self.assertRaises(ResultSchemaViolation):
                validate_current_action(blocked)

    def test_lite_current_action_exposes_impact_and_ownership_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            data_dir = root / "data"
            server = create_server(str(data_dir))
            started = asyncio.run(server.call_tool(
                "dev_flow_start_task",
                {
                    "requirement": "exercise self-contained MCP payload contracts",
                    "workflow": "lite",
                    "repositories": [str(repository)],
                },
            ))
            task_id = started.structured_content["result"]["task_id"]
            repository_id = started.structured_content["result"]["repository_set"]["repository_ids"][0]

            current = asyncio.run(server.call_tool(
                "dev_flow_get_next_action", {"task_id": task_id},
            )).structured_content["result"]
            advanced = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": current["action"]["id"],
                    "payload": {},
                    "binding": current["action"]["binding"],
                },
            ))
            impact = advanced.structured_content["result"]["current"]
            impact_schema = impact["action"]["payload_schema"]
            self.assertIn("impact_manifest", impact_schema["properties"])
            self.assertIn("impact_manifest", impact_schema["required"])
            omitted = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": impact["action"]["id"],
                    "payload": {
                        "summary": "Hidden impact must not be inferred",
                        "driver_result": {
                            "schema": DRIVER_RESULT_SCHEMA,
                            "status": "available",
                        },
                    },
                    "binding": impact["action"]["binding"],
                },
            ))
            self.assertTrue(omitted.is_error)
            self.assertEqual(
                omitted.structured_content["error"]["code"],
                "NODE_OUTPUT_INVALID",
            )
            self.assertEqual(
                omitted.structured_content["error"]["details"]["missing_fields"],
                ["impact_manifest"],
            )
            before_invalid = Controller(str(data_dir)).show(task_id)
            invalid = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": impact["action"]["id"],
                    "payload": {
                        "summary": "Reject legacy confidence on a live action",
                        "driver_result": {
                            "schema": DRIVER_RESULT_SCHEMA,
                            "status": "available",
                        },
                        "impact_manifest": {
                            "confidence": "legacy-arbitrary-value",
                            "entries": [],
                            "edges": [],
                            "risk_triggers": [],
                            "public_behavior": False,
                            "documentation_required": False,
                            "manual_evidence_required": False,
                            "executable_reproduction_required": False,
                            "overflow": False,
                            "limitations": [],
                        },
                    },
                    "binding": impact["action"]["binding"],
                },
            ))
            self.assertTrue(invalid.is_error)
            error = invalid.structured_content["error"]
            self.assertEqual(error["code"], "IMPACT_INVALID")
            self.assertNotEqual(error["code"], "MCP_COMPLETION_UNCERTAIN")
            self.assertEqual(error["recovery"]["tool"], "dev_flow_get_next_action")
            self.assertEqual(error["recovery"]["task_id"], task_id)
            self.assertFalse(error["recovery"]["blind_retry"])
            recovered = asyncio.run(server.call_tool(
                error["recovery"]["tool"],
                {"task_id": error["recovery"]["task_id"]},
            ))
            self.assertFalse(recovered.is_error)
            self.assertEqual(
                recovered.structured_content["result"]["action"]["id"],
                impact["action"]["id"],
            )
            self.assertEqual(Controller(str(data_dir)).show(task_id), before_invalid)
            impact_payload = {
                "summary": "Source impact is confirmed",
                "driver_result": {
                    "schema": DRIVER_RESULT_SCHEMA,
                    "status": "available",
                },
                "impact_manifest": {
                    "confidence": "source-confirmed",
                    "entries": [{
                        "repository_id": repository_id,
                        "path": "tracked.txt",
                        "symbol": None,
                        "criterion_ids": ["requirement"],
                    }],
                    "edges": [],
                    "risk_triggers": [],
                    "public_behavior": False,
                    "documentation_required": False,
                    "manual_evidence_required": False,
                    "executable_reproduction_required": True,
                    "overflow": False,
                    "limitations": [],
                },
            }
            self.assertIsNone(
                next(Draft202012Validator(impact_schema).iter_errors(impact_payload), None)
            )
            advanced = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": impact["action"]["id"],
                    "payload": impact_payload,
                    "binding": impact["action"]["binding"],
                },
            ))
            implementation = advanced.structured_content["result"]["current"]
            implementation_schema = implementation["action"]["payload_schema"]
            self.assertIn("ownership_claims", implementation_schema["properties"])
            self.assertIn("ownership_claims", implementation_schema["required"])
            claim_schema = implementation_schema["properties"]["ownership_claims"]
            claim_item = claim_schema["properties"]["claims"]["items"]["properties"]
            (repository / "tracked.txt").write_text(
                "baseline\nimplemented through MCP\n",
                encoding="utf-8",
            )
            exact_claims = {
                "summary": "Implemented the bounded source change",
                "ownership_claims": {
                    "schema": claim_schema["properties"]["schema"]["const"],
                    "claims": [{
                        "repository_id": claim_item["repository_id"]["enum"][0],
                        "path": "tracked.txt",
                        "classification": "implementation",
                        "criterion_ids": [claim_item["criterion_ids"]["items"]["enum"][0]],
                        "purpose": "Implement the current acceptance criterion",
                    }],
                },
            }
            self.assertIsNone(
                next(
                    Draft202012Validator(implementation_schema).iter_errors(exact_claims),
                    None,
                )
            )
            advanced = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": implementation["action"]["id"],
                    "payload": exact_claims,
                    "binding": implementation["action"]["binding"],
                },
            ))
            self.assertFalse(advanced.is_error, advanced.structured_content)
            refreshed = asyncio.run(server.call_tool(
                "dev_flow_get_next_action",
                {"task_id": task_id},
            ))
            self.assertFalse(refreshed.is_error, refreshed.structured_content)
            assurance_action = refreshed.structured_content["result"]["action"]
            assurance = assurance_action["assurance"]
            self.assertEqual(assurance["confidence"], "source-confirmed")
            self.assertTrue(assurance["not_required"]["independent_review"])
            assurance_result_schema = assurance_action["payload_schema"]["properties"][
                "assurance_result"
            ]
            self.assertEqual(
                set(assurance_result_schema["required"]),
                {"obligation_id", "passed", "evidence", "limitations"},
            )
            obligation_id = assurance_action["current_obligation"]["obligation_id"]
            self.assertEqual(
                assurance_result_schema["properties"]["obligation_id"],
                {"const": obligation_id},
            )
            assurance_result = {
                "obligation_id": obligation_id,
                "passed": True,
                "evidence": [{
                    "kind": "command",
                    "reference": "git diff --check",
                    "summary": "Repository check passed",
                }],
                "limitations": [],
            }
            self.assertIsNone(
                next(
                    Draft202012Validator(assurance_result_schema).iter_errors(
                        assurance_result
                    ),
                    None,
                )
            )
            completed = asyncio.run(server.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": assurance_action["id"],
                    "payload": {
                        "summary": "Executed the projected repository check",
                        "assurance_result": assurance_result,
                    },
                    "binding": assurance_action["binding"],
                },
            ))
            self.assertFalse(completed.is_error, completed.structured_content)

    def test_historical_non_enum_impact_is_readable_through_mcp(self) -> None:
        legacy_confidence = "legacy-arbitrary-value"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = self._repository(root, "repository")
            data_dir = root / "data"
            controller = Controller(str(data_dir))
            started = controller.start(
                requirement="Read a historical impact through MCP",
                workflow="lite",
                repositories=(str(repository),),
            )
            task_id = started.task_id
            preflight = controller.next(task_id)
            controller.apply(
                task_id,
                preflight["action"]["action_id"],
                {},
                binding=preflight["action"]["binding"],
            )
            impact = controller.next(task_id)
            with mock.patch.object(
                assurance_module,
                "IMPACT_CONFIDENCE_VALUES",
                (*IMPACT_CONFIDENCE_VALUES, legacy_confidence),
            ):
                controller.apply(
                    task_id,
                    impact["action"]["action_id"],
                    {
                        "summary": "Historical non-enum impact",
                        "driver_result": {
                            "schema": DRIVER_RESULT_SCHEMA,
                            "status": "degraded",
                        },
                        "impact_manifest": {
                            "confidence": legacy_confidence,
                            "entries": [],
                            "edges": [],
                            "risk_triggers": [],
                            "public_behavior": False,
                            "documentation_required": False,
                            "manual_evidence_required": False,
                            "executable_reproduction_required": False,
                            "overflow": False,
                            "limitations": ["Historical confidence provenance"],
                        },
                    },
                    binding=impact["action"]["binding"],
                )
            state_path = data_dir / MODEL_VERSION / "tasks" / task_id / "state.json"
            persisted = state_path.read_bytes()
            server = create_server(str(data_dir))

            task_result = asyncio.run(server.call_tool(
                "dev_flow_get_task",
                {"task_id": task_id},
            ))
            self.assertFalse(task_result.is_error, task_result.structured_content)
            action_result = asyncio.run(server.call_tool(
                "dev_flow_get_next_action",
                {"task_id": task_id},
            ))
            self.assertFalse(action_result.is_error, action_result.structured_content)
            self.assertEqual(
                action_result.structured_content["result"]["action"]["id"],
                "implementation.record",
            )
            self.assertEqual(state_path.read_bytes(), persisted)

    def test_cli_and_mcp_start_apply_have_domain_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            environment = hermetic_subprocess_env(root)
            subprocess.run(["git", "init", "-q"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "config", "user.email", "mcp@example.invalid"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "config", "user.name", "MCP Test"], cwd=repository, env=environment, check=True)
            (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repository, env=environment, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repository, env=environment, check=True)
            cli_data = root / "cli-data"
            mcp_data = root / "mcp-data"
            task_id = "task-parity"

            def normalized_receipt(receipt: dict) -> dict:
                normalized = json.loads(json.dumps(receipt))
                observed_at = normalized["workspace_freshness"]["observed_at"]
                self.assertIsInstance(observed_at, str)
                self.assertTrue(observed_at.endswith("Z"))
                normalized["workspace_freshness"]["observed_at"] = "<observed-at>"
                return normalized

            self._run_cli(
                "--data-dir", str(cli_data), "start", "--requirement", "parity",
                "--workflow", "lite", "--repo", str(repository), "--task-id", task_id,
            )
            server = create_server(str(mcp_data))
            started = asyncio.run(server.call_tool("dev_flow_start_task", {
                "requirement": "parity", "workflow": "lite", "repositories": [str(repository)],
                "task_id": task_id,
            }))
            self.assertFalse(started.is_error)
            cli_projection = self._run_cli("--data-dir", str(cli_data), "next", task_id)["projection"]
            mcp_projection = asyncio.run(server.call_tool("dev_flow_get_next_action", {"task_id": task_id}))
            binding = mcp_projection.structured_content["result"]["action"]["binding"]
            self.assertEqual(binding, cli_projection["action"]["binding"])
            cli_applied = self._run_cli(
                "--data-dir", str(cli_data), "apply", task_id,
                "--action", "task.preflight", "--payload-json", "{}",
                "--binding-json", json.dumps(binding, separators=(",", ":")),
            )
            mcp_applied = asyncio.run(server.call_tool("dev_flow_apply_action", {
                "task_id": task_id, "action_id": "task.preflight", "payload": {}, "binding": binding,
            }))
            self.assertFalse(mcp_applied.is_error)
            self.assertIsNotNone(
                mcp_applied.structured_content["result"]["current"]
            )
            self.assertEqual(
                normalized_receipt(
                    mcp_applied.structured_content["result"]["receipt"]
                ),
                normalized_receipt(cli_applied["receipt"]),
            )
            replayed = asyncio.run(server.call_tool("dev_flow_apply_action", {
                "task_id": task_id,
                "action_id": "task.preflight",
                "payload": {},
                "binding": binding,
            }))
            self.assertTrue(replayed.is_error)
            self.assertIn(
                replayed.structured_content["error"]["code"],
                {"ACTION_BINDING_STALE", "REVISION_CONFLICT"},
            )
            self.assertEqual(
                replayed.structured_content["error"]["recovery"]["tool"],
                "dev_flow_get_next_action",
            )
            decision = {
                "id": "risk-1",
                "kind": "risk-acceptance",
                "subject": "local-risk",
                "outcome": "accepted",
                "rationale": "Bounded parity decision",
                "actor_label": "maintainer",
            }
            cli_decided = self._run_cli(
                "--data-dir", str(cli_data), "decide", task_id,
                "--decision-json", json.dumps(decision, separators=(",", ":")),
            )
            mcp_decided = asyncio.run(server.call_tool("dev_flow_record_decision", {
                "task_id": task_id,
                "decision": decision,
            }))
            self.assertFalse(mcp_decided.is_error)
            self.assertIsNotNone(
                mcp_decided.structured_content["result"]["current"]
            )
            self.assertEqual(
                normalized_receipt(
                    mcp_decided.structured_content["result"]["receipt"]
                ),
                normalized_receipt(cli_decided["receipt"]),
            )
            cli_cancelled = self._run_cli(
                "--data-dir", str(cli_data), "cancel", task_id,
                "--reason", "Parity cancellation",
            )
            mcp_cancelled = asyncio.run(server.call_tool("dev_flow_cancel_task", {
                "task_id": task_id,
                "reason": "Parity cancellation",
            }))
            self.assertFalse(mcp_cancelled.is_error)
            self.assertIsNotNone(
                mcp_cancelled.structured_content["result"]["current"]
            )
            self.assertEqual(
                normalized_receipt(
                    mcp_cancelled.structured_content["result"]["receipt"]
                ),
                normalized_receipt(cli_cancelled["receipt"]),
            )
            cancelled_again = asyncio.run(server.call_tool("dev_flow_cancel_task", {
                "task_id": task_id,
                "reason": "Blind replay",
            }))
            self.assertTrue(cancelled_again.is_error)
            self.assertEqual(
                cancelled_again.structured_content["error"]["code"],
                "ACTION_NOT_AVAILABLE",
            )
            cli_state = Controller(str(cli_data)).show(task_id)
            mcp_state = Controller(str(mcp_data)).show(task_id)
            self.assertEqual((mcp_state.revision, mcp_state.status, mcp_state.current_node),
                             (cli_state.revision, cli_state.status, cli_state.current_node))
            self.assertEqual([record["kind"] for record in mcp_state.records],
                             [record["kind"] for record in cli_state.records])


class MCPStdioProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_catalog_and_read_call_over_real_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            environment = hermetic_subprocess_env(Path(data_dir))
            probe_subprocess_runtime_roots(Path(data_dir), environment)
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "dev_flow_orchestrator.mcp",
                    "--stdio",
                    "--data-dir",
                    data_dir,
                ],
                cwd=ROOT,
                env=environment,
            )
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    self.assertEqual(initialized.server_info.name, "dev-flow")
                    self.assertEqual(initialized.server_info.version, "0.6.9")
                    self.assertEqual(initialized.instructions, SERVER_INSTRUCTIONS)
                    self.assertIsNotNone(initialized.capabilities.tools)
                    self.assertIsNone(initialized.capabilities.resources)
                    self.assertIsNone(initialized.capabilities.prompts)
                    self.assertIsNone(initialized.capabilities.tasks)
                    listed = await session.list_tools()
                    self.assertEqual(tuple(sorted(tool.name for tool in listed.tools)), EXPECTED_TOOLS)
                    result = await session.call_tool("dev_flow_server_info", {})
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content["result"]["model_version"], "0.4.0")
                    failed = await session.call_tool(
                        "dev_flow_get_task",
                        {"task_id": "missing-task"},
                    )
                    self.assertTrue(failed.is_error)
                    self.assertEqual(
                        failed.structured_content["error"]["code"],
                        "TASK_NOT_FOUND",
                    )
                    self.assertEqual(len(failed.content), 1)
                    text = failed.content[0].text
                    self.assertIn("TASK_NOT_FOUND", text)
                    self.assertIn("dev_flow_find_tasks_for_path", text)
                    self.assertNotIn('"schema"', text)
                    self.assertLessEqual(len(text.encode("utf-8")), 4 * 1024)
            # The first clean EOF must release STDIO ownership so the same
            # installed command and data namespace can start again.
            async with stdio_client(parameters) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    restarted = await session.call_tool("dev_flow_server_info", {})
                    self.assertFalse(restarted.is_error)
                    self.assertEqual(restarted.structured_content["result"]["health"]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
