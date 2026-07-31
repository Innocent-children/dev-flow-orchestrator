"""Thin JSON-RPC stdio adapter for the greenfield V4 controller."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Callable, Mapping, Optional, Sequence

from .controller import Controller
from .model import DevFlowError


SERVER_NAME = "dev-flow-orchestrator"
SERVER_VERSION = "4.0.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_REQUEST_BYTES = 64 * 1024


def _object_schema(properties: Mapping[str, object], required: Sequence[str]) -> dict:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


_STRING = {"type": "string", "minLength": 1}
_ROUTING_ID = {"type": "string", "minLength": 1, "maxLength": 256}
_REVISION = {"type": "integer", "minimum": 0}
TOOLS = (
    {
        "name": "task-start",
        "description": "Create one explicit full@4 or lite@4 schema-v4 task.",
        "inputSchema": _object_schema(
            {
                "requirement": _STRING,
                "workflow": {"type": "string", "enum": ["full", "lite"]},
                "workspace_strategy": {
                    "type": "string",
                    "enum": ["in-place", "branch", "worktree"],
                },
                "repositories": {
                    "type": "array",
                    "items": _STRING,
                    "minItems": 1,
                },
                "task_id": _STRING,
            },
            ("requirement", "workflow", "workspace_strategy", "repositories"),
        ),
    },
    {
        "name": "task-show",
        "description": "Read one current schema-v4 task.",
        "inputSchema": _object_schema({"task_id": _STRING}, ("task_id",)),
    },
    {
        "name": "task-next",
        "description": "Read the graph-derived agent-v1 current action.",
        "inputSchema": _object_schema(
            {"task_id": _STRING, "session_id": _ROUTING_ID},
            ("task_id",),
        ),
    },
    {
        "name": "task-preflight",
        "description": "Record bounded current Git evidence for the exact repository set.",
        "inputSchema": _object_schema(
            {"task_id": _STRING, "expected_revision": _REVISION},
            ("task_id", "expected_revision"),
        ),
    },
    {
        "name": "action-apply",
        "description": "Apply the current controller-owned action at an exact revision.",
        "inputSchema": _object_schema(
            {
                "task_id": _STRING,
                "expected_revision": _REVISION,
                "action_id": _STRING,
                "payload": {"type": "object"},
                "session_id": _ROUTING_ID,
                "request_turn_id": _ROUTING_ID,
            },
            ("task_id", "expected_revision", "action_id"),
        ),
    },
    {
        "name": "effect-inspect",
        "description": "Inspect current V4 effect journal entries for one task.",
        "inputSchema": _object_schema({"task_id": _STRING}, ("task_id",)),
    },
    {
        "name": "effect-recover",
        "description": "Apply one explicit current V4 effect recovery decision.",
        "inputSchema": _object_schema(
            {
                "task_id": _STRING,
                "execution_id": _STRING,
                "mode": {
                    "type": "string",
                    "enum": ["settle", "abandon", "reattach", "compensate"],
                },
                "session_id": _ROUTING_ID,
                "request_turn_id": _ROUTING_ID,
            },
            ("task_id", "execution_id", "mode"),
        ),
    },
)


class McpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_schema(value: object, schema: Mapping[str, object], field: str) -> None:
    expected = schema.get("type")
    string_bytes = None
    if isinstance(value, str):
        try:
            string_bytes = len(value.encode("utf-8"))
        except UnicodeError:
            string_bytes = -1
    valid = (
        expected == "string"
        and isinstance(value, str)
        and len(value) >= schema.get("minLength", 0)
        and len(value) <= schema.get("maxLength", len(value))
        and string_bytes is not None
        and string_bytes >= 0
        and string_bytes <= schema.get("maxLength", string_bytes)
    ) or (
        expected == "integer"
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= schema.get("minimum", value)
    ) or (
        expected == "object"
        and isinstance(value, dict)
    ) or (
        expected == "array"
        and isinstance(value, list)
        and len(value) >= schema.get("minItems", 0)
    )
    if not valid:
        raise McpError(-32602, field + " has the wrong type or bound")
    choices = schema.get("enum")
    if isinstance(choices, list) and value not in choices:
        raise McpError(-32602, field + " is not an allowed value")
    items = schema.get("items")
    if isinstance(value, list) and isinstance(items, Mapping):
        for index, item in enumerate(value):
            _validate_schema(item, items, "{}[{}]".format(field, index))


def _validate_tool_arguments(name: str, arguments: Mapping[str, object]) -> None:
    tool = next((item for item in TOOLS if item["name"] == name), None)
    if tool is None:
        raise McpError(-32602, "unknown tool")
    schema = tool["inputSchema"]
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise McpError(-32602, "unknown tool arguments: " + ", ".join(unknown))
    missing = [
        field for field in schema["required"]
        if field not in arguments
    ]
    if missing:
        raise McpError(-32602, "required tool argument is missing")
    for field, value in arguments.items():
        _validate_schema(value, properties[field], field)


class McpServer:
    """Own MCP framing only; every product operation calls Controller."""

    def __init__(self, data_dir: str) -> None:
        self.controller = Controller(data_dir)
        self.initialized = False

    @staticmethod
    def _arguments(params: object) -> tuple[str, dict]:
        if not isinstance(params, dict):
            raise McpError(-32602, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise McpError(-32602, "tool name and arguments are invalid")
        return name, arguments

    def _dispatch_tool(self, name: str, arguments: dict) -> dict:
        _validate_tool_arguments(name, arguments)
        operations: Mapping[str, Callable[[], object]] = {
            "task-start": lambda: self.controller.start(
                requirement=arguments["requirement"],
                workflow=arguments["workflow"],
                workspace_strategy=arguments["workspace_strategy"],
                repositories=arguments["repositories"],
                task_id=arguments.get("task_id"),
            ).as_dict(),
            "task-show": lambda: self.controller.show(arguments["task_id"]).as_dict(),
            "task-next": lambda: self.controller.next(
                arguments["task_id"],
                session_id=arguments.get("session_id"),
            ),
            "task-preflight": lambda: self.controller.preflight(
                arguments["task_id"],
                arguments["expected_revision"],
            ).as_dict(),
            "action-apply": lambda: self.controller.apply(
                arguments["task_id"],
                arguments["expected_revision"],
                arguments["action_id"],
                arguments.get("payload"),
                session_id=arguments.get("session_id"),
                request_turn_id=arguments.get("request_turn_id"),
            ).as_dict(),
            "effect-inspect": lambda: self.controller.effect_inspect(
                arguments["task_id"]
            ),
            "effect-recover": lambda: self.controller.recover_effect(
                arguments["task_id"],
                arguments["execution_id"],
                arguments["mode"],
                session_id=arguments.get("session_id"),
                request_turn_id=arguments.get("request_turn_id"),
            ),
        }
        operation = operations.get(name)
        if operation is None:
            raise McpError(-32602, "unknown tool")
        try:
            value = operation()
            result = {"ok": True, "result": value}
            is_error = False
        except KeyError as exc:
            raise McpError(-32602, "required tool argument is missing") from exc
        except (TypeError, ValueError) as exc:
            raise McpError(-32602, "tool arguments are invalid") from exc
        except DevFlowError as exc:
            result = exc.as_dict()
            is_error = True
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "content": [{"type": "text", "text": encoded}],
            "structuredContent": result,
            "isError": is_error,
        }

    def dispatch(self, request: object) -> Optional[dict]:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            raise McpError(-32600, "invalid JSON-RPC request")
        method = request.get("method")
        request_id = request.get("id")
        if method == "notifications/initialized":
            self.initialized = True
            return None
        if request_id is None:
            return None
        if method == "initialize":
            params = request.get("params")
            offered = params.get("protocolVersion") if isinstance(params, dict) else None
            protocol = offered if offered in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": list(TOOLS)},
            }
        if method == "tools/call":
            name, arguments = self._arguments(request.get("params"))
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self._dispatch_tool(name, arguments),
            }
        raise McpError(-32601, "method not found")


def _data_dir(arguments: argparse.Namespace) -> str:
    value = arguments.data_dir or os.environ.get("PLUGIN_DATA")
    if not value:
        raise DevFlowError(
            "DATA_DIR_REQUIRED",
            "--data-dir or PLUGIN_DATA is required",
        )
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-flow-mcp")
    parser.add_argument("--data-dir")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        server = McpServer(_data_dir(_parser().parse_args(argv)))
    except DevFlowError as exc:
        print(
            json.dumps(exc.as_dict(), separators=(",", ":")),
            file=sys.stderr,
        )
        return 2
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_REQUEST_BYTES:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "request is too large"},
            }
        else:
            request_id = None
            try:
                request = json.loads(raw.decode("utf-8"))
                request_id = request.get("id") if isinstance(request, dict) else None
                response = server.dispatch(request)
            except (UnicodeError, ValueError):
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32700, "message": "parse error"},
                }
            except McpError as exc:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": exc.code, "message": exc.message},
                }
            except Exception:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": "internal error"},
                }
        if response is not None:
            sys.stdout.write(
                json.dumps(
                    response,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
