"""Focused tests for the release lifecycle authority primitives."""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import lifecycle_state


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
PROTOCOL = lifecycle_state.DISPATCHER_PROTOCOL


class LifecycleStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="Dev Flow 生命周期 root's space "
        )
        # macOS exposes /var as a compatibility symlink to /private/var.  Use
        # the native spelling so the test root itself has no linked ancestor.
        base = Path(self.temporary.name).resolve()
        self.state_root = base / "state root's 数据"
        self.releases = base / "managed releases 数据"
        self.releases.mkdir()
        self.release_a = self.releases / "release-A"
        self.release_b = self.releases / "release-B"
        self.release_a.mkdir()
        self.release_b.mkdir()
        self.state = lifecycle_state.LifecycleState(self.state_root, self.releases)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _activate(
        self,
        token: object,
        expected: lifecycle_state.ActiveSnapshot,
        release_id: str,
        path: Path,
        digest: str,
        transaction_id: str,
    ) -> lifecycle_state.ActiveSnapshot:
        return self.state.compare_and_set_active(
            token,
            expected,
            release_id=release_id,
            release_path=path,
            receipt_sha256=digest,
            dispatcher_protocol=PROTOCOL,
            transaction_id=transaction_id,
        )

    def _journal(
        self,
        transaction_id: str,
        snapshot: lifecycle_state.ActiveSnapshot,
        operation: str = "upgrade",
    ) -> lifecycle_state.TransactionJournal:
        return lifecycle_state.TransactionJournal(
            transaction_id=transaction_id,
            operation=operation,
            expected_active=self.state.expectation(snapshot),
            target_release=lifecycle_state.TargetRelease(
                "release-B", str(self.release_b), DIGEST_B
            ),
            previous_authority=snapshot.record,
            external_observations=(
                lifecycle_state.ExternalObservation(
                    "codex-plugin", "exact", DIGEST_A, "read back under lock"
                ),
            ),
            provisional_effects=(),
            owned_paths=(str(self.release_b),),
        )

    def test_authority_requires_live_lock_and_lock_file_is_persistent(self) -> None:
        with self.assertRaises(lifecycle_state.LockRequiredError):
            self.state.read_active(None)  # type: ignore[arg-type]

        with self.state.lock() as token:
            snapshot = self.state.read_active(token)
            self.assertFalse(snapshot.present)
            self.assertEqual(snapshot.generation, 0)
        inode = self.state.lock_path.stat().st_ino
        self.assertTrue(self.state.lock_path.is_file())

        with self.assertRaises(lifecycle_state.LockRequiredError):
            self.state.read_active(token)
        with self.state.lock() as second_token:
            self.assertFalse(self.state.read_active(second_token).present)
        self.assertEqual(self.state.lock_path.stat().st_ino, inode)

    def test_active_schema_is_closed_contained_and_protocol_fixed(self) -> None:
        with self.state.lock() as token:
            created = self._activate(
                token, self.state.read_active(token), "release-A", self.release_a,
                DIGEST_A, "tx-create",
            )
            raw = json.loads(self.state.active_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(raw),
                {
                    "schema",
                    "generation",
                    "release_id",
                    "release_path",
                    "receipt_sha256",
                    "dispatcher_protocol",
                    "transaction_id",
                },
            )
            self.assertEqual(created.record.transaction_id, "tx-create")

        invalid = dict(raw, unknown=True)
        self.state.active_path.write_text(json.dumps(invalid), encoding="utf-8")
        with self.state.lock() as token:
            with self.assertRaises(lifecycle_state.SchemaError):
                self.state.read_active(token)

        self.state.active_path.unlink()
        with self.state.lock() as token:
            with self.assertRaises(lifecycle_state.UnsafePathError):
                self._activate(
                    token,
                    self.state.read_active(token),
                    "outside",
                    Path(self.temporary.name) / "outside",
                    DIGEST_A,
                    "tx-outside",
                )
            with self.assertRaises(lifecycle_state.SchemaError):
                self.state.compare_and_set_active(
                    token,
                    self.state.read_active(token),
                    release_id="release-A",
                    release_path=self.release_a,
                    receipt_sha256=DIGEST_A,
                    dispatcher_protocol="dev-flow-dispatcher/2.0.0",
                    transaction_id="tx-protocol",
                )

    def test_generation_digest_cas_rejects_stale_and_prevents_aba(self) -> None:
        with self.state.lock() as token:
            absent_zero = self.state.read_active(token)
            release_a = self._activate(
                token, absent_zero, "release-A", self.release_a, DIGEST_A, "tx-A"
            )
            with self.assertRaises(lifecycle_state.CasMismatchError):
                self._activate(
                    token, absent_zero, "stale", self.release_b, DIGEST_B, "tx-stale"
                )

            release_b = self._activate(
                token, release_a, "release-B", self.release_b, DIGEST_B, "tx-B"
            )
            restored_a = self.state.restore_active(
                token, release_b, release_a.record, transaction_id="tx-restore-A"
            )
            self.assertEqual(restored_a.record.release_id, "release-A")
            self.assertEqual(restored_a.record.transaction_id, "tx-A")
            self.assertEqual((release_a.generation, release_b.generation, restored_a.generation), (1, 2, 3))
            with self.assertRaises(lifecycle_state.CasMismatchError):
                self.state.compare_and_delete_active(token, release_a)

            absent_four = self.state.compare_and_delete_active(token, restored_a)
            self.assertEqual(absent_four.generation, 4)
            recreated = self._activate(
                token, absent_four, "release-B", self.release_b, DIGEST_B, "tx-new-B"
            )
            self.assertEqual(recreated.generation, 5)
            with self.assertRaises(lifecycle_state.CasMismatchError):
                self._activate(
                    token, absent_zero, "old-absence", self.release_a, DIGEST_A,
                    "tx-old-absence",
                )

    def test_uninstall_can_cas_delete_after_owned_release_removal(self) -> None:
        with self.state.lock() as token:
            active = self._activate(
                token,
                self.state.read_active(token),
                "release-A",
                self.release_a,
                DIGEST_A,
                "tx-install",
            )
            self.release_a.rmdir()
            observed = self.state.read_active(token)
            self.assertEqual(observed, active)
            deleted = self.state.compare_and_delete_active(token, observed)
            self.assertFalse(deleted.present)
            self.assertEqual(deleted.generation, 2)

    def test_journal_schema_bounds_recovery_scan_and_terminal_transitions(self) -> None:
        with self.state.lock() as token:
            active = self._activate(
                token, self.state.read_active(token), "release-A", self.release_a,
                DIGEST_A, "tx-active",
            )
            created = self.state.create_transaction(token, self._journal("tx-upgrade", active))
            self.state.require_no_non_terminal(
                token, except_transaction_id="tx-upgrade"
            )
            with self.assertRaises(lifecycle_state.UnresolvedTransactionError):
                self.state.require_no_non_terminal(token)

            provisional = self.state.advance_transaction(
                token,
                created,
                phase="candidate_ready",
                observations=(
                    lifecycle_state.ExternalObservation("candidate", "exact", DIGEST_B),
                ),
                provisional_effects=(
                    lifecycle_state.ProvisionalEffect(
                        "marketplace", "dev-flow", DIGEST_A, DIGEST_B, True
                    ),
                ),
            )
            terminal = self.state.finish_transaction(
                token,
                provisional,
                "rolled_back",
                retained_paths=(str(self.release_b),),
                recovery=("Inspect the retained candidate before exact removal.",),
            )
            self.assertEqual(terminal.journal.phase, "terminal")
            self.assertEqual(terminal.journal.outcome, "rolled_back")
            self.state.require_no_non_terminal(token)
            with self.assertRaises(lifecycle_state.TransitionError):
                self.state.finish_transaction(token, terminal, "committed")
            with self.assertRaises(lifecycle_state.TransitionError):
                self.state.finish_transaction(token, terminal, "success")

            oversized = replace(
                self._journal("tx-oversized", active),
                recovery=("x" * (lifecycle_state.MAX_TEXT_BYTES + 1),),
            )
            with self.assertRaises(lifecycle_state.ResourceLimitError):
                self.state.create_transaction(token, oversized)

        raw = json.loads(
            (self.state.transactions_path / "tx-upgrade.json").read_text(encoding="utf-8")
        )
        raw["unknown"] = True
        (self.state.transactions_path / "tx-upgrade.json").write_text(
            json.dumps(raw), encoding="utf-8"
        )
        with self.state.lock() as token:
            with self.assertRaises(lifecycle_state.SchemaError):
                self.state.scan_transactions(token)

    def test_repeated_retained_path_is_deduplicated_through_recovery_and_finish(self) -> None:
        retained = str(self.release_b)
        with self.state.lock() as token:
            active = self._activate(
                token,
                self.state.read_active(token),
                "release-A",
                self.release_a,
                DIGEST_A,
                "tx-active",
            )
            pending = self.state.create_transaction(
                token, self._journal("tx-repeated-retained", active)
            )
            pending = self.state.advance_transaction(
                token,
                pending,
                phase="candidate_ready",
                retained_paths=(retained,),
            )
            recovering = self.state.advance_transaction(
                token,
                pending,
                phase="recovering",
                retained_paths=(retained, retained + os.sep),
            )
            terminal = self.state.finish_transaction(
                token,
                recovering,
                "rolled_back",
                retained_paths=(retained,),
            )

        self.assertEqual(terminal.journal.outcome, "rolled_back")
        self.assertEqual(terminal.journal.retained_paths, (retained,))

    def test_symlinked_state_ancestor_is_rejected(self) -> None:
        if os.name == "nt":
            self.skipTest("native reparse evidence belongs to the Windows gate")
        base = Path(self.temporary.name).resolve()
        actual = base / "actual-state"
        actual.mkdir()
        linked = base / "linked-state"
        linked.symlink_to(actual, target_is_directory=True)
        unsafe = lifecycle_state.LifecycleState(linked, self.releases)
        with self.assertRaises(lifecycle_state.UnsafePathError):
            with unsafe.lock():
                pass

    def _run_concurrent(self, first, second) -> tuple[list[int], list[BaseException]]:
        barrier = threading.Barrier(3)
        generations: list[int] = []
        failures: list[BaseException] = []
        guard = threading.Lock()

        def invoke(callback) -> None:
            try:
                barrier.wait(timeout=5)
                with self.state.lock(timeout_seconds=5) as token:
                    generation = callback(token)
                    with guard:
                        generations.append(generation)
                    time.sleep(0.03)
            except BaseException as exc:  # preserve thread evidence for assertion
                with guard:
                    failures.append(exc)

        threads = [threading.Thread(target=invoke, args=(item,)) for item in (first, second)]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        return generations, failures

    def test_concurrent_upgrade_vs_upgrade_is_serialized(self) -> None:
        def upgrade_a(token) -> int:
            observed = self.state.read_active(token)
            return self._activate(
                token, observed, "release-A", self.release_a, DIGEST_A, "tx-upgrade-A"
            ).generation

        def upgrade_b(token) -> int:
            observed = self.state.read_active(token)
            return self._activate(
                token, observed, "release-B", self.release_b, DIGEST_B, "tx-upgrade-B"
            ).generation

        generations, failures = self._run_concurrent(upgrade_a, upgrade_b)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(generations), [1, 2])
        with self.state.lock() as token:
            self.assertEqual(self.state.read_active(token).generation, 2)

    def test_concurrent_upgrade_vs_uninstall_is_serialized(self) -> None:
        with self.state.lock() as token:
            self._activate(
                token, self.state.read_active(token), "release-A", self.release_a,
                DIGEST_A, "tx-initial",
            )

        def upgrade(token) -> int:
            observed = self.state.read_active(token)
            return self._activate(
                token, observed, "release-B", self.release_b, DIGEST_B, "tx-upgrade"
            ).generation

        def uninstall(token) -> int:
            observed = self.state.read_active(token)
            return self.state.compare_and_delete_active(token, observed).generation

        generations, failures = self._run_concurrent(upgrade, uninstall)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(generations), [2, 3])
        with self.state.lock() as token:
            final = self.state.read_active(token)
            self.assertEqual(final.generation, 3)
            self.assertIn(
                None if final.record is None else final.record.release_id,
                (None, "release-B"),
            )

    def test_strict_json_rejects_duplicate_keys(self) -> None:
        with self.assertRaises(lifecycle_state.SchemaError):
            lifecycle_state.strict_json_bytes(
                b'{"schema":"one","schema":"two"}',
                maximum=1024,
                label="fixture",
            )


if __name__ == "__main__":
    unittest.main()
