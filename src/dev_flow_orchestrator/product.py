"""The one authoritative product and activation matrix."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Tuple


TASK_SCHEMA_VERSION = 4
WORKFLOW_VERSION = 4
WORKFLOW_IDS = ("full", "lite")
TOPOLOGIES = ("single-repository", "multi-repository")
WORKSPACE_STRATEGIES = ("in-place", "branch", "worktree")


@dataclass(frozen=True)
class Profile:
    """One exact workflow and repository-topology activation profile."""

    workflow_id: str
    workflow_version: int
    topology: str
    required_suites: Tuple[str, ...]

    @property
    def identity(self) -> str:
        return "{}@{}/{}".format(
            self.workflow_id,
            self.workflow_version,
            self.topology,
        )

    def as_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "topology": self.topology,
            "required_suites": list(self.required_suites),
        }


_FULL_SUITES = (
    "greenfield-skeleton",
    "greenfield-core-workflow",
    "greenfield-effect-recovery",
    "greenfield-adapters",
)
_LITE_SUITES = (
    "greenfield-skeleton",
    "greenfield-core-workflow",
    "greenfield-effect-recovery",
    "greenfield-adapters",
)
_MULTI_SUITE = "greenfield-multi-repository"

PROFILES: Mapping[Tuple[str, str], Profile] = MappingProxyType(
    {
        ("full", "single-repository"): Profile(
            "full",
            WORKFLOW_VERSION,
            "single-repository",
            _FULL_SUITES,
        ),
        ("full", "multi-repository"): Profile(
            "full",
            WORKFLOW_VERSION,
            "multi-repository",
            (*_FULL_SUITES, _MULTI_SUITE),
        ),
        ("lite", "single-repository"): Profile(
            "lite",
            WORKFLOW_VERSION,
            "single-repository",
            _LITE_SUITES,
        ),
        ("lite", "multi-repository"): Profile(
            "lite",
            WORKFLOW_VERSION,
            "multi-repository",
            (*_LITE_SUITES, _MULTI_SUITE),
        ),
    }
)

WORKSPACE_COMPATIBILITY: Mapping[Tuple[str, str], Tuple[str, ...]] = (
    MappingProxyType(
        {
            key: WORKSPACE_STRATEGIES
            for key in PROFILES
        }
    )
)


def topology_for_repository_count(repository_count: int) -> str:
    if repository_count < 1:
        raise ValueError("at least one repository is required")
    if repository_count == 1:
        return TOPOLOGIES[0]
    return TOPOLOGIES[1]


def uses_repository_kernel(topology: str) -> bool:
    if topology not in TOPOLOGIES:
        raise ValueError("unsupported repository topology")
    return topology == TOPOLOGIES[1]


def select_profile(
    workflow_id: str,
    repository_count: int,
    workspace_strategy: str,
) -> Profile:
    topology = topology_for_repository_count(repository_count)
    profile = PROFILES.get((workflow_id, topology))
    if profile is None:
        raise ValueError("unsupported workflow or repository topology")
    allowed_workspaces = WORKSPACE_COMPATIBILITY[(workflow_id, topology)]
    if workspace_strategy not in allowed_workspaces:
        raise ValueError("unsupported workflow, topology and workspace combination")
    return profile


def product_document() -> dict:
    return {
        "plugin": "dev-flow-orchestrator",
        "task_schema_version": TASK_SCHEMA_VERSION,
        "profiles": [
            PROFILES[key].as_dict()
            for key in sorted(PROFILES)
        ],
        "workspace_compatibility": [
            {
                "workflow_id": key[0],
                "topology": key[1],
                "workspace_strategies": list(WORKSPACE_COMPATIBILITY[key]),
            }
            for key in sorted(WORKSPACE_COMPATIBILITY)
        ],
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


PRODUCT_IDENTITY = hashlib.sha256(
    b"dev-flow-greenfield-product-v1\x00"
    + _canonical_bytes(product_document())
).hexdigest()
