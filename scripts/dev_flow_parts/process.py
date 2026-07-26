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
) -> dict[str, Any]:
    previous_revision = int(old_state.get("revision", 0)) if old_state else 0
    revision = previous_revision + 1
    now = utc_now()
    new_state["revision"] = revision
    new_state["updated_at"] = now
    event_specs = [(event_type, payload or {}), *(additional_events or ())]
    transaction_id = str(uuid.uuid4()) if len(event_specs) > 1 else None
    events: list[dict[str, Any]] = []
    for recorded_type, recorded_payload in event_specs:
        event = {
            "event_id": str(uuid.uuid4()),
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
        if int(new_state.get("schema_version", 1)) < TASK_SCHEMA_VERSION:
            raise FlowError(
                "UNSUPPORTED_STATE",
                "batched audit facts require task schema v2",
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


@contextlib.contextmanager
def _locked_state(
    task_id: str,
    data_dir: str | os.PathLike[str] | None,
    expected_revision: int,
    *,
    lock_workspace_registry: bool = False,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    task_dir = _task_dir(task_id, data_dir)
    with _task_lock(task_dir):
        state_value = load_state(task_id, data_dir)
        _check_revision(state_value, expected_revision)
        if lock_workspace_registry:
            with _workspace_registry_lock(resolve_data_dir(data_dir)):
                yield task_dir, state_value
        else:
            yield task_dir, state_value


def _posix_process_group_alive(process_group: int) -> bool:
    if os.name == "nt":  # pragma: no cover - POSIX helper
        return False
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
    if os.name == "nt" or not _posix_process_group_alive(process.pid):
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


def _windows_kill_on_close_job(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    require_ownership: bool = True,
) -> Any:
    """Place a protected child in a kill-on-close job.

    ``require_ownership`` is true for a gated mutation, whose child is blocked
    reading its gate byte and is therefore provably still alive: failing to
    own it is a real failure and stays fail-closed, because kill-on-job-close
    containment is what the quarantine mechanism relies on.  A read-only
    protected child is contained on the same terms when Windows allows it, but
    an unownable one is not an error; see the failure branch below.
    """

    if os.name != "nt":  # pragma: no cover - native Windows helper
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
    ]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def ownership_failure(message: str, error: int) -> None:
        try:
            process.terminate()
            process.wait(timeout=5.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            quarantine = _persist_mutation_quarantine(
                process, command, exc
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "unowned Windows child could not be proven quiescent",
                details={
                    "pid": process.pid,
                    "winerror": error,
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from exc
        raise FlowError(
            "PROCESS_OWNERSHIP_FAILED",
            message,
            details={"pid": process.pid, "winerror": error},
        )

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        if not require_ownership:
            return None
        ownership_failure(
            "could not create a Windows child-process job",
            ctypes.get_last_error(),
        )
    limits = EXTENDED_LIMITS()
    limits.BasicLimitInformation.LimitFlags = 0x00002000
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel32.AssignProcessToJobObject(
        job, wintypes.HANDLE(process._handle)  # type: ignore[attr-defined]
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        if not require_ownership:
            # Containment of a read-only child is best effort, not a
            # precondition.  Such a child runs under DEVNULL stdin with no
            # gate holding it, so it regularly finishes between Popen and
            # this assignment, and Windows answers ERROR_ACCESS_DENIED for a
            # process that has terminated or is terminating -- sometimes
            # before its handle is even signalled, so an exit check cannot
            # recognize every instance.  There is no mutation to contain, so
            # continue with an unowned child rather than failing a read-only
            # command with a mutation-ownership error.
            return None
        ownership_failure(
            "could not place a mutating child in an owned Windows job",
            error,
        )
    return job


def _terminate_windows_job(job: Any) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
    ]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    if not kernel32.TerminateJobObject(job, 1):
        raise OSError(
            ctypes.get_last_error(), "TerminateJobObject failed"
        )


def _windows_job_active_processes(job: Any) -> int:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return 0
    import ctypes
    from ctypes import wintypes

    class BASIC_ACCOUNTING(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    accounting = BASIC_ACCOUNTING()
    returned = wintypes.DWORD()
    if not kernel32.QueryInformationJobObject(
        job,
        1,  # JobObjectBasicAccountingInformation
        ctypes.byref(accounting),
        ctypes.sizeof(accounting),
        ctypes.byref(returned),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "QueryInformationJobObject failed",
        )
    return int(accounting.ActiveProcesses)


def _quiesce_windows_job(
    job: Any,
    process: subprocess.Popen[bytes],
    command: Sequence[str],
) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    try:
        active = _windows_job_active_processes(job)
        if active:
            _terminate_windows_job(job)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if _windows_job_active_processes(job) == 0:
                    return
                time.sleep(0.05)
            active = _windows_job_active_processes(job)
        if active:
            raise OSError(
                errno.EBUSY,
                f"Windows job still contains {active} active processes",
            )
    except OSError as exc:
        quarantine = _persist_mutation_quarantine(
            process, command, exc
        )
        raise FlowError(
            "MUTATION_QUARANTINED",
            "Windows child job could not be proven quiescent",
            details={
                "pid": process.pid,
                "command": _redacted_command(command),
                "quarantine": (
                    str(quarantine) if quarantine else None
                ),
                "error": str(exc),
            },
        ) from exc


def _close_windows_job(job: Any) -> None:
    if os.name != "nt" or not job:  # pragma: no cover - native Windows
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(job):
        raise OSError(ctypes.get_last_error(), "CloseHandle failed")


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
# Compatibility aliases retained for focused downstream tests and diagnostics.
_WINDOWS_MUTATION_GATE_CODE = _MUTATION_GATE_CODE


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


def _windows_mutation_gate_command(
    command: Sequence[str],
) -> list[str]:
    return _mutation_gate_command(command)


def _terminate_and_quiesce_owned_child(
    process: subprocess.Popen[bytes],
    command: Sequence[str],
    *,
    protected_child: bool,
    windows_job: Any,
) -> bool:
    """Best-effort termination whose result is safe to use before unlock."""

    try:
        if os.name == "nt" and windows_job:
            _terminate_windows_job(windows_job)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                pass
            _quiesce_windows_job(windows_job, process, command)
            return _windows_job_active_processes(windows_job) == 0
        if os.name != "nt" and protected_child:
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
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["SSH_ASKPASS_REQUIRE"] = "never"
        environment["GIT_NO_REPLACE_OBJECTS"] = "1"
        environment["GIT_NO_LAZY_FETCH"] = "1"
        # Disable both environment-selected and repository-local legacy grafts.
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
    if protected_child and os.name == "nt":  # pragma: no cover - native Windows
        process_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    elif protected_child:
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
    windows_job: Any = None
    if protected_child and os.name == "nt":  # pragma: no cover - native Windows
        try:
            windows_job = _windows_kill_on_close_job(
                process, command, require_ownership=gated_mutation
            )
        except FlowError as exc:
            if (
                gated_mutation
                and exc.code == "PROCESS_OWNERSHIP_FAILED"
            ):
                _abandon_unstarted_mutation_intent(
                    mutation_intent
                )
            raise
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
                    windows_job=windows_job,
                )
            except BaseException as nested_error:
                cleanup_error = nested_error
                if os.name == "nt" and windows_job:
                    try:
                        _terminate_windows_job(windows_job)
                    except BaseException:
                        pass
                elif os.name != "nt" and protected_child:
                    try:
                        os.killpg(process.pid, 9)
                    except BaseException:
                        pass
            if os.name == "nt" and windows_job:
                try:
                    _close_windows_job(windows_job)
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
        if os.name == "nt" and windows_job:
            _quiesce_windows_job(
                windows_job, process, command
            )
        elif protected_child and os.name != "nt":
            _quiesce_completed_process_group(process, command)
    except BaseException as exc:
        cleanup_error = None
        try:
            quiescent = _terminate_and_quiesce_owned_child(
                process,
                command,
                protected_child=protected_child,
                windows_job=windows_job,
            )
        except BaseException as nested_error:
            quiescent = False
            cleanup_error = nested_error
            if os.name == "nt" and windows_job:
                try:
                    _terminate_windows_job(windows_job)
                except BaseException:
                    pass
            elif os.name != "nt" and protected_child:
                try:
                    os.killpg(process.pid, 9)
                except BaseException:
                    pass
        if not quiescent:
            quarantine = _persist_mutation_quarantine(
                process, command, cleanup_error or exc
            )
            try:
                _close_windows_job(windows_job)
            except BaseException:
                pass
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
                try:
                    _close_windows_job(windows_job)
                except BaseException:
                    pass
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
        try:
            _close_windows_job(windows_job)
        except BaseException as close_error:
            quarantine = _persist_mutation_quarantine(
                process, command, close_error
            )
            raise FlowError(
                "MUTATION_QUARANTINED",
                "Windows child job could not be closed after interruption",
                details={
                    "pid": process.pid,
                    "quarantine": (
                        str(quarantine) if quarantine else None
                    ),
                },
            ) from close_error
        raise
    try:
        _close_windows_job(windows_job)
    except BaseException as exc:
        quarantine = _persist_mutation_quarantine(process, command, exc)
        raise FlowError(
            "MUTATION_QUARANTINED",
            "Windows child-process ownership could not be released safely",
            details={
                "pid": process.pid,
                "command": _redacted_command(command),
                "quarantine": str(quarantine) if quarantine else None,
                "error": str(exc),
            },
        ) from exc
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
