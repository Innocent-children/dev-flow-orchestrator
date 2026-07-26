# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Test recording, review snapshots, transitions, and cancellation.
from __future__ import annotations

def _test_identity(name: Any, command: Any) -> str:
    return _sha256_bytes(
        _json_bytes({"name": str(name or ""), "command": str(command or "")})
    )


def command_record_test(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    output_record: dict[str, Any] | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve(strict=True)
        output_record = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(output_path),
            "path_identity": _serializable_path_identity(output_path),
            "sha256": _sha256_file(output_path),
            "size": output_path.stat().st_size,
        }
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
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "test_id": str(uuid.uuid4()),
            "name": args.name,
            "command": args.test_command,
            "test_identity": _test_identity(args.name, args.test_command),
            "exit_code": args.exit_code,
            "passed": args.exit_code == 0,
            "recorded_at": utc_now(),
            "repository_ids": [repo["id"] for repo in selected],
            "fingerprints": fingerprints,
            "capability_profile_sha256": {
                repository_id: fingerprint[
                    "capability_profile_sha256"
                ]
                for repository_id, fingerprint in fingerprints.items()
            },
            **binding,
            "output": output_record,
        }
        state_value["tests"].append(test_record)
        _commit_state(current, state_value, task_dir, "test_recorded", {"test_id": test_record["test_id"], "passed": test_record["passed"], "repository_ids": test_record["repository_ids"]})
    return _result("record-test", state_value, test=test_record)


def _write_review_repo(
    snapshot_root: Path,
    repo: dict[str, Any],
    *,
    initial_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    working = _working_path(repo)
    _assert_evidence_supported(working)
    base_sha = (repo.get("baseline") or {}).get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")

    def capture_sections() -> tuple[
        str, dict[str, bytes], dict[str, list[str]]
    ]:
        captured_head = _git_evidence(working, "rev-parse", "HEAD")
        captured_sections = {
            "committed": _git_diff(
                working,
                "--binary",
                "--full-index",
                f"{base_sha}...HEAD",
                "--",
                text=False,
            ),
            "cached": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--cached",
                "--",
                text=False,
            ),
            "unstaged": _git_diff(
                working,
                "--binary",
                "--full-index",
                "--",
                text=False,
            ),
        }
        captured_files = {
            "committed": _split_lines(
                _git_diff(
                    working,
                    "--name-status",
                    f"{base_sha}...HEAD",
                    "--",
                )
            ),
            "cached": _split_lines(
                _git_diff(
                    working, "--cached", "--name-status", "--"
                )
            ),
            "unstaged": _split_lines(
                _git_diff(working, "--name-status", "--")
            ),
        }
        return captured_head, captured_sections, captured_files

    fingerprint = (
        initial_fingerprint
        if initial_fingerprint is not None
        else _fingerprint_repo(working)
    )
    repo_dir = snapshot_root / repo["id"]
    _ensure_private_dir(repo_dir)
    head_sha, sections, section_files = capture_sections()
    if head_sha != fingerprint.get("head_sha"):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository HEAD changed before review sections were captured",
            details={
                "repository_id": repo["id"],
                "fingerprint_head": fingerprint.get("head_sha"),
                "section_head": head_sha,
            },
        )
    section_records: dict[str, Any] = {}
    for name, content in sections.items():
        path = repo_dir / f"{name}.patch"
        _atomic_write_bytes(path, content)
        section_records[name] = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(path),
            "path_identity": _serializable_path_identity(path),
            "sha256": _sha256_bytes(content),
            "size": len(content),
            "files": section_files[name],
            "range": f"{base_sha}...{head_sha}" if name == "committed" else None,
        }
    untracked_manifest_path = repo_dir / "untracked.json"
    _atomic_write_json(untracked_manifest_path, fingerprint["untracked"])
    tar_path = repo_dir / "untracked.tar"
    with tarfile.open(tar_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for item in fingerprint["untracked"]:
            relative = _untracked_filesystem_path(item)
            archive.add(working / relative, arcname=relative, recursive=False)
    _set_private_permissions(tar_path, 0o600)
    # Windows requires a writable descriptor for fsync; no bytes are changed.
    with tar_path.open("rb+") as archive_handle:
        os.fsync(archive_handle.fileno())
    _validate_untracked_archive(tar_path, fingerprint["untracked"])
    middle_fingerprint = _fingerprint_repo(working)
    verify_head, verify_sections, verify_files = capture_sections()
    final_fingerprint = _fingerprint_repo(working)
    if (
        fingerprint.get("sha256") != middle_fingerprint.get("sha256")
        or fingerprint.get("sha256") != final_fingerprint.get("sha256")
        or verify_head != head_sha
        or verify_sections != sections
        or verify_files != section_files
    ):
        raise FlowError(
            "REVIEW_SNAPSHOT_CHANGED",
            "repository changed while the complete review snapshot was being built",
            details={
                "repository_id": repo["id"],
                "before_sha256": fingerprint.get("sha256"),
                "middle_sha256": middle_fingerprint.get("sha256"),
                "after_sha256": final_fingerprint.get("sha256"),
                "before_head": head_sha,
                "after_head": verify_head,
            },
        )
    section_records["untracked"] = {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "manifest_path": str(untracked_manifest_path),
        "manifest_path_identity": _serializable_path_identity(
            untracked_manifest_path
        ),
        "manifest_sha256": _sha256_file(untracked_manifest_path),
        "archive_path": str(tar_path),
        "archive_path_identity": _serializable_path_identity(tar_path),
        "archive_sha256": _sha256_file(tar_path),
        "size": tar_path.stat().st_size,
        "files": fingerprint["untracked"],
    }
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "repository_id": repo["id"],
        "working_path": str(working),
        "working_path_identity": _serializable_path_identity(working),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "capability_profile_sha256": fingerprint[
            "capability_profile_sha256"
        ],
        "tracked_worktree_manifest_sha256": fingerprint[
            "tracked_worktree_manifest_sha256"
        ],
        "fingerprint": fingerprint,
        "sections": section_records,
    }


def _latest_passing_test_is_current(
    state_value: dict[str, Any],
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
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
        current = (
            fingerprints[repo["id"]]
            if fingerprints is not None and repo["id"] in fingerprints
            else _fingerprint_repo(_working_path(repo))
        )
        for latest in latest_by_identity.values():
            label = latest.get("name") or latest.get("test_identity") or "unnamed"
            try:
                _require_current_evidence(latest, f"test:{label}")
            except FlowError as exc:
                return False, exc.message
            if not latest.get("passed"):
                return (
                    False,
                    f"latest result for test identity {label!r} failed for repository: {repo['id']}",
                )
            output = latest.get("output")
            if output is not None:
                try:
                    _require_current_evidence(
                        output, f"test-output:{label}"
                    )
                except FlowError as exc:
                    return False, exc.message
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
                    or not _recorded_path_matches(
                        (output or {}).get("path_identity"),
                        (output or {}).get("path"),
                        output_path,
                    )
                ):
                    return (
                        False,
                        f"test output for identity {label!r} is missing or changed: {output_path}",
                    )
            recorded = latest.get("fingerprints", {}).get(repo["id"], {})
            try:
                _require_current_evidence(
                    recorded, f"test-fingerprint:{label}:{repo['id']}"
                )
            except FlowError as exc:
                return False, exc.message
            if current.get("sha256") != recorded.get("sha256"):
                return (
                    False,
                    f"repository changed after test identity {label!r} passed: {repo['id']}",
                )
            recorded_profiles = latest.get(
                "capability_profile_sha256", {}
            )
            if (
                current.get("capability_profile_sha256")
                != recorded_profiles.get(repo["id"])
            ):
                return (
                    False,
                    f"repository capability profile changed after test identity {label!r}: {repo['id']}",
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
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        if len(selected) != len(state_value["repositories"]):
            raise FlowError("INCOMPLETE_REVIEW", "review-snapshot must include every configured repository")
        initial_fingerprints = {
            repo["id"]: _fingerprint_repo(_working_path(repo))
            for repo in selected
        }
        passing, reason = _latest_passing_test_is_current(
            current,
            fingerprints=initial_fingerprints,
        )
        if not passing:
            raise FlowError("CURRENT_TEST_REQUIRED", reason or "a current passing test is required")
        snapshot_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        snapshot_root = task_dir / "reviews" / snapshot_id
        try:
            repositories = [
                _write_review_repo(
                    snapshot_root,
                    repo,
                    initial_fingerprint=initial_fingerprints[repo["id"]],
                )
                for repo in selected
            ]
            for repository in repositories:
                current_fingerprint = _fingerprint_repo(
                    Path(repository["working_path"])
                )
                recorded_fingerprint = repository.get(
                    "fingerprint"
                ) or {}
                if current_fingerprint.get(
                    "sha256"
                ) != recorded_fingerprint.get("sha256"):
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CHANGED",
                        (
                            "a repository changed after its section of the "
                            "multi-repository snapshot was captured"
                        ),
                        details={
                            "repository_id": repository[
                                "repository_id"
                            ],
                            "recorded_sha256": recorded_fingerprint.get(
                                "sha256"
                            ),
                            "current_sha256": current_fingerprint.get(
                                "sha256"
                            ),
                        },
                    )
            snapshot = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": utc_now(),
                "repository_ids": [repo["id"] for repo in selected],
                "repositories": repositories,
            }
            manifest_path = snapshot_root / "manifest.json"
            _atomic_write_json(manifest_path, snapshot)
            snapshot["manifest_path"] = str(manifest_path)
            snapshot["manifest_path_identity"] = (
                _serializable_path_identity(manifest_path)
            )
            snapshot["sha256"] = _sha256_file(manifest_path)
            integrity_error = _review_snapshot_integrity_error(
                snapshot
            )
            if integrity_error:
                raise FlowError(
                    "REVIEW_SNAPSHOT_INVALID",
                    integrity_error,
                    details={"snapshot_id": snapshot_id},
                )
        except BaseException as exc:
            if snapshot_root.exists():
                try:
                    shutil.rmtree(snapshot_root)
                except OSError as cleanup_error:
                    raise FlowError(
                        "REVIEW_SNAPSHOT_CLEANUP_FAILED",
                        (
                            "an incomplete review snapshot could not be "
                            "removed and was not recorded as usable"
                        ),
                        details={
                            "snapshot_root": str(snapshot_root),
                            "error": str(cleanup_error),
                            "cause": f"{type(exc).__name__}: {exc}",
                        },
                    ) from cleanup_error
            raise
        state_value["review_snapshots"].append(snapshot)
        state_value["artifacts"].append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "artifact_id": str(uuid.uuid4()),
                "kind": "review-snapshot",
                "path": str(manifest_path),
                "path_identity": _serializable_path_identity(manifest_path),
                "sha256": snapshot["sha256"],
                "size": manifest_path.stat().st_size,
                "recorded_at": utc_now(),
                "metadata": {
                    "snapshot_id": snapshot_id,
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "capability_profile_sha256": {
                        item["repository_id"]: item[
                            "capability_profile_sha256"
                        ]
                        for item in repositories
                    },
                },
            }
        )
        state_value["status"] = "REVIEWING"
        _commit_state(current, state_value, task_dir, "review_snapshot_recorded", {"snapshot_id": snapshot_id, "sha256": snapshot["sha256"], "repository_ids": snapshot["repository_ids"]})
    return _result("review-snapshot", state_value, snapshot=snapshot)


def _snapshot_file_error(
    path_value: Any,
    expected_sha: Any,
    label: str,
    path_identity: Any = None,
) -> str | None:
    if not isinstance(path_value, str) or not path_value or not isinstance(expected_sha, str):
        return f"review snapshot has incomplete {label} integrity metadata"
    path = Path(path_value)
    if not _recorded_path_matches(path_identity, path_value, path):
        return f"review snapshot {label} path identity changed: {path}"
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
    try:
        _require_current_evidence(snapshot, "review snapshot")
    except FlowError as exc:
        return exc.message
    error = _snapshot_file_error(
        snapshot.get("manifest_path"),
        snapshot.get("sha256"),
        "manifest",
        snapshot.get("manifest_path_identity"),
    )
    if error:
        return error
    for repository in snapshot.get("repositories", []):
        repository_id = repository.get("repository_id", "unknown")
        try:
            _require_current_evidence(
                repository, f"review-repository:{repository_id}"
            )
            _require_current_evidence(
                repository.get("fingerprint"),
                f"review-fingerprint:{repository_id}",
            )
        except FlowError as exc:
            return exc.message
        sections = repository.get("sections") or {}
        for section_name in ("committed", "cached", "unstaged"):
            section = sections.get(section_name) or {}
            error = _snapshot_file_error(
                section.get("path"),
                section.get("sha256"),
                f"{repository_id}/{section_name}",
                section.get("path_identity"),
            )
            if error:
                return error
        untracked = sections.get("untracked") or {}
        error = _snapshot_file_error(
            untracked.get("manifest_path"),
            untracked.get("manifest_sha256"),
            f"{repository_id}/untracked-manifest",
            untracked.get("manifest_path_identity"),
        )
        if error:
            return error
        error = _snapshot_file_error(
            untracked.get("archive_path"),
            untracked.get("archive_sha256"),
            f"{repository_id}/untracked-archive",
            untracked.get("archive_path_identity"),
        )
        if error:
            return error
    return None


def _review_is_current(
    state_value: dict[str, Any],
    *,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, str | None]:
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
        current = (
            fingerprints[repo["id"]]
            if fingerprints is not None and repo["id"] in fingerprints
            else _fingerprint_repo(_working_path(repo))
        )
        if current.get("sha256") != (recorded.get("fingerprint") or {}).get("sha256"):
            return False, f"repository changed after review snapshot: {repo['id']}"
        if current.get("capability_profile_sha256") != recorded.get(
            "capability_profile_sha256"
        ):
            return False, f"repository capability profile changed after review snapshot: {repo['id']}"
    return True, None


def _current_repository_fingerprints(
    state_value: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Observe each working repository once for equivalent currentness checks."""

    return {
        repo["id"]: _fingerprint_repo(_working_path(repo))
        for repo in state_value.get("repositories", [])
    }


def _lite_transition_guard(state_value: dict[str, Any], target: str) -> None:
    repositories = state_value.get("repositories", [])
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
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
    if target == "PREFLIGHTED":
        if not all(
            (repo.get("preflight") or {}).get("ready")
            for repo in repositories
        ):
            raise FlowError(
                "PREFLIGHT_REQUIRED", "all repositories must pass preflight"
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("preflight"), f"preflight:{repo.get('id')}"
            )
    if target == "BASELINED":
        if not all(repo.get("baseline") for repo in repositories):
            raise FlowError(
                "BASELINE_REQUIRED",
                "all repositories must have a pinned baseline",
            )
        for repo in repositories:
            _require_current_evidence(
                repo.get("baseline"), f"baseline:{repo.get('id')}"
            )
    if target in {"INDEXED", "IMPACT_REVIEW"}:
        if not all(repo.get("index") for repo in repositories):
            raise FlowError(
                "INDEX_REQUIRED",
                "all repositories must have a recorded index",
            )
        _index_provenance_evidence(state_value)
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
        current_fingerprints = _current_repository_fingerprints(state_value)
        review_current, review_reason = _review_is_current(
            state_value,
            fingerprints=current_fingerprints,
        )
        if not review_current:
            raise FlowError("CURRENT_REVIEW_REQUIRED", review_reason or "a current review snapshot is required")
        test_current, test_reason = _latest_passing_test_is_current(
            state_value,
            fingerprints=current_fingerprints,
        )
        if not test_current:
            raise FlowError("CURRENT_TEST_REQUIRED", test_reason or "a current passing test is required")
        _require_review_gate(state_value)


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
        if (
            target == "PREFLIGHTED"
            and (
                source == "INTAKE"
                or (
                    source == "BLOCKED"
                    and (current.get("blocked") or {}).get("phase")
                    == "preflight"
                )
            )
        ):
            raise FlowError(
                "PREFLIGHT_CONFIRMATION_REQUIRED",
                (
                    "initial and preflight-blocked transitions to "
                    "PREFLIGHTED require an all-repository "
                    "preflight --preview/--confirm-preview pair"
                ),
                details={"from": source, "to": target},
            )
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


