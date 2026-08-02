#!/usr/bin/env python3
"""Validate the complete macOS V6 plugin candidate from its own root."""

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
    PLUGIN_DATA_NAMESPACE,
    WORKFLOW_IDS,
    WORKFLOW_V2_ADAPTER_IDENTITY,
    WORKFLOW_VERSION,
)
from dev_flow_orchestrator.workflow import (  # noqa: E402
    ASSURANCE_HANDLER_IDS,
    SCHEMA_V2,
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
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README_CN.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "hooks/dev_flow_hook.py",
    "hooks/hooks.json",
    "scripts/dev_flow.py",
    "scripts/dev_flow_python_launcher",
    "scripts/validate_installed_stage1.py",
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
    "src/dev_flow_orchestrator/delivery.py",
    "src/dev_flow_orchestrator/engine.py",
    "src/dev_flow_orchestrator/filesystem.py",
    "src/dev_flow_orchestrator/git_client.py",
    "src/dev_flow_orchestrator/hook.py",
    "src/dev_flow_orchestrator/model.py",
    "src/dev_flow_orchestrator/product.py",
    "src/dev_flow_orchestrator/snapshot.py",
    "src/dev_flow_orchestrator/store.py",
    "src/dev_flow_orchestrator/workflow.py",
    "src/dev_flow_orchestrator/workflows.py",
    "src/dev_flow_orchestrator/yaml_subset.py",
    "templates/marketplace-entry.json",
    "templates/personal-marketplace.example.json",
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
    "delivery",
    "model",
    "product",
    "snapshot",
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
    # Snapshot validation performs lexical path checks only; it does no I/O.
    "snapshot.py": {"os"},
}
PURE_ATTRIBUTE_ALLOWLIST = {
    "snapshot.py": {
        ("os", "path"),
        ("os", "path", "isabs"),
        ("os", "path", "normpath"),
    },
}
PUBLIC_TEXT = (
    "README.md",
    "README_CN.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "INSTALL.md",
    "ARCHITECTURE.md",
    "skills/analyze-change-impact/SKILL.md",
    "skills/follow-dev-flow/SKILL.md",
    "skills/review-dev-flow-change/SKILL.md",
)
MAIN_SKILL_AGENT = "skills/follow-dev-flow/agents/openai.yaml"
STALE_MAIN_AGENT_GUIDANCE = re.compile(
    r"\bV[2345]\b|\bmulti[- ]repository\b|单仓库或多仓库|多仓库",
    re.IGNORECASE,
)
SEMVER_V6 = re.compile(r"6\.0\.0\+codex\.[a-z0-9]+(?:-[a-z0-9]+)*")
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
    baseline = details.get("baseline")
    current = details.get("current")
    affected = details.get("affected")
    list_fields = ("confirmed", "inferred", "unknowns", "risks", "limitations")
    return (
        details.get("schema") == "dev-flow-impact-report/v1"
        and details.get("status") == envelope.get("status")
        and details.get("phase") == envelope.get("phase")
        and isinstance(details.get("contract_digest"), str)
        and bool(details["contract_digest"])
        and isinstance(details.get("workspace_snapshot_digest"), str)
        and bool(details["workspace_snapshot_digest"])
        and isinstance(baseline, dict)
        and set(baseline) == {"project_id", "snapshot_digest", "status"}
        and isinstance(current, dict)
        and set(current) == {"project_id", "snapshot_digest", "status"}
        and isinstance(details.get("selected_project_id"), str)
        and bool(details["selected_project_id"])
        and isinstance(affected, dict)
        and set(affected) == {"components", "symbols", "contracts", "tests"}
        and all(isinstance(value, list) for value in affected.values())
        and all(isinstance(details.get(field), list) for field in list_fields)
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
        and example.get("schema") == "dev-flow-driver-result/v1"
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
        and "V6" in guidance
        and _is_single_repository_guidance(guidance),
        errors,
        "follow-dev-flow agent metadata is not V6 single-repository guidance",
    )
    _check(
        default_prompt is not None and "$follow-dev-flow" in default_prompt,
        errors,
        "follow-dev-flow default_prompt does not invoke $follow-dev-flow",
    )
    _check(
        STALE_MAIN_AGENT_GUIDANCE.search(guidance) is None,
        errors,
        "follow-dev-flow agent metadata contains a stale generation or "
        "multi-repository claim",
    )


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
            "V6" in str(interface.get("longDescription", "")),
            errors,
            "plugin interface does not describe V6",
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
        isinstance(manifest_version, str)
        and SEMVER_V6.fullmatch(manifest_version) is not None,
        errors,
        "plugin version is not V6 with one Codex cachebuster",
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
        definition.schema == SCHEMA_V2
        and definition.version == WORKFLOW_VERSION
        and definition.adapter_identity == WORKFLOW_V2_ADAPTER_IDENTITY,
        errors,
        prefix + " is not an official workflow-v2 definition",
    )
    expected_identity = workflow_identity(
        selector,
        definition.document,
        WORKFLOW_V2_ADAPTER_IDENTITY,
    )
    _check(
        definition.identity == expected_identity
        and SHA256.fullmatch(definition.identity) is not None,
        errors,
        prefix + " identity is invalid",
    )
    cancel = definition.cancel_contract
    _check(
        cancel is not None
        and cancel.target_node in definition.terminal_nodes
        and cancel.target_status == "CANCELLED",
        errors,
        prefix + " does not expose shared cancellation",
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
    cancel_target = None if cancel is None else cancel.target_node
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
                "V6",
                "dev-flow-delivery-contract/v1",
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
                "openspec-tasks-v1",
                "reported",
            )
            + tuple(WORKFLOW_IDS),
            errors,
            "follow-dev-flow Skill is missing V6 delivery guidance",
        )
        _require_any(
            document,
            ("single-repository", "single repository", "单个 Git 仓库", "单仓库"),
            errors,
            "follow-dev-flow Skill does not state the repository boundary",
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
            ("baseline", "current", "project ID", "phase", "source", "degraded"),
            errors,
            "analyze-change-impact Skill is missing V6 graph evidence guidance",
        )
        _validate_impact_skill_driver_envelope(impact, errors)
    review_path = root / "skills" / "review-dev-flow-change" / "SKILL.md"
    if review_path.is_file():
        review = review_path.read_text(encoding="utf-8")
        _require_tokens(
            review,
            ("V6", "independent", "exact", "snapshot", "digest"),
            errors,
            "review-dev-flow-change Skill is missing V6 review guidance",
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
                "V6",
                "delivery contract",
                "bounded",
                "rework",
                "OpenSpec",
                "codebase-memory",
                "independent-review",
                "Delivery Dossier",
                "V5",
                "upgrade",
                "rollback",
            )
            + catalog_tokens,
            errors,
            "README.md is missing Stage 1 or V5 compatibility guidance",
        )
    chinese_path = root / "README_CN.md"
    if chinese_path.is_file():
        chinese = chinese_path.read_text(encoding="utf-8")
        _require_tokens(
            chinese,
            (
                "V6",
                "交付契约",
                "有界",
                "返工",
                "OpenSpec",
                "codebase-memory",
                "independent-review",
                "V5",
                "升级",
                "回滚",
            )
            + catalog_tokens,
            errors,
            "README_CN.md 缺少阶段 1 或 V5 兼容性说明",
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
            ("<PLUGIN_DATA>/v6", "<PLUGIN_DATA>/v5", "V5", "upgrade", "rollback"),
            errors,
            "INSTALL.md is missing the V6/V5 upgrade and rollback boundary",
        )
    architecture_path = root / "ARCHITECTURE.md"
    if architecture_path.is_file():
        architecture = architecture_path.read_text(encoding="utf-8")
        _require_tokens(
            architecture,
            (
                "V6",
                AGENT_PROTOCOL_SCHEMA,
                "dev-flow-record/v1",
                "dev-flow-artifact/v1",
                "Delivery Dossier",
            ),
            errors,
            "ARCHITECTURE.md is missing V6 identity or dossier guidance",
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
        retained_v5 = plugin_data / "v5" / "tasks" / "retained" / "state.json"
        retained_v5.parent.mkdir(parents=True)
        retained_payload = '{"schema_version":5}\n'
        retained_v5.write_text(retained_payload, encoding="utf-8")
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
            tokens[2:] == ["--data-dir", str((plugin_data / "v6").resolve())],
            errors,
            "Hook locator does not isolate V6 plugin data",
        )
        _check(
            "Dev Flow V6" in context and "$follow-dev-flow" in context,
            errors,
            "Hook does not inject V6 Skill guidance",
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
            retained_v5.read_text(encoding="utf-8") == retained_payload,
            errors,
            "V6 Hook modified or loaded the retained V5 data fixture",
        )


def _validate_current_candidate(root: Path) -> dict:
    errors: list[str] = []
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
    _check(
        WORKFLOW_VERSION == 6
        and PLUGIN_DATA_NAMESPACE == "v6"
        and AGENT_PROTOCOL_SCHEMA == "dev-flow-agent-v2",
        errors,
        "product generation, data namespace, or agent protocol is not V6",
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
        _check("V6" in source, errors, relative + " does not identify V6")
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
    hook_source_path = runtime_root / "hook.py"
    if hook_source_path.is_file():
        hook_source = hook_source_path.read_text(encoding="utf-8")
        _check(
            'os.environ.get("PLUGIN_DATA")' in hook_source
            and "PLUGIN_DATA_NAMESPACE" in hook_source
            and "Dev Flow V6" in hook_source
            and "$follow-dev-flow" in hook_source,
            errors,
            "Hook does not honor the V6 PLUGIN_DATA and Skill guidance contract",
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
    selector_pattern = "|".join(re.escape(item) for item in safe_catalog)
    stale_selector = re.compile(
        r"\b(?:{})@[45]\b".format(selector_pattern or r"(?!)")
    )
    for relative in PUBLIC_TEXT:
        path = root / relative
        if path.is_file():
            _check(
                stale_selector.search(path.read_text(encoding="utf-8")) is None,
                errors,
                "stale public workflow selector remains: " + relative,
            )
    _validate_skill_guidance(root, errors)
    _validate_main_skill_agent(root, errors)
    _validate_public_docs(root, errors)
    _hook_locator_smoke(root, errors)
    return {
        "ok": not errors,
        "platform": "macOS-current-host",
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
