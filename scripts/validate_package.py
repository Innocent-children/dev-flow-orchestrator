#!/usr/bin/env python3
"""Validate the complete cross-platform plugin candidate from its own root."""

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
from typing import Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dev_flow_orchestrator import workflows as workflows_loader  # noqa: E402
from dev_flow_orchestrator.product import (  # noqa: E402
    AGENT_PROTOCOL_SCHEMA,
    ARTIFACT_SCHEMA,
    DELIVERY_CONTRACT_SCHEMA,
    DELIVERY_DOSSIER_SCHEMA,
    DRIVER_RESULT_SCHEMA,
    ASSURANCE_POLICY_SCHEMA,
    ASSURANCE_PROFILES,
    MAX_ACTION_PAYLOAD_BYTES,
    MAX_ASSURANCE_OBLIGATIONS,
    MAX_EVIDENCE_ITEMS,
    MAX_IMPACT_ENTRIES,
    MAX_INDEX_COMMAND_OUTPUT_BYTES,
    MAX_INDEX_STAGE_ENTRIES,
    MAX_OWNERSHIP_CLAIMS,
    IMPACT_REPORT_SCHEMA,
    MAX_REPOSITORY_COUNT,
    MAX_REVIEW_FINDINGS,
    MAX_SNAPSHOT_PATHS,
    MAX_TASK_CHANGE_MANIFEST_ENTRIES,
    MAX_TEXT_FIELD_BYTES,
    MAX_WORKFLOW_ACTIONS,
    MIN_REPOSITORY_COUNT,
    OPENSPEC_TASKS_NORMALIZER,
    PLUGIN_DATA_NAMESPACE,
    PRODUCT_VERSION,
    RECORD_SCHEMA,
    REPOSITORY_SET_SNAPSHOT_SCHEMA,
    REPOSITORY_TOPOLOGY_CAPABILITIES,
    REPOSITORY_TOPOLOGY_SCHEMA,
    VERIFICATION_COVERAGE_SCHEMA,
    WORKFLOW_IDS,
    WORKFLOW_SCHEMA,
    product_schema,
)
from dev_flow_orchestrator.workflow import (  # noqa: E402
    ASSURANCE_HANDLER_IDS,
    canonical_json_bytes,
    workflow_identity,
)


PUBLIC_BOOTSTRAPS = (
    "scripts/dev_flow.py",
    "hooks/dev_flow_hook.py",
)
REQUIRED_STATIC = (
    ".codex-plugin/plugin.json",
    "ARCHITECTURE.md",
    "ARCHITECTURE_CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING_CN.md",
    "INSTALL.md",
    "INSTALL_CN.md",
    "LICENSE",
    "README.md",
    "README_CN.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "hooks/dev_flow_hook.py",
    "hooks/hooks.json",
    "scripts/dev_flow.py",
    "scripts/dev_flow_python_launcher",
    "scripts/dev_flow_python_launcher.cmd",
    "scripts/install.sh",
    "scripts/install.ps1",
    "scripts/uninstall.sh",
    "scripts/uninstall.ps1",
    "scripts/validate_installed_stage1.py",
    "scripts/validate_package.py",
    "docs/assets/demo.gif",
    "docs/assets/generate_demo.py",
    "docs/PROMOTION.md",
    "skills/analyze-change-impact/SKILL.md",
    "skills/analyze-change-impact/agents/openai.yaml",
    "skills/follow-dev-flow/SKILL.md",
    "skills/follow-dev-flow/agents/openai.yaml",
    "skills/review-dev-flow-change/SKILL.md",
    "skills/review-dev-flow-change/agents/openai.yaml",
    "src/dev_flow_orchestrator/__init__.py",
    "src/dev_flow_orchestrator/cli.py",
    "src/dev_flow_orchestrator/capsule.py",
    "src/dev_flow_orchestrator/controller.py",
    "src/dev_flow_orchestrator/delivery.py",
    "src/dev_flow_orchestrator/engine.py",
    "src/dev_flow_orchestrator/filesystem.py",
    "src/dev_flow_orchestrator/git_client.py",
    "src/dev_flow_orchestrator/hook.py",
    "src/dev_flow_orchestrator/model.py",
    "src/dev_flow_orchestrator/product.py",
    "src/dev_flow_orchestrator/assurance.py",
    "src/dev_flow_orchestrator/review.py",
    "src/dev_flow_orchestrator/snapshot.py",
    "src/dev_flow_orchestrator/store.py",
    "src/dev_flow_orchestrator/web.py",
    "src/dev_flow_orchestrator/web_views.py",
    "src/dev_flow_orchestrator/web_assets/index.html",
    "src/dev_flow_orchestrator/web_assets/app.js",
    "src/dev_flow_orchestrator/web_assets/styles.css",
    "src/dev_flow_orchestrator/workflow.py",
    "src/dev_flow_orchestrator/workflows.py",
    "src/dev_flow_orchestrator/yaml_subset.py",
    "templates/marketplace-entry.json",
    "templates/personal-marketplace.example.json",
    "tests/test_install_script.py",
    "tests/test_windows_product_support.py",
    "tests/test_windows_lifecycle.py",
    "tests/test_uninstall_script.py",
    "tests/test_read_only_inspection.py",
    "tests/test_web_read_models.py",
    "tests/test_web_server.py",
    "tests/test_web_ui_product_identity.py",
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
    r"greenfield",
    re.IGNORECASE,
)
PURE_MODULES = (
    "assurance",
    "capsule",
    "delivery",
    "model",
    "product",
    "snapshot",
    "review",
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
PURE_IMPORT_ALLOWLIST = {
    # Model validates canonical absolute paths lexically; it performs no I/O.
    "model.py": {"os"},
    # Snapshot validation performs lexical path checks only; it does no I/O.
    "snapshot.py": {"os"},
}
PURE_ATTRIBUTE_ALLOWLIST = {
    "model.py": {
        ("os", "path"),
        ("os", "path", "isabs"),
        ("os", "path", "normpath"),
    },
    "snapshot.py": {
        ("os", "path"),
        ("os", "path", "isabs"),
        ("os", "path", "normpath"),
    },
}
CURRENT_PRODUCT_CLAIM_TEXT = frozenset(
    {
        "README.md",
        "README_CN.md",
        "INSTALL.md",
        "INSTALL_CN.md",
        "ARCHITECTURE.md",
        "ARCHITECTURE_CN.md",
        "CONTRIBUTING.md",
        "CONTRIBUTING_CN.md",
        "skills/analyze-change-impact/SKILL.md",
        "skills/follow-dev-flow/SKILL.md",
        "skills/review-dev-flow-change/SKILL.md",
    }
)
EXPECTED_PRODUCT_VERSION = "0.3.0"
CURRENT_PRODUCT_ASSET_DIRECTORIES = (
    ".codex-plugin",
    ".github/workflows",
    "hooks",
    "scripts",
    "skills",
    "src/dev_flow_orchestrator",
    "templates",
    "tests",
    "workflows",
)
CURRENT_PRODUCT_ASSET_FILES = (
    "ARCHITECTURE.md",
    "ARCHITECTURE_CN.md",
    "CONTRIBUTING.md",
    "CONTRIBUTING_CN.md",
    "INSTALL.md",
    "INSTALL_CN.md",
    "LICENSE",
    "README.md",
    "README_CN.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "pyproject.toml",
    "uv.lock",
)
CURRENT_PRODUCT_ASSET_IGNORED_PARTS = frozenset(
    {"__pycache__", ".pytest_cache"}
)
VERSION_CODED_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9])(?:V|v)[0-9]+"
)
DEV_FLOW_NUMERIC_SCHEMA = re.compile(
    r"\bdev-flow-[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"(?P<version>(?:V|v)?[0-9]+(?:\.[0-9]+)*)(?![A-Za-z0-9.])",
    re.IGNORECASE,
)
EXTERNAL_VERSION_LITERALS = {
    "src/dev_flow_orchestrator/git_client.py": (
        "--porcelain=" + "v" + "1",
    ),
    ".github/workflows/focused.yml": (
        "actions/checkout@" + "v" + "4",
        "actions/setup-python@" + "v" + "5",
    ),
}
MAIN_SKILL_AGENT = "skills/follow-dev-flow/agents/openai.yaml"
UNSUPPORTED_LATER_STAGE_CLAIM = re.compile(
    r"automatically (?:creates?|manages?) (?:branches?|worktrees?)|"
    r"runs? (?:each )?repositor(?:y|ies) in parallel|"
    r"parallel repository executors?|"
    r"dispatches external CI|opens? pull requests? automatically|"
    r"自动(?:创建|管理)(?:分支|工作树)|"
    r"并行(?:执行|处理)[^。！？；;]*(?:仓库|工作树)|"
    r"并行仓库执行器|协调并行 Agent|"
    r"调度外部 CI|自动创建 PR",
    re.IGNORECASE,
)
UNSUPPORTED_WEB_UI_CLAIM = re.compile(
    r"Web ?UI (?:can|will|does) (?:mutate|approve|edit|advance)|"
    r"Web ?UI supports? (?:mutation|approvals?|task editing)|"
    r"Web ?UI (?:可以|将|会)(?:修改|批准|审批|推进)|"
    r"Web ?UI 支持(?:修改|批准|审批|推进)",
    re.IGNORECASE,
)
FULL_HORIZON_TWO_CLAIM = re.compile(
    r"Horizon 2 (?:is )?(?:fully|completely) (?:delivered|complete)|"
    r"阶段 2 (?:已经|已)?(?:全部|完整|整体)(?:交付|完成)",
    re.IGNORECASE,
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OFFICIAL_DRIVER_TOOLS = {
    "codebase-memory",
    "independent-review",
    "openspec",
}
DRIVER_RESULT_FIELDS = {
    "schema",
    "tool",
    "status",
    "phase",
    "details",
    "limitations",
}
IMPACT_REPORT_FIELDS = {
    "schema",
    "status",
    "phase",
    "contract_digest",
    "workspace_snapshot_digest",
    "repository_set_id",
    "repositories",
    "cross_repository",
    "limitations",
}
IMPACT_MEMBER_FIELDS = {
    "root",
    "workspace_snapshot_digest",
    "baseline",
    "current",
    "selected_project_id",
    "affected",
    "confirmed",
    "inferred",
    "unknowns",
    "risks",
    "limitations",
}


def _json_object(path: Path, errors: list[str], label: str) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        errors.append(label + " must contain valid JSON")
        return None
    if not isinstance(value, dict):
        errors.append(label + " must contain a JSON object")
        return None
    return value


def _check(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def _require_tokens(
    document: str,
    tokens: tuple,
    errors: list[str],
    message: str,
) -> None:
    folded = document.casefold()
    missing = [token for token in tokens if str(token).casefold() not in folded]
    if missing:
        errors.append("{} (missing: {})".format(message, ", ".join(missing)))


def _require_any(
    document: str,
    alternatives: tuple,
    errors: list[str],
    message: str,
) -> None:
    folded = document.casefold()
    if not any(str(token).casefold() in folded for token in alternatives):
        errors.append(
            "{} (expected one of: {})".format(message, ", ".join(alternatives))
        )


def _contains_unsupported_later_stage_claim(document: str) -> bool:
    normalized = re.sub(r"\s+", " ", document)
    for sentence in re.split(r"(?<=[.!?。！？;；])\s*", normalized):
        for match in UNSUPPORTED_LATER_STAGE_CLAIM.finditer(sentence):
            prefix = sentence[: match.start()]
            if re.search(
                r"\b(?:no|not|never|unsupported|outside|exclude[ds]?)\b|"
                r"不会|不得|不支持|范围外",
                prefix,
                re.IGNORECASE,
            ) is None:
                return True
    return False


def _string_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(
            item
            for nested in value.values()
            for item in _string_values(nested)
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            item
            for nested in value
            for item in _string_values(nested)
        )
    return ()


def _current_product_asset_paths(root: Path) -> tuple[Path, ...]:
    relative_paths: set[Path] = set()
    for relative in CURRENT_PRODUCT_ASSET_FILES:
        path = root / relative
        if path.is_file():
            relative_paths.add(Path(relative))
    for relative in CURRENT_PRODUCT_ASSET_DIRECTORIES:
        directory = root / relative
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            candidate_relative = path.relative_to(root)
            if any(
                part in CURRENT_PRODUCT_ASSET_IGNORED_PARTS
                for part in candidate_relative.parts
            ):
                continue
            relative_paths.add(candidate_relative)
    return tuple(sorted(relative_paths, key=lambda path: path.as_posix()))


def _without_external_version_literals(relative: str, document: str) -> str:
    for literal in EXTERNAL_VERSION_LITERALS.get(relative, ()):
        document = document.replace(literal, "<external-version>")
    return document


def _validate_current_product_versions(root: Path, errors: list[str]) -> None:
    _check(
        PRODUCT_VERSION == EXPECTED_PRODUCT_VERSION,
        errors,
        "product.PRODUCT_VERSION is not the supported package version",
    )
    for relative_path in _current_product_asset_paths(root):
        relative = relative_path.as_posix()
        if VERSION_CODED_IDENTIFIER.search(relative) is not None:
            errors.append(
                "current product asset path contains version-coded identifier: "
                + relative
            )
        try:
            document = (root / relative_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("current product asset is not readable UTF-8 text: " + relative)
            continue
        inspected = _without_external_version_literals(relative, document)
        if VERSION_CODED_IDENTIFIER.search(inspected) is not None:
            errors.append(
                "current product asset content contains version-coded identifier: "
                + relative
            )
        if any(
            match.group("version") != EXPECTED_PRODUCT_VERSION
            for match in DEV_FLOW_NUMERIC_SCHEMA.finditer(inspected)
        ):
            errors.append(
                "current product asset contains non-current dev-flow numeric schema: "
                + relative
            )


def _json_examples(document: str) -> tuple[object, ...]:
    examples = []
    for match in re.finditer(
        r"```json[ \t]*\r?\n(.*?)\r?\n```",
        document,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            examples.append(json.loads(match.group(1)))
        except ValueError:
            continue
    return tuple(examples)


def _valid_impact_report_details(details: object, envelope: dict) -> bool:
    if not isinstance(details, dict) or set(details) != IMPACT_REPORT_FIELDS:
        return False
    repositories = details.get("repositories")
    cross_repository = details.get("cross_repository")
    if (
        not isinstance(repositories, dict)
        or not 1 <= len(repositories) <= 8
        or not isinstance(cross_repository, dict)
        or set(cross_repository) != {"contracts", "effects", "unknowns", "risks"}
        or not all(isinstance(value, list) for value in cross_repository.values())
    ):
        return False

    def valid_member(repository_id: object, member: object) -> bool:
        if (
            not isinstance(repository_id, str)
            or not repository_id
            or not isinstance(member, dict)
            or set(member) != IMPACT_MEMBER_FIELDS
        ):
            return False
        baseline = member.get("baseline")
        current = member.get("current")
        affected = member.get("affected")
        return (
            isinstance(member.get("root"), str)
            and bool(member["root"])
            and isinstance(member.get("workspace_snapshot_digest"), str)
            and bool(member["workspace_snapshot_digest"])
            and isinstance(baseline, dict)
            and set(baseline) == {"project_id", "snapshot_digest", "status"}
            and isinstance(current, dict)
            and set(current) == {"project_id", "snapshot_digest", "status"}
            and isinstance(member.get("selected_project_id"), str)
            and bool(member["selected_project_id"])
            and isinstance(affected, dict)
            and set(affected) == {"components", "symbols", "contracts", "tests"}
            and all(isinstance(value, list) for value in affected.values())
            and all(
                isinstance(member.get(field), list)
                for field in (
                    "confirmed",
                    "inferred",
                    "unknowns",
                    "risks",
                    "limitations",
                )
            )
        )

    return (
        details.get("schema") == IMPACT_REPORT_SCHEMA
        and details.get("status") == envelope.get("status")
        and details.get("phase") == envelope.get("phase")
        and isinstance(details.get("contract_digest"), str)
        and bool(details["contract_digest"])
        and isinstance(details.get("workspace_snapshot_digest"), str)
        and bool(details["workspace_snapshot_digest"])
        and isinstance(details.get("repository_set_id"), str)
        and bool(details["repository_set_id"])
        and all(valid_member(key, value) for key, value in repositories.items())
        and isinstance(details.get("limitations"), list)
        and details["limitations"] == envelope.get("limitations")
    )


def _validate_impact_skill_driver_envelope(
    document: str,
    errors: list[str],
) -> None:
    envelopes = [
        example
        for example in _json_examples(document)
        if isinstance(example, dict)
        and example.get("schema") == DRIVER_RESULT_SCHEMA
    ]
    valid_envelopes = [
        envelope
        for envelope in envelopes
        if set(envelope) == DRIVER_RESULT_FIELDS
        and envelope.get("tool") == "codebase-memory"
        and envelope.get("status") in {"available", "degraded", "unavailable"}
        and isinstance(envelope.get("phase"), str)
        and bool(envelope["phase"])
        and isinstance(envelope.get("details"), dict)
        and isinstance(envelope.get("limitations"), list)
        and all(isinstance(item, str) for item in envelope["limitations"])
    ]
    _check(
        bool(valid_envelopes),
        errors,
        "analyze-change-impact Skill has no valid common driver_result envelope",
    )
    _check(
        any(
            _valid_impact_report_details(envelope["details"], envelope)
            for envelope in valid_envelopes
        ),
        errors,
        "analyze-change-impact Skill does not place a complete impact report "
        "in driver_result.details",
    )
    _check(
        "driver_result.details" in document,
        errors,
        "analyze-change-impact Skill does not explain driver_result.details "
        "placement",
    )


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


def _is_exact_repository_set_guidance(value: str) -> bool:
    folded = value.casefold()
    bounded = any(
        token in folded
        for token in (
            "one to eight",
            "one through eight",
            "up to eight",
            "1-8",
            "1–8",
            "一至八",
            "最多八",
        )
    )
    exact = "exact" in folded or "精确" in value
    return bounded and exact


def _is_user_prepared_guidance(value: str) -> bool:
    folded = value.casefold()
    return (
        "user-prepared" in folded
        or "用户预备" in value
        or "用户提前准备" in value
    )


def _is_single_executor_guidance(value: str) -> bool:
    folded = value.casefold()
    has_codex = "one codex" in folded or "一个 Codex" in value
    has_action = "one current action" in folded or "当前动作" in value
    return has_codex and has_action


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
        and PRODUCT_VERSION in guidance
        and _is_exact_repository_set_guidance(guidance)
        and _is_user_prepared_guidance(guidance)
        and _is_single_executor_guidance(guidance),
        errors,
        "follow-dev-flow agent metadata does not use the current exact-set version",
    )
    _check(
        default_prompt is not None and "$follow-dev-flow" in default_prompt,
        errors,
        "follow-dev-flow default_prompt does not invoke $follow-dev-flow",
    )
def _validate_repository_topology(root: Path, errors: list[str]) -> None:
    expected = {
        "schema": REPOSITORY_TOPOLOGY_SCHEMA,
        "minimum_repositories": 1,
        "maximum_repositories": 8,
        "membership": "exact-canonical-set",
        "caller_order": "non-semantic",
        "worktrees": "user-prepared",
        "execution": "single-codex-single-current-action",
        "managed_git_effects": False,
        "partial_assurance_reuse": True,
        "external_delivery_effects": False,
    }
    _check(
        MIN_REPOSITORY_COUNT == 1
        and MAX_REPOSITORY_COUNT == 8
        and dict(REPOSITORY_TOPOLOGY_CAPABILITIES) == expected,
        errors,
        "product repository-topology authority is invalid",
    )


def _validate_adaptive_assurance_authority(root: Path, errors: list[str]) -> None:
    expected_bounds = {
        "snapshot_paths_per_repository": 4096,
        "index_stage_entries_per_repository": 12288,
        "index_command_output_bytes": 2 * 1024 * 1024,
        "ownership_claims_per_source_action": 128,
        "task_change_manifest_entries": 4096,
        "impact_entries": 128,
        "assurance_obligations": 64,
        "review_findings": 64,
        "evidence_items_per_execution": 64,
        "workflow_actions_per_contract": 256,
        "action_payload_bytes": 64 * 1024,
        "text_field_bytes": 8 * 1024,
    }
    actual_bounds = {
        "snapshot_paths_per_repository": MAX_SNAPSHOT_PATHS,
        "index_stage_entries_per_repository": MAX_INDEX_STAGE_ENTRIES,
        "index_command_output_bytes": MAX_INDEX_COMMAND_OUTPUT_BYTES,
        "ownership_claims_per_source_action": MAX_OWNERSHIP_CLAIMS,
        "task_change_manifest_entries": MAX_TASK_CHANGE_MANIFEST_ENTRIES,
        "impact_entries": MAX_IMPACT_ENTRIES,
        "assurance_obligations": MAX_ASSURANCE_OBLIGATIONS,
        "review_findings": MAX_REVIEW_FINDINGS,
        "evidence_items_per_execution": MAX_EVIDENCE_ITEMS,
        "workflow_actions_per_contract": MAX_WORKFLOW_ACTIONS,
        "action_payload_bytes": MAX_ACTION_PAYLOAD_BYTES,
        "text_field_bytes": MAX_TEXT_FIELD_BYTES,
    }
    _check(actual_bounds == expected_bounds, errors, "0.3 product bounds are invalid")
    _check(
        ASSURANCE_POLICY_SCHEMA == product_schema("assurance-policy")
        and set(ASSURANCE_PROFILES)
        == {"lite", "feature", "bugfix", "investigation", "refactor", "full"},
        errors,
        "closed adaptive-assurance policy identity is invalid",
    )
    _check(
        AGENT_PROTOCOL_SCHEMA == product_schema("agent")
        and VERIFICATION_COVERAGE_SCHEMA == product_schema("verification-coverage")
        and DELIVERY_DOSSIER_SCHEMA == product_schema("delivery-dossier")
        and REPOSITORY_SET_SNAPSHOT_SCHEMA == product_schema("repository-set-snapshot"),
        errors,
        "current repository-set protocol identity is invalid",
    )

    runtime_contracts = {
        "src/dev_flow_orchestrator/cli.py": (
            'action="append"',
            "repositories=arguments.repo",
            "user-prepared Git worktree",
        ),
        "src/dev_flow_orchestrator/model.py": (
            "MAX_REPOSITORY_COUNT",
            "canonical_repositories",
            "repository_set_id",
        ),
        "src/dev_flow_orchestrator/controller.py": (
            "make_repository_set_snapshot",
            "tasks_for_path",
            "state.repositories",
        ),
        "src/dev_flow_orchestrator/engine.py": (
            "AGENT_PROTOCOL_SCHEMA",
            "criteria, repositories, and integration",
            '"repository_set"',
        ),
        "src/dev_flow_orchestrator/snapshot.py": (
            "REPOSITORY_SET_SNAPSHOT_SCHEMA",
            "validate_repository_set_snapshot",
            "validate_task_snapshot",
        ),
        "src/dev_flow_orchestrator/delivery.py": (
            "generate_dossier",
            "DELIVERY_DOSSIER_SCHEMA",
            "repository_id",
        ),
        "src/dev_flow_orchestrator/hook.py": (
            "tasks_for_path",
            "one current action for one Codex executor",
            "repository set with one Codex",
            "user-owned",
        ),
    }
    for relative, tokens in runtime_contracts.items():
        path = root / relative
        if not path.is_file():
            continue
        _require_tokens(
            path.read_text(encoding="utf-8"),
            tokens,
            errors,
            "{} is not wired to the repository-topology authority".format(relative),
        )

    installed_runner = root / "scripts" / "validate_installed_stage1.py"
    if installed_runner.is_file():
        _require_tokens(
            installed_runner.read_text(encoding="utf-8"),
            (
                "exact-set-secondary-resume-drift-resources-dossier",
                "exact-set-lite-success-dossier",
                "AGENT_PROTOCOL_SCHEMA",
                "DELIVERY_DOSSIER_SCHEMA",
                "ACTION_BINDING_STALE",
            ),
            errors,
            "installed validation does not prove the exact-set journeys",
        )


def _markdown_section(document: str, heading: str) -> str:
    start = document.casefold().find(heading.casefold())
    if start < 0:
        return ""
    end = document.find("\n## ", start + len(heading))
    if end < 0:
        return document[start:]
    return document[start:end]


def _validate_manifest(
    root: Path,
    manifest: Optional[dict],
    errors: list[str],
) -> None:
    if manifest is None:
        return
    allowed = {
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
    unknown = sorted(str(key) for key in manifest if key not in allowed)
    _check(
        not unknown,
        errors,
        "plugin manifest contains unsupported field(s): " + ", ".join(unknown),
    )
    _check(
        manifest.get("name") == "dev-flow-orchestrator",
        errors,
        "plugin identity changed",
    )
    _check(
        isinstance(manifest.get("description"), str)
        and bool(manifest["description"].strip()),
        errors,
        "plugin description is missing",
    )
    author = manifest.get("author")
    _check(
        isinstance(author, dict)
        and isinstance(author.get("name"), str)
        and bool(author["name"].strip())
        and not (set(author) - {"name", "email", "url"}),
        errors,
        "plugin author metadata is invalid",
    )
    _check(
        manifest.get("skills") == "./skills/" and (root / "skills").is_dir(),
        errors,
        "plugin skills path is invalid",
    )
    _check(
        "mcpServers" not in manifest and "apps" not in manifest,
        errors,
        "plugin manifest declares a missing MCP or app companion",
    )
    interface = manifest.get("interface")
    allowed_interface = {
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
    required_interface = {
        "displayName",
        "shortDescription",
        "longDescription",
        "developerName",
        "category",
    }
    _check(
        isinstance(interface, dict)
        and all(
            isinstance(interface.get(field), str)
            and bool(interface[field].strip())
            for field in required_interface
        ),
        errors,
        "plugin interface metadata is incomplete",
    )
    if isinstance(interface, dict):
        unknown_interface = sorted(
            str(key) for key in interface if key not in allowed_interface
        )
        _check(
            not unknown_interface,
            errors,
            "plugin interface contains unsupported field(s): "
            + ", ".join(unknown_interface),
        )
        capabilities = interface.get("capabilities")
        prompts = interface.get("defaultPrompt", interface.get("default_prompt"))
        _check(
            isinstance(capabilities, list)
            and bool(capabilities)
            and all(
                isinstance(item, str) and bool(item.strip())
                for item in capabilities
            ),
            errors,
            "plugin interface capabilities are invalid",
        )
        _check(
            isinstance(prompts, list)
            and 1 <= len(prompts) <= 3
            and all(
                isinstance(item, str)
                and bool(item.strip())
                and len(item) <= 128
                for item in prompts
            ),
            errors,
            "plugin interface default prompts are invalid",
        )
        _check(
            PRODUCT_VERSION in str(interface.get("longDescription", "")),
            errors,
            "plugin interface does not describe the current product version",
        )
    _check(
        "[TODO:" not in json.dumps(manifest, ensure_ascii=False),
        errors,
        "plugin manifest contains a TODO placeholder",
    )


def _validate_package_versions(
    root: Path,
    manifest: Optional[dict],
    errors: list[str],
) -> None:
    manifest_version = manifest.get("version") if isinstance(manifest, dict) else None
    _check(
        manifest_version == PRODUCT_VERSION,
        errors,
        "plugin version does not match PRODUCT_VERSION",
    )
    pyproject_path = root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject = pyproject_path.read_text(encoding="utf-8")
        version_match = re.search(
            r'^version\s*=\s*"([^"]+)"\s*$', pyproject, re.MULTILINE
        )
        pyproject_version = (
            version_match.group(1) if version_match is not None else None
        )
        _check(
            pyproject_version == manifest_version,
            errors,
            "manifest and pyproject versions differ",
        )
        _check(
            re.search(
                r"^dependencies\s*=\s*\[\s*\]\s*$", pyproject, re.MULTILINE
            )
            is not None,
            errors,
            "runtime dependencies must remain empty",
        )
    lock_path = root / "uv.lock"
    if lock_path.is_file():
        lock = lock_path.read_text(encoding="utf-8")
        lock_match = re.search(
            r'^\[\[package\]\]\s*\nname\s*=\s*"dev-flow-orchestrator"\s*\n'
            r'version\s*=\s*"([^"]+)"\s*$',
            lock,
            re.MULTILINE,
        )
        lock_version = lock_match.group(1) if lock_match is not None else None
        _check(
            lock_version == manifest_version,
            errors,
            "manifest and uv.lock versions differ",
        )


def _validate_driver_contract(
    selector: str,
    node_id: str,
    contract: object,
    errors: list[str],
) -> None:
    driver = contract.driver
    if driver is None:
        return
    artifact = contract.artifact
    valid = (
        isinstance(driver, Mapping)
        and set(driver) == {"tool", "optional", "fallback", "produces"}
        and driver.get("tool") in OFFICIAL_DRIVER_TOOLS
        and driver.get("optional") is True
        and isinstance(driver.get("fallback"), str)
        and bool(driver["fallback"].strip())
        and artifact is not None
        and driver.get("produces") == artifact.artifact_type
        and contract.payload_types.get("driver_result") == "object"
    )
    _check(
        valid,
        errors,
        "workflow {!r} node {} driver contract is invalid".format(
            selector, node_id
        ),
    )


def _validate_official_workflow(
    selector: str,
    definition: object,
    errors: list[str],
) -> None:
    prefix = "workflow {!r}".format(selector)
    _check(
        definition.schema == WORKFLOW_SCHEMA
        and definition.version == PRODUCT_VERSION,
        errors,
        prefix + " does not use the current workflow version",
    )
    expected_identity = workflow_identity(
        selector,
        definition.document,
    )
    _check(
        definition.identity == expected_identity
        and SHA256.fullmatch(definition.identity) is not None,
        errors,
        prefix + " identity is invalid",
    )
    topology_keys = {
        "repository_count",
        "repository_topology",
        "workspace_strategy",
        "execution_topology",
    }
    _check(
        not (set(definition.document) & topology_keys),
        errors,
        prefix + " improperly binds workflow depth to repository topology",
    )
    cancellable_nodes = {
        node_id
        for node_id, contract in definition.nodes.items()
        if contract.action_id and contract.handler_id != "delivery.finalize"
    }
    cancel_stages = set(definition.cancel_stages)
    cancel_contracts = tuple(definition.cancellations.values())
    cancel_targets = {
        (contract.target_node, contract.target_status)
        for contract in cancel_contracts
    }
    _check(
        bool(cancel_stages)
        and cancel_stages.issubset(cancellable_nodes)
        and len(cancel_stages) * 2 > len(cancellable_nodes)
        and all(
            contract.action_id == "task.cancel"
            and contract.handler_id == "artifact.record"
            and dict(contract.payload_types) == {"reason": "string"}
            for contract in cancel_contracts
        )
        and len(cancel_targets) == 1
        and next(iter(cancel_targets), (None, None))[0]
        in definition.terminal_nodes
        and next(iter(cancel_targets), (None, None))[1] == "CANCELLED",
        errors,
        prefix + " does not expose stage-declared cancellation for most normal stages",
    )
    finalizers = []
    for node_id, contract in definition.nodes.items():
        if not contract.action_id:
            continue
        _check(
            contract.artifact is not None,
            errors,
            "{} node {} has no typed artifact".format(prefix, node_id),
        )
        expected_driver = None
        if contract.action_id == "impact.record":
            expected_driver = "codebase-memory"
        elif contract.action_id == "plan.record":
            expected_driver = "openspec"
        elif contract.handler_id == "review.record":
            expected_driver = "independent-review"
        if expected_driver is not None:
            _check(
                contract.driver is not None
                and contract.driver.get("tool") == expected_driver,
                errors,
                "{} node {} is missing its {} driver".format(
                    prefix, node_id, expected_driver
                ),
            )
        _validate_driver_contract(selector, node_id, contract, errors)
        if contract.handler_id in ASSURANCE_HANDLER_IDS:
            rework = contract.rework
            exhausted = (
                definition.nodes.get(rework.exhausted_node)
                if rework is not None
                else None
            )
            _check(
                rework is not None
                and isinstance(rework.max_attempts, int)
                and not isinstance(rework.max_attempts, bool)
                and rework.max_attempts > 0
                and exhausted is not None
                and exhausted.handler_id == "delivery.finalize"
                and exhausted.finalize_outcome == "incomplete",
                errors,
                "{} node {} has no finite rework/exhaustion contract".format(
                    prefix, node_id
                ),
            )
        if contract.handler_id == "delivery.finalize":
            finalizers.append(contract)
            _check(
                contract.artifact is not None
                and contract.artifact.artifact_type == "delivery-dossier"
                and contract.target_node in definition.terminal_nodes
                and contract.finalize_outcome in {"success", "incomplete"},
                errors,
                "{} node {} does not finalize a Delivery Dossier".format(
                    prefix, node_id
                ),
            )
    outcomes = {contract.finalize_outcome for contract in finalizers}
    _check(
        outcomes == {"success", "incomplete"},
        errors,
        prefix + " must expose successful and incomplete dossier outcomes",
    )
    cancel_target = next(iter(cancel_targets), (None, None))[0]
    for terminal in definition.terminal_nodes:
        if terminal == cancel_target:
            continue
        inbound = [
            contract
            for contract in definition.nodes.values()
            if contract.target_node == terminal
        ]
        _check(
            bool(inbound)
            and all(
                contract.handler_id == "delivery.finalize" for contract in inbound
            ),
            errors,
            "{} terminal {} bypasses Delivery Dossier finalization".format(
                prefix, terminal
            ),
        )


def _validate_skill_guidance(root: Path, errors: list[str]) -> None:
    main_path = root / "skills" / "follow-dev-flow" / "SKILL.md"
    if main_path.is_file():
        document = main_path.read_text(encoding="utf-8")
        _require_tokens(
            document,
            (
                PRODUCT_VERSION,
                DELIVERY_CONTRACT_SCHEMA,
                "$follow-dev-flow",
                "--binding-json",
                "revise-contract",
                "decide",
                "Delivery Dossier",
                "DONE",
                "INCOMPLETE",
                "OpenSpec",
                "codebase-memory",
                "independent-review",
                "fallback",
                "degraded",
                "unavailable",
                "governing",
                "source-predecessor",
                "causal",
                "produces-source",
                "verifies-source",
                OPENSPEC_TASKS_NORMALIZER,
                "reported",
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                "repository_set",
                DELIVERY_DOSSIER_SCHEMA,
                "--repo",
                "repository_id",
                "current_obligation",
                "assurance_result",
                "impact_manifest",
                "review_contract",
                "causal_manifest_entries",
                "one current action",
                "one Codex",
                "user-prepared",
                "aggregate",
                "external CI",
                "cancel.stages",
                "Delivery finalizers",
            )
            + tuple(WORKFLOW_IDS),
            errors,
            "follow-dev-flow Skill is missing current-version delivery guidance",
        )
        _require_any(
            document,
            ("one to eight", "1-8", "1–8", "一至八"),
            errors,
            "follow-dev-flow Skill does not state the bounded repository boundary",
        )
        mismatch_guidance = _markdown_section(
            document,
            "## Close a confirmed repository mismatch",
        )
        _require_tokens(
            mismatch_guidance,
            (
                "confirmed semantic repository mismatch",
                "Stop the projected action",
                "exact task ID",
                "task remains active",
                "explicit user authorization",
                "`done: true`",
                "`status: CANCELLED`",
                "`current_node: cancelled`",
                "Do not substitute another repository",
                "stash, reset, clean, checkout",
            ),
            errors,
            "follow-dev-flow Skill does not close confirmed repository mismatches",
        )
        _check(
            document.count("--repo") >= 3,
            errors,
            "follow-dev-flow Skill does not document repeatable --repo selection",
        )
        _require_tokens(
            document,
            (
                "Do not",
                "create/switch branches or worktrees",
                "open pull requests",
                "external CI",
                "partial approval after aggregate drift",
            ),
            errors,
            "follow-dev-flow Skill does not preserve user-owned delivery boundaries",
        )
        _require_any(
            document,
            ("max_attempts", "bounded rework", "finite rework", "有界返工"),
            errors,
            "follow-dev-flow Skill does not explain bounded assurance",
        )
        _require_tokens(
            document,
            ("JSON", "status", "instructions"),
            errors,
            "follow-dev-flow Skill does not require current OpenSpec "
            "JSON status and instructions",
        )
    impact_path = root / "skills" / "analyze-change-impact" / "SKILL.md"
    if impact_path.is_file():
        impact = impact_path.read_text(encoding="utf-8")
        _require_tokens(
            impact,
            (
                "baseline",
                "current",
                "project ID",
                "phase",
                "source",
                "degraded",
                "repository_id",
                "every canonical",
                "cross-repository",
            ),
            errors,
            "analyze-change-impact Skill is missing current-version graph evidence guidance",
        )
        _validate_impact_skill_driver_envelope(impact, errors)
    review_path = root / "skills" / "review-dev-flow-change" / "SKILL.md"
    if review_path.is_file():
        review = review_path.read_text(encoding="utf-8")
        _require_tokens(
            review,
            (
                PRODUCT_VERSION,
                "independent",
                "exact",
                "snapshot",
                "digest",
                "canonical member",
                "aggregate",
                "every member",
                "partial approval after aggregate drift",
            ),
            errors,
            "review-dev-flow-change Skill is missing current-version review guidance",
        )
        for alternatives, label in (
            (("base revision", "base_revision"), "base revision"),
            (("artifact digest", "artifact_digest"), "artifact digest"),
            (
                ("guidance snapshot digest", "guidance_snapshot_digest"),
                "guidance digest",
            ),
        ):
            _require_any(
                review,
                alternatives,
                errors,
                "review-dev-flow-change Skill is missing " + label,
            )


def _validate_public_docs(root: Path, errors: list[str]) -> None:
    catalog_tokens = tuple(WORKFLOW_IDS)
    english_path = root / "README.md"
    if english_path.is_file():
        english = english_path.read_text(encoding="utf-8")
        _require_tokens(
            english,
            (
                PRODUCT_VERSION,
                "delivery contract",
                "bounded",
                "rework",
                "OpenSpec",
                "codebase-memory",
                "independent-review",
                "Delivery Dossier",
                "one to eight",
                "exact",
                "user-prepared",
                "one current action",
                "one Codex",
                "--repo",
                AGENT_PROTOCOL_SCHEMA,
                "repository_id",
                "criteria",
                "repositories",
                "integration",
                AGENT_PROTOCOL_SCHEMA,
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
                VERIFICATION_COVERAGE_SCHEMA,
                DELIVERY_DOSSIER_SCHEMA,
            )
            + catalog_tokens,
            errors,
            "README.md is missing current-version repository-set guidance",
        )
    chinese_path = root / "README_CN.md"
    if chinese_path.is_file():
        chinese = chinese_path.read_text(encoding="utf-8")
        _require_tokens(
            chinese,
            (
                PRODUCT_VERSION,
                "交付契约",
                "有界",
                "返工",
                "OpenSpec",
                "codebase-memory",
                "independent-review",
                "一至八",
                "精确",
                "用户提前准备",
                "一个当前动作",
                "一个 Codex",
                "--repo",
                AGENT_PROTOCOL_SCHEMA,
                "repository_id",
                "criteria",
                "repositories",
                "integration",
                AGENT_PROTOCOL_SCHEMA,
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
                VERIFICATION_COVERAGE_SCHEMA,
                DELIVERY_DOSSIER_SCHEMA,
            )
            + catalog_tokens,
            errors,
            "README_CN.md 缺少当前版本仓库集合说明",
        )
        _require_any(
            chinese,
            ("Delivery Dossier", "交付档案"),
            errors,
            "README_CN.md 缺少 Delivery Dossier 说明",
        )
    install_path = root / "INSTALL.md"
    if install_path.is_file():
        install = install_path.read_text(encoding="utf-8")
        _require_tokens(
            install,
            (
                "<PLUGIN_DATA>/{}".format(PLUGIN_DATA_NAMESPACE),
                "--repo",
                "user-prepared",
                "secondary member",
                "exact canonical",
                "missing or moved",
                "aggregate repository-set snapshot",
            ),
            errors,
            "INSTALL.md is missing the current-version exact-set install boundary",
        )
    architecture_path = root / "ARCHITECTURE.md"
    if architecture_path.is_file():
        architecture = architecture_path.read_text(encoding="utf-8")
        _require_tokens(
            architecture,
            (
                PRODUCT_VERSION,
                WORKFLOW_SCHEMA,
                AGENT_PROTOCOL_SCHEMA,
                REPOSITORY_SET_SNAPSHOT_SCHEMA,
                VERIFICATION_COVERAGE_SCHEMA,
                DELIVERY_DOSSIER_SCHEMA,
                RECORD_SCHEMA,
                ARTIFACT_SCHEMA,
                "repository_id",
                "criteria",
                "repositories",
                "integration",
                "aggregate",
                "one current action",
                "one Codex",
                "Delivery Dossier",
            ),
            errors,
            "ARCHITECTURE.md is missing current-version exact-set identity or dossier guidance",
        )
    contributing_path = root / "CONTRIBUTING.md"
    if contributing_path.is_file():
        _require_tokens(
            contributing_path.read_text(encoding="utf-8"),
            (
                "repository topology",
                "cardinality",
                "repository-set",
                WORKFLOW_SCHEMA,
                "validate_package.py",
            ),
            errors,
            "CONTRIBUTING.md is missing repository-topology validation guidance",
        )
    roadmap_path = root / "ROADMAP.md"
    if roadmap_path.is_file():
        _require_tokens(
            roadmap_path.read_text(encoding="utf-8"),
            (
                PRODUCT_VERSION,
                "multi-repository",
                "user-prepared",
                "one Codex",
                "partial assurance",
                "external CI",
            ),
            errors,
            "ROADMAP.md is missing the delivered exact-set boundary",
        )
    roadmap_cn_path = root / "ROADMAP_CN.md"
    if roadmap_cn_path.is_file():
        _require_tokens(
            roadmap_cn_path.read_text(encoding="utf-8"),
            (
                PRODUCT_VERSION,
                "user-prepared",
                "one Codex",
                "部分复用",
                "外部 CI",
            ),
            errors,
            "ROADMAP_CN.md is missing the delivered exact-set boundary",
        )

    web_ui_documents = {
        "README.md": (
            "[简体中文](README_CN.md)",
            "Local read-only Web UI",
            "dev-flow --data-dir",
            "127.0.0.1",
            "no separate WebUI version",
            "Observe live",
        ),
        "README_CN.md": (
            "[English](README.md)",
            "本地只读 Web UI",
            "dev-flow --data-dir",
            "127.0.0.1",
            "独立的 WebUI 版本",
            "Observe live",
        ),
        "ROADMAP.md": (
            "[简体中文](ROADMAP_CN.md)",
            "first read-only slice delivered",
            "local read-only Web UI",
            "remain planned",
        ),
        "ROADMAP_CN.md": (
            "[English](ROADMAP.md)",
            "首个只读切片已交付",
            "本地只读 Web UI",
            "仍处于规划中",
        ),
        "ARCHITECTURE.md": (
            "[简体中文](ARCHITECTURE_CN.md)",
            "Local read-only presentation boundary",
            "web.py",
            "web_views.py",
            "VIEW_STALE",
            "429",
        ),
        "ARCHITECTURE_CN.md": (
            "[English](ARCHITECTURE.md)",
            "本地只读展示边界",
            "web.py",
            "web_views.py",
            "VIEW_STALE",
            "429",
        ),
        "CONTRIBUTING.md": (
            "[简体中文](CONTRIBUTING_CN.md)",
            "Web UI contribution boundary",
            "PRODUCT_IDENTITY",
            "manual-unverified",
        ),
        "CONTRIBUTING_CN.md": (
            "[English](CONTRIBUTING.md)",
            "Web UI 贡献边界",
            "PRODUCT_IDENTITY",
            "manual-unverified",
        ),
        "INSTALL.md": (
            "[简体中文](INSTALL_CN.md)",
            "Launch the local read-only Web UI",
            "dev-flow --data-dir",
            "127.0.0.1",
            "Observe live",
        ),
        "INSTALL_CN.md": (
            "[English](INSTALL.md)",
            "启动本地只读 Web UI",
            "dev-flow --data-dir",
            "127.0.0.1",
            "Observe live",
        ),
    }
    for relative, tokens in web_ui_documents.items():
        path = root / relative
        if path.is_file():
            document = path.read_text(encoding="utf-8")
            _require_tokens(
                re.sub(r"\s+", " ", document),
                (PRODUCT_VERSION,) + tokens,
                errors,
                relative + " is missing the integrated read-only Web UI boundary",
            )
            _check(
                re.search(r"(?:Web ?UI|WebUI).{0,48}(?:version|版本)\s+[0-9]", document, re.IGNORECASE)
                is None,
                errors,
                relative + " declares a separate numeric Web UI version",
            )
            _check(
                UNSUPPORTED_WEB_UI_CLAIM.search(re.sub(r"\s+", " ", document))
                is None,
                errors,
                relative + " claims unsupported Web UI mutation authority",
            )
            if relative in {"ROADMAP.md", "ROADMAP_CN.md"}:
                _check(
                    FULL_HORIZON_TWO_CLAIM.search(re.sub(r"\s+", " ", document))
                    is None,
                    errors,
                    relative + " claims that all of Horizon 2 is delivered",
                )


def _validate_imports(module: Path, errors: list[str]) -> None:
    if not module.is_file():
        return
    source = module.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(module))
    except SyntaxError:
        errors.append("runtime syntax invalid: " + module.name)
        return
    allowed = PURE_IMPORT_ALLOWLIST.get(module.name, set())
    allowed_attributes = PURE_ATTRIBUTE_ALLOWLIST.get(module.name, set())

    def qualified_attribute(node: ast.Attribute) -> tuple[str, ...]:
        parts = [node.attr]
        value = node.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return tuple(reversed(parts))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = next(
                    (
                        part
                        for part in alias.name.split(".")
                        if part in FORBIDDEN_IMPORTS
                    ),
                    None,
                )
                if imported is not None and imported not in allowed:
                    errors.append(
                        "{} imports infrastructure module {}".format(
                            module.name, alias.name
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            imported = next(
                (
                    part
                    for part in (node.module or "").split(".")
                    if part in FORBIDDEN_IMPORTS
                ),
                None,
            )
            # An allowlisted module must stay qualified so the attribute gate
            # can prove which APIs it uses; `from os import ...` bypasses that.
            if imported is not None:
                errors.append(
                    "{} imports infrastructure module {}".format(
                        module.name, node.module
                    )
                )
        elif isinstance(node, ast.Attribute):
            qualified = qualified_attribute(node)
            if (
                qualified
                and qualified[0] in allowed
                and qualified not in allowed_attributes
            ):
                errors.append(
                    "{} uses forbidden infrastructure API {}".format(
                        module.name, ".".join(qualified)
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
            tokens[2:] == [
                "--data-dir",
                str((plugin_data / PLUGIN_DATA_NAMESPACE).resolve()),
            ],
            errors,
            "Hook locator does not isolate current-version plugin data",
        )
        _check(
            "Dev Flow {}".format(PRODUCT_VERSION) in context
            and "$follow-dev-flow" in context,
            errors,
            "Hook does not inject current-version Skill guidance",
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


def _validate_windows_product_integration(root: Path, errors: list[str]) -> None:
    required_tokens = {
        "scripts/dev_flow_python_launcher.cmd": (
            "DisableDelayedExpansion",
            "DEV_FLOW_PYTHON",
            "struct.calcsize('P') == 8",
            "-X utf8 -I -S",
        ),
        "scripts/install.ps1": (
            "Set-StrictMode -Version Latest",
            "refs/heads/$RepositoryRef",
            "--ff-only",
            "--no-overwrite-ignore",
            "scripts\\validate_package.py",
            "[IO.File]::Replace",
            "/hooks",
        ),
        "scripts/uninstall.ps1": (
            "[switch]$KeepSource",
            "status', '--ignored', '--porcelain",
            "--remotes=origin",
            "[IO.File]::Replace",
            "TASK DATA",
        ),
    }
    for relative, tokens in required_tokens.items():
        path = root / relative
        if path.is_file():
            _require_tokens(
                path.read_text(encoding="utf-8"),
                tokens,
                errors,
                relative + " does not preserve the Windows integration boundary",
            )
    document_tokens = {
        "README.md": ("Windows 10 22H2 x64", "Windows 11 x64", "/hooks", "preview"),
        "README_CN.md": ("Windows 10 22H2 x64", "Windows 11 x64", "/hooks", "预览"),
        "INSTALL.md": ("install.ps1", "uninstall.ps1", "-KeepSource", "127.0.0.1"),
        "INSTALL_CN.md": ("install.ps1", "uninstall.ps1", "-KeepSource", "127.0.0.1"),
        "ARCHITECTURE.md": ("commandWindows", "PowerShell", "guardrail"),
        "ARCHITECTURE_CN.md": ("commandWindows", "PowerShell", "guardrail"),
        "ROADMAP.md": ("Windows 11 x64", "Windows 10 22H2 x64", "Server"),
        "ROADMAP_CN.md": ("Windows 11 x64", "Windows 10 22H2 x64", "Server"),
        "CONTRIBUTING.md": ("commandWindows", "PowerShell 5.1", "installed journey"),
        "CONTRIBUTING_CN.md": ("commandWindows", "PowerShell 5.1", "安装后旅程"),
    }
    for relative, tokens in document_tokens.items():
        path = root / relative
        if path.is_file():
            _require_tokens(
                re.sub(r"\s+", " ", path.read_text(encoding="utf-8")),
                tokens,
                errors,
                relative + " is missing the bounded Windows integration guidance",
            )


def _validate_local_read_only_web_ui(root: Path, errors: list[str]) -> None:
    runtime = root / "src" / "dev_flow_orchestrator"
    web_path = runtime / "web.py"
    views_path = runtime / "web_views.py"
    cli_path = runtime / "cli.py"
    assets = runtime / "web_assets"
    if not all(path.is_file() for path in (web_path, views_path, cli_path)):
        return
    web = web_path.read_text(encoding="utf-8")
    views = views_path.read_text(encoding="utf-8")
    cli = cli_path.read_text(encoding="utf-8")
    _require_tokens(
        web,
        (
            'SERVER_HOST = "127.0.0.1"',
            "secrets.token_urlsafe(32)",
            '"Authorization"',
            '"HTTP_HOST_FORBIDDEN"',
            '"HTTP_ORIGIN_FORBIDDEN"',
            '"LIVE_CAPTURE_BUSY"',
            "LIVE_CAPTURE_SLOT.acquire(blocking=False)",
            '"Cache-Control", "no-store"',
            '"Content-Security-Policy"',
        ),
        errors,
        "src/dev_flow_orchestrator/web.py is not the bounded loopback authority",
    )
    _require_tokens(
        views,
        (
            "PRODUCT_VERSION",
            "PRODUCT_IDENTITY",
            '"not-evaluated"',
            '"task-live-detail"',
            '"$follow-dev-flow task_id={}"',
        ),
        errors,
        "src/dev_flow_orchestrator/web_views.py is not the bounded read model",
    )
    _require_tokens(
        cli,
        (
            'commands.add_parser("web")',
            'web.add_argument("--port", type=int, default=0)',
            "run_web(arguments.data_dir, port=arguments.port)",
        ),
        errors,
        "CLI does not expose the integrated foreground Web UI",
    )
    asset_paths = tuple(
        assets / name for name in ("index.html", "app.js", "styles.css")
    )
    for path in asset_paths:
        _check(path.is_file() and path.stat().st_size > 0, errors, "missing Web UI asset " + path.name)
        matches = tuple(
            candidate
            for candidate in root.rglob(path.name)
            if not any(part in CURRENT_PRODUCT_ASSET_IGNORED_PARTS for part in candidate.parts)
        )
        _check(
            matches == (path,),
            errors,
            "Web UI asset must appear exactly once: " + path.name,
        )
    if all(path.is_file() for path in asset_paths):
        combined = "\n".join(path.read_text(encoding="utf-8") for path in asset_paths)
        for forbidden in (
            "http://",
            "https://",
            "localStorage",
            "sessionStorage",
            "serviceWorker",
            "document.cookie",
            ".innerHTML",
        ):
            _check(
                forbidden not in combined,
                errors,
                "Web UI asset uses forbidden browser capability " + forbidden,
            )
        _check(
            "textContent" in combined and 'credentials: "omit"' in combined,
            errors,
            "Web UI assets do not use safe local-only rendering",
        )
    _check(
        not (root / ".mcp.json").exists()
        and not (root / "web-ui").exists()
        and not (root / "package.json").exists(),
        errors,
        "Web UI must not introduce an app, MCP server, or Node package",
    )
    allowed_runtime_imports = {
        "__future__",
        "collections",
        "datetime",
        "http",
        "importlib",
        "json",
        "select",
        "secrets",
        "signal",
        "socket",
        "socketserver",
        "sys",
        "threading",
        "typing",
        "urllib",
    }
    for module_path in (web_path, views_path):
        try:
            tree = ast.parse(module_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            imported = None
            if isinstance(node, ast.Import):
                imported = next(
                    (alias.name.split(".", 1)[0] for alias in node.names),
                    None,
                )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported = (node.module or "").split(".", 1)[0]
            if imported is not None:
                _check(
                    imported in allowed_runtime_imports,
                    errors,
                    module_path.name + " imports non-standard runtime dependency " + imported,
                )
    installed_path = root / "scripts" / "validate_installed_stage1.py"
    if installed_path.is_file():
        _require_tokens(
            installed_path.read_text(encoding="utf-8"),
            (
                "def web_ui_journey(self)",
                "self.web_ui_journey()",
                '"state_unchanged": True',
                '"status": "manual-unverified"',
                '"hostile-origin"',
            ),
            errors,
            "installed evidence does not preserve the Web UI observation boundary",
        )


def _validate_current_candidate(root: Path) -> dict:
    errors: list[str] = []
    _validate_current_product_versions(root, errors)
    catalog_valid = (
        isinstance(WORKFLOW_IDS, tuple)
        and len(WORKFLOW_IDS) == 6
        and len(set(WORKFLOW_IDS)) == len(WORKFLOW_IDS)
        and tuple(sorted(WORKFLOW_IDS)) == WORKFLOW_IDS
        and all(
            isinstance(item, str) and IDENTIFIER.fullmatch(item) is not None
            for item in WORKFLOW_IDS
        )
    )
    _check(
        catalog_valid,
        errors,
        "product.WORKFLOW_IDS must declare six sorted unique workflow ids",
    )
    safe_catalog = (
        WORKFLOW_IDS
        if catalog_valid
        else tuple(
            item
            for item in WORKFLOW_IDS
            if isinstance(item, str) and IDENTIFIER.fullmatch(item) is not None
        )
    )
    required = REQUIRED_STATIC + tuple(
        "workflows/{}.yaml".format(selector) for selector in safe_catalog
    )
    for relative in required:
        _check((root / relative).is_file(), errors, "missing " + relative)
    for relative in FORBIDDEN_PATHS:
        _check(
            not (root / relative).exists(),
            errors,
            "predecessor path remains: " + relative,
        )
    workflow_assets = tuple(
        sorted(path.stem for path in (root / "workflows").glob("*.yaml"))
    )
    _check(
        workflow_assets == safe_catalog,
        errors,
        "workflow assets differ from product.WORKFLOW_IDS",
    )
    manifest = _json_object(
        root / ".codex-plugin" / "plugin.json",
        errors,
        ".codex-plugin/plugin.json",
    )
    _validate_manifest(root, manifest, errors)
    _validate_package_versions(root, manifest, errors)
    _validate_local_read_only_web_ui(root, errors)
    _validate_windows_product_integration(root, errors)
    _validate_repository_topology(root, errors)
    _validate_adaptive_assurance_authority(root, errors)
    _check(
        PLUGIN_DATA_NAMESPACE == PRODUCT_VERSION
        and WORKFLOW_SCHEMA == product_schema("workflow")
        and AGENT_PROTOCOL_SCHEMA == product_schema("agent"),
        errors,
        "product version, data namespace, or agent protocol is inconsistent",
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
        _check(
            PRODUCT_VERSION in source,
            errors,
            relative + " does not identify the current product version",
        )
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
    discovered = workflows_loader.list_builtin_ids()
    _check(
        discovered == WORKFLOW_IDS,
        errors,
        "workflow registry mismatch with product.WORKFLOW_IDS",
    )
    definitions = []
    for selector in safe_catalog:
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
        _validate_official_workflow(selector, definition, errors)
        _check(
            definition.assurance_policy == ASSURANCE_POLICY_SCHEMA
            and definition.assurance_profile == selector
            and sum(
                node.handler_id == "assurance.dispatch"
                for node in definition.nodes.values()
            ) == 1,
            errors,
            "built-in workflow {!r} does not use one closed adaptive dispatch".format(
                selector
            ),
        )
    _check(
        len({definition.identity for definition in definitions})
        == len(definitions),
        errors,
        "built-in workflow identities are not distinct",
    )
    hooks = _json_object(root / "hooks" / "hooks.json", errors, "hooks/hooks.json")
    serialized = json.dumps(hooks, ensure_ascii=False)
    _check(
        "$PLUGIN_ROOT/scripts/dev_flow_python_launcher" in serialized
        and "$PLUGIN_ROOT/hooks/dev_flow_hook.py" in serialized,
        errors,
        "Hook does not launch the packaged bootstrap",
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
    expected_windows_hook_command = (
        '"%PLUGIN_ROOT%\\scripts\\dev_flow_python_launcher.cmd" '
        '"%PLUGIN_ROOT%\\hooks\\dev_flow_hook.py"'
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
                    _check(
                        isinstance(entry, dict)
                        and entry.get("commandWindows")
                        == expected_windows_hook_command,
                        errors,
                        "Hook event {!r} lacks the packaged Windows launcher".format(
                            event
                        ),
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
    hook_source_path = runtime_root / "hook.py"
    if hook_source_path.is_file():
        hook_source = hook_source_path.read_text(encoding="utf-8")
        _check(
            'os.environ.get("PLUGIN_DATA")' in hook_source
            and "PLUGIN_DATA_NAMESPACE" in hook_source
            and "PRODUCT_VERSION" in hook_source
            and "$follow-dev-flow" in hook_source,
            errors,
            "Hook does not honor the current PLUGIN_DATA and Skill guidance contract",
        )
    marketplace_entry = _json_object(
        root / "templates" / "marketplace-entry.json",
        errors,
        "templates/marketplace-entry.json",
    )
    marketplace = _json_object(
        root / "templates" / "personal-marketplace.example.json",
        errors,
        "templates/personal-marketplace.example.json",
    )
    plugins = marketplace.get("plugins") if isinstance(marketplace, dict) else None
    _check(
        isinstance(marketplace_entry, dict)
        and marketplace_entry.get("name") == "dev-flow-orchestrator"
        and marketplace_entry.get("source")
        == {"source": "local", "path": "./plugins/dev-flow-orchestrator"}
        and marketplace_entry.get("policy")
        == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}
        and marketplace_entry.get("category") == "Productivity",
        errors,
        "marketplace entry identity, source or policy is invalid",
    )
    _check(
        isinstance(plugins, list)
        and plugins == [marketplace_entry],
        errors,
        "personal marketplace template must contain the canonical entry once",
    )
    for relative in CURRENT_PRODUCT_CLAIM_TEXT:
        path = root / relative
        if path.is_file():
            public_document = path.read_text(encoding="utf-8")
            _check(
                not _contains_unsupported_later_stage_claim(public_document),
                errors,
                "unsupported later-stage product claim remains: " + relative,
            )
    if isinstance(manifest, dict):
        _check(
            not any(
                _contains_unsupported_later_stage_claim(value)
                for value in _string_values(manifest)
            ),
            errors,
            "plugin manifest claims unsupported later-stage product behavior",
        )
    _validate_skill_guidance(root, errors)
    _validate_main_skill_agent(root, errors)
    _validate_public_docs(root, errors)
    _hook_locator_smoke(root, errors)
    return {
        "ok": not errors,
        "platform": "current-host",
        "builtin_workflows": list(discovered),
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
