"""The sole application boundary for task inspection and mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
import re
import threading
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
    record_finding_disposition,
    revise_contract,
    task_view,
    validate_action_payload,
)
from .git_client import GitClient
from .model import (
    canonical_repositories as canonical_repository_records,
    DevFlowError,
    MutationReceipt,
    RepositoryRecord,
    TaskState,
    initial_state,
    json_value,
    repository_by_id,
    validate_repositories,
)
from .product import MAX_REPOSITORY_COUNT, MIN_REPOSITORY_COUNT
from .snapshot import make_repository_set_snapshot, validate_snapshot
from .store import TaskStore
from .web_views import (
    DEFAULT_PAGE_LIMIT,
    inventory_view as web_inventory_view,
    live_task_view as web_live_task_view,
    product_metadata as web_product_metadata,
    stored_task_view as web_stored_task_view,
)


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
            key = (
                item.get("repository_id"),
                item.get("path"),
                item.get("role"),
                item.get("normalizer"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(json_value(item))
    return tuple(result)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


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

    def _member_error(
        self,
        exc: DevFlowError,
        repository: RepositoryRecord,
        *,
        phase: str,
        capture_pass: Optional[int] = None,
    ) -> DevFlowError:
        details = dict(exc.details)
        details.setdefault("repository_id", repository.repository_id)
        details.setdefault("repository_path", repository.path)
        details.setdefault("phase", phase)
        if capture_pass is not None:
            details.setdefault("capture_pass", capture_pass)
        return DevFlowError(exc.code, exc.message, details=details)

    def _validate_repository_paths(
        self,
        repositories: Sequence[RepositoryRecord],
    ) -> tuple:
        records = validate_repositories(repositories)
        resolved = []
        for repository in records:
            try:
                root = Path(repository.path).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path cannot be resolved",
                    details={
                        "repository_id": repository.repository_id,
                        "repository_path": repository.path,
                        "error": str(exc),
                    },
                ) from exc
            if not root.is_dir():
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path is not a directory",
                    details={
                        "repository_id": repository.repository_id,
                        "repository_path": repository.path,
                    },
                )
            if str(root) != repository.path:
                raise DevFlowError(
                    "REPOSITORY_IDENTITY_MISMATCH",
                    "repository no longer resolves to its canonical task root",
                    details={
                        "repository_id": repository.repository_id,
                        "repository_path": repository.path,
                        "resolved_path": str(root),
                    },
                )
            if _paths_overlap(self.store.root, root):
                raise DevFlowError(
                    "DATA_DIR_INSIDE_REPOSITORY",
                    "controller data directory must remain outside target repositories",
                    details={
                        "data_dir": str(self.store.root),
                        "repository": str(root),
                        "repository_id": repository.repository_id,
                    },
                )
            resolved.append((repository, root))
        for index, (repository, root) in enumerate(resolved):
            for other, other_root in resolved[index + 1 :]:
                if _paths_overlap(root, other_root):
                    raise DevFlowError(
                        "REPOSITORY_OVERLAP",
                        "task repository roots must not overlap",
                        details={
                            "repository_ids": [
                                repository.repository_id,
                                other.repository_id,
                            ],
                            "repository_paths": [str(root), str(other_root)],
                        },
                    )
        return records

    def _capture_members(
        self,
        repositories: Sequence[RepositoryRecord],
        resources_by_id: Mapping[str, Sequence[Mapping[str, object]]],
        *,
        phase: str,
        capture_pass: int,
        verify_persisted_identity: bool = True,
    ) -> dict:
        records = self._validate_repository_paths(repositories)
        snapshots = {}
        common_directories = {}
        for repository in records:
            try:
                snapshot = validate_snapshot(
                    self.git.snapshot(
                        repository.path,
                        resources=resources_by_id.get(repository.repository_id, ()),
                    )
                )
                if snapshot["repository_root"] != repository.path:
                    raise DevFlowError(
                        "REPOSITORY_IDENTITY_MISMATCH",
                        "captured repository root does not match task membership",
                        details={
                            "captured_repository_root": snapshot["repository_root"],
                        },
                    )
                if verify_persisted_identity and (
                    snapshot["git_worktree_dir"] != repository.git_worktree_dir
                    or snapshot["git_common_dir"] != repository.git_common_dir
                ):
                    raise DevFlowError(
                        "REPOSITORY_IDENTITY_MISMATCH",
                        "captured Git identity does not match immutable task membership",
                        details={
                            "captured_git_worktree_dir": snapshot["git_worktree_dir"],
                            "expected_git_worktree_dir": repository.git_worktree_dir,
                            "captured_git_common_dir": snapshot["git_common_dir"],
                            "expected_git_common_dir": repository.git_common_dir,
                        },
                    )
                common_path = Path(snapshot["git_common_dir"]).resolve(strict=True)
                if not common_path.is_dir():
                    raise DevFlowError(
                        "REPOSITORY_INVALID",
                        "Git common directory is not a directory",
                        details={"git_common_dir": str(common_path)},
                    )
            except DevFlowError as exc:
                raise self._member_error(
                    exc,
                    repository,
                    phase=phase,
                    capture_pass=capture_pass,
                ) from exc
            except (OSError, RuntimeError) as exc:
                wrapped = DevFlowError(
                    "REPOSITORY_INVALID",
                    "Git common directory cannot be resolved",
                    details={"error": str(exc)},
                )
                raise self._member_error(
                    wrapped,
                    repository,
                    phase=phase,
                    capture_pass=capture_pass,
                ) from exc
            common_identity = str(common_path)
            other = common_directories.get(common_identity)
            if other is not None:
                raise DevFlowError(
                    "REPOSITORY_GIT_IDENTITY_DUPLICATE",
                    "task repositories must not share a Git common directory",
                    details={
                        "git_common_dir": common_identity,
                        "repository_ids": [other, repository.repository_id],
                        "phase": phase,
                        "capture_pass": capture_pass,
                    },
                )
            common_directories[common_identity] = repository.repository_id
            snapshots[repository.repository_id] = snapshot
        return snapshots

    @staticmethod
    def _changed_members(
        repositories: Sequence[RepositoryRecord],
        first: Mapping[str, object],
        second: Mapping[str, object],
    ) -> list:
        return [
            repository.repository_id
            for repository in repositories
            if first.get(repository.repository_id)
            != second.get(repository.repository_id)
        ]

    def _canonical_repositories(self, paths: Iterable[str]) -> tuple:
        if isinstance(paths, (str, bytes, Mapping)):
            raise DevFlowError(
                "REPOSITORY_COUNT_INVALID",
                "repositories must be a collection of repository roots",
            )
        try:
            supplied_paths = tuple(paths)
        except TypeError as exc:
            raise DevFlowError(
                "REPOSITORY_COUNT_INVALID",
                "repositories must be a collection of repository roots",
            ) from exc
        count = len(supplied_paths)
        if not MIN_REPOSITORY_COUNT <= count <= MAX_REPOSITORY_COUNT:
            raise DevFlowError(
                "REPOSITORY_COUNT_INVALID",
                "task repository count is outside the supported bound",
                details={
                    "minimum": MIN_REPOSITORY_COUNT,
                    "maximum": MAX_REPOSITORY_COUNT,
                    "repository_count": count,
                },
            )
        seen = {}
        repositories = []
        for input_index, supplied in enumerate(supplied_paths):
            if not isinstance(supplied, str) or not supplied:
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path must be a non-empty string",
                    details={"input_index": input_index},
                )
            try:
                path = Path(supplied).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path cannot be resolved",
                    details={
                        "input_index": input_index,
                        "path": supplied,
                        "error": str(exc),
                    },
                ) from exc
            if not path.is_dir():
                raise DevFlowError(
                    "REPOSITORY_INVALID",
                    "repository path is not a directory",
                    details={"input_index": input_index, "path": str(path)},
                )
            identity = str(path)
            if identity in seen:
                raise DevFlowError(
                    "REPOSITORY_DUPLICATE",
                    "repository inputs resolve to the same canonical root",
                    details={
                        "path": identity,
                        "input_indices": [seen[identity], input_index],
                    },
                )
            seen[identity] = input_index
            # Admission captures the authoritative Git identities below.  The
            # provisional values are never persisted.
            repositories.append(
                RepositoryRecord(_repository_id(path), identity, identity, identity)
            )
        records = canonical_repository_records(repositories)
        self._validate_repository_paths(records)
        resources_by_id = {record.repository_id: () for record in records}
        first = self._capture_members(
            records,
            resources_by_id,
            phase="admission",
            capture_pass=1,
            verify_persisted_identity=False,
        )
        second = self._capture_members(
            records,
            resources_by_id,
            phase="admission",
            capture_pass=2,
            verify_persisted_identity=False,
        )
        changed = self._changed_members(records, first, second)
        if changed:
            raise DevFlowError(
                "SNAPSHOT_UNSTABLE",
                "repository set changed during admission",
                details={"repository_ids": changed, "phase": "admission"},
            )
        persisted = canonical_repository_records(
            RepositoryRecord(
                repository.repository_id,
                repository.path,
                second[repository.repository_id]["git_worktree_dir"],
                second[repository.repository_id]["git_common_dir"],
            )
            for repository in records
        )
        self._validate_repository_paths(persisted)
        return persisted

    def _partition_resources(
        self,
        state: TaskState,
        resources: Sequence[Mapping[str, object]],
    ) -> dict:
        records = validate_repositories(state.repositories)
        partitions = {record.repository_id: [] for record in records}
        seen = set()
        for item in resources:
            if not isinstance(item, Mapping):
                raise DevFlowError(
                    "NODE_OUTPUT_INVALID",
                    "resource request must be an object",
                )
            fields = set(item)
            expected_fields = {"repository_id", "path", "role", "normalizer"}
            if fields != expected_fields:
                raise DevFlowError(
                    "NODE_OUTPUT_INVALID",
                    "resource request fields are invalid",
                    details={"fields": sorted(str(field) for field in fields)},
                )
            repository_id = item.get("repository_id")
            repository = repository_by_id(records, repository_id)
            normalized = {
                "path": item.get("path"),
                "role": item.get("role"),
                "normalizer": item.get("normalizer"),
            }
            identity = (
                repository.repository_id,
                normalized["path"],
                normalized["role"],
                normalized["normalizer"],
            )
            if identity in seen:
                continue
            seen.add(identity)
            partitions[repository.repository_id].append(normalized)
        return {
            repository_id: tuple(requests)
            for repository_id, requests in partitions.items()
        }

    def _snapshot(
        self,
        state: TaskState,
        *,
        additional_resources: Sequence[Mapping[str, object]] = (),
        include_current_resources: bool = True,
    ) -> Mapping[str, object]:
        current = current_resource_requests(state) if include_current_resources else ()
        task_paths = ()
        for record in reversed(state.records):
            artifact = record.get("artifact") if isinstance(record, Mapping) else None
            body = artifact.get("body") if isinstance(artifact, Mapping) else None
            manifest = body.get("task_change_manifest") if isinstance(body, Mapping) else None
            if isinstance(manifest, Mapping):
                task_paths = tuple(
                    {
                        "repository_id": entry["repository_id"],
                        "path": entry["path"],
                        "role": "reported",
                        "normalizer": "none",
                    }
                    for entry in manifest.get("entries", ())
                    if isinstance(entry, Mapping)
                )
                break
        resources = _merge_resources(current, task_paths, additional_resources)
        partitions = self._partition_resources(state, resources)
        first = self._capture_members(
            state.repositories,
            partitions,
            phase="snapshot",
            capture_pass=1,
        )
        second = self._capture_members(
            state.repositories,
            partitions,
            phase="snapshot",
            capture_pass=2,
        )
        changed = self._changed_members(state.repositories, first, second)
        if changed:
            raise DevFlowError(
                "SNAPSHOT_UNSTABLE",
                "repository set changed between complete capture passes",
                details={"repository_ids": changed, "phase": "snapshot"},
            )
        return make_repository_set_snapshot(state.repositories, second)

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
        repositories: Iterable[str],
        task_id: Optional[str] = None,
        contract: Optional[Mapping[str, object]] = None,
    ) -> TaskState:
        if not isinstance(requirement, str) or not requirement.strip():
            raise DevFlowError(
                "REQUIREMENT_INVALID", "requirement must not be empty"
        )
        clean_requirement = requirement.strip()
        definition = workflows.load_definition(workflow)
        delivery_contract = (
            minimal_contract(clean_requirement)
            if contract is None
            else validate_contract(contract, expected_revision=1)
        )
        requested_repositories = tuple(repositories)
        repository_records = self._canonical_repositories(requested_repositories)
        with self.store.membership_lock():
            locked_records = self._canonical_repositories(requested_repositories)
            if locked_records != repository_records:
                raise DevFlowError(
                    "SNAPSHOT_UNSTABLE",
                    "repository identities changed during task admission",
                )
            state = initial_state(
                task_id=task_id or "task-{}".format(uuid.uuid4().hex[:16]),
                requirement=clean_requirement,
                contract=delivery_contract,
                definition=definition,
                repositories=repository_records,
                timestamp=_utc_now(),
            )
            return self.store.create_admitted(state)

    def show(self, task_id: str) -> TaskState:
        return self.store.load(task_id)

    def show_view(self, task_id: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        try:
            snapshot = self._snapshot(state)
        except DevFlowError as exc:
            return task_view(
                state,
                definition,
                None,
                snapshot_error=exc.as_dict()["error"],
            )
        return task_view(state, definition, snapshot)

    def inspect_product(self) -> dict:
        """Return current product metadata for the integrated read-only surface."""
        return web_product_metadata(_utc_now())

    def inspect_tasks(
        self,
        *,
        query: str = "",
        statuses: Sequence[str] = (),
        workflows: Sequence[str] = (),
        repositories: Sequence[str] = (),
        terminal: Optional[bool] = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> dict:
        entries, diagnostics = self.store.inspect_inventory()
        return web_inventory_view(
            entries,
            diagnostics,
            _utc_now(),
            query=query,
            statuses=statuses,
            workflows=workflows,
            repositories=repositories,
            terminal=terminal,
            offset=offset,
            limit=limit,
        )

    def inspect_task(
        self,
        task_id: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> dict:
        state, definition = self.store.inspect_with_definition(task_id)
        return web_stored_task_view(
            state,
            definition,
            _utc_now(),
            offset=offset,
            limit=limit,
        )

    def inspect_live_task(
        self,
        task_id: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict:
        state, definition = self.store.inspect_with_definition(task_id)
        snapshot = None
        projection = None
        snapshot_error_code = None
        try:
            with GitClient.cancellation(cancel_event):
                snapshot = self._snapshot(state)
            projection = agent_projection(state, definition, snapshot)
        except DevFlowError as exc:
            snapshot_error_code = exc.code
        latest, latest_definition = self.store.inspect_with_definition(task_id)
        if (
            latest.revision != state.revision
            or latest.updated_at != state.updated_at
            or latest.product_identity != state.product_identity
            or latest_definition.identity != definition.identity
        ):
            raise DevFlowError(
                "VIEW_STALE",
                "task changed during live observation",
                details={
                    "task_id": task_id,
                    "observed_revision": state.revision,
                    "current_revision": latest.revision,
                },
            )
        return web_live_task_view(
            state,
            definition,
            _utc_now(),
            projection=projection,
            snapshot_error_code=snapshot_error_code,
            offset=offset,
            limit=limit,
        )

    def next(self, task_id: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        return self._projection(state, definition)

    def list_tasks(self) -> tuple:
        return self.store.list_states()

    def inventory_diagnostics(self) -> tuple:
        """Return read-only corruption diagnostics for the current namespace."""
        return self.store.inventory_diagnostics()

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
            requested = resource_requests(
                validated,
                repository_ids=tuple(
                    repository.repository_id for repository in state.repositories
                ),
            )
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
            "projection": agent_projection(committed, definition, snapshot),
        }

    def revise_contract(
        self,
        task_id: str,
        *,
        contract: Mapping[str, object],
        ownership_claims: Optional[Mapping[str, object]] = None,
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
                    ownership_claims=ownership_claims,
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
            "projection": agent_projection(committed, definition, snapshot),
        }

    def decide(
        self,
        task_id: str,
        *,
        decision: Mapping[str, object],
    ) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        snapshot = self._snapshot(state)
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
            "projection": agent_projection(committed, definition, snapshot),
        }

    def dispose_finding(
        self,
        task_id: str,
        *,
        disposition: Mapping[str, object],
        actor_authorized: bool,
    ) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        expands_contract = isinstance(disposition.get("next_contract"), Mapping)
        snapshot = self._snapshot(
            state,
            include_current_resources=not expands_contract,
        )
        try:
            committed = self.store.update(
                task_id,
                state.revision,
                lambda current: record_finding_disposition(
                    current,
                    definition,
                    disposition=disposition,
                    actor_authorized=actor_authorized,
                    snapshot=snapshot if expands_contract else None,
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
                "finding.dispose",
                committed.revision,
                committed.status,
                committed.current_node,
            ).as_dict(),
            "projection": agent_projection(committed, definition, snapshot),
        }

    def cancel(self, task_id: str, *, reason: str) -> dict:
        state, definition = self.store.load_with_definition(task_id)
        if is_terminal_state(state, definition):
            raise DevFlowError("ACTION_NOT_AVAILABLE", "task is already finished")
        cancel = definition.cancel_for(state.current_node)
        if cancel is None:
            raise DevFlowError(
                "ACTION_NOT_AVAILABLE",
                "current workflow stage does not declare cancellation",
                details={"current_node": state.current_node},
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
            if any(
                candidate == Path(repository.path)
                or Path(repository.path) in candidate.parents
                for repository in state.repositories
            ):
                matches.append(state)
        ordered = tuple(
            sorted(matches, key=lambda item: item.task_id.encode("utf-8"))
        )
        if len(ordered) > 1:
            raise DevFlowError(
                "LEASE_INTEGRITY_CONFLICT",
                "multiple active tasks claim the inspected repository path",
                details={
                    "path": str(candidate),
                    "task_ids": [state.task_id for state in ordered],
                },
            )
        return ordered
