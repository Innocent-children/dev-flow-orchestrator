"""Current controller boundary contracts."""

from __future__ import annotations

import stat
import sys
from pathlib import Path
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    PLUGIN_DATA_NAMESPACE,
    RECEIPT_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
)
from support import RepositoryTestCase, make_repository


class ControllerContractTests(RepositoryTestCase):
    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def passing_verification(self, task_id: str, command: str) -> dict:
        projection = self.controller.next(task_id)
        obligation = projection["action"]["current_obligation"]
        result = {
            "obligation_id": obligation["obligation_id"],
            "passed": True,
            "evidence": [{
                "kind": "command",
                "reference": command,
                "summary": "Verification passed",
            }],
            "limitations": [],
        }
        if obligation["kind"] == "independent-review":
            review = projection["action"]["review_contract"]
            result["review"] = {
                "reviewer_available": True,
                "independent": True,
                "reviewer_digest": "a" * 64,
                "review_scope_digest": review["review_scope_digest"],
                "guidance_digest": review["guidance_digest"],
                "workspace_digest": review["workspace_digest"],
                "findings": [],
                "claimed_outcome": "approved",
            }
        return {"summary": "Verification passed", "assurance_result": result}

    def test_data_directory_must_be_disjoint_from_repository(self) -> None:
        cases = []

        inside = self.repository / "data"
        cases.append((
            Controller(str(inside)),
            self.repository,
            inside / PLUGIN_DATA_NAMESPACE / "tasks",
        ))

        cases.append(
            (
                Controller(str(self.repository)),
                self.repository,
                self.repository / PLUGIN_DATA_NAMESPACE / "tasks",
            )
        )

        data_root = self.root / "containing-data"
        data_root.mkdir()
        nested_repository = make_repository(data_root, "nested-repository")
        cases.append((
            Controller(str(data_root)),
            nested_repository,
            data_root / PLUGIN_DATA_NAMESPACE / "tasks",
        ))

        for controller, repository, state_root in cases:
            with self.subTest(data_dir=str(controller.store.root), repository=str(repository)):
                with self.assertRaises(DevFlowError) as context:
                    controller.start(
                        requirement="Keep state outside the repository",
                        workflow="lite",
                        repositories=(str(repository),),
                    )
                self.assertEqual(
                    context.exception.code, "DATA_DIR_INSIDE_REPOSITORY"
                )
                self.assertFalse(state_root.exists())

    def test_state_paths_are_private(self) -> None:
        task_id = self.start_lite()
        state_path = (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "tasks"
            / task_id
            / "state.json"
        )

        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(state_path.parent.stat().st_mode), 0o700)

    def test_explicit_task_id_is_persisted(self) -> None:
        state = self.controller.start(
            requirement="Named task",
            workflow="lite",
            repositories=(str(self.repository),),
            task_id="task-custom",
        )

        self.assertEqual(state.task_id, "task-custom")
        self.assertEqual(self.controller.show("task-custom").task_id, "task-custom")

    def test_wrong_action_is_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                "verification.record",
                {},
                binding=projection["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id), before)

    def test_invalid_payloads_are_rejected_without_mutation(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        cases = (
            ({
                "summary": "x",
                "driver_result": {"schema": DRIVER_RESULT_SCHEMA, "status": "degraded"},
                "extra": 1,
            }, "extra"),
            ({}, "summary"),
            ({
                "summary": 42,
                "driver_result": {"schema": DRIVER_RESULT_SCHEMA, "status": "degraded"},
            }, None),
        )

        for payload, detail in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.apply(
                        task_id,
                        projection["action"]["action_id"],
                        payload,
                        binding=projection["action"]["binding"],
                    )
                self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
                if detail is not None:
                    self.assertIn(detail, str(context.exception.details))
                self.assertEqual(self.controller.show(task_id), before)

    def test_stale_apply_after_terminal_returns_fresh_conflict(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        pending = self.controller.next(task_id)
        self.controller.cancel(task_id, reason="Stop before implementation")
        terminal = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                pending["action"]["action_id"],
                {"summary": "too late"},
                binding=pending["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        fresh = context.exception.details["projection"]
        self.assertEqual(fresh["revision"], terminal.revision)
        self.assertEqual(fresh["status"], "CANCELLED")
        self.assertTrue(fresh["done"])
        self.assertIsNone(fresh["action"])
        self.assertEqual(self.controller.show(task_id), terminal)

    def test_cancel_after_terminal_state_is_rejected(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        self.controller.cancel(task_id, reason="Stop once")

        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="Stop twice")

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")

    def test_entry_stage_cancel_is_a_replayable_first_record(self) -> None:
        task_id = self.start_lite("Cancel before preflight")

        result = self.controller.cancel(
            task_id,
            reason="No delivery work should begin",
        )

        self.assertEqual(result["projection"]["status"], "CANCELLED")
        self.assertTrue(result["projection"]["done"])
        state = self.controller.show(task_id)
        self.assertEqual(state.revision, 1)
        self.assertEqual(len(state.records), 1)
        record = state.records[0]
        self.assertEqual(record["kind"], "action")
        self.assertEqual(record["producer"]["node_id"], "cancel")
        self.assertEqual(
            record["snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(Controller(self.data_dir).show(task_id), state)

    def test_cancel_is_rejected_outside_declared_stages(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        self.apply_current(task_id, {
            "summary": "Impact bounded",
            "driver_result": {"schema": DRIVER_RESULT_SCHEMA, "status": "degraded"},
        })
        self.apply_current(task_id, {"summary": "Implemented"})
        while self.controller.next(task_id)["action"]["action_id"] == "assurance.execute":
            self.apply_current(
                task_id,
                self.passing_verification(task_id, "python3 -m unittest focused"),
            )
        before = self.controller.show(task_id)
        self.assertEqual(before.current_node, "finalize_success")

        with self.assertRaises(DevFlowError) as context:
            self.controller.cancel(task_id, reason="Too late for this stage")

        self.assertEqual(context.exception.code, "ACTION_NOT_AVAILABLE")
        self.assertEqual(self.controller.show(task_id), before)

    def test_missing_task_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.next("task-nope")
        self.assertEqual(context.exception.code, "TASK_NOT_FOUND")

    def test_empty_requirement_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="   ",
                workflow="lite",
                repositories=(str(self.repository),),
            )
        self.assertEqual(context.exception.code, "REQUIREMENT_INVALID")

    def test_truly_unknown_workflow_is_rejected(self) -> None:
        with self.assertRaises(DevFlowError) as context:
            self.controller.start(
                requirement="Unknown workflow",
                workflow="workflow-that-does-not-exist",
                repositories=(str(self.repository),),
            )
        self.assertEqual(context.exception.code, "WORKFLOW_NOT_FOUND")

    def test_apply_returns_current_receipt_and_projection(self) -> None:
        task_id = self.start_lite()
        projected = self.controller.next(task_id)
        result = self.controller.apply(
            task_id,
            projected["action"]["action_id"],
            {},
            binding=projected["action"]["binding"],
        )

        self.assertEqual(
            result["receipt"],
            {
                "schema": RECEIPT_SCHEMA,
                "task_id": task_id,
                "action_id": "task.preflight",
                "committed_revision": 1,
                "status": "ANALYZING",
                "current_node": "impact",
            },
        )
        self.assertEqual(result["projection"]["revision"], 1)
        self.assertEqual(result["projection"]["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(
            len(result["projection"]["repository_set"]["repositories"]),
            1,
        )
        self.assertEqual(
            result["projection"]["action"]["binding"][
                "starting_snapshot_digest"
            ],
            result["projection"]["repository_set"]["digest"],
        )
        self.assertEqual(
            self.controller.show_view(task_id)["current_snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(
            result["projection"]["action"]["action_id"], "impact.record"
        )


if __name__ == "__main__":
    unittest.main()
