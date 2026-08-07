"""Bounded stored and live read models for the integrated Web UI."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import MODEL_VERSION, PRODUCT_IDENTITY, RELEASE_VERSION
from dev_flow_orchestrator.web_views import live_task_view
from support import RepositoryTestCase, make_repository


class WebReadModelTests(RepositoryTestCase):
    def test_metadata_uses_the_current_product_identity(self) -> None:
        metadata = self.controller.inspect_product()

        self.assertEqual(metadata["version"], RELEASE_VERSION)
        self.assertEqual(metadata["product_identity"], PRODUCT_IDENTITY)
        self.assertEqual(metadata["result"]["version"], RELEASE_VERSION)
        self.assertNotIn("api_version", metadata)

    def test_inventory_is_filtered_paged_and_repository_independent(self) -> None:
        first = self.start_lite("alpha contract")
        second_repository = make_repository(self.root, "second-web-inventory")
        second = self.controller.start(
            requirement="beta contract",
            workflow="full",
            repositories=(str(second_repository),),
        ).task_id

        with mock.patch.object(
            self.controller,
            "_snapshot",
            side_effect=AssertionError("stored inventory must not capture Git"),
        ):
            page = self.controller.inspect_tasks(query="beta", limit=1)

        self.assertEqual(page["view"], "task-inventory")
        self.assertEqual(
            [item["task_id"] for item in page["result"]["tasks"]],
            [second],
        )
        self.assertEqual(page["result"]["page"]["total"], 1)
        self.assertEqual(page["result"]["filters"]["q"], "beta")
        self.assertEqual(page["result"]["tasks"][0]["workflow_version"], MODEL_VERSION)
        self.assertEqual(page["result"]["tasks"][0]["health"], "not-evaluated")
        self.assertNotIn(str(second_repository), json.dumps(page))
        self.assertNotIn("original_contract", json.dumps(page))
        self.assertNotIn("records", json.dumps(page))
        self.assertNotEqual(first, second)

        by_path = self.controller.inspect_tasks(
            repositories=(str(second_repository.resolve()),),
        )
        self.assertEqual(
            [item["task_id"] for item in by_path["result"]["tasks"]],
            [second],
        )
        self.assertNotIn(str(second_repository), json.dumps(by_path))

    def test_stored_detail_has_no_git_binding_or_absolute_path(self) -> None:
        task_id = self.start_lite("stored detail")

        with mock.patch.object(
            self.controller,
            "_snapshot",
            side_effect=AssertionError("stored detail must not capture Git"),
        ):
            detail = self.controller.inspect_task(task_id)

        serialized = json.dumps(detail)
        self.assertEqual(detail["result"]["health"], "not-evaluated")
        self.assertEqual(
            detail["result"]["recovery"]["prompt"],
            "$follow-dev-flow task_id={}".format(task_id),
        )
        self.assertNotIn(str(self.repository), serialized)
        self.assertNotIn(str(self.data_dir), serialized)
        self.assertNotIn('"binding"', serialized)
        self.assertNotIn("records", detail["result"])
        self.assertEqual(
            detail["result"]["task"]["contract"]["criteria"][0]["statement"],
            "stored detail",
        )
        recovery = detail["result"]["recovery"]
        self.assertEqual(recovery["state"]["terminal"], False)
        self.assertEqual(recovery["why_next"]["readiness"], "not-evaluated")
        self.assertEqual(
            recovery["repositories"]["repository_set_id"],
            detail["result"]["task"]["repository_set_id"],
        )
        self.assertIsNone(recovery["assurance"])
        self.assertIsNone(recovery["freshness"])

    def test_inventory_detail_and_recovery_use_the_effective_revised_contract(self) -> None:
        task_id = self.start_lite("original web contract")
        projection = self.controller.next(task_id)
        self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        state, _ = self.controller.store.inspect_with_definition(task_id)
        revised = dict(state.original_contract)
        revised.update(
            {
                "revision": 2,
                "summary": "revised web contract",
                "acceptance_criteria": [
                    {
                        "id": "revised-web",
                        "statement": "revised web criterion",
                    }
                ],
                "scope": ["revised web scope"],
            }
        )
        self.controller.revise_contract(
            task_id,
            contract=revised,
            reason="Exercise effective Web contract projection",
            actor_label="web-test",
        )

        with mock.patch.object(
            self.controller,
            "_snapshot",
            side_effect=AssertionError("stored revised views must not capture Git"),
        ):
            inventory = self.controller.inspect_tasks(query="revised web contract")
            detail = self.controller.inspect_task(task_id)

        row_contract = inventory["result"]["tasks"][0]["contract"]
        detail_contract = detail["result"]["task"]["contract"]
        recovery_contract = detail["result"]["recovery"]["contract"]
        for contract in (row_contract, detail_contract, recovery_contract):
            self.assertEqual(contract["revision"], 2)
            self.assertEqual(contract["summary"], "revised web contract")
            self.assertEqual(contract["criterion_ids"], ["revised-web"])
        self.assertEqual(
            detail["result"]["recovery"]["contract_summary"],
            "revised web contract",
        )

    def test_stored_timeline_is_newest_first_and_terminal_stays_terminal(self) -> None:
        task_id = self.start_lite("terminal timeline")
        projection = self.controller.next(task_id)
        self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        self.controller.cancel(task_id, reason="timeline complete")

        detail = self.controller.inspect_task(task_id, limit=1)
        timeline = detail["result"]["timeline"]
        self.assertEqual(detail["result"]["health"], "terminal")
        self.assertEqual(detail["result"]["why_next"]["readiness"], "terminal")
        self.assertEqual(timeline["page"]["total"], 2)
        self.assertEqual(timeline["page"]["next_offset"], 1)
        self.assertEqual(timeline["records"][0]["action_id"], "task.cancel")
        self.assertEqual(timeline["records"][0]["revision"], 2)
        older = self.controller.inspect_task(task_id, offset=1, limit=1)
        self.assertEqual(
            older["result"]["timeline"]["records"][0]["action_id"],
            "task.preflight",
        )
        self.assertTrue(detail["result"]["artifacts"])

    def test_live_detail_reuses_one_snapshot_and_scrubs_binding(self) -> None:
        task_id = self.start_lite("live detail")
        state, _ = self.controller.store.inspect_with_definition(task_id)
        snapshot = self.controller._snapshot(state)

        with mock.patch.object(
            self.controller,
            "_snapshot",
            return_value=snapshot,
        ) as capture:
            detail = self.controller.inspect_live_task(task_id)

        capture.assert_called_once()
        serialized = json.dumps(detail)
        self.assertEqual(detail["view"], "task-live-detail")
        self.assertEqual(detail["result"]["health"], "ready")
        self.assertEqual(detail["result"]["live"]["snapshot"], "captured")
        self.assertEqual(
            detail["result"]["live"]["snapshot_summary"]["repository_set_id"],
            state.repository_set_id,
        )
        self.assertEqual(
            detail["result"]["live"]["snapshot_summary"]["repositories"][0][
                "repository_id"
            ],
            state.repositories[0].repository_id,
        )
        self.assertIn("freshness", detail["result"]["live"])
        self.assertIn("review", detail["result"]["live"])
        self.assertEqual(detail["result"]["why_next"]["readiness"], "ready")
        self.assertNotIn('"binding"', serialized)
        self.assertNotIn(str(self.repository), serialized)

    def test_blocked_recovery_is_complete_bounded_and_allowlisted(self) -> None:
        task_id = self.start_lite("bounded recovery")
        preflight = self.controller.next(task_id)
        self.controller.apply(
            task_id,
            preflight["action"]["action_id"],
            {},
            binding=preflight["action"]["binding"],
        )
        state, definition = self.controller.store.inspect_with_definition(task_id)
        repository_id = state.repositories[0].repository_id
        secret = str(self.repository)
        projection = {
            "repository_set": {
                "id": state.repository_set_id,
                "digest": "a" * 64,
                "repositories": [
                    {
                        "id": repository_id,
                        "path": secret,
                        "snapshot": {"digest": "b" * 64, "clean": False},
                    }
                ],
            },
            "freshness": {
                "record-safe": {
                    "current": False,
                    "reasons": ["workspace_changed"],
                    "raw": {"path": secret},
                }
            },
            "review": {
                "outcome": "changes-requested",
                "status": "current",
                "current": True,
                "reviewer_available": True,
                "findings": [{"raw": secret}],
            },
            "dossier": {
                "record_id": "dossier-safe",
                "digest": "c" * 64,
                "outcome": "INCOMPLETE",
                "current": False,
                "stale_reasons": ["workspace_changed"],
                "body": {"raw": secret},
            },
            "action": {
                "action_id": "assurance.execute",
                "handler": "assurance.dispatch",
                "binding": {"raw": secret},
                "inputs": [{"raw": secret}],
                "blocked": {
                    "code": "AMBIENT_DRIFT",
                    "message": "unclaimed ambient drift blocks source production",
                    "details": {
                        "ambient_drift": {
                            "present": True,
                            "paths": [
                                {
                                    "repository_id": repository_id,
                                    "path": "src/recovery.py",
                                    "change_kind": "modified",
                                    "raw": secret,
                                },
                                {
                                    "repository_id": repository_id,
                                    "path": secret,
                                    "change_kind": "modified",
                                },
                            ],
                            "member_planes": [
                                {
                                    "repository_id": repository_id,
                                    "planes": ["head", secret],
                                }
                            ],
                            "raw": secret,
                        },
                        "recovery": ["restore", "revise-contract"],
                        "raw": secret,
                    },
                },
                "retry_budget": {
                    "obligation_id": "verify-current",
                    "state": "outstanding",
                    "attempts_used": 1,
                    "allowance": 2,
                    "remaining": 1,
                    "raw": secret,
                },
                "current_obligation": {
                    "obligation_id": "verify-current",
                    "kind": "verification",
                    "repository_ids": [repository_id],
                    "task_change_slice": {"raw": secret},
                },
                "assurance": {
                    "policy": "task-scoped",
                    "profile": "lite",
                    "plan_id": "plan-safe",
                    "plan_digest": "d" * 64,
                    "confidence": "high",
                    "maximum_remaining_actions": 4,
                    "obligation_states": [
                        {
                            "obligation_id": "verify-current",
                            "kind": "verification",
                            "state": "outstanding",
                            "attempts_used": 1,
                            "allowance": 2,
                            "remaining": 1,
                            "raw": secret,
                        },
                        {
                            "obligation_id": "review-exhausted",
                            "kind": "independent-review",
                            "state": "exhausted",
                            "attempts_used": 2,
                            "allowance": 2,
                            "remaining": 0,
                            "raw": secret,
                        },
                    ],
                    "budget": {
                        "maximum_remaining_actions": 4,
                        "used": {"verification": 1, "raw": secret},
                        "remaining": {"verification": 1, "total_action": 4},
                        "raw": secret,
                    },
                    "raw": secret,
                },
            },
            "raw": secret,
        }

        detail = live_task_view(
            state,
            definition,
            "2026-08-05T00:00:00Z",
            projection=projection,
        )

        why_next = detail["result"]["why_next"]
        recovery = detail["result"]["recovery"]
        blocker = why_next["blocker"]
        self.assertEqual(detail["result"]["health"], "blocked")
        self.assertEqual(why_next["declared_action"]["action_id"], "assurance.execute")
        self.assertEqual(why_next["blocked_code"], "AMBIENT_DRIFT")
        self.assertEqual(
            blocker["reason"],
            "unclaimed ambient drift blocks source production",
        )
        self.assertEqual(blocker["recovery_choices"], ["restore", "revise-contract"])
        self.assertEqual(
            blocker["evidence"]["ambient_drift"]["paths"][0]["path"],
            "src/recovery.py",
        )
        self.assertIsNone(
            blocker["evidence"]["ambient_drift"]["paths"][1]["path"]
        )
        self.assertEqual(recovery["retry"]["remaining"], 1)
        self.assertEqual(recovery["assurance"]["budget"]["used"], {"verification": 1})
        self.assertEqual(
            [item["obligation_id"] for item in recovery["outstanding_assurance"]],
            ["verify-current"],
        )
        self.assertEqual(
            [item["obligation_id"] for item in recovery["exhausted_assurance"]],
            ["review-exhausted"],
        )
        self.assertEqual(recovery["freshness"]["counts"]["stale"], 1)
        self.assertEqual(recovery["review"]["finding_count"], 1)
        self.assertEqual(recovery["dossier"]["record_id"], "dossier-safe")
        self.assertEqual(
            recovery["repositories"]["repository_set_id"], state.repository_set_id
        )
        self.assertLessEqual(recovery["recent_timeline"]["returned"], 8)
        serialized = json.dumps(detail)
        self.assertNotIn(secret, serialized)
        self.assertNotIn('"binding"', serialized)
        self.assertNotIn('"raw"', serialized)

    def test_unavailable_live_snapshot_returns_sanitized_health(self) -> None:
        task_id = self.start_lite("unavailable live detail")

        with mock.patch.object(
            self.controller,
            "_snapshot",
            side_effect=DevFlowError(
                "REPOSITORY_UNAVAILABLE",
                "secret repository failure",
                details={"path": str(self.repository)},
            ),
        ):
            detail = self.controller.inspect_live_task(task_id)

        self.assertEqual(detail["result"]["health"], "unavailable")
        self.assertEqual(
            detail["result"]["live"]["error"],
            {"code": "REPOSITORY_UNAVAILABLE"},
        )
        self.assertEqual(detail["result"]["why_next"]["readiness"], "unavailable")
        self.assertIsNone(detail["result"]["why_next"]["declared_action"])
        self.assertEqual(
            detail["result"]["why_next"]["blocked_code"],
            "REPOSITORY_UNAVAILABLE",
        )
        self.assertEqual(
            detail["result"]["recovery"]["why_next"]["blocker"],
            {
                "code": "REPOSITORY_UNAVAILABLE",
                "reason": "Repository observation is unavailable",
                "evidence": None,
                "recovery_choices": [],
            },
        )
        self.assertNotIn("secret repository failure", json.dumps(detail))
        self.assertNotIn(str(self.repository), json.dumps(detail))

    def test_revision_change_during_live_capture_is_stale_without_retry(self) -> None:
        task_id = self.start_lite("stale live detail")
        state, definition = self.controller.store.inspect_with_definition(task_id)
        snapshot = self.controller._snapshot(state)
        changed = replace(state, updated_at="2099-01-01T00:00:00Z")

        with mock.patch.object(
            self.controller.store,
            "inspect_with_definition",
            side_effect=((state, definition), (changed, definition)),
        ), mock.patch.object(self.controller, "_snapshot", return_value=snapshot) as capture:
            with self.assertRaises(DevFlowError) as context:
                self.controller.inspect_live_task(task_id)

        self.assertEqual(context.exception.code, "VIEW_STALE")
        capture.assert_called_once()

    def test_page_bounds_fail_closed(self) -> None:
        task_id = self.start_lite("invalid page")

        for call in (
            lambda: self.controller.inspect_tasks(limit=101),
            lambda: self.controller.inspect_tasks(offset=-1),
            lambda: self.controller.inspect_task(task_id, limit=0),
        ):
            with self.subTest(call=call):
                with self.assertRaises(DevFlowError) as context:
                    call()
                self.assertEqual(context.exception.code, "VIEW_QUERY_INVALID")

    def test_missing_task_and_large_text_responses_are_bounded(self) -> None:
        with self.assertRaises(DevFlowError) as missing:
            self.controller.inspect_task("missing-web-task")
        self.assertEqual(missing.exception.code, "TASK_NOT_FOUND")

        task_id = self.start_lite("x" * 4096)
        detail = self.controller.inspect_task(task_id)
        self.assertLessEqual(len(detail["result"]["task"]["requirement"]), 1024)
        self.assertLess(len(json.dumps(detail)), 64 * 1024)


if __name__ == "__main__":
    unittest.main()
