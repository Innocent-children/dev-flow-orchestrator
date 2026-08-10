"""Real-process POSIX lock timeout, cancellation, and ordering regressions."""

from __future__ import annotations

from contextlib import ExitStack
import multiprocessing
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

if os.name != "nt":
    import fcntl

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator import store as store_module
from dev_flow_orchestrator._platform import storage as storage_module
from dev_flow_orchestrator._platform.storage import exclusive_file_lock
from dev_flow_orchestrator.mcp.application import MCPApplication
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import PLUGIN_DATA_NAMESPACE
from dev_flow_orchestrator.store import TaskStore
from support import RepositoryTestCase, make_repository


def _hold_raw_posix_lock(path_text, ready, release) -> None:
    path = Path(path_text)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        ready.set()
        release.wait(10.0)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _hold_raw_posix_lock_with_release_ack(path_text, ready, release, released) -> None:
    path = Path(path_text)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        ready.set()
        release.wait(10.0)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
        released.set()


def _operation_worker(operation, arguments, timeout_seconds, result, cancel) -> None:
    from dev_flow_orchestrator._platform import storage as storage_module
    from dev_flow_orchestrator import web as web_module

    storage_module.DEFAULT_POSIX_FILE_LOCK_TIMEOUT_SECONDS = timeout_seconds
    started = time.monotonic()
    try:
        controller = Controller(arguments["data_dir"])
        if operation == "apply":
            value = controller.apply(
                arguments["task_id"],
                arguments["action_id"],
                {},
                binding=arguments["binding"],
            )
            outcome = {
                "ok": True,
                "revision": value["receipt"]["committed_revision"],
            }
        elif operation == "start":
            state = controller.start(
                requirement="contended membership",
                workflow="lite",
                repositories=(arguments["repository"],),
                task_id=arguments["task_id"],
                cancellation_check=(
                    (lambda: cancel.is_set()) if cancel is not None else None
                ),
            )
            outcome = {"ok": True, "task_id": state.task_id}
        elif operation == "next":
            value = controller.next(arguments["task_id"])
            outcome = {"ok": True, "revision": value["task_revision"]}
        elif operation == "start-web":
            web_module._start_web(arguments["data_dir"], 0)
            outcome = {"ok": True}
        else:  # pragma: no cover - test helper invariant
            raise AssertionError("unknown operation")
    except DevFlowError as exc:
        outcome = {"ok": False, "code": exc.code, "details": exc.details}
    except BaseException as exc:  # keep a failed child observable and bounded
        outcome = {"ok": False, "type": type(exc).__name__, "message": str(exc)}
    outcome["elapsed"] = time.monotonic() - started
    result.put(outcome)


def _authority_worker(data_dir, task_id, reverse, hold_seconds, result) -> None:
    from dev_flow_orchestrator._platform.storage import exclusive_file_lock

    store = TaskStore(data_dir)
    state, _ = store.inspect_with_definition(task_id)
    repositories = tuple(reversed(state.repositories)) if reverse else state.repositories
    authorities = store._repository_authorities(repositories)
    try:
        with ExitStack() as locks:
            for authority in authorities:
                locks.enter_context(
                    exclusive_file_lock(authority.lock_path, timeout_seconds=2.0)
                )
            time.sleep(hold_seconds)
        result.put({"ok": True, "order": [item.lock_path.name for item in authorities]})
    except DevFlowError as exc:
        result.put({"ok": False, "code": exc.code})


@unittest.skipIf(os.name == "nt", "POSIX-only storage lock contract")
class PosixStorageLockingTests(RepositoryTestCase):
    PROCESS_TIMEOUT_SECONDS = 5.0

    def setUp(self) -> None:
        super().setUp()
        self.context = multiprocessing.get_context("spawn")
        self.processes = []

    def tearDown(self) -> None:
        for process in self.processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1.0)
        super().tearDown()

    def _lock_path(self, task_id: str) -> Path:
        return (
            Path(self.data_dir)
            / PLUGIN_DATA_NAMESPACE
            / "locks"
            / (task_id + ".lock")
        )

    def _holder(self, path: Path):
        ready = self.context.Event()
        release = self.context.Event()
        process = self.context.Process(
            target=_hold_raw_posix_lock,
            args=(str(path), ready, release),
        )
        process.start()
        self.processes.append(process)
        self.assertTrue(ready.wait(self.PROCESS_TIMEOUT_SECONDS), "holder did not acquire lock")
        return process, release

    def _holder_with_release_ack(self, path: Path):
        ready = self.context.Event()
        release = self.context.Event()
        released = self.context.Event()
        process = self.context.Process(
            target=_hold_raw_posix_lock_with_release_ack,
            args=(str(path), ready, release, released),
        )
        process.start()
        self.processes.append(process)
        self.assertTrue(ready.wait(self.PROCESS_TIMEOUT_SECONDS), "holder did not acquire lock")
        return process, release, released

    def _operation(self, operation: str, arguments: dict, *, timeout=0.25, cancel=None):
        result = self.context.Queue()
        process = self.context.Process(
            target=_operation_worker,
            args=(operation, arguments, timeout, result, cancel),
        )
        process.start()
        self.processes.append(process)
        process.join(self.PROCESS_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            self.fail("contending process did not exit within the join timeout")
        self.assertEqual(process.exitcode, 0)
        return result.get(timeout=1.0)

    @staticmethod
    def _release(process, release) -> None:
        release.set()
        process.join(2.0)
        if process.is_alive():
            process.terminate()
            process.join(1.0)

    def test_task_lock_timeout_is_precommit_and_release_allows_success(self) -> None:
        task_id = self.start_lite("bounded task lock")
        projection = self.controller.next(task_id)
        path = self.controller.store._state_path(task_id)
        before_bytes = path.read_bytes()
        before = self.controller.show(task_id)
        holder, release = self._holder(self._lock_path(task_id))

        outcome = self._operation("apply", {
            "data_dir": self.data_dir,
            "task_id": task_id,
            "action_id": projection["action"]["action_id"],
            "binding": projection["action"]["binding"],
        })

        self.assertEqual(outcome["code"], "STATE_LOCK_TIMEOUT")
        self.assertLess(outcome["elapsed"], 2.0)
        self.assertEqual(path.read_bytes(), before_bytes)
        self._release(holder, release)
        unchanged = self.controller.show(task_id)
        self.assertEqual(unchanged.revision, before.revision)
        self.assertEqual(unchanged.current_node, before.current_node)
        self.assertEqual(unchanged.records, before.records)
        committed = self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        self.assertEqual(
            committed["receipt"]["committed_revision"],
            before.revision + 1,
        )

    def test_membership_and_repository_locks_share_the_timeout(self) -> None:
        membership = Path(self.data_dir) / PLUGIN_DATA_NAMESPACE / "locks" / "membership.lock"
        holder, release = self._holder(membership)
        repository = make_repository(self.root, "membership-contender")
        contender = "task-membership-contender"
        outcome = self._operation("start", {
            "data_dir": self.data_dir,
            "repository": str(repository),
            "task_id": contender,
        })
        self.assertEqual(outcome["code"], "STATE_LOCK_TIMEOUT")
        self.assertFalse(self.controller.store._state_path(contender).exists())
        self._release(holder, release)
        self.assertEqual(
            self.controller.start(
                requirement="released membership",
                workflow="lite",
                repositories=(str(repository),),
                task_id=contender,
            ).task_id,
            contender,
        )

        state = self.controller.show(contender)
        authority = self.controller.store._repository_authorities(state.repositories)[0]
        holder, release = self._holder(authority.lock_path)
        outcome = self._operation("next", {
            "data_dir": self.data_dir,
            "task_id": contender,
        })
        self.assertEqual(outcome["code"], "STATE_LOCK_TIMEOUT")
        self._release(holder, release)
        self.assertEqual(
            self.controller.next(contender)["action"]["binding"]["task_revision"],
            0,
        )

    def test_cancellation_interrupts_admission_task_wait_without_state_write(self) -> None:
        existing = self.start_lite("retained task lock")
        holder, release = self._holder(self._lock_path(existing))
        repository = make_repository(self.root, "cancelled-contender")
        cancel = self.context.Event()
        result = self.context.Queue()
        arguments = {
            "data_dir": self.data_dir,
            "repository": str(repository),
            "task_id": "task-cancelled-contender",
        }
        process = self.context.Process(
            target=_operation_worker,
            args=("start", arguments, 5.0, result, cancel),
        )
        process.start()
        self.processes.append(process)
        time.sleep(0.2)
        signalled_at = time.monotonic()
        cancel.set()
        process.join(self.PROCESS_TIMEOUT_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            self.fail("cancelled lock waiter did not exit")
        outcome = result.get(timeout=1.0)
        self.assertEqual(outcome["code"], "REQUEST_CANCELLED")
        self.assertLess(time.monotonic() - signalled_at, 1.0)
        self.assertFalse(self.controller.store._state_path(arguments["task_id"]).exists())
        self._release(holder, release)

    def test_post_acquire_cancellation_releases_lock_without_entering(self) -> None:
        path = self._lock_path("task-post-acquire-cancel")
        holder, release, released = self._holder_with_release_ack(path)
        sentinel = self.root / "post-acquire-cancel-entered"
        checks = 0

        def cancellation_check() -> bool:
            nonlocal checks
            checks += 1
            if checks == 2:
                release.set()
                self.assertTrue(
                    released.wait(self.PROCESS_TIMEOUT_SECONDS),
                    "holder did not release for the successful contender attempt",
                )
            return checks >= 4

        with self.assertRaises(DevFlowError) as caught:
            with exclusive_file_lock(
                path,
                timeout_seconds=2.0,
                cancellation_check=cancellation_check,
            ):
                sentinel.write_text("entered", encoding="utf-8")

        self.assertEqual(caught.exception.code, "REQUEST_CANCELLED")
        self.assertFalse(sentinel.exists())
        holder.join(2.0)
        self.assertFalse(holder.is_alive())
        with exclusive_file_lock(path, timeout_seconds=1.0):
            pass

    def test_post_acquire_deadline_releases_lock_without_entering(self) -> None:
        path = self._lock_path("task-post-acquire-timeout")
        holder, release, released = self._holder_with_release_ack(path)
        sentinel = self.root / "post-acquire-timeout-entered"
        monotonic_values = iter((100.0, 100.95, 101.01))

        def release_during_poll(_seconds: float) -> None:
            release.set()
            self.assertTrue(
                released.wait(self.PROCESS_TIMEOUT_SECONDS),
                "holder did not release after the last pre-deadline check",
            )

        with mock.patch.object(
            storage_module.time,
            "monotonic",
            side_effect=lambda: next(monotonic_values),
        ), mock.patch.object(
            storage_module.time,
            "sleep",
            side_effect=release_during_poll,
        ):
            with self.assertRaises(DevFlowError) as caught:
                with exclusive_file_lock(path, timeout_seconds=1.0):
                    sentinel.write_text("entered", encoding="utf-8")

        self.assertEqual(caught.exception.code, "STATE_LOCK_TIMEOUT")
        self.assertFalse(sentinel.exists())
        holder.join(2.0)
        self.assertFalse(holder.is_alive())
        with exclusive_file_lock(path, timeout_seconds=1.0):
            pass

    def test_post_acquire_rejection_is_precommit_for_real_mcp_mutation(self) -> None:
        task_id = self.start_lite("Post-acquire cancellation is precommit")
        projection = self.controller.next(task_id)
        state_path = self.controller.store._state_path(task_id)
        before_bytes = state_path.read_bytes()
        before = self.controller.show(task_id)
        task_lock = self._lock_path(task_id)
        holder, release, released = self._holder_with_release_ack(task_lock)
        real_lock = store_module.exclusive_file_lock
        checks = 0

        def target_cancellation_check() -> bool:
            nonlocal checks
            checks += 1
            if checks == 2:
                release.set()
                self.assertTrue(
                    released.wait(self.PROCESS_TIMEOUT_SECONDS),
                    "holder did not release before the successful task-lock attempt",
                )
            return checks >= 4

        def routed_lock(path, *args, **kwargs):
            if Path(path).name == task_lock.name:
                return real_lock(
                    path,
                    timeout_seconds=2.0,
                    cancellation_check=target_cancellation_check,
                )
            return real_lock(path, *args, **kwargs)

        application = MCPApplication(self.data_dir)
        with mock.patch.object(
            store_module,
            "exclusive_file_lock",
            side_effect=routed_lock,
        ):
            rejected = application.call(
                "dev_flow_apply_action",
                {
                    "task_id": task_id,
                    "action_id": projection["action"]["action_id"],
                    "payload": {},
                    "binding": projection["action"]["binding"],
                },
                cancellation_check=lambda: False,
            )

        self.assertTrue(rejected.is_error)
        self.assertEqual(
            rejected.structured_content["error"]["code"],
            "REQUEST_CANCELLED",
        )
        self.assertNotEqual(
            rejected.structured_content["error"]["code"],
            "MCP_COMPLETION_UNCERTAIN",
        )
        self.assertIsNone(rejected.structured_content["result"])
        self.assertEqual(state_path.read_bytes(), before_bytes)
        after = self.controller.show(task_id)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.current_node, before.current_node)
        self.assertEqual(after.status, before.status)
        self.assertEqual(after.records, before.records)
        holder.join(2.0)
        self.assertFalse(holder.is_alive())

        committed = self.controller.apply(
            task_id,
            projection["action"]["action_id"],
            {},
            binding=projection["action"]["binding"],
        )
        self.assertEqual(
            committed["receipt"]["committed_revision"],
            before.revision + 1,
        )

    def test_opposite_repository_input_order_does_not_deadlock(self) -> None:
        second = make_repository(self.root, "second-authority")
        task_id = self.controller.start(
            requirement="canonical authority order",
            workflow="lite",
            repositories=(str(self.repository), str(second)),
        ).task_id
        results = self.context.Queue()
        first = self.context.Process(
            target=_authority_worker,
            args=(self.data_dir, task_id, False, 0.3, results),
        )
        second_process = self.context.Process(
            target=_authority_worker,
            args=(self.data_dir, task_id, True, 0.0, results),
        )
        first.start()
        second_process.start()
        self.processes.extend((first, second_process))
        first.join(self.PROCESS_TIMEOUT_SECONDS)
        second_process.join(self.PROCESS_TIMEOUT_SECONDS)
        self.assertFalse(first.is_alive())
        self.assertFalse(second_process.is_alive())
        outcomes = [results.get(timeout=1.0), results.get(timeout=1.0)]
        self.assertTrue(all(item["ok"] for item in outcomes), outcomes)
        self.assertEqual(outcomes[0]["order"], outcomes[1]["order"])

    def test_web_control_lock_inherits_bounded_shared_primitive(self) -> None:
        runtime_root = Path(self.data_dir).resolve() / "web-runtime"
        lock_path = runtime_root / "control.lock"
        holder, release = self._holder(lock_path)
        outcome = self._operation("start-web", {"data_dir": self.data_dir})
        self.assertEqual(outcome["code"], "STATE_LOCK_TIMEOUT")
        self.assertFalse((runtime_root / "state.json").exists())
        self._release(holder, release)


if __name__ == "__main__":
    unittest.main()
