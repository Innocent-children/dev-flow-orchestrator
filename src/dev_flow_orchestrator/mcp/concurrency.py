"""Bounded process coordination; Store locks and CAS remain authoritative."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from typing import Callable, Iterator, Optional

from anyio import from_thread

from .results import MCPRuntimeFailure, cancelled_failure


MAX_PROCESS_OPERATIONS = 4
MUTATION_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.05
CancellationCheck = Callable[[], bool]


@dataclass
class _MutationEntry:
    lock: threading.Lock
    users: int = 0


class _CoordinatorState:
    def __init__(self, capacity: int) -> None:
        self.guard = threading.Lock()
        self.slots = threading.BoundedSemaphore(capacity)
        self.capacity = capacity
        self.active = 0
        self.mutations: dict[str, _MutationEntry] = {}


_PROCESS_STATE = _CoordinatorState(MAX_PROCESS_OPERATIONS)


def cooperative_cancellation_requested() -> bool:
    """Observe AnyIO cancellation from a synchronous MCP worker thread."""
    try:
        from_thread.check_cancelled()
    except RuntimeError:
        # Direct unit calls are not running in an AnyIO worker thread.
        return False
    except BaseException:
        # AnyIO backend cancellation classes intentionally inherit BaseException.
        return True
    return False


def _cancelled(check: Optional[CancellationCheck]) -> bool:
    return (check or cooperative_cancellation_requested)()


class BoundedCoordinator:
    """Share four no-queue process slots and serialize same-task mutations."""

    def __init__(self, *, _state: Optional[_CoordinatorState] = None) -> None:
        self._state = _state or _PROCESS_STATE

    @property
    def active_count(self) -> int:
        with self._state.guard:
            return self._state.active

    @property
    def mutation_count(self) -> int:
        with self._state.guard:
            return len(self._state.mutations)

    @contextmanager
    def _operation_slot(
        self,
        *,
        cancellation_check: Optional[CancellationCheck],
    ) -> Iterator[None]:
        if _cancelled(cancellation_check):
            raise cancelled_failure()
        if not self._state.slots.acquire(blocking=False):
            raise MCPRuntimeFailure(
                "MCP_RUNTIME_UNAVAILABLE",
                "The bounded MCP live-operation coordinator is at capacity.",
                details={"maximum_active": self._state.capacity},
                recovery={"kind": "retry-later", "blind_retry": True},
            )
        with self._state.guard:
            self._state.active += 1
        try:
            if _cancelled(cancellation_check):
                raise cancelled_failure()
            yield
        finally:
            with self._state.guard:
                self._state.active -= 1
            self._state.slots.release()

    @contextmanager
    def mutation(
        self,
        task_id: str,
        *,
        cancellation_check: Optional[CancellationCheck] = None,
    ) -> Iterator[None]:
        with self._operation_slot(cancellation_check=cancellation_check):
            with self._state.guard:
                entry = self._state.mutations.get(task_id)
                if entry is None:
                    entry = _MutationEntry(threading.Lock())
                    self._state.mutations[task_id] = entry
                entry.users += 1
            acquired = False
            deadline = time.monotonic() + MUTATION_WAIT_SECONDS
            try:
                while not acquired:
                    if _cancelled(cancellation_check):
                        raise cancelled_failure()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MCPRuntimeFailure(
                            "MCP_RUNTIME_UNAVAILABLE",
                            "The same-task mutation coordinator did not become available.",
                            details={"task_id": task_id},
                            recovery={"kind": "retry-later", "blind_retry": True},
                        )
                    acquired = entry.lock.acquire(timeout=min(_POLL_SECONDS, remaining))
                if _cancelled(cancellation_check):
                    raise cancelled_failure()
                yield
            finally:
                if acquired:
                    entry.lock.release()
                with self._state.guard:
                    entry.users -= 1
                    if entry.users == 0 and self._state.mutations.get(task_id) is entry:
                        self._state.mutations.pop(task_id, None)

    @contextmanager
    def capture(
        self,
        *,
        cancellation_check: Optional[CancellationCheck] = None,
    ) -> Iterator[None]:
        with self._operation_slot(cancellation_check=cancellation_check):
            yield
