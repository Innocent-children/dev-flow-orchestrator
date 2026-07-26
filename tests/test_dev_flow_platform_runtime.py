from __future__ import annotations

import argparse
import contextlib
import errno
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


if __package__:
    from . import dev_flow_test_case as test_case
else:
    import dev_flow_test_case as test_case

SCRIPT = test_case.SCRIPT
SUPPORT = test_case.SUPPORT
dev_flow = test_case.dev_flow
git = test_case.git


class DevFlowPlatformRuntimeTest(test_case.DevFlowTestCase):
    def test_windows_dacl_policy_is_fail_closed_under_mock_descriptors(self) -> None:
        path = self.root / "mock windows state"
        current_user = "S-1-5-21-1000"
        safe = {
            "owner": current_user,
            "current_user": current_user,
            "null_dacl": False,
            "aces": [],
        }
        with mock.patch.object(
            dev_flow,
            "_windows_security_descriptor",
            return_value=safe,
        ):
            dev_flow._verify_windows_private_path(path)

        system_owned = {
            **safe,
            "owner": "S-1-5-18",
            "aces": [
                {
                    "type": "allow",
                    "sid": current_user,
                    "mask": 0x00000002,
                    "inherited": False,
                    "unverifiable": False,
                }
            ],
        }
        with mock.patch.object(
            dev_flow,
            "_windows_security_descriptor",
            return_value=system_owned,
        ):
            dev_flow._verify_windows_private_path(path)

        unsafe_descriptors = (
            {**safe, "null_dacl": True},
            {
                **safe,
                "aces": [
                    {
                        "type": "allow",
                        "sid": "S-1-1-0",
                        "mask": 0x40000000,
                        "inherited": True,
                        "unverifiable": False,
                    }
                ],
            },
            {
                **safe,
                "aces": [
                    {
                        "type": 5,
                        "sid": None,
                        "mask": None,
                        "inherited": False,
                        "unverifiable": True,
                    }
                ],
            },
            {**safe, "owner": "S-1-5-21-foreign"},
        )
        for descriptor in unsafe_descriptors:
            with self.subTest(descriptor=descriptor):
                with mock.patch.object(
                    dev_flow,
                    "_windows_security_descriptor",
                    return_value=descriptor,
                ):
                    with self.assertRaises(
                        dev_flow.FlowError
                    ) as captured:
                        dev_flow._verify_windows_private_path(path)
                self.assertIn(
                    captured.exception.code,
                    {"PERMISSIONS_UNSAFE", "PERMISSIONS_UNVERIFIABLE"},
                )

    @unittest.skipUnless(
        os.name == "nt", "requires native Windows DACL APIs"
    )
    def test_windows_native_dacl_rejects_world_writable_path(self) -> None:
        import ctypes
        from ctypes import wintypes

        path = self.root / "native insecure windows state"
        path.mkdir()
        current_user = dev_flow._windows_security_descriptor(path)[
            "current_user"
        ]
        self.assertIsInstance(current_user, str)

        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
            wintypes.BOOL
        )
        advapi32.SetFileSecurityW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        advapi32.SetFileSecurityW.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p

        def apply_dacl(sddl: str) -> None:
            descriptor = ctypes.c_void_p()
            descriptor_size = wintypes.DWORD()
            if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl,
                1,
                ctypes.byref(descriptor),
                ctypes.byref(descriptor_size),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not advapi32.SetFileSecurityW(
                    str(path),
                    0x00000004,  # DACL_SECURITY_INFORMATION
                    descriptor,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel32.LocalFree(descriptor)

        safe_dacl = f"D:P(A;;GA;;;{current_user})"
        unsafe_dacl = (
            f"D:P(A;;GA;;;{current_user})(A;;GW;;;WD)"
        )
        apply_dacl(unsafe_dacl)
        try:
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._verify_windows_private_path(path)
            self.assertEqual(
                captured.exception.code, "PERMISSIONS_UNSAFE"
            )
        finally:
            apply_dacl(safe_dacl)

    def test_windows_process_handles_use_pointer_sized_ctypes_signatures(self) -> None:
        import ctypes
        from ctypes import wintypes

        class Function:
            def __init__(self, result, callback=None) -> None:
                self.result = result
                self.callback = callback
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, *arguments):
                self.calls.append(arguments)
                if self.callback is not None:
                    self.callback(*arguments)
                return self.result

        large_handle = 0x1_0000_1234

        process_kernel = mock.Mock()
        process_kernel.OpenProcess = Function(large_handle)
        process_kernel.WaitForSingleObject = Function(258)
        process_kernel.CloseHandle = Function(True)
        with mock.patch.object(
            dev_flow.os, "name", "nt"
        ), mock.patch.object(
            ctypes,
            "WinDLL",
            return_value=process_kernel,
            create=True,
        ), mock.patch.object(
            ctypes, "get_last_error", return_value=0, create=True
        ):
            self.assertTrue(
                dev_flow._quarantined_process_alive(4242)
            )
        self.assertIs(
            process_kernel.OpenProcess.restype, wintypes.HANDLE
        )
        self.assertEqual(
            process_kernel.WaitForSingleObject.argtypes[0],
            wintypes.HANDLE,
        )
        self.assertEqual(
            process_kernel.WaitForSingleObject.calls,
            [(large_handle, 0)],
        )
        self.assertEqual(
            process_kernel.CloseHandle.argtypes,
            [wintypes.HANDLE],
        )
        self.assertEqual(
            process_kernel.CloseHandle.calls, [(large_handle,)]
        )

        process_kernel.WaitForSingleObject = Function(0)
        with mock.patch.object(
            dev_flow.os, "name", "nt"
        ), mock.patch.object(
            ctypes,
            "WinDLL",
            return_value=process_kernel,
            create=True,
        ), mock.patch.object(
            ctypes, "get_last_error", return_value=0, create=True
        ):
            self.assertFalse(
                dev_flow._quarantined_process_alive(4242)
            )

        job_kernel = mock.Mock()
        job_kernel.CreateJobObjectW = Function(large_handle)
        job_kernel.SetInformationJobObject = Function(True)
        job_kernel.AssignProcessToJobObject = Function(False)
        job_kernel.CloseHandle = Function(True)
        process = mock.Mock()
        process.pid = 4343
        process._handle = large_handle + 1
        process.wait.return_value = 0
        with mock.patch.object(
            dev_flow.os, "name", "nt"
        ), mock.patch.object(
            ctypes,
            "WinDLL",
            return_value=job_kernel,
            create=True,
        ), mock.patch.object(
            ctypes, "get_last_error", return_value=5, create=True
        ):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._windows_kill_on_close_job(
                    process, ["fixture"]
                )
        self.assertEqual(
            captured.exception.code, "PROCESS_OWNERSHIP_FAILED"
        )
        self.assertIs(
            job_kernel.CreateJobObjectW.restype, wintypes.HANDLE
        )
        self.assertEqual(
            job_kernel.AssignProcessToJobObject.argtypes,
            [wintypes.HANDLE, wintypes.HANDLE],
        )
        assigned_process_handle = (
            job_kernel.AssignProcessToJobObject.calls[0][1]
        )
        self.assertEqual(
            assigned_process_handle.value, large_handle + 1
        )
        self.assertEqual(
            job_kernel.CloseHandle.calls, [(large_handle,)]
        )

    @unittest.skipUnless(
        os.name == "nt", "requires native Windows process handles"
    )
    def test_windows_exit_code_259_is_not_treated_as_active(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(259)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.communicate(timeout=20)
        self.assertEqual(process.returncode, 259)
        self.assertFalse(
            dev_flow._quarantined_process_alive(process.pid)
        )

    def test_lock_backends_fail_closed_on_acquire_release_and_absence(self) -> None:
        handle = mock.Mock()
        handle.fileno.return_value = 17
        lock_path = self.root / "portable.lock"

        posix_backend = mock.Mock()
        posix_backend.LOCK_EX = 1
        posix_backend.LOCK_NB = 2
        posix_backend.LOCK_UN = 4
        with mock.patch.object(
            dev_flow, "fcntl", posix_backend
        ), mock.patch.object(dev_flow, "msvcrt", None):
            dev_flow._acquire_exclusive(handle, lock_path)
            dev_flow._release_exclusive(handle, lock_path)
        self.assertEqual(posix_backend.lockf.call_count, 2)

        acquire_failure = mock.Mock()
        acquire_failure.LOCK_EX = 1
        acquire_failure.LOCK_NB = 2
        acquire_failure.LOCK_UN = 4
        acquire_failure.lockf.side_effect = OSError(
            errno.EIO, "injected acquire failure"
        )
        with mock.patch.object(
            dev_flow, "fcntl", acquire_failure
        ), mock.patch.object(dev_flow, "msvcrt", None):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._acquire_exclusive(handle, lock_path)
        self.assertEqual(captured.exception.code, "LOCK_ACQUIRE_FAILED")

        release_failure = mock.Mock()
        release_failure.LOCK_EX = 1
        release_failure.LOCK_NB = 2
        release_failure.LOCK_UN = 4
        release_failure.lockf.side_effect = [
            None,
            OSError(errno.EIO, "injected release failure"),
        ]
        with mock.patch.object(
            dev_flow, "fcntl", release_failure
        ), mock.patch.object(dev_flow, "msvcrt", None):
            dev_flow._acquire_exclusive(handle, lock_path)
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._release_exclusive(handle, lock_path)
        self.assertEqual(captured.exception.code, "LOCK_RELEASE_FAILED")

        windows_backend = mock.Mock()
        windows_backend.LK_NBLCK = 10
        windows_backend.LK_UNLCK = 11
        with mock.patch.object(
            dev_flow, "fcntl", None
        ), mock.patch.object(dev_flow, "msvcrt", windows_backend):
            dev_flow._acquire_exclusive(handle, lock_path)
            dev_flow._release_exclusive(handle, lock_path)
        windows_backend.locking.assert_has_calls(
            [
                mock.call(17, 10, 1),
                mock.call(17, 11, 1),
            ]
        )

        with mock.patch.object(
            dev_flow, "fcntl", None
        ), mock.patch.object(dev_flow, "msvcrt", None):
            with self.assertRaises(dev_flow.FlowError) as captured:
                dev_flow._acquire_exclusive(handle, lock_path)
        self.assertEqual(captured.exception.code, "LOCK_UNSUPPORTED")

    def test_native_lock_contention_revision_race_and_process_death(self) -> None:
        lock_directory = self.root / "锁 directory with spaces"
        ready = self.root / "holder ready"
        release = self.root / "holder release"
        holder = subprocess.Popen(
            [
                sys.executable,
                str(SUPPORT),
                "hold-lock",
                str(SCRIPT),
                str(lock_directory),
                str(ready),
                str(release),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.wait_for_path(ready, holder)
        with mock.patch.object(
            dev_flow, "LOCK_TIMEOUT_SECONDS", 0.05
        ), mock.patch.object(dev_flow, "LOCK_POLL_SECONDS", 0.005):
            with self.assertRaises(dev_flow.FlowError) as captured:
                with dev_flow._file_lock(
                    lock_directory, "native.lock"
                ):
                    self.fail("contended lock was acquired")
        self.assertEqual(captured.exception.code, "LOCK_TIMEOUT")
        release.write_text("release\n", encoding="utf-8")
        stdout, stderr = holder.communicate(timeout=10)
        self.assertEqual((holder.returncode, stdout, stderr), (0, b"", b""))
        with dev_flow._file_lock(lock_directory, "native.lock"):
            pass

        ready.unlink()
        release.unlink()
        holder = subprocess.Popen(
            [
                sys.executable,
                str(SUPPORT),
                "hold-lock",
                str(SCRIPT),
                str(lock_directory),
                str(ready),
                str(release),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.wait_for_path(ready, holder)
        holder.kill()
        holder.communicate(timeout=10)
        self.assertNotEqual(holder.returncode, 0)
        with dev_flow._file_lock(lock_directory, "native.lock"):
            pass

        repo, _ = self.make_repo("revision race")
        task = self.start(repo, task_id="revision-race")["task"]
        cancellation = [
            "cancel",
            task["task_id"],
            "--expected-revision",
            str(task["revision"]),
            "--reason",
            "concurrent cancellation",
        ]
        first = self.controller_process(*cancellation)
        second = self.controller_process(*cancellation)
        results = [
            self.process_response(first),
            self.process_response(second),
        ]
        self.assertEqual(
            sorted(code for code, _ in results), [0, 3]
        )
        self.assertEqual(
            [
                response["error"]["code"]
                for code, response in results
                if code == 3
            ],
            ["REVISION_CONFLICT"],
        )
        self.assertEqual(
            dev_flow.load_state("revision-race", self.data)["revision"],
            task["revision"] + 1,
        )

    def test_protocol_child_bytes_and_spawn_exit_diagnostics(self) -> None:
        unicode_argument = str(
            self.root / "子 process argument with spaces"
        )
        with mock.patch.dict(
            os.environ, {"DEV_FLOW_CHILD_VALUE": "环境 value"}
        ):
            echoed = dev_flow._run(
                [
                    sys.executable,
                    str(SUPPORT),
                    "echo",
                    "--environment",
                    "DEV_FLOW_CHILD_VALUE",
                    unicode_argument,
                ],
                text=False,
            )
        self.assertEqual(
            echoed.stdout,
            f"{unicode_argument}\0环境 value".encode("utf-8"),
        )

        invalid = dev_flow._run(
            [
                sys.executable,
                str(SUPPORT),
                "emit",
                "--stdout-hex",
                "ff0d0a",
                "--stderr-hex",
                "fe",
            ]
        )
        self.assertEqual(invalid.stdout, "\\xff\r\n")
        self.assertEqual(invalid.stderr, "\\xfe")

        missing = self.root / "missing executable"
        with self.assertRaises(dev_flow.FlowError) as spawn_error:
            dev_flow._run([str(missing)])
        self.assertEqual(
            spawn_error.exception.details["failure_kind"], "spawn"
        )

        with self.assertRaises(dev_flow.FlowError) as exit_error:
            dev_flow._run(
                [
                    sys.executable,
                    str(SUPPORT),
                    "emit",
                    "--stderr-hex",
                    "ff0d0a",
                    "--exit-code",
                    "7",
                ]
            )
        self.assertEqual(
            exit_error.exception.details["failure_kind"], "exit"
        )
        self.assertEqual(exit_error.exception.details["returncode"], 7)
        self.assertEqual(
            exit_error.exception.details["stderr_sha256"],
            dev_flow._sha256_bytes(b"\xff\r\n"),
        )

        class BinaryStdout:
            def __init__(self) -> None:
                self.buffer = io.BytesIO()

            def write(self, value: str) -> int:
                raise AssertionError("binary protocol output was expected")

            def flush(self) -> None:
                pass

        output = BinaryStdout()
        with mock.patch.object(dev_flow.sys, "stdout", output):
            dev_flow._write_protocol_response({"路径": "值"})
        payload = output.buffer.getvalue()
        self.assertEqual(payload.count(b"\n"), 1)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertNotIn(b"\r\n", payload)
        self.assertEqual(
            json.loads(payload.decode("utf-8")), {"路径": "值"}
        )

    def test_interrupted_children_are_quiesced_or_durably_quarantined(self) -> None:
        repo, _ = self.make_repo("quarantine source")
        task = self.start(repo, task_id="quarantine-task")["task"]
        task_dir = self.data / "tasks" / task["task_id"]

        class InterruptedProcess:
            pid = 987654321
            returncode = None

            def __init__(self, *, quiescent: bool) -> None:
                self.quiescent = quiescent
                self.wait_calls = 0

            def communicate(self):
                raise KeyboardInterrupt()

            def poll(self):
                return None

            def terminate(self):
                pass

            def kill(self):
                pass

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.quiescent:
                    self.returncode = -1
                    return self.returncode
                raise subprocess.TimeoutExpired("fixture", timeout)

        quiescent = InterruptedProcess(quiescent=True)
        with dev_flow._task_lock(task_dir):
            with contextlib.ExitStack() as patches:
                patches.enter_context(
                    mock.patch.object(
                        dev_flow.subprocess,
                        "Popen",
                        return_value=quiescent,
                    )
                )
                if os.name == "nt":
                    fake_job = object()
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow,
                            "_windows_kill_on_close_job",
                            return_value=fake_job,
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_terminate_windows_job"
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_quiesce_windows_job"
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow,
                            "_windows_job_active_processes",
                            return_value=0,
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_close_windows_job"
                        )
                    )
                else:
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow.os,
                            "killpg",
                            return_value=None,
                            create=True,
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow,
                            "_posix_process_group_alive",
                            return_value=False,
                        )
                    )
                with self.assertRaises(KeyboardInterrupt):
                    dev_flow._run(
                        [sys.executable, str(SUPPORT), "emit"]
                    )
        self.assertFalse(dev_flow._quarantine_path(task_dir).exists())

        stuck = InterruptedProcess(quiescent=False)
        with dev_flow._task_lock(task_dir):
            with contextlib.ExitStack() as patches:
                patches.enter_context(
                    mock.patch.object(
                        dev_flow.subprocess,
                        "Popen",
                        return_value=stuck,
                    )
                )
                if os.name == "nt":
                    fake_job = object()
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow,
                            "_windows_kill_on_close_job",
                            return_value=fake_job,
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_terminate_windows_job"
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_quiesce_windows_job"
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow,
                            "_windows_job_active_processes",
                            return_value=1,
                        )
                    )
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow, "_close_windows_job"
                        )
                    )
                else:
                    patches.enter_context(
                        mock.patch.object(
                            dev_flow.os,
                            "killpg",
                            side_effect=OSError(
                                errno.EPERM, "injected"
                            ),
                            create=True,
                        )
                    )
                with self.assertRaises(
                    dev_flow.FlowError
                ) as captured:
                    dev_flow._run(
                        [sys.executable, str(SUPPORT), "emit"]
                    )
        self.assertEqual(
            captured.exception.code, "MUTATION_QUARANTINED"
        )
        quarantine_path = dev_flow._quarantine_path(task_dir)
        quarantine = json.loads(
            quarantine_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            quarantine["evidence_contract_version"],
            dev_flow.EVIDENCE_CONTRACT_VERSION,
        )
        self.assertEqual(quarantine["state_revision"], task["revision"])

        blocked = self.mutate(
            "cancel",
            task,
            "--reason",
            "must remain blocked",
            expected_code=2,
        )
        self.assertEqual(
            blocked["error"]["code"], "MUTATION_QUARANTINED"
        )
        with mock.patch.object(
            dev_flow, "_quarantine_processes_alive", return_value=True
        ):
            active = self.mutate(
                "recover-quarantine",
                task,
                expected_code=2,
            )
        self.assertEqual(
            active["error"]["code"], "QUARANTINE_CHILD_ACTIVE"
        )

        with mock.patch.object(
            dev_flow, "_quarantine_processes_alive", return_value=False
        ):
            recovered = self.mutate(
                "recover-quarantine",
                task,
            )
        self.assertTrue(recovered["recovered"])
        self.assertFalse(quarantine_path.exists())
        state = dev_flow.load_state(task["task_id"], self.data)
        self.assertEqual(state["revision"], task["revision"] + 1)
        self.assertEqual(len(state["mutation_recoveries"]), 1)
        self.assertTrue(
            list(
                task_dir.glob(
                    "mutation-quarantine.recovered-*.json"
                )
            )
        )



if __name__ == "__main__":
    unittest.main()
