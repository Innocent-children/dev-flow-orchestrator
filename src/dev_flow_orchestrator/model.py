"""Current V5 domain values with no infrastructure dependency."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Optional, Tuple

from .product import PRODUCT_IDENTITY, TASK_SCHEMA_VERSION, WORKFLOW_VERSION

if TYPE_CHECKING:
    from .workflow import WorkflowDefinition


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
            {
                str(key): freeze_json(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


def json_value(value: object) -> object:
    """Deep-convert a frozen value back to plain lists and dicts."""
    if isinstance(value, Mapping):
        return {
            str(key): json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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
    preflight: Optional[Mapping[str, object]] = None

    def __post_init__(self) -> None:
        if self.preflight is not None:
            object.__setattr__(self, "preflight", freeze_json(self.preflight))

    def as_dict(self) -> dict:
        return {
            "id": self.repository_id,
            "path": self.path,
            "preflight": (
                None
                if self.preflight is None
                else json_value(self.preflight)
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> "RepositoryRecord":
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "repository record must be an object")
        repository_id = value.get("id")
        path = value.get("path")
        preflight = value.get("preflight")
        if not isinstance(repository_id, str) or not isinstance(path, str):
            raise DevFlowError("STATE_INVALID", "repository identity is invalid")
        if preflight is not None and not isinstance(preflight, dict):
            raise DevFlowError("STATE_INVALID", "repository preflight is invalid")
        return cls(repository_id, path, preflight)


@dataclass(frozen=True)
class TaskState:
    task_id: str
    requirement: str
    revision: int
    created_at: str
    updated_at: str
    workflow_id: str
    workflow_version: int
    workflow_identity: str
    status: str
    current_node: str
    repositories: Tuple[RepositoryRecord, ...]
    evidence: Tuple[object, ...] = ()
    schema_version: int = TASK_SCHEMA_VERSION
    product_identity: str = PRODUCT_IDENTITY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence",
            tuple(freeze_json(value) for value in self.evidence),
        )

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "product_identity": self.product_identity,
            "task_id": self.task_id,
            "requirement": self.requirement,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workflow": {
                "id": self.workflow_id,
                "version": self.workflow_version,
                "identity": self.workflow_identity,
            },
            "status": self.status,
            "current_node": self.current_node,
            "repositories": [
                repository.as_dict()
                for repository in self.repositories
            ],
            "evidence": [
                json_value(item)
                for item in self.evidence
            ],
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        definition: Optional["WorkflowDefinition"] = None,
    ) -> "TaskState":
        """Rebuild task state from a stored JSON value.

        ``definition`` is the loaded ``WorkflowDefinition``; when provided
        the pinned workflow version and identity are verified against it.
        """
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
        workflow = value.get("workflow")
        repositories = value.get("repositories")
        if not isinstance(workflow, dict):
            raise DevFlowError("STATE_INVALID", "task product selection is invalid")
        if not isinstance(repositories, list) or len(repositories) != 1:
            raise DevFlowError(
                "STATE_INVALID",
                "task must have exactly one repository",
            )
        task_id = validate_task_id(value.get("task_id"))
        requirement = value.get("requirement")
        revision = value.get("revision")
        if not isinstance(requirement, str) or not requirement:
            raise DevFlowError("STATE_INVALID", "task requirement is invalid")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise DevFlowError("STATE_INVALID", "task revision is invalid")
        scalar_fields = {
            "created_at": value.get("created_at"),
            "updated_at": value.get("updated_at"),
            "workflow_id": workflow.get("id"),
            "workflow_identity": workflow.get("identity"),
            "status": value.get("status"),
            "current_node": value.get("current_node"),
        }
        if any(not isinstance(item, str) or not item for item in scalar_fields.values()):
            raise DevFlowError("STATE_INVALID", "task scalar field is invalid")
        workflow_version = workflow.get("version")
        if workflow_version != WORKFLOW_VERSION:
            raise DevFlowError("STATE_INVALID", "task workflow identity is invalid")
        if definition is not None:
            if workflow_version != definition.version:
                raise DevFlowError(
                    "WORKFLOW_IDENTITY_MISMATCH",
                    "task workflow version is not installed",
                )
            if scalar_fields["workflow_identity"] != definition.identity:
                raise DevFlowError(
                    "WORKFLOW_IDENTITY_MISMATCH",
                    "task workflow identity is not installed",
                )
        evidence = value.get("evidence")
        if not isinstance(evidence, list):
            raise DevFlowError("STATE_INVALID", "task evidence is invalid")
        return cls(
            task_id=task_id,
            requirement=requirement,
            revision=revision,
            created_at=scalar_fields["created_at"],
            updated_at=scalar_fields["updated_at"],
            workflow_id=scalar_fields["workflow_id"],
            workflow_version=workflow_version,
            workflow_identity=scalar_fields["workflow_identity"],
            status=scalar_fields["status"],
            current_node=scalar_fields["current_node"],
            repositories=tuple(
                RepositoryRecord.from_dict(item)
                for item in repositories
            ),
            evidence=tuple(evidence),
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
            "schema": "dev-flow-v5-receipt/v1",
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
    definition: "WorkflowDefinition",
    repository: RepositoryRecord,
    timestamp: str,
) -> TaskState:
    validate_task_id(task_id)
    if not requirement:
        raise DevFlowError("REQUIREMENT_INVALID", "requirement must not be empty")
    return TaskState(
        task_id=task_id,
        requirement=requirement,
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
        workflow_id=definition.workflow_id,
        workflow_version=definition.version,
        workflow_identity=definition.identity,
        status="INTAKE",
        current_node=definition.entry_node,
        repositories=(repository,),
    )
