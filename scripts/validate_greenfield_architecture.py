#!/usr/bin/env python3
"""Validate the explicit dependency boundary of the greenfield V4 runtime."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "src" / "dev_flow_orchestrator"
OLD_RUNTIME = "dev_flow_parts"
FORBIDDEN_CALLS = {"eval", "exec"}
DOMAIN_MODULES = {
    "model.py",
    "product.py",
    "engine.py",
    "workflow.py",
    "repository_kernel.py",
}
INFRASTRUCTURE_MODULES = {
    "authority",
    "controller",
    "filesystem",
    "git_client",
    "journal",
    "store",
    "cli",
    "mcp",
    "hook",
}
PROFILE_LITERALS = {
    "single-repository",
    "multi-repository",
}


def _module_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def validate() -> dict[str, object]:
    errors: list[dict[str, object]] = []
    inspected: list[str] = []
    if not RUNTIME_ROOT.is_dir():
        return {
            "ok": True,
            "runtime_present": False,
            "inspected": inspected,
            "errors": errors,
        }
    for path in sorted(RUNTIME_ROOT.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        inspected.append(relative)
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(
                {
                    "code": "GREENFIELD_SYNTAX_INVALID",
                    "path": relative,
                    "line": exc.lineno,
                }
            )
            continue
        imports = _module_imports(tree)
        if any(OLD_RUNTIME in name for name in imports) or OLD_RUNTIME in source:
            errors.append(
                {
                    "code": "GREENFIELD_OLD_RUNTIME_DEPENDENCY",
                    "path": relative,
                }
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in FORBIDDEN_CALLS:
                errors.append(
                    {
                        "code": "GREENFIELD_DYNAMIC_SOURCE_EXECUTION",
                        "path": relative,
                        "line": node.lineno,
                    }
                )
        if path.name in DOMAIN_MODULES:
            forbidden = sorted(
                name
                for name in imports
                if name.split(".")[-1] in INFRASTRUCTURE_MODULES
            )
            if forbidden:
                errors.append(
                    {
                        "code": "GREENFIELD_DOMAIN_INFRASTRUCTURE_DEPENDENCY",
                        "path": relative,
                        "imports": forbidden,
                    }
                )
        duplicate_profile_values = sorted(
            {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in PROFILE_LITERALS
            }
        )
        if path.name != "product.py" and duplicate_profile_values:
            errors.append(
                {
                    "code": "GREENFIELD_DUPLICATE_PRODUCT_MATRIX",
                    "path": relative,
                    "values": duplicate_profile_values,
                }
            )
    return {
        "ok": not errors,
        "runtime_present": True,
        "inspected": inspected,
        "errors": errors,
    }


def main() -> int:
    result = validate()
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
