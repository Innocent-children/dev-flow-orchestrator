"""Immutable current-product domain values with no infrastructure dependency."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Iterable, Mapping, Optional, Tuple

from .product import (
    MAX_REPOSITORY_COUNT,
    MIN_REPOSITORY_COUNT,
    PRODUCT_IDENTITY,
    PRODUCT_VERSION,
    RECEIPT_SCHEMA,
    WORKFLOW_SCHEMA,
    product_domain,
)

if TYPE_CHECKING:
    from .workflow import WorkflowDefinition


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPOSITORY_SET_ID_DOMAIN = product_domain("repository-set-identity")


class DevFlowError(Exception):
    """Stable current-product failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": dict(self.details),
            },
        }


def freeze_json(value: object) -> object:
    """Deep-freeze a parsed JSON value for immutable storage."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def json_value(value: object) -> object:
    """Deep-convert a frozen value back to plain lists and dicts."""
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def strict_json_loads(text: str) -> object:
    """Parse strict JSON, rejecting duplicate keys and non-finite numbers."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key: {}".format(key))
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite JSON number: {}".format(value))

    return json.loads(
        text,
        object_pairs_hook=pairs,
        parse_constant=constant,
    )


def validate_task_id(task_id: str) -> str:
    if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
        raise DevFlowError(
            "TASK_ID_INVALID",
            "task id must be 1-64 portable characters",
            details={"task_id": task_id if isinstance(task_id, str) else None},
        )
    return task_id


@dataclass(frozen=True)
class RepositoryRecord:
    repository_id: str
    path: str
    git_worktree_dir: str
    git_common_dir: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository_id, str)
            or not self.repository_id
            or "\x00" in self.repository_id
        ):
            raise DevFlowError("STATE_INVALID", "repository identity is invalid")
        try:
            self.repository_id.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise DevFlowError(
                "STATE_INVALID", "repository identity is not UTF-8"
            ) from exc
        for field, value in (
            ("path", self.path),
            ("git_worktree_dir", self.git_worktree_dir),
            ("git_common_dir", self.git_common_dir),
        ):
            if (
                not isinstance(value, str)
                or not value
                or not os.path.isabs(value)
                or "\x00" in value
                or os.path.normpath(value) != value
            ):
                raise DevFlowError(
                    "STATE_INVALID", "repository {} is invalid".format(field)
                )
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise DevFlowError(
                    "STATE_INVALID", "repository {} is not UTF-8".format(field)
                ) from exc

    def as_dict(self) -> dict:
        return {
            "id": self.repository_id,
            "path": self.path,
            "git_worktree_dir": self.git_worktree_dir,
            "git_common_dir": self.git_common_dir,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RepositoryRecord":
        if not isinstance(value, dict) or set(value) != {
            "id", "path", "git_worktree_dir", "git_common_dir"
        }:
            raise DevFlowError("STATE_INVALID", "repository record is invalid")
        return cls(
            value.get("id"),
            value.get("path"),
            value.get("git_worktree_dir"),
            value.get("git_common_dir"),
        )


def repository_order_key(repository: RepositoryRecord) -> tuple:
    """Return the byte-stable persisted repository ordering key."""
    if not isinstance(repository, RepositoryRecord):
        raise DevFlowError("STATE_INVALID", "repository record is invalid")
    return (repository.path.encode("utf-8"), repository.repository_id.encode("utf-8"))


def validate_repositories(
    repositories: object,
    *,
    require_canonical: bool = True,
) -> Tuple[RepositoryRecord, ...]:
    """Validate the exact persisted repository tuple without filesystem access."""
    if isinstance(repositories, (str, bytes, Mapping)):
        raise DevFlowError("STATE_INVALID", "task repositories are invalid")
    try:
        items = tuple(repositories)  # type: ignore[arg-type]
    except TypeError as exc:
        raise DevFlowError("STATE_INVALID", "task repositories are invalid") from exc
    if not MIN_REPOSITORY_COUNT <= len(items) <= MAX_REPOSITORY_COUNT:
        raise DevFlowError(
            "STATE_INVALID",
            "task repository count is invalid",
            details={
                "minimum": MIN_REPOSITORY_COUNT,
                "maximum": MAX_REPOSITORY_COUNT,
                "repository_count": len(items),
            },
        )
    if any(not isinstance(item, RepositoryRecord) for item in items):
        raise DevFlowError("STATE_INVALID", "repository record is invalid")
    repository_ids = [item.repository_id for item in items]
    paths = [item.path for item in items]
    git_worktree_dirs = [item.git_worktree_dir for item in items]
    if len(set(repository_ids)) != len(repository_ids):
        raise DevFlowError("STATE_INVALID", "repository identities are not unique")
    if len(set(paths)) != len(paths):
        raise DevFlowError("STATE_INVALID", "repository paths are not unique")
    if len(set(git_worktree_dirs)) != len(git_worktree_dirs):
        raise DevFlowError(
            "STATE_INVALID", "repository worktree Git directories are not unique"
        )
    canonical = tuple(sorted(items, key=repository_order_key))
    if require_canonical and items != canonical:
        raise DevFlowError("STATE_INVALID", "task repositories are not canonical")
    return items


def canonical_repositories(
    repositories: Iterable[RepositoryRecord],
) -> Tuple[RepositoryRecord, ...]:
    """Validate and canonically order a candidate exact repository set."""
    items = validate_repositories(repositories, require_canonical=False)
    return tuple(sorted(items, key=repository_order_key))


def repository_set_id(repositories: object) -> str:
    """Derive the domain-separated identity of an ordered repository tuple."""
    items = validate_repositories(repositories)
    return hashlib.sha256(
        _REPOSITORY_SET_ID_DOMAIN
        + canonical_json_bytes([item.as_dict() for item in items])
    ).hexdigest()


def repository_by_id(
    repositories: object,
    repository_id: object,
) -> RepositoryRecord:
    """Resolve a persisted member without inferring a default repository."""
    items = validate_repositories(repositories)
    if isinstance(repository_id, str):
        for item in items:
            if item.repository_id == repository_id:
                return item
    raise DevFlowError(
        "REPOSITORY_UNKNOWN",
        "repository identity is not a task member",
        details={"repository_id": repository_id if isinstance(repository_id, str) else None},
    )


@dataclass(frozen=True)
class TaskState:
    task_id: str
    requirement: str
    revision: int
    created_at: str
    updated_at: str
    workflow_id: str
    workflow_version: str
    workflow_schema: str
    workflow_identity: str
    status: str
    current_node: str
    repositories: Tuple[RepositoryRecord, ...]
    original_contract: Mapping[str, object]
    records: Tuple[object, ...] = ()
    version: str = PRODUCT_VERSION
    product_identity: str = PRODUCT_IDENTITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repositories",
            validate_repositories(self.repositories),
        )
        object.__setattr__(self, "original_contract", freeze_json(self.original_contract))
        object.__setattr__(
            self,
            "records",
            tuple(freeze_json(value) for value in self.records),
        )

    @property
    def repository_set_id(self) -> str:
        return repository_set_id(self.repositories)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "product_identity": self.product_identity,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workflow": {
                "id": self.workflow_id,
                "version": self.workflow_version,
                "schema": self.workflow_schema,
                "identity": self.workflow_identity,
            },
            "status": self.status,
            "current_node": self.current_node,
            "repositories": [item.as_dict() for item in self.repositories],
            "original_contract": json_value(self.original_contract),
            "records": [json_value(item) for item in self.records],
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        definition: Optional["WorkflowDefinition"] = None,
    ) -> "TaskState":
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "task state must be an object")
        expected_fields = {
            "version",
            "product_identity",
            "task_id",
            "requirement",
            "revision",
            "created_at",
            "updated_at",
            "workflow",
            "status",
            "current_node",
            "repositories",
            "original_contract",
            "records",
        }
        if set(value) != expected_fields:
            raise DevFlowError(
                "STATE_INVALID",
                "task state fields are invalid",
                details={"fields": sorted(str(field) for field in value)},
            )
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
        workflow = value.get("workflow")
        repositories = value.get("repositories")
        if not isinstance(workflow, dict) or set(workflow) != {
            "id",
            "version",
            "schema",
            "identity",
        }:
            raise DevFlowError("STATE_INVALID", "task workflow selection is invalid")
        if not isinstance(repositories, list):
            raise DevFlowError("STATE_INVALID", "task repositories are invalid")
        repository_records = validate_repositories(
            tuple(RepositoryRecord.from_dict(item) for item in repositories)
        )
        task_id = validate_task_id(value.get("task_id"))
        requirement = value.get("requirement")
        revision = value.get("revision")
        records = value.get("records")
        contract = value.get("original_contract")
        if not isinstance(requirement, str) or not requirement.strip():
            raise DevFlowError("STATE_INVALID", "task requirement is invalid")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise DevFlowError("STATE_INVALID", "task revision is invalid")
        if not isinstance(records, list) or revision != len(records):
            raise DevFlowError("STATE_INVALID", "task record ledger is invalid")
        if not isinstance(contract, dict):
            raise DevFlowError("STATE_INVALID", "original delivery contract is invalid")
        from .delivery import validate_contract

        validate_contract(contract, expected_revision=1, state_error=True)
        scalar_fields = {
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
            "workflow_id": workflow.get("id"),
            "workflow_schema": workflow.get("schema"),
            "workflow_identity": workflow.get("identity"),
            "status": value.get("status"),
            "current_node": value.get("current_node"),
        }
        if any(not isinstance(item, str) or not item for item in scalar_fields.values()):
            raise DevFlowError("STATE_INVALID", "task scalar field is invalid")
        workflow_version = workflow.get("version")
        if not isinstance(workflow_version, str):
            raise DevFlowError("STATE_INVALID", "task workflow version is invalid")
        if (
            workflow_version != PRODUCT_VERSION
            or scalar_fields["workflow_schema"] != WORKFLOW_SCHEMA
        ):
            raise DevFlowError(
                "WORKFLOW_IDENTITY_MISMATCH",
                "task workflow language is not installed",
            )
        if definition is not None:
            checks = (
                (scalar_fields["workflow_id"], definition.workflow_id),
                (workflow_version, definition.version),
                (scalar_fields["workflow_schema"], definition.schema),
                (scalar_fields["workflow_identity"], definition.identity),
            )
            if any(stored != loaded for stored, loaded in checks):
                raise DevFlowError(
                    "WORKFLOW_IDENTITY_MISMATCH",
                    "task workflow identity is not installed",
                )
        return cls(
            task_id=task_id,
            requirement=requirement,
            revision=revision,
            created_at=scalar_fields["created_at"],
            updated_at=scalar_fields["updated_at"],
            workflow_id=scalar_fields["workflow_id"],
            workflow_version=workflow_version,
            workflow_schema=scalar_fields["workflow_schema"],
            workflow_identity=scalar_fields["workflow_identity"],
            status=scalar_fields["status"],
            current_node=scalar_fields["current_node"],
            repositories=repository_records,
            original_contract=contract,
            records=tuple(records),
        )


@dataclass(frozen=True)
class MutationPlan:
    action_id: str
    task_id: str
    expected_revision: int
    source_node: str
    target_node: str
    effect_kind: str
    allowed_writes: Tuple[str, ...]


@dataclass(frozen=True)
class MutationReceipt:
    task_id: str
    action_id: str
    committed_revision: int
    status: str
    current_node: str

    def as_dict(self) -> dict:
        return {
            "schema": RECEIPT_SCHEMA,
            "task_id": self.task_id,
            "action_id": self.action_id,
            "committed_revision": self.committed_revision,
            "status": self.status,
            "current_node": self.current_node,
        }


def initial_state(
    *,
    task_id: str,
    requirement: str,
    contract: Mapping[str, object],
    definition: "WorkflowDefinition",
    repositories: Iterable[RepositoryRecord],
    timestamp: str,
) -> TaskState:
    validate_task_id(task_id)
    if not isinstance(requirement, str) or not requirement.strip():
        raise DevFlowError("REQUIREMENT_INVALID", "requirement must not be empty")
    from .delivery import validate_contract

    validated_contract = validate_contract(contract, expected_revision=1)
    repository_records = canonical_repositories(repositories)
    return TaskState(
        task_id=task_id,
        requirement=requirement.strip(),
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
        workflow_id=definition.workflow_id,
        workflow_version=definition.version,
        workflow_schema=definition.schema,
        workflow_identity=definition.identity,
        status="INTAKE",
        current_node=definition.entry_node,
        repositories=repository_records,
        original_contract=validated_contract,
    )
