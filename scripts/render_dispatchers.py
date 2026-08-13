#!/usr/bin/env python3
"""Render byte-stable public dispatchers for one installation root."""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sys


SCHEMA = "dev-flow-stable-dispatchers/1.0.0"
PROTOCOL = "dev-flow-dispatcher/1.0.0"
_MODES = {"dev-flow": "cli", "dev-flow-mcp": "mcp", "dev-flow-uninstall": "uninstall"}
_RECOVERY_PREFIX = ".dev-flow-uninstall-recovery-"


class DispatcherRenderError(RuntimeError):
    pass


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _cmd_quote(value: str) -> str:
    if any(character in value for character in '\r\n\0"'):
        raise DispatcherRenderError("Windows dispatcher path is not representable")
    # cmd.exe expands percent pairs before Python sees the value.
    return value.replace("%", "%%")


def _python_quote(value: str) -> str:
    return repr(value)


def _recovery_root(value: str, *, windows: bool) -> str:
    normalized = ntpath.normcase(value) if windows else os.path.normcase(value)
    identity = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    parent = ntpath.dirname(value) if windows else os.path.dirname(value)
    return (
        ntpath.join(parent, _RECOVERY_PREFIX + identity)
        if windows
        else os.path.join(parent, _RECOVERY_PREFIX + identity)
    )


def _posix(
    runtime_root: Path, support: Path, recovery_support: Path, mode: str
) -> bytes:
    prelude = ""
    rendered_support = _shell_quote(str(support))
    if mode == "uninstall":
        prelude = (
            "dev_flow_support="
            + rendered_support
            + "\n"
            + "if [ ! -f \"$dev_flow_support\" ]; then\n"
            + "  dev_flow_support="
            + _shell_quote(str(recovery_support))
            + "\n"
            + "fi\n"
        )
        rendered_support = '"$dev_flow_support"'
    return (
        "#!/bin/sh\n"
        "# dev-flow-orchestrator stable dispatcher; protocol " + PROTOCOL + "\n"
        "set -eu\n"
        + prelude
        + "exec env PYTHONDONTWRITEBYTECODE=1 "
        + _shell_quote(str(Path(sys.executable)))
        + " -B -I "
        + rendered_support
        + " --runtime-root "
        + _shell_quote(str(runtime_root))
        + " "
        + mode
        + " -- \"$@\"\n"
    ).encode("utf-8")


def _windows(
    runtime_root: str, support: str, recovery_support: str, mode: str
) -> bytes:
    prelude = ""
    rendered_support = '"' + _cmd_quote(support) + '"'
    if mode == "uninstall":
        prelude = (
            'set "DEV_FLOW_SUPPORT=' + _cmd_quote(support) + '"\r\n'
            'if not exist "%DEV_FLOW_SUPPORT%" set "DEV_FLOW_SUPPORT='
            + _cmd_quote(recovery_support)
            + '"\r\n'
        )
        rendered_support = '"%DEV_FLOW_SUPPORT%"'
    return (
        "@echo off\r\n"
        "rem dev-flow-orchestrator stable dispatcher; protocol " + PROTOCOL + "\r\n"
        "set \"PYTHONDONTWRITEBYTECODE=1\"\r\n"
        + prelude
        + '"' + _cmd_quote(str(Path(sys.executable))) + '" -B -I '
        + rendered_support + ' --runtime-root "'
        + _cmd_quote(runtime_root) + '" ' + mode + ' -- %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    ).encode("utf-8")


def render_dispatchers(runtime_root: Path, *, windows: bool) -> dict[str, bytes]:
    raw_root = str(runtime_root)
    if windows:
        if not ntpath.isabs(raw_root):
            raise DispatcherRenderError("managed runtime root must be absolute")
        normalized_root = ntpath.normpath(raw_root)
    else:
        if not runtime_root.is_absolute():
            raise DispatcherRenderError("managed runtime root must be absolute")
        normalized_root = os.path.abspath(runtime_root)
    if not normalized_root:
        raise DispatcherRenderError("managed runtime root must be absolute")
    runtime_root = Path(normalized_root)
    support = runtime_root / "lifecycle" / "stable_dispatcher.py"
    recovery_root = _recovery_root(normalized_root, windows=False)
    recovery_support = Path(recovery_root) / "stable_dispatcher.py"
    windows_root = normalized_root
    windows_support = ntpath.join(windows_root, "lifecycle", "stable_dispatcher.py")
    windows_recovery_support = ntpath.join(
        _recovery_root(windows_root, windows=True), "stable_dispatcher.py"
    )
    rendered: dict[str, bytes] = {}
    for name, mode in _MODES.items():
        filename = name + (".cmd" if windows else "")
        rendered[filename] = (
            _windows(
                windows_root, windows_support, windows_recovery_support, mode
            )
            if windows
            else _posix(runtime_root, support, recovery_support, mode)
        )
    return rendered


def dispatcher_manifest(runtime_root: Path, *, windows: bool) -> dict[str, object]:
    rendered = render_dispatchers(runtime_root, windows=windows)
    return {
        "schema": SCHEMA,
        "dispatcher_protocol": PROTOCOL,
        "runtime_root": str(runtime_root),
        "platform": "windows" if windows else "posix",
        "files": [
            {
                "name": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
            for name, payload in sorted(rendered.items())
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--windows", action="store_true")
    arguments = parser.parse_args()
    rendered = render_dispatchers(arguments.runtime_root, windows=arguments.windows)
    arguments.output.mkdir(parents=True, exist_ok=False)
    for name, payload in rendered.items():
        path = arguments.output / name
        with path.open("xb") as stream:
            stream.write(payload)
        if not arguments.windows:
            path.chmod(0o755)
    print(json.dumps(dispatcher_manifest(arguments.runtime_root, windows=arguments.windows), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
