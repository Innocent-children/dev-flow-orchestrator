#!/usr/bin/env python3
"""Shared, standard-library release resolution and canonical download rules.

This module is embedded by the universal first-install entries and shipped as
digest-pinned lifecycle support for the installed ``update`` and ``reinstall``
commands.  Both surfaces share the exact version grammar, the canonical
repository identity, the official-release filter, and the HTTPS-only download
host rules below.  Every download lands in installer-owned temporary state;
no product state is modified here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


RESOLVER_SCHEMA = "dev-flow-release-resolver/1.0.0"
CANONICAL_REPOSITORY = "Innocent-children/dev-flow-orchestrator"
PRODUCT_NAME = "dev-flow-orchestrator"
# Dev Flow-owned Controller data layout constants shared by install evidence,
# the data-ownership marker, and reinstall cleanup.
DATA_MARKER_NAME = "dev-flow-data.json"
DATA_OWNERSHIP_SCHEMA = "dev-flow-data-ownership/1.0.0"
DATA_NAMESPACE = "0.4.0"
WEB_RUNTIME_DIR = "web-runtime"

MAX_API_BYTES = 512 * 1024
MAX_BOOTSTRAP_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 60
_UA = "dev-flow-release-resolver"

_SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
_TAG = re.compile(r"^v(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))$")
# Only the canonical repository and the official GitHub release delivery hosts
# are accepted.  Arbitrary repositories, mirrors, and download URLs are refused.
_ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


class ReleaseResolveError(RuntimeError):
    """Raised when a requested release cannot be proven official or acquired."""


def parse_version_request(value: object) -> str:
    """Parse ``latest`` or one strict MAJOR.MINOR.PATCH version token."""

    if not isinstance(value, str) or not value:
        raise ReleaseResolveError(
            "a version argument is required: MAJOR.MINOR.PATCH or latest"
        )
    if value == "latest":
        return value
    if _SEMVER.fullmatch(value) is None:
        raise ReleaseResolveError(
            "release version must be MAJOR.MINOR.PATCH without a prefix, "
            "or the exact token latest"
        )
    return value


def validate_version(value: object) -> str:
    value = parse_version_request(value)
    if value == "latest":
        raise ReleaseResolveError("a concrete release version is required")
    return value


def versioned_bootstrap_names(version: str) -> tuple[str, str]:
    version = validate_version(version)
    return (
        "install-{}.sh".format(version),
        "install-{}.ps1".format(version),
    )


class _HttpsHostsOnly(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        absolute = urljoin(req.full_url, newurl)
        if urlparse(absolute).scheme.lower() != "https":
            raise ReleaseResolveError("release download redirect target is not HTTPS")
        if urlparse(absolute).hostname not in _ALLOWED_HOSTS:
            raise ReleaseResolveError(
                "release download redirect target is outside the canonical hosts"
            )
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _check_origin(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ReleaseResolveError(label + " is not HTTPS")
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ReleaseResolveError(label + " is outside the canonical GitHub hosts")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ReleaseResolveError("release metadata contains a duplicate member")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ReleaseResolveError("release metadata contains a non-finite number")


def _read_json_object(
    url: str,
    *,
    maximum: int,
    label: str,
    opener: Any = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> dict[str, object]:
    _check_origin(url, label)
    selected = opener or build_opener(_HttpsHostsOnly())
    try:
        response = selected.open(
            Request(url, headers={"User-Agent": _UA}),
            timeout=timeout,
        )
        try:
            final_url = response.geturl()
            if urlparse(final_url).scheme.lower() != "https":
                raise ReleaseResolveError(label + " resolved to a non-HTTPS URL")
            if urlparse(final_url).hostname not in _ALLOWED_HOSTS:
                raise ReleaseResolveError(
                    label + " resolved outside the canonical GitHub hosts"
                )
            raw = bytearray()
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > maximum:
                    raise ReleaseResolveError(label + " exceeds its fixed byte cap")
            try:
                value = json.loads(
                    bytes(raw).decode("utf-8"),
                    object_pairs_hook=_strict_object,
                    parse_constant=_reject_constant,
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise ReleaseResolveError(label + " is not strict UTF-8 JSON") from exc
            if not isinstance(value, dict):
                raise ReleaseResolveError(label + " must be a JSON object")
            return value
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except ReleaseResolveError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        raise ReleaseResolveError(label + " failed") from exc


def _latest_release_url() -> str:
    return "https://api.github.com/repos/{}/releases/latest".format(
        CANONICAL_REPOSITORY
    )


def resolve_latest_version(
    opener: Any = None,
    *,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Resolve the latest *official* GitHub Release of the canonical repository.

    Draft and prerelease entries are rejected even if the platform endpoint
    returned them, and the resolved tag must carry both versioned bootstrap
    assets of the release.  Failure raises before any local state is touched.
    """

    url = _latest_release_url()
    value = _read_json_object(
        url,
        maximum=MAX_API_BYTES,
        label="latest official release lookup",
        opener=opener,
        timeout=timeout,
    )
    draft = value.get("draft")
    prerelease = value.get("prerelease")
    if draft is not False or prerelease is not False:
        raise ReleaseResolveError("latest GitHub Release is not an official release")
    tag_name = value.get("tag_name")
    match = _TAG.fullmatch(tag_name) if isinstance(tag_name, str) else None
    if match is None:
        raise ReleaseResolveError("latest GitHub Release tag is not a vMAJOR.MINOR.PATCH tag")
    version = match.group("version")
    assets = value.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ReleaseResolveError("latest GitHub Release declares no assets")
    names: set[str] = set()
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ReleaseResolveError("latest GitHub Release asset identity is invalid")
        names.add(str(item["name"]))
    expected = set(versioned_bootstrap_names(version))
    missing = sorted(expected - names)
    if missing:
        raise ReleaseResolveError(
            "latest GitHub Release is missing its versioned bootstrap asset(s): "
            + ", ".join(missing)
        )
    return version


def bootstrap_url(version: str, *, windows: bool) -> str:
    version = validate_version(version)
    name = versioned_bootstrap_names(version)[1 if windows else 0]
    return "https://github.com/{}/releases/download/v{}/{}".format(
        CANONICAL_REPOSITORY, version, name
    )


def _download(
    url: str,
    destination: Path,
    *,
    maximum: int,
    label: str,
    opener: Any = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> None:
    _check_origin(url, label)
    selected = opener or build_opener(_HttpsHostsOnly())
    try:
        response = selected.open(
            Request(url, headers={"User-Agent": _UA}),
            timeout=timeout,
        )
        try:
            final_url = response.geturl()
            if urlparse(final_url).scheme.lower() != "https":
                raise ReleaseResolveError(label + " resolved to a non-HTTPS URL")
            if urlparse(final_url).hostname not in _ALLOWED_HOSTS:
                raise ReleaseResolveError(
                    label + " resolved outside the canonical GitHub hosts"
                )
            received = 0
            with destination.open("xb") as output:
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > maximum:
                        raise ReleaseResolveError(label + " exceeds its fixed byte cap")
                    output.write(chunk)
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except ReleaseResolveError:
        raise
    except HTTPError as exc:
        if exc.code == 404:
            raise ReleaseResolveError(
                "requested GitHub Release does not exist at its official locator"
            ) from exc
        raise ReleaseResolveError(label + " failed") from exc
    except (URLError, OSError, TimeoutError) as exc:
        raise ReleaseResolveError(label + " failed") from exc


def acquire_version_bootstrap(
    version: str,
    *,
    windows: bool,
    destination_dir: Path,
    opener: Any = None,
) -> Path:
    """Download one version-matched bootstrap into installer-owned staging."""

    version = validate_version(version)
    if not destination_dir.is_dir() or destination_dir.is_symlink():
        raise ReleaseResolveError("bootstrap staging directory is unavailable")
    name = versioned_bootstrap_names(version)[1 if windows else 0]
    destination = destination_dir / name
    try:
        _download(
            bootstrap_url(version, windows=windows),
            destination,
            maximum=MAX_BOOTSTRAP_BYTES,
            label="release bootstrap download",
            opener=opener,
        )
    except BaseException:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return destination


def run_version_bootstrap(
    bootstrap: Path,
    arguments: Sequence[str],
    *,
    timeout: float | None = None,
) -> int:
    """Execute one downloaded version-matched bootstrap with forwarded options."""

    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(bootstrap),
            *arguments,
        ]
    else:
        command = ["/bin/sh", str(bootstrap), *arguments]
    completed = subprocess.run(list(command), check=False, timeout=timeout)
    return completed.returncode


def resolve_request(
    requested: object,
    *,
    windows: bool,
    destination_dir: Path,
    opener: Any = None,
) -> tuple[str, Path]:
    """Resolve ``latest`` or one exact version, then acquire its bootstrap."""

    requested = parse_version_request(requested)
    if requested == "latest":
        version = resolve_latest_version(opener=opener)
    else:
        version = requested
    return version, acquire_version_bootstrap(
        version,
        windows=windows,
        destination_dir=destination_dir,
        opener=opener,
    )


def _reject_repeated_options(arguments: Sequence[str]) -> None:
    seen: set[str] = set()
    for token in arguments:
        if not isinstance(token, str) or not token.startswith("--") or token == "--":
            continue
        option = token.partition("=")[0]
        if option in seen:
            raise ReleaseResolveError("repeated resolver option is rejected: " + option)
        seen.add(option)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, allow_abbrev=False
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", allow_abbrev=False)
    install.add_argument("--repository", required=True)
    install.add_argument("--requested", required=True)
    install.add_argument("phase_b_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        selected_argv = list(sys.argv[1:] if argv is None else argv)
        _reject_repeated_options(selected_argv)
        arguments = _parser().parse_args(selected_argv)
        if arguments.repository != CANONICAL_REPOSITORY:
            raise ReleaseResolveError("install entry repository is not canonical")
        if "DEV_FLOW_SOURCE_ROOT" in os.environ:
            raise ReleaseResolveError(
                "DEV_FLOW_SOURCE_ROOT is unsupported; run the official install entry"
            )
        forwarded = list(arguments.phase_b_args)
        if forwarded[:1] == ["--"]:
            forwarded = forwarded[1:]
        with tempfile.TemporaryDirectory(prefix="dev-flow-install-") as name:
            _version, bootstrap = resolve_request(
                arguments.requested,
                windows=os.name == "nt",
                destination_dir=Path(name).resolve(),
            )
            return run_version_bootstrap(bootstrap, forwarded)
    except (OSError, ReleaseResolveError, subprocess.SubprocessError) as exc:
        print(
            json.dumps({"ok": False, "phase": "resolve", "error": str(exc)},
                      sort_keys=True),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
