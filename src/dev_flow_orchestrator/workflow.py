"""Static greenfield workflow graphs and explicit node contracts."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import hashlib
import json
from types import MappingProxyType
from typing import Mapping, Tuple

from .model import DevFlowError, TaskState
from .product import PRODUCT_IDENTITY, uses_repository_kernel


@dataclass(frozen=True)
class NodeContract:
    node_id: str
    action_id: str
    target_node: str
    target_status: str
    required_authority: str
    allowed_state_writes: Tuple[str, ...]
    effect_kind: str
    effect_port: str
    handler_id: str
    output_kind: str
    required_payload_fields: Tuple[str, ...]
    payload_types: Mapping[str, str]
    idempotency_fields: Tuple[str, ...]
    failure_code: str
    recovery_action: str

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "action_id": self.action_id,
            "target_node": self.target_node,
            "target_status": self.target_status,
            "required_authority": self.required_authority,
            "allowed_state_writes": list(self.allowed_state_writes),
            "effect_kind": self.effect_kind,
            "effect_port": self.effect_port,
            "handler_id": self.handler_id,
            "output_kind": self.output_kind,
            "required_payload_fields": list(self.required_payload_fields),
            "payload_types": dict(self.payload_types),
            "idempotency_fields": list(self.idempotency_fields),
            "failure_code": self.failure_code,
            "recovery_action": self.recovery_action,
        }


_COMMON_WRITES = (
    "/current_node",
    "/revision",
    "/status",
    "/updated_at",
)
_EVIDENCE_WRITES = (*_COMMON_WRITES, "/evidence")
_APPROVAL_WRITES = (*_COMMON_WRITES, "/approvals")
_WORKSPACE_WRITES = (
    *_COMMON_WRITES,
    "/effects",
    "/repositories/*/workspace",
)
_PREFLIGHT_WRITES = (
    *_COMMON_WRITES,
    "/repositories/*/preflight",
)


def _node(
    node_id: str,
    action_id: str,
    target_node: str,
    target_status: str,
    *,
    writes: Tuple[str, ...],
    output_kind: str,
    handler_id: str,
    required_fields: Tuple[str, ...],
    payload_types: Mapping[str, str] | None = None,
    effect_kind: str = "none",
    effect_port: str = "none",
    authority: str = "task-revision",
    recovery_action: str = "none",
) -> NodeContract:
    return NodeContract(
        node_id=node_id,
        action_id=action_id,
        target_node=target_node,
        target_status=target_status,
        required_authority=authority,
        allowed_state_writes=writes,
        effect_kind=effect_kind,
        effect_port=effect_port,
        handler_id=handler_id,
        output_kind=output_kind,
        required_payload_fields=required_fields,
        payload_types=MappingProxyType(
            dict(payload_types or {field: "string" for field in required_fields})
        ),
        idempotency_fields=("task_id", "action_id", "expected_revision"),
        failure_code="NODE_OUTPUT_INVALID",
        recovery_action=recovery_action,
    )


PREFLIGHT_CONTRACT = _node(
    "preflight",
    "task.preflight",
    "workflow-entry",
    "PREFLIGHTED",
    writes=_PREFLIGHT_WRITES,
    output_kind="preflight",
    handler_id="preflight",
    required_fields=(),
    effect_kind="git-read",
    effect_port="git.inspect-repository",
    authority="task-revision",
)


FULL_GRAPH: Mapping[str, NodeContract] = MappingProxyType(
    {
        "baseline": _node(
            "baseline",
            "evidence.baseline.record",
            "impact",
            "BASELINED",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("baseline",),
        ),
        "impact": _node(
            "impact",
            "evidence.impact.record",
            "route",
            "IMPACT_REVIEW",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("impact",),
        ),
        "route": _node(
            "route",
            "task.route.set",
            "workspace",
            "ROUTE_APPROVED",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("route", "reason"),
        ),
        "workspace": _node(
            "workspace",
            "workspace.prepare",
            "planning",
            "WORKSPACE_READY",
            writes=_WORKSPACE_WRITES,
            output_kind="workspace",
            handler_id="workspace.attach",
            required_fields=(),
            effect_kind="git-workspace",
            effect_port="git.prepare-workspace",
            authority="task-revision+workspace-mutation",
            recovery_action="effect.inspect",
        ),
        "planning": _node(
            "planning",
            "evidence.plan.record",
            "plan-approval",
            "PLANNING",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("plan",),
        ),
        "plan-approval": _node(
            "plan-approval",
            "gate.plan.approve",
            "implement",
            "IMPLEMENTING",
            writes=_APPROVAL_WRITES,
            output_kind="approval",
            handler_id="approval.record",
            required_fields=("approved",),
            payload_types={"approved": "boolean"},
            authority="task-revision+human-approval",
        ),
        "implement": _node(
            "implement",
            "task.implementation.complete",
            "verify",
            "VERIFYING",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("summary",),
            authority="task-revision+implementer",
        ),
        "verify": _node(
            "verify",
            "evidence.test.record",
            "review",
            "REVIEWING",
            writes=_EVIDENCE_WRITES,
            output_kind="test",
            handler_id="test.record",
            required_fields=("passed", "command"),
            payload_types={"passed": "boolean", "command": "string"},
        ),
        "review": _node(
            "review",
            "evidence.review.record",
            "finalize",
            "FINALIZING",
            writes=_EVIDENCE_WRITES,
            output_kind="review",
            handler_id="review.record",
            required_fields=("verdict", "review_fingerprint"),
            payload_types={
                "verdict": "string",
                "review_fingerprint": "sha256",
            },
            authority="task-revision+independent-review",
        ),
        "finalize": _node(
            "finalize",
            "task.finalize",
            "done",
            "DONE",
            writes=_EVIDENCE_WRITES,
            output_kind="finalization",
            handler_id="evidence.record",
            required_fields=("summary",),
        ),
    }
)

LITE_GRAPH: Mapping[str, NodeContract] = MappingProxyType(
    {
        "implement": _node(
            "implement",
            "task.implementation.complete",
            "verify",
            "VERIFYING",
            writes=_EVIDENCE_WRITES,
            output_kind="evidence",
            handler_id="evidence.record",
            required_fields=("summary",),
            authority="task-revision+implementer",
        ),
        "verify": _node(
            "verify",
            "evidence.test.record",
            "done",
            "DONE",
            writes=_EVIDENCE_WRITES,
            output_kind="test",
            handler_id="test.record",
            required_fields=("passed", "command"),
            payload_types={"passed": "boolean", "command": "string"},
        ),
    }
)

WORKFLOW_GRAPHS = MappingProxyType(
    {
        "full": FULL_GRAPH,
        "lite": LITE_GRAPH,
    }
)

_REPOSITORY_WRITES = (*_COMMON_WRITES, "/orchestration")
REPOSITORY_GRAPH: Mapping[str, NodeContract] = MappingProxyType(
    {
        "repository-plan": _node(
            "repository-plan",
            "repository.plan.record",
            "repository-dispatch",
            "ORCHESTRATING",
            writes=_REPOSITORY_WRITES,
            output_kind="repository-plan",
            handler_id="repository.plan",
            required_fields=("dependencies", "concurrency", "max_retries"),
            payload_types={
                "dependencies": "object",
                "concurrency": "integer",
                "max_retries": "integer",
            },
            authority="task-revision+manager",
        ),
        "repository-dispatch": _node(
            "repository-dispatch",
            "repository.lease.issue",
            "repository-results",
            "ORCHESTRATING",
            writes=_REPOSITORY_WRITES,
            output_kind="repository-dispatch",
            handler_id="repository.dispatch",
            required_fields=(),
        ),
        "repository-results": _node(
            "repository-results",
            "repository.result.accept",
            "repository-results",
            "ORCHESTRATING",
            writes=_REPOSITORY_WRITES,
            output_kind="repository-result",
            handler_id="repository.result",
            required_fields=(
                "repository_id",
                "lease_id",
                "outcome",
                "result_sha256",
            ),
            authority="task-revision+lease-owner",
            effect_kind="git-read",
            effect_port="git.inspect-result-head",
        ),
        "repository-barrier": _node(
            "repository-barrier",
            "repository.barrier.close",
            "repository-integration",
            "ORCHESTRATING",
            writes=_REPOSITORY_WRITES,
            output_kind="repository-barrier",
            handler_id="repository.barrier",
            required_fields=(),
        ),
        "repository-integration": _node(
            "repository-integration",
            "repository.integration.record",
            "implement",
            "IMPLEMENTING",
            writes=_REPOSITORY_WRITES,
            output_kind="repository-integration",
            handler_id="repository.integration",
            required_fields=("integration_sha256",),
        ),
    }
)

REPOSITORY_CANCEL_CONTRACT = _node(
    "repository-shared",
    "repository.cancel",
    "repository-cancelled",
    "CANCELLED",
    writes=_REPOSITORY_WRITES,
    output_kind="repository-cancel",
    handler_id="repository.cancel",
    required_fields=("reason",),
    authority="task-revision+manager",
)


def _entry_contract(workflow_id: str) -> NodeContract:
    return replace(
        PREFLIGHT_CONTRACT,
        target_node=(
            "baseline"
            if workflow_id == "full"
            else "implement"
        ),
        target_status=(
            "PREFLIGHTED"
            if workflow_id == "full"
            else "IMPLEMENTING"
        ),
    )


def _profile_contract(
    contract: NodeContract,
    topology: str,
) -> NodeContract:
    if (
        uses_repository_kernel(topology)
        and contract.target_node == "implement"
        and contract.node_id not in REPOSITORY_GRAPH
    ):
        return replace(
            contract,
            target_node="repository-plan",
            target_status="ORCHESTRATING",
        )
    return contract


def current_contract(state: TaskState) -> NodeContract:
    if state.current_node == PREFLIGHT_CONTRACT.node_id:
        return _profile_contract(
            _entry_contract(state.workflow_id),
            state.topology,
        )
    if state.current_node in REPOSITORY_GRAPH:
        return REPOSITORY_GRAPH[state.current_node]
    graph = WORKFLOW_GRAPHS.get(state.workflow_id)
    if graph is None:
        raise DevFlowError(
            "WORKFLOW_INVALID",
            "task workflow is not installed",
        )
    contract = graph.get(state.current_node)
    if contract is None:
        raise DevFlowError(
            "NO_ACTION_AVAILABLE",
            "current node has no public action",
            details={
                "current_node": state.current_node,
                "status": state.status,
            },
        )
    return _profile_contract(contract, state.topology)


def required_grant(contract: NodeContract) -> str | None:
    parts = contract.required_authority.split("+")
    if not parts or parts[0] != "task-revision" or len(parts) > 2:
        raise DevFlowError(
            "AUTHORITY_CONTRACT_INVALID",
            "node authority contract is invalid",
        )
    return parts[1] if len(parts) == 2 else None


def workflow_identity(workflow_id: str, topology: str) -> str:
    graph = WORKFLOW_GRAPHS.get(workflow_id)
    if graph is None:
        raise DevFlowError("WORKFLOW_INVALID", "workflow is not installed")
    document = {
        "product_identity": PRODUCT_IDENTITY,
        "workflow_id": workflow_id,
        "topology": topology,
        "entry": _profile_contract(
            _entry_contract(workflow_id),
            topology,
        ).as_dict(),
        "nodes": {
            node_id: _profile_contract(contract, topology).as_dict()
            for node_id, contract in sorted(graph.items())
        },
        "repository_nodes": (
            {
                node_id: contract.as_dict()
                for node_id, contract in sorted(REPOSITORY_GRAPH.items())
            }
            if uses_repository_kernel(topology)
            else {}
        ),
        "shared_actions": (
            {
                "repository.cancel": {
                    "contract": REPOSITORY_CANCEL_CONTRACT.as_dict(),
                    "available_at": sorted(REPOSITORY_GRAPH),
                }
            }
            if uses_repository_kernel(topology)
            else {}
        ),
    }
    return hashlib.sha256(
        b"dev-flow-v4-workflow-identity/v1\x00"
        + json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def agent_projection(state: TaskState) -> dict:
    if state.status in {"DONE", "CANCELLED", "BLOCKED"}:
        action = None
    else:
        primary = current_contract(state)
        action = primary.as_dict()
    additional_actions = []
    if action is not None and state.current_node in REPOSITORY_GRAPH:
        additional_actions.append(REPOSITORY_CANCEL_CONTRACT.as_dict())
    frontier = []
    if (
        action is not None
        and state.current_node == "repository-results"
        and state.orchestration is not None
    ):
        leases = state.orchestration.get("leases")
        if isinstance(leases, Mapping):
            for lease in sorted(
                (
                    value
                    for value in leases.values()
                    if isinstance(value, Mapping)
                    and value.get("status") == "ACTIVE"
                ),
                key=lambda value: (
                    str(value.get("repository_id")).encode("utf-8"),
                    int(value.get("attempt", 0)),
                ),
            ):
                instance = dict(action)
                instance["node_instance_id"] = "{}:{}:{}".format(
                    lease.get("repository_id"),
                    lease.get("attempt"),
                    lease.get("lease_id"),
                )
                instance["arguments"] = {
                    "repository_id": lease.get("repository_id"),
                    "lease_id": lease.get("lease_id"),
                    "attempt": lease.get("attempt"),
                    "owner_id": lease.get("owner_id"),
                    "pinned_head": lease.get("pinned_head"),
                }
                frontier.append(instance)
    elif action is not None:
        frontier.append(action)
    return {
        "schema": "dev-flow-agent-v1",
        "task_id": state.task_id,
        "revision": state.revision,
        "workflow": {
            "id": state.workflow_id,
            "version": state.workflow_version,
            "identity": state.workflow_identity,
            "topology": state.topology,
        },
        "status": state.status,
        "current_node": state.current_node,
        "action": action,
        "frontier": frontier,
        "additional_actions": additional_actions,
    }
