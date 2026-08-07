"""Authenticated loopback-only HTTP presentation surface for current tasks."""

from __future__ import annotations

import datetime as dt
import http.client
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
import json
import os
from pathlib import Path
import select
import secrets
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from typing import Mapping, Optional, Sequence, TextIO
from urllib.parse import parse_qs, urlsplit

from .controller import Controller
from ._platform.storage import (
    atomic_write_bytes,
    ensure_private_directory,
    exclusive_file_lock,
)
from .model import DevFlowError
from .product import PRODUCT_IDENTITY, RELEASE_VERSION


SERVER_HOST = "127.0.0.1"
DEFAULT_HANDLER_LIMIT = 8
MAX_REQUEST_TARGET_BYTES = 4096
LIVE_RETRY_SECONDS = 1
LIVE_CAPTURE_SLOT = threading.Lock()
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
WEB_RUNTIME_SCHEMA = "dev-flow-web-runtime"
WEB_RUNTIME_DIRECTORY = "web-runtime"
WEB_RUNTIME_STATE = "state.json"
WEB_RUNTIME_LOCK = "control.lock"
WEB_RUNTIME_LOG = "server.log"
WEB_START_TIMEOUT_SECONDS = 5.0


class _CancellationSignal:
    """Read-only union of cancellation events accepted by GitClient."""

    def __init__(self, *events: threading.Event) -> None:
        self._events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _error(code: str, message: str) -> dict:
    return {
        "ok": False,
        "version": RELEASE_VERSION,
        "product_identity": PRODUCT_IDENTITY,
        "view": "error",
        "observed_at": _utc_now(),
        "error": {"code": code, "message": message},
    }


class BoundedThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Threaded loopback server with a fixed process-local handler budget."""

    daemon_threads = False
    block_on_close = True
    request_queue_size = 16

    def __init__(
        self,
        server_address: tuple,
        handler_class: type,
        *,
        controller: Controller,
        token: str,
        handler_limit: int = DEFAULT_HANDLER_LIMIT,
    ) -> None:
        self.controller = controller
        self.token = token
        self.cancel_event = threading.Event()
        self._handlers = threading.BoundedSemaphore(handler_limit)
        super().__init__(server_address, handler_class, bind_and_activate=True)

    @property
    def origin(self) -> str:
        return "http://{}:{}".format(SERVER_HOST, self.server_port)

    @property
    def expected_host(self) -> str:
        return "{}:{}".format(SERVER_HOST, self.server_port)

    def process_request(self, request: socket.socket, client_address: tuple) -> None:
        if not self._handlers.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Connection: close\r\nContent-Length: 0\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._handlers.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._handlers.release()

    def cancel_live_capture(self) -> None:
        self.cancel_event.set()

    def handle_error(self, request: socket.socket, client_address: tuple) -> None:
        return


class WebRequestHandler(BaseHTTPRequestHandler):
    """Closed route adapter; no task mutation method is implemented."""

    protocol_version = "HTTP/1.1"
    server: BoundedThreadingHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self, content_type: str, length: int) -> None:
        self.close_connection = True
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'none'"
        ))
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        content_type: str,
        *,
        head_only: bool = False,
        retry_after: Optional[int] = None,
    ) -> None:
        self.send_response(status)
        self._security_headers(content_type, len(payload))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        if not head_only:
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return

    def _send_json(
        self,
        status: int,
        value: Mapping[str, object],
        *,
        retry_after: Optional[int] = None,
    ) -> None:
        self._send_bytes(
            status,
            _json_bytes(value),
            "application/json; charset=utf-8",
            retry_after=retry_after,
        )

    def _reject(self, status: int, code: str, message: str) -> None:
        self._send_json(status, _error(code, message))

    def _target(self) -> tuple:
        try:
            raw = self.path.encode("ascii", errors="strict")
        except UnicodeError as exc:
            raise DevFlowError("HTTP_TARGET_INVALID", "request target must be ASCII") from exc
        if len(raw) > MAX_REQUEST_TARGET_BYTES:
            raise DevFlowError("HTTP_TARGET_INVALID", "request target is not canonical")
        target = urlsplit(self.path)
        if (
            target.scheme
            or target.netloc
            or "#" in self.path
            or not target.path.startswith("/")
        ):
            raise DevFlowError("HTTP_TARGET_INVALID", "request target is not origin-form")
        if (
            "\\" in target.path
            or "%" in target.path
            or "//" in target.path
            or any(segment in (".", "..") for segment in target.path.split("/"))
        ):
            raise DevFlowError("HTTP_TARGET_INVALID", "request path is not canonical")
        return target.path, target.query

    def _validate_origin(self, *, api: bool) -> bool:
        hosts = self.headers.get_all("Host", ())
        if tuple(hosts) != (self.server.expected_host,):
            self._reject(HTTPStatus.FORBIDDEN, "HTTP_HOST_FORBIDDEN", "request Host is not bound origin")
            return False
        origins = self.headers.get_all("Origin", ())
        if len(origins) > 1:
            self._reject(HTTPStatus.FORBIDDEN, "HTTP_ORIGIN_FORBIDDEN", "request origin is not bound origin")
            return False
        origin = origins[0] if origins else None
        if origin is not None and origin != self.server.origin:
            self._reject(HTTPStatus.FORBIDDEN, "HTTP_ORIGIN_FORBIDDEN", "request origin is not bound origin")
            return False
        fetch_sites = self.headers.get_all("Sec-Fetch-Site", ())
        if len(fetch_sites) > 1:
            self._reject(HTTPStatus.FORBIDDEN, "HTTP_FETCH_FORBIDDEN", "cross-site request is forbidden")
            return False
        fetch_site = fetch_sites[0] if fetch_sites else None
        allowed_sites = {None, "same-origin", "none"}
        if fetch_site not in allowed_sites or (api and fetch_site == "cross-site"):
            self._reject(HTTPStatus.FORBIDDEN, "HTTP_FETCH_FORBIDDEN", "cross-site request is forbidden")
            return False
        return True

    def _authorize(self) -> bool:
        values = self.headers.get_all("Authorization", ())
        value = values[0] if len(values) == 1 else None
        if not isinstance(value, str) or not value.startswith("Bearer "):
            self._reject(HTTPStatus.UNAUTHORIZED, "HTTP_AUTH_REQUIRED", "bearer authority is required")
            return False
        supplied = value[len("Bearer ") :]
        if not secrets.compare_digest(supplied, self.server.token):
            self._reject(HTTPStatus.UNAUTHORIZED, "HTTP_AUTH_INVALID", "bearer authority is invalid")
            return False
        return True

    def _watch_client(
        self,
        abandoned: threading.Event,
        completed: threading.Event,
    ) -> None:
        """Signal when the peer disappears during an explicit live capture."""
        while not completed.is_set():
            try:
                readable, _, _ = select.select([self.connection], [], [], 0.1)
                if readable:
                    pending = self.connection.recv(1, socket.MSG_PEEK)
                    if not pending:
                        abandoned.set()
                        return
                    completed.wait(0.1)
            except (OSError, ValueError):
                abandoned.set()
                return

    @staticmethod
    def _query(query: str, allowed: Sequence[str]) -> dict:
        cursor = 0
        while cursor < len(query):
            if query[cursor] != "%":
                cursor += 1
                continue
            if (
                cursor + 2 >= len(query)
                or query[cursor + 1] not in _HEX_DIGITS
                or query[cursor + 2] not in _HEX_DIGITS
            ):
                raise DevFlowError("VIEW_QUERY_INVALID", "query string is invalid")
            cursor += 3
        try:
            values = parse_qs(
                query,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=32,
                encoding="utf-8",
                errors="strict",
            ) if query else {}
        except ValueError as exc:
            raise DevFlowError("VIEW_QUERY_INVALID", "query string is invalid") from exc
        unknown = set(values) - set(allowed)
        if unknown:
            raise DevFlowError("VIEW_QUERY_INVALID", "query contains unsupported fields")
        return values

    @staticmethod
    def _one(values: Mapping[str, list], name: str, default: str) -> str:
        selected = values.get(name)
        if selected is None:
            return default
        if len(selected) != 1:
            raise DevFlowError("VIEW_QUERY_INVALID", "query field must appear once")
        return selected[0]

    @classmethod
    def _integer(cls, values: Mapping[str, list], name: str, default: int) -> int:
        raw = cls._one(values, name, str(default))
        try:
            return int(raw)
        except ValueError as exc:
            raise DevFlowError("VIEW_QUERY_INVALID", "query integer is invalid") from exc

    def _asset(self, name: str, content_type: str, *, head_only: bool) -> None:
        payload = resources.files("dev_flow_orchestrator").joinpath(
            "web_assets", name
        ).read_bytes()
        self._send_bytes(HTTPStatus.OK, payload, content_type, head_only=head_only)

    def _static(self, path: str, *, head_only: bool) -> bool:
        if path == "/":
            self._asset("index.html", "text/html; charset=utf-8", head_only=head_only)
            return True
        if path == "/assets/app.js":
            self._asset("app.js", "text/javascript; charset=utf-8", head_only=head_only)
            return True
        if path == "/assets/styles.css":
            self._asset("styles.css", "text/css; charset=utf-8", head_only=head_only)
            return True
        return False

    def _api(self, path: str, query: str) -> None:
        if path == "/api/meta":
            if query:
                raise DevFlowError("VIEW_QUERY_INVALID", "metadata view has no query fields")
            self._send_json(HTTPStatus.OK, self.server.controller.inspect_product())
            return
        if path == "/api/tasks":
            values = self._query(
                query,
                ("q", "status", "workflow", "repository", "terminal", "offset", "limit"),
            )
            terminal_raw = self._one(values, "terminal", "")
            if terminal_raw not in ("", "true", "false"):
                raise DevFlowError("VIEW_QUERY_INVALID", "terminal query is invalid")
            response = self.server.controller.inspect_tasks(
                query=self._one(values, "q", ""),
                statuses=tuple(values.get("status", ())),
                workflows=tuple(values.get("workflow", ())),
                repositories=tuple(values.get("repository", ())),
                terminal=None if terminal_raw == "" else terminal_raw == "true",
                offset=self._integer(values, "offset", 0),
                limit=self._integer(values, "limit", 50),
            )
            self._send_json(HTTPStatus.OK, response)
            return

        prefix = "/api/tasks/"
        if not path.startswith(prefix):
            raise DevFlowError("HTTP_ROUTE_NOT_FOUND", "route is not available")
        remainder = path[len(prefix) :]
        live = remainder.endswith("/live")
        task_id = remainder[:-5] if live else remainder
        if not task_id or "/" in task_id:
            raise DevFlowError("HTTP_ROUTE_NOT_FOUND", "route is not available")
        values = self._query(query, ("offset", "limit"))
        arguments = {
            "offset": self._integer(values, "offset", 0),
            "limit": self._integer(values, "limit", 50),
        }
        if not live:
            self._send_json(
                HTTPStatus.OK,
                self.server.controller.inspect_task(task_id, **arguments),
            )
            return
        if not LIVE_CAPTURE_SLOT.acquire(blocking=False):
            self._send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                _error("LIVE_CAPTURE_BUSY", "another live observation is active"),
                retry_after=LIVE_RETRY_SECONDS,
            )
            return
        abandoned = threading.Event()
        completed = threading.Event()
        cancellation = _CancellationSignal(self.server.cancel_event, abandoned)
        watcher = threading.Thread(
            target=self._watch_client,
            args=(abandoned, completed),
            daemon=True,
        )
        watcher.start()
        try:
            response = self.server.controller.inspect_live_task(
                task_id,
                cancel_event=cancellation,
                **arguments,
            )
        finally:
            completed.set()
            watcher.join(timeout=0.3)
            LIVE_CAPTURE_SLOT.release()
        self._send_json(HTTPStatus.OK, response)

    def do_GET(self) -> None:
        try:
            path, query = self._target()
            api = path.startswith("/api/")
            if not self._validate_origin(api=api):
                return
            if not api:
                if query or not self._static(path, head_only=False):
                    self._reject(HTTPStatus.NOT_FOUND, "HTTP_ROUTE_NOT_FOUND", "route is not available")
                return
            if not self._authorize():
                return
            self._api(path, query)
        except DevFlowError as exc:
            status = {
                "HTTP_ROUTE_NOT_FOUND": HTTPStatus.NOT_FOUND,
                "TASK_NOT_FOUND": HTTPStatus.NOT_FOUND,
                "VIEW_STALE": HTTPStatus.CONFLICT,
                "VIEW_QUERY_INVALID": HTTPStatus.BAD_REQUEST,
                "HTTP_TARGET_INVALID": HTTPStatus.BAD_REQUEST,
            }.get(exc.code, HTTPStatus.BAD_REQUEST)
            self._reject(status, exc.code, exc.message)
        except (OSError, ValueError):
            self._reject(HTTPStatus.INTERNAL_SERVER_ERROR, "HTTP_RESPONSE_FAILED", "response could not be produced")

    def do_HEAD(self) -> None:
        try:
            path, query = self._target()
            if path.startswith("/api/"):
                self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "HTTP_METHOD_FORBIDDEN", "method is not available")
                return
            if not self._validate_origin(api=False):
                return
            if query or not self._static(path, head_only=True):
                self._reject(HTTPStatus.NOT_FOUND, "HTTP_ROUTE_NOT_FOUND", "route is not available")
        except DevFlowError as exc:
            self._reject(HTTPStatus.BAD_REQUEST, exc.code, exc.message)

    def _method_not_allowed(self) -> None:
        self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "HTTP_METHOD_FORBIDDEN", "method is not available")

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_TRACE = _method_not_allowed
    do_CONNECT = _method_not_allowed


def create_server(
    data_dir: str,
    *,
    port: int = 0,
    token: Optional[str] = None,
    handler_limit: int = DEFAULT_HANDLER_LIMIT,
) -> BoundedThreadingHTTPServer:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise DevFlowError("WEB_PORT_INVALID", "--port must be between 0 and 65535")
    authority = token or secrets.token_urlsafe(32)
    if not isinstance(authority, str) or len(authority) < 32:
        raise DevFlowError("WEB_TOKEN_INVALID", "Web UI authority is invalid")
    try:
        return BoundedThreadingHTTPServer(
            (SERVER_HOST, port),
            WebRequestHandler,
            controller=Controller(data_dir),
            token=authority,
            handler_limit=handler_limit,
        )
    except OSError as exc:
        raise DevFlowError(
            "WEB_BIND_FAILED",
            "loopback Web UI could not bind the requested port",
            details={"port": port},
        ) from exc


def startup_receipt(server: BoundedThreadingHTTPServer) -> dict:
    return {
        "ok": True,
        "command": "web",
        "version": RELEASE_VERSION,
        "product_identity": PRODUCT_IDENTITY,
        "host": SERVER_HOST,
        "port": server.server_port,
        "url": "{}/#token={}".format(server.origin, server.token),
    }


def _serve_server(
    server: BoundedThreadingHTTPServer,
    *,
    stream: Optional[TextIO] = None,
) -> int:
    if stream is not None:
        stream.write(_json_bytes(startup_receipt(server)).decode("utf-8") + "\n")
        stream.flush()
    previous = {}

    def stop(signum: int, frame: object) -> None:
        server.cancel_live_capture()
        threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        if threading.current_thread() is threading.main_thread():
            signals = [signal.SIGINT, signal.SIGTERM]
            if sys.platform == "win32":
                signals.append(signal.SIGBREAK)
            for signum in signals:
                previous[signum] = signal.getsignal(signum)
                signal.signal(signum, stop)
        server.serve_forever(poll_interval=0.1)
    finally:
        server.cancel_live_capture()
        server.server_close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        server.token = ""
    return 0


def run_web(data_dir: str, *, port: int = 0, stream: TextIO = sys.stdout) -> int:
    return _serve_server(create_server(data_dir, port=port), stream=stream)


def _runtime_paths(data_dir: str) -> tuple:
    root = Path(data_dir).expanduser().resolve() / WEB_RUNTIME_DIRECTORY
    return root, root / WEB_RUNTIME_STATE, root / WEB_RUNTIME_LOCK, root / WEB_RUNTIME_LOG


def _read_runtime_state(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise DevFlowError("WEB_RUNTIME_UNSAFE", "Web UI runtime state is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except DevFlowError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise DevFlowError("WEB_RUNTIME_INVALID", "Web UI runtime state is invalid") from exc
    required = ("schema", "instance_id", "pid", "status", "started_at")
    if not isinstance(value, dict) or any(key not in value for key in required):
        raise DevFlowError("WEB_RUNTIME_INVALID", "Web UI runtime state is incomplete")
    if (
        value["schema"] != WEB_RUNTIME_SCHEMA
        or not isinstance(value["instance_id"], str)
        or len(value["instance_id"]) < 24
        or isinstance(value["pid"], bool)
        or not isinstance(value["pid"], int)
        or value["pid"] <= 0
        or value["status"] not in ("starting", "running")
        or not isinstance(value["started_at"], str)
    ):
        raise DevFlowError("WEB_RUNTIME_INVALID", "Web UI runtime state has an unsupported identity")
    if value["status"] == "running":
        if (
            value.get("host") != SERVER_HOST
            or isinstance(value.get("port"), bool)
            or not isinstance(value.get("port"), int)
            or not 0 < value["port"] <= 65535
            or not isinstance(value.get("token"), str)
            or len(value["token"]) < 32
            or value.get("url")
            != "http://{}:{}/#token={}".format(
                SERVER_HOST,
                value["port"],
                value["token"],
            )
        ):
            raise DevFlowError("WEB_RUNTIME_INVALID", "Web UI running state is invalid")
    return value


def _write_runtime_state(path: Path, value: Mapping[str, object]) -> None:
    atomic_write_bytes(path, _json_bytes(value) + b"\n")


def _remove_runtime_state(path: Path, instance_id: Optional[str] = None) -> None:
    state = _read_runtime_state(path)
    if state is None or (instance_id is not None and state["instance_id"] != instance_id):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise DevFlowError("WEB_RUNTIME_WRITE_FAILED", "Web UI runtime state could not be removed") from exc


def _probe_runtime(state: Mapping[str, object]) -> bool:
    if state.get("status") != "running":
        return False
    port = state.get("port")
    token = state.get("token")
    if not isinstance(port, int) or not isinstance(token, str):
        return False
    connection = http.client.HTTPConnection(SERVER_HOST, port, timeout=0.4)
    try:
        connection.request("GET", "/api/meta", headers={"Authorization": "Bearer " + token})
        response = connection.getresponse()
        payload = response.read()
        if response.status != HTTPStatus.OK:
            return False
        body = json.loads(payload.decode("utf-8"))
        return body.get("product_identity") == PRODUCT_IDENTITY
    except (OSError, UnicodeError, ValueError):
        return False
    finally:
        connection.close()


def _runtime_view(state: Optional[Mapping[str, object]], *, action: str) -> dict:
    running = state is not None and _probe_runtime(state)
    result = {
        "ok": True,
        "command": "web",
        "action": action,
        "status": "running" if running else "stopped",
        "version": RELEASE_VERSION,
        "product_identity": PRODUCT_IDENTITY,
    }
    if running:
        for key in ("pid", "host", "port", "url", "started_at"):
            result[key] = state[key]
    return result


def _child_command(data_dir: str, port: int, instance_id: str) -> list:
    entry = Path(sys.argv[0]).resolve()
    if entry.name == "dev_flow.py":
        prefix = [sys.executable, str(entry)]
    else:
        prefix = [sys.executable, "-m", "dev_flow_orchestrator.cli"]
    return prefix + [
        "--data-dir", str(Path(data_dir).expanduser().resolve()),
        "web", "_serve", "--port", str(port), "--instance-id", instance_id,
    ]


def _open_runtime_log(path: Path) -> object:
    if path.is_symlink():
        raise DevFlowError("WEB_RUNTIME_UNSAFE", "Web UI runtime log is not a regular file")
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    if os.name == "nt":
        flags |= os.O_BINARY
    try:
        descriptor = os.open(str(path), flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode) or path.is_symlink():
            os.close(descriptor)
            raise DevFlowError("WEB_RUNTIME_UNSAFE", "Web UI runtime log is not a regular file")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "ab", buffering=0)
    except DevFlowError:
        raise
    except OSError as exc:
        raise DevFlowError("WEB_RUNTIME_WRITE_FAILED", "Web UI runtime log could not be opened") from exc


def _start_web(data_dir: str, port: int) -> dict:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise DevFlowError("WEB_PORT_INVALID", "--port must be between 0 and 65535")
    root, state_path, lock_path, log_path = _runtime_paths(data_dir)
    ensure_private_directory(root)
    instance_id = secrets.token_urlsafe(24)
    with exclusive_file_lock(lock_path):
        current = _read_runtime_state(state_path)
        if current is not None and _probe_runtime(current):
            result = _runtime_view(current, action="start")
            result["already_running"] = True
            return result
        _remove_runtime_state(state_path)
        with _open_runtime_log(log_path) as log:
            kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": log,
                "stderr": log,
                "close_fds": True,
            }
            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                )
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(_child_command(data_dir, port, instance_id), **kwargs)
        _write_runtime_state(state_path, {
            "schema": WEB_RUNTIME_SCHEMA,
            "instance_id": instance_id,
            "pid": process.pid,
            "status": "starting",
            "started_at": _utc_now(),
        })
    deadline = time.monotonic() + WEB_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.05)
        state = _read_runtime_state(state_path)
        if state is not None and state.get("instance_id") == instance_id and _probe_runtime(state):
            return _runtime_view(state, action="start")
        if process.poll() is not None:
            break
    with exclusive_file_lock(lock_path):
        _remove_runtime_state(state_path, instance_id)
    raise DevFlowError(
        "WEB_START_FAILED",
        "managed Web UI did not become ready",
        details={"log": str(log_path)},
    )


def _stop_web(data_dir: str) -> dict:
    root, state_path, lock_path, _ = _runtime_paths(data_dir)
    if not root.exists():
        return _runtime_view(None, action="stop")
    with exclusive_file_lock(lock_path):
        state = _read_runtime_state(state_path)
        if state is None or not _probe_runtime(state):
            _remove_runtime_state(state_path)
            return _runtime_view(None, action="stop")
        pid = state["pid"]
        instance_id = state["instance_id"]
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            _remove_runtime_state(state_path, instance_id)
            return _runtime_view(None, action="stop")
        except OSError as exc:
            raise DevFlowError("WEB_STOP_FAILED", "managed Web UI could not be stopped") from exc
    deadline = time.monotonic() + WEB_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        current = _read_runtime_state(state_path)
        if current is None or current.get("instance_id") != instance_id or not _probe_runtime(current):
            with exclusive_file_lock(lock_path):
                _remove_runtime_state(state_path, instance_id)
            return _runtime_view(None, action="stop")
        time.sleep(0.05)
    raise DevFlowError("WEB_STOP_TIMEOUT", "managed Web UI did not stop in time")


def manage_web(data_dir: str, *, action: str, port: int = 0) -> dict:
    if action == "start":
        return _start_web(data_dir, port)
    if action == "stop":
        return _stop_web(data_dir)
    if action == "restart":
        _stop_web(data_dir)
        result = _start_web(data_dir, port)
        result["action"] = "restart"
        return result
    root, state_path, _, _ = _runtime_paths(data_dir)
    state = _read_runtime_state(state_path) if root.exists() else None
    if state is not None and not _probe_runtime(state):
        state = None
    result = _runtime_view(state, action=action)
    if action == "open" and state is None:
        raise DevFlowError("WEB_NOT_RUNNING", "managed Web UI is not running")
    if action not in ("status", "open"):
        raise DevFlowError("ACTION_UNSUPPORTED", "Web UI action is not implemented")
    return result


def run_web_worker(data_dir: str, *, port: int, instance_id: Optional[str]) -> int:
    if not isinstance(instance_id, str) or len(instance_id) < 24:
        raise DevFlowError("WEB_RUNTIME_INVALID", "managed Web UI instance identity is invalid")
    root, state_path, lock_path, _ = _runtime_paths(data_dir)
    ensure_private_directory(root)
    server = create_server(data_dir, port=port)
    receipt = startup_receipt(server)
    state = {
        "schema": WEB_RUNTIME_SCHEMA,
        "instance_id": instance_id,
        "pid": os.getpid(),
        "status": "running",
        "started_at": _utc_now(),
        **{key: receipt[key] for key in ("host", "port", "url")},
        "token": server.token,
    }
    with exclusive_file_lock(lock_path):
        reserved = _read_runtime_state(state_path)
        if reserved is None or reserved.get("instance_id") != instance_id:
            server.server_close()
            raise DevFlowError("WEB_RUNTIME_CONFLICT", "managed Web UI start reservation was lost")
        _write_runtime_state(state_path, state)
    try:
        return _serve_server(server)
    finally:
        server.server_close()
        with exclusive_file_lock(lock_path):
            _remove_runtime_state(state_path, instance_id)
