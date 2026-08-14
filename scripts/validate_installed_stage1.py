#!/usr/bin/env python3
"""Validate an installed Dev Flow MCP runtime through its real STDIO launcher.

The runner is deliberately an MCP client, not a Controller test helper.  The
server process is always created from the launcher supplied by the installer,
and the workflow executor below uses only the public eleven-tool catalog.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterator, Mapping, Sequence
import uuid

from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


EXPECTED_TOOLS = (
    "dev_flow_apply_action",
    "dev_flow_cancel_task",
    "dev_flow_dispose_finding",
    "dev_flow_find_tasks_for_path",
    "dev_flow_get_next_action",
    "dev_flow_get_task",
    "dev_flow_list_tasks",
    "dev_flow_record_decision",
    "dev_flow_revise_contract",
    "dev_flow_server_info",
    "dev_flow_start_task",
)
OFFICIAL_WORKFLOWS = (
    "bugfix",
    "feature",
    "full",
    "investigation",
    "lite",
    "refactor",
)
EXPECTED_OBLIGATIONS = {
    "bugfix": {"repository-check", "independent-review"},
    "feature": {"repository-check"},
    "full": {"repository-check", "documentation-check", "independent-review"},
    "investigation": {"manual-evidence"},
    "lite": {"repository-check"},
    "refactor": {"repository-check", "independent-review"},
}
EXPECTED_ALLOWANCE = {
    "bugfix": 2,
    "feature": 2,
    "full": 3,
    "investigation": 2,
    "lite": 2,
    "refactor": 2,
}
EVIDENCE_SCHEMA = "dev-flow-mcp-installed-evidence/1.0.0"
INSTALLED_SKILL_FILES = (
    "skills/dev-flow/SKILL.md",
    "skills/dev-flow/agents/openai.yaml",
    "skills/dev-flow/references/activation-and-routing.md",
)
EXPECTED_SKILL_AGENT = """interface:
  display_name: "Dev Flow"
  short_description: "Drive resumable repository work through Dev Flow"
  default_prompt: "Use $dev-flow to start or resume this repository task through the authoritative Dev Flow Controller."
policy:
  allow_implicit_invocation: true
"""
RESULT_SCHEMA = "dev-flow-mcp-result/1.0.0"
ACTION_SCHEMA = "dev-flow-mcp-action/1.0.0"
DOSSIER_SCHEMA = "dev-flow-delivery-dossier/0.4.0"
DRIVER_RESULT_SCHEMA = "dev-flow-driver-result/0.4.0"
TASK_CHANGE_CLAIMS_SCHEMA = "dev-flow-task-change-claims/0.4.0"
CONTRACT_SCHEMA = "dev-flow-delivery-contract/0.4.0"
FINDING_SCHEMA = "dev-flow-review-finding/0.4.0"
FINDING_DISPOSITION_SCHEMA = "dev-flow-finding-disposition/0.4.0"
OPENSPEC_TASKS_NORMALIZER = "openspec-tasks/0.4.0"


class AcceptanceFailure(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _exception_messages(error: BaseException) -> list[str]:
    nested = getattr(error, "exceptions", ())
    if nested:
        messages = [
            message
            for item in nested
            for message in _exception_messages(item)
        ]
        if messages:
            return messages
    message = str(error)
    return [message if message else error.__class__.__name__]


def _finding_template(body: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint = hashlib.sha256(
        FINDING_SCHEMA.encode("ascii") + b"\0" + _json(body).encode("utf-8")
    ).hexdigest()
    return {
        **body,
        "finding_id": "finding-{}".format(fingerprint[:16]),
        "fingerprint": fingerprint,
    }


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        if path.is_symlink():
            digest.update(b"L" + path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            digest.update(b"F" + path.read_bytes())
        elif path.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def _installed_skill(plugin_root: Path) -> dict[str, Any]:
    resolved_root = plugin_root.resolve(strict=True)
    assets: dict[str, Path] = {}
    for relative in INSTALLED_SKILL_FILES:
        path = plugin_root / relative
        _require(path.is_file(), "installed plugin is missing " + relative)
        _require(not path.is_symlink(), "installed Skill asset is a symlink: " + relative)
        resolved = path.resolve(strict=True)
        _require(
            resolved.is_relative_to(resolved_root),
            "installed Skill asset escapes the plugin root: " + relative,
        )
        assets[relative] = path

    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    registration_path = plugin_root / ".mcp.json"
    _require(manifest_path.is_file(), "installed plugin manifest is missing")
    _require(registration_path.is_file(), "installed MCP registration is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    _require(
        isinstance(manifest, dict)
        and manifest.get("skills") == "./skills/"
        and manifest.get("mcpServers") == "./.mcp.json"
        and "hooks" not in manifest,
        "installed plugin manifest does not register the canonical Skill and MCP companions",
    )
    _require(
        registration
        == {
            "mcpServers": {
                "dev-flow": {"command": "dev-flow-mcp", "args": ["--stdio"]}
            }
        },
        "installed plugin MCP registration is invalid",
    )

    skill_document = assets["skills/dev-flow/SKILL.md"].read_text(encoding="utf-8")
    frontmatter = re.match(
        r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)",
        skill_document,
        re.DOTALL,
    )
    _require(frontmatter is not None, "installed dev-flow Skill frontmatter is invalid")
    frontmatter_lines = [
        line.strip()
        for line in frontmatter.group("body").splitlines()
        if line.strip()
    ]
    _require(
        len(frontmatter_lines) == 2
        and frontmatter_lines[0] == "name: dev-flow"
        and frontmatter_lines[1].startswith("description: ")
        and "$dev-flow" in frontmatter_lines[1]
        and "bundled dev-flow MCP" in frontmatter_lines[1],
        "installed dev-flow Skill identity or activation description is invalid",
    )
    _require(
        all(
            token in skill_document
            for token in (
                "dev_flow_server_info",
                "dev_flow_find_tasks_for_path",
                "dev_flow_get_next_action",
                "dev_flow_apply_action",
                "sole task-state writer",
            )
        ),
        "installed dev-flow Skill routing or authority guidance is incomplete",
    )

    agent_document = assets["skills/dev-flow/agents/openai.yaml"].read_text(
        encoding="utf-8"
    )
    _require(
        agent_document.replace("\r\n", "\n") == EXPECTED_SKILL_AGENT,
        "installed dev-flow Skill agent metadata is invalid",
    )
    routing_document = assets[
        "skills/dev-flow/references/activation-and-routing.md"
    ].read_text(encoding="utf-8")
    _require(
        all(
            token in routing_document
            for token in (
                "No matching active task",
                "One compatible active task",
                "Several plausible tasks",
                "Inventory unavailable or inconsistent",
                "dev_flow_get_task",
            )
        ),
        "installed dev-flow Skill routing reference is incomplete",
    )

    return {
        "name": "dev-flow",
        "path": "skills/dev-flow",
        "explicit_invocation": "$dev-flow",
        "implicit_invocation": True,
        "mcp_server": "dev-flow",
        "mcp_transport": "stdio",
        "files": {
            relative: hashlib.sha256(path.read_bytes()).hexdigest()
            for relative, path in assets.items()
        },
    }


def _make_repository(root: Path, name: str) -> Path:
    repository = root / name
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "installed@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Installed MCP"],
        cwd=repository,
        check=True,
    )
    (repository / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repository, check=True)
    return repository


def _request_uuid(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("mcp-"):
        return False
    try:
        parsed = uuid.UUID(value[4:])
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value[4:]


def _structured(result: Any, tool: str, *, expect_error: bool = False) -> dict[str, Any]:
    value = result.structured_content
    if not isinstance(value, dict):
        summaries = []
        for item in getattr(result, "content", ()):
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                summaries.append(text.strip().encode("utf-8")[:512].decode("utf-8", errors="ignore"))
        suffix = ": " + " | ".join(summaries) if summaries else ""
        raise AcceptanceFailure(
            "{} omitted structured content (is_error={!r}){}".format(
                tool, getattr(result, "is_error", None), suffix
            )
        )
    _require(
        set(value) == {"schema", "ok", "tool", "request_id", "result", "error"},
        tool + " returned a non-canonical result envelope",
    )
    _require(value.get("schema") == RESULT_SCHEMA, tool + " returned the wrong envelope")
    _require(value.get("tool") == tool, tool + " returned the wrong tool identity")
    _require(_request_uuid(value.get("request_id")), tool + " omitted canonical mcp-UUID request_id")
    if expect_error:
        _require(result.is_error is True and value.get("ok") is False, tool + " did not fail")
        _require(value.get("result") is None and isinstance(value.get("error"), dict), tool + " error fields are invalid")
    else:
        if result.is_error is not False or value.get("ok") is not True:
            error = value.get("error")
            code = error.get("code") if isinstance(error, Mapping) else "UNKNOWN"
            message = error.get("message") if isinstance(error, Mapping) else "tool failed"
            details = error.get("details") if isinstance(error, Mapping) else None
            outcome = ""
            if isinstance(details, Mapping) and (
                "claimed" in details or "derived" in details
            ):
                outcome = " (claimed={!r}, derived={!r})".format(
                    details.get("claimed"), details.get("derived")
                )
            raise AcceptanceFailure(
                "{} failed [{}]: {}{}".format(tool, code, message, outcome)
            )
        _require(isinstance(value.get("result"), dict) and value.get("error") is None, tool + " success fields are invalid")
    return value


def _result(result: Any, tool: str) -> dict[str, Any]:
    envelope = _structured(result, tool)
    return envelope["result"]


def _launcher_parameters(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    data_dir: Path,
) -> StdioServerParameters:
    return StdioServerParameters(
        command=launcher,
        args=[*launcher_args, "--stdio", "--data-dir", str(data_dir)],
        cwd=plugin_root,
    )


def _disconnect_proxy_main(arguments: Sequence[str]) -> int:
    """Forward one STDIO session and drop the first apply response after commit."""

    encoded_target = os.environ.get("DEV_FLOW_DISCONNECT_PROXY_TARGET")
    try:
        target = json.loads(encoded_target or "null")
    except ValueError as exc:
        raise SystemExit("disconnect proxy target is invalid JSON") from exc
    if (
        not isinstance(target, list)
        or not target
        or any(not isinstance(item, str) or not item for item in target)
    ):
        raise SystemExit("disconnect proxy target must be a non-empty string array")
    child = subprocess.Popen(
        [*target, *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    assert child.stderr is not None
    pending: dict[str, object] = {"apply_id": None}

    def forward_input() -> None:
        buffered = b""
        try:
            while True:
                chunk = os.read(sys.stdin.fileno(), 8192)
                if not chunk:
                    break
                buffered += chunk
                lines = buffered.split(b"\n")
                buffered = lines.pop()
                for line in lines:
                    line += b"\n"
                    try:
                        message = json.loads(line)
                    except ValueError:
                        message = None
                    if (
                        isinstance(message, Mapping)
                        and message.get("method") == "tools/call"
                        and isinstance(message.get("params"), Mapping)
                        and message["params"].get("name") == "dev_flow_apply_action"
                    ):
                        pending["apply_id"] = message.get("id")
                try:
                    os.write(child.stdin.fileno(), chunk)
                except BrokenPipeError:
                    break
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                child.stdin.close()
            except OSError:
                pass

    def forward_stderr() -> None:
        try:
            for chunk in iter(lambda: os.read(child.stderr.fileno(), 8192), b""):
                os.write(sys.stderr.fileno(), chunk)
        except OSError:
            pass

    input_thread = threading.Thread(target=forward_input, daemon=True)
    stderr_thread = threading.Thread(target=forward_stderr, daemon=True)
    input_thread.start()
    stderr_thread.start()
    suppressed = False
    try:
        for line in child.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                message = None
            if (
                pending["apply_id"] is not None
                and isinstance(message, Mapping)
                and message.get("id") == pending["apply_id"]
            ):
                suppressed = True
                break
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
    if not suppressed:
        raise SystemExit("disconnect proxy ended before observing an apply response")
    return 0


async def _initialize(session: ClientSession) -> dict[str, Any]:
    initialized = await session.initialize()
    _require(initialized.server_info.name == "dev-flow", "installed server name is invalid")
    _require(initialized.server_info.version == "0.6.10", "installed release is not 0.6.10")
    _require(initialized.capabilities.tools is not None, "tools capability is absent")
    _require(initialized.capabilities.resources is None, "resources capability must be absent")
    _require(initialized.capabilities.prompts is None, "prompts capability must be absent")
    _require(initialized.capabilities.tasks is None, "task augmentation must be absent")
    instructions = initialized.instructions or ""
    _require(len(instructions.encode("utf-8")) <= 4 * 1024, "server instructions exceed 4 KiB")
    first = instructions.encode("utf-8")[:512].decode("utf-8", errors="ignore")
    sequence_tokens = (
        ("dev_flow_find_tasks_for_path", "discover tasks"),
        ("dev_flow_get_next_action", "current action"),
        ("dev_flow_apply_action", "Submit mutations"),
    )
    for exact, semantic in sequence_tokens:
        _require(
            exact in first or semantic in first,
            "server instructions omit the bounded discovery sequence",
        )

    catalog = await session.list_tools()
    names = tuple(sorted(tool.name for tool in catalog.tools))
    _require(names == EXPECTED_TOOLS, "installed tool catalog is not exact")
    for tool in catalog.tools:
        _require(isinstance(tool.input_schema, dict), tool.name + " omitted input schema")
        _require(isinstance(tool.output_schema, dict), tool.name + " omitted output schema")
        execution = getattr(tool, "execution", None)
        _require(
            execution is not None and getattr(execution, "task_support", None) == "forbidden",
            tool.name + " permits MCP task augmentation",
        )
    return {
        "server": initialized.server_info.name,
        "release": initialized.server_info.version,
        "instructions_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "catalog": list(names),
    }


async def _smoke(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    scratch: Path,
) -> dict[str, Any]:
    data_dir = scratch / "smoke data 雪's"
    repository = _make_repository(scratch, "smoke repository")
    parameters = _launcher_parameters(launcher, launcher_args, plugin_root, data_dir)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            identity = await _initialize(session)
            info = _result(await session.call_tool("dev_flow_server_info", {}), "dev_flow_server_info")
            _require(info.get("model_version") == "0.4.0", "persisted model changed")
            _require(str(data_dir) not in _json(info), "server-info exposed the data root")

            empty = _result(
                await session.call_tool("dev_flow_list_tasks", {"limit": 1}),
                "dev_flow_list_tasks",
            )
            _require(empty.get("tasks") == [], "isolated installed data root is not empty")

            started = _result(
                await session.call_tool(
                    "dev_flow_start_task",
                    {
                        "requirement": "isolated installed MCP mutation smoke",
                        "workflow": "lite",
                        "repositories": [str(repository)],
                        "task_id": "installed-mcp-smoke",
                    },
                ),
                "dev_flow_start_task",
            )
            _require(started.get("revision") == 0, "installed mutation smoke did not start")
            cancelled = _result(
                await session.call_tool(
                    "dev_flow_cancel_task",
                    {"task_id": "installed-mcp-smoke", "reason": "installed smoke complete"},
                ),
                "dev_flow_cancel_task",
            )
            _require(cancelled.get("receipt", {}).get("status") == "CANCELLED", "installed mutation smoke did not persist")
            detail = _result(
                await session.call_tool("dev_flow_get_task", {"task_id": "installed-mcp-smoke"}),
                "dev_flow_get_task",
            )
            _require(detail.get("task", {}).get("status") == "CANCELLED", "installed cancellation was not stored")
            _require(str(data_dir) not in _json(detail), "normal installed result exposed the data root")
    return {
        "initialize": identity,
        "read_smoke": True,
        "mutation_smoke": True,
        "terminal_status": "CANCELLED",
    }


async def _candidate_smoke(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    scratch: Path,
) -> dict[str, Any]:
    """Prove the staged Skill and MCP without requiring a Git repository.

    End-user artifact installation intentionally has no Git prerequisite.  The
    fuller installed acceptance journey still exercises task mutations against
    real repositories, while this candidate-only gate verifies the exact
    plugin, server identity, catalog, isolated data root, and read path.
    """

    data_dir = scratch / "candidate data 雪's"
    parameters = _launcher_parameters(launcher, launcher_args, plugin_root, data_dir)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            identity = await _initialize(session)
            info = _result(
                await session.call_tool("dev_flow_server_info", {}),
                "dev_flow_server_info",
            )
            _require(info.get("model_version") == "0.4.0", "persisted model changed")
            _require(str(data_dir) not in _json(info), "server-info exposed the data root")
            empty = _result(
                await session.call_tool("dev_flow_list_tasks", {"limit": 1}),
                "dev_flow_list_tasks",
            )
            _require(empty.get("tasks") == [], "isolated candidate data root is not empty")
    return {
        "initialize": identity,
        "read_smoke": True,
        "candidate_smoke": True,
        "mutation_smoke": False,
        "terminal_status": None,
    }


class _ReadAudit:
    """Process-local executor guard; server imports occur in a separate process."""

    def __init__(self, plugin_root: Path, data_dir: Path):
        self.plugin_root = plugin_root.resolve()
        self.data_dir = data_dir.resolve()
        self.active = False
        self.violations: list[str] = []

    def _forbidden(self, path: Path) -> bool:
        try:
            relative = path.resolve().relative_to(self.plugin_root)
        except (OSError, ValueError):
            relative = None
        if relative is not None:
            text = relative.as_posix()
            return (
                text.startswith("skills/")
                or text.startswith("hooks/")
                or text in {"scripts/dev_flow.py", "scripts/dev_flow_mcp.py"}
                or text.startswith("src/dev_flow_orchestrator/mcp/")
            )
        try:
            path.resolve().relative_to(self.data_dir)
        except (OSError, ValueError):
            return False
        return True

    def hook(self, event: str, arguments: tuple[object, ...]) -> None:
        if not self.active or event != "open" or not arguments:
            return
        raw = arguments[0]
        mode = arguments[1] if len(arguments) > 1 else "r"
        if not isinstance(raw, (str, bytes, os.PathLike)):
            return
        mode_text = str(mode)
        if mode_text and not any(token in mode_text for token in ("r", "+")):
            return
        try:
            path = Path(os.fsdecode(raw))
        except (TypeError, ValueError):
            return
        if self._forbidden(path):
            self.violations.append(str(path))
            raise AcceptanceFailure("executor attempted a forbidden package/state source read")


@contextmanager
def _instrument_executor(audit: _ReadAudit) -> Iterator[None]:
    audit.active = True
    try:
        yield
    finally:
        audit.active = False


def _repositories(current: Mapping[str, Any]) -> list[dict[str, Any]]:
    repository_set = current.get("repository_set")
    repositories = repository_set.get("repositories") if isinstance(repository_set, Mapping) else None
    _require(isinstance(repositories, list) and repositories, "current action lost repository membership")
    return repositories


def _criterion_ids(current: Mapping[str, Any]) -> list[str]:
    contract = current.get("contract")
    values = contract.get("criterion_ids") if isinstance(contract, Mapping) else None
    _require(isinstance(values, list) and values, "current action lost contract criteria")
    return [str(value) for value in values]


def _change_repositories(
    current: Mapping[str, Any],
    relative_path: str,
    marker: str,
    classification: str,
) -> dict[str, Any]:
    claims = []
    criteria = _criterion_ids(current)
    for repository in _repositories(current):
        path = Path(str(repository["path"])) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(marker + "\n")
        claims.append(
            {
                "repository_id": repository["id"],
                "path": relative_path,
                "classification": classification,
                "criterion_ids": criteria,
                "purpose": "Installed MCP journey evidence for the current action",
            }
        )
    return {"schema": TASK_CHANGE_CLAIMS_SCHEMA, "claims": claims}


def _restore_impact_gap_fixture_sources(
    repositories: Sequence[Path],
    task_id: str,
    scenario: Mapping[str, Any],
) -> list[str]:
    """Restore only exact untracked files generated by this isolated journey."""

    relative_paths = [
        str(scenario["implementation_path"]),
        "journey-documentation.md",
    ]
    if scenario.get("openspec"):
        prefix = "openspec/changes/{}".format(task_id)
        relative_paths.extend((prefix + "/proposal.md", prefix + "/tasks.md"))
    else:
        relative_paths.append("journey-plan.md")
    restored: list[str] = []
    for repository in repositories:
        repository_root = repository.resolve()
        for relative in relative_paths:
            path = repository / relative
            try:
                path.resolve(strict=False).relative_to(repository_root)
            except ValueError as exc:
                raise AcceptanceFailure("impact-gap restore path escaped its fixture") from exc
            status = subprocess.run(
                ["git", "-C", str(repository), "status", "--porcelain", "--", relative],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            _require(
                status == "?? " + relative and path.is_file() and not path.is_symlink(),
                "impact-gap restore target is not an exact generated untracked file",
            )
            path.unlink()
            restored.append(relative)
        for parent in sorted(
            {((repository / relative).parent) for relative in relative_paths},
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            while parent != repository_root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    return sorted(set(restored), key=lambda item: item.encode("utf-8"))


def _impact_manifest(
    current: Mapping[str, Any],
    *,
    triggered: bool = False,
    extra_paths: Sequence[str] = (),
    confidence: str = "source-confirmed",
) -> dict[str, Any]:
    criteria = _criterion_ids(current)
    paths = tuple(dict.fromkeys(("tracked.txt", *extra_paths)))
    return {
        "confidence": confidence,
        "entries": [
            {
                "repository_id": repository["id"],
                "path": path,
                "symbol": None,
                "criterion_ids": criteria,
            }
            for repository in _repositories(current)
            for path in paths
        ],
        "edges": [],
        "risk_triggers": ["security"] if triggered else [],
        "public_behavior": False,
        "documentation_required": False,
        "manual_evidence_required": False,
        "executable_reproduction_required": False,
        "overflow": False,
        "limitations": [],
    }


def _review(
    current: Mapping[str, Any],
    *,
    reviewer_available: bool = True,
    independent: bool = True,
    reviewer_digest: str = "a" * 64,
    findings: Sequence[Mapping[str, Any]] = (),
    claimed_outcome: str = "approved",
) -> dict[str, Any]:
    action = current.get("action")
    review = action.get("review_contract") if isinstance(action, Mapping) else None
    _require(isinstance(review, Mapping), "independent review lost its current bindings")
    return {
        "reviewer_available": reviewer_available,
        "independent": independent,
        "reviewer_digest": reviewer_digest,
        "review_scope_digest": review["review_scope_digest"],
        "guidance_digest": review["guidance_digest"],
        "workspace_digest": review["workspace_digest"],
        "findings": [dict(item) for item in findings],
        "claimed_outcome": claimed_outcome,
    }


def _review_finding(
    current: Mapping[str, Any],
    *,
    causal_relation: str,
    path: str,
    reviewer_digest: str,
    evidence_label: str,
) -> dict[str, Any]:
    action = current.get("action")
    _require(isinstance(action, Mapping), "review finding lost its action")
    review = action.get("review_contract")
    assurance = action.get("assurance")
    obligation = action.get("current_obligation")
    change_slice = action.get("task_change_slice")
    _require(isinstance(review, Mapping), "review finding lost its bindings")
    _require(isinstance(assurance, Mapping), "review finding lost its plan")
    _require(isinstance(obligation, Mapping), "review finding lost its obligation")
    _require(isinstance(change_slice, list) and change_slice, "review finding lost its task slice")
    selected = next(
        (
            item
            for item in change_slice
            if isinstance(item, Mapping) and item.get("path") == path
        ),
        change_slice[0],
    )
    repository_id = selected.get("repository_id")
    selected_path = str(selected.get("path"))
    source_confirmed = causal_relation != "unknown"
    causal_entries = (
        [{"repository_id": repository_id, "path": selected_path}]
        if causal_relation in {"introduced", "affected"}
        else []
    )
    causal_path = (
        [
            {
                "kind": "source-flow",
                "from": "task change manifest",
                "to": "affected behavior",
                "evidence": evidence_label,
                "source_confirmed": True,
            }
        ]
        if causal_relation == "affected"
        else []
    )
    body = {
        "schema": FINDING_SCHEMA,
        "severity": "high",
        "blocking": True,
        "causal_relation": causal_relation,
        "criterion_ids": _criterion_ids(current),
        "repository_id": repository_id,
        "path": selected_path,
        "symbol": None,
        "location_label": None,
        "evidence": [
            {
                "kind": "source",
                "reference": selected_path,
                "summary": evidence_label,
                "source_confirmed": source_confirmed,
            }
        ],
        "causal_manifest_entries": causal_entries,
        "causal_path": causal_path,
        "smallest_sufficient_resolution": (
            "Authorize this exact bounded residual risk"
            if causal_relation == "unknown"
            else "Apply bounded source rework"
        ),
        "reviewer_assurance": "independent",
        "limitations": (
            ["Causal path remains unknown"]
            if causal_relation == "unknown"
            else []
        ),
        "task_id": current["task"]["task_id"],
        "contract_digest": review["contract_digest"],
        "plan_digest": assurance["plan_digest"],
        "manifest_digest": review["manifest_digest"],
        "review_scope_digest": review["review_scope_digest"],
        "guidance_digest": review["guidance_digest"],
        "reviewer_digest": reviewer_digest,
        "workspace_digest": review["workspace_digest"],
    }
    return _finding_template(body)


def _payload_for_action(
    current: Mapping[str, Any],
    workflow: str,
    sequence: int,
    scenario: Mapping[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    action = current.get("action")
    _require(isinstance(action, Mapping), "non-terminal task omitted its current action")
    action_id = action.get("id")
    if action_id == "task.preflight":
        return {}, None
    if action_id == "impact.record":
        impact_count = int(state.get("impact_count", 0))
        extra_paths = (
            (str(scenario["implementation_path"]),)
            if scenario.get("review_mode") == "impact-gap" and impact_count > 0
            else ()
        )
        payload: dict[str, Any] = {
            "summary": "Installed MCP source-confirmed impact",
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": str(scenario.get("impact_driver_status", "available")),
            },
        }
        artifact = action.get("context", {}).get("artifact")
        if isinstance(artifact, Mapping) and artifact.get("type") == "impact-report":
            payload["impact_manifest"] = _impact_manifest(
                current,
                triggered=bool(scenario.get("triggered")),
                extra_paths=extra_paths,
            )
        state["impact_count"] = impact_count + 1
        return payload, None
    if action_id == "plan.record":
        if scenario.get("openspec"):
            prefix = "openspec/changes/{}".format(current["task"]["task_id"])
            proposal = prefix + "/proposal.md"
            tasks = prefix + "/tasks.md"
            proposal_claims = _change_repositories(
                current,
                proposal,
                "# Installed MCP OpenSpec proposal {}".format(sequence),
                "documentation",
            )
            task_claims = _change_repositories(
                current,
                tasks,
                "- [ ] installed MCP task {}".format(sequence),
                "documentation",
            )
            claims = {
                "schema": TASK_CHANGE_CLAIMS_SCHEMA,
                "claims": [
                    *proposal_claims["claims"],
                    *task_claims["claims"],
                ],
            }
            resources = {
                "items": [
                    item
                    for repository in _repositories(current)
                    for item in (
                        {
                            "repository_id": repository["id"],
                            "path": proposal,
                            "role": "governing",
                            "normalizer": "none",
                        },
                        {
                            "repository_id": repository["id"],
                            "path": tasks,
                            "role": "reported",
                            "normalizer": "none",
                        },
                        {
                            "repository_id": repository["id"],
                            "path": tasks,
                            "role": "governing",
                            "normalizer": OPENSPEC_TASKS_NORMALIZER,
                        },
                    )
                ]
            }
            state["openspec_tasks_path"] = tasks
            relative = proposal
        else:
            relative = "journey-plan.md"
            claims = _change_repositories(
                current,
                relative,
                "installed plan {}".format(sequence),
                "documentation",
            )
            resources = {
                "items": [
                    {
                        "repository_id": repository["id"],
                        "path": relative,
                        "role": "governing",
                        "normalizer": "none",
                    }
                    for repository in _repositories(current)
                ]
            }
        return {
            "summary": "Installed MCP repository-backed plan",
            "resources": resources,
            "driver_result": {
                "schema": DRIVER_RESULT_SCHEMA,
                "status": str(scenario.get("plan_driver_status", "degraded")),
            },
            "ownership_claims": claims,
        }, relative
    if action_id == "implementation.record":
        relative = str(scenario.get("implementation_path", "tracked.txt"))
        implementation_count = int(state.get("implementation_count", 0))
        state["implementation_count"] = implementation_count + 1
        if scenario.get("review_mode") == "impact-gap" and implementation_count > 0:
            state["implementation_reexecuted"] = True
        return {
            "summary": "Installed MCP implementation",
            "ownership_claims": _change_repositories(
                current,
                relative,
                "installed implementation {}".format(sequence),
                "implementation",
            ),
        }, relative
    if action_id == "documentation.record":
        relative = "journey-documentation.md"
        return {
            "summary": "Installed MCP documentation",
            "ownership_claims": _change_repositories(
                current,
                relative,
                "installed documentation {}".format(sequence),
                "documentation",
            ),
        }, relative
    if action_id in {"investigation.record", "investigation.rework.record"}:
        return {
            "summary": "Installed MCP investigation evidence",
            "evidence": {"observations": ["bounded installed MCP observation"]},
        }, None
    if action_id in {"verification.rework.record"}:
        relative = "tracked.txt"
        return {
            "summary": "Installed MCP bounded verification rework",
            "ownership_claims": _change_repositories(
                current,
                relative,
                "installed verification rework {}".format(sequence),
                "implementation",
            ),
        }, relative
    if action_id == "assurance.execute":
        obligation = action.get("current_obligation")
        _require(isinstance(obligation, Mapping), "assurance action omitted its obligation")
        evidence_kind = "manual" if obligation.get("kind") in {"manual-evidence", "documentation-check"} else "command"
        result: dict[str, Any] = {
            "obligation_id": obligation["obligation_id"],
            "passed": True,
            "evidence": [
                {
                    "kind": evidence_kind,
                    "reference": "installed-mcp-{}".format(obligation["kind"]),
                    "summary": "Current installed obligation passed",
                }
            ],
            "limitations": [],
        }
        if obligation.get("kind") == "independent-review":
            mode = str(scenario.get("review_mode", "approved"))
            if mode != "approved" and not state.get("special_review_used"):
                state["special_review_used"] = True
                reviewer_digest = "c" * 64
                if mode == "unavailable-waived":
                    result["passed"] = False
                    result["evidence"] = []
                    result["review"] = _review(
                        current,
                        reviewer_available=False,
                        independent=False,
                        reviewer_digest=reviewer_digest,
                        claimed_outcome="unavailable",
                    )
                    state["pending_waiver"] = obligation["obligation_id"]
                elif mode == "introduced-affected-rework":
                    path = str(scenario.get("implementation_path", "tracked.txt"))
                    findings = [
                        _review_finding(
                            current,
                            causal_relation=relation,
                            path=path,
                            reviewer_digest=reviewer_digest,
                            evidence_label="Installed {} finding".format(relation),
                        )
                        for relation in ("introduced", "affected")
                    ]
                    result["passed"] = False
                    result["evidence"] = []
                    result["review"] = _review(
                        current,
                        reviewer_digest=reviewer_digest,
                        findings=findings,
                        claimed_outcome="changes-requested",
                    )
                    state["expected_rework"] = True
                    state["finding_relations"] = ["introduced", "affected"]
                elif mode in {"unknown-disposition", "impact-gap"}:
                    path = str(scenario.get("implementation_path", "tracked.txt"))
                    relation = "unknown" if mode == "unknown-disposition" else "affected"
                    finding = _review_finding(
                        current,
                        causal_relation=relation,
                        path=path,
                        reviewer_digest=reviewer_digest,
                        evidence_label="Installed {} triage finding".format(relation),
                    )
                    result["passed"] = False
                    result["evidence"] = []
                    result["limitations"] = (
                        ["Causal path remains unknown"] if relation == "unknown" else []
                    )
                    result["review"] = _review(
                        current,
                        reviewer_digest=reviewer_digest,
                        findings=(finding,),
                        claimed_outcome="triage-required",
                    )
                    state["triage_finding"] = finding
                    state["triage_plan_digest"] = action["assurance"]["plan_digest"]
                    state["expect_impact_replan"] = mode == "impact-gap"
                else:
                    raise AcceptanceFailure("unknown installed review scenario " + mode)
            else:
                result["review"] = _review(current)
        return {
            "summary": "Installed MCP assurance recorded",
            "assurance_result": result,
        }, None
    if isinstance(action_id, str) and action_id.startswith("delivery.finalize."):
        return {
            "summary": "Installed MCP workflow delivered",
            "remaining_risks": {},
            "handoff": "Installed MCP journey complete",
        }, None
    raise AcceptanceFailure("installed executor has no payload for action {!r}".format(action_id))


async def _complete_workflow(
    session: ClientSession,
    *,
    workflow: str,
    task_id: str,
    repositories: Sequence[Path],
    start: bool = True,
    scenario: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    scenario = dict(scenario or {})
    state: dict[str, Any] = {}
    if start:
        started = _result(
            await session.call_tool(
                "dev_flow_start_task",
                {
                    "requirement": "Installed MCP {} workflow journey".format(workflow),
                    "workflow": workflow,
                    "repositories": [str(path) for path in repositories],
                    "task_id": task_id,
                },
            ),
            "dev_flow_start_task",
        )
        _require(started.get("task_id") == task_id, "workflow start returned the wrong task")

    action_ids: list[str] = []
    obligation_kinds: list[str] = []
    allowances: list[int] = []
    assurance_authority: dict[str, Any] | None = None
    driver_observations: dict[str, Any] = {}
    final_current: dict[str, Any] | None = None
    for sequence in range(128):
        current = _result(
            await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
            "dev_flow_get_next_action",
        )
        _require(current.get("schema") == ACTION_SCHEMA, "current action schema changed")
        action = current.get("action")
        if action is None:
            final_current = current
            break
        action_id = action.get("id")
        _require(isinstance(action_id, str), "current action has no identity")
        if action.get("binding") is None:
            blocked = action.get("context", {}).get("blocked")
            blocked_code = blocked.get("code") if isinstance(blocked, Mapping) else None
            if (
                scenario.get("review_mode") == "impact-gap"
                and state.get("impact_observed_current") is True
                and action_id == "plan.record"
                and blocked_code == "AMBIENT_DRIFT"
            ):
                state["plan_blocked"] = blocked_code
                state["impact_gap_restored_paths"] = _restore_impact_gap_fixture_sources(
                    repositories,
                    task_id,
                    scenario,
                )
                state["restored_for_replan"] = True
                current = _result(
                    await session.call_tool(
                        "dev_flow_get_next_action", {"task_id": task_id}
                    ),
                    "dev_flow_get_next_action",
                )
                action = current.get("action")
                _require(
                    isinstance(action, Mapping)
                    and action.get("id") == "plan.record"
                    and isinstance(action.get("binding"), Mapping),
                    "restoring exact generated drift did not recover the plan binding",
                )
                action_id = "plan.record"
            else:
                raise AcceptanceFailure(
                    "task={} action={} is blocked with {}".format(
                        task_id, action_id, blocked_code or "UNKNOWN"
                    )
                )
        action_ids.append(action_id)
        guidance_text = _json(current.get("guidance", {})).casefold()
        driver = action.get("driver")
        if action_id == "impact.record" and isinstance(driver, Mapping):
            _require(driver.get("tool") == "codebase-memory", "impact lost codebase-memory driver")
            _require(
                "baseline" in guidance_text and "current" in guidance_text,
                "impact guidance lost current/baseline separation",
            )
            _require("fallback" in guidance_text, "impact guidance lost degraded fallback")
            driver_observations["codebase_memory"] = {
                "tool": driver.get("tool"),
                "status": scenario.get("impact_driver_status", "available"),
                "current_baseline_separated": True,
                "degraded_fallback_present": True,
            }
        if action_id == "plan.record" and isinstance(driver, Mapping):
            _require(driver.get("tool") == "openspec", "planning lost OpenSpec driver")
            _require(
                "source" in guidance_text and "fallback" in guidance_text,
                "planning guidance lost source confirmation or fallback",
            )
            driver_observations["openspec"] = {
                "tool": driver.get("tool"),
                "status": scenario.get("plan_driver_status", "degraded"),
                "source_producing": True,
                "governing_resources": True,
            }
        obligation = action.get("current_obligation")
        if isinstance(obligation, Mapping):
            obligation_kinds.append(str(obligation.get("kind")))
            allowance = obligation.get("allowance")
            if isinstance(allowance, int) and not isinstance(allowance, bool):
                allowances.append(allowance)
            assurance = action.get("assurance")
            if assurance_authority is None and isinstance(assurance, Mapping):
                budget = assurance.get("budget")
                _require(isinstance(budget, Mapping), "assurance budget is missing")
                used = budget.get("used")
                remaining = budget.get("remaining")
                _require(isinstance(used, Mapping) and isinstance(remaining, Mapping), "assurance ceilings are missing")
                ceilings = {
                    key: int(used.get(key, 0)) + int(remaining.get(key, 0))
                    for key in ("verification", "review", "rework", "total_action")
                }
                _require(ceilings["total_action"] <= 256, "assurance action ceiling exceeded")
                assurance_authority = {
                    "profile": assurance.get("profile"),
                    "plan_digest": assurance.get("plan_digest"),
                    "not_required": assurance.get("not_required"),
                    "ceilings": ceilings,
                }
                _require(assurance_authority["profile"] == workflow, "assurance profile changed")
        payload, _ = _payload_for_action(
            current,
            workflow,
            sequence,
            scenario,
            state,
        )
        try:
            applied = _result(
                await session.call_tool(
                    "dev_flow_apply_action",
                    {
                        "task_id": task_id,
                        "action_id": action_id,
                        "payload": payload,
                        "binding": action["binding"],
                    },
                ),
                "dev_flow_apply_action",
            )
        except AcceptanceFailure as exc:
            raise AcceptanceFailure(
                "{} at task={} action={}".format(exc, task_id, action_id)
            ) from exc
        _require(applied.get("receipt", {}).get("task_id") == task_id, "action receipt lost task identity")
        if (
            scenario.get("review_mode") == "impact-gap"
            and action_id == "impact.record"
            and state.get("impact_count", 0) >= 2
        ):
            manifest = payload.get("impact_manifest")
            entries = manifest.get("entries") if isinstance(manifest, Mapping) else None
            _require(
                isinstance(entries, list)
                and any(
                    isinstance(item, Mapping)
                    and item.get("path") == scenario.get("implementation_path")
                    for item in entries
                ),
                "re-planned impact did not observe the current gap path",
            )
            state["impact_observed_current"] = True
        if (
            action_id == "plan.record"
            and scenario.get("openspec_stale")
            and not state.get("openspec_stale_seen")
        ):
            tasks_path = state.get("openspec_tasks_path")
            _require(isinstance(tasks_path, str), "OpenSpec tasks resource was not recorded")
            originals: list[tuple[Path, str]] = []
            for repository in repositories:
                path = repository / tasks_path
                original = path.read_text(encoding="utf-8")
                originals.append((path, original))
                path.write_text(
                    original + "- [ ] semantically new installed MCP task\n",
                    encoding="utf-8",
                )
            stale = _result(
                await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
                "dev_flow_get_next_action",
            )
            stale_action = stale.get("action")
            blocked = (
                stale_action.get("context", {}).get("blocked")
                if isinstance(stale_action, Mapping)
                else None
            )
            _require(
                isinstance(stale_action, Mapping)
                and stale_action.get("binding") is None
                and isinstance(blocked, Mapping)
                and blocked.get("code") == "ARTIFACT_INPUT_MISSING",
                "semantic OpenSpec drift did not stale the governing plan",
            )
            for path, original in originals:
                path.write_text(original, encoding="utf-8")
            refreshed = _result(
                await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
                "dev_flow_get_next_action",
            )
            _require(
                isinstance(refreshed.get("action"), Mapping)
                and refreshed["action"].get("binding") is not None,
                "restored OpenSpec resource did not recover the exact binding",
            )
            state["openspec_stale_seen"] = True

        if state.pop("pending_waiver", None) is not None:
            waiver_subject = obligation["obligation_id"]
            waived = _result(
                await session.call_tool(
                    "dev_flow_record_decision",
                    {
                        "task_id": task_id,
                        "decision": {
                            "id": "installed-review-waiver",
                            "kind": "assurance-waiver",
                            "subject": waiver_subject,
                            "outcome": "waived",
                            "rationale": "Independent review is unavailable for this installed personal delivery",
                            "actor_label": "installed-task-owner",
                        },
                    },
                ),
                "dev_flow_record_decision",
            )
            _require(waived["receipt"]["task_id"] == task_id, "review waiver was not recorded")
            state["review_waived"] = True

        if state.pop("expected_rework", False):
            _require(
                applied.get("current", {}).get("task", {}).get("current_node")
                == "verification_rework",
                "introduced/affected findings did not route to bounded rework",
            )
            state["review_rework_seen"] = True

        if state.get("triage_finding") is not None and not state.get("triage_handled"):
            current_after = applied.get("current")
            _require(isinstance(current_after, Mapping), "triage mutation lost current state")
            if state.get("expect_impact_replan"):
                _require(
                    current_after.get("task", {}).get("current_node") == "impact",
                    "impact-gap finding did not route to impact re-planning",
                )
                state["impact_gap_replanned"] = True
            else:
                after_action = current_after.get("action")
                review_state = (
                    after_action.get("review_state")
                    if isinstance(after_action, Mapping)
                    else None
                )
                finding = state["triage_finding"]
                _require(isinstance(review_state, Mapping), "triage review digest is unavailable")
                disposition = {
                    "schema": FINDING_DISPOSITION_SCHEMA,
                    "kind": "accepted-risk",
                    "task_id": task_id,
                    "contract_digest": current_after["contract"]["digest"],
                    "plan_digest": state["triage_plan_digest"],
                    "review_digest": review_state["digest"],
                    "finding_fingerprint": finding["fingerprint"],
                    "actor": "installed-task-owner",
                    "rationale": "Accept this exact unresolved installed causal risk",
                    "expected_revision": current_after["task"]["revision"],
                    "next_contract": None,
                }
                forbidden = _structured(
                    await session.call_tool(
                        "dev_flow_dispose_finding",
                        {
                            "task_id": task_id,
                            "disposition": disposition,
                            "actor_authorized": False,
                        },
                    ),
                    "dev_flow_dispose_finding",
                    expect_error=True,
                )
                _require(
                    forbidden["error"].get("code") == "FINDING_DISPOSITION_FORBIDDEN",
                    "unauthorized finding disposition did not fail closed",
                )
                disposed = _result(
                    await session.call_tool(
                        "dev_flow_dispose_finding",
                        {
                            "task_id": task_id,
                            "disposition": disposition,
                            "actor_authorized": True,
                        },
                    ),
                    "dev_flow_dispose_finding",
                )
                _require(disposed["receipt"]["task_id"] == task_id, "authorized disposition was not recorded")
                state["finding_disposed"] = True
            state["triage_handled"] = True
    _require(final_current is not None, "workflow exceeded the installed action bound")
    terminal = final_current.get("terminal")
    dossier = terminal.get("dossier") if isinstance(terminal, Mapping) else None
    _require(final_current.get("task", {}).get("status") == "DONE", workflow + " did not reach DONE")
    _require(isinstance(dossier, Mapping) and dossier.get("schema") == DOSSIER_SCHEMA, workflow + " omitted its terminal Dossier")
    observed = set(obligation_kinds)
    _require(EXPECTED_OBLIGATIONS[workflow].issubset(observed), workflow + " missed representative assurance obligations")
    if scenario.get("triggered"):
        _require("independent-review" in observed, workflow + " closed trigger missed independent review")
    _require(all(value == EXPECTED_ALLOWANCE[workflow] for value in allowances), workflow + " changed its obligation allowance")
    _require(assurance_authority is not None, workflow + " omitted assurance authority")
    if scenario.get("openspec_stale"):
        _require(state.get("openspec_stale_seen") is True, "OpenSpec stale/recovery path was not exercised")
    if scenario.get("review_mode") == "unavailable-waived":
        _require(state.get("review_waived") is True, "unavailable review was not waived")
    if scenario.get("review_mode") == "introduced-affected-rework":
        _require(state.get("review_rework_seen") is True, "review rework path was not exercised")
    if scenario.get("review_mode") == "unknown-disposition":
        _require(state.get("finding_disposed") is True, "unknown finding was not disposed")
    if scenario.get("review_mode") == "impact-gap":
        _require(
            state.get("impact_gap_replanned") is True
            and state.get("impact_count", 0) >= 2
            and state.get("impact_observed_current") is True
            and state.get("plan_blocked") == "AMBIENT_DRIFT"
            and state.get("restored_for_replan") is True
            and state.get("implementation_reexecuted") is True
            and bool(state.get("impact_gap_restored_paths")),
            "impact gap was not restored and re-planned",
        )
    return {
        "task_id": task_id,
        "workflow": workflow,
        "route": "closed-trigger" if scenario.get("triggered") else "focused",
        "repository_count": len(repositories),
        "actions": action_ids,
        "obligation_kinds": sorted(observed),
        "allowance": EXPECTED_ALLOWANCE[workflow],
        "assurance_authority": assurance_authority,
        "driver_observations": driver_observations,
        "scenario_evidence": {
            key: value
            for key, value in state.items()
            if key
            in {
                "openspec_stale_seen",
                "review_waived",
                "review_rework_seen",
                "finding_relations",
                "finding_disposed",
                "impact_gap_replanned",
                "impact_gap_restored_paths",
                "impact_observed_current",
                "plan_blocked",
                "restored_for_replan",
                "implementation_reexecuted",
            }
        },
        "terminal_status": "DONE",
        "dossier": dict(dossier),
    }


def _start_legacy_cli_task(
    legacy_cli_root: Path,
    data_dir: Path,
    repository: Path,
) -> dict[str, Any]:
    manifest_path = legacy_cli_root / ".codex-plugin" / "plugin.json"
    cli = legacy_cli_root / "scripts" / "dev_flow.py"
    _require(manifest_path.is_file() and cli.is_file(), "0.4.x CLI artifact is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release = manifest.get("version") if isinstance(manifest, Mapping) else None
    _require(
        isinstance(release, str) and release.startswith("0.4."),
        "legacy CLI artifact is not a 0.4.x release",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(cli),
            "--data-dir",
            str(data_dir),
            "start",
            "--requirement",
            "Resume a persisted 0.4.x CLI task through installed MCP",
            "--workflow",
            "lite",
            "--repo",
            str(repository),
            "--task-id",
            "installed-legacy-0-4-cli",
        ],
        cwd=legacy_cli_root,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(completed.returncode == 0, "0.4.x CLI could not create the compatibility task")
    value = json.loads(completed.stdout)
    _require(
        isinstance(value, Mapping)
        and value.get("ok") is True
        and value.get("task", {}).get("version") == "0.4.0",
        "0.4.x CLI did not persist the current model namespace",
    )
    return {"release": release, "model": "0.4.0", "task_id": "installed-legacy-0-4-cli"}


async def _contract_revision_journey(
    session: ClientSession,
    scratch: Path,
) -> dict[str, Any]:
    repository = _make_repository(scratch, "contract revision repository")
    task_id = "installed-contract-revision"
    _result(
        await session.call_tool(
            "dev_flow_start_task",
            {
                "requirement": "Installed exact adopted-drift contract revision",
                "workflow": "full",
                "repositories": [str(repository)],
                "task_id": task_id,
            },
        ),
        "dev_flow_start_task",
    )
    scenario: dict[str, Any] = {}
    state: dict[str, Any] = {}
    for sequence, expected in enumerate(("task.preflight", "impact.record", "plan.record")):
        current = _result(
            await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
            "dev_flow_get_next_action",
        )
        action = current["action"]
        _require(action["id"] == expected, "contract revision setup lost its declared path")
        payload, _ = _payload_for_action(current, "full", sequence, scenario, state)
        _result(
            await session.call_tool(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": action["id"],
                    "payload": payload,
                    "binding": action["binding"],
                },
            ),
            "dev_flow_apply_action",
        )
    (repository / "ambient-adopted.txt").write_text(
        "exact ambient drift adopted by revision\n", encoding="utf-8"
    )
    current = _result(
        await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
        "dev_flow_get_next_action",
    )
    repository_id = _repositories(current)[0]["id"]
    revised_contract = {
        "schema": CONTRACT_SCHEMA,
        "revision": 2,
        "summary": "Revised installed delivery scope",
        "acceptance_criteria": [
            {
                "id": "revised-delivery",
                "statement": "The exact adopted drift is verified and delivered",
            }
        ],
        "scope": ["Revised installed MCP scope"],
        "constraints": ["One prepared repository member"],
        "risks": [],
        "non_goals": [],
        "open_questions": [],
    }
    claims = {
        "schema": TASK_CHANGE_CLAIMS_SCHEMA,
        "claims": [
            {
                "repository_id": repository_id,
                "path": path,
                "classification": classification,
                "criterion_ids": ["revised-delivery"],
                "purpose": purpose,
            }
            for path, classification, purpose in (
                (
                    "journey-plan.md",
                    "documentation",
                    "Carry the existing repository plan into the revised contract",
                ),
                (
                    "ambient-adopted.txt",
                    "implementation",
                    "Adopt this exact ambient drift into the revised contract",
                ),
            )
        ],
    }
    revised = _result(
        await session.call_tool(
            "dev_flow_revise_contract",
            {
                "task_id": task_id,
                "contract": revised_contract,
                "ownership_claims": claims,
                "reason": "Adopt the exact bounded ambient drift",
                "actor_label": "installed-task-owner",
            },
        ),
        "dev_flow_revise_contract",
    )
    _require(
        revised["current"]["task"]["current_node"] == "impact"
        and revised["current"]["contract"]["criterion_ids"] == ["revised-delivery"],
        "contract revision did not re-enter impact with the revised criterion",
    )
    completed = await _complete_workflow(
        session,
        workflow="full",
        task_id=task_id,
        repositories=(repository,),
        start=False,
    )
    return {
        "task_id": task_id,
        "adopted_paths": ["ambient-adopted.txt", "journey-plan.md"],
        "reentered": "impact",
        "terminal_status": completed["terminal_status"],
        "dossier": completed["dossier"],
    }


async def _corrupt_inventory_admission(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    scratch: Path,
) -> dict[str, Any]:
    data_dir = scratch / "corrupt inventory data"
    corrupt = data_dir / "0.4.0" / "tasks" / "corrupt-entry"
    corrupt.mkdir(parents=True, mode=0o700)
    (corrupt / "state.json").write_text("{not strict JSON\n", encoding="utf-8")
    repository = _make_repository(scratch, "corrupt inventory admission repository")
    parameters = _launcher_parameters(launcher, launcher_args, plugin_root, data_dir)
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await _initialize(session)
            rejected = _structured(
                await session.call_tool(
                    "dev_flow_start_task",
                    {
                        "requirement": "Must not bypass corrupt membership inventory",
                        "workflow": "lite",
                        "repositories": [str(repository)],
                        "task_id": "must-not-be-admitted",
                    },
                ),
                "dev_flow_start_task",
                expect_error=True,
            )
    _require(
        rejected["error"].get("code") == "LEASE_INVENTORY_INVALID",
        "corrupt inventory did not fail admission closed",
    )
    _require(
        not (data_dir / "0.4.0" / "tasks" / "must-not-be-admitted").exists(),
        "corrupt inventory admission partially created a task",
    )
    return {"error_code": "LEASE_INVENTORY_INVALID", "partial_task_created": False}


async def _linked_worktree_concurrent_admission(
    session: ClientSession,
    scratch: Path,
) -> dict[str, Any]:
    primary = _make_repository(scratch, "linked worktree primary")
    linked = scratch / "linked worktree secondary 雪"
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "worktree",
            "add",
            "-q",
            "-b",
            "installed-linked-worktree",
            str(linked),
        ],
        check=True,
    )
    common_primary = subprocess.run(
        ["git", "-C", str(primary), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    common_linked = subprocess.run(
        ["git", "-C", str(linked), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _require(common_primary == common_linked, "linked-worktree fixture lost its shared Git identity")

    async def start(task_id: str, repository: Path) -> Any:
        return await session.call_tool(
            "dev_flow_start_task",
            {
                "requirement": "Concurrent installed linked-worktree admission",
                "workflow": "lite",
                "repositories": [str(repository)],
                "task_id": task_id,
            },
        )

    results = await asyncio.gather(
        start("installed-linked-primary", primary),
        start("installed-linked-secondary", linked),
    )
    task_ids = []
    rejected_task_ids = []
    for task_id, result in zip(
        ("installed-linked-primary", "installed-linked-secondary"), results
    ):
        envelope = result.structured_content
        _require(isinstance(envelope, dict), "linked admission omitted structured authority")
        if envelope.get("ok") is True:
            started = envelope["result"]
            _require(started["task_id"] == task_id, "concurrent linked admission lost task identity")
            task_ids.append(task_id)
        else:
            _require(
                envelope.get("error", {}).get("code") == "TASK_MEMBERSHIP_LEASED",
                "linked-worktree conflict did not fail with membership authority",
            )
            rejected_task_ids.append(task_id)
    _require(len(task_ids) == 1 and len(rejected_task_ids) == 1, "linked worktrees did not admit exactly one active owner")
    for task_id in task_ids:
        _result(
            await session.call_tool(
                "dev_flow_cancel_task",
                {"task_id": task_id, "reason": "linked-worktree admission evidence complete"},
            ),
            "dev_flow_cancel_task",
        )
    return {
        "shared_git_common_dir": True,
        "lease_conflict_enforced": True,
        "public_mcp_admissions": task_ids,
        "rejected_admissions": rejected_task_ids,
        "terminal_status": "CANCELLED",
    }


async def _uncertain_disconnect_journey(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    scratch: Path,
) -> dict[str, Any]:
    """Prove recovery when a committed mutation response is lost in transport."""

    data_dir = scratch / "uncertain disconnect data"
    repository = _make_repository(scratch, "uncertain disconnect repository")
    task_id = "installed-uncertain-disconnect"
    direct = _launcher_parameters(launcher, launcher_args, plugin_root, data_dir)
    async with stdio_client(direct) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await _initialize(session)
            _result(
                await session.call_tool(
                    "dev_flow_start_task",
                    {
                        "requirement": "Recover a committed MCP mutation with a lost response",
                        "workflow": "lite",
                        "repositories": [str(repository)],
                        "task_id": task_id,
                    },
                ),
                "dev_flow_start_task",
            )
            current = _result(
                await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
                "dev_flow_get_next_action",
            )
            action = current["action"]
            _require(action["id"] == "task.preflight", "uncertainty fixture lost preflight")
            binding = action["binding"]

    proxy_environment = dict(os.environ)
    proxy_environment["DEV_FLOW_DISCONNECT_PROXY_TARGET"] = _json(
        [launcher, *launcher_args]
    )
    proxy = StdioServerParameters(
        command=sys.executable,
        args=[
            str(Path(__file__).resolve()),
            "--_disconnect-proxy",
            "--stdio",
            "--data-dir",
            str(data_dir),
        ],
        cwd=plugin_root,
        env=proxy_environment,
    )
    response_lost = False
    try:
        async with stdio_client(proxy) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await _initialize(session)
                await session.call_tool(
                    "dev_flow_apply_action",
                    {
                        "task_id": task_id,
                        "action_id": "task.preflight",
                        "payload": {},
                        "binding": binding,
                    },
                )
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        response_lost = True
    _require(response_lost, "uncertainty proxy did not interrupt the committed response")

    async with stdio_client(direct) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await _initialize(session)
            stored = _result(
                await session.call_tool("dev_flow_get_task", {"task_id": task_id}),
                "dev_flow_get_task",
            )
            _require(
                stored.get("task", {}).get("revision") == 1,
                "lost-response mutation was not committed exactly once",
            )
            current = _result(
                await session.call_tool("dev_flow_get_next_action", {"task_id": task_id}),
                "dev_flow_get_next_action",
            )
            _require(
                current.get("action", {}).get("id") == "impact.record",
                "restart did not resume after the committed uncertain mutation",
            )
            _result(
                await session.call_tool(
                    "dev_flow_cancel_task",
                    {
                        "task_id": task_id,
                        "reason": "uncertain transport recovery evidence complete",
                    },
                ),
                "dev_flow_cancel_task",
            )
    return {
        "response_lost_after_commit": True,
        "authoritative_revision": 1,
        "next_action_after_restart": "impact.record",
        "blind_mutation_replay": False,
        "terminal_status": "CANCELLED",
    }


async def _installed_journeys(
    launcher: str,
    launcher_args: Sequence[str],
    plugin_root: Path,
    scratch: Path,
    legacy_cli_root: Path,
) -> dict[str, Any]:
    data_dir = scratch / "task data 雪's"
    legacy_repository = _make_repository(scratch, "legacy 0.4.x repository")
    legacy_seed = _start_legacy_cli_task(
        legacy_cli_root,
        data_dir,
        legacy_repository,
    )
    parameters = _launcher_parameters(launcher, launcher_args, plugin_root, data_dir)
    audit = _ReadAudit(plugin_root, data_dir)
    sys.addaudithook(audit.hook)
    official: list[dict[str, Any]] = []
    contract_revision: dict[str, Any]
    linked_worktrees: dict[str, Any]

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            identity = await _initialize(session)
            info = _result(await session.call_tool("dev_flow_server_info", {}), "dev_flow_server_info")
            _require(info.get("model_version") == "0.4.0", "persisted model changed")
            legacy_found = _result(
                await session.call_tool(
                    "dev_flow_find_tasks_for_path", {"path": str(legacy_repository)}
                ),
                "dev_flow_find_tasks_for_path",
            )
            _require(
                legacy_found.get("classification") == "single"
                and legacy_found.get("tasks", [{}])[0].get("task_id")
                == legacy_seed["task_id"],
                "installed MCP did not discover the task created by the 0.4.x CLI",
            )
            with _instrument_executor(audit):
                legacy_completed = await _complete_workflow(
                    session,
                    workflow="lite",
                    task_id=legacy_seed["task_id"],
                    repositories=(legacy_repository,),
                    start=False,
                )
                for workflow in OFFICIAL_WORKFLOWS:
                    repository = _make_repository(scratch, "{} focused repository".format(workflow))
                    official.append(
                        await _complete_workflow(
                            session,
                            workflow=workflow,
                            task_id="installed-{}-focused".format(workflow),
                            repositories=(repository,),
                        )
                    )
                triggered_scenarios: dict[str, dict[str, Any]] = {
                    workflow: {
                        "triggered": True,
                        "impact_driver_status": "degraded",
                    }
                    for workflow in OFFICIAL_WORKFLOWS
                }
                triggered_scenarios["bugfix"].update(
                    {"review_mode": "unavailable-waived"}
                )
                triggered_scenarios["feature"].update(
                    {
                        "openspec": True,
                        "openspec_stale": True,
                        "plan_driver_status": "available",
                        "implementation_path": "impact-gap.txt",
                        "review_mode": "impact-gap",
                    }
                )
                triggered_scenarios["full"].update(
                    {
                        "openspec": True,
                        "plan_driver_status": "unavailable",
                        "review_mode": "unknown-disposition",
                    }
                )
                triggered_scenarios["lite"].update(
                    {"review_mode": "introduced-affected-rework"}
                )
                for workflow in OFFICIAL_WORKFLOWS:
                    repository = _make_repository(
                        scratch, "{} closed trigger repository".format(workflow)
                    )
                    official.append(
                        await _complete_workflow(
                            session,
                            workflow=workflow,
                            task_id="installed-{}-closed-trigger".format(workflow),
                            repositories=(repository,),
                            scenario=triggered_scenarios[workflow],
                        )
                    )
                contract_revision = await _contract_revision_journey(session, scratch)
                linked_worktrees = await _linked_worktree_concurrent_admission(
                    session, scratch
                )

            first = _make_repository(scratch, "restart primary repo")
            second = _make_repository(scratch, "restart secondary repo 雪")
            restart_task_id = "installed-restart-exact-set"
            _result(
                await session.call_tool(
                    "dev_flow_start_task",
                    {
                        "requirement": "Installed restart from secondary exact-set member",
                        "workflow": "lite",
                        "repositories": [str(first), str(second)],
                        "task_id": restart_task_id,
                    },
                ),
                "dev_flow_start_task",
            )
            before_restart = _result(
                await session.call_tool("dev_flow_get_next_action", {"task_id": restart_task_id}),
                "dev_flow_get_next_action",
            )
            first_action = before_restart["action"]
            _result(
                await session.call_tool(
                    "dev_flow_apply_action",
                    {
                        "task_id": restart_task_id,
                        "action_id": first_action["id"],
                        "payload": {},
                        "binding": first_action["binding"],
                    },
                ),
                "dev_flow_apply_action",
            )

    # A new OS process must discover the task from a non-first member and use
    # persisted Controller state.  No mutation is replayed after disconnect.
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await _initialize(session)
            found = _result(
                await session.call_tool("dev_flow_find_tasks_for_path", {"path": str(second)}),
                "dev_flow_find_tasks_for_path",
            )
            _require(found.get("classification") == "single", "secondary-member discovery failed after restart")
            _require(found.get("tasks", [{}])[0].get("task_id") == restart_task_id, "restart found the wrong task")
            stored = _result(
                await session.call_tool("dev_flow_get_task", {"task_id": restart_task_id}),
                "dev_flow_get_task",
            )
            _require(stored.get("task", {}).get("revision") == 1, "disconnect recovery did not read authoritative revision")
            with _instrument_executor(audit):
                exact_set = await _complete_workflow(
                    session,
                    workflow="lite",
                    task_id=restart_task_id,
                    repositories=(first, second),
                    start=False,
                )

    corrupt_inventory = await _corrupt_inventory_admission(
        launcher,
        launcher_args,
        plugin_root,
        scratch,
    )
    uncertain_disconnect = await _uncertain_disconnect_journey(
        launcher,
        launcher_args,
        plugin_root,
        scratch,
    )
    _require(not audit.violations, "installed executor read forbidden package or Controller state")
    return {
        "initialize": identity,
        "catalog": identity["catalog"],
        "read_smoke": True,
        "mutation_smoke": True,
        "official_workflows": official,
        "legacy_cli_resume": {
            **legacy_seed,
            "discovered_by_mcp": True,
            "terminal_status": legacy_completed["terminal_status"],
            "dossier": legacy_completed["dossier"],
            "state_migration": False,
        },
        "contract_revision": contract_revision,
        "corrupt_inventory": corrupt_inventory,
        "linked_worktrees": linked_worktrees,
        "exact_set_lite": exact_set,
        "secondary_member_resume": True,
        "restart_resume": True,
        "disconnect_recovery": uncertain_disconnect,
        "executor_source_reads": {
            "instrumented": True,
            "forbidden_reads": [],
        },
        "terminal_status": "DONE",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run installed Dev Flow MCP STDIO acceptance")
    parser.add_argument("--plugin-root", required=True, help="installed immutable plugin snapshot")
    parser.add_argument("--launcher", help="installed dev-flow-mcp PATH launcher")
    parser.add_argument(
        "--legacy-cli-root",
        help="extracted immutable 0.4.x release used only by the full compatibility journey",
    )
    parser.add_argument(
        "--launcher-arg",
        action="append",
        default=[],
        help="argument placed before --stdio (repeatable; use --launcher-arg=-I for option values)",
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="run initialize/catalog/read/isolated-mutation activation smoke only",
    )
    parser.add_argument(
        "--candidate-smoke-only",
        action="store_true",
        help="run the checkout-free staged Skill and MCP read-health gate",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    plugin_root = Path(arguments.plugin_root).expanduser().resolve()
    launcher = arguments.launcher or shutil.which("dev-flow-mcp")
    evidence: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "ok": False,
        "evidence_class": (
            "candidate-staged-smoke"
            if arguments.candidate_smoke_only
            else "staged-or-installed-smoke"
            if arguments.smoke_only
            else "native-installed"
        ),
        "platform": sys.platform,
        "plugin_digest_before": None,
        "plugin_digest_after": None,
        "skill": None,
        "journey": None,
        "errors": [],
    }
    try:
        _require(plugin_root.is_dir(), "plugin root is not a directory")
        _require(bool(launcher), "dev-flow-mcp is not on PATH; pass --launcher")
        launcher_path = Path(str(launcher))
        if os.sep in str(launcher) or (os.altsep and os.altsep in str(launcher)):
            _require(launcher_path.is_file(), "configured dev-flow-mcp launcher is missing")
        before = _tree_digest(plugin_root)
        evidence["plugin_digest_before"] = before
        evidence["skill"] = _installed_skill(plugin_root)
        with tempfile.TemporaryDirectory(prefix="dev-flow-installed-mcp-") as temporary:
            scratch = Path(temporary).resolve()
            _require(
                not (arguments.smoke_only and arguments.candidate_smoke_only),
                "select only one smoke mode",
            )
            if arguments.candidate_smoke_only:
                evidence["journey"] = asyncio.run(
                    _candidate_smoke(
                        str(launcher),
                        tuple(arguments.launcher_arg),
                        plugin_root,
                        scratch,
                    )
                )
            elif arguments.smoke_only:
                evidence["journey"] = asyncio.run(
                    _smoke(str(launcher), tuple(arguments.launcher_arg), plugin_root, scratch)
                )
            else:
                _require(
                    bool(arguments.legacy_cli_root),
                    "full installed acceptance requires --legacy-cli-root",
                )
                legacy_cli_root = Path(arguments.legacy_cli_root).expanduser().resolve()
                _require(
                    legacy_cli_root.is_dir(),
                    "configured 0.4.x CLI artifact root is missing",
                )
                evidence["journey"] = asyncio.run(
                    _installed_journeys(
                        str(launcher),
                        tuple(arguments.launcher_arg),
                        plugin_root,
                        scratch,
                        legacy_cli_root,
                    )
                )
        after = _tree_digest(plugin_root)
        evidence["plugin_digest_after"] = after
        _require(before == after, "installed plugin snapshot changed during acceptance")
        evidence["ok"] = True
    except (AcceptanceFailure, OSError, subprocess.SubprocessError, ValueError) as exc:
        evidence["errors"].append(str(exc))
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        evidence["errors"].extend(_exception_messages(exc))
    print(_json(evidence))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--_disconnect-proxy":
        raise SystemExit(_disconnect_proxy_main(sys.argv[2:]))
    raise SystemExit(main())
