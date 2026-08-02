"""Workflow language validation and immutable node contracts.

Workflow-v1 remains an accepted absolute-path compatibility language.  Its
linear version-5 document is kept verbatim for identity purposes and adapted
to the V6 record boundary.  Workflow-v2 is the official version-6 language:
it declares typed artifact lineage, a contract-revision re-entry node, and
finite verification/review rework edges.

Validation is pure.  Drivers are descriptive metadata and are never imported
or executed here.
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
from .product import (
    WORKFLOW_V1_ADAPTER_IDENTITY,
    WORKFLOW_V2_ADAPTER_IDENTITY,
    WORKFLOW_VERSION,
)


SCHEMA_V1 = "dev-flow-workflow/v1"
SCHEMA_V2 = "dev-flow-workflow/v2"
SCHEMA = SCHEMA_V2
V1_VERSION = 5
V2_VERSION = WORKFLOW_VERSION

PAYLOAD_TYPE_VOCABULARY = ("string", "boolean", "integer", "object", "sha256")
INPUT_EDGE_KINDS = ("governing", "source-predecessor", "causal")
WORKSPACE_ROLES = ("context", "produces-source", "verifies-source")
FINALIZE_OUTCOMES = ("success", "incomplete")

V1_HANDLER_IDS = ("preflight", "evidence.record", "test.record")
V2_HANDLER_IDS = (
    "preflight",
    "artifact.record",
    "verification.record",
    "review.record",
    "delivery.finalize",
)
HANDLER_IDS = tuple(dict.fromkeys((*V1_HANDLER_IDS, *V2_HANDLER_IDS)))
ASSURANCE_HANDLER_IDS = ("verification.record", "review.record")
EFFECT_PORTS = ("none", "git.inspect-repository")

_COMMON_WRITES = (
    "/current_node",
    "/revision",
    "/status",
    "/updated_at",
)
_RECORD_WRITES = (*_COMMON_WRITES, "/records")
_V1_DECLARED_WRITES = MappingProxyType(
    {
        "preflight": (*_COMMON_WRITES, "/repositories/*/preflight"),
        "evidence.record": (*_COMMON_WRITES, "/evidence"),
        "test.record": (*_COMMON_WRITES, "/evidence"),
    }
)
_HANDLER_EFFECT_PORTS = MappingProxyType(
    {
        handler: (("git.inspect-repository",) if handler == "preflight" else ("none",))
        for handler in HANDLER_IDS
    }
)


def _workflow_error(source: str, message: str, **details: object) -> DevFlowError:
    return DevFlowError(
        "WORKFLOW_INVALID",
        message,
        details={"path": source, **details},
    )


@dataclass(frozen=True)
class InputContract:
    """One typed artifact dependency declared by a workflow node."""

    artifact_type: str
    edge_kind: str

    def as_dict(self) -> dict:
        return {"type": self.artifact_type, "edge": self.edge_kind}


@dataclass(frozen=True)
class ArtifactContract:
    """The artifact produced by a node and its workspace authority."""

    artifact_type: str
    workspace_role: str
    inputs: Tuple[InputContract, ...]

    def as_dict(self) -> dict:
        return {
            "type": self.artifact_type,
            "workspace": self.workspace_role,
            "inputs": [item.as_dict() for item in self.inputs],
        }


@dataclass(frozen=True)
class ReworkContract:
    """Finite failure routing for one verification or review node."""

    failure_node: str
    failure_status: str
    max_attempts: int
    exhausted_node: str
    exhausted_status: str

    def as_dict(self) -> dict:
        return {
            "failure": {
                "node": self.failure_node,
                "status": self.failure_status,
            },
            "max_attempts": self.max_attempts,
            "exhausted": {
                "node": self.exhausted_node,
                "status": self.exhausted_status,
            },
        }


@dataclass(frozen=True)
class NodeContract:
    """One declared action, its normal target, and optional V2 contracts."""

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
    artifact: Optional[ArtifactContract] = None
    rework: Optional[ReworkContract] = None
    finalize_outcome: Optional[str] = None

    def __post_init__(self) -> None:
        if self.driver is not None:
            object.__setattr__(self, "driver", freeze_json(self.driver))

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "action_id": self.action_id,
            "target": (
                {"node": self.target_node, "status": self.target_status}
                if self.target_node is not None
                else None
            ),
            "handler": self.handler_id,
            "payload": dict(self.payload_types),
            "writes": list(self.allowed_state_writes),
            "driver": None if self.driver is None else json_value(self.driver),
            "description": self.description,
            "artifact": None if self.artifact is None else self.artifact.as_dict(),
            "rework": None if self.rework is None else self.rework.as_dict(),
            "finalize": self.finalize_outcome,
        }


@dataclass(frozen=True)
class WorkflowDefinition:
    """A validated workflow graph and the identity of its original document."""

    workflow_id: str
    version: int
    schema: str
    adapter_identity: str
    revision_target: str
    document: Mapping[str, object]
    entry_node: str
    nodes: Mapping[str, NodeContract]
    terminal_nodes: Tuple[str, ...]
    cancel_contract: Optional[NodeContract]
    identity: str

    @property
    def canonical_document(self) -> Mapping[str, object]:
        return self.document

    @property
    def terminals(self) -> Tuple[str, ...]:
        return self.terminal_nodes

    @property
    def cancel(self) -> Optional[NodeContract]:
        return self.cancel_contract


def _adapter_for_schema(schema: object) -> str:
    if schema == SCHEMA_V1:
        return WORKFLOW_V1_ADAPTER_IDENTITY
    if schema == SCHEMA_V2:
        return WORKFLOW_V2_ADAPTER_IDENTITY
    raise ValueError("unsupported workflow schema")


def workflow_identity(
    workflow_id: str,
    document: Mapping[str, object],
    adapter_identity: Optional[str] = None,
) -> str:
    """Digest one selected original document and its language adapter.

    Product and built-in-catalog identities are deliberately absent.  A
    catalog-only release therefore cannot invalidate a task pinned to an
    unchanged selected definition.
    """
    adapter = adapter_identity or _adapter_for_schema(document.get("schema"))
    value = {
        "selector": workflow_id,
        "schema": document.get("schema"),
        "adapter_identity": adapter,
        "document": document,
    }
    return hashlib.sha256(
        b"dev-flow-v6-selected-workflow-identity/v1\x00"
        + canonical_json_bytes(value)
    ).hexdigest()


def _node_spec_error(source: str, node_id: str, message: str) -> DevFlowError:
    return _workflow_error(source, message, node_id=node_id)


def _valid_identifier(value: object) -> bool:
    return isinstance(value, str) and TASK_ID_PATTERN.fullmatch(value) is not None


def _payload_types(
    source: str,
    node_id: str,
    payload: object,
    *,
    handler: str,
) -> Mapping[str, str]:
    if payload is None:
        types = {}
    elif not isinstance(payload, Mapping):
        raise _node_spec_error(source, node_id, "payload must be a mapping")
    else:
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
            source,
            node_id,
            "the preflight node records Git evidence and takes no payload",
        )
    if handler in ("test.record", "verification.record"):
        if types.get("passed") != "boolean":
            raise _node_spec_error(
                source,
                node_id,
                "the {} node must declare payload 'passed: boolean'".format(handler),
            )
    return MappingProxyType(types)


def _declared_writes(
    source: str,
    node_id: str,
    writes: object,
    handler: str,
    schema: str,
) -> Tuple[str, ...]:
    if writes is not None:
        declared_expected = (
            _V1_DECLARED_WRITES[handler]
            if schema == SCHEMA_V1
            else _RECORD_WRITES
        )
        if not isinstance(writes, list) or tuple(writes) != declared_expected:
            raise _node_spec_error(
                source,
                node_id,
                "declared writes must be exactly {}".format(
                    ", ".join(declared_expected)
                ),
            )
    # Both languages execute against V6's append-only record boundary.
    return _RECORD_WRITES


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
            "by this runtime yet",
        )


def _declared_driver(
    source: str, node_id: str, driver: object
) -> Optional[Mapping[str, object]]:
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


def _artifact_contract(
    source: str,
    node_id: str,
    value: object,
    *,
    handler: str,
    required: bool,
) -> Optional[ArtifactContract]:
    if value is None:
        if required:
            raise _node_spec_error(
                source, node_id, "workflow-v2 action nodes must declare artifact"
            )
        return None
    if not isinstance(value, Mapping):
        raise _node_spec_error(source, node_id, "artifact must be a mapping")
    unknown = sorted(str(key) for key in value if key not in {"type", "workspace", "inputs"})
    if unknown:
        raise _node_spec_error(
            source,
            node_id,
            "unknown artifact field(s): {}".format(", ".join(unknown)),
        )
    artifact_type = value.get("type")
    workspace = value.get("workspace")
    inputs_value = value.get("inputs", [])
    if not _valid_identifier(artifact_type):
        raise _node_spec_error(
            source,
            node_id,
            "artifact.type must be 1-64 identifier characters",
        )
    if workspace not in WORKSPACE_ROLES:
        raise _node_spec_error(
            source,
            node_id,
            "artifact.workspace must be one of {}".format(", ".join(WORKSPACE_ROLES)),
        )
    if not isinstance(inputs_value, list):
        raise _node_spec_error(source, node_id, "artifact.inputs must be a list")
    inputs = []
    seen = set()
    for index, item in enumerate(inputs_value):
        if not isinstance(item, Mapping):
            raise _node_spec_error(
                source, node_id, "artifact input {} must be a mapping".format(index)
            )
        unknown_input = sorted(
            str(key) for key in item if key not in {"type", "edge"}
        )
        if unknown_input:
            raise _node_spec_error(
                source,
                node_id,
                "unknown artifact input field(s): {}".format(
                    ", ".join(unknown_input)
                ),
            )
        input_type = item.get("type")
        edge = item.get("edge")
        if not _valid_identifier(input_type):
            raise _node_spec_error(
                source, node_id, "artifact input.type must be an identifier"
            )
        if edge not in INPUT_EDGE_KINDS:
            raise _node_spec_error(
                source,
                node_id,
                "artifact input.edge must be one of {}".format(
                    ", ".join(INPUT_EDGE_KINDS)
                ),
            )
        key = (input_type, edge)
        if key in seen:
            raise _node_spec_error(source, node_id, "artifact inputs must be unique")
        seen.add(key)
        inputs.append(InputContract(input_type, edge))
    predecessor_count = sum(
        item.edge_kind == "source-predecessor" for item in inputs
    )
    predecessor_exempt = handler == "preflight" or artifact_type == "revision-source"
    if workspace == "produces-source" and not predecessor_exempt:
        if predecessor_count != 1:
            raise _node_spec_error(
                source,
                node_id,
                "a produces-source node must declare exactly one "
                "source-predecessor input",
            )
    elif predecessor_count:
        raise _node_spec_error(
            source,
            node_id,
            "source-predecessor inputs belong only to source-producing nodes",
        )
    if handler in (*ASSURANCE_HANDLER_IDS, "delivery.finalize"):
        if workspace != "verifies-source":
            raise _node_spec_error(
                source,
                node_id,
                "verification, review, and finalization artifacts must use "
                "workspace: verifies-source",
            )
    return ArtifactContract(artifact_type, workspace, tuple(inputs))


def _target_fields(
    source: str,
    node_id: str,
    label: str,
    target: object,
    node_ids: Tuple[str, ...],
) -> Tuple[str, str]:
    if not isinstance(target, Mapping):
        raise _node_spec_error(source, node_id, "{} is required".format(label))
    unknown = sorted(str(key) for key in target if key not in {"node", "status"})
    if unknown:
        raise _node_spec_error(
            source,
            node_id,
            "unknown {} field(s): {}".format(label, ", ".join(unknown)),
        )
    target_node = target.get("node")
    target_status = target.get("status")
    if not isinstance(target_node, str) or target_node not in node_ids:
        raise _node_spec_error(
            source, node_id, "{}.node must be a declared node".format(label)
        )
    if not isinstance(target_status, str) or not target_status:
        raise _node_spec_error(source, node_id, "{}.status is required".format(label))
    return target_node, target_status


def _rework_contract(
    source: str,
    node_id: str,
    value: object,
    *,
    handler: str,
    node_ids: Tuple[str, ...],
) -> Optional[ReworkContract]:
    if value is None:
        return None
    if handler not in ASSURANCE_HANDLER_IDS:
        raise _node_spec_error(
            source,
            node_id,
            "rework is supported only by verification.record and review.record",
        )
    if not isinstance(value, Mapping):
        raise _node_spec_error(source, node_id, "rework must be a mapping")
    unknown = sorted(
        str(key) for key in value if key not in {"failure", "max_attempts", "exhausted"}
    )
    if unknown:
        raise _node_spec_error(
            source,
            node_id,
            "unknown rework field(s): {}".format(", ".join(unknown)),
        )
    failure_node, failure_status = _target_fields(
        source, node_id, "rework.failure", value.get("failure"), node_ids
    )
    exhausted_node, exhausted_status = _target_fields(
        source, node_id, "rework.exhausted", value.get("exhausted"), node_ids
    )
    max_attempts = value.get("max_attempts")
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts <= 0
    ):
        raise _node_spec_error(
            source, node_id, "rework.max_attempts must be a positive integer"
        )
    return ReworkContract(
        failure_node,
        failure_status,
        max_attempts,
        exhausted_node,
        exhausted_status,
    )


def _node_contract(
    source: str,
    node_id: str,
    spec: object,
    *,
    schema: str,
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
    if schema == SCHEMA_V2:
        allowed.update({"artifact", "rework", "finalize"})
    unknown = sorted(str(key) for key in spec if key not in allowed)
    if unknown:
        raise _node_spec_error(
            source,
            node_id,
            "unknown node field(s): {}".format(", ".join(unknown)),
        )
    if spec.get("terminal") is True:
        forbidden = set(spec) - {"terminal", "description"}
        if forbidden:
            field = sorted(str(item) for item in forbidden)[0]
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
    allowed_handlers = V1_HANDLER_IDS if schema == SCHEMA_V1 else V2_HANDLER_IDS
    if not isinstance(action_id, str) or not action_id:
        raise _node_spec_error(source, node_id, "action_id is required")
    if not isinstance(handler, str) or handler not in allowed_handlers:
        raise _node_spec_error(
            source,
            node_id,
            "handler must be one of {}".format(", ".join(allowed_handlers)),
        )
    target_node, target_status = _target_fields(
        source, node_id, "target", spec.get("target"), node_ids
    )
    if target_node == node_id and not shared_action:
        raise _node_spec_error(source, node_id, "node must not target itself")
    _declared_authority(source, node_id, spec.get("authority"))
    description = spec.get("description")
    if description is not None and not isinstance(description, str):
        raise _node_spec_error(source, node_id, "description must be a string")
    artifact = _artifact_contract(
        source,
        node_id,
        spec.get("artifact"),
        handler=handler,
        required=schema == SCHEMA_V2 and not shared_action,
    )
    rework = _rework_contract(
        source,
        node_id,
        spec.get("rework"),
        handler=handler,
        node_ids=node_ids,
    )
    finalize = spec.get("finalize")
    if handler == "delivery.finalize":
        if finalize not in FINALIZE_OUTCOMES:
            raise _node_spec_error(
                source,
                node_id,
                "delivery.finalize must declare finalize: success or incomplete",
            )
        if artifact is None or artifact.artifact_type != "delivery-dossier":
            raise _node_spec_error(
                source,
                node_id,
                "delivery.finalize must produce artifact type delivery-dossier",
            )
        expected_status = "DONE" if finalize == "success" else "INCOMPLETE"
        if target_status != expected_status:
            raise _node_spec_error(
                source,
                node_id,
                "{} finalization target.status must be {}".format(
                    finalize, expected_status
                ),
            )
    elif finalize is not None:
        raise _node_spec_error(
            source, node_id, "finalize belongs only to delivery.finalize nodes"
        )
    return NodeContract(
        node_id=node_id,
        action_id=action_id,
        target_node=target_node,
        target_status=target_status,
        handler_id=handler,
        effect_port=_declared_effect(source, node_id, spec.get("effect"), handler),
        allowed_state_writes=_declared_writes(
            source, node_id, spec.get("writes"), handler, schema
        ),
        payload_types=_payload_types(
            source, node_id, spec.get("payload"), handler=handler
        ),
        driver=_declared_driver(source, node_id, spec.get("driver")),
        description=description,
        artifact=artifact,
        rework=rework,
        finalize_outcome=finalize,
    )


def _validate_cancel_contract(
    source: str,
    contract: NodeContract,
    *,
    schema: str,
    action_ids: Tuple[str, ...],
    terminal_nodes: Tuple[str, ...],
) -> None:
    expected_handler = "evidence.record" if schema == SCHEMA_V1 else "artifact.record"
    if contract.handler_id != expected_handler:
        raise _workflow_error(
            source,
            "the cancel action must use the {} handler".format(expected_handler),
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


def _graph_edges(
    contracts: Mapping[str, NodeContract],
    *,
    include_failure: bool,
) -> Mapping[str, Tuple[str, ...]]:
    edges = {}
    for node_id, contract in contracts.items():
        targets = []
        if contract.target_node is not None:
            targets.append(contract.target_node)
        if contract.rework is not None:
            targets.append(contract.rework.exhausted_node)
            if include_failure:
                targets.append(contract.rework.failure_node)
        edges[node_id] = tuple(dict.fromkeys(targets))
    return MappingProxyType(edges)


def _reachable_nodes(
    entry: str,
    edges: Mapping[str, Tuple[str, ...]],
    *,
    cancel_target: Optional[str],
) -> Tuple[str, ...]:
    reached = []
    seen = set()
    pending = [entry]
    while pending:
        node_id = pending.pop(0)
        if node_id in seen:
            continue
        seen.add(node_id)
        reached.append(node_id)
        pending.extend(target for target in edges[node_id] if target not in seen)
    if cancel_target is not None and cancel_target not in seen:
        reached.append(cancel_target)
    return tuple(reached)


def _validate_acyclic(
    source: str,
    edges: Mapping[str, Tuple[str, ...]],
) -> None:
    visiting = set()
    visited = set()
    path = []

    def visit(node_id: str) -> None:
        if node_id in visiting:
            start = path.index(node_id)
            raise _workflow_error(
                source,
                "workflow graph must not contain a cycle after finite failure "
                "edges are removed",
                node_id=node_id,
                cycle=path[start:] + [node_id],
            )
        if node_id in visited:
            return
        visiting.add(node_id)
        path.append(node_id)
        for target in edges[node_id]:
            visit(target)
        path.pop()
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in edges:
        visit(node_id)


def _validate_rework_targets(
    source: str,
    contracts: Mapping[str, NodeContract],
    terminal_nodes: Tuple[str, ...],
) -> None:
    terminal = set(terminal_nodes)
    for node_id, contract in contracts.items():
        if contract.rework is None:
            continue
        if contract.rework.failure_node in terminal:
            raise _node_spec_error(
                source, node_id, "rework.failure must target a nonterminal node"
            )
        if contract.rework.exhausted_node in terminal:
            raise _node_spec_error(
                source,
                node_id,
                "rework.exhausted must target incomplete delivery finalization",
            )
        exhausted = contracts[contract.rework.exhausted_node]
        if (
            exhausted.handler_id != "delivery.finalize"
            or exhausted.finalize_outcome != "incomplete"
        ):
            raise _node_spec_error(
                source,
                node_id,
                "rework.exhausted must target an incomplete delivery.finalize node",
            )


def _validate_v2_terminal_paths(
    source: str,
    contracts: Mapping[str, NodeContract],
    terminal_nodes: Tuple[str, ...],
    cancel_contract: Optional[NodeContract],
) -> None:
    terminal = set(terminal_nodes)
    cancel_target = None if cancel_contract is None else cancel_contract.target_node
    inbound = {node_id: [] for node_id in terminal_nodes}
    for node_id, contract in contracts.items():
        if contract.target_node in terminal:
            inbound[contract.target_node].append(node_id)
            if contract.target_node == cancel_target:
                raise _node_spec_error(
                    source,
                    node_id,
                    "the cancellation terminal is reserved for the cancel action",
                )
            if contract.handler_id != "delivery.finalize":
                raise _node_spec_error(
                    source,
                    node_id,
                    "non-cancelled workflow paths must enter a terminal through "
                    "delivery.finalize",
                )
        if contract.handler_id == "delivery.finalize" and contract.target_node not in terminal:
            raise _node_spec_error(
                source, node_id, "delivery.finalize must target a terminal node"
            )
    for terminal_node in terminal_nodes:
        if terminal_node == cancel_target:
            continue
        if not inbound[terminal_node]:
            raise _workflow_error(
                source,
                "non-cancellation terminal has no delivery.finalize predecessor",
                node_id=terminal_node,
            )


def validate_definition_document(
    document: object,
    *,
    workflow_id: str,
    source: str,
) -> WorkflowDefinition:
    """Validate one original workflow document and build its common contract."""
    if not isinstance(document, Mapping):
        raise _workflow_error(source, "workflow document must be a mapping")
    schema = document.get("schema")
    if schema not in (SCHEMA_V1, SCHEMA_V2):
        raise _workflow_error(
            source,
            "schema must be exactly {!r} or {!r}".format(SCHEMA_V1, SCHEMA_V2),
        )
    allowed_top = {
        "schema",
        "id",
        "version",
        "description",
        "entry",
        "nodes",
        "cancel",
    }
    if schema == SCHEMA_V2:
        allowed_top.add("revision_target")
    unknown = sorted(str(key) for key in document if key not in allowed_top)
    if unknown:
        raise _workflow_error(
            source,
            "unknown workflow field(s): {}".format(", ".join(unknown)),
        )
    declared_id = document.get("id")
    if not _valid_identifier(declared_id):
        raise _workflow_error(
            source,
            "id must be 1-64 characters using letters, digits, '.', '_' or '-'",
        )
    version = document.get("version")
    expected_version = V1_VERSION if schema == SCHEMA_V1 else V2_VERSION
    if version != expected_version:
        if schema == SCHEMA_V1:
            message = "version must be current schema v5 for workflow-v1 compatibility"
        else:
            message = "workflow-v2 version must be exactly {}".format(V2_VERSION)
        raise _workflow_error(source, message)
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
    if any(not _valid_identifier(node_id) for node_id in node_ids):
        raise _workflow_error(source, "node ids must use the identifier vocabulary")
    if entry not in node_ids:
        raise _workflow_error(source, "entry node {!r} is not declared".format(entry))
    contracts = {
        node_id: _node_contract(
            source,
            node_id,
            nodes_value[node_id],
            schema=schema,
            node_ids=node_ids,
        )
        for node_id in node_ids
    }
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
    if preflight_nodes != [entry]:
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
        contract.action_id for contract in contracts.values() if contract.action_id
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
            schema=schema,
            node_ids=node_ids,
            shared_action=True,
        )
        _validate_cancel_contract(
            source,
            cancel_contract,
            schema=schema,
            action_ids=tuple(action_ids),
            terminal_nodes=terminal_nodes,
        )
    if schema == SCHEMA_V2:
        if cancel_contract is None:
            raise _workflow_error(
                source, "workflow-v2 definitions must declare a shared cancel action"
            )
        _validate_rework_targets(source, contracts, terminal_nodes)
        _validate_v2_terminal_paths(
            source, contracts, terminal_nodes, cancel_contract
        )
    _validate_acyclic(
        source,
        _graph_edges(contracts, include_failure=False),
    )
    full_edges = _graph_edges(contracts, include_failure=True)
    reached = set(
        _reachable_nodes(
            entry,
            full_edges,
            cancel_target=(
                None if cancel_contract is None else cancel_contract.target_node
            ),
        )
    )
    unreachable = [node_id for node_id in node_ids if node_id not in reached]
    if unreachable:
        raise _workflow_error(
            source,
            "node(s) not reachable from the entry: {}".format(", ".join(unreachable)),
        )
    revision_target = entry if schema == SCHEMA_V1 else document.get("revision_target")
    if (
        not isinstance(revision_target, str)
        or revision_target not in reached
        or revision_target in terminal_nodes
    ):
        raise _workflow_error(
            source,
            "revision_target must identify a reachable nonterminal node",
            revision_target=revision_target,
        )
    adapter_identity = _adapter_for_schema(schema)
    original_document = freeze_json(dict(document))
    return WorkflowDefinition(
        workflow_id=workflow_id,
        version=version,
        schema=schema,
        adapter_identity=adapter_identity,
        revision_target=revision_target,
        document=original_document,
        entry_node=entry,
        nodes=MappingProxyType(contracts),
        terminal_nodes=terminal_nodes,
        cancel_contract=cancel_contract,
        identity=workflow_identity(workflow_id, document, adapter_identity),
    )


def is_terminal_state(state: TaskState, definition: WorkflowDefinition) -> bool:
    """Return whether the task's current node is terminal for its workflow."""
    return state.current_node in definition.terminal_nodes


def current_contract(state: TaskState, definition: WorkflowDefinition) -> NodeContract:
    """Return the one node contract currently exposed by a task."""
    if is_terminal_state(state, definition):
        raise DevFlowError(
            "NO_ACTION_AVAILABLE",
            "current node has no public action",
            details={"current_node": state.current_node, "status": state.status},
        )
    contract = definition.nodes.get(state.current_node)
    if contract is None:
        raise DevFlowError(
            "NO_ACTION_AVAILABLE",
            "current node has no public action",
            details={"current_node": state.current_node, "status": state.status},
        )
    return contract


def agent_projection(
    state: TaskState,
    definition: WorkflowDefinition,
    current_snapshot: Optional[Mapping[str, object]] = None,
) -> dict:
    """Delegate projection construction to the V6 evidence-aware engine."""
    if current_snapshot is None:
        raise DevFlowError(
            "WORKSPACE_SNAPSHOT_REQUIRED",
            "V6 projections require a current bounded workspace snapshot",
        )
    from .engine import agent_projection as project

    return project(state, definition, current_snapshot)
