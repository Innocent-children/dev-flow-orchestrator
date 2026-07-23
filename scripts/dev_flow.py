#!/usr/bin/env python3
"""A deterministic, local control plane for Codex development work.

The module intentionally depends only on Python's standard library.  Every
normal CLI response (including errors) is one JSON object on stdout so hooks
and skills do not need to scrape prose.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterator, Sequence

try:  # POSIX is the primary Codex environment; the fallback still works single-process.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
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
FORWARD_EDGES = {
    state: {ORDERED_STATES[index + 1]}
    for index, state in enumerate(ORDERED_STATES[:-1])
}
FORWARD_EDGES["DONE"] = set()
REWORK_EDGES = {
    "IMPLEMENTING": {"PLANNING"},
    "VERIFYING": {"IMPLEMENTING", "PLANNING"},
    "REVIEWING": {"IMPLEMENTING", "PLANNING"},
    "FINALIZING": {"IMPLEMENTING", "PLANNING"},
}
IMPACT_REASSESS_SOURCES = {
    "ROUTE_APPROVED",
    "WORKSPACE_READY",
    "PLANNING",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "FINALIZING",
}
for _reassess_source in IMPACT_REASSESS_SOURCES:
    REWORK_EDGES.setdefault(_reassess_source, set()).add("INDEXED")
FLOW_MODES = ("full", "lite")
DEFAULT_FLOW = "full"
LITE_GATE = "lite"
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
LITE_FORWARD_EDGES = {
    state: {LITE_ORDERED_STATES[index + 1]}
    for index, state in enumerate(LITE_ORDERED_STATES[:-1])
}
LITE_FORWARD_EDGES["DONE"] = set()
# Backward edges: rework the implementation, or re-open scope evidence with a
# fresh preflight when the checkout drifted or the fix outgrew its approval.
LITE_REWORK_EDGES = {
    "IMPLEMENTING": {"PREFLIGHTED"},
    "VERIFYING": {"IMPLEMENTING", "PREFLIGHTED"},
}
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
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise FlowError("INVALID_ARGUMENT", message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve state storage using CLI, environment, then platform state dir.

    Resolution order is deliberately exposed for hooks: explicit ``data_dir``;
    ``DEV_FLOW_DATA_DIR``; ``PLUGIN_DATA``; finally the user's state directory.
    The returned path is absolute, but this function does not create it.
    """

    candidate: str | os.PathLike[str] | None = data_dir
    if not candidate:
        candidate = os.environ.get("DEV_FLOW_DATA_DIR") or os.environ.get("PLUGIN_DATA")
    if not candidate:
        if sys.platform == "darwin":
            candidate = Path.home() / "Library" / "Application Support" / "dev-flow-orchestrator"
        elif os.name == "nt":  # pragma: no cover - platform-specific
            candidate = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "dev-flow-orchestrator"
        else:
            candidate = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "dev-flow-orchestrator"
    return Path(candidate).expanduser().resolve(strict=False)


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_RE.fullmatch(task_id):
        raise FlowError(
            "INVALID_TASK_ID",
            "task id must be 1-64 characters using letters, digits, '.', '_' or '-'",
            details={"task_id": task_id},
        )
    return task_id


def _task_dir(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "tasks" / _validate_task_id(task_id)


def _state_path(task_id: str, data_dir: str | os.PathLike[str] | None = None) -> Path:
    return _task_dir(task_id, data_dir) / "state.json"


def load_state(
    task_id: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Load a task snapshot by id, or load an explicit ``state.json`` path."""

    supplied = Path(task_id)
    if supplied.name == "state.json" or supplied.is_file():
        path = supplied.expanduser().resolve(strict=False)
    else:
        path = _state_path(str(task_id), data_dir)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise FlowError(
            "TASK_NOT_FOUND",
            f"task state does not exist: {path}",
            details={"path": str(path)},
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowError(
            "STATE_READ_FAILED",
            f"could not read task state: {path}",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise FlowError(
            "UNSUPPORTED_STATE",
            f"unsupported or invalid task state: {path}",
            details={"path": str(path), "schema_version": value.get("schema_version") if isinstance(value, dict) else None},
        )
    # Schema v1 predates implementation-worktree indexes.  Keep the schema
    # number stable and make the additive field visible to old task snapshots
    # without rewriting them merely because they were read.
    for repository in value.get("repositories", []):
        if isinstance(repository, dict):
            repository.setdefault("workspace_index", None)
            repository.setdefault("index_history", [])
    # Tasks recorded before flow selection are full-flow tasks by definition.
    value.setdefault("flow", DEFAULT_FLOW)
    return value


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def find_active_task_for_cwd(
    cwd: str | os.PathLike[str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Return the newest non-terminal task whose repo/workspace contains cwd."""

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
    return max(matches, key=lambda value: (str(value.get("updated_at", "")), int(value.get("revision", 0))))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _atomic_write_bytes(path: Path, data: bytes, mode: int = 0o600) -> None:
    _ensure_dir(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_bytes(path, _json_bytes(value))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _append_event(path: Path, event: dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    payload = (json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _task_lock(task_dir: Path) -> Iterator[None]:
    _ensure_dir(task_dir)
    lock_path = task_dir / "state.lock"
    with lock_path.open("a+b") as handle:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _workspace_registry_lock(data_root: Path) -> Iterator[None]:
    _ensure_dir(data_root)
    lock_path = data_root / "workspace-registry.lock"
    with lock_path.open("a+b") as handle:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _config_lock(data_root: Path) -> Iterator[None]:
    _ensure_dir(data_root)
    lock_path = data_root / "config.lock"
    with lock_path.open("a+b") as handle:
        try:
            lock_path.chmod(0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def config_path(data_dir: str | os.PathLike[str] | None = None) -> Path:
    return resolve_data_dir(data_dir) / "config.json"


def _default_config() -> dict[str, Any]:
    """The absent-configuration default keeps the plugin active everywhere."""

    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {"mode": "all", "include": [], "exclude": []},
    }


def _normalize_scope_root(
    value: Any, option: str, *, code: str = "INVALID_ARGUMENT"
) -> str:
    text = str(value or "").strip()
    if not text:
        raise FlowError(code, f"{option} requires a non-empty directory path")
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise FlowError(
            code,
            f"{option} is not a usable directory path",
            details={"path": text, "error": str(exc)},
        ) from exc


def _normalize_scope(value: Any) -> dict[str, Any]:
    """Coerce a stored scope object into its canonical absolute-path form."""

    supplied = value if isinstance(value, dict) else {}
    mode = str(supplied.get("mode", "all")).strip().lower() or "all"
    if mode not in SCOPE_MODES:
        raise FlowError(
            "CONFIG_INVALID",
            f"scope.mode must be one of: {', '.join(SCOPE_MODES)}",
            details={"mode": mode},
        )
    scope: dict[str, Any] = {"mode": mode}
    for key in ("include", "exclude"):
        raw = supplied.get(key) or []
        if not isinstance(raw, list):
            raise FlowError(
                "CONFIG_INVALID",
                f"scope.{key} must be a list of directories",
                details={"key": key},
            )
        roots = {
            _normalize_scope_root(item, f"scope.{key}", code="CONFIG_INVALID")
            for item in raw
        }
        scope[key] = sorted(roots)
    return scope


def load_config(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the stored plugin configuration, or the defaults when absent."""

    path = config_path(data_dir)
    if not path.exists():
        return _default_config()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise FlowError(
            "CONFIG_INVALID",
            "plugin configuration has an unsupported structure",
            details={
                "path": str(path),
                "schema_version": value.get("schema_version")
                if isinstance(value, dict)
                else None,
            },
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": _normalize_scope(value.get("scope")),
    }


def _scope_env_roots(environ: Any, name: str) -> list[str] | None:
    """Parse one ``os.pathsep`` separated override, or None when unset."""

    raw = environ.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    roots = {
        _normalize_scope_root(item, name)
        for item in raw.split(os.pathsep)
        if item.strip()
    }
    return sorted(roots) or None


def resolve_scope(
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Return the stored scope after applying the environment overrides.

    ``DEV_FLOW_SCOPE`` replaces the included directories and forces allowlist
    mode; ``DEV_FLOW_SCOPE_EXCLUDE`` replaces the excluded directories in
    either mode.  ``overrides`` records which list the environment supplied.
    """

    values = os.environ if environ is None else environ
    scope = load_config(data_dir)["scope"]
    overrides: dict[str, str] = {}
    include = _scope_env_roots(values, SCOPE_INCLUDE_ENV)
    if include is not None:
        scope.update({"mode": "allowlist", "include": include})
        overrides["include"] = SCOPE_INCLUDE_ENV
    exclude = _scope_env_roots(values, SCOPE_EXCLUDE_ENV)
    if exclude is not None:
        scope["exclude"] = exclude
        overrides["exclude"] = SCOPE_EXCLUDE_ENV
    scope["overrides"] = overrides
    return scope


def evaluate_scope(path: str | os.PathLike[str], scope: dict[str, Any]) -> dict[str, Any]:
    """Decide whether one directory is in scope; the deepest root wins.

    A directory nested under both an included and an excluded root follows the
    more specific one, so an allowlist can carve exceptions back out of an
    exclusion.  An exactly equal pair resolves to the exclusion.
    """

    current = Path(path).expanduser().resolve(strict=False)
    matched: str | None = None
    rule = "default"
    depth = -1
    for candidate_rule in ("include", "exclude"):
        for root in scope.get(candidate_rule) or []:
            candidate = Path(root)
            if not _is_within(current, candidate):
                continue
            candidate_depth = len(candidate.parts)
            if candidate_depth > depth or (
                candidate_depth == depth and candidate_rule == "exclude"
            ):
                matched, rule, depth = root, candidate_rule, candidate_depth
    if rule == "default":
        in_scope = str(scope.get("mode", "all")) != "allowlist"
    else:
        in_scope = rule == "include"
    return {
        "path": str(current),
        "in_scope": in_scope,
        "rule": rule,
        "matched": matched,
        "mode": str(scope.get("mode", "all")),
    }


def evaluate_scope_for_path(
    path: str | os.PathLike[str],
    data_dir: str | os.PathLike[str] | None = None,
    environ: Any = None,
) -> dict[str, Any]:
    """Resolve the effective scope and evaluate one directory against it."""

    return evaluate_scope(path, resolve_scope(data_dir, environ))


def _scope_summary(scope: dict[str, Any]) -> str:
    if str(scope.get("mode", "all")) == "allowlist":
        if not scope.get("include"):
            return "inactive in every directory"
        if scope.get("exclude"):
            return "active only inside the included directories, minus the excluded ones"
        return "active only inside the included directories"
    if scope.get("exclude"):
        return "active in every directory except the excluded ones"
    return "active in every directory"


def _assert_path_in_scope(
    path: Path, label: str, data_dir: str | os.PathLike[str] | None
) -> None:
    decision = evaluate_scope_for_path(path, data_dir)
    if decision["in_scope"]:
        return
    raise FlowError(
        "OUT_OF_SCOPE",
        f"{label} is outside the configured Dev Flow scope",
        details={
            "path": decision["path"],
            "matched": decision["matched"],
            "rule": decision["rule"],
            "mode": decision["mode"],
            "config_path": str(config_path(data_dir)),
            "remedy": "add the directory with the scope command, or widen the scope",
        },
    )


def _load_workspace_registry(data_root: Path) -> dict[str, Any]:
    path = data_root / "workspace-registry.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "claims": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCHEMA_VERSION
        or not isinstance(value.get("claims"), list)
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has an unsupported structure",
            details={"path": str(path)},
        )
    return value


def _source_common_dir_for_claim(source_path: Any) -> str:
    source = Path(str(source_path)).expanduser().resolve(strict=False)
    try:
        return str(_git_evidence_path(source, "--git-common-dir"))
    except (FlowError, OSError):
        return f"unavailable:{source}"


def _state_workspace_claims(data_root: Path) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    tasks_dir = data_root / "tasks"
    if not tasks_dir.is_dir():
        return claims
    for state_path in tasks_dir.glob("*/state.json"):
        try:
            state_value = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(state_value, dict) or not state_value.get("task_id"):
            continue
        task_id = state_value["task_id"]
        for repo in state_value.get("repositories", []):
            common_dir = _source_common_dir_for_claim(repo.get("path"))
            for workspace in [repo.get("workspace"), *repo.get("workspace_history", [])]:
                if not isinstance(workspace, dict) or not workspace.get("path"):
                    continue
                claims.append(
                    {
                        "task_id": task_id,
                        "repository_id": repo.get("id"),
                        "path": str(Path(workspace["path"]).resolve(strict=False)),
                        "branch": workspace.get("branch"),
                        "source_common_dir": common_dir,
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": (
                            workspace.get("workspace_claim") or {}
                        ).get("plan_sha256"),
                        "origin": "task-state",
                    }
                )
        controller_plan = (state_value.get("workspace") or {}).get("plan") or {}
        plan_path = controller_plan.get("path")
        if plan_path:
            try:
                evidence = json.loads(Path(plan_path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            for planned in evidence.get("repositories", []):
                if not planned.get("path"):
                    continue
                claims.append(
                    {
                        "task_id": task_id,
                        "repository_id": planned.get("repository_id"),
                        "path": str(Path(planned["path"]).resolve(strict=False)),
                        "branch": planned.get("branch"),
                        "source_common_dir": _source_common_dir_for_claim(
                            planned.get("source_path")
                        ),
                        "workspace_generation": controller_plan.get(
                            "workspace_generation"
                        ),
                        "plan_sha256": controller_plan.get("sha256"),
                        "origin": "task-plan",
                    }
                )
    return claims


def _claim_workspace_plan(
    data_root: Path,
    state_value: dict[str, Any],
    plan_sha256: str,
    plans: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    with _workspace_registry_lock(data_root):
        registry = _load_workspace_registry(data_root)
        existing_claims = [*registry["claims"], *_state_workspace_claims(data_root)]
        proposed: list[dict[str, Any]] = []
        for plan in plans:
            proposed.append(
                {
                    "claim_id": str(uuid.uuid4()),
                    "task_id": state_value["task_id"],
                    "repository_id": plan["repository_id"],
                    "source_path": str(
                        Path(plan["source_path"]).resolve(strict=False)
                    ),
                    "source_common_dir": _source_common_dir_for_claim(
                        plan["source_path"]
                    ),
                    "path": str(Path(plan["path"]).resolve(strict=False)),
                    "branch": plan["branch"],
                    "workspace_generation": int(
                        (state_value.get("workspace") or {}).get("generation", 0)
                    ),
                    "plan_sha256": plan_sha256,
                    "claimed_at": utc_now(),
                }
            )
        for candidate_index, candidate in enumerate(proposed):
            candidate_path = Path(candidate["path"])
            for claimed in [*existing_claims, *proposed[:candidate_index]]:
                exact_retry = (
                    claimed.get("task_id") == candidate["task_id"]
                    and claimed.get("repository_id")
                    == candidate["repository_id"]
                    and claimed.get("path") == candidate["path"]
                    and claimed.get("branch") == candidate["branch"]
                    and claimed.get("source_common_dir")
                    == candidate["source_common_dir"]
                    and claimed.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claimed.get("plan_sha256") == candidate["plan_sha256"]
                )
                if exact_retry:
                    continue
                claimed_path_value = claimed.get("path")
                claimed_path = (
                    Path(claimed_path_value).resolve(strict=False)
                    if claimed_path_value
                    else None
                )
                path_conflict = bool(
                    claimed_path
                    and (
                        _is_within(candidate_path, claimed_path)
                        or _is_within(claimed_path, candidate_path)
                    )
                )
                branch_conflict = bool(
                    candidate.get("branch")
                    and claimed.get("branch")
                    and (
                        candidate["branch"] == claimed["branch"]
                        or candidate["branch"].startswith(
                            f"{claimed['branch']}/"
                        )
                        or claimed["branch"].startswith(
                            f"{candidate['branch']}/"
                        )
                    )
                    and candidate.get("source_common_dir")
                    == claimed.get("source_common_dir")
                )
                if path_conflict or branch_conflict:
                    raise FlowError(
                        "WORKSPACE_OWNERSHIP_CONFLICT",
                        "workspace path or repository branch is already claimed by another task or repository plan",
                        details={
                            "task_id": state_value["task_id"],
                            "repository_id": candidate["repository_id"],
                            "path": candidate["path"],
                            "branch": candidate["branch"],
                            "owner_task_id": claimed.get("task_id"),
                            "owner_path": claimed.get("path"),
                            "owner_branch": claimed.get("branch"),
                            "conflict": "path" if path_conflict else "branch",
                        },
                    )
        selected_claims: dict[str, dict[str, Any]] = {}
        for candidate in proposed:
            existing = next(
                (
                    claim
                    for claim in registry["claims"]
                    if claim.get("task_id") == candidate["task_id"]
                    and claim.get("repository_id") == candidate["repository_id"]
                    and claim.get("workspace_generation")
                    == candidate["workspace_generation"]
                    and claim.get("plan_sha256") == candidate["plan_sha256"]
                    and claim.get("path") == candidate["path"]
                    and claim.get("branch") == candidate["branch"]
                ),
                None,
            )
            if existing is None:
                registry["claims"].append(candidate)
                existing = candidate
            selected_claims[candidate["repository_id"]] = existing
        _atomic_write_json(data_root / "workspace-registry.json", registry)
        for plan in plans:
            claim = selected_claims[plan["repository_id"]]
            plan["workspace_claim"] = {
                "claim_id": claim["claim_id"],
                "registry_path": str(data_root / "workspace-registry.json"),
                "plan_sha256": plan_sha256,
            }
        return selected_claims


def _actor() -> str:
    return os.environ.get("DEV_FLOW_ACTOR") or os.environ.get("USER") or "unknown"


def _commit_state(
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any],
    task_dir: Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_revision = int(old_state.get("revision", 0)) if old_state else 0
    revision = previous_revision + 1
    now = utc_now()
    new_state["revision"] = revision
    new_state["updated_at"] = now
    event = {
        "event_id": str(uuid.uuid4()),
        "task_id": new_state["task_id"],
        "type": event_type,
        "at": now,
        "actor": _actor(),
        "previous_revision": previous_revision,
        "revision": revision,
        "status": new_state["status"],
        "payload": payload or {},
    }
    _atomic_write_json(task_dir / "state.json", new_state)
    _append_event(task_dir / "events.jsonl", event)
    return event


def _check_revision(state_value: dict[str, Any], expected_revision: int) -> None:
    actual = int(state_value.get("revision", 0))
    if expected_revision != actual:
        raise FlowError(
            "REVISION_CONFLICT",
            f"expected revision {expected_revision}, but current revision is {actual}",
            details={
                "task_id": state_value.get("task_id"),
                "expected_revision": expected_revision,
                "actual_revision": actual,
            },
            exit_code=3,
        )


@contextlib.contextmanager
def _locked_state(
    task_id: str,
    data_dir: str | os.PathLike[str] | None,
    expected_revision: int,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    task_dir = _task_dir(task_id, data_dir)
    with _task_lock(task_dir):
        state_value = load_state(task_id, data_dir)
        _check_revision(state_value, expected_revision)
        yield task_dir, state_value


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    text: bool = True,
    evidence_git: bool = False,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    is_git = bool(command) and Path(command[0]).name == "git"
    if is_git:
        # ``git -C`` does not override repository redirection variables.  A
        # caller-controlled environment must not be able to make identity,
        # baseline, worktree, or side-effect commands operate on another
        # repository or index.
        for key in list(environment):
            if key in {
                "GIT_DIR",
                "GIT_WORK_TREE",
                "GIT_INDEX_FILE",
                "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE",
                "GIT_CONFIG",
                "GIT_CONFIG_PARAMETERS",
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM",
                "GIT_CONFIG_NOSYSTEM",
                "GIT_CEILING_DIRECTORIES",
                "GIT_DISCOVERY_ACROSS_FILESYSTEM",
                "GIT_SHALLOW_FILE",
                "GIT_GRAFT_FILE",
                "GIT_REPLACE_REF_BASE",
            } or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                environment.pop(key, None)
        environment.pop("GIT_CONFIG_COUNT", None)
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        environment["GIT_NO_LAZY_FETCH"] = "1"
        # Disable both environment-selected and repository-local legacy grafts.
        environment["GIT_GRAFT_FILE"] = os.devnull
    if evidence_git:
        environment.pop("GIT_EXTERNAL_DIFF", None)
        environment.pop("GIT_DIFF_OPTS", None)
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=text,
            check=False,
        )
    except OSError as exc:
        raise FlowError(
            "COMMAND_FAILED",
            f"could not execute {command[0]}",
            details={"command": list(command), "error": str(exc)},
        ) from exc
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if text else result.stderr.decode("utf-8", "replace").strip()
        raise FlowError(
            "COMMAND_FAILED",
            f"command failed with exit code {result.returncode}",
            details={"command": list(command), "cwd": str(cwd) if cwd else None, "stderr": stderr},
        )
    return result


def _git(repo: Path, *arguments: str, check: bool = True, text: bool = True) -> Any:
    result = _run(["git", "-C", str(repo), *arguments], check=check, text=text)
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(["git", "-C", str(repo), *arguments], check=False, text=True)
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _evidence_git_command(repo: Path, *arguments: str) -> list[str]:
    return [
        "git",
        "-c",
        "color.ui=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.ignoreStat=false",
        "-c",
        "core.trustctime=true",
        "-c",
        "core.checkStat=default",
        "-c",
        "core.fileMode=true",
        "-c",
        "core.symlinks=true",
        "-c",
        "core.ignoreCase=false",
        "-c",
        "core.quotePath=true",
        "-c",
        "diff.external=",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.noprefix=false",
        "-c",
        "diff.srcPrefix=a/",
        "-c",
        "diff.dstPrefix=b/",
        "-c",
        "diff.ignoreSubmodules=none",
        "-c",
        "diff.submodule=short",
        "-C",
        str(repo),
        *arguments,
    ]


def _git_evidence(
    repo: Path, *arguments: str, check: bool = True, text: bool = True
) -> Any:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=check,
        text=text,
        evidence_git=True,
    )
    if text:
        return result.stdout.strip()
    return result.stdout


def _git_evidence_optional(repo: Path, *arguments: str) -> str | None:
    result = _run(
        _evidence_git_command(repo, *arguments),
        check=False,
        text=True,
        evidence_git=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _git_diff(repo: Path, *arguments: str, text: bool = True) -> Any:
    return _git_evidence(
        repo,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        "--submodule=short",
        "--no-renames",
        "--no-color",
        "--no-indent-heuristic",
        "--diff-algorithm=myers",
        "--unified=3",
        "--inter-hunk-context=0",
        *arguments,
        text=text,
    )


def _git_evidence_path(repo: Path, option: str) -> Path:
    raw = Path(_git_evidence(repo, "rev-parse", option))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _dirty_initialized_submodules(repo: Path) -> list[dict[str, str]]:
    """Return initialized submodules with unbound inner worktree content.

    A parent diff records a dirty submodule only as ``<gitlink>-dirty``.  It
    therefore cannot distinguish two different inner worktree states.  Clean
    submodule HEAD changes are safe because the changed gitlink commit remains
    part of the parent diff; tracked or untracked content below that HEAD is
    not safe evidence and must be rejected.
    """

    output = _git_evidence(
        repo,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
        "--ignore-submodules=none",
        "--no-renames",
        text=False,
    )
    dirty: list[dict[str, str]] = []
    records = output.split(b"\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or record[:2] not in {b"1 ", b"2 ", b"u "}:
            continue
        kind = record[:1]
        path_field = {b"1": 8, b"2": 9, b"u": 10}[kind]
        fields = record.split(b" ", path_field)
        if len(fields) <= path_field or len(fields) < 3:
            continue
        submodule = fields[2]
        # Porcelain v2 uses S<c><m><u>: c is a clean pointer/HEAD change,
        # while m/u mean modified/untracked content inside the submodule.
        if (
            len(submodule) == 4
            and submodule.startswith(b"S")
            and (submodule[2:3] != b"." or submodule[3:4] != b".")
        ):
            dirty.append(
                {
                    "path": fields[path_field].decode("utf-8", "replace"),
                    "submodule_status": submodule.decode("ascii", "replace"),
                }
            )
        if kind == b"2" and index < len(records):
            # A rename/copy record is followed by its original path.
            index += 1
    return dirty


def _initialized_submodule_worktrees(repo: Path) -> list[tuple[str, Path]]:
    output = _git_evidence(
        repo, "ls-files", "--stage", "-z", "--cached", "--", text=False
    )
    initialized: list[tuple[str, Path]] = []
    for record in output.split(b"\0"):
        metadata, separator, path_bytes = record.partition(b"\t")
        if not separator or not metadata.startswith(b"160000 "):
            continue
        relative = os.fsdecode(path_bytes)
        target = (repo / relative).resolve(strict=False)
        root = _git_evidence_optional(target, "rev-parse", "--show-toplevel")
        if root and Path(root).resolve(strict=False) == target:
            initialized.append((relative, target))
    return initialized


def _hidden_index_entries(repo: Path) -> list[dict[str, str]]:
    """Return tracked paths hidden from ordinary status/diff inspection."""

    output = _git_evidence(repo, "ls-files", "-v", "-z", "--cached", "--", text=False)
    hidden: list[dict[str, str]] = []
    for record in output.split(b"\0"):
        if len(record) < 3 or record[1:2] != b" ":
            continue
        tag = record[:1]
        assume_unchanged = tag.isalpha() and tag == tag.lower()
        skip_worktree = tag.upper() == b"S"
        if assume_unchanged or skip_worktree:
            flags: list[str] = []
            if assume_unchanged:
                flags.append("assume-unchanged")
            if skip_worktree:
                flags.append("skip-worktree")
            hidden.append(
                {
                    "path": record[2:].decode("utf-8", "replace"),
                    "flags": ",".join(flags),
                    "tag": tag.decode("ascii", "replace"),
                }
            )
    return hidden


def _content_filter_entries(
    repo: Path, source: str | None = None
) -> list[dict[str, str]]:
    """Return tracked paths whose Git attributes select a content filter."""

    if source:
        tracked_raw = _git_evidence(
            repo, "ls-tree", "-r", "-z", "--name-only", source, text=False
        )
    else:
        tracked_raw = _git_evidence(
            repo, "ls-files", "-z", "--cached", "--", text=False
        )
    tracked = [os.fsdecode(item) for item in tracked_raw.split(b"\0") if item]
    filtered: list[dict[str, str]] = []
    for offset in range(0, len(tracked), 128):
        batch = tracked[offset : offset + 128]
        source_arguments = ["--source", source] if source else []
        output = _git_evidence(
            repo,
            "check-attr",
            "-z",
            *source_arguments,
            "filter",
            "--",
            *batch,
            text=False,
        )
        fields = output.split(b"\0")
        for index in range(0, len(fields) - 2, 3):
            path_bytes, attribute, value = fields[index : index + 3]
            if attribute != b"filter" or value in {b"unspecified", b"unset"}:
                continue
            filtered.append(
                {
                    "path": path_bytes.decode("utf-8", "replace"),
                    "filter": value.decode("utf-8", "replace"),
                }
            )
    return filtered


def _assert_tree_checkout_supported(repo: Path, source: str) -> None:
    filtered = _content_filter_entries(repo, source)
    if filtered:
        raise FlowError(
            "CONTENT_FILTER_UNSUPPORTED",
            "target tree uses Git content filters that can execute during checkout",
            details={
                "repository": str(repo.resolve(strict=False)),
                "source": source,
                "entries": filtered,
                "hint": "remove filter attributes before materializing a worktree",
            },
        )


def _assert_no_hidden_index_entries(repo: Path) -> None:
    hidden = _hidden_index_entries(repo)
    if hidden:
        raise FlowError(
            "HIDDEN_INDEX_FLAGS",
            "tracked paths hidden by index flags cannot be used as complete evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "entries": hidden,
                "hint": (
                    "clear assume-unchanged/skip-worktree flags and use a full "
                    "non-sparse checkout before continuing"
                ),
            },
        )


def _prefixed_evidence_path(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def _assert_evidence_supported(repo: Path) -> None:
    evidence_root = repo.resolve(strict=True)
    visited: set[Path] = set()

    def visit(current: Path, prefix: str) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        hidden = _hidden_index_entries(resolved)
        if hidden:
            for entry in hidden:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "HIDDEN_INDEX_FLAGS",
                "tracked paths hidden by index flags cannot be used as complete evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": hidden,
                    "hint": (
                        "clear assume-unchanged/skip-worktree flags in every "
                        "initialized submodule and use a full non-sparse checkout"
                    ),
                },
            )
        filtered = _content_filter_entries(resolved)
        if filtered:
            for entry in filtered:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "CONTENT_FILTER_UNSUPPORTED",
                "Git clean/process filters cannot be used as complete byte evidence",
                details={
                    "repository": str(evidence_root),
                    "entries": filtered,
                    "hint": "remove filter attributes before continuing",
                },
            )
        children = _initialized_submodule_worktrees(resolved)
        for relative, child in children:
            visit(child, _prefixed_evidence_path(prefix, relative))
        dirty = _dirty_initialized_submodules(resolved)
        if dirty:
            for entry in dirty:
                entry["path"] = _prefixed_evidence_path(prefix, entry["path"])
            raise FlowError(
                "DIRTY_SUBMODULE_UNSUPPORTED",
                "dirty initialized submodules cannot be represented by complete review evidence",
                details={
                    "repository": str(evidence_root),
                    "submodules": dirty,
                    "hint": (
                        "commit each submodule change and update its parent gitlink, "
                        "or configure the submodule as a separate task repository"
                    ),
                },
            )

    visit(evidence_root, "")


def _assert_no_dirty_submodules(repo: Path) -> None:
    dirty = _dirty_initialized_submodules(repo)
    if dirty:
        raise FlowError(
            "DIRTY_SUBMODULE_UNSUPPORTED",
            "dirty initialized submodules cannot be represented by complete review evidence",
            details={
                "repository": str(repo.resolve(strict=False)),
                "submodules": dirty,
                "hint": (
                    "commit each submodule change and update its parent gitlink, "
                    "or configure the submodule as a separate task repository"
                ),
            },
        )


def _tracked_worktree_manifest(repo: Path) -> list[dict[str, Any]]:
    """Bind raw tracked filesystem bytes/types/modes, including submodules."""

    manifest: list[dict[str, Any]] = []
    visited: set[Path] = set()

    def visit(current: Path, prefix: bytes) -> None:
        resolved = current.resolve(strict=True)
        if resolved in visited:
            return
        visited.add(resolved)
        output = _git_evidence(
            resolved, "ls-files", "--stage", "-z", "--cached", "--", text=False
        )
        for record in output.split(b"\0"):
            metadata, separator, path_bytes = record.partition(b"\t")
            fields = metadata.split(b" ")
            if not separator or len(fields) != 3:
                continue
            index_mode, index_oid, stage = fields
            full_path = prefix + (b"/" if prefix else b"") + path_bytes
            target = resolved / os.fsdecode(path_bytes)
            item: dict[str, Any] = {
                "path": full_path.decode("utf-8", "replace"),
                "path_bytes_hex": full_path.hex(),
                "index_mode": index_mode.decode("ascii", "replace"),
                "index_oid": index_oid.decode("ascii", "replace"),
                "index_stage": stage.decode("ascii", "replace"),
            }
            try:
                metadata_value = target.lstat()
            except FileNotFoundError:
                item["worktree_type"] = "missing"
            else:
                item["worktree_mode"] = format(metadata_value.st_mode & 0o177777, "06o")
                item["size"] = metadata_value.st_size
                if stat.S_ISLNK(metadata_value.st_mode):
                    target_bytes = os.fsencode(os.readlink(target))
                    item["worktree_type"] = "symlink"
                    item["sha256"] = _sha256_bytes(target_bytes)
                elif stat.S_ISREG(metadata_value.st_mode):
                    item["worktree_type"] = "file"
                    item["sha256"] = _sha256_file(target)
                elif stat.S_ISDIR(metadata_value.st_mode):
                    item["worktree_type"] = "directory"
                else:
                    item["worktree_type"] = "other"
            manifest.append(item)
        for relative, child in _initialized_submodule_worktrees(resolved):
            relative_bytes = os.fsencode(relative)
            child_prefix = prefix + (b"/" if prefix else b"") + relative_bytes
            visit(child, child_prefix)

    visit(repo, b"")
    manifest.sort(
        key=lambda item: (item["path_bytes_hex"], item["index_stage"], item["index_oid"])
    )
    return manifest


def _canonical_repo(path_value: str) -> Path:
    supplied = Path(path_value).expanduser().resolve(strict=False)
    root = _git_optional(supplied, "rev-parse", "--show-toplevel")
    if not root:
        raise FlowError(
            "NOT_A_GIT_REPOSITORY",
            f"not a Git repository: {supplied}",
            details={"path": str(supplied)},
        )
    return Path(root).resolve(strict=True)


def _slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return result or "repo"


def _repo_id(root: Path, existing: set[str]) -> str:
    base = _slug(root.name)[:40]
    candidate = base
    if candidate in existing:
        digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
        candidate = f"{base}-{digest}"
    return candidate


def _split_lines(value: str | None) -> list[str]:
    if not value:
        return []
    return [line for line in value.splitlines() if line]


def _repo_by_selector(state_value: dict[str, Any], selectors: Sequence[str] | None) -> list[dict[str, Any]]:
    repositories = state_value.get("repositories", [])
    if not selectors:
        return repositories
    selected: list[dict[str, Any]] = []
    for selector in selectors:
        normalized_path = str(Path(selector).expanduser().resolve(strict=False)) if os.sep in selector or selector.startswith(".") else None
        matches = [
            repo
            for repo in repositories
            if selector == repo.get("id")
            or selector == repo.get("path")
            or selector == repo.get("canonical_path")
            or normalized_path in {repo.get("path"), repo.get("canonical_path")}
            or selector == Path(str(repo.get("path", ""))).name
        ]
        if len(matches) != 1:
            raise FlowError(
                "REPOSITORY_NOT_FOUND" if not matches else "AMBIGUOUS_REPOSITORY",
                f"repository selector must match exactly one configured repository: {selector}",
                details={"selector": selector, "matches": [repo.get("id") for repo in matches]},
            )
        if matches[0] not in selected:
            selected.append(matches[0])
    return selected


def _assert_status(state_value: dict[str, Any], allowed: set[str], command: str) -> None:
    current = state_value.get("status")
    if current not in allowed:
        raise FlowError(
            "INVALID_STATE",
            f"{command} is not allowed while task is {current}",
            details={"status": current, "allowed": sorted(allowed), "command": command},
        )


def _flow(state_value: dict[str, Any]) -> str:
    value = state_value.get("flow")
    return value if value in FLOW_MODES else DEFAULT_FLOW


def _assert_flow(state_value: dict[str, Any], required: str, command: str) -> None:
    actual = _flow(state_value)
    if actual != required:
        raise FlowError(
            "FLOW_MISMATCH",
            f"{command} is not part of the {actual} flow",
            details={"flow": actual, "required_flow": required, "command": command},
        )


def _operation_state(repo: Path) -> dict[str, bool]:
    git_dir_text = _git(repo, "rev-parse", "--absolute-git-dir")
    git_dir = Path(git_dir_text)
    return {
        "merge": (git_dir / "MERGE_HEAD").exists(),
        "rebase": (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists(),
        "cherry_pick": (git_dir / "CHERRY_PICK_HEAD").exists(),
        "revert": (git_dir / "REVERT_HEAD").exists(),
        "bisect": (git_dir / "BISECT_LOG").exists(),
        "sequencer": (git_dir / "sequencer").exists(),
    }


def _ref_exists(repo: Path, ref: str) -> bool:
    result = _run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref], check=False)
    return result.returncode == 0


def _default_remote(repo: Path, branch: str | None) -> str | None:
    if branch:
        configured = _git_optional(repo, "config", "--get", f"branch.{branch}.remote")
        if configured and configured != ".":
            return configured
    for key in ("remote.pushDefault", "checkout.defaultRemote"):
        configured = _git_optional(repo, "config", "--get", key)
        if configured:
            return configured
    remotes = _split_lines(_git_optional(repo, "remote"))
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else None


def _default_base(repo: Path, remote: str | None, branch: str | None, protected: Sequence[str]) -> str | None:
    if remote:
        symbolic = _git_optional(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
        if symbolic and symbolic.startswith(f"{remote}/"):
            return symbolic[len(remote) + 1 :]
    for candidate in protected:
        if remote and _ref_exists(repo, f"refs/remotes/{remote}/{candidate}"):
            return candidate
        if _ref_exists(repo, f"refs/heads/{candidate}"):
            return candidate
    # A feature branch is not a safe implicit baseline.  Repositories with a
    # non-standard default branch must expose remote/HEAD or pass --base.
    return branch if branch in protected else None


def _remote_url(repo: Path, remote: str | None) -> str | None:
    if not remote:
        return None
    return _git_optional(repo, "remote", "get-url", "--", remote)


def _approved_fetch_refspec(remote: str | None, base_branch: str | None) -> str | None:
    if not remote or not base_branch:
        return None
    return f"+refs/heads/{base_branch}:refs/remotes/{remote}/{base_branch}"


def _baseline_source_ref(remote: str | None, base_branch: str | None) -> str | None:
    if not base_branch:
        return None
    return (
        f"refs/remotes/{remote}/{base_branch}"
        if remote
        else f"refs/heads/{base_branch}"
    )


def _preflight_repo(
    repo_record: dict[str, Any],
    remote_override: str | None,
    base_override: str | None,
) -> dict[str, Any]:
    repo = Path(repo_record["path"])
    _assert_evidence_supported(repo)
    branch = _git_optional(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    head_sha = _git(repo, "rev-parse", "HEAD")
    remote = remote_override or _default_remote(repo, branch)
    base_branch = base_override or _default_base(
        repo, remote, branch, repo_record.get("protected_branches", DEFAULT_PROTECTED_BRANCHES)
    )
    if remote and (
        remote.startswith("-")
        or _run(
            ["git", "check-ref-format", f"refs/remotes/{remote}/base"],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_REMOTE",
            "remote name is not safe for deterministic fetch operations",
            details={"repository": str(repo), "remote": remote},
        )
    if base_branch and (
        _run(
            ["git", "check-ref-format", "--branch", base_branch],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "INVALID_BASE_BRANCH",
            "base branch name is invalid",
            details={"repository": str(repo), "base_branch": base_branch},
        )
    base_candidate_ref = _baseline_source_ref(remote, base_branch)
    base_candidate_sha = (
        _git_optional(
            repo, "rev-parse", "--verify", f"{base_candidate_ref}^{{commit}}"
        )
        if base_candidate_ref
        else None
    )
    staged = _split_lines(_git_diff(repo, "--cached", "--name-only", "--"))
    unstaged = _split_lines(_git_diff(repo, "--name-only", "--"))
    untracked = _split_lines(
        _git_evidence_optional(
            repo, "ls-files", "--others", "--exclude-standard", "--"
        )
    )
    conflicts = _split_lines(
        _git_diff(repo, "--name-only", "--diff-filter=U", "--")
    )
    operations = _operation_state(repo)
    blockers: list[str] = []
    if branch is None:
        blockers.append("detached_head")
    if conflicts:
        blockers.append("unmerged_conflicts")
    blockers.extend(f"operation_in_progress:{name}" for name, active in operations.items() if active)
    if not base_branch:
        blockers.append("base_branch_unresolved")
    if remote and remote not in _split_lines(_git_optional(repo, "remote")):
        blockers.append("remote_not_found")
    worktree_fingerprint_sha256 = _fingerprint_repo(repo)["sha256"]
    return {
        "checked_at": utc_now(),
        "branch": branch,
        "head_sha": head_sha,
        "remote": remote,
        "remote_url": _remote_url(repo, remote),
        "base_branch": base_branch,
        "base_candidate_ref": base_candidate_ref,
        "base_candidate_sha": base_candidate_sha,
        "fetch_refspec": _approved_fetch_refspec(remote, base_branch),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicts": conflicts,
        "operations": operations,
        "dirty": bool(staged or unstaged or untracked or conflicts),
        "worktree_fingerprint_sha256": worktree_fingerprint_sha256,
        "blockers": blockers,
        "ready": not blockers,
    }


def _baseline_ref(repo: Path, remote: str | None, base_branch: str) -> tuple[str, str]:
    if remote:
        # Never label a local branch as a remote baseline.  If the tracking
        # ref is absent, the caller must explicitly fetch (behind its gate) or
        # fix the remote rather than silently pinning stale local state.
        candidates = [f"refs/remotes/{remote}/{base_branch}"]
    else:
        candidates = [f"refs/heads/{base_branch}", base_branch]
    for candidate in candidates:
        sha = _git_optional(repo, "rev-parse", "--verify", f"{candidate}^{{commit}}")
        if sha:
            return candidate, sha
    raise FlowError(
        "BASE_REF_NOT_FOUND",
        f"could not resolve base branch {base_branch}",
        details={
            "repository": str(repo),
            "remote": remote,
            "base_branch": base_branch,
            "required_ref": f"refs/remotes/{remote}/{base_branch}" if remote else f"refs/heads/{base_branch}",
            "hint": "approve baseline-fetch and rerun baseline --fetch" if remote else "pass --base during preflight",
        },
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_artifact(path: Path) -> dict[str, Any]:
    """Hash a file or a directory without following directory symlinks.

    Directory hashes are a canonical JSONL manifest over sorted relative
    paths.  Entries bind path, type, file content, or symlink target; empty
    directories therefore remain significant too.
    """

    if path.is_file():
        size = path.stat().st_size
        return {
            "artifact_type": "file",
            "sha256": _sha256_file(path),
            "size": size,
            "file_count": 1,
            "total_size": size,
        }
    if not path.is_dir():
        raise FlowError("INVALID_ARTIFACT", f"artifact must be a regular file or directory: {path}")

    entries: list[dict[str, Any]] = [{"path": ".", "type": "directory"}]
    file_count = 0
    total_size = 0

    def visit(directory: Path, relative_directory: Path) -> None:
        nonlocal file_count, total_size
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise FlowError(
                "ARTIFACT_READ_FAILED",
                f"could not enumerate artifact directory: {directory}",
                details={"path": str(directory), "error": str(exc)},
            ) from exc
        for child in children:
            relative = (relative_directory / child.name).as_posix()
            try:
                if child.is_symlink():
                    target = os.readlink(child.path)
                    entries.append({"path": relative, "type": "symlink", "target": target})
                    file_count += 1
                elif child.is_dir(follow_symlinks=False):
                    entries.append({"path": relative, "type": "directory"})
                    visit(Path(child.path), relative_directory / child.name)
                elif child.is_file(follow_symlinks=False):
                    child_path = Path(child.path)
                    size = child.stat(follow_symlinks=False).st_size
                    entries.append(
                        {
                            "path": relative,
                            "type": "file",
                            "size": size,
                            "sha256": _sha256_file(child_path),
                        }
                    )
                    file_count += 1
                    total_size += size
                else:
                    entries.append({"path": relative, "type": "other"})
                    file_count += 1
            except OSError as exc:
                raise FlowError(
                    "ARTIFACT_READ_FAILED",
                    f"could not read artifact entry: {child.path}",
                    details={"path": child.path, "error": str(exc)},
                ) from exc

    visit(path, Path())
    manifest = b"".join(
        (json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        for entry in entries
    )
    return {
        "artifact_type": "directory",
        "sha256": _sha256_bytes(manifest),
        "size": total_size,
        "file_count": file_count,
        "total_size": total_size,
        "manifest_entry_count": len(entries),
    }


def _parse_review_report_verdict(path: Path) -> str:
    if not path.is_file():
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be a UTF-8 text file containing one 'Verdict: VALUE' line",
            details={"path": str(path)},
        )
    try:
        body = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "review-report must be readable UTF-8 text",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    nonempty_lines = [line for line in body.splitlines() if line.strip()]
    first_match = (
        REVIEW_VERDICT_RE.fullmatch(nonempty_lines[0]) if nonempty_lines else None
    )
    verdict_lines = [
        line for line in body.splitlines() if line.lstrip().startswith("Verdict:")
    ]
    if first_match is None or len(verdict_lines) != 1:
        raise FlowError(
            "INVALID_REVIEW_REPORT",
            "the first non-empty review-report line must be exactly 'Verdict: PASS|CONDITIONAL|FAIL', with no second Verdict line",
            details={
                "path": str(path),
                "verdict_field_count": len(verdict_lines),
                "first_nonempty_line": nonempty_lines[0] if nonempty_lines else None,
            },
        )
    return first_match.group(1)


def _latest_artifact(state_value: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (artifact for artifact in reversed(state_value.get("artifacts", [])) if artifact.get("kind") == kind),
        None,
    )


def _assert_artifact_unchanged(artifact: dict[str, Any]) -> None:
    path_value = artifact.get("path")
    if not path_value:
        raise FlowError(
            "ARTIFACT_CHANGED",
            "recorded artifact has no verifiable path",
            details={"artifact_id": artifact.get("artifact_id")},
        )
    path = Path(path_value)
    try:
        current = _hash_artifact(path)
    except (FlowError, OSError) as exc:
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact is missing or unreadable: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "error": str(exc),
            },
        ) from exc
    if current.get("sha256") != artifact.get("sha256"):
        raise FlowError(
            "ARTIFACT_CHANGED",
            f"recorded artifact changed on disk: {path}",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "path": str(path),
                "recorded_sha256": artifact.get("sha256"),
                "current_sha256": current.get("sha256"),
            },
        )


def _require_gate(state_value: dict[str, Any], gate: str) -> dict[str, Any]:
    approval = state_value.get("approvals", {}).get(gate)
    if not approval:
        raise FlowError(
            "APPROVAL_REQUIRED",
            f"the {gate} gate must be approved first",
            details={"gate": gate},
        )
    return approval


def _require_gate_for_latest_artifact(
    state_value: dict[str, Any], gate: str, artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _latest_artifact(state_value, artifact_kind)
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            f"the {gate} gate requires a recorded {artifact_kind} artifact",
            details={"gate": gate, "artifact_kind": artifact_kind},
        )
    _assert_artifact_unchanged(artifact)
    approval = _require_gate(state_value, gate)
    if approval.get("artifact_sha256") != artifact.get("sha256"):
        raise FlowError(
            "STALE_APPROVAL",
            f"the {gate} approval must bind the latest {artifact_kind} artifact",
            details={
                "gate": gate,
                "artifact_kind": artifact_kind,
                "expected_sha256": artifact.get("sha256"),
                "approved_sha256": approval.get("artifact_sha256"),
            },
        )
    return approval, artifact


def _require_current_impact(state_value: dict[str, Any]) -> dict[str, Any]:
    artifact = _latest_artifact(state_value, "impact")
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            "route selection requires a current impact artifact",
            details={"artifact_kind": "impact"},
        )
    _assert_artifact_unchanged(artifact)
    expected = _index_provenance_sha256(state_value)
    metadata = artifact.get("metadata") or {}
    recorded = metadata.get("index_provenance_sha256")
    expected_generation = int(state_value.get("impact_generation", 0))
    recorded_generation = metadata.get("impact_generation")
    if recorded != expected or recorded_generation != expected_generation:
        raise FlowError(
            "STALE_IMPACT",
            "latest impact artifact does not describe the current impact epoch and all-repository index provenance",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "expected_index_provenance_sha256": expected,
                "recorded_index_provenance_sha256": recorded,
                "expected_impact_generation": expected_generation,
                "recorded_impact_generation": recorded_generation,
            },
        )
    return artifact


def _require_current_route_selection(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    impact = _require_current_impact(state_value)
    route = state_value.get("route")
    if not isinstance(route, dict) or route.get("value") not in {"direct", "openspec"}:
        raise FlowError("ROUTE_REQUIRED", "a route must be selected for the current impact")
    if (
        route.get("impact_artifact_id") != impact.get("artifact_id")
        or route.get("impact_sha256") != impact.get("sha256")
        or route.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or route.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
    ):
        raise FlowError(
            "STALE_ROUTE_SELECTION",
            "route selection is not bound to the latest current impact artifact",
        )
    return route, impact


def _require_route_gate(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, impact = _require_current_route_selection(state_value)
    approval, approved_impact = _require_gate_for_latest_artifact(
        state_value, "route", "impact"
    )
    if (
        approval.get("artifact_id") != impact.get("artifact_id")
        or approval.get("index_provenance_sha256")
        != (impact.get("metadata") or {}).get("index_provenance_sha256")
        or approval.get("impact_generation")
        != (impact.get("metadata") or {}).get("impact_generation")
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "route approval is not bound to the current impact record and index provenance",
        )
    return approval, approved_impact


def _latest_review_snapshot(state_value: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = state_value.get("review_snapshots", [])
    return snapshots[-1] if snapshots else None


def _require_review_report_for_latest_snapshot(
    state_value: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _latest_review_snapshot(state_value)
    if not snapshot:
        raise FlowError("CURRENT_REVIEW_REQUIRED", "a review snapshot is required")
    report = _latest_artifact(state_value, "review-report")
    if not report:
        raise FlowError("ARTIFACT_REQUIRED", "the review gate requires a review-report artifact")
    _assert_artifact_unchanged(report)
    body_verdict = _parse_review_report_verdict(Path(report["path"]))
    metadata_verdict = (report.get("metadata") or {}).get("verdict")
    if body_verdict != metadata_verdict:
        raise FlowError(
            "REVIEW_VERDICT_MISMATCH",
            "review report Verdict field no longer matches its recorded metadata",
            details={
                "body_verdict": body_verdict,
                "metadata_verdict": metadata_verdict,
                "path": report.get("path"),
            },
        )
    bound_snapshot = (report.get("metadata") or {}).get("review_snapshot_sha256")
    if bound_snapshot != snapshot.get("sha256"):
        raise FlowError(
            "STALE_REVIEW_REPORT",
            "the latest review report is not bound to the latest review snapshot",
            details={
                "report_sha256": report.get("sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "bound_review_snapshot_sha256": bound_snapshot,
            },
        )
    return report, snapshot


def _require_review_gate(state_value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report, snapshot = _require_review_report_for_latest_snapshot(state_value)
    verdict = (report.get("metadata") or {}).get("verdict")
    if verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
        raise FlowError(
            "INVALID_REVIEW_VERDICT",
            "latest review report has no valid structured verdict",
            details={"verdict": verdict},
        )
    if verdict == "FAIL":
        raise FlowError(
            "REVIEW_VERDICT_FAILED",
            "a FAIL review report cannot pass the final review gate",
        )
    approval = _require_gate(state_value, "review")
    if (
        approval.get("artifact_sha256") != report.get("sha256")
        or approval.get("review_snapshot_sha256") != snapshot.get("sha256")
        or approval.get("review_verdict") != verdict
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "the review approval must bind the latest report and review snapshot",
            details={
                "expected_report_sha256": report.get("sha256"),
                "approved_report_sha256": approval.get("artifact_sha256"),
                "expected_review_snapshot_sha256": snapshot.get("sha256"),
                "approved_review_snapshot_sha256": approval.get("review_snapshot_sha256"),
                "expected_verdict": verdict,
                "approved_verdict": approval.get("review_verdict"),
            },
        )
    if verdict == "CONDITIONAL" and approval.get("conditional_accepted") is not True:
        raise FlowError(
            "CONDITIONAL_ACCEPTANCE_REQUIRED",
            "the CONDITIONAL review verdict lacks explicit acceptance",
        )
    return approval, report


def _fingerprint_repo(repo: Path) -> dict[str, Any]:
    resolved_repo = repo.resolve(strict=True)
    _assert_evidence_supported(repo)
    head = _git_evidence(repo, "rev-parse", "HEAD")
    cached = _git_diff(
        repo, "--binary", "--full-index", "--cached", "--", text=False
    )
    unstaged = _git_diff(repo, "--binary", "--full-index", "--", text=False)
    untracked_output = _git_evidence(
        repo,
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        text=False,
    )
    untracked_paths = [item for item in untracked_output.split(b"\0") if item]
    untracked: list[dict[str, Any]] = []
    for relative_bytes in sorted(untracked_paths):
        relative = relative_bytes.decode("utf-8", "replace")
        target = repo / os.fsdecode(relative_bytes)
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            raise FlowError(
                "WORKTREE_CHANGED",
                f"untracked path disappeared while creating a snapshot: {relative}",
                details={"repository": str(repo), "path": relative},
            )
        if stat.S_ISLNK(metadata.st_mode):
            content_hash = _sha256_bytes(os.readlink(target).encode("utf-8", "surrogateescape"))
            item_type = "symlink"
        elif stat.S_ISREG(metadata.st_mode):
            content_hash = _sha256_file(target)
            item_type = "file"
        else:
            content_hash = None
            item_type = "other"
        untracked.append(
            {
                "path": relative,
                "path_bytes_hex": relative_bytes.hex(),
                "type": item_type,
                "size": metadata.st_size,
                "sha256": content_hash,
            }
        )
    payload = {
        "path": str(resolved_repo),
        "root": _git_evidence(repo, "rev-parse", "--show-toplevel"),
        "branch": _git_evidence_optional(
            repo, "symbolic-ref", "--quiet", "--short", "HEAD"
        ),
        "git_dir": str(_git_evidence_path(repo, "--git-dir")),
        "git_common_dir": str(_git_evidence_path(repo, "--git-common-dir")),
        "linked_worktree": _git_evidence_path(
            repo, "--git-dir"
        )
        != _git_evidence_path(repo, "--git-common-dir"),
        "head_sha": head,
        "cached_sha256": _sha256_bytes(cached),
        "unstaged_sha256": _sha256_bytes(unstaged),
        "tracked_worktree": _tracked_worktree_manifest(repo),
        "untracked": untracked,
    }
    payload["sha256"] = _sha256_bytes(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return payload


def _untracked_filesystem_path(item: dict[str, Any]) -> str:
    raw_hex = item.get("path_bytes_hex")
    if isinstance(raw_hex, str):
        try:
            return os.fsdecode(bytes.fromhex(raw_hex))
        except ValueError as exc:
            raise FlowError(
                "REVIEW_SNAPSHOT_INVALID",
                "untracked evidence contains an invalid raw path encoding",
                details={"path": item.get("path"), "path_bytes_hex": raw_hex},
            ) from exc
    # Compatibility for evidence recorded before raw path bytes were bound.
    return str(item.get("path", ""))


def _working_path(repo: dict[str, Any]) -> Path:
    workspace = repo.get("workspace")
    if isinstance(workspace, dict) and workspace.get("ready") and workspace.get("path"):
        return Path(workspace["path"])
    return Path(repo["path"])


def _copy_state(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _recommended_index_name(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> str:
    prefix = f"devflow-{state_value['task_id']}-{repo['id']}"
    if role == "baseline":
        return f"{prefix}-baseline"
    if role == "workspace":
        generation = int(
            (state_value.get("workspace") or {}).get("generation", 0)
        )
        return f"{prefix}-workspace-r{generation}"
    raise ValueError(f"unknown index role: {role}")


def _index_role_for_status(state_value: dict[str, Any]) -> str | None:
    if _flow(state_value) == "lite":
        # Lite tasks record no controller-bound indexes; ad-hoc codebase-memory
        # use stays outside the evidence chain.
        return None
    status = state_value.get("status")
    if status == "BLOCKED":
        status = (state_value.get("blocked") or {}).get("from_status")
    if status in BASELINE_INDEX_STATES:
        return "baseline"
    if status in WORKSPACE_INDEX_STATES:
        return "workspace"
    return None


def _index_role_summary(
    state_value: dict[str, Any], repo: dict[str, Any], role: str
) -> dict[str, Any]:
    record = repo.get("index" if role == "baseline" else "workspace_index")
    record = record if isinstance(record, dict) else {}
    summary: dict[str, Any] = {
        "role": role,
        "recorded_project": record.get("index_id"),
        "recommended_project": _recommended_index_name(
            state_value, repo, role
        ),
        "recorded": bool(record),
        "repo_path": record.get("repo_path"),
    }
    if role == "workspace":
        summary["workspace_generation"] = record.get(
            "workspace_generation"
        )
    return summary


def _index_selection(state_value: dict[str, Any]) -> dict[str, Any]:
    """Describe the exact phase-selected project without selecting it for callers."""

    selected_role = _index_role_for_status(state_value)
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        baseline = _index_role_summary(state_value, repo, "baseline")
        workspace = _index_role_summary(state_value, repo, "workspace")
        selected = (
            baseline
            if selected_role == "baseline"
            else workspace
            if selected_role == "workspace"
            else None
        )
        repositories.append(
            {
                "repository_id": repo.get("id"),
                "selected_role": selected_role,
                "role": selected_role,
                "recorded_project": (
                    selected.get("recorded_project") if selected else None
                ),
                "recommended_project": (
                    selected.get("recommended_project") if selected else None
                ),
                "baseline": baseline,
                "workspace": workspace,
            }
        )
    return {
        "automatic": False,
        "selected_role": selected_role,
        # ``role`` is retained as a compact compatibility alias.  Consumers
        # should use selected_role and pass recorded_project explicitly.
        "role": selected_role,
        "repositories": repositories,
    }


def _result(command: str, state_value: dict[str, Any], **extra: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "ok": True,
        "command": command,
        "task_id": state_value["task_id"],
        "revision": state_value["revision"],
        "status": state_value["status"],
        "flow": _flow(state_value),
        "index_selection": _index_selection(state_value),
    }
    response.update(extra)
    return response


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    requirement = (args.requirement_option or args.requirement or "").strip()
    if not requirement:
        raise FlowError("INVALID_ARGUMENT", "start requires a non-empty requirement")
    flow = getattr(args, "flow", None) or DEFAULT_FLOW
    if flow not in FLOW_MODES:
        raise FlowError(
            "INVALID_ARGUMENT",
            f"flow must be one of: {', '.join(FLOW_MODES)}",
            details={"flow": flow},
        )
    task_id = args.task_id or f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    _validate_task_id(task_id)
    if not args.repo:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one --repo")
    roots: list[Path] = []
    for supplied in args.repo:
        root = _canonical_repo(supplied)
        if root not in roots:
            roots.append(root)
    if not roots:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one distinct Git repository")
    for root in roots:
        _assert_path_in_scope(root, "repository", args.data_dir)
    common_dirs: dict[Path, Path] = {}
    for root in roots:
        common_dir = _git_evidence_path(root, "--git-common-dir")
        previous = common_dirs.get(common_dir)
        if previous is not None:
            raise FlowError(
                "DUPLICATE_GIT_REPOSITORY",
                "multiple configured checkouts share the same Git common directory",
                details={
                    "repository": str(root),
                    "duplicate_of": str(previous),
                    "git_common_dir": str(common_dir),
                },
            )
        common_dirs[common_dir] = root
    protected = list(dict.fromkeys(args.protected_branch or DEFAULT_PROTECTED_BRANCHES))
    repositories: list[dict[str, Any]] = []
    ids: set[str] = set()
    for root in roots:
        repo_id = _repo_id(root, ids)
        ids.add(repo_id)
        repositories.append(
            {
                "id": repo_id,
                "path": str(root),
                "canonical_path": str(root),
                "protected_branches": protected,
                "preflight": None,
                "baseline": None,
                "analysis_workspace": None,
                "index": None,
                "workspace": None,
                "workspace_index": None,
                "index_history": [],
                "workspace_history": [],
            }
        )
    task_dir = _task_dir(task_id, args.data_dir)
    with _task_lock(task_dir):
        if (task_dir / "state.json").exists():
            raise FlowError("TASK_EXISTS", f"task already exists: {task_id}", details={"task_id": task_id})
        _ensure_dir(task_dir / "artifacts")
        created = utc_now()
        state_value: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "requirement": requirement,
            "status": "INTAKE",
            "revision": 0,
            "created_at": created,
            "updated_at": created,
            "flow": flow,
            "route": None,
            "repositories": repositories,
            "artifacts": [],
            "approvals": {},
            "tests": [],
            "review_snapshots": [],
            "impact_generation": 0,
            "planning_generation": 0,
            "workspace": {
                "strategy": "in-place" if flow == "lite" else "worktree",
                "ready": False,
                "generation": 0,
            },
            "blocked": None,
            "cancelled": None,
        }
        _commit_state(None, state_value, task_dir, "task_started", {"repository_ids": sorted(ids)})
    return _result("start", state_value, task=state_value)


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    state_value = load_state(_task_arg(args), args.data_dir)
    return _result("show", state_value, task=state_value)


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    tasks_dir = resolve_data_dir(args.data_dir) / "tasks"
    values: list[dict[str, Any]] = []
    if tasks_dir.is_dir():
        for state_file in tasks_dir.glob("*/state.json"):
            try:
                state_value = load_state(state_file)
            except FlowError:
                continue
            if args.active_only and state_value.get("status") in TERMINAL_STATES:
                continue
            if args.status and state_value.get("status") not in args.status:
                continue
            values.append(
                {
                    "task_id": state_value.get("task_id"),
                    "requirement": state_value.get("requirement"),
                    "status": state_value.get("status"),
                    "flow": _flow(state_value),
                    "revision": state_value.get("revision"),
                    "updated_at": state_value.get("updated_at"),
                    "repositories": [repo.get("path") for repo in state_value.get("repositories", [])],
                }
            )
    values.sort(key=lambda item: (str(item.get("updated_at", "")), str(item.get("task_id", ""))), reverse=True)
    return {"ok": True, "command": "list", "count": len(values), "tasks": values}


def _apply_scope_changes(scope: dict[str, Any], args: argparse.Namespace) -> None:
    """Apply one invocation's edits: mode, then removals, then additions."""

    if args.mode:
        scope["mode"] = args.mode
    for option, key in (("remove", "include"), ("remove_exclude", "exclude")):
        for supplied in getattr(args, option) or []:
            flag = "--" + option.replace("_", "-")
            root = _normalize_scope_root(supplied, flag)
            if root not in scope[key]:
                raise FlowError(
                    "SCOPE_PATH_NOT_CONFIGURED",
                    f"{flag} does not match a configured scope directory",
                    details={"path": root, "configured": list(scope[key])},
                )
            scope[key].remove(root)
    # Adding the first included directory is what turns the allowlist on; an
    # include recorded while the mode stays "all" would silently do nothing.
    activates = args.mode is None and scope["mode"] == "all" and not scope["include"]
    for option, key in (("add", "include"), ("add_exclude", "exclude")):
        for supplied in getattr(args, option) or []:
            root = _normalize_scope_root(supplied, "--" + option.replace("_", "-"))
            if root not in scope[key]:
                scope[key].append(root)
    if activates and scope["include"]:
        scope["mode"] = "allowlist"


def command_scope(args: argparse.Namespace) -> dict[str, Any]:
    path = config_path(args.data_dir)
    edits = (
        args.clear
        or args.mode
        or args.add
        or args.remove
        or args.add_exclude
        or args.remove_exclude
    )
    if edits:
        with _config_lock(resolve_data_dir(args.data_dir)):
            try:
                config = load_config(args.data_dir)
                # load_config already normalized; repeat it for an independent
                # snapshot the edits below cannot mutate through shared lists.
                before = _normalize_scope(config["scope"])
            except FlowError:
                # An unusable configuration must still be resettable.
                if not args.clear:
                    raise
                before = None
            if args.clear:
                config = _default_config()
            _apply_scope_changes(config["scope"], args)
            config["scope"] = _normalize_scope(config["scope"])
            _atomic_write_json(path, config)
            stored = config["scope"]
    else:
        before = stored = load_config(args.data_dir)["scope"]
    effective = resolve_scope(args.data_dir)
    overrides = effective.pop("overrides", {})
    response = {
        "ok": True,
        "command": "scope",
        "config_path": str(path),
        "changed": stored != before,
        "scope": stored,
        "effective": effective,
        "overrides": overrides,
        "summary": _scope_summary(effective),
        "missing_paths": [
            root
            for root in (*effective["include"], *effective["exclude"])
            if not Path(root).is_dir()
        ],
    }
    if args.check is not None:
        response["check"] = evaluate_scope(
            _normalize_scope_root(args.check, "--check"), effective
        )
    return response


def command_preflight(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        allowed = {"INTAKE", "PREFLIGHTED"}
        if current.get("status") == "BLOCKED" and (current.get("blocked") or {}).get("phase") == "preflight":
            allowed.add("BLOCKED")
        _assert_status(current, allowed, "preflight")
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        for repo in selected:
            repo["preflight"] = _preflight_repo(repo, args.remote, args.base)
        all_checked = all(repo.get("preflight") is not None for repo in state_value["repositories"])
        blockers = [
            {"repository_id": repo["id"], "blockers": repo["preflight"]["blockers"]}
            for repo in state_value["repositories"]
            if repo.get("preflight") and repo["preflight"]["blockers"]
        ]
        if blockers:
            previous = current["status"] if current["status"] != "BLOCKED" else (current.get("blocked") or {}).get("from_status", "INTAKE")
            state_value["status"] = "BLOCKED"
            state_value["blocked"] = {
                "phase": "preflight",
                "from_status": previous,
                "reason": "preflight blockers detected",
                "details": blockers,
                "at": utc_now(),
            }
        elif all_checked:
            state_value["status"] = "PREFLIGHTED"
            state_value["blocked"] = None
        # Remote/base selection and HEAD evidence were just refreshed.  A
        # previous baseline or lite approval must never authorize this new
        # preflight.
        state_value["approvals"].pop("baseline-fetch", None)
        state_value["approvals"].pop(LITE_GATE, None)
        _commit_state(
            current,
            state_value,
            task_dir,
            "preflight_recorded",
            {"repository_ids": [repo["id"] for repo in selected], "blockers": blockers},
        )
    return _result(
        "preflight",
        state_value,
        ready=all_checked and not blockers,
        repositories=[{"id": repo["id"], "preflight": repo["preflight"]} for repo in selected],
    )


def _git_common_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _git_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _is_linked_worktree(repo: Path) -> bool:
    return _git_dir(repo) != _git_common_dir(repo)


def _status_porcelain(repo: Path) -> tuple[bool, str]:
    try:
        _assert_evidence_supported(repo)
    except FlowError as exc:
        if exc.code == "COMMAND_FAILED":
            return False, ""
        raise
    result = _run(
        _evidence_git_command(
            repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
            "--no-renames",
        ),
        check=False,
        evidence_git=True,
    )
    if result.returncode != 0:
        return False, result.stdout.strip()
    return True, result.stdout.strip()


def _preflight_remote_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        repositories.append(
            {
                "repository_id": repo["id"],
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "base_branch": preflight.get("base_branch"),
                "base_candidate_ref": preflight.get("base_candidate_ref"),
                "base_candidate_sha": preflight.get("base_candidate_sha"),
                "fetch_refspec": preflight.get("fetch_refspec"),
                "head_sha": preflight.get("head_sha"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _preflight_remote_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_preflight_remote_evidence(state_value)))


def _require_baseline_fetch_approval(state_value: dict[str, Any]) -> dict[str, Any]:
    approval = _require_gate(state_value, "baseline-fetch")
    current_evidence_sha = _preflight_remote_evidence_sha256(state_value)
    if approval.get("preflight_remote_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "baseline-fetch approval does not bind the current preflight remote evidence",
            details={
                "expected_preflight_remote_sha256": current_evidence_sha,
                "approved_preflight_remote_sha256": approval.get("preflight_remote_sha256"),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require baseline-fetch approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        remote = preflight.get("remote")
        recorded_url = preflight.get("remote_url")
        actual_url = _remote_url(Path(repo["path"]), remote)
        if actual_url != recorded_url:
            raise FlowError(
                "REMOTE_URL_CHANGED",
                f"remote URL changed after preflight approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "remote": remote,
                    "recorded_url": recorded_url,
                    "actual_url": actual_url,
                },
            )
        actual_fingerprint = _fingerprint_repo(Path(repo["path"]))["sha256"]
        recorded_fingerprint = preflight.get("worktree_fingerprint_sha256")
        if actual_fingerprint != recorded_fingerprint:
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after preflight approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": recorded_fingerprint,
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _lite_preflight_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    """The exact checkout identity a lite approval authorizes working inside."""

    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        repositories.append(
            {
                "repository_id": repo["id"],
                "branch": preflight.get("branch"),
                "head_sha": preflight.get("head_sha"),
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _lite_preflight_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_lite_preflight_evidence(state_value)))


def _require_lite_gate(
    state_value: dict[str, Any], *, verify_worktree: bool = False
) -> dict[str, Any]:
    """Require a lite approval bound to the current preflight evidence.

    The approval authorizes in-place work on the exact recorded checkouts, so
    the branch identity is revalidated live at every downstream gate.  The
    worktree fingerprint and ``HEAD`` are only revalidated when entering
    implementation: after that point the edits themselves legitimately change
    both, and test currency binds the final tree instead.
    """

    approval = _require_gate(state_value, LITE_GATE)
    current_evidence_sha = _lite_preflight_evidence_sha256(state_value)
    if approval.get("preflight_evidence_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "lite approval does not bind the current preflight evidence",
            details={
                "expected_preflight_evidence_sha256": current_evidence_sha,
                "approved_preflight_evidence_sha256": approval.get(
                    "preflight_evidence_sha256"
                ),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require lite approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        path = Path(repo["path"])
        actual_branch = _git_optional(
            path, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        if actual_branch != preflight.get("branch"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout branch changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_branch": preflight.get("branch"),
                    "actual_branch": actual_branch,
                },
            )
        if not verify_worktree:
            continue
        actual_head = _git_optional(path, "rev-parse", "HEAD")
        if actual_head != preflight.get("head_sha"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout HEAD changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_head_sha": preflight.get("head_sha"),
                    "actual_head_sha": actual_head,
                },
            )
        actual_fingerprint = _fingerprint_repo(path)["sha256"]
        if actual_fingerprint != preflight.get("worktree_fingerprint_sha256"):
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _materialize_analysis_workspace(
    state_value: dict[str, Any], repo: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    source = Path(repo["path"]).resolve(strict=True)
    _assert_evidence_supported(source)
    base_sha = (repo.get("baseline") or {}).get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
    _assert_tree_checkout_supported(source, base_sha)
    destination = (
        data_root / "analysis" / state_value["task_id"] / repo["id"]
    ).resolve(strict=False)
    entries = _worktree_entries(source)
    destination_entry = next(
        (
            entry
            for entry in entries
            if Path(entry.get("worktree", "")).resolve(strict=False) == destination
        ),
        None,
    )
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        head = _git_optional(destination, "rev-parse", "HEAD")
        branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _git_common_dir(destination) == _git_common_dir(source)
                linked_worktree = _is_linked_worktree(destination)
            except (FlowError, OSError):
                same_common_dir = False
        if (
            not root
            or Path(root).resolve(strict=False) != destination
            or not same_common_dir
            or not linked_worktree
            or head != base_sha
            or branch is not None
            or not destination_entry
            or destination_entry.get("HEAD") != head
            or "detached" not in destination_entry
            or not status_available
            or bool(status_porcelain)
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"analysis path exists but is not the pinned detached worktree: {destination}",
                details={
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "expected_head": base_sha,
                    "actual_head": head,
                    "actual_branch": branch,
                    "same_common_dir": same_common_dir,
                    "linked_worktree": linked_worktree,
                    "dirty": bool(status_porcelain),
                    "status_porcelain": status_porcelain,
                },
            )
        return {
            "path": str(destination),
            "head_sha": head,
            "detached": True,
            "ready": True,
            "created": False,
            "materialized_at": utc_now(),
        }
    if destination_entry:
        recorded = repo.get("analysis_workspace") or {}
        recorded_path = Path(recorded.get("path", "")).resolve(strict=False)
        if not recorded.get("ready") or recorded_path != destination:
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"Git reports an unowned analysis path that is unavailable: {destination}",
                details={"repository_id": repo["id"], "path": str(destination)},
            )
    _ensure_dir(destination.parent)
    add_arguments = ["worktree", "add"]
    if destination_entry:
        add_arguments.append("--force")
    add_arguments.extend(["--detach", str(destination), base_sha])
    _git(source, "-c", f"core.hooksPath={os.devnull}", *add_arguments)
    head = _git(destination, "rev-parse", "HEAD")
    branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(destination)
    created_entry = next(
        (
            entry
            for entry in _worktree_entries(source)
            if Path(entry.get("worktree", "")).resolve(strict=False) == destination
        ),
        None,
    )
    if (
        head != base_sha
        or branch is not None
        or _git_common_dir(destination) != _git_common_dir(source)
        or not _is_linked_worktree(destination)
        or not status_available
        or bool(status_porcelain)
        or not created_entry
        or created_entry.get("HEAD") != head
        or "detached" not in created_entry
    ):
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            f"created analysis worktree failed verification: {destination}",
            details={
                "expected_head": base_sha,
                "actual_head": head,
                "actual_branch": branch,
                "dirty": bool(status_porcelain),
                "status_porcelain": status_porcelain,
            },
        )
    return {
        "path": str(destination),
        "head_sha": head,
        "detached": True,
        "ready": True,
        "created": True,
        "materialized_at": utc_now(),
    }


def _analysis_workspace_integrity_error(repo: dict[str, Any]) -> str | None:
    analysis = repo.get("analysis_workspace") or {}
    if not analysis.get("ready") or not analysis.get("path"):
        return f"analysis workspace is not ready: {repo.get('id')}"
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(analysis["path"]).resolve(strict=False)
    if not path.is_dir():
        return f"analysis workspace path is missing: {repo.get('id')}"
    expected_head = (repo.get("baseline") or {}).get("base_sha")
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    head = _git_optional(path, "rev-parse", "HEAD")
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(path)
    try:
        same_common_dir = _git_common_dir(path) == _git_common_dir(source)
        linked_worktree = _is_linked_worktree(path)
    except (FlowError, OSError):
        same_common_dir = False
        linked_worktree = False
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if Path(item.get("worktree", "")).resolve(strict=False) == path
        ),
        None,
    )
    if (
        not root
        or Path(root).resolve(strict=False) != path
        or head != expected_head
        or branch is not None
        or not same_common_dir
        or not linked_worktree
        or not status_available
        or bool(status_porcelain)
        or not entry
        or entry.get("HEAD") != head
        or "detached" not in entry
    ):
        return f"analysis workspace identity, baseline or cleanliness changed: {repo.get('id')}"
    return None


def command_baseline(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "baseline")
        _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "baseline")
        baseline_approval = _require_baseline_fetch_approval(current)
        if args.fetch and baseline_approval.get("fetch_allowed") is not True:
            raise FlowError(
                "FETCH_NOT_APPROVED",
                "baseline --fetch requires baseline-fetch approval with --allow-fetch",
            )
        already_baselined = current.get("status") == "BASELINED" and all(
            repo.get("baseline") for repo in current["repositories"]
        )
        if already_baselined and args.fetch:
            raise FlowError(
                "BASELINE_ALREADY_PINNED",
                "--fetch cannot repin an existing baseline; the recorded base is immutable",
            )
        if already_baselined and not args.materialize:
            return _result(
                "baseline",
                current,
                unchanged=True,
                repositories=[
                    {
                        "id": repo["id"],
                        "baseline": repo["baseline"],
                        "analysis_workspace": repo.get("analysis_workspace"),
                    }
                    for repo in current["repositories"]
                ],
            )
        state_value = _copy_state(current)
        if not already_baselined:
            for repo in state_value["repositories"]:
                preflight = repo.get("preflight") or {}
                if not preflight.get("ready"):
                    raise FlowError(
                        "PREFLIGHT_REQUIRED",
                        f"repository has not passed preflight: {repo['id']}",
                        details={"repository_id": repo["id"]},
                    )
                path = Path(repo["path"])
                current_head = _git(path, "rev-parse", "HEAD")
                if current_head != preflight.get("head_sha"):
                    raise FlowError(
                        "HEAD_CHANGED",
                        f"repository HEAD changed after preflight: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "preflight_head": preflight.get("head_sha"),
                            "current_head": current_head,
                        },
                    )
                remote = preflight.get("remote")
                candidate_ref = _baseline_source_ref(
                    remote, preflight.get("base_branch")
                )
                pre_fetch_sha = (
                    _git_optional(
                        path,
                        "rev-parse",
                        "--verify",
                        f"{candidate_ref}^{{commit}}",
                    )
                    if candidate_ref
                    else None
                )
                if args.fetch and remote:
                    fetch_refspec = preflight.get("fetch_refspec")
                    if fetch_refspec != _approved_fetch_refspec(
                        remote, preflight.get("base_branch")
                    ):
                        raise FlowError(
                            "STALE_APPROVAL",
                            "approved fetch refspec no longer matches the selected remote base",
                            details={
                                "repository_id": repo["id"],
                                "fetch_refspec": fetch_refspec,
                            },
                        )
                    _git(
                        path,
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "--",
                        remote,
                        fetch_refspec,
                    )
                source_ref, base_sha = _baseline_ref(path, remote, preflight["base_branch"])
                if not args.fetch and (
                    source_ref != preflight.get("base_candidate_ref")
                    or base_sha != preflight.get("base_candidate_sha")
                ):
                    raise FlowError(
                        "BASE_REF_CHANGED",
                        "base ref changed after preflight approval",
                        details={
                            "repository_id": repo["id"],
                            "approved_ref": preflight.get("base_candidate_ref"),
                            "approved_sha": preflight.get("base_candidate_sha"),
                            "actual_ref": source_ref,
                            "actual_sha": base_sha,
                        },
                    )
                repo["baseline"] = {
                    "recorded_at": utc_now(),
                    "remote": remote,
                    "base_branch": preflight["base_branch"],
                    "source_ref": source_ref,
                    "base_sha": base_sha,
                    "remote_base_sha": base_sha,
                    "head_sha": preflight["head_sha"],
                    "fetched": bool(args.fetch and remote),
                    "pre_fetch_base_sha": pre_fetch_sha,
                    "fetch_refspec": preflight.get("fetch_refspec"),
                }
        if args.materialize:
            source_fingerprints = {
                repo["id"]: _fingerprint_repo(Path(repo["path"]))["sha256"]
                for repo in state_value["repositories"]
            }
            for repo in state_value["repositories"]:
                repo["analysis_workspace"] = _materialize_analysis_workspace(
                    state_value, repo, resolve_data_dir(args.data_dir)
                )
            for repo in state_value["repositories"]:
                error = _analysis_workspace_integrity_error(repo)
                if error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                        error,
                        details={"repository_id": repo["id"]},
                    )
                current_source = _fingerprint_repo(Path(repo["path"]))["sha256"]
                if current_source != source_fingerprints[repo["id"]]:
                    raise FlowError(
                        "SOURCE_WORKTREE_CHANGED",
                        "source checkout changed while materializing analysis worktrees",
                        details={"repository_id": repo["id"]},
                    )
        state_value["status"] = "BASELINED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "baseline_recorded",
            {
                "fetch": bool(args.fetch),
                "materialize": bool(args.materialize),
                "base_shas": {
                    repo["id"]: repo["baseline"]["base_sha"]
                    for repo in state_value["repositories"]
                },
            },
        )
    return _result(
        "baseline",
        state_value,
        repositories=[
            {
                "id": repo["id"],
                "baseline": repo["baseline"],
                "analysis_workspace": repo.get("analysis_workspace"),
            }
            for repo in state_value["repositories"]
        ],
    )


def _validate_degraded_index_metadata(
    metadata: dict[str, Any], approval: dict[str, Any]
) -> None:
    if metadata.get("status") != "failed":
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "an index without --index-id requires metadata status='failed'",
        )
    if metadata.get("impact_degraded_approval_id") != approval.get("approval_id"):
        raise FlowError(
            "STALE_APPROVAL",
            "degraded index metadata must bind the current impact-degraded approval",
            details={
                "expected_approval_id": approval.get("approval_id"),
                "provided_approval_id": metadata.get("impact_degraded_approval_id"),
            },
        )
    if not isinstance(metadata.get("error"), str) or not metadata["error"].strip():
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires a non-empty error",
        )
    if not metadata.get("fallback_coverage"):
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires non-empty fallback_coverage",
        )


def _index_provenance_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        index = repo.get("index")
        if not isinstance(index, dict):
            raise FlowError(
                "INDEX_REQUIRED",
                f"repository is missing index provenance: {repo.get('id')}",
            )
        if not index.get("index_record_id"):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                f"repository index has no stable record token: {repo.get('id')}",
            )
        receipt = index.get("receipt")
        if isinstance(receipt, dict):
            receipt_path = Path(str(receipt.get("path", "")))
            expected_receipt_sha = receipt.get("sha256")
            try:
                actual_receipt_sha = (
                    _sha256_file(receipt_path) if receipt_path.is_file() else None
                )
            except OSError:
                actual_receipt_sha = None
            if (
                not isinstance(expected_receipt_sha, str)
                or actual_receipt_sha != expected_receipt_sha
            ):
                raise FlowError(
                    "INDEX_RECEIPT_CHANGED",
                    f"index receipt is missing or changed: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "path": str(receipt_path),
                        "expected_sha256": expected_receipt_sha,
                        "actual_sha256": actual_receipt_sha,
                    },
                )
        if not index.get("index_id"):
            approval = _require_gate(state_value, "impact-degraded")
            _validate_degraded_index_metadata(index.get("metadata") or {}, approval)
            if index.get("impact_degraded_approval_id") != approval.get("approval_id"):
                raise FlowError(
                    "STALE_APPROVAL",
                    f"degraded index no longer binds the current approval: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "expected_approval_id": approval.get("approval_id"),
                        "recorded_approval_id": index.get("impact_degraded_approval_id"),
                    },
                )
        repositories.append(
            {
                "repository_id": repo["id"],
                "index_record_id": index["index_record_id"],
                "commit_sha": index.get("commit_sha"),
                "index_id": index.get("index_id"),
                "receipt": index.get("receipt"),
                "metadata": index.get("metadata") or {},
                "impact_degraded_approval_id": index.get(
                    "impact_degraded_approval_id"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _index_provenance_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_index_provenance_evidence(state_value)))


def _index_receipt(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    receipt_path = Path(path_value).expanduser().resolve(strict=True)
    return {
        "path": str(receipt_path),
        "sha256": _sha256_file(receipt_path),
        "size": receipt_path.stat().st_size,
    }


def _repository_index_history(repo: dict[str, Any]) -> list[dict[str, Any]]:
    history = repo.setdefault("index_history", [])
    if not isinstance(history, list) or not all(
        isinstance(item, dict) for item in history
    ):
        raise FlowError(
            "INDEX_HISTORY_INVALID",
            f"repository index history has an invalid structure: {repo.get('id')}",
            details={"repository_id": repo.get("id")},
        )
    return history


def _archive_replaced_index(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    previous_role: str,
    replacement: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(previous, dict):
        return None, None
    previous_record = _copy_state(previous)
    previous_record.setdefault("role", previous_role)
    replacement_binding = {
        "role": replacement.get("role"),
        "project": replacement.get("index_id"),
        "index_id": replacement.get("index_id"),
        "index_record_id": replacement.get("index_record_id"),
    }
    archived = {
        **previous_record,
        "superseded_at": replacement.get("recorded_at") or utc_now(),
        "replacement_role": replacement_binding["role"],
        "replacement_project": replacement_binding["project"],
        "replacement_index_id": replacement_binding["index_id"],
        "replacement_record_id": replacement_binding["index_record_id"],
        "replacement_index_record_id": replacement_binding[
            "index_record_id"
        ],
        "replacement": replacement_binding,
    }
    _repository_index_history(repo).append(archived)
    return previous_record, archived


def _recorded_index_change(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    role: str,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    previous_record, history_entry = _archive_replaced_index(
        repo, previous, role, replacement
    )
    return {
        "repository_id": repo.get("id"),
        "role": role,
        "previous": previous_record,
        "current": _copy_state(replacement),
        "history_entry": _copy_state(history_entry)
        if history_entry is not None
        else None,
    }


def _archived_workspace_indexes(repo: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for workspace in repo.get("workspace_history", []):
        if not isinstance(workspace, dict):
            continue
        archived = workspace.get("workspace_index")
        if isinstance(archived, dict):
            yield archived


def _assert_index_id_available(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    role: str,
    index_id: str,
) -> None:
    conflicts: list[dict[str, Any]] = []
    current_generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    for candidate in state_value.get("repositories", []):
        baseline = candidate.get("index")
        if isinstance(baseline, dict) and baseline.get("index_id") == index_id:
            same_role_refresh = (
                role == "baseline" and candidate.get("id") == repo.get("id")
            )
            if not same_role_refresh:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "baseline",
                        "recorded_project": index_id,
                    }
                )
        workspace = candidate.get("workspace_index")
        if isinstance(workspace, dict) and workspace.get("index_id") == index_id:
            same_current_record = (
                role == "workspace"
                and candidate.get("id") == repo.get("id")
                and workspace.get("workspace_generation")
                == current_generation
            )
            if not same_current_record:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace",
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for historical in _repository_index_history(candidate):
            if historical.get("index_id") != index_id:
                continue
            historical_role = historical.get("role")
            same_repository_role = (
                candidate.get("id") == repo.get("id")
                and historical_role == role
            )
            reusable_history = same_repository_role and (
                role == "baseline"
                or (
                    role == "workspace"
                    and historical.get("workspace_generation")
                    == current_generation
                )
            )
            if not reusable_history:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": historical_role,
                        "origin": "index-history",
                        "workspace_generation": historical.get(
                            "workspace_generation"
                        ),
                        "index_record_id": historical.get(
                            "index_record_id"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for archived in _archived_workspace_indexes(candidate):
            if archived.get("index_id") == index_id:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace-history",
                        "origin": "workspace-history",
                        "workspace_generation": archived.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
    if conflicts:
        error_code = (
            "WORKSPACE_INDEX_ID_CONFLICT"
            if role == "workspace"
            else "INDEX_ID_CONFLICT"
        )
        raise FlowError(
            error_code,
            "index project must be distinct across role/repository pairs and retired workspace generations",
            details={
                "repository_id": repo.get("id"),
                "role": role,
                "index_id": index_id,
                "conflicts": conflicts,
            },
        )


def command_record_index(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "record-index")
        role = args.role
        if role == "baseline":
            _assert_status(current, {"BASELINED", "INDEXED"}, "record-index")
        else:
            _assert_status(
                current,
                {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING"},
                "record-index --role workspace",
            )
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        metadata = _parse_json_object(args.metadata_json, "--metadata-json")
        degraded_approval: dict[str, Any] | None = None
        normalized_index_id = args.index_id.strip() if args.index_id else None
        if role == "workspace":
            if not normalized_index_id:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_REQUIRED",
                    "workspace indexes require a successful non-empty --index-id",
                )
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "workspace index metadata cannot record a failed index",
                )
            if metadata.get("persistence") is not False:
                raise FlowError(
                    "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
                    "workspace index metadata must explicitly set persistence=false",
                )
            _require_workspace_ready(current)
            if len(selected) > 1:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_CONFLICT",
                    "one workspace project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "workspace", normalized_index_id
            )
        elif normalized_index_id:
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "metadata status='failed' is only valid when --index-id is omitted",
                )
            if len(selected) > 1:
                raise FlowError(
                    "INDEX_ID_CONFLICT",
                    "one baseline project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "baseline", normalized_index_id
            )
        else:
            degraded_approval = _require_gate(current, "impact-degraded")
            _validate_degraded_index_metadata(metadata, degraded_approval)
        receipt = _index_receipt(args.receipt)
        index_changes: list[dict[str, Any]] = []
        for repo in selected:
            if role == "baseline":
                analysis_workspace = repo.get("analysis_workspace") or {}
                if not analysis_workspace.get("ready"):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_REQUIRED",
                        f"materialize the pinned baseline before recording an index: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "hint": "baseline --materialize",
                        },
                    )
                integrity_error = _analysis_workspace_integrity_error(repo)
                if integrity_error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        integrity_error,
                        details={"repository_id": repo["id"]},
                    )
                repo_path = Path(analysis_workspace["path"])
                expected_sha = repo["baseline"]["base_sha"]
                analysis_head = _git(repo_path, "rev-parse", "HEAD")
                analysis_branch = _git_optional(
                    repo_path,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                )
                status_available, analysis_status = _status_porcelain(repo_path)
                if (
                    analysis_head != expected_sha
                    or analysis_branch is not None
                    or not status_available
                    or analysis_status
                ):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        f"analysis worktree no longer exactly represents the pinned base: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_head": expected_sha,
                            "actual_head": analysis_head,
                            "actual_branch": analysis_branch,
                            "dirty": bool(analysis_status),
                        },
                    )
                commit_sha = args.commit or expected_sha
                resolved = _git_optional(
                    repo_path,
                    "rev-parse",
                    "--verify",
                    f"{commit_sha}^{{commit}}",
                )
                if not resolved:
                    raise FlowError(
                        "INVALID_COMMIT",
                        f"index commit does not exist in repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "commit": commit_sha,
                        },
                    )
                if resolved != expected_sha:
                    raise FlowError(
                        "INDEX_BASE_MISMATCH",
                        f"recorded index must target the pinned base for repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_commit": expected_sha,
                            "provided_commit": resolved,
                        },
                    )
                replacement = {
                    "index_record_id": str(uuid.uuid4()),
                    "recorded_at": utc_now(),
                    "role": "baseline",
                    "commit_sha": resolved,
                    "repo_path": str(repo_path),
                    "index_id": normalized_index_id,
                    "recommended_index_id": _recommended_index_name(
                        state_value, repo, "baseline"
                    ),
                    "receipt": receipt,
                    "metadata": metadata,
                    "impact_degraded_approval_id": (
                        degraded_approval.get("approval_id")
                        if degraded_approval
                        else None
                    ),
                }
                index_changes.append(
                    _recorded_index_change(
                        repo, repo.get("index"), "baseline", replacement
                    )
                )
                repo["index"] = replacement
                continue

            workspace = repo.get("workspace") or {}
            integrity_error = _workspace_integrity_error(state_value, repo)
            if integrity_error:
                raise FlowError(
                    "WORKSPACE_INTEGRITY_FAILED",
                    integrity_error,
                    details={"repository_id": repo["id"]},
                )
            repo_path = Path(workspace["path"]).resolve(strict=True)
            actual_branch = _git_optional(
                repo_path, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            actual_head = _git(repo_path, "rev-parse", "HEAD")
            commit_sha = args.commit or actual_head
            resolved = _git_optional(
                repo_path,
                "rev-parse",
                "--verify",
                f"{commit_sha}^{{commit}}",
            )
            if not resolved:
                raise FlowError(
                    "INVALID_COMMIT",
                    f"index commit does not exist in workspace {repo['id']}",
                    details={"repository_id": repo["id"], "commit": commit_sha},
                )
            if resolved != actual_head:
                raise FlowError(
                    "INDEX_WORKSPACE_MISMATCH",
                    f"workspace index must target the current HEAD for repository {repo['id']}",
                    details={
                        "repository_id": repo["id"],
                        "expected_head": actual_head,
                        "provided_commit": resolved,
                    },
                )
            generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            plan_sha = (
                (state_value.get("workspace") or {}).get("plan") or {}
            ).get("sha256")
            fingerprint = _fingerprint_repo(repo_path)
            replacement = {
                "index_record_id": str(uuid.uuid4()),
                "recorded_at": utc_now(),
                "role": "workspace",
                "commit_sha": actual_head,
                "repo_path": str(repo_path),
                "index_id": normalized_index_id,
                "recommended_index_id": _recommended_index_name(
                    state_value, repo, "workspace"
                ),
                "receipt": receipt,
                "metadata": metadata,
                "fingerprint_sha256": fingerprint["sha256"],
                "workspace_generation": generation,
                "workspace_plan_sha256": plan_sha,
                "workspace_branch": actual_branch,
                "workspace_head_sha": actual_head,
            }
            index_changes.append(
                _recorded_index_change(
                    repo,
                    repo.get("workspace_index"),
                    "workspace",
                    replacement,
                )
            )
            repo["workspace_index"] = replacement
        if role == "baseline":
            all_indexed = all(
                repo.get("index") for repo in state_value["repositories"]
            )
            if all_indexed:
                state_value["status"] = "INDEXED"
        else:
            all_indexed = all(
                repo.get("workspace_index")
                for repo in state_value["repositories"]
            )
        _commit_state(
            current,
            state_value,
            task_dir,
            "index_recorded",
            {
                "role": role,
                "repository_ids": [repo["id"] for repo in selected],
                "complete": all_indexed,
                "index_records": index_changes,
            },
        )
    return _result(
        "record-index",
        state_value,
        role=role,
        complete=all_indexed,
        repositories=[
            {
                "id": repo["id"],
                "role": role,
                "repo_path": (
                    repo["analysis_workspace"]["path"]
                    if role == "baseline"
                    else repo["workspace"]["path"]
                ),
                "index": (
                    repo["index"]
                    if role == "baseline"
                    else repo["workspace_index"]
                ),
                **(
                    {"workspace_index": repo["workspace_index"]}
                    if role == "workspace"
                    else {}
                ),
            }
            for repo in selected
        ],
    )


def command_record_artifact(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    artifact_path = Path(args.path).expanduser().resolve(strict=True)
    artifact_hash = _hash_artifact(artifact_path)
    digest = artifact_hash["sha256"]
    metadata = _parse_json_object(args.metadata_json, "--metadata-json")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "record-artifact")
        if args.kind in {"workspace-plan", "review-snapshot"}:
            raise FlowError(
                "RESERVED_ARTIFACT_KIND",
                f"{args.kind} is controller-generated and cannot be recorded manually",
                details={"kind": args.kind},
            )
        if args.kind != "review-report" and args.verdict:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--verdict is only valid with --kind review-report",
            )
        if args.kind == "review-report":
            _assert_status(current, {"REVIEWING"}, "record-artifact --kind review-report")
            if not args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--kind review-report requires --verdict PASS, CONDITIONAL or FAIL",
                )
            body_verdict = _parse_review_report_verdict(artifact_path)
            if body_verdict != args.verdict:
                raise FlowError(
                    "REVIEW_VERDICT_MISMATCH",
                    "--verdict does not match the review report's Verdict field",
                    details={
                        "path": str(artifact_path),
                        "body_verdict": body_verdict,
                        "verdict": args.verdict,
                    },
                )
            snapshot = _latest_review_snapshot(current)
            if not snapshot:
                raise FlowError(
                    "CURRENT_REVIEW_REQUIRED",
                    "record a review snapshot before recording a review report",
                )
            supplied_binding = metadata.get("review_snapshot_sha256")
            if supplied_binding and supplied_binding != snapshot.get("sha256"):
                raise FlowError(
                    "STALE_REVIEW_REPORT",
                    "review report metadata does not name the latest review snapshot",
                    details={
                        "expected_review_snapshot_sha256": snapshot.get("sha256"),
                        "provided_review_snapshot_sha256": supplied_binding,
                    },
                )
            metadata = dict(metadata)
            metadata["review_snapshot_sha256"] = snapshot["sha256"]
            supplied_verdict = metadata.get("verdict")
            if supplied_verdict and supplied_verdict != args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "review report metadata verdict conflicts with --verdict",
                    details={
                        "metadata_verdict": supplied_verdict,
                        "verdict": args.verdict,
                    },
                )
            metadata["verdict"] = args.verdict
        elif args.kind == "impact":
            _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "record-artifact --kind impact")
            index_provenance_sha = _index_provenance_sha256(current)
            impact_generation = int(current.get("impact_generation", 0))
            supplied_binding = metadata.get("index_provenance_sha256")
            if supplied_binding and supplied_binding != index_provenance_sha:
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata does not bind the current all-repository index provenance",
                    details={
                        "expected_index_provenance_sha256": index_provenance_sha,
                        "provided_index_provenance_sha256": supplied_binding,
                    },
                )
            supplied_generation = metadata.get("impact_generation")
            if (
                supplied_generation is not None
                and supplied_generation != impact_generation
            ):
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata names a stale impact generation",
                    details={
                        "expected_impact_generation": impact_generation,
                        "provided_impact_generation": supplied_generation,
                    },
                )
            metadata = dict(metadata)
            metadata["index_provenance_sha256"] = index_provenance_sha
            metadata["impact_generation"] = impact_generation
        elif args.kind in {"direct-contract", "openspec-plan"}:
            _assert_status(
                current,
                {"PLANNING"},
                f"record-artifact --kind {args.kind}",
            )
            if args.kind == "openspec-plan":
                _assert_openspec_plan_in_current_workspace(current, artifact_path)
            planning_context = _current_planning_context(current)
            planning_context_sha = _planning_context_sha256(planning_context)
            supplied_context = metadata.get("planning_context")
            supplied_context_sha = metadata.get("planning_context_sha256")
            if (
                supplied_context is not None
                and supplied_context != planning_context
            ) or (
                supplied_context_sha is not None
                and supplied_context_sha != planning_context_sha
            ):
                raise FlowError(
                    "STALE_PLAN",
                    "supplied plan metadata names a stale planning context",
                )
            metadata = dict(metadata)
            metadata["planning_context"] = planning_context
            metadata["planning_context_sha256"] = planning_context_sha
        state_value = _copy_state(current)
        artifact = {
            "artifact_id": str(uuid.uuid4()),
            "kind": args.kind,
            "path": str(artifact_path),
            "sha256": digest,
            "artifact_type": artifact_hash["artifact_type"],
            "size": artifact_hash["size"],
            "file_count": artifact_hash["file_count"],
            "total_size": artifact_hash["total_size"],
            "recorded_at": utc_now(),
            "metadata": metadata,
        }
        if "manifest_entry_count" in artifact_hash:
            artifact["manifest_entry_count"] = artifact_hash["manifest_entry_count"]
        state_value["artifacts"].append(artifact)
        if args.kind == "impact":
            state_value["route"] = None
            state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "artifact_recorded", {"artifact_id": artifact["artifact_id"], "kind": args.kind, "sha256": digest})
    return _result("record-artifact", state_value, artifact=artifact)


def command_set_route(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    route = args.route_option or args.route
    if route not in {"direct", "openspec"}:
        raise FlowError("INVALID_ARGUMENT", "route must be 'direct' or 'openspec'")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "set-route")
        _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "set-route")
        impact = _require_current_impact(current)
        state_value = _copy_state(current)
        state_value["route"] = {
            "value": route,
            "reason": args.reason,
            "set_at": utc_now(),
            "impact_artifact_id": impact["artifact_id"],
            "impact_sha256": impact["sha256"],
            "index_provenance_sha256": (impact.get("metadata") or {})[
                "index_provenance_sha256"
            ],
            "impact_generation": (impact.get("metadata") or {})[
                "impact_generation"
            ],
        }
        state_value["status"] = "IMPACT_REVIEW"
        state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "route_set", {"route": route, "reason": args.reason})
    return _result("set-route", state_value, route=state_value["route"])


def command_approve(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    artifact_sha = args.artifact_sha256
    if artifact_sha and not SHA256_RE.fullmatch(artifact_sha):
        raise FlowError("INVALID_ARGUMENT", "--artifact-sha256 must be 64 lowercase hexadecimal characters")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "approve")
        if args.accept_conditional and args.gate != "review":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--accept-conditional is only valid for the review gate",
            )
        if args.allow_fetch and args.gate != "baseline-fetch":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-fetch is only valid for the baseline-fetch gate",
            )
        if args.allow_dirty and args.gate not in {"baseline-fetch", LITE_GATE}:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-dirty is only valid for the baseline-fetch and lite gates",
            )
        if artifact_sha and not any(item.get("sha256") == artifact_sha for item in current.get("artifacts", [])):
            raise FlowError("ARTIFACT_NOT_FOUND", "approval artifact hash is not recorded on this task", details={"sha256": artifact_sha})
        required_artifact_kind: str | None = None
        review_verdict: str | None = None
        baseline_remote_evidence: dict[str, Any] | None = None
        route_impact: dict[str, Any] | None = None
        plan_artifact: dict[str, Any] | None = None
        plan_context: dict[str, Any] | None = None
        lite_evidence: dict[str, Any] | None = None
        if args.gate in {
            "baseline-fetch",
            "impact-degraded",
            "route",
            "workspace",
            "plan",
            "review",
        }:
            _assert_flow(current, "full", f"approve --gate {args.gate}")
        if args.gate == "route":
            _assert_status(current, {"IMPACT_REVIEW"}, "approve --gate route")
            _, route_impact = _require_current_route_selection(current)
            required_artifact_kind = "impact"
        elif args.gate == "plan":
            _assert_status(current, {"PLANNING"}, "approve --gate plan")
            route_value = (current.get("route") or {}).get("value")
            if route_value not in {"direct", "openspec"}:
                raise FlowError("ROUTE_REQUIRED", "an approved route is required before plan approval")
            required_artifact_kind = (
                "direct-contract" if route_value == "direct" else "openspec-plan"
            )
            plan_artifact, plan_context = _require_current_plan_artifact(
                current, required_artifact_kind
            )
        elif args.gate == "review":
            _assert_status(current, {"REVIEWING"}, "approve --gate review")
            required_artifact_kind = "review-report"
            review_report, _ = _require_review_report_for_latest_snapshot(current)
            review_verdict = (review_report.get("metadata") or {}).get("verdict")
            if review_verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
                raise FlowError(
                    "INVALID_REVIEW_VERDICT",
                    "latest review report has no valid structured verdict",
                    details={"verdict": review_verdict},
                )
            if review_verdict == "FAIL":
                raise FlowError(
                    "REVIEW_VERDICT_FAILED",
                    "a FAIL review report cannot be approved",
                )
            if review_verdict == "CONDITIONAL" and not args.accept_conditional:
                raise FlowError(
                    "CONDITIONAL_ACCEPTANCE_REQUIRED",
                    "approving a CONDITIONAL review requires --accept-conditional",
                )
            if review_verdict == "PASS" and args.accept_conditional:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--accept-conditional is not valid for a PASS review",
                )
        elif args.gate == "baseline-fetch":
            _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "approve --gate baseline-fetch")
            baseline_remote_evidence = _preflight_remote_evidence(current)
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "impact-degraded":
            _assert_status(
                current,
                {"BASELINED", "INDEXED"},
                "approve --gate impact-degraded",
            )
        elif args.gate == LITE_GATE:
            _assert_flow(current, "lite", "approve --gate lite")
            _assert_status(current, {"PREFLIGHTED"}, "approve --gate lite")
            lite_evidence = _lite_preflight_evidence(current)
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "workspace":
            _assert_status(current, {"ROUTE_APPROVED", "WORKSPACE_READY"}, "approve --gate workspace")
            required_artifact_kind = "workspace-plan"
        if required_artifact_kind:
            latest = _latest_artifact(current, required_artifact_kind)
            if not latest:
                raise FlowError(
                    "ARTIFACT_REQUIRED",
                    f"the {args.gate} gate requires a recorded {required_artifact_kind} artifact",
                    details={"gate": args.gate, "artifact_kind": required_artifact_kind},
                )
            _assert_artifact_unchanged(latest)
            if artifact_sha != latest.get("sha256"):
                raise FlowError(
                    "APPROVAL_ARTIFACT_MISMATCH",
                    f"the {args.gate} gate must bind the latest {required_artifact_kind} artifact",
                    details={
                        "gate": args.gate,
                        "artifact_kind": required_artifact_kind,
                        "expected_sha256": latest.get("sha256"),
                        "provided_sha256": artifact_sha,
                    },
                )
            if args.gate == "workspace":
                current_generation = int(
                    (current.get("workspace") or {}).get("generation", 0)
                )
                controller_plan = (
                    (current.get("workspace") or {}).get("plan") or {}
                )
                if (
                    (latest.get("metadata") or {}).get("workspace_generation")
                    != current_generation
                    or controller_plan.get("sha256") != latest.get("sha256")
                    or controller_plan.get("artifact_id")
                    != latest.get("artifact_id")
                    or controller_plan.get("path") != latest.get("path")
                ):
                    raise FlowError(
                        "STALE_WORKSPACE_PLAN",
                        "workspace plan is not current for this workspace generation",
                    )
        state_value = _copy_state(current)
        approval = {
            "approval_id": str(uuid.uuid4()),
            "gate": args.gate,
            "note": args.note,
            "artifact_sha256": artifact_sha,
            "approved_at": utc_now(),
            "approved_by": _actor(),
        }
        if args.gate == "review":
            approval["review_snapshot_sha256"] = _latest_review_snapshot(current)["sha256"]
            approval["review_verdict"] = review_verdict
            approval["conditional_accepted"] = bool(
                review_verdict == "CONDITIONAL" and args.accept_conditional
            )
        if args.gate == "baseline-fetch":
            approval["preflight_remote_sha256"] = _sha256_bytes(
                _json_bytes(baseline_remote_evidence)
            )
            approval["preflight_remotes"] = baseline_remote_evidence["repositories"]
            approval["fetch_allowed"] = bool(args.allow_fetch)
            approval["dirty_allowed"] = bool(args.allow_dirty)
        if args.gate == LITE_GATE:
            approval["preflight_evidence_sha256"] = _sha256_bytes(
                _json_bytes(lite_evidence)
            )
            approval["preflight_repositories"] = lite_evidence["repositories"]
            approval["dirty_allowed"] = bool(args.allow_dirty)
        if args.gate == "route":
            approval["artifact_id"] = route_impact["artifact_id"]
            approval["index_provenance_sha256"] = (
                route_impact.get("metadata") or {}
            )["index_provenance_sha256"]
            approval["impact_generation"] = (
                route_impact.get("metadata") or {}
            )["impact_generation"]
        if args.gate == "workspace":
            approval["artifact_id"] = latest["artifact_id"]
            approval["workspace_generation"] = (
                latest.get("metadata") or {}
            )["workspace_generation"]
        if args.gate == "plan":
            approval["artifact_id"] = plan_artifact["artifact_id"]
            approval["planning_context_sha256"] = _planning_context_sha256(
                plan_context
            )
        state_value["approvals"][args.gate] = approval
        if args.gate == "route":
            state_value["status"] = "ROUTE_APPROVED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "gate_approved",
            {
                "gate": args.gate,
                "artifact_sha256": artifact_sha,
                "approval": approval,
            },
        )
    return _result("approve", state_value, approval=approval)


def _parse_workspace_overrides(
    state_value: dict[str, Any],
    values: Sequence[str] | None,
    option: str,
    *,
    require_absolute_path: bool,
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw in values or []:
        selector, separator, supplied = raw.partition("=")
        if not separator or not selector or not supplied:
            raise FlowError(
                "INVALID_ARGUMENT",
                f"{option} must use REPOSITORY=VALUE",
                details={"value": raw},
            )
        repo = _repo_by_selector(state_value, [selector])[0]
        if repo["id"] in overrides:
            raise FlowError(
                "DUPLICATE_WORKSPACE_OVERRIDE",
                f"{option} repeats repository: {repo['id']}",
                details={"repository_id": repo["id"]},
            )
        if require_absolute_path:
            candidate = Path(supplied).expanduser()
            if not candidate.is_absolute():
                raise FlowError(
                    "INVALID_ARGUMENT",
                    f"{option} requires an absolute path",
                    details={"repository_id": repo["id"], "path": supplied},
                )
            supplied = str(candidate.resolve(strict=False))
        overrides[repo["id"]] = supplied
    return overrides


def _has_exact_workspace_claim(
    data_root: Path,
    state_value: dict[str, Any],
    repo: dict[str, Any],
    path: Path,
    branch: str,
) -> bool:
    registry = _load_workspace_registry(data_root)
    generation = int((state_value.get("workspace") or {}).get("generation", 0))
    canonical_path = str(path.resolve(strict=False))
    return any(
        isinstance(claim, dict)
        and claim.get("task_id") == state_value.get("task_id")
        and claim.get("repository_id") == repo.get("id")
        and claim.get("workspace_generation") == generation
        and claim.get("path") == canonical_path
        and claim.get("branch") == branch
        for claim in registry.get("claims", [])
    )


def _containing_git_worktree(path: Path) -> Path | None:
    ancestor = path.resolve(strict=False)
    while not ancestor.exists() and ancestor.parent != ancestor:
        ancestor = ancestor.parent
    if not ancestor.is_dir():
        return None
    root = _git_optional(ancestor, "rev-parse", "--show-toplevel")
    return Path(root).resolve(strict=False) if root else None


def _workspace_plan(
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    data_root: Path,
    branch_override: str | None,
    path_override: str | None,
    branch_overrides: dict[str, str] | None = None,
    path_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if path_override and len(selected) != 1:
        raise FlowError("INVALID_ARGUMENT", "--path can only be used when exactly one repository is selected")
    plans: list[dict[str, Any]] = []
    branch_overrides = branch_overrides or {}
    path_overrides = path_overrides or {}
    generation = int((state_value.get("workspace") or {}).get("generation", 0))
    resolved_data_root = data_root.resolve(strict=False)
    managed_generation_root = (
        resolved_data_root
        / "workspaces"
        / state_value["task_id"]
        / (f"r{generation}" if generation else "")
    ).resolve(strict=False)
    for repo in selected:
        default_branch = f"codex/{state_value['task_id']}"
        if generation:
            default_branch = f"{default_branch}-r{generation}"
        branch = branch_overrides.get(repo["id"]) or branch_override or default_branch
        protected = set(repo.get("protected_branches", DEFAULT_PROTECTED_BRANCHES))
        base_branch = (repo.get("baseline") or {}).get("base_branch")
        if branch in protected or branch == base_branch:
            raise FlowError(
                "PROTECTED_BRANCH",
                f"workspace branch is protected or is the base branch: {branch}",
                details={"repository_id": repo["id"], "branch": branch},
            )
        if (
            _run(
                ["git", "check-ref-format", "--branch", branch],
                check=False,
            ).returncode
            != 0
        ):
            raise FlowError(
                "INVALID_WORKSPACE_BRANCH",
                f"workspace branch name is invalid: {branch}",
                details={"repository_id": repo["id"], "branch": branch},
            )
        symbolic_target = _git_optional(
            Path(repo["path"]),
            "symbolic-ref",
            "--quiet",
            f"refs/heads/{branch}",
        )
        if symbolic_target:
            raise FlowError(
                "SYMBOLIC_WORKSPACE_BRANCH",
                "workspace branch refs must be direct refs, not symbolic refs",
                details={
                    "repository_id": repo["id"],
                    "branch": branch,
                    "symbolic_target": symbolic_target,
                },
            )
        explicit_path = repo["id"] in path_overrides or bool(path_override)
        managed_repository_root = (
            managed_generation_root / repo["id"]
        ).resolve(strict=False)
        if repo["id"] in path_overrides:
            path = Path(path_overrides[repo["id"]]).resolve(strict=False)
        elif path_override:
            path = Path(path_override).expanduser().resolve(strict=False)
        elif generation:
            path = data_root / "workspaces" / state_value["task_id"] / f"r{generation}" / repo["id"]
        else:
            path = data_root / "workspaces" / state_value["task_id"] / repo["id"]
        recorded = repo.get("workspace") or {}
        exact_recorded = bool(
            recorded.get("ready")
            and Path(recorded.get("path", "")).resolve(strict=False) == path
            and recorded.get("branch") == branch
            and recorded.get("workspace_generation") == generation
        )
        exact_claimed = _has_exact_workspace_claim(
            data_root, state_value, repo, path, branch
        )
        for retired in repo.get("workspace_history", []):
            retired_path_value = retired.get("path")
            retired_path = (
                Path(retired_path_value).resolve(strict=False)
                if retired_path_value
                else None
            )
            if retired_path == path or retired.get("branch") == branch:
                raise FlowError(
                    "RETIRED_WORKSPACE_REUSE",
                    "a retired workspace path or branch cannot be reused",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "branch": branch,
                        "retired_path": retired.get("path"),
                        "retired_branch": retired.get("branch"),
                    },
                )
        if _is_within(resolved_data_root, path):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace path cannot be the controller data root or one of its ancestors",
                details={"repository_id": repo["id"], "path": str(path)},
            )
        if (
            explicit_path
            and _is_within(path, resolved_data_root)
            and not _is_within(path, managed_repository_root)
        ):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace overrides inside controller data must stay in this task and generation namespace",
                details={
                    "repository_id": repo["id"],
                    "path": str(path),
                    "managed_namespace": str(managed_repository_root),
                },
            )
        for reserved in (
            (data_root / "tasks").resolve(strict=False),
            (data_root / "analysis").resolve(strict=False),
        ):
            if _is_within(path, reserved) or _is_within(reserved, path):
                raise FlowError(
                    "WORKSPACE_NOT_ISOLATED",
                    "implementation workspace must be independent from controller and analysis data",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "reserved_path": str(reserved),
                    },
                )
        for configured_repo in state_value.get("repositories", []):
            source = Path(configured_repo["path"]).resolve(strict=False)
            if _is_within(path, source) or _is_within(source, path):
                raise FlowError(
                    "WORKSPACE_NOT_ISOLATED",
                    "workspace path must be independent from every source checkout",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "source_path": str(source),
                    },
                )
            analysis = configured_repo.get("analysis_workspace") or {}
            if analysis.get("path"):
                analysis_path = Path(analysis["path"]).resolve(strict=False)
                if _is_within(path, analysis_path) or _is_within(analysis_path, path):
                    raise FlowError(
                        "WORKSPACE_NOT_ISOLATED",
                        "implementation workspace must be independent from every analysis worktree",
                        details={
                            "repository_id": repo["id"],
                            "path": str(path),
                            "analysis_path": str(analysis_path),
                        },
                    )
            for entry in _worktree_entries(Path(configured_repo["path"])):
                entry_path_value = entry.get("worktree")
                if not entry_path_value:
                    continue
                entry_path = Path(entry_path_value).resolve(strict=False)
                exact_allowed = bool(
                    entry_path == path
                    and configured_repo.get("id") == repo.get("id")
                    and (exact_recorded or exact_claimed)
                )
                if not exact_allowed and (
                    _is_within(path, entry_path) or _is_within(entry_path, path)
                ):
                    raise FlowError(
                        "WORKSPACE_NOT_ISOLATED",
                        "workspace path overlaps an existing registered Git worktree",
                        details={
                            "repository_id": repo["id"],
                            "path": str(path),
                            "existing_worktree": str(entry_path),
                        },
                    )
        containing_root = _containing_git_worktree(path)
        if containing_root and not (
            containing_root == path and (exact_recorded or exact_claimed)
        ):
            raise FlowError(
                "WORKSPACE_NOT_ISOLATED",
                "workspace path is nested in an existing Git worktree",
                details={
                    "repository_id": repo["id"],
                    "path": str(path),
                    "existing_worktree": str(containing_root),
                },
            )
        base_sha = (repo.get("baseline") or {}).get("base_sha")
        if not base_sha:
            raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
        plans.append(
            {
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "path": str(path),
                "branch": branch,
                "base_sha": base_sha,
                "strategy": "worktree",
                "owner_task_id": state_value["task_id"],
                "workspace_generation": generation,
                "previously_recorded": bool(
                    recorded.get("ready")
                    and Path(recorded.get("path", "")).resolve(strict=False) == path
                    and recorded.get("branch") == branch
                    and recorded.get("base_sha") == base_sha
                ),
            }
        )
    for index, plan in enumerate(plans):
        plan_path = Path(plan["path"])
        for other in plans[index + 1 :]:
            other_path = Path(other["path"])
            if _is_within(plan_path, other_path) or _is_within(other_path, plan_path):
                raise FlowError(
                    "WORKSPACE_PLAN_COLLISION",
                    "workspace paths for different repositories must be independent",
                    details={"path": str(plan_path), "other_path": str(other_path)},
                )
    return plans


def _workspace_plan_evidence(
    state_value: dict[str, Any], plans: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    evidence_repositories = [
        {
            "repository_id": plan["repository_id"],
            "source_path": plan["source_path"],
            "path": plan["path"],
            "branch": plan["branch"],
            "base_sha": plan["base_sha"],
            "strategy": "worktree",
        }
        for plan in plans
    ]
    evidence_repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": state_value["task_id"],
        "strategy": "worktree",
        "workspace_generation": int(
            (state_value.get("workspace") or {}).get("generation", 0)
        ),
        "repositories": evidence_repositories,
    }


def _worktree_entries(repo: Path) -> list[dict[str, str]]:
    output = _git(repo, "worktree", "list", "--porcelain", "-z", text=False)
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for field in output.split(b"\0") + [b""]:
        if not field:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = field.partition(b" ")
        current[key.decode("ascii", "replace")] = os.fsdecode(value)
    return entries


def _execute_worktree(plan: dict[str, Any]) -> dict[str, Any]:
    source = Path(plan["source_path"]).resolve(strict=True)
    _assert_evidence_supported(source)
    _assert_tree_checkout_supported(source, plan["base_sha"])
    destination = Path(plan["path"]).resolve(strict=False)
    branch = plan["branch"]
    branch_ref = f"refs/heads/{branch}"
    previously_recorded = bool(plan.get("previously_recorded"))
    entries = _worktree_entries(source)
    branch_entry = next((entry for entry in entries if entry.get("branch") == branch_ref), None)
    destination_entry = next((entry for entry in entries if Path(entry.get("worktree", "")).resolve(strict=False) == destination), None)
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        actual_branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        actual_head = _git_optional(destination, "rev-parse", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _git_common_dir(destination) == _git_common_dir(source)
                linked_worktree = _is_linked_worktree(destination)
            except (FlowError, OSError):
                same_common_dir = False
        base_is_ancestor = (
            _run(
                [
                    "git",
                    "-C",
                    str(destination),
                    "merge-base",
                    "--is-ancestor",
                    plan["base_sha"],
                    "HEAD",
                ],
                check=False,
            ).returncode
            == 0
        )
        head_is_acceptable = (
            base_is_ancestor if previously_recorded else actual_head == plan["base_sha"]
        )
        unrecorded_is_clean = previously_recorded or (
            status_available and not status_porcelain
        )
        if (
            not root
            or Path(root).resolve(strict=False) != destination
            or not same_common_dir
            or not linked_worktree
            or actual_branch != branch
            or not head_is_acceptable
            or not destination_entry
            or destination_entry.get("branch") != branch_ref
            or destination_entry.get("HEAD") != actual_head
            or not unrecorded_is_clean
        ):
            reason = (
                "unrecorded_worktree_not_clean"
                if not previously_recorded and not unrecorded_is_clean
                else "workspace_integrity_mismatch"
            )
            raise FlowError(
                "WORKSPACE_COLLISION",
                f"workspace path exists but is not the requested worktree: {destination}",
                details={
                    "path": str(destination),
                    "actual_root": root,
                    "expected_branch": branch,
                    "actual_branch": actual_branch,
                    "expected_base": plan["base_sha"],
                    "actual_head": actual_head,
                    "same_common_dir": same_common_dir,
                    "linked_worktree": linked_worktree,
                    "previously_recorded": previously_recorded,
                    "recovery_candidate_clean": unrecorded_is_clean,
                    "dirty": bool(status_porcelain),
                    "status_porcelain": status_porcelain,
                    "reason": reason,
                },
            )
        return {
            **plan,
            "ready": True,
            "created": False,
            "head_sha": actual_head,
            "recovered_unrecorded": not previously_recorded,
        }
    if destination_entry:
        raise FlowError("WORKSPACE_COLLISION", f"Git reports the workspace path but it is unavailable: {destination}", details={"path": str(destination)})
    if branch_entry:
        raise FlowError(
            "BRANCH_ALREADY_CHECKED_OUT",
            f"workspace branch is already checked out elsewhere: {branch}",
            details={"branch": branch, "path": branch_entry.get("worktree")},
        )
    symbolic_target = _git_optional(
        source, "symbolic-ref", "--quiet", branch_ref
    )
    if symbolic_target:
        raise FlowError(
            "SYMBOLIC_WORKSPACE_BRANCH",
            "workspace branch refs must be direct refs, not symbolic refs",
            details={
                "branch": branch,
                "symbolic_target": symbolic_target,
            },
        )
    _ensure_dir(destination.parent)
    if _ref_exists(source, branch_ref):
        branch_head = _git(source, "rev-parse", branch_ref)
        if previously_recorded:
            base_is_ancestor = (
                _run(
                    [
                        "git",
                        "-C",
                        str(source),
                        "merge-base",
                        "--is-ancestor",
                        plan["base_sha"],
                        branch_ref,
                    ],
                    check=False,
                ).returncode
                == 0
            )
            acceptable = base_is_ancestor
        else:
            acceptable = branch_head == plan["base_sha"]
        if not acceptable:
            raise FlowError(
                "WORKSPACE_BASE_MISMATCH",
                f"existing workspace branch is not at the approved base: {branch}",
                details={
                    "branch": branch,
                    "expected_base": plan["base_sha"],
                    "actual_head": branch_head,
                    "previously_recorded": previously_recorded,
                },
            )
        _git(
            source,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            str(destination),
            branch,
        )
    else:
        _git(
            source,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            "-b",
            branch,
            str(destination),
            plan["base_sha"],
        )
    actual_root = _git_optional(destination, "rev-parse", "--show-toplevel")
    actual_branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
    actual_head = _git_optional(destination, "rev-parse", "HEAD")
    status_available, status_porcelain = _status_porcelain(destination)
    created_entry = next(
        (
            entry
            for entry in _worktree_entries(source)
            if Path(entry.get("worktree", "")).resolve(strict=False) == destination
        ),
        None,
    )
    if (
        not actual_root
        or Path(actual_root).resolve(strict=False) != destination
        or actual_branch != branch
        or actual_head != plan["base_sha"]
        or _git_common_dir(destination) != _git_common_dir(source)
        or not _is_linked_worktree(destination)
        or not status_available
        or bool(status_porcelain)
        or not created_entry
        or created_entry.get("branch") != branch_ref
        or created_entry.get("HEAD") != actual_head
    ):
        raise FlowError(
            "WORKSPACE_VERIFY_FAILED",
            f"created worktree failed branch, ownership or cleanliness verification: {destination}",
            details={
                "expected_branch": branch,
                "actual_branch": actual_branch,
                "expected_head": plan["base_sha"],
                "actual_head": actual_head,
                "dirty": bool(status_porcelain),
                "status_porcelain": status_porcelain,
            },
        )
    return {**plan, "ready": True, "created": True, "head_sha": actual_head}


def _workspace_claim_integrity_error(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> str | None:
    workspace = repo.get("workspace") or {}
    receipt = workspace.get("workspace_claim") or {}
    registry_path_value = receipt.get("registry_path")
    claim_id = receipt.get("claim_id")
    if not registry_path_value or not claim_id:
        return f"workspace has no durable ownership claim: {repo.get('id')}"
    registry_path = Path(registry_path_value)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"workspace ownership registry cannot be read: {repo.get('id')}: {exc}"
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != SCHEMA_VERSION
        or not isinstance(registry.get("claims"), list)
    ):
        return f"workspace ownership registry has an invalid structure: {repo.get('id')}"
    claim = next(
        (
            item
            for item in registry.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    expected_plan_sha = ((state_value.get("workspace") or {}).get("plan") or {}).get(
        "sha256"
    )
    expected_source = str(Path(repo.get("path", "")).resolve(strict=False))
    expected_common_dir = _source_common_dir_for_claim(repo.get("path"))
    if (
        not claim
        or claim.get("task_id") != state_value.get("task_id")
        or claim.get("repository_id") != repo.get("id")
        or claim.get("source_path") != expected_source
        or claim.get("source_common_dir") != expected_common_dir
        or claim.get("path")
        != str(Path(workspace.get("path", "")).resolve(strict=False))
        or claim.get("branch") != workspace.get("branch")
        or claim.get("workspace_generation")
        != int((state_value.get("workspace") or {}).get("generation", 0))
        or claim.get("plan_sha256") != expected_plan_sha
        or receipt.get("plan_sha256") != expected_plan_sha
    ):
        return f"workspace durable ownership claim is stale or mismatched: {repo.get('id')}"
    return None


def _workspace_integrity_error(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> str | None:
    workspace = repo.get("workspace") or {}
    if not workspace.get("ready"):
        return f"workspace is not ready: {repo.get('id')}"
    if workspace.get("owner_task_id") != state_value.get("task_id"):
        return f"workspace ownership does not match task: {repo.get('id')}"
    if workspace.get("workspace_generation") != int(
        (state_value.get("workspace") or {}).get("generation", 0)
    ):
        return f"workspace generation does not match task: {repo.get('id')}"
    claim_error = _workspace_claim_integrity_error(state_value, repo)
    if claim_error:
        return claim_error
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(workspace.get("path", "")).resolve(strict=False)
    for configured_repo in state_value.get("repositories", []):
        configured_source = Path(configured_repo["path"]).resolve(strict=False)
        if _is_within(path, configured_source) or _is_within(configured_source, path):
            return f"workspace is not independent from source checkout: {repo.get('id')}"
        analysis = configured_repo.get("analysis_workspace") or {}
        if analysis.get("path"):
            analysis_path = Path(analysis["path"]).resolve(strict=False)
            if _is_within(path, analysis_path) or _is_within(analysis_path, path):
                return f"workspace is not independent from analysis worktree: {repo.get('id')}"
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    if not root or Path(root).resolve(strict=False) != path:
        return f"workspace path is not a Git worktree root: {repo.get('id')}"
    try:
        if _git_common_dir(path) != _git_common_dir(source):
            return f"workspace belongs to a different Git repository: {repo.get('id')}"
        if not _is_linked_worktree(path):
            return f"workspace is not a linked worktree: {repo.get('id')}"
    except (FlowError, OSError) as exc:
        return f"workspace Git ownership cannot be verified: {repo.get('id')}: {exc}"
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != workspace.get("branch"):
        return f"workspace branch changed: {repo.get('id')}"
    head = _git_optional(path, "rev-parse", "HEAD")
    base_sha = workspace.get("base_sha")
    if not head or not base_sha:
        return f"workspace HEAD/base metadata is incomplete: {repo.get('id')}"
    if (
        _run(
            ["git", "-C", str(path), "merge-base", "--is-ancestor", base_sha, "HEAD"],
            check=False,
        ).returncode
        != 0
    ):
        return f"workspace HEAD no longer descends from approved base: {repo.get('id')}"
    expected_ref = f"refs/heads/{workspace.get('branch')}"
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if Path(item.get("worktree", "")).resolve(strict=False) == path
        ),
        None,
    )
    if (
        not entry
        or entry.get("branch") != expected_ref
        or entry.get("HEAD") != head
    ):
        return f"workspace is not registered as the approved linked worktree: {repo.get('id')}"
    return None


def _require_workspace_ready(state_value: dict[str, Any]) -> dict[str, Any]:
    approval, artifact = _require_gate_for_latest_artifact(
        state_value, "workspace", "workspace-plan"
    )
    current_generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    if (
        approval.get("artifact_id") != artifact.get("artifact_id")
        or approval.get("workspace_generation") != current_generation
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "workspace approval is not bound to the current plan record and generation",
        )
    repositories = state_value.get("repositories", [])
    required_ids = {repo["id"] for repo in repositories}
    try:
        evidence = json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_PLAN_INVALID",
            "approved workspace plan cannot be parsed",
            details={"path": artifact.get("path"), "error": str(exc)},
        ) from exc
    evidence_repositories = evidence.get("repositories", []) if isinstance(evidence, dict) else []
    evidence_ids = [item.get("repository_id") for item in evidence_repositories]
    if (
        evidence.get("task_id") != state_value.get("task_id")
        or evidence.get("workspace_generation")
        != int((state_value.get("workspace") or {}).get("generation", 0))
        or len(evidence_ids) != len(required_ids)
        or set(evidence_ids) != required_ids
    ):
        raise FlowError(
            "INCOMPLETE_WORKSPACE_PLAN",
            "approved workspace plan does not cover exactly every task repository",
            details={
                "required_repository_ids": sorted(required_ids),
                "planned_repository_ids": sorted(str(item) for item in evidence_ids),
            },
        )
    plans: list[dict[str, Any]] = []
    for repo in repositories:
        workspace = repo.get("workspace") or {}
        if not workspace.get("ready"):
            raise FlowError(
                "WORKSPACE_REQUIRED",
                f"repository has no ready workspace: {repo['id']}",
            )
        plans.append(
            {
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "path": workspace.get("path"),
                "branch": workspace.get("branch"),
                "base_sha": workspace.get("base_sha"),
                "strategy": "worktree",
            }
        )
    current_evidence = _workspace_plan_evidence(state_value, plans)
    current_sha = _sha256_bytes(_json_bytes(current_evidence))
    if current_sha != artifact.get("sha256") or current_evidence != evidence:
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "ready workspaces no longer match the approved all-repository plan",
            details={
                "approved_sha256": artifact.get("sha256"),
                "current_sha256": current_sha,
            },
        )
    controller_workspace = state_value.get("workspace") or {}
    controller_plan = controller_workspace.get("plan") or {}
    if (
        not controller_workspace.get("ready")
        or controller_plan.get("artifact_id") != artifact.get("artifact_id")
        or controller_plan.get("path") != artifact.get("path")
        or controller_plan.get("sha256") != artifact.get("sha256")
        or controller_plan.get("workspace_generation")
        != int(controller_workspace.get("generation", 0))
    ):
        raise FlowError(
            "WORKSPACE_REQUIRED",
            "controller workspace readiness is not bound to the approved plan",
        )
    for repo in repositories:
        error = _workspace_integrity_error(state_value, repo)
        if error:
            raise FlowError(
                "WORKSPACE_INTEGRITY_FAILED",
                error,
                details={"repository_id": repo["id"]},
            )
    return approval


def _workspace_index_staleness(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    index: dict[str, Any],
) -> dict[str, Any] | None:
    repository_id = repo.get("id")
    if index.get("role") != "workspace" or not index.get("index_id"):
        return {
            "repository_id": repository_id,
            "reason": "workspace index role or project id is invalid",
        }
    if (index.get("metadata") or {}).get("persistence") is not False:
        return {
            "repository_id": repository_id,
            "reason": "workspace index does not explicitly disable persistence",
        }
    receipt = index.get("receipt")
    if receipt is not None:
        if not isinstance(receipt, dict) or not receipt.get("path"):
            return {
                "repository_id": repository_id,
                "reason": "workspace index receipt metadata is incomplete",
            }
        receipt_path = Path(str(receipt["path"]))
        try:
            actual_sha = (
                _sha256_file(receipt_path) if receipt_path.is_file() else None
            )
            actual_size = (
                receipt_path.stat().st_size if receipt_path.is_file() else None
            )
        except OSError:
            actual_sha = None
            actual_size = None
        if (
            actual_sha != receipt.get("sha256")
            or actual_size != receipt.get("size")
        ):
            return {
                "repository_id": repository_id,
                "reason": "workspace index receipt is missing or changed",
                "receipt_path": str(receipt_path),
                "expected_receipt_sha256": receipt.get("sha256"),
                "actual_receipt_sha256": actual_sha,
            }

    integrity_error = _workspace_integrity_error(state_value, repo)
    if integrity_error:
        return {
            "repository_id": repository_id,
            "reason": integrity_error,
        }
    workspace = repo.get("workspace") or {}
    workspace_path_value = workspace.get("path")
    recorded_path_value = index.get("repo_path")
    if not workspace_path_value or not recorded_path_value:
        return {
            "repository_id": repository_id,
            "reason": "workspace index path binding is incomplete",
        }
    workspace_path = Path(workspace_path_value).resolve(strict=False)
    recorded_path = Path(recorded_path_value).resolve(strict=False)
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    plan_sha = (
        (state_value.get("workspace") or {}).get("plan") or {}
    ).get("sha256")
    actual_branch = _git_optional(
        workspace_path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    actual_head = _git_optional(workspace_path, "rev-parse", "HEAD")
    bindings = {
        "path": (str(recorded_path), str(workspace_path)),
        "workspace_generation": (
            index.get("workspace_generation"),
            generation,
        ),
        "workspace_plan_sha256": (
            index.get("workspace_plan_sha256"),
            plan_sha,
        ),
        "workspace_branch": (
            index.get("workspace_branch"),
            actual_branch,
        ),
        "commit_sha": (index.get("commit_sha"), actual_head),
        "workspace_head_sha": (
            index.get("workspace_head_sha"),
            actual_head,
        ),
    }
    mismatches = {
        name: {"recorded": recorded, "current": current}
        for name, (recorded, current) in bindings.items()
        if recorded != current
    }
    if mismatches:
        return {
            "repository_id": repository_id,
            "reason": "workspace identity, generation, branch or HEAD changed",
            "mismatches": mismatches,
        }
    try:
        current_fingerprint = _fingerprint_repo(workspace_path)["sha256"]
    except (FlowError, OSError) as exc:
        return {
            "repository_id": repository_id,
            "reason": f"workspace fingerprint cannot be verified: {exc}",
        }
    if current_fingerprint != index.get("fingerprint_sha256"):
        return {
            "repository_id": repository_id,
            "reason": "workspace content changed after indexing",
            "recorded_fingerprint_sha256": index.get("fingerprint_sha256"),
            "current_fingerprint_sha256": current_fingerprint,
        }
    return None


def _require_current_workspace_indexes(
    state_value: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    missing = [
        repo.get("id")
        for repo in state_value.get("repositories", [])
        if not isinstance(repo.get("workspace_index"), dict)
        or not (repo.get("workspace_index") or {}).get("index_id")
    ]
    if missing:
        raise FlowError(
            "WORKSPACE_INDEX_REQUIRED",
            "every repository requires a recorded workspace index for the current implementation worktree",
            details={
                "repository_ids": missing,
                "selected_role": "workspace",
            },
        )
    stale: list[dict[str, Any]] = []
    records: dict[str, dict[str, Any]] = {}
    for repo in state_value.get("repositories", []):
        index = repo["workspace_index"]
        records[repo["id"]] = index
        error = _workspace_index_staleness(state_value, repo, index)
        if error:
            stale.append(error)
    if stale:
        raise FlowError(
            "STALE_WORKSPACE_INDEX",
            "one or more workspace indexes no longer describe the current implementation worktree",
            details={"repositories": stale, "selected_role": "workspace"},
        )
    return records


def _current_planning_context(state_value: dict[str, Any]) -> dict[str, Any]:
    route_approval, impact = _require_route_gate(state_value)
    workspace_approval = _require_workspace_ready(state_value)
    workspace_plan = _latest_artifact(state_value, "workspace-plan")
    if not workspace_plan:
        raise FlowError("WORKSPACE_REQUIRED", "a current workspace plan is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": state_value["task_id"],
        "planning_generation": int(state_value.get("planning_generation", 0)),
        "impact_generation": int(state_value.get("impact_generation", 0)),
        "route": {
            "value": (state_value.get("route") or {}).get("value"),
            "approval_id": route_approval.get("approval_id"),
            "impact_artifact_id": impact.get("artifact_id"),
            "impact_sha256": impact.get("sha256"),
        },
        "workspace": {
            "generation": int(
                (state_value.get("workspace") or {}).get("generation", 0)
            ),
            "approval_id": workspace_approval.get("approval_id"),
            "plan_artifact_id": workspace_plan.get("artifact_id"),
            "plan_sha256": workspace_plan.get("sha256"),
        },
    }


def _planning_context_sha256(context: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(context))


def _assert_openspec_plan_in_current_workspace(
    state_value: dict[str, Any], artifact_path: Path
) -> None:
    resolved = artifact_path.resolve(strict=True)
    if not any(
        (repo.get("workspace") or {}).get("ready")
        and _is_within(
            resolved,
            Path((repo.get("workspace") or {})["path"]).resolve(strict=True),
        )
        for repo in state_value.get("repositories", [])
    ):
        raise FlowError(
            "OPENSPEC_PLAN_OUTSIDE_WORKSPACE",
            "openspec-plan must be recorded from a current ready implementation workspace",
            details={"path": str(resolved)},
        )


def _require_current_plan_artifact(
    state_value: dict[str, Any], artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = _latest_artifact(state_value, artifact_kind)
    if not artifact:
        raise FlowError(
            "ARTIFACT_REQUIRED",
            f"the plan gate requires a recorded {artifact_kind} artifact",
        )
    _assert_artifact_unchanged(artifact)
    if artifact_kind == "openspec-plan":
        _assert_openspec_plan_in_current_workspace(
            state_value, Path(artifact["path"])
        )
    expected_context = _current_planning_context(state_value)
    metadata = artifact.get("metadata") or {}
    recorded_context = metadata.get("planning_context")
    recorded_context_sha = metadata.get("planning_context_sha256")
    expected_context_sha = _planning_context_sha256(expected_context)
    if (
        recorded_context != expected_context
        or recorded_context_sha != expected_context_sha
    ):
        raise FlowError(
            "STALE_PLAN",
            "latest plan artifact is not bound to the current planning epoch, route and workspace",
            details={
                "artifact_id": artifact.get("artifact_id"),
                "expected_planning_context_sha256": expected_context_sha,
                "recorded_planning_context_sha256": recorded_context_sha,
            },
        )
    return artifact, expected_context


def _require_current_plan_gate(
    state_value: dict[str, Any], artifact_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact, context = _require_current_plan_artifact(state_value, artifact_kind)
    approval = _require_gate(state_value, "plan")
    context_sha = _planning_context_sha256(context)
    if (
        approval.get("artifact_sha256") != artifact.get("sha256")
        or approval.get("artifact_id") != artifact.get("artifact_id")
        or approval.get("planning_context_sha256") != context_sha
    ):
        raise FlowError(
            "STALE_APPROVAL",
            "plan approval is not bound to the current plan record and planning context",
        )
    return approval, artifact


def command_prepare_workspace(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    data_root = resolve_data_dir(args.data_dir)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "prepare-workspace")
        _assert_status(current, {"ROUTE_APPROVED", "WORKSPACE_READY"}, "prepare-workspace")
        selected_current = _repo_by_selector(current, args.repo)
        configured_ids = {repo["id"] for repo in current.get("repositories", [])}
        selected_ids = {repo["id"] for repo in selected_current}
        if selected_ids != configured_ids:
            raise FlowError(
                "INCOMPLETE_WORKSPACE_PLAN",
                "workspace plans must cover every repository in the task",
                details={
                    "required_repository_ids": sorted(configured_ids),
                    "selected_repository_ids": sorted(selected_ids),
                },
            )
        _require_route_gate(current)
        path_overrides = _parse_workspace_overrides(
            current,
            args.workspace_path,
            "--workspace-path",
            require_absolute_path=True,
        )
        branch_overrides = _parse_workspace_overrides(
            current,
            args.workspace_branch,
            "--workspace-branch",
            require_absolute_path=False,
        )
        if args.path and path_overrides:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--path cannot be combined with --workspace-path",
            )
        plans = _workspace_plan(
            current,
            selected_current,
            data_root,
            args.branch,
            args.path,
            branch_overrides,
            path_overrides,
        )
        evidence = _workspace_plan_evidence(current, plans)
        evidence_bytes = _json_bytes(evidence)
        evidence_sha = _sha256_bytes(evidence_bytes)
        if current.get("status") == "WORKSPACE_READY":
            ready_plan = (current.get("workspace") or {}).get("plan") or {}
            if ready_plan.get("sha256") != evidence_sha:
                raise FlowError(
                    "WORKSPACE_REASSESSMENT_REQUIRED",
                    "a ready workspace cannot be replaced within the same generation",
                    details={
                        "workspace_generation": evidence["workspace_generation"],
                        "ready_plan_sha256": ready_plan.get("sha256"),
                        "requested_plan_sha256": evidence_sha,
                    },
                )
        if not args.execute:
            _claim_workspace_plan(data_root, current, evidence_sha, plans)
            plan_path = task_dir / "workspace-plans" / f"{evidence_sha}.json"
            latest_plan = _latest_artifact(current, "workspace-plan")
            current_workspace_plan = (current.get("workspace") or {}).get("plan") or {}
            if (
                latest_plan
                and latest_plan.get("sha256") == evidence_sha
                and current_workspace_plan.get("sha256") == evidence_sha
                and current_workspace_plan.get("artifact_id")
                == latest_plan.get("artifact_id")
                and current_workspace_plan.get("path")
                == latest_plan.get("path")
                and current_workspace_plan.get("workspace_generation")
                == evidence["workspace_generation"]
                and (latest_plan.get("metadata") or {}).get(
                    "workspace_generation"
                )
                == evidence["workspace_generation"]
            ):
                try:
                    _assert_artifact_unchanged(latest_plan)
                except FlowError:
                    _atomic_write_bytes(plan_path, evidence_bytes)
                else:
                    return _result(
                        "prepare-workspace",
                        current,
                        dry_run=True,
                        unchanged=True,
                        plans=plans,
                        plan_artifact=latest_plan,
                    )
            _atomic_write_bytes(plan_path, evidence_bytes)
            state_value = _copy_state(current)
            plan_artifact = {
                "artifact_id": str(uuid.uuid4()),
                "kind": "workspace-plan",
                "path": str(plan_path),
                "sha256": evidence_sha,
                "artifact_type": "file",
                "size": len(evidence_bytes),
                "file_count": 1,
                "total_size": len(evidence_bytes),
                "recorded_at": utc_now(),
                "metadata": {
                    "repository_ids": [item["repository_id"] for item in evidence["repositories"]],
                    "workspace_generation": evidence["workspace_generation"],
                },
            }
            state_value["artifacts"].append(plan_artifact)
            workspace_state = dict(state_value.get("workspace") or {})
            workspace_state["strategy"] = "worktree"
            workspace_state["plan"] = {
                "artifact_id": plan_artifact["artifact_id"],
                "sha256": evidence_sha,
                "path": str(plan_path),
                "repository_ids": plan_artifact["metadata"]["repository_ids"],
                "recorded_at": plan_artifact["recorded_at"],
                "workspace_generation": evidence["workspace_generation"],
            }
            state_value["workspace"] = workspace_state
            state_value["approvals"].pop("workspace", None)
            _commit_state(
                current,
                state_value,
                task_dir,
                "workspace_plan_recorded",
                {
                    "sha256": evidence_sha,
                    "repository_ids": plan_artifact["metadata"]["repository_ids"],
                },
            )
            return _result(
                "prepare-workspace",
                state_value,
                dry_run=True,
                plans=plans,
                plan_artifact=plan_artifact,
            )
        workspace_approval, approved_plan = _require_gate_for_latest_artifact(
            current, "workspace", "workspace-plan"
        )
        controller_plan = (current.get("workspace") or {}).get("plan") or {}
        if (
            workspace_approval.get("artifact_id")
            != approved_plan.get("artifact_id")
            or controller_plan.get("artifact_id")
            != approved_plan.get("artifact_id")
            or controller_plan.get("path") != approved_plan.get("path")
            or controller_plan.get("sha256") != approved_plan.get("sha256")
        ):
            raise FlowError(
                "STALE_WORKSPACE_PLAN",
                "workspace approval and controller state are not bound to the latest plan record",
            )
        if evidence_sha != approved_plan.get("sha256"):
            raise FlowError(
                "WORKSPACE_PLAN_MISMATCH",
                "execute arguments do not match the approved workspace plan",
                details={
                    "approved_sha256": approved_plan.get("sha256"),
                    "requested_sha256": evidence_sha,
                    "approved_path": approved_plan.get("path"),
                },
            )
        approved_generation = (approved_plan.get("metadata") or {}).get(
            "workspace_generation"
        )
        if approved_generation != evidence["workspace_generation"]:
            raise FlowError(
                "WORKSPACE_PLAN_MISMATCH",
                "approved workspace plan belongs to a different workspace generation",
                details={
                    "approved_workspace_generation": approved_generation,
                    "current_workspace_generation": evidence["workspace_generation"],
                },
            )
        _claim_workspace_plan(data_root, current, evidence_sha, plans)
        state_value = _copy_state(current)
        by_id = {repo["id"]: repo for repo in state_value["repositories"]}
        source_fingerprints = {
            repo["id"]: _fingerprint_repo(Path(repo["path"]))["sha256"]
            for repo in state_value["repositories"]
        }
        outcomes: list[dict[str, Any]] = []
        for plan in plans:
            outcome = _execute_worktree(plan)
            outcomes.append(outcome)
            repository = by_id[plan["repository_id"]]
            previous_workspace = repository.get("workspace") or {}
            same_workspace = (
                previous_workspace.get("ready")
                and previous_workspace.get("path") == outcome.get("path")
                and previous_workspace.get("branch") == outcome.get("branch")
                and previous_workspace.get("workspace_generation")
                == outcome.get("workspace_generation")
            )
            if not same_workspace:
                repository["workspace_index"] = None
            repository["workspace"] = outcome
        for outcome in outcomes:
            if not (
                outcome.get("created") or outcome.get("recovered_unrecorded")
            ):
                continue
            status_available, status_porcelain = _status_porcelain(
                Path(outcome["path"])
            )
            if not status_available or status_porcelain:
                raise FlowError(
                    "WORKSPACE_VERIFY_FAILED",
                    "a newly prepared workspace changed before atomic state commit",
                    details={
                        "repository_id": outcome["repository_id"],
                        "path": outcome["path"],
                        "status_porcelain": status_porcelain,
                    },
                )
        for repo in state_value["repositories"]:
            current_source = _fingerprint_repo(Path(repo["path"]))["sha256"]
            if current_source != source_fingerprints[repo["id"]]:
                raise FlowError(
                    "SOURCE_WORKTREE_CHANGED",
                    "source checkout changed while preparing implementation workspaces",
                    details={"repository_id": repo["id"]},
                )
        all_ready = all((repo.get("workspace") or {}).get("ready") for repo in state_value["repositories"])
        workspace_state = dict(state_value.get("workspace") or {})
        workspace_state.update(
            {
                "strategy": "worktree",
                "ready": all_ready,
                "prepared_at": utc_now() if all_ready else None,
            }
        )
        state_value["workspace"] = workspace_state
        if all_ready:
            _require_workspace_ready(state_value)
            state_value["status"] = "WORKSPACE_READY"
        _commit_state(current, state_value, task_dir, "workspace_prepared", {"repository_ids": [item["repository_id"] for item in outcomes], "complete": all_ready})
    return _result("prepare-workspace", state_value, dry_run=False, complete=all_ready, workspaces=outcomes)


def _test_identity(name: Any, command: Any) -> str:
    return _sha256_bytes(
        _json_bytes({"name": str(name or ""), "command": str(command or "")})
    )


def command_record_test(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    output_record: dict[str, Any] | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve(strict=True)
        output_record = {"path": str(output_path), "sha256": _sha256_file(output_path), "size": output_path.stat().st_size}
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_status(current, {"IMPLEMENTING", "VERIFYING"}, "record-test")
        if _flow(current) == "lite":
            # Lite tests bind the lite approval instead of a plan artifact:
            # re-approving the gate invalidates older results the same way a
            # plan reapproval does on the full flow.
            lite_approval = _require_lite_gate(current)
            binding = {
                "lite_approval_id": lite_approval["approval_id"],
                "lite_approved_at": lite_approval["approved_at"],
            }
        else:
            _require_workspace_ready(current)
            route_value = (current.get("route") or {}).get("value")
            plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
            plan_approval, plan_artifact = _require_current_plan_gate(
                current, plan_kind
            )
            binding = {
                "plan_artifact_sha256": plan_artifact["sha256"],
                "plan_approved_at": plan_approval["approved_at"],
                "plan_approval_id": plan_approval["approval_id"],
            }
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        fingerprints = {repo["id"]: _fingerprint_repo(_working_path(repo)) for repo in selected}
        test_record = {
            "test_id": str(uuid.uuid4()),
            "name": args.name,
            "command": args.test_command,
            "test_identity": _test_identity(args.name, args.test_command),
            "exit_code": args.exit_code,
            "passed": args.exit_code == 0,
            "recorded_at": utc_now(),
            "repository_ids": [repo["id"] for repo in selected],
            "fingerprints": fingerprints,
            **binding,
            "output": output_record,
        }
        state_value["tests"].append(test_record)
        _commit_state(current, state_value, task_dir, "test_recorded", {"test_id": test_record["test_id"], "passed": test_record["passed"], "repository_ids": test_record["repository_ids"]})
    return _result("record-test", state_value, test=test_record)


def _write_review_repo(snapshot_root: Path, repo: dict[str, Any]) -> dict[str, Any]:
    working = _working_path(repo)
    _assert_evidence_supported(working)
    base_sha = (repo.get("baseline") or {}).get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
    repo_dir = snapshot_root / repo["id"]
    _ensure_dir(repo_dir)
    head_sha = _git_evidence(working, "rev-parse", "HEAD")
    sections = {
        "committed": _git_diff(
            working,
            "--binary",
            "--full-index",
            f"{base_sha}...HEAD",
            "--",
            text=False,
        ),
        "cached": _git_diff(
            working, "--binary", "--full-index", "--cached", "--", text=False
        ),
        "unstaged": _git_diff(
            working, "--binary", "--full-index", "--", text=False
        ),
    }
    section_records: dict[str, Any] = {}
    for name, content in sections.items():
        path = repo_dir / f"{name}.patch"
        _atomic_write_bytes(path, content)
        if name == "committed":
            name_status = _git_diff(
                working, "--name-status", f"{base_sha}...HEAD", "--"
            )
        elif name == "cached":
            name_status = _git_diff(working, "--cached", "--name-status", "--")
        else:
            name_status = _git_diff(working, "--name-status", "--")
        section_records[name] = {
            "path": str(path),
            "sha256": _sha256_bytes(content),
            "size": len(content),
            "files": _split_lines(name_status),
            "range": f"{base_sha}...{head_sha}" if name == "committed" else None,
        }
    fingerprint = _fingerprint_repo(working)
    untracked_manifest_path = repo_dir / "untracked.json"
    _atomic_write_json(untracked_manifest_path, fingerprint["untracked"])
    tar_path = repo_dir / "untracked.tar"
    with tarfile.open(tar_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for item in fingerprint["untracked"]:
            relative = _untracked_filesystem_path(item)
            archive.add(working / relative, arcname=relative, recursive=False)
    try:
        tar_path.chmod(0o600)
    except OSError:
        pass
    section_records["untracked"] = {
        "manifest_path": str(untracked_manifest_path),
        "manifest_sha256": _sha256_file(untracked_manifest_path),
        "archive_path": str(tar_path),
        "archive_sha256": _sha256_file(tar_path),
        "size": tar_path.stat().st_size,
        "files": fingerprint["untracked"],
    }
    return {
        "repository_id": repo["id"],
        "working_path": str(working),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "fingerprint": fingerprint,
        "sections": section_records,
    }


def _latest_passing_test_is_current(state_value: dict[str, Any]) -> tuple[bool, str | None]:
    """Require each repo's newest relevant test record to pass and remain current."""

    if _flow(state_value) == "lite":
        lite_approval = _require_lite_gate(state_value)

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return test.get("lite_approval_id") == lite_approval.get(
                "approval_id"
            ) and str(test.get("recorded_at", "")) >= str(
                lite_approval.get("approved_at", "")
            )

        missing_message = "no test result for the current lite approval covers repository"
    else:
        route_value = (state_value.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        plan_approval, plan_artifact = _require_current_plan_gate(
            state_value, plan_kind
        )

        def _bound_to_current_approval(test: dict[str, Any]) -> bool:
            return (
                test.get("plan_artifact_sha256") == plan_artifact.get("sha256")
                and test.get("plan_approval_id")
                == plan_approval.get("approval_id")
                and str(test.get("recorded_at", ""))
                >= str(plan_approval.get("approved_at", ""))
            )

        missing_message = "no test result for the current plan approval covers repository"
    tests = state_value.get("tests", [])
    for repo in state_value["repositories"]:
        latest_by_identity: dict[str, dict[str, Any]] = {}
        for test in tests:
            if repo["id"] not in test.get("repository_ids", []):
                continue
            if not _bound_to_current_approval(test):
                continue
            identity = test.get("test_identity") or _test_identity(
                test.get("name"), test.get("command")
            )
            latest_by_identity[identity] = test
        if not latest_by_identity:
            return (
                False,
                f"{missing_message}: {repo['id']}",
            )
        current = _fingerprint_repo(_working_path(repo))
        for latest in latest_by_identity.values():
            label = latest.get("name") or latest.get("test_identity") or "unnamed"
            if not latest.get("passed"):
                return (
                    False,
                    f"latest result for test identity {label!r} failed for repository: {repo['id']}",
                )
            output = latest.get("output")
            if output is not None:
                output_path = Path(str((output or {}).get("path", "")))
                try:
                    output_sha = (
                        _sha256_file(output_path)
                        if output_path.is_file()
                        else None
                    )
                    output_size = (
                        output_path.stat().st_size
                        if output_path.is_file()
                        else None
                    )
                except OSError:
                    output_sha = None
                    output_size = None
                if (
                    output_sha != (output or {}).get("sha256")
                    or output_size != (output or {}).get("size")
                ):
                    return (
                        False,
                        f"test output for identity {label!r} is missing or changed: {output_path}",
                    )
            recorded = latest.get("fingerprints", {}).get(repo["id"], {})
            if current.get("sha256") != recorded.get("sha256"):
                return (
                    False,
                    f"repository changed after test identity {label!r} passed: {repo['id']}",
                )
    return True, None


def command_review_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        _assert_flow(current, "full", "review-snapshot")
        _assert_status(current, {"VERIFYING", "REVIEWING"}, "review-snapshot")
        _require_current_workspace_indexes(current)
        _require_workspace_ready(current)
        route_value = (current.get("route") or {}).get("value")
        plan_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(current, plan_kind)
        passing, reason = _latest_passing_test_is_current(current)
        if not passing:
            raise FlowError("CURRENT_TEST_REQUIRED", reason or "a current passing test is required")
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        if len(selected) != len(state_value["repositories"]):
            raise FlowError("INCOMPLETE_REVIEW", "review-snapshot must include every configured repository")
        snapshot_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        snapshot_root = task_dir / "reviews" / snapshot_id
        repositories = [_write_review_repo(snapshot_root, repo) for repo in selected]
        snapshot = {
            "snapshot_id": snapshot_id,
            "created_at": utc_now(),
            "repository_ids": [repo["id"] for repo in selected],
            "repositories": repositories,
        }
        manifest_path = snapshot_root / "manifest.json"
        _atomic_write_json(manifest_path, snapshot)
        snapshot["manifest_path"] = str(manifest_path)
        snapshot["sha256"] = _sha256_file(manifest_path)
        state_value["review_snapshots"].append(snapshot)
        state_value["artifacts"].append(
            {
                "artifact_id": str(uuid.uuid4()),
                "kind": "review-snapshot",
                "path": str(manifest_path),
                "sha256": snapshot["sha256"],
                "size": manifest_path.stat().st_size,
                "recorded_at": utc_now(),
                "metadata": {"snapshot_id": snapshot_id},
            }
        )
        state_value["status"] = "REVIEWING"
        _commit_state(current, state_value, task_dir, "review_snapshot_recorded", {"snapshot_id": snapshot_id, "sha256": snapshot["sha256"], "repository_ids": snapshot["repository_ids"]})
    return _result("review-snapshot", state_value, snapshot=snapshot)


def _snapshot_file_error(path_value: Any, expected_sha: Any, label: str) -> str | None:
    if not isinstance(path_value, str) or not path_value or not isinstance(expected_sha, str):
        return f"review snapshot has incomplete {label} integrity metadata"
    path = Path(path_value)
    if not path.is_file():
        return f"review snapshot {label} file is missing: {path}"
    try:
        current_sha = _sha256_file(path)
    except OSError as exc:
        return f"review snapshot {label} file is unreadable: {path}: {exc}"
    if current_sha != expected_sha:
        return f"review snapshot {label} file changed: {path}"
    return None


def _review_snapshot_integrity_error(snapshot: dict[str, Any]) -> str | None:
    error = _snapshot_file_error(
        snapshot.get("manifest_path"), snapshot.get("sha256"), "manifest"
    )
    if error:
        return error
    for repository in snapshot.get("repositories", []):
        repository_id = repository.get("repository_id", "unknown")
        sections = repository.get("sections") or {}
        for section_name in ("committed", "cached", "unstaged"):
            section = sections.get(section_name) or {}
            error = _snapshot_file_error(
                section.get("path"),
                section.get("sha256"),
                f"{repository_id}/{section_name}",
            )
            if error:
                return error
        untracked = sections.get("untracked") or {}
        error = _snapshot_file_error(
            untracked.get("manifest_path"),
            untracked.get("manifest_sha256"),
            f"{repository_id}/untracked-manifest",
        )
        if error:
            return error
        error = _snapshot_file_error(
            untracked.get("archive_path"),
            untracked.get("archive_sha256"),
            f"{repository_id}/untracked-archive",
        )
        if error:
            return error
    return None


def _review_is_current(state_value: dict[str, Any]) -> tuple[bool, str | None]:
    snapshots = state_value.get("review_snapshots", [])
    if not snapshots:
        return False, "no review snapshot has been recorded"
    latest = snapshots[-1]
    integrity_error = _review_snapshot_integrity_error(latest)
    if integrity_error:
        return False, integrity_error
    by_id = {item["repository_id"]: item for item in latest.get("repositories", [])}
    for repo in state_value["repositories"]:
        workspace_error = _workspace_integrity_error(state_value, repo)
        if workspace_error:
            return False, workspace_error
        recorded = by_id.get(repo["id"])
        if not recorded:
            return False, f"review snapshot does not cover repository: {repo['id']}"
        current = _fingerprint_repo(_working_path(repo))
        if current.get("sha256") != (recorded.get("fingerprint") or {}).get("sha256"):
            return False, f"repository changed after review snapshot: {repo['id']}"
    return True, None


def _lite_transition_guard(state_value: dict[str, Any], target: str) -> None:
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED" and not all((repo.get("preflight") or {}).get("ready") for repo in repositories):
        raise FlowError("PREFLIGHT_REQUIRED", "all repositories must pass preflight")
    if target == "IMPLEMENTING":
        # Entering implementation from PREFLIGHTED must find the exact approved
        # checkouts untouched; re-entering from rework legitimately finds the
        # tree already edited, so only branch identity is revalidated there.
        _require_lite_gate(
            state_value,
            verify_worktree=state_value.get("status") == "PREFLIGHTED",
        )
    if target in {"VERIFYING", "DONE"}:
        _require_lite_gate(state_value)
    if target == "DONE":
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")


def _transition_guard(state_value: dict[str, Any], target: str) -> None:
    if _flow(state_value) == "lite":
        _lite_transition_guard(state_value, target)
        return
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED" and not all((repo.get("preflight") or {}).get("ready") for repo in repositories):
        raise FlowError("PREFLIGHT_REQUIRED", "all repositories must pass preflight")
    if target == "BASELINED" and not all(repo.get("baseline") for repo in repositories):
        raise FlowError("BASELINE_REQUIRED", "all repositories must have a pinned baseline")
    if target in {"INDEXED", "IMPACT_REVIEW"} and not all(repo.get("index") for repo in repositories):
        raise FlowError("INDEX_REQUIRED", "all repositories must have a recorded index")
    if target == "ROUTE_APPROVED":
        _require_route_gate(state_value)
    if target in {"PLANNING", "IMPLEMENTING", "VERIFYING"}:
        _require_current_workspace_indexes(state_value)
    if target in {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        _require_route_gate(state_value)
        _require_workspace_ready(state_value)
    if target in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING", "DONE"}:
        route_value = (state_value.get("route") or {}).get("value")
        artifact_kind = "direct-contract" if route_value == "direct" else "openspec-plan"
        _require_current_plan_gate(state_value, artifact_kind)
    if target == "REVIEWING":
        current, reason = _review_is_current(state_value)
        if not current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", reason or "a current review snapshot is required")
    if target in {"FINALIZING", "DONE"}:
        review_current, review_reason = _review_is_current(state_value)
        if not review_current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", review_reason or "a current review snapshot is required")
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")
        _require_review_gate(state_value)
    if target == "DONE":
        test_current, test_reason = _latest_passing_test_is_current(state_value)
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")


def command_transition(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    target = args.to_option or args.to
    if target not in ALL_STATES:
        raise FlowError("INVALID_ARGUMENT", f"unknown target state: {target}", details={"allowed": sorted(ALL_STATES)})
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        source = current["status"]
        if source == target:
            return _result("transition", current, unchanged=True, transition={"from": source, "to": target})
        if source in TERMINAL_STATES:
            raise FlowError("INVALID_TRANSITION", f"terminal task cannot transition from {source}")
        if target == "CANCELLED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to CANCELLED requires --note; cancel is preferred")
        elif target == "BLOCKED":
            if not args.note:
                raise FlowError("INVALID_ARGUMENT", "transition to BLOCKED requires --note")
        elif source == "BLOCKED":
            expected = (current.get("blocked") or {}).get("from_status")
            if target != expected:
                raise FlowError("INVALID_TRANSITION", f"blocked task can only resume to {expected}", details={"from": source, "to": target, "allowed": [expected]})
        else:
            lite = _flow(current) == "lite"
            forward_edges = LITE_FORWARD_EDGES if lite else FORWARD_EDGES
            rework_edges = LITE_REWORK_EDGES if lite else REWORK_EDGES
            allowed = set(forward_edges.get(source, set())) | set(rework_edges.get(source, set()))
            if target not in allowed:
                raise FlowError("INVALID_TRANSITION", f"transition {source} -> {target} is not allowed", details={"from": source, "to": target, "allowed": sorted(allowed | {"BLOCKED", "CANCELLED"})})
            if (
                target == "PLANNING"
                and source in {"IMPLEMENTING", "VERIFYING", "REVIEWING", "FINALIZING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "replanning requires --note",
                    details={"from": source, "to": target},
                )
            if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES and not args.note:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "impact reassessment requires --note",
                    details={"from": source, "to": target},
                )
            if (
                lite
                and target == "PREFLIGHTED"
                and source in {"IMPLEMENTING", "VERIFYING"}
                and not args.note
            ):
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "reopening lite scope evidence requires --note",
                    details={"from": source, "to": target},
                )
        _transition_guard(current, target)
        state_value = _copy_state(current)
        state_value["status"] = target
        if target == "PLANNING" and source != "BLOCKED":
            state_value["planning_generation"] = int(
                current.get("planning_generation", 0)
            ) + 1
        if target == "BLOCKED":
            state_value["blocked"] = {"phase": "manual", "from_status": source, "reason": args.note, "details": [], "at": utc_now()}
        elif source == "BLOCKED":
            state_value["blocked"] = None
        if target == "CANCELLED":
            state_value["cancelled"] = {"reason": args.note, "at": utc_now(), "by": _actor()}
        if target == "IMPLEMENTING" and source in {"VERIFYING", "REVIEWING", "FINALIZING"}:
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("review", None)
        if target == "PLANNING" and source != "BLOCKED":
            state_value["review_snapshots"] = []
            state_value["approvals"].pop("plan", None)
            state_value["approvals"].pop("review", None)
        if target == "INDEXED" and source in IMPACT_REASSESS_SOURCES:
            state_value["impact_generation"] = int(
                current.get("impact_generation", 0)
            ) + 1
            state_value["route"] = None
            for gate in ("route", "workspace", "plan", "review"):
                state_value["approvals"].pop(gate, None)
            state_value["review_snapshots"] = []
            reassessed_at = utc_now()
            for repo in state_value.get("repositories", []):
                previous_workspace = repo.get("workspace")
                if previous_workspace:
                    history = repo.setdefault("workspace_history", [])
                    history.append(
                        {
                            **previous_workspace,
                            "workspace_index": repo.get("workspace_index"),
                            "retired_at": reassessed_at,
                            "retired_reason": args.note,
                        }
                    )
                repo["workspace"] = None
                repo["workspace_index"] = None
            previous_generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            state_value["workspace"] = {
                "strategy": "worktree",
                "ready": False,
                "generation": previous_generation + 1,
                "plan": None,
                "reassessed_at": reassessed_at,
            }
        _commit_state(current, state_value, task_dir, "state_transitioned", {"from": source, "to": target, "note": args.note})
    return _result("transition", state_value, transition={"from": source, "to": target, "note": args.note})


def command_cancel(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        if current.get("status") == "CANCELLED":
            return _result("cancel", current, unchanged=True, cancelled=current.get("cancelled"))
        if current.get("status") == "DONE":
            raise FlowError("INVALID_STATE", "completed task cannot be cancelled")
        state_value = _copy_state(current)
        source = state_value["status"]
        state_value["status"] = "CANCELLED"
        state_value["cancelled"] = {"reason": args.reason, "at": utc_now(), "by": _actor(), "from_status": source}
        _commit_state(current, state_value, task_dir, "task_cancelled", {"from": source, "reason": args.reason})
    return _result("cancel", state_value, cancelled=state_value["cancelled"])


def _parse_json_object(value: str | None, option: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise FlowError("INVALID_ARGUMENT", f"{option} is not valid JSON", details={"error": str(exc)}) from exc
    if not isinstance(parsed, dict):
        raise FlowError("INVALID_ARGUMENT", f"{option} must contain a JSON object")
    return parsed


def _task_arg(args: argparse.Namespace) -> str:
    task_id = getattr(args, "task_option", None) or getattr(args, "task_id", None)
    if not task_id:
        raise FlowError("INVALID_ARGUMENT", "task id is required (positional or --task)")
    return _validate_task_id(task_id)


def _add_data_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        default=argparse.SUPPRESS,
        help="state directory (overrides DEV_FLOW_DATA_DIR and PLUGIN_DATA)",
    )


def _add_task(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("task_id", nargs="?", help="task id")
    parser.add_argument("--task", dest="task_option", help="task id (alternative to positional form)")


def _add_mutation(parser: argparse.ArgumentParser) -> None:
    _add_task(parser)
    parser.add_argument(
        "--expected-revision",
        type=int,
        required=True,
        help="current state revision; stale writers fail with REVISION_CONFLICT",
    )
    _add_data_dir(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="dev_flow.py",
        description="Deterministic Codex + OpenSpec + codebase-memory development-flow control plane.",
    )
    parser.add_argument("--data-dir", help="state directory (may also follow a subcommand)")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    start = subparsers.add_parser("start", help="create an INTAKE task for one or more repositories")
    start.add_argument("requirement", nargs="?", help="requirement text")
    start.add_argument("--requirement", dest="requirement_option", help="requirement text (alternative to positional form)")
    start.add_argument("--repo", action="append", required=True, help="Git repository path; repeat for multiple repositories")
    start.add_argument("--task-id", help="stable task id (generated when omitted)")
    start.add_argument(
        "--flow",
        choices=sorted(FLOW_MODES),
        default=DEFAULT_FLOW,
        help=(
            "full runs baseline, impact, managed worktrees and independent review; "
            "lite works in place through preflight, one lite approval, implementation and verification"
        ),
    )
    start.add_argument("--protected-branch", action="append", help="protected branch name; repeat as needed")
    _add_data_dir(start)
    start.set_defaults(handler=command_start)

    show = subparsers.add_parser("show", help="show one full task snapshot")
    _add_task(show)
    _add_data_dir(show)
    show.set_defaults(handler=command_show)

    listing = subparsers.add_parser("list", help="list task summaries")
    listing.add_argument("--active-only", action="store_true", help="exclude DONE and CANCELLED tasks")
    listing.add_argument("--status", action="append", choices=sorted(ALL_STATES), help="include only this status; repeatable")
    _add_data_dir(listing)
    listing.set_defaults(handler=command_list)

    scope = subparsers.add_parser(
        "scope",
        help="show or change the directories where this plugin is active",
    )
    scope.add_argument(
        "--mode",
        choices=sorted(SCOPE_MODES),
        help="allowlist activates only inside included directories; all activates everywhere except excluded ones",
    )
    scope.add_argument(
        "--add",
        action="append",
        metavar="DIR",
        help="include a directory and its subdirectories; the first one switches to allowlist mode; repeatable",
    )
    scope.add_argument(
        "--remove", action="append", metavar="DIR", help="drop an included directory; repeatable"
    )
    scope.add_argument(
        "--add-exclude",
        action="append",
        metavar="DIR",
        help="exclude a directory and its subdirectories; repeatable",
    )
    scope.add_argument(
        "--remove-exclude",
        action="append",
        metavar="DIR",
        help="drop an excluded directory; repeatable",
    )
    scope.add_argument(
        "--clear",
        action="store_true",
        help="reset to the default scope: active in every directory",
    )
    scope.add_argument(
        "--check",
        nargs="?",
        const=".",
        metavar="DIR",
        help="report whether a directory is in scope; defaults to the current directory",
    )
    _add_data_dir(scope)
    scope.set_defaults(handler=command_scope)

    preflight = subparsers.add_parser("preflight", help="record Git identity, remote/base and an exact worktree fingerprint")
    _add_mutation(preflight)
    preflight.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    preflight.add_argument("--remote", help="override the parsed default remote")
    preflight.add_argument("--base", help="override the parsed default base branch")
    preflight.set_defaults(handler=command_preflight)

    baseline = subparsers.add_parser(
        "baseline",
        help="pin each repository's remote base commit after baseline-fetch approval",
    )
    _add_mutation(baseline)
    baseline.add_argument(
        "--fetch",
        action="store_true",
        help="fetch before pinning; approval must include --allow-fetch",
    )
    baseline.add_argument(
        "--materialize",
        action="store_true",
        help="create/reuse a detached analysis worktree at base_sha; requires baseline-fetch approval",
    )
    baseline.set_defaults(handler=command_baseline)

    record_index = subparsers.add_parser("record-index", help="record codebase-memory indexing provenance")
    _add_mutation(record_index)
    record_index.add_argument(
        "--role",
        choices=["baseline", "workspace"],
        default="baseline",
        help="index role; baseline is the backward-compatible default",
    )
    record_index.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    record_index.add_argument(
        "--commit",
        help="indexed commit; defaults to pinned base for baseline or current HEAD for workspace",
    )
    record_index.add_argument(
        "--index-id",
        help="external index id; omission requires impact-degraded approval and failed metadata",
    )
    record_index.add_argument("--receipt", help="optional index receipt file to hash")
    record_index.add_argument(
        "--metadata-json",
        help="JSON provenance; workspace requires persistence:false; degraded baseline requires failure provenance",
    )
    record_index.set_defaults(handler=command_record_index)

    artifact = subparsers.add_parser(
        "record-artifact",
        help="hash and record an immutable file or deterministic directory artifact",
    )
    _add_mutation(artifact)
    artifact.add_argument(
        "--path", "--artifact", dest="path", required=True, help="artifact file or directory"
    )
    artifact.add_argument("--kind", required=True, help="artifact kind, for example impact, openspec, plan or review")
    artifact.add_argument(
        "--verdict",
        choices=["PASS", "CONDITIONAL", "FAIL"],
        help="must match the review report's unique first non-empty Verdict: line",
    )
    artifact.add_argument("--metadata-json", help="optional JSON object")
    artifact.set_defaults(handler=command_record_artifact)

    route = subparsers.add_parser("set-route", help="bind direct or openspec to the current impact/index evidence")
    _add_mutation(route)
    route.add_argument("route", nargs="?", choices=["direct", "openspec"], help="development route")
    route.add_argument("--route", dest="route_option", choices=["direct", "openspec"], help="development route")
    route.add_argument("--reason", required=True, help="why this route fits the impact")
    route.set_defaults(handler=command_set_route)

    approve = subparsers.add_parser("approve", help="approve a named gate with an auditable note")
    _add_mutation(approve)
    approve.add_argument("--gate", required=True, help="gate name; route approval advances to ROUTE_APPROVED")
    approve.add_argument("--note", required=True, help="approval note")
    approve.add_argument("--artifact-sha256", help="artifact hash; required by evidence-bound gates")
    approve.add_argument(
        "--accept-conditional",
        action="store_true",
        help="explicitly accept a CONDITIONAL review verdict",
    )
    approve.add_argument(
        "--allow-fetch",
        action="store_true",
        help="authorize network fetches (only for --gate baseline-fetch)",
    )
    approve.add_argument(
        "--allow-dirty",
        action="store_true",
        help="approve the exact dirty preflight snapshot (only for baseline-fetch or lite)",
    )
    approve.set_defaults(handler=command_approve)

    transition = subparsers.add_parser("transition", help="make one guarded state-machine transition")
    _add_mutation(transition)
    transition.add_argument("to", nargs="?", choices=sorted(ALL_STATES), help="target state")
    transition.add_argument("--to", dest="to_option", choices=sorted(ALL_STATES), help="target state")
    transition.add_argument("--note", help="transition note; required for BLOCKED or CANCELLED")
    transition.set_defaults(handler=command_transition)

    workspace = subparsers.add_parser(
        "prepare-workspace",
        help="record an approvable plan or create its exact isolated Git worktrees",
    )
    _add_mutation(workspace)
    workspace.add_argument("--repo", action="append", help="repository id or path; if supplied, must enumerate all task repositories")
    workspace.add_argument("--branch", help="workspace branch; defaults to codex/<task-id>")
    workspace.add_argument("--path", help="workspace path (only with one selected repository)")
    workspace.add_argument(
        "--workspace-path",
        action="append",
        help="per-repository absolute path override as REPOSITORY=PATH; repeatable",
    )
    workspace.add_argument(
        "--workspace-branch",
        action="append",
        help="per-repository branch override as REPOSITORY=BRANCH; repeatable",
    )
    mode = workspace.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="execute the latest workspace-gate-approved plan exactly",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="record/return a deterministic workspace-plan artifact (default)",
    )
    workspace.set_defaults(handler=command_prepare_workspace)

    tests = subparsers.add_parser("record-test", help="record a named command identity against exact repository fingerprints")
    _add_mutation(tests)
    tests.add_argument("--repo", action="append", help="repository id or path; defaults to all")
    tests.add_argument("--name", required=True, help="test suite name")
    tests.add_argument("--command", dest="test_command", required=True, help="command that was run (recorded, never executed)")
    tests.add_argument("--exit-code", type=int, required=True, help="observed process exit code")
    tests.add_argument("--output", help="optional captured test output file to hash")
    tests.set_defaults(handler=command_record_test)

    review = subparsers.add_parser("review-snapshot", help="capture base...HEAD, cached, unstaged and untracked review inputs")
    _add_mutation(review)
    review.add_argument("--repo", action="append", help="repository id or path; must cover all repositories")
    review.set_defaults(handler=command_review_snapshot)

    cancel = subparsers.add_parser("cancel", help="cancel a non-terminal task with a reason")
    _add_mutation(cancel)
    cancel.add_argument("--reason", required=True, help="cancellation reason")
    cancel.set_defaults(handler=command_cancel)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = build_parser()
        args, unknown = parser.parse_known_args(argv)
        # argparse cannot intermix optional arguments between two optional
        # positionals.  Accept the natural `TASK --expected-revision N TARGET`
        # spelling for these two commands without weakening typo detection.
        if unknown:
            if (
                args.command == "set-route"
                and len(unknown) == 1
                and args.route is None
                and unknown[0] in {"direct", "openspec"}
            ):
                args.route = unknown[0]
            elif (
                args.command == "transition"
                and len(unknown) == 1
                and args.to is None
                and unknown[0] in ALL_STATES
            ):
                args.to = unknown[0]
            else:
                parser.error(f"unrecognized arguments: {' '.join(unknown)}")
        if not hasattr(args, "data_dir"):
            args.data_dir = None
        response = args.handler(args)
        print(json.dumps(response, sort_keys=True, ensure_ascii=False))
        return 0
    except FlowError as exc:
        response = {
            "ok": False,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }
        print(json.dumps(response, sort_keys=True, ensure_ascii=False))
        return exc.exit_code
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": {"code": "INTERRUPTED", "message": "operation interrupted", "details": {}}}, sort_keys=True))
        return 130
    except Exception as exc:  # Keep the machine contract even for unexpected failures.
        print(json.dumps({"ok": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc), "details": {"type": type(exc).__name__}}}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
