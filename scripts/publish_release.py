#!/usr/bin/env python3
"""Build, tag, and publish one immutable Dev Flow release."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence

import build_release
import bump_version
import promote_release
import release_artifact as artifact


REMOTE_NAME = "origin"
COMPARE_CHUNK_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_CHARACTERS = 2048
_OID = re.compile(r"^[0-9a-f]{40}$")
_CANONICAL_ORIGIN_URLS = frozenset(
    {
        "git@github.com:{}.git".format(artifact.CANONICAL_REPOSITORY),
        "https://github.com/{}".format(artifact.CANONICAL_REPOSITORY),
        "https://github.com/{}.git".format(artifact.CANONICAL_REPOSITORY),
        "ssh://git@github.com/{}.git".format(artifact.CANONICAL_REPOSITORY),
    }
)


class PublishReleaseError(RuntimeError):
    """Raised when the one-command release cannot preserve exact identity."""


def _invoke(
    runner: Callable[..., Any],
    command: Sequence[str],
    *,
    cwd: Path,
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
        raise PublishReleaseError("command could not run: {}".format(command[0])) from exc


def _require(
    runner: Callable[..., Any],
    command: Sequence[str],
    *,
    cwd: Path,
    label: str,
) -> subprocess.CompletedProcess[str]:
    completed = _invoke(runner, command, cwd=cwd)
    if completed.returncode != 0:
        diagnostic = str(completed.stderr or "").strip()[:MAX_DIAGNOSTIC_CHARACTERS]
        suffix = ": " + diagnostic if diagnostic else ""
        raise PublishReleaseError(label + " failed" + suffix)
    return completed


def _oid(value: object, label: str) -> str:
    if not isinstance(value, str) or not _OID.fullmatch(value):
        raise PublishReleaseError(label + " is not a full Git object ID")
    return value


def _head_identity(root: Path, runner: Callable[..., Any]) -> tuple[str, str]:
    commit = _require(
        runner,
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        label="HEAD lookup",
    ).stdout.strip()
    tree = _require(
        runner,
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        label="HEAD tree lookup",
    ).stdout.strip()
    return _oid(commit, "HEAD"), _oid(tree, "HEAD tree")


def _require_clean_source(root: Path, runner: Callable[..., Any]) -> None:
    status = _require(
        runner,
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        label="source status lookup",
    ).stdout
    if status.strip():
        raise PublishReleaseError("release source has tracked or untracked changes")


def _require_canonical_origin(root: Path, runner: Callable[..., Any]) -> None:
    origin = _require(
        runner,
        ["git", "remote", "get-url", "--push", REMOTE_NAME],
        cwd=root,
        label="origin lookup",
    ).stdout.strip()
    if origin not in _CANONICAL_ORIGIN_URLS:
        raise PublishReleaseError("origin does not identify the canonical GitHub repository")


def _local_tag_commit(
    root: Path,
    tag: str,
    runner: Callable[..., Any],
) -> str | None:
    reference = "refs/tags/" + tag
    exists = _invoke(
        runner,
        ["git", "show-ref", "--verify", "--quiet", reference],
        cwd=root,
    )
    if exists.returncode == 1:
        return None
    if exists.returncode != 0:
        raise PublishReleaseError("local release tag lookup failed")
    commit = _require(
        runner,
        ["git", "rev-parse", "{}^{{commit}}".format(tag)],
        cwd=root,
        label="local release tag resolution",
    ).stdout.strip()
    return _oid(commit, "local release tag")


def _remote_tag_commit(
    root: Path,
    tag: str,
    runner: Callable[..., Any],
) -> str | None:
    reference = "refs/tags/" + tag
    output = _require(
        runner,
        ["git", "ls-remote", "--tags", REMOTE_NAME, reference, reference + "^{}"],
        cwd=root,
        label="remote release tag lookup",
    ).stdout
    observed: dict[str, str] = {}
    for raw_line in output.splitlines():
        fields = raw_line.split()
        if len(fields) != 2 or fields[1] not in {reference, reference + "^{}"}:
            raise PublishReleaseError("remote release tag lookup returned invalid output")
        value = _oid(fields[0], "remote release tag")
        previous = observed.get(fields[1])
        if previous is not None and previous != value:
            raise PublishReleaseError("remote release tag lookup is ambiguous")
        observed[fields[1]] = value
    if not observed:
        return None
    direct = observed.get(reference)
    if direct is None:
        raise PublishReleaseError("remote release tag is missing its direct reference")
    return observed.get(reference + "^{}", direct)


def _ensure_local_tag(
    root: Path,
    tag: str,
    commit: str,
    runner: Callable[..., Any],
) -> bool:
    observed = _local_tag_commit(root, tag, runner)
    if observed is not None:
        if observed != commit:
            raise PublishReleaseError("local release tag points to another commit")
        return False
    _require(
        runner,
        ["git", "tag", tag, commit],
        cwd=root,
        label="local release tag creation",
    )
    if _local_tag_commit(root, tag, runner) != commit:
        raise PublishReleaseError("created local release tag cannot be proven")
    return True


def _ensure_remote_tag(
    root: Path,
    tag: str,
    commit: str,
    runner: Callable[..., Any],
) -> bool:
    observed = _remote_tag_commit(root, tag, runner)
    if observed is not None:
        if observed != commit:
            raise PublishReleaseError("remote release tag points to another commit")
        return False
    reference = "refs/tags/" + tag
    _require(
        runner,
        ["git", "push", REMOTE_NAME, reference + ":" + reference],
        cwd=root,
        label="remote release tag push",
    )
    if _remote_tag_commit(root, tag, runner) != commit:
        raise PublishReleaseError("pushed remote release tag cannot be proven")
    return True


def _prepare_build_checkout(
    root: Path,
    checkout: Path,
    *,
    tag: str,
    commit: str,
    runner: Callable[..., Any],
) -> None:
    _require(
        runner,
        [
            "git",
            "clone",
            "--local",
            "--no-hardlinks",
            "--no-checkout",
            str(root),
            str(checkout),
        ],
        cwd=root.parent,
        label="clean release checkout creation",
    )
    _require(
        runner,
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "checkout",
            "--detach",
            commit,
        ],
        cwd=checkout,
        label="clean release checkout selection",
    )
    if _head_identity(checkout, runner)[0] != commit:
        raise PublishReleaseError("clean release checkout differs from the selected commit")
    _ensure_local_tag(checkout, tag, commit, runner)


def _files_equal(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open("rb") as left_stream, right.open("rb") as right_stream:
        while True:
            left_chunk = left_stream.read(COMPARE_CHUNK_BYTES)
            right_chunk = right_stream.read(COMPARE_CHUNK_BYTES)
            if left_chunk != right_chunk:
                return False
            if not left_chunk:
                return True


def compare_asset_sets(
    first: Path,
    second: Path,
    *,
    version: str,
) -> dict[str, object]:
    first_identity = promote_release.validate_asset_set(first, version=version)
    second_identity = promote_release.validate_asset_set(second, version=version)
    identity_fields = (
        "asset_digests",
        "component_digests",
        "source_commit",
        "source_tree",
        "release_id",
    )
    if any(first_identity[field] != second_identity[field] for field in identity_fields):
        raise PublishReleaseError("double-build release identities differ")
    for name in sorted(first_identity["asset_digests"]):
        if not _files_equal(first / name, second / name):
            raise PublishReleaseError("double-build release bytes differ: " + name)
    return first_identity


def _default_record_path(version: str) -> Path:
    return Path(tempfile.gettempdir()).resolve() / (
        "dev-flow-promotion-{}.json".format(version)
    )


def publish_release(
    root: Path,
    version: str,
    *,
    record_path: Path | None = None,
    runner: Callable[..., Any] = subprocess.run,
    builder: Callable[..., Mapping[str, object]] = build_release.build_release,
    promoter: Callable[..., Mapping[str, object]] = promote_release.promote_release,
) -> dict[str, object]:
    root = root.resolve(strict=True)
    version = artifact.validate_version(version)
    observed_version = bump_version.validate_release_files(root)
    if observed_version != version:
        raise PublishReleaseError("requested version differs from release metadata")
    _require_clean_source(root, runner)
    _require_canonical_origin(root, runner)
    commit, tree = _head_identity(root, runner)
    tag = "v" + version
    local_before = _local_tag_commit(root, tag, runner)
    if local_before is not None and local_before != commit:
        raise PublishReleaseError("local release tag points to another commit")
    remote_before = _remote_tag_commit(root, tag, runner)
    if remote_before is not None and remote_before != commit:
        raise PublishReleaseError("remote release tag points to another commit")
    _require(
        runner,
        ["gh", "auth", "status", "--hostname", "github.com"],
        cwd=root,
        label="GitHub authentication preflight",
    )

    record = Path(os.path.abspath(record_path or _default_record_path(version)))
    if record == root or root in record.parents:
        raise PublishReleaseError("promotion record must remain outside the repository")
    with tempfile.TemporaryDirectory(prefix="dev-flow-publish-{}-".format(version)) as name:
        temporary = Path(name).resolve()
        checkout = temporary / "source"
        _prepare_build_checkout(
            root,
            checkout,
            tag=tag,
            commit=commit,
            runner=runner,
        )
        first = temporary / "first"
        second = temporary / "second"
        builder(checkout, first, version=version, runner=runner)
        builder(checkout, second, version=version, runner=runner)
        candidate = compare_asset_sets(first, second, version=version)
        if candidate["source_commit"] != commit or candidate["source_tree"] != tree:
            raise PublishReleaseError("built release source identity differs from HEAD")

        _require_clean_source(root, runner)
        if bump_version.validate_release_files(root) != version:
            raise PublishReleaseError("release metadata changed during the build")
        if _head_identity(root, runner) != (commit, tree):
            raise PublishReleaseError("HEAD changed during the build")
        created_local_tag = _ensure_local_tag(root, tag, commit, runner)
        pushed_remote_tag = _ensure_remote_tag(root, tag, commit, runner)
        promotion = promoter(
            first,
            version=version,
            journal_path=record,
        )

    if promotion.get("phase") != "published" or promotion.get("published") is not True:
        raise PublishReleaseError("promotion did not prove a published release")
    return {
        "version": version,
        "tag": tag,
        "source_commit": commit,
        "source_tree": tree,
        "created_local_tag": created_local_tag,
        "pushed_remote_tag": pushed_remote_tag,
        "release_id": promotion["release_id"],
        "release_url": "https://github.com/{}/releases/tag/{}".format(
            artifact.CANONICAL_REPOSITORY,
            tag,
        ),
        "assets": sorted(candidate["asset_digests"]),
        "record": str(record),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--record", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    record: Path | None = arguments.record
    try:
        version = artifact.validate_version(arguments.version)
        record = Path(os.path.abspath(record or _default_record_path(version)))
        result = publish_release(
            arguments.root,
            version,
            record_path=record,
        )
    except (
        OSError,
        ValueError,
        artifact.ReleaseArtifactError,
        build_release.ReleaseBuildError,
        bump_version.VersionError,
        promote_release.PromotionError,
        PublishReleaseError,
    ) as exc:
        payload: dict[str, object] = {"error": str(exc), "ok": False}
        if record is not None:
            payload["record"] = str(record)
        print(json.dumps(payload, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
