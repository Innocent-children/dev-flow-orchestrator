"""Canonical local-path handling for supported hosts."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import Union


PathValue = Union[str, Path]


def _reject_windows_namespace(value: PathValue) -> None:
    spelling = str(value).replace("/", "\\")
    if spelling.startswith("\\\\"):
        raise ValueError("network and extended Windows path namespaces are unsupported")


def _normalized(path: Path) -> Path:
    return Path(os.path.normpath(str(path)))


def canonical_repository_root(value: PathValue) -> Path:
    """Resolve one existing repository root to the host canonical spelling."""
    if os.name == "nt":
        _reject_windows_namespace(value)
    resolved = Path(value).expanduser().resolve(strict=True)
    if os.name == "nt":
        _reject_windows_namespace(resolved)
    return _normalized(resolved)


def canonical_data_root(value: PathValue) -> Path:
    """Resolve a controller root that may not exist yet."""
    if os.name == "nt":
        _reject_windows_namespace(value)
    resolved = Path(value).expanduser().resolve(strict=False)
    if os.name == "nt":
        _reject_windows_namespace(resolved)
    return _normalized(resolved)


def canonical_git_path(value: PathValue, *, repository_root: Path) -> Path:
    """Normalize an absolute or repository-relative path reported by Git."""
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    if os.name == "nt":
        _reject_windows_namespace(candidate)
    resolved = candidate.resolve(strict=True)
    if os.name == "nt":
        _reject_windows_namespace(resolved)
    return _normalized(resolved)


def comparison_key(value: PathValue) -> str:
    spelling = os.path.normpath(str(value))
    return os.path.normcase(spelling) if os.name == "nt" else spelling


def paths_equal(left: PathValue, right: PathValue) -> bool:
    return comparison_key(left) == comparison_key(right)


def path_contains(parent: PathValue, child: PathValue) -> bool:
    """Return whether child is parent or below it; different drives are disjoint."""
    left = comparison_key(parent)
    right = comparison_key(child)
    try:
        return os.path.commonpath((left, right)) == left
    except ValueError:
        return False


def paths_overlap(left: PathValue, right: PathValue) -> bool:
    return path_contains(left, right) or path_contains(right, left)


def path_is_absolute(value: PathValue) -> bool:
    return Path(value).is_absolute()


def windows_comparison_key(value: PathValue) -> str:
    """Pure helper used by platform-focused tests on non-Windows hosts."""
    return ntpath.normcase(ntpath.normpath(str(value)))


def windows_path_contains(parent: PathValue, child: PathValue) -> bool:
    left = windows_comparison_key(parent)
    right = windows_comparison_key(child)
    try:
        return ntpath.commonpath((left, right)) == left
    except ValueError:
        return False
