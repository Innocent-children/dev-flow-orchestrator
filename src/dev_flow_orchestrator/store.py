"""Private schema-v5 filesystem state store and lock boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Tuple

from .engine import validate_persisted_state, validate_state_transition
from .filesystem import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
    read_regular_file_at,
)
from .model import DevFlowError, TaskState, canonical_json_bytes, validate_task_id
from .product import PRODUCT_IDENTITY, TASK_SCHEMA_VERSION
from .workflow import WorkflowDefinition
from .workflows import load_definition, task_definition


class TaskStore:
    """Persist current task state beneath one explicit data directory."""

    def __init__(self, data_dir: str) -> None:
        if not isinstance(data_dir, str) or not data_dir:
            raise DevFlowError("DATA_DIR_REQUIRED", "--data-dir is required")
        supplied_root = Path(data_dir).expanduser()
        try:
            if supplied_root.is_symlink():
                raise DevFlowError(
                    "DATA_PATH_UNSAFE",
                    "controller data directory must not be a symlink",
                    details={"path": str(supplied_root)},
                )
            self.root = supplied_root.resolve()
        except DevFlowError:
            raise
        except OSError as exc:
            raise DevFlowError(
                "DATA_PATH_FAILED",
                "controller data directory could not be resolved",
                details={"path": str(supplied_root), "error": str(exc)},
            ) from exc
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

    def _read_state_with_definition(
        self,
        task_id: str,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        expected_task_id = validate_task_id(task_id)
        path = self._state_path(expected_task_id)
        try:
            raw = read_regular_file_at(
                self.root,
                ("tasks", expected_task_id, "state.json"),
            )
        except FileNotFoundError as exc:
            raise DevFlowError(
                "TASK_NOT_FOUND",
                "task does not exist",
                details={"path": str(path)},
            ) from exc
        except DevFlowError:
            raise
        except OSError as exc:
            raise DevFlowError(
                "STATE_READ_FAILED",
                "task state could not be read",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not valid UTF-8 JSON",
                details={"path": str(path)},
            ) from exc
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "task state must be an object")
        if value.get("schema_version") != TASK_SCHEMA_VERSION:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not current schema v{}".format(TASK_SCHEMA_VERSION),
            )
        if value.get("product_identity") != PRODUCT_IDENTITY:
            raise DevFlowError(
                "PRODUCT_IDENTITY_MISMATCH",
                "task product identity is not installed",
            )
        stored_task_id = value.get("task_id")
        if stored_task_id != expected_task_id:
            raise DevFlowError(
                "STATE_INVALID",
                "task state identity does not match its storage path",
                details={
                    "path": str(path),
                    "expected_task_id": expected_task_id,
                    "stored_task_id": stored_task_id,
                },
            )
        workflow = value.get("workflow")
        if not isinstance(workflow, dict) or not isinstance(workflow.get("id"), str):
            raise DevFlowError(
                "STATE_INVALID",
                "task product selection is invalid",
                details={"path": str(path)},
            )
        definition = load_definition(workflow["id"])
        state = TaskState.from_dict(value, definition=definition)
        validate_persisted_state(state, definition)
        return state, definition

    def _read_state(self, task_id: str) -> TaskState:
        state, _ = self._read_state_with_definition(task_id)
        return state

    @staticmethod
    def _atomic_write(path: Path, state: TaskState) -> None:
        payload = canonical_json_bytes(state.as_dict()) + b"\n"
        atomic_write_bytes(path, payload)

    def create(self, state: TaskState) -> TaskState:
        with self._lock(state.task_id):
            task_directory = self._task_directory(state.task_id)
            state_path = self._state_path(state.task_id)
            ensure_private_directory(task_directory)
            if state_path.is_symlink():
                raise DevFlowError(
                    "DATA_PATH_UNSAFE",
                    "task state path must not be a symlink",
                    details={"path": str(state_path)},
                )
            if state_path.exists():
                raise DevFlowError(
                    "TASK_EXISTS",
                    "task already exists",
                    details={"task_id": state.task_id},
                )
            definition = task_definition(state)
            validate_persisted_state(state, definition)
            self._atomic_write(state_path, state)
        return state

    def load(self, task_id: str) -> TaskState:
        with self._lock(task_id):
            return self._read_state(task_id)

    def load_with_definition(
        self,
        task_id: str,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        with self._lock(task_id):
            return self._read_state_with_definition(task_id)

    def list_states(self) -> Tuple[TaskState, ...]:
        return tuple(state for state, _ in self.list_states_with_definitions())

    def list_states_with_definitions(
        self,
    ) -> Tuple[Tuple[TaskState, WorkflowDefinition], ...]:
        try:
            if not self.tasks_root.exists():
                return ()
            if self.tasks_root.is_symlink() or not self.tasks_root.is_dir():
                raise DevFlowError(
                    "DATA_PATH_UNSAFE",
                    "controller tasks path must be a real directory",
                    details={"path": str(self.tasks_root)},
                )
            paths = tuple(self.tasks_root.iterdir())
        except DevFlowError:
            raise
        except OSError as exc:
            raise DevFlowError(
                "STATE_READ_FAILED",
                "task directory could not be listed",
                details={"path": str(self.tasks_root), "error": str(exc)},
            ) from exc
        ensure_private_directory(self.root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        task_ids = []
        for path in paths:
            try:
                candidate = path.is_dir() or path.is_symlink()
            except OSError as exc:
                raise DevFlowError(
                    "STATE_READ_FAILED",
                    "task directory entry could not be inspected",
                    details={"path": str(path), "error": str(exc)},
                ) from exc
            if candidate:
                try:
                    task_ids.append(validate_task_id(path.name))
                except DevFlowError:
                    continue
        states = []
        for task_id in sorted(task_ids, key=lambda item: item.encode("utf-8")):
            try:
                states.append(self.load_with_definition(task_id))
            except DevFlowError:
                continue
        return tuple(states)

    def update(
        self,
        task_id: str,
        expected_revision: int,
        mutation: Callable[[TaskState], TaskState],
    ) -> TaskState:
        with self._lock(task_id):
            state_path = self._state_path(task_id)
            current, definition = self._read_state_with_definition(task_id)
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
            if candidate.task_id != task_id:
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "mutation changed task identity",
                )
            validate_state_transition(current, candidate, definition)
            self._atomic_write(state_path, candidate)
            return candidate
