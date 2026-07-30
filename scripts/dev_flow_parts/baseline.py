# Loaded by scripts/dev_flow.py into its shared module namespace.
# Do not import this implementation fragment directly.
# Responsibility: Baseline, analysis workspace, index, artifact, route, and approval workflows.
from __future__ import annotations

import copy as _baseline_copy
import hmac as _baseline_hmac
import json as _baseline_json
import os as _baseline_os
import re as _baseline_re
import threading as _baseline_threading
from contextlib import contextmanager as _baseline_contextmanager
from dataclasses import dataclass as _baseline_dataclass
from pathlib import Path as _BaselinePath
from types import MappingProxyType as _BaselineMappingProxyType
from typing import Callable as _BaselineCallable
from typing import Mapping as _BaselineMapping


_V3_PURE_COMMAND_EVIDENCE_CONTRACT = (
    "dev-flow-v3-pure-command-evidence/v1"
)


def _v3_pure_command_raise(exc: TransitionEngineError) -> None:
    details = _workflow_transition_public(exc.details)
    raise FlowError(
        exc.code,
        exc.message,
        details=details if isinstance(details, dict) else {},
    ) from exc


def _v3_pure_action_outcome(
    edge: Mapping[str, object],
    *,
    command: str,
    proposed_state_delta: Mapping[str, object],
    evidence: Mapping[str, object],
) -> ActionOutcome:
    """Build a typed side-effect-free result for one exact catalog edge."""

    trigger = edge.get("trigger")
    action_id = (
        trigger.get("id") if isinstance(trigger, Mapping) else None
    )
    edge_id = edge.get("id")
    if (
        not isinstance(action_id, str)
        or not action_id
        or not isinstance(edge_id, str)
        or not edge_id
    ):
        raise FlowError(
            "WORKFLOW_ACTION_EDGE_INVALID",
            "pinned pure command action has no exact identity",
            details={"command": command},
        )
    public_evidence = _copy_state(dict(evidence))
    public_delta = _copy_state(dict(proposed_state_delta))
    binding = {
        "contract": _V3_PURE_COMMAND_EVIDENCE_CONTRACT,
        "command": command,
        "edge_id": edge_id,
        "evidence": public_evidence,
    }
    proposed_state_delta_sha256 = _sha256_contract(public_delta)
    return ActionOutcome(
        action_id,
        edge_id,
        evidence_records=(binding,),
        proposed_state_delta=public_delta,
        audit_facts=(
            AuditFact(
                "pure-command-outcome-accepted",
                {
                    "command": command,
                    "edge_id": edge_id,
                    "evidence_sha256": _sha256_contract(
                        public_evidence
                    ),
                    "proposed_state_delta_sha256": (
                        proposed_state_delta_sha256
                    ),
                },
            ),
        ),
    )


def _v3_pure_approval_outcome(
    edge: Mapping[str, object],
    approval: Mapping[str, object],
) -> ApprovalOutcome:
    gate = edge.get("gate")
    gate_id = gate.get("id") if isinstance(gate, Mapping) else None
    edge_id = edge.get("id")
    if (
        not isinstance(gate_id, str)
        or not gate_id
        or not isinstance(edge_id, str)
        or not edge_id
    ):
        raise FlowError(
            "WORKFLOW_ACTION_APPROVAL_REQUIRED",
            "pinned approval action has no exact gate identity",
            details={"edge_id": edge_id},
        )
    return ApprovalOutcome(
        gate_id,
        edge_id,
        _copy_state(dict(approval)),
        audit_facts=(
            AuditFact(
                "pure-command-approval-built",
                {
                    "edge_id": edge_id,
                    "gate_id": gate_id,
                    "approval_id": approval.get("approval_id"),
                },
            ),
        ),
    )


def _v3_pure_node_action_commit(
    current: dict[str, Any],
    task_dir: Path,
    *,
    public_command: str,
    selector: str | None,
    action_outcome: ActionOutcome,
    approval_outcome: ApprovalOutcome | None = None,
    action_parameters: Mapping[str, object] | None = None,
    evidence: Mapping[str, object] | None = None,
) -> tuple[dict[str, Any], TransitionEvaluation]:
    """Preview, explicitly confirm, and proof-commit one pure node action."""

    try:
        preview = evaluate_v3_node_action(
            current,
            public_command=public_command,
            selector=selector,
            action_outcome=action_outcome,
            approval_outcome=approval_outcome,
            action_parameters=action_parameters,
            evidence=evidence,
            preview=True,
        )
        evaluation = evaluate_v3_node_action(
            current,
            public_command=public_command,
            selector=selector,
            action_outcome=action_outcome,
            approval_outcome=approval_outcome,
            action_parameters=action_parameters,
            evidence=evidence,
            confirm_intent=str(preview.intent["intent_id"]),
        )
        committed = commit_v3_workflow_action(
            current, evaluation, task_dir
        )
    except TransitionEngineError as exc:
        _v3_pure_command_raise(exc)
    return committed, evaluation


def _v3_command_set_route_commit(
    current: dict[str, Any],
    task_dir: Path,
    *,
    route: str,
    reason: str,
    route_record: Mapping[str, object],
    impact: Mapping[str, object],
    impact_metadata: Mapping[str, object],
) -> dict[str, Any]:
    try:
        edge = resolve_v3_node_action_edge(current, "set-route")
    except TransitionEngineError as exc:
        _v3_pure_command_raise(exc)
    outcome = _v3_pure_action_outcome(
        edge,
        command="set-route",
        proposed_state_delta={
            "set": {"/route": dict(route_record)},
            "remove": [],
            "operations": [],
        },
        evidence={
            "route": route,
            "reason": reason,
            "impact_artifact_id": impact["artifact_id"],
            "impact_sha256": impact["sha256"],
            "impact_generation": impact_metadata[
                "impact_generation"
            ],
        },
    )
    state_value, _evaluation = _v3_pure_node_action_commit(
        current,
        task_dir,
        public_command="set-route",
        selector=None,
        action_outcome=outcome,
        action_parameters={"route": route, "reason": reason},
        evidence={
            "impact_artifact_id": impact["artifact_id"],
            "impact_sha256": impact["sha256"],
        },
    )
    return state_value


def _v3_command_approve_commit(
    current: dict[str, Any],
    task_dir: Path,
    args: argparse.Namespace,
    approval: Mapping[str, object],
    artifact_sha: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        edge = resolve_v3_node_action_edge(
            current, "approve", selector=args.gate
        )
    except TransitionEngineError as exc:
        _v3_pure_command_raise(exc)
    action_parameters = {
        "gate": args.gate,
        "note": args.note,
        "artifact_sha256": artifact_sha,
        "accept_conditional": bool(args.accept_conditional),
        "allow_fetch": bool(args.allow_fetch),
        "allow_dirty": bool(args.allow_dirty),
    }
    approval_value = _copy_state(dict(approval))
    approval_value["confirmation_mode"] = "explicit-action"
    evidence = {
        "gate": args.gate,
        "approval_id": approval_value["approval_id"],
        "approval_sha256": _sha256_contract(approval_value),
    }
    pointer = "/approvals/" + args.gate.replace(
        "~", "~0"
    ).replace("/", "~1")
    seed_outcome = _v3_pure_action_outcome(
        edge,
        command="approve",
        proposed_state_delta={
            "set": {pointer: approval_value},
            "remove": [],
            "operations": [],
        },
        evidence=evidence,
    )
    seed_approval = _v3_pure_approval_outcome(
        edge, approval_value
    )
    try:
        preview = evaluate_v3_node_action(
            current,
            public_command="approve",
            selector=args.gate,
            action_outcome=seed_outcome,
            approval_outcome=seed_approval,
            action_parameters=action_parameters,
            evidence=evidence,
            preview=True,
        )
        approval_value.update(
            {
                "intent_id": str(preview.intent["intent_id"]),
            }
        )
        outcome = _v3_pure_action_outcome(
            edge,
            command="approve",
            proposed_state_delta={
                "set": {pointer: approval_value},
                "remove": [],
                "operations": [],
            },
            evidence=evidence,
        )
        approval_outcome = _v3_pure_approval_outcome(
            edge, approval_value
        )
        evaluation = evaluate_v3_node_action(
            current,
            public_command="approve",
            selector=args.gate,
            action_outcome=outcome,
            approval_outcome=approval_outcome,
            action_parameters=action_parameters,
            evidence=evidence,
            confirm_intent=str(preview.intent["intent_id"]),
        )
        state_value = commit_v3_workflow_action(
            current, evaluation, task_dir
        )
    except TransitionEngineError as exc:
        _v3_pure_command_raise(exc)
    return state_value, approval_value


_V3_BASELINE_PLAN_SCHEMA = "dev-flow-v3-baseline-effect-plan/v1"
_V3_BASELINE_OBSERVATION_SCHEMA = (
    "dev-flow-v3-baseline-effect-observation/v1"
)
_V3_BASELINE_RECEIPT_SCHEMA = "dev-flow-v3-baseline-effect-receipt/v1"
_V3_BASELINE_PLAN_DOMAIN = b"dev-flow-v3-baseline-effect-plan-v1\x00"
_V3_BASELINE_OBSERVATION_DOMAIN = (
    b"dev-flow-v3-baseline-effect-observation-v1\x00"
)
_V3_BASELINE_RECEIPT_DOMAIN = (
    b"dev-flow-v3-baseline-effect-receipt-v1\x00"
)
_V3_BASELINE_ACTIONS = frozenset(
    {
        "fetch",
        "materialization",
        "record-index",
        "record-artifact",
    }
)
_V3_BASELINE_SECRET_FIELDS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "credential",
        "manager_secret",
        "password",
        "private_key",
        "secret",
        "token",
    }
)
_v3_baseline_readonly_git_lock = _baseline_threading.RLock()


@_baseline_contextmanager
def _v3_baseline_readonly_git():
    """Prevent evidence commands from refreshing Git's mutable index cache."""

    with _v3_baseline_readonly_git_lock:
        marker = object()
        previous = _baseline_os.environ.get(
            "GIT_OPTIONAL_LOCKS", marker
        )
        _baseline_os.environ["GIT_OPTIONAL_LOCKS"] = "0"
        try:
            yield
        finally:
            if previous is marker:
                _baseline_os.environ.pop("GIT_OPTIONAL_LOCKS", None)
            else:
                _baseline_os.environ["GIT_OPTIONAL_LOCKS"] = str(
                    previous
                )


def _v3_baseline_error(
    code: str,
    message: str,
    *,
    details: _BaselineMapping[str, object] | None = None,
) -> FlowError:
    return FlowError(code, message, details=dict(details or {}))


def _v3_baseline_semantic_value(
    value: object,
    *,
    pointer: str = "",
) -> object:
    """Delegate strict canonicalization to the action-journal contract."""

    def _plain(item: object) -> object:
        if isinstance(item, _BaselineMapping):
            return {key: _plain(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [_plain(nested) for nested in item]
        return item

    plain = _plain(value)
    try:
        # Round-trip only to obtain a caller-independent builtin graph.
        # Validation, NFC/int64 policy, ordering and bytes all come from the
        # already-loaded journal canonicalizer.
        return _baseline_json.loads(semantic_json_bytes(plain))
    except Exception as exc:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_SEMANTIC_JSON_INVALID",
            "baseline effect value violates strict semantic JSON",
            details={
                "pointer": pointer or "/",
                "cause_code": getattr(
                    exc, "code", "ACTION_JOURNAL_JSON_INVALID"
                ),
            },
        ) from None


def _v3_baseline_reject_secrets(
    value: object,
    *,
    pointer: str = "",
) -> None:
    if isinstance(value, _BaselineMapping):
        for key, item in value.items():
            folded = str(key).casefold().replace("-", "_")
            if folded in _V3_BASELINE_SECRET_FIELDS or any(
                folded.endswith("_" + secret)
                for secret in _V3_BASELINE_SECRET_FIELDS
            ):
                raise _v3_baseline_error(
                    "BASELINE_EFFECT_SECRET_FORBIDDEN",
                    "effect plans and receipts cannot contain secret fields",
                    details={"pointer": pointer + "/" + str(key)},
                )
            _v3_baseline_reject_secrets(
                item, pointer=pointer + "/" + str(key)
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _v3_baseline_reject_secrets(
                item, pointer=f"{pointer}/{index}"
            )


def _v3_baseline_semantic_bytes(value: object) -> bytes:
    normalized = _v3_baseline_semantic_value(value)
    return semantic_json_bytes(normalized)


def _v3_baseline_semantic_sha256(
    domain: bytes, value: object
) -> str:
    normalized = _v3_baseline_semantic_value(value)
    return semantic_sha256(domain, normalized)


def _v3_baseline_freeze(value: object) -> object:
    normalized = _v3_baseline_semantic_value(value)
    if isinstance(normalized, dict):
        return _BaselineMappingProxyType(
            {
                key: _v3_baseline_freeze(item)
                for key, item in normalized.items()
            }
        )
    if isinstance(normalized, list):
        return tuple(_v3_baseline_freeze(item) for item in normalized)
    return normalized


def _v3_baseline_thaw(value: object) -> object:
    if isinstance(value, _BaselineMapping):
        return {
            str(key): _v3_baseline_thaw(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_v3_baseline_thaw(item) for item in value]
    return _baseline_copy.deepcopy(value)


def _v3_baseline_require_text(value: object, role: str) -> str:
    if not isinstance(value, str) or not value:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_BINDING_INVALID",
            f"{role} must be non-empty text",
        )
    _v3_baseline_semantic_value(value, pointer="/" + role)
    return value


def _v3_baseline_require_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_BINDING_INVALID",
            "task revision must be a non-negative integer",
        )
    return value


def _v3_baseline_canonical_path(
    value: str | _BaselinePath,
    *,
    must_exist: bool,
) -> str:
    try:
        path = _BaselinePath(value).expanduser().resolve(
            strict=must_exist
        )
    except (OSError, RuntimeError) as exc:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PATH_INVALID",
            "effect path cannot be resolved canonically",
            details={"path": str(value)},
        ) from exc
    return str(path)


def _v3_baseline_plan_core(
    action: str,
    task_id: str,
    task_revision: int,
    repository_id: str,
    bindings: _BaselineMapping[str, object],
) -> dict[str, object]:
    return {
        "schema": _V3_BASELINE_PLAN_SCHEMA,
        "action": action,
        "task_id": task_id,
        "task_revision": task_revision,
        "repository_id": repository_id,
        "bindings": dict(bindings),
    }


@_baseline_dataclass(frozen=True)
class V3BaselineEffectPlan:
    """Immutable semantic plan. Construct plans only through the builders."""

    action: str
    task_id: str
    task_revision: int
    repository_id: str
    bindings: _BaselineMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        if self.action not in _V3_BASELINE_ACTIONS:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_ACTION_INVALID",
                "unsupported baseline effect action",
                details={"action": self.action},
            )
        expected_type = {
            "fetch": "V3BaselineFetchPlan",
            "materialization": "V3BaselineMaterializationPlan",
            "record-index": "V3RecordIndexPlan",
            "record-artifact": "V3RecordArtifactPlan",
        }[self.action]
        if type(self).__name__ != expected_type:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_PLAN_TYPE_INVALID",
                "typed plan class does not match its action",
                details={
                    "action": self.action,
                    "expected_type": expected_type,
                    "actual_type": type(self).__name__,
                },
            )
        _v3_baseline_require_text(self.task_id, "task_id")
        _v3_baseline_require_revision(self.task_revision)
        _v3_baseline_require_text(
            self.repository_id, "repository_id"
        )
        public_bindings = _v3_baseline_semantic_value(
            dict(self.bindings), pointer="/bindings"
        )
        assert isinstance(public_bindings, dict)
        _v3_baseline_reject_secrets(public_bindings)
        core = _v3_baseline_plan_core(
            self.action,
            self.task_id,
            self.task_revision,
            self.repository_id,
            public_bindings,
        )
        expected = _v3_baseline_semantic_sha256(
            _V3_BASELINE_PLAN_DOMAIN, core
        )
        if self.semantic_sha256 != expected:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_PLAN_DIGEST_MISMATCH",
                "effect plan digest does not match its semantic bindings",
            )
        object.__setattr__(
            self, "bindings", _v3_baseline_freeze(public_bindings)
        )

    def as_dict(self) -> dict[str, object]:
        core = _v3_baseline_plan_core(
            self.action,
            self.task_id,
            self.task_revision,
            self.repository_id,
            _v3_baseline_thaw(self.bindings),
        )
        core["semantic_sha256"] = self.semantic_sha256
        return core


@_baseline_dataclass(frozen=True)
class V3BaselineFetchPlan(V3BaselineEffectPlan):
    pass


@_baseline_dataclass(frozen=True)
class V3BaselineMaterializationPlan(V3BaselineEffectPlan):
    pass


@_baseline_dataclass(frozen=True)
class V3RecordIndexPlan(V3BaselineEffectPlan):
    pass


@_baseline_dataclass(frozen=True)
class V3RecordArtifactPlan(V3BaselineEffectPlan):
    pass


_V3_BASELINE_PLAN_TYPES = {
    "fetch": V3BaselineFetchPlan,
    "materialization": V3BaselineMaterializationPlan,
    "record-index": V3RecordIndexPlan,
    "record-artifact": V3RecordArtifactPlan,
}


def _v3_baseline_build_plan(
    action: str,
    *,
    task_id: str,
    task_revision: int,
    repository_id: str,
    bindings: _BaselineMapping[str, object],
) -> V3BaselineEffectPlan:
    task_value = _v3_baseline_require_text(task_id, "task_id")
    revision_value = _v3_baseline_require_revision(task_revision)
    repository_value = _v3_baseline_require_text(
        repository_id, "repository_id"
    )
    public_bindings = _v3_baseline_semantic_value(
        dict(bindings), pointer="/bindings"
    )
    assert isinstance(public_bindings, dict)
    _v3_baseline_reject_secrets(public_bindings)
    core = _v3_baseline_plan_core(
        action,
        task_value,
        revision_value,
        repository_value,
        public_bindings,
    )
    digest = _v3_baseline_semantic_sha256(
        _V3_BASELINE_PLAN_DOMAIN, core
    )
    plan_type = _V3_BASELINE_PLAN_TYPES[action]
    return plan_type(
        action,
        task_value,
        revision_value,
        repository_value,
        public_bindings,
        digest,
    )


def plan_v3_baseline_fetch(
    *,
    task_id: str,
    task_revision: int,
    repository_id: str,
    repository_path: str | _BaselinePath,
    remote: str,
    remote_url: str,
    remote_url_sha256: str,
    refspec: str,
    source_ref: str,
    pre_head_sha: str,
    pre_ref_sha: str | None,
) -> V3BaselineFetchPlan:
    """Pure/read-only fetch planning bound to exact pre-effect Git facts."""

    path = _v3_baseline_canonical_path(
        repository_path, must_exist=True
    )
    actual_head = _git(_BaselinePath(path), "rev-parse", "HEAD")
    if actual_head != pre_head_sha:
        raise _v3_baseline_error(
            "BASELINE_FETCH_PRECONDITION_MISMATCH",
            "fetch plan pre-HEAD differs from the repository",
            details={
                "expected_pre_head_sha": pre_head_sha,
                "actual_pre_head_sha": actual_head,
            },
        )
    if (
        _redact_sensitive_text(remote_url) != remote_url
        or not _baseline_re.fullmatch(r"[0-9a-f]{64}", remote_url_sha256)
    ):
        raise _v3_baseline_error(
            "BASELINE_FETCH_REMOTE_BINDING_INVALID",
            "fetch plans require a redacted remote URL and lowercase SHA-256",
        )
    live_url = _remote_url(_BaselinePath(path), remote)
    live_digest = _sensitive_value_sha256(live_url)
    if (
        not isinstance(live_url, str)
        or not isinstance(live_digest, str)
        or not _baseline_hmac.compare_digest(
            live_digest, remote_url_sha256
        )
        or _redact_sensitive_text(live_url) != remote_url
    ):
        raise _v3_baseline_error(
            "BASELINE_FETCH_REMOTE_BINDING_MISMATCH",
            "fetch plan does not match the live approved remote",
            details={
                "repository_id": repository_id,
                "remote": remote,
                "recorded_url": remote_url,
                "recorded_url_sha256": remote_url_sha256,
                "actual_url": (
                    _redact_sensitive_text(live_url)
                    if live_url
                    else None
                ),
                "actual_url_sha256": live_digest,
            },
        )
    live_url = None
    plan = _v3_baseline_build_plan(
        "fetch",
        task_id=task_id,
        task_revision=task_revision,
        repository_id=repository_id,
        bindings={
            "repository_path": path,
            "remote": _v3_baseline_require_text(remote, "remote"),
            "remote_url": _v3_baseline_require_text(
                remote_url, "remote_url"
            ),
            "remote_url_sha256": _v3_baseline_require_text(
                remote_url_sha256, "remote_url_sha256"
            ),
            "refspec": _v3_baseline_require_text(
                refspec, "refspec"
            ),
            "source_ref": _v3_baseline_require_text(
                source_ref, "source_ref"
            ),
            "pre_head_sha": _v3_baseline_require_text(
                pre_head_sha, "pre_head_sha"
            ),
            "pre_ref_sha": pre_ref_sha,
        },
    )
    assert isinstance(plan, V3BaselineFetchPlan)
    return plan


def plan_v3_baseline_materialization(
    *,
    task_id: str,
    task_revision: int,
    repository_id: str,
    source_path: str | _BaselinePath,
    destination_path: str | _BaselinePath,
    base_sha: str,
) -> V3BaselineMaterializationPlan:
    """Pure/read-only plan for one repository's detached analysis result."""

    source = _BaselinePath(
        _v3_baseline_canonical_path(source_path, must_exist=True)
    )
    destination = _v3_baseline_canonical_path(
        destination_path, must_exist=False
    )
    resolved_base = _git_optional(
        source, "rev-parse", "--verify", f"{base_sha}^{{commit}}"
    )
    if resolved_base != base_sha:
        raise _v3_baseline_error(
            "BASELINE_MATERIALIZATION_BASE_INVALID",
            "materialization base is not the exact requested commit",
            details={
                "requested_base_sha": base_sha,
                "resolved_base_sha": resolved_base,
            },
        )
    with _v3_baseline_readonly_git():
        source_fingerprint = _fingerprint_repo(source)
    plan = _v3_baseline_build_plan(
        "materialization",
        task_id=task_id,
        task_revision=task_revision,
        repository_id=repository_id,
        bindings={
            "source_path": str(source),
            "source_common_dir": str(_git_common_dir(source)),
            "destination_path": destination,
            "base_sha": base_sha,
            "source_head_sha": _git(source, "rev-parse", "HEAD"),
            "source_fingerprint_sha256": source_fingerprint["sha256"],
            "source_capability_profile_sha256": source_fingerprint[
                "capability_profile_sha256"
            ],
        },
    )
    assert isinstance(plan, V3BaselineMaterializationPlan)
    return plan


def plan_v3_record_index(
    *,
    task_id: str,
    task_revision: int,
    repository_id: str,
    phase: str,
    source_role: str,
    generation: int,
    project_id: str,
    source_path: str | _BaselinePath,
    source_snapshot_sha: str,
    external_receipt: _BaselineMapping[str, object],
) -> V3RecordIndexPlan:
    """Pure index-evidence plan with explicit phase/generation separation."""

    expected_role = {
        "baseline": "baseline",
        "current-generation-workspace": "workspace",
    }
    if phase not in expected_role or expected_role[phase] != source_role:
        raise _v3_baseline_error(
            "INDEX_PHASE_SOURCE_ROLE_MISMATCH",
            "index phase and source role do not identify the same source",
            details={"phase": phase, "source_role": source_role},
        )
    if isinstance(generation, bool) or not isinstance(generation, int):
        raise _v3_baseline_error(
            "INDEX_GENERATION_INVALID",
            "index generation must be an integer",
        )
    if phase == "baseline" and generation != 0:
        raise _v3_baseline_error(
            "INDEX_GENERATION_INVALID",
            "baseline index generation must be zero",
        )
    if phase == "current-generation-workspace" and generation <= 0:
        raise _v3_baseline_error(
            "INDEX_GENERATION_INVALID",
            "workspace index generation must be positive",
        )
    path = _BaselinePath(
        _v3_baseline_canonical_path(source_path, must_exist=True)
    )
    actual_head = _git(path, "rev-parse", "HEAD")
    if actual_head != source_snapshot_sha:
        raise _v3_baseline_error(
            "INDEX_SOURCE_SNAPSHOT_MISMATCH",
            "index source snapshot differs from the current source HEAD",
            details={
                "expected_source_snapshot_sha": source_snapshot_sha,
                "actual_source_snapshot_sha": actual_head,
            },
        )
    source_branch = _git_optional(
        path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    with _v3_baseline_readonly_git():
        status_available, source_status = _status_porcelain(path)
    if not status_available:
        raise _v3_baseline_error(
            "INDEX_SOURCE_OBSERVATION_UNAVAILABLE",
            "index source cleanliness cannot be observed",
        )
    if phase == "baseline" and (
        source_branch is not None or bool(source_status)
    ):
        raise _v3_baseline_error(
            "INDEX_BASELINE_SOURCE_INVALID",
            "baseline index source must be clean and detached",
            details={
                "repository_id": repository_id,
                "branch": source_branch,
                "dirty": bool(source_status),
            },
        )
    public_receipt = _v3_baseline_semantic_value(
        dict(external_receipt), pointer="/external_receipt"
    )
    assert isinstance(public_receipt, dict)
    if not public_receipt:
        raise _v3_baseline_error(
            "INDEX_TYPED_RECEIPT_REQUIRED",
            "external index success requires a non-empty typed receipt",
        )
    _v3_baseline_reject_secrets(public_receipt)
    receipt_mismatches = [
        field
        for field, expected in (
            ("phase", phase),
            ("source_role", source_role),
            ("generation", generation),
            ("repository_id", repository_id),
            ("project_id", project_id),
            ("source_snapshot_sha", source_snapshot_sha),
        )
        if public_receipt.get(field) != expected
    ]
    receipt_schema = public_receipt.get("schema")
    receipt_sha256 = public_receipt.get("receipt_sha256")
    if not isinstance(receipt_schema, str) or not receipt_schema:
        receipt_mismatches.append("schema")
    if not isinstance(receipt_sha256, str) or not _baseline_re.fullmatch(
        r"[0-9a-f]{64}", receipt_sha256
    ):
        receipt_mismatches.append("receipt_sha256")
    if receipt_mismatches:
        raise _v3_baseline_error(
            "INDEX_TYPED_RECEIPT_MISMATCH",
            "external receipt differs from the exact index source binding",
            details={"fields": sorted(set(receipt_mismatches))},
        )
    with _v3_baseline_readonly_git():
        fingerprint = _fingerprint_repo(path)
    plan = _v3_baseline_build_plan(
        "record-index",
        task_id=task_id,
        task_revision=task_revision,
        repository_id=repository_id,
        bindings={
            "phase": phase,
            "source_role": source_role,
            "generation": generation,
            "project_id": _v3_baseline_require_text(
                project_id, "project_id"
            ),
            "source_path": str(path),
            "source_snapshot_sha": source_snapshot_sha,
            "source_branch": source_branch,
            "source_clean": not bool(source_status),
            "source_fingerprint_sha256": fingerprint["sha256"],
            "source_capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
            "external_receipt": public_receipt,
            "evidence_classification": "discovery-evidence",
            "coverage_proof": False,
        },
    )
    assert isinstance(plan, V3RecordIndexPlan)
    return plan


def plan_v3_record_artifact(
    *,
    task_id: str,
    task_revision: int,
    repository_id: str,
    artifact_path: str | _BaselinePath,
    artifact_kind: str,
) -> V3RecordArtifactPlan:
    """Pure artifact plan binding the exact canonical path, kind and hash."""

    path = _BaselinePath(
        _v3_baseline_canonical_path(artifact_path, must_exist=True)
    )
    artifact_hash = _hash_artifact(path)
    plan = _v3_baseline_build_plan(
        "record-artifact",
        task_id=task_id,
        task_revision=task_revision,
        repository_id=repository_id,
        bindings={
            "artifact_path": str(path),
            "artifact_kind": _v3_baseline_require_text(
                artifact_kind, "artifact_kind"
            ),
            "planned_hash": artifact_hash,
        },
    )
    assert isinstance(plan, V3RecordArtifactPlan)
    return plan


@_baseline_dataclass(frozen=True)
class V3BaselineEffectObservation:
    action: str
    plan_sha256: str
    task_id: str
    execution_id: str
    effect_id: str
    claim_id: str
    attempt_id: str
    result: _BaselineMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        public_result = _v3_baseline_semantic_value(
            dict(self.result), pointer="/result"
        )
        assert isinstance(public_result, dict)
        _v3_baseline_reject_secrets(public_result)
        core = {
            "schema": _V3_BASELINE_OBSERVATION_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "effect_id": self.effect_id,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "result": public_result,
        }
        expected = _v3_baseline_semantic_sha256(
            _V3_BASELINE_OBSERVATION_DOMAIN, core
        )
        if expected != self.semantic_sha256:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_OBSERVATION_DIGEST_MISMATCH",
                "dispatch observation digest does not match its bindings",
            )
        object.__setattr__(
            self, "result", _v3_baseline_freeze(public_result)
        )


def v3_baseline_effect_safe_inputs(
    plan: V3BaselineEffectPlan,
) -> dict[str, object]:
    """Return the exact safe-input binding the transaction must journal."""

    if type(plan) not in set(_V3_BASELINE_PLAN_TYPES.values()):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "safe inputs require an exact typed baseline plan",
        )
    return {
        "baseline_plan_schema": _V3_BASELINE_PLAN_SCHEMA,
        "baseline_action": plan.action,
        "baseline_plan_sha256": plan.semantic_sha256,
        "baseline_repository_id": plan.repository_id,
    }


def v3_baseline_effect_scopes(
    plan: V3BaselineEffectPlan,
) -> dict[str, list[str]]:
    """Return the one exact normalized scope set for the typed plan."""

    if type(plan) not in set(_V3_BASELINE_PLAN_TYPES.values()):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "scopes require an exact typed baseline plan",
        )
    bindings = plan.bindings
    if plan.action == "fetch":
        paths = [str(bindings["repository_path"])]
        resources = [
            "git-remote:"
            + plan.repository_id
            + ":"
            + str(bindings["remote"])
        ]
    elif plan.action == "materialization":
        paths = [
            str(bindings["source_path"]),
            str(bindings["destination_path"]),
        ]
        resources = []
    elif plan.action == "record-index":
        paths = [str(bindings["source_path"])]
        resources = ["index-project:" + str(bindings["project_id"])]
    else:
        paths = [str(bindings["artifact_path"])]
        resources = []
    paths = sorted(set(paths), key=lambda item: item.encode("utf-8"))
    resources = sorted(
        set(resources), key=lambda item: item.encode("utf-8")
    )
    return normalize_scopes(
        {
            "repository_ids": [plan.repository_id],
            "paths": paths,
            "external_resources": resources,
            "node_ids": [],
            "worktree_ids": [],
            "lease_ids": [],
        }
    )


def _v3_baseline_validate_transaction_permit(
    plan: V3BaselineEffectPlan,
    permit: object,
) -> ActionDispatchPlan:
    """Accept only the exact process-local plan returned by Transaction."""

    if type(permit) is not WorkflowActionDispatchContext:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_PERMIT_REQUIRED",
            "direct plan dispatch is forbidden without a transaction permit",
        )
    verifier = globals().get(
        "verify_active_v3_workflow_action_dispatch_context"
    )
    if not callable(verifier):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "transaction active-dispatch verifier is unavailable",
        )
    try:
        verifier(permit)
    except Exception as exc:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_PERMIT_INACTIVE",
            "transaction context is forged, copied, replayed, or inactive",
            details={
                "cause_code": getattr(
                    exc,
                    "code",
                    "WORKFLOW_ACTION_TRANSACTION_DISPATCH_INACTIVE",
                )
            },
        ) from None
    transaction_plan = permit.plan
    if type(transaction_plan) is not ActionDispatchPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_PERMIT_REQUIRED",
            "transaction context has no exact first-claim dispatch plan",
        )
    expected_safe_inputs = v3_baseline_effect_safe_inputs(plan)
    mismatches: list[str] = []
    if transaction_plan.task_id != plan.task_id:
        mismatches.append("task_id")
    if transaction_plan.safe_inputs != expected_safe_inputs:
        mismatches.append("safe_inputs")
    if permit.settlement != "synchronous-quiescence":
        mismatches.append("settlement")
    if permit.scopes != v3_baseline_effect_scopes(plan):
        mismatches.append("scopes")
    for field, value in (
        (
            "journal_record_sha256",
            transaction_plan.journal_record_sha256,
        ),
        ("index_record_sha256", transaction_plan.index_record_sha256),
        ("catalog_contract_sha256", permit.catalog_contract_sha256),
    ):
        if not isinstance(value, str) or not _baseline_re.fullmatch(
            r"[0-9a-f]{64}", value
        ):
            mismatches.append(field)
    if mismatches:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_PERMIT_MISMATCH",
            "transaction dispatch permit differs from the immutable plan",
            details={"fields": sorted(mismatches)},
        )
    return transaction_plan


def dispatch_v3_baseline_effect(
    plan: V3BaselineEffectPlan,
    permit: object,
    dispatcher: _BaselineCallable[
        [V3BaselineEffectPlan], _BaselineMapping[str, object] | None
    ],
) -> V3BaselineEffectObservation:
    """Dispatch only through Transaction's just-persisted first-claim plan.

    Baseline never creates, persists, reconstructs, or retries a permit. The
    ActionExecutionStore/Transaction boundary remains the sole durable claim
    authority, including after a lost response.
    """

    if not callable(dispatcher):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_DISPATCH_INVALID",
            "dispatch requires a callable effect implementation",
        )
    transaction_plan = _v3_baseline_validate_transaction_permit(
        plan, permit
    )
    result = dispatcher(plan)
    public_result = _v3_baseline_semantic_value(
        dict(result or {}), pointer="/result"
    )
    assert isinstance(public_result, dict)
    _v3_baseline_reject_secrets(public_result)
    core = {
        "schema": _V3_BASELINE_OBSERVATION_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "task_id": transaction_plan.task_id,
        "execution_id": transaction_plan.execution_id,
        "effect_id": transaction_plan.effect_id,
        "claim_id": transaction_plan.claim_id,
        "attempt_id": transaction_plan.attempt_id,
        "result": public_result,
    }
    return V3BaselineEffectObservation(
        plan.action,
        plan.semantic_sha256,
        transaction_plan.task_id,
        transaction_plan.execution_id,
        transaction_plan.effect_id,
        transaction_plan.claim_id,
        transaction_plan.attempt_id,
        public_result,
        _v3_baseline_semantic_sha256(
            _V3_BASELINE_OBSERVATION_DOMAIN, core
        ),
    )


def dispatch_v3_baseline_fetch(
    plan: V3BaselineFetchPlan,
    permit: object,
) -> V3BaselineEffectObservation:
    """Fetch with a transient URL capability after exact digest revalidation."""

    if type(plan) is not V3BaselineFetchPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "fetch dispatch requires an exact fetch plan",
        )
    _v3_baseline_validate_transaction_permit(plan, permit)

    def _dispatch(
        current_plan: V3BaselineEffectPlan,
    ) -> dict[str, object]:
        bindings = current_plan.bindings
        path = _BaselinePath(str(bindings["repository_path"]))
        remote = str(bindings["remote"])
        # The credential-bearing URL exists only in this stack frame. It is
        # re-read immediately before invocation and never enters a plan,
        # journal safe input, receipt, result, repr, or error detail.
        live_url = _remote_url(path, remote)
        live_digest = _sensitive_value_sha256(live_url)
        expected_digest = str(bindings["remote_url_sha256"])
        if (
            not isinstance(live_url, str)
            or not isinstance(live_digest, str)
            or not _baseline_hmac.compare_digest(
                live_digest, expected_digest
            )
            or _redact_sensitive_text(live_url)
            != bindings["remote_url"]
        ):
            raise _v3_baseline_error(
                "BASELINE_FETCH_REMOTE_BINDING_MISMATCH",
                "live fetch capability differs from the approved remote",
                details={
                    "repository_id": current_plan.repository_id,
                    "remote": remote,
                    "recorded_url": bindings["remote_url"],
                    "recorded_url_sha256": expected_digest,
                    "actual_url": (
                        _redact_sensitive_text(live_url)
                        if live_url
                        else None
                    ),
                    "actual_url_sha256": live_digest,
                },
            )
        try:
            _git_mutating(
                path,
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.gitProxy=",
                "-c",
                "core.askPass=",
                "-c",
                "core.sshCommand=ssh",
                "-c",
                "credential.helper=",
                "-c",
                "maintenance.auto=false",
                "-c",
                "gc.auto=0",
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.file.allow=always",
                "-c",
                "protocol.git.allow=always",
                "-c",
                "protocol.http.allow=always",
                "-c",
                "protocol.https.allow=always",
                "-c",
                "protocol.ssh.allow=always",
                "-c",
                "protocol.ext.allow=never",
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "--no-auto-maintenance",
                "--no-write-commit-graph",
                "--no-prune",
                "--no-prune-tags",
                "--upload-pack=git-upload-pack",
                "--",
                live_url,
                str(bindings["refspec"]),
            )
        except FlowError as exc:
            raise _v3_baseline_error(
                "BASELINE_FETCH_DISPATCH_FAILED",
                "approved fetch invocation failed",
                details={
                    "repository_id": current_plan.repository_id,
                    "remote": remote,
                    "remote_url": bindings["remote_url"],
                    "remote_url_sha256": expected_digest,
                    "cause_code": exc.code,
                },
            ) from None
        finally:
            live_url = None
        return {
            "remote": remote,
            "remote_url": bindings["remote_url"],
            "remote_url_sha256": expected_digest,
            "refspec": bindings["refspec"],
            "pre_head_sha": bindings["pre_head_sha"],
        }

    return dispatch_v3_baseline_effect(plan, permit, _dispatch)


def _v3_baseline_validate_observe_context(
    plan: V3BaselineEffectPlan,
    context: object,
) -> dict[str, object]:
    if type(context) is not WorkflowActionObserveContext:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVE_CONTEXT_REQUIRED",
            "receipt observation requires Transaction's exact observe-only context",
        )
    verifier = globals().get(
        "verify_active_v3_workflow_action_observe_context"
    )
    if not callable(verifier):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_TRANSACTION_AUTHORITY_UNAVAILABLE",
            "transaction observe-only verifier is unavailable",
        )
    try:
        facts = verifier(context)
    except Exception as exc:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVE_CONTEXT_INACTIVE",
            "observe-only context is forged, copied, stale, or inactive",
            details={
                "cause_code": getattr(
                    exc,
                    "code",
                    "WORKFLOW_ACTION_TRANSACTION_ACTIVE_OBSERVE_REQUIRED",
                )
            },
        ) from None
    if not isinstance(facts, dict):
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVE_CONTEXT_MISMATCH",
            "observe-only verifier returned invalid authority facts",
        )
    mismatches = [
        field
        for field, actual, expected in (
            ("task_id", facts.get("task_id"), plan.task_id),
            (
                "safe_inputs",
                facts.get("safe_inputs"),
                v3_baseline_effect_safe_inputs(plan),
            ),
            (
                "scopes",
                facts.get("scopes"),
                v3_baseline_effect_scopes(plan),
            ),
            (
                "settlement",
                facts.get("settlement"),
                "synchronous-quiescence",
            ),
        )
        if actual != expected
    ]
    if mismatches:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVE_CONTEXT_MISMATCH",
            "observe-only context does not bind the immutable effect plan",
            details={"fields": mismatches},
        )
    return facts


def _v3_baseline_verify_dispatch_observation(
    plan: V3BaselineEffectPlan,
    facts: _BaselineMapping[str, object],
    observation: V3BaselineEffectObservation | None,
) -> None:
    if observation is None:
        return
    if type(observation) is not V3BaselineEffectObservation:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVATION_INVALID",
            "receipt observation requires the exact typed dispatch observation",
        )
    mismatches = [
        field
        for field, actual, expected in (
            ("action", observation.action, plan.action),
            (
                "plan_sha256",
                observation.plan_sha256,
                plan.semantic_sha256,
            ),
            ("task_id", observation.task_id, facts["task_id"]),
            (
                "execution_id",
                observation.execution_id,
                facts["execution_id"],
            ),
            ("effect_id", observation.effect_id, facts["effect_id"]),
            ("claim_id", observation.claim_id, facts["claim_id"]),
            ("attempt_id", observation.attempt_id, facts["attempt_id"]),
        )
        if actual != expected
    ]
    if mismatches:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_OBSERVATION_MISMATCH",
            "dispatch observation differs from the durable observe context",
            details={"fields": mismatches},
        )


@_baseline_dataclass(frozen=True)
class V3BaselineEffectReceipt:
    action: str
    plan_sha256: str
    claim_id: str
    attempt_id: str
    journal_record_sha256: str
    index_record_sha256: str
    containment_record_sha256: str
    observe_context_sha256: str
    repository_id: str
    observation: _BaselineMapping[str, object]
    semantic_sha256: str

    def __post_init__(self) -> None:
        expected_type = {
            "fetch": "V3BaselineFetchReceipt",
            "materialization": "V3BaselineMaterializationReceipt",
            "record-index": "V3RecordIndexReceipt",
            "record-artifact": "V3RecordArtifactReceipt",
        }.get(self.action)
        if type(self).__name__ != expected_type:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_RECEIPT_TYPE_INVALID",
                "typed receipt class does not match its action",
            )
        _v3_baseline_require_text(self.claim_id, "claim_id")
        _v3_baseline_require_text(self.attempt_id, "attempt_id")
        for field_name in (
            "journal_record_sha256",
            "index_record_sha256",
            "containment_record_sha256",
            "observe_context_sha256",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or not _baseline_re.fullmatch(
                    r"[0-9a-f]{64}", value
                )
            ):
                raise _v3_baseline_error(
                    "BASELINE_EFFECT_RECEIPT_BINDING_INVALID",
                    f"{field_name} must be lowercase SHA-256",
                )
        public_observation = _v3_baseline_semantic_value(
            dict(self.observation), pointer="/observation"
        )
        assert isinstance(public_observation, dict)
        _v3_baseline_reject_secrets(public_observation)
        core = {
            "schema": _V3_BASELINE_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_id": self.repository_id,
            "observation": public_observation,
        }
        expected = _v3_baseline_semantic_sha256(
            _V3_BASELINE_RECEIPT_DOMAIN, core
        )
        if expected != self.semantic_sha256:
            raise _v3_baseline_error(
                "BASELINE_EFFECT_RECEIPT_DIGEST_MISMATCH",
                "effect receipt digest does not match its bindings",
            )
        object.__setattr__(
            self,
            "observation",
            _v3_baseline_freeze(public_observation),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": _V3_BASELINE_RECEIPT_SCHEMA,
            "action": self.action,
            "plan_sha256": self.plan_sha256,
            "claim_id": self.claim_id,
            "attempt_id": self.attempt_id,
            "journal_record_sha256": self.journal_record_sha256,
            "index_record_sha256": self.index_record_sha256,
            "containment_record_sha256": (
                self.containment_record_sha256
            ),
            "observe_context_sha256": (
                self.observe_context_sha256
            ),
            "repository_id": self.repository_id,
            "observation": _v3_baseline_thaw(self.observation),
            "semantic_sha256": self.semantic_sha256,
        }


@_baseline_dataclass(frozen=True)
class V3BaselineFetchReceipt(V3BaselineEffectReceipt):
    pass


@_baseline_dataclass(frozen=True)
class V3BaselineMaterializationReceipt(V3BaselineEffectReceipt):
    pass


@_baseline_dataclass(frozen=True)
class V3RecordIndexReceipt(V3BaselineEffectReceipt):
    pass


@_baseline_dataclass(frozen=True)
class V3RecordArtifactReceipt(V3BaselineEffectReceipt):
    pass


_V3_BASELINE_RECEIPT_TYPES = {
    "fetch": V3BaselineFetchReceipt,
    "materialization": V3BaselineMaterializationReceipt,
    "record-index": V3RecordIndexReceipt,
    "record-artifact": V3RecordArtifactReceipt,
}


def _v3_baseline_build_receipt(
    plan: V3BaselineEffectPlan,
    facts: _BaselineMapping[str, object],
    observed: _BaselineMapping[str, object],
) -> V3BaselineEffectReceipt:
    public = _v3_baseline_semantic_value(
        dict(observed), pointer="/observation"
    )
    assert isinstance(public, dict)
    core = {
        "schema": _V3_BASELINE_RECEIPT_SCHEMA,
        "action": plan.action,
        "plan_sha256": plan.semantic_sha256,
        "claim_id": facts["claim_id"],
        "attempt_id": facts["attempt_id"],
        "journal_record_sha256": facts[
            "journal_record_sha256"
        ],
        "index_record_sha256": facts["index_record_sha256"],
        "containment_record_sha256": facts[
            "containment_record_sha256"
        ],
        "observe_context_sha256": facts[
            "observe_context_sha256"
        ],
        "repository_id": plan.repository_id,
        "observation": public,
    }
    receipt_type = _V3_BASELINE_RECEIPT_TYPES[plan.action]
    return receipt_type(
        plan.action,
        plan.semantic_sha256,
        str(facts["claim_id"]),
        str(facts["attempt_id"]),
        str(facts["journal_record_sha256"]),
        str(facts["index_record_sha256"]),
        str(facts["containment_record_sha256"]),
        str(facts["observe_context_sha256"]),
        plan.repository_id,
        public,
        _v3_baseline_semantic_sha256(
            _V3_BASELINE_RECEIPT_DOMAIN, core
        ),
    )


def observe_v3_baseline_fetch(
    plan: V3BaselineFetchPlan,
    observe_context: object,
    observation: V3BaselineEffectObservation | None = None,
) -> V3BaselineFetchReceipt:
    """Observe-only fetch receipt; this function cannot invoke fetch."""

    if type(plan) is not V3BaselineFetchPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "fetch observation requires an exact fetch plan",
        )
    facts = _v3_baseline_validate_observe_context(
        plan, observe_context
    )
    _v3_baseline_verify_dispatch_observation(
        plan, facts, observation
    )
    bindings = plan.bindings
    path = _BaselinePath(str(bindings["repository_path"]))
    actual_head = _git(path, "rev-parse", "HEAD")
    if actual_head != bindings["pre_head_sha"]:
        raise _v3_baseline_error(
            "BASELINE_FETCH_POSTCONDITION_MISMATCH",
            "fetch changed or no longer observes the bound checkout HEAD",
        )
    remote = str(bindings["remote"])
    live_url = _remote_url(path, remote)
    live_digest = _sensitive_value_sha256(live_url)
    expected_digest = str(bindings["remote_url_sha256"])
    if (
        not isinstance(live_url, str)
        or not isinstance(live_digest, str)
        or not _baseline_hmac.compare_digest(
            live_digest, expected_digest
        )
        or _redact_sensitive_text(live_url) != bindings["remote_url"]
    ):
        raise _v3_baseline_error(
            "BASELINE_FETCH_POSTCONDITION_MISMATCH",
            "fetch remote binding differs from the immutable plan",
            details={
                "recorded_url": bindings["remote_url"],
                "recorded_url_sha256": expected_digest,
                "actual_url": (
                    _redact_sensitive_text(live_url)
                    if live_url
                    else None
                ),
                "actual_url_sha256": live_digest,
            },
        )
    post_ref_sha = _git_optional(
        path,
        "rev-parse",
        "--verify",
        f"{bindings['source_ref']}^{{commit}}",
    )
    if not post_ref_sha:
        raise _v3_baseline_error(
            "BASELINE_FETCH_POSTCONDITION_MISMATCH",
            "fetch did not leave the planned source ref observable",
        )
    receipt = _v3_baseline_build_receipt(
        plan,
        facts,
        {
            "repository_path": str(path),
            "remote": remote,
            "remote_url": bindings["remote_url"],
            "remote_url_sha256": expected_digest,
            "refspec": bindings["refspec"],
            "source_ref": bindings["source_ref"],
            "pre_head_sha": bindings["pre_head_sha"],
            "post_head_sha": actual_head,
            "pre_ref_sha": bindings["pre_ref_sha"],
            "post_ref_sha": post_ref_sha,
        },
    )
    live_url = None
    assert isinstance(receipt, V3BaselineFetchReceipt)
    return receipt


def observe_v3_baseline_materialization(
    plan: V3BaselineMaterializationPlan,
    observe_context: object,
    observation: V3BaselineEffectObservation | None = None,
) -> V3BaselineMaterializationReceipt:
    """Re-observe the exact clean detached result for one repository."""

    if type(plan) is not V3BaselineMaterializationPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "materialization observation requires its exact typed plan",
        )
    facts = _v3_baseline_validate_observe_context(
        plan, observe_context
    )
    _v3_baseline_verify_dispatch_observation(
        plan, facts, observation
    )
    bindings = plan.bindings
    source = _BaselinePath(str(bindings["source_path"]))
    destination = _BaselinePath(str(bindings["destination_path"]))
    if not destination.is_dir():
        raise _v3_baseline_error(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            "materialized destination does not exist",
            details={"path": str(destination)},
        )
    head = _git_optional(destination, "rev-parse", "HEAD")
    branch = _git_optional(
        destination,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
    )
    with _v3_baseline_readonly_git():
        status_available, status_porcelain = _status_porcelain(
            destination
        )
    try:
        common_dir_matches = _same_path(
            _git_common_dir(destination),
            _BaselinePath(str(bindings["source_common_dir"])),
        )
        linked = _is_linked_worktree(destination)
    except (FlowError, OSError):
        common_dir_matches = False
        linked = False
    if (
        head != bindings["base_sha"]
        or branch is not None
        or not status_available
        or bool(status_porcelain)
        or not common_dir_matches
        or not linked
    ):
        raise _v3_baseline_error(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            "materialized result is not the exact clean detached worktree",
            details={
                "expected_head": bindings["base_sha"],
                "actual_head": head,
                "actual_branch": branch,
                "dirty": bool(status_porcelain),
            },
        )
    with _v3_baseline_readonly_git():
        source_fingerprint = _fingerprint_repo(source)
    if (
        source_fingerprint["sha256"]
        != bindings["source_fingerprint_sha256"]
        or source_fingerprint["capability_profile_sha256"]
        != bindings["source_capability_profile_sha256"]
    ):
        raise _v3_baseline_error(
            "SOURCE_WORKTREE_CHANGED",
            "source checkout changed after materialization planning",
        )
    with _v3_baseline_readonly_git():
        fingerprint = _fingerprint_repo(destination)
    receipt = _v3_baseline_build_receipt(
        plan,
        facts,
        {
            "source_path": str(source),
            "destination_path": str(destination),
            "source_common_dir": bindings["source_common_dir"],
            "head_sha": head,
            "detached": True,
            "clean": True,
            "fingerprint_sha256": fingerprint["sha256"],
            "capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
        },
    )
    assert isinstance(receipt, V3BaselineMaterializationReceipt)
    return receipt


def observe_v3_record_index(
    plan: V3RecordIndexPlan,
    observe_context: object,
    observation: V3BaselineEffectObservation | None = None,
) -> V3RecordIndexReceipt:
    """Re-observe the source and preserve index evidence as discovery only."""

    if type(plan) is not V3RecordIndexPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "index observation requires an exact record-index plan",
        )
    facts = _v3_baseline_validate_observe_context(
        plan, observe_context
    )
    _v3_baseline_verify_dispatch_observation(
        plan, facts, observation
    )
    bindings = plan.bindings
    path = _BaselinePath(str(bindings["source_path"]))
    head = _git_optional(path, "rev-parse", "HEAD")
    branch = _git_optional(
        path, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    with _v3_baseline_readonly_git():
        status_available, status_porcelain = _status_porcelain(path)
        fingerprint = _fingerprint_repo(path)
    mismatches = []
    if head != bindings["source_snapshot_sha"]:
        mismatches.append("source_snapshot_sha")
    if fingerprint["sha256"] != bindings["source_fingerprint_sha256"]:
        mismatches.append("source_fingerprint_sha256")
    if branch != bindings["source_branch"]:
        mismatches.append("source_branch")
    if (
        not status_available
        or (not bool(status_porcelain)) != bindings["source_clean"]
    ):
        mismatches.append("source_clean")
    if (
        fingerprint["capability_profile_sha256"]
        != bindings["source_capability_profile_sha256"]
    ):
        mismatches.append("source_capability_profile_sha256")
    result = observation.result if observation is not None else {}
    for field in (
        "phase",
        "source_role",
        "generation",
        "project_id",
    ):
        if field in result and result[field] != bindings[field]:
            mismatches.append("external_result." + field)
    if mismatches:
        raise _v3_baseline_error(
            "INDEX_OBSERVATION_MISMATCH",
            "index observation differs from its phase/source binding",
            details={"fields": sorted(mismatches)},
        )
    receipt = _v3_baseline_build_receipt(
        plan,
        facts,
        {
            "phase": bindings["phase"],
            "source_role": bindings["source_role"],
            "generation": bindings["generation"],
            "repository_id": plan.repository_id,
            "project_id": bindings["project_id"],
            "source_path": str(path),
            "source_snapshot_sha": head,
            "source_branch": branch,
            "source_clean": not bool(status_porcelain),
            "source_fingerprint_sha256": fingerprint["sha256"],
            "external_receipt": bindings["external_receipt"],
            "evidence_classification": "discovery-evidence",
            "coverage_proof": False,
        },
    )
    assert isinstance(receipt, V3RecordIndexReceipt)
    return receipt


def observe_v3_record_artifact(
    plan: V3RecordArtifactPlan,
    observe_context: object,
    observation: V3BaselineEffectObservation | None = None,
) -> V3RecordArtifactReceipt:
    """Re-hash the exact path before issuing an artifact receipt."""

    if type(plan) is not V3RecordArtifactPlan:
        raise _v3_baseline_error(
            "BASELINE_EFFECT_PLAN_TYPE_INVALID",
            "artifact observation requires an exact record-artifact plan",
        )
    facts = _v3_baseline_validate_observe_context(
        plan, observe_context
    )
    _v3_baseline_verify_dispatch_observation(
        plan, facts, observation
    )
    bindings = plan.bindings
    path = _BaselinePath(str(bindings["artifact_path"]))
    actual_hash = _hash_artifact(path)
    if actual_hash != _v3_baseline_thaw(bindings["planned_hash"]):
        raise _v3_baseline_error(
            "ARTIFACT_CHANGED",
            "artifact path content changed after immutable planning",
            details={"path": str(path)},
        )
    receipt = _v3_baseline_build_receipt(
        plan,
        facts,
        {
            "artifact_path": str(path),
            "artifact_kind": bindings["artifact_kind"],
            "artifact_hash": actual_hash,
        },
    )
    assert isinstance(receipt, V3RecordArtifactReceipt)
    return receipt


def _git_common_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _git_dir(repo: Path) -> Path:
    raw = Path(_git(repo, "rev-parse", "--git-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve(strict=True)


def _is_linked_worktree(repo: Path) -> bool:
    return _git_dir(repo) != _git_common_dir(repo)


def _status_porcelain(repo: Path) -> tuple[bool, str]:
    try:
        _assert_evidence_supported(repo)
    except FlowError as exc:
        if exc.code == "COMMAND_FAILED":
            return False, ""
        raise
    result = _run(
        _evidence_git_command(
            repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored=matching",
            "--ignore-submodules=none",
            "--no-renames",
        ),
        check=False,
        evidence_git=True,
    )
    if result.returncode != 0:
        return False, result.stdout.strip()
    return True, result.stdout.strip()


def _preflight_remote_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "remote_url_sha256": preflight.get("remote_url_sha256"),
                "base_branch": preflight.get("base_branch"),
                "base_candidate_ref": preflight.get("base_candidate_ref"),
                "base_candidate_sha": preflight.get("base_candidate_sha"),
                "fetch_refspec": preflight.get("fetch_refspec"),
                "head_sha": preflight.get("head_sha"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _preflight_remote_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_preflight_remote_evidence(state_value)))


def _require_baseline_fetch_approval(state_value: dict[str, Any]) -> dict[str, Any]:
    approval = _require_gate(state_value, "baseline-fetch")
    current_evidence_sha = _preflight_remote_evidence_sha256(state_value)
    if approval.get("preflight_remote_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "baseline-fetch approval does not bind the current preflight remote evidence",
            details={
                "expected_preflight_remote_sha256": current_evidence_sha,
                "approved_preflight_remote_sha256": approval.get("preflight_remote_sha256"),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require baseline-fetch approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        _live_approved_remote_url(
            Path(repo["path"]), repo["id"], preflight
        )
        actual_fingerprint = _fingerprint_repo(Path(repo["path"]))["sha256"]
        recorded_fingerprint = preflight.get("worktree_fingerprint_sha256")
        if actual_fingerprint != recorded_fingerprint:
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after preflight approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": recorded_fingerprint,
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _lite_preflight_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    """The exact checkout identity a lite approval authorizes working inside."""

    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight")
        if not isinstance(preflight, dict):
            raise FlowError(
                "PREFLIGHT_REQUIRED",
                f"repository is missing preflight evidence: {repo.get('id')}",
            )
        _require_current_evidence(preflight, f"preflight:{repo.get('id')}")
        repositories.append(
            {
                "evidence_contract_version": preflight.get(
                    "evidence_contract_version"
                ),
                "repository_id": repo["id"],
                "branch": preflight.get("branch"),
                "head_sha": preflight.get("head_sha"),
                "remote": preflight.get("remote"),
                "remote_url": preflight.get("remote_url"),
                "remote_url_sha256": preflight.get("remote_url_sha256"),
                "dirty": bool(preflight.get("dirty")),
                "worktree_fingerprint_sha256": preflight.get(
                    "worktree_fingerprint_sha256"
                ),
                "capability_profile_sha256": preflight.get(
                    "capability_profile_sha256"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _lite_preflight_evidence_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_lite_preflight_evidence(state_value)))


def _require_lite_gate(
    state_value: dict[str, Any],
    *,
    verify_worktree: bool = False,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Require a lite approval bound to the current preflight evidence.

    The approval authorizes in-place work on the exact recorded checkouts, so
    the branch identity is revalidated live at every downstream gate.  The
    worktree fingerprint and ``HEAD`` are only revalidated when entering
    implementation: after that point the edits themselves legitimately change
    both, and test currency binds the final tree instead.
    """

    approval = _require_gate(state_value, LITE_GATE)
    if _uses_confirmation_contract(state_value):
        risk = state_value.get("risk_assessment") or {}
        if (
            approval.get("lite_policy_sha256")
            != risk.get("policy_sha256")
        ):
            raise FlowError(
                "STALE_APPROVAL",
                "lite approval does not bind the task risk policy",
                details={
                    "expected_lite_policy_sha256": risk.get(
                        "policy_sha256"
                    ),
                    "approved_lite_policy_sha256": approval.get(
                        "lite_policy_sha256"
                    ),
                },
            )
    current_evidence_sha = _lite_preflight_evidence_sha256(state_value)
    if approval.get("preflight_evidence_sha256") != current_evidence_sha:
        raise FlowError(
            "STALE_APPROVAL",
            "lite approval does not bind the current preflight evidence",
            details={
                "expected_preflight_evidence_sha256": current_evidence_sha,
                "approved_preflight_evidence_sha256": approval.get(
                    "preflight_evidence_sha256"
                ),
            },
        )
    dirty_repositories = [
        repo["id"]
        for repo in state_value.get("repositories", [])
        if (repo.get("preflight") or {}).get("dirty")
    ]
    if dirty_repositories and approval.get("dirty_allowed") is not True:
        raise FlowError(
            "DIRTY_NOT_APPROVED",
            "dirty preflight snapshots require lite approval with --allow-dirty",
            details={"repository_ids": dirty_repositories},
        )
    for repo in state_value.get("repositories", []):
        preflight = repo.get("preflight") or {}
        _assert_branch_checkout_binding(state_value, repo)
        path = Path(repo["path"])
        actual_branch = _git_optional(
            path, "symbolic-ref", "--quiet", "--short", "HEAD"
        )
        if actual_branch != preflight.get("branch"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout branch changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_branch": preflight.get("branch"),
                    "actual_branch": actual_branch,
                },
            )
        if not verify_worktree:
            continue
        actual_head = _git_optional(path, "rev-parse", "HEAD")
        if actual_head != preflight.get("head_sha"):
            raise FlowError(
                "CHECKOUT_DRIFT",
                f"checkout HEAD changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "approved_head_sha": preflight.get("head_sha"),
                    "actual_head_sha": actual_head,
                },
            )
        fingerprint = (
            fingerprints.get(repo["id"])
            if fingerprints is not None
            else None
        )
        if fingerprint is None:
            fingerprint = _fingerprint_repo(path)
        actual_fingerprint = fingerprint["sha256"]
        if actual_fingerprint != preflight.get("worktree_fingerprint_sha256"):
            raise FlowError(
                "PREFLIGHT_WORKTREE_CHANGED",
                f"repository worktree changed after lite approval: {repo['id']}",
                details={
                    "repository_id": repo["id"],
                    "recorded_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
                    "actual_fingerprint_sha256": actual_fingerprint,
                },
            )
    return approval


def _materialize_analysis_workspace(
    state_value: dict[str, Any], repo: dict[str, Any], data_root: Path
) -> dict[str, Any]:
    source = Path(repo["path"]).resolve(strict=True)
    baseline = _require_current_evidence(
        repo.get("baseline"), f"baseline:{repo.get('id')}"
    )
    _assert_evidence_supported(source)
    base_sha = baseline.get("base_sha")
    if not base_sha:
        raise FlowError("BASELINE_REQUIRED", f"repository is missing a baseline: {repo['id']}")
    _assert_tree_checkout_supported(source, base_sha)
    destination = (
        data_root / "analysis" / state_value["task_id"] / repo["id"]
    ).resolve(strict=False)
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != baseline.get(
        "capability_profile_sha256"
    ):
        raise FlowError(
            "GIT_CAPABILITY_CHANGED",
            "source repository capabilities changed after baseline",
            details={"repository_id": repo.get("id")},
        )
    destination_profile = _git_capability_profile(source, destination)
    entries = _worktree_entries(source)
    destination_entry = next(
        (
            entry
            for entry in entries
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if destination.exists():
        root = _git_optional(destination, "rev-parse", "--show-toplevel")
        head = _git_optional(destination, "rev-parse", "HEAD")
        branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
        same_common_dir = False
        linked_worktree = False
        status_available, status_porcelain = _status_porcelain(destination)
        if root:
            try:
                same_common_dir = _same_path(
                    _git_common_dir(destination), _git_common_dir(source)
                )
                linked_worktree = _is_linked_worktree(destination)
            except (FlowError, OSError):
                same_common_dir = False
        if (
            not root
            or not _same_path(Path(root), destination)
            or not same_common_dir
            or not linked_worktree
            or head != base_sha
            or branch is not None
            or not destination_entry
            or destination_entry.get("HEAD") != head
            or "detached" not in destination_entry
            or not status_available
            or bool(status_porcelain)
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"analysis path exists but is not the pinned detached worktree: {destination}",
                details={
                    "repository_id": repo["id"],
                    "path": str(destination),
                    "expected_head": base_sha,
                    "actual_head": head,
                    "actual_branch": branch,
                    "same_common_dir": same_common_dir,
                    "linked_worktree": linked_worktree,
                    "dirty": bool(status_porcelain),
                    "status_porcelain": status_porcelain,
                },
            )
        fingerprint = _fingerprint_repo(destination)
        if fingerprint["capability_profile_sha256"] != destination_profile[
            "sha256"
        ]:
            raise FlowError(
                "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                "analysis worktree capabilities differ from the approved destination profile",
                details={"repository_id": repo.get("id")},
            )
        _set_private_permissions(destination, 0o700)
        return {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "path": str(destination),
            "path_identity": _serializable_path_identity(destination),
            "source_identity": _serializable_path_identity(source),
            "source_common_dir_identity": _serializable_path_identity(
                _git_common_dir(source)
            ),
            "head_sha": head,
            "detached": True,
            "ready": True,
            "created": False,
            "materialized_at": utc_now(),
            "filesystem_identity": _serializable_path_identity(destination),
            "source_capability_profile_sha256": source_profile["sha256"],
            "capability_profile_sha256": fingerprint[
                "capability_profile_sha256"
            ],
            "fingerprint_sha256": fingerprint["sha256"],
        }
    if destination_entry:
        recorded = repo.get("analysis_workspace") or {}
        if not recorded.get("ready") or not _recorded_path_matches(
            recorded.get("path_identity"),
            recorded.get("path"),
            destination,
        ):
            raise FlowError(
                "ANALYSIS_WORKSPACE_COLLISION",
                f"Git reports an unowned analysis path that is unavailable: {destination}",
                details={"repository_id": repo["id"], "path": str(destination)},
            )
    _ensure_private_dir(destination.parent)
    add_arguments = ["worktree", "add"]
    if destination_entry:
        add_arguments.append("--force")
    add_arguments.extend(["--detach", str(destination), base_sha])
    _git_mutating(
        source,
        "-c",
        f"core.hooksPath={os.devnull}",
        *add_arguments,
    )
    head = _git(destination, "rev-parse", "HEAD")
    branch = _git_optional(destination, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(destination)
    created_entry = next(
        (
            entry
            for entry in _worktree_entries(source)
            if entry.get("worktree")
            and _same_path(Path(entry["worktree"]), destination)
        ),
        None,
    )
    if (
        head != base_sha
        or branch is not None
        or not _same_path(
            _git_common_dir(destination), _git_common_dir(source)
        )
        or not _is_linked_worktree(destination)
        or not status_available
        or bool(status_porcelain)
        or not created_entry
        or created_entry.get("HEAD") != head
        or "detached" not in created_entry
    ):
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            f"created analysis worktree failed verification: {destination}",
            details={
                "expected_head": base_sha,
                "actual_head": head,
                "actual_branch": branch,
                "dirty": bool(status_porcelain),
                "status_porcelain": status_porcelain,
            },
        )
    fingerprint = _fingerprint_repo(destination)
    if fingerprint["capability_profile_sha256"] != destination_profile[
        "sha256"
    ]:
        raise FlowError(
            "ANALYSIS_WORKSPACE_VERIFY_FAILED",
            "analysis worktree capabilities differ from the approved destination profile",
            details={"repository_id": repo.get("id")},
        )
    _set_private_permissions(destination, 0o700)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(destination),
        "path_identity": _serializable_path_identity(destination),
        "source_identity": _serializable_path_identity(source),
        "source_common_dir_identity": _serializable_path_identity(
            _git_common_dir(source)
        ),
        "head_sha": head,
        "detached": True,
        "ready": True,
        "created": True,
        "materialized_at": utc_now(),
        "filesystem_identity": _serializable_path_identity(destination),
        "source_capability_profile_sha256": source_profile["sha256"],
        "capability_profile_sha256": fingerprint["capability_profile_sha256"],
        "fingerprint_sha256": fingerprint["sha256"],
    }


def _analysis_workspace_integrity_error(repo: dict[str, Any]) -> str | None:
    analysis = repo.get("analysis_workspace") or {}
    try:
        _require_current_evidence(repo.get("baseline"), f"baseline:{repo.get('id')}")
        _require_current_evidence(analysis, f"analysis-workspace:{repo.get('id')}")
    except FlowError as exc:
        return exc.message
    if not analysis.get("ready") or not analysis.get("path"):
        return f"analysis workspace is not ready: {repo.get('id')}"
    source = Path(repo["path"]).resolve(strict=False)
    path = Path(analysis["path"]).resolve(strict=False)
    if not _recorded_path_matches(
        analysis.get("source_identity"), repo.get("path"), source
    ):
        return f"analysis source identity changed: {repo.get('id')}"
    if not _recorded_path_matches(
        analysis.get("path_identity"), analysis.get("path"), path
    ):
        return f"analysis workspace path identity changed: {repo.get('id')}"
    if not path.is_dir():
        return f"analysis workspace path is missing: {repo.get('id')}"
    expected_head = (repo.get("baseline") or {}).get("base_sha")
    root = _git_optional(path, "rev-parse", "--show-toplevel")
    head = _git_optional(path, "rev-parse", "HEAD")
    branch = _git_optional(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    status_available, status_porcelain = _status_porcelain(path)
    try:
        same_common_dir = _same_path(
            _git_common_dir(path), _git_common_dir(source)
        )
        linked_worktree = _is_linked_worktree(path)
    except (FlowError, OSError):
        same_common_dir = False
        linked_worktree = False
    entry = next(
        (
            item
            for item in _worktree_entries(source)
            if item.get("worktree")
            and _same_path(Path(item["worktree"]), path)
        ),
        None,
    )
    if (
        not root
        or not _same_path(Path(root), path)
        or head != expected_head
        or branch is not None
        or not same_common_dir
        or not linked_worktree
        or not status_available
        or bool(status_porcelain)
        or not entry
        or entry.get("HEAD") != head
        or "detached" not in entry
    ):
        return f"analysis workspace identity, baseline or cleanliness changed: {repo.get('id')}"
    try:
        fingerprint = _fingerprint_repo(path)
    except FlowError as exc:
        return f"analysis workspace evidence cannot be regenerated: {repo.get('id')}: {exc.message}"
    if (
        fingerprint.get("capability_profile_sha256")
        != analysis.get("capability_profile_sha256")
    ):
        return f"analysis workspace capability profile changed: {repo.get('id')}"
    source_profile = _git_capability_profile(source)
    if source_profile["sha256"] != analysis.get(
        "source_capability_profile_sha256"
    ):
        return f"analysis source capability profile changed: {repo.get('id')}"
    if fingerprint.get("sha256") != analysis.get("fingerprint_sha256"):
        return f"analysis workspace fingerprint changed: {repo.get('id')}"
    return None


def command_baseline(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="task.baseline",
    ) as (task_dir, current):
        _assert_flow(current, "full", "baseline")
        _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "baseline")
        baseline_approval = _require_baseline_fetch_approval(current)
        if args.fetch and baseline_approval.get("fetch_allowed") is not True:
            raise FlowError(
                "FETCH_NOT_APPROVED",
                "baseline --fetch requires baseline-fetch approval with --allow-fetch",
            )
        already_baselined = current.get("status") == "BASELINED" and all(
            repo.get("baseline") for repo in current["repositories"]
        )
        regenerate_baseline = already_baselined and any(
            (repo.get("baseline") or {}).get(
                "evidence_contract_version"
            )
            != EVIDENCE_CONTRACT_VERSION
            for repo in current["repositories"]
        )
        if already_baselined and args.fetch:
            raise FlowError(
                "BASELINE_ALREADY_PINNED",
                "--fetch cannot repin an existing baseline; the recorded base is immutable",
            )
        if (
            already_baselined
            and not regenerate_baseline
            and not args.materialize
        ):
            return _result(
                "baseline",
                current,
                unchanged=True,
                repositories=[
                    {
                        "id": repo["id"],
                        "baseline": repo["baseline"],
                        "analysis_workspace": repo.get("analysis_workspace"),
                    }
                    for repo in current["repositories"]
                ],
            )
        state_value = _copy_state(current)
        if not already_baselined or regenerate_baseline:
            for repo in state_value["repositories"]:
                previous_baseline = repo.get("baseline") or {}
                preflight = repo.get("preflight") or {}
                if not preflight.get("ready"):
                    raise FlowError(
                        "PREFLIGHT_REQUIRED",
                        f"repository has not passed preflight: {repo['id']}",
                        details={"repository_id": repo["id"]},
                    )
                path = Path(repo["path"])
                current_head = _git(path, "rev-parse", "HEAD")
                if current_head != preflight.get("head_sha"):
                    raise FlowError(
                        "HEAD_CHANGED",
                        f"repository HEAD changed after preflight: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "preflight_head": preflight.get("head_sha"),
                            "current_head": current_head,
                        },
                    )
                remote = preflight.get("remote")
                candidate_ref = _baseline_source_ref(
                    remote, preflight.get("base_branch")
                )
                pre_fetch_sha = (
                    _git_optional(
                        path,
                        "rev-parse",
                        "--verify",
                        f"{candidate_ref}^{{commit}}",
                    )
                    if candidate_ref
                    else None
                )
                if args.fetch and remote:
                    fetch_refspec = preflight.get("fetch_refspec")
                    live_remote_url = _live_approved_remote_url(
                        path, repo["id"], preflight
                    )
                    if fetch_refspec != _approved_fetch_refspec(
                        remote, preflight.get("base_branch")
                    ):
                        raise FlowError(
                            "STALE_APPROVAL",
                            "approved fetch refspec no longer matches the selected remote base",
                            details={
                                "repository_id": repo["id"],
                                "fetch_refspec": fetch_refspec,
                            },
                        )
                    if (
                        not isinstance(live_remote_url, str)
                        or not live_remote_url.strip()
                    ):
                        raise FlowError(
                            "REMOTE_URL_UNAVAILABLE",
                            "approved fetch has no usable remote URL",
                            details={
                                "repository_id": repo["id"],
                                "remote": remote,
                            },
                        )
                    _git_mutating(
                        path,
                        "-c",
                        f"core.hooksPath={os.devnull}",
                        "-c",
                        "core.fsmonitor=false",
                        "-c",
                        "core.gitProxy=",
                        "-c",
                        "core.askPass=",
                        "-c",
                        "core.sshCommand=ssh",
                        "-c",
                        "credential.helper=",
                        "-c",
                        "maintenance.auto=false",
                        "-c",
                        "gc.auto=0",
                        "-c",
                        "protocol.allow=never",
                        "-c",
                        "protocol.file.allow=always",
                        "-c",
                        "protocol.git.allow=always",
                        "-c",
                        "protocol.http.allow=always",
                        "-c",
                        "protocol.https.allow=always",
                        "-c",
                        "protocol.ssh.allow=always",
                        "-c",
                        "protocol.ext.allow=never",
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "--no-auto-maintenance",
                        "--no-write-commit-graph",
                        "--no-prune",
                        "--no-prune-tags",
                        "--upload-pack=git-upload-pack",
                        "--",
                        live_remote_url,
                        fetch_refspec,
                    )
                source_ref, base_sha = _baseline_ref(path, remote, preflight["base_branch"])
                if not args.fetch and (
                    source_ref != preflight.get("base_candidate_ref")
                    or base_sha != preflight.get("base_candidate_sha")
                ):
                    raise FlowError(
                        "BASE_REF_CHANGED",
                        "base ref changed after preflight approval",
                        details={
                            "repository_id": repo["id"],
                            "approved_ref": preflight.get("base_candidate_ref"),
                            "approved_sha": preflight.get("base_candidate_sha"),
                            "actual_ref": source_ref,
                            "actual_sha": base_sha,
                        },
                    )
                if (
                    regenerate_baseline
                    and previous_baseline.get("base_sha") != base_sha
                ):
                    raise FlowError(
                        "EVIDENCE_REGENERATION_REQUIRED",
                        "legacy baseline no longer resolves to its recorded immutable object",
                        details={
                            "repository_id": repo["id"],
                            "recorded_base_sha": previous_baseline.get(
                                "base_sha"
                            ),
                            "current_base_sha": base_sha,
                        },
                    )
                repo["baseline"] = {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "recorded_at": utc_now(),
                    "remote": remote,
                    "base_branch": preflight["base_branch"],
                    "source_ref": source_ref,
                    "base_sha": base_sha,
                    "remote_base_sha": base_sha,
                    "head_sha": preflight["head_sha"],
                    "fetched": bool(args.fetch and remote),
                    "pre_fetch_base_sha": pre_fetch_sha,
                    "fetch_refspec": preflight.get("fetch_refspec"),
                    "capability_profile": preflight.get("capability_profile"),
                    "capability_profile_sha256": preflight.get(
                        "capability_profile_sha256"
                    ),
                    "worktree_fingerprint_sha256": preflight.get(
                        "worktree_fingerprint_sha256"
                    ),
                }
        if args.materialize:
            source_fingerprints = {
                repo["id"]: _fingerprint_repo(Path(repo["path"]))["sha256"]
                for repo in state_value["repositories"]
            }
            for repo in state_value["repositories"]:
                repo["analysis_workspace"] = _materialize_analysis_workspace(
                    state_value, repo, resolve_data_dir(args.data_dir)
                )
            for repo in state_value["repositories"]:
                error = _analysis_workspace_integrity_error(repo)
                if error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_VERIFY_FAILED",
                        error,
                        details={"repository_id": repo["id"]},
                    )
                current_source = _fingerprint_repo(Path(repo["path"]))["sha256"]
                if current_source != source_fingerprints[repo["id"]]:
                    raise FlowError(
                        "SOURCE_WORKTREE_CHANGED",
                        "source checkout changed while materializing analysis worktrees",
                        details={"repository_id": repo["id"]},
                    )
        state_value["status"] = "BASELINED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "baseline_recorded",
            {
                "fetch": bool(args.fetch),
                "materialize": bool(args.materialize),
                "base_shas": {
                    repo["id"]: repo["baseline"]["base_sha"]
                    for repo in state_value["repositories"]
                },
            },
        )
    return _result(
        "baseline",
        state_value,
        repositories=[
            {
                "id": repo["id"],
                "baseline": repo["baseline"],
                "analysis_workspace": repo.get("analysis_workspace"),
            }
            for repo in state_value["repositories"]
        ],
    )


def _validate_degraded_index_metadata(
    metadata: dict[str, Any], approval: dict[str, Any]
) -> None:
    if metadata.get("status") != "failed":
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "an index without --index-id requires metadata status='failed'",
        )
    if metadata.get("impact_degraded_approval_id") != approval.get("approval_id"):
        raise FlowError(
            "STALE_APPROVAL",
            "degraded index metadata must bind the current impact-degraded approval",
            details={
                "expected_approval_id": approval.get("approval_id"),
                "provided_approval_id": metadata.get("impact_degraded_approval_id"),
            },
        )
    if not isinstance(metadata.get("error"), str) or not metadata["error"].strip():
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires a non-empty error",
        )
    if not metadata.get("fallback_coverage"):
        raise FlowError(
            "DEGRADED_INDEX_METADATA_REQUIRED",
            "degraded index metadata requires non-empty fallback_coverage",
        )


def _index_provenance_evidence(state_value: dict[str, Any]) -> dict[str, Any]:
    repositories: list[dict[str, Any]] = []
    for repo in state_value.get("repositories", []):
        index = repo.get("index")
        if not isinstance(index, dict):
            raise FlowError(
                "INDEX_REQUIRED",
                f"repository is missing index provenance: {repo.get('id')}",
            )
        _require_current_evidence(index, f"baseline-index:{repo.get('id')}")
        integrity_error = _analysis_workspace_integrity_error(repo)
        if integrity_error:
            raise FlowError(
                "ANALYSIS_WORKSPACE_CHANGED",
                integrity_error,
                details={"repository_id": repo.get("id")},
            )
        analysis_workspace = repo.get("analysis_workspace") or {}
        analysis_path = Path(str(analysis_workspace.get("path", "")))
        if (
            not _recorded_path_matches(
                index.get("repo_path_identity"),
                index.get("repo_path"),
                analysis_path,
            )
            or index.get("commit_sha")
            != (repo.get("baseline") or {}).get("base_sha")
            or index.get("capability_profile_sha256")
            != analysis_workspace.get("capability_profile_sha256")
            or index.get("fingerprint_sha256")
            != analysis_workspace.get("fingerprint_sha256")
        ):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                "baseline index no longer binds the current analysis evidence",
                details={"repository_id": repo.get("id")},
            )
        if not index.get("index_record_id"):
            raise FlowError(
                "INDEX_PROVENANCE_INVALID",
                f"repository index has no stable record token: {repo.get('id')}",
            )
        receipt = index.get("receipt")
        if isinstance(receipt, dict):
            _require_current_evidence(
                receipt, f"index-receipt:{repo.get('id')}"
            )
            receipt_path = Path(str(receipt.get("path", "")))
            expected_receipt_sha = receipt.get("sha256")
            try:
                actual_receipt_sha = (
                    _sha256_file(receipt_path) if receipt_path.is_file() else None
                )
            except OSError:
                actual_receipt_sha = None
            if (
                not isinstance(expected_receipt_sha, str)
                or actual_receipt_sha != expected_receipt_sha
                or not _recorded_path_matches(
                    receipt.get("path_identity"),
                    receipt.get("path"),
                    receipt_path,
                )
            ):
                raise FlowError(
                    "INDEX_RECEIPT_CHANGED",
                    f"index receipt is missing or changed: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "path": str(receipt_path),
                        "expected_sha256": expected_receipt_sha,
                        "actual_sha256": actual_receipt_sha,
                    },
                )
        if not index.get("index_id"):
            approval = _require_gate(state_value, "impact-degraded")
            _validate_degraded_index_metadata(index.get("metadata") or {}, approval)
            if index.get("impact_degraded_approval_id") != approval.get("approval_id"):
                raise FlowError(
                    "STALE_APPROVAL",
                    f"degraded index no longer binds the current approval: {repo.get('id')}",
                    details={
                        "repository_id": repo.get("id"),
                        "expected_approval_id": approval.get("approval_id"),
                        "recorded_approval_id": index.get("impact_degraded_approval_id"),
                    },
                )
        repositories.append(
            {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "repository_id": repo["id"],
                "index_record_id": index["index_record_id"],
                "commit_sha": index.get("commit_sha"),
                "index_id": index.get("index_id"),
                "receipt": index.get("receipt"),
                "repo_path_identity": index.get("repo_path_identity"),
                "capability_profile_sha256": index.get(
                    "capability_profile_sha256"
                ),
                "fingerprint_sha256": index.get("fingerprint_sha256"),
                "metadata": index.get("metadata") or {},
                "impact_degraded_approval_id": index.get(
                    "impact_degraded_approval_id"
                ),
            }
        )
    repositories.sort(key=lambda item: item["repository_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "task_id": state_value["task_id"],
        "repositories": repositories,
    }


def _index_provenance_sha256(state_value: dict[str, Any]) -> str:
    return _sha256_bytes(_json_bytes(_index_provenance_evidence(state_value)))


def _index_receipt(path_value: str | None) -> dict[str, Any] | None:
    if not path_value:
        return None
    receipt_path = Path(path_value).expanduser().resolve(strict=True)
    return {
        "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
        "path": str(receipt_path),
        "path_identity": _serializable_path_identity(receipt_path),
        "sha256": _sha256_file(receipt_path),
        "size": receipt_path.stat().st_size,
    }


def _repository_index_history(repo: dict[str, Any]) -> list[dict[str, Any]]:
    history = repo.setdefault("index_history", [])
    if not isinstance(history, list) or not all(
        isinstance(item, dict) for item in history
    ):
        raise FlowError(
            "INDEX_HISTORY_INVALID",
            f"repository index history has an invalid structure: {repo.get('id')}",
            details={"repository_id": repo.get("id")},
        )
    return history


def _archive_replaced_index(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    previous_role: str,
    replacement: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(previous, dict):
        return None, None
    previous_record = _copy_state(previous)
    previous_record.setdefault("role", previous_role)
    replacement_binding = {
        "role": replacement.get("role"),
        "project": replacement.get("index_id"),
        "index_id": replacement.get("index_id"),
        "index_record_id": replacement.get("index_record_id"),
    }
    archived = {
        **previous_record,
        "superseded_at": replacement.get("recorded_at") or utc_now(),
        "replacement_role": replacement_binding["role"],
        "replacement_project": replacement_binding["project"],
        "replacement_index_id": replacement_binding["index_id"],
        "replacement_record_id": replacement_binding["index_record_id"],
        "replacement_index_record_id": replacement_binding[
            "index_record_id"
        ],
        "replacement": replacement_binding,
    }
    _repository_index_history(repo).append(archived)
    return previous_record, archived


def _recorded_index_change(
    repo: dict[str, Any],
    previous: dict[str, Any] | None,
    role: str,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    previous_record, history_entry = _archive_replaced_index(
        repo, previous, role, replacement
    )
    return {
        "repository_id": repo.get("id"),
        "role": role,
        "previous": previous_record,
        "current": _copy_state(replacement),
        "history_entry": _copy_state(history_entry)
        if history_entry is not None
        else None,
    }


def _archived_workspace_indexes(repo: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for workspace in repo.get("workspace_history", []):
        if not isinstance(workspace, dict):
            continue
        archived = workspace.get("workspace_index")
        if isinstance(archived, dict):
            yield archived


def _assert_index_id_available(
    state_value: dict[str, Any],
    repo: dict[str, Any],
    role: str,
    index_id: str,
) -> None:
    conflicts: list[dict[str, Any]] = []
    current_generation = int(
        (state_value.get("workspace") or {}).get("generation", 0)
    )
    for candidate in state_value.get("repositories", []):
        baseline = candidate.get("index")
        if isinstance(baseline, dict) and baseline.get("index_id") == index_id:
            same_role_refresh = (
                role == "baseline" and candidate.get("id") == repo.get("id")
            )
            if not same_role_refresh:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "baseline",
                        "recorded_project": index_id,
                    }
                )
        workspace = candidate.get("workspace_index")
        if isinstance(workspace, dict) and workspace.get("index_id") == index_id:
            same_current_record = (
                role == "workspace"
                and candidate.get("id") == repo.get("id")
                and workspace.get("workspace_generation")
                == current_generation
            )
            if not same_current_record:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace",
                        "workspace_generation": workspace.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for historical in _repository_index_history(candidate):
            if historical.get("index_id") != index_id:
                continue
            historical_role = historical.get("role")
            same_repository_role = (
                candidate.get("id") == repo.get("id")
                and historical_role == role
            )
            reusable_history = same_repository_role and (
                role == "baseline"
                or (
                    role == "workspace"
                    and historical.get("workspace_generation")
                    == current_generation
                )
            )
            if not reusable_history:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": historical_role,
                        "origin": "index-history",
                        "workspace_generation": historical.get(
                            "workspace_generation"
                        ),
                        "index_record_id": historical.get(
                            "index_record_id"
                        ),
                        "recorded_project": index_id,
                    }
                )
        for archived in _archived_workspace_indexes(candidate):
            if archived.get("index_id") == index_id:
                conflicts.append(
                    {
                        "repository_id": candidate.get("id"),
                        "role": "workspace-history",
                        "origin": "workspace-history",
                        "workspace_generation": archived.get(
                            "workspace_generation"
                        ),
                        "recorded_project": index_id,
                    }
                )
    if conflicts:
        error_code = (
            "WORKSPACE_INDEX_ID_CONFLICT"
            if role == "workspace"
            else "INDEX_ID_CONFLICT"
        )
        raise FlowError(
            error_code,
            "index project must be distinct across role/repository pairs and retired workspace generations",
            details={
                "repository_id": repo.get("id"),
                "role": role,
                "index_id": index_id,
                "conflicts": conflicts,
            },
        )


def command_record_index(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="evidence.index.record",
    ) as (task_dir, current):
        _assert_flow(current, "full", "record-index")
        role = args.role
        if role == "baseline":
            _assert_status(current, {"BASELINED", "INDEXED"}, "record-index")
        else:
            _assert_status(
                current,
                {"WORKSPACE_READY", "PLANNING", "IMPLEMENTING", "VERIFYING"},
                "record-index --role workspace",
            )
        state_value = _copy_state(current)
        selected = _repo_by_selector(state_value, args.repo)
        metadata = _parse_json_object(args.metadata_json, "--metadata-json")
        degraded_approval: dict[str, Any] | None = None
        normalized_index_id = args.index_id.strip() if args.index_id else None
        if role == "workspace":
            if not normalized_index_id:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_REQUIRED",
                    "workspace indexes require a successful non-empty --index-id",
                )
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "workspace index metadata cannot record a failed index",
                )
            if metadata.get("persistence") is not False:
                raise FlowError(
                    "PERSISTENT_WORKSPACE_INDEX_UNSUPPORTED",
                    "workspace index metadata must explicitly set persistence=false",
                )
            _require_workspace_ready(current)
            if len(selected) > 1:
                raise FlowError(
                    "WORKSPACE_INDEX_ID_CONFLICT",
                    "one workspace project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "workspace", normalized_index_id
            )
        elif normalized_index_id:
            if metadata.get("status") == "failed":
                raise FlowError(
                    "INVALID_INDEX_METADATA",
                    "metadata status='failed' is only valid when --index-id is omitted",
                )
            if len(selected) > 1:
                raise FlowError(
                    "INDEX_ID_CONFLICT",
                    "one baseline project id cannot be assigned to multiple repositories",
                    details={
                        "index_id": normalized_index_id,
                        "repository_ids": [repo["id"] for repo in selected],
                    },
                )
            _assert_index_id_available(
                state_value, selected[0], "baseline", normalized_index_id
            )
        else:
            degraded_approval = _require_gate(current, "impact-degraded")
            _validate_degraded_index_metadata(metadata, degraded_approval)
        receipt = _index_receipt(args.receipt)
        index_changes: list[dict[str, Any]] = []
        for repo in selected:
            if role == "baseline":
                analysis_workspace = repo.get("analysis_workspace") or {}
                if not analysis_workspace.get("ready"):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_REQUIRED",
                        f"materialize the pinned baseline before recording an index: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "hint": "baseline --materialize",
                        },
                    )
                integrity_error = _analysis_workspace_integrity_error(repo)
                if integrity_error:
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        integrity_error,
                        details={"repository_id": repo["id"]},
                    )
                repo_path = Path(analysis_workspace["path"])
                expected_sha = repo["baseline"]["base_sha"]
                analysis_head = _git(repo_path, "rev-parse", "HEAD")
                analysis_branch = _git_optional(
                    repo_path,
                    "symbolic-ref",
                    "--quiet",
                    "--short",
                    "HEAD",
                )
                status_available, analysis_status = _status_porcelain(repo_path)
                if (
                    analysis_head != expected_sha
                    or analysis_branch is not None
                    or not status_available
                    or analysis_status
                ):
                    raise FlowError(
                        "ANALYSIS_WORKSPACE_CHANGED",
                        f"analysis worktree no longer exactly represents the pinned base: {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_head": expected_sha,
                            "actual_head": analysis_head,
                            "actual_branch": analysis_branch,
                            "dirty": bool(analysis_status),
                        },
                    )
                commit_sha = args.commit or expected_sha
                resolved = _git_optional(
                    repo_path,
                    "rev-parse",
                    "--verify",
                    f"{commit_sha}^{{commit}}",
                )
                if not resolved:
                    raise FlowError(
                        "INVALID_COMMIT",
                        f"index commit does not exist in repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "commit": commit_sha,
                        },
                    )
                if resolved != expected_sha:
                    raise FlowError(
                        "INDEX_BASE_MISMATCH",
                        f"recorded index must target the pinned base for repository {repo['id']}",
                        details={
                            "repository_id": repo["id"],
                            "expected_commit": expected_sha,
                            "provided_commit": resolved,
                        },
                    )
                replacement = {
                    "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                    "index_record_id": str(uuid.uuid4()),
                    "recorded_at": utc_now(),
                    "role": "baseline",
                    "commit_sha": resolved,
                    "repo_path": str(repo_path),
                    "repo_path_identity": _serializable_path_identity(
                        repo_path
                    ),
                    "capability_profile_sha256": analysis_workspace.get(
                        "capability_profile_sha256"
                    ),
                    "fingerprint_sha256": analysis_workspace.get(
                        "fingerprint_sha256"
                    ),
                    "index_id": normalized_index_id,
                    "recommended_index_id": _recommended_index_name(
                        state_value, repo, "baseline"
                    ),
                    "receipt": receipt,
                    "metadata": metadata,
                    "impact_degraded_approval_id": (
                        degraded_approval.get("approval_id")
                        if degraded_approval
                        else None
                    ),
                }
                index_changes.append(
                    _recorded_index_change(
                        repo, repo.get("index"), "baseline", replacement
                    )
                )
                repo["index"] = replacement
                continue

            workspace = repo.get("workspace") or {}
            integrity_error = _workspace_integrity_error(state_value, repo)
            if integrity_error:
                raise FlowError(
                    "WORKSPACE_INTEGRITY_FAILED",
                    integrity_error,
                    details={"repository_id": repo["id"]},
                )
            repo_path = Path(workspace["path"]).resolve(strict=True)
            actual_branch = _git_optional(
                repo_path, "symbolic-ref", "--quiet", "--short", "HEAD"
            )
            actual_head = _git(repo_path, "rev-parse", "HEAD")
            commit_sha = args.commit or actual_head
            resolved = _git_optional(
                repo_path,
                "rev-parse",
                "--verify",
                f"{commit_sha}^{{commit}}",
            )
            if not resolved:
                raise FlowError(
                    "INVALID_COMMIT",
                    f"index commit does not exist in workspace {repo['id']}",
                    details={"repository_id": repo["id"], "commit": commit_sha},
                )
            if resolved != actual_head:
                raise FlowError(
                    "INDEX_WORKSPACE_MISMATCH",
                    f"workspace index must target the current HEAD for repository {repo['id']}",
                    details={
                        "repository_id": repo["id"],
                        "expected_head": actual_head,
                        "provided_commit": resolved,
                    },
                )
            generation = int(
                (state_value.get("workspace") or {}).get("generation", 0)
            )
            plan_sha = (
                (state_value.get("workspace") or {}).get("plan") or {}
            ).get("sha256")
            fingerprint = _fingerprint_repo(repo_path)
            replacement = {
                "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
                "index_record_id": str(uuid.uuid4()),
                "recorded_at": utc_now(),
                "role": "workspace",
                "commit_sha": actual_head,
                "repo_path": str(repo_path),
                "repo_path_identity": _serializable_path_identity(repo_path),
                "index_id": normalized_index_id,
                "recommended_index_id": _recommended_index_name(
                    state_value, repo, "workspace"
                ),
                "receipt": receipt,
                "metadata": metadata,
                "fingerprint_sha256": fingerprint["sha256"],
                "capability_profile_sha256": fingerprint[
                    "capability_profile_sha256"
                ],
                "workspace_generation": generation,
                "workspace_plan_sha256": plan_sha,
                "workspace_branch": actual_branch,
                "workspace_head_sha": actual_head,
            }
            index_changes.append(
                _recorded_index_change(
                    repo,
                    repo.get("workspace_index"),
                    "workspace",
                    replacement,
                )
            )
            repo["workspace_index"] = replacement
        if role == "baseline":
            all_indexed = all(
                repo.get("index") for repo in state_value["repositories"]
            )
            if all_indexed:
                state_value["status"] = "INDEXED"
        else:
            all_indexed = all(
                repo.get("workspace_index")
                for repo in state_value["repositories"]
            )
        automatic_state_transition = (
            _uses_confirmation_contract(current)
            and current.get("status") != state_value.get("status")
        )
        if automatic_state_transition:
            _require_automatic_action(
                _flow(current),
                "record-index",
                str(current.get("status")),
                str(state_value.get("status")),
            )
        _commit_state(
            current,
            state_value,
            task_dir,
            "index_recorded",
            {
                "role": role,
                "repository_ids": [repo["id"] for repo in selected],
                "complete": all_indexed,
                "index_records": index_changes,
                "confirmation_mode": (
                    "automatic"
                    if automatic_state_transition
                    else "not-applicable"
                ),
            },
            additional_events=(
                [
                    (
                        "state_transitioned",
                        {
                            "from": "BASELINED",
                            "to": "INDEXED",
                            "action": "record-index",
                            "confirmation_mode": "automatic",
                        },
                    )
                ]
                if automatic_state_transition
                else None
            ),
        )
    return _result(
        "record-index",
        state_value,
        role=role,
        complete=all_indexed,
        repositories=[
            {
                "id": repo["id"],
                "role": role,
                "repo_path": (
                    repo["analysis_workspace"]["path"]
                    if role == "baseline"
                    else repo["workspace"]["path"]
                ),
                "index": (
                    repo["index"]
                    if role == "baseline"
                    else repo["workspace_index"]
                ),
                **(
                    {"workspace_index": repo["workspace_index"]}
                    if role == "workspace"
                    else {}
                ),
            }
            for repo in selected
        ],
    )


IMPACT_CHECKS = (
    "orientation",
    "candidates",
    "paths",
    "contracts",
    "tests",
    "source_confirmation",
)
IMPACT_QUERY_KEYS = (
    "architecture",
    "search_graph",
    "trace",
    "search_code",
    "snippet",
)
IMPACT_QUERY_BUDGETS = {
    "seed-v1": {
        "architecture": 1,
        "search_graph": 5,
        "trace": 4,
        "search_code": 3,
        "snippet": 4,
    },
    "expanded-v1": {
        "architecture": 1,
        "search_graph": 9,
        "trace": 8,
        "search_code": 6,
        "snippet": 8,
    },
}
IMPACT_ANALYSIS_CANONICAL_FIELDS = (
    "schema",
    "strategy",
    "coverage",
    "budget_profile",
    "expansion_reason",
    "repositories",
    "cross_repository",
)
IMPACT_ANALYSIS_CONTROLLER_FIELDS = frozenset(
    {
        "impact_analysis_contract_version",
        "impact_analysis_sha256",
        "index_provenance_sha256",
        "impact_generation",
    }
)


def _impact_contract_error(
    message: str, *, details: dict[str, Any] | None = None
) -> None:
    raise FlowError(
        "IMPACT_ANALYSIS_INVALID",
        message,
        details=details or {},
    )


def _impact_analysis_canonical_projection(
    metadata: dict[str, Any],
    *,
    allow_controller_fields: bool = False,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        _impact_contract_error("impact metadata must be an object")
    allowed = set(IMPACT_ANALYSIS_CANONICAL_FIELDS)
    if allow_controller_fields:
        allowed.update(IMPACT_ANALYSIS_CONTROLLER_FIELDS)
    invalid_keys = [
        key
        for key in metadata
        if not isinstance(key, str) or key not in allowed
    ]
    if invalid_keys:
        _impact_contract_error(
            (
                "impact metadata contains controller-owned, reserved, "
                "or unsupported fields"
            ),
            details={
                "fields": sorted(str(key) for key in invalid_keys),
            },
        )
    return {
        field: _copy_state(metadata[field])
        for field in IMPACT_ANALYSIS_CANONICAL_FIELDS
        if field in metadata
    }


def _impact_analysis_contract_sha256(
    metadata: dict[str, Any],
    *,
    allow_controller_fields: bool = False,
) -> str:
    projection = _impact_analysis_canonical_projection(
        metadata,
        allow_controller_fields=allow_controller_fields,
    )
    return _sha256_bytes(_json_bytes(projection))


def _validate_impact_analysis_contract(
    state_value: dict[str, Any], metadata: dict[str, Any]
) -> dict[str, Any]:
    metadata = _impact_analysis_canonical_projection(metadata)
    if metadata.get("schema") != "dev-flow-impact-analysis/v1":
        _impact_contract_error(
            "schema-v2 tasks require dev-flow-impact-analysis/v1 metadata"
        )
    if metadata.get("strategy") != "funnel":
        _impact_contract_error("impact strategy must be funnel")
    coverage = metadata.get("coverage")
    if coverage not in {"complete", "degraded"}:
        _impact_contract_error(
            "impact coverage must be complete or degraded"
        )
    profile = metadata.get("budget_profile")
    budget = IMPACT_QUERY_BUDGETS.get(profile)
    if budget is None:
        _impact_contract_error(
            "impact budget_profile must be seed-v1 or expanded-v1"
        )
    if profile == "expanded-v1" and not _nonempty(
        metadata.get("expansion_reason")
    ):
        _impact_contract_error(
            "expanded-v1 requires a non-empty expansion_reason"
        )
    repositories = metadata.get("repositories")
    if not isinstance(repositories, list):
        _impact_contract_error("impact repositories must be a list")
    expected = {
        repo["id"]: repo for repo in state_value.get("repositories", [])
    }
    supplied_ids: list[str] = []
    for item in repositories:
        if not isinstance(item, dict):
            _impact_contract_error(
                "each impact repository must be an object"
            )
        repository_id = item.get("repository_id")
        if not isinstance(repository_id, str) or not repository_id.strip():
            _impact_contract_error(
                "impact repository_id must be a non-empty string",
                details={"repository_id": repository_id},
            )
        supplied_ids.append(repository_id)
    if (
        len(set(supplied_ids)) != len(supplied_ids)
        or set(supplied_ids) != set(expected)
    ):
        _impact_contract_error(
            "impact repositories must exactly cover the task repositories",
            details={
                "expected_repository_ids": sorted(expected),
                "provided_repository_ids": supplied_ids,
            },
        )
    degraded_signal = False
    for item in repositories:
        repository_id = item["repository_id"]
        current_index = expected[repository_id].get("index") or {}
        index_id = item.get("index_id")
        if index_id is not None and (
            not isinstance(index_id, str) or not index_id.strip()
        ):
            _impact_contract_error(
                "impact index_id must be a non-empty string or null",
                details={"repository_id": repository_id},
            )
        if index_id is not None and index_id != current_index.get("index_id"):
            _impact_contract_error(
                "impact index_id does not match current index provenance",
                details={
                    "repository_id": repository_id,
                    "expected_index_id": current_index.get("index_id"),
                    "provided_index_id": index_id,
                },
            )
        index_mode = item.get("index_mode")
        if index_mode not in {"fast", "moderate", "full"}:
            _impact_contract_error(
                "impact index_mode must be fast, moderate, or full",
                details={"repository_id": repository_id},
            )
        index_receipt = current_index.get("receipt")
        index_receipt = (
            index_receipt if isinstance(index_receipt, dict) else {}
        )
        index_metadata = current_index.get("metadata")
        index_metadata = (
            index_metadata if isinstance(index_metadata, dict) else {}
        )
        recorded_mode = index_receipt.get("mode") or index_metadata.get(
            "mode"
        )
        if recorded_mode is not None and index_mode != recorded_mode:
            _impact_contract_error(
                "impact index_mode does not match current index provenance",
                details={
                    "repository_id": repository_id,
                    "expected_index_mode": recorded_mode,
                    "provided_index_mode": index_mode,
                },
            )
        checks = item.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(
            IMPACT_CHECKS
        ):
            _impact_contract_error(
                "impact checks must contain the exact completeness fields",
                details={"repository_id": repository_id},
            )
        for check_name in IMPACT_CHECKS:
            check = checks[check_name]
            if not isinstance(check, dict) or check.get("status") not in {
                "complete",
                "not_applicable",
                "degraded",
            }:
                _impact_contract_error(
                    "impact check has an invalid status",
                    details={
                        "repository_id": repository_id,
                        "check": check_name,
                    },
                )
            if check["status"] != "complete" and not _nonempty(
                check.get("reason")
            ):
                _impact_contract_error(
                    "non-complete impact checks require a reason",
                    details={
                        "repository_id": repository_id,
                        "check": check_name,
                    },
                )
            if check["status"] == "degraded":
                degraded_signal = True
        queries = item.get("queries")
        if not isinstance(queries, dict) or set(queries) != set(
            IMPACT_QUERY_KEYS
        ):
            _impact_contract_error(
                "impact queries must contain the exact canonical counters",
                details={"repository_id": repository_id},
            )
        for query_name, limit in budget.items():
            count = queries[query_name]
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                or count > limit
            ):
                _impact_contract_error(
                    "impact query count exceeds its declared budget",
                    details={
                        "repository_id": repository_id,
                        "query": query_name,
                        "count": count,
                        "limit": limit,
                        "budget_profile": profile,
                    },
                )
        for field in ("unresolved_truncations", "material_unknowns"):
            entries = item.get(field)
            if not isinstance(entries, list):
                _impact_contract_error(
                    f"impact {field} must be a list",
                    details={"repository_id": repository_id},
                )
            if entries:
                degraded_signal = True
        if index_id is None:
            degraded_signal = True
        if coverage == "complete" and (
            index_id is None
            or any(
                checks[name]["status"] == "degraded"
                for name in IMPACT_CHECKS
            )
            or item["unresolved_truncations"]
            or item["material_unknowns"]
        ):
            _impact_contract_error(
                "complete coverage conflicts with degraded repository evidence",
                details={"repository_id": repository_id},
            )
    cross = metadata.get("cross_repository")
    if not isinstance(cross, dict) or cross.get("status") not in {
        "complete",
        "not_applicable",
        "degraded",
    }:
        _impact_contract_error(
            "cross_repository has an invalid status"
        )
    if cross["status"] != "complete" and not _nonempty(
        cross.get("reason")
    ):
        _impact_contract_error(
            "non-complete cross_repository status requires a reason"
        )
    if len(expected) > 1 and cross["status"] == "not_applicable":
        _impact_contract_error(
            "multi-repository impact cannot mark cross_repository not applicable"
        )
    if cross["status"] == "degraded":
        degraded_signal = True
    if coverage == "complete" and cross["status"] == "degraded":
        _impact_contract_error(
            "complete coverage conflicts with degraded cross-repository evidence"
        )
    if coverage == "degraded" and not degraded_signal:
        _impact_contract_error(
            "degraded coverage must identify a degraded or unresolved signal"
        )
    normalized = _copy_state(metadata)
    normalized["impact_analysis_contract_version"] = (
        IMPACT_ANALYSIS_CONTRACT_VERSION
    )
    normalized["impact_analysis_sha256"] = (
        _impact_analysis_contract_sha256(metadata)
    )
    return normalized


def command_record_artifact(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    artifact_path = Path(args.path).expanduser().resolve(strict=True)
    metadata = _parse_json_object(args.metadata_json, "--metadata-json")
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="evidence.artifact.record",
    ) as (task_dir, current):
        artifact_hash = _hash_artifact(artifact_path)
        digest = artifact_hash["sha256"]
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "record-artifact")
        if args.kind in {"workspace-plan", "review-snapshot"}:
            raise FlowError(
                "RESERVED_ARTIFACT_KIND",
                f"{args.kind} is controller-generated and cannot be recorded manually",
                details={"kind": args.kind},
            )
        if args.kind != "review-report" and args.verdict:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--verdict is only valid with --kind review-report",
            )
        if args.kind == "review-report":
            _assert_status(current, {"REVIEWING"}, "record-artifact --kind review-report")
            if not args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--kind review-report requires --verdict PASS, CONDITIONAL or FAIL",
                )
            body_verdict = _parse_review_report_verdict(artifact_path)
            if body_verdict != args.verdict:
                raise FlowError(
                    "REVIEW_VERDICT_MISMATCH",
                    "--verdict does not match the review report's Verdict field",
                    details={
                        "path": str(artifact_path),
                        "body_verdict": body_verdict,
                        "verdict": args.verdict,
                    },
                )
            snapshot = _latest_review_snapshot(current)
            if not snapshot:
                raise FlowError(
                    "CURRENT_REVIEW_REQUIRED",
                    "record a review snapshot before recording a review report",
                )
            supplied_binding = metadata.get("review_snapshot_sha256")
            if supplied_binding and supplied_binding != snapshot.get("sha256"):
                raise FlowError(
                    "STALE_REVIEW_REPORT",
                    "review report metadata does not name the latest review snapshot",
                    details={
                        "expected_review_snapshot_sha256": snapshot.get("sha256"),
                        "provided_review_snapshot_sha256": supplied_binding,
                    },
                )
            metadata = dict(metadata)
            metadata["review_snapshot_sha256"] = snapshot["sha256"]
            supplied_verdict = metadata.get("verdict")
            if supplied_verdict and supplied_verdict != args.verdict:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "review report metadata verdict conflicts with --verdict",
                    details={
                        "metadata_verdict": supplied_verdict,
                        "verdict": args.verdict,
                    },
                )
            metadata["verdict"] = args.verdict
        elif args.kind == "impact":
            _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "record-artifact --kind impact")
            if _uses_confirmation_contract(current):
                metadata = _validate_impact_analysis_contract(
                    current, metadata
                )
            index_provenance_sha = _index_provenance_sha256(current)
            impact_generation = int(current.get("impact_generation", 0))
            supplied_binding = metadata.get("index_provenance_sha256")
            if supplied_binding and supplied_binding != index_provenance_sha:
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata does not bind the current all-repository index provenance",
                    details={
                        "expected_index_provenance_sha256": index_provenance_sha,
                        "provided_index_provenance_sha256": supplied_binding,
                    },
                )
            supplied_generation = metadata.get("impact_generation")
            if (
                supplied_generation is not None
                and supplied_generation != impact_generation
            ):
                raise FlowError(
                    "STALE_IMPACT",
                    "impact metadata names a stale impact generation",
                    details={
                        "expected_impact_generation": impact_generation,
                        "provided_impact_generation": supplied_generation,
                    },
                )
            metadata = dict(metadata)
            metadata["index_provenance_sha256"] = index_provenance_sha
            metadata["impact_generation"] = impact_generation
        elif args.kind in {"direct-contract", "openspec-plan"}:
            _assert_status(
                current,
                {"PLANNING"},
                f"record-artifact --kind {args.kind}",
            )
            if args.kind == "openspec-plan":
                _assert_openspec_plan_in_current_workspace(current, artifact_path)
            planning_context = _current_planning_context(current)
            planning_context_sha = _planning_context_sha256(planning_context)
            supplied_context = metadata.get("planning_context")
            supplied_context_sha = metadata.get("planning_context_sha256")
            if (
                supplied_context is not None
                and supplied_context != planning_context
            ) or (
                supplied_context_sha is not None
                and supplied_context_sha != planning_context_sha
            ):
                raise FlowError(
                    "STALE_PLAN",
                    "supplied plan metadata names a stale planning context",
                )
            metadata = dict(metadata)
            metadata["planning_context"] = planning_context
            metadata["planning_context_sha256"] = planning_context_sha
        final_artifact_hash = _hash_artifact(artifact_path)
        if final_artifact_hash != artifact_hash:
            raise FlowError(
                "ARTIFACT_CHANGED",
                "artifact changed while it was being recorded",
                details={"path": str(artifact_path)},
            )
        state_value = _copy_state(current)
        artifact = {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "artifact_id": str(uuid.uuid4()),
            "kind": args.kind,
            "path": str(artifact_path),
            "path_identity": _serializable_path_identity(artifact_path),
            "sha256": digest,
            "artifact_type": artifact_hash["artifact_type"],
            "size": artifact_hash["size"],
            "file_count": artifact_hash["file_count"],
            "total_size": artifact_hash["total_size"],
            "recorded_at": utc_now(),
            "metadata": metadata,
        }
        if "manifest_entry_count" in artifact_hash:
            artifact["manifest_entry_count"] = artifact_hash["manifest_entry_count"]
        state_value["artifacts"].append(artifact)
        if args.kind == "impact":
            state_value["route"] = None
            state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "artifact_recorded", {"artifact_id": artifact["artifact_id"], "kind": args.kind, "sha256": digest})
    return _result("record-artifact", state_value, artifact=artifact)


def command_set_route(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    route = args.route_option or args.route
    if route not in {"direct", "openspec"}:
        raise FlowError("INVALID_ARGUMENT", "route must be 'direct' or 'openspec'")
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="task.route.set",
    ) as (task_dir, current):
        _assert_flow(current, "full", "set-route")
        _assert_status(current, {"INDEXED", "IMPACT_REVIEW"}, "set-route")
        impact = _require_current_impact(current)
        impact_metadata = impact.get("metadata") or {}
        route_record = {
            "value": route,
            "reason": args.reason,
            "set_at": utc_now(),
            "impact_artifact_id": impact["artifact_id"],
            "impact_sha256": impact["sha256"],
            "index_provenance_sha256": impact_metadata[
                "index_provenance_sha256"
            ],
            "impact_generation": impact_metadata["impact_generation"],
        }
        if (
            _uses_confirmation_contract(current)
            and impact_metadata.get("impact_analysis_sha256") is not None
        ):
            route_record["impact_analysis_sha256"] = (
                impact_metadata["impact_analysis_sha256"]
            )
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            state_value = _v3_command_set_route_commit(
                current,
                task_dir,
                route=route,
                reason=args.reason,
                route_record=route_record,
                impact=impact,
                impact_metadata=impact_metadata,
            )
            return _result(
                "set-route", state_value, route=state_value["route"]
            )
        state_value = _copy_state(current)
        state_value["route"] = route_record
        state_value["status"] = "IMPACT_REVIEW"
        state_value["approvals"].pop("route", None)
        _commit_state(current, state_value, task_dir, "route_set", {"route": route, "reason": args.reason})
    return _result("set-route", state_value, route=state_value["route"])


def command_approve(args: argparse.Namespace) -> dict[str, Any]:
    task_id = _task_arg(args)
    if args.gate not in APPROVAL_GATES:
        # Rejected before the lock so an unknown gate cannot consume a
        # revision or leave a permanent approval behind.
        raise FlowError(
            "INVALID_ARGUMENT",
            "--gate must name a defined approval gate: "
            + ", ".join(APPROVAL_GATES),
            details={"gate": args.gate, "gates": list(APPROVAL_GATES)},
        )
    artifact_sha = args.artifact_sha256
    if artifact_sha and not SHA256_RE.fullmatch(artifact_sha):
        raise FlowError("INVALID_ARGUMENT", "--artifact-sha256 must be 64 lowercase hexadecimal characters")
    with _locked_state(
        task_id,
        args.data_dir,
        args.expected_revision,
        manager_action_id="gate.approve",
    ) as (task_dir, current):
        _assert_status(current, set(ALL_STATES) - TERMINAL_STATES - {"BLOCKED"}, "approve")
        if args.accept_conditional and args.gate != "review":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--accept-conditional is only valid for the review gate",
            )
        if args.allow_fetch and args.gate != "baseline-fetch":
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-fetch is only valid for the baseline-fetch gate",
            )
        if args.allow_dirty and args.gate not in {"baseline-fetch", LITE_GATE}:
            raise FlowError(
                "INVALID_ARGUMENT",
                "--allow-dirty is only valid for the baseline-fetch and lite gates",
            )
        if artifact_sha and not any(item.get("sha256") == artifact_sha for item in current.get("artifacts", [])):
            raise FlowError("ARTIFACT_NOT_FOUND", "approval artifact hash is not recorded on this task", details={"sha256": artifact_sha})
        required_artifact_kind: str | None = None
        review_verdict: str | None = None
        baseline_remote_evidence: dict[str, Any] | None = None
        route_impact: dict[str, Any] | None = None
        plan_artifact: dict[str, Any] | None = None
        plan_context: dict[str, Any] | None = None
        lite_evidence: dict[str, Any] | None = None
        lite_risk_assessment: dict[str, Any] | None = None
        if args.gate in FULL_GATES:
            _assert_flow(current, "full", f"approve --gate {args.gate}")
        if args.gate == "route":
            _assert_status(current, {"IMPACT_REVIEW"}, "approve --gate route")
            _, route_impact = _require_current_route_selection(current)
            required_artifact_kind = "impact"
        elif args.gate == "plan":
            _assert_status(current, {"PLANNING"}, "approve --gate plan")
            route_value = (current.get("route") or {}).get("value")
            if route_value not in {"direct", "openspec"}:
                raise FlowError("ROUTE_REQUIRED", "an approved route is required before plan approval")
            required_artifact_kind = (
                "direct-contract" if route_value == "direct" else "openspec-plan"
            )
            plan_artifact, plan_context = _require_current_plan_artifact(
                current, required_artifact_kind
            )
        elif args.gate == "review":
            _assert_status(current, {"REVIEWING"}, "approve --gate review")
            required_artifact_kind = "review-report"
            review_report, _ = _require_review_report_for_latest_snapshot(current)
            review_verdict = (review_report.get("metadata") or {}).get("verdict")
            if review_verdict not in {"PASS", "CONDITIONAL", "FAIL"}:
                raise FlowError(
                    "INVALID_REVIEW_VERDICT",
                    "latest review report has no valid structured verdict",
                    details={"verdict": review_verdict},
                )
            if review_verdict == "FAIL":
                raise FlowError(
                    "REVIEW_VERDICT_FAILED",
                    "a FAIL review report cannot be approved",
                )
            if review_verdict == "CONDITIONAL" and not args.accept_conditional:
                raise FlowError(
                    "CONDITIONAL_ACCEPTANCE_REQUIRED",
                    "approving a CONDITIONAL review requires --accept-conditional",
                )
            if review_verdict == "PASS" and args.accept_conditional:
                raise FlowError(
                    "INVALID_ARGUMENT",
                    "--accept-conditional is not valid for a PASS review",
                )
        elif args.gate == "baseline-fetch":
            _assert_status(current, {"PREFLIGHTED", "BASELINED"}, "approve --gate baseline-fetch")
            baseline_remote_evidence = _preflight_remote_evidence(current)
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "impact-degraded":
            _assert_status(
                current,
                {"BASELINED", "INDEXED"},
                "approve --gate impact-degraded",
            )
        elif args.gate == LITE_GATE:
            _assert_flow(current, "lite", "approve --gate lite")
            _assert_status(current, {"PREFLIGHTED"}, "approve --gate lite")
            lite_evidence = _lite_preflight_evidence(current)
            if _uses_confirmation_contract(current):
                lite_risk_assessment = _lite_change_assessment(
                    current, args.data_dir
                )
                if lite_risk_assessment["decision"] != "safe":
                    raise FlowError(
                        "LITE_REQUIRES_FULL",
                        "live preflight changes require the full flow",
                        details={
                            "required_flow": "full",
                            "assessment": lite_risk_assessment,
                        },
                    )
            dirty_repositories = [
                repo["id"]
                for repo in current.get("repositories", [])
                if (repo.get("preflight") or {}).get("dirty")
            ]
            if dirty_repositories and not args.allow_dirty:
                raise FlowError(
                    "DIRTY_APPROVAL_REQUIRED",
                    "approving a dirty preflight snapshot requires --allow-dirty",
                    details={"repository_ids": dirty_repositories},
                )
        elif args.gate == "workspace":
            _assert_status(current, {"ROUTE_APPROVED", "WORKSPACE_READY"}, "approve --gate workspace")
            required_artifact_kind = "workspace-plan"
        if required_artifact_kind:
            latest = _latest_artifact(current, required_artifact_kind)
            if not latest:
                raise FlowError(
                    "ARTIFACT_REQUIRED",
                    f"the {args.gate} gate requires a recorded {required_artifact_kind} artifact",
                    details={"gate": args.gate, "artifact_kind": required_artifact_kind},
                )
            _assert_artifact_unchanged(latest)
            if artifact_sha != latest.get("sha256"):
                raise FlowError(
                    "APPROVAL_ARTIFACT_MISMATCH",
                    f"the {args.gate} gate must bind the latest {required_artifact_kind} artifact",
                    details={
                        "gate": args.gate,
                        "artifact_kind": required_artifact_kind,
                        "expected_sha256": latest.get("sha256"),
                        "provided_sha256": artifact_sha,
                    },
                )
            if args.gate == "workspace":
                current_generation = int(
                    (current.get("workspace") or {}).get("generation", 0)
                )
                controller_plan = (
                    (current.get("workspace") or {}).get("plan") or {}
                )
                if (
                    (latest.get("metadata") or {}).get("workspace_generation")
                    != current_generation
                    or controller_plan.get("sha256") != latest.get("sha256")
                    or controller_plan.get("artifact_id")
                    != latest.get("artifact_id")
                    or controller_plan.get("path") != latest.get("path")
                ):
                    raise FlowError(
                        "STALE_WORKSPACE_PLAN",
                        "workspace plan is not current for this workspace generation",
                    )
        route_intent: dict[str, Any] | None = None
        if (
            current.get("schema_version") != V3_TASK_SCHEMA_VERSION
            and args.gate == "route"
            and _uses_confirmation_contract(current)
        ):
            route_intent = _transition_intent_preview(
                current,
                "IMPACT_REVIEW",
                "ROUTE_APPROVED",
                action="approve-route",
                action_parameters={
                    "gate": "route",
                    "note": args.note,
                    "artifact_sha256": artifact_sha,
                    "impact_analysis_sha256": (
                        route_impact.get("metadata") or {}
                    ).get("impact_analysis_sha256"),
                },
            )
        state_value = _copy_state(current)
        approval = {
            "approval_id": str(uuid.uuid4()),
            "gate": args.gate,
            "note": args.note,
            "artifact_sha256": artifact_sha,
            "approved_at": utc_now(),
            "approved_by": _actor(),
        }
        if args.gate == "review":
            approval["review_snapshot_sha256"] = _latest_review_snapshot(current)["sha256"]
            approval["review_verdict"] = review_verdict
            approval["conditional_accepted"] = bool(
                review_verdict == "CONDITIONAL" and args.accept_conditional
            )
        if args.gate == "baseline-fetch":
            approval["preflight_remote_sha256"] = _sha256_bytes(
                _json_bytes(baseline_remote_evidence)
            )
            approval["preflight_remotes"] = baseline_remote_evidence["repositories"]
            approval["fetch_allowed"] = bool(args.allow_fetch)
            approval["dirty_allowed"] = bool(args.allow_dirty)
        if args.gate == LITE_GATE:
            approval["preflight_evidence_sha256"] = _sha256_bytes(
                _json_bytes(lite_evidence)
            )
            approval["preflight_repositories"] = lite_evidence["repositories"]
            approval["dirty_allowed"] = bool(args.allow_dirty)
            if lite_risk_assessment is not None:
                approval["lite_policy_sha256"] = (
                    current["risk_assessment"]["policy_sha256"]
                )
                approval["risk_assessment_sha256"] = (
                    lite_risk_assessment["sha256"]
                )
        if args.gate == "route":
            approval["artifact_id"] = route_impact["artifact_id"]
            approval["index_provenance_sha256"] = (
                route_impact.get("metadata") or {}
            )["index_provenance_sha256"]
            approval["impact_generation"] = (
                route_impact.get("metadata") or {}
            )["impact_generation"]
            impact_analysis_sha = (
                route_impact.get("metadata") or {}
            ).get("impact_analysis_sha256")
            if (
                _uses_confirmation_contract(current)
                and impact_analysis_sha is not None
            ):
                approval["impact_analysis_sha256"] = impact_analysis_sha
            if route_intent is not None:
                approval["intent_id"] = route_intent["intent_id"]
                approval["confirmation_mode"] = "explicit-action"
        if args.gate == "workspace":
            approval["artifact_id"] = latest["artifact_id"]
            approval["workspace_generation"] = (
                latest.get("metadata") or {}
            )["workspace_generation"]
        if args.gate == "plan":
            approval["artifact_id"] = plan_artifact["artifact_id"]
            approval["planning_context_sha256"] = _planning_context_sha256(
                plan_context
            )
        if current.get("schema_version") == V3_TASK_SCHEMA_VERSION:
            state_value, approval = _v3_command_approve_commit(
                current,
                task_dir,
                args,
                approval,
                artifact_sha,
            )
            return _result(
                "approve", state_value, approval=approval
            )
        state_value["approvals"][args.gate] = approval
        if args.gate == "route":
            state_value["status"] = "ROUTE_APPROVED"
        _commit_state(
            current,
            state_value,
            task_dir,
            "gate_approved",
            {
                "gate": args.gate,
                "artifact_sha256": artifact_sha,
                "approval": approval,
                "intent_id": (
                    route_intent["intent_id"]
                    if route_intent is not None
                    else None
                ),
            },
            additional_events=(
                [
                    (
                        "state_transitioned",
                        {
                            "from": "IMPACT_REVIEW",
                            "to": "ROUTE_APPROVED",
                            "intent_id": route_intent["intent_id"],
                            "approval_id": approval["approval_id"],
                            "confirmation_mode": "explicit-action",
                        },
                    )
                ]
                if route_intent is not None
                else None
            ),
        )
    return _result("approve", state_value, approval=approval)
