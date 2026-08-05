"""Private current-product filesystem state store and lock boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Tuple

from .engine import (
    is_terminal_state,
    validate_persisted_state,
    validate_state_transition,
)
from .filesystem import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
    list_directory_names_at,
    read_regular_file_at,
)
from .model import (
    DevFlowError,
    TaskState,
    canonical_json_bytes,
    strict_json_loads,
    validate_task_id,
)
from .product import PLUGIN_DATA_NAMESPACE, PRODUCT_IDENTITY, PRODUCT_VERSION
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
        self.namespace_root = self.root / PLUGIN_DATA_NAMESPACE
        self.tasks_root = self.namespace_root / "tasks"
        self.locks_root = self.namespace_root / "locks"

    def _task_directory(self, task_id: str) -> Path:
        return self.tasks_root / validate_task_id(task_id)

    def _state_path(self, task_id: str) -> Path:
        return self._task_directory(task_id) / "state.json"

    def _lock(self, task_id: str):
        validate_task_id(task_id)
        ensure_private_directory(self.root)
        ensure_private_directory(self.namespace_root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        lock_path = self.locks_root / "{}.lock".format(task_id)
        return exclusive_file_lock(lock_path)

    def membership_lock(self):
        """Serialize complete current-namespace membership admission."""
        ensure_private_directory(self.root)
        ensure_private_directory(self.namespace_root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        return exclusive_file_lock(self.locks_root / "membership.lock")

    def _read_state_with_definition(
        self,
        task_id: str,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        expected_task_id = validate_task_id(task_id)
        path = self._state_path(expected_task_id)
        try:
            raw = read_regular_file_at(
                self.namespace_root,
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
            value = strict_json_loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not valid UTF-8 JSON",
                details={"path": str(path)},
            ) from exc
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "task state must be an object")
        if value.get("version") != PRODUCT_VERSION:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not current product version {}".format(
                    PRODUCT_VERSION
                ),
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

    def create_admitted(self, state: TaskState) -> TaskState:
        """Persist revision zero after a caller-held membership lock check."""
        for existing, definition in self.list_states_with_definitions(strict=True):
            if is_terminal_state(existing, definition):
                continue
            for requested in state.repositories:
                for owned in existing.repositories:
                    if (
                        requested.path == owned.path
                        or requested.git_worktree_dir == owned.git_worktree_dir
                    ):
                        raise DevFlowError(
                            "TASK_MEMBERSHIP_LEASED",
                            "requested worktree belongs to another active task",
                            details={
                                "owning_task_id": existing.task_id,
                                "owning_repository_id": owned.repository_id,
                                "requested_repository_id": requested.repository_id,
                                "repository_root": requested.path,
                                "git_worktree_dir": requested.git_worktree_dir,
                            },
                        )
        return self.create(state)

    def load(self, task_id: str) -> TaskState:
        with self._lock(task_id):
            return self._read_state(task_id)

    def load_with_definition(
        self,
        task_id: str,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        with self._lock(task_id):
            return self._read_state_with_definition(task_id)

    def inspect_with_definition(
        self,
        task_id: str,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        """Read one current task without locks, repairs, or filesystem writes."""
        return self._read_state_with_definition(task_id)

    @staticmethod
    def _inspection_diagnostic(entry: str, exc: BaseException) -> dict:
        code = getattr(exc, "code", "STATE_READ_FAILED")
        if code not in {
            "DATA_PATH_UNSAFE",
            "PRODUCT_IDENTITY_MISMATCH",
            "STATE_INVALID",
            "STATE_READ_FAILED",
            "TASK_NOT_FOUND",
            "WORKFLOW_NOT_FOUND",
        }:
            code = "STATE_READ_FAILED"
        diagnostic = {"code": code}
        try:
            diagnostic["task_id"] = validate_task_id(entry)
        except DevFlowError:
            diagnostic["entry"] = entry[:128]
            if len(entry) > 128:
                diagnostic["entry_truncated"] = True
        return diagnostic

    def inspect_inventory(
        self,
    ) -> Tuple[
        Tuple[Tuple[TaskState, WorkflowDefinition], ...],
        Tuple[dict, ...],
    ]:
        """Read current task inventory without creating directories or locks."""
        try:
            names = list_directory_names_at(
                self.root,
                (PLUGIN_DATA_NAMESPACE, "tasks"),
            )
        except FileNotFoundError:
            return (), ()
        except (DevFlowError, OSError) as exc:
            return (), (self._inspection_diagnostic("tasks", exc),)

        states = []
        diagnostics = []
        for name in sorted(names, key=lambda item: item.encode("utf-8")):
            try:
                task_id = validate_task_id(name)
                states.append(self._read_state_with_definition(task_id))
            except (DevFlowError, OSError) as exc:
                diagnostics.append(self._inspection_diagnostic(name, exc))
        return tuple(states), tuple(diagnostics)

    def list_states(self) -> Tuple[TaskState, ...]:
        return tuple(state for state, _ in self.list_states_with_definitions())

    def inventory_diagnostics(self) -> Tuple[dict, ...]:
        """Describe unreadable current-namespace entries without mutating them."""
        if not self.tasks_root.exists():
            return ()
        if self.tasks_root.is_symlink() or not self.tasks_root.is_dir():
            return ({
                "code": "DATA_PATH_UNSAFE",
                "path": str(self.tasks_root),
                "cause": "current tasks root is not a real directory",
            },)
        diagnostics = []
        try:
            paths = tuple(self.tasks_root.iterdir())
        except OSError as exc:
            return ({
                "code": "STATE_READ_FAILED",
                "path": str(self.tasks_root),
                "cause": str(exc),
            },)
        for path in sorted(paths, key=lambda item: item.name.encode("utf-8")):
            try:
                task_id = validate_task_id(path.name)
                if not path.is_dir() or path.is_symlink():
                    raise DevFlowError(
                        "DATA_PATH_UNSAFE",
                        "current task entry is not a real directory",
                    )
                self._read_state_with_definition(task_id)
            except (DevFlowError, OSError) as exc:
                diagnostics.append({
                    "code": getattr(exc, "code", "STATE_READ_FAILED"),
                    "path": str(path),
                    "cause": str(exc),
                })
        return tuple(diagnostics)

    def list_states_with_definitions(
        self,
        *,
        strict: bool = False,
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
        ensure_private_directory(self.namespace_root)
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
                except DevFlowError as exc:
                    if strict:
                        raise DevFlowError(
                            "LEASE_INVENTORY_INVALID",
                            "current task inventory contains an invalid entry",
                            details={"path": str(path), "cause": exc.code},
                        ) from exc
                    continue
            elif strict:
                raise DevFlowError(
                    "LEASE_INVENTORY_INVALID",
                    "current task inventory contains a non-directory entry",
                    details={"path": str(path)},
                )
        states = []
        for task_id in sorted(task_ids, key=lambda item: item.encode("utf-8")):
            try:
                states.append(self.load_with_definition(task_id))
            except DevFlowError as exc:
                if strict:
                    raise DevFlowError(
                        "LEASE_INVENTORY_INVALID",
                        "current task inventory cannot prove membership and terminal state",
                        details={
                            "task_id": task_id,
                            "path": str(self._state_path(task_id)),
                            "cause": exc.code,
                        },
                    ) from exc
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
