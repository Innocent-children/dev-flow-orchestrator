# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Mutation quarantine, intent persistence, process liveness, and locks.
from __future__ import annotations

def _quarantine_path(directory: Path) -> Path:
    return directory / "mutation-quarantine.json"


def _read_quarantine(directory: Path) -> dict[str, Any] | None:
    path = _quarantine_path(directory)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "mutation quarantine evidence is unreadable",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(value, dict) or value.get("ready") is not False:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "mutation quarantine evidence is invalid",
            details={"path": str(path)},
        )
    safe_value = _redact_sensitive_value(value)
    if not isinstance(safe_value, dict):  # Defensive: validated above.
        raise TypeError("quarantine redaction produced a non-object value")
    if safe_value != value:
        _atomic_write_json(path, safe_value)
    return safe_value


def _assert_no_mutation_quarantine(directory: Path) -> None:
    quarantine = _read_quarantine(directory)
    if quarantine is not None:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "a prior mutating child was not proven quiescent",
            details={
                "path": str(_quarantine_path(directory)),
                "pid": quarantine.get("pid"),
                "command": quarantine.get("command"),
                "recovery": (
                    "prove the recorded child is gone and validate partial "
                    "Git/filesystem postconditions before recovery"
                ),
            },
        )


def _held_task_directory() -> Path | None:
    held = [Path(value) for value in _HELD_LOCK_DIRECTORIES.get()]
    return next(
        (
            candidate
            for candidate in held
            if (candidate / "state.json").is_file()
        ),
        None,
    )


def _begin_mutation_intent(command: Sequence[str]) -> Path | None:
    """Durably announce a mutating child before it is allowed to start."""

    directory = _held_task_directory()
    if directory is None:
        return None
    path = _quarantine_path(directory)
    active = set(_ACTIVE_MUTATION_INTENTS.get())
    if str(path) in active:
        evidence = _read_quarantine(directory)
        if evidence is None:
            raise FlowError(
                "MUTATION_INTENT_LOST",
                "active mutation intent disappeared before state commit",
                details={"path": str(path)},
            )
        operations = list(evidence.get("operations") or [])
        operations.append(
            {
                "command": _redacted_command(command),
                "announced_at": utc_now(),
                "phase": "spawn_pending",
                "gate_protocol_version": 1,
                "target_release_authorized": False,
                "containment_kind": (
                    "windows_job_kill_on_close"
                    if os.name == "nt"
                    else "posix_process_group"
                ),
                "containment_established": False,
            }
        )
        evidence["operations"] = operations
        evidence["command"] = _redacted_command(command)
        evidence["phase"] = "spawn_pending"
        evidence["pid"] = None
        evidence["process_group"] = None
        evidence["gate_protocol_version"] = 1
        evidence["target_release_authorized"] = False
        evidence["containment_kind"] = (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        )
        evidence["containment_established"] = False
        _atomic_write_sensitive_json(path, evidence)
        return path
    if path.exists():
        raise FlowError(
            "MUTATION_QUARANTINED",
            "a prior mutation intent remains active",
            details={"path": str(path)},
        )
    state_revision: int | None = None
    try:
        state_value = json.loads(
            (directory / "state.json").read_text(encoding="utf-8")
        )
        if isinstance(state_value, dict):
            state_revision = int(state_value.get("revision", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    announced_at = utc_now()
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": False,
        "recovery_id": str(uuid.uuid4()),
        "created_at": announced_at,
        "updated_at": announced_at,
        "phase": "spawn_pending",
        "pid": None,
        "process_group": None,
        "gate_protocol_version": 1,
        "target_release_authorized": False,
        "containment_kind": (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        ),
        "containment_established": False,
        "command": _redacted_command(command),
        "operations": [
            {
                "command": _redacted_command(command),
                "announced_at": announced_at,
                "phase": "spawn_pending",
                "gate_protocol_version": 1,
                "target_release_authorized": False,
                "containment_kind": (
                    "windows_job_kill_on_close"
                    if os.name == "nt"
                    else "posix_process_group"
                ),
                "containment_established": False,
            }
        ],
        "platform": _platform_family(),
        "state_revision": state_revision,
        "expected_committed_revision": (
            state_revision + 1
            if isinstance(state_revision, int)
            else None
        ),
        "cause": None,
        "required_recovery": [
            "prove_child_quiescent",
            "validate_partial_git_and_filesystem_postconditions",
        ],
    }
    # This write is deliberately before Popen.  If it cannot be committed,
    # the target process is never started.
    _atomic_write_sensitive_json(path, evidence)
    _ACTIVE_MUTATION_INTENTS.set(
        (*_ACTIVE_MUTATION_INTENTS.get(), str(path))
    )
    return path


def _update_mutation_intent(
    path: Path | None,
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    phase: str,
    cause: BaseException | None = None,
    target_release_authorized: bool | None = None,
) -> None:
    if path is None:
        return
    directory = path.parent
    evidence = _read_quarantine(directory)
    if evidence is None:
        raise FlowError(
            "MUTATION_INTENT_LOST",
            "mutation intent disappeared while its child was active",
            details={"path": str(path), "pid": process.pid},
        )
    evidence.update(
        {
            "updated_at": utc_now(),
            "phase": phase,
            "pid": process.pid,
            "process_group": (
                process.pid if os.name != "nt" else None
            ),
            "command": _redacted_command(command),
            "cause": (
                f"{type(cause).__name__}: {cause}"
                if cause is not None
                else None
            ),
        }
    )
    if target_release_authorized is not None:
        evidence["target_release_authorized"] = (
            target_release_authorized
        )
    if phase == "child_owned":
        evidence["containment_established"] = True
    operations = list(evidence.get("operations") or [])
    if operations:
        operations[-1] = {
            **operations[-1],
            "phase": phase,
            "pid": process.pid,
            "updated_at": evidence["updated_at"],
        }
        if target_release_authorized is not None:
            operations[-1]["target_release_authorized"] = (
                target_release_authorized
            )
        if phase == "child_owned":
            operations[-1]["containment_established"] = True
    evidence["operations"] = operations
    _atomic_write_sensitive_json(path, evidence)


def _forget_active_mutation_intents(directory: Path) -> None:
    prefix = str(_quarantine_path(directory))
    _ACTIVE_MUTATION_INTENTS.set(
        tuple(
            item
            for item in _ACTIVE_MUTATION_INTENTS.get()
            if item != prefix
        )
    )


def _complete_mutation_intent(
    task_dir: Path, committed_revision: int
) -> None:
    path = _quarantine_path(task_dir)
    if str(path) not in set(_ACTIVE_MUTATION_INTENTS.get()):
        return
    evidence = _read_quarantine(task_dir)
    if evidence is None:
        raise FlowError(
            "MUTATION_INTENT_LOST",
            "mutation committed but its durable intent disappeared",
            details={
                "path": str(path),
                "committed_revision": committed_revision,
            },
        )
    evidence.update(
        {
            "updated_at": utc_now(),
            "phase": "postconditions_committed",
            "committed_revision": committed_revision,
            "pid": None,
            "process_group": None,
        }
    )
    _atomic_write_sensitive_json(path, evidence)
    try:
        path.unlink()
        if os.name != "nt":
            directory_fd = os.open(task_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        if not path.exists():
            try:
                evidence["phase"] = "clear_durability_uncertain"
                _atomic_write_sensitive_json(path, evidence)
            except FlowError:
                pass
        raise FlowError(
            "MUTATION_COMMITTED_QUARANTINE",
            (
                "state committed but mutation-intent cleanup could not be "
                "proven durable; reload and recover before continuing"
            ),
            details={
                "path": str(path),
                "committed_revision": committed_revision,
                "error": str(exc),
            },
        ) from exc
    finally:
        _forget_active_mutation_intents(task_dir)


def _abandon_unstarted_mutation_intent(path: Path | None) -> None:
    """Withdraw only the newest intent when its real target never started.

    A single controller transition can perform several mutating Git commands
    before committing state (for example, one fetch or worktree creation per
    repository).  If a later target cannot start, earlier operations still
    require durable recovery evidence; removing the whole marker would lose
    that fact.
    """

    if path is None:
        return
    forget_active = False
    try:
        evidence = _read_quarantine(path.parent)
        if evidence is None:
            forget_active = True
            return
        operations = list(evidence.get("operations") or [])
        if len(operations) > 1:
            operations.pop()
            previous = operations[-1]
            evidence.update(
                {
                    "updated_at": utc_now(),
                    "operations": operations,
                    "command": list(previous.get("command") or []),
                    "phase": previous.get("phase") or "child_quiescent",
                    "pid": previous.get("pid"),
                    "process_group": (
                        previous.get("pid")
                        if os.name != "nt"
                        else None
                    ),
                    "gate_protocol_version": previous.get(
                        "gate_protocol_version"
                    ),
                    "target_release_authorized": bool(
                        previous.get("target_release_authorized")
                    ),
                    "containment_kind": previous.get(
                        "containment_kind"
                    ),
                    "containment_established": bool(
                        previous.get("containment_established")
                    ),
                    "cause": None,
                }
            )
            _atomic_write_sensitive_json(path, evidence)
            return
        path.unlink()
        forget_active = True
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except FileNotFoundError:
        forget_active = True
    except OSError as exc:
        raise FlowError(
            "MUTATION_QUARANTINED",
            "an unstarted mutation intent could not be cleared durably",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    finally:
        if forget_active:
            _forget_active_mutation_intents(path.parent)


def _persist_mutation_quarantine(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    error: BaseException,
) -> Path | None:
    directory = _held_task_directory()
    if directory is None:
        return None
    path = _quarantine_path(directory)
    try:
        if path.exists():
            _update_mutation_intent(
                path,
                process,
                command,
                phase="quiescence_unproven",
                cause=error,
            )
            return path
    except FlowError:
        # The pre-spawn marker is already durable.  Preserve it rather than
        # letting an update failure erase the only fail-closed evidence.
        if path.exists():
            return path
    state_revision: int | None = None
    state_path = directory / "state.json"
    try:
        state_value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(state_value, dict):
            state_revision = int(state_value.get("revision", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    evidence = {
        "schema_version": 1,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "ready": False,
        "created_at": utc_now(),
        "pid": process.pid,
        "process_group": (
            process.pid if os.name != "nt" else None
        ),
        "containment_kind": (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        ),
        "containment_established": os.name != "nt",
        "command": _redacted_command(command),
        "platform": _platform_family(),
        "state_revision": state_revision,
        "cause": f"{type(error).__name__}: {error}",
        "required_recovery": [
            "prove_child_quiescent",
            "validate_partial_git_and_filesystem_postconditions",
        ],
    }
    _atomic_write_sensitive_json(path, evidence)
    return path


def _quarantined_process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise FlowError(
            "QUARANTINE_INVALID",
            "mutation quarantine does not contain a valid child process id",
            details={"pid": pid},
        )
    if os.name == "nt":  # pragma: no cover - exercised on native Windows
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x00100000, False, pid)
        if not process:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process is gone.
                return False
            if error == 5:  # Access denied proves a process still owns the id.
                return True
            raise FlowError(
                "QUARANTINE_PROCESS_UNVERIFIABLE",
                "could not determine whether the quarantined child still exists",
                details={"pid": pid, "winerror": error},
            )
        try:
            wait_result = int(kernel32.WaitForSingleObject(process, 0))
            if wait_result == 258:  # WAIT_TIMEOUT
                return True
            if wait_result == 0:  # WAIT_OBJECT_0
                return False
            raise FlowError(
                "QUARANTINE_PROCESS_UNVERIFIABLE",
                "could not wait on the quarantined child process",
                details={
                    "pid": pid,
                    "wait_result": wait_result,
                    "winerror": ctypes.get_last_error(),
                },
            )
        finally:
            kernel32.CloseHandle(process)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise FlowError(
            "QUARANTINE_PROCESS_UNVERIFIABLE",
            "could not determine whether the quarantined child still exists",
            details={"pid": pid, "error": str(exc)},
        ) from exc
    return True


def _quarantine_processes_alive(quarantine: dict[str, Any]) -> bool:
    if (
        quarantine.get("gate_protocol_version") == 1
        and quarantine.get("phase") == "spawn_pending"
        and quarantine.get("pid") is None
        and quarantine.get("target_release_authorized") is False
        and quarantine.get("containment_established") is False
    ):
        # The only process that could have existed was the no-side-effect gate.
        # The controller lock can be reacquired only after its parent has
        # exited, which closes the gate pipe; without a durable release
        # authorization the real target could never have started.
        return False
    if quarantine.get("gate_protocol_version") == 1:
        expected_containment = (
            "windows_job_kill_on_close"
            if os.name == "nt"
            else "posix_process_group"
        )
        if (
            quarantine.get("containment_kind")
            != expected_containment
            or quarantine.get("containment_established") is not True
        ):
            raise FlowError(
                "QUARANTINE_INVALID",
                "mutation quarantine lacks valid child-containment evidence",
                details={
                    "containment_kind": quarantine.get(
                        "containment_kind"
                    ),
                    "containment_established": quarantine.get(
                        "containment_established"
                    ),
                },
            )
    if (
        quarantine.get("pid") is None
        and quarantine.get("phase")
        in {"postconditions_committed", "clear_durability_uncertain"}
    ):
        return False
    process_group = quarantine.get("process_group")
    if os.name != "nt" and isinstance(process_group, int):
        return _posix_process_group_alive(process_group)
    return _quarantined_process_alive(quarantine.get("pid"))


def _validate_partial_workspace_plan(
    state_value: dict[str, Any], task_dir: Path
) -> list[dict[str, Any]]:
    controller_plan = (state_value.get("workspace") or {}).get("plan") or {}
    plan_path_value = controller_plan.get("path")
    if not plan_path_value:
        return []
    plan_path = Path(str(plan_path_value))
    try:
        evidence = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "QUARANTINE_POSTCONDITION_FAILED",
            "workspace plan cannot be read during quarantine recovery",
            details={"path": str(plan_path), "error": str(exc)},
        ) from exc
    _require_current_evidence(evidence, "workspace plan")
    if _sha256_file(plan_path) != controller_plan.get("sha256"):
        raise FlowError(
            "QUARANTINE_POSTCONDITION_FAILED",
            "workspace plan changed while a mutation was quarantined",
            details={"path": str(plan_path)},
        )
    by_id = {
        repo.get("id"): repo for repo in state_value.get("repositories", [])
    }
    checked: list[dict[str, Any]] = []
    data_root = task_dir.parent.parent
    for plan in evidence.get("repositories", []):
        repo = by_id.get(plan.get("repository_id"))
        if not repo:
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "workspace plan names an unknown repository",
                details={"repository_id": plan.get("repository_id")},
            )
        destination = Path(str(plan.get("path", ""))).resolve(strict=False)
        workspace = repo.get("workspace") or {}
        if workspace.get("ready") and _recorded_path_matches(
            workspace.get("path_identity"),
            workspace.get("path"),
            destination,
        ):
            checked.append(
                {
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "state": "recorded-ready",
                }
            )
            continue
        if not destination.exists():
            checked.append(
                {
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "state": "absent",
                }
            )
            continue
        source = Path(repo["path"]).resolve(strict=True)
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        branch = _git_optional(
            destination, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        head = _git_optional(destination, "rev-parse", "HEAD")
        status_available, status_porcelain = _status_porcelain(destination)
        entry = next(
            (
                item
                for item in _worktree_entries(source)
                if item.get("worktree")
                and _same_path(Path(item["worktree"]), destination)
            ),
            None,
        )
        if (
            not root
            or not _same_path(Path(root), destination)
            or not _same_path(
                _git_common_dir(destination), _git_common_dir(source)
            )
            or not _is_linked_worktree(destination)
            or branch != plan.get("branch")
            or head != plan.get("base_sha")
            or not status_available
            or bool(status_porcelain)
            or not entry
            or entry.get("branch") != plan.get("branch_ref")
            or entry.get("HEAD") != head
            or not _has_exact_workspace_claim(
                data_root,
                state_value,
                repo,
                destination,
                str(plan.get("branch")),
            )
        ):
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "partial workspace mutation does not satisfy the approved clean postconditions",
                details={
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "branch": branch,
                    "head": head,
                    "dirty": bool(status_porcelain),
                },
            )
        checked.append(
            {
                "repository_id": repo["id"],
                "path": str(destination),
                "state": "complete-unrecorded",
            }
        )
    return checked


def _validate_quarantine_postconditions(
    state_value: dict[str, Any],
    task_dir: Path,
    quarantine: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    partial_analysis: list[dict[str, Any]] = []
    mutation_commands = [
        item.get("command")
        for item in (quarantine or {}).get("operations", [])
        if isinstance(item, dict)
        and isinstance(item.get("command"), list)
    ]
    if isinstance((quarantine or {}).get("command"), list):
        mutation_commands.append((quarantine or {})["command"])
    data_root = task_dir.parent.parent
    for repo in state_value.get("repositories", []):
        source = Path(repo["path"]).resolve(strict=True)
        canonical = _canonical_repo(str(source))
        if not _same_path(source, canonical):
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "repository root identity changed during the quarantined mutation",
                details={"repository_id": repo.get("id")},
            )
        operations = _operation_state(source)
        active = [name for name, value in operations.items() if value]
        if active:
            raise FlowError(
                "QUARANTINE_POSTCONDITION_FAILED",
                "repository still has an incomplete Git operation",
                details={
                    "repository_id": repo.get("id"),
                    "operations": active,
                },
            )
        baseline = repo.get("baseline")
        if isinstance(baseline, dict):
            _require_current_evidence(
                baseline, f"baseline:{repo.get('id')}"
            )
            source_profile = _git_capability_profile(source)
            if source_profile["sha256"] != baseline.get(
                "capability_profile_sha256"
            ):
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    "repository capability profile changed during the quarantined mutation",
                    details={"repository_id": repo.get("id")},
                )
        analysis = repo.get("analysis_workspace")
        if isinstance(analysis, dict) and analysis.get("ready"):
            error = _analysis_workspace_integrity_error(repo)
            if error:
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    error,
                    details={"repository_id": repo.get("id")},
                )
        else:
            candidate = (
                data_root
                / "analysis"
                / str(state_value.get("task_id"))
                / str(repo.get("id"))
            ).resolve(strict=False)
            if candidate.exists():
                matching_command = next(
                    (
                        command
                        for command in mutation_commands
                        if "worktree" in command
                        and "add" in command
                        and str(candidate) in command
                    ),
                    None,
                )
                expected_head = (
                    str(matching_command[-1])
                    if matching_command
                    else None
                )
                root = _git_optional(
                    candidate, "rev-parse", "--show-toplevel"
                )
                head = _git_optional(
                    candidate, "rev-parse", "HEAD"
                )
                branch = _git_optional(
                    candidate,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                )
                status_available, status_porcelain = (
                    _status_porcelain(candidate)
                )
                entry = next(
                    (
                        item
                        for item in _worktree_entries(source)
                        if item.get("worktree")
                        and _same_path(
                            Path(item["worktree"]), candidate
                        )
                    ),
                    None,
                )
                permissions_safe = True
                try:
                    if os.name == "nt":
                        _verify_windows_private_path(candidate)
                    else:
                        permissions_safe = (
                            stat.S_IMODE(candidate.stat().st_mode)
                            == 0o700
                        )
                except FlowError:
                    permissions_safe = False
                if (
                    expected_head is None
                    or not root
                    or not _same_path(Path(root), candidate)
                    or not _same_path(
                        _git_common_dir(candidate),
                        _git_common_dir(source),
                    )
                    or not _is_linked_worktree(candidate)
                    or head != expected_head
                    or branch is not None
                    or not status_available
                    or bool(status_porcelain)
                    or not entry
                    or entry.get("HEAD") != head
                    or "detached" not in entry
                    or not permissions_safe
                ):
                    raise FlowError(
                        "QUARANTINE_POSTCONDITION_FAILED",
                        (
                            "unrecorded analysis worktree does not match "
                            "the quarantined approved mutation"
                        ),
                        details={
                            "repository_id": repo.get("id"),
                            "path": str(candidate),
                            "expected_head": expected_head,
                            "actual_head": head,
                            "branch": branch,
                            "dirty": bool(status_porcelain),
                            "permissions_safe": permissions_safe,
                        },
                    )
                partial_analysis.append(
                    {
                        "repository_id": repo.get("id"),
                        "path": str(candidate),
                        "head_sha": head,
                        "state": "complete-unrecorded",
                    }
                )
        workspace = repo.get("workspace")
        if isinstance(workspace, dict) and workspace.get("ready"):
            error = _workspace_integrity_error(state_value, repo)
            if error:
                raise FlowError(
                    "QUARANTINE_POSTCONDITION_FAILED",
                    error,
                    details={"repository_id": repo.get("id")},
                )
        repositories.append(
            {
                "repository_id": repo.get("id"),
                "source_path": str(source),
                "operations": operations,
            }
        )
    partial_workspaces = _validate_partial_workspace_plan(
        state_value, task_dir
    )
    return {
        "repositories": repositories,
        "partial_analysis_worktrees": partial_analysis,
        "partial_workspaces": partial_workspaces,
    }


def _acquire_exclusive(handle: Any, lock_path: Path) -> None:
    """Take an exclusive advisory lock on an open lock file.

    POSIX uses ``fcntl.lockf``; Windows uses ``msvcrt.locking`` over byte zero.
    Both release automatically when the process exits. Every unsupported or
    failed backend is a structured fail-closed error.
    """

    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            if fcntl is not None:
                fcntl.lockf(
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                    1,
                    0,
                    os.SEEK_SET,
                )
            elif msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                raise FlowError(
                    "LOCK_UNSUPPORTED",
                    "no verified operating-system lock backend is available",
                    details={
                        "path": str(lock_path),
                        "platform": _platform_family(),
                    },
                )
            return
        except FlowError:
            raise
        except (OSError, ValueError) as exc:
            busy = isinstance(exc, OSError) and exc.errno in {
                errno.EACCES,
                errno.EAGAIN,
                errno.EDEADLK,
            }
            if busy and time.monotonic() < deadline:
                time.sleep(LOCK_POLL_SECONDS)
                continue
            if busy:
                raise FlowError(
                    "LOCK_TIMEOUT",
                    "timed out waiting for the exclusive controller lock",
                    details={
                        "path": str(lock_path),
                        "platform": _platform_family(),
                        "timeout_seconds": LOCK_TIMEOUT_SECONDS,
                    },
                ) from exc
            raise FlowError(
                "LOCK_ACQUIRE_FAILED",
                "could not acquire the exclusive controller lock",
                details={
                    "path": str(lock_path),
                    "platform": _platform_family(),
                    "error": str(exc),
                },
            ) from exc


def _release_exclusive(handle: Any, lock_path: Path) -> None:
    try:
        if fcntl is not None:
            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_UN,
                1,
                0,
                os.SEEK_SET,
            )
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            raise FlowError(
                "LOCK_UNSUPPORTED",
                "no verified operating-system lock backend is available",
                details={"path": str(lock_path), "platform": _platform_family()},
            )
    except FlowError:
        raise
    except (OSError, ValueError) as exc:
        raise FlowError(
            "LOCK_RELEASE_FAILED",
            (
                "exclusive controller lock release could not be verified; "
                "reload durable state before any retry"
            ),
            details={
                "path": str(lock_path),
                "platform": _platform_family(),
                "error": str(exc),
            },
        ) from exc


@contextlib.contextmanager
def _file_lock(
    directory: Path, name: str, *, allow_quarantine: bool = False
) -> Iterator[None]:
    _ensure_private_dir(directory)
    lock_path = directory / name
    with lock_path.open("a+b") as handle:
        _set_private_permissions(lock_path, 0o600)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        _acquire_exclusive(handle, lock_path)
        token: contextvars.Token[tuple[str, ...]] | None = None
        try:
            if not allow_quarantine:
                _assert_no_mutation_quarantine(directory)
            token = _HELD_LOCK_DIRECTORIES.set(
                (
                    *_HELD_LOCK_DIRECTORIES.get(),
                    str(directory.resolve(strict=False)),
                )
            )
            yield
        finally:
            if token is not None:
                _HELD_LOCK_DIRECTORIES.reset(token)
            try:
                _release_exclusive(handle, lock_path)
            finally:
                _forget_active_mutation_intents(directory)


@contextlib.contextmanager
def _task_lock(
    task_dir: Path, *, allow_quarantine: bool = False
) -> Iterator[None]:
    with _file_lock(
        task_dir, "state.lock", allow_quarantine=allow_quarantine
    ):
        yield


@contextlib.contextmanager
def _task_namespace_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "task-namespace.lock"):
        yield


@contextlib.contextmanager
def _workspace_registry_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "workspace-registry.lock"):
        yield


@contextlib.contextmanager
def _config_lock(data_root: Path) -> Iterator[None]:
    with _file_lock(data_root, "config.lock"):
        yield


