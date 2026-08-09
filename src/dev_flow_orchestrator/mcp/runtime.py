"""Bounded STDIO-only MCP runtime entry point."""

from __future__ import annotations

import argparse
import importlib.metadata
import struct
import sys

from .._version import RELEASE_VERSION
from ..model import DevFlowError
from ..product import MODEL_VERSION, PLUGIN_DATA_NAMESPACE
from ..review_guidance import INDEPENDENT_REVIEW_GUIDANCE_DIGEST
from ..runtime_paths import resolve_data_dir
from .identity import (
    MCP_ACTION_SCHEMA,
    MCP_GUIDANCE_SCHEMA,
    MCP_INTERFACE_SCHEMA,
    MCP_RESULT_SCHEMA,
)
from .logging import configure, write_startup_error
from .server import create_server
from .catalog import (
    GUIDANCE_CATALOG_DIGEST,
    TOOL_NAMES,
    _digest,
    catalog_digest,
    canonical_tool_projection,
)
from .guidance import GUIDANCE_CATALOG, SERVER_INSTRUCTIONS
from .schemas import OUTPUT_SCHEMAS


UNSUPPORTED_OPTIONS = (
    "--http", "--sse", "--host", "--port", "--token", "--oauth", "--transport",
)
STARTUP_ERROR_CODES = frozenset({
    "MCP_RUNTIME_UNAVAILABLE",
    "MCP_DEPENDENCY_INVALID",
    "INTERNAL_ERROR",
})


class RuntimeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise DevFlowError(
            "MCP_RUNTIME_UNAVAILABLE",
            "invalid dev-flow-mcp runtime arguments; use the local --stdio transport",
        )


def _parser() -> argparse.ArgumentParser:
    parser = RuntimeArgumentParser(prog="dev-flow-mcp")
    parser.add_argument("--stdio", action="store_true", help="run the local STDIO transport")
    parser.add_argument(
        "--data-dir",
        help="controller data base directory; the Store appends the current model namespace",
    )
    parser.add_argument("--log-level", choices=("WARNING", "ERROR", "CRITICAL"), default="WARNING")
    return parser


def startup_self_check() -> None:
    if not ((3, 10) <= sys.version_info[:2] < (3, 15)):
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "Dev Flow MCP requires Python 3.10 through 3.14")
    if struct.calcsize("P") != 8:
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "Dev Flow MCP requires 64-bit Python")
    try:
        installed_release = importlib.metadata.version("dev-flow-orchestrator")
    except importlib.metadata.PackageNotFoundError as exc:
        raise DevFlowError(
            "MCP_DEPENDENCY_INVALID",
            "installed Dev Flow release metadata is unavailable",
        ) from exc
    if installed_release != RELEASE_VERSION:
        raise DevFlowError(
            "MCP_DEPENDENCY_INVALID",
            "installed Dev Flow release metadata does not match the runtime release",
        )
    try:
        major = importlib.metadata.version("mcp").split(".", 1)[0]
    except importlib.metadata.PackageNotFoundError as exc:
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "the MCP Python SDK is unavailable") from exc
    if major != "2":
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "Dev Flow MCP requires MCP Python SDK major 2")
    if MODEL_VERSION != "0.4.0" or PLUGIN_DATA_NAMESPACE != "0.4.0":
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "Dev Flow model identity or data namespace is invalid")
    if (
        MCP_INTERFACE_SCHEMA,
        MCP_RESULT_SCHEMA,
        MCP_ACTION_SCHEMA,
        MCP_GUIDANCE_SCHEMA,
    ) != (
        "dev-flow-mcp/1.0.0",
        "dev-flow-mcp-result/1.0.0",
        "dev-flow-mcp-action/1.0.0",
        "dev-flow-mcp-guidance/1.0.0",
    ):
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "MCP interface identity is invalid")
    if (
        len(TOOL_NAMES) != 11
        or TOOL_NAMES != tuple(sorted(OUTPUT_SCHEMAS))
        or len(SERVER_INSTRUCTIONS.encode("utf-8")) > 4 * 1024
    ):
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "MCP tool or instruction catalog is invalid")
    expected_guidance_digest = _digest({
        "server_instructions": SERVER_INSTRUCTIONS,
        "catalog": GUIDANCE_CATALOG,
        "independent_review_guidance_digest": INDEPENDENT_REVIEW_GUIDANCE_DIGEST,
    })
    if GUIDANCE_CATALOG_DIGEST != expected_guidance_digest:
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "MCP catalog digests are invalid")
    catalog_server = create_server(".")
    projection = canonical_tool_projection(
        catalog_server._tool_manager.list_tools(),
        output_schemas=OUTPUT_SCHEMAS,
    )
    expected_tool_digest = catalog_digest(projection)
    if getattr(catalog_server, "tool_catalog_digest", None) != expected_tool_digest:
        raise DevFlowError("MCP_DEPENDENCY_INVALID", "MCP catalog digests are invalid")


def main(argv: list[str] | None = None) -> int:
    try:
        raw_arguments = list(sys.argv[1:] if argv is None else argv)
        if any(
            item == option or item.startswith(option + "=")
            for item in raw_arguments
            for option in UNSUPPORTED_OPTIONS
        ):
            raise DevFlowError(
                "MCP_RUNTIME_UNAVAILABLE",
                "remote, authenticated, and listening transports are unsupported; use --stdio",
            )
        arguments = _parser().parse_args(raw_arguments)
        if not arguments.stdio:
            raise DevFlowError("MCP_RUNTIME_UNAVAILABLE", "only --stdio transport is supported")
        configure(arguments.log_level)
        startup_self_check()
        create_server(resolve_data_dir(arguments.data_dir)).run("stdio")
        return 0
    except DevFlowError as exc:
        if exc.code in STARTUP_ERROR_CODES:
            code = exc.code
            message = str(exc)
        else:
            code = "MCP_RUNTIME_UNAVAILABLE"
            message = "Dev Flow MCP runtime configuration is unavailable"
        write_startup_error(code, message=message)
        return 2
    except Exception:
        write_startup_error("INTERNAL_ERROR")
        return 2
