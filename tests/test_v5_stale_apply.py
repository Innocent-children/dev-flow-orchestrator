"""A stale or raced apply fails with a fresh projection and corrupts nothing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from v5_support import V5TestCase


class StaleApplyTests(V5TestCase):
    def test_store_rejects_stale_revision(self) -> None:
        task_id = self.start_lite()
        self.controller.apply(task_id, "task.preflight", {})
        with self.assertRaises(DevFlowError) as context:
            self.controller.store.update(
                task_id,
                0,
                lambda state: state,
            )
        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        self.assertEqual(
            context.exception.details["actual_revision"], 1
        )

    def test_apply_conflict_carries_fresh_projection(self) -> None:
        task_id = self.start_lite()
        original_update = self.controller.store.update

        def racing_update(task_id_value, expected_revision, mutation):
            if expected_revision == 0:
                raise DevFlowError(
                    "REVISION_CONFLICT",
                    "task revision is stale",
                    details={
                        "task_id": task_id_value,
                        "expected_revision": expected_revision,
                        "actual_revision": 1,
                    },
                )
            return original_update(task_id_value, expected_revision, mutation)

        with mock.patch.object(
            self.controller.store, "update", side_effect=racing_update
        ):
            with self.assertRaises(DevFlowError) as context:
                self.controller.apply(task_id, "task.preflight", {})
        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        projection = context.exception.details["projection"]
        self.assertEqual(projection["task_id"], task_id)
        self.assertEqual(projection["requirement"], "A test requirement")
        self.assertEqual(projection["revision"], 0)
        self.assertEqual(projection["action"]["action_id"], "task.preflight")

        # state is untouched and a normal apply still succeeds
        self.assertEqual(self.controller.show(task_id).revision, 0)
        result = self.controller.apply(task_id, "task.preflight", {})
        self.assertEqual(result["receipt"]["committed_revision"], 1)

    def test_cancel_conflict_carries_fresh_projection(self) -> None:
        task_id = self.start_lite()
        original_update = self.controller.store.update

        def racing_update(task_id_value, expected_revision, mutation):
            raise DevFlowError(
                "REVISION_CONFLICT",
                "task revision is stale",
                details={
                    "task_id": task_id_value,
                    "expected_revision": expected_revision,
                    "actual_revision": 2,
                },
            )

        with mock.patch.object(
            self.controller.store, "update", side_effect=racing_update
        ):
            with self.assertRaises(DevFlowError) as context:
                self.controller.cancel(task_id, reason="race")
        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        self.assertIn("projection", context.exception.details)


if __name__ == "__main__":
    unittest.main()
