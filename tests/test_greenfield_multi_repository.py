from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError, canonical_json_bytes
from dev_flow_orchestrator.repository_kernel import (
    accept_result,
    authority_evidence_ids,
    build_plan,
    issue_ready_leases,
)
from tests.greenfield_authority import ConversationAuthority


class GreenfieldMultiRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repositories = (
            self._repository("alpha"),
            self._repository("beta"),
        )
        self.controller = Controller(str(self.root / "data"))
        self.authority = ConversationAuthority(
            self.controller,
            self.repositories[0],
            session_id="multi-repository-session",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _repository(self, name: str) -> Path:
        repository = self.root / name
        repository.mkdir()
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        (repository / "README.md").write_text(name + "\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository), "add", "README.md"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Greenfield Test",
                "-c",
                "user.email=greenfield@example.invalid",
                "commit",
                "-q",
                "-m",
                "initial",
            ],
            check=True,
        )
        return repository

    def _apply(self, task_id: str, action_id: str, payload: dict):
        revision = self.controller.show(task_id).revision
        return self.authority.apply(
            task_id,
            revision,
            action_id,
            payload,
        )

    def _start_multi(self, task_id: str, workflow: str) -> None:
        self.controller.start(
            requirement="coordinate two repositories",
            workflow=workflow,
            workspace_strategy="in-place",
            repositories=[str(path) for path in self.repositories],
            task_id=task_id,
        )
        self.controller.preflight(task_id, 0)
        if workflow == "full":
            self._apply(
                task_id,
                "evidence.baseline.record",
                {"baseline": "two repository heads"},
            )
            self._apply(
                task_id,
                "evidence.impact.record",
                {"impact": "both repositories"},
            )
            self._apply(
                task_id,
                "task.route.set",
                {"route": "coordinated", "reason": "shared contract"},
            )
            self._apply(task_id, "workspace.prepare", {})
            self._apply(
                task_id,
                "evidence.plan.record",
                {"plan": "coordinate repositories"},
            )
            self._apply(task_id, "gate.plan.approve", {"approved": True})
        self.assertEqual(
            self.controller.show(task_id).current_node,
            "repository-plan",
        )

    def _record_plan(
        self,
        task_id: str,
        dependencies: dict,
        *,
        concurrency: int = 2,
        max_retries: int = 1,
    ) -> None:
        self._apply(
            task_id,
            "repository.plan.record",
            {
                "dependencies": dependencies,
                "concurrency": concurrency,
                "max_retries": max_retries,
            },
        )
        self._apply(task_id, "repository.lease.issue", {})

    def test_full_and_lite_resolve_to_the_same_repository_contracts(self) -> None:
        observed_actions = []
        for task_id, workflow in (("full-multi", "full"), ("lite-multi", "lite")):
            self._start_multi(task_id, workflow)
            projection = self.controller.next(task_id)
            observed_actions.append(projection["action"])
            self.assertEqual(projection["action"]["action_id"], "repository.plan.record")
            self.assertEqual(
                projection["additional_actions"][0]["action_id"],
                "repository.cancel",
            )
        self.assertEqual(observed_actions[0], observed_actions[1])
        lite = self.controller.show("lite-multi")
        self.assertEqual(lite.workflow_id, "lite")
        self.assertFalse(
            any(
                item["node_id"] in {"baseline", "impact", "route", "planning"}
                for item in lite.evidence
            )
        )

    def test_repository_dag_lease_barrier_and_integration(self) -> None:
        self._start_multi("dag", "lite")
        repository_ids = [
            item.repository_id
            for item in self.controller.show("dag").repositories
        ]
        first, second = sorted(repository_ids, key=lambda item: item.encode("utf-8"))
        self._record_plan(
            "dag",
            {first: [], second: [first]},
            concurrency=2,
        )
        state = self.controller.show("dag")
        owners = set(state.orchestration["owners"].values())
        self.assertEqual(len(owners), 1)
        self.assertTrue(next(iter(owners)).startswith("local:"))
        active = [
            lease
            for lease in state.orchestration["leases"].values()
            if lease["status"] == "ACTIVE"
        ]
        self.assertEqual([lease["repository_id"] for lease in active], [first])
        projection = self.controller.next("dag")
        self.assertEqual(len(projection["frontier"]), 1)
        self.assertEqual(
            projection["frontier"][0]["arguments"]["lease_id"],
            active[0]["lease_id"],
        )
        self._apply(
            "dag",
            "repository.result.accept",
            {
                "repository_id": first,
                "lease_id": active[0]["lease_id"],
                "outcome": "PASS",
                "result_sha256": "a" * 64,
            },
        )
        state = self.controller.show("dag")
        second_lease = next(
            lease
            for lease in state.orchestration["leases"].values()
            if lease["repository_id"] == second and lease["status"] == "ACTIVE"
        )
        self._apply(
            "dag",
            "repository.result.accept",
            {
                "repository_id": second,
                "lease_id": second_lease["lease_id"],
                "outcome": "PASS",
                "result_sha256": "b" * 64,
            },
        )
        self.assertEqual(
            self.controller.show("dag").current_node,
            "repository-barrier",
        )
        self._apply("dag", "repository.barrier.close", {})
        self._apply(
            "dag",
            "repository.integration.record",
            {"integration_sha256": "c" * 64},
        )
        state = self.controller.show("dag")
        self.assertEqual(state.current_node, "implement")
        self.assertEqual(state.orchestration["status"], "INTEGRATED")

    def test_retry_and_cancellation_are_repository_scoped(self) -> None:
        self._start_multi("retry", "lite")
        repository_ids = [
            item.repository_id
            for item in self.controller.show("retry").repositories
        ]
        self._record_plan(
            "retry",
            {repository_id: [] for repository_id in repository_ids},
            concurrency=1,
            max_retries=1,
        )
        state = self.controller.show("retry")
        first_lease = next(
            lease
            for lease in state.orchestration["leases"].values()
            if lease["status"] == "ACTIVE"
        )
        failed_receipt = self._apply(
            "retry",
            "repository.result.accept",
            {
                "repository_id": first_lease["repository_id"],
                "lease_id": first_lease["lease_id"],
                "outcome": "FAIL",
                "result_sha256": "d" * 64,
            },
        )
        state = self.controller.show("retry")
        failed_evidence = state.orchestration["attempt_results"][
            first_lease["lease_id"]
        ]
        self.assertEqual(
            failed_evidence["schema"],
            "dev-flow-v4-repository-attempt-result/v1",
        )
        self.assertEqual(failed_evidence["attempt"], 1)
        self.assertEqual(failed_evidence["outcome"], "FAIL")
        self.assertEqual(failed_evidence["result_sha256"], "d" * 64)
        self.assertEqual(
            failed_evidence["authority_id"],
            failed_receipt.confirmation["request_id"],
        )
        self.assertEqual(
            canonical_json_bytes(
                accept_result(
                    state.orchestration,
                    repository_id=first_lease["repository_id"],
                    lease_id=first_lease["lease_id"],
                    outcome="FAIL",
                    result_sha256="d" * 64,
                    actor_id=first_lease["owner_id"],
                    authority_id=failed_receipt.confirmation["request_id"],
                    observed_head=first_lease["pinned_head"],
                )
            ),
            canonical_json_bytes(state.orchestration),
        )
        with self.assertRaises(DevFlowError) as conflicting_replay:
            accept_result(
                state.orchestration,
                repository_id=first_lease["repository_id"],
                lease_id=first_lease["lease_id"],
                outcome="FAIL",
                result_sha256="e" * 64,
                actor_id=first_lease["owner_id"],
                authority_id=failed_receipt.confirmation["request_id"],
                observed_head=first_lease["pinned_head"],
            )
        self.assertEqual(
            conflicting_replay.exception.code,
            "REPOSITORY_RESULT_CONFLICT",
        )
        with self.assertRaises(DevFlowError) as conflicting_authority:
            accept_result(
                state.orchestration,
                repository_id=first_lease["repository_id"],
                lease_id=first_lease["lease_id"],
                outcome="FAIL",
                result_sha256="d" * 64,
                actor_id=first_lease["owner_id"],
                authority_id="confirm-conflicting-authority",
                observed_head=first_lease["pinned_head"],
            )
        self.assertEqual(
            conflicting_authority.exception.code,
            "REPOSITORY_RESULT_CONFLICT",
        )
        retry_lease = next(
            lease
            for lease in state.orchestration["leases"].values()
            if lease["repository_id"] == first_lease["repository_id"]
            and lease["status"] == "ACTIVE"
        )
        self.assertEqual(retry_lease["attempt"], 2)
        accepted = {
            "schema": "dev-flow-v4-repository-plan/v1",
            "plan_id": "e" * 64,
            "repository_ids": [first_lease["repository_id"]],
            "dependencies": {first_lease["repository_id"]: []},
            "owners": {
                first_lease["repository_id"]: first_lease["owner_id"],
            },
            "pinned_heads": {
                first_lease["repository_id"]: first_lease["pinned_head"],
            },
            "concurrency": 1,
            "max_retries": 0,
            "attempts": {first_lease["repository_id"]: 1},
            "leases": {
                first_lease["lease_id"]: {
                    **first_lease,
                    "status": "SETTLED",
                }
            },
            "attempt_results": {
                first_lease["lease_id"]: {
                    "schema": "dev-flow-v4-repository-attempt-result/v1",
                    "repository_id": first_lease["repository_id"],
                    "lease_id": first_lease["lease_id"],
                    "attempt": 1,
                    "outcome": "PASS",
                    "result_sha256": "f" * 64,
                    "actor_id": first_lease["owner_id"],
                    "authority_id": "confirm-focused-result",
                    "observed_head": first_lease["pinned_head"],
                }
            },
            "results": {
                first_lease["repository_id"]: {
                    "schema": "dev-flow-v4-repository-attempt-result/v1",
                    "repository_id": first_lease["repository_id"],
                    "lease_id": first_lease["lease_id"],
                    "attempt": 1,
                    "outcome": "PASS",
                    "result_sha256": "f" * 64,
                    "actor_id": first_lease["owner_id"],
                    "authority_id": "confirm-focused-result",
                    "observed_head": first_lease["pinned_head"],
                }
            },
            "barrier": {
                "status": "READY",
                "members": [first_lease["repository_id"]],
            },
            "integration": None,
            "status": "BARRIER_READY",
        }
        self.assertEqual(
            accept_result(
                accepted,
                repository_id=first_lease["repository_id"],
                lease_id=first_lease["lease_id"],
                outcome="PASS",
                result_sha256="f" * 64,
                actor_id=first_lease["owner_id"],
                authority_id="confirm-focused-result",
                observed_head=first_lease["pinned_head"],
            ),
            accepted,
        )
        pending_cancel = self.authority.request_action(
            "retry",
            self.controller.show("retry").revision,
            "repository.cancel",
            {"reason": "operator stopped coordinated work"},
        )
        self.authority.decide(pending_cancel, approve=True)
        confirmation_projection = self.controller.next(
            "retry",
            session_id=pending_cancel.session_id,
        )["confirmation"]
        self.assertEqual(confirmation_projection["status"], "CONFIRMED")
        self.assertEqual(
            confirmation_projection["requests"][0]["action_id"],
            "repository.cancel",
        )
        cancellation = self.authority.retry_action(pending_cancel)
        state = self.controller.show("retry")
        self.assertEqual(state.status, "CANCELLED")
        self.assertEqual(state.orchestration["status"], "CANCELLED")
        self.assertEqual(cancellation.confirmation["status"], "CONSUMED")
        self.assertEqual(
            state.orchestration["cancellation"]["authority_id"],
            cancellation.confirmation["request_id"],
        )
        self.assertFalse(
            any(
                lease["status"] == "ACTIVE"
                for lease in state.orchestration["leases"].values()
            )
        )

    def test_failed_attempt_retains_authority_evidence_if_consume_fails(
        self,
    ) -> None:
        self._start_multi("failed-attempt-evidence", "lite")
        repository_ids = [
            item.repository_id
            for item in self.controller.show(
                "failed-attempt-evidence"
            ).repositories
        ]
        self._record_plan(
            "failed-attempt-evidence",
            {repository_id: [] for repository_id in repository_ids},
            concurrency=1,
            max_retries=1,
        )
        state = self.controller.show("failed-attempt-evidence")
        lease = next(
            item
            for item in state.orchestration["leases"].values()
            if item["status"] == "ACTIVE"
        )
        payload = {
            "repository_id": lease["repository_id"],
            "lease_id": lease["lease_id"],
            "outcome": "FAIL",
            "result_sha256": "9" * 64,
        }
        pending = self.authority.request_action(
            "failed-attempt-evidence",
            state.revision,
            "repository.result.accept",
            payload,
        )
        self.authority.decide(pending, approve=True)
        original_consume = self.controller.authorities.consume

        def fail_consume(task_id, request_id):
            if request_id == pending.request_id:
                raise DevFlowError(
                    "INJECTED_CONSUME_FAILURE",
                    "task commit preceded confirmation consumption",
                )
            return original_consume(task_id, request_id)

        self.controller.authorities.consume = fail_consume
        try:
            with self.assertRaises(DevFlowError) as captured:
                self.authority.retry_action(pending)
        finally:
            self.controller.authorities.consume = original_consume

        self.assertEqual(captured.exception.code, "INJECTED_CONSUME_FAILURE")
        committed = self.controller.show("failed-attempt-evidence")
        self.assertIn(
            lease["lease_id"],
            committed.orchestration["attempt_results"],
        )
        evidence = committed.orchestration["attempt_results"][lease["lease_id"]]
        self.assertEqual(
            evidence,
            {
                "schema": "dev-flow-v4-repository-attempt-result/v1",
                "repository_id": lease["repository_id"],
                "lease_id": lease["lease_id"],
                "attempt": 1,
                "outcome": "FAIL",
                "result_sha256": "9" * 64,
                "actor_id": lease["owner_id"],
                "authority_id": pending.request_id,
                "observed_head": lease["pinned_head"],
            },
        )
        retry = next(
            item
            for item in committed.orchestration["leases"].values()
            if item["repository_id"] == lease["repository_id"]
            and item["status"] == "ACTIVE"
        )
        self.assertEqual(retry["attempt"], 2)
        confirmation = next(
            record
            for record in self.controller.authorities.records_for_task(
                "failed-attempt-evidence"
            )
            if record["request_id"] == pending.request_id
        )
        self.assertEqual(confirmation["status"], "CONFIRMED")
        self.assertEqual(
            authority_evidence_ids(committed.orchestration),
            {pending.request_id},
        )
        self.controller.next(
            "failed-attempt-evidence",
            session_id=self.authority.session_id,
        )
        confirmation = next(
            record
            for record in self.controller.authorities.records_for_task(
                "failed-attempt-evidence"
            )
            if record["request_id"] == pending.request_id
        )
        self.assertEqual(confirmation["status"], "CONSUMED")

    def test_authority_evidence_helper_validates_exact_attempt_history(
        self,
    ) -> None:
        repository_id = "focused-repository"
        owner_id = "local:focused-owner"
        pinned_head = "a" * 40
        first_authority = "confirm-" + ("1" * 64)
        second_authority = "confirm-" + ("2" * 64)
        plan = issue_ready_leases(
            build_plan(
                [repository_id],
                {repository_id: []},
                owner_id,
                {repository_id: pinned_head},
                1,
                1,
            )
        )
        first_lease = next(iter(plan["leases"].values()))
        plan = accept_result(
            plan,
            repository_id=repository_id,
            lease_id=first_lease["lease_id"],
            outcome="FAIL",
            result_sha256="1" * 64,
            actor_id=owner_id,
            authority_id=first_authority,
            observed_head=pinned_head,
        )
        second_lease = next(
            lease
            for lease in plan["leases"].values()
            if lease["status"] == "ACTIVE"
        )
        plan = accept_result(
            plan,
            repository_id=repository_id,
            lease_id=second_lease["lease_id"],
            outcome="PASS",
            result_sha256="2" * 64,
            actor_id=owner_id,
            authority_id=second_authority,
            observed_head=pinned_head,
        )
        self.assertEqual(
            authority_evidence_ids(plan),
            {first_authority, second_authority},
        )
        self.assertEqual(
            plan["results"][repository_id],
            plan["attempt_results"][second_lease["lease_id"]],
        )

        cases = (
            ("plan schema", ("schema",), "wrong-plan-schema"),
            ("plan id shape", ("plan_id",), "not-a-sha256"),
            ("lease identity", ("plan_id",), "0" * 64),
            ("attempt result map", ("attempt_results",), []),
            ("lease map", ("leases",), []),
            (
                "attempt schema",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "schema",
                ),
                "wrong-attempt-schema",
            ),
            (
                "attempt extra field",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "unexpected",
                ),
                True,
            ),
            (
                "lease extra field",
                ("leases", first_lease["lease_id"], "unexpected"),
                True,
            ),
            (
                "lease key",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "lease_id",
                ),
                second_lease["lease_id"],
            ),
            (
                "repository",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "repository_id",
                ),
                "other-repository",
            ),
            (
                "attempt",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "attempt",
                ),
                2,
            ),
            (
                "owner",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "actor_id",
                ),
                "local:other-owner",
            ),
            (
                "head",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "observed_head",
                ),
                "b" * 40,
            ),
            (
                "outcome",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "outcome",
                ),
                "UNKNOWN",
            ),
            (
                "result hash",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "result_sha256",
                ),
                "not-a-sha256",
            ),
            (
                "authority",
                (
                    "attempt_results",
                    first_lease["lease_id"],
                    "authority_id",
                ),
                "confirm-not-a-current-id",
            ),
            (
                "terminal result",
                ("results", repository_id, "authority_id"),
                "confirm-unmatched-terminal",
            ),
        )
        for label, path, value in cases:
            with self.subTest(label=label):
                candidate = json.loads(
                    canonical_json_bytes(plan).decode("utf-8")
                )
                target = candidate
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(DevFlowError) as invalid:
                    authority_evidence_ids(candidate)
                self.assertEqual(
                    invalid.exception.code,
                    "REPOSITORY_STATE_INVALID",
                )
        missing_attempt = json.loads(
            canonical_json_bytes(plan).decode("utf-8")
        )
        del missing_attempt["leases"][first_lease["lease_id"]]
        del missing_attempt["attempt_results"][first_lease["lease_id"]]
        with self.assertRaises(DevFlowError) as invalid_gap:
            authority_evidence_ids(missing_attempt)
        self.assertEqual(
            invalid_gap.exception.code,
            "REPOSITORY_STATE_INVALID",
        )

    def test_frontier_owner_authority_and_pinned_head_are_repository_scoped(
        self,
    ) -> None:
        self._start_multi("bindings", "lite")
        state = self.controller.show("bindings")
        repository_ids = [
            item.repository_id
            for item in state.repositories
        ]
        self._record_plan(
            "bindings",
            {repository_id: [] for repository_id in repository_ids},
            concurrency=2,
            max_retries=0,
        )
        state = self.controller.show("bindings")
        active = sorted(
            (
                lease
                for lease in state.orchestration["leases"].values()
                if lease["status"] == "ACTIVE"
            ),
            key=lambda lease: lease["repository_id"].encode("utf-8"),
        )
        projection = self.controller.next("bindings")
        self.assertEqual(len(active), 2)
        self.assertEqual(
            [
                item["arguments"]["repository_id"]
                for item in projection["frontier"]
            ],
            [lease["repository_id"] for lease in active],
        )
        self.assertEqual(
            [
                item["node_instance_id"]
                for item in projection["frontier"]
            ],
            [
                "{}:{}:{}".format(
                    lease["repository_id"],
                    lease["attempt"],
                    lease["lease_id"],
                )
                for lease in active
            ],
        )
        first, second = active
        payload = {
            "repository_id": first["repository_id"],
            "lease_id": first["lease_id"],
            "outcome": "PASS",
            "result_sha256": "1" * 64,
        }
        pending = self.authority.request_action(
            "bindings",
            state.revision,
            "repository.result.accept",
            payload,
        )
        self.assertEqual(
            self.controller.show("bindings").revision,
            state.revision,
        )
        with self.assertRaises(DevFlowError) as wrong_owner:
            self.controller.apply(
                "bindings",
                state.revision,
                "repository.result.accept",
                {
                    **payload,
                    "lease_id": second["lease_id"],
                },
                session_id=pending.session_id,
                request_turn_id="wrong-owner",
            )
        self.assertEqual(
            wrong_owner.exception.code,
            "REPOSITORY_OWNER_MISMATCH",
        )
        request_record = next(
            record
            for record in self.controller.authorities.records_for_task(
                "bindings"
            )
            if record["request_id"] == pending.request_id
        )
        self.assertEqual(
            request_record["binding"]["scope"],
            {
                "repository_id": first["repository_id"],
                "lease_id": first["lease_id"],
            },
        )
        self.authority.decide(pending, approve=True)
        repository_path = next(
            Path(item.path)
            for item in state.repositories
            if item.repository_id == first["repository_id"]
        )
        (repository_path / "DRIFT.md").write_text("drift\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository_path), "add", "DRIFT.md"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository_path),
                "-c",
                "user.name=Greenfield Test",
                "-c",
                "user.email=greenfield@example.invalid",
                "commit",
                "-q",
                "-m",
                "drift",
            ],
            check=True,
        )
        with self.assertRaises(DevFlowError) as drift:
            self.authority.retry_action(pending)
        self.assertEqual(drift.exception.code, "REPOSITORY_DRIFT")
        cancellation = self._apply(
            "bindings",
            "repository.cancel",
            {"reason": "stop after drift"},
        )
        self.assertEqual(cancellation.confirmation["status"], "CONSUMED")
        self.assertEqual(
            self.controller.show("bindings")
            .orchestration["cancellation"]["authority_id"],
            cancellation.confirmation["request_id"],
        )

    def test_plan_validation_and_revision_cas_do_not_mutate(self) -> None:
        self._start_multi("cas", "full")
        state = self.controller.show("cas")
        repository_ids = [item.repository_id for item in state.repositories]
        requests_before = len(
            self.controller.authorities.records_for_task("cas")
        )
        with self.assertRaises(DevFlowError) as caller_owner:
            self._apply(
                "cas",
                "repository.plan.record",
                {
                    "dependencies": {
                        repository_id: []
                        for repository_id in repository_ids
                    },
                    "owners": {
                        repository_id: "caller-selected"
                        for repository_id in repository_ids
                    },
                    "concurrency": 2,
                    "max_retries": 0,
                },
            )
        self.assertEqual(caller_owner.exception.code, "NODE_OUTPUT_INVALID")
        self.assertEqual(
            len(self.controller.authorities.records_for_task("cas")),
            requests_before,
        )
        with self.assertRaises(DevFlowError) as cycle:
            self._apply(
                "cas",
                "repository.plan.record",
                {
                    "dependencies": {
                        repository_ids[0]: [repository_ids[1]],
                        repository_ids[1]: [repository_ids[0]],
                    },
                    "concurrency": 2,
                    "max_retries": 0,
                },
            )
        self.assertEqual(cycle.exception.code, "REPOSITORY_PLAN_CYCLE")
        self.assertEqual(self.controller.show("cas").revision, state.revision)
        with self.assertRaises(DevFlowError) as stale:
            self.controller.apply(
                "cas",
                state.revision + 1,
                "repository.plan.record",
                {
                    "dependencies": {
                        repository_id: []
                        for repository_id in repository_ids
                    },
                    "concurrency": 2,
                    "max_retries": 0,
                },
            )
        self.assertEqual(stale.exception.code, "REVISION_CONFLICT")
        self.assertEqual(self.controller.show("cas").revision, state.revision)


if __name__ == "__main__":
    unittest.main()
