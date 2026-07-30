#!/usr/bin/env python3
"""Validate the plugin manifest, default hooks, skills, and package inventory."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence, Set
from urllib.parse import unquote


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^)]*['\"])?\)")
CODE_SPAN_RE = re.compile(r"`([^`\r\n]+)`")
PACKAGE_PREFIXES = (
    ".codex-plugin/",
    "hooks/",
    "scripts/",
    "skills/",
    "templates/",
    "tests/",
    "workflows/",
    ".github/",
)
EXCLUDED_TOP_LEVEL = {".git", ".codex", ".idea", "__pycache__"}
REQUIRED_PATHS = (
    ".gitattributes",
    ".gitignore",
    ".mcp.json",
    ".codex-plugin/plugin.json",
    ".github/workflows/cross-platform.yml",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
    "hooks/dev_flow_hook.cmd",
    "hooks/dev_flow_hook.py",
    "hooks/hooks.json",
    "scripts/__init__.py",
    "scripts/audit_runtime_imports.py",
    "scripts/candidate_identity.py",
    "scripts/dev_flow.py",
    "scripts/dev_flow_mcp.py",
    "scripts/dev_flow_mcp_launcher",
    "scripts/dev_flow_mcp_launcher.cmd",
    "scripts/dev_flow_python_launcher",
    "scripts/legacy_base_oracle.py",
    "scripts/release_ledger.py",
    "scripts/workflow_bundle_identity.py",
    "scripts/dev_flow_parts/core.py",
    "scripts/dev_flow_parts/workflow_registry.py",
    "scripts/dev_flow_parts/workflow_handlers.py",
    "scripts/dev_flow_parts/workflow_builtin_handlers.py",
    "scripts/dev_flow_parts/workflow_v3_handlers.py",
    "scripts/dev_flow_parts/workflow_v4_handlers.py",
    "scripts/dev_flow_parts/workflow_catalog.py",
    "scripts/dev_flow_parts/workflow_state.py",
    "scripts/dev_flow_parts/transition_engine.py",
    "scripts/dev_flow_parts/agent_protocol.py",
    "scripts/dev_flow_parts/node_telemetry.py",
    "scripts/dev_flow_parts/external_tools.py",
    "scripts/dev_flow_parts/external_write_bridge.py",
    "scripts/dev_flow_parts/repository_plan.py",
    "scripts/dev_flow_parts/orchestration_authority.py",
    "scripts/dev_flow_parts/orchestration_results.py",
    "scripts/dev_flow_parts/runtime_adapters.py",
    "scripts/dev_flow_parts/workflow_projection.py",
    "scripts/dev_flow_parts/workflow_transition_service.py",
    "scripts/dev_flow_parts/action_execution_journal.py",
    "scripts/dev_flow_parts/action_execution_store.py",
    "scripts/dev_flow_parts/workflow_action_service.py",
    "scripts/dev_flow_parts/workflow_action_transaction.py",
    "scripts/dev_flow_parts/workflow_action_reconciliation.py",
    "scripts/dev_flow_parts/workflow_action_recovery_cli.py",
    "scripts/dev_flow_parts/workflow_action_recovery_commands.py",
    "scripts/dev_flow_parts/orchestration_action_adapters.py",
    "scripts/dev_flow_parts/workflow_runtime.py",
    "scripts/dev_flow_parts/mutation.py",
    "scripts/dev_flow_parts/scope.py",
    "scripts/dev_flow_parts/manager_channel.py",
    "scripts/dev_flow_parts/process.py",
    "scripts/dev_flow_parts/orchestration_service.py",
    "scripts/dev_flow_parts/mcp_controller_service.py",
    "scripts/dev_flow_parts/git.py",
    "scripts/dev_flow_parts/commands.py",
    "scripts/dev_flow_parts/baseline.py",
    "scripts/dev_flow_parts/workspace.py",
    "scripts/dev_flow_parts/review.py",
    "scripts/dev_flow_parts/cli.py",
    "scripts/run_bundled_validators.py",
    "scripts/validate_package.py",
    "scripts/windows_native_validation.cmd",
    "scripts/windows_native_validation.py",
    "skills/analyze-change-impact/SKILL.md",
    "skills/analyze-change-impact/agents/openai.yaml",
    "skills/analyze-change-impact/assets/impact-report-template.md",
    "skills/analyze-change-impact/references/evidence-workflow.md",
    "skills/follow-dev-flow/SKILL.md",
    "skills/follow-dev-flow/agents/openai.yaml",
    "skills/follow-dev-flow/assets/direct-contract-template.md",
    "skills/follow-dev-flow/references/index-routing.md",
    "skills/follow-dev-flow/references/openspec-route.md",
    "skills/follow-dev-flow/references/recovery.md",
    "skills/follow-dev-flow/references/state-machine.md",
    "skills/follow-dev-flow/references/state-machine-common.md",
    "skills/follow-dev-flow/references/flow-lite.md",
    "skills/follow-dev-flow/references/flow-full.md",
    "skills/follow-dev-flow/references/gates/preflight.md",
    "skills/follow-dev-flow/references/gates/baseline-impact-route.md",
    "skills/follow-dev-flow/references/gates/workspace-plan.md",
    "skills/follow-dev-flow/references/gates/verification-review.md",
    "skills/review-dev-flow-change/SKILL.md",
    "skills/review-dev-flow-change/agents/openai.yaml",
    "skills/review-dev-flow-change/references/independent-review.md",
    "templates/marketplace-entry.json",
    "templates/personal-marketplace.example.json",
    "tests/test_packaging.py",
    "tests/test_candidate_identity.py",
    "tests/test_dev_flow_mcp.py",
    "tests/test_node_telemetry.py",
    "tests/test_protocol_size_current.py",
    "tests/fixtures/mcp/initialize.json",
    "tests/fixtures/mcp/tool-list.json",
    "tests/fixtures/mcp/successful-calls.json",
    "tests/fixtures/mcp/malformed.json",
    "tests/fixtures/mcp/unsupported-version.json",
    "tests/fixtures/mcp/disabled-tool.json",
    "tests/fixtures/mcp/disconnect.json",
    "tests/fixtures/mcp/lost-response.json",
    "tests/fixtures/mcp/cli-fallback.json",
    "tests/fixtures/protocol_sizes/baseline.json",
    "tests/fixtures/protocol_sizes/current.json",
    "tests/fixtures/protocol_sizes/representative_worker_summary.json",
    "tests/fixtures/telemetry/representative_workflows.json",
    "tests/fixtures/workflow_legacy/pristine_full_suite.json",
    "workflows/catalog.json",
    "workflows/activation.json",
    "workflows/release-ledger.json",
    "workflows/release-provenance/first-introduction.json",
    "workflows/release-provenance/reserved-v3-activation.json",
    "workflows/release-provenance/introduction-epochs/introduction-epoch-1.json",
    "workflows/runtime/commands.json",
    "workflows/runtime/guards.json",
    "workflows/runtime/reducers.json",
    "workflows/runtime/gates.json",
    "workflows/runtime/executors.json",
    "workflows/bundles/full-legacy-v2/workflow.json",
    "workflows/bundles/full-legacy-v2/schemas/contracts.json",
    "workflows/bundles/full-legacy-v2/schemas/node-input.json",
    "workflows/bundles/full-legacy-v2/schemas/node-result.json",
    "workflows/bundles/full-legacy-v2/playbooks/workflow.md",
    "workflows/bundles/lite-legacy-v2/workflow.json",
    "workflows/bundles/lite-legacy-v2/schemas/contracts.json",
    "workflows/bundles/lite-legacy-v2/schemas/node-input.json",
    "workflows/bundles/lite-legacy-v2/schemas/node-result.json",
    "workflows/bundles/lite-legacy-v2/playbooks/workflow.md",
    "workflows/bundles/full-v3/workflow.json",
    "workflows/bundles/full-v3/schemas/contracts.json",
    "workflows/bundles/full-v3/schemas/node-input.json",
    "workflows/bundles/full-v3/schemas/node-result.json",
    "workflows/bundles/full-v3/playbooks/workflow.md",
    "workflows/bundles/lite-v3/workflow.json",
    "workflows/bundles/lite-v3/schemas/contracts.json",
    "workflows/bundles/lite-v3/schemas/node-input.json",
    "workflows/bundles/lite-v3/schemas/node-result.json",
    "workflows/bundles/lite-v3/playbooks/workflow.md",
    "workflows/bundles/full-v4/workflow.json",
    "workflows/bundles/full-v4/schemas/contracts.json",
    "workflows/bundles/full-v4/schemas/node-input.json",
    "workflows/bundles/full-v4/schemas/node-result.json",
    "workflows/bundles/full-v4/playbooks/workflow.md",
    "workflows/bundles/lite-v4/workflow.json",
    "workflows/bundles/lite-v4/schemas/contracts.json",
    "workflows/bundles/lite-v4/schemas/node-input.json",
    "workflows/bundles/lite-v4/schemas/node-result.json",
    "workflows/bundles/lite-v4/playbooks/workflow.md",
)
ALLOWED_MANIFEST_KEYS = {
    "id",
    "name",
    "version",
    "description",
    "skills",
    "apps",
    "mcpServers",
    "interface",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
}
REQUIRED_INTERFACE_STRINGS = (
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
)


def _portable_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def package_inventory(plugin_root: Path) -> Set[str]:
    result: Set[str] = set()
    for path in plugin_root.rglob("*"):
        relative = path.relative_to(plugin_root)
        if not relative.parts:
            continue
        if relative.parts[0] in EXCLUDED_TOP_LEVEL or "__pycache__" in relative.parts:
            continue
        result.add(relative.as_posix())
    return result


def case_collision_errors(paths: Iterable[str]) -> list[str]:
    by_identity: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        by_identity[_portable_key(path)].append(path)
    errors: list[str] = []
    for variants in sorted(by_identity.values(), key=lambda item: item[0]):
        unique = sorted(set(variants))
        if len(unique) > 1:
            errors.append(
                "portable package path collision: " + ", ".join(unique)
            )
    return errors


def _exact_path_error(
    relative: str,
    inventory: Set[str],
    *,
    label: str,
) -> Optional[str]:
    normalized = PurePosixPath(relative).as_posix().rstrip("/")
    if normalized in inventory:
        return None
    aliases = sorted(
        path for path in inventory if _portable_key(path) == _portable_key(normalized)
    )
    if aliases:
        return (
            f"{label} uses non-portable case/normalization spelling "
            f"`{normalized}`; package contains {aliases}"
        )
    return f"{label} references missing package path `{normalized}`"


def _read_json_object(path: Path, errors: list[str], label: str) -> Optional[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing {label}: {path}")
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not readable UTF-8 JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def validate_identity_inventory(
    plugin_root: Path,
    inventory: Set[str],
) -> list[str]:
    """Prove identity-bearing catalog and handler paths ship in the package."""

    errors: list[str] = []
    covered = {
        "workflows/catalog.json",
        "workflows/activation.json",
        "workflows/release-ledger.json",
        "workflows/release-provenance/first-introduction.json",
        "workflows/release-provenance/reserved-v3-activation.json",
    }
    catalog = _read_json_object(
        plugin_root / "workflows" / "catalog.json",
        errors,
        "workflow catalog identity inventory",
    )
    if catalog is not None:
        bundles = catalog.get("bundles")
        if not isinstance(bundles, list):
            errors.append("workflow catalog identity inventory is invalid")
        else:
            for entry in bundles:
                if not isinstance(entry, dict):
                    errors.append(
                        "workflow catalog identity inventory entry is invalid"
                    )
                    continue
                root = entry.get("root")
                graph = entry.get("graph")
                files = entry.get("files")
                if (
                    not isinstance(root, str)
                    or not isinstance(graph, str)
                    or not isinstance(files, list)
                ):
                    errors.append(
                        "workflow catalog identity inventory paths are invalid"
                    )
                    continue
                covered.add(f"workflows/{root}/{graph}")
                for declaration in files:
                    if (
                        isinstance(declaration, dict)
                        and isinstance(declaration.get("path"), str)
                    ):
                        covered.add(
                            f"workflows/{root}/{declaration['path']}"
                        )
                    else:
                        errors.append(
                            "workflow catalog identity file declaration is invalid"
                        )
    for manifest_name in (
        "commands.json",
        "executors.json",
        "gates.json",
        "guards.json",
        "reducers.json",
    ):
        relative = f"workflows/runtime/{manifest_name}"
        covered.add(relative)
        manifest = _read_json_object(
            plugin_root / relative,
            errors,
            f"{manifest_name} handler identity inventory",
        )
        if manifest is None:
            continue
        file_sets = manifest.get("implementation_file_sets")
        if not isinstance(file_sets, dict):
            errors.append(
                f"{manifest_name} handler identity inventory is invalid"
            )
            continue
        for raw_file_set in file_sets.values():
            declarations = (
                raw_file_set.get("files")
                if isinstance(raw_file_set, dict)
                else raw_file_set
            )
            if not isinstance(declarations, list):
                errors.append(
                    f"{manifest_name} handler identity file set is invalid"
                )
                continue
            for declaration in declarations:
                if (
                    isinstance(declaration, dict)
                    and isinstance(declaration.get("path"), str)
                ):
                    covered.add(str(declaration["path"]))
                else:
                    errors.append(
                        f"{manifest_name} handler identity declaration is invalid"
                    )
    for relative in sorted(covered, key=lambda item: item.encode("utf-8")):
        error = _exact_path_error(
            relative,
            inventory,
            label="identity-covered package inventory",
        )
        if error:
            errors.append(error)
    return errors


def validate_manifest(
    manifest: Mapping[str, Any],
    inventory: Set[str],
    plugin_root: Path,
) -> list[str]:
    errors: list[str] = []
    unsupported = sorted(set(manifest) - ALLOWED_MANIFEST_KEYS)
    for field in unsupported:
        errors.append(f"plugin.json field `{field}` is not supported")
    if "hooks" in manifest:
        errors.append(
            "plugin.json must omit `hooks`; bundled hooks use default hooks/hooks.json discovery"
        )
    for field in ("name", "version", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            errors.append(f"plugin.json field `{field}` must be a non-empty string")
    version = manifest.get("version")
    if isinstance(version, str) and SEMVER_RE.fullmatch(version) is None:
        errors.append("plugin.json field `version` must be strict semver")
    name = manifest.get("name")
    if isinstance(name, str) and name != plugin_root.name:
        errors.append(
            f"plugin.json name `{name}` does not match plugin directory `{plugin_root.name}`"
        )
    author = manifest.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
        errors.append("plugin.json field `author.name` must be a non-empty string")
    elif not author["name"].strip():
        errors.append("plugin.json field `author.name` must be a non-empty string")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("plugin.json field `interface` must be an object")
    else:
        for field in REQUIRED_INTERFACE_STRINGS:
            value = interface.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"plugin.json field `interface.{field}` must be a non-empty string"
                )
        prompts = interface.get("defaultPrompt", interface.get("default_prompt"))
        if (
            not isinstance(prompts, list)
            or not prompts
            or not all(isinstance(item, str) and item.strip() for item in prompts)
        ):
            errors.append(
                "plugin.json interface must define a non-empty defaultPrompt string array"
            )
    for field in ("skills", "apps", "mcpServers"):
        value = manifest.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.startswith("./"):
            errors.append(f"plugin.json field `{field}` must be a ./-relative path")
            continue
        error = _exact_path_error(
            value[2:].rstrip("/"), inventory, label=f"plugin.json field `{field}`"
        )
        if error:
            errors.append(error)
    return errors


def validate_mcp_configuration(
    document: Mapping[str, Any],
    inventory: Set[str],
) -> list[str]:
    """Validate the explicit, disabled-by-default host MCP launch profiles."""

    errors: list[str] = []
    if set(document) != {"mcpServers"}:
        errors.append(
            ".mcp.json must use the Codex plugin companion root "
            "`mcpServers`"
        )
        return errors
    servers = document.get("mcpServers")
    if not isinstance(servers, dict):
        return [".mcp.json field `mcpServers` must be an object"]
    expected_server_ids = {"dev-flow-posix", "dev-flow-windows"}
    if set(servers) != expected_server_ids:
        return [
            ".mcp.json field `mcpServers` must define exactly "
            "`dev-flow-posix` and `dev-flow-windows`"
        ]
    allowed = {
        "command",
        "args",
        "cwd",
        "enabled",
        "required",
        "startup_timeout_sec",
        "tool_timeout_sec",
        "default_tools_approval_mode",
        "enabled_tools",
    }
    expected_tools = [
        "task-next",
        "node-description",
        "evidence-read",
        "action-preview",
        "action-apply",
        "worker-result",
    ]
    launch_contracts = {
        "dev-flow-posix": {
            "command": "/bin/sh",
            "args": [
                "./scripts/dev_flow_python_launcher",
                "./scripts/dev_flow_mcp.py",
            ],
            "paths": (
                "scripts/dev_flow_python_launcher",
                "scripts/dev_flow_mcp.py",
            ),
        },
        "dev-flow-windows": {
            "command": "cmd.exe",
            "args": [
                "/d",
                "/c",
                ".\\scripts\\dev_flow_mcp_launcher.cmd",
            ],
            "paths": ("scripts/dev_flow_mcp_launcher.cmd",),
        },
    }
    for server_id in sorted(expected_server_ids):
        server = servers.get(server_id)
        if not isinstance(server, dict):
            errors.append(
                f".mcp.json server `{server_id}` must be an object"
            )
            continue
        unknown = sorted(set(server) - allowed)
        if unknown:
            errors.append(
                f".mcp.json server `{server_id}` contains unsupported "
                "fields: " + ", ".join(unknown)
            )
        contract = launch_contracts[server_id]
        if server.get("command") != contract["command"]:
            errors.append(
                f".mcp.json server `{server_id}` command must be "
                f"`{contract['command']}`"
            )
        if server.get("args") != contract["args"]:
            errors.append(
                f".mcp.json server `{server_id}` args do not match the "
                "explicit host launcher contract"
            )
        for relative in contract["paths"]:
            error = _exact_path_error(
                str(relative),
                inventory,
                label=f".mcp.json server `{server_id}` launcher",
            )
            if error:
                errors.append(error)
        if server.get("cwd") != ".":
            errors.append(
                f".mcp.json server `{server_id}` cwd must be `.`"
            )
        if server.get("enabled") is not False:
            errors.append(
                f".mcp.json server `{server_id}` must default disabled; "
                "Codex MCP configuration has no OS-specific command field"
            )
        if server.get("required") is not False:
            errors.append(
                f".mcp.json server `{server_id}` required must be false so "
                "CLI recovery remains available"
            )
        if server.get("default_tools_approval_mode") != "writes":
            errors.append(
                f".mcp.json server `{server_id}` must prompt for write tools "
                "by default with `default_tools_approval_mode: writes`"
            )
        if server.get("enabled_tools") != expected_tools:
            errors.append(
                f".mcp.json server `{server_id}` enabled_tools differs from "
                "the versioned MCP surface"
            )
        for field, maximum in (
            ("startup_timeout_sec", 60),
            ("tool_timeout_sec", 300),
        ):
            value = server.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                or value > maximum
            ):
                errors.append(
                    f".mcp.json server `{server_id}` {field} must be an "
                    f"integer between 1 and {maximum}"
                )
    serialized = json.dumps(
        document, ensure_ascii=False, sort_keys=True
    ).casefold()
    for forbidden in (
        "manager_secret",
        "manager-proof",
        "bearer_token",
        "authorization",
    ):
        if forbidden in serialized:
            errors.append(
                ".mcp.json must not carry manager or bearer secret material"
            )
            break
    return errors


def _iter_hook_handlers(document: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if isinstance(handler, dict):
                    yield str(event), handler


def validate_default_hooks(
    plugin_root: Path,
    document: Mapping[str, Any],
    inventory: Set[str],
) -> list[str]:
    errors: list[str] = []
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        return ["hooks/hooks.json field `hooks` must be an object"]
    required_events = {
        "SessionStart",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "PreCompact",
        "PostCompact",
        "PreToolUse",
    }
    if set(hooks) != required_events:
        errors.append(
            "hooks/hooks.json must define exactly SessionStart, "
            "UserPromptSubmit, SubagentStart, SubagentStop, PreCompact, "
            "PostCompact, and PreToolUse"
        )
    pretool_groups = hooks.get("PreToolUse")
    if not isinstance(pretool_groups, list) or not pretool_groups:
        errors.append("hooks/hooks.json must define a PreToolUse handler group")
    else:
        for group in pretool_groups:
            if isinstance(group, dict) and group.get("matcher") != "^(Bash|apply_patch|Edit|Write)$":
                errors.append(
                    "PreToolUse must retain the canonical ^(Bash|apply_patch|Edit|Write)$ matcher"
                )
    shim_path = plugin_root / "hooks/dev_flow_hook.cmd"
    posix_launcher_path = (
        plugin_root / "scripts/dev_flow_python_launcher"
    )
    try:
        shim = shim_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"Windows hook shim is unreadable: {exc}")
        shim = ""
    if "dev_flow_hook.py" not in shim:
        errors.append("Windows hook shim must invoke hooks/dev_flow_hook.py")
    try:
        posix_launcher = posix_launcher_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"POSIX Python launcher is unreadable: {exc}")
        posix_launcher = ""
    if "(3, 9) <= sys.version_info[:2] < (3, 15)" not in posix_launcher:
        errors.append(
            "POSIX Python launcher must enforce Python 3.9 through 3.14"
        )
    handler_count = 0
    for event, handler in _iter_hook_handlers(document):
        if handler.get("type") != "command":
            errors.append(f"{event} contains a non-command hook handler")
            continue
        handler_count += 1
        command = handler.get("command")
        windows = handler.get("commandWindows")
        if (
            not isinstance(command, str)
            or "$PLUGIN_ROOT/scripts/dev_flow_python_launcher" not in command
            or "$PLUGIN_ROOT/hooks/dev_flow_hook.py" not in command
        ):
            errors.append(
                f"{event} command must use the shared POSIX Python launcher "
                "for $PLUGIN_ROOT/hooks/dev_flow_hook.py"
            )
        if (
            not isinstance(windows, str)
            or "%PLUGIN_ROOT%" not in windows
            or "hooks\\dev_flow_hook.cmd" not in windows
        ):
            errors.append(
                f"{event} commandWindows must target %PLUGIN_ROOT%\\hooks\\dev_flow_hook.cmd"
            )
    if handler_count == 0:
        errors.append("hooks/hooks.json contains no command handlers")
    for required in (
        "hooks/hooks.json",
        "hooks/dev_flow_hook.py",
        "hooks/dev_flow_hook.cmd",
        "scripts/dev_flow_python_launcher",
    ):
        error = _exact_path_error(required, inventory, label="default hook discovery")
        if error:
            errors.append(error)
    return errors


def _frontmatter_value(frontmatter: str, key: str) -> Optional[str]:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(?:['\"]([^'\"]+)['\"]|(.+?))\s*$",
        frontmatter,
    )
    if match is None:
        return None
    return (match.group(1) or match.group(2) or "").strip()


def validate_skills(plugin_root: Path, inventory: Set[str]) -> list[str]:
    errors: list[str] = []
    skills_root = plugin_root / "skills"
    if not skills_root.is_dir():
        return ["package is missing skills/"]
    skill_names: list[str] = []
    for skill_root in sorted(skills_root.iterdir(), key=lambda item: item.name):
        if not skill_root.is_dir() or skill_root.name.startswith("."):
            continue
        skill_names.append(skill_root.name)
        skill_md = skill_root / "SKILL.md"
        try:
            contents = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"skill `{skill_root.name}` SKILL.md is unreadable: {exc}")
            continue
        match = re.match(r"^---\n(.*?)\n---(?:\n|$)", contents, re.DOTALL)
        if match is None:
            errors.append(f"skill `{skill_root.name}` has invalid YAML frontmatter framing")
            continue
        declared_name = _frontmatter_value(match.group(1), "name")
        description = _frontmatter_value(match.group(1), "description")
        if declared_name != skill_root.name:
            errors.append(
                f"skill directory `{skill_root.name}` declares name `{declared_name}`"
            )
        if declared_name is None or SKILL_NAME_RE.fullmatch(declared_name) is None:
            errors.append(f"skill `{skill_root.name}` name must be portable hyphen-case")
        if not description:
            errors.append(f"skill `{skill_root.name}` description must be non-empty")
        if re.search(r"python3\b[^\n]*(?:dev_flow\.py|absolute-controller-path)", contents):
            errors.append(
                f"skill `{skill_root.name}` reconstructs the controller with hard-coded python3"
            )
        for line_number, line in enumerate(contents.splitlines(), 1):
            if line.rstrip().endswith("\\"):
                errors.append(
                    f"{skill_md.relative_to(plugin_root)}:{line_number}: "
                    "skill guidance contains a platform-specific line continuation"
                )
    if set(skill_names) != {
        "analyze-change-impact",
        "follow-dev-flow",
        "review-dev-flow-change",
    }:
        errors.append(f"unexpected shipped skill set: {skill_names}")
    agent_path = (
        skills_root / "follow-dev-flow" / "agents" / "openai.yaml"
    )
    try:
        agent_metadata = agent_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(
            "follow-dev-flow agent metadata is unreadable: "
            f"{exc}"
        )
    else:
        for false_dependency in (
            "dev-flow",
            "dev-flow-posix",
            "dev-flow-windows",
        ):
            if re.search(
                rf"(?m)^\s*value:\s*['\"]?{re.escape(false_dependency)}"
                r"['\"]?\s*$",
                agent_metadata,
            ):
                errors.append(
                    "follow-dev-flow must not declare mutually exclusive "
                    f"optional MCP profile `{false_dependency}` as a hard "
                    "skill dependency"
                )
    return errors


def _normalize_reference(
    source: Path,
    raw_target: str,
    plugin_root: Path,
) -> Optional[str]:
    target = unquote(raw_target.strip().strip("<>"))
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith(("#", "/", "\\")):
        return None
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    target_path = PurePosixPath(target.replace("\\", "/"))
    source_parent = PurePosixPath(source.relative_to(plugin_root).parent.as_posix())
    combined = source_parent.joinpath(target_path)
    parts: list[str] = []
    for part in combined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _inline_package_reference(value: str) -> Optional[str]:
    candidate = value.strip().strip(".,:;()[]{}")
    if not candidate:
        return None
    for prefix in ("<plugin-root>/", "<plugin-root>\\"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :]
            break
    candidate = candidate.replace("\\", "/")
    if any(token in candidate for token in ("*", " ...", "[--", "<business-repo>")):
        return None
    first = candidate.split(None, 1)[0]
    if first.startswith(PACKAGE_PREFIXES):
        return first.rstrip("/")
    if first in {
        "CONTRIBUTING.md",
        "README.md",
        "README.zh-CN.md",
        "INSTALL.md",
        "LICENSE",
    }:
        return first
    return None


def validate_document_references(
    plugin_root: Path,
    inventory: Set[str],
    documents: Iterable[Path],
) -> list[str]:
    errors: list[str] = []
    for document in documents:
        try:
            contents = document.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{document}: documentation is unreadable: {exc}")
            continue
        relative_source = document.relative_to(plugin_root)
        if "templates/project/AGENTS.md" in contents:
            errors.append(
                f"{relative_source}: stale reference to unshipped templates/project/AGENTS.md"
            )
        for match in MARKDOWN_LINK_RE.finditer(contents):
            reference = _normalize_reference(document, match.group(1), plugin_root)
            if reference is None:
                continue
            error = _exact_path_error(
                reference, inventory, label=f"{relative_source} Markdown link"
            )
            if error:
                errors.append(error)
        for match in CODE_SPAN_RE.finditer(contents):
            reference = _inline_package_reference(match.group(1))
            if reference is None:
                continue
            error = _exact_path_error(
                reference, inventory, label=f"{relative_source} inline path"
            )
            if error:
                errors.append(error)
    return errors


def _documentation_files(plugin_root: Path) -> list[Path]:
    result = [
        plugin_root / "CONTRIBUTING.md",
        plugin_root / "README.md",
        plugin_root / "README.zh-CN.md",
        plugin_root / "INSTALL.md",
    ]
    result.extend(sorted((plugin_root / "skills").glob("**/*.md")))
    return result


def _documentation_contract_errors(plugin_root: Path) -> list[str]:
    errors: list[str] = []
    required_token_groups = (
        ("Windows",),
        ("macOS",),
        ("Linux",),
        ("3.9",),
        ("3.14",),
        ("commandWindows",),
        ("recover-quarantine",),
        ("evidence contract version", "证据契约版本"),
        ("--require-available",),
        ("windows_native_validation.py",),
        ("canonical",),
        ("optional/OR",),
        ("Never enable both", "绝不能同时启用"),
        ("tools/list",),
        ("native-windows-compact-hook-lifecycle",),
    )
    for name in ("README.md", "README.zh-CN.md", "INSTALL.md"):
        try:
            contents = (plugin_root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        folded = contents.casefold()
        for tokens in required_token_groups:
            if not any(token.casefold() in folded for token in tokens):
                errors.append(
                    f"{name} does not document required platform token "
                    f"`{'|'.join(tokens)}`"
                )
    return errors


def validate_package(plugin_root: Path) -> list[str]:
    inventory = package_inventory(plugin_root)
    errors = case_collision_errors(inventory)
    for required in REQUIRED_PATHS:
        error = _exact_path_error(required, inventory, label="required package inventory")
        if error:
            errors.append(error)
    errors.extend(validate_identity_inventory(plugin_root, inventory))
    manifest_errors: list[str] = []
    manifest = _read_json_object(
        plugin_root / ".codex-plugin/plugin.json",
        manifest_errors,
        "plugin manifest",
    )
    errors.extend(manifest_errors)
    if manifest is not None:
        errors.extend(validate_manifest(manifest, inventory, plugin_root))
    mcp_errors: list[str] = []
    mcp_configuration = _read_json_object(
        plugin_root / ".mcp.json",
        mcp_errors,
        "MCP configuration",
    )
    errors.extend(mcp_errors)
    if mcp_configuration is not None:
        errors.extend(
            validate_mcp_configuration(mcp_configuration, inventory)
        )
    hook_errors: list[str] = []
    hooks = _read_json_object(
        plugin_root / "hooks/hooks.json",
        hook_errors,
        "default hook configuration",
    )
    errors.extend(hook_errors)
    if hooks is not None:
        errors.extend(validate_default_hooks(plugin_root, hooks, inventory))
    errors.extend(validate_skills(plugin_root, inventory))
    errors.extend(
        validate_document_references(
            plugin_root,
            inventory,
            _documentation_files(plugin_root),
        )
    )
    errors.extend(_documentation_contract_errors(plugin_root))
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the manifest independently of default hook discovery, then "
            "validate shipped skills, documentation references, and portable inventory."
        )
    )
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="plugin source root (defaults to this script's parent plugin)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    plugin_root = Path(args.plugin_root).expanduser().resolve()
    errors = validate_package(plugin_root)
    diagnostic = (
        f"os={platform.system()} python={platform.python_version()} "
        f"root={plugin_root}"
    )
    if errors:
        print(f"Package validation failed ({diagnostic}):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Package validation passed ({diagnostic})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
