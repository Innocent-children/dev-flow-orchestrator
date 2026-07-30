#!/usr/bin/env python3
"""Prepare or run the project-local, canonical-bound Windows native validation."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


SCRIPT_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_ROOT.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from scripts import candidate_identity  # noqa: E402


REPORT_SCHEMA_VERSION = 1
SENTINEL_NAME = ".dev-flow-native-validation.json"
CHILD_PREFIX = "dev-flow-native-"
HEX_RE = re.compile(r"^[0-9a-f]+$")
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_EXPECTED_TOOLS = (
    "task-next",
    "node-description",
    "evidence-read",
    "action-preview",
    "action-apply",
    "worker-result",
)
MCP_PROBE_MAX_STDOUT_BYTES = 96 * 1024
HOOK_PROBE_MAX_STDOUT_BYTES = 32 * 1024
POST_COMPACT_COMMON_FIELDS = {
    "continue",
    "stopReason",
    "systemMessage",
    "suppressOutput",
}
MANAGER_CAPABILITY_REQUEST_SCHEMA = (
    "dev-flow-manager-capability-request/v1"
)
MANAGER_SECRET_CHANNEL_MIN_BYTES = 32
MANAGER_SECRET_CHANNEL_MAX_BYTES = 1024
CONTROLLER_MANAGER_TTL_SECONDS = 15 * 60
CONTROLLER_ACTION_IDS = {
    "approve": "gate.approve",
    "baseline": "task.baseline",
    "preflight": "task.preflight",
    "prepare-workspace": "workspace.prepare",
    "record-artifact": "evidence.artifact.record",
    "record-index": "evidence.index.record",
    "set-route": "task.route.set",
    "transition": "task.transition",
}


class NativeValidationError(RuntimeError):
    def __init__(self, code: str, message: str, *, incomplete: bool = False):
        super().__init__(message)
        self.code = code
        self.incomplete = incomplete


def _stable_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _redacted_identity(path: Path) -> str:
    try:
        metadata = path.stat()
        fields = (
            os.name,
            str(getattr(metadata, "st_dev", "")),
            str(getattr(metadata, "st_ino", "")),
            str(getattr(metadata, "st_file_attributes", "")),
        )
    except OSError as exc:
        raise NativeValidationError(
            "ROOT_IDENTITY_UNAVAILABLE",
            f"cannot inspect supplied root identity: {exc.__class__.__name__}",
            incomplete=True,
        ) from exc
    return hashlib.sha256("\0".join(fields).encode("utf-8")).hexdigest()


def _path_class(value: Path) -> str:
    spelling = str(value)
    if spelling.startswith(("\\\\", "//")):
        return "unc"
    if re.match(r"^[A-Za-z]:[\\/]", spelling):
        return "drive"
    return "other"


def _samefile(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def _is_broad_root(path: Path, *, require_unc: bool) -> bool:
    spelling = str(path)
    if require_unc:
        normalized = spelling.replace("/", "\\").rstrip("\\")
        parts = [part for part in normalized.split("\\") if part]
        return len(parts) <= 2
    resolved = path.resolve()
    return resolved == Path(resolved.anchor)


def _report_preflight(report: Path, protected: Sequence[Path]) -> None:
    parent = report.expanduser().absolute().parent
    if not parent.is_dir():
        raise NativeValidationError(
            "REPORT_PARENT_MISSING",
            "report parent must already exist",
            incomplete=True,
        )
    if report.exists():
        raise NativeValidationError(
            "REPORT_EXISTS",
            "report destination already exists and will not be overwritten",
            incomplete=True,
        )
    for root in protected:
        try:
            report.expanduser().absolute().relative_to(root.expanduser().absolute())
        except ValueError:
            continue
        raise NativeValidationError(
            "REPORT_INSIDE_PROTECTED_ROOT",
            "report must be outside the candidate and supplied test roots",
            incomplete=True,
        )


def write_report_exclusive(path: Path, report: Mapping[str, Any]) -> None:
    """Publish a complete report atomically without overwriting a prior report."""

    destination = path.expanduser().absolute()
    if destination.exists():
        raise NativeValidationError(
            "REPORT_EXISTS",
            "report destination already exists and will not be overwritten",
            incomplete=True,
        )
    payload = _stable_json_bytes(report)
    temporary: Optional[Path] = None
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=str(destination.parent),
        )
        temporary = Path(raw_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise NativeValidationError(
            "REPORT_EXISTS",
            "report destination already exists and will not be overwritten",
            incomplete=True,
        ) from exc
    except OSError as exc:
        raise NativeValidationError(
            "REPORT_WRITE_FAILED",
            f"could not publish report atomically: {exc.__class__.__name__}",
            incomplete=True,
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _run(
    arguments: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    stdin: Optional[bytes] = None,
    timeout: int = 120,
    inherited_fds: Sequence[int] = (),
) -> subprocess.CompletedProcess:
    descriptors = tuple(dict.fromkeys(inherited_fds))
    if any(
        isinstance(descriptor, bool)
        or not isinstance(descriptor, int)
        or descriptor <= 2
        for descriptor in descriptors
    ):
        raise NativeValidationError(
            "CHILD_DESCRIPTOR_INVALID",
            "native validation child descriptor must be an integer above 2",
        )
    run_options: dict[str, Any] = {}
    windows_inheritability: list[tuple[int, bool]] = []
    try:
        if descriptors:
            if os.name == "nt":  # pragma: no cover - native Windows
                # CPython preserves inheritable CRT descriptors only when
                # CreateProcess is allowed to inherit handles. PEP 446 keeps
                # every other descriptor non-inheritable by default; restore
                # the bounded channel immediately after this synchronous spawn.
                for descriptor in descriptors:
                    inherited = os.get_inheritable(descriptor)
                    windows_inheritability.append(
                        (descriptor, inherited)
                    )
                    os.set_inheritable(descriptor, True)
                run_options["close_fds"] = False
            else:
                run_options["pass_fds"] = descriptors
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            timeout=timeout,
            **run_options,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeValidationError(
            "CHILD_SPAWN_FAILED",
            f"native validation child could not run: {exc.__class__.__name__}",
        ) from exc
    finally:
        for descriptor, inherited in windows_inheritability:
            try:
                os.set_inheritable(descriptor, inherited)
            except OSError:
                pass


def _git(arguments: Sequence[str], cwd: Path) -> bytes:
    completed = _run(["git", *arguments], cwd=cwd)
    if completed.returncode != 0:
        raise NativeValidationError(
            "GIT_COMMAND_FAILED",
            f"Git command failed with exit {completed.returncode}",
        )
    return completed.stdout


def _git_version() -> Optional[str]:
    try:
        completed = _run(["git", "--version"], timeout=30)
    except NativeValidationError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "backslashreplace").strip()


def _code_page_available(code_page: int) -> bool:
    completed = _run(
        ["cmd.exe", "/d", "/s", "/c", f"chcp {code_page}>nul"],
        timeout=30,
    )
    return completed.returncode == 0


def _cmd_python(
    code_page: int,
    arguments: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdin: Optional[bytes] = None,
) -> subprocess.CompletedProcess:
    command = (
        f"chcp {code_page}>nul && "
        + subprocess.list2cmdline([sys.executable, *arguments])
    )
    return _run(
        ["cmd.exe", "/d", "/s", "/c", command],
        cwd=cwd,
        env=env,
        stdin=stdin,
    )


def _parse_single_utf8_json(payload: bytes, label: str) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NativeValidationError(
            "UTF8_PROTOCOL_INVALID",
            f"{label} output was not UTF-8",
        ) from exc
    lines = [line for line in text.splitlines() if line]
    if len(lines) != 1:
        raise NativeValidationError(
            "UTF8_PROTOCOL_FRAMING",
            f"{label} did not emit exactly one JSON line",
        )
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise NativeValidationError(
            "UTF8_PROTOCOL_JSON",
            f"{label} output was not JSON",
        ) from exc
    if not isinstance(value, dict):
        raise NativeValidationError(
            "UTF8_PROTOCOL_JSON",
            f"{label} output was not a JSON object",
        )
    return value


def _mcp_probe_input() -> bytes:
    messages = (
        {
            "jsonrpc": "2.0",
            "id": "dev-flow-native-initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "dev-flow-native-validator",
                    "version": "1.0.0",
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": "dev-flow-native-tools",
            "method": "tools/list",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "id": "dev-flow-native-shutdown",
            "method": "shutdown",
            "params": {},
        },
        {
            "jsonrpc": "2.0",
            "method": "exit",
            "params": {},
        },
    )
    return b"".join(_stable_json_bytes(message) for message in messages)


def _validate_mcp_probe(
    completed: subprocess.CompletedProcess,
    *,
    label: str,
) -> dict[str, Any]:
    if completed.returncode != 0:
        raise NativeValidationError(
            "MCP_HANDSHAKE_FAILED",
            f"{label} MCP handshake exited {completed.returncode}",
        )
    if completed.stderr:
        raise NativeValidationError(
            "MCP_STDERR_NOT_EMPTY",
            f"{label} MCP handshake emitted stderr",
        )
    if len(completed.stdout) > MCP_PROBE_MAX_STDOUT_BYTES:
        raise NativeValidationError(
            "MCP_RESPONSE_BUDGET_EXCEEDED",
            f"{label} MCP handshake exceeded its output budget",
        )
    raw_lines = completed.stdout.splitlines()
    if len(raw_lines) != 3 or any(not line for line in raw_lines):
        raise NativeValidationError(
            "MCP_RESPONSE_FRAMING",
            f"{label} MCP handshake did not emit exactly three JSON lines",
        )
    responses: dict[object, dict[str, Any]] = {}
    for line in raw_lines:
        if len(line) > 32 * 1024:
            raise NativeValidationError(
                "MCP_RESPONSE_BUDGET_EXCEEDED",
                f"{label} MCP response line exceeded 32 KiB",
            )
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise NativeValidationError(
                "MCP_RESPONSE_INVALID",
                f"{label} MCP response was not UTF-8 JSON",
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("jsonrpc") != "2.0"
            or value.get("id") in responses
            or set(value) - {"jsonrpc", "id", "result", "error"}
        ):
            raise NativeValidationError(
                "MCP_RESPONSE_INVALID",
                f"{label} MCP response envelope was invalid",
            )
        responses[value.get("id")] = value
    expected_ids = {
        "dev-flow-native-initialize",
        "dev-flow-native-tools",
        "dev-flow-native-shutdown",
    }
    if set(responses) != expected_ids:
        raise NativeValidationError(
            "MCP_RESPONSE_INVALID",
            f"{label} MCP response IDs differed from the probe",
        )
    if any("error" in response for response in responses.values()):
        raise NativeValidationError(
            "MCP_HANDSHAKE_FAILED",
            f"{label} MCP handshake returned a JSON-RPC error",
        )
    initialize = responses["dev-flow-native-initialize"].get("result")
    if (
        not isinstance(initialize, dict)
        or initialize.get("protocolVersion") != MCP_PROTOCOL_VERSION
        or not isinstance(initialize.get("serverInfo"), dict)
        or initialize["serverInfo"].get("name")
        != "dev-flow-orchestrator"
    ):
        raise NativeValidationError(
            "MCP_INITIALIZE_INVALID",
            f"{label} MCP initialize response differed from the contract",
        )
    tool_result = responses["dev-flow-native-tools"].get("result")
    tools = tool_result.get("tools") if isinstance(tool_result, dict) else None
    if not isinstance(tools, list) or len(tools) != len(MCP_EXPECTED_TOOLS):
        raise NativeValidationError(
            "MCP_TOOL_LIST_INVALID",
            f"{label} MCP tools/list result had an invalid bounded count",
        )
    names = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else None
        if (
            not isinstance(name, str)
            or not name
            or len(name.encode("utf-8")) > 64
        ):
            raise NativeValidationError(
                "MCP_TOOL_LIST_INVALID",
                f"{label} MCP tool name exceeded its contract",
            )
        names.append(name)
    if tuple(names) != MCP_EXPECTED_TOOLS or len(set(names)) != len(names):
        raise NativeValidationError(
            "MCP_TOOL_LIST_INVALID",
            f"{label} MCP tools/list names differed from the package surface",
        )
    shutdown = responses["dev-flow-native-shutdown"]
    if shutdown.get("result", object()) is not None:
        raise NativeValidationError(
            "MCP_SHUTDOWN_INVALID",
            f"{label} MCP shutdown response was invalid",
        )
    return {
        "protocol_version": MCP_PROTOCOL_VERSION,
        "tool_count": len(names),
        "tool_names": names,
    }


def _initialize_repository(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(["init", "--initial-branch=main"], repo)
    _git(["config", "--local", "user.name", "Native Validator"], repo)
    _git(["config", "--local", "user.email", "native@example.invalid"], repo)
    _git(["config", "--local", "core.autocrlf", "false"], repo)
    _git(["config", "--local", "core.longpaths", "true"], repo)
    _git(["config", "--local", "core.hooksPath", os.devnull], repo)
    tracked = repo / "\u8ddf\u8e2a-bytes.txt"
    tracked.write_bytes(b"native-line-1\r\nnative-line-2\n")
    _git(["add", "--", tracked.name], repo)
    _git(["commit", "-m", "native validation fixture"], repo)


def _check_code_page(
    candidate_root: Path,
    child: Path,
    code_page: int,
) -> dict[str, Any]:
    if code_page == 65001:
        raise NativeValidationError(
            "CODE_PAGE_NOT_LEGACY",
            "code page must be a supported non-UTF-8 Windows code page",
            incomplete=True,
        )
    if not _code_page_available(code_page):
        raise NativeValidationError(
            "CODE_PAGE_UNAVAILABLE",
            "requested Windows code page is unavailable",
            incomplete=True,
        )
    repo = child / "\u7f16\u7801-\u6d4b\u8bd5-repository"
    _initialize_repository(repo)
    data_dir = child / "\u63a7\u5236\u5668-\u72b6\u6001"
    environment = dict(os.environ)
    environment["DEV_FLOW_ACTOR"] = "\u9a8c\u8bc1\u7528\u6237"
    environment["PYTHONUTF8"] = "0"
    controller = candidate_root / "scripts" / "dev_flow.py"
    arguments = [
        str(controller),
        "--data-dir",
        str(data_dir),
        "start",
        "--task-id",
        "native-codepage",
        "--workspace-strategy",
        "worktree",
        "--repo",
        str(repo),
        "--requirement",
        "\u539f\u751f\u7f16\u7801\u9a8c\u8bc1",
    ]
    completed = _cmd_python(
        code_page,
        arguments,
        cwd=candidate_root,
        env=environment,
    )
    if completed.returncode != 0:
        raise NativeValidationError(
            "CONTROLLER_CODE_PAGE_FAILED",
            f"controller code-page round-trip exited {completed.returncode}",
        )
    value = _parse_single_utf8_json(completed.stdout, "controller")
    serialized = completed.stdout.decode("utf-8")
    for required in ("\u539f\u751f\u7f16\u7801\u9a8c\u8bc1", "\u7f16\u7801-\u6d4b\u8bd5-repository"):
        if required not in serialized:
            raise NativeValidationError(
                "CONTROLLER_UNICODE_MISSING",
                "controller UTF-8 output did not preserve required Unicode",
            )
    if value.get("ok") is not True:
        raise NativeValidationError(
            "CONTROLLER_CODE_PAGE_FAILED",
            "controller code-page result was not successful",
        )

    hook = candidate_root / "hooks" / "dev_flow_hook.py"
    hook_environment = dict(environment)
    hook_environment["PLUGIN_ROOT"] = str(candidate_root)
    hook_environment["PLUGIN_DATA"] = str(data_dir)
    event = _stable_json_bytes(
        {
            "cwd": str(repo),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    ).rstrip(b"\n") + b"\r\n"
    hook_result = _cmd_python(
        code_page,
        [str(hook)],
        cwd=candidate_root,
        env=hook_environment,
        stdin=event,
    )
    if hook_result.returncode != 0:
        raise NativeValidationError(
            "HOOK_CODE_PAGE_FAILED",
            f"hook code-page round-trip exited {hook_result.returncode}",
        )
    if not hook_result.stdout:
        raise NativeValidationError(
            "HOOK_PROTOCOL_EMPTY",
            "hook code-page round-trip emitted no JSON",
        )
    _parse_single_utf8_json(hook_result.stdout, "hook")
    if "\u63a7\u5236\u5668-\u72b6\u6001" not in hook_result.stdout.decode("utf-8"):
        raise NativeValidationError(
            "HOOK_UNICODE_MISSING",
            "hook UTF-8 output did not preserve the Unicode data directory",
        )
    return {
        "diagnostic": "UTF8_JSON_EXACT",
        "id": "legacy-code-page-protocol",
        "observed_code_page": code_page,
        "status": "passed",
    }


def _check_windows_mcp_launcher(candidate_root: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            (candidate_root / ".mcp.json").read_text(encoding="utf-8")
        )
        server = document["mcpServers"]["dev-flow-windows"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise NativeValidationError(
            "WINDOWS_MCP_PROFILE_INVALID",
            "the extracted candidate has no readable Windows MCP profile",
        ) from exc
    expected_args = [
        "/d",
        "/c",
        ".\\scripts\\dev_flow_mcp_launcher.cmd",
    ]
    if (
        not isinstance(server, dict)
        or server.get("command") != "cmd.exe"
        or server.get("args") != expected_args
        or server.get("cwd") != "."
        or server.get("enabled") is not False
        or server.get("enabled_tools") != list(MCP_EXPECTED_TOOLS)
    ):
        raise NativeValidationError(
            "WINDOWS_MCP_PROFILE_INVALID",
            "the Windows MCP profile differs from the explicit host contract",
        )
    completed = _run(
        [server["command"], *server["args"]],
        cwd=candidate_root,
        stdin=_mcp_probe_input(),
        timeout=30,
    )
    observed = _validate_mcp_probe(
        completed,
        label="packaged Windows profile",
    )
    return {
        "diagnostic": "WINDOWS_MCP_LAUNCH_OK",
        "id": "native-windows-mcp-launcher",
        "protocol_version": observed["protocol_version"],
        "status": "passed",
        "tool_count": observed["tool_count"],
        "tool_names": observed["tool_names"],
    }


def _packaged_windows_hook_command(
    candidate_root: Path,
    event: str,
) -> list[str]:
    try:
        document = json.loads(
            (candidate_root / "hooks" / "hooks.json").read_text(
                encoding="utf-8"
            )
        )
        groups = document["hooks"][event]
        handlers = groups[0]["hooks"]
        handler = handlers[0]
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise NativeValidationError(
            "WINDOWS_HOOK_PROFILE_INVALID",
            f"the packaged {event} hook profile is unreadable",
        ) from exc
    expected = '"%PLUGIN_ROOT%\\hooks\\dev_flow_hook.cmd"'
    if (
        not isinstance(groups, list)
        or len(groups) != 1
        or not isinstance(handlers, list)
        or len(handlers) != 1
        or not isinstance(handler, dict)
        or handler.get("type") != "command"
        or handler.get("commandWindows") != expected
    ):
        raise NativeValidationError(
            "WINDOWS_HOOK_PROFILE_INVALID",
            f"the packaged {event} Windows command differs from the contract",
        )
    return ["cmd.exe", "/d", "/c", expected]


def _compact_hook_payloads(
    cwd: Path,
    session_id: str,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    common = {
        "cwd": str(cwd),
        "session_id": session_id,
    }
    return (
        (
            "PreCompact",
            {
                **common,
                "hook_event_name": "PreCompact",
                "trigger": "manual",
            },
        ),
        (
            "PostCompact",
            {
                **common,
                "hook_event_name": "PostCompact",
                "compaction_id": "native-compact-probe",
            },
        ),
        (
            "SessionStart",
            {
                **common,
                "hook_event_name": "SessionStart",
                "source": "compact",
            },
        ),
    )


def _validate_common_post_compact_output(value: Mapping[str, Any]) -> None:
    if "hookSpecificOutput" in value or set(value) - POST_COMPACT_COMMON_FIELDS:
        raise NativeValidationError(
            "POST_COMPACT_OUTPUT_INVALID",
            "PostCompact emitted unsupported hook-specific output",
        )
    expected_types = {
        "continue": bool,
        "stopReason": str,
        "systemMessage": str,
        "suppressOutput": bool,
    }
    for key, item in value.items():
        if not isinstance(item, expected_types[key]):
            raise NativeValidationError(
                "POST_COMPACT_OUTPUT_INVALID",
                f"PostCompact common field {key} has the wrong type",
            )


def _validate_compact_hook_outputs(
    *,
    pre_compact: bytes,
    post_compact: bytes,
    session_start: bytes,
    expected_task_id: str,
) -> dict[str, Any]:
    for label, payload in (
        ("PreCompact", pre_compact),
        ("PostCompact", post_compact),
        ("SessionStart(compact)", session_start),
    ):
        if len(payload) > HOOK_PROBE_MAX_STDOUT_BYTES:
            raise NativeValidationError(
                "HOOK_RESPONSE_BUDGET_EXCEEDED",
                f"{label} exceeded the native hook output budget",
            )
    if _parse_single_utf8_json(pre_compact, "PreCompact") != {}:
        raise NativeValidationError(
            "PRE_COMPACT_OUTPUT_INVALID",
            "PreCompact did not emit the expected empty JSON object",
        )
    if post_compact.strip():
        post_value = _parse_single_utf8_json(
            post_compact,
            "PostCompact",
        )
        _validate_common_post_compact_output(post_value)
        post_shape = "common"
    else:
        post_shape = "empty"
    restored = _parse_single_utf8_json(
        session_start,
        "SessionStart(compact)",
    )
    specific = restored.get("hookSpecificOutput")
    if (
        not isinstance(specific, dict)
        or specific.get("hookEventName") != "SessionStart"
        or not isinstance(specific.get("additionalContext"), str)
    ):
        raise NativeValidationError(
            "COMPACT_RESTORE_INVALID",
            "SessionStart(compact) did not emit the SessionStart wire shape",
        )
    context = specific["additionalContext"]
    if len(context.encode("utf-8")) > 4096:
        raise NativeValidationError(
            "HOOK_RESPONSE_BUDGET_EXCEEDED",
            "SessionStart(compact) locator exceeded 4 KiB",
        )
    try:
        locator = json.loads(context)
    except json.JSONDecodeError as exc:
        raise NativeValidationError(
            "COMPACT_RESTORE_INVALID",
            "SessionStart(compact) additionalContext was not a JSON locator",
        ) from exc
    if (
        not isinstance(locator, dict)
        or locator.get("contract") != "dev-flow-hook-checkpoint/v1"
        or locator.get("task_id") != expected_task_id
        or isinstance(locator.get("revision"), bool)
        or not isinstance(locator.get("revision"), int)
        or not isinstance(locator.get("controller"), str)
    ):
        raise NativeValidationError(
            "COMPACT_RESTORE_INVALID",
            "SessionStart(compact) locator differed from the task checkpoint",
        )
    serialized = json.dumps(
        restored,
        ensure_ascii=False,
        sort_keys=True,
    ).casefold()
    if "manager_secret" in serialized or "manager-proof" in serialized:
        raise NativeValidationError(
            "COMPACT_RESTORE_SECRET_EXPOSURE",
            "SessionStart(compact) exposed manager secret material",
        )
    return {
        "post_compact_shape": post_shape,
        "restored_contract": locator["contract"],
        "task_id": locator["task_id"],
    }


def _check_windows_compact_hook_lifecycle(
    candidate_root: Path,
    child: Path,
    code_page: int,
) -> dict[str, Any]:
    task_id = "native-hook-compact"
    repo = child / "compact-hook-repository"
    _initialize_repository(repo)
    data_dir = child / "compact-hook-state"
    environment = dict(os.environ)
    environment["DEV_FLOW_ACTOR"] = "native-hook-validator"
    environment["PYTHONUTF8"] = "0"
    started = _cmd_python(
        code_page,
        [
            str(candidate_root / "scripts" / "dev_flow.py"),
            "--data-dir",
            str(data_dir),
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "worktree",
            "--repo",
            str(repo),
            "--requirement",
            "validate packaged compact lifecycle",
        ],
        cwd=candidate_root,
        env=environment,
    )
    if started.returncode != 0:
        raise NativeValidationError(
            "COMPACT_TASK_START_FAILED",
            f"compact lifecycle task start exited {started.returncode}",
        )
    started_value = _parse_single_utf8_json(
        started.stdout,
        "compact lifecycle task start",
    )
    if started_value.get("ok") is not True:
        raise NativeValidationError(
            "COMPACT_TASK_START_FAILED",
            "compact lifecycle task start was not successful",
        )
    hook_environment = dict(environment)
    hook_environment["PLUGIN_ROOT"] = str(candidate_root)
    hook_environment["PLUGIN_DATA"] = str(data_dir)
    outputs: dict[str, bytes] = {}
    session_id = "native-hook-compact-session"
    for event, payload in _compact_hook_payloads(repo, session_id):
        completed = _run(
            _packaged_windows_hook_command(candidate_root, event),
            cwd=candidate_root,
            env=hook_environment,
            stdin=_stable_json_bytes(payload),
            timeout=30,
        )
        if completed.returncode != 0 or completed.stderr:
            raise NativeValidationError(
                "WINDOWS_HOOK_LAUNCH_FAILED",
                f"packaged {event} hook failed its native launcher",
            )
        outputs[event] = completed.stdout
    observed = _validate_compact_hook_outputs(
        pre_compact=outputs["PreCompact"],
        post_compact=outputs["PostCompact"],
        session_start=outputs["SessionStart"],
        expected_task_id=task_id,
    )
    return {
        "diagnostic": "WINDOWS_COMPACT_HOOK_LIFECYCLE_OK",
        "id": "native-windows-compact-hook-lifecycle",
        "post_compact_shape": observed["post_compact_shape"],
        "restored_contract": observed["restored_contract"],
        "status": "passed",
    }


def _load_controller(candidate_root: Path):
    controller_path = candidate_root / "scripts" / "dev_flow.py"
    module_name = (
        "_dev_flow_native_candidate_"
        + hashlib.sha256(str(controller_path).encode("utf-8")).hexdigest()[:16]
    )
    specification = importlib.util.spec_from_file_location(
        module_name,
        controller_path,
    )
    if specification is None or specification.loader is None:
        raise NativeValidationError(
            "CONTROLLER_IMPORT_FAILED",
            "verified candidate controller could not be loaded",
        )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@dataclass
class _ControllerManagerCapability:
    task_id: str
    manager_session_id: str
    capability_id: str
    secret: bytearray = field(repr=False)

    def close(self) -> None:
        for index in range(len(self.secret)):
            self.secret[index] = 0


def _close_descriptor(descriptor: Optional[int]) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _read_exact_descriptor(descriptor: int, size: int) -> bytearray:
    value = bytearray()
    try:
        while len(value) < size:
            chunk = os.read(descriptor, size - len(value))
            if not chunk:
                raise NativeValidationError(
                    "MANAGER_SECRET_CHANNEL_TRUNCATED",
                    "manager secret channel closed before its frame completed",
                )
            value.extend(chunk)
        return value
    except BaseException:
        for index in range(len(value)):
            value[index] = 0
        raise


def _receive_manager_secret(descriptor: int) -> bytearray:
    header: Optional[bytearray] = None
    secret: Optional[bytearray] = None
    try:
        header = _read_exact_descriptor(descriptor, 4)
        (size,) = struct.unpack(">I", header)
        if not (
            MANAGER_SECRET_CHANNEL_MIN_BYTES
            <= size
            <= MANAGER_SECRET_CHANNEL_MAX_BYTES
        ):
            raise NativeValidationError(
                "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
                "manager secret channel frame exceeded its fixed bounds",
            )
        secret = _read_exact_descriptor(descriptor, size)
        if os.read(descriptor, 1):
            raise NativeValidationError(
                "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
                "manager authorization published more than one secret frame",
            )
        result = secret
        secret = None
        return result
    finally:
        if header is not None:
            for index in range(len(header)):
                header[index] = 0
        if secret is not None:
            for index in range(len(secret)):
                secret[index] = 0


def _publish_manager_secret(
    descriptor: int,
    secret: bytearray,
) -> None:
    if not (
        MANAGER_SECRET_CHANNEL_MIN_BYTES
        <= len(secret)
        <= MANAGER_SECRET_CHANNEL_MAX_BYTES
    ):
        raise NativeValidationError(
            "MANAGER_SECRET_CHANNEL_FRAME_INVALID",
            "manager secret has an invalid bounded length",
        )
    frame = bytearray(struct.pack(">I", len(secret)))
    frame.extend(secret)
    try:
        offset = 0
        while offset < len(frame):
            written = os.write(descriptor, frame[offset:])
            if written <= 0:
                raise NativeValidationError(
                    "MANAGER_SECRET_CHANNEL_TRUNCATED",
                    "manager secret frame could not be published",
                )
            offset += written
    except OSError as exc:
        raise NativeValidationError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager secret channel could not publish a proof frame",
        ) from exc
    finally:
        for index in range(len(frame)):
            frame[index] = 0


def _controller_call(
    candidate_root: Path,
    data_dir: Path,
    arguments: Sequence[str],
    *,
    expected_error: Optional[str] = None,
    inherited_fds: Sequence[int] = (),
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    completed = _run(
        [
            sys.executable,
            str(candidate_root / "scripts" / "dev_flow.py"),
            "--data-dir",
            str(data_dir),
            *arguments,
        ],
        cwd=candidate_root,
        env=environment,
        inherited_fds=inherited_fds,
    )
    if not completed.stdout:
        raise NativeValidationError(
            "CONTROLLER_PROTOCOL_EMPTY",
            "controller managed-worktree call emitted no JSON",
        )
    value = _parse_single_utf8_json(completed.stdout, "controller managed-worktree")
    if expected_error is None:
        if completed.returncode != 0 or value.get("ok") is not True:
            raise NativeValidationError(
                "CONTROLLER_FLOW_FAILED",
                "controller managed-worktree call did not succeed",
            )
        return value
    observed = (value.get("error") or {}).get("code")
    if completed.returncode == 0 or observed != expected_error:
        raise NativeValidationError(
            "CONTROLLER_GUARD_MISSED",
            "controller did not return the required managed-worktree guard",
        )
    return value


def _authorize_controller_manager(
    candidate_root: Path,
    data_dir: Path,
    task_id: str,
    revision: int,
) -> tuple[int, _ControllerManagerCapability]:
    manager_session_id = f"native-manager-{task_id}"
    common_arguments = [
        "manager-authorize",
        task_id,
        "--expected-revision",
        str(revision),
        "--manager-session-id",
        manager_session_id,
        "--ttl-seconds",
        str(CONTROLLER_MANAGER_TTL_SECONDS),
    ]
    preview = _controller_call(
        candidate_root,
        data_dir,
        [*common_arguments, "--preview"],
    )
    intent_id = str((preview.get("preview") or {}).get("intent_id") or "")
    if not intent_id:
        raise NativeValidationError(
            "MANAGER_AUTHORIZATION_PREVIEW_INVALID",
            "manager authorization preview returned no confirmation intent",
        )

    read_descriptor: Optional[int] = None
    write_descriptor: Optional[int] = None
    secret: Optional[bytearray] = None
    try:
        read_descriptor, write_descriptor = os.pipe()
        confirmed = _controller_call(
            candidate_root,
            data_dir,
            [
                *common_arguments,
                "--confirm-intent",
                intent_id,
                "--manager-secret-fd",
                str(write_descriptor),
            ],
            inherited_fds=(write_descriptor,),
        )
        _close_descriptor(write_descriptor)
        write_descriptor = None
        secret = _receive_manager_secret(read_descriptor)
        capability = confirmed.get("capability") or {}
        capability_id = str(capability.get("capability_id") or "")
        allowed_actions = capability.get("allowed_actions")
        if (
            not capability_id
            or not isinstance(allowed_actions, list)
            or not set(CONTROLLER_ACTION_IDS.values()).issubset(
                set(allowed_actions)
            )
            or capability.get("manager_session_id") != manager_session_id
            or capability.get("secret_transport")
            != "local-secret-channel"
        ):
            raise NativeValidationError(
                "MANAGER_AUTHORIZATION_INVALID",
                "manager authorization response differed from the v3 contract",
            )
        result = _ControllerManagerCapability(
            task_id=task_id,
            manager_session_id=manager_session_id,
            capability_id=capability_id,
            secret=secret,
        )
        secret = None
        return int(confirmed["revision"]), result
    except OSError as exc:
        raise NativeValidationError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager authorization pipe could not be created",
        ) from exc
    finally:
        _close_descriptor(read_descriptor)
        _close_descriptor(write_descriptor)
        if secret is not None:
            for index in range(len(secret)):
                secret[index] = 0


def _controller_manager_request(
    manager: _ControllerManagerCapability,
    action_id: str,
    revision: int,
) -> str:
    request = {
        "schema": MANAGER_CAPABILITY_REQUEST_SCHEMA,
        "capability_id": manager.capability_id,
        "task_id": manager.task_id,
        "manager_session_id": manager.manager_session_id,
        "action_id": action_id,
        "expected_revision": revision,
        "request_nonce": secrets.token_hex(32),
    }
    return json.dumps(
        request,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _controller_authorized_call(
    candidate_root: Path,
    data_dir: Path,
    arguments: Sequence[str],
    *,
    manager: Optional[_ControllerManagerCapability],
    action_id: str,
    revision: int,
    expected_error: Optional[str] = None,
) -> dict[str, Any]:
    if manager is None:
        return _controller_call(
            candidate_root,
            data_dir,
            arguments,
            expected_error=expected_error,
        )
    if manager.task_id not in arguments:
        raise NativeValidationError(
            "MANAGER_AUTHORIZATION_SCOPE_INVALID",
            "manager capability task differs from the controller mutation",
        )
    read_descriptor: Optional[int] = None
    write_descriptor: Optional[int] = None
    try:
        read_descriptor, write_descriptor = os.pipe()
        _publish_manager_secret(write_descriptor, manager.secret)
        _close_descriptor(write_descriptor)
        write_descriptor = None
        return _controller_call(
            candidate_root,
            data_dir,
            [
                *arguments,
                "--manager-request-json",
                _controller_manager_request(
                    manager,
                    action_id,
                    revision,
                ),
                "--manager-secret-fd",
                str(read_descriptor),
            ],
            expected_error=expected_error,
            inherited_fds=(read_descriptor,),
        )
    except OSError as exc:
        raise NativeValidationError(
            "MANAGER_SECRET_CHANNEL_UNAVAILABLE",
            "manager mutation pipe could not be created",
        ) from exc
    finally:
        _close_descriptor(read_descriptor)
        _close_descriptor(write_descriptor)


def _controller_mutation(
    candidate_root: Path,
    data_dir: Path,
    command: str,
    task_id: str,
    revision: int,
    *arguments: str,
    manager: Optional[_ControllerManagerCapability],
    expected_error: Optional[str] = None,
) -> dict[str, Any]:
    try:
        action_id = CONTROLLER_ACTION_IDS[command]
    except KeyError as exc:
        raise NativeValidationError(
            "MANAGER_ACTION_UNKNOWN",
            "controller mutation has no public manager action identity",
        ) from exc
    if command == "preflight" and expected_error is None:
        preview = _controller_call(
            candidate_root,
            data_dir,
            [
                command,
                task_id,
                "--expected-revision",
                str(revision),
                *arguments,
                "--preview",
            ],
        )
        return _controller_authorized_call(
            candidate_root,
            data_dir,
            [
                command,
                task_id,
                "--expected-revision",
                str(revision),
                *arguments,
                "--confirm-preview",
                str(preview["transition_preview"]["token"]),
            ],
            manager=manager,
            action_id=action_id,
            revision=revision,
        )
    if command == "transition" and expected_error is None:
        preview = _controller_call(
            candidate_root,
            data_dir,
            [
                command,
                task_id,
                "--expected-revision",
                str(revision),
                *arguments,
                "--preview",
            ],
        )
        intent_id = str((preview.get("preview") or {}).get("intent_id") or "")
        if not intent_id:
            raise NativeValidationError(
                "CONTROLLER_TRANSITION_PREVIEW_INVALID",
                "controller transition preview returned no confirmation intent",
            )
        arguments = (*arguments, "--confirm-intent", intent_id)
    return _controller_authorized_call(
        candidate_root,
        data_dir,
        [
            command,
            task_id,
            "--expected-revision",
            str(revision),
            *arguments,
        ],
        manager=manager,
        action_id=action_id,
        revision=revision,
        expected_error=expected_error,
    )


def _configure_local_origin(
    candidate_root: Path,
    repo: Path,
    remote: Path,
) -> None:
    _git(["clone", "--bare", str(repo), str(remote)], candidate_root)
    _git(["-C", str(repo), "remote", "add", "origin", str(remote)], candidate_root)
    _git(["-C", str(repo), "fetch", "--quiet", "origin"], candidate_root)
    _git(["-C", str(repo), "remote", "set-head", "origin", "main"], candidate_root)


def _route_approved_controller_task(
    candidate_root: Path,
    data_dir: Path,
    *,
    task_id: str,
    start_selector: Path,
    alternate_selector: Path,
    impact_path: Path,
) -> tuple[int, str, Optional[_ControllerManagerCapability]]:
    started = _controller_call(
        candidate_root,
        data_dir,
        [
            "start",
            "--task-id",
            task_id,
            "--workspace-strategy",
            "worktree",
            "--repo",
            str(start_selector),
            "--requirement",
            "Native managed-worktree contract",
        ],
    )
    task = started.get("task") or {}
    repositories = task.get("repositories") or []
    if len(repositories) != 1:
        raise NativeValidationError(
            "CONTROLLER_REPOSITORY_SELECTION_FAILED",
            "controller did not configure exactly one selected repository",
        )
    repository_id = str(repositories[0].get("id") or "")
    if not repository_id:
        raise NativeValidationError(
            "CONTROLLER_REPOSITORY_SELECTION_FAILED",
            "controller selected repository has no stable id",
        )
    if not _samefile(Path(str(repositories[0].get("path"))), alternate_selector):
        raise NativeValidationError(
            "CONTROLLER_REPOSITORY_IDENTITY_FAILED",
            "controller repository selection did not retain filesystem identity",
        )

    manager: Optional[_ControllerManagerCapability] = None
    revision = int(started["revision"])
    if task.get("schema_version") == 3:
        revision, manager = _authorize_controller_manager(
            candidate_root,
            data_dir,
            task_id,
            revision,
        )
    try:
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "preflight",
            task_id,
            revision,
            "--repo",
            str(alternate_selector),
            manager=manager,
        )
        revision = int(response["revision"])
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "approve",
            task_id,
            revision,
            "--gate",
            "baseline-fetch",
            "--note",
            "native fixture baseline approved without fetch",
            manager=manager,
        )
        revision = int(response["revision"])
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "baseline",
            task_id,
            revision,
            "--materialize",
            manager=manager,
        )
        revision = int(response["revision"])
        index_id = f"native-baseline-{task_id}"
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "record-index",
            task_id,
            revision,
            "--repo",
            str(start_selector),
            "--index-id",
            index_id,
            manager=manager,
        )
        revision = int(response["revision"])
        impact_path.write_text(
            "Native managed-worktree impact.\n",
            encoding="utf-8",
        )
        controller = _load_controller(candidate_root)
        impact_metadata = {
            "schema": "dev-flow-impact-analysis/v1",
            "strategy": "funnel",
            "coverage": "complete",
            "budget_profile": "seed-v1",
            "repositories": [
                {
                    "repository_id": repository_id,
                    "index_id": index_id,
                    "index_mode": "fast",
                    "checks": {
                        name: {"status": "complete"}
                        for name in controller.IMPACT_CHECKS
                    },
                    "queries": {
                        name: 0 for name in controller.IMPACT_QUERY_KEYS
                    },
                    "unresolved_truncations": [],
                    "material_unknowns": [],
                }
            ],
            "cross_repository": {
                "status": "not_applicable",
                "reason": "single repository native validation",
            },
        }
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "record-artifact",
            task_id,
            revision,
            "--kind",
            "impact",
            "--path",
            str(impact_path),
            "--metadata-json",
            json.dumps(impact_metadata, sort_keys=True),
            manager=manager,
        )
        revision = int(response["revision"])
        artifact_sha256 = str(
            (response.get("artifact") or {}).get("sha256") or ""
        )
        if not candidate_identity.SHA256_RE.fullmatch(artifact_sha256):
            raise NativeValidationError(
                "CONTROLLER_IMPACT_IDENTITY_FAILED",
                "controller did not return a valid impact identity",
            )
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "set-route",
            task_id,
            revision,
            "direct",
            "--reason",
            "bounded native managed-worktree validation",
            manager=manager,
        )
        revision = int(response["revision"])
        response = _controller_mutation(
            candidate_root,
            data_dir,
            "approve",
            task_id,
            revision,
            "--gate",
            "route",
            "--note",
            "native fixture impact and route approved",
            "--artifact-sha256",
            artifact_sha256,
            manager=manager,
        )
        return int(response["revision"]), repository_id, manager
    except BaseException:
        if manager is not None:
            manager.close()
        raise


def _exercise_controller_managed_worktree(
    candidate_root: Path,
    data_dir: Path,
    local_repo: Path,
    repository_alias: Path,
    worktree: Path,
    scratch: Path,
    manager_stack: contextlib.ExitStack,
) -> dict[str, Any]:
    """Exercise the real controller CLI and its durable worktree contracts."""

    owner_task = "native-managed-owner"
    contender_task = "native-managed-contender"
    branch = "native/long-path-validation"
    (
        owner_revision,
        repository_id,
        owner_manager,
    ) = _route_approved_controller_task(
        candidate_root,
        data_dir,
        task_id=owner_task,
        start_selector=repository_alias,
        alternate_selector=local_repo,
        impact_path=scratch / "owner-impact.md",
    )
    if owner_manager is not None:
        manager_stack.callback(owner_manager.close)
    alias_claim = _controller_call(
        candidate_root,
        data_dir,
        [
            "start",
            "--task-id",
            "native-managed-alias-contender",
            "--workspace-strategy",
            "worktree",
            "--repo",
            str(local_repo),
            "--requirement",
            "Native repository alias ownership guard",
        ],
        expected_error="REPOSITORY_CLAIM_CONFLICT",
    )
    alias_claim_details = (alias_claim.get("error") or {}).get("details") or {}
    if (
        alias_claim_details.get("owner_task_id") != owner_task
        or alias_claim_details.get("conflict") != "canonical_path"
    ):
        raise NativeValidationError(
            "CONTROLLER_REPOSITORY_CLAIM_INEXACT",
            "local and alias repository selectors did not share one exclusive claim",
        )

    contender_repo = scratch / "native-managed-contender-repository"
    _initialize_repository(contender_repo)
    _configure_local_origin(
        candidate_root,
        contender_repo,
        scratch / "native-managed-contender-origin.git",
    )
    (
        contender_revision,
        _,
        contender_manager,
    ) = _route_approved_controller_task(
        candidate_root,
        data_dir,
        task_id=contender_task,
        start_selector=contender_repo,
        alternate_selector=contender_repo,
        impact_path=scratch / "contender-impact.md",
    )
    if contender_manager is not None:
        manager_stack.callback(contender_manager.close)

    plan = _controller_mutation(
        candidate_root,
        data_dir,
        "prepare-workspace",
        owner_task,
        owner_revision,
        "--path",
        str(worktree),
        "--branch",
        branch,
        manager=owner_manager,
    )
    owner_revision = int(plan["revision"])
    plan_artifact = plan.get("plan_artifact") or {}
    plan_sha256 = str(plan_artifact.get("sha256") or "")
    if not candidate_identity.SHA256_RE.fullmatch(plan_sha256):
        raise NativeValidationError(
            "CONTROLLER_WORKSPACE_PLAN_FAILED",
            "controller did not return a valid workspace plan identity",
        )

    conflict = _controller_mutation(
        candidate_root,
        data_dir,
        "prepare-workspace",
        contender_task,
        contender_revision,
        "--path",
        str(worktree),
        "--branch",
        "native/independent-contender",
        manager=contender_manager,
        expected_error="WORKSPACE_OWNERSHIP_CONFLICT",
    )
    conflict_details = (conflict.get("error") or {}).get("details") or {}
    if conflict_details.get("conflict") != "path":
        raise NativeValidationError(
            "CONTROLLER_OWNERSHIP_CONFLICT_INEXACT",
            "independent repository did not produce an exact workspace path claim conflict",
        )

    approved = _controller_mutation(
        candidate_root,
        data_dir,
        "approve",
        owner_task,
        owner_revision,
        "--gate",
        "workspace",
        "--note",
        "native durable workspace claim approved",
        "--artifact-sha256",
        plan_sha256,
        manager=owner_manager,
    )
    owner_revision = int(approved["revision"])
    executed = _controller_mutation(
        candidate_root,
        data_dir,
        "prepare-workspace",
        owner_task,
        owner_revision,
        "--execute",
        "--path",
        str(worktree),
        "--branch",
        branch,
        manager=owner_manager,
    )
    owner_revision = int(executed["revision"])
    if executed.get("complete") is not True:
        raise NativeValidationError(
            "CONTROLLER_WORKSPACE_INCOMPLETE",
            "controller did not complete managed worktree materialization",
        )
    shown = _controller_call(
        candidate_root,
        data_dir,
        ["show", "--task", owner_task],
    )
    task = shown.get("task") or {}
    if task.get("status") != "WORKSPACE_READY":
        raise NativeValidationError(
            "CONTROLLER_WORKSPACE_NOT_READY",
            "controller did not persist WORKSPACE_READY after postconditions",
        )
    repositories = task.get("repositories") or []
    workspace = (repositories[0].get("workspace") or {}) if repositories else {}
    claim = workspace.get("workspace_claim") or {}
    if (
        workspace.get("ready") is not True
        or workspace.get("owner_task_id") != owner_task
        or workspace.get("branch") != branch
        or claim.get("plan_sha256") != plan_sha256
        or not claim.get("claim_id")
    ):
        raise NativeValidationError(
            "CONTROLLER_WORKSPACE_RECEIPT_FAILED",
            "controller workspace readiness lacks the approved durable ownership receipt",
        )
    if not _samefile(Path(str(workspace.get("path"))), worktree):
        raise NativeValidationError(
            "CONTROLLER_WORKSPACE_PATH_FAILED",
            "controller workspace receipt does not identify the materialized worktree",
        )

    indexed = _controller_mutation(
        candidate_root,
        data_dir,
        "record-index",
        owner_task,
        owner_revision,
        "--role",
        "workspace",
        "--repo",
        repository_id,
        "--index-id",
        "native-workspace-index",
        "--metadata-json",
        '{"persistence":false}',
        manager=owner_manager,
    )
    indexed_revision = int(indexed["revision"])
    tracked = worktree / "\u8ddf\u8e2a-bytes.txt"
    original = tracked.read_bytes()
    tracked.write_bytes(original + b"changed")
    drift = _controller_mutation(
        candidate_root,
        data_dir,
        "transition",
        owner_task,
        indexed_revision,
        "PLANNING",
        manager=owner_manager,
        expected_error="STALE_WORKSPACE_INDEX",
    )
    stale_repositories = (
        ((drift.get("error") or {}).get("details") or {}).get("repositories")
        or []
    )
    if not any(
        item.get("reason") == "workspace content changed after indexing"
        for item in stale_repositories
        if isinstance(item, dict)
    ):
        raise NativeValidationError(
            "CONTROLLER_TRACKED_DRIFT_INEXACT",
            "controller did not attribute tracked-byte drift to workspace content",
        )
    tracked.write_bytes(original)
    restored = _controller_mutation(
        candidate_root,
        data_dir,
        "transition",
        owner_task,
        indexed_revision,
        "PLANNING",
        manager=owner_manager,
    )
    if restored.get("status") != "PLANNING":
        raise NativeValidationError(
            "CONTROLLER_REVALIDATION_FAILED",
            "controller did not pass integrity revalidation after exact byte restoration",
        )
    return {
        "claim_conflict": "WORKSPACE_OWNERSHIP_CONFLICT",
        "drift_guard": "STALE_WORKSPACE_INDEX",
        "postcondition": "WORKSPACE_READY",
    }


def exercise_controller_managed_worktree(
    candidate_root: Path,
    data_dir: Path,
    local_repo: Path,
    repository_alias: Path,
    worktree: Path,
    scratch: Path,
) -> dict[str, Any]:
    """Exercise production schema-v3 controller and worktree guardrails."""

    manager_stack = contextlib.ExitStack()
    try:
        return _exercise_controller_managed_worktree(
            candidate_root,
            data_dir,
            local_repo,
            repository_alias,
            worktree,
            scratch,
            manager_stack,
        )
    finally:
        manager_stack.close()


def _check_paths_and_worktree(
    candidate_root: Path,
    local_child: Path,
    unc_child: Path,
) -> dict[str, Any]:
    if not _samefile(local_child, unc_child):
        raise NativeValidationError(
            "CHILD_ALIAS_MISMATCH",
            "runner-owned child is not reachable through both supplied aliases",
        )
    local_repo = local_child / "\u7f16\u7801-\u6d4b\u8bd5-repository"
    unc_repo = unc_child / local_repo.name
    if not _samefile(local_repo, unc_repo):
        raise NativeValidationError(
            "REPOSITORY_ALIAS_MISMATCH",
            "fixture repository aliases do not identify one directory",
        )

    dev_flow = _load_controller(candidate_root)
    if not dev_flow._same_path(local_repo, unc_repo):
        raise NativeValidationError(
            "CONTROLLER_IDENTITY_MISMATCH",
            "controller filesystem identity did not unify local and UNC aliases",
        )
    unc_fingerprint = dev_flow._fingerprint_repo(unc_repo)
    if not unc_fingerprint.get("tracked_worktree_manifest_sha256"):
        raise NativeValidationError(
            "TRACKED_MANIFEST_MISSING",
            "controller fingerprint omitted tracked-byte evidence",
        )
    _configure_local_origin(
        candidate_root,
        local_repo,
        local_child / "native-fixture-origin.git",
    )

    long_parent = local_child
    index = 0
    while len(str(long_parent)) < 285:
        index += 1
        long_parent = long_parent / (f"long-{index:02d}-" + "x" * 28)
    long_parent.mkdir(parents=True)
    worktree = long_parent / "managed-worktree-\u6d4b\u8bd5"
    contract = exercise_controller_managed_worktree(
        candidate_root,
        local_child / "managed-controller-state",
        local_repo,
        unc_repo,
        worktree,
        local_child,
    )
    common_main = _git(
        [
            "-C",
            str(unc_repo),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        candidate_root,
    )
    common_worktree = _git(
        [
            "-C",
            str(worktree),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        candidate_root,
    )
    if Path(
        common_main.decode("utf-8", "surrogateescape").strip()
    ).resolve() != Path(
        common_worktree.decode("utf-8", "surrogateescape").strip()
    ).resolve():
        raise NativeValidationError(
            "WORKTREE_COMMON_DIR_MISMATCH",
            "real Git worktree does not share the approved common directory",
        )
    final_fingerprint = dev_flow._fingerprint_repo(worktree)
    if final_fingerprint.get("branch") != "native/long-path-validation":
        raise NativeValidationError(
            "WORKTREE_BRANCH_MISMATCH",
            "real Git worktree postcondition branch did not match",
        )
    return {
        "diagnostic": "UNC_LONG_WORKTREE_BYTES_EXACT",
        "id": "unc-long-path-managed-worktree",
        "long_path_length": len(str(worktree)),
        "managed_contract": contract,
        "status": "passed",
    }


def _sentinel_payload(
    nonce: str,
    canonical: str,
    local_identity: str,
    unc_identity: str,
) -> bytes:
    return _stable_json_bytes(
        {
            "candidate_sha256": canonical,
            "local_root_identity_sha256": local_identity,
            "nonce": nonce,
            "schema_version": 1,
            "unc_root_identity_sha256": unc_identity,
        }
    )


def cleanup_owned_child(
    local_root: Path,
    child: Path,
    expected_sentinel: bytes,
) -> None:
    root = local_root.resolve(strict=True)
    candidate = child.resolve(strict=True)
    if candidate == root or candidate.parent != root:
        raise NativeValidationError(
            "CLEANUP_SCOPE_MISMATCH",
            "cleanup target is not one direct runner-owned child",
            incomplete=True,
        )
    if not candidate.name.startswith(CHILD_PREFIX):
        raise NativeValidationError(
            "CLEANUP_NAME_MISMATCH",
            "cleanup target lacks the runner-owned name prefix",
            incomplete=True,
        )
    sentinel = candidate / SENTINEL_NAME
    try:
        observed = sentinel.read_bytes()
    except OSError as exc:
        raise NativeValidationError(
            "CLEANUP_SENTINEL_MISSING",
            "cleanup sentinel is missing or unreadable",
            incomplete=True,
        ) from exc
    if observed != expected_sentinel:
        raise NativeValidationError(
            "CLEANUP_SENTINEL_MISMATCH",
            "cleanup sentinel does not match this run",
            incomplete=True,
        )
    shutil.rmtree(candidate)


def _base_report(
    expected: str,
    archive_sha256: Optional[str],
    local_root: Path,
    unc_root: Path,
    code_page: int,
) -> dict[str, Any]:
    return {
        "candidate": {
            "contract": candidate_identity.CONTRACT_VERSION,
            "expected_sha256": expected,
            "observed_sha256": None,
        },
        "checks": [],
        "cleanup": {"status": "not-started"},
        "handoff": {"archive_sha256": archive_sha256},
        "host": {
            "git": _git_version(),
            "os": platform.system(),
            "python": platform.python_version(),
        },
        "inputs": {
            "code_page": code_page,
            "local_root_class": _path_class(local_root),
            "local_root_identity_sha256": None,
            "unc_root_class": _path_class(unc_root),
            "unc_root_identity_sha256": None,
        },
        "result": "incomplete",
        "schema_version": REPORT_SCHEMA_VERSION,
    }


def _report_failure(
    report: dict[str, Any],
    error: NativeValidationError,
) -> None:
    report["checks"].append(
        {
            "diagnostic": error.code,
            "id": "native-validation",
            "status": "incomplete" if error.incomplete else "failed",
        }
    )
    report["result"] = "incomplete" if error.incomplete else "failed"


def run_native(args: argparse.Namespace) -> int:
    archive = Path(args.archive).expanduser().absolute()
    manifest_path = Path(args.manifest).expanduser().absolute()
    report_path = Path(args.report).expanduser().absolute()
    local_root = Path(args.local_root).expanduser().absolute()
    unc_root = Path(args.unc_root)
    expected = args.expected_canonical
    protected = [archive, manifest_path, local_root, unc_root]
    try:
        _report_preflight(report_path, protected)
    except NativeValidationError as exc:
        print(json.dumps({"code": exc.code, "result": "incomplete"}, sort_keys=True))
        return 2

    archive_sha256: Optional[str] = None
    try:
        archive_sha256 = candidate_identity._sha256_file(archive)
    except candidate_identity.CandidateIdentityError:
        pass
    report = _base_report(
        expected,
        archive_sha256,
        local_root,
        unc_root,
        args.code_page,
    )
    extraction: Optional[Path] = None
    child: Optional[Path] = None
    expected_sentinel: Optional[bytes] = None
    cleanup_error: Optional[NativeValidationError] = None
    try:
        candidate_identity.verify_handoff(archive, manifest_path, expected)
        report["checks"].append(
            {
                "diagnostic": "HANDOFF_VERIFIED",
                "id": "canonical-handoff",
                "status": "passed",
            }
        )
        if os.name != "nt":
            raise NativeValidationError(
                "NATIVE_WINDOWS_REQUIRED",
                "native PASS can only be produced on Windows",
                incomplete=True,
            )
        if not local_root.is_dir() or not unc_root.is_dir():
            raise NativeValidationError(
                "TEST_ROOT_MISSING",
                "both supplied test roots must already exist",
                incomplete=True,
            )
        if _path_class(unc_root) != "unc":
            raise NativeValidationError(
                "UNC_ROOT_REQUIRED",
                "the UNC root must use an explicit UNC spelling",
                incomplete=True,
            )
        if _is_broad_root(local_root, require_unc=False) or _is_broad_root(
            unc_root, require_unc=True
        ):
            raise NativeValidationError(
                "BROAD_ROOT_REJECTED",
                "drive and share roots are not valid test roots",
                incomplete=True,
            )
        if not _samefile(local_root, unc_root):
            raise NativeValidationError(
                "ROOT_ALIAS_MISMATCH",
                "local and UNC roots do not identify the same directory",
                incomplete=True,
            )
        if not os.access(local_root, os.W_OK):
            raise NativeValidationError(
                "ROOT_NOT_WRITABLE",
                "supplied test root is not writable",
                incomplete=True,
            )
        local_identity = _redacted_identity(local_root)
        unc_identity = _redacted_identity(unc_root)
        report["inputs"]["local_root_identity_sha256"] = local_identity
        report["inputs"]["unc_root_identity_sha256"] = unc_identity

        nonce = secrets.token_hex(16)
        extraction = report_path.parent / f".dev-flow-candidate-{nonce}"
        candidate_identity.extract_verified_handoff(
            archive,
            manifest_path,
            expected,
            extraction,
        )
        observed, _ = candidate_identity.candidate_digest(extraction)
        report["candidate"]["observed_sha256"] = observed
        if observed != expected:
            raise NativeValidationError(
                "EXTRACTED_CANDIDATE_MISMATCH",
                "extracted candidate does not match expected canonical digest",
            )

        child = local_root / f"{CHILD_PREFIX}{nonce}"
        unc_child = unc_root / child.name
        expected_sentinel = _sentinel_payload(
            nonce,
            expected,
            local_identity,
            unc_identity,
        )
        child.mkdir()
        (child / SENTINEL_NAME).write_bytes(expected_sentinel)
        if not _samefile(child, unc_child):
            raise NativeValidationError(
                "CHILD_ALIAS_MISMATCH",
                "runner-owned child is not reachable through both aliases",
            )
        report["checks"].append(_check_windows_mcp_launcher(extraction))
        report["checks"].append(_check_code_page(extraction, child, args.code_page))
        report["checks"].append(
            _check_windows_compact_hook_lifecycle(
                extraction,
                child,
                args.code_page,
            )
        )
        report["checks"].append(
            _check_paths_and_worktree(extraction, child, unc_child)
        )
        report["result"] = "passed"
    except candidate_identity.CandidateIdentityError as exc:
        _report_failure(
            report,
            NativeValidationError("HANDOFF_INVALID", str(exc), incomplete=True),
        )
    except NativeValidationError as exc:
        _report_failure(report, exc)
    except Exception as exc:
        _report_failure(
            report,
            NativeValidationError(
                "UNEXPECTED_NATIVE_FAILURE",
                f"unexpected native failure: {exc.__class__.__name__}",
            ),
        )
    finally:
        if child is not None and child.exists() and expected_sentinel is not None:
            if args.keep_owned_fixture_on_failure and report["result"] != "passed":
                cleanup_error = NativeValidationError(
                    "CLEANUP_INTENTIONALLY_RETAINED",
                    "runner-owned fixture was retained by explicit option",
                    incomplete=True,
                )
            else:
                try:
                    cleanup_owned_child(local_root, child, expected_sentinel)
                except NativeValidationError as exc:
                    cleanup_error = exc
        if extraction is not None and extraction.exists():
            try:
                shutil.rmtree(extraction)
            except OSError:
                cleanup_error = NativeValidationError(
                    "EXTRACTION_CLEANUP_FAILED",
                    "verified extraction directory could not be removed",
                    incomplete=True,
                )
        if cleanup_error is None:
            report["cleanup"] = {"status": "passed"}
        else:
            report["cleanup"] = {
                "diagnostic": cleanup_error.code,
                "status": "incomplete",
            }
            report["result"] = "incomplete"
        try:
            write_report_exclusive(report_path, report)
        except NativeValidationError as exc:
            print(json.dumps({"code": exc.code, "result": "incomplete"}, sort_keys=True))
            return 2
    print(
        json.dumps(
            {
                "report": str(report_path),
                "result": report["result"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["result"] == "passed" else 2


def prepare_handoff(args: argparse.Namespace) -> int:
    try:
        manifest = candidate_identity.build_handoff(
            Path(args.candidate_root),
            Path(args.archive),
            Path(args.manifest),
        )
    except candidate_identity.CandidateIdentityError as exc:
        print(
            json.dumps(
                {"code": "HANDOFF_PREPARE_FAILED", "detail": str(exc), "ok": False},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "archive_sha256": manifest["archive"]["sha256"],
                "candidate_sha256": manifest["candidate"]["sha256"],
                "contract": manifest["candidate"]["contract"],
                "ok": True,
                "path_count": manifest["candidate"]["path_count"],
            },
            sort_keys=True,
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a deterministic candidate handoff or produce canonical-bound "
            "native Windows validation evidence."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare",
        help="create a deterministic ZIP_STORED handoff and external manifest",
    )
    prepare.add_argument("--candidate-root", required=True)
    prepare.add_argument("--archive", required=True)
    prepare.add_argument("--manifest", required=True)
    prepare.set_defaults(handler=prepare_handoff)

    run = subparsers.add_parser(
        "run",
        help="run canonical-bound checks on a native Windows host",
    )
    run.add_argument("--archive", required=True)
    run.add_argument("--manifest", required=True)
    run.add_argument("--expected-canonical", required=True)
    run.add_argument("--local-root", required=True)
    run.add_argument("--unc-root", required=True)
    run.add_argument("--code-page", type=int, default=936)
    run.add_argument("--report", required=True)
    run.add_argument(
        "--keep-owned-fixture-on-failure",
        action="store_true",
        help=(
            "retain only the sentinel-owned child after a failed run for diagnosis; "
            "the report remains incomplete"
        ),
    )
    run.set_defaults(handler=run_native)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if (
        getattr(args, "expected_canonical", None)
        and not candidate_identity.SHA256_RE.fullmatch(args.expected_canonical)
    ):
        print(
            json.dumps(
                {
                    "code": "EXPECTED_CANONICAL_INVALID",
                    "result": "incomplete",
                },
                sort_keys=True,
            )
        )
        return 2
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
