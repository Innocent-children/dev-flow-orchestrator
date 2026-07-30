#!/usr/bin/env python3
"""Validate the single macOS V4 plugin package."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


EXPECTED_BUNDLES = {("full", 4), ("lite", 4)}
EXPECTED_PROFILES = {
    "full-single-repository",
    "full-multi-repository",
    "lite-single-repository",
}
EXPECTED_SUITES = {
    "v4-static-closure",
    "v4-core-runtime",
    "v4-effect-recovery",
    "v4-external-tools",
    "v4-multi-repository",
}
EXPECTED_TOOLS = [
    "task-next",
    "node-description",
    "evidence-read",
    "action-preview",
    "action-apply",
    "worker-result",
]
MANIFEST_KEYS = {
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
INTERFACE_KEYS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "websiteURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "brandColor",
    "composerIcon",
    "logo",
    "logoDark",
    "screenshots",
    "defaultPrompt",
    "default_prompt",
}
FORBIDDEN_IDENTITY = re.compile(
    "(?:[" + "Vv" + "]" + "3|V" + "2|" + "leg" + "acy)"
)
FORBIDDEN_TASK_PREDECESSOR = re.compile(
    "(?:task schema v"
    + "2|schema-v"
    + "2 tasks|a v"
    + "2 risk contract|get\\([\"']schema_version[\"'],\\s*1\\))"
)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
NONINSTALLABLE_VALIDATORS = {
    "scripts/audit_runtime_imports.py",
    "scripts/candidate_identity.py",
    "scripts/run_bundled_validators.py",
    "scripts/validate_package.py",
}


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _check(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def validate(root: Path) -> dict[str, object]:
    errors: list[str] = []
    manifest = _read_json(root / ".codex-plugin/plugin.json")
    _check(isinstance(manifest, dict), errors, "plugin manifest must be an object")
    if isinstance(manifest, dict):
        _check(
            not (set(manifest) - MANIFEST_KEYS),
            errors,
            "plugin manifest contains unsupported fields",
        )
        _check(
            manifest.get("name") == "dev-flow-orchestrator",
            errors,
            "plugin name must remain dev-flow-orchestrator",
        )
        _check(
            isinstance(manifest.get("version"), str)
            and re.fullmatch(
                r"4\.0\.0\+codex\.[A-Za-z0-9.-]+",
                str(manifest.get("version")),
            )
            is not None,
            errors,
            "plugin version must be 4.0.0+codex.<cachebuster>",
        )
        _check(manifest.get("skills") == "./skills/", errors, "skills path mismatch")
        _check(
            manifest.get("mcpServers") == "./.mcp.json",
            errors,
            "MCP path mismatch",
        )
        _check("hooks" not in manifest, errors, "manifest must use default Hook discovery")
        _check(
            isinstance(manifest.get("description"), str)
            and bool(manifest["description"].strip()),
            errors,
            "plugin description must be non-empty",
        )
        author = manifest.get("author")
        _check(
            isinstance(author, dict)
            and isinstance(author.get("name"), str)
            and bool(author["name"].strip()),
            errors,
            "plugin author.name must be non-empty",
        )
        interface = manifest.get("interface")
        _check(
            isinstance(interface, dict),
            errors,
            "plugin interface must be an object",
        )
        if isinstance(interface, dict):
            _check(
                not (set(interface) - INTERFACE_KEYS),
                errors,
                "plugin interface contains unsupported fields",
            )
            for field in (
                "displayName",
                "shortDescription",
                "longDescription",
                "developerName",
                "category",
            ):
                _check(
                    isinstance(interface.get(field), str)
                    and bool(interface[field].strip()),
                    errors,
                    f"plugin interface.{field} must be non-empty",
                )
            _check(
                isinstance(interface.get("capabilities"), list)
                and all(
                    isinstance(value, str) and bool(value.strip())
                    for value in interface.get("capabilities", [])
                ),
                errors,
                "plugin interface.capabilities must be an array of strings",
            )
            _check(
                "defaultPrompt" in interface or "default_prompt" in interface,
                errors,
                "plugin interface requires a default prompt",
            )

    catalog = _read_json(root / "workflows/catalog.json")
    bundles = catalog.get("bundles") if isinstance(catalog, dict) else None
    bundle_keys = {
        (entry.get("workflow_id"), entry.get("workflow_version"))
        for entry in bundles or []
        if isinstance(entry, dict)
    }
    _check(bundle_keys == EXPECTED_BUNDLES, errors, "catalog must contain only full@4 and lite@4")
    _check(len(bundles or []) == 2, errors, "catalog must contain exactly two bundles")

    activation = _read_json(root / "workflows/activation.json")
    profiles = activation.get("profiles") if isinstance(activation, dict) else None
    profile_ids = {
        f"{entry.get('workflow_id')}-{entry.get('execution_profile')}"
        for entry in profiles or []
        if isinstance(entry, dict)
    }
    _check(profile_ids == EXPECTED_PROFILES, errors, "activation profile set mismatch")
    _check(len(profiles or []) == 3, errors, "activation must contain exactly three profiles")
    selected_suites = {
        suite
        for entry in profiles or []
        if isinstance(entry, dict)
        for suite in entry.get("required_suites", [])
    }
    _check(selected_suites == EXPECTED_SUITES, errors, "activation suite set mismatch")

    mcp = _read_json(root / ".mcp.json")
    servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    _check(
        isinstance(servers, dict) and set(servers) == {"dev-flow-macos"},
        errors,
        "MCP configuration must contain one macOS profile",
    )
    if isinstance(servers, dict) and "dev-flow-macos" in servers:
        server = servers["dev-flow-macos"]
        _check(server.get("enabled") is False, errors, "MCP profile must default disabled")
        _check(server.get("command") == "/bin/sh", errors, "MCP launcher command mismatch")
        _check(server.get("enabled_tools") == EXPECTED_TOOLS, errors, "MCP tool set mismatch")

    hook_config = _read_json(root / "hooks/hooks.json")
    serialized_hooks = json.dumps(hook_config, ensure_ascii=False)
    unsupported_hook_key = "command" + "Win" + "dows"
    _check(
        unsupported_hook_key not in serialized_hooks,
        errors,
        "Hook contains an unsupported launch entry",
    )
    _check(
        "$PLUGIN_ROOT/scripts/dev_flow_python_launcher" in serialized_hooks
        and "$PLUGIN_ROOT/hooks/dev_flow_hook.py" in serialized_hooks,
        errors,
        "Hook commands must target packaged V4 handler",
    )
    pre_tool = hook_config.get("hooks", {}).get("PreToolUse", [])
    _check(
        bool(pre_tool) and pre_tool[0].get("matcher") == "^(Bash|apply_patch|Edit|Write)$",
        errors,
        "canonical Bash Hook matcher is missing",
    )

    required = [
        "README.md",
        "README.zh-CN.md",
        "INSTALL.md",
        "CONTRIBUTING.md",
        ".mcp.json",
        "hooks/hooks.json",
        "hooks/dev_flow_hook.py",
        "scripts/dev_flow.py",
        "scripts/dev_flow_mcp.py",
        "scripts/dev_flow_python_launcher",
        "skills/analyze-change-impact/SKILL.md",
        "skills/follow-dev-flow/SKILL.md",
        "skills/review-dev-flow-change/SKILL.md",
        "templates/marketplace-entry.json",
        "templates/personal-marketplace.example.json",
        "workflows/bundles/full-v4/workflow.json",
        "workflows/bundles/lite-v4/workflow.json",
    ]
    for relative in required:
        path = root / relative
        _check(path.is_file() and not path.is_symlink(), errors, f"missing regular file: {relative}")

    referenced: set[str] = set(required)
    if isinstance(bundles, list):
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            root_value = bundle.get("root")
            graph_value = bundle.get("graph")
            if isinstance(root_value, str) and isinstance(graph_value, str):
                referenced.add(f"workflows/{root_value}/{graph_value}")
            for entry in bundle.get("files", []):
                if (
                    isinstance(entry, dict)
                    and isinstance(root_value, str)
                    and isinstance(entry.get("path"), str)
                ):
                    referenced.add(
                        f"workflows/{root_value}/{entry['path']}"
                    )
    for relative in sorted(referenced):
        path = root / relative
        _check(
            path.is_file() and not path.is_symlink(),
            errors,
            f"unresolved package reference: {relative}",
        )

    reference_documents = [
        root / "README.md",
        root / "README.zh-CN.md",
        root / "INSTALL.md",
        root / "CONTRIBUTING.md",
        *(root / relative / "SKILL.md" for relative in (
            Path("skills/analyze-change-impact"),
            Path("skills/follow-dev-flow"),
            Path("skills/review-dev-flow-change"),
        )),
    ]
    for document in reference_documents:
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).split("#", 1)[0]
            if (
                not target
                or "://" in target
                or target.startswith(("mailto:", "#", "/"))
            ):
                continue
            resolved = (document.parent / target).resolve()
            _check(
                resolved.is_relative_to(root)
                and resolved.is_file()
                and not resolved.is_symlink(),
                errors,
                "unresolved local documentation reference: "
                + document.relative_to(root).as_posix()
                + " -> "
                + target,
            )

    portable_names: dict[str, str] = {}
    for package_root in (
        ".codex-plugin",
        "hooks",
        "scripts",
        "skills",
        "templates",
        "workflows",
    ):
        for path in sorted((root / package_root).rglob("*")):
            if not path.is_file() or path.suffix == ".pyc":
                continue
            relative = path.relative_to(root).as_posix()
            folded = relative.casefold()
            previous = portable_names.setdefault(folded, relative)
            _check(
                previous == relative,
                errors,
                f"case-ambiguous package paths: {previous}, {relative}",
            )

    scan_roots = [
        root / ".codex-plugin",
        root / "hooks",
        root / "scripts",
        root / "skills",
        root / "templates",
        root / "workflows",
        root / "README.md",
        root / "README.zh-CN.md",
        root / "INSTALL.md",
        root / "CONTRIBUTING.md",
    ]
    for candidate in scan_roots:
        paths = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
        for path in paths:
            if path.is_symlink():
                errors.append(f"symlink is not packageable: {path.relative_to(root)}")
                continue
            if not path.is_file() or path.suffix == ".pyc":
                continue
            if path.relative_to(root).as_posix() in NONINSTALLABLE_VALIDATORS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            if FORBIDDEN_IDENTITY.search(text):
                errors.append(f"predecessor identity in {path.relative_to(root).as_posix()}")
            if FORBIDDEN_TASK_PREDECESSOR.search(text):
                errors.append(
                    "predecessor task-schema compatibility in "
                    + path.relative_to(root).as_posix()
                )

    marketplace = _read_json(root / "templates/personal-marketplace.example.json")
    entries = marketplace.get("plugins") if isinstance(marketplace, dict) else None
    _check(
        isinstance(entries, list)
        and len(entries) == 1
        and entries[0].get("name") == "dev-flow-orchestrator",
        errors,
        "personal marketplace must contain one existing plugin identity",
    )
    return {
        "schema": "dev-flow-v4-package-validation/v1",
        "ok": not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = validate(args.root.resolve())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
