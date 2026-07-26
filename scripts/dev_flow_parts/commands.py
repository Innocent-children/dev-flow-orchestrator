# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Task, recovery, scope, and preflight command handlers.
from __future__ import annotations

def _result(command: str, state_value: dict[str, Any], **extra: Any) -> dict[str, Any]:
    workflow = _workflow_progress(state_value)
    response: dict[str, Any] = {
        "ok": True,
        "command": command,
        "task_id": state_value["task_id"],
        "revision": state_value["revision"],
        "status": state_value["status"],
        "status_name": workflow["current"]["name"],
        "flow": _flow(state_value),
        "flow_name": workflow["flow"]["name"],
        "workspace_strategy": workflow["workspace_strategy"]["id"],
        "workspace_strategy_name": workflow["workspace_strategy"]["name"],
        "workflow": workflow,
        "index_selection": _index_selection(state_value),
    }
    response.update(extra)
    return response


SHOW_SECTION_FIELDS = {
    "approvals": "approvals",
    "artifacts": "artifacts",
    "blocked": "blocked",
    "cancelled": "cancelled",
    "repositories": "repositories",
    "review-snapshots": "review_snapshots",
    "risk": "risk_assessment",
    "route": "route",
    "tests": "tests",
    "workspace": "workspace",
}


def _show_summary(state_value: dict[str, Any]) -> dict[str, Any]:
    return {
        "updated_at": state_value.get("updated_at"),
        "repository_count": len(state_value.get("repositories") or []),
        "artifact_count": len(state_value.get("artifacts") or []),
        "test_count": len(state_value.get("tests") or []),
        "review_snapshot_count": len(
            state_value.get("review_snapshots") or []
        ),
        "approval_gates": sorted(
            (state_value.get("approvals") or {}).keys()
        ),
        "blocked": state_value.get("blocked"),
        "cancelled": state_value.get("cancelled"),
        "risk_decision": (
            (state_value.get("risk_assessment") or {}).get("decision")
        ),
    }


def _show_section_projection(
    state_value: dict[str, Any],
    sections: Sequence[str],
) -> dict[str, Any]:
    projection = {
        key: state_value.get(key)
        for key in (
            "schema_version",
            "evidence_contract_version",
            "task_id",
            "requirement",
            "status",
            "revision",
            "created_at",
            "updated_at",
            "flow",
        )
    }
    for section in sections:
        field = SHOW_SECTION_FIELDS[section]
        projection[field] = state_value.get(field)
    return projection


def _start_risk_assessment(
    flow: str,
    roots: Sequence[Path],
    args: argparse.Namespace,
) -> dict[str, Any]:
    policy = load_config(args.data_dir)["risk_policy"]
    policy_sha256 = _sha256_bytes(_json_bytes(policy))
    categories = sorted(
        {
            str(item)
            for item in (getattr(args, "change_category", None) or [])
        }
    )
    target_paths = sorted(
        {
            _normalize_repo_relative_path(item, "--target-path")
            for item in (getattr(args, "target_path", None) or [])
        }
    )
    reasons = _declared_risk_reasons(
        len(roots), categories, target_paths, policy
    )
    decision = "requires_full" if reasons else "safe"
    assessment = {
        "schema": "dev-flow-risk-assessment/v1",
        "decision": decision,
        "categories": categories,
        "target_paths": target_paths,
        "repository_count": len(roots),
        "policy": policy,
        "policy_sha256": policy_sha256,
        "reasons": reasons,
        "evaluated_at": utc_now(),
    }
    assessment["sha256"] = _sha256_bytes(_json_bytes(assessment))
    if flow == "lite" and decision != "safe":
        raise FlowError(
            "LITE_REQUIRES_FULL",
            "the declared change cannot safely use the lite flow",
            details={
                "required_flow": "full",
                "required_workspace_strategy": "worktree",
                "assessment": assessment,
            },
        )
    return assessment


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    requirement = (args.requirement_option or args.requirement or "").strip()
    if not requirement:
        raise FlowError("INVALID_ARGUMENT", "start requires a non-empty requirement")
    workspace_strategy = getattr(args, "workspace_strategy", None)
    if workspace_strategy is None:
        raise FlowError(
            "WORKSPACE_STRATEGY_REQUIRED",
            (
                "start requires an explicit --workspace-strategy selected "
                "before task creation"
            ),
            details={
                "choices": [
                    {
                        "flow": "lite",
                        "workspace_strategy": "in-place",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['in-place']}"
                            f"（{FLOW_NAMES_ZH['lite']}）"
                        ),
                    },
                    {
                        "flow": "lite",
                        "workspace_strategy": "branch",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['branch']}"
                            f"（{FLOW_NAMES_ZH['lite']}）"
                        ),
                    },
                    {
                        "flow": "full",
                        "workspace_strategy": "worktree",
                        "name": (
                            f"{WORKSPACE_STRATEGY_NAMES_ZH['worktree']}"
                            f"（{FLOW_NAMES_ZH['full']}）"
                        ),
                    },
                ]
            },
        )
    if workspace_strategy not in FLOW_BY_WORKSPACE_STRATEGY:
        raise FlowError(
            "INVALID_ARGUMENT",
            (
                "workspace strategy must be one of: "
                f"{', '.join(WORKSPACE_STRATEGIES)}"
            ),
            details={"workspace_strategy": workspace_strategy},
        )
    inferred_flow = FLOW_BY_WORKSPACE_STRATEGY[workspace_strategy]
    requested_flow = getattr(args, "flow", None)
    if requested_flow is not None and requested_flow not in FLOW_MODES:
        raise FlowError(
            "INVALID_ARGUMENT",
            f"flow must be one of: {', '.join(FLOW_MODES)}",
            details={"flow": requested_flow},
        )
    flow = requested_flow or inferred_flow
    if flow != inferred_flow:
        raise FlowError(
            "FLOW_WORKSPACE_STRATEGY_MISMATCH",
            (
                f"workspace strategy {workspace_strategy!r} is not valid "
                f"for the {flow} flow"
            ),
            details={
                "flow": flow,
                "workspace_strategy": workspace_strategy,
                "inferred_flow": inferred_flow,
                "allowed": [
                    strategy
                    for strategy, strategy_flow in (
                        FLOW_BY_WORKSPACE_STRATEGY.items()
                    )
                    if strategy_flow == flow
                ],
            },
        )
    task_id = args.task_id or f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    _validate_task_id(task_id)
    if not args.repo:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one --repo")
    roots: list[Path] = []
    for supplied in args.repo:
        root = _canonical_repo(supplied)
        if not any(_same_path(root, existing) for existing in roots):
            roots.append(root)
    if not roots:
        raise FlowError("INVALID_ARGUMENT", "start requires at least one distinct Git repository")
    for root in roots:
        _assert_path_in_scope(root, "repository", args.data_dir)
    common_dirs: list[tuple[Path, Path]] = []
    repository_claims: dict[str, dict[str, Any]] = {}
    for root in roots:
        common_dir = _git_evidence_path(root, "--git-common-dir")
        previous = next(
            (
                previous_root
                for previous_common_dir, previous_root in common_dirs
                if _same_path(common_dir, previous_common_dir)
            ),
            None,
        )
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
        common_dirs.append((common_dir, root))
        repository_claims[str(root)] = _repository_claim(root, common_dir)
    protected = list(
        dict.fromkeys(
            [*DEFAULT_PROTECTED_BRANCHES, *(args.protected_branch or [])]
        )
    )
    branch_bindings: dict[str, dict[str, Any]] = {}
    if workspace_strategy == "branch":
        for root in roots:
            branch = _git_optional(
                root, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            if not branch:
                raise FlowError(
                    "BRANCH_STRATEGY_NOT_READY",
                    (
                        "branch workspace strategy requires a named branch "
                        "to be checked out before start"
                    ),
                    details={"repository": str(root), "branch": branch},
                )
            head_ref = _git_optional(
                root,
                "symbolic-ref",
                "--quiet",
                "--no-recurse",
                "HEAD",
            )
            branch_ref = f"refs/heads/{branch}"
            if head_ref != branch_ref:
                raise FlowError(
                    "SYMBOLIC_WORKSPACE_BRANCH",
                    (
                        "branch workspace strategy requires HEAD to point "
                        "directly at the selected local branch"
                    ),
                    details={
                        "repository": str(root),
                        "branch": branch,
                        "branch_ref": branch_ref,
                        "head_ref": head_ref,
                    },
                )
            default_remote = _default_remote(root, branch)
            resolved_base = _default_base(
                root,
                default_remote,
                branch,
                protected,
            )
            protected_for_repo = [
                *protected,
                *([resolved_base] if resolved_base else []),
            ]
            branch_state = _branch_ref_state(
                root,
                branch,
                protected_for_repo,
            )
            head_sha = _git(root, "rev-parse", "HEAD")
            if branch_state.get("planned_ref_oid") != head_sha:
                raise FlowError(
                    "CHECKOUT_DRIFT",
                    "checked-out branch does not resolve to the current HEAD",
                    details={
                        "repository": str(root),
                        "approved_branch": branch,
                        "actual_branch": branch,
                        "approved_head_sha": branch_state.get(
                            "planned_ref_oid"
                        ),
                        "actual_head_sha": head_sha,
                    },
                )
            branch_bindings[str(root)] = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "branch": branch,
                "head_sha": head_sha,
                "initial_preflight_confirmed": False,
            }
    risk_assessment = _start_risk_assessment(flow, roots, args)
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
                "repository_claim": repository_claims[str(root)],
                "protected_branches": protected,
                "branch_binding": branch_bindings.get(str(root)),
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
    data_root = resolve_data_dir(args.data_dir)
    task_dir = _task_dir(task_id, data_root)
    identity = _task_identity(task_id)
    with _task_namespace_lock(data_root):
        tasks_root = data_root / "tasks"
        if tasks_root.is_dir():
            for candidate in tasks_root.iterdir():
                if not candidate.is_dir():
                    continue
                try:
                    candidate_identity = _task_identity(candidate.name)
                except FlowError:
                    # Non-portable legacy directories are not adoptable by a
                    # new task, but still reserve their literal case-folded
                    # spelling so creation cannot alias them.
                    candidate_identity = candidate.name.lower()
                if candidate_identity == identity:
                    code = "TASK_EXISTS" if candidate.name == task_id else "TASK_ID_COLLISION"
                    raise FlowError(
                        code,
                        (
                            f"task already exists: {task_id}"
                            if code == "TASK_EXISTS"
                            else "task id has the same portable identity as an existing task"
                        ),
                        details={
                            "task_id": task_id,
                            "existing_task_id": candidate.name,
                            "portable_identity": identity,
                        },
                    )
        existing_repository_claims = _active_repository_claims(data_root)
        for proposed_claim in repository_claims.values():
            for existing_claim in existing_repository_claims:
                conflict = _repository_claim_conflict(
                    proposed_claim, existing_claim
                )
                if conflict is None:
                    continue
                raise FlowError(
                    "REPOSITORY_CLAIM_CONFLICT",
                    (
                        "repository source checkout is already exclusively "
                        "claimed by an active task"
                    ),
                    details={
                        "task_id": task_id,
                        "repository": proposed_claim["canonical_path"],
                        "git_common_dir": proposed_claim["git_common_dir"],
                        "owner_task_id": existing_claim.get("task_id"),
                        "owner_repository_id": existing_claim.get(
                            "repository_id"
                        ),
                        "owner_repository": existing_claim.get(
                            "canonical_path"
                        ),
                        "owner_git_common_dir": existing_claim.get(
                            "git_common_dir"
                        ),
                        "conflict": conflict,
                        "sharing_rule": (
                            "active tasks exclusively own canonical source "
                            "paths and Git common directories"
                        ),
                    },
                )
        with _task_lock(task_dir):
            if (task_dir / "state.json").exists():
                raise FlowError(
                    "TASK_EXISTS",
                    f"task already exists: {task_id}",
                    details={"task_id": task_id},
                )
            _ensure_private_dir(task_dir / "artifacts")
            created = utc_now()
            state_value: dict[str, Any] = {
                "schema_version": TASK_SCHEMA_VERSION,
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "confirmation_contract_version": (
                    CONFIRMATION_CONTRACT_VERSION
                ),
                "task_id": task_id,
                "requirement": requirement,
                "status": "INTAKE",
                "revision": 0,
                "created_at": created,
                "updated_at": created,
                "flow": flow,
                "risk_assessment": risk_assessment,
                "route": None,
                "repositories": repositories,
                "artifacts": [],
                "approvals": {},
                "tests": [],
                "review_snapshots": [],
                "mutation_recoveries": [],
                "impact_generation": 0,
                "planning_generation": 0,
                "workspace": {
                    "strategy": workspace_strategy,
                    "ready": False,
                    "generation": 0,
                },
                "blocked": None,
                "cancelled": None,
            }
            _commit_state(
                None,
                state_value,
                task_dir,
                "task_started",
                {
                    "repository_ids": sorted(ids),
                    "risk_assessment_sha256": risk_assessment["sha256"],
                },
            )
    return _result("start", state_value, task=state_value)


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    state_value = load_state(_task_arg(args), args.data_dir)
    if getattr(args, "compact", False):
        return _result(
            "show",
            state_value,
            summary=_show_summary(state_value),
        )
    sections = getattr(args, "section", None)
    if sections:
        return _result(
            "show",
            state_value,
            task=_show_section_projection(state_value, sections),
            sections=list(sections),
        )
    return _result("show", state_value, task=state_value)


def _archive_quarantine(
    task_dir: Path, quarantine: dict[str, Any]
) -> Path:
    recovery_id = str(
        quarantine.get("recovery_id") or uuid.uuid4()
    )
    source = _quarantine_path(task_dir)
    archive = task_dir / f"mutation-quarantine.recovered-{recovery_id}.json"
    try:
        os.replace(source, archive)
    except OSError as exc:
        raise FlowError(
            "QUARANTINE_ARCHIVE_FAILED",
            "validated quarantine could not be archived; mutations remain blocked",
            details={
                "source": str(source),
                "archive": str(archive),
                "error": str(exc),
            },
        ) from exc
    _set_private_permissions(archive, 0o600)
    return archive


def command_recover_quarantine(
    args: argparse.Namespace,
) -> dict[str, Any]:
    task_id = _task_arg(args)
    task_dir = _task_dir(task_id, args.data_dir)
    with _task_lock(task_dir, allow_quarantine=True):
        current = load_state(task_id, args.data_dir)
        _check_revision(current, args.expected_revision)
        quarantine = _read_quarantine(task_dir)
        if quarantine is None:
            raise FlowError(
                "QUARANTINE_NOT_FOUND",
                "task has no active mutation quarantine",
                details={"task_id": task_id},
            )
        _require_current_evidence(quarantine, "mutation quarantine")
        recovery_id = quarantine.get("recovery_id")
        validated_revision = quarantine.get(
            "recovery_validated_revision"
        )
        recoveries = current.get("mutation_recoveries") or []
        completed = next(
            (
                item
                for item in recoveries
                if isinstance(item, dict)
                and item.get("recovery_id") == recovery_id
            ),
            None,
        )
        if (
            recovery_id
            and validated_revision == current.get("revision")
            and completed
        ):
            archive = _archive_quarantine(task_dir, quarantine)
            return _result(
                "recover-quarantine",
                current,
                recovered=True,
                unchanged=True,
                recovery=completed,
                archive_path=str(archive),
            )
        compatible_revisions = {
            quarantine.get("state_revision"),
            quarantine.get("expected_committed_revision"),
            quarantine.get("committed_revision"),
        }
        if current.get("revision") not in compatible_revisions:
            raise FlowError(
                "QUARANTINE_REVISION_CHANGED",
                "task revision changed after the quarantined child was recorded",
                details={
                    "quarantine_revision": quarantine.get(
                        "state_revision"
                    ),
                    "expected_committed_revision": quarantine.get(
                        "expected_committed_revision"
                    ),
                    "committed_revision": quarantine.get(
                        "committed_revision"
                    ),
                    "current_revision": current.get("revision"),
                },
            )
        if _quarantine_processes_alive(quarantine):
            raise FlowError(
                "QUARANTINE_CHILD_ACTIVE",
                "the quarantined child process is still active",
                details={"pid": quarantine.get("pid")},
            )
        validation = _validate_quarantine_postconditions(
            current, task_dir, quarantine
        )
        recovery_id = str(uuid.uuid4())
        recovery = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "recovery_id": recovery_id,
            "recovered_at": utc_now(),
            "quarantined_pid": quarantine.get("pid"),
            "quarantined_command": quarantine.get("command"),
            "state_revision": current.get("revision"),
            "validation": validation,
        }
        validated_quarantine = {
            **quarantine,
            "recovery_id": recovery_id,
            "recovery_validated_at": recovery["recovered_at"],
            "recovery_validated_revision": int(
                current.get("revision", 0)
            )
            + 1,
            "validation": validation,
        }
        _atomic_write_json(
            _quarantine_path(task_dir), validated_quarantine
        )
        state_value = _copy_state(current)
        state_value.setdefault("mutation_recoveries", []).append(recovery)
        _commit_state(
            current,
            state_value,
            task_dir,
            "mutation_quarantine_recovered",
            {
                "recovery_id": recovery_id,
                "quarantined_pid": quarantine.get("pid"),
            },
        )
        archive = _archive_quarantine(task_dir, validated_quarantine)
    return _result(
        "recover-quarantine",
        state_value,
        recovered=True,
        recovery=recovery,
        archive_path=str(archive),
    )


def _atomic_evidence_summary(path: Path) -> dict[str, Any]:
    """Describe one side of a rollback pair well enough to decide about it."""

    summary: dict[str, Any] = {"path": str(path), "present": path.is_file()}
    if not summary["present"]:
        return summary
    try:
        summary["size"] = path.stat().st_size
        summary["sha256"] = _sha256_file(path)
        raw = path.read_bytes()
    except OSError as exc:
        summary["readable"] = False
        summary["error"] = str(exc)
        return summary
    summary["readable"] = True
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        summary["json"] = False
        return summary
    summary["json"] = True
    if isinstance(value, dict):
        summary["schema"] = {
            key: value.get(key)
            for key in (
                "schema_version",
                "evidence_contract_version",
                "task_id",
                "status",
                "revision",
                "updated_at",
            )
            if key in value
        }
    return summary


def _classify_rollback_candidate(
    destination: Path, rollback: Path
) -> dict[str, Any]:
    """Decide whether rollback evidence can be cleared without a choice."""

    destination_summary = _atomic_evidence_summary(destination)
    rollback_summary = _atomic_evidence_summary(rollback)
    if destination_summary.get("present") and destination_summary.get(
        "sha256"
    ) == rollback_summary.get("sha256"):
        # The interrupted writer either had not replaced the destination yet
        # or had already restored it; the evidence is a proven duplicate.
        resolution = "identical"
    elif (
        not destination_summary.get("present")
        and rollback_summary.get("size") == 0
    ):
        # The interrupted write was creating a new file, so the empty
        # placeholder preserves nothing and no destination was committed.
        resolution = "uncommitted"
    else:
        resolution = "mismatch"
    return {
        "resolution": resolution,
        "destination": destination_summary,
        "rollback": rollback_summary,
    }


def _atomic_rollback_candidates(
    data_root: Path,
) -> list[tuple[Path, Path]]:
    """Every controller-owned destination that still carries rollback evidence.

    The scan covers the controller's own state files only: the data root and
    every task directory.  Managed worktrees hold repository content, never
    atomically written controller state.
    """

    found: list[Path] = []
    if data_root.is_dir():
        found.extend(sorted(data_root.glob(f".*{_ROLLBACK_MARKER}*")))
        tasks_root = data_root / "tasks"
        if tasks_root.is_dir():
            found.extend(
                sorted(tasks_root.rglob(f".*{_ROLLBACK_MARKER}*"))
            )
    pairs: list[tuple[Path, Path]] = []
    for candidate in found:
        if not candidate.is_file():
            continue
        destination = _rollback_evidence_destination(candidate)
        if destination is None:
            continue
        pairs.append((destination, candidate))
    return pairs


def _atomic_recovery_lock(
    data_root: Path, destination: Path
) -> contextlib.AbstractContextManager[None]:
    """Hold the same lock the interrupted writer of this file would hold."""

    tasks_root = data_root / "tasks"
    try:
        relative = destination.relative_to(tasks_root)
    except ValueError:
        relative = None
    if relative is not None and relative.parts:
        # A quarantined task is exactly the case that needs recovering.
        return _task_lock(
            tasks_root / relative.parts[0], allow_quarantine=True
        )
    if destination.parent == data_root:
        if destination.name == "config.json":
            return _config_lock(data_root)
        if destination.name == "workspace-registry.json":
            return _workspace_registry_lock(data_root)
    return contextlib.nullcontext()


def _discard_rollback_evidence(rollback: Path) -> None:
    try:
        rollback.unlink()
    except OSError as exc:
        raise FlowError(
            "ATOMIC_ROLLBACK_CLEANUP_FAILED",
            "rollback evidence could not be removed",
            details={"rollback": str(rollback), "error": str(exc)},
        ) from exc


def _restore_rollback_evidence(destination: Path, rollback: Path) -> None:
    try:
        os.replace(rollback, destination)
    except OSError as exc:
        raise FlowError(
            "ATOMIC_ROLLBACK_RESTORE_FAILED",
            "rollback evidence could not be restored over the destination",
            details={
                "path": str(destination),
                "rollback": str(rollback),
                "error": str(exc),
            },
        ) from exc
    _set_private_permissions(destination, 0o600)


def command_recover_atomic_write(
    args: argparse.Namespace,
) -> dict[str, Any]:
    data_root = resolve_data_dir(args.data_dir)
    selected: Path | None = None
    if args.path:
        supplied = Path(args.path).expanduser()
        if not supplied.is_absolute():
            raise FlowError(
                "INVALID_ARGUMENT",
                "--path requires an absolute path",
                details={"path": args.path},
            )
        # Both spellings are accepted: the blocked destination, or one of the
        # rollback files named by details.rollback_candidates.
        selected = _rollback_evidence_destination(supplied) or supplied
    if args.resolve and selected is None:
        raise FlowError(
            "INVALID_ARGUMENT",
            "--resolve requires --path naming one blocked destination",
        )
    if args.rollback_sha256 and not SHA256_RE.fullmatch(
        args.rollback_sha256
    ):
        raise FlowError(
            "INVALID_ARGUMENT",
            "--rollback-sha256 must be 64 lowercase hexadecimal characters",
        )
    candidates = [
        pair
        for pair in _atomic_rollback_candidates(data_root)
        if selected is None or _same_path(pair[0], selected)
    ]
    reports = [
        _classify_rollback_candidate(destination, rollback)
        for destination, rollback in candidates
    ]
    response: dict[str, Any] = {
        "ok": True,
        "command": "recover-atomic-write",
        "data_dir": str(data_root),
        "changed": False,
        "candidates": reports,
        "removed": [],
        "restored": [],
    }
    if not (args.apply or args.resolve):
        return response
    if not candidates:
        raise FlowError(
            "ATOMIC_ROLLBACK_NOT_FOUND",
            "no rollback evidence is present for the selected scope",
            details={
                "data_dir": str(data_root),
                "path": str(selected) if selected else None,
            },
        )
    if args.resolve:
        if len(candidates) > 1:
            raise FlowError(
                "ATOMIC_ROLLBACK_AMBIGUOUS",
                "--resolve needs exactly one rollback file; name it with --path",
                details={
                    "path": str(selected),
                    "rollback_candidates": [
                        str(rollback) for _, rollback in candidates
                    ],
                },
            )
        if not args.rollback_sha256:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--resolve requires --rollback-sha256 naming the inspected evidence",
                details={"candidate": reports[0]},
            )
        destination, rollback = candidates[0]
        with _atomic_recovery_lock(data_root, destination):
            report = _classify_rollback_candidate(destination, rollback)
            if report["rollback"].get("sha256") != args.rollback_sha256:
                raise FlowError(
                    "ATOMIC_ROLLBACK_MISMATCH",
                    "--rollback-sha256 does not name the current rollback evidence",
                    details={
                        "expected_sha256": report["rollback"].get("sha256"),
                        "provided_sha256": args.rollback_sha256,
                        "candidate": report,
                    },
                )
            if args.resolve == "restore-rollback":
                _restore_rollback_evidence(destination, rollback)
                response["restored"].append(str(destination))
            else:
                _discard_rollback_evidence(rollback)
                response["removed"].append(str(rollback))
        response["changed"] = True
        response["candidates"] = [report]
        response["resolved"] = args.resolve
        return response
    blocked: list[dict[str, Any]] = []
    for destination, rollback in candidates:
        with _atomic_recovery_lock(data_root, destination):
            report = _classify_rollback_candidate(destination, rollback)
            if report["resolution"] == "mismatch":
                blocked.append(report)
                continue
            _discard_rollback_evidence(rollback)
        response["removed"].append(str(rollback))
    response["changed"] = bool(response["removed"])
    if blocked:
        # Fail closed: differing content is a decision about committed state,
        # never something this command may make on the user's behalf.
        raise FlowError(
            "ATOMIC_ROLLBACK_MISMATCH",
            (
                "rollback evidence differs from the committed destination and "
                "needs an explicit resolution"
            ),
            details={
                "data_dir": str(data_root),
                "removed": response["removed"],
                "blocked": blocked,
                "resolutions": ["keep-current", "restore-rollback"],
            },
        )
    return response


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    tasks_dir = resolve_data_dir(args.data_dir) / "tasks"
    values: list[dict[str, Any]] = []
    if tasks_dir.is_dir():
        for state_file in tasks_dir.glob("*/state.json"):
            try:
                state_value = load_state(state_file)
            except FlowError as exc:
                if exc.code == "EVIDENCE_CONTRACT_UNSUPPORTED":
                    raise
                continue
            if args.active_only and state_value.get("status") in TERMINAL_STATES:
                continue
            if args.status and state_value.get("status") not in args.status:
                continue
            workflow = _workflow_progress(state_value)
            values.append(
                {
                    "task_id": state_value.get("task_id"),
                    "requirement": state_value.get("requirement"),
                    "status": state_value.get("status"),
                    "status_name": workflow["current"]["name"],
                    "flow": workflow["flow"]["id"],
                    "flow_name": workflow["flow"]["name"],
                    "workspace_strategy": workflow["workspace_strategy"]["id"],
                    "workspace_strategy_name": workflow[
                        "workspace_strategy"
                    ]["name"],
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
            matches = [
                configured
                for configured in scope[key]
                if _same_path(Path(root), Path(configured))
            ]
            if len(matches) != 1:
                raise FlowError(
                    "SCOPE_PATH_NOT_CONFIGURED",
                    f"{flag} does not match a configured scope directory",
                    details={
                        "path": root,
                        "configured": list(scope[key]),
                        "identity_matches": matches,
                    },
                )
            scope[key].remove(matches[0])
    # Adding the first included directory is what turns the allowlist on; an
    # include recorded while the mode stays "all" would silently do nothing.
    activates = args.mode is None and scope["mode"] == "all" and not scope["include"]
    for option, key in (("add", "include"), ("add_exclude", "exclude")):
        for supplied in getattr(args, option) or []:
            root = _normalize_scope_root(supplied, "--" + option.replace("_", "-"))
            if not any(
                _same_path(Path(root), Path(configured))
                for configured in scope[key]
            ):
                scope[key].append(root)
    if activates and scope["include"]:
        scope["mode"] = "allowlist"


def _apply_risk_policy_changes(
    risk_policy: dict[str, Any], args: argparse.Namespace
) -> None:
    if getattr(args, "reset_protected_paths", False):
        risk_policy["protected_paths"] = list(
            DEFAULT_PROTECTED_PATH_GLOBS
        )
    for supplied in getattr(args, "remove_protected_path", None) or []:
        pattern = _normalize_risk_glob(
            supplied, "--remove-protected-path"
        )
        if pattern not in risk_policy["protected_paths"]:
            raise FlowError(
                "RISK_GLOB_NOT_CONFIGURED",
                "--remove-protected-path does not match a configured glob",
                details={
                    "glob": pattern,
                    "configured": list(risk_policy["protected_paths"]),
                },
            )
        risk_policy["protected_paths"].remove(pattern)
    for supplied in getattr(args, "add_protected_path", None) or []:
        pattern = _normalize_risk_glob(supplied, "--add-protected-path")
        if pattern not in risk_policy["protected_paths"]:
            risk_policy["protected_paths"].append(pattern)


def command_scope(args: argparse.Namespace) -> dict[str, Any]:
    path = config_path(args.data_dir)
    edits = (
        args.clear
        or args.mode
        or args.add
        or args.remove
        or args.add_exclude
        or args.remove_exclude
        or getattr(args, "add_protected_path", None)
        or getattr(args, "remove_protected_path", None)
        or getattr(args, "reset_protected_paths", False)
    )
    if edits:
        with _config_lock(resolve_data_dir(args.data_dir)):
            try:
                config = load_config(args.data_dir)
                before = _copy_state(config)
            except FlowError:
                # An unusable configuration must still be resettable.
                if not args.clear:
                    raise
                before = None
            if args.clear:
                config = _default_config()
            _apply_scope_changes(config["scope"], args)
            _apply_risk_policy_changes(config["risk_policy"], args)
            config["schema_version"] = CONFIG_SCHEMA_VERSION
            config["scope"] = _normalize_scope(config["scope"])
            config["risk_policy"] = _normalize_risk_policy(
                config["risk_policy"]
            )
            _atomic_write_json(path, config)
            stored = config
    else:
        before = stored = load_config(args.data_dir)
    effective = resolve_scope(args.data_dir)
    overrides = effective.pop("overrides", {})
    response = {
        "ok": True,
        "command": "scope",
        "config_path": str(path),
        "changed": stored != before,
        "scope": stored["scope"],
        "risk_policy": stored["risk_policy"],
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


PREFLIGHT_PREVIEW_TOKEN_VERSION = "v3"
PREFLIGHT_DECISION_FIELDS = (
    "evidence_contract_version",
    "repository_root",
    "repository_path_identity",
    "repository_root_identity",
    "git_dir",
    "git_dir_identity",
    "git_common_dir",
    "git_common_dir_identity",
    "branch",
    "head_sha",
    "remote",
    "remote_url",
    "remote_url_sha256",
    "base_branch",
    "base_candidate_ref",
    "base_candidate_sha",
    "fetch_refspec",
    "conflicts",
    "conflict_paths_sha256",
    "operations",
    "blockers",
    "ready",
)
PREFLIGHT_OBSERVATION_FIELDS = (
    *PREFLIGHT_DECISION_FIELDS,
    "staged",
    "staged_paths_sha256",
    "unstaged",
    "unstaged_paths_sha256",
    "untracked",
    "untracked_paths_sha256",
    "dirty",
)
PREFLIGHT_LIST_FIELDS = {
    "blockers",
    "conflicts",
    "staged",
    "unstaged",
    "untracked",
}
def _preflight_repository_projection(
    selected: list[dict[str, Any]],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    repositories: list[dict[str, Any]] = []
    for repo in selected:
        evidence = repo["preflight"]
        projected: dict[str, Any] = {}
        for field in fields:
            value = evidence.get(field)
            if field in PREFLIGHT_LIST_FIELDS and isinstance(value, list):
                value = sorted(value)
            projected[field] = value
        repositories.append(
            {
                "id": repo["id"],
                "path": repo.get("canonical_path") or repo.get("path"),
                "preflight": projected,
            }
        )
    repositories.sort(key=lambda item: str(item["id"]))
    return repositories


def _preflight_preview_hashes(
    current: dict[str, Any],
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    selection_complete: bool,
    args: argparse.Namespace,
) -> tuple[str, str]:
    common = {
        "task_id": current["task_id"],
        "revision": current["revision"],
        "from_status": current["status"],
        "to_status": state_value["status"],
        "flow": _flow(state_value),
        "workspace_strategy": _workspace_strategy(state_value),
        "repository_ids": sorted(repo["id"] for repo in selected),
        "selection_complete": selection_complete,
        "all_checked": all(
            repo.get("preflight") is not None
            for repo in state_value.get("repositories", [])
        ),
        "remote_override": args.remote,
        "base_override": args.base,
        "blockers": sorted(
            (
                {
                    "repository_id": item["repository_id"],
                    "blockers": sorted(item["blockers"]),
                }
                for item in blockers
            ),
            key=lambda item: str(item["repository_id"]),
        ),
    }
    decision_payload = {
        **common,
        "repositories": _preflight_repository_projection(
            selected,
            PREFLIGHT_DECISION_FIELDS,
        ),
    }
    observation_payload = {
        **common,
        "repositories": _preflight_repository_projection(
            selected,
            PREFLIGHT_OBSERVATION_FIELDS,
        ),
    }
    return (
        _sha256_bytes(_json_bytes(decision_payload)),
        _sha256_bytes(_json_bytes(observation_payload)),
    )


def _preflight_preview_token(
    decision_sha256: str,
    observation_sha256: str,
) -> str:
    return (
        f"{PREFLIGHT_PREVIEW_TOKEN_VERSION}:"
        f"{decision_sha256}:{observation_sha256}"
    )


def _parse_preflight_preview_token(token: str | None) -> tuple[str | None, str | None]:
    if not isinstance(token, str):
        return None, None
    version, separator, remainder = token.partition(":")
    decision_sha256, second_separator, observation_sha256 = (
        remainder.partition(":")
    )
    if (
        version != PREFLIGHT_PREVIEW_TOKEN_VERSION
        or not separator
        or not second_separator
        or not SHA256_RE.fullmatch(decision_sha256)
        or not SHA256_RE.fullmatch(observation_sha256)
    ):
        return None, None
    return decision_sha256, observation_sha256


def _assert_branch_checkout_binding(
    state_value: dict[str, Any], repo: dict[str, Any]
) -> None:
    if _workspace_strategy(state_value) != "branch":
        return
    binding = repo.get("branch_binding")
    if not isinstance(binding, dict):
        raise FlowError(
            "CHECKOUT_BINDING_MISSING",
            "branch workspace task has no start-time checkout binding",
            details={"repository_id": repo.get("id")},
        )
    _require_current_evidence(
        binding, f"branch-binding:{repo.get('id')}"
    )
    path = Path(repo["path"])
    actual_branch = _git_optional(
        path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    actual_head_ref = _git_optional(
        path,
        "symbolic-ref",
        "--quiet",
        "--no-recurse",
        "HEAD",
    )
    actual_head = _git_optional(path, "rev-parse", "HEAD")
    approved_branch = binding.get("branch")
    approved_head_ref = (
        f"refs/heads/{approved_branch}"
        if isinstance(approved_branch, str)
        else None
    )
    approved_head = binding.get("head_sha")
    initial_head_required = (
        binding.get("initial_preflight_confirmed") is not True
    )
    if (
        actual_branch != approved_branch
        or actual_head_ref != approved_head_ref
        or (initial_head_required and actual_head != approved_head)
    ):
        raise FlowError(
            "CHECKOUT_DRIFT",
            "branch workspace checkout changed after task start",
            details={
                "repository_id": repo.get("id"),
                "approved_branch": approved_branch,
                "actual_branch": actual_branch,
                "approved_head_ref": approved_head_ref,
                "actual_head_ref": actual_head_ref,
                "approved_head_sha": approved_head,
                "actual_head_sha": actual_head,
                "initial_head_required": initial_head_required,
            },
        )


def _guard_branch_workspace_base(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    if _workspace_strategy(state_value) != "branch":
        return
    branch = evidence.get("branch")
    base_branch = evidence.get("base_branch")
    if not isinstance(branch, str) or not isinstance(base_branch, str):
        return
    try:
        _branch_ref_state(
            Path(repo["path"]),
            branch,
            [base_branch],
        )
    except FlowError as exc:
        if exc.code != "PROTECTED_BRANCH":
            raise
        blockers = evidence.setdefault("blockers", [])
        if "branch_matches_base" not in blockers:
            blockers.append("branch_matches_base")
        evidence["ready"] = False


def _preflight_blockers(
    state_value: dict[str, Any],
    selected: list[dict[str, Any]],
    selection_complete: bool,
) -> list[dict[str, Any]]:
    repositories = (
        state_value["repositories"] if selection_complete else selected
    )
    return [
        {
            "repository_id": repo["id"],
            "blockers": repo["preflight"]["blockers"],
        }
        for repo in repositories
        if repo.get("preflight") and repo["preflight"]["blockers"]
    ]


def _apply_preflight_outcome(
    current: dict[str, Any],
    state_value: dict[str, Any],
    *,
    selection_complete: bool,
    all_checked: bool,
    blockers: list[dict[str, Any]],
) -> None:
    if selection_complete and blockers:
        previous = (
            current["status"]
            if current["status"] != "BLOCKED"
            else (current.get("blocked") or {}).get(
                "from_status",
                "INTAKE",
            )
        )
        state_value["status"] = "BLOCKED"
        state_value["blocked"] = {
            "phase": "preflight",
            "from_status": previous,
            "reason": "preflight blockers detected",
            "details": blockers,
            "at": utc_now(),
        }
    elif selection_complete and all_checked:
        state_value["status"] = "PREFLIGHTED"
        state_value["blocked"] = None


def command_preflight(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    if args.preview and args.confirm_preview:
        raise FlowError(
            "INVALID_ARGUMENT",
            "preflight accepts either --preview or --confirm-preview, not both",
        )
    if getattr(args, "accept_evidence_refresh", False) and not args.confirm_preview:
        raise FlowError(
            "INVALID_ARGUMENT",
            "--accept-evidence-refresh requires --confirm-preview",
        )
    with _locked_state(task_id, args.data_dir, args.expected_revision) as (task_dir, current):
        if not args.preview and not args.confirm_preview:
            raise FlowError(
                "PREFLIGHT_PREVIEW_REQUIRED",
                (
                    "preflight must first run with --preview, then rerun with "
                    "--confirm-preview <token> after any required status-edge confirmation"
                ),
            )
        allowed = {"INTAKE", "PREFLIGHTED"}
        if current.get("status") == "BLOCKED" and (current.get("blocked") or {}).get("phase") == "preflight":
            allowed.add("BLOCKED")
        _assert_status(current, allowed, "preflight")
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        selected_ids = {repo["id"] for repo in selected}
        configured_ids = {
            repo["id"] for repo in state_value["repositories"]
        }
        selection_complete = selected_ids == configured_ids
        if (
            current.get("status") == "PREFLIGHTED"
            and not selection_complete
        ):
            raise FlowError(
                "PREFLIGHT_FULL_SELECTION_REQUIRED",
                (
                    "refreshing a preflighted task requires selecting every "
                    "configured repository"
                ),
                details={
                    "selected_repository_ids": sorted(selected_ids),
                    "required_repository_ids": sorted(configured_ids),
                },
            )
        for repo in selected:
            try:
                _assert_branch_checkout_binding(state_value, repo)
            except FlowError as exc:
                if (
                    args.confirm_preview
                    and exc.code == "CHECKOUT_DRIFT"
                ):
                    raise FlowError(
                        "PREFLIGHT_PREVIEW_STALE",
                        (
                            "branch checkout changed after preview; rerun "
                            "--preview after restoring the approved checkout"
                        ),
                        details=exc.details,
                    ) from exc
                raise
            repo["preflight"] = _preflight_repo(
                repo,
                args.remote,
                args.base,
                capture_fingerprint=False,
            )
            _guard_branch_workspace_base(
                state_value, repo, repo["preflight"]
            )
        all_checked = all(repo.get("preflight") is not None for repo in state_value["repositories"])
        blockers = _preflight_blockers(
            state_value,
            selected,
            selection_complete,
        )
        _apply_preflight_outcome(
            current,
            state_value,
            selection_complete=selection_complete,
            all_checked=all_checked,
            blockers=blockers,
        )
        decision_sha256, observation_sha256 = _preflight_preview_hashes(
            current,
            state_value,
            selected,
            blockers,
            selection_complete,
            args,
        )
        preview_token = _preflight_preview_token(
            decision_sha256,
            observation_sha256,
        )
        prospective_workflow = _workflow_progress(state_value)
        transition_preview = {
            "token": preview_token,
            "decision_sha256": decision_sha256,
            "observation_sha256": observation_sha256,
            "changes_status": state_value["status"] != current["status"],
            "from": {
                "id": current["status"],
                "name": STATE_NAMES_ZH.get(current["status"], current["status"]),
            },
            "target": prospective_workflow["current"],
            "remaining": prospective_workflow["remaining"],
        }
        repositories = [
            {"id": repo["id"], "preflight": repo["preflight"]}
            for repo in selected
        ]
        if args.preview:
            return _result(
                "preflight-preview",
                current,
                ready=selection_complete and all_checked and not blockers,
                selection_complete=selection_complete,
                confirmation_scope={
                    "decision": "must_remain_unchanged",
                    "observation": (
                        "refresh_requires_explicit_acceptance"
                    ),
                    "evidence": "captured_on_confirm",
                },
                transition_preview=transition_preview,
                repositories=repositories,
            )
        (
            approved_decision_sha256,
            approved_observation_sha256,
        ) = _parse_preflight_preview_token(args.confirm_preview)
        token_contract_current = (
            isinstance(args.confirm_preview, str)
            and args.confirm_preview.startswith(
                f"{PREFLIGHT_PREVIEW_TOKEN_VERSION}:"
            )
        )
        if (
            approved_decision_sha256 is None
            or not secrets.compare_digest(
                approved_decision_sha256,
                decision_sha256,
            )
        ):
            raise FlowError(
                "PREFLIGHT_PREVIEW_STALE",
                (
                    "the preflight status decision changed after preview; rerun "
                    "--preview and confirm the newly reported status edge"
                ),
                details={
                    "reason": (
                        "status_decision_changed"
                        if approved_decision_sha256 is not None
                        else (
                            "invalid_token"
                            if token_contract_current
                            else "token_contract_changed"
                        )
                    ),
                    "from_status": current["status"],
                    "prospective_status": state_value["status"],
                    "revision": current["revision"],
                    "approved_decision_sha256": approved_decision_sha256,
                    "current_decision_sha256": decision_sha256,
                },
            )
        observation_changed_before_capture = (
            approved_observation_sha256 is None
            or not secrets.compare_digest(
                approved_observation_sha256,
                observation_sha256,
            )
        )
        if (
            observation_changed_before_capture
            and not args.accept_evidence_refresh
        ):
            raise FlowError(
                "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
                (
                    "the preflight worktree summary changed after preview; "
                    "inspect the current evidence and rerun the same token with "
                    "--accept-evidence-refresh"
                ),
                details={
                    "token_reusable": True,
                    "required_flag": "--accept-evidence-refresh",
                    "acceptance_scope": (
                        "current_observation_at_successful_confirm"
                    ),
                    "preview_observation_sha256": (
                        approved_observation_sha256
                    ),
                    "current_observation_sha256": observation_sha256,
                    "repositories": repositories,
                },
            )

        captured_fingerprints: dict[str, dict[str, Any]] = {}
        for repo in selected:
            captured_fingerprints[repo["id"]] = _fingerprint_repo(
                Path(repo["path"])
            )

        # Re-sample every selected repository only after all complete
        # fingerprints have finished. This detects decision-level drift
        # observed after capture across every repository without repeating the
        # byte-complete scan; external repositories cannot form one atomic
        # cross-repository snapshot.
        for repo in selected:
            try:
                _assert_branch_checkout_binding(state_value, repo)
            except FlowError as exc:
                if exc.code == "CHECKOUT_DRIFT":
                    raise FlowError(
                        "PREFLIGHT_PREVIEW_STALE",
                        (
                            "branch checkout changed while preflight evidence "
                            "was captured; rerun --preview"
                        ),
                        details={
                            **exc.details,
                            "reason": "decision_changed_during_capture",
                        },
                    ) from exc
                raise
            post_capture = _preflight_repo(
                repo,
                args.remote,
                args.base,
                capture_fingerprint=False,
            )
            _guard_branch_workspace_base(
                state_value,
                repo,
                post_capture,
            )
            fingerprint = captured_fingerprints[repo["id"]]
            identity_matches = (
                isinstance(fingerprint.get("path"), str)
                and _same_path(
                    Path(fingerprint["path"]),
                    Path(repo["path"]),
                )
                and isinstance(fingerprint.get("root"), str)
                and _same_path(
                    Path(fingerprint["root"]),
                    Path(post_capture["repository_root"]),
                )
                and isinstance(fingerprint.get("git_dir"), str)
                and _same_path(
                    Path(fingerprint["git_dir"]),
                    Path(post_capture["git_dir"]),
                )
                and isinstance(fingerprint.get("git_common_dir"), str)
                and _same_path(
                    Path(fingerprint["git_common_dir"]),
                    Path(post_capture["git_common_dir"]),
                )
                and fingerprint.get("branch")
                == post_capture.get("branch")
                and fingerprint.get("head_sha")
                == post_capture.get("head_sha")
            )
            if not identity_matches:
                raise FlowError(
                    "PREFLIGHT_PREVIEW_STALE",
                    (
                        "repository identity changed while complete preflight "
                        "evidence was captured; rerun --preview"
                    ),
                    details={
                        "repository_id": repo["id"],
                        "reason": "decision_changed_during_capture",
                        "fingerprint_branch": fingerprint.get("branch"),
                        "observed_branch": post_capture.get("branch"),
                        "fingerprint_head_sha": fingerprint.get("head_sha"),
                        "observed_head_sha": post_capture.get("head_sha"),
                    },
                )
            post_capture.update(
                {
                    "evidence_complete": True,
                    "capture_phase": "confirm",
                    "worktree_fingerprint_sha256": fingerprint["sha256"],
                    "capability_profile": fingerprint[
                        "capability_profile"
                    ],
                    "capability_profile_sha256": fingerprint[
                        "capability_profile_sha256"
                    ],
                    "tracked_worktree_manifest_sha256": fingerprint[
                        "tracked_worktree_manifest_sha256"
                    ],
                }
            )
            repo["preflight"] = post_capture

        all_checked = all(
            repo.get("preflight") is not None
            for repo in state_value["repositories"]
        )
        blockers = _preflight_blockers(
            state_value,
            selected,
            selection_complete,
        )
        state_value["status"] = current["status"]
        state_value["blocked"] = _copy_state(current).get("blocked")
        _apply_preflight_outcome(
            current,
            state_value,
            selection_complete=selection_complete,
            all_checked=all_checked,
            blockers=blockers,
        )
        post_decision_sha256, captured_observation_sha256 = (
            _preflight_preview_hashes(
                current,
                state_value,
                selected,
                blockers,
                selection_complete,
                args,
            )
        )
        if not secrets.compare_digest(
            decision_sha256,
            post_decision_sha256,
        ):
            raise FlowError(
                "PREFLIGHT_PREVIEW_STALE",
                (
                    "the preflight status decision changed while complete "
                    "evidence was captured; rerun --preview"
                ),
                details={
                    "reason": "decision_changed_during_capture",
                    "before_capture_decision_sha256": decision_sha256,
                    "after_capture_decision_sha256": (
                        post_decision_sha256
                    ),
                    "from_status": current["status"],
                    "prospective_status": state_value["status"],
                    "revision": current["revision"],
                },
            )
        observation_changed_since_preview = (
            approved_observation_sha256 is None
            or not secrets.compare_digest(
                approved_observation_sha256,
                captured_observation_sha256,
            )
        )
        evidence_refresh_observed = (
            observation_changed_before_capture
            or observation_changed_since_preview
        )
        evidence_refresh_accepted = bool(
            args.accept_evidence_refresh
            and evidence_refresh_observed
        )
        repositories = [
            {"id": repo["id"], "preflight": repo["preflight"]}
            for repo in selected
        ]
        if (
            observation_changed_since_preview
            and not args.accept_evidence_refresh
        ):
            raise FlowError(
                "PREFLIGHT_EVIDENCE_REFRESH_REQUIRED",
                (
                    "the preflight worktree summary changed while complete "
                    "evidence was captured; inspect the current evidence and "
                    "rerun the same token with --accept-evidence-refresh"
                ),
                details={
                    "token_reusable": True,
                    "required_flag": "--accept-evidence-refresh",
                    "acceptance_scope": (
                        "current_observation_at_successful_confirm"
                    ),
                    "preview_observation_sha256": (
                        approved_observation_sha256
                    ),
                    "current_observation_sha256": (
                        captured_observation_sha256
                    ),
                    "repositories": repositories,
                },
            )
        if (
            selection_complete
            and state_value["status"] == "PREFLIGHTED"
            and _workspace_strategy(state_value) == "branch"
        ):
            for repo in state_value["repositories"]:
                binding = repo.get("branch_binding")
                if not isinstance(binding, dict):
                    raise FlowError(
                        "CHECKOUT_BINDING_MISSING",
                        (
                            "branch workspace task has no start-time "
                            "checkout binding"
                        ),
                        details={"repository_id": repo.get("id")},
                    )
                binding["initial_preflight_confirmed"] = True
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
            {
                "repository_ids": [repo["id"] for repo in selected],
                "blockers": blockers,
                "decision_sha256": post_decision_sha256,
                "preview_observation_sha256": (
                    approved_observation_sha256
                ),
                "captured_observation_sha256": (
                    captured_observation_sha256
                ),
                "evidence_refreshed_since_preview": (
                    evidence_refresh_observed
                ),
                "evidence_refresh_accepted": evidence_refresh_accepted,
                "accepted_observation_sha256": (
                    captured_observation_sha256
                    if evidence_refresh_accepted
                    else None
                ),
            },
        )
    return _result(
        "preflight",
        state_value,
        ready=selection_complete and all_checked and not blockers,
        selection_complete=selection_complete,
        transition_preview=transition_preview,
        evidence_refreshed_since_preview=(
            evidence_refresh_observed
        ),
        evidence_refresh_accepted=evidence_refresh_accepted,
        preview_observation_sha256=approved_observation_sha256,
        captured_observation_sha256=captured_observation_sha256,
        confirmed_preview={
            "token": args.confirm_preview,
            "decision_sha256": post_decision_sha256,
            "preview_observation_sha256": (
                approved_observation_sha256
            ),
            "captured_observation_sha256": (
                captured_observation_sha256
            ),
            "evidence_refresh_accepted": (
                evidence_refresh_accepted
            ),
        },
        repositories=repositories,
    )
