from __future__ import annotations

import unittest

from tests import test_orchestration_service as orchestration_tests


class V4OrchestrationRuntimeTests(
    orchestration_tests.OrchestrationServiceTests
):
    """Focused exact-full@4 multi-repository runtime dogfood."""

    task_id = "v4-orchestration-runtime"

    def test_exact_full_v4_two_repository_happy_path(self) -> None:
        initial = self.state()
        bundle = (
            orchestration_tests.dev_flow.workflow_runtime_services()
            .catalog.resolve("full", 4)
        )
        self.assertEqual(initial["schema_version"], 3)
        self.assertEqual(initial["execution_profile"], "multi-repository")
        self.assertEqual(
            initial["workflow_ref"],
            {
                "id": "full",
                "version": 4,
                "schema": bundle.graph["schema"],
                "graph_sha256": bundle.graph_sha256,
                "bundle_sha256": bundle.bundle_sha256,
            },
        )

        super().test_two_repository_worktrees_complete_serialized_cas_chain()

        final = self.state()
        self.assertEqual(final["workflow_ref"], initial["workflow_ref"])
        self.assertTrue(
            self.service.finalization_status(
                self.task_id, data_dir=self.data
            )["ready"]
        )
        orchestration = final["orchestration"]
        self.assertEqual(
            set(orchestration["current_results"]),
            {
                child["node_instance_id"]
                for child in orchestration["expansion"]["children"]
            },
        )
        self.assertTrue(
            any(
                barrier["status"] == "CLOSED"
                for barrier in orchestration["barriers"].values()
            )
        )
        self.assertIsNotNone(orchestration["integration_verification"])
        self.assertIsNotNone(orchestration["review"])


def load_tests(
    _loader: unittest.TestLoader,
    _tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    """Keep this module intentionally limited to its one M2 dogfood path."""

    return unittest.TestSuite(
        (
            V4OrchestrationRuntimeTests(
                "test_exact_full_v4_two_repository_happy_path"
            ),
        )
    )


if __name__ == "__main__":
    unittest.main()
