#!/usr/bin/env python3
"""Thin standard-library stdio MCP adapter for the Dev Flow controller.

The adapter owns JSON-RPC/MCP framing, discovery, bounded diagnostics, and
strict adapter-level argument validation.  It deliberately owns no workflow
state.  A package-owned controller service must implement
``dispatch_mcp_tool(request)`` and remains responsible for task locks,
revision CAS, manager-capability verification, evidence, gates, idempotency,
and durable commits.

Manager proof material is never accepted as a tool argument.  Mutating calls
carry only the public ``dev-flow-manager-capability-request/v1`` identity; the
controller service obtains and verifies the plaintext proof through its local
manager-secret channel.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import importlib.util
import json
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any, BinaryIO, Mapping, Optional, Sequence


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSIONS = (
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)
SERVER_NAME = "dev-flow-orchestrator"
SERVER_VERSION = "0.3.0"
CONTROLLER_REQUEST_SCHEMA = "dev-flow-controller-mcp-request/v1"
TOOL_RESULT_SCHEMA = "dev-flow-mcp-tool-result/v1"
CLI_FALLBACK_SCHEMA = "dev-flow-cli-fallback/v1"
MANAGER_REQUEST_SCHEMA = "dev-flow-manager-capability-request/v1"
NODE_RESULT_SCHEMA = "dev-flow-node-result/v1"
WORKER_RESULT_ACTION_ID = "worker-result.submit/v1"
TASK_NEXT_UNCHANGED_SCHEMA = "dev-flow-task-next-unchanged/v1"
TASK_NEXT_DELTA_SCHEMA = "dev-flow-task-next-delta/v1"
NODE_DESCRIPTION_SCHEMA = "dev-flow-node-description/v1"
NODE_DESCRIPTION_REFERENCE_SCHEMA = (
    "dev-flow-node-description-reference/v1"
)
EVIDENCE_PROJECTION_SCHEMA = "dev-flow-evidence-projection/v1"
ACTION_PREVIEW_RESULT_SCHEMA = (
    "dev-flow-mcp-action-preview-result/v1"
)
ACTION_APPLY_RESULT_SCHEMA = "dev-flow-mcp-action-apply-result/v1"
WORKER_RESULT_ACCEPTANCE_SCHEMA = (
    "dev-flow-worker-result-acceptance/v1"
)
AGENT_PROTOCOL_SCHEMA = "agent-v1"
ARTIFACT_REFERENCE_SCHEMA = "dev-flow-artifact-reference/v1"

MAX_REQUEST_BYTES = 64 * 1024
MAX_TOOL_ARGUMENT_BYTES = 16 * 1024
MAX_TOOL_VALUE_BYTES = 12 * 1024
MAX_RESPONSE_BYTES = 32 * 1024
MAX_ERROR_MESSAGE_BYTES = 320
MAX_ERROR_DETAILS_BYTES = 2048
MAX_JSON_DEPTH = 24
MAX_JSON_ITEMS = 4096

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002
SERVER_SHUTTING_DOWN = -32003
TOOL_DISABLED = -32004
UNSUPPORTED_PROTOCOL = -32005

_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NODE_RESULT_ID_RE = re.compile(r"^node-result-[0-9a-f]{64}$")
_CONTENT_ID_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9._-]{0,63}:[0-9a-f]{64}$"
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:secret|proof|password|authorization|bearer|credential|access[_-]?token)",
    re.IGNORECASE,
)
_TOOL_NAMES = (
    "task-next",
    "node-description",
    "evidence-read",
    "action-preview",
    "action-apply",
    "worker-result",
)
_READ_TOOLS = frozenset(
    {
        "task-next",
        "node-description",
        "evidence-read",
        "action-preview",
    }
)
_WRITE_TOOLS = frozenset({"action-apply", "worker-result"})


class McpProtocolError(Exception):
    """One bounded JSON-RPC protocol failure."""

    def __init__(
        self,
        rpc_code: int,
        stable_code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.rpc_code = rpc_code
        self.stable_code = stable_code
        self.message = message
        self.details = dict(details or {})


class ControllerServiceError(Exception):
    """Stable controller-service failure surfaced as an MCP tool error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
        fallback: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.fallback = dict(fallback) if fallback is not None else None


def _canonical_json_value(
    value: object,
    *,
    path: str = "$",
    depth: int = 0,
    item_budget: Optional[list[int]] = None,
) -> object:
    if item_budget is None:
        item_budget = [MAX_JSON_ITEMS]
    if depth > MAX_JSON_DEPTH:
        raise McpProtocolError(
            INVALID_PARAMS,
            "JSON_DEPTH_EXCEEDED",
            "JSON value exceeds the supported nesting depth",
            details={"path": path},
        )
    item_budget[0] -= 1
    if item_budget[0] < 0:
        raise McpProtocolError(
            INVALID_PARAMS,
            "JSON_ITEM_BUDGET_EXCEEDED",
            "JSON value contains too many items",
            details={"path": path},
        )
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise McpProtocolError(
            INVALID_PARAMS,
            "JSON_FLOAT_FORBIDDEN",
            "floating-point protocol values are not supported",
            details={"path": path},
        )
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise McpProtocolError(
                    INVALID_PARAMS,
                    "JSON_KEY_INVALID",
                    "JSON object keys must be strings",
                    details={"path": path},
                )
            result[key] = _canonical_json_value(
                item,
                path=f"{path}/{key}",
                depth=depth + 1,
                item_budget=item_budget,
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _canonical_json_value(
                item,
                path=f"{path}/{index}",
                depth=depth + 1,
                item_budget=item_budget,
            )
            for index, item in enumerate(value)
        ]
    raise McpProtocolError(
        INVALID_PARAMS,
        "JSON_VALUE_INVALID",
        "protocol values must be canonical JSON",
        details={"path": path, "type": type(value).__name__},
    )


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            _canonical_json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except McpProtocolError:
        raise
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise McpProtocolError(
            INTERNAL_ERROR,
            "JSON_SERIALIZATION_FAILED",
            "protocol response could not be serialized",
        ) from exc


def _bounded_text(value: object, maximum: int) -> str:
    text = str(value)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return encoded.decode("utf-8", errors="replace")
    suffix = b"..."
    clipped = encoded[: max(0, maximum - len(suffix))]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix.decode("ascii")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix.decode("ascii")


def _redact_and_bound(
    value: object,
    *,
    depth: int = 0,
    remaining: Optional[list[int]] = None,
) -> object:
    if remaining is None:
        remaining = [64]
    if depth > 6 or remaining[0] <= 0:
        return "[BOUNDED]"
    remaining[0] -= 1
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _bounded_text(value, 256)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key in sorted(value, key=lambda item: str(item).encode("utf-8")):
            name = _bounded_text(key, 96)
            if _SENSITIVE_KEY_RE.search(name):
                result[name] = "[REDACTED]"
            else:
                result[name] = _redact_and_bound(
                    value[key], depth=depth + 1, remaining=remaining
                )
            if remaining[0] <= 0:
                break
        return result
    if isinstance(value, (list, tuple)):
        return [
            _redact_and_bound(item, depth=depth + 1, remaining=remaining)
            for item in value[:16]
        ]
    return _bounded_text(type(value).__name__, 64)


def _bounded_error_data(
    stable_code: str, details: Optional[Mapping[str, object]]
) -> dict[str, object]:
    result: dict[str, object] = {"code": stable_code}
    if details:
        result["details"] = _redact_and_bound(details)
    while len(canonical_json_bytes(result)) > MAX_ERROR_DETAILS_BYTES:
        result = {
            "code": stable_code,
            "details": {"diagnostic": "details exceeded MCP error budget"},
        }
        break
    return result


def _rpc_error_response(
    request_id: object,
    error: McpProtocolError,
) -> dict[str, object]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {
            "code": error.rpc_code,
            "message": _bounded_text(
                error.message, MAX_ERROR_MESSAGE_BYTES
            ),
            "data": _bounded_error_data(
                error.stable_code, error.details
            ),
        },
    }


def _object_schema(
    properties: Mapping[str, object],
    required: Sequence[str],
    *,
    description: Optional[str] = None,
) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


def _stable_id_schema(description: str) -> dict[str, object]:
    return {
        "type": "string",
        "pattern": _STABLE_ID_RE.pattern,
        "minLength": 1,
        "maxLength": 256,
        "description": description,
    }


def _manager_request_json_schema() -> dict[str, object]:
    return _object_schema(
        {
            "schema": {"const": MANAGER_REQUEST_SCHEMA},
            "capability_id": _stable_id_schema(
                "Public verifier identity; never the manager proof."
            ),
            "task_id": _stable_id_schema("Bound task identity."),
            "manager_session_id": _stable_id_schema(
                "Bound manager session identity."
            ),
            "action_id": _stable_id_schema("Bound controller action."),
            "expected_revision": {
                "type": "integer",
                "minimum": 0,
            },
            "request_nonce": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
                "minLength": 64,
                "maxLength": 64,
                "description": (
                    "One-use 256-bit request identity. It is not a secret."
                ),
            },
        },
        (
            "schema",
            "capability_id",
            "task_id",
            "manager_session_id",
            "action_id",
            "expected_revision",
            "request_nonce",
        ),
    )


def _node_result_json_schema() -> dict[str, object]:
    compact_reference = _object_schema(
        {
            "id": _stable_id_schema("Content-addressed reference ID."),
            "semantic_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "size": {"type": "integer", "minimum": 0},
            "kind": {"type": "string", "minLength": 1},
            "locator": {"type": "string", "minLength": 1},
        },
        (
            "id",
            "semantic_sha256",
            "sha256",
            "size",
            "kind",
            "locator",
        ),
    )
    return _object_schema(
        {
            "schema": {"const": NODE_RESULT_SCHEMA},
            "result_id": {
                "type": "string",
                "pattern": _NODE_RESULT_ID_RE.pattern,
            },
            "task_id": _stable_id_schema("Owning task identity."),
            "workflow_bundle_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "map_epoch": {"type": "integer", "minimum": 1},
            "repository_id": {
                "anyOf": [
                    _stable_id_schema("Repository identity."),
                    {"type": "null"},
                ]
            },
            "node_instance_id": _stable_id_schema(
                "Exact node-instance identity."
            ),
            "attempt": {"type": "integer", "minimum": 1},
            "assignment_id": {
                "type": "string",
                "pattern": _CONTENT_ID_RE.pattern,
            },
            "lease_id": {
                "anyOf": [
                    {
                        "type": "string",
                        "pattern": _CONTENT_ID_RE.pattern,
                    },
                    {"type": "null"},
                ]
            },
            "lease_nonce": {
                "anyOf": [
                    {
                        "type": "string",
                        "pattern": _SHA256_RE.pattern,
                    },
                    {"type": "null"},
                ]
            },
            "input_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "output_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "worktree_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "changed_paths_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "verification_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "outcome": {
                "type": "string",
                "enum": [
                    "SUCCEEDED",
                    "FAILED",
                    "BLOCKED",
                    "WAITING_APPROVAL",
                    "WAITING_EXTERNAL",
                ],
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
            },
            "blockers": {
                "type": "array",
                "items": _stable_id_schema("Stable blocker ID."),
                "maxItems": 32,
            },
            "plan_drift": _object_schema(
                {
                    "detected": {"type": "boolean"},
                    "reasons": {
                        "type": "array",
                        "items": _stable_id_schema(
                            "Stable plan-drift reason ID."
                        ),
                        "maxItems": 32,
                    },
                },
                ("detected", "reasons"),
            ),
            "artifact_refs": {
                "type": "array",
                "items": compact_reference,
                "maxItems": 32,
            },
            "evidence_refs": {
                "type": "array",
                "items": compact_reference,
                "maxItems": 32,
            },
            "runtime_handle": {
                "anyOf": [
                    _stable_id_schema("Runtime handle identity."),
                    {"type": "null"},
                ]
            },
        },
        (
            "schema",
            "result_id",
            "task_id",
            "workflow_bundle_sha256",
            "map_epoch",
            "repository_id",
            "node_instance_id",
            "attempt",
            "assignment_id",
            "lease_id",
            "lease_nonce",
            "input_sha256",
            "output_sha256",
            "worktree_sha256",
            "changed_paths_sha256",
            "verification_sha256",
            "outcome",
            "summary",
            "blockers",
            "plan_drift",
            "artifact_refs",
            "evidence_refs",
            "runtime_handle",
        ),
    )


def _action_input_json_schema() -> dict[str, object]:
    transition = _object_schema(
        {
            "contract": {
                "const": "dev-flow-action-transition-input/v1"
            },
            "to": _stable_id_schema("Target workflow node ID."),
            "note": {
                "anyOf": [
                    {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2048,
                    },
                    {"type": "null"},
                ]
            },
        },
        ("contract", "to", "note"),
    )
    cancel = _object_schema(
        {
            "contract": {
                "const": "dev-flow-action-cancel-input/v1"
            },
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2048,
            },
        },
        ("contract", "reason"),
    )
    return {
        "oneOf": [transition, cancel],
        "description": (
            "Package-owned typed action input. Unsupported graph actions "
            "must omit input and preview as inapplicable."
        ),
    }


def _artifact_reference_json_schema() -> dict[str, object]:
    return _object_schema(
        {
            "schema": {"const": ARTIFACT_REFERENCE_SCHEMA},
            "artifact_id": _stable_id_schema(
                "Task-scoped content-addressed artifact identity."
            ),
            "task_id": _stable_id_schema("Owning task identity."),
            "semantic_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "size": {"type": "integer", "minimum": 0},
            "media_type": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "minLength": 1},
            "locator": {"type": "string", "minLength": 1},
        },
        (
            "schema",
            "artifact_id",
            "task_id",
            "semantic_sha256",
            "sha256",
            "size",
            "media_type",
            "kind",
            "locator",
        ),
    )


def _workflow_identity_json_schema() -> dict[str, object]:
    return _object_schema(
        {
            "id": _stable_id_schema("Pinned workflow identity."),
            "version": {"type": "integer", "minimum": 1},
            "schema": {"type": "string", "minLength": 1},
            "graph_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "bundle_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "adapter": {"type": "string", "minLength": 1},
        },
        ("id", "version", "schema", "graph_sha256", "bundle_sha256"),
    )


def _task_next_revision_delta_json_schema() -> dict[str, object]:
    return _object_schema(
        {
            "contract": {"const": TASK_NEXT_DELTA_SCHEMA},
            "from_revision": {"type": "integer", "minimum": 0},
            "to_revision": {"type": "integer", "minimum": 1},
            "revision_count": {"type": "integer", "minimum": 0},
            "delta_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "reset_required": {"type": "boolean"},
        },
        (
            "contract",
            "from_revision",
            "to_revision",
            "revision_count",
            "delta_sha256",
            "reset_required",
        ),
    )


def _task_next_value_schema() -> dict[str, object]:
    projection = _object_schema(
        {
            "contract": {"const": AGENT_PROTOCOL_SCHEMA},
            "task_id": _stable_id_schema("Task identity."),
            "revision": {"type": "integer", "minimum": 0},
            "workflow": _workflow_identity_json_schema(),
            "frontier": {
                "type": "array",
                "items": {"type": "object"},
                "maxItems": 256,
            },
            "actions": {
                "type": "array",
                "items": {"type": "object"},
                "maxItems": 256,
            },
            "frontier_sha256": {
                "type": "string",
                "pattern": _SHA256_RE.pattern,
            },
            "condition": {"type": "object"},
            "locator": {"type": "object"},
            "artifact": _artifact_reference_json_schema(),
            "revision_delta": _task_next_revision_delta_json_schema(),
        },
        (
            "contract",
            "task_id",
            "revision",
            "frontier_sha256",
            "condition",
        ),
    )
    projection["oneOf"] = [
        {
            "required": ["workflow", "frontier", "actions"],
            "not": {"required": ["artifact"]},
        },
        {
            "required": ["artifact"],
            "not": {
                "anyOf": [
                    {"required": ["frontier"]},
                    {"required": ["actions"]},
                ]
            },
        },
    ]
    unchanged = _object_schema(
        {
            "contract": {"const": TASK_NEXT_UNCHANGED_SCHEMA},
            "task_id": _stable_id_schema("Task identity."),
            "revision": {"type": "integer", "minimum": 0},
            "known_revision": {"type": "integer", "minimum": 0},
            "unchanged": {"const": True},
        },
        (
            "contract",
            "task_id",
            "revision",
            "known_revision",
            "unchanged",
        ),
    )
    return {"oneOf": [projection, unchanged]}


def _node_description_value_schema() -> dict[str, object]:
    inline = _object_schema(
        {
            "contract": {"const": NODE_DESCRIPTION_SCHEMA},
            "workflow": _workflow_identity_json_schema(),
            "node": {"type": "object"},
            "legal_actions": {
                "type": "array",
                "items": {"type": "object"},
                "maxItems": 256,
            },
            "playbook": {"type": "object"},
        },
        ("contract", "workflow", "node", "legal_actions", "playbook"),
    )
    reference = _object_schema(
        {
            "contract": {
                "const": NODE_DESCRIPTION_REFERENCE_SCHEMA
            },
            "task_id": _stable_id_schema("Task identity."),
            "revision": {"type": "integer", "minimum": 0},
            "node_id": _stable_id_schema("Workflow node identity."),
            "artifact": _artifact_reference_json_schema(),
        },
        ("contract", "task_id", "revision", "node_id", "artifact"),
    )
    return {"oneOf": [inline, reference]}


def _tool_value_schema(tool_name: str) -> dict[str, object]:
    task_id = _stable_id_schema("Task identity.")
    revision = {"type": "integer", "minimum": 0}
    if tool_name == "task-next":
        return _task_next_value_schema()
    if tool_name == "node-description":
        return _node_description_value_schema()
    if tool_name == "evidence-read":
        return _object_schema(
            {
                "contract": {"const": EVIDENCE_PROJECTION_SCHEMA},
                "task_id": task_id,
                "revision": revision,
                "evidence_id": _stable_id_schema(
                    "Task-scoped evidence identity."
                ),
                "reference": _artifact_reference_json_schema(),
                "inline": {"type": "boolean"},
                "content_encoding": {
                    "type": "string",
                    "enum": ["base64", "artifact-reference"],
                },
                "content_base64": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
            },
            (
                "contract",
                "task_id",
                "revision",
                "evidence_id",
                "reference",
                "inline",
                "content_encoding",
                "content_base64",
            ),
        )
    if tool_name == "action-preview":
        return _object_schema(
            {
                "contract": {"const": ACTION_PREVIEW_RESULT_SCHEMA},
                "task_id": task_id,
                "revision": revision,
                "action_id": _stable_id_schema(
                    "Versioned controller action identity."
                ),
                "input_sha256": {
                    "type": "string",
                    "pattern": _SHA256_RE.pattern,
                },
                "preview_intent": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1024,
                },
                "applicable": {"type": "boolean"},
                "blockers": {
                    "type": "array",
                    "items": _stable_id_schema("Stable blocker code."),
                    "maxItems": 64,
                },
                "fallback": _object_schema(
                    {
                        "schema": {"const": CLI_FALLBACK_SCHEMA},
                        "controller": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "data_dir": {
                            "type": ["string", "null"],
                        },
                        "arguments": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 16,
                        },
                    },
                    (
                        "schema",
                        "controller",
                        "data_dir",
                        "arguments",
                    ),
                ),
            },
            (
                "contract",
                "task_id",
                "revision",
                "action_id",
                "input_sha256",
                "preview_intent",
                "applicable",
                "blockers",
            ),
        )
    if tool_name == "action-apply":
        return _object_schema(
            {
                "contract": {"const": ACTION_APPLY_RESULT_SCHEMA},
                "task_id": task_id,
                "action_id": _stable_id_schema(
                    "Versioned controller action identity."
                ),
                "preview_intent": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1024,
                },
                "revision": revision,
                "event_id": _stable_id_schema(
                    "Committed event identity."
                ),
                "event_type": _stable_id_schema(
                    "Committed event type."
                ),
                "authorization_id": _stable_id_schema(
                    "Manager authorization identity."
                ),
            },
            (
                "contract",
                "task_id",
                "action_id",
                "preview_intent",
                "revision",
                "event_id",
                "event_type",
                "authorization_id",
            ),
        )
    if tool_name == "worker-result":
        return _object_schema(
            {
                "contract": {
                    "const": WORKER_RESULT_ACCEPTANCE_SCHEMA
                },
                "task_id": task_id,
                "result_id": {
                    "type": "string",
                    "pattern": _NODE_RESULT_ID_RE.pattern,
                },
                "revision": revision,
                "event_id": _stable_id_schema(
                    "Committed event identity."
                ),
                "event_type": _stable_id_schema(
                    "Committed event type."
                ),
                "authorization_id": _stable_id_schema(
                    "Manager authorization identity."
                ),
            },
            (
                "contract",
                "task_id",
                "result_id",
                "revision",
                "event_id",
                "event_type",
                "authorization_id",
            ),
        )
    raise ValueError(f"unknown MCP tool schema: {tool_name}")


def _tool_output_schema(tool_name: str) -> dict[str, object]:
    error_schema = _object_schema(
        {
            "code": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
            "details": {"type": "object"},
        },
        ("code", "message", "details"),
    )
    fallback_schema = _object_schema(
        {
            "schema": {"const": CLI_FALLBACK_SCHEMA},
            "controller": {"type": "string", "minLength": 1},
            "data_dir": {
                "type": ["string", "null"],
            },
            "arguments": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 16,
            },
        },
        ("schema", "controller", "data_dir", "arguments"),
    )
    return {
        "type": "object",
        "properties": {
            "schema": {"const": TOOL_RESULT_SCHEMA},
            "tool": {"const": tool_name},
            "ok": {"type": "boolean"},
            "value": _tool_value_schema(tool_name),
            "error": error_schema,
            "fallback": fallback_schema,
        },
        "required": ["schema", "tool", "ok"],
        "additionalProperties": False,
        "allOf": [
            {
                "if": {
                    "properties": {"ok": {"const": True}},
                    "required": ["ok"],
                },
                "then": {
                    "required": ["value"],
                    "not": {
                        "anyOf": [
                            {"required": ["error"]},
                            {"required": ["fallback"]},
                        ]
                    },
                },
                "else": {
                    "required": ["error"],
                    "not": {"required": ["value"]},
                },
            }
        ],
    }


def _tool_definitions() -> tuple[dict[str, object], ...]:
    task_id = _stable_id_schema("Task identity.")
    revision = {"type": "integer", "minimum": 0}
    action_id = _stable_id_schema("Versioned controller action identity.")
    contract = lambda name: {"const": f"dev-flow-mcp-{name}/v1"}
    common_annotations = {
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    definitions = (
        {
            "name": "task-next",
            "description": (
                "Read the bounded agent-v1 actionable frontier for one task."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("task-next"),
                    "task_id": task_id,
                    "known_revision": revision,
                },
                ("contract", "task_id"),
            ),
            "annotations": {
                **common_annotations,
                "title": "Read next Dev Flow action",
                "readOnlyHint": True,
            },
        },
        {
            "name": "node-description",
            "description": (
                "Read the pinned versioned description for one workflow node."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("node-description"),
                    "task_id": task_id,
                    "node_id": _stable_id_schema("Workflow node ID."),
                    "node_instance_id": _stable_id_schema(
                        "Optional concrete node-instance ID."
                    ),
                },
                ("contract", "task_id", "node_id"),
            ),
            "annotations": {
                **common_annotations,
                "title": "Describe Dev Flow node",
                "readOnlyHint": True,
            },
        },
        {
            "name": "evidence-read",
            "description": (
                "Read a task-scoped, controller-validated evidence projection."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("evidence-read"),
                    "task_id": task_id,
                    "evidence_id": _stable_id_schema(
                        "Task-scoped evidence or artifact identity."
                    ),
                    "expected_sha256": {
                        "type": "string",
                        "pattern": _SHA256_RE.pattern,
                    },
                },
                ("contract", "task_id", "evidence_id"),
            ),
            "annotations": {
                **common_annotations,
                "title": "Read Dev Flow evidence",
                "readOnlyHint": True,
            },
        },
        {
            "name": "action-preview",
            "description": (
                "Validate and preview one current action without committing."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("action-preview"),
                    "task_id": task_id,
                    "expected_revision": revision,
                    "action_id": action_id,
                    "input": _action_input_json_schema(),
                },
                (
                    "contract",
                    "task_id",
                    "expected_revision",
                    "action_id",
                ),
            ),
            "annotations": {
                **common_annotations,
                "title": "Preview Dev Flow action",
                "readOnlyHint": True,
            },
        },
        {
            "name": "action-apply",
            "description": (
                "Apply an unchanged preview through manager-authorized "
                "controller validation."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("action-apply"),
                    "task_id": task_id,
                    "expected_revision": revision,
                    "action_id": action_id,
                    "preview_intent": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1024,
                    },
                    "request_identity": _manager_request_json_schema(),
                    "input": _action_input_json_schema(),
                },
                (
                    "contract",
                    "task_id",
                    "expected_revision",
                    "action_id",
                    "preview_intent",
                    "request_identity",
                ),
            ),
            "annotations": {
                "title": "Apply Dev Flow action",
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        {
            "name": "worker-result",
            "description": (
                "Submit a bounded candidate NodeResult through "
                "manager-authorized controller validation."
            ),
            "inputSchema": _object_schema(
                {
                    "contract": contract("worker-result"),
                    "task_id": task_id,
                    "expected_revision": revision,
                    "request_identity": _manager_request_json_schema(),
                    "result": _node_result_json_schema(),
                },
                (
                    "contract",
                    "task_id",
                    "expected_revision",
                    "request_identity",
                    "result",
                ),
            ),
            "annotations": {
                "title": "Submit Dev Flow worker result",
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    )
    result: list[dict[str, object]] = []
    for definition in definitions:
        item = copy.deepcopy(definition)
        item["outputSchema"] = _tool_output_schema(
            str(definition["name"])
        )
        result.append(item)
    return tuple(result)


TOOL_DEFINITIONS = _tool_definitions()
TOOL_BY_NAME = {
    str(definition["name"]): definition
    for definition in TOOL_DEFINITIONS
}


def _require_mapping(
    value: object, field: str
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise McpProtocolError(
            INVALID_PARAMS,
            "FIELD_TYPE_INVALID",
            f"{field} must be an object",
            details={"field": field},
        )
    return dict(value)


def _reject_unknown(
    value: Mapping[str, object],
    allowed: Sequence[str],
    field: str,
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise McpProtocolError(
            INVALID_PARAMS,
            "UNKNOWN_FIELD",
            f"{field} contains unsupported fields",
            details={"field": field, "fields": unknown},
        )


def _require_fields(
    value: Mapping[str, object],
    required: Sequence[str],
    field: str,
) -> None:
    missing = sorted(set(required) - set(value))
    if missing:
        raise McpProtocolError(
            INVALID_PARAMS,
            "MISSING_FIELD",
            f"{field} is missing required fields",
            details={"field": field, "fields": missing},
        )


def _require_string(
    value: object,
    field: str,
    *,
    maximum: int = 1024,
    pattern: Optional[re.Pattern[str]] = None,
) -> str:
    if not isinstance(value, str) or not value:
        raise McpProtocolError(
            INVALID_PARAMS,
            "FIELD_TYPE_INVALID",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    if len(value.encode("utf-8")) > maximum:
        raise McpProtocolError(
            INVALID_PARAMS,
            "FIELD_TOO_LARGE",
            f"{field} exceeds its UTF-8 byte budget",
            details={"field": field, "budget": maximum},
        )
    if pattern is not None and pattern.fullmatch(value) is None:
        raise McpProtocolError(
            INVALID_PARAMS,
            "FIELD_FORMAT_INVALID",
            f"{field} has an invalid format",
            details={"field": field},
        )
    return value


def _require_revision(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise McpProtocolError(
            INVALID_PARAMS,
            "FIELD_TYPE_INVALID",
            f"{field} must be a non-negative integer",
            details={"field": field},
        )
    return value


def _validate_manager_request(
    value: object,
) -> dict[str, object]:
    request = _require_mapping(value, "request_identity")
    fields = (
        "schema",
        "capability_id",
        "task_id",
        "manager_session_id",
        "action_id",
        "expected_revision",
        "request_nonce",
    )
    _reject_unknown(request, fields, "request_identity")
    _require_fields(request, fields, "request_identity")
    if request["schema"] != MANAGER_REQUEST_SCHEMA:
        raise McpProtocolError(
            INVALID_PARAMS,
            "MANAGER_REQUEST_SCHEMA_UNSUPPORTED",
            "request_identity schema is unsupported",
            details={"supported": [MANAGER_REQUEST_SCHEMA]},
        )
    for field in (
        "capability_id",
        "task_id",
        "manager_session_id",
        "action_id",
    ):
        _require_string(
            request[field],
            f"request_identity.{field}",
            maximum=256,
            pattern=_STABLE_ID_RE,
        )
    _require_revision(
        request["expected_revision"],
        "request_identity.expected_revision",
    )
    _require_string(
        request["request_nonce"],
        "request_identity.request_nonce",
        maximum=64,
        pattern=_SHA256_RE,
    )
    return request


def _validate_action_input(value: object) -> dict[str, object]:
    action_input = _require_mapping(value, "input")
    contract = action_input.get("contract")
    if contract == "dev-flow-action-transition-input/v1":
        _reject_unknown(
            action_input, ("contract", "to", "note"), "input"
        )
        _require_fields(
            action_input, ("contract", "to", "note"), "input"
        )
        _require_string(
            action_input["to"],
            "input.to",
            maximum=256,
            pattern=_STABLE_ID_RE,
        )
        note = action_input["note"]
        if note is not None:
            _require_string(note, "input.note", maximum=2048)
        return action_input
    if contract == "dev-flow-action-cancel-input/v1":
        _reject_unknown(
            action_input, ("contract", "reason"), "input"
        )
        _require_fields(
            action_input, ("contract", "reason"), "input"
        )
        _require_string(
            action_input["reason"], "input.reason", maximum=2048
        )
        return action_input
    raise McpProtocolError(
        INVALID_PARAMS,
        "ACTION_INPUT_CONTRACT_UNSUPPORTED",
        "action input contract is unsupported",
        details={
            "supported": [
                "dev-flow-action-transition-input/v1",
                "dev-flow-action-cancel-input/v1",
            ]
        },
    )


def _validate_node_result(
    value: object, *, task_id: str
) -> dict[str, object]:
    result = _require_mapping(value, "result")
    allowed = (
        "schema",
        "result_id",
        "task_id",
        "workflow_bundle_sha256",
        "map_epoch",
        "repository_id",
        "node_instance_id",
        "attempt",
        "assignment_id",
        "lease_id",
        "lease_nonce",
        "input_sha256",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
        "outcome",
        "summary",
        "blockers",
        "plan_drift",
        "artifact_refs",
        "evidence_refs",
        "runtime_handle",
    )
    _reject_unknown(result, allowed, "result")
    _require_fields(result, allowed, "result")
    if result["schema"] != NODE_RESULT_SCHEMA:
        raise McpProtocolError(
            INVALID_PARAMS,
            "NODE_RESULT_SCHEMA_UNSUPPORTED",
            "worker result schema is unsupported",
            details={"supported": [NODE_RESULT_SCHEMA]},
        )
    if result["task_id"] != task_id:
        raise McpProtocolError(
            INVALID_PARAMS,
            "NODE_RESULT_TASK_MISMATCH",
            "worker result belongs to another task",
        )
    _require_string(
        result["result_id"],
        "result.result_id",
        maximum=76,
        pattern=_NODE_RESULT_ID_RE,
    )
    for field in ("task_id", "node_instance_id"):
        _require_string(
            result[field],
            f"result.{field}",
            maximum=256,
            pattern=_STABLE_ID_RE,
        )
    if result["repository_id"] is not None:
        _require_string(
            result["repository_id"],
            "result.repository_id",
            maximum=256,
            pattern=_STABLE_ID_RE,
        )
    for field in (
        "workflow_bundle_sha256",
        "input_sha256",
        "output_sha256",
        "worktree_sha256",
        "changed_paths_sha256",
        "verification_sha256",
    ):
        _require_string(
            result[field],
            f"result.{field}",
            maximum=64,
            pattern=_SHA256_RE,
        )
    for field in ("map_epoch", "attempt"):
        if _require_revision(result[field], f"result.{field}") < 1:
            raise McpProtocolError(
                INVALID_PARAMS,
                "FIELD_VALUE_INVALID",
                f"result.{field} must be at least 1",
            )
    _require_string(
        result["assignment_id"],
        "result.assignment_id",
        maximum=129,
        pattern=_CONTENT_ID_RE,
    )
    if (result["lease_id"] is None) != (
        result["lease_nonce"] is None
    ):
        raise McpProtocolError(
            INVALID_PARAMS,
            "NODE_RESULT_LEASE_BINDING_INVALID",
            "lease_id and lease_nonce must both be present or both be null",
        )
    if result["lease_id"] is not None:
        _require_string(
            result["lease_id"],
            "result.lease_id",
            maximum=129,
            pattern=_CONTENT_ID_RE,
        )
        _require_string(
            result["lease_nonce"],
            "result.lease_nonce",
            maximum=64,
            pattern=_SHA256_RE,
        )
    _require_string(result["outcome"], "result.outcome", maximum=32)
    if result["outcome"] not in {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
    }:
        raise McpProtocolError(
            INVALID_PARAMS,
            "NODE_RESULT_OUTCOME_INVALID",
            "worker result outcome is unsupported",
        )
    _require_string(result["summary"], "result.summary", maximum=512)
    canonical = canonical_json_bytes(result)
    if len(canonical) > 2048:
        raise McpProtocolError(
            INVALID_PARAMS,
            "NODE_RESULT_BUDGET_EXCEEDED",
            "manager-visible worker result exceeds 2048 UTF-8 bytes",
            details={"size": len(canonical), "budget": 2048},
        )
    return result


def validate_tool_arguments(
    tool_name: str, value: object
) -> dict[str, object]:
    arguments = _require_mapping(value, "arguments")
    canonical = canonical_json_bytes(arguments)
    if len(canonical) > MAX_TOOL_ARGUMENT_BYTES:
        raise McpProtocolError(
            INVALID_PARAMS,
            "TOOL_ARGUMENT_BUDGET_EXCEEDED",
            "tool arguments exceed the MCP adapter budget",
            details={
                "size": len(canonical),
                "budget": MAX_TOOL_ARGUMENT_BYTES,
            },
        )
    allowed_by_tool = {
        "task-next": ("contract", "task_id", "known_revision"),
        "node-description": (
            "contract",
            "task_id",
            "node_id",
            "node_instance_id",
        ),
        "evidence-read": (
            "contract",
            "task_id",
            "evidence_id",
            "expected_sha256",
        ),
        "action-preview": (
            "contract",
            "task_id",
            "expected_revision",
            "action_id",
            "input",
        ),
        "action-apply": (
            "contract",
            "task_id",
            "expected_revision",
            "action_id",
            "preview_intent",
            "request_identity",
            "input",
        ),
        "worker-result": (
            "contract",
            "task_id",
            "expected_revision",
            "request_identity",
            "result",
        ),
    }
    required_by_tool = {
        "task-next": ("contract", "task_id"),
        "node-description": ("contract", "task_id", "node_id"),
        "evidence-read": ("contract", "task_id", "evidence_id"),
        "action-preview": (
            "contract",
            "task_id",
            "expected_revision",
            "action_id",
        ),
        "action-apply": (
            "contract",
            "task_id",
            "expected_revision",
            "action_id",
            "preview_intent",
            "request_identity",
        ),
        "worker-result": (
            "contract",
            "task_id",
            "expected_revision",
            "request_identity",
            "result",
        ),
    }
    if tool_name not in allowed_by_tool:
        raise McpProtocolError(
            INVALID_PARAMS,
            "TOOL_UNKNOWN",
            "requested tool is not supported",
            details={"tool": tool_name},
        )
    _reject_unknown(
        arguments, allowed_by_tool[tool_name], "arguments"
    )
    _require_fields(
        arguments, required_by_tool[tool_name], "arguments"
    )
    expected_contract = f"dev-flow-mcp-{tool_name}/v1"
    if arguments["contract"] != expected_contract:
        raise McpProtocolError(
            INVALID_PARAMS,
            "TOOL_CONTRACT_UNSUPPORTED",
            "tool argument contract is unsupported",
            details={"supported": [expected_contract]},
        )
    task_id = _require_string(
        arguments["task_id"],
        "task_id",
        maximum=256,
        pattern=_STABLE_ID_RE,
    )
    if "known_revision" in arguments:
        _require_revision(
            arguments["known_revision"], "known_revision"
        )
    for field in (
        "node_id",
        "node_instance_id",
        "evidence_id",
        "action_id",
    ):
        if field in arguments:
            _require_string(
                arguments[field],
                field,
                maximum=256,
                pattern=_STABLE_ID_RE,
            )
    if "expected_sha256" in arguments:
        _require_string(
            arguments["expected_sha256"],
            "expected_sha256",
            maximum=64,
            pattern=_SHA256_RE,
        )
    if "expected_revision" in arguments:
        _require_revision(
            arguments["expected_revision"], "expected_revision"
        )
    if "preview_intent" in arguments:
        _require_string(
            arguments["preview_intent"],
            "preview_intent",
            maximum=1024,
        )
    if "input" in arguments:
        _validate_action_input(arguments["input"])
    if tool_name in _WRITE_TOOLS:
        identity = _validate_manager_request(
            arguments["request_identity"]
        )
        if identity["task_id"] != task_id:
            raise McpProtocolError(
                INVALID_PARAMS,
                "MANAGER_REQUEST_TASK_MISMATCH",
                "request identity belongs to another task",
            )
        if (
            identity["expected_revision"]
            != arguments["expected_revision"]
        ):
            raise McpProtocolError(
                INVALID_PARAMS,
                "MANAGER_REQUEST_REVISION_MISMATCH",
                "request identity is bound to another revision",
            )
        expected_action = (
            arguments["action_id"]
            if tool_name == "action-apply"
            else WORKER_RESULT_ACTION_ID
        )
        if identity["action_id"] != expected_action:
            raise McpProtocolError(
                INVALID_PARAMS,
                "MANAGER_REQUEST_ACTION_MISMATCH",
                "request identity is bound to another action",
            )
    if tool_name == "worker-result":
        _validate_node_result(arguments["result"], task_id=task_id)
    return arguments


def _validate_output_mapping(
    value: object, field: str
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            f"{field} must be an object",
        )
    return dict(value)


def _validate_output_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            f"{field} must be a lowercase SHA-256 value",
        )
    return value


def _validate_output_workflow_identity(value: object) -> dict[str, object]:
    workflow = _validate_output_mapping(value, "workflow")
    required = {
        "id",
        "version",
        "schema",
        "graph_sha256",
        "bundle_sha256",
    }
    if set(workflow) - (required | {"adapter"}) or required - set(
        workflow
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "workflow identity has an invalid field set",
        )
    for field in ("id", "schema"):
        if not isinstance(workflow.get(field), str) or not workflow[field]:
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "workflow identity contains an invalid string",
            )
    version = workflow.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "workflow identity version is invalid",
        )
    for field in ("graph_sha256", "bundle_sha256"):
        _validate_output_digest(
            workflow.get(field), f"workflow.{field}"
        )
    adapter = workflow.get("adapter")
    if adapter is not None and (
        not isinstance(adapter, str) or not adapter
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "workflow identity adapter is invalid",
        )
    return workflow


def _validate_output_artifact_reference(
    value: object, *, task_id: str
) -> dict[str, object]:
    reference = _validate_output_mapping(value, "artifact")
    fields = {
        "schema",
        "artifact_id",
        "task_id",
        "semantic_sha256",
        "sha256",
        "size",
        "media_type",
        "kind",
        "locator",
    }
    if set(reference) != fields:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "artifact reference has an invalid field set",
        )
    if (
        reference.get("schema") != ARTIFACT_REFERENCE_SCHEMA
        or reference.get("task_id") != task_id
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "artifact reference is outside the requested task",
        )
    for field in ("artifact_id", "media_type", "kind"):
        if (
            not isinstance(reference.get(field), str)
            or not reference[field]
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "artifact reference contains an invalid string",
            )
    for field in ("semantic_sha256", "sha256"):
        _validate_output_digest(
            reference.get(field), f"artifact.{field}"
        )
    size = reference.get("size")
    locator = reference.get("locator")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not isinstance(locator, str)
        or not locator
        or locator.startswith("/")
        or "\\" in locator
        or any(
            part in {"", ".", ".."} for part in locator.split("/")
        )
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "artifact reference has invalid integrity or locator facts",
        )
    return reference


def _validate_task_next_revision_delta(
    value: object,
    *,
    known_revision: int,
    current_revision: int,
) -> dict[str, object]:
    delta = _validate_output_mapping(value, "task-next.revision_delta")
    fields = {
        "contract",
        "from_revision",
        "to_revision",
        "revision_count",
        "delta_sha256",
        "reset_required",
    }
    if set(delta) != fields:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "task-next revision delta has an invalid field set",
        )
    expected_count = current_revision - known_revision
    revision_count = delta.get("revision_count")
    reset_required = delta.get("reset_required")
    if (
        delta.get("contract") != TASK_NEXT_DELTA_SCHEMA
        or delta.get("from_revision") != known_revision
        or delta.get("to_revision") != current_revision
        or isinstance(revision_count, bool)
        or not isinstance(revision_count, int)
        or revision_count < 0
        or revision_count > expected_count
        or not isinstance(reset_required, bool)
        or (not reset_required and revision_count != expected_count)
        or (reset_required and revision_count == expected_count)
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "task-next revision delta is not bound to the requested revisions",
        )
    _validate_output_digest(
        delta.get("delta_sha256"),
        "task-next.revision_delta.delta_sha256",
    )
    return delta


def _validate_cli_fallback_value(value: object) -> dict[str, object]:
    fallback = _validate_output_mapping(value, "fallback")
    if set(fallback) != {
        "schema",
        "controller",
        "data_dir",
        "arguments",
    }:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "CLI fallback has an invalid field set",
        )
    controller = fallback.get("controller")
    data_dir = fallback.get("data_dir")
    arguments = fallback.get("arguments")
    if (
        fallback.get("schema") != CLI_FALLBACK_SCHEMA
        or not isinstance(controller, str)
        or not controller
        or "\x00" in controller
        or (
            data_dir is not None
            and (
                not isinstance(data_dir, str)
                or not data_dir
                or "\x00" in data_dir
            )
        )
        or not isinstance(arguments, list)
        or not arguments
        or len(arguments) > 16
        or any(
            not isinstance(item, str)
            or not item
            or "\x00" in item
            or len(item.encode("utf-8")) > 1024
            for item in arguments
        )
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "CLI fallback is malformed",
        )
    serialized = canonical_json_bytes(fallback).lower()
    if any(
        marker in serialized
        for marker in (
            b"manager_secret",
            b"manager-secret",
            b"request_nonce",
            b"request-nonce",
            b'"proof"',
            b"--proof",
        )
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "CLI fallback contains forbidden authority material",
        )
    return fallback


def _validate_tool_output_value(
    tool_name: str,
    value: Mapping[str, object],
    *,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Validate the narrow controller projection before MCP serialization."""

    result = dict(value)
    contract = result.get("contract")
    expected_fields: frozenset[str]
    required_fields: frozenset[str]
    if tool_name == "task-next":
        if contract == TASK_NEXT_UNCHANGED_SCHEMA:
            expected_fields = frozenset(
                {
                    "contract",
                    "task_id",
                    "revision",
                    "known_revision",
                    "unchanged",
                }
            )
            required_fields = expected_fields
            if (
                result.get("unchanged") is not True
                or result.get("known_revision")
                != arguments.get("known_revision")
                or result.get("revision")
                != arguments.get("known_revision")
            ):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "task-next unchanged result has invalid revision binding",
                )
        elif contract == AGENT_PROTOCOL_SCHEMA:
            expected_fields = frozenset(
                {
                    "contract",
                    "task_id",
                    "revision",
                    "workflow",
                    "frontier",
                    "actions",
                    "frontier_sha256",
                    "condition",
                    "locator",
                    "artifact",
                    "revision_delta",
                }
            )
            required_fields = frozenset(
                {
                    "contract",
                    "task_id",
                    "revision",
                    "frontier_sha256",
                    "condition",
                }
            )
            inline = "frontier" in result and "actions" in result
            overflow = "artifact" in result
            if inline == overflow:
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "task-next must contain exactly one inline or overflow projection",
                )
            _validate_output_digest(
                result.get("frontier_sha256"),
                "task-next.frontier_sha256",
            )
            condition = _validate_output_mapping(
                result.get("condition"), "task-next.condition"
            )
            if inline:
                _validate_output_workflow_identity(
                    result.get("workflow")
                )
                frontier = result.get("frontier")
                actions = result.get("actions")
                if (
                    not isinstance(frontier, list)
                    or len(frontier) > 256
                    or any(not isinstance(item, Mapping) for item in frontier)
                    or not isinstance(actions, list)
                    or len(actions) > 256
                    or any(not isinstance(item, Mapping) for item in actions)
                ):
                    raise ControllerServiceError(
                        "CONTROLLER_RESPONSE_INVALID",
                        "task-next inline projection is malformed",
                    )
                observed_frontier_sha256 = hashlib.sha256(
                    canonical_json_bytes(
                        {
                            "frontier": frontier,
                            "actions": actions,
                            "condition": condition,
                        }
                    )
                ).hexdigest()
                if result.get("frontier_sha256") != observed_frontier_sha256:
                    raise ControllerServiceError(
                        "CONTROLLER_RESPONSE_INVALID",
                        "task-next frontier digest is invalid",
                    )
            else:
                _validate_output_artifact_reference(
                    result.get("artifact"),
                    task_id=str(arguments.get("task_id")),
                )
            if "locator" in result and not isinstance(
                result.get("locator"), Mapping
            ):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "task-next locator must be an object",
                )
            known_revision = arguments.get("known_revision")
            current_revision = result.get("revision")
            needs_delta = (
                isinstance(known_revision, int)
                and not isinstance(known_revision, bool)
                and isinstance(current_revision, int)
                and not isinstance(current_revision, bool)
                and known_revision < current_revision
            )
            if needs_delta != ("revision_delta" in result):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "task-next revision delta presence does not match the requested checkpoint",
                )
            if needs_delta:
                _validate_task_next_revision_delta(
                    result.get("revision_delta"),
                    known_revision=known_revision,
                    current_revision=current_revision,
                )
        else:
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "task-next returned an unsupported contract",
            )
    elif tool_name == "node-description":
        if contract == NODE_DESCRIPTION_SCHEMA:
            expected_fields = frozenset(
                {
                    "contract",
                    "workflow",
                    "node",
                    "legal_actions",
                    "playbook",
                }
            )
            required_fields = expected_fields
            _validate_output_workflow_identity(result.get("workflow"))
            node = _validate_output_mapping(
                result.get("node"), "node-description.node"
            )
            if node.get("id") != arguments.get("node_id"):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "node-description belongs to another node",
                )
            if (
                not isinstance(result.get("legal_actions"), list)
                or len(result.get("legal_actions", [])) > 256
                or any(
                    not isinstance(item, Mapping)
                    for item in result.get("legal_actions", [])
                )
                or not isinstance(result.get("playbook"), Mapping)
            ):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "node-description projection is malformed",
                )
        elif contract == NODE_DESCRIPTION_REFERENCE_SCHEMA:
            expected_fields = frozenset(
                {
                    "contract",
                    "task_id",
                    "revision",
                    "node_id",
                    "artifact",
                }
            )
            required_fields = expected_fields
            if result.get("node_id") != arguments.get("node_id"):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "node-description reference belongs to another node",
                )
            _validate_output_artifact_reference(
                result.get("artifact"),
                task_id=str(arguments.get("task_id")),
            )
        else:
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "node-description returned an unsupported contract",
            )
    elif tool_name == "evidence-read":
        expected_fields = frozenset(
            {
                "contract",
                "task_id",
                "revision",
                "evidence_id",
                "reference",
                "inline",
                "content_encoding",
                "content_base64",
            }
        )
        required_fields = expected_fields
        if (
            contract != EVIDENCE_PROJECTION_SCHEMA
            or result.get("evidence_id")
            != arguments.get("evidence_id")
            or (
                result.get("inline") is True
                and (
                    result.get("content_encoding") != "base64"
                    or not isinstance(
                        result.get("content_base64"), str
                    )
                )
            )
            or (
                result.get("inline") is False
                and (
                    result.get("content_encoding")
                    != "artifact-reference"
                    or result.get("content_base64") is not None
                )
            )
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "evidence-read returned an invalid bounded projection",
            )
        reference = _validate_output_artifact_reference(
            result.get("reference"),
            task_id=str(arguments.get("task_id")),
        )
        if reference.get("artifact_id") != arguments.get("evidence_id"):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "evidence-read reference belongs to another evidence identity",
            )
        expected_sha256 = arguments.get("expected_sha256")
        if (
            expected_sha256 is not None
            and reference.get("sha256") != expected_sha256
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "evidence-read ignored the expected digest binding",
            )
        if result.get("inline") is True:
            try:
                decoded = base64.b64decode(
                    str(result.get("content_base64")),
                    validate=True,
                )
            except (ValueError, binascii.Error) as exc:
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "evidence-read inline content is not canonical base64",
                ) from exc
            if (
                base64.b64encode(decoded).decode("ascii")
                != result.get("content_base64")
                or len(decoded) != reference.get("size")
                or hashlib.sha256(decoded).hexdigest()
                != reference.get("sha256")
            ):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "evidence-read inline content fails integrity checks",
                )
    elif tool_name == "action-preview":
        expected_fields = frozenset(
            {
                "contract",
                "task_id",
                "revision",
                "action_id",
                "input_sha256",
                "preview_intent",
                "applicable",
                "blockers",
                "fallback",
            }
        )
        required_fields = expected_fields - {"fallback"}
        if (
            contract != ACTION_PREVIEW_RESULT_SCHEMA
            or result.get("revision")
            != arguments.get("expected_revision")
            or result.get("action_id") != arguments.get("action_id")
            or result.get("input_sha256")
            != hashlib.sha256(
                canonical_json_bytes(arguments.get("input", {}))
            ).hexdigest()
            or not isinstance(result.get("preview_intent"), str)
            or not result.get("preview_intent")
            or len(
                str(result.get("preview_intent")).encode("utf-8")
            )
            > 1024
            or not isinstance(result.get("applicable"), bool)
            or not isinstance(result.get("blockers"), list)
            or len(result.get("blockers", [])) > 64
            or any(
                not isinstance(item, str) or not item
                for item in result.get("blockers", [])
            )
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "action-preview result is not bound to its request",
            )
        fallback = result.get("fallback")
        if fallback is not None:
            try:
                _validate_cli_fallback_value(fallback)
            except ControllerServiceError as exc:
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "action-preview returned an invalid CLI fallback",
                ) from exc
            if result.get("applicable") is not False:
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "applicable action-preview cannot return a CLI fallback",
                )
    elif tool_name == "action-apply":
        expected_fields = frozenset(
            {
                "contract",
                "task_id",
                "action_id",
                "preview_intent",
                "revision",
                "event_id",
                "event_type",
                "authorization_id",
            }
        )
        required_fields = expected_fields
        if (
            contract != ACTION_APPLY_RESULT_SCHEMA
            or result.get("action_id") != arguments.get("action_id")
            or result.get("preview_intent")
            != arguments.get("preview_intent")
            or not isinstance(result.get("event_id"), str)
            or not result.get("event_id")
            or not isinstance(result.get("event_type"), str)
            or not result.get("event_type")
            or not isinstance(
                result.get("authorization_id"), str
            )
            or not result.get("authorization_id")
            or result.get("revision")
            != arguments.get("expected_revision", -1) + 1
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "action-apply result is not bound to its request",
            )
    elif tool_name == "worker-result":
        expected_fields = frozenset(
            {
                "contract",
                "task_id",
                "result_id",
                "revision",
                "event_id",
                "event_type",
                "authorization_id",
            }
        )
        required_fields = expected_fields
        candidate = arguments.get("result")
        candidate_id = (
            candidate.get("result_id")
            if isinstance(candidate, Mapping)
            else None
        )
        if (
            contract != WORKER_RESULT_ACCEPTANCE_SCHEMA
            or result.get("result_id") != candidate_id
            or not isinstance(result.get("event_id"), str)
            or not result.get("event_id")
            or not isinstance(result.get("event_type"), str)
            or not result.get("event_type")
            or not isinstance(
                result.get("authorization_id"), str
            )
            or not result.get("authorization_id")
            or result.get("revision")
            != arguments.get("expected_revision", -1) + 1
        ):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "worker-result acceptance is not bound to its candidate",
            )
    else:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "controller returned a value for an unsupported MCP tool",
        )
    unknown = sorted(set(result) - set(expected_fields))
    missing = sorted(set(required_fields) - set(result))
    if unknown or missing:
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "controller response has an invalid field set",
            details={"unknown": unknown, "missing": missing},
        )
    if (
        "task_id" in result
        and result.get("task_id") != arguments.get("task_id")
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "controller response belongs to another task",
        )
    revision = result.get("revision")
    if "revision" in result and (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        raise ControllerServiceError(
            "CONTROLLER_RESPONSE_INVALID",
            "controller response revision is invalid",
        )
    return result


def cli_fallback(
    *,
    task_id: Optional[str],
    controller: Path,
    data_dir: Optional[str],
) -> dict[str, object]:
    arguments = ["show"]
    if task_id:
        arguments.extend(("--task", task_id))
    if data_dir:
        arguments.extend(("--data-dir", data_dir))
    return {
        "schema": CLI_FALLBACK_SCHEMA,
        "controller": str(controller),
        "data_dir": data_dir,
        "arguments": arguments,
    }


class UnavailableControllerService:
    """Fail-closed boundary used until the shared service is available."""

    def __init__(
        self, controller: Path, data_dir: Optional[str]
    ) -> None:
        self._controller = controller
        self._data_dir = data_dir

    def dispatch_mcp_tool(
        self, request: Mapping[str, object]
    ) -> Mapping[str, object]:
        arguments = request.get("arguments")
        task_id = (
            arguments.get("task_id")
            if isinstance(arguments, Mapping)
            and isinstance(arguments.get("task_id"), str)
            else None
        )
        raise ControllerServiceError(
            "CONTROLLER_SERVICE_UNAVAILABLE",
            "the shared MCP controller service is not available",
            details={
                "required_service_contract": (
                    "dev-flow-controller-mcp-service/v1"
                )
            },
            fallback=cli_fallback(
                task_id=task_id,
                controller=self._controller,
                data_dir=self._data_dir,
            ),
        )


class PackageControllerService:
    """Lazy adapter to a package-owned controller service factory.

    The fixed package path is intentional: MCP configuration and target
    repositories cannot inject executable controller handlers.
    """

    def __init__(
        self,
        *,
        plugin_root: Path,
        data_dir: Optional[str],
    ) -> None:
        self._plugin_root = plugin_root
        self._controller = (
            plugin_root / "scripts" / "dev_flow.py"
        ).resolve()
        self._data_dir = data_dir
        self._loaded: Optional[object] = None
        self._load_attempted = False

    def _fallback(self, task_id: Optional[str]) -> dict[str, object]:
        return cli_fallback(
            task_id=task_id,
            controller=self._controller,
            data_dir=self._data_dir,
        )

    def _load(self, task_id: Optional[str]) -> object:
        if self._load_attempted:
            if self._loaded is None:
                raise ControllerServiceError(
                    "CONTROLLER_SERVICE_UNAVAILABLE",
                    "the shared MCP controller service is not available",
                    fallback=self._fallback(task_id),
                )
            return self._loaded
        self._load_attempted = True
        expected = self._plugin_root.resolve()
        try:
            if (
                self._controller.is_symlink()
                or not self._controller.is_file()
                or not self._controller.is_relative_to(expected)
            ):
                raise OSError("controller path is not package-owned")
            spec = importlib.util.spec_from_file_location(
                "_dev_flow_mcp_controller", self._controller
            )
            if spec is None or spec.loader is None:
                raise OSError("controller module cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(spec.name, None)
                raise
            runtime_factory = getattr(
                module, "workflow_runtime_services", None
            )
            if not callable(runtime_factory):
                raise AttributeError(
                    "workflow_runtime_services is absent"
                )
            runtime = runtime_factory()
            adapters = getattr(runtime, "adapters", None)
            factory = getattr(
                adapters, "create_mcp_controller_service", None
            )
            if not callable(factory):
                raise AttributeError(
                    "runtime MCP controller adapter is absent"
                )
            service = factory(data_dir=self._data_dir)
            if not callable(
                getattr(service, "dispatch_mcp_tool", None)
            ):
                raise TypeError(
                    "controller service lacks dispatch_mcp_tool"
                )
            self._loaded = service
            return service
        except Exception as exc:
            raise ControllerServiceError(
                "CONTROLLER_SERVICE_UNAVAILABLE",
                "the shared MCP controller service is not available",
                details={"failure_type": type(exc).__name__},
                fallback=self._fallback(task_id),
            ) from exc

    def dispatch_mcp_tool(
        self, request: Mapping[str, object]
    ) -> Mapping[str, object]:
        arguments = request.get("arguments")
        task_id = (
            arguments.get("task_id")
            if isinstance(arguments, Mapping)
            and isinstance(arguments.get("task_id"), str)
            else None
        )
        service = self._load(task_id)
        try:
            result = service.dispatch_mcp_tool(request)
        except ControllerServiceError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            message = getattr(exc, "message", None)
            details = getattr(exc, "details", None)
            if isinstance(code, str) and isinstance(message, str):
                raise ControllerServiceError(
                    code,
                    message,
                    details=(
                        details
                        if isinstance(details, Mapping)
                        else None
                    ),
                    fallback=(
                        self._fallback(task_id)
                        if code
                        in {
                            "CONTROLLER_SERVICE_UNAVAILABLE",
                            "MCP_UNSUPPORTED",
                            "MCP_ACTION_SERVICE_UNAVAILABLE",
                            "MCP_WORKER_RESULT_SERVICE_UNAVAILABLE",
                        }
                        else None
                    ),
                ) from exc
            raise ControllerServiceError(
                "CONTROLLER_SERVICE_FAILED",
                "the shared controller service rejected the request",
                details={"failure_type": type(exc).__name__},
            ) from exc
        if not isinstance(result, Mapping):
            raise ControllerServiceError(
                "CONTROLLER_RESPONSE_INVALID",
                "controller service returned a non-object response",
            )
        return dict(result)


class McpServer:
    """Synchronous, single-transport MCP server.

    The controller itself serializes state mutations under task locks.  The
    stdio adapter intentionally does not create a second writer or local
    idempotency cache.
    """

    def __init__(
        self,
        service: object,
        *,
        enabled_tools: Optional[Sequence[str]] = None,
    ) -> None:
        requested = (
            tuple(_TOOL_NAMES)
            if enabled_tools is None
            else tuple(enabled_tools)
        )
        unknown = sorted(set(requested) - set(_TOOL_NAMES))
        if unknown:
            raise ValueError(
                "unsupported enabled MCP tools: " + ", ".join(unknown)
            )
        if len(set(requested)) != len(requested):
            raise ValueError("enabled MCP tools must be unique")
        self._service = service
        self._enabled = frozenset(requested)
        self._phase = "new"
        self._protocol_version: Optional[str] = None
        self._stop_requested = False

    @property
    def stopped(self) -> bool:
        return self._stop_requested

    def stop(self) -> None:
        self._stop_requested = True

    def _ensure_ready(self) -> None:
        if self._phase == "shutting-down":
            raise McpProtocolError(
                SERVER_SHUTTING_DOWN,
                "SERVER_SHUTTING_DOWN",
                "MCP server is shutting down",
            )
        if self._phase != "ready":
            raise McpProtocolError(
                SERVER_NOT_INITIALIZED,
                "SERVER_NOT_INITIALIZED",
                "MCP client has not completed initialization",
            )

    def _initialize(
        self, params: object
    ) -> dict[str, object]:
        if self._phase != "new":
            raise McpProtocolError(
                INVALID_REQUEST,
                "INITIALIZE_ALREADY_COMPLETED",
                "initialize may be called only once",
            )
        source = _require_mapping(params, "params")
        _reject_unknown(
            source,
            (
                "protocolVersion",
                "capabilities",
                "clientInfo",
                "_meta",
            ),
            "params",
        )
        _require_fields(
            source,
            ("protocolVersion", "capabilities", "clientInfo"),
            "params",
        )
        requested = _require_string(
            source["protocolVersion"],
            "protocolVersion",
            maximum=32,
        )
        if requested not in MCP_PROTOCOL_VERSIONS:
            raise McpProtocolError(
                UNSUPPORTED_PROTOCOL,
                "UNSUPPORTED_PROTOCOL_VERSION",
                "requested MCP protocol version is unsupported",
                details={
                    "requested": requested,
                    "supported": list(MCP_PROTOCOL_VERSIONS),
                },
            )
        _require_mapping(source["capabilities"], "capabilities")
        client = _require_mapping(source["clientInfo"], "clientInfo")
        _reject_unknown(
            client, ("name", "version", "title"), "clientInfo"
        )
        _require_fields(client, ("name", "version"), "clientInfo")
        _require_string(client["name"], "clientInfo.name", maximum=128)
        _require_string(
            client["version"], "clientInfo.version", maximum=64
        )
        if "title" in client:
            _require_string(
                client["title"], "clientInfo.title", maximum=128
            )
        self._protocol_version = requested
        self._phase = "negotiated"
        return {
            "protocolVersion": requested,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
                "title": "Dev Flow Orchestrator",
            },
            "instructions": (
                "Use read tools for bounded projections. Mutations require "
                "a manager request identity and remain controller-gated. "
                "Never place manager proof material in tool arguments."
            ),
        }

    def _initialized_notification(self, params: object) -> None:
        if self._phase != "negotiated":
            raise McpProtocolError(
                INVALID_REQUEST,
                "INITIALIZATION_SEQUENCE_INVALID",
                "notifications/initialized requires a negotiated session",
            )
        if params not in (None, {}):
            source = _require_mapping(params, "params")
            _reject_unknown(source, ("_meta",), "params")
        self._phase = "ready"

    def _list_tools(self, params: object) -> dict[str, object]:
        self._ensure_ready()
        if params not in (None, {}):
            source = _require_mapping(params, "params")
            _reject_unknown(source, ("cursor", "_meta"), "params")
            if "cursor" in source:
                _require_string(
                    source["cursor"], "cursor", maximum=256
                )
        return {
            "tools": [
                copy.deepcopy(TOOL_BY_NAME[name])
                for name in _TOOL_NAMES
                if name in self._enabled
            ]
        }

    def _tool_error(
        self,
        tool_name: str,
        error: ControllerServiceError,
    ) -> dict[str, object]:
        structured: dict[str, object] = {
            "schema": TOOL_RESULT_SCHEMA,
            "tool": tool_name,
            "ok": False,
            "error": {
                "code": _bounded_text(error.code, 128),
                "message": _bounded_text(
                    error.message, MAX_ERROR_MESSAGE_BYTES
                ),
                "details": _redact_and_bound(error.details),
            },
        }
        if error.fallback is not None:
            try:
                fallback = _validate_cli_fallback_value(
                    error.fallback
                )
                structured["fallback"] = _redact_and_bound(
                    fallback
                )
            except ControllerServiceError:
                pass
        return self._mcp_tool_result(structured, is_error=True)

    def _mcp_tool_result(
        self,
        structured: Mapping[str, object],
        *,
        is_error: bool,
    ) -> dict[str, object]:
        encoded = canonical_json_bytes(structured)
        if len(encoded) > MAX_TOOL_VALUE_BYTES:
            fallback = {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": str(structured.get("tool", "unknown")),
                "ok": False,
                "error": {
                    "code": "MCP_RESULT_BUDGET_EXCEEDED",
                    "message": (
                        "controller result exceeds the MCP response budget"
                    ),
                    "details": {
                        "size": len(encoded),
                        "budget": MAX_TOOL_VALUE_BYTES,
                    },
                },
            }
            encoded = canonical_json_bytes(fallback)
            structured = fallback
            is_error = True
        return {
            "content": [
                {
                    "type": "text",
                    "text": encoded.decode("utf-8"),
                }
            ],
            "structuredContent": dict(structured),
            "isError": is_error,
        }

    def _call_tool(self, params: object) -> dict[str, object]:
        self._ensure_ready()
        source = _require_mapping(params, "params")
        _reject_unknown(source, ("name", "arguments", "_meta"), "params")
        _require_fields(source, ("name", "arguments"), "params")
        name = _require_string(source["name"], "name", maximum=128)
        if name not in TOOL_BY_NAME:
            raise McpProtocolError(
                INVALID_PARAMS,
                "TOOL_UNKNOWN",
                "requested MCP tool is not supported",
                details={"tool": name},
            )
        if name not in self._enabled:
            raise McpProtocolError(
                TOOL_DISABLED,
                "TOOL_DISABLED",
                "requested MCP tool is disabled",
                details={"tool": name},
            )
        arguments = validate_tool_arguments(name, source["arguments"])
        request_identity = (
            arguments.get("request_identity")
            if name in _WRITE_TOOLS
            else None
        )
        controller_request = {
            "schema": CONTROLLER_REQUEST_SCHEMA,
            "tool": name,
            "arguments": arguments,
            "request_identity": request_identity,
        }
        try:
            value = self._service.dispatch_mcp_tool(
                controller_request
            )
            if not isinstance(value, Mapping):
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_INVALID",
                    "controller service returned a non-object response",
                )
            validated_value = _validate_tool_output_value(
                name, value, arguments=arguments
            )
            canonical_value = canonical_json_bytes(validated_value)
            if len(canonical_value) > MAX_TOOL_VALUE_BYTES:
                raise ControllerServiceError(
                    "CONTROLLER_RESPONSE_TOO_LARGE",
                    "controller service response exceeds the MCP budget",
                    details={
                        "size": len(canonical_value),
                        "budget": MAX_TOOL_VALUE_BYTES,
                    },
                )
            structured = {
                "schema": TOOL_RESULT_SCHEMA,
                "tool": name,
                "ok": True,
                "value": validated_value,
            }
            return self._mcp_tool_result(
                structured, is_error=False
            )
        except ControllerServiceError as exc:
            return self._tool_error(name, exc)
        except Exception as exc:
            return self._tool_error(
                name,
                ControllerServiceError(
                    "CONTROLLER_SERVICE_FAILED",
                    "controller service failed without a stable error",
                    details={"failure_type": type(exc).__name__},
                ),
            )

    def _dispatch_request(
        self, method: str, params: object
    ) -> object:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return self._list_tools(params)
        if method == "tools/call":
            return self._call_tool(params)
        if method == "shutdown":
            if self._phase == "new":
                raise McpProtocolError(
                    SERVER_NOT_INITIALIZED,
                    "SERVER_NOT_INITIALIZED",
                    "MCP client has not initialized the server",
                )
            self._phase = "shutting-down"
            return None
        raise McpProtocolError(
            METHOD_NOT_FOUND,
            "METHOD_NOT_FOUND",
            "JSON-RPC method is not supported",
            details={"method": method},
        )

    def _dispatch_notification(
        self, method: str, params: object
    ) -> None:
        if method == "notifications/initialized":
            self._initialized_notification(params)
            return
        if method == "exit":
            if self._phase == "shutting-down":
                self.stop()
            else:
                self.stop()
            return
        if method in {
            "notifications/cancelled",
            "notifications/progress",
        }:
            return
        # Unknown notifications do not receive responses under JSON-RPC.

    def handle_message(
        self, message: object
    ) -> Optional[dict[str, object]]:
        request_id: object = None
        try:
            if not isinstance(message, Mapping):
                raise McpProtocolError(
                    INVALID_REQUEST,
                    "INVALID_REQUEST",
                    "JSON-RPC message must be an object",
                )
            source = dict(message)
            _reject_unknown(
                source,
                ("jsonrpc", "id", "method", "params"),
                "request",
            )
            if source.get("jsonrpc") != JSONRPC_VERSION:
                raise McpProtocolError(
                    INVALID_REQUEST,
                    "JSONRPC_VERSION_INVALID",
                    "jsonrpc must equal 2.0",
                )
            method = _require_string(
                source.get("method"), "method", maximum=128
            )
            has_id = "id" in source
            if has_id:
                request_id = source["id"]
                if (
                    isinstance(request_id, bool)
                    or not isinstance(
                        request_id, (str, int, type(None))
                    )
                ):
                    raise McpProtocolError(
                        INVALID_REQUEST,
                        "REQUEST_ID_INVALID",
                        "JSON-RPC id must be a string, integer, or null",
                    )
            params = source.get("params", {})
            if not has_id:
                try:
                    self._dispatch_notification(method, params)
                except McpProtocolError:
                    # Notifications never receive protocol responses.
                    pass
                return None
            result = self._dispatch_request(method, params)
            response = {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": result,
            }
            if len(canonical_json_bytes(response)) > MAX_RESPONSE_BYTES:
                raise McpProtocolError(
                    INTERNAL_ERROR,
                    "RESPONSE_BUDGET_EXCEEDED",
                    "JSON-RPC response exceeds the server budget",
                )
            return response
        except McpProtocolError as exc:
            return _rpc_error_response(request_id, exc)
        except Exception as exc:
            return _rpc_error_response(
                request_id,
                McpProtocolError(
                    INTERNAL_ERROR,
                    "INTERNAL_ERROR",
                    "MCP server encountered an internal error",
                    details={"failure_type": type(exc).__name__},
                ),
            )

    def process_line(
        self, raw: bytes
    ) -> Optional[bytes]:
        if len(raw) > MAX_REQUEST_BYTES:
            response = _rpc_error_response(
                None,
                McpProtocolError(
                    INVALID_REQUEST,
                    "REQUEST_BUDGET_EXCEEDED",
                    "JSON-RPC request exceeds the server byte budget",
                    details={
                        "size": len(raw),
                        "budget": MAX_REQUEST_BYTES,
                    },
                ),
            )
            return canonical_json_bytes(response) + b"\n"
        try:
            text = raw.decode("utf-8", errors="strict")
            message = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            response = _rpc_error_response(
                None,
                McpProtocolError(
                    PARSE_ERROR,
                    "JSON_PARSE_ERROR",
                    "invalid UTF-8 JSON-RPC input",
                ),
            )
            return canonical_json_bytes(response) + b"\n"
        response = self.handle_message(message)
        if response is None:
            return None
        encoded = canonical_json_bytes(response)
        if len(encoded) > MAX_RESPONSE_BYTES:
            encoded = canonical_json_bytes(
                _rpc_error_response(
                    message.get("id")
                    if isinstance(message, Mapping)
                    else None,
                    McpProtocolError(
                        INTERNAL_ERROR,
                        "RESPONSE_BUDGET_EXCEEDED",
                        "JSON-RPC response exceeds the server budget",
                    ),
                )
            )
        return encoded + b"\n"

    def run_stream(
        self, input_stream: BinaryIO, output_stream: BinaryIO
    ) -> int:
        while not self.stopped:
            try:
                line = input_stream.readline(MAX_REQUEST_BYTES + 2)
            except (OSError, ValueError):
                return 0
            if not line:
                self.stop()
                return 0
            if len(line) > MAX_REQUEST_BYTES and not line.endswith(b"\n"):
                while line and not line.endswith(b"\n"):
                    line = input_stream.readline(MAX_REQUEST_BYTES + 2)
                response = self.process_line(b"x" * (MAX_REQUEST_BYTES + 1))
            elif not line.strip():
                continue
            else:
                response = self.process_line(line)
            if response is None:
                continue
            try:
                output_stream.write(response)
                output_stream.flush()
            except (BrokenPipeError, OSError, ValueError):
                # A lost response cannot roll back or replay controller state.
                self.stop()
                return 0
        return 0


def _enabled_tools_from_environment(
    environ: Mapping[str, str],
) -> Optional[tuple[str, ...]]:
    raw = environ.get("DEV_FLOW_MCP_ENABLED_TOOLS")
    if raw is None or not raw.strip():
        return None
    return tuple(
        item.strip() for item in raw.split(",") if item.strip()
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the standard-library Dev Flow MCP adapter over stdio."
        )
    )
    parser.add_argument(
        "--enabled-tool",
        action="append",
        choices=_TOOL_NAMES,
        help=(
            "expose only this tool; repeat as needed. The host may also "
            "apply plugin-scoped enabled_tools policy."
        ),
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="expose only read-only workflow projection tools",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    enabled = (
        tuple(name for name in _TOOL_NAMES if name in _READ_TOOLS)
        if args.read_only
        else (
            tuple(args.enabled_tool)
            if args.enabled_tool
            else _enabled_tools_from_environment(os.environ)
        )
    )
    plugin_root = Path(__file__).resolve().parents[1]
    data_dir = (
        os.environ.get("DEV_FLOW_DATA_DIR")
        or os.environ.get("PLUGIN_DATA")
        or None
    )
    service = PackageControllerService(
        plugin_root=plugin_root,
        data_dir=data_dir,
    )
    try:
        server = McpServer(service, enabled_tools=enabled)
    except ValueError as exc:
        sys.stderr.write(
            _bounded_text(exc, MAX_ERROR_MESSAGE_BYTES) + "\n"
        )
        return 2

    def request_stop(
        _signum: int, _frame: object
    ) -> None:
        server.stop()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            try:
                signal.signal(signal_value, request_stop)
            except (OSError, RuntimeError, ValueError):
                pass
    try:
        return server.run_stream(sys.stdin.buffer, sys.stdout.buffer)
    except KeyboardInterrupt:
        server.stop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
