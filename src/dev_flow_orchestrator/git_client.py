"""Bounded macOS Git evidence through argument-vector subprocess calls."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
from typing import Mapping, Optional

from .model import DevFlowError


MAX_GIT_OUTPUT_BYTES = 1024 * 1024


class GitClient:
    """Read current repository evidence without mutating Git state."""

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
        }
        command = ["git", "-C", str(repository), *arguments]
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                env=environment,
            )
        except OSError as exc:
            raise DevFlowError(
                "GIT_UNAVAILABLE",
                "Git could not be executed",
                details={"error": str(exc)},
            ) from exc
        if (
            len(completed.stdout) > MAX_GIT_OUTPUT_BYTES
            or len(completed.stderr) > MAX_GIT_OUTPUT_BYTES
        ):
            raise DevFlowError(
                "GIT_OUTPUT_TOO_LARGE",
                "Git output exceeds the preflight budget",
            )
        if completed.returncode != 0:
            raise DevFlowError(
                "GIT_COMMAND_FAILED",
                "required Git evidence is unavailable",
                details={
                    "arguments": list(arguments),
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.decode(
                        "utf-8",
                        errors="replace",
                    )[:1024],
                },
            )
        return completed.stdout

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
            "schema": "dev-flow-v4-git-preflight/v1",
            "repository_root": str(root),
            "git_common_dir": str(git_common_path.resolve()),
            "head": head,
            "branch": branch,
            "clean": not status,
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "status_bytes": len(status),
        }

    @classmethod
    def prepare_workspace(
        cls,
        repository_path: str,
        strategy: str,
        destination: Path,
        expected_head: object,
    ) -> dict:
        evidence = cls.inspect(repository_path)
        if (
            not isinstance(expected_head, str)
            or evidence["head"] != expected_head
        ):
            raise DevFlowError(
                "REPOSITORY_DRIFT",
                "repository HEAD changed after preflight",
                details={
                    "expected_head": expected_head,
                    "observed_head": evidence["head"],
                },
            )
        if strategy == "in-place":
            workspace_path = evidence["repository_root"]
        elif strategy == "branch":
            if evidence["branch"] is None:
                raise DevFlowError(
                    "WORKSPACE_BRANCH_REQUIRED",
                    "branch workspace requires a named current branch",
                )
            workspace_path = evidence["repository_root"]
        elif strategy == "worktree":
            if destination.exists():
                raise DevFlowError(
                    "WORKSPACE_EXISTS",
                    "managed worktree destination already exists",
                    details={"path": str(destination)},
                )
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(destination.parent, 0o700)
            cls._run(
                Path(repository_path),
                "worktree",
                "add",
                "--detach",
                str(destination),
                evidence["head"],
            )
            workspace_path = str(destination.resolve())
        else:
            raise DevFlowError(
                "WORKSPACE_STRATEGY_INVALID",
                "workspace strategy is not supported",
                details={"workspace_strategy": strategy},
            )
        return {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "strategy": strategy,
            "path": workspace_path,
            "head": evidence["head"],
            "branch": evidence["branch"],
        }

    @classmethod
    def observe_workspace(cls, request: Mapping[str, object]) -> dict:
        repository_path = request.get("repository_path")
        strategy = request.get("strategy")
        destination = request.get("destination")
        expected_head = request.get("expected_head")
        if not all(
            isinstance(value, str)
            for value in (
                repository_path,
                strategy,
                destination,
                expected_head,
            )
        ):
            raise DevFlowError(
                "EFFECT_REQUEST_INVALID",
                "workspace observation request is incomplete",
            )
        observed_path = (
            destination
            if strategy == "worktree"
            else repository_path
        )
        evidence = cls.inspect(observed_path)
        if evidence["head"] != expected_head:
            raise DevFlowError(
                "EFFECT_OBSERVATION_MISMATCH",
                "workspace HEAD does not match the claimed effect",
            )
        return {
            "schema": "dev-flow-v4-workspace-receipt/v1",
            "strategy": strategy,
            "path": evidence["repository_root"],
            "head": evidence["head"],
            "branch": evidence["branch"],
        }

    @classmethod
    def workspace_effect_absent(cls, request: Mapping[str, object]) -> bool:
        strategy = request.get("strategy")
        if strategy in {"in-place", "branch"}:
            return True
        repository_path = request.get("repository_path")
        destination = request.get("destination")
        if not isinstance(repository_path, str) or not isinstance(destination, str):
            raise DevFlowError(
                "EFFECT_REQUEST_INVALID",
                "workspace absence request is incomplete",
            )
        destination_path = Path(destination).resolve()
        if destination_path.exists():
            return False
        listing = cls._text(
            Path(repository_path),
            "worktree",
            "list",
            "--porcelain",
        )
        registered = {
            str(Path(line[len("worktree ") :]).resolve())
            for line in listing.splitlines()
            if line.startswith("worktree ")
        }
        return str(destination_path) not in registered
