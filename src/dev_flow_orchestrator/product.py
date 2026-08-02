"""Authoritative V6 product identities and official workflow catalog."""

from __future__ import annotations

import hashlib
import json
from typing import Tuple


TASK_SCHEMA_VERSION = 6
WORKFLOW_VERSION = 6
WORKFLOW_IDS: Tuple[str, ...] = (
    "bugfix",
    "feature",
    "full",
    "investigation",
    "lite",
    "refactor",
)
PLUGIN_DATA_NAMESPACE = "v6"

TASK_IDENTITY = "dev-flow-task/v6"
WORKFLOW_V1_ADAPTER_IDENTITY = "dev-flow-workflow-v1-adapter/v1"
WORKFLOW_V2_ADAPTER_IDENTITY = "dev-flow-workflow-v2-adapter/v1"
RECORD_SCHEMA = "dev-flow-record/v1"
ARTIFACT_SCHEMA = "dev-flow-artifact/v1"
ACTION_BINDING_SCHEMA = "dev-flow-action-binding/v1"
AGENT_PROTOCOL_SCHEMA = "dev-flow-agent-v2"
WORKSPACE_SNAPSHOT_SCHEMA = "dev-flow-workspace-snapshot/v1"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def product_document() -> dict:
    """Identity vocabulary for persisted V6 tasks.

    The official catalog deliberately has its own identity so adding an
    unrelated built-in does not invalidate a task's selected workflow.
    """
    return {
        "plugin": "dev-flow-orchestrator",
        "generation": 6,
        "task_identity": TASK_IDENTITY,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "record_schema": RECORD_SCHEMA,
        "artifact_schema": ARTIFACT_SCHEMA,
        "plugin_data_namespace": PLUGIN_DATA_NAMESPACE,
    }


PRODUCT_IDENTITY = hashlib.sha256(
    b"dev-flow-v6-product-identity/v1\x00" + _canonical_bytes(product_document())
).hexdigest()

CATALOG_IDENTITY = hashlib.sha256(
    b"dev-flow-v6-catalog-identity/v1\x00"
    + _canonical_bytes({"workflow_ids": list(WORKFLOW_IDS)})
).hexdigest()
