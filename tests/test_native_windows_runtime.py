"""Focused host-runtime tests for the native Windows OpenSpec slice."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator._platform.paths import (
    _reject_windows_namespace,
    canonical_repository_root,
    windows_comparison_key,
    windows_path_contains,
)
from dev_flow_orchestrator._platform.process import (
    ProcessFailure,
    _run_windows,
    run_bounded_process,
)
from dev_flow_orchestrator._platform.storage import (
    atomic_write_bytes,
    exclusive_file_lock,
)
from dev_flow_orchestrator.git_client import GitClient
from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import (
    PLUGIN_DATA_NAMESPACE,
    MODEL_VERSION,
    WORKFLOW_IDS,
    WORKSPACE_SNAPSHOT_SCHEMA,
)
from support import hermetic_subprocess_env, make_repository


def _hold_lock(path: str, ready: multiprocessing.Event, seconds: float) -> None:
    with exclusive_file_lock(Path(path)):
        ready.set()
        time.sleep(seconds)


def _windows_process_is_running(pid: int) -> bool:
    import ctypes

    process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(
            process, ctypes.byref(exit_code)
        ):
            return False
        return exit_code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(process)


class NativeWindowsRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires native Windows paths")
    def test_canonical_repository_root_preserves_host_spelling(self) -> None:
        with tempfile.TemporaryDirectory(prefix="Dev Flow Mixed Case ") as temporary:
            expected = Path(temporary).resolve()
            self.assertEqual(canonical_repository_root(expected), expected)

    def test_core_modules_import_without_eager_posix_host_use(self) -> None:
        from dev_flow_orchestrator import cli, controller, git_client, store

        self.assertTrue(all((cli, controller, git_client, store)))
        if os.name == "nt":
            self.assertNotIn("fcntl", sys.modules)

    def test_windows_path_aliases_and_drive_containment(self) -> None:
        canonical = windows_comparison_key(r"C:/Work/space/../Repo/")
        self.assertEqual(canonical, windows_comparison_key(r"c:\work\repo"))
        self.assertTrue(windows_path_contains(r"C:\Work\Repo", r"c:/work/repo/sub/file"))
        self.assertFalse(windows_path_contains(r"C:\Work\Repo", r"D:\Work\Repo"))
        for unsupported in (r"\\server\share", r"\\wsl$\Ubuntu", r"\\?\C:\repo"):
            with self.subTest(path=unsupported), self.assertRaises(ValueError):
                _reject_windows_namespace(unsupported)

    def test_process_runner_preserves_argument_and_stream_boundaries(self) -> None:
        script = (
            "import sys; "
            "sys.stdout.buffer.write(sys.argv[1].encode()); "
            "sys.stderr.buffer.write(sys.argv[2].encode())"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = run_bounded_process(
                [sys.executable, "-c", script, "a value", "x&y"],
                hermetic_subprocess_env(Path(directory)),
                5.0,
                1024,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"a value")
        self.assertEqual(result.stderr, b"x&y")

    def test_process_runner_reports_combined_overflow(self) -> None:
        script = "import sys; sys.stdout.buffer.write(b'a'*80); sys.stderr.buffer.write(b'b'*80)"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProcessFailure) as context:
                run_bounded_process(
                    [sys.executable, "-c", script],
                    hermetic_subprocess_env(Path(directory)),
                    5.0,
                    100,
                )
        self.assertEqual(context.exception.kind, "output-too-large")
        self.assertGreater(
            context.exception.details["stdout_bytes"]
            + context.exception.details["stderr_bytes"],
            100,
        )

    def test_process_runner_failure_categories_and_nonzero_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = hermetic_subprocess_env(root)
            nonzero = run_bounded_process(
                [sys.executable, "-c", "import sys; sys.stderr.write('no'); sys.exit(7)"],
                environment,
                5.0,
                1024,
            )
            self.assertEqual(nonzero.returncode, 7)
            self.assertEqual(nonzero.stderr, b"no")

            with self.assertRaises(ProcessFailure) as missing:
                run_bounded_process(
                    [str(root / "missing-dev-flow-executable")],
                    environment,
                    1.0,
                    1024,
                )
            self.assertEqual(missing.exception.kind, "unavailable")

            sleeper = "import time; time.sleep(10)"
            with self.assertRaises(ProcessFailure) as timeout:
                run_bounded_process(
                    [sys.executable, "-c", sleeper], environment, 0.05, 1024,
                )
            self.assertEqual(timeout.exception.kind, "timeout")

            cancelled = threading.Event()
            timer = threading.Timer(0.05, cancelled.set)
            timer.start()
            try:
                with self.assertRaises(ProcessFailure) as cancellation:
                    run_bounded_process(
                        [sys.executable, "-c", sleeper],
                        environment,
                        5.0,
                        1024,
                        cancelled,
                    )
            finally:
                timer.cancel()
                timer.join(timeout=1)
            self.assertEqual(cancellation.exception.kind, "cancelled")

    def test_windows_runner_times_out_after_parent_exits_with_inherited_pipes(self) -> None:
        parent = (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', sys.argv[1]])"
        )
        descendant = "import time; time.sleep(1)"
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            environment = hermetic_subprocess_env(Path(directory))
            with mock.patch(
                "dev_flow_orchestrator._platform.process.TERMINATE_GRACE_SECONDS", 0.02
            ):
                with self.assertRaises(ProcessFailure) as context:
                    _run_windows(
                        [sys.executable, "-c", parent, descendant],
                        environment,
                        0.05,
                        1024,
                        None,
                    )
        self.assertEqual(context.exception.kind, "timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    @unittest.skipUnless(os.name == "nt", "requires Windows pipe handles")
    def test_windows_runner_closes_pipes_after_timeout(self) -> None:
        processes = []
        original_popen = subprocess.Popen

        def tracked_popen(*args: object, **kwargs: object) -> subprocess.Popen:
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            environment = hermetic_subprocess_env(Path(directory))
            with mock.patch(
                "dev_flow_orchestrator._platform.process.subprocess.Popen",
                side_effect=tracked_popen,
            ):
                with self.assertRaises(ProcessFailure) as context:
                    _run_windows(
                        [sys.executable, "-c", "import time; time.sleep(10)"],
                        environment,
                        0.05,
                        1024,
                        None,
                    )

        self.assertEqual(context.exception.kind, "timeout")
        command_processes = [process for process in processes if process.stdout is not None]
        self.assertEqual(len(command_processes), 1)
        self.assertTrue(command_processes[0].stdout.closed)
        self.assertTrue(command_processes[0].stderr.closed)

    @unittest.skipUnless(os.name == "nt", "requires Windows taskkill")
    def test_windows_runner_timeout_terminates_live_parent_and_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_path = root / "processes.txt"
            environment = hermetic_subprocess_env(root)
            parent = (
                "import os, pathlib, subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', sys.argv[2]]); "
                "pathlib.Path(sys.argv[1]).write_text("
                "f'{os.getpid()} {child.pid}', encoding='ascii'); "
                "time.sleep(30)"
            )
            descendant = "import time; time.sleep(30)"
            observed_running = threading.Event()
            observed_pids: list[int] = []

            def observe_processes() -> None:
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    try:
                        pids = [int(value) for value in pid_path.read_text().split()]
                    except (FileNotFoundError, ValueError):
                        time.sleep(0.01)
                        continue
                    if len(pids) == 2 and all(
                        _windows_process_is_running(pid) for pid in pids
                    ):
                        observed_pids.extend(pids)
                        observed_running.set()
                        return
                    time.sleep(0.01)

            observer = threading.Thread(target=observe_processes, daemon=True)
            observer.start()
            try:
                with self.assertRaises(ProcessFailure) as context:
                    _run_windows(
                        [
                            sys.executable,
                            "-c",
                            parent,
                            str(pid_path),
                            descendant,
                        ],
                        environment,
                        2.0,
                        1024,
                        None,
                    )
            finally:
                observer.join(timeout=2)

            self.assertEqual(context.exception.kind, "timeout")
            self.assertTrue(
                observed_running.is_set(),
                "parent and descendant were not both observed alive before timeout",
            )
            self.assertEqual(len(observed_pids), 2)
            cleanup_deadline = time.monotonic() + 2
            while time.monotonic() < cleanup_deadline and any(
                _windows_process_is_running(pid) for pid in observed_pids
            ):
                time.sleep(0.01)
            self.assertFalse(
                any(_windows_process_is_running(pid) for pid in observed_pids),
                "taskkill did not terminate both the parent and descendant",
            )

    def test_windows_snapshot_total_budget_is_consumed_per_chunk(self) -> None:
        class CountingReader:
            def __init__(self, stream: object) -> None:
                self.stream = stream
                self.bytes_read = 0

            def __enter__(self) -> "CountingReader":
                return self

            def __exit__(self, *args: object) -> None:
                self.stream.close()

            def fileno(self) -> int:
                return self.stream.fileno()

            def read(self, size: int) -> bytes:
                chunk = self.stream.read(size)
                self.bytes_read += len(chunk)
                return chunk

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_bytes(b"1234")
            second.write_bytes(b"abcdefghijkl")
            total = [0]
            deadline = time.monotonic() + 5
            with mock.patch(
                "dev_flow_orchestrator.git_client.MAX_SNAPSHOT_CONTENT_BYTES", 8
            ), mock.patch(
                "dev_flow_orchestrator.git_client.SNAPSHOT_READ_CHUNK_BYTES", 4
            ):
                GitClient._read_path_windows(
                    root, "first.txt", {}, {}, deadline, total, "sha1"
                )
                original_open = Path.open
                reader = None

                def tracked_open(path: Path, *args: object, **kwargs: object) -> CountingReader:
                    nonlocal reader
                    reader = CountingReader(original_open(path, *args, **kwargs))
                    return reader

                with mock.patch.object(Path, "open", autospec=True, side_effect=tracked_open):
                    with self.assertRaises(DevFlowError) as context:
                        GitClient._read_path_windows(
                            root, "second.txt", {}, {}, deadline, total, "sha1"
                        )
            self.assertEqual(context.exception.code, "SNAPSHOT_BUDGET_EXCEEDED")
            self.assertEqual(context.exception.details["path"], "second.txt")
            self.assertIsNotNone(reader)
            self.assertEqual(reader.bytes_read, 8)

    @unittest.skipUnless(os.name == "nt", "native Windows EOL coverage")
    def test_windows_snapshot_ignores_only_text_eol_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_repository(root, "eol repository")
            environment = hermetic_subprocess_env(root)
            (repository / ".gitattributes").write_bytes(b"*.txt text\n*.bin -text\n")
            (repository / "text.txt").write_bytes(b"first\r\nsecond\r\n")
            (repository / "binary.bin").write_bytes(b"\x00first\r\nsecond\r\n")
            subprocess.run(
                ["git", "-C", str(repository), "add", ".gitattributes", "text.txt", "binary.bin"],
                env=environment,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-qm", "add EOL fixtures"],
                env=environment,
                check=True,
            )

            clean = GitClient.snapshot(str(repository))
            self.assertTrue(clean["clean"])
            self.assertEqual(clean["entries"], [])

            (repository / "text.txt").write_bytes(b"first\r\nchanged\r\n")
            (repository / "binary.bin").write_bytes(b"\x00first\nsecond\n")
            changed = GitClient.snapshot(str(repository))
            changed_paths = {entry["path"] for entry in changed["entries"]}
            self.assertIn("text.txt", changed_paths)
            self.assertIn("binary.bin", changed_paths)

    def test_cross_process_lock_serializes_and_atomic_failure_preserves_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for lock_name in ("membership.lock", "task-example.lock"):
                with self.subTest(lock_name=lock_name):
                    lock_path = root / lock_name
                    ready = multiprocessing.Event()
                    process = multiprocessing.Process(
                        target=_hold_lock, args=(str(lock_path), ready, 0.35)
                    )
                    process.start()
                    self.assertTrue(ready.wait(timeout=5))
                    started = time.monotonic()
                    with exclusive_file_lock(lock_path):
                        pass
                    process.join(timeout=5)
                    self.assertEqual(process.exitcode, 0)
                    self.assertGreaterEqual(time.monotonic() - started, 0.20)

            state_path = root / "state.json"
            atomic_write_bytes(state_path, b"old\n")
            with mock.patch(
                "dev_flow_orchestrator._platform.storage.os.replace",
                side_effect=OSError("injected replacement failure"),
            ):
                with self.assertRaises(DevFlowError) as context:
                    atomic_write_bytes(state_path, b"new\n")
            self.assertEqual(context.exception.code, "STATE_WRITE_FAILED")
            self.assertEqual(state_path.read_bytes(), b"old\n")

    def test_runtime_change_keeps_product_authority(self) -> None:
        self.assertEqual(MODEL_VERSION, "0.4.0")
        self.assertEqual(PLUGIN_DATA_NAMESPACE, "0.4.0")
        self.assertEqual(WORKSPACE_SNAPSHOT_SCHEMA, "dev-flow-workspace-snapshot/0.4.0")
        self.assertEqual(
            WORKFLOW_IDS,
            ("bugfix", "feature", "full", "investigation", "lite", "refactor"),
        )

    @unittest.skipUnless(os.name == "nt", "native Windows snapshot coverage")
    def test_windows_snapshot_covers_common_worktree_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_repository(root, "space Unicode-仓库")
            environment = hermetic_subprocess_env(root)
            (repository / "deleted.txt").write_text("delete me\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repository), "add", "deleted.txt"],
                env=environment,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-qm", "add deletion target"],
                env=environment,
                check=True,
            )
            clean = GitClient.snapshot(str(repository))
            self.assertTrue(clean["clean"])
            (repository / "a.txt").write_text("unstaged\n", encoding="utf-8")
            (repository / "staged.txt").write_text("staged\n", encoding="utf-8")
            (repository / "untracked 文件.txt").write_text("new\n", encoding="utf-8")
            (repository / "deleted.txt").unlink()
            subprocess.run(
                ["git", "-C", str(repository), "add", "staged.txt"],
                env=environment,
                check=True,
            )
            snapshot = GitClient.snapshot(
                str(repository),
                resources=({
                    "path": "untracked 文件.txt", "role": "governing",
                    "normalizer": "none",
                },),
            )
            kinds = {item["path"]: item["kind"] for item in snapshot["entries"]}
            self.assertEqual(kinds["a.txt"], "regular")
            self.assertEqual(kinds["staged.txt"], "regular")
            self.assertEqual(kinds["untracked 文件.txt"], "regular")
            self.assertEqual(kinds["deleted.txt"], "missing")
            self.assertEqual(snapshot["resources"][0]["path"], "untracked 文件.txt")

            subprocess.run(
                ["git", "-C", str(repository), "checkout", "--detach", "-q"],
                env=environment,
                check=True,
            )
            self.assertIsNone(GitClient.snapshot(str(repository))["branch"])

            linked = root / "linked worktree-二"
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-q", str(linked), "HEAD"],
                env=environment,
                check=True,
            )
            linked_snapshot = GitClient.snapshot(str(linked))
            self.assertEqual(linked_snapshot["repository_root"], str(linked.resolve()))
            self.assertNotEqual(
                linked_snapshot["git_worktree_dir"], linked_snapshot["git_common_dir"]
            )

    @unittest.skipUnless(os.name == "nt", "native Windows repository-set coverage")
    def test_windows_two_repository_order_and_admission_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = make_repository(root, "Zeta Repo")
            second = make_repository(root, "alpha 仓库")
            controller = Controller(str(root / "controller-data"))
            state = controller.start(
                requirement="Windows two-repository smoke",
                workflow="lite",
                repositories=(str(first), str(second)),
            )
            paths = tuple(item.path for item in state.repositories)
            self.assertEqual(paths, tuple(sorted(paths, key=lambda item: item.encode("utf-8"))))

            nested = first / "src" / "module"
            nested.mkdir(parents=True)
            alternate = str(nested).replace("\\", "/")
            if len(alternate) > 1 and alternate[1] == ":":
                alternate = alternate[0].swapcase() + alternate[1:]
            for spelling in (str(nested), alternate):
                with self.subTest(spelling=spelling):
                    matches = controller.tasks_for_path(spelling)
                    self.assertEqual(
                        tuple(item.task_id for item in matches), (state.task_id,)
                    )

            missing = root / "missing-repository"
            before = tuple(controller.list_tasks())
            with self.assertRaises(DevFlowError):
                controller.start(
                    requirement="must not partially admit",
                    workflow="lite",
                    repositories=(str(first), str(missing)),
                )
            self.assertEqual(tuple(controller.list_tasks()), before)


if __name__ == "__main__":
    unittest.main()
