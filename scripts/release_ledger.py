#!/usr/bin/env python3
"""Workflow release-ledger and first-introduction provenance contracts.

This is release tooling, not controller runtime.  It validates immutable Git
objects and package-owned workflow identities without treating controller data
root scans as positive proof that an identity has never been exposed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

try:
    from workflow_bundle_identity import (
        BundleFile,
        HandlerImplementation,
        compute_workflow_bundle_identity,
        handler_implementation_sha256,
    )
except ModuleNotFoundError:  # Imported as ``scripts.release_ledger`` in tests.
    from scripts.workflow_bundle_identity import (
        BundleFile,
        HandlerImplementation,
        compute_workflow_bundle_identity,
        handler_implementation_sha256,
    )


RELEASE_LEDGER_SCHEMA = "dev-flow-workflow-release-ledger/v1"
FIRST_INTRODUCTION_SCHEMA = (
    "dev-flow-workflow-first-introduction-provenance/v1"
)
INTRODUCTION_EPOCH_SCHEMA = (
    "dev-flow-workflow-introduction-epoch-provenance/v1"
)
FIRST_INTRODUCTION_INVENTORY_CONTRACT = (
    "dev-flow-first-introduction-git-tree/v1"
)
FIRST_INTRODUCTION_INVENTORY_DOMAIN = (
    b"dev-flow-first-introduction-git-tree-v1\x00"
)
RELEASE_REVIEW_SCHEMA = "dev-flow-release-review/v1"
RELEASE_HANDOFF_SCHEMA = "dev-flow-release-handoff/v1"
FIRST_INTRODUCTION_CHANGE_ID = "introduce-versioned-workflow-kernel"
FIRST_INTRODUCTION_BASE_COMMIT = (
    "2dc397411ad1ea5f2a43d43e881523b125bb5eec"
)
FIRST_INTRODUCTION_BASE_TREE = (
    "ee7de366a818d8800b4808015f2d8ae4c4405136"
)
FIRST_INTRODUCTION_OBJECT_FORMAT = "sha1"
FIRST_INTRODUCTION_INVENTORY_SHA256 = (
    "43bf5e1da67a18e6beb15c7915357e7f84975c369d7ed165f50c84f40ba2b886"
)
FIRST_INTRODUCTION_RAW_INVENTORY_BYTES = 7912
FIRST_INTRODUCTION_MANIFEST_SHA256 = (
    "72e301d16546001abb397e37600cf3a141ca2955e7052f5d7dabdbb96f02016a"
)
RESERVED_V3_ACTIVATION_SHA256 = (
    "ab7e025864038fdae1016117aa955dc01838b54c9e039b4de48e2fe6656eb710"
)
RESERVED_V3_LEDGER_SHA256 = (
    "89002240941e29ecb9f6bb6eb4093ae657897e3209d070ca74abd33aad747062"
)
RESERVED_V3_RESERVATION_COUNT = 4
INTRODUCTION_EPOCH_APPEND_BATCH_DOMAIN = (
    b"dev-flow-workflow-release-ledger-append-batch-v1\x00"
)
INTRODUCTION_EPOCH_CUMULATIVE_IDENTITY_SET_DOMAIN = (
    b"dev-flow-workflow-introduction-cumulative-identity-set-v1\x00"
)
INTRODUCTION_EPOCH_RESERVED_UNEXPOSED = "reserved-unexposed"
INTRODUCTION_EPOCH_OFFICIAL_RELEASE = "official-release"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")
_HANDLER_ID_RE = re.compile(
    r"^(?P<prefix>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:[./-][A-Za-z0-9][A-Za-z0-9._-]*)*/"
    r"(?P<version>v[1-9][0-9]*)$"
)
_RUNTIME_MANIFESTS = (
    ("commands", "commands.json"),
    ("executors", "executors.json"),
    ("gates", "gates.json"),
    ("guards", "guards.json"),
    ("reducers", "reducers.json"),
)
_LEDGER_FIELDS = frozenset({"schema", "reservations"})
_RESERVATION_FIELDS = frozenset(
    {
        "workflow_id",
        "workflow_version",
        "graph_sha256",
        "bundle_sha256",
        "handlers",
    }
)
_RESERVATION_HANDLER_FIELDS = frozenset(
    {
        "registry",
        "id",
        "version",
        "contract_id",
        "implementation_sha256",
    }
)
_FIRST_INTRODUCTION_FIELDS = frozenset(
    {
        "schema",
        "change_id",
        "git_object_format",
        "base_commit",
        "base_tree",
        "inventory_contract",
        "inventory_sha256",
        "introduced_workflows",
        "introduced_handlers",
    }
)
_INTRODUCTION_EPOCH_COMMON_FIELDS = frozenset(
    {
        "schema",
        "change_id",
        "epoch_id",
        "epoch_sequence",
        "predecessor_kind",
        "predecessor_provenance_sha256",
        "predecessor_ledger_sha256",
        "predecessor_reservation_count",
        "git_object_format",
        "base_commit",
        "base_tree",
        "inventory_contract",
        "inventory_sha256",
        "introduced_workflows",
        "introduced_handlers",
        "append_batch_start",
        "append_batch_count",
        "append_batch_sha256",
        "result_ledger_sha256",
        "cumulative_identity_set_sha256",
    }
)
_INTRODUCTION_EPOCH_RESERVED_UNEXPOSED_FIELDS = frozenset(
    {
        "predecessor_first_introduction_sha256",
        "predecessor_activation_sha256",
        "reviewed",
        "handoff",
        "published",
        "installed",
        "activated",
        "pin_eligible",
    }
)
_INTRODUCTION_EPOCH_OFFICIAL_RELEASE_FIELDS = frozenset(
    {
        "predecessor_review_sha256",
        "predecessor_handoff_sha256",
    }
)
_INTRODUCED_WORKFLOW_FIELDS = frozenset(
    {"workflow_id", "workflow_version"}
)
_INTRODUCED_HANDLER_FIELDS = frozenset(
    {"registry", "id", "version", "contract_id"}
)
_REVIEW_FIELDS = frozenset(
    {
        "schema",
        "reviewer_id",
        "provenance_sha256",
        "base_commit",
        "base_tree",
        "inventory_sha256",
        "candidate_sha256",
    }
)
_RELEASE_HANDOFF_FIELDS = frozenset(
    {
        "schema",
        "release_id",
        "ledger_sha256",
        "review_sha256",
        "reviewer_id",
        "provenance_sha256",
        "base_commit",
        "base_tree",
        "inventory_sha256",
        "candidate_sha256",
        "archive_manifest_sha256",
        "archive_sha256",
    }
)


class ReleaseLedgerError(RuntimeError):
    """Stable release/provenance validation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class GitInventoryEvidence:
    object_format: str
    base_commit: str
    base_tree: str
    raw_size: int
    inventory_sha256: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseBoundaryDecision:
    allowed: bool
    blocker_codes: tuple[str, ...]
    observed_task_references: tuple[Mapping[str, object], ...]
    data_root_scan_is_authoritative_absence_proof: bool = False


@dataclass(frozen=True)
class FirstIntroductionProvenanceInput:
    """Raw evidence that the boundary evaluator validates itself."""

    manifest_bytes: bytes
    repository: Path
    plugin_root: Path


@dataclass(frozen=True)
class ContinuousPriorReleaseInput:
    """Exact prior official release records, validated as one chain."""

    ledger_bytes: bytes
    review_bytes: bytes
    handoff_bytes: bytes


@dataclass(frozen=True)
class IntroductionEpochProvenanceInput:
    """Exact inputs for one entry in an introduction-provenance chain."""

    manifest_bytes: bytes
    result_ledger_bytes: bytes
    predecessor_review_bytes: Optional[bytes] = None
    predecessor_handoff_bytes: Optional[bytes] = None


@dataclass(frozen=True)
class IntroductionEpochValidation:
    """Validated epoch facts; provenance alone never authorizes exposure."""

    manifest: Mapping[str, object]
    provenance_sha256: str
    result_ledger_sha256: str
    cumulative_identity_set_sha256: str
    authorizes_exposure: bool = False


class _DuplicateJsonKey(ValueError):
    pass


def _strict_object(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _reject_float(value: str) -> object:
    raise ValueError(f"floating-point value is forbidden: {value[:40]}")


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite value is forbidden: {value}")


def _parse_json_integer(value: str) -> int:
    parsed = int(value, 10)
    if not -(2**63) <= parsed < 2**63:
        raise ValueError("integer is outside the signed 64-bit range")
    return parsed


def _validate_json_value(
    value: object,
    *,
    pointer: str = "",
) -> None:
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            try:
                value.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise ReleaseLedgerError(
                    "RELEASE_JSON_UNICODE_INVALID",
                    "release JSON contains a string that is not exact UTF-8",
                    details={"pointer": pointer or "/"},
                ) from exc
            if unicodedata.normalize("NFC", value) != value:
                raise ReleaseLedgerError(
                    "RELEASE_JSON_NOT_NFC",
                    "release JSON strings must be NFC",
                    details={"pointer": pointer or "/"},
                )
        return
    if isinstance(value, int):
        if isinstance(value, bool) or not -(2**63) <= value < 2**63:
            raise ReleaseLedgerError(
                "RELEASE_JSON_INTEGER_INVALID",
                "release JSON integers must fit signed 64-bit range",
                details={"pointer": pointer or "/"},
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, pointer=f"{pointer}/{index}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReleaseLedgerError(
                    "RELEASE_JSON_KEY_INVALID",
                    "release JSON object keys must be strings",
                    details={"pointer": pointer or "/"},
                )
            _validate_json_value(
                key, pointer=f"{pointer}/{_json_pointer_part(key)}"
            )
            _validate_json_value(
                item, pointer=f"{pointer}/{_json_pointer_part(key)}"
            )
        return
    raise ReleaseLedgerError(
        "RELEASE_JSON_TYPE_INVALID",
        "release JSON contains an unsupported value type",
        details={
            "pointer": pointer or "/",
            "type": type(value).__name__,
        },
    )


def _json_pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def canonical_json_bytes(value: object) -> bytes:
    _validate_json_value(value)
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, ReleaseLedgerError):
            raise
        raise ReleaseLedgerError(
            "RELEASE_JSON_INVALID",
            "release JSON cannot be canonically encoded",
        ) from exc


def parse_canonical_json_bytes(
    source: bytes,
    *,
    label: str,
) -> object:
    if not isinstance(source, bytes):
        raise ReleaseLedgerError(
            "RELEASE_JSON_INVALID",
            "release JSON source must be bytes",
            details={"label": label},
        )
    try:
        text = source.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except _DuplicateJsonKey as exc:
        raise ReleaseLedgerError(
            "RELEASE_JSON_DUPLICATE_KEY",
            "release JSON contains a duplicate object key",
            details={"label": label, "key": str(exc)},
        ) from exc
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReleaseLedgerError(
            "RELEASE_JSON_INVALID",
            "release JSON cannot be parsed strictly",
            details={"label": label},
        ) from exc
    _validate_json_value(value)
    if canonical_json_bytes(value) != source:
        raise ReleaseLedgerError(
            "RELEASE_JSON_NONCANONICAL",
            "release JSON bytes are not the strict canonical encoding",
            details={"label": label},
        )
    return value


def _expect_object(
    value: object,
    *,
    pointer: str,
    fields: frozenset[str],
) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ReleaseLedgerError(
            "RELEASE_SCHEMA_INVALID",
            "release record must be an object",
            details={"pointer": pointer},
        )
    if set(value) != fields:
        raise ReleaseLedgerError(
            "RELEASE_SCHEMA_INVALID",
            "release record fields do not match the strict schema",
            details={
                "pointer": pointer,
                "missing": sorted(fields - set(value)),
                "unknown": sorted(set(value) - fields),
            },
        )
    return value


def _stable_id(value: object, *, pointer: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID_RE.fullmatch(value):
        raise ReleaseLedgerError(
            "RELEASE_IDENTITY_INVALID",
            "release identity is missing or malformed",
            details={"pointer": pointer},
        )
    return value


def _digest(value: object, *, pointer: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReleaseLedgerError(
            "RELEASE_DIGEST_INVALID",
            "release digest must be lowercase SHA-256",
            details={"pointer": pointer},
        )
    return value


def _positive_version(value: object, *, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ReleaseLedgerError(
            "RELEASE_VERSION_INVALID",
            "workflow versions must be positive integers",
            details={"pointer": pointer},
        )
    return value


def _handler_version(identifier: str, *, pointer: str) -> str:
    match = _HANDLER_ID_RE.fullmatch(identifier)
    if match is None:
        raise ReleaseLedgerError(
            "RELEASE_HANDLER_ID_INVALID",
            "handler identity must end in one explicit /vN version",
            details={"pointer": pointer},
        )
    return match.group("version")


def _validate_handler_entry(
    value: object,
    *,
    pointer: str,
    implementation_required: bool,
) -> dict[str, object]:
    fields = (
        _RESERVATION_HANDLER_FIELDS
        if implementation_required
        else _INTRODUCED_HANDLER_FIELDS
    )
    item = _expect_object(value, pointer=pointer, fields=fields)
    registry = _stable_id(item["registry"], pointer=f"{pointer}/registry")
    identifier = _stable_id(item["id"], pointer=f"{pointer}/id")
    version = _stable_id(item["version"], pointer=f"{pointer}/version")
    if version != _handler_version(identifier, pointer=f"{pointer}/id"):
        raise ReleaseLedgerError(
            "RELEASE_HANDLER_VERSION_MISMATCH",
            "handler version does not match its identity suffix",
            details={"pointer": pointer},
        )
    contract_id = _stable_id(
        item["contract_id"], pointer=f"{pointer}/contract_id"
    )
    result: dict[str, object] = {
        "registry": registry,
        "id": identifier,
        "version": version,
        "contract_id": contract_id,
    }
    if implementation_required:
        result["implementation_sha256"] = _digest(
            item["implementation_sha256"],
            pointer=f"{pointer}/implementation_sha256",
        )
    return result


def _handler_sort_key(
    value: Mapping[str, object],
) -> tuple[bytes, bytes, bytes, bytes]:
    return (
        str(value["registry"]).encode("utf-8"),
        str(value["id"]).encode("utf-8"),
        str(value["version"]).encode("utf-8"),
        str(value["contract_id"]).encode("utf-8"),
    )


def _workflow_sort_key(
    value: Mapping[str, object],
) -> tuple[bytes, int]:
    return (
        str(value["workflow_id"]).encode("utf-8"),
        int(value["workflow_version"]),
    )


def validate_release_ledger_bytes(
    source: bytes,
    *,
    previous_ledger_bytes: Optional[bytes] = None,
) -> dict[str, object]:
    value = parse_canonical_json_bytes(source, label="release ledger")
    ledger = _expect_object(value, pointer="/", fields=_LEDGER_FIELDS)
    if ledger["schema"] != RELEASE_LEDGER_SCHEMA:
        raise ReleaseLedgerError(
            "RELEASE_LEDGER_SCHEMA_UNSUPPORTED",
            "workflow release-ledger schema is unsupported",
        )
    reservations_value = ledger["reservations"]
    if not isinstance(reservations_value, list):
        raise ReleaseLedgerError(
            "RELEASE_LEDGER_INVALID",
            "release ledger reservations must be a list",
        )
    reservations: list[dict[str, object]] = []
    keys: set[tuple[str, int]] = set()
    for index, raw in enumerate(reservations_value):
        pointer = f"/reservations/{index}"
        item = _expect_object(
            raw, pointer=pointer, fields=_RESERVATION_FIELDS
        )
        workflow_id = _stable_id(
            item["workflow_id"], pointer=f"{pointer}/workflow_id"
        )
        workflow_version = _positive_version(
            item["workflow_version"],
            pointer=f"{pointer}/workflow_version",
        )
        key = (workflow_id, workflow_version)
        if key in keys:
            raise ReleaseLedgerError(
                "RELEASE_RESERVATION_DUPLICATE",
                "one workflow identifier/version may have one reservation",
                details={"workflow": list(key)},
            )
        keys.add(key)
        handlers_value = item["handlers"]
        if not isinstance(handlers_value, list) or not handlers_value:
            raise ReleaseLedgerError(
                "RELEASE_RESERVATION_HANDLER_INVALID",
                "each reservation must bind at least one handler",
                details={"pointer": f"{pointer}/handlers"},
            )
        handlers = [
            _validate_handler_entry(
                handler,
                pointer=f"{pointer}/handlers/{handler_index}",
                implementation_required=True,
            )
            for handler_index, handler in enumerate(handlers_value)
        ]
        if handlers != sorted(handlers, key=_handler_sort_key) or len(
            {_handler_sort_key(handler) for handler in handlers}
        ) != len(handlers):
            raise ReleaseLedgerError(
                "RELEASE_RESERVATION_HANDLER_ORDER_INVALID",
                "reservation handlers must be sorted and unique",
                details={"pointer": f"{pointer}/handlers"},
            )
        reservations.append(
            {
                "workflow_id": workflow_id,
                "workflow_version": workflow_version,
                "graph_sha256": _digest(
                    item["graph_sha256"],
                    pointer=f"{pointer}/graph_sha256",
                ),
                "bundle_sha256": _digest(
                    item["bundle_sha256"],
                    pointer=f"{pointer}/bundle_sha256",
                ),
                "handlers": handlers,
            }
        )
    if previous_ledger_bytes is not None:
        previous = validate_release_ledger_bytes(previous_ledger_bytes)
        previous_reservations = previous["reservations"]
        if reservations[: len(previous_reservations)] != previous_reservations:
            raise ReleaseLedgerError(
                "RELEASE_LEDGER_HISTORY_MUTATED",
                "prior release reservations must remain an exact prefix",
            )
        appended = reservations[len(previous_reservations) :]
        if appended != sorted(appended, key=_workflow_sort_key):
            raise ReleaseLedgerError(
                "RELEASE_LEDGER_APPEND_BATCH_ORDER_INVALID",
                "new release reservations must be sorted within the "
                "contiguous append batch",
            )
    return {
        "schema": RELEASE_LEDGER_SCHEMA,
        "reservations": reservations,
    }


def empty_release_ledger_bytes() -> bytes:
    return canonical_json_bytes(
        {"schema": RELEASE_LEDGER_SCHEMA, "reservations": []}
    )


def append_release_reservations(
    ledger_bytes: bytes,
    reservations: Iterable[Mapping[str, object]],
) -> bytes:
    ledger = validate_release_ledger_bytes(ledger_bytes)
    appended = [dict(item) for item in reservations]
    if not appended:
        raise ReleaseLedgerError(
            "RELEASE_LEDGER_APPEND_BATCH_EMPTY",
            "a release-ledger append batch must not be empty",
        )
    candidate = {
        "schema": RELEASE_LEDGER_SCHEMA,
        "reservations": [
            *ledger["reservations"],
            *appended,
        ],
    }
    encoded = canonical_json_bytes(candidate)
    validate_release_ledger_bytes(
        encoded, previous_ledger_bytes=ledger_bytes
    )
    return encoded


def first_introduction_inventory_sha256(
    raw_inventory: bytes,
) -> str:
    if not isinstance(raw_inventory, bytes):
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_INVENTORY_INVALID",
            "raw Git inventory must be exact bytes",
        )
    preimage = (
        FIRST_INTRODUCTION_INVENTORY_DOMAIN
        + struct.pack(">Q", len(raw_inventory))
        + raw_inventory
    )
    return hashlib.sha256(preimage).hexdigest()


def _run_git(
    repository: Path,
    arguments: Sequence[str],
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_GIT_UNAVAILABLE",
            "Git could not be launched for immutable provenance validation",
        ) from exc
    if completed.returncode != 0:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_GIT_FAILED",
            "Git could not resolve immutable provenance objects",
            details={
                "operation": list(arguments),
                "returncode": completed.returncode,
            },
        )
    return completed.stdout


def _decode_git_line(value: bytes, *, label: str) -> str:
    try:
        text = value.decode("ascii", "strict").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_GIT_INVALID",
            "Git returned a non-ASCII object identity",
            details={"label": label},
        ) from exc
    return text


def _git_inventory_paths(raw_inventory: bytes) -> tuple[str, ...]:
    paths: list[str] = []
    for record in raw_inventory.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, object_id = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8", "strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseLedgerError(
                "FIRST_INTRODUCTION_INVENTORY_INVALID",
                "raw Git tree inventory has an unexpected record",
            ) from exc
        if (
            mode not in {b"100644", b"100755", b"120000", b"160000"}
            or object_type not in {b"blob", b"commit"}
            or not _SHA1_RE.fullmatch(
                object_id.decode("ascii", "strict")
            )
            or not path
            or "\x00" in path
        ):
            raise ReleaseLedgerError(
                "FIRST_INTRODUCTION_INVENTORY_INVALID",
                "raw Git tree inventory contains an invalid entry",
                details={"path": path},
            )
        paths.append(path)
    if tuple(path.encode("utf-8") for path in paths) != tuple(
        sorted(path.encode("utf-8") for path in paths)
    ):
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_INVENTORY_INVALID",
            "raw Git tree inventory is not path-byte sorted",
        )
    return tuple(paths)


def observe_first_introduction_git_inventory(
    repository: Path,
) -> GitInventoryEvidence:
    root = repository.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_GIT_INVALID",
            "source repository must be a directory",
        )
    object_format = _decode_git_line(
        _run_git(root, ["rev-parse", "--show-object-format"]),
        label="object-format",
    )
    resolved_commit = _decode_git_line(
        _run_git(
            root,
            [
                "rev-parse",
                "--verify",
                f"{FIRST_INTRODUCTION_BASE_COMMIT}^{{commit}}",
            ],
        ),
        label="base-commit",
    )
    resolved_tree = _decode_git_line(
        _run_git(
            root,
            [
                "rev-parse",
                "--verify",
                f"{FIRST_INTRODUCTION_BASE_COMMIT}^{{tree}}",
            ],
        ),
        label="base-tree",
    )
    raw_inventory = _run_git(
        root,
        [
            "ls-tree",
            "-rz",
            "--full-tree",
            FIRST_INTRODUCTION_BASE_COMMIT,
        ],
    )
    paths = _git_inventory_paths(raw_inventory)
    observed_digest = first_introduction_inventory_sha256(raw_inventory)
    expected = (
        object_format == FIRST_INTRODUCTION_OBJECT_FORMAT
        and resolved_commit == FIRST_INTRODUCTION_BASE_COMMIT
        and resolved_tree == FIRST_INTRODUCTION_BASE_TREE
        and len(raw_inventory)
        == FIRST_INTRODUCTION_RAW_INVENTORY_BYTES
        and observed_digest
        == FIRST_INTRODUCTION_INVENTORY_SHA256
    )
    if not expected:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_BASE_MISMATCH",
            "immutable first-introduction Git evidence does not match",
            details={
                "object_format": object_format,
                "base_commit": resolved_commit,
                "base_tree": resolved_tree,
                "raw_inventory_bytes": len(raw_inventory),
                "inventory_sha256": observed_digest,
            },
        )
    if any(
        path == "workflows" or path.startswith("workflows/")
        for path in paths
    ):
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_IDENTITY_PREEXISTED",
            "base tree already contains package workflow identities",
        )
    return GitInventoryEvidence(
        object_format=object_format,
        base_commit=resolved_commit,
        base_tree=resolved_tree,
        raw_size=len(raw_inventory),
        inventory_sha256=observed_digest,
        paths=paths,
    )


def discover_introduced_identity_keys(
    plugin_root: Path,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    root = plugin_root.expanduser().resolve(strict=True)
    workflows_root = root / "workflows"
    try:
        catalog = json.loads(
            (workflows_root / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseLedgerError(
            "RELEASE_PACKAGE_INVALID",
            "workflow catalog cannot be read for release provenance",
        ) from exc
    bundles = catalog.get("bundles") if isinstance(catalog, dict) else None
    if not isinstance(bundles, list):
        raise ReleaseLedgerError(
            "RELEASE_PACKAGE_INVALID",
            "workflow catalog bundle inventory is invalid",
        )
    workflows: list[dict[str, object]] = []
    workflow_keys: set[tuple[str, int]] = set()
    for index, bundle in enumerate(bundles):
        if not isinstance(bundle, dict):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow catalog bundle entry is invalid",
                details={"index": index},
            )
        workflow_id = _stable_id(
            bundle.get("workflow_id"),
            pointer=f"/bundles/{index}/workflow_id",
        )
        workflow_version = _positive_version(
            bundle.get("workflow_version"),
            pointer=f"/bundles/{index}/workflow_version",
        )
        key = (workflow_id, workflow_version)
        if key in workflow_keys:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow catalog has duplicate identity keys",
            )
        workflow_keys.add(key)
        workflows.append(
            {
                "workflow_id": workflow_id,
                "workflow_version": workflow_version,
            }
        )

    handlers: list[dict[str, object]] = []
    handler_keys: set[tuple[bytes, bytes, bytes, bytes]] = set()
    for registry, filename in _RUNTIME_MANIFESTS:
        try:
            manifest = json.loads(
                (
                    workflows_root / "runtime" / filename
                ).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "runtime handler manifest cannot be read",
                details={"registry": registry},
            ) from exc
        entries = (
            manifest.get("entries")
            if isinstance(manifest, dict)
            else None
        )
        if not isinstance(entries, list):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "runtime handler manifest entries are invalid",
                details={"registry": registry},
            )
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "runtime handler entry is invalid",
                    details={"registry": registry, "index": index},
                )
            identifier = _stable_id(
                entry.get("id"),
                pointer=f"/{registry}/{index}/id",
            )
            item = {
                "registry": registry,
                "id": identifier,
                "version": _handler_version(
                    identifier, pointer=f"/{registry}/{index}/id"
                ),
                "contract_id": _stable_id(
                    entry.get("contract_id"),
                    pointer=f"/{registry}/{index}/contract_id",
                ),
            }
            key = _handler_sort_key(item)
            if key in handler_keys:
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "runtime handler identity keys are duplicated",
                    details={"registry": registry, "id": identifier},
                )
            handler_keys.add(key)
            handlers.append(item)
    return (
        tuple(sorted(workflows, key=_workflow_sort_key)),
        tuple(sorted(handlers, key=_handler_sort_key)),
    )


def _validate_introduced_workflows(
    value: object,
    *,
    pointer: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReleaseLedgerError(
            "RELEASE_PROVENANCE_IDENTITY_SET_INVALID",
            "introduced workflow identities must be a strict list",
            details={"pointer": pointer},
        )
    result: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        item_pointer = f"{pointer}/{index}"
        item = _expect_object(
            raw,
            pointer=item_pointer,
            fields=_INTRODUCED_WORKFLOW_FIELDS,
        )
        result.append(
            {
                "workflow_id": _stable_id(
                    item["workflow_id"],
                    pointer=f"{item_pointer}/workflow_id",
                ),
                "workflow_version": _positive_version(
                    item["workflow_version"],
                    pointer=f"{item_pointer}/workflow_version",
                ),
            }
        )
    keys = [_workflow_sort_key(item) for item in result]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ReleaseLedgerError(
            "RELEASE_PROVENANCE_IDENTITY_SET_INVALID",
            "introduced workflow identities must be sorted and unique",
            details={"pointer": pointer},
        )
    return result


def _validate_introduced_handlers(
    value: object,
    *,
    pointer: str,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ReleaseLedgerError(
            "RELEASE_PROVENANCE_IDENTITY_SET_INVALID",
            "introduced handler identities must be a strict list",
            details={"pointer": pointer},
        )
    result = [
        _validate_handler_entry(
            raw,
            pointer=f"{pointer}/{index}",
            implementation_required=False,
        )
        for index, raw in enumerate(value)
    ]
    keys = [_handler_sort_key(item) for item in result]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise ReleaseLedgerError(
            "RELEASE_PROVENANCE_IDENTITY_SET_INVALID",
            "introduced handler identities must be sorted and unique",
            details={"pointer": pointer},
        )
    return result


def validate_first_introduction_bytes(
    source: bytes,
    *,
    repository: Path,
    plugin_root: Path,
) -> tuple[dict[str, object], str]:
    value = parse_canonical_json_bytes(
        source, label="first-introduction provenance"
    )
    manifest = _expect_object(
        value, pointer="/", fields=_FIRST_INTRODUCTION_FIELDS
    )
    fixed = {
        "schema": FIRST_INTRODUCTION_SCHEMA,
        "change_id": FIRST_INTRODUCTION_CHANGE_ID,
        "git_object_format": FIRST_INTRODUCTION_OBJECT_FORMAT,
        "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
        "base_tree": FIRST_INTRODUCTION_BASE_TREE,
        "inventory_contract": (
            FIRST_INTRODUCTION_INVENTORY_CONTRACT
        ),
        "inventory_sha256": FIRST_INTRODUCTION_INVENTORY_SHA256,
    }
    for field, expected in fixed.items():
        if manifest[field] != expected:
            raise ReleaseLedgerError(
                "FIRST_INTRODUCTION_MANIFEST_MISMATCH",
                "first-introduction immutable binding does not match",
                details={"field": field},
            )
    evidence = observe_first_introduction_git_inventory(repository)
    package_workflows, package_handlers = (
        discover_introduced_identity_keys(plugin_root)
    )
    workflows = _validate_introduced_workflows(
        manifest["introduced_workflows"],
        pointer="/introduced_workflows",
    )
    handlers = _validate_introduced_handlers(
        manifest["introduced_handlers"],
        pointer="/introduced_handlers",
    )
    package_workflow_keys = {
        _workflow_sort_key(item) for item in package_workflows
    }
    package_handler_keys = {
        _handler_sort_key(item) for item in package_handlers
    }
    if (
        any(
            _workflow_sort_key(item) not in package_workflow_keys
            for item in workflows
        )
        or any(
            _handler_sort_key(item) not in package_handler_keys
            for item in handlers
        )
    ):
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_IDENTITY_SET_MISMATCH",
            "historical first-introduction identities must remain present "
            "in the current package",
        )
    normalized = {
        **fixed,
        "introduced_workflows": workflows,
        "introduced_handlers": handlers,
    }
    if evidence.inventory_sha256 != normalized["inventory_sha256"]:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_INVENTORY_MISMATCH",
            "first-introduction inventory digest does not match Git",
        )
    digest = hashlib.sha256(source).hexdigest()
    if digest != FIRST_INTRODUCTION_MANIFEST_SHA256:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_HISTORY_MUTATED",
            "the frozen first-introduction manifest bytes changed",
            details={
                "expected_sha256": FIRST_INTRODUCTION_MANIFEST_SHA256,
                "actual_sha256": digest,
            },
        )
    return normalized, digest


def build_first_introduction_bytes(
    *,
    repository: Path,
    plugin_root: Path,
) -> bytes:
    evidence = observe_first_introduction_git_inventory(repository)
    workflows, handlers = discover_introduced_identity_keys(plugin_root)
    encoded = canonical_json_bytes(
        {
            "schema": FIRST_INTRODUCTION_SCHEMA,
            "change_id": FIRST_INTRODUCTION_CHANGE_ID,
            "git_object_format": evidence.object_format,
            "base_commit": evidence.base_commit,
            "base_tree": evidence.base_tree,
            "inventory_contract": (
                FIRST_INTRODUCTION_INVENTORY_CONTRACT
            ),
            "inventory_sha256": evidence.inventory_sha256,
            "introduced_workflows": list(workflows),
            "introduced_handlers": list(handlers),
        }
    )
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != FIRST_INTRODUCTION_MANIFEST_SHA256:
        raise ReleaseLedgerError(
            "FIRST_INTRODUCTION_ALREADY_FROZEN",
            "the immutable first-introduction manifest cannot be regenerated "
            "from a later package identity set",
            details={
                "expected_sha256": FIRST_INTRODUCTION_MANIFEST_SHA256,
                "actual_sha256": digest,
            },
        )
    return encoded


def validate_reserved_v3_ledger_bytes(
    source: bytes,
    *,
    plugin_root: Path,
) -> dict[str, object]:
    """Validate the exact immutable four-reservation V3 ledger prefix."""

    digest = hashlib.sha256(source).hexdigest()
    if digest != RESERVED_V3_LEDGER_SHA256:
        raise ReleaseLedgerError(
            "RESERVED_V3_LEDGER_MISMATCH",
            "reserved V3 ledger bytes do not match the immutable prefix",
            details={
                "expected_sha256": RESERVED_V3_LEDGER_SHA256,
                "actual_sha256": digest,
            },
        )
    ledger = validate_ledger_against_package(
        source,
        plugin_root=plugin_root,
    )
    if len(ledger["reservations"]) != RESERVED_V3_RESERVATION_COUNT:
        raise ReleaseLedgerError(
            "RESERVED_V3_LEDGER_COUNT_MISMATCH",
            "reserved V3 ledger must contain exactly four reservations",
        )
    return ledger


def introduction_epoch_append_batch_sha256(
    reservations: Iterable[Mapping[str, object]],
) -> str:
    """Hash one complete, normalized, internally sorted append batch."""

    materialized = [dict(item) for item in reservations]
    if not materialized:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_APPEND_BATCH_EMPTY",
            "an introduction epoch must reserve at least one workflow",
        )
    encoded_ledger = canonical_json_bytes(
        {
            "schema": RELEASE_LEDGER_SCHEMA,
            "reservations": materialized,
        }
    )
    normalized = validate_release_ledger_bytes(encoded_ledger)[
        "reservations"
    ]
    if normalized != sorted(normalized, key=_workflow_sort_key):
        raise ReleaseLedgerError(
            "RELEASE_LEDGER_APPEND_BATCH_ORDER_INVALID",
            "introduction-epoch reservations must be sorted within the batch",
        )
    batch_bytes = canonical_json_bytes(normalized)
    preimage = (
        INTRODUCTION_EPOCH_APPEND_BATCH_DOMAIN
        + struct.pack(">Q", len(batch_bytes))
        + batch_bytes
    )
    return hashlib.sha256(preimage).hexdigest()


def introduction_epoch_cumulative_identity_set_sha256(
    workflows: Iterable[Mapping[str, object]],
    handlers: Iterable[Mapping[str, object]],
) -> str:
    """Hash the complete cumulative provenance identity-key sets."""

    materialized_workflows = [dict(item) for item in workflows]
    materialized_handlers = [dict(item) for item in handlers]
    normalized_workflows = _validate_introduced_workflows(
        materialized_workflows,
        pointer="/workflows",
    )
    normalized_handlers = _validate_introduced_handlers(
        materialized_handlers,
        pointer="/handlers",
    )
    identity_bytes = canonical_json_bytes(
        {
            "handlers": normalized_handlers,
            "workflows": normalized_workflows,
        }
    )
    preimage = (
        INTRODUCTION_EPOCH_CUMULATIVE_IDENTITY_SET_DOMAIN
        + struct.pack(">Q", len(identity_bytes))
        + identity_bytes
    )
    return hashlib.sha256(preimage).hexdigest()


def _parse_activation_bytes(source: bytes) -> dict[str, object]:
    if not isinstance(source, bytes):
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
            "predecessor activation evidence must be exact bytes",
        )
    try:
        value = json.loads(
            source.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_int=_parse_json_integer,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeError,
        ValueError,
        _DuplicateJsonKey,
    ) as exc:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
            "predecessor activation evidence is invalid",
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "profiles"}
        or value.get("schema") != "dev-flow-workflow-activation/v1"
        or not isinstance(value.get("profiles"), list)
    ):
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
            "predecessor activation evidence has the wrong schema",
        )
    return value


def _validate_reserved_unexposed_activation(
    source: bytes,
    *,
    predecessor_workflows: Sequence[Mapping[str, object]],
) -> str:
    digest = hashlib.sha256(source).hexdigest()
    if digest != RESERVED_V3_ACTIVATION_SHA256:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ACTIVATION_MISMATCH",
            "reserved V3 activation bytes do not match the frozen identity",
            details={
                "expected_sha256": RESERVED_V3_ACTIVATION_SHA256,
                "actual_sha256": digest,
            },
        )
    value = _parse_activation_bytes(source)
    expected = {
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        for item in predecessor_workflows
        if int(item["workflow_version"]) == 3
        and str(item["workflow_id"]) in {"full", "lite"}
    }
    observed: set[tuple[str, int]] = set()
    profile_keys: set[tuple[str, int, str]] = set()
    for index, raw in enumerate(value["profiles"]):
        if not isinstance(raw, dict):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
                "activation profiles must be strict objects",
                details={"index": index},
            )
        workflow_id = raw.get("workflow_id")
        workflow_version = raw.get("workflow_version")
        execution_profile = raw.get("execution_profile")
        active = raw.get("active")
        if (
            not isinstance(workflow_id, str)
            or isinstance(workflow_version, bool)
            or not isinstance(workflow_version, int)
            or not isinstance(execution_profile, str)
            or not isinstance(active, bool)
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
                "activation profile identity is malformed",
                details={"index": index},
            )
        profile_key = (
            workflow_id,
            workflow_version,
            execution_profile,
        )
        if profile_key in profile_keys:
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_ACTIVATION_INVALID",
                "activation profile identity is duplicated",
                details={"index": index},
            )
        profile_keys.add(profile_key)
        workflow_key = (workflow_id, workflow_version)
        if workflow_key in expected:
            observed.add(workflow_key)
            if active:
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_PREDECESSOR_EXPOSED",
                    "reserved V3 predecessor profiles must all be inactive",
                    details={"profile": list(profile_key)},
                )
    if observed != expected:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ACTIVATION_MISMATCH",
            "activation evidence does not enumerate the reserved V3 workflows",
            details={
                "missing": [
                    list(item) for item in sorted(expected - observed)
                ]
            },
        )
    return digest


def _expected_epoch_id(epoch_sequence: int) -> str:
    return f"introduction-epoch-{epoch_sequence}"


def _parse_introduction_epoch_bytes(
    source: bytes,
) -> dict[str, object]:
    value = parse_canonical_json_bytes(
        source,
        label="introduction epoch provenance",
    )
    if not isinstance(value, dict):
        raise ReleaseLedgerError(
            "RELEASE_SCHEMA_INVALID",
            "introduction epoch provenance must be an object",
        )
    predecessor_kind = value.get("predecessor_kind")
    if predecessor_kind == INTRODUCTION_EPOCH_RESERVED_UNEXPOSED:
        fields = (
            _INTRODUCTION_EPOCH_COMMON_FIELDS
            | _INTRODUCTION_EPOCH_RESERVED_UNEXPOSED_FIELDS
        )
    elif predecessor_kind == INTRODUCTION_EPOCH_OFFICIAL_RELEASE:
        fields = (
            _INTRODUCTION_EPOCH_COMMON_FIELDS
            | _INTRODUCTION_EPOCH_OFFICIAL_RELEASE_FIELDS
        )
    else:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_PREDECESSOR_KIND_UNSUPPORTED",
            "introduction epoch predecessor kind is unsupported",
        )
    epoch = _expect_object(value, pointer="/", fields=fields)
    sequence = _positive_version(
        epoch["epoch_sequence"],
        pointer="/epoch_sequence",
    )
    epoch_id = _stable_id(epoch["epoch_id"], pointer="/epoch_id")
    if epoch_id != _expected_epoch_id(sequence):
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ID_INVALID",
            "epoch identity must be the canonical identity for its sequence",
            details={
                "expected": _expected_epoch_id(sequence),
                "actual": epoch_id,
            },
        )
    for field in (
        "predecessor_provenance_sha256",
        "predecessor_ledger_sha256",
        "inventory_sha256",
        "append_batch_sha256",
        "result_ledger_sha256",
        "cumulative_identity_set_sha256",
    ):
        _digest(epoch[field], pointer=f"/{field}")
    if predecessor_kind == INTRODUCTION_EPOCH_RESERVED_UNEXPOSED:
        for field in (
            "predecessor_first_introduction_sha256",
            "predecessor_activation_sha256",
        ):
            _digest(epoch[field], pointer=f"/{field}")
        for field in (
            "reviewed",
            "handoff",
            "published",
            "installed",
            "activated",
            "pin_eligible",
        ):
            if epoch[field] is not False:
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_PREDECESSOR_STATUS_INVALID",
                    "reserved-unexposed status fields are declarations and "
                    "must all remain explicitly false",
                    details={"field": field},
                )
    else:
        _digest(
            epoch["predecessor_review_sha256"],
            pointer="/predecessor_review_sha256",
        )
        _digest(
            epoch["predecessor_handoff_sha256"],
            pointer="/predecessor_handoff_sha256",
        )
    for field in (
        "predecessor_reservation_count",
        "append_batch_start",
        "append_batch_count",
    ):
        count = epoch[field]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_FIELD_INVALID",
                "epoch count fields must be non-negative integers",
                details={"field": field},
            )
    _validate_introduced_workflows(
        epoch["introduced_workflows"],
        pointer="/introduced_workflows",
    )
    _validate_introduced_handlers(
        epoch["introduced_handlers"],
        pointer="/introduced_handlers",
    )
    return dict(epoch)


def _package_introduction_material(
    plugin_root: Path,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[tuple[str, int], dict[str, object]],
]:
    package_workflows, package_handlers = discover_introduced_identity_keys(
        plugin_root
    )
    reservations: dict[tuple[str, int], dict[str, object]] = {}
    for item in package_release_reservations(plugin_root):
        key = (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        if key in reservations:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "package reservations contain a duplicate workflow key",
                details={"workflow": list(key)},
            )
        reservations[key] = dict(item)
    return (
        [dict(item) for item in package_workflows],
        [dict(item) for item in package_handlers],
        reservations,
    )


def _validate_epoch_ledger_transition(
    *,
    predecessor_ledger_bytes: bytes,
    result_ledger_bytes: bytes,
    introduced_workflows: Sequence[Mapping[str, object]],
    introduced_handlers: Sequence[Mapping[str, object]],
    predecessor_handler_keys: set[
        tuple[bytes, bytes, bytes, bytes]
    ],
    package_reservations: Mapping[
        tuple[str, int], Mapping[str, object]
    ],
) -> dict[str, object]:
    predecessor = validate_release_ledger_bytes(
        predecessor_ledger_bytes
    )
    result = validate_release_ledger_bytes(
        result_ledger_bytes,
        previous_ledger_bytes=predecessor_ledger_bytes,
    )
    predecessor_count = len(predecessor["reservations"])
    exact_prefix = canonical_json_bytes(
        {
            "schema": RELEASE_LEDGER_SCHEMA,
            "reservations": result["reservations"][
                :predecessor_count
            ],
        }
    )
    if exact_prefix != predecessor_ledger_bytes:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_PREDECESSOR_MISMATCH",
            "result ledger does not reconstruct the exact predecessor bytes",
        )
    suffix = result["reservations"][predecessor_count:]
    if not suffix:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_APPEND_BATCH_EMPTY",
            "an introduction epoch must append one non-empty batch",
        )
    workflow_keys = [
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        for item in introduced_workflows
    ]
    suffix_keys = [
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        for item in suffix
    ]
    if suffix_keys != workflow_keys:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_WORKFLOW_SUFFIX_MISMATCH",
            "ledger suffix workflow keys must equal the introduced keys",
        )
    for reservation in suffix:
        key = (
            str(reservation["workflow_id"]),
            int(reservation["workflow_version"]),
        )
        if package_reservations.get(key) != reservation:
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_APPEND_BATCH_MISMATCH",
                "ledger suffix reservation differs from exact package bytes",
                details={"workflow": list(key)},
            )
    suffix_handler_keys = {
        _handler_sort_key(handler)
        for reservation in suffix
        for handler in reservation["handlers"]
    }
    introduced_handler_keys = {
        _handler_sort_key(item) for item in introduced_handlers
    }
    expected_introduced_handler_keys = (
        suffix_handler_keys - predecessor_handler_keys
    )
    if introduced_handler_keys != expected_introduced_handler_keys:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_HANDLER_DELTA_MISMATCH",
            "introduced handler identities must equal the handlers first "
            "referenced by this append batch relative to complete "
            "predecessor provenance",
            details={
                "missing": [
                    [
                        component.decode("utf-8")
                        for component in item
                    ]
                    for item in sorted(
                        expected_introduced_handler_keys
                        - introduced_handler_keys
                    )
                ],
                "extra": [
                    [
                        component.decode("utf-8")
                        for component in item
                    ]
                    for item in sorted(
                        introduced_handler_keys
                        - expected_introduced_handler_keys
                    )
                ],
            },
        )
    return {
        "predecessor": predecessor,
        "result": result,
        "predecessor_count": predecessor_count,
        "suffix": suffix,
        "batch_sha256": introduction_epoch_append_batch_sha256(
            suffix
        ),
        "result_sha256": hashlib.sha256(
            result_ledger_bytes
        ).hexdigest(),
    }


def _validate_introduction_epoch_chain(
    epochs: Iterable[IntroductionEpochProvenanceInput],
    *,
    first_introduction_bytes: bytes,
    reserved_v3_ledger_bytes: bytes,
    reserved_v3_activation_bytes: bytes,
    repository: Path,
    plugin_root: Path,
    require_complete_package: bool,
) -> tuple[
    tuple[IntroductionEpochValidation, ...],
    dict[str, object],
]:
    entries = tuple(epochs)
    first, first_sha256 = validate_first_introduction_bytes(
        first_introduction_bytes,
        repository=repository,
        plugin_root=plugin_root,
    )
    reserved_v3 = validate_reserved_v3_ledger_bytes(
        reserved_v3_ledger_bytes,
        plugin_root=plugin_root,
    )
    activation_sha256 = _validate_reserved_unexposed_activation(
        reserved_v3_activation_bytes,
        predecessor_workflows=first["introduced_workflows"],
    )
    (
        package_workflows,
        package_handlers,
        package_reservations,
    ) = _package_introduction_material(plugin_root)
    package_workflow_keys = {
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        for item in package_workflows
    }
    package_handler_keys = {
        _handler_sort_key(item) for item in package_handlers
    }
    cumulative_workflows = [
        dict(item) for item in first["introduced_workflows"]
    ]
    cumulative_handlers = [
        dict(item) for item in first["introduced_handlers"]
    ]
    cumulative_workflow_keys = {
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        for item in cumulative_workflows
    }
    cumulative_handler_keys = {
        _handler_sort_key(item) for item in cumulative_handlers
    }
    predecessor_ledger_bytes = reserved_v3_ledger_bytes
    predecessor_provenance_sha256 = first_sha256
    epoch_ids: set[str] = set()
    validations: list[IntroductionEpochValidation] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, IntroductionEpochProvenanceInput):
            raise ReleaseLedgerError(
                "RELEASE_PROVENANCE_INPUT_INVALID",
                "introduction epoch input is invalid",
                details={"index": index},
            )
        epoch = _parse_introduction_epoch_bytes(
            entry.manifest_bytes
        )
        sequence = int(epoch["epoch_sequence"])
        expected_sequence = index + 1
        if sequence != expected_sequence:
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_SEQUENCE_INVALID",
                "epoch sequence must be contiguous and start at one",
                details={
                    "expected": expected_sequence,
                    "actual": sequence,
                },
            )
        epoch_id = str(epoch["epoch_id"])
        if epoch_id in epoch_ids:
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_ID_DUPLICATE",
                "epoch identities must be unique across the chain",
            )
        epoch_ids.add(epoch_id)
        predecessor_kind = str(epoch["predecessor_kind"])
        if index == 0:
            if predecessor_kind != INTRODUCTION_EPOCH_RESERVED_UNEXPOSED:
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_PREDECESSOR_KIND_INVALID",
                    "the factual V3 predecessor must use reserved-unexposed",
                )
            if (
                entry.predecessor_review_bytes is not None
                or entry.predecessor_handoff_bytes is not None
            ):
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_FALSE_HANDOFF",
                    "reserved-unexposed history must not fabricate review "
                    "or handoff evidence",
                )
            branch_expected: dict[str, object] = {
                "predecessor_first_introduction_sha256": first_sha256,
                "predecessor_activation_sha256": activation_sha256,
                "reviewed": False,
                "handoff": False,
                "published": False,
                "installed": False,
                "activated": False,
                "pin_eligible": False,
            }
        else:
            if predecessor_kind != INTRODUCTION_EPOCH_OFFICIAL_RELEASE:
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_PREDECESSOR_KIND_INVALID",
                    "later epochs must continue from an official reviewed "
                    "release",
                )
            if (
                entry.predecessor_review_bytes is None
                or entry.predecessor_handoff_bytes is None
            ):
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_OFFICIAL_EVIDENCE_MISSING",
                    "official-release continuity requires review and handoff",
                )
            handoff = validate_release_handoff_bytes(
                entry.predecessor_handoff_bytes,
                ledger_bytes=predecessor_ledger_bytes,
                review_bytes=entry.predecessor_review_bytes,
                expected_provenance_sha256=(
                    predecessor_provenance_sha256
                ),
            )
            branch_expected = {
                "predecessor_review_sha256": hashlib.sha256(
                    entry.predecessor_review_bytes
                ).hexdigest(),
                "predecessor_handoff_sha256": hashlib.sha256(
                    entry.predecessor_handoff_bytes
                ).hexdigest(),
            }
            if handoff["provenance_sha256"] != (
                predecessor_provenance_sha256
            ):
                raise ReleaseLedgerError(
                    "INTRODUCTION_EPOCH_OFFICIAL_EVIDENCE_MISMATCH",
                    "official handoff does not bind predecessor provenance",
                )

        introduced_workflows = _validate_introduced_workflows(
            epoch["introduced_workflows"],
            pointer="/introduced_workflows",
        )
        introduced_handlers = _validate_introduced_handlers(
            epoch["introduced_handlers"],
            pointer="/introduced_handlers",
        )
        if not introduced_workflows:
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_IDENTITY_SET_EMPTY",
                "a successor epoch must introduce at least one workflow",
            )
        introduced_workflow_keys = {
            (
                str(item["workflow_id"]),
                int(item["workflow_version"]),
            )
            for item in introduced_workflows
        }
        introduced_handler_keys = {
            _handler_sort_key(item) for item in introduced_handlers
        }
        if (
            introduced_workflow_keys & cumulative_workflow_keys
            or introduced_handler_keys & cumulative_handler_keys
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_HISTORY_OVERLAP",
                "an epoch must not reintroduce a historical identity",
            )
        if (
            not introduced_workflow_keys <= package_workflow_keys
            or not introduced_handler_keys <= package_handler_keys
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_IDENTITY_SET_MISMATCH",
                "introduced identities must exist in the exact package",
            )
        ledger_transition = _validate_epoch_ledger_transition(
            predecessor_ledger_bytes=predecessor_ledger_bytes,
            result_ledger_bytes=entry.result_ledger_bytes,
            introduced_workflows=introduced_workflows,
            introduced_handlers=introduced_handlers,
            predecessor_handler_keys=cumulative_handler_keys,
            package_reservations=package_reservations,
        )
        cumulative_workflows.extend(introduced_workflows)
        cumulative_workflows.sort(key=_workflow_sort_key)
        cumulative_handlers.extend(introduced_handlers)
        cumulative_handlers.sort(key=_handler_sort_key)
        cumulative_workflow_keys.update(introduced_workflow_keys)
        cumulative_handler_keys.update(introduced_handler_keys)
        cumulative_sha256 = (
            introduction_epoch_cumulative_identity_set_sha256(
                cumulative_workflows,
                cumulative_handlers,
            )
        )
        expected: dict[str, object] = {
            "schema": INTRODUCTION_EPOCH_SCHEMA,
            "change_id": FIRST_INTRODUCTION_CHANGE_ID,
            "epoch_id": _expected_epoch_id(sequence),
            "epoch_sequence": sequence,
            "predecessor_kind": predecessor_kind,
            "predecessor_provenance_sha256": (
                predecessor_provenance_sha256
            ),
            "predecessor_ledger_sha256": hashlib.sha256(
                predecessor_ledger_bytes
            ).hexdigest(),
            "predecessor_reservation_count": ledger_transition[
                "predecessor_count"
            ],
            "git_object_format": FIRST_INTRODUCTION_OBJECT_FORMAT,
            "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
            "base_tree": FIRST_INTRODUCTION_BASE_TREE,
            "inventory_contract": (
                FIRST_INTRODUCTION_INVENTORY_CONTRACT
            ),
            "inventory_sha256": FIRST_INTRODUCTION_INVENTORY_SHA256,
            "introduced_workflows": introduced_workflows,
            "introduced_handlers": introduced_handlers,
            "append_batch_start": ledger_transition[
                "predecessor_count"
            ],
            "append_batch_count": len(ledger_transition["suffix"]),
            "append_batch_sha256": ledger_transition["batch_sha256"],
            "result_ledger_sha256": ledger_transition["result_sha256"],
            "cumulative_identity_set_sha256": cumulative_sha256,
            **branch_expected,
        }
        if epoch != expected:
            mismatched = sorted(
                field
                for field in set(epoch) | set(expected)
                if epoch.get(field) != expected.get(field)
            )
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_BINDING_MISMATCH",
                "epoch does not bind the exact chain, package delta, and "
                "ledger transition",
                details={"fields": mismatched},
            )
        provenance_sha256 = hashlib.sha256(
            entry.manifest_bytes
        ).hexdigest()
        validations.append(
            IntroductionEpochValidation(
                manifest=expected,
                provenance_sha256=provenance_sha256,
                result_ledger_sha256=str(
                    ledger_transition["result_sha256"]
                ),
                cumulative_identity_set_sha256=cumulative_sha256,
            )
        )
        predecessor_ledger_bytes = entry.result_ledger_bytes
        predecessor_provenance_sha256 = provenance_sha256

    if require_complete_package and (
        cumulative_workflow_keys != package_workflow_keys
        or cumulative_handler_keys != package_handler_keys
    ):
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_IDENTITY_SET_MISMATCH",
            "complete provenance chain must equal the current package "
            "identity sets",
            details={
                "missing_workflows": [
                    list(item)
                    for item in sorted(
                        package_workflow_keys - cumulative_workflow_keys
                    )
                ],
                "extra_workflows": [
                    list(item)
                    for item in sorted(
                        cumulative_workflow_keys - package_workflow_keys
                    )
                ],
            },
        )
    return (
        tuple(validations),
        {
            "first": first,
            "first_sha256": first_sha256,
            "reserved_v3": reserved_v3,
            "activation_sha256": activation_sha256,
            "predecessor_ledger_bytes": predecessor_ledger_bytes,
            "predecessor_provenance_sha256": (
                predecessor_provenance_sha256
            ),
            "cumulative_workflows": cumulative_workflows,
            "cumulative_handlers": cumulative_handlers,
            "cumulative_workflow_keys": cumulative_workflow_keys,
            "cumulative_handler_keys": cumulative_handler_keys,
            "package_workflows": package_workflows,
            "package_handlers": package_handlers,
            "package_reservations": package_reservations,
        },
    )


def validate_introduction_epoch_chain(
    epochs: Iterable[IntroductionEpochProvenanceInput],
    *,
    first_introduction_bytes: bytes,
    reserved_v3_ledger_bytes: bytes,
    reserved_v3_activation_bytes: bytes,
    repository: Path,
    plugin_root: Path,
) -> tuple[IntroductionEpochValidation, ...]:
    materialized = tuple(epochs)
    if not materialized:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_CHAIN_EMPTY",
            "introduction epoch chain must not be empty",
        )
    validations, _state = _validate_introduction_epoch_chain(
        materialized,
        first_introduction_bytes=first_introduction_bytes,
        reserved_v3_ledger_bytes=reserved_v3_ledger_bytes,
        reserved_v3_activation_bytes=reserved_v3_activation_bytes,
        repository=repository,
        plugin_root=plugin_root,
        require_complete_package=True,
    )
    return validations


def build_introduction_epoch_bytes(
    *,
    epoch_id: str,
    epoch_sequence: int,
    predecessor_first_introduction_bytes: bytes,
    predecessor_ledger_bytes: bytes,
    predecessor_activation_bytes: bytes,
    current_ledger_bytes: bytes,
    repository: Path,
    plugin_root: Path,
    prior_epochs: Iterable[IntroductionEpochProvenanceInput] = (),
    predecessor_review_bytes: Optional[bytes] = None,
    predecessor_handoff_bytes: Optional[bytes] = None,
) -> bytes:
    """Build one strict next epoch without writing package history."""

    normalized_sequence = _positive_version(
        epoch_sequence,
        pointer="/epoch_sequence",
    )
    normalized_epoch_id = _stable_id(epoch_id, pointer="/epoch_id")
    if normalized_epoch_id != _expected_epoch_id(normalized_sequence):
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_ID_INVALID",
            "epoch identity must be the canonical identity for its sequence",
        )
    materialized_prior = tuple(prior_epochs)
    _validations, state = _validate_introduction_epoch_chain(
        materialized_prior,
        first_introduction_bytes=(
            predecessor_first_introduction_bytes
        ),
        reserved_v3_ledger_bytes=predecessor_ledger_bytes,
        reserved_v3_activation_bytes=predecessor_activation_bytes,
        repository=repository,
        plugin_root=plugin_root,
        require_complete_package=False,
    )
    if normalized_sequence != len(materialized_prior) + 1:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_SEQUENCE_INVALID",
            "new epoch sequence must directly follow prior history",
        )
    cumulative_workflow_keys = state["cumulative_workflow_keys"]
    cumulative_handler_keys = state["cumulative_handler_keys"]
    introduced_workflows = [
        dict(item)
        for item in state["package_workflows"]
        if (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        )
        not in cumulative_workflow_keys
    ]
    introduced_handlers = [
        dict(item)
        for item in state["package_handlers"]
        if _handler_sort_key(item) not in cumulative_handler_keys
    ]
    if not introduced_workflows:
        raise ReleaseLedgerError(
            "INTRODUCTION_EPOCH_IDENTITY_SET_EMPTY",
            "new epoch must introduce at least one package workflow",
        )
    ledger_transition = _validate_epoch_ledger_transition(
        predecessor_ledger_bytes=state["predecessor_ledger_bytes"],
        result_ledger_bytes=current_ledger_bytes,
        introduced_workflows=introduced_workflows,
        introduced_handlers=introduced_handlers,
        predecessor_handler_keys=state["cumulative_handler_keys"],
        package_reservations=state["package_reservations"],
    )
    cumulative_workflows = [
        *state["cumulative_workflows"],
        *introduced_workflows,
    ]
    cumulative_workflows.sort(key=_workflow_sort_key)
    cumulative_handlers = [
        *state["cumulative_handlers"],
        *introduced_handlers,
    ]
    cumulative_handlers.sort(key=_handler_sort_key)
    cumulative_sha256 = (
        introduction_epoch_cumulative_identity_set_sha256(
            cumulative_workflows,
            cumulative_handlers,
        )
    )
    predecessor_provenance_sha256 = str(
        state["predecessor_provenance_sha256"]
    )
    if not materialized_prior:
        if (
            predecessor_review_bytes is not None
            or predecessor_handoff_bytes is not None
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_FALSE_HANDOFF",
                "reserved-unexposed predecessor must not supply a V3 "
                "review or handoff",
            )
        predecessor_kind = INTRODUCTION_EPOCH_RESERVED_UNEXPOSED
        branch: dict[str, object] = {
            "predecessor_first_introduction_sha256": state[
                "first_sha256"
            ],
            "predecessor_activation_sha256": state[
                "activation_sha256"
            ],
            "reviewed": False,
            "handoff": False,
            "published": False,
            "installed": False,
            "activated": False,
            "pin_eligible": False,
        }
    else:
        if (
            predecessor_review_bytes is None
            or predecessor_handoff_bytes is None
        ):
            raise ReleaseLedgerError(
                "INTRODUCTION_EPOCH_OFFICIAL_EVIDENCE_MISSING",
                "official-release predecessor requires review and handoff",
            )
        validate_release_handoff_bytes(
            predecessor_handoff_bytes,
            ledger_bytes=state["predecessor_ledger_bytes"],
            review_bytes=predecessor_review_bytes,
            expected_provenance_sha256=(
                predecessor_provenance_sha256
            ),
        )
        predecessor_kind = INTRODUCTION_EPOCH_OFFICIAL_RELEASE
        branch = {
            "predecessor_review_sha256": hashlib.sha256(
                predecessor_review_bytes
            ).hexdigest(),
            "predecessor_handoff_sha256": hashlib.sha256(
                predecessor_handoff_bytes
            ).hexdigest(),
        }
    manifest = {
        "schema": INTRODUCTION_EPOCH_SCHEMA,
        "change_id": FIRST_INTRODUCTION_CHANGE_ID,
        "epoch_id": normalized_epoch_id,
        "epoch_sequence": normalized_sequence,
        "predecessor_kind": predecessor_kind,
        "predecessor_provenance_sha256": (
            predecessor_provenance_sha256
        ),
        "predecessor_ledger_sha256": hashlib.sha256(
            state["predecessor_ledger_bytes"]
        ).hexdigest(),
        "predecessor_reservation_count": ledger_transition[
            "predecessor_count"
        ],
        "git_object_format": FIRST_INTRODUCTION_OBJECT_FORMAT,
        "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
        "base_tree": FIRST_INTRODUCTION_BASE_TREE,
        "inventory_contract": FIRST_INTRODUCTION_INVENTORY_CONTRACT,
        "inventory_sha256": FIRST_INTRODUCTION_INVENTORY_SHA256,
        "introduced_workflows": introduced_workflows,
        "introduced_handlers": introduced_handlers,
        "append_batch_start": ledger_transition["predecessor_count"],
        "append_batch_count": len(ledger_transition["suffix"]),
        "append_batch_sha256": ledger_transition["batch_sha256"],
        "result_ledger_sha256": ledger_transition["result_sha256"],
        "cumulative_identity_set_sha256": cumulative_sha256,
        **branch,
    }
    return canonical_json_bytes(manifest)


def validate_introduction_epoch_bytes(
    source: bytes,
    *,
    predecessor_first_introduction_bytes: bytes,
    predecessor_ledger_bytes: bytes,
    predecessor_activation_bytes: bytes,
    current_ledger_bytes: bytes,
    repository: Path,
    plugin_root: Path,
    prior_epochs: Iterable[IntroductionEpochProvenanceInput] = (),
    predecessor_review_bytes: Optional[bytes] = None,
    predecessor_handoff_bytes: Optional[bytes] = None,
) -> tuple[dict[str, object], str]:
    materialized_prior = tuple(prior_epochs)
    current = IntroductionEpochProvenanceInput(
        manifest_bytes=source,
        result_ledger_bytes=current_ledger_bytes,
        predecessor_review_bytes=predecessor_review_bytes,
        predecessor_handoff_bytes=predecessor_handoff_bytes,
    )
    validations = validate_introduction_epoch_chain(
        (*materialized_prior, current),
        first_introduction_bytes=(
            predecessor_first_introduction_bytes
        ),
        reserved_v3_ledger_bytes=predecessor_ledger_bytes,
        reserved_v3_activation_bytes=predecessor_activation_bytes,
        repository=repository,
        plugin_root=plugin_root,
    )
    validated = validations[-1]
    return dict(validated.manifest), validated.provenance_sha256


def validate_release_review_bytes(
    source: bytes,
    *,
    provenance_sha256: str,
    candidate_sha256: str,
) -> dict[str, object]:
    value = parse_canonical_json_bytes(source, label="release review")
    review = _expect_object(value, pointer="/", fields=_REVIEW_FIELDS)
    expected = {
        "schema": RELEASE_REVIEW_SCHEMA,
        "provenance_sha256": _digest(
            provenance_sha256, pointer="/provenance_sha256"
        ),
        "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
        "base_tree": FIRST_INTRODUCTION_BASE_TREE,
        "inventory_sha256": FIRST_INTRODUCTION_INVENTORY_SHA256,
        "candidate_sha256": _digest(
            candidate_sha256, pointer="/candidate_sha256"
        ),
    }
    reviewer_id = _stable_id(
        review["reviewer_id"], pointer="/reviewer_id"
    )
    for field, expected_value in expected.items():
        if review[field] != expected_value:
            raise ReleaseLedgerError(
                "RELEASE_REVIEW_BINDING_MISMATCH",
                "release review does not bind exact provenance/candidate",
                details={"field": field},
            )
    return {"reviewer_id": reviewer_id, **expected}


def validate_release_handoff_bytes(
    source: bytes,
    *,
    ledger_bytes: bytes,
    review_bytes: bytes,
    expected_provenance_sha256: Optional[str] = None,
    expected_candidate_sha256: Optional[str] = None,
) -> dict[str, object]:
    """Validate one external handoff against its exact ledger and review."""

    validate_release_ledger_bytes(ledger_bytes)
    value = parse_canonical_json_bytes(
        source, label="release handoff"
    )
    handoff = _expect_object(
        value, pointer="/", fields=_RELEASE_HANDOFF_FIELDS
    )
    normalized = {
        "schema": RELEASE_HANDOFF_SCHEMA,
        "release_id": _stable_id(
            handoff["release_id"], pointer="/release_id"
        ),
        "ledger_sha256": _digest(
            handoff["ledger_sha256"], pointer="/ledger_sha256"
        ),
        "review_sha256": _digest(
            handoff["review_sha256"], pointer="/review_sha256"
        ),
        "reviewer_id": _stable_id(
            handoff["reviewer_id"], pointer="/reviewer_id"
        ),
        "provenance_sha256": _digest(
            handoff["provenance_sha256"],
            pointer="/provenance_sha256",
        ),
        "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
        "base_tree": FIRST_INTRODUCTION_BASE_TREE,
        "inventory_sha256": FIRST_INTRODUCTION_INVENTORY_SHA256,
        "candidate_sha256": _digest(
            handoff["candidate_sha256"],
            pointer="/candidate_sha256",
        ),
        "archive_manifest_sha256": _digest(
            handoff["archive_manifest_sha256"],
            pointer="/archive_manifest_sha256",
        ),
        "archive_sha256": _digest(
            handoff["archive_sha256"], pointer="/archive_sha256"
        ),
    }
    for field in (
        "schema",
        "base_commit",
        "base_tree",
        "inventory_sha256",
    ):
        if handoff[field] != normalized[field]:
            raise ReleaseLedgerError(
                "RELEASE_HANDOFF_BINDING_MISMATCH",
                "release handoff contains a mismatched fixed binding",
                details={"field": field},
            )
    expected_ledger_sha256 = hashlib.sha256(
        ledger_bytes
    ).hexdigest()
    expected_review_sha256 = hashlib.sha256(
        review_bytes
    ).hexdigest()
    if handoff["ledger_sha256"] != expected_ledger_sha256:
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_LEDGER_MISMATCH",
            "release handoff does not bind the exact previous ledger",
        )
    if handoff["review_sha256"] != expected_review_sha256:
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_REVIEW_MISMATCH",
            "release handoff does not bind the exact independent review",
        )
    if (
        expected_provenance_sha256 is not None
        and normalized["provenance_sha256"]
        != _digest(
            expected_provenance_sha256,
            pointer="/expected_provenance_sha256",
        )
    ):
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_PROVENANCE_MISMATCH",
            "release handoff provenance digest is not the expected record",
        )
    if (
        expected_candidate_sha256 is not None
        and normalized["candidate_sha256"]
        != _digest(
            expected_candidate_sha256,
            pointer="/expected_candidate_sha256",
        )
    ):
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_CANDIDATE_MISMATCH",
            "release handoff candidate digest is not the expected release",
        )
    review = validate_release_review_bytes(
        review_bytes,
        provenance_sha256=str(normalized["provenance_sha256"]),
        candidate_sha256=str(normalized["candidate_sha256"]),
    )
    if review["reviewer_id"] != normalized["reviewer_id"]:
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_REVIEWER_MISMATCH",
            "release handoff reviewer does not match the bound review",
        )
    if canonical_json_bytes(normalized) != source:
        raise ReleaseLedgerError(
            "RELEASE_HANDOFF_NONCANONICAL",
            "release handoff is not the exact normalized record",
        )
    return normalized


def build_release_handoff_bytes(
    *,
    release_id: str,
    ledger_bytes: bytes,
    review_bytes: bytes,
    provenance_sha256: str,
    candidate_sha256: str,
    archive_manifest_sha256: str,
    archive_sha256: str,
) -> bytes:
    """Build a canonical external release binding after handoff creation."""

    validate_release_ledger_bytes(ledger_bytes)
    review = validate_release_review_bytes(
        review_bytes,
        provenance_sha256=provenance_sha256,
        candidate_sha256=candidate_sha256,
    )
    content = canonical_json_bytes(
        {
            "schema": RELEASE_HANDOFF_SCHEMA,
            "release_id": _stable_id(
                release_id, pointer="/release_id"
            ),
            "ledger_sha256": hashlib.sha256(
                ledger_bytes
            ).hexdigest(),
            "review_sha256": hashlib.sha256(
                review_bytes
            ).hexdigest(),
            "reviewer_id": review["reviewer_id"],
            "provenance_sha256": _digest(
                provenance_sha256, pointer="/provenance_sha256"
            ),
            "base_commit": FIRST_INTRODUCTION_BASE_COMMIT,
            "base_tree": FIRST_INTRODUCTION_BASE_TREE,
            "inventory_sha256": (
                FIRST_INTRODUCTION_INVENTORY_SHA256
            ),
            "candidate_sha256": _digest(
                candidate_sha256, pointer="/candidate_sha256"
            ),
            "archive_manifest_sha256": _digest(
                archive_manifest_sha256,
                pointer="/archive_manifest_sha256",
            ),
            "archive_sha256": _digest(
                archive_sha256, pointer="/archive_sha256"
            ),
        }
    )
    validate_release_handoff_bytes(
        content,
        ledger_bytes=ledger_bytes,
        review_bytes=review_bytes,
        expected_provenance_sha256=provenance_sha256,
        expected_candidate_sha256=candidate_sha256,
    )
    return content


def _runtime_handler_specs(
    plugin_root: Path,
) -> dict[tuple[str, str, str], dict[str, object]]:
    root = plugin_root.resolve(strict=True)
    workflows_root = root / "workflows"
    result: dict[tuple[str, str, str], dict[str, object]] = {}
    for registry, filename in _RUNTIME_MANIFESTS:
        path = workflows_root / "runtime" / filename
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "runtime handler manifest cannot be loaded",
                details={"path": str(path)},
            ) from exc
        if not isinstance(manifest, dict):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "runtime handler manifest must be an object",
            )
        file_sets = manifest.get("implementation_file_sets")
        entries = manifest.get("entries")
        if not isinstance(file_sets, dict) or not isinstance(entries, list):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "runtime handler manifest inventory is invalid",
            )
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "runtime handler entry is invalid",
                )
            identifier = _stable_id(
                entry.get("id"),
                pointer=f"/{registry}/{index}/id",
            )
            version = _handler_version(
                identifier, pointer=f"/{registry}/{index}/id"
            )
            contract_id = _stable_id(
                entry.get("contract_id"),
                pointer=f"/{registry}/{index}/contract_id",
            )
            file_set_name = entry.get("implementation_file_set")
            raw_file_set = (
                file_sets.get(file_set_name)
                if isinstance(file_set_name, str)
                else None
            )
            if isinstance(raw_file_set, dict):
                if set(raw_file_set) != {"files", "semantic_roots"}:
                    raise ReleaseLedgerError(
                        "RELEASE_PACKAGE_INVALID",
                        "structured handler implementation file set is invalid",
                        details={"registry": registry, "id": identifier},
                    )
                declarations = raw_file_set.get("files")
                semantic_roots = raw_file_set.get("semantic_roots")
                if (
                    not isinstance(semantic_roots, list)
                    or not semantic_roots
                    or any(
                        not isinstance(item, str) or not item
                        for item in semantic_roots
                    )
                    or semantic_roots
                    != sorted(set(semantic_roots))
                ):
                    raise ReleaseLedgerError(
                        "RELEASE_PACKAGE_INVALID",
                        "handler semantic roots are invalid",
                        details={"registry": registry, "id": identifier},
                    )
            else:
                declarations = raw_file_set
            if not isinstance(declarations, list) or not declarations:
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "handler implementation file set is missing",
                    details={"registry": registry, "id": identifier},
                )
            files: list[BundleFile] = []
            for declaration_index, declaration in enumerate(
                declarations
            ):
                if (
                    not isinstance(declaration, dict)
                    or set(declaration) != {"path", "kind"}
                    or declaration.get("kind") not in {"B", "J", "T"}
                    or not isinstance(declaration.get("path"), str)
                ):
                    raise ReleaseLedgerError(
                        "RELEASE_PACKAGE_INVALID",
                        "handler implementation declaration is invalid",
                        details={
                            "registry": registry,
                            "id": identifier,
                            "index": declaration_index,
                        },
                    )
                relative = str(declaration["path"])
                source_path = root / relative
                try:
                    metadata = source_path.lstat()
                    source = source_path.read_bytes()
                except OSError as exc:
                    raise ReleaseLedgerError(
                        "RELEASE_PACKAGE_INVALID",
                        "handler implementation source cannot be read",
                        details={"path": relative},
                    ) from exc
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
                    metadata.st_mode
                ):
                    raise ReleaseLedgerError(
                        "RELEASE_PACKAGE_INVALID",
                        "handler implementation source must be a regular file",
                        details={"path": relative},
                    )
                files.append(
                    BundleFile(relative, str(declaration["kind"]), source)
                )
            implementation_sha256 = handler_implementation_sha256(
                identifier, contract_id, files
            )
            key = (registry, identifier, version)
            if key in result:
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "runtime handler identity is duplicated",
                    details={"key": list(key)},
                )
            result[key] = {
                "registry": registry,
                "id": identifier,
                "version": version,
                "contract_id": contract_id,
                "implementation_sha256": implementation_sha256,
                "files": tuple(files),
            }
    return result


def package_release_reservations(
    plugin_root: Path,
) -> tuple[dict[str, object], ...]:
    root = plugin_root.expanduser().resolve(strict=True)
    workflows_root = root / "workflows"
    try:
        catalog = json.loads(
            (workflows_root / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReleaseLedgerError(
            "RELEASE_PACKAGE_INVALID",
            "workflow catalog cannot be loaded",
        ) from exc
    bundles = catalog.get("bundles") if isinstance(catalog, dict) else None
    if not isinstance(bundles, list):
        raise ReleaseLedgerError(
            "RELEASE_PACKAGE_INVALID",
            "workflow catalog bundle inventory is invalid",
        )
    handler_specs = _runtime_handler_specs(root)
    reservations: list[dict[str, object]] = []
    for index, entry in enumerate(bundles):
        if not isinstance(entry, dict):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow catalog bundle entry is invalid",
            )
        workflow_id = _stable_id(
            entry.get("workflow_id"),
            pointer=f"/bundles/{index}/workflow_id",
        )
        workflow_version = _positive_version(
            entry.get("workflow_version"),
            pointer=f"/bundles/{index}/workflow_version",
        )
        graph_digest = _digest(
            entry.get("graph_sha256"),
            pointer=f"/bundles/{index}/graph_sha256",
        )
        bundle_digest = _digest(
            entry.get("bundle_sha256"),
            pointer=f"/bundles/{index}/bundle_sha256",
        )
        root_relative = entry.get("root")
        graph_relative = entry.get("graph")
        files_value = entry.get("files")
        if (
            not isinstance(root_relative, str)
            or not isinstance(graph_relative, str)
            or not isinstance(files_value, list)
        ):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow catalog bundle paths are invalid",
            )
        bundle_root = workflows_root / root_relative
        try:
            graph_source = (
                bundle_root / graph_relative
            ).read_bytes()
            graph = json.loads(graph_source.decode("utf-8", "strict"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow graph cannot be loaded",
                details={"workflow": [workflow_id, workflow_version]},
            ) from exc
        contracts = (
            graph.get("contracts") if isinstance(graph, dict) else None
        )
        if not isinstance(contracts, list) or not contracts:
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_INVALID",
                "workflow graph contract inventory is invalid",
            )
        selected: dict[
            tuple[str, str, str], dict[str, object]
        ] = {}
        for contract_index, contract in enumerate(contracts):
            if not isinstance(contract, dict):
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "workflow contract reference is invalid",
                )
            key = (
                _stable_id(
                    contract.get("registry"),
                    pointer=(
                        f"/bundles/{index}/contracts/"
                        f"{contract_index}/registry"
                    ),
                ),
                _stable_id(
                    contract.get("id"),
                    pointer=(
                        f"/bundles/{index}/contracts/"
                        f"{contract_index}/id"
                    ),
                ),
                _stable_id(
                    contract.get("version"),
                    pointer=(
                        f"/bundles/{index}/contracts/"
                        f"{contract_index}/version"
                    ),
                ),
            )
            try:
                selected[key] = handler_specs[key]
            except KeyError as exc:
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "workflow references an unknown runtime handler",
                    details={"handler": list(key)},
                ) from exc
        bundle_files: list[BundleFile] = []
        for file_index, declaration in enumerate(files_value):
            if (
                not isinstance(declaration, dict)
                or set(declaration) != {"path", "kind"}
                or declaration.get("kind") not in {"B", "J", "T"}
                or not isinstance(declaration.get("path"), str)
            ):
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "workflow bundle file declaration is invalid",
                    details={"index": file_index},
                )
            relative = str(declaration["path"])
            try:
                source = (bundle_root / relative).read_bytes()
            except OSError as exc:
                raise ReleaseLedgerError(
                    "RELEASE_PACKAGE_INVALID",
                    "workflow bundle source cannot be read",
                    details={"path": relative},
                ) from exc
            bundle_files.append(
                BundleFile(relative, str(declaration["kind"]), source)
            )
        identity_handlers = tuple(
            HandlerImplementation(
                handler_id=str(spec["id"]),
                contract_id=str(spec["contract_id"]),
                files=spec["files"],  # type: ignore[arg-type]
            )
            for _key, spec in sorted(
                selected.items(),
                key=lambda item: item[0][1].encode("utf-8"),
            )
        )
        identity = compute_workflow_bundle_identity(
            graph_source, bundle_files, identity_handlers
        )
        if (
            identity.graph_sha256 != graph_digest
            or identity.bundle_sha256 != bundle_digest
        ):
            raise ReleaseLedgerError(
                "RELEASE_PACKAGE_IDENTITY_MISMATCH",
                "catalog workflow identity does not match package bytes",
                details={"workflow": [workflow_id, workflow_version]},
            )
        handlers = [
            {
                field: spec[field]
                for field in _RESERVATION_HANDLER_FIELDS
            }
            for spec in selected.values()
        ]
        handlers.sort(key=_handler_sort_key)
        reservations.append(
            {
                "workflow_id": workflow_id,
                "workflow_version": workflow_version,
                "graph_sha256": graph_digest,
                "bundle_sha256": bundle_digest,
                "handlers": handlers,
            }
        )
    reservations.sort(key=_workflow_sort_key)
    encoded = append_release_reservations(
        empty_release_ledger_bytes(), reservations
    )
    return tuple(
        validate_release_ledger_bytes(encoded)["reservations"]
    )


def validate_ledger_against_package(
    ledger_bytes: bytes,
    *,
    plugin_root: Path,
) -> dict[str, object]:
    ledger = validate_release_ledger_bytes(ledger_bytes)
    package = {
        (
            str(item["workflow_id"]),
            int(item["workflow_version"]),
        ): item
        for item in package_release_reservations(plugin_root)
    }
    for reservation in ledger["reservations"]:
        key = (
            str(reservation["workflow_id"]),
            int(reservation["workflow_version"]),
        )
        if package.get(key) != reservation:
            raise ReleaseLedgerError(
                "RELEASE_RESERVED_IDENTITY_UNRESOLVABLE",
                "reserved workflow/handler bytes are missing or substituted",
                details={"workflow": list(key)},
            )
    return ledger


def _task_reference(
    state: object,
    *,
    data_root: Path,
    path: Path,
) -> Optional[dict[str, object]]:
    if not isinstance(state, dict):
        return None
    workflow_ref = state.get("workflow_ref")
    if not isinstance(workflow_ref, dict):
        return None
    workflow_id = workflow_ref.get("id")
    workflow_version = workflow_ref.get("version")
    bundle_sha256 = workflow_ref.get("bundle_sha256")
    if (
        not isinstance(workflow_id, str)
        or isinstance(workflow_version, bool)
        or not isinstance(workflow_version, int)
        or not isinstance(bundle_sha256, str)
    ):
        return {
            "data_root": str(data_root),
            "state_path": str(path),
            "malformed": True,
        }
    return {
        "data_root": str(data_root),
        "state_path": str(path),
        "task_id": state.get("task_id"),
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "bundle_sha256": bundle_sha256,
        "malformed": False,
    }


def scan_data_root_task_references(
    data_roots: Iterable[Path],
) -> tuple[Mapping[str, object], ...]:
    observations: list[Mapping[str, object]] = []
    for supplied in data_roots:
        root = supplied.expanduser().resolve(strict=False)
        tasks = root / "tasks"
        if not tasks.exists():
            continue
        if not tasks.is_dir() or tasks.is_symlink():
            observations.append(
                {
                    "data_root": str(root),
                    "malformed": True,
                    "reason": "tasks-root-invalid",
                }
            )
            continue
        try:
            task_directories = sorted(
                tasks.iterdir(),
                key=lambda item: item.name.encode(
                    "utf-8", "surrogateescape"
                ),
            )
        except OSError:
            observations.append(
                {
                    "data_root": str(root),
                    "malformed": True,
                    "reason": "tasks-root-unreadable",
                }
            )
            continue
        for task_directory in task_directories:
            state_path = task_directory / "state.json"
            try:
                metadata = state_path.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_size > 16 * 1024 * 1024
                ):
                    raise OSError("state path is not a bounded regular file")
                state = json.loads(
                    state_path.read_text(encoding="utf-8")
                )
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError, ValueError):
                observations.append(
                    {
                        "data_root": str(root),
                        "state_path": str(state_path),
                        "malformed": True,
                    }
                )
                continue
            reference = _task_reference(
                state,
                data_root=root,
                path=state_path,
            )
            if reference is not None:
                observations.append(reference)
    return tuple(observations)


def validate_continuous_prior_release(
    evidence: ContinuousPriorReleaseInput,
    *,
    current_ledger_bytes: bytes,
    workflow_id: str,
    workflow_version: int,
) -> dict[str, object]:
    """Prove a target key absent from the exact prior reviewed release."""

    if not isinstance(evidence, ContinuousPriorReleaseInput):
        raise ReleaseLedgerError(
            "RELEASE_PROVENANCE_INPUT_INVALID",
            "continuous prior-release evidence is invalid",
        )
    previous = validate_release_ledger_bytes(
        evidence.ledger_bytes
    )
    # The previous official ledger must be an exact append-only prefix of the
    # current package ledger. A missing/substituted reservation is a broken
    # release chain, even when the target key itself is absent.
    validate_release_ledger_bytes(
        current_ledger_bytes,
        previous_ledger_bytes=evidence.ledger_bytes,
    )
    handoff = validate_release_handoff_bytes(
        evidence.handoff_bytes,
        ledger_bytes=evidence.ledger_bytes,
        review_bytes=evidence.review_bytes,
    )
    target = (workflow_id, workflow_version)
    if any(
        (
            reservation["workflow_id"],
            reservation["workflow_version"],
        )
        == target
        for reservation in previous["reservations"]
    ):
        raise ReleaseLedgerError(
            "RELEASE_PRIOR_PROVENANCE_TARGET_PRESENT",
            "prior official release already reserved the target identity",
            details={"workflow": list(target)},
        )
    return {
        "release_id": handoff["release_id"],
        "ledger_sha256": handoff["ledger_sha256"],
        "review_sha256": handoff["review_sha256"],
        "candidate_sha256": handoff["candidate_sha256"],
        "target_absent": True,
    }


def evaluate_unreleased_regeneration(
    *,
    workflow_id: str,
    workflow_version: int,
    bundle_sha256: str,
    ledger_bytes: bytes,
    activation_profiles: Sequence[Mapping[str, object]],
    first_introduction: Optional[
        FirstIntroductionProvenanceInput
    ] = None,
    continuous_prior_release: Optional[
        ContinuousPriorReleaseInput
    ] = None,
    data_roots: Iterable[Path] = (),
    exposure_kinds: Iterable[str] = (),
) -> ReleaseBoundaryDecision:
    target_id = _stable_id(workflow_id, pointer="/workflow_id")
    target_version = _positive_version(
        workflow_version, pointer="/workflow_version"
    )
    target_bundle = _digest(
        bundle_sha256, pointer="/bundle_sha256"
    )
    ledger = validate_release_ledger_bytes(ledger_bytes)
    blockers: set[str] = set()
    for reservation in ledger["reservations"]:
        if (
            reservation["workflow_id"] == target_id
            and reservation["workflow_version"] == target_version
        ):
            blockers.add("RELEASE_IDENTITY_RESERVED")
            if reservation["bundle_sha256"] != target_bundle:
                blockers.add("RELEASE_IDENTITY_SUBSTITUTED")
    matching_profiles = [
        profile
        for profile in activation_profiles
        if profile.get("workflow_id") == target_id
        and profile.get("workflow_version") == target_version
    ]
    if any(profile.get("active") is True for profile in matching_profiles):
        blockers.add("RELEASE_PROFILE_PIN_ELIGIBLE")
    if any(
        profile.get("bundle_sha256") != target_bundle
        for profile in matching_profiles
    ):
        blockers.add("RELEASE_ACTIVATION_IDENTITY_MISMATCH")
    authoritative_provenance = False
    if first_introduction is not None:
        if not isinstance(
            first_introduction, FirstIntroductionProvenanceInput
        ):
            raise ReleaseLedgerError(
                "RELEASE_PROVENANCE_INPUT_INVALID",
                "first-introduction provenance input is invalid",
            )
        manifest, _provenance_sha256 = (
            validate_first_introduction_bytes(
                first_introduction.manifest_bytes,
                repository=first_introduction.repository,
                plugin_root=first_introduction.plugin_root,
            )
        )
        introduced = manifest["introduced_workflows"]
        authoritative_provenance = any(
            isinstance(item, Mapping)
            and item.get("workflow_id") == target_id
            and item.get("workflow_version") == target_version
            for item in introduced
        )
        if not authoritative_provenance:
            blockers.add(
                "RELEASE_AUTHORITATIVE_PROVENANCE_TARGET_MISSING"
            )
    if continuous_prior_release is not None:
        validate_continuous_prior_release(
            continuous_prior_release,
            current_ledger_bytes=ledger_bytes,
            workflow_id=target_id,
            workflow_version=target_version,
        )
        authoritative_provenance = True
    if not authoritative_provenance:
        blockers.add("RELEASE_AUTHORITATIVE_PROVENANCE_MISSING")
    observations = scan_data_root_task_references(data_roots)
    for observation in observations:
        if observation.get("malformed") is True:
            blockers.add("RELEASE_DATA_ROOT_SCAN_INCOMPLETE")
        if (
            observation.get("workflow_id") == target_id
            and observation.get("workflow_version") == target_version
        ):
            blockers.add("RELEASE_UNRESERVED_TASK_REFERENCE")
            if observation.get("bundle_sha256") != target_bundle:
                blockers.add("RELEASE_TASK_IDENTITY_SUBSTITUTED")
    normalized_exposures = tuple(exposure_kinds)
    if normalized_exposures:
        if any(
            not isinstance(item, str)
            or item
            not in {
                "external-handoff",
                "installation",
                "pin-eligible",
                "publication",
            }
            for item in normalized_exposures
        ):
            raise ReleaseLedgerError(
                "RELEASE_EXPOSURE_INVALID",
                "release exposure kind is unsupported",
            )
        blockers.add("RELEASE_IDENTITY_EXPOSED")
    return ReleaseBoundaryDecision(
        allowed=not blockers,
        blocker_codes=tuple(sorted(blockers)),
        observed_task_references=observations,
        data_root_scan_is_authoritative_absence_proof=False,
    )


def require_exact_reservation_before_exposure(
    *,
    workflow_id: str,
    workflow_version: int,
    expected_reservation: Mapping[str, object],
    ledger_bytes: bytes,
) -> None:
    ledger = validate_release_ledger_bytes(ledger_bytes)
    matches = [
        reservation
        for reservation in ledger["reservations"]
        if reservation["workflow_id"] == workflow_id
        and reservation["workflow_version"] == workflow_version
    ]
    if matches != [dict(expected_reservation)]:
        raise ReleaseLedgerError(
            "RELEASE_RESERVATION_REQUIRED",
            "exact release reservation is required before exposure",
            details={
                "workflow": [workflow_id, workflow_version],
            },
        )


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or generate workflow release provenance without "
            "installing, publishing, handing off, or activating the plugin."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-first-introduction")
    validate.add_argument("--plugin-root", type=Path, required=True)
    validate.add_argument("--repository", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    generate = subparsers.add_parser("generate-first-introduction")
    generate.add_argument("--plugin-root", type=Path, required=True)
    generate.add_argument("--repository", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    ledger = subparsers.add_parser("validate-ledger")
    ledger.add_argument("--plugin-root", type=Path, required=True)
    ledger.add_argument("--ledger", type=Path, required=True)
    epoch = subparsers.add_parser("validate-introduction-epoch")
    epoch.add_argument("--plugin-root", type=Path, required=True)
    epoch.add_argument("--repository", type=Path, required=True)
    epoch.add_argument(
        "--first-introduction",
        type=Path,
        required=True,
    )
    epoch.add_argument(
        "--reserved-v3-ledger",
        type=Path,
        required=True,
    )
    epoch.add_argument(
        "--reserved-v3-activation",
        type=Path,
        required=True,
    )
    epoch.add_argument("--manifest", type=Path, required=True)
    epoch.add_argument("--result-ledger", type=Path, required=True)
    epoch.add_argument("--predecessor-review", type=Path)
    epoch.add_argument("--predecessor-handoff", type=Path)
    epoch.add_argument(
        "--prior-epoch",
        nargs=4,
        action="append",
        default=[],
        metavar=(
            "MANIFEST",
            "RESULT_LEDGER",
            "PREDECESSOR_REVIEW_OR_DASH",
            "PREDECESSOR_HANDOFF_OR_DASH",
        ),
        help=(
            "Ordered prior epoch inputs; use '-' for both predecessor "
            "review/handoff paths on the first reserved-unexposed epoch."
        ),
    )
    return parser


def _optional_cli_bytes(value: str) -> Optional[bytes]:
    if value == "-":
        return None
    return Path(value).read_bytes()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate-first-introduction":
            manifest, digest = validate_first_introduction_bytes(
                args.manifest.read_bytes(),
                repository=args.repository,
                plugin_root=args.plugin_root,
            )
            result = {
                "ok": True,
                "schema": manifest["schema"],
                "provenance_sha256": digest,
            }
        elif args.command == "generate-first-introduction":
            content = build_first_introduction_bytes(
                repository=args.repository,
                plugin_root=args.plugin_root,
            )
            _write_exclusive(args.output, content)
            result = {
                "ok": True,
                "schema": FIRST_INTRODUCTION_SCHEMA,
                "provenance_sha256": hashlib.sha256(
                    content
                ).hexdigest(),
            }
        elif args.command == "validate-ledger":
            ledger = validate_ledger_against_package(
                args.ledger.read_bytes(),
                plugin_root=args.plugin_root,
            )
            result = {
                "ok": True,
                "schema": ledger["schema"],
                "reservation_count": len(ledger["reservations"]),
            }
        else:
            prior_epochs = tuple(
                IntroductionEpochProvenanceInput(
                    manifest_bytes=Path(values[0]).read_bytes(),
                    result_ledger_bytes=Path(values[1]).read_bytes(),
                    predecessor_review_bytes=_optional_cli_bytes(
                        values[2]
                    ),
                    predecessor_handoff_bytes=_optional_cli_bytes(
                        values[3]
                    ),
                )
                for values in args.prior_epoch
            )
            manifest, digest = validate_introduction_epoch_bytes(
                args.manifest.read_bytes(),
                predecessor_first_introduction_bytes=(
                    args.first_introduction.read_bytes()
                ),
                predecessor_ledger_bytes=(
                    args.reserved_v3_ledger.read_bytes()
                ),
                predecessor_activation_bytes=(
                    args.reserved_v3_activation.read_bytes()
                ),
                current_ledger_bytes=args.result_ledger.read_bytes(),
                repository=args.repository,
                plugin_root=args.plugin_root,
                prior_epochs=prior_epochs,
                predecessor_review_bytes=(
                    args.predecessor_review.read_bytes()
                    if args.predecessor_review is not None
                    else None
                ),
                predecessor_handoff_bytes=(
                    args.predecessor_handoff.read_bytes()
                    if args.predecessor_handoff is not None
                    else None
                ),
            )
            result = {
                "ok": True,
                "schema": manifest["schema"],
                "epoch_id": manifest["epoch_id"],
                "epoch_sequence": manifest["epoch_sequence"],
                "provenance_sha256": digest,
                "result_ledger_sha256": manifest[
                    "result_ledger_sha256"
                ],
                "cumulative_identity_set_sha256": manifest[
                    "cumulative_identity_set_sha256"
                ],
                "authorizes_exposure": False,
                "supersession_review_required": True,
            }
    except (OSError, ReleaseLedgerError) as exc:
        error = (
            exc.as_dict()
            if isinstance(exc, ReleaseLedgerError)
            else {
                "code": "RELEASE_IO_FAILED",
                "message": "release input/output could not be read or written",
                "details": {"type": type(exc).__name__},
            }
        )
        print(
            json.dumps(
                {"ok": False, "error": error},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "FIRST_INTRODUCTION_BASE_COMMIT",
    "FIRST_INTRODUCTION_BASE_TREE",
    "FIRST_INTRODUCTION_CHANGE_ID",
    "FIRST_INTRODUCTION_INVENTORY_CONTRACT",
    "FIRST_INTRODUCTION_INVENTORY_SHA256",
    "FIRST_INTRODUCTION_OBJECT_FORMAT",
    "FIRST_INTRODUCTION_SCHEMA",
    "INTRODUCTION_EPOCH_OFFICIAL_RELEASE",
    "INTRODUCTION_EPOCH_RESERVED_UNEXPOSED",
    "INTRODUCTION_EPOCH_SCHEMA",
    "IntroductionEpochProvenanceInput",
    "IntroductionEpochValidation",
    "RESERVED_V3_ACTIVATION_SHA256",
    "RESERVED_V3_LEDGER_SHA256",
    "RESERVED_V3_RESERVATION_COUNT",
    "ContinuousPriorReleaseInput",
    "FirstIntroductionProvenanceInput",
    "RELEASE_LEDGER_SCHEMA",
    "RELEASE_HANDOFF_SCHEMA",
    "RELEASE_REVIEW_SCHEMA",
    "GitInventoryEvidence",
    "ReleaseBoundaryDecision",
    "ReleaseLedgerError",
    "append_release_reservations",
    "build_first_introduction_bytes",
    "build_introduction_epoch_bytes",
    "build_release_handoff_bytes",
    "canonical_json_bytes",
    "discover_introduced_identity_keys",
    "empty_release_ledger_bytes",
    "evaluate_unreleased_regeneration",
    "first_introduction_inventory_sha256",
    "introduction_epoch_append_batch_sha256",
    "introduction_epoch_cumulative_identity_set_sha256",
    "observe_first_introduction_git_inventory",
    "package_release_reservations",
    "parse_canonical_json_bytes",
    "require_exact_reservation_before_exposure",
    "scan_data_root_task_references",
    "validate_first_introduction_bytes",
    "validate_introduction_epoch_bytes",
    "validate_introduction_epoch_chain",
    "validate_continuous_prior_release",
    "validate_ledger_against_package",
    "validate_release_handoff_bytes",
    "validate_release_ledger_bytes",
    "validate_release_review_bytes",
    "validate_reserved_v3_ledger_bytes",
]
