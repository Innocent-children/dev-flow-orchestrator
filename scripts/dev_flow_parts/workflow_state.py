# Loaded by scripts/dev_flow.py only after bundle-aware state support is
# integrated.  Until then tests load this fragment directly.  Keep it
# standard-library only, pure, and free of controller or catalog globals.
from __future__ import annotations

import re
from types import MappingProxyType
from typing import Callable, Mapping


V4_TASK_SCHEMA_VERSION = 4
SUPPORTED_TASK_SCHEMA_VERSIONS = frozenset({V4_TASK_SCHEMA_VERSION})

_workflow_state_workflow_schema = "dev-flow-workflow/v1"
_workflow_state_result_reference_schema = (
    "dev-flow-node-result-reference/v1"
)
_workflow_state_runtime_handle_schema = "dev-flow-runtime-handle/v1"
_workflow_state_orchestration_schema = (
    "dev-flow-orchestration-state/v1"
)
_workflow_state_map_expansion_schema = (
    "dev-flow-repository-map-expansion/v1"
)
_workflow_state_sha256_re = re.compile(r"^[0-9a-f]{64}$")
_workflow_state_stable_id_re = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$"
)
_workflow_state_workflow_id_re = re.compile(r"^[a-z][a-z0-9._-]*$")
_workflow_state_lifecycle_states = frozenset(
    {
        "PENDING",
        "READY",
        "RUNNING",
        "WAITING_APPROVAL",
        "WAITING_EXTERNAL",
        "BLOCKED",
        "SUCCEEDED",
        "FAILED",
        "SKIPPED",
    }
)
_workflow_state_execution_profiles = frozenset(
    {"single-repository", "multi-repository"}
)
_workflow_state_resolution_purposes = frozenset(
    {"inspection", "mutation", "recovery"}
)
_workflow_state_workflow_ref_fields = frozenset(
    {
        "id",
        "version",
        "schema",
        "graph_sha256",
        "bundle_sha256",
    }
)
_workflow_state_node_instance_fields = frozenset(
    {
        "node_instance_id",
        "node_id",
        "state",
        "dependencies",
        "attempts",
        "repository_id",
    }
)
_workflow_state_attempt_fields = frozenset(
    {
        "attempt",
        "state",
        "input_sha256",
        "result_refs",
        "previous_attempt",
        "runtime_handle",
    }
)
_workflow_state_result_reference_fields = frozenset(
    {
        "schema",
        "result_id",
        "task_id",
        "bundle_sha256",
        "node_instance_id",
        "attempt",
        "input_sha256",
        "output_sha256",
        "locator",
    }
)
_workflow_state_runtime_handle_fields = frozenset(
    {
        "schema",
        "handle_id",
        "kind",
        "task_id",
        "node_instance_id",
        "attempt",
        "repository_id",
    }
)
_workflow_state_expansion_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "semantic_input_sha256",
        "map_node_id",
        "map_epoch",
        "repository_set",
        "children",
        "current",
        "stale_reason",
        "stale_at_revision",
        "stale_facts_sha256",
        "minimum_successor_map_epoch",
        "retired_at_revision",
    }
)
_workflow_state_expansion_required_fields = frozenset(
    {
        "schema",
        "task_id",
        "workflow_bundle_sha256",
        "plan_id",
        "dag_sha256",
        "semantic_input_sha256",
        "map_node_id",
        "map_epoch",
        "repository_set",
        "children",
    }
)
_workflow_state_expansion_child_fields = frozenset(
    {
        "node_instance_id",
        "node_id",
        "repository_id",
        "repository_identity_sha256",
        "map_epoch",
        "dependencies",
    }
)


class WorkflowStateError(Exception):
    """Stable structured failure raised by the pure task-state boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


def _workflow_state_error(
    code: str,
    message: str,
    *,
    pointer: str,
    value: object = None,
    details: Mapping[str, object] | None = None,
) -> "WorkflowStateError":
    error_details = {"pointer": pointer}
    if value is not None:
        error_details["value"] = value
    error_details.update(details or {})
    return WorkflowStateError(code, message, details=error_details)


def _workflow_state_require_mapping(
    value: object, pointer: str, *, code: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _workflow_state_error(
            code,
            "workflow state field must be an object",
            pointer=pointer,
            details={"type": type(value).__name__},
        )
    if any(not isinstance(key, str) for key in value):
        raise _workflow_state_error(
            code,
            "workflow state object keys must be strings",
            pointer=pointer,
        )
    return value


def _workflow_state_reject_unknown(
    value: Mapping[str, object],
    allowed: frozenset[str],
    pointer: str,
    *,
    code: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _workflow_state_error(
            code,
            "workflow state field contains unsupported properties",
            pointer=pointer,
            details={"fields": unknown},
        )


def _workflow_state_require_string(
    value: object,
    pointer: str,
    *,
    code: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value:
        raise _workflow_state_error(
            code,
            "workflow state field must be a non-empty string",
            pointer=pointer,
        )
    if pattern is not None and not pattern.fullmatch(value):
        raise _workflow_state_error(
            code,
            "workflow state field is not a stable portable identifier",
            pointer=pointer,
            value=value,
        )
    return value


def _workflow_state_require_integer(
    value: object,
    pointer: str,
    *,
    code: str,
    minimum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
    ):
        raise _workflow_state_error(
            code,
            f"workflow state field must be an integer >= {minimum}",
            pointer=pointer,
            value=value,
        )
    return value


def _workflow_state_require_digest(
    value: object, pointer: str, *, code: str
) -> str:
    digest = _workflow_state_require_string(
        value, pointer, code=code
    )
    if not _workflow_state_sha256_re.fullmatch(digest):
        raise _workflow_state_error(
            code,
            "workflow state digest must be a lowercase SHA-256 value",
            pointer=pointer,
            value=digest,
        )
    return digest


def _workflow_state_require_string_array(
    value: object,
    pointer: str,
    *,
    code: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _workflow_state_error(
            code,
            "workflow state field must be an array",
            pointer=pointer,
        )
    result = tuple(
        _workflow_state_require_string(
            item,
            f"{pointer}/{index}",
            code=code,
            pattern=_workflow_state_stable_id_re,
        )
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise _workflow_state_error(
            code,
            "workflow state array values must be unique",
            pointer=pointer,
        )
    expected = tuple(
        sorted(result, key=lambda item: item.encode("utf-8"))
    )
    if result != expected:
        raise _workflow_state_error(
            code,
            "workflow state array values must use deterministic UTF-8 order",
            pointer=pointer,
        )
    return result


def _workflow_state_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _workflow_state_freeze(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_workflow_state_freeze(item) for item in value)
    return value


def _workflow_state_unsupported_resolution(
    state: object,
) -> Mapping[str, object]:
    if isinstance(state, Mapping):
        schema_version = state.get("schema_version")
        flow = state.get("flow")
        workflow_ref = state.get("workflow_ref")
    else:
        schema_version = None
        flow = None
        workflow_ref = None
    return MappingProxyType(
        {
            "kind": "unsupported",
            "supported": False,
            "schema_version": schema_version,
            "flow": flow,
            "workflow_ref": _workflow_state_freeze(workflow_ref),
        }
    )


def validate_workflow_ref(value: object) -> Mapping[str, object]:
    """Validate and return an immutable schema-v4 pinned workflow identity."""

    reference = _workflow_state_require_mapping(
        value, "/workflow_ref", code="WORKFLOW_REF_INVALID"
    )
    _workflow_state_reject_unknown(
        reference,
        _workflow_state_workflow_ref_fields,
        "/workflow_ref",
        code="WORKFLOW_REF_INVALID",
    )
    missing = sorted(_workflow_state_workflow_ref_fields - set(reference))
    if missing:
        raise _workflow_state_error(
            "WORKFLOW_REF_INVALID",
            "workflow_ref is missing required pinned identity fields",
            pointer="/workflow_ref",
            details={"fields": missing},
        )
    workflow_id = _workflow_state_require_string(
        reference["id"],
        "/workflow_ref/id",
        code="WORKFLOW_REF_INVALID",
        pattern=_workflow_state_workflow_id_re,
    )
    workflow_version = _workflow_state_require_integer(
        reference["version"],
        "/workflow_ref/version",
        code="WORKFLOW_REF_INVALID",
        minimum=1,
    )
    if reference["schema"] != _workflow_state_workflow_schema:
        raise _workflow_state_error(
            "WORKFLOW_REF_UNSUPPORTED",
            "workflow_ref schema contract is unsupported",
            pointer="/workflow_ref/schema",
            value=reference["schema"],
            details={"supported": [_workflow_state_workflow_schema]},
        )
    graph_sha256 = _workflow_state_require_digest(
        reference["graph_sha256"],
        "/workflow_ref/graph_sha256",
        code="WORKFLOW_REF_INVALID",
    )
    bundle_sha256 = _workflow_state_require_digest(
        reference["bundle_sha256"],
        "/workflow_ref/bundle_sha256",
        code="WORKFLOW_REF_INVALID",
    )
    return MappingProxyType(
        {
            "id": workflow_id,
            "version": workflow_version,
            "schema": _workflow_state_workflow_schema,
            "graph_sha256": graph_sha256,
            "bundle_sha256": bundle_sha256,
        }
    )


def _workflow_state_validate_result_reference(
    value: object,
    pointer: str,
    *,
    task_id: str,
    bundle_sha256: str,
    node_instance_id: str,
    attempt: int,
    input_sha256: str,
) -> Mapping[str, object]:
    reference = _workflow_state_require_mapping(
        value, pointer, code="RESULT_REFERENCE_INVALID"
    )
    _workflow_state_reject_unknown(
        reference,
        _workflow_state_result_reference_fields,
        pointer,
        code="RESULT_REFERENCE_INVALID",
    )
    missing = sorted(
        _workflow_state_result_reference_fields - set(reference)
    )
    if missing:
        raise _workflow_state_error(
            "RESULT_REFERENCE_INVALID",
            "node result reference is missing required fields",
            pointer=pointer,
            details={"fields": missing},
        )
    if reference["schema"] != _workflow_state_result_reference_schema:
        raise _workflow_state_error(
            "RESULT_REFERENCE_UNSUPPORTED",
            "node result reference schema is unsupported",
            pointer=f"{pointer}/schema",
            value=reference["schema"],
            details={
                "supported": [_workflow_state_result_reference_schema]
            },
        )
    expected_values = {
        "task_id": task_id,
        "bundle_sha256": bundle_sha256,
        "node_instance_id": node_instance_id,
        "attempt": attempt,
        "input_sha256": input_sha256,
    }
    for field, expected in expected_values.items():
        if reference[field] != expected:
            raise _workflow_state_error(
                "RESULT_REFERENCE_MISMATCH",
                "node result reference does not match its owning attempt",
                pointer=f"{pointer}/{field}",
                value=reference[field],
                details={"expected": expected},
            )
    _workflow_state_require_string(
        reference["result_id"],
        f"{pointer}/result_id",
        code="RESULT_REFERENCE_INVALID",
        pattern=_workflow_state_stable_id_re,
    )
    _workflow_state_require_digest(
        reference["output_sha256"],
        f"{pointer}/output_sha256",
        code="RESULT_REFERENCE_INVALID",
    )
    _workflow_state_require_string(
        reference["locator"],
        f"{pointer}/locator",
        code="RESULT_REFERENCE_INVALID",
    )
    return _workflow_state_freeze(reference)  # type: ignore[return-value]


def _workflow_state_validate_runtime_handle(
    value: object,
    pointer: str,
    *,
    task_id: str,
    node_instance_id: str,
    repository_id: str | None,
    attempt: int,
) -> Mapping[str, object]:
    handle = _workflow_state_require_mapping(
        value, pointer, code="RUNTIME_HANDLE_INVALID"
    )
    _workflow_state_reject_unknown(
        handle,
        _workflow_state_runtime_handle_fields,
        pointer,
        code="RUNTIME_HANDLE_INVALID",
    )
    required = _workflow_state_runtime_handle_fields - {"repository_id"}
    missing = sorted(required - set(handle))
    if missing:
        raise _workflow_state_error(
            "RUNTIME_HANDLE_INVALID",
            "runtime handle is missing required binding fields",
            pointer=pointer,
            details={"fields": missing},
        )
    if handle["schema"] != _workflow_state_runtime_handle_schema:
        raise _workflow_state_error(
            "RUNTIME_HANDLE_UNSUPPORTED",
            "runtime handle schema is unsupported",
            pointer=f"{pointer}/schema",
            value=handle["schema"],
            details={"supported": [_workflow_state_runtime_handle_schema]},
        )
    expected_values = {
        "task_id": task_id,
        "node_instance_id": node_instance_id,
        "attempt": attempt,
    }
    for field, expected in expected_values.items():
        if handle[field] != expected:
            raise _workflow_state_error(
                "RUNTIME_HANDLE_MISMATCH",
                "runtime handle does not match its owning attempt",
                pointer=f"{pointer}/{field}",
                value=handle[field],
                details={"expected": expected},
            )
    if handle.get("repository_id") != repository_id:
        raise _workflow_state_error(
            "RUNTIME_HANDLE_MISMATCH",
            "runtime handle repository binding does not match its node",
            pointer=f"{pointer}/repository_id",
            value=handle.get("repository_id"),
            details={"expected": repository_id},
        )
    for field in ("handle_id", "kind"):
        _workflow_state_require_string(
            handle[field],
            f"{pointer}/{field}",
            code="RUNTIME_HANDLE_INVALID",
            pattern=_workflow_state_stable_id_re,
        )
    return _workflow_state_freeze(handle)  # type: ignore[return-value]


def _workflow_state_validate_attempt(
    value: object,
    pointer: str,
    *,
    task_id: str,
    bundle_sha256: str,
    node_instance_id: str,
    repository_id: str | None,
    expected_attempt: int,
) -> Mapping[str, object]:
    attempt_value = _workflow_state_require_mapping(
        value, pointer, code="NODE_ATTEMPT_INVALID"
    )
    _workflow_state_reject_unknown(
        attempt_value,
        _workflow_state_attempt_fields,
        pointer,
        code="NODE_ATTEMPT_INVALID",
    )
    required = _workflow_state_attempt_fields - {
        "previous_attempt",
        "runtime_handle",
    }
    missing = sorted(required - set(attempt_value))
    if missing:
        raise _workflow_state_error(
            "NODE_ATTEMPT_INVALID",
            "node attempt is missing required fields",
            pointer=pointer,
            details={"fields": missing},
        )
    attempt = _workflow_state_require_integer(
        attempt_value["attempt"],
        f"{pointer}/attempt",
        code="NODE_ATTEMPT_INVALID",
        minimum=1,
    )
    if attempt != expected_attempt:
        raise _workflow_state_error(
            "NODE_ATTEMPT_INVALID",
            "attempt history must be consecutive and ordered from one",
            pointer=f"{pointer}/attempt",
            value=attempt,
            details={"expected": expected_attempt},
        )
    state = attempt_value["state"]
    if state not in _workflow_state_lifecycle_states:
        raise _workflow_state_error(
            "NODE_ATTEMPT_INVALID",
            "node attempt lifecycle state is unsupported",
            pointer=f"{pointer}/state",
            value=state,
        )
    input_sha256 = _workflow_state_require_digest(
        attempt_value["input_sha256"],
        f"{pointer}/input_sha256",
        code="NODE_ATTEMPT_INVALID",
    )
    if attempt == 1:
        if "previous_attempt" in attempt_value:
            raise _workflow_state_error(
                "NODE_ATTEMPT_INVALID",
                "the first attempt cannot reference a previous attempt",
                pointer=f"{pointer}/previous_attempt",
            )
    elif attempt_value.get("previous_attempt") != attempt - 1:
        raise _workflow_state_error(
            "NODE_ATTEMPT_INVALID",
            "retry attempts must link to the immediately prior attempt",
            pointer=f"{pointer}/previous_attempt",
            value=attempt_value.get("previous_attempt"),
            details={"expected": attempt - 1},
        )
    result_refs = attempt_value["result_refs"]
    if not isinstance(result_refs, list):
        raise _workflow_state_error(
            "RESULT_REFERENCE_INVALID",
            "result_refs must be an array",
            pointer=f"{pointer}/result_refs",
        )
    result_ids: list[str] = []
    for result_index, result_reference in enumerate(result_refs):
        validated = _workflow_state_validate_result_reference(
            result_reference,
            f"{pointer}/result_refs/{result_index}",
            task_id=task_id,
            bundle_sha256=bundle_sha256,
            node_instance_id=node_instance_id,
            attempt=attempt,
            input_sha256=input_sha256,
        )
        result_ids.append(str(validated["result_id"]))
    if len(result_ids) != len(set(result_ids)):
        raise _workflow_state_error(
            "RESULT_REFERENCE_INVALID",
            "result reference identities must be unique within an attempt",
            pointer=f"{pointer}/result_refs",
        )
    if result_ids != sorted(
        result_ids, key=lambda item: item.encode("utf-8")
    ):
        raise _workflow_state_error(
            "RESULT_REFERENCE_INVALID",
            "result references must use deterministic result-id order",
            pointer=f"{pointer}/result_refs",
        )
    if attempt_value.get("runtime_handle") is not None:
        _workflow_state_validate_runtime_handle(
            attempt_value["runtime_handle"],
            f"{pointer}/runtime_handle",
            task_id=task_id,
            node_instance_id=node_instance_id,
            repository_id=repository_id,
            attempt=attempt,
        )
    return _workflow_state_freeze(attempt_value)  # type: ignore[return-value]


def _workflow_state_validate_node_instance(
    value: object,
    pointer: str,
    *,
    task_id: str,
    bundle_sha256: str,
) -> Mapping[str, object]:
    node = _workflow_state_require_mapping(
        value, pointer, code="NODE_INSTANCE_INVALID"
    )
    _workflow_state_reject_unknown(
        node,
        _workflow_state_node_instance_fields,
        pointer,
        code="NODE_INSTANCE_INVALID",
    )
    required = _workflow_state_node_instance_fields - {"repository_id"}
    missing = sorted(required - set(node))
    if missing:
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instance is missing required fields",
            pointer=pointer,
            details={"fields": missing},
        )
    node_instance_id = _workflow_state_require_string(
        node["node_instance_id"],
        f"{pointer}/node_instance_id",
        code="NODE_INSTANCE_INVALID",
        pattern=_workflow_state_stable_id_re,
    )
    _workflow_state_require_string(
        node["node_id"],
        f"{pointer}/node_id",
        code="NODE_INSTANCE_INVALID",
        pattern=_workflow_state_stable_id_re,
    )
    if node["state"] not in _workflow_state_lifecycle_states:
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instance lifecycle state is unsupported",
            pointer=f"{pointer}/state",
            value=node["state"],
        )
    dependencies = _workflow_state_require_string_array(
        node["dependencies"],
        f"{pointer}/dependencies",
        code="NODE_INSTANCE_INVALID",
    )
    if node_instance_id in dependencies:
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instance cannot depend on itself",
            pointer=f"{pointer}/dependencies",
            value=node_instance_id,
        )
    repository_id = None
    if "repository_id" in node:
        repository_id = _workflow_state_require_string(
            node["repository_id"],
            f"{pointer}/repository_id",
            code="NODE_INSTANCE_INVALID",
            pattern=_workflow_state_stable_id_re,
        )
    attempts = node["attempts"]
    if not isinstance(attempts, list):
        raise _workflow_state_error(
            "NODE_ATTEMPT_INVALID",
            "node attempts must be an array",
            pointer=f"{pointer}/attempts",
        )
    for attempt_index, attempt_value in enumerate(attempts):
        _workflow_state_validate_attempt(
            attempt_value,
            f"{pointer}/attempts/{attempt_index}",
            task_id=task_id,
            bundle_sha256=bundle_sha256,
            node_instance_id=node_instance_id,
            repository_id=repository_id,
            expected_attempt=attempt_index + 1,
        )
    return _workflow_state_freeze(node)  # type: ignore[return-value]


def validate_v4_task_state(state: object) -> Mapping[str, object]:
    """Strictly validate schema-v4 workflow-owned persisted structures."""

    task = _workflow_state_require_mapping(
        state, "", code="TASK_STATE_INVALID"
    )
    if task.get("schema_version") != V4_TASK_SCHEMA_VERSION:
        raise _workflow_state_error(
            "TASK_SCHEMA_UNSUPPORTED",
            "task is not a supported schema-v4 state",
            pointer="/schema_version",
            value=task.get("schema_version"),
            details={
                "supported_schema_versions": sorted(
                    SUPPORTED_TASK_SCHEMA_VERSIONS
                )
            },
        )
    task_id = _workflow_state_require_string(
        task.get("task_id"), "/task_id", code="TASK_STATE_INVALID"
    )
    _workflow_state_require_integer(
        task.get("revision"),
        "/revision",
        code="TASK_STATE_INVALID",
        minimum=0,
    )
    flow = task.get("flow")
    if flow not in {"full", "lite"}:
        raise _workflow_state_error(
            "TASK_STATE_INVALID",
            "V4 flow must be full or lite",
            pointer="/flow",
            value=flow,
        )
    execution_profile = task.get("execution_profile")
    if execution_profile not in _workflow_state_execution_profiles:
        raise _workflow_state_error(
            "TASK_EXECUTION_PROFILE_INVALID",
            "schema-v4 tasks must persist one supported execution profile",
            pointer="/execution_profile",
            value=execution_profile,
            details={
                "supported": sorted(_workflow_state_execution_profiles)
            },
        )
    _workflow_state_require_string(
        task.get("status"), "/status", code="TASK_STATE_INVALID"
    )
    workflow_ref = validate_workflow_ref(task.get("workflow_ref"))
    node_instances = task.get("node_instances")
    if not isinstance(node_instances, list):
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node_instances must be an array",
            pointer="/node_instances",
        )
    node_ids: list[str] = []
    dependency_ids: set[str] = set()
    for node_index, node_value in enumerate(node_instances):
        validated = _workflow_state_validate_node_instance(
            node_value,
            f"/node_instances/{node_index}",
            task_id=task_id,
            bundle_sha256=str(workflow_ref["bundle_sha256"]),
        )
        node_ids.append(str(validated["node_instance_id"]))
        dependency_ids.update(str(item) for item in validated["dependencies"])
    if len(node_ids) != len(set(node_ids)):
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instance identities must be unique",
            pointer="/node_instances",
        )
    if node_ids != sorted(node_ids, key=lambda item: item.encode("utf-8")):
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instances must use deterministic node-instance-id order",
            pointer="/node_instances",
        )
    unknown_dependencies = sorted(dependency_ids - set(node_ids))
    if unknown_dependencies:
        raise _workflow_state_error(
            "NODE_INSTANCE_INVALID",
            "node instance dependencies must resolve within the task",
            pointer="/node_instances",
            details={"dependencies": unknown_dependencies},
        )
    return _workflow_state_freeze(task)  # type: ignore[return-value]


def _workflow_state_bundle_graph(
    bundle: object,
) -> Mapping[str, object]:
    graph = _workflow_state_descriptor_value(bundle, "graph")
    if not isinstance(graph, Mapping):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "resolved bundle does not expose its validated graph",
        )
    return graph


def _workflow_state_bundle_nodes(
    bundle: object, graph: Mapping[str, object]
) -> Mapping[str, object]:
    nodes = _workflow_state_descriptor_value(bundle, "nodes")
    if isinstance(nodes, Mapping):
        return nodes
    graph_nodes = graph.get("nodes")
    if not isinstance(graph_nodes, (list, tuple)):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "resolved bundle does not expose validated node declarations",
        )
    result: dict[str, object] = {}
    for index, node in enumerate(graph_nodes):
        if not isinstance(node, Mapping) or not isinstance(
            node.get("id"), str
        ):
            raise WorkflowStateError(
                "WORKFLOW_RESOLUTION_INVALID",
                "resolved bundle contains an invalid node declaration",
                details={"pointer": f"/nodes/{index}"},
            )
        node_id = str(node["id"])
        if node_id in result:
            raise WorkflowStateError(
                "WORKFLOW_RESOLUTION_INVALID",
                "resolved bundle contains duplicate node identities",
                details={"node_id": node_id},
            )
        result[node_id] = node
    return MappingProxyType(result)


def _workflow_state_validate_expansion_child(
    value: object,
    pointer: str,
    *,
    template_node_id: str,
    map_epoch: int,
) -> Mapping[str, object]:
    child = _workflow_state_require_mapping(
        value, pointer, code="ORCHESTRATION_EXPANSION_INVALID"
    )
    _workflow_state_reject_unknown(
        child,
        _workflow_state_expansion_child_fields,
        pointer,
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    missing = sorted(
        _workflow_state_expansion_child_fields - set(child)
    )
    if missing:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion child is missing required fields",
            pointer=pointer,
            details={"fields": missing},
        )
    for field in ("node_instance_id", "repository_id"):
        _workflow_state_require_string(
            child[field],
            f"{pointer}/{field}",
            code="ORCHESTRATION_EXPANSION_INVALID",
            pattern=_workflow_state_stable_id_re,
        )
    if child["node_id"] != template_node_id:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion child does not bind the pinned child node",
            pointer=f"{pointer}/node_id",
            value=child["node_id"],
            details={"expected": template_node_id},
        )
    _workflow_state_require_digest(
        child["repository_identity_sha256"],
        f"{pointer}/repository_identity_sha256",
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    child_epoch = _workflow_state_require_integer(
        child["map_epoch"],
        f"{pointer}/map_epoch",
        code="ORCHESTRATION_EXPANSION_INVALID",
        minimum=1,
    )
    if child_epoch != map_epoch:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion child map epoch differs from its expansion",
            pointer=f"{pointer}/map_epoch",
            value=child_epoch,
            details={"expected": map_epoch},
        )
    _workflow_state_require_string_array(
        (
            list(child["dependencies"])
            if isinstance(child["dependencies"], tuple)
            else child["dependencies"]
        ),
        f"{pointer}/dependencies",
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    return _workflow_state_freeze(child)  # type: ignore[return-value]


def validate_v4_task_state_against_bundle(
    state: object, bundle: object
) -> Mapping[str, object]:
    """Cross-check schema-v4 state against its already resolved bundle.

    This pure boundary consumes only the persisted task and an injected,
    package-validated bundle descriptor.  It performs no file, Git, catalog,
    controller, or global lookup.
    """

    task = validate_v4_task_state(state)
    graph = _workflow_state_bundle_graph(bundle)
    nodes = _workflow_state_bundle_nodes(bundle, graph)
    bundle_flow = graph.get("flow")
    if bundle_flow != task["flow"]:
        raise _workflow_state_error(
            "WORKFLOW_STATE_BUNDLE_MISMATCH",
            "task flow differs from its pinned bundle",
            pointer="/flow",
            value=task["flow"],
            details={"expected": bundle_flow},
        )
    profiles_value = _workflow_state_descriptor_value(
        bundle, "execution_profiles"
    )
    if profiles_value is None:
        profiles_value = graph.get("execution_profiles")
    if not isinstance(profiles_value, (list, tuple)):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "resolved bundle does not expose execution profiles",
        )
    profiles = tuple(profiles_value)
    execution_profile = str(task["execution_profile"])
    if execution_profile not in profiles:
        raise _workflow_state_error(
            "WORKFLOW_STATE_BUNDLE_MISMATCH",
            "task execution profile is absent from its pinned bundle",
            pointer="/execution_profile",
            value=execution_profile,
            details={"supported": list(profiles)},
        )
    metadata = _workflow_state_descriptor_value(
        bundle, "repository_orchestration"
    )
    if metadata is None:
        metadata = graph.get("repository_orchestration")

    task_nodes = task["node_instances"]
    assert isinstance(task_nodes, tuple)
    coarse_by_node: dict[str, list[Mapping[str, object]]] = {}
    dynamic_nodes: dict[str, Mapping[str, object]] = {}
    for index, node in enumerate(task_nodes):
        assert isinstance(node, Mapping)
        node_id = str(node["node_id"])
        repository_id = node.get("repository_id")
        if repository_id is None:
            if node_id not in nodes:
                raise _workflow_state_error(
                    "NODE_INSTANCE_BUNDLE_MISMATCH",
                    "coarse node instance is absent from the pinned bundle",
                    pointer=f"/node_instances/{index}/node_id",
                    value=node_id,
                )
            coarse_by_node.setdefault(node_id, []).append(node)
        else:
            dynamic_nodes[str(node["node_instance_id"])] = node
    duplicate_coarse = sorted(
        node_id
        for node_id, instances in coarse_by_node.items()
        if len(instances) != 1
    )
    if duplicate_coarse:
        raise _workflow_state_error(
            "NODE_INSTANCE_BUNDLE_MISMATCH",
            "coarse bundle nodes cannot be caller-created more than once",
            pointer="/node_instances",
            details={"node_ids": duplicate_coarse},
        )

    if execution_profile == "single-repository":
        if dynamic_nodes:
            raise _workflow_state_error(
                "ORCHESTRATION_STATE_FORBIDDEN",
                "single-repository tasks cannot persist repository orchestration",
                pointer="/orchestration",
            )
        if "orchestration" in task:
            authority_state = task["orchestration"]
            authority_state = _workflow_state_require_mapping(
                authority_state,
                "/orchestration",
                code="ORCHESTRATION_STATE_INVALID",
            )
            allowed_authority_fields = {
                "schema",
                "manager_capabilities",
            }
            _workflow_state_reject_unknown(
                authority_state,
                allowed_authority_fields,
                "/orchestration",
                code="ORCHESTRATION_STATE_FORBIDDEN",
            )
            missing = sorted(
                allowed_authority_fields - set(authority_state)
            )
            if missing:
                raise _workflow_state_error(
                    "ORCHESTRATION_STATE_INVALID",
                    "single-repository authority state is incomplete",
                    pointer="/orchestration",
                    details={"fields": missing},
                )
            if (
                authority_state["schema"]
                != _workflow_state_orchestration_schema
            ):
                raise _workflow_state_error(
                    "ORCHESTRATION_STATE_INVALID",
                    "persisted orchestration schema is unsupported",
                    pointer="/orchestration/schema",
                    value=authority_state["schema"],
                )
            capabilities = _workflow_state_require_mapping(
                authority_state["manager_capabilities"],
                "/orchestration/manager_capabilities",
                code="ORCHESTRATION_STATE_INVALID",
            )
            for capability_id, verifier in capabilities.items():
                _workflow_state_require_string(
                    capability_id,
                    (
                        "/orchestration/manager_capabilities/"
                        f"{capability_id}"
                    ),
                    code="ORCHESTRATION_STATE_INVALID",
                    pattern=_workflow_state_stable_id_re,
                )
                _workflow_state_require_mapping(
                    verifier,
                    (
                        "/orchestration/manager_capabilities/"
                        f"{capability_id}"
                    ),
                    code="ORCHESTRATION_STATE_INVALID",
                )
        return task
    if not isinstance(metadata, Mapping):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "multi-repository bundle lacks orchestration metadata",
        )
    map_value = metadata.get("map")
    join_value = metadata.get("join")
    if not isinstance(map_value, Mapping) or not isinstance(
        join_value, Mapping
    ):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "multi-repository bundle orchestration metadata is incomplete",
        )
    child_template = map_value.get("child_template")
    if not isinstance(child_template, Mapping):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "multi-repository bundle has no child template binding",
        )
    template_id = child_template.get("template_id")
    template_node_id = child_template.get("node_id")
    map_parent_node_id = map_value.get("parent_node_id")
    join_node_id = join_value.get("node_id")
    if not all(
        isinstance(item, str)
        for item in (
            template_id,
            template_node_id,
            map_parent_node_id,
            join_node_id,
        )
    ):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "multi-repository bundle node bindings are invalid",
        )
    missing_coarse = sorted(
        {
            str(map_parent_node_id),
            str(join_node_id),
        }
        - set(coarse_by_node)
    )
    if missing_coarse:
        raise _workflow_state_error(
            "NODE_INSTANCE_BUNDLE_MISMATCH",
            "multi-repository task lacks its pinned map or join node",
            pointer="/node_instances",
            details={"node_ids": missing_coarse},
        )

    orchestration = _workflow_state_require_mapping(
        task.get("orchestration"),
        "/orchestration",
        code="ORCHESTRATION_STATE_REQUIRED",
    )
    if orchestration.get("schema") != _workflow_state_orchestration_schema:
        raise _workflow_state_error(
            "ORCHESTRATION_STATE_INVALID",
            "persisted orchestration schema is unsupported",
            pointer="/orchestration/schema",
            value=orchestration.get("schema"),
        )
    if "expansion" not in orchestration:
        raise _workflow_state_error(
            "ORCHESTRATION_STATE_INVALID",
            "persisted orchestration state must declare its map expansion",
            pointer="/orchestration",
            details={"fields": ["expansion"]},
        )
    expansion_value = orchestration["expansion"]
    if expansion_value is None:
        if dynamic_nodes:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_REQUIRED",
                "repository child instances require a persisted expansion",
                pointer="/orchestration/expansion",
            )
        return task

    expansion = _workflow_state_require_mapping(
        expansion_value,
        "/orchestration/expansion",
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    _workflow_state_reject_unknown(
        expansion,
        _workflow_state_expansion_fields,
        "/orchestration/expansion",
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    missing = sorted(
        _workflow_state_expansion_required_fields - set(expansion)
    )
    if missing:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "persisted repository expansion is missing required fields",
            pointer="/orchestration/expansion",
            details={"fields": missing},
        )
    if expansion["schema"] != _workflow_state_map_expansion_schema:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "persisted repository expansion schema is unsupported",
            pointer="/orchestration/expansion/schema",
            value=expansion["schema"],
        )
    expected_values = {
        "task_id": task["task_id"],
        "workflow_bundle_sha256": task["workflow_ref"][
            "bundle_sha256"
        ],
        "map_node_id": template_id,
    }
    for field, expected in expected_values.items():
        if expansion[field] != expected:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_MISMATCH",
                "persisted repository expansion differs from pinned task identity",
                pointer=f"/orchestration/expansion/{field}",
                value=expansion[field],
                details={"expected": expected},
            )
    for field in ("dag_sha256", "semantic_input_sha256"):
        _workflow_state_require_digest(
            expansion[field],
            f"/orchestration/expansion/{field}",
            code="ORCHESTRATION_EXPANSION_INVALID",
        )
    _workflow_state_require_string(
        expansion["plan_id"],
        "/orchestration/expansion/plan_id",
        code="ORCHESTRATION_EXPANSION_INVALID",
        pattern=_workflow_state_stable_id_re,
    )
    map_epoch = _workflow_state_require_integer(
        expansion["map_epoch"],
        "/orchestration/expansion/map_epoch",
        code="ORCHESTRATION_EXPANSION_INVALID",
        minimum=1,
    )
    current = expansion.get("current", True)
    if not isinstance(current, bool):
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion currentness must be boolean",
            pointer="/orchestration/expansion/current",
            value=current,
        )
    stale_fields = {
        "stale_reason",
        "stale_at_revision",
        "stale_facts_sha256",
        "minimum_successor_map_epoch",
    }
    if current:
        unexpected_stale = sorted(
            stale_fields.union({"retired_at_revision"})
            & set(expansion)
        )
        if unexpected_stale:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_INVALID",
                "a current expansion cannot carry stale-generation facts",
                pointer="/orchestration/expansion",
                details={"fields": unexpected_stale},
            )
    else:
        missing_stale = sorted(stale_fields - set(expansion))
        if missing_stale:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_INVALID",
                "a stale expansion must persist its invalidation facts",
                pointer="/orchestration/expansion",
                details={"fields": missing_stale},
            )
        _workflow_state_require_string(
            expansion["stale_reason"],
            "/orchestration/expansion/stale_reason",
            code="ORCHESTRATION_EXPANSION_INVALID",
        )
        stale_revision = _workflow_state_require_integer(
            expansion["stale_at_revision"],
            "/orchestration/expansion/stale_at_revision",
            code="ORCHESTRATION_EXPANSION_INVALID",
            minimum=1,
        )
        _workflow_state_require_digest(
            expansion["stale_facts_sha256"],
            "/orchestration/expansion/stale_facts_sha256",
            code="ORCHESTRATION_EXPANSION_INVALID",
        )
        minimum_successor = _workflow_state_require_integer(
            expansion["minimum_successor_map_epoch"],
            "/orchestration/expansion/minimum_successor_map_epoch",
            code="ORCHESTRATION_EXPANSION_INVALID",
            minimum=map_epoch + 1,
        )
        if minimum_successor <= map_epoch:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_INVALID",
                "successor map epoch must be strictly newer than the stale generation",
                pointer=(
                    "/orchestration/expansion/"
                    "minimum_successor_map_epoch"
                ),
            )
        if "retired_at_revision" in expansion:
            retired_revision = _workflow_state_require_integer(
                expansion["retired_at_revision"],
                "/orchestration/expansion/retired_at_revision",
                code="ORCHESTRATION_EXPANSION_INVALID",
                minimum=stale_revision,
            )
            if retired_revision < stale_revision:
                raise _workflow_state_error(
                    "ORCHESTRATION_EXPANSION_INVALID",
                    "retirement cannot predate stale generation",
                    pointer=(
                        "/orchestration/expansion/"
                        "retired_at_revision"
                    ),
                )
    repository_set = _workflow_state_require_string_array(
        (
            list(expansion["repository_set"])
            if isinstance(expansion["repository_set"], tuple)
            else expansion["repository_set"]
        ),
        "/orchestration/expansion/repository_set",
        code="ORCHESTRATION_EXPANSION_INVALID",
    )
    children_value = expansion["children"]
    if not isinstance(children_value, (list, tuple)):
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion children must be an array",
            pointer="/orchestration/expansion/children",
        )
    children: dict[str, Mapping[str, object]] = {}
    child_repository_ids: list[str] = []
    for index, child_value in enumerate(children_value):
        child = _workflow_state_validate_expansion_child(
            child_value,
            f"/orchestration/expansion/children/{index}",
            template_node_id=str(template_node_id),
            map_epoch=map_epoch,
        )
        child_id = str(child["node_instance_id"])
        if child_id in children:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_INVALID",
                "repository expansion child identities must be unique",
                pointer="/orchestration/expansion/children",
                value=child_id,
            )
        children[child_id] = child
        child_repository_ids.append(str(child["repository_id"]))
    if tuple(child_repository_ids) != repository_set:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_MISMATCH",
            "repository expansion children must exactly match its repository set",
            pointer="/orchestration/expansion/children",
            details={
                "expected": list(repository_set),
                "actual": child_repository_ids,
            },
        )
    unknown_dependencies = sorted(
        {
            str(dependency)
            for child in children.values()
            for dependency in child["dependencies"]
        }
        - set(children)
    )
    if unknown_dependencies:
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_INVALID",
            "repository expansion dependencies must reference map children",
            pointer="/orchestration/expansion/children",
            details={"dependencies": unknown_dependencies},
        )
    historical_nodes = set(dynamic_nodes) - set(children)
    invalid_historical = sorted(
        identifier
        for identifier in historical_nodes
        if dynamic_nodes[identifier].get("state") != "SKIPPED"
    )
    if (
        not set(children).issubset(dynamic_nodes)
        or invalid_historical
    ):
        raise _workflow_state_error(
            "ORCHESTRATION_EXPANSION_MISMATCH",
            "dynamic repository nodes must match the current expansion or be retired",
            pointer="/node_instances",
            details={
                "missing": sorted(set(children) - set(dynamic_nodes)),
                "unexpected": sorted(historical_nodes),
                "non_retired": invalid_historical,
            },
        )
    for node_instance_id, child in children.items():
        node = dynamic_nodes[node_instance_id]
        projection = {
            "node_id": node["node_id"],
            "repository_id": node["repository_id"],
            "dependencies": tuple(node["dependencies"]),
        }
        expected_projection = {
            "node_id": child["node_id"],
            "repository_id": child["repository_id"],
            "dependencies": tuple(child["dependencies"]),
        }
        if projection != expected_projection:
            raise _workflow_state_error(
                "ORCHESTRATION_EXPANSION_MISMATCH",
                "dynamic repository node differs from its expansion child",
                pointer="/node_instances",
                details={"node_instance_id": node_instance_id},
            )
    return task


def _workflow_state_schema_version(state: object) -> object:
    if not isinstance(state, Mapping):
        return None
    return state.get("schema_version")


def _workflow_state_resolver_lookup(
    resolver: object,
    key: object,
    *,
    alternate_key: object | None,
    call_arguments: tuple[object, ...],
    resolver_name: str,
    missing_code: str,
) -> object:
    try:
        if isinstance(resolver, Mapping):
            if key in resolver:
                return resolver[key]
            if alternate_key is not None and alternate_key in resolver:
                return resolver[alternate_key]
            raise WorkflowStateError(
                missing_code,
                "injected workflow resolver has no exact task match",
                details={"resolver": resolver_name, "key": key},
            )
        if callable(resolver):
            return resolver(*call_arguments)
    except WorkflowStateError:
        raise
    except Exception as exc:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_FAILED",
            "injected workflow resolver could not resolve the task",
            details={
                "resolver": resolver_name,
                "key": key,
                "error": str(exc),
            },
        ) from exc
    raise WorkflowStateError(
        "WORKFLOW_RESOLUTION_REQUIRED",
        "workflow resolution requires an injected callable or mapping",
        details={"resolver": resolver_name},
    )


def _workflow_state_descriptor_value(
    descriptor: object, *names: str
) -> object:
    for name in names:
        if isinstance(descriptor, Mapping) and name in descriptor:
            return descriptor[name]
        if hasattr(descriptor, name):
            return getattr(descriptor, name)
    return None


def _workflow_state_resolution_descriptor(
    *,
    kind: str,
    schema_version: int,
    flow: str,
    descriptor: object,
    workflow_ref: Mapping[str, object] | None,
) -> Mapping[str, object]:
    if isinstance(descriptor, (list, tuple, set, frozenset)):
        if len(descriptor) != 1:
            raise WorkflowStateError(
                "WORKFLOW_RESOLUTION_AMBIGUOUS",
                "workflow resolver returned an ambiguous definition set",
                details={"matches": len(descriptor)},
            )
        descriptor = next(iter(descriptor))
    if descriptor is None:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_FAILED",
            "workflow resolver returned no matching definition",
            details={"schema_version": schema_version, "flow": flow},
        )
    result: dict[str, object] = {
        "kind": kind,
        "supported": True,
        "schema_version": schema_version,
        "flow": flow,
    }
    if workflow_ref is None:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "V4 resolution requires an exact workflow reference",
        )
    result.update(workflow_ref)
    return MappingProxyType(result)


def _workflow_state_verify_bundle_resolution(
    descriptor: object, workflow_ref: Mapping[str, object]
) -> None:
    graph = _workflow_state_descriptor_value(descriptor, "graph")
    resolved = {
        "id": _workflow_state_descriptor_value(
            descriptor, "id", "workflow_id"
        ),
        "version": _workflow_state_descriptor_value(
            descriptor, "version", "workflow_version"
        ),
        "graph_sha256": _workflow_state_descriptor_value(
            descriptor, "graph_sha256"
        ),
        "bundle_sha256": _workflow_state_descriptor_value(
            descriptor, "bundle_sha256"
        ),
    }
    resolved_schema = _workflow_state_descriptor_value(descriptor, "schema")
    if resolved_schema is None and isinstance(graph, Mapping):
        resolved_schema = graph.get("schema")
    resolved["schema"] = resolved_schema
    missing = sorted(field for field, value in resolved.items() if value is None)
    if missing:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_INVALID",
            "bundle resolver result lacks pinned identity fields",
            details={"fields": missing},
        )
    mismatches = {
        field: {"expected": workflow_ref[field], "actual": value}
        for field, value in resolved.items()
        if value != workflow_ref[field]
    }
    if mismatches:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_MISMATCH",
            "resolved bundle does not match the task-pinned identity",
            details={"mismatches": mismatches},
        )


def resolve_task_workflow(
    state: object,
    *,
    bundle_resolver: object,
    purpose: str,
) -> Mapping[str, object]:
    """Resolve one immutable workflow descriptor without changing task state."""

    if purpose not in _workflow_state_resolution_purposes:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_PURPOSE_INVALID",
            "workflow resolution purpose is unsupported",
            details={
                "purpose": purpose,
                "supported": sorted(_workflow_state_resolution_purposes),
            },
        )
    schema_version = _workflow_state_schema_version(state)
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_TASK_SCHEMA_VERSIONS
    ):
        raise WorkflowStateError(
            "TASK_SCHEMA_UNSUPPORTED",
            "task schema is not the current V4 schema",
            details={
                "schema_version": schema_version,
                "supported_schema_versions": sorted(
                    SUPPORTED_TASK_SCHEMA_VERSIONS
                ),
            },
        )
    task = validate_v4_task_state(state)
    workflow_ref = task["workflow_ref"]
    descriptor = _workflow_state_resolver_lookup(
        bundle_resolver,
        (
            workflow_ref["id"],
            workflow_ref["version"],
            workflow_ref["bundle_sha256"],
        ),
        alternate_key=workflow_ref["bundle_sha256"],
        call_arguments=(workflow_ref,),
        resolver_name="bundle",
        missing_code="WORKFLOW_RESOLUTION_FAILED",
    )
    _workflow_state_verify_bundle_resolution(descriptor, workflow_ref)
    validate_v4_task_state_against_bundle(state, descriptor)
    return _workflow_state_resolution_descriptor(
        kind="bundle",
        schema_version=V4_TASK_SCHEMA_VERSION,
        flow=str(task["flow"]),
        descriptor=descriptor,
        workflow_ref=workflow_ref,
    )


def validate_task_state_for_mutation(
    state: object,
    *,
    resolver: Callable[..., Mapping[str, object]],
) -> Mapping[str, object]:
    """Validate supported state and fail closed on unresolved workflow truth."""

    schema_version = _workflow_state_schema_version(state)
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_TASK_SCHEMA_VERSIONS
    ):
        raise WorkflowStateError(
            "TASK_SCHEMA_UNSUPPORTED",
            "task schema is unsupported for mutation",
            details={
                "schema_version": schema_version,
                "supported_schema_versions": sorted(
                    SUPPORTED_TASK_SCHEMA_VERSIONS
                ),
            },
        )
    validate_v4_task_state(state)
    if not callable(resolver):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_REQUIRED",
            "mutation validation requires an injected workflow resolver",
        )
    try:
        resolution = resolver(state, purpose="mutation")
    except WorkflowStateError:
        raise
    except Exception as exc:
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_FAILED",
            "injected workflow resolver failed during mutation validation",
            details={"error": str(exc)},
        ) from exc
    if (
        not isinstance(resolution, Mapping)
        or resolution.get("supported") is not True
    ):
        raise WorkflowStateError(
            "WORKFLOW_RESOLUTION_FAILED",
            "mutation validation did not resolve a supported workflow",
        )
    return resolution


def inspect_task_state(
    state: object,
    *,
    resolver: Callable[..., Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Return a tolerant, non-mutating inspection of any task-state value."""

    schema_version = _workflow_state_schema_version(state)
    result: dict[str, object] = {
        "schema_version": schema_version,
        "supported": (
            isinstance(schema_version, int)
            and not isinstance(schema_version, bool)
            and schema_version in SUPPORTED_TASK_SCHEMA_VERSIONS
        ),
        "valid": False,
        "mutation_ready": False,
        "task_id": state.get("task_id") if isinstance(state, Mapping) else None,
        "workflow_ref": _workflow_state_freeze(
            state.get("workflow_ref")
            if isinstance(state, Mapping)
            else None
        ),
        "workflow": None,
        "errors": [],
    }
    errors: list[dict[str, object]] = result["errors"]  # type: ignore[assignment]
    if not result["supported"]:
        errors.append(
            WorkflowStateError(
                "TASK_SCHEMA_UNSUPPORTED",
                "task schema is not supported by this controller",
                details={
                    "schema_version": schema_version,
                    "supported_schema_versions": sorted(
                        SUPPORTED_TASK_SCHEMA_VERSIONS
                    ),
                },
            ).as_dict()
        )
        return result
    try:
        validate_v4_task_state(state)
        result["valid"] = True
    except WorkflowStateError as exc:
        errors.append(exc.as_dict())
        return result
    if resolver is None:
        return result
    try:
        workflow = resolver(state, purpose="inspection")
        if not isinstance(workflow, Mapping):
            raise WorkflowStateError(
                "WORKFLOW_RESOLUTION_FAILED",
                "inspection resolver returned an invalid descriptor",
            )
        result["workflow"] = workflow
        result["mutation_ready"] = workflow.get("supported") is True
    except WorkflowStateError as exc:
        errors.append(exc.as_dict())
    except Exception as exc:
        errors.append(
            WorkflowStateError(
                "WORKFLOW_RESOLUTION_FAILED",
                "inspection resolver failed",
                details={"error": str(exc)},
            ).as_dict()
        )
    return result


__all__ = [
    "SUPPORTED_TASK_SCHEMA_VERSIONS",
    "V4_TASK_SCHEMA_VERSION",
    "WorkflowStateError",
    "inspect_task_state",
    "resolve_task_workflow",
    "validate_task_state_for_mutation",
    "validate_v4_task_state",
    "validate_v4_task_state_against_bundle",
    "validate_workflow_ref",
]
