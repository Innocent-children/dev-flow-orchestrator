"""Closed 0.3 adaptive-assurance policy, plans, dispatch, and budgets."""

from __future__ import annotations

import hashlib
from typing import Mapping, Optional, Sequence

from .model import DevFlowError, canonical_json_bytes, json_value
from .product import (
    ASSURANCE_EXECUTION_SCHEMA,
    ASSURANCE_OBLIGATION_SCHEMA,
    ASSURANCE_PLAN_SCHEMA,
    ASSURANCE_POLICY_SCHEMA,
    IMPACT_CONFIDENCE_VALUES,
    IMPACT_MANIFEST_SCHEMA,
    MAX_ASSURANCE_OBLIGATIONS,
    MAX_EVIDENCE_ITEMS,
    MAX_IMPACT_ENTRIES,
    MAX_REVIEW_FINDINGS,
    MAX_WORKFLOW_ACTIONS,
    RISK_TRIGGER_IDS,
    TASK_CHANGE_MANIFEST_SCHEMA,
    product_domain,
)


OBLIGATION_KINDS = (
    "repository-check",
    "integration-check",
    "documentation-check",
    "manual-evidence",
    "independent-review",
)
OBLIGATION_STATES = (
    "required",
    "blocked",
    "outstanding",
    "satisfied",
    "reused",
    "not-required",
    "waived",
    "exhausted",
)
POLICY_ID = ASSURANCE_POLICY_SCHEMA

_IMPACT_DOMAIN = product_domain("impact-manifest")
_OBLIGATION_DOMAIN = product_domain("assurance-obligation")
_PLAN_DOMAIN = product_domain("assurance-plan")
_EXECUTION_DOMAIN = product_domain("assurance-execution")


def _error(code: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(code, message, details=details)


def _digest(domain: bytes, value: Mapping[str, object]) -> str:
    return hashlib.sha256(domain + canonical_json_bytes(value)).hexdigest()


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _error("ASSURANCE_INVALID", "{} is invalid".format(field))
    if len(value.encode("utf-8")) > 8192:
        raise _error("ASSURANCE_INVALID", "{} exceeds the text bound".format(field))
    return value.strip()


def _criterion_ids(contract: Mapping[str, object]) -> tuple:
    values = contract.get("acceptance_criteria")
    if not isinstance(values, (list, tuple)) or not values:
        raise _error("ASSURANCE_INVALID", "contract acceptance criteria are invalid")
    result = tuple(
        item.get("id")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    )
    if len(result) != len(values) or len(set(result)) != len(result):
        raise _error("ASSURANCE_INVALID", "contract acceptance criteria are invalid")
    return result


def normalize_impact_report(
    value: object,
    *,
    repositories: Sequence[object],
    contract: Mapping[str, object],
    historical_replay: bool = False,
) -> dict:
    """Validate impact, preserving only the baseline confidence replay behavior."""
    fields = {
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
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("IMPACT_INVALID", "impact report fields are invalid")
    repository_ids = tuple(item.repository_id for item in repositories)
    criteria = set(_criterion_ids(contract))
    raw_entries = value.get("entries")
    overflow = value.get("overflow")
    if not isinstance(raw_entries, (list, tuple)) or not isinstance(overflow, bool):
        raise _error("IMPACT_INVALID", "impact report entry envelope is invalid")
    if len(raw_entries) > MAX_IMPACT_ENTRIES:
        raise _error(
            "IMPACT_OVERFLOW_INVALID",
            "overflowed impact must submit a bounded reason instead of a partial closure",
            entry_limit=MAX_IMPACT_ENTRIES,
        )
    entries = []
    seen_entries = set()
    for item in raw_entries:
        expected = {"repository_id", "path", "symbol", "criterion_ids"}
        if not isinstance(item, Mapping) or set(item) != expected:
            raise _error("IMPACT_INVALID", "impact entry fields are invalid")
        repository_id = item.get("repository_id")
        path = item.get("path")
        symbol = item.get("symbol")
        criterion_ids = item.get("criterion_ids")
        if (
            repository_id not in repository_ids
            or (path is None and symbol is None)
            or (path is not None and not isinstance(path, str))
            or (symbol is not None and not isinstance(symbol, str))
            or not isinstance(criterion_ids, (list, tuple))
            or not criterion_ids
            or tuple(criterion_ids) != tuple(sorted(criterion_ids))
            or len(set(criterion_ids)) != len(criterion_ids)
            or not set(criterion_ids).issubset(criteria)
        ):
            raise _error("IMPACT_INVALID", "impact entry is invalid")
        if path is not None:
            _text(path, "impact path")
        if symbol is not None:
            _text(symbol, "impact symbol")
        key = (repository_id, path, symbol)
        if key in seen_entries:
            raise _error("IMPACT_INVALID", "impact entries are not unique")
        seen_entries.add(key)
        entries.append(
            {
                "repository_id": repository_id,
                "path": path,
                "symbol": symbol,
                "criterion_ids": list(criterion_ids),
            }
        )
    raw_edges = value.get("edges")
    if not isinstance(raw_edges, (list, tuple)):
        raise _error("IMPACT_INVALID", "impact edges are invalid")
    edges = []
    seen_edges = set()
    for item in raw_edges:
        expected = {
            "from_repository_id",
            "to_repository_id",
            "evidence_contract",
            "criterion_ids",
            "affected",
        }
        if not isinstance(item, Mapping) or set(item) != expected:
            raise _error("IMPACT_INVALID", "impact edge fields are invalid")
        source = item.get("from_repository_id")
        target = item.get("to_repository_id")
        evidence_contract = item.get("evidence_contract")
        edge_criteria = item.get("criterion_ids")
        if (
            source not in repository_ids
            or target not in repository_ids
            or source == target
            or not isinstance(evidence_contract, str)
            or not evidence_contract.strip()
            or len(evidence_contract.encode("utf-8")) > 8192
            or not isinstance(edge_criteria, (list, tuple))
            or not edge_criteria
            or tuple(edge_criteria) != tuple(sorted(edge_criteria))
            or not set(edge_criteria).issubset(criteria)
            or not isinstance(item.get("affected"), bool)
        ):
            raise _error("IMPACT_INVALID", "impact edge is invalid")
        key = (source, target, evidence_contract)
        if key in seen_edges:
            raise _error("IMPACT_INVALID", "impact edges are not unique")
        seen_edges.add(key)
        edges.append(
            {
                "from_repository_id": source,
                "to_repository_id": target,
                "evidence_contract": evidence_contract.strip(),
                "criterion_ids": list(edge_criteria),
                "affected": item["affected"],
            }
        )
    triggers = value.get("risk_triggers")
    if (
        not isinstance(triggers, (list, tuple))
        or tuple(triggers) != tuple(sorted(triggers))
        or len(set(triggers)) != len(triggers)
        or not set(triggers).issubset(RISK_TRIGGER_IDS)
    ):
        raise _error("IMPACT_INVALID", "impact risk triggers are invalid")
    limitations = value.get("limitations")
    if not isinstance(limitations, (list, tuple)):
        raise _error("IMPACT_INVALID", "impact limitations are invalid")
    normalized_limitations = [_text(item, "impact limitation") for item in limitations]
    flags = {}
    for field in (
        "public_behavior",
        "documentation_required",
        "manual_evidence_required",
        "executable_reproduction_required",
    ):
        if not isinstance(value.get(field), bool):
            raise _error("IMPACT_INVALID", "impact flag is invalid", field=field)
        flags[field] = value[field]
    submitted_confidence = value.get("confidence")
    if (
        not historical_replay
        and submitted_confidence not in IMPACT_CONFIDENCE_VALUES
    ):
        raise _error("IMPACT_INVALID", "impact confidence is invalid")
    confidence = (
        "source-confirmed"
        if submitted_confidence == "source-confirmed" and not overflow
        else "unknown"
    )
    if confidence == "unknown" and submitted_confidence != "unknown":
        normalized_limitations.append(
            "submitted confidence {!r} normalized to unknown".format(submitted_confidence)
        )
    base = {
        "schema": IMPACT_MANIFEST_SCHEMA,
        "confidence": confidence,
        "entries": sorted(
            entries,
            key=lambda item: (
                item["repository_id"].encode("utf-8"),
                (item["path"] or "").encode("utf-8"),
                (item["symbol"] or "").encode("utf-8"),
            ),
        ),
        "edges": sorted(
            edges,
            key=lambda item: (
                item["evidence_contract"].encode("utf-8"),
                item["from_repository_id"].encode("utf-8"),
                item["to_repository_id"].encode("utf-8"),
            ),
        ),
        "risk_triggers": list(triggers),
        **flags,
        "overflow": overflow,
        "limitations": normalized_limitations,
    }
    return {**base, "digest": _digest(_IMPACT_DOMAIN, base)}


def _obligation(body: Mapping[str, object]) -> dict:
    identity = _digest(_OBLIGATION_DOMAIN, body)
    return {
        "schema": ASSURANCE_OBLIGATION_SCHEMA,
        "obligation_id": "obligation-{}".format(identity[:16]),
        "fingerprint": identity,
        **json_value(body),
    }


def _manifest_entries(manifest: Mapping[str, object]) -> tuple:
    entries = manifest.get("entries")
    if not isinstance(entries, (list, tuple)):
        raise _error("ASSURANCE_INVALID", "task change manifest entries are invalid")
    return tuple(entries)


def _budget_reservations(
    *,
    profile: str,
    repository_ids: Sequence[str],
    edges: Sequence[Mapping[str, object]],
    allowance: int,
) -> list:
    """Derive the stable conservative obligation subjects for one contract."""
    subjects = [
        {
            "kind": "repository-check",
            "repository_ids": [repository_id],
            "evidence_contract": None,
            "budget_class": "verification",
            "source_rework": True,
        }
        for repository_id in repository_ids
    ]
    edge_groups = {}
    for edge in edges:
        edge_groups.setdefault(str(edge["evidence_contract"]), []).append(edge)
    for evidence_contract in sorted(edge_groups, key=lambda item: item.encode("utf-8")):
        members = sorted({
            repository_id
            for edge in edge_groups[evidence_contract]
            for repository_id in (
                str(edge["from_repository_id"]),
                str(edge["to_repository_id"]),
            )
        })
        subjects.append({
            "kind": "integration-check",
            "repository_ids": members,
            "evidence_contract": evidence_contract,
            "budget_class": "verification",
            "source_rework": True,
        })
    subjects.extend((
        {
            "kind": "documentation-check",
            "repository_ids": list(repository_ids),
            "evidence_contract": None,
            "budget_class": "verification",
            "source_rework": True,
        },
        {
            "kind": "manual-evidence",
            "repository_ids": list(repository_ids),
            "evidence_contract": None,
            "budget_class": "verification",
            "source_rework": False,
        },
        {
            "kind": "independent-review",
            "repository_ids": list(repository_ids),
            "evidence_contract": None,
            "budget_class": "review",
            "source_rework": True,
        },
    ))
    reservations = []
    for subject in subjects:
        identity = hashlib.sha256(canonical_json_bytes({
            "profile": profile,
            **subject,
        })).hexdigest()
        reservations.append({
            "reservation_id": "reservation-{}".format(identity[:16]),
            **subject,
            "allowance": allowance,
            "retry_units": (
                max(allowance - 1, 0) if subject["source_rework"] else 0
            ),
        })
    return reservations


def _reservation_covers_obligation(
    reservation: Mapping[str, object],
    obligation: Mapping[str, object],
) -> bool:
    if reservation.get("kind") != obligation.get("kind"):
        return False
    kind = obligation.get("kind")
    if kind == "repository-check":
        return reservation.get("repository_ids") == obligation.get("repository_ids")
    if kind == "integration-check":
        evidence = obligation.get("evidence_contract")
        return bool(
            isinstance(evidence, Mapping)
            and reservation.get("repository_ids") == obligation.get("repository_ids")
            and reservation.get("evidence_contract") == evidence.get("name")
        )
    return True


def _prerequisite_reservations(
    reservation_set: Sequence[Mapping[str, object]],
) -> list:
    """Reserve one refresh subject for each conservative dependency set."""
    values = []
    prerequisite_reservation_ids = sorted(
        str(reservation["reservation_id"])
        for reservation in reservation_set
        if reservation.get("kind") != "independent-review"
    )
    for reservation in reservation_set:
        if reservation.get("kind") != "independent-review":
            continue
        body = {
            "dependent_reservation_id": reservation["reservation_id"],
            "dependent_kind": reservation["kind"],
            "prerequisite_reservation_ids": prerequisite_reservation_ids,
        }
        values.append({
            **body,
            "subject_fingerprint": hashlib.sha256(
                canonical_json_bytes(body)
            ).hexdigest(),
        })
    return values


def derive_assurance_plan(
    *,
    task_id: str,
    profile: str,
    contract: Mapping[str, object],
    contract_digest: str,
    repositories: Sequence[object],
    manifest: Mapping[str, object],
    impact: Mapping[str, object],
    previous_plan: Optional[Mapping[str, object]] = None,
) -> dict:
    """Derive the one canonical plan permitted by the closed official policy."""
    if profile not in ("lite", "feature", "bugfix", "investigation", "refactor", "full"):
        raise _error("ASSURANCE_INVALID", "assurance profile is unsupported")
    repository_ids = tuple(item.repository_id for item in repositories)
    criteria = _criterion_ids(contract)
    if impact.get("schema") != IMPACT_MANIFEST_SCHEMA:
        raise _error("ASSURANCE_INVALID", "impact manifest schema is unsupported")
    if manifest.get("schema") != TASK_CHANGE_MANIFEST_SCHEMA:
        raise _error("ASSURANCE_INVALID", "task change manifest is unavailable")
    conservative = impact.get("confidence") != "source-confirmed"
    affected = {
        item.get("repository_id")
        for item in impact.get("entries", ())
        if isinstance(item, Mapping)
    }
    affected.update(
        item.get("repository_id")
        for item in _manifest_entries(manifest)
        if isinstance(item, Mapping)
    )
    affected.intersection_update(repository_ids)
    if conservative or profile == "full":
        required_members = repository_ids
    elif profile == "investigation" and not impact.get("executable_reproduction_required"):
        required_members = ()
    else:
        required_members = tuple(item for item in repository_ids if item in affected)
    all_edges = tuple(item for item in impact.get("edges", ()) if isinstance(item, Mapping))
    required_edges = (
        all_edges
        if conservative or profile == "full"
        else tuple(item for item in all_edges if item.get("affected") is True)
    )
    review_required = bool(
        conservative
        or profile == "full"
        or impact.get("risk_triggers")
    )
    documentation_required = bool(
        profile == "full"
        or impact.get("documentation_required")
        or (profile == "feature" and impact.get("public_behavior"))
    )
    manual_required = bool(
        profile == "investigation" or impact.get("manual_evidence_required")
    )
    allowance = 3 if profile == "full" else 2
    manifest_entries = _manifest_entries(manifest)
    manifest_by_member = {
        repository_id: [
            {
                "repository_id": item.get("repository_id"),
                "path": item.get("path"),
                "entry_digest": hashlib.sha256(
                    canonical_json_bytes(item)
                ).hexdigest(),
                "classification": item.get("classification"),
                "criterion_ids": json_value(item.get("criterion_ids", [])),
            }
            for item in manifest_entries
            if isinstance(item, Mapping) and item.get("repository_id") == repository_id
        ]
        for repository_id in repository_ids
    }
    obligations = []
    for repository_id in required_members:
        evidence_contract = {
            "type": "repository",
            "command_required": True,
            "regression_required": profile == "bugfix",
            "independent": False,
        }
        obligations.append(
            _obligation(
                {
                    "kind": "repository-check",
                    "criterion_ids": list(criteria),
                    "repository_ids": [repository_id],
                    "edges": [],
                    "task_change_slice": manifest_by_member[repository_id],
                    "impact_closure": [
                        json_value(item)
                        for item in impact.get("entries", ())
                        if item.get("repository_id") == repository_id
                    ],
                    "prerequisites": [],
                    "evidence_contract": evidence_contract,
                    "completion_rule": "all declared evidence passes",
                    "invalidation_rule": "slice-or-governing-input-intersection",
                    "reuse_rule": "same-contract-equivalent-obligation-disjoint-delta",
                    "driver": "local-command",
                    "budget_class": "verification",
                    "allowance": allowance,
                    "source_rework": True,
                }
            )
        )
    edge_groups = {}
    for edge in required_edges:
        edge_groups.setdefault(edge["evidence_contract"], []).append(edge)
    for evidence_contract in sorted(edge_groups, key=lambda item: item.encode("utf-8")):
        edges = edge_groups[evidence_contract]
        member_scope = sorted(
            {
                value
                for edge in edges
                for value in (edge["from_repository_id"], edge["to_repository_id"])
            }
        )
        edge_criteria = sorted(
            {criterion for edge in edges for criterion in edge["criterion_ids"]}
        )
        obligations.append(
            _obligation(
                {
                    "kind": "integration-check",
                    "criterion_ids": edge_criteria,
                    "repository_ids": member_scope,
                    "edges": json_value(edges),
                    "task_change_slice": [
                        item
                        for repository_id in member_scope
                        for item in manifest_by_member[repository_id]
                    ],
                    "impact_closure": json_value(edges),
                    "prerequisites": [],
                    "evidence_contract": {
                        "type": "integration",
                        "name": evidence_contract,
                        "command_required": True,
                        "regression_required": profile == "bugfix",
                        "independent": False,
                    },
                    "completion_rule": "integration evidence passes",
                    "invalidation_rule": "any-member-or-edge-intersection",
                    "reuse_rule": "same-contract-equivalent-edge-disjoint-delta",
                    "driver": "local-command",
                    "budget_class": "verification",
                    "allowance": allowance,
                    "source_rework": True,
                }
            )
        )
    if documentation_required:
        obligations.append(
            _obligation(
                {
                    "kind": "documentation-check",
                    "criterion_ids": list(criteria),
                    "repository_ids": list(required_members or repository_ids),
                    "edges": [],
                    "task_change_slice": [
                        item for values in manifest_by_member.values() for item in values
                    ],
                    "impact_closure": json_value(impact.get("entries", ())),
                    "prerequisites": [],
                    "evidence_contract": {
                        "type": "documentation",
                        "command_required": False,
                        "regression_required": False,
                        "independent": False,
                    },
                    "completion_rule": "documentation evidence is current",
                    "invalidation_rule": "public-contract-or-documentation-slice-change",
                    "reuse_rule": "same-public-contract-and-disjoint-delta",
                    "driver": "manual-or-local-command",
                    "budget_class": "verification",
                    "allowance": allowance,
                    "source_rework": True,
                }
            )
        )
    if manual_required:
        obligations.append(
            _obligation(
                {
                    "kind": "manual-evidence",
                    "criterion_ids": list(criteria),
                    "repository_ids": list(required_members),
                    "edges": [],
                    "task_change_slice": [
                        item for values in manifest_by_member.values() for item in values
                    ],
                    "impact_closure": json_value(impact.get("entries", ())),
                    "prerequisites": [],
                    "evidence_contract": {
                        "type": "manual",
                        "command_required": False,
                        "regression_required": False,
                        "independent": False,
                    },
                    "completion_rule": "bounded conclusions have evidence",
                    "invalidation_rule": "conclusion-or-governing-input-change",
                    "reuse_rule": "same-conclusion-and-disjoint-delta",
                    "driver": "manual-evidence",
                    "budget_class": "verification",
                    "allowance": allowance,
                    "source_rework": False,
                }
            )
        )
    if review_required:
        obligations.append(
            _obligation(
                {
                    "kind": "independent-review",
                    "criterion_ids": list(criteria),
                    "repository_ids": list(repository_ids),
                    "edges": json_value(required_edges),
                    "task_change_slice": [
                        item for values in manifest_by_member.values() for item in values
                    ],
                    "impact_closure": {
                        "entries": json_value(impact.get("entries", ())),
                        "edges": json_value(required_edges),
                    },
                    "prerequisites": [
                        item["obligation_id"]
                        for item in obligations
                        if item["kind"] != "independent-review"
                    ],
                    "evidence_contract": {
                        "type": "review",
                        "command_required": False,
                        "regression_required": False,
                        "independent": True,
                    },
                    "completion_rule": "controller-derived review outcome is approved",
                    "invalidation_rule": "reviewed-slice-plan-guidance-or-snapshot-change",
                    "reuse_rule": "same-plan-slice-guidance-and-disjoint-delta",
                    "driver": "independent-review",
                    "budget_class": "review",
                    "allowance": allowance,
                    "source_rework": True,
                }
            )
        )
    kind_order = {kind: index for index, kind in enumerate(OBLIGATION_KINDS)}
    obligations.sort(
        key=lambda item: (
            kind_order[item["kind"]],
            tuple(item["repository_ids"]),
            item["fingerprint"],
        )
    )
    if not obligations or len(obligations) > MAX_ASSURANCE_OBLIGATIONS:
        raise _error(
            "ASSURANCE_INVALID",
            "canonical assurance obligations exceed the supported bound",
            obligation_limit=MAX_ASSURANCE_OBLIGATIONS,
        )
    covered_criteria = {
        criterion for item in obligations for criterion in item["criterion_ids"]
    }
    if covered_criteria != set(criteria):
        raise _error("ASSURANCE_INVALID", "assurance plan does not cover every criterion")
    reservation_set = _budget_reservations(
        profile=profile,
        repository_ids=repository_ids,
        edges=all_edges,
        allowance=allowance,
    )
    prerequisite_reservation_set = _prerequisite_reservations(reservation_set)
    verification_count = sum(
        item["budget_class"] == "verification" for item in reservation_set
    )
    review_count = sum(item["budget_class"] == "review" for item in reservation_set)
    retry_units = sum(
        int(item["retry_units"])
        for item in reservation_set
    )
    if profile in ("lite", "investigation"):
        verification_ceiling = min(allowance * verification_count, verification_count + 1)
        review_ceiling = 0 if review_count == 0 else min(allowance * review_count, review_count + 1)
        rework_ceiling = min(1, retry_units)
    elif profile in ("feature", "bugfix", "refactor"):
        verification_ceiling = min(allowance * verification_count, verification_count + 2)
        review_ceiling = 0 if review_count == 0 else min(allowance * review_count, review_count + 1)
        rework_ceiling = min(2, retry_units)
    else:
        verification_ceiling = min(allowance * verification_count, verification_count + 4)
        review_ceiling = min(allowance * review_count, review_count + 2)
        rework_ceiling = min(4, retry_units)
    finding_disposition_reserve = review_ceiling * MAX_REVIEW_FINDINGS
    governance_reserve = (
        len(criteria)
        + len(reservation_set)
        + len(prerequisite_reservation_set)
        + finding_disposition_reserve
    )
    fixed_mutations = 3 if profile in ("lite", "investigation") else 5
    total_action_ceiling = (
        fixed_mutations
        + verification_ceiling
        + review_ceiling
        + rework_ceiling
        + governance_reserve
        + 1
    )
    prior_budgets = None
    if previous_plan is not None:
        prior = validate_assurance_plan(previous_plan)
        if prior["contract_digest"] == contract_digest:
            prior_budgets = json_value(prior["budgets"])
    if prior_budgets is None and total_action_ceiling > MAX_WORKFLOW_ACTIONS:
        raise _error(
            "ASSURANCE_BUDGET_INVALID",
            "assurance route exceeds the product action ceiling",
            total_action_ceiling=total_action_ceiling,
            product_ceiling=MAX_WORKFLOW_ACTIONS,
        )
    budgets = {
        "per_obligation_cap": allowance,
        "verification_ceiling": verification_ceiling,
        "review_ceiling": review_ceiling,
        "rework_ceiling": rework_ceiling,
        "total_action_ceiling": total_action_ceiling,
        "retry_unit_total": retry_units,
        "finding_disposition_reserve": finding_disposition_reserve,
        "reservation_set": reservation_set,
        "prerequisite_reservation_set": prerequisite_reservation_set,
        "used": {
            "verification": 0,
            "review": 0,
            "rework": 0,
            "total_action": 0,
        },
    }
    if prior_budgets is not None:
        budgets = prior_budgets
    uncovered = [
        item["obligation_id"]
        for item in obligations
        if not any(
            _reservation_covers_obligation(reservation, item)
            for reservation in budgets["reservation_set"]
        )
    ]
    required_verification = sum(
        item["budget_class"] == "verification" for item in obligations
    )
    required_review = sum(item["budget_class"] == "review" for item in obligations)
    obligations_by_id = {
        item["obligation_id"]: item for item in obligations
    }
    prerequisite_subjects = {
        item.get("dependent_reservation_id"): set(
            item.get("prerequisite_reservation_ids", ())
        )
        for item in budgets.get("prerequisite_reservation_set", ())
        if isinstance(item, Mapping)
    }
    uncovered_prerequisites = []
    for dependent in obligations:
        if not dependent["prerequisites"]:
            continue
        dependent_reservation = next(
            (
                reservation
                for reservation in budgets["reservation_set"]
                if _reservation_covers_obligation(reservation, dependent)
            ),
            None,
        )
        if (
            dependent_reservation is None
            or dependent_reservation["reservation_id"] not in prerequisite_subjects
        ):
            uncovered_prerequisites.append(dependent["obligation_id"])
            continue
        allowed_prerequisite_reservations = prerequisite_subjects[
            dependent_reservation["reservation_id"]
        ]
        for prerequisite_id in dependent["prerequisites"]:
            prerequisite = obligations_by_id.get(prerequisite_id)
            prerequisite_reservation = next(
                (
                    reservation
                    for reservation in budgets["reservation_set"]
                    if prerequisite is not None
                    and _reservation_covers_obligation(reservation, prerequisite)
                ),
                None,
            )
            if (
                prerequisite_reservation is None
                or prerequisite_reservation["reservation_id"]
                not in allowed_prerequisite_reservations
            ):
                uncovered_prerequisites.append(prerequisite_id)
    if (
        uncovered
        or uncovered_prerequisites
        or required_verification > budgets["verification_ceiling"]
        or required_review > budgets["review_ceiling"]
    ):
        raise _error(
            "ASSURANCE_BUDGET_INVALID",
            "replacement assurance obligations exceed the initial conservative reservation",
            uncovered_obligation_ids=uncovered,
            uncovered_prerequisite_ids=uncovered_prerequisites,
        )
    not_required = {
        "repository_ids": [item for item in repository_ids if item not in required_members],
        "integration": not bool(required_edges),
        "documentation": not documentation_required,
        "manual_evidence": not manual_required,
        "independent_review": not review_required,
        "rule": "closed-policy-profile-impact-and-risk-derivation",
    }
    remaining_actions = budgets["total_action_ceiling"] - budgets["used"]["total_action"]
    if remaining_actions < 0:
        raise _error("ASSURANCE_BUDGET_INVALID", "recorded action use exceeds the ceiling")
    base = {
        "schema": ASSURANCE_PLAN_SCHEMA,
        "policy": POLICY_ID,
        "task_id": task_id,
        "profile": profile,
        "contract_digest": contract_digest,
        "manifest_digest": manifest.get("digest"),
        "impact_digest": impact.get("digest"),
        "confidence": impact.get("confidence"),
        "obligations": obligations,
        "not_required": not_required,
        "budgets": budgets,
        "maximum_remaining_actions": remaining_actions,
    }
    identity = _digest(_PLAN_DOMAIN, base)
    return {
        **base,
        "plan_id": "plan-{}".format(identity[:16]),
        "digest": identity,
    }


def validate_assurance_plan(value: object) -> dict:
    fields = {
        "schema", "policy", "task_id", "profile", "contract_digest",
        "manifest_digest", "impact_digest", "confidence", "obligations",
        "not_required", "budgets", "maximum_remaining_actions", "plan_id", "digest"
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("ASSURANCE_INVALID", "assurance plan fields are invalid")
    plain = json_value(value)
    digest = plain.pop("digest", None)
    plan_id = plain.pop("plan_id", None)
    expected_digest = _digest(_PLAN_DOMAIN, plain)
    if (
        plain.get("schema") != ASSURANCE_PLAN_SCHEMA
        or plain.get("policy") != POLICY_ID
        or digest != expected_digest
        or plan_id != "plan-{}".format(expected_digest[:16])
    ):
        raise _error("ASSURANCE_INVALID", "assurance plan identity is invalid")
    obligations = plain.get("obligations")
    if not isinstance(obligations, list) or not 1 <= len(obligations) <= MAX_ASSURANCE_OBLIGATIONS:
        raise _error("ASSURANCE_INVALID", "assurance plan obligations are invalid")
    ids = [item.get("obligation_id") for item in obligations if isinstance(item, Mapping)]
    if len(ids) != len(obligations) or len(set(ids)) != len(ids):
        raise _error("ASSURANCE_INVALID", "assurance obligation identities are invalid")
    budgets = plain.get("budgets")
    if (
        not isinstance(budgets, dict)
        or budgets.get("total_action_ceiling", MAX_WORKFLOW_ACTIONS + 1) > MAX_WORKFLOW_ACTIONS
        or plain.get("maximum_remaining_actions")
        != budgets.get("total_action_ceiling") - budgets.get("used", {}).get("total_action", 0)
    ):
        raise _error("ASSURANCE_INVALID", "assurance plan budgets are invalid")
    return {**plain, "plan_id": plan_id, "digest": digest}


def validate_assurance_execution(
    value: object,
    *,
    plan: Mapping[str, object],
    obligation: Mapping[str, object],
) -> dict:
    fields = {
        "schema", "plan_digest", "obligation_id", "obligation_fingerprint",
        "contract_digest", "manifest_digest", "passed", "evidence", "limitations"
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _error("ASSURANCE_EXECUTION_INVALID", "assurance execution fields are invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, (list, tuple)) or len(evidence) > MAX_EVIDENCE_ITEMS:
        raise _error(
            "ASSURANCE_EXECUTION_INVALID",
            "assurance evidence exceeds its product bound",
            evidence_limit=MAX_EVIDENCE_ITEMS,
        )
    normalized_evidence = []
    for item in evidence:
        if not isinstance(item, Mapping) or set(item) != {"kind", "reference", "summary"}:
            raise _error("ASSURANCE_EXECUTION_INVALID", "assurance evidence item is invalid")
        normalized_evidence.append(
            {
                "kind": _text(item.get("kind"), "evidence kind"),
                "reference": _text(item.get("reference"), "evidence reference"),
                "summary": _text(item.get("summary"), "evidence summary"),
            }
        )
    limitations = value.get("limitations")
    if not isinstance(limitations, (list, tuple)):
        raise _error("ASSURANCE_EXECUTION_INVALID", "assurance limitations are invalid")
    base = {
        "schema": ASSURANCE_EXECUTION_SCHEMA,
        "plan_digest": plan.get("digest"),
        "obligation_id": obligation.get("obligation_id"),
        "obligation_fingerprint": obligation.get("fingerprint"),
        "contract_digest": plan.get("contract_digest"),
        "manifest_digest": plan.get("manifest_digest"),
        "passed": value.get("passed"),
        "evidence": normalized_evidence,
        "limitations": [_text(item, "assurance limitation") for item in limitations],
    }
    for field in (
        "schema", "plan_digest", "obligation_id", "obligation_fingerprint",
        "contract_digest", "manifest_digest", "passed"
    ):
        if value.get(field) != base[field]:
            raise _error(
                "ASSURANCE_EXECUTION_INVALID",
                "assurance execution binding is invalid",
                field=field,
            )
    if not isinstance(base["passed"], bool):
        raise _error("ASSURANCE_EXECUTION_INVALID", "assurance pass flag is invalid")
    return {**base, "digest": _digest(_EXECUTION_DOMAIN, base)}


def obligation_states(
    plan: Mapping[str, object],
    executions: Sequence[Mapping[str, object]],
    *,
    waived_obligation_ids: Sequence[str] = (),
    reused_obligation_ids: Sequence[str] = (),
) -> tuple:
    validated = validate_assurance_plan(plan)
    by_obligation = {}
    for execution in executions:
        by_obligation.setdefault(execution.get("obligation_id"), []).append(execution)
    result = []
    for obligation in validated["obligations"]:
        obligation_id = obligation["obligation_id"]
        attempts = by_obligation.get(obligation_id, [])
        prerequisites = obligation["prerequisites"]
        if obligation_id in waived_obligation_ids:
            state = "waived"
        elif obligation_id in reused_obligation_ids:
            state = "reused"
        elif any(item.get("passed") is True for item in attempts):
            state = "satisfied"
        elif len(attempts) >= obligation["allowance"]:
            state = "exhausted"
        elif any(
            next(
                (item["state"] for item in result if item["obligation_id"] == prerequisite),
                "blocked",
            )
            not in ("satisfied", "reused", "waived")
            for prerequisite in prerequisites
        ):
            state = "blocked"
        else:
            state = "outstanding"
        result.append(
            {
                "obligation_id": obligation_id,
                "fingerprint": obligation["fingerprint"],
                "kind": obligation["kind"],
                "state": state,
                "attempts_used": len(attempts),
                "allowance": obligation["allowance"],
                "remaining": max(0, obligation["allowance"] - len(attempts)),
            }
        )
    return tuple(result)


def next_obligation(
    plan: Mapping[str, object],
    executions: Sequence[Mapping[str, object]],
    *,
    waived_obligation_ids: Sequence[str] = (),
    reused_obligation_ids: Sequence[str] = (),
) -> Optional[dict]:
    states = obligation_states(
        plan,
        executions,
        waived_obligation_ids=waived_obligation_ids,
        reused_obligation_ids=reused_obligation_ids,
    )
    state_map = {item["obligation_id"]: item for item in states}
    validated = validate_assurance_plan(plan)
    for obligation in validated["obligations"]:
        if state_map[obligation["obligation_id"]]["state"] == "outstanding":
            return {
                "obligation": obligation,
                "state": state_map[obligation["obligation_id"]],
            }
    return None


def budget_view(
    plan: Mapping[str, object],
    executions: Sequence[Mapping[str, object]],
    *,
    execution_classes: Optional[Mapping[str, str]] = None,
    rework_executions: int = 0,
    governance_mutations: int = 0,
    fixed_mutations: int = 0,
) -> dict:
    validated = validate_assurance_plan(plan)
    obligations = {
        item["obligation_id"]: item for item in validated["obligations"]
    }
    verification = 0
    review = 0
    for execution in executions:
        obligation = obligations.get(execution.get("obligation_id"))
        budget_class = (
            obligation.get("budget_class")
            if obligation is not None
            else None
        )
        if budget_class is None and execution_classes is not None:
            budget_class = execution_classes.get(str(execution.get("digest", "")))
        if budget_class not in ("verification", "review"):
            raise _error("ASSURANCE_BUDGET_INVALID", "execution names an unknown obligation")
        if budget_class == "review":
            review += 1
        else:
            verification += 1
    total = verification + review + rework_executions + governance_mutations + fixed_mutations
    ceilings = validated["budgets"]
    used = {
        "verification": verification,
        "review": review,
        "rework": rework_executions,
        "total_action": total,
    }
    remaining = {
        "verification": ceilings["verification_ceiling"] - verification,
        "review": ceilings["review_ceiling"] - review,
        "rework": ceilings["rework_ceiling"] - rework_executions,
        "total_action": ceilings["total_action_ceiling"] - total,
    }
    if any(value < 0 for value in remaining.values()):
        raise _error("ASSURANCE_BUDGET_EXHAUSTED", "assurance execution exceeds a ceiling")
    return {
        "used": used,
        "remaining": remaining,
        "maximum_remaining_actions": remaining["total_action"],
    }
