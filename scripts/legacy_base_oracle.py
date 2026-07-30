#!/usr/bin/env python3
"""Read-only validator for the frozen legacy side-effect oracle.

The oracle fixture is generated outside candidate execution from immutable Git
objects.  This module intentionally has no fixture-generation or file-writing
path: it can verify the frozen base objects, validate the explicit v1/v2
cross-product, and audit that candidate source still exposes every retained
legacy command and observation seam.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ORACLE_SCHEMA = "dev-flow-legacy-base-side-effect-oracle/v1"
BASE_COMMIT = "2dc397411ad1ea5f2a43d43e881523b125bb5eec"
BASE_TREE = "ee7de366a818d8800b4808015f2d8ae4c4405136"
SUPPORTED_TASK_SCHEMAS = ("1", "2")

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMAND_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_VARIANT_RE = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")

_REQUIRED_VARIANTS = frozenset(
    {
        "baseline.fetch",
        "baseline.materialize",
        "preflight.capture",
        "prepare-workspace.execute",
        "prepare-workspace.plan",
        "record-artifact.observe",
        "record-test.fingerprint",
        "review-snapshot.capture",
    }
)
_REQUIRED_PROFILES = frozenset(
    {
        "atomic-write",
        "mutation-gate",
        "review-cleanup",
        "state-outbox",
    }
)
_OBSERVATION_FIELDS = frozenset(
    {
        "effect_start",
        "mutation_intent",
        "containment",
        "quarantine",
        "recovery",
        "revision_delta",
        "durable_event_batch",
        "error_code",
        "persisted_bytes",
    }
)
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema",
        "base",
        "generation",
        "inventory",
        "byte_contracts",
        "interruption_profiles",
        "cross_product",
        "base_test_evidence",
        "unsupported_injection_points",
        "fixture_sha256",
    }
)


class OracleError(ValueError):
    """Fail-closed immutable-oracle validation error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
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


def _error(
    code: str,
    message: str,
    *,
    field: str | None = None,
    details: Mapping[str, object] | None = None,
) -> OracleError:
    payload = dict(details or {})
    if field is not None:
        payload.setdefault("field", field)
    return OracleError(code, message, details=payload)


def _require_exact_fields(
    value: object,
    fields: Iterable[str],
    *,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(
            "ORACLE_OBJECT_INVALID",
            "oracle contract value must be an object",
            field=field,
        )
    if any(not isinstance(key, str) for key in value):
        raise _error(
            "ORACLE_FIELDS_INVALID",
            "oracle contract field names must be strings",
            field=field,
        )
    expected = frozenset(fields)
    actual = frozenset(value)
    if actual != expected:
        raise _error(
            "ORACLE_FIELDS_INVALID",
            "oracle contract fields do not match the frozen schema",
            field=field,
            details={
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            },
        )
    return value


def _require_string(
    value: object, field: str, *, pattern: re.Pattern[str] | None = None
) -> str:
    if not isinstance(value, str) or not value:
        raise _error(
            "ORACLE_FIELD_INVALID",
            "oracle field must be a non-empty string",
            field=field,
        )
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise _error(
            "ORACLE_FIELD_INVALID",
            "oracle string must be valid UTF-8",
            field=field,
        ) from exc
    if pattern is not None and not pattern.fullmatch(value):
        raise _error(
            "ORACLE_FIELD_INVALID",
            "oracle field does not use its canonical form",
            field=field,
        )
    return value


def _require_string_list(
    value: object,
    field: str,
    *,
    pattern: re.Pattern[str] | None = None,
    sorted_values: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _error(
            "ORACLE_FIELD_INVALID",
            "oracle field must be an array",
            field=field,
        )
    normalized = tuple(
        _require_string(item, f"{field}/{index}", pattern=pattern)
        for index, item in enumerate(value)
    )
    if len(set(normalized)) != len(normalized):
        raise _error(
            "ORACLE_DUPLICATE_VALUE",
            "oracle array values must be unique",
            field=field,
        )
    if sorted_values and normalized != tuple(sorted(normalized)):
        raise _error(
            "ORACLE_ORDER_INVALID",
            "oracle array must be sorted",
            field=field,
        )
    return normalized


def canonical_oracle_bytes(value: object) -> bytes:
    """Canonical fixture-identity encoding, distinct from runtime state."""

    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _error(
            "ORACLE_VALUE_INVALID",
            "oracle value cannot be canonically encoded",
        ) from exc


def oracle_fixture_sha256(value: Mapping[str, object]) -> str:
    payload = dict(value)
    payload.pop("fixture_sha256", None)
    return hashlib.sha256(canonical_oracle_bytes(payload)).hexdigest()


def _validate_observation(
    value: object, *, field: str
) -> Mapping[str, object]:
    observation = _require_exact_fields(
        value, _OBSERVATION_FIELDS, field=field
    )
    if not isinstance(observation["effect_start"], bool):
        raise _error(
            "ORACLE_OBSERVATION_INVALID",
            "effect_start must be boolean",
            field=f"{field}/effect_start",
        )
    for name in (
        "mutation_intent",
        "containment",
        "quarantine",
        "recovery",
        "persisted_bytes",
    ):
        _require_string(observation[name], f"{field}/{name}")
    revision_delta = observation["revision_delta"]
    if (
        isinstance(revision_delta, bool)
        or not isinstance(revision_delta, int)
        or revision_delta not in {0, 1}
    ):
        raise _error(
            "ORACLE_OBSERVATION_INVALID",
            "revision_delta must be zero or one",
            field=f"{field}/revision_delta",
        )
    _require_string_list(
        observation["durable_event_batch"],
        f"{field}/durable_event_batch",
    )
    error_code = observation["error_code"]
    if error_code is not None:
        _require_string(error_code, f"{field}/error_code")
    return observation


def _validate_byte_contracts(value: object) -> None:
    contracts = _require_exact_fields(
        value,
        {"state_json", "event_jsonl", "mutation_quarantine"},
        field="byte_contracts",
    )
    for name, raw in contracts.items():
        contract = _require_exact_fields(
            raw,
            {
                "encoding",
                "format",
                "terminal_lf",
                "vector",
                "exact_hex",
                "size",
                "sha256",
            },
            field=f"byte_contracts/{name}",
        )
        if contract["encoding"] != "utf-8":
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract encoding must be UTF-8",
                field=f"byte_contracts/{name}/encoding",
            )
        if contract["terminal_lf"] is not True:
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract must require one terminal LF",
                field=f"byte_contracts/{name}/terminal_lf",
            )
        exact_hex = _require_string(
            contract["exact_hex"],
            f"byte_contracts/{name}/exact_hex",
        )
        try:
            encoded = bytes.fromhex(exact_hex)
        except ValueError as exc:
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract contains invalid hexadecimal bytes",
                field=f"byte_contracts/{name}/exact_hex",
            ) from exc
        if not encoded.endswith(b"\n"):
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract does not end in LF",
                field=f"byte_contracts/{name}/exact_hex",
            )
        if contract["size"] != len(encoded):
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract size differs from exact bytes",
                field=f"byte_contracts/{name}/size",
            )
        digest = _require_string(
            contract["sha256"],
            f"byte_contracts/{name}/sha256",
            pattern=_SHA256_RE,
        )
        if hashlib.sha256(encoded).hexdigest() != digest:
            raise _error(
                "ORACLE_BYTE_CONTRACT_INVALID",
                "byte contract digest differs from exact bytes",
                field=f"byte_contracts/{name}/sha256",
            )


def _validate_inventory(value: object) -> None:
    inventory = _require_exact_fields(
        value,
        {
            "base_cli_commands",
            "classifications",
            "retained_side_effect_commands",
            "variant_ids",
        },
        field="inventory",
    )
    base_commands = _require_string_list(
        inventory["base_cli_commands"],
        "inventory/base_cli_commands",
        pattern=_COMMAND_RE,
    )
    classifications = _require_exact_fields(
        inventory["classifications"],
        {
            "lifecycle_or_config",
            "read_only",
            "recovery",
            "state_only",
            "retained_side_effect",
        },
        field="inventory/classifications",
    )
    classified: list[str] = []
    for name, raw in classifications.items():
        classified.extend(
            _require_string_list(
                raw,
                f"inventory/classifications/{name}",
                pattern=_COMMAND_RE,
                sorted_values=True,
            )
        )
    if len(classified) != len(set(classified)):
        raise _error(
            "ORACLE_INVENTORY_OVERLAP",
            "base command classifications overlap",
            field="inventory/classifications",
        )
    if frozenset(classified) != frozenset(base_commands):
        raise _error(
            "ORACLE_INVENTORY_INCOMPLETE",
            "base command classifications do not partition the CLI",
            details={
                "unclassified": sorted(
                    set(base_commands) - set(classified)
                ),
                "unknown": sorted(set(classified) - set(base_commands)),
            },
        )
    retained = _require_string_list(
        inventory["retained_side_effect_commands"],
        "inventory/retained_side_effect_commands",
        pattern=_COMMAND_RE,
        sorted_values=True,
    )
    classified_retained = tuple(
        classifications["retained_side_effect"]  # type: ignore[arg-type]
    )
    if retained != classified_retained:
        raise _error(
            "ORACLE_INVENTORY_MISMATCH",
            "retained command inventory differs from its classification",
        )
    variants = frozenset(
        _require_string_list(
            inventory["variant_ids"],
            "inventory/variant_ids",
            pattern=_VARIANT_RE,
            sorted_values=True,
        )
    )
    if variants != _REQUIRED_VARIANTS:
        raise _error(
            "ORACLE_VARIANT_INCOMPLETE",
            "frozen side-effect variants are incomplete",
            details={
                "missing": sorted(_REQUIRED_VARIANTS - variants),
                "unknown": sorted(variants - _REQUIRED_VARIANTS),
            },
        )


def _validate_interruption_profiles(value: object) -> None:
    if not isinstance(value, Mapping):
        raise _error(
            "ORACLE_INTERRUPTION_INVALID",
            "interruption profiles must be an object",
        )
    if frozenset(value) != _REQUIRED_PROFILES:
        raise _error(
            "ORACLE_INTERRUPTION_INCOMPLETE",
            "interruption profile inventory is incomplete",
            details={
                "missing": sorted(_REQUIRED_PROFILES - set(value)),
                "unknown": sorted(set(value) - _REQUIRED_PROFILES),
            },
        )
    for profile_name, raw in value.items():
        profile = _require_exact_fields(
            raw,
            {"supported_stages", "base_evidence", "unsupported_stages"},
            field=f"interruption_profiles/{profile_name}",
        )
        stages = profile["supported_stages"]
        if not isinstance(stages, list) or not stages:
            raise _error(
                "ORACLE_INTERRUPTION_INVALID",
                "profile must declare supported stages",
                field=(
                    f"interruption_profiles/{profile_name}/"
                    "supported_stages"
                ),
            )
        stage_ids: list[str] = []
        for index, stage_raw in enumerate(stages):
            stage = _require_exact_fields(
                stage_raw,
                {"id", "observation"},
                field=(
                    f"interruption_profiles/{profile_name}/"
                    f"supported_stages/{index}"
                ),
            )
            stage_ids.append(
                _require_string(
                    stage["id"],
                    (
                        f"interruption_profiles/{profile_name}/"
                        f"supported_stages/{index}/id"
                    ),
                    pattern=_VARIANT_RE,
                )
            )
            _validate_observation(
                stage["observation"],
                field=(
                    f"interruption_profiles/{profile_name}/"
                    f"supported_stages/{index}/observation"
                ),
            )
        if len(stage_ids) != len(set(stage_ids)):
            raise _error(
                "ORACLE_INTERRUPTION_INVALID",
                "interruption stage ids must be unique",
                field=f"interruption_profiles/{profile_name}",
            )
        _require_string_list(
            profile["base_evidence"],
            f"interruption_profiles/{profile_name}/base_evidence",
            sorted_values=True,
        )
        _require_string_list(
            profile["unsupported_stages"],
            f"interruption_profiles/{profile_name}/unsupported_stages",
            sorted_values=True,
        )


def _validate_cross_product(value: object) -> None:
    if not isinstance(value, list):
        raise _error(
            "ORACLE_CROSS_PRODUCT_INVALID",
            "cross_product must be an array",
        )
    seen: set[str] = set()
    for index, raw in enumerate(value):
        row = _require_exact_fields(
            raw,
            {
                "variant_id",
                "command",
                "phase",
                "effects",
                "source_anchors",
                "interruption_profiles",
                "schemas",
            },
            field=f"cross_product/{index}",
        )
        variant_id = _require_string(
            row["variant_id"],
            f"cross_product/{index}/variant_id",
            pattern=_VARIANT_RE,
        )
        if variant_id in seen:
            raise _error(
                "ORACLE_CROSS_PRODUCT_DUPLICATE",
                "cross-product variant is duplicated",
                field=f"cross_product/{index}/variant_id",
            )
        seen.add(variant_id)
        _require_string(
            row["command"],
            f"cross_product/{index}/command",
            pattern=_COMMAND_RE,
        )
        _require_string(
            row["phase"], f"cross_product/{index}/phase"
        )
        _require_string_list(
            row["effects"],
            f"cross_product/{index}/effects",
            sorted_values=True,
        )
        anchors = row["source_anchors"]
        if not isinstance(anchors, list) or not anchors:
            raise _error(
                "ORACLE_SOURCE_ANCHOR_INVALID",
                "cross-product row requires source anchors",
                field=f"cross_product/{index}/source_anchors",
            )
        for anchor_index, raw_anchor in enumerate(anchors):
            anchor = _require_exact_fields(
                raw_anchor,
                {"path", "tokens"},
                field=(
                    f"cross_product/{index}/source_anchors/"
                    f"{anchor_index}"
                ),
            )
            _require_string(
                anchor["path"],
                (
                    f"cross_product/{index}/source_anchors/"
                    f"{anchor_index}/path"
                ),
            )
            _require_string_list(
                anchor["tokens"],
                (
                    f"cross_product/{index}/source_anchors/"
                    f"{anchor_index}/tokens"
                ),
            )
        profiles = frozenset(
            _require_string_list(
                row["interruption_profiles"],
                f"cross_product/{index}/interruption_profiles",
                sorted_values=True,
            )
        )
        if not profiles or not profiles.issubset(_REQUIRED_PROFILES):
            raise _error(
                "ORACLE_INTERRUPTION_INVALID",
                "cross-product row uses an invalid interruption profile",
                field=f"cross_product/{index}/interruption_profiles",
            )
        schemas = _require_exact_fields(
            row["schemas"],
            SUPPORTED_TASK_SCHEMAS,
            field=f"cross_product/{index}/schemas",
        )
        for schema in SUPPORTED_TASK_SCHEMAS:
            scenarios = _require_exact_fields(
                schemas[schema],
                {"success", "pre_effect_rejection"},
                field=f"cross_product/{index}/schemas/{schema}",
            )
            _validate_observation(
                scenarios["success"],
                field=(
                    f"cross_product/{index}/schemas/{schema}/success"
                ),
            )
            rejected = _validate_observation(
                scenarios["pre_effect_rejection"],
                field=(
                    f"cross_product/{index}/schemas/{schema}/"
                    "pre_effect_rejection"
                ),
            )
            if rejected["effect_start"] is not False:
                raise _error(
                    "ORACLE_PRE_EFFECT_INVALID",
                    "pre-effect rejection must not start an effect",
                    field=(
                        f"cross_product/{index}/schemas/{schema}/"
                        "pre_effect_rejection/effect_start"
                    ),
                )
            if rejected["revision_delta"] != 0:
                raise _error(
                    "ORACLE_PRE_EFFECT_INVALID",
                    "pre-effect rejection must preserve revision",
                    field=(
                        f"cross_product/{index}/schemas/{schema}/"
                        "pre_effect_rejection/revision_delta"
                    ),
                )
    if seen != _REQUIRED_VARIANTS:
        raise _error(
            "ORACLE_CROSS_PRODUCT_INCOMPLETE",
            "v1/v2 side-effect cross-product is incomplete",
            details={
                "missing": sorted(_REQUIRED_VARIANTS - seen),
                "unknown": sorted(seen - _REQUIRED_VARIANTS),
            },
        )


def validate_oracle(value: object) -> Mapping[str, object]:
    oracle = _require_exact_fields(
        value, _TOP_LEVEL_FIELDS, field="$"
    )
    if oracle["schema"] != ORACLE_SCHEMA:
        raise _error(
            "ORACLE_SCHEMA_INVALID",
            "legacy side-effect oracle schema is unsupported",
            field="schema",
        )
    base = _require_exact_fields(
        oracle["base"],
        {
            "commit",
            "tree",
            "object_format",
            "source_objects",
        },
        field="base",
    )
    if base["commit"] != BASE_COMMIT or base["tree"] != BASE_TREE:
        raise _error(
            "ORACLE_BASE_IDENTITY_MISMATCH",
            "oracle does not bind the immutable reviewed base",
        )
    if base["object_format"] != "sha1":
        raise _error(
            "ORACLE_OBJECT_FORMAT_INVALID",
            "base object format must be sha1",
        )
    source_objects = base["source_objects"]
    if not isinstance(source_objects, list) or not source_objects:
        raise _error(
            "ORACLE_BASE_INVENTORY_INVALID",
            "base source-object inventory must be non-empty",
        )
    source_paths: list[str] = []
    for index, raw in enumerate(source_objects):
        source = _require_exact_fields(
            raw,
            {"path", "mode", "blob", "content_sha256", "size"},
            field=f"base/source_objects/{index}",
        )
        source_paths.append(
            _require_string(
                source["path"], f"base/source_objects/{index}/path"
            )
        )
        if source["mode"] not in {"100644", "100755"}:
            raise _error(
                "ORACLE_BASE_INVENTORY_INVALID",
                "base source mode is invalid",
                field=f"base/source_objects/{index}/mode",
            )
        _require_string(
            source["blob"],
            f"base/source_objects/{index}/blob",
            pattern=_SHA1_RE,
        )
        _require_string(
            source["content_sha256"],
            f"base/source_objects/{index}/content_sha256",
            pattern=_SHA256_RE,
        )
        if (
            isinstance(source["size"], bool)
            or not isinstance(source["size"], int)
            or source["size"] < 0
        ):
            raise _error(
                "ORACLE_BASE_INVENTORY_INVALID",
                "base source size is invalid",
                field=f"base/source_objects/{index}/size",
            )
    if source_paths != sorted(set(source_paths)):
        raise _error(
            "ORACLE_BASE_INVENTORY_INVALID",
            "base source-object inventory must be unique and sorted",
        )
    generation = _require_exact_fields(
        oracle["generation"],
        {
            "method",
            "isolated_clone",
            "git_object_access",
            "fixture_frozen_before_candidate",
            "candidate_expected_regeneration",
            "audit_command",
        },
        field="generation",
    )
    if (
        generation["method"]
        != "isolated-local-clone-read-only-execution-and-audit"
        or generation["isolated_clone"] is not True
        or generation["git_object_access"] != "cat-file-and-ls-tree"
        or generation["fixture_frozen_before_candidate"] is not True
        or generation["candidate_expected_regeneration"] != "forbidden"
    ):
        raise _error(
            "ORACLE_PROVENANCE_INVALID",
            "oracle generation provenance is not immutable-base evidence",
        )
    _require_string_list(
        generation["audit_command"],
        "generation/audit_command",
    )
    _validate_inventory(oracle["inventory"])
    _validate_byte_contracts(oracle["byte_contracts"])
    _validate_interruption_profiles(oracle["interruption_profiles"])
    _validate_cross_product(oracle["cross_product"])
    evidence = oracle["base_test_evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise _error(
            "ORACLE_BASE_EVIDENCE_INVALID",
            "oracle must bind isolated base test evidence",
        )
    for index, raw in enumerate(evidence):
        record = _require_exact_fields(
            raw,
            {"command", "tests", "result"},
            field=f"base_test_evidence/{index}",
        )
        _require_string_list(
            record["command"], f"base_test_evidence/{index}/command"
        )
        _require_string_list(
            record["tests"],
            f"base_test_evidence/{index}/tests",
            sorted_values=True,
        )
        if record["result"] != "passed":
            raise _error(
                "ORACLE_BASE_EVIDENCE_INVALID",
                "frozen positive base evidence must have passed",
                field=f"base_test_evidence/{index}/result",
            )
    unsupported = _require_string_list(
        oracle["unsupported_injection_points"],
        "unsupported_injection_points",
        sorted_values=True,
    )
    if not unsupported:
        raise _error(
            "ORACLE_UNSUPPORTED_INJECTION_INCOMPLETE",
            "base-unsupported injection points must be explicit",
        )
    supplied_digest = _require_string(
        oracle["fixture_sha256"],
        "fixture_sha256",
        pattern=_SHA256_RE,
    )
    expected_digest = oracle_fixture_sha256(oracle)
    if supplied_digest != expected_digest:
        raise _error(
            "ORACLE_FIXTURE_IDENTITY_MISMATCH",
            "oracle fixture identity differs from its frozen content",
            details={
                "expected": expected_digest,
                "actual": supplied_digest,
            },
        )
    return oracle


def load_frozen_oracle(path: Path) -> Mapping[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _error(
            "ORACLE_READ_FAILED",
            "frozen oracle fixture cannot be read",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            "ORACLE_PARSE_FAILED",
            "frozen oracle fixture is not valid UTF-8 JSON",
            details={"path": str(path)},
        ) from exc
    return validate_oracle(value)


def _run_git(
    repository: Path, arguments: Sequence[str], *, text: bool = False
) -> subprocess.CompletedProcess[Any]:
    allowed = {"cat-file", "rev-parse", "ls-tree"}
    if not arguments or arguments[0] not in allowed:
        raise _error(
            "ORACLE_GIT_COMMAND_FORBIDDEN",
            "oracle permits only read-only Git object commands",
            details={"arguments": list(arguments)},
        )
    environment = os.environ.copy()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=text,
        env=environment,
    )
    if result.returncode != 0:
        stderr = (
            result.stderr
            if isinstance(result.stderr, str)
            else result.stderr.decode("utf-8", "backslashreplace")
        )
        raise _error(
            "ORACLE_GIT_OBJECT_FAILED",
            "read-only Git object command failed",
            details={
                "arguments": list(arguments),
                "stderr": stderr.strip(),
            },
        )
    return result


def _base_blob(repository: Path, path: str) -> bytes:
    result = _run_git(
        repository,
        ["cat-file", "blob", f"{BASE_COMMIT}:{path}"],
    )
    return bytes(result.stdout)


def _cli_commands(source: bytes) -> tuple[str, ...]:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeError, SyntaxError) as exc:
        raise _error(
            "ORACLE_CLI_AUDIT_FAILED",
            "CLI source cannot be parsed",
        ) from exc
    commands: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            commands.append(node.args[0].value)
    return tuple(commands)


def _candidate_cli_commands(
    plugin_root: Path, cli_source: bytes
) -> tuple[str, ...]:
    """Read candidate commands from either legacy literals or its manifest.

    The immutable base uses literal ``add_parser("...")`` calls.  The
    candidate may instead route those same parsers through the sealed command
    registry, whose checked-in manifest remains candidate evidence rather than
    an oracle source.
    """

    literal_commands = _cli_commands(cli_source)
    if literal_commands:
        return literal_commands
    manifest_path = (
        plugin_root / "workflows" / "runtime" / "commands.json"
    )
    try:
        value = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
            "candidate command inventory cannot be read",
            details={"path": str(manifest_path)},
        ) from exc
    if not isinstance(value, Mapping):
        raise _error(
            "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
            "candidate command manifest must be an object",
            details={"path": str(manifest_path)},
        )
    entries = value.get("entries")
    if not isinstance(entries, list) or not entries:
        raise _error(
            "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
            "candidate command manifest has no entries",
            details={"path": str(manifest_path)},
        )
    registered: list[tuple[int, str, str]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise _error(
                "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
                "candidate command entry must be an object",
                details={"entry": index},
            )
        command = raw.get("command")
        order = raw.get("parser_order")
        symbols = raw.get("symbols")
        parser_factory = (
            symbols.get("parser_factory")
            if isinstance(symbols, Mapping)
            else None
        )
        if (
            not isinstance(command, str)
            or not _COMMAND_RE.fullmatch(command)
            or isinstance(order, bool)
            or not isinstance(order, int)
            or order < 0
            or not isinstance(parser_factory, str)
            or not parser_factory
        ):
            raise _error(
                "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
                "candidate command entry is incomplete",
                details={"entry": index},
            )
        registered.append((order, command, parser_factory))
    orders = [item[0] for item in registered]
    commands = [item[1] for item in registered]
    if (
        len(set(orders)) != len(orders)
        or len(set(commands)) != len(commands)
        or sorted(orders) != list(range(len(registered)))
    ):
        raise _error(
            "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
            "candidate parser orders and commands must be unique and contiguous",
            details={"path": str(manifest_path)},
        )
    cli_text = cli_source.decode("utf-8")
    missing_factories = sorted(
        factory
        for _, _, factory in registered
        if f"def {factory}" not in cli_text
    )
    if missing_factories:
        raise _error(
            "ORACLE_CANDIDATE_COMMAND_INVENTORY_FAILED",
            "candidate command parser factories are missing",
            details={"missing": missing_factories},
        )
    return tuple(
        command for _, command, _ in sorted(registered)
    )


def verify_base_objects(
    repository: Path, oracle: Mapping[str, object]
) -> dict[str, object]:
    """Verify every frozen source/test blob from immutable Git objects."""

    validated = validate_oracle(oracle)
    actual_tree = str(
        _run_git(
            repository,
            ["rev-parse", f"{BASE_COMMIT}^{{tree}}"],
            text=True,
        ).stdout
    ).strip()
    if actual_tree != BASE_TREE:
        raise _error(
            "ORACLE_BASE_TREE_MISMATCH",
            "immutable base tree differs from the frozen identity",
            details={"expected": BASE_TREE, "actual": actual_tree},
        )
    base = validated["base"]
    assert isinstance(base, Mapping)
    verified: list[str] = []
    blobs: dict[str, bytes] = {}
    source_objects = base["source_objects"]
    assert isinstance(source_objects, list)
    for raw in source_objects:
        assert isinstance(raw, Mapping)
        path = str(raw["path"])
        listing = bytes(
            _run_git(
                repository,
                ["ls-tree", "-z", BASE_COMMIT, "--", path],
            ).stdout
        )
        metadata, separator, listed_path = listing.partition(b"\t")
        if (
            not separator
            or listed_path.rstrip(b"\0").decode("utf-8") != path
        ):
            raise _error(
                "ORACLE_BASE_OBJECT_MISSING",
                "frozen base object is absent",
                details={"path": path},
            )
        mode, object_type, blob = metadata.decode("ascii").split(" ")
        if (
            mode != raw["mode"]
            or object_type != "blob"
            or blob != raw["blob"]
        ):
            raise _error(
                "ORACLE_BASE_OBJECT_MISMATCH",
                "base object metadata differs from the fixture",
                details={"path": path},
            )
        content = _base_blob(repository, path)
        if (
            len(content) != raw["size"]
            or hashlib.sha256(content).hexdigest()
            != raw["content_sha256"]
        ):
            raise _error(
                "ORACLE_BASE_OBJECT_MISMATCH",
                "base object content differs from the fixture",
                details={"path": path},
            )
        blobs[path] = content
        verified.append(path)
    inventory = validated["inventory"]
    assert isinstance(inventory, Mapping)
    base_commands = tuple(inventory["base_cli_commands"])
    cli_source = blobs.get("scripts/dev_flow_parts/cli.py")
    if cli_source is None or _cli_commands(cli_source) != base_commands:
        raise _error(
            "ORACLE_BASE_COMMAND_INVENTORY_MISMATCH",
            "base CLI inventory differs from the frozen command order",
        )
    _verify_source_anchors(validated, blobs, label="base")
    return {
        "base_commit": BASE_COMMIT,
        "base_tree": BASE_TREE,
        "verified_source_objects": verified,
        "base_cli_commands": list(base_commands),
    }


def _verify_source_anchors(
    oracle: Mapping[str, object],
    sources: Mapping[str, bytes],
    *,
    label: str,
) -> None:
    rows = oracle["cross_product"]
    assert isinstance(rows, list)
    for raw in rows:
        assert isinstance(raw, Mapping)
        anchors = raw["source_anchors"]
        assert isinstance(anchors, list)
        for raw_anchor in anchors:
            assert isinstance(raw_anchor, Mapping)
            path = str(raw_anchor["path"])
            content = sources.get(path)
            if content is None:
                raise _error(
                    "ORACLE_SOURCE_ANCHOR_MISSING",
                    f"{label} source file is missing",
                    details={
                        "variant_id": raw["variant_id"],
                        "path": path,
                    },
                )
            text = content.decode("utf-8")
            missing = [
                token
                for token in raw_anchor["tokens"]  # type: ignore[union-attr]
                if token not in text
            ]
            if missing:
                raise _error(
                    "ORACLE_SOURCE_ANCHOR_MISSING",
                    f"{label} source no longer exposes frozen observation seams",
                    details={
                        "variant_id": raw["variant_id"],
                        "path": path,
                        "tokens": missing,
                    },
                )


def audit_candidate(
    plugin_root: Path, oracle: Mapping[str, object]
) -> dict[str, object]:
    """Audit candidate inventory without deriving expected observations."""

    validated = validate_oracle(oracle)
    cli_path = plugin_root / "scripts" / "dev_flow_parts" / "cli.py"
    try:
        cli_source = cli_path.read_bytes()
    except OSError as exc:
        raise _error(
            "ORACLE_CANDIDATE_READ_FAILED",
            "candidate CLI source cannot be read",
            details={"path": str(cli_path), "error": str(exc)},
        ) from exc
    candidate_cli = _candidate_cli_commands(plugin_root, cli_source)
    inventory = validated["inventory"]
    assert isinstance(inventory, Mapping)
    base_commands = tuple(inventory["base_cli_commands"])
    missing_commands = [
        command for command in base_commands if command not in candidate_cli
    ]
    if missing_commands:
        raise _error(
            "ORACLE_CANDIDATE_INVENTORY_INCOMPLETE",
            "candidate removed retained legacy CLI commands",
            details={"missing": missing_commands},
        )
    source_paths = {
        str(anchor["path"])
        for row in validated["cross_product"]  # type: ignore[union-attr]
        for anchor in row["source_anchors"]
    }
    sources: dict[str, bytes] = {}
    for relative in source_paths:
        path = plugin_root / relative
        try:
            sources[relative] = path.read_bytes()
        except OSError as exc:
            raise _error(
                "ORACLE_CANDIDATE_READ_FAILED",
                "candidate source anchor file cannot be read",
                details={"path": str(path), "error": str(exc)},
            ) from exc
    _verify_source_anchors(validated, sources, label="candidate")
    return {
        "retained_base_commands": list(base_commands),
        "candidate_cli_commands": list(candidate_cli),
        "additional_candidate_commands": [
            item for item in candidate_cli if item not in base_commands
        ],
        "verified_variants": sorted(_REQUIRED_VARIANTS),
        "task_schema_versions": [1, 2],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the frozen legacy base side-effect oracle"
    )
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--object-repository", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        oracle = load_frozen_oracle(Path(args.fixture))
        base = verify_base_objects(
            Path(args.object_repository), oracle
        )
        candidate = audit_candidate(Path(args.plugin_root), oracle)
    except OracleError as exc:
        print(
            json.dumps(
                {"ok": False, "error": exc.as_dict()},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {"ok": True, "base": base, "candidate": candidate},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
