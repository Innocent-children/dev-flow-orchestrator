"""Derived action-payload authority shared by Controller and MCP projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .capsule import OWNERSHIP_CLASSIFICATIONS
from .model import freeze_json, json_value
from .product import (
    IMPACT_CONFIDENCE_VALUES,
    MAX_EVIDENCE_ITEMS,
    MAX_IMPACT_ENTRIES,
    MAX_OWNERSHIP_CLAIMS,
    MAX_REVIEW_FINDINGS,
    REVIEW_FINDING_SCHEMA,
    RISK_TRIGGER_IDS,
    TASK_CHANGE_CLAIMS_SCHEMA,
)
from .workflow import NodeContract


ASSURANCE_RESULT_FIELDS = (
    "obligation_id",
    "passed",
    "evidence",
    "limitations",
)
ASSURANCE_EVIDENCE_FIELDS = ("kind", "reference", "summary")
INDEPENDENT_REVIEW_FIELDS = (
    "reviewer_available",
    "independent",
    "reviewer_digest",
    "review_scope_digest",
    "guidance_digest",
    "workspace_digest",
    "findings",
    "claimed_outcome",
)
REVIEW_FINDING_FIELDS = (
    "schema",
    "finding_id",
    "fingerprint",
    "severity",
    "blocking",
    "causal_relation",
    "criterion_ids",
    "repository_id",
    "path",
    "symbol",
    "location_label",
    "evidence",
    "causal_manifest_entries",
    "causal_path",
    "smallest_sufficient_resolution",
    "reviewer_assurance",
    "limitations",
    "task_id",
    "contract_digest",
    "plan_digest",
    "manifest_digest",
    "review_scope_digest",
    "guidance_digest",
    "reviewer_digest",
    "workspace_digest",
)
REVIEW_FINDING_EVIDENCE_FIELDS = (
    "kind",
    "reference",
    "summary",
    "source_confirmed",
)
REVIEW_CAUSAL_MANIFEST_FIELDS = ("repository_id", "path")
REVIEW_CAUSAL_PATH_FIELDS = (
    "kind",
    "from",
    "to",
    "evidence",
    "source_confirmed",
)
REVIEW_CAUSAL_RELATIONS = (
    "introduced",
    "affected",
    "pre-existing",
    "out-of-scope",
    "unknown",
)
REVIEW_SEVERITIES = ("critical", "high", "medium", "low", "advisory")
REVIEW_OUTCOMES = (
    "approved",
    "changes-requested",
    "triage-required",
    "unavailable",
)


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


def _non_empty_text_schema(*, nullable: bool = False) -> dict:
    return {
        "type": ["string", "null"] if nullable else "string",
        "minLength": 1,
    }


def _sha256_schema(value: object = None) -> dict:
    if isinstance(value, str) and len(value) == 64:
        return {"const": value}
    return {"type": "string", "pattern": "^[0-9a-f]{64}$"}


def _digest_identity_schema() -> dict:
    """Match the current reviewer identity contract: exactly 64 text characters."""
    return {"type": "string", "minLength": 64, "maxLength": 64}


def _bound_text_schema(value: object) -> dict:
    if isinstance(value, str) and value:
        return {"const": value}
    return _non_empty_text_schema()


def _assurance_evidence_schema() -> dict:
    return {
        "type": "array",
        "maxItems": MAX_EVIDENCE_ITEMS,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": list(ASSURANCE_EVIDENCE_FIELDS),
            "properties": {
                field: _non_empty_text_schema()
                for field in ASSURANCE_EVIDENCE_FIELDS
            },
        },
    }


def _review_finding_schema(
    *,
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
    review_bindings: Mapping[str, object],
) -> dict:
    text_or_null = _non_empty_text_schema(nullable=True)
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(REVIEW_FINDING_EVIDENCE_FIELDS),
        "properties": {
            "kind": _non_empty_text_schema(),
            "reference": _non_empty_text_schema(),
            "summary": _non_empty_text_schema(),
            "source_confirmed": {"type": "boolean"},
        },
    }
    causal_manifest_item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(REVIEW_CAUSAL_MANIFEST_FIELDS),
        "properties": {
            "repository_id": _identity_schema(repository_ids),
            "path": _non_empty_text_schema(),
        },
    }
    causal_path_item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(REVIEW_CAUSAL_PATH_FIELDS),
        "properties": {
            "kind": _non_empty_text_schema(),
            "from": _non_empty_text_schema(),
            "to": _non_empty_text_schema(),
            "evidence": _non_empty_text_schema(),
            "source_confirmed": {"type": "boolean"},
        },
    }
    properties = {
        "schema": {"const": REVIEW_FINDING_SCHEMA},
        "finding_id": {
            "type": "string",
            "pattern": "^finding-[0-9a-f]{16}$",
        },
        "fingerprint": _sha256_schema(),
        "severity": {"type": "string", "enum": list(REVIEW_SEVERITIES)},
        "blocking": {"type": "boolean"},
        "causal_relation": {
            "type": "string",
            "enum": list(REVIEW_CAUSAL_RELATIONS),
        },
        "criterion_ids": _criterion_list_schema(criterion_ids),
        "repository_id": _identity_schema(repository_ids),
        "path": text_or_null,
        "symbol": text_or_null,
        "location_label": text_or_null,
        "evidence": {
            "type": "array",
            "minItems": 1,
            "items": evidence_item,
        },
        "causal_manifest_entries": {
            "type": "array",
            "items": causal_manifest_item,
        },
        "causal_path": {"type": "array", "items": causal_path_item},
        "smallest_sufficient_resolution": _non_empty_text_schema(),
        "reviewer_assurance": _non_empty_text_schema(),
        "limitations": {
            "type": "array",
            "items": _non_empty_text_schema(),
        },
        "task_id": _bound_text_schema(review_bindings.get("task_id")),
        "contract_digest": _sha256_schema(review_bindings.get("contract_digest")),
        "plan_digest": _sha256_schema(review_bindings.get("plan_digest")),
        "manifest_digest": _sha256_schema(review_bindings.get("manifest_digest")),
        "review_scope_digest": _sha256_schema(
            review_bindings.get("review_scope_digest")
        ),
        "guidance_digest": _sha256_schema(review_bindings.get("guidance_digest")),
        "reviewer_digest": _digest_identity_schema(),
        "workspace_digest": _sha256_schema(review_bindings.get("workspace_digest")),
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(REVIEW_FINDING_FIELDS),
        "properties": properties,
        "anyOf": [
            {"required": ["path"], "properties": {"path": {"type": "string"}}},
            {
                "required": ["symbol"],
                "properties": {"symbol": {"type": "string"}},
            },
            {
                "required": ["location_label"],
                "properties": {"location_label": {"type": "string"}},
            },
        ],
    }


def _independent_review_schema(
    *,
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
    review_bindings: Mapping[str, object],
) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(INDEPENDENT_REVIEW_FIELDS),
        "properties": {
            "reviewer_available": {"type": "boolean"},
            "independent": {"type": "boolean"},
            "reviewer_digest": _digest_identity_schema(),
            "review_scope_digest": _sha256_schema(
                review_bindings.get("review_scope_digest")
            ),
            "guidance_digest": _sha256_schema(
                review_bindings.get("guidance_digest")
            ),
            "workspace_digest": _sha256_schema(
                review_bindings.get("workspace_digest")
            ),
            "findings": {
                "type": "array",
                "maxItems": MAX_REVIEW_FINDINGS,
                "items": _review_finding_schema(
                    repository_ids=repository_ids,
                    criterion_ids=criterion_ids,
                    review_bindings=review_bindings,
                ),
            },
            "claimed_outcome": {"enum": [None, *REVIEW_OUTCOMES]},
        },
    }


def assurance_result_schema(
    *,
    obligation: Optional[Mapping[str, object]] = None,
    repository_ids: Sequence[str] = (),
    criterion_ids: Sequence[str] = (),
    review_bindings: Optional[Mapping[str, object]] = None,
) -> dict:
    """Return the complete accepted assurance-result input schema."""
    obligation_id = obligation.get("obligation_id") if obligation is not None else None
    kind = obligation.get("kind") if obligation is not None else None
    bindings = review_bindings if review_bindings is not None else {}
    properties = {
        "obligation_id": _bound_text_schema(obligation_id),
        "passed": {"type": "boolean"},
        "evidence": _assurance_evidence_schema(),
        "limitations": {
            "type": "array",
            "items": _non_empty_text_schema(),
        },
    }
    basic = {
        "type": "object",
        "additionalProperties": False,
        "required": list(ASSURANCE_RESULT_FIELDS),
        "properties": properties,
    }
    review = {
        **basic,
        "required": [*ASSURANCE_RESULT_FIELDS, "review"],
        "properties": {
            **properties,
            "review": _independent_review_schema(
                repository_ids=repository_ids,
                criterion_ids=criterion_ids,
                review_bindings=bindings,
            ),
        },
    }
    if kind == "independent-review":
        return review
    if kind is not None:
        return basic
    return {"oneOf": [basic, review]}


def _field_schema(
    field: str,
    field_type: str,
    *,
    repository_ids: Sequence[str],
    criterion_ids: Sequence[str],
    assurance_schema: Optional[Mapping[str, object]],
) -> dict:
    if field == "impact_manifest":
        return _impact_manifest_schema(repository_ids, criterion_ids)
    if field == "ownership_claims":
        return _ownership_claims_schema(repository_ids, criterion_ids)
    if field == "assurance_result":
        return json_value(
            assurance_schema
            if assurance_schema is not None
            else assurance_result_schema(
                repository_ids=repository_ids,
                criterion_ids=criterion_ids,
            )
        )
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
    assurance_obligation: Optional[Mapping[str, object]] = None,
    assurance_review_bindings: Optional[Mapping[str, object]] = None,
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
    assurance_schema = (
        assurance_result_schema(
            obligation=assurance_obligation,
            repository_ids=repository_ids,
            criterion_ids=criterion_ids,
            review_bindings=assurance_review_bindings,
        )
        if node.handler_id == "assurance.dispatch"
        else None
    )
    properties = {
        field: _field_schema(
            field,
            field_type,
            repository_ids=repository_ids,
            criterion_ids=criterion_ids,
            assurance_schema=assurance_schema,
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
