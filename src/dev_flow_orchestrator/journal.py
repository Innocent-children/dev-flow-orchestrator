"""Minimal durable claim, receipt and recovery journal for external effects."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Callable, Mapping, Optional

from .filesystem import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
)
from .model import DevFlowError, MutationPlan, canonical_json_bytes, validate_task_id


_BINDING_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_PHASES = frozenset({"ABANDONED", "COMMITTED"})
_PHASES = frozenset(
    {"CLAIMED", "RECEIPT", "QUARANTINED", "ABANDONED", "COMMITTED"}
)
_RECORD_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "action_id",
        "expected_revision",
        "plan_binding",
        "authority_id",
        "authority_binding_digest",
        "actor_id",
        "effect_kind",
        "attempt",
        "phase",
        "payload",
        "requests",
        "receipt",
        "error",
        "claimed_at",
        "updated_at",
        "committed_revision",
        "recovery_claim",
        "history",
    }
)
_HISTORY_FIELDS = frozenset(
    {
        "attempt",
        "phase",
        "authority_id",
        "authority_binding_digest",
        "actor_id",
        "recovery_claim",
        "claimed_at",
        "updated_at",
    }
)
_RECOVERY_CLAIM_FIELDS = frozenset(
    {
        "request_id",
        "binding_digest",
        "mode",
        "effect_attempt",
        "evidence_digest",
        "claimed_at",
    }
)


def _strict_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate effect journal object key")
        value[key] = item
    return value


class EffectJournal:
    """One durable record per action/revision plan binding."""

    def __init__(self, data_root: Path) -> None:
        self.root = data_root / "effects"
        self.locks = data_root / "locks" / "effects"
        self.fences = data_root / "locks" / "effect-executions"

    @staticmethod
    def _validate_binding(binding: str) -> str:
        if not isinstance(binding, str) or not _BINDING_PATTERN.fullmatch(binding):
            raise DevFlowError(
                "EFFECT_BINDING_INVALID",
                "effect binding must be a lowercase SHA-256 value",
            )
        return binding

    def _task_root(self, task_id: str) -> Path:
        return self.root / validate_task_id(task_id)

    def _path(self, task_id: str, binding: str) -> Path:
        return self._task_root(task_id) / (
            self._validate_binding(binding) + ".json"
        )

    def _lock(self, task_id: str, binding: str):
        validate_task_id(task_id)
        self._validate_binding(binding)
        ensure_private_directory(self.root)
        ensure_private_directory(self.locks)
        return exclusive_file_lock(
            self.locks / "{}-{}.lock".format(task_id, binding)
        )

    def execution_fence(self, task_id: str, binding: str):
        """Serialize dispatch and recovery for one exact effect execution.

        Callers acquire this fence before invoking journal methods. Journal
        methods only acquire the separate record lock, so the lock order is
        always execution fence followed by record lock.
        """

        validate_task_id(task_id)
        self._validate_binding(binding)
        ensure_private_directory(self.fences)
        return exclusive_file_lock(
            self.fences / "{}-{}.lock".format(task_id, binding)
        )

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            value = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_strict_json_object,
            )
        except FileNotFoundError as exc:
            raise DevFlowError(
                "EFFECT_NOT_FOUND",
                "effect execution does not exist",
            ) from exc
        except (UnicodeError, ValueError) as exc:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal is not valid current JSON",
            ) from exc
        if not isinstance(value, dict):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal must be an object",
            )
        return value

    @staticmethod
    def _valid_integer(value: object, *, minimum: int = 0) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= minimum
        )

    @classmethod
    def _validate_recovery_claim(
        cls,
        claim: object,
        *,
        effect_attempt: int,
    ) -> None:
        if claim is None:
            return
        if (
            not isinstance(claim, dict)
            or set(claim) != _RECOVERY_CLAIM_FIELDS
            or not isinstance(claim.get("request_id"), str)
            or not claim["request_id"].startswith("confirm-")
            or not isinstance(claim.get("binding_digest"), str)
            or not _BINDING_PATTERN.fullmatch(claim["binding_digest"])
            or claim.get("mode") not in {"settle", "abandon"}
            or claim.get("effect_attempt") != effect_attempt
            or not isinstance(claim.get("evidence_digest"), str)
            or not _BINDING_PATTERN.fullmatch(claim["evidence_digest"])
            or not isinstance(claim.get("claimed_at"), str)
            or not claim["claimed_at"]
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect recovery claim is malformed or misbound",
            )

    @classmethod
    def validate_record(
        cls,
        task_id: str,
        binding: str,
        record: Mapping[str, object],
    ) -> dict:
        """Validate the complete durable journal schema and file identity."""

        validate_task_id(task_id)
        cls._validate_binding(binding)
        if (
            not isinstance(record, dict)
            or set(record) != _RECORD_FIELDS
            or record.get("schema") != "dev-flow-v4-effect-journal/v1"
            or record.get("task_id") != task_id
            or record.get("plan_binding") != binding
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal schema or identity is invalid",
            )
        expected_revision = record.get("expected_revision")
        attempt = record.get("attempt")
        phase = record.get("phase")
        committed_revision = record.get("committed_revision")
        receipt = record.get("receipt")
        error = record.get("error")
        if (
            not isinstance(record.get("action_id"), str)
            or not record["action_id"]
            or not cls._valid_integer(expected_revision)
            or not isinstance(record.get("authority_id"), str)
            or not record["authority_id"].startswith("confirm-")
            or not isinstance(record.get("authority_binding_digest"), str)
            or not _BINDING_PATTERN.fullmatch(
                record["authority_binding_digest"]
            )
            or not isinstance(record.get("actor_id"), str)
            or not record["actor_id"]
            or not isinstance(record.get("effect_kind"), str)
            or not record["effect_kind"]
            or not cls._valid_integer(attempt, minimum=1)
            or phase not in _PHASES
            or not isinstance(record.get("payload"), dict)
            or not isinstance(record.get("requests"), dict)
            or not record["requests"]
            or (receipt is not None and not isinstance(receipt, dict))
            or (error is not None and not isinstance(error, dict))
            or not isinstance(record.get("claimed_at"), str)
            or not record["claimed_at"]
            or not isinstance(record.get("updated_at"), str)
            or not record["updated_at"]
            or (
                committed_revision is not None
                and not cls._valid_integer(committed_revision, minimum=1)
            )
            or not isinstance(record.get("history"), list)
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal action or lifecycle fields are invalid",
            )
        if phase == "CLAIMED" and (receipt is not None or error is not None):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "claimed effect journal has terminal evidence",
            )
        if phase == "RECEIPT" and (
            not isinstance(receipt, dict) or error is not None
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "receipt effect journal is incomplete",
            )
        if phase == "QUARANTINED" and not isinstance(error, dict):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "quarantined effect journal lacks its error",
            )
        if phase == "ABANDONED" and (
            receipt is not None or committed_revision is not None
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "abandoned effect journal contains settlement evidence",
            )
        if phase == "COMMITTED" and (
            not isinstance(receipt, dict)
            or committed_revision != expected_revision + 1
            or error is not None
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "committed effect journal is incomplete or misbound",
            )
        if phase != "COMMITTED" and committed_revision is not None:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "non-committed effect journal has a committed revision",
            )
        recovery_claim = record.get("recovery_claim")
        cls._validate_recovery_claim(
            recovery_claim,
            effect_attempt=attempt,
        )
        if phase == "ABANDONED" and (
            not isinstance(recovery_claim, dict)
            or recovery_claim.get("mode") != "abandon"
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "abandoned effect journal lacks its exact recovery claim",
            )
        if (
            phase == "COMMITTED"
            and isinstance(recovery_claim, dict)
            and recovery_claim.get("mode") != "settle"
        ):
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "committed effect journal has a conflicting recovery claim",
            )
        history = record["history"]
        if len(history) != attempt - 1:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect attempt history length is invalid",
            )
        for expected_attempt, item in enumerate(history, start=1):
            if (
                not isinstance(item, dict)
                or set(item) != _HISTORY_FIELDS
                or item.get("attempt") != expected_attempt
                or item.get("phase") != "ABANDONED"
                or not isinstance(item.get("authority_id"), str)
                or not item["authority_id"].startswith("confirm-")
                or not isinstance(
                    item.get("authority_binding_digest"),
                    str,
                )
                or not _BINDING_PATTERN.fullmatch(
                    item["authority_binding_digest"]
                )
                or not isinstance(item.get("actor_id"), str)
                or not item["actor_id"]
                or not isinstance(item.get("claimed_at"), str)
                or not item["claimed_at"]
                or not isinstance(item.get("updated_at"), str)
                or not item["updated_at"]
            ):
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "effect attempt history is malformed",
                )
            cls._validate_recovery_claim(
                item.get("recovery_claim"),
                effect_attempt=expected_attempt,
            )
            if (
                not isinstance(item.get("recovery_claim"), dict)
                or item["recovery_claim"].get("mode") != "abandon"
            ):
                raise DevFlowError(
                    "EFFECT_JOURNAL_INVALID",
                    "abandoned attempt history lacks its recovery claim",
                )
        return dict(record)

    @staticmethod
    def _write(path: Path, value: Mapping[str, object]) -> None:
        try:
            payload = canonical_json_bytes(dict(value)) + b"\n"
        except (TypeError, ValueError) as exc:
            raise DevFlowError(
                "EFFECT_JOURNAL_INVALID",
                "effect journal contains a non-JSON value",
            ) from exc
        atomic_write_bytes(path, payload)

    def claim(
        self,
        *,
        task_id: str,
        plan: MutationPlan,
        payload: Mapping[str, object],
        requests: Mapping[str, object],
        authority_binding_digest: str,
        expected_attempt: int,
        timestamp: str,
    ) -> dict:
        binding = plan.binding
        path = self._path(task_id, binding)
        with self._lock(task_id, binding):
            history = []
            attempt = 1
            if path.exists():
                previous = self.validate_record(
                    task_id,
                    binding,
                    self._read(path),
                )
                if previous.get("phase") != "ABANDONED":
                    raise DevFlowError(
                        "EFFECT_ALREADY_CLAIMED",
                        "the exact action plan already has a durable effect claim",
                        details={
                            "binding": binding,
                            "phase": previous.get("phase"),
                        },
                    )
                history = list(previous.get("history") or [])
                history.append(
                    {
                        key: previous.get(key)
                        for key in (
                            "attempt",
                            "phase",
                            "authority_id",
                            "authority_binding_digest",
                            "actor_id",
                            "recovery_claim",
                            "claimed_at",
                            "updated_at",
                        )
                    }
                )
                attempt = int(previous.get("attempt", 1)) + 1
            if attempt != expected_attempt:
                raise DevFlowError(
                    "EFFECT_ATTEMPT_CONFLICT",
                    "effect attempt no longer matches the confirmed request",
                    details={
                        "expected_attempt": expected_attempt,
                        "actual_attempt": attempt,
                    },
                )
            record = {
                "schema": "dev-flow-v4-effect-journal/v1",
                "task_id": task_id,
                "action_id": plan.action_id,
                "expected_revision": plan.expected_revision,
                "plan_binding": binding,
                "authority_id": plan.authority_id,
                "authority_binding_digest": authority_binding_digest,
                "actor_id": plan.actor_id,
                "effect_kind": plan.effect_kind,
                "attempt": attempt,
                "phase": "CLAIMED",
                "payload": dict(payload),
                "requests": dict(requests),
                "receipt": None,
                "error": None,
                "claimed_at": timestamp,
                "updated_at": timestamp,
                "committed_revision": None,
                "recovery_claim": None,
                "history": history,
            }
            self.validate_record(task_id, binding, record)
            self._write(path, record)
            return record

    def get(self, task_id: str, binding: str) -> dict:
        with self._lock(task_id, binding):
            return self.validate_record(
                task_id,
                binding,
                self._read(self._path(task_id, binding)),
            )

    def update(
        self,
        task_id: str,
        binding: str,
        mutation: Callable[[dict], dict],
    ) -> dict:
        path = self._path(task_id, binding)
        with self._lock(task_id, binding):
            current = self.validate_record(
                task_id,
                binding,
                self._read(path),
            )
            candidate = mutation(dict(current))
            candidate = self.validate_record(task_id, binding, candidate)
            self._write(path, candidate)
            return candidate

    def mark_receipt(
        self,
        task_id: str,
        binding: str,
        receipt: Mapping[str, object],
        timestamp: str,
    ) -> dict:
        def mutation(record: dict) -> dict:
            if record.get("phase") in {"RECEIPT", "COMMITTED"}:
                if record.get("receipt") != dict(receipt):
                    raise DevFlowError(
                        "EFFECT_RECEIPT_CONFLICT",
                        "stored effect receipt conflicts with replay",
                    )
                return record
            if record.get("phase") not in {"CLAIMED", "QUARANTINED"}:
                raise DevFlowError(
                    "EFFECT_PHASE_INVALID",
                    "effect cannot accept a receipt in its current phase",
                )
            record.update(
                phase="RECEIPT",
                receipt=dict(receipt),
                error=None,
                updated_at=timestamp,
            )
            return record

        return self.update(task_id, binding, mutation)

    def mark_quarantined(
        self,
        task_id: str,
        binding: str,
        error: Mapping[str, object],
        timestamp: str,
    ) -> dict:
        def mutation(record: dict) -> dict:
            if record.get("phase") in TERMINAL_PHASES:
                raise DevFlowError(
                    "EFFECT_PHASE_INVALID",
                    "terminal effect cannot enter quarantine",
                )
            record.update(
                phase="QUARANTINED",
                error=dict(error),
                updated_at=timestamp,
            )
            return record

        return self.update(task_id, binding, mutation)

    def mark_committed(
        self,
        task_id: str,
        binding: str,
        revision: int,
        timestamp: str,
    ) -> dict:
        def mutation(record: dict) -> dict:
            if record.get("phase") == "COMMITTED":
                if record.get("committed_revision") != revision:
                    raise DevFlowError(
                        "EFFECT_COMMIT_CONFLICT",
                        "stored effect commit revision conflicts with replay",
                    )
                return record
            if record.get("phase") != "RECEIPT":
                raise DevFlowError(
                    "EFFECT_PHASE_INVALID",
                    "effect requires a stored receipt before commit",
                )
            committed_revision = record.get("committed_revision")
            if (
                committed_revision is not None
                and committed_revision != revision
            ):
                raise DevFlowError(
                    "EFFECT_COMMIT_CONFLICT",
                    "stored effect commit revision conflicts with replay",
                )
            record.update(
                phase="COMMITTED",
                committed_revision=revision,
                updated_at=timestamp,
            )
            return record

        return self.update(task_id, binding, mutation)

    def mark_abandoned(
        self,
        task_id: str,
        binding: str,
        timestamp: str,
    ) -> dict:
        def mutation(record: dict) -> dict:
            if record.get("phase") == "COMMITTED":
                raise DevFlowError(
                    "EFFECT_PHASE_INVALID",
                    "committed effect cannot be abandoned",
                )
            record.update(
                phase="ABANDONED",
                receipt=None,
                updated_at=timestamp,
            )
            return record

        return self.update(task_id, binding, mutation)

    def claim_recovery(
        self,
        task_id: str,
        binding: str,
        request_id: str,
        binding_digest: str,
        mode: str,
        effect_attempt: int,
        evidence_digest: str,
        timestamp: str,
    ) -> dict:
        """Bind one confirmed recovery request before any recovery mutation."""

        def mutation(record: dict) -> dict:
            claim = {
                "request_id": request_id,
                "binding_digest": binding_digest,
                "mode": mode,
                "effect_attempt": effect_attempt,
                "evidence_digest": evidence_digest,
                "claimed_at": timestamp,
            }
            existing = record.get("recovery_claim")
            if isinstance(existing, dict):
                if (
                    existing.get("request_id") == request_id
                    and existing.get("binding_digest") == binding_digest
                    and existing.get("mode") == mode
                    and existing.get("effect_attempt") == effect_attempt
                    and existing.get("evidence_digest") == evidence_digest
                ):
                    return record
                raise DevFlowError(
                    "EFFECT_RECOVERY_ALREADY_CLAIMED",
                    "effect recovery already has a different durable claim",
                    details={
                        "request_id": existing.get("request_id"),
                        "mode": existing.get("mode"),
                    },
                )
            if record.get("phase") in TERMINAL_PHASES:
                raise DevFlowError(
                    "EFFECT_PHASE_INVALID",
                    "terminal effect cannot accept a recovery claim",
                )
            record.update(
                recovery_claim=claim,
                updated_at=timestamp,
            )
            return record

        return self.update(task_id, binding, mutation)

    def inspect(self, task_id: str) -> list:
        task_root = self._task_root(task_id)
        if not task_root.is_dir():
            return []
        records = []
        for path in sorted(task_root.glob("*.json")):
            binding = path.stem
            records.append(
                self.validate_record(
                    task_id,
                    binding,
                    self._read(path),
                )
            )
        return records
