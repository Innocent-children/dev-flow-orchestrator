# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Workspace planning, claims, execution, integrity, and planning context.
from __future__ import annotations

import copy as _workspace_copy
import hashlib as _workspace_hashlib
import os as _workspace_os
import re as _workspace_re
import threading as _workspace_threading
from contextlib import contextmanager as _workspace_contextmanager
from dataclasses import dataclass as _workspace_dataclass
from pathlib import Path as _WorkspacePath
from types import MappingProxyType as _WorkspaceMappingProxyType
from typing import Mapping as _WorkspaceMapping


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
    return any(
        isinstance(claim, dict)
        and claim.get("evidence_contract_version")
        == EVIDENCE_CONTRACT_VERSION
        and claim.get("task_id") == state_value.get("task_id")
        and claim.get("repository_id") == repo.get("id")
        and claim.get("workspace_generation") == generation
        and _recorded_path_matches(
            claim.get("path_identity"), claim.get("path"), path
        )
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


def _branch_ref_state(
    source: Path, branch: str, protected_branches: Sequence[str]
) -> dict[str, Any]:
    branch_ref = f"refs/heads/{branch}"
    common_dir = _git_common_dir(source)
    ref_case_sensitive = _probe_filesystem_case_sensitive(common_dir)
    ref_unicode_distinct = _probe_filesystem_unicode_distinct(common_dir)
    output = _git(
        source,
        "for-each-ref",
        "--format=%(refname)%09%(objectname)",
        "refs/heads",
        text=False,
    )
    refs: dict[str, str] = {}
    for line in output.splitlines():
        ref_name_bytes, separator, object_id_bytes = line.partition(b"\t")
        if (
            not separator
            or not ref_name_bytes
            or not object_id_bytes
        ):
            raise FlowError(
                "GIT_EVIDENCE_MALFORMED",
                "Git returned malformed local-ref identity evidence",
                details={
                    "repository": str(source),
                    "record_hex": line.hex(),
                },
            )
        try:
            ref_name = ref_name_bytes.decode("utf-8", "strict")
            object_id = object_id_bytes.decode("ascii", "strict")
        except UnicodeError as exc:
            raise FlowError(
                "REF_IDENTITY_UNAVAILABLE",
                "local ref identity is not representable losslessly",
                details={
                    "repository": str(source),
                    "record_hex": line.hex(),
                },
            ) from exc
        refs[ref_name] = object_id

    def alias(value: str) -> str:
        normalized = (
            value
            if ref_unicode_distinct
            else unicodedata.normalize("NFC", value)
        )
        return normalized if ref_case_sensitive else normalized.casefold()

    protected_refs = {f"refs/heads/{item}" for item in protected_branches}
    if any(alias(item) == alias(branch_ref) for item in protected_refs):
        raise FlowError(
            "PROTECTED_BRANCH",
            f"workspace branch aliases a protected branch: {branch}",
            details={
                "repository": str(source),
                "branch": branch,
                "branch_ref": branch_ref,
                "ref_case_sensitive": ref_case_sensitive,
                "ref_unicode_normalization_distinct": ref_unicode_distinct,
            },
        )
    for existing_ref in refs:
        if existing_ref == branch_ref:
            continue
        filesystem_alias = alias(existing_ref) == alias(branch_ref)
        directory_file_alias = (
            existing_ref.startswith(f"{branch_ref}/")
            or branch_ref.startswith(f"{existing_ref}/")
        )
        if filesystem_alias or directory_file_alias:
            raise FlowError(
                "WORKSPACE_REF_COLLISION",
                "workspace branch is path-equivalent to an incompatible existing ref",
                details={
                    "repository": str(source),
                    "branch_ref": branch_ref,
                    "existing_ref": existing_ref,
                    "ref_case_sensitive": ref_case_sensitive,
                    "ref_unicode_normalization_distinct": ref_unicode_distinct,
                    "collision": (
                        "filesystem_alias"
                        if filesystem_alias
                        else "directory_file_alias"
                    ),
                },
            )
    return {
        "branch_ref": branch_ref,
        "planned_ref_oid": refs.get(branch_ref),
        "ref_case_sensitive": ref_case_sensitive,
        "ref_unicode_normalization_distinct": ref_unicode_distinct,
        "git_common_dir": str(common_dir),
        "git_common_dir_identity": _serializable_path_identity(common_dir),
    }


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
        baseline = _require_current_evidence(repo.get("baseline"), "baseline")
        source_repo = Path(repo["path"]).resolve(strict=True)
        source_capability_profile = _git_capability_profile(source_repo)
        if (
            baseline.get("capability_profile_sha256")
            != source_capability_profile["sha256"]
        ):
            raise FlowError(
                "GIT_CAPABILITY_CHANGED",
                "repository capabilities changed after the approved baseline",
                details={
                    "repository_id": repo["id"],
                    "baseline_capability_profile_sha256": baseline.get(
                        "capability_profile_sha256"
                    ),
                    "current_capability_profile_sha256": (
                        source_capability_profile["sha256"]
                    ),
                },
            )
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
        protected_ref_names = set(protected)
        if base_branch:
            protected_ref_names.add(base_branch)
        branch_state = _branch_ref_state(
            source_repo, branch, sorted(protected_ref_names)
        )
        symbolic_target = _git_optional(
            source_repo,
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
        capability_profile = _git_capability_profile(source_repo, path)
        recorded = repo.get("workspace") or {}
        exact_recorded = bool(
            recorded.get("ready")
            and _recorded_path_matches(
                recorded.get("path_identity"),
                recorded.get("path"),
                path,
            )
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
            if (
                retired_path is not None
                and _recorded_path_matches(
                    retired.get("path_identity"),
                    retired.get("path"),
                    path,
                )
            ) or retired.get("branch") == branch:
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
            configured_source = Path(configured_repo["path"]).resolve(
                strict=False
            )
            if _is_within(path, configured_source) or _is_within(
                configured_source, path
            ):
                raise FlowError(
                    "WORKSPACE_NOT_ISOLATED",
                    "workspace path must be independent from every source checkout",
                    details={
                        "repository_id": repo["id"],
                        "path": str(path),
                        "source_path": str(configured_source),
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
                    _same_path(entry_path, path)
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
            _same_path(containing_root, path)
            and (exact_recorded or exact_claimed)
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
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "source_identity": _serializable_path_identity(source_repo),
                "path": str(path),
                "path_identity": _serializable_path_identity(path),
                "branch": branch,
                "branch_ref": branch_state["branch_ref"],
                "planned_ref_oid": (
                    recorded.get("planned_ref_oid")
                    if exact_recorded
                    else branch_state["planned_ref_oid"]
                ),
                "ref_case_sensitive": branch_state["ref_case_sensitive"],
                "ref_unicode_normalization_distinct": branch_state[
                    "ref_unicode_normalization_distinct"
                ],
                "source_common_dir": branch_state["git_common_dir"],
                "source_common_dir_identity": branch_state[
                    "git_common_dir_identity"
                ],
                "base_sha": base_sha,
                "capability_profile": capability_profile,
                "capability_profile_sha256": capability_profile["sha256"],
                "source_capability_profile_sha256": (
                    source_capability_profile["sha256"]
                ),
                "strategy": "worktree",
                "owner_task_id": state_value["task_id"],
                "workspace_generation": generation,
                "previously_recorded": bool(
                    recorded.get("ready")
                    and _recorded_path_matches(
                        recorded.get("path_identity"),
                        recorded.get("path"),
                        path,
                    )
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
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "repository_id": plan["repository_id"],
            "source_path": plan["source_path"],
            "source_identity": plan["source_identity"],
            "path": plan["path"],
            # The approval digest must survive the expected transition from a
            # planned path (identified through its nearest existing ancestor)
            # to a materialized directory (which has its own file ID).  Live
            # ownership checks retain and revalidate the complete identities.
            "path_identity": _capability_path_identity(
                Path(plan["path"])
            ),
            "branch": plan["branch"],
            "branch_ref": plan["branch_ref"],
            "planned_ref_oid": plan["planned_ref_oid"],
            "ref_case_sensitive": plan["ref_case_sensitive"],
            "ref_unicode_normalization_distinct": plan[
                "ref_unicode_normalization_distinct"
            ],
            "source_common_dir": plan["source_common_dir"],
            "source_common_dir_identity": plan[
                "source_common_dir_identity"
            ],
            "base_sha": plan["base_sha"],
            "capability_profile_sha256": plan[
                "capability_profile_sha256"
            ],
            "source_capability_profile_sha256": plan[
                "source_capability_profile_sha256"
            ],
            "strategy": "worktree",
        }
        for plan in plans
    ]
    evidence_repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "strategy": "worktree",
        "workspace_generation": int(
            (state_value.get("workspace") or {}).get("generation", 0)
        ),
        "repositories": evidence_repositories,
    }


_V4_WORKSPACE_EFFECT_PLAN_SCHEMA = (
    "dev-flow-v4-workspace-effect-plan/v1"
)
_V4_WORKSPACE_EFFECT_OBSERVATION_SCHEMA = (
    "dev-flow-v4-workspace-effect-observation/v1"
)
_V4_WORKSPACE_EFFECT_RECEIPT_SCHEMA = (
    "dev-flow-v4-workspace-effect-receipt/v1"
)
_V4_WORKSPACE_PLAN_ARTIFACT_AUTHORIZATION_SCHEMA = (
    "dev-flow-v4-workspace-plan-artifact-authorization/v1"
)
_V4_WORKSPACE_EFFECT_PLAN_DOMAIN = (
    b"dev-flow-v4-workspace-effect-plan-v1\x00"
)
_V4_WORKSPACE_EFFECT_OBSERVATION_DOMAIN = (
    b"dev-flow-v4-workspace-effect-observation-v1\x00"
)
_V4_WORKSPACE_EFFECT_RECEIPT_DOMAIN = (
    b"dev-flow-v4-workspace-effect-receipt-v1\x00"
)
_V4_WORKSPACE_APPROVAL_BINDING_DOMAIN = (
    b"dev-flow-v4-workspace-approval-binding-v1\x00"
)
_V4_WORKSPACE_SOURCE_BINDING_DOMAIN = (
    b"dev-flow-v4-workspace-source-binding-v1\x00"
)
_V4_WORKSPACE_ACTIONS = frozenset({"plan", "execute"})
_V4_WORKSPACE_EXPECTED_EFFECT_IDS = {
    "plan": "full.route-approved.plan-workspace.v1.effect",
    "execute": "full.route-approved.prepare-workspace.v1.effect",
}
_V4_WORKSPACE_SHA256 = _workspace_re.compile(r"[0-9a-f]{64}")
_V4_WORKSPACE_SECRET_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "manager_secret",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_v4_workspace_readonly_git_lock = _workspace_threading.RLock()


@_workspace_contextmanager
def _v4_workspace_readonly_git():
    """Prevent read-only Git evidence from refreshing mutable index caches."""

    with _v4_workspace_readonly_git_lock:
        marker = object()
        previous = _workspace_os.environ.get(
            "GIT_OPTIONAL_LOCKS", marker
        )
        _workspace_os.environ["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            yield
        finally:
            if previous is marker:
                _workspace_os.environ.pop("GIT_OPTIONAL_LOCKS", None)
            else:
                _workspace_os.environ["GIT_OPTIONAL_LOCKS"] = str(
                    previous
                )


def _v4_workspace_seed_filesystem_facts(
    path: _WorkspacePath,
    filesystem: _WorkspaceMapping[str, object],
) -> None:
    """Hydrate only process-local probes from approved durable facts."""

    case_sensitive = filesystem.get("case_sensitive")
    unicode_distinct = filesystem.get(
        "unicode_normalization_distinct"
    )
    if not isinstance(case_sensitive, bool) or not isinstance(
        unicode_distinct, bool
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_FILESYSTEM_FACTS_INVALID",
            "approved filesystem facts are incomplete",
            details={"path": str(path)},
        )
    ancestor, _suffix = _nearest_existing_path(path)
    stable = _stable_existing_identity(ancestor)
    case_key: object = ("macos-device", stable.get("device"))
    unicode_key: object = ("macos-device", stable.get("device"))
    for cache, key, approved, role in (
        (
            _FILESYSTEM_CASE_CACHE,
            case_key,
            case_sensitive,
            "case-sensitive",
        ),
        (
            _FILESYSTEM_UNICODE_CACHE,
            unicode_key,
            unicode_distinct,
            "unicode-normalization",
        ),
    ):
        cached = cache.get(key)
        if cached is not None and cached != approved:
            raise _v4_workspace_error(
                "GIT_CAPABILITY_CHANGED",
                "approved filesystem facts conflict with live cached facts",
                details={"path": str(path), "fact": role},
            )
        cache[key] = approved


def _v4_workspace_readonly_recorded_path_matches(
    recorded_identity: object,
    recorded_path: object,
    candidate: _WorkspacePath,
) -> bool:
    """Verify canonical location/stable ID without filesystem probes."""

    if not isinstance(recorded_path, str) or not recorded_path:
        return False
    try:
        expected = _WorkspacePath(recorded_path).resolve(strict=True)
        actual = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    try:
        if not _workspace_os.path.samefile(expected, actual):
            return False
    except OSError:
        if str(expected) != str(actual):
            return False
    if not isinstance(recorded_identity, _WorkspaceMapping):
        return True
    stable = recorded_identity.get("ancestor_identity")
    suffix = recorded_identity.get("suffix_parts")
    if isinstance(stable, _WorkspaceMapping) and not tuple(
        suffix or ()
    ):
        current = _stable_existing_identity(actual)
        current_public = {
            key: value
            for key, value in current.items()
            if key != "final_path"
        }
        if current_public != dict(stable):
            return False
    return True


def _v4_workspace_error(
    code: str,
    message: str,
    *,
    details: _WorkspaceMapping[str, object] | None = None,
) -> FlowError:
    return FlowError(code, message, details=dict(details or {}))


def _v4_workspace_public(value: object) -> object:
    """Copy and validate one strict semantic-JSON value."""

    if isinstance(value, _WorkspaceMapping):
        candidate = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _v4_workspace_error(
                    "WORKSPACE_EFFECT_SEMANTIC_JSON_INVALID",
                    "workspace semantic object keys must be text",
                )
            candidate[key] = _v4_workspace_public(item)
    elif isinstance(value, tuple):
        candidate = [_v4_workspace_public(item) for item in value]
    elif isinstance(value, list):
        candidate = [_v4_workspace_public(item) for item in value]
    else:
        candidate = _workspace_copy.deepcopy(value)
    try:
        canonical = semantic_json_bytes(candidate)
        return parse_semantic_json(canonical)
    except Exception as exc:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SEMANTIC_JSON_INVALID",
            "workspace effect values must use strict NFC semantic JSON",
            details={
                "cause_code": getattr(
                    exc, "code", type(exc).__name__
                )
            },
        ) from None


def _v4_workspace_freeze(value: object) -> object:
    public = _v4_workspace_public(value)
    if isinstance(public, dict):
        return _WorkspaceMappingProxyType(
            {
                key: _v4_workspace_freeze(item)
                for key, item in public.items()
            }
        )
    if isinstance(public, list):
        return tuple(_v4_workspace_freeze(item) for item in public)
    return public


def _v4_workspace_thaw(value: object) -> object:
    if isinstance(value, _WorkspaceMapping):
        return {
            str(key): _v4_workspace_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_v4_workspace_thaw(item) for item in value]
    return _workspace_copy.deepcopy(value)


def _v4_workspace_reject_secrets(
    value: object,
    *,
    pointer: str = "",
) -> None:
    if isinstance(value, _WorkspaceMapping):
        for key, item in value.items():
            folded = str(key).casefold().replace("-", "_")
            if folded in _V4_WORKSPACE_SECRET_FIELDS or any(
                folded.endswith("_" + secret)
                for secret in _V4_WORKSPACE_SECRET_FIELDS
            ):
                raise _v4_workspace_error(
                    "WORKSPACE_EFFECT_SECRET_FORBIDDEN",
                    "workspace plans and receipts cannot contain secrets",
                    details={"pointer": pointer + "/" + str(key)},
                )
            _v4_workspace_reject_secrets(
                item, pointer=pointer + "/" + str(key)
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _v4_workspace_reject_secrets(
                item, pointer=f"{pointer}/{index}"
            )


def _v4_workspace_sha256(
    domain: bytes, value: object
) -> str:
    public = _v4_workspace_public(value)
    return semantic_sha256(domain, public)


def _v4_workspace_require_text(value: object, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_BINDING_INVALID",
            f"{role} must be non-empty text",
        )
    _v4_workspace_public(value)
    return value


def _v4_workspace_require_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_BINDING_INVALID",
            "task revision must be a non-negative integer",
        )
    return value


def _v4_workspace_sorted_text(
    values: Sequence[object], role: str
) -> tuple[str, ...]:
    normalized = tuple(
        _v4_workspace_require_text(item, role) for item in values
    )
    expected = tuple(
        sorted(set(normalized), key=lambda item: item.encode("utf-8"))
    )
    if normalized != expected:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_BINDING_INVALID",
            f"{role} must be sorted and unique",
        )
    return normalized


def _v4_workspace_plan_core(
    action: str,
    expected_effect_id: str,
    task_id: str,
    task_revision: int,
    workspace_generation: int,
    repository_ids: Sequence[str],
    approved_binding_sha256: str,
    bindings: _WorkspaceMapping[str, object],
) -> dict[str, object]:
    return {
        "schema": _V4_WORKSPACE_EFFECT_PLAN_SCHEMA,
        "action": action,
        "expected_effect_id": expected_effect_id,
        "task_id": task_id,
        "task_revision": task_revision,
        "workspace_generation": workspace_generation,
        "repository_ids": list(repository_ids),
        "approved_binding_sha256": approved_binding_sha256,
        "bindings": dict(bindings),
    }


@_workspace_dataclass(frozen=True)
class V4WorkspaceEffectPlan:
    """Immutable authorization-independent workspace effect description."""

    action: str
    expected_effect_id: str
    task_id: str
    task_revision: int
    workspace_generation: int
    repository_ids: tuple[str, ...]
    approved_binding_sha256: str
    bindings: _WorkspaceMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        expected_type = {
            "plan": "V4WorkspacePlanEffectPlan",
            "execute": "V4WorkspaceExecuteEffectPlan",
        }.get(self.action)
        if expected_type is None or type(self).__name__ != expected_type:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
                "typed workspace plan class does not match its action",
                details={"action": self.action},
            )
        expected_effect_id = _V4_WORKSPACE_EXPECTED_EFFECT_IDS[
            self.action
        ]
        if self.expected_effect_id != expected_effect_id:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_ID_MISMATCH",
                "typed workspace plan does not bind its sealed effect ID",
                details={
                    "expected_effect_id": expected_effect_id,
                    "actual_effect_id": self.expected_effect_id,
                },
            )
        _v4_workspace_require_text(self.task_id, "task_id")
        _v4_workspace_require_revision(self.task_revision)
        if (
            isinstance(self.workspace_generation, bool)
            or not isinstance(self.workspace_generation, int)
            or self.workspace_generation < 0
        ):
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_BINDING_INVALID",
                "workspace generation must be a non-negative integer",
            )
        repository_ids = _v4_workspace_sorted_text(
            self.repository_ids, "repository_ids"
        )
        if not repository_ids:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_BINDING_INVALID",
                "workspace effects require at least one repository",
            )
        if (
            not isinstance(self.approved_binding_sha256, str)
            or not _V4_WORKSPACE_SHA256.fullmatch(
                self.approved_binding_sha256
            )
        ):
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_BINDING_INVALID",
                "approved binding digest must be lowercase SHA-256",
            )
        public_bindings = _v4_workspace_public(dict(self.bindings))
        assert isinstance(public_bindings, dict)
        _v4_workspace_reject_secrets(public_bindings)
        core = _v4_workspace_plan_core(
            self.action,
            self.expected_effect_id,
            self.task_id,
            self.task_revision,
            self.workspace_generation,
            repository_ids,
            self.approved_binding_sha256,
            public_bindings,
        )
        expected = _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_PLAN_DOMAIN, core
        )
        if expected != self.semantic_sha256:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_PLAN_DIGEST_MISMATCH",
                "workspace plan digest differs from its semantic bindings",
            )
        object.__setattr__(self, "repository_ids", repository_ids)
        object.__setattr__(
            self, "bindings", _v4_workspace_freeze(public_bindings)
        )

    def as_dict(self) -> dict[str, object]:
        core = _v4_workspace_plan_core(
            self.action,
            self.expected_effect_id,
            self.task_id,
            self.task_revision,
            self.workspace_generation,
            self.repository_ids,
            self.approved_binding_sha256,
            _v4_workspace_thaw(self.bindings),
        )
        core["semantic_sha256"] = self.semantic_sha256
        return core


@_workspace_dataclass(frozen=True)
class V4WorkspacePlanEffectPlan(V4WorkspaceEffectPlan):
    pass


@_workspace_dataclass(frozen=True)
class V4WorkspaceExecuteEffectPlan(V4WorkspaceEffectPlan):
    pass


_V4_WORKSPACE_PLAN_TYPES = {
    "plan": V4WorkspacePlanEffectPlan,
    "execute": V4WorkspaceExecuteEffectPlan,
}


def _v4_workspace_build_plan(
    action: str,
    *,
    task_id: str,
    task_revision: int,
    workspace_generation: int,
    repository_ids: Sequence[str],
    approved_binding_sha256: str,
    bindings: _WorkspaceMapping[str, object],
) -> V4WorkspaceEffectPlan:
    ids = tuple(
        sorted(
            {
                _v4_workspace_require_text(item, "repository_id")
                for item in repository_ids
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    public = _v4_workspace_public(dict(bindings))
    assert isinstance(public, dict)
    _v4_workspace_reject_secrets(public)
    core = _v4_workspace_plan_core(
        action,
        _V4_WORKSPACE_EXPECTED_EFFECT_IDS[action],
        _v4_workspace_require_text(task_id, "task_id"),
        _v4_workspace_require_revision(task_revision),
        workspace_generation,
        ids,
        approved_binding_sha256,
        public,
    )
    plan_type = _V4_WORKSPACE_PLAN_TYPES[action]
    return plan_type(
        action,
        _V4_WORKSPACE_EXPECTED_EFFECT_IDS[action],
        task_id,
        task_revision,
        workspace_generation,
        ids,
        approved_binding_sha256,
        public,
        _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_PLAN_DOMAIN, core
        ),
    )


def _v4_workspace_task_paths(
    task_id: str,
    data_root: str | _WorkspacePath,
    task_dir: str | _WorkspacePath,
) -> tuple[_WorkspacePath, _WorkspacePath, _WorkspacePath]:
    resolved_data = _WorkspacePath(data_root).expanduser().resolve(
        strict=True
    )
    resolved_task = _WorkspacePath(task_dir).expanduser().resolve(
        strict=True
    )
    expected_task = (resolved_data / "tasks" / task_id).resolve(
        strict=False
    )
    if not _same_path(resolved_task, expected_task):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TASK_PATH_MISMATCH",
            "workspace task directory is outside its controller namespace",
            details={
                "task_id": task_id,
                "task_dir": str(resolved_task),
                "expected_task_dir": str(expected_task),
            },
        )
    state_path = resolved_task / "state.json"
    if not state_path.is_file():
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_STATE_UNAVAILABLE",
            "workspace effect requires a durable task state",
            details={"path": str(state_path)},
        )
    return resolved_data, resolved_task, state_path


def _v4_workspace_route_approval_binding(
    state_value: dict[str, Any],
) -> dict[str, object]:
    impact = _latest_artifact(state_value, "impact")
    if not isinstance(impact, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "workspace planning requires a current impact artifact",
        )
    impact_path = _WorkspacePath(str(impact.get("path")))
    if not _v4_workspace_readonly_recorded_path_matches(
        impact.get("path_identity"),
        impact.get("path"),
        impact_path,
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "impact artifact path identity changed",
        )
    try:
        current_hash = _hash_artifact(impact_path)
    except (FlowError, OSError) as exc:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "impact artifact cannot be revalidated",
            details={"cause_code": getattr(exc, "code", "OSError")},
        ) from None
    if current_hash.get("sha256") != impact.get("sha256"):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "impact artifact bytes changed",
        )
    approval = (state_value.get("approvals") or {}).get("route")
    if not isinstance(approval, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "workspace planning requires route approval",
        )
    route = state_value.get("route") or {}
    metadata = impact.get("metadata") or {}
    if not isinstance(route, dict) or route.get("value") not in {
        "direct",
        "openspec",
    }:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "workspace route selection is unavailable",
        )
    impact_generation = metadata.get("impact_generation")
    index_provenance = metadata.get(
        "index_provenance_sha256"
    )
    mismatches = []
    for field, actual, expected in (
        (
            "route.impact_artifact_id",
            route.get("impact_artifact_id"),
            impact.get("artifact_id"),
        ),
        (
            "route.impact_sha256",
            route.get("impact_sha256"),
            impact.get("sha256"),
        ),
        (
            "route.impact_generation",
            route.get("impact_generation"),
            impact_generation,
        ),
        (
            "route.index_provenance_sha256",
            route.get("index_provenance_sha256"),
            index_provenance,
        ),
        (
            "approval.artifact_id",
            approval.get("artifact_id"),
            impact.get("artifact_id"),
        ),
        (
            "approval.artifact_sha256",
            approval.get("artifact_sha256"),
            impact.get("sha256"),
        ),
        (
            "approval.impact_generation",
            approval.get("impact_generation"),
            impact_generation,
        ),
        (
            "approval.index_provenance_sha256",
            approval.get("index_provenance_sha256"),
            index_provenance,
        ),
        (
            "state.impact_generation",
            int(state_value.get("impact_generation", 0)),
            impact_generation,
        ),
    ):
        if actual != expected:
            mismatches.append(field)
    expected_analysis = metadata.get("impact_analysis_sha256")
    if _uses_confirmation_contract(state_value):
        if (
            route.get("impact_analysis_sha256")
            != expected_analysis
        ):
            mismatches.append("route.impact_analysis_sha256")
        if (
            approval.get("impact_analysis_sha256")
            != expected_analysis
        ):
            mismatches.append("approval.impact_analysis_sha256")
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "route approval is not bound to the current impact record",
            details={"fields": sorted(mismatches)},
        )
    return {
        "gate": "route",
        "approval_id": approval.get("approval_id"),
        "artifact_id": impact.get("artifact_id"),
        "artifact_sha256": impact.get("sha256"),
        "route": route.get("value"),
        "impact_generation": impact_generation,
        "index_provenance_sha256": index_provenance,
        "impact_analysis_sha256": metadata.get(
            "impact_analysis_sha256",
            route.get("impact_analysis_sha256"),
        ),
    }


def _v4_workspace_approved_plan_binding(
    state_value: dict[str, Any],
) -> tuple[dict[str, object], dict[str, Any]]:
    approval, artifact = _require_gate_for_latest_artifact(
        state_value, "workspace", "workspace-plan"
    )
    controller = (state_value.get("workspace") or {}).get(
        "plan"
    ) or {}
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    metadata = artifact.get("metadata") or {}
    mismatches = []
    if approval.get("artifact_id") != artifact.get("artifact_id"):
        mismatches.append("approval.artifact_id")
    if approval.get("workspace_generation") != generation:
        mismatches.append("approval.workspace_generation")
    if controller.get("artifact_id") != artifact.get("artifact_id"):
        mismatches.append("controller.artifact_id")
    if controller.get("sha256") != artifact.get("sha256"):
        mismatches.append("controller.sha256")
    if controller.get("path") != artifact.get("path"):
        mismatches.append("controller.path")
    if controller.get("workspace_generation") != generation:
        mismatches.append("controller.workspace_generation")
    if metadata.get("workspace_generation") != generation:
        mismatches.append("artifact.workspace_generation")
    if mismatches:
        raise _v4_workspace_error(
            "STALE_WORKSPACE_PLAN",
            "workspace approval, artifact, and controller plan disagree",
            details={"fields": sorted(mismatches)},
        )
    binding = {
        "gate": "workspace",
        "approval_id": approval.get("approval_id"),
        "artifact_id": artifact.get("artifact_id"),
        "artifact_sha256": artifact.get("sha256"),
        "artifact_path": artifact.get("path"),
        "workspace_generation": generation,
        "repository_ids": metadata.get("repository_ids"),
    }
    return binding, artifact


def _v4_workspace_capture_source_unlocked(
    repo: dict[str, Any],
) -> dict[str, object]:
    baseline = _require_current_evidence(
        repo.get("baseline"), "baseline"
    )
    source = _WorkspacePath(str(repo["path"])).resolve(strict=True)
    if not _recorded_path_matches(
        repo.get("path_identity"),
        repo.get("path"),
        source,
    ) and repo.get("path_identity") is not None:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SOURCE_MISMATCH",
            "repository source identity differs from controller state",
            details={"repository_id": repo.get("id")},
        )
    approved_profile = baseline.get("capability_profile")
    if not isinstance(approved_profile, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SOURCE_MISMATCH",
            "baseline has no approved capability profile",
            details={"repository_id": repo.get("id")},
        )
    filesystem_capabilities = approved_profile.get("filesystem")
    if not isinstance(filesystem_capabilities, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SOURCE_MISMATCH",
            "baseline has no approved filesystem capability facts",
            details={"repository_id": repo.get("id")},
        )
    first = _fingerprint_repo_once(
        source,
        filesystem_capabilities=filesystem_capabilities,
    )
    second = _fingerprint_repo_once(
        source,
        filesystem_capabilities=filesystem_capabilities,
    )
    if first.get("sha256") != second.get("sha256"):
        raise _v4_workspace_error(
            "SOURCE_WORKTREE_CHANGED",
            "source changed during read-only workspace planning",
            details={"repository_id": repo.get("id")},
        )
    approved_capability = baseline.get(
        "capability_profile_sha256"
    )
    if second.get("capability_profile_sha256") != approved_capability:
        raise _v4_workspace_error(
            "GIT_CAPABILITY_CHANGED",
            "source capabilities differ from the approved baseline",
            details={"repository_id": repo.get("id")},
        )
    base_sha = baseline.get("base_sha")
    if (
        not isinstance(base_sha, str)
        or _git_optional(
            source,
            "rev-parse",
            "--verify",
            f"{base_sha}^{{commit}}",
        )
        != base_sha
    ):
        raise _v4_workspace_error(
            "WORKSPACE_BASE_MISMATCH",
            "approved workspace base object is unavailable",
            details={"repository_id": repo.get("id")},
        )
    binding = {
        "repository_id": repo.get("id"),
        "source_path": str(source),
        "source_identity": _serializable_path_identity(source),
        "source_common_dir": str(_git_common_dir(source)),
        "source_common_dir_identity": (
            _serializable_path_identity(_git_common_dir(source))
        ),
        "base_branch": baseline.get("base_branch"),
        "base_sha": base_sha,
        "source_head_sha": second.get("head_sha"),
        "source_fingerprint_sha256": second.get("sha256"),
        "source_capability_profile_sha256": approved_capability,
        "source_filesystem_capabilities": filesystem_capabilities,
    }
    binding["source_binding_sha256"] = _v4_workspace_sha256(
        _V4_WORKSPACE_SOURCE_BINDING_DOMAIN, binding
    )
    return binding


def _v4_workspace_capture_source(
    repo: dict[str, Any],
) -> dict[str, object]:
    baseline = _require_current_evidence(
        repo.get("baseline"), "baseline"
    )
    profile = baseline.get("capability_profile")
    filesystem = (
        profile.get("filesystem")
        if isinstance(profile, dict)
        else None
    )
    if not isinstance(filesystem, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SOURCE_MISMATCH",
            "baseline has no approved filesystem capability facts",
            details={"repository_id": repo.get("id")},
        )
    _v4_workspace_seed_filesystem_facts(
        _WorkspacePath(str(repo["path"])), filesystem
    )
    with _v4_workspace_readonly_git():
        return _v4_workspace_capture_source_unlocked(repo)


def _v4_workspace_capture_sources(
    state_value: dict[str, Any],
    repository_ids: Sequence[str],
) -> list[dict[str, object]]:
    by_id = {
        str(repo.get("id")): repo
        for repo in state_value.get("repositories", [])
        if isinstance(repo, dict)
    }
    missing = sorted(set(repository_ids) - set(by_id))
    if missing:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_REPOSITORY_MISMATCH",
            "workspace effect references an unknown repository",
            details={"repository_ids": missing},
        )
    return [
        _v4_workspace_capture_source(by_id[repository_id])
        for repository_id in repository_ids
    ]


def _v4_workspace_normalize_override_map(
    value: _WorkspaceMapping[str, object] | None,
    repository_ids: Sequence[str],
    *,
    paths: bool,
) -> dict[str, str]:
    allowed = set(repository_ids)
    normalized: dict[str, str] = {}
    for repository_id, supplied in (value or {}).items():
        if repository_id not in allowed:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_REPOSITORY_MISMATCH",
                "workspace override targets an unselected repository",
                details={"repository_id": repository_id},
            )
        text = _v4_workspace_require_text(
            supplied, "workspace_override"
        )
        if paths:
            candidate = _WorkspacePath(text).expanduser()
            if not candidate.is_absolute():
                raise _v4_workspace_error(
                    "WORKSPACE_EFFECT_PATH_INVALID",
                    "workspace path overrides must be absolute",
                    details={"repository_id": repository_id},
                )
            text = str(candidate.resolve(strict=False))
        normalized[str(repository_id)] = text
    return {
        key: normalized[key]
        for key in sorted(normalized, key=lambda item: item.encode("utf-8"))
    }


def plan_v4_workspace_plan_effect(
    *,
    state_value: dict[str, Any],
    data_root: str | _WorkspacePath,
    task_dir: str | _WorkspacePath,
    repository_ids: Sequence[str] | None = None,
    branch_override: str | None = None,
    path_override: str | _WorkspacePath | None = None,
    branch_overrides: _WorkspaceMapping[str, object] | None = None,
    path_overrides: _WorkspaceMapping[str, object] | None = None,
) -> V4WorkspacePlanEffectPlan:
    """Build a read-only plan for claiming and recording a workspace plan."""

    if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SCHEMA_REQUIRED",
            "typed workspace effects require a schema-v4 task",
        )
    task_id = _v4_workspace_require_text(
        state_value.get("task_id"), "task_id"
    )
    revision = _v4_workspace_require_revision(
        state_value.get("revision")
    )
    resolved_data, resolved_task, state_path = (
        _v4_workspace_task_paths(task_id, data_root, task_dir)
    )
    configured_ids = {
        str(repo.get("id"))
        for repo in state_value.get("repositories", [])
        if isinstance(repo, dict)
    }
    selected_ids = tuple(
        sorted(
            (
                configured_ids
                if repository_ids is None
                else {
                    _v4_workspace_require_text(
                        item, "repository_id"
                    )
                    for item in repository_ids
                }
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if set(selected_ids) != configured_ids or not selected_ids:
        raise _v4_workspace_error(
            "INCOMPLETE_WORKSPACE_PLAN",
            "schema-v4 workspace plans must cover every repository",
            details={
                "required_repository_ids": sorted(configured_ids),
                "selected_repository_ids": list(selected_ids),
            },
        )
    route_binding = _v4_workspace_route_approval_binding(state_value)
    route_binding_sha = _v4_workspace_sha256(
        _V4_WORKSPACE_APPROVAL_BINDING_DOMAIN, route_binding
    )
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    branches = _v4_workspace_normalize_override_map(
        branch_overrides, selected_ids, paths=False
    )
    paths = _v4_workspace_normalize_override_map(
        path_overrides, selected_ids, paths=True
    )
    branch_value = (
        None
        if branch_override is None
        else _v4_workspace_require_text(
            branch_override, "branch_override"
        )
    )
    path_value = None
    if path_override is not None:
        if len(selected_ids) != 1:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_PATH_INVALID",
                "single path override requires exactly one repository",
            )
        supplied = _WorkspacePath(path_override).expanduser()
        if not supplied.is_absolute():
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_PATH_INVALID",
                "workspace path override must be absolute",
            )
        path_value = str(supplied.resolve(strict=False))
    if path_value is not None and paths:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PATH_INVALID",
            "single and per-repository path overrides cannot be combined",
        )
    source_bindings = _v4_workspace_capture_sources(
        state_value, selected_ids
    )
    bindings = {
        "mode": "plan",
        "data_root": str(resolved_data),
        "task_dir": str(resolved_task),
        "state_path": str(state_path),
        "artifact_directory": str(
            resolved_task / "workspace-plans"
        ),
        "route_binding": route_binding,
        "branch_override": branch_value,
        "path_override": path_value,
        "branch_overrides": branches,
        "path_overrides": paths,
        "source_repositories": source_bindings,
    }
    result = _v4_workspace_build_plan(
        "plan",
        task_id=task_id,
        task_revision=revision,
        workspace_generation=generation,
        repository_ids=selected_ids,
        approved_binding_sha256=route_binding_sha,
        bindings=bindings,
    )
    assert isinstance(result, V4WorkspacePlanEffectPlan)
    return result


def _v4_workspace_read_artifact_bytes(
    path: _WorkspacePath,
    expected_sha256: str,
) -> tuple[bytes, dict[str, object]]:
    if (
        not isinstance(expected_sha256, str)
        or not _V4_WORKSPACE_SHA256.fullmatch(expected_sha256)
    ):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace artifact digest is invalid",
        )
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan artifact cannot be read",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    actual = _workspace_hashlib.sha256(source).hexdigest()
    if actual != expected_sha256:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan artifact bytes changed",
            details={
                "path": str(path),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual,
            },
        )
    try:
        parsed = parse_semantic_json(source)
        if semantic_json_bytes(parsed) != source:
            raise ValueError("non-canonical semantic JSON")
    except Exception as exc:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan artifact is not canonical semantic JSON",
            details={
                "path": str(path),
                "cause_code": getattr(
                    exc, "code", type(exc).__name__
                ),
            },
        ) from None
    if not isinstance(parsed, dict):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan artifact must be an object",
        )
    return source, parsed


def _v4_workspace_validate_plan_artifact(
    evidence: dict[str, object],
    *,
    expected_sha256: str,
    expected_generation: int,
    expected_repository_ids: Sequence[str],
    authorization_plan_sha256: str | None = None,
) -> None:
    repositories = evidence.get("repositories")
    repository_ids = (
        [
            item.get("repository_id")
            for item in repositories
            if isinstance(item, dict)
        ]
        if isinstance(repositories, list)
        else []
    )
    authorization = evidence.get("authorization")
    mismatches = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        mismatches.append("schema_version")
    if evidence.get("strategy") != "worktree":
        mismatches.append("strategy")
    if evidence.get("workspace_generation") != expected_generation:
        mismatches.append("workspace_generation")
    if repository_ids != list(expected_repository_ids):
        mismatches.append("repository_ids")
    if not isinstance(authorization, dict):
        mismatches.append("authorization")
    else:
        if (
            authorization.get("schema")
            != _V4_WORKSPACE_PLAN_ARTIFACT_AUTHORIZATION_SCHEMA
        ):
            mismatches.append("authorization.schema")
        if authorization.get("mode") != "plan":
            mismatches.append("authorization.mode")
        if authorization.get("repository_ids") != list(
            expected_repository_ids
        ):
            mismatches.append("authorization.repository_ids")
        if (
            authorization_plan_sha256 is not None
            and authorization.get("effect_plan_sha256")
            != authorization_plan_sha256
        ):
            mismatches.append("authorization.effect_plan_sha256")
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan artifact differs from its exact authorization",
            details={
                "sha256": expected_sha256,
                "fields": sorted(mismatches),
            },
        )


def _v4_workspace_seed_evidence_filesystems_at(
    data_root: _WorkspacePath,
    task_dir: _WorkspacePath,
    evidence: dict[str, object],
) -> None:
    authorization = evidence.get("authorization")
    controller = (
        authorization.get("controller_filesystem_capabilities")
        if isinstance(authorization, dict)
        else None
    )
    if not isinstance(controller, dict):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace evidence has no controller filesystem facts",
        )
    for path in (
        data_root,
        task_dir,
        data_root / "workspace-registry.json",
    ):
        _v4_workspace_seed_filesystem_facts(path, controller)
    repositories = evidence.get("repositories")
    if not isinstance(repositories, list):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace evidence has no repository records",
        )
    for record in repositories:
        if not isinstance(record, dict):
            raise _v4_workspace_error(
                "WORKSPACE_PLAN_INVALID",
                "workspace evidence repository record is invalid",
            )
        capability = record.get("capability_profile")
        workspace_filesystem = (
            capability.get("filesystem")
            if isinstance(capability, dict)
            else None
        )
        source_filesystem = record.get(
            "source_filesystem_capabilities"
        )
        if not isinstance(workspace_filesystem, dict) or not isinstance(
            source_filesystem, dict
        ):
            raise _v4_workspace_error(
                "WORKSPACE_PLAN_INVALID",
                "workspace evidence has incomplete filesystem facts",
                details={
                    "repository_id": record.get("repository_id")
                },
            )
        _v4_workspace_seed_filesystem_facts(
            _WorkspacePath(str(record["path"])),
            workspace_filesystem,
        )
        _v4_workspace_seed_filesystem_facts(
            _WorkspacePath(str(record["source_path"])),
            source_filesystem,
        )


def _v4_workspace_seed_evidence_filesystems(
    plan: V4WorkspaceEffectPlan,
    evidence: dict[str, object],
) -> None:
    _v4_workspace_seed_evidence_filesystems_at(
        _WorkspacePath(str(plan.bindings["data_root"])),
        _WorkspacePath(str(plan.bindings["task_dir"])),
        evidence,
    )


def _v4_workspace_execution_plan_from_evidence(
    state_value: dict[str, Any],
    evidence: dict[str, object],
    repository_id: str,
) -> dict[str, object]:
    repositories = evidence.get("repositories")
    if not isinstance(repositories, list):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "approved workspace plan has no repository records",
        )
    record = next(
        (
            item
            for item in repositories
            if isinstance(item, dict)
            and item.get("repository_id") == repository_id
        ),
        None,
    )
    repo = next(
        (
            item
            for item in state_value.get("repositories", [])
            if isinstance(item, dict)
            and item.get("id") == repository_id
        ),
        None,
    )
    if not isinstance(record, dict) or not isinstance(repo, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_REPOSITORY_MISMATCH",
            "approved plan does not bind the requested repository",
            details={"repository_id": repository_id},
        )
    baseline = _require_current_evidence(
        repo.get("baseline"), "baseline"
    )
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    mismatches = []
    for field, expected in (
        ("source_path", str(_WorkspacePath(repo["path"]).resolve())),
        ("base_sha", baseline.get("base_sha")),
        ("strategy", "worktree"),
    ):
        if record.get(field) != expected:
            mismatches.append(field)
    if not isinstance(record.get("capability_profile"), dict):
        mismatches.append("capability_profile")
    if (
        (record.get("capability_profile") or {}).get("sha256")
        != record.get("capability_profile_sha256")
    ):
        mismatches.append("capability_profile_sha256")
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_MISMATCH",
            "approved repository workspace plan is stale",
            details={
                "repository_id": repository_id,
                "fields": sorted(mismatches),
            },
        )
    current_workspace = repo.get("workspace") or {}
    previously_recorded = bool(
        current_workspace.get("ready")
        and _recorded_path_matches(
            current_workspace.get("path_identity"),
            current_workspace.get("path"),
            _WorkspacePath(str(record["path"])),
        )
        and current_workspace.get("branch") == record.get("branch")
        and current_workspace.get("base_sha") == record.get("base_sha")
        and current_workspace.get("workspace_generation")
        == generation
    )
    return {
        **_workspace_copy.deepcopy(record),
        "owner_task_id": state_value["task_id"],
        "workspace_generation": generation,
        "previously_recorded": previously_recorded,
    }


def plan_v4_workspace_execute_effect(
    *,
    state_value: dict[str, Any],
    data_root: str | _WorkspacePath,
    task_dir: str | _WorkspacePath,
    repository_ids: Sequence[str] | None = None,
) -> V4WorkspaceExecuteEffectPlan:
    """Build the one catalog-fixed, all-repository execution effect."""

    if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_SCHEMA_REQUIRED",
            "typed workspace effects require a schema-v4 task",
        )
    task_id = _v4_workspace_require_text(
        state_value.get("task_id"), "task_id"
    )
    revision = _v4_workspace_require_revision(
        state_value.get("revision")
    )
    resolved_data, resolved_task, state_path = (
        _v4_workspace_task_paths(task_id, data_root, task_dir)
    )
    seed_artifact = _latest_artifact(
        state_value, "workspace-plan"
    )
    if not isinstance(seed_artifact, dict):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "execute effect requires a workspace plan artifact",
        )
    artifact_path = _WorkspacePath(
        str(seed_artifact.get("path"))
    ).resolve(strict=True)
    _source, evidence = _v4_workspace_read_artifact_bytes(
        artifact_path, str(seed_artifact.get("sha256"))
    )
    _v4_workspace_seed_evidence_filesystems_at(
        resolved_data, resolved_task, evidence
    )
    approved_binding, artifact = _v4_workspace_approved_plan_binding(
        state_value
    )
    approved_binding_sha = _v4_workspace_sha256(
        _V4_WORKSPACE_APPROVAL_BINDING_DOMAIN, approved_binding
    )
    if (
        artifact.get("artifact_id")
        != seed_artifact.get("artifact_id")
        or artifact.get("sha256") != seed_artifact.get("sha256")
        or artifact.get("path") != seed_artifact.get("path")
    ):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace plan changed during read-only planning",
        )
    expected_path = (
        resolved_task
        / "workspace-plans"
        / f"{artifact['sha256']}.json"
    ).resolve(strict=False)
    if not _same_path(artifact_path, expected_path):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "approved workspace plan path is not digest-derived",
            details={
                "path": str(artifact_path),
                "expected_path": str(expected_path),
            },
        )
    configured_ids = tuple(
        sorted(
            {
                str(repo.get("id"))
                for repo in state_value.get("repositories", [])
                if isinstance(repo, dict)
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    selected_ids = tuple(
        sorted(
            (
                configured_ids
                if repository_ids is None
                else {
                    _v4_workspace_require_text(
                        item, "repository_id"
                    )
                    for item in repository_ids
                }
            ),
            key=lambda item: item.encode("utf-8"),
        )
    )
    if not configured_ids or selected_ids != configured_ids:
        raise _v4_workspace_error(
            "INCOMPLETE_WORKSPACE_PLAN",
            "the catalog-fixed execute effect must cover every repository",
            details={
                "required_repository_ids": list(configured_ids),
                "selected_repository_ids": list(selected_ids),
            },
        )
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    _v4_workspace_validate_plan_artifact(
        evidence,
        expected_sha256=str(artifact["sha256"]),
        expected_generation=generation,
        expected_repository_ids=configured_ids,
    )
    execution_plans = [
        _v4_workspace_execution_plan_from_evidence(
            state_value, evidence, repository_id
        )
        for repository_id in configured_ids
    ]
    source_bindings = _v4_workspace_capture_sources(
        state_value, configured_ids
    )
    evidence_by_id = {
        str(item["repository_id"]): item
        for item in evidence["repositories"]
    }
    drifted = [
        str(source["repository_id"])
        for source in source_bindings
        if source["source_binding_sha256"]
        != evidence_by_id[str(source["repository_id"])].get(
            "source_binding_sha256"
        )
    ]
    if drifted:
        raise _v4_workspace_error(
            "SOURCE_WORKTREE_CHANGED",
            "a source differs from the plan-time fingerprint",
            details={"repository_ids": drifted},
        )
    bindings = {
        "mode": "execute",
        "data_root": str(resolved_data),
        "task_dir": str(resolved_task),
        "state_path": str(state_path),
        "approved_workspace": approved_binding,
        "approved_artifact_path": str(artifact_path),
        "approved_artifact_sha256": artifact.get("sha256"),
        "approved_repository_ids": list(configured_ids),
        "repository_plans": execution_plans,
        "source_repositories": source_bindings,
    }
    result = _v4_workspace_build_plan(
        "execute",
        task_id=task_id,
        task_revision=revision,
        workspace_generation=generation,
        repository_ids=configured_ids,
        approved_binding_sha256=approved_binding_sha,
        bindings=bindings,
    )
    assert isinstance(result, V4WorkspaceExecuteEffectPlan)
    return result


def v4_workspace_effect_safe_inputs(
    plan: V4WorkspaceEffectPlan,
) -> dict[str, object]:
    """Return only the durable semantic summary allowed in the journal."""

    if type(plan) not in set(_V4_WORKSPACE_PLAN_TYPES.values()):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "safe inputs require an exact typed workspace plan",
        )
    return {
        "workspace_plan_schema": _V4_WORKSPACE_EFFECT_PLAN_SCHEMA,
        "workspace_action": plan.action,
        "workspace_mode": str(plan.bindings["mode"]),
        "workspace_expected_effect_id": plan.expected_effect_id,
        "workspace_effect_plan_sha256": plan.semantic_sha256,
        "workspace_repository_ids": list(plan.repository_ids),
        "approved_binding_sha256": (
            plan.approved_binding_sha256
        ),
    }


def v4_workspace_effect_scopes(
    plan: V4WorkspaceEffectPlan,
) -> dict[str, list[str]]:
    """Return exact all-repository scopes for the fixed catalog effect."""

    if type(plan) not in set(_V4_WORKSPACE_PLAN_TYPES.values()):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "scopes require an exact typed workspace plan",
        )
    bindings = plan.bindings
    paths = {
        str(item["source_path"])
        for item in bindings["source_repositories"]
    }
    paths.add(
        str(
            _WorkspacePath(str(bindings["data_root"]))
            / "workspace-registry.json"
        )
    )
    if plan.action == "plan":
        paths.add(str(bindings["artifact_directory"]))
        paths.add(
            str(
                _WorkspacePath(str(bindings["data_root"]))
                / "workspaces"
                / plan.task_id
                / (
                    f"r{plan.workspace_generation}"
                    if plan.workspace_generation
                    else ""
                )
            )
        )
        if bindings["path_override"] is not None:
            paths.add(str(bindings["path_override"]))
        paths.update(
            str(item)
            for item in bindings["path_overrides"].values()
        )
    else:
        paths.add(str(bindings["approved_artifact_path"]))
        paths.update(
            str(item["path"])
            for item in bindings["repository_plans"]
        )
    return normalize_scopes(
        {
            "repository_ids": list(plan.repository_ids),
            "node_ids": [],
            "worktree_ids": (
                []
                if plan.action == "plan"
                else [
                    (
                        "workspace:"
                        + plan.task_id
                        + ":"
                        + str(plan.workspace_generation)
                        + ":"
                        + repository_id
                    )
                    for repository_id in plan.repository_ids
                ]
            ),
            "lease_ids": [],
            "paths": sorted(
                paths, key=lambda item: item.encode("utf-8")
            ),
            "external_resources": [],
        }
    )


def _v4_workspace_validate_transaction_permit(
    plan: V4WorkspaceEffectPlan,
    permit: object,
) -> ActionDispatchPlan:
    """Accept only Transaction's exact active callback-stack context."""

    if type(permit) is not WorkflowActionDispatchContext:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TRANSACTION_PERMIT_REQUIRED",
            "workspace dispatch requires a transaction context",
        )
    verifier = globals().get(
        "verify_active_v4_workflow_action_dispatch_context"
    )
    if not callable(verifier):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "transaction active-dispatch verifier is unavailable",
        )
    try:
        verifier(permit)
    except Exception as exc:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TRANSACTION_PERMIT_INACTIVE",
            "transaction context is forged, copied, replayed, or inactive",
            details={
                "cause_code": getattr(
                    exc,
                    "code",
                    "WORKFLOW_ACTION_TRANSACTION_DISPATCH_INACTIVE",
                )
            },
        ) from None
    transaction_plan = permit.plan
    mismatches = []
    if type(transaction_plan) is not ActionDispatchPlan:
        mismatches.append("plan_type")
    else:
        if transaction_plan.task_id != plan.task_id:
            mismatches.append("task_id")
        if transaction_plan.effect_id != plan.expected_effect_id:
            mismatches.append("effect_id")
        if (
            transaction_plan.safe_inputs
            != v4_workspace_effect_safe_inputs(plan)
        ):
            mismatches.append("safe_inputs")
        for field, value in (
            (
                "journal_record_sha256",
                transaction_plan.journal_record_sha256,
            ),
            (
                "index_record_sha256",
                transaction_plan.index_record_sha256,
            ),
        ):
            if (
                not isinstance(value, str)
                or not _V4_WORKSPACE_SHA256.fullmatch(value)
            ):
                mismatches.append(field)
    if permit.effect_kind != "filesystem":
        mismatches.append("effect_kind")
    if permit.settlement != "synchronous-quiescence":
        mismatches.append("settlement")
    if permit.scopes != v4_workspace_effect_scopes(plan):
        mismatches.append("scopes")
    if (
        not isinstance(permit.catalog_contract_sha256, str)
        or not _V4_WORKSPACE_SHA256.fullmatch(
            permit.catalog_contract_sha256
        )
    ):
        mismatches.append("catalog_contract_sha256")
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TRANSACTION_PERMIT_MISMATCH",
            "transaction dispatch context differs from the typed plan",
            details={"fields": sorted(set(mismatches))},
        )
    assert isinstance(transaction_plan, ActionDispatchPlan)
    return transaction_plan


def _v4_workspace_validate_observe_context(
    plan: V4WorkspaceEffectPlan,
    context: object,
) -> _WorkspaceMapping[str, object]:
    """Accept only Transaction's exact active observe-only context."""

    if type(context) is not WorkflowActionObserveContext:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVE_CONTEXT_REQUIRED",
            "observation requires Transaction's exact observe-only context",
        )
    verifier = globals().get(
        "verify_active_v4_workflow_action_observe_context"
    )
    if not callable(verifier):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "transaction active-observe verifier is unavailable",
        )
    try:
        facts = verifier(context)
    except Exception as exc:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVE_CONTEXT_INACTIVE",
            "observe context is forged, copied, replayed, or inactive",
            details={
                "cause_code": getattr(
                    exc,
                    "code",
                    "WORKFLOW_ACTION_TRANSACTION_OBSERVE_INACTIVE",
                )
            },
        ) from None
    if not isinstance(facts, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVE_CONTEXT_MISMATCH",
            "transaction observe verifier returned invalid facts",
            details={"fields": ["facts"]},
        )
    mismatches = []
    if facts.get("task_id") != plan.task_id:
        mismatches.append("task_id")
    if facts.get("effect_id") != plan.expected_effect_id:
        mismatches.append("effect_id")
    if facts.get("safe_inputs") != v4_workspace_effect_safe_inputs(
        plan
    ):
        mismatches.append("safe_inputs")
    if facts.get("scopes") != v4_workspace_effect_scopes(plan):
        mismatches.append("scopes")
    if facts.get("effect_kind") != "filesystem":
        mismatches.append("effect_kind")
    if facts.get("settlement") != "synchronous-quiescence":
        mismatches.append("settlement")
    for field in (
        "execution_id",
        "effect_id",
        "claim_id",
        "attempt_id",
    ):
        value = facts.get(field)
        if not isinstance(value, str) or not value:
            mismatches.append(field)
    for field in (
        "journal_record_sha256",
        "index_record_sha256",
        "containment_record_sha256",
        "catalog_contract_sha256",
        "observe_context_sha256",
    ):
        value = facts.get(field)
        if (
            not isinstance(value, str)
            or not _V4_WORKSPACE_SHA256.fullmatch(value)
        ):
            mismatches.append(field)
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVE_CONTEXT_MISMATCH",
            "observe context differs from the immutable workspace plan",
            details={"fields": sorted(set(mismatches))},
        )
    return facts


@_workspace_dataclass(frozen=True)
class V4WorkspaceEffectObservation:
    action: str
    plan_sha256: str
    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    result: _WorkspaceMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if self.action not in _V4_WORKSPACE_ACTIONS:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_OBSERVATION_INVALID",
                "workspace observation action is invalid",
            )
        for field in (
            "plan_sha256",
            "task_id",
            "execution_id",
            "effect_id",
            "claim_id",
            "attempt_id",
        ):
            _v4_workspace_require_text(getattr(self, field), field)
        public = _v4_workspace_public(dict(self.result))
        assert isinstance(public, dict)
        _v4_workspace_reject_secrets(public)
        core = {
            "schema": _V4_WORKSPACE_EFFECT_OBSERVATION_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "result": public,
        }
        expected = _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_OBSERVATION_DOMAIN, core
        )
        if expected != self.semantic_sha256:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_OBSERVATION_DIGEST_MISMATCH",
                "workspace dispatch observation digest is invalid",
            )
        object.__setattr__(
            self, "result", _v4_workspace_freeze(public)
        )


def _v4_workspace_build_observation(
    plan: V4WorkspaceEffectPlan,
    transaction_plan: ActionDispatchPlan,
    result: _WorkspaceMapping[str, object],
) -> V4WorkspaceEffectObservation:
    public = _v4_workspace_public(dict(result))
    assert isinstance(public, dict)
    core = {
        "schema": _V4_WORKSPACE_EFFECT_OBSERVATION_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "task_id": transaction_plan.task_id,
        "execution_id": transaction_plan.execution_id,
        "effect_id": transaction_plan.effect_id,
        "claim_id": transaction_plan.claim_id,
        "attempt_id": transaction_plan.attempt_id,
        "result": public,
    }
    return V4WorkspaceEffectObservation(
        plan.action,
        plan.semantic_sha256,
        transaction_plan.task_id,
        transaction_plan.execution_id,
        transaction_plan.effect_id,
        transaction_plan.claim_id,
        transaction_plan.attempt_id,
        public,
        _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_OBSERVATION_DOMAIN, core
        ),
    )


def _v4_workspace_load_bound_state(
    plan: V4WorkspaceEffectPlan,
) -> dict[str, Any]:
    bindings = plan.bindings
    state_path = _WorkspacePath(str(bindings["state_path"]))
    if not _same_path(
        state_path,
        _WorkspacePath(str(bindings["task_dir"])) / "state.json",
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_STATE_MISMATCH",
            "typed plan state path is outside the bound task directory",
        )
    try:
        state_value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_STATE_UNAVAILABLE",
            "durable task state cannot be revalidated",
            details={"path": str(state_path), "error": str(exc)},
        ) from exc
    if not isinstance(state_value, dict):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_STATE_UNAVAILABLE",
            "durable task state must be an object",
        )
    generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    configured_ids = tuple(
        sorted(
            {
                str(repo.get("id"))
                for repo in state_value.get("repositories", [])
                if isinstance(repo, dict)
            },
            key=lambda item: item.encode("utf-8"),
        )
    )
    mismatches = []
    if state_value.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if state_value.get("task_id") != plan.task_id:
        mismatches.append("task_id")
    if state_value.get("revision") != plan.task_revision:
        mismatches.append("task_revision")
    if generation != plan.workspace_generation:
        mismatches.append("workspace_generation")
    if configured_ids != plan.repository_ids:
        mismatches.append("repository_ids")
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_STATE_MISMATCH",
            "durable task state changed after effect planning",
            details={"fields": sorted(mismatches)},
        )
    current_sources = _v4_workspace_capture_sources(
        state_value, plan.repository_ids
    )
    if current_sources != _v4_workspace_thaw(
        bindings["source_repositories"]
    ):
        raise _v4_workspace_error(
            "SOURCE_WORKTREE_CHANGED",
            "source fingerprint changed after workspace effect planning",
        )
    if plan.action == "plan":
        current_binding = _v4_workspace_route_approval_binding(
            state_value
        )
    else:
        current_binding, _artifact = (
            _v4_workspace_approved_plan_binding(state_value)
        )
    current_binding_sha = _v4_workspace_sha256(
        _V4_WORKSPACE_APPROVAL_BINDING_DOMAIN, current_binding
    )
    if (
        current_binding_sha != plan.approved_binding_sha256
        or current_binding
        != _v4_workspace_thaw(
            (
                bindings["route_binding"]
                if plan.action == "plan"
                else bindings["approved_workspace"]
            )
        )
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_APPROVAL_MISMATCH",
            "approved binding changed after effect planning",
        )
    return state_value


def _v4_workspace_evidence_authorization(
    plan: V4WorkspacePlanEffectPlan,
    controller_filesystem_capabilities: dict[str, Any],
) -> dict[str, object]:
    return {
        "schema": (
            _V4_WORKSPACE_PLAN_ARTIFACT_AUTHORIZATION_SCHEMA
        ),
        "mode": "plan",
        "expected_effect_id": plan.expected_effect_id,
        "task_revision": plan.task_revision,
        "workspace_generation": plan.workspace_generation,
        "repository_ids": list(plan.repository_ids),
        "effect_plan_sha256": plan.semantic_sha256,
        "approved_binding_sha256": (
            plan.approved_binding_sha256
        ),
        "controller_filesystem_capabilities": (
            controller_filesystem_capabilities
        ),
    }


def dispatch_v4_workspace_plan_effect(
    plan: V4WorkspacePlanEffectPlan,
    permit: object,
) -> V4WorkspaceEffectObservation:
    """Claim ownership and write one digest-addressed plan artifact."""

    if type(plan) is not V4WorkspacePlanEffectPlan:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "plan dispatch requires its exact typed plan",
        )
    transaction_plan = _v4_workspace_validate_transaction_permit(
        plan, permit
    )
    current = _v4_workspace_load_bound_state(plan)
    bindings = plan.bindings
    by_id = {
        str(repo["id"]): repo for repo in current["repositories"]
    }
    selected = [by_id[item] for item in plan.repository_ids]
    low_level_plans = _workspace_plan(
        current,
        selected,
        _WorkspacePath(str(bindings["data_root"])),
        (
            None
            if bindings["branch_override"] is None
            else str(bindings["branch_override"])
        ),
        (
            None
            if bindings["path_override"] is None
            else str(bindings["path_override"])
        ),
        {
            str(key): str(value)
            for key, value in bindings["branch_overrides"].items()
        },
        {
            str(key): str(value)
            for key, value in bindings["path_overrides"].items()
        },
    )
    low_by_id = {
        str(item["repository_id"]): item
        for item in low_level_plans
    }
    source_by_id = {
        str(item["repository_id"]): item
        for item in bindings["source_repositories"]
    }
    evidence = _workspace_plan_evidence(current, low_level_plans)
    evidence["repositories"].sort(
        key=lambda item: str(item["repository_id"]).encode("utf-8")
    )
    for item in evidence["repositories"]:
        repository_id = str(item["repository_id"])
        item["capability_profile"] = _workspace_copy.deepcopy(
            low_by_id[repository_id]["capability_profile"]
        )
        item["source_binding_sha256"] = source_by_id[
            repository_id
        ]["source_binding_sha256"]
        item["source_fingerprint_sha256"] = source_by_id[
            repository_id
        ]["source_fingerprint_sha256"]
        item["source_filesystem_capabilities"] = (
            _v4_workspace_thaw(
                source_by_id[repository_id][
                    "source_filesystem_capabilities"
                ]
            )
        )
    evidence["authorization"] = _v4_workspace_evidence_authorization(
        plan,
        _probe_worktree_capabilities(
            _WorkspacePath(str(bindings["task_dir"]))
        ),
    )
    evidence_bytes = semantic_json_bytes(evidence)
    evidence_sha = _workspace_hashlib.sha256(
        evidence_bytes
    ).hexdigest()
    claims = _claim_workspace_plan(
        _WorkspacePath(str(bindings["data_root"])),
        current,
        evidence_sha,
        low_level_plans,
    )
    artifact_path = (
        _WorkspacePath(str(bindings["artifact_directory"]))
        / f"{evidence_sha}.json"
    )
    expected_path = (
        _WorkspacePath(str(bindings["task_dir"]))
        / "workspace-plans"
        / f"{evidence_sha}.json"
    )
    if not _same_path(artifact_path, expected_path):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PATH_MISMATCH",
            "workspace artifact path is not digest-derived",
        )
    _atomic_write_bytes(artifact_path, evidence_bytes)
    result = {
        "evidence_sha256": evidence_sha,
        "artifact_path": str(artifact_path),
        "artifact_path_identity": _serializable_path_identity(
            artifact_path
        ),
        "artifact_size": len(evidence_bytes),
        "registry_path": str(
            _WorkspacePath(str(bindings["data_root"]))
            / "workspace-registry.json"
        ),
        "claims": [
            {
                "repository_id": repository_id,
                "claim_id": claims[repository_id]["claim_id"],
            }
            for repository_id in plan.repository_ids
        ],
    }
    return _v4_workspace_build_observation(
        plan, transaction_plan, result
    )


def _v4_workspace_load_execute_evidence(
    plan: V4WorkspaceExecuteEffectPlan,
) -> dict[str, object]:
    bindings = plan.bindings
    artifact_path = _WorkspacePath(
        str(bindings["approved_artifact_path"])
    )
    _source, evidence = _v4_workspace_read_artifact_bytes(
        artifact_path, str(bindings["approved_artifact_sha256"])
    )
    _v4_workspace_seed_evidence_filesystems(plan, evidence)
    _v4_workspace_validate_plan_artifact(
        evidence,
        expected_sha256=str(
            bindings["approved_artifact_sha256"]
        ),
        expected_generation=plan.workspace_generation,
        expected_repository_ids=plan.repository_ids,
    )
    return evidence


def dispatch_v4_workspace_execute_effect(
    plan: V4WorkspaceExecuteEffectPlan,
    permit: object,
) -> V4WorkspaceEffectObservation:
    """Materialize every configured repository in canonical order."""

    if type(plan) is not V4WorkspaceExecuteEffectPlan:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "execute dispatch requires its exact typed plan",
        )
    transaction_plan = _v4_workspace_validate_transaction_permit(
        plan, permit
    )
    current = _v4_workspace_load_bound_state(plan)
    evidence = _v4_workspace_load_execute_evidence(plan)
    bindings = plan.bindings
    evidence_sha = str(bindings["approved_artifact_sha256"])
    low_level_plans = [
        _workspace_copy.deepcopy(
            _v4_workspace_thaw(item)
        )
        for item in bindings["repository_plans"]
    ]
    if [
        item["repository_id"] for item in low_level_plans
    ] != list(plan.repository_ids):
        raise _v4_workspace_error(
            "INCOMPLETE_WORKSPACE_PLAN",
            "execute plan lost its canonical all-repository order",
        )
    evidence_by_id = {
        str(item["repository_id"]): item
        for item in evidence["repositories"]
    }
    for item in low_level_plans:
        if (
            item["repository_id"] not in evidence_by_id
            or item["path"]
            != evidence_by_id[item["repository_id"]].get("path")
            or item["branch"]
            != evidence_by_id[item["repository_id"]].get("branch")
            or item["base_sha"]
            != evidence_by_id[item["repository_id"]].get("base_sha")
        ):
            raise _v4_workspace_error(
                "WORKSPACE_PLAN_MISMATCH",
                "execute plan differs from approved artifact",
                details={"repository_id": item["repository_id"]},
            )
    _claim_workspace_plan(
        _WorkspacePath(str(bindings["data_root"])),
        current,
        evidence_sha,
        low_level_plans,
    )
    outcomes: list[dict[str, object]] = []
    for item in low_level_plans:
        # A thrown exception deliberately prevents a typed observation for the
        # entire fixed effect. Transaction will quarantine any partial result.
        outcomes.append(_execute_worktree(item))
    return _v4_workspace_build_observation(
        plan,
        transaction_plan,
        {"outcomes": outcomes},
    )


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


def _assert_workspace_plan_claim(plan: dict[str, Any]) -> None:
    receipt = plan.get("workspace_claim") or {}
    registry_path_value = receipt.get("registry_path")
    claim_id = receipt.get("claim_id")
    if not registry_path_value or not claim_id:
        raise FlowError(
            "WORKSPACE_OWNERSHIP_CONFLICT",
            "workspace plan has no durable ownership receipt",
            details={"repository_id": plan.get("repository_id")},
        )
    registry_path = Path(str(registry_path_value))
    if not _recorded_path_matches(
        receipt.get("registry_identity"), registry_path_value, registry_path
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry path identity changed",
            details={"path": str(registry_path)},
        )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry cannot be revalidated",
            details={"path": str(registry_path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != SCHEMA_VERSION
        or not isinstance(registry.get("claims"), list)
    ):
        raise FlowError(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has an invalid structure",
            details={"path": str(registry_path)},
        )
    _assert_supported_evidence_versions(registry)
    _require_current_evidence(registry, "workspace registry")
    claim = next(
        (
            item
            for item in registry.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    _require_current_evidence(claim, "workspace ownership claim")
    destination = Path(plan["path"])
    source = Path(plan["source_path"])
    if (
        not claim
        or claim.get("task_id") != plan.get("owner_task_id")
        or claim.get("repository_id") != plan.get("repository_id")
        or not _recorded_path_matches(
            claim.get("path_identity"), claim.get("path"), destination
        )
        or not _recorded_path_matches(
            claim.get("source_identity"), claim.get("source_path"), source
        )
        or claim.get("branch_ref") != plan.get("branch_ref")
        or claim.get("planned_ref_oid") != plan.get("planned_ref_oid")
        or claim.get("ref_case_sensitive")
        != plan.get("ref_case_sensitive")
        or claim.get("ref_unicode_normalization_distinct")
        != plan.get("ref_unicode_normalization_distinct")
        or claim.get("plan_sha256") != receipt.get("plan_sha256")
    ):
        raise FlowError(
            "WORKSPACE_OWNERSHIP_CONFLICT",
            "workspace ownership claim changed after plan approval",
            details={
                "repository_id": plan.get("repository_id"),
                "claim_id": claim_id,
                "registry_path": str(registry_path),
            },
        )


def _workspace_outcome(
    plan: dict[str, Any],
    *,
    created: bool,
    head_sha: str,
    recovered_unrecorded: bool = False,
) -> dict[str, Any]:
    destination = Path(plan["path"]).resolve(strict=True)
    fingerprint = _fingerprint_repo(destination)
    if fingerprint["capability_profile_sha256"] != plan.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "WORKSPACE_VERIFY_FAILED",
            "materialized worktree capability profile differs from the approved plan",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "capability_profile_sha256"
                ),
                "actual_capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
            },
        )
    return {
        **plan,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": True,
        "created": created,
        "head_sha": head_sha,
        "recovered_unrecorded": recovered_unrecorded,
        "path_identity": _serializable_path_identity(destination),
        "source_identity": _serializable_path_identity(
            Path(plan["source_path"])
        ),
        "capability_profile": fingerprint["capability_profile"],
        "capability_profile_sha256": fingerprint[
            "capability_profile_sha256"
        ],
        "fingerprint_sha256": fingerprint["sha256"],
        "tracked_worktree_manifest_sha256": fingerprint[
            "tracked_worktree_manifest_sha256"
        ],
    }


def _execute_worktree(plan: dict[str, Any]) -> dict[str, Any]:
    _require_current_evidence(plan, "workspace plan")
    source = Path(plan["source_path"]).resolve(strict=True)
    if not _recorded_path_matches(
        plan.get("source_identity"), plan.get("source_path"), source
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace plan source identity changed before mutation",
            details={"repository_id": plan.get("repository_id")},
        )
    _assert_evidence_supported(source)
    _assert_tree_checkout_supported(source, plan["base_sha"])
    destination = Path(plan["path"]).resolve(strict=False)
    if not _recorded_path_matches(
        plan.get("path_identity"), plan.get("path"), destination
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace destination identity changed before mutation",
            details={"repository_id": plan.get("repository_id")},
        )
    current_source_profile = _git_capability_profile(source)
    if current_source_profile["sha256"] != plan.get(
        "source_capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "source repository capabilities changed after workspace approval",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "source_capability_profile_sha256"
                ),
                "current_capability_profile_sha256": (
                    current_source_profile["sha256"]
                ),
            },
        )
    current_workspace_profile = _git_capability_profile(source, destination)
    if current_workspace_profile["sha256"] != plan.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "workspace filesystem capabilities changed after approval",
            details={
                "repository_id": plan.get("repository_id"),
                "planned_capability_profile_sha256": plan.get(
                    "capability_profile_sha256"
                ),
                "current_capability_profile_sha256": (
                    current_workspace_profile["sha256"]
                ),
            },
        )
    if (
        _run(
            ["git", "-C", str(source), "cat-file", "-e", f"{plan['base_sha']}^{{commit}}"],
            check=False,
        ).returncode
        != 0
    ):
        raise FlowError(
            "WORKSPACE_BASE_MISMATCH",
            "approved workspace base object is no longer available",
            details={
                "repository_id": plan.get("repository_id"),
                "base_sha": plan.get("base_sha"),
            },
        )
    branch = plan["branch"]
    branch_ref = plan.get("branch_ref") or f"refs/heads/{branch}"
    if branch_ref != f"refs/heads/{branch}":
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace branch and full ref identity disagree",
            details={"branch": branch, "branch_ref": branch_ref},
        )
    previously_recorded = bool(plan.get("previously_recorded"))
    current_branch_state = _branch_ref_state(source, branch, [])
    current_ref_oid = current_branch_state["planned_ref_oid"]
    if (
        (
            not previously_recorded
            and current_ref_oid != plan.get("planned_ref_oid")
        )
        or current_branch_state["branch_ref"] != branch_ref
        or current_branch_state["ref_case_sensitive"]
        != plan.get("ref_case_sensitive")
        or current_branch_state["ref_unicode_normalization_distinct"]
        != plan.get("ref_unicode_normalization_distinct")
        or not _path_identity_equal(
            current_branch_state["git_common_dir_identity"],
            plan.get("source_common_dir_identity"),
        )
    ):
        raise FlowError(
            "WORKSPACE_PLAN_MISMATCH",
            "workspace branch or ref-storage identity changed after plan approval",
            details={
                "branch_ref": branch_ref,
                "planned_ref_oid": plan.get("planned_ref_oid"),
                "current_ref_oid": current_ref_oid,
                "planned_ref_case_sensitive": plan.get(
                    "ref_case_sensitive"
                ),
                "current_ref_case_sensitive": current_branch_state[
                    "ref_case_sensitive"
                ],
            },
        )
    _assert_workspace_plan_claim(plan)
    registry_path = Path(
        str((plan.get("workspace_claim") or {}).get("registry_path"))
    )
    managed_destination = _is_within(destination, registry_path.parent)
    entries = _worktree_entries(source)
    branch_entry = next((entry for entry in entries if entry.get("branch") == branch_ref), None)
    destination_entry = next(
        (
            entry
            for entry in entries
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        actual_branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        actual_head = _git_optional(destination, "rev-parse", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _same_path(
                    _git_common_dir(destination), _git_common_dir(source)
                )
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
        unrecorded_is_clean = status_available and not status_porcelain
        if (
            not root
            or not _same_path(Path(root), destination)
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
        if managed_destination:
            _set_private_permissions(destination, 0o700)
        return _workspace_outcome(
            plan,
            created=False,
            head_sha=actual_head,
            recovered_unrecorded=not previously_recorded,
        )
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
    if managed_destination:
        _ensure_private_dir(destination.parent)
    else:
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
        _git_mutating(
            source,
            "-c",
            f"core.hooksPath={os.devnull}",
            "worktree",
            "add",
            str(destination),
            branch,
        )
    else:
        _git_mutating(
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
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if (
        not actual_root
        or not _same_path(Path(actual_root), destination)
        or actual_branch != branch
        or actual_head != plan["base_sha"]
        or not _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
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
    if managed_destination:
        _set_private_permissions(destination, 0o700)
    return _workspace_outcome(
        plan, created=True, head_sha=actual_head
    )


def _v4_workspace_registry_claims(
    plan: V4WorkspaceEffectPlan,
    *,
    evidence_sha256: str,
    evidence: dict[str, object],
) -> dict[str, dict[str, object]]:
    """Read and verify the exact all-repository ownership claim set."""

    data_root = _WorkspacePath(str(plan.bindings["data_root"]))
    registry_path = data_root / "workspace-registry.json"
    if registry_path.is_symlink():
        raise _v4_workspace_error(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace registry cannot be a symbolic link",
            details={"path": str(registry_path)},
        )
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _v4_workspace_error(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry cannot be revalidated",
            details={"path": str(registry_path), "error": str(exc)},
        ) from exc
    if (
        not isinstance(registry, dict)
        or registry.get("schema_version") != SCHEMA_VERSION
        or not isinstance(registry.get("claims"), list)
    ):
        raise _v4_workspace_error(
            "WORKSPACE_REGISTRY_INVALID",
            "workspace ownership registry has invalid structure",
        )
    _assert_supported_evidence_versions(registry)
    _require_current_evidence(registry, "workspace registry")
    evidence_repositories = evidence.get("repositories")
    if not isinstance(evidence_repositories, list):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "workspace evidence lost repository records",
        )
    evidence_by_id = {
        str(item["repository_id"]): item
        for item in evidence_repositories
        if isinstance(item, dict)
        and isinstance(item.get("repository_id"), str)
    }
    selected: dict[str, dict[str, object]] = {}
    seen_claim_ids: set[str] = set()
    for repository_id in plan.repository_ids:
        record = evidence_by_id.get(repository_id)
        if not isinstance(record, dict):
            raise _v4_workspace_error(
                "WORKSPACE_PLAN_INVALID",
                "workspace evidence does not cover every repository",
                details={"repository_id": repository_id},
            )
        matches = []
        for candidate in registry["claims"]:
            if not isinstance(candidate, dict):
                continue
            try:
                _require_current_evidence(
                    candidate, "workspace ownership claim"
                )
            except FlowError:
                continue
            source = _WorkspacePath(str(record.get("source_path")))
            destination = _WorkspacePath(str(record.get("path")))
            common = _WorkspacePath(
                str(record.get("source_common_dir"))
            )
            if (
                candidate.get("task_id") == plan.task_id
                and candidate.get("repository_id") == repository_id
                and candidate.get("workspace_generation")
                == plan.workspace_generation
                and candidate.get("plan_sha256")
                == evidence_sha256
                and _recorded_path_matches(
                    candidate.get("source_identity"),
                    candidate.get("source_path"),
                    source,
                )
                and _recorded_path_matches(
                    candidate.get("path_identity"),
                    candidate.get("path"),
                    destination,
                )
                and _recorded_path_matches(
                    candidate.get("source_common_dir_identity"),
                    candidate.get("source_common_dir"),
                    common,
                )
                and candidate.get("branch") == record.get("branch")
                and candidate.get("branch_ref")
                == record.get("branch_ref")
                and candidate.get("planned_ref_oid")
                == record.get("planned_ref_oid")
                and candidate.get("ref_case_sensitive")
                == record.get("ref_case_sensitive")
                and candidate.get(
                    "ref_unicode_normalization_distinct"
                )
                == record.get(
                    "ref_unicode_normalization_distinct"
                )
            ):
                matches.append(candidate)
        if len(matches) != 1:
            raise _v4_workspace_error(
                "WORKSPACE_OWNERSHIP_CONFLICT",
                "workspace registry has no unique exact claim",
                details={
                    "repository_id": repository_id,
                    "match_count": len(matches),
                },
            )
        claim = matches[0]
        claim_id = claim.get("claim_id")
        if (
            not isinstance(claim_id, str)
            or not claim_id
            or claim_id in seen_claim_ids
        ):
            raise _v4_workspace_error(
                "WORKSPACE_REGISTRY_INVALID",
                "workspace claim identities must be non-empty and unique",
                details={"repository_id": repository_id},
            )
        seen_claim_ids.add(claim_id)
        selected[repository_id] = _workspace_copy.deepcopy(claim)
    return selected


def _v4_workspace_plan_artifact_candidates(
    plan: V4WorkspacePlanEffectPlan,
    observation: V4WorkspaceEffectObservation | None,
) -> list[tuple[_WorkspacePath, bytes, dict[str, object]]]:
    artifact_directory = _WorkspacePath(
        str(plan.bindings["artifact_directory"])
    )
    if observation is None:
        try:
            paths = sorted(
                artifact_directory.glob("*.json"),
                key=lambda item: item.name.encode("utf-8"),
            )
        except OSError:
            paths = []
    else:
        observed_path = observation.result.get("artifact_path")
        paths = (
            [_WorkspacePath(str(observed_path))]
            if isinstance(observed_path, str)
            else []
        )
    candidates = []
    for path in paths:
        stem = path.stem
        if (
            path.suffix != ".json"
            or not _V4_WORKSPACE_SHA256.fullmatch(stem)
            or path.is_symlink()
        ):
            continue
        expected = (
            artifact_directory / f"{stem}.json"
        ).resolve(strict=False)
        if not _same_path(path, expected):
            continue
        try:
            source, evidence = _v4_workspace_read_artifact_bytes(
                path, stem
            )
            _v4_workspace_seed_evidence_filesystems(plan, evidence)
            _v4_workspace_validate_plan_artifact(
                evidence,
                expected_sha256=stem,
                expected_generation=plan.workspace_generation,
                expected_repository_ids=plan.repository_ids,
                authorization_plan_sha256=plan.semantic_sha256,
            )
        except FlowError:
            continue
        authorization = evidence.get("authorization") or {}
        if (
            evidence.get("task_id") != plan.task_id
            or authorization.get("task_revision")
            != plan.task_revision
            or authorization.get("expected_effect_id")
            != plan.expected_effect_id
            or authorization.get("workspace_generation")
            != plan.workspace_generation
            or authorization.get("approved_binding_sha256")
            != plan.approved_binding_sha256
        ):
            continue
        candidates.append((path, source, evidence))
    return candidates


def _v4_workspace_verify_observation_identity(
    plan: V4WorkspaceEffectPlan,
    claim: _WorkspaceMapping[str, object],
    observation: V4WorkspaceEffectObservation | None,
) -> None:
    if observation is None:
        return
    if type(observation) is not V4WorkspaceEffectObservation:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVATION_INVALID",
            "observer requires the exact typed dispatch observation",
        )
    mismatches = [
        field
        for field, actual, expected in (
            ("action", observation.action, plan.action),
            (
                "plan_sha256",
                observation.plan_sha256,
                plan.semantic_sha256,
            ),
            ("task_id", observation.task_id, claim["task_id"]),
            (
                "execution_id",
                observation.execution_id,
                claim["execution_id"],
            ),
            ("effect_id", observation.effect_id, claim["effect_id"]),
            ("claim_id", observation.claim_id, claim["claim_id"]),
            ("attempt_id", observation.attempt_id, claim["attempt_id"]),
        )
        if actual != expected
    ]
    if mismatches:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVATION_MISMATCH",
            "dispatch observation differs from the durable claim",
            details={"fields": mismatches},
        )


@_workspace_dataclass(frozen=True)
class V4WorkspaceEffectReceipt:
    action: str
    plan_sha256: str
    claim_id: str
    attempt_id: str
    journal_record_sha256: str
    index_record_sha256: str
    containment_record_sha256: str
    observe_context_sha256: str
    repository_ids: tuple[str, ...]
    recovered_lost_response: bool
    observation: _WorkspaceMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        expected_type = {
            "plan": "V4WorkspacePlanEffectReceipt",
            "execute": "V4WorkspaceExecuteEffectReceipt",
        }.get(self.action)
        if expected_type is None or type(self).__name__ != expected_type:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_RECEIPT_TYPE_INVALID",
                "typed receipt class does not match its action",
            )
        _v4_workspace_require_text(self.claim_id, "claim_id")
        _v4_workspace_require_text(self.attempt_id, "attempt_id")
        for field_name in (
            "journal_record_sha256",
            "index_record_sha256",
            "containment_record_sha256",
            "observe_context_sha256",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not _V4_WORKSPACE_SHA256.fullmatch(value)
            ):
                raise _v4_workspace_error(
                    "WORKSPACE_EFFECT_RECEIPT_BINDING_INVALID",
                    f"{field_name} must be lowercase SHA-256",
                )
        repository_ids = _v4_workspace_sorted_text(
            self.repository_ids, "repository_ids"
        )
        public = _v4_workspace_public(dict(self.observation))
        assert isinstance(public, dict)
        _v4_workspace_reject_secrets(public)
        core = {
            "schema": _V4_WORKSPACE_EFFECT_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_ids": list(repository_ids),
            "recovered_lost_response": self.recovered_lost_response,
            "observation": public,
        }
        expected = _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_RECEIPT_DOMAIN, core
        )
        if expected != self.semantic_sha256:
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_RECEIPT_DIGEST_MISMATCH",
                "workspace receipt digest is invalid",
            )
        object.__setattr__(self, "repository_ids", repository_ids)
        object.__setattr__(
            self, "observation", _v4_workspace_freeze(public)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _V4_WORKSPACE_EFFECT_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_ids": list(self.repository_ids),
            "recovered_lost_response": (
                self.recovered_lost_response
            ),
            "observation": _v4_workspace_thaw(self.observation),
            "semantic_sha256": self.semantic_sha256,
        }


@_workspace_dataclass(frozen=True)
class V4WorkspacePlanEffectReceipt(V4WorkspaceEffectReceipt):
    pass


@_workspace_dataclass(frozen=True)
class V4WorkspaceExecuteEffectReceipt(V4WorkspaceEffectReceipt):
    pass


_V4_WORKSPACE_RECEIPT_TYPES = {
    "plan": V4WorkspacePlanEffectReceipt,
    "execute": V4WorkspaceExecuteEffectReceipt,
}


def _v4_workspace_build_receipt(
    plan: V4WorkspaceEffectPlan,
    claim: _WorkspaceMapping[str, object],
    *,
    recovered_lost_response: bool,
    observation: _WorkspaceMapping[str, object],
) -> V4WorkspaceEffectReceipt:
    public = _v4_workspace_public(dict(observation))
    assert isinstance(public, dict)
    core = {
        "schema": _V4_WORKSPACE_EFFECT_RECEIPT_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "claim_id": claim["claim_id"],
        "attempt_id": claim["attempt_id"],
        "journal_record_sha256": claim["journal_record_sha256"],
        "index_record_sha256": claim["index_record_sha256"],
        "containment_record_sha256": claim[
            "containment_record_sha256"
        ],
        "observe_context_sha256": claim[
            "observe_context_sha256"
        ],
        "repository_ids": list(plan.repository_ids),
        "recovered_lost_response": recovered_lost_response,
        "observation": public,
    }
    receipt_type = _V4_WORKSPACE_RECEIPT_TYPES[plan.action]
    return receipt_type(
        plan.action,
        plan.semantic_sha256,
        str(claim["claim_id"]),
        str(claim["attempt_id"]),
        str(claim["journal_record_sha256"]),
        str(claim["index_record_sha256"]),
        str(claim["containment_record_sha256"]),
        str(claim["observe_context_sha256"]),
        plan.repository_ids,
        recovered_lost_response,
        public,
        _v4_workspace_sha256(
            _V4_WORKSPACE_EFFECT_RECEIPT_DOMAIN, core
        ),
    )


def observe_v4_workspace_plan_effect(
    plan: V4WorkspacePlanEffectPlan,
    observe_context: object,
    observation: V4WorkspaceEffectObservation | None = None,
) -> V4WorkspacePlanEffectReceipt:
    """Read artifact and registry only; never re-plan or re-dispatch."""

    if type(plan) is not V4WorkspacePlanEffectPlan:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "plan observer requires its exact typed plan",
        )
    claim = _v4_workspace_validate_observe_context(
        plan, observe_context
    )
    _v4_workspace_verify_observation_identity(
        plan, claim, observation
    )
    _v4_workspace_load_bound_state(plan)
    candidates = _v4_workspace_plan_artifact_candidates(
        plan, observation
    )
    if len(candidates) != 1:
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_INVALID",
            "observer found no unique exact digest-addressed plan",
            details={"candidate_count": len(candidates)},
        )
    path, source, evidence = candidates[0]
    evidence_sha = _workspace_hashlib.sha256(source).hexdigest()
    claims = _v4_workspace_registry_claims(
        plan,
        evidence_sha256=evidence_sha,
        evidence=evidence,
    )
    observed = {
        "evidence_sha256": evidence_sha,
        "artifact_path": str(path),
        "artifact_path_identity": _serializable_path_identity(path),
        "artifact_size": len(source),
        "registry_path": str(
            _WorkspacePath(str(plan.bindings["data_root"]))
            / "workspace-registry.json"
        ),
        "claims": [
            {
                "repository_id": repository_id,
                "claim_id": claims[repository_id]["claim_id"],
            }
            for repository_id in plan.repository_ids
        ],
    }
    if (
        observation is not None
        and _v4_workspace_thaw(observation.result) != observed
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_OBSERVATION_MISMATCH",
            "plan dispatch result differs from durable artifact/registry",
        )
    receipt = _v4_workspace_build_receipt(
        plan,
        claim,
        recovered_lost_response=observation is None,
        observation=observed,
    )
    assert isinstance(receipt, V4WorkspacePlanEffectReceipt)
    return receipt


def _v4_workspace_observe_materialized_unlocked(
    plan: V4WorkspaceExecuteEffectPlan,
    repository_plan: dict[str, object],
    source_binding: dict[str, object],
    claim: dict[str, object],
    *,
    evidence_sha256: str,
) -> dict[str, object]:
    repository_id = str(repository_plan["repository_id"])
    if (
        source_binding.get("repository_id") != repository_id
        or source_binding.get("source_path")
        != repository_plan.get("source_path")
        or source_binding.get("base_sha")
        != repository_plan.get("base_sha")
        or source_binding.get("source_capability_profile_sha256")
        != repository_plan.get("source_capability_profile_sha256")
    ):
        raise _v4_workspace_error(
            "WORKSPACE_PLAN_MISMATCH",
            "execute source binding differs from the approved repo plan",
            details={"repository_id": repository_id},
        )
    try:
        source = _WorkspacePath(
            str(repository_plan["source_path"])
        ).resolve(strict=True)
        destination = _WorkspacePath(
            str(repository_plan["path"])
        ).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _v4_workspace_error(
            "WORKSPACE_VERIFY_FAILED",
            "one approved worktree is not materialized",
            details={
                "repository_id": repository_id,
                "path": str(repository_plan.get("path")),
                "error": str(exc),
            },
        ) from None
    mutable_plan = _workspace_copy.deepcopy(repository_plan)
    registry_path = (
        _WorkspacePath(str(plan.bindings["data_root"]))
        / "workspace-registry.json"
    )
    mutable_plan["workspace_claim"] = {
        "claim_id": claim["claim_id"],
        "registry_path": str(registry_path),
        "registry_identity": _serializable_path_identity(
            registry_path
        ),
        "plan_sha256": evidence_sha256,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path_identity": claim.get("path_identity"),
        "source_identity": claim.get("source_identity"),
        "source_common_dir_identity": claim.get(
            "source_common_dir_identity"
        ),
    }
    _assert_workspace_plan_claim(mutable_plan)
    root = _git_optional(
        destination, "rev-parse", "--show-toplevel"
    )
    branch = _git_optional(
        destination,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
    )
    head = _git_optional(destination, "rev-parse", "HEAD")
    status_available, status_porcelain = _status_porcelain(
        destination
    )
    try:
        common_dir_matches = _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
        linked = _is_linked_worktree(destination)
    except (FlowError, OSError):
        common_dir_matches = False
        linked = False
    base_sha = str(repository_plan["base_sha"])
    previously_recorded = bool(
        repository_plan.get("previously_recorded")
    )
    if previously_recorded:
        base_acceptable = (
            _run(
                [
                    "git",
                    "-C",
                    str(destination),
                    "merge-base",
                    "--is-ancestor",
                    base_sha,
                    "HEAD",
                ],
                check=False,
            ).returncode
            == 0
        )
    else:
        base_acceptable = head == base_sha
    branch_ref = str(repository_plan["branch_ref"])
    ref_head = _git_optional(
        source,
        "rev-parse",
        "--verify",
        f"{branch_ref}^{{commit}}",
    )
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if item.get("worktree")
            and _same_path(
                _WorkspacePath(item["worktree"]), destination
            )
        ),
        None,
    )
    if (
        not root
        or not _same_path(_WorkspacePath(root), destination)
        or branch != repository_plan.get("branch")
        or not head
        or not base_acceptable
        or ref_head != head
        or not status_available
        or bool(status_porcelain)
        or not common_dir_matches
        or not linked
        or not entry
        or entry.get("branch") != branch_ref
        or entry.get("HEAD") != head
        or not _recorded_path_matches(
            repository_plan.get("source_identity"),
            repository_plan.get("source_path"),
            source,
        )
        or not _recorded_path_matches(
            repository_plan.get("path_identity"),
            repository_plan.get("path"),
            destination,
        )
        or not _recorded_path_matches(
            repository_plan.get("source_common_dir_identity"),
            repository_plan.get("source_common_dir"),
            _git_common_dir(source),
        )
    ):
        raise _v4_workspace_error(
            "WORKSPACE_VERIFY_FAILED",
            "materialized worktree differs from the exact approved plan",
            details={
                "repository_id": repository_id,
                "expected_branch": repository_plan.get("branch"),
                "actual_branch": branch,
                "expected_base": base_sha,
                "actual_head": head,
                "dirty": bool(status_porcelain),
            },
        )
    capability_profile = repository_plan.get("capability_profile")
    filesystem_capabilities = (
        capability_profile.get("filesystem")
        if isinstance(capability_profile, dict)
        else None
    )
    if not isinstance(filesystem_capabilities, dict):
        raise _v4_workspace_error(
            "WORKSPACE_VERIFY_FAILED",
            "approved workspace capability facts are unavailable",
            details={"repository_id": repository_id},
        )
    first = _fingerprint_repo_once(
        destination,
        filesystem_capabilities=filesystem_capabilities,
    )
    second = _fingerprint_repo_once(
        destination,
        filesystem_capabilities=filesystem_capabilities,
    )
    if (
        first.get("sha256") != second.get("sha256")
        or second.get("capability_profile_sha256")
        != repository_plan.get("capability_profile_sha256")
    ):
        raise _v4_workspace_error(
            "WORKSPACE_VERIFY_FAILED",
            "worktree fingerprint or capability profile drifted",
            details={"repository_id": repository_id},
        )
    return {
        "repository_id": repository_id,
        "path": str(destination),
        "path_identity": _serializable_path_identity(destination),
        "source_path": str(source),
        "source_identity": _serializable_path_identity(source),
        "branch": branch,
        "branch_ref": branch_ref,
        "base_sha": base_sha,
        "head_sha": head,
        "clean": True,
        "linked_worktree": True,
        "workspace_generation": plan.workspace_generation,
        "claim_id": claim["claim_id"],
        "capability_profile_sha256": second[
            "capability_profile_sha256"
        ],
        "fingerprint_sha256": second["sha256"],
        "tracked_worktree_manifest_sha256": second[
            "tracked_worktree_manifest_sha256"
        ],
    }


def _v4_workspace_observe_materialized(
    plan: V4WorkspaceExecuteEffectPlan,
    repository_plan: dict[str, object],
    source_binding: dict[str, object],
    claim: dict[str, object],
    *,
    evidence_sha256: str,
) -> dict[str, object]:
    source_filesystem = source_binding.get(
        "source_filesystem_capabilities"
    )
    capability_profile = repository_plan.get(
        "capability_profile"
    )
    workspace_filesystem = (
        capability_profile.get("filesystem")
        if isinstance(capability_profile, dict)
        else None
    )
    if not isinstance(source_filesystem, dict) or not isinstance(
        workspace_filesystem, dict
    ):
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_FILESYSTEM_FACTS_INVALID",
            "observer requires approved source and workspace facts",
        )
    _v4_workspace_seed_filesystem_facts(
        _WorkspacePath(str(repository_plan["source_path"])),
        source_filesystem,
    )
    _v4_workspace_seed_filesystem_facts(
        _WorkspacePath(str(repository_plan["path"])),
        workspace_filesystem,
    )
    with _v4_workspace_readonly_git():
        return _v4_workspace_observe_materialized_unlocked(
            plan,
            repository_plan,
            source_binding,
            claim,
            evidence_sha256=evidence_sha256,
        )


def _v4_workspace_execute_observation_projection(
    outcome: _WorkspaceMapping[str, object],
) -> dict[str, object]:
    claim = outcome.get("workspace_claim")
    return {
        "repository_id": outcome.get("repository_id"),
        "path": outcome.get("path"),
        "path_identity": outcome.get("path_identity"),
        "source_path": outcome.get("source_path"),
        "source_identity": outcome.get("source_identity"),
        "branch": outcome.get("branch"),
        "branch_ref": outcome.get("branch_ref"),
        "base_sha": outcome.get("base_sha"),
        "head_sha": outcome.get("head_sha"),
        "clean": True,
        "linked_worktree": True,
        "workspace_generation": outcome.get("workspace_generation"),
        "claim_id": (
            claim.get("claim_id")
            if isinstance(claim, _WorkspaceMapping)
            else None
        ),
        "capability_profile_sha256": outcome.get(
            "capability_profile_sha256"
        ),
        "fingerprint_sha256": outcome.get("fingerprint_sha256"),
        "tracked_worktree_manifest_sha256": outcome.get(
            "tracked_worktree_manifest_sha256"
        ),
    }


def observe_v4_workspace_execute_effect(
    plan: V4WorkspaceExecuteEffectPlan,
    observe_context: object,
    observation: V4WorkspaceEffectObservation | None = None,
) -> V4WorkspaceExecuteEffectReceipt:
    """Read-only all-repository postcondition verification."""

    if type(plan) is not V4WorkspaceExecuteEffectPlan:
        raise _v4_workspace_error(
            "WORKSPACE_EFFECT_PLAN_TYPE_INVALID",
            "execute observer requires its exact typed plan",
        )
    claim = _v4_workspace_validate_observe_context(
        plan, observe_context
    )
    _v4_workspace_verify_observation_identity(
        plan, claim, observation
    )
    _v4_workspace_load_bound_state(plan)
    evidence = _v4_workspace_load_execute_evidence(plan)
    evidence_sha = str(plan.bindings["approved_artifact_sha256"])
    claims = _v4_workspace_registry_claims(
        plan,
        evidence_sha256=evidence_sha,
        evidence=evidence,
    )
    repository_plans = [
        _v4_workspace_thaw(item)
        for item in plan.bindings["repository_plans"]
    ]
    source_by_id = {
        str(item["repository_id"]): _v4_workspace_thaw(item)
        for item in plan.bindings["source_repositories"]
    }
    results = [
        _v4_workspace_observe_materialized(
            plan,
            repository_plan,
            source_by_id[str(repository_plan["repository_id"])],
            claims[str(repository_plan["repository_id"])],
            evidence_sha256=evidence_sha,
        )
        for repository_plan in repository_plans
    ]
    # Close the read-only TOCTOU window across the whole canonical repo set.
    _v4_workspace_load_bound_state(plan)
    observed = {"workspaces": results}
    if observation is not None:
        dispatched = _v4_workspace_thaw(observation.result)
        outcomes = (
            dispatched.get("outcomes")
            if isinstance(dispatched, dict)
            else None
        )
        if (
            not isinstance(outcomes, list)
            or [
                _v4_workspace_execute_observation_projection(item)
                for item in outcomes
                if isinstance(item, dict)
            ]
            != results
        ):
            raise _v4_workspace_error(
                "WORKSPACE_EFFECT_OBSERVATION_MISMATCH",
                "execute dispatch result differs from all-repository observation",
            )
    receipt = _v4_workspace_build_receipt(
        plan,
        claim,
        recovered_lost_response=observation is None,
        observation=observed,
    )
    assert isinstance(receipt, V4WorkspaceExecuteEffectReceipt)
    return receipt


def _workspace_claim_integrity_error(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> str | None:
    workspace = repo.get("workspace") or {}
    receipt = workspace.get("workspace_claim") or {}
    try:
        _require_current_evidence(workspace, "workspace")
        _require_current_evidence(receipt, "workspace claim receipt")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    registry_path_value = receipt.get("registry_path")
    claim_id = receipt.get("claim_id")
    if not registry_path_value or not claim_id:
        return f"workspace has no durable ownership claim: {repo.get('id')}"
    registry_path = Path(registry_path_value)
    if not _recorded_path_matches(
        receipt.get("registry_identity"),
        registry_path_value,
        registry_path,
    ):
        return f"workspace ownership registry identity changed: {repo.get('id')}"
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
    try:
        _assert_supported_evidence_versions(registry)
        _require_current_evidence(registry, "workspace registry")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    claim = next(
        (
            item
            for item in registry.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    try:
        _require_current_evidence(claim, "workspace ownership claim")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    expected_plan_sha = ((state_value.get("workspace") or {}).get("plan") or {}).get(
        "sha256"
    )
    expected_source = str(Path(repo.get("path", "")).resolve(strict=False))
    expected_common_dir = _source_common_dir_for_claim(repo.get("path"))
    expected_workspace_path = Path(
        workspace.get("path", "")
    ).resolve(strict=False)
    expected_source_path = Path(expected_source)
    expected_common_path = Path(expected_common_dir)
    try:
        _require_current_evidence(claim, "workspace ownership claim")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
    if (
        not claim
        or claim.get("task_id") != state_value.get("task_id")
        or claim.get("repository_id") != repo.get("id")
        or not _recorded_path_matches(
            claim.get("source_identity"),
            claim.get("source_path"),
            expected_source_path,
        )
        or not _recorded_path_matches(
            claim.get("source_common_dir_identity"),
            claim.get("source_common_dir"),
            expected_common_path,
        )
        or not _recorded_path_matches(
            claim.get("path_identity"),
            claim.get("path"),
            expected_workspace_path,
        )
        or claim.get("branch") != workspace.get("branch")
        or claim.get("branch_ref") != workspace.get("branch_ref")
        or claim.get("planned_ref_oid") != workspace.get("planned_ref_oid")
        or claim.get("ref_case_sensitive")
        != workspace.get("ref_case_sensitive")
        or claim.get("ref_unicode_normalization_distinct")
        != workspace.get("ref_unicode_normalization_distinct")
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
    try:
        _require_current_evidence(workspace, "workspace")
    except FlowError as exc:
        return f"{exc.message}: {repo.get('id')}"
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
    if not _recorded_path_matches(
        workspace.get("source_identity"), repo.get("path"), source
    ):
        return f"workspace source filesystem identity changed: {repo.get('id')}"
    if not _recorded_path_matches(
        workspace.get("path_identity"), workspace.get("path"), path
    ):
        return f"workspace filesystem identity changed: {repo.get('id')}"
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
    if not root or not _same_path(Path(root), path):
        return f"workspace path is not a Git worktree root: {repo.get('id')}"
    try:
        if not _same_path(_git_common_dir(path), _git_common_dir(source)):
            return f"workspace belongs to a different Git repository: {repo.get('id')}"
        if not _is_linked_worktree(path):
            return f"workspace is not a linked worktree: {repo.get('id')}"
        source_profile = _git_capability_profile(source)
        workspace_profile = _git_capability_profile(path)
        if source_profile["sha256"] != workspace.get(
            "source_capability_profile_sha256"
        ):
            return f"source capability profile changed: {repo.get('id')}"
        if workspace_profile["sha256"] != workspace.get(
            "capability_profile_sha256"
        ):
            return f"workspace capability profile changed: {repo.get('id')}"
        branch_state = _branch_ref_state(
            source, str(workspace.get("branch")), []
        )
        if (
            branch_state.get("branch_ref")
            != workspace.get("branch_ref")
            or branch_state.get("ref_case_sensitive")
            != workspace.get("ref_case_sensitive")
            or branch_state.get("ref_unicode_normalization_distinct")
            != workspace.get("ref_unicode_normalization_distinct")
            or not _path_identity_equal(
                branch_state.get("git_common_dir_identity"),
                workspace.get("source_common_dir_identity"),
            )
        ):
            return f"workspace ref-storage identity changed: {repo.get('id')}"
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
    expected_ref = workspace.get("branch_ref")
    if expected_ref != f"refs/heads/{workspace.get('branch')}":
        return f"workspace full ref identity is invalid: {repo.get('id')}"
    resolved_ref = _git_optional(
        source, "rev-parse", "--verify", f"{expected_ref}^{{commit}}"
    )
    if resolved_ref != head:
        return f"workspace ref object changed independently of HEAD: {repo.get('id')}"
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if item.get("worktree")
            and _same_path(Path(item["worktree"]), path)
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
    _require_current_evidence(evidence, "workspace plan")
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
                "evidence_contract_version": workspace.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "source_path": repo["path"],
                "source_identity": workspace.get("source_identity"),
                "path": workspace.get("path"),
                "path_identity": workspace.get("path_identity"),
                "branch": workspace.get("branch"),
                "branch_ref": workspace.get("branch_ref"),
                "planned_ref_oid": workspace.get("planned_ref_oid"),
                "ref_case_sensitive": workspace.get("ref_case_sensitive"),
                "ref_unicode_normalization_distinct": workspace.get(
                    "ref_unicode_normalization_distinct"
                ),
                "source_common_dir": workspace.get("source_common_dir"),
                "source_common_dir_identity": workspace.get(
                    "source_common_dir_identity"
                ),
                "base_sha": workspace.get("base_sha"),
                "capability_profile_sha256": workspace.get(
                    "capability_profile_sha256"
                ),
                "source_capability_profile_sha256": workspace.get(
                    "source_capability_profile_sha256"
                ),
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
    try:
        _require_current_evidence(index, f"workspace-index:{repository_id}")
    except FlowError as exc:
        return {
            "repository_id": repository_id,
            "reason": exc.message,
        }
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
        try:
            _require_current_evidence(
                receipt, f"workspace-index-receipt:{repository_id}"
            )
        except FlowError as exc:
            return {
                "repository_id": repository_id,
                "reason": exc.message,
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
            or not _recorded_path_matches(
                receipt.get("path_identity"),
                receipt.get("path"),
                receipt_path,
            )
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
    if not _recorded_path_matches(
        index.get("repo_path_identity"),
        recorded_path_value,
        workspace_path,
    ):
        return {
            "repository_id": repository_id,
            "reason": "workspace index path identity changed",
        }
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
        fingerprint = _fingerprint_repo(workspace_path)
    except (FlowError, OSError) as exc:
        return {
            "repository_id": repository_id,
            "reason": f"workspace fingerprint cannot be verified: {exc}",
        }
    if fingerprint["capability_profile_sha256"] != index.get(
        "capability_profile_sha256"
    ):
        return {
            "repository_id": repository_id,
            "reason": "workspace capability profile changed after indexing",
            "recorded_capability_profile_sha256": index.get(
                "capability_profile_sha256"
            ),
            "current_capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
        }
    current_fingerprint = fingerprint["sha256"]
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
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
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
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        lock_workspace_registry=True,
        manager_action_id="workspace.prepare",
    ) as (task_dir, current):
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
            _claim_workspace_plan(
                data_root,
                current,
                evidence_sha,
                plans,
                registry_locked=True,
            )
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
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "artifact_id": str(uuid.uuid4()),
                "kind": "workspace-plan",
                "path": str(plan_path),
                "path_identity": _serializable_path_identity(plan_path),
                "sha256": evidence_sha,
                "artifact_type": "file",
                "size": len(evidence_bytes),
                "file_count": 1,
                "total_size": len(evidence_bytes),
                "recorded_at": utc_now(),
                "metadata": {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "repository_ids": [item["repository_id"] for item in evidence["repositories"]],
                    "workspace_generation": evidence["workspace_generation"],
                    "capability_profile_sha256": {
                        item["repository_id"]: item[
                            "capability_profile_sha256"
                        ]
                        for item in evidence["repositories"]
                    },
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
        _claim_workspace_plan(
            data_root,
            current,
            evidence_sha,
            plans,
            registry_locked=True,
        )
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
