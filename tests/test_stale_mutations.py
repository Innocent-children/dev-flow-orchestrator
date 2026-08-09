"""Current compare-and-swap mutation contracts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import DRIVER_RESULT_SCHEMA
from support import RepositoryTestCase, make_repository


class StaleMutationTests(RepositoryTestCase):
    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def test_store_rejects_stale_revision_after_preflight(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})

        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(task_id, 0, lambda state: state)

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        self.assertEqual(context.exception.details["actual_revision"], 1)

    def test_cancel_cas_conflict_returns_fresh_projection(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        racing = Controller(self.data_dir)
        original_commit = self.controller.store.commit_repository_mutation
        raced = False

        def commit_after_competing_decision(*args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                racing.decide(
                    task_id,
                    decision={
                        "id": "cancel-race-winner",
                        "kind": "risk-acceptance",
                        "subject": "cancel-race",
                        "outcome": "accepted",
                        "rationale": "Exercise the cancel compare-and-swap boundary",
                        "actor_label": "test",
                    },
                )
            return original_commit(*args, **kwargs)

        with mock.patch.object(
            self.controller.store,
            "commit_repository_mutation",
            side_effect=commit_after_competing_decision,
        ):
            with self.assertRaises(DevFlowError) as context:
                self.controller.cancel(task_id, reason="losing cancellation")

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        self.assertEqual(context.exception.details["projection"]["revision"], 2)
        self.assertEqual(
            context.exception.details["projection"]["action"]["action_id"],
            "impact.record",
        )
        state = self.controller.show(task_id)
        self.assertEqual([record["kind"] for record in state.records], ["preflight", "decision"])

    def test_apply_cas_conflict_returns_fresh_projection(self) -> None:
        task_id = self.start_lite()
        self.apply_current(task_id, {})
        projected = self.controller.next(task_id)
        racing = Controller(self.data_dir)
        original_commit = self.controller.store.commit_repository_mutation
        raced = False

        def commit_after_competing_decision(*args, **kwargs):
            nonlocal raced
            if not raced:
                raced = True
                racing.decide(
                    task_id,
                    decision={
                        "id": "apply-race-winner",
                        "kind": "risk-acceptance",
                        "subject": "apply-race",
                        "outcome": "accepted",
                        "rationale": "Exercise the apply compare-and-swap boundary",
                        "actor_label": "test",
                    },
                )
            return original_commit(*args, **kwargs)

        with mock.patch.object(
            self.controller.store,
            "commit_repository_mutation",
            side_effect=commit_after_competing_decision,
        ):
            with self.assertRaises(DevFlowError) as context:
                self.controller.apply(
                    task_id,
                    projected["action"]["action_id"],
                    {
                        "summary": "losing impact",
                        "driver_result": {
                            "schema": DRIVER_RESULT_SCHEMA,
                            "status": "degraded",
                        },
                    },
                    binding=projected["action"]["binding"],
                )

        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        fresh = context.exception.details["projection"]
        self.assertEqual(fresh["revision"], 2)
        self.assertEqual(fresh["action"]["action_id"], "impact.record")
        self.assertEqual(fresh["action"]["binding"]["task_revision"], 2)
        state = self.controller.show(task_id)
        self.assertEqual(
            [record["kind"] for record in state.records],
            ["preflight", "decision"],
        )

    def test_same_revision_foreign_binding_remains_stale(self) -> None:
        task_id = self.start_lite("first")
        foreign_repository = make_repository(self.root, "foreign")
        foreign_task = self.controller.start(
            requirement="second",
            workflow="lite",
            repositories=(str(foreign_repository),),
        ).task_id
        projected = self.controller.next(task_id)
        foreign = self.controller.next(foreign_task)

        with self.assertRaises(DevFlowError) as context:
            self.controller.apply(
                task_id,
                projected["action"]["action_id"],
                {},
                binding=foreign["action"]["binding"],
            )

        self.assertEqual(context.exception.code, "ACTION_BINDING_STALE")
        self.assertEqual(self.controller.show(task_id).revision, 0)


if __name__ == "__main__":
    unittest.main()
