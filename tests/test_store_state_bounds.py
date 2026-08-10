"""Bounded state bytes, JSON depth, and corrupt-inventory isolation."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import unittest
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator import store as store_module
from dev_flow_orchestrator import cli as cli_module
from dev_flow_orchestrator.mcp.application import MCPApplication
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    DRIVER_RESULT_SCHEMA,
    PLUGIN_DATA_NAMESPACE,
)
from support import RepositoryTestCase


class StoreStateBoundsTests(RepositoryTestCase):
    def state_path(self, task_id: str) -> Path:
        return (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

    def write_entry(self, task_id: str, payload: bytes) -> Path:
        path = self.state_path(task_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def derived_state(self, source: bytes, task_id: str, **changes) -> bytes:
        value = json.loads(source.decode("utf-8"))
        value["task_id"] = task_id
        value.update(changes)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    @staticmethod
    def impact_payload() -> dict:
        return {
            "summary": "Impact remains bounded",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "degraded",
            },
            "impact_manifest": {
                "confidence": "unknown",
                "entries": [],
                "edges": [],
                "risk_triggers": [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": False,
                "overflow": False,
                "limitations": ["Depth-bound mutation regression"],
            },
        }

    def test_real_mutation_cannot_commit_an_unreadable_candidate_state(self) -> None:
        state = self.controller.start(
            requirement="Reject an unreadable persisted candidate",
            workflow="investigation",
            repositories=(str(self.repository),),
        )
        task_id = state.task_id
        self.apply_current(task_id, {})
        self.apply_current(task_id, self.impact_payload())
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        path = self.state_path(task_id)
        before_bytes = path.read_bytes()

        evidence = {"leaf": "雪 {[]} \\\" bounded"}
        for index in range(store_module.MAX_STATE_JSON_NESTING_DEPTH - 4):
            evidence = {"level-{}".format(index): evidence}
        payload = {
            "summary": "Candidate exceeds the persisted-state envelope",
            "evidence": evidence,
        }

        try:
            result = self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                payload,
                binding=projection["action"]["binding"],
            )
        except DevFlowError as exc:
            self.assertEqual(exc.code, "STATE_LIMIT_EXCEEDED")
            self.assertEqual(exc.details.get("phase"), "candidate-write")
        else:
            self.assertIn("receipt", result)
            with self.assertRaises(DevFlowError) as unreadable:
                self.controller.show(task_id)
            self.assertEqual(unreadable.exception.code, "STATE_LIMIT_EXCEEDED")
            self.fail("mutation committed a candidate that the same version cannot read")

        self.assertEqual(path.read_bytes(), before_bytes)
        after = self.controller.show(task_id)
        self.assertEqual(after, before)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.current_node, before.current_node)
        self.assertEqual(after.status, before.status)
        self.assertEqual(after.records, before.records)

        application = MCPApplication(self.data_dir)
        rejected = application.call(
            "dev_flow_apply_action",
            {
                "task_id": task_id,
                "action_id": projection["action"]["action_id"],
                "payload": payload,
                "binding": projection["action"]["binding"],
            },
        )
        self.assertTrue(rejected.is_error)
        error = rejected.structured_content["error"]
        self.assertEqual(error["code"], "STATE_LIMIT_EXCEEDED")
        self.assertNotEqual(error["code"], "MCP_COMPLETION_UNCERTAIN")
        self.assertEqual(error["recovery"]["kind"], "refresh-current-action")
        self.assertFalse(error["recovery"]["blind_retry"])
        self.assertEqual(path.read_bytes(), before_bytes)

    def test_shared_envelope_has_symmetric_byte_and_depth_boundaries(self) -> None:
        decode = store_module._decode_persisted_state_envelope

        below = b"0\n"
        at_limit = b"0" + b" " * 7
        self.assertEqual(
            decode(below, maximum_bytes=8, maximum_depth=4),
            0,
        )
        self.assertEqual(
            decode(at_limit, maximum_bytes=8, maximum_depth=4),
            0,
        )
        with self.assertRaises(DevFlowError) as oversized:
            decode(
                at_limit + b" ",
                maximum_bytes=8,
                maximum_depth=4,
                phase="candidate-write",
            )
        self.assertEqual(oversized.exception.code, "STATE_LIMIT_EXCEEDED")
        self.assertEqual(oversized.exception.details["maximum_bytes"], 8)
        self.assertEqual(oversized.exception.details["phase"], "candidate-write")

        boundary = {"leaf": "雪 {[}] \\\""}
        for index in range(3):
            boundary = {"level-{}".format(index): boundary}
        boundary_bytes = json.dumps(
            boundary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            decode(boundary_bytes, maximum_bytes=10_000, maximum_depth=4),
            boundary,
        )
        too_deep = {"outer": boundary}
        with self.assertRaises(DevFlowError) as deep:
            decode(
                json.dumps(too_deep, ensure_ascii=False).encode("utf-8"),
                maximum_bytes=10_000,
                maximum_depth=4,
                phase="candidate-write",
            )
        self.assertEqual(deep.exception.code, "STATE_LIMIT_EXCEEDED")
        self.assertEqual(deep.exception.details["maximum_depth"], 4)

    def test_every_state_replacement_path_uses_the_shared_envelope_gate(self) -> None:
        real_gate = store_module._validated_candidate_state_payload
        with mock.patch.object(
            store_module,
            "_validated_candidate_state_payload",
            wraps=real_gate,
        ) as gate:
            task_id = self.start_lite("All writes share one persisted envelope")
            self.assertEqual(gate.call_count, 1, "task creation bypassed the gate")

            gate.reset_mock()
            with mock.patch.object(
                store_module,
                "validate_state_transition",
                return_value=None,
            ):
                self.controller.store.update(task_id, 0, lambda state: state)
            self.assertEqual(gate.call_count, 1, "ordinary Store update bypassed the gate")

            gate.reset_mock()
            self.apply_current(task_id, {})
            self.assertEqual(
                gate.call_count,
                1,
                "repository-bound mutation bypassed the gate",
            )

    def test_mixed_corruption_is_task_local_bounded_and_read_only(self) -> None:
        healthy = self.start_lite("healthy inventory")
        healthy_bytes = self.state_path(healthy).read_bytes()
        shallow = "task-shallow-bracket-strings"
        shallow_bytes = self.derived_state(
            healthy_bytes,
            shallow,
            requirement=("{}[]\\\"雪" * 2_000),
        )
        self.write_entry(shallow, shallow_bytes)

        byte_limit = 300_000
        payloads = {
            "task-oversized": b" " * (byte_limit + 1),
            "task-deep": b"[" * 100_000 + b"0" + b"]" * 100_000,
            "task-invalid-utf8": b"{\"value\":\xff}",
            "task-duplicate-key": b'{"task_id":"one","task_id":"two"}',
            "task-non-finite": b'{"value":NaN}',
            "task-damaged-record": self.derived_state(
                healthy_bytes,
                "task-damaged-record",
                revision=1,
                records=[{"payload": {"artifact": {"digest": "broken"}}}],
            ),
        }
        paths = {task_id: self.write_entry(task_id, payload) for task_id, payload in payloads.items()}
        before = {task_id: path.read_bytes() for task_id, path in paths.items()}
        locks_root = Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "locks"
        lock_names_before = tuple(sorted(path.name for path in locks_root.iterdir()))

        with mock.patch.object(
            store_module,
            "MAX_STATE_FILE_BYTES",
            byte_limit,
            create=True,
        ), mock.patch.object(
            store_module,
            "MAX_STATE_JSON_NESTING_DEPTH",
            128,
            create=True,
        ):
            entries, diagnostics = self.controller.store.inspect_inventory()
            sanitized = self.controller.inventory_diagnostics()
            for task_id in payloads:
                with self.subTest(task_id=task_id):
                    try:
                        self.controller.inspect_task(task_id)
                    except RecursionError as exc:  # explicit regression signal
                        self.fail("RecursionError escaped direct state inspection: {}".format(exc))
                    except DevFlowError as exc:
                        expected = (
                            "STATE_LIMIT_EXCEEDED"
                            if task_id in {"task-oversized", "task-deep"}
                            else "STATE_INVALID"
                        )
                        self.assertEqual(exc.code, expected)
                    else:
                        self.fail("corrupt task was accepted")

        self.assertEqual(
            tuple(state.task_id for state, _ in entries),
            (healthy, shallow),
        )
        diagnostic_by_task = {item["task_id"]: item for item in diagnostics}
        self.assertEqual(set(diagnostic_by_task), set(payloads))
        self.assertEqual(
            diagnostic_by_task["task-oversized"]["code"],
            "STATE_LIMIT_EXCEEDED",
        )
        self.assertEqual(
            diagnostic_by_task["task-deep"]["code"],
            "STATE_LIMIT_EXCEEDED",
        )
        self.assertEqual(sanitized, diagnostics)
        for diagnostic in diagnostics:
            encoded = json.dumps(diagnostic, sort_keys=True).encode("utf-8")
            self.assertLessEqual(len(encoded), 512)
            self.assertNotIn(str(self.data_dir), encoded.decode("utf-8"))
        self.assertEqual(
            {task_id: path.read_bytes() for task_id, path in paths.items()},
            before,
        )
        self.assertEqual(
            tuple(sorted(path.name for path in locks_root.iterdir())),
            lock_names_before,
        )

    def test_nesting_guard_accepts_boundary_strings_escapes_and_unicode(self) -> None:
        guard = store_module._validate_state_json_nesting
        boundary = 32
        guard("[" * boundary + "0" + "]" * boundary, maximum_depth=boundary)
        guard(
            json.dumps({"value": ("{}[]\\\"雪" * 10_000)}, ensure_ascii=False),
            maximum_depth=boundary,
        )
        with self.assertRaises(DevFlowError) as context:
            guard("{" * (boundary + 1), maximum_depth=boundary)
        self.assertEqual(context.exception.code, "STATE_LIMIT_EXCEEDED")

    def test_current_state_read_preserves_exact_bytes(self) -> None:
        task_id = self.start_lite("byte preserving read")
        path = self.state_path(task_id)
        before = path.read_bytes()
        state, definition = self.controller.store.inspect_with_definition(task_id)
        self.assertEqual(state.task_id, task_id)
        self.assertEqual(definition.workflow_id, "lite")
        self.assertEqual(path.read_bytes(), before)

    def test_cli_and_mcp_expose_bounded_corruption_diagnostics(self) -> None:
        healthy = self.start_lite("adapter inventory")
        corrupt = "task-adapter-corrupt"
        corrupt_path = self.write_entry(
            corrupt,
            b"[" * 1_000 + b"0" + b"]" * 1_000,
        )
        before = corrupt_path.read_bytes()
        corrupt_lock = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "locks"
            / (corrupt + ".lock")
        )

        with mock.patch.object(
            store_module,
            "MAX_STATE_JSON_NESTING_DEPTH",
            32,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                cli_rc = cli_module.main([
                    "--data-dir",
                    self.data_dir,
                    "list",
                ])
            cli_result = json.loads(output.getvalue())
            application = MCPApplication(self.data_dir)
            inventory = application.call("dev_flow_list_tasks", {})
            detail = application.call(
                "dev_flow_get_task",
                {"task_id": corrupt, "offset": 0, "limit": 20},
            )

        self.assertEqual(cli_rc, 0)
        self.assertEqual(
            [item["task_id"] for item in cli_result["tasks"]],
            [healthy],
        )
        self.assertEqual(
            cli_result["diagnostics"],
            [{"code": "STATE_LIMIT_EXCEEDED", "task_id": corrupt}],
        )
        self.assertFalse(inventory.is_error)
        self.assertEqual(
            [item["task_id"] for item in inventory.structured_content["result"]["tasks"]],
            [healthy],
        )
        self.assertEqual(
            inventory.structured_content["result"]["diagnostics"],
            [{"code": "STATE_LIMIT_EXCEEDED", "task_id": corrupt}],
        )
        self.assertTrue(detail.is_error)
        error = detail.structured_content["error"]
        self.assertEqual(error["code"], "STATE_LIMIT_EXCEEDED")
        self.assertEqual(error["recovery"]["kind"], "inspect-diagnostics")
        self.assertFalse(error["recovery"]["blind_retry"])
        self.assertNotIn(str(self.data_dir), json.dumps(detail.structured_content))
        self.assertEqual(corrupt_path.read_bytes(), before)
        self.assertFalse(corrupt_lock.exists())


if __name__ == "__main__":
    unittest.main()
