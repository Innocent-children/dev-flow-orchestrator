"""Shared test support: scratch git repositories and controllers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence
import unittest

from dev_flow_orchestrator.controller import Controller
from dev_flow_orchestrator.runtime_paths import (
    resolve_data_dir,
    resolve_managed_runtime_root,
)


_INHERITED_ENV_ALLOWLIST = (
    "CI",
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_ARCHITEW6432",
    "SYSTEMROOT",
    "SystemRoot",
    "TERM",
    "TZ",
    "WINDIR",
)

_LOCAL_PATH_AUTHORITIES = (
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "CODEX_HOME",
    "DEV_FLOW_DATA_DIR",
    "PLUGIN_DATA",
    "DEV_FLOW_RUNTIME_HOME",
    "DEV_FLOW_SOURCE_ROOT",
    "DEV_FLOW_MARKETPLACE_FILE",
    "DEV_FLOW_BIN_DIR",
    "DEV_FLOW_CODEX_STATE",
    "DEV_FLOW_CODEX_LOG",
    "DEV_FLOW_CODEX_CANDIDATE_ACTIVE",
    "DEV_FLOW_CODEX_ADD_FAIL_ONCE_FILE",
    "DEV_FLOW_CODEX_CORRUPT_LAUNCHER",
    "DEV_FLOW_CODEX_CORRUPT_ONCE_FILE",
    "UV_CACHE_DIR",
    "TMPDIR",
    "TEMP",
    "TMP",
)

_FORBIDDEN_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _host_tool_path() -> tuple[str, ...]:
    directories: list[str] = [
        str(Path(sys.executable).parent),
        str(Path(sys.executable).resolve().parent),
    ]
    for executable in (
        "git",
        "uv",
        "python3",
        "python",
        "powershell.exe",
        "pwsh",
    ):
        resolved = shutil.which(executable)
        if resolved:
            directories.append(str(Path(resolved).parent))
            directories.append(str(Path(resolved).resolve().parent))
    directories.extend(item for item in os.defpath.split(os.pathsep) if item)
    return tuple(dict.fromkeys(directories))


def hermetic_subprocess_env(
    root: Path,
    *,
    path_entries: Sequence[Path | str] = (),
    overrides: Mapping[str, str] | None = None,
    unset: Sequence[str] = (),
) -> dict[str, str]:
    """Build a subprocess environment with test-owned mutable authorities."""

    resolved_root = root.resolve()
    environment = {
        name: os.environ[name]
        for name in _INHERITED_ENV_ALLOWLIST
        if name in os.environ
    }
    home = resolved_root / "home"
    bin_dir = resolved_root / "bin"
    environment.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(resolved_root / "local-app-data"),
            "APPDATA": str(resolved_root / "app-data"),
            "XDG_DATA_HOME": str(resolved_root / "xdg-data"),
            "XDG_CONFIG_HOME": str(resolved_root / "xdg-config"),
            "XDG_CACHE_HOME": str(resolved_root / "xdg-cache"),
            "CODEX_HOME": str(resolved_root / "codex-home"),
            "DEV_FLOW_DATA_DIR": str(resolved_root / "data"),
            "PLUGIN_DATA": str(resolved_root / "plugin-data"),
            "DEV_FLOW_RUNTIME_HOME": str(resolved_root / "managed-runtime"),
            "DEV_FLOW_SOURCE_ROOT": str(resolved_root / "source"),
            "DEV_FLOW_MARKETPLACE_FILE": str(
                resolved_root / "marketplace" / "marketplace.json"
            ),
            "DEV_FLOW_BIN_DIR": str(bin_dir),
            "UV_CACHE_DIR": str(resolved_root / "uv-cache"),
            "TMPDIR": str(resolved_root),
            "TEMP": str(resolved_root),
            "TMP": str(resolved_root),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.pathsep.join(
                dict.fromkeys(
                    [os.fspath(item) for item in path_entries]
                    + [str(bin_dir)]
                    + list(_host_tool_path())
                )
            ),
        }
    )
    if overrides:
        environment.update(overrides)
    for name in unset:
        environment.pop(name, None)

    assert_hermetic_subprocess_env(resolved_root, environment)
    return environment


def assert_hermetic_subprocess_env(
    root: Path,
    environment: Mapping[str, str],
) -> dict[str, Path]:
    """Prove every supported mutable authority resolves below ``root``."""

    resolved_root = root.resolve()
    leaked_git = [name for name in _FORBIDDEN_GIT_REDIRECTS if name in environment]
    if leaked_git:
        raise AssertionError(
            "subprocess environment retains Git redirect authority: {}".format(
                ", ".join(leaked_git)
            )
        )
    for name in _LOCAL_PATH_AUTHORITIES:
        value = environment.get(name)
        if value:
            candidate = Path(value).expanduser().resolve()
            try:
                candidate.relative_to(resolved_root)
            except ValueError as exc:
                raise AssertionError(
                    "{} escapes subprocess fixture root: {}".format(name, candidate)
                ) from exc

    resolved = {
        "data": Path(resolve_data_dir(None, environment=environment)).resolve(),
        "runtime": Path(
            resolve_managed_runtime_root(None, environment=environment)
        ).resolve(),
    }
    for name, candidate in resolved.items():
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise AssertionError(
                "resolved {} root escapes subprocess fixture: {}".format(
                    name, candidate
                )
            ) from exc
    return resolved


def probe_subprocess_runtime_roots(
    root: Path,
    environment: Mapping[str, str],
) -> dict[str, Path]:
    """Resolve data/runtime authorities in a real isolated child process."""

    expected = assert_hermetic_subprocess_env(root, environment)
    source_root = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import json,sys;"
        "sys.path.insert(0,sys.argv[1]);"
        "from dev_flow_orchestrator.runtime_paths import "
        "resolve_data_dir,resolve_managed_runtime_root;"
        "print(json.dumps({'data':resolve_data_dir(),"
        "'runtime':resolve_managed_runtime_root()},sort_keys=True))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-c", code, str(source_root)],
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "subprocess runtime-root probe failed: {}".format(completed.stderr)
        )
    try:
        observed_value = json.loads(completed.stdout)
        observed = {
            name: Path(str(observed_value[name])).resolve()
            for name in ("data", "runtime")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise AssertionError(
            "subprocess runtime-root probe returned invalid JSON: {}".format(
                completed.stdout
            )
        ) from exc
    if observed != expected:
        raise AssertionError(
            "child resolver differs from fixture proof: {!r} != {!r}".format(
                observed, expected
            )
        )
    return observed


def make_repository(root: Path, name: str = "work") -> Path:
    repository = root / name
    repository.mkdir()
    environment = hermetic_subprocess_env(root)
    subprocess.run(
        ["git", "init", "-q", str(repository)],
        check=True,
        env=environment,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "test@local"],
        check=True,
        env=environment,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "Test"],
        check=True,
        env=environment,
    )
    (repository / "a.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repository), "add", "a.txt"],
        check=True,
        env=environment,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "init"],
        check=True,
        env=environment,
    )
    return repository


class RepositoryTestCase(unittest.TestCase):
    """Temporary data dir plus a scratch git repository and controller."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = str(self.root / "data")
        self.repository = make_repository(self.root)
        self.controller = Controller(self.data_dir)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def start_lite(self, requirement: str = "A test requirement") -> str:
        state = self.controller.start(
            requirement=requirement,
            workflow="lite",
            repositories=(str(self.repository),),
        )
        return state.task_id
