#!/usr/bin/env python3
"""Validate the one macOS greenfield V4 plugin package."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator.mcp import TOOLS  # noqa: E402
from dev_flow_orchestrator.engine import NODE_FAMILY_CATALOG  # noqa: E402
from dev_flow_orchestrator.product import PROFILES  # noqa: E402
from dev_flow_orchestrator.workflow import (  # noqa: E402
    FULL_GRAPH,
    LITE_GRAPH,
    PREFLIGHT_CONTRACT,
    REPOSITORY_CANCEL_CONTRACT,
    REPOSITORY_GRAPH,
    workflow_identity,
)


PUBLIC_RUNTIME = (
    "scripts/dev_flow.py",
    "scripts/dev_flow_mcp.py",
    "hooks/dev_flow_hook.py",
)
REQUIRED = (
    ".codex-plugin/plugin.json",
    ".mcp.json",
    "hooks/hooks.json",
    "scripts/dev_flow_python_launcher",
    "skills/analyze-change-impact/SKILL.md",
    "skills/follow-dev-flow/SKILL.md",
    "skills/review-dev-flow-change/SKILL.md",
    "src/dev_flow_orchestrator/authority.py",
    "src/dev_flow_orchestrator/controller.py",
    "src/dev_flow_orchestrator/engine.py",
    "src/dev_flow_orchestrator/product.py",
    "src/dev_flow_orchestrator/repository_kernel.py",
    "src/dev_flow_orchestrator/workflow.py",
    "ARCHITECTURE.md",
)
FORBIDDEN_PATH_PARTS = (
    "dev_flow_parts",
    "workflows/bundles",
    "workflows/runtime",
    "workflows/provenance",
)
FORBIDDEN_AUTHORITY_ENTRYPOINTS = (
    "scripts/dev_flow_authority.py",
    "src/dev_flow_orchestrator/authority_cli.py",
    "src/dev_flow_orchestrator/host_authority.py",
)
FORBIDDEN_SOURCE = re.compile(
    r"dev_flow_parts|workflow_bundle_identity|CLI_FALLBACK_SCHEMA|"
    r"\b(?:V2|V3|legacy)\b",
    re.IGNORECASE,
)
CURRENT_SOURCE_CLOSURE = (
    ".codex-plugin",
    ".github",
    ".gitattributes",
    ".gitignore",
    ".mcp.json",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "hooks",
    "pyproject.toml",
    "scripts",
    "skills",
    "src",
    "templates",
    "tests",
    "uv.lock",
    "workflows",
)
SOURCE_SCAN_IGNORED_PARTS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
# Keep the removed implementation signatures split so the validator itself is
# part of the closure instead of becoming a privileged self-exclusion.
POPUP_SOURCE_SIGNATURES = (
    (
        "approval-port",
        re.compile(
            r"\b(?:MacOS|Fake)?"
            + "Approval"
            + r"Port\b"
        ),
    ),
    (
        "apple-script-executable",
        re.compile(
            r"(?:/usr/bin/)?"
            + "osa"
            + r"script\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dialog-channel-schema",
        re.compile(
            "macos-system-"
            + "dialog/v1",
            re.IGNORECASE,
        ),
    ),
    (
        "dialog-script",
        re.compile(
            r"\bdisplay\s+"
            + r"dialog\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dialog-title",
        re.compile(
            "Dev Flow "
            + "Authority",
            re.IGNORECASE,
        ),
    ),
    (
        "dialog-timeout",
        re.compile(
            r"(?:timeout\s*=\s*"
            + r"120\b|120(?:-|\s+)second(?:s)?"
            + r"[^\n]{0,80}\b(?:dialog|popup)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "graphical-host-prerequisite",
        re.compile(
            r"(?:logged-in\s+)?graphical\s+"
            + r"macOS\s+(?:session|user)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "macos-dialog-product-reference",
        re.compile(
            r"\bmacOS\s+(?:system|approval)\s+"
            + r"dialog\b",
            re.IGNORECASE,
        ),
    ),
    (
        "popup-error-contract",
        re.compile(
            "HOST_"
            + r"APPROVAL_(?:UNAVAILABLE|INVALID|DENIED)\b"
        ),
    ),
)


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _check(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _current_source_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for relative in CURRENT_SOURCE_CLOSURE:
        candidate = root / relative
        candidates = (
            [candidate]
            if candidate.is_file() or candidate.is_symlink()
            else sorted(candidate.rglob("*"))
            if candidate.is_dir()
            else []
        )
        for path in candidates:
            if (
                not path.is_file()
                or path.suffix in {".pyc", ".pyo"}
                or any(part in SOURCE_SCAN_IGNORED_PARTS for part in path.parts)
            ):
                continue
            paths.append(path)
    return tuple(
        sorted(
            set(paths),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def validate_popup_source_closure(root: Path = ROOT) -> dict:
    """Audit every shipped/current product file, including this validator."""

    files: list[str] = []
    violations: list[dict[str, str]] = []
    for path in _current_source_paths(root):
        relative = path.relative_to(root).as_posix()
        files.append(relative)
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for signature, pattern in POPUP_SOURCE_SIGNATURES:
            if pattern.search(source):
                violations.append(
                    {
                        "path": relative,
                        "signature": signature,
                    }
                )
    return {
        "files": files,
        "violations": violations,
    }


def validate(root: Path = ROOT) -> dict:
    errors: list[str] = []
    for relative in REQUIRED:
        _check((root / relative).is_file(), errors, "missing " + relative)
    for relative in FORBIDDEN_AUTHORITY_ENTRYPOINTS:
        _check(
            not (root / relative).exists(),
            errors,
            "separate authority entrypoint remains: " + relative,
        )
    for relative in PUBLIC_RUNTIME:
        path = root / relative
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        _check("src" in source, errors, relative + " does not bootstrap src")
        _check("exec(" not in source, errors, relative + " executes source")
        _check(
            FORBIDDEN_SOURCE.search(source) is None,
            errors,
            relative + " references predecessor runtime",
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        _check(
            completed.returncode == 0,
            errors,
            relative + " isolated launch failed",
        )
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in relative for part in FORBIDDEN_PATH_PARTS):
            errors.append("predecessor package path remains: " + relative)
    runtime_root = root / "src" / "dev_flow_orchestrator"
    for path in sorted(runtime_root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError:
            errors.append("runtime syntax invalid: " + path.name)
        if FORBIDDEN_SOURCE.search(source):
            errors.append("predecessor runtime name remains: " + path.name)
    manifest = _json(root / ".codex-plugin" / "plugin.json")
    _check(
        isinstance(manifest, dict)
        and manifest.get("name") == "dev-flow-orchestrator",
        errors,
        "plugin identity changed",
    )
    _check(
        isinstance(manifest, dict)
        and isinstance(manifest.get("version"), str)
        and re.fullmatch(
            r"4\.0\.0\+codex\.[A-Za-z0-9.-]+",
            manifest["version"],
        )
        is not None,
        errors,
        "plugin version is not V4",
    )
    expected_profiles = {
        ("full", "single-repository"),
        ("full", "multi-repository"),
        ("lite", "single-repository"),
        ("lite", "multi-repository"),
    }
    _check(set(PROFILES) == expected_profiles, errors, "profile matrix mismatch")
    _check(
        len(
            {
                workflow_identity(workflow_id, topology)
                for workflow_id, topology in PROFILES
            }
        )
        == 4,
        errors,
        "profile workflow identities are not exact and distinct",
    )
    _check(
        set(FULL_GRAPH) == {
            "baseline",
            "impact",
            "route",
            "workspace",
            "planning",
            "plan-approval",
            "implement",
            "verify",
            "review",
            "finalize",
        },
        errors,
        "full graph mismatch",
    )
    _check(
        set(LITE_GRAPH) == {"implement", "verify"},
        errors,
        "lite graph mismatch",
    )
    _check(
        set(REPOSITORY_GRAPH)
        == {
            "repository-plan",
            "repository-dispatch",
            "repository-results",
            "repository-barrier",
            "repository-integration",
        },
        errors,
        "repository graph mismatch",
    )
    repository_plan = REPOSITORY_GRAPH["repository-plan"]
    _check(
        "owners" not in repository_plan.payload_types
        and repository_plan.required_authority == "task-revision+manager",
        errors,
        "repository owner is caller-selectable",
    )
    _check(
        FULL_GRAPH["review"].payload_types.get("review_fingerprint")
        == "sha256",
        errors,
        "full review does not bind an independent review fingerprint",
    )
    _check(
        all(
            "authority_id"
            not in tool["inputSchema"].get("properties", {})
            for tool in TOOLS
        ),
        errors,
        "public MCP surface accepts caller-supplied authority",
    )
    contracts = [
        PREFLIGHT_CONTRACT,
        REPOSITORY_CANCEL_CONTRACT,
        *FULL_GRAPH.values(),
        *LITE_GRAPH.values(),
        *REPOSITORY_GRAPH.values(),
    ]
    _check(
        all(
            contract.handler_id in NODE_FAMILY_CATALOG
            and callable(NODE_FAMILY_CATALOG[contract.handler_id].handler)
            and NODE_FAMILY_CATALOG[contract.handler_id].effect_port
            == contract.effect_port
            for contract in contracts
        ),
        errors,
        "node handler/effect-port catalog mismatch",
    )
    engine_source = (
        root / "src" / "dev_flow_orchestrator" / "engine.py"
    ).read_text(encoding="utf-8")
    _check(
        "contract.output_kind" not in engine_source,
        errors,
        "engine dispatches reducers through output_kind",
    )
    mcp_source = (
        root / "src" / "dev_flow_orchestrator" / "mcp.py"
    ).read_text(encoding="utf-8")
    _check(
        "_validate_tool_arguments(name, arguments)" in mcp_source,
        errors,
        "MCP does not enforce its current tool schema",
    )
    mcp = _json(root / ".mcp.json")
    servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    _check(
        isinstance(servers, dict) and set(servers) == {"dev-flow-macos"},
        errors,
        "MCP must declare one macOS server",
    )
    if isinstance(servers, dict) and "dev-flow-macos" in servers:
        server = servers["dev-flow-macos"]
        _check(server.get("enabled") is False, errors, "MCP must default disabled")
        _check(
            server.get("enabled_tools") == [tool["name"] for tool in TOOLS],
            errors,
            "MCP tool inventory mismatch",
        )
        _check(
            server.get("args", [])[-1:] == ["./scripts/dev_flow_mcp.py"],
            errors,
            "MCP does not launch the public greenfield adapter",
        )
    hooks = _json(root / "hooks" / "hooks.json")
    serialized = json.dumps(hooks, ensure_ascii=False)
    _check(
        "$PLUGIN_ROOT/hooks/dev_flow_hook.py" in serialized,
        errors,
        "Hook does not launch the public greenfield adapter",
    )
    hook_groups = (
        hooks.get("hooks")
        if isinstance(hooks, dict)
        else None
    )
    user_prompt_groups = (
        hook_groups.get("UserPromptSubmit")
        if isinstance(hook_groups, dict)
        else None
    )
    expected_hook_command = (
        '"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" '
        '"$PLUGIN_ROOT/hooks/dev_flow_hook.py"'
    )
    user_prompt_commands = [
        hook.get("command")
        for group in user_prompt_groups or []
        if isinstance(group, dict)
        for hook in group.get("hooks", [])
        if isinstance(hook, dict) and hook.get("type") == "command"
    ]
    _check(
        isinstance(user_prompt_groups, list)
        and len(user_prompt_groups) == 1
        and user_prompt_commands == [expected_hook_command],
        errors,
        "Hook must expose exactly one packaged UserPromptSubmit command",
    )
    hook_source = (
        root / "src" / "dev_flow_orchestrator" / "hook.py"
    ).read_text(encoding="utf-8")
    _check(
        'os.environ.get("PLUGIN_DATA")' in hook_source
        and 'os.environ.get("PLUGIN_DATA")' in mcp_source,
        errors,
        "Hook and MCP do not share the packaged PLUGIN_DATA contract",
    )
    popup_closure = validate_popup_source_closure(root)
    errors.extend(
        "removed popup source remains: {path} ({signature})".format(**item)
        for item in popup_closure["violations"]
    )
    return {
        "ok": not errors,
        "platform": "macOS-current-host",
        "profiles": len(PROFILES),
        "full_nodes": len(FULL_GRAPH),
        "lite_nodes": len(LITE_GRAPH),
        "repository_nodes": len(REPOSITORY_GRAPH),
        "popup_source_files": len(popup_closure["files"]),
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
    raise SystemExit(main())
