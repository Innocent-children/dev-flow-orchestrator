"""Strict causal review findings and controller-derived review outcomes."""

from __future__ import annotations

import hashlib
from typing import Mapping, Optional, Sequence

from .model import DevFlowError, canonical_json_bytes, json_value
from .product import (
    FINDING_DISPOSITION_SCHEMA,
    MAX_REVIEW_FINDINGS,
    MAX_TEXT_FIELD_BYTES,
    REVIEW_FINDING_SCHEMA,
    product_domain,
)


CAUSAL_RELATIONS = (
    "introduced",
    "affected",
    "pre-existing",
    "out-of-scope",
    "unknown",
)
SEVERITIES = ("critical", "high", "medium", "low", "advisory")
DISPOSITIONS = ("accepted-risk", "confirmed-out-of-scope", "expand-contract")
REVIEW_OUTCOMES = (
    "approved",
    "changes-requested",
    "triage-required",
    "unavailable",
)

_FINDING_DOMAIN = product_domain("review-finding")
_REVIEW_DOMAIN = product_domain("independent-review")
_DISPOSITION_DOMAIN = product_domain("finding-disposition")


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def _digest(domain: bytes, value: Mapping[str, object]) -> str:
    return hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def _text(value: object, field: str, *, optional: bool = False) -> Optional[str]:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _error("REVIEW_FINDING_INVALID", "{} is invalid".format(field))
    normalized = value.strip()
    if len(normalized.encode("utf-8")) > MAX_TEXT_FIELD_BYTES:
        raise _error("REVIEW_FINDING_INVALID", "{} exceeds the text bound".format(field))
    return normalized


def _safe_path(path: object) -> Optional[str]:
    if path is None:
        return None
    value = _text(path, "finding path")
    if value.startswith("/") or value in (".", "..") or "\\" in value:
        raise _error("REVIEW_FINDING_INVALID", "finding path is unsafe", path=value)
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise _error("REVIEW_FINDING_INVALID", "finding path is unsafe", path=value)
    return value


def _criteria(contract: Mapping[str, object]) -> tuple:
    values = contract.get("acceptance_criteria")
    if not isinstance(values, (list, tuple)) or not values:
        raise _error("REVIEW_FINDING_INVALID", "contract criteria are invalid")
    result = tuple(
        item.get("id")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    )
    if len(result) != len(values) or len(set(result)) != len(result):
        raise _error("REVIEW_FINDING_INVALID", "contract criteria are invalid")
    return result


def _manifest_keys(manifest: Mapping[str, object]) -> set:
    entries = manifest.get("entries")
    if not isinstance(entries, (list, tuple)):
        raise _error("REVIEW_FINDING_INVALID", "task manifest is invalid")
    return {
        (item.get("repository_id"), item.get("path"))
        for item in entries
        if isinstance(item, Mapping)
    }


def _closure_keys(plan: Mapping[str, object]) -> set:
    result = set()
    for obligation in plan.get("obligations", ()):
        if not isinstance(obligation, Mapping):
            continue
        closure = obligation.get("impact_closure")
        values = closure.get("entries", ()) if isinstance(closure, Mapping) else closure
        if not isinstance(values, (list, tuple)):
            continue
        for item in values:
            if isinstance(item, Mapping):
                result.add((item.get("repository_id"), item.get("path")))
    return result


def finding_fingerprint(body: Mapping[str, object]) -> str:
    """Return the canonical fingerprint over immutable finding content."""
    return _digest(_FINDING_DOMAIN, body)


def validate_finding(
    value: object,
    *,
    task_id: str,
    contract: Mapping[str, object],
    contract_digest: str,
    plan: Mapping[str, object],
    manifest: Mapping[str, object],
    repository_ids: Sequence[str],
    review_scope_digest: str,
    guidance_digest: str,
    reviewer_digest: str,
    workspace_digest: str,
) -> dict:
    """Validate one finding and derive impact-gap/triage authority."""
    fields = {
        "schema", "finding_id", "fingerprint", "severity", "blocking",
        "causal_relation", "criterion_ids", "repository_id", "path", "symbol",
        "location_label", "evidence", "causal_manifest_entries", "causal_path",
        "smallest_sufficient_resolution", "reviewer_assurance", "limitations",
        "task_id", "contract_digest", "plan_digest", "manifest_digest",
        "review_scope_digest", "guidance_digest", "reviewer_digest",
        "workspace_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("REVIEW_FINDING_INVALID", "review finding fields are invalid")
    relation = value.get("causal_relation")
    severity = value.get("severity")
    blocking = value.get("blocking")
    if relation not in CAUSAL_RELATIONS or severity not in SEVERITIES or not isinstance(blocking, bool):
        raise _error("REVIEW_FINDING_INVALID", "finding classification is invalid")
    repository_id = value.get("repository_id")
    if repository_id not in repository_ids:
        raise _error("REVIEW_FINDING_INVALID", "finding repository is outside membership")
    path = _safe_path(value.get("path"))
    symbol = _text(value.get("symbol"), "finding symbol", optional=True)
    label = _text(value.get("location_label"), "finding location", optional=True)
    if path is None and symbol is None and label is None:
        raise _error("REVIEW_FINDING_INVALID", "finding has no bounded location")
    criterion_ids = value.get("criterion_ids")
    valid_criteria = set(_criteria(contract))
    if (
        not isinstance(criterion_ids, (list, tuple))
        or not criterion_ids
        or tuple(criterion_ids) != tuple(sorted(criterion_ids))
        or len(set(criterion_ids)) != len(criterion_ids)
        or not set(criterion_ids).issubset(valid_criteria)
    ):
        raise _error("REVIEW_FINDING_INVALID", "finding criterion mapping is invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, (list, tuple)) or not evidence:
        raise _error("REVIEW_FINDING_INVALID", "finding evidence is unavailable")
    normalized_evidence = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"kind", "reference", "summary", "source_confirmed"}:
            raise _error("REVIEW_FINDING_INVALID", "finding evidence item is invalid")
        if not isinstance(item.get("source_confirmed"), bool):
            raise _error("REVIEW_FINDING_INVALID", "finding evidence confidence is invalid")
        normalized_evidence.append({
            "kind": _text(item.get("kind"), "evidence kind"),
            "reference": _text(item.get("reference"), "evidence reference"),
            "summary": _text(item.get("summary"), "evidence summary"),
            "source_confirmed": item["source_confirmed"],
        })
    causal_entries = value.get("causal_manifest_entries")
    causal_path = value.get("causal_path")
    if not isinstance(causal_entries, (list, tuple)) or not isinstance(causal_path, (list, tuple)):
        raise _error("REVIEW_FINDING_INVALID", "finding causal evidence is invalid")
    normalized_causal_entries = []
    manifest_keys = _manifest_keys(manifest)
    for item in causal_entries:
        if not isinstance(item, Mapping) or set(item) != {"repository_id", "path"}:
            raise _error("REVIEW_FINDING_INVALID", "causal manifest reference is invalid")
        key = (item.get("repository_id"), _safe_path(item.get("path")))
        if key not in manifest_keys:
            raise _error("REVIEW_FINDING_INVALID", "causal manifest reference is stale")
        normalized_causal_entries.append({"repository_id": key[0], "path": key[1]})
    normalized_causal_path = []
    for item in causal_path:
        if not isinstance(item, Mapping) or set(item) != {"kind", "from", "to", "evidence", "source_confirmed"}:
            raise _error("REVIEW_FINDING_INVALID", "causal path step is invalid")
        if not isinstance(item.get("source_confirmed"), bool):
            raise _error("REVIEW_FINDING_INVALID", "causal path confidence is invalid")
        normalized_causal_path.append({
            "kind": _text(item.get("kind"), "causal path kind"),
            "from": _text(item.get("from"), "causal path source"),
            "to": _text(item.get("to"), "causal path target"),
            "evidence": _text(item.get("evidence"), "causal path evidence"),
            "source_confirmed": item["source_confirmed"],
        })
    if relation == "introduced" and (
        (repository_id, path) not in manifest_keys
        or {(
            item["repository_id"], item["path"]
        ) for item in normalized_causal_entries}
        != {(repository_id, path)}
    ):
        raise _error(
            "REVIEW_FINDING_INVALID",
            "introduced finding must bind its exact task manifest entry",
        )
    if relation == "affected" and (
        not normalized_causal_entries
        or not normalized_causal_path
        or not all(item["source_confirmed"] for item in normalized_causal_path)
    ):
        raise _error("REVIEW_FINDING_INVALID", "affected finding lacks bounded source-confirmed causality")
    limitations = value.get("limitations")
    if not isinstance(limitations, (list, tuple)):
        raise _error("REVIEW_FINDING_INVALID", "finding limitations are invalid")
    bindings = {
        "task_id": task_id,
        "contract_digest": contract_digest,
        "plan_digest": plan.get("digest"),
        "manifest_digest": manifest.get("digest"),
        "review_scope_digest": review_scope_digest,
        "guidance_digest": guidance_digest,
        "reviewer_digest": reviewer_digest,
        "workspace_digest": workspace_digest,
    }
    if any(value.get(key) != expected for key, expected in bindings.items()):
        raise _error("REVIEW_FINDING_INVALID", "finding bindings are stale")
    body = {
        "schema": REVIEW_FINDING_SCHEMA,
        "severity": severity,
        "blocking": blocking,
        "causal_relation": relation,
        "criterion_ids": list(criterion_ids),
        "repository_id": repository_id,
        "path": path,
        "symbol": symbol,
        "location_label": label,
        "evidence": normalized_evidence,
        "causal_manifest_entries": normalized_causal_entries,
        "causal_path": normalized_causal_path,
        "smallest_sufficient_resolution": _text(value.get("smallest_sufficient_resolution"), "smallest sufficient resolution"),
        "reviewer_assurance": _text(value.get("reviewer_assurance"), "reviewer assurance"),
        "limitations": [_text(item, "finding limitation") for item in limitations],
        **bindings,
    }
    fingerprint = finding_fingerprint(body)
    expected_id = "finding-{}".format(fingerprint[:16])
    if value.get("fingerprint") != fingerprint or value.get("finding_id") != expected_id:
        raise _error("REVIEW_FINDING_INVALID", "finding identity is invalid")
    impact_gap = relation == "affected" and (repository_id, path) not in _closure_keys(plan)
    return {
        **body,
        "finding_id": expected_id,
        "fingerprint": fingerprint,
        "impact_gap": impact_gap,
    }


def finding_template(body: Mapping[str, object]) -> dict:
    """Seal caller-supplied canonical finding fields for agent/test construction."""
    plain = json_value(body)
    fingerprint = finding_fingerprint(plain)
    return {
        **plain,
        "finding_id": "finding-{}".format(fingerprint[:16]),
        "fingerprint": fingerprint,
    }


def derive_review_result(
    *,
    plan: Mapping[str, object],
    review_obligation: Mapping[str, object],
    findings: Sequence[Mapping[str, object]],
    reviewer_available: bool,
    independent: bool,
    disposition_fingerprints: Sequence[str] = (),
    claimed_outcome: Optional[str] = None,
) -> dict:
    """Derive the aggregate outcome; reviewer output is never verdict authority."""
    if len(findings) > MAX_REVIEW_FINDINGS:
        raise _error("REVIEW_FINDING_LIMIT", "review exceeds the finding bound", finding_limit=MAX_REVIEW_FINDINGS)
    if review_obligation.get("kind") != "independent-review":
        raise _error("REVIEW_INVALID", "review is not bound to a review obligation")
    if not reviewer_available or not independent:
        outcome = "unavailable"
        rework = ()
        triage = ()
        gaps = ()
    else:
        current = [item for item in findings if item.get("fingerprint") not in disposition_fingerprints]
        gaps = tuple(sorted(item["fingerprint"] for item in current if item.get("impact_gap") is True))
        triage = tuple(sorted(item["fingerprint"] for item in current if item.get("blocking") is True and item.get("causal_relation") == "unknown"))
        rework = tuple(sorted(item["fingerprint"] for item in current if item.get("blocking") is True and item.get("causal_relation") in ("introduced", "affected") and not item.get("impact_gap")))
        if gaps or triage:
            outcome = "triage-required"
        elif rework:
            outcome = "changes-requested"
        else:
            outcome = "approved"
    if claimed_outcome is not None and claimed_outcome != outcome:
        raise _error("REVIEW_OUTCOME_CONTRADICTORY", "submitted review outcome contradicts controller derivation", claimed=claimed_outcome, derived=outcome)
    base = {
        "schema": "dev-flow-independent-review/0.4.0",
        "plan_digest": plan.get("digest"),
        "obligation_id": review_obligation.get("obligation_id"),
        "reviewer_available": reviewer_available,
        "independent": independent,
        "finding_fingerprints": [item["fingerprint"] for item in findings],
        "outcome": outcome,
        "rework_fingerprints": list(rework),
        "triage_fingerprints": list(triage),
        "impact_gap_fingerprints": list(gaps),
    }
    return {**base, "digest": _digest(_REVIEW_DOMAIN, base)}


def validate_disposition(
    value: object,
    *,
    task_id: str,
    contract_digest: str,
    plan_digest: str,
    review_digest: str,
    finding_fingerprint_value: str,
    expected_revision: int,
    current_revision: int,
    actor_authorized: bool,
) -> dict:
    fields = {
        "schema", "kind", "task_id", "contract_digest", "plan_digest",
        "review_digest", "finding_fingerprint", "actor", "rationale",
        "expected_revision", "next_contract",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("FINDING_DISPOSITION_INVALID", "finding disposition fields are invalid")
    if expected_revision != current_revision or value.get("expected_revision") != expected_revision:
        raise _error("REVISION_CONFLICT", "finding disposition revision is stale")
    if not actor_authorized:
        raise _error("FINDING_DISPOSITION_FORBIDDEN", "finding disposition requires task authority")
    kind = value.get("kind")
    if kind not in DISPOSITIONS:
        raise _error("FINDING_DISPOSITION_INVALID", "finding disposition kind is invalid")
    bindings = {
        "schema": FINDING_DISPOSITION_SCHEMA,
        "task_id": task_id,
        "contract_digest": contract_digest,
        "plan_digest": plan_digest,
        "review_digest": review_digest,
        "finding_fingerprint": finding_fingerprint_value,
        "expected_revision": expected_revision,
    }
    if any(value.get(key) != expected for key, expected in bindings.items()):
        raise _error("FINDING_DISPOSITION_INVALID", "finding disposition binding is stale")
    next_contract = value.get("next_contract")
    if (kind == "expand-contract") != isinstance(next_contract, Mapping):
        raise _error("FINDING_DISPOSITION_INVALID", "expand-contract requires one atomic next contract")
    base = {
        **bindings,
        "kind": kind,
        "actor": _text(value.get("actor"), "disposition actor"),
        "rationale": _text(value.get("rationale"), "disposition rationale"),
        "next_contract": None if next_contract is None else json_value(next_contract),
    }
    return {**base, "digest": _digest(_DISPOSITION_DOMAIN, base)}
