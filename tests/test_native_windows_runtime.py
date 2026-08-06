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
    windows_comparison_key,
    windows_path_contains,
)
from dev_flow_orchestrator._platform.process import (
    ProcessFailure,
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
    PRODUCT_VERSION,
    WORKFLOW_IDS,
    WORKSPACE_SNAPSHOT_SCHEMA,
)
from support import make_repository


def _hold_lock(path: str, ready: multiprocessing.Event, seconds: float) -> None:
    with exclusive_file_lock(Path(path)):
        ready.set()
        time.sleep(seconds)


class NativeWindowsRuntimeTests(unittest.TestCase):
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
        result = run_bounded_process(
            [sys.executable, "-c", script, "a value", "x&y"],
            dict(os.environ), 5.0, 1024,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"a value")
        self.assertEqual(result.stderr, b"x&y")

    def test_process_runner_reports_combined_overflow(self) -> None:
        script = "import sys; sys.stdout.buffer.write(b'a'*80); sys.stderr.buffer.write(b'b'*80)"
        with self.assertRaises(ProcessFailure) as context:
            run_bounded_process(
                [sys.executable, "-c", script], dict(os.environ), 5.0, 100,
            )
        self.assertEqual(context.exception.kind, "output-too-large")
        self.assertGreater(
            context.exception.details["stdout_bytes"]
            + context.exception.details["stderr_bytes"],
            100,
        )

    def test_process_runner_failure_categories_and_nonzero_result(self) -> None:
        nonzero = run_bounded_process(
            [sys.executable, "-c", "import sys; sys.stderr.write('no'); sys.exit(7)"],
            dict(os.environ), 5.0, 1024,
        )
        self.assertEqual(nonzero.returncode, 7)
        self.assertEqual(nonzero.stderr, b"no")

        with self.assertRaises(ProcessFailure) as missing:
            run_bounded_process(
                [str(Path(tempfile.gettempdir()) / "missing-dev-flow-executable")],
                dict(os.environ), 1.0, 1024,
            )
        self.assertEqual(missing.exception.kind, "unavailable")

        sleeper = "import time; time.sleep(10)"
        with self.assertRaises(ProcessFailure) as timeout:
            run_bounded_process(
                [sys.executable, "-c", sleeper], dict(os.environ), 0.05, 1024,
            )
        self.assertEqual(timeout.exception.kind, "timeout")

        cancelled = threading.Event()
        timer = threading.Timer(0.05, cancelled.set)
        timer.start()
        try:
            with self.assertRaises(ProcessFailure) as cancellation:
                run_bounded_process(
                    [sys.executable, "-c", sleeper], dict(os.environ), 5.0, 1024,
                    cancelled,
                )
        finally:
            timer.cancel()
            timer.join(timeout=1)
        self.assertEqual(cancellation.exception.kind, "cancelled")

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
        self.assertEqual(PRODUCT_VERSION, "0.3.0")
        self.assertEqual(PLUGIN_DATA_NAMESPACE, "0.3.0")
        self.assertEqual(WORKSPACE_SNAPSHOT_SCHEMA, "dev-flow-workspace-snapshot/0.3.0")
        self.assertEqual(
            WORKFLOW_IDS,
            ("bugfix", "feature", "full", "investigation", "lite", "refactor"),
        )

    @unittest.skipUnless(os.name == "nt", "native Windows snapshot coverage")
    def test_windows_snapshot_covers_common_worktree_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_repository(root, "space Unicode-仓库")
            (repository / "deleted.txt").write_text("delete me\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repository), "add", "deleted.txt"], check=True
            )
            subprocess.run(
                ["git", "-C", str(repository), "commit", "-qm", "add deletion target"],
                check=True,
            )
            clean = GitClient.snapshot(str(repository))
            self.assertTrue(clean["clean"])
            (repository / "a.txt").write_text("unstaged\n", encoding="utf-8")
            (repository / "staged.txt").write_text("staged\n", encoding="utf-8")
            (repository / "untracked 文件.txt").write_text("new\n", encoding="utf-8")
            (repository / "deleted.txt").unlink()
            subprocess.run(
                ["git", "-C", str(repository), "add", "staged.txt"], check=True
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
                ["git", "-C", str(repository), "checkout", "--detach", "-q"], check=True
            )
            self.assertIsNone(GitClient.snapshot(str(repository))["branch"])

            linked = root / "linked worktree-二"
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "add", "-q", str(linked), "HEAD"],
                check=True,
            )
            linked_snapshot = GitClient.snapshot(str(linked))
            self.assertEqual(linked_snapshot["repository_root"], str(linked).lower())
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
