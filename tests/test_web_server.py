"""Loopback HTTP security and lifecycle tests for the integrated Web UI."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Optional
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlencode, urlsplit


SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from dev_flow_orchestrator.product import PRODUCT_IDENTITY, RELEASE_VERSION
from dev_flow_orchestrator.model import DevFlowError
from dev_flow_orchestrator.web import (
    LIVE_CAPTURE_SLOT,
    create_server,
    startup_receipt,
)
from support import RepositoryTestCase


class WebServerTests(RepositoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.token = "test-authority-" + "a" * 32
        self.server = create_server(self.data_dir, token=self.token)
        self.worker = threading.Thread(target=self.server.serve_forever)
        self.worker.start()

    def tearDown(self) -> None:
        self.server.cancel_live_capture()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        super().tearDown()

    def request(
        self,
        method: str,
        target: str,
        *,
        authorize: bool = False,
        headers: Optional[dict] = None,
    ) -> tuple:
        selected = {} if headers is None else dict(headers)
        if authorize:
            selected["Authorization"] = "Bearer " + self.token
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request(method, target, headers=selected)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()), body)
        connection.close()
        return result

    def json_request(self, method: str, target: str, **kwargs: object) -> tuple:
        status, headers, body = self.request(method, target, **kwargs)
        return status, headers, json.loads(body.decode("utf-8"))

    def test_startup_receipt_uses_ephemeral_loopback_and_fragment_token(self) -> None:
        receipt = startup_receipt(self.server)

        self.assertEqual(receipt["host"], "127.0.0.1")
        self.assertGreater(receipt["port"], 0)
        self.assertEqual(receipt["version"], RELEASE_VERSION)
        self.assertEqual(receipt["product_identity"], PRODUCT_IDENTITY)
        self.assertEqual(
            receipt["url"],
            "http://127.0.0.1:{}/#token={}".format(
                self.server.server_port,
                self.token,
            ),
        )

    def test_static_assets_are_allowlisted_no_store_and_headable(self) -> None:
        for path, content_type in (
            ("/", "text/html"),
            ("/assets/app.js", "text/javascript"),
            ("/assets/styles.css", "text/css"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["Connection"], "close")
                self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
                self.assertNotIn("Access-Control-Allow-Origin", headers)
                self.assertTrue(body)
                head_status, head_headers, head_body = self.request("HEAD", path)
                self.assertEqual(head_status, 200)
                self.assertEqual(head_body, b"")
                self.assertEqual(head_headers["Content-Length"], headers["Content-Length"])

    def test_api_requires_exact_bearer_host_and_origin(self) -> None:
        missing, _, missing_body = self.json_request("GET", "/api/meta")
        self.assertEqual(missing, 401)
        self.assertEqual(missing_body["error"]["code"], "HTTP_AUTH_REQUIRED")

        invalid, _, invalid_body = self.json_request(
            "GET",
            "/api/meta",
            headers={"Authorization": "Bearer incorrect"},
        )
        self.assertEqual(invalid, 401)
        self.assertEqual(invalid_body["error"]["code"], "HTTP_AUTH_INVALID")

        forbidden_host, _, host_body = self.json_request(
            "GET",
            "/api/meta",
            authorize=True,
            headers={"Host": "localhost:{}".format(self.server.server_port)},
        )
        self.assertEqual(forbidden_host, 403)
        self.assertEqual(host_body["error"]["code"], "HTTP_HOST_FORBIDDEN")

        forbidden_origin, _, origin_body = self.json_request(
            "GET",
            "/api/meta",
            authorize=True,
            headers={"Origin": "https://attacker.invalid"},
        )
        self.assertEqual(forbidden_origin, 403)
        self.assertEqual(origin_body["error"]["code"], "HTTP_ORIGIN_FORBIDDEN")

        forbidden_fetch, _, fetch_body = self.json_request(
            "GET",
            "/api/meta",
            authorize=True,
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        self.assertEqual(forbidden_fetch, 403)
        self.assertEqual(fetch_body["error"]["code"], "HTTP_FETCH_FORBIDDEN")

        duplicate = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2)
        duplicate.sendall(
            (
                "GET /api/meta HTTP/1.1\r\n"
                "Host: 127.0.0.1:{}\r\n"
                "Host: attacker.invalid\r\n"
                "Authorization: Bearer {}\r\n\r\n"
            ).format(self.server.server_port, self.token).encode("ascii")
        )
        chunks = []
        while True:
            chunk = duplicate.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        response = b"".join(chunks)
        duplicate.close()
        self.assertIn(b"403 Forbidden", response)
        self.assertIn(b"HTTP_HOST_FORBIDDEN", response)

    def test_closed_routes_methods_and_targets_fail(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"):
            with self.subTest(method=method):
                status, _, body = self.json_request(method, "/api/tasks", authorize=True)
                self.assertEqual(status, 405)
                self.assertEqual(body["error"]["code"], "HTTP_METHOD_FORBIDDEN")

        for target in ("/unknown", "/../state.json", "/%2e%2e/state.json", "/api/tasks?extra=1"):
            with self.subTest(target=target):
                status, _, body = self.json_request("GET", target, authorize=True)
                self.assertIn(status, (400, 404))
                self.assertIn(
                    body["error"]["code"],
                    {"HTTP_ROUTE_NOT_FOUND", "HTTP_TARGET_INVALID", "VIEW_QUERY_INVALID"},
                )

        head_status, _, head_body = self.request("HEAD", "/api/meta", authorize=True)
        self.assertEqual(head_status, 405)
        self.assertEqual(head_body, b"")

    def test_percent_encoded_utf8_inventory_filters_work(self) -> None:
        task_id = self.start_lite("支持中文检索")

        search_query = urlencode({"q": "中文检索"})
        self.assertIn("%E4%B8%AD", search_query)
        search_status, _, search = self.json_request(
            "GET",
            "/api/tasks?" + search_query,
            authorize=True,
        )

        self.assertEqual(search_status, 200)
        self.assertEqual(search["result"]["filters"]["q"], "中文检索")
        self.assertEqual(
            [item["task_id"] for item in search["result"]["tasks"]],
            [task_id],
        )

        repository_path = str(self.repository.resolve())
        repository_query = urlencode({"repository": repository_path})
        encoded_separator = "%5C" if os.name == "nt" else "%2F"
        self.assertIn(encoded_separator, repository_query)
        repository_status, _, repository = self.json_request(
            "GET",
            "/api/tasks?" + repository_query,
            authorize=True,
        )

        self.assertEqual(repository_status, 200)
        self.assertEqual(repository["result"]["filters"]["repository_path_count"], 1)
        self.assertEqual(
            [item["task_id"] for item in repository["result"]["tasks"]],
            [task_id],
        )

    def test_invalid_encoded_targets_fail_before_storage_inspection(self) -> None:
        invalid_targets = (
            ("/api%2Ftasks", "HTTP_TARGET_INVALID"),
            ("/api%5Ctasks", "HTTP_TARGET_INVALID"),
            ("/api/%2e%2e/tasks", "HTTP_TARGET_INVALID"),
            ("/api/../tasks", "HTTP_TARGET_INVALID"),
            ("/api//tasks", "HTTP_TARGET_INVALID"),
            ("/api/tasks?q=%", "VIEW_QUERY_INVALID"),
            ("/api/tasks?q=%GG", "VIEW_QUERY_INVALID"),
            ("/api/tasks?q=%FF", "VIEW_QUERY_INVALID"),
            ("/api/tasks?extra=%E4%B8%AD", "VIEW_QUERY_INVALID"),
            ("/api/tasks?q=" + "a" * 4096, "HTTP_TARGET_INVALID"),
        )
        with mock.patch.object(
            self.server.controller.store,
            "inspect_inventory",
        ) as inspect_inventory, mock.patch.object(
            self.server.controller.store,
            "inspect_with_definition",
        ) as inspect_detail:
            for target, code in invalid_targets:
                with self.subTest(target=target[:80], code=code):
                    status, _, body = self.json_request(
                        "GET",
                        target,
                        authorize=True,
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(body["error"]["code"], code)

        inspect_inventory.assert_not_called()
        inspect_detail.assert_not_called()

    def test_stored_inventory_and_detail_are_available_over_http(self) -> None:
        task_id = self.start_lite("HTTP stored task")
        status, headers, inventory = self.json_request("GET", "/api/tasks", authorize=True)

        self.assertEqual(status, 200)
        self.assertEqual(inventory["view"], "task-inventory")
        self.assertEqual(inventory["result"]["tasks"][0]["task_id"], task_id)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

        detail_status, _, detail = self.json_request(
            "GET",
            "/api/tasks/{}".format(task_id),
            authorize=True,
        )
        self.assertEqual(detail_status, 200)
        self.assertEqual(detail["result"]["health"], "not-evaluated")
        self.assertNotIn(str(self.repository), json.dumps(detail))

    def test_competing_live_capture_returns_429_without_queueing(self) -> None:
        task_id = self.start_lite("busy live task")
        acquired = LIVE_CAPTURE_SLOT.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            status, headers, body = self.json_request(
                "GET",
                "/api/tasks/{}/live".format(task_id),
                authorize=True,
            )
        finally:
            LIVE_CAPTURE_SLOT.release()

        self.assertEqual(status, 429)
        self.assertEqual(headers["Retry-After"], "1")
        self.assertEqual(body["error"]["code"], "LIVE_CAPTURE_BUSY")

    def test_client_abandonment_cancels_live_capture_and_releases_slot(self) -> None:
        task_id = self.start_lite("abandoned live task")
        started = threading.Event()
        cancelled = threading.Event()

        def inspect_live_task(selected_task_id: str, *, cancel_event: object, **_: object) -> dict:
            self.assertEqual(selected_task_id, task_id)
            started.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    cancelled.set()
                    raise DevFlowError("GIT_COMMAND_CANCELLED", "live observation cancelled")
                time.sleep(0.01)
            self.fail("abandoned client did not cancel live capture")

        self.server.controller.inspect_live_task = inspect_live_task
        client = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2)
        request = (
            "GET /api/tasks/{}/live HTTP/1.1\r\n"
            "Host: 127.0.0.1:{}\r\n"
            "Authorization: Bearer {}\r\n"
            "Connection: close\r\n\r\n"
        ).format(task_id, self.server.server_port, self.token)
        client.sendall(request.encode("ascii"))
        self.assertTrue(started.wait(timeout=2))
        client.close()
        self.assertTrue(cancelled.wait(timeout=2))

        deadline = time.monotonic() + 2
        acquired = False
        while time.monotonic() < deadline and not acquired:
            acquired = LIVE_CAPTURE_SLOT.acquire(blocking=False)
            if not acquired:
                time.sleep(0.01)
        self.assertTrue(acquired)
        LIVE_CAPTURE_SLOT.release()

    def test_shutdown_cancels_active_live_and_releases_listener(self) -> None:
        task_id = self.start_lite("shutdown live task")
        other = create_server(self.data_dir, token=self.token)
        port = other.server_port
        worker = threading.Thread(target=other.serve_forever)
        worker.start()
        started = threading.Event()
        cancelled = threading.Event()

        def inspect_live_task(_: str, *, cancel_event: object, **__: object) -> dict:
            started.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    cancelled.set()
                    raise DevFlowError("GIT_COMMAND_CANCELLED", "shutdown cancelled capture")
                time.sleep(0.01)
            self.fail("shutdown did not cancel live capture")

        other.controller.inspect_live_task = inspect_live_task
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        client.sendall(
            (
                "GET /api/tasks/{}/live HTTP/1.1\r\n"
                "Host: 127.0.0.1:{}\r\n"
                "Authorization: Bearer {}\r\n\r\n"
            ).format(task_id, port, self.token).encode("ascii")
        )
        self.assertTrue(started.wait(timeout=2))
        other.cancel_live_capture()
        other.shutdown()
        other.server_close()
        worker.join(timeout=2)
        client.close()

        self.assertTrue(cancelled.wait(timeout=2))
        self.assertFalse(worker.is_alive())
        acquired = LIVE_CAPTURE_SLOT.acquire(blocking=False)
        self.assertTrue(acquired)
        LIVE_CAPTURE_SLOT.release()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)
        finally:
            probe.close()

    def test_missing_namespace_inventory_does_not_create_storage(self) -> None:
        missing = self.root / "missing-web-data"
        other = create_server(str(missing), token=self.token)
        worker = threading.Thread(target=other.serve_forever)
        worker.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", other.server_port, timeout=5)
            connection.request(
                "GET",
                "/api/tasks",
                headers={"Authorization": "Bearer " + self.token},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            connection.close()
        finally:
            other.shutdown()
            other.server_close()
            worker.join(timeout=2)
        self.assertFalse(missing.exists())

    def test_request_handler_concurrency_is_bounded(self) -> None:
        bounded = create_server(self.data_dir, token=self.token, handler_limit=1)
        worker = threading.Thread(target=bounded.serve_forever)
        worker.start()
        occupying = socket.create_connection(("127.0.0.1", bounded.server_port), timeout=2)
        occupying.sendall(b"GET / HTTP/1.1\r\n")
        try:
            rejected = socket.create_connection(("127.0.0.1", bounded.server_port), timeout=2)
            try:
                rejected.sendall(
                    "GET / HTTP/1.1\r\nHost: 127.0.0.1:{}\r\n\r\n".format(
                        bounded.server_port
                    ).encode("ascii")
                )
                try:
                    response = rejected.recv(256)
                except (ConnectionAbortedError, ConnectionResetError):
                    if os.name != "nt":
                        raise
                else:
                    self.assertIn(b"503 Service Unavailable", response)
            finally:
                rejected.close()
            occupying.close()

            deadline = time.monotonic() + 2
            while True:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", bounded.server_port, timeout=2
                )
                try:
                    connection.request(
                        "GET",
                        "/api/meta",
                        headers={"Authorization": "Bearer " + self.token},
                    )
                    response = connection.getresponse()
                    response.read()
                    if response.status == 200:
                        break
                    self.assertEqual(response.status, 503)
                    if time.monotonic() >= deadline:
                        self.fail("handler slot was not released after rejected request")
                    time.sleep(0.02)
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.02)
                finally:
                    connection.close()
        finally:
            occupying.close()
            bounded.shutdown()
            bounded.server_close()
            worker.join(timeout=2)

    def test_requested_occupied_port_fails_closed(self) -> None:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        try:
            with self.assertRaises(DevFlowError) as context:
                create_server(
                    self.data_dir,
                    port=occupied.getsockname()[1],
                    token=self.token,
                )
        finally:
            occupied.close()
        self.assertEqual(context.exception.code, "WEB_BIND_FAILED")

    def test_cli_web_is_foreground_and_stops_on_console_interrupt(self) -> None:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(SRC)
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "dev_flow_orchestrator.cli",
                "--data-dir",
                self.data_dir,
                "web",
            ],
            cwd=str(SRC.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            creationflags=creationflags,
        )
        try:
            self.assertIsNotNone(process.stdout)
            receipt = json.loads(process.stdout.readline())
            self.assertIsNone(process.poll())
            parsed = urlsplit(receipt["url"])
            token = parse_qs(parsed.fragment)["token"][0]
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            connection.request(
                "GET",
                "/api/meta",
                headers={"Authorization": "Bearer " + token},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Connection"), "close")
            response.read()
            if os.name == "nt":
                os.kill(process.pid, signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
            self.assertEqual(process.wait(timeout=5), 0)
            connection.close()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
