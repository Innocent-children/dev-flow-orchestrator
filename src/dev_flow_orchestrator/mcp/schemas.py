"""Generated transport constraints and structured-result validation."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import Field


TaskId = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$"),
]
ShortText = Annotated[str, Field(min_length=1, max_length=8192)]
PathText = Annotated[str, Field(min_length=1, max_length=32768)]
PageLimit = Annotated[int, Field(strict=True, ge=1, le=100)]
PageOffset = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
Cursor = Annotated[
    str,
    Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$"),
]
WorkflowRef = Annotated[str, Field(min_length=1, max_length=32768)]
WorkflowId = Literal["bugfix", "feature", "full", "investigation", "lite", "refactor"]
TaskStatus = Literal[
    "INTAKE", "ANALYZING", "PLANNING", "IMPLEMENTING", "INVESTIGATING",
    "DOCUMENTING", "VERIFYING", "FINALIZING", "DONE", "INCOMPLETE", "CANCELLED",
]
WorkflowList = Annotated[list[WorkflowRef], Field(max_length=100)]
StatusList = Annotated[list[TaskStatus], Field(max_length=11)]
RepositoryList = Annotated[list[PathText], Field(min_length=1, max_length=8)]
JsonObject = dict[str, Any]
StrictFlag = Annotated[bool, Field(strict=True)]


REQUEST_ID_PATTERN = (
    r"^mcp-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
TOOL_NAME_ENUM = [
    "dev_flow_server_info",
    "dev_flow_list_tasks",
    "dev_flow_find_tasks_for_path",
    "dev_flow_get_task",
    "dev_flow_get_next_action",
    "dev_flow_start_task",
    "dev_flow_apply_action",
    "dev_flow_revise_contract",
    "dev_flow_record_decision",
    "dev_flow_dispose_finding",
    "dev_flow_cancel_task",
]
RECOVERY_KIND_ENUM = [
    "correct-request",
    "discover-task",
    "inspect-diagnostics",
    "narrow-request",
    "read-after-write",
    "read-current-state",
    "refresh-current-action",
    "retry-later",
]


RECOVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "blind_retry"],
    "properties": {
        "kind": {"enum": RECOVERY_KIND_ENUM},
        "tool": {
            "type": "string",
            "pattern": "^dev_flow_[a-z_]+$",
            "maxLength": 64,
        },
        "task_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "blind_retry": {"type": "boolean"},
    },
}
ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code", "message", "details", "recovery"],
    "properties": {
        "code": {"type": "string", "minLength": 1, "maxLength": 128},
        "message": {"type": "string", "minLength": 1, "maxLength": 8192},
        "details": {"type": "object", "maxProperties": 128},
        "recovery": {"anyOf": [RECOVERY_SCHEMA, {"type": "null"}]},
    },
}


def result_schema(tool: str, data_schema: dict[str, Any]) -> dict[str, Any]:
    """Build the exact success/error union published for one stable tool."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "ok", "tool", "request_id", "result", "error"],
        "properties": {
            "schema": {"const": "dev-flow-mcp-result/1.0.0"},
            "ok": {"type": "boolean"},
            "tool": {"const": tool},
            "request_id": {"type": "string", "pattern": REQUEST_ID_PATTERN},
            "result": {},
            "error": {},
        },
        "oneOf": [
            {
                "properties": {
                    "ok": {"const": True},
                    "result": data_schema,
                    "error": {"type": "null"},
                },
                "required": ["ok", "result", "error"],
            },
            {
                "properties": {
                    "ok": {"const": False},
                    "result": {"type": "null"},
                    "error": ERROR_SCHEMA,
                },
                "required": ["ok", "result", "error"],
            },
        ],
    }


OBJECT: dict[str, Any] = {"type": "object"}
NULLABLE_OBJECT: dict[str, Any] = {"anyOf": [OBJECT, {"type": "null"}]}
CURRENT_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema", "task", "contract", "repository_set", "action", "inputs",
        "resources", "guidance", "source_projection_digest",
    ],
    "additionalProperties": False,
    "properties": {
        "schema": {"const": "dev-flow-mcp-action/1.0.0"},
        "task": OBJECT,
        "contract": OBJECT,
        "repository_set": OBJECT,
        "action": NULLABLE_OBJECT,
        "inputs": {"type": "array"},
        "resources": {"type": "array"},
        "guidance": OBJECT,
        "terminal": {},
        "source_projection_digest": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    },
}
MUTATION_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["receipt", "current"],
    "properties": {
        "receipt": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema", "task_id", "action_id", "committed_revision",
                "status", "current_node",
            ],
            "properties": {
                "schema": {"const": "dev-flow-receipt/0.4.0"},
                "task_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "action_id": {"type": "string", "minLength": 1, "maxLength": 8192},
                "committed_revision": {"type": "integer", "minimum": 0},
                "status": {"type": "string", "minLength": 1, "maxLength": 64},
                "current_node": {"type": "string", "minLength": 1, "maxLength": 256},
            },
        },
        "current": OBJECT,
    },
}


OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "dev_flow_server_info": result_schema(
        "dev_flow_server_info",
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "server", "release_version", "model_version", "model_namespace",
                "interface_schema", "result_schema", "action_schema",
                "guidance_schema", "transport", "python", "workflow_ids",
                "repository_count", "registration_mode", "tool_catalog_digest",
                "guidance_catalog_digest", "health", "data_root_available",
            ],
            "properties": {
                "server": {"const": "dev-flow"},
                "release_version": {"type": "string", "minLength": 1, "maxLength": 64},
                "model_version": {"const": "0.4.0"},
                "model_namespace": {"const": "0.4.0"},
                "interface_schema": {"const": "dev-flow-mcp/1.0.0"},
                "result_schema": {"const": "dev-flow-mcp-result/1.0.0"},
                "action_schema": {"const": "dev-flow-mcp-action/1.0.0"},
                "guidance_schema": {"const": "dev-flow-mcp-guidance/1.0.0"},
                "transport": {"const": "stdio"},
                "python": {"const": ">=3.10,<3.15"},
                "workflow_ids": {
                    "type": "array",
                    "items": {"enum": [
                        "bugfix", "feature", "full", "investigation", "lite", "refactor",
                    ]},
                    "minItems": 6,
                    "maxItems": 6,
                    "uniqueItems": True,
                },
                "repository_count": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["minimum", "maximum"],
                    "properties": {
                        "minimum": {"const": 1},
                        "maximum": {"const": 8},
                    },
                },
                "registration_mode": {"enum": ["bundled", "standalone", "unknown"]},
                "tool_catalog_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "guidance_catalog_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "health": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "code"],
                    "properties": {
                        "status": {"enum": ["ready", "unavailable"]},
                        "code": {
                            "anyOf": [
                                {"type": "string", "minLength": 1, "maxLength": 128},
                                {"type": "null"},
                            ],
                        },
                    },
                },
                "data_root_available": {"type": "boolean"},
            },
        },
    ),
    "dev_flow_list_tasks": result_schema(
        "dev_flow_list_tasks",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["health", "filters", "tasks", "diagnostics", "page", "next_cursor"],
            "properties": {
                "health": {"type": "string", "minLength": 1, "maxLength": 64},
                "filters": OBJECT,
                "tasks": {"type": "array", "items": OBJECT, "maxItems": 100},
                "diagnostics": {"type": "array", "items": OBJECT, "maxItems": 100},
                "page": OBJECT,
                "next_cursor": {
                    "anyOf": [
                        {"type": "string", "minLength": 1, "maxLength": 512},
                        {"type": "null"},
                    ],
                },
            },
        },
    ),
    "dev_flow_find_tasks_for_path": result_schema(
        "dev_flow_find_tasks_for_path",
        {
            "type": "object",
            "required": ["classification", "tasks", "diagnostics"],
            "additionalProperties": False,
            "properties": {
                "classification": {
                    "enum": ["none", "single", "ambiguous", "inventory-unavailable"],
                },
                "tasks": {"type": "array", "items": OBJECT, "maxItems": 100},
                "diagnostics": {"type": "array", "items": OBJECT, "maxItems": 100},
            },
        },
    ),
    "dev_flow_get_task": result_schema(
        "dev_flow_get_task",
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["task", "health", "why_next", "timeline", "artifacts", "dossier", "recovery"],
            "properties": {
                "task": OBJECT,
                "health": {"type": "string", "minLength": 1, "maxLength": 64},
                "why_next": OBJECT,
                "timeline": OBJECT,
                "artifacts": {"type": "array"},
                "dossier": {},
                "recovery": OBJECT,
            },
        },
    ),
    "dev_flow_get_next_action": result_schema(
        "dev_flow_get_next_action",
        CURRENT_ACTION_SCHEMA,
    ),
    "dev_flow_start_task": result_schema(
        "dev_flow_start_task",
        {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "task_id", "revision", "status", "current_node",
                "repository_set", "next",
            ],
            "properties": {
                "task_id": {"type": "string", "minLength": 1, "maxLength": 256},
                "revision": {"type": "integer", "minimum": 0},
                "status": {"type": "string", "minLength": 1, "maxLength": 64},
                "current_node": {"type": "string", "minLength": 1, "maxLength": 256},
                "repository_set": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["repository_set_id", "repository_ids", "count"],
                    "properties": {
                        "repository_set_id": {"type": "string", "minLength": 1, "maxLength": 128},
                        "repository_ids": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1, "maxLength": 128},
                            "minItems": 1,
                            "maxItems": 8,
                            "uniqueItems": True,
                        },
                        "count": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                },
                "next": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["tool", "task_id"],
                    "properties": {
                        "tool": {"const": "dev_flow_get_next_action"},
                        "task_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                },
            },
        },
    ),
    "dev_flow_apply_action": result_schema("dev_flow_apply_action", MUTATION_RESULT_SCHEMA),
    "dev_flow_revise_contract": result_schema("dev_flow_revise_contract", MUTATION_RESULT_SCHEMA),
    "dev_flow_record_decision": result_schema("dev_flow_record_decision", MUTATION_RESULT_SCHEMA),
    "dev_flow_dispose_finding": result_schema("dev_flow_dispose_finding", MUTATION_RESULT_SCHEMA),
    "dev_flow_cancel_task": result_schema("dev_flow_cancel_task", MUTATION_RESULT_SCHEMA),
}


class ResultSchemaViolation(RuntimeError):
    """Raised internally when the adapter produced an invalid result."""


_OUTPUT_VALIDATORS = {
    name: Draft202012Validator(schema)
    for name, schema in OUTPUT_SCHEMAS.items()
}
_CURRENT_ACTION_VALIDATOR = Draft202012Validator(CURRENT_ACTION_SCHEMA)


def validate_structured_result(tool: str, value: object) -> None:
    """Validate a produced envelope before it can reach the MCP transport."""
    validator = _OUTPUT_VALIDATORS.get(tool)
    if validator is None:
        raise ResultSchemaViolation("no output schema exists for the tool")
    error = next(validator.iter_errors(value), None)
    if error is not None:
        raise ResultSchemaViolation("structured result violates its declared output schema")


def validate_current_action(value: object) -> None:
    """Apply the full current-action schema when it is nested in a mutation."""
    if next(_CURRENT_ACTION_VALIDATOR.iter_errors(value), None) is not None:
        raise ResultSchemaViolation("nested current action violates its declared schema")
