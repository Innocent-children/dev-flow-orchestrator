#!/usr/bin/env python3
"""Prepare or run the project-local, canonical-bound Windows native validation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
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
) -> subprocess.CompletedProcess:
    try:
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
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeValidationError(
            "CHILD_SPAWN_FAILED",
            f"native validation child could not run: {exc.__class__.__name__}",
        ) from exc


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


def _controller_call(
    candidate_root: Path,
    data_dir: Path,
    arguments: Sequence[str],
    *,
    expected_error: Optional[str] = None,
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


def _controller_mutation(
    candidate_root: Path,
    data_dir: Path,
    command: str,
    task_id: str,
    revision: int,
    *arguments: str,
    expected_error: Optional[str] = None,
) -> dict[str, Any]:
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
        return _controller_call(
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
        )
    return _controller_call(
        candidate_root,
        data_dir,
        [
            command,
            task_id,
            "--expected-revision",
            str(revision),
            *arguments,
        ],
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
) -> tuple[int, str]:
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

    revision = int(started["revision"])
    response = _controller_mutation(
        candidate_root,
        data_dir,
        "preflight",
        task_id,
        revision,
        "--repo",
        str(alternate_selector),
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
    )
    revision = int(response["revision"])
    response = _controller_mutation(
        candidate_root,
        data_dir,
        "baseline",
        task_id,
        revision,
        "--materialize",
    )
    revision = int(response["revision"])
    response = _controller_mutation(
        candidate_root,
        data_dir,
        "record-index",
        task_id,
        revision,
        "--repo",
        str(start_selector),
        "--index-id",
        f"native-baseline-{task_id}",
    )
    revision = int(response["revision"])
    impact_path.write_text("Native managed-worktree impact.\n", encoding="utf-8")
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
    )
    revision = int(response["revision"])
    artifact_sha256 = str((response.get("artifact") or {}).get("sha256") or "")
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
    )
    return int(response["revision"]), repository_id


def exercise_controller_managed_worktree(
    candidate_root: Path,
    data_dir: Path,
    local_repo: Path,
    repository_alias: Path,
    worktree: Path,
    scratch: Path,
) -> dict[str, Any]:
    """Exercise the real controller CLI and its durable worktree contracts."""

    owner_task = "native-managed-owner"
    contender_task = "native-managed-contender"
    branch = "native/long-path-validation"
    owner_revision, repository_id = _route_approved_controller_task(
        candidate_root,
        data_dir,
        task_id=owner_task,
        start_selector=repository_alias,
        alternate_selector=local_repo,
        impact_path=scratch / "owner-impact.md",
    )
    contender_revision, _ = _route_approved_controller_task(
        candidate_root,
        data_dir,
        task_id=contender_task,
        start_selector=local_repo,
        alternate_selector=repository_alias,
        impact_path=scratch / "contender-impact.md",
    )

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
        "native/equivalent-alias-contender",
        expected_error="WORKSPACE_OWNERSHIP_CONFLICT",
    )
    conflict_details = (conflict.get("error") or {}).get("details") or {}
    if conflict_details.get("conflict") != "path":
        raise NativeValidationError(
            "CONTROLLER_OWNERSHIP_CONFLICT_INEXACT",
            "equivalent repository alias did not produce an exact path claim conflict",
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
        report["checks"].append(_check_code_page(extraction, child, args.code_page))
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
