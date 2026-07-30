# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Errors, workflow constants, redaction, paths, and V4 state I/O.
from __future__ import annotations

import argparse
import contextlib
import contextvars
import datetime as dt
import errno
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlsplit, urlunsplit

import fcntl


# Auxiliary records and plugin configuration use independently versioned
# generic protocols. Every task snapshot uses the V4 task schema.
SCHEMA_VERSION = 1
SUPPORTED_TASK_SCHEMA_VERSIONS = {V4_TASK_SCHEMA_VERSION}
CONFIG_SCHEMA_VERSION = 2
SUPPORTED_CONFIG_SCHEMA_VERSIONS = {1, CONFIG_SCHEMA_VERSION}
EVIDENCE_CONTRACT_VERSION = 2
CONFIRMATION_CONTRACT_VERSION = 1
IMPACT_ANALYSIS_CONTRACT_VERSION = 1
TERMINAL_STATES = {"DONE", "CANCELLED"}
ORDERED_STATES = [
    "INTAKE",
    "PREFLIGHTED",
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
]
ALL_STATES = set(ORDERED_STATES) | {"BLOCKED", "CANCELLED"}
FLOW_MODES = ("full", "lite")
DEFAULT_FLOW = "full"
LOW_RISK_CHANGE_CATEGORIES = ("docs", "internal", "tests")
FULL_FLOW_CHANGE_CATEGORIES = (
    "auth",
    "cross-repo",
    "infrastructure",
    "migration",
    "public-api",
    "schema",
)
CHANGE_CATEGORIES = (
    *LOW_RISK_CHANGE_CATEGORIES,
    *FULL_FLOW_CHANGE_CATEGORIES,
)
DEFAULT_PROTECTED_PATH_GLOBS = (
    ".github/workflows/**",
    ".gitmodules",
    "**/alembic/**",
    "**/api/**",
    "**/auth/**",
    "**/migrations/**",
    "**/schema/**",
    "**/schemas/**",
    "**/security/**",
    "**/*.graphql",
    "**/*.proto",
    "**/*.sql",
    "**/*.tf",
    "deploy/**",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "Dockerfile*",
    "infra/**",
    "infrastructure/**",
    "k8s/**",
    "terraform/**",
)


def _declared_risk_reasons(
    repository_count: int,
    categories: Sequence[str],
    target_paths: Sequence[str],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the canonical reasons for the immutable start declaration."""

    reasons: list[dict[str, Any]] = []
    if repository_count > 1:
        reasons.append(
            {
                "code": "cross_repository",
                "repository_count": repository_count,
            }
        )
    if not categories:
        reasons.append({"code": "change_category_unknown"})
    for category in categories:
        if category in FULL_FLOW_CHANGE_CATEGORIES:
            reasons.append(
                {"code": "full_only_category", "category": category}
            )
        elif category not in LOW_RISK_CHANGE_CATEGORIES:
            reasons.append(
                {"code": "change_category_unknown", "category": category}
            )
    if not target_paths:
        reasons.append({"code": "target_paths_unknown"})
    for relative_path in target_paths:
        pattern = _protected_path_match(relative_path, policy)
        if pattern is not None:
            reasons.append(
                {
                    "code": "protected_path",
                    "path": relative_path,
                    "pattern": pattern,
                }
            )
    return reasons
FLOW_NAMES_ZH = {
    "full": "完整流程",
    "lite": "精简流程",
}
STATE_NAMES_ZH = {
    "INTAKE": "需求接收",
    "PREFLIGHTED": "预检完成",
    "BASELINED": "基线就绪",
    "INDEXED": "索引完成",
    "IMPACT_REVIEW": "影响评审",
    "ROUTE_APPROVED": "路线已批准",
    "WORKSPACE_READY": "工作区就绪",
    "PLANNING": "方案规划",
    "IMPLEMENTING": "实现中",
    "VERIFYING": "验证中",
    "REVIEWING": "独立审查",
    "FINALIZING": "交付确认",
    "DONE": "已完成",
    "BLOCKED": "已阻塞",
    "CANCELLED": "已取消",
}
FLOW_BY_WORKSPACE_STRATEGY = {
    "branch": "lite",
    "in-place": "lite",
    "worktree": "full",
}
WORKSPACE_STRATEGIES = tuple(FLOW_BY_WORKSPACE_STRATEGY)
WORKSPACE_STRATEGY_NAMES_ZH = {
    "branch": "新建并切换分支",
    "in-place": "使用当前分支",
    "worktree": "创建独立工作树",
}
LITE_GATE = "lite"
FULL_GATES = (
    "baseline-fetch",
    "impact-degraded",
    "route",
    "workspace",
    "plan",
    "review",
)
# One vocabulary shared by the argparse surface and the approve dispatch, so
# an unrecognized gate can never record an approval, consume a revision, or
# skip the status/flow assertions bound to each real gate.
APPROVAL_GATES = (*FULL_GATES, LITE_GATE)
# The lite flow works in place inside the user's own checkouts.  It keeps
# preflight evidence, one explicit human gate, and test-currency enforcement,
# and deliberately has no baseline, index, impact, route, managed workspace,
# plan, or independent-review machinery.
LITE_ORDERED_STATES = [
    "INTAKE",
    "PREFLIGHTED",
    "IMPLEMENTING",
    "VERIFYING",
    "DONE",
]
def _require_automatic_action(
    state_value: dict[str, Any],
    action: str,
    source: str,
    target: str,
) -> None:
    try:
        bundle = _workflow_transition_bundle(state_value)
    except TransitionEngineError as exc:
        raise FlowError(exc.code, exc.message, details=exc.details) from exc
    matches = [
        edge
        for edge in bundle.legal_edges(source)
        if edge.get("target") == target
        and edge.get("automatic") is True
        and isinstance(edge.get("trigger"), Mapping)
        and edge["trigger"].get("id") == action
    ]
    if len(matches) != 1:
        raise FlowError(
            "AUTOMATIC_ACTION_NOT_ALLOWED",
            "the task-pinned V4 bundle does not authorize this automatic action",
            details={
                "action": action,
                "source_status": source,
                "target_status": target,
            },
        )
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_PROTECTED_BRANCHES = ["main", "master", "trunk"]
REVIEW_VERDICTS = {"PASS", "CONDITIONAL", "FAIL"}
REVIEW_VERDICT_RE = re.compile(
    r"^Verdict: (PASS|CONDITIONAL|FAIL)$", re.MULTILINE
)
BASELINE_INDEX_STATES = {
    "BASELINED",
    "INDEXED",
    "IMPACT_REVIEW",
    "ROUTE_APPROVED",
}
WORKSPACE_INDEX_STATES = {
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
    "DONE",
}
SCOPE_MODES = ("all", "allowlist")
SCOPE_INCLUDE_ENV = "DEV_FLOW_SCOPE"
SCOPE_EXCLUDE_ENV = "DEV_FLOW_SCOPE_EXCLUDE"
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.05
_FILESYSTEM_CASE_CACHE: dict[Any, bool] = {}
_FILESYSTEM_UNICODE_CACHE: dict[Any, bool] = {}
_HELD_LOCK_DIRECTORIES: contextvars.ContextVar[tuple[str, ...]] = (
    contextvars.ContextVar("dev_flow_held_lock_directories", default=())
)
_IN_PROCESS_FILE_LOCKS_GUARD = threading.Lock()
_IN_PROCESS_FILE_LOCKS: dict[str, tuple[Any, int]] = {}
_ACTIVE_MUTATION_INTENTS: contextvars.ContextVar[tuple[str, ...]] = (
    contextvars.ContextVar("dev_flow_active_mutation_intents", default=())
)
_URL_VALUE_RE = re.compile(r"(?:https?|ssh|git|file)://[^\s'\"<>]+", re.IGNORECASE)
_SCP_REMOTE_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])(?P<user>[^/\s@'\"<>]+)@"
    r"(?P<host>\[[^\]\s]+\]|[A-Za-z0-9._-]+):(?P<path>[^\s'\"<>]+)"
)
_AUTHORIZATION_VALUE_RE = re.compile(
    r"(?i)(\b(?:proxy-)?authorization\s*:\s*(?:bearer|basic|token)\s+)"
    r"([^\s,;]+)"
)
_SENSITIVE_VALUE_RE = re.compile(
    r"""(?ix)
    \b
    (?P<key>
       access[_-]?token|token|auth(?:orization)?|password|passwd|secret|
       api[_-]?key|apikey|credential|private[_-]?key|signature|sig
    )
    \b
    (?P<separator>\s*(?:=|:)\s*)
    (?P<value>"[^"]*"|'[^']*'|[^\s,;]+)
    """
)
_SENSITIVE_OPTION_VALUE_RE = re.compile(
    r"""(?ix)
    (?P<option>
       (?<!\S)--(?:
          access[_-]?token|token|auth(?:orization)?|password|passwd|secret|
          api[_-]?key|apikey|credential|private[_-]?key|signature|sig
       )
    )
    (?P<separator>\s+)
    (?P<value>"[^"]*"|'[^']*'|[^\s,;]+)
    """
)
_SENSITIVE_FIELD_NAMES = {
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "password",
    "passwords",
    "passwd",
    "private_key",
    "secret",
    "secrets",
    "sig",
    "signature",
    "token",
    "tokens",
}
_SENSITIVE_COMMAND_OPTIONS = {
    "--access-token",
    "--access_token",
    "--api-key",
    "--api_key",
    "--apikey",
    "--authorization",
    "--credential",
    "--password",
    "--passwd",
    "--private-key",
    "--private_key",
    "--secret",
    "--sig",
    "--signature",
    "--token",
}
_UNSTRUCTURED_TEXT_FIELDS = {
    "cause",
    "detail",
    "diagnostic",
    "error",
    "message",
    "stderr",
    "stdout",
}
_PUBLIC_PROTOCOL_TOKEN_PARENTS = {
    "confirmed_preview",
    "transition_preview",
}


class FlowError(Exception):
    """A predictable user-facing error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 2,
    ) -> None:
        # Error objects are also consumed directly by the hook and focused
        # callers, not only by ``main``.  Redact at construction as well as at
        # the protocol boundary so raw child output has no alternate route to
        # a user-visible response.
        safe_message = _redact_sensitive_text(message)
        safe_details = _redact_sensitive_value(details or {})
        super().__init__(safe_message)
        self.code = code
        self.message = safe_message
        self.details = safe_details
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise FlowError("INVALID_ARGUMENT", message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _nonempty(value: Any) -> str | None:
    """Return a stripped non-empty environment/argument value."""

    if value is None:
        return None
    text = os.fspath(value) if isinstance(value, os.PathLike) else str(value)
    text = text.strip()
    return text or None


def _redact_url(value: str) -> str:
    """Return a safe display form without URL credentials or query values."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<redacted-url>" if "@" in value or "?" in value else value
    if not parsed.scheme or not parsed.netloc or host is None:
        return value
    host_display = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = host_display
    if parsed.username is not None or parsed.password is not None:
        netloc = f"<redacted>@{netloc}"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            "<redacted>" if parsed.query else "",
            "<redacted>" if parsed.fragment else "",
        )
    )


def _redact_sensitive_text(value: str) -> str:
    """Remove credential-like material before it reaches durable or CLI JSON."""

    # Git's scp-like remote syntax (``user:token@host:path``) has no URL
    # scheme, so scrub it before URL handling.  Deliberately hiding an
    # ordinary remote account name is preferable to ever exposing a token.
    redacted = _SCP_REMOTE_VALUE_RE.sub(
        lambda match: f"<redacted>@{match.group('host')}:{match.group('path')}",
        value,
    )
    redacted = _URL_VALUE_RE.sub(
        lambda match: _redact_url(match.group(0)), redacted
    )
    redacted = _AUTHORIZATION_VALUE_RE.sub(r"\1<redacted>", redacted)
    redacted = _SENSITIVE_OPTION_VALUE_RE.sub(
        lambda match: (
            f"{match.group('option')}{match.group('separator')}<redacted>"
        ),
        redacted,
    )
    return _SENSITIVE_VALUE_RE.sub(
        lambda match: (
            f"{match.group('key')}{match.group('separator')}<redacted>"
        ),
        redacted,
    )


def _normalized_sensitive_field_name(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _field_contains_unstructured_text(field_name: str) -> bool:
    normalized = _normalized_sensitive_field_name(field_name)
    return (
        normalized in _UNSTRUCTURED_TEXT_FIELDS
        or any(
            normalized.endswith(f"_{suffix}")
            for suffix in _UNSTRUCTURED_TEXT_FIELDS
        )
    )


def _redacted_sensitive_field_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return "<redacted>"


def _redact_sensitive_value(value: Any, *, field_name: str | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, nested in value.items():
            normalized = _normalized_sensitive_field_name(key)
            parent = (
                _normalized_sensitive_field_name(field_name)
                if field_name is not None
                else ""
            )
            if (
                normalized == "token"
                and parent in _PUBLIC_PROTOCOL_TOKEN_PARENTS
            ):
                result[key] = _redact_sensitive_value(
                    nested, field_name=normalized
                )
            elif normalized in _SENSITIVE_FIELD_NAMES:
                result[key] = _redacted_sensitive_field_value(nested)
            elif normalized == "command" or normalized.endswith("_command"):
                if isinstance(nested, (list, tuple)):
                    result[key] = _redacted_command(nested)
                elif isinstance(nested, str):
                    result[key] = _redact_sensitive_text(nested)
                else:
                    result[key] = _redact_sensitive_value(
                        nested, field_name=normalized
                    )
            elif normalized == "url" or normalized.endswith("_url"):
                result[key] = (
                    _redact_sensitive_text(nested)
                    if isinstance(nested, str)
                    else _redact_sensitive_value(nested, field_name=normalized)
                )
            elif _field_contains_unstructured_text(normalized):
                result[key] = (
                    _redact_sensitive_text(nested)
                    if isinstance(nested, str)
                    else _redact_sensitive_value(nested, field_name=normalized)
                )
            else:
                result[key] = _redact_sensitive_value(
                    nested, field_name=normalized
                )
        return result
    if isinstance(value, list):
        return [
            _redact_sensitive_value(item, field_name=field_name)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_sensitive_value(item, field_name=field_name)
            for item in value
        )
    if isinstance(value, str):
        if field_name is None or _field_contains_unstructured_text(field_name):
            return _redact_sensitive_text(value)
        return value
    return value


def _redact_state_in_place(value: dict[str, Any]) -> None:
    redacted = _redact_sensitive_value(value)
    if not isinstance(redacted, dict):  # Defensive: the input contract is dict.
        raise TypeError("state redaction produced a non-object value")
    value.clear()
    value.update(redacted)


def _redacted_command(command: Sequence[str]) -> list[str]:
    result: list[str] = []
    redact_next = False
    for argument in command:
        raw = str(argument)
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        result.append(_redact_sensitive_text(raw))
        option = raw.split("=", 1)[0].lower()
        if "=" not in raw and option in _SENSITIVE_COMMAND_OPTIONS:
            redact_next = True
    return result


def _sensitive_value_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve state storage using CLI, environment, then macOS app support.

    Resolution order is deliberately exposed for hooks: explicit ``data_dir``;
    ``DEV_FLOW_DATA_DIR``; ``PLUGIN_DATA``; finally the user's state directory.
    The returned path is absolute, but this function does not create it.
    """

    candidate = _nonempty(data_dir)
    if candidate is None:
        candidate = _nonempty(os.environ.get("DEV_FLOW_DATA_DIR"))
    if candidate is None:
        candidate = _nonempty(os.environ.get("PLUGIN_DATA"))
    if candidate is None:
        candidate = str(
            Path.home()
            / "Library"
            / "Application Support"
            / "dev-flow-orchestrator"
        )
    return Path(candidate).expanduser().resolve(strict=False)


def _validate_task_id(task_id: str) -> str:
    encoded_length = len(task_id.encode("ascii", "ignore"))
    if (
        not task_id.isascii()
        or encoded_length != len(task_id)
        or not TASK_ID_RE.fullmatch(task_id)
        or task_id.endswith(".")
    ):
        raise FlowError(
            "INVALID_TASK_ID",
            (
                "task id must be 1-64 ASCII bytes matching "
                "[A-Za-z0-9][A-Za-z0-9._-]{0,63} and must not end in '.'"
            ),
            details={
                "task_id": task_id,
                "ascii_bytes": encoded_length if task_id.isascii() else None,
            },
        )
    return task_id


def _task_identity(task_id: str) -> str:
    return _validate_task_id(task_id).lower()


def _task_dir(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "tasks" / _validate_task_id(task_id)


def _state_path(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return _task_dir(task_id, data_dir) / "state.json"


def _nearest_existing_path(path: Path) -> tuple[Path, tuple[str, ...]]:
    """Return the nearest existing ancestor and the uncreated suffix."""

    suffix: list[str] = []
    current = path.expanduser()
    while not current.exists():
        if current.parent == current:
            raise FlowError(
                "PATH_IDENTITY_UNAVAILABLE",
                "path has no existing ancestor whose filesystem identity can be verified",
                details={"path": str(path)},
            )
        suffix.append(current.name)
        current = current.parent
    try:
        ancestor = current.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not resolve an existing path ancestor",
            details={"path": str(path), "ancestor": str(current), "error": str(exc)},
        ) from exc
    return ancestor, tuple(reversed(suffix))


def _stable_existing_identity(path: Path) -> dict[str, Any]:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not read stable filesystem identity",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    return {
        "kind": "posix-file-id",
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "final_path": str(path.resolve(strict=True)),
    }


def _probe_filesystem_case_sensitive(existing: Path) -> bool:
    """Probe case behavior on the same filesystem and clean up unconditionally."""

    probe_parent = existing if existing.is_dir() else existing.parent
    stable = _stable_existing_identity(probe_parent)
    cache_key: Any = ("posix-device", stable.get("device"))
    cached = _FILESYSTEM_CASE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    probe_dir: Path | None = None
    try:
        probe_dir = Path(
            tempfile.mkdtemp(prefix=".dev-flow-case-", dir=str(probe_parent))
        )
        mixed = probe_dir / "CaseProbe"
        alternate = probe_dir / "caseprobe"
        mixed.write_bytes(b"case")
        case_sensitive = not alternate.exists()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not verify filesystem case behavior",
            details={"path": str(probe_parent), "error": str(exc)},
        ) from exc
    finally:
        if probe_dir is not None:
            try:
                shutil.rmtree(probe_dir)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "PATH_IDENTITY_UNAVAILABLE",
                    "filesystem case probe could not be cleaned up safely",
                    details={"path": str(probe_dir), "error": str(exc)},
                ) from exc
    _FILESYSTEM_CASE_CACHE[cache_key] = case_sensitive
    return case_sensitive


def _probe_filesystem_unicode_distinct(existing: Path) -> bool:
    probe_parent = existing if existing.is_dir() else existing.parent
    stable = _stable_existing_identity(probe_parent)
    cache_key: Any = (
        "posix-device",
        stable.get("device"),
    )
    cached = _FILESYSTEM_UNICODE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    probe_dir: Path | None = None
    try:
        probe_dir = Path(
            tempfile.mkdtemp(prefix=".dev-flow-unicode-", dir=str(probe_parent))
        )
        composed = probe_dir / "\u00e9"
        decomposed = probe_dir / "e\u0301"
        composed.write_bytes(b"unicode")
        distinct = not decomposed.exists()
    except OSError as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "could not verify filesystem Unicode normalization behavior",
            details={"path": str(probe_parent), "error": str(exc)},
        ) from exc
    finally:
        if probe_dir is not None:
            try:
                shutil.rmtree(probe_dir)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FlowError(
                    "PATH_IDENTITY_UNAVAILABLE",
                    "filesystem Unicode probe could not be cleaned up safely",
                    details={"path": str(probe_dir), "error": str(exc)},
                ) from exc
    _FILESYSTEM_UNICODE_CACHE[cache_key] = distinct
    return distinct


def _filesystem_identity(path: Path) -> dict[str, Any]:
    """Return a canonical identity for existing and planned filesystem paths."""

    try:
        supplied = Path(
            os.path.abspath(os.fspath(path.expanduser()))
        )
    except (OSError, TypeError, ValueError) as exc:
        raise FlowError(
            "PATH_IDENTITY_UNAVAILABLE",
            "path spelling could not be normalized safely",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    ancestor, suffix = _nearest_existing_path(supplied)
    stable_ancestor = _stable_existing_identity(ancestor)
    case_sensitive = _probe_filesystem_case_sensitive(ancestor)
    unicode_distinct = _probe_filesystem_unicode_distinct(ancestor)

    def normalize(value: str) -> str:
        return (
            value
            if unicode_distinct
            else unicodedata.normalize("NFC", value)
        )

    display = ancestor.joinpath(*suffix)
    canonical_ancestor = Path(
        str(stable_ancestor.get("final_path") or ancestor)
    )
    canonical_display = canonical_ancestor.joinpath(*suffix)
    normalized = normalize(
        os.path.normpath(str(canonical_display))
    )
    if not case_sensitive:
        normalized = normalized.casefold()
    try:
        anchor = canonical_ancestor.anchor or str(
            canonical_ancestor
        )
        relative = canonical_ancestor.relative_to(anchor)
        anchor_normalized = normalize(str(anchor))
        relative_parts = tuple(
            normalize(part) for part in relative.parts
        )
    except (TypeError, ValueError):
        anchor_normalized = normalize(canonical_ancestor.anchor)
        relative_parts = tuple(
            normalize(part) for part in canonical_ancestor.parts
        )
    suffix_parts = tuple(normalize(part) for part in suffix)
    identity_parts = relative_parts + suffix_parts
    if not case_sensitive:
        anchor_normalized = anchor_normalized.casefold()
        identity_parts = tuple(part.casefold() for part in identity_parts)
    return {
        "path": str(display),
        "normalized": normalized,
        "anchor": anchor_normalized,
        "parts": identity_parts,
        "case_sensitive": case_sensitive,
        "unicode_normalization_distinct": unicode_distinct,
        "ancestor": str(ancestor),
        "ancestor_identity": {
            key: value
            for key, value in stable_ancestor.items()
            if key != "final_path"
        },
        "suffix_parts": suffix_parts,
    }


def _same_path(left: Path, right: Path) -> bool:
    if left.exists() and right.exists():
        try:
            return os.path.samefile(left, right)
        except OSError:
            pass
    left_identity = _filesystem_identity(left)
    right_identity = _filesystem_identity(right)
    same_ancestor = (
        left_identity.get("ancestor_identity")
        == right_identity.get("ancestor_identity")
        and left_identity.get("suffix_parts")
        == right_identity.get("suffix_parts")
    )
    return (
        (
            same_ancestor
            or left_identity.get("normalized")
            == right_identity.get("normalized")
            or (
                left_identity["anchor"]
                == right_identity["anchor"]
                and left_identity["parts"]
                == right_identity["parts"]
            )
        )
        and left_identity["case_sensitive"]
        == right_identity["case_sensitive"]
        and left_identity["unicode_normalization_distinct"]
        == right_identity["unicode_normalization_distinct"]
    )


def _serializable_path_identity(path: Path) -> dict[str, Any]:
    identity = _filesystem_identity(path)
    return {
        "normalized": identity["normalized"],
        "anchor": identity["anchor"],
        "parts": list(identity["parts"]),
        "case_sensitive": identity["case_sensitive"],
        "unicode_normalization_distinct": identity[
            "unicode_normalization_distinct"
        ],
        "ancestor_identity": identity.get("ancestor_identity"),
        "suffix_parts": list(identity.get("suffix_parts") or ()),
    }


def _capability_path_identity(path: Path) -> dict[str, Any]:
    """Return the location fields that stay stable across path creation.

    Stable file IDs intentionally change when a previously planned path is
    materialized: before creation they identify the nearest existing ancestor,
    while afterwards they identify the new directory itself.  Capability
    profiles need to bind the canonical location without treating that expected
    transition as capability drift.  Ownership checks continue to use the full
    serializable identity, including file IDs.
    """

    identity = _serializable_path_identity(path)
    return {
        "normalized": identity["normalized"],
        "anchor": identity["anchor"],
        "parts": identity["parts"],
        "case_sensitive": identity["case_sensitive"],
        "unicode_normalization_distinct": identity[
            "unicode_normalization_distinct"
        ],
    }


def _path_identity_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    modern_identity = (
        isinstance(left.get("ancestor_identity"), dict)
        and isinstance(right.get("ancestor_identity"), dict)
    )
    location_matches = (
        (
            isinstance(left.get("normalized"), str)
            and left.get("normalized") == right.get("normalized")
        )
        or (
            modern_identity
            and left.get("ancestor_identity")
            == right.get("ancestor_identity")
            and tuple(left.get("suffix_parts") or ())
            == tuple(right.get("suffix_parts") or ())
        )
        or (
            left.get("anchor") == right.get("anchor")
            and tuple(left.get("parts") or ())
            == tuple(right.get("parts") or ())
        )
    )
    return (
        location_matches
        and left.get("case_sensitive") == right.get("case_sensitive")
        and left.get("unicode_normalization_distinct")
        == right.get("unicode_normalization_distinct")
    )


def _recorded_path_matches(
    recorded_identity: Any, recorded_path: Any, candidate: Path
) -> bool:
    candidate_identity = _serializable_path_identity(candidate)
    if isinstance(recorded_identity, dict):
        return _path_identity_equal(recorded_identity, candidate_identity)
    if not recorded_path:
        return False
    return _same_path(Path(str(recorded_path)), candidate)


def _declared_evidence_versions(value: Any) -> Iterator[int]:
    if isinstance(value, dict):
        declared = value.get("evidence_contract_version")
        if declared is not None:
            if not isinstance(declared, int) or isinstance(declared, bool):
                raise FlowError(
                    "EVIDENCE_CONTRACT_INVALID",
                    "evidence contract versions must be integers",
                    details={"value": declared},
                )
            yield declared
        for key, nested in value.items():
            # ``metadata`` is an explicit user/integration namespace.  A
            # third-party payload may legitimately describe its own evidence
            # contract and must never be mistaken for this controller's
            # durable evidence version.
            if key == "metadata":
                continue
            yield from _declared_evidence_versions(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _declared_evidence_versions(nested)


def _assert_supported_evidence_versions(value: Any) -> None:
    newer = sorted(
        {
            version
            for version in _declared_evidence_versions(value)
            if version > EVIDENCE_CONTRACT_VERSION
        }
    )
    if newer:
        raise FlowError(
            "EVIDENCE_CONTRACT_UNSUPPORTED",
            "task evidence was created by a newer incompatible controller",
            details={
                "supported_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_versions": newer,
            },
        )


def _require_current_evidence(record: Any, label: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            f"{label} evidence is missing and must be regenerated",
            details={"label": label, "required_version": EVIDENCE_CONTRACT_VERSION},
        )
    version = record.get("evidence_contract_version")
    if version != EVIDENCE_CONTRACT_VERSION:
        if isinstance(version, int) and version > EVIDENCE_CONTRACT_VERSION:
            raise FlowError(
                "EVIDENCE_CONTRACT_UNSUPPORTED",
                f"{label} evidence uses a newer incompatible contract",
                details={
                    "label": label,
                    "supported_version": EVIDENCE_CONTRACT_VERSION,
                    "encountered_version": version,
                },
            )
        raise FlowError(
            "EVIDENCE_REGENERATION_REQUIRED",
            f"{label} evidence must use the current protocol version",
            details={
                "label": label,
                "required_version": EVIDENCE_CONTRACT_VERSION,
                "encountered_version": version,
            },
        )
    return record


def _validate_task_state_structure(path: Path, value: Any) -> int:
    """Validate only fields needed to identify a supported task snapshot."""

    schema_version = value.get("schema_version") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in SUPPORTED_TASK_SCHEMA_VERSIONS
    ):
        raise FlowError(
            "UNSUPPORTED_STATE",
            f"unsupported or invalid task state: {path}",
            details={
                "path": str(path),
                "schema_version": schema_version,
                "supported_schema_versions": sorted(
                    SUPPORTED_TASK_SCHEMA_VERSIONS
                ),
            },
        )
    stored_task_id = value.get("task_id")
    if not isinstance(stored_task_id, str):
        raise FlowError(
            "UNSUPPORTED_STATE",
            f"task state does not contain a valid task identifier: {path}",
            details={"path": str(path), "task_id": stored_task_id},
        )
    _validate_task_id(stored_task_id)
    return schema_version


def _validate_task_state_snapshot(
    path: Path,
    value: Any,
    *,
    resolve_workflow: bool = True,
) -> int:
    schema_version = _validate_task_state_structure(path, value)
    try:
        validate_v4_task_state(value)
        if resolve_workflow:
            resolve_loaded_task_workflow(
                value,
                purpose=(
                    "recovery"
                    if value.get("pending_event") is not None
                    or value.get("pending_events") is not None
                    else "inspection"
                ),
            )
    except (
        WorkflowCatalogError,
        WorkflowHandlerAuditError,
        WorkflowStateError,
    ) as exc:
        raise FlowError(
            getattr(exc, "code", "UNSUPPORTED_STATE"),
            getattr(
                exc,
                "message",
                "task workflow contract is unsupported or invalid",
            ),
            details={
                "path": str(path),
                **dict(getattr(exc, "details", {})),
            },
        ) from exc
    _assert_supported_evidence_versions(value)
    _validate_pending_event_outbox(path.parent, value)
    return schema_version


def _state_file_path(
    task_id: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
) -> Path:
    supplied = Path(task_id)
    if supplied.name == "state.json" or supplied.is_file():
        return supplied.expanduser().resolve(strict=False)
    return _state_path(str(task_id), data_dir)


def _read_task_state_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise FlowError(
            "TASK_NOT_FOUND",
            f"task state does not exist: {path}",
            details={"path": str(path)},
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "STATE_READ_FAILED",
            f"could not read task state: {path}",
            details={"path": str(path), "error": str(exc)},
        ) from exc


def _read_task_state_snapshot(path: Path) -> dict[str, Any]:
    value = _read_task_state_json(path)
    _validate_task_state_snapshot(path, value)
    return value


def _read_task_state_structural_snapshot(
    path: Path,
) -> dict[str, Any]:
    """Read validated state without resolving its pinned workflow.

    Mutation callers use this narrow phase so the expected-revision CAS check
    remains ahead of workflow resolution. Recovery and ordinary supported
    reads continue to use ``_read_task_state_snapshot`` and therefore still
    fail closed on an unavailable v4 bundle before delivering an outbox.
    """

    value = _read_task_state_json(path)
    _validate_task_state_structure(path, value)
    return value


def _finish_loaded_state(
    path: Path, value: dict[str, Any]
) -> dict[str, Any]:
    if (
        value.get("pending_event") is not None
        or value.get("pending_events") is not None
    ):
        value = _recover_pending_event(path, value)
    return value


def load_state(
    task_id: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load a task snapshot by id, or load an explicit ``state.json`` path."""

    path = _state_file_path(task_id, data_dir)
    return _finish_loaded_state(
        path, _read_task_state_snapshot(path)
    )


def load_state_for_inspection(
    task_id: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, Any], None]:
    """Load and validate the current V4 task snapshot."""

    return load_state(task_id, data_dir), None


def _is_within(path: Path, parent: Path) -> bool:
    path_identity = _filesystem_identity(path)
    parent_identity = _filesystem_identity(parent)

    def stable_id(identity: dict[str, Any]) -> dict[str, Any] | None:
        value = identity.get("ancestor_identity")
        return value if isinstance(value, dict) else None

    path_ancestor_id = stable_id(path_identity)
    parent_ancestor_id = stable_id(parent_identity)
    if (
        path_ancestor_id is not None
        and path_ancestor_id == parent_ancestor_id
    ):
        parent_suffix = tuple(
            parent_identity.get("suffix_parts") or ()
        )
        path_suffix = tuple(
            path_identity.get("suffix_parts") or ()
        )
        return (
            path_suffix[: len(parent_suffix)] == parent_suffix
        )

    # Existing descendants can cross a mapped-drive/UNC, symlink/junction, or
    # per-directory case-sensitivity boundary.  Textual anchors and capability
    # flags are not sufficient there, so walk the existing ancestor chain and
    # compare stable volume/file identities.  A non-existing parent is handled
    # by the common-ancestor/suffix rule above.
    if (
        parent_ancestor_id is not None
        and not tuple(parent_identity.get("suffix_parts") or ())
    ):
        candidate = Path(str(path_identity.get("ancestor") or ""))
        while candidate:
            try:
                candidate_stable = _stable_existing_identity(candidate)
            except FlowError:
                break
            candidate_id = {
                key: value
                for key, value in candidate_stable.items()
                if key != "final_path"
            }
            if candidate_id == parent_ancestor_id:
                return True
            if candidate.parent == candidate:
                break
            candidate = candidate.parent

    if (
        path_identity["case_sensitive"]
        != parent_identity["case_sensitive"]
        or path_identity["unicode_normalization_distinct"]
        != parent_identity["unicode_normalization_distinct"]
    ):
        return False
    if path_identity["anchor"] != parent_identity["anchor"]:
        return False
    parent_parts = parent_identity["parts"]
    return path_identity["parts"][: len(parent_parts)] == parent_parts


def find_active_task_for_cwd(
    cwd: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Return the sole non-terminal task whose repo/workspace contains cwd."""

    current = Path(cwd or os.getcwd()).expanduser().resolve(strict=False)
    tasks_dir = resolve_data_dir(data_dir) / "tasks"
    if not tasks_dir.is_dir():
        return None
    matches: list[dict[str, Any]] = []
    for state_file in tasks_dir.glob("*/state.json"):
        try:
            state_value = load_state(state_file)
        except FlowError:
            continue
        if state_value.get("status") in TERMINAL_STATES:
            continue
        for repo in state_value.get("repositories", []):
            candidates = [repo.get("path"), repo.get("canonical_path")]
            workspace = repo.get("workspace")
            if isinstance(workspace, dict):
                candidates.append(workspace.get("path"))
            analysis_workspace = repo.get("analysis_workspace")
            if isinstance(analysis_workspace, dict):
                candidates.append(analysis_workspace.get("path"))
            if any(
                item and _is_within(current, Path(item).expanduser().resolve(strict=False))
                for item in candidates
            ):
                matches.append(state_value)
                break
    if not matches:
        return None
    by_task_id = {
        str(value.get("task_id")): value
        for value in matches
        if isinstance(value.get("task_id"), str)
    }
    if len(by_task_id) != 1:
        raise FlowError(
            "ACTIVE_TASK_AMBIGUITY",
            "multiple active Dev Flow tasks match the current repository",
            details={
                "cwd": str(current),
                "task_ids": sorted(by_task_id),
                "match_count": len(matches),
                "recovery": (
                    "resolve or cancel the conflicting active tasks before "
                    "continuing in this repository"
                ),
            },
        )
    return next(iter(by_task_id.values()))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _set_private_permissions(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
        actual = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise FlowError(
            "PERMISSIONS_UNVERIFIABLE",
            "could not apply private controller storage permissions",
            details={"path": str(path), "mode": oct(mode), "error": str(exc)},
        ) from exc
    if actual != mode:
        raise FlowError(
            "PERMISSIONS_UNSAFE",
            "controller-managed storage permissions are broader than required",
            details={"path": str(path), "expected": oct(mode), "actual": oct(actual)},
        )


def _ensure_private_dir(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise FlowError(
                "PERMISSIONS_UNVERIFIABLE",
                "could not create private controller storage",
                details={"path": str(directory), "error": str(exc)},
            ) from exc
        _set_private_permissions(directory, 0o700)
    if not path.is_dir():
        raise FlowError(
            "PERMISSIONS_UNVERIFIABLE",
            "controller storage directory path is not a directory",
            details={"path": str(path)},
        )
    _set_private_permissions(path, 0o700)


_ROLLBACK_MARKER = ".rollback-"
_ROLLBACK_RECOVERY_COMMAND = "recover-atomic-write"


def _rollback_evidence_destination(candidate: Path) -> Path | None:
    """Map `.NAME.rollback-XXXX` back to the NAME it was captured for."""

    name = candidate.name
    if not name.startswith("."):
        return None
    destination, marker, _ = name[1:].rpartition(_ROLLBACK_MARKER)
    if not marker or not destination:
        return None
    return candidate.parent / destination


def _rollback_evidence_for(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f".{path.name}{_ROLLBACK_MARKER}*"))


def _atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    _ensure_private_dir(path.parent)
    rollback_prefix = f".{path.name}{_ROLLBACK_MARKER}"
    unresolved = _rollback_evidence_for(path)
    if unresolved:
        raise FlowError(
            "ATOMIC_RECOVERY_REQUIRED",
            "a prior atomic replacement left rollback evidence",
            details={
                "path": str(path),
                "rollback_candidates": [
                    str(candidate) for candidate in unresolved
                ],
                "recovery_command": _ROLLBACK_RECOVERY_COMMAND,
            },
        )

    def fsync_parent() -> None:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    rollback_descriptor = -1
    rollback: Path | None = None
    original_existed = path.exists()
    try:
        rollback_descriptor, rollback_name = tempfile.mkstemp(
            prefix=rollback_prefix, dir=path.parent
        )
        rollback = Path(rollback_name)
        os.fchmod(rollback_descriptor, mode)
        with os.fdopen(rollback_descriptor, "wb") as rollback_handle:
            rollback_descriptor = -1
            if original_existed:
                try:
                    with path.open("rb") as original:
                        shutil.copyfileobj(original, rollback_handle)
                except OSError as exc:
                    raise FlowError(
                        "ATOMIC_WRITE_FAILED",
                        "could not preserve the prior committed file",
                        details={
                            "path": str(path),
                            "rollback": str(rollback),
                            "phase": "backup",
                            "error": str(exc),
                        },
                    ) from exc
            rollback_handle.flush()
            os.fsync(rollback_handle.fileno())
        _set_private_permissions(rollback, mode)
        if (
            original_existed
            and _sha256_file(rollback) != _sha256_file(path)
        ):
            raise FlowError(
                "ATOMIC_WRITE_FAILED",
                "prior committed file changed while rollback evidence was captured",
                details={
                    "path": str(path),
                    "rollback": str(rollback),
                    "phase": "backup",
                },
            )
    except BaseException:
        if rollback_descriptor >= 0:
            try:
                os.close(rollback_descriptor)
            except OSError:
                pass
        if rollback is not None:
            try:
                rollback.unlink()
            except OSError:
                pass
        raise

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        if rollback is not None:
            try:
                rollback.unlink()
            except OSError:
                pass
        raise FlowError(
            "ATOMIC_WRITE_FAILED",
            "could not create a same-directory temporary state file",
            details={"path": str(path), "error": str(exc), "phase": "create"},
        ) from exc
    temporary = Path(temporary_name)
    replaced = False
    restored = False
    recovery_uncertain = False
    try:
        try:
            os.fchmod(descriptor, mode)
        except OSError as exc:
            raise FlowError(
                "PERMISSIONS_UNVERIFIABLE",
                "could not apply private permissions to a temporary state file",
                details={"path": str(temporary), "mode": oct(mode), "error": str(exc)},
            ) from exc
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, path)
            replaced = True
        except OSError as exc:
            raise FlowError(
                "ATOMIC_WRITE_FAILED",
                "atomic state replacement failed; the previous file was preserved",
                details={"path": str(path), "error": str(exc), "phase": "replace"},
            ) from exc
        try:
            _set_private_permissions(path, mode)
            fsync_parent()
        except (FlowError, OSError) as post_error:
            try:
                if original_existed:
                    if rollback is None:
                        raise OSError(
                            errno.ENOENT,
                            "rollback evidence is unavailable",
                        )
                    os.replace(rollback, path)
                    rollback = None
                    _set_private_permissions(path, mode)
                else:
                    path.unlink()
                fsync_parent()
                restored = True
            except (FlowError, OSError) as restore_error:
                recovery_uncertain = True
                raise FlowError(
                    "ATOMIC_RECOVERY_UNCERTAIN",
                    (
                        "replacement post-check failed and the previous "
                        "destination could not be restored safely"
                    ),
                    details={
                        "path": str(path),
                        "rollback": (
                            str(rollback) if rollback else None
                        ),
                        "committed": True,
                        "post_error": str(post_error),
                        "restore_error": str(restore_error),
                    },
                ) from restore_error
            raise FlowError(
                "ATOMIC_POSTCHECK_FAILED",
                (
                    "replacement post-check failed; the previously "
                    "committed destination was restored"
                ),
                details={
                    "path": str(path),
                    "committed": False,
                    "restored": True,
                    "error": str(post_error),
                },
            ) from post_error
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            if not replaced:
                raise FlowError(
                    "ATOMIC_CLEANUP_FAILED",
                    "an uncommitted temporary state file could not be removed",
                    details={"path": str(temporary), "error": str(exc)},
                ) from exc
        if rollback is not None and not recovery_uncertain:
            try:
                rollback.unlink()
                rollback = None
                if replaced and not restored:
                    fsync_parent()
            except OSError as exc:
                if replaced and not restored:
                    raise FlowError(
                        "ATOMIC_COMMIT_UNCERTAIN",
                        (
                            "replacement committed but rollback-evidence "
                            "cleanup could not be proven durable"
                        ),
                        details={
                            "path": str(path),
                            "rollback": str(rollback),
                            "committed": True,
                            "error": str(exc),
                        },
                    ) from exc


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, _json_bytes(value))


def _atomic_write_sensitive_json(path: Path, value: Any) -> None:
    _atomic_write_json(path, _redact_sensitive_value(value))


def _event_id_recorded(path: Path, event_id: str) -> bool:
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    recorded = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FlowError(
                        "EVENT_LOG_INVALID",
                        "event log contains an incomplete or invalid record",
                        details={"path": str(path), "line": line_number},
                    ) from exc
                if (
                    isinstance(recorded, dict)
                    and recorded.get("event_id") == event_id
                ):
                    return True
    except OSError as exc:
        raise FlowError(
            "EVENT_LOG_READ_FAILED",
            "could not inspect event log before an idempotent append",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    return False


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8", "backslashreplace"
    )


def _protocol_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8", "backslashreplace")


def _write_protocol_response(value: Any) -> None:
    # CLI JSON is an external display surface.  Keep this final guard even
    # when a lower-level error or future feature accidentally retains raw
    # command output in memory.
    payload = _protocol_json_bytes(_redact_sensitive_value(value))
    binary = getattr(sys.stdout, "buffer", None)
    if binary is not None:
        binary.write(payload)
        binary.flush()
    else:
        sys.stdout.write(payload.decode("utf-8"))
        sys.stdout.flush()


def _append_event(path: Path, event: dict[str, Any]) -> None:
    safe_event = _redact_sensitive_value(event)
    if not isinstance(safe_event, dict):  # Defensive: event callers provide objects.
        raise TypeError("event redaction produced a non-object value")
    event_id = safe_event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise FlowError(
            "EVENT_INVALID",
            "event records require a stable non-empty event_id",
            details={"path": str(path)},
        )
    _ensure_private_dir(path.parent)
    if path.exists():
        _set_private_permissions(path, 0o600)
    if _event_id_recorded(path, event_id):
        return
    payload = (
        json.dumps(
            safe_event,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8", "backslashreplace")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError(errno.EIO, "event append made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise FlowError(
            "EVENT_APPEND_FAILED",
            "could not append the durable task event",
            details={"path": str(path), "event_id": event_id, "error": str(exc)},
        ) from exc
    finally:
        os.close(descriptor)
    _set_private_permissions(path, 0o600)


def _validate_pending_event_outbox(
    task_dir: Path, state_value: dict[str, Any]
) -> list[dict[str, Any]]:
    pending_single = state_value.get("pending_event")
    pending_batch = state_value.get("pending_events")
    if pending_single is not None and pending_batch is not None:
        raise FlowError(
            "PENDING_EVENT_INVALID",
            "task state cannot contain both a single and batched event outbox",
            details={"path": str(task_dir / "state.json")},
        )
    if pending_batch is not None:
        if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "batched event outboxes require the current V4 task schema",
                details={
                    "path": str(task_dir / "state.json"),
                    "schema_version": state_value.get("schema_version"),
                },
            )
        if (
            not isinstance(pending_batch, list)
            or not pending_batch
            or not all(isinstance(item, dict) for item in pending_batch)
        ):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "task state contains an invalid pending event batch",
                details={"path": str(task_dir / "state.json")},
            )
        pending_events = pending_batch
    elif pending_single is not None:
        if not isinstance(pending_single, dict):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "task state contains an invalid pending event outbox record",
                details={"path": str(task_dir / "state.json")},
            )
        pending_events = [pending_single]
    else:
        return []

    state_revision = state_value.get("revision")
    if (
        not isinstance(state_revision, int)
        or isinstance(state_revision, bool)
        or state_revision < 1
    ):
        raise FlowError(
            "PENDING_EVENT_INVALID",
            "pending event state revision is invalid",
            details={"path": str(task_dir / "state.json")},
        )

    event_ids: set[str] = set()
    transaction_ids: set[str] = set()
    event_times: set[str] = set()
    event_actors: set[str] = set()
    for pending in pending_events:
        if pending.get("task_id") != state_value.get("task_id"):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event task identity does not match its state snapshot",
                details={"path": str(task_dir / "state.json")},
            )
        if pending.get("revision") != state_value.get("revision"):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event revision does not match its state snapshot",
                details={"path": str(task_dir / "state.json")},
            )
        if pending.get("previous_revision") != state_revision - 1:
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event previous revision does not match its state snapshot",
                details={"path": str(task_dir / "state.json")},
            )
        if pending.get("status") != state_value.get("status"):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event status does not match its state snapshot",
                details={"path": str(task_dir / "state.json")},
            )
        if (
            not isinstance(pending.get("type"), str)
            or not pending.get("type")
            or not isinstance(pending.get("payload"), dict)
        ):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event type or payload is invalid",
                details={"path": str(task_dir / "state.json")},
            )
        event_id = pending.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids:
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event batch contains a missing or duplicate event id",
                details={"path": str(task_dir / "state.json")},
            )
        event_ids.add(event_id)
        event_at = pending.get("at")
        event_actor = pending.get("actor")
        if (
            not isinstance(event_at, str)
            or not event_at
            or not isinstance(event_actor, str)
            or not event_actor
        ):
            raise FlowError(
                "PENDING_EVENT_INVALID",
                "pending event timestamp or actor is invalid",
                details={"path": str(task_dir / "state.json")},
            )
        event_times.add(event_at)
        event_actors.add(event_actor)
        transaction_id = pending.get("transaction_id")
        if len(pending_events) > 1:
            if not isinstance(transaction_id, str) or not transaction_id:
                raise FlowError(
                    "PENDING_EVENT_INVALID",
                    "every event in a batch requires a transaction id",
                    details={"path": str(task_dir / "state.json")},
                )
            transaction_ids.add(transaction_id)
        elif transaction_id is not None:
            if not isinstance(transaction_id, str) or not transaction_id:
                raise FlowError(
                    "PENDING_EVENT_INVALID",
                    "pending event transaction id is invalid",
                    details={"path": str(task_dir / "state.json")},
                )
            transaction_ids.add(transaction_id)
    if len(pending_events) > 1 and (
        len(transaction_ids) != 1
        or len(event_times) != 1
        or len(event_actors) != 1
    ):
        raise FlowError(
            "PENDING_EVENT_INVALID",
            "all events in a pending batch must share transaction metadata",
            details={"path": str(task_dir / "state.json")},
        )
    return pending_events


def _flush_pending_event(task_dir: Path, state_value: dict[str, Any]) -> None:
    pending_events = _validate_pending_event_outbox(task_dir, state_value)
    if not pending_events:
        return
    for pending in pending_events:
        _append_event(task_dir / "events.jsonl", pending)
    state_value.pop("pending_event", None)
    state_value.pop("pending_events", None)
    _redact_state_in_place(state_value)
    _atomic_write_json(task_dir / "state.json", state_value)


def _recover_pending_event(
    state_path: Path, state_value: dict[str, Any]
) -> dict[str, Any]:
    """Deliver an outboxed event under the task lock, including after a crash."""

    task_dir = state_path.parent.resolve(strict=False)
    held_directories = set(_HELD_LOCK_DIRECTORIES.get())
    if str(task_dir) in held_directories:
        _flush_pending_event(task_dir, state_value)
        return state_value
    # Recovery must work even when a mutation quarantine remains: the outbox
    # itself is sufficient to repair the audit gap and does not authorize a
    # new mutating child.
    with _task_lock(task_dir, allow_quarantine=True):
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FlowError(
                "STATE_READ_FAILED",
                "could not reload task state for pending-event recovery",
                details={"path": str(state_path), "error": str(exc)},
            ) from exc
        if not isinstance(current, dict):
            raise FlowError(
                "UNSUPPORTED_STATE",
                "task state is invalid during pending-event recovery",
                details={"path": str(state_path)},
            )
        _validate_task_state_snapshot(state_path, current)
        _flush_pending_event(task_dir, current)
        return current
