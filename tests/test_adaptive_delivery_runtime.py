"""Focused controller journeys for 0.3 adaptive dispatch and selective reuse."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    DRIVER_RESULT_SCHEMA,
    FINDING_DISPOSITION_SCHEMA,
    TASK_CHANGE_CLAIMS_SCHEMA,
)
from dev_flow_orchestrator.review import finding_template
from support import make_repository


class AdaptiveDeliveryRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.first = make_repository(self.root, "first")
        self.second = make_repository(self.root, "second")
        self.controller = Controller(self.data_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def apply(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def repository_id(self, task_id: str, path: Path) -> str:
        state = self.controller.show(task_id)
        canonical = str(path.resolve())
        return next(
            item.repository_id for item in state.repositories if item.path == canonical
        )

    def impact(self, task_id: str, *, trigger: bool = False) -> dict:
        projection = self.controller.next(task_id)
        repository_id = self.repository_id(task_id, self.first)
        return {
            "summary": "Source closure confirmed",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": "available",
            },
            "impact_manifest": {
                "confidence": "source-confirmed",
                "entries": [{
                    "repository_id": repository_id,
                    "path": "a.txt",
                    "symbol": None,
                    "criterion_ids": projection["contract"]["criterion_ids"],
                }],
                "edges": [],
                "risk_triggers": ["security"] if trigger else [],
                "public_behavior": False,
                "documentation_required": False,
                "manual_evidence_required": False,
                "executable_reproduction_required": True,
                "overflow": False,
                "limitations": [],
            },
        }

    def claims(self, task_id: str, repository: Path, path: str = "a.txt") -> dict:
        projection = self.controller.next(task_id)
        return {
            "schema": TASK_CHANGE_CLAIMS_SCHEMA,
            "claims": [{
                "repository_id": self.repository_id(task_id, repository),
                "path": path,
                "classification": "implementation",
                "criterion_ids": projection["contract"]["criterion_ids"],
                "purpose": "Implement the accepted task scope",
            }],
        }

    def source(self, task_id: str, repository: Path, marker: str) -> dict:
        projection = self.controller.next(task_id)
        with (repository / "a.txt").open("a", encoding="utf-8") as stream:
            stream.write(marker + "\n")
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {
                "summary": marker,
                "ownership_claims": self.claims(task_id, repository),
            },
            binding=projection["action"]["binding"],
        )

    def pass_obligation(self, task_id: str) -> dict:
        projection = self.controller.next(task_id)
        obligation = projection["action"]["current_obligation"]
        result = {
            "obligation_id": obligation["obligation_id"],
            "passed": True,
            "evidence": [{
                "kind": "command",
                "reference": "focused-check",
                "summary": "Current obligation passed",
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
        return self.apply(task_id, {
            "summary": "Current obligation passed",
            "assurance_result": result,
        })

    def start_to_source(self, workflow: str, repositories: tuple[Path, ...]) -> str:
        task_id = self.controller.start(
            requirement="Deliver the bounded change",
            workflow=workflow,
            repositories=tuple(str(item) for item in repositories),
        ).task_id
        self.apply(task_id, {})
        self.apply(task_id, self.impact(task_id, trigger=workflow == "full"))
        if workflow != "lite":
            self.apply(task_id, {
                "summary": "Plan recorded",
                "resources": {"items": []},
                "driver_result": {
                    "schema": DRIVER_RESULT_SCHEMA,
                    "status": "available",
                },
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [],
                },
            })
        self.source(task_id, self.first, "implemented")
        if workflow != "lite":
            self.apply(task_id, {
                "summary": "Documentation not required",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [],
                },
            })
        return task_id

    def test_lite_focused_change_dispatches_one_check_and_no_review(self) -> None:
        task_id = self.start_to_source("lite", (self.first,))
        projection = self.controller.next(task_id)
        self.assertEqual(projection["action"]["current_obligation"]["kind"], "repository-check")
        self.assertTrue(projection["action"]["assurance"]["not_required"]["independent_review"])

        result = self.pass_obligation(task_id)
        self.assertEqual(result["projection"]["current_node"], "finalize_success")
        final = self.apply(task_id, {
            "summary": "Delivered",
            "remaining_risks": {},
            "handoff": "Ready",
        })
        self.assertEqual(final["projection"]["status"], "DONE")

    def test_full_rework_reuses_only_the_disjoint_member_check(self) -> None:
        task_id = self.start_to_source("full", (self.first, self.second))
        first_id = self.repository_id(task_id, self.first)
        second_id = self.repository_id(task_id, self.second)
        second_obligation_id = None
        while True:
            projection = self.controller.next(task_id)
            obligation = projection["action"]["current_obligation"]
            if obligation["kind"] == "independent-review":
                break
            if obligation["repository_ids"] == [second_id]:
                second_obligation_id = obligation["obligation_id"]
            self.pass_obligation(task_id)
        self.assertIsNotNone(second_obligation_id)

        review_contract = projection["action"]["review_contract"]
        finding = finding_template({
            "schema": "dev-flow-review-finding/0.3.0",
            "severity": "high",
            "blocking": True,
            "causal_relation": "introduced",
            "criterion_ids": projection["contract"]["criterion_ids"],
            "repository_id": first_id,
            "path": "a.txt",
            "symbol": None,
            "location_label": None,
            "evidence": [{
                "kind": "source",
                "reference": "a.txt",
                "summary": "Introduced defect",
                "source_confirmed": True,
            }],
            "causal_manifest_entries": [],
            "causal_path": [],
            "smallest_sufficient_resolution": "Repair a.txt",
            "reviewer_assurance": "independent",
            "limitations": [],
            "task_id": task_id,
            "contract_digest": review_contract["contract_digest"],
            "plan_digest": projection["action"]["assurance"]["plan_digest"],
            "manifest_digest": review_contract["manifest_digest"],
            "review_scope_digest": review_contract["review_scope_digest"],
            "guidance_digest": review_contract["guidance_digest"],
            "reviewer_digest": "b" * 64,
            "workspace_digest": review_contract["workspace_digest"],
        })
        review_result = {
            "obligation_id": obligation["obligation_id"],
            "passed": False,
            "evidence": [],
            "limitations": [],
            "review": {
                "reviewer_available": True,
                "independent": True,
                "reviewer_digest": "b" * 64,
                "review_scope_digest": review_contract["review_scope_digest"],
                "guidance_digest": review_contract["guidance_digest"],
                "workspace_digest": review_contract["workspace_digest"],
                "findings": [finding],
                "claimed_outcome": "changes-requested",
            },
        }
        rework = self.apply(task_id, {
            "summary": "Review requested bounded rework",
            "assurance_result": review_result,
        })
        self.assertEqual(rework["projection"]["current_node"], "verification_rework")

        self.source(task_id, self.first, "repaired")
        projection = self.controller.next(task_id)
        states = projection["action"]["assurance"]["obligation_states"]
        reused = [item for item in states if item["state"] == "reused"]
        self.assertEqual(len(reused), 1)
        self.assertEqual(reused[0]["obligation_id"], second_obligation_id)
        current = projection["action"]["current_obligation"]
        self.assertNotEqual(current["repository_ids"], [second_id])

    def test_authorized_accepted_risk_resolves_blocking_unknown_atomically(self) -> None:
        task_id = self.start_to_source("full", (self.first,))
        while True:
            projection = self.controller.next(task_id)
            obligation = projection["action"]["current_obligation"]
            if obligation["kind"] == "independent-review":
                break
            self.pass_obligation(task_id)

        review_contract = projection["action"]["review_contract"]
        finding = finding_template({
            "schema": "dev-flow-review-finding/0.3.0",
            "severity": "high",
            "blocking": True,
            "causal_relation": "unknown",
            "criterion_ids": projection["contract"]["criterion_ids"],
            "repository_id": self.repository_id(task_id, self.first),
            "path": "a.txt",
            "symbol": None,
            "location_label": None,
            "evidence": [{
                "kind": "source",
                "reference": "a.txt",
                "summary": "Causality could not be bounded",
                "source_confirmed": False,
            }],
            "causal_manifest_entries": [],
            "causal_path": [],
            "smallest_sufficient_resolution": "Authorize the exact residual risk",
            "reviewer_assurance": "independent",
            "limitations": ["Causal path remains unknown"],
            "task_id": task_id,
            "contract_digest": review_contract["contract_digest"],
            "plan_digest": projection["action"]["assurance"]["plan_digest"],
            "manifest_digest": review_contract["manifest_digest"],
            "review_scope_digest": review_contract["review_scope_digest"],
            "guidance_digest": review_contract["guidance_digest"],
            "reviewer_digest": "c" * 64,
            "workspace_digest": review_contract["workspace_digest"],
        })
        triage = self.apply(task_id, {
            "summary": "Blocking causality remains unknown",
            "assurance_result": {
                "obligation_id": obligation["obligation_id"],
                "passed": False,
                "evidence": [],
                "limitations": ["Causal path remains unknown"],
                "review": {
                    "reviewer_available": True,
                    "independent": True,
                    "reviewer_digest": "c" * 64,
                    "review_scope_digest": review_contract["review_scope_digest"],
                    "guidance_digest": review_contract["guidance_digest"],
                    "workspace_digest": review_contract["workspace_digest"],
                    "findings": [finding],
                    "claimed_outcome": "triage-required",
                },
            },
        })
        self.assertEqual(triage["projection"]["current_node"], "impact")
        review_record = self.controller.show(task_id).records[-1]
        review_digest = review_record["artifact"]["body"]["review_result"]["digest"]
        revision = triage["projection"]["revision"]
        disposition = {
            "schema": FINDING_DISPOSITION_SCHEMA,
            "kind": "accepted-risk",
            "task_id": task_id,
            "contract_digest": review_contract["contract_digest"],
            "plan_digest": projection["action"]["assurance"]["plan_digest"],
            "review_digest": review_digest,
            "finding_fingerprint": finding["fingerprint"],
            "actor": "task-owner",
            "rationale": "Accept this exact unresolved causal risk",
            "expected_revision": revision,
            "next_contract": None,
        }
        with self.assertRaises(DevFlowError) as context:
            self.controller.dispose_finding(
                task_id,
                disposition=disposition,
                actor_authorized=False,
            )
        self.assertEqual(context.exception.code, "FINDING_DISPOSITION_FORBIDDEN")
        resolved = self.controller.dispose_finding(
            task_id,
            disposition=disposition,
            actor_authorized=True,
        )
        self.assertEqual(resolved["projection"]["current_node"], "verify")
        self.assertEqual(
            resolved["projection"]["action"]["action_id"],
            "delivery.finalize.success",
        )
        restarted = Controller(self.data_dir)
        final_projection = restarted.next(task_id)
        final = restarted.apply(
            task_id,
            final_projection["action"]["action_id"],
            {"summary": "Delivered", "remaining_risks": {}, "handoff": "Ready"},
            binding=final_projection["action"]["binding"],
        )
        self.assertEqual(final["projection"]["status"], "DONE")
        dossier = restarted.show(task_id).records[-1]["artifact"]["body"]
        self.assertEqual(
            dossier["finding_dispositions"][0]["finding_fingerprint"],
            finding["fingerprint"],
        )
        self.assertEqual(
            dossier["review_findings"][0]["fingerprint"],
            finding["fingerprint"],
        )


if __name__ == "__main__":
    unittest.main()
