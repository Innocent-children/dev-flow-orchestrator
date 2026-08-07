"""Focused 0.3 adaptive-assurance and causal-review domain tests."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from dev_flow_orchestrator.assurance import (
    budget_view,
    derive_assurance_plan,
    next_obligation,
    normalize_impact_report,
    obligation_states,
    validate_assurance_execution,
)
from dev_flow_orchestrator.model import DevFlowError, RepositoryRecord
from dev_flow_orchestrator.product import MAX_REVIEW_FINDINGS, TASK_CHANGE_MANIFEST_SCHEMA
from dev_flow_orchestrator.review import (
    derive_review_result,
    finding_template,
    validate_disposition,
    validate_finding,
)


CONTRACT = {
    "acceptance_criteria": [
        {"id": "criterion-1", "statement": "The changed behavior works"},
    ],
}
CONTRACT_DIGEST = "c" * 64
REPOSITORIES = (
    RepositoryRecord("app", "/tmp/adaptive-app", "/tmp/adaptive-app/.git", "/tmp/adaptive-app/.git"),
    RepositoryRecord("client", "/tmp/adaptive-client", "/tmp/adaptive-client/.git", "/tmp/adaptive-client/.git"),
)
MANIFEST = {
    "schema": TASK_CHANGE_MANIFEST_SCHEMA,
    "digest": "m" * 64,
    "entries": [{"repository_id": "app", "path": "src/a.py"}],
}


def impact(*, confidence="source-confirmed", triggers=(), documentation=False, manual=False, reproduction=True, edges=()):
    return normalize_impact_report(
        {
            "confidence": confidence,
            "entries": [{
                "repository_id": "app",
                "path": "src/a.py",
                "symbol": "run",
                "criterion_ids": ["criterion-1"],
            }],
            "edges": list(edges),
            "risk_triggers": list(triggers),
            "public_behavior": documentation,
            "documentation_required": documentation,
            "manual_evidence_required": manual,
            "executable_reproduction_required": reproduction,
            "overflow": False,
            "limitations": [],
        },
        repositories=REPOSITORIES,
        contract=CONTRACT,
    )


def plan(profile: str, report=None):
    return derive_assurance_plan(
        task_id="task-adaptive",
        profile=profile,
        contract=CONTRACT,
        contract_digest=CONTRACT_DIGEST,
        repositories=REPOSITORIES,
        manifest=MANIFEST,
        impact=report or impact(),
    )


class AdaptiveAssuranceTests(unittest.TestCase):
    def test_each_profile_has_a_focused_and_triggered_plan(self) -> None:
        for profile in ("lite", "feature", "bugfix", "investigation", "refactor", "full"):
            with self.subTest(profile=profile, mode="focused"):
                focused = plan(profile)
                self.assertTrue(focused["obligations"])
                self.assertLessEqual(focused["budgets"]["total_action_ceiling"], 256)
                if profile != "full":
                    self.assertEqual(focused["not_required"]["repository_ids"], ["client"])
            with self.subTest(profile=profile, mode="triggered"):
                triggered = plan(profile, impact(triggers=("security",)))
                self.assertIn("independent-review", {item["kind"] for item in triggered["obligations"]})

    def test_unknown_impact_uses_conservative_member_closure(self) -> None:
        conservative = plan("lite", impact(confidence="partial"))
        members = {
            item["repository_ids"][0]
            for item in conservative["obligations"]
            if item["kind"] == "repository-check"
        }
        self.assertEqual(members, {"app", "client"})
        self.assertEqual(conservative["confidence"], "unknown")
        self.assertIn("independent-review", {item["kind"] for item in conservative["obligations"]})

    def test_bugfix_requires_regression_evidence(self) -> None:
        value = plan("bugfix")
        repository = next(item for item in value["obligations"] if item["kind"] == "repository-check")
        self.assertTrue(repository["evidence_contract"]["regression_required"])

    def test_exact_budget_formula_and_dispatch(self) -> None:
        value = plan("feature", impact(triggers=("security",)))
        verification = [item for item in value["budgets"]["reservation_set"] if item["budget_class"] == "verification"]
        reviews = [item for item in value["budgets"]["reservation_set"] if item["budget_class"] == "review"]
        self.assertEqual(value["budgets"]["verification_ceiling"], min(2 * len(verification), len(verification) + 2))
        self.assertEqual(value["budgets"]["review_ceiling"], min(2 * len(reviews), len(reviews) + 1))
        retry_units = sum(item["retry_units"] for item in value["budgets"]["reservation_set"])
        self.assertEqual(value["budgets"]["rework_ceiling"], min(2, retry_units))
        self.assertEqual(
            value["budgets"]["finding_disposition_reserve"],
            MAX_REVIEW_FINDINGS * value["budgets"]["review_ceiling"],
        )
        prerequisite_reservations = value["budgets"]["prerequisite_reservation_set"]
        self.assertEqual(len(prerequisite_reservations), 1)
        self.assertEqual(
            set(prerequisite_reservations[0]["prerequisite_reservation_ids"]),
            {
                item["reservation_id"]
                for item in value["budgets"]["reservation_set"]
                if item["kind"] != "independent-review"
            },
        )
        projected = next_obligation(value, ())
        self.assertIsNotNone(projected)
        first = projected["obligation"]
        execution = validate_assurance_execution(
            {
                "schema": "dev-flow-assurance-execution/0.4.0",
                "plan_digest": value["digest"],
                "obligation_id": first["obligation_id"],
                "obligation_fingerprint": first["fingerprint"],
                "contract_digest": CONTRACT_DIGEST,
                "manifest_digest": MANIFEST["digest"],
                "passed": True,
                "evidence": [{"kind": "command", "reference": "unit", "summary": "passed"}],
                "limitations": [],
            },
            plan=value,
            obligation=first,
        )
        states = obligation_states(value, (execution,))
        self.assertEqual(states[0]["state"], "satisfied")
        self.assertEqual(budget_view(value, (execution,))["used"]["verification"], 1)

    def test_same_contract_replan_keeps_conservative_budget_for_expanded_route(self) -> None:
        focused = plan("feature")
        conservative = derive_assurance_plan(
            task_id="task-adaptive",
            profile="feature",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            repositories=REPOSITORIES,
            manifest=MANIFEST,
            impact=impact(confidence="unknown"),
            previous_plan=focused,
        )
        self.assertGreater(len(conservative["obligations"]), len(focused["obligations"]))
        self.assertEqual(conservative["budgets"], focused["budgets"])
        self.assertGreaterEqual(
            conservative["budgets"]["verification_ceiling"],
            sum(
                item["budget_class"] == "verification"
                for item in conservative["obligations"]
            ),
        )
        self.assertGreaterEqual(conservative["budgets"]["review_ceiling"], 1)

    def test_same_contract_replan_inherits_budget_before_expanding_prerequisites(self) -> None:
        edges = tuple(
            {
                "from_repository_id": "app",
                "to_repository_id": "client",
                "evidence_contract": "contract-{}".format(index),
                "criterion_ids": ["criterion-1"],
                "affected": False,
            }
            for index in range(35)
        )
        focused = plan("feature", impact(edges=edges))
        self.assertLess(focused["budgets"]["total_action_ceiling"], 256)
        self.assertEqual(
            len(focused["budgets"]["prerequisite_reservation_set"]),
            1,
        )

        conservative = derive_assurance_plan(
            task_id="task-adaptive",
            profile="feature",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            repositories=REPOSITORIES,
            manifest=MANIFEST,
            impact=impact(confidence="unknown", edges=edges),
            previous_plan=focused,
        )

        self.assertGreater(len(conservative["obligations"]), len(focused["obligations"]))
        self.assertEqual(conservative["budgets"], focused["budgets"])
        review = next(
            item
            for item in conservative["obligations"]
            if item["kind"] == "independent-review"
        )
        self.assertEqual(len(review["prerequisites"]), 37)

    def test_finding_disposition_reserve_rejects_route_over_product_ceiling(self) -> None:
        edges = tuple(
            {
                "from_repository_id": "app",
                "to_repository_id": "client",
                "evidence_contract": "contract-{}".format(index),
                "criterion_ids": ["criterion-1"],
                "affected": True,
            }
            for index in range(20)
        )
        with self.assertRaises(DevFlowError) as context:
            plan("full", impact(edges=edges))
        self.assertEqual(context.exception.code, "ASSURANCE_BUDGET_INVALID")
        self.assertGreater(
            context.exception.details["total_action_ceiling"],
            256,
        )


class CausalReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan("feature", impact(triggers=("security",)))
        self.review_obligation = next(item for item in self.plan["obligations"] if item["kind"] == "independent-review")
        self.bindings = {
            "task_id": "task-adaptive",
            "contract_digest": CONTRACT_DIGEST,
            "plan_digest": self.plan["digest"],
            "manifest_digest": MANIFEST["digest"],
            "review_scope_digest": "s" * 64,
            "guidance_digest": "g" * 64,
            "reviewer_digest": "r" * 64,
            "workspace_digest": "w" * 64,
        }

    def finding(self, relation: str, blocking: bool, *, path="src/a.py", causal=False):
        body = {
            "schema": "dev-flow-review-finding/0.4.0",
            "severity": "high",
            "blocking": blocking,
            "causal_relation": relation,
            "criterion_ids": ["criterion-1"],
            "repository_id": "app",
            "path": path,
            "symbol": "run",
            "location_label": None,
            "evidence": [{"kind": "source", "reference": path, "summary": "confirmed", "source_confirmed": True}],
            "causal_manifest_entries": [
                {"repository_id": "app", "path": "src/a.py"}
            ] if causal or relation == "introduced" else [],
            "causal_path": [{"kind": "call", "from": "src/a.py", "to": path, "evidence": "direct call", "source_confirmed": True}] if causal else [],
            "smallest_sufficient_resolution": "Correct the bounded behavior",
            "reviewer_assurance": "independent",
            "limitations": [],
            **self.bindings,
        }
        sealed = finding_template(body)
        return validate_finding(
            sealed,
            task_id="task-adaptive",
            contract=CONTRACT,
            contract_digest=CONTRACT_DIGEST,
            plan=self.plan,
            manifest=MANIFEST,
            repository_ids=("app", "client"),
            review_scope_digest=self.bindings["review_scope_digest"],
            guidance_digest=self.bindings["guidance_digest"],
            reviewer_digest=self.bindings["reviewer_digest"],
            workspace_digest=self.bindings["workspace_digest"],
        )

    def test_only_current_blocking_causal_findings_request_rework(self) -> None:
        causal = self.finding("introduced", True)
        unrelated = self.finding("pre-existing", True)
        result = derive_review_result(
            plan=self.plan,
            review_obligation=self.review_obligation,
            findings=(causal, unrelated),
            reviewer_available=True,
            independent=True,
        )
        self.assertEqual(result["outcome"], "changes-requested")
        self.assertEqual(result["rework_fingerprints"], [causal["fingerprint"]])

    def test_blocking_unknown_requires_triage_not_rework(self) -> None:
        finding = self.finding("unknown", True)
        result = derive_review_result(
            plan=self.plan,
            review_obligation=self.review_obligation,
            findings=(finding,),
            reviewer_available=True,
            independent=True,
        )
        self.assertEqual(result["outcome"], "triage-required")
        self.assertEqual(result["rework_fingerprints"], [])

    def test_out_of_closure_affected_finding_is_an_impact_gap(self) -> None:
        finding = self.finding("affected", True, path="src/consumer.py", causal=True)
        self.assertTrue(finding["impact_gap"])
        result = derive_review_result(
            plan=self.plan,
            review_obligation=self.review_obligation,
            findings=(finding,),
            reviewer_available=True,
            independent=True,
        )
        self.assertEqual(result["outcome"], "triage-required")
        self.assertEqual(result["impact_gap_fingerprints"], [finding["fingerprint"]])

    def test_contradictory_agent_verdict_is_rejected(self) -> None:
        finding = self.finding("introduced", True)
        with self.assertRaises(DevFlowError) as context:
            derive_review_result(
                plan=self.plan,
                review_obligation=self.review_obligation,
                findings=(finding,),
                reviewer_available=True,
                independent=True,
                claimed_outcome="approved",
            )
        self.assertEqual(context.exception.code, "REVIEW_OUTCOME_CONTRADICTORY")

    def test_all_dispositions_are_exactly_bound_and_authorized(self) -> None:
        base = {
            "schema": "dev-flow-finding-disposition/0.4.0",
            "task_id": "task-adaptive",
            "contract_digest": CONTRACT_DIGEST,
            "plan_digest": self.plan["digest"],
            "review_digest": "v" * 64,
            "finding_fingerprint": "f" * 64,
            "actor": "task-owner",
            "rationale": "Resolve only this exact finding",
            "expected_revision": 7,
        }
        for kind in ("accepted-risk", "confirmed-out-of-scope", "expand-contract"):
            with self.subTest(kind=kind):
                value = {
                    **base,
                    "kind": kind,
                    "next_contract": (
                        {"schema": "dev-flow-delivery-contract/0.4.0"}
                        if kind == "expand-contract"
                        else None
                    ),
                }
                validated = validate_disposition(
                    value,
                    task_id="task-adaptive",
                    contract_digest=CONTRACT_DIGEST,
                    plan_digest=self.plan["digest"],
                    review_digest="v" * 64,
                    finding_fingerprint_value="f" * 64,
                    expected_revision=7,
                    current_revision=7,
                    actor_authorized=True,
                )
                self.assertEqual(validated["kind"], kind)
        with self.assertRaises(DevFlowError) as context:
            validate_disposition(
                {**base, "kind": "accepted-risk", "next_contract": None},
                task_id="task-adaptive",
                contract_digest=CONTRACT_DIGEST,
                plan_digest=self.plan["digest"],
                review_digest="v" * 64,
                finding_fingerprint_value="f" * 64,
                expected_revision=7,
                current_revision=7,
                actor_authorized=False,
            )
        self.assertEqual(context.exception.code, "FINDING_DISPOSITION_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
