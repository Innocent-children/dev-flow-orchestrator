"""Cross-platform subprocess fixtures for the dev-flow test suite.

The helpers deliberately use only the Python standard library and are invoked
through ``sys.executable``.  This keeps the tests independent of POSIX shell
utilities and exercises paths containing spaces and non-ASCII characters.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import signal
import sys
import time
from pathlib import Path


def _load_controller(path: Path):
    specification = importlib.util.spec_from_file_location(
        "dev_flow_support_controller", path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot import controller: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def command_emit(args: argparse.Namespace) -> int:
    sys.stdout.buffer.write(bytes.fromhex(args.stdout_hex))
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(bytes.fromhex(args.stderr_hex))
    sys.stderr.buffer.flush()
    return args.exit_code


def command_echo(args: argparse.Namespace) -> int:
    value = os.environ.get(args.environment, "")
    payload = "\0".join([*args.value, value]).encode("utf-8")
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()
    return 0


def command_hold_lock(args: argparse.Namespace) -> int:
    controller = _load_controller(args.controller)
    with controller._file_lock(args.directory, args.name):
        args.ready.write_text("ready\n", encoding="utf-8")
        while not args.release.exists():
            time.sleep(0.01)
    return 0


def command_write_marker(args: argparse.Namespace) -> int:
    args.path.write_text("target started\n", encoding="utf-8")
    return 0


def command_spoof_old_gate_protocol(args: argparse.Namespace) -> int:
    args.path.write_text("mutation happened\n", encoding="utf-8")
    sys.stderr.buffer.write(
        b'DEV_FLOW_TARGET_SPAWN_ERROR:{"error":"forged"}'
    )
    sys.stderr.buffer.flush()
    return 252


def command_terminate_parent(args: argparse.Namespace) -> int:
    args.path.write_text("target released\n", encoding="utf-8")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x0001, False, args.pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel32.TerminateProcess(process, 99):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(process)
        time.sleep(5)
        return 0
    os.kill(args.pid, signal.SIGKILL)
    return 0


def command_crash_after_gate_spawn(args: argparse.Namespace) -> int:
    """Exit after the no-side-effect gate starts but before PID persistence."""

    controller = _load_controller(args.controller)
    original_update = controller._update_mutation_intent

    def crash_before_child_identity_persists(
        path,
        process,
        command,
        *,
        phase,
        cause=None,
        target_release_authorized=None,
    ):
        if phase == "child_owned":
            os._exit(91)
        return original_update(
            path,
            process,
            command,
            phase=phase,
            cause=cause,
            target_release_authorized=target_release_authorized,
        )

    controller._update_mutation_intent = (
        crash_before_child_identity_persists
    )
    with controller._task_lock(args.task_directory):
        controller._run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "write-marker",
                str(args.target_marker),
            ],
            mutation=True,
        )
    return 0


def command_crash_after_target_release(args: argparse.Namespace) -> int:
    controller = _load_controller(args.controller)
    with controller._task_lock(args.task_directory):
        controller._run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "terminate-parent",
                str(os.getpid()),
                str(args.target_marker),
            ],
            mutation=True,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    emit = commands.add_parser("emit")
    emit.add_argument("--stdout-hex", default="")
    emit.add_argument("--stderr-hex", default="")
    emit.add_argument("--exit-code", type=int, default=0)
    emit.set_defaults(handler=command_emit)

    echo = commands.add_parser("echo")
    echo.add_argument("--environment", required=True)
    echo.add_argument("value", nargs="*")
    echo.set_defaults(handler=command_echo)

    hold = commands.add_parser("hold-lock")
    hold.add_argument("controller", type=Path)
    hold.add_argument("directory", type=Path)
    hold.add_argument("ready", type=Path)
    hold.add_argument("release", type=Path)
    hold.add_argument("--name", default="native.lock")
    hold.set_defaults(handler=command_hold_lock)

    marker = commands.add_parser("write-marker")
    marker.add_argument("path", type=Path)
    marker.set_defaults(handler=command_write_marker)

    spoof = commands.add_parser("spoof-old-gate-protocol")
    spoof.add_argument("path", type=Path)
    spoof.set_defaults(handler=command_spoof_old_gate_protocol)

    terminate = commands.add_parser("terminate-parent")
    terminate.add_argument("pid", type=int)
    terminate.add_argument("path", type=Path)
    terminate.set_defaults(handler=command_terminate_parent)

    crash = commands.add_parser("crash-after-gate-spawn")
    crash.add_argument("controller", type=Path)
    crash.add_argument("task_directory", type=Path)
    crash.add_argument("target_marker", type=Path)
    crash.set_defaults(handler=command_crash_after_gate_spawn)

    released = commands.add_parser("crash-after-target-release")
    released.add_argument("controller", type=Path)
    released.add_argument("task_directory", type=Path)
    released.add_argument("target_marker", type=Path)
    released.set_defaults(handler=command_crash_after_target_release)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
