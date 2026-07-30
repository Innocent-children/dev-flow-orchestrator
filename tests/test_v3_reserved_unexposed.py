from __future__ import annotations

import copy
import json
from unittest import mock

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class ReservedUnexposedV3Tests(DevFlowTestCase):
    def _state(self, flow: str = "full") -> dict[str, object]:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            flow, 3
        )
        return {
            "schema_version": 3,
            "task_id": f"reserved-{flow}",
            "revision": 7,
            "status": "INTAKE",
            "flow": flow,
            "execution_profile": "single-repository",
            "workflow_ref": {
                "id": bundle.workflow_id,
                "version": bundle.workflow_version,
                "schema": bundle.graph["schema"],
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            },
            "node_instances": [],
        }

    def test_creation_targets_inactive_v4_without_exposing_production(
        self,
    ) -> None:
        for flow in ("full", "lite"):
            with self.subTest(flow=flow):
                selection = dev_flow.select_task_creation_workflow(
                    flow, 1
                )
                self.assertEqual(selection["kind"], "legacy")
                self.assertEqual(selection["schema_version"], 2)
                with self.assertRaises(
                    dev_flow.WorkflowCatalogError
                ) as raised:
                    dev_flow.select_task_creation_workflow(
                        flow, 1, require_schema_v3=True
                    )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_CREATION_INACTIVE",
                )
                self.assertEqual(
                    raised.exception.details["workflow_version"], 4
                )

    def test_exact_reserved_identities_remain_inspectable_but_not_mutable(
        self,
    ) -> None:
        expected = {
            "full": (
                "31b82d3774c56546b9d28237a0dd68226ff0516d247cc0b18457294a0d3b4a12"
            ),
            "lite": (
                "111791bb7dd660dbb22842411cd8af87b8bc103478d0d6414900a993ef326bf3"
            ),
        }
        for flow, digest in expected.items():
            with self.subTest(flow=flow):
                state = self._state(flow)
                before = copy.deepcopy(state)

                inspection = dev_flow.inspect_loaded_task_state(state)

                self.assertTrue(inspection["valid"])
                self.assertFalse(inspection["mutation_ready"])
                self.assertEqual(
                    inspection["workflow"]["bundle_sha256"], digest
                )
                historical = inspection["historical_status"]
                self.assertEqual(
                    historical["kind"], "reserved-unexposed"
                )
                self.assertEqual(
                    historical["workflow"]["bundle_sha256"], digest
                )
                self.assertFalse(
                    historical["safety_control"]["available"]
                )
                self.assertEqual(state, before)

                with self.assertRaises(
                    dev_flow.WorkflowStateError
                ) as raised:
                    dev_flow.resolve_loaded_task_workflow(
                        state, purpose="mutation"
                    )
                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_RESERVED_UNEXPOSED",
                )
                self.assertEqual(state, before)

    def test_agent_projection_reports_exact_v3_blocker_without_actions(
        self,
    ) -> None:
        state = self._state("full")
        before = copy.deepcopy(state)

        projected = dev_flow.build_workflow_task_next(
            state, data_dir=self.data
        )
        if "artifact" in projected:
            content, _ = dev_flow.resolve_workflow_protocol_artifact(
                str(state["task_id"]),
                projected["artifact"]["locator"],
                data_dir=self.data,
            )
            projected = json.loads(content.decode("utf-8"))

        self.assertEqual(projected["contract"], "agent-v1")
        self.assertEqual(projected["workflow"], state["workflow_ref"])
        self.assertEqual(projected["actions"], [])
        self.assertEqual(
            projected["condition"]["kind"], "historical-blocked"
        )
        self.assertEqual(
            projected["condition"]["code"],
            "WORKFLOW_RESERVED_UNEXPOSED",
        )
        self.assertEqual(
            projected["locator"]["kind"], "reserved-unexposed-v3"
        )
        self.assertEqual(
            projected["locator"]["safety_control"], "unavailable"
        )
        self.assertNotIn("@4", json.dumps(projected, sort_keys=True))
        self.assertEqual(state, before)

    def test_read_only_open_and_rejected_mutation_preserve_persisted_bytes(
        self,
    ) -> None:
        state = self._state("full")
        task_dir = dev_flow._task_dir(
            str(state["task_id"]), self.data
        )
        dev_flow._ensure_private_dir(task_dir)
        state_path = task_dir / "state.json"
        dev_flow._atomic_write_json(state_path, state)
        before = state_path.read_bytes()

        loaded, inspection = dev_flow.load_state_for_inspection(
            str(state["task_id"]), self.data
        )

        self.assertEqual(
            loaded["workflow_ref"], state["workflow_ref"]
        )
        self.assertIsNotNone(inspection)
        self.assertEqual(state_path.read_bytes(), before)
        with self.assertRaises(dev_flow.FlowError) as raised:
            with dev_flow._locked_state(
                str(state["task_id"]),
                self.data,
                int(state["revision"]),
            ):
                self.fail("reserved-unexposed mutation was authorized")
        self.assertEqual(
            raised.exception.code, "WORKFLOW_RESERVED_UNEXPOSED"
        )
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((task_dir / "events.jsonl").exists())

    def test_recovery_resolution_allows_exact_idempotent_outbox_completion(
        self,
    ) -> None:
        state = self._state("lite")
        state["pending_event"] = {
            "event_id": "already-authoritatively-committed",
            "task_id": state["task_id"],
            "revision": state["revision"],
            "previous_revision": int(state["revision"]) - 1,
            "status": state["status"],
            "type": "task_already_committed",
            "at": "2026-07-29T00:00:00+00:00",
            "actor": "historical-controller",
            "payload": {},
        }
        before = copy.deepcopy(state)

        resolution = dev_flow.resolve_loaded_task_workflow(
            state, purpose="recovery"
        )

        self.assertEqual(
            resolution["bundle_sha256"],
            state["workflow_ref"]["bundle_sha256"],
        )
        self.assertEqual(state, before)
        task_dir = dev_flow._task_dir(
            str(state["task_id"]), self.data
        )
        dev_flow._ensure_private_dir(task_dir)
        dev_flow._atomic_write_json(task_dir / "state.json", state)

        with mock.patch.object(
            dev_flow,
            "_migrate_sensitive_state",
            side_effect=AssertionError(
                "reserved-unexposed load must not migrate state"
            ),
        ):
            state = dev_flow._finish_loaded_state(
                task_dir / "state.json", state
            )
        first_events = (task_dir / "events.jsonl").read_bytes()
        first_state = (task_dir / "state.json").read_bytes()
        dev_flow._flush_pending_event(task_dir, state)

        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), first_events
        )
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), first_state
        )
        self.assertNotIn("pending_event", state)
        persisted = json.loads(first_state.decode("utf-8"))
        self.assertEqual(
            persisted["workflow_ref"], before["workflow_ref"]
        )

    def test_nonexact_identity_is_not_classified_as_reserved_unexposed(
        self,
    ) -> None:
        for field, replacement in (
            ("schema", "dev-flow-workflow/v999"),
            ("graph_sha256", "e" * 64),
            ("bundle_sha256", "f" * 64),
        ):
            with self.subTest(field=field):
                state = self._state("full")
                state["workflow_ref"][field] = replacement
                self.assertIsNone(
                    dev_flow._workflow_runtime_reserved_unexposed_v3(
                        state
                    )
                )
                inspection = dev_flow.inspect_loaded_task_state(state)
                self.assertNotIn("historical_status", inspection)
                self.assertFalse(
                    any(
                        error.get("code")
                        == "WORKFLOW_RESERVED_UNEXPOSED"
                        for error in inspection["errors"]
                    )
                )

    def test_public_load_rejects_nonexact_identity_before_outbox_delivery(
        self,
    ) -> None:
        for index, (field, replacement) in enumerate(
            (
                ("schema", "dev-flow-workflow/v999"),
                ("graph_sha256", "e" * 64),
                ("bundle_sha256", "f" * 64),
            )
        ):
            with self.subTest(field=field):
                state = self._state("lite")
                state["task_id"] = f"reserved-lite-mismatch-{index}"
                state["workflow_ref"][field] = replacement
                state["pending_event"] = {
                    "event_id": f"must-not-be-delivered-{index}",
                    "task_id": state["task_id"],
                    "revision": state["revision"],
                    "previous_revision": int(state["revision"]) - 1,
                    "status": state["status"],
                    "type": "task_already_committed",
                    "at": "2026-07-29T00:00:00+00:00",
                    "actor": "historical-controller",
                    "payload": {},
                }
                task_dir = dev_flow._task_dir(
                    str(state["task_id"]), self.data
                )
                dev_flow._ensure_private_dir(task_dir)
                state_path = task_dir / "state.json"
                dev_flow._atomic_write_json(state_path, state)

                with mock.patch.object(
                    dev_flow,
                    "_recover_pending_event",
                    side_effect=AssertionError(
                        "nonexact workflow identity must fail before delivery"
                    ),
                ):
                    with self.assertRaises(
                        dev_flow.FlowError
                    ) as raised:
                        dev_flow.load_state(state_path)

                self.assertEqual(
                    raised.exception.code,
                    "WORKFLOW_RESERVED_UNEXPOSED_IDENTITY_MISMATCH",
                )
                self.assertFalse(
                    (task_dir / "events.jsonl").exists()
                )
                persisted = json.loads(
                    state_path.read_text(encoding="utf-8")
                )
                self.assertIn("pending_event", persisted)
