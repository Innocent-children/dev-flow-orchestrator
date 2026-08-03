"""Focused current ledger, binding, contract, assurance, and dossier journeys."""

from __future__ import annotations

import contextlib
import io
import json
from collections.abc import Mapping
from pathlib import Path
import sys
import unittest


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.cli import main as cli_main
import dev_flow_orchestrator.product as product_module
from dev_flow_orchestrator.delivery import (
    CONTRACT_SCHEMA,
    contract_digest,
    seal_record,
)
from dev_flow_orchestrator.model import DevFlowError, json_value
from dev_flow_orchestrator.product import (
    DRIVER_RESULT_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
)
from dev_flow_orchestrator.snapshot import repository_snapshot
from dev_flow_orchestrator.yaml_subset import load as load_yaml_subset
from support import RepositoryTestCase


def revised_contract(revision: int, criterion: str = "revised") -> dict:
    return {
        "schema": CONTRACT_SCHEMA,
        "revision": revision,
        "summary": "Revised delivery scope",
        "acceptance_criteria": [
            {"id": criterion, "statement": "The revised scope is verified"}
        ],
        "scope": ["Revised scope"],
        "constraints": ["One prepared repository-set member"],
        "risks": [],
        "non_goals": [],
        "open_questions": [],
    }


def driver_result(status: str, **details: object) -> dict:
    return {
        "schema": DRIVER_RESULT_SCHEMA,
        "status": status,
        **details,
    }


class DeliveryRuntimeTests(RepositoryTestCase):
    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def preflight(self, task_id: str) -> None:
        self.apply_current(task_id, {})

    def repository_id(self, task_id: str) -> str:
        state = self.controller.show(task_id)
        self.assertEqual(len(state.repositories), 1)
        return state.repositories[0].repository_id

    def verification_payload(
        self,
        task_id: str,
        *,
        passed: bool,
        criteria: dict,
        command: str,
        summary: str,
    ) -> dict:
        repository_id = self.repository_id(task_id)
        return {
            "passed": passed,
            "command": command,
            "coverage": {
                "schema": VERIFICATION_COVERAGE_SCHEMA,
                "criteria": criteria,
                "repositories": {
                    repository_id: {"passed": passed, "command": command}
                },
                "integration": {"passed": passed, "command": command},
            },
            "summary": summary,
        }

    def sole_member_snapshot(self, task_id: str, snapshot: object) -> dict:
        state = self.controller.show(task_id)
        return repository_snapshot(
            snapshot,
            state.repositories,
            self.repository_id(task_id),
        )

    def resource_payload(self, task_id: str, items: list[dict]) -> dict:
        repository_id = self.repository_id(task_id)
        return {
            "items": [
                {"repository_id": repository_id, **item}
                for item in items
            ]
        }

    def source_action(self, task_id: str, payload: dict, marker: str) -> None:
        projection = self.controller.next(task_id)
        with (self.repository / "a.txt").open("a", encoding="utf-8") as stream:
            stream.write(marker + "\n")
        self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def state_path(self, task_id: str) -> Path:
        return Path(self.data_dir) / "tasks" / task_id / "state.json"

    def decision(
        self,
        decision_id: str,
        *,
        kind: str = "risk-acceptance",
        subject: str = "local-risk",
        outcome: str = "accepted",
    ) -> dict:
        return {
            "id": decision_id,
            "kind": kind,
            "subject": subject,
            "outcome": outcome,
            "rationale": "Bounded personal-delivery decision",
            "actor_label": "maintainer",
        }

    def start_feature(self, requirement: str = "Deliver a reviewed feature") -> str:
        return self.controller.start(
            requirement=requirement,
            workflow="feature",
            repositories=(str(self.repository),),
        ).task_id

    def advance_feature_to_review(self, task_id: str, marker: str) -> None:
        self.apply_current(
            task_id,
            {"summary": "Impact checked", "driver_result": driver_result("available")},
        )
        self.apply_current(
            task_id,
            {
                "summary": "Plan recorded",
                "resources": {"items": []},
                "driver_result": driver_result("available"),
            },
        )
        self.source_action(
            task_id, {"summary": "Implementation complete"}, marker + "-implementation"
        )
        self.source_action(
            task_id, {"summary": "Documentation complete"}, marker + "-documentation"
        )
        criterion_ids = self.controller.next(task_id)["contract"]["criterion_ids"]
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={criterion_id: "proven" for criterion_id in criterion_ids},
                summary="Focused verification passed",
            ),
        )

    def review_payload(
        self, outcome: str, assurance: str, summary: str = "Review recorded"
    ) -> dict:
        return {
            "outcome": outcome,
            "assurance": assurance,
            "findings": {},
            "summary": summary,
            "driver_result": driver_result(
                "available" if assurance == "independent" else "unavailable"
            ),
        }

    def write_linear_workflow(self, path: Path, *, description: str) -> None:
        document = load_yaml_subset(
            (SRC.parent / "workflows" / "lite.yaml").read_text(encoding="utf-8")
        )
        self.assertIsInstance(document, dict)
        document["id"] = path.stem
        document["description"] = description
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_current_driver_and_coverage_schemas_succeed_and_are_recorded(self) -> None:
        driver_task_id = self.start_feature("Record the current driver schema")
        self.preflight(driver_task_id)
        driver_apply = self.apply_current(
            driver_task_id,
            {
                "summary": "Impact checked",
                "driver_result": driver_result("available"),
            },
        )
        driver_record = self.controller.show(driver_task_id).records[-1]

        self.assertEqual(driver_apply["projection"]["current_node"], "planning")
        self.assertEqual(
            driver_record["producer"]["driver"]["result"]["schema"],
            DRIVER_RESULT_SCHEMA,
        )
        self.assertEqual(
            driver_record["payload"]["driver_result"]["schema"],
            DRIVER_RESULT_SCHEMA,
        )

        coverage_task_id = self.start_lite("Record the current coverage schema")
        self.preflight(coverage_task_id)
        self.source_action(
            coverage_task_id,
            {"summary": "Implementation complete"},
            "coverage-schema",
        )
        verification_apply = self.apply_current(
            coverage_task_id,
            self.verification_payload(
                coverage_task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={"requirement": "proven"},
                summary="Current coverage schema accepted",
            ),
        )
        verification_record = self.controller.show(coverage_task_id).records[-1]

        self.assertEqual(
            verification_apply["projection"]["current_node"],
            "finalize_success",
        )
        self.assertEqual(
            verification_record["payload"]["coverage"]["schema"],
            VERIFICATION_COVERAGE_SCHEMA,
        )
        self.assertEqual(
            verification_record["artifact"]["body"]["coverage"]["schema"],
            VERIFICATION_COVERAGE_SCHEMA,
        )

    def test_driver_result_missing_or_unsupported_schema_fails_atomically(self) -> None:
        task_id = self.start_feature("Reject invalid driver schemas")
        self.preflight(task_id)
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        unsupported_schema = (
            DRIVER_RESULT_SCHEMA.rsplit("/", 1)[0] + "/unsupported"
        )
        invalid_results = (
            ("missing", {"status": "available"}),
            (
                "unsupported",
                {"schema": unsupported_schema, "status": "available"},
            ),
        )

        for case, invalid_result in invalid_results:
            with self.subTest(case=case):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.apply(
                        task_id,
                        projection["action"]["action_id"],
                        {
                            "summary": "Impact checked",
                            "driver_result": invalid_result,
                        },
                        binding=projection["action"]["binding"],
                    )
                self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
                self.assertEqual(self.controller.show(task_id), before)

    def test_coverage_missing_or_unsupported_schema_fails_atomically(self) -> None:
        task_id = self.start_lite("Reject invalid coverage schemas")
        self.preflight(task_id)
        self.source_action(
            task_id,
            {"summary": "Implementation complete"},
            "invalid-coverage-schema",
        )
        projection = self.controller.next(task_id)
        before = self.controller.show(task_id)
        valid_payload = self.verification_payload(
            task_id,
            passed=True,
            command="python3 focused_test.py",
            criteria={"requirement": "proven"},
            summary="Coverage schema validation",
        )
        missing_schema = json_value(valid_payload)
        del missing_schema["coverage"]["schema"]
        unsupported_schema = json_value(valid_payload)
        unsupported_schema["coverage"]["schema"] = (
            VERIFICATION_COVERAGE_SCHEMA.rsplit("/", 1)[0] + "/unsupported"
        )

        for case, invalid_payload in (
            ("missing", missing_schema),
            ("unsupported", unsupported_schema),
        ):
            with self.subTest(case=case):
                with self.assertRaises(DevFlowError) as context:
                    self.controller.apply(
                        task_id,
                        projection["action"]["action_id"],
                        invalid_payload,
                        binding=projection["action"]["binding"],
                    )
                self.assertEqual(context.exception.code, "NODE_OUTPUT_INVALID")
                self.assertEqual(self.controller.show(task_id), before)

    def test_lite_golden_path_is_revision_zero_then_one_record_per_mutation(self) -> None:
        task_id = self.start_lite("Deliver the requested behavior")
        created = self.controller.show(task_id)
        self.assertEqual(created.revision, 0)
        self.assertEqual(created.records, ())
        self.assertEqual(created.original_contract["revision"], 1)
        self.assertEqual(created.original_contract["summary"], "Deliver the requested behavior")
        self.assertEqual(
            [item["id"] for item in created.original_contract["acceptance_criteria"]],
            ["requirement"],
        )
        self.assertEqual(
            self.controller.next(task_id)["contract"]["digest"],
            contract_digest(created.original_contract),
        )

        self.preflight(task_id)
        self.source_action(task_id, {"summary": "Implemented"}, "implementation")
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={"requirement": "proven"},
                summary="Focused verification passed",
            ),
        )
        result = self.apply_current(
            task_id,
            {
                "summary": "Delivered",
                "remaining_risks": {},
                "handoff": "Ready to use",
            },
        )
        self.assertTrue(result["projection"]["done"])
        self.assertEqual(result["projection"]["status"], "DONE")
        self.assertEqual(result["projection"]["dossier"]["outcome"], "success")
        self.assertIsNone(result["projection"]["action"])
        self.assertEqual(
            set(result["projection"]["dossier"]),
            {
                "schema",
                "record_id",
                "digest",
                "repository_set_id",
                "outcome",
                "coverage",
                "current",
                "stale_reasons",
            },
        )
        self.assertNotIn("records", result["projection"])
        self.assertNotIn("body", result["projection"]["dossier"])
        final = Controller(self.data_dir).show(task_id)
        self.assertEqual(final.revision, len(final.records))
        self.assertEqual([record["task_revision"] for record in final.records], [1, 2, 3, 4])

    def test_preflight_precedes_decisions_and_advanced_binding_conflicts(self) -> None:
        task_id = self.start_lite()
        original = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as revision:
            self.controller.revise_contract(
                task_id,
                contract=revised_contract(2),
                reason="Premature scope change",
                actor_label="maintainer",
            )
        self.assertEqual(revision.exception.code, "PREFLIGHT_REQUIRED")
        self.assertEqual(self.controller.show(task_id), original)
        self.assertEqual(
            self.controller.next(task_id)["action"]["action_id"], "task.preflight"
        )

        decision = self.decision("risk-1")
        with self.assertRaises(DevFlowError) as caught:
            self.controller.decide(task_id, decision=decision)
        self.assertEqual(caught.exception.code, "PREFLIGHT_REQUIRED")
        self.assertEqual(self.controller.show(task_id), original)

        self.preflight(task_id)
        old = self.controller.next(task_id)
        self.controller.decide(task_id, decision=decision)
        (self.repository / "a.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(DevFlowError) as stale:
            self.controller.apply(
                task_id,
                old["action"]["action_id"],
                {"summary": "Implementation"},
                binding=old["action"]["binding"],
            )
        self.assertEqual(stale.exception.code, "REVISION_CONFLICT")
        fresh = stale.exception.details["projection"]
        self.assertEqual(fresh["revision"], 2)
        self.assertEqual(fresh["action"]["action_id"], "implementation.record")
        self.assertEqual(self.controller.show(task_id).revision, 2)

    def test_invalid_contracts_fail_atomically_before_task_creation(self) -> None:
        missing = revised_contract(1)
        del missing["scope"]
        duplicate = revised_contract(1, "duplicate")
        duplicate["acceptance_criteria"].append(
            {"id": "duplicate", "statement": "A second statement"}
        )
        oversized = revised_contract(1)
        oversized["scope"] = ["x" * 1000 for _ in range(100)]

        for label, contract in (
            ("missing", missing),
            ("duplicate", duplicate),
            ("oversized", oversized),
        ):
            with self.subTest(label=label):
                task_id = "task-invalid-contract-{}".format(label)
                with self.assertRaises(DevFlowError) as caught:
                    self.controller.start(
                        task_id=task_id,
                        requirement="Invalid contract must not persist",
                        workflow="lite",
                        repositories=(str(self.repository),),
                        contract=contract,
                    )
                self.assertEqual(caught.exception.code, "CONTRACT_INVALID")
                self.assertFalse(self.state_path(task_id).exists())
        self.assertEqual(self.controller.list_tasks(), ())

    def test_explicit_contract_is_immutable_revision_zero_initialization(self) -> None:
        supplied = revised_contract(1, "explicit")
        state = self.controller.start(
            requirement="Explicit contract delivery",
            workflow="lite",
            repositories=(str(self.repository),),
            contract=supplied,
        )
        self.assertEqual(state.revision, 0)
        self.assertEqual(state.records, ())
        self.assertEqual(json_value(state.original_contract), supplied)
        restarted = Controller(self.data_dir)
        self.assertEqual(restarted.show(state.task_id).original_contract, state.original_contract)
        self.assertEqual(
            restarted.next(state.task_id)["contract"]["digest"],
            contract_digest(state.original_contract),
        )

    def test_decision_identity_and_subject_conflicts_do_not_append(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        self.controller.decide(task_id, decision=self.decision("risk-1"))
        committed = self.controller.show(task_id)

        with self.assertRaises(DevFlowError) as reused:
            self.controller.decide(
                task_id,
                decision=self.decision("risk-1", subject="different-risk"),
            )
        self.assertEqual(reused.exception.code, "DECISION_CONFLICT")
        self.assertEqual(self.controller.show(task_id), committed)

        with self.assertRaises(DevFlowError) as same_subject:
            self.controller.decide(task_id, decision=self.decision("risk-2"))
        self.assertEqual(same_subject.exception.code, "DECISION_CONFLICT")
        self.assertEqual(self.controller.show(task_id), committed)

    def test_decisions_and_waivers_replay_after_restart(self) -> None:
        task_id = self.start_feature()
        self.preflight(task_id)
        criterion = self.decision(
            "criterion-waiver-1",
            kind="criterion-waiver",
            subject="requirement",
            outcome="waived",
        )
        review = self.decision(
            "review-waiver-1",
            kind="assurance-waiver",
            subject="review",
            outcome="waived",
        )
        self.controller.decide(task_id, decision=criterion)
        self.controller.decide(task_id, decision=review)

        restarted = Controller(self.data_dir)
        replayed = restarted.show(task_id)
        self.assertEqual(replayed.revision, 3)
        self.assertEqual(
            [record["payload"]["id"] for record in replayed.records[1:]],
            ["criterion-waiver-1", "review-waiver-1"],
        )
        projection = restarted.next(task_id)
        self.assertEqual(projection["current_node"], "impact")
        self.assertEqual(projection["action"]["action_id"], "impact.record")
        with self.assertRaises(DevFlowError) as duplicate:
            restarted.decide(task_id, decision=criterion)
        self.assertEqual(duplicate.exception.code, "DECISION_CONFLICT")
        self.assertEqual(restarted.show(task_id), replayed)

    def test_exhausted_verification_replays_and_contract_revision_resets_budget(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        self.source_action(task_id, {"summary": "Initial implementation"}, "initial")
        failure = self.verification_payload(
            task_id,
            passed=False,
            command="python3 focused_test.py",
            criteria={"requirement": "unverified"},
            summary="Failure retained",
        )
        failed = self.apply_current(
            task_id,
            failure,
        )
        self.assertEqual(failed["projection"]["current_node"], "verification_rework")
        self.assertEqual(self.controller.show(task_id).records[-1]["kind"], "verification")
        restarted_mid_rework = Controller(self.data_dir).next(task_id)
        self.assertFalse(restarted_mid_rework["done"])
        self.assertIsNone(restarted_mid_rework["dossier"])
        self.assertEqual(
            restarted_mid_rework["action"]["action_id"],
            "verification.rework.record",
        )
        self.assertNotIn("records", restarted_mid_rework)
        self.assertTrue(restarted_mid_rework["action"]["inputs"])

        self.source_action(task_id, {"summary": "Bounded repair"}, "repair")
        exhausted = self.apply_current(task_id, failure)
        self.assertEqual(
            exhausted["projection"]["current_node"],
            "finalize_verification_incomplete",
        )
        before_revision = self.controller.show(task_id)
        old_contract = before_revision.original_contract

        revised = self.controller.revise_contract(
            task_id,
            contract=revised_contract(2),
            reason="Acceptance scope changed",
            actor_label="maintainer",
        )
        self.assertEqual(revised["projection"]["current_node"], "implement")
        self.assertEqual(revised["projection"]["contract"]["revision"], 2)
        self.assertEqual(revised["projection"]["action"]["retry_budget"], None)
        revision_record = self.controller.show(task_id).records[-1]
        self.assertEqual(
            revision_record["payload"]["previous_contract_digest"],
            contract_digest(old_contract),
        )
        self.assertEqual(
            revision_record["payload"]["new_contract_digest"],
            revised["projection"]["contract"]["digest"],
        )

        self.controller = Controller(self.data_dir)
        self.source_action(task_id, {"summary": "Revised implementation"}, "revised")
        verification = self.controller.next(task_id)
        self.assertEqual(verification["action"]["retry_budget"]["attempts_used"], 0)
        self.assertEqual(verification["action"]["retry_budget"]["remaining"], 2)
        self.assertEqual(
            sum(
                record["kind"] == "verification"
                for record in self.controller.show(task_id).records
            ),
            2,
        )
        self.assertEqual(
            self.controller.show(task_id).records[-2]["artifact"]["type"],
            "revision-source",
        )
        first_revised_failure = self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=False,
                command="python3 revised_focused_test.py",
                criteria={"revised": "unverified"},
                summary="First failure under the revised contract",
            ),
        )
        self.assertEqual(
            first_revised_failure["projection"]["current_node"],
            "verification_rework",
        )
        self.assertEqual(
            self.controller.show(task_id).records[-1]["producer"]["attempt"],
            1,
        )
        self.source_action(task_id, {"summary": "Second bounded repair"}, "repair-2")
        restarted_verification = Controller(self.data_dir).next(task_id)
        self.assertEqual(
            restarted_verification["action"]["retry_budget"]["attempts_used"],
            1,
        )
        self.assertEqual(
            restarted_verification["action"]["retry_budget"]["remaining"],
            1,
        )

    def test_feature_review_unavailable_succeeds_only_with_exact_waiver(self) -> None:
        state = self.controller.start(
            requirement="Deliver a reviewed feature",
            workflow="feature",
            repositories=(str(self.repository),),
        )
        task_id = state.task_id
        self.preflight(task_id)
        self.apply_current(
            task_id,
            {"summary": "Impact checked", "driver_result": driver_result("available")},
        )
        planning = self.controller.next(task_id)
        plan_dir = self.repository / "openspec" / "changes" / "feature"
        plan_dir.mkdir(parents=True)
        (plan_dir / "proposal.md").write_text("# Proposal\n", encoding="utf-8")
        (plan_dir / "tasks.md").write_text("- [ ] focused test\n", encoding="utf-8")
        resources = self.resource_payload(
            task_id,
            [
                {
                    "path": "openspec/changes/feature/proposal.md",
                    "role": "governing",
                    "normalizer": "none",
                },
                {
                    "path": "openspec/changes/feature/tasks.md",
                    "role": "reported",
                    "normalizer": "none",
                },
                {
                    "path": "openspec/changes/feature/tasks.md",
                    "role": "governing",
                    "normalizer": product_module.OPENSPEC_TASKS_NORMALIZER,
                },
            ],
        )
        self.controller.apply(
            task_id,
            planning["action"]["action_id"],
            {
                "summary": "Plan recorded",
                "resources": resources,
                "driver_result": driver_result("available", change="feature"),
            },
            binding=planning["action"]["binding"],
        )
        self.source_action(task_id, {"summary": "Implemented"}, "feature")
        self.source_action(task_id, {"summary": "Documented"}, "documentation")
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={"requirement": "proven"},
                summary="Verified",
            ),
        )
        self.controller.decide(
            task_id,
            decision={
                "id": "review-waiver-1",
                "kind": "assurance-waiver",
                "subject": "review",
                "outcome": "waived",
                "rationale": "Independent reviewer is unavailable for this personal delivery",
                "actor_label": "maintainer",
            },
        )
        review = self.apply_current(
            task_id,
            {
                "outcome": "unavailable",
                "assurance": "self",
                "findings": {},
                "summary": "Self-review complete; independence unavailable",
                "driver_result": driver_result("unavailable"),
            },
        )
        self.assertEqual(review["projection"]["current_node"], "finalize_success")
        final = self.apply_current(
            task_id,
            {"summary": "Feature delivered", "remaining_risks": {}, "handoff": "Ready"},
        )
        dossier = self.controller.show(task_id).records[-1]["artifact"]["body"]
        self.assertEqual(final["projection"]["status"], "DONE")
        self.assertEqual(dossier["review_assurance"]["status"], "waived")
        self.assertIn("remaining_risk", dossier["review_assurance"])

    def test_changes_requested_rework_lineage_replays_and_exhausts(self) -> None:
        task_id = self.start_feature("Feature requiring review rework")
        self.preflight(task_id)
        self.advance_feature_to_review(task_id, "review-lineage")
        first_review_result = self.apply_current(
            task_id,
            self.review_payload(
                "changes-requested", "independent", "First review requests changes"
            ),
        )
        self.assertEqual(first_review_result["projection"]["current_node"], "review_rework")
        first_review = self.controller.show(task_id).records[-1]

        self.controller = Controller(self.data_dir)
        rework_projection = self.controller.next(task_id)
        self.assertEqual(
            rework_projection["action"]["action_id"], "review.rework.record"
        )
        projected_edges = {
            item["edge"]: item for item in rework_projection["action"]["inputs"]
        }
        self.assertEqual(
            projected_edges["causal"]["record_id"], first_review["record_id"]
        )
        first_documentation = next(
            record
            for record in reversed(self.controller.show(task_id).records)
            if isinstance(record.get("artifact"), Mapping)
            and record["artifact"].get("type") == "documentation"
        )
        self.assertEqual(
            projected_edges["source-predecessor"]["record_id"],
            first_documentation["record_id"],
        )

        self.source_action(task_id, {"summary": "Review findings addressed"}, "review-rework")
        rework = self.controller.show(task_id).records[-1]
        rework_edges = {item["edge"]: item for item in rework["artifact"]["inputs"]}
        self.assertEqual(rework_edges["causal"]["record_id"], first_review["record_id"])
        self.assertEqual(
            rework_edges["source-predecessor"]["record_id"],
            first_documentation["record_id"],
        )

        self.source_action(
            task_id,
            {"summary": "Documentation updated after review"},
            "review-documentation",
        )
        replacement_documentation = self.controller.show(task_id).records[-1]
        self.assertEqual(
            replacement_documentation["artifact"]["inputs"][0]["record_id"],
            rework["record_id"],
        )
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={"requirement": "proven"},
                summary="Rework verified",
            ),
        )
        replacement_verification = self.controller.show(task_id).records[-1]
        verification_inputs = {
            item["type"]: item
            for item in replacement_verification["artifact"]["inputs"]
        }
        self.assertEqual(
            verification_inputs["documentation"]["record_id"],
            replacement_documentation["record_id"],
        )
        exhausted = self.apply_current(
            task_id,
            self.review_payload(
                "changes-requested", "independent", "Second review requests changes"
            ),
        )
        self.assertEqual(
            exhausted["projection"]["current_node"], "finalize_review_incomplete"
        )
        second_review = self.controller.show(task_id).records[-1]
        self.assertEqual(second_review["producer"]["attempt"], 2)
        second_inputs = {
            item["type"]: item for item in second_review["artifact"]["inputs"]
        }
        self.assertEqual(
            second_inputs["verification-result"]["record_id"],
            replacement_verification["record_id"],
        )
        replayed = Controller(self.data_dir).next(task_id)
        self.assertEqual(
            replayed["action"]["action_id"],
            "delivery.finalize.review-incomplete",
        )

    def test_verification_incomplete_dossier_does_not_promote_stale_review(self) -> None:
        task_id = self.start_feature("Stale review is historical evidence")
        self.preflight(task_id)
        self.advance_feature_to_review(task_id, "stale-review")
        review_payload = self.review_payload(
            "changes-requested",
            "independent",
            "Review requires a source change",
        )
        review_payload["findings"] = {
            "blocking": ["Update the repository-set implementation"]
        }
        self.apply_current(task_id, review_payload)
        stale_review = self.controller.show(task_id).records[-1]

        self.source_action(
            task_id,
            {"summary": "Addressed the review finding"},
            "review-rework",
        )
        self.source_action(
            task_id,
            {"summary": "Updated documentation after review"},
            "review-documentation",
        )
        failure = self.verification_payload(
            task_id,
            passed=False,
            command="python3 focused_test.py",
            criteria={"requirement": "unverified"},
            summary="Verification still fails",
        )
        exhausted = self.apply_current(task_id, failure)
        self.assertEqual(
            exhausted["projection"]["current_node"],
            "finalize_verification_incomplete",
        )
        self.apply_current(
            task_id,
            {
                "summary": "Verification remained incomplete",
                "remaining_risks": {"verification": "failing"},
                "handoff": "Operator intervention required",
            },
        )

        dossier = self.controller.show(task_id).records[-1]["artifact"]["body"]
        self.assertIsNone(dossier["review"])
        self.assertIsNone(dossier["review_assurance"])
        review_history = next(
            item
            for item in dossier["artifacts"]
            if item["record_id"] == stale_review["record_id"]
        )
        self.assertFalse(review_history["current"])
        self.assertTrue(review_history["stale_reasons"])
        review_attempt = next(
            item
            for item in dossier["review_attempts"]
            if item["record_id"] == stale_review["record_id"]
        )
        self.assertFalse(review_attempt["current"])
        self.assertTrue(review_attempt["stale_reasons"])
        self.assertEqual(review_attempt["result"]["outcome"], "changes-requested")
        self.assertEqual(review_attempt["result"]["assurance"], "independent")
        self.assertEqual(
            json_value(review_attempt["result"]["findings"]),
            json_value(review_payload["findings"]),
        )

    def test_unavailable_review_without_exact_waiver_replays_as_rework(self) -> None:
        task_id = self.start_feature("Unavailable independent review")
        self.preflight(task_id)
        self.advance_feature_to_review(task_id, "unavailable")
        before = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as wrong_subject:
            self.controller.decide(
                task_id,
                decision=self.decision(
                    "wrong-review-waiver",
                    kind="assurance-waiver",
                    subject="documentation",
                    outcome="waived",
                ),
            )
        self.assertEqual(wrong_subject.exception.code, "DECISION_INVALID")
        self.assertEqual(self.controller.show(task_id), before)

        result = self.apply_current(
            task_id,
            self.review_payload("unavailable", "self", "Independence unavailable"),
        )
        self.assertEqual(result["projection"]["current_node"], "review_rework")
        restarted = Controller(self.data_dir)
        state = restarted.show(task_id)
        self.assertEqual(state.records[-1]["kind"], "review")
        self.assertEqual(state.records[-1]["payload"]["outcome"], "unavailable")
        self.assertEqual(
            restarted.next(task_id)["action"]["action_id"], "review.rework.record"
        )

    def test_old_contract_review_waiver_is_historical_after_revision(self) -> None:
        task_id = self.start_feature("Review waiver staleness")
        self.preflight(task_id)
        waiver = self.decision(
            "old-review-waiver",
            kind="assurance-waiver",
            subject="review",
            outcome="waived",
        )
        self.controller.decide(task_id, decision=waiver)
        old_waiver_record = self.controller.show(task_id).records[-1]
        self.controller.revise_contract(
            task_id,
            contract=revised_contract(2),
            reason="Review scope changed",
            actor_label="maintainer",
        )
        self.advance_feature_to_review(task_id, "old-waiver")
        current_digest = self.controller.next(task_id)["contract"]["digest"]
        self.assertNotEqual(old_waiver_record["contract"]["digest"], current_digest)
        result = self.apply_current(
            task_id,
            self.review_payload("unavailable", "self", "Old waiver is not current"),
        )
        self.assertEqual(result["projection"]["current_node"], "review_rework")

    def test_current_waiver_does_not_turn_self_review_into_approval(self) -> None:
        task_id = self.start_feature("Self review remains non-independent")
        self.preflight(task_id)
        self.advance_feature_to_review(task_id, "self-review")
        self.controller.decide(
            task_id,
            decision=self.decision(
                "current-review-waiver",
                kind="assurance-waiver",
                subject="review",
                outcome="waived",
            ),
        )
        result = self.apply_current(
            task_id,
            self.review_payload("approved", "self", "Self review found no issue"),
        )
        self.assertEqual(result["projection"]["current_node"], "review_rework")

    def test_read_only_binding_rejects_unowned_source_change_and_stales_terminal_proof(self) -> None:
        task_id = self.start_feature("Read-only assurance binding")
        self.preflight(task_id)
        self.advance_feature_to_review(task_id, "read-only")
        review_projection = self.controller.next(task_id)
        review_binding = review_projection["action"]["binding"]
        before_review = self.controller.show(task_id)
        source_path = self.repository / "a.txt"
        reviewed_bytes = source_path.read_bytes()
        source_path.write_bytes(reviewed_bytes + b"unowned review change\n")

        with self.assertRaises(DevFlowError) as changed:
            self.controller.apply(
                task_id,
                review_projection["action"]["action_id"],
                self.review_payload("approved", "independent"),
                binding=review_binding,
            )
        self.assertEqual(changed.exception.code, "WORKSPACE_CHANGED")
        self.assertEqual(self.controller.show(task_id), before_review)

        source_path.write_bytes(reviewed_bytes)
        approved = self.controller.apply(
            task_id,
            review_projection["action"]["action_id"],
            self.review_payload("approved", "independent"),
            binding=review_binding,
        )
        self.assertEqual(approved["projection"]["current_node"], "finalize_success")
        before_terminal_drift = self.controller.show(task_id)
        records_by_type = {
            record["artifact"]["type"]: record
            for record in before_terminal_drift.records
            if isinstance(record.get("artifact"), Mapping)
        }

        source_path.write_bytes(reviewed_bytes + b"unowned terminal change\n")
        blocked = self.controller.next(task_id)
        self.assertIsNone(blocked["action"]["binding"])
        self.assertEqual(
            blocked["action"]["blocked"]["code"], "ARTIFACT_INPUT_MISSING"
        )
        self.assertTrue(
            blocked["freshness"][records_by_type["impact-report"]["record_id"]][
                "current"
            ]
        )
        for artifact_type in ("verification-result", "review-result"):
            with self.subTest(artifact_type=artifact_type):
                self.assertFalse(
                    blocked["freshness"][records_by_type[artifact_type]["record_id"]][
                        "current"
                    ]
                )
        self.assertEqual(self.controller.show(task_id), before_terminal_drift)
        self.assertFalse(
            any(
                isinstance(record.get("artifact"), Mapping)
                and record["artifact"].get("type") == "delivery-dossier"
                for record in before_terminal_drift.records
            )
        )

    def test_governing_openspec_tasks_ignore_only_checkbox_state(self) -> None:
        state = self.controller.start(
            requirement="Feature with repository plan",
            workflow="feature",
            repositories=(str(self.repository),),
        )
        task_id = state.task_id
        self.preflight(task_id)
        self.apply_current(
            task_id,
            {"summary": "Impact", "driver_result": driver_result("degraded")},
        )
        projection = self.controller.next(task_id)
        plan = self.repository / "plan.md"
        tasks = self.repository / "tasks.md"
        plan.write_text("plan\n", encoding="utf-8")
        original_tasks = "- [ ] implement change\n- [ ] run focused runtime test\n"
        checked_tasks = "- [x] implement change\n- [X] run focused runtime test\n"
        tasks.write_text(original_tasks, encoding="utf-8")
        resources = self.resource_payload(task_id, [
            {"path": "plan.md", "role": "governing", "normalizer": "none"},
            {"path": "tasks.md", "role": "reported", "normalizer": "none"},
            {
                "path": "tasks.md",
                "role": "governing",
                "normalizer": product_module.OPENSPEC_TASKS_NORMALIZER,
            },
        ])
        self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {
                "summary": "Plan",
                "resources": resources,
                "driver_result": driver_result("degraded"),
            },
            binding=projection["action"]["binding"],
        )
        implementation = self.controller.next(task_id)
        plan_record = next(
            record
            for record in self.controller.show(task_id).records
            if isinstance(record.get("artifact"), Mapping)
            and record["artifact"].get("type") == "delivery-plan"
        )
        recorded_resources = plan_record["artifact"]["resources"]
        initial_reported = next(
            item
            for item in recorded_resources
            if item["path"] == "tasks.md" and item["normalizer"] == "none"
        )
        initial_governing = next(
            item
            for item in recorded_resources
            if item["path"] == "tasks.md"
            and item["normalizer"] == product_module.OPENSPEC_TASKS_NORMALIZER
        )
        tasks.write_text(checked_tasks, encoding="utf-8")
        (self.repository / "a.txt").write_text("implemented\n", encoding="utf-8")
        result = self.controller.apply(
            task_id,
            implementation["action"]["action_id"],
            {"summary": "Implemented"},
            binding=implementation["action"]["binding"],
        )
        self.assertTrue(
            result["projection"]["freshness"][plan_record["record_id"]]["current"]
        )
        current_resources = self.sole_member_snapshot(
            task_id,
            self.controller.show_view(task_id)["current_snapshot"],
        )["resources"]
        checked_reported = next(
            item
            for item in current_resources
            if item["path"] == "tasks.md" and item["normalizer"] == "none"
        )
        checked_governing = next(
            item
            for item in current_resources
            if item["path"] == "tasks.md"
            and item["normalizer"] == product_module.OPENSPEC_TASKS_NORMALIZER
        )
        self.assertNotEqual(
            initial_reported["raw_sha256"], checked_reported["raw_sha256"]
        )
        self.assertEqual(
            initial_governing["semantic_sha256"],
            checked_governing["semantic_sha256"],
        )

        tasks.write_text(
            "- [X] run focused runtime test\n- [x] implement change\n",
            encoding="utf-8",
        )
        stale_order = self.controller.next(task_id)
        self.assertIsNone(stale_order["action"]["binding"])
        self.assertEqual(
            stale_order["action"]["blocked"]["code"], "ARTIFACT_INPUT_MISSING"
        )

        tasks.write_text(checked_tasks, encoding="utf-8")
        self.assertIsNotNone(self.controller.next(task_id)["action"]["binding"])
        tasks.write_text(
            "- [x] implement change\n- [X] run full runtime test suite\n",
            encoding="utf-8",
        )
        stale_test_obligation = self.controller.next(task_id)
        self.assertIsNone(stale_test_obligation["action"]["binding"])
        self.assertEqual(
            stale_test_obligation["action"]["blocked"]["code"],
            "ARTIFACT_INPUT_MISSING",
        )

    def test_full_contract_revision_bridges_to_replacement_plan(self) -> None:
        task_id = self.controller.start(
            requirement="Full delivery with revised scope",
            workflow="full",
            repositories=(str(self.repository),),
        ).task_id
        self.preflight(task_id)
        self.apply_current(
            task_id,
            {"summary": "C1 impact", "driver_result": driver_result("available")},
        )
        first_planning = self.controller.next(task_id)
        plan = self.repository / "plan.md"
        tasks = self.repository / "tasks.md"
        plan.write_text("C1 plan\n", encoding="utf-8")
        tasks.write_text("- [ ] verify C1\n", encoding="utf-8")
        resources = self.resource_payload(
            task_id,
            [
                {"path": "plan.md", "role": "governing", "normalizer": "none"},
                {"path": "tasks.md", "role": "reported", "normalizer": "none"},
                {
                    "path": "tasks.md",
                    "role": "governing",
                    "normalizer": product_module.OPENSPEC_TASKS_NORMALIZER,
                },
            ],
        )
        self.controller.apply(
            task_id,
            first_planning["action"]["action_id"],
            {
                "summary": "C1 plan",
                "resources": resources,
                "driver_result": driver_result("available", change="c1"),
            },
            binding=first_planning["action"]["binding"],
        )
        state_c1 = self.controller.show(task_id)
        plan_c1 = next(
            record
            for record in state_c1.records
            if isinstance(record.get("artifact"), Mapping)
            and record["artifact"].get("type") == "delivery-plan"
        )

        revised = self.controller.revise_contract(
            task_id,
            contract=revised_contract(2, "replacement"),
            reason="C2 replaces C1 scope",
            actor_label="maintainer",
        )
        self.assertEqual(revised["projection"]["current_node"], "impact")
        revision_record = self.controller.show(task_id).records[-1]
        self.assertEqual(revision_record["artifact"]["type"], "revision-source")
        self.assertEqual(tuple(revision_record["artifact"]["inputs"]), ())
        revision_snapshot = self.sole_member_snapshot(
            task_id, revision_record["artifact"]["snapshot"]
        )
        plan_c1_snapshot = self.sole_member_snapshot(
            task_id, plan_c1["artifact"]["snapshot"]
        )
        self.assertEqual(
            revision_snapshot["status_sha256"],
            plan_c1_snapshot["status_sha256"],
        )
        self.assertEqual(tuple(revision_snapshot["resources"]), ())
        self.assertEqual(
            revision_record["payload"]["previous_contract_digest"],
            plan_c1["artifact"]["contract_digest"],
        )
        self.assertEqual(
            revision_record["payload"]["new_contract_digest"],
            revision_record["artifact"]["contract_digest"],
        )

        self.apply_current(
            task_id,
            {"summary": "C2 impact", "driver_result": driver_result("available")},
        )
        impact_c2 = self.controller.show(task_id).records[-1]
        self.assertEqual(
            impact_c2["artifact"]["inputs"][0]["record_id"],
            revision_record["record_id"],
        )
        self.assertEqual(impact_c2["artifact"]["inputs"][0]["type"], "revision-source")

        replacement_planning = self.controller.next(task_id)
        source_input = next(
            item
            for item in replacement_planning["action"]["inputs"]
            if item["edge"] == "source-predecessor"
        )
        self.assertEqual(source_input["record_id"], revision_record["record_id"])
        plan.write_text("C2 replacement plan\n", encoding="utf-8")
        tasks.write_text("- [ ] verify replacement C2\n", encoding="utf-8")
        self.controller.apply(
            task_id,
            replacement_planning["action"]["action_id"],
            {
                "summary": "C2 replacement plan",
                "resources": resources,
                "driver_result": driver_result("available", change="c2"),
            },
            binding=replacement_planning["action"]["binding"],
        )
        plan_c2 = self.controller.show(task_id).records[-1]
        plan_c2_inputs = {item["edge"]: item for item in plan_c2["artifact"]["inputs"]}
        self.assertEqual(
            plan_c2_inputs["source-predecessor"]["record_id"],
            revision_record["record_id"],
        )
        self.assertEqual(
            plan_c2_inputs["governing"]["record_id"], impact_c2["record_id"]
        )
        restarted = Controller(self.data_dir)
        projection = restarted.next(task_id)
        self.assertEqual(projection["contract"]["revision"], 2)
        self.assertEqual(projection["action"]["action_id"], "implementation.record")
        self.assertEqual(
            next(
                item
                for item in projection["action"]["inputs"]
                if item["edge"] == "source-predecessor"
            )["record_id"],
            plan_c2["record_id"],
        )
        self.assertFalse(
            restarted.show_view(task_id)["artifact_freshness"][plan_c1["record_id"]][
                "current"
            ]
        )

    def test_revision_snapshot_failure_is_atomic_and_restart_recovers(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        self.source_action(task_id, {"summary": "Initial implementation"}, "snapshot-failure")
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=False,
                command="python3 focused_test.py",
                criteria={"requirement": "unverified"},
                summary="Attempt retained before snapshot failure",
            ),
        )
        before = self.controller.show(task_id)

        def fail_snapshot(*args, **kwargs):
            del args, kwargs
            raise DevFlowError(
                "WORKSPACE_SNAPSHOT_FAILED", "injected stable snapshot failure"
            )

        self.controller.git.snapshot = fail_snapshot
        with self.assertRaises(DevFlowError) as caught:
            self.controller.revise_contract(
                task_id,
                contract=revised_contract(2),
                reason="Retry after a stable snapshot is available",
                actor_label="maintainer",
            )
        self.assertEqual(caught.exception.code, "WORKSPACE_SNAPSHOT_FAILED")
        after_failure = Controller(self.data_dir).show(task_id)
        self.assertEqual(after_failure, before)
        self.assertEqual(
            sum(record["kind"] == "verification" for record in after_failure.records),
            1,
        )
        self.assertEqual(after_failure.current_node, "verification_rework")

        recovered = Controller(self.data_dir).revise_contract(
            task_id,
            contract=revised_contract(2),
            reason="Stable snapshot recovered",
            actor_label="maintainer",
        )
        self.assertEqual(recovered["projection"]["contract"]["revision"], 2)
        self.assertEqual(
            Controller(self.data_dir).show(task_id).records[-1]["artifact"]["type"],
            "revision-source",
        )

    def test_contract_revision_loses_revision_cas_without_partial_record(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        racing = Controller(self.data_dir)
        original_update = self.controller.store.update
        raced = False

        def update_after_competing_decision(candidate_task_id, expected_revision, mutation):
            nonlocal raced
            if not raced:
                raced = True
                racing.decide(
                    task_id,
                    decision=self.decision("race-winner", subject="scope-race"),
                )
            return original_update(candidate_task_id, expected_revision, mutation)

        self.controller.store.update = update_after_competing_decision
        try:
            with self.assertRaises(DevFlowError) as caught:
                self.controller.revise_contract(
                    task_id,
                    contract=revised_contract(2),
                    reason="Losing concurrent revision",
                    actor_label="maintainer",
                )
        finally:
            self.controller.store.update = original_update
        self.assertEqual(caught.exception.code, "REVISION_CONFLICT")
        self.assertEqual(caught.exception.details["projection"]["revision"], 2)
        state = self.controller.show(task_id)
        self.assertEqual([record["kind"] for record in state.records], ["preflight", "decision"])
        self.assertEqual(state.original_contract["revision"], 1)
        self.assertEqual(
            self.controller.next(task_id)["action"]["action_id"],
            "implementation.record",
        )

    def test_record_tamper_fails_closed_on_restart(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        state_path = Path(self.data_dir) / "tasks" / task_id / "state.json"
        value = json.loads(state_path.read_text(encoding="utf-8"))
        value["records"][0]["transition"]["to"] = "done"
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as caught:
            Controller(self.data_dir).show(task_id)
        self.assertEqual(caught.exception.code, "STATE_INVALID")

    def test_contract_revision_digest_chain_tamper_fails_closed_on_restart(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        self.controller.revise_contract(
            task_id,
            contract=revised_contract(2),
            reason="Accepted revision",
            actor_label="maintainer",
        )
        original = json.loads(self.state_path(task_id).read_text(encoding="utf-8"))
        for field, replacement in (
            ("previous_contract_digest", "0" * 64),
            ("new_contract_digest", "f" * 64),
        ):
            with self.subTest(field=field):
                value = json.loads(json.dumps(original))
                revision = value["records"][-1]
                revision["payload"][field] = replacement
                value["records"][-1] = json_value(seal_record(revision))
                self.state_path(task_id).write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaises(DevFlowError) as caught:
                    Controller(self.data_dir).show(task_id)
                self.assertEqual(caught.exception.code, "STATE_INVALID")
                self.assertEqual(
                    caught.exception.details["reason"],
                    "contract_revision_replay_failed",
                )
        self.state_path(task_id).write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(Controller(self.data_dir).show(task_id).revision, 2)

    def test_verification_exhaustion_generates_incomplete_dossier(self) -> None:
        task_id = self.start_lite()
        self.preflight(task_id)
        self.source_action(task_id, {"summary": "Implementation"}, "initial")
        failure = self.verification_payload(
            task_id,
            passed=False,
            command="python3 focused_test.py",
            criteria={"requirement": "unverified"},
            summary="Still failing",
        )
        self.apply_current(task_id, failure)
        self.source_action(task_id, {"summary": "Bounded repair"}, "repair")
        second = self.apply_current(task_id, failure)
        self.assertEqual(
            second["projection"]["current_node"],
            "finalize_verification_incomplete",
        )
        result = self.apply_current(
            task_id,
            {
                "summary": "Delivery incomplete",
                "remaining_risks": {"verification": "failing"},
                "handoff": "Operator intervention required",
            },
        )
        self.assertEqual(result["projection"]["status"], "INCOMPLETE")
        self.assertEqual(result["projection"]["dossier"]["outcome"], "incomplete")

    def test_criterion_waiver_is_authoritative_coverage(self) -> None:
        contract = {
            "schema": CONTRACT_SCHEMA,
            "revision": 1,
            "summary": "Two acceptance criteria",
            "acceptance_criteria": [
                {"id": "required", "statement": "Required behavior works"},
                {"id": "optional", "statement": "Optional environment is checked"},
            ],
            "scope": ["Current repository"],
            "constraints": [],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        state = self.controller.start(
            requirement="Two acceptance criteria",
            workflow="lite",
            repositories=(str(self.repository),),
            contract=contract,
        )
        task_id = state.task_id
        self.preflight(task_id)
        self.controller.decide(
            task_id,
            decision={
                "id": "criterion-waiver-1",
                "kind": "criterion-waiver",
                "subject": "optional",
                "outcome": "waived",
                "rationale": "The optional environment is outside this personal delivery",
                "actor_label": "maintainer",
            },
        )
        self.source_action(task_id, {"summary": "Implemented"}, "waiver")
        result = self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 focused_test.py",
                criteria={"required": "proven", "optional": "unverified"},
                summary="Required criterion proven",
            ),
        )
        self.assertEqual(result["projection"]["current_node"], "finalize_success")
        final = self.apply_current(
            task_id,
            {"summary": "Delivered", "remaining_risks": {}, "handoff": "Ready"},
        )
        self.assertEqual(final["projection"]["dossier"]["coverage"]["waived"], 1)

    def test_every_official_workflow_starts_with_preflight_and_cancels(self) -> None:
        for workflow in (
            "lite",
            "feature",
            "bugfix",
            "investigation",
            "refactor",
            "full",
        ):
            with self.subTest(workflow=workflow):
                state = self.controller.start(
                    requirement="{} journey".format(workflow),
                    workflow=workflow,
                    repositories=(str(self.repository),),
                )
                projection = self.controller.next(state.task_id)
                self.assertEqual(projection["action"]["handler"], "preflight")
                self.apply_current(state.task_id, {})
                cancelled = self.controller.cancel(
                    state.task_id, reason="Focused cancellation journey"
                )
                self.assertEqual(cancelled["projection"]["status"], "CANCELLED")
                self.assertTrue(cancelled["projection"]["done"])

    def test_investigation_completes_without_implementation_artifact(self) -> None:
        state = self.controller.start(
            requirement="Investigate the observed behavior",
            workflow="investigation",
            repositories=(str(self.repository),),
        )
        task_id = state.task_id
        self.preflight(task_id)
        self.apply_current(
            task_id,
            {"summary": "Impact located", "driver_result": driver_result("available")},
        )
        self.apply_current(
            task_id,
            {"summary": "Investigation complete", "evidence": {"finding": "bounded"}},
        )
        self.apply_current(
            task_id,
            self.verification_payload(
                task_id,
                passed=True,
                command="python3 reproduce.py",
                criteria={"requirement": "proven"},
                summary="Finding reproduced",
            ),
        )
        self.apply_current(
            task_id,
            {"summary": "Report ready", "remaining_risks": {}, "handoff": "Use report"},
        )
        artifact_types = [
            record["artifact"]["type"]
            for record in self.controller.show(task_id).records
            if record.get("artifact") is not None
        ]
        self.assertNotIn("implementation", artifact_types)
        self.assertIn("investigation-report", artifact_types)

    def test_selected_workflow_and_record_identity_drift_are_task_local(self) -> None:
        workflow_a = self.root / "linear-a.json"
        workflow_b = self.root / "linear-b.json"
        self.write_linear_workflow(workflow_a, description="Workflow A")
        self.write_linear_workflow(workflow_b, description="Workflow B")
        task_a = self.controller.start(
            requirement="Pinned workflow A",
            workflow=str(workflow_a),
            repositories=(str(self.repository),),
        ).task_id
        task_b = self.controller.start(
            requirement="Pinned workflow B",
            workflow=str(workflow_b),
            repositories=(str(self.repository),),
        ).task_id
        task_c = self.start_lite("Unaffected built-in task")
        for task_id in (task_a, task_b, task_c):
            self.preflight(task_id)

        self.write_linear_workflow(workflow_a, description="Workflow A drifted")
        with self.assertRaises(DevFlowError) as workflow_drift:
            Controller(self.data_dir).show(task_a)
        self.assertEqual(workflow_drift.exception.code, "WORKFLOW_IDENTITY_MISMATCH")
        self.assertEqual(Controller(self.data_dir).show(task_b).revision, 1)
        self.assertEqual(Controller(self.data_dir).show(task_c).revision, 1)

        value = json.loads(self.state_path(task_b).read_text(encoding="utf-8"))
        value["records"][0]["schema"] = "dev-flow-record/unsupported"
        self.state_path(task_b).write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as record_drift:
            Controller(self.data_dir).show(task_b)
        self.assertEqual(record_drift.exception.code, "STATE_INVALID")
        self.assertEqual(Controller(self.data_dir).show(task_c).revision, 1)

    def test_catalog_drift_is_local_but_product_identity_mismatch_fails_closed(self) -> None:
        task_id = self.start_lite("Identity isolation")
        self.preflight(task_id)
        self.source_action(task_id, {"summary": "Replayable work"}, "identity")
        persisted = self.controller.show(task_id)
        original_catalog = product_module.CATALOG_IDENTITY
        try:
            product_module.CATALOG_IDENTITY = "catalog-with-unrelated-workflow"
            restarted = Controller(self.data_dir)
            self.assertEqual(restarted.show(task_id), persisted)
            projection = restarted.next(task_id)
            self.assertEqual(
                projection["workflow"]["identity"], persisted.workflow_identity
            )
            self.assertEqual(projection["revision"], persisted.revision)
            self.assertEqual(
                projection["action"]["action_id"], "verification.record"
            )
        finally:
            product_module.CATALOG_IDENTITY = original_catalog

        value = json.loads(self.state_path(task_id).read_text(encoding="utf-8"))
        value["product_identity"] = "not-the-installed-product"
        self.state_path(task_id).write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(DevFlowError) as mismatch:
            Controller(self.data_dir).show(task_id)
        self.assertEqual(mismatch.exception.code, "PRODUCT_IDENTITY_MISMATCH")

    def test_cli_requires_strict_binding_json(self) -> None:
        data_dir = str(self.root / "cli-data")

        def invoke(arguments):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli_main(arguments)
            return code, json.loads(output.getvalue())

        code, started = invoke(
            [
                "--data-dir",
                data_dir,
                "start",
                "--requirement",
                "CLI delivery",
                "--workflow",
                "lite",
                "--repo",
                str(self.repository),
            ]
        )
        self.assertEqual(code, 0)
        task_id = started["task"]["task_id"]
        _, projected = invoke(["--data-dir", data_dir, "next", task_id])
        binding = projected["projection"]["action"]["binding"]
        code, applied = invoke(
            [
                "--data-dir",
                data_dir,
                "apply",
                task_id,
                "--action",
                "task.preflight",
                "--binding-json",
                json.dumps(binding),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(applied["projection"]["current_node"], "implement")
        code, invalid = invoke(
            [
                "--data-dir",
                data_dir,
                "apply",
                task_id,
                "--action",
                "implementation.record",
                "--payload-json",
                '{"summary":"one","summary":"two"}',
                "--binding-json",
                "{}",
            ]
        )
        self.assertEqual(code, 2)
        self.assertEqual(invalid["error"]["code"], "ARGUMENT_JSON_INVALID")


if __name__ == "__main__":
    unittest.main()
