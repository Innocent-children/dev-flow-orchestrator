"""Authoritative product version, identities, and official workflow catalog."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Tuple


PRODUCT_VERSION = "0.2.0"
WORKFLOW_IDS: Tuple[str, ...] = (
    "bugfix",
    "feature",
    "full",
    "investigation",
    "lite",
    "refactor",
)
PLUGIN_DATA_NAMESPACE = PRODUCT_VERSION
OPENSPEC_TASKS_NORMALIZER = "openspec-tasks/{}".format(PRODUCT_VERSION)


def product_schema(kind: str) -> str:
    """Return one typed identifier under the sole product version."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("product schema kind must not be empty")
    return "dev-flow-{}/{}".format(kind, PRODUCT_VERSION)


def product_domain(kind: str) -> bytes:
    """Return the digest domain paired with a typed product identifier."""
    return product_schema(kind).encode("ascii") + b"\x00"


TASK_IDENTITY = product_schema("task")
RECORD_SCHEMA = product_schema("record")
ARTIFACT_SCHEMA = product_schema("artifact")
ACTION_BINDING_SCHEMA = product_schema("action-binding")
WORKSPACE_SNAPSHOT_SCHEMA = product_schema("workspace-snapshot")
REPOSITORY_SET_SNAPSHOT_SCHEMA = product_schema("repository-set-snapshot")
WORKFLOW_SCHEMA = product_schema("workflow")
AGENT_PROTOCOL_SCHEMA = product_schema("agent")
VERIFICATION_COVERAGE_SCHEMA = product_schema("verification-coverage")
DELIVERY_DOSSIER_SCHEMA = product_schema("delivery-dossier")
DELIVERY_CONTRACT_SCHEMA = product_schema("delivery-contract")
RECEIPT_SCHEMA = product_schema("receipt")
DRIVER_RESULT_SCHEMA = product_schema("driver-result")
IMPACT_REPORT_SCHEMA = product_schema("impact-report")
INDEPENDENT_REVIEW_SCHEMA = product_schema("independent-review")
INSTALLED_EVIDENCE_SCHEMA = product_schema("installed-evidence")
EXTERNAL_EVIDENCE_SCHEMA = product_schema("external-evidence")
TREE_SNAPSHOT_SCHEMA = product_schema("tree-snapshot")
REPOSITORY_TOPOLOGY_SCHEMA = product_schema("repository-topology-capabilities")

MIN_REPOSITORY_COUNT = 1
MAX_REPOSITORY_COUNT = 8

# Runtime/package authority for the independently selectable repository axis.
REPOSITORY_TOPOLOGY_CAPABILITIES = MappingProxyType(
    {
        "schema": REPOSITORY_TOPOLOGY_SCHEMA,
        "minimum_repositories": MIN_REPOSITORY_COUNT,
        "maximum_repositories": MAX_REPOSITORY_COUNT,
        "membership": "exact-canonical-set",
        "caller_order": "non-semantic",
        "worktrees": "user-prepared",
        "execution": "single-codex-single-current-action",
        "managed_git_effects": False,
        "partial_assurance_reuse": False,
        "external_delivery_effects": False,
    }
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def product_document() -> dict:
    """Identity vocabulary for persisted tasks under the current version.

    The official catalog deliberately has its own identity so adding an
    unrelated built-in does not invalidate a task's selected workflow.
    """
    return {
        "plugin": "dev-flow-orchestrator",
        "version": PRODUCT_VERSION,
        "schemas": {
            "task": TASK_IDENTITY,
            "record": RECORD_SCHEMA,
            "artifact": ARTIFACT_SCHEMA,
            "action_binding": ACTION_BINDING_SCHEMA,
            "workspace_member_snapshot": WORKSPACE_SNAPSHOT_SCHEMA,
            "repository_set_snapshot": REPOSITORY_SET_SNAPSHOT_SCHEMA,
            "workflow": WORKFLOW_SCHEMA,
            "agent_projection": AGENT_PROTOCOL_SCHEMA,
            "verification_coverage": VERIFICATION_COVERAGE_SCHEMA,
            "delivery_dossier": DELIVERY_DOSSIER_SCHEMA,
            "delivery_contract": DELIVERY_CONTRACT_SCHEMA,
            "receipt": RECEIPT_SCHEMA,
            "driver_result": DRIVER_RESULT_SCHEMA,
            "impact_report": IMPACT_REPORT_SCHEMA,
            "independent_review": INDEPENDENT_REVIEW_SCHEMA,
            "installed_evidence": INSTALLED_EVIDENCE_SCHEMA,
            "external_evidence": EXTERNAL_EVIDENCE_SCHEMA,
            "tree_snapshot": TREE_SNAPSHOT_SCHEMA,
        },
        "repository_topology": dict(REPOSITORY_TOPOLOGY_CAPABILITIES),
        "plugin_data_namespace": PLUGIN_DATA_NAMESPACE,
        "openspec_tasks_normalizer": OPENSPEC_TASKS_NORMALIZER,
    }


PRODUCT_IDENTITY = hashlib.sha256(
    product_domain("product-identity") + _canonical_bytes(product_document())
).hexdigest()

CATALOG_IDENTITY = hashlib.sha256(
    product_domain("catalog-identity")
    + _canonical_bytes({"workflow_ids": list(WORKFLOW_IDS)})
).hexdigest()
