#!/usr/bin/env python3
"""Promote a prevalidated immutable release and verify re-downloaded assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence

import release_artifact as artifact


PROMOTION_SCHEMA = "dev-flow-release-promotion/1.0.0"
MAX_PROMOTION_RECORD_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_CHARACTERS = 2048
_PHASES = (
    "local_validated",
    "remote_identity_verified",
    "draft_created",
    "assets_uploaded",
    "remote_verified",
    "published",
)
_JOURNAL_FIELDS = {
    "schema",
    "repository",
    "tag",
    "version",
    "source_commit",
    "source_tree",
    "release_id",
    "local_asset_digests",
    "local_component_digests",
    "phase",
    "draft_release_id",
    "uploaded_assets",
    "final_asset_digests",
    "final_component_digests",
    "redownloaded",
    "published",
    "diagnostic",
}


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


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise PromotionError("promotion journal contains a duplicate field")
        value[key] = item
    return value


def _phase_at_least(journal: Mapping[str, object], phase: str) -> bool:
    return _PHASES.index(str(journal["phase"])) >= _PHASES.index(phase)


def _write_journal(path: Path, journal: Mapping[str, object]) -> None:
    raw = artifact.canonical_json_bytes(dict(journal))
    if len(raw) > MAX_PROMOTION_RECORD_BYTES:
        raise PromotionError("promotion journal exceeds its fixed byte cap")
    path = Path(os.path.abspath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PromotionError("promotion journal path is unsafe")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="." + path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        if path.is_symlink():
            raise PromotionError("promotion journal path became unsafe")
        os.replace(temporary, path)
        try:
            directory = os.open(
                str(path.parent),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
        except OSError:
            directory = None
        if directory is not None:
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _load_journal(path: Path) -> dict[str, object]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not path.is_file() or metadata.st_size > MAX_PROMOTION_RECORD_BYTES:
            raise PromotionError("promotion journal is unsafe or exceeds its fixed byte cap")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
    except PromotionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromotionError("promotion journal is not bounded strict UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != _JOURNAL_FIELDS:
        raise PromotionError("promotion journal fields are invalid")
    if value.get("schema") != PROMOTION_SCHEMA or value.get("phase") not in _PHASES:
        raise PromotionError("promotion journal schema or phase is invalid")
    if not isinstance(value.get("uploaded_assets"), dict):
        raise PromotionError("promotion journal uploaded asset identities are invalid")
    if any(
        not isinstance(name, str)
        or isinstance(asset_id, bool)
        or not isinstance(asset_id, int)
        or asset_id <= 0
        for name, asset_id in value["uploaded_assets"].items()
    ):
        raise PromotionError("promotion journal uploaded asset identities are invalid")
    for field in (
        "local_asset_digests",
        "local_component_digests",
    ):
        if not isinstance(value.get(field), dict):
            raise PromotionError("promotion journal digest identity is invalid")
    for field in ("final_asset_digests", "final_component_digests"):
        if value.get(field) is not None and not isinstance(value.get(field), dict):
            raise PromotionError("promotion journal final digest identity is invalid")
    if value.get("draft_release_id") is not None and (
        isinstance(value["draft_release_id"], bool)
        or not isinstance(value["draft_release_id"], int)
        or int(value["draft_release_id"]) <= 0
    ):
        raise PromotionError("promotion journal release ID is invalid")
    if not isinstance(value.get("redownloaded"), bool) or not isinstance(
        value.get("published"), bool
    ):
        raise PromotionError("promotion journal completion flags are invalid")
    diagnostic = value.get("diagnostic")
    if diagnostic is not None and (
        not isinstance(diagnostic, str)
        or len(diagnostic) > MAX_DIAGNOSTIC_CHARACTERS
    ):
        raise PromotionError("promotion journal diagnostic is invalid")
    return value


class GitHubReleaseAPI:
    """Small authenticated official GitHub interface used by promotion."""

    def __init__(
        self,
        repository: str,
        cwd: Path,
        runner: Callable[..., Any],
    ) -> None:
        self.repository = repository
        self.cwd = cwd
        self.runner = runner

    def _json(self, command: Sequence[str], label: str) -> dict[str, object]:
        completed = _run(self.runner, command, cwd=self.cwd)
        if completed.returncode != 0:
            raise PromotionError("{} failed: {}".format(label, completed.stderr.strip()))
        try:
            value = json.loads(completed.stdout, object_pairs_hook=_strict_object)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PromotionError(label + " returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PromotionError(label + " returned a non-object response")
        return value

    def tag_identity(self, tag: str) -> tuple[str, str]:
        reference = self._json(
            [
                "gh",
                "api",
                "repos/{}/git/ref/tags/{}".format(self.repository, tag),
            ],
            "remote tag reference lookup",
        )
        reference_object = reference.get("object")
        if (
            reference.get("ref") != "refs/tags/" + tag
            or not isinstance(reference_object, dict)
            or reference_object.get("type") not in {"commit", "tag"}
            or not isinstance(reference_object.get("sha"), str)
            or len(str(reference_object["sha"])) != 40
        ):
            raise PromotionError("remote tag reference identity is invalid")
        value = self._json(
            ["gh", "api", "repos/{}/commits/{}".format(self.repository, tag)],
            "remote tag identity lookup",
        )
        commit = value.get("sha")
        commit_model = value.get("commit")
        tree_model = commit_model.get("tree") if isinstance(commit_model, dict) else None
        tree = tree_model.get("sha") if isinstance(tree_model, dict) else None
        if (
            not isinstance(commit, str)
            or not isinstance(tree, str)
            or len(commit) != 40
            or len(tree) != 40
        ):
            raise PromotionError("remote tag commit/tree identity is invalid")
        if reference_object["type"] == "commit" and reference_object["sha"] != commit:
            raise PromotionError("remote lightweight tag differs from its resolved commit")
        return commit, tree

    def release_by_tag(self, tag: str) -> dict[str, object] | None:
        completed = _run(
            self.runner,
            [
                "gh",
                "api",
                "repos/{}/releases/tags/{}".format(self.repository, tag),
            ],
            cwd=self.cwd,
        )
        if completed.returncode != 0:
            diagnostic = (completed.stderr or "").lower()
            if "404" in diagnostic or "not found" in diagnostic:
                return None
            raise PromotionError(
                "same-version release state could not be proven: "
                + completed.stderr.strip()
            )
        try:
            value = json.loads(completed.stdout, object_pairs_hook=_strict_object)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PromotionError("same-version release lookup returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PromotionError("same-version release lookup returned a non-object")
        return value

    def create_draft(self, tag: str, commit: str, title: str) -> None:
        completed = _run(
            self.runner,
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                self.repository,
                "--verify-tag",
                "--target",
                commit,
                "--title",
                title,
                "--draft",
            ],
            cwd=self.cwd,
        )
        if completed.returncode != 0:
            raise PromotionError(
                "Draft Release creation failed: " + completed.stderr.strip()
            )

    def upload(self, tag: str, assets: Sequence[Path]) -> None:
        completed = _run(
            self.runner,
            [
                "gh",
                "release",
                "upload",
                tag,
                *(str(path) for path in assets),
                "--repo",
                self.repository,
            ],
            cwd=self.cwd,
        )
        if completed.returncode != 0:
            raise PromotionError("release asset upload failed: " + completed.stderr.strip())

    def download_asset(self, asset_id: int, destination: Path, maximum: int) -> None:
        try:
            with destination.open("xb") as output:
                completed = self.runner(
                    [
                        "gh",
                        "api",
                        "repos/{}/releases/assets/{}".format(
                            self.repository,
                            asset_id,
                        ),
                        "--header",
                        "Accept: application/octet-stream",
                    ],
                    cwd=self.cwd,
                    stdout=output,
                    stderr=subprocess.PIPE,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PromotionError("authenticated release asset download failed") from exc
        if completed.returncode != 0:
            try:
                destination.unlink()
            except OSError:
                pass
            diagnostic = completed.stderr
            if isinstance(diagnostic, bytes):
                diagnostic = diagnostic.decode("utf-8", "replace")
            raise PromotionError(
                "authenticated release asset download failed: "
                + str(diagnostic or "").strip()
            )
        if destination.stat().st_size > maximum:
            destination.unlink()
            raise PromotionError("authenticated release asset exceeds its fixed byte cap")

    def publish(self, tag: str) -> None:
        completed = _run(
            self.runner,
            [
                "gh",
                "release",
                "edit",
                tag,
                "--repo",
                self.repository,
                "--draft=false",
            ],
            cwd=self.cwd,
        )
        if completed.returncode != 0:
            raise PromotionError("Draft Release publication failed: " + completed.stderr.strip())


def _release_identity(
    value: Mapping[str, object],
    *,
    tag: str,
    source_commit: str,
) -> tuple[int, bool, dict[str, int]]:
    release_id = value.get("id")
    draft = value.get("draft")
    assets = value.get("assets")
    if (
        isinstance(release_id, bool)
        or not isinstance(release_id, int)
        or release_id <= 0
        or value.get("tag_name") != tag
        or value.get("target_commitish") != source_commit
        or not isinstance(draft, bool)
        or value.get("prerelease") is not False
        or not isinstance(assets, list)
    ):
        raise PromotionError("same-version release identity cannot be proven")
    selected: dict[str, int] = {}
    for item in assets:
        if not isinstance(item, dict):
            raise PromotionError("release asset identity cannot be proven")
        name = item.get("name")
        asset_id = item.get("id")
        if (
            not isinstance(name, str)
            or isinstance(asset_id, bool)
            or not isinstance(asset_id, int)
            or asset_id <= 0
            or name in selected
        ):
            raise PromotionError("release asset identity cannot be proven")
        selected[name] = asset_id
    return release_id, draft, selected


def _initial_journal(
    *,
    repository: str,
    tag: str,
    version: str,
    local: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": PROMOTION_SCHEMA,
        "repository": repository,
        "tag": tag,
        "version": version,
        "source_commit": local["source_commit"],
        "source_tree": local["source_tree"],
        "release_id": local["release_id"],
        "local_asset_digests": local["asset_digests"],
        "local_component_digests": local["component_digests"],
        "phase": "local_validated",
        "draft_release_id": None,
        "uploaded_assets": {},
        "final_asset_digests": None,
        "final_component_digests": None,
        "redownloaded": False,
        "published": False,
        "diagnostic": None,
    }


def _resume_journal(
    path: Path,
    expected: Mapping[str, object],
) -> dict[str, object]:
    if not path.exists() and not path.is_symlink():
        journal = dict(expected)
        _write_journal(path, journal)
        return journal
    journal = _load_journal(path)
    immutable = (
        "schema",
        "repository",
        "tag",
        "version",
        "source_commit",
        "source_tree",
        "release_id",
        "local_asset_digests",
        "local_component_digests",
    )
    if any(journal[field] != expected[field] for field in immutable):
        raise PromotionError("promotion journal identity differs from local assets")
    return journal


def promote_release(
    asset_dir: Path,
    *,
    version: str,
    journal_path: Path,
    repository: str = artifact.CANONICAL_REPOSITORY,
    runner: Callable[..., Any] = subprocess.run,
    api: Any = None,
) -> dict[str, object]:
    """Journal a Draft-first immutable promotion through authenticated APIs."""

    if repository != artifact.CANONICAL_REPOSITORY:
        raise PromotionError("promotion repository is not canonical")
    asset_dir = asset_dir.resolve()
    local = validate_asset_set(asset_dir, version=version)
    tag = "v{}".format(version)
    expected = _initial_journal(
        repository=repository,
        tag=tag,
        version=version,
        local=local,
    )
    journal = _resume_journal(journal_path, expected)
    github = api or GitHubReleaseAPI(repository, asset_dir, runner)
    try:
        remote_commit, remote_tree = github.tag_identity(tag)
        if (
            remote_commit != local["source_commit"]
            or remote_tree != local["source_tree"]
        ):
            raise PromotionError(
                "remote tag commit/tree differs from the release index source identity"
            )
        if not _phase_at_least(journal, "remote_identity_verified"):
            journal["phase"] = "remote_identity_verified"
            journal["diagnostic"] = None
            _write_journal(journal_path, journal)

        release = github.release_by_tag(tag)
        recorded_release_id = journal["draft_release_id"]
        created_here = False
        if release is None:
            if recorded_release_id is not None:
                raise PromotionError("recorded Draft Release is no longer observable")
            github.create_draft(
                tag,
                remote_commit,
                "Dev Flow Orchestrator {}".format(version),
            )
            created_here = True
            release = github.release_by_tag(tag)
            if release is None:
                raise PromotionError("created Draft Release cannot be read back")
        release_id, draft, observed_assets = _release_identity(
            release,
            tag=tag,
            source_commit=remote_commit,
        )
        if recorded_release_id is None:
            if not created_here:
                if draft:
                    raise PromotionError(
                        "unrecorded same-version Draft Release is ambiguous"
                    )
                raise PromotionError(
                    "published same-version release exists; overwrite is refused"
                )
            if not draft:
                raise PromotionError(
                    "new same-version release was published before verification"
                )
            journal["draft_release_id"] = release_id
            journal["phase"] = "draft_created"
            journal["diagnostic"] = None
            _write_journal(journal_path, journal)
        elif release_id != recorded_release_id:
            raise PromotionError("same-version release differs from the promotion journal")

        if not draft:
            recorded_assets = journal.get("uploaded_assets")
            if (
                _phase_at_least(journal, "remote_verified")
                and observed_assets == recorded_assets
                and journal.get("final_asset_digests")
                == journal.get("local_asset_digests")
                and journal.get("final_component_digests")
                == journal.get("local_component_digests")
            ):
                journal["phase"] = "published"
                journal["published"] = True
                journal["diagnostic"] = None
                _write_journal(journal_path, journal)
                return dict(journal)
            raise PromotionError(
                "published same-version release lacks proven remote verification; overwrite is refused"
            )

        expected_names = set(_expected_assets(version))
        if not set(observed_assets).issubset(expected_names):
            raise PromotionError("Draft Release contains undeclared assets")
        missing = [
            asset_dir / name
            for name in _expected_assets(version)
            if name not in observed_assets
        ]
        if missing:
            github.upload(tag, missing)
            release = github.release_by_tag(tag)
            if release is None:
                raise PromotionError("Draft Release disappeared after upload")
            observed_id, observed_draft, observed_assets = _release_identity(
                release,
                tag=tag,
                source_commit=remote_commit,
            )
            if observed_id != release_id or not observed_draft:
                raise PromotionError("Draft Release identity changed during upload")
        if set(observed_assets) != expected_names:
            raise PromotionError("Draft Release asset set is incomplete")
        journal["uploaded_assets"] = {
            name: observed_assets[name] for name in sorted(observed_assets)
        }
        if not _phase_at_least(journal, "assets_uploaded"):
            journal["phase"] = "assets_uploaded"
        journal["diagnostic"] = None
        _write_journal(journal_path, journal)

        with tempfile.TemporaryDirectory(
            prefix="dev-flow-promotion-download-"
        ) as temporary_name:
            downloaded = Path(temporary_name).resolve() / "assets"
            downloaded.mkdir()
            for name in _expected_assets(version):
                local_path = asset_dir / name
                github.download_asset(
                    observed_assets[name],
                    downloaded / name,
                    max(local_path.stat().st_size, 1),
                )
            final = validate_asset_set(downloaded, version=version)
        if final["asset_digests"] != local["asset_digests"]:
            raise PromotionError("re-downloaded release assets differ from uploaded bytes")
        if final["component_digests"] != local["component_digests"]:
            raise PromotionError("re-downloaded release component identity differs")
        if (
            final["source_commit"] != remote_commit
            or final["source_tree"] != remote_tree
            or final["release_id"] != local["release_id"]
        ):
            raise PromotionError("re-downloaded release source identity differs")
        journal["final_asset_digests"] = final["asset_digests"]
        journal["final_component_digests"] = final["component_digests"]
        journal["redownloaded"] = True
        journal["phase"] = "remote_verified"
        journal["diagnostic"] = None
        _write_journal(journal_path, journal)

        github.publish(tag)
        release = github.release_by_tag(tag)
        if release is None:
            raise PromotionError("published release cannot be read back")
        published_id, published_draft, published_assets = _release_identity(
            release,
            tag=tag,
            source_commit=remote_commit,
        )
        if (
            published_id != release_id
            or published_draft
            or published_assets != observed_assets
        ):
            raise PromotionError("published release identity cannot be proven")
        journal["phase"] = "published"
        journal["published"] = True
        journal["diagnostic"] = None
        _write_journal(journal_path, journal)
        return dict(journal)
    except Exception as exc:
        diagnostic = str(exc)[:MAX_DIAGNOSTIC_CHARACTERS]
        journal["diagnostic"] = diagnostic
        try:
            _write_journal(journal_path, journal)
        except Exception:
            pass
        if isinstance(exc, PromotionError):
            raise
        if isinstance(exc, artifact.ReleaseArtifactError):
            raise PromotionError(str(exc)) from exc
        raise PromotionError("promotion API operation failed: " + diagnostic) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--record", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = promote_release(
            arguments.asset_dir.resolve(),
            version=arguments.version,
            journal_path=arguments.record,
        )
    except (OSError, ValueError, PromotionError, artifact.ReleaseArtifactError) as exc:
        print(json.dumps({"error": str(exc), "ok": False}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "record": str(arguments.record), **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
