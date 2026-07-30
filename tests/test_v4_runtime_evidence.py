from __future__ import annotations

import copy
import unittest

from scripts.dev_flow_parts import action_execution_journal as journal
from scripts.dev_flow_parts import action_execution_store as store
from scripts.dev_flow_parts import runtime_adapters as runtime
from tests.test_action_execution_journal import MANAGER_SECRET, _sha
from tests.test_action_execution_store import ActionExecutionStoreCase


def _thread_request(*, attempt: int, revision: int) -> object:
    return runtime.build_runtime_execution_request(
        executor_id="executor.codex-thread/v1",
        task_id="task-vector",
        workflow_bundle_sha256=_sha("v4-bundle"),
        node_instance_id="node-runtime",
        repository_id="repo-a",
        revision=revision,
        attempt=attempt,
        input_sha256=_sha(f"runtime-input-{attempt}"),
        effect_classification="repository-write",
        logical_model_policy="balanced",
        workspace_path="/worktrees/repo-a",
        approved_paths=("src",),
        prompt_sha256=_sha("runtime-prompt"),
    )


def _runtime_event(
    reservation: dict[str, object],
    containment: dict[str, object],
) -> dict[str, object]:
    return {
        "schema": "dev-flow-v4-runtime-result-event/v1",
        "task_id": reservation["task_id"],
        "payload": {
            "execution": {
                "execution_id": reservation["execution_id"],
                "effect_id": reservation["effect_id"],
                "claim_id": containment["claim_id"],
                "attempt_id": containment["attempt_id"],
                "runtime_handle_sha256": reservation[
                    "runtime_handle_sha256"
                ],
                "containment_record_sha256": reservation[
                    "containment_record_sha256"
                ],
                "runtime_reservation_record_sha256": reservation[
                    "record_sha256"
                ],
            },
            "outcome": "exited",
        },
    }


class V4RuntimeReservationEvidenceTests(ActionExecutionStoreCase):
    def test_release_requires_fresh_controller_evidence_and_exact_outbox(
        self,
    ) -> None:
        index, current, containment, reservation = (
            self.complete_asynchronous()
        )
        closure = self.store.archive_and_close(
            "execution-vector",
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            authoritative_event_sha256=_sha("runtime-event"),
            promote_runtime_reservation=True,
            manager_secret=MANAGER_SECRET,
        )
        event = _runtime_event(reservation, containment)
        event_sha256 = runtime.v4_runtime_result_event_sha256(event)
        settled_core = {
            key: value
            for key, value in reservation.items()
            if key != "record_sha256"
        }
        settled_core.update(
            {
                "phase": "EXITED",
                "result_event_sha256": event_sha256,
            }
        )
        settled = journal.seal_runtime_reservation(settled_core)
        authority = runtime.V4RuntimeEvidenceAuthority(
            monotonic_clock=lambda: 10.0
        )
        evidence = authority.issue_settlement(
            task_id=str(reservation["task_id"]),
            execution_id=str(reservation["execution_id"]),
            effect_id=str(reservation["effect_id"]),
            claim_id=str(containment["claim_id"]),
            attempt_id=str(containment["attempt_id"]),
            runtime_attempt=1,
            executor_id="executor.codex-thread/v1",
            request_id="request-v4",
            node_instance_id="node-runtime",
            repository_id="repo-a",
            runtime_handle_sha256=str(
                reservation["runtime_handle_sha256"]
            ),
            containment_record_sha256=str(
                reservation["containment_record_sha256"]
            ),
            runtime_reservation_record_sha256=str(
                reservation["record_sha256"]
            ),
            settlement="EXITED",
            runtime_exit_or_quiescence_sha256=_sha("runtime-exit"),
            authoritative_event=event,
        )

        with self.assertRaises(
            store.ActionExecutionStoreError
        ) as raised:
            self.store.release_v4_runtime_reservation(
                settled,
                expected_index=journal.cas_token(closure.index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                evidence_authority=authority,
                settlement_evidence=evidence,
                authoritative_event=event,
            )
        self.assertEqual(
            raised.exception.code,
            "ACTION_STORE_V4_RUNTIME_EVENT_MISSING",
        )

        (self.task_dir / "events.jsonl").write_bytes(
            journal.semantic_json_bytes(event) + b"\n"
        )
        wrong_authority = runtime.V4RuntimeEvidenceAuthority(
            monotonic_clock=lambda: 10.0
        )
        with self.assertRaises(
            store.ActionExecutionStoreError
        ) as raised:
            self.store.release_v4_runtime_reservation(
                settled,
                expected_index=journal.cas_token(closure.index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                evidence_authority=wrong_authority,
                settlement_evidence=evidence,
                authoritative_event=event,
            )
        self.assertEqual(
            raised.exception.code,
            "ACTION_STORE_V4_RUNTIME_EVIDENCE_INVALID",
        )

        tampered_event = copy.deepcopy(event)
        tampered_event["payload"]["outcome"] = "cancelled"
        with self.assertRaises(
            store.ActionExecutionStoreError
        ) as raised:
            self.store.release_v4_runtime_reservation(
                settled,
                expected_index=journal.cas_token(closure.index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                evidence_authority=authority,
                settlement_evidence=evidence,
                authoritative_event=tampered_event,
            )
        self.assertEqual(
            raised.exception.code,
            "ACTION_STORE_V4_RUNTIME_EVENT_MISSING",
        )

        wrong_claim = authority.issue_settlement(
            task_id=str(reservation["task_id"]),
            execution_id=str(reservation["execution_id"]),
            effect_id=str(reservation["effect_id"]),
            claim_id="claim-wrong",
            attempt_id=str(containment["attempt_id"]),
            runtime_attempt=1,
            executor_id="executor.codex-thread/v1",
            request_id="request-v4",
            node_instance_id="node-runtime",
            repository_id="repo-a",
            runtime_handle_sha256=str(
                reservation["runtime_handle_sha256"]
            ),
            containment_record_sha256=str(
                reservation["containment_record_sha256"]
            ),
            runtime_reservation_record_sha256=str(
                reservation["record_sha256"]
            ),
            settlement="EXITED",
            runtime_exit_or_quiescence_sha256=_sha("runtime-exit"),
            authoritative_event=event,
        )
        with self.assertRaises(
            store.ActionExecutionStoreError
        ) as raised:
            self.store.release_v4_runtime_reservation(
                settled,
                expected_index=journal.cas_token(closure.index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                evidence_authority=authority,
                settlement_evidence=wrong_claim,
                authoritative_event=event,
            )
        self.assertEqual(
            raised.exception.code,
            "ACTION_STORE_V4_RUNTIME_EVIDENCE_MISMATCH",
        )
        self.assertEqual(
            self.store.read_index()["entries"][0]["entry_kind"],
            "runtime-reservation",
        )

        released = self.store.release_v4_runtime_reservation(
            settled,
            expected_index=journal.cas_token(closure.index),
            expected_reservation_record_sha256=str(
                reservation["record_sha256"]
            ),
            evidence_authority=authority,
            settlement_evidence=evidence,
            authoritative_event=event,
        )
        self.assertEqual(released.index["entries"], [])
        self.assertEqual(released.record["phase"], "EXITED")


class V4RuntimeReplacementAuthorityTests(unittest.TestCase):
    def test_new_attempt_requires_exact_terminal_abandoned_authority(
        self,
    ) -> None:
        first = _thread_request(attempt=1, revision=7)
        handle = runtime.build_runtime_handle_record(
            first, handle_id="thread-v4"
        )
        running = runtime.build_runtime_attempt_record(
            first, phase="running", runtime_handle=handle
        )
        quiescence_sha256 = _sha("runtime-quiescence")
        quiesced_handle = runtime.update_runtime_handle(
            handle,
            availability="quiesced",
            quiescence_evidence_sha256=quiescence_sha256,
        )
        previous = runtime.update_runtime_attempt(
            running,
            phase="quiesced",
            runtime_handle=quiesced_handle,
            quiescence_evidence_sha256=quiescence_sha256,
        )
        second = _thread_request(attempt=2, revision=8)
        legacy_proof = runtime.build_runtime_replacement_proof(
            previous,
            next_attempt=2,
            authorization_sha256=_sha("legacy-authorization"),
            reason="recovery",
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_v4_runtime_dispatch(
                second,
                attempts=(previous,),
                handles=(quiesced_handle,),
                replacement_proof=legacy_proof,
            )
        self.assertEqual(
            raised.exception.code,
            "V4_RUNTIME_ABANDONED_AUTHORITY_REQUIRED",
        )

        clock = [20.0]
        authority = runtime.V4RuntimeEvidenceAuthority(
            monotonic_clock=lambda: clock[0]
        )
        event = {
            "schema": "dev-flow-v4-runtime-result-event/v1",
            "task_id": "task-vector",
            "payload": {"outcome": "quiesced"},
        }
        settlement = authority.issue_settlement(
            task_id="task-vector",
            execution_id="execution-vector",
            effect_id="effect-a",
            claim_id="claim-a",
            attempt_id="attempt-a",
            runtime_attempt=1,
            executor_id=str(first.executor_id),
            request_id=str(first.request_id),
            node_instance_id=str(first.node_instance_id),
            repository_id=str(first.repository_id),
            runtime_handle_sha256=_sha("runtime-handle"),
            containment_record_sha256=_sha("containment"),
            runtime_reservation_record_sha256=_sha("reservation"),
            settlement="QUIESCED",
            runtime_exit_or_quiescence_sha256=quiescence_sha256,
            authoritative_event=event,
            ttl_seconds=1,
        )
        abandoned = authority.issue_terminal_abandoned(
            settlement,
            terminal_reconciliation_record_sha256=_sha(
                "terminal-abandoned"
            ),
            no_accepted_outcome_evidence_sha256=_sha("no-outcome"),
            authorization_sha256=_sha("recovery-authorization"),
        )
        proof = runtime.build_v4_runtime_replacement_proof(
            previous,
            next_attempt=2,
            evidence_authority=authority,
            terminal_abandoned_authority=abandoned,
        )
        wrong_target_settlement = authority.issue_settlement(
            task_id="task-vector",
            execution_id="execution-vector",
            effect_id="effect-a",
            claim_id="claim-a",
            attempt_id="attempt-a",
            runtime_attempt=1,
            executor_id=str(first.executor_id),
            request_id=str(first.request_id),
            node_instance_id="node-other",
            repository_id=str(first.repository_id),
            runtime_handle_sha256=_sha("runtime-handle"),
            containment_record_sha256=_sha("containment"),
            runtime_reservation_record_sha256=_sha("reservation"),
            settlement="QUIESCED",
            runtime_exit_or_quiescence_sha256=quiescence_sha256,
            authoritative_event=event,
            ttl_seconds=1,
        )
        wrong_target_abandoned = authority.issue_terminal_abandoned(
            wrong_target_settlement,
            terminal_reconciliation_record_sha256=_sha(
                "wrong-target-abandoned"
            ),
            no_accepted_outcome_evidence_sha256=_sha("no-outcome"),
            authorization_sha256=_sha("recovery-authorization"),
        )
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.build_v4_runtime_replacement_proof(
                previous,
                next_attempt=2,
                evidence_authority=authority,
                terminal_abandoned_authority=wrong_target_abandoned,
            )
        self.assertEqual(
            raised.exception.code,
            "V4_RUNTIME_ABANDONED_AUTHORITY_MISMATCH",
        )

        decision = runtime.plan_v4_runtime_dispatch(
            second,
            attempts=(previous,),
            handles=(quiesced_handle,),
            replacement_proof=proof,
            evidence_authority=authority,
            terminal_abandoned_authority=abandoned,
        )
        self.assertEqual(decision.action, "replace")
        self.assertEqual(decision.replaced_attempt, 1)

        clock[0] = 22.0
        with self.assertRaises(runtime.RuntimeAdapterError) as raised:
            runtime.plan_v4_runtime_dispatch(
                second,
                attempts=(previous,),
                handles=(quiesced_handle,),
                replacement_proof=proof,
                evidence_authority=authority,
                terminal_abandoned_authority=abandoned,
            )
        self.assertEqual(
            raised.exception.code,
            "V4_RUNTIME_ABANDONED_AUTHORITY_EXPIRED",
        )


if __name__ == "__main__":
    unittest.main()
