# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Workspace planning, claims, execution, integrity, and planning context.
from __future__ import annotations

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
    registry = _load_workspace_registry(
        data_root, allow_legacy_container=True
    )
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


