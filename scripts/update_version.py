#!/usr/bin/env python3
"""Update all checked-in current-release references to one required version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import bump_version


ROOT = Path(__file__).resolve().parents[1]


def update_version(root: Path, version: str) -> dict[str, object]:
    root = root.expanduser().resolve(strict=True)
    previous_version = bump_version.validate_release_files(root)
    changed = bump_version.bump(root, version)
    return {
        "changed": list(changed),
        "previous_version": previous_version,
        "release_version": version,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--version",
        required=True,
        help="new release version in MAJOR.MINOR.PATCH form",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = update_version(arguments.root, arguments.version)
    except (OSError, ValueError, bump_version.VersionError) as exc:
        print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
