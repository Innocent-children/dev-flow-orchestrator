"""Pure shared repository plan, lease, result and barrier kernel."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping, Sequence

from .model import DevFlowError, canonical_json_bytes


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_CONFIRMATION_ID = re.compile(r"^confirm-[0-9a-f]{64}$")
_ATTEMPT_RESULT_SCHEMA = "dev-flow-v4-repository-attempt-result/v1"
_LEASE_FIELDS = frozenset(
    {
        "lease_id",
        "repository_id",
        "owner_id",
        "pinned_head",
        "attempt",
        "status",
    }
)
_ATTEMPT_RESULT_FIELDS = frozenset(
    {
        "schema",
        "repository_id",
        "lease_id",
        "attempt",
        "outcome",
        "result_sha256",
        "actor_id",
        "authority_id",
        "observed_head",
    }
)


def _mutable(value: Mapping[str, object]) -> dict:
    return json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))


def _digest(value: object) -> str:
    return hashlib.sha256(
        b"dev-flow-greenfield-repository-v1\x00"
        + canonical_json_bytes(value)
    ).hexdigest()


def build_plan(
    repository_ids: Sequence[str],
    dependencies: object,
    owner_id: object,
    pinned_heads: object,
    concurrency: object,
    max_retries: object,
) -> dict:
    ordered_ids = tuple(sorted(set(repository_ids), key=lambda item: item.encode("utf-8")))
    if len(ordered_ids) != len(repository_ids):
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "repository IDs must be unique",
        )
    if not isinstance(dependencies, dict) or set(dependencies) != set(ordered_ids):
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "dependency map must cover the exact repository set",
        )
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "repository owner must be a host-confirmed principal",
        )
    if (
        not isinstance(pinned_heads, dict)
        or set(pinned_heads) != set(ordered_ids)
        or any(
            not isinstance(value, str) or not _GIT_OBJECT_ID.fullmatch(value)
            for value in pinned_heads.values()
        )
    ):
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "pinned HEAD map must cover the exact repository set",
        )
    normalized = {}
    for repository_id in ordered_ids:
        values = dependencies.get(repository_id)
        if not isinstance(values, list):
            raise DevFlowError(
                "REPOSITORY_PLAN_INVALID",
                "repository dependencies must be arrays",
            )
        items = tuple(sorted(set(values), key=lambda item: str(item).encode("utf-8")))
        if (
            any(not isinstance(item, str) for item in items)
            or repository_id in items
            or not set(items).issubset(ordered_ids)
        ):
            raise DevFlowError(
                "REPOSITORY_PLAN_INVALID",
                "repository dependency is invalid",
                details={"repository_id": repository_id},
            )
        normalized[repository_id] = list(items)
    visiting = set()
    visited = set()

    def visit(repository_id: str) -> None:
        if repository_id in visiting:
            raise DevFlowError(
                "REPOSITORY_PLAN_CYCLE",
                "repository dependency graph contains a cycle",
            )
        if repository_id in visited:
            return
        visiting.add(repository_id)
        for dependency in normalized[repository_id]:
            visit(dependency)
        visiting.remove(repository_id)
        visited.add(repository_id)

    for repository_id in ordered_ids:
        visit(repository_id)
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or concurrency < 1
        or concurrency > len(ordered_ids)
    ):
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "concurrency must be between one and repository count",
        )
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or max_retries < 0
        or max_retries > 3
    ):
        raise DevFlowError(
            "REPOSITORY_PLAN_INVALID",
            "max_retries must be between zero and three",
        )
    identity_input = {
        "repository_ids": list(ordered_ids),
        "dependencies": normalized,
        "owners": {
            repository_id: owner_id
            for repository_id in ordered_ids
        },
        "pinned_heads": {
            repository_id: pinned_heads[repository_id]
            for repository_id in ordered_ids
        },
        "concurrency": concurrency,
        "max_retries": max_retries,
    }
    return {
        "schema": "dev-flow-v4-repository-plan/v1",
        "plan_id": _digest(identity_input),
        **identity_input,
        "attempts": {repository_id: 0 for repository_id in ordered_ids},
        "leases": {},
        "attempt_results": {},
        "results": {},
        "barrier": {"status": "OPEN", "members": list(ordered_ids)},
        "integration": None,
        "status": "PLANNED",
    }


def _accepted(plan: Mapping[str, object]) -> set:
    results = plan.get("results")
    if not isinstance(results, Mapping):
        raise DevFlowError("REPOSITORY_STATE_INVALID", "repository results are invalid")
    return {
        repository_id
        for repository_id, result in results.items()
        if isinstance(result, Mapping) and result.get("outcome") == "PASS"
    }


def issue_ready_leases(plan_value: Mapping[str, object]) -> dict:
    plan = _mutable(plan_value)
    if plan.get("status") not in {"PLANNED", "RUNNING"}:
        raise DevFlowError(
            "REPOSITORY_DISPATCH_INVALID",
            "repository plan is not dispatchable",
        )
    repository_ids = plan["repository_ids"]
    dependencies = plan["dependencies"]
    leases = plan["leases"]
    attempts = plan["attempts"]
    accepted = _accepted(plan)
    active = {
        lease["repository_id"]
        for lease in leases.values()
        if lease.get("status") == "ACTIVE"
    }
    available = int(plan["concurrency"]) - len(active)
    for repository_id in repository_ids:
        if available <= 0:
            break
        if repository_id in accepted or repository_id in active:
            continue
        if not set(dependencies[repository_id]).issubset(accepted):
            continue
        attempt = int(attempts[repository_id]) + 1
        attempts[repository_id] = attempt
        lease_id = _digest(
            {
                "plan_id": plan["plan_id"],
                "repository_id": repository_id,
                "attempt": attempt,
            }
        )
        leases[lease_id] = {
            "lease_id": lease_id,
            "repository_id": repository_id,
            "owner_id": plan["owners"][repository_id],
            "pinned_head": plan["pinned_heads"][repository_id],
            "attempt": attempt,
            "status": "ACTIVE",
        }
        active.add(repository_id)
        available -= 1
    plan["status"] = "RUNNING"
    return plan


def accept_result(
    plan_value: Mapping[str, object],
    *,
    repository_id: object,
    lease_id: object,
    outcome: object,
    result_sha256: object,
    actor_id: object,
    authority_id: object,
    observed_head: object,
) -> dict:
    plan = _mutable(plan_value)
    if (
        not isinstance(repository_id, str)
        or repository_id not in plan["repository_ids"]
        or not isinstance(lease_id, str)
        or lease_id not in plan["leases"]
        or outcome not in {"PASS", "FAIL"}
        or not isinstance(result_sha256, str)
        or not _SHA256.fullmatch(result_sha256)
        or not isinstance(actor_id, str)
        or not isinstance(authority_id, str)
        or not isinstance(observed_head, str)
        or not _GIT_OBJECT_ID.fullmatch(observed_head)
    ):
        raise DevFlowError(
            "REPOSITORY_RESULT_INVALID",
            "repository result binding is invalid",
        )
    lease = plan["leases"][lease_id]
    if lease.get("repository_id") != repository_id:
        raise DevFlowError(
            "REPOSITORY_LEASE_INVALID",
            "repository lease does not own this repository",
        )
    if lease.get("owner_id") != actor_id:
        raise DevFlowError(
            "REPOSITORY_OWNER_MISMATCH",
            "repository result actor does not own the lease",
        )
    if lease.get("pinned_head") != observed_head:
        raise DevFlowError(
            "REPOSITORY_DRIFT",
            "repository HEAD drifted from the lease binding",
        )
    prior = plan["results"].get(repository_id)
    result = {
        "schema": _ATTEMPT_RESULT_SCHEMA,
        "repository_id": repository_id,
        "lease_id": lease_id,
        "attempt": lease["attempt"],
        "outcome": outcome,
        "result_sha256": result_sha256,
        "actor_id": actor_id,
        "authority_id": authority_id,
        "observed_head": observed_head,
    }
    attempt_results = plan.get("attempt_results")
    if not isinstance(attempt_results, dict):
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "repository attempt results are invalid",
        )
    prior_attempt = attempt_results.get(lease_id)
    if prior_attempt is not None:
        if prior_attempt == result:
            return plan
        raise DevFlowError(
            "REPOSITORY_RESULT_CONFLICT",
            "repository attempt already has different accepted evidence",
        )
    if prior is not None:
        if prior == result:
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "terminal repository result lacks matching attempt evidence",
            )
        raise DevFlowError(
            "REPOSITORY_RESULT_CONFLICT",
            "repository already has a different accepted result",
        )
    if lease.get("status") != "ACTIVE":
        raise DevFlowError(
            "REPOSITORY_LEASE_INVALID",
            "repository lease is not current and active",
        )
    lease["status"] = "SETTLED"
    attempt_results[lease_id] = result
    if outcome == "PASS":
        plan["results"][repository_id] = result
    elif int(lease["attempt"]) > int(plan["max_retries"]):
        plan["status"] = "BLOCKED"
        plan["results"][repository_id] = result
        return plan
    plan = issue_ready_leases(plan)
    if _accepted(plan) == set(plan["repository_ids"]):
        plan["barrier"]["status"] = "READY"
        plan["status"] = "BARRIER_READY"
    return plan


def authority_evidence_ids(plan_value: Mapping[str, object]) -> set:
    """Return accepted-attempt authority IDs after exact structural validation."""

    if (
        not isinstance(plan_value, Mapping)
        or plan_value.get("schema") != "dev-flow-v4-repository-plan/v1"
    ):
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "repository authority evidence requires a current plan schema",
        )
    repository_ids = plan_value.get("repository_ids")
    if (
        not isinstance(repository_ids, (list, tuple))
        or any(not isinstance(item, str) for item in repository_ids)
        or len(set(repository_ids)) != len(repository_ids)
    ):
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "repository authority evidence has an invalid repository set",
        )
    repositories = set(repository_ids)
    plan_id = plan_value.get("plan_id")
    owners = plan_value.get("owners")
    pinned_heads = plan_value.get("pinned_heads")
    attempts = plan_value.get("attempts")
    leases = plan_value.get("leases")
    attempt_results = plan_value.get("attempt_results")
    results = plan_value.get("results")
    max_retries = plan_value.get("max_retries")
    if (
        not isinstance(plan_id, str)
        or not _SHA256.fullmatch(plan_id)
        or not isinstance(owners, Mapping)
        or set(owners) != repositories
        or not isinstance(pinned_heads, Mapping)
        or set(pinned_heads) != repositories
        or not isinstance(attempts, Mapping)
        or set(attempts) != repositories
        or not isinstance(leases, Mapping)
        or not isinstance(attempt_results, Mapping)
        or not isinstance(results, Mapping)
        or isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or max_retries < 0
        or max_retries > 3
    ):
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "repository authority evidence containers are invalid",
        )
    for repository_id in repository_ids:
        attempt = attempts[repository_id]
        if (
            not isinstance(owners[repository_id], str)
            or not owners[repository_id].strip()
            or not isinstance(pinned_heads[repository_id], str)
            or not _GIT_OBJECT_ID.fullmatch(pinned_heads[repository_id])
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 0
            or attempt > max_retries + 1
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "repository authority evidence bindings are invalid",
                details={"repository_id": repository_id},
            )

    lease_attempts = {}
    settled_leases = set()
    for lease_id, lease in leases.items():
        if (
            not isinstance(lease_id, str)
            or not _SHA256.fullmatch(lease_id)
            or not isinstance(lease, Mapping)
            or set(lease) != _LEASE_FIELDS
            or lease.get("lease_id") != lease_id
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "repository authority evidence has an invalid lease key",
            )
        repository_id = lease.get("repository_id")
        attempt = lease.get("attempt")
        status = lease.get("status")
        if (
            not isinstance(repository_id, str)
            or repository_id not in repositories
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt < 1
            or attempt > max_retries + 1
            or lease.get("owner_id") != owners[repository_id]
            or lease.get("pinned_head") != pinned_heads[repository_id]
            or status not in {"ACTIVE", "SETTLED", "REVOKED"}
            or lease_id
            != _digest(
                {
                    "plan_id": plan_id,
                    "repository_id": repository_id,
                    "attempt": attempt,
                }
            )
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "repository authority evidence lease binding is invalid",
                details={"lease_id": lease_id},
            )
        pair = (repository_id, attempt)
        if pair in lease_attempts:
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "repository authority evidence has duplicate lease attempts",
                details={
                    "repository_id": repository_id,
                    "attempt": attempt,
                },
            )
        lease_attempts[pair] = lease_id
        if status == "SETTLED":
            settled_leases.add(lease_id)
    for repository_id in repository_ids:
        observed_attempts = {
            attempt
            for candidate, attempt in lease_attempts
            if candidate == repository_id
        }
        expected_attempts = set(
            range(1, attempts[repository_id] + 1)
        )
        if observed_attempts != expected_attempts:
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "repository authority evidence attempts are not contiguous",
                details={"repository_id": repository_id},
            )
    if set(attempt_results) != settled_leases:
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "settled leases and accepted attempt evidence do not match",
        )

    authorities = set()
    seen_pairs = set()
    terminal_by_repository = {}
    for lease_id, record in attempt_results.items():
        lease = leases.get(lease_id)
        if (
            not isinstance(record, Mapping)
            or set(record) != _ATTEMPT_RESULT_FIELDS
            or record.get("schema") != _ATTEMPT_RESULT_SCHEMA
            or record.get("lease_id") != lease_id
            or not isinstance(lease, Mapping)
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "accepted repository attempt evidence is invalid",
                details={"lease_id": lease_id},
            )
        repository_id = record.get("repository_id")
        attempt = record.get("attempt")
        authority_id = record.get("authority_id")
        result_sha256 = record.get("result_sha256")
        if (
            not isinstance(repository_id, str)
            or repository_id not in repositories
            or repository_id != lease.get("repository_id")
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or attempt != lease.get("attempt")
            or record.get("actor_id") != lease.get("owner_id")
            or record.get("observed_head") != lease.get("pinned_head")
            or record.get("outcome") not in {"PASS", "FAIL"}
            or not isinstance(result_sha256, str)
            or not _SHA256.fullmatch(result_sha256)
            or not isinstance(authority_id, str)
            or not _CONFIRMATION_ID.fullmatch(authority_id)
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "accepted repository attempt binding is invalid",
                details={"lease_id": lease_id},
            )
        pair = (repository_id, attempt)
        if pair in seen_pairs or authority_id in authorities:
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "accepted repository attempt evidence is not unique",
                details={
                    "repository_id": repository_id,
                    "attempt": attempt,
                },
            )
        seen_pairs.add(pair)
        authorities.add(authority_id)
        is_terminal = record.get("outcome") == "PASS" or (
            record.get("outcome") == "FAIL"
            and attempt > max_retries
        )
        if is_terminal:
            if repository_id in terminal_by_repository:
                raise DevFlowError(
                    "REPOSITORY_STATE_INVALID",
                    "repository has multiple terminal attempt results",
                    details={"repository_id": repository_id},
                )
            terminal_by_repository[repository_id] = record

    if set(results) != set(terminal_by_repository):
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "terminal repository results do not match accepted attempts",
        )
    for repository_id, result in results.items():
        if (
            not isinstance(repository_id, str)
            or not isinstance(result, Mapping)
            or dict(result) != dict(terminal_by_repository[repository_id])
        ):
            raise DevFlowError(
                "REPOSITORY_STATE_INVALID",
                "terminal repository result does not match attempt evidence",
                details={"repository_id": repository_id},
            )
    return authorities


def close_barrier(plan_value: Mapping[str, object]) -> dict:
    plan = _mutable(plan_value)
    if (
        plan.get("status") != "BARRIER_READY"
        or plan.get("barrier", {}).get("status") != "READY"
    ):
        raise DevFlowError(
            "REPOSITORY_BARRIER_NOT_READY",
            "repository barrier is not ready to close",
        )
    plan["barrier"]["status"] = "CLOSED"
    plan["barrier"]["result_sha256"] = _digest(plan["results"])
    plan["status"] = "BARRIER_CLOSED"
    return plan


def record_integration(
    plan_value: Mapping[str, object],
    integration_sha256: object,
) -> dict:
    plan = _mutable(plan_value)
    if (
        plan.get("status") != "BARRIER_CLOSED"
        or not isinstance(integration_sha256, str)
        or not _SHA256.fullmatch(integration_sha256)
    ):
        raise DevFlowError(
            "REPOSITORY_INTEGRATION_INVALID",
            "integration result is not bound to a closed barrier",
        )
    plan["integration"] = {
        "integration_sha256": integration_sha256,
        "barrier_sha256": plan["barrier"]["result_sha256"],
    }
    plan["status"] = "INTEGRATED"
    return plan


def cancel_plan(
    plan_value: Mapping[str, object],
    reason: object,
    *,
    authority_id: object = None,
) -> dict:
    if not isinstance(reason, str) or not reason.strip():
        raise DevFlowError(
            "REPOSITORY_CANCELLATION_INVALID",
            "repository cancellation requires a reason",
        )
    plan = _mutable(plan_value)
    for lease in plan.get("leases", {}).values():
        if lease.get("status") == "ACTIVE":
            lease["status"] = "REVOKED"
    plan["status"] = "CANCELLED"
    plan["cancellation"] = {
        "reason": reason.strip(),
        "authority_id": authority_id,
    }
    return plan
