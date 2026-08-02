"""Bounded read-only Git evidence through argument-vector subprocess calls.

The controller treats Git output as opaque evidence: ``git status`` is
hashed, never interpreted. Unusual repository states (submodules, LFS,
sparse checkouts, in-progress operations) surface as recorded evidence,
not as detection logic in the runtime.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
from typing import Optional

from .model import DevFlowError


MAX_GIT_OUTPUT_BYTES = 1024 * 1024
GIT_COMMAND_TIMEOUT_SECONDS = 30
GIT_TERMINATE_GRACE_SECONDS = 1
GIT_READ_CHUNK_BYTES = 64 * 1024


class GitClient:
    """Read current repository evidence without mutating Git state."""

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=GIT_TERMINATE_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=GIT_TERMINATE_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, OSError):
            pass

    @staticmethod
    def _run(repository: Path, *arguments: str) -> bytes:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repository),
            *arguments,
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
        except OSError as exc:
            raise DevFlowError(
                "GIT_UNAVAILABLE",
                "Git could not be executed",
                details={"error": str(exc)},
            ) from exc
        stdout = bytearray()
        stderr = bytearray()
        selector = selectors.DefaultSelector()
        deadline = time.monotonic() + GIT_COMMAND_TIMEOUT_SECONDS
        try:
            if process.stdout is None or process.stderr is None:
                GitClient._terminate(process)
                raise DevFlowError(
                    "GIT_UNAVAILABLE",
                    "Git output pipes could not be created",
                )
            selector.register(process.stdout, selectors.EVENT_READ, stdout)
            selector.register(process.stderr, selectors.EVENT_READ, stderr)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    GitClient._terminate(process)
                    raise DevFlowError(
                        "GIT_COMMAND_TIMEOUT",
                        "Git command exceeded the preflight time budget",
                        details={
                            "arguments": list(arguments),
                            "timeout_seconds": GIT_COMMAND_TIMEOUT_SECONDS,
                        },
                    )
                events = selector.select(remaining)
                if not events:
                    GitClient._terminate(process)
                    raise DevFlowError(
                        "GIT_COMMAND_TIMEOUT",
                        "Git command exceeded the preflight time budget",
                        details={
                            "arguments": list(arguments),
                            "timeout_seconds": GIT_COMMAND_TIMEOUT_SECONDS,
                        },
                    )
                for key, _ in events:
                    chunk = os.read(key.fileobj.fileno(), GIT_READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        continue
                    key.data.extend(chunk)
                    if len(stdout) + len(stderr) > MAX_GIT_OUTPUT_BYTES:
                        GitClient._terminate(process)
                        raise DevFlowError(
                            "GIT_OUTPUT_TOO_LARGE",
                            "Git output exceeds the preflight budget",
                            details={
                                "arguments": list(arguments),
                                "limit_bytes": MAX_GIT_OUTPUT_BYTES,
                                "stdout_bytes": len(stdout),
                                "stderr_bytes": len(stderr),
                            },
                        )
            remaining = max(0.0, deadline - time.monotonic())
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                GitClient._terminate(process)
                raise DevFlowError(
                    "GIT_COMMAND_TIMEOUT",
                    "Git command exceeded the preflight time budget",
                    details={
                        "arguments": list(arguments),
                        "timeout_seconds": GIT_COMMAND_TIMEOUT_SECONDS,
                    },
                ) from exc
        except DevFlowError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            GitClient._terminate(process)
            raise DevFlowError(
                "GIT_COMMAND_FAILED",
                "Git evidence collection failed",
                details={
                    "arguments": list(arguments),
                    "error": str(exc),
                },
            ) from exc
        finally:
            selector.close()
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        if returncode != 0:
            raise DevFlowError(
                "GIT_COMMAND_FAILED",
                "required Git evidence is unavailable",
                details={
                    "arguments": list(arguments),
                    "returncode": returncode,
                    "stderr": bytes(stderr).decode(
                        "utf-8",
                        errors="replace",
                    )[:1024],
                },
            )
        return bytes(stdout)

    @classmethod
    def _text(cls, repository: Path, *arguments: str) -> str:
        raw = cls._run(repository, *arguments)
        try:
            return raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise DevFlowError(
                "GIT_OUTPUT_INVALID",
                "required Git output is not UTF-8",
                details={"arguments": list(arguments)},
            ) from exc

    @classmethod
    def inspect(cls, repository_path: str) -> dict:
        supplied = Path(repository_path).expanduser().resolve()
        if not supplied.is_dir():
            raise DevFlowError(
                "REPOSITORY_INVALID",
                "repository path is not a directory",
                details={"path": str(supplied)},
            )
        root = Path(
            cls._text(supplied, "rev-parse", "--show-toplevel")
        ).resolve()
        if root != supplied:
            raise DevFlowError(
                "REPOSITORY_ROOT_REQUIRED",
                "repository path must name the Git worktree root",
                details={"path": str(supplied), "root": str(root)},
            )
        head = cls._text(root, "rev-parse", "HEAD")
        branch: Optional[str]
        try:
            branch = cls._text(
                root,
                "symbolic-ref",
                "--quiet",
                "--short",
                "HEAD",
            )
        except DevFlowError as exc:
            if exc.code != "GIT_COMMAND_FAILED":
                raise
            branch = None
        status = cls._run(
            root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
        git_common = cls._text(root, "rev-parse", "--git-common-dir")
        git_common_path = Path(git_common)
        if not git_common_path.is_absolute():
            git_common_path = root / git_common_path
        return {
            "schema": "dev-flow-v5-git-preflight/v1",
            "repository_root": str(root),
            "git_common_dir": str(git_common_path.resolve()),
            "head": head,
            "branch": branch,
            "clean": not status,
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "status_bytes": len(status),
        }
