"""Private schema-v4 filesystem state store and lock boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Tuple

from .filesystem import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
)
from .model import DevFlowError, TaskState, canonical_json_bytes, validate_task_id


class TaskStore:
    """Persist current task state beneath one explicit data directory."""

    def __init__(self, data_dir: str) -> None:
        if not isinstance(data_dir, str) or not data_dir:
            raise DevFlowError("DATA_DIR_REQUIRED", "--data-dir is required")
        self.root = Path(data_dir).expanduser().resolve()
        self.tasks_root = self.root / "tasks"
        self.locks_root = self.root / "locks"

    def _task_directory(self, task_id: str) -> Path:
        return self.tasks_root / validate_task_id(task_id)

    def _state_path(self, task_id: str) -> Path:
        return self._task_directory(task_id) / "state.json"

    def _lock(self, task_id: str):
        validate_task_id(task_id)
        ensure_private_directory(self.root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        lock_path = self.locks_root / "{}.lock".format(task_id)
        return exclusive_file_lock(lock_path)

    @staticmethod
    def _read_state(path: Path) -> TaskState:
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise DevFlowError(
                "TASK_NOT_FOUND",
                "task does not exist",
                details={"path": str(path)},
            ) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not valid UTF-8 JSON",
                details={"path": str(path)},
            ) from exc
        return TaskState.from_dict(value)

    @staticmethod
    def _atomic_write(path: Path, state: TaskState) -> None:
        payload = canonical_json_bytes(state.as_dict()) + b"\n"
        atomic_write_bytes(path, payload)

    def create(self, state: TaskState) -> TaskState:
        with self._lock(state.task_id):
            task_directory = self._task_directory(state.task_id)
            state_path = self._state_path(state.task_id)
            if state_path.exists():
                raise DevFlowError(
                    "TASK_EXISTS",
                    "task already exists",
                    details={"task_id": state.task_id},
                )
            ensure_private_directory(task_directory)
            self._atomic_write(state_path, state)
        return state

    def load(self, task_id: str) -> TaskState:
        return self._read_state(self._state_path(task_id))

    def list_states(self) -> Tuple[TaskState, ...]:
        states = []
        for path in sorted(
            self.tasks_root.glob("*/state.json"),
            key=lambda item: item.as_posix().encode("utf-8"),
        ):
            states.append(self._read_state(path))
        return tuple(states)

    def update(
        self,
        task_id: str,
        expected_revision: int,
        mutation: Callable[[TaskState], TaskState],
    ) -> TaskState:
        with self._lock(task_id):
            state_path = self._state_path(task_id)
            current = self._read_state(state_path)
            if current.revision != expected_revision:
                raise DevFlowError(
                    "REVISION_CONFLICT",
                    "task revision is stale",
                    details={
                        "task_id": task_id,
                        "expected_revision": expected_revision,
                        "actual_revision": current.revision,
                    },
                )
            candidate = mutation(current)
            if candidate.task_id != current.task_id:
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "mutation changed task identity",
                )
            if candidate.revision != current.revision + 1:
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "mutation must increment revision exactly once",
                )
            self._atomic_write(state_path, candidate)
            return candidate
