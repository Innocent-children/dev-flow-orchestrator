#!/usr/bin/env python3
"""Promote a prevalidated immutable release and verify re-downloaded assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence

import release_artifact as artifact


PROMOTION_SCHEMA = "dev-flow-release-promotion/1.0.0"


class PromotionError(RuntimeError):
    """Raised when immutable promotion or final-byte verification fails."""


def _run(
    runner: Callable[..., Any], command: Sequence[str], *, cwd: Path
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PromotionError("promotion command could not run") from exc


def _expected_assets(version: str) -> tuple[str, ...]:
    return (
        "dev-flow-orchestrator-{}.tar.gz".format(version),
        "release-index.json",
        "install.sh",
        "install.ps1",
    )


def _digest(path: Path) -> str:
    return artifact.sha256_file(path)[1]


def _aggregate_inventory_digest(
    entries: Iterable[Mapping[str, object]], prefix: str
) -> str:
    selected = [
        dict(entry)
        for entry in entries
        if str(entry["path"]) == prefix
        or str(entry["path"]).startswith(prefix + "/")
    ]
    return hashlib.sha256(artifact.canonical_json_bytes(selected)).hexdigest()


def validate_asset_set(asset_dir: Path, *, version: str) -> dict[str, object]:
    version = artifact.validate_version(version)
    asset_dir = asset_dir.resolve()
    if not asset_dir.is_dir() or asset_dir.is_symlink():
        raise PromotionError("release asset directory is not a regular directory")
    expected_names = set(_expected_assets(version))
    observed_names = {path.name for path in asset_dir.iterdir()}
    if observed_names != expected_names:
        raise PromotionError("release asset set is incomplete or contains undeclared assets")
    for name in sorted(expected_names):
        path = asset_dir / name
        if not path.is_file() or path.is_symlink():
            raise PromotionError("release asset is not a regular file: {}".format(name))
    index_raw = (asset_dir / "release-index.json").read_bytes()
    index_digest = hashlib.sha256(index_raw).hexdigest()
    archive_name = "dev-flow-orchestrator-{}.tar.gz".format(version)
    index = artifact.verify_release_index_bytes(
        index_raw,
        index_digest,
        artifact.CANONICAL_REPOSITORY,
        version,
        archive_name,
    )
    with tempfile.TemporaryDirectory(prefix="dev-flow-promotion-validate-") as temporary_name:
        verified = artifact.inspect_and_extract_artifact(
            asset_dir / archive_name,
            Path(temporary_name).resolve() / "extracted",
            index,
        )
        root = Path(str(verified["root"]))
        inventory = verified["inventory"]
        if not isinstance(inventory, list):
            raise PromotionError("verified release inventory is unavailable")
        component_digests = {
            "index": index_digest,
            "archive": _digest(asset_dir / archive_name),
            "manifest": str(verified["manifest_sha256"]),
            "wheel": _digest(Path(str(verified["topology"]["wheel_path"]))),
            "requirements": _digest(root / "runtime-requirements.txt"),
            "lock": _digest(root / "uv.lock"),
            "plugin": _aggregate_inventory_digest(inventory, "plugin"),
            "lifecycle": _aggregate_inventory_digest(inventory, "lifecycle"),
            "install_sh": _digest(asset_dir / "install.sh"),
            "install_ps1": _digest(asset_dir / "install.ps1"),
        }
    # Each bootstrap is itself an identity-bound release asset. This is a
    # static contract check; executing it belongs to native lifecycle gates.
    for name in ("install.sh", "install.ps1"):
        document = (asset_dir / name).read_text(encoding="utf-8")
        for literal in (
            artifact.CANONICAL_REPOSITORY,
            version,
            archive_name,
            index_digest,
        ):
            if literal not in document:
                raise PromotionError("{} is not version-matched".format(name))
    return {
        "version": version,
        "source_commit": index["source_commit"],
        "source_tree": index["source_tree"],
        "release_id": verified["release_id"],
        "asset_digests": {
            name: _digest(asset_dir / name) for name in sorted(expected_names)
        },
        "component_digests": component_digests,
    }


def _default_downloader(url: str, destination: Path, maximum: int) -> None:
    artifact._download(url, destination, maximum=maximum)


def promote_release(
    asset_dir: Path,
    *,
    version: str,
    repository: str = artifact.CANONICAL_REPOSITORY,
    runner: Callable[..., Any] = subprocess.run,
    downloader: Callable[[str, Path, int], None] = _default_downloader,
) -> dict[str, object]:
    """Upload once, then verify exact version-specific final asset bytes."""

    if repository != artifact.CANONICAL_REPOSITORY:
        raise PromotionError("promotion repository is not canonical")
    # Validate all four local assets before the first external mutation.
    local = validate_asset_set(asset_dir, version=version)
    tag = "v{}".format(version)
    probe = _run(
        runner,
        ["gh", "api", "repos/{}/releases/tags/{}".format(repository, tag), "--silent"],
        cwd=asset_dir,
    )
    if probe.returncode == 0:
        raise PromotionError("release version already exists; overwrite is refused")
    diagnostic = (probe.stderr or "").lower()
    if "404" not in diagnostic and "not found" not in diagnostic:
        raise PromotionError("same-version release absence could not be proven")
    asset_paths = [str(asset_dir / name) for name in _expected_assets(version)]
    created = _run(
        runner,
        [
            "gh",
            "release",
            "create",
            tag,
            *asset_paths,
            "--repo",
            repository,
            "--verify-tag",
            "--title",
            "Dev Flow Orchestrator {}".format(version),
        ],
        cwd=asset_dir,
    )
    if created.returncode != 0:
        raise PromotionError("explicit release upload failed: {}".format(created.stderr.strip()))
    base_url = "https://github.com/{}/releases/download/{}/".format(repository, tag)
    with tempfile.TemporaryDirectory(prefix="dev-flow-promotion-download-") as temporary_name:
        downloaded = Path(temporary_name).resolve() / "assets"
        downloaded.mkdir()
        for name in _expected_assets(version):
            local_path = asset_dir / name
            maximum = max(local_path.stat().st_size, 1)
            downloader(base_url + name, downloaded / name, maximum)
        final = validate_asset_set(downloaded, version=version)
        if final["asset_digests"] != local["asset_digests"]:
            raise PromotionError("re-downloaded release assets differ from uploaded bytes")
        if final["component_digests"] != local["component_digests"]:
            raise PromotionError("re-downloaded release component identity differs")
    return {
        "schema": PROMOTION_SCHEMA,
        "repository": repository,
        "tag": tag,
        "version": version,
        "source_commit": final["source_commit"],
        "source_tree": final["source_tree"],
        "release_id": final["release_id"],
        "asset_digests": final["asset_digests"],
        "component_digests": final["component_digests"],
        "redownloaded": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--record", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.record.exists() or arguments.record.is_symlink():
            raise PromotionError("promotion record already exists")
        result = promote_release(arguments.asset_dir.resolve(), version=arguments.version)
        arguments.record.parent.mkdir(parents=True, exist_ok=True)
        with arguments.record.open("xb") as output:
            output.write(artifact.canonical_json_bytes(result))
    except (OSError, ValueError, PromotionError, artifact.ReleaseArtifactError) as exc:
        print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "record": str(arguments.record), **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
