"""Bounded binary subprocess execution with host-specific pipe handling."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import threading
import time
from typing import Mapping, NamedTuple, Optional, Sequence


READ_CHUNK_BYTES = 64 * 1024
POLL_SECONDS = 0.1
TERMINATE_GRACE_SECONDS = 1.0


class ProcessResult(NamedTuple):
    returncode: int
    stdout: bytes
    stderr: bytes


class ProcessFailure(Exception):
    def __init__(self, kind: str, **details: object) -> None:
        super().__init__(kind)
        self.kind = kind
        self.details = details


def _posix_terminate(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=TERMINATE_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            pass


def _windows_terminate(process: subprocess.Popen, environment: Mapping[str, str]) -> None:
    system_root = environment.get("SystemRoot") or environment.get("SYSTEMROOT")
    taskkill = os.path.join(system_root, "System32", "taskkill.exe") if system_root else "taskkill.exe"
    try:
        subprocess.run(
            [taskkill, "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=TERMINATE_GRACE_SECONDS,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _cancelled(cancel_event: Optional[threading.Event]) -> bool:
    return cancel_event is not None and cancel_event.is_set()


def _run_posix(
    command: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
    cancel_event: Optional[threading.Event],
) -> ProcessResult:
    try:
        process = subprocess.Popen(
            list(command), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(environment),
            start_new_session=True,
        )
    except OSError as exc:
        raise ProcessFailure("unavailable", error=str(exc)) from exc
    stdout = bytearray()
    stderr = bytearray()
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + max(0.001, timeout_seconds)
    try:
        if process.stdout is None or process.stderr is None:
            _posix_terminate(process)
            raise ProcessFailure("unavailable")
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        while selector.get_map():
            if _cancelled(cancel_event):
                _posix_terminate(process)
                raise ProcessFailure("cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _posix_terminate(process)
                raise ProcessFailure("timeout")
            events = selector.select(min(remaining, POLL_SECONDS) if cancel_event else remaining)
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), READ_CHUNK_BYTES)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                key.data.extend(chunk)
                if len(stdout) + len(stderr) > output_limit_bytes:
                    _posix_terminate(process)
                    raise ProcessFailure(
                        "output-too-large", limit_bytes=output_limit_bytes,
                        stdout_bytes=len(stdout), stderr_bytes=len(stderr),
                    )
        while True:
            if _cancelled(cancel_event):
                _posix_terminate(process)
                raise ProcessFailure("cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _posix_terminate(process)
                raise ProcessFailure("timeout")
            try:
                returncode = process.wait(timeout=min(remaining, POLL_SECONDS) if cancel_event else remaining)
                return ProcessResult(returncode, bytes(stdout), bytes(stderr))
            except subprocess.TimeoutExpired:
                continue
    except ProcessFailure:
        raise
    except (OSError, ValueError, KeyError) as exc:
        _posix_terminate(process)
        raise ProcessFailure("io-failed", error=str(exc)) from exc
    finally:
        selector.close()
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _run_windows(
    command: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
    cancel_event: Optional[threading.Event],
) -> ProcessResult:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            list(command), shell=False, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(environment),
            creationflags=creationflags,
        )
    except OSError as exc:
        raise ProcessFailure("unavailable", error=str(exc)) from exc
    if process.stdout is None or process.stderr is None:
        _windows_terminate(process, environment)
        raise ProcessFailure("unavailable")

    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    counts = {"stdout": 0, "stderr": 0}
    state_lock = threading.Lock()
    overflow = threading.Event()
    reader_error = []

    def read_stream(name: str, stream: object) -> None:
        try:
            while True:
                chunk = stream.read(READ_CHUNK_BYTES)
                if not chunk:
                    return
                with state_lock:
                    counts[name] += len(chunk)
                    remaining = max(0, output_limit_bytes - sum(len(value) for value in buffers.values()))
                    if remaining:
                        buffers[name].extend(chunk[:remaining])
                    if counts["stdout"] + counts["stderr"] > output_limit_bytes:
                        overflow.set()
        except (OSError, ValueError) as exc:
            with state_lock:
                reader_error.append(str(exc))

    threads = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + max(0.001, timeout_seconds)
    failure = None
    while True:
        if _cancelled(cancel_event):
            failure = ProcessFailure("cancelled")
            break
        if overflow.is_set():
            with state_lock:
                failure = ProcessFailure(
                    "output-too-large", limit_bytes=output_limit_bytes,
                    stdout_bytes=counts["stdout"], stderr_bytes=counts["stderr"],
                )
            break
        with state_lock:
            if reader_error:
                failure = ProcessFailure("io-failed", error=reader_error[0])
                break
        if time.monotonic() >= deadline:
            failure = ProcessFailure("timeout")
            break
        if process.poll() is not None and all(not thread.is_alive() for thread in threads):
            break
        time.sleep(min(POLL_SECONDS, max(0.0, deadline - time.monotonic())))

    if failure is not None:
        _windows_terminate(process, environment)
        for thread in threads:
            thread.join()
    else:
        for thread in threads:
            thread.join()
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass
    if failure is not None:
        raise failure
    with state_lock:
        if reader_error:
            raise ProcessFailure("io-failed", error=reader_error[0])
        if counts["stdout"] + counts["stderr"] > output_limit_bytes:
            raise ProcessFailure(
                "output-too-large", limit_bytes=output_limit_bytes,
                stdout_bytes=counts["stdout"], stderr_bytes=counts["stderr"],
            )
        return ProcessResult(process.returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"]))


def run_bounded_process(
    command: Sequence[str],
    environment: Mapping[str, str],
    timeout_seconds: float,
    output_limit_bytes: int,
    cancel_event: Optional[threading.Event] = None,
) -> ProcessResult:
    if os.name == "nt":
        return _run_windows(command, environment, timeout_seconds, output_limit_bytes, cancel_event)
    return _run_posix(command, environment, timeout_seconds, output_limit_bytes, cancel_event)
