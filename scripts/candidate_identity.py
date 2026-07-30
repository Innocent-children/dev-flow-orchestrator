#!/usr/bin/env python3
"""Canonical cross-host candidate identity and byte-preserving handoff tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence


CONTRACT_VERSION = "dev-flow-canonical-v1"
DOMAIN = b"dev-flow-canonical-v1\x00"
FILE_KIND = b"\x46"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOLDEN_PREIMAGE_HEX = (
    "6465762d666c6f772d63616e6f6e6963616c2d7631000000000000000002"
    "0000000000000009524541444d452e6d6446000000000000000668656c6c"
    "6f0a0000000000000011736372697074732fe6b58be8af952e707946000000"
    "000000000c7072696e7428226f6b22290a"
)
GOLDEN_SHA256 = "a5f265def6c95a23cf668937f83a6d06320d2e784f064627a6847aed11974674"

_ALLOWED_TOP_LEVEL_DIRECTORIES = {
    ".codex-plugin",
    ".github",
    "hooks",
    "scripts",
    "skills",
    "templates",
    "tests",
    "workflows",
}
_ALLOWED_ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    ".mcp.json",
    "CONTRIBUTING.md",
    "INSTALL.md",
    "LICENSE",
    "README.md",
    "README.zh-CN.md",
}
_EXCLUDED_TOP_LEVEL = {
    ".codex",
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "docs",
    "htmlcov",
    "openspec",
    "work",
}
_EXCLUDED_ANYWHERE = {"__pycache__", ".DS_Store", ".coverage"}
_EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".pyd")
_HOST_LOCAL_EXCLUDED_FILES = {
    ".claude/settings.local.json",
    "AGENTS.md",
    "pyproject.toml",
    "uv.lock",
}
_HOST_LOCAL_CONTAINER_DIRECTORIES = {".claude"}
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class CandidateIdentityError(RuntimeError):
    """A candidate or handoff cannot satisfy the canonical-v1 contract."""


@dataclass(frozen=True)
class CanonicalEntry:
    path: str
    payload: bytes

    @property
    def path_bytes(self) -> bytes:
        return self.path.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


def _u64be(value: int) -> bytes:
    if value < 0 or value >= 2**64:
        raise CandidateIdentityError(f"value does not fit U64BE: {value}")
    return struct.pack(">Q", value)


def validate_relative_path(value: str) -> tuple[bytes, str]:
    """Return exact UTF-8 bytes and portable collision identity for one path."""

    if not isinstance(value, str) or not value:
        raise CandidateIdentityError("candidate path must be a non-empty string")
    if "\\" in value:
        raise CandidateIdentityError(f"candidate path contains backslash: {value!r}")
    if value.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", value):
        raise CandidateIdentityError(f"candidate path is absolute, drive, or UNC: {value!r}")
    path = PurePosixPath(value)
    if path.as_posix() != value:
        raise CandidateIdentityError(f"candidate path is not exact POSIX spelling: {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise CandidateIdentityError(f"candidate path contains traversal: {value!r}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CandidateIdentityError(
            f"candidate path is not exact UTF-8: {value!r}"
        ) from exc
    identity = unicodedata.normalize("NFC", value).casefold()
    return encoded, identity


def _validated_entries(entries: Iterable[CanonicalEntry]) -> list[CanonicalEntry]:
    result: list[CanonicalEntry] = []
    exact: set[bytes] = set()
    portable: dict[str, str] = {}
    for entry in entries:
        path_bytes, identity = validate_relative_path(entry.path)
        if path_bytes in exact:
            raise CandidateIdentityError(f"duplicate candidate path: {entry.path}")
        previous = portable.get(identity)
        if previous is not None:
            raise CandidateIdentityError(
                "portable candidate path collision: "
                f"{previous!r} and {entry.path!r}"
            )
        exact.add(path_bytes)
        portable[identity] = entry.path
        result.append(entry)
    return sorted(result, key=lambda item: item.path_bytes)


def canonical_preimage(entries: Iterable[CanonicalEntry]) -> bytes:
    ordered = _validated_entries(entries)
    framed = bytearray(DOMAIN)
    framed.extend(_u64be(len(ordered)))
    for entry in ordered:
        path_bytes = entry.path_bytes
        framed.extend(_u64be(len(path_bytes)))
        framed.extend(path_bytes)
        framed.extend(FILE_KIND)
        framed.extend(_u64be(len(entry.payload)))
        framed.extend(entry.payload)
    return bytes(framed)


def canonical_digest(entries: Iterable[CanonicalEntry]) -> tuple[str, int]:
    ordered = _validated_entries(entries)
    return hashlib.sha256(canonical_preimage(ordered)).hexdigest(), len(ordered)


def assert_golden_vector() -> None:
    entries = [
        CanonicalEntry("README.md", b"hello\n"),
        CanonicalEntry("scripts/\u6d4b\u8bd5.py", b'print("ok")\n'),
    ]
    preimage = canonical_preimage(entries)
    actual = hashlib.sha256(preimage).hexdigest()
    if preimage.hex() != GOLDEN_PREIMAGE_HEX or actual != GOLDEN_SHA256:
        raise CandidateIdentityError(
            "canonical-v1 golden vector failed: "
            f"expected={GOLDEN_SHA256} actual={actual}"
        )


def _excluded(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if relative.as_posix() in _HOST_LOCAL_EXCLUDED_FILES:
        return True
    if parts[0] in _EXCLUDED_TOP_LEVEL:
        return True
    if any(part in _EXCLUDED_ANYWHERE for part in parts):
        return True
    return relative.name.endswith(_EXCLUDED_SUFFIXES)


def _allowed(relative: Path) -> bool:
    return (
        relative.parts[0] in _ALLOWED_TOP_LEVEL_DIRECTORIES
        or relative.as_posix() in _HOST_LOCAL_CONTAINER_DIRECTORIES
        or relative.as_posix() in _ALLOWED_ROOT_FILES
    )


def _is_reparse_point(metadata: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(attributes & flag)


def canonical_entries(candidate_root: Path) -> list[CanonicalEntry]:
    root = candidate_root.expanduser().resolve()
    if not root.is_dir():
        raise CandidateIdentityError(f"candidate root is not a directory: {root}")
    result: list[CanonicalEntry] = []

    def visit(directory: Path) -> None:
        try:
            children = sorted(
                os.scandir(directory),
                key=lambda item: item.name.encode("utf-8", "surrogateescape"),
            )
        except OSError as exc:
            relative = directory.relative_to(root).as_posix() or "."
            raise CandidateIdentityError(
                f"cannot enumerate candidate directory {relative}: {exc}"
            ) from exc
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(root)
            if _excluded(relative):
                continue
            if not _allowed(relative):
                raise CandidateIdentityError(
                    f"unexpected path outside canonical allowlist: {relative.as_posix()}"
                )
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateIdentityError(
                    f"cannot inspect candidate path {relative.as_posix()}: {exc}"
                ) from exc
            if child.is_symlink() or _is_reparse_point(metadata):
                raise CandidateIdentityError(
                    "canonical candidate rejects symlink/reparse entry: "
                    f"{relative.as_posix()}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                visit(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise CandidateIdentityError(
                    f"canonical candidate rejects special entry: {relative.as_posix()}"
                )
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise CandidateIdentityError(
                    f"cannot read candidate file {relative.as_posix()}: {exc}"
                ) from exc
            result.append(CanonicalEntry(relative.as_posix(), payload))

    visit(root)
    return _validated_entries(result)


def candidate_digest(candidate_root: Path) -> tuple[str, int]:
    assert_golden_vector()
    return canonical_digest(canonical_entries(candidate_root))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CandidateIdentityError(f"cannot hash file {path}: {exc}") from exc
    return digest.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _write_exclusive(path: Path, payload: bytes) -> None:
    if not path.parent.is_dir():
        raise CandidateIdentityError(f"output parent does not exist: {path.parent}")
    temporary: Optional[Path] = None
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        temporary = Path(raw_name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise CandidateIdentityError(f"refusing to overwrite output: {path}") from exc
    except OSError as exc:
        raise CandidateIdentityError(f"cannot create output {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                # The final hardlink is already complete. A Windows sharing
                # violation or ACL failure while removing only the temporary
                # name must not turn a successful publication into a half-set.
                pass


def _publish_archive_exclusive(
    path: Path,
    entries: Sequence[CanonicalEntry],
) -> None:
    temporary: Optional[Path] = None
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        os.close(descriptor)
        temporary = Path(raw_name)
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as bundle:
            bundle.comment = b""
            for entry in entries:
                info = zipfile.ZipInfo(entry.path, date_time=_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                info.extra = b""
                info.comment = b""
                bundle.writestr(info, entry.payload)
        # Windows requires a write-capable descriptor for fsync even though
        # the completed archive bytes are only being flushed here.
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise CandidateIdentityError(f"refusing to overwrite output: {path}") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateIdentityError(f"cannot create output {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                # Preserve the completed no-clobber publication even when the
                # disposable hardlink name cannot be removed immediately.
                pass


def build_handoff(
    candidate_root: Path,
    archive_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    """Create a deterministic ZIP_STORED archive and external JSON manifest."""

    root = candidate_root.expanduser().resolve()
    archive = archive_path.expanduser().absolute()
    manifest = manifest_path.expanduser().absolute()
    if archive == manifest:
        raise CandidateIdentityError("archive and manifest paths must differ")
    if _inside(archive, root) or _inside(manifest, root):
        raise CandidateIdentityError("handoff outputs must be outside the candidate root")
    if archive.exists() or manifest.exists():
        raise CandidateIdentityError("handoff outputs must be new and cannot be overwritten")
    if not archive.parent.is_dir() or not manifest.parent.is_dir():
        raise CandidateIdentityError("handoff output parents must already exist")

    entries = canonical_entries(root)
    digest, count = canonical_digest(entries)
    assert_golden_vector()
    archive_published = False
    try:
        _publish_archive_exclusive(archive, entries)
        archive_published = True
        archive_sha256 = _sha256_file(archive)
        document: dict[str, Any] = {
            "archive": {
                "format": "ZIP_STORED",
                "sha256": archive_sha256,
            },
            "candidate": {
                "contract": CONTRACT_VERSION,
                "path_count": count,
                "sha256": digest,
            },
            "members": [
                {
                    "path": entry.path,
                    "sha256": entry.sha256,
                    "size": len(entry.payload),
                }
                for entry in entries
            ],
            "schema_version": 1,
        }
        _write_exclusive(manifest, _json_bytes(document))
    except Exception:
        if archive_published:
            try:
                archive.unlink()
            except FileNotFoundError:
                pass
        raise
    return document


def load_handoff_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateIdentityError(f"handoff manifest is invalid: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise CandidateIdentityError("handoff manifest schema_version must be 1")
    candidate = value.get("candidate")
    archive = value.get("archive")
    members = value.get("members")
    if (
        not isinstance(candidate, dict)
        or candidate.get("contract") != CONTRACT_VERSION
        or not SHA256_RE.fullmatch(str(candidate.get("sha256", "")))
        or not isinstance(candidate.get("path_count"), int)
        or not isinstance(archive, dict)
        or archive.get("format") != "ZIP_STORED"
        or not SHA256_RE.fullmatch(str(archive.get("sha256", "")))
        or not isinstance(members, list)
        or candidate["path_count"] != len(members)
    ):
        raise CandidateIdentityError("handoff manifest fields are invalid")
    parsed: list[CanonicalEntry] = []
    for member in members:
        if (
            not isinstance(member, dict)
            or not isinstance(member.get("path"), str)
            or not isinstance(member.get("size"), int)
            or member["size"] < 0
            or not SHA256_RE.fullmatch(str(member.get("sha256", "")))
        ):
            raise CandidateIdentityError("handoff manifest member is invalid")
        parsed.append(CanonicalEntry(member["path"], b""))
    _validated_entries(parsed)
    if [entry.path for entry in _validated_entries(parsed)] != [
        member["path"] for member in members
    ]:
        raise CandidateIdentityError("handoff manifest members are not path-byte sorted")
    return value


def verify_handoff(
    archive_path: Path,
    manifest_path: Path,
    expected_canonical: str,
) -> tuple[dict[str, Any], list[CanonicalEntry]]:
    if not SHA256_RE.fullmatch(expected_canonical):
        raise CandidateIdentityError(
            "expected canonical digest must be exactly 64 lowercase hexadecimal characters"
        )
    manifest = load_handoff_manifest(manifest_path)
    if manifest["candidate"]["sha256"] != expected_canonical:
        raise CandidateIdentityError("expected canonical digest does not match manifest")
    if _sha256_file(archive_path) != manifest["archive"]["sha256"]:
        raise CandidateIdentityError("handoff archive SHA-256 does not match manifest")

    expected = {member["path"]: member for member in manifest["members"]}
    entries: list[CanonicalEntry] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as bundle:
            if bundle.comment:
                raise CandidateIdentityError("handoff archive comment must be empty")
            infos = bundle.infolist()
            names = [info.filename for info in infos]
            _validated_entries(CanonicalEntry(name, b"") for name in names)
            if names != list(expected):
                raise CandidateIdentityError("handoff archive member set/order mismatch")
            for info in infos:
                if (
                    info.is_dir()
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.date_time != _ZIP_TIMESTAMP
                    or info.create_system != 3
                    or info.external_attr
                    != ((stat.S_IFREG | 0o600) << 16)
                    or info.internal_attr != 0
                    or info.extra
                    or info.comment
                ):
                    raise CandidateIdentityError(
                        f"handoff archive metadata is not deterministic: {info.filename}"
                    )
                payload = bundle.read(info)
                member = expected[info.filename]
                if len(payload) != member["size"]:
                    raise CandidateIdentityError(
                        f"handoff member size mismatch: {info.filename}"
                    )
                if hashlib.sha256(payload).hexdigest() != member["sha256"]:
                    raise CandidateIdentityError(
                        f"handoff member digest mismatch: {info.filename}"
                    )
                entries.append(CanonicalEntry(info.filename, payload))
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateIdentityError(f"handoff archive is invalid: {exc}") from exc
    digest, count = canonical_digest(entries)
    if digest != expected_canonical or count != manifest["candidate"]["path_count"]:
        raise CandidateIdentityError("handoff canonical candidate digest mismatch")
    return manifest, _validated_entries(entries)


def extract_verified_handoff(
    archive_path: Path,
    manifest_path: Path,
    expected_canonical: str,
    destination: Path,
) -> dict[str, Any]:
    """Verify then binary-write members into one new destination; never extractall."""

    manifest, entries = verify_handoff(
        archive_path,
        manifest_path,
        expected_canonical,
    )
    target = destination.expanduser().absolute()
    if target.exists():
        raise CandidateIdentityError(f"extraction destination must be new: {target}")
    if not target.parent.is_dir():
        raise CandidateIdentityError(
            f"extraction destination parent does not exist: {target.parent}"
        )
    target.mkdir()
    try:
        for entry in entries:
            output = target.joinpath(*PurePosixPath(entry.path).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_exclusive(output, entry.payload)
        observed, count = candidate_digest(target)
        if observed != expected_canonical or count != len(entries):
            raise CandidateIdentityError("extracted canonical candidate digest mismatch")
    except Exception:
        raise
    return manifest


__all__ = [
    "CONTRACT_VERSION",
    "DOMAIN",
    "FILE_KIND",
    "GOLDEN_PREIMAGE_HEX",
    "GOLDEN_SHA256",
    "CandidateIdentityError",
    "CanonicalEntry",
    "assert_golden_vector",
    "build_handoff",
    "candidate_digest",
    "canonical_digest",
    "canonical_entries",
    "canonical_preimage",
    "extract_verified_handoff",
    "load_handoff_manifest",
    "validate_relative_path",
    "verify_handoff",
]
