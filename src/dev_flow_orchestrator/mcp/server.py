"""Construction of the single strict local STDIO MCP server."""

from __future__ import annotations

import os
from typing import AsyncIterator

import anyio

from mcp.server import MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ToolExecution

from .._version import RELEASE_VERSION
from ..model import strict_json_loads
from .application import MCPApplication
from .guidance import SERVER_INSTRUCTIONS
from .identity import SERVER_NAME
from .logging import emit
from .results import internal_error, new_request_id
from .schemas import OUTPUT_SCHEMAS, ResultSchemaViolation, validate_structured_result
from .tools import register_tools


MAX_PROTOCOL_LINE_BYTES = 2 * 1024 * 1024
_INVALID_JSON_LINE = "{\n"


class _StrictJsonLineStream:
    """Preflight UTF-8, duplicates, non-finite values, and line bounds.

    Invalid input is replaced with malformed JSON so the official MCP STDIO
    parser and low-level server retain ownership of the protocol error.
    """

    def __init__(self, stream: anyio.AsyncFile[bytes]) -> None:
        self._stream = stream

    @staticmethod
    def _checked(raw: bytes) -> str:
        if len(raw) > MAX_PROTOCOL_LINE_BYTES:
            return _INVALID_JSON_LINE
        try:
            text = raw.decode("utf-8", errors="strict")
            strict_json_loads(text)
        except (UnicodeError, ValueError):
            return _INVALID_JSON_LINE
        return text

    async def __aiter__(self) -> AsyncIterator[str]:
        pending = bytearray()
        discarding = False
        while True:
            chunk = await self._stream.read(64 * 1024)
            if not chunk:
                break
            pending.extend(chunk)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                raw = bytes(pending[: newline + 1])
                del pending[: newline + 1]
                if discarding:
                    discarding = False
                    yield _INVALID_JSON_LINE
                else:
                    yield self._checked(raw)
            if len(pending) > MAX_PROTOCOL_LINE_BYTES:
                pending.clear()
                discarding = True
        if discarding:
            yield _INVALID_JSON_LINE
        elif pending:
            yield self._checked(bytes(pending))


class DevFlowMCPServer(MCPServer):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.execution = ToolExecution(taskSupport="forbidden")
            tool.output_schema = OUTPUT_SCHEMAS[tool.name]
        return tools

    async def call_tool(self, name, arguments, context=None):
        result = await super().call_tool(name, arguments, context)
        if not isinstance(result, CallToolResult):
            return result
        try:
            validate_structured_result(name, result.structured_content)
        except ResultSchemaViolation:
            request_id = new_request_id()
            emit(
                level="error",
                event="output_schema_violation",
                request_id=request_id,
                tool=name,
                code="INTERNAL_ERROR",
            )
            return internal_error(name, request_id)
        return result

    async def run_stdio_async(self) -> None:
        """Run the official STDIO/low-level stack with a strict input preflight."""
        duplicate = os.fdopen(os.dup(0), "rb", buffering=0)
        stdin = anyio.wrap_file(duplicate)
        try:
            async with stdio_server(stdin=_StrictJsonLineStream(stdin)) as (read_stream, write_stream):
                await self._lowlevel_server.run(
                    read_stream,
                    write_stream,
                    self._lowlevel_server.create_initialization_options(),
                )
        finally:
            await stdin.aclose()


def create_server(data_dir: str) -> MCPServer:
    server = DevFlowMCPServer(
        name=SERVER_NAME,
        title="Dev Flow Orchestrator",
        description="Typed local adapter for the authoritative Dev Flow Controller.",
        instructions=SERVER_INSTRUCTIONS,
        version=RELEASE_VERSION,
        resources=[],
        log_level="WARNING",
    )
    register_tools(server, MCPApplication(data_dir))
    for method in (
        "prompts/list",
        "prompts/get",
        "resources/list",
        "resources/read",
        "resources/templates/list",
        "resources/subscribe",
        "resources/unsubscribe",
        "subscriptions/listen",
    ):
        server._lowlevel_server._request_handlers.pop(method, None)
    return server
