# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: State transactions, subprocess containment, mutation gates, and command execution.
from __future__ import annotations

def _actor() -> str:
    return (
        _nonempty(os.environ.get("DEV_FLOW_ACTOR"))
        or _nonempty(os.environ.get("USER"))
        or _nonempty(os.environ.get("USERNAME"))
        or "unknown"
    )


def _commit_state(
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any],
    task_dir: Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    additional_events: Sequence[tuple[str, dict[str, Any]]] | None = None,
    _manager_registry_operation: object = None,
    _engine_commit_evaluation: object = None,
    _engine_commit_proof: object = None,
    _verified_receipt: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    linked = list(additional_events or ())
    is_v4 = (
        old_state is not None
        and old_state.get("schema_version") == V4_TASK_SCHEMA_VERSION
    )
    if not is_v4:
        if (
            _engine_commit_evaluation is not None
            or _engine_commit_proof is not None
            or _verified_receipt is not None
        ):
            raise FlowError(
                "V4_ENGINE_COMMIT_SCHEMA_REQUIRED",
                "engine commit authority applies only to schema-v4 tasks",
            )
        return _persist_state_transaction(
            old_state,
            new_state,
            task_dir,
            event_type,
            payload,
            additional_events=linked,
        )
    if _engine_commit_proof is not None:
        raise FlowError(
            "V4_ENGINE_COMMIT_AUTHORITY_CONFLICT",
            (
                "pre-minted proofs must enter the raw transaction boundary; "
                "commit_state accepts an engine evaluation"
            ),
        )
    if _engine_commit_evaluation is None:
        raise FlowError(
            "V4_ENGINE_COMMIT_PROOF_REQUIRED",
            "schema-v4 state changes require a live kernel evaluation",
        )
    try:
        resolve_loaded_task_workflow(old_state, purpose="mutation")
    except (WorkflowCatalogError, WorkflowStateError) as exc:
        raise FlowError(
            getattr(exc, "code", "WORKFLOW_MOVEMENT_REJECTED"),
            str(
                getattr(
                    exc,
                    "message",
                    "pinned workflow resolution failed",
                )
            ),
            details=getattr(exc, "details", {}),
        ) from exc
    manager_evaluation_state: dict[str, object] | None = None
    manager_authorization_binding: dict[str, object] | None = None
    if _manager_registry_operation is not None:
        manager_process_commit_gate_v1(
            old_state,
            new_state,
            event_type,
            _manager_registry_operation,
        )
    else:
        manager_event = manager_process_commit_gate_v1(
            old_state,
            new_state,
            event_type,
        )
        if manager_event is None:
            raise FlowError(
                "MANAGER_AUTHORIZATION_INVALID",
                "manager authority gate produced no consumption event",
            )
        linked.append(manager_event)
        prepared_manager_state = _manager_engine_evaluation_state_v1(
            old_state, event_type=event_type
        )
        if not isinstance(prepared_manager_state, dict):
            raise FlowError(
                "MANAGER_PREAUTHORIZATION_REQUIRED",
                "manager proof has no pre-evaluated nonce state",
            )
        manager_evaluation_state = prepared_manager_state
        manager_authorization_binding = {
            "event_type": manager_event[0],
            "payload": copy.deepcopy(manager_event[1]),
        }
    try:
        proof = _workflow_transition_mint_engine_commit_proof(
            old_state,
            _engine_commit_evaluation,
            task_dir,
            event_type,
            payload,
            additional_events=linked,
            verified_receipt=_verified_receipt,
            manager_evaluation_state=manager_evaluation_state,
            manager_authorization=manager_authorization_binding,
        )
    except TransitionEngineError as exc:
        raise FlowError(exc.code, exc.message, details=exc.details) from exc
    return _persist_state_transaction(
        old_state,
        new_state,
        task_dir,
        event_type,
        payload,
        additional_events=linked,
        _engine_commit_proof=proof,
        _verified_receipt=_verified_receipt,
    )


def _persist_state_transaction(
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any],
    task_dir: Path,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    additional_events: Sequence[
        tuple[str, dict[str, Any]]
    ] | None = None,
    _event_ids: Sequence[str] | None = None,
    _transaction_id: str | None = None,
    _engine_commit_proof: object = None,
    _verified_receipt: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Raw revision/outbox persistence; callers must authorize beforehand."""

    linked = tuple(additional_events or ())
    if (
        old_state is not None
        and old_state.get("schema_version") == V4_TASK_SCHEMA_VERSION
    ):
        try:
            _workflow_transition_consume_engine_commit(
                _engine_commit_proof,
                old_state,
                new_state,
                task_dir,
                event_type=event_type,
                payload=payload,
                additional_events=linked,
                event_ids=_event_ids,
                transaction_id=_transaction_id,
                verified_receipt=_verified_receipt,
            )
        except TransitionEngineError as exc:
            raise FlowError(exc.code, exc.message, details=exc.details) from exc

    previous_revision = int(old_state.get("revision", 0)) if old_state else 0
    revision = previous_revision + 1
    now = utc_now()
    new_state["revision"] = revision
    new_state["updated_at"] = now
    event_specs = [
        (event_type, payload or {}),
        *linked,
    ]
    if _event_ids is None:
        event_ids = [str(uuid.uuid4()) for _item in event_specs]
    else:
        event_ids = list(_event_ids)
        if (
            len(event_ids) != len(event_specs)
            or any(
                not isinstance(item, str) or not item
                for item in event_ids
            )
            or len(event_ids) != len(set(event_ids))
        ):
            raise FlowError(
                "STATE_EVENT_PLAN_INVALID",
                "preallocated event identities do not match the transaction",
            )
    transaction_id = (
        _transaction_id
        if len(event_specs) > 1
        else None
    )
    if len(event_specs) > 1 and transaction_id is None:
        transaction_id = str(uuid.uuid4())
    if (
        transaction_id is not None
        and (
            not isinstance(transaction_id, str)
            or not transaction_id
        )
    ):
        raise FlowError(
            "STATE_EVENT_PLAN_INVALID",
            "preallocated transaction identity is invalid",
        )
    events: list[dict[str, Any]] = []
    for event_id, (
        recorded_type,
        recorded_payload,
    ) in zip(event_ids, event_specs):
        event = {
            "event_id": event_id,
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "task_id": new_state["task_id"],
            "type": recorded_type,
            "at": now,
            "actor": _actor(),
            "previous_revision": previous_revision,
            "revision": revision,
            "status": new_state["status"],
            "payload": recorded_payload,
        }
        if transaction_id is not None:
            event["transaction_id"] = transaction_id
        events.append(event)
    # The state snapshot is the durable outbox.  A crash after this atomic
    # replacement but before JSONL delivery is recoverable without advancing
    # state a second time or losing the audit event.
    if len(events) == 1:
        new_state["pending_event"] = events[0]
    else:
        if new_state.get("schema_version") != V4_TASK_SCHEMA_VERSION:
            raise FlowError(
                "UNSUPPORTED_STATE",
                "batched audit facts require the current V4 task schema",
                details={
                    "task_id": new_state.get("task_id"),
                    "schema_version": new_state.get("schema_version"),
                },
            )
        new_state["pending_events"] = events
    _redact_state_in_place(new_state)
    stored_events = (
        new_state.get("pending_events")
        if len(events) > 1
        else [new_state.get("pending_event")]
    )
    event = dict(stored_events[0])
    _atomic_write_json(task_dir / "state.json", new_state)
    try:
        _flush_pending_event(task_dir, new_state)
    except FlowError as exc:
        raise FlowError(
            "EVENT_DELIVERY_PENDING",
            "state was committed but its audit event is pending durable delivery",
            details={
                "task_id": new_state.get("task_id"),
                "revision": revision,
                "event_ids": [item.get("event_id") for item in events],
                "recovery": "reload the task to retry the pending event outbox",
            },
        ) from exc
    _complete_mutation_intent(task_dir, revision)
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


def _validate_loaded_state_for_mutation(
    state_path: Path,
    state_value: dict[str, Any],
) -> Mapping[str, object]:
    """Resolve immutable workflow truth before any mutation-side effect."""

    try:
        return validate_task_state_for_mutation(
            state_value,
            resolver=resolve_loaded_task_workflow,
        )
    except WorkflowStateError as exc:
        raise FlowError(
            exc.code,
            exc.message,
            details={
                "path": str(state_path),
                **dict(exc.details),
            },
        ) from exc


@contextlib.contextmanager
def _locked_state(
    task_id: str,
    data_dir: str | os.PathLike[str] | None,
    expected_revision: int,
    *,
    lock_workspace_registry: bool = False,
    manager_effect_policy: str = "generic",
    manager_action_id: str | None = None,
    allow_quarantine: bool = False,
    short_v4_effect_boundary: bool = False,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    task_dir = _task_dir(task_id, data_dir)
    detached_v4_snapshot: tuple[Path, dict[str, Any]] | None = None
    preauthorization_open = False
    try:
        with _task_lock(
            task_dir, allow_quarantine=allow_quarantine
        ):
            state_path = task_dir / "state.json"
            state_value = _read_task_state_structural_snapshot(
                state_path
            )
            _check_revision(state_value, expected_revision)
            _validate_loaded_state_for_mutation(
                state_path, state_value
            )
            _validate_task_state_snapshot(
                state_path, state_value, resolve_workflow=False
            )
            manager_process_commit_gate_v1(
                state_value,
                state_value,
                "manager_effect_preauthorized",
                _effect_lifecycle=(
                    "preauthorize",
                    manager_effect_policy,
                ),
                _effect_package_action_id=manager_action_id,
            )
            preauthorization_open = True
            state_value = _finish_loaded_state(state_path, state_value)
            if (
                short_v4_effect_boundary
                and state_value.get("schema_version")
                == V4_TASK_SCHEMA_VERSION
            ):
                detached_v4_snapshot = (
                    task_dir,
                    _copy_state(state_value),
                )
            else:
                try:
                    if (
                        lock_workspace_registry
                        or state_value.get("schema_version")
                        == V4_TASK_SCHEMA_VERSION
                    ):
                        with _workspace_registry_lock(
                            resolve_data_dir(data_dir)
                        ):
                            yield task_dir, state_value
                    else:
                        yield task_dir, state_value
                finally:
                    manager_process_commit_gate_v1(
                        state_value,
                        state_value,
                        "manager_effect_closed",
                        _effect_lifecycle=(
                            "clear",
                            manager_effect_policy,
                        ),
                    )
                    preauthorization_open = False
                return
        if detached_v4_snapshot is None:
            raise FlowError(
                "MANAGER_EFFECT_BOUNDARY_INVALID",
                "short schema-v4 effect boundary produced no snapshot",
            )
        yield detached_v4_snapshot
    finally:
        if preauthorization_open:
            authorization_state = (
                detached_v4_snapshot[1]
                if detached_v4_snapshot is not None
                else state_value
            )
            manager_process_commit_gate_v1(
                authorization_state,
                authorization_state,
                "manager_effect_closed",
                _effect_lifecycle=(
                    "clear",
                    manager_effect_policy,
                ),
            )


def _posix_process_group_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise
    return True


def _quiesce_completed_process_group(
    process: subprocess.Popen[bytes], command: Sequence[str]
) -> None:
    if not _posix_process_group_alive(process.pid):
        return
    for signal_number, timeout_seconds in ((15, 2.0), (9, 5.0)):
        try:
            os.killpg(process.pid, signal_number)
        except ProcessLookupError:
            return
        except OSError:
            pass
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not _posix_process_group_alive(process.pid):
                return
            time.sleep(0.05)
    error = RuntimeError(
        "owned process group remained active after its leader exited"
    )
    quarantine = _persist_mutation_quarantine(process, command, error)
    raise FlowError(
        "MUTATION_QUARANTINED",
        "mutating child descendants could not be proven quiescent",
        details={
            "pid": process.pid,
            "process_group": process.pid,
            "command": _redacted_command(command),
            "quarantine": str(quarantine) if quarantine else None,
        },
    )


_MUTATION_GATE_ENVELOPE = b"DEV_FLOW_GATE_V1:"
_MUTATION_GATE_CODE = """
import base64
import json
import subprocess
import sys

gate = sys.stdin.buffer.read(1)
command = json.loads(sys.argv[1])
if gate != b"G":
    sys.exit(253)
try:
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    envelope = {
        "version": 1,
        "status": "completed",
        "returncode": result.returncode,
        "stdout": base64.b64encode(result.stdout).decode("ascii"),
        "stderr": base64.b64encode(result.stderr).decode("ascii"),
    }
except (OSError, ValueError, subprocess.SubprocessError) as exc:
    envelope = {
        "version": 1,
        "status": "spawn_error",
        "error": str(exc),
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
    }
payload = json.dumps(
    envelope,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8", "backslashreplace")
sys.stdout.buffer.write(b"DEV_FLOW_GATE_V1:" + payload)
sys.stdout.buffer.flush()
""".strip()
def _mutation_gate_command(
    command: Sequence[str],
) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-S",
        "-c",
        _MUTATION_GATE_CODE,
        json.dumps(list(command), ensure_ascii=True),
    ]


def _terminate_and_quiesce_owned_child(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    protected_child: bool,
) -> bool:
    """Best-effort termination whose result is safe to use before unlock."""

    try:
        if protected_child:
            process_group = process.pid
            if _posix_process_group_alive(process_group):
                try:
                    os.killpg(process_group, 15)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 2.0
            while (
                time.monotonic() < deadline
                and _posix_process_group_alive(process_group)
            ):
                time.sleep(0.05)
            if _posix_process_group_alive(process_group):
                try:
                    os.killpg(process_group, 9)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
            deadline = time.monotonic() + 5.0
            while (
                time.monotonic() < deadline
                and _posix_process_group_alive(process_group)
            ):
                time.sleep(0.05)
            return not _posix_process_group_alive(process_group)
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
        return process.poll() is not None
    except BaseException:
        return False


def _parse_mutation_gate_envelope(
    stdout: bytes, stderr: bytes, returncode: int
) -> dict[str, Any]:
    if (
        returncode != 0
        or stderr
        or not stdout.startswith(_MUTATION_GATE_ENVELOPE)
    ):
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate did not return its private completion envelope",
            details={
                "gate_returncode": returncode,
                "stdout_sha256": _sha256_bytes(stdout),
                "stderr_sha256": _sha256_bytes(stderr),
            },
        )
    payload = stdout[len(_MUTATION_GATE_ENVELOPE) :]
    try:
        envelope = json.loads(payload.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate returned an invalid completion envelope",
            details={
                "payload_sha256": _sha256_bytes(payload),
                "error": str(exc),
            },
        ) from exc
    if not isinstance(envelope, dict) or envelope.get("version") != 1:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate returned an unsupported completion envelope",
        )
    status = envelope.get("status")
    if status == "spawn_error":
        return envelope
    returncode_value = envelope.get("returncode")
    if (
        status != "completed"
        or not isinstance(returncode_value, int)
        or isinstance(returncode_value, bool)
        or not isinstance(envelope.get("stdout"), str)
        or not isinstance(envelope.get("stderr"), str)
    ):
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate completion envelope is incomplete",
        )
    import base64
    import binascii

    try:
        target_stdout = base64.b64decode(
            envelope["stdout"].encode("ascii"), validate=True
        )
        target_stderr = base64.b64decode(
            envelope["stderr"].encode("ascii"), validate=True
        )
    except (UnicodeError, binascii.Error) as exc:
        raise FlowError(
            "MUTATION_GATE_PROTOCOL_FAILED",
            "mutation gate completion bytes are invalid",
            details={"error": str(exc)},
        ) from exc
    return {
        **envelope,
        "stdout_bytes": target_stdout,
        "stderr_bytes": target_stderr,
    }


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    text: bool = True,
    evidence_git: bool = False,
    mutation: bool = False,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    executable = (
        re.split(r"[\\/]", str(command[0]))[-1].casefold()
        if command
        else ""
    )
    is_git = executable in {"git", "git.exe"}
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
                "GIT_EXEC_PATH",
                "GIT_SHALLOW_FILE",
                "GIT_GRAFT_FILE",
                "GIT_TEMPLATE_DIR",
                "GIT_REPLACE_REF_BASE",
                "GIT_ALLOW_PROTOCOL",
                "GIT_PROTOCOL_FROM_USER",
                "GIT_REDIRECT_STDERR",
            } or key.startswith(
                (
                    "GIT_CONFIG_KEY_",
                    "GIT_CONFIG_VALUE_",
                    "GIT_TRACE",
                )
            ):
                environment.pop(key, None)
        environment.pop("GIT_CONFIG_COUNT", None)
        for key in (
            "GIT_ASKPASS",
            "GIT_PROXY_COMMAND",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GIT_SSH_VARIANT",
            "SSH_ASKPASS",
            "SSH_ASKPASS_REQUIRE",
        ):
            environment.pop(key, None)
        environment["GIT_CONFIG_NOSYSTEM"] = "1"
        environment["GIT_CONFIG_GLOBAL"] = os.devnull
        environment["GIT_CONFIG_SYSTEM"] = os.devnull
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["SSH_ASKPASS_REQUIRE"] = "never"
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        environment["GIT_NO_LAZY_FETCH"] = "1"
        # Disable environment-selected and repository-local module grafts.
        environment["GIT_GRAFT_FILE"] = os.devnull
    if evidence_git:
        environment.pop("GIT_EXTERNAL_DIFF", None)
        environment.pop("GIT_DIFF_OPTS", None)
    protected_child = bool(_HELD_LOCK_DIRECTORIES.get())
    if mutation and not protected_child:
        raise FlowError(
            "MUTATION_LOCK_REQUIRED",
            "a mutating child cannot start outside a controller lock",
            details={"command": _redacted_command(command)},
        )
    mutation_intent = (
        _begin_mutation_intent(command) if mutation else None
    )
    gated_mutation = bool(mutation and protected_child)
    launch_command = (
        _mutation_gate_command(command)
        if gated_mutation
        else list(command)
    )
    process_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": environment,
        "stdin": (
            subprocess.PIPE
            if gated_mutation
            else subprocess.DEVNULL
        ),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": False,
    }
    if protected_child:
        process_kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(launch_command, **process_kwargs)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _abandon_unstarted_mutation_intent(mutation_intent)
        raise FlowError(
            "COMMAND_FAILED",
            f"could not execute {command[0]}",
            details={
                "command": _redacted_command(command),
                "cwd": str(cwd) if cwd else None,
                "error": str(exc),
                "failure_kind": "spawn",
                "errno": getattr(exc, "errno", None),
            },
        ) from exc
    if mutation:
        try:
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase="child_owned",
            )
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase="target_release_authorized",
                target_release_authorized=True,
            )
        except BaseException as exc:
            cleanup_error: BaseException | None = None
            try:
                _terminate_and_quiesce_owned_child(
                    process,
                    command,
                    protected_child=protected_child,
                )
            except BaseException as nested_error:
                cleanup_error = nested_error
                if protected_child:
                    try:
                        os.killpg(process.pid, 9)
                    except BaseException:
                        pass
            quarantine = _persist_mutation_quarantine(
                process, command, cleanup_error or exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                (
                    "mutating child ownership was established but its "
                    "durable PID evidence could not be updated"
                ),
                details={
                    "pid": process.pid,
                    "command": _redacted_command(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
    try:
        if gated_mutation:
            stdout_bytes, stderr_bytes = process.communicate(
                input=b"G"
            )
        else:
            stdout_bytes, stderr_bytes = process.communicate()
        if protected_child:
            _quiesce_completed_process_group(process, command)
    except BaseException as exc:
        cleanup_error = None
        try:
            quiescent = _terminate_and_quiesce_owned_child(
                process,
                command,
                protected_child=protected_child,
            )
        except BaseException as nested_error:
            quiescent = False
            cleanup_error = nested_error
            if protected_child:
                try:
                    os.killpg(process.pid, 9)
                except BaseException:
                    pass
        if not quiescent:
            quarantine = _persist_mutation_quarantine(
                process, command, cleanup_error or exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "protected child failed and could not be proven quiescent",
                details={
                    "pid": process.pid,
                    "command": _redacted_command(command),
                    "quarantine": str(quarantine) if quarantine else None,
                },
            ) from exc
        if mutation:
            try:
                _update_mutation_intent(
                    mutation_intent,
                    process,
                    command,
                    phase="interrupted_quiescent",
                    cause=exc,
                )
            except BaseException as evidence_error:
                quarantine = _persist_mutation_quarantine(
                    process, command, evidence_error
                )
                raise FlowError(
                    "MUTATION_QUARANTINED",
                    "child was quiesced but interruption evidence could not be finalized",
                    details={
                        "pid": process.pid,
                        "quarantine": (
                            str(quarantine) if quarantine else None
                        ),
                    },
                ) from evidence_error
        raise
    stdout_bytes = stdout_bytes or b""
    stderr_bytes = stderr_bytes or b""
    effective_returncode = int(process.returncode or 0)
    if gated_mutation:
        try:
            gate_envelope = _parse_mutation_gate_envelope(
                stdout_bytes,
                stderr_bytes,
                effective_returncode,
            )
        except FlowError as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "mutation gate completion could not be authenticated",
                details={
                    "pid": process.pid,
                    "command": _redacted_command(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
        if gate_envelope.get("status") == "spawn_error":
            spawn_details = {
                key: gate_envelope.get(key)
                for key in ("error", "errno", "winerror")
            }
            _abandon_unstarted_mutation_intent(mutation_intent)
            raise FlowError(
                "COMMAND_FAILED",
                f"could not execute {command[0]}",
                details={
                    "command": _redacted_command(command),
                    "cwd": str(cwd) if cwd else None,
                    "failure_kind": "spawn",
                    **spawn_details,
                },
            )
        effective_returncode = int(gate_envelope["returncode"])
        stdout_bytes = gate_envelope["stdout_bytes"]
        stderr_bytes = gate_envelope["stderr_bytes"]
    if mutation:
        try:
            _update_mutation_intent(
                mutation_intent,
                process,
                command,
                phase=(
                    "child_quiescent"
                    if effective_returncode == 0
                    else "child_failed_quiescent"
                ),
            )
        except BaseException as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "child exited but durable mutation evidence could not be finalized",
                details={
                    "pid": process.pid,
                    "command": _redacted_command(command),
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
    if text:
        stdout: Any = stdout_bytes.decode("utf-8", "backslashreplace")
        stderr: Any = stderr_bytes.decode("utf-8", "backslashreplace")
    else:
        stdout = stdout_bytes
        stderr = stderr_bytes
    result = subprocess.CompletedProcess(
        args=list(command),
        returncode=effective_returncode,
        stdout=stdout,
        stderr=stderr,
    )
    if check and result.returncode != 0:
        rendered_stderr = (
            result.stderr.strip()
            if text
            else result.stderr.decode("utf-8", "backslashreplace").strip()
        )
        raise FlowError(
            "COMMAND_FAILED",
            f"command failed with exit code {result.returncode}",
            details={
                "command": _redacted_command(command),
                "cwd": str(cwd) if cwd else None,
                "stderr": rendered_stderr,
                "stderr_sha256": _sha256_bytes(stderr_bytes),
                "failure_kind": "exit",
                "returncode": result.returncode,
            },
        )
    return result
