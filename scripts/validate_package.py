#!/usr/bin/env python3
"""Validate the one macOS V5 plugin package."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator import workflows as workflows_loader  # noqa: E402
from dev_flow_orchestrator.engine import NODE_FAMILY_CATALOG  # noqa: E402
from dev_flow_orchestrator.product import WORKFLOW_IDS  # noqa: E402
from dev_flow_orchestrator.workflow import (  # noqa: E402
    canonical_json_bytes,
    validate_definition_document,
)


PUBLIC_BOOTSTRAPS = (
    "scripts/dev_flow.py",
    "hooks/dev_flow_hook.py",
)
REQUIRED = (
    ".codex-plugin/plugin.json",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README_CN.md",
    "hooks/dev_flow_hook.py",
    "hooks/hooks.json",
    "pyproject.toml",
    "scripts/dev_flow.py",
    "scripts/dev_flow_python_launcher",
    "scripts/validate_package.py",
    "skills/analyze-change-impact/SKILL.md",
    "skills/analyze-change-impact/agents/openai.yaml",
    "skills/follow-dev-flow/SKILL.md",
    "skills/follow-dev-flow/agents/openai.yaml",
    "skills/review-dev-flow-change/SKILL.md",
    "skills/review-dev-flow-change/agents/openai.yaml",
    "src/dev_flow_orchestrator/__init__.py",
    "src/dev_flow_orchestrator/cli.py",
    "src/dev_flow_orchestrator/controller.py",
    "src/dev_flow_orchestrator/engine.py",
    "src/dev_flow_orchestrator/filesystem.py",
    "src/dev_flow_orchestrator/git_client.py",
    "src/dev_flow_orchestrator/hook.py",
    "src/dev_flow_orchestrator/model.py",
    "src/dev_flow_orchestrator/product.py",
    "src/dev_flow_orchestrator/store.py",
    "src/dev_flow_orchestrator/workflow.py",
    "src/dev_flow_orchestrator/workflows.py",
    "src/dev_flow_orchestrator/yaml_subset.py",
    "templates/marketplace-entry.json",
    "templates/personal-marketplace.example.json",
    "workflows/lite.yaml",
)
FORBIDDEN_PATHS = (
    ".mcp.json",
    "src/dev_flow_orchestrator/authority.py",
    "src/dev_flow_orchestrator/journal.py",
    "src/dev_flow_orchestrator/repository_kernel.py",
    "src/dev_flow_orchestrator/mcp.py",
    "scripts/dev_flow_mcp.py",
    "scripts/dev_flow_parts",
    "scripts/validate_greenfield_architecture.py",
    "scripts/candidate_identity.py",
    "workflows/bundles",
    "workflows/runtime",
    "workflows/provenance",
    "workflows/release-provenance",
)
FORBIDDEN_SOURCE = re.compile(
    r"dev_flow_parts|workflow_bundle_identity|CLI_FALLBACK_SCHEMA|"
    r"\b(?:V2|V3|V4|legacy|greenfield)\b",
    re.IGNORECASE,
)
PURE_MODULES = (
    "model",
    "product",
    "workflow",
    "engine",
)
# Infrastructure modules that pure domain modules must never import.
FORBIDDEN_IMPORTS = (
    "os",
    "subprocess",
    "fcntl",
    "tempfile",
    "controller",
    "store",
    "git_client",
    "filesystem",
    "hook",
    "cli",
    "workflows",
    "yaml_subset",
)
PUBLIC_TEXT = (
    "README.md",
    "README_CN.md",
    "INSTALL.md",
    "ARCHITECTURE.md",
    "skills/analyze-change-impact/SKILL.md",
    "skills/follow-dev-flow/SKILL.md",
    "skills/review-dev-flow-change/SKILL.md",
)
MAIN_SKILL_AGENT = "skills/follow-dev-flow/agents/openai.yaml"
STALE_MAIN_AGENT_GUIDANCE = re.compile(
    r"\bV4\b|\bmulti[- ]repository\b|单仓库或多仓库|多仓库",
    re.IGNORECASE,
)


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _check(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _validation_failure(message: str) -> dict:
    return {
        "ok": False,
        "platform": "macOS-current-host",
        "builtin_workflows": [],
        "workflow_identities": [],
        "errors": [message],
    }


def _validate_foreign_candidate(root: Path) -> dict:
    validator = root / "scripts" / "validate_package.py"
    if not validator.is_file():
        return _validation_failure("missing scripts/validate_package.py")
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(validator)],
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return _validation_failure(
            "candidate package validator could not start: {}".format(exc)
        )
    try:
        result = json.loads(completed.stdout)
    except (TypeError, ValueError):
        detail = completed.stderr.strip() or completed.stdout.strip()
        return _validation_failure(
            "candidate package validator returned invalid JSON: {}".format(
                detail[:1024]
            )
        )
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("ok"), bool)
        or not isinstance(result.get("errors"), list)
        or not all(isinstance(item, str) for item in result["errors"])
    ):
        return _validation_failure(
            "candidate package validator returned an invalid result"
        )
    expected_returncode = 0 if result["ok"] else 1
    if completed.returncode != expected_returncode:
        return _validation_failure(
            "candidate package validator result disagrees with its exit status"
        )
    return result


def _quoted_yaml_string(document: str, key: str) -> Optional[str]:
    match = re.search(
        r'^  {}:\s*("(?:[^"\\]|\\.)*")\s*$'.format(re.escape(key)),
        document,
        re.MULTILINE,
    )
    if match is None:
        return None
    try:
        value = json.loads(match.group(1))
    except ValueError:
        return None
    return value if isinstance(value, str) else None


def _is_single_repository_guidance(value: str) -> bool:
    return (
        "单仓库" in value
        or "单个 Git 仓库" in value
        or re.search(r"\bsingle[- ]repository\b", value, re.IGNORECASE)
        is not None
    )


def _validate_main_skill_agent(root: Path, errors: list[str]) -> None:
    path = root / MAIN_SKILL_AGENT
    if not path.is_file():
        return
    document = path.read_text(encoding="utf-8")
    short_description = _quoted_yaml_string(document, "short_description")
    default_prompt = _quoted_yaml_string(document, "default_prompt")
    guidance = " ".join(
        value
        for value in (short_description, default_prompt)
        if value is not None
    )
    _check(
        short_description is not None
        and 25 <= len(short_description) <= 64
        and "V5" in guidance
        and _is_single_repository_guidance(guidance),
        errors,
        "follow-dev-flow agent metadata is not V5 single-repository guidance",
    )
    _check(
        default_prompt is not None and "$follow-dev-flow" in default_prompt,
        errors,
        "follow-dev-flow default_prompt does not invoke $follow-dev-flow",
    )
    _check(
        STALE_MAIN_AGENT_GUIDANCE.search(guidance) is None,
        errors,
        "follow-dev-flow agent metadata contains stale V4 or multi-repository guidance",
    )


def _validate_imports(module: Path, errors: list[str]) -> None:
    source = module.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(module))
    except SyntaxError:
        errors.append("runtime syntax invalid: " + module.name)
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    errors.append(
                        "{} imports infrastructure module {}".format(
                            module.name, alias.name
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module in FORBIDDEN_IMPORTS:
                errors.append(
                    "{} imports infrastructure module {}".format(
                        module.name, node.module
                    )
                )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                errors.append("{} executes source".format(module.name))


def _hook_locator_smoke(root: Path, errors: list[str]) -> None:
    launcher = root / "scripts" / "dev_flow_python_launcher"
    hook = root / "hooks" / "dev_flow_hook.py"
    if not launcher.is_file() or not hook.is_file():
        return
    with tempfile.TemporaryDirectory(prefix="dev flow package ") as temporary:
        plugin_data = Path(temporary) / "plugin data"
        legacy = plugin_data / "tasks" / "legacy" / "state.json"
        legacy.parent.mkdir(parents=True)
        legacy_payload = '{"schema_version":4}\n'
        legacy.write_text(legacy_payload, encoding="utf-8")
        payload = json.dumps(
            {"hook_event_name": "SessionStart", "cwd": str(root)}
        )
        environment = {
            **os.environ,
            "PLUGIN_DATA": str(plugin_data),
            "DEV_FLOW_PYTHON": sys.executable,
        }
        try:
            completed = subprocess.run(
                [str(launcher), str(hook)],
                input=payload,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
        except OSError as exc:
            errors.append("Hook launcher smoke could not start: {}".format(exc))
            return
        if completed.returncode != 0:
            errors.append("Hook launcher smoke failed: " + completed.stderr[:1024])
            return
        try:
            output = json.loads(completed.stdout)
            context = output["hookSpecificOutput"]["additionalContext"]
            locator = context.rsplit(": ", 1)[1]
            tokens = shlex.split(locator)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            errors.append("Hook locator smoke returned invalid context: {}".format(exc))
            return
        expected_prefix = [str(launcher), str(root / "scripts" / "dev_flow.py")]
        _check(tokens[:2] == expected_prefix, errors, "Hook locator bypasses launcher")
        _check(
            tokens[2:] == ["--data-dir", str((plugin_data / "v5").resolve())],
            errors,
            "Hook locator does not isolate V5 plugin data",
        )
        shell = subprocess.run(
            ["/bin/sh", "-c", locator + " --help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=environment,
        )
        _check(shell.returncode == 0, errors, "Hook locator is not shell executable")
        _check(
            legacy.read_text(encoding="utf-8") == legacy_payload,
            errors,
            "V5 Hook modified or loaded the retained V4 data fixture",
        )


def _validate_current_candidate(root: Path) -> dict:
    errors: list[str] = []
    for relative in REQUIRED:
        _check((root / relative).is_file(), errors, "missing " + relative)
    for relative in FORBIDDEN_PATHS:
        _check(
            not (root / relative).exists(),
            errors,
            "predecessor path remains: " + relative,
        )
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
            r"5\.0\.0\+codex\.[A-Za-z0-9.-]+",
            manifest["version"],
        )
        is not None,
        errors,
        "plugin version is not V5",
    )
    _check(
        isinstance(manifest, dict) and "mcpServers" not in manifest,
        errors,
        "plugin manifest still declares MCP servers",
    )
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version_match = re.search(
        r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE
    )
    _check(
        version_match is not None
        and isinstance(manifest, dict)
        and version_match.group(1) == manifest.get("version"),
        errors,
        "manifest and pyproject versions differ",
    )
    launcher = root / "scripts" / "dev_flow_python_launcher"
    _check(
        launcher.is_file()
        and bool(launcher.stat().st_mode & stat.S_IXUSR),
        errors,
        "scripts/dev_flow_python_launcher is not executable",
    )
    for relative in PUBLIC_BOOTSTRAPS:
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
    runtime_root = root / "src" / "dev_flow_orchestrator"
    for path in sorted(runtime_root.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        _check(
            FORBIDDEN_SOURCE.search(source) is None,
            errors,
            "predecessor runtime name remains: " + path.name,
        )
    for name in PURE_MODULES:
        _validate_imports(runtime_root / "{}.py".format(name), errors)
    _check(
        workflows_loader.list_builtin_ids() == WORKFLOW_IDS,
        errors,
        "workflow registry mismatch with product.WORKFLOW_IDS",
    )
    definitions = []
    for selector in workflows_loader.list_builtin_ids():
        try:
            definition = workflows_loader.load_definition(selector)
        except Exception as exc:  # noqa: BLE001 - validator reports everything
            errors.append("built-in workflow {!r} failed to load: {}".format(
                selector, exc
            ))
            continue
        definitions.append(definition)
        document = definition.document
        try:
            canonical_json_bytes(document)
        except Exception as exc:  # noqa: BLE001
            errors.append("built-in workflow {!r} is not canonicalizable".format(
                selector
            ))
        if definition.workflow_id != selector:
            errors.append("built-in workflow {!r} declares id {!r}".format(
                selector, definition.workflow_id
            ))
    _check(
        len({definition.identity for definition in definitions})
        == len(definitions),
        errors,
        "built-in workflow identities are not distinct",
    )
    for definition in definitions:
        for node_id, contract in definition.nodes.items():
            if contract.handler_id == "":
                continue  # terminal node: no action, no handler
            family = NODE_FAMILY_CATALOG.get(contract.handler_id)
            _check(
                family is not None
                and callable(family.handler)
                and family.effect_port == contract.effect_port,
                errors,
                "node {} handler/effect-port catalog mismatch".format(node_id),
            )
    hooks = _json(root / "hooks" / "hooks.json")
    serialized = json.dumps(hooks, ensure_ascii=False)
    _check(
        "$PLUGIN_ROOT/scripts/dev_flow_python_launcher" in serialized
        and "$PLUGIN_ROOT/hooks/dev_flow_hook.py" in serialized,
        errors,
        "Hook does not launch the packaged adapter",
    )
    hook_groups = hooks.get("hooks") if isinstance(hooks, dict) else None
    _check(
        isinstance(hook_groups, dict)
        and set(hook_groups) == {"SessionStart", "UserPromptSubmit", "PreToolUse"},
        errors,
        "Hook must register exactly SessionStart, UserPromptSubmit and PreToolUse",
    )
    expected_hook_command = (
        '"$PLUGIN_ROOT/scripts/dev_flow_python_launcher" '
        '"$PLUGIN_ROOT/hooks/dev_flow_hook.py"'
    )
    if isinstance(hook_groups, dict):
        for event, groups in hook_groups.items():
            if not isinstance(groups, list):
                errors.append("Hook event {!r} must contain a list".format(event))
                continue
            for group in groups:
                hook_entries = group.get("hooks") if isinstance(group, dict) else None
                if not isinstance(hook_entries, list) or not hook_entries:
                    errors.append("Hook event {!r} has no command".format(event))
                    continue
                for entry in hook_entries:
                    _check(
                        isinstance(entry, dict)
                        and entry.get("type") == "command"
                        and entry.get("command") == expected_hook_command,
                        errors,
                        "Hook event {!r} bypasses the packaged launcher".format(event),
                    )
        pre_tool_groups = hook_groups.get("PreToolUse")
        matcher = (
            pre_tool_groups[0].get("matcher")
            if isinstance(pre_tool_groups, list)
            and pre_tool_groups
            and isinstance(pre_tool_groups[0], dict)
            else ""
        )
        _check(
            isinstance(matcher, str)
            and "Bash" in matcher
            and "apply_patch" in matcher,
            errors,
            "PreToolUse matcher must cover Bash and apply_patch",
        )
    hook_source = (
        runtime_root / "hook.py"
    ).read_text(encoding="utf-8")
    _check(
        'os.environ.get("PLUGIN_DATA")' in hook_source,
        errors,
        "Hook does not honor the packaged PLUGIN_DATA contract",
    )
    marketplace_entry = _json(root / "templates" / "marketplace-entry.json")
    marketplace = _json(
        root / "templates" / "personal-marketplace.example.json"
    )
    plugins = marketplace.get("plugins") if isinstance(marketplace, dict) else None
    _check(
        isinstance(marketplace_entry, dict)
        and marketplace_entry.get("name") == "dev-flow-orchestrator"
        and marketplace_entry.get("source")
        == {"source": "local", "path": "./plugins/dev-flow-orchestrator"}
        and marketplace_entry.get("policy")
        == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        errors,
        "marketplace entry identity, source or policy is invalid",
    )
    _check(
        isinstance(plugins, list)
        and plugins == [marketplace_entry],
        errors,
        "personal marketplace template must contain the canonical entry once",
    )
    stale_selector = re.compile(r"\b(?:lite|full)@4\b")
    for relative in PUBLIC_TEXT:
        path = root / relative
        if path.is_file():
            _check(
                stale_selector.search(path.read_text(encoding="utf-8")) is None,
                errors,
                "stale public workflow selector remains: " + relative,
            )
    _validate_main_skill_agent(root, errors)
    _hook_locator_smoke(root, errors)
    return {
        "ok": not errors,
        "platform": "macOS-current-host",
        "builtin_workflows": list(workflows_loader.list_builtin_ids()),
        "workflow_identities": [
            definition.identity[:12] for definition in definitions
        ],
        "errors": errors,
    }


def validate(root: Path = ROOT) -> dict:
    root = root.resolve()
    if root != ROOT.resolve():
        return _validate_foreign_candidate(root)
    return _validate_current_candidate(root)


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
