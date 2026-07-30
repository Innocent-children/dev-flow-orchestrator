from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path
from unittest import mock


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case


dev_flow = test_case.dev_flow


class TaskStateRuntimeIntegrationTests(test_case.DevFlowTestCase):
    def _write_state(self, task_id: str, state: object) -> Path:
        task_dir = self.data / "tasks" / task_id
        task_dir.mkdir(parents=True)
        state_path = task_dir / "state.json"
        state_path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return state_path

    def _pending_event(
        self,
        task_id: str,
        *,
        revision: int,
        status: str,
    ) -> dict[str, object]:
        return {
            "event_id": f"{task_id}-pending",
            "evidence_contract_version": (
                dev_flow.EVIDENCE_CONTRACT_VERSION
            ),
            "task_id": task_id,
            "type": "pending-test-event",
            "at": "2026-07-27T00:00:00.000Z",
            "actor": "test",
            "previous_revision": revision - 1,
            "revision": revision,
            "status": status,
            "payload": {},
        }

    def test_future_task_show_is_tolerant_and_strictly_read_only(
        self,
    ) -> None:
        state = {
            "schema_version": 4,
            "task_id": "future-show",
            "revision": 9,
            "status": "WAITING_EXTERNAL",
            "flow": "full",
            "workflow_ref": {
                "id": "future-workflow",
                "version": 8,
                "schema": "dev-flow-workflow/v2",
                "graph_sha256": "a" * 64,
                "bundle_sha256": "b" * 64,
                "future_identity_field": "retained",
            },
            "pending_event": {"future": "outbox-contract"},
            "token": "must-not-leak",
        }
        state_path = self._write_state("future-show", state)
        before = state_path.read_bytes()

        response = self.cli("show", "--task", "future-show")

        self.assertTrue(response["ok"])
        self.assertTrue(response["read_only"])
        self.assertFalse(response["inspection"]["supported"])
        self.assertFalse(response["inspection"]["mutation_ready"])
        self.assertEqual(
            response["inspection"]["schema_version"], 4
        )
        self.assertEqual(
            response["inspection"]["workflow_ref"]["version"], 8
        )
        self.assertEqual(response["task"]["token"], "<redacted>")
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((state_path.parent / "events.jsonl").exists())

    def test_unknown_pinned_bundle_show_does_not_recover_outbox(
        self,
    ) -> None:
        state = {
            "schema_version": 3,
            "task_id": "unknown-bundle-show",
            "revision": 2,
            "status": "RUNNING",
            "flow": "full",
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": "full",
                "version": 3,
                "schema": "dev-flow-workflow/v1",
                "graph_sha256": "a" * 64,
                "bundle_sha256": "f" * 64,
            },
            "node_instances": [],
            "pending_event": {"future": "outbox-contract"},
        }
        state_path = self._write_state(
            "unknown-bundle-show", state
        )
        before = state_path.read_bytes()

        response = self.cli(
            "show", "--task", "unknown-bundle-show", "--compact"
        )

        self.assertTrue(response["read_only"])
        self.assertTrue(response["inspection"]["valid"])
        self.assertFalse(response["inspection"]["mutation_ready"])
        self.assertEqual(
            response["inspection"]["errors"][0]["code"],
            "WORKFLOW_BUNDLE_UNKNOWN",
        )
        self.assertEqual(
            response["summary"]["workflow_ref"]["bundle_sha256"],
            "f" * 64,
        )
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((state_path.parent / "events.jsonl").exists())

    def test_supported_show_keeps_the_legacy_response_contract(
        self,
    ) -> None:
        self._write_state(
            "supported-show",
            {
                "schema_version": 1,
                "task_id": "supported-show",
                "revision": 0,
                "status": "INTAKE",
                "repositories": [],
            },
        )
        args = argparse.Namespace(
            task_option="supported-show",
            task_id=None,
            data_dir=self.data,
            compact=False,
            section=None,
        )

        response = dev_flow.command_show(args)

        self.assertNotIn("read_only", response)
        self.assertNotIn("inspection", response)
        self.assertIn("workflow", response)
        self.assertEqual(response["flow"], "full")
        self.assertEqual(response["task"]["schema_version"], 1)

    def test_revision_conflict_precedes_workflow_validation_and_delivery(
        self,
    ) -> None:
        task_id = "revision-before-workflow"
        state = {
            "schema_version": 1,
            "task_id": task_id,
            "revision": 3,
            "status": "INTAKE",
            "flow": "experimental",
            "repositories": [],
            "pending_event": self._pending_event(
                task_id, revision=3, status="INTAKE"
            ),
        }
        state_path = self._write_state(task_id, state)
        before = state_path.read_bytes()

        with (
            mock.patch.object(
                dev_flow,
                "validate_task_state_for_mutation",
                wraps=dev_flow.validate_task_state_for_mutation,
            ) as validate,
            mock.patch.object(
                dev_flow, "_flush_pending_event"
            ) as flush,
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                with dev_flow._locked_state(task_id, self.data, 2):
                    self.fail("revision-conflicted state must not be yielded")

        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        validate.assert_not_called()
        flush.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)

    def test_unresolved_legacy_workflow_precedes_pending_delivery(
        self,
    ) -> None:
        task_id = "workflow-before-outbox"
        state = {
            "schema_version": 1,
            "task_id": task_id,
            "revision": 1,
            "status": "INTAKE",
            "flow": "experimental",
            "repositories": [],
            "pending_event": self._pending_event(
                task_id, revision=1, status="INTAKE"
            ),
        }
        state_path = self._write_state(task_id, state)
        before = state_path.read_bytes()

        with mock.patch.object(
            dev_flow, "_flush_pending_event"
        ) as flush:
            with self.assertRaises(dev_flow.FlowError) as raised:
                with dev_flow._locked_state(task_id, self.data, 1):
                    self.fail("unresolved workflow must not be yielded")

        self.assertEqual(
            raised.exception.code, "LEGACY_WORKFLOW_AMBIGUOUS"
        )
        flush.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((state_path.parent / "events.jsonl").exists())

    def test_v3_revision_conflict_precedes_bundle_resolution_and_delivery(
        self,
    ) -> None:
        task_id = "v3-revision-before-workflow"
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 3,
            "status": "RUNNING",
            "flow": "full",
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": "full",
                "version": 3,
                "schema": "dev-flow-workflow/v1",
                "graph_sha256": "a" * 64,
                "bundle_sha256": "f" * 64,
            },
            "node_instances": [],
            "pending_event": {"future": "outbox-contract"},
        }
        state_path = self._write_state(task_id, state)
        before = state_path.read_bytes()

        with (
            mock.patch.object(
                dev_flow,
                "validate_task_state_for_mutation",
                wraps=dev_flow.validate_task_state_for_mutation,
            ) as validate,
            mock.patch.object(
                dev_flow, "_flush_pending_event"
            ) as flush,
        ):
            with self.assertRaises(dev_flow.FlowError) as raised:
                with dev_flow._locked_state(task_id, self.data, 2):
                    self.fail("revision-conflicted state must not be yielded")

        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        validate.assert_not_called()
        flush.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)

    def test_legacy_missing_flow_uses_frozen_full_adapter_for_mutation(
        self,
    ) -> None:
        task_id = "legacy-default-flow"
        self._write_state(
            task_id,
            {
                "schema_version": 1,
                "task_id": task_id,
                "revision": 0,
                "status": "INTAKE",
                "repositories": [],
            },
        )

        with mock.patch.object(
            dev_flow,
            "validate_task_state_for_mutation",
            wraps=dev_flow.validate_task_state_for_mutation,
        ) as validate:
            with dev_flow._locked_state(
                task_id, self.data, 0
            ) as (_, state):
                self.assertEqual(state["flow"], "full")

        validate.assert_called_once()

    def test_unknown_v3_bundle_blocks_mutation_before_outbox_delivery(
        self,
    ) -> None:
        task_id = "unknown-bundle-mutation"
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 1,
            "status": "RUNNING",
            "flow": "full",
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": "full",
                "version": 3,
                "schema": "dev-flow-workflow/v1",
                "graph_sha256": "a" * 64,
                "bundle_sha256": "f" * 64,
            },
            "node_instances": [],
            "pending_event": {"future": "outbox-contract"},
        }
        state_path = self._write_state(task_id, state)
        before = state_path.read_bytes()

        with mock.patch.object(
            dev_flow, "_flush_pending_event"
        ) as flush:
            with self.assertRaises(dev_flow.FlowError) as raised:
                with dev_flow._locked_state(task_id, self.data, 1):
                    self.fail("unknown bundle must not be yielded")

        self.assertEqual(
            raised.exception.code, "WORKFLOW_BUNDLE_UNKNOWN"
        )
        flush.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
