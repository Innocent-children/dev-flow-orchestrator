"""Private current-product filesystem state store and lock boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple

from ._platform.paths import (
    canonical_data_root,
    canonical_git_path,
    canonical_repository_root,
    comparison_key,
    paths_equal,
)
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
from .product import (
    MAX_STATE_FILE_BYTES,
    MAX_STATE_JSON_NESTING_DEPTH,
    PLUGIN_DATA_NAMESPACE,
    PRODUCT_IDENTITY,
    MODEL_VERSION,
)
from .workflow import WorkflowDefinition
from .workflows import load_definition, task_definition


@dataclass(frozen=True)
class RepositoryMutationPlan:
    """Freeze one repository capture and pure state derivation request."""

    action_id: str
    capture: Callable[[], Mapping[str, object]]
    derive: Callable[[Mapping[str, object]], TaskState]


@dataclass(frozen=True)
class RepositoryMutationCommit:
    """Separate a durable state replacement from its live observation."""

    state: TaskState
    action_id: str
    committed_snapshot: Mapping[str, object]
    observation: Optional[Mapping[str, object]]
    observed_at: Optional[str]
    observation_error_code: Optional[str]


@dataclass(frozen=True)
class _RepositoryAuthority:
    repository_id: str
    identity: bytes
    lock_path: Path


def _validate_state_json_nesting(
    text: str,
    *,
    maximum_depth: int = MAX_STATE_JSON_NESTING_DEPTH,
    phase: Optional[str] = None,
) -> None:
    """Reject excessive JSON container nesting without counting string content."""
    stack = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append(character)
            if len(stack) > maximum_depth:
                details = {"maximum_depth": maximum_depth}
                if phase is not None:
                    details["phase"] = phase
                raise DevFlowError(
                    "STATE_LIMIT_EXCEEDED",
                    "task state exceeds the current product nesting limit",
                    details=details,
                )
        elif character in "}]":
            if not stack or stack[-1] != pairs[character]:
                raise DevFlowError(
                    "STATE_INVALID",
                    "task state is not valid UTF-8 JSON",
                )
            stack.pop()


def _decode_persisted_state_envelope(
    payload: bytes,
    *,
    maximum_bytes: Optional[int] = None,
    maximum_depth: Optional[int] = None,
    phase: Optional[str] = None,
) -> object:
    """Validate and decode the byte/depth envelope shared by reads and writes."""
    byte_limit = MAX_STATE_FILE_BYTES if maximum_bytes is None else maximum_bytes
    depth_limit = (
        MAX_STATE_JSON_NESTING_DEPTH
        if maximum_depth is None
        else maximum_depth
    )
    if len(payload) > byte_limit:
        details = {"maximum_bytes": byte_limit}
        if phase is not None:
            details["phase"] = phase
        raise DevFlowError(
            "STATE_LIMIT_EXCEEDED",
            "task state exceeds the current product byte limit",
            details=details,
        )
    try:
        text = payload.decode("utf-8")
        _validate_state_json_nesting(
            text,
            maximum_depth=depth_limit,
            phase=phase,
        )
        return strict_json_loads(text)
    except DevFlowError:
        raise
    except RecursionError as exc:
        details = {"maximum_depth": depth_limit}
        if phase is not None:
            details["phase"] = phase
        raise DevFlowError(
            "STATE_LIMIT_EXCEEDED",
            "task state exceeds the current product nesting limit",
            details=details,
        ) from exc
    except (UnicodeError, ValueError) as exc:
        raise DevFlowError(
            "STATE_INVALID",
            "task state is not valid UTF-8 JSON",
        ) from exc


def _validated_candidate_state_payload(state: TaskState) -> bytes:
    """Return canonical state bytes only when the read envelope accepts them."""
    try:
        payload = canonical_json_bytes(state.as_dict()) + b"\n"
    except RecursionError as exc:
        raise DevFlowError(
            "STATE_LIMIT_EXCEEDED",
            "candidate task state exceeds the current product nesting limit",
            details={
                "maximum_depth": MAX_STATE_JSON_NESTING_DEPTH,
                "phase": "candidate-write",
            },
        ) from exc
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DevFlowError(
            "STATE_WRITE_INVALID",
            "candidate task state is not canonical JSON",
        ) from exc
    value = _decode_persisted_state_envelope(
        payload,
        phase="candidate-write",
    )
    if not isinstance(value, dict):
        raise DevFlowError(
            "STATE_WRITE_INVALID",
            "candidate task state must serialize as an object",
        )
    return payload


def _exclusive_lock(
    path: Path,
    cancellation_check: Optional[Callable[[], object]],
):
    """Preserve the one-argument lock seam when no cancellation is supplied."""
    if cancellation_check is None:
        return exclusive_file_lock(path)
    return exclusive_file_lock(
        path,
        cancellation_check=cancellation_check,
    )


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
            self.root = canonical_data_root(supplied_root)
        except DevFlowError:
            raise
        except (OSError, ValueError) as exc:
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

    def _lock(
        self,
        task_id: str,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ):
        validate_task_id(task_id)
        ensure_private_directory(self.root)
        ensure_private_directory(self.namespace_root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        lock_path = self.locks_root / "{}.lock".format(task_id)
        return _exclusive_lock(
            lock_path,
            cancellation_check,
        )

    def membership_lock(
        self,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ):
        """Serialize complete current-namespace membership admission."""
        ensure_private_directory(self.root)
        ensure_private_directory(self.namespace_root)
        ensure_private_directory(self.tasks_root)
        ensure_private_directory(self.locks_root)
        return _exclusive_lock(
            self.locks_root / "membership.lock",
            cancellation_check,
        )

    @staticmethod
    def _repository_identity(repository) -> bytes:
        try:
            root = canonical_repository_root(repository.path)
            git_worktree_dir = canonical_git_path(
                repository.git_worktree_dir,
                repository_root=root,
            )
            root_key = comparison_key(root).encode("utf-8")
            git_worktree_key = comparison_key(git_worktree_dir).encode("utf-8")
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            raise DevFlowError(
                "REPOSITORY_INVALID",
                "repository authority identity cannot be resolved",
                details={"repository_id": repository.repository_id},
            ) from exc
        return root_key + b"\0" + git_worktree_key

    def _repository_authorities(self, repositories) -> Tuple[_RepositoryAuthority, ...]:
        seen = {}
        authorities = []
        lock_domain = b"dev-flow-orchestrator/repository-authority-lock/v1\0"
        for repository in repositories:
            identity = self._repository_identity(repository)
            duplicate = seen.get(identity)
            if duplicate is not None:
                raise DevFlowError(
                    "REPOSITORY_DUPLICATE",
                    "task repositories resolve to the same authority identity",
                    details={
                        "repository_ids": [
                            duplicate,
                            repository.repository_id,
                        ],
                    },
                )
            seen[identity] = repository.repository_id
            digest = hashlib.sha256(lock_domain + identity).hexdigest()
            authorities.append(
                _RepositoryAuthority(
                    repository.repository_id,
                    identity,
                    self.locks_root / "repository-{}.lock".format(digest),
                )
            )
        return tuple(sorted(authorities, key=lambda item: item.identity))

    @staticmethod
    def _same_authorities(
        left: Tuple[_RepositoryAuthority, ...],
        right: Tuple[_RepositoryAuthority, ...],
    ) -> bool:
        return tuple(
            (item.repository_id, item.identity) for item in left
        ) == tuple((item.repository_id, item.identity) for item in right)

    @staticmethod
    def _capture_mapping(plan: RepositoryMutationPlan) -> Mapping[str, object]:
        snapshot = plan.capture()
        if not isinstance(snapshot, Mapping):
            raise DevFlowError(
                "SNAPSHOT_INVALID",
                "repository mutation capture must return a mapping",
            )
        return snapshot

    @staticmethod
    def _changed_repository_ids(
        repositories,
        before: Mapping[str, object],
        after: Mapping[str, object],
    ) -> list:
        repository_ids = tuple(
            sorted(
                (repository.repository_id for repository in repositories),
                key=lambda item: item.encode("utf-8"),
            )
        )

        def members(snapshot: Mapping[str, object]) -> dict:
            values = snapshot.get("repositories")
            if not isinstance(values, (list, tuple)):
                return {}
            result = {}
            for value in values:
                if not isinstance(value, Mapping):
                    continue
                repository_id = value.get("repository_id")
                if isinstance(repository_id, str):
                    result[repository_id] = value
            return result

        before_members = members(before)
        after_members = members(after)
        changed = [
            repository_id
            for repository_id in repository_ids
            if before_members.get(repository_id) != after_members.get(repository_id)
        ]
        if changed:
            return changed[:8]
        # A valid repository-set snapshot cannot differ only outside its member
        # values.  Fail closed with the bounded task membership when a caller
        # supplies another Mapping implementation or an invalid aggregate.
        return list(repository_ids[:8])

    @staticmethod
    def _observation_error_code(exc: Exception) -> str:
        try:
            code = getattr(exc, "code", None)
            if (
                isinstance(code, str)
                and 1 <= len(code) <= 64
                and code[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                and all(
                    character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                    for character in code
                )
            ):
                return code
        except Exception:
            pass
        return "OBSERVATION_FAILED"

    @staticmethod
    def _utc_now() -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

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
                maximum_bytes=MAX_STATE_FILE_BYTES,
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
        value = _decode_persisted_state_envelope(raw)
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "task state must be an object")
        if value.get("version") != MODEL_VERSION:
            raise DevFlowError(
                "STATE_INVALID",
                "task state is not current product version {}".format(
                    MODEL_VERSION
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
        try:
            workflow = value.get("workflow")
            if not isinstance(workflow, dict) or not isinstance(
                workflow.get("id"), str
            ):
                raise DevFlowError(
                    "STATE_INVALID",
                    "task product selection is invalid",
                    details={"path": str(path)},
                )
            definition = load_definition(workflow["id"])
            state = TaskState.from_dict(value, definition=definition)
            validate_persisted_state(state, definition)
        except RecursionError as exc:
            raise DevFlowError(
                "STATE_LIMIT_EXCEEDED",
                "task state exceeds the current product nesting limit",
                details={"maximum_depth": MAX_STATE_JSON_NESTING_DEPTH},
            ) from exc
        return state, definition

    def _read_state(self, task_id: str) -> TaskState:
        state, _ = self._read_state_with_definition(task_id)
        return state

    @staticmethod
    def _atomic_write(path: Path, state: TaskState) -> None:
        payload = _validated_candidate_state_payload(state)
        atomic_write_bytes(path, payload)

    def create(
        self,
        state: TaskState,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ) -> TaskState:
        with self._lock(
            state.task_id,
            cancellation_check=cancellation_check,
        ):
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

    def create_admitted(
        self,
        state: TaskState,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ) -> TaskState:
        """Persist revision zero after a caller-held membership lock check."""
        for existing, definition in self.list_states_with_definitions(
            strict=True,
            cancellation_check=cancellation_check,
        ):
            if is_terminal_state(existing, definition):
                continue
            for requested in state.repositories:
                for owned in existing.repositories:
                    if self._repositories_overlap(requested, owned):
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
        return self.create(state, cancellation_check=cancellation_check)

    @staticmethod
    def _repositories_overlap(left, right) -> bool:
        return any(
            paths_equal(left_value, right_value)
            for left_value in (left.path, left.git_worktree_dir, left.git_common_dir)
            for right_value in (right.path, right.git_worktree_dir, right.git_common_dir)
        )

    def _assert_active_membership(self, state: TaskState) -> None:
        conflicts = []
        for other, definition in self.list_states_with_definitions(
            strict=True,
            acquire_task_locks=False,
        ):
            if other.task_id == state.task_id or is_terminal_state(other, definition):
                continue
            for current_repository in state.repositories:
                for other_repository in other.repositories:
                    if self._repositories_overlap(current_repository, other_repository):
                        conflicts.append({
                            "task_id": other.task_id,
                            "repository_id": current_repository.repository_id,
                            "conflicting_repository_id": other_repository.repository_id,
                        })
        if conflicts:
            raise DevFlowError(
                "LEASE_INTEGRITY_CONFLICT",
                "active repository membership is not unique",
                details={
                    "task_id": state.task_id,
                    "conflicts": conflicts[:8],
                },
            )

    @contextmanager
    def repository_read(
        self,
        task_id: str,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ):
        """Hold established authority locks for one live repository projection."""
        with ExitStack() as locks:
            locks.enter_context(
                self.membership_lock(cancellation_check=cancellation_check)
            )
            inspected, _ = self.inspect_with_definition(task_id)
            self._assert_active_membership(inspected)
            authorities = self._repository_authorities(inspected.repositories)
            for authority in authorities:
                locks.enter_context(
                    _exclusive_lock(
                        authority.lock_path,
                        cancellation_check,
                    )
                )
            locks.enter_context(
                self._lock(task_id, cancellation_check=cancellation_check)
            )
            current, definition = self._read_state_with_definition(task_id)
            if current.repositories != inspected.repositories:
                raise DevFlowError(
                    "REVISION_CONFLICT",
                    "task membership changed while live authority was acquired",
                    details={"task_id": task_id},
                )
            yield current, definition

    def load(
        self,
        task_id: str,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ) -> TaskState:
        with self._lock(task_id, cancellation_check=cancellation_check):
            return self._read_state(task_id)

    def load_with_definition(
        self,
        task_id: str,
        *,
        cancellation_check: Optional[Callable[[], object]] = None,
    ) -> Tuple[TaskState, WorkflowDefinition]:
        with self._lock(task_id, cancellation_check=cancellation_check):
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
            "STATE_LIMIT_EXCEEDED",
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
            except (
                DevFlowError,
                OSError,
                RecursionError,
                UnicodeError,
                ValueError,
            ) as exc:
                diagnostics.append(self._inspection_diagnostic(name, exc))
        return tuple(states), tuple(diagnostics)

    def list_states(self) -> Tuple[TaskState, ...]:
        return tuple(state for state, _ in self.list_states_with_definitions())

    def inventory_diagnostics(self) -> Tuple[dict, ...]:
        """Describe unreadable current-namespace entries without mutating them."""
        _entries, diagnostics = self.inspect_inventory()
        return diagnostics

    def list_states_with_definitions(
        self,
        *,
        strict: bool = False,
        acquire_task_locks: bool = True,
        cancellation_check: Optional[Callable[[], object]] = None,
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
                states.append(
                    self.load_with_definition(
                        task_id,
                        cancellation_check=cancellation_check,
                    )
                    if acquire_task_locks
                    else self._read_state_with_definition(task_id)
                )
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

    def commit_repository_mutation(
        self,
        task_id: str,
        expected_revision: int,
        prepare: Callable[
            [TaskState, WorkflowDefinition],
            RepositoryMutationPlan,
        ],
        cancellation_check: Optional[Callable[[], None]] = None,
        phase_hook: Optional[Callable[[str], None]] = None,
    ) -> RepositoryMutationCommit:
        """Commit one snapshot-bound mutation under canonical repository locks."""
        with ExitStack() as locks:
            locks.enter_context(
                self.membership_lock(cancellation_check=cancellation_check)
            )

            inspected, _ = self.inspect_with_definition(task_id)
            self._assert_active_membership(inspected)
            selected_authorities = self._repository_authorities(
                inspected.repositories
            )
            for authority in selected_authorities:
                locks.enter_context(
                    _exclusive_lock(
                        authority.lock_path,
                        cancellation_check,
                    )
                )

            locks.enter_context(
                self._lock(task_id, cancellation_check=cancellation_check)
            )
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
            if current.repositories != inspected.repositories:
                raise DevFlowError(
                    "REVISION_CONFLICT",
                    "task repository membership changed while commit authority was acquired",
                    details={
                        "task_id": task_id,
                        "expected_revision": expected_revision,
                        "actual_revision": current.revision,
                        "cause": "repository_membership_changed",
                    },
                )
            current_authorities = self._repository_authorities(
                current.repositories
            )
            if not self._same_authorities(
                selected_authorities,
                current_authorities,
            ):
                raise DevFlowError(
                    "REPOSITORY_IDENTITY_MISMATCH",
                    "repository authority identity changed while locks were acquired",
                    details={
                        "repository_ids": [
                            repository.repository_id
                            for repository in current.repositories[:8]
                        ],
                    },
                )

            plan = prepare(current, definition)
            if not isinstance(plan, RepositoryMutationPlan):
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "repository mutation prepare callback returned an invalid plan",
                )
            if not isinstance(plan.action_id, str) or not plan.action_id:
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "repository mutation action identity is invalid",
                )

            committed_snapshot = self._capture_mapping(plan)
            if cancellation_check is not None:
                cancellation_check()
            candidate = plan.derive(committed_snapshot)
            if not isinstance(candidate, TaskState):
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "repository mutation derivation returned an invalid task state",
                )
            if candidate.task_id != task_id:
                raise DevFlowError(
                    "STATE_WRITE_INVALID",
                    "mutation changed task identity",
                )
            validate_state_transition(current, candidate, definition)

            if phase_hook is not None:
                phase_hook("before-revalidation")
            revalidated_snapshot = self._capture_mapping(plan)
            if revalidated_snapshot != committed_snapshot:
                raise DevFlowError(
                    "SNAPSHOT_UNSTABLE",
                    "repository set changed before task state replacement",
                    details={
                        "repository_ids": self._changed_repository_ids(
                            current.repositories,
                            committed_snapshot,
                            revalidated_snapshot,
                        ),
                        "phase": "revalidation",
                    },
                )
            if phase_hook is not None:
                phase_hook("after-revalidation")

            self._atomic_write(state_path, candidate)

            observation = None
            observed_at = None
            observation_error_code = None
            try:
                if phase_hook is not None:
                    phase_hook("before-observation")
                observation = self._capture_mapping(plan)
                observed_at = self._utc_now()
            except Exception as exc:
                observation = None
                observed_at = None
                observation_error_code = self._observation_error_code(exc)

            return RepositoryMutationCommit(
                state=candidate,
                action_id=plan.action_id,
                committed_snapshot=committed_snapshot,
                observation=observation,
                observed_at=observed_at,
                observation_error_code=observation_error_code,
            )
