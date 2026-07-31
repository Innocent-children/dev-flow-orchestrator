"""Current V4 domain values with no infrastructure dependency."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple

from .product import (
    PRODUCT_IDENTITY,
    TASK_SCHEMA_VERSION,
    Profile,
    select_profile,
)


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


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _json_value(value),
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
    workspace: Optional[Mapping[str, object]] = None

    def __post_init__(self) -> None:
        for field_name in ("preflight", "workspace"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _freeze_json(value),
                )

    def as_dict(self) -> dict:
        return {
            "id": self.repository_id,
            "path": self.path,
            "preflight": (
                None
                if self.preflight is None
                else _json_value(self.preflight)
            ),
            "workspace": (
                None
                if self.workspace is None
                else _json_value(self.workspace)
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> "RepositoryRecord":
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "repository record must be an object")
        repository_id = value.get("id")
        path = value.get("path")
        preflight = value.get("preflight")
        workspace = value.get("workspace")
        if not isinstance(repository_id, str) or not isinstance(path, str):
            raise DevFlowError("STATE_INVALID", "repository identity is invalid")
        if preflight is not None and not isinstance(preflight, dict):
            raise DevFlowError("STATE_INVALID", "repository preflight is invalid")
        if workspace is not None and not isinstance(workspace, dict):
            raise DevFlowError("STATE_INVALID", "repository workspace is invalid")
        return cls(repository_id, path, preflight, workspace)


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
    topology: str
    workspace_strategy: str
    required_suites: Tuple[str, ...]
    status: str
    current_node: str
    repositories: Tuple[RepositoryRecord, ...]
    approvals: Tuple[object, ...] = ()
    evidence: Tuple[object, ...] = ()
    effects: Tuple[object, ...] = ()
    orchestration: Optional[Mapping[str, object]] = None
    schema_version: int = TASK_SCHEMA_VERSION
    product_identity: str = PRODUCT_IDENTITY

    def __post_init__(self) -> None:
        for field_name in ("approvals", "evidence", "effects"):
            object.__setattr__(
                self,
                field_name,
                tuple(
                    _freeze_json(value)
                    for value in getattr(self, field_name)
                ),
            )
        if self.orchestration is not None:
            object.__setattr__(
                self,
                "orchestration",
                _freeze_json(self.orchestration),
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
                "topology": self.topology,
                "required_suites": list(self.required_suites),
            },
            "workspace": {"strategy": self.workspace_strategy},
            "status": self.status,
            "current_node": self.current_node,
            "repositories": [
                repository.as_dict()
                for repository in self.repositories
            ],
            "approvals": [
                _json_value(item)
                for item in self.approvals
            ],
            "evidence": [
                _json_value(item)
                for item in self.evidence
            ],
            "effects": [
                _json_value(item)
                for item in self.effects
            ],
            "orchestration": (
                None
                if self.orchestration is None
                else _json_value(self.orchestration)
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> "TaskState":
        if not isinstance(value, dict):
            raise DevFlowError("STATE_INVALID", "task state must be an object")
        workflow = value.get("workflow")
        workspace = value.get("workspace")
        repositories = value.get("repositories")
        if value.get("schema_version") != TASK_SCHEMA_VERSION:
            raise DevFlowError("STATE_INVALID", "task state is not current schema v4")
        if value.get("product_identity") != PRODUCT_IDENTITY:
            raise DevFlowError("PRODUCT_IDENTITY_MISMATCH", "task product identity is not installed")
        if not isinstance(workflow, dict) or not isinstance(workspace, dict):
            raise DevFlowError("STATE_INVALID", "task product selection is invalid")
        if not isinstance(repositories, list) or not repositories:
            raise DevFlowError("STATE_INVALID", "task repositories are invalid")
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
            "topology": workflow.get("topology"),
            "workspace_strategy": workspace.get("strategy"),
            "status": value.get("status"),
            "current_node": value.get("current_node"),
        }
        if any(not isinstance(item, str) or not item for item in scalar_fields.values()):
            raise DevFlowError("STATE_INVALID", "task scalar field is invalid")
        workflow_version = workflow.get("version")
        suites = workflow.get("required_suites")
        if workflow_version != 4 or not isinstance(suites, list):
            raise DevFlowError("STATE_INVALID", "task workflow identity is invalid")
        try:
            profile = select_profile(
                scalar_fields["workflow_id"],
                len(repositories),
                scalar_fields["workspace_strategy"],
            )
        except ValueError as exc:
            raise DevFlowError(
                "STATE_INVALID",
                "task product selection is invalid",
            ) from exc
        if (
            profile.topology != scalar_fields["topology"]
            or profile.workflow_version != workflow_version
            or profile.required_suites != tuple(suites)
        ):
            raise DevFlowError(
                "STATE_INVALID",
                "task profile does not match the current product matrix",
            )
        from .workflow import workflow_identity

        if scalar_fields["workflow_identity"] != workflow_identity(
            scalar_fields["workflow_id"],
            scalar_fields["topology"],
        ):
            raise DevFlowError(
                "WORKFLOW_IDENTITY_MISMATCH",
                "task workflow identity is not installed",
            )
        collections = {
            "approvals": value.get("approvals"),
            "evidence": value.get("evidence"),
            "effects": value.get("effects"),
        }
        if any(not isinstance(item, list) for item in collections.values()):
            raise DevFlowError("STATE_INVALID", "task collection is invalid")
        orchestration = value.get("orchestration")
        if orchestration is not None and not isinstance(orchestration, dict):
            raise DevFlowError("STATE_INVALID", "task orchestration is invalid")
        return cls(
            task_id=task_id,
            requirement=requirement,
            revision=revision,
            created_at=scalar_fields["created_at"],
            updated_at=scalar_fields["updated_at"],
            workflow_id=scalar_fields["workflow_id"],
            workflow_version=workflow_version,
            workflow_identity=scalar_fields["workflow_identity"],
            topology=scalar_fields["topology"],
            workspace_strategy=scalar_fields["workspace_strategy"],
            required_suites=tuple(str(item) for item in suites),
            status=scalar_fields["status"],
            current_node=scalar_fields["current_node"],
            repositories=tuple(
                RepositoryRecord.from_dict(item)
                for item in repositories
            ),
            approvals=tuple(collections["approvals"]),
            evidence=tuple(collections["evidence"]),
            effects=tuple(collections["effects"]),
            orchestration=orchestration,
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
    authority_id: Optional[str] = None
    actor_id: Optional[str] = None

    @property
    def binding(self) -> str:
        value = {
            "action_id": self.action_id,
            "task_id": self.task_id,
            "expected_revision": self.expected_revision,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "effect_kind": self.effect_kind,
            "allowed_writes": list(self.allowed_writes),
        }
        return hashlib.sha256(
            b"dev-flow-greenfield-mutation-plan-v1\x00"
            + canonical_json_bytes(value)
        ).hexdigest()


@dataclass(frozen=True)
class NodeDecision:
    action_id: str
    eligible: bool
    reason: Optional[str]
    plan: Optional[MutationPlan]


@dataclass(frozen=True)
class MutationReceipt:
    task_id: str
    action_id: str
    committed_revision: int
    status: str
    current_node: str
    changed_sections: Tuple[str, ...]
    plan_binding: str
    confirmation: Optional[Mapping[str, object]] = None

    def __post_init__(self) -> None:
        if self.confirmation is not None:
            object.__setattr__(
                self,
                "confirmation",
                _freeze_json(self.confirmation),
            )

    def as_dict(self) -> dict:
        value = {
            "schema": "dev-flow-v4-receipt/v1",
            "task_id": self.task_id,
            "action_id": self.action_id,
            "committed_revision": self.committed_revision,
            "status": self.status,
            "current_node": self.current_node,
            "changed_sections": list(self.changed_sections),
            "plan_binding": self.plan_binding,
        }
        if self.confirmation is not None:
            value["confirmation"] = _json_value(self.confirmation)
        return value


def initial_state(
    *,
    task_id: str,
    requirement: str,
    profile: Profile,
    workspace_strategy: str,
    repositories: Sequence[RepositoryRecord],
    timestamp: str,
) -> TaskState:
    validate_task_id(task_id)
    if not requirement:
        raise DevFlowError("REQUIREMENT_INVALID", "requirement must not be empty")
    if not repositories:
        raise DevFlowError("REPOSITORY_REQUIRED", "at least one repository is required")
    from .workflow import workflow_identity

    return TaskState(
        task_id=task_id,
        requirement=requirement,
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
        workflow_id=profile.workflow_id,
        workflow_version=profile.workflow_version,
        workflow_identity=workflow_identity(
            profile.workflow_id,
            profile.topology,
        ),
        topology=profile.topology,
        workspace_strategy=workspace_strategy,
        required_suites=profile.required_suites,
        status="INTAKE",
        current_node="preflight",
        repositories=tuple(repositories),
    )
