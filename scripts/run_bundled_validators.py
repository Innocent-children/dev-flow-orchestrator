#!/usr/bin/env python3
"""Run available Codex-bundled validators against one exact plugin snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

try:
    from scripts import candidate_identity
except ImportError:  # Direct script execution puts scripts/ on sys.path.
    import candidate_identity  # type: ignore


EXCLUDED_PARTS = {".git", ".codex", ".idea", "__pycache__"}
SKILL_VALIDATOR_RELATIVE = Path(
    "skills/.system/skill-creator/scripts/quick_validate.py"
)
PLUGIN_VALIDATOR_RELATIVE = Path(
    "skills/.system/plugin-creator/scripts/validate_plugin.py"
)
UNAVAILABLE_MARKERS = (
    "modulenotfounderror",
    "no module named",
    "cannot import name",
    "failed to import",
    "syntaxerror",
)


def _json_line(event: str, **values: Any) -> None:
    print(
        json.dumps(
            {"event": event, **values},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _candidate_paths(plugin_root: Path) -> list[Path]:
    result: list[Path] = []
    for path in plugin_root.rglob("*"):
        relative = path.relative_to(plugin_root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        result.append(path)
    return sorted(result, key=lambda item: item.relative_to(plugin_root).as_posix())


def snapshot_digest(plugin_root: Path) -> tuple[str, int]:
    """Hash path identities, kinds, executable bits, symlink targets, and file bytes."""

    digest = hashlib.sha256()
    count = 0
    for path in _candidate_paths(plugin_root):
        relative = path.relative_to(plugin_root).as_posix()
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RuntimeError(f"cannot inspect candidate path {relative}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            kind = b"link"
            try:
                payload = os.readlink(path).encode("utf-8", "surrogateescape")
            except OSError as exc:
                raise RuntimeError(
                    f"cannot read candidate symlink {relative}: {exc}"
                ) from exc
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"file+x" if metadata.st_mode & stat.S_IXUSR else b"file"
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise RuntimeError(
                    f"cannot read candidate file {relative}: {exc}"
                ) from exc
        elif stat.S_ISDIR(metadata.st_mode):
            kind = b"directory"
            payload = b""
        else:
            raise RuntimeError(f"unsupported candidate path kind: {relative}")
        encoded_path = relative.encode("utf-8", "surrogateescape")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(kind).to_bytes(2, "big"))
        digest.update(kind)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
    return digest.hexdigest(), count


def _run_git(plugin_root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *arguments],
        cwd=plugin_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=30,
    )


def source_diagnostics(
    plugin_root: Path,
    expected_revision: Optional[str],
    expected_canonical: Optional[str] = None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        host_digest, host_path_count = snapshot_digest(plugin_root)
        canonical_digest, canonical_path_count = candidate_identity.candidate_digest(
            plugin_root
        )
    except (RuntimeError, candidate_identity.CandidateIdentityError) as exc:
        return (
            {
                "candidate_sha256": None,
                "candidate_path_count": None,
                "canonical_candidate_sha256": None,
                "canonical_candidate_path_count": None,
                "canonical_contract": candidate_identity.CONTRACT_VERSION,
                "host_local_snapshot_sha256": None,
                "host_local_snapshot_path_count": None,
                "git_head": None,
                "git_clean": None,
            },
            [str(exc)],
        )
    try:
        head_result = _run_git(plugin_root, ["rev-parse", "HEAD"])
        status_result = _run_git(
            plugin_root,
            ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=no"],
        )
    except (OSError, subprocess.SubprocessError) as exc:
        head = None
        clean = None
        status = ""
        errors.append(f"real Git source diagnostics could not run: {exc}")
    else:
        head = head_result.stdout.strip() if head_result.returncode == 0 else None
        if head is None:
            errors.append(
                "git rev-parse HEAD failed: "
                + (head_result.stderr.strip() or f"exit {head_result.returncode}")
            )
        clean = status_result.returncode == 0 and not status_result.stdout.strip()
        status = status_result.stdout.strip()
        if status_result.returncode != 0:
            errors.append(
                "git status failed: "
                + (status_result.stderr.strip() or f"exit {status_result.returncode}")
            )
    normalized_expected = expected_revision.strip() if expected_revision else None
    normalized_canonical = (
        expected_canonical.strip() if expected_canonical else None
    )
    if normalized_canonical and not candidate_identity.SHA256_RE.fullmatch(
        normalized_canonical
    ):
        errors.append(
            "expected canonical candidate must be exactly 64 lowercase "
            "hexadecimal characters"
        )
    elif normalized_canonical and canonical_digest != normalized_canonical:
        errors.append(
            "canonical candidate SHA-256 does not match reviewed input: "
            f"expected {normalized_canonical}, observed {canonical_digest}"
        )
    if normalized_expected and head != normalized_expected:
        errors.append(
            f"candidate Git HEAD {head!r} does not match expected revision "
            f"{normalized_expected!r}"
        )
    if normalized_expected and clean is False:
        errors.append(
            "candidate worktree differs from the expected Git revision: "
            + (status or "Git reported an unspecified difference")
        )
    return (
        {
            # Keep the legacy names as the mode-sensitive host-local identity.
            "candidate_sha256": host_digest,
            "candidate_path_count": host_path_count,
            "canonical_candidate_sha256": canonical_digest,
            "canonical_candidate_path_count": canonical_path_count,
            "canonical_contract": candidate_identity.CONTRACT_VERSION,
            "canonical_golden_sha256": candidate_identity.GOLDEN_SHA256,
            "expected_canonical_candidate_sha256": normalized_canonical,
            "host_local_snapshot_sha256": host_digest,
            "host_local_snapshot_path_count": host_path_count,
            "git_head": head,
            "git_clean": clean,
            "expected_revision": normalized_expected,
            "github_sha": os.environ.get("GITHUB_SHA"),
            "runner_os": os.environ.get("RUNNER_OS"),
            "os": platform.system(),
            "python": platform.python_version(),
        },
        errors,
    )


def _codex_homes() -> Iterable[Path]:
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        yield Path(configured).expanduser()
    yield Path.home() / ".codex"


def _validator_path(
    environment_name: str,
    relative: Path,
) -> tuple[Optional[Path], bool, Optional[str]]:
    configured = os.environ.get(environment_name, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            return None, True, f"{environment_name} does not name a file: {path}"
        return path, True, None
    seen: set[str] = set()
    for root in _codex_homes():
        path = root.expanduser().resolve() / relative
        identity = os.path.normcase(str(path))
        if identity in seen:
            continue
        seen.add(identity)
        if path.is_file():
            return path, False, None
    return None, False, None


def _validator_python() -> tuple[Optional[Path], Optional[str]]:
    configured = os.environ.get("DEV_FLOW_VALIDATOR_PYTHON", "").strip()
    if not configured:
        return Path(os.path.abspath(sys.executable)), None
    # Do not resolve the final executable symlink: a virtual environment's
    # ``python`` commonly points at its base interpreter, but launching through
    # the venv path is what activates that environment's site-packages.
    interpreter = Path(
        os.path.abspath(os.fspath(Path(configured).expanduser()))
    )
    if not interpreter.is_file():
        return None, (
            "DEV_FLOW_VALIDATOR_PYTHON does not name an interpreter file: "
            f"{interpreter}"
        )
    return interpreter, None


def _unavailable_reason(completed: subprocess.CompletedProcess) -> Optional[str]:
    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    lowered = combined.casefold()
    if any(marker in lowered for marker in UNAVAILABLE_MARKERS):
        last_lines = [line.strip() for line in combined.splitlines() if line.strip()]
        return last_lines[-1] if last_lines else "validator dependency is unavailable"
    return None


def _run_validator(
    *,
    validator_kind: str,
    validator_path: Path,
    interpreter: Path,
    target: Path,
) -> tuple[str, Optional[str]]:
    command = [str(interpreter), str(validator_path), str(target)]
    try:
        completed = subprocess.run(
            command,
            cwd=target if target.is_dir() else target.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = f"could not start validator: {exc}"
        _json_line(
            "bundled_validator",
            validator=validator_kind,
            target=str(target),
            status="failed",
            detail=detail,
        )
        return "failed", detail
    unavailable = _unavailable_reason(completed)
    if unavailable is not None:
        _json_line(
            "bundled_validator",
            validator=validator_kind,
            target=str(target),
            validator_path=str(validator_path),
            interpreter=str(interpreter),
            status="unavailable",
            detail=unavailable,
        )
        return "unavailable", unavailable
    output = completed.stdout.strip()
    error_output = completed.stderr.strip()
    if completed.returncode != 0:
        detail = error_output or output or f"validator exited {completed.returncode}"
        _json_line(
            "bundled_validator",
            validator=validator_kind,
            target=str(target),
            validator_path=str(validator_path),
            interpreter=str(interpreter),
            status="failed",
            exit_code=completed.returncode,
            detail=detail,
        )
        return "failed", detail
    _json_line(
        "bundled_validator",
        validator=validator_kind,
        target=str(target),
        validator_path=str(validator_path),
        interpreter=str(interpreter),
        status="passed",
        detail=output or "validator exited successfully",
    )
    return "passed", None


def validate_with_bundled_tools(
    plugin_root: Path,
    *,
    require_available: bool,
) -> list[str]:
    errors: list[str] = []
    interpreter, interpreter_error = _validator_python()
    if interpreter_error is not None or interpreter is None:
        return [interpreter_error or "validator interpreter is unavailable"]
    skill_validator, skill_explicit, skill_error = _validator_path(
        "DEV_FLOW_SKILL_VALIDATOR",
        SKILL_VALIDATOR_RELATIVE,
    )
    plugin_validator, plugin_explicit, plugin_error = _validator_path(
        "DEV_FLOW_PLUGIN_VALIDATOR",
        PLUGIN_VALIDATOR_RELATIVE,
    )
    for kind, path, explicit, discovery_error in (
        ("skill", skill_validator, skill_explicit, skill_error),
        ("plugin-manifest", plugin_validator, plugin_explicit, plugin_error),
    ):
        if discovery_error is not None:
            errors.append(discovery_error)
            _json_line(
                "bundled_validator",
                validator=kind,
                status="failed",
                detail=discovery_error,
            )
        elif path is None:
            detail = (
                "Codex-bundled validator was not found; set "
                + (
                    "DEV_FLOW_SKILL_VALIDATOR"
                    if kind == "skill"
                    else "DEV_FLOW_PLUGIN_VALIDATOR"
                )
                + " to an explicit validator path"
            )
            _json_line(
                "bundled_validator",
                validator=kind,
                status="unavailable",
                detail=detail,
            )
            if require_available:
                errors.append(f"{kind}: {detail}")
        elif explicit:
            _json_line(
                "bundled_validator_discovery",
                validator=kind,
                source="explicit-environment",
                path=str(path),
            )
        else:
            _json_line(
                "bundled_validator_discovery",
                validator=kind,
                source="codex-home",
                path=str(path),
            )
    if skill_validator is not None and skill_error is None:
        skill_roots = sorted(
            path.parent
            for path in (plugin_root / "skills").glob("*/SKILL.md")
            if path.is_file()
        )
        if not skill_roots:
            errors.append("package contains no shipped skills to validate")
        for skill_root in skill_roots:
            status, detail = _run_validator(
                validator_kind=f"skill:{skill_root.name}",
                validator_path=skill_validator,
                interpreter=interpreter,
                target=skill_root,
            )
            if status == "failed" or (status == "unavailable" and require_available):
                errors.append(f"skill:{skill_root.name}: {detail}")
    if plugin_validator is not None and plugin_error is None:
        status, detail = _run_validator(
            validator_kind="plugin-manifest",
            validator_path=plugin_validator,
            interpreter=interpreter,
            target=plugin_root,
        )
        if status == "failed" or (status == "unavailable" and require_available):
            errors.append(f"plugin-manifest: {detail}")
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record one exact candidate snapshot, then run Codex-bundled skill and "
            "plugin manifest validators when their official scripts are available."
        )
    )
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="plugin source root (defaults to this script's parent plugin)",
    )
    parser.add_argument(
        "--require-available",
        action="store_true",
        help="fail when either official bundled validator cannot run",
    )
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="record and verify the candidate snapshot without invoking validators",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    plugin_root = Path(args.plugin_root).expanduser().resolve()
    expected_revision = (
        os.environ.get("DEV_FLOW_EXPECTED_GIT_SHA", "").strip()
        or os.environ.get("GITHUB_SHA", "").strip()
        or None
    )
    expected_canonical = (
        os.environ.get("DEV_FLOW_EXPECTED_CANONICAL_SHA256", "").strip() or None
    )
    before, errors = source_diagnostics(
        plugin_root,
        expected_revision,
        expected_canonical,
    )
    _json_line("candidate_snapshot", phase="before", **before)
    if not args.snapshot_only:
        errors.extend(
            validate_with_bundled_tools(
                plugin_root,
                require_available=args.require_available,
            )
        )
    after, after_errors = source_diagnostics(
        plugin_root,
        expected_revision,
        expected_canonical,
    )
    errors.extend(after_errors)
    _json_line("candidate_snapshot", phase="after", **after)
    if before.get("candidate_sha256") != after.get("candidate_sha256"):
        errors.append(
            "candidate package snapshot changed while bundled validators were running: "
            f"{before.get('candidate_sha256')} -> {after.get('candidate_sha256')}"
        )
    if before.get("canonical_candidate_sha256") != after.get(
        "canonical_candidate_sha256"
    ):
        errors.append(
            "canonical candidate changed while bundled validators were running: "
            f"{before.get('canonical_candidate_sha256')} -> "
            f"{after.get('canonical_candidate_sha256')}"
        )
    if errors:
        for error in errors:
            _json_line("validation_error", detail=error)
        _json_line("bundled_validation_summary", status="failed", error_count=len(errors))
        return 1
    _json_line("bundled_validation_summary", status="passed", error_count=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
