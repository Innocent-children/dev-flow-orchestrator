#!/usr/bin/env python3
"""Source-checkout launcher for the Dev Flow MCP server."""

from pathlib import Path
import sys


_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SOURCE_ROOT))

from dev_flow_orchestrator.mcp.runtime import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
