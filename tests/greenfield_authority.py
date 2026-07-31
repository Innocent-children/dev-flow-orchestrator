"""Focused helpers for the durable conversation-confirmation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
from pathlib import Path
from typing import Optional

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError


_PENDING_CODES = frozenset(
    ("CONFIRMATION_REQUIRED", "CONFIRMATION_PENDING")
)


@dataclass(frozen=True)
class PendingConfirmation:
    kind: str
    task_id: str
    request_id: str
    session_id: str
    request_turn_id: str
    expected_revision: Optional[int] = None
    action_id: Optional[str] = None
    payload: Optional[dict] = None
    binding: Optional[str] = None
    mode: Optional[str] = None


class ConversationAuthority:
    """Drive only real controller request, prompt and exact-retry boundaries."""

    def __init__(
        self,
        controller: Controller,
        cwd: Path,
        *,
        session_id: str = "focused-conversation-session",
    ) -> None:
        self.controller = controller
        self.cwd = str(Path(cwd).resolve())
        self.session_id = session_id
        self._turns = itertools.count(1)

    def _turn(self, purpose: str) -> str:
        return "{}-{}".format(purpose, next(self._turns))

    @staticmethod
    def _pending_packet(exc: DevFlowError) -> dict:
        if exc.code not in _PENDING_CODES:
            raise exc
        packet = exc.details.get("confirmation")
        if not isinstance(packet, dict):
            raise AssertionError("pending response lacks a confirmation packet")
        request_id = packet.get("request_id")
        if (
            not isinstance(request_id, str)
            or not request_id.startswith("confirm-")
            or packet.get("status") != "PENDING"
        ):
            raise AssertionError("pending confirmation packet is malformed")
        return packet

    def request_action(
        self,
        task_id: str,
        expected_revision: int,
        action_id: str,
        payload: dict,
    ) -> PendingConfirmation:
        request_turn_id = self._turn("action-request")
        try:
            self.controller.apply(
                task_id,
                expected_revision,
                action_id,
                payload,
                session_id=self.session_id,
                request_turn_id=request_turn_id,
            )
        except DevFlowError as exc:
            packet = self._pending_packet(exc)
        else:
            raise AssertionError(
                "authority-gated action applied without confirmation"
            )
        return PendingConfirmation(
            kind="action",
            task_id=task_id,
            request_id=packet["request_id"],
            session_id=self.session_id,
            request_turn_id=request_turn_id,
            expected_revision=expected_revision,
            action_id=action_id,
            payload=dict(payload),
        )

    def request_recovery(
        self,
        task_id: str,
        binding: str,
        mode: str,
    ) -> PendingConfirmation:
        request_turn_id = self._turn("recovery-request")
        try:
            self.controller.recover_effect(
                task_id,
                binding,
                mode,
                session_id=self.session_id,
                request_turn_id=request_turn_id,
            )
        except DevFlowError as exc:
            packet = self._pending_packet(exc)
        else:
            raise AssertionError(
                "actionable recovery completed without confirmation"
            )
        return PendingConfirmation(
            kind="recovery",
            task_id=task_id,
            request_id=packet["request_id"],
            session_id=self.session_id,
            request_turn_id=request_turn_id,
            binding=binding,
            mode=mode,
        )

    def decide(
        self,
        pending: PendingConfirmation,
        *,
        approve: bool,
    ) -> dict:
        verb = "approve" if approve else "deny"
        result = self.controller.observe_user_prompt(
            session_id=pending.session_id,
            turn_id=self._turn("user-decision"),
            cwd=self.cwd,
            prompt="{} {}".format(verb, pending.request_id),
        )
        expected = "CONFIRMED" if approve else "DENIED"
        if (
            result.get("status") != expected
            or result.get("request_id") != pending.request_id
        ):
            raise AssertionError(
                "user-prompt decision did not target the exact request"
            )
        return result

    def retry_action(self, pending: PendingConfirmation):
        if (
            pending.kind != "action"
            or pending.expected_revision is None
            or pending.action_id is None
            or pending.payload is None
        ):
            raise AssertionError("pending record is not an action request")
        return self.controller.apply(
            pending.task_id,
            pending.expected_revision,
            pending.action_id,
            pending.payload,
            session_id=pending.session_id,
            request_turn_id=pending.request_turn_id,
        )

    def retry_recovery(self, pending: PendingConfirmation) -> dict:
        if (
            pending.kind != "recovery"
            or pending.binding is None
            or pending.mode is None
        ):
            raise AssertionError("pending record is not a recovery request")
        return self.controller.recover_effect(
            pending.task_id,
            pending.binding,
            pending.mode,
            session_id=pending.session_id,
            request_turn_id=pending.request_turn_id,
        )

    def apply(
        self,
        task_id: str,
        expected_revision: int,
        action_id: str,
        payload: dict,
    ):
        """Apply a normal action or complete its exact confirmation lifecycle."""

        request_turn_id = self._turn("action-request")
        try:
            return self.controller.apply(
                task_id,
                expected_revision,
                action_id,
                payload,
                session_id=self.session_id,
                request_turn_id=request_turn_id,
            )
        except DevFlowError as exc:
            packet = self._pending_packet(exc)
        pending = PendingConfirmation(
            kind="action",
            task_id=task_id,
            request_id=packet["request_id"],
            session_id=self.session_id,
            request_turn_id=request_turn_id,
            expected_revision=expected_revision,
            action_id=action_id,
            payload=dict(payload),
        )
        self.decide(pending, approve=True)
        return self.retry_action(pending)

    def recover(
        self,
        task_id: str,
        binding: str,
        mode: str,
    ) -> dict:
        pending = self.request_recovery(task_id, binding, mode)
        self.decide(pending, approve=True)
        return self.retry_recovery(pending)
