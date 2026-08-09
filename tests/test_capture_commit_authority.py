"""Controller-level capture/commit authority regression tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

import test_adaptive_delivery_runtime as adaptive_runtime
import test_delivery_runtime as delivery_runtime
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.delivery import CONTRACT_SCHEMA
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    FINDING_DISPOSITION_SCHEMA,
    WORKSPACE_FRESHNESS_SCHEMA,
)
from dev_flow_orchestrator.review import finding_template
import dev_flow_orchestrator.store as store_module
from support import RepositoryTestCase, make_repository


class CaptureCommitAuthorityTests(RepositoryTestCase):
    """Prove the controller routes every repository-bound write through one protocol."""

    decision = delivery_runtime.DeliveryRuntimeTests.decision

    @staticmethod
    def revised_contract(revision: int) -> dict:
        return {
            "schema": CONTRACT_SCHEMA,
            "revision": revision,
            "summary": "Revised capture authority scope",
            "acceptance_criteria": [{
                "id": "revised",
                "statement": "The revised scope is verified",
            }],
            "scope": ["Revised scope"],
            "constraints": ["One bounded repository set"],
            "risks": [],
            "non_goals": [],
            "open_questions": [],
        }

    def assert_committed_receipt(
        self,
        result: Mapping[str, object],
        *,
        freshness: object,
    ) -> Mapping[str, object]:
        receipt = result["receipt"]
        self.assertIsInstance(receipt, Mapping)
        self.assertIs(receipt["committed"], True)
        self.assertIs(receipt["blind_retry"], False)
        self.assertEqual(receipt["workspace_freshness"]["schema"], WORKSPACE_FRESHNESS_SCHEMA)
        self.assertEqual(receipt["workspace_freshness"]["status"], freshness)
        self.assertEqual(receipt["recovery"]["kind"], "read-after-write")
        self.assertEqual(receipt["recovery"]["tool"], "dev_flow_get_next_action")
        self.assertIs(receipt["recovery"]["blind_retry"], False)
        return receipt

    def assert_prewrite_drift_is_atomic(
        self,
        controller: Controller,
        task_id: str,
        repository: Path,
        invoke: Callable[[Controller], Mapping[str, object]],
        *,
        retry: bool = True,
    ) -> tuple[Controller, Mapping[str, object] | None]:
        """Inject S-to-S' drift, prove no write, restore, reread, and retry."""
        state_path = controller.store._state_path(task_id)
        source_path = repository / "a.txt"
        source_before = source_path.read_bytes()
        bytes_before = state_path.read_bytes()
        state_before = controller.show(task_id)
        fields_before = (
            state_before.revision,
            state_before.current_node,
            state_before.status,
            len(state_before.records),
        )
        hook_calls = []

        def hook(phase: str) -> None:
            if phase == "before-revalidation":
                hook_calls.append(phase)
                source_path.write_bytes(
                    source_before + b"capture-authority-prewrite-drift\n"
                )

        sentinel = object()
        result: object = sentinel
        controller._mutation_test_hook = hook
        try:
            with self.assertRaises(DevFlowError) as caught:
                result = invoke(controller)
        finally:
            controller._mutation_test_hook = None

        self.assertIs(result, sentinel, "a rejected mutation must not return a receipt")
        self.assertEqual(caught.exception.code, "SNAPSHOT_UNSTABLE")
        self.assertEqual(caught.exception.details.get("phase"), "revalidation")
        self.assertEqual(hook_calls, ["before-revalidation"])
        self.assertEqual(state_path.read_bytes(), bytes_before)

        state_after = Controller(str(controller.store.root)).show(task_id)
        self.assertEqual(
            (
                state_after.revision,
                state_after.current_node,
                state_after.status,
                len(state_after.records),
            ),
            fields_before,
        )
        if state_before.status != "DONE":
            self.assertNotEqual(state_after.status, "DONE")

        source_path.write_bytes(source_before)
        restarted = Controller(str(controller.store.root))
        reread = restarted.next(task_id)
        self.assertEqual(reread["revision"], state_before.revision)
        if not retry:
            return restarted, None

        retried = invoke(restarted)
        receipt = self.assert_committed_receipt(retried, freshness=True)
        persisted = restarted.show(task_id)
        self.assertEqual(receipt["committed_revision"], persisted.revision)
        self.assertEqual(persisted.revision, state_before.revision + 1)
        return restarted, retried

    def test_prewrite_revalidation_covers_apply_decision_revision_and_cancel(self) -> None:
        task_id = self.start_lite("Exercise all ordinary mutation entry points")

        def apply_invoke(current: Controller) -> Mapping[str, object]:
            projection = current.next(task_id)
            return current.apply(
                task_id,
                projection["action"]["action_id"],
                {},
                binding=projection["action"]["binding"],
            )
        self.controller, _ = self.assert_prewrite_drift_is_atomic(
            self.controller,
            task_id,
            self.repository,
            apply_invoke,
        )

        decision = self.decision("capture-authority-risk")
        decision_invoke = lambda current: current.decide(
            task_id,
            decision=decision,
        )
        self.controller, _ = self.assert_prewrite_drift_is_atomic(
            self.controller,
            task_id,
            self.repository,
            decision_invoke,
        )

        revision_invoke = lambda current: current.revise_contract(
            task_id,
            contract=self.revised_contract(2),
            reason="Exercise capture authority",
            actor_label="maintainer",
        )
        self.controller, _ = self.assert_prewrite_drift_is_atomic(
            self.controller,
            task_id,
            self.repository,
            revision_invoke,
        )

        def cancel_invoke(current: Controller) -> Mapping[str, object]:
            with patch.object(
                current,
                "apply",
                side_effect=AssertionError("cancel must not nest public apply"),
            ):
                return current.cancel(task_id, reason="Bounded cancellation")

        self.controller, cancelled = self.assert_prewrite_drift_is_atomic(
            self.controller,
            task_id,
            self.repository,
            cancel_invoke,
        )
        self.assertEqual(cancelled["receipt"]["status"], "CANCELLED")
        self.assertEqual(self.controller.show(task_id).status, "CANCELLED")

    def test_prewrite_revalidation_detects_drift_in_nonfirst_member(self) -> None:
        other = make_repository(self.root, "other")
        state = self.controller.start(
            requirement="Capture every repository-set member",
            workflow="lite",
            repositories=(str(self.repository), str(other)),
        )
        task_id = state.task_id
        persisted = self.controller.show(task_id)
        self.assertEqual(len(persisted.repositories), 2)
        nonfirst = Path(persisted.repositories[1].path)
        def invoke(current: Controller) -> Mapping[str, object]:
            projection = current.next(task_id)
            return current.apply(
                task_id,
                projection["action"]["action_id"],
                {},
                binding=projection["action"]["binding"],
            )
        self.controller, result = self.assert_prewrite_drift_is_atomic(
            self.controller,
            task_id,
            nonfirst,
            invoke,
        )
        self.assertEqual(result["receipt"]["committed_revision"], 1)

    def prepare_disposition(self):
        journey = adaptive_runtime.AdaptiveDeliveryRuntimeTests(methodName="runTest")
        journey.setUp()
        self.addCleanup(journey.tearDown)
        task_id = journey.start_to_source("full", (journey.first,))

        while True:
            projection = journey.controller.next(task_id)
            obligation = projection["action"]["current_obligation"]
            if obligation["kind"] == "independent-review":
                break
            journey.pass_obligation(task_id)

        review_contract = projection["action"]["review_contract"]
        finding = finding_template({
            "schema": "dev-flow-review-finding/0.4.0",
            "severity": "high",
            "blocking": True,
            "causal_relation": "unknown",
            "criterion_ids": projection["contract"]["criterion_ids"],
            "repository_id": journey.repository_id(task_id, journey.first),
            "path": "a.txt",
            "symbol": None,
            "location_label": None,
            "evidence": [{
                "kind": "source",
                "reference": "a.txt",
                "summary": "Causality cannot be bounded further",
                "source_confirmed": False,
            }],
            "causal_manifest_entries": [],
            "causal_path": [],
            "smallest_sufficient_resolution": "Authorize this exact residual risk",
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
        triage = journey.apply(task_id, {
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
        review_digest = journey.controller.show(task_id).records[-1]["artifact"][
            "body"
        ]["review_result"]["digest"]
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
            "expected_revision": triage["projection"]["revision"],
            "next_contract": None,
        }
        return journey, task_id, disposition

    def test_disposition_and_finalize_use_revalidation_and_report_residual_window(self) -> None:
        journey, task_id, disposition = self.prepare_disposition()

        dispose_invoke = lambda current: current.dispose_finding(
            task_id,
            disposition=disposition,
            actor_authorized=True,
        )
        journey.controller, disposed = self.assert_prewrite_drift_is_atomic(
            journey.controller,
            task_id,
            journey.first,
            dispose_invoke,
        )
        self.assertEqual(
            disposed["projection"]["action"]["action_id"],
            "delivery.finalize.success",
        )

        final_payload = {
            "summary": "Delivery complete",
            "remaining_risks": {},
            "handoff": "Ready",
        }

        def final_invoke(current: Controller) -> Mapping[str, object]:
            final_projection = current.next(task_id)
            return current.apply(
                task_id,
                final_projection["action"]["action_id"],
                final_payload,
                binding=final_projection["action"]["binding"],
            )
        journey.controller, _ = self.assert_prewrite_drift_is_atomic(
            journey.controller,
            task_id,
            journey.first,
            final_invoke,
            retry=False,
        )

        source_path = journey.first / "a.txt"
        source_before = source_path.read_bytes()
        hook_calls = []

        def residual_window(phase: str) -> None:
            if phase == "after-revalidation":
                hook_calls.append(phase)
                source_path.write_bytes(
                    source_before + b"capture-authority-residual-window\n"
                )

        journey.controller._mutation_test_hook = residual_window
        try:
            final = final_invoke(journey.controller)
        finally:
            journey.controller._mutation_test_hook = None

        receipt = self.assert_committed_receipt(final, freshness=False)
        self.assertEqual(hook_calls, ["after-revalidation"])
        self.assertEqual(receipt["status"], "DONE")
        self.assertIsNotNone(receipt["workspace_freshness"]["observed_at"])
        self.assertIn("workspace_changed", receipt["workspace_freshness"]["reasons"])
        self.assertIsNotNone(final["projection"])
        self.assertEqual(final["projection"]["status"], "DONE")
        self.assertIs(final["projection"]["dossier"]["current"], False)
        self.assertEqual(journey.controller.show(task_id).status, "DONE")

    def test_postwrite_freshness_modes_and_frozen_capture_partitions(self) -> None:
        task_id = self.start_lite("Report committed workspace freshness")
        projection = self.controller.next(task_id)
        captured_partitions = []
        original_capture = self.controller._capture_snapshot

        def recording_capture(state, partitions, *, phase):
            captured_partitions.append(partitions)
            return original_capture(state, partitions, phase=phase)

        with patch.object(
            self.controller,
            "_partition_resources",
            wraps=self.controller._partition_resources,
        ) as partition_resources, patch.object(
            self.controller,
            "_capture_snapshot",
            side_effect=recording_capture,
        ):
            matching = self.controller.apply(
                task_id,
                projection["action"]["action_id"],
                {},
                binding=projection["action"]["binding"],
            )

        matching_receipt = self.assert_committed_receipt(matching, freshness=True)
        self.assertIsNotNone(matching_receipt["workspace_freshness"]["observed_at"])
        self.assertEqual(partition_resources.call_count, 1)
        self.assertEqual(len(captured_partitions), 3)
        self.assertTrue(
            all(item is captured_partitions[0] for item in captured_partitions),
            "S, S', and observation must reuse one frozen partition mapping",
        )

        source_path = self.repository / "a.txt"
        source_before = source_path.read_bytes()
        false_calls = []

        def postwrite_drift(phase: str) -> None:
            if phase == "before-observation":
                false_calls.append(phase)
                source_path.write_bytes(
                    source_before + b"capture-authority-observation-drift\n"
                )

        self.controller._mutation_test_hook = postwrite_drift
        try:
            changed = self.controller.decide(
                task_id,
                decision=self.decision("postwrite-change"),
            )
        finally:
            self.controller._mutation_test_hook = None
        changed_receipt = self.assert_committed_receipt(changed, freshness=False)
        self.assertEqual(false_calls, ["before-observation"])
        self.assertIsNotNone(changed_receipt["workspace_freshness"]["observed_at"])
        self.assertIn(
            "workspace_changed",
            changed_receipt["workspace_freshness"]["reasons"],
        )
        self.assertIsNotNone(changed["projection"])

        source_path.write_bytes(source_before)
        unknown_calls = []

        def observation_failure(phase: str) -> None:
            if phase == "before-observation":
                unknown_calls.append(phase)
                raise RuntimeError("private observation failure detail")

        self.controller._mutation_test_hook = observation_failure
        try:
            unknown = self.controller.decide(
                task_id,
                decision=self.decision(
                    "postwrite-unknown",
                    subject="second-local-risk",
                ),
            )
        finally:
            self.controller._mutation_test_hook = None

        unknown_receipt = self.assert_committed_receipt(unknown, freshness="unknown")
        self.assertEqual(unknown_calls, ["before-observation"])
        self.assertIsNone(unknown_receipt["workspace_freshness"]["observed_at"])
        self.assertEqual(
            unknown_receipt["workspace_freshness"]["reasons"],
            ["observation_failed:OBSERVATION_FAILED"],
        )
        self.assertIsNone(unknown["projection"])
        self.assertEqual(self.controller.show(task_id).revision, 3)

    def test_repository_lock_acquisition_failure_releases_entered_authorities(self) -> None:
        other = make_repository(self.root, "lock-other")
        state = self.controller.start(
            requirement="Release partial repository lock acquisition",
            workflow="lite",
            repositories=(str(self.repository), str(other)),
        )
        task_id = state.task_id
        projection = self.controller.next(task_id)
        state_path = self.controller.store._state_path(task_id)
        state_before = state_path.read_bytes()
        events = []
        repository_attempts = 0

        @contextmanager
        def failing_lock(path):
            nonlocal repository_attempts
            name = path.name
            events.append(("attempt", name))
            if name.startswith("repository-"):
                repository_attempts += 1
                if repository_attempts == 2:
                    raise DevFlowError(
                        "LOCK_ACQUISITION_TEST",
                        "inject second repository lock acquisition failure",
                    )
            events.append(("enter", name))
            try:
                yield
            finally:
                events.append(("exit", name))

        with patch(
            "dev_flow_orchestrator.store.exclusive_file_lock",
            side_effect=failing_lock,
        ):
            with self.assertRaises(DevFlowError) as caught:
                self.controller.apply(
                    task_id,
                    projection["action"]["action_id"],
                    {},
                    binding=projection["action"]["binding"],
                )

        self.assertEqual(caught.exception.code, "LOCK_ACQUISITION_TEST")
        entered = [name for event, name in events if event == "enter"]
        exited = [name for event, name in events if event == "exit"]
        self.assertEqual(entered[0], "membership.lock")
        self.assertTrue(entered[1].startswith("repository-"))
        self.assertEqual(len(entered), 2)
        self.assertEqual(exited, list(reversed(entered)))
        self.assertFalse(any(name == task_id + ".lock" for _, name in events))
        self.assertEqual(state_path.read_bytes(), state_before)
        self.assertEqual(self.controller.show(task_id).revision, 0)

        fresh = self.controller.next(task_id)
        recovered = self.controller.apply(
            task_id,
            fresh["action"]["action_id"],
            {},
            binding=fresh["action"]["binding"],
        )
        self.assert_committed_receipt(recovered, freshness=True)
        self.assertEqual(self.controller.show(task_id).revision, 1)

    def test_opposite_repository_inputs_contend_in_one_canonical_order(self) -> None:
        other = make_repository(self.root, "concurrent-other")
        state = self.controller.start(
            requirement="Canonical concurrent repository lock order",
            workflow="lite",
            repositories=(str(self.repository), str(other)),
        )
        records = self.controller.show(state.task_id).repositories
        self.assertEqual(len(records), 2)

        start = threading.Barrier(3)
        first_inside = threading.Event()
        release_first = threading.Event()
        inside_guard = threading.Lock()
        entered = []
        orders = {}
        errors = []

        def acquire(label: str, supplied_records) -> None:
            try:
                authorities = self.controller.store._repository_authorities(
                    supplied_records
                )
                orders[label] = tuple(
                    (authority.identity, authority.lock_path)
                    for authority in authorities
                )
                start.wait(2)
                with ExitStack() as locks:
                    for authority in authorities:
                        locks.enter_context(
                            store_module.exclusive_file_lock(authority.lock_path)
                        )
                    with inside_guard:
                        is_first = not entered
                        entered.append(label)
                    if is_first:
                        first_inside.set()
                        release_first.wait(2)
            except BaseException as exc:  # preserve thread failures for the test
                errors.append(exc)

        forward = threading.Thread(
            target=acquire,
            args=("forward", records),
            daemon=True,
        )
        reverse = threading.Thread(
            target=acquire,
            args=("reverse", tuple(reversed(records))),
            daemon=True,
        )
        forward.start()
        reverse.start()
        try:
            start.wait(2)
            self.assertTrue(
                first_inside.wait(2),
                "opposite input order prevented either worker acquiring the full set",
            )
        finally:
            release_first.set()
            forward.join(3)
            reverse.join(3)

        self.assertFalse(forward.is_alive(), "forward lock worker deadlocked")
        self.assertFalse(reverse.is_alive(), "reverse lock worker deadlocked")
        self.assertEqual(errors, [])
        self.assertEqual(set(entered), {"forward", "reverse"})
        self.assertEqual(orders["forward"], orders["reverse"])
        self.assertEqual(
            [identity for identity, _path in orders["forward"]],
            sorted(identity for identity, _path in orders["forward"]),
        )


if __name__ == "__main__":
    unittest.main()
