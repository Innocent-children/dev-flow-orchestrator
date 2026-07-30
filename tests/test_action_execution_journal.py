from __future__ import annotations

import copy
import hashlib
import json
import struct
import unittest
from pathlib import Path

from scripts.dev_flow_parts import action_execution_journal as journal


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "action_execution_journal"
MANAGER_SECRET = "test-only-manager-secret-\u2713"
PROOF_KEY = bytes.fromhex(
    "000102030405060708090a0b0c0d0e0f"
    "101112131415161718191a1b1c1d1e1f"
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _compensation_plan() -> dict[str, object]:
    safe_inputs = {
        "operation": "remove-generated-output",
        "target": "/work/repo-a/output",
    }
    return {
        "schema": journal.ACTION_COMPENSATION_PLAN_SCHEMA,
        "action_id": "recovery.compensate/v1",
        "effect_id": "compensate-effect-a",
        "safe_inputs": safe_inputs,
        "safe_inputs_sha256": journal.semantic_sha256(
            journal.SAFE_INPUT_DOMAIN, safe_inputs
        ),
        "postcondition_contract_sha256": _sha(
            "compensation-postcondition-contract"
        ),
    }


def _scopes(
    repository_id: str = "repo-a",
    path: str = "/work/repo-a",
    *,
    node_id: str | None = None,
    worktree_id: str | None = None,
    lease_id: str | None = None,
    external_resource: str | None = None,
) -> dict[str, object]:
    return {
        "repository_ids": [repository_id],
        "node_ids": [node_id or f"node-{repository_id}"],
        "worktree_ids": [worktree_id or f"worktree-{repository_id}"],
        "lease_ids": [lease_id or f"lease-{repository_id}"],
        "paths": [path],
        "external_resources": (
            [] if external_resource is None else [external_resource]
        ),
    }


def _effect(
    effect_id: str = "effect-a",
    *,
    repository_id: str = "repo-a",
    path: str = "/work/repo-a",
    kind: str = "filesystem",
    settlement: str = "synchronous-quiescence",
    predecessors: list[str] | None = None,
    parallel_group: str | None = None,
) -> dict[str, object]:
    safe_inputs = {
        "operation": "materialize",
        "target": f"{path}/output",
    }
    return {
        "effect_id": effect_id,
        "kind": kind,
        "settlement": settlement,
        "scopes": _scopes(repository_id, path),
        "safe_inputs": safe_inputs,
        "safe_input_sha256": journal.semantic_sha256(
            journal.SAFE_INPUT_DOMAIN, safe_inputs
        ),
        "idempotency_key_sha256": _sha(f"idempotency:{effect_id}"),
        "predecessors": sorted(predecessors or []),
        "parallel_group": parallel_group,
        "attempt_id": f"attempt-{effect_id}",
        "phase": "PLANNED",
        "settled_as": None,
        "claim_id": None,
        "containment_record_sha256": None,
        "runtime_binding_sha256": None,
        "receipt_sha256": None,
    }


def _journal_core(
    *,
    task_id: str = "task-vector",
    execution_id: str = "execution-vector",
    effects: list[dict[str, object]] | None = None,
    concurrency_class: str = "scoped",
    authorization_kind: str = "manager",
) -> dict[str, object]:
    declared_effects = effects or [_effect()]
    repositories = sorted(
        {
            repository_id
            for effect in declared_effects
            for repository_id in effect["scopes"]["repository_ids"]
        }
    )
    nodes = sorted(
        {
            node_id
            for effect in declared_effects
            for node_id in effect["scopes"]["node_ids"]
        }
    )
    worktrees = sorted(
        {
            worktree_id
            for effect in declared_effects
            for worktree_id in effect["scopes"]["worktree_ids"]
        }
    )
    leases = sorted(
        {
            lease_id
            for effect in declared_effects
            for lease_id in effect["scopes"]["lease_ids"]
        }
    )
    paths = sorted(
        {
            path
            for effect in declared_effects
            for path in effect["scopes"]["paths"]
        }
    )
    resources = sorted(
        {
            resource
            for effect in declared_effects
            for resource in effect["scopes"]["external_resources"]
        }
    )
    scopes = {
        "repository_ids": repositories,
        "node_ids": nodes,
        "worktree_ids": worktrees,
        "lease_ids": leases,
        "paths": paths,
        "external_resources": resources,
    }
    return {
        "schema": journal.ACTION_EXECUTION_JOURNAL_SCHEMA,
        "task_id": task_id,
        "execution_id": execution_id,
        "revision": 0,
        "phase": "PREPARED",
        "bindings": {
            "task_revision": 7,
            "pre_effect_state_sha256": _sha("pre-effect-state"),
            "workflow_id": "full-dev-workflow",
            "workflow_version": "3.0.0",
            "workflow_bundle_sha256": _sha("workflow-bundle"),
            "action_edge_id": "baseline.materialize/v3",
            "authorization_action_edge_id": "baseline.materialize/v3",
            "completion_edge_id": "baseline.materialize/v3",
            "handler_id": "baseline.materialize-handler/v3",
            "effect_plan_sha256": _sha("effect-plan"),
            "concurrency_class": concurrency_class,
            "scopes": scopes,
            "authorized_paths": paths,
            "confirmation_sha256": _sha("confirmation"),
            "operation_sha256": _sha("operation"),
            "semantic_operation_sha256": _sha(
                "semantic-operation"
            ),
            "authorization_kind": authorization_kind,
            "authorization_sha256": _sha("authorization"),
            "capability_sha256": (
                _sha("capability") if authorization_kind == "manager" else None
            ),
            "request_sha256": _sha("request"),
            "request_nonce_sha256": _sha("request-nonce"),
            "principal": "manager:test",
            "guard_projection_sha256": _sha("guard-projection"),
            "evidence_sha256": _sha("evidence"),
            "approval_sha256": _sha("approval"),
            "ownership_sha256": _sha("ownership"),
            "registry_state_sha256": _sha("registry-state"),
            "postcondition_contract_sha256": _sha(
                "postcondition-contract"
            ),
            "verifier_before_sha256": _sha("verifier-before"),
            "candidate_after_sha256": _sha("candidate-after"),
            "revision_policy": "exact-revision",
        },
        "effects": declared_effects,
        "receipt": None,
        "quarantine": None,
        "reconciliation_attempt_ids": [],
        "finalization": None,
    }


def _sealed_journal(**kwargs: object) -> dict[str, object]:
    core = _journal_core(**kwargs)
    secret = MANAGER_SECRET if core["bindings"]["authorization_kind"] == "manager" else None
    return journal.seal_journal(core, manager_secret=secret)


def _initially_persisted(
    record: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    index = journal.new_index(str(record["task_id"]))
    plan = journal.plan_initial_write(
        index,
        record,
        expected_index=journal.cas_token(index),
        manager_secret=(
            MANAGER_SECRET
            if record["bindings"]["authorization_kind"] == "manager"
            else None
        ),
    )
    return plan.promoted_index, record


def _persist_update(
    index: dict[str, object],
    before: dict[str, object],
    after: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    plan = journal.plan_journal_update(
        index,
        before,
        after,
        expected_index=journal.cas_token(index),
        expected_journal=journal.cas_token(before),
        manager_secret=(
            MANAGER_SECRET
            if before["bindings"]["authorization_kind"] == "manager"
            else None
        ),
    )
    return plan.promoted_index, after


def _complete_synchronous_execution() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    current = _sealed_journal()
    index, current = _initially_persisted(current)
    claimed = journal.plan_effect_claim(
        current,
        "effect-a",
        "claim-effect-a",
        index=index,
        expected_index=journal.cas_token(index),
        manager_secret=MANAGER_SECRET,
    ).journal
    index, current = _persist_update(index, current, claimed)
    containment = journal.new_containment(
        current,
        "effect-a",
        index=index,
        expected_index=journal.cas_token(index),
        manager_secret=MANAGER_SECRET,
    )
    running = journal.advance_effect_phase(
        current,
        "effect-a",
        "RUNNING",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(containment["record_sha256"]),
    )
    index, current = _persist_update(index, current, running)
    quiesced_containment = journal.advance_containment(
        containment,
        "QUIESCED",
        receipt_sha256=_sha("quiescence-observation"),
    )
    quiesced = journal.advance_effect_phase(
        current,
        "effect-a",
        "QUIESCED",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(
            quiesced_containment["record_sha256"]
        ),
    )
    index, current = _persist_update(index, current, quiesced)
    closed_containment = journal.advance_containment(
        quiesced_containment,
        "CLOSED",
    )
    verified = journal.advance_effect_phase(
        current,
        "effect-a",
        "VERIFIED",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(closed_containment["record_sha256"]),
        receipt_sha256=_sha("effect-receipt"),
    )
    index, current = _persist_update(index, current, verified)
    settled = journal.advance_global_settlement(
        current, manager_secret=MANAGER_SECRET
    )
    index, current = _persist_update(index, current, settled)
    receipt_verified = journal.verify_receipt_intent(
        current,
        {
            "receipt_sha256": _sha("action-receipt"),
            "candidate_state_sha256": _sha("candidate-state"),
            "event_batch_sha256": _sha("event-batch"),
            "engine_proof_sha256": _sha("engine-proof"),
            "authorization_action_edge_id": "baseline.materialize/v3",
            "completion_edge_id": "baseline.materialize/v3",
        },
        manager_secret=MANAGER_SECRET,
    )
    index, current = _persist_update(index, current, receipt_verified)
    committed = journal.commit_journal(
        current,
        {
            "task_commit_revision": 8,
            "task_state_sha256": _sha("task-state"),
            "event_sha256": _sha("authoritative-event"),
            "outbox_sha256": _sha("outbox"),
            "nonce_consumed": True,
        },
        manager_secret=MANAGER_SECRET,
    )
    index, current = _persist_update(index, current, committed)
    return index, current, closed_containment


def _quarantined_execution() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    current = _sealed_journal()
    index, current = _initially_persisted(current)
    claimed = journal.plan_effect_claim(
        current,
        "effect-a",
        "claim-effect-a",
        index=index,
        expected_index=journal.cas_token(index),
        manager_secret=MANAGER_SECRET,
    ).journal
    index, current = _persist_update(index, current, claimed)
    containment = journal.new_containment(
        current,
        "effect-a",
        index=index,
        expected_index=journal.cas_token(index),
        manager_secret=MANAGER_SECRET,
    )
    running = journal.advance_effect_phase(
        current,
        "effect-a",
        "RUNNING",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(containment["record_sha256"]),
    )
    index, current = _persist_update(index, current, running)
    quiesced_containment = journal.advance_containment(
        containment,
        "QUIESCED",
        receipt_sha256=_sha("quiescence"),
    )
    quiesced = journal.advance_effect_phase(
        current,
        "effect-a",
        "QUIESCED",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(
            quiesced_containment["record_sha256"]
        ),
    )
    index, current = _persist_update(index, current, quiesced)
    closed = journal.advance_containment(quiesced_containment, "CLOSED")
    verified = journal.advance_effect_phase(
        current,
        "effect-a",
        "VERIFIED",
        manager_secret=MANAGER_SECRET,
        containment_record_sha256=str(closed["record_sha256"]),
        receipt_sha256=_sha("effect-receipt"),
    )
    index, current = _persist_update(index, current, verified)
    settled = journal.advance_global_settlement(
        current, manager_secret=MANAGER_SECRET
    )
    index, current = _persist_update(index, current, settled)
    quarantined = journal.quarantine_journal(
        current,
        reason_code="postcondition-drift",
        details_sha256=_sha("drift"),
        effect_id="effect-a",
        receipt_sha256=_sha("effect-receipt"),
        manager_secret=MANAGER_SECRET,
    )
    index, current = _persist_update(index, current, quarantined)
    assert current["effects"][0]["phase"] == "QUARANTINED"
    return index, current, closed


class SemanticJsonAndCryptoTests(unittest.TestCase):
    def test_strict_semantic_json_and_u64be(self) -> None:
        self.assertEqual(
            journal.semantic_json_bytes(
                {"z": [3, 2, 1], "a": {"value": None, "enabled": True}}
            ),
            b'{"a":{"enabled":true,"value":null},"z":[3,2,1]}',
        )
        self.assertEqual(journal.u64be(258), struct.pack(">Q", 258))
        self.assertEqual(journal.u64be(2**64 - 1), b"\xff" * 8)
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.u64be(2**64)

        invalid = (
            b'{"a":1,"a":2}',
            b'{"a":1.0}',
            b'{"a":NaN}',
            b'{"a":9223372036854775808}',
            b"\xef\xbb\xbf{}",
            '{"a":"e\u0301"}'.encode("utf-8"),
            b'{"a":"\\ud800"}',
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(journal.ActionExecutionJournalError):
                    journal.parse_semantic_json(payload)

    def test_normative_golden_fixture(self) -> None:
        fixture = json.loads(
            (FIXTURE_ROOT / "normative-vector.json").read_text(
                encoding="utf-8"
            )
        )
        record = _sealed_journal()
        index = journal.new_index("task-vector")
        core_bytes = journal.semantic_json_bytes(
            {
                key: value
                for key, value in record.items()
                if key not in {"record_sha256", "seal"}
            }
        )
        index_core_bytes = journal.semantic_json_bytes(
            {
                key: value
                for key, value in index.items()
                if key != "record_sha256"
            }
        )
        proof_payload = {
            "candidate_sha256": _sha("candidate"),
            "execution_id": "execution-vector",
            "task_id": "task-vector",
        }
        fixture_core_file = (FIXTURE_ROOT / "journal-core.json").read_bytes()
        self.assertTrue(fixture_core_file.endswith(b"\n"))
        self.assertFalse(fixture_core_file.endswith(b"\n\n"))
        fixture_core = fixture_core_file[:-1]
        self.assertEqual(
            journal.semantic_json_bytes(
                journal.parse_semantic_json(fixture_core)
            ),
            fixture_core,
        )
        self.assertEqual(core_bytes, fixture_core)
        self.assertEqual(
            index_core_bytes.hex(), fixture["index_core_hex"]
        )
        self.assertEqual(
            record["record_sha256"], fixture["journal_record_sha256"]
        )
        self.assertEqual(index["record_sha256"], fixture["index_sha256"])
        self.assertEqual(
            journal.derive_execution_key(
                MANAGER_SECRET, "task-vector", "execution-vector"
            ).hex(),
            fixture["execution_key_hex"],
        )
        self.assertEqual(record["seal"], fixture["journal_seal"])
        self.assertEqual(
            journal.engine_proof_mac(PROOF_KEY, proof_payload),
            fixture["proof_mac"],
        )

    def test_tamper_wrong_secret_identity_copy_and_restart(self) -> None:
        record = _sealed_journal()
        serialized = journal.semantic_json_bytes(record)
        restarted = journal.parse_semantic_json(serialized)
        self.assertTrue(
            journal.verify_journal_seal(
                restarted,
                MANAGER_SECRET,
                expected_task_id="task-vector",
                expected_execution_id="execution-vector",
            )
        )
        self.assertFalse(
            journal.verify_journal_seal(record, "wrong-secret")
        )
        self.assertFalse(
            journal.verify_journal_seal(
                record, MANAGER_SECRET, expected_task_id="other-task"
            )
        )
        self.assertFalse(
            journal.verify_journal_seal(
                record, MANAGER_SECRET, expected_execution_id="other-execution"
            )
        )

        tampered = copy.deepcopy(record)
        tampered["bindings"]["task_revision"] = 8
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "digest"
        ):
            journal.normalize_journal(tampered)

        other = _sealed_journal(
            task_id="task-other", execution_id="execution-other"
        )
        copied_seal = copy.deepcopy(other)
        copied_seal["seal"] = record["seal"]
        self.assertFalse(
            journal.verify_journal_seal(copied_seal, MANAGER_SECRET)
        )
        copied_digest_and_seal = copy.deepcopy(other)
        copied_digest_and_seal["record_sha256"] = record["record_sha256"]
        copied_digest_and_seal["seal"] = record["seal"]
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.normalize_journal(copied_digest_and_seal)

        for role in (
            "authorization_action_edge_id",
            "completion_edge_id",
        ):
            role_tampered = copy.deepcopy(record)
            role_tampered["bindings"][role] = "other.edge/v3"
            with self.subTest(role=role):
                with self.assertRaises(
                    journal.ActionExecutionJournalError
                ):
                    journal.normalize_journal(role_tampered)
                copied_role = copy.deepcopy(other)
                copied_role["bindings"][role] = record["bindings"][role]
                copied_role["record_sha256"] = record["record_sha256"]
                copied_role["seal"] = record["seal"]
                with self.assertRaises(
                    journal.ActionExecutionJournalError
                ):
                    journal.normalize_journal(copied_role)

        alias_mismatch = _journal_core()
        alias_mismatch["bindings"]["completion_edge_id"] = (
            "other.completion/v3"
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "alias"
        ):
            journal.seal_journal(
                alias_mismatch, manager_secret=MANAGER_SECRET
            )

        self.assertNotIn(
            MANAGER_SECRET.encode("utf-8"), journal.semantic_json_bytes(record)
        )
        secret_core = _journal_core()
        secret_core["effects"][0]["safe_inputs"]["manager_secret"] = "leak"
        secret_core["effects"][0]["safe_input_sha256"] = journal.semantic_sha256(
            journal.SAFE_INPUT_DOMAIN,
            secret_core["effects"][0]["safe_inputs"],
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "raw nonce"
        ):
            journal.seal_journal(
                secret_core, manager_secret=MANAGER_SECRET
            )
        disguised_secret = _journal_core()
        disguised_secret["effects"][0]["safe_inputs"]["token"] = MANAGER_SECRET
        disguised_secret["effects"][0][
            "safe_input_sha256"
        ] = journal.semantic_sha256(
            journal.SAFE_INPUT_DOMAIN,
            disguised_secret["effects"][0]["safe_inputs"],
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "never be serialized"
        ):
            journal.seal_journal(
                disguised_secret, manager_secret=MANAGER_SECRET
            )

    def test_proof_mac_rejects_payload_and_key_copy(self) -> None:
        payload = {
            "task_id": "task-vector",
            "execution_id": "execution-vector",
        }
        candidate = journal.engine_proof_mac(PROOF_KEY, payload)
        self.assertTrue(
            journal.verify_engine_proof_mac(PROOF_KEY, payload, candidate)
        )
        self.assertFalse(
            journal.verify_engine_proof_mac(
                PROOF_KEY,
                {**payload, "execution_id": "execution-other"},
                candidate,
            )
        )
        self.assertFalse(
            journal.verify_engine_proof_mac(b"other-key", payload, candidate)
        )

    def test_strict_records_reject_unknown_fields_and_noncanonical_effect_state(
        self,
    ) -> None:
        record = _sealed_journal()
        unknown = copy.deepcopy(record)
        unknown["unexpected"] = True
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "unknown"
        ):
            journal.normalize_journal(unknown)

        impossible = _journal_core()
        impossible["phase"] = "PREPARED"
        impossible["effects"][0]["phase"] = "CLAIMED"
        impossible["effects"][0]["claim_id"] = "claim-forged"
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "PREPARED"
        ):
            journal.seal_journal(
                impossible, manager_secret=MANAGER_SECRET
            )

    def test_receipt_binds_both_edge_roles_independently(self) -> None:
        _index, committed, _containment = (
            _complete_synchronous_execution()
        )
        settled_core = {
            key: value
            for key, value in committed.items()
            if key not in {"record_sha256", "seal"}
        }
        settled_core.update(
            {
                "revision": int(committed["revision"]) + 1,
                "phase": "QUIESCED",
                "receipt": None,
                "finalization": None,
            }
        )
        current = journal.seal_journal(
            settled_core, manager_secret=MANAGER_SECRET
        )
        receipt = {
            "receipt_sha256": _sha("edge-role-receipt"),
            "candidate_state_sha256": _sha("edge-role-candidate"),
            "event_batch_sha256": _sha("edge-role-event"),
            "engine_proof_sha256": _sha("edge-role-proof"),
            "authorization_action_edge_id": (
                current["bindings"]["authorization_action_edge_id"]
            ),
            "completion_edge_id": (
                current["bindings"]["completion_edge_id"]
            ),
        }
        verified = journal.verify_receipt_intent(
            current, receipt, manager_secret=MANAGER_SECRET
        )
        self.assertEqual(
            verified["receipt"]["authorization_action_edge_id"],
            current["bindings"]["authorization_action_edge_id"],
        )
        for role in (
            "authorization_action_edge_id",
            "completion_edge_id",
        ):
            mismatched = dict(receipt)
            mismatched[role] = "other.edge/v3"
            with self.subTest(role=role):
                with self.assertRaisesRegex(
                    journal.ActionExecutionJournalError, "exact"
                ):
                    journal.verify_receipt_intent(
                        current,
                        mismatched,
                        manager_secret=MANAGER_SECRET,
                    )


class IndexAndWriteAheadTests(unittest.TestCase):
    def test_pending_write_promote_and_recovery(self) -> None:
        record = _sealed_journal()
        index = journal.new_index("task-vector")
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "secret-channel"
        ):
            journal.plan_initial_write(
                index,
                record,
                expected_index=journal.cas_token(index),
            )
        plan = journal.plan_initial_write(
            index,
            record,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        reserved_entry = plan.reserved_index["entries"][0]
        self.assertEqual(
            reserved_entry["pending_record_sha256"],
            record["record_sha256"],
        )
        self.assertIsNone(reserved_entry["record_sha256"])
        promoted_entry = plan.promoted_index["entries"][0]
        self.assertIsNone(promoted_entry["pending_record_sha256"])
        self.assertEqual(
            promoted_entry["record_sha256"], record["record_sha256"]
        )
        self.assertEqual(
            plan.journal_bytes, journal.semantic_json_bytes(record)
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "promoted"
        ):
            journal.plan_effect_claim(
                record,
                "effect-a",
                "claim-too-early",
                index=plan.reserved_index,
                expected_index=journal.cas_token(plan.reserved_index),
                manager_secret=MANAGER_SECRET,
            )

        status, recovered = journal.recover_pending_promotion(
            plan.reserved_index,
            "execution-vector",
            plan.journal_bytes,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(status, "PROMOTE")
        self.assertEqual(
            recovered["entries"][0]["record_sha256"],
            record["record_sha256"],
        )
        status, recovered = journal.recover_pending_promotion(
            plan.reserved_index, "execution-vector", None
        )
        self.assertEqual((status, recovered), ("BLOCKED_MISSING_RECORD", None))
        status, recovered = journal.recover_pending_promotion(
            plan.reserved_index,
            "execution-vector",
            plan.journal_bytes + b"\n",
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual((status, recovered), ("QUARANTINE_MISMATCH", None))
        status, recovered = journal.recover_pending_promotion(
            plan.reserved_index,
            "execution-vector",
            plan.journal_bytes,
        )
        self.assertEqual(
            (status, recovered), ("QUARANTINE_REAUTH_REQUIRED", None)
        )

    def test_cas_conflict_and_record_update(self) -> None:
        record = _sealed_journal()
        index, current = _initially_persisted(record)
        stale_index = journal.CASToken(
            int(index["revision"]) - 1, str(index["record_sha256"])
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "revision"
        ):
            journal.plan_effect_claim(
                current,
                "effect-a",
                "claim-a",
                index=index,
                expected_index=stale_index,
                manager_secret=MANAGER_SECRET,
            )

        claimed = journal.plan_effect_claim(
            current,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        plan = journal.plan_journal_update(
            index,
            current,
            claimed,
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            plan.reserved_index["entries"][0]["record_sha256"],
            current["record_sha256"],
        )
        self.assertEqual(
            plan.reserved_index["entries"][0]["pending_record_sha256"],
            claimed["record_sha256"],
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "promoted"
        ):
            journal.assert_journal_promoted(
                plan.reserved_index,
                claimed,
                expected_index=journal.cas_token(plan.reserved_index),
                manager_secret=MANAGER_SECRET,
            )
        journal.assert_journal_promoted(
            plan.promoted_index,
            claimed,
            expected_index=journal.cas_token(plan.promoted_index),
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_journal_update(
                plan.promoted_index,
                current,
                claimed,
                expected_index=journal.cas_token(plan.promoted_index),
                expected_journal=journal.cas_token(current),
                manager_secret=MANAGER_SECRET,
            )
        tampered_index = copy.deepcopy(index)
        tampered_index["revision"] = int(tampered_index["revision"]) + 1
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "index digest"
        ):
            journal.normalize_index(tampered_index)
        other_index = journal.new_index("task-other")
        copied_digest = copy.deepcopy(other_index)
        copied_digest["record_sha256"] = index["record_sha256"]
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.normalize_index(copied_digest)

    def test_disjoint_overlap_and_exclusive_scope_conflicts(self) -> None:
        first = _sealed_journal()
        index, _ = _initially_persisted(first)
        disjoint = _sealed_journal(
            execution_id="execution-b",
            effects=[
                _effect(
                    "effect-b",
                    repository_id="repo-b",
                    path="/work/repo-b",
                )
            ],
        )
        plan = journal.plan_initial_write(
            index,
            disjoint,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = plan.promoted_index
        self.assertEqual(len(index["entries"]), 2)

        overlap = _sealed_journal(
            execution_id="execution-overlap",
            effects=[
                _effect(
                    "effect-overlap",
                    repository_id="repo-a",
                    path="/work/repo-a/subdir",
                )
            ],
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "conflicts"
        ):
            journal.plan_initial_write(
                index,
                overlap,
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
            )

        exclusive = _sealed_journal(
            execution_id="execution-exclusive",
            effects=[
                _effect(
                    "effect-exclusive",
                    repository_id="repo-c",
                    path="/work/repo-c",
                )
            ],
            concurrency_class="exclusive-task",
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_initial_write(
                index,
                exclusive,
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
            )

    def test_control_child_may_overlap_only_its_target(self) -> None:
        target = _sealed_journal()
        index, _ = _initially_persisted(target)
        control = _sealed_journal(
            execution_id="control-stop-a",
            effects=[
                _effect(
                    "control-effect",
                    repository_id="repo-a",
                    path="/work/repo-a/subdir",
                    kind="control",
                )
            ],
        )
        plan = journal.plan_initial_write(
            index,
            control,
            expected_index=journal.cas_token(index),
            entry_kind="control",
            target_execution_id="execution-vector",
            control_action_id="runtime.stop/v1",
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            plan.promoted_index["entries"][0]["execution_id"],
            "control-stop-a",
        )
        widened = _sealed_journal(
            execution_id="control-wide",
            effects=[
                _effect(
                    "wide-control",
                    repository_id="repo-b",
                    path="/work/repo-b",
                    kind="control",
                )
            ],
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_initial_write(
                index,
                widened,
                expected_index=journal.cas_token(index),
                entry_kind="control",
                target_execution_id="execution-vector",
                control_action_id="runtime.stop/v1",
                manager_secret=MANAGER_SECRET,
            )

    def test_required_lock_order_is_closed_and_deterministic(self) -> None:
        record = _sealed_journal()
        claims = journal.required_lock_claims(
            record, registry_ids=["registry-b", "registry-a"]
        )
        self.assertEqual(
            [claim["kind"] for claim in claims],
            ["task", "repository", "worktree", "lease", "registry", "registry"],
        )
        self.assertEqual(
            [claim["identity"] for claim in claims[-2:]],
            ["registry-a", "registry-b"],
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "order"
        ):
            journal.normalize_lock_claims(list(reversed(claims)))

    def test_portable_record_layout_is_exact(self) -> None:
        self.assertEqual(
            journal.ACTION_EXECUTION_INDEX_PATH,
            "action-executions/index.json",
        )
        self.assertEqual(
            journal.action_execution_active_path("execution-1"),
            "action-executions/active/execution-1.json",
        )
        self.assertEqual(
            journal.action_execution_archive_path("execution-1"),
            "action-executions/archive/execution-1.json",
        )
        self.assertEqual(
            journal.action_effect_containment_path(
                "execution-1", "effect-1"
            ),
            "action-executions/containment/execution-1/effect-1.json",
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.action_execution_active_path("../escape")


class EffectStateMachineTests(unittest.TestCase):
    def test_effect_and_containment_phases_are_monotonic(self) -> None:
        record = _sealed_journal()
        index, record = _initially_persisted(record)
        claimed = journal.plan_effect_claim(
            record,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, claimed = _persist_update(index, record, claimed)
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "monotonic"
        ):
            journal.advance_effect_phase(
                claimed,
                "effect-a",
                "QUIESCED",
                manager_secret=MANAGER_SECRET,
            )
        containment = journal.new_containment(
            claimed,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "monotonic"
        ):
            journal.advance_containment(containment, "CLOSED")

    def test_claim_is_one_shot_and_idempotency_never_allows_redispatch(self) -> None:
        record = _sealed_journal()
        index, record = _initially_persisted(record)
        claim = journal.plan_effect_claim(
            record,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index, durable_claim = _persist_update(index, record, claim.journal)
        self.assertTrue(claim.first_claim)
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "second first-claim"
        ):
            journal.plan_effect_claim(
                durable_claim,
                "effect-a",
                "claim-b",
                index=index,
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
            )
        lost_handle = journal.recovery_disposition(
            durable_claim,
            "effect-a",
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            lost_handle.action,
            "QUARANTINE_NO_AUTHENTIC_HANDLE_OR_RECEIPT",
        )
        self.assertFalse(lost_handle.dispatcher_reinvocation_allowed)
        self.assertTrue(lost_handle.preserves_receipt)
        reauth_required = journal.recovery_disposition(
            durable_claim, "effect-a"
        )
        self.assertEqual(
            reauth_required.action, "QUARANTINE_REAUTH_REQUIRED"
        )
        self.assertFalse(
            reauth_required.dispatcher_reinvocation_allowed
        )

        unclaimed = journal.recovery_disposition(
            record, "effect-a", manager_secret=MANAGER_SECRET
        )
        self.assertEqual(unclaimed.action, "CLAIM_UNSTARTED")
        self.assertTrue(unclaimed.requires_new_durable_claim)
        self.assertFalse(unclaimed.dispatcher_reinvocation_allowed)

    def test_parallel_group_and_dependency_claims(self) -> None:
        effects = [
            _effect(
                "effect-a",
                repository_id="repo-a",
                path="/work/repo-a",
                parallel_group="group-1",
            ),
            _effect(
                "effect-b",
                repository_id="repo-b",
                path="/work/repo-b",
                parallel_group="group-1",
            ),
            _effect(
                "effect-c",
                repository_id="repo-c",
                path="/work/repo-c",
                predecessors=["effect-a"],
            ),
        ]
        record = _sealed_journal(effects=effects)
        index, record = _initially_persisted(record)
        first = journal.plan_effect_claim(
            record,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, first = _persist_update(index, record, first)
        second = journal.plan_effect_claim(
            first,
            "effect-b",
            "claim-b",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, second = _persist_update(index, first, second)
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "predecessor"
        ):
            journal.plan_effect_claim(
                second,
                "effect-c",
                "claim-c",
                index=index,
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
            )
        for effect_id in ("effect-a", "effect-b"):
            disposition = journal.recovery_disposition(
                second, effect_id, manager_secret=MANAGER_SECRET
            )
            self.assertFalse(disposition.dispatcher_reinvocation_allowed)
        unclaimed = journal.recovery_disposition(
            second, "effect-c", manager_secret=MANAGER_SECRET
        )
        self.assertTrue(unclaimed.requires_new_durable_claim)
        self.assertFalse(unclaimed.dispatcher_reinvocation_allowed)

        overlapping = _sealed_journal(
            effects=[
                _effect(
                    "effect-a",
                    repository_id="repo-a",
                    path="/work/repo-a",
                    parallel_group="group-1",
                ),
                _effect(
                    "effect-b",
                    repository_id="repo-a",
                    path="/work/repo-a/child",
                    parallel_group="group-1",
                ),
            ]
        )
        overlap_index, overlapping = _initially_persisted(overlapping)
        claimed = journal.plan_effect_claim(
            overlapping,
            "effect-a",
            "claim-a",
            index=overlap_index,
            expected_index=journal.cas_token(overlap_index),
            manager_secret=MANAGER_SECRET,
        ).journal
        overlap_index, claimed = _persist_update(
            overlap_index, overlapping, claimed
        )
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "parallel"
        ):
            journal.plan_effect_claim(
                claimed,
                "effect-b",
                "claim-b",
                index=overlap_index,
                expected_index=journal.cas_token(overlap_index),
                manager_secret=MANAGER_SECRET,
            )

    def test_dependent_effect_waits_for_verified_predecessor(self) -> None:
        record = _sealed_journal(
            effects=[
                _effect("effect-a"),
                _effect(
                    "effect-b",
                    repository_id="repo-b",
                    path="/work/repo-b",
                    predecessors=["effect-a"],
                ),
            ]
        )
        index, current = _initially_persisted(record)
        claimed = journal.plan_effect_claim(
            record,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, current = _persist_update(index, current, claimed)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(containment["record_sha256"]),
        )
        index, current = _persist_update(index, current, running)
        quiesced = journal.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=_sha("quiesced"),
        )
        settled = journal.advance_effect_phase(
            current,
            "effect-a",
            "QUIESCED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(quiesced["record_sha256"]),
        )
        index, current = _persist_update(index, current, settled)
        closed = journal.advance_containment(quiesced, "CLOSED")
        verified = journal.advance_effect_phase(
            current,
            "effect-a",
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(closed["record_sha256"]),
            receipt_sha256=_sha("effect-a-receipt"),
        )
        index, current = _persist_update(index, current, verified)
        dependent = journal.plan_effect_claim(
            current,
            "effect-b",
            "claim-b",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            dependent.journal["effects"][1]["phase"], "CLAIMED"
        )

    def test_runtime_reattach_is_observe_only(self) -> None:
        record = _sealed_journal(
            effects=[
                _effect(
                    kind="runtime-dispatch",
                    settlement="asynchronous-handoff",
                )
            ]
        )
        index, current = _initially_persisted(record)
        claimed = journal.plan_effect_claim(
            record,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, current = _persist_update(index, current, claimed)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        bound = journal.advance_containment(
            containment,
            "RUNTIME_BOUND",
            runtime_handle_sha256=_sha("runtime-handle"),
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(bound["record_sha256"]),
            runtime_binding_sha256=_sha("runtime-binding"),
        )
        index, current = _persist_update(index, current, running)
        disposition = journal.recovery_disposition(
            current,
            "effect-a",
            authenticated_live_runtime=True,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(disposition.action, "REATTACH_OBSERVE_ONLY")
        self.assertFalse(disposition.dispatcher_reinvocation_allowed)
        receipt = journal.recovery_disposition(
            current,
            "effect-a",
            complete_stored_receipt=True,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(receipt.action, "OBSERVE_STORED_RECEIPT")
        self.assertFalse(receipt.dispatcher_reinvocation_allowed)

    def test_executor_recovery_matrix_is_claim_monotonic(
        self,
    ) -> None:
        executor_ids = (
            "executor.codex-thread/v1",
            "executor.native-subagents/v1",
            "executor.codex-exec/v1",
        )
        for executor_id in executor_ids:
            with self.subTest(executor_id=executor_id):
                effect = _effect(
                    "effect-runtime",
                    kind="runtime-dispatch",
                    settlement="asynchronous-handoff",
                )
                effect["safe_inputs"] = {
                    "executor_id": executor_id,
                    "operation": "launch",
                }
                effect["safe_input_sha256"] = (
                    journal.semantic_sha256(
                        journal.SAFE_INPUT_DOMAIN,
                        effect["safe_inputs"],
                    )
                )
                prepared = _sealed_journal(
                    execution_id=(
                        "execution-"
                        + executor_id.split(".")[1].split("/")[0]
                    ),
                    effects=[effect],
                )
                unstarted = journal.recovery_disposition(
                    prepared,
                    "effect-runtime",
                    manager_secret=MANAGER_SECRET,
                )
                self.assertEqual(
                    unstarted.action, "CLAIM_UNSTARTED"
                )
                self.assertTrue(
                    unstarted.requires_new_durable_claim
                )
                self.assertFalse(
                    unstarted.dispatcher_reinvocation_allowed
                )
                index, persisted = _initially_persisted(prepared)
                claimed = journal.plan_effect_claim(
                    persisted,
                    "effect-runtime",
                    "claim-runtime",
                    index=index,
                    expected_index=journal.cas_token(index),
                    manager_secret=MANAGER_SECRET,
                ).journal
                lost_before_binding = journal.recovery_disposition(
                    claimed,
                    "effect-runtime",
                    manager_secret=MANAGER_SECRET,
                )
                self.assertEqual(
                    lost_before_binding.action,
                    "QUARANTINE_NO_AUTHENTIC_HANDLE_OR_RECEIPT",
                )
                self.assertFalse(
                    lost_before_binding
                    .dispatcher_reinvocation_allowed
                )
                running = journal.advance_effect_phase(
                    claimed,
                    "effect-runtime",
                    "RUNNING",
                    manager_secret=MANAGER_SECRET,
                    containment_record_sha256=_sha(
                        "runtime-containment"
                    ),
                    runtime_binding_sha256=_sha(
                        "runtime-binding"
                    ),
                )
                live = journal.recovery_disposition(
                    running,
                    "effect-runtime",
                    authenticated_live_runtime=True,
                    manager_secret=MANAGER_SECRET,
                )
                self.assertEqual(
                    live.action, "REATTACH_OBSERVE_ONLY"
                )
                self.assertFalse(
                    live.dispatcher_reinvocation_allowed
                )
                stored_receipt = journal.recovery_disposition(
                    running,
                    "effect-runtime",
                    complete_stored_receipt=True,
                    manager_secret=MANAGER_SECRET,
                )
                self.assertEqual(
                    stored_receipt.action,
                    "OBSERVE_STORED_RECEIPT",
                )
                self.assertFalse(
                    stored_receipt.dispatcher_reinvocation_allowed
                )

    def test_exact_revision_and_disjoint_revalidation_fail_closed(self) -> None:
        exact = _sealed_journal()
        self.assertEqual(
            journal.revision_revalidation_disposition(
                exact, 7, manager_secret=MANAGER_SECRET
            ),
            "CURRENT_REVISION",
        )
        self.assertEqual(
            journal.revision_revalidation_disposition(
                exact, 8, manager_secret=MANAGER_SECRET
            ),
            "QUARANTINE_EXACT_REVISION_DRIFT",
        )

        core = _journal_core()
        core["bindings"]["revision_policy"] = "disjoint-scope-revalidate"
        scoped = journal.seal_journal(
            core, manager_secret=MANAGER_SECRET
        )
        fields = {
            field: scoped["bindings"][field]
            for field in (
                "workflow_bundle_sha256",
                "effect_plan_sha256",
                "semantic_operation_sha256",
                "scopes",
                "guard_projection_sha256",
                "evidence_sha256",
                "approval_sha256",
                "ownership_sha256",
                "registry_state_sha256",
                "postcondition_contract_sha256",
            )
        }
        self.assertEqual(
            journal.revision_revalidation_disposition(
                scoped,
                8,
                current_facts=fields,
                manager_secret=MANAGER_SECRET,
            ),
            "REEVALUATE_CURRENT_STATE",
        )
        drifted = copy.deepcopy(fields)
        drifted["approval_sha256"] = _sha("changed-approval")
        self.assertEqual(
            journal.revision_revalidation_disposition(
                scoped,
                8,
                current_facts=drifted,
                manager_secret=MANAGER_SECRET,
            ),
            "QUARANTINE_BOUND_FACT_DRIFT",
        )
        semantic_drifted = copy.deepcopy(fields)
        semantic_drifted["semantic_operation_sha256"] = _sha(
            "changed-semantic-operation"
        )
        self.assertEqual(
            journal.revision_revalidation_disposition(
                scoped,
                8,
                current_facts=semantic_drifted,
                manager_secret=MANAGER_SECRET,
            ),
            "QUARANTINE_BOUND_FACT_DRIFT",
        )


class TerminalAndReconciliationTests(unittest.TestCase):
    def test_synchronous_archive_precedes_index_removal(self) -> None:
        index, committed, containment = _complete_synchronous_execution()
        archive = journal.plan_archive(
            committed, manager_secret=MANAGER_SECRET
        )
        before = copy.deepcopy(index)
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_index_closure(
                index,
                committed,
                archive.archive_bytes + b"\n",
                expected_index=journal.cas_token(index),
                authoritative_event_sha256=_sha("authoritative-event"),
                containment_records=[containment],
                manager_secret=MANAGER_SECRET,
            )
        self.assertEqual(index, before)
        unrelated = _sealed_journal(
            execution_id="execution-unrelated",
            effects=[
                _effect(
                    "effect-unrelated",
                    repository_id="repo-b",
                    path="/work/repo-b",
                )
            ],
        )
        unrelated_plan = journal.plan_initial_write(
            index,
            unrelated,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(len(unrelated_plan.promoted_index["entries"]), 2)
        closure = journal.plan_index_closure(
            index,
            committed,
            archive.archive_bytes,
            expected_index=journal.cas_token(index),
            authoritative_event_sha256=_sha("authoritative-event"),
            containment_records=[containment],
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.mode, "REMOVE")
        self.assertEqual(closure.index["entries"], [])
        self.assertTrue(
            journal.orphan_active_matches_archive(
                archive.archive_bytes, archive.archive_bytes
            )
        )
        self.assertFalse(
            journal.orphan_active_matches_archive(
                archive.archive_bytes, archive.archive_bytes + b"\n"
            )
        )

    def test_async_handoff_promotes_and_releases_runtime_reservation(self) -> None:
        current = _sealed_journal(
            effects=[
                _effect(
                    kind="runtime-dispatch",
                    settlement="asynchronous-handoff",
                )
            ]
        )
        index, current = _initially_persisted(current)
        claimed = journal.plan_effect_claim(
            current,
            "effect-a",
            "claim-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        index, current = _persist_update(index, current, claimed)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        bound = journal.advance_containment(
            containment,
            "RUNTIME_BOUND",
            runtime_handle_sha256=_sha("runtime-handle"),
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(bound["record_sha256"]),
            runtime_binding_sha256=_sha("runtime-binding"),
        )
        index, current = _persist_update(index, current, running)
        released = journal.advance_containment(bound, "RELEASED")
        handoff = journal.advance_containment(
            released,
            "HANDOFF_VERIFIED",
            receipt_sha256=_sha("handoff-observation"),
        )
        handed_off = journal.advance_effect_phase(
            current,
            "effect-a",
            "HANDOFF_VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(handoff["record_sha256"]),
            runtime_binding_sha256=_sha("runtime-binding"),
        )
        index, current = _persist_update(index, current, handed_off)
        verified = journal.advance_effect_phase(
            current,
            "effect-a",
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(handoff["record_sha256"]),
            receipt_sha256=_sha("runtime-effect-receipt"),
        )
        index, current = _persist_update(index, current, verified)
        settled = journal.advance_global_settlement(
            current, manager_secret=MANAGER_SECRET
        )
        self.assertEqual(settled["phase"], "HANDOFF_VERIFIED")
        index, current = _persist_update(index, current, settled)
        receipt_verified = journal.verify_receipt_intent(
            current,
            {
                "receipt_sha256": _sha("action-receipt"),
                "candidate_state_sha256": _sha("candidate"),
                "event_batch_sha256": _sha("event-batch"),
                "engine_proof_sha256": _sha("proof"),
                "authorization_action_edge_id": "baseline.materialize/v3",
                "completion_edge_id": "baseline.materialize/v3",
            },
            manager_secret=MANAGER_SECRET,
        )
        index, current = _persist_update(index, current, receipt_verified)
        committed = journal.commit_journal(
            current,
            {
                "task_commit_revision": 8,
                "task_state_sha256": _sha("state"),
                "event_sha256": _sha("runtime-event"),
                "outbox_sha256": _sha("outbox"),
                "nonce_consumed": True,
            },
            manager_secret=MANAGER_SECRET,
        )
        index, current = _persist_update(index, current, committed)
        reservation = journal.seal_runtime_reservation(
            {
                "schema": journal.ACTION_RUNTIME_RESERVATION_SCHEMA,
                "task_id": "task-vector",
                "execution_id": "execution-vector",
                "effect_id": "effect-a",
                "lease_id": "lease-repo-a",
                "runtime_handle_sha256": _sha("runtime-handle"),
                "scopes": _scopes(),
                "containment_record_sha256": handoff["record_sha256"],
                "handoff_receipt_sha256": _sha("handoff-observation"),
                "stop_action_id": "runtime.stop/v1",
                "reconcile_action_id": "runtime.reconcile/v1",
                "phase": "ACTIVE",
                "result_event_sha256": None,
            }
        )
        archive = journal.plan_archive(
            committed, manager_secret=MANAGER_SECRET
        )
        closure = journal.plan_index_closure(
            index,
            committed,
            archive.archive_bytes,
            expected_index=journal.cas_token(index),
            authoritative_event_sha256=_sha("runtime-event"),
            containment_records=[handoff],
            runtime_reservation=reservation,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.mode, "PROMOTE_RUNTIME_RESERVATION")
        self.assertEqual(
            closure.index["entries"][0]["entry_kind"],
            "runtime-reservation",
        )

        overlap = _sealed_journal(
            execution_id="overlap-runtime",
            effects=[_effect("overlap-effect")],
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_initial_write(
                closure.index,
                overlap,
                expected_index=journal.cas_token(closure.index),
                manager_secret=MANAGER_SECRET,
            )
        release = journal.plan_runtime_reservation_release(
            closure.index,
            "execution-vector",
            expected_index=journal.cas_token(closure.index),
            authenticated_exit_or_quiescence_sha256=_sha("runtime-exit"),
            result_or_cancellation_event_sha256=_sha("result-event"),
        )
        self.assertEqual(release.index["entries"], [])

    def test_reconciliation_attempts_are_indexed_fresh_and_nonreplayable(
        self,
    ) -> None:
        index, quarantined, containment = _quarantined_execution()
        attempt = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-1",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="recovery.accept/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("fresh-authorization"),
            capability_sha256=_sha("fresh-capability"),
            gate_sha256=_sha("fresh-gate"),
            request_nonce_sha256=_sha("fresh-nonce"),
            engine_proof_sha256=_sha("fresh-proof"),
            principal="manager:recovery",
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            journal.reconciliation_eligibility(
                attempt,
                quarantined,
                current_task_revision=8,
                authorization_current=True,
                gate_current=True,
                nonce_unused=True,
                engine_proof_current=True,
                manager_secret=MANAGER_SECRET,
            ),
            "CURRENT",
        )
        self.assertEqual(
            journal.reconciliation_eligibility(
                attempt,
                quarantined,
                current_task_revision=8,
                authorization_current=False,
                gate_current=True,
                nonce_unused=True,
                engine_proof_current=True,
                manager_secret=MANAGER_SECRET,
            ),
            "AUTHORIZATION_EXPIRED_OR_REVOKED",
        )
        self.assertEqual(
            journal.reconciliation_eligibility(
                attempt,
                quarantined,
                current_task_revision=8,
                authorization_current=True,
                gate_current=True,
                nonce_unused=False,
                engine_proof_current=True,
                manager_secret=MANAGER_SECRET,
            ),
            "NONCE_REPLAY",
        )
        initial_plan = journal.plan_reconciliation_initial_write(
            index,
            attempt,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = initial_plan.promoted_index
        claimed = journal.advance_reconciliation_attempt(attempt, "CLAIMED")
        claim_plan = journal.plan_reconciliation_update(
            index,
            attempt,
            claimed,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(attempt),
        )
        index = claim_plan.promoted_index
        accepted = journal.advance_reconciliation_attempt(
            claimed,
            "ACCEPTED",
            evidence_sha256=_sha("postconditions"),
            recovery_event_sha256=_sha("recovery-event"),
            task_commit_revision=9,
            task_state_sha256=_sha("recovered-task-state"),
            outbox_sha256=_sha("recovery-outbox"),
            nonce_consumed=True,
        )
        terminal_plan = journal.plan_reconciliation_update(
            index,
            claimed,
            accepted,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
        )
        index = terminal_plan.promoted_index
        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "replayed"
        ):
            journal.advance_reconciliation_attempt(
                accepted,
                "UNRESOLVED",
                evidence_sha256=_sha("other"),
            )
        disposition = journal.recovery_disposition(
            quarantined,
            "effect-a",
            complete_stored_receipt=True,
            manager_secret=MANAGER_SECRET,
        )
        self.assertFalse(disposition.dispatcher_reinvocation_allowed)

        archive = journal.plan_archive(
            quarantined,
            reconciliation_attempt=accepted,
            manager_secret=MANAGER_SECRET,
        )
        closure = journal.plan_index_closure(
            index,
            quarantined,
            archive.archive_bytes,
            expected_index=journal.cas_token(index),
            authoritative_event_sha256=_sha("recovery-event"),
            containment_records=[containment],
            reconciliation_attempt=accepted,
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.index["entries"], [])

    def test_unresolved_and_failed_compensation_keep_scope_blocked(self) -> None:
        index, quarantined, containment = _quarantined_execution()
        attempt = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-unresolved",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="recovery.inspect/v1",
            authorization_kind="operator",
            authorization_sha256=_sha("operator-auth"),
            capability_sha256=None,
            gate_sha256=_sha("gate"),
            request_nonce_sha256=_sha("nonce"),
            engine_proof_sha256=_sha("proof"),
            principal="operator:test",
            manager_secret=MANAGER_SECRET,
        )
        initial = journal.plan_reconciliation_initial_write(
            index,
            attempt,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = initial.promoted_index
        claimed = journal.advance_reconciliation_attempt(attempt, "CLAIMED")
        update = journal.plan_reconciliation_update(
            index,
            attempt,
            claimed,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(attempt),
        )
        index = update.promoted_index
        unresolved = journal.advance_reconciliation_attempt(
            claimed,
            "UNRESOLVED",
            evidence_sha256=_sha("uncertain"),
        )
        update = journal.plan_reconciliation_update(
            index,
            claimed,
            unresolved,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
        )
        index = update.promoted_index
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_archive(
                quarantined,
                reconciliation_attempt=unresolved,
                manager_secret=MANAGER_SECRET,
            )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_index_closure(
                index,
                quarantined,
                journal.semantic_json_bytes(quarantined),
                expected_index=journal.cas_token(index),
                authoritative_event_sha256=_sha("recovery-event"),
                containment_records=[containment],
                reconciliation_attempt=unresolved,
                manager_secret=MANAGER_SECRET,
            )
        self.assertEqual(len(index["entries"]), 2)

        with self.assertRaisesRegex(
            journal.ActionExecutionJournalError, "first bind"
        ):
            journal.advance_reconciliation_attempt(
                claimed,
                "COMPENSATED",
                evidence_sha256=_sha("compensation"),
                recovery_event_sha256=_sha("event"),
            )

    def test_abandoned_and_compensated_terminal_contracts(self) -> None:
        index, quarantined, _ = _quarantined_execution()
        attempt = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-outcomes",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="recovery.decide/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("auth"),
            capability_sha256=_sha("capability"),
            gate_sha256=_sha("gate"),
            request_nonce_sha256=_sha("nonce"),
            engine_proof_sha256=_sha("proof"),
            principal="manager:test",
            manager_secret=MANAGER_SECRET,
        )
        claimed = journal.advance_reconciliation_attempt(attempt, "CLAIMED")
        abandoned = journal.advance_reconciliation_attempt(
            claimed,
            "ABANDONED",
            evidence_sha256=_sha("no-outcome-and-quiescent"),
            recovery_event_sha256=_sha("abandoned-event"),
            task_commit_revision=9,
            task_state_sha256=_sha("abandoned-task-state"),
            outbox_sha256=_sha("abandoned-outbox"),
            nonce_consumed=True,
        )
        self.assertEqual(abandoned["phase"], "ABANDONED")
        authorized = journal.authorize_reconciliation_compensation(
            claimed,
            compensation_execution_id="compensation-execution-1",
            compensation_plan=_compensation_plan(),
            dual_approval_sha256=_sha("dual-approval"),
            host_principal="host:approver",
            host_approval_sha256=_sha("host-approval"),
            workflow_principal="workflow:approver",
            workflow_approval_sha256=_sha("workflow-approval"),
        )
        compensation = journal.new_compensation_execution(
            authorized,
            quarantined,
            manager_secret=MANAGER_SECRET,
        )
        claimed_compensation = journal.advance_compensation_execution(
            compensation,
            "CLAIMED",
            claim_id="compensation-claim-1",
        )
        receipt = journal.seal_compensation_receipt(
            {
                "execution_id": "compensation-execution-1",
                "claim_id": "compensation-claim-1",
                "target_journal_record_sha256": quarantined[
                    "record_sha256"
                ],
                "authorization_record_sha256": authorized[
                    "record_sha256"
                ],
                "compensation_plan_sha256": (
                    journal.compensation_plan_sha256(
                        _compensation_plan()
                    )
                ),
                "effect_receipt_sha256": _sha(
                    "compensation-effect-receipt"
                ),
                "postcondition_proof_sha256": _sha(
                    "compensation-postcondition"
                ),
            }
        )
        verified_compensation = (
            journal.advance_compensation_execution(
                claimed_compensation,
                "RECEIPT_VERIFIED",
                receipt=receipt,
            )
        )
        committed_compensation = (
            journal.advance_compensation_execution(
                verified_compensation,
                "COMMITTED",
                recovery_event_sha256=_sha("compensated-event"),
                task_commit_revision=9,
                task_state_sha256=_sha(
                    "compensated-task-state"
                ),
                outbox_sha256=_sha("compensated-outbox"),
                nonce_consumed=True,
            )
        )
        compensated = journal.finalize_reconciliation_compensation(
            authorized, committed_compensation
        )
        self.assertEqual(
            compensated["outcome"]["compensation_execution_id"],
            "compensation-execution-1",
        )

    def test_unresolved_control_rotates_by_one_exact_index_cas(
        self,
    ) -> None:
        index, quarantined, _containment = _quarantined_execution()
        first = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-old",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("old-auth"),
            capability_sha256=_sha("old-capability"),
            gate_sha256=_sha("old-gate"),
            request_nonce_sha256=_sha("old-nonce"),
            engine_proof_sha256=_sha("old-proof"),
            principal="manager:old",
            manager_secret=MANAGER_SECRET,
        )
        initial = journal.plan_reconciliation_initial_write(
            index,
            first,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = initial.promoted_index
        claimed = journal.advance_reconciliation_attempt(
            first, "CLAIMED"
        )
        update = journal.plan_reconciliation_update(
            index,
            first,
            claimed,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(first),
        )
        index = update.promoted_index
        unresolved = journal.advance_reconciliation_attempt(
            claimed,
            "UNRESOLVED",
            evidence_sha256=_sha("unresolved"),
        )
        update = journal.plan_reconciliation_update(
            index,
            claimed,
            unresolved,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
        )
        index = update.promoted_index
        fresh = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-fresh",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("fresh-auth"),
            capability_sha256=_sha("fresh-capability"),
            gate_sha256=_sha("fresh-gate"),
            request_nonce_sha256=_sha("fresh-nonce"),
            engine_proof_sha256=_sha("fresh-proof"),
            principal="manager:fresh",
            manager_secret=MANAGER_SECRET,
        )
        rotation = journal.plan_reconciliation_control_rotation(
            index,
            unresolved,
            fresh,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            {
                entry["execution_id"]
                for entry in rotation.reserved_index["entries"]
            },
            {"execution-vector", "reconcile-fresh"},
        )
        fresh_entry = next(
            entry
            for entry in rotation.reserved_index["entries"]
            if entry["execution_id"] == "reconcile-fresh"
        )
        self.assertEqual(
            fresh_entry["pending_record_sha256"],
            fresh["record_sha256"],
        )
        self.assertEqual(
            {
                entry["execution_id"]
                for entry in rotation.promoted_index["entries"]
            },
            {"execution-vector", "reconcile-fresh"},
        )
        reused_authority = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-reused-authority",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("old-auth"),
            capability_sha256=_sha("reused-capability"),
            gate_sha256=_sha("fresh-reused-gate"),
            request_nonce_sha256=_sha("fresh-reused-nonce"),
            engine_proof_sha256=_sha("fresh-reused-proof"),
            principal="manager:fresh",
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_reconciliation_control_rotation(
                index,
                unresolved,
                reused_authority,
                target_journal=quarantined,
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
            )
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.plan_reconciliation_control_rotation(
                rotation.promoted_index,
                unresolved,
                fresh,
                target_journal=quarantined,
                expected_index=journal.cas_token(
                    rotation.promoted_index
                ),
                manager_secret=MANAGER_SECRET,
            )

    def test_compensation_rotation_receipt_and_closure_crosslink(
        self,
    ) -> None:
        index, quarantined, containment = _quarantined_execution()
        attempt = journal.new_reconciliation_attempt(
            quarantined,
            index,
            attempt_id="reconcile-compensation",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("compensation-auth"),
            capability_sha256=_sha("compensation-capability"),
            gate_sha256=_sha("compensation-gate"),
            request_nonce_sha256=_sha("compensation-nonce"),
            engine_proof_sha256=_sha("compensation-proof"),
            principal="manager:compensation",
            manager_secret=MANAGER_SECRET,
        )
        initial = journal.plan_reconciliation_initial_write(
            index,
            attempt,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = initial.promoted_index
        claimed = journal.advance_reconciliation_attempt(
            attempt, "CLAIMED"
        )
        update = journal.plan_reconciliation_update(
            index,
            attempt,
            claimed,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(attempt),
        )
        index = update.promoted_index
        authorized = journal.authorize_reconciliation_compensation(
            claimed,
            compensation_execution_id="compensation-control",
            compensation_plan=_compensation_plan(),
            dual_approval_sha256=_sha("dual-approval"),
            host_principal="host:approver",
            host_approval_sha256=_sha("host-approval"),
            workflow_principal="workflow:approver",
            workflow_approval_sha256=_sha("workflow-approval"),
        )
        update = journal.plan_reconciliation_update(
            index,
            claimed,
            authorized,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
        )
        index = update.promoted_index
        compensation = journal.new_compensation_execution(
            authorized,
            quarantined,
            manager_secret=MANAGER_SECRET,
        )
        rotation = journal.plan_compensation_control_rotation(
            index,
            authorized,
            compensation,
            target_journal=quarantined,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        index = rotation.promoted_index
        claimed_compensation = journal.advance_compensation_execution(
            compensation,
            "CLAIMED",
            claim_id="compensation-claim",
        )
        update = journal.plan_compensation_update(
            index,
            compensation,
            claimed_compensation,
            expected_index=journal.cas_token(index),
            expected_execution=journal.cas_token(compensation),
        )
        index = update.promoted_index
        receipt = journal.seal_compensation_receipt(
            {
                "execution_id": "compensation-control",
                "claim_id": "compensation-claim",
                "target_journal_record_sha256": quarantined[
                    "record_sha256"
                ],
                "authorization_record_sha256": authorized[
                    "record_sha256"
                ],
                "compensation_plan_sha256": (
                    journal.compensation_plan_sha256(
                        _compensation_plan()
                    )
                ),
                "effect_receipt_sha256": _sha(
                    "compensation-effect-receipt"
                ),
                "postcondition_proof_sha256": _sha(
                    "compensation-postcondition"
                ),
            }
        )
        verified = journal.advance_compensation_execution(
            claimed_compensation,
            "RECEIPT_VERIFIED",
            receipt=receipt,
        )
        update = journal.plan_compensation_update(
            index,
            claimed_compensation,
            verified,
            expected_index=journal.cas_token(index),
            expected_execution=journal.cas_token(
                claimed_compensation
            ),
        )
        index = update.promoted_index
        committed = journal.advance_compensation_execution(
            verified,
            "COMMITTED",
            recovery_event_sha256=_sha("compensation-event"),
            task_commit_revision=9,
            task_state_sha256=_sha("compensation-state"),
            outbox_sha256=_sha("compensation-outbox"),
            nonce_consumed=True,
        )
        update = journal.plan_compensation_update(
            index,
            verified,
            committed,
            expected_index=journal.cas_token(index),
            expected_execution=journal.cas_token(verified),
        )
        index = update.promoted_index
        terminal = journal.finalize_reconciliation_compensation(
            authorized, committed
        )
        closure = journal.plan_compensation_index_closure(
            index,
            quarantined,
            journal.semantic_json_bytes(quarantined),
            terminal,
            journal.semantic_json_bytes(terminal),
            committed,
            journal.semantic_json_bytes(committed),
            expected_index=journal.cas_token(index),
            containment_records=[containment],
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.index["entries"], [])
        forged = copy.deepcopy(receipt)
        forged["outbox_sha256"] = _sha("wrong-outbox")
        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.advance_compensation_execution(
                claimed_compensation,
                "RECEIPT_VERIFIED",
                receipt=forged,
            )


if __name__ == "__main__":
    unittest.main()
