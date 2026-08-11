"""Managed POSIX Web lifecycle regressions for exact-instance authority."""

from __future__ import annotations

import json
import http.client
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator import web as web_module
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.product import PRODUCT_IDENTITY
from support import hermetic_subprocess_env


class _MetadataHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        self.server.request_count += 1
        expected = getattr(self.server, "expected_token")
        if self.headers.get("Authorization") != "Bearer " + expected:
            payload = b"{}"
            self.send_response(HTTPStatus.UNAUTHORIZED)
        else:
            payload = json.dumps(
                getattr(self.server, "metadata"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(getattr(self.server, "response_status"))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


class _UnreapableProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None

    def terminate(self) -> None:
        return

    def kill(self) -> None:
        return

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("unreapable", timeout)


@unittest.skipIf(os.name == "nt", "POSIX managed Web lifecycle contract")
class ManagedWebLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.children: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for process in self.children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        self.temporary.cleanup()

    def test_child_command_preserves_dash_prefixed_instance_id(self) -> None:
        command = web_module._child_command(self.data_dir, 0, "-dash-prefixed")

        self.assertIn("--instance-id=-dash-prefixed", command)
        self.assertNotIn("--instance-id", command)

    def _spawn_sleeper(self) -> subprocess.Popen:
        environment = hermetic_subprocess_env(self.root)
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            env=environment,
        )
        self.children.append(process)
        return process

    @staticmethod
    def _unused_port() -> int:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((web_module.SERVER_HOST, 0))
            return int(probe.getsockname()[1])
        finally:
            probe.close()

    def _running_state(self, process: subprocess.Popen) -> tuple[Path, dict]:
        root, state_path, _lock_path, _log_path = web_module._runtime_paths(
            self.data_dir
        )
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        port = self._unused_port()
        token = "retained-authority-" + "a" * 32
        state = {
            "schema": web_module.WEB_RUNTIME_SCHEMA,
            "instance_id": "retained-instance-" + "b" * 24,
            "pid": process.pid,
            "status": "running",
            "started_at": "2026-08-11T00:00:00Z",
            "host": web_module.SERVER_HOST,
            "port": port,
            "url": "http://{}:{}/#token={}".format(
                web_module.SERVER_HOST,
                port,
                token,
            ),
            "token": token,
        }
        web_module._write_runtime_state(state_path, state)
        return state_path, state

    def _cli_command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "dev_flow_orchestrator.cli",
            "--data-dir",
            self.data_dir,
            "web",
        ]

    def _invoke_cli(self, action: str, *, timeout: float = 15.0) -> tuple[int, dict]:
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        completed = subprocess.run(
            self._cli_command() + [action],
            cwd=str(SRC.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout)

    def _metadata_server(
        self,
        *,
        expected_token: str,
        metadata: dict,
        status: int = HTTPStatus.OK,
    ) -> tuple[HTTPServer, threading.Thread]:
        server = HTTPServer((web_module.SERVER_HOST, 0), _MetadataHandler)
        server.expected_token = expected_token
        server.metadata = metadata
        server.response_status = status
        server.request_count = 0
        worker = threading.Thread(target=server.serve_forever)
        worker.start()

        def cleanup() -> None:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2.0)

        self.addCleanup(cleanup)
        return server, worker

    def _exact_managed_state(self) -> tuple[subprocess.Popen, Path, dict]:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        server, _worker = self._metadata_server(
            expected_token=state["token"],
            metadata={
                "product_identity": PRODUCT_IDENTITY,
                "managed_runtime": {
                    "managed": True,
                    "instance_id": state["instance_id"],
                    "pid": state["pid"],
                },
            },
        )
        state["port"] = server.server_port
        state["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            server.server_port,
            state["token"],
        )
        web_module._write_runtime_state(state_path, state)
        return process, state_path, state

    def _dead_state_on_server(
        self,
        *,
        metadata: dict | None = None,
        status: int = HTTPStatus.OK,
        accept_token: bool = True,
    ) -> tuple[Path, dict, HTTPServer, threading.Thread]:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        process.terminate()
        process.wait(timeout=2.0)
        exact = {
            "product_identity": PRODUCT_IDENTITY,
            "managed_runtime": {
                "managed": True,
                "instance_id": state["instance_id"],
                "pid": state["pid"],
            },
        }
        server, worker = self._metadata_server(
            expected_token=(
                state["token"]
                if accept_token
                else "different-authority-" + "z" * 32
            ),
            metadata=exact if metadata is None else metadata,
            status=status,
        )
        state["port"] = server.server_port
        state["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            server.server_port,
            state["token"],
        )
        web_module._write_runtime_state(state_path, state)
        return state_path, state, server, worker

    def test_live_pid_with_failed_probe_is_unreachable_and_state_is_retained(self) -> None:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        before = state_path.read_bytes()

        result = web_module.manage_web(self.data_dir, action="status")

        self.assertEqual(result["status"], "unreachable")
        self.assertEqual(state_path.read_bytes(), before)
        self.assertIsNone(process.poll())
        retained = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(retained["pid"], process.pid)
        self.assertEqual(retained["instance_id"], state["instance_id"])
        self.assertEqual(retained["token"], state["token"])

    def test_non_posix_liveness_never_calls_signal_zero(self) -> None:
        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("non-POSIX liveness called os.kill"),
        ) as kill:
            liveness = web_module._process_liveness(4242)

        self.assertIs(liveness, web_module.ProcessLiveness.UNKNOWN)
        kill.assert_not_called()

    def test_non_posix_status_is_unreachable_and_observational(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("non-POSIX status called os.kill"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("status created a child"),
        ) as spawn:
            status = web_module.manage_web(self.data_dir, action="status")

        self.assertEqual(status["status"], "unreachable")
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_non_posix_start_fails_closed_without_duplicate(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("non-POSIX start called os.kill"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("non-POSIX start created a child"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="start")

        self.assertEqual(caught.exception.code, "WEB_INSTANCE_UNREACHABLE")
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_non_posix_stop_does_not_signal_or_remove_state(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("non-POSIX stop signalled a PID"),
        ) as kill:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(caught.exception.code, "WEB_INSTANCE_UNREACHABLE")
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()

    def test_non_posix_restart_and_open_fail_closed(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("non-POSIX lifecycle signalled a PID"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("non-POSIX lifecycle created a child"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as restarted:
                web_module.manage_web(self.data_dir, action="restart")
            with self.assertRaises(DevFlowError) as opened:
                web_module.manage_web(self.data_dir, action="open")

        self.assertEqual(restarted.exception.code, "WEB_INSTANCE_UNREACHABLE")
        self.assertEqual(opened.exception.code, "WEB_INSTANCE_UNREACHABLE")
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_non_posix_exact_probe_establishes_running(self) -> None:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        server, _worker = self._metadata_server(
            expected_token=state["token"],
            metadata={
                "product_identity": PRODUCT_IDENTITY,
                "managed_runtime": {
                    "managed": True,
                    "instance_id": state["instance_id"],
                    "pid": state["pid"],
                },
            },
        )
        state["port"] = server.server_port
        state["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            server.server_port,
            state["token"],
        )
        web_module._write_runtime_state(state_path, state)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
            create=True,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("exact probe called os.kill"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("exact probe start created a child"),
        ) as spawn:
            status = web_module.manage_web(self.data_dir, action="status")
            opened = web_module.manage_web(self.data_dir, action="open")
            started = web_module.manage_web(self.data_dir, action="start")

        self.assertEqual(status["status"], "running")
        self.assertEqual(opened["url"], state["url"])
        self.assertEqual(started["status"], "running")
        self.assertTrue(started["already_running"])
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_non_posix_exact_probe_stop_lacks_signal_authority(self) -> None:
        _process, state_path, _state = self._exact_managed_state()
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("unknown liveness authorized a signal"),
        ) as kill:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(
            caught.exception.code,
            "WEB_PROCESS_LIVENESS_UNKNOWN",
        )
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()

    def test_non_posix_exact_probe_restart_lacks_signal_authority(self) -> None:
        _process, state_path, _state = self._exact_managed_state()
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("unknown liveness authorized a signal"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("unauthorized restart created a child"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="restart")

        self.assertEqual(
            caught.exception.code,
            "WEB_PROCESS_LIVENESS_UNKNOWN",
        )
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_alive_exact_probe_stop_has_signal_authority(self) -> None:
        _process, state_path, state = self._exact_managed_state()

        with mock.patch.object(
            web_module,
            "_process_liveness",
            side_effect=[
                web_module.ProcessLiveness.ALIVE,
                web_module.ProcessLiveness.DEAD,
                web_module.ProcessLiveness.DEAD,
            ],
        ) as liveness, mock.patch.object(web_module.os, "kill") as kill:
            stopped = web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(stopped["status"], "stopped")
        kill.assert_called_once_with(state["pid"], signal.SIGTERM)
        self.assertEqual(liveness.call_count, 3)
        self.assertFalse(state_path.exists())

    def test_dead_pid_overrides_all_reused_port_probe_results(self) -> None:
        cases = {
            "unauthorized": {"accept_token": False},
            "not-found": {"status": HTTPStatus.NOT_FOUND},
            "conflict": {
                "metadata": {
                    "product_identity": "other-product",
                    "managed_runtime": {
                        "managed": False,
                        "instance_id": None,
                        "pid": os.getpid(),
                    },
                },
            },
            "exact-looking": {},
        }
        real_kill = os.kill

        for name, options in cases.items():
            with self.subTest(name=name):
                state_path, _state, server, worker = self._dead_state_on_server(
                    **options
                )
                before = state_path.read_bytes()
                signals: list[int] = []

                def guarded_kill(pid: int, signum: int) -> None:
                    signals.append(signum)
                    if signum == 0:
                        real_kill(pid, signum)
                        return
                    raise AssertionError("dead state authorized a signal")

                with mock.patch.object(
                    web_module.os,
                    "kill",
                    side_effect=guarded_kill,
                ):
                    status = web_module.manage_web(self.data_dir, action="status")
                    with self.assertRaises(DevFlowError) as opened:
                        web_module.manage_web(self.data_dir, action="open")

                self.assertEqual(status["status"], "stopped")
                self.assertEqual(opened.exception.code, "WEB_NOT_RUNNING")
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(server.request_count, 0)
                self.assertTrue(worker.is_alive())
                self.assertTrue(all(signum == 0 for signum in signals))

    def test_dead_reused_port_stop_cleans_only_stale_state(self) -> None:
        state_path, _state, server, worker = self._dead_state_on_server()
        real_kill = os.kill
        signals: list[int] = []

        def guarded_kill(pid: int, signum: int) -> None:
            signals.append(signum)
            if signum == 0:
                real_kill(pid, signum)
                return
            raise AssertionError("dead-state cleanup sent a signal")

        with mock.patch.object(
            web_module.os,
            "kill",
            side_effect=guarded_kill,
        ):
            stopped = web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(stopped["status"], "stopped")
        self.assertFalse(state_path.exists())
        self.assertEqual(server.request_count, 0)
        self.assertTrue(worker.is_alive())
        self.assertTrue(all(signum == 0 for signum in signals))

    def test_dead_reused_port_recovers_with_one_dynamic_start(self) -> None:
        state_path, old_state, server, worker = self._dead_state_on_server(
            status=HTTPStatus.NOT_FOUND,
        )
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []
        real_kill = os.kill
        signals: list[int] = []

        def capture_popen(command, **kwargs):
            child = real_popen(command, env=environment, **kwargs)
            spawned.append(child)
            self.children.append(child)
            return child

        def guarded_kill(pid: int, signum: int) -> None:
            signals.append(signum)
            if signum == 0:
                real_kill(pid, signum)
                return
            raise AssertionError("stale recovery sent a signal")

        started = None
        try:
            with mock.patch.object(
                web_module.subprocess,
                "Popen",
                side_effect=capture_popen,
            ), mock.patch.object(
                web_module.os,
                "kill",
                side_effect=guarded_kill,
            ):
                started = web_module.manage_web(self.data_dir, action="start")

            self.assertEqual(started["status"], "running")
            self.assertEqual(len(spawned), 1)
            current = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(current["instance_id"], old_state["instance_id"])
            self.assertNotEqual(current["pid"], old_state["pid"])
            self.assertNotEqual(current["token"], old_state["token"])
            self.assertNotEqual(current["port"], old_state["port"])
            self.assertEqual(server.request_count, 0)
            self.assertTrue(worker.is_alive())
            self.assertTrue(all(signum == 0 for signum in signals))
        finally:
            if started is not None:
                try:
                    web_module.manage_web(self.data_dir, action="stop")
                except DevFlowError:
                    pass

    def test_dead_reused_fixed_port_fails_without_touching_service(self) -> None:
        state_path, _state, server, worker = self._dead_state_on_server(
            status=HTTPStatus.NOT_FOUND,
        )
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []
        real_kill = os.kill
        signals: list[int] = []

        def capture_popen(command, **kwargs):
            child = real_popen(command, env=environment, **kwargs)
            spawned.append(child)
            self.children.append(child)
            return child

        def guarded_kill(pid: int, signum: int) -> None:
            signals.append(signum)
            if signum == 0:
                real_kill(pid, signum)
                return
            raise AssertionError("fixed-port recovery sent a signal")

        with mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=capture_popen,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=guarded_kill,
        ):
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(
                    self.data_dir,
                    action="start",
                    port=server.server_port,
                )

        self.assertEqual(caught.exception.code, "WEB_START_FAILED")
        self.assertEqual(len(spawned), 1)
        self.assertTrue(all(child.poll() is not None for child in spawned))
        self.assertFalse(state_path.exists())
        self.assertEqual(server.request_count, 0)
        self.assertTrue(worker.is_alive())
        self.assertTrue(all(signum == 0 for signum in signals))

    def test_dead_reused_port_restart_recovers_without_signalling(self) -> None:
        state_path, old_state, server, worker = self._dead_state_on_server(
            accept_token=False,
        )
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []
        real_kill = os.kill
        signals: list[int] = []

        def capture_popen(command, **kwargs):
            child = real_popen(command, env=environment, **kwargs)
            spawned.append(child)
            self.children.append(child)
            return child

        def guarded_kill(pid: int, signum: int) -> None:
            signals.append(signum)
            if signum == 0:
                real_kill(pid, signum)
                return
            raise AssertionError("dead-state restart sent a signal")

        restarted = None
        try:
            with mock.patch.object(
                web_module.subprocess,
                "Popen",
                side_effect=capture_popen,
            ), mock.patch.object(
                web_module.os,
                "kill",
                side_effect=guarded_kill,
            ):
                restarted = web_module.manage_web(
                    self.data_dir,
                    action="restart",
                )

            self.assertEqual(restarted["action"], "restart")
            self.assertEqual(restarted["status"], "running")
            self.assertEqual(len(spawned), 1)
            current = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(current["instance_id"], old_state["instance_id"])
            self.assertEqual(server.request_count, 0)
            self.assertTrue(worker.is_alive())
            self.assertTrue(all(signum == 0 for signum in signals))
        finally:
            if restarted is not None:
                try:
                    web_module.manage_web(self.data_dir, action="stop")
                except DevFlowError:
                    pass

    def test_stale_start_cleanup_does_not_overwrite_replacement_state(self) -> None:
        process = self._spawn_sleeper()
        state_path, old_state = self._running_state(process)
        process.terminate()
        process.wait(timeout=2.0)
        replacement = {
            **old_state,
            "instance_id": "replacement-instance-" + "r" * 24,
            "pid": os.getpid(),
            "token": "replacement-authority-" + "t" * 32,
        }
        replacement["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            replacement["port"],
            replacement["token"],
        )
        real_read = web_module._read_runtime_state
        reads = 0

        def replace_on_revalidation(path: Path):
            nonlocal reads
            reads += 1
            if reads == 2:
                web_module._write_runtime_state(path, replacement)
            return real_read(path)

        with mock.patch.object(
            web_module,
            "_read_runtime_state",
            side_effect=replace_on_revalidation,
        ), mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("stale cleanup started a child"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="start")

        self.assertEqual(
            caught.exception.code,
            "WEB_INSTANCE_IDENTITY_CONFLICT",
        )
        self.assertEqual(
            json.loads(state_path.read_text(encoding="utf-8")),
            replacement,
        )
        spawn.assert_not_called()

    def test_non_posix_exact_probe_preserves_identity_conflict(self) -> None:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        server, _worker = self._metadata_server(
            expected_token=state["token"],
            metadata={
                "product_identity": PRODUCT_IDENTITY,
                "managed_runtime": {
                    "managed": True,
                    "instance_id": "different-instance-" + "x" * 24,
                    "pid": state["pid"],
                },
            },
        )
        state["port"] = server.server_port
        state["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            server.server_port,
            state["token"],
        )
        web_module._write_runtime_state(state_path, state)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module,
            "_supports_non_destructive_pid_probe",
            return_value=False,
        ), mock.patch.object(
            web_module.os,
            "kill",
            side_effect=AssertionError("identity conflict signalled a PID"),
        ) as kill, mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("identity conflict created a child"),
        ) as spawn:
            status = web_module.manage_web(self.data_dir, action="status")
            with self.assertRaises(DevFlowError) as started:
                web_module.manage_web(self.data_dir, action="start")
            with self.assertRaises(DevFlowError) as stopped:
                web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(status["status"], "identity-conflict")
        self.assertEqual(
            started.exception.code,
            "WEB_INSTANCE_IDENTITY_CONFLICT",
        )
        self.assertEqual(
            stopped.exception.code,
            "WEB_INSTANCE_IDENTITY_CONFLICT",
        )
        self.assertEqual(state_path.read_bytes(), before)
        kill.assert_not_called()
        spawn.assert_not_called()

    def test_start_does_not_spawn_duplicate_when_live_instance_is_unreachable(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("duplicate child was created"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="start")

        self.assertEqual(caught.exception.code, "WEB_INSTANCE_UNREACHABLE")
        spawn.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)
        self.assertIsNone(process.poll())

    def test_stop_does_not_signal_or_forget_unverified_live_pid(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()
        real_kill = os.kill
        signals: list[int] = []

        def guarded_kill(pid: int, signum: int) -> None:
            signals.append(signum)
            if signum == 0:
                real_kill(pid, signum)
                return
            raise AssertionError("unverified PID received a termination signal")

        with mock.patch.object(web_module.os, "kill", side_effect=guarded_kill):
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="stop")

        self.assertEqual(caught.exception.code, "WEB_INSTANCE_UNREACHABLE")
        self.assertNotIn(signal.SIGTERM, signals)
        self.assertEqual(state_path.read_bytes(), before)
        self.assertIsNone(process.poll())

    def test_start_timeout_reaps_owned_child_before_removing_reservation(self) -> None:
        environment = hermetic_subprocess_env(self.root)
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []

        def capture_popen(command, **kwargs):
            process = real_popen(command, env=environment, **kwargs)
            spawned.append(process)
            self.children.append(process)
            return process

        child_command = [sys.executable, "-c", "import time; time.sleep(30)"]
        with mock.patch.object(
            web_module,
            "WEB_START_TIMEOUT_SECONDS",
            0.1,
        ), mock.patch.object(
            web_module,
            "_child_command",
            return_value=child_command,
        ), mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=capture_popen,
        ):
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="start")

        self.assertEqual(caught.exception.code, "WEB_START_FAILED")
        self.assertEqual(len(spawned), 1)
        self.assertIsNotNone(spawned[0].poll(), "start timeout left its child alive")
        _root, state_path, _lock_path, _log_path = web_module._runtime_paths(
            self.data_dir
        )
        self.assertFalse(state_path.exists())

    def test_exact_managed_metadata_stop_and_recovery_have_no_orphan(self) -> None:
        started_rc, started = self._invoke_cli("start")
        self.assertEqual(started_rc, 0, started)
        first_pid = started["pid"]
        try:
            _root, state_path, _lock_path, _log_path = web_module._runtime_paths(
                self.data_dir
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            parsed = urlsplit(started["url"])
            token = parse_qs(parsed.fragment)["token"][0]
            connection = http.client.HTTPConnection(
                parsed.hostname,
                parsed.port,
                timeout=5,
            )
            connection.request(
                "GET",
                "/api/meta",
                headers={"Authorization": "Bearer " + token},
            )
            response = connection.getresponse()
            metadata = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, HTTPStatus.OK)
            self.assertEqual(metadata["product_identity"], PRODUCT_IDENTITY)
            self.assertEqual(
                metadata["managed_runtime"],
                {
                    "managed": True,
                    "instance_id": state["instance_id"],
                    "pid": first_pid,
                },
            )

            stopped_rc, stopped = self._invoke_cli("stop")
            self.assertEqual(stopped_rc, 0, stopped)
            self.assertEqual(stopped["status"], "stopped")
            with self.assertRaises(ProcessLookupError):
                os.kill(first_pid, 0)
            self.assertFalse(state_path.exists())
            status_rc, status = self._invoke_cli("status")
            self.assertEqual(status_rc, 0)
            self.assertEqual(status["status"], "stopped")

            restarted_rc, restarted = self._invoke_cli("start")
            self.assertEqual(restarted_rc, 0, restarted)
            self.assertNotEqual(restarted["pid"], first_pid)
        finally:
            self._invoke_cli("stop")

    def test_identity_conflicts_retain_state_and_forbid_start_and_stop(self) -> None:
        process = self._spawn_sleeper()
        state_path, state = self._running_state(process)
        server, _worker = self._metadata_server(
            expected_token=state["token"],
            metadata={},
        )
        state["port"] = server.server_port
        state["url"] = "http://{}:{}/#token={}".format(
            web_module.SERVER_HOST,
            server.server_port,
            state["token"],
        )
        exact = {
            "product_identity": PRODUCT_IDENTITY,
            "managed_runtime": {
                "managed": True,
                "instance_id": state["instance_id"],
                "pid": state["pid"],
            },
        }
        cases = {
            "instance": {
                **exact,
                "managed_runtime": {
                    **exact["managed_runtime"],
                    "instance_id": "different-instance-" + "x" * 24,
                },
            },
            "pid": {
                **exact,
                "managed_runtime": {
                    **exact["managed_runtime"],
                    "pid": state["pid"] + 1,
                },
            },
            "product": {**exact, "product_identity": "other-product"},
            "other-service": {
                **exact,
                "managed_runtime": {
                    "managed": False,
                    "instance_id": None,
                    "pid": os.getpid(),
                },
            },
            "token": exact,
        }
        real_kill = os.kill

        for name, metadata in cases.items():
            with self.subTest(name=name):
                server.metadata = metadata
                server.expected_token = (
                    "different-authority-" + "z" * 32
                    if name == "token"
                    else state["token"]
                )
                web_module._write_runtime_state(state_path, state)
                before = state_path.read_bytes()
                status = web_module.manage_web(self.data_dir, action="status")
                self.assertEqual(status["status"], "identity-conflict")

                with mock.patch.object(
                    web_module.subprocess,
                    "Popen",
                    side_effect=AssertionError("identity conflict spawned a child"),
                ) as spawn:
                    with self.assertRaises(DevFlowError) as start_error:
                        web_module.manage_web(self.data_dir, action="start")
                self.assertEqual(
                    start_error.exception.code,
                    "WEB_INSTANCE_IDENTITY_CONFLICT",
                )
                spawn.assert_not_called()

                sent: list[int] = []

                def guarded_kill(pid: int, signum: int) -> None:
                    sent.append(signum)
                    if signum == 0:
                        real_kill(pid, signum)
                        return
                    raise AssertionError("identity conflict was signalled")

                with mock.patch.object(
                    web_module.os,
                    "kill",
                    side_effect=guarded_kill,
                ):
                    with self.assertRaises(DevFlowError) as stop_error:
                        web_module.manage_web(self.data_dir, action="stop")
                self.assertEqual(
                    stop_error.exception.code,
                    "WEB_INSTANCE_IDENTITY_CONFLICT",
                )
                self.assertNotIn(signal.SIGTERM, sent)
                self.assertEqual(state_path.read_bytes(), before)

    def test_dead_state_is_observed_then_exactly_replaced_once(self) -> None:
        old_process = self._spawn_sleeper()
        state_path, old_state = self._running_state(old_process)
        old_bytes = state_path.read_bytes()
        old_process.terminate()
        old_process.wait(timeout=2.0)

        observed = web_module.manage_web(self.data_dir, action="status")
        self.assertEqual(observed["status"], "stopped")
        self.assertEqual(state_path.read_bytes(), old_bytes)

        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen] = []

        def capture_popen(command, **kwargs):
            child = real_popen(command, env=environment, **kwargs)
            spawned.append(child)
            self.children.append(child)
            return child

        try:
            with mock.patch.object(
                web_module.subprocess,
                "Popen",
                side_effect=capture_popen,
            ):
                started = web_module.manage_web(self.data_dir, action="start")
            self.assertEqual(started["status"], "running")
            self.assertEqual(len(spawned), 1)
            new_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotEqual(new_state["instance_id"], old_state["instance_id"])
            self.assertNotEqual(new_state["pid"], old_state["pid"])
            web_module._remove_runtime_state(
                state_path,
                old_state["instance_id"],
            )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["instance_id"],
                new_state["instance_id"],
            )
        finally:
            try:
                web_module.manage_web(self.data_dir, action="stop")
            except DevFlowError:
                pass

    def test_unconfirmed_startup_child_retains_state_and_blocks_next_start(self) -> None:
        owned_process = self._spawn_sleeper()
        fake = _UnreapableProcess(owned_process.pid)
        with mock.patch.object(
            web_module,
            "WEB_START_TIMEOUT_SECONDS",
            0.05,
        ), mock.patch.object(
            web_module,
            "WEB_CHILD_TERMINATE_TIMEOUT_SECONDS",
            0.01,
        ), mock.patch.object(
            web_module.subprocess,
            "Popen",
            return_value=fake,
        ):
            with self.assertRaises(DevFlowError) as caught:
                web_module.manage_web(self.data_dir, action="start")
        self.assertEqual(caught.exception.code, "WEB_START_UNVERIFIED")
        _root, state_path, _lock_path, _log_path = web_module._runtime_paths(
            self.data_dir
        )
        retained = state_path.read_bytes()
        status = web_module.manage_web(self.data_dir, action="status")
        self.assertEqual(status["status"], "starting")

        with mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("retained starting state spawned another child"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as repeated:
                web_module.manage_web(self.data_dir, action="start")
        self.assertEqual(repeated.exception.code, "WEB_INSTANCE_STARTING")
        spawn.assert_not_called()
        self.assertEqual(state_path.read_bytes(), retained)

    def test_restart_and_open_do_not_bypass_unreachable_gate(self) -> None:
        process = self._spawn_sleeper()
        state_path, _state = self._running_state(process)
        before = state_path.read_bytes()

        with self.assertRaises(DevFlowError) as opened:
            web_module.manage_web(self.data_dir, action="open")
        self.assertEqual(opened.exception.code, "WEB_INSTANCE_UNREACHABLE")

        with mock.patch.object(
            web_module.subprocess,
            "Popen",
            side_effect=AssertionError("restart bypassed safe stop"),
        ) as spawn:
            with self.assertRaises(DevFlowError) as restarted:
                web_module.manage_web(self.data_dir, action="restart")
        self.assertEqual(restarted.exception.code, "WEB_INSTANCE_UNREACHABLE")
        spawn.assert_not_called()
        self.assertEqual(state_path.read_bytes(), before)

    def test_two_independent_starts_converge_on_one_managed_instance(self) -> None:
        environment = hermetic_subprocess_env(
            self.root,
            overrides={"PYTHONPATH": str(SRC)},
        )
        command = self._cli_command() + ["start"]
        contenders = [
            subprocess.Popen(
                command,
                cwd=str(SRC.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
            )
            for _ in range(2)
        ]
        outcomes = []
        try:
            for contender in contenders:
                stdout, stderr = contender.communicate(timeout=20.0)
                outcomes.append(
                    (contender.returncode, json.loads(stdout), stderr)
                )
            successful = [value for code, value, _ in outcomes if code == 0]
            rejected = [value for code, value, _ in outcomes if code != 0]
            rejected_codes = [value["error"]["code"] for value in rejected]
            if successful:
                for code in rejected_codes:
                    self.assertIn(
                        code,
                        {"WEB_INSTANCE_STARTING", "WEB_INSTANCE_UNREACHABLE"},
                    )
            else:
                self.assertCountEqual(
                    rejected_codes,
                    ["WEB_INSTANCE_STARTING", "WEB_START_FAILED"],
                )
                stopped_rc, stopped = self._invoke_cli("status")
                self.assertEqual(stopped_rc, 0, outcomes)
                self.assertEqual(stopped["status"], "stopped")
                recovered_rc, recovered = self._invoke_cli("start")
                self.assertEqual(recovered_rc, 0, recovered)
                successful = [recovered]
            status_rc, status = self._invoke_cli("status")
            self.assertEqual(status_rc, 0, outcomes)
            self.assertEqual(status["status"], "running")
            self.assertEqual(
                {value["pid"] for value in successful},
                {status["pid"]},
            )
            _root, state_path, _lock_path, _log_path = web_module._runtime_paths(
                self.data_dir
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["pid"], status["pid"])
        finally:
            for contender in contenders:
                if contender.poll() is None:
                    contender.terminate()
                    contender.wait(timeout=2.0)
            self._invoke_cli("stop")


if __name__ == "__main__":
    unittest.main()
