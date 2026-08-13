"""Layered simulated evidence for the shared lifecycle state machine."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import lifecycle_machine
from scripts import lifecycle_state


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
ENVELOPE_A = lifecycle_machine.ArtifactEnvelope(DIGEST_A, DIGEST_B, DIGEST_C)
ENVELOPE_CHANGED = lifecycle_machine.ArtifactEnvelope(DIGEST_D, DIGEST_B, DIGEST_C)


def observation(subject: str, state: str = "exact", detail: str | None = None):
    return lifecycle_state.ExternalObservation(subject, state, None, detail)


def exact(subject: str) -> lifecycle_machine.StepEvidence:
    return lifecycle_machine.StepEvidence(True, (observation(subject),))


class FakeCandidates:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.attestation = lifecycle_machine.ActiveAttestation(
            True, False, "1.0.0", ENVELOPE_A, (observation("active-attestation"),)
        )
        self.fail_staged = False
        self.retain_inactive = False
        self.build_count = 0

    def attest_active(self, active):
        self.events.append(f"attest:{active.release_id}")
        return self.attestation

    def build_candidate(self, request):
        self.events.append(f"build:{request.release_id}")
        self.build_count += 1
        Path(request.release_path).mkdir(parents=True, exist_ok=True)
        return lifecycle_machine.Candidate(
            request.version,
            request.release_id,
            request.release_path,
            DIGEST_D,
            request.envelope,
            (request.release_path,),
        )

    def staged_health(self, candidate):
        self.events.append(f"staged:{candidate.release_id}")
        return lifecycle_machine.StepEvidence(
            not self.fail_staged,
            (
                observation(
                    "candidate-staged-health",
                    "exact" if not self.fail_staged else "changed",
                ),
            ),
        )

    def cleanup_owned(self, journal):
        self.events.append(f"cleanup:{journal.transaction_id}")
        retained = tuple(path for path in journal.owned_paths if Path(path).exists())
        return lifecycle_machine.StepEvidence(
            True,
            (observation("candidate-cleanup"),),
            retained_paths=retained,
            recovery=("Remove retained candidate only after exact comparison.",)
            if retained
            else (),
        )

    def cleanup_inactive(self, previous, active):
        release_id = None if previous is None else previous.release_id
        self.events.append(f"cleanup-inactive:{release_id}")
        retained = (
            (previous.release_path,)
            if previous is not None and self.retain_inactive
            else ()
        )
        return lifecycle_machine.StepEvidence(
            not retained,
            (observation("inactive-release-cleanup", "exact" if not retained else "changed"),),
            retained_paths=retained,
            recovery=("Inspect retained non-authoritative release content.",)
            if retained
            else (),
        )


class FakeHost:
    def __init__(
        self,
        events: list[str],
        active_path: Path,
        initial_release: str | None,
    ) -> None:
        self.events = events
        self.active_path = active_path
        self.marketplace = initial_release
        self.plugin = initial_release
        self.fail_plugin = False
        self.fail_target_public_once = False
        self.fail_previous_public = False
        self.restore_exact = True
        self.public_active_transactions: list[str | None] = []

    @staticmethod
    def _effect(kind: str, before: str | None, after: str | None):
        return lifecycle_state.ProvisionalEffect(
            kind,
            "dev-flow-orchestrator",
            None if before is None else DIGEST_A,
            None if after is None else DIGEST_B,
            True,
        )

    def observe_previous(self, active):
        expected = None if active is None else active.release_id
        self.events.append(f"observe:{expected}")
        is_exact = self.marketplace == expected and self.plugin == expected
        return lifecycle_machine.StepEvidence(
            is_exact,
            (
                observation(
                    "previous-host-state", "exact" if is_exact else "changed"
                ),
            ),
        )

    def provision_marketplace(self, candidate):
        self.events.append(f"marketplace:{candidate.release_id}")
        before = self.marketplace
        self.marketplace = candidate.release_id
        return lifecycle_machine.StepEvidence(
            True,
            (observation("marketplace-read-back"),),
            (self._effect("marketplace", before, candidate.release_id),),
        )

    def provision_plugin(self, candidate):
        self.events.append(f"plugin:{candidate.release_id}")
        before = self.plugin
        self.plugin = candidate.release_id
        return lifecycle_machine.StepEvidence(
            not self.fail_plugin,
            (
                observation(
                    "plugin-read-back", "changed" if self.fail_plugin else "exact"
                ),
            ),
            (self._effect("plugin", before, candidate.release_id),),
        )

    def read_back_candidate(self, candidate):
        self.events.append(f"readback-candidate:{candidate.release_id}")
        matches = (
            self.marketplace == candidate.release_id
            and self.plugin == candidate.release_id
        )
        return lifecycle_machine.StepEvidence(
            matches,
            (observation("candidate-host-read-back", "exact" if matches else "changed"),),
        )

    def read_back_active(self, active):
        self.events.append(f"readback-active:{active.release_id}")
        matches = self.marketplace == active.release_id and self.plugin == active.release_id
        return lifecycle_machine.StepEvidence(
            matches,
            (observation("active-host-read-back", "exact" if matches else "changed"),),
        )

    def restore_previous(self, journal):
        previous = journal.previous_authority
        release_id = None if previous is None else previous.release_id
        self.events.append(f"restore:{release_id}")
        if self.restore_exact:
            self.marketplace = release_id
            self.plugin = release_id
        return lifecycle_machine.StepEvidence(
            self.restore_exact,
            (
                observation(
                    "previous-host-restoration",
                    "exact" if self.restore_exact else "unknown",
                ),
            ),
        )

    def public_proof(self, active):
        release_id = None if active is None else active.release_id
        self.events.append(f"public:{release_id}")
        transaction_id = None
        if self.active_path.exists():
            transaction_id = json.loads(
                self.active_path.read_text(encoding="utf-8")
            )["transaction_id"]
        self.public_active_transactions.append(transaction_id)
        matches = self.marketplace == release_id and self.plugin == release_id
        if self.fail_target_public_once and release_id == "release-B":
            self.fail_target_public_once = False
            matches = False
        if self.fail_previous_public and release_id == "release-A":
            matches = False
        state = "exact" if matches else "changed"
        return lifecycle_machine.StepEvidence(
            matches,
            (
                observation("public-cli-startup", state),
                observation("public-mcp-startup", state),
            ),
        )


class FrozenMigrationClassifier:
    def __init__(self, exact_predecessor: bool) -> None:
        self.exact_predecessor = exact_predecessor
        self.calls = 0

    def classify(self):
        self.calls += 1
        return lifecycle_machine.MigrationClassification(
            self.exact_predecessor,
            (
                observation(
                    "legacy-fixture",
                    "exact" if self.exact_predecessor else "unknown",
                ),
            ),
            ()
            if self.exact_predecessor
            else ("Use only the frozen immediately preceding installer fixture.",),
        )


class LifecycleMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="Dev Flow machine root's 数据 "
        )
        base = Path(self.temporary.name).resolve()
        self.state_root = base / "lifecycle"
        self.releases = base / "managed releases"
        self.releases.mkdir()
        self.release_a = self.releases / "release-A"
        self.release_b = self.releases / "release-B"
        self.release_c = self.releases / "release-C"
        self.release_a.mkdir()
        self.state = lifecycle_state.LifecycleState(self.state_root, self.releases)
        self.events: list[str] = []
        self.candidates = FakeCandidates(self.events)
        self.host = FakeHost(self.events, self.state.active_path, None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _machine(self, classifier=None):
        return lifecycle_machine.LifecycleMachine(
            self.state,
            self.candidates,
            self.host,
            migration_classifier=classifier,
        )

    def _request(
        self,
        operation: str = "upgrade",
        transaction_id: str = "tx-new",
        release_id: str = "release-B",
        release_path: Path | None = None,
        envelope: lifecycle_machine.ArtifactEnvelope = ENVELOPE_A,
    ):
        return lifecycle_machine.ActivationRequest(
            operation,
            transaction_id,
            "1.0.0",
            release_id,
            str(self.release_b if release_path is None else release_path),
            envelope,
        )

    def _install_active_a(self) -> lifecycle_state.ActiveSnapshot:
        with self.state.lock() as token:
            active = self.state.compare_and_set_active(
                token,
                self.state.read_active(token),
                release_id="release-A",
                release_path=self.release_a,
                receipt_sha256=DIGEST_A,
                dispatcher_protocol=lifecycle_state.DISPATCHER_PROTOCOL,
                transaction_id="tx-existing",
            )
        self.host.marketplace = "release-A"
        self.host.plugin = "release-A"
        return active

    def _journal(self, transaction_id: str):
        with self.state.lock() as token:
            return self.state.read_transaction(token, transaction_id).journal

    def test_fresh_activation_has_strict_order_and_commits_after_public_proof(self) -> None:
        result = self._machine().run(self._request("install"))

        self.assertEqual(result.outcome, "committed")
        self.assertEqual(result.active.record.release_id, "release-B")
        self.assertEqual(
            self.events,
            [
                "build:release-B",
                "staged:release-B",
                "observe:None",
                "marketplace:release-B",
                "plugin:release-B",
                "readback-candidate:release-B",
                "public:release-B",
                "cleanup-inactive:None",
            ],
        )
        self.assertEqual(self.host.public_active_transactions, ["tx-new"])
        journal = self._journal("tx-new")
        self.assertEqual(journal.outcome, "committed")
        self.assertEqual([effect.kind for effect in journal.provisional_effects], ["marketplace", "plugin"])
        subjects = [item.subject for item in journal.external_observations]
        self.assertIn("candidate-staged-health", subjects)
        self.assertIn("candidate-host-read-back", subjects)
        self.assertIn("public-cli-startup", subjects)
        self.assertIn("public-mcp-startup", subjects)

    def test_healthy_repair_reuses_only_after_full_readback_and_public_proof(self) -> None:
        active = self._install_active_a()
        self.candidates.attestation = lifecycle_machine.ActiveAttestation(
            True, True, "1.0.0", ENVELOPE_A, (observation("complete-attestation"),)
        )
        result = self._machine().run(
            self._request(
                "repair", "tx-repair", "release-A", self.release_a, ENVELOPE_A
            )
        )

        self.assertEqual(result.outcome, "committed")
        self.assertTrue(result.reused)
        self.assertEqual(result.active.digest, active.digest)
        self.assertEqual(self.candidates.build_count, 0)
        self.assertEqual(
            self.events,
            ["attest:release-A", "readback-active:release-A", "public:release-A"],
        )

    def test_drift_repair_builds_same_envelope_candidate(self) -> None:
        self._install_active_a()
        self.candidates.attestation = lifecycle_machine.ActiveAttestation(
            True, False, "1.0.0", ENVELOPE_A, (observation("installed-drift", "changed"),)
        )
        result = self._machine().run(self._request("repair", "tx-drift"))

        self.assertEqual(result.outcome, "committed")
        self.assertEqual(result.active.record.release_id, "release-B")
        self.assertEqual(self.candidates.build_count, 1)
        self.assertLess(self.events.index("staged:release-B"), self.events.index("marketplace:release-B"))

    def test_same_version_digest_envelope_change_is_refused(self) -> None:
        active = self._install_active_a()
        self.candidates.attestation = lifecycle_machine.ActiveAttestation(
            True, False, "1.0.0", ENVELOPE_A, (observation("receipt-envelope"),)
        )
        result = self._machine().run(
            self._request("repair", "tx-replaced", envelope=ENVELOPE_CHANGED)
        )

        self.assertEqual(result.outcome, "rolled_back")
        self.assertEqual(result.active.digest, active.digest)
        self.assertIn("same-version", result.detail)
        self.assertEqual(self.candidates.build_count, 0)
        self.assertEqual(self.events, ["attest:release-A", "public:release-A"])

    def test_failure_before_provisional_effects_rolls_back_without_host_mutation(self) -> None:
        active = self._install_active_a()
        self.candidates.fail_staged = True
        result = self._machine().run(self._request("upgrade", "tx-staged-fail"))

        self.assertEqual(result.outcome, "rolled_back")
        self.assertEqual(result.active.digest, active.digest)
        self.assertNotIn("marketplace:release-B", self.events)
        self.assertNotIn("restore:release-A", self.events)
        self.assertIn("public:release-A", self.events)
        journal = self._journal("tx-staged-fail")
        self.assertEqual(journal.outcome, "rolled_back")
        self.assertIn(str(self.release_b), journal.retained_paths)

    def test_failure_without_host_effect_is_partial_when_previous_is_unproven(self) -> None:
        active = self._install_active_a()
        self.candidates.fail_staged = True
        self.host.fail_previous_public = True
        result = self._machine().run(
            self._request("upgrade", "tx-unproven-previous")
        )

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.active.digest, active.digest)
        self.assertIn("public:release-A", self.events)
        self.assertNotIn("marketplace:release-B", self.events)
        self.assertEqual(
            self._journal("tx-unproven-previous").outcome, "partial"
        )

    def test_failure_after_host_effects_restores_previous_before_active_commit(self) -> None:
        active = self._install_active_a()
        self.host.fail_plugin = True
        result = self._machine().run(self._request("upgrade", "tx-plugin-fail"))

        self.assertEqual(result.outcome, "rolled_back")
        self.assertEqual(result.active.digest, active.digest)
        self.assertEqual((self.host.marketplace, self.host.plugin), ("release-A", "release-A"))
        self.assertIn("restore:release-A", self.events)
        self.assertNotIn("public:release-B", self.events)
        self.assertLess(self.events.index("restore:release-A"), self.events.index("public:release-A"))
        journal = self._journal("tx-plugin-fail")
        self.assertEqual([effect.kind for effect in journal.provisional_effects], ["marketplace", "plugin"])

    def test_failure_after_host_effect_is_partial_when_restored_startup_is_unproven(self) -> None:
        active = self._install_active_a()
        self.host.fail_plugin = True
        self.host.fail_previous_public = True

        result = self._machine().run(
            self._request("upgrade", "tx-plugin-fail-unproven")
        )

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.active.digest, active.digest)
        self.assertIn("restore:release-A", self.events)
        self.assertIn("public:release-A", self.events)
        self.assertEqual(
            self._journal("tx-plugin-fail-unproven").outcome, "partial"
        )

    def test_public_failure_cas_restores_immediate_previous_and_reproves_it(self) -> None:
        active = self._install_active_a()
        self.host.fail_target_public_once = True
        result = self._machine().run(self._request("upgrade", "tx-public-fail"))

        self.assertEqual(result.outcome, "rolled_back")
        self.assertEqual(result.active.record.release_id, "release-A")
        self.assertGreater(result.active.generation, active.generation)
        self.assertEqual(result.active.record.transaction_id, "tx-existing")
        self.assertLess(self.events.index("public:release-B"), self.events.index("restore:release-A"))
        self.assertLess(self.events.index("restore:release-A"), self.events.index("public:release-A"))
        self.assertEqual(self._journal("tx-public-fail").outcome, "rolled_back")

    def test_success_cleans_only_immediate_previous_before_terminal_commit(self) -> None:
        self._install_active_a()
        result = self._machine().run(self._request("upgrade", "tx-cleanup"))

        self.assertEqual(result.outcome, "committed")
        self.assertIn("cleanup-inactive:release-A", self.events)
        self.assertLess(
            self.events.index("public:release-B"),
            self.events.index("cleanup-inactive:release-A"),
        )
        journal = self._journal("tx-cleanup")
        self.assertEqual(journal.outcome, "committed")
        self.assertTrue(
            any(item.subject == "inactive-release-cleanup" for item in journal.external_observations)
        )

    def test_changed_inactive_residue_is_recorded_but_not_authoritative(self) -> None:
        self._install_active_a()
        self.candidates.retain_inactive = True
        result = self._machine().run(self._request("upgrade", "tx-retained"))

        self.assertEqual(result.outcome, "committed")
        self.assertEqual(result.active.record.release_id, "release-B")
        journal = self._journal("tx-retained")
        self.assertIn(str(self.release_a), journal.retained_paths)
        self.assertIn(
            "Inspect retained non-authoritative release content.", journal.recovery
        )

    def test_unprovable_post_commit_restoration_is_partial_and_stops(self) -> None:
        self._install_active_a()
        self.host.fail_target_public_once = True
        self.host.restore_exact = False
        result = self._machine().run(self._request("upgrade", "tx-partial"))

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.active.record.release_id, "release-A")
        self.assertIn("restore:release-A", self.events)
        self.assertNotIn("public:release-A", self.events)
        journal = self._journal("tx-partial")
        self.assertEqual(journal.outcome, "partial")
        self.assertTrue(journal.recovery)

    def test_interrupted_transaction_is_recovered_before_new_activation(self) -> None:
        active = self._install_active_a()
        self.release_b.mkdir()
        with self.state.lock() as token:
            pending = self.state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id="tx-interrupted",
                    operation="upgrade",
                    expected_active=self.state.expectation(active),
                    target_release=lifecycle_state.TargetRelease(
                        "release-B", str(self.release_b), DIGEST_B
                    ),
                    previous_authority=active.record,
                    owned_paths=(str(self.release_b),),
                ),
            )
            self.state.advance_transaction(token, pending, phase="candidate_ready")

        result = self._machine().run(
            self._request(
                "upgrade", "tx-after-recovery", "release-C", self.release_c
            )
        )

        self.assertEqual(result.outcome, "committed")
        self.assertEqual(result.recovered_transactions, ("tx-interrupted",))
        self.assertEqual(self._journal("tx-interrupted").outcome, "rolled_back")
        self.assertEqual(result.active.record.release_id, "release-C")
        self.assertLess(self.events.index("cleanup:tx-interrupted"), self.events.index("build:release-C"))

    def test_recovery_can_report_an_already_retained_owned_path(self) -> None:
        active = self._install_active_a()
        self.release_b.mkdir()
        retained = str(self.release_b)
        with self.state.lock() as token:
            pending = self.state.create_transaction(
                token,
                lifecycle_state.TransactionJournal(
                    transaction_id="tx-retained-recovery",
                    operation="upgrade",
                    expected_active=self.state.expectation(active),
                    target_release=lifecycle_state.TargetRelease(
                        "release-B", retained, DIGEST_B
                    ),
                    previous_authority=active.record,
                    owned_paths=(retained,),
                    retained_paths=(retained,),
                ),
            )
            self.state.advance_transaction(token, pending, phase="candidate_ready")

        result = self._machine().run(
            self._request(
                "upgrade", "tx-after-retained-recovery", "release-C", self.release_c
            )
        )

        self.assertEqual(result.outcome, "committed")
        self.assertEqual(result.recovered_transactions, ("tx-retained-recovery",))
        journal = self._journal("tx-retained-recovery")
        self.assertEqual(journal.outcome, "rolled_back")
        self.assertEqual(journal.retained_paths, (retained,))

    def test_migration_rejects_ambiguous_predecessor_before_candidate_build(self) -> None:
        classifier = FrozenMigrationClassifier(False)
        result = self._machine(classifier).run(
            self._request("migration", "tx-migration")
        )

        self.assertEqual(result.outcome, "partial")
        self.assertFalse(result.active.present)
        self.assertEqual(classifier.calls, 1)
        self.assertEqual(self.candidates.build_count, 0)
        self.assertEqual(self._journal("tx-migration").outcome, "partial")


if __name__ == "__main__":
    unittest.main()
