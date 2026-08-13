#!/usr/bin/env python3
"""Update the distributable release version without changing model protocols."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
VERSION_ASSIGNMENT = re.compile(
    r'(?m)^RELEASE_VERSION = "(?P<version>[^"]+)"$'
)
PROJECT_VERSION = re.compile(
    r'(?m)^(\[project\]\nname = "dev-flow-orchestrator"\nversion = ")(?P<version>[^"]+)(")'
)
LOCK_VERSION = re.compile(
    r'(?m)^(\[\[package\]\]\nname = "dev-flow-orchestrator"\nversion = ")(?P<version>[^"]+)(")'
)
CORE_RELEASE_FILES = (
    "src/dev_flow_orchestrator/_version.py",
    ".codex-plugin/plugin.json",
    "pyproject.toml",
    "uv.lock",
)
# Public English sources precede their synchronized Chinese translations.
CURRENT_RELEASE_REFERENCE_FILES = (
    "README.md",
    "README_CN.md",
    "ARCHITECTURE.md",
    "ARCHITECTURE_CN.md",
    "ROADMAP.md",
    "ROADMAP_CN.md",
    "INSTALL.md",
    "INSTALL_CN.md",
    "docs/PROMOTION.md",
    "scripts/validate_installed_stage1.py",
    "tests/test_installed_journeys.py",
    "tests/test_mcp_runtime.py",
    "tests/test_web_ui_product_identity.py",
)
MANAGED_RELEASE_FILES = CORE_RELEASE_FILES + CURRENT_RELEASE_REFERENCE_FILES


class VersionError(RuntimeError):
    pass


def _replace_exact(document: str, pattern: re.Pattern[str], version: str, label: str) -> str:
    matches = tuple(pattern.finditer(document))
    if len(matches) != 1:
        raise VersionError("{} must contain exactly one release version".format(label))
    match = matches[0]
    if pattern is VERSION_ASSIGNMENT:
        return document[: match.start("version")] + version + document[match.end("version") :]
    return document[: match.start("version")] + version + document[match.end("version") :]


def _read_release_version(root: Path) -> str:
    document = (root / "src/dev_flow_orchestrator/_version.py").read_text(encoding="utf-8")
    matches = tuple(VERSION_ASSIGNMENT.finditer(document))
    if len(matches) != 1:
        raise VersionError("_version.py must contain exactly one RELEASE_VERSION")
    value = matches[0].group("version")
    if SEMVER.fullmatch(value) is None:
        raise VersionError("current release version is not semantic")
    return value


def _tracked_release_reference_paths(root: Path, version: str) -> tuple[str, ...]:
    if not (root / ".git").exists():
        return ()
    try:
        completed = subprocess.run(
            ["git", "grep", "-l", "-z", "-F", "-e", version, "--", "."],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VersionError("tracked release reference lookup could not run") from exc
    if completed.returncode not in (0, 1):
        diagnostic = completed.stderr.strip()
        suffix = ": " + diagnostic if diagnostic else ""
        raise VersionError("tracked release reference lookup failed" + suffix)
    return tuple(
        Path(value).as_posix()
        for value in completed.stdout.split("\0")
        if value
    )


def _require_managed_release_references(root: Path, version: str) -> None:
    observed = set(_tracked_release_reference_paths(root, version))
    unmanaged = sorted(observed.difference(MANAGED_RELEASE_FILES))
    if unmanaged:
        raise VersionError(
            "current release version occurs in unmanaged tracked files: {}".format(
                ", ".join(unmanaged)
            )
        )


def _candidate_documents(
    root: Path,
    current_version: str,
    version: str,
) -> Mapping[Path, str]:
    version_path = root / "src/dev_flow_orchestrator/_version.py"
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "uv.lock"
    manifest_path = root / ".codex-plugin/plugin.json"
    version_document = version_path.read_text(encoding="utf-8")
    pyproject = pyproject_path.read_text(encoding="utf-8")
    lock = lock_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise VersionError("plugin manifest version is invalid")
    manifest["version"] = version
    documents = {
        version_path: _replace_exact(version_document, VERSION_ASSIGNMENT, version, "_version.py"),
        pyproject_path: _replace_exact(pyproject, PROJECT_VERSION, version, "pyproject.toml"),
        lock_path: _replace_exact(lock, LOCK_VERSION, version, "uv.lock"),
        manifest_path: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    for relative in CURRENT_RELEASE_REFERENCE_FILES:
        path = root / relative
        document = path.read_text(encoding="utf-8")
        if current_version not in document:
            raise VersionError(
                "{} must contain the current release version".format(relative)
            )
        documents[path] = document.replace(current_version, version)
    return documents


def _atomic_write(path: Path, document: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".version-", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_release_files(root: Path) -> str:
    release = _read_release_version(root)
    manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    observed = {
        "_version.py": release,
        "plugin.json": manifest.get("version") if isinstance(manifest, dict) else None,
        "pyproject.toml": next(iter(PROJECT_VERSION.finditer(pyproject)), None),
        "uv.lock": next(iter(LOCK_VERSION.finditer(lock)), None),
    }
    normalized = {
        key: value.group("version") if isinstance(value, re.Match) else value
        for key, value in observed.items()
    }
    if any(value != release for value in normalized.values()):
        raise VersionError("release versions differ: {}".format(normalized))
    missing_references = tuple(
        relative
        for relative in CURRENT_RELEASE_REFERENCE_FILES
        if release not in (root / relative).read_text(encoding="utf-8")
    )
    if missing_references:
        raise VersionError(
            "current release version is missing from managed files: {}".format(
                ", ".join(missing_references)
            )
        )
    return release


def bump(root: Path, version: str) -> tuple[str, ...]:
    if SEMVER.fullmatch(version) is None:
        raise VersionError("release version must be MAJOR.MINOR.PATCH without a prefix")
    current_version = validate_release_files(root)
    _require_managed_release_references(root, current_version)
    documents = _candidate_documents(root, current_version, version)
    changed = tuple(path for path, document in documents.items() if path.read_text(encoding="utf-8") != document)
    for path in changed:
        _atomic_write(path, documents[path])
    validate_release_files(root)
    return tuple(path.relative_to(root).as_posix() for path in changed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="new release version")
    parser.add_argument("--check", action="store_true", help="validate release metadata without writing")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    root = arguments.root.expanduser().resolve()
    try:
        if arguments.check:
            if arguments.version is not None:
                raise VersionError("--check does not accept a new version")
            release = validate_release_files(root)
            result = {"changed": [], "ok": True, "release_version": release}
        else:
            if arguments.version is None:
                raise VersionError("a release version is required")
            changed = bump(root, arguments.version)
            result = {
                "changed": list(changed),
                "ok": True,
                "release_version": arguments.version,
            }
    except (OSError, ValueError, VersionError) as exc:
        print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
