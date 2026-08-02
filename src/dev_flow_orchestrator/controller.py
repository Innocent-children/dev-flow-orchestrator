"""The sole application boundary for current V5 task mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Optional
import uuid

from . import workflows
from .engine import apply_current_action, plan_current_action, validate_action_payload
from .git_client import GitClient
from .model import (
    DevFlowError,
    MutationReceipt,
    RepositoryRecord,
    TaskState,
    initial_state,
)
from .store import TaskStore
from .workflow import agent_projection, is_terminal_state


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _repository_id(path: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip("-") or "repo"
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return "{}-{}".format(slug[:40], digest)


class Controller:
    """Coordinate product selection, Git evidence and the private task store."""

    def __init__(
        self,
        data_dir: str,
        *,
        git_client: Optional[GitClient] = None,
    ) -> None:
        self.store = TaskStore(data_dir)
        self.git = git_client or GitClient()

    def _canonical_repositories(self, paths: Iterable[str]) -> tuple:
        seen = set()
        repositories = []
        for supplied in paths:
            path = Path(supplied).expanduser().resolve()
            if not path.is_dir():
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path is not a directory",
                    details={"path": str(path)},
                )
            identity = str(path)
            if identity in seen:
                continue
            seen.add(identity)
            repositories.append(
                RepositoryRecord(_repository_id(path), identity)
            )
        if not repositories:
            raise DevFlowError(
                "REPOSITORY_REQUIRED",
                "at least one repository is required",
            )
        if len(repositories) > 1:
            raise DevFlowError(
                "REPOSITORY_COUNT_UNSUPPORTED",
                "this runtime supports exactly one repository per task",
                details={"repository_count": len(repositories)},
            )
        return tuple(repositories)

    def start(
        self,
        *,
        requirement: str,
        workflow: str,
        repository: str,
        task_id: Optional[str] = None,
    ) -> TaskState:
        clean_requirement = requirement.strip()
        definition = workflows.load_definition(workflow)
        repository_records = self._canonical_repositories([repository])
        for repository_record in repository_records:
            root = Path(repository_record.path).resolve()
            if (
                self.store.root == root
                or root in self.store.root.parents
                or self.store.root in root.parents
            ):
                raise DevFlowError(
                    "DATA_DIR_INSIDE_REPOSITORY",
                    "controller data directory must remain outside target repositories",
                    details={
                        "data_dir": str(self.store.root),
                        "repository": str(root),
                    },
                )
        effective_task_id = task_id or "task-{}".format(uuid.uuid4().hex[:16])
        state = initial_state(
            task_id=effective_task_id,
            requirement=clean_requirement,
            definition=definition,
            repository=repository_records[0],
            timestamp=_utc_now(),
        )
        return self.store.create(state)

    def show(self, task_id: str) -> TaskState:
        return self.store.load(task_id)

    def next(self, task_id: str) -> dict:
        """The agent-v1 projection: exactly one thing to do next."""
        state, definition = self.store.load_with_definition(task_id)
        return agent_projection(state, definition)

    def list_tasks(self) -> tuple:
        return self.store.list_states()

    def apply(
        self,
        task_id: str,
        action_id: str,
        payload: Optional[Mapping[str, object]] = None,
    ) -> dict:
        """Validate and execute one action, advancing the task state.

        Revision is read from the loaded state, never from the caller.
        On a concurrent-writer CAS loss the caller receives a fresh
        projection in ``details.projection`` and simply re-runs ``next``.
        """
        state, definition = self.store.load_with_definition(task_id)
        contract, plan = plan_current_action(
            state, definition, action_id, state.revision
        )
        validated = validate_action_payload(contract, payload)
        effect_result = None
        if contract.effect_port == "git.inspect-repository":
            effect_result = {
                repository.repository_id: self.git.inspect(repository.path)
                for repository in state.repositories
            }
        elif contract.effect_port != "none":
            raise DevFlowError(
                "EFFECT_UNSUPPORTED",
                "effect port {!r} is not supported by this runtime".format(
                    contract.effect_port
                ),
            )
        try:
            committed = self.store.update(
                task_id,
                state.revision,
                lambda current: apply_current_action(
                    current,
                    definition,
                    contract,
                    plan,
                    payload=validated,
                    effect_result=effect_result,
                    timestamp=_utc_now(),
                ),
            )
        except DevFlowError as exc:
            if exc.code == "REVISION_CONFLICT":
                fresh, fresh_definition = self.store.load_with_definition(task_id)
                raise DevFlowError(
                    "REVISION_CONFLICT",
                    "task advanced concurrently; re-run next and apply the "
                    "fresh action",
                    details={"projection": agent_projection(fresh, fresh_definition)},
                ) from exc
            raise
        return {
            "receipt": MutationReceipt(
                committed.task_id,
                plan.action_id,
                committed.revision,
                committed.status,
                committed.current_node,
            ).as_dict(),
            "projection": agent_projection(committed, definition),
        }

    def cancel(self, task_id: str, *, reason: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        if is_terminal_state(state, definition):
            raise DevFlowError(
                "ACTION_NOT_AVAILABLE",
                "task is already finished",
                details={
                    "task_id": task_id,
                    "status": state.status,
                    "current_node": state.current_node,
                },
            )
        if definition.cancel_contract is None:
            raise DevFlowError(
                "ACTION_NOT_AVAILABLE",
                "workflow does not declare a cancel action",
            )
        return self.apply(task_id, definition.cancel_contract.action_id, {"reason": reason})

    def tasks_for_path(self, path: str) -> tuple:
        candidate = Path(path).expanduser().resolve()
        matches = []
        for state, definition in self.store.list_states_with_definitions():
            if is_terminal_state(state, definition):
                continue
            roots = [
                Path(repository.path).resolve()
                for repository in state.repositories
            ]
            if any(
                candidate == root or root in candidate.parents
                for root in roots
            ):
                matches.append(state)
        return tuple(
            sorted(
                matches,
                key=lambda state: state.task_id.encode("utf-8"),
            )
        )
