#!/usr/bin/env python3
"""Audit shipped runtime imports and prove isolated controller/hook startup."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Iterable, Optional, Sequence, Set


RUNTIME_PATHS = (
    Path("scripts/candidate_identity.py"),
    Path("scripts/dev_flow.py"),
    Path("scripts/__init__.py"),
    Path("scripts/windows_native_validation.py"),
    Path("hooks/dev_flow_hook.py"),
)
PLATFORM_STDLIB_MODULES = {
    "fcntl",
    "grp",
    "msvcrt",
    "nt",
    "posix",
    "pwd",
    "resource",
    "termios",
    "winreg",
}
PACKAGE_INTERNAL_MODULES = {"candidate_identity", "dev_flow", "scripts"}


def _stdlib_names() -> Set[str]:
    declared = getattr(sys, "stdlib_module_names", None)
    if declared is not None:
        return set(declared) | set(sys.builtin_module_names) | PLATFORM_STDLIB_MODULES
    return set(sys.builtin_module_names) | PLATFORM_STDLIB_MODULES


def _resolved_roots(values: Iterable[object]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in values:
        if not isinstance(value, (str, os.PathLike)) or not os.fspath(value):
            continue
        try:
            root = Path(value).resolve()
        except (OSError, TypeError, ValueError):
            continue
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _origin_is_stdlib(
    origin: Path,
    stdlib_roots: Iterable[Path],
    third_party_roots: Iterable[Path],
) -> bool:
    """Classify one module origin without assuming extensions live in Lib/.

    CPython 3.9 on Windows commonly places standard-library extension modules
    in ``<base_prefix>/DLLs``, a sibling of the ``Lib`` directory reported by
    ``sysconfig``.  Third-party roots still take precedence.
    """

    if any(origin.is_relative_to(root) for root in third_party_roots):
        return False
    return any(origin.is_relative_to(root) for root in stdlib_roots)


def _is_stdlib_module(name: str, declared: Set[str]) -> bool:
    if name in declared:
        return True
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
    if spec is None:
        return False
    if spec.origin in {None, "built-in", "frozen"}:
        return True
    configured = sysconfig.get_paths()
    stdlib_roots = _resolved_roots(
        (
            configured.get("stdlib"),
            configured.get("platstdlib"),
            sysconfig.get_config_var("DESTSHARED"),
            Path(sys.base_prefix) / "DLLs",
            Path(sys.exec_prefix) / "DLLs",
        )
    )
    third_party_roots = _resolved_roots(
        (configured.get("purelib"), configured.get("platlib"))
    )
    try:
        origin = Path(spec.origin).resolve()
    except (OSError, TypeError):
        return False
    return _origin_is_stdlib(
        origin,
        stdlib_roots,
        third_party_roots,
    )


def _top_level_imports(path: Path) -> tuple[Set[str], list[str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imports: Set[str] = set()
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
        ):
            errors.append(
                f"{path}:{node.lineno}: dynamic __import__ is not permitted in shipped runtime"
            )
    return imports, errors


def audit_imports(
    paths: Iterable[Path],
    internal_modules: Optional[Set[str]] = None,
) -> list[str]:
    declared = _stdlib_names()
    internal = set(internal_modules or PACKAGE_INTERNAL_MODULES)
    errors: list[str] = []
    for path in paths:
        if not path.is_file():
            errors.append(f"missing shipped runtime file: {path}")
            continue
        try:
            imports, parse_errors = _top_level_imports(path)
        except (OSError, SyntaxError, UnicodeError) as exc:
            errors.append(f"{path}: runtime import audit could not parse file: {exc}")
            continue
        errors.extend(parse_errors)
        for name in sorted(imports):
            if name in internal or _is_stdlib_module(name, declared):
                continue
            errors.append(f"{path}: third-party or unresolved runtime import: {name}")
    return errors


def _isolated_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PLUGIN_ROOT",
        "PLUGIN_DATA",
        "DEV_FLOW_DATA_DIR",
    ):
        environment.pop(key, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def isolated_startup_errors(plugin_root: Path) -> list[str]:
    checks = (
        (
            "controller",
            [sys.executable, "-I", "-S", str(plugin_root / "scripts/dev_flow.py"), "--help"],
            None,
        ),
        (
            "hook",
            [sys.executable, "-I", "-S", str(plugin_root / "hooks/dev_flow_hook.py")],
            b"{}\n",
        ),
        (
            "windows-native-runner",
            [
                sys.executable,
                "-I",
                "-S",
                str(plugin_root / "scripts/windows_native_validation.py"),
                "--help",
            ],
            None,
        ),
    )
    errors: list[str] = []
    for name, command, input_bytes in checks:
        try:
            completed = subprocess.run(
                command,
                cwd=plugin_root,
                env=_isolated_environment(),
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{name}: isolated startup could not run: {exc}")
            continue
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", "backslashreplace").strip()
            errors.append(
                f"{name}: isolated startup exited {completed.returncode}: {stderr}"
            )
    return errors


def validate(plugin_root: Path) -> list[str]:
    paths = [plugin_root / relative for relative in RUNTIME_PATHS]
    return audit_imports(paths) + isolated_startup_errors(plugin_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reject third-party imports in shipped controller/hook runtime files and "
            "start both entry points with Python -I -S."
        )
    )
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="plugin source root (defaults to this script's parent plugin)",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    plugin_root = Path(args.plugin_root).expanduser().resolve()
    errors = validate(plugin_root)
    diagnostic = (
        f"os={platform.system()} python={platform.python_version()} "
        f"root={plugin_root}"
    )
    if errors:
        print(f"Runtime dependency audit failed ({diagnostic}):")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Runtime dependency audit passed ({diagnostic})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
