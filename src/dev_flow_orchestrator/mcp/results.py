"""Exact MCP result envelopes, bounded recovery, and redaction."""

from __future__ import annotations

import json
import uuid
from typing import Iterable, Mapping, Optional

from mcp.types import CallToolResult, TextContent

from ..model import DevFlowError
from .identity import MCP_RESULT_SCHEMA
from .schemas import validate_structured_result


MAX_TEXT_SUMMARY_BYTES = 4 * 1024
MAX_ERROR_MESSAGE_BYTES = 8 * 1024
MAX_ERROR_DETAILS_BYTES = 8 * 1024
RUNTIME_ERROR_CODES = frozenset({
    "MCP_RUNTIME_UNAVAILABLE",
    "MCP_DEPENDENCY_INVALID",
    "MCP_RESULT_LIMIT",
    "REQUEST_CANCELLED",
    "MCP_COMPLETION_UNCERTAIN",
    "INTERNAL_ERROR",
})


class MCPRuntimeFailure(RuntimeError):
    """A failure from the closed MCP runtime error boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
        recovery: Optional[Mapping[str, object]] = None,
    ) -> None:
        if code not in RUNTIME_ERROR_CODES:
            raise ValueError("unknown MCP runtime error code")
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.recovery = dict(recovery) if recovery is not None else None


def _bounded_text(value: object, maximum: int) -> str:
    text = str(value).strip()
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text
    return encoded[:maximum].decode("utf-8", errors="ignore")


def _recovery(
    kind: str,
    *,
    tool: Optional[str] = None,
    task_id: Optional[str] = None,
    blind_retry: bool = False,
) -> dict[str, object]:
    value: dict[str, object] = {"kind": kind, "blind_retry": blind_retry}
    if tool:
        value["tool"] = tool
    if task_id:
        value["task_id"] = task_id
    return value


def _recovery_for_domain(
    code: str,
    task_id: Optional[str],
    tool: str,
    details: Optional[Mapping[str, object]] = None,
) -> Optional[dict[str, object]]:
    if code in {"TASK_NOT_FOUND", "TASK_ID_INVALID"}:
        return _recovery(
            "discover-task",
            tool="dev_flow_find_tasks_for_path",
            blind_retry=False,
        )
    if code in {
        "ACTION_BINDING_INVALID",
        "ACTION_BINDING_MISMATCH",
        "ACTION_BINDING_STALE",
        "ACTION_MISMATCH",
        "REVISION_CONFLICT",
        "SNAPSHOT_UNSTABLE",
        "STALE_MUTATION",
        "WORKSPACE_CHANGED",
    }:
        return _recovery(
            "refresh-current-action",
            tool="dev_flow_get_next_action",
            task_id=task_id,
            blind_retry=False,
        )
    if code in {"CURSOR_INVALID", "PAYLOAD_LIMIT", "VIEW_QUERY_INVALID"}:
        return _recovery("correct-request", blind_retry=False)
    if code == "STATE_LOCK_TIMEOUT":
        return _recovery("retry-later", blind_retry=True)
    if (
        code == "STATE_LIMIT_EXCEEDED"
        and isinstance(details, Mapping)
        and details.get("phase") == "candidate-write"
    ):
        if tool == "dev_flow_apply_action":
            return _recovery(
                "refresh-current-action",
                tool="dev_flow_get_next_action",
                task_id=task_id,
                blind_retry=False,
            )
        return _recovery("correct-request", blind_retry=False)
    if code in {"STATE_INVALID", "STATE_LIMIT_EXCEEDED", "STATE_READ_FAILED"}:
        return _recovery(
            "inspect-diagnostics",
            task_id=task_id,
            blind_retry=False,
        )
    if code == "NODE_OUTPUT_INVALID" and tool == "dev_flow_apply_action":
        return _recovery(
            "correct-request",
            tool="dev_flow_apply_action",
            task_id=task_id,
            blind_retry=False,
        )
    if code == "IMPACT_INVALID" and tool == "dev_flow_apply_action":
        return _recovery(
            "refresh-current-action",
            tool="dev_flow_get_next_action",
            task_id=task_id,
            blind_retry=False,
        )
    return None


def _bounded_json(value: object, maximum: int) -> object:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return {"bounded": True, "reason": "details were not canonical JSON"}
    if len(encoded) <= maximum:
        return value
    return {"bounded": True, "reason": "details exceeded the MCP result limit"}


def _redact(value: object, redactions: Iterable[str]) -> object:
    secrets = tuple(sorted((item for item in redactions if item), key=len, reverse=True))
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "<redacted-data-root>")
        return redacted
    if isinstance(value, Mapping):
        return {str(key): _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    return value


def _call_result(tool: str, envelope: dict[str, object], text: str) -> CallToolResult:
    validate_structured_result(tool, envelope)
    return CallToolResult(
        content=[TextContent(text=_bounded_text(text, MAX_TEXT_SUMMARY_BYTES))],
        structuredContent=envelope,
        isError=not bool(envelope["ok"]),
    )


def success(tool: str, result: object, summary: str, request_id: str) -> CallToolResult:
    envelope = {
        "schema": MCP_RESULT_SCHEMA,
        "ok": True,
        "tool": tool,
        "request_id": request_id,
        "result": result,
        "error": None,
    }
    return _call_result(tool, envelope, summary)


def domain_error(
    tool: str,
    error: DevFlowError,
    request_id: str,
    *,
    task_id: Optional[str] = None,
    redactions: Iterable[str] = (),
) -> CallToolResult:
    raw = error.as_dict().get("error", {})
    details = raw.get("details", {}) if isinstance(raw, Mapping) else {}
    code = raw.get("code", error.code) if isinstance(raw, Mapping) else error.code
    message = raw.get("message", "Dev Flow rejected the request") if isinstance(raw, Mapping) else str(error)
    details = _redact(details, redactions)
    bounded_message = _bounded_text(
        _redact(message, redactions),
        MAX_ERROR_MESSAGE_BYTES,
    ) or "Dev Flow rejected the request."
    envelope = {
        "schema": MCP_RESULT_SCHEMA,
        "ok": False,
        "tool": tool,
        "request_id": request_id,
        "result": None,
        "error": {
            "code": code,
            "message": bounded_message,
            "details": _bounded_json(details, MAX_ERROR_DETAILS_BYTES),
            "recovery": _recovery_for_domain(
                str(code),
                task_id,
                tool,
                details if isinstance(details, Mapping) else None,
            ),
        },
    }
    text = "{}{}; request {}".format(
        code,
        " for task {}".format(task_id) if task_id else "",
        request_id,
    )
    recovery = envelope["error"]["recovery"]  # type: ignore[index]
    if isinstance(recovery, Mapping) and isinstance(recovery.get("tool"), str):
        text += "; next safe operation: {}".format(recovery["tool"])
    return _call_result(tool, envelope, text)


def runtime_error(
    tool: str,
    failure: MCPRuntimeFailure,
    request_id: str,
    *,
    redactions: Iterable[str] = (),
) -> CallToolResult:
    details = _redact(failure.details, redactions)
    message = _bounded_text(
        _redact(failure.message, redactions),
        MAX_ERROR_MESSAGE_BYTES,
    ) or "The MCP runtime could not complete the request."
    recovery = _redact(failure.recovery, redactions) if failure.recovery is not None else None
    envelope = {
        "schema": MCP_RESULT_SCHEMA,
        "ok": False,
        "tool": tool,
        "request_id": request_id,
        "result": None,
        "error": {
            "code": failure.code,
            "message": message,
            "details": _bounded_json(details, MAX_ERROR_DETAILS_BYTES),
            "recovery": recovery,
        },
    }
    text = "{}; request {}".format(failure.code, request_id)
    if isinstance(recovery, Mapping) and isinstance(recovery.get("tool"), str):
        text += "; next safe operation: {}".format(recovery["tool"])
    return _call_result(tool, envelope, text)


def cancelled_failure() -> MCPRuntimeFailure:
    return MCPRuntimeFailure(
        "REQUEST_CANCELLED",
        "The request was cancelled before Controller entry.",
        recovery=None,
    )


def completion_uncertain_failure(
    *,
    task_id: Optional[str],
    recovery_tool: str,
) -> MCPRuntimeFailure:
    return MCPRuntimeFailure(
        "MCP_COMPLETION_UNCERTAIN",
        "The mutation may have committed; read authoritative state before any retry.",
        details={"task_id": task_id} if task_id else {},
        recovery=_recovery(
            "read-after-write",
            tool=recovery_tool,
            task_id=task_id,
            blind_retry=False,
        ),
    )


def internal_error(tool: str, request_id: str) -> CallToolResult:
    return runtime_error(
        tool,
        MCPRuntimeFailure(
            "INTERNAL_ERROR",
            "The MCP adapter encountered an unexpected error.",
            recovery=_recovery("inspect-diagnostics", blind_retry=False),
        ),
        request_id,
    )


def new_request_id() -> str:
    return "mcp-{}".format(uuid.uuid4())
