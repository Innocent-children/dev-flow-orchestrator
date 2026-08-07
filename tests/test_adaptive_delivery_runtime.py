"""Focused controller journeys for 0.3 adaptive dispatch and selective reuse."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import subprocess
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

    def source(
        self,
        task_id: str,
        repository: Path,
        marker: str,
        *,
        path: str = "a.txt",
        staged: bool = False,
    ) -> dict:
        projection = self.controller.next(task_id)
        with (repository / path).open("a", encoding="utf-8") as stream:
            stream.write(marker + "\n")
        if staged:
            subprocess.run(
                ["git", "-C", str(repository), "add", "--", path],
                check=True,
            )
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {
                "summary": marker,
                "ownership_claims": self.claims(task_id, repository, path),
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

    def start_to_source(
        self,
        workflow: str,
        repositories: tuple[Path, ...],
        *,
        staged: bool = False,
        trigger: bool | None = None,
    ) -> str:
        task_id = self.controller.start(
            requirement="Deliver the bounded change",
            workflow=workflow,
            repositories=tuple(str(item) for item in repositories),
        ).task_id
        self.apply(task_id, {})
        self.apply(task_id, self.impact(
            task_id,
            trigger=workflow == "full" if trigger is None else trigger,
        ))
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
        self.source(task_id, self.first, "implemented", staged=staged)
        if workflow != "lite":
            self.apply(task_id, {
                "summary": "Documentation not required",
                "ownership_claims": {
                    "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                    "claims": [],
                },
            })
        return task_id

    def test_fully_staged_first_tracked_change_keeps_immutable_origin(self) -> None:
        task_id = self.start_to_source("lite", (self.first,), staged=True)
        source_record = next(
            record
            for record in reversed(self.controller.show(task_id).records)
            if isinstance(record.get("artifact"), Mapping)
            and isinstance(record["artifact"].get("body"), Mapping)
            and isinstance(
                record["artifact"]["body"].get("task_change_manifest"), Mapping
            )
        )
        entries = source_record["artifact"]["body"]["task_change_manifest"]["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "a.txt")
        self.assertEqual(entries[0]["change_kind"], "modified")
        self.assertNotEqual(
            entries[0]["original_before"]["index_entries"][0]["oid"],
            entries[0]["current_after"]["index_entries"][0]["oid"],
        )

    def test_lite_focused_change_dispatches_one_check_and_no_review(self) -> None:
        task_id = self.start_to_source("lite", (self.first,))
        source_record = next(
            record
            for record in reversed(self.controller.show(task_id).records)
            if isinstance(record.get("artifact"), Mapping)
            and isinstance(record["artifact"].get("body"), Mapping)
            and isinstance(
                record["artifact"]["body"].get("task_change_manifest"), Mapping
            )
        )
        manifest_entry = source_record["artifact"]["body"]["task_change_manifest"][
            "entries"
        ][0]
        original = manifest_entry["original_before"]
        self.assertEqual(original["worktree"]["kind"], "regular")
        self.assertIsNotNone(original["worktree"]["worktree_oid"])
        self.assertEqual(
            original["worktree"]["worktree_oid"],
            original["index_entries"][0]["oid"],
        )
        projection = self.controller.next(task_id)
        self.assertEqual(projection["action"]["current_obligation"]["kind"], "repository-check")
        self.assertTrue(projection["action"]["assurance"]["not_required"]["independent_review"])
        with self.assertRaises(DevFlowError) as non_review_waiver:
            self.controller.decide(
                task_id,
                decision={
                    "id": "invalid-repository-waiver",
                    "kind": "assurance-waiver",
                    "subject": projection["action"]["current_obligation"]["obligation_id"],
                    "outcome": "waived",
                    "rationale": "Repository evidence cannot be waived",
                    "actor_label": "maintainer",
                },
            )
        self.assertEqual(non_review_waiver.exception.code, "DECISION_INVALID")

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
        second_execution_record_id = None
        while True:
            projection = self.controller.next(task_id)
            obligation = projection["action"]["current_obligation"]
            if obligation["kind"] == "independent-review":
                break
            if obligation["repository_ids"] == [second_id]:
                second_obligation_id = obligation["obligation_id"]
            self.pass_obligation(task_id)
            if obligation["repository_ids"] == [second_id]:
                second_execution_record_id = self.controller.show(task_id).records[-1][
                    "record_id"
                ]
        self.assertIsNotNone(second_obligation_id)

        review_contract = projection["action"]["review_contract"]
        finding = finding_template({
            "schema": "dev-flow-review-finding/0.4.0",
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
            "causal_manifest_entries": [{
                "repository_id": first_id,
                "path": "a.txt",
            }],
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
        unbound_body = {
            key: value
            for key, value in finding.items()
            if key not in ("finding_id", "fingerprint")
        }
        unbound_body["causal_manifest_entries"] = []
        unbound_finding = finding_template(unbound_body)
        rejected_result = {
            **review_result,
            "review": {
                **review_result["review"],
                "findings": [unbound_finding],
            },
        }
        before_rejected_review = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as unbound:
            self.apply(task_id, {
                "summary": "Unbound introduced finding",
                "assurance_result": rejected_result,
            })
        self.assertEqual(unbound.exception.code, "REVIEW_FINDING_INVALID")
        self.assertEqual(self.controller.show(task_id), before_rejected_review)
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
        while self.controller.next(task_id)["action"].get("current_obligation") is not None:
            self.pass_obligation(task_id)
        ready = self.controller.next(task_id)
        self.assertEqual(
            ready["action"]["action_id"],
            "delivery.finalize.success",
            ready["action"],
        )
        final = self.apply(task_id, {
            "summary": "Reworked delivery complete",
            "remaining_risks": {},
            "handoff": "Ready",
        })
        self.assertEqual(final["projection"]["status"], "DONE")
        dossier = self.controller.show(task_id).records[-1]["artifact"]["body"]
        second_artifact = next(
            item
            for item in dossier["artifacts"]
            if item["record_id"] == second_execution_record_id
        )
        self.assertTrue(second_artifact["current"])
        self.assertEqual(tuple(second_artifact["stale_reasons"]), ())
        second_history = next(
            item
            for item in dossier["assurance_history"]
            if item["record_id"] == second_execution_record_id
        )
        self.assertTrue(second_history["current"])

    def test_same_member_disjoint_rework_reuses_proof_and_records_basis(self) -> None:
        task_id = self.start_to_source("feature", (self.first,), trigger=True)
        repository_projection = self.controller.next(task_id)
        repository_obligation = repository_projection["action"]["current_obligation"]
        self.assertEqual(repository_obligation["kind"], "repository-check")
        repository_execution = self.pass_obligation(task_id)
        repository_record_id = self.controller.show(task_id).records[-1]["record_id"]

        projection = self.controller.next(task_id)
        review_obligation = projection["action"]["current_obligation"]
        review_contract = projection["action"]["review_contract"]
        finding = finding_template({
            "schema": "dev-flow-review-finding/0.4.0",
            "severity": "high",
            "blocking": True,
            "causal_relation": "introduced",
            "criterion_ids": projection["contract"]["criterion_ids"],
            "repository_id": self.repository_id(task_id, self.first),
            "path": "a.txt",
            "symbol": None,
            "location_label": None,
            "evidence": [{
                "kind": "source",
                "reference": "a.txt",
                "summary": "Bounded review finding",
                "source_confirmed": True,
            }],
            "causal_manifest_entries": [{
                "repository_id": self.repository_id(task_id, self.first),
                "path": "a.txt",
            }],
            "causal_path": [],
            "smallest_sufficient_resolution": "Apply bounded rework",
            "reviewer_assurance": "independent",
            "limitations": [],
            "task_id": task_id,
            "contract_digest": review_contract["contract_digest"],
            "plan_digest": projection["action"]["assurance"]["plan_digest"],
            "manifest_digest": review_contract["manifest_digest"],
            "review_scope_digest": review_contract["review_scope_digest"],
            "guidance_digest": review_contract["guidance_digest"],
            "reviewer_digest": "d" * 64,
            "workspace_digest": review_contract["workspace_digest"],
        })
        self.apply(task_id, {
            "summary": "Review requested rework",
            "assurance_result": {
                "obligation_id": review_obligation["obligation_id"],
                "passed": False,
                "evidence": [],
                "limitations": [],
                "review": {
                    "reviewer_available": True,
                    "independent": True,
                    "reviewer_digest": "d" * 64,
                    "review_scope_digest": review_contract["review_scope_digest"],
                    "guidance_digest": review_contract["guidance_digest"],
                    "workspace_digest": review_contract["workspace_digest"],
                    "findings": [finding],
                    "claimed_outcome": "changes-requested",
                },
            },
        })
        self.source(task_id, self.first, "disjoint", path="b.txt")

        replanned = self.controller.next(task_id)
        states = replanned["action"]["assurance"]["obligation_states"]
        repository_state = next(
            item for item in states if item["kind"] == "repository-check"
        )
        self.assertEqual(repository_state["state"], "reused")
        reuse = next(
            item
            for item in replanned["action"]["assurance"]["reuse_decisions"]
            if item["current_obligation_id"] == repository_state["obligation_id"]
        )
        self.assertEqual(reuse["status"], "reused")
        self.assertEqual(reuse["changed_slice"], [{
            "repository_id": self.repository_id(task_id, self.first),
            "path": "b.txt",
        }])
        self.assertEqual(
            replanned["action"]["current_obligation"]["kind"],
            "independent-review",
        )
        self.pass_obligation(task_id)
        final = self.apply(task_id, {
            "summary": "Disjoint rework completed",
            "remaining_risks": {},
            "handoff": "Ready",
        })
        self.assertEqual(final["projection"]["status"], "DONE")
        dossier = self.controller.show(task_id).records[-1]["artifact"]["body"]
        dossier_reuse = next(
            item
            for item in dossier["assurance_reuse_history"]
            if str(item["execution_record_id"]) == str(repository_record_id)
        )
        self.assertEqual(dossier_reuse["status"], "reused")
        review_history = dossier["review_history"]
        self.assertTrue(review_history[-1]["review_binding"]["independent"])
        self.assertEqual(
            review_history[-1]["review_binding"]["reviewer_digest"],
            "a" * 64,
        )

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
            "schema": "dev-flow-review-finding/0.4.0",
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
        second_body = {
            key: value
            for key, value in finding.items()
            if key not in ("finding_id", "fingerprint")
        }
        second_body["evidence"] = [{
            "kind": "source",
            "reference": "a.txt",
            "summary": "A second bounded causal uncertainty remains",
            "source_confirmed": False,
        }]
        second_body["smallest_sufficient_resolution"] = (
            "Authorize the second exact residual risk"
        )
        second_finding = finding_template(second_body)
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
                    "findings": [finding, second_finding],
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
            resolved["projection"]["action"]["current_obligation"]["kind"],
            "independent-review",
        )
        duplicate = {
            **disposition,
            "expected_revision": resolved["projection"]["revision"],
        }
        before_duplicate = self.controller.show(task_id)
        with self.assertRaises(DevFlowError) as duplicate_error:
            self.controller.dispose_finding(
                task_id,
                disposition=duplicate,
                actor_authorized=True,
            )
        self.assertEqual(
            duplicate_error.exception.code,
            "FINDING_DISPOSITION_INVALID",
        )
        self.assertEqual(self.controller.show(task_id), before_duplicate)
        second_disposition = {
            **disposition,
            "finding_fingerprint": second_finding["fingerprint"],
            "rationale": "Accept the second exact unresolved causal risk",
            "expected_revision": resolved["projection"]["revision"],
        }
        resolved = self.controller.dispose_finding(
            task_id,
            disposition=second_disposition,
            actor_authorized=True,
        )
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
            {item["finding_fingerprint"] for item in dossier["finding_dispositions"]},
            {finding["fingerprint"], second_finding["fingerprint"]},
        )
        self.assertEqual(
            {item["fingerprint"] for item in dossier["review_findings"]},
            {finding["fingerprint"], second_finding["fingerprint"]},
        )


if __name__ == "__main__":
    unittest.main()
