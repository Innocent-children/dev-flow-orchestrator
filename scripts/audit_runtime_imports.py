#!/usr/bin/env python3
"""Audit shipped Python runtime imports and isolated startup."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
import sysconfig
from pathlib import Path


RUNTIME_FILES = (
    Path("scripts/dev_flow.py"),
    Path("scripts/dev_flow_mcp.py"),
    Path("hooks/dev_flow_hook.py"),
)
RUNTIME_DIRECTORIES = (Path("scripts/dev_flow_parts"),)


def _python_files(root: Path) -> list[Path]:
    files = [root / path for path in RUNTIME_FILES]
    for directory in RUNTIME_DIRECTORIES:
        files.extend(sorted((root / directory).glob("*.py")))
    return files


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _is_stdlib(name: str, package_internal: set[str]) -> bool:
    if name in package_internal:
        return True
    if name in sys.builtin_module_names:
        return True
    stdlib_names = getattr(sys, "stdlib_module_names", frozenset())
    if stdlib_names:
        return name in stdlib_names
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin in {None, "built-in", "frozen"}:
        return spec is not None
    origin = Path(spec.origin).resolve()
    paths = {
        key: Path(value).resolve()
        for key, value in sysconfig.get_paths().items()
        if key in {"stdlib", "platstdlib", "purelib", "platlib"} and value
    }
    for key in ("purelib", "platlib"):
        installed = paths.get(key)
        if installed is not None and (
            origin == installed or installed in origin.parents
        ):
            return False
    for key in ("stdlib", "platstdlib"):
        stdlib = paths.get(key)
        if stdlib is not None and (
            origin == stdlib or stdlib in origin.parents
        ):
            return True
    return False


def _isolated_smoke(
    root: Path,
    relative_path: str,
    *,
    arguments: tuple[str, ...] = (),
    input_bytes: bytes = b"",
) -> dict[str, str] | None:
    path = root / relative_path
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(path), *arguments],
        cwd=root,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        return {
            "path": relative_path,
            "import": f"isolated-startup:{completed.returncode}",
        }
    return None


def audit(root: Path) -> dict[str, object]:
    violations: list[dict[str, str]] = []
    checked: list[str] = []
    python_files = _python_files(root)
    package_internal = {path.stem for path in python_files}
    package_internal.update(path.name for path in RUNTIME_DIRECTORIES)
    for path in python_files:
        relative = path.relative_to(root).as_posix()
        checked.append(relative)
        for name in sorted(_import_roots(path)):
            if not _is_stdlib(name, package_internal):
                violations.append({"path": relative, "import": name})
    mcp_input = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "runtime-import-audit",
                        "version": "1",
                    },
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    hook_input = (
        json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "runtime-import-audit",
                "source": "startup",
                "cwd": str(root),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    for smoke in (
        _isolated_smoke(
            root,
            "scripts/dev_flow.py",
            arguments=("--help",),
        ),
        _isolated_smoke(
            root,
            "scripts/dev_flow_mcp.py",
            input_bytes=mcp_input,
        ),
        _isolated_smoke(
            root,
            "hooks/dev_flow_hook.py",
            input_bytes=hook_input,
        ),
    ):
        if smoke is not None:
            violations.append(smoke)
    return {
        "schema": "dev-flow-v4-runtime-import-audit/v1",
        "ok": not violations,
        "files": checked,
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
