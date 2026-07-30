from __future__ import annotations

import copy

if __package__:
    from .dev_flow_test_case import DevFlowTestCase, dev_flow
else:
    from dev_flow_test_case import DevFlowTestCase, dev_flow


class WorkflowTransitionServiceTests(DevFlowTestCase):
    def _start(self) -> dict:
        repository, _ = self.make_repo("transition-service-repository")
        return self.cli(
            "start",
            "validate every committed movement",
            "--repo",
            str(repository),
            "--task-id",
            "transition-service",
            "--workspace-strategy",
            "in-place",
            "--change-category",
            "docs",
            "--target-path",
            "tracked.txt",
        )

    def test_legacy_command_commit_is_gated_by_one_pinned_edge(self) -> None:
        started = self._start()

        response = self.cli(
            "transition",
            "transition-service",
            "--expected-revision",
            str(started["revision"]),
            "--to",
            "BLOCKED",
            "--note",
            "waiting for an external decision",
            "--preview",
        )
        intent = response["preview"]["intent_id"]
        applied = self.cli(
            "transition",
            "transition-service",
            "--expected-revision",
            str(started["revision"]),
            "--to",
            "BLOCKED",
            "--note",
            "waiting for an external decision",
            "--confirm-intent",
            intent,
        )

        self.assertEqual(applied["status"], "BLOCKED")
        self.assertEqual(applied["revision"], started["revision"] + 1)

    def test_candidate_with_undeclared_state_change_fails_before_commit(
        self,
    ) -> None:
        self._start()
        current = dev_flow.load_state("transition-service", self.data)
        candidate = copy.deepcopy(current)
        candidate["status"] = "BLOCKED"
        candidate["blocked"] = {
            "phase": "manual",
            "from_status": "INTAKE",
            "reason": "blocked",
            "details": [],
            "at": dev_flow.utc_now(),
        }
        candidate["requirement"] = "silently replaced"
        task_dir = dev_flow._task_dir("transition-service", self.data)

        with self.assertRaises(dev_flow.FlowError) as raised:
            dev_flow._commit_state(
                current,
                candidate,
                task_dir,
                "state_transitioned",
                {
                    "from": "INTAKE",
                    "to": "BLOCKED",
                    "note": "blocked",
                },
            )

        self.assertEqual(
            raised.exception.code, "KERNEL_WRITE_OUT_OF_SCOPE"
        )
        unchanged = dev_flow.load_state("transition-service", self.data)
        self.assertEqual(unchanged["status"], "INTAKE")
        self.assertNotEqual(
            unchanged["requirement"], "silently replaced"
        )

    def test_action_event_selects_preflight_edge_not_manual_block(self) -> None:
        self._start()
        current = dev_flow.load_state("transition-service", self.data)
        candidate = copy.deepcopy(current)
        candidate["status"] = "BLOCKED"
        candidate["blocked"] = {
            "phase": "preflight",
            "from_status": "INTAKE",
            "reason": "repository preflight blocked",
            "details": [],
            "at": dev_flow.utc_now(),
        }

        result = dev_flow.validate_workflow_movement_candidate(
            current,
            candidate,
            event_type="preflight_recorded",
            payload={"blockers": ["dirty"]},
        )

        self.assertTrue(result["checked"])
        self.assertEqual(result["action_id"], "preflight")
        self.assertEqual(
            result["edge_id"],
            "lite-legacy.intake.preflight-blocked",
        )

    def test_v3_candidate_cannot_fall_back_to_legacy_shadow_bridge(
        self,
    ) -> None:
        self._start()
        current = dev_flow.load_state("transition-service", self.data)
        current["schema_version"] = 3
        candidate = copy.deepcopy(current)
        candidate["status"] = "BLOCKED"

        with self.assertRaises(
            dev_flow.TransitionEngineError
        ) as raised:
            dev_flow.validate_workflow_movement_candidate(
                current,
                candidate,
                event_type="state_transitioned",
                payload={"note": "blocked"},
            )

        self.assertEqual(
            raised.exception.code, "V3_TRANSITION_SERVICE_REQUIRED"
        )
