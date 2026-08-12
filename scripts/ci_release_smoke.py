#!/usr/bin/env python3
"""Run the lightweight installed-wheel/import/STDIO smoke used by the Python matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


class SmokeError(RuntimeError):
    """Raised when the installed release cannot complete the bounded smoke."""


_CLIENT = r"""
import asyncio
import os
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def smoke():
    parameters = StdioServerParameters(
        command=sys.argv[1],
        args=["--stdio", "--data-dir", sys.argv[2]],
        env=os.environ.copy(),
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(*streams) as session:
            initialized = await session.initialize()
            if initialized.server_info.name != "dev-flow":
                raise RuntimeError("unexpected MCP server identity")
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            if len(names) != 11 or "dev_flow_server_info" not in names:
                raise RuntimeError("unexpected MCP tool catalog")

asyncio.run(smoke())
"""


def _run(command: list[str], *, cwd: Path, timeout: int = 180) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SmokeError("{} failed: {}".format(command[0], detail[:2048]))


def smoke(root: Path) -> dict[str, object]:
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="dev-flow-wheel-smoke-") as name:
        work = Path(name).resolve()
        wheels = work / "wheels"
        wheels.mkdir()
        requirements = work / "runtime-requirements.txt"
        environment = work / "environment"
        data_dir = work / "controller-data"

        _run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--no-header",
                "--no-annotate",
                "--format",
                "requirements.txt",
                "--output-file",
                str(requirements),
            ],
            cwd=root,
        )
        _run(["uv", "build", "--wheel", "--out-dir", str(wheels)], cwd=root)
        built = sorted(wheels.glob("*.whl"))
        if len(built) != 1:
            raise SmokeError("wheel build did not produce exactly one wheel")

        _run(
            ["uv", "venv", "--python", sys.executable, str(environment)],
            cwd=root,
        )
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        entrypoint = environment / (
            "Scripts/dev-flow-mcp.exe" if sys.platform == "win32" else "bin/dev-flow-mcp"
        )
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--require-hashes",
                "--only-binary",
                ":all:",
                "-r",
                str(requirements),
            ],
            cwd=root,
        )
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--only-binary",
                ":all:",
                str(built[0]),
            ],
            cwd=root,
        )
        _run(
            [
                str(python),
                "-I",
                "-c",
                "from dev_flow_orchestrator.mcp.runtime import startup_self_check; startup_self_check()",
            ],
            cwd=work,
        )
        if not entrypoint.is_file():
            raise SmokeError("installed dev-flow-mcp entry point is missing")
        _run(
            [str(python), "-I", "-c", _CLIENT, str(entrypoint), str(data_dir)],
            cwd=work,
            timeout=30,
        )
        return {
            "ok": True,
            "python": "{}.{}.{}".format(*sys.version_info[:3]),
            "wheel": built[0].name,
            "wheel_only": True,
            "stdio": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    try:
        result = smoke(arguments.root)
    except (OSError, subprocess.SubprocessError, SmokeError) as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
