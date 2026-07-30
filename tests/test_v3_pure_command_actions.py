from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import mock

from tests.dev_flow_test_case import DevFlowTestCase, dev_flow


class V3PureCommandActionTests(DevFlowTestCase):
    def _persist_v3(
        self,
        task_id: str,
        *,
        status: str,
        baseline_fetch_approved: bool = False,
    ) -> tuple[Path, dict[str, object]]:
        bundle = dev_flow.workflow_runtime_services().catalog.resolve(
            "full", 3
        )
        state = {
            "schema_version": 3,
            "task_id": task_id,
            "revision": 0,
            "status": status,
            "flow": "full",
            "repositories": [],
            "route": None,
            **copy.deepcopy(
                dev_flow.build_v3_task_creation_fields(
                    task_id,
                    bundle,
                    execution_profile="single-repository",
                )
            ),
        }
        if baseline_fetch_approved:
            state.setdefault("approvals", {})
            remote_evidence = dev_flow._preflight_remote_evidence(
                state
            )
            state["approvals"]["baseline-fetch"] = {
                "approval_id": "baseline-fetch-for-pure-command-test",
                "gate": "baseline-fetch",
                "approved_at": dev_flow.utc_now(),
                "approved_by": "test",
                "note": "test baseline remains current",
                "artifact_sha256": None,
                "preflight_remote_sha256": (
                    dev_flow._sha256_bytes(
                        dev_flow._json_bytes(remote_evidence)
                    )
                ),
                "preflight_remotes": [],
                "fetch_allowed": False,
                "dirty_allowed": False,
            }
        task_dir = dev_flow._task_dir(task_id, self.data)
        dev_flow._ensure_private_dir(task_dir)
        dev_flow._persist_state_transaction(
            None,
            state,
            task_dir,
            "task_started",
            {"status": status},
        )
        return task_dir, dev_flow.load_state(task_id, self.data)

    @staticmethod
    def _impact() -> dict[str, object]:
        return {
            "artifact_id": "impact-v3-pure-command",
            "kind": "impact",
            "sha256": "a" * 64,
            "metadata": {
                "index_provenance_sha256": "b" * 64,
                "impact_generation": 0,
            },
        }

    @staticmethod
    def _event_records(task_dir: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (task_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]

    def test_set_route_uses_typed_action_and_proof_commit(self) -> None:
        task_dir, current = self._persist_v3(
            "pure-set-route", status="INDEXED"
        )
        impact = self._impact()
        with (
            mock.patch.object(
                dev_flow,
                "manager_process_commit_gate_v1",
                return_value=None,
            ),
            mock.patch.object(
                dev_flow,
                "_require_current_impact",
                return_value=impact,
            ),
            mock.patch.object(
                dev_flow,
                "_commit_state",
                side_effect=AssertionError(
                    "schema-v3 set-route used legacy commit"
                ),
            ),
        ):
            response = self.cli(
                "set-route",
                current["task_id"],
                "direct",
                "--reason",
                "keep the pure command inside the kernel",
                "--expected-revision",
                str(current["revision"]),
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["route"]["value"], "direct")
        committed = dev_flow.load_state(current["task_id"], self.data)
        self.assertEqual(committed["status"], "INDEXED")
        self.assertEqual(
            committed["revision"], current["revision"] + 1
        )
        events = self._event_records(task_dir)
        route_events = [
            event for event in events if event["type"] == "route_set"
        ]
        self.assertEqual(len(route_events), 1)
        self.assertEqual(
            route_events[0]["payload"]["edge_id"],
            "full.action.indexed.set-route.v1",
        )
        self.assertTrue(
            any(
                event["type"] == "workflow_audit_fact"
                and event["payload"]["fact_type"]
                == "pure-command-outcome-accepted"
                for event in events
            )
        )

    def test_approve_uses_typed_gate_outcome_and_intent_binding(
        self,
    ) -> None:
        task_dir, current = self._persist_v3(
            "pure-approve",
            status="INDEXED",
            baseline_fetch_approved=True,
        )
        with (
            mock.patch.object(
                dev_flow,
                "manager_process_commit_gate_v1",
                return_value=None,
            ),
            mock.patch.object(
                dev_flow,
                "_commit_state",
                side_effect=AssertionError(
                    "schema-v3 approve used legacy commit"
                ),
            ),
        ):
            response = self.cli(
                "approve",
                current["task_id"],
                "--gate",
                "impact-degraded",
                "--note",
                "operator accepts bounded degraded discovery",
                "--expected-revision",
                str(current["revision"]),
            )

        self.assertTrue(response["ok"])
        approval = response["approval"]
        self.assertEqual(approval["gate"], "impact-degraded")
        self.assertEqual(
            approval["confirmation_mode"], "explicit-action"
        )
        self.assertTrue(
            approval["intent_id"].startswith(
                "dev-flow-transition-intent/v1:"
            )
        )
        committed = dev_flow.load_state(current["task_id"], self.data)
        self.assertEqual(committed["status"], "INDEXED")
        self.assertEqual(
            committed["approvals"]["impact-degraded"], approval
        )
        events = self._event_records(task_dir)
        approval_events = [
            event
            for event in events
            if event["type"] == "gate_approved"
        ]
        self.assertEqual(len(approval_events), 1)
        self.assertEqual(
            approval_events[0]["payload"]["edge_id"],
            "full.action.indexed.approve-impact-degraded.v1",
        )
        self.assertTrue(
            any(
                event["type"] == "workflow_audit_fact"
                and event["payload"]["fact_type"]
                == "pinned-action-gate-resolved"
                for event in events
            )
        )

    def test_wrong_node_and_unknown_gate_are_zero_write(self) -> None:
        task_dir, current = self._persist_v3(
            "pure-command-rejections", status="IMPACT_REVIEW"
        )
        state_bytes = (task_dir / "state.json").read_bytes()
        event_bytes = (task_dir / "events.jsonl").read_bytes()
        with (
            mock.patch.object(
                dev_flow,
                "manager_process_commit_gate_v1",
                return_value=None,
            ),
            mock.patch.object(
                dev_flow,
                "_require_current_impact",
                return_value=self._impact(),
            ),
        ):
            wrong_node = self.cli(
                "set-route",
                current["task_id"],
                "direct",
                "--reason",
                "not placed on this pinned node",
                "--expected-revision",
                str(current["revision"]),
                expected_code=2,
            )
        self.assertEqual(
            wrong_node["error"]["code"],
            "WORKFLOW_ACTION_PLACEMENT_INVALID",
        )
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), state_bytes
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), event_bytes
        )

        with mock.patch.object(
            dev_flow,
            "manager_process_commit_gate_v1",
            return_value=None,
        ):
            unknown_gate = self.cli(
                "approve",
                current["task_id"],
                "--gate",
                "not-a-gate",
                "--note",
                "must be rejected before mutation",
                "--expected-revision",
                str(current["revision"]),
                expected_code=2,
            )
        self.assertEqual(
            unknown_gate["error"]["code"], "INVALID_ARGUMENT"
        )
        self.assertEqual(
            (task_dir / "state.json").read_bytes(), state_bytes
        )
        self.assertEqual(
            (task_dir / "events.jsonl").read_bytes(), event_bytes
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
