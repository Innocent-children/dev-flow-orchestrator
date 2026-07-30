from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.dev_flow_parts import action_execution_journal as journal
from scripts.dev_flow_parts import action_execution_store as store
from tests.test_action_execution_journal import (
    MANAGER_SECRET,
    _compensation_plan,
    _effect,
    _scopes,
    _sealed_journal,
    _sha,
)


class _InjectedCrash(RuntimeError):
    pass


def _crash_at(target: str):
    def crash(stage: str) -> None:
        if stage == target:
            raise _InjectedCrash(stage)

    return crash


class ActionExecutionStoreCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary_base = Path(tempfile.gettempdir()).resolve()
        self.temporary = tempfile.TemporaryDirectory(
            dir=str(temporary_base)
        )
        self.task_dir = Path(self.temporary.name) / "task"
        self.task_dir.mkdir(mode=0o700)
        self.store = store.ActionExecutionStore(self.task_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def initialize(self) -> dict[str, object]:
        return self.store.initialize_index("task-vector").index

    def persist_initial(
        self,
        record: dict[str, object] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        index = self.initialize()
        current = record or _sealed_journal()
        result = self.store.persist_initial(
            current,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        assert result.record is not None
        return result.index, result.record

    def persist_update(
        self,
        index: dict[str, object],
        current: dict[str, object],
        updated: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        result = self.store.persist_update(
            updated,
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        assert result.record is not None
        return result.index, result.record

    def claim(
        self,
        index: dict[str, object],
        current: dict[str, object],
        *,
        claim_id: str = "claim-store",
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        store.ActionDispatchPlan,
    ]:
        permit = self.store.claim_for_dispatch(
            str(current["execution_id"]),
            "effect-a",
            claim_id,
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        promoted_index = self.store.read_index(
            expected_task_id=str(current["task_id"])
        )
        promoted_journal = self.store.read_active_journal(
            str(current["execution_id"]),
            manager_secret=MANAGER_SECRET,
        )
        return promoted_index, promoted_journal, permit

    def persist_containment(
        self,
        index: dict[str, object],
        current: dict[str, object],
        containment: dict[str, object],
        *,
        before: dict[str, object] | None = None,
    ) -> dict[str, object]:
        result = self.store.persist_containment(
            containment,
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            expected_containment=(
                None if before is None else journal.cas_token(before)
            ),
            manager_secret=MANAGER_SECRET,
        )
        assert result.record is not None
        return result.record

    def complete_synchronous(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        index, current = self.persist_initial()
        index, current, _ = self.claim(index, current)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                containment["record_sha256"]
            ),
        )
        index, current = self.persist_update(index, current, running)
        quiesced_containment = journal.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=_sha("quiescence"),
        )
        quiesced_containment = self.persist_containment(
            index,
            current,
            quiesced_containment,
            before=containment,
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
        index, current = self.persist_update(
            index, current, quiesced
        )
        closed_containment = journal.advance_containment(
            quiesced_containment, "CLOSED"
        )
        closed_containment = self.persist_containment(
            index,
            current,
            closed_containment,
            before=quiesced_containment,
        )
        verified = journal.advance_effect_phase(
            current,
            "effect-a",
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                closed_containment["record_sha256"]
            ),
            receipt_sha256=_sha("effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, verified
        )
        settled = journal.advance_global_settlement(
            current, manager_secret=MANAGER_SECRET
        )
        index, current = self.persist_update(
            index, current, settled
        )
        receipt_verified = journal.verify_receipt_intent(
            current,
            {
                "receipt_sha256": _sha("action-receipt"),
                "candidate_state_sha256": _sha("candidate"),
                "event_batch_sha256": _sha("event-batch"),
                "engine_proof_sha256": _sha("engine-proof"),
                "authorization_action_edge_id": "baseline.materialize/v3",
                "completion_edge_id": "baseline.materialize/v3",
            },
            manager_secret=MANAGER_SECRET,
        )
        index, current = self.persist_update(
            index, current, receipt_verified
        )
        committed = journal.commit_journal(
            current,
            {
                "task_commit_revision": 8,
                "task_state_sha256": _sha("task-state"),
                "event_sha256": _sha("task-event"),
                "outbox_sha256": _sha("outbox"),
                "nonce_consumed": True,
            },
            manager_secret=MANAGER_SECRET,
        )
        index, current = self.persist_update(
            index, current, committed
        )
        return index, current, closed_containment

    def quarantine_for_reconciliation(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        index, current = self.persist_initial()
        index, current, _permit = self.claim(index, current)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                containment["record_sha256"]
            ),
        )
        index, current = self.persist_update(
            index, current, running
        )
        quiesced_containment = journal.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=_sha("quiescence"),
        )
        quiesced_containment = self.persist_containment(
            index,
            current,
            quiesced_containment,
            before=containment,
        )
        quiesced = journal.advance_effect_phase(
            current,
            "effect-a",
            "QUIESCED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(
                quiesced_containment["record_sha256"]
            ),
            receipt_sha256=_sha("effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, quiesced
        )
        closed = journal.advance_containment(
            quiesced_containment, "CLOSED"
        )
        closed = self.persist_containment(
            index,
            current,
            closed,
            before=quiesced_containment,
        )
        verified = journal.advance_effect_phase(
            current,
            "effect-a",
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(closed["record_sha256"]),
            receipt_sha256=_sha("effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, verified
        )
        settled = journal.advance_global_settlement(
            current, manager_secret=MANAGER_SECRET
        )
        index, current = self.persist_update(
            index, current, settled
        )
        quarantined = journal.quarantine_journal(
            current,
            reason_code="store-compensation-test",
            details_sha256=_sha("quarantine-details"),
            effect_id="effect-a",
            receipt_sha256=_sha("effect-receipt"),
            manager_secret=MANAGER_SECRET,
        )
        index, current = self.persist_update(
            index, current, quarantined
        )
        return index, current, closed

    def complete_asynchronous(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        record = _sealed_journal(
            effects=[
                _effect(
                    kind="runtime-dispatch",
                    settlement="asynchronous-handoff",
                )
            ]
        )
        index, current = self.persist_initial(record)
        index, current, _ = self.claim(index, current)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        bound = journal.advance_containment(
            containment,
            "RUNTIME_BOUND",
            runtime_handle_sha256=_sha("runtime-handle"),
        )
        bound = self.persist_containment(
            index, current, bound, before=containment
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(bound["record_sha256"]),
            runtime_binding_sha256=_sha("runtime-binding"),
        )
        index, current = self.persist_update(index, current, running)
        released = journal.advance_containment(bound, "RELEASED")
        released = self.persist_containment(
            index, current, released, before=bound
        )
        handoff = journal.advance_containment(
            released,
            "HANDOFF_VERIFIED",
            receipt_sha256=_sha("handoff-observation"),
        )
        handoff = self.persist_containment(
            index, current, handoff, before=released
        )
        handed_off = journal.advance_effect_phase(
            current,
            "effect-a",
            "HANDOFF_VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(handoff["record_sha256"]),
            runtime_binding_sha256=_sha("runtime-binding"),
        )
        index, current = self.persist_update(
            index, current, handed_off
        )
        verified = journal.advance_effect_phase(
            current,
            "effect-a",
            "VERIFIED",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(handoff["record_sha256"]),
            receipt_sha256=_sha("runtime-effect-receipt"),
        )
        index, current = self.persist_update(
            index, current, verified
        )
        settled = journal.advance_global_settlement(
            current, manager_secret=MANAGER_SECRET
        )
        index, current = self.persist_update(
            index, current, settled
        )
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
        index, current = self.persist_update(
            index, current, receipt_verified
        )
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
        index, current = self.persist_update(
            index, current, committed
        )
        reservation = journal.seal_runtime_reservation(
            {
                "schema": journal.ACTION_RUNTIME_RESERVATION_SCHEMA,
                "task_id": "task-vector",
                "execution_id": "execution-vector",
                "effect_id": "effect-a",
                "lease_id": "lease-repo-a",
                "runtime_handle_sha256": _sha("runtime-handle"),
                "scopes": _scopes(),
                "containment_record_sha256": handoff[
                    "record_sha256"
                ],
                "handoff_receipt_sha256": _sha(
                    "handoff-observation"
                ),
                "stop_action_id": "runtime.stop/v1",
                "reconcile_action_id": "runtime.reconcile/v1",
                "phase": "ACTIVE",
                "result_event_sha256": None,
            }
        )
        persisted = self.store.persist_runtime_reservation(
            reservation,
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        return index, current, handoff, persisted.record


class AtomicLayoutAndSafetyTests(ActionExecutionStoreCase):
    def test_layout_lock_declaration_and_initial_round_trip(self) -> None:
        index, current = self.persist_initial()
        self.assertEqual(
            (
                ("task", "task-vector"),
                ("repository", "repo-a"),
                ("worktree", "worktree-repo-a"),
                ("lease", "lease-repo-a"),
            ),
            store.action_execution_required_lock_claims(current),
        )
        self.assertTrue(
            (
                self.task_dir
                / journal.action_execution_active_path(
                    "execution-vector"
                )
            ).is_file()
        )
        self.assertEqual(
            "action-executions/runtime-reservations/"
            "execution-vector.json",
            store.action_execution_runtime_reservation_path(
                "execution-vector"
            ),
        )
        journal.assert_journal_promoted(
            index,
            current,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        context = self.store.read_promoted_context(
            "execution-vector",
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(context.index, index)
        self.assertEqual(context.record, current)
        raw = (
            self.task_dir
            / journal.action_execution_active_path(
                "execution-vector"
            )
        ).read_bytes()
        self.assertEqual(raw, journal.semantic_json_bytes(current))

    def test_rejects_relative_symlink_special_and_escape_paths(self) -> None:
        with self.assertRaisesRegex(
            store.ActionExecutionStoreError, "absolute"
        ):
            store.ActionExecutionStore("relative/task")
        with self.assertRaises(store.ActionExecutionStoreError):
            store.ActionExecutionStore(
                str(self.task_dir / ".." / "task")
            )

        real_task = self.task_dir.parent / "real-task"
        real_task.mkdir()
        linked_task = self.task_dir.parent / "linked-task"
        try:
            linked_task.symlink_to(real_task, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable")
        with self.assertRaisesRegex(
            store.ActionExecutionStoreError, "symbolic"
        ):
            store.ActionExecutionStore(linked_task).initialize_index(
                "task-vector"
            )

        outside = self.task_dir.parent / "outside.json"
        outside.write_bytes(b"outside")
        action_root = self.task_dir / "action-executions"
        action_root.mkdir()
        (action_root / "index.json").symlink_to(outside)
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.initialize_index("task-vector")
        self.assertEqual(outside.read_bytes(), b"outside")

        with self.assertRaises(journal.ActionExecutionJournalError):
            journal.action_execution_active_path("../escape")

    @unittest.skipIf(
        not hasattr(os, "mkfifo"),
        "special FIFO creation is unavailable",
    )
    def test_rejects_special_index_and_nested_directory_symlink(self) -> None:
        action_root = self.task_dir / "action-executions"
        action_root.mkdir()
        os.mkfifo(action_root / "index.json")
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.read_index()
        (action_root / "index.json").unlink()
        self.store.initialize_index("task-vector")

        outside = self.task_dir.parent / "outside-active"
        outside.mkdir()
        active = action_root / "active"
        active.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.persist_initial(
                _sealed_journal(),
                expected_index=journal.cas_token(
                    self.store.read_index()
                ),
                manager_secret=MANAGER_SECRET,
            )
        self.assertEqual(list(outside.iterdir()), [])

    def test_file_to_symlink_race_never_writes_external_target(self) -> None:
        index, current = self.persist_initial()
        claimed = journal.plan_effect_claim(
            current,
            "effect-a",
            "race-claim",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        outside = self.task_dir.parent / "race-outside"
        outside.write_bytes(b"outside")
        active_path = (
            self.task_dir
            / journal.action_execution_active_path(
                "execution-vector"
            )
        )
        original_read = store._ActionStoreRoot._read_from_parent
        calls = {"active": 0}

        def racing_read(
            root,
            parent_descriptor,
            parent_path,
            filename,
            *,
            missing_ok,
        ):
            result = original_read(
                root,
                parent_descriptor,
                parent_path,
                filename,
                missing_ok=missing_ok,
            )
            if (
                filename == "execution-vector.json"
                and result is not None
            ):
                calls["active"] += 1
                if calls["active"] == 2:
                    active_path.unlink()
                    active_path.symlink_to(outside)
            return result

        with mock.patch.object(
            store._ActionStoreRoot,
            "_read_from_parent",
            racing_read,
        ):
            with self.assertRaises(store.ActionExecutionStoreError):
                self.store.persist_update(
                    claimed,
                    expected_index=journal.cas_token(index),
                    expected_journal=journal.cas_token(current),
                    manager_secret=MANAGER_SECRET,
                )
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_directory_swap_race_is_detected_by_open_descriptor(
        self,
    ) -> None:
        index, current = self.persist_initial()
        claimed = journal.plan_effect_claim(
            current,
            "effect-a",
            "directory-race-claim",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        ).journal
        action_root = self.task_dir / "action-executions"
        active = action_root / "active"
        displaced = action_root / "active-displaced"
        outside = self.task_dir.parent / "outside-directory"
        outside.mkdir()
        original_read = store._ActionStoreRoot._read_from_parent
        swapped = {"done": False}

        def racing_read(
            root,
            parent_descriptor,
            parent_path,
            filename,
            *,
            missing_ok,
        ):
            result = original_read(
                root,
                parent_descriptor,
                parent_path,
                filename,
                missing_ok=missing_ok,
            )
            if (
                filename == "execution-vector.json"
                and not swapped["done"]
            ):
                swapped["done"] = True
                active.rename(displaced)
                active.symlink_to(outside, target_is_directory=True)
            return result

        with mock.patch.object(
            store._ActionStoreRoot,
            "_read_from_parent",
            racing_read,
        ):
            with self.assertRaises(store.ActionExecutionStoreError):
                self.store.persist_update(
                    claimed,
                    expected_index=journal.cas_token(index),
                    expected_journal=journal.cas_token(current),
                    manager_secret=MANAGER_SECRET,
                )
        self.assertEqual(list(outside.iterdir()), [])


class WriteAheadCrashAndClaimTests(ActionExecutionStoreCase):
    def test_every_index_initialization_crash_point_is_recoverable(self) -> None:
        stages = [
            stage
            for stage in store.ACTION_EXECUTION_STORE_FAILURE_POINTS
            if stage.startswith("initialize-index:")
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory(
                    dir=str(Path(tempfile.gettempdir()).resolve())
                ) as raw:
                    task_dir = Path(raw) / "task"
                    task_dir.mkdir()
                    adapter = store.ActionExecutionStore(task_dir)
                    with self.assertRaises(_InjectedCrash):
                        adapter.initialize_index(
                            "task-vector",
                            failure_hook=_crash_at(stage),
                        )
                    index_path = (
                        task_dir / journal.ACTION_EXECUTION_INDEX_PATH
                    )
                    if stage in {
                        "initialize-index:before",
                        "initialize-index:after-temp-fsync",
                    }:
                        self.assertFalse(index_path.exists())
                        initialized = adapter.initialize_index(
                            "task-vector"
                        )
                        self.assertEqual(
                            initialized.status, "initialized"
                        )
                    else:
                        self.assertEqual(
                            adapter.read_index()["task_id"],
                            "task-vector",
                        )

    def test_every_initial_wal_crash_point_blocks_or_recovers_exactly(
        self,
    ) -> None:
        stages = [
            stage
            for stage in store.ACTION_EXECUTION_STORE_FAILURE_POINTS
            if stage.startswith("wal-")
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory(
                    dir=str(Path(tempfile.gettempdir()).resolve())
                ) as raw:
                    task_dir = Path(raw) / "task"
                    task_dir.mkdir()
                    adapter = store.ActionExecutionStore(task_dir)
                    index = adapter.initialize_index(
                        "task-vector"
                    ).index
                    with self.assertRaises(_InjectedCrash):
                        adapter.persist_initial(
                            _sealed_journal(),
                            expected_index=journal.cas_token(index),
                            manager_secret=MANAGER_SECRET,
                            failure_hook=_crash_at(stage),
                        )
                    current_index = adapter.read_index()
                    entries = current_index["entries"]
                    assert isinstance(entries, list)
                    active = (
                        task_dir
                        / journal.action_execution_active_path(
                            "execution-vector"
                        )
                    )
                    if not entries:
                        self.assertFalse(active.exists())
                        result = adapter.persist_initial(
                            _sealed_journal(),
                            expected_index=journal.cas_token(
                                current_index
                            ),
                            manager_secret=MANAGER_SECRET,
                        )
                        self.assertEqual(result.status, "promoted")
                        continue
                    entry = entries[0]
                    if entry["pending_record_sha256"] is not None:
                        recovered = adapter.recover_pending(
                            "execution-vector",
                            manager_secret=MANAGER_SECRET,
                        )
                        if active.exists():
                            self.assertEqual(
                                recovered.status, "PROMOTED"
                            )
                        else:
                            self.assertEqual(
                                recovered.status,
                                "BLOCKED_MISSING_RECORD",
                            )
                    else:
                        self.assertTrue(active.exists())
                        stored = adapter.read_active_journal(
                            "execution-vector",
                            manager_secret=MANAGER_SECRET,
                        )
                        journal.assert_journal_promoted(
                            current_index,
                            stored,
                            expected_index=journal.cas_token(
                                current_index
                            ),
                            manager_secret=MANAGER_SECRET,
                        )

    def test_update_crash_recovery_never_invents_missing_claim(
        self,
    ) -> None:
        stages = [
            stage
            for stage in store.ACTION_EXECUTION_STORE_FAILURE_POINTS
            if stage.startswith("wal-")
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory(
                    dir=str(Path(tempfile.gettempdir()).resolve())
                ) as raw:
                    task_dir = Path(raw) / "task"
                    task_dir.mkdir()
                    adapter = store.ActionExecutionStore(task_dir)
                    index = adapter.initialize_index(
                        "task-vector"
                    ).index
                    initial = adapter.persist_initial(
                        _sealed_journal(),
                        expected_index=journal.cas_token(index),
                        manager_secret=MANAGER_SECRET,
                    )
                    assert initial.record is not None
                    claimed = journal.plan_effect_claim(
                        initial.record,
                        "effect-a",
                        "claim-crash",
                        index=initial.index,
                        expected_index=journal.cas_token(
                            initial.index
                        ),
                        manager_secret=MANAGER_SECRET,
                    ).journal
                    with self.assertRaises(_InjectedCrash):
                        adapter.persist_update(
                            claimed,
                            expected_index=journal.cas_token(
                                initial.index
                            ),
                            expected_journal=journal.cas_token(
                                initial.record
                            ),
                            manager_secret=MANAGER_SECRET,
                            failure_hook=_crash_at(stage),
                        )
                    current_index = adapter.read_index()
                    entry = current_index["entries"][0]
                    if entry["pending_record_sha256"] is not None:
                        recovered = adapter.recover_pending(
                            "execution-vector",
                            manager_secret=MANAGER_SECRET,
                        )
                        expected_status = (
                            "PROMOTED"
                            if stage
                            in {
                                "wal-write-record:after-replace",
                                "wal-write-record:after-dir-fsync",
                                "wal-write-record:after-verify",
                                "wal-promote-index:before",
                                "wal-promote-index:after-temp-fsync",
                            }
                            else "QUARANTINE_MISMATCH"
                        )
                        self.assertEqual(
                            recovered.status, expected_status
                        )
                    else:
                        stored = adapter.read_active_journal(
                            "execution-vector",
                            manager_secret=MANAGER_SECRET,
                        )
                        if stage in {
                            "wal-reserve-index:before",
                            "wal-reserve-index:after-temp-fsync",
                        }:
                            self.assertIsNone(
                                stored["effects"][0]["claim_id"]
                            )
                        else:
                            self.assertEqual(
                                stored["effects"][0]["claim_id"],
                                "claim-crash",
                            )

    def test_dispatch_gate_is_one_shot_even_after_lost_response(self) -> None:
        index, current = self.persist_initial()
        with self.assertRaises(_InjectedCrash):
            self.store.claim_for_dispatch(
                "execution-vector",
                "effect-a",
                "lost-claim",
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                manager_secret=MANAGER_SECRET,
                failure_hook=_crash_at(
                    "wal-promote-index:after-verify"
                ),
            )
        promoted_index = self.store.read_index()
        promoted = self.store.read_active_journal(
            "execution-vector", manager_secret=MANAGER_SECRET
        )
        self.assertEqual(
            promoted["effects"][0]["claim_id"], "lost-claim"
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            self.store.claim_for_dispatch(
                "execution-vector",
                "effect-a",
                "lost-claim",
                expected_index=journal.cas_token(promoted_index),
                expected_journal=journal.cas_token(promoted),
                manager_secret=MANAGER_SECRET,
            )

    def test_normal_dispatch_plan_returns_only_after_exact_promotion(
        self,
    ) -> None:
        index, current = self.persist_initial()
        index, claimed, permit = self.claim(index, current)
        self.assertEqual(permit.claim_id, "claim-store")
        self.assertEqual(
            permit.journal_record_sha256,
            claimed["record_sha256"],
        )
        self.assertEqual(
            permit.index_record_sha256, index["record_sha256"]
        )
        journal.assert_journal_promoted(
            index,
            claimed,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            self.store.claim_for_dispatch(
                "execution-vector",
                "effect-a",
                "second-claim",
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(claimed),
                manager_secret=MANAGER_SECRET,
            )

    def test_stale_concurrent_index_cas_cannot_overwrite_winner(self) -> None:
        index = self.initialize()
        stale = journal.cas_token(index)
        first = _sealed_journal(
            execution_id="execution-first",
            effects=[_effect("effect-first")],
        )
        second = _sealed_journal(
            execution_id="execution-second",
            effects=[
                _effect(
                    "effect-second",
                    repository_id="repo-b",
                    path="/work/repo-b",
                )
            ],
        )
        winner = self.store.persist_initial(
            first,
            expected_index=stale,
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            self.store.persist_initial(
                second,
                expected_index=stale,
                manager_secret=MANAGER_SECRET,
            )
        current = self.store.read_index()
        self.assertEqual(current, winner.index)
        retry = self.store.persist_initial(
            second,
            expected_index=journal.cas_token(current),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(len(retry.index["entries"]), 2)


class ContainmentReconciliationAndArchiveTests(
    ActionExecutionStoreCase
):
    def test_containment_rejects_wrong_crosslink_and_skipped_phase(self) -> None:
        index, current = self.persist_initial()
        index, current, _ = self.claim(index, current)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        wrong_core = {
            key: value
            for key, value in containment.items()
            if key != "record_sha256"
        }
        wrong_core["claim_id"] = "other-claim"
        wrong = journal.seal_containment(wrong_core)
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.persist_containment(
                wrong,
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                expected_containment=journal.cas_token(containment),
                manager_secret=MANAGER_SECRET,
            )
        skipped_core = {
            key: value
            for key, value in containment.items()
            if key != "record_sha256"
        }
        skipped_core.update(
            {
                "revision": 9,
                "phase": "QUIESCED",
                "receipt_sha256": _sha("skipped"),
            }
        )
        skipped = journal.seal_containment(skipped_core)
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.persist_containment(
                skipped,
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                expected_containment=journal.cas_token(containment),
                manager_secret=MANAGER_SECRET,
            )

    def test_reconciliation_wal_crash_recovers_exact_control_child(
        self,
    ) -> None:
        index, current = self.persist_initial()
        index, current, _ = self.claim(index, current)
        containment = journal.new_containment(
            current,
            "effect-a",
            index=index,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        containment = self.persist_containment(
            index, current, containment
        )
        quiesced = journal.advance_containment(
            containment,
            "QUIESCED",
            receipt_sha256=_sha("no-outcome"),
        )
        quiesced = self.persist_containment(
            index, current, quiesced, before=containment
        )
        closed = journal.advance_containment(quiesced, "CLOSED")
        closed = self.persist_containment(
            index, current, closed, before=quiesced
        )
        running = journal.advance_effect_phase(
            current,
            "effect-a",
            "RUNNING",
            manager_secret=MANAGER_SECRET,
            containment_record_sha256=str(closed["record_sha256"]),
        )
        index, current = self.persist_update(index, current, running)
        quarantined = journal.quarantine_journal(
            current,
            reason_code="test-quarantine",
            details_sha256=_sha("quarantine"),
            effect_id="effect-a",
            manager_secret=MANAGER_SECRET,
        )
        index, current = self.persist_update(
            index, current, quarantined
        )
        attempt = journal.new_reconciliation_attempt(
            current,
            index,
            attempt_id="reconcile-store",
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="recovery.accept/v1",
            authorization_kind="manager",
            authorization_sha256=_sha("fresh-auth"),
            capability_sha256=_sha("fresh-capability"),
            gate_sha256=_sha("fresh-gate"),
            request_nonce_sha256=_sha("fresh-nonce"),
            engine_proof_sha256=_sha("fresh-proof"),
            principal="manager:recovery",
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(_InjectedCrash):
            self.store.persist_reconciliation_initial(
                attempt,
                target_execution_id="execution-vector",
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
                failure_hook=_crash_at(
                    "wal-write-record:after-replace"
                ),
            )
        recovered = self.store.recover_pending("reconcile-store")
        self.assertEqual(recovered.status, "PROMOTED")
        self.assertEqual(
            recovered.record["attempt_id"], "reconcile-store"
        )
        self.assertEqual(
            self.store.read_reconciliation("reconcile-store"),
            recovered.record,
        )
        claimed = journal.advance_reconciliation_attempt(
            recovered.record, "CLAIMED"
        )
        updated = self.store.persist_reconciliation_update(
            claimed,
            expected_index=journal.cas_token(recovered.index),
            expected_attempt=journal.cas_token(recovered.record),
            target_manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(updated.record["phase"], "CLAIMED")

    def test_all_archive_and_closure_crash_points_preserve_truth(
        self,
    ) -> None:
        stages = [
            stage
            for stage in store.ACTION_EXECUTION_STORE_FAILURE_POINTS
            if stage.startswith(
                (
                    "terminal-archive:",
                    "terminal-index-closure:",
                    "terminal-active-cleanup:",
                )
            )
        ]
        for stage in stages:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory(
                    dir=str(Path(tempfile.gettempdir()).resolve())
                ) as raw:
                    task_dir = Path(raw) / "task"
                    task_dir.mkdir()
                    case_store = store.ActionExecutionStore(task_dir)
                    original_store = self.store
                    original_dir = self.task_dir
                    self.store = case_store
                    self.task_dir = task_dir
                    try:
                        index, current, _ = (
                            self.complete_synchronous()
                        )
                        with self.assertRaises(_InjectedCrash):
                            case_store.archive_and_close(
                                "execution-vector",
                                expected_index=journal.cas_token(index),
                                expected_journal=journal.cas_token(
                                    current
                                ),
                                authoritative_event_sha256=_sha(
                                    "task-event"
                                ),
                                manager_secret=MANAGER_SECRET,
                                failure_hook=_crash_at(stage),
                            )
                        archive_path = (
                            task_dir
                            / journal.action_execution_archive_path(
                                "execution-vector"
                            )
                        )
                        active_path = (
                            task_dir
                            / journal.action_execution_active_path(
                                "execution-vector"
                            )
                        )
                        after = case_store.read_index()
                        entries = after["entries"]
                        assert isinstance(entries, list)
                        closure_visible = stage in {
                            "terminal-index-closure:after-replace",
                            "terminal-index-closure:after-dir-fsync",
                            "terminal-index-closure:after-verify",
                            "terminal-active-cleanup:before",
                            "terminal-active-cleanup:after-unlink",
                            "terminal-active-cleanup:after-dir-fsync",
                        }
                        self.assertEqual(
                            bool(entries), not closure_visible
                        )
                        archive_visible = not stage.startswith(
                            "terminal-archive:"
                        ) or stage in {
                            "terminal-archive:after-replace",
                            "terminal-archive:after-dir-fsync",
                            "terminal-archive:after-verify",
                        }
                        self.assertEqual(
                            archive_path.exists(), archive_visible
                        )
                        if closure_visible and active_path.exists():
                            self.assertTrue(
                                case_store.cleanup_orphan_active(
                                    "execution-vector"
                                )
                            )
                        if archive_path.exists():
                            self.assertEqual(
                                archive_path.read_bytes(),
                                journal.semantic_json_bytes(current),
                            )
                    finally:
                        self.store = original_store
                        self.task_dir = original_dir

    def test_synchronous_terminal_archive_closes_and_is_readable(
        self,
    ) -> None:
        index, current, _ = self.complete_synchronous()
        closure = self.store.archive_and_close(
            "execution-vector",
            expected_index=journal.cas_token(index),
            expected_journal=journal.cas_token(current),
            authoritative_event_sha256=_sha("task-event"),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.mode, "REMOVE")
        self.assertEqual(closure.index["entries"], [])
        self.assertTrue(closure.active_removed)
        self.assertEqual(
            self.store.read_archive_journal(
                "execution-vector",
                manager_secret=MANAGER_SECRET,
            ),
            current,
        )

    def test_archive_failure_blocks_only_affected_scope(self) -> None:
        index, current, _ = self.complete_synchronous()
        with self.assertRaises(_InjectedCrash):
            self.store.archive_and_close(
                "execution-vector",
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                authoritative_event_sha256=_sha("task-event"),
                manager_secret=MANAGER_SECRET,
                failure_hook=_crash_at("terminal-archive:before"),
            )
        blocked_index = self.store.read_index()
        overlap = _sealed_journal(
            execution_id="overlap",
            effects=[_effect("overlap-effect")],
        )
        with self.assertRaises(journal.ActionExecutionJournalError):
            self.store.persist_initial(
                overlap,
                expected_index=journal.cas_token(blocked_index),
                manager_secret=MANAGER_SECRET,
            )
        disjoint = _sealed_journal(
            execution_id="disjoint",
            effects=[
                _effect(
                    "disjoint-effect",
                    repository_id="repo-b",
                    path="/work/repo-b",
                )
            ],
        )
        persisted = self.store.persist_initial(
            disjoint,
            expected_index=journal.cas_token(blocked_index),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(len(persisted.index["entries"]), 2)

    def test_preexisting_wrong_archive_never_allows_index_closure(
        self,
    ) -> None:
        index, current, _ = self.complete_synchronous()
        archive_path = (
            self.task_dir
            / journal.action_execution_archive_path(
                "execution-vector"
            )
        )
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(b"not-the-terminal-journal")
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.archive_and_close(
                "execution-vector",
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                authoritative_event_sha256=_sha("task-event"),
                manager_secret=MANAGER_SECRET,
            )
        self.assertEqual(self.store.read_index(), index)

    def test_orphan_cleanup_requires_exact_archive_bytes(self) -> None:
        index, current, _ = self.complete_synchronous()
        with self.assertRaises(_InjectedCrash):
            self.store.archive_and_close(
                "execution-vector",
                expected_index=journal.cas_token(index),
                expected_journal=journal.cas_token(current),
                authoritative_event_sha256=_sha("task-event"),
                manager_secret=MANAGER_SECRET,
                failure_hook=_crash_at(
                    "terminal-active-cleanup:before"
                ),
            )
        active_path = (
            self.task_dir
            / journal.action_execution_active_path(
                "execution-vector"
            )
        )
        active_path.write_bytes(active_path.read_bytes() + b"\n")
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.cleanup_orphan_active("execution-vector")


class ControlRotationAndCompensationStoreTests(
    ActionExecutionStoreCase
):
    def _persist_reconciliation(
        self,
        index: dict[str, object],
        target: dict[str, object],
        *,
        attempt_id: str,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
    ]:
        attempt = journal.new_reconciliation_attempt(
            target,
            index,
            attempt_id=attempt_id,
            effect_id="effect-a",
            expected_task_revision=8,
            recovery_action_id="control.reconcile/v1",
            authorization_kind="manager",
            authorization_sha256=_sha(attempt_id + "-auth"),
            capability_sha256=_sha(
                attempt_id + "-capability"
            ),
            gate_sha256=_sha(attempt_id + "-gate"),
            request_nonce_sha256=_sha(attempt_id + "-nonce"),
            engine_proof_sha256=_sha(attempt_id + "-proof"),
            principal="manager:" + attempt_id,
            manager_secret=MANAGER_SECRET,
        )
        persisted = self.store.persist_reconciliation_initial(
            attempt,
            target_execution_id=str(target["execution_id"]),
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        claimed = journal.advance_reconciliation_attempt(
            persisted.record, "CLAIMED"
        )
        claimed_result = self.store.persist_reconciliation_update(
            claimed,
            expected_index=journal.cas_token(persisted.index),
            expected_attempt=journal.cas_token(persisted.record),
            target_manager_secret=MANAGER_SECRET,
        )
        assert claimed_result.record is not None
        return (
            claimed_result.index,
            claimed_result.record,
            attempt,
        )

    def _unresolved_rotation(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
        journal.ControlRotationPlan,
    ]:
        index, target, _closed = (
            self.quarantine_for_reconciliation()
        )
        index, claimed, _attempt = self._persist_reconciliation(
            index, target, attempt_id="reconcile-old"
        )
        unresolved = journal.advance_reconciliation_attempt(
            claimed,
            "UNRESOLVED",
            evidence_sha256=_sha("unresolved-diagnostic"),
        )
        persisted = self.store.persist_reconciliation_update(
            unresolved,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        index = persisted.index
        unresolved = persisted.record
        fresh = journal.new_reconciliation_attempt(
            target,
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
        plan = journal.plan_reconciliation_control_rotation(
            index,
            unresolved,
            fresh,
            target_journal=target,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        return index, target, unresolved, fresh, plan

    def _authorized_compensation(
        self,
    ) -> tuple[
        dict[str, object],
        dict[str, object],
        dict[str, object],
        dict[str, object],
        journal.ControlRotationPlan,
    ]:
        index, target, _closed = (
            self.quarantine_for_reconciliation()
        )
        index, claimed, _attempt = self._persist_reconciliation(
            index, target, attempt_id="reconcile-compensation"
        )
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
        persisted = self.store.persist_reconciliation_update(
            authorized,
            expected_index=journal.cas_token(index),
            expected_attempt=journal.cas_token(claimed),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        index = persisted.index
        authorized = persisted.record
        compensation = journal.new_compensation_execution(
            authorized,
            target,
            manager_secret=MANAGER_SECRET,
        )
        plan = journal.plan_compensation_control_rotation(
            index,
            authorized,
            compensation,
            target_journal=target,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        return index, target, authorized, compensation, plan

    @staticmethod
    def _receipt(
        target: dict[str, object],
        authorized: dict[str, object],
    ) -> dict[str, object]:
        return journal.seal_compensation_receipt(
            {
                "execution_id": "compensation-control",
                "claim_id": "compensation-claim",
                "target_journal_record_sha256": target[
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

    def test_unresolved_rotation_crash_matrix_never_unblocks_target(
        self,
    ) -> None:
        stages = (
            "control-rotation-reserve:after-replace",
            "control-rotation-write:after-replace",
            "control-rotation-promote:after-replace",
            "control-rotation-archive:after-replace",
            "control-rotation-cleanup:after-unlink",
        )
        for stage in stages:
            case = type(self)(methodName="runTest")
            case.setUp()
            try:
                (
                    index,
                    target,
                    unresolved,
                    fresh,
                    plan,
                ) = case._unresolved_rotation()
                with self.subTest(stage=stage):
                    with self.assertRaises(_InjectedCrash):
                        case.store.rotate_reconciliation_control(
                            unresolved,
                            fresh,
                            target_execution_id=str(
                                target["execution_id"]
                            ),
                            expected_index=journal.cas_token(index),
                            manager_secret=MANAGER_SECRET,
                            rotation_plan=plan,
                            failure_hook=_crash_at(stage),
                        )
                    blocked = case.store.read_index()
                    self.assertEqual(len(blocked["entries"]), 2)
                    self.assertIn(
                        "execution-vector",
                        {
                            entry["execution_id"]
                            for entry in blocked["entries"]
                        },
                    )
                    completed = (
                        case.store.rotate_reconciliation_control(
                            unresolved,
                            fresh,
                            target_execution_id=str(
                                target["execution_id"]
                            ),
                            expected_index=journal.cas_token(index),
                            manager_secret=MANAGER_SECRET,
                            rotation_plan=plan,
                        )
                    )
                    self.assertEqual(
                        {
                            entry["execution_id"]
                            for entry in completed.index["entries"]
                        },
                        {
                            "execution-vector",
                            "reconcile-fresh",
                        },
                    )
                    self.assertEqual(
                        case.store.read_reconciliation_archive(
                            "reconcile-old"
                        ),
                        unresolved,
                    )
            finally:
                case.tearDown()

    def test_rotation_cas_loser_preserves_disjoint_winner(
        self,
    ) -> None:
        index, target, unresolved, fresh, plan = (
            self._unresolved_rotation()
        )
        disjoint = _sealed_journal(
            execution_id="disjoint-execution",
            effects=[
                _effect(
                    effect_id="disjoint-effect",
                    repository_id="repo-b",
                    path="/work/repo-b",
                )
            ],
        )
        winner = self.store.persist_initial(
            disjoint,
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
        )
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.rotate_reconciliation_control(
                unresolved,
                fresh,
                target_execution_id=str(target["execution_id"]),
                expected_index=journal.cas_token(index),
                manager_secret=MANAGER_SECRET,
                rotation_plan=plan,
            )
        self.assertEqual(self.store.read_index(), winner.index)

    def test_compensation_claim_is_one_shot_and_closure_is_exact(
        self,
    ) -> None:
        index, target, authorized, compensation, plan = (
            self._authorized_compensation()
        )
        rotated = self.store.rotate_to_compensation_control(
            authorized,
            compensation,
            target_execution_id=str(target["execution_id"]),
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
            rotation_plan=plan,
        )
        permit = self.store.claim_compensation_for_dispatch(
            "compensation-control",
            "compensation-claim",
            expected_index=journal.cas_token(rotated.index),
            expected_execution=journal.cas_token(compensation),
            target_manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(
            permit.compensation_plan, _compensation_plan()
        )
        claimed = self.store.read_compensation(
            "compensation-control"
        )
        claimed_index = self.store.read_index()
        with self.assertRaises(store.ActionExecutionStoreError):
            self.store.claim_compensation_for_dispatch(
                "compensation-control",
                "another-claim",
                expected_index=journal.cas_token(claimed_index),
                expected_execution=journal.cas_token(claimed),
                target_manager_secret=MANAGER_SECRET,
            )
        verified = journal.advance_compensation_execution(
            claimed,
            "RECEIPT_VERIFIED",
            receipt=self._receipt(target, authorized),
        )
        persisted = self.store.persist_compensation_update(
            verified,
            expected_index=journal.cas_token(claimed_index),
            expected_execution=journal.cas_token(claimed),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        committed = journal.advance_compensation_execution(
            persisted.record,
            "COMMITTED",
            recovery_event_sha256=_sha("compensation-event"),
            task_commit_revision=9,
            task_state_sha256=_sha("compensation-state"),
            outbox_sha256=_sha("compensation-outbox"),
            nonce_consumed=True,
        )
        persisted = self.store.persist_compensation_update(
            committed,
            expected_index=journal.cas_token(persisted.index),
            expected_execution=journal.cas_token(persisted.record),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        terminal = journal.finalize_reconciliation_compensation(
            authorized, persisted.record
        )
        closure = self.store.finalize_compensation_and_close(
            terminal,
            persisted.record,
            expected_index=journal.cas_token(persisted.index),
            expected_journal=journal.cas_token(target),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.index["entries"], [])
        self.assertEqual(
            self.store.read_archive_journal(
                "execution-vector",
                manager_secret=MANAGER_SECRET,
            ),
            target,
        )
        self.assertEqual(
            self.store.read_reconciliation_archive(
                "reconcile-compensation"
            ),
            terminal,
        )
        self.assertEqual(
            self.store.read_compensation_archive(
                "compensation-control"
            ),
            persisted.record,
        )

    def test_compensation_archive_failure_keeps_scope_then_retries(
        self,
    ) -> None:
        index, target, authorized, compensation, plan = (
            self._authorized_compensation()
        )
        rotated = self.store.rotate_to_compensation_control(
            authorized,
            compensation,
            target_execution_id=str(target["execution_id"]),
            expected_index=journal.cas_token(index),
            manager_secret=MANAGER_SECRET,
            rotation_plan=plan,
        )
        self.store.claim_compensation_for_dispatch(
            "compensation-control",
            "compensation-claim",
            expected_index=journal.cas_token(rotated.index),
            expected_execution=journal.cas_token(compensation),
            target_manager_secret=MANAGER_SECRET,
        )
        claimed = self.store.read_compensation(
            "compensation-control"
        )
        claimed_index = self.store.read_index()
        verified = journal.advance_compensation_execution(
            claimed,
            "RECEIPT_VERIFIED",
            receipt=self._receipt(target, authorized),
        )
        persisted = self.store.persist_compensation_update(
            verified,
            expected_index=journal.cas_token(claimed_index),
            expected_execution=journal.cas_token(claimed),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        committed = journal.advance_compensation_execution(
            persisted.record,
            "COMMITTED",
            recovery_event_sha256=_sha("compensation-event"),
            task_commit_revision=9,
            task_state_sha256=_sha("compensation-state"),
            outbox_sha256=_sha("compensation-outbox"),
            nonce_consumed=True,
        )
        persisted = self.store.persist_compensation_update(
            committed,
            expected_index=journal.cas_token(persisted.index),
            expected_execution=journal.cas_token(persisted.record),
            target_manager_secret=MANAGER_SECRET,
        )
        assert persisted.record is not None
        terminal = journal.finalize_reconciliation_compensation(
            authorized, persisted.record
        )
        with self.assertRaises(_InjectedCrash):
            self.store.finalize_compensation_and_close(
                terminal,
                persisted.record,
                expected_index=journal.cas_token(persisted.index),
                expected_journal=journal.cas_token(target),
                manager_secret=MANAGER_SECRET,
                failure_hook=_crash_at(
                    "compensation-reconciliation-archive:before"
                ),
            )
        self.assertEqual(len(self.store.read_index()["entries"]), 2)
        closure = self.store.finalize_compensation_and_close(
            terminal,
            persisted.record,
            expected_index=journal.cas_token(persisted.index),
            expected_journal=journal.cas_token(target),
            manager_secret=MANAGER_SECRET,
        )
        self.assertEqual(closure.index["entries"], [])


class RuntimeReservationTests(ActionExecutionStoreCase):
    def test_runtime_reservation_is_durable_before_closure_and_release(
        self,
    ) -> None:
        index, current, _handoff, reservation = (
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
        self.assertEqual(
            closure.mode, "PROMOTE_RUNTIME_RESERVATION"
        )
        self.assertEqual(
            closure.index["entries"][0]["entry_kind"],
            "runtime-reservation",
        )
        self.assertEqual(
            self.store.read_runtime_reservation(
                "execution-vector"
            ),
            reservation,
        )
        settled_core = {
            key: value
            for key, value in reservation.items()
            if key != "record_sha256"
        }
        settled_core.update(
            {
                "phase": "EXITED",
                "result_event_sha256": _sha("result-event"),
            }
        )
        settled = journal.seal_runtime_reservation(settled_core)
        released = self.store.release_runtime_reservation(
            settled,
            expected_index=journal.cas_token(closure.index),
            expected_reservation_record_sha256=str(
                reservation["record_sha256"]
            ),
            authenticated_exit_or_quiescence_sha256=_sha(
                "runtime-exit"
            ),
            result_or_cancellation_event_sha256=_sha(
                "result-event"
            ),
        )
        self.assertEqual(released.index["entries"], [])
        self.assertEqual(released.record["phase"], "EXITED")
        self.assertIn(
            ("lease", "lease-repo-a"),
            released.required_lock_claims,
        )

    def test_release_crash_after_settlement_keeps_scope_then_retries(
        self,
    ) -> None:
        index, current, _handoff, reservation = (
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
        settled_core = {
            key: value
            for key, value in reservation.items()
            if key != "record_sha256"
        }
        settled_core.update(
            {
                "phase": "QUIESCED",
                "result_event_sha256": _sha("cancel-event"),
            }
        )
        settled = journal.seal_runtime_reservation(settled_core)
        with self.assertRaises(_InjectedCrash):
            self.store.release_runtime_reservation(
                settled,
                expected_index=journal.cas_token(closure.index),
                expected_reservation_record_sha256=str(
                    reservation["record_sha256"]
                ),
                authenticated_exit_or_quiescence_sha256=_sha(
                    "runtime-quiescence"
                ),
                result_or_cancellation_event_sha256=_sha(
                    "cancel-event"
                ),
                failure_hook=_crash_at(
                    "runtime-reservation-release:before"
                ),
            )
        blocked = self.store.read_index()
        self.assertEqual(
            blocked["entries"][0]["entry_kind"],
            "runtime-reservation",
        )
        released = self.store.release_runtime_reservation(
            settled,
            expected_index=journal.cas_token(blocked),
            expected_reservation_record_sha256=str(
                reservation["record_sha256"]
            ),
            authenticated_exit_or_quiescence_sha256=_sha(
                "runtime-quiescence"
            ),
            result_or_cancellation_event_sha256=_sha(
                "cancel-event"
            ),
        )
        self.assertEqual(released.index["entries"], [])


if __name__ == "__main__":
    unittest.main()
