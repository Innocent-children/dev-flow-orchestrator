# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Baseline, analysis workspace, index, artifact, route, and approval workflows.
from __future__ import annotations

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
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "remote_url_sha256": preflight.get("remote_url_sha256"),
                "base_branch": preflight.get("base_branch"),
                "base_candidate_ref": preflight.get("base_candidate_ref"),
                "base_candidate_sha": preflight.get("base_candidate_sha"),
                "fetch_refspec": preflight.get("fetch_refspec"),
                "head_sha": preflight.get("head_sha"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
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
        _live_approved_remote_url(
            Path(repo["path"]), repo["id"], preflight
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
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "branch": preflight.get("branch"),
                "head_sha": preflight.get("head_sha"),
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "remote_url_sha256": preflight.get("remote_url_sha256"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
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
        _assert_branch_checkout_binding(state_value, repo)
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
    baseline = _require_current_evidence(
        repo.get("baseline"), f"baseline:{repo.get('id')}"
    )
    _assert_evidence_supported(source)
    base_sha = baseline.get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
    _assert_tree_checkout_supported(source, base_sha)
    destination = (
        data_root / "analysis" / state_value["task_id"] / repo["id"]
    ).resolve(strict=False)
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != baseline.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "source repository capabilities changed after baseline",
            details={"repository_id": repo.get("id")},
        )
    destination_profile = _git_capability_profile(source, destination)
    entries = _worktree_entries(source)
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
        head = _git_optional(destination, "rev-parse", "HEAD")
        branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
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
        if (
            not root
            or not _same_path(Path(root), destination)
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
        fingerprint = _fingerprint_repo(destination)
        if fingerprint["capability_profile_sha256"] != destination_profile[
            "sha256"
        ]:
            raise FlowError(
                "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                "analysis worktree capabilities differ from the approved destination profile",
                details={"repository_id": repo.get("id")},
            )
        _set_private_permissions(destination, 0o700)
        return {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(destination),
            "path_identity": _serializable_path_identity(destination),
            "source_identity": _serializable_path_identity(source),
            "source_common_dir_identity": _serializable_path_identity(
                _git_common_dir(source)
            ),
            "head_sha": head,
            "detached": True,
            "ready": True,
            "created": False,
            "materialized_at": utc_now(),
            "filesystem_identity": _serializable_path_identity(destination),
            "source_capability_profile_sha256": source_profile["sha256"],
            "capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
            "fingerprint_sha256": fingerprint["sha256"],
        }
    if destination_entry:
        recorded = repo.get("analysis_workspace") or {}
        if not recorded.get("ready") or not _recorded_path_matches(
            recorded.get("path_identity"),
            recorded.get("path"),
            destination,
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"Git reports an unowned analysis path that is unavailable: {destination}",
                details={"repository_id": repo["id"], "path": str(destination)},
            )
    _ensure_private_dir(destination.parent)
    add_arguments = ["worktree", "add"]
    if destination_entry:
        add_arguments.append("--force")
    add_arguments.extend(["--detach", str(destination), base_sha])
    _git_mutating(
        source,
        "-c",
        f"core.hooksPath={os.devnull}",
        *add_arguments,
    )
    head = _git(destination, "rev-parse", "HEAD")
    branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
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
        head != base_sha
        or branch is not None
        or not _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
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
    fingerprint = _fingerprint_repo(destination)
    if fingerprint["capability_profile_sha256"] != destination_profile[
        "sha256"
    ]:
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            "analysis worktree capabilities differ from the approved destination profile",
            details={"repository_id": repo.get("id")},
        )
    _set_private_permissions(destination, 0o700)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(destination),
        "path_identity": _serializable_path_identity(destination),
        "source_identity": _serializable_path_identity(source),
        "source_common_dir_identity": _serializable_path_identity(
            _git_common_dir(source)
        ),
        "head_sha": head,
        "detached": True,
        "ready": True,
        "created": True,
        "materialized_at": utc_now(),
        "filesystem_identity": _serializable_path_identity(destination),
        "source_capability_profile_sha256": source_profile["sha256"],
        "capability_profile_sha256": fingerprint["capability_profile_sha256"],
        "fingerprint_sha256": fingerprint["sha256"],
    }


def _analysis_workspace_integrity_error(repo: dict[str, Any]) -> str | None:
    analysis = repo.get("analysis_workspace") or {}
    try:
        _require_current_evidence(repo.get("baseline"), f"baseline:{repo.get('id')}")
        _require_current_evidence(analysis, f"analysis-workspace:{repo.get('id')}")
    except FlowError as exc:
        return exc.message
    if not analysis.get("ready") or not analysis.get("path"):
        return f"analysis workspace is not ready: {repo.get('id')}"
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(analysis["path"]).resolve(strict=False)
    if not _recorded_path_matches(
        analysis.get("source_identity"), repo.get("path"), source
    ):
        return f"analysis source identity changed: {repo.get('id')}"
    if not _recorded_path_matches(
        analysis.get("path_identity"), analysis.get("path"), path
    ):
        return f"analysis workspace path identity changed: {repo.get('id')}"
    if not path.is_dir():
        return f"analysis workspace path is missing: {repo.get('id')}"
    expected_head = (repo.get("baseline") or {}).get("base_sha")
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    head = _git_optional(path, "rev-parse", "HEAD")
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(path)
    try:
        same_common_dir = _same_path(
            _git_common_dir(path), _git_common_dir(source)
        )
        linked_worktree = _is_linked_worktree(path)
    except (FlowError, OSError):
        same_common_dir = False
        linked_worktree = False
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
        not root
        or not _same_path(Path(root), path)
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
    try:
        fingerprint = _fingerprint_repo(path)
    except FlowError as exc:
        return f"analysis workspace evidence cannot be regenerated: {repo.get('id')}: {exc.message}"
    if (
        fingerprint.get("capability_profile_sha256")
        != analysis.get("capability_profile_sha256")
    ):
        return f"analysis workspace capability profile changed: {repo.get('id')}"
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != analysis.get(
        "source_capability_profile_sha256"
    ):
        return f"analysis source capability profile changed: {repo.get('id')}"
    if fingerprint.get("sha256") != analysis.get("fingerprint_sha256"):
        return f"analysis workspace fingerprint changed: {repo.get('id')}"
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
        regenerate_baseline = already_baselined and any(
            (repo.get("baseline") or {}).get(
                "evidence_contract_version"
            )
            != EVIDENCE_CONTRACT_VERSION
            for repo in current["repositories"]
        )
        if already_baselined and args.fetch:
            raise FlowError(
                "BASELINE_ALREADY_PINNED",
                "--fetch cannot repin an existing baseline; the recorded base is immutable",
            )
        if (
            already_baselined
            and not regenerate_baseline
            and not args.materialize
        ):
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
        if not already_baselined or regenerate_baseline:
            for repo in state_value["repositories"]:
                previous_baseline = repo.get("baseline") or {}
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
                    live_remote_url = _live_approved_remote_url(
                        path, repo["id"], preflight
                    )
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
                    if (
                        not isinstance(live_remote_url, str)
                        or not live_remote_url.strip()
                    ):
                        raise FlowError(
                            "REMOTE_URL_UNAVAILABLE",
                            "approved fetch has no usable remote URL",
                            details={
                                "repository_id": repo["id"],
                                "remote": remote,
                            },
                        )
                    _git_mutating(
                        path,
                        "-c",
                        f"core.hooksPath={os.devnull}",
                        "-c",
                        "core.fsmonitor=false",
                        "-c",
                        "core.gitProxy=",
                        "-c",
                        "core.askPass=",
                        "-c",
                        "core.sshCommand=ssh",
                        "-c",
                        "credential.helper=",
                        "-c",
                        "maintenance.auto=false",
                        "-c",
                        "gc.auto=0",
                        "-c",
                        "protocol.allow=never",
                        "-c",
                        "protocol.file.allow=always",
                        "-c",
                        "protocol.git.allow=always",
                        "-c",
                        "protocol.http.allow=always",
                        "-c",
                        "protocol.https.allow=always",
                        "-c",
                        "protocol.ssh.allow=always",
                        "-c",
                        "protocol.ext.allow=never",
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "--no-auto-maintenance",
                        "--no-write-commit-graph",
                        "--no-prune",
                        "--no-prune-tags",
                        "--upload-pack=git-upload-pack",
                        "--",
                        live_remote_url,
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
                if (
                    regenerate_baseline
                    and previous_baseline.get("base_sha") != base_sha
                ):
                    raise FlowError(
                        "EVIDENCE_REGENERATION_REQUIRED",
                        "legacy baseline no longer resolves to its recorded immutable object",
                        details={
                            "repository_id": repo["id"],
                            "recorded_base_sha": previous_baseline.get(
                                "base_sha"
                            ),
                            "current_base_sha": base_sha,
                        },
                    )
                repo["baseline"] = {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
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
                    "capability_profile": preflight.get("capability_profile"),
                    "capability_profile_sha256": preflight.get(
                        "capability_profile_sha256"
                    ),
                    "worktree_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
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
        _require_current_evidence(index, f"baseline-index:{repo.get('id')}")
        integrity_error = _analysis_workspace_integrity_error(repo)
        if integrity_error:
            raise FlowError(
                "ANALYSIS_WORKSPACE_CHANGED",
                integrity_error,
                details={"repository_id": repo.get("id")},
            )
        analysis_workspace = repo.get("analysis_workspace") or {}
        analysis_path = Path(str(analysis_workspace.get("path", "")))
        if (
            not _recorded_path_matches(
                index.get("repo_path_identity"),
                index.get("repo_path"),
                analysis_path,
            )
            or index.get("commit_sha")
            != (repo.get("baseline") or {}).get("base_sha")
            or index.get("capability_profile_sha256")
            != analysis_workspace.get("capability_profile_sha256")
            or index.get("fingerprint_sha256")
            != analysis_workspace.get("fingerprint_sha256")
        ):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                "baseline index no longer binds the current analysis evidence",
                details={"repository_id": repo.get("id")},
            )
        if not index.get("index_record_id"):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                f"repository index has no stable record token: {repo.get('id')}",
            )
        receipt = index.get("receipt")
        if isinstance(receipt, dict):
            _require_current_evidence(
                receipt, f"index-receipt:{repo.get('id')}"
            )
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
                or not _recorded_path_matches(
                    receipt.get("path_identity"),
                    receipt.get("path"),
                    receipt_path,
                )
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
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "repository_id": repo["id"],
                "index_record_id": index["index_record_id"],
                "commit_sha": index.get("commit_sha"),
                "index_id": index.get("index_id"),
                "receipt": index.get("receipt"),
                "repo_path_identity": index.get("repo_path_identity"),
                "capability_profile_sha256": index.get(
                    "capability_profile_sha256"
                ),
                "fingerprint_sha256": index.get("fingerprint_sha256"),
                "metadata": index.get("metadata") or {},
                "impact_degraded_approval_id": index.get(
                    "impact_degraded_approval_id"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
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
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(receipt_path),
        "path_identity": _serializable_path_identity(receipt_path),
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
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "index_record_id": str(uuid.uuid4()),
                    "recorded_at": utc_now(),
                    "role": "baseline",
                    "commit_sha": resolved,
                    "repo_path": str(repo_path),
                    "repo_path_identity": _serializable_path_identity(
                        repo_path
                    ),
                    "capability_profile_sha256": analysis_workspace.get(
                        "capability_profile_sha256"
                    ),
                    "fingerprint_sha256": analysis_workspace.get(
                        "fingerprint_sha256"
                    ),
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
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "index_record_id": str(uuid.uuid4()),
                "recorded_at": utc_now(),
                "role": "workspace",
                "commit_sha": actual_head,
                "repo_path": str(repo_path),
                "repo_path_identity": _serializable_path_identity(repo_path),
                "index_id": normalized_index_id,
                "recommended_index_id": _recommended_index_name(
                    state_value, repo, "workspace"
                ),
                "receipt": receipt,
                "metadata": metadata,
                "fingerprint_sha256": fingerprint["sha256"],
                "capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
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
    metadata = _parse_json_object(args.metadata_json, "--metadata-json")
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        artifact_hash = _hash_artifact(artifact_path)
        digest = artifact_hash["sha256"]
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
        final_artifact_hash = _hash_artifact(artifact_path)
        if final_artifact_hash != artifact_hash:
            raise FlowError(
                "ARTIFACT_CHANGED",
                "artifact changed while it was being recorded",
                details={"path": str(artifact_path)},
            )
        state_value = _copy_state(current)
        artifact = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "kind": args.kind,
            "path": str(artifact_path),
            "path_identity": _serializable_path_identity(artifact_path),
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
    if args.gate not in APPROVAL_GATES:
        # Rejected before the lock so an unknown gate cannot consume a
        # revision or leave a permanent approval behind.
        raise FlowError(
            "INVALID_ARGUMENT",
            "--gate must name a defined approval gate: "
            + ", ".join(APPROVAL_GATES),
            details={"gate": args.gate, "gates": list(APPROVAL_GATES)},
        )
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
        if args.gate in FULL_GATES:
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


