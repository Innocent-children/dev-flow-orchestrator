"""Declarative workflow definitions: loading rules and node contracts.

A workflow has one deterministic normal path from its entry to a terminal
node, plus an optional shared cancel action that may target a terminal node.
The runtime executes exactly one action per non-terminal node, then moves to
the node's single target. Everything else -- payload schemas, effects,
external drivers, authority -- is declared data, not runtime branches.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .model import (
    TASK_ID_PATTERN,
    DevFlowError,
    TaskState,
    canonical_json_bytes,
    freeze_json,
    json_value,
)
from .product import PRODUCT_IDENTITY, TASK_SCHEMA_VERSION


SCHEMA = "dev-flow-workflow/v1"
PAYLOAD_TYPE_VOCABULARY = ("string", "boolean", "integer", "object", "sha256")
HANDLER_IDS = ("preflight", "evidence.record", "test.record")
EFFECT_PORTS = ("none", "git.inspect-repository")

_COMMON_WRITES = (
    "/current_node",
    "/revision",
    "/status",
    "/updated_at",
)
_EVIDENCE_WRITES = (*_COMMON_WRITES, "/evidence")
_PREFLIGHT_WRITES = (*_COMMON_WRITES, "/repositories/*/preflight")
_HANDLER_WRITES = MappingProxyType(
    {
        "preflight": _PREFLIGHT_WRITES,
        "evidence.record": _EVIDENCE_WRITES,
        "test.record": _EVIDENCE_WRITES,
    }
)
_HANDLER_EFFECT_PORTS = MappingProxyType(
    {
        "preflight": ("git.inspect-repository",),
        "evidence.record": ("none",),
        "test.record": ("none",),
    }
)


def _workflow_error(source: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(
        "WORKFLOW_INVALID",
        message,
        details={"path": source, **details},
    )


@dataclass(frozen=True)
class NodeContract:
    """One declared node: what action advances it and where it lands."""

    node_id: str
    action_id: str
    target_node: Optional[str]
    target_status: Optional[str]
    handler_id: str
    effect_port: str
    allowed_state_writes: Tuple[str, ...]
    payload_types: Mapping[str, str]
    driver: Optional[Mapping[str, object]] = None
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if self.driver is not None:
            object.__setattr__(self, "driver", freeze_json(self.driver))

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "action_id": self.action_id,
            "target": (
                {
                    "node": self.target_node,
                    "status": self.target_status,
                }
                if self.target_node is not None
                else None
            ),
            "handler": self.handler_id,
            "payload": dict(self.payload_types),
            "writes": list(self.allowed_state_writes),
            "driver": (
                None
                if self.driver is None
                else json_value(self.driver)
            ),
            "description": self.description,
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """A validated workflow graph plus its pinned identity."""

    workflow_id: str
    version: int
    schema: str
    document: Mapping[str, object]
    entry_node: str
    nodes: Mapping[str, NodeContract]
    terminal_nodes: Tuple[str, ...]
    cancel_contract: Optional[NodeContract]
    identity: str


def workflow_identity(workflow_id: str, document: Mapping[str, object]) -> str:
    """Deterministic identity of a workflow definition.

    The identity binds the product identity, the selection token, and the
    canonicalized document. Tasks pin this digest at creation; loading
    recomputes it and rejects drift, so editing a workflow file after a
    task started fails fast instead of silently changing the flow.
    """
    value = {
        "product_identity": PRODUCT_IDENTITY,
        "workflow_id": workflow_id,
        "document": document,
    }
    return hashlib.sha256(
        b"dev-flow-v5-workflow-identity/v1\x00" + canonical_json_bytes(value)
    ).hexdigest()


def _node_spec_error(source: str, node_id: str, message: str) -> DevFlowError:
    return _workflow_error(source, message, node_id=node_id)


def _payload_types(
    source: str,
    node_id: str,
    payload: object,
    *,
    handler: str,
) -> Mapping[str, str]:
    if payload is None:
        return MappingProxyType({})
    if not isinstance(payload, Mapping):
        raise _node_spec_error(source, node_id, "payload must be a mapping")
    types = {}
    for field, field_type in payload.items():
        if not isinstance(field, str) or not field:
            raise _node_spec_error(
                source, node_id, "payload field names must be non-empty strings"
            )
        if field_type not in PAYLOAD_TYPE_VOCABULARY:
            raise _node_spec_error(
                source,
                node_id,
                "payload field {!r} has unknown type {!r}; expected one of {}".format(
                    field, field_type, ", ".join(PAYLOAD_TYPE_VOCABULARY)
                ),
            )
        types[field] = field_type
    if handler == "preflight" and types:
        raise _node_spec_error(
            source, node_id, "the preflight node records Git evidence and takes no payload"
        )
    if handler == "test.record" and types.get("passed") != "boolean":
        raise _node_spec_error(
            source,
            node_id,
            "the test.record node must declare payload 'passed: boolean'",
        )
    return MappingProxyType(types)


def _declared_writes(source: str, node_id: str, writes: object, handler: str) -> Tuple[str, ...]:
    expected = _HANDLER_WRITES[handler]
    if writes is None:
        return expected
    if not isinstance(writes, list) or tuple(writes) != expected:
        raise _node_spec_error(
            source,
            node_id,
            "declared writes must be exactly {}".format(", ".join(expected)),
        )
    return tuple(writes)


def _declared_effect(source: str, node_id: str, effect: object, handler: str) -> str:
    expected = _HANDLER_EFFECT_PORTS[handler]
    if effect is None:
        return expected[0]
    if not isinstance(effect, str) or effect not in expected:
        raise _node_spec_error(
            source,
            node_id,
            "handler {!r} supports only effect(s) {}".format(
                handler, ", ".join(expected)
            ),
        )
    return effect


def _declared_authority(source: str, node_id: str, authority: object) -> None:
    if authority is not None and authority != "task-revision":
        raise _node_spec_error(
            source,
            node_id,
            "authority values other than 'task-revision' are not supported "
            "by this runtime yet; conversation approvals arrive in a later slice",
        )


def _declared_driver(source: str, node_id: str, driver: object) -> Optional[Mapping[str, object]]:
    if driver is None:
        return None
    if not isinstance(driver, Mapping):
        raise _node_spec_error(source, node_id, "driver must be a mapping")
    for key, item in driver.items():
        if not isinstance(key, str):
            raise _node_spec_error(source, node_id, "driver keys must be strings")
        if key == "tool" and (not isinstance(item, str) or not item):
            raise _node_spec_error(
                source, node_id, "driver.tool must be a non-empty string"
            )
    return dict(driver)


def _node_contract(
    source: str,
    node_id: str,
    spec: object,
    *,
    entry: str,
    node_ids: Tuple[str, ...],
    shared_action: bool = False,
) -> NodeContract:
    if not isinstance(spec, Mapping):
        raise _node_spec_error(source, node_id, "node must be a mapping")
    allowed = {
        "action_id",
        "handler",
        "target",
        "terminal",
        "payload",
        "writes",
        "effect",
        "authority",
        "driver",
        "description",
    }
    unknown = sorted(str(key) for key in spec if key not in allowed)
    if unknown:
        raise _node_spec_error(
            source,
            node_id,
            "unknown node field(s): {}".format(", ".join(unknown)),
        )
    if spec.get("terminal") is True:
        for field in ("action_id", "handler", "target", "payload", "writes", "effect", "authority", "driver"):
            if field in spec:
                raise _node_spec_error(
                    source, node_id, "terminal node must not declare {!r}".format(field)
                )
        description = spec.get("description")
        if description is not None and not isinstance(description, str):
            raise _node_spec_error(source, node_id, "description must be a string")
        return NodeContract(
            node_id=node_id,
            action_id="",
            target_node=None,
            target_status=None,
            handler_id="",
            effect_port="none",
            allowed_state_writes=(),
            payload_types=MappingProxyType({}),
            description=description,
        )
    if spec.get("terminal") not in (None, False):
        raise _node_spec_error(source, node_id, "terminal must be a boolean")
    action_id = spec.get("action_id")
    handler = spec.get("handler")
    if not isinstance(action_id, str) or not action_id:
        raise _node_spec_error(source, node_id, "action_id is required")
    if not isinstance(handler, str) or handler not in HANDLER_IDS:
        raise _node_spec_error(
            source,
            node_id,
            "handler must be one of {}".format(", ".join(HANDLER_IDS)),
        )
    target = spec.get("target")
    if not isinstance(target, Mapping):
        raise _node_spec_error(source, node_id, "target is required")
    target_node = target.get("node")
    target_status = target.get("status")
    if not isinstance(target_node, str) or target_node not in node_ids:
        raise _node_spec_error(
            source, node_id, "target.node must be a declared node"
        )
    if not isinstance(target_status, str) or not target_status:
        raise _node_spec_error(source, node_id, "target.status is required")
    if target_node == node_id and not shared_action:
        raise _node_spec_error(source, node_id, "node must not target itself")
    _declared_authority(source, node_id, spec.get("authority"))
    description = spec.get("description")
    if description is not None and not isinstance(description, str):
        raise _node_spec_error(source, node_id, "description must be a string")
    return NodeContract(
        node_id=node_id,
        action_id=action_id,
        target_node=target_node,
        target_status=target_status,
        handler_id=handler,
        effect_port=_declared_effect(source, node_id, spec.get("effect"), handler),
        allowed_state_writes=_declared_writes(
            source, node_id, spec.get("writes"), handler
        ),
        payload_types=_payload_types(
            source, node_id, spec.get("payload"), handler=handler
        ),
        driver=_declared_driver(source, node_id, spec.get("driver")),
        description=description,
    )


def _validate_cancel_contract(
    source: str,
    contract: NodeContract,
    *,
    action_ids: Tuple[str, ...],
    terminal_nodes: Tuple[str, ...],
) -> None:
    if contract.handler_id != "evidence.record":
        raise _workflow_error(
            source,
            "the cancel action must use the evidence.record handler",
            node_id="cancel",
        )
    if contract.action_id in action_ids:
        raise _workflow_error(
            source,
            "cancel action_id must differ from node action_ids",
            node_id="cancel",
        )
    if dict(contract.payload_types) != {"reason": "string"}:
        raise _workflow_error(
            source,
            "cancel payload must be exactly reason: string",
            node_id="cancel",
            payload=dict(contract.payload_types),
        )
    if contract.target_node not in terminal_nodes:
        raise _workflow_error(
            source,
            "cancel target must be a terminal node",
            node_id="cancel",
            target_node=contract.target_node,
        )
    if contract.target_status != "CANCELLED":
        raise _workflow_error(
            source,
            "cancel target.status must be exactly 'CANCELLED'",
            node_id="cancel",
            target_node=contract.target_node,
            expected_status="CANCELLED",
        )


def _trace_normal_path(
    source: str,
    entry: str,
    contracts: Mapping[str, NodeContract],
    terminal_nodes: Tuple[str, ...],
) -> Tuple[str, ...]:
    """Return the unique entry-to-terminal path or reject a cycle."""
    path = []
    positions = {}
    node_id = entry
    while True:
        if node_id in positions:
            cycle = path[positions[node_id]:] + [node_id]
            raise _workflow_error(
                source,
                "normal workflow path must not contain a cycle",
                node_id=node_id,
                cycle=cycle,
            )
        positions[node_id] = len(path)
        path.append(node_id)
        if node_id in terminal_nodes:
            return tuple(path)
        target = contracts[node_id].target_node
        if target is None:
            raise _workflow_error(
                source,
                "normal workflow path ended outside a terminal node",
                node_id=node_id,
            )
        node_id = target


def validate_definition_document(
    document: object,
    *,
    workflow_id: str,
    source: str,
) -> WorkflowDefinition:
    """Validate a parsed workflow document and build its definition.

    Pure function: performs no filesystem, process, or network I/O.
    Every violation raises ``DevFlowError("WORKFLOW_INVALID", ...)`` with
    the offending node in ``details``.
    """
    if not isinstance(document, Mapping):
        raise _workflow_error(source, "workflow document must be a mapping")
    allowed_top = {"schema", "id", "version", "description", "entry", "nodes", "cancel"}
    unknown = sorted(str(key) for key in document if key not in allowed_top)
    if unknown:
        raise _workflow_error(
            source,
            "unknown workflow field(s): {}".format(", ".join(unknown)),
        )
    if document.get("schema") != SCHEMA:
        raise _workflow_error(
            source,
            "schema must be exactly {!r}".format(SCHEMA),
        )
    declared_id = document.get("id")
    if not isinstance(declared_id, str) or not TASK_ID_PATTERN.fullmatch(declared_id):
        raise _workflow_error(
            source,
            "id must be 1-64 characters using letters, digits, '.', '_' or '-'",
        )
    version = document.get("version")
    if version != TASK_SCHEMA_VERSION:
        raise _workflow_error(
            source,
            "version must be current schema v{}".format(TASK_SCHEMA_VERSION),
        )
    description = document.get("description")
    if description is not None and not isinstance(description, str):
        raise _workflow_error(source, "description must be a string")
    entry = document.get("entry")
    nodes_value = document.get("nodes")
    if not isinstance(entry, str) or not entry:
        raise _workflow_error(source, "entry is required")
    if not isinstance(nodes_value, Mapping) or not nodes_value:
        raise _workflow_error(source, "nodes must be a non-empty mapping")
    node_ids = tuple(nodes_value)
    if entry not in node_ids:
        raise _workflow_error(source, "entry node {!r} is not declared".format(entry))
    contracts: dict = {}
    for node_id in node_ids:
        contracts[node_id] = _node_contract(
            source, node_id, nodes_value[node_id], entry=entry, node_ids=node_ids
        )
    if contracts[entry].handler_id != "preflight":
        raise _workflow_error(
            source,
            "the entry node must use the preflight handler (Git evidence entry)",
            entry=entry,
        )
    preflight_nodes = [
        node_id
        for node_id in node_ids
        if contracts[node_id].handler_id == "preflight"
    ]
    if len(preflight_nodes) != 1:
        raise _workflow_error(
            source,
            "exactly one preflight node (the entry) is allowed",
            preflight_nodes=preflight_nodes,
        )
    terminal_nodes = tuple(
        node_id for node_id in node_ids if contracts[node_id].target_node is None
    )
    if not terminal_nodes:
        raise _workflow_error(source, "at least one terminal node is required")
    action_ids = [
        contract.action_id
        for contract in contracts.values()
        if contract.action_id
    ]
    if len(action_ids) != len(set(action_ids)):
        raise _workflow_error(source, "action_id values must be unique")
    cancel_contract = None
    cancel_spec = document.get("cancel")
    if cancel_spec is not None:
        cancel_contract = _node_contract(
            source,
            "cancel",
            cancel_spec,
            entry=entry,
            node_ids=node_ids,
            shared_action=True,
        )
        _validate_cancel_contract(
            source,
            cancel_contract,
            action_ids=tuple(action_ids),
            terminal_nodes=terminal_nodes,
        )
    normal_path = _trace_normal_path(source, entry, contracts, terminal_nodes)
    reached = set(normal_path)
    if cancel_contract is not None:
        reached.add(cancel_contract.target_node)
    unreachable = [node_id for node_id in node_ids if node_id not in reached]
    if unreachable:
        raise _workflow_error(
            source,
            "node(s) not reachable from the entry: {}".format(", ".join(unreachable)),
        )
    return WorkflowDefinition(
        workflow_id=workflow_id,
        version=version,
        schema=SCHEMA,
        document=freeze_json(dict(document)),
        entry_node=entry,
        nodes=MappingProxyType(contracts),
        terminal_nodes=terminal_nodes,
        cancel_contract=cancel_contract,
        identity=workflow_identity(workflow_id, document),
    )


def is_terminal_state(state: TaskState, definition: WorkflowDefinition) -> bool:
    """Return whether the task's current node is terminal for its workflow."""
    return state.current_node in definition.terminal_nodes


def current_contract(state: TaskState, definition: WorkflowDefinition) -> NodeContract:
    if is_terminal_state(state, definition):
        raise DevFlowError(
            "NO_ACTION_AVAILABLE",
            "current node has no public action",
            details={
                "current_node": state.current_node,
                "status": state.status,
            },
        )
    contract = definition.nodes.get(state.current_node)
    if contract is None:
        raise DevFlowError(
            "NO_ACTION_AVAILABLE",
            "current node has no public action",
            details={
                "current_node": state.current_node,
                "status": state.status,
            },
        )
    return contract


def agent_projection(state: TaskState, definition: WorkflowDefinition) -> dict:
    """The agent-v1 projection: exactly one thing to do next."""
    repository = state.repositories[0]
    repo_context = {
        "repository_id": repository.repository_id,
        "path": repository.path,
        "preflight": (
            None
            if repository.preflight is None
            else json_value(repository.preflight)
        ),
    }
    terminal = is_terminal_state(state, definition)
    action = None
    if not terminal:
        action = current_contract(state, definition).as_dict()
    return {
        "schema": "dev-flow-agent-v1",
        "task_id": state.task_id,
        "requirement": state.requirement,
        "revision": state.revision,
        "workflow": {
            "id": state.workflow_id,
            "version": state.workflow_version,
            "identity": state.workflow_identity,
        },
        "status": state.status,
        "current_node": state.current_node,
        "repo_context": repo_context,
        "action": action,
        "done": terminal,
    }
