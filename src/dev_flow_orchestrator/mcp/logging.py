"""Bounded, stderr-only diagnostics for the MCP adapter."""

from __future__ import annotations

import json
import logging
import sys
from typing import Iterable, Mapping, Optional, Sequence


LOGGER_NAME = "dev_flow_orchestrator.mcp"
MAX_DIAGNOSTIC_BYTES = 4 * 1024
_LOGGER = logging.getLogger(LOGGER_NAME)


def _bounded(value: str, maximum: int) -> str:
    raw = value.encode("utf-8")
    if len(raw) <= maximum:
        return value
    return raw[:maximum].decode("utf-8", errors="ignore")


def _redacted(value: object, redactions: Iterable[str]) -> object:
    secrets = tuple(sorted((item for item in redactions if item), key=len, reverse=True))
    if isinstance(value, str):
        result = value
        for secret in secrets:
            result = result.replace(secret, "<redacted>")
        return result
    if isinstance(value, Mapping):
        return {str(key): _redacted(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(item, secrets) for item in value]
    return value


def _event_bytes(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    if len(encoded.encode("utf-8")) <= MAX_DIAGNOSTIC_BYTES:
        return encoded
    fallback = {
        "level": value.get("level", "error"),
        "event": value.get("event", "diagnostic_truncated"),
        "request_id": value.get("request_id"),
        "tool": value.get("tool"),
        "code": value.get("code", "INTERNAL_ERROR"),
        "truncated": True,
    }
    return _bounded(
        json.dumps(fallback, sort_keys=True, separators=(",", ":")),
        MAX_DIAGNOSTIC_BYTES,
    )


def configure(level: str = "WARNING") -> None:
    """Configure only the MCP logger and keep its output on stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.handlers[:] = [handler]
    _LOGGER.setLevel(getattr(logging, level))
    _LOGGER.propagate = False


def emit(
    *,
    level: str,
    event: str,
    request_id: str,
    tool: str,
    code: str,
    frames: Sequence[Mapping[str, object]] = (),
    redactions: Iterable[str] = (),
) -> None:
    """Write one bounded event without payloads, contracts, paths, or messages."""
    value: dict[str, object] = {
        "level": level,
        "event": _bounded(event, 128),
        "request_id": _bounded(request_id, 64),
        "tool": _bounded(tool, 128),
        "code": _bounded(code, 128),
    }
    if frames:
        value["trace"] = list(frames[:8])
    value = _redacted(value, redactions)  # type: ignore[assignment]
    numeric_level = {
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get(level, logging.ERROR)
    _LOGGER.log(numeric_level, _event_bytes(value))


def write_startup_error(
    code: str,
    *,
    event: str = "startup_failed",
    message: Optional[str] = None,
) -> None:
    """Emit a bounded startup diagnostic before logging has been configured."""
    value = {
        "level": "error",
        "event": _bounded(event, 128),
        "request_id": None,
        "tool": None,
        "code": _bounded(code, 128),
    }
    if message:
        value["message"] = _bounded(message, 1024)
    sys.stderr.write(_event_bytes(value) + "\n")
