#!/usr/bin/env python3
"""Canonical workflow-bundle identities for ``dev-flow-bundle-identity/v1``.

This module intentionally operates on declared paths, kinds, and source bytes.
Catalog discovery and filesystem containment belong to the bundle loader; the
identity contract implemented here never infers file kinds or file sets.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


IDENTITY_CONTRACT = "dev-flow-bundle-identity/v1"
HANDLER_IMPLEMENTATION_DOMAIN = b"dev-flow-handler-implementation-v1\x00"
GRAPH_DOMAIN = b"dev-flow-graph-v1\x00"
BUNDLE_DOMAIN = b"dev-flow-workflow-bundle-v1\x00"
SIGNED_INT64_MIN = -(2**63)
SIGNED_INT64_MAX = 2**63 - 1

_workflow_bundle_kind_bytes = {
    "J": b"\x4a",
    "T": b"\x54",
    "B": b"\x42",
}
_workflow_bundle_utf8_bom = b"\xef\xbb\xbf"
_workflow_bundle_glob_characters = frozenset("*?[]")


class WorkflowBundleIdentityError(ValueError):
    """A stable, machine-readable canonicalization or framing failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class BundleFile:
    """One explicitly classified bundle or handler implementation file."""

    path: str
    kind: str
    source: bytes


ManifestFile = BundleFile
ImplementationFile = BundleFile


@dataclass(frozen=True)
class HandlerImplementation:
    """The exact package-owned implementation set for one registered handler."""

    handler_id: str
    contract_id: str
    files: Sequence[BundleFile]

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", tuple(self.files))


@dataclass(frozen=True)
class CanonicalFile:
    """A validated path and canonical payload ready for identity framing."""

    path: str
    kind: str
    payload: bytes
    path_bytes: bytes
    portable_identity: str

    @property
    def kind_byte(self) -> bytes:
        return _workflow_bundle_kind_bytes[self.kind]


@dataclass(frozen=True)
class WorkflowBundleIdentity:
    """Hex digests produced from one root graph, bundle, and handler set."""

    graph_sha256: str
    handler_implementation_sha256: Tuple[Tuple[str, str], ...]
    bundle_sha256: str

    def handler_digests(self) -> dict[str, str]:
        return dict(self.handler_implementation_sha256)


class _WorkflowBundleJsonSemanticError(Exception):
    def __init__(self, code: str, details: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


def _validate_package_relative_path(value: str) -> Tuple[bytes, str]:
    """Mirror the canonical candidate's portable package-path contract.

    This module is also loaded by the isolated controller, where package
    imports are intentionally unavailable.  Keeping this narrow validator
    local avoids changing ``sys.path`` or dynamically importing executable
    code while preserving the candidate identity's exact path grammar.
    """

    if not isinstance(value, str) or not value:
        raise ValueError("package path must be a non-empty string")
    if "\\" in value:
        raise ValueError("package path contains a backslash")
    if value.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", value):
        raise ValueError("package path is absolute, drive, or UNC")
    path = PurePosixPath(value)
    if path.as_posix() != value:
        raise ValueError("package path is not exact POSIX spelling")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("package path contains traversal")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("package path is not exact UTF-8") from exc
    identity = unicodedata.normalize("NFC", value).casefold()
    return encoded, identity


def u64be(value: int) -> bytes:
    """Encode one unsigned 64-bit integer in network byte order."""

    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
        raise WorkflowBundleIdentityError(
            "BUNDLE_IDENTITY_U64_INVALID",
            "value does not fit U64BE",
            details={"value": value if isinstance(value, int) else None},
        )
    return struct.pack(">Q", value)


def _source_bytes(source: Any, *, label: str) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, (bytearray, memoryview)):
        return bytes(source)
    raise WorkflowBundleIdentityError(
        "BUNDLE_IDENTITY_SOURCE_INVALID",
        f"{label} source must be bytes",
        details={"source_type": type(source).__name__},
    )


def _decode_utf8(source: Any, *, label: str) -> str:
    payload = _source_bytes(source, label=label)
    if payload.startswith(_workflow_bundle_utf8_bom):
        raise WorkflowBundleIdentityError(
            "BUNDLE_IDENTITY_BOM_FORBIDDEN",
            f"{label} must not contain a UTF-8 BOM",
            details={"label": label},
        )
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkflowBundleIdentityError(
            "BUNDLE_IDENTITY_UTF8_INVALID",
            f"{label} must be valid UTF-8",
            details={
                "label": label,
                "start": exc.start,
                "end": exc.end,
            },
        ) from exc


def _bounded_literal(value: str) -> str:
    return value if len(value) <= 80 else value[:77] + "..."


def _parse_json_integer(literal: str) -> int:
    negative = literal.startswith("-")
    digits = literal[1:] if negative else literal
    limit = "9223372036854775808" if negative else "9223372036854775807"
    if len(digits) > len(limit) or (
        len(digits) == len(limit) and digits > limit
    ):
        raise _WorkflowBundleJsonSemanticError(
            "BUNDLE_JSON_INTEGER_OUT_OF_RANGE",
            {"literal": _bounded_literal(literal)},
        )
    return int(literal)


def _reject_json_float(literal: str) -> Any:
    raise _WorkflowBundleJsonSemanticError(
        "BUNDLE_JSON_FLOAT_FORBIDDEN",
        {"literal": _bounded_literal(literal)},
    )


def _reject_json_constant(literal: str) -> Any:
    raise _WorkflowBundleJsonSemanticError(
        "BUNDLE_JSON_NONFINITE_FORBIDDEN",
        {"literal": literal},
    )


def _strict_json_object(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    observed: set[str] = set()
    for key, value in pairs:
        if key in observed:
            raise _WorkflowBundleJsonSemanticError(
                "BUNDLE_JSON_DUPLICATE_KEY",
                {"key": key},
            )
        observed.add(key)
        result[key] = value
    return result


def _json_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _validate_json_strings(value: Any, *, pointer: str = "") -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise WorkflowBundleIdentityError(
                "BUNDLE_JSON_UNICODE_INVALID",
                "JSON string contains a value that cannot be encoded as UTF-8",
                details={"pointer": pointer or "/"},
            ) from exc
        if unicodedata.normalize("NFC", value) != value:
            raise WorkflowBundleIdentityError(
                "BUNDLE_JSON_STRING_NOT_NFC",
                "JSON strings must be NFC",
                details={"pointer": pointer or "/"},
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_strings(item, pointer=f"{pointer}/{index}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_pointer = f"{pointer}/{_json_pointer_segment(key)}"
            try:
                key.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise WorkflowBundleIdentityError(
                    "BUNDLE_JSON_UNICODE_INVALID",
                    "JSON object key cannot be encoded as UTF-8",
                    details={"pointer": key_pointer},
                ) from exc
            if unicodedata.normalize("NFC", key) != key:
                raise WorkflowBundleIdentityError(
                    "BUNDLE_JSON_KEY_NOT_NFC",
                    "JSON object keys must be NFC",
                    details={"pointer": key_pointer},
                )
            _validate_json_strings(item, pointer=key_pointer)


def canonical_json_payload(source: Any) -> bytes:
    """Decode strict JSON and emit the exact canonical standard-library form."""

    text = _decode_utf8(source, label="JSON")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_json_object,
            parse_float=_reject_json_float,
            parse_int=_parse_json_integer,
            parse_constant=_reject_json_constant,
        )
    except _WorkflowBundleJsonSemanticError as exc:
        messages = {
            "BUNDLE_JSON_DUPLICATE_KEY": "JSON object keys must be unique",
            "BUNDLE_JSON_FLOAT_FORBIDDEN": "JSON floating-point numbers are forbidden",
            "BUNDLE_JSON_INTEGER_OUT_OF_RANGE": (
                "JSON integers must fit the signed 64-bit range"
            ),
            "BUNDLE_JSON_NONFINITE_FORBIDDEN": (
                "JSON NaN and infinity values are forbidden"
            ),
        }
        raise WorkflowBundleIdentityError(
            exc.code,
            messages[exc.code],
            details=exc.details,
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        details: dict[str, Any] = {}
        if isinstance(exc, json.JSONDecodeError):
            details = {
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
            }
        raise WorkflowBundleIdentityError(
            "BUNDLE_JSON_MALFORMED",
            "JSON payload is malformed",
            details=details,
        ) from exc

    _validate_json_strings(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise WorkflowBundleIdentityError(
            "BUNDLE_JSON_CANONICALIZATION_FAILED",
            "JSON payload cannot be canonically encoded",
        ) from exc
    return encoded


def canonical_text_payload(source: Any) -> bytes:
    """Validate NFC UTF-8 text and canonicalize CRLF and CR newlines to LF."""

    text = _decode_utf8(source, label="text")
    if unicodedata.normalize("NFC", text) != text:
        raise WorkflowBundleIdentityError(
            "BUNDLE_TEXT_NOT_NFC",
            "text payload must be NFC",
        )
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def canonical_binary_payload(source: Any) -> bytes:
    """Return binary content without transformation."""

    return _source_bytes(source, label="binary")


def canonical_payload(kind: str, source: Any) -> bytes:
    """Canonicalize one explicitly classified source payload."""

    if kind == "J":
        return canonical_json_payload(source)
    if kind == "T":
        return canonical_text_payload(source)
    if kind == "B":
        return canonical_binary_payload(source)
    raise WorkflowBundleIdentityError(
        "BUNDLE_CONTENT_KIND_UNSUPPORTED",
        "content kind must be exactly J, T, or B",
        details={"kind": kind if isinstance(kind, str) else None},
    )


def validate_bundle_path(value: str) -> Tuple[bytes, str]:
    """Validate one exact portable POSIX path and return its collision key."""

    if not isinstance(value, str):
        raise WorkflowBundleIdentityError(
            "BUNDLE_PATH_INVALID",
            "bundle path must be a non-empty string",
            details={"path_type": type(value).__name__},
        )
    if "\x00" in value:
        raise WorkflowBundleIdentityError(
            "BUNDLE_PATH_INVALID",
            "bundle path must not contain NUL",
            details={"path": value},
        )
    if any(
        character in value
        for character in _workflow_bundle_glob_characters
    ):
        raise WorkflowBundleIdentityError(
            "BUNDLE_PATH_GLOB_FORBIDDEN",
            "bundle manifests must enumerate exact paths without globs",
            details={"path": value},
        )
    try:
        path_bytes, portable_identity = _validate_package_relative_path(value)
    except ValueError as exc:
        raise WorkflowBundleIdentityError(
            "BUNDLE_PATH_INVALID",
            "bundle path is not an exact portable relative POSIX path",
            details={"path": value, "reason": str(exc)},
        ) from exc
    for index, segment in enumerate(value.split("/")):
        if unicodedata.normalize("NFC", segment) != segment:
            raise WorkflowBundleIdentityError(
                "BUNDLE_PATH_SEGMENT_NOT_NFC",
                "every bundle path segment must be NFC",
                details={"path": value, "segment_index": index},
            )
    return path_bytes, portable_identity


validate_relative_path = validate_bundle_path


def canonical_manifest_files(files: Iterable[BundleFile]) -> Tuple[CanonicalFile, ...]:
    """Validate, canonicalize, collision-check, and byte-sort a declared set."""

    result: list[CanonicalFile] = []
    exact: dict[bytes, str] = {}
    portable: dict[str, str] = {}
    for index, entry in enumerate(files):
        if not isinstance(entry, BundleFile):
            raise WorkflowBundleIdentityError(
                "BUNDLE_FILE_ENTRY_INVALID",
                "manifest entries must be BundleFile values",
                details={"index": index, "entry_type": type(entry).__name__},
            )
        path_bytes, portable_identity = validate_bundle_path(entry.path)
        previous_exact = exact.get(path_bytes)
        if previous_exact is not None:
            raise WorkflowBundleIdentityError(
                "BUNDLE_PATH_DUPLICATE",
                "bundle manifest paths must be unique",
                details={"path": entry.path},
            )
        previous_portable = portable.get(portable_identity)
        if previous_portable is not None:
            raise WorkflowBundleIdentityError(
                "BUNDLE_PATH_COLLISION",
                "bundle paths collide under NFC plus Unicode case-folding",
                details={"first_path": previous_portable, "second_path": entry.path},
            )
        payload = canonical_payload(entry.kind, entry.source)
        exact[path_bytes] = entry.path
        portable[portable_identity] = entry.path
        result.append(
            CanonicalFile(
                path=entry.path,
                kind=entry.kind,
                payload=payload,
                path_bytes=path_bytes,
                portable_identity=portable_identity,
            )
        )
    return tuple(sorted(result, key=lambda item: item.path_bytes))


def _identifier_bytes(value: Any, *, label: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise WorkflowBundleIdentityError(
            "BUNDLE_HANDLER_IDENTIFIER_INVALID",
            f"{label} must be a non-empty string",
            details={"field": label},
        )
    if unicodedata.normalize("NFC", value) != value:
        raise WorkflowBundleIdentityError(
            "BUNDLE_HANDLER_IDENTIFIER_NOT_NFC",
            f"{label} must be NFC",
            details={"field": label},
        )
    try:
        return value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise WorkflowBundleIdentityError(
            "BUNDLE_HANDLER_IDENTIFIER_INVALID",
            f"{label} must be valid UTF-8 text",
            details={"field": label},
        ) from exc


def handler_implementation_preimage(
    handler_id: str,
    contract_id: str,
    files: Iterable[BundleFile],
) -> bytes:
    """Build the exact domain-separated handler implementation preimage."""

    handler_bytes = _identifier_bytes(handler_id, label="handler_id")
    contract_bytes = _identifier_bytes(contract_id, label="contract_id")
    canonical_files = canonical_manifest_files(files)
    if not canonical_files:
        raise WorkflowBundleIdentityError(
            "BUNDLE_HANDLER_FILE_SET_EMPTY",
            "handler implementation file sets must be non-empty",
            details={"handler_id": handler_id},
        )

    framed = bytearray(HANDLER_IMPLEMENTATION_DOMAIN)
    framed.extend(u64be(len(handler_bytes)))
    framed.extend(handler_bytes)
    framed.extend(u64be(len(contract_bytes)))
    framed.extend(contract_bytes)
    framed.extend(u64be(len(canonical_files)))
    for entry in canonical_files:
        framed.extend(u64be(len(entry.path_bytes)))
        framed.extend(entry.path_bytes)
        framed.extend(entry.kind_byte)
        framed.extend(u64be(len(entry.payload)))
        framed.extend(entry.payload)
    return bytes(framed)


def handler_implementation_digest(
    handler_id: str,
    contract_id: str,
    files: Iterable[BundleFile],
) -> bytes:
    return hashlib.sha256(
        handler_implementation_preimage(handler_id, contract_id, files)
    ).digest()


def handler_implementation_sha256(
    handler_id: str,
    contract_id: str,
    files: Iterable[BundleFile],
) -> str:
    return handler_implementation_digest(handler_id, contract_id, files).hex()


def graph_preimage(root_graph_source: Any) -> bytes:
    root_json = canonical_json_payload(root_graph_source)
    return GRAPH_DOMAIN + u64be(len(root_json)) + root_json


def graph_digest(root_graph_source: Any) -> bytes:
    return hashlib.sha256(graph_preimage(root_graph_source)).digest()


def graph_sha256(root_graph_source: Any) -> str:
    return graph_digest(root_graph_source).hex()


def _canonical_handlers(
    handlers: Iterable[HandlerImplementation],
) -> Tuple[Tuple[bytes, bytes, HandlerImplementation, bytes], ...]:
    result: list[Tuple[bytes, bytes, HandlerImplementation, bytes]] = []
    exact: set[bytes] = set()
    portable: dict[str, str] = {}
    for index, handler in enumerate(handlers):
        if not isinstance(handler, HandlerImplementation):
            raise WorkflowBundleIdentityError(
                "BUNDLE_HANDLER_ENTRY_INVALID",
                "handlers must be HandlerImplementation values",
                details={"index": index, "entry_type": type(handler).__name__},
            )
        handler_bytes = _identifier_bytes(handler.handler_id, label="handler_id")
        contract_bytes = _identifier_bytes(handler.contract_id, label="contract_id")
        if handler_bytes in exact:
            raise WorkflowBundleIdentityError(
                "BUNDLE_HANDLER_DUPLICATE",
                "handler identifiers must be unique",
                details={"handler_id": handler.handler_id},
            )
        portable_identity = unicodedata.normalize(
            "NFC", handler.handler_id
        ).casefold()
        previous = portable.get(portable_identity)
        if previous is not None:
            raise WorkflowBundleIdentityError(
                "BUNDLE_HANDLER_COLLISION",
                "handler identifiers collide under Unicode case-folding",
                details={
                    "first_handler_id": previous,
                    "second_handler_id": handler.handler_id,
                },
            )
        implementation_digest = handler_implementation_digest(
            handler.handler_id,
            handler.contract_id,
            handler.files,
        )
        exact.add(handler_bytes)
        portable[portable_identity] = handler.handler_id
        result.append(
            (handler_bytes, contract_bytes, handler, implementation_digest)
        )
    return tuple(sorted(result, key=lambda item: item[0]))


def bundle_preimage(
    files: Iterable[BundleFile],
    handlers: Iterable[HandlerImplementation],
) -> bytes:
    """Build the exact domain-separated workflow bundle preimage."""

    canonical_files = canonical_manifest_files(files)
    canonical_handlers = _canonical_handlers(handlers)

    framed = bytearray(BUNDLE_DOMAIN)
    framed.extend(u64be(len(canonical_files)))
    for entry in canonical_files:
        framed.extend(u64be(len(entry.path_bytes)))
        framed.extend(entry.path_bytes)
        framed.extend(entry.kind_byte)
        framed.extend(u64be(len(entry.payload)))
        framed.extend(entry.payload)
    framed.extend(u64be(len(canonical_handlers)))
    for handler_bytes, contract_bytes, _handler, implementation_digest in (
        canonical_handlers
    ):
        framed.extend(u64be(len(handler_bytes)))
        framed.extend(handler_bytes)
        framed.extend(u64be(len(contract_bytes)))
        framed.extend(contract_bytes)
        framed.extend(implementation_digest)
    return bytes(framed)


def bundle_digest(
    files: Iterable[BundleFile],
    handlers: Iterable[HandlerImplementation],
) -> bytes:
    return hashlib.sha256(bundle_preimage(files, handlers)).digest()


def bundle_sha256(
    files: Iterable[BundleFile],
    handlers: Iterable[HandlerImplementation],
) -> str:
    return bundle_digest(files, handlers).hex()


def compute_workflow_bundle_identity(
    root_graph_source: Any,
    files: Iterable[BundleFile],
    handlers: Iterable[HandlerImplementation],
) -> WorkflowBundleIdentity:
    """Compute all graph, handler, and enclosing bundle digests."""

    materialized_files = tuple(files)
    materialized_handlers = tuple(handlers)
    canonical_handlers = _canonical_handlers(materialized_handlers)
    return WorkflowBundleIdentity(
        graph_sha256=graph_sha256(root_graph_source),
        handler_implementation_sha256=tuple(
            (handler.handler_id, implementation_digest.hex())
            for _handler_bytes, _contract_bytes, handler, implementation_digest in (
                canonical_handlers
            )
        ),
        bundle_sha256=bundle_sha256(materialized_files, materialized_handlers),
    )


compute_graph_sha256 = graph_sha256
compute_handler_implementation_sha256 = handler_implementation_sha256
compute_bundle_sha256 = bundle_sha256


__all__ = [
    "BUNDLE_DOMAIN",
    "BundleFile",
    "CanonicalFile",
    "GRAPH_DOMAIN",
    "HANDLER_IMPLEMENTATION_DOMAIN",
    "HandlerImplementation",
    "IDENTITY_CONTRACT",
    "ImplementationFile",
    "ManifestFile",
    "SIGNED_INT64_MAX",
    "SIGNED_INT64_MIN",
    "WorkflowBundleIdentity",
    "WorkflowBundleIdentityError",
    "bundle_digest",
    "bundle_preimage",
    "bundle_sha256",
    "canonical_binary_payload",
    "canonical_json_payload",
    "canonical_manifest_files",
    "canonical_payload",
    "canonical_text_payload",
    "compute_bundle_sha256",
    "compute_graph_sha256",
    "compute_handler_implementation_sha256",
    "compute_workflow_bundle_identity",
    "graph_digest",
    "graph_preimage",
    "graph_sha256",
    "handler_implementation_digest",
    "handler_implementation_preimage",
    "handler_implementation_sha256",
    "u64be",
    "validate_bundle_path",
    "validate_relative_path",
]
