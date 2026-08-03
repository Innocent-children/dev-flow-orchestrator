"""Focused multi-repository evidence, assurance, and dossier journeys."""

from __future__ import annotations

from pathlib import Path
import tempfile
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.delivery import CONTRACT_SCHEMA
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    AGENT_PROTOCOL_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
)
from support import make_repository


def driver_result(status: str, **details: object) -> dict:
    return {
        "schema": DRIVER_RESULT_SCHEMA,
        "status": status,
        **details,
    }


class MultiRepositoryDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.api = make_repository(self.root, "api")
        self.client = make_repository(self.root, "client")
        self.data_dir = str(self.root / "data")
        self.controller = Controller(self.data_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start_multi(self, workflow: str = "lite"):
        return self.controller.start(
            requirement="Deliver API and client together",
            workflow=workflow,
            repositories=(str(self.client), str(self.api)),
        )

    def apply_current(self, task_id: str, payload: dict) -> dict:
        projection = self.controller.next(task_id)
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    def apply_after_mutation(self, task_id: str, payload: dict, mutation) -> dict:
        projection = self.controller.next(task_id)
        mutation()
        return self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            payload,
            binding=projection["action"]["binding"],
        )

    @staticmethod
    def append(path: Path, text: str) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")

    @staticmethod
    def member_ids(state) -> tuple:
        return tuple(repository.repository_id for repository in state.repositories)

    def verification_payload(
        self,
        state,
        *,
        criterion_id: str = "requirement",
        criterion: str = "proven",
        passed: bool = True,
        integration_command: str = "python3 verify_integration.py",
    ) -> dict:
        repositories = {
            repository.repository_id: {
                "command": "python3 verify_{}.py".format(repository.repository_id),
                "passed": passed,
            }
            for repository in state.repositories
        }
        return {
            "passed": passed,
            "command": integration_command,
            "coverage": {
                "schema": VERIFICATION_COVERAGE_SCHEMA,
                "criteria": {criterion_id: criterion},
                "repositories": repositories,
                "integration": {
                    "command": integration_command,
                    "passed": passed,
                },
            },
            "summary": "Aggregate verification recorded",
        }

    def test_feature_dossier_covers_exact_set_resources_and_later_drift(self) -> None:
        state = self.start_multi("feature")
        repository_ids = self.member_ids(state)
        by_path = {repository.path: repository for repository in state.repositories}
        api_id = by_path[str(self.api.resolve())].repository_id
        client_id = by_path[str(self.client.resolve())].repository_id

        initial = self.controller.next(state.task_id)
        self.assertEqual(initial["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertNotIn("repository", initial)
        self.assertEqual(initial["repository_set"]["id"], state.repository_set_id)
        self.assertEqual(
            [item["id"] for item in initial["repository_set"]["repositories"]],
            list(repository_ids),
        )

        self.apply_current(state.task_id, {})
        self.apply_current(
            state.task_id,
            {
                "summary": "Impact checked across both repositories",
                "driver_result": driver_result("available"),
            },
        )

        def create_plans() -> None:
            (self.api / "plan.md").write_text("api plan\n", encoding="utf-8")
            (self.client / "plan.md").write_text("client plan\n", encoding="utf-8")

        self.apply_after_mutation(
            state.task_id,
            {
                "summary": "One aggregate plan",
                "resources": {
                    "items": [
                        {
                            "repository_id": client_id,
                            "path": "plan.md",
                            "role": "governing",
                            "normalizer": "none",
                        },
                        {
                            "repository_id": api_id,
                            "path": "plan.md",
                            "role": "governing",
                            "normalizer": "none",
                        },
                    ]
                },
                "driver_result": driver_result("available"),
            },
            create_plans,
        )

        def implement() -> None:
            self.append(self.api / "a.txt", "api implementation")
            self.append(self.client / "a.txt", "client implementation")

        self.apply_after_mutation(
            state.task_id,
            {"summary": "Implementation complete"},
            implement,
        )
        self.apply_after_mutation(
            state.task_id,
            {"summary": "Documentation complete"},
            lambda: (self.client / "documentation.md").write_text(
                "combined usage\n", encoding="utf-8"
            ),
        )

        verification = self.controller.next(state.task_id)
        self.assertEqual(
            verification["action"]["verification_coverage"]["repository_ids"],
            list(repository_ids),
        )
        self.apply_current(state.task_id, self.verification_payload(state))
        self.apply_current(
            state.task_id,
            {
                "outcome": "approved",
                "assurance": "independent",
                "findings": {},
                "summary": "Independent review approved",
                "driver_result": driver_result("available"),
            },
        )
        result = self.apply_current(
            state.task_id,
            {
                "summary": "Delivered exact repository set",
                "remaining_risks": {},
                "handoff": "Ready for user-owned publication",
            },
        )

        self.assertTrue(result["projection"]["done"])
        self.assertEqual(
            result["projection"]["dossier"]["schema"],
            DELIVERY_DOSSIER_SCHEMA,
        )
        final = self.controller.show(state.task_id)
        dossier = final.records[-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(dossier["repository_set"]["id"], state.repository_set_id)
        self.assertEqual(
            [item["repository_id"] for item in dossier["repository_set"]["members"]],
            list(repository_ids),
        )
        self.assertEqual(set(dossier["changed_repositories"]), set(repository_ids))
        self.assertEqual(len(dossier["verification_attempts"]), 1)
        self.assertTrue(dossier["verification_attempts"][0]["current"])
        self.assertEqual(
            set(dossier["verification"]["coverage"]["repositories"]),
            set(repository_ids),
        )
        self.assertTrue(dossier["aggregate_freshness"]["current"])
        self.assertEqual(
            {
                item["resource"]["repository_id"]
                for item in dossier["resources"]
                if item["resource"]["path"] == "plan.md"
            },
            set(repository_ids),
        )
        self.assertTrue(
            all(
                record["snapshot"]["schema"]
                == REPOSITORY_SET_SNAPSHOT_SCHEMA
                for record in final.records
                if record["kind"] != "decision"
            )
        )

        self.append(self.api / "a.txt", "post-delivery drift")
        stale = self.controller.next(state.task_id)
        self.assertFalse(stale["dossier"]["current"])
        self.assertIn(
            "workspace_changed:" + api_id,
            stale["dossier"]["stale_reasons"],
        )
        documentation_record = next(
            record
            for record in final.records
            if record["producer"].get("node_id") == "documentation"
        )
        self.assertIn(
            "workspace_changed:" + api_id,
            stale["freshness"][documentation_record["record_id"]]["reasons"],
        )

    def test_nested_coverage_is_exact_and_unverified_is_a_failure_attempt(self) -> None:
        state = self.start_multi()
        self.apply_current(state.task_id, {})
        self.apply_after_mutation(
            state.task_id,
            {"summary": "Implementation complete"},
            lambda: self.append(self.api / "a.txt", "implementation"),
        )
        projection = self.controller.next(state.task_id)
        binding = projection["action"]["binding"]
        baseline_revision = projection["revision"]
        valid = self.verification_payload(state)

        invalid_payloads = []
        missing = self.verification_payload(state)
        del missing["coverage"]["repositories"][self.member_ids(state)[0]]
        invalid_payloads.append(missing)
        unknown = self.verification_payload(state)
        unknown["coverage"]["repositories"]["unknown"] = {
            "command": "python3 unknown.py",
            "passed": True,
        }
        invalid_payloads.append(unknown)
        command_mismatch = self.verification_payload(state)
        command_mismatch["command"] = "python3 another.py"
        invalid_payloads.append(command_mismatch)
        passed_mismatch = self.verification_payload(state)
        passed_mismatch["passed"] = False
        invalid_payloads.append(passed_mismatch)

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(DevFlowError) as invalid:
                    self.controller.apply(
                        state.task_id,
                        projection["action"]["action_id"],
                        payload,
                        binding=binding,
                    )
                self.assertEqual(invalid.exception.code, "NODE_OUTPUT_INVALID")
                self.assertEqual(
                    self.controller.show(state.task_id).revision,
                    baseline_revision,
                )

        valid["coverage"]["criteria"]["requirement"] = "unverified"
        recorded = self.controller.apply(
            state.task_id,
            projection["action"]["action_id"],
            valid,
            binding=binding,
        )
        self.assertEqual(recorded["receipt"]["current_node"], "verification_rework")
        self.assertEqual(
            recorded["projection"]["action"]["retry_budget"],
            {"attempts_used": 1, "max_attempts": 2, "remaining": 1},
        )
        failed = self.controller.show(state.task_id).records[-1]
        self.assertTrue(failed["payload"]["passed"])
        self.assertEqual(
            failed["artifact"]["body"]["coverage"]["criteria"]["requirement"],
            "unverified",
        )

        reworked = self.apply_after_mutation(
            state.task_id,
            {"summary": "Addressed incomplete criterion evidence"},
            lambda: self.append(self.client / "a.txt", "verification rework"),
        )
        self.assertEqual(
            reworked["projection"]["action"]["retry_budget"]["attempts_used"],
            1,
        )
        exhausted_payload = self.verification_payload(state, criterion="unverified")
        exhausted = self.apply_current(state.task_id, exhausted_payload)
        self.assertEqual(
            exhausted["receipt"]["current_node"],
            "finalize_verification_incomplete",
        )
        finalized = self.apply_current(
            state.task_id,
            {
                "summary": "Verification evidence remains incomplete",
                "remaining_risks": {"requirement": "unverified"},
                "handoff": "Collect complete aggregate evidence",
            },
        )
        self.assertEqual(finalized["receipt"]["status"], "INCOMPLETE")
        dossier = self.controller.show(state.task_id).records[-1]["artifact"]["body"]
        self.assertEqual(dossier["schema"], DELIVERY_DOSSIER_SCHEMA)
        self.assertEqual(dossier["outcome"], "incomplete")
        self.assertEqual(len(dossier["verification_attempts"]), 2)
        self.assertEqual(
            [attempt["current"] for attempt in dossier["verification_attempts"]],
            [False, True],
        )
        self.assertEqual(
            dossier["verification"]["coverage"]["criteria"]["requirement"],
            "unverified",
        )

    def test_repository_scoped_governing_resource_stales_exact_member(self) -> None:
        state = self.start_multi("feature")
        by_path = {repository.path: repository for repository in state.repositories}
        api_id = by_path[str(self.api.resolve())].repository_id
        client_id = by_path[str(self.client.resolve())].repository_id
        self.apply_current(state.task_id, {})
        self.apply_current(
            state.task_id,
            {
                "summary": "Impact checked",
                "driver_result": driver_result("available"),
            },
        )
        def create_plans() -> None:
            (self.api / "plan.md").write_text("api plan\n", encoding="utf-8")
            (self.client / "plan.md").write_text("client plan\n", encoding="utf-8")

        self.apply_after_mutation(
            state.task_id,
            {
                "summary": "Scoped plans recorded",
                "resources": {
                    "items": [
                        {
                            "repository_id": api_id,
                            "path": "plan.md",
                            "role": "governing",
                            "normalizer": "none",
                        },
                        {
                            "repository_id": client_id,
                            "path": "plan.md",
                            "role": "governing",
                            "normalizer": "none",
                        },
                    ]
                },
                "driver_result": driver_result("available"),
            },
            create_plans,
        )
        planning = self.controller.show(state.task_id).records[-1]
        self.assertEqual(
            {resource["repository_id"] for resource in planning["artifact"]["resources"]},
            {api_id, client_id},
        )

        def mutate_bound_plan() -> None:
            self.append(self.client / "plan.md", "changed plan obligation")
            self.append(self.api / "a.txt", "implementation")

        result = self.apply_after_mutation(
            state.task_id,
            {"summary": "Implementation touched a bound plan"},
            mutate_bound_plan,
        )
        self.assertEqual(result["projection"]["action"]["blocked"]["code"], "ARTIFACT_INPUT_MISSING")
        reasons = result["projection"]["freshness"][planning["record_id"]]["reasons"]
        self.assertIn("governing_resource_changed:" + client_id, reasons)
        self.assertNotIn("governing_resource_changed:" + api_id, reasons)

    def test_dossier_keeps_old_contract_verification_as_stale(self) -> None:
        state = self.start_multi()
        self.apply_current(state.task_id, {})
        self.apply_after_mutation(
            state.task_id,
            {"summary": "Revision one implementation"},
            lambda: self.append(self.api / "a.txt", "revision one"),
        )
        self.apply_current(
            state.task_id,
            self.verification_payload(state, criterion="unverified"),
        )
        revised_contract = {
            "schema": CONTRACT_SCHEMA,
            "revision": 2,
            "summary": "Revised aggregate delivery",
            "acceptance_criteria": [
                {"id": "revised", "statement": "Revised set is verified"}
            ],
            "scope": ["Exact repository set"],
            "constraints": ["Aggregate proof"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        self.controller.revise_contract(
            state.task_id,
            contract=revised_contract,
            reason="Replace the acceptance criterion",
            actor_label="maintainer",
        )
        self.apply_after_mutation(
            state.task_id,
            {"summary": "Revision two implementation"},
            lambda: self.append(self.client / "a.txt", "revision two"),
        )
        self.apply_current(
            state.task_id,
            self.verification_payload(state, criterion_id="revised"),
        )
        self.apply_current(
            state.task_id,
            {
                "summary": "Revised delivery complete",
                "remaining_risks": {},
                "handoff": "Ready",
            },
        )
        dossier = self.controller.show(state.task_id).records[-1]["artifact"]["body"]
        self.assertEqual(len(dossier["verification_attempts"]), 2)
        historical, current = dossier["verification_attempts"]
        self.assertFalse(historical["current"])
        self.assertIn("contract_changed", historical["stale_reasons"])
        self.assertTrue(current["current"])
        self.assertEqual(
            dossier["verification"]["coverage"]["criteria"],
            {"revised": "proven"},
        )

    def test_revision_uses_set_snapshot_and_decisions_keep_three_nulls(self) -> None:
        state = self.start_multi()
        self.apply_current(state.task_id, {})
        revised_contract = {
            "schema": CONTRACT_SCHEMA,
            "revision": 2,
            "summary": "Revised exact-set delivery",
            "acceptance_criteria": [
                {"id": "revised", "statement": "Both members are verified"}
            ],
            "scope": ["API and client"],
            "constraints": ["Immutable repository set"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }
        self.controller.revise_contract(
            state.task_id,
            contract=revised_contract,
            reason="Clarify aggregate criterion",
            actor_label="maintainer",
        )
        self.controller.decide(
            state.task_id,
            decision={
                "id": "risk-1",
                "kind": "risk-acceptance",
                "subject": "publication",
                "outcome": "accepted",
                "rationale": "Publication remains user-owned",
                "actor_label": "maintainer",
            },
        )
        current = self.controller.show(state.task_id)
        revision_record = current.records[-2]
        decision_record = current.records[-1]
        self.assertEqual(revision_record["kind"], "contract-revision")
        self.assertEqual(
            revision_record["snapshot"]["schema"],
            REPOSITORY_SET_SNAPSHOT_SCHEMA,
        )
        self.assertEqual(
            revision_record["artifact"]["snapshot"],
            revision_record["snapshot"],
        )
        self.assertIsNone(revision_record["binding"])
        self.assertEqual(decision_record["kind"], "decision")
        self.assertIsNone(decision_record["snapshot"])
        self.assertIsNone(decision_record["artifact"])
        self.assertIsNone(decision_record["binding"])
        self.assertEqual(Controller(self.data_dir).show(state.task_id), current)

        one_member = Controller(str(self.root / "one-member-data"))
        one_member_state = one_member.start(
            requirement="One-member repository-set decision",
            workflow="lite",
            repositories=(str(self.api),),
        )
        projection = one_member.next(one_member_state.task_id)
        self.assertEqual(projection["schema"], AGENT_PROTOCOL_SCHEMA)
        self.assertEqual(len(projection["repository_set"]["repositories"]), 1)
        one_member.apply(
            one_member_state.task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        one_member.decide(
            one_member_state.task_id,
            decision={
                "id": "one-member-risk",
                "kind": "risk-acceptance",
                "subject": "publication",
                "outcome": "accepted",
                "rationale": "Publication remains user-owned",
                "actor_label": "maintainer",
            },
        )
        one_member_decision = one_member.show(one_member_state.task_id).records[-1]
        self.assertEqual(
            (
                one_member_decision["snapshot"],
                one_member_decision["artifact"],
                one_member_decision["binding"],
            ),
            (None, None, None),
        )


if __name__ == "__main__":
    unittest.main()
