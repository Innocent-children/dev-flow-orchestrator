"""Derived action-payload authority shared by Controller and MCP projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .capsule import OWNERSHIP_CLASSIFICATIONS
from .model import freeze_json, json_value
from .product import (
    IMPACT_CONFIDENCE_VALUES,
    MAX_IMPACT_ENTRIES,
    MAX_OWNERSHIP_CLAIMS,
    RISK_TRIGGER_IDS,
    TASK_CHANGE_CLAIMS_SCHEMA,
)
from .workflow import NodeContract


@dataclass(frozen=True)
class EffectivePayloadContract:
    """Exact top-level fields plus their self-contained public JSON Schema."""

    field_types: Mapping[str, str]
    required_fields: tuple[str, ...]
    schema: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_types", freeze_json(self.field_types))
        object.__setattr__(self, "schema", freeze_json(self.schema))

    def schema_dict(self) -> dict:
        return json_value(self.schema)


def _identity_schema(values: Sequence[str]) -> dict:
    identities = sorted(set(values))
    if identities:
        return {"type": "string", "enum": identities}
    return {"type": "string", "minLength": 1}


def _criterion_list_schema(criterion_ids: Sequence[str]) -> dict:
    return {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": _identity_schema(criterion_ids),
    }


def _impact_manifest_schema(
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
) -> dict:
    entry_fields = ("repository_id", "path", "symbol", "criterion_ids")
    edge_fields = (
        "from_repository_id",
        "to_repository_id",
        "evidence_contract",
        "criterion_ids",
        "affected",
    )
    repository = _identity_schema(repository_ids)
    criteria = _criterion_list_schema(criterion_ids)
    fields = (
        "confidence",
        "entries",
        "edges",
        "risk_triggers",
        "public_behavior",
        "documentation_required",
        "manual_evidence_required",
        "executable_reproduction_required",
        "overflow",
        "limitations",
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(fields),
        "properties": {
            "confidence": {
                "type": "string",
                "enum": list(IMPACT_CONFIDENCE_VALUES),
            },
            "entries": {
                "type": "array",
                "maxItems": MAX_IMPACT_ENTRIES,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(entry_fields),
                    "properties": {
                        "repository_id": repository,
                        "path": {"type": ["string", "null"], "minLength": 1},
                        "symbol": {"type": ["string", "null"], "minLength": 1},
                        "criterion_ids": criteria,
                    },
                    "anyOf": [
                        {"properties": {"path": {"type": "string", "minLength": 1}}},
                        {"properties": {"symbol": {"type": "string", "minLength": 1}}},
                    ],
                },
            },
            "edges": {
                "type": "array",
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(edge_fields),
                    "properties": {
                        "from_repository_id": repository,
                        "to_repository_id": repository,
                        "evidence_contract": {"type": "string", "minLength": 1},
                        "criterion_ids": criteria,
                        "affected": {"type": "boolean"},
                    },
                },
            },
            "risk_triggers": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string", "enum": list(RISK_TRIGGER_IDS)},
            },
            "public_behavior": {"type": "boolean"},
            "documentation_required": {"type": "boolean"},
            "manual_evidence_required": {"type": "boolean"},
            "executable_reproduction_required": {"type": "boolean"},
            "overflow": {"type": "boolean"},
            "limitations": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


def _ownership_claims_schema(
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
) -> dict:
    claim_fields = (
        "repository_id",
        "path",
        "classification",
        "criterion_ids",
        "purpose",
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "claims"],
        "properties": {
            "schema": {"const": TASK_CHANGE_CLAIMS_SCHEMA},
            "claims": {
                "type": "array",
                "maxItems": MAX_OWNERSHIP_CLAIMS,
                "uniqueItems": True,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(claim_fields),
                    "properties": {
                        "repository_id": _identity_schema(repository_ids),
                        "path": {"type": "string", "minLength": 1},
                        "classification": {
                            "type": "string",
                            "enum": list(OWNERSHIP_CLASSIFICATIONS),
                        },
                        "criterion_ids": _criterion_list_schema(criterion_ids),
                        "purpose": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def _field_schema(
    field: str,
    field_type: str,
    *,
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
) -> dict:
    if field == "impact_manifest":
        return _impact_manifest_schema(repository_ids, criterion_ids)
    if field == "ownership_claims":
        return _ownership_claims_schema(repository_ids, criterion_ids)
    if field_type == "string":
        return {"type": "string", "minLength": 1}
    if field_type == "boolean":
        return {"type": "boolean"}
    if field_type == "integer":
        return {"type": "integer"}
    if field_type == "sha256":
        return {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    return {"type": "object"}


def effective_payload_contract(
    node: NodeContract,
    *,
    repository_ids: Sequence[str] = (),
    criterion_ids: Sequence[str] = (),
) -> EffectivePayloadContract:
    """Return the sole live payload field set and its complete public schema."""
    field_types = dict(node.payload_types)
    if (
        node.artifact is not None
        and node.artifact.workspace_role == "produces-source"
        and node.handler_id != "preflight"
    ):
        field_types["ownership_claims"] = "object"
    if node.artifact is not None and node.artifact.artifact_type == "impact-report":
        field_types["impact_manifest"] = "object"
    if node.handler_id == "assurance.dispatch":
        field_types["assurance_result"] = "object"
    required_fields = tuple(sorted(field_types))
    properties = {
        field: _field_schema(
            field,
            field_type,
            repository_ids=repository_ids,
            criterion_ids=criterion_ids,
        )
        for field, field_type in field_types.items()
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(required_fields),
        "properties": properties,
    }
    return EffectivePayloadContract(
        field_types=field_types,
        required_fields=required_fields,
        schema=schema,
    )
