"""The one authoritative product identity and built-in workflow registry.

The product document is the single source of truth for the plugin
identity. Workflow definitions themselves live as declarative YAML files
under ``workflows/``; this module only names which of them are built in.
"""

from __future__ import annotations

import hashlib
import json
from typing import Tuple


TASK_SCHEMA_VERSION = 5
WORKFLOW_VERSION = 5
WORKFLOW_IDS: Tuple[str, ...] = ("lite",)
PLUGIN_DATA_NAMESPACE = "v5"


def product_document() -> dict:
    return {
        "plugin": "dev-flow-orchestrator",
        "task_schema_version": TASK_SCHEMA_VERSION,
        "builtin_workflows": list(WORKFLOW_IDS),
        "plugin_data_namespace": PLUGIN_DATA_NAMESPACE,
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


PRODUCT_IDENTITY = hashlib.sha256(
    b"dev-flow-v5-product-identity/v1\x00" + _canonical_bytes(product_document())
).hexdigest()
