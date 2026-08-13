#!/usr/bin/env python3
"""Shared, adapter-driven lifecycle activation state machine.

This module deliberately owns no Codex, marketplace, wheel, or filesystem
installation implementation.  Those effects are supplied by narrow adapters;
the machine owns their ordering, the durable journal, active-record CAS, and
bounded recovery decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence, Tuple

from scripts import lifecycle_state


ACTIVATION_OPERATIONS = frozenset({"install", "repair", "upgrade", "migration"})


@dataclass(frozen=True)
class ArtifactEnvelope:
    index_sha256: str
    archive_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ActivationRequest:
    operation: str
    transaction_id: str
    version: str
    release_id: str
    release_path: str
    envelope: ArtifactEnvelope


@dataclass(frozen=True)
class Candidate:
    version: str
    release_id: str
    release_path: str
    receipt_sha256: str
    envelope: ArtifactEnvelope
    owned_paths: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StepEvidence:
    exact: bool
    observations: Tuple[lifecycle_state.ExternalObservation, ...] = ()
    effects: Tuple[lifecycle_state.ProvisionalEffect, ...] = ()
    retained_paths: Tuple[str, ...] = ()
    recovery: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ActiveAttestation:
    """Receipt identity and complete reuse health are intentionally separate."""

    identity_proven: bool
    reusable: bool
    version: Optional[str]
    envelope: Optional[ArtifactEnvelope]
    observations: Tuple[lifecycle_state.ExternalObservation, ...] = ()


@dataclass(frozen=True)
class MigrationClassification:
    exact_predecessor: bool
    observations: Tuple[lifecycle_state.ExternalObservation, ...] = ()
    recovery: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleResult:
    transaction_id: str
    outcome: str
    active: lifecycle_state.ActiveSnapshot
    reused: bool = False
    recovered_transactions: Tuple[str, ...] = ()
    detail: Optional[str] = None


class AdapterFailure(RuntimeError):
    """An adapter failure with bounded evidence suitable for the journal."""

    def __init__(
        self,
        message: str,
        *,
        observations: Sequence[lifecycle_state.ExternalObservation] = (),
        effects: Sequence[lifecycle_state.ProvisionalEffect] = (),
        retained_paths: Sequence[str] = (),
        recovery: Sequence[str] = (),
        uncertain: bool = False,
    ) -> None:
        super().__init__(message)
        self.observations = tuple(observations)
        self.effects = tuple(effects)
        self.retained_paths = tuple(retained_paths)
        self.recovery = tuple(recovery)
        self.uncertain = uncertain


class CandidateAdapter(Protocol):
    def attest_active(
        self, active: lifecycle_state.ActiveRecord
    ) -> ActiveAttestation: ...

    def build_candidate(
        self, request: ActivationRequest
    ) -> Candidate: ...

    def staged_health(self, candidate: Candidate) -> StepEvidence: ...

    def cleanup_owned(
        self, journal: lifecycle_state.TransactionJournal
    ) -> StepEvidence: ...

    def cleanup_inactive(
        self,
        previous: Optional[lifecycle_state.ActiveRecord],
        active: lifecycle_state.ActiveRecord,
    ) -> StepEvidence: ...


class HostAdapter(Protocol):
    def observe_previous(
        self, active: Optional[lifecycle_state.ActiveRecord]
    ) -> StepEvidence: ...

    def provision_marketplace(
        self, candidate: Candidate
    ) -> StepEvidence: ...

    def provision_plugin(self, candidate: Candidate) -> StepEvidence: ...

    def read_back_candidate(self, candidate: Candidate) -> StepEvidence: ...

    def read_back_active(
        self, active: lifecycle_state.ActiveRecord
    ) -> StepEvidence: ...

    def restore_previous(
        self, journal: lifecycle_state.TransactionJournal
    ) -> StepEvidence: ...

    def public_proof(
        self, active: Optional[lifecycle_state.ActiveRecord]
    ) -> StepEvidence: ...


class MigrationClassifier(Protocol):
    def classify(self) -> MigrationClassification: ...


class LifecycleMachine:
    def __init__(
        self,
        state: lifecycle_state.LifecycleState,
        candidates: CandidateAdapter,
        host: HostAdapter,
        *,
        migration_classifier: Optional[MigrationClassifier] = None,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        self.state = state
        self.candidates = candidates
        self.host = host
        self.migration_classifier = migration_classifier
        self.lock_timeout_seconds = lock_timeout_seconds

    def run(self, request: ActivationRequest) -> LifecycleResult:
        if request.operation not in ACTIVATION_OPERATIONS:
            raise ValueError(f"unsupported activation operation: {request.operation}")
        recovered: list[str] = []
        with self.state.lock(timeout_seconds=self.lock_timeout_seconds) as token:
            pending_transactions = self.state.non_terminal_transactions(token)
            if len(pending_transactions) > 1:
                for pending in pending_transactions:
                    self.state.finish_transaction(
                        token,
                        pending,
                        "partial",
                        observations=(
                            lifecycle_state.ExternalObservation(
                                "transaction-recovery",
                                "unknown",
                                detail="multiple non-terminal journals are ambiguous",
                            ),
                        ),
                        recovery=(
                            "Inspect every recorded transaction before any identity-specific mutation.",
                        ),
                    )
                    recovered.append(pending.journal.transaction_id)
                return LifecycleResult(
                    pending_transactions[0].journal.transaction_id,
                    "partial",
                    self.state.read_active(token),
                    recovered_transactions=tuple(recovered),
                    detail="multiple non-terminal lifecycle transactions were classified partial",
                )
            for pending in pending_transactions:
                result = self._recover_one(token, pending)
                recovered.append(result.transaction_id)
                if result.outcome == "partial":
                    return LifecycleResult(
                        result.transaction_id,
                        "partial",
                        self.state.read_active(token),
                        recovered_transactions=tuple(recovered),
                        detail="prior lifecycle transaction remains unresolved",
                    )
            self.state.require_no_non_terminal(token)
            result = self._run_locked(token, request)
            return LifecycleResult(
                result.transaction_id,
                result.outcome,
                result.active,
                reused=result.reused,
                recovered_transactions=tuple(recovered),
                detail=result.detail,
            )

    def _run_locked(self, token: object, request: ActivationRequest) -> LifecycleResult:
        previous = self.state.read_active(token)
        journal = self.state.create_transaction(
            token,
            lifecycle_state.TransactionJournal(
                transaction_id=request.transaction_id,
                operation=request.operation,
                expected_active=self.state.expectation(previous),
                target_release=lifecycle_state.TargetRelease(
                    request.release_id,
                    request.release_path,
                    request.envelope.archive_sha256,
                ),
                previous_authority=previous.record,
                owned_paths=(request.release_path,),
            ),
        )

        precondition = self._precondition(token, journal, request, previous)
        if precondition is not None:
            return precondition

        if request.operation == "repair":
            repair = self._repair_decision(token, journal, request, previous)
            if repair is not None:
                return repair
            journal = self.state.read_transaction(token, request.transaction_id)

        if request.operation == "migration":
            migration = self._classify_migration(token, journal, previous)
            if migration is not None:
                return migration
            journal = self.state.read_transaction(token, request.transaction_id)

        candidate: Optional[Candidate] = None
        active_commit: Optional[lifecycle_state.ActiveSnapshot] = None
        host_effect_started = False
        try:
            candidate = self.candidates.build_candidate(request)
            self._validate_candidate(request, candidate)
            staged = self.candidates.staged_health(candidate)
            if not staged.exact:
                raise AdapterFailure(
                    "candidate staged health was not exact",
                    observations=staged.observations,
                    retained_paths=staged.retained_paths,
                    recovery=staged.recovery,
                )
            journal = self.state.advance_transaction(
                token,
                journal,
                phase="candidate_ready",
                observations=staged.observations,
                retained_paths=staged.retained_paths,
                recovery=staged.recovery,
                owned_paths=self._new_owned_paths(journal, candidate.owned_paths),
            )

            observed = self.host.observe_previous(previous.record)
            if not observed.exact:
                raise AdapterFailure(
                    "previous external state could not be observed exactly",
                    observations=observed.observations,
                    retained_paths=observed.retained_paths,
                    recovery=observed.recovery,
                    uncertain=True,
                )
            journal = self.state.advance_transaction(
                token,
                journal,
                observations=observed.observations,
                retained_paths=observed.retained_paths,
                recovery=observed.recovery,
            )

            marketplace = self.host.provision_marketplace(candidate)
            self._validate_provision("marketplace", marketplace)
            host_effect_started = bool(marketplace.effects)
            journal = self._record_provisional(token, journal, marketplace)
            if not marketplace.exact:
                raise AdapterFailure(
                    "marketplace provisioning or read-back failed",
                    observations=marketplace.observations,
                    effects=(),
                    retained_paths=marketplace.retained_paths,
                    recovery=marketplace.recovery,
                    uncertain=not bool(marketplace.effects),
                )

            plugin = self.host.provision_plugin(candidate)
            self._validate_provision("plugin", plugin)
            host_effect_started = host_effect_started or bool(plugin.effects)
            journal = self._record_provisional(token, journal, plugin)
            if not plugin.exact:
                raise AdapterFailure(
                    "plugin provisioning or read-back failed",
                    observations=plugin.observations,
                    retained_paths=plugin.retained_paths,
                    recovery=plugin.recovery,
                    uncertain=not host_effect_started,
                )

            read_back = self.host.read_back_candidate(candidate)
            if not read_back.exact:
                raise AdapterFailure(
                    "candidate host read-back failed",
                    observations=read_back.observations,
                    retained_paths=read_back.retained_paths,
                    recovery=read_back.recovery,
                )
            journal = self.state.advance_transaction(
                token,
                journal,
                phase="host_read_back",
                observations=read_back.observations,
                retained_paths=read_back.retained_paths,
                recovery=read_back.recovery,
            )

            active_commit = self.state.compare_and_set_active(
                token,
                previous,
                release_id=candidate.release_id,
                release_path=candidate.release_path,
                receipt_sha256=candidate.receipt_sha256,
                dispatcher_protocol=lifecycle_state.DISPATCHER_PROTOCOL,
                transaction_id=request.transaction_id,
            )
            journal = self.state.advance_transaction(
                token, journal, phase="active_committed"
            )
            proof = self.host.public_proof(active_commit.record)
            if not proof.exact:
                raise AdapterFailure(
                    "public CLI/MCP startup proof failed",
                    observations=proof.observations,
                    retained_paths=proof.retained_paths,
                    recovery=proof.recovery,
                )
            journal = self.state.advance_transaction(
                token,
                journal,
                phase="public_proof",
                observations=proof.observations,
                retained_paths=proof.retained_paths,
                recovery=proof.recovery,
            )
            assert active_commit.record is not None
            inactive_cleanup = self._safe_step(
                lambda: self.candidates.cleanup_inactive(
                    previous.record, active_commit.record
                )
            )
            journal = self._append_evidence(token, journal, inactive_cleanup)
            terminal = self.state.finish_transaction(token, journal, "committed")
            return LifecycleResult(
                terminal.journal.transaction_id, "committed", active_commit
            )
        except Exception as exc:
            failure = self._as_failure(exc, request.transaction_id)
            journal = self._append_failure(token, journal, failure)
            try:
                target_is_active = self._is_target_record(
                    self.state.read_active(token).record, journal.journal
                )
            except lifecycle_state.LifecycleStateError as active_error:
                return self._finish_partial(
                    token,
                    journal,
                    "active authority could not be observed after failure: "
                    + self._bounded_detail(active_error),
                )
            if active_commit is not None or target_is_active:
                return self._rollback_after_active(token, journal, failure)
            if host_effect_started or self._has_applied_effect(journal):
                return self._rollback_before_active(token, journal, failure)
            return self._finish_without_host_effect(token, journal, failure)

    def _precondition(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        request: ActivationRequest,
        previous: lifecycle_state.ActiveSnapshot,
    ) -> Optional[LifecycleResult]:
        invalid = None
        if request.operation == "install" and previous.present:
            invalid = "fresh install requires absent active authority"
        elif request.operation in {"repair", "upgrade"} and not previous.present:
            invalid = f"{request.operation} requires an active release"
        elif request.operation == "migration" and previous.present:
            invalid = "migration requires absence of artifact active authority"
        if invalid is None:
            return None
        evidence = lifecycle_state.ExternalObservation(
            "active-authority", "changed", previous.digest, invalid
        )
        journal = self.state.advance_transaction(
            token, journal, observations=(evidence,)
        )
        proof = self._safe_step(lambda: self.host.public_proof(previous.record))
        journal = self._append_evidence(token, journal, proof)
        outcome = "rolled_back" if proof.exact else "partial"
        journal = self.state.finish_transaction(token, journal, outcome)
        return LifecycleResult(
            journal.journal.transaction_id,
            outcome,
            previous,
            detail=invalid,
        )

    def _repair_decision(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        request: ActivationRequest,
        previous: lifecycle_state.ActiveSnapshot,
    ) -> Optional[LifecycleResult]:
        assert previous.record is not None
        try:
            attestation = self.candidates.attest_active(previous.record)
        except Exception as exc:
            failure = self._as_failure(exc, request.transaction_id)
            journal = self._append_failure(token, journal, failure)
            return self._finish_without_host_effect(token, journal, failure, partial=True)
        journal = self.state.advance_transaction(
            token, journal, observations=attestation.observations
        )
        if not attestation.identity_proven or attestation.envelope is None:
            failure = AdapterFailure(
                "active receipt envelope could not be proven for repair",
                observations=(
                    lifecycle_state.ExternalObservation(
                        "active-receipt", "unknown", detail="repair identity unavailable"
                    ),
                ),
                recovery=("Run exact-version recovery after inspecting active receipt drift.",),
                uncertain=True,
            )
            journal = self._append_failure(token, journal, failure)
            return self._finish_without_host_effect(token, journal, failure, partial=True)
        if attestation.version == request.version and attestation.envelope != request.envelope:
            proof = self._safe_step(lambda: self.host.public_proof(previous.record))
            journal = self._append_evidence(token, journal, proof)
            outcome = "rolled_back" if proof.exact else "partial"
            terminal = self.state.finish_transaction(
                token,
                journal,
                outcome,
                recovery=(
                    "Use the original exact-version digest envelope; same-version bytes changed.",
                ),
            )
            return LifecycleResult(
                terminal.journal.transaction_id,
                outcome,
                previous,
                detail="same-version release digest envelope changed",
            )
        if attestation.version != request.version:
            failure = AdapterFailure(
                "repair bootstrap version does not match active release",
                observations=(
                    lifecycle_state.ExternalObservation(
                        "active-version", "changed", detail=str(attestation.version)
                    ),
                ),
            )
            journal = self._append_failure(token, journal, failure)
            return self._finish_without_host_effect(token, journal, failure)
        if not attestation.reusable:
            return None

        read_back = self._safe_step(lambda: self.host.read_back_active(previous.record))
        journal = self._append_evidence(token, journal, read_back)
        proof = self._safe_step(lambda: self.host.public_proof(previous.record))
        journal = self._append_evidence(token, journal, proof)
        if read_back.exact and proof.exact:
            terminal = self.state.finish_transaction(token, journal, "committed")
            return LifecycleResult(
                terminal.journal.transaction_id,
                "committed",
                previous,
                reused=True,
            )
        # A nominally reusable candidate failed complete startup/read-back and
        # is therefore drifted; build a fresh candidate from the same envelope.
        return None

    def _classify_migration(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        previous: lifecycle_state.ActiveSnapshot,
    ) -> Optional[LifecycleResult]:
        if self.migration_classifier is None:
            classification = MigrationClassification(
                False,
                (
                    lifecycle_state.ExternalObservation(
                        "legacy-installation", "unknown", detail="classifier unavailable"
                    ),
                ),
                ("Use the frozen immediate-predecessor migration environment.",),
            )
        else:
            try:
                classification = self.migration_classifier.classify()
            except Exception as exc:
                classification = MigrationClassification(
                    False,
                    (
                        lifecycle_state.ExternalObservation(
                            "legacy-installation", "unknown", detail=self._bounded_detail(exc)
                        ),
                    ),
                    ("Inspect installed predecessor observations without reading its checkout.",),
                )
        journal = self.state.advance_transaction(
            token,
            journal,
            observations=classification.observations,
            recovery=classification.recovery,
        )
        if classification.exact_predecessor:
            return None
        # No artifact authority exists yet and the frozen classifier could not
        # prove one predecessor identity.  Calling this a rollback would assert
        # that an immediate previous authority was known and re-proven; retain
        # the ambiguity instead and stop before identity-specific mutation.
        terminal = self.state.finish_transaction(token, journal, "partial")
        return LifecycleResult(
            terminal.journal.transaction_id,
            "partial",
            previous,
            detail="legacy installation is unsupported or ambiguous",
        )

    @staticmethod
    def _validate_candidate(request: ActivationRequest, candidate: Candidate) -> None:
        if (
            candidate.version != request.version
            or candidate.release_id != request.release_id
            or Path(candidate.release_path) != Path(request.release_path)
            or candidate.envelope != request.envelope
        ):
            raise AdapterFailure(
                "candidate identity disagrees with the verified target",
                observations=(
                    lifecycle_state.ExternalObservation(
                        "candidate-identity", "changed", detail="request/candidate mismatch"
                    ),
                ),
            )

    @staticmethod
    def _validate_provision(kind: str, evidence: StepEvidence) -> None:
        if not any(effect.kind == kind and effect.applied for effect in evidence.effects):
            raise AdapterFailure(
                f"{kind} provisioning did not report its exact applied effect",
                observations=evidence.observations,
                effects=evidence.effects,
                retained_paths=evidence.retained_paths,
                recovery=evidence.recovery,
                uncertain=True,
            )

    @staticmethod
    def _new_owned_paths(
        journal: lifecycle_state.TransactionSnapshot, paths: Sequence[str]
    ) -> Tuple[str, ...]:
        existing = set(journal.journal.owned_paths)
        return tuple(path for path in paths if path not in existing)

    def _record_provisional(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        evidence: StepEvidence,
    ) -> lifecycle_state.TransactionSnapshot:
        return self.state.advance_transaction(
            token,
            journal,
            phase="provisional_activation",
            observations=evidence.observations,
            provisional_effects=evidence.effects,
            retained_paths=evidence.retained_paths,
            recovery=evidence.recovery,
        )

    def _append_evidence(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        evidence: StepEvidence,
    ) -> lifecycle_state.TransactionSnapshot:
        return self.state.advance_transaction(
            token,
            journal,
            observations=evidence.observations,
            provisional_effects=evidence.effects,
            retained_paths=evidence.retained_paths,
            recovery=evidence.recovery,
        )

    def _append_failure(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        failure: AdapterFailure,
    ) -> lifecycle_state.TransactionSnapshot:
        observations = failure.observations or (
            lifecycle_state.ExternalObservation(
                "lifecycle-step", "unknown", detail=self._bounded_detail(failure)
            ),
        )
        return self.state.advance_transaction(
            token,
            journal,
            observations=observations,
            provisional_effects=failure.effects,
            retained_paths=failure.retained_paths,
            recovery=failure.recovery,
        )

    def _finish_without_host_effect(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        failure: AdapterFailure,
        *,
        partial: bool = False,
    ) -> LifecycleResult:
        cleanup = self._safe_step(lambda: self.candidates.cleanup_owned(journal.journal))
        journal = self._append_evidence(token, journal, cleanup)
        proof = self._safe_step(
            lambda: self.host.public_proof(journal.journal.previous_authority)
        )
        journal = self._append_evidence(token, journal, proof)
        outcome = (
            "rolled_back"
            if not partial and not failure.uncertain and cleanup.exact and proof.exact
            else "partial"
        )
        terminal = self.state.finish_transaction(token, journal, outcome)
        return LifecycleResult(
            terminal.journal.transaction_id,
            outcome,
            self.state.read_active(token),
            detail=self._bounded_detail(failure),
        )

    def _rollback_before_active(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        failure: AdapterFailure,
    ) -> LifecycleResult:
        journal = self.state.advance_transaction(token, journal, phase="restoring")
        restoration = self._safe_step(
            lambda: self.host.restore_previous(journal.journal)
        )
        journal = self._append_evidence(token, journal, restoration)
        proof = self._safe_step(
            lambda: self.host.public_proof(journal.journal.previous_authority)
        )
        journal = self._append_evidence(token, journal, proof)
        cleanup = self._safe_step(lambda: self.candidates.cleanup_owned(journal.journal))
        journal = self._append_evidence(token, journal, cleanup)
        outcome = "rolled_back" if restoration.exact and proof.exact else "partial"
        terminal = self.state.finish_transaction(token, journal, outcome)
        return LifecycleResult(
            terminal.journal.transaction_id,
            outcome,
            self.state.read_active(token),
            detail=self._bounded_detail(failure),
        )

    def _rollback_after_active(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        failure: AdapterFailure,
    ) -> LifecycleResult:
        journal = self.state.advance_transaction(token, journal, phase="restoring")
        current = self.state.read_active(token)
        if not self._is_target_record(current.record, journal.journal):
            return self._finish_partial(
                token,
                journal,
                "active authority changed before compensating CAS; no host restoration attempted",
            )
        try:
            if journal.journal.previous_authority is None:
                restored = self.state.compare_and_delete_active(token, current)
            else:
                restored = self.state.restore_active(
                    token,
                    current,
                    journal.journal.previous_authority,
                    transaction_id=journal.journal.transaction_id,
                )
        except lifecycle_state.LifecycleStateError as exc:
            return self._finish_partial(token, journal, self._bounded_detail(exc))

        host_restore = self._safe_step(
            lambda: self.host.restore_previous(journal.journal)
        )
        journal = self._append_evidence(token, journal, host_restore)
        if not host_restore.exact:
            return self._finish_partial(
                token, journal, "previous external state could not be proven"
            )
        proof = self._safe_step(
            lambda: self.host.public_proof(journal.journal.previous_authority)
        )
        journal = self._append_evidence(token, journal, proof)
        if not proof.exact:
            return self._finish_partial(
                token, journal, "previous public startup could not be proven"
            )
        cleanup = self._safe_step(lambda: self.candidates.cleanup_owned(journal.journal))
        journal = self._append_evidence(token, journal, cleanup)
        terminal = self.state.finish_transaction(token, journal, "rolled_back")
        return LifecycleResult(
            terminal.journal.transaction_id,
            "rolled_back",
            restored,
            detail=self._bounded_detail(failure),
        )

    def _finish_partial(
        self,
        token: object,
        journal: lifecycle_state.TransactionSnapshot,
        detail: str,
    ) -> LifecycleResult:
        terminal = self.state.finish_transaction(
            token,
            journal,
            "partial",
            observations=(
                lifecycle_state.ExternalObservation(
                    "recovery", "unknown", detail=detail
                ),
            ),
            recovery=(
                "Stop automatic identity-specific mutation and inspect the recorded observations.",
            ),
        )
        return LifecycleResult(
            terminal.journal.transaction_id,
            "partial",
            self.state.read_active(token),
            detail=detail,
        )

    def _recover_one(
        self, token: object, pending: lifecycle_state.TransactionSnapshot
    ) -> LifecycleResult:
        if pending.journal.operation not in ACTIVATION_OPERATIONS:
            terminal = self.state.finish_transaction(
                token,
                pending,
                "partial",
                observations=(
                    lifecycle_state.ExternalObservation(
                        "transaction-recovery",
                        "unknown",
                        detail="activation machine cannot classify this operation",
                    ),
                ),
                recovery=(
                    "Resume this operation with its version-matched lifecycle driver.",
                ),
            )
            return LifecycleResult(
                terminal.journal.transaction_id,
                "partial",
                self.state.read_active(token),
            )
        journal = self.state.advance_transaction(
            token,
            pending,
            phase="recovering",
            observations=(
                lifecycle_state.ExternalObservation(
                    "transaction-recovery",
                    "exact",
                    detail=f"resuming {pending.journal.phase}",
                ),
            ),
        )
        current = self.state.read_active(token)
        if self._is_target_record(current.record, journal.journal):
            read_back = self._safe_step(lambda: self.host.read_back_active(current.record))
            journal = self._append_evidence(token, journal, read_back)
            proof = self._safe_step(lambda: self.host.public_proof(current.record))
            journal = self._append_evidence(token, journal, proof)
            if read_back.exact and proof.exact:
                assert current.record is not None
                inactive_cleanup = self._safe_step(
                    lambda: self.candidates.cleanup_inactive(
                        journal.journal.previous_authority, current.record
                    )
                )
                journal = self._append_evidence(token, journal, inactive_cleanup)
                terminal = self.state.finish_transaction(token, journal, "committed")
                return LifecycleResult(
                    terminal.journal.transaction_id, "committed", current
                )
            failure = AdapterFailure("interrupted target activation did not pass proof")
            return self._rollback_after_active(token, journal, failure)

        if self._is_previous_or_expected(current, journal.journal):
            if self._has_applied_effect(journal):
                restoration = self._safe_step(
                    lambda: self.host.restore_previous(journal.journal)
                )
                journal = self._append_evidence(token, journal, restoration)
                if not restoration.exact:
                    return self._finish_partial(
                        token, journal, "interrupted host effects could not be restored"
                    )
            proof = self._safe_step(
                lambda: self.host.public_proof(journal.journal.previous_authority)
            )
            journal = self._append_evidence(token, journal, proof)
            if not proof.exact:
                return self._finish_partial(
                    token, journal, "previous authority could not be proven during recovery"
                )
            cleanup = self._safe_step(
                lambda: self.candidates.cleanup_owned(journal.journal)
            )
            journal = self._append_evidence(token, journal, cleanup)
            terminal = self.state.finish_transaction(token, journal, "rolled_back")
            return LifecycleResult(
                terminal.journal.transaction_id, "rolled_back", current
            )
        return self._finish_partial(
            token,
            journal,
            "active authority matches neither the interrupted target nor its immediate previous authority",
        )

    @staticmethod
    def _has_applied_effect(journal: lifecycle_state.TransactionSnapshot) -> bool:
        return any(effect.applied for effect in journal.journal.provisional_effects)

    @staticmethod
    def _is_target_record(
        active: Optional[lifecycle_state.ActiveRecord],
        journal: lifecycle_state.TransactionJournal,
    ) -> bool:
        target = journal.target_release
        return bool(
            active is not None
            and target is not None
            and active.transaction_id == journal.transaction_id
            and active.release_id == target.release_id
            and Path(active.release_path) == Path(target.release_path)
        )

    @staticmethod
    def _is_previous_or_expected(
        current: lifecycle_state.ActiveSnapshot,
        journal: lifecycle_state.TransactionJournal,
    ) -> bool:
        expected = journal.expected_active
        if (
            current.generation == expected.generation
            and current.digest == expected.digest
            and current.present == expected.present
        ):
            return True
        previous = journal.previous_authority
        if previous is None:
            return not current.present and current.generation > expected.generation
        if current.record is None:
            return False
        return (
            current.generation > expected.generation
            and current.record.transaction_id == previous.transaction_id
            and current.record.release_id == previous.release_id
            and Path(current.record.release_path) == Path(previous.release_path)
            and current.record.receipt_sha256 == previous.receipt_sha256
            and current.record.dispatcher_protocol == previous.dispatcher_protocol
        )

    @staticmethod
    def _safe_step(callback) -> StepEvidence:
        try:
            evidence = callback()
            if not isinstance(evidence, StepEvidence):
                raise TypeError("adapter returned a non-StepEvidence value")
            return evidence
        except AdapterFailure as exc:
            observations = exc.observations or (
                lifecycle_state.ExternalObservation(
                    "adapter-step", "unknown", detail=LifecycleMachine._bounded_detail(exc)
                ),
            )
            return StepEvidence(
                False,
                observations,
                exc.effects,
                exc.retained_paths,
                exc.recovery,
            )
        except Exception as exc:
            return StepEvidence(
                False,
                (
                    lifecycle_state.ExternalObservation(
                        "adapter-step", "unknown", detail=LifecycleMachine._bounded_detail(exc)
                    ),
                ),
                recovery=("Inspect the adapter failure before retrying.",),
            )

    @staticmethod
    def _as_failure(exc: BaseException, transaction_id: str) -> AdapterFailure:
        if isinstance(exc, AdapterFailure):
            return exc
        return AdapterFailure(
            f"transaction {transaction_id}: {LifecycleMachine._bounded_detail(exc)}",
            observations=(
                lifecycle_state.ExternalObservation(
                    "lifecycle-step",
                    "unknown",
                    detail=LifecycleMachine._bounded_detail(exc),
                ),
            ),
            recovery=("Inspect the recorded failure before rerunning the exact operation.",),
            uncertain=False,
        )

    @staticmethod
    def _bounded_detail(exc: BaseException | str) -> str:
        value = str(exc).replace("\x00", "")
        encoded = value.encode("utf-8")
        if len(encoded) <= 1024:
            return value or "unspecified lifecycle failure"
        return encoded[:1024].decode("utf-8", errors="ignore")


__all__ = [
    "ACTIVATION_OPERATIONS",
    "ActiveAttestation",
    "ActivationRequest",
    "AdapterFailure",
    "ArtifactEnvelope",
    "Candidate",
    "CandidateAdapter",
    "HostAdapter",
    "LifecycleMachine",
    "LifecycleResult",
    "MigrationClassification",
    "MigrationClassifier",
    "StepEvidence",
]
