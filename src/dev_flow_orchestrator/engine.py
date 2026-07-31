"""Pure current-node eligibility and bounded mutation planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Sequence

from .model import (
    DevFlowError,
    MutationPlan,
    NodeDecision,
    RepositoryRecord,
    TaskState,
    canonical_json_bytes,
)
from .workflow import NodeContract, current_contract
from .workflow import REPOSITORY_CANCEL_CONTRACT, REPOSITORY_GRAPH
from .repository_kernel import (
    accept_result,
    build_plan,
    cancel_plan,
    close_barrier,
    issue_ready_leases,
    record_integration,
)


def decide_preflight(
    state: TaskState,
    expected_revision: int,
) -> NodeDecision:
    if state.revision != expected_revision:
        raise DevFlowError(
            "REVISION_CONFLICT",
            "task revision is stale",
            details={
                "task_id": state.task_id,
                "expected_revision": expected_revision,
                "actual_revision": state.revision,
            },
        )
    if state.status != "INTAKE" or state.current_node != "preflight":
        raise DevFlowError(
            "ACTION_NOT_AVAILABLE",
            "preflight is not available at the current node",
            details={
                "status": state.status,
                "current_node": state.current_node,
            },
        )
    contract = current_contract(state)
    plan = MutationPlan(
        action_id=contract.action_id,
        task_id=state.task_id,
        expected_revision=expected_revision,
        source_node=state.current_node,
        target_node=contract.target_node,
        effect_kind=contract.effect_kind,
        allowed_writes=contract.allowed_state_writes,
    )
    return NodeDecision(
        action_id=plan.action_id,
        eligible=True,
        reason=None,
        plan=plan,
    )


def plan_preflight(state: TaskState, expected_revision: int) -> MutationPlan:
    decision = decide_preflight(state, expected_revision)
    if not decision.eligible or decision.plan is None:
        raise DevFlowError(
            "ACTION_NOT_AVAILABLE",
            decision.reason or "preflight is not eligible",
        )
    return decision.plan


def apply_preflight(
    state: TaskState,
    plan: MutationPlan,
    evidence: Mapping[str, Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    current_plan = plan_preflight(state, plan.expected_revision)
    if current_plan != plan:
        raise DevFlowError(
            "PLAN_BINDING_MISMATCH",
            "preflight plan is no longer current",
        )
    contract = current_contract(state)
    expected_ids = {
        repository.repository_id
        for repository in state.repositories
    }
    if set(evidence) != expected_ids:
        raise DevFlowError(
            "PREFLIGHT_EVIDENCE_INVALID",
            "preflight evidence does not cover the exact repository set",
        )
    repositories = tuple(
        RepositoryRecord(
            repository.repository_id,
            repository.path,
            evidence[repository.repository_id],
            repository.workspace,
        )
        for repository in state.repositories
    )
    return TaskState(
        task_id=state.task_id,
        requirement=state.requirement,
        revision=state.revision + 1,
        created_at=state.created_at,
        updated_at=timestamp,
        workflow_id=state.workflow_id,
        workflow_version=state.workflow_version,
        workflow_identity=state.workflow_identity,
        topology=state.topology,
        workspace_strategy=state.workspace_strategy,
        required_suites=state.required_suites,
        status=contract.target_status,
        current_node=plan.target_node,
        repositories=repositories,
        approvals=state.approvals,
        evidence=state.evidence,
        effects=state.effects,
    )


def validate_write_set(
    plan: MutationPlan,
    writes: Sequence[str],
) -> None:
    undeclared = sorted(set(writes) - set(plan.allowed_writes))
    if undeclared:
        raise DevFlowError(
            "STATE_WRITE_UNDECLARED",
            "mutation plan contains an undeclared state write",
            details={"writes": undeclared},
        )


def plan_current_action(
    state: TaskState,
    action_id: str,
    expected_revision: int,
    *,
    authority_id: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> tuple:
    if state.revision != expected_revision:
        raise DevFlowError(
            "REVISION_CONFLICT",
            "task revision is stale",
            details={
                "task_id": state.task_id,
                "expected_revision": expected_revision,
                "actual_revision": state.revision,
            },
        )
    if (
        action_id == REPOSITORY_CANCEL_CONTRACT.action_id
        and state.current_node in REPOSITORY_GRAPH
    ):
        contract = replace(
            REPOSITORY_CANCEL_CONTRACT,
            node_id=state.current_node,
        )
    else:
        contract = current_contract(state)
    if contract.action_id != action_id:
        raise DevFlowError(
            "ACTION_NOT_AVAILABLE",
            "action is not available at the current node",
            details={
                "action_id": action_id,
                "current_node": state.current_node,
                "expected_action_id": contract.action_id,
            },
        )
    plan = MutationPlan(
        action_id=contract.action_id,
        task_id=state.task_id,
        expected_revision=expected_revision,
        source_node=contract.node_id,
        target_node=contract.target_node,
        effect_kind=contract.effect_kind,
        allowed_writes=contract.allowed_state_writes,
        authority_id=authority_id,
        actor_id=actor_id,
    )
    return contract, plan


def validate_action_payload(
    contract: NodeContract,
    payload: Optional[Mapping[str, object]],
) -> Mapping[str, object]:
    value = dict(payload or {})
    missing = [
        field
        for field in contract.required_payload_fields
        if field not in value
    ]
    if missing:
        raise DevFlowError(
            contract.failure_code,
            "node output is incomplete",
            details={"missing_fields": missing},
        )
    unknown = sorted(set(value) - set(contract.payload_types))
    if unknown:
        raise DevFlowError(
            contract.failure_code,
            "node output contains undeclared fields",
            details={"unknown_fields": unknown},
        )
    if len(canonical_json_bytes(value)) > 16 * 1024:
        raise DevFlowError(
            contract.failure_code,
            "node output exceeds the bounded payload budget",
        )
    for field, expected_type in contract.payload_types.items():
        if field not in value:
            continue
        item = value[field]
        valid = (
            expected_type == "string"
            and isinstance(item, str)
            and 0 < len(item.encode("utf-8")) <= 8192
        ) or (
            expected_type == "boolean"
            and isinstance(item, bool)
        ) or (
            expected_type == "integer"
            and isinstance(item, int)
            and not isinstance(item, bool)
        ) or (
            expected_type == "object"
            and isinstance(item, dict)
        ) or (
            expected_type == "sha256"
            and isinstance(item, str)
            and re.fullmatch(r"[0-9a-f]{64}", item) is not None
        )
        if not valid:
            raise DevFlowError(
                contract.failure_code,
                "node output field has the wrong type or size",
                details={"field": field, "expected_type": expected_type},
            )
    return MappingProxyType(value)


NodeHandler = Callable[
    [
        TaskState,
        NodeContract,
        MutationPlan,
        Mapping[str, object],
        Optional[Mapping[str, object]],
        str,
    ],
    TaskState,
]


@dataclass(frozen=True)
class NodeFamily:
    """Direct pure handler and declared external effect port for one node family."""

    handler: NodeHandler
    effect_port: str


def _record(
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    timestamp: str,
) -> dict:
    return {
        "schema": "dev-flow-v4-node-output/v1",
        "action_id": contract.action_id,
        "node_id": contract.node_id,
        "recorded_at": timestamp,
        "authority_id": plan.authority_id,
        "actor_id": plan.actor_id,
        "payload": dict(output),
    }


def _transition(
    state: TaskState,
    contract: NodeContract,
    timestamp: str,
    **changes,
) -> TaskState:
    return replace(
        state,
        revision=state.revision + 1,
        updated_at=timestamp,
        status=changes.pop("status", contract.target_status),
        current_node=changes.pop("current_node", contract.target_node),
        **changes,
    )


def _record_evidence(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    return _transition(
        state,
        contract,
        timestamp,
        evidence=(*state.evidence, _record(contract, plan, output, timestamp)),
    )


def _record_approval(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    if output.get("approved") is not True:
        raise DevFlowError(
            "APPROVAL_REQUIRED",
            "node requires explicit approval",
        )
    return _transition(
        state,
        contract,
        timestamp,
        approvals=(*state.approvals, _record(contract, plan, output, timestamp)),
    )


def _record_test(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    if output.get("passed") is not True:
        raise DevFlowError(
            "TEST_NOT_PASSING",
            "current test evidence is not passing",
        )
    return _record_evidence(state, contract, plan, output, None, timestamp)


def _record_review(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    if output.get("verdict") != "PASS":
        raise DevFlowError(
            "REVIEW_NOT_PASSING",
            "independent review verdict must be PASS",
        )
    return _record_evidence(state, contract, plan, output, None, timestamp)


def _attach_workspace(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del output
    if effect_result is None:
        raise DevFlowError(
            "EFFECT_RECEIPT_REQUIRED",
            "workspace node requires its Git effect receipt",
        )
    workspace_records = effect_result.get("repositories")
    if not isinstance(workspace_records, Mapping):
        raise DevFlowError(
            "EFFECT_RECEIPT_INVALID",
            "workspace receipt does not cover repositories",
        )
    repositories = tuple(
        replace(
            repository,
            workspace=workspace_records.get(repository.repository_id),
        )
        for repository in state.repositories
    )
    if any(repository.workspace is None for repository in repositories):
        raise DevFlowError(
            "EFFECT_RECEIPT_INVALID",
            "workspace receipt does not cover the exact repository set",
        )
    effect = {
        "schema": "dev-flow-v4-effect-summary/v1",
        "action_id": contract.action_id,
        "authority_id": plan.authority_id,
        "execution_id": effect_result.get("execution_id"),
        "receipt": dict(effect_result),
    }
    return _transition(
        state,
        contract,
        timestamp,
        repositories=repositories,
        effects=(*state.effects, effect),
    )


def _record_repository_plan(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    if plan.actor_id is None:
        raise DevFlowError(
            "AUTHORITY_REQUIRED",
            "repository ownership requires a host-confirmed principal",
        )
    orchestration = build_plan(
        [repository.repository_id for repository in state.repositories],
        output.get("dependencies"),
        plan.actor_id,
        {
            repository.repository_id: (
                repository.preflight or {}
            ).get("head")
            for repository in state.repositories
        },
        output.get("concurrency"),
        output.get("max_retries"),
    )
    orchestration["authority_id"] = plan.authority_id
    return _transition(
        state,
        contract,
        timestamp,
        orchestration=orchestration,
    )


def _require_orchestration(state: TaskState) -> Mapping[str, object]:
    if state.orchestration is None:
        raise DevFlowError(
            "REPOSITORY_STATE_INVALID",
            "repository plan has not been recorded",
        )
    return state.orchestration


def _dispatch_repositories(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del plan, output, effect_result
    orchestration = issue_ready_leases(_require_orchestration(state))
    if not any(
        lease.get("status") == "ACTIVE"
        for lease in orchestration["leases"].values()
    ):
        raise DevFlowError(
            "REPOSITORY_DISPATCH_EMPTY",
            "repository plan has no ready lease",
        )
    return _transition(
        state,
        contract,
        timestamp,
        orchestration=orchestration,
    )


def _accept_repository_result(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    orchestration = accept_result(
        _require_orchestration(state),
        repository_id=output.get("repository_id"),
        lease_id=output.get("lease_id"),
        outcome=output.get("outcome"),
        result_sha256=output.get("result_sha256"),
        actor_id=plan.actor_id,
        authority_id=plan.authority_id,
        observed_head=(
            None
            if effect_result is None
            else effect_result.get("observed_head")
        ),
    )
    target_node = contract.target_node
    target_status = contract.target_status
    if orchestration.get("status") == "BARRIER_READY":
        target_node = "repository-barrier"
    elif orchestration.get("status") == "BLOCKED":
        target_status = "BLOCKED"
    return _transition(
        state,
        contract,
        timestamp,
        current_node=target_node,
        status=target_status,
        orchestration=orchestration,
    )


def _close_repository_barrier(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del plan, output, effect_result
    return _transition(
        state,
        contract,
        timestamp,
        orchestration=close_barrier(_require_orchestration(state)),
    )


def _record_repository_integration(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del plan, effect_result
    return _transition(
        state,
        contract,
        timestamp,
        orchestration=record_integration(
            _require_orchestration(state),
            output.get("integration_sha256"),
        ),
    )


def _cancel_repositories(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    output: Mapping[str, object],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    del effect_result
    return _transition(
        state,
        contract,
        timestamp,
        orchestration=cancel_plan(
            _require_orchestration(state),
            output.get("reason"),
            authority_id=plan.authority_id,
        ),
    )


NODE_FAMILY_CATALOG = MappingProxyType(
    {
        "preflight": NodeFamily(apply_preflight, "git.inspect-repository"),
        "evidence.record": NodeFamily(_record_evidence, "none"),
        "approval.record": NodeFamily(_record_approval, "none"),
        "test.record": NodeFamily(_record_test, "none"),
        "review.record": NodeFamily(_record_review, "none"),
        "workspace.attach": NodeFamily(
            _attach_workspace,
            "git.prepare-workspace",
        ),
        "repository.plan": NodeFamily(_record_repository_plan, "none"),
        "repository.dispatch": NodeFamily(_dispatch_repositories, "none"),
        "repository.result": NodeFamily(
            _accept_repository_result,
            "git.inspect-result-head",
        ),
        "repository.barrier": NodeFamily(_close_repository_barrier, "none"),
        "repository.integration": NodeFamily(
            _record_repository_integration,
            "none",
        ),
        "repository.cancel": NodeFamily(_cancel_repositories, "none"),
    }
)


def apply_current_action(
    state: TaskState,
    contract: NodeContract,
    plan: MutationPlan,
    *,
    payload: Optional[Mapping[str, object]],
    effect_result: Optional[Mapping[str, object]],
    timestamp: str,
) -> TaskState:
    current_contract_value, current_plan = plan_current_action(
        state,
        plan.action_id,
        plan.expected_revision,
        authority_id=plan.authority_id,
        actor_id=plan.actor_id,
    )
    if current_contract_value != contract or current_plan != plan:
        raise DevFlowError(
            "PLAN_BINDING_MISMATCH",
            "node action plan is no longer current",
        )
    output = validate_action_payload(contract, payload)
    family = NODE_FAMILY_CATALOG.get(contract.handler_id)
    if family is None or family.effect_port != contract.effect_port:
        raise DevFlowError(
            "NODE_BINDING_INVALID",
            "node handler or effect port is not installed",
            details={
                "handler_id": contract.handler_id,
                "effect_port": contract.effect_port,
            },
        )
    return family.handler(
        state,
        contract,
        plan,
        output,
        effect_result,
        timestamp,
    )
