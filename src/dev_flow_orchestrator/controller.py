"""The sole application boundary for V6 task inspection and mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping, Optional, Sequence
import uuid

from . import workflows
from .delivery import (
    contract_digest,
    effective_contract,
    make_action_binding,
    minimal_contract,
    resource_requests,
    validate_action_binding,
    validate_contract,
)
from .engine import (
    agent_projection,
    apply_current_action,
    current_resource_requests,
    is_terminal_state,
    plan_current_action,
    record_decision,
    revise_contract,
    task_view,
    validate_action_payload,
)
from .git_client import GitClient
from .model import (
    DevFlowError,
    MutationReceipt,
    RepositoryRecord,
    TaskState,
    initial_state,
    json_value,
)
from .store import TaskStore


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _repository_id(path: Path) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name).strip("-") or "repo"
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    return "{}-{}".format(slug[:40], digest)


def _merge_resources(*groups: Sequence[Mapping[str, object]]) -> tuple:
    result = []
    seen = set()
    for group in groups:
        for item in group:
            key = (item.get("path"), item.get("role"), item.get("normalizer"))
            if key in seen:
                continue
            seen.add(key)
            result.append(json_value(item))
    return tuple(result)


class Controller:
    """Coordinate selected workflows, safe snapshots, and the private store."""

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
            repositories.append(RepositoryRecord(_repository_id(path), identity))
        if not repositories:
            raise DevFlowError("REPOSITORY_REQUIRED", "one repository is required")
        if len(repositories) != 1:
            raise DevFlowError(
                "REPOSITORY_COUNT_UNSUPPORTED",
                "this runtime supports exactly one repository per task",
                details={"repository_count": len(repositories)},
            )
        return tuple(repositories)

    def _snapshot(
        self,
        state: TaskState,
        *,
        additional_resources: Sequence[Mapping[str, object]] = (),
        include_current_resources: bool = True,
    ) -> Mapping[str, object]:
        current = current_resource_requests(state) if include_current_resources else ()
        resources = _merge_resources(current, additional_resources)
        return self.git.snapshot(state.repositories[0].path, resources=resources)

    def _projection(self, state: TaskState, definition) -> dict:
        return agent_projection(state, definition, self._snapshot(state))

    def _conflict(self, task_id: str, exc: DevFlowError) -> DevFlowError:
        fresh, definition = self.store.load_with_definition(task_id)
        return DevFlowError(
            "REVISION_CONFLICT",
            "task advanced concurrently; obtain the fresh action binding",
            details={"projection": self._projection(fresh, definition)},
        )

    def start(
        self,
        *,
        requirement: str,
        workflow: str,
        repository: str,
        task_id: Optional[str] = None,
        contract: Optional[Mapping[str, object]] = None,
    ) -> TaskState:
        if not isinstance(requirement, str) or not requirement.strip():
            raise DevFlowError(
                "REQUIREMENT_INVALID", "requirement must not be empty"
            )
        clean_requirement = requirement.strip()
        definition = workflows.load_definition(workflow)
        repository_record = self._canonical_repositories([repository])[0]
        root = Path(repository_record.path).resolve()
        if (
            self.store.root == root
            or root in self.store.root.parents
            or self.store.root in root.parents
        ):
            raise DevFlowError(
                "DATA_DIR_INSIDE_REPOSITORY",
                "controller data directory must remain outside target repositories",
                details={"data_dir": str(self.store.root), "repository": str(root)},
            )
        delivery_contract = (
            minimal_contract(clean_requirement)
            if contract is None
            else validate_contract(contract, expected_revision=1)
        )
        state = initial_state(
            task_id=task_id or "task-{}".format(uuid.uuid4().hex[:16]),
            requirement=clean_requirement,
            contract=delivery_contract,
            definition=definition,
            repository=repository_record,
            timestamp=_utc_now(),
        )
        return self.store.create(state)

    def show(self, task_id: str) -> TaskState:
        return self.store.load(task_id)

    def show_view(self, task_id: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        return task_view(state, definition, self._snapshot(state))

    def next(self, task_id: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        return self._projection(state, definition)

    def list_tasks(self) -> tuple:
        return self.store.list_states()

    def apply(
        self,
        task_id: str,
        action_id: str,
        payload: Optional[Mapping[str, object]] = None,
        *,
        binding: object,
    ) -> dict:
        """Commit one workflow action using the exact binding emitted by next."""
        state, definition = self.store.load_with_definition(task_id)
        validated_binding = validate_action_binding(binding)
        expected_revision = validated_binding["task_revision"]
        try:
            contract, plan = plan_current_action(
                state, definition, action_id, expected_revision
            )
            validated = validate_action_payload(contract, payload)
            requested = resource_requests(validated)
            snapshot = self._snapshot(state, additional_resources=requested)
            committed = self.store.update(
                task_id,
                expected_revision,
                lambda current: apply_current_action(
                    current,
                    definition,
                    contract,
                    plan,
                    payload=validated,
                    binding=validated_binding,
                    snapshot=snapshot,
                    timestamp=_utc_now(),
                ),
            )
        except DevFlowError as exc:
            if exc.code == "REVISION_CONFLICT":
                raise self._conflict(task_id, exc) from exc
            raise
        return {
            "receipt": MutationReceipt(
                committed.task_id,
                plan.action_id,
                committed.revision,
                committed.status,
                committed.current_node,
            ).as_dict(),
            "projection": self._projection(committed, definition),
        }

    def revise_contract(
        self,
        task_id: str,
        *,
        contract: Mapping[str, object],
        reason: str,
        actor_label: str,
    ) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        # A revision starts a new contract lineage, so old-contract governing
        # resources are intentionally absent from this new source baseline.
        snapshot = self._snapshot(state, include_current_resources=False)
        try:
            committed = self.store.update(
                task_id,
                state.revision,
                lambda current: revise_contract(
                    current,
                    definition,
                    new_contract=contract,
                    reason=reason,
                    actor_label=actor_label,
                    snapshot=snapshot,
                    timestamp=_utc_now(),
                ),
            )
        except DevFlowError as exc:
            if exc.code == "REVISION_CONFLICT":
                raise self._conflict(task_id, exc) from exc
            raise
        return {
            "receipt": MutationReceipt(
                committed.task_id,
                "contract.revise",
                committed.revision,
                committed.status,
                committed.current_node,
            ).as_dict(),
            "projection": self._projection(committed, definition),
        }

    def decide(
        self,
        task_id: str,
        *,
        decision: Mapping[str, object],
    ) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        try:
            committed = self.store.update(
                task_id,
                state.revision,
                lambda current: record_decision(
                    current,
                    definition,
                    decision=decision,
                    timestamp=_utc_now(),
                ),
            )
        except DevFlowError as exc:
            if exc.code == "REVISION_CONFLICT":
                raise self._conflict(task_id, exc) from exc
            raise
        return {
            "receipt": MutationReceipt(
                committed.task_id,
                "decision.record",
                committed.revision,
                committed.status,
                committed.current_node,
            ).as_dict(),
            "projection": self._projection(committed, definition),
        }

    def cancel(self, task_id: str, *, reason: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        if is_terminal_state(state, definition):
            raise DevFlowError("ACTION_NOT_AVAILABLE", "task is already finished")
        cancel = definition.cancel_contract
        if cancel is None:
            raise DevFlowError(
                "ACTION_NOT_AVAILABLE", "workflow does not declare cancellation"
            )
        snapshot = self._snapshot(state)
        contract_value = effective_contract(state.original_contract, state.records)
        binding = make_action_binding(
            task_id=state.task_id,
            revision=state.revision,
            action_id=cancel.action_id,
            node_id=cancel.node_id,
            contract=contract_value,
            inputs=(),
            current_snapshot=snapshot,
        )
        return self.apply(
            task_id,
            cancel.action_id,
            {"reason": reason},
            binding=binding,
        )

    def tasks_for_path(self, path: str) -> tuple:
        candidate = Path(path).expanduser().resolve()
        matches = []
        for state, definition in self.store.list_states_with_definitions():
            if is_terminal_state(state, definition):
                continue
            root = Path(state.repositories[0].path).resolve()
            if candidate == root or root in candidate.parents:
                matches.append(state)
        return tuple(sorted(matches, key=lambda item: item.task_id.encode("utf-8")))
